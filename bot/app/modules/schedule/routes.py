"""Журнал клиники: панель дня, неделя, день врача, ручная запись, заметки,
статусы, выгрузка CSV.

Сюда же попала главная страница `/admin`: она на девять десятых состоит из того
же дня — сетка, свободные слоты, свежие записи из бота. Отдельный модуль
«дашборд» пришлось бы кормить теми же `_day_canvas` и `_slot_modal`, то есть
один модуль импортировал бы другой. Дробить имеет смысл, когда дробится и
содержимое, а не только адрес.

Правило то же, что у пациентов: сюда можно смотреть в `core`, `db` и `engine`,
и нельзя — в `main.py`.
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import urllib.parse
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ... import db
from ... import engine as eng
from ...core.auth import PERM_DOCTORS, _guard, can, request_user
from ...core import xlsx
from ...core.charts import spark as _spark
from ...core.layout import (LIVE_STATUSES, STATUS_LABEL, _age, _banner, _ic,
                            _initials, _shell, _tg_state, js_json, tg_configured)
from ...core.visits import (SVC_PALETTE, _DOC_HUES, _STATUS_ICON, _card_modal,
                            _collect_cards, _list, _move_attrs, _move_modal,
                            _parse_date, _photo_path)

router = APIRouter()


def _date_nav(d: date, base: str, extra: str = "") -> str:
    prev_d, next_d = d - timedelta(days=1), d + timedelta(days=1)
    wk_prev, wk_next = d - timedelta(days=7), d + timedelta(days=7)
    lbl = eng.day_label(eng.Session(lang="ro"), d)
    picker = (f"<form class='dpickf' method='get' action='{base}'>"
              f"<input class='dpick' type='date' name='date' value='{d.isoformat()}' "
              f"onchange='this.form.submit()' title='Alege data (calendar)'></form>")
    # ⚠️ Дата ОДИН раз. До 08-11 тут стояло `{lbl} {d.isoformat()}`, то есть
    # «Ma 11.08 2026-08-11» — один и тот же день двумя записями подряд и без
    # разделителя, а следом поле выбора рисует его же третий раз («11.08.2026»).
    # Год берётся из `d.year`, а не из ISO: day_label даёт только день с месяцем,
    # и без года шапка не сказала бы, какой это август.
    return (f"<div class='nav'><b>{lbl}.{d.year}</b>"
            f"<a href='{base}?date={wk_prev.isoformat()}' title='-7 zile'>{_ic('chevs-l')}</a>"
            f"<a href='{base}?date={prev_d.isoformat()}'>{_ic('chev-l')} {prev_d.strftime('%d.%m')}</a>"
            f"<a href='{base}'>Azi</a>"
            f"<a href='{base}?date={next_d.isoformat()}'>{next_d.strftime('%d.%m')} {_ic('chev-r')}</a>"
            f"<a href='{base}?date={wk_next.isoformat()}' title='+7 zile'>{_ic('chevs-r')}</a>"
            f"{picker}{extra}</div>")


def _grid(d: date, doctors_items: list, active: dict, href_fn,
          cards: dict | None = None) -> str:
    starts, covered = active
    # ⚠️ Ряды — НЕПРЕРЫВНЫЙ диапазон часов, а не только открытые (08-12).
    # `day_slots` выбрасывает обеденный час совсем, и в таблице 12:00 сменялось
    # на 14:00 без единого следа паузы, тогда как канва панели дня показывает её
    # штриховкой: две страницы про один и тот же день говорили разное.
    # ⛔ Хуже была вторая половина: запись, оказавшаяся в ЗАКРЫТОМ часу (обед
    # или график поменяли ПОСЛЕ брони), исчезала из сетки целиком — час не
    # рисовался, значит и `starts` по нему никто не спрашивал. В списке дня и на
    # канве визит есть, здесь его нет. Отсюда часы записей в диапазоне наравне с
    # рабочими — ровно так же, как это делает `_day_canvas`.
    open_h = {x.hour for x in eng.day_slots(d)}
    known = sorted(open_h | {h for _k, h in starts} | {h for _k, h in covered})
    hours = list(range(known[0], known[-1] + 1)) if known else []
    # закрытый час называет СЕБЯ: обед клиники — «pauză», всё остальное —
    # «închis» (день ещё не начался / уже кончился, а запись тут есть)
    _hf = eng.hours_for(d)
    br_f, br_t = (int(_hf[2]), int(_hf[3])) if _hf and len(_hf) >= 4 else (0, 0)
    # Текущий час подсвечивается ТОЛЬКО на сегодняшнем дне. Отдельной линии
    # «сейчас» поперёк сетки здесь нет намеренно: таблица — не холст, линию
    # пришлось бы позиционировать поверх строк, и она разъезжалась бы с ними
    # при любой ширине. Подсветка строки отвечает на тот же вопрос («где мы
    # сейчас») и не может разъехаться, потому что она и есть строка.
    now = datetime.now(eng.TZ)
    now_hour = now.hour if now.date() == d else None
    out = ["<div class='gridwrap'><table class='grid'><tr><th class='gh-t'></th>"]
    for dk, name in doctors_items:
        spec = eng.DOCTOR_SPEC.get(dk, "")
        if not eng.DOCTOR_META.get(dk, {}).get("active", True):
            spec = (spec + " · inactiv").strip(" ·")
        out.append(f"<th><a class='dh-n' href='/admin/doctor/{dk}?date={d.isoformat()}'>"
                   f"{html.escape(name)}</a>"
                   f"<span class='dh-s'>{html.escape(spec)}</span></th>")
    out.append("</tr>")
    # ⭐ «Принимает ли ЭТОТ врач в ЭТОТ час» — один ответ на обе дневные
    # страницы (eng.doctor_hours). Он же закрывает три случая разом: обед и
    # закрытые часы клиники, суженные часы врача в его фише и выключенного
    # врача, которому /admin/add всё равно ответит `bad_off`. Прежний набор
    # `off` знал только про последний, и таблица предлагала «+» там, где канва
    # рисовала штриховку.
    work = {dk: eng.doctor_hours(dk, d) for dk, _n in doctors_items}
    for h in hours:
        nowcls = " now" if h == now_hour else ""
        closed = h not in open_h
        note = (f"<small>{'pauză' if br_f <= h < br_t else 'închis'}</small>"
                if closed else "")
        out.append(f"<tr class='hrow{' off' if closed else ''}{nowcls}'>"
                   f"<td class='hour{' off' if closed else ''}{nowcls}'>"
                   f"{h:02d}:00{note}</td>")
        for dk, dname in doctors_items:
            rs = starts.get((dk, h)) or starts.get((dname, h)) or []
            # приёмный час = мишень для перетаскивания, ЗАНЯТ он или нет:
            # в 10:00 стоит визит, а 10:30 у того же часа свободно, и отказать
            # в половине часа только потому, что ячейка не пуста, нельзя
            drop = (f" data-dk='{html.escape(dk, quote=True)}' data-h='{h}'"
                    if h in work.get(dk, set()) else "")
            if not rs:
                if (dk, h) in covered or (dname, h) in covered:
                    # час накрыт длинным визитом — «+» тут врал бы
                    out.append(f"<td{drop}><div class='appt busy'>"
                               f"{_ic('hourglass')} ocupat</div></td>")
                elif h not in work.get(dk, set()):
                    # врач не принимает: «+» тут врал бы так же, как в обед —
                    # запись либо отобьётся, либо назначит визит в пустой кабинет
                    out.append("<td class='goff'></td>")
                else:
                    args = html.escape(json.dumps([dk, dname, f"{h:02d}:00"]), quote=True)
                    out.append(
                        f"<td{drop}><a class='free' href='{href_fn(dk, h)}' "
                        f"onclick=\"openSlot.apply(null,{args});return false\">+</a></td>")
                continue
            cell = []
            for r in rs:   # в часе может быть две записи (10:00 и 10:30)
                stl = r["starts_at"].astimezone(eng.TZ)
                hhmm = stl.strftime("%H:%M")
                dur = int(r.get("duration_min") or 60)
                if r["source"] == "note":
                    cell.append(f"<div class='appt note' data-appt='{r['id']}'"
                                f"{_move_attrs(r, dk, stl)}>"
                                f"{_ic('note')} {hhmm} {html.escape(r['service'])}</div>")
                    continue
                src = _ic("bot") if r["source"] == "bot" else _ic("pen")
                urgent = r["service"] in eng.URGENT_LABELS
                cls = r["status"] + (" urgent" if urgent else "")
                svc_txt = (_ic("sos") + " " if urgent else "") + html.escape(r["service"])
                click = ""
                if cards is not None and r["id"] in cards:
                    cls += " clickable"
                    click = f" onclick=\"openCard({r['id']})\""
                cmt = (f"<div class='cmt'>{_ic('chat')} {html.escape((r['comment'] or '')[:60])}</div>"
                       if r["comment"] else "")
                a = _age(r["birth_year"])
                age_txt = f" <small style='color:#889'>{a} a.</small>" if a else ""
                # ⚠️ Значок статуса тот же и на том же месте, что в блоке канвы
                # (_day_canvas): до 08-12 «Finalizat» помечал запись ТОЛЬКО на
                # панели дня, а в сетке «Programări» менялся один фон — на
                # голубом «выполнено» и сером «отменено» это разница, которую
                # регистратура не видит, пока не откроет карточку.
                sic = (f"<span class='stt'>{_STATUS_ICON[r['status']]}</span>"
                       if r["status"] in _STATUS_ICON else "")
                # 08-13, просьба Олега: статус — СЛОВОМ на самой карточке, тем
                # же бейджем, что в списке дня (.stat s-*), а не только цветом
                # фона. confirmed — базовое состояние: его бейдж на каждой
                # зелёной карточке был бы шумом, который прячет остальные.
                stw = (f"<div class='stw'><span class='stat s-{r['status']}'>"
                       f"{_STATUS_ICON.get(r['status'], '')}"
                       f"{STATUS_LABEL.get(r['status'], r['status'])}</span></div>"
                       if r["status"] != "confirmed" else "")
                cell.append(
                    f"<div class='appt {cls}' data-appt='{r['id']}'"
                    f"{_move_attrs(r, dk, stl)}{click}>"
                    f"<b>{sic}{hhmm} · {html.escape(r['name'] or '—')}</b>"
                    f"{age_txt} {src}<br>{svc_txt} <small>({dur}′)</small>"
                    f"<br><small>{html.escape(r['phone'] or '')}</small>{stw}{cmt}</div>")
            # мишень переноса и у ЗАНЯТОЙ ячейки — ровно то, что обещает
            # комментарий у drop выше: в 10:00 стоит визит, а 10:30 свободно
            out.append(f"<td{drop}>" + "".join(cell) + "</td>")
        out.append("</tr>")
    out.append("</table></div>")
    # ⚠️ Подсказка обязана быть и здесь. Перетаскивание ничем себя не выдаёт:
    # ни курсора-подсказки на пустом месте, ни кнопки. На панели дня про него
    # написано под канвой — таблица без своей строки выглядела бы страницей,
    # где переносить нельзя, хотя можно ровно так же.
    out.append("<p class='hint'>Trageți o programare pentru a o muta la altă "
               "oră sau alt medic; click pe «+» — programare nouă sau notiță.</p>")
    return "".join(out)


def _form(d: date, doctors_items: list, sel_doctor: str, sel_time: str, back: str) -> str:
    # 30-мин шаг (v1.8.0), но только те старты, где помещается минимум 30 минут
    # приёма внутри рабочего окна клиники (не предлагаем 17:30 при закрытии в 18)
    def _starts(fits) -> list[str]:
        out = []
        for x in eng.day_slots(d):
            for m in (0, 30):
                st = x.replace(minute=m)
                if fits(st):
                    out.append(st.strftime("%H:%M"))
        return out

    half = _starts(lambda st: eng.fits_clinic(st, 30))
    # ⭐ Часы ВРАЧА, а не только клиники. /admin/add отказывает `outside_doc` по
    # личному графику (work_from/work_to), и список, знающий одну лишь клинику,
    # предлагал 15:00 утреннему врачу — форма подсказывала час, который сервер
    # тут же отвергал. Окна те же, из которых free_starts берёт слоты.
    # ⚠️ Пустой список (у врача в этот день окна нет) заменяется часами клиники:
    # <select> без единого option не отправил бы поле вовсе, и вместо внятного
    # «Medicul nu lucrează la ora aleasă» вышла бы ошибка разбора формы.
    doc_times = {dk: _starts(lambda st, k=dk: eng.fits_doctor(k, st, 30)) or half
                 for dk, _n in doctors_items}
    cur_doc = (sel_doctor if sel_doctor in doc_times
               else (doctors_items[0][0] if doctors_items else ""))
    time_opts = "".join(
        f"<option value='{t}'{' selected' if sel_time == t else ''}>{t}</option>"
        for t in doc_times.get(cur_doc, half)
    )
    if len(doctors_items) == 1:
        dk, dn = doctors_items[0]
        doc_field = (f"<input type='hidden' name='adoctor' value='{dk}'>"
                     f"<b>{html.escape(dn)}</b>")
    else:
        doc_opts = "".join(
            f"<option value='{dk}'{' selected' if sel_doctor == dk else ''}>{html.escape(dn)}</option>"
            for dk, dn in doctors_items
        )
        doc_field = f"<select name='adoctor'>{doc_opts}</select>"
    svc_opts = "".join(
        f"<option value='{k}'>{html.escape(v['ro'])}</option>" for k, v in eng.SERVICES.items()
    )
    # Врача в этой форме меняют без перезагрузки, поэтому список часов
    # переписывается на месте — данные для этого печатаются в саму страницу
    # (panel.js данных из Python не знает намеренно, см. его шапку).
    doc_js = "" if len(doctors_items) < 2 else f"""
