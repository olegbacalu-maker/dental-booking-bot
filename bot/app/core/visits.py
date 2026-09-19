"""Как выглядит ВИЗИТ на экране — общее для нескольких разделов.

Список визитов, модалка с подробностями, аватар и цвет врача, разбор даты из
адреса. Всё это нужно и журналу дня, и карточке врача, и статистике: положить
его внутрь одного модуля значило бы, что соседний модуль импортирует соседа —
а это ровно та паутина, ради ухода от которой всё и затевалось.

Граница простая: здесь то, что описывает визит как таковой. Каркас страницы —
в layout.py, доступ — в auth.py, пути к данным — в storage.py.
"""
from __future__ import annotations

import html
import json
import pathlib
import urllib.parse
from datetime import date, datetime

from .. import engine as eng
from .layout import LIVE_STATUSES, STATUS_LABEL, _age, _ic, _initials, js_json
from .storage import _data_dir


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(eng.TZ).date()


# Кнопки исхода — ПО СОСТОЯНИЮ записи, а не один набор на все живые статусы.
# Пациенту, который уже в кресле, «A sosit» повторяет сделанное, а «Nu a venit»
# рядом с ним предлагает записать неправду.
# ⭐ Закрытая запись получает ОДНУ кнопку — возврат в «confirmată». До 08-12
# промах по «Finalizat» был из журнала неисправим совсем: столбец «Acțiuni»
# просто пустел, а маршрут `to=confirmed` при этом существовал и работал —
# нажать его было нечем.
# ⛔ Статусы перечислены ПОИМЁННО. Правило «всё, что не живое, — переоткрыть»
# молча раздало бы свои кнопки новому статусу, и он получил бы чужое поведение
# без единой строки о себе (тот же урок, что PLAN_ACTIVE в db.py).
_REOPEN = ("confirmed", "b-reopen", "Redeschide")
# 08-13: конвейер приёма честный — «A venit» (waiting, пациент в приёмной) →
# «În cabinet» (arrived). Второй шаг НЕОБЯЗАТЕЛЕН намеренно: «Finalizat»
# доступен и из waiting, и прямиком из confirmed — иначе регистратура
# прокликивала бы статусы ради галочки, и «în cabinet» стал бы ритуалом, а не
# фактом. Кнопка зовётся словом статуса, который она ставит (STATUS_LABEL) —
# бывшая «A sosit» ставила arrived и потому теперь называется «În cabinet».
# ⚠️ «Nu a venit» у waiting НЕ предлагается: пациент пришёл, кнопка рядом
# предлагала бы записать неправду (тот же принцип, что у arrived).
_ACT_BUTTONS = {
    "confirmed": (("waiting", "b-waiting", "A venit"),
                  ("arrived", "b-arrived", "În cabinet"),
                  ("done", "b-done", "Finalizat"),
                  ("noshow", "b-noshow", "Nu a venit"),
                  ("cancelled", "b-cancel", "Anulează")),
    "waiting": (("arrived", "b-arrived", "În cabinet"),
                ("done", "b-done", "Finalizat"),
                ("cancelled", "b-cancel", "Anulează")),
    "arrived": (("done", "b-done", "Finalizat"),
                ("cancelled", "b-cancel", "Anulează")),
    "done": (_REOPEN,), "noshow": (_REOPEN,), "cancelled": (_REOPEN,),
}
# заметка — не визит: прихода и исхода у неё нет, есть «убрать» и «вернуть»
# (блокировка слота снимается и ставится обратно тем же статусом)
_NOTE_BUTTONS = {
    "confirmed": (("cancelled", "b-cancel", "Șterge"),),
    "cancelled": (("confirmed", "b-reopen", "Restabilește"),),
}
# возврат спрашивают подтверждением: это отмена уже записанного факта, а не
# следующий шаг приёма (так же ведёт себя «Redeschide» в плане лечения)
_ASK_APPT = "Redeschideți programarea (înapoi la «confirmată»)?"
_ASK_NOTE = "Restabiliți notița?"


