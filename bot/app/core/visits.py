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
from .layout import (LIVE_STATUSES, STATUS_LABEL, _age, _ic, _initials, js_json)
from .storage import _data_dir


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(eng.TZ).date()


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
        acts = ""
        if r["status"] in LIVE_STATUSES:
            buttons = ([("cancelled", "b-cancel", "Șterge")] if is_note else [
                ("arrived", "b-arrived", "A sosit"),
                ("done", "b-done", "Finalizat"),
                ("noshow", "b-noshow", "Nu a venit"),
                ("cancelled", "b-cancel", "Anulează"),
            ])
            acts = "".join(
                f"<form class='act' method='post' action='/admin/status/{r['id']}'>"
                f"<input type='hidden' name='to' value='{to}'>"
                f"<input type='hidden' name='back' value='{html.escape(back)}'>"
                f"<button class='{cls}'>{label}</button></form>"
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
            "canAct": r["status"] in LIVE_STATUSES,
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
    <form method="post" id="cs_arrived"><input type="hidden" name="to" value="arrived">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-arrived">A sosit</button></form>
    <form method="post" id="cs_done"><input type="hidden" name="to" value="done">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-done">Finalizat</button></form>
    <form method="post" id="cs_noshow"><input type="hidden" name="to" value="noshow">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-noshow">Nu a venit</button></form>
    <form method="post" id="cs_cancel"><input type="hidden" name="to" value="cancelled">
      <input type="hidden" name="back" value="{b}"><button class="bstat b-cancel">Anulează</button></form>
  </div>
</dialog>
<script>
const CARDS = {data};
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
  document.getElementById('cs_arrived').action = '/admin/status/' + id;
  document.getElementById('cs_done').action = '/admin/status/' + id;
  document.getElementById('cs_noshow').action = '/admin/status/' + id;
  document.getElementById('cs_cancel').action = '/admin/status/' + id;
  document.getElementById('c_status').style.display = c.canAct ? 'flex' : 'none';
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

_STATUS_ICON = {"confirmed": _ic("clock"), "arrived": _ic("checkin"),
                "done": _ic("check"), "noshow": _ic("ban")}


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
