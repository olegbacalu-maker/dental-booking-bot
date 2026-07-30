import asyncio
import html
import io
import os
import pathlib
import urllib.parse
from datetime import date, datetime, timedelta

import qrcode
from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import db
from . import engine as eng

app = FastAPI(title="DentArt Demo Bot")

STATIC = pathlib.Path(__file__).parent / "static"

URGENT_LABELS = {v[lang] for v in eng.SERVICES.values() if v.get("urgent")
                 for lang in ("ro", "ru")}

STATUS_LABEL = {
    "confirmed": "✅ confirmată",
    "done": "🟦 a venit",
    "noshow": "🟥 nu a venit",
    "cancelled": "❌ anulată",
}
MSG_BANNER = {
    "ok": ("ok", "Programare adăugată ✔"),
    "conflict": ("err", "Intervalul este deja ocupat la acest medic"),
    "dup": ("err", "Pacientul are deja o programare la această oră"),
    "bad": ("err", "Date invalide — verificați câmpurile"),
    "ok_note": ("ok", "Notiță adăugată — slotul este blocat pentru bot ✔"),
}

PANEL_CSS = """
 *{box-sizing:border-box}
 body{font-family:system-ui,'Segoe UI',Roboto,sans-serif;background:#f4f6f7;margin:0;padding:18px}
 h1{font-size:19px;color:#075e54;margin:0 0 4px}
 h1 a{color:#075e54;text-decoration:none}
 .sub{color:#777;font-size:12px;margin-bottom:14px}
 .nav{margin-bottom:12px}
 .nav a{display:inline-block;background:#fff;border:1px solid #cdd;border-radius:6px;
        padding:5px 12px;margin-right:6px;text-decoration:none;color:#075e54;font-size:14px}
 .nav a.primary{background:#075e54;color:#fff;border-color:#075e54}
 .nav b{font-size:15px;margin-right:8px}
 .banner{padding:8px 12px;border-radius:6px;margin-bottom:10px;font-size:14px}
 .banner.ok{background:#dff3e3;color:#14632a}
 .banner.err{background:#fde2e2;color:#8f1d1d}
 .tiles{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
 .tile{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);
       padding:10px 16px;min-width:110px;text-align:center}
 .tile b{display:block;font-size:22px;color:#075e54}
 .tile.warn b{color:#e8710a}
 .tile.bad b{color:#d23c3c}
 .tile span{font-size:12px;color:#667}
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;margin-bottom:16px}
 a.card{display:block;background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);
        padding:12px 14px;text-decoration:none;color:#1c2b33;border-left:4px solid #075e54}
 a.card:hover{box-shadow:0 2px 8px rgba(0,0,0,.15)}
 a.card b{font-size:15px}
 a.card .spec{color:#667;font-size:12px;margin:2px 0 8px}
 a.card .meta{font-size:13px;color:#334}
 a.card .meta .u{color:#e8710a;font-weight:600}
 table.grid{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:18px}
 table.grid th,table.grid td{border:1px solid #e4e8e9;padding:4px 6px;font-size:13px;vertical-align:top}
 table.grid th{background:#075e54;color:#fff;font-weight:600}
 table.grid th a{color:#fff}
 td.hour{width:52px;color:#555;font-weight:600;background:#fafbfb;text-align:center}
 .appt{border-radius:6px;padding:5px 7px;line-height:1.3}
 .appt.confirmed{background:#e5f6ec;border-left:3px solid #1d9e55}
 .appt.done{background:#e7eefc;border-left:3px solid #3466c4}
 .appt.noshow{background:#fdecec;border-left:3px solid #d23c3c}
 .appt.urgent{background:#fff1e0;border-left:3px solid #e8710a}
 .appt.note{background:#fffbe6;border-left:3px solid #d4b106;color:#5c4d00}
 dialog{border:none;border-radius:10px;box-shadow:0 6px 30px rgba(0,0,0,.25);padding:0;width:430px;max-width:95vw}
 dialog::backdrop{background:rgba(0,0,0,.35)}
 .dlg-head{background:#075e54;color:#fff;padding:10px 14px;font-weight:600;display:flex;justify-content:space-between}
 .dlg-head button{background:none;border:none;color:#fff;font-size:16px;cursor:pointer}
 .dlg-tabs{display:flex;gap:6px;padding:10px 14px 0}
 .tabbtn{flex:1;padding:7px;border:1px solid #ccd4d4;background:#f4f6f7;border-radius:6px;cursor:pointer;font-size:13px}
 .tabbtn.on{background:#075e54;color:#fff;border-color:#075e54}
 .dlg-form{display:flex;flex-direction:column;gap:8px;padding:12px 14px 14px}
 .dlg-form input,.dlg-form select{padding:8px 10px;border:1px solid #ccd4d4;border-radius:6px;font-size:14px}
 .dlg-form button{background:#075e54;color:#fff;border:none;border-radius:6px;padding:9px;cursor:pointer;font-size:14px}
 a.free{display:block;text-align:center;color:#b9c4c4;text-decoration:none;font-size:17px;padding:5px 0}
 a.free:hover{color:#075e54;background:#eef6f4;border-radius:6px}
 h2{font-size:15px;color:#075e54;margin:16px 0 8px}
 form.add{background:#fff;padding:12px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);
          display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:18px}
 form.add input,form.add select{padding:7px 9px;border:1px solid #ccd4d4;border-radius:6px;font-size:14px}
 form.add button{background:#075e54;color:#fff;border:none;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:14px}
 table.list{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.08)}
 table.list th,table.list td{padding:6px 10px;border-bottom:1px solid #eef1f1;text-align:left;font-size:13px}
 table.list th{background:#f0f4f4;color:#333}
 tr.cancelled td{opacity:.45;text-decoration:line-through}
 .act{display:inline}
 .act button{border:none;border-radius:4px;padding:3px 8px;margin-right:4px;cursor:pointer;font-size:12px;color:#fff}
 .b-done{background:#3466c4}.b-noshow{background:#d23c3c}.b-cancel{background:#888}
 .hint{color:#999;font-size:12px;margin-top:10px}
"""