def status_actions(status: str, is_note: bool = False) -> list[dict]:
    """Кнопки исхода для этого состояния — ОДНА матрица на всех.

    Список дня печатает их формами, модалка карточки прячет лишние через
    CS_SHOW, React спросит здесь же. Это одно правило в трёх видах, и
    расхождение молчит: закрытая запись теряла бы кнопку возврата в одном
    месте и сохраняла в другом, а увидеть это можно, только открыв оба.
    """
    src = (_NOTE_BUTTONS if is_note else _ACT_BUTTONS).get(status, ())
    ask = _ASK_NOTE if is_note else _ASK_APPT
    return [{"to": to, "cls": cls, "label": label,
             "confirm": ask if cls == "b-reopen" else ""}
            for to, cls, label in src]


def all_status_actions(is_note: bool = False) -> dict:
    """Вся матрица разом — {состояние: кнопки}. Её отдаёт JSON API: клиент
    спрашивает по статусу карточки, как это делает CS_SHOW старой страницы.

    ⚠️ Состояния перечисляет САМА матрица, а не список рядом: список пришлось
    бы дополнять при седьмом статусе, и забытая строка молча оставила бы
    новое состояние без кнопок.
    """
    return {st: status_actions(st, is_note)
            for st in (_NOTE_BUTTONS if is_note else _ACT_BUTTONS)}


def list_rows(rows: list) -> list[dict]:
    """«Lista zilei» данными — строка за строкой, в порядке страницы.

    ⚠️ Это НЕ сетка, и три отличия несущие. Список показывает ОТМЕНЁННЫЕ
    записи (в сетке их нет — там они только мешали бы) и заметки стойки; и
    только здесь заметку можно убрать и вернуть, потому что карточки визита у
    неё нет по замыслу.
    ⛔ Один текст живёт в ЧЕТЫРЁХ длинах — 80 в списке, 60 в карточке сетки,
    полный в `cards` и полный в базе, — и с 19.09 обрезок больше не носит
    имени полного значения: правят `comment`, печатают `comment_cut`. До этого
    оба звались одинаково в разных словарях, оба были `str`, и взять не тот
    было нечем помешать (прайор 08-16).
    ⚠️ Врач — СНИМОК имени из самой строки, а не колонка сетки: у записи без
    `doctor_id` другого адреса нет, и переименование врача не двигает историю.
    """
    out = []
    for r in rows:
        is_note = r["source"] == "note"
        st = r["status"]
        out.append({
            "id": r["id"], "is_note": is_note,
            "time": r["starts_at"].astimezone(eng.TZ).strftime("%H:%M"),
            "name": "" if is_note else (r["name"] or ""),
            "age": None if is_note else _age(r.get("birth_year")),
            "phone": "" if is_note else (r["phone"] or ""),
            "service": r["service"] or "",
            "urgent": not is_note and r["service"] in eng.URGENT_LABELS,
            # полное значение — источник правки, обрезок — то, что
            # печатает строка списка; имена разные намеренно
            "comment": r["comment"] or "",
            "comment_cut": (r["comment"] or "")[:80],
            "doctor": r["doctor"] or "",
            "source": "note" if is_note else r["source"],
            "source_label": "notiță" if is_note else (
                "bot" if r["source"] == "bot" else "manual"),
            "status": st, "status_label": STATUS_LABEL.get(st, st),
            "reminded": bool(r.get("reminded_day")),
            "rec": bool(r.get("has_rec")),
        })
    return out


