import asyncio
import csv
import hashlib
import hmac
import html
import io
import json
import os
import pathlib
import re
import secrets
import sys
import urllib.parse
from datetime import date, datetime, timedelta

import qrcode
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse,
                               Response)

from . import db
from . import engine as eng
from . import update as upd

app = FastAPI(title="DentPilot")

STATIC = pathlib.Path(__file__).parent / "static"


@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    """Отсекает гигантские POST-тела ДО того, как Starlette спулит multipart
    во временный файл (сам по себе роут-кап 25MB срабатывает уже после)."""
    if request.method == "POST":
        cl = request.headers.get("content-length", "")
        if cl.isdigit() and int(cl) > (26) * 1024 * 1024:  # 25MB файла + запас
            return Response("Payload too large", status_code=413)
    return await call_next(request)

# --- защита журнала ---
# Desktop (SQLite): PIN 4–6 цифр, ставится в самом приложении (data/auth.json,
# hash+salt); «забыл PIN» = удалить этот файл → снова экран установки.
# Cloud (Postgres): по-прежнему ADMIN_KEY из .env.
ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()

FEEDBACK_EMAIL = "dentpilotpro@gmail.com"


def _data_dir() -> pathlib.Path | None:
    if db.IS_SQLITE:
        return pathlib.Path(db.DATABASE_URL.split("///", 1)[1]).parent
    return None


def _auth_path() -> pathlib.Path | None:
    d = _data_dir()
    return d / "auth.json" if d else None