<script>
const DOC_TIMES = {js_json(doc_times)};
(function () {{
  const f = document.querySelector('form.add');
  if (!f) return;
  const doc = f.querySelector('[name=adoctor]');
  const tim = f.querySelector('[name=atime]');
  if (!doc || !tim) return;
  doc.addEventListener('change', function () {{
    const list = DOC_TIMES[doc.value];
    if (!list || !list.length) return;
    const keep = tim.value;
    tim.innerHTML = '';
    for (const t of list) {{
      const o = document.createElement('option');
      o.value = t;
      o.textContent = t;
      if (t === keep) o.selected = true;
      tim.appendChild(o);
    }}
  }});
}})();
</script>"""
    return f"""
<h2 id="addform">{_ic("pen")} Adaugă programare manual (telefon / recepție)</h2>
<form class="add" method="post" action="/admin/add">
  <input type="hidden" name="back" value="{html.escape(back)}">
  <input type="date" name="adate" value="{d.isoformat()}" required>
  <select name="atime">{time_opts}</select>
  {doc_field}
  <select name="aservice">{svc_opts}</select>
  <input name="aname" placeholder="Nume pacient" required>
  <input name="aphone" placeholder="Telefon" required>
  <label style="display:inline-flex;align-items:center;gap:6px;font-size:12.5px;
    color:var(--text3)">Naștere (opț.)
    <input type="date" name="abirth" max="{date.today().isoformat()}"></label>
  <button>Adaugă</button>
</form>{doc_js}"""


def _slot_modal(d: date, back: str) -> str:
    """Модалка по клику на «+»: записать пациента ИЛИ заметка/блокировка слота."""
    svc_opts = "".join(
        f"<option value='{k}'>{html.escape(v['ro'])}</option>" for k, v in eng.SERVICES.items()
    )
    return f"""
<dialog id="slotdlg">
  <div class="dlg-head"><span id="m_title">—</span>
    <button type="button" onclick="document.getElementById('slotdlg').close()">{_ic('close')}</button></div>
  <div class="dlg-tabs">
    <button type="button" id="tb_a" class="tabbtn on" onclick="showTab('a')">{_ic('user')} Programare</button>
    <button type="button" id="tb_n" class="tabbtn" onclick="showTab('n')">{_ic('note')} Notiță / blocare</button>
  </div>
  <form id="tab_a" class="dlg-form" method="post" action="/admin/add">
    <input type="hidden" name="back" value="{html.escape(back)}">
    <input type="hidden" name="adate" value="{d.isoformat()}">
    <input type="hidden" name="atime" id="m_time_a">
    <input type="hidden" name="adoctor" id="m_doc_a">
    <div class="halfpick" role="group" aria-label="Ora">
      <button type="button" id="hp_00" class="hp on" onclick="pickHalf(0)">—</button>
      <button type="button" id="hp_30" class="hp" onclick="pickHalf(30)">—</button>
    </div>
    <select name="aservice">{svc_opts}</select>
    <input name="aname" placeholder="Nume pacient" required>
    <input name="aphone" placeholder="Telefon" required>
    <label style="font-size:13px;color:#556;display:flex;align-items:center;gap:8px">
      Data nașterii (opț.)
      <input type="date" name="abirth" max="{date.today().isoformat()}" style="flex:1"></label>
    <button>Adaugă programarea</button>
  </form>
  <form id="tab_n" class="dlg-form" method="post" action="/admin/note" style="display:none">
    <input type="hidden" name="back" value="{html.escape(back)}">
    <input type="hidden" name="ndate" value="{d.isoformat()}">
    <input type="hidden" name="ntime" id="m_time_n">
    <input type="hidden" name="ndoctor" id="m_doc_n">
    <input name="ntext" placeholder="ex.: pauză de masă, ședință, rezervat telefonic…" maxlength="120" required>
    <label style="font-size:13px;color:#556;display:flex;align-items:center;gap:8px">până la ora
      <select name="nuntil" id="m_until" style="flex:1"></select></label>
    <button>Salvează notița (blochează orele)</button>
  </form>
</dialog>
<script>
const NOTE_ENDS = {js_json([x.hour + 1 for x in eng.day_slots(d)])};
/* Клик по ячейке — это ЧАС, а запись бывает и на его половину (08-13, Олег):
   раньше 10:30 из модалки было не выбрать вовсе — только нижней формой.
   Выбор получаса меняет ТОЛЬКО время записи (atime) и заголовок; заметка
   (ntime) остаётся почасовой — блокировки живут часами, как и ячейки. */