def _list(rows: list, back: str, title: str = "Lista zilei") -> str:
    """Таблица «Lista zilei». Что в строке — считает `list_rows`, здесь только
    разметка: тот же список отдаётся JSON API, и два разбора одной строки
    разошлись бы молча."""
    items = []
    for v in list_rows(rows):
        dt_txt = v["time"]
        is_note = v["is_note"]
        src = (_ic("note") if is_note else _ic("bot") if v["source"] == "bot"
               else _ic("pen")) + " " + v["source_label"]
        svc_txt = ((_ic("note") + " " if is_note else _ic("sos") + " "
                    if v["urgent"] else "")
                   + html.escape(v["service"]))
        if v["comment_cut"]:
            svc_txt += (f"<br><small style='color:#7a6a00'>{_ic('chat')} "
                        f"{html.escape(v['comment_cut'])}</small>")
        acts = "".join(
            f"<form class='act' method='post' action='/admin/status/{v['id']}'"
            + (f" onsubmit=\"return confirm('{b['confirm']}')\"" if b["confirm"] else "")
            + f"><input type='hidden' name='to' value='{b['to']}'>"
            f"<input type='hidden' name='back' value='{html.escape(back)}'>"
            f"<button class='{b['cls']}'>"
            f"{_ic('undo') + ' ' if b['cls'] == 'b-reopen' else ''}{b['label']}</button></form>"
            for b in status_actions(v["status"], is_note)
        )
        name_html = html.escape(v["name"])
        if not is_note and name_html:
            name_html = (f"<a class='plink' href='#' "
                         f"onclick=\"openCard({v['id']});return false\">{name_html}</a>")
            if v["age"]:
                name_html += f" <small style='color:#889'>({v['age']} ani)</small>"
        items.append(
            f"<tr class='{v['status']}'><td>{v['id']}</td><td>{dt_txt}</td>"
            f"<td>{name_html}</td><td>{html.escape(v['phone'])}</td>"
            f"<td>{svc_txt}</td><td>{html.escape(v['doctor'])}</td>"
            f"<td>{src}</td>"
            f"<td><span class='stat s-{v['status']}'>"
            f"{_STATUS_ICON.get(v['status'], '')}"
            f"{v['status_label']}</span>"
            f"{_REM_MARK if v['reminded'] else ''}"
            f"{_REC_MARK if v['rec'] else ''}</td><td>{acts}</td></tr>"
        )
    if not items:
        items = ["<tr><td colspan='9' style='color:var(--text3)'>— nicio programare —</td></tr>"]
    return (
        f"<h2>{title}</h2><table class='list'>"
        "<tr><th>#</th><th>Ora</th><th>Pacient</th><th>Telefon</th><th>Serviciu</th>"
        "<th>Medic</th><th>Sursă</th><th>Status</th><th>Acțiuni</th></tr>"
        + "".join(items) + "</table>"
    )


def _move_attrs(r: dict, dk: str, st: datetime) -> str:
    """`data-*` для перетаскивания — ОДНА разметка на обе дневные страницы.

    Канва и таблица рисуют визит по-разному, но перетаскивание у них общее, и
    договор с `panel.js` обязан быть один: разойдись он — на одной странице
    перенос молча перестал бы работать, а поймать это можно только руками.

    `data-busy` — «этот визит занимает интервал», ровно те статусы, что считает
    `db._conflicts`. По ним браузер предупреждает о столкновении ДО отправки;
    завершённый и отменённый визит места не занимают и сюда не попадают.
    ⛔ Тащить можно только активный визит и только из колонки НАСТОЯЩЕГО врача:
    колонка-сирота (легаси-имя без id) — не адрес, переносить оттуда некуда.
    """
    live = r["status"] in LIVE_STATUSES
    name = r["service"] if r["source"] == "note" else (r["name"] or "—")
    a = (f" data-min='{st.hour * 60 + st.minute}'"
         f" data-dur='{int(r.get('duration_min') or 60)}'"
         f" data-nm=\"{html.escape(str(name)[:40], quote=True)}\"")
    if dk:
        a += f" data-dk='{html.escape(dk, quote=True)}'"
    if live:
        a += " data-busy='1'"
        if dk:
            a += " draggable='true' data-mv='1'"
    return a


