import asyncio
import csv
import hmac
import html
import io
import json
import os
import pathlib
import logging
import re
import secrets
import sys
import urllib.parse
from datetime import date, datetime, timedelta

import qrcode
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)

from . import brand
from . import db
from . import engine as eng
from . import paths
from . import update as upd
# Общий слой. Имена оставлены прежними намеренно: переезжают ОПРЕДЕЛЕНИЯ, а
# места использования (их больше сотни) остаются нетронутыми — так видно, что
# перенос ничего не переписал по дороге.
from .core.auth import (ADMIN_KEY, _guard, _pin_hash, _pin_rec, _secret,
                        _set_auth_cookie, _setup_allowed, _write_pin)
from .core.layout import (FEEDBACK_EMAIL, LIVE_STATUSES, LOGIN_TMPL,
                          MSG_BANNER, SETUP_TMPL, STATIC, STATUS_LABEL, _age,
                          _asset, _banner, _ic, _initials, _shell, _tg_state)
from .core.storage import _data_dir
from .modules.patients import routes as patients

app = FastAPI(title="DentPilot")
log = logging.getLogger("web")

# Модули подключаются здесь и только здесь. Модуль знает про core, db и engine,
# но ничего не знает про main.py — иначе импорт замкнулся бы в круг.
app.include_router(patients.router)








@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    """Отсекает гигантские POST-тела ДО того, как Starlette спулит multipart
    во временный файл (сам по себе роут-кап 25MB срабатывает уже после)."""
    if request.method == "POST":
        cl = request.headers.get("content-length", "")
        if cl.isdigit() and int(cl) > (26) * 1024 * 1024:  # 25MB файла + запас
            return Response("Payload too large", status_code=413)
    return await call_next(request)























PIN_INPUT = ("<input type='password' name='password' placeholder='PIN' autofocus required "
             "inputmode='numeric' pattern='[0-9]*' maxlength='6' "
             "style='text-align:center;font-size:28px;letter-spacing:12px'>")
PASS_INPUT = "<input type='password' name='password' placeholder='Parola' autofocus required>"
PIN_HINT = ("<div style='color:#889;font-size:12px'>PIN uitat? Închideți programul și "
            "ștergeți fișierul <b>data\\auth.json</b> — la pornire veți seta un PIN nou.</div>")






















def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(eng.TZ).date()


def _date_nav(d: date, base: str, extra: str = "") -> str:
    prev_d, next_d = d - timedelta(days=1), d + timedelta(days=1)
    wk_prev, wk_next = d - timedelta(days=7), d + timedelta(days=7)
    lbl = eng.day_label(eng.Session(lang="ro"), d)
    picker = (f"<form class='dpickf' method='get' action='{base}'>"
              f"<input class='dpick' type='date' name='date' value='{d.isoformat()}' "
              f"onchange='this.form.submit()' title='Alege data (calendar)'></form>")
    return (f"<div class='nav'><b>{lbl} {d.isoformat()}</b>"
            f"<a href='{base}?date={wk_prev.isoformat()}' title='-7 zile'>◀◀</a>"
            f"<a href='{base}?date={prev_d.isoformat()}'>◀ {prev_d.strftime('%d.%m')}</a>"
            f"<a href='{base}'>Azi</a>"
            f"<a href='{base}?date={next_d.isoformat()}'>{next_d.strftime('%d.%m')} ▶</a>"
            f"<a href='{base}?date={wk_next.isoformat()}' title='+7 zile'>▶▶</a>"
            f"{picker}{extra}</div>")