def _pin_rec() -> dict | None:
    p = _auth_path()
    if p and p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _pin_hash(pin: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()


def _secret() -> str:
    rec = _pin_rec()
    if rec:
        return rec.get("hash", "")
    return ADMIN_KEY


def _sec_warn() -> str:
    if _secret() or db.IS_SQLITE:
        return ""
    return " · ⚠️ fără parolă — setați ADMIN_KEY în .env"


def _cookie_sig() -> str:
    return hmac.new(_secret().encode(), b"dentart-admin-v1", hashlib.sha256).hexdigest()


def _set_auth_cookie(resp: RedirectResponse) -> RedirectResponse:
    resp.set_cookie("admin_auth", _cookie_sig(), max_age=60 * 60 * 24 * 30,
                    httponly=True, samesite="lax")
    return resp


def _guard(request: Request) -> RedirectResponse | None:
    sec = _secret()
    if not sec:
        if db.IS_SQLITE:
            # desktop без PIN — принудительная первичная установка
            return RedirectResponse("/admin/setup", status_code=303)
        return None  # облачный демо-режим без ключа
    if hmac.compare_digest(request.cookies.get("admin_auth", ""), _cookie_sig()):
        return None
    q = str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(
        f"/admin/login?next={urllib.parse.quote(q, safe='')}", status_code=303)


LOGIN_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — acces</title><style>
 body{font-family:system-ui,'Segoe UI',sans-serif;background:#f4f6f7;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0}
 form{background:#fff;padding:26px 30px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.12);
      display:flex;flex-direction:column;gap:10px;width:320px}
 h1{font-size:17px;color:#075e54;margin:0 0 4px}
 input{padding:10px 12px;border:1px solid #ccd4d4;border-radius:6px;font-size:15px}
 button{background:#075e54;color:#fff;border:none;border-radius:6px;padding:10px;font-size:15px;cursor:pointer}
 .err{color:#c62828;font-size:13px}
</style></head><body>
<form method="post" action="/admin/login">
  <h1>🦷 __CLINIC__ — registrul clinicii</h1>
  __ERR__
  <input type="hidden" name="next" value="__NEXT__">
  __INPUT__
  <button>Intră</button>
  __HINT__
</form></body></html>"""

PIN_INPUT = ("<input type='password' name='password' placeholder='PIN' autofocus required "
             "inputmode='numeric' pattern='[0-9]*' maxlength='6' "
             "style='text-align:center;font-size:28px;letter-spacing:12px'>")
PASS_INPUT = "<input type='password' name='password' placeholder='Parola' autofocus required>"
PIN_HINT = ("<div style='color:#889;font-size:12px'>PIN uitat? Închideți programul și "
            "ștergeți fișierul <b>data\\auth.json</b> — la pornire veți seta un PIN nou.</div>")

STATUS_LABEL = {
    "confirmed": "✅ confirmată",
    "arrived": "🟢 în cabinet",
    "done": "🟦 a venit",
    "noshow": "🟥 nu a venit",
    "cancelled": "❌ anulată",
}
# статусы, при которых слот занят — единый источник правды в db.py
LIVE_STATUSES = db.ACTIVE_STATUSES
MSG_BANNER = {
    "ok": ("ok", "Programare adăugată ✔"),
    "conflict": ("err", "Intervalul este deja ocupat la acest medic"),
    "dup": ("err", "Pacientul are deja o programare la această oră"),
    "bad": ("err", "Date invalide — verificați câmpurile"),
    "ok_note": ("ok", "Notiță adăugată — slotul este blocat pentru bot ✔"),
    "ok_comment": ("ok", "Comentariu salvat ✔"),
    "ok_set": ("ok", "Setări salvate ✔ — botul folosește deja noile date"),
    "upd_err": ("err", "Actualizarea a eșuat — vezi detalii în pagina de setări / log"),
    "ok_pin": ("ok", "PIN schimbat ✔"),
    "bad_pin": ("err", "PIN-ul vechi e greșit sau cel nou nu are 4–6 cifre identice"),
    "bad_tok": ("err", "Token invalid — copiați exact tokenul de la @BotFather"),
    "ok_tok": ("ok", "Token salvat ✔ — reporniți programul pentru aplicare"),
    "part_note": ("ok", "Pauza a fost salvată parțial — unele ore erau deja ocupate"),
    "bad_set": ("err", "Setări invalide — verificați câmpurile (nume/telefon, ore, minim un medic și un serviciu)"),
    "ok_card": ("ok", "Fișa pacientului a fost actualizată ✔"),
    "bad_card": ("err", "Date invalide — verificați câmpurile fișei"),
    "ok_doc": ("ok", "Document încărcat ✔ — rămâne local, în folderul programului"),
    "bad_doc": ("err", "Fișier gol sau prea mare (max 25 MB)"),
}

# Дизайн-система v1.5.0 (референс: светлый SaaS-макет Олега 07-31):
# фон #F8FAFC, текст #1F2937/#6B7280, один акцент Teal, тени вместо границ,
# радиусы 12/16, отступы 8/16/24/32, типографика 600/400 без капса.
PANEL_CSS = """
 :root{--bg:#F8FAFC;--panel:#FFFFFF;--line:#E5E7EB;--line2:#F1F5F9;
   --text:#1F2937;--text2:#6B7280;--text3:#9CA3AF;
   --teal:#0D9488;--teal-d:#0F766E;--teal-soft:#F0FDFA;--teal-line:#CCFBF1;
   --green:#059669;--green-soft:#ECFDF5;--blue:#3B82F6;--blue-soft:#EFF6FF;
   --amber:#D97706;--amber-soft:#FFFBEB;--red:#DC2626;--red-soft:#FEF2F2;
   --violet:#7C3AED;--violet-soft:#F5F3FF;
   --sh:0 1px 3px rgba(16,24,40,.07),0 1px 2px rgba(16,24,40,.04);
   --sh2:0 4px 12px rgba(16,24,40,.10)}
 *{box-sizing:border-box}
 body{font-family:'Segoe UI Variable Text','Segoe UI',system-ui,Roboto,sans-serif;
   background:var(--bg);margin:0;color:var(--text);display:flex;min-height:100vh}
 a{color:var(--teal)}
 /* ---------- каркас: сайдбар + топбар + контент ---------- */
 .side{width:216px;flex:0 0 216px;background:var(--panel);border-right:1px solid var(--line);
   display:flex;flex-direction:column;position:sticky;top:0;height:100vh;overflow-y:auto}
 .side .brand{display:flex;align-items:center;gap:10px;padding:18px 16px 14px}
 .side .brand .logo{width:34px;height:34px;border-radius:10px;background:var(--teal);color:#fff;
   display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;flex:0 0 34px}
 .side .brand b{font-size:15px;display:block;line-height:1.2}
 .side .brand small{color:var(--text2);font-size:11.5px;display:block;white-space:nowrap;
   overflow:hidden;text-overflow:ellipsis;max-width:130px}
 .side .sec{font-size:10.5px;font-weight:600;letter-spacing:.08em;color:var(--text3);
   padding:14px 18px 6px;text-transform:uppercase}
 .side nav a{display:flex;align-items:center;gap:10px;margin:2px 10px;padding:8px 10px;
   border-radius:10px;text-decoration:none;color:var(--text2);font-size:13.5px;font-weight:500}
 .side nav a svg{flex:0 0 16px}
 .side nav a:hover{background:var(--line2);color:var(--text)}
 .side nav a.on{background:var(--teal-soft);color:var(--teal-d);font-weight:600}
 .side nav a .dot{width:7px;height:7px;border-radius:50%;margin-left:auto}
 .side nav a .dot.ok{background:var(--green)}
 .side nav a .dot.off{background:var(--text3)}
 .side .sfoot{margin-top:auto;padding:12px 16px;border-top:1px solid var(--line);
   font-size:11.5px;color:var(--text3)}
 .main{flex:1;min-width:0;display:flex;flex-direction:column}
 .top{height:58px;flex:0 0 58px;background:var(--panel);border-bottom:1px solid var(--line);
   display:flex;align-items:center;gap:10px;padding:0 20px;position:sticky;top:0;z-index:20}
 .top form.searchf{display:flex;gap:0;align-items:center;background:var(--bg);
   border:1px solid var(--line);border-radius:10px;padding:0 6px 0 12px;height:36px;width:320px;margin:0}
 .top form.searchf input{border:none;background:none;outline:none;font-size:13px;flex:1;color:var(--text)}
 .top form.searchf button{background:none;border:none;color:var(--text3);cursor:pointer;font-size:14px;padding:4px 6px}
 .top .kbd{font-size:10.5px;color:var(--text3);border:1px solid var(--line);border-radius:5px;padding:1px 5px}
 .top .bell{position:relative;width:36px;height:36px;border-radius:10px;display:flex;align-items:center;
   justify-content:center;color:var(--text2);text-decoration:none;font-size:16px}
 .top .bell:hover{background:var(--line2)}
 .top .bell .n{position:absolute;top:2px;right:2px;min-width:15px;height:15px;border-radius:8px;
   background:var(--red);color:#fff;font-size:9.5px;font-weight:600;line-height:15px;text-align:center;padding:0 3px}
 .top .newbtn{display:flex;align-items:center;gap:7px;height:38px;padding:0 16px;border-radius:10px;
   background:var(--teal);color:#fff;font-size:13.5px;font-weight:600;text-decoration:none}
 .top .newbtn:hover{background:var(--teal-d)}
 .content{padding:20px 24px 60px;max-width:1500px}
 /* ---------- общие элементы ---------- */
 h1{font-size:19px;margin:0 0 4px;font-weight:600}
 h1 a{color:var(--text);text-decoration:none}
 h2{font-size:15px;color:var(--text);margin:20px 0 10px;font-weight:600}
 .sub{color:var(--text3);font-size:12px;margin-bottom:14px}
 .nav{margin-bottom:14px;display:flex;align-items:center;flex-wrap:wrap;gap:6px}
 .nav b{font-size:15px;margin-right:6px;font-weight:600}
 .nav a{display:inline-block;background:var(--panel);border:1px solid var(--line);border-radius:10px;
        padding:6px 13px;text-decoration:none;color:var(--text2);font-size:13px;font-weight:500}
 .nav a:hover{border-color:var(--teal);color:var(--teal-d)}
 .nav a.primary{background:var(--teal);color:#fff;border-color:var(--teal)}
 .nav form.dpickf{display:inline-block;margin:0}
 .nav input.dpick{padding:5px 8px;border:1px solid var(--line);border-radius:10px;font-size:13px;
   background:var(--panel);color:var(--text2)}
 .nav form.searchf{display:flex;gap:6px;align-items:center;margin:0}
 .nav form.searchf input{padding:6px 11px;border:1px solid var(--line);border-radius:10px;
   font-size:13px;width:240px;background:var(--panel);color:var(--text);outline:none}
 .nav form.searchf input:focus{border-color:var(--teal)}
 .nav form.searchf button{background:var(--teal);color:#fff;border:none;border-radius:10px;
   padding:7px 13px;cursor:pointer;font-size:13px;font-weight:600}
 .banner{padding:9px 14px;border-radius:10px;margin-bottom:12px;font-size:13.5px}
 .banner.ok{background:var(--green-soft);color:#065F46}
 .banner.err{background:var(--red-soft);color:#991B1B}
 .statbar{background:var(--line2);border-radius:4px;height:8px;overflow:hidden}
 .statbar div{background:var(--teal);height:8px}
 /* ---------- KPI ---------- */
 .tiles{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
 .tile{background:var(--panel);border-radius:14px;box-shadow:var(--sh);padding:14px 16px;
   min-width:170px;flex:1;display:flex;gap:12px;align-items:flex-start}
 a.tile{text-decoration:none;color:inherit;transition:box-shadow .15s,transform .15s}
 a.tile:hover{box-shadow:var(--sh2);transform:translateY(-1px)}
 .tile .ico{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;
   justify-content:center;font-size:17px;flex:0 0 38px}
 .tile b{display:block;font-size:24px;font-weight:600;line-height:1.1}
 .tile span{font-size:12px;color:var(--text2);font-weight:500}
 .tile .trend{display:block;font-size:11.5px;margin-top:3px;color:var(--text3)}
 .tile .trend .up{color:var(--green);font-weight:600}
 .tile .trend .dn{color:var(--red);font-weight:600}
 .tile.warn b{color:var(--amber)}
 .tile.bad b{color:var(--red)}
 /* ---------- дневная сетка (canvas) ---------- */
 .dash{display:flex;gap:16px;align-items:flex-start}
 .dashmain{flex:1;min-width:0}
 .rail{width:300px;flex:0 0 300px;display:flex;flex-direction:column;gap:14px}
 .gridcard{background:var(--panel);border-radius:16px;box-shadow:var(--sh);overflow:hidden}
 .gridhead{display:flex;border-bottom:1px solid var(--line)}
 .gridhead .gh-time{width:56px;flex:0 0 56px;border-right:1px solid var(--line2)}
 .gridhead .gh-doc{flex:1;min-width:0;padding:10px 12px;display:flex;gap:9px;align-items:center;
   border-right:1px solid var(--line2)}
 .gridhead .gh-doc:last-child{border-right:none}
 .gh-doc .av{width:32px;height:32px;border-radius:9px;color:#fff;display:flex;align-items:center;
   justify-content:center;font-size:12px;font-weight:600;flex:0 0 32px}
 .gh-doc .nm{min-width:0}
 .gh-doc .nm a{font-size:13px;font-weight:600;color:var(--text);text-decoration:none;white-space:nowrap}
 .gh-doc .nm a:hover{color:var(--teal-d)}
 .gh-doc .nm small{display:block;font-size:11px;color:var(--text3);white-space:nowrap;
   overflow:hidden;text-overflow:ellipsis}
 .gh-doc .st{width:8px;height:8px;border-radius:50%;margin-left:auto;flex:0 0 8px}
 .gridbody{display:flex;position:relative;--cell:56px}
 .gcol-time{width:56px;flex:0 0 56px;border-right:1px solid var(--line2);background:var(--bg)}
 .gcol-time div{height:var(--cell);font-size:11px;color:var(--text3);text-align:right;padding:4px 8px 0}
 .gcol{flex:1;min-width:0;border-right:1px solid var(--line2);position:relative}
 .gcol:last-child{border-right:none}
 .gcell{height:var(--cell);border-bottom:1px solid var(--line2);cursor:pointer;position:relative}
 .gcell:hover{background:var(--teal-soft)}
 .gcell:hover::after{content:'+';position:absolute;inset:0;display:flex;align-items:center;
   justify-content:center;color:var(--teal);font-size:18px}
 .gcell.off{cursor:default;background:repeating-linear-gradient(135deg,var(--line2) 0 5px,transparent 5px 11px)}
 .gcell.off:hover{background:repeating-linear-gradient(135deg,var(--line2) 0 5px,transparent 5px 11px)}
 .gcell.off:hover::after{content:''}
 .gappt{position:absolute;left:4px;right:4px;border-radius:9px;padding:5px 8px;overflow:hidden;
   font-size:11.5px;line-height:1.35;cursor:pointer;box-shadow:0 1px 2px rgba(16,24,40,.06);z-index:2}
 .gappt:hover{box-shadow:var(--sh2)}
 .gappt b{font-size:12px;font-weight:600;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .gappt small{color:inherit;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
 .gappt .stt{position:absolute;top:5px;right:7px;font-size:11px}
 .gappt.noshow{text-decoration:line-through;opacity:.75}
 .gappt.gnote{border:1px dashed var(--line);background:repeating-linear-gradient(135deg,var(--line2) 0 6px,transparent 6px 12px);color:var(--text2)}
 .nowline{position:absolute;left:0;right:0;height:2px;background:var(--red);z-index:5;pointer-events:none}
 .nowline::before{content:'';position:absolute;left:-4px;top:-3px;width:8px;height:8px;border-radius:50%;background:var(--red)}
 /* ---------- правая колонка ---------- */
 .mcal{background:var(--panel);border-radius:14px;box-shadow:var(--sh);padding:12px 14px}
 .mcal .mhead{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
 .mcal .mhead b{font-size:13px;font-weight:600}
 .mcal .mhead a{text-decoration:none;color:var(--text2);padding:2px 8px;border-radius:7px}
 .mcal .mhead a:hover{background:var(--line2)}
 .mcal table{width:100%;border-collapse:collapse}
 .mcal th{font-size:10px;color:var(--text3);font-weight:500;padding:2px 0}
 .mcal td{text-align:center;padding:1px 0}
 .mcal td a{display:inline-flex;width:26px;height:26px;border-radius:8px;align-items:center;
   justify-content:center;font-size:11.5px;color:var(--text2);text-decoration:none}
 .mcal td a:hover{background:var(--line2)}
 .mcal td a.oth{color:var(--text3);opacity:.5}
 .mcal td a.tdy{box-shadow:inset 0 0 0 1.5px var(--teal);color:var(--teal-d);font-weight:600}
 .mcal td a.seld{background:var(--teal);color:#fff;font-weight:600}
 /* ---------- старые страницы (перекрашены) ---------- */
 .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-bottom:16px}
 a.card{display:block;background:var(--panel);border-radius:14px;box-shadow:var(--sh);
        padding:14px 16px;text-decoration:none;color:var(--text)}
 a.card:hover{box-shadow:var(--sh2)}
 a.card b{font-size:14.5px}
 a.card .spec{color:var(--text2);font-size:12px;margin:2px 0 8px}
 a.card .meta{font-size:12.5px;color:var(--text2)}
 a.card .meta .u{color:var(--amber);font-weight:600}
 table.grid{border-collapse:separate;border-spacing:0;width:100%;background:var(--panel);
   box-shadow:var(--sh);border-radius:14px;overflow:hidden;margin-bottom:18px}
 table.grid th,table.grid td{border-bottom:1px solid var(--line2);border-right:1px solid var(--line2);
   padding:5px 7px;font-size:12.5px;vertical-align:top}
 table.grid th{background:var(--panel);color:var(--text);font-weight:600;border-bottom:1px solid var(--line)}
 table.grid th a{color:var(--text);text-decoration:none}
 table.grid th a:hover{color:var(--teal-d)}
 td.hour{width:52px;color:var(--text3);font-weight:500;background:var(--bg);text-align:center;font-size:11.5px}
 .appt{border-radius:9px;padding:5px 8px;line-height:1.35}
 .appt.confirmed{background:var(--green-soft);border-left:3px solid var(--green)}
 .appt.arrived{background:var(--teal-soft);border-left:3px solid var(--teal)}
 .appt.done{background:var(--blue-soft);border-left:3px solid var(--blue)}
 .appt.noshow{background:var(--red-soft);border-left:3px solid var(--red)}
 .appt.urgent{background:var(--amber-soft);border-left:3px solid var(--amber)}
 .appt.note{background:var(--amber-soft);border-left:3px solid #EAB308;color:#713F12}
 .appt.clickable{cursor:pointer}
 .appt.clickable:hover{filter:brightness(.98)}
 .appt .cmt{color:#92710A;font-size:11.5px;margin-top:2px}
 a.plink{color:var(--teal-d);text-decoration:none;border-bottom:1px dashed var(--teal-line)}
 a.plink:hover{border-bottom-style:solid}
 .pcard{background:var(--panel);border-radius:14px;box-shadow:var(--sh);padding:14px 18px;margin-bottom:12px}
 .pcard h3{margin:0 0 6px;font-size:14.5px;color:var(--text)}
 .pcard .meta{color:var(--text2);font-size:12.5px;margin-bottom:8px}
 .vpast{opacity:.55}
 table.set{border-collapse:collapse;width:100%;background:var(--panel);box-shadow:var(--sh);
   border-radius:14px;overflow:hidden;margin-bottom:10px}
 table.set th,table.set td{padding:8px 12px;border-bottom:1px solid var(--line2);text-align:left;font-size:13px}
 table.set th{background:var(--bg);color:var(--text2);font-weight:600}
 table.set input[type=text],table.set input[type=number]{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:8px;font-size:13px}
 table.set select{padding:6px 7px;border:1px solid var(--line);border-radius:8px;font-size:13px}
 .rowdel{background:var(--red-soft);color:var(--red);border:none;border-radius:7px;padding:4px 10px;cursor:pointer}
 .addrow{background:none;border:1px dashed var(--teal);color:var(--teal-d);border-radius:10px;padding:7px 15px;cursor:pointer;margin-bottom:16px}
 .savebtn{background:var(--teal);color:#fff;border:none;border-radius:10px;padding:12px 26px;font-size:14.5px;font-weight:600;cursor:pointer}
 .savebtn:hover{background:var(--teal-d)}
 .dlg-status{display:flex;gap:6px;padding:0 14px 14px}
 .dlg-status form{flex:1;margin:0}
 .bstat{border:none;border-radius:8px;padding:9px 4px;color:#fff;cursor:pointer;font-size:13px;width:100%;font-weight:500}
 dialog{border:none;border-radius:16px;box-shadow:0 12px 40px rgba(16,24,40,.22);padding:0;width:430px;max-width:95vw}
 dialog::backdrop{background:rgba(15,23,42,.4)}
 .dlg-head{background:var(--panel);color:var(--text);padding:13px 16px;font-weight:600;font-size:14.5px;
   display:flex;justify-content:space-between;border-bottom:1px solid var(--line)}
 .dlg-head button{background:none;border:none;color:var(--text3);font-size:16px;cursor:pointer}
 .dlg-tabs{display:flex;gap:6px;padding:12px 16px 0}
 .tabbtn{flex:1;padding:8px;border:1px solid var(--line);background:var(--bg);border-radius:9px;cursor:pointer;font-size:13px;color:var(--text2)}
 .tabbtn.on{background:var(--teal);color:#fff;border-color:var(--teal);font-weight:600}
 .dlg-form{display:flex;flex-direction:column;gap:9px;padding:13px 16px 16px}
 .dlg-form input,.dlg-form select,.dlg-form textarea{padding:9px 11px;border:1px solid var(--line);border-radius:9px;font-size:13.5px}
 .dlg-form button{background:var(--teal);color:#fff;border:none;border-radius:9px;padding:10px;cursor:pointer;font-size:13.5px;font-weight:600}
 a.free{display:block;text-align:center;color:var(--text3);text-decoration:none;font-size:16px;padding:4px 0;border-radius:8px}
 a.free:hover{color:var(--teal-d);background:var(--teal-soft)}
 form.add{background:var(--panel);padding:14px;border-radius:14px;box-shadow:var(--sh);
          display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:18px}
 form.add input,form.add select{padding:8px 10px;border:1px solid var(--line);border-radius:9px;font-size:13.5px}
 form.add button{background:var(--teal);color:#fff;border:none;border-radius:9px;padding:9px 17px;cursor:pointer;font-size:13.5px;font-weight:600}
 table.list{border-collapse:collapse;width:100%;background:var(--panel);box-shadow:var(--sh);border-radius:14px;overflow:hidden}
 table.list th,table.list td{padding:8px 12px;border-bottom:1px solid var(--line2);text-align:left;font-size:13px}
 table.list th{background:var(--bg);color:var(--text2);font-weight:600}
 tr.cancelled td{opacity:.45;text-decoration:line-through}
 .act{display:inline}
 .act button{border:none;border-radius:7px;padding:4px 9px;margin-right:4px;cursor:pointer;font-size:12px;color:#fff}
 .b-arrived{background:var(--teal)}
 .b-done{background:var(--blue)}.b-noshow{background:var(--red)}.b-cancel{background:#94A3B8}
 .hint{color:var(--text3);font-size:12px;margin-top:10px}
 .botnew{background:var(--panel);border-radius:14px;box-shadow:var(--sh);padding:12px 14px;margin-bottom:14px}
 .botnew h3{margin:0 0 4px;font-size:13.5px;font-weight:600}
 .botnew a{display:block;padding:6px 0;font-size:12.5px;color:inherit;text-decoration:none;border-top:1px solid var(--line2)}
 .botnew a:hover{background:var(--bg)}
 .botnew .dt{color:var(--teal-d);font-weight:600}
 .botnew .crt{color:var(--text3);font-size:11.5px}
 .botnew .nou{background:var(--amber);color:#fff;border-radius:5px;padding:1px 6px;font-size:10.5px;margin-left:6px;font-weight:600}
 .brandcorner{position:fixed;right:14px;bottom:10px;font-size:11.5px;color:var(--text3);
   background:rgba(255,255,255,.94);padding:5px 12px;border-radius:14px;box-shadow:var(--sh);z-index:50}
 .brandcorner b{color:var(--teal-d)}
 .brandcorner a{color:var(--teal-d);text-decoration:none;font-weight:600}
 .brandcorner a:hover{text-decoration:underline}
 /* ---------- карточка пациента ---------- */
 .fisa{display:flex;gap:16px;align-items:flex-start}
 .fcol-l{width:300px;flex:0 0 300px;display:flex;flex-direction:column;gap:14px}
 .fcol-c{flex:1;min-width:0;display:flex;flex-direction:column;gap:14px}
 .fcol-r{width:300px;flex:0 0 300px;display:flex;flex-direction:column;gap:14px}
 .fcard{background:var(--panel);border-radius:14px;box-shadow:var(--sh);padding:14px 16px}
 .fcard h3{margin:0 0 10px;font-size:13.5px;font-weight:600}
 .fcard h3 small{color:var(--text3);font-weight:400;font-size:11.5px}
 .fhead{display:flex;align-items:center;gap:12px}
 .fhead .fav{width:48px;height:48px;border-radius:12px;background:var(--teal);color:#fff;
   display:flex;align-items:center;justify-content:center;font-size:17px;font-weight:600;flex:0 0 48px}
 .fhead b{font-size:16px;display:block;line-height:1.25}
 .fhead small{color:var(--text3);font-size:11.5px}
 .frow{display:flex;justify-content:space-between;gap:10px;padding:4px 0;font-size:12.5px}
 .frow span:first-child{color:var(--text3)}
 .frow span:last-child{color:var(--text);font-weight:500;text-align:right;min-width:0;
   overflow:hidden;text-overflow:ellipsis}
 .alert{display:flex;align-items:center;gap:8px;border-radius:9px;padding:7px 10px;
   font-size:12.5px;font-weight:600;margin-bottom:6px}
 .alert form{margin-left:auto}
 .alert button{background:none;border:none;cursor:pointer;color:inherit;opacity:.55;font-size:12px}
 .alert.allergy{background:var(--red-soft);color:var(--red)}
 .alert.medication{background:var(--amber-soft);color:var(--amber)}
 .alert.warning{background:var(--amber-soft);color:var(--amber)}
 .alert.info{background:var(--blue-soft);color:var(--blue)}
 .teeth{display:flex;justify-content:center;gap:3px;flex-wrap:nowrap;overflow-x:auto;padding:2px 0}
 .tooth{width:30px;height:38px;flex:0 0 30px;border-radius:7px;border:1px solid var(--line);
   background:var(--panel);color:var(--text2);display:flex;align-items:center;justify-content:center;
   font-size:11px;font-weight:600;cursor:pointer}
 .tooth:hover{box-shadow:var(--sh2)}
 .tooth.carie{background:var(--red-soft);border-color:var(--red);color:var(--red)}
 .tooth.obturatie{background:var(--blue-soft);border-color:var(--blue);color:var(--blue)}
 .tooth.coroana{background:var(--amber-soft);border-color:var(--amber);color:var(--amber)}
 .tooth.implant{background:var(--violet-soft);border-color:var(--violet);color:var(--violet)}
 .tooth.extras{background:var(--line2);border-color:var(--line);color:var(--text3);text-decoration:line-through}
 .tooth.tratament{background:var(--teal-soft);border-color:var(--teal);color:var(--teal-d)}
 .tleg{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--text2);margin-top:10px}
 .tleg i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:4px}
 .plan-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line2);font-size:12.5px}
 .plan-row:first-of-type{border-top:none}
 .plan-row .pt{width:32px;flex:0 0 32px;font-weight:600;color:var(--text2)}
 .plan-row .pp{flex:1;min-width:0;font-weight:500}
 .plan-row .pd{width:120px;flex:0 0 120px;color:var(--text2);font-size:12px}
 .plan-row .pm{width:90px;flex:0 0 90px;text-align:right;font-weight:600}
 .pbadge{font-size:10px;font-weight:600;letter-spacing:.05em;padding:3px 7px;border-radius:5px;text-transform:uppercase}
 .pbadge.planificat{border:1px solid var(--line);color:var(--text3)}
 .pbadge.in_lucru{background:var(--teal);color:#fff}
 .pbadge.finalizat{background:var(--line2);color:var(--text2)}
 .plan-row form{margin:0}
 .plan-row .pact button{background:none;border:1px solid var(--line);border-radius:6px;
   padding:2px 7px;cursor:pointer;font-size:11px;color:var(--text2);margin-left:3px}
 .plan-row .pact button:hover{border-color:var(--teal);color:var(--teal-d)}
 .ptotal{display:flex;justify-content:flex-end;gap:12px;padding-top:10px;border-top:1px solid var(--line);
   font-size:12.5px;color:var(--text3);align-items:baseline}
 .ptotal b{font-size:15px;color:var(--text)}
 .tline{display:flex;gap:10px;margin-bottom:10px}
 .tline .tdot{width:7px;flex:0 0 7px;display:flex;flex-direction:column;align-items:center}
 .tline .tdot i{width:7px;height:7px;border-radius:50%;background:var(--line);margin-top:4px}
 .tline.next .tdot i{background:var(--teal)}
 .tline .tb{min-width:0;font-size:12.5px}
 .tline .tb small{display:block;color:var(--text3);font-size:11px}
 .doc{display:flex;align-items:center;gap:9px;padding:7px 10px;border:1px solid var(--line);
   border-radius:9px;margin-bottom:6px;font-size:12px}
 .doc a{font-weight:500;color:var(--text);text-decoration:none;min-width:0;
   overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .doc a:hover{color:var(--teal-d)}
 .doc small{color:var(--text3);white-space:nowrap}
 .doc form{margin-left:auto}
 .doc form button{background:none;border:none;color:var(--text3);cursor:pointer}
 .doc form button:hover{color:var(--red)}
 .fform{display:flex;flex-direction:column;gap:7px}
 .fform input,.fform select,.fform textarea{padding:7px 10px;border:1px solid var(--line);
   border-radius:8px;font-size:12.5px;font-family:inherit;width:100%}
 .fform button{background:var(--teal);color:#fff;border:none;border-radius:8px;padding:8px;
   cursor:pointer;font-size:12.5px;font-weight:600}
 .fform .r2{display:flex;gap:7px}
 @media (max-width:1400px){.fisa{flex-wrap:wrap}.fcol-l,.fcol-r{width:100%;flex:1 1 100%}}
 /* ---------- недельный вид ---------- */
 .week{display:flex;gap:12px;align-items:flex-start}
 .wcol{flex:1;min-width:0;background:var(--panel);border-radius:14px;box-shadow:var(--sh);overflow:hidden}
 .wcol .wh{padding:10px 12px;border-bottom:1px solid var(--line)}
 .wcol .wh.tdy{background:var(--teal-soft)}
 .wcol .wh a{font-size:13px;font-weight:600;color:var(--text);text-decoration:none}
 .wcol .wh a:hover{color:var(--teal-d)}
 .wcol .wh small{display:block;font-size:11px;color:var(--text3);margin-top:1px}
 .wcol .wb{padding:8px;display:flex;flex-direction:column;gap:5px;min-height:60px}
 .wchip{border-radius:8px;padding:4px 8px;font-size:11.5px;line-height:1.4;overflow:hidden}
 .wchip b{font-weight:600}
 .wchip small{opacity:.75;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .wchip.noshow{text-decoration:line-through;opacity:.7}
 @media (max-width:1280px){.dash{flex-wrap:wrap}.rail{width:100%;flex:1 1 100%}}
 @media (max-width:1000px){
   .side{width:56px;flex:0 0 56px}
   .side .brand div,.side .sec,.side nav a span,.side nav a .dot,.side .sfoot{display:none}
   .side .brand{justify-content:center;padding:14px 0}
   .side nav a{justify-content:center;margin:2px 8px;padding:9px 0}
   .week{flex-wrap:wrap}.wcol{flex:1 1 45%}
 }
"""

REFRESH_JS = """
<script>
setInterval(function(){
  if(document.querySelector("dialog[open]"))return;
  var pe=document.getElementById("pedit");
  if(pe&&pe.style.display!=="none")return;            // открыта форма профиля
  var fi=document.querySelector("input[type=file]");
  if(fi&&fi.files&&fi.files.length)return;            // выбран файл — не терять
  var a=document.activeElement;
  if(a&&a.closest&&a.closest("form"))return;          // любой ввод в форме
  if(!a||(a.tagName!=="INPUT"&&a.tagName!=="SELECT"&&a.tagName!=="TEXTAREA"&&a.tagName!=="BUTTON"))location.reload();
},12000);
</script>
"""


def _update_banner() -> str:
    if upd.can_self_update():
        # в desktop-версии баннер ведёт к кнопке «Actualizează acum», не на GitHub
        return (f" · <a href='/admin/settings' "
                f"style='color:#e8710a;font-weight:600'>🔄 versiune nouă "
                f"{html.escape(upd.STATE['latest'])} — click pentru actualizare</a>")
    if upd.asset_pending() and upd.is_desktop():
        # релиз есть, файла в нём ещё нет — честно говорим и НЕ шлём на GitHub
        return (f" · <span style='color:var(--text3)'>🔄 {html.escape(upd.STATE['latest'])} "
                f"se pregătește…</span>")
    if upd.newer_available():
        return (f" · <a href='{html.escape(upd.STATE['url'])}' target='_blank' "
                f"style='color:#e8710a;font-weight:600'>🔄 versiune nouă "
                f"{html.escape(upd.STATE['latest'])}</a>")
    return ""


def _tg_state() -> tuple[bool, str]:
    """Статус Telegram-канала БЕЗ импорта адаптера: import aiogram занимает
    секунды, а это горячий путь (сайдбар на каждой странице). Модуль уже
    импортирован в startup(), если токен задан — берём из sys.modules."""
    mod = sys.modules.get(f"{__package__}.telegram")
    if mod is None:
        return False, ""
    st = mod.STATUS
    return bool(st["running"]), st.get("username", "")


_I = {  # компактные stroke-иконки сайдбара
    "home": "<path d='M3 10.5 12 3l9 7.5M5.5 9.5V21h13V9.5'/>",
    "cal": "<rect x='3.5' y='5' width='17' height='16' rx='2.5'/><path d='M3.5 10h17M8.5 3v4M15.5 3v4'/>",
    "pat": "<circle cx='12' cy='8' r='3.5'/><path d='M5 20.5c1.3-3.8 4-5.4 7-5.4s5.7 1.6 7 5.4'/>",
    "stat": "<path d='M4 20h16M8 20v-6M13 20V7M18 20v-9'/>",
    "set": "<circle cx='12' cy='12' r='3'/><path d='M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M18 6l-2 2M8 16l-2 2'/>",
    "bot": "<rect x='3.5' y='7.5' width='17' height='12' rx='3'/><path d='M12 7.5V4'/><circle cx='9' cy='13.5' r='1' fill='currentColor' stroke='none'/><circle cx='15' cy='13.5' r='1' fill='currentColor' stroke='none'/>",
    "qr": "<rect x='4' y='4' width='6.5' height='6.5' rx='1'/><rect x='13.5' y='4' width='6.5' height='6.5' rx='1'/><rect x='4' y='13.5' width='6.5' height='6.5' rx='1'/><path d='M13.5 13.5h6.5v6.5h-6.5z'/>",
}


def _ic(name: str) -> str:
    return (f"<svg width='16' height='16' viewBox='0 0 24 24' fill='none' "
            f"stroke='currentColor' stroke-width='1.8' stroke-linecap='round' "
            f"stroke-linejoin='round'>{_I[name]}</svg>")


def _sidebar(active: str) -> str:
    def item(key: str, href: str, icon: str, label: str, extra: str = "") -> str:
        on = " on" if key == active else ""
        return (f"<a class='{on.strip()}' href='{href}' title='{label}'>{_ic(icon)}"
                f"<span>{label}</span>{extra}</a>")

    tg_on, tg_user = _tg_state()
    tg_dot = "<span class='dot ok'></span>" if tg_on else "<span class='dot off'></span>"
    tg_title = f"@{tg_user}" if tg_on else "neconectat"
    return f"""<aside class="side">
  <div class="brand"><div class="logo">DP</div>
    <div><b>DentPilot</b><small title="{html.escape(eng.CLINIC_NAME)}">{html.escape(eng.CLINIC_NAME)}</small></div>
  </div>
  <nav>
    <div class="sec">Meniu</div>
    {item('dash', '/admin', 'home', 'Dashboard')}
    {item('prog', '/admin/all', 'cal', 'Programări')}
    {item('pat', '/admin/search', 'pat', 'Pacienți')}
    {item('stat', '/admin/stats', 'stat', 'Statistici')}
    {item('set', '/admin/settings', 'set', 'Setări')}
    <div class="sec">Sincronizări</div>
    {item('tg', '/admin/settings', 'bot', 'Telegram Bot', tg_dot)}
    {item('qr', '/admin/qr-print', 'qr', 'QR pacienți')}
  </nav>
  <div class="sfoot" title="Telegram: {html.escape(tg_title)}">v{eng.APP_VERSION} · <span id="sf_clock"></span></div>
</aside>"""


def _topbar(bell: int | None) -> str:
    bell_html = ""
    if bell is not None:
        badge = f"<span class='n'>{bell}</span>" if bell else ""
        # ведёт к блоку «Programări noi din bot» (по created_at) — а не к дневному
        # фильтру: бронь на неделю вперёд должна быть в одном клике (урок демо 07-31)
        bell_html = (f"<a class='bell' href='/admin#botnew' "
                     f"title='Programări noi din bot'>🔔{badge}</a>")
    today = datetime.now(eng.TZ).date().isoformat()
    return f"""<div class="top">
  <form class="searchf" method="get" action="/admin/search">
    <input id="topq" name="q" placeholder="Caută pacient, telefon…" autocomplete="off">
    <span class="kbd">Ctrl K</span><button>🔍</button>
  </form>
  <div style="flex:1"></div>
  <span style="font-size:12px;color:var(--text3)">{_update_banner().removeprefix(' · ')}</span>
  {bell_html}
  <a class="newbtn" href="/admin/all?date={today}#addform">＋ Programare nouă</a>
</div>"""


def _shell(body: str, sub: str, active: str = "dash", bell: int | None = None) -> str:
    fb_subject = urllib.parse.quote(
        f"Feedback DentPilot — {eng.CLINIC_NAME} (v{eng.APP_VERSION})")
    fb_body = urllib.parse.quote("Ideea / problema mea:\n\n")
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(eng.CLINIC_NAME)} — registru</title><style>{PANEL_CSS}</style></head><body>
{_sidebar(active)}
<div class="main">
{_topbar(bell)}
<div class="content">
<h1><a href="/admin">{html.escape(eng.CLINIC_NAME)} — registrul clinicii</a></h1>
<div class="sub">{sub}{_sec_warn()} · v{eng.APP_VERSION}</div>
{body}
</div></div>
<div class="brandcorner">🦷 <b>DentPilot</b> ·
<a href="mailto:{FEEDBACK_EMAIL}?subject={fb_subject}&body={fb_body}"
   title="{FEEDBACK_EMAIL}">💬 Feedback</a></div>
<script>
document.addEventListener('keydown',function(e){{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){{
    e.preventDefault();var q=document.getElementById('topq');if(q)q.focus();}}
}});
var sfc=document.getElementById('sf_clock');
if(sfc){{var t=new Date();sfc.textContent=('0'+t.getHours()).slice(-2)+':'+('0'+t.getMinutes()).slice(-2);}}
</script>
{REFRESH_JS}</body></html>"""


def _age(birth_year) -> int | None:
    if not birth_year:
        return None
    return datetime.now(eng.TZ).year - int(birth_year)


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


def _banner(msg: str, d: date) -> str:
    out = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        out += f"<div class='banner {cls}'>{text}</div>"
    if not eng.hours_for(d):
        out += "<div class='banner err'>Zi liberă — clinica este închisă (bot-ul nu oferă această zi)</div>"
    return out


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
    for h in hours:
        out.append(f"<tr><td class='hour'>{h:02d}:00</td>")
        for dk, dname in doctors_items:
            r = active.get((dname, h))
            if r and r["source"] == "note":
                out.append(f"<td><div class='appt note'>📝 {html.escape(r['service'])}</div></td>")
            elif r:
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
                out.append(
                    f"<td><div class='appt {cls}'{click}><b>{html.escape(r['name'] or '—')}</b>{age_txt} {src}"
                    f"<br>{svc_txt}<br><small>{html.escape(r['phone'] or '')}</small>{cmt}</div></td>"
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
        items = ["<tr><td colspan='9' style='color:#999'>— nicio programare —</td></tr>"]
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
        style="padding:8px 10px;border:1px solid #ccd4d4;border-radius:6px;font-size:14px;font-family:inherit;resize:vertical"></textarea>
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


def _active_map(rows: list) -> dict:
    out = {}
    for r in rows:
        if r["status"] != "cancelled":
            out[(r["doctor"], r["starts_at"].astimezone(eng.TZ).hour)] = r
    return out


@app.on_event("startup")
async def startup() -> None:
    if not db.IS_SQLITE and not ADMIN_KEY:
        # Postgres = серверный режим: с v1.6.0 в журнале мед-данные и файлы,
        # fail-open без ключа недопустим — падаем громко, а не открываемся тихо
        raise RuntimeError("ADMIN_KEY is required for the Postgres edition — set it in .env")
    await db.init(eng.build_seed_rows())
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


SETUP_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — PIN</title><style>
 body{font-family:system-ui,'Segoe UI',sans-serif;background:#075e54;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0}
 form{background:#fff;padding:28px 32px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.25);
      display:flex;flex-direction:column;gap:12px;width:340px}
 h1{font-size:17px;color:#075e54;margin:0}
 p{color:#667;font-size:13px;margin:0}
 input{padding:10px;border:1px solid #ccd4d4;border-radius:8px;font-size:26px;
       text-align:center;letter-spacing:12px}
 button{background:#075e54;color:#fff;border:none;border-radius:8px;padding:12px;
        font-size:15px;cursor:pointer}
 .err{color:#c62828;font-size:13px}
</style></head><body>
<form method="post" action="/admin/setup">
  <h1>🦷 __CLINIC__</h1>
  <p>Prima pornire: setați un PIN pentru registrul clinicii (4–6 cifre).</p>
  __ERR__
  <input type="password" name="pin1" placeholder="PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="6" autofocus required>
  <input type="password" name="pin2" placeholder="repetați PIN" inputmode="numeric"
         pattern="[0-9]*" maxlength="6" required>
  <button>Setează PIN</button>
</form></body></html>"""


def _setup_allowed() -> bool:
    return db.IS_SQLITE and _pin_rec() is None and not ADMIN_KEY


@app.get("/admin/setup", response_class=HTMLResponse)
async def admin_setup_page(err: str = ""):
    if not _setup_allowed():
        return RedirectResponse("/admin", status_code=303)
    err_html = "<div class='err'>PIN-urile nu coincid sau nu au 4–6 cifre</div>" if err else ""
    return (SETUP_TMPL.replace("__CLINIC__", html.escape(eng.CLINIC_NAME))
            .replace("__ERR__", err_html))


def _write_pin(pin: str) -> None:
    salt = secrets.token_hex(8)
    _auth_path().write_text(
        json.dumps({"salt": salt, "hash": _pin_hash(pin, salt)}),
        encoding="utf-8",
    )


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
_DOC_HUES = ["#0D9488", "#3B82F6", "#8B5CF6", "#D97706", "#DC2626", "#059669",
             "#6366F1", "#DB2777"]

_SVC_CAT = [
    (re.compile(r"urgent|sos|durere|acut", re.I), ("var(--red-soft)", "var(--red)")),
    (re.compile(r"implant|extract|chirur|sinus", re.I), ("var(--blue-soft)", "var(--blue)")),
    (re.compile(r"hyg|igien|airflow|detartraj|fluor", re.I), ("var(--amber-soft)", "var(--amber)")),
    (re.compile(r"whiten|albire|estet|fatet|venir", re.I), ("var(--violet-soft)", "var(--violet)")),
]


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[\s.]+", name) if w and w.lower() not in ("dr", "dr.")]
    return "".join(w[0].upper() for w in words[:2]) or "?"


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
    """(фон, полоса) записи: статус важнее типа; тип — цвет из конфига услуги,
    а если он не задан — прежняя эвристика по названию."""
    if r["status"] == "noshow":
        return "var(--red-soft)", "var(--red)"
    label = r["service"]
    if label in eng.URGENT_LABELS:
        return "var(--red-soft)", "var(--red)"
    for sid, v in eng.SERVICES.items():
        if v.get("ro") == label or v.get("ru") == label:
            color = eng.SERVICE_COLOR.get(sid)
            if color in SVC_PALETTE:
                return SVC_PALETTE[color]
            key = sid + " " + label
            break
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
    row_hours = {r["starts_at"].astimezone(eng.TZ).hour for r in live}
    hours = sorted(set(sched) | row_hours)
    if not hours:
        return "<div class='gridcard' style='padding:28px;text-align:center;color:var(--text3)'>Zi liberă — clinica este închisă</div>"
    idx = {h: i for i, h in enumerate(hours)}
    active: dict = {}
    for r in live:
        key = (r["doctor"], r["starts_at"].astimezone(eng.TZ).hour)
        active.setdefault(key, []).append(r)

    def _blocks(name: str) -> str:
        out = []
        for (doc, h), rs in active.items():
            if doc != name or h not in idx:
                continue
            n = len(rs)
            # коллизия (done/noshow + новая бронь на тот же час) — делим ширину,
            # confirmed рисуем последним (поверх/правее), ничего не теряем
            for j, r in enumerate(sorted(rs, key=lambda x: x["status"] in LIVE_STATUSES)):
                pos = (f"top:calc({idx[h]}*var(--cell) + 3px);"
                       f"height:calc(var(--cell) - 8px);"
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
                out.append(
                    f"<div class='gappt{ns}' style='{pos};"
                    f"background:{bg};border-left:3px solid {bar}'{click}>"
                    f"<span class='stt'>{ico}</span>"
                    f"<b>{html.escape(r['name'] or '—')} {src}</b>"
                    f"<small>{h:02d}:00 · {html.escape(r['service'])}</small></div>")
        return "".join(out)

    def _cells(dk: str | None, name: str) -> str:
        out = []
        for h in hours:
            if dk is not None and h in sched:
                # json+escape: имя врача с апострофом не ломает JS-обработчик
                args = html.escape(json.dumps([dk, name, f"{h:02d}:00"]), quote=True)
                out.append(f"<div class='gcell' onclick=\"openSlot.apply(null,{args})\"></div>")
            else:
                out.append("<div class='gcell off'></div>")
        return "".join(out)

    head = ["<div class='gridhead'><div class='gh-time'></div>"]
    cols = []
    for i, (dk, name) in enumerate(eng.DOCTORS.items()):
        hue = eng.DOCTOR_META.get(dk, {}).get("color") or _DOC_HUES[i % len(_DOC_HUES)]
        mine = [r for r in live if r["doctor"] == name and r["source"] != "note"]
        free_h = next((h for h in sched if (name, h) not in active), None)
        dot = "var(--green)" if free_h is not None else "var(--text3)"
        liber = f"liber {free_h:02d}:00" if free_h is not None else "complet"
        meta = eng.DOCTOR_META.get(dk, {})
        extra = " · ".join(x for x in [meta.get("room", ""), meta.get("phone", "")] if x)
        off = "" if meta.get("active", True) else " · inactiv"
        head.append(
            f"<div class='gh-doc'><span class='av' style='background:{hue}'>{_initials(name)}</span>"
            f"<div class='nm'><a href='/admin/doctor/{dk}?date={d.isoformat()}' "
            f"title='{html.escape(extra)}'>{html.escape(name)}</a>"
            f"<small>{html.escape(eng.DOCTOR_SPEC.get(dk, ''))}{off} · {len(mine)} prog. · {liber}</small></div>"
            f"<span class='st' style='background:{dot}' title='{liber}'></span></div>")
        cols.append(f"<div class='gcol'>{_cells(dk, name)}{_blocks(name)}</div>")

    # «осиротевшие» имена (врача переименовали в Setări) — записи остаются видимыми
    orphans = sorted({doc for (doc, _h) in active} - set(eng.DOCTORS.values()))
    for name in orphans:
        mine = [r for r in live if r["doctor"] == name and r["source"] != "note"]
        head.append(
            f"<div class='gh-doc'><span class='av' style='background:#94A3B8'>{_initials(name)}</span>"
            f"<div class='nm'><a>{html.escape(name)}</a>"
            f"<small>în afara listei · {len(mine)} prog.</small></div></div>")
        cols.append(f"<div class='gcol'>{_cells(None, name)}{_blocks(name)}</div>")
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
    return (f"<div class='gridcard'>{''.join(head)}"
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
        dk = rev.get(r["doctor"])
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


def _hour_opts(sel: int, lo: int, hi: int) -> str:
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
        for x in range(6, 22):
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
            f"<td><select id='hf_{day}'>{_hour_opts(f, 0, 23)}</select></td>"
            f"<td><select id='ht_{day}'>{_hour_opts(t, 1, 24)}</select></td>"
            f"<td><select id='hb_{day}'>{_break_opts(bf)}</select></td>"
            f"<td><select id='he_{day}'>{_break_opts(bt)}</select></td></tr>"
        )

    def _color_opts(sel: str) -> str:
        out = [f"<option value=''{' selected' if not sel else ''}>auto</option>"]
        for k, ro in _PALETTE_RO.items():
            out.append(f"<option value='{k}'{' selected' if sel == k else ''}>{ro}</option>")
        return "".join(out)

    # ⚠️ Врача НЕ удаляем — гасим галочкой «activ». Иначе его id уходит в
    # переиспользование и история достаётся новому врачу (баг найден 08-01).
    doc_rows = "".join(
        f"<tr><td><input type='hidden' class='d_id' value='{e(d['id'])}'>"
        f"<input type='text' class='d_name' value='{e(d['name'])}'></td>"
        f"<td><input type='text' class='d_spec' value='{e(d.get('spec', ''))}'></td>"
        f"<td><input type='text' class='d_room' value='{e(d.get('room', ''))}' "
        f"placeholder='Cab. 1' style='width:90px'></td>"
        f"<td><input type='text' class='d_phone' value='{e(d.get('phone', ''))}' "
        f"placeholder='intern' style='width:120px'></td>"
        f"<td><input type='color' class='d_color' value='{e(d.get('color') or '#0D9488')}' "
        f"style='width:44px;padding:2px;height:30px'></td>"
        f"<td style='text-align:center'><input type='checkbox' class='d_active'"
        f"{' checked' if d.get('active', True) else ''}></td></tr>"
        for d in cfg["doctors"]
    )
    svc_rows = "".join(
        f"<tr><td><input type='hidden' class='s_id' value='{e(s['id'])}'>"
        f"<input type='text' class='s_ro' value='{e(s['ro'])}'></td>"
        f"<td><input type='text' class='s_ru' value='{e(s['ru'])}'></td>"
        f"<td><input type='text' class='s_price' value='{e(str(s.get('price', '')) if not isinstance(s.get('price'), dict) else s['price'].get('ro', ''))}'></td>"
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
<table class='set' id='docs_t'>
<tr><th>Nume</th><th>Specializare</th><th style='width:90px'>Cabinet</th>
<th style='width:120px'>Telefon</th><th style='width:60px'>Culoare</th>
<th style='width:60px'>Activ</th></tr>
<tbody id='docs_tb'>{doc_rows}</tbody>
</table>
<button type='button' class='addrow' onclick='addDoc()'>+ Adaugă medic</button>
<p class='hint'>Medicul care pleacă se <b>dezactivează</b> (bifa «Activ»), nu se șterge:
programările lui rămân în istoric, iar botul și formularele nu îl mai propun.
Culoarea se vede în grila zilei. Redenumirea nu modifică programările din trecut
(rămân pe numele vechi).</p>

<h2>🦷 Servicii</h2>
<table class='set' id='svc_t'>
<tr><th>Denumire (RO)</th><th>Denumire (RU)</th><th style='width:140px'>Preț</th>
<th style='width:110px'>Culoare</th>
<th style='width:40px'>🆘</th><th style='width:150px'>Medici (id)</th><th></th></tr>
<tbody id='svc_tb'>{svc_rows}</tbody>
</table>
<button type='button' class='addrow' onclick='addSvc()'>+ Adaugă serviciu</button>
<p class='hint'>Coloana «Medici»: id-uri separate prin spațiu ({doc_ids_hint}); gol = toți medicii.
🆘 = flux urgent (fără alegerea medicului, sloturi din ziua curentă).</p>

<button class='savebtn'>💾 Salvează setările</button>
</form>

<script>
function addDoc() {{
  const tb = document.getElementById('docs_tb');
  const tr = document.createElement('tr');
  tr.innerHTML = "<td><input type='hidden' class='d_id' value=''>" +
    "<input type='text' class='d_name' placeholder='Dr. ...'></td>" +
    "<td><input type='text' class='d_spec' placeholder='Terapie'></td>" +
    "<td><input type='text' class='d_room' placeholder='Cab. 1' style='width:90px'></td>" +
    "<td><input type='text' class='d_phone' placeholder='intern' style='width:120px'></td>" +
    "<td><input type='color' class='d_color' value='#0D9488' style='width:44px;padding:2px;height:30px'></td>" +
    "<td style='text-align:center'><input type='checkbox' class='d_active' checked></td>";
  tb.appendChild(tr);
}}
const SVC_COLORS = {json.dumps(_PALETTE_RO)};
function addSvc() {{
  const tb = document.getElementById('svc_tb');
  const tr = document.createElement('tr');
  let opts = "<option value=''>auto</option>";
  for (const k in SVC_COLORS) opts += "<option value='" + k + "'>" + SVC_COLORS[k] + "</option>";
  tr.innerHTML = "<td><input type='hidden' class='s_id' value=''>" +
    "<input type='text' class='s_ro' placeholder='Serviciu'></td>" +
    "<td><input type='text' class='s_ru' placeholder='Услуга'></td>" +
    "<td><input type='text' class='s_price' placeholder='500 MDL'></td>" +
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
  const doctors = [];
  document.querySelectorAll('#docs_tb tr').forEach(tr => {{
    doctors.push({{ id: tr.querySelector('.d_id').value,
                   name: tr.querySelector('.d_name').value,
                   spec: tr.querySelector('.d_spec').value,
                   room: tr.querySelector('.d_room').value,
                   phone: tr.querySelector('.d_phone').value,
                   color: tr.querySelector('.d_color').value,
                   active: tr.querySelector('.d_active').checked }});
  }});
  const services = [];
  document.querySelectorAll('#svc_tb tr').forEach(tr => {{
    services.push({{ id: tr.querySelector('.s_id').value,
                    ro: tr.querySelector('.s_ro').value,
                    ru: tr.querySelector('.s_ru').value,
                    price: tr.querySelector('.s_price').value,
                    color: tr.querySelector('.s_color').value,
                    urgent: tr.querySelector('.s_urg').checked,
                    docs: tr.querySelector('.s_docs').value }});
  }});
  // валидация ДО отправки: при серверной ошибке форма перерисуется из
  // сохранённого конфига и все правки админа пропадут — не доводим до этого
  if (!doctors.some(d => d.active && d.name.trim())) {{
    alert('Trebuie să existe cel puțin un medic activ.');
    return false;
  }}
  const seen = {{}};
  for (const d of doctors) {{
    const key = d.name.trim().toLowerCase();
    if (!key) continue;
    if (seen[key]) {{
      alert('Două rânduri au același nume de medic: «' + d.name.trim() +
            '». Redenumiți unul dintre ele.');
      return false;
    }}
    seen[key] = true;
  }}
  const payload = {{
    name: document.getElementById('cname').value,
    phone: document.getElementById('cphone').value,
    address: {{ ro: document.getElementById('caddr_ro').value,
               ru: document.getElementById('caddr_ru').value }},
    hours: hours, doctors: doctors, services: services
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

    doctors = []
    used: set[str] = set()
    for d in data.get("doctors", []):
        dn = str(d.get("name", "")).strip()[:60]
        if not dn:
            continue
        did = str(d.get("id", "")).strip()
        if not re.fullmatch(r"d\d+", did) or did in used:
            seq_d += 1
            did = f"d{seq_d}"
        used.add(did)
        entry_d: dict = {"id": did, "name": dn,
                         "spec": str(d.get("spec", "")).strip()[:60],
                         "active": bool(d.get("active", True))}
        room = str(d.get("room", "")).strip()[:30]
        phone_d = str(d.get("phone", "")).strip()[:30]
        color_d = str(d.get("color", "")).strip()[:16]
        if room:
            entry_d["room"] = room
        if phone_d:
            entry_d["phone"] = phone_d
        if re.fullmatch(r"#[0-9a-fA-F]{6}", color_d):
            entry_d["color"] = color_d
        doctors.append(entry_d)
    if not doctors:
        raise ValueError("doctors")
    if not any(d["active"] for d in doctors):
        raise ValueError("no active doctor")
    # записи связаны с врачом по ИМЕНИ — два одинаковых имени слили бы их истории
    names_seen = set()
    for d in doctors:
        key = d["name"].casefold()
        if key in names_seen:
            raise ValueError("duplicate doctor name")
        names_seen.add(key)
    doc_ids = {d["id"] for d in doctors}

    services = []
    sused: set[str] = set()
    for s in data.get("services", []):
        ro = str(s.get("ro", "")).strip()[:60]
        ru = str(s.get("ru", "")).strip()[:60] or ro
        if not ro:
            continue
        sid = str(s.get("id", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]{1,20}", sid) or sid in sused:
            seq_s += 1
            sid = f"s{seq_s}"
        sused.add(sid)
        entry: dict = {"id": sid, "ro": ro, "ru": ru}
        price = str(s.get("price", "")).strip()[:60]
        if price:
            entry["price"] = price
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
      justify-content:center;height:100vh;margin:0;background:#075e54;color:#fff;text-align:center}}
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
        if ln.strip().startswith("TELEGRAM_TOKEN="):
            out.append(f"TELEGRAM_TOKEN={tok}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"TELEGRAM_TOKEN={tok}")
    p.write_text("\r\n".join(out) + "\r\n", encoding="utf-8")
    os.environ["TELEGRAM_TOKEN"] = tok
    if upd.restart_app() is not None:
        # dev-режим/тест-хук: перезапуск не случился — просто баннер
        return RedirectResponse("/admin/settings?msg=ok_tok", status_code=303)
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15;url=/admin/settings">
<title>Repornire…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:#075e54;color:#fff;text-align:center}}
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
    loss = sum(eng.SERVICE_PRICE.get(r["service"], 0) for r in act if r["status"] == "noshow")
    bot_value = sum(eng.SERVICE_PRICE.get(r["service"], 0) for r in act if r["source"] == "bot")

    tiles = (
        "<div class='tiles'>"
        f"<div class='tile'><b>{len(act)}</b><span>programări</span></div>"
        f"<div class='tile'><b>{n_bot}</b><span>🤖 prin bot</span></div>"
        f"<div class='tile'><b>{n_man}</b><span>✍️ recepție</span></div>"
        f"<div class='tile'><b>{n_done}</b><span>🟦 au venit</span></div>"
        f"<div class='tile bad'><b>{n_noshow}</b><span>neprezentări<br>≈ {_fmt_mdl(loss)}</span></div>"
        f"<div class='tile'><b>{n_cancel}</b><span>anulate</span></div>"
        f"<div class='tile'><b>{n_rem}</b><span>🔔 remindere</span></div>"
        f"<div class='tile'><b>≈ {_fmt_mdl(bot_value)}</b><span>valoare adusă de bot</span></div>"
        "</div>"
    )

    # загрузка врачей: занято / ёмкость периода
    days = [d1 + timedelta(days=i) for i in range((d2 - d1).days + 1)]
    capacity = sum(len(eng.day_slots(day)) for day in days)
    doc_rows = []
    for name in eng.DOCTORS.values():
        mine = [r for r in act if r["doctor"] == name]
        ns = sum(1 for r in mine if r["status"] == "noshow")
        pct = round(100 * len(mine) / capacity) if capacity else 0
        doc_rows.append(
            f"<tr><td>{html.escape(name)}</td><td>{len(mine)}</td><td>{ns}</td>"
            f"<td style='min-width:160px'>{pct}%<div class='statbar'><div style='width:{min(pct,100)}%'></div></div></td></tr>"
        )
    doctors_tbl = ("<h2>Medici</h2><table class='list'>"
                   "<tr><th>Medic</th><th>Programări</th><th>Neprezentări</th><th>Ocupare</th></tr>"
                   + "".join(doc_rows) + "</table>")

    svc_count: dict[str, int] = {}
    for r in act:
        svc_count[r["service"]] = svc_count.get(r["service"], 0) + 1
    svc_rows = "".join(
        f"<tr><td>{html.escape(sname)}</td><td>{cnt}</td>"
        f"<td>≈ {_fmt_mdl(cnt * eng.SERVICE_PRICE.get(sname, 0))}</td></tr>"
        for sname, cnt in sorted(svc_count.items(), key=lambda x: -x[1])[:8]
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
        f"<button class='searchf' style='background:#075e54;color:#fff;border:none;border-radius:6px;padding:5px 10px;cursor:pointer'>OK</button></form>"
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


# ---------- карточка пациента (v1.6.0) ----------

TOOTH_STATES = {
    "ok": "Sănătos", "carie": "Carie", "obturatie": "Obturație",
    "coroana": "Coroană", "implant": "Implant", "extras": "Extras",
    "tratament": "În tratament",
}
_FDI_UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
_FDI_LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
_ALERT_KINDS = {"allergy": "⚠️ Alergie", "medication": "💊 Medicație",
                "warning": "⏰ Atenție", "info": "ℹ️ Info"}
DOC_CATEGORIES = {"radiografie": "🩻 Radiografie", "acord": "📝 Acord / contract",
                  "trimitere": "📨 Trimitere", "alt": "📄 Alt document"}
_PLAN_NEXT = {"planificat": "in_lucru", "in_lucru": "finalizat", "finalizat": "planificat"}
_PLAN_LABEL = {"planificat": "Planificat", "in_lucru": "În lucru", "finalizat": "Finalizat"}
MAX_DOC_MB = 25


def _files_dir(pid: int) -> pathlib.Path:
    base = _data_dir() or pathlib.Path("data")
    d = base / "files" / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _p_age(p: dict) -> int | None:
    if p.get("birth_date"):
        try:
            bd = date.fromisoformat(p["birth_date"])
            t = datetime.now(eng.TZ).date()
            return t.year - bd.year - ((t.month, t.day) < (bd.month, bd.day))
        except ValueError:
            pass
    return _age(p.get("birth_year"))


@app.get("/admin/patient/{pid}", response_class=HTMLResponse)
async def admin_patient(request: Request, pid: int, msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    e = html.escape
    alerts = await db.patient_alerts(pid)
    tmap = await db.teeth_map(pid)
    plan = await db.plan_items(pid)
    docs = await db.documents(pid)
    visits = await db.patient_appointments(pid)
    now = datetime.now(eng.TZ)
    base = f"/admin/patient/{pid}"

    banner = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        banner = f"<div class='banner {cls}'>{text}</div>"

    # -- левая колонка: профиль --
    age = _p_age(p)
    chan = ("📱 Telegram" if (p["session_key"] or "").startswith("tg:")
            else "✍️ recepție" if (p["session_key"] or "").startswith("manual:")
            else "🌐 web")
    meta = " · ".join(x for x in [f"{age} ani" if age else "", chan,
                                  f"dosar {e(p['file_no'])}" if p.get("file_no") else "",
                                  "🗄 arhivat" if p.get("archived") else ""] if x)

    def frow(label: str, val) -> str:
        return (f"<div class='frow'><span>{label}</span>"
                f"<span>{e(str(val)) if val else '—'}</span></div>")

    info_rows = (frow("Telefon", p.get("phone"))
                 + frow("Data nașterii", p.get("birth_date") or p.get("birth_year"))
                 + frow("Gen", {"m": "M", "f": "F"}.get(p.get("gender") or "", p.get("gender")))
                 + frow("IDNP", p.get("idnp")) + frow("E-mail", p.get("email"))
                 + frow("Adresă", p.get("address")) + frow("Asigurare", p.get("insurance"))
                 + frow("Medic curant", p.get("primary_doctor"))
                 + frow("Pacient din", p["created_at"].astimezone(eng.TZ).strftime("%d.%m.%Y")))
    notes_html = (f"<div style='font-size:12px;color:var(--text2);background:var(--bg);"
                  f"border-radius:8px;padding:8px 10px;margin-top:8px'>📝 {e(p['notes'])}</div>"
                  if p.get("notes") else "")

    doc_opts = "".join(f"<option value='{e(n)}'"
                       f"{' selected' if p.get('primary_doctor') == n else ''}>{e(n)}</option>"
                       for n in eng.DOCTORS.values())
    edit_form = f"""
<form class='fform' id='pedit' method='post' action='{base}/save' style='display:none;margin-top:10px'>
  <input name='name' value="{e(p['name'] or '')}" placeholder='Nume' required>
  <input name='phone' value="{e(p['phone'] or '')}" placeholder='Telefon'>
  <div class='r2'><input type='date' name='birth_date' value="{e(p.get('birth_date') or '')}">
  <select name='gender'><option value=''>Gen —</option>
    <option value='m'{" selected" if p.get('gender') == 'm' else ''}>M</option>
    <option value='f'{" selected" if p.get('gender') == 'f' else ''}>F</option></select></div>
  <input name='idnp' value="{e(p.get('idnp') or '')}" placeholder='IDNP (opțional)' maxlength='13'>
  <input name='email' value="{e(p.get('email') or '')}" placeholder='E-mail'>
  <input name='address' value="{e(p.get('address') or '')}" placeholder='Adresă'>
  <input name='insurance' value="{e(p.get('insurance') or '')}" placeholder='Asigurare (ex. CNAM activă)'>
  <div class='r2'><select name='primary_doctor'><option value=''>Medic curant —</option>{doc_opts}</select>
  <input name='file_no' value="{e(p.get('file_no') or '')}" placeholder='Nr. dosar'></div>
  <textarea name='notes' rows='2' placeholder='Notițe interne'>{e(p.get('notes') or '')}</textarea>
  <button>💾 Salvează profilul</button>
</form>"""

    alerts_html = "".join(
        f"<div class='alert {e(a['kind'])}'>{_ALERT_KINDS.get(a['kind'], 'ℹ️')} {e(a['text'])}"
        f"<form method='post' action='{base}/alert/{a['id']}/del'>"
        f"<button title='Șterge'>✕</button></form></div>"
        for a in alerts) or "<p class='hint' style='margin:0'>— fără atenționări —</p>"
    kind_opts = "".join(f"<option value='{k}'>{v}</option>" for k, v in _ALERT_KINDS.items())
    alerts_card = f"""<div class='fcard'><h3>Atenționări medicale</h3>{alerts_html}
<form class='fform' method='post' action='{base}/alert' style='margin-top:9px'>
  <div class='r2'><select name='kind' style='width:130px'>{kind_opts}</select>
  <input name='text' placeholder='ex. Alergie: Penicilină' maxlength='120' required></div>
  <button>+ Adaugă</button></form></div>"""

    # -- центр: формула FDI + план --
    def tooth_div(n: int) -> str:
        t = tmap.get(n)
        st = t["state"] if t else "ok"
        note = t["note"] if t else ""
        title = f"{n} · {TOOTH_STATES.get(st, st)}" + (f" · {note}" if note else "")
        return (f"<div class='tooth {e(st)}' title=\"{e(title)}\" "
                f"onclick='openTooth({n})'>{n}</div>")

    upper = "".join(tooth_div(n) for n in _FDI_UPPER)
    lower = "".join(tooth_div(n) for n in _FDI_LOWER)
    legend = "".join(
        f"<span><i class='tooth {k}' style='width:9px;height:9px;padding:0;border-radius:3px;display:inline-block'></i> {v}</span>"
        for k, v in TOOTH_STATES.items() if k != "ok")
    # .replace("</", ...) — чтобы note вида "</script>..." не вырвался из тега
    teeth_json = json.dumps({str(n): {"state": (tmap[n]["state"] if n in tmap else "ok"),
                                      "note": (tmap[n]["note"] if n in tmap else "")}
                             for n in _FDI_UPPER + _FDI_LOWER}).replace("</", "<\\/")
    state_opts = "".join(f"<option value='{k}'>{v}</option>" for k, v in TOOTH_STATES.items())
    teeth_card = f"""<div class='fcard'>
<h3>Formula dentară <small>· notație FDI · click pe dinte</small></h3>
<div class='teeth'>{upper}</div>
<div style='height:1px;background:var(--line);margin:8px 30px'></div>
<div class='teeth'>{lower}</div>
<div class='tleg'>{legend}</div></div>
<dialog id='toothdlg'>
  <div class='dlg-head'><span id='t_title'>Dinte</span>
    <button type='button' onclick="document.getElementById('toothdlg').close()">✕</button></div>
  <form class='dlg-form' method='post' action='{base}/tooth'>
    <input type='hidden' name='tooth' id='t_num'>
    <select name='state' id='t_state'>{state_opts}</select>
    <input name='note' id='t_note' placeholder='Notiță (opțional)' maxlength='120'>
    <button>💾 Salvează</button>
  </form>
</dialog>
<script>
const TEETH = {teeth_json};
function openTooth(n) {{
  const t = TEETH[String(n)] || {{state: 'ok', note: ''}};
  document.getElementById('t_title').textContent = 'Dinte ' + n;
  document.getElementById('t_num').value = n;
  document.getElementById('t_state').value = t.state;
  document.getElementById('t_note').value = t.note;
  document.getElementById('toothdlg').showModal();
}}
</script>"""

    plan_rows = []
    total = 0
    for it in plan:
        if it["price_mdl"] and it["status"] != "finalizat":
            total += it["price_mdl"]
        nxt = _PLAN_NEXT[it["status"] if it["status"] in _PLAN_NEXT else "planificat"]
        plan_rows.append(
            f"<div class='plan-row'><span class='pt'>{it['tooth'] or '—'}</span>"
            f"<span class='pp'>{e(it['procedure'])}</span>"
            f"<span class='pd'>{e(it['doctor'] or '—')}</span>"
            f"<span class='pbadge {e(it['status'])}'>{_PLAN_LABEL.get(it['status'], it['status'])}</span>"
            f"<span class='pm'>{f'{it['price_mdl']:,}'.replace(',', ' ') + ' MDL' if it['price_mdl'] else '—'}</span>"
            f"<span class='pact'>"
            f"<form style='display:inline' method='post' action='{base}/plan/{it['id']}/status'>"
            f"<input type='hidden' name='to' value='{nxt}'>"
            f"<button title='Următorul status'>→ {_PLAN_LABEL[nxt]}</button></form>"
            f"<form style='display:inline' method='post' action='{base}/plan/{it['id']}/del' "
            f"onsubmit=\"return confirm('Ștergeți poziția din plan?')\">"
            f"<button title='Șterge'>✕</button></form></span></div>")
    plan_html = "".join(plan_rows) or "<p class='hint' style='margin:6px 0'>— plan gol —</p>"
    tooth_opts = "<option value=''>—</option>" + "".join(
        f"<option value='{n}'>{n}</option>" for n in _FDI_UPPER + _FDI_LOWER)
    plan_card = f"""<div class='fcard'>
<h3>Plan de tratament <small>· plan activ (nefinalizat): {f'{total:,}'.replace(',', ' ')} MDL</small></h3>
{plan_html}
<div class='ptotal'><span>Total plan activ</span><b>{f'{total:,}'.replace(',', ' ')} MDL</b></div>
<form class='fform' method='post' action='{base}/plan' style='margin-top:10px'>
  <div class='r2'><select name='tooth' style='width:90px'>{tooth_opts}</select>
  <input name='procedure' placeholder='Procedură (ex. Coroană zirconiu)' maxlength='120' required></div>
  <div class='r2'><select name='doctor'><option value=''>Medic —</option>{doc_opts}</select>
  <input name='price' type='number' min='0' max='1000000' placeholder='Preț MDL' style='width:130px'></div>
  <button>+ Adaugă în plan</button>
</form></div>"""

    # -- правая колонка: визиты + документы --
    future = [v for v in visits if v["status"] in LIVE_STATUSES and v["starts_at"] > now]
    nextv = min(future, key=lambda v: v["starts_at"]) if future else None
    next_html = ""
    if nextv:
        dtv = nextv["starts_at"].astimezone(eng.TZ)
        next_html = (f"<div class='fcard' style='background:var(--teal-soft)'>"
                     f"<h3 style='color:var(--teal-d)'>Următoarea vizită</h3>"
                     f"<div style='font-size:13.5px;font-weight:600'>{dtv.strftime('%d.%m.%Y · %H:%M')}</div>"
                     f"<div style='font-size:12px;color:var(--text2);margin-top:3px'>"
                     f"{e(nextv['service'])} · {e(nextv['doctor'])}</div></div>")
    hist = []
    for v in visits[:8]:
        dtv = v["starts_at"].astimezone(eng.TZ)
        is_next = nextv is not None and v["id"] == nextv["id"]
        hist.append(
            f"<div class='tline{' next' if is_next else ''}'>"
            f"<div class='tdot'><i></i></div><div class='tb'>"
            f"<small>{dtv.strftime('%d.%m.%Y %H:%M')} · {STATUS_LABEL.get(v['status'], v['status'])}</small>"
            f"<b style='font-size:12.5px'>{e(v['service'])}</b>"
            f"<small>{e(v['doctor'])}</small></div></div>")
    hist_card = (f"<div class='fcard'><h3>Istoric vizite <small>· ultimele {len(visits[:8])}</small></h3>"
                 + ("".join(hist) or "<p class='hint' style='margin:0'>— încă fără vizite —</p>")
                 + f"<a href='/admin/search?q={urllib.parse.quote(p['name'] or '')}' "
                 f"style='font-size:12px'>Vezi tot istoricul →</a></div>")

    docs_rows = "".join(
        f"<div class='doc'>{DOC_CATEGORIES.get(dd['category'], '📄')} "
        f"<a href='/admin/doc/{dd['id']}' title='{e(dd['filename'])}'>{e(dd['filename'])}</a>"
        f"<small>{dd['size'] // 1024} KB</small>"
        f"<form method='post' action='{base}/doc/{dd['id']}/del' "
        f"onsubmit=\"return confirm('Ștergeți documentul?')\"><button>✕</button></form></div>"
        for dd in docs) or "<p class='hint' style='margin:0 0 8px'>— fără documente —</p>"
    cat_opts = "".join(
        f"<option value='{k}'{' selected' if k == 'alt' else ''}>{v}</option>"
        for k, v in DOC_CATEGORIES.items())
    docs_card = f"""<div class='fcard'><h3>Documente și imagini <small>· max {MAX_DOC_MB} MB</small></h3>
{docs_rows}
<form class='fform' method='post' action='{base}/doc' enctype='multipart/form-data'>
  <select name='category'>{cat_opts}</select>
  <input type='file' name='file' required>
  <button>⬆️ Încarcă document</button>
</form>
<p class='hint' style='margin-top:8px'>Fișierele rămân local, în folderul programului (data\\files).</p></div>"""

    body = f"""{banner}
<div class='nav'><a href='/admin/search'>← Pacienți</a>
<a href='/admin/all'>📋 Programări</a></div>
<div class='fisa'>
  <div class='fcol-l'>
    <div class='fcard'>
      <div class='fhead'><div class='fav'>{e(_initials(p['name'] or '?'))}</div>
        <div style='min-width:0'><b>{e(p['name'] or '—')}</b><small>{meta}</small></div></div>
      <div style='margin-top:10px'>{info_rows}</div>{notes_html}
      <button onclick="var f=document.getElementById('pedit');f.style.display=f.style.display==='none'?'flex':'none'"
        style='margin-top:10px;background:none;border:1px solid var(--line);border-radius:8px;
        padding:7px 12px;cursor:pointer;font-size:12.5px;color:var(--text2);width:100%'>✏️ Editează profilul</button>
      {edit_form}
      <form method='post' action='{base}/archive' style='margin-top:7px'>
        <input type='hidden' name='on' value='{"0" if p.get("archived") else "1"}'>
        <button style='background:none;border:1px solid var(--line);border-radius:8px;
          padding:6px 12px;cursor:pointer;font-size:12px;color:var(--text3);width:100%'>
          {"↩️ Scoate din arhivă" if p.get("archived") else "🗄 Arhivează pacientul"}</button>
      </form>
    </div>
    {alerts_card}
  </div>
  <div class='fcol-c'>{teeth_card}{plan_card}</div>
  <div class='fcol-r'>{next_html}{hist_card}{docs_card}</div>
</div>"""
    return _shell(body, f"fișa pacientului · #{pid}", active="pat")


def _card_redirect(pid: int, msg: str = "") -> RedirectResponse:
    url = f"/admin/patient/{pid}" + (f"?msg={msg}" if msg else "")
    return RedirectResponse(url, status_code=303)


@app.post("/admin/patient/{pid}/save")
async def patient_save(request: Request, pid: int):
    if (deny := _guard(request)) is not None:
        return deny
    form = await request.form()
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    data = {}
    for f in db.PATIENT_FIELDS:
        v = str(form.get(f) or "").strip()[:200 if f != "notes" else 500]
        data[f] = v or None
    if not data.get("name"):
        return _card_redirect(pid, "bad_card")
    bd = data.get("birth_date")
    bd_year = None
    if bd:
        try:
            parsed = date.fromisoformat(bd)
            data["birth_date"] = parsed.isoformat()
            bd_year = parsed.year
        except ValueError:
            return _card_redirect(pid, "bad_card")
    if data.get("idnp") and not re.fullmatch(r"[0-9]{13}", data["idnp"]):
        return _card_redirect(pid, "bad_card")
    await db.update_patient(pid, data)
    if bd_year:
        # возраст в поиске/сетке/CSV считается по birth_year — держим в синке
        await db.set_birth_year(pid, bd_year)
    return _card_redirect(pid, "ok_card")


@app.post("/admin/patient/{pid}/archive")
async def patient_archive(request: Request, pid: int, on: str = Form("1")):
    """Архив = скрыть из списков; история и файлы остаются на месте."""
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    await db.set_archived(pid, on == "1")
    return _card_redirect(pid, "ok_card")


@app.post("/admin/patient/{pid}/alert")
async def patient_alert_add(request: Request, pid: int,
                            kind: str = Form(...), text: str = Form(...)):
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    if kind not in _ALERT_KINDS or not text.strip():
        return _card_redirect(pid, "bad_card")
    await db.add_alert(pid, kind, text.strip()[:120])
    return _card_redirect(pid, "ok_card")


@app.post("/admin/patient/{pid}/alert/{aid}/del")
async def patient_alert_del(request: Request, pid: int, aid: int):
    if (deny := _guard(request)) is not None:
        return deny
    await db.delete_alert(aid, pid)
    return _card_redirect(pid)


@app.post("/admin/patient/{pid}/tooth")
async def patient_tooth(request: Request, pid: int, tooth: int = Form(...),
                        state: str = Form(...), note: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    if tooth not in _FDI_UPPER + _FDI_LOWER or state not in TOOTH_STATES:
        return _card_redirect(pid, "bad_card")
    await db.set_tooth(pid, tooth, state, note.strip()[:120])
    return _card_redirect(pid, "ok_card")


@app.post("/admin/patient/{pid}/plan")
async def patient_plan_add(request: Request, pid: int, tooth: str = Form(""),
                           procedure: str = Form(...), doctor: str = Form(""),
                           price: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    if not procedure.strip():
        return _card_redirect(pid, "bad_card")
    t = int(tooth) if tooth.strip().isdecimal() else None
    if t is not None and t not in _FDI_UPPER + _FDI_LOWER:
        t = None
    pr = int(price) if price.strip().isdecimal() else None
    if pr is not None:
        pr = min(pr, 1_000_000)  # клиентский max дублируем на сервере (PG INT)
    await db.add_plan_item(pid, t, procedure.strip()[:120], doctor.strip()[:80], pr)
    return _card_redirect(pid, "ok_card")


@app.post("/admin/patient/{pid}/plan/{item_id}/status")
async def patient_plan_status(request: Request, pid: int, item_id: int,
                              to: str = Form(...)):
    if (deny := _guard(request)) is not None:
        return deny
    if to not in _PLAN_LABEL:
        return _card_redirect(pid, "bad_card")
    await db.set_plan_status(item_id, pid, to)
    return _card_redirect(pid)


@app.post("/admin/patient/{pid}/plan/{item_id}/del")
async def patient_plan_del(request: Request, pid: int, item_id: int):
    if (deny := _guard(request)) is not None:
        return deny
    await db.delete_plan_item(item_id, pid)
    return _card_redirect(pid)


@app.post("/admin/patient/{pid}/doc")
async def patient_doc_upload(request: Request, pid: int, file: UploadFile = File(...),
                             category: str = Form("alt")):
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    if category not in DOC_CATEGORIES:
        category = "alt"
    orig = pathlib.Path(file.filename or "document").name[:120] or "document"
    # whitelist расширения: ':' в имени = NTFS ADS (данные пропадут при копии
    # на USB/в zip), '?<>|*' = OSError; хвост не из [a-z0-9] просто отбрасываем
    ext = pathlib.Path(orig).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,9}", ext):
        ext = ""
    stored = _files_dir(pid) / f"{secrets.token_hex(8)}{ext}"
    size, cap = 0, MAX_DOC_MB * 1024 * 1024
    try:
        with open(stored, "wb") as out:
            while chunk := await file.read(1024 * 256):
                size += len(chunk)
                if size > cap:
                    out.close()
                    stored.unlink(missing_ok=True)
                    return _card_redirect(pid, "bad_doc")
                out.write(chunk)
    except OSError:
        stored.unlink(missing_ok=True)  # диск полон и т.п. — не оставляем огрызок
        return _card_redirect(pid, "bad_doc")
    finally:
        await file.close()
    if size == 0:
        stored.unlink(missing_ok=True)
        return _card_redirect(pid, "bad_doc")
    await db.add_document(pid, orig, str(stored), size, file.content_type or "", category)
    return _card_redirect(pid, "ok_doc")


@app.get("/admin/doc/{doc_id}")
async def patient_doc_get(request: Request, doc_id: int):
    if (deny := _guard(request)) is not None:
        return deny
    d = await db.get_document(doc_id)
    if not d or not pathlib.Path(d["stored_path"]).exists():
        return RedirectResponse("/admin/search", status_code=303)
    return FileResponse(d["stored_path"], filename=d["filename"],
                        media_type=d["mime"] or "application/octet-stream")


@app.post("/admin/patient/{pid}/doc/{doc_id}/del")
async def patient_doc_del(request: Request, pid: int, doc_id: int):
    if (deny := _guard(request)) is not None:
        return deny
    d = await db.get_document(doc_id)
    if d and d["patient_id"] == pid:
        pathlib.Path(d["stored_path"]).unlink(missing_ok=True)
        await db.delete_document(doc_id, pid)
    return _card_redirect(pid)


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
    items = list(eng.DOCTORS.items())
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
            if r["doctor"] == name]
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
    if not doctor or not svc or not name or len(digits) < 8:
        return _back_redirect(back, adate, "bad")
    if not eng.DOCTOR_META.get(adoctor, {}).get("active", True):
        return _back_redirect(back, adate, "bad")  # выключенному врачу не пишем
    year = int(ayear) if ayear.strip().isdigit() and 1900 <= int(ayear) <= 2026 else None
    r = await db.admin_add(name, phone, svc["ro"], doctor, dt, birth_year=year)
    msg = "ok" if isinstance(r, int) else ("dup" if r == "dup" else "conflict")
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
        if await db.add_note(doctor, dt, text) is not None:
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
 .noprint button{{background:#075e54;color:#fff;border:none;border-radius:8px;
      padding:10px 22px;font-size:15px;cursor:pointer}}
 .noprint a{{align-self:center;color:#075e54}}
 .sheet{{border:2px dashed #ccd;border-radius:6mm;padding:12mm 16mm;max-width:150mm}}
 h1{{font-size:26pt;color:#075e54}}
 h2{{font-size:15pt;color:#334;margin:4mm 0 8mm;font-weight:600}}
 img{{width:88mm;height:88mm}}
 .user{{font-size:14pt;color:#075e54;font-weight:600;margin-top:4mm}}
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
justify-content:center;height:100vh;margin:0;background:#075e54;color:#fff}}
img{{background:#fff;padding:18px;border-radius:12px;width:340px;height:340px}}
h1{{font-weight:600;font-size:22px}}p{{font-size:14px;opacity:.85}}</style></head><body>
<h1>🦷 Scanați pentru programare / Сканируйте для записи</h1>
<img src="/qr?data={q}" alt="QR">
<p>{html.escape(target)}</p></body></html>"""