def _move_modal(d: date, back: str) -> str:
    """Подтверждение переноса: что, откуда, куда — и предупреждение о занятости.

    ⚠️ Диалог обязателен: перетащить мышью легко случайно, а визит — это
    человек, которому уже назвали время. Отдельная строка «de la» стоит здесь
    не для красоты: если блок уехал не туда, вернуть его можно только зная,
    откуда он.
    """
    b = html.escape(back)
    return f"""
<dialog id="movedlg">
  <div class="dlg-head"><span>Mutare programare</span>
    <button type="button" onclick="document.getElementById('movedlg').close()">{_ic('close')}</button></div>
  <div class="dlg-form">
    <div class="mv-rows">
      <div><span>Pacient</span><b id="mv_nm">—</b></div>
      <div><span>De la</span><b id="mv_from">—</b></div>
      <div><span>La</span><b id="mv_to">—</b></div>
    </div>
    <div class="banner err" id="mv_warn" style="display:none"></div>
    <form method="post" id="mv_form">
      <input type="hidden" name="back" value="{b}">
      <input type="hidden" name="mdate" value="{d.isoformat()}">
      <input type="hidden" name="mtime" id="mv_time">
      <input type="hidden" name="mdoctor" id="mv_doc">
      <div class="mv-act">
        <button type="button" class="mv-no"
          onclick="document.getElementById('movedlg').close()">Anulează</button>
        <button id="mv_yes">Da, mută</button>
      </div>
    </form>
  </div>
</dialog>"""


def _collect_cards(rows: list) -> dict:
    """Данные карточек для модалки — по ВСЕМ записям дня (вкл. отменённые), кроме заметок."""
    cards: dict = {}
    for r in rows:
        if r["source"] == "note":
            continue
        cards[r["id"]] = {
            "name": r["name"] or "—", "phone": r["phone"] or "",
            "service": r["service"], "doctor": r["doctor"],
            "time": r["starts_at"].astimezone(eng.TZ).strftime("%H:%M"),
            "comment": r["comment"] or "",
            "age": _age(r["birth_year"]),
            # состояние, а не «можно ли действовать»: набор кнопок в модалке
            # зависит от статуса так же, как в списке дня, и одним «да/нет»
            # его больше не выразить
            # ⚠️ Имя `status`, а не `st` (C26.5.3-a): ровно так это
            # поле зовётся в блоке сетки, и рядом с ним лежит
            # `status_label`. Два имени одного состояния в двух
            # словарях — это 08-12 и 08-16, и в контракте, который
            # пишется ради ОДНОГО канонического состояния, их быть
            # не может.
            "status": r["status"],
            "pid": r.get("patient_id"),
            # .get: не всякий вызывающий тянет флаг дневника из day_appointments
            "rec": bool(r.get("has_rec")),
        }
    return cards


