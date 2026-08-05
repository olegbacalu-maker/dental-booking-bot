import asyncio
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
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse,
                               Response)

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
from .core.visits import (SVC_PALETTE, _DOC_HUES, _STATUS_ICON, _avatar,
                          _card_modal, _collect_cards, _doc_hue, _doctors_dir,
                          _list, _parse_date, _photo_path)
from .modules.patients import routes as patients
from .modules.schedule import routes as schedule

app = FastAPI(title="DentPilot")
log = logging.getLogger("web")

# Модули подключаются здесь и только здесь. Модуль знает про core, db и engine,
# но ничего не знает про main.py — иначе импорт замкнулся бы в круг.
app.include_router(patients.router)
app.include_router(schedule.router)








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







_PALETTE_RO = {"green": "verde", "blue": "albastru", "amber": "portocaliu",
               "violet": "violet", "red": "roșu", "teal": "turcoaz"}



















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





# ---------- страница одного врача ----------



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




def _sniff_photo(head: bytes) -> tuple[str, str] | None:
    """(расширение, mime) по СОДЕРЖИМОМУ файла — имени и content-type не верим."""
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None








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