let SLOT_H = '';
let SLOT_NAME = '';
function pickHalf(mm) {{
  const t = SLOT_H + ':' + (mm ? '30' : '00');
  document.getElementById('m_time_a').value = t;
  document.getElementById('m_title').textContent = SLOT_NAME + ' — ' + t;
  document.getElementById('hp_00').className = 'hp' + (mm ? '' : ' on');
  document.getElementById('hp_30').className = 'hp' + (mm ? ' on' : '');
}}
function openSlot(dk, dname, hh) {{
  document.getElementById('m_doc_a').value = dk;
  document.getElementById('m_doc_n').value = dk;
  document.getElementById('m_time_n').value = hh;
  SLOT_H = hh.split(':')[0];
  SLOT_NAME = dname;
  document.getElementById('hp_00').textContent = SLOT_H + ':00';
  document.getElementById('hp_30').textContent = SLOT_H + ':30';
  pickHalf(0);
  const start = parseInt(hh);
  const sel = document.getElementById('m_until');
  sel.innerHTML = '';
  for (const e of NOTE_ENDS) {{
    if (e > start) {{
      const o = document.createElement('option');
      o.value = e; o.textContent = e + ':00';
      sel.appendChild(o);
    }}
  }}
  showTab('a');
  document.getElementById('slotdlg').showModal();
}}
function showTab(x) {{
  document.getElementById('tab_a').style.display = (x === 'a') ? 'flex' : 'none';
  document.getElementById('tab_n').style.display = (x === 'n') ? 'flex' : 'none';
  document.getElementById('tb_a').className = 'tabbtn' + (x === 'a' ? ' on' : '');
  document.getElementById('tb_n').className = 'tabbtn' + (x === 'n' ? ' on' : '');
}}
</script>"""


def _active_map(rows: list) -> tuple[dict, set]:
    """({(врач, час): [записи]}, {(врач, час) накрытые чужим интервалом}).
    Ключ — стабильный doctor_id (v1.7.1), легаси без id — имя-снапшот.
    Второе множество нужно, чтобы под 90-минутным визитом не рисовать «+»."""
    starts: dict = {}
    covered: set = set()
    for r in rows:
        if r["status"] == "cancelled":
            continue
        did = r.get("doctor_id")
        key = did if did and did in eng.DOCTORS else r["doctor"]
        st = r["starts_at"].astimezone(eng.TZ)
        starts.setdefault((key, st.hour), []).append(r)
        dur = int(r.get("duration_min") or 60)
        end_min = st.hour * 60 + st.minute + dur
        for h in range(st.hour + 1, (end_min + 59) // 60):
            covered.add((key, h))
    return starts, covered


_SVC_CAT = [
    (re.compile(r"urgent|sos|durere|acut", re.I), ("var(--red-soft)", "var(--red)")),
    (re.compile(r"implant|extract|chirur|sinus", re.I), ("var(--blue-soft)", "var(--blue)")),
    (re.compile(r"hyg|igien|airflow|detartraj|fluor", re.I), ("var(--amber-soft)", "var(--amber)")),
    (re.compile(r"whiten|albire|estet|fatet|venir", re.I), ("var(--violet-soft)", "var(--violet)")),
]


def _svc_colors(r) -> tuple[str, str]:
    """(фон, полоса) записи: статус важнее типа; тип — по service_id (v1.7.1),
    для легаси-строк без id — по подписи; явный цвет из конфига важнее эвристики."""
    if r["status"] == "noshow":
        return "var(--red-soft)", "var(--red)"
    label = r["service"]
    if label in eng.URGENT_LABELS:
        return "var(--red-soft)", "var(--red)"
    sid = r.get("service_id")
    if not sid or sid not in eng.SERVICES:
        sid = next((k for k, v in eng.SERVICES.items()
                    if v.get("ro") == label or v.get("ru") == label), None)
    if sid:
        color = eng.SERVICE_COLOR.get(sid)
        if color in SVC_PALETTE:
            return SVC_PALETTE[color]
        key = sid + " " + label
    else:
        key = label
    for rx, colors in _SVC_CAT:
        if rx.search(key):
            return colors
    return "var(--green-soft)", "var(--green)"


_RO_MONTHS = ["Ianuarie", "Februarie", "Martie", "Aprilie", "Mai", "Iunie", "Iulie",
              "August", "Septembrie", "Octombrie", "Noiembrie", "Decembrie"]


def _mini_cal(sel: date, base: str = "/admin") -> str:
    first = sel.replace(day=1)
    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = (first + timedelta(days=32)).replace(day=1)
    start = first - timedelta(days=first.weekday())
    today = datetime.now(eng.TZ).date()
    cells = []
    cur = start
    while cur.month == sel.month or cur <= first or len(cells) % 7 != 0:
        cls = []
        if cur.month != sel.month:
            cls.append("oth")
        if cur == today:
            cls.append("tdy")
        if cur == sel:
            cls.append("seld")
        cells.append(f"<td><a class='{' '.join(cls)}' "
                     f"href='{base}?date={cur.isoformat()}'>{cur.day}</a></td>")
        cur += timedelta(days=1)
    weeks = ["<tr>" + "".join(cells[i:i + 7]) + "</tr>"
             for i in range(0, len(cells), 7)]
    return f"""<div class='mcal'>
  <div class='mhead'><a href='{base}?date={prev_m.isoformat()}'>‹</a>
    <b>{_RO_MONTHS[sel.month - 1]} {sel.year}</b>
    <a href='{base}?date={next_m.isoformat()}'>›</a></div>
  <table><tr><th>Lu</th><th>Ma</th><th>Mi</th><th>Jo</th><th>Vi</th><th>Sâ</th><th>Du</th></tr>
  {''.join(weeks)}</table></div>"""


SPARK_DAYS = 14


# бейдж строки повестки: тот же компонент, что в списке пациентов (.pl-badge) —
# один вид состояния на всю программу, а не свой значок на каждом экране
# Плашка повестки: ЦВЕТ здесь, а ТЕКСТ — из layout.STATUS_LABEL. Своя пара
# «класс + слово» держалась ровно до тех пор, пока слова совпадали: 08-12
# оказалось, что один статус зовут «Finalizat» в повестке, «a venit» в списке
# дня и «finalizată» в летописи пациента — три имени одного состояния на
# соседних экранах.
# waiting — свой класс «wai» (фиолетовый), а не жёлтый «att»: цвет статуса
# обязан совпадать со .stat s-waiting в списке дня — один статус, один цвет
_AG_CLS = {"confirmed": "act", "waiting": "wai", "arrived": "trt",
           "done": "off", "noshow": "bad"}


def _agenda_block(d: date, rows: list, cards: dict, now: datetime) -> str:
    """«Agenda de azi» — тот же день, но списком и по времени.

    Сетка отвечает «кто когда свободен», список — «что дальше». Соседний блок
    «Programări noi din bot» её НЕ заменяет и не заменяется ею: тот отсортирован
    по времени СОЗДАНИЯ и ловит бронь на неделю вперёд, невидимую в дневных
    видах (урок полевого демо 07-31).
    """
    items = sorted((r for r in rows
                    if r["status"] != "cancelled" and r["source"] != "note"),
                   key=lambda r: r["starts_at"])
    if not items:
        return ("<div class='agenda'><div class='ag-h'><b>Agenda zilei</b></div>"
                "<p class='hint' style='margin:0'>— nicio programare —</p></div>")
    out = []
    for r in items:
        st = r["starts_at"].astimezone(eng.TZ)
        end = st + timedelta(minutes=int(r.get("duration_min") or 60))
        urgent = r["service"] in eng.URGENT_LABELS and r["status"] == "confirmed"
        cls, label = (("bad", "Urgent") if urgent else
                      (_AG_CLS.get(r["status"], "off"),
                       STATUS_LABEL.get(r["status"], r["status"]).capitalize()))
        _bg, bar = _svc_colors(r)
        # прошедшее приглушается только на СЕГОДНЯ: в чужом дне «прошло» не
        # значит ничего, а тусклый список читался бы как отменённый
        past = " past" if d == now.date() and end <= now else ""
        click = (f" onclick=\"openCard({r['id']})\"" if r["id"] in cards else "")
        out.append(
            f"<div class='ag-i{past}' data-appt='{r['id']}' "
            f"style='border-left-color:{bar}'{click}>"
            f"<span class='ag-t'>{st.strftime('%H:%M')}</span>"
            f"<div class='ag-b'><b>{html.escape(r['name'] or '—')}</b>"
            f"<small>{html.escape(r['service'])}</small></div>"
            f"<span class='pl-badge {cls}'>{label}</span></div>")
    return (f"<div class='agenda'><div class='ag-h'><b>Agenda zilei</b>"
            f"<span>{len(items)} programări</span></div>"
            f"<div class='ag-l'>{''.join(out)}</div>"
            f"<a class='ag-all' href='/admin/all?date={d.isoformat()}'>"
            f"Vezi toate programările ›</a></div>")


def _day_canvas(d: date, rows: list, cards: dict) -> str:
    """Дневная сетка-канва: колонки врачей, блоки записей цветом по типу, линия «сейчас».
    Показывает ВСЁ не-отменённое: записи вне текущего графика (часы/обед поменяли
    после брони) получают свою строку, переименованные врачи — свою колонку."""
    live = [r for r in rows if r["status"] != "cancelled"]
    sched = [x.hour for x in eng.day_slots(d)]
    row_hours: set[int] = set()
    for r in live:  # и старт, и КОНЕЦ визита — иначе хвост 120′ уходит за сетку
        st = r["starts_at"].astimezone(eng.TZ)
        end_min = st.hour * 60 + st.minute + int(r.get("duration_min") or 60)
        row_hours.add(st.hour)
        row_hours.add(max(st.hour, (end_min - 1) // 60))
    all_hours = sorted(set(sched) | row_hours)
    if not all_hours:
        return "<div class='gridcard' style='padding:28px;text-align:center;color:var(--text3)'>Zi liberă — clinica este închisă</div>"
    # НЕПРЕРЫВНЫЙ диапазон часов (обед = off-строка): время на канве линейно,
    # поэтому блоки могут быть пропорциональны длительности (v1.8.0)
    hours = list(range(all_hours[0], all_hours[-1] + 1))
    idx = {h: i for i, h in enumerate(hours)}
    base_min = hours[0] * 60

    def _pos(r) -> tuple[float, float]:
        """(top, height) в ячейках: старт и длительность в минутах."""
        st = r["starts_at"].astimezone(eng.TZ)
        dur = int(r.get("duration_min") or 60)
        top = (st.hour * 60 + st.minute - base_min) / 60
        return top, max(dur / 60, 0.4)

    def _row_col(r) -> str:
        """Ключ колонки: стабильный doctor_id; легаси без id — снапшот имени."""
        did = r.get("doctor_id")
        if did and did in eng.DOCTORS:
            return f"k:{did}"
        return f"n:{r['doctor']}"

    # группировка коллизий по ПЕРЕСЕЧЕНИЮ интервалов внутри колонки
    by_col: dict = {}
    for r in live:
        by_col.setdefault(_row_col(r), []).append(r)

    def _r_bounds(r) -> tuple[int, int]:
        st = r["starts_at"].astimezone(eng.TZ)
        s_min = st.hour * 60 + st.minute
        return s_min, s_min + int(r.get("duration_min") or 60)

    def _blocks(col_key: str) -> str:
        # ключ врача для перетаскивания: у колонки-сироты (легаси-имя без id)
        # его нет, и она намеренно остаётся неподвижной — см. _move_attrs
        col_dk = col_key[2:] if col_key.startswith("k:") else ""
        rs_all = sorted(by_col.get(col_key, []), key=_r_bounds)
        # кластеры пересекающихся интервалов делят ширину (ничего не прячем)
        clusters: list[list] = []
        for r in rs_all:
            s_min, e_min = _r_bounds(r)
            if clusters and any(_r_bounds(x)[0] < e_min and s_min < _r_bounds(x)[1]
                                for x in clusters[-1]):
                clusters[-1].append(r)
            else:
                clusters.append([r])
        out = []
        for cluster in clusters:
            n = len(cluster)
            for j, r in enumerate(sorted(cluster,
                                         key=lambda x: x["status"] in LIVE_STATUSES)):
                top_c, h_c = _pos(r)
                st = r["starts_at"].astimezone(eng.TZ)
                pos = (f"top:calc({top_c:.3f}*var(--cell) + 2px);"
                       f"height:calc({h_c:.3f}*var(--cell) - 6px);"
                       f"left:calc({j}*(100% - 8px)/{n} + 4px);"
                       f"width:calc((100% - 8px)/{n} - 2px)")
                if r["source"] == "note":
                    out.append(f"<div class='gappt gnote' data-appt='{r['id']}'"
                               f"{_move_attrs(r, col_dk, st)} "
                               f"style='{pos}' "
                               f"title='{html.escape(r['service'][:80])}'>"
                               f"<b>{_ic('note')} {html.escape(r['service'][:40])}</b></div>")
                    continue
                bg, bar = _svc_colors(r)
                ico = _ic("excl") if (r["service"] in eng.URGENT_LABELS
                              and r["status"] == "confirmed") \
                    else _STATUS_ICON.get(r["status"], "")
                src = _ic("bot") if r["source"] == "bot" else _ic("pen")
                ns = " noshow" if r["status"] == "noshow" else ""
                click = f" onclick=\"openCard({r['id']})\"" if r["id"] in cards else ""
                dur = int(r.get("duration_min") or 60)
                # ⚠️ title несёт ВСЁ, что есть в блоке. Он не украшение: у короткой
                # записи fitAppts сжимает текст в строку с многоточием, а у совсем
                # короткой убирает совсем — и тогда подсказка единственное, что
                # отвечает «кто это», не открывая карточку.
                # статус словом — и в title (у сжатой карточки он единственный
                # ответ «что с визитом»), и бейджем на самой карточке; бейдж
                # прячут .slim/.tiny — там нет места и для имени
                st_word = (STATUS_LABEL.get(r["status"], r["status"])
                           if r["status"] != "confirmed" else "")
                tip = html.escape(f"{st.strftime('%H:%M')} · {dur}′ · {r['service']}"
                                  f" · {r['name'] or '—'}"
                                  + (f" · {st_word}" if st_word else ""))
                stw = (f"<small class='stw'><span class='stat s-{r['status']}'>"
                       f"{STATUS_LABEL.get(r['status'], r['status'])}</span></small>"
                       if st_word else "")
                out.append(
                    f"<div class='gappt{ns}' data-appt='{r['id']}'"
                    f"{_move_attrs(r, col_dk, st)} style='{pos};"
                    f"background:{bg};border-left:5px solid {bar}' title='{tip}'{click}>"
                    f"<span class='stt'>{ico}</span>"
                    f"<b>{html.escape(r['name'] or '—')} {src}</b>"
                    f"<small>{st.strftime('%H:%M')} · {dur}′ · {html.escape(r['service'])}</small>"
                    f"{stw}</div>")
        return "".join(out)

    def _cells(dk: str | None, name: str) -> str:
        # рабочие часы КОНКРЕТНОГО врача (сужение work_from/work_to, v1.8.0).
        # Формула живёт в eng.doctor_hours — её же спрашивает таблица
        # «Programări», иначе две страницы разойдутся в том, где можно писать
        # (08-12). Колонка-сирота (dk=None) не принимает: врача с таким именем
        # в списке уже нет, писать ему некуда.
        work = eng.doctor_hours(dk, d) if dk is not None else set()
        out = []
        for h in hours:
            if dk is not None and h in work:
                # json+escape: имя врача с апострофом не ломает JS-обработчик
                args = html.escape(json.dumps([dk, name, f"{h:02d}:00"]), quote=True)
                # data-h: та же ячейка принимает и клик (новая запись), и
                # перетащенный визит. Закрытая (.off) не принимает ни того, ни
                # другого — «куда нельзя записать, туда нельзя и перенести».
                out.append(f"<div class='gcell' data-h='{h}' "
                           f"onclick=\"openSlot.apply(null,{args})\"></div>")
            else:
                out.append("<div class='gcell off'></div>")
        return "".join(out)

    def _free_hour(dk: str, col_key: str) -> int | None:
        """Первый рабочий час врача без пересечений с его занятыми интервалами."""
        b = eng.doctor_bounds(dk, d)
        if not b:
            return None
        f_h, to_h, bf_h, bt_h = b
        taken = [_r_bounds(r) for r in by_col.get(col_key, [])]
        for h in range(f_h, to_h):
            if bf_h <= h < bt_h:
                continue
            if not any(s < (h + 1) * 60 and h * 60 < e for s, e in taken):
                return h
        return None

    # выключенный врач исчезает из расписания; если на этот день у него ещё
    # остались записи — колонка держится с пометкой «inactiv», пока их не разберут
    shown = [(dk, name) for dk, name in eng.DOCTORS.items()
             if eng.DOCTOR_META.get(dk, {}).get("active", True)
             or by_col.get(f"k:{dk}")]

    # ---- крайние ПОЛНОСТЬЮ закрытые часы — полоской, а не рядом (08-11) ----
    # Час, закрытый у ВСЕХ колонок и без единой записи, не сообщает ничего, кроме
    # «клиника закрыта», а стоит целый ряд var(--cell). Полоска в 10px говорит то
    # же самое: граница дня видна, а часы читаются в подсказке. На дне из 11 рядов
    # с двумя закрытыми краями это отдаёт 2×56 − 2×10 = 92px.
    # ⚠️ Срезаются ТОЛЬКО края. Закрытый час в СЕРЕДИНЕ — это обед, и он обязан
    # остаться рядом: время на канве линейно, блоки стоят множителями var(--cell)
    # от base_min, и выкинутый средний час сдвинул бы всё, что после него.
    # ⚠️ «Закрыто» спрашивается у doctor_bounds — ровно там, где его спрашивает
    # _cells для класса .off. Свой второй признак развёл бы полоску и штриховку.
    # ⚠️ Час, в котором ЕСТЬ запись, не срезается никогда (row_hours): визит вне
    # графика — как раз то, что сетка обязана показывать.
    open_h: set[int] = set()
    for _dk, _nm in shown:
        _b = eng.doctor_bounds(_dk, d)
        if _b:
            _f, _to, _bf, _bt = _b
            open_h |= {h for h in range(_f, _to) if not (_bf <= h < _bt)}
    keep_h = open_h | row_hours
    lead, tail = 0, len(hours)
    while lead < tail - 1 and hours[lead] not in keep_h:
        lead += 1
    while tail - 1 > lead and hours[tail - 1] not in keep_h:
        tail -= 1
    band_l, band_r = hours[:lead], hours[tail:]
    # хотя бы один ряд остаётся всегда (условия циклов), иначе день без графика
    # и без записей отдал бы пустую карточку вместо сетки
    hours = hours[lead:tail]
    idx = {h: i for i, h in enumerate(hours)}
    base_min = hours[0] * 60

    def _band(hs: list[int], side: str) -> str:
        """Полоска «закрыто» вместо срезанных рядов. Стоит СНАРУЖИ .gridbody:
        внутри она сдвинула бы начало координат, от которого .gappt считает top.
        ⚠️ side — `gb-top`/`gb-bot` с префиксом: `.top` уже занят липкой шапкой,
        и её «стеклянное» правило перекрашивало полоску (подробности в panel.css)."""
        if not hs:
            return ""
        return (f"<div class='gband {side}' "
                f"title='Închis · {hs[0]:02d}:00 - {hs[-1] + 1:02d}:00'></div>")

    # класс дописываем в конце: полное число колонок известно только после сирот
    head = ["<div class='gridhead'><div class='gh-time'></div>"]
    cols = []
    for i, (dk, name) in enumerate(shown):
        col_key = f"k:{dk}"
        hue = eng.DOCTOR_META.get(dk, {}).get("color") or _DOC_HUES[i % len(_DOC_HUES)]
        mine = [r for r in live if _row_col(r) == col_key and r["source"] != "note"]
        free_h = _free_hour(dk, col_key)
        dot = "var(--green)" if free_h is not None else "var(--text3)"
        liber = f"liber {free_h:02d}:00" if free_h is not None else "complet"
        meta = eng.DOCTOR_META.get(dk, {})
        # имя в title тоже: у длинных имён карточка обрезает его многоточием
        extra = " · ".join(x for x in [name, meta.get("room", ""),
                                       meta.get("phone", "")] if x)
        off = "" if meta.get("active", True) else " · inactiv"
        # фото врача (если загружено в его фише) вместо инициалов — v1.9.0
        pp = _photo_path(dk)
        av = (f"<img src='/admin/doctor-photo/{urllib.parse.quote(dk)}"
              f"?v={urllib.parse.quote(pp.name)}' alt=''>" if pp
              else html.escape(_initials(name)))
        # Загрузка кресла: занятые минуты / рабочие минуты врача В ЭТОТ ДЕНЬ.
        # Формула ровно та же, что в статистике за период, и ёмкость берётся у
        # того же eng.work_minutes — иначе дашборд и раздел «Statistici»
        # показывали бы разный процент про одного и того же врача.
        cap = eng.work_minutes(dk, d)
        busy = sum(int(r.get("duration_min") or 60) for r in mine)
        pct = round(100 * busy / cap) if cap else 0
        occ = (f"<div class='occ' title='{busy} din {cap} minute de lucru'>"
               f"<div class='statbar'><div style='width:{min(pct, 100)}%'></div></div>"
               f"<b>{pct}%</b></div>" if cap else "")
        head.append(
            f"<div class='gh-doc'><div class='dcard{'' if not off else ' off'}' "
            f"style='border-left-color:{hue}'>"
            f"<span class='av' style='background:{hue}'>{av}</span>"
            f"<div class='nm'><a href='/admin/doctor/{dk}?date={d.isoformat()}' "
            f"title='{html.escape(extra)}'>{html.escape(name)}</a>"
            f"<small>{html.escape(eng.DOCTOR_SPEC.get(dk, '')) or '&nbsp;'}{off}</small>"
            f"<small class='mt'>{len(mine)} prog. · {liber}</small>{occ}</div>"
            f"<span class='st' style='background:{dot}' title='{liber}'></span></div></div>")
        cols.append(f"<div class='gcol' data-dk='{html.escape(dk, quote=True)}'>"
                    f"{_cells(dk, name)}{_blocks(col_key)}</div>")

    # легаси-строки без id со старым именем (переименовали ДО v1.7.1) —
    # видимы отдельной колонкой + инструмент «переприкрепить к врачу»:
    # без этого их будущие брони невидимы для проверки занятости
    known = {f"k:{dk}" for dk, _n in shown}
    orphans = sorted(set(by_col) - known - {f"k:{dk}" for dk in eng.DOCTORS})
    for col_key in orphans:
        name = col_key[2:]
        mine = [r for r in live if _row_col(r) == col_key and r["source"] != "note"]
        relink_opts = "".join(f"<option value='{dk}'>{html.escape(n)}</option>"
                              for dk, n in eng.DOCTORS.items())
        head.append(
            f"<div class='gh-doc'><div class='dcard off' style='border-left-color:#94A3B8'>"
            f"<span class='av' style='background:#94A3B8'>"
            f"{html.escape(_initials(name))}</span>"
            f"<div class='nm'><a>{html.escape(name)}</a>"
            f"<small>în afara listei · {len(mine)} prog.</small>"
            f"<form method='post' action='/admin/relink' style='margin-top:3px;display:flex;gap:3px'>"
            f"<input type='hidden' name='old_name' value=\"{html.escape(name)}\">"
            f"<input type='hidden' name='back' value='/admin?date={d.isoformat()}'>"
            f"<select name='dk' style='font-size:10.5px;max-width:110px'>{relink_opts}</select>"
            f"<button style='font-size:10.5px;border:1px solid var(--line);background:none;"
            f"border-radius:6px;cursor:pointer'>{_ic('chev-r')}</button></form></div></div></div>")
        cols.append(f"<div class='gcol'>{_cells(None, name)}{_blocks(col_key)}</div>")
    # больше четырёх колонок — карточка ужимается (аватар меньше, специализация
    # прячется): у клиники на 6 врачей полноразмерная карточка режет имена
    if len(cols) > 4:
        head[0] = head[0].replace("class='gridhead'", "class='gridhead tight'", 1)
    head.append("</div>")

    now = datetime.now(eng.TZ)
    nowline = ""
    if d == now.date() and now.hour in idx:
        frac = idx[now.hour] + now.minute / 60
        nowline = f"<div class='nowline' style='top:calc({frac:.3f}*var(--cell))'></div>"
    # метка ТЕКУЩЕГО часа выделена: красная линия показывает точный момент, а
    # подсветка часа читается боковым зрением с другого конца стойки
    timecol = "".join(
        f"<div class='nowh'>{h:02d}:00</div>"
        if d == now.date() and h == now.hour else f"<div>{h:02d}:00</div>"
        for h in hours)
    # fitGrid: день заполняет окно до низа — высота ячейки тянется под вьюпорт
    # (короткая суббота не оставляет пустую страницу), минимум 56px + прокрутка
    # fitAppts: блок записи сам говорит, влез ли он. Классы ставятся ПО ЗАМЕРУ
    # (scrollHeight > clientHeight), а не по порогу длительности, и это здесь
    # единственный честный способ: высоту ряда решает fitGrid из окна, поэтому
    # получасовая запись на ноутбуке клиники и на большом мониторе — разные
    # пиксели. Порог числом («короче 55 минут») врал бы на одном из двух.
    # ⭐ Побочная выгода: ни одной магической цифры. Поменяются кегль, padding
    # или line-height внутри .gappt — правило подстроится само, потому что
    # спрашивает браузер, а не таблицу констант.
    # ⚠️ Поправка на переполнение (последний шаг fitGrid) применяется ТОЛЬКО
    # тогда, когда ниже всех кончается сама сетка. Правая колонка длиннее её
    # почти всегда (08-12, 1920×1080: календарь 263 + агенда 404 + «Azi» 440 =
    # 1134 против 616 у сетки), и отнятые у часа пиксели не убирали прокрутку
    # ни на один — страница всё равно длиной с соседа. Платили за это дырой ПОД
    # сеткой: замер дал 360px пустоты, и это ровно то, на что Олег показал
    # скриншотом. Со снятой поправкой час вырос 56 → 64, сетка кончается у
    # нижнего края окна (зазор 113 → 25px), длина страницы не изменилась.
    # ⛔ Саму поправку не выбрасывать: когда сетка ДЛИННЕЕ соседа (короткий
    # день, пустая агенда), она честно убирает лишнюю прокрутку.
    # ⚠️ Знаки ⚠/⭐/⛔ живут только в питоновских комментариях. Ниже начинается
    # СТРОКА, уезжающая в страницу, и test_structure проверяет её на знаки,
    # которые Windows рисует своим шрифтом, — даже внутри JS-комментария.
    # Лестница в ТРИ ступени, каждая следующая — только если предыдущая не влезла:
    # slim (имя и услуга одной строкой) → tiny (только имя) → bare (цвет и полоса).
    # ⚠️ Ступень «только имя» появилась не сразу, и её отсутствие стоило релиза:
    # блок в 0.4 ячейки (пол в `_pos`, 16px при --cell:56) проваливался мимо slim
    # прямо в «текста нет», и короткая запись стояла в журнале безымянным пятном.
    # Имя туда помещается — см. .gappt.tiny в panel.css.
    fit_js = f"""<script>