def _card_modal(cards: dict, back: str) -> str:
    """Карточка записи по клику: инфо + комментарий ресепшена + статусы."""
    # js_json, а не json.dumps: комментарий вида "</script>…" не имеет права
    # вырваться из тега (см. core/layout.js_json)
    data = js_json(cards)
    b = html.escape(back)
    return f"""
<dialog id="carddlg">
  <div class="dlg-head"><span id="c_title">—</span>
    <button type="button" onclick="document.getElementById('carddlg').close()">{_ic('close')}</button></div>
  <div class="dlg-form">
    <div id="c_info" style="font-size:14px;color:var(--text2)"></div>
    <a id="c_fisa" href="#" style="font-size:12.5px;font-weight:600">{_ic('id')} Deschide fișa pacientului ›</a>
    <a id="c_visit" href="#" style="font-size:12.5px;font-weight:600">{_ic('med')} Consultația vizitei ›</a>
    <form id="c_form" method="post" style="display:flex;flex-direction:column;gap:8px">
      <input type="hidden" name="back" value="{b}">
      <textarea name="comment" id="c_text" rows="3" maxlength="300"
        placeholder="Comentariu: alergii, preferințe, de sunat înapoi…"
        style="resize:vertical"></textarea>
      <button>{_ic('chat')} Salvează comentariul</button>
    </form>
  </div>
  <div class="dlg-status" id="c_status">
    <form method="post" id="cs_waiting"><input type="hidden" name="to" value="waiting">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-waiting">A venit</button></form>
    <form method="post" id="cs_arrived"><input type="hidden" name="to" value="arrived">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-arrived">În cabinet</button></form>
    <form method="post" id="cs_done"><input type="hidden" name="to" value="done">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-done">Finalizat</button></form>
    <form method="post" id="cs_noshow"><input type="hidden" name="to" value="noshow">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-noshow">Nu a venit</button></form>
    <form method="post" id="cs_cancel"><input type="hidden" name="to" value="cancelled">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-cancel">Anulează</button></form>
    <form method="post" id="cs_reopen"
      onsubmit="return confirm('Redeschideți programarea (înapoi la «confirmată»)?')">
      <input type="hidden" name="to" value="confirmed">
      <input type="hidden" name="back" value="{b}">
      <button class="bstat b-reopen">{_ic('undo')} Redeschide</button></form>
  </div>
</dialog>
<script data-live>
/* data-live: panel.js исполняет скрипт заново после подмены живого куска —
   иначе CARDS остался бы от прошлого рендера, и клик по свежеприехавшей записи
   молча не открывал бы карточку. var, не const: повторное объявление const в
   общем scope — SyntaxError. */
var CARDS = {data};
var CS_SHOW = {{waiting: ['confirmed'], arrived: ['confirmed', 'waiting'],
                  done: ['confirmed', 'waiting', 'arrived'],
                  noshow: ['confirmed'],
                  cancel: ['confirmed', 'waiting', 'arrived'],
                  reopen: ['done', 'noshow', 'cancelled']}};
function openCard(id) {{
  const c = CARDS[id];
  if (!c) return;
  document.getElementById('c_title').textContent = c.time + ' — ' + c.name;
  document.getElementById('c_info').textContent =
    c.service + ' · ' + c.doctor + (c.phone ? ' · ' + c.phone : '')
    + (c.age ? ' · ' + c.age + ' ani' : '');
  document.getElementById('c_text').value = c.comment;
  const fl = document.getElementById('c_fisa');
  if (c.pid) {{ fl.style.display = 'inline'; fl.href = '/admin/patient/' + c.pid; }}
  else fl.style.display = 'none';
  const vl = document.getElementById('c_visit');
  if (c.pid) {{
    vl.style.display = 'inline';
    vl.href = '/admin/visit/' + id + '?back={urllib.parse.quote(back, safe='')}';
    vl.textContent = c.rec ? 'Vezi consultația ›' : 'Completează consultația ›';
  }} else vl.style.display = 'none';
  document.getElementById('c_form').action = '/admin/comment/' + id;
  // какие кнопки исхода показывать — ТОТ ЖЕ разбор, что в списке дня
  // (_ACT_BUTTONS): в кресле не предлагаем «A sosit» и «Nu a venit», у
  // закрытой записи остаётся только возврат. Раньше здесь стоял один флаг
  // canAct, и закрытая запись теряла ВСЕ кнопки разом.
  for (const k in CS_SHOW) {{
    const f = document.getElementById('cs_' + k);
    f.action = '/admin/status/' + id;
    f.style.display = CS_SHOW[k].indexOf(c.status) < 0 ? 'none' : '';
  }}
  document.getElementById('carddlg').showModal();
}}
</script>"""


# --- палитра врачей и цвет записи ПО ТИПУ процедуры (референс v2) ---
# палитра карточек врача (макет 08-03): зелёный / синий / фиолетовый / янтарный —
# первые четыре цвета намеренно максимально различимы, дальше по кругу
_DOC_HUES = ["#10B981", "#3B82F6", "#8B5CF6", "#F59E0B", "#DC2626", "#0891B2",
             "#6366F1", "#DB2777"]