REFRESH_JS = """
<script>
setInterval(function(){
  if(document.querySelector("dialog[open]"))return;
  var a=document.activeElement;
  if(!a||(a.tagName!=="INPUT"&&a.tagName!=="SELECT"&&a.tagName!=="TEXTAREA"))location.reload();
},12000);
</script>
"""


def _shell(body: str, sub: str) -> str:
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(eng.CLINIC_NAME)} — registru</title><style>{PANEL_CSS}</style></head><body>
<h1>🦷 <a href="/admin">{html.escape(eng.CLINIC_NAME)} — registrul clinicii</a></h1>
<div class="sub">{sub}</div>
{body}
{REFRESH_JS}</body></html>"""


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(eng.TZ).date()


def _date_nav(d: date, base: str, extra: str = "") -> str:
    prev_d, next_d = d - timedelta(days=1), d + timedelta(days=1)
    lbl = eng.day_label(eng.Session(lang="ro"), d)
    return (f"<div class='nav'><b>{lbl} {d.isoformat()}</b>"
            f"<a href='{base}?date={prev_d.isoformat()}'>◀ {prev_d.strftime('%d.%m')}</a>"
            f"<a href='{base}'>Azi</a>"
            f"<a href='{base}?date={next_d.isoformat()}'>{next_d.strftime('%d.%m')} ▶</a>"
            f"{extra}</div>")


def _banner(msg: str, d: date) -> str:
    out = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        out += f"<div class='banner {cls}'>{text}</div>"
    if not eng.hours_for(d):
        out += "<div class='banner err'>Zi liberă — clinica este închisă (bot-ul nu oferă această zi)</div>"
    return out


def _grid(d: date, doctors_items: list, active: dict, href_fn) -> str:
    hours = [x.hour for x in eng.day_slots(d)]
    out = ["<table class='grid'><tr><th></th>"]
    for dk, name in doctors_items:
        spec = eng.DOCTOR_SPEC.get(dk, "")
        out.append(f"<th><a href='/admin/doctor/{dk}?date={d.isoformat()}'>{html.escape(name)}</a>"
                   f"<br><small style='font-weight:400;opacity:.8'>{html.escape(spec)}</small></th>")
    out.append("</tr>")
    for h in hours:
        out.append(f"<tr><td class='hour'>{h:02d}:00</td>")
        for dk, dname in doctors_items:
            r = active.get((dname, h))
            if r and r["source"] == "note":
                out.append(f"<td><div class='appt note'>📝 {html.escape(r['service'])}</div></td>")
            elif r:
                src = "🤖" if r["source"] == "bot" else "✍️"
                urgent = r["service"] in URGENT_LABELS
                cls = r["status"] + (" urgent" if urgent else "")
                svc_txt = ("🆘 " if urgent else "") + html.escape(r["service"])
                out.append(
                    f"<td><div class='appt {cls}'><b>{html.escape(r['name'] or '—')}</b> {src}"
                    f"<br>{svc_txt}<br><small>{html.escape(r['phone'] or '')}</small></div></td>"
                )
            else:
                out.append(
                    f"<td><a class='free' href='{href_fn(dk, h)}' "
                    f"onclick=\"openSlot('{dk}','{html.escape(dname)}','{h:02d}:00');return false\">+</a></td>"
                )
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def _form(d: date, doctors_items: list, sel_doctor: str, sel_time: str, back: str) -> str:
    hours = [x.hour for x in eng.day_slots(d)]
    time_opts = "".join(
        f"<option value='{h:02d}:00'{' selected' if sel_time == f'{h:02d}:00' else ''}>{h:02d}:00</option>"
        for h in hours
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
  <button>Adaugă</button>
</form>"""