function fitAppts() {{
  document.querySelectorAll('.gappt').forEach(function (a) {{
    a.classList.remove('slim', 'tiny', 'bare');
    if (a.scrollHeight > a.clientHeight) a.classList.add('slim');
    if (a.scrollHeight > a.clientHeight) a.classList.add('tiny');
    if (a.scrollHeight > a.clientHeight) a.classList.add('bare');
  }});
}}
function fitGrid() {{
  var gb = document.querySelector('.gridbody'), n = {len(hours)};
  if (!gb) return;
  gb.style.setProperty('--cell', '56px');
  var c = Math.max(56, Math.floor((window.innerHeight - gb.getBoundingClientRect().top - 24) / n));
  gb.style.setProperty('--cell', c + 'px');
  var over = document.documentElement.scrollHeight - window.innerHeight;
  /* ужимать час имеет смысл, только если страницу распирает сама сетка */
  var rail = document.querySelector('.rail');
  if (rail && rail.getBoundingClientRect().bottom > gb.getBoundingClientRect().bottom) over = 0;
  if (over > 0) gb.style.setProperty('--cell', Math.max(56, c - Math.ceil(over / n)) + 'px');
  fitAppts();
}}
fitGrid();                                  // сразу, чтобы не мигало
document.addEventListener('DOMContentLoaded', fitGrid);  // и когда виден весь макет
window.addEventListener('resize', fitGrid);
</script>"""
    # шапка врачей вынесена ИЗ белой карточки сетки (макет Олега 08-03):
    # это отдельная полоса карточек над расписанием. Ширины те же (56px под
    # колонку времени + flex:1 на врача), поэтому карточка стоит ровно над
    # своей колонкой — выравнивание держится само.
    # data-day — ключ, по которому panel.js помнит, какие записи уже видели:
    # без него переход на завтра подсветил бы весь день как «только что пришло»
    return (f"{''.join(head)}<div class='gridcard'>"
            f"{_band(band_l, 'gb-top')}"
            f"<div class='gridbody' data-day='{d.isoformat()}'>"
            f"<div class='gcol-time'>{timecol}</div>"
            f"{''.join(cols)}{nowline}</div>"
            f"{_band(band_r, 'gb-bot')}</div>{fit_js}")


def _botnew_block(recent: list, now: datetime) -> str:
    if not recent:
        return ""
    rev = {name: dk for dk, name in eng.DOCTORS.items()}
    items = []
    for r in recent:
        visit = r["starts_at"].astimezone(eng.TZ)
        created = r["created_at"].astimezone(eng.TZ)
        dk = r.get("doctor_id") or rev.get(r["doctor"])
        if dk not in eng.DOCTORS:
            dk = None
        href = (f"/admin/doctor/{dk}?date={visit.date().isoformat()}" if dk
                else f"/admin/all?date={visit.date().isoformat()}")
        nou = ("<span class='nou'>NOU</span>"
               if now - created < timedelta(hours=24) else "")
        items.append(
            f"<a href='{href}'>"
            f"<span class='dt'>{visit.strftime('%d.%m %H:%M')}</span> · "
            f"{html.escape(r['doctor'])} · {html.escape(r['service'])} · "
            f"<b>{html.escape(r['name'] or '')}</b> · {html.escape(r['phone'] or '')}"
            f"{nou} <span class='crt'>— primită {created.strftime('%d.%m %H:%M')}</span></a>")
    return (f"<div class='botnew' id='botnew'><h3>{_ic('bot')} Programări noi din bot (7 zile, ultimele 10)</h3>"
            + "".join(items) + "</div>")


@router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, date_q: str = Query("", alias="date"), msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    # Две недели одним запросом вместо «сегодня» + «вчера» двумя: из этой же
    # выборки берутся и день, и вчера, и ряды для мини-графиков в плитках.
    span = [d - timedelta(days=SPARK_DAYS - 1 - i) for i in range(SPARK_DAYS)]
    all_rows = await db.day_appointments(
        day_start - timedelta(days=SPARK_DAYS - 1), day_start + timedelta(days=1))
    by_day: dict = {x: [] for x in span}
    for r in all_rows:
        by_day.setdefault(r["starts_at"].astimezone(eng.TZ).date(), []).append(r)
    rows = by_day[d]

    def _counts(rr: list) -> tuple[int, int, int, int, int]:
        a = [r for r in rr if r["status"] != "cancelled" and r["source"] != "note"]
        return (len(a), sum(1 for r in a if r["source"] == "bot"),
                sum(1 for r in a if r["source"] == "manual"),
                sum(1 for r in a if r["service"] in eng.URGENT_LABELS),
                sum(1 for r in rr if r["status"] == "noshow"))

    total, n_bot, n_man, n_urg, n_noshow = _counts(rows)
    y_total, _yb, y_man, _yu, y_noshow = _counts(by_day[d - timedelta(days=1)])
    series = list(zip(*(_counts(by_day[x]) for x in span)))

    def trend(cur: int, prev: int, bad_up: bool = False) -> str:
        diff = cur - prev
        if diff == 0:
            return "<span class='trend'>la fel ca ieri</span>"
        cls = ("dn" if bad_up else "up") if diff > 0 else ("up" if bad_up else "dn")
        arrow = _ic("caret-u") if diff > 0 else _ic("caret-d")
        return (f"<span class='trend'><span class='{cls}'>{arrow} {diff:+d}</span>"
                f" față de ieri</span>")

    now = datetime.now(eng.TZ)
    recent = await db.recent_bot_appointments(now - timedelta(days=7))
    new_today = sum(1 for r in recent
                    if r["created_at"].astimezone(eng.TZ).date() == now.date())

    day_url = f"/admin/all?date={d.isoformat()}"
    bot_sub = (f"<span class='trend'><span class='up'>{new_today} noi</span> azi</span>"
               if new_today else "<span class='trend'>nimic nou azi</span>")
    def _kpi(href: str, ico: str, soft: str, tone: str, val: int, label: str,
             sub: str, ser, cls: str = "") -> str:
        """Строка карточки «Azi» в правой колонке (макет Олега 08-11). Цифру
        оживляет `data-count` (panel.js), сама строка ведёт в тот список, из
        которого она посчитана, а под ней — ряд за две недели.

        ⚠️ Мини-график тут НЕ украшение, и выбрасывать его при переезде из ряда
        наверху было нельзя: я попробовал, и три проверки «Панели дня» упали —
        включая ту, что требует график даже на двух неделях нулей. Причина
        записана в `core/charts.spark`: без него спокойная клиника видит пустое
        место вместо ровной линии по полу. В колонке график идёт ВТОРОЙ строкой
        на всю ширину карточки — так же, как у загрузки кресел, — потому что
        рядом с цифрой в 300px ему остаётся 40px, где семь точек уже шум.
        ⚠️ Подпись без «azi»: его один раз говорит заголовок карточки, иначе
        слово повторилось бы пять раз подряд."""
        return (f"<a class='rk-i{cls}' href='{href}'>"
                f"<span class='ico' style='background:{soft};color:{tone}'>{ico}</span>"
                f"<b data-count='{val}'>{val}</b>"
                f"<span class='rk-l'>{label}</span>{sub}"
                f"{_spark(list(ser), tone)}</a>")

    # Загрузка кресел за день: занятые минуты всех записей / рабочие минуты
    # АКТИВНЫХ врачей — та же формула, что на карточке врача и в «Statistici»,
    # чтобы три места не могли назвать три разных процента.
    active_dks = [dk for dk in eng.DOCTORS
                  if eng.DOCTOR_META.get(dk, {}).get("active", True)]

    def _occ_pct(day: date, rr: list) -> int:
        cap = sum(eng.work_minutes(dk, day) for dk in active_dks)
        if not cap:
            return 0
        busy = sum(int(r.get("duration_min") or 60) for r in rr
                   if r["status"] != "cancelled" and r["source"] != "note")
        return min(round(100 * busy / cap), 100)

    occ = _occ_pct(d, rows)
    prev_day = d - timedelta(days=1)
    occ_prev = _occ_pct(prev_day, by_day[prev_day])
    # тренд ДВУМЯ значениями («ieri 70% → azi 86%»), а не разницей «+16 pp»:
    # процентные пункты пришлось объяснять даже Олегу — регистратура не обязана
    # знать эту единицу. Слова «ieri/azi» только на СЕГОДНЯШНЕЙ странице:
    # журнал умеет показывать любой день, и там честнее даты.
    a_lbl, b_lbl = (("ieri", "azi") if d == now.date()
                    else (prev_day.strftime("%d.%m"), d.strftime("%d.%m")))
    prev_open = any(eng.work_minutes(dk, prev_day) for dk in active_dks)
    left = f"{occ_prev}%" if prev_open else "închis"
    arrow = (f"<span class='up'>{_ic('caret-u')}</span> " if occ > occ_prev else
             f"<span class='dn'>{_ic('caret-d')}</span> " if occ < occ_prev else "")
    occ_sub = (f"<span class='trend'>{arrow}{a_lbl} {left} › {b_lbl} {occ}%</span>")
    # Загрузка кресел стоит ПОСЛЕДНЕЙ и устроена иначе остальных строк: у неё
    # своя строка под цифру и мини-график на всю ширину карточки. Причина не в
    # красоте — это единственная величина, у которой нет списка за спиной
    # (кликать не во что), зато есть форма за две недели.
    occ_row = (f"<div class='rk-occ'>"
               f"<span class='ico' style='background:var(--violet-soft);"
               f"color:var(--violet)'>{_ic('trend')}</span>"
               f"<span class='rk-l'>Grad de ocupare</span>{occ_sub}"
               f"<b data-count='{occ}' data-suffix='%'>{occ}%</b>"
               f"{_spark([_occ_pct(x, by_day[x]) for x in span], 'var(--violet)')}"
               f"</div>")

    # Telegram заморожен (tg_configured): клинике без бота панель не смеет
    # рассказывать про канал, которого у неё нет, — плитка, блок «noi din
    # bot», колокольчик и строка статуса живут только у grandfather-клиник
    tg_ui = tg_configured()
    kpi_card = ("<div class='rkpi'><div class='rk-h'><b>Azi</b></div>"
                + _kpi(day_url, _ic("cal"), "var(--green-soft)", "var(--green)",
                       total, "Programări", trend(total, y_total), series[0])
                + (_kpi(f"{day_url}&amp;f=bot", _ic("bot"), "var(--teal-soft)",
                        "var(--teal-d)", n_bot, "Prin bot", bot_sub,
                        series[1]) if tg_ui else "")
                + _kpi(f"{day_url}&amp;f=rec", _ic("headset"), "var(--blue-soft)",
                       "var(--blue)", n_man, "Recepție", trend(n_man, y_man), series[2])
                + _kpi(f"{day_url}&amp;f=urg", _ic("alarm"), "var(--amber-soft)",
                       "var(--amber)", n_urg, "Urgențe",
                       "<span class='trend'>intercalate azi</span>", series[3], cls=" warn")
                + _kpi(f"{day_url}&amp;f=noshow", _ic("ban"), "var(--red-soft)",
                       "var(--red)", n_noshow, "Neprezentări",
                       trend(n_noshow, y_noshow, bad_up=True), series[4], cls=" bad")
                + occ_row
                + "</div>")

    cards = _collect_cards(rows)
    back = f"/admin?date={d.isoformat()}"
    sync = ""
    if tg_ui:
        tg_on, _u = _tg_state()
        sync = ("<div style='display:flex;align-items:center;gap:7px;font-size:11.5px;"
                "color:var(--text3);padding:0 4px'>"
                f"<span style='width:7px;height:7px;border-radius:50%;background:"
                f"{'var(--green)' if tg_on else 'var(--text3)'}'></span>"
                f"{'Sincronizat cu botul Telegram' if tg_on else 'Bot Telegram neconectat'}</div>")
    tabs = (f"<a class='primary' href='/admin?date={d.isoformat()}'>Zi</a>"
            f"<a href='/admin/week?date={d.isoformat()}'>Săptămâna</a>")
    # ⭐ KPI живут в ПРАВОЙ колонке, а не полноширинным рядом над журналом
    # (макет Олега 08-11). Ряд наверху стоил 218px и уводил начало сетки на
    # 556-й пиксель: на рабочем экране клиники (1366×768, окно ~696px) от дня
    # было видно 2.5 часа из 11. Порядок в колонке — календарь, агенда, «Azi»:
    # сверху то, чем регистратура пользуется, ниже то, на что смотрят.
    body = (_date_nav(d, "/admin", tabs) + _banner(msg, d)
            + "<div class='dash'><div class='dashmain'>"
            + _day_canvas(d, rows, cards)
            + "<p class='hint'>Click pe o programare — detalii și statusuri; "
              "click pe un slot liber — programare nouă sau notiță; "
              "trageți o programare pentru a o muta la altă oră sau alt medic."
            + (" Programările prin bot apar automat." if tg_ui else "")
            + "</p>"
            + "</div><div class='rail'>"
            + _mini_cal(d) + _agenda_block(d, rows, cards, now) + kpi_card
            + (_botnew_block(recent, now) if tg_ui else "") + sync
            + "</div></div>"
            + _slot_modal(d, back) + _card_modal(cards, back)
            + _move_modal(d, back))
    sub = (f"panou principal · {_ic('bot')} bot / {_ic('pen')} recepție · se actualizează automat"
           if tg_ui else "panou principal · se actualizează automat")
    return _shell(body, sub, active="dash",
                  bell=new_today if tg_ui else None)


@router.get("/admin/week", response_class=HTMLResponse)
async def admin_week(request: Request, date_q: str = Query("", alias="date")):
    """Недельный календарь: колонки рабочих дней, компактные чипы записей."""
    if (deny := _guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    monday = d - timedelta(days=d.weekday())
    today = datetime.now(eng.TZ).date()
    cols, total_wk = [], 0
    for i in range(7):
        day = monday + timedelta(days=i)
        day_start = datetime(day.year, day.month, day.day, tzinfo=eng.TZ)
        rows = await db.day_appointments(day_start, day_start + timedelta(days=1))
        act = sorted((r for r in rows if r["status"] != "cancelled"),
                     key=lambda r: r["starts_at"])
        if not eng.hours_for(day) and not act:
            continue  # выходной прячем, только если на нём НЕТ живых записей
        n_real = sum(1 for r in act if r["source"] != "note")
        total_wk += n_real
        chips = []
        for r in act:
            hh = r["starts_at"].astimezone(eng.TZ).strftime("%H:%M")
            if r["source"] == "note":
                chips.append(f"<div class='wchip gnote' style='border:1px dashed var(--line);"
                             f"color:var(--text2)'>{_ic('note')} {hh} {html.escape(r['service'][:30])}</div>")
                continue
            bg, bar = _svc_colors(r)
            ns = " noshow" if r["status"] == "noshow" else ""
            chips.append(
                f"<div class='wchip{ns}' style='background:{bg};border-left:5px solid {bar}'>"
                f"<b>{hh}</b> {html.escape(r['name'] or '—')}"
                f"<small>{html.escape(r['service'])}</small></div>")
        if not chips:
            chips.append("<div style='font-size:11.5px;color:var(--text3);"
                         "text-align:center;padding:12px 0'>— liber —</div>")
        dow = eng.day_label(eng.Session(lang="ro"), day).split(",")[0].split()[0]
        tdy = " tdy" if day == today else ""
        cols.append(
            f"<div class='wcol'><div class='wh{tdy}'>"
            f"<a href='/admin?date={day.isoformat()}'>{dow} {day.strftime('%d.%m')}</a>"
            f"<small>{n_real} programări</small></div>"
            f"<div class='wb'>{''.join(chips)}</div></div>")
    prev_w = (monday - timedelta(days=7)).isoformat()
    next_w = (monday + timedelta(days=7)).isoformat()
    sunday = monday + timedelta(days=6)
    nav = (f"<div class='nav'><b>{monday.strftime('%d.%m')} – {sunday.strftime('%d.%m.%Y')}"
           f" · {total_wk} programări</b>"
           f"<a href='/admin/week?date={prev_w}'>{_ic('chev-l')} săpt.</a>"
           f"<a href='/admin/week'>Azi</a>"
           f"<a href='/admin/week?date={next_w}'>săpt. {_ic('chev-r')}</a>"
           f"<a href='/admin?date={d.isoformat()}'>Zi</a>"
           f"<a class='primary' href='/admin/week?date={d.isoformat()}'>Săptămâna</a></div>")
    body = nav + f"<div class='week'>{''.join(cols)}</div>" + \
        "<p class='hint'>Click pe ziua din antet — deschide programul zilei.</p>"
    return _shell(body, "calendar săptămânal · culori după tipul procedurii", active="dash")


@router.get("/admin/export")
async def admin_export(
    request: Request,
    from_q: str = Query("", alias="from"),
    to_q: str = Query("", alias="to"),
):
    if (deny := _guard(request)) is not None:
        return deny
    d1 = _parse_date(from_q) if from_q else datetime.now(eng.TZ).date()
    d2 = _parse_date(to_q) if to_q else d1
    if d2 < d1:
        d1, d2 = d2, d1
    start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    end = datetime(d2.year, d2.month, d2.day, tzinfo=eng.TZ) + timedelta(days=1)
    rows = await db.day_appointments(start, end)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Data", "Ora", "Pacient", "An naștere", "Telefon", "Serviciu",
                "Medic", "Sursă", "Status", "Reminder", "Comentariu"])
    for r in rows:
        dt = r["starts_at"].astimezone(eng.TZ)
        w.writerow([
            dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M"),
            r["name"] or ("— notiță —" if r["source"] == "note" else ""),
            r["birth_year"] or "", r["phone"] or "", r["service"], r["doctor"],
            r["source"], r["status"],
            "da" if r["reminded_day"] else "", r["comment"] or "",
        ])
    csv_text = "\ufeff" + buf.getvalue()  # BOM: Excel открывает UTF-8 корректно
    fname = f"programari_{d1.isoformat()}_{d2.isoformat()}.csv"
    return Response(
        csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ⭐ Та же выгрузка, но с ТИПАМИ. CSV их не несёт, и Excel угадывает: телефон
# `022447788` он считает числом и роняет ведущий ноль (в Молдове все номера с
# нуля — по такой таблице не позвонить), а дату не вмещает в колонку по
# умолчанию и рисует `########`. Второе кричит, первое молчит — потому эта
# кнопка и стала основной.
# ⚠️ CSV-маршрут остаётся живым намеренно: он мог уехать в чью-то закладку или
# скрипт, а исчезнувшая ссылка — это 404 у клиники на ровном месте.
@router.get("/admin/export.xlsx")
async def admin_export_xlsx(
    request: Request,
    from_q: str = Query("", alias="from"),
    to_q: str = Query("", alias="to"),
):
    if (deny := _guard(request)) is not None:
        return deny
    d1 = _parse_date(from_q) if from_q else datetime.now(eng.TZ).date()
    d2 = _parse_date(to_q) if to_q else d1
    if d2 < d1:
        d1, d2 = d2, d1
    start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    end = datetime(d2.year, d2.month, d2.day, tzinfo=eng.TZ) + timedelta(days=1)
    rows = await db.day_appointments(start, end)

    data = []
    for r in rows:
        dt = r["starts_at"].astimezone(eng.TZ)
        data.append([
            dt.date(), dt.strftime("%H:%M"),
            r["name"] or ("— notiță —" if r["source"] == "note" else ""),
            int(r["birth_year"]) if r["birth_year"] else "",
            r["phone"] or "", r["service"], r["doctor"], r["source"], r["status"],
            "da" if r["reminded_day"] else "", r["comment"] or "",
        ])
    blob = xlsx.book(
        ["Data", "Ora", "Pacient", "An naștere", "Telefon", "Serviciu",
         "Medic", "Sursă", "Status", "Reminder", "Comentariu"],
        data,
        # ширины в знаках — под самое длинное, что в колонке реально бывает:
        # это и есть вторая половина ответа на «дата не влезает»
        widths=[11, 7, 22, 11, 14, 26, 22, 9, 12, 10, 34],
    )
    fname = f"programari_{d1.isoformat()}_{d2.isoformat()}.xlsx"
    return Response(
        blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# фильтры для клика по плиткам дашборда: цифра → сразу список этих записей
_TILE_FILTERS = {
    "bot": ("prin bot",
            lambda r: r["source"] == "bot" and r["status"] != "cancelled"),
    "rec": ("recepție",
            lambda r: r["source"] == "manual" and r["status"] != "cancelled"),
    "urg": ("urgențe",
            lambda r: r["service"] in eng.URGENT_LABELS
            and r["source"] != "note" and r["status"] != "cancelled"),
    "noshow": ("neprezentări", lambda r: r["status"] == "noshow"),
}


@router.get("/admin/all", response_class=HTMLResponse)
async def admin_all(
    request: Request,
    date_q: str = Query("", alias="date"),
    doctor: str = "", time_pre: str = "", msg: str = "", f: str = "",
):
    if (deny := _guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = await db.day_appointments(day_start, day_start + timedelta(days=1))
    active = _active_map(rows)
    # неактивный врач в сетке — только пока у него есть записи этого дня
    busy_keys = {r.get("doctor_id") for r in rows if r["status"] != "cancelled"}
    busy_names = {r["doctor"] for r in rows if r["status"] != "cancelled"}
    items = [(dk, n) for dk, n in eng.DOCTORS.items()
             if eng.DOCTOR_META.get(dk, {}).get("active", True)
             or dk in busy_keys or n in busy_names]
    flt = _TILE_FILTERS.get(f)
    back = f"/admin/all?date={d.isoformat()}" + (f"&f={f}" if flt else "")

    def href(dk, h):
        return f"/admin/all?date={d.isoformat()}&doctor={dk}&time_pre={h:02d}:00#addform"

    cards = _collect_cards(rows)
    filter_chip, filtered_list = "", ""
    if flt:
        label, pred = flt
        hits = [r for r in rows if pred(r)]
        filter_chip = (
            f"<div class='banner ok'>Filtru: <b>{label}</b> — {len(hits)} programări "
            f"· <a href='/admin/all?date={d.isoformat()}'>arată tot {_ic('close')}</a></div>")
        filtered_list = _list(hits, back, title=f"{label} — {d.strftime('%d.%m.%Y')}")
    body = (_date_nav(d, "/admin/all",
                      f"<a href='/admin?date={d.isoformat()}'>{_ic('home')} Panou</a>"
                      f"<a href='/admin/export.xlsx?from={d.isoformat()}&to={d.isoformat()}'>{_ic('download')} Excel</a>")
            + _banner(msg, d)
            + filter_chip + filtered_list
            + _grid(d, items, active, href, cards)
            + _form(d, list(eng.ACTIVE_DOCTORS.items()) or items, doctor, time_pre, back)
            + ("" if flt else _list(rows, back))
            + _slot_modal(d, back)
            + _card_modal(cards, back)
            + _move_modal(d, back))
    return _shell(body, (f"toți medicii · {_ic('bot')} bot / {_ic('pen')} recepție / {_ic('note')} notițe"
                         if tg_configured()
                         else f"toți medicii · {_ic('pen')} recepție / {_ic('note')} notițe"),
                  active="prog")


@router.get("/admin/doctor/{dk}", response_class=HTMLResponse)
async def admin_doctor(
    request: Request,
    dk: str, date_q: str = Query("", alias="date"),
    time_pre: str = "", msg: str = "",
):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin")
    name = eng.DOCTORS[dk]
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = [r for r in await db.day_appointments(day_start, day_start + timedelta(days=1))
            if r.get("doctor_id") == dk
            or (not r.get("doctor_id") and r["doctor"] == name)]
    active = _active_map(rows)
    items = [(dk, name)]
    base = f"/admin/doctor/{dk}"
    back = f"{base}?date={d.isoformat()}"

    def href(_dk, h):
        return f"{base}?date={d.isoformat()}&time_pre={h:02d}:00#addform"

    is_active = eng.DOCTOR_META.get(dk, {}).get("active", True)
    off_badge = ("" if is_active
                 else " <span style='color:var(--text3)'>· inactiv (istoric)</span>")
    # ссылка на карточку — только тем, кому карточка открыта (PERM_DOCTORS):
    # это удобство, а не защита — отказ выдаёт require() в самом маршруте
    me = request_user()
    fisa = (f"<a href='/admin/doctor-card/{dk}'>{_ic('user')} Fișa medicului</a>"
            if can(me, PERM_DOCTORS) or me is None else "")
    head = (f"<div class='nav'><b>{html.escape(name)}</b>{off_badge} "
            f"<span style='color:#667'>{html.escape(eng.DOCTOR_SPEC.get(dk, ''))}</span> "
            f"{fisa}"
            f"<a href='/admin?date={d.isoformat()}'>{_ic('home')} Panou</a>"
            f"<a href='/admin/all?date={d.isoformat()}'>{_ic('clipboard')} Toți medicii</a></div>")
    cards = _collect_cards(rows)
    body = (head + _date_nav(d, base) + _banner(msg, d)
            + _grid(d, items, active, href, cards)
            + (_form(d, items, dk, time_pre, back) if is_active else "")
            + _list(rows, back)
            + _slot_modal(d, back)
            + _card_modal(cards, back)
            + _move_modal(d, back))
    return _shell(body, (f"ziua unui medic · {_ic('bot')} bot / {_ic('pen')} recepție / {_ic('note')} notițe"
                         if tg_configured()
                         else f"ziua unui medic · {_ic('pen')} recepție / {_ic('note')} notițe"),
                  active="prog")


def _back_redirect(back: str, fallback_date: str, msg: str) -> RedirectResponse:
    target = back if back.startswith("/admin") else f"/admin/all?date={fallback_date}"
    sep = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{sep}msg={msg}", status_code=303)


@router.post("/admin/add")
async def admin_add(
    request: Request,
    adate: str = Form(...), atime: str = Form(...), adoctor: str = Form(...),
    aservice: str = Form(...), aname: str = Form(...), aphone: str = Form(...),
    abirth: str = Form(""), ayear: str = Form(""), back: str = Form(""),
):
    if (deny := _guard(request)) is not None:
        return deny
    try:
        d = date.fromisoformat(adate)
        hh, mm = atime.split(":")
        dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return _back_redirect(back, adate, "bad")
    doctor = eng.DOCTORS.get(adoctor)
    svc = eng.SERVICES.get(aservice)
    name = aname.strip()[:80]
    phone = aphone.strip()[:25]
    digits = "".join(ch for ch in phone if ch.isdigit())
    # ⚠️ пять разных причин отвечали одним «Date invalide — verificați
    # câmpurile». По такому баннеру не видно, какое поле чинить, и отказ
    # читается как «программа не работает». Каждая причина называет себя.
    if not doctor or not svc:
        return _back_redirect(back, adate, "bad")
    if not name:
        return _back_redirect(back, adate, "bad_name")
    # 6–15 цифр: у стран номера от 6 национальных цифр, E.164 даёт максимум 15.
    # Жёсткий молдавский формат отверг бы иностранца у стойки (просьба 08-07)
    if not 6 <= len(digits) <= 15:
        return _back_redirect(back, adate, "bad_phone")
    if not eng.DOCTOR_META.get(adoctor, {}).get("active", True):
        return _back_redirect(back, adate, "bad_off")  # выключенному не пишем
    if dt.minute not in (0, 30):
        return _back_redirect(back, adate, "bad_time")  # 30-мин сетка стартов
    if not eng.fits_clinic(dt, eng.svc_duration(aservice)):
        # визит не помещается в рабочее окно клиники (закрытие/обед)
        return _back_redirect(back, adate, "outside")
    # личный график врача (work_from/work_to) — той же проверкой окон, из
    # которой free_starts предлагает слоты.
    # ⚠️ Гейт применяется ТОЛЬКО к будущему: его смысл — не обещать пациенту
    # час, когда врача нет, а у состоявшегося приёма обещать уже нечего. График
    # могли сузить ПОСЛЕ визита, и тогда внести его постфактум стало бы нечем:
    # фиша прошлое не берёт по замыслу, журнал — единственный вход.
    # Граница здесь МГНОВЕННАЯ (is_past), а не дневная: «приём был сегодня
    # утром, а график сузили после обеда» — тот же постфактум, и на дневной
    # границе он остался бы невозможным. Дневная граница ниже про другое — она
    # решает, показывать ли предупреждение, а не пускать ли запись.
    fits_doc = eng.fits_doctor(adoctor, dt, eng.svc_duration(aservice))
    if not eng.is_past(dt) and not fits_doc:
        return _back_redirect(back, adate, "outside_doc")
    # полная дата рождения (просьба 08-07: был только год); ayear принимаем
    # ради вкладки, открытой до обновления, — форма шлёт уже только abirth
    year, bdate = None, None
    if abirth.strip():
        try:
            parsed = date.fromisoformat(abirth.strip()[:10])
        except ValueError:
            return _back_redirect(back, adate, "bad_bd")
        if not (1900 <= parsed.year and parsed <= date.today()):
            return _back_redirect(back, adate, "bad_bd")
        year, bdate = parsed.year, parsed.isoformat()
    elif ayear.strip().isdigit() and 1900 <= int(ayear) <= datetime.now(eng.TZ).year:
        year = int(ayear)
    # ⚠️ Спрашиваем ДО записи: после неё карточка уже может быть создана этой же
    # записью, и «существующий пациент» перестанет отличаться от нового.
    existing = await db.patient_name_by_phone(phone)
    r = await db.admin_add(name, phone, svc["ro"], doctor, dt, birth_year=year,
                           birth_date=bdate,
                           doctor_id=adoctor, service_id=aservice,
                           duration_min=eng.svc_duration(aservice))
    msg = "ok" if isinstance(r, int) else ("dup" if r == "dup" else "conflict")
    # ⛔ Визит лёг в ЧУЖУЮ карточку — по номеру нашёлся пациент с другим именем
    # (08-10). Чаще всего это ребёнок на телефоне родителя, и это норма; но
    # молча приклеивать к родителю нельзя: дальше туда пойдут одонтограмма,
    # дневник и 043/e, и обнаружится это на распечатанном бланке. Запись
    # проходит — регистратуре нужна скорость, — но она названа вслух.
    # ⚠️ Сравниваем ЛИЧНОЕ ИМЯ, а не строку целиком. Целиком не годится: тот же
    # человек записан в боте как «Ion», а регистратура пишет «Ion Popescu» —
    # предупреждение загоралось бы на обычной работе, и его перестали бы
    # читать раньше, чем оно окажется право (та же болезнь, что у ok_past на
    # мгновенной границе). Разные ЛИЧНЫЕ имена — уже другой человек.
    if msg == "ok" and existing and name.strip():
        was, now = existing.strip().lower().split(), name.strip().lower().split()
        if was and now and was[0] != now[0]:
            msg = "ok_other"
    # ручную запись задним числом НЕ запрещаем (визит вносят постфактум), но и
    # молчать нельзя: запись на закрытый день чаще всего опечатка, а она просто
    # исчезает из журнала — её никто больше не увидит. Граница ДНЕВНАЯ: визит в
    # уже прошедший час сегодня — обычная работа регистратуры, а не ошибка
    if msg == "ok" and eng.is_past_day(dt.date()):
        msg = "ok_past"
    return _back_redirect(back, adate, msg)


@router.post("/admin/note")
async def admin_note(
    request: Request,
    ndate: str = Form(...), ntime: str = Form(...), ndoctor: str = Form(...),
    ntext: str = Form(...), nuntil: str = Form(""), back: str = Form(""),
):
    if (deny := _guard(request)) is not None:
        return deny
    try:
        d = date.fromisoformat(ndate)
        start_h = int(ntime.split(":")[0])
        until_h = int(nuntil) if nuntil.strip() else start_h + 1
    except (ValueError, AttributeError):
        return _back_redirect(back, ndate, "bad")
    doctor = eng.DOCTORS.get(ndoctor)
    text = ntext.strip()[:120]
    day_hours = [x.hour for x in eng.day_slots(d)]
    hours = [h for h in day_hours if start_h <= h < until_h]
    if not doctor or not text or not hours or until_h <= start_h:
        return _back_redirect(back, ndate, "bad")
    if not eng.DOCTOR_META.get(ndoctor, {}).get("active", True):
        return _back_redirect(back, ndate, "bad")
    ok_cnt = fail_cnt = 0
    for h in hours:
        dt = datetime(d.year, d.month, d.day, h, 0, tzinfo=eng.TZ)
        if await db.add_note(doctor, dt, text, doctor_id=ndoctor) is not None:
            ok_cnt += 1
        else:
            fail_cnt += 1
    if fail_cnt == 0:
        msg = "ok_note"
    elif ok_cnt:
        msg = "part_note"
    else:
        msg = "conflict"
    return _back_redirect(back, ndate, msg)


@router.post("/admin/comment/{appt_id}")
async def admin_comment(request: Request, appt_id: int,
                        comment: str = Form(""), back: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    await db.set_comment(appt_id, comment.strip()[:300])
    return _back_redirect(back, "", "ok_comment")


@router.post("/admin/move/{appt_id}")
async def admin_move(
    request: Request, appt_id: int,
    mdate: str = Form(...), mtime: str = Form(...), mdoctor: str = Form(...),
    back: str = Form(""),
):
    """Перенос визита перетаскиванием: другой час и/или другой врач.

    ⚠️ Проверки те же, что у ручной записи, и по той же причине: перетащить —
    это назначить визит на новое место, а не «подвинуть картинку». Браузер
    отказывается класть блок в закрытую ячейку ещё до отправки, но верить ему
    нельзя: вкладка живёт с автообновлением 12 с, а часы клиники и график
    врача меняются на другом экране.
    """
    if (deny := _guard(request)) is not None:
        return deny
    try:
        d = date.fromisoformat(mdate)
        hh, mm = mtime.split(":")
        dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return _back_redirect(back, mdate, "bad")
    doctor = eng.DOCTORS.get(mdoctor)
    if not doctor:
        return _back_redirect(back, mdate, "bad")
    if not eng.DOCTOR_META.get(mdoctor, {}).get("active", True):
        return _back_redirect(back, mdate, "bad_off")
    if dt.minute not in (0, 30):
        return _back_redirect(back, mdate, "bad_time")
    if not eng.fits_clinic(dt, 30):
        # 30 минут, а не полная длительность: визит УЖЕ существует, и требовать
        # от него влезть в окно целиком значило бы отказывать в переносе тем,
        # кого клиника принимает внахлёст с закрытием (так их и записали).
        return _back_redirect(back, mdate, "outside")
    # график врача — та причина серверной перепроверки, которую называет
    # докстринг: часы врача меняются на другом экране, а вкладка устаревает
    if not eng.fits_doctor(mdoctor, dt, 30):
        return _back_redirect(back, mdate, "outside_doc")
    code = await db.move_appointment(appt_id, mdoctor, doctor, dt,
                                     when=dt.strftime("%H:%M"))
    return _back_redirect(back, mdate,
                          {"": "ok_move", "gone": "mv_gone",
                           "closed": "mv_closed"}.get(code, code))


@router.post("/admin/status/{appt_id}")
async def admin_status(request: Request, appt_id: int, to: str = Form(...), back: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    if to in {"waiting", "arrived", "done", "noshow", "cancelled", "confirmed"}:
        # код отказа, а не «не получилось»: «занято у медика» и «у пациента уже
        # есть запись на этот час» чинятся по-разному, и регистратуре нужно
        # знать, ЧТО именно занято (см. db.set_status)
        code = await db.set_status(appt_id, to)
        if code:
            msg = code if code in {"conflict", "dup"} else "conflict"
            sep = "&" if "?" in back else "?"
            target = (back + f"{sep}msg={msg}") if back.startswith("/admin") \
                else f"/admin?msg={msg}"
            return RedirectResponse(target, status_code=303)
    target = back if back.startswith("/admin") else "/admin"
    return RedirectResponse(target, status_code=303)
