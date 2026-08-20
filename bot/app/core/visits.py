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


def _list(rows: list, back: str, title: str = "Lista zilei") -> str:
    items = []
    for r in rows:
        dt_txt = r["starts_at"].astimezone(eng.TZ).strftime("%H:%M")
        is_note = r["source"] == "note"
        src = _ic("note") + " notiță" if is_note else (_ic("bot") + " bot" if r["source"] == "bot" else _ic("pen") + " manual")
        svc_txt = ((_ic("note") + " " if is_note else _ic("sos") + " "
                    if r["service"] in eng.URGENT_LABELS else "")
                   + html.escape(r["service"]))
        if r["comment"]:
            svc_txt += (f"<br><small style='color:#7a6a00'>{_ic('chat')} "
                        f"{html.escape(r['comment'][:80])}</small>")
        buttons = ((_NOTE_BUTTONS if is_note else _ACT_BUTTONS)
                   .get(r["status"], ()))
        # возврат спрашивают подтверждением: это отмена уже записанного факта,
        # а не следующий шаг приёма (так же ведёт себя «Redeschide» в плане)
        ask = ("Restabiliți notița?" if is_note
               else "Redeschideți programarea (înapoi la «confirmată»)?")
        acts = "".join(
            f"<form class='act' method='post' action='/admin/status/{r['id']}'"
            + (f" onsubmit=\"return confirm('{ask}')\"" if cls == "b-reopen" else "")
            + f"><input type='hidden' name='to' value='{to}'>"
            f"<input type='hidden' name='back' value='{html.escape(back)}'>"
            f"<button class='{cls}'>"
            f"{_ic('undo') + ' ' if cls == 'b-reopen' else ''}{label}</button></form>"
            for to, cls, label in buttons
        )
        name_html = html.escape(r["name"] or "")
        if not is_note and name_html:
            name_html = (f"<a class='plink' href='#' "
                         f"onclick=\"openCard({r['id']});return false\">{name_html}</a>")
            a = _age(r["birth_year"])
            if a:
                name_html += f" <small style='color:#889'>({a} ani)</small>"
        items.append(
            f"<tr class='{r['status']}'><td>{r['id']}</td><td>{dt_txt}</td>"
            f"<td>{name_html}</td><td>{html.escape(r['phone'] or '')}</td>"
            f"<td>{svc_txt}</td><td>{html.escape(r['doctor'])}</td>"
            f"<td>{src}</td>"
            f"<td><span class='stat s-{r['status']}'>"
            f"{_STATUS_ICON.get(r['status'], '')}"
            f"{STATUS_LABEL.get(r['status'], r['status'])}</span>"
            f"{_REM_MARK if r['reminded_day'] else ''}"
            f"{_REC_MARK if r.get('has_rec') else ''}</td><td>{acts}</td></tr>"
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
            "st": r["status"],
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
    f.style.display = CS_SHOW[k].indexOf(c.st) < 0 ? 'none' : '';
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