def _list(rows: list, back: str) -> str:
    items = []
    for r in rows:
        dt_txt = r["starts_at"].astimezone(eng.TZ).strftime("%H:%M")
        is_note = r["source"] == "note"
        src = "📝 notiță" if is_note else ("🤖 bot" if r["source"] == "bot" else "✍️ manual")
        svc_txt = (("📝 " if is_note else "🆘 " if r["service"] in URGENT_LABELS else "")
                   + html.escape(r["service"]))
        acts = ""
        if r["status"] == "confirmed":
            buttons = ([("cancelled", "b-cancel", "Șterge")] if is_note else [
                ("done", "b-done", "A venit"),
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
        items.append(
            f"<tr class='{r['status']}'><td>{r['id']}</td><td>{dt_txt}</td>"
            f"<td>{html.escape(r['name'] or '')}</td><td>{html.escape(r['phone'] or '')}</td>"
            f"<td>{svc_txt}</td><td>{html.escape(r['doctor'])}</td>"
            f"<td>{src}</td><td>{STATUS_LABEL.get(r['status'], r['status'])}</td><td>{acts}</td></tr>"
        )
    return (
        "<h2>Lista zilei</h2><table class='list'>"
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
    <button>Adaugă programarea</button>
  </form>
  <form id="tab_n" class="dlg-form" method="post" action="/admin/note" style="display:none">
    <input type="hidden" name="back" value="{html.escape(back)}">
    <input type="hidden" name="ndate" value="{d.isoformat()}">
    <input type="hidden" name="ntime" id="m_time_n">
    <input type="hidden" name="ndoctor" id="m_doc_n">
    <input name="ntext" placeholder="ex.: pauză de masă, ședință, rezervat telefonic…" maxlength="120" required>
    <button>Salvează notița (blochează slotul)</button>
  </form>
</dialog>
<script>
function openSlot(dk, dname, hh) {{
  document.getElementById('m_doc_a').value = dk;
  document.getElementById('m_doc_n').value = dk;
  document.getElementById('m_time_a').value = hh;
  document.getElementById('m_time_n').value = hh;
  document.getElementById('m_title').textContent = dname + ' — ' + hh;
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


def _active_map(rows: list) -> dict:
    out = {}
    for r in rows:
        if r["status"] != "cancelled":
            out[(r["doctor"], r["starts_at"].astimezone(eng.TZ).hour)] = r
    return out


@app.on_event("startup")
async def startup() -> None:
    await db.init(eng.build_seed_rows())
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
    return {"ok": True}


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

@app.get("/admin", response_class=HTMLResponse)
async def admin_home(date_q: str = Query("", alias="date"), msg: str = "") -> str:
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = await db.day_appointments(day_start, day_start + timedelta(days=1))
    act = [r for r in rows
           if r["status"] != "cancelled" and r["source"] != "note"]

    total = len(act)
    n_bot = sum(1 for r in act if r["source"] == "bot")
    n_man = total - n_bot
    n_urg = sum(1 for r in act if r["service"] in URGENT_LABELS)
    n_noshow = sum(1 for r in rows if r["status"] == "noshow")
    tiles = (
        f"<div class='tiles'>"
        f"<div class='tile'><b>{total}</b><span>programări azi</span></div>"
        f"<div class='tile'><b>{n_bot}</b><span>🤖 prin bot</span></div>"
        f"<div class='tile'><b>{n_man}</b><span>✍️ recepție</span></div>"
        f"<div class='tile warn'><b>{n_urg}</b><span>🆘 urgențe</span></div>"
        f"<div class='tile bad'><b>{n_noshow}</b><span>neprezentări</span></div>"
        f"</div>"
    )

    cards = ["<div class='cards'>"]
    for dk, name in eng.DOCTORS.items():
        mine = [r for r in act if r["doctor"] == name]
        urg = sum(1 for r in mine if r["service"] in URGENT_LABELS)
        free = await eng.free_slots(dk, d)
        nxt = free[0].astimezone(eng.TZ).strftime("%H:%M") if free else "—"
        urg_txt = f" · <span class='u'>🆘 {urg}</span>" if urg else ""
        cards.append(
            f"<a class='card' href='/admin/doctor/{dk}?date={d.isoformat()}'>"
            f"<b>{html.escape(name)}</b>"
            f"<div class='spec'>{html.escape(eng.DOCTOR_SPEC.get(dk, ''))}</div>"
            f"<div class='meta'>{len(mine)} programări{urg_txt} · liber de la {nxt}</div></a>"
        )
    cards.append("</div>")

    extra = f"<a class='primary' href='/admin/all?date={d.isoformat()}'>📋 Toți medicii</a>"
    body = _date_nav(d, "/admin", extra) + _banner(msg, d) + tiles + "".join(cards) + \
        "<p class='hint'>Click pe un medic — ziua lui. Programările prin bot apar automat (aceeași bază de date).</p>"
    return _shell(body, "panou principal · 🤖 bot / ✍️ recepție · se actualizează automat · demo, date sintetice")


# ---------- общая сетка: все врачи ----------

@app.get("/admin/all", response_class=HTMLResponse)
async def admin_all(
    date_q: str = Query("", alias="date"),
    doctor: str = "", time_pre: str = "", msg: str = "",
) -> str:
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = await db.day_appointments(day_start, day_start + timedelta(days=1))
    active = _active_map(rows)
    items = list(eng.DOCTORS.items())
    back = f"/admin/all?date={d.isoformat()}"

    def href(dk, h):
        return f"/admin/all?date={d.isoformat()}&doctor={dk}&time_pre={h:02d}:00#addform"

    body = (_date_nav(d, "/admin/all", f"<a href='/admin?date={d.isoformat()}'>🏠 Panou</a>")
            + _banner(msg, d)
            + _grid(d, items, active, href)
            + _form(d, items, doctor, time_pre, back)
            + _list(rows, back)
            + _slot_modal(d, back))
    return _shell(body, "toți medicii · 🤖 bot / ✍️ recepție / 📝 notițe · demo, date sintetice")


# ---------- страница одного врача ----------

@app.get("/admin/doctor/{dk}", response_class=HTMLResponse)
async def admin_doctor(
    dk: str, date_q: str = Query("", alias="date"),
    time_pre: str = "", msg: str = "",
) -> str:
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin")
    name = eng.DOCTORS[dk]
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = [r for r in await db.day_appointments(day_start, day_start + timedelta(days=1))
            if r["doctor"] == name]
    active = _active_map(rows)
    items = [(dk, name)]
    base = f"/admin/doctor/{dk}"
    back = f"{base}?date={d.isoformat()}"

    def href(_dk, h):
        return f"{base}?date={d.isoformat()}&time_pre={h:02d}:00#addform"

    head = (f"<div class='nav'><b>{html.escape(name)}</b> "
            f"<span style='color:#667'>{html.escape(eng.DOCTOR_SPEC.get(dk, ''))}</span> "
            f"<a href='/admin?date={d.isoformat()}'>🏠 Panou</a>"
            f"<a href='/admin/all?date={d.isoformat()}'>📋 Toți medicii</a></div>")
    body = (head + _date_nav(d, base) + _banner(msg, d)
            + _grid(d, items, active, href)
            + _form(d, items, dk, time_pre, back)
            + _list(rows, back)
            + _slot_modal(d, back))
    return _shell(body, "ziua unui medic · 🤖 bot / ✍️ recepție / 📝 notițe · demo, date sintetice")


# ---------- действия ----------

def _back_redirect(back: str, fallback_date: str, msg: str) -> RedirectResponse:
    target = back if back.startswith("/admin") else f"/admin/all?date={fallback_date}"
    sep = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{sep}msg={msg}", status_code=303)


@app.post("/admin/add")
async def admin_add(
    adate: str = Form(...), atime: str = Form(...), adoctor: str = Form(...),
    aservice: str = Form(...), aname: str = Form(...), aphone: str = Form(...),
    back: str = Form(""),
):
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
    if not doctor or not svc or not name or len(digits) < 8:
        return _back_redirect(back, adate, "bad")
    r = await db.admin_add(name, phone, svc["ro"], doctor, dt)
    msg = "ok" if isinstance(r, int) else ("dup" if r == "dup" else "conflict")
    return _back_redirect(back, adate, msg)


@app.post("/admin/note")
async def admin_note(
    ndate: str = Form(...), ntime: str = Form(...), ndoctor: str = Form(...),
    ntext: str = Form(...), back: str = Form(""),
):
    try:
        d = date.fromisoformat(ndate)
        hh, mm = ntime.split(":")
        dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return _back_redirect(back, ndate, "bad")
    doctor = eng.DOCTORS.get(ndoctor)
    text = ntext.strip()[:120]
    if not doctor or not text:
        return _back_redirect(back, ndate, "bad")
    r = await db.add_note(doctor, dt, text)
    return _back_redirect(back, ndate, "ok_note" if r else "conflict")


@app.post("/admin/status/{appt_id}")
async def admin_status(appt_id: int, to: str = Form(...), back: str = Form("")):
    if to in {"done", "noshow", "cancelled", "confirmed"}:
        await db.set_status(appt_id, to)
    target = back if back.startswith("/admin") else "/admin"
    return RedirectResponse(target, status_code=303)


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
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>DentArt Demo — QR</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
justify-content:center;height:100vh;margin:0;background:#075e54;color:#fff}}
img{{background:#fff;padding:18px;border-radius:12px;width:340px;height:340px}}
h1{{font-weight:600;font-size:22px}}p{{font-size:14px;opacity:.85}}</style></head><body>
<h1>🦷 Scanați pentru programare / Сканируйте для записи</h1>
<img src="/qr?data={q}" alt="QR">
<p>{html.escape(target)}</p></body></html>"""