def _grid(d: date, doctors_items: list, active: dict, href_fn,
          cards: dict | None = None) -> str:
    hours = [x.hour for x in eng.day_slots(d)]
    out = ["<table class='grid'><tr><th></th>"]
    for dk, name in doctors_items:
        spec = eng.DOCTOR_SPEC.get(dk, "")
        if not eng.DOCTOR_META.get(dk, {}).get("active", True):
            spec = (spec + " · inactiv").strip(" ·")
        out.append(f"<th><a href='/admin/doctor/{dk}?date={d.isoformat()}'>{html.escape(name)}</a>"
                   f"<br><small style='font-weight:400;opacity:.8'>{html.escape(spec)}</small></th>")
    out.append("</tr>")
    starts, covered = active
    # ⚠️ выключенному врачу писать нельзя (проверка в /admin/add), а «+» у него
    # рисовался наравне со всеми: клик открывал модалку, и любая отправка
    # возвращалась с «Date invalide» — тупик без единого намёка на причину.
    off = {dk for dk, _n in doctors_items
           if not eng.DOCTOR_META.get(dk, {}).get("active", True)}
    for h in hours:
        out.append(f"<tr><td class='hour'>{h:02d}:00</td>")
        for dk, dname in doctors_items:
            rs = starts.get((dk, h)) or starts.get((dname, h)) or []
            if not rs:
                if (dk, h) in covered or (dname, h) in covered:
                    # час накрыт длинным визитом — «+» тут врал бы
                    out.append("<td><div class='appt busy'>⏳ ocupat</div></td>")
                elif dk in off:
                    out.append("<td></td>")
                else:
                    args = html.escape(json.dumps([dk, dname, f"{h:02d}:00"]), quote=True)
                    out.append(
                        f"<td><a class='free' href='{href_fn(dk, h)}' "
                        f"onclick=\"openSlot.apply(null,{args});return false\">+</a></td>")
                continue
            cell = []
            for r in rs:   # в часе может быть две записи (10:00 и 10:30)
                hhmm = r["starts_at"].astimezone(eng.TZ).strftime("%H:%M")
                dur = int(r.get("duration_min") or 60)
                if r["source"] == "note":
                    cell.append(f"<div class='appt note'>📝 {hhmm} {html.escape(r['service'])}</div>")
                    continue
                src = "🤖" if r["source"] == "bot" else "✍️"
                urgent = r["service"] in eng.URGENT_LABELS
                cls = r["status"] + (" urgent" if urgent else "")
                svc_txt = ("🆘 " if urgent else "") + html.escape(r["service"])
                click = ""
                if cards is not None and r["id"] in cards:
                    cls += " clickable"
                    click = f" onclick=\"openCard({r['id']})\""
                cmt = (f"<div class='cmt'>💬 {html.escape((r['comment'] or '')[:60])}</div>"
                       if r["comment"] else "")
                a = _age(r["birth_year"])
                age_txt = f" <small style='color:#889'>{a} a.</small>" if a else ""
                cell.append(
                    f"<div class='appt {cls}'{click}><b>{hhmm} · {html.escape(r['name'] or '—')}</b>"
                    f"{age_txt} {src}<br>{svc_txt} <small>({dur}′)</small>"
                    f"<br><small>{html.escape(r['phone'] or '')}</small>{cmt}</div>")
            out.append("<td>" + "".join(cell) + "</td>")
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def _form(d: date, doctors_items: list, sel_doctor: str, sel_time: str, back: str) -> str:
    # 30-мин шаг (v1.8.0), но только те старты, где помещается минимум 30 минут
    # приёма внутри рабочего окна клиники (не предлагаем 17:30 при закрытии в 18)
    half = []
    for x in eng.day_slots(d):
        for m in (0, 30):
            st = x.replace(minute=m)
            if eng.fits_clinic(st, 30):
                half.append(st.strftime("%H:%M"))
    time_opts = "".join(
        f"<option value='{t}'{' selected' if sel_time == t else ''}>{t}</option>"
        for t in half
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
    return f"""
<h2 id="addform">✍️ Adaugă programare manual (telefon / recepție)</h2>
<form class="add" method="post" action="/admin/add">
  <input type="hidden" name="back" value="{html.escape(back)}">
  <input type="date" name="adate" value="{d.isoformat()}" required>
  <select name="atime">{time_opts}</select>
  {doc_field}
  <select name="aservice">{svc_opts}</select>
  <input name="aname" placeholder="Nume pacient" required>
  <input name="aphone" placeholder="Telefon" required>
  <input name="ayear" type="number" min="1900" max="2026" placeholder="An naștere (opț.)" style="width:140px">
  <button>Adaugă</button>
</form>"""


def _list(rows: list, back: str, title: str = "Lista zilei") -> str:
    items = []
    for r in rows:
        dt_txt = r["starts_at"].astimezone(eng.TZ).strftime("%H:%M")
        is_note = r["source"] == "note"
        src = "📝 notiță" if is_note else ("🤖 bot" if r["source"] == "bot" else "✍️ manual")
        svc_txt = (("📝 " if is_note else "🆘 " if r["service"] in eng.URGENT_LABELS else "")
                   + html.escape(r["service"]))
        if r["comment"]:
            svc_txt += (f"<br><small style='color:#7a6a00'>💬 "
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
            f"<td>{src}</td><td>{STATUS_LABEL.get(r['status'], r['status'])}"
            f"{' 🔔' if r['reminded_day'] else ''}</td><td>{acts}</td></tr>"
        )
    if not items:
        items = ["<tr><td colspan='9' style='color:var(--text3)'>— nicio programare —</td></tr>"]
    return (
        f"<h2>{title}</h2><table class='list'>"
        "<tr><th>#</th><th>Ora</th><th>Pacient</th><th>Telefon</th><th>Serviciu</th>"
        "<th>Medic</th><th>Sursă</th><th>Status</th><th>Acțiuni</th></tr>"
        + "".join(items) + "</table>"
    )


def _slot_modal(d: date, back: str) -> str:
    """Модалка по клику на «+»: записать пациента ИЛИ заметка/блокировка слота."""
    svc_opts = "".join(
        f"<option value='{k}'>{html.escape(v['ro'])}</option>" for k, v in eng.SERVICES.items()
    )
    return f"""
<dialog id="slotdlg">
  <div class="dlg-head"><span id="m_title">—</span>
    <button type="button" onclick="document.getElementById('slotdlg').close()">✕</button></div>
  <div class="dlg-tabs">
    <button type="button" id="tb_a" class="tabbtn on" onclick="showTab('a')">👤 Programare</button>
    <button type="button" id="tb_n" class="tabbtn" onclick="showTab('n')">📝 Notiță / blocare</button>
  </div>
  <form id="tab_a" class="dlg-form" method="post" action="/admin/add">
    <input type="hidden" name="back" value="{html.escape(back)}">
    <input type="hidden" name="adate" value="{d.isoformat()}">
    <input type="hidden" name="atime" id="m_time_a">
    <input type="hidden" name="adoctor" id="m_doc_a">
    <select name="aservice">{svc_opts}</select>
    <input name="aname" placeholder="Nume pacient" required>
    <input name="aphone" placeholder="Telefon" required>
    <input name="ayear" type="number" min="1900" max="2026" placeholder="An naștere (opțional)">
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
const NOTE_ENDS = {json.dumps([x.hour + 1 for x in eng.day_slots(d)])};
function openSlot(dk, dname, hh) {{
  document.getElementById('m_doc_a').value = dk;
  document.getElementById('m_doc_n').value = dk;
  document.getElementById('m_time_a').value = hh;
  document.getElementById('m_time_n').value = hh;
  document.getElementById('m_title').textContent = dname + ' — ' + hh;
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
        }
    return cards


def _card_modal(cards: dict, back: str) -> str:
    """Карточка записи по клику: инфо + комментарий ресепшена + статусы."""
    # .replace("</", ...) — комментарий "</script>…" не должен вырваться из тега
    data = json.dumps(cards, ensure_ascii=True).replace("</", "<\\/")
    b = html.escape(back)
    return f"""
<dialog id="carddlg">
  <div class="dlg-head"><span id="c_title">—</span>
    <button type="button" onclick="document.getElementById('carddlg').close()">✕</button></div>
  <div class="dlg-form">
    <div id="c_info" style="font-size:14px;color:var(--text2)"></div>
    <a id="c_fisa" href="#" style="font-size:12.5px;font-weight:600">📇 Deschide fișa pacientului →</a>
    <form id="c_form" method="post" style="display:flex;flex-direction:column;gap:8px">
      <input type="hidden" name="back" value="{b}">
      <textarea name="comment" id="c_text" rows="3" maxlength="300"
        placeholder="Comentariu: alergii, preferințe, de sunat înapoi…"
        style="resize:vertical"></textarea>
      <button>💬 Salvează comentariul</button>
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
    c.service + ' · ' + c.doctor + (c.phone ? ' · 📞 ' + c.phone : '')
    + (c.age ? ' · ' + c.age + ' ani' : '');
  document.getElementById('c_text').value = c.comment;
  const fl = document.getElementById('c_fisa');
  if (c.pid) {{ fl.style.display = 'inline'; fl.href = '/admin/patient/' + c.pid; }}
  else fl.style.display = 'none';
  document.getElementById('c_form').action = '/admin/comment/' + id;
  document.getElementById('cs_arrived').action = '/admin/status/' + id;
  document.getElementById('cs_done').action = '/admin/status/' + id;
  document.getElementById('cs_noshow').action = '/admin/status/' + id;
  document.getElementById('cs_cancel').action = '/admin/status/' + id;
  document.getElementById('c_status').style.display = c.canAct ? 'flex' : 'none';
  document.getElementById('carddlg').showModal();
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


@app.on_event("startup")
async def startup() -> None:
    if not db.IS_SQLITE and not ADMIN_KEY:
        # Postgres = серверный режим: с v1.6.0 в журнале мед-данные и файлы,
        # fail-open без ключа недопустим — падаем громко, а не открываемся тихо
        raise RuntimeError("ADMIN_KEY is required for the Postgres edition — set it in .env")
    try:
        seed_rows = eng.build_seed_rows()
    except Exception as e:  # noqa: BLE001 — демо-наполнение НЕ должно валить старт
        logging.getLogger("startup").warning("build_seed_rows failed: %r", e)
        seed_rows = []
    await db.init(seed_rows)
    # v1.7.1: старым записям проставляются стабильные ключи по текущему конфигу;
    # идемпотентно (только NULL), на каждом старте — дёшево и самозалечивается
    doc_map = {name: k for k, name in eng.DOCTORS.items()}
    svc_map = {}
    for k, v in eng.SERVICES.items():
        svc_map[v["ro"]] = k
        svc_map[v["ru"]] = k
    await db.backfill_ids(doc_map, svc_map)
    upd.sync_uninstall_version()   # версия в «Программах и компонентах»
    upd.check_async()
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if token:
        from . import telegram as tg

        async def _tg_guard() -> None:
            try:
                await tg.run(token)
            except Exception as e:  # noqa: BLE001 — веб-чат должен жить при любой ошибке TG
                print(f"Telegram adapter FAILED: {e!r} — web chat keeps running")

        asyncio.create_task(_tg_guard())
        print("Telegram adapter: starting (token present)")
    else:
        print("TELEGRAM_TOKEN not set — Telegram adapter disabled (web chat only)")


@app.get("/health")
async def health() -> dict:
    # "app" = отпечаток для single-instance guard в desktop.py:
    # чужой сервис с {"ok":true} на нашем порту не должен сойти за нас
    return {"ok": True, "app": "dentpilot", "version": eng.APP_VERSION}


@app.get("/static/css/{name}")
async def static_css(name: str) -> Response:
    """Оформление журнала. Кеш вечный намеренно: адрес несёт версию программы
    (?v=…), поэтому после обновления браузер запросит новый файл, а между
    обновлениями не будет тянуть 45 КБ на каждую автоперезагрузку страницы —
    а она происходит раз в 12 секунд на каждом открытом экране."""
    if not re.fullmatch(r"[a-z0-9_-]+\.css", name):
        return Response(status_code=404)
    try:
        text = _asset("css", name)
    except OSError:
        log.error("не читается стиль %s — интерфейс останется без оформления", name)
        return Response(status_code=404)
    cache = ("public, max-age=31536000, immutable" if paths.is_frozen()
             else "no-cache")
    return Response(text, media_type="text/css",
                    headers={"Cache-Control": cache})


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Тот же знак во вкладке браузера. Браузер сам просит /favicon.ico, поэтому
    один роут закрывает все страницы, включая печатные."""
    return Response(brand.mark_svg(None), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    return page.replace("{{CLINIC_NAME}}", html.escape(eng.CLINIC_NAME))


@app.post("/chat")
async def chat(payload: dict):
    sid = str(payload.get("session_id") or "").strip()[:64]
    if not sid:
        return {"messages": [{"text": "session_id required"}], "buttons": []}
    msg = str(payload.get("message") or "/start")[:500]
    s = eng.get_session(sid)
    texts, buttons = await eng.handle(s, sid, msg)
    return {"messages": [{"text": x} for x in texts], "buttons": buttons}


# ---------- домашняя страница журнала: сводка + карточки врачей ----------

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(next: str = "/admin", err: str = ""):
    if not _secret():
        return RedirectResponse("/admin", status_code=303)
    pin_mode = _pin_rec() is not None
    err_html = ("<div class='err'>PIN greșit</div>" if pin_mode
                else "<div class='err'>Parolă greșită</div>") if err else ""
    nxt = next if next.startswith("/admin") else "/admin"
    return (LOGIN_TMPL.replace("__CLINIC__", html.escape(eng.CLINIC_NAME))
            .replace("__ERR__", err_html).replace("__NEXT__", html.escape(nxt))
            .replace("__INPUT__", PIN_INPUT if pin_mode else PASS_INPUT)
            .replace("__HINT__", PIN_HINT if pin_mode else ""))


@app.post("/admin/login")
async def admin_login(password: str = Form(...), next_url: str = Form("/admin", alias="next")):
    target = next_url if next_url.startswith("/admin") else "/admin"
    pw = password.strip()
    rec = _pin_rec()
    if rec:
        ok = hmac.compare_digest(_pin_hash(pw, rec.get("salt", "")), rec.get("hash", ""))
    else:
        ok = bool(ADMIN_KEY) and hmac.compare_digest(pw, ADMIN_KEY)
    if ok:
        return _set_auth_cookie(RedirectResponse(target, status_code=303))
    return RedirectResponse(
        f"/admin/login?err=1&next={urllib.parse.quote(target, safe='')}", status_code=303)






@app.get("/admin/setup", response_class=HTMLResponse)
async def admin_setup_page(err: str = ""):
    if not _setup_allowed():
        return RedirectResponse("/admin", status_code=303)
    err_html = "<div class='err'>PIN-urile nu coincid sau nu au 4–6 cifre</div>" if err else ""
    return (SETUP_TMPL.replace("__CLINIC__", html.escape(eng.CLINIC_NAME))
            .replace("__ERR__", err_html))




@app.post("/admin/setup")
async def admin_setup(pin1: str = Form(...), pin2: str = Form(...)):
    if not _setup_allowed():
        return RedirectResponse("/admin", status_code=303)
    p1, p2 = pin1.strip(), pin2.strip()
    if p1 != p2 or not p1.isdigit() or not (4 <= len(p1) <= 6):
        return RedirectResponse("/admin/setup?err=1", status_code=303)
    _write_pin(p1)
    return _set_auth_cookie(RedirectResponse("/admin", status_code=303))


@app.post("/admin/pin/change")
async def admin_pin_change(request: Request, old_pin: str = Form(...),
                           new1: str = Form(...), new2: str = Form(...)):
    if (deny := _guard(request)) is not None:
        return deny
    rec = _pin_rec()
    if not rec:
        return RedirectResponse("/admin/settings?msg=bad_pin", status_code=303)
    if not hmac.compare_digest(_pin_hash(old_pin.strip(), rec.get("salt", "")),
                               rec.get("hash", "")):
        return RedirectResponse("/admin/settings?msg=bad_pin", status_code=303)
    n1, n2 = new1.strip(), new2.strip()
    if n1 != n2 or not n1.isdigit() or not (4 <= len(n1) <= 6):
        return RedirectResponse("/admin/settings?msg=bad_pin", status_code=303)
    _write_pin(n1)
    return _set_auth_cookie(RedirectResponse("/admin/settings?msg=ok_pin", status_code=303))


# --- палитра врачей и цвет записи ПО ТИПУ процедуры (референс v2) ---
# палитра карточек врача (макет 08-03): зелёный / синий / фиолетовый / янтарный —
# первые четыре цвета намеренно максимально различимы, дальше по кругу
_DOC_HUES = ["#10B981", "#3B82F6", "#8B5CF6", "#F59E0B", "#DC2626", "#0891B2",
             "#6366F1", "#DB2777"]

_SVC_CAT = [
    (re.compile(r"urgent|sos|durere|acut", re.I), ("var(--red-soft)", "var(--red)")),
    (re.compile(r"implant|extract|chirur|sinus", re.I), ("var(--blue-soft)", "var(--blue)")),
    (re.compile(r"hyg|igien|airflow|detartraj|fluor", re.I), ("var(--amber-soft)", "var(--amber)")),
    (re.compile(r"whiten|albire|estet|fatet|venir", re.I), ("var(--violet-soft)", "var(--violet)")),
]




# палитра для явного цвета услуги в Setări (значение → фон/полоса)
SVC_PALETTE = {
    "green": ("var(--green-soft)", "var(--green)"),
    "blue": ("var(--blue-soft)", "var(--blue)"),
    "amber": ("var(--amber-soft)", "var(--amber)"),
    "violet": ("var(--violet-soft)", "var(--violet)"),
    "red": ("var(--red-soft)", "var(--red)"),
    "teal": ("var(--teal-soft)", "var(--teal)"),
}
_PALETTE_RO = {"green": "verde", "blue": "albastru", "amber": "portocaliu",
               "violet": "violet", "red": "roșu", "teal": "turcoaz"}


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




_STATUS_ICON = {"confirmed": "🕐", "arrived": "🟢", "done": "✅", "noshow": "❌"}

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
                    out.append(f"<div class='gappt gnote' style='{pos}'>"
                               f"<b>📝 {html.escape(r['service'][:40])}</b></div>")
                    continue
                bg, bar = _svc_colors(r)
                ico = "❗" if (r["service"] in eng.URGENT_LABELS
                              and r["status"] == "confirmed") \
                    else _STATUS_ICON.get(r["status"], "")
                src = "🤖" if r["source"] == "bot" else "✍️"
                ns = " noshow" if r["status"] == "noshow" else ""
                click = f" onclick=\"openCard({r['id']})\"" if r["id"] in cards else ""
                dur = int(r.get("duration_min") or 60)
                out.append(
                    f"<div class='gappt{ns}' style='{pos};"
                    f"background:{bg};border-left:3px solid {bar}'{click}>"
                    f"<span class='stt'>{ico}</span>"
                    f"<b>{html.escape(r['name'] or '—')} {src}</b>"
                    f"<small>{st.strftime('%H:%M')} · {dur}′ · {html.escape(r['service'])}</small></div>")
        return "".join(out)

    def _cells(dk: str | None, name: str) -> str:
        # рабочие часы КОНКРЕТНОГО врача (сужение work_from/work_to, v1.8.0)
        if dk is not None:
            b = eng.doctor_bounds(dk, d)
            work = set()
            if b:
                f_h, to_h, bf_h, bt_h = b
                work = {h for h in range(f_h, to_h) if not (bf_h <= h < bt_h)}
        else:
            work = set()
        out = []
        for h in hours:
            if dk is not None and h in work:
                # json+escape: имя врача с апострофом не ломает JS-обработчик
                args = html.escape(json.dumps([dk, name, f"{h:02d}:00"]), quote=True)
                out.append(f"<div class='gcell' onclick=\"openSlot.apply(null,{args})\"></div>")
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
        head.append(
            f"<div class='gh-doc'><div class='dcard{'' if not off else ' off'}' "
            f"style='border-left-color:{hue}'>"
            f"<span class='av' style='background:{hue}'>{av}</span>"
            f"<div class='nm'><a href='/admin/doctor/{dk}?date={d.isoformat()}' "
            f"title='{html.escape(extra)}'>{html.escape(name)}</a>"
            f"<small>{html.escape(eng.DOCTOR_SPEC.get(dk, '')) or '&nbsp;'}{off}</small>"
            f"<small class='mt'>{len(mine)} prog. · {liber}</small></div>"
            f"<span class='st' style='background:{dot}' title='{liber}'></span></div></div>")
        cols.append(f"<div class='gcol'>{_cells(dk, name)}{_blocks(col_key)}</div>")

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
            f"border-radius:6px;cursor:pointer'>→</button></form></div></div></div>")
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
    timecol = "".join(f"<div>{h:02d}:00</div>" for h in hours)
    # fitGrid: день заполняет окно до низа — высота ячейки тянется под вьюпорт
    # (короткая суббота не оставляет пустую страницу), минимум 56px + прокрутка
    fit_js = f"""<script>
function fitGrid() {{
  var gb = document.querySelector('.gridbody'), n = {len(hours)};
  if (!gb) return;
  gb.style.setProperty('--cell', '56px');
  var c = Math.max(56, Math.floor((window.innerHeight - gb.getBoundingClientRect().top - 24) / n));
  gb.style.setProperty('--cell', c + 'px');
  var over = document.documentElement.scrollHeight - window.innerHeight;
  if (over > 0) gb.style.setProperty('--cell', Math.max(56, c - Math.ceil(over / n)) + 'px');
}}
fitGrid();                                  // сразу, чтобы не мигало
document.addEventListener('DOMContentLoaded', fitGrid);  // и когда виден весь макет
window.addEventListener('resize', fitGrid);
</script>"""
    # шапка врачей вынесена ИЗ белой карточки сетки (макет Олега 08-03):
    # это отдельная полоса карточек над расписанием. Ширины те же (56px под
    # колонку времени + flex:1 на врача), поэтому карточка стоит ровно над
    # своей колонкой — выравнивание держится само.
    return (f"{''.join(head)}<div class='gridcard'>"
            f"<div class='gridbody'><div class='gcol-time'>{timecol}</div>"
            f"{''.join(cols)}{nowline}</div></div>{fit_js}")


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
    return ("<div class='botnew' id='botnew'><h3>🤖 Programări noi din bot (7 zile, ultimele 10)</h3>"
            + "".join(items) + "</div>")


@app.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, date_q: str = Query("", alias="date"), msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = await db.day_appointments(day_start, day_start + timedelta(days=1))
    yrows = await db.day_appointments(day_start - timedelta(days=1), day_start)

    def _counts(rr: list) -> tuple[int, int, int, int, int]:
        a = [r for r in rr if r["status"] != "cancelled" and r["source"] != "note"]
        return (len(a), sum(1 for r in a if r["source"] == "bot"),
                sum(1 for r in a if r["source"] == "manual"),
                sum(1 for r in a if r["service"] in eng.URGENT_LABELS),
                sum(1 for r in rr if r["status"] == "noshow"))

    total, n_bot, n_man, n_urg, n_noshow = _counts(rows)
    y_total, _yb, y_man, _yu, y_noshow = _counts(yrows)

    def trend(cur: int, prev: int, bad_up: bool = False) -> str:
        diff = cur - prev
        if diff == 0:
            return "<span class='trend'>la fel ca ieri</span>"
        cls = ("dn" if bad_up else "up") if diff > 0 else ("up" if bad_up else "dn")
        arrow = "▲" if diff > 0 else "▼"
        return (f"<span class='trend'><span class='{cls}'>{arrow} {diff:+d}</span>"
                f" față de ieri</span>")

    now = datetime.now(eng.TZ)
    recent = await db.recent_bot_appointments(now - timedelta(days=7))
    new_today = sum(1 for r in recent
                    if r["created_at"].astimezone(eng.TZ).date() == now.date())

    day_url = f"/admin/all?date={d.isoformat()}"
    bot_sub = (f"<span class='trend'><span class='up'>{new_today} noi</span> azi</span>"
               if new_today else "<span class='trend'>nimic nou azi</span>")
    tiles = (
        f"<div class='tiles'>"
        f"<a class='tile' href='{day_url}'>"
        f"<span class='ico' style='background:var(--green-soft);color:var(--green)'>📅</span>"
        f"<div><b>{total}</b><span>Programări azi</span>{trend(total, y_total)}</div></a>"
        f"<a class='tile' href='{day_url}&f=bot'>"
        f"<span class='ico' style='background:var(--teal-soft);color:var(--teal-d)'>🤖</span>"
        f"<div><b>{n_bot}</b><span>Prin bot</span>{bot_sub}</div></a>"
        f"<a class='tile' href='{day_url}&f=rec'>"
        f"<span class='ico' style='background:var(--blue-soft);color:var(--blue)'>🎧</span>"
        f"<div><b>{n_man}</b><span>Recepție</span>{trend(n_man, y_man)}</div></a>"
        f"<a class='tile warn' href='{day_url}&f=urg'>"
        f"<span class='ico' style='background:var(--amber-soft);color:var(--amber)'>⏰</span>"
        f"<div><b>{n_urg}</b><span>Urgențe</span>"
        f"<span class='trend'>intercalate azi</span></div></a>"
        f"<a class='tile bad' href='{day_url}&f=noshow'>"
        f"<span class='ico' style='background:var(--red-soft);color:var(--red)'>🚫</span>"
        f"<div><b>{n_noshow}</b><span>Neprezentări</span>"
        f"{trend(n_noshow, y_noshow, bad_up=True)}</div></a>"
        f"</div>"
    )

    cards = _collect_cards(rows)
    back = f"/admin?date={d.isoformat()}"
    tg_on, _u = _tg_state()
    sync = ("<div style='display:flex;align-items:center;gap:7px;font-size:11.5px;"
            "color:var(--text3);padding:0 4px'>"
            f"<span style='width:7px;height:7px;border-radius:50%;background:"
            f"{'var(--green)' if tg_on else 'var(--text3)'}'></span>"
            f"{'Sincronizat cu botul Telegram' if tg_on else 'Bot Telegram neconectat'}</div>")
    tabs = (f"<a class='primary' href='/admin?date={d.isoformat()}'>Zi</a>"
            f"<a href='/admin/week?date={d.isoformat()}'>Săptămâna</a>")
    body = (_date_nav(d, "/admin", tabs) + _banner(msg, d) + tiles
            + "<div class='dash'><div class='dashmain'>"
            + _day_canvas(d, rows, cards)
            + "<p class='hint'>Click pe o programare — detalii și statusuri; click pe un slot liber — programare nouă sau notiță. Programările prin bot apar automat.</p>"
            + "</div><div class='rail'>"
            + _mini_cal(d) + _botnew_block(recent, now) + sync
            + "</div></div>"
            + _slot_modal(d, back) + _card_modal(cards, back))
    return _shell(body, "panou principal · 🤖 bot / ✍️ recepție · se actualizează automat",
                  active="dash", bell=new_today)


@app.get("/admin/week", response_class=HTMLResponse)
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
                             f"color:var(--text2)'>📝 {hh} {html.escape(r['service'][:30])}</div>")
                continue
            bg, bar = _svc_colors(r)
            ns = " noshow" if r["status"] == "noshow" else ""
            chips.append(
                f"<div class='wchip{ns}' style='background:{bg};border-left:3px solid {bar}'>"
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
           f"<a href='/admin/week?date={prev_w}'>◀ săpt.</a>"
           f"<a href='/admin/week'>Azi</a>"
           f"<a href='/admin/week?date={next_w}'>săpt. ▶</a>"
           f"<a href='/admin?date={d.isoformat()}'>Zi</a>"
           f"<a class='primary' href='/admin/week?date={d.isoformat()}'>Săptămâna</a></div>")
    body = nav + f"<div class='week'>{''.join(cols)}</div>" + \
        "<p class='hint'>Click pe ziua din antet — deschide programul zilei.</p>"
    return _shell(body, "calendar săptămânal · culori după tipul procedurii", active="dash")


# ---------- настройки клиники ----------

_DOW_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DOW_FULL = {"mon": "Luni", "tue": "Marți", "wed": "Miercuri", "thu": "Joi",
             "fri": "Vineri", "sat": "Sâmbătă", "sun": "Duminică"}
_DOW_SHORT = {"ro": {"mon": "Lu", "tue": "Ma", "wed": "Mi", "thu": "Jo",
                     "fri": "Vi", "sat": "Sâ", "sun": "Du"},
              "ru": {"mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
                     "fri": "Пт", "sat": "Сб", "sun": "Вс"}}


def _hours_summary(hours: dict, lang: str) -> str:
    """'Lu–Vi 9:00–18:00, Sâ 9:00–14:00' из hours-словаря."""
    names = _DOW_SHORT[lang]
    parts = []
    i = 0
    while i < 7:
        h = hours.get(_DOW_ORDER[i])
        j = i
        while j + 1 < 7 and hours.get(_DOW_ORDER[j + 1]) == h:
            j += 1
        if h:
            rng = (names[_DOW_ORDER[i]] if i == j
                   else f"{names[_DOW_ORDER[i]]}–{names[_DOW_ORDER[j]]}")
            txt = f"{rng} {h[0]}:00–{h[1]}:00"
            if len(h) >= 4:
                txt += (f" (pauză {h[2]}:00–{h[3]}:00)" if lang == "ro"
                        else f" (перерыв {h[2]}:00–{h[3]}:00)")
            parts.append(txt)
        i = j + 1
    return ", ".join(parts)


# Единый диапазон часов для ВСЕХ выпадающих списков: часы клиники, обед,
# личное окно врача. Раньше их было три разных (0-23 / 6-21 / 7-23) — клиника
# видела в соседних полях разные наборы без всякой причины.
# 07:00 — самая ранняя разумная смена; потолок 21:00 намеренно выше вечерних
# 19-20, чтобы кабинет с поздним приёмом мог себя настроить.
HOUR_MIN, HOUR_MAX = 7, 21


def _hour_opts(sel: int, lo: int = HOUR_MIN, hi: int = HOUR_MAX) -> str:
    return "".join(
        f"<option value='{h}'{' selected' if h == sel else ''}>{h}:00</option>"
        for h in range(lo, hi + 1)
    )


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    cfg = eng.CONFIG
    e = html.escape

    def _break_opts(sel) -> str:
        out = [f"<option value=''{' selected' if sel is None else ''}>—</option>"]
        for x in range(HOUR_MIN, HOUR_MAX + 1):
            out.append(f"<option value='{x}'{' selected' if sel == x else ''}>{x}:00</option>")
        return "".join(out)

    hours_rows = []
    for day in _DOW_ORDER:
        h = cfg.get("hours", {}).get(day)
        closed = h is None
        hv = list(h) if h else [9, 18]
        f, t = int(hv[0]), int(hv[1])
        bf = int(hv[2]) if len(hv) >= 4 else None
        bt = int(hv[3]) if len(hv) >= 4 else None
        hours_rows.append(
            f"<tr><td>{_DOW_FULL[day]}</td>"
            f"<td><input type='checkbox' id='hc_{day}'{' checked' if closed else ''}> închis</td>"
            f"<td><select id='hf_{day}'>{_hour_opts(f)}</select></td>"
            f"<td><select id='ht_{day}'>{_hour_opts(t, HOUR_MIN + 1, HOUR_MAX)}</select></td>"
            f"<td><select id='hb_{day}'>{_break_opts(bf)}</select></td>"
            f"<td><select id='he_{day}'>{_break_opts(bt)}</select></td></tr>"
        )

    def _color_opts(sel: str) -> str:
        out = [f"<option value=''{' selected' if not sel else ''}>auto</option>"]
        for k, ro in _PALETTE_RO.items():
            out.append(f"<option value='{k}'{' selected' if sel == k else ''}>{ro}</option>")
        return "".join(out)

    # v1.9.0: таблица врачей уехала в раздел «Medici» — здесь только сводка,
    # чтобы у каталога врачей было ровно одно место правки
    doc_rows = "".join(
        f"<tr><td><a href='/admin/doctor-card/{e(d['id'])}'>{e(d['name'])}</a></td>"
        f"<td>{e(d.get('spec', '')) or '—'}</td><td>{e(d.get('room', '')) or '—'}</td>"
        f"<td>{e(d.get('phone', '')) or '—'}</td>"
        f"<td>{e(_doc_hours_text(d['id']))}</td>"
        f"<td><span class='dbadge {eng.doctor_state(d)}'>"
        f"{_DOC_STATE_RO[eng.doctor_state(d)]}</span></td></tr>"
        for d in cfg["doctors"]
    )
    def _dur_opts(sel) -> str:
        cur = int(sel) if sel else 60
        return "".join(f"<option value='{x}'{' selected' if cur == x else ''}>{x} min</option>"
                       for x in (15, 30, 45, 60, 90, 120))

    svc_rows = "".join(
        f"<tr><td><input type='hidden' class='s_id' value='{e(s['id'])}'>"
        f"<input type='text' class='s_ro' value='{e(s['ro'])}'></td>"
        f"<td><input type='text' class='s_ru' value='{e(s['ru'])}'></td>"
        f"<td><input type='text' class='s_price' value='{e(str(s.get('price', '')) if not isinstance(s.get('price'), dict) else s['price'].get('ro', ''))}'></td>"
        f"<td><select class='s_dur'>{_dur_opts(s.get('duration'))}</select></td>"
        f"<td><select class='s_color'>{_color_opts(s.get('color', ''))}</select></td>"
        f"<td style='text-align:center'><input type='checkbox' class='s_urg'{' checked' if s.get('urgent') else ''}></td>"
        f"<td><input type='text' class='s_docs' value='{e(' '.join(s.get('docs', [])))}' placeholder='gol = toți'></td>"
        f"<td><button type='button' class='rowdel' onclick='this.closest(\"tr\").remove()'>✖</button></td></tr>"
        for s in cfg["services"]
    )
    doc_ids_hint = ", ".join(f"{d['id']}={e(d['name'])}" for d in cfg["doctors"])

    banner = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        banner = f"<div class='banner {cls}'>{text}</div>"

    tgmod = sys.modules.get(f"{__package__}.telegram")
    tg_status = tgmod.STATUS if tgmod else {"running": False, "username": "", "error": ""}
    if tg_status["running"]:
        tg_line = f"✅ activ — @{html.escape(tg_status['username'])}"
    elif os.environ.get("TELEGRAM_TOKEN", "").strip():
        tg_line = f"⚠️ {html.escape(tg_status.get('error') or 'pornire…')}"
    else:
        tg_line = "— fără token (adăugați TELEGRAM_TOKEN în dental.env / .env)"
    if upd.can_self_update():
        up_line = (
            f"🔄 disponibilă {html.escape(upd.STATE['latest'])} "
            f"<form method='post' action='/admin/update/run' style='display:inline'>"
            f"<button style='background:#e8710a;color:#fff;border:none;border-radius:6px;"
            f"padding:6px 14px;cursor:pointer;font-size:14px;margin-left:8px'>"
            f"⬆️ Actualizează acum</button></form>"
        )
    elif upd.asset_pending() and upd.is_desktop():
        up_line = (f"🕐 versiunea {html.escape(upd.STATE['latest'])} este anunțată, "
                   f"dar fișierul programului încă nu e publicat — "
                   f"reverificăm automat peste câteva minute")
    elif upd.newer_available():
        up_line = (f"<a href='{html.escape(upd.STATE['url'])}' target='_blank'>"
                   f"🔄 disponibilă {html.escape(upd.STATE['latest'])} — descărcați</a>")
    elif upd.STATE["checked"] and not upd.STATE["error"]:
        up_line = "✅ la zi"
    elif upd.STATE["error"]:
        up_line = "— necunoscut (offline?)"
    else:
        up_line = "se verifică…"
    # Канал виден в интерфейсе намеренно: на этой машине обновление приходит
    # РАНЬШЕ, чем клиникам, и перепутать её с боевой установкой нельзя.
    chan_row = ""
    ch = upd.channel()
    if ch != "stable":
        # beta — публичные пре-релизы, ключ не нужен; draft — ещё и черновики,
        # но для них нужен токен с правом записи. Названия разные намеренно:
        # риск у этих двух режимов разный, и путать их нельзя.
        name = "🧪 draft (test)" if ch == "draft" else "🧪 beta (pre-lansări)"
        note = ""
        if upd.STATE.get("draft"):
            note = " · versiunea curentă din canal este nepublicată"
        elif upd.STATE.get("prerelease"):
            note = " · versiunea curentă din canal este pre-lansare"
        chan_row = (f"<tr><th>Canal actualizări</th><td>"
                    f"<b style='color:var(--amber-t)'>{name}</b> — "
                    "acest calculator vede versiunile ÎNAINTE de clinici"
                    + note + "</td></tr>")
    up_line += ("<form method='post' action='/admin/update/check' style='display:inline'>"
                "<button style='background:none;border:1px solid var(--line);border-radius:8px;"
                "padding:4px 10px;cursor:pointer;font-size:12px;color:var(--text2);"
                "margin-left:10px'>🔄 Verifică acum</button></form>")
    status_tbl = f"""
<h2>ℹ️ Stare sistem</h2>
<table class='set'>
<tr><th style='width:180px'>Versiune</th><td>v{eng.APP_VERSION}</td></tr>
<tr><th>Bază de date</th><td>{"SQLite (local, data/dental.db)" if db.IS_SQLITE else "PostgreSQL"}</td></tr>
<tr><th>Canal Telegram</th><td>{tg_line}</td></tr>
<tr><th>Actualizări</th><td>{up_line}</td></tr>
{chan_row}
<tr><th>Acces jurnal</th><td>{"🔒 PIN setat" if _pin_rec() else ("🔒 parolă (ADMIN_KEY)" if ADMIN_KEY else "🔓 deschis")}</td></tr>
<tr><th>Feedback / suport</th><td><a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a></td></tr>
</table>

<h2>🔐 Confidențialitate</h2>
<div class='pcard' style='max-width:760px'>
<p style='margin:0 0 8px;font-size:13px;line-height:1.55;color:var(--text2)'>
<b style='color:var(--text)'>Programul funcționează local.</b> Datele personale ale pacienților
nu sunt transmise dezvoltatorului și nu sunt stocate pe serverele acestuia.
Actualizările descarcă doar fișierele programului. Baza de date, jurnalele și
copiile de rezervă rămân pe acest calculator, în folderul programului.</p>
<p style='margin:0;font-size:12.5px;line-height:1.55;color:var(--text3)'>
Программа работает локально. Персональные данные пациентов не передаются
разработчику и не хранятся на его серверах. Обновления загружают только файлы
программы. База данных, журналы и резервные копии остаются на этом компьютере.</p>
</div>"""
    if db.IS_SQLITE and os.environ.get("DENTART_ENV_FILE"):
        tok_set = bool(os.environ.get("TELEGRAM_TOKEN", "").strip())
        ph = ("••• token setat — introduceți altul pentru schimbare" if tok_set
              else "token de la @BotFather (ex. 123456789:AA...)")
        status_tbl += f"""
<h2>📱 Telegram — token bot</h2>
<form class='add' method='post' action='/admin/telegram/save'
      onsubmit="return confirm('Programul se va reporni pentru aplicare. Continuați?')">
  <input type='password' name='token' placeholder="{ph}" style='width:430px'>
  <button>💾 Salvează și repornește</button>
</form>
<p class='hint'>Creați botul clinicii la @BotFather (2 minute) și lipiți tokenul aici.
Câmp gol + salvare = dezactivează canalul Telegram.</p>"""
    if _pin_rec():
        status_tbl += """
<h2>🔒 Schimbă PIN</h2>
<form class='add' method='post' action='/admin/pin/change'>
  <input type='password' name='old_pin' placeholder='PIN actual' inputmode='numeric' maxlength='6' required style='width:140px'>
  <input type='password' name='new1' placeholder='PIN nou' inputmode='numeric' maxlength='6' required style='width:140px'>
  <input type='password' name='new2' placeholder='repetați' inputmode='numeric' maxlength='6' required style='width:140px'>
  <button>Schimbă</button>
</form>"""

    body = f"""
<div class='nav'><a href='/admin'>🏠 Panou</a></div>
{banner}
{status_tbl}
<form method='post' action='/admin/settings/save' onsubmit='return collectSettings()'>
<input type='hidden' name='payload' id='payload'>

<h2>🏥 Clinica</h2>
<table class='set'>
<tr><th style='width:180px'>Nume</th><td><input type='text' id='cname' value='{e(cfg["name"])}'></td></tr>
<tr><th>Telefon</th><td><input type='text' id='cphone' value='{e(cfg["phone"])}'></td></tr>
<tr><th>Adresa (RO)</th><td><input type='text' id='caddr_ro' value='{e(cfg.get("address", {}).get("ro", ""))}'></td></tr>
<tr><th>Adresa (RU)</th><td><input type='text' id='caddr_ru' value='{e(cfg.get("address", {}).get("ru", ""))}'></td></tr>
</table>

<h2>🕘 Program de lucru</h2>
<table class='set'>
<tr><th>Ziua</th><th>Închis</th><th>De la</th><th>Până la</th>
<th>Pauză de la</th><th>Pauză până la</th></tr>
{''.join(hours_rows)}
</table>
<p class='hint'>Pauza (ex. prânz 13:00–14:00) dispare din calendarul botului și din registru.
«—» = fără pauză.</p>

<h2>👨‍⚕️ Medici</h2>
<table class='set'>
<tr><th>Nume</th><th>Specializare</th><th style='width:90px'>Cabinet</th>
<th style='width:110px'>Telefon</th><th style='width:150px'>Program</th>
<th style='width:110px'>Stare</th></tr>
{doc_rows}
</table>
<p class='hint'>Medicii se editează în secțiunea
<a href='/admin/medici'><b>👨‍⚕️ Medici</b></a> — acolo sunt fișa completă, fotografia,
serviciile și starea (activ / în concediu / arhivat). Aici sunt afișați doar pentru
verificare, ca datele lor să aibă un singur loc de modificare.</p>

<h2>🦷 Servicii</h2>
<table class='set' id='svc_t'>
<tr><th>Denumire (RO)</th><th>Denumire (RU)</th><th style='width:120px'>Preț</th>
<th style='width:90px'>Durată</th><th style='width:100px'>Culoare</th>
<th style='width:40px'>🆘</th><th style='width:140px'>Medici (id)</th><th></th></tr>
<tbody id='svc_tb'>{svc_rows}</tbody>
</table>
<button type='button' class='addrow' onclick='addSvc()'>+ Adaugă serviciu</button>
<p class='hint'>Coloana «Medici»: id-uri separate prin spațiu ({doc_ids_hint}); gol = toți medicii.
🆘 = flux urgent (fără alegerea medicului, sloturi din ziua curentă).</p>

<button class='savebtn'>💾 Salvează setările</button>
</form>

<script>
const SVC_COLORS = {json.dumps(_PALETTE_RO)};
function addSvc() {{
  const tb = document.getElementById('svc_tb');
  const tr = document.createElement('tr');
  let opts = "<option value=''>auto</option>";
  for (const k in SVC_COLORS) opts += "<option value='" + k + "'>" + SVC_COLORS[k] + "</option>";
  let dopts = "";
  for (const x of [15, 30, 45, 60, 90, 120])
    dopts += "<option value='" + x + "'" + (x === 60 ? " selected" : "") + ">" + x + " min</option>";
  tr.innerHTML = "<td><input type='hidden' class='s_id' value=''>" +
    "<input type='text' class='s_ro' placeholder='Serviciu'></td>" +
    "<td><input type='text' class='s_ru' placeholder='Услуга'></td>" +
    "<td><input type='text' class='s_price' placeholder='500 MDL'></td>" +
    "<td><select class='s_dur'>" + dopts + "</select></td>" +
    "<td><select class='s_color'>" + opts + "</select></td>" +
    "<td style='text-align:center'><input type='checkbox' class='s_urg'></td>" +
    "<td><input type='text' class='s_docs' placeholder='gol = toți'></td>" +
    "<td><button type='button' class='rowdel' onclick='this.closest(\\"tr\\").remove()'>✖</button></td>";
  tb.appendChild(tr);
}}
function collectSettings() {{
  const days = ['mon','tue','wed','thu','fri','sat','sun'];
  const hours = {{}};
  for (const d of days) {{
    if (document.getElementById('hc_' + d).checked) {{ hours[d] = null; continue; }}
    const f = parseInt(document.getElementById('hf_' + d).value);
    const t = parseInt(document.getElementById('ht_' + d).value);
    const bf = document.getElementById('hb_' + d).value;
    const bt = document.getElementById('he_' + d).value;
    if (bf !== '' && bt !== '') hours[d] = [f, t, parseInt(bf), parseInt(bt)];
    else hours[d] = [f, t];
  }}
  const services = [];
  document.querySelectorAll('#svc_tb tr').forEach(tr => {{
    services.push({{ id: tr.querySelector('.s_id').value,
                    ro: tr.querySelector('.s_ro').value,
                    ru: tr.querySelector('.s_ru').value,
                    price: tr.querySelector('.s_price').value,
                    duration: tr.querySelector('.s_dur').value,
                    color: tr.querySelector('.s_color').value,
                    urgent: tr.querySelector('.s_urg').checked,
                    docs: tr.querySelector('.s_docs').value }});
  }});
  // валидация ДО отправки: при серверной ошибке форма перерисуется из
  // сохранённого конфига и все правки админа пропадут — не доводим до этого
  const seen = {{}};
  for (const s of services) {{
    const key = s.ro.trim().toLowerCase();
    if (!key) continue;
    if (seen[key]) {{
      alert('Două rânduri au aceeași denumire de serviciu: «' + s.ro.trim() +
            '». Redenumiți unul dintre ele.');
      return false;
    }}
    seen[key] = true;
  }}
  // медиков форма больше не отправляет — их каталог правится în «Medici»
  const payload = {{
    name: document.getElementById('cname').value,
    phone: document.getElementById('cphone').value,
    address: {{ ro: document.getElementById('caddr_ro').value,
               ru: document.getElementById('caddr_ru').value }},
    hours: hours, services: services
  }};
  document.getElementById('payload').value = JSON.stringify(payload);
  return true;
}}
</script>"""
    return _shell(body, "setările clinicii · se aplică imediat, fără restart", active="set")


def _build_config(data: dict) -> dict:
    name = str(data.get("name", "")).strip()[:80]
    phone = str(data.get("phone", "")).strip()[:30]
    if not name or not phone:
        raise ValueError("name/phone")
    addr_ro = str(data.get("address", {}).get("ro", "")).strip()[:120]
    addr_ru = str(data.get("address", {}).get("ru", "")).strip()[:120]

    hours = {}
    for day in _DOW_ORDER:
        h = data.get("hours", {}).get(day)
        if h is None:
            hours[day] = None
            continue
        vals = [int(x) for x in h]
        if len(vals) == 2:
            f, t = vals
            if not (0 <= f < t <= 24):
                raise ValueError("hours")
            hours[day] = [f, t]
        elif len(vals) == 4:
            f, t, bf, bt = vals
            if not (0 <= f < t <= 24 and f <= bf < bt <= t):
                raise ValueError("break")
            if bf <= f and bt >= t:
                raise ValueError("break=whole day")
            hours[day] = [f, t, bf, bt]
        else:
            raise ValueError("hours format")
    if all(v is None for v in hours.values()):
        raise ValueError("all closed")

    # ⭐ Счётчики id ПЕРСИСТЕНТНЫ (cfg["seq"]) и только растут. Раньше id искался
    # как первый свободный d{n} среди текущего списка: удалили d2, добавили врача —
    # он получал d2 и наследовал историю уволенного. Теперь id не переиспользуется.
    seq = dict(eng.CONFIG.get("seq") or {})
    seq_d = int(seq.get("doctor", 0))
    seq_s = int(seq.get("service", 0))
    for d in eng.CONFIG.get("doctors", []):
        mnum = re.fullmatch(r"d(\d+)", str(d.get("id", "")))
        if mnum:
            seq_d = max(seq_d, int(mnum.group(1)))
    for s in eng.CONFIG.get("services", []):
        mnum = re.fullmatch(r"s(\d+)", str(s.get("id", "")))
        if mnum:
            seq_s = max(seq_s, int(mnum.group(1)))

    # v1.9.0: врачей эта форма больше не присылает — их каталог правится только
    # в разделе «Medici», поэтому переносим список как есть (фото/e-mail/статус
    # не должны теряться из-за сохранения настроек клиники)
    doctors = [dict(d) for d in eng.CONFIG.get("doctors", [])]
    if not doctors:
        raise ValueError("doctors")
    doc_ids = {d["id"] for d in doctors}
    # то же для услуг: одинаковые подписи ломали бы бэкфилл service_id и отчёты
    labels_seen: set[str] = set()

    services = []
    sused: set[str] = set()
    for s in data.get("services", []):
        ro = str(s.get("ro", "")).strip()[:60]
        ru = str(s.get("ru", "")).strip()[:60] or ro
        if not ro:
            continue
        if ro.casefold() in labels_seen or (ru.casefold() != ro.casefold()
                                            and ru.casefold() in labels_seen):
            raise ValueError("duplicate service label")
        labels_seen.add(ro.casefold())
        labels_seen.add(ru.casefold())
        sid = str(s.get("id", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]{1,20}", sid) or sid in sused:
            seq_s += 1
            sid = f"s{seq_s}"
        sused.add(sid)
        entry: dict = {"id": sid, "ro": ro, "ru": ru}
        price = str(s.get("price", "")).strip()[:60]
        if price:
            entry["price"] = price
        dur_raw = str(s.get("duration", "") or "").strip()
        if dur_raw.isdecimal() and int(dur_raw) in (15, 30, 45, 60, 90, 120):
            if int(dur_raw) != 60:
                entry["duration"] = int(dur_raw)  # 60 = дефолт, не пишем
        color_s = str(s.get("color", "")).strip()
        if color_s in SVC_PALETTE:
            entry["color"] = color_s
        if s.get("urgent"):
            entry["urgent"] = True
        docs = [tok for tok in re.split(r"[,\s]+", str(s.get("docs", "")))
                if tok in doc_ids]
        if docs:
            entry["docs"] = docs
        services.append(entry)
    if not services:
        raise ValueError("services")

    cfg = dict(eng.CONFIG)
    cfg.pop("template", None)      # клинику заполнили — подсказка больше не нужна
    cfg.pop("_comment", None)
    cfg.update({"name": name, "phone": phone,
                "address": {"ro": addr_ro, "ru": addr_ru},
                "hours": hours, "doctors": doctors, "services": services,
                "seq": {"doctor": seq_d, "service": seq_s}})
    cfg["contacts"] = {
        "ro": (f"📍 {addr_ro}\n" if addr_ro else "")
              + f"☎️ {phone}\n🕘 {_hours_summary(hours, 'ro')}",
        "ru": (f"📍 {addr_ru}\n" if addr_ru else "")
              + f"☎️ {phone}\n🕘 {_hours_summary(hours, 'ru')}",
    }
    return cfg


@app.post("/admin/relink")
async def admin_relink(request: Request, old_name: str = Form(...),
                       dk: str = Form(...), back: str = Form("/admin")):
    """Переприкрепить сиротские записи (старое имя, без doctor_id) к врачу."""
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin", status_code=303)
    n = await db.relink_doctor(old_name.strip()[:80], dk)
    target = back if back.startswith("/admin") else "/admin"
    sep = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{sep}msg={'ok_set' if n >= 0 else 'bad'}",
                            status_code=303)


@app.post("/admin/update/check")
def admin_update_check(request: Request):
    """Проверить обновления прямо сейчас — не ждать следующего цикла.
    Синхронный def → threadpool, сетевой запрос не блокирует сервер."""
    if (deny := _guard(request)) is not None:
        return deny
    upd.check_now()
    return RedirectResponse("/admin/settings", status_code=303)


@app.post("/admin/update/run", response_class=HTMLResponse)
def admin_update_run(request: Request):
    """Одним кликом: скачать новый exe, подменить себя, перезапуститься.
    Синхронный def — FastAPI выполняет в threadpool (скачивание блокирует)."""
    if (deny := _guard(request)) is not None:
        return deny
    err = upd.self_update()
    if err:
        return RedirectResponse("/admin/settings?msg=upd_err", status_code=303)
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="18;url=/admin/settings">
<title>Actualizare…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:#0E9F8A;color:#fff;text-align:center}}
 .sp{{font-size:44px;animation:r 1.2s linear infinite;display:inline-block}}
 @keyframes r{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="sp">🔄</div>
<h1>Se actualizează la {html.escape(upd.STATE['latest'])}…</h1>
<p>Programul se închide și repornește singur.<br>
Această pagină se va reîncărca automat în ~18 secunde.</p>
</body></html>"""


@app.post("/admin/telegram/save", response_class=HTMLResponse)
async def admin_telegram_save(request: Request, token: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    env_file = os.environ.get("DENTART_ENV_FILE", "")
    if not (db.IS_SQLITE and env_file):
        return RedirectResponse("/admin/settings", status_code=303)
    tok = token.strip()
    if tok and not re.fullmatch(r"\d{6,12}:[\w-]{30,120}", tok):
        return RedirectResponse("/admin/settings?msg=bad_tok", status_code=303)
    p = pathlib.Path(env_file)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, done = [], False
    for ln in lines:
        # пустые не переносим: у уже раздутых файлов это лечит прошлые сохранения
        if not ln.strip():
            continue
        if ln.strip().startswith("TELEGRAM_TOKEN="):
            out.append(f"TELEGRAM_TOKEN={tok}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"TELEGRAM_TOKEN={tok}")
    # \n, а НЕ \r\n: write_text открывает файл с newline=None и сам переводит \n
    # в os.linesep. Явный \r\n давал \r\r\n — а splitlines() видит в этом два
    # перевода строки, поэтому файл РОС ВДВОЕ на каждом сохранении (замерено:
    # 2 строки -> 8 -> 16 -> 32). Прочие ключи при этом уцелевали, но файл,
    # который клиника правит руками, становился нечитаемым.
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ["TELEGRAM_TOKEN"] = tok
    if upd.restart_app() is not None:
        # dev-режим/тест-хук: перезапуск не случился — просто баннер
        return RedirectResponse("/admin/settings?msg=ok_tok", status_code=303)
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15;url=/admin/settings">
<title>Repornire…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:#0E9F8A;color:#fff;text-align:center}}
 .sp{{font-size:44px;animation:r 1.2s linear infinite;display:inline-block}}
 @keyframes r{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="sp">🔄</div>
<h1>Token salvat — programul repornește…</h1>
<p>Fereastra se va redeschide singură în câteva secunde.</p>
</body></html>"""


@app.post("/admin/settings/save")
async def admin_settings_save(request: Request, payload: str = Form(...)):
    if (deny := _guard(request)) is not None:
        return deny
    try:
        cfg = _build_config(json.loads(payload))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return RedirectResponse("/admin/settings?msg=bad_set", status_code=303)
    if eng.save_config(cfg) is not None:
        return RedirectResponse("/admin/settings?msg=bad_set", status_code=303)
    return RedirectResponse("/admin/settings?msg=ok_set", status_code=303)


# ---------- статистика ----------

def _fmt_mdl(x: int) -> str:
    return f"{x:,}".replace(",", " ") + " MDL"


@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(
    request: Request,
    from_q: str = Query("", alias="from"),
    to_q: str = Query("", alias="to"),
):
    if (deny := _guard(request)) is not None:
        return deny
    today = datetime.now(eng.TZ).date()
    d1 = _parse_date(from_q) if from_q else today - timedelta(days=6)
    d2 = _parse_date(to_q) if to_q else today
    if d2 < d1:
        d1, d2 = d2, d1
    start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    end = datetime(d2.year, d2.month, d2.day, tzinfo=eng.TZ) + timedelta(days=1)
    rows = await db.day_appointments(start, end)
    appts = [r for r in rows if r["source"] != "note"]
    act = [r for r in appts if r["status"] != "cancelled"]

    n_bot = sum(1 for r in act if r["source"] == "bot")
    n_man = len(act) - n_bot
    # «пришли» = завершённые + сидящие в кресле прямо сейчас
    n_done = sum(1 for r in act if r["status"] in ("done", "arrived"))
    n_noshow = sum(1 for r in act if r["status"] == "noshow")
    n_cancel = len(appts) - len(act)
    n_rem = sum(1 for r in appts if r["reminded_day"])
    def _price(r) -> int:
        """Цена: по стабильному service_id (не зависит от языка/переименований),
        для легаси-строк — по подписи."""
        sid = r.get("service_id")
        if sid and sid in eng.SERVICE_PRICE_BY_ID:
            return eng.SERVICE_PRICE_BY_ID[sid]
        return eng.SERVICE_PRICE.get(r["service"], 0)

    loss = sum(_price(r) for r in act if r["status"] == "noshow")
    bot_value = sum(_price(r) for r in act if r["source"] == "bot")

    def _tile(val, label: str, cls: str = "", ico: str = "") -> str:
        """Плитка периода. Структура ТА ЖЕ, что на дашборде: иначе flex кладёт
        подпись сбоку от числа, а не под ним (долг разметки с v1.5.0)."""
        icon = (f"<span class='ico' style='background:var(--teal-soft)'>{ico}</span>"
                if ico else "")
        return (f"<div class='tile {cls}'>{icon}"
                f"<div><b>{val}</b><span>{label}</span></div></div>")

    tiles = (
        "<div class='tiles'>"
        + _tile(len(act), "programări", ico="📅")
        + _tile(n_bot, "🤖 prin bot")
        + _tile(n_man, "✍️ recepție")
        + _tile(n_done, "🟦 au venit")
        + _tile(n_noshow, f"neprezentări<br>≈ {_fmt_mdl(loss)}", cls="bad")
        + _tile(n_cancel, "anulate")
        + _tile(n_rem, "🔔 remindere")
        + _tile(f"≈ {_fmt_mdl(bot_value)}", "valoare adusă de bot")
        + "</div>"
    )

    # загрузка врачей: занятые МИНУТЫ / рабочие минуты врача за период (v1.8.0 —
    # при разных длительностях считать «в штуках слотов» стало бессмысленно)
    days = [d1 + timedelta(days=i) for i in range((d2 - d1).days + 1)]
    doc_rows = []
    for dk, name in eng.DOCTORS.items():
        # по стабильному id (v1.7.1): переименование врача не обнуляет историю
        mine = [r for r in act if r.get("doctor_id") == dk
                or (not r.get("doctor_id") and r["doctor"] == name)]
        off = not eng.DOCTOR_META.get(dk, {}).get("active", True)
        if off and not mine:
            continue  # выключенный врач без записей за период — не мусорим нулями
        ns = sum(1 for r in mine if r["status"] == "noshow")
        cap_min = sum(eng.work_minutes(dk, day) for day in days)
        busy_min = sum(int(r.get("duration_min") or 60) for r in mine)
        pct = round(100 * busy_min / cap_min) if cap_min else 0
        doc_rows.append(
            f"<tr><td>{html.escape(name)}"
            f"{' <small style=\"color:var(--text3)\">· inactiv</small>' if off else ''}</td>"
            f"<td>{len(mine)}</td><td>{ns}</td>"
            f"<td style='min-width:160px'>{pct}%<div class='statbar'><div style='width:{min(pct,100)}%'></div></div></td></tr>"
        )
    doctors_tbl = ("<h2>Medici</h2><table class='list'>"
                   "<tr><th>Medic</th><th>Programări</th><th>Neprezentări</th><th>Ocupare</th></tr>"
                   + "".join(doc_rows) + "</table>")

    # группировка по service_id: RU- и RO-запись одной услуги = одна строка
    # отчёта (раньше язык пациента раздваивал услугу и делил её выручку)
    svc_count: dict[str, dict] = {}
    for r in act:
        sid = r.get("service_id")
        if sid and sid in eng.SERVICES:
            key, label = sid, eng.SERVICES[sid]["ro"]
        else:
            key, label = "lbl:" + r["service"], r["service"]
        ent = svc_count.setdefault(key, {"label": label, "cnt": 0, "val": 0})
        ent["cnt"] += 1
        ent["val"] += _price(r)
    svc_rows = "".join(
        f"<tr><td>{html.escape(ent['label'])}</td><td>{ent['cnt']}</td>"
        f"<td>≈ {_fmt_mdl(ent['val'])}</td></tr>"
        for ent in sorted(svc_count.values(), key=lambda x: -x["cnt"])[:8]
    )
    services_tbl = ("<h2>Servicii</h2><table class='list'>"
                    "<tr><th>Serviciu</th><th>Programări</th><th>≈ Valoare</th></tr>"
                    + svc_rows + "</table>")

    q7 = (today - timedelta(days=6)).isoformat()
    q30 = (today - timedelta(days=29)).isoformat()
    m1 = today.replace(day=1).isoformat()
    nav = (
        "<div class='nav'>"
        f"<b>{d1.strftime('%d.%m.%Y')} — {d2.strftime('%d.%m.%Y')}</b>"
        f"<a href='/admin/stats?from={today.isoformat()}&to={today.isoformat()}'>Azi</a>"
        f"<a href='/admin/stats?from={q7}&to={today.isoformat()}'>7 zile</a>"
        f"<a href='/admin/stats?from={m1}&to={today.isoformat()}'>Luna asta</a>"
        f"<a href='/admin/stats?from={q30}&to={today.isoformat()}'>30 zile</a>"
        f"<form class='dpickf' method='get' action='/admin/stats' style='display:inline-flex;gap:4px'>"
        f"<input class='dpick' type='date' name='from' value='{d1.isoformat()}'>"
        f"<input class='dpick' type='date' name='to' value='{d2.isoformat()}'>"
        f"<button class='searchf' style='background:var(--teal);color:#fff;border:none;"
        f"border-radius:var(--r-ctl);height:var(--h-ctl);padding:0 18px;cursor:pointer;"
        f"font-size:14px;font-weight:600'>OK</button></form>"
        f"<a href='/admin/export?from={d1.isoformat()}&to={d2.isoformat()}'>📥 Export CSV</a>"
        f"<a href='/admin'>🏠 Panou</a></div>"
    )
    hint = ("<p class='hint'>Prețurile sunt medii orientative din lista clinicii; "
            "neprezentările = venit pierdut estimat. Notițele nu se numără.</p>")
    return _shell(nav + tiles + doctors_tbl + services_tbl + hint,
                  "statistici · perioadă selectabilă", active="stat")


# ---------- экспорт CSV ----------

@app.get("/admin/export")
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


# ---------- поиск пациента ----------

@app.get("/admin/search", response_class=HTMLResponse)
async def admin_search(request: Request, q: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    q = q.strip()[:60]
    now = datetime.now(eng.TZ)
    blocks = []
    if not q:
        # стартовый вид «Pacienți»: последние пациенты, без поискового запроса
        rec = await db.recent_patients(20)
        if rec:
            rrows = []
            for p in rec:
                chan = ("📱 Telegram" if (p["session_key"] or "").startswith("tg:")
                        else "✍️ recepție" if (p["session_key"] or "").startswith("manual:")
                        else "🌐 web")
                pa = _age(p["birth_year"])
                rrows.append(
                    f"<tr><td><a class='plink' href='/admin/patient/{p['id']}'>"
                    f"{html.escape(p['name'] or '—')}</a></td>"
                    f"<td>{html.escape(p['phone'] or '—')}</td>"
                    f"<td>{pa or '—'}</td><td>{chan}</td>"
                    f"<td>{p['created_at'].astimezone(eng.TZ).strftime('%d.%m.%Y')}</td></tr>")
            blocks.append(
                "<h2>Pacienți recenți</h2><table class='list'>"
                "<tr><th>Nume</th><th>Telefon</th><th>Vârstă</th><th>Canal</th>"
                "<th>Înregistrat</th></tr>" + "".join(rrows) + "</table>")
    if q:
        patients = await db.search_patients(q)
        if not patients:
            blocks.append("<div class='banner err'>Nimic găsit. Încercați alt nume sau telefon.</div>")
        for p in patients:
            visits = await db.patient_appointments(p["id"])
            chan = ("📱 Telegram" if (p["session_key"] or "").startswith("tg:")
                    else "✍️ recepție" if (p["session_key"] or "").startswith("manual:")
                    else "🌐 web")
            upcoming = sum(1 for v in visits
                           if v["status"] in LIVE_STATUSES and v["starts_at"] > now)
            rows = []
            for v in visits:
                dt = v["starts_at"].astimezone(eng.TZ)
                future = v["starts_at"] > now
                day_link = f"/admin/all?date={dt.date().isoformat()}"
                cmt = (f"<br><small style='color:#7a6a00'>💬 {html.escape(v['comment'][:60])}</small>"
                       if v["comment"] else "")
                rows.append(
                    f"<tr class='{'' if future else 'vpast'}'>"
                    f"<td>{dt.strftime('%d.%m.%Y %H:%M')}</td>"
                    f"<td>{html.escape(v['service'])}{cmt}</td>"
                    f"<td>{html.escape(v['doctor'])}</td>"
                    f"<td>{STATUS_LABEL.get(v['status'], v['status'])}</td>"
                    f"<td><a href='{day_link}'>→ ziua</a></td></tr>"
                )
            pa = _age(p["birth_year"])
            age_meta = f" · {pa} ani ({p['birth_year']})" if pa else ""
            blocks.append(
                f"<div class='pcard'><h3><a class='plink' href='/admin/patient/{p['id']}'>"
                f"{html.escape(p['name'] or '—')}</a> "
                f"<a href='/admin/patient/{p['id']}' style='font-size:12px;font-weight:400'>📇 fișa →</a></h3>"
                f"<div class='meta'>📞 {html.escape(p['phone'] or '—')}{age_meta} · {chan}"
                f" · {len(visits)} vizite, {upcoming} viitoare</div>"
                f"<table class='list'><tr><th>Când</th><th>Serviciu</th><th>Medic</th>"
                f"<th>Status</th><th></th></tr>{''.join(rows)}</table></div>"
            )
    body = (
        "<div class='nav'><a href='/admin'>🏠 Panou</a><a href='/admin/all'>📋 Toți medicii</a>"
        f"<form class='searchf' method='get' action='/admin/search' style='margin-left:0'>"
        f"<input name='q' value='{html.escape(q)}' placeholder='Nume sau telefon…' autofocus>"
        f"<button>🔍 Caută</button></form></div>"
        + "".join(blocks)
        + ("" if q else "<p class='hint'>Căutați după nume (min. 2 litere) sau telefon (min. 3 cifre, orice format).</p>")
    )
    return _shell(body, "pacienți · căutare și istoric vizite", active="pat")


















































# ---------- общая сетка: все врачи ----------

# фильтры для клика по плиткам дашборда: цифра → сразу список этих записей
_TILE_FILTERS = {
    "bot": ("🤖 prin bot",
            lambda r: r["source"] == "bot" and r["status"] != "cancelled"),
    "rec": ("✍️ recepție",
            lambda r: r["source"] == "manual" and r["status"] != "cancelled"),
    "urg": ("🆘 urgențe",
            lambda r: r["service"] in eng.URGENT_LABELS
            and r["source"] != "note" and r["status"] != "cancelled"),
    "noshow": ("neprezentări", lambda r: r["status"] == "noshow"),
}


@app.get("/admin/all", response_class=HTMLResponse)
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
            f"· <a href='/admin/all?date={d.isoformat()}'>arată tot ✕</a></div>")
        filtered_list = _list(hits, back, title=f"{label} — {d.strftime('%d.%m.%Y')}")
    body = (_date_nav(d, "/admin/all",
                      f"<a href='/admin?date={d.isoformat()}'>🏠 Panou</a>"
                      f"<a href='/admin/export?from={d.isoformat()}&to={d.isoformat()}'>📥 CSV</a>")
            + _banner(msg, d)
            + filter_chip + filtered_list
            + _grid(d, items, active, href, cards)
            + _form(d, list(eng.ACTIVE_DOCTORS.items()) or items, doctor, time_pre, back)
            + ("" if flt else _list(rows, back))
            + _slot_modal(d, back)
            + _card_modal(cards, back))
    return _shell(body, "toți medicii · 🤖 bot / ✍️ recepție / 📝 notițe", active="prog")


# ---------- страница одного врача ----------

@app.get("/admin/doctor/{dk}", response_class=HTMLResponse)
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
    head = (f"<div class='nav'><b>{html.escape(name)}</b>{off_badge} "
            f"<span style='color:#667'>{html.escape(eng.DOCTOR_SPEC.get(dk, ''))}</span> "
            f"<a href='/admin/doctor-card/{dk}'>👤 Fișa medicului</a>"
            f"<a href='/admin?date={d.isoformat()}'>🏠 Panou</a>"
            f"<a href='/admin/all?date={d.isoformat()}'>📋 Toți medicii</a></div>")
    cards = _collect_cards(rows)
    body = (head + _date_nav(d, base) + _banner(msg, d)
            + _grid(d, items, active, href, cards)
            + (_form(d, items, dk, time_pre, back) if is_active else "")
            + _list(rows, back)
            + _slot_modal(d, back)
            + _card_modal(cards, back))
    return _shell(body, "ziua unui medic · 🤖 bot / ✍️ recepție / 📝 notițe", active="prog")


# ---------- раздел «Medici»: карточка врача (v1.9.0) ----------
#
# Каталог врачей живёт в clinic.json (Setări + hot-reload), в БД — только
# doctor_id и снапшот имени (решение PLAN_DB_V17). Этот раздел = единственное
# место правки врачей: таблица из Setări убрана, чтобы не было двух источников.

MAX_PHOTO_MB = 5
_DOC_STATE_RO = {"activ": "Activ", "concediu": "În concediu", "arhivat": "Arhivat"}
_DOC_STATE_HINT = {
    "activ": "botul și formularele îl propun",
    "concediu": "temporar nu primește; programările existente rămân",
    "arhivat": "a plecat din clinică; istoricul rămâne",
}
_PHOTO_MIME = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _doctors_dir() -> pathlib.Path:
    base = _data_dir() or pathlib.Path("data")
    d = base / "files" / "doctors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sniff_photo(head: bytes) -> tuple[str, str] | None:
    """(расширение, mime) по СОДЕРЖИМОМУ файла — имени и content-type не верим."""
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


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


def _doc_hours_text(dk: str) -> str:
    meta = eng.DOCTOR_META.get(dk, {})
    wf, wt = meta.get("work_from"), meta.get("work_to")
    if wf is None and wt is None:
        return "ca clinica"
    a = f"{int(wf):02d}:00" if wf is not None else "deschidere"
    b = f"{int(wt):02d}:00" if wt is not None else "închidere"
    return f"{a}–{b}"


def _doc_rows(dk: str, name: str, rows: list) -> list:
    """Записи врача среди строк периода: по стабильному id, легаси — по имени."""
    return [r for r in rows
            if r.get("doctor_id") == dk or (not r.get("doctor_id") and r["doctor"] == name)]


def _doc_stats(dk: str, name: str, rows: list, days: list) -> dict:
    live = [r for r in _doc_rows(dk, name, rows)
            if r["source"] != "note" and r["status"] != "cancelled"]
    cap = sum(eng.work_minutes(dk, day) for day in days)
    busy = sum(int(r.get("duration_min") or 60) for r in live)
    return {"n": len(live), "pct": round(100 * busy / cap) if cap else 0,
            "noshow": sum(1 for r in live if r["status"] == "noshow")}


def _med_redirect(dk: str, msg: str = "") -> RedirectResponse:
    q = f"?msg={msg}" if msg else ""
    return RedirectResponse(f"/admin/doctor-card/{dk}{q}", status_code=303)


def _save_cfg(**changes) -> str | None:
    cfg = dict(eng.CONFIG)
    cfg.update(changes)
    return eng.save_config(cfg)


def _doctor_entry(prev: dict, **fields) -> dict:
    """Запись врача для конфига: правим поля, ничего чужого не теряем."""
    entry = dict(prev)
    entry.update(fields)
    for k in ("spec", "room", "phone", "email", "color", "photo"):
        if not entry.get(k):
            entry.pop(k, None)
    for k in ("work_from", "work_to"):
        if entry.get(k) is None:
            entry.pop(k, None)
    entry["status"] = eng.doctor_state(entry)
    # active остаётся в файле ради совместимости: старая версия программы
    # (откат) читает только его и поймёт «в отпуске / в архиве» как выключенного
    entry["active"] = entry["status"] == "activ"
    return entry


def _patch_doctor(dk: str, **fields) -> str | None:
    docs = [(_doctor_entry(d, **fields) if d["id"] == dk else d)
            for d in eng.CONFIG["doctors"]]
    return _save_cfg(doctors=docs)


def _med_card_html(dk: str, name: str, rows: list, days: list) -> str:
    e = html.escape
    meta = eng.DOCTOR_META.get(dk, {})
    st = meta.get("status", "activ")
    s = _doc_stats(dk, name, rows, days)
    bits = [f"🚪 {e(meta['room'])}" if meta.get("room") else "",
            f"☎️ {e(meta['phone'])}" if meta.get("phone") else "",
            f"🕘 {e(_doc_hours_text(dk))}"]
    return f"""<a class="medcard{'' if st == 'activ' else ' off'}" href="/admin/doctor-card/{dk}">
  <div class="medhead">{_avatar(dk, name)}
    <div style="min-width:0"><b>{e(name)}</b>
      <small>{e(eng.DOCTOR_SPEC.get(dk, '') or '—')}</small></div>
    <span class="dbadge {st}" style="margin-left:auto">{_DOC_STATE_RO[st]}</span>
  </div>
  <div class="medmeta">{''.join(f'<span>{b}</span>' for b in bits if b)}</div>
  <div class="medstats">
    <div><b>{s['n']}</b><span>programări · 30 zile</span></div>
    <div><b>{s['pct']}%</b><span>ocupare</span></div>
    <div><b>{s['noshow']}</b><span>neprezentări</span></div>
  </div>
</a>"""


@app.get("/admin/medici", response_class=HTMLResponse)
async def admin_medici(request: Request, msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    today = datetime.now(eng.TZ).date()
    d1 = today - timedelta(days=29)
    start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    end = datetime(today.year, today.month, today.day, tzinfo=eng.TZ) + timedelta(days=1)
    rows = await db.day_appointments(start, end)
    days = [d1 + timedelta(days=i) for i in range(30)]

    live, arch = [], []
    for dk, name in eng.DOCTORS.items():
        card = _med_card_html(dk, name, rows, days)
        (arch if eng.DOCTOR_META.get(dk, {}).get("status") == "arhivat" else live).append(card)

    banner = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        banner = f"<div class='banner {cls}'>{text}</div>"

    # ⚠️ старая таблица в Setări подставляла КАЖДОМУ врачу один и тот же цвет по
    # умолчанию — на таком конфиге карточки в расписании неразличимы. Молча
    # переписывать чужой выбор нельзя, поэтому просто предлагаем сброс.
    set_colors = {(d.get("color") or "").lower() for d in eng.CONFIG["doctors"]}
    same_color = len(eng.CONFIG["doctors"]) > 1 and len(set_colors) == 1 and "" not in set_colors
    color_hint = (
        "<div class='banner err'>Toți medicii au aceeași culoare, deci cardurile lor "
        "din programul zilei nu se disting. "
        "<form method='post' action='/admin/medici/colors' style='display:inline'>"
        "<button style='background:var(--teal);color:#fff;border:none;border-radius:8px;"
        "padding:5px 12px;cursor:pointer;font-size:12.5px;margin-left:8px'>"
        "🎨 Culori automate</button></form></div>") if same_color else ""
    arch_block = (f"<h2>🗄 Arhivă <small style='font-weight:400;color:var(--text3)'>"
                  f"· medici care nu mai lucrează; istoricul lor rămâne</small></h2>"
                  f"<div class='medgrid'>{''.join(arch)}</div>") if arch else ""
    body = f"""
<div class='nav'><a href='/admin'>🏠 Panou</a><a href='/admin/settings'>⚙️ Setările clinicii</a></div>
{banner}{color_hint}
<div class='medgrid'>{''.join(live)}</div>
<h2>➕ Medic nou</h2>
<form class='add' method='post' action='/admin/medici/add'>
  <input type='text' name='name' placeholder='Dr. Nume Prenume' required style='width:260px'>
  <input type='text' name='spec' placeholder='Specializare (ex. Terapie)' style='width:220px'>
  <button>+ Adaugă medic</button>
</form>
<p class='hint'>Medicul nu se șterge niciodată: programările lui păstrează legătura cu el.
«În concediu» = pauză temporară, «Arhivat» = a plecat (posibil doar fără programări viitoare).</p>
{arch_block}"""
    return _shell(body, "medicii clinicii · fișă, program, servicii", active="med")


@app.post("/admin/medici/add")
async def admin_medici_add(request: Request, name: str = Form(...), spec: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    nm = name.strip()[:60]
    if not nm:
        return RedirectResponse("/admin/medici?msg=bad_med", status_code=303)
    # тёзки слили бы истории (легаси-строки матчатся по имени) — запрещаем
    if any(d["name"].casefold() == nm.casefold() for d in eng.CONFIG["doctors"]):
        return RedirectResponse("/admin/medici?msg=dup_med", status_code=303)
    seq = dict(eng.CONFIG.get("seq") or {})
    n = int(seq.get("doctor", 0))
    for d in eng.CONFIG.get("doctors", []):
        mnum = re.fullmatch(r"d(\d+)", str(d.get("id", "")))
        if mnum:
            n = max(n, int(mnum.group(1)))
    n += 1                      # id не переиспользуются (урок 08-01)
    seq["doctor"] = n
    did = f"d{n}"
    entry = _doctor_entry({"id": did, "name": nm}, spec=spec.strip()[:60], status="activ")
    err = _save_cfg(doctors=list(eng.CONFIG["doctors"]) + [entry], seq=seq)
    if err:
        return RedirectResponse("/admin/medici?msg=save_err", status_code=303)
    return _med_redirect(did, "new_med")


@app.post("/admin/medici/colors")
async def admin_medici_colors(request: Request):
    """Сброс цветов врачей на автоматические (различимые по палитре)."""
    if (deny := _guard(request)) is not None:
        return deny
    docs = [_doctor_entry(d, color="") for d in eng.CONFIG["doctors"]]
    err = _save_cfg(doctors=docs)
    return RedirectResponse(f"/admin/medici?msg={'save_err' if err else 'ok_med'}",
                            status_code=303)


@app.get("/admin/doctor-card/{dk}", response_class=HTMLResponse)
async def admin_doctor_card(request: Request, dk: str, msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    e = html.escape
    name = eng.DOCTORS[dk]
    meta = eng.DOCTOR_META.get(dk, {})
    st = meta.get("status", "activ")
    today = datetime.now(eng.TZ).date()

    # один запрос на всё: сегодняшний список + ближайшие 7 дней
    wk_start = datetime(today.year, today.month, today.day, tzinfo=eng.TZ)
    wk_rows = await db.day_appointments(wk_start, wk_start + timedelta(days=7))
    mine_wk = _doc_rows(dk, name, wk_rows)
    today_rows = [r for r in mine_wk if r["starts_at"].astimezone(eng.TZ).date() == today]

    d1 = today - timedelta(days=29)
    m_start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    stat_rows = await db.day_appointments(m_start, wk_start + timedelta(days=1))
    stats = _doc_stats(dk, name, stat_rows, [d1 + timedelta(days=i) for i in range(30)])
    future = await db.doctor_future_count(dk, name, datetime.now(eng.TZ))

    banner = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        banner = f"<div class='banner {cls}'>{text}</div>"

    # услуги, которые останутся (или уже остались) без единого активного врача:
    # бот тогда честно скажет «недоступна» (v1.8.1), но админ должен это ВИДЕТЬ.
    # ⚠️ v1.9.1: раньше предупреждение показывалось только пока врач активен —
    # то есть исчезало ровно в тот момент, когда становилось правдой.
    def _orphans(*, without: bool) -> list[str]:
        out = []
        for sv in eng.SERVICES.values():
            docs = sv.get("docs") or []
            if not docs or (without and dk not in docs):
                continue
            others = [k for k in docs
                      if (k != dk if without else True)
                      and eng.DOCTOR_META.get(k, {}).get("active")]
            if not others:
                out.append(sv["ro"])
        return out

    warn = ""
    if st == "activ":
        if (soon := _orphans(without=True)):
            warn = (f"<div class='banner err'>Atenție: dacă acest medic nu mai e activ, "
                    f"serviciile <b>{e(', '.join(soon))}</b> rămân fără medic și "
                    f"botul le va marca indisponibile.</div>")
    elif (now_orphan := _orphans(without=False)):
        warn = (f"<div class='banner err'>Cât timp acest medic nu e activ, serviciile "
                f"<b>{e(', '.join(now_orphan))}</b> nu au niciun medic activ — botul "
                f"nu le mai propune. Bifați-le la alt medic sau readuceți-l în "
                f"activitate.</div>")

    def _wh_opts(sel, lo: int = HOUR_MIN, hi: int = HOUR_MAX) -> str:
        out = [f"<option value=''{' selected' if sel is None else ''}>—</option>"]
        for x in range(lo, hi + 1):
            out.append(f"<option value='{x}'{' selected' if sel == x else ''}>{x}:00</option>")
        return "".join(out)

    st_opts = "".join(
        f"<option value='{k}'{' selected' if st == k else ''}>{v} — {_DOC_STATE_HINT[k]}</option>"
        for k, v in _DOC_STATE_RO.items())
    photo_form = f"""
<form class='fform' method='post' action='/admin/doctor-card/{dk}/photo'
      enctype='multipart/form-data' style='margin-top:10px'>
  <div class='filepick'>
    <input type='file' name='file' id='docphoto' accept='image/jpeg,image/png,image/webp'
           required onchange='pickName(this)'>
    <label for='docphoto'>📎 Alege fotografia</label>
    <span class='fname' id='docphoto_n'>niciun fișier ales</span>
  </div>
  <button>📷 Încarcă fotografia</button>
</form>
<p class='hint' style='margin:6px 0 0'>JPEG / PNG / WebP, max {MAX_PHOTO_MB} MB.
Rămâne local, în folderul programului; pacienții nu o văd.</p>"""
    if meta.get("photo"):
        photo_form += (f"<form method='post' action='/admin/doctor-card/{dk}/photo/del' "
                       f"style='margin-top:6px' onsubmit=\"return confirm('Ștergeți fotografia?')\">"
                       f"<button class='rowdel' style='background:none;border:1px solid var(--line);"
                       f"border-radius:8px;padding:4px 10px;cursor:pointer;font-size:12px;"
                       f"color:var(--text2)'>🗑 Șterge fotografia</button></form>")

    left = f"""<div class='fcard'>
  <div class='fhead'>{_avatar(dk, name, big=True)}
    <div style='min-width:0'><b>{e(name)}</b>
      <small>{e(eng.DOCTOR_SPEC.get(dk, '') or '—')}</small>
      <span class='dbadge {st}' style='display:inline-block;margin-top:6px'>{_DOC_STATE_RO[st]}</span>
    </div>
  </div>
  {photo_form}
</div>
<div class='fcard'><h3>Date de contact și program</h3>
<form class='fform' method='post' action='/admin/doctor-card/{dk}/save'>
  <input name='name' value="{e(name)}" placeholder='Nume' maxlength='60' required>
  <input name='spec' value="{e(eng.DOCTOR_SPEC.get(dk, ''))}" placeholder='Specializare' maxlength='60'>
  <div class='r2'><input name='room' value="{e(meta.get('room', ''))}" placeholder='Cabinet'>
  <input name='phone' value="{e(meta.get('phone', ''))}" placeholder='Telefon intern'></div>
  <input name='email' value="{e(meta.get('email', ''))}" placeholder='E-mail (opțional)' maxlength='80'>
  <div style='font-size:11.5px;color:var(--text3);margin-top:2px'>Program personal (de la / până la)</div>
  <div class='r2'><select name='work_from'>{_wh_opts(meta.get('work_from'))}</select>
  <select name='work_to'>{_wh_opts(meta.get('work_to'), HOUR_MIN + 1, HOUR_MAX)}</select></div>
  <div style='font-size:11.5px;color:var(--text3);margin-top:2px'>Culoare în calendar</div>
  <div class='r2' style='align-items:center'>
    <input type='color' name='color' value="{e(meta.get('color') or _doc_hue(dk))}"
           style='width:56px;padding:3px;height:var(--h-ctl);flex:0 0 56px'>
    <label style='font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px'>
      <input type='checkbox' name='auto_color' value='1'
             {'checked' if not meta.get('color') else ''} style='width:auto'> automată</label>
  </div>
  <div style='font-size:11.5px;color:var(--text3);margin-top:2px'>Starea medicului</div>
  <select name='status'>{st_opts}</select>
  <button>💾 Salvează</button>
</form>
<p class='hint' style='margin:8px 0 0'>Programul «—» = ca al clinicii. Culoarea se
folosește în calendarul zilei. Arhivarea e posibilă doar fără programări viitoare
(acum: <b>{future}</b>).</p>
</div>"""

    # центр: сегодня + ближайшая неделя (заметки не в счёт — это не приёмы)
    wk_cells = []
    for i in range(7):
        day = today + timedelta(days=i)
        cnt = sum(1 for r in mine_wk
                  if r["starts_at"].astimezone(eng.TZ).date() == day
                  and r["source"] != "note" and r["status"] != "cancelled")
        cap = eng.work_minutes(dk, day)
        lbl = ("Azi" if i == 0 else _DOW_FULL[_DOW_ORDER[day.weekday()]][:2])
        tone = ("var(--teal-soft)" if cnt else "var(--bg)") if cap else "var(--line2)"
        wk_cells.append(
            f"<a href='/admin/doctor/{dk}?date={day.isoformat()}' style='flex:1;min-width:0;"
            f"text-decoration:none;color:inherit;background:{tone};border-radius:10px;"
            f"padding:8px 6px;text-align:center'>"
            f"<div style='font-size:11px;color:var(--text3)'>{lbl} {day.day:02d}.{day.month:02d}</div>"
            f"<div style='font-size:16px;font-weight:600'>{cnt if cap else '—'}</div></a>")
    back = f"/admin/doctor-card/{dk}"
    cards = _collect_cards(today_rows)
    # 9 колонок в узкой средней колонке — таблица скроллится сама, страница нет
    day_list = _list(today_rows, back,
                     title=f"Astăzi, {today.strftime('%d.%m.%Y')}").replace(
        "<table class='list'>", "<div style='overflow-x:auto'><table class='list'>", 1).replace(
        "</table>", "</table></div>", 1).replace(
        "</h2>", f" <small style='font-size:12px;font-weight:400'>"
                 f"<a href='/admin/doctor/{dk}?date={today.isoformat()}'>grila zilei ↗</a>"
                 f"</small></h2>", 1)
    center = f"""<div class='fcard'><h3>Următoarele 7 zile <small>· click = ziua completă</small></h3>
<div style='display:flex;gap:6px'>{''.join(wk_cells)}</div></div>
<div class='fcard' style='padding-top:4px'>{day_list}</div>"""

    # справа: услуги галочками + цифры за 30 дней
    svc_lines = []
    for sid, sv in eng.SERVICES.items():
        docs = sv.get("docs") or []
        checked = (not docs) or dk in docs
        note = ("toți medicii" if not docs
                else "1 medic" if len(docs) == 1 else f"{len(docs)} medici")
        svc_lines.append(
            f"<label><input type='checkbox' name='svc' value='{e(sid)}'"
            f"{' checked' if checked else ''}> {e(sv['ro'])}<small>{note}</small></label>")
    right = f"""<div class='fcard'><h3>Servicii pe care le face</h3>
<form method='post' action='/admin/doctor-card/{dk}/services'>
  <div class='svcpick'>{''.join(svc_lines)}</div>
  <button class='savebtn' style='margin-top:10px'>💾 Salvează serviciile</button>
</form>
<p class='hint' style='margin:8px 0 0'>Serviciul fără bife explicite se oferă la
<b>toți</b> medicii activi. Dacă scoateți bifa de la un astfel de serviciu, lista lui
devine explicită — un medic nou va trebui bifat manual.</p>
</div>
<div class='fcard'><h3>Ultimele 30 de zile</h3>
{"".join(f"<div class='frow'><span>{lbl}</span><span class='v'>{val}</span></div>" for lbl, val in
         [("Programări", stats['n']), ("Ocupare", f"{stats['pct']}%"),
          ("Neprezentări", stats['noshow']), ("Programări viitoare", future)])}
<p class='hint' style='margin:8px 0 0'><a href='/admin/stats'>Statistica întregii clinici ↗</a></p>
</div>"""

    body = (f"<div class='nav'><a href='/admin/medici'>👨‍⚕️ Toți medicii</a>"
            f"<a href='/admin/doctor/{dk}'>📅 Ziua medicului</a>"
            f"<a href='/admin'>🏠 Panou</a></div>{banner}{warn}"
            f"<div class='fisa med'><div class='fcol-l'>{left}</div>"
            f"<div class='fcol-c'>{center}</div><div class='fcol-r'>{right}</div></div>"
            + _card_modal(cards, back))
    return _shell(body, f"fișa medicului · {html.escape(name)}", active="med")


@app.post("/admin/doctor-card/{dk}/save")
async def doctor_card_save(request: Request, dk: str, name: str = Form(...),
                           spec: str = Form(""), room: str = Form(""),
                           phone: str = Form(""), email: str = Form(""),
                           color: str = Form(""), auto_color: str = Form(""),
                           work_from: str = Form(""), work_to: str = Form(""),
                           status: str = Form("activ")):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    nm = name.strip()[:60]
    if not nm:
        return _med_redirect(dk, "bad_med")
    if any(d["id"] != dk and d["name"].casefold() == nm.casefold()
           for d in eng.CONFIG["doctors"]):
        return _med_redirect(dk, "dup_med")
    st = status if status in eng.DOCTOR_STATES else "activ"
    if st != "activ" and not any(d["id"] != dk and eng.doctor_state(d) == "activ"
                                 for d in eng.CONFIG["doctors"]):
        return _med_redirect(dk, "last_med")
    if st == "arhivat":
        # архив = «его больше нет в расписании»; с живыми будущими бронями это
        # тихо оставило бы пациентов без врача — только «в отпуске»
        if await db.doctor_future_count(dk, eng.DOCTORS[dk], datetime.now(eng.TZ)):
            return _med_redirect(dk, "arch_busy")
    wf = int(work_from) if work_from.isdecimal() and 0 <= int(work_from) <= 23 else None
    wt = int(work_to) if work_to.isdecimal() and 1 <= int(work_to) <= 24 else None
    if wf is not None and wt is not None and wf >= wt:
        return _med_redirect(dk, "bad_med")
    col = "" if auto_color else color.strip()[:16]
    if col and not re.fullmatch(r"#[0-9a-fA-F]{6}", col):
        return _med_redirect(dk, "bad_med")
    err = _patch_doctor(dk, name=nm, spec=spec.strip()[:60], room=room.strip()[:30],
                        phone=phone.strip()[:30], email=email.strip()[:80],
                        color=col, work_from=wf, work_to=wt, status=st)
    return _med_redirect(dk, "save_err" if err else "ok_med")


@app.post("/admin/doctor-card/{dk}/services")
async def doctor_card_services(request: Request, dk: str):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    form = await request.form()
    picked = set(form.getlist("svc"))
    all_ids = [d["id"] for d in eng.CONFIG["doctors"]]
    services = []
    for s in eng.CONFIG["services"]:
        sid = s["id"]
        docs = list(s.get("docs") or [])
        entry = dict(s)
        if sid in picked:
            if docs and dk not in docs:
                docs.append(dk)
            # пустой docs = «все медики», этот тоже входит — менять нечего
        else:
            # «все врачи» → материализуем список, иначе бифу не снять.
            # Список берём ПОЛНЫЙ (с отпускниками): вернётся из отпуска —
            # снова будет выполнять услугу, забывать это нельзя.
            docs = ([k for k in all_ids if k != dk] if not docs
                    else [k for k in docs if k != dk])
            # ⚠️ v1.9.1: проверять НЕПУСТОТУ мало. Список из одних отпускников/
            # архивных непуст, но allowed_doc_items() пересекает его с
            # ACTIVE_DOCTORS → пусто → услуга ПРОПАДАЕТ из меню бота, а админ
            # видит зелёный баннер. Гейт считает только активных.
            if not any(eng.DOCTOR_META.get(k, {}).get("active") for k in docs):
                return _med_redirect(dk, "svc_empty")
        if docs:
            entry["docs"] = docs
        else:
            entry.pop("docs", None)
        services.append(entry)
    err = _save_cfg(services=services)
    return _med_redirect(dk, "save_err" if err else "ok_svc_med")


@app.post("/admin/doctor-card/{dk}/photo")
async def doctor_card_photo(request: Request, dk: str, file: UploadFile = File(...)):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    cap, buf = MAX_PHOTO_MB * 1024 * 1024, bytearray()
    try:
        while chunk := await file.read(1024 * 256):
            buf += chunk
            if len(buf) > cap:
                return _med_redirect(dk, "bad_photo")
    finally:
        await file.close()
    kind = _sniff_photo(bytes(buf[:16]))
    if not buf or not kind:
        return _med_redirect(dk, "bad_photo")
    old = _photo_path(dk)
    stored = _doctors_dir() / f"{dk}_{secrets.token_hex(6)}{kind[0]}"
    try:
        stored.write_bytes(bytes(buf))
    except OSError:
        stored.unlink(missing_ok=True)
        return _med_redirect(dk, "bad_photo")
    if _patch_doctor(dk, photo=stored.name):
        stored.unlink(missing_ok=True)      # конфиг не записался — файл не нужен
        return _med_redirect(dk, "save_err")
    if old and old != stored:
        old.unlink(missing_ok=True)
    return _med_redirect(dk, "ok_photo")


@app.post("/admin/doctor-card/{dk}/photo/del")
async def doctor_card_photo_del(request: Request, dk: str):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin/medici", status_code=303)
    old = _photo_path(dk)
    if _patch_doctor(dk, photo=""):
        return _med_redirect(dk, "save_err")  # конфиг не записался — файл храним
    if old:
        old.unlink(missing_ok=True)
    return _med_redirect(dk, "ok_med")


@app.get("/admin/doctor-photo/{dk}")
async def doctor_photo_get(request: Request, dk: str, v: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    p = _photo_path(dk)
    if not p:
        return Response(status_code=404)
    return FileResponse(p, media_type=_PHOTO_MIME.get(p.suffix.lower(), "image/jpeg"))


# ---------- действия ----------

def _back_redirect(back: str, fallback_date: str, msg: str) -> RedirectResponse:
    target = back if back.startswith("/admin") else f"/admin/all?date={fallback_date}"
    sep = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{sep}msg={msg}", status_code=303)


@app.post("/admin/add")
async def admin_add(
    request: Request,
    adate: str = Form(...), atime: str = Form(...), adoctor: str = Form(...),
    aservice: str = Form(...), aname: str = Form(...), aphone: str = Form(...),
    ayear: str = Form(""), back: str = Form(""),
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
    if len(digits) < 8:
        return _back_redirect(back, adate, "bad_phone")
    if not eng.DOCTOR_META.get(adoctor, {}).get("active", True):
        return _back_redirect(back, adate, "bad_off")  # выключенному не пишем
    if dt.minute not in (0, 30):
        return _back_redirect(back, adate, "bad_time")  # 30-мин сетка стартов
    if not eng.fits_clinic(dt, eng.svc_duration(aservice)):
        # визит не помещается в рабочее окно клиники (закрытие/обед)
        return _back_redirect(back, adate, "outside")
    year = int(ayear) if ayear.strip().isdigit() and 1900 <= int(ayear) <= 2026 else None
    r = await db.admin_add(name, phone, svc["ro"], doctor, dt, birth_year=year,
                           doctor_id=adoctor, service_id=aservice,
                           duration_min=eng.svc_duration(aservice))
    msg = "ok" if isinstance(r, int) else ("dup" if r == "dup" else "conflict")
    # ручную запись задним числом НЕ запрещаем (визит вносят постфактум), но и
    # молчать нельзя: запись на закрытый день чаще всего опечатка, а она просто
    # исчезает из журнала — её никто больше не увидит. Граница ДНЕВНАЯ: визит в
    # уже прошедший час сегодня — обычная работа регистратуры, а не ошибка
    if msg == "ok" and eng.is_past_day(dt.date()):
        msg = "ok_past"
    return _back_redirect(back, adate, msg)


@app.post("/admin/note")
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


@app.post("/admin/comment/{appt_id}")
async def admin_comment(request: Request, appt_id: int,
                        comment: str = Form(""), back: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    await db.set_comment(appt_id, comment.strip()[:300])
    return _back_redirect(back, "", "ok_comment")


@app.post("/admin/status/{appt_id}")
async def admin_status(request: Request, appt_id: int, to: str = Form(...), back: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    if to in {"arrived", "done", "noshow", "cancelled", "confirmed"}:
        ok = await db.set_status(appt_id, to)
        if not ok:
            # возврат в confirmed/arrived, а слот уже занят новой записью
            sep = "&" if "?" in back else "?"
            target = (back + f"{sep}msg=conflict") if back.startswith("/admin") \
                else "/admin?msg=conflict"
            return RedirectResponse(target, status_code=303)
    target = back if back.startswith("/admin") else "/admin"
    return RedirectResponse(target, status_code=303)


# ---------- печатный QR для пациентов ----------

@app.get("/admin/qr-print", response_class=HTMLResponse)
async def admin_qr_print(request: Request):
    if (deny := _guard(request)) is not None:
        return deny
    _run, username = _tg_state()
    if not username:
        return _shell(
            "<div class='banner err'>Botul Telegram nu este activ — setați tokenul în "
            "<a href='/admin/settings'>Setări</a>, apoi reveniți aici pentru QR.</div>",
            "QR pentru pacienți", active="qr")
    link = f"https://t.me/{username}"
    q = urllib.parse.quote(link, safe="")
    name = html.escape(eng.CLINIC_NAME)
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — QR pacienți</title><style>
 *{{box-sizing:border-box;margin:0;padding:0}}
 body{{font-family:'Segoe UI',system-ui,sans-serif;color:#1c2b33;display:flex;
      flex-direction:column;align-items:center;padding:10mm;text-align:center}}
 .noprint{{margin-bottom:8mm;display:flex;gap:10px}}
 .noprint button{{background:#0E9F8A;color:#fff;border:none;border-radius:8px;
      padding:10px 22px;font-size:15px;cursor:pointer}}
 .noprint a{{align-self:center;color:#0E9F8A}}
 .sheet{{border:2px dashed #ccd;border-radius:6mm;padding:12mm 16mm;max-width:150mm}}
 h1{{font-size:26pt;color:#0E9F8A}}
 h2{{font-size:15pt;color:#334;margin:4mm 0 8mm;font-weight:600}}
 img{{width:88mm;height:88mm}}
 .user{{font-size:14pt;color:#0E9F8A;font-weight:600;margin-top:4mm}}
 .how{{font-size:11pt;color:#556;margin-top:6mm;line-height:1.5}}
 .phone{{font-size:12pt;margin-top:6mm}}
 .brand{{font-size:8pt;color:#aab;margin-top:8mm}}
 @media print{{ .noprint{{display:none}} .sheet{{border:none}} body{{padding:0}} }}
</style></head><body>
<div class="noprint">
  <button onclick="window.print()">🖨 Printează</button>
  <a href="/admin">← Panou</a>
</div>
<div class="sheet">
  <h1>🦷 {name}</h1>
  <h2>Programare online — 24/7</h2>
  <img src="/qr?data={q}" alt="QR">
  <div class="user">Telegram: @{html.escape(username)}</div>
  <div class="how">Scanați codul cu camera telefonului și programați-vă în 40 de secunde.<br>
  Отсканируйте код камерой телефона — запись за 40 секунд.</div>
  <div class="phone">📞 {html.escape(eng.CLINIC_PHONE)}</div>
  <div class="brand">DentPilot</div>
</div>
</body></html>"""


# ---------- QR для демо ----------

@app.get("/qr")
async def qr(data: str) -> Response:
    img = qrcode.make(data[:500])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.get("/demo", response_class=HTMLResponse)
async def demo(url: str = "") -> str:
    target = (url or "http://localhost:8088").strip()[:500]
    q = urllib.parse.quote(target, safe="")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>DentPilot Demo — QR</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
justify-content:center;height:100vh;margin:0;background:#0E9F8A;color:#fff}}
img{{background:#fff;padding:18px;border-radius:12px;width:340px;height:340px}}
h1{{font-weight:600;font-size:22px}}p{{font-size:14px;opacity:.85}}</style></head><body>
<h1>🦷 Scanați pentru programare / Сканируйте для записи</h1>
<img src="/qr?data={q}" alt="QR">
<p>{html.escape(target)}</p></body></html>"""