# палитра для явного цвета услуги в Setări (значение → фон/полоса)
SVC_PALETTE = {
    "green": ("var(--green-soft)", "var(--green)"),
    "blue": ("var(--blue-soft)", "var(--blue)"),
    "amber": ("var(--amber-soft)", "var(--amber)"),
    "violet": ("var(--violet-soft)", "var(--violet)"),
    "red": ("var(--red-soft)", "var(--red)"),
    "teal": ("var(--teal-soft)", "var(--teal)"),
}


# Пометка «визит записан в дневник» — со своим классом: по нему её
# находит и стиль, и проверка в test_visit. Без класса единственным
# признаком был бы сам значок, а он есть и в меню («Medici»).
_REM_MARK = (" <span class='rem-mark' title='Reminder trimis'>"
             + _ic("bell") + "</span>")
_REC_MARK = (" <span class='rec-mark' title='Consultație completată'>"
             + _ic("med") + "</span>")

_STATUS_ICON = {"confirmed": _ic("clock"), "waiting": _ic("hourglass"),
                "arrived": _ic("checkin"), "done": _ic("check"),
                "noshow": _ic("ban")}


def _doctors_dir() -> pathlib.Path:
    base = _data_dir() or pathlib.Path("data")
    d = base / "files" / "doctors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _photo_path(dk: str) -> pathlib.Path | None:
    """Файл фото врача. Имя приходит из clinic.json — а его правят и руками,
    поэтому проверяем, что путь действительно внутри папки фотографий."""
    fn = str(eng.DOCTOR_META.get(dk, {}).get("photo") or "")
    if not fn or fn != pathlib.Path(fn).name:
        return None
    base = _doctors_dir()
    p = base / fn
    try:
        if p.resolve().parent != base.resolve() or not p.is_file():
            return None
    except OSError:
        return None
    return p


def photo_url(dk: str) -> str:
    """Адрес фото врача — ТОТ ЖЕ, что рисует `_avatar` и что печатает канва
    дня: `?v=` — имя файла, и кэш браузера сбрасывается сам при замене фото.

    ⚠️ Лежит в `core`, потому что спрашивают ДВА модуля — врачи (`/api/doctors`)
    и журнал (модель канвы). Копия формулы в каждом из них разошлась бы молча:
    у одного экрана фото обновилось бы после замены, у другого осталось бы
    старым из кэша, и выглядело бы это как «фото не сохранилось».
    """
    p = _photo_path(dk)
    if not p:
        return ""
    return (f"/admin/doctor-photo/{urllib.parse.quote(dk)}"
            f"?v={urllib.parse.quote(p.name)}")


def _doc_hue(dk: str) -> str:
    meta = eng.DOCTOR_META.get(dk, {})
    if meta.get("color"):
        return meta["color"]
    keys = list(eng.DOCTORS)
    idx = keys.index(dk) if dk in keys else 0
    return _DOC_HUES[idx % len(_DOC_HUES)]


def _avatar(dk: str, name: str, big: bool = False) -> str:
    # файл проверяем на месте: конфиг может указывать на удалённое фото —
    # инициалы честнее «сломанной картинки»
    photo = _photo_path(dk).name if _photo_path(dk) else ""
    inner = html.escape(_initials(name))   # имя врача правит человек: «<» бывает
    if photo:
        # ?v= — имя файла меняется при замене, значит кэш браузера сам сбросится
        src = (f"/admin/doctor-photo/{urllib.parse.quote(dk)}"
               f"?v={urllib.parse.quote(str(photo))}")
        inner = f"<img src='{src}' alt=''>"
    return (f"<span class='avatar{' big' if big else ''}' "
            f"style='background:{html.escape(_doc_hue(dk))}'>{inner}</span>")
