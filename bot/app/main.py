import asyncio
import csv
import hashlib
import hmac
import html
import io
import json
import os
import pathlib
import logging
import re
import secrets
import shutil
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
from . import teeth_svg as tsvg
from . import update as upd

app = FastAPI(title="DentPilot")
log = logging.getLogger("web")

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
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#F6FBF8;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0;color:#162033}
 form{background:#fff;padding:30px 32px;border-radius:18px;border:1px solid #E7EDF5;
      box-shadow:0 18px 40px rgba(15,23,42,.08);
      display:flex;flex-direction:column;gap:12px;width:340px}
 h1{font-size:19px;color:#162033;margin:0 0 4px;font-weight:600;letter-spacing:-.02em}
 input{height:44px;padding:0 14px;border:1px solid #E7EDF5;border-radius:12px;font-size:15px;
       outline:none;color:#162033}
 input:focus{border-color:#0E9F8A;box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 button{background:#0E9F8A;color:#fff;border:none;border-radius:12px;height:44px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:#0B7E6D}
 .err{color:#B91C1C;font-size:13px}
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
    "past": ("err", "Ora aleasă a trecut deja — reîmprospătați lista orelor libere"),
    "ok_past": ("warn", "Programare adăugată ✔ — atenție: este pe o zi trecută. "
                        "Verificați data dacă nu ați vrut asta"),
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
    "outside": ("err", "Vizita nu încape în programul clinicii (închidere sau pauză)"),
    "ok_card": ("ok", "Fișa pacientului a fost actualizată ✔"),
    "bad_card": ("err", "Date invalide — verificați câmpurile fișei"),
    "ok_doc": ("ok", "Document încărcat ✔ — rămâne local, în folderul programului"),
    "bad_doc": ("err", "Fișier gol sau prea mare (max 25 MB)"),
    "ok_med": ("ok", "Datele medicului au fost salvate ✔"),
    "bad_med": ("err", "Date invalide — verificați câmpurile medicului"),
    "new_med": ("ok", "Medic adăugat ✔ — completați fișa lui"),
    "dup_med": ("err", "Există deja un medic cu acest nume — numele trebuie să fie unic"),
    "ok_photo": ("ok", "Fotografia a fost salvată ✔ — rămâne local, lângă program"),
    "bad_photo": ("err", "Doar JPEG / PNG / WebP, până la 5 MB"),
    "ok_svc_med": ("ok", "Serviciile medicului au fost actualizate ✔"),
    "svc_empty": ("err", "Fiecare serviciu trebuie să rămână cu cel puțin un medic "
                         "ACTIV — altfel dispare din meniul botului. Bifați alt medic "
                         "(sau readuceți unul din concediu) înainte de a-l scoate pe acesta"),
    "save_err": ("err", "Nu am putut scrie fișierul clinicii (clinic.json) — datele NU "
                        "au fost salvate. Verificați spațiul pe disc și drepturile la "
                        "folderul programului; detalii în data\\dentpilot.log"),
    "arch_busy": ("err", "Medicul are programări viitoare — mutați-le la alt medic sau "
                         "alegeți «în concediu» în loc de arhivare"),
    "last_med": ("err", "Trebuie să rămână cel puțin un medic activ"),
}

# Дизайн-система v1.10.0 (макет Олега 08-03, панели 1-11) — развитие светлого
# SaaS-референса v1.5.0: тот же акцент teal, но крупнее типографика, выше
# контролы (44px), радиусы 12/16, мягкие многослойные тени, фон с зелёным
# подтоном. ⭐ Имена переменных СОХРАНЕНЫ (--teal/--bg/--line/--sh): меняются
# значения, поэтому вся система перекрашивается разом, без правки сотен мест.
# Соответствие макету: --teal=--primary, --bg=--background, --line=--border,
# --text2=--text-secondary, --sh/--sh2/--sh3=--shadow-sm/md/lg.
PANEL_CSS = """
 :root{--bg:#F6FBF8;--panel:#FFFFFF;--line:#E7EDF5;--line2:#F1F6FA;
   --text:#162033;--text2:#7E8B9C;--text3:#A0AAB8;
   --teal:#0E9F8A;--teal-d:#0B7E6D;--teal-soft:#EAFBF5;--teal-line:#CCF0E7;
   --green:#10B981;--green-soft:#ECFDF5;--blue:#3B82F6;--blue-soft:#EFF6FF;
   --amber:#F59E0B;--amber-soft:#FFFBEB;--red:#EF4444;--red-soft:#FEF2F2;
   --violet:#7C3AED;--violet-soft:#F5F3FF;
   /* текстовые варианты акцентных цветов: макетные #F59E0B/#EF4444 хороши для
      рамок и иконок, но как ТЕКСТ на белом дают ~2:1 — читаемость важнее */
   --amber-t:#B45309;--red-t:#B91C1C;--green-t:#047857;
   --r-card:18px;--r-ctl:12px;--h-ctl:44px;
   --sh:0 2px 6px rgba(15,23,42,.04);
   --sh2:0 8px 24px rgba(15,23,42,.06);
   --sh3:0 18px 40px rgba(15,23,42,.08)}
 *{box-sizing:border-box}
 body{font-family:'Inter','Segoe UI Variable Text','Segoe UI',system-ui,Roboto,sans-serif;
   background:var(--bg);margin:0;color:var(--text);display:flex;min-height:100vh;
   line-height:1.5}
 a{color:var(--teal)}
 /* ---------- каркас: сайдбар + топбар + контент ---------- */
 .side{width:216px;flex:0 0 216px;background:var(--panel);border-right:1px solid var(--line);
   display:flex;flex-direction:column;position:sticky;top:0;height:100vh;overflow-y:auto}
 .side .brand{display:flex;align-items:center;gap:10px;padding:18px 16px 14px}
 /* знак — тот же, что на иконке рабочего стола (bot/app/brand.py): фон и
    скругление нарисованы внутри самой картинки, CSS их не дублирует */
 .side .brand .logo{width:34px;height:34px;flex:0 0 34px;display:block}
 .side .brand b{font-size:15px;display:block;line-height:1.2}
 .side .brand small{color:var(--text2);font-size:11.5px;display:block;white-space:nowrap;
   overflow:hidden;text-overflow:ellipsis;max-width:130px}
 .side .sec{font-size:10.5px;font-weight:600;letter-spacing:.08em;color:var(--text3);
   padding:14px 18px 6px;text-transform:uppercase}
 .side nav a{display:flex;align-items:center;gap:12px;margin:2px 10px;padding:0 12px;
   height:44px;border-radius:var(--r-ctl);text-decoration:none;color:var(--text2);
   font-size:14px;font-weight:500;transition:background-color .2s ease,color .2s ease}
 .side nav a svg{flex:0 0 16px}
 .side nav a:hover{background:var(--line2);color:var(--text)}
 .side nav a.on{background:var(--teal-soft);color:var(--teal);font-weight:600}
 .side nav a .dot{width:7px;height:7px;border-radius:50%;margin-left:auto}
 .side nav a .dot.ok{background:var(--green)}
 .side nav a .dot.off{background:var(--text3)}
 .side .sfoot{margin-top:auto;padding:12px 16px;border-top:1px solid var(--line);
   font-size:11.5px;color:var(--text3)}
 .main{flex:1;min-width:0;display:flex;flex-direction:column}
 .top{height:72px;flex:0 0 72px;background:var(--panel);border-bottom:1px solid var(--line);
   display:flex;align-items:center;gap:12px;padding:0 24px;position:sticky;top:0;z-index:20}
 .top form.searchf{display:flex;gap:0;align-items:center;background:#FBFDFE;
   border:1px solid var(--line);border-radius:var(--r-ctl);padding:0 8px 0 14px;
   height:var(--h-ctl);width:320px;margin:0;transition:border-color .2s ease,box-shadow .2s ease}
 .top form.searchf:focus-within{border-color:var(--teal);box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 .top form.searchf input{border:none;background:none;outline:none;font-size:14px;flex:1;color:var(--text)}
 .top form.searchf button{background:none;border:none;color:var(--text3);cursor:pointer;font-size:15px;padding:4px 6px}
 .top .kbd{font-size:11px;color:var(--text3);border:1px solid var(--line);border-radius:6px;padding:2px 6px}
 .top .bell{position:relative;width:var(--h-ctl);height:var(--h-ctl);border-radius:var(--r-ctl);
   display:flex;align-items:center;justify-content:center;color:var(--text2);
   text-decoration:none;font-size:17px;transition:background-color .2s ease}
 .top .bell:hover{background:var(--line2)}
 .top .bell .n{position:absolute;top:5px;right:5px;min-width:16px;height:16px;border-radius:8px;
   background:var(--red);color:#fff;font-size:10px;font-weight:600;line-height:16px;text-align:center;padding:0 4px}
 .top .newbtn{display:flex;align-items:center;gap:8px;height:var(--h-ctl);padding:0 18px;
   border-radius:var(--r-ctl);background:var(--teal);color:#fff;font-size:14px;font-weight:600;
   text-decoration:none;transition:background-color .2s ease,box-shadow .2s ease,transform .2s ease}
 .top .newbtn:hover{background:var(--teal-d);box-shadow:0 6px 16px rgba(14,159,138,.22);
   transform:translateY(-1px)}
 .top .newbtn:active{transform:translateY(0)}
 .content{padding:24px 24px 60px;max-width:1500px}
 /* ---------- общие элементы ---------- */
 h1{font-size:32px;margin:0 0 4px;font-weight:600;letter-spacing:-.03em;line-height:1.2}
 h1 a{color:var(--text);text-decoration:none}
 h2{font-size:18px;color:var(--text);margin:24px 0 12px;font-weight:600}
 .sub{color:var(--text2);font-size:13px;margin-bottom:18px}
 .nav{margin-bottom:16px;display:flex;align-items:center;flex-wrap:wrap;gap:8px}
 .nav b{font-size:16px;margin-right:6px;font-weight:600}
 .nav a{display:inline-flex;align-items:center;height:var(--h-ctl);background:var(--panel);
        border:1px solid var(--line);border-radius:var(--r-ctl);padding:0 16px;text-decoration:none;
        color:var(--text2);font-size:14px;font-weight:500;
        transition:border-color .2s ease,color .2s ease,box-shadow .2s ease,transform .2s ease}
 .nav a:hover{border-color:var(--teal);color:var(--teal-d);
   box-shadow:0 4px 12px rgba(14,159,138,.12);transform:translateY(-1px)}
 .nav a:active{transform:translateY(0)}
 .nav a.primary{background:var(--teal);color:#fff;border-color:var(--teal)}
 .nav form.dpickf{display:inline-flex;margin:0}
 .nav input.dpick{height:var(--h-ctl);padding:0 12px;border:1px solid var(--line);
   border-radius:var(--r-ctl);font-size:14px;background:var(--panel);color:var(--text2)}
 .nav form.searchf{display:flex;gap:8px;align-items:center;margin:0}
 .nav form.searchf input{height:var(--h-ctl);padding:0 14px;border:1px solid var(--line);
   border-radius:var(--r-ctl);font-size:14px;width:240px;background:var(--panel);
   color:var(--text);outline:none}
 .nav form.searchf input:focus{border-color:var(--teal);box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 .nav form.searchf button{background:var(--teal);color:#fff;border:none;border-radius:var(--r-ctl);
   height:var(--h-ctl);padding:0 16px;cursor:pointer;font-size:14px;font-weight:600}
 .banner{padding:12px 16px;border-radius:var(--r-ctl);margin-bottom:14px;font-size:14px}
 .banner.ok{background:var(--green-soft);color:#065F46}
 .banner.err{background:var(--red-soft);color:#991B1B}
 .banner.warn{background:var(--amber-soft);color:var(--amber-t)}
 .statbar{background:var(--line2);border-radius:4px;height:8px;overflow:hidden}
 .statbar div{background:var(--teal);height:8px}
 /* ---------- KPI ---------- */
 .tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));
   gap:14px;margin-bottom:22px}
 .tile{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);
   box-shadow:var(--sh);padding:16px;min-width:0;display:flex;gap:14px;
   align-items:flex-start}
 a.tile{text-decoration:none;color:inherit;
   transition:box-shadow .25s ease,transform .25s ease,border-color .2s ease}
 a.tile:hover{box-shadow:0 12px 32px rgba(15,23,42,.08);transform:translateY(-2px)}
 .tile .ico{width:44px;height:44px;border-radius:14px;display:flex;align-items:center;
   justify-content:center;font-size:18px;flex:0 0 44px}
 .tile b{display:block;font-size:26px;font-weight:600;line-height:1.1}
 .tile span{font-size:13px;color:var(--text2);font-weight:500}
 .tile .trend{display:block;font-size:12px;margin-top:4px;color:var(--text3)}
 .tile .trend .up{color:var(--green);font-weight:600}
 .tile .trend .dn{color:var(--red-t);font-weight:600}
 .tile.warn b{color:var(--amber-t)}
 .tile.bad b{color:var(--red-t)}
 /* ---------- дневная сетка (canvas) ---------- */
 .dash{display:flex;gap:16px;align-items:flex-start}
 .dashmain{flex:1;min-width:0}
 .rail{width:300px;flex:0 0 300px;display:flex;flex-direction:column;gap:14px}
 .gridcard{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);
   box-shadow:var(--sh);overflow:hidden}
 /* полоса карточек врачей над расписанием (макет Олега 08-03): каждая ячейка
    остаётся flex:1 и стоит над своей колонкой, а сама карточка живёт ВНУТРИ неё
    с отступом — так вид «плавающих карточек» не ломает выравнивание с сеткой */
 .gridhead{display:flex;margin-bottom:14px;align-items:stretch}
 .gridhead .gh-time{width:56px;flex:0 0 56px}
 .gridhead .gh-doc{flex:1;min-width:0;padding:0 5px;display:flex}
 .gh-doc .dcard{flex:1;min-width:0;display:flex;gap:10px;align-items:center;
   background:var(--panel);border-radius:16px;padding:12px;box-shadow:var(--sh);
   border-left:4px solid var(--teal);transition:transform .18s ease,box-shadow .18s ease}
 .gh-doc .dcard:hover{transform:translateY(-2px);box-shadow:var(--sh2)}
 .gh-doc .dcard.off{opacity:.72}
 .gh-doc .av{width:44px;height:44px;border-radius:50%;color:#fff;display:flex;align-items:center;
   justify-content:center;font-size:15px;font-weight:600;flex:0 0 44px;overflow:hidden}
 .gh-doc .av img{width:100%;height:100%;object-fit:cover;display:block}
 .gh-doc .nm{min-width:0;flex:1}
 .gh-doc .nm a{font-size:14px;font-weight:600;color:var(--text);text-decoration:none;
   white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
 .gh-doc .nm a:hover{color:var(--teal-d)}
 .gh-doc .nm small{display:block;font-size:11.5px;color:var(--text2);white-space:nowrap;
   overflow:hidden;text-overflow:ellipsis}
 .gh-doc .nm small.mt{color:var(--text3);font-size:11px}
 .gh-doc .st{width:8px;height:8px;border-radius:50%;flex:0 0 8px;align-self:flex-start;
   margin-top:3px}
 /* Плотный режим — когда карточка становится узкой: >4 врачей (класс ставит
    сервер, он один знает их число) или окно уже 1440px (у клиники это 1366×768,
    там на карточку остаётся ~170px). Специализация уходит первой — её роль берёт
    на себя цвет карточки; имя вместо многоточия переносится на вторую строку,
    место под неё в карточке есть. */
 .gridhead.tight .gh-doc{padding:0 3px}
 .gridhead.tight .dcard{gap:8px;padding:9px;border-radius:12px}
 .gridhead.tight .av{width:34px;height:34px;flex:0 0 34px;font-size:12px}
 .gridhead.tight .nm a{font-size:12.5px;white-space:normal;line-height:1.22;
   display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
 .gridhead.tight .nm small{display:none}
 .gridhead.tight .nm small.mt{display:block;font-size:10.5px;margin-top:1px}
 @media (max-width:1440px){
   .gh-doc .dcard{gap:8px;padding:9px;border-radius:12px}
   .gh-doc .av{width:34px;height:34px;flex:0 0 34px;font-size:12px}
   .gh-doc .nm a{font-size:12.5px;white-space:normal;line-height:1.22;
     display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
   .gh-doc .nm small{display:none}
   .gh-doc .nm small.mt{display:block;font-size:10.5px;margin-top:1px}
 }
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
 .mcal{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);
   box-shadow:var(--sh);padding:14px 16px}
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
 a.card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--sh);
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
 .appt.busy{background:repeating-linear-gradient(135deg,var(--line2) 0 5px,transparent 5px 11px);
   color:var(--text3);text-align:center;font-size:11.5px}
 .appt.clickable{cursor:pointer}
 .appt.clickable:hover{filter:brightness(.98)}
 .appt .cmt{color:#92710A;font-size:11.5px;margin-top:2px}
 a.plink{color:var(--teal-d);text-decoration:none;border-bottom:1px dashed var(--teal-line)}
 a.plink:hover{border-bottom-style:solid}
 .pcard{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);
   box-shadow:var(--sh);padding:16px 18px;margin-bottom:14px}
 .pcard h3{margin:0 0 6px;font-size:14.5px;color:var(--text)}
 .pcard .meta{color:var(--text2);font-size:12.5px;margin-bottom:8px}
 .vpast{opacity:.55}
 table.set{border-collapse:collapse;width:100%;background:var(--panel);box-shadow:var(--sh);
   border-radius:14px;overflow:hidden;margin-bottom:10px}
 table.set th,table.set td{padding:8px 12px;border-bottom:1px solid var(--line2);text-align:left;font-size:13px}
 table.set th{background:var(--bg);color:var(--text2);font-weight:600}
 table.set input[type=text],table.set input[type=number]{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:8px;font-size:13px}
 table.set select{padding:6px 7px;border:1px solid var(--line);border-radius:8px;font-size:13px}
 .rowdel{background:var(--red-soft);color:var(--red-t);border:none;border-radius:7px;padding:4px 10px;cursor:pointer}
 .addrow{background:none;border:1px dashed var(--teal);color:var(--teal-d);border-radius:10px;padding:7px 15px;cursor:pointer;margin-bottom:16px}
 .savebtn{background:var(--teal);color:#fff;border:none;border-radius:var(--r-ctl);
   height:var(--h-ctl);padding:0 26px;font-size:14px;font-weight:600;cursor:pointer;
   transition:background-color .2s ease,box-shadow .2s ease,transform .2s ease}
 .savebtn:hover{background:var(--teal-d);box-shadow:0 6px 16px rgba(14,159,138,.22);
   transform:translateY(-1px)}
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
 .dlg-form input,.dlg-form select{height:var(--h-ctl);padding:0 14px;border:1px solid var(--line);
   border-radius:var(--r-ctl);font-size:14px;background:var(--panel);color:var(--text);outline:none}
 .dlg-form textarea{padding:11px 14px;border:1px solid var(--line);border-radius:var(--r-ctl);
   font-size:14px;font-family:inherit;background:var(--panel);color:var(--text);outline:none}
 .dlg-form input:focus,.dlg-form select:focus,.dlg-form textarea:focus{border-color:var(--teal);
   box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 .dlg-form button{background:var(--teal);color:#fff;border:none;border-radius:9px;padding:10px;cursor:pointer;font-size:13.5px;font-weight:600}
 a.free{display:block;text-align:center;color:var(--text3);text-decoration:none;font-size:16px;padding:4px 0;border-radius:8px}
 a.free:hover{color:var(--teal-d);background:var(--teal-soft)}
 form.add{background:var(--panel);padding:16px;border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--sh);
          display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:18px}
 form.add input,form.add select{height:var(--h-ctl);padding:0 14px;border:1px solid var(--line);
   border-radius:var(--r-ctl);font-size:14px;background:var(--panel);color:var(--text);outline:none;
   transition:border-color .2s ease,box-shadow .2s ease}
 form.add input:focus,form.add select:focus{border-color:var(--teal);
   box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 form.add input::placeholder{color:var(--text3)}
 form.add button{background:var(--teal);color:#fff;border:none;border-radius:var(--r-ctl);
   height:var(--h-ctl);padding:0 20px;cursor:pointer;font-size:14px;font-weight:600;
   transition:background-color .2s ease,box-shadow .2s ease,transform .2s ease}
 form.add button:hover{background:var(--teal-d);box-shadow:0 6px 16px rgba(14,159,138,.22);
   transform:translateY(-1px)}
 form.add button:active{transform:translateY(0)}
 table.list{border-collapse:collapse;width:100%;background:var(--panel);box-shadow:var(--sh);
   border:1px solid var(--line);border-radius:var(--r-card);overflow:hidden}
 table.list th,table.list td{padding:11px 14px;border-bottom:1px solid var(--line2);
   text-align:left;font-size:13.5px}
 table.list th{background:var(--bg);color:var(--text2);font-weight:600}
 tr.cancelled td{opacity:.45;text-decoration:line-through}
 .act{display:inline}
 .act button{border:none;border-radius:8px;padding:5px 10px;margin-right:4px;cursor:pointer;
   font-size:12px;color:#fff;transition:filter .2s ease}
 .act button:hover{filter:brightness(1.08)}
 .b-arrived{background:var(--teal-d)}
 .b-done{background:#2563EB}.b-noshow{background:var(--red-t)}.b-cancel{background:#64748B}
 .hint{color:var(--text2);font-size:12.5px;margin-top:10px;line-height:1.55}
 .botnew{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);
   box-shadow:var(--sh);padding:14px 16px;margin-bottom:14px}
 .botnew h3{margin:0 0 4px;font-size:13.5px;font-weight:600}
 .botnew a{display:block;padding:6px 0;font-size:12.5px;color:inherit;text-decoration:none;border-top:1px solid var(--line2)}
 .botnew a:hover{background:var(--bg)}
 .botnew .dt{color:var(--teal-d);font-weight:600}
 .botnew .crt{color:var(--text3);font-size:11.5px}
 .botnew .nou{background:var(--amber-t);color:#fff;border-radius:5px;padding:1px 6px;font-size:10.5px;margin-left:6px;font-weight:600}
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
 .fcard{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);
   box-shadow:var(--sh);padding:18px}
 .fcard h3{margin:0 0 14px;font-size:18px;font-weight:600}
 .fcard h3 small{color:var(--text2);font-weight:400;font-size:13px}
 .fhead{display:flex;align-items:center;gap:14px}
 .fhead .fav{width:56px;height:56px;border-radius:16px;background:var(--teal);color:#fff;
   display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:600;flex:0 0 56px}
 .fhead b{font-size:20px;display:block;line-height:1.25;font-weight:600}
 .fhead small{color:var(--text2);font-size:13px}
 /* строка профиля: подпись слева, значение справа, иконка-якорь в конце
    (панель «Card» макета) */
 .frow{display:flex;justify-content:space-between;align-items:center;gap:10px;
   padding:9px 0;font-size:13.5px;border-top:1px solid var(--line2)}
 .frow:first-of-type{border-top:none}
 .frow span:first-child{color:var(--text2);flex:0 0 auto}
 .frow .v{color:var(--text);font-weight:500;text-align:right;min-width:0;flex:1;
   overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .frow .ic{flex:0 0 16px;color:var(--text3);display:flex;align-items:center}
 .alert{display:flex;align-items:center;gap:9px;border-radius:var(--r-ctl);padding:10px 12px;
   font-size:13px;font-weight:600;margin-bottom:8px}
 .alert form{margin-left:auto}
 .alert button{background:none;border:none;cursor:pointer;color:inherit;opacity:.55;font-size:13px}
 .alert.allergy{background:var(--red-soft);color:var(--red-t)}
 .alert.medication{background:var(--amber-soft);color:var(--amber-t)}
 .alert.warning{background:var(--amber-soft);color:var(--amber-t)}
 .alert.info{background:var(--blue-soft);color:var(--blue)}
 /* зубы — кнопки 40x44 (панель 9 макета): состояние показывает РАМКА, а не
    заливка, поэтому крупная сетка не рябит цветом */
 /* одонтограмма: параметрические SVG-зубы (bot/app/teeth_svg.py) */
 .tooth-svg{display:block;overflow:visible}
 .tooth-btn{background:none;border:none;padding:4px 2px;cursor:pointer;border-radius:12px;
   display:flex;flex-direction:column;align-items:center;gap:4px;
   transition:transform .2s ease,background-color .2s ease,box-shadow .2s ease}
 .tooth-btn .num{font-size:11.5px;font-weight:600;color:var(--text2);
   transition:color .2s ease}
 .tooth-btn:hover{background:var(--teal-soft);transform:translateY(-3px) scale(1.04);
   box-shadow:0 10px 24px rgba(15,23,42,.10)}
 .tooth-btn:hover .num{color:var(--teal-d)}
 .tooth-btn.sel{background:var(--teal-soft);box-shadow:inset 0 0 0 2px var(--teal)}
 .tooth-btn.sel .num{color:var(--teal-d)}
 .arch{display:grid;grid-template-columns:repeat(16,minmax(0,1fr));gap:var(--tooth-gap,10px);
   align-items:end}
 .arch.lower{align-items:start}
 .arch-wrap{display:flex;flex-direction:column;gap:10px}
 .arch-mid{height:1px;background:var(--line);margin:2px 0}
 .tleg{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--text2);
   margin-top:16px;align-items:center}
 .tleg .lg{display:inline-flex;align-items:center;gap:6px}

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
 .fform{display:flex;flex-direction:column;gap:9px}
 .fform input,.fform select{height:var(--h-ctl);padding:0 14px;border:1px solid var(--line);
   border-radius:var(--r-ctl);font-size:14px;font-family:inherit;width:100%;
   background:var(--panel);color:var(--text);outline:none;
   transition:border-color .2s ease,box-shadow .2s ease}
 .fform textarea{padding:11px 14px;border:1px solid var(--line);border-radius:var(--r-ctl);
   font-size:14px;font-family:inherit;width:100%;background:var(--panel);color:var(--text);
   outline:none;transition:border-color .2s ease,box-shadow .2s ease}
 .fform input:focus,.fform select:focus,.fform textarea:focus{border-color:var(--teal);
   box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 .fform input::placeholder,.fform textarea::placeholder{color:var(--text3)}
 .fform button{background:var(--teal);color:#fff;border:none;border-radius:var(--r-ctl);
   height:var(--h-ctl);cursor:pointer;font-size:14px;font-weight:600;
   transition:background-color .2s ease,box-shadow .2s ease,transform .2s ease}
 .fform button:hover{background:var(--teal-d);box-shadow:0 6px 16px rgba(14,159,138,.22);
   transform:translateY(-1px)}
 .fform button:active{transform:translateY(0)}
 .fform .r2{display:flex;gap:9px}
 @media (max-width:1400px){.fisa{flex-wrap:wrap}.fcol-l,.fcol-r{width:100%;flex:1 1 100%}}
 /* фиша медика уже карточки пациента (нет формулы зубов) — на 1366×768,
    рабочем разрешении клиники, она остаётся в три колонки */
 @media (max-width:1400px){.fisa.med{flex-wrap:nowrap}
   .fisa.med .fcol-l{width:300px;flex:0 0 300px}
   .fisa.med .fcol-r{width:280px;flex:0 0 280px}}
 @media (max-width:1150px){.fisa.med{flex-wrap:wrap}
   .fisa.med .fcol-l,.fisa.med .fcol-r{width:100%;flex:1 1 100%}}
 /* ---------- фиша пациента V2 (макет 08-03): рабочее пространство врача ----------
    Центр отдан одонтограмме и лечению, справа — липкая информационная панель. */
 .pv2{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:20px;align-items:start}
 .pv2-main{min-width:0;display:flex;flex-direction:column;gap:16px}
 .pv2-side{position:sticky;top:88px;display:flex;flex-direction:column;gap:16px}
 /* Порог = ширина, при которой центру ещё хватает на одонтограмму:
    16 зубов × 38px + 15 зазоров × 10px + поля карточки ≈ 794px.
    1366 − сайдбар 216 − поля 48 − панель 320 − зазор 20 = 762 < 794 → на таком
    экране правая панель уходит ВНИЗ, и дуга помещается целиком. */
 @media (max-width:1400px){.pv2{grid-template-columns:minmax(0,1fr)}
   .pv2-side{position:static}}
 .hero{display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap;
   background:var(--panel);border:1px solid var(--line);border-radius:22px;
   padding:24px 28px;box-shadow:var(--sh);margin-bottom:16px}
 .hero-av{width:92px;height:92px;flex:0 0 92px;border-radius:24px;background:var(--teal);
   color:#fff;display:flex;align-items:center;justify-content:center;font-size:32px;
   font-weight:600;box-shadow:0 12px 24px rgba(14,159,138,.22)}
 .hero-id{flex:1;min-width:260px}
 .hero-id h2{font-size:34px;font-weight:600;letter-spacing:-.03em;margin:0;line-height:1.15}
 .hero-meta{display:flex;gap:16px;flex-wrap:wrap;font-size:14px;color:var(--text2);margin-top:6px}
 .hero-badges{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
 .pill{padding:6px 12px;border-radius:999px;font-size:13px;font-weight:500;white-space:nowrap}
 .pill.orange{background:#FFF4E5;color:var(--amber-t)}
 .pill.green{background:#ECFDF3;color:#15803D}
 .pill.purple{background:#F3E8FF;color:#6D28D9}
 .pill.red{background:#FEECEC;color:var(--red-t)}
 .pill.grey{background:var(--line2);color:var(--text2)}
 .hero-side{display:flex;gap:28px;flex-wrap:wrap}
 .hero-side .hs{font-size:13px}
 .hero-side .hs span{display:block;color:var(--text3);font-size:12px;margin-bottom:3px}
 .hero-side .hs b{font-weight:600;font-size:14.5px}
 .hero-acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
 .hero-acts a,.hero-acts button{display:inline-flex;align-items:center;gap:7px;height:40px;
   padding:0 14px;border:1px solid var(--line);border-radius:var(--r-ctl);text-decoration:none;
   color:var(--text2);font-size:13.5px;font-weight:500;background:var(--panel);
   font-family:inherit;cursor:pointer;
   transition:border-color .2s ease,color .2s ease,transform .2s ease}
 .hero-acts a:hover,.hero-acts button:hover{border-color:var(--teal);color:var(--teal-d);
   transform:translateY(-1px)}
 /* внутренний номер фиши: справочная мелочь, копируется кликом */
 .idchip{cursor:pointer;border-bottom:1px dashed var(--line);color:var(--text3)}
 .idchip:hover{color:var(--teal-d);border-bottom-color:var(--teal)}
 .kpi5{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;
   margin-bottom:16px}
 .kpi{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px;
   display:flex;gap:14px;align-items:center;
   transition:transform .2s ease,box-shadow .2s ease}
 .kpi:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(15,23,42,.08)}
 .kpi .ki{width:42px;height:42px;flex:0 0 42px;border-radius:13px;display:flex;
   align-items:center;justify-content:center;font-size:18px;background:var(--teal-soft)}
 .kpi b{display:block;font-size:22px;font-weight:600;line-height:1.15}
 .kpi span{font-size:12.5px;color:var(--text2)}
 .kpi small{display:block;font-size:11.5px;color:var(--text3);margin-top:2px}
 /* цифра кликабельна: за ней открывается список, из которого она посчитана */
 button.kpi{width:100%;text-align:left;font-family:inherit;color:inherit;cursor:pointer}
 button.kpi:focus-visible{outline:2px solid var(--teal);outline-offset:2px}
 /* список за цифрой + просмотрщик документов */
 dialog.wide{width:660px}
 .lbody{padding:4px 16px 16px;max-height:62vh;overflow:auto}
 .lrow{display:flex;flex-direction:column;gap:2px;padding:10px 0;
   border-bottom:1px solid var(--line2)}
 .lrow:last-of-type{border-bottom:none}
 .lrow .lk{font-size:11.5px;color:var(--text3)}
 .lrow b{font-size:13.5px;font-weight:600}
 .lrow small{font-size:12px;color:var(--text2)}
 .lmore{display:inline-block;margin-top:12px;font-size:12.5px;font-weight:600}
 .lbtn{margin-top:12px;width:100%;height:42px;border:none;border-radius:var(--r-ctl);
   background:var(--teal);color:#fff;font-size:13.5px;font-weight:600;cursor:pointer;
   font-family:inherit}
 .dlg-form .dlab{display:flex;flex-direction:column;gap:4px;font-size:11.5px;
   font-weight:600;color:var(--text3)}
 .dlg-form .dlab select,.dlg-form .dlab input{width:100%}
 .dlg-form button[disabled]{opacity:.5;cursor:not-allowed}
 .dvbody{background:var(--line2);display:flex;align-items:center;justify-content:center;
   min-height:280px;max-height:70vh;overflow:auto}
 .dvbody img{max-width:100%;max-height:70vh;display:block}
 .dvbody iframe{width:100%;height:70vh;border:none;background:#fff}
 .dvacts{display:flex;gap:10px;padding:12px 16px;flex-wrap:wrap}
 .dvacts button,.dvacts a{height:38px;padding:0 14px;display:inline-flex;align-items:center;
   gap:7px;border:1px solid var(--line);border-radius:var(--r-ctl);background:var(--panel);
   color:var(--text2);font-size:13px;font-weight:500;font-family:inherit;cursor:pointer;
   text-decoration:none}
 .dvacts button:hover,.dvacts a:hover{border-color:var(--teal);color:var(--teal-d)}
 .tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
 .tabs button{height:36px;padding:0 14px;border-radius:999px;border:1px solid var(--line);
   background:var(--panel);color:var(--text2);font-size:13px;font-weight:500;cursor:pointer;
   transition:background-color .2s ease,border-color .2s ease,color .2s ease}
 .tabs button:hover{border-color:var(--teal);color:var(--teal-d)}
 .tabs button.on{background:var(--teal);border-color:var(--teal);color:#fff}
 .docgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}
 .doccard{position:relative;border:1px solid var(--line);border-radius:16px;overflow:hidden;
   background:var(--panel);text-decoration:none;color:inherit;display:flex;
   flex-direction:column;transition:transform .2s ease,box-shadow .2s ease}
 .doccard:hover{transform:translateY(-3px);box-shadow:0 14px 30px rgba(15,23,42,.10)}
 .doccard .thumb{height:120px;background:var(--line2);display:flex;align-items:center;
   justify-content:center;font-size:30px;overflow:hidden}
 .doccard .thumb img{width:100%;height:100%;object-fit:cover;display:block}
 .doccard .dmeta{padding:9px 11px;font-size:12px;min-width:0}
 .doccard .dmeta b{display:block;font-weight:600;font-size:12.5px;white-space:nowrap;
   overflow:hidden;text-overflow:ellipsis}
 .doccard .dmeta small{color:var(--text3);font-size:11px}
 .doccard .del{position:absolute;top:8px;right:8px;opacity:0;transition:opacity .2s ease}
 .doccard:hover .del{opacity:1}
 .doccard .del button{border:none;background:rgba(255,255,255,.92);color:var(--red-t);
   width:28px;height:28px;border-radius:9px;cursor:pointer;font-size:13px;box-shadow:var(--sh)}
 /* свой выбор файла: системный input рисует ОС на языке Windows */
 .filepick{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 .filepick input[type=file]{position:absolute;width:1px;height:1px;opacity:0;
   overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
 .filepick label{display:inline-flex;align-items:center;gap:8px;height:var(--h-ctl);
   padding:0 16px;border:1px solid var(--line);border-radius:var(--r-ctl);
   background:var(--panel);color:var(--text2);font-size:13.5px;font-weight:500;
   cursor:pointer;transition:border-color .2s ease,color .2s ease}
 .filepick label:hover{border-color:var(--teal);color:var(--teal-d)}
 .filepick input[type=file]:focus-visible + label{border-color:var(--teal);
   box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 .filepick .fname{font-size:12.5px;color:var(--text3);min-width:0;
   overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
 .filepick .fname.on{color:var(--text)}
 .qa{display:flex;gap:12px;flex-wrap:wrap}
 .qa a,.qa button{display:inline-flex;align-items:center;justify-content:center;gap:9px;
   height:48px;min-width:140px;padding:0 18px;border:1px solid var(--line);
   border-radius:14px;background:var(--panel);color:var(--text);font-size:14px;
   font-weight:500;text-decoration:none;cursor:pointer;
   transition:background-color .2s ease,transform .2s ease,border-color .2s ease}
 .qa a:hover,.qa button:hover{background:#F3F8FC;border-color:var(--teal);transform:translateY(-1px)}
 @media print{
   .side,.top,.brandcorner,.qa,.tabs,.hero-acts,.doccard .del{display:none !important}
   body{background:#fff}.content{padding:0;max-width:none}
   .pv2{grid-template-columns:1fr}.pv2-side{position:static}
   .fcard,.hero,.kpi{box-shadow:none;break-inside:avoid}
 }
 /* лента активности: что происходило с фишей */
 .acti{display:flex;gap:12px;align-items:flex-start;padding:14px 0;
   border-bottom:1px solid var(--line2);transition:background-color .2s ease}
 .acti:last-of-type{border-bottom:none}
 .acti:hover{background:#F9FBFD}
 .acti .ai{width:44px;height:44px;flex:0 0 44px;border-radius:14px;display:flex;
   align-items:center;justify-content:center;font-size:18px;background:var(--teal-soft)}
 .acti .ab{min-width:0;flex:1}
 .acti .ab b{display:block;font-size:13px;font-weight:500;line-height:1.4}
 .acti .ab small{color:var(--text3);font-size:11.5px}
 .acti .at{color:var(--text3);font-size:11.5px;white-space:nowrap}
 .actmore{margin-top:12px;width:100%;height:40px;border:1px solid var(--line);
   border-radius:var(--r-ctl);background:none;color:var(--text2);font-size:13px;
   cursor:pointer}
 .actmore:hover{border-color:var(--teal);color:var(--teal-d)}
 .thist{margin-top:14px;padding-top:12px;border-top:1px solid var(--line2)}
 .thist .th-t{font-size:11px;letter-spacing:.06em;text-transform:uppercase;
   color:var(--text3);font-weight:600;margin-bottom:8px}
 .thist .th-r{font-size:12.5px;color:var(--text2);padding:4px 0;display:flex;gap:10px}
 .thist .th-r span{color:var(--text3);flex:0 0 76px}
 /* подсказка зуба — одна на всю дугу, летает за курсором */
 .toothtip{display:none;position:absolute;z-index:60;width:220px;border-radius:16px;
   padding:16px 18px;background:var(--panel);border:1px solid var(--line);
   box-shadow:0 18px 40px rgba(15,23,42,.12);font-size:13px;pointer-events:none}
 .toothtip b.tt-n{font-size:14.5px;font-weight:600;display:block}
 .toothtip .tt-s{color:var(--teal-d);font-weight:600;font-size:12.5px;margin:2px 0 8px}
 .toothtip .tt-d{color:var(--text2);font-size:12.5px;line-height:1.65}
 .toothtip .tt-d b{color:var(--text);font-weight:600}
 .toothtip .tt-note{margin-top:8px;padding-top:8px;border-top:1px solid var(--line2);
   color:var(--text2)}
 .plan-row .pdue{width:104px;flex:0 0 104px;font-size:12px;color:var(--text2)}
 /* ---------- раздел «Medici» (v1.9.0) ---------- */
 .medgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
 .medcard{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--sh);padding:16px 18px;
   display:flex;flex-direction:column;gap:10px;text-decoration:none;color:inherit;
   transition:box-shadow .15s,transform .15s}
 a.medcard:hover{box-shadow:var(--sh2);transform:translateY(-1px)}
 .medcard.off{opacity:.72}
 .medhead{display:flex;align-items:center;gap:12px}
 .avatar{width:52px;height:52px;flex:0 0 52px;border-radius:14px;color:#fff;overflow:hidden;
   display:flex;align-items:center;justify-content:center;font-size:17px;font-weight:600}
 .avatar img{width:100%;height:100%;object-fit:cover;display:block}
 .avatar.big{width:96px;height:96px;flex:0 0 96px;border-radius:18px;font-size:30px}
 .medhead b{font-size:15px;display:block;line-height:1.25}
 .medhead small{color:var(--text2);font-size:11.5px;display:block}
 .medmeta{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--text2)}
 .medstats{display:flex;gap:10px;border-top:1px solid var(--line2);padding-top:9px}
 .medstats div{flex:1;min-width:0}
 .medstats b{display:block;font-size:16px;font-weight:600}
 .medstats span{font-size:11px;color:var(--text3)}
 .dbadge{font-size:10px;font-weight:600;letter-spacing:.04em;padding:3px 8px;border-radius:6px;
   text-transform:uppercase;white-space:nowrap}
 .dbadge.activ{background:var(--green-soft);color:var(--green-t)}
 .dbadge.concediu{background:var(--amber-soft);color:var(--amber-t)}
 .dbadge.arhivat{background:var(--line2);color:var(--text3)}
 .svcpick{display:flex;flex-direction:column;gap:2px;max-height:320px;overflow:auto}
 .svcpick label{display:flex;align-items:center;gap:8px;font-size:12.5px;padding:5px 6px;
   border-radius:8px;cursor:pointer}
 .svcpick label:hover{background:var(--bg)}
 .svcpick input{margin:0}
 .svcpick small{margin-left:auto;color:var(--text3);font-size:11px;white-space:nowrap}
 /* ---------- недельный вид ---------- */
 .week{display:flex;gap:12px;align-items:flex-start}
 .wcol{flex:1;min-width:0;background:var(--panel);border:1px solid var(--line);
   border-radius:var(--r-card);box-shadow:var(--sh);overflow:hidden}
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
   /* прячем ПОДПИСЬ, но не знак: раньше селектор бил по всем div внутри
      .brand и в узком окне (min_size 960) шапка оставалась пустой */
   .side .brand .txt,.side .sec,.side nav a span,.side nav a .dot,.side .sfoot{display:none}
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
    "med": "<path d='M8 3v4a4 4 0 0 0 8 0V3'/><path d='M12 11v3a4.5 4.5 0 0 0 9 0v-1'/>"
           "<circle cx='20.5' cy='11' r='1.6'/>",
    "stat": "<path d='M4 20h16M8 20v-6M13 20V7M18 20v-9'/>",
    "set": "<circle cx='12' cy='12' r='3'/><path d='M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M18 6l-2 2M8 16l-2 2'/>",
    "bot": "<rect x='3.5' y='7.5' width='17' height='12' rx='3'/><path d='M12 7.5V4'/><circle cx='9' cy='13.5' r='1' fill='currentColor' stroke='none'/><circle cx='15' cy='13.5' r='1' fill='currentColor' stroke='none'/>",
    "qr": "<rect x='4' y='4' width='6.5' height='6.5' rx='1'/><rect x='13.5' y='4' width='6.5' height='6.5' rx='1'/><rect x='4' y='13.5' width='6.5' height='6.5' rx='1'/><path d='M13.5 13.5h6.5v6.5h-6.5z'/>",
    # якоря строк профиля пациента (макет 08-03)
    "phone": "<path d='M6.5 3.5h3l1.5 4-2 1.2a12 12 0 0 0 5.3 5.3l1.2-2 4 1.5v3a1.5 1.5 0 0 1-1.7 1.5C10.6 17.4 6.6 13.4 5 5.2A1.5 1.5 0 0 1 6.5 3.5z'/>",
    "mail": "<rect x='3' y='5.5' width='18' height='13' rx='2.5'/><path d='m3.8 7 8.2 6 8.2-6'/>",
    "pin": "<path d='M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11z'/><circle cx='12' cy='10' r='2.6'/>",
    "id": "<rect x='2.8' y='5' width='18.4' height='14' rx='2.5'/><circle cx='9' cy='11' r='2'/>"
          "<path d='M5.6 16.2c.7-1.6 2-2.3 3.4-2.3s2.7.7 3.4 2.3M15 10h4M15 13.5h4'/>",
    "shield": "<path d='M12 3l7 3v5.5c0 4.3-3 7.6-7 9.5-4-1.9-7-5.2-7-9.5V6z'/>",
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
  <div class="brand">{brand.mark_svg(34, 'logo')}
    <div class="txt"><b>DentPilot</b><small title="{html.escape(eng.CLINIC_NAME)}">{html.escape(eng.CLINIC_NAME)}</small></div>
  </div>
  <nav>
    <div class="sec">Meniu</div>
    {item('dash', '/admin', 'home', 'Dashboard')}
    {item('prog', '/admin/all', 'cal', 'Programări')}
    {item('pat', '/admin/search', 'pat', 'Pacienți')}
    {item('med', '/admin/medici', 'med', 'Medici')}
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


def _setup_hint() -> str:
    """Пока профиль клиники — нетронутый шаблон, об этом надо говорить прямо.
    Иначе «Clinica mea» и «Medic 1» тихо доживают до первого пациента, а бот
    называет их вслух."""
    if not eng.CONFIG.get("template"):
        return ""
    return ("<div class='banner err' style='margin-bottom:14px'>"
            "Programul încă are datele de exemplu. "
            "<a href='/admin/settings'><b>Completați datele clinicii</b></a> — "
            "denumire, telefon, medici, servicii și program de lucru. "
            "Până atunci botul le spune pacienților exact ce scrie aici.</div>")


def _shell(body: str, sub: str, active: str = "dash", bell: int | None = None) -> str:
    fb_subject = urllib.parse.quote(
        f"Feedback DentPilot — {eng.CLINIC_NAME} (v{eng.APP_VERSION})")
    fb_body = urllib.parse.quote("Ideea / problema mea:\n\n")
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/favicon.ico">
<title>{html.escape(eng.CLINIC_NAME)} — registru</title><style>{PANEL_CSS}</style></head><body>
{_sidebar(active)}
<div class="main">
{_topbar(bell)}
<div class="content">
<h1><a href="/admin">{html.escape(eng.CLINIC_NAME)} — registrul clinicii</a></h1>
<div class="sub">{sub}{_sec_warn()} · v{eng.APP_VERSION}</div>
{_setup_hint()}
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
function pickName(inp){{
  var out=document.getElementById(inp.id+'_n');
  if(!out) return;
  var f=inp.files&&inp.files[0];
  out.textContent=f?f.name:'niciun fișier ales';
  out.classList.toggle('on',!!f);
}}
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
    starts, covered = active
    for h in hours:
        out.append(f"<tr><td class='hour'>{h:02d}:00</td>")
        for dk, dname in doctors_items:
            rs = starts.get((dk, h)) or starts.get((dname, h)) or []
            if not rs:
                if (dk, h) in covered or (dname, h) in covered:
                    # час накрыт длинным визитом — «+» тут врал бы
                    out.append("<td><div class='appt busy'>⏳ ocupat</div></td>")
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


SETUP_TMPL = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__CLINIC__ — PIN</title><style>
 body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#0E9F8A;display:flex;
      align-items:center;justify-content:center;height:100vh;margin:0}
 form{background:#fff;padding:30px 32px;border-radius:18px;box-shadow:0 18px 40px rgba(15,23,42,.25);
      display:flex;flex-direction:column;gap:12px;width:340px}
 h1{font-size:19px;color:#162033;margin:0;font-weight:600;letter-spacing:-.02em}
 p{color:#7E8B9C;font-size:13px;margin:0;line-height:1.5}
 input{padding:12px;border:1px solid #E7EDF5;border-radius:12px;font-size:26px;
       text-align:center;letter-spacing:12px;outline:none;color:#162033}
 input:focus{border-color:#0E9F8A;box-shadow:0 0 0 3px rgba(14,159,138,.12)}
 button{background:#0E9F8A;color:#fff;border:none;border-radius:12px;height:48px;
        font-size:15px;font-weight:600;cursor:pointer;transition:background-color .2s ease}
 button:hover{background:#0B7E6D}
 .err{color:#B91C1C;font-size:13px}
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


def _due_html(due, status: str) -> str:
    """Срок позиции плана. Просроченное незавершённое подсвечиваем — иначе
    дата в таблице ничем не отличается от любой другой даты."""
    if not due:
        return "—"
    try:
        d = date.fromisoformat(str(due)[:10])
    except ValueError:
        return "—"
    txt = d.strftime("%d.%m.%Y")
    if status != "finalizat" and d < datetime.now(eng.TZ).date():
        return (f"<span style='color:var(--red-t);font-weight:600' "
                f"title='Termen depășit'>⚠ {txt}</span>")
    return txt


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


# ---------- карточка пациента (v1.6.0) ----------

TOOTH_STATES = {
    "ok": "Sănătos", "carie": "Carie", "obturatie": "Obturație",
    "coroana": "Coroană", "implant": "Implant", "tratament": "În tratament",
    "extras": "Extras", "lipsa": "Lipsă",
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
    visits = await db.patient_appointments(pid, 1000)
    acts = await db.patient_activity(pid, 60)
    tooth_acts = await db.tooth_activity(pid)
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

    def frow(label: str, val, icon: str = "") -> str:
        ic = f"<span class='ic'>{_ic(icon)}</span>" if icon else "<span class='ic'></span>"
        return (f"<div class='frow'><span>{label}</span>"
                f"<span class='v'>{e(str(val)) if val else '—'}</span>{ic}</div>")

    info_rows = (frow("Telefon", p.get("phone"), "phone")
                 + frow("Data nașterii", p.get("birth_date") or p.get("birth_year"), "cal")
                 + frow("Gen", {"m": "M", "f": "F"}.get(p.get("gender") or "", p.get("gender")), "pat")
                 + frow("IDNP", p.get("idnp"), "id")
                 + frow("E-mail", p.get("email"), "mail")
                 + frow("Adresă", p.get("address"), "pin")
                 + frow("Asigurare", p.get("insurance"), "shield")
                 + frow("Medic curant", p.get("primary_doctor"), "med")
                 + frow("Pacient din",
                        p["created_at"].astimezone(eng.TZ).strftime("%d.%m.%Y"), "cal"))
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
    def tooth_div(n: int, lower: bool = False) -> str:
        t = tmap.get(n)
        st = t["state"] if t else "ok"
        note = t["note"] if t else ""
        title = f"{n} · {TOOTH_STATES.get(st, st)}" + (f" · {note}" if note else "")
        num = f"<span class='num'>{n}</span>"
        svg = tsvg.tooth_svg(n, st, width=38, interactive=True)
        # номер всегда со стороны КОРНЕЙ: у верхней дуги сверху, у нижней снизу —
        # так цифры не лезут в межчелюстной зазор и читаются как в макете
        return (f"<button type='button' class='tooth-btn' title=\"{e(title)}\" "
                f"onclick='openTooth({n})' onmouseenter='toothTip(event,{n})' "
                f"onmouseleave='toothTipOff()' onfocus='toothTip(event,{n})' "
                f"onblur='toothTipOff()'>{svg + num if lower else num + svg}</button>")

    upper = "".join(tooth_div(n) for n in _FDI_UPPER)
    lower = "".join(tooth_div(n, lower=True) for n in _FDI_LOWER)
    # легенда показывает НАСТОЯЩИЙ зуб в каждом состоянии, а не цветной квадрат:
    # так видно, чем «коронка» отличается от «пломбы», без словаря
    legend = "".join(
        f"<span class='lg'>{tsvg.tooth_svg(36, k, width=20)} {v}</span>"
        for k, v in TOOTH_STATES.items() if k != "ok")
    # .replace("</", ...) — чтобы note вида "</script>..." не вырвался из тега
    def _tinfo(n: int) -> dict:
        t = tmap.get(n)
        if not t:
            return {"state": "ok", "note": "", "doctor": "", "at": ""}
        return {"state": t["state"], "note": t["note"] or "",
                "doctor": t["doctor"] or "",
                "at": t["updated_at"].astimezone(eng.TZ).strftime("%d.%m.%Y")
                      if t["updated_at"] else ""}

    hist_by_tooth: dict[str, list] = {}
    for a in tooth_acts:
        at = a["at"].astimezone(eng.TZ) if hasattr(a["at"], "astimezone") else None
        hist_by_tooth.setdefault(str(a["tooth"]), []).append(
            {"at": at.strftime("%d.%m.%Y") if at else "", "text": a["text"]})
    teeth_json = json.dumps({str(n): _tinfo(n) for n in _FDI_UPPER + _FDI_LOWER},
                            ensure_ascii=False).replace("</", "<\\/")
    thist_json = json.dumps(hist_by_tooth, ensure_ascii=False).replace("</", "<\\/")
    state_opts = "".join(f"<option value='{k}'>{v}</option>" for k, v in TOOTH_STATES.items())
    state_ro_json = json.dumps(TOOTH_STATES, ensure_ascii=False)
    teeth_card = f"""<div class='fcard'>
<h3>Formula dentară <small>· notație FDI · click pe dinte</small></h3>
<div class='arch-wrap'>
  <div class='arch'>{upper}</div>
  <div class='arch-mid'></div>
  <div class='arch lower'>{lower}</div>
</div>
<div class='tleg'>{legend}</div></div>
<div id='toothtip' class='toothtip'><b class='tt-n'></b><div class='tt-s'></div>
  <div class='tt-d'></div></div>
<dialog id='toothdlg'>
  <div class='dlg-head'><span id='t_title'>Dinte</span>
    <button type='button' onclick="document.getElementById('toothdlg').close()">✕</button></div>
  <form class='dlg-form' method='post' action='{base}/tooth'>
    <input type='hidden' name='tooth' id='t_num'>
    <select name='state' id='t_state'>{state_opts}</select>
    <select name='doctor' id='t_doc'><option value=''>Medic —</option>{doc_opts}</select>
    <input name='note' id='t_note' placeholder='Notiță (opțional)' maxlength='120'>
    <button>💾 Salvează</button>
  </form>
  <div id='t_hist' class='thist'></div>
</dialog>
<script>
const TEETH = {teeth_json};
const STATE_RO = {state_ro_json};
const THIST = {thist_json};
function openTooth(n) {{
  const t = TEETH[String(n)] || {{state: 'ok', note: '', doctor: ''}};
  document.getElementById('t_title').textContent = 'Dinte ' + n;
  document.getElementById('t_num').value = n;
  document.getElementById('t_state').value = t.state;
  document.getElementById('t_doc').value = t.doctor || '';
  document.getElementById('t_note').value = t.note;
  const h = THIST[String(n)] || [];
  document.getElementById('t_hist').innerHTML = h.length
    ? '<div class="th-t">Istoria dintelui</div>' + h.map(function (x) {{
        return '<div class="th-r"><span>' + x.at + '</span>' + x.text + '</div>';
      }}).join('')
    : '';
  document.getElementById('toothdlg').showModal();
}}
// подсказка зуба: одна плавающая карточка на всю дугу, позиционируется у зуба
const TIP = document.getElementById('toothtip');
function toothTip(ev, n) {{
  const t = TEETH[String(n)];
  if (!t || (t.state === 'ok' && !t.note && !t.doctor)) {{ TIP.style.display = 'none'; return; }}
  TIP.querySelector('.tt-n').textContent = 'Dinte ' + n;
  TIP.querySelector('.tt-s').textContent = STATE_RO[t.state] || t.state;
  TIP.querySelector('.tt-d').innerHTML =
    (t.at ? '<div>Actualizat: <b>' + t.at + '</b></div>' : '') +
    (t.doctor ? '<div>Medic: <b>' + t.doctor + '</b></div>' : '') +
    (t.note ? '<div class="tt-note">' + t.note + '</div>' : '');
  const r = ev.currentTarget.getBoundingClientRect();
  TIP.style.display = 'block';
  const w = TIP.offsetWidth;
  let left = r.left + r.width / 2 - w / 2 + window.scrollX;
  left = Math.max(8, Math.min(left, document.documentElement.clientWidth - w - 8));
  TIP.style.left = left + 'px';
  TIP.style.top = (r.bottom + window.scrollY + 8) + 'px';
}}
function toothTipOff() {{ TIP.style.display = 'none'; }}
</script>"""

    plan_rows = []
    total = 0
    for it in plan:
        if it["price_mdl"] and it["status"] != "finalizat":
            total += it["price_mdl"]
        nxt = _PLAN_NEXT[it["status"] if it["status"] in _PLAN_NEXT else "planificat"]
        plan_rows.append(
            f"<div class='plan-row' data-st='{e(it['status'])}'>"
            f"<span class='pt'>{it['tooth'] or '—'}</span>"
            f"<span class='pp'>{e(it['procedure'])}</span>"
            f"<span class='pd'>{e(it['doctor'] or '—')}</span>"
            f"<span class='pdue'>{_due_html(it.get('due_date'), it['status'])}</span>"
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
    cnt = {k: sum(1 for it in plan if it["status"] == k)
           for k in ("planificat", "in_lucru", "finalizat")}
    tabs = ("<div class='tabs'>"
            f"<button class='on' data-f='all' onclick='planTab(this)'>Toate ({len(plan)})</button>"
            f"<button data-f='in_lucru' onclick='planTab(this)'>În lucru ({cnt['in_lucru']})</button>"
            f"<button data-f='planificat' onclick='planTab(this)'>Planificate ({cnt['planificat']})</button>"
            f"<button data-f='finalizat' onclick='planTab(this)'>Finalizate ({cnt['finalizat']})</button>"
            "</div>")
    plan_card = f"""<div class='fcard' id='plan'>
<h3>Plan de tratament <small>· plan activ (nefinalizat): {f'{total:,}'.replace(',', ' ')} MDL</small></h3>
{tabs}
{plan_html}
<div class='ptotal'><span>Total plan activ</span><b>{f'{total:,}'.replace(',', ' ')} MDL</b></div>
<form class='fform' method='post' action='{base}/plan' style='margin-top:10px'>
  <div class='r2'><select name='tooth' style='width:90px'>{tooth_opts}</select>
  <input name='procedure' placeholder='Procedură (ex. Coroană zirconiu)' maxlength='120' required></div>
  <div class='r2'><select name='doctor'><option value=''>Medic —</option>{doc_opts}</select>
  <input name='price' type='number' min='0' max='1000000' placeholder='Preț MDL' style='width:130px'></div>
  <div class='r2'><input type='date' name='due_date' title='Termen planificat'>
  <span style='font-size:12px;color:var(--text3);align-self:center'>termen (opțional)</span></div>
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

    doc_meta: dict = {}

    def doc_card(dd) -> str:
        # картинку показываем ею же: файлы лежат локально, отдельный рендер
        # миниатюр — оптимизация следующего этапа, а не условие работы
        mime = dd["mime"] or ""
        is_img = mime.startswith("image/")
        thumb = (f"<img src='/admin/doc/{dd['id']}?thumb=1' alt='' loading='lazy'>" if is_img
                 else (DOC_CATEGORIES.get(dd["category"], "📄").split()[0]))
        when = dd["uploaded_at"].astimezone(eng.TZ).strftime("%d.%m.%Y")
        kb = dd["size"] // 1024
        size = f"{kb} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"
        # чем открывать файл: свой просмотрщик (растр, PDF) или программа
        # Windows. href остаётся прежним — без JS карточка просто скачает файл
        doc_meta[dd["id"]] = {
            "name": dd["filename"],
            "view": ("img" if mime in _INLINE_MIME
                     else "pdf" if mime in _PDF_MIME else "ext"),
        }
        return (f"<div class='doccard'><a href='/admin/doc/{dd['id']}' "
                f"onclick='return openDoc({dd['id']})' "
                f"title='{e(dd['filename'])}'><div class='thumb'>{thumb}</div>"
                f"<div class='dmeta'><b>{e(dd['filename'])}</b>"
                f"<small>{when} · {size}</small></div></a>"
                f"<div class='del'><form method='post' action='{base}/doc/{dd['id']}/del' "
                f"onsubmit=\"return confirm('Ștergeți documentul?')\">"
                f"<button title='Șterge'>✕</button></form></div></div>")

    _ACT_ICON = {"appt_new": "📅", "appt_status": "✅", "appt_cancel": "❌",
                 "tooth": "🦷", "plan_add": "➕", "plan_status": "🔄",
                 "plan_del": "➖", "doc_add": "📎", "doc_del": "🗑",
                 "alert_add": "⚠️", "profile": "✏️", "archive": "🗄"}
    act_rows = []
    for a in acts:
        at = a["at"].astimezone(eng.TZ) if hasattr(a["at"], "astimezone") else None
        when = at.strftime("%d.%m.%Y") if at else ""
        hhmm = at.strftime("%H:%M") if at else ""
        who = "🤖 bot" if a["actor"] == "bot" else "🎧 recepție"
        act_rows.append(
            f"<div class='acti'><span class='ai'>{_ACT_ICON.get(a['kind'], '•')}</span>"
            f"<div class='ab'><b>{e(a['text'])}</b>"
            f"<small>{when} · {who}</small></div><span class='at'>{hhmm}</span></div>")
    shown, rest = act_rows[:10], act_rows[10:]
    more = (f"<div id='actmore' style='display:none'>{''.join(rest)}</div>"
            f"<button type='button' class='actmore' onclick=\"var m=document.getElementById('actmore');"
            f"m.style.display='block';this.remove()\">Toate evenimentele ({len(acts)})</button>"
            if rest else "")
    act_card = (f"<div class='fcard'><h3>Istoric activitate "
                f"<small>· ce s-a întâmplat cu fișa</small></h3>"
                + ("".join(shown) + more if act_rows
                   else "<p class='hint' style='margin:0'>— încă fără evenimente —</p>")
                + "</div>")

    docs_rows = ("<div class='docgrid'>" + "".join(doc_card(dd) for dd in docs) + "</div>"
                 if docs else "<p class='hint' style='margin:0 0 8px'>— fără documente —</p>")
    cat_opts = "".join(
        f"<option value='{k}'{' selected' if k == 'alt' else ''}>{v}</option>"
        for k, v in DOC_CATEGORIES.items())
    docs_card = f"""<div class='fcard' id='docs'><h3>Documente și imagini <small>· max {MAX_DOC_MB} MB</small></h3>
{docs_rows}
<form class='fform' method='post' action='{base}/doc' enctype='multipart/form-data'>
  <select name='category'>{cat_opts}</select>
  <div class='filepick'>
    <input type='file' name='file' id='docfile' required onchange='pickName(this)'>
    <label for='docfile'>📎 Alege fișierul</label>
    <span class='fname' id='docfile_n'>niciun fișier ales</span>
  </div>
  <button>⬆️ Încarcă document</button>
</form>
<p class='hint' style='margin-top:8px'>Click pe fișier — pozele și PDF-urile se deschid aici,
restul în programul potrivit (Word, Excel). Fișierele rămân local, în folderul
programului (data\\files).</p></div>"""

    # ---- hero: кто перед врачом, одним взглядом ----
    # бейджи собираются из УЖЕ имеющихся данных: алерты, страховка, импланты
    pills = []
    if p.get("archived"):
        pills.append("<span class='pill grey'>🗄 Arhivat</span>")
    else:
        pills.append("<span class='pill green'>✔ Pacient activ</span>")
    for a in alerts[:3]:
        tone = {"allergy": "orange", "medication": "orange",
                "warning": "red"}.get(a["kind"], "grey")
        icon = _ALERT_KINDS.get(a["kind"], "ℹ️").split()[0]
        pills.append(f"<span class='pill {tone}'>{icon} {e(a['text'][:38])}</span>")
    if p.get("insurance"):
        pills.append(f"<span class='pill green'>🛡 {e(p['insurance'][:28])}</span>")
    n_impl = sum(1 for t in tmap.values() if t["state"] == "implant")
    if n_impl:
        pills.append(f"<span class='pill purple'>⚙ {n_impl} implant"
                     f"{'e' if n_impl > 1 else ''}</span>")

    past = [v for v in visits if v["starts_at"] <= now and v["status"] != "cancelled"]
    lastv = max(past, key=lambda v: v["starts_at"]) if past else None

    def hs(label: str, val: str, sub: str = "") -> str:
        tail = (f"<div style='color:var(--text3);font-size:12px'>{sub}</div>" if sub else "")
        return f"<div class='hs'><span>{label}</span><b>{val}</b>{tail}</div>"

    acts = []
    if p.get("phone"):
        acts.append(f"<a href='tel:{e(p['phone'])}'>{_ic('phone')} Sună</a>")
    if p.get("email"):
        acts.append(f"<a href='mailto:{e(p['email'])}'>{_ic('mail')} E-mail</a>")
    # запись делается ДЛЯ ЭТОГО пациента и прямо здесь: прежняя ссылка вела в
    # общий журнал дня, где имя и телефон надо было вбивать заново
    acts.append(f"<button type='button' onclick='openAppt()'>"
                f"{_ic('cal')} Programează</button>")

    # ID — внутренний номер фиши в программе (адрес страницы, бэкап, обращение
    # в поддержку). Клинике он нужен редко, поэтому уходит в конец строки и
    # копируется одним кликом, а не переспрашивается голосом.
    id_chip = (f"<span class='idchip' onclick='copyId(this)' data-id='{pid}' "
               f"title='Numărul intern al fișei în program (adresa paginii, "
               f"copiile de siguranță, suport). Click = copiază'>ID #{pid}</span>")
    meta_bits = [f"{age} ani" if age else "", chan,
                 f"dosar {e(p['file_no'])}" if p.get("file_no") else "",
                 "Pacient din " + p["created_at"].astimezone(eng.TZ).strftime("%Y"),
                 id_chip]
    hero = f"""<div class='hero'>
  <div class='hero-av'>{e(_initials(p['name'] or '?'))}</div>
  <div class='hero-id'>
    <h2>{e(p['name'] or '—')}</h2>
    <div class='hero-meta'>{''.join(f'<span>{x}</span>' for x in meta_bits if x)}</div>
    <div class='hero-badges'>{''.join(pills)}</div>
    <div class='hero-acts'>{''.join(acts)}</div>
  </div>
  <div class='hero-side'>
    {hs('Ultima vizită',
        lastv['starts_at'].astimezone(eng.TZ).strftime('%d.%m.%Y') if lastv else '—',
        e(lastv['service']) if lastv else 'încă fără vizite')}
    {hs('Medic curant', e(p.get('primary_doctor') or '—'),
        'din fișa pacientului' if p.get('primary_doctor') else 'nesetat')}
  </div>
</div>"""

    # ---- KPI: пять цифр, которые спрашивают первыми ----
    n_active = sum(1 for it in plan if it["status"] != "finalizat")
    n_done = sum(1 for it in plan if it["status"] == "finalizat")
    days_ago = ((now.date() - lastv["starts_at"].astimezone(eng.TZ).date()).days
                if lastv else None)
    # каждая цифра кликабельна и открывает ТОТ САМЫЙ список, из которого она
    # посчитана: цифра без расшифровки заставляет верить журналу на слово
    def _vrow(v) -> str:
        dtv = v["starts_at"].astimezone(eng.TZ)
        return (f"<div class='lrow'><span class='lk'>{dtv.strftime('%d.%m.%Y · %H:%M')}</span>"
                f"<b>{e(v['service'])}</b><small>{e(v['doctor'])} · "
                f"{STATUS_LABEL.get(v['status'], v['status'])}</small></div>")

    def _prow(it) -> str:
        price = (f"{it['price_mdl']:,}".replace(",", " ") + " MDL") if it["price_mdl"] else "—"
        return (f"<div class='lrow'><span class='lk'>"
                f"{('dinte ' + str(it['tooth'])) if it['tooth'] else '—'}</span>"
                f"<b>{e(it['procedure'])}</b><small>{e(it['doctor'] or '—')} · "
                f"{_PLAN_LABEL.get(it['status'], it['status'])} · {price}</small></div>")

    def _empty(txt: str) -> str:
        return f"<p class='hint' style='margin:0'>— {txt} —</p>"

    def _lmore(href: str, txt: str) -> str:
        return f"<a class='lmore' href='{href}' onclick='closeKpi()'>{txt} →</a>"

    live_visits = [v for v in visits if v["status"] != "cancelled"]
    canc = len(visits) - len(live_visits)
    act_items = [it for it in plan if it["status"] != "finalizat"]
    done_items = [it for it in plan if it["status"] == "finalizat"]
    kpi_panels = {
        "visits": ("Toate vizitele",
                   ("".join(_vrow(v) for v in live_visits) or _empty("încă fără vizite"))
                   + (f"<p class='hint'>+ {canc} anulate (nu se numără)</p>" if canc else "")),
        "active": ("Proceduri active",
                   ("".join(_prow(it) for it in act_items) or _empty("planul este gol"))
                   + _lmore("#plan", "Deschide planul de tratament")),
        "last": ("Ultima vizită",
                 (_vrow(lastv) + (f"<p class='hint'>acum {days_ago} zile</p>"
                                  if days_ago else "<p class='hint'>astăzi</p>"))
                 if lastv else _empty("încă fără vizite")),
        "next": ("Următoarea vizită",
                 _vrow(nextv) if nextv else
                 (_empty("nicio vizită programată")
                  + "<button type='button' class='lbtn' "
                    "onclick='closeKpi();openAppt()'>📅 Programează acum</button>")),
        "done": ("Proceduri finalizate",
                 "".join(_prow(it) for it in done_items)
                 or _empty("încă nimic finalizat")),
    }
    kpis = [
        ("visits", "📋", len(live_visits), "Vizite în total",
         "din " + p["created_at"].astimezone(eng.TZ).strftime("%Y")),
        ("active", "🦷", n_active, "Proceduri active", "în planul de tratament"),
        ("last", "🕐", (f"{days_ago} zile" if days_ago else "azi") if lastv else "—",
         "Ultima vizită",
         lastv["starts_at"].astimezone(eng.TZ).strftime("%d.%m.%Y") if lastv else "—"),
        ("next", "📅", nextv["starts_at"].astimezone(eng.TZ).strftime("%d.%m") if nextv else "—",
         "Următoarea vizită",
         nextv["starts_at"].astimezone(eng.TZ).strftime("%H:%M") if nextv else "neprogramat"),
        ("done", "✅", n_done, "Proceduri finalizate", "istoric complet"),
    ]
    kpi_html = "<div class='kpi5'>" + "".join(
        f"<button type='button' class='kpi' onclick=\"openKpi('{key}')\" "
        f"title='{lbl} — click pentru detalii'>"
        f"<span class='ki'>{ic}</span><div style='min-width:0'>"
        f"<b>{val}</b><span>{lbl}</span><small>{sub}</small></div></button>"
        for key, ic, val, lbl, sub in kpis) + "</div>"

    arch_label = ("↩️ Scoate din arhivă" if p.get("archived")
                  else "🗄 Arhivează pacientul")
    profile_card = f"""<div class='fcard'><h3>Date pacient</h3>
{info_rows}{notes_html}
<button style='width:100%;margin-top:12px;background:none;border:1px solid var(--line);
  border-radius:var(--r-ctl);height:var(--h-ctl);cursor:pointer;font-size:14px;
  font-weight:600;color:var(--text2)'
  onclick="var f=document.getElementById('pedit');f.style.display=f.style.display==='none'?'flex':'none'">
  ✏️ Editează profilul</button>
{edit_form}
<form method='post' action='{base}/archive' style='margin-top:8px'>
  <input type='hidden' name='on' value='{"0" if p.get("archived") else "1"}'>
  <button style='background:none;border:1px solid var(--line);border-radius:var(--r-ctl);
    height:40px;cursor:pointer;font-size:13px;color:var(--text3);width:100%'>
    {arch_label}</button>
</form></div>"""

    quick = f"""<div class='fcard'><h3>Acțiuni rapide</h3><div class='qa'>
  <button type='button' onclick='openAppt()'>➕ Vizită nouă</button>
  <a href='#plan'>🦷 Plan de tratament</a>
  <a href='#docs'>📷 Încarcă document</a>
  <button type='button' onclick="openNote()">📝 Notiță</button>
  <button type='button' onclick="window.print()">🖨 Printează fișa</button>
</div></div>"""

    # ---- окно записи ДЛЯ ЭТОГО пациента ----
    # услуга решает, кто из врачей её выполняет; дата и врач решают, какие часы
    # свободны — часы тянем у того же движка, что обслуживает бота
    ap_svc_docs = {k: [dk for dk, _n in eng.allowed_doc_items(k)] for k in eng.SERVICES}
    ap_prim = next((dk for dk, n in eng.ACTIVE_DOCTORS.items()
                    if n == (p.get("primary_doctor") or "")), "")
    ap_svc_opts = "".join(f"<option value='{k}'>{e(v['ro'])}</option>"
                          for k, v in eng.SERVICES.items())
    today_iso = now.date().isoformat()
    kpi_json = json.dumps(kpi_panels, ensure_ascii=True).replace("</", "<\\/")
    docs_json = json.dumps(doc_meta, ensure_ascii=True).replace("</", "<\\/")
    dialogs = f"""<dialog id='apptdlg'>
  <div class='dlg-head'><span>📅 Programare — {e(p['name'] or '—')}</span>
    <button type='button' onclick="document.getElementById('apptdlg').close()">✕</button></div>
  <form class='dlg-form' method='post' action='{base}/appoint'>
    <label class='dlab'>Serviciu
      <select name='aservice' id='ap_svc' onchange='apRefresh(1)'>{ap_svc_opts}</select></label>
    <label class='dlab'>Medic
      <select name='adoctor' id='ap_doc' onchange='apRefresh(0)'></select></label>
    <label class='dlab'>Data
      <input type='date' name='adate' id='ap_date' value='{today_iso}'
        min='{today_iso}' onchange='apRefresh(0)'></label>
    <label class='dlab'>Ora — doar intervalele libere
      <select name='atime' id='ap_time' required></select></label>
    <p class='hint' id='ap_hint' style='margin:0'></p>
    <button id='ap_go'>Adaugă programarea</button>
  </form>
</dialog>
<dialog id='kpidlg' class='wide'>
  <div class='dlg-head'><span id='kpi_t'>—</span>
    <button type='button' onclick='closeKpi()'>✕</button></div>
  <div class='lbody' id='kpi_b'></div>
</dialog>
<dialog id='docdlg' class='wide'>
  <div class='dlg-head'><span id='dv_t'>—</span>
    <button type='button' onclick="document.getElementById('docdlg').close()">✕</button></div>
  <div class='dvbody' id='dv_b'></div>
  <div class='dvacts'>
    <button type='button' onclick='sysOpen(DV_ID)'>🖥 Deschide în alt program</button>
    <a id='dv_dl' href='#'>⬇️ Salvează pe disc</a>
  </div>
</dialog>"""

    body = f"""{banner}
<div class='nav'><a href='/admin/search'>← Pacienți</a>
<a href='/admin/all'>📋 Programări</a></div>
{hero}
{kpi_html}
<div class='pv2'>
  <div class='pv2-main'>{teeth_card}{plan_card}{docs_card}{quick}</div>
  <div class='pv2-side'>{next_html}{act_card}{profile_card}{alerts_card}{hist_card}</div>
</div>
{dialogs}
<script>
const BASE = "{base}";
const AP_DOCS = {json.dumps(ap_svc_docs, ensure_ascii=True)};
const AP_NAMES = {json.dumps(dict(eng.ACTIVE_DOCTORS), ensure_ascii=True)};
const AP_PRIM = "{ap_prim}";
const KPI = {kpi_json};
const DOCS = {docs_json};
let DV_ID = 0;
let AP_SEQ = 0;
// ---- запись прямо из фиши: пациент известен, спрашиваем только визит ----
function openAppt() {{
  document.getElementById('apptdlg').showModal();
  apRefresh(1);
}}
function apRefresh(rebuild) {{
  var svc = document.getElementById('ap_svc').value;
  var sel = document.getElementById('ap_doc');
  if (rebuild) {{
    var keep = sel.value, list = AP_DOCS[svc] || [];
    sel.innerHTML = '';
    list.forEach(function (k) {{
      var o = document.createElement('option');
      o.value = k; o.textContent = AP_NAMES[k] || k; sel.appendChild(o);
    }});
    if (list.indexOf(keep) >= 0) sel.value = keep;
    else if (list.indexOf(AP_PRIM) >= 0) sel.value = AP_PRIM;
  }}
  var t = document.getElementById('ap_time'), hint = document.getElementById('ap_hint');
  var go = document.getElementById('ap_go'), d = document.getElementById('ap_date').value;
  t.innerHTML = ''; go.disabled = true;
  if (!sel.value) {{ hint.textContent = 'Niciun medic activ pentru acest serviciu.'; return; }}
  hint.textContent = 'Caut orele libere…';
  // Меняя услугу/врача/дату подряд, легко оставить два запроса в полёте. Оба
  // писали в один список, и он склеивался из ЛЮБЫХ двух ответов независимо от
  // порядка прихода: список с подписью «только свободные часы» показывал часы
  // чужого дня или чужого врача. Пишет только самый свежий запрос.
  var seq = ++AP_SEQ;
  fetch(BASE + '/slots?date=' + encodeURIComponent(d) + '&doctor=' +
        encodeURIComponent(sel.value) + '&service=' + encodeURIComponent(svc))
    .then(function (r) {{ return r.json(); }})
    .then(function (j) {{
      if (seq !== AP_SEQ) return;
      var s = j.slots || [];
      t.innerHTML = '';
      s.forEach(function (x) {{
        var o = document.createElement('option');
        o.value = x; o.textContent = x; t.appendChild(o);
      }});
      hint.textContent = s.length
        ? s.length + ' intervale libere în această zi'
        : 'Nicio oră liberă — alegeți altă zi sau alt medic.';
      go.disabled = !s.length;
    }})
    .catch(function () {{
      if (seq !== AP_SEQ) return;
      hint.textContent = 'Nu am putut încărca orele libere.';
    }});
}}
// ---- цифра → список, из которого она посчитана ----
function openKpi(k) {{
  var p = KPI[k];
  if (!p) return;
  document.getElementById('kpi_t').textContent = p[0];
  document.getElementById('kpi_b').innerHTML = p[1];
  document.getElementById('kpidlg').showModal();
}}
function closeKpi() {{ document.getElementById('kpidlg').close(); }}
function copyId(el) {{
  if (navigator.clipboard) navigator.clipboard.writeText(el.dataset.id);
  var was = el.textContent;
  el.textContent = 'copiat ✔';
  setTimeout(function () {{ el.textContent = was; }}, 1200);
}}
// ---- документ открываем, а не скачиваем ----
function openDoc(id) {{
  var d = DOCS[id];
  if (!d) return true;                     // нет данных — пусть сработает ссылка
  if (d.view === 'ext') {{ sysOpen(id); return false; }}
  DV_ID = id;
  document.getElementById('dv_t').textContent = d.name;
  document.getElementById('dv_dl').href = '/admin/doc/' + id;
  document.getElementById('dv_b').innerHTML = (d.view === 'img')
    ? '<img src="/admin/doc/' + id + '?inline=1" alt="">'
    : '<iframe src="/admin/doc/' + id + '?inline=1"></iframe>';
  document.getElementById('docdlg').showModal();
  return false;
}}
// Word/Excel и прочее открывает Windows; облачный журнал так не умеет —
// там честно откатываемся на скачивание
function sysOpen(id) {{
  fetch('/admin/doc/' + id + '/open', {{method: 'POST'}})
    .then(function (r) {{ return r.json(); }})
    .then(function (j) {{ if (!j.ok) location.href = '/admin/doc/' + id; }})
    .catch(function () {{ location.href = '/admin/doc/' + id; }});
}}
document.getElementById('docdlg').addEventListener('close', function () {{
  document.getElementById('dv_b').innerHTML = '';
}});
function planTab(btn) {{
  document.querySelectorAll('.tabs button').forEach(function (b) {{
    b.classList.toggle('on', b === btn);
  }});
  var f = btn.dataset.f;
  document.querySelectorAll('.plan-row').forEach(function (r) {{
    r.style.display = (f === 'all' || r.dataset.st === f) ? '' : 'none';
  }});
}}
function openNote() {{
  var f = document.getElementById('pedit');
  f.style.display = 'flex';
  f.scrollIntoView({{behavior: 'smooth', block: 'center'}});
  var t = f.querySelector('textarea[name=notes]');
  if (t) t.focus();
}}
</script>"""
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


@app.get("/admin/patient/{pid}/slots")
async def patient_slots(request: Request, pid: int,
                        date_q: str = Query("", alias="date"),
                        doctor: str = "", service: str = ""):
    """Свободные старты у врача на дату — для окна записи прямо из фиши.
    Тот же eng.free_starts, что у бота: одна правда о занятости на всех."""
    if (deny := _guard(request)) is not None:
        return deny
    if doctor not in eng.DOCTORS or service not in eng.SERVICES:
        return JSONResponse({"slots": []})
    try:
        d = date.fromisoformat(date_q)
    except ValueError:
        return JSONResponse({"slots": []})
    allowed = [k for k, _n in eng.allowed_doc_items(service)]
    if doctor not in allowed:
        return JSONResponse({"slots": []})  # услугу этот врач не выполняет
    free = await eng.free_starts(doctor, d, eng.svc_duration(service), allowed)
    return JSONResponse({"slots": [x.strftime("%H:%M") for x in free]})


@app.post("/admin/patient/{pid}/appoint")
async def patient_appoint(request: Request, pid: int,
                          adate: str = Form(...), atime: str = Form(...),
                          adoctor: str = Form(...), aservice: str = Form(...)):
    """Запись из фиши: пациент берётся по id страницы, а не по имени/телефону
    из формы — визит физически не может уехать однофамильцу."""
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    try:
        d = date.fromisoformat(adate)
        hh, mm = atime.split(":")
        dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return _card_redirect(pid, "bad")
    doctor = eng.DOCTORS.get(adoctor)
    svc = eng.SERVICES.get(aservice)
    if not doctor or not svc or dt.minute not in (0, 30):
        return _card_redirect(pid, "bad")
    if not eng.DOCTOR_META.get(adoctor, {}).get("active", True):
        return _card_redirect(pid, "bad")   # выключенному врачу не пишем
    if adoctor not in [k for k, _n in eng.allowed_doc_items(aservice)]:
        return _card_redirect(pid, "bad")
    # окно даёт только свободные будущие часы, но вкладку могли открыть утром:
    # к обеду её список устарел и без этой проверки визит уехал бы в прошлое
    if eng.is_past(dt):
        return _card_redirect(pid, "past")
    dur = eng.svc_duration(aservice)
    if not eng.fits_clinic(dt, dur):
        return _card_redirect(pid, "outside")
    r = await db.add_visit_for_patient(pid, svc["ro"], doctor, dt,
                                       doctor_id=adoctor, service_id=aservice,
                                       duration_min=dur)
    return _card_redirect(pid, "ok" if isinstance(r, int)
                          else ("dup" if r == "dup" else "conflict"))


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
                        state: str = Form(...), note: str = Form(""),
                        doctor: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    if tooth not in _FDI_UPPER + _FDI_LOWER or state not in TOOTH_STATES:
        return _card_redirect(pid, "bad_card")
    # врача принимаем только из справочника: свободный текст тут — будущий
    # «Иванов»/«Иванова» в истории зуба
    doc = doctor.strip() if doctor.strip() in set(eng.DOCTORS.values()) else ""
    await db.set_tooth(pid, tooth, state, note.strip()[:120], doc)
    return _card_redirect(pid, "ok_card")


@app.post("/admin/patient/{pid}/plan")
async def patient_plan_add(request: Request, pid: int, tooth: str = Form(""),
                           procedure: str = Form(...), doctor: str = Form(""),
                           price: str = Form(""), due_date: str = Form("")):
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
    due = due_date.strip()[:10]
    try:
        date.fromisoformat(due) if due else None
    except ValueError:
        due = ""
    await db.add_plan_item(pid, t, procedure.strip()[:120], doctor.strip()[:80],
                           pr, due)
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


# растровые картинки, которые безопасно отдавать inline (для превью в фише).
# ⛔ SVG и HTML сюда НЕ входят: файл с того же origin, показанный inline, — это
# чужой скрипт в нашем журнале.
_INLINE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
# PDF смотрим внутри программы (в WebView2 свой просмотрщик), но множество
# отдельное: миниатюры и <img> остаются только у растра.
_PDF_MIME = {"application/pdf"}
THUMB_PX = 320          # с запасом под ретину: карточка показывает 150x120


def _thumb_path(stored: str) -> pathlib.Path:
    return pathlib.Path(stored).with_suffix(pathlib.Path(stored).suffix + ".thumb.jpg")


def _make_thumb(stored: str) -> pathlib.Path | None:
    """Миниатюра рядом с оригиналом. Панорамный снимок бывает на 8 МБ — гонять
    его в карточку целиком (а их там десяток) незачем. Не вышло — не беда:
    вызывающий покажет оригинал."""
    src = pathlib.Path(stored)
    dst = _thumb_path(stored)
    if dst.exists():
        return dst
    if not src.exists():
        return None
    try:
        from PIL import Image
        with Image.open(src) as im:
            im.draft("RGB", (THUMB_PX * 2, THUMB_PX * 2))   # ускоряет JPEG вдвое
            im = im.convert("RGB")
            im.thumbnail((THUMB_PX, THUMB_PX))
            im.save(dst, "JPEG", quality=82, optimize=True)
        return dst
    except Exception as e:                    # noqa: BLE001 — битый файл, экзотика
        log.warning("thumb %s: %r", src.name, e)
        return None


@app.get("/admin/doc/{doc_id}")
async def patient_doc_get(request: Request, doc_id: int, inline: str = "",
                          thumb: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    d = await db.get_document(doc_id)
    if not d or not pathlib.Path(d["stored_path"]).exists():
        return RedirectResponse("/admin/search", status_code=303)
    mime = d["mime"] or "application/octet-stream"
    if thumb and mime in _INLINE_MIME:
        t = _make_thumb(d["stored_path"])
        if t:
            return FileResponse(t, media_type="image/jpeg")
        return FileResponse(d["stored_path"], media_type=mime)   # откат
    if inline and mime in _INLINE_MIME | _PDF_MIME:
        # без filename= отдаётся inline; с ним браузер считает файл вложением.
        # nosniff: mime приходит от клиента при загрузке, и без запрета браузер
        # волен «передумать» и исполнить .html, залитый как application/pdf
        return FileResponse(d["stored_path"], media_type=mime,
                            headers={"X-Content-Type-Options": "nosniff"})
    return FileResponse(d["stored_path"], filename=d["filename"], media_type=mime)


def _open_copy(src: pathlib.Path, filename: str) -> pathlib.Path:
    """Копия документа под ЧИТАЕМЫМ именем — для открытия внешней программой.
    На диске файлы лежат под случайным hex (a1b2c3.docx), и Word показал бы
    клинике именно его. Это кэш, а не второе хранилище: копии старше суток
    удаляем, оригинал остаётся единственным."""
    room = (_data_dir() or pathlib.Path("data")) / "open"
    room.mkdir(parents=True, exist_ok=True)
    now = datetime.now().timestamp()
    for old in room.iterdir():
        try:
            if old.is_dir() and now - old.stat().st_mtime > 86400:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_",
                  pathlib.Path(filename or "document").name)[:120] or "document"
    dst_dir = room / src.stem            # stem = случайный hex, уже уникален
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / safe
    # Копию НЕ обновляем, если она уже есть. Оригинал пишется ровно один раз
    # (при загрузке) и больше не меняется — значит разойтись копия с ним может
    # только по одной причине: врач открыл её в Word и что-то дописал. Прежняя
    # проверка «размер не совпал → перезалить» затирала бы ровно эту работу.
    # Обрывок недокопированного файла тут тоже возможен, но он сам исчезнет на
    # суточной уборке выше, а стёртая правка не возвращается ничем.
    if not dst.exists():
        shutil.copyfile(src, dst)
    return dst


# Что разрешено отдавать чужой программе одним кликом: документы, изображения,
# снимки. Загрузка документов пропускает ЛЮБОЕ расширение (regex .[a-z0-9]{1,9}),
# то есть .exe/.bat/.ps1 ложатся в фишу наравне с .pdf. Пока по файлу кликали
# ради скачивания, это была просто копия на диске; открытие через Windows
# превратило бы один клик в запуск принесённой программы. Всё, чего нет в
# списке, уезжает в скачивание — файл клинике доступен, но не исполняется.
_OPEN_EXT = {
    ".pdf", ".txt", ".rtf", ".csv",
    ".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic",
    ".dcm", ".stl", ".ply", ".obj",          # снимки КЛКТ и модели сканера
}


@app.post("/admin/doc/{doc_id}/open")
async def patient_doc_open(request: Request, doc_id: int):
    """Открыть документ программой этого же компьютера (Word, Excel, просмотр
    фото). Только настольное издание и только локальный запрос: журнал не
    должен запускать программы на компьютере клиники по команде из сети."""
    if (deny := _guard(request)) is not None:
        return deny
    host = request.client.host if request.client else ""
    if os.name != "nt" or host not in ("127.0.0.1", "::1"):
        return JSONResponse({"ok": False, "err": "not_local"})
    d = await db.get_document(doc_id)
    if not d or not pathlib.Path(d["stored_path"]).exists():
        return JSONResponse({"ok": False, "err": "missing"})
    src = pathlib.Path(d["stored_path"])
    if src.suffix.lower() not in _OPEN_EXT:
        return JSONResponse({"ok": False, "err": "ext"})
    try:
        # startfile не блокирует: ShellExecute возвращает управление сразу,
        # не дожидаясь, пока Word нарисует окно
        os.startfile(_open_copy(src, d["filename"]))
    except OSError as ex:                     # нет ассоциации у расширения и т.п.
        log.warning("startfile doc=%s: %r", doc_id, ex)
        return JSONResponse({"ok": False, "err": "os"})
    return JSONResponse({"ok": True})


@app.post("/admin/patient/{pid}/doc/{doc_id}/del")
async def patient_doc_del(request: Request, pid: int, doc_id: int):
    if (deny := _guard(request)) is not None:
        return deny
    d = await db.get_document(doc_id)
    if d and d["patient_id"] == pid:
        pathlib.Path(d["stored_path"]).unlink(missing_ok=True)
        _thumb_path(d["stored_path"]).unlink(missing_ok=True)
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
    if not doctor or not svc or not name or len(digits) < 8:
        return _back_redirect(back, adate, "bad")
    if not eng.DOCTOR_META.get(adoctor, {}).get("active", True):
        return _back_redirect(back, adate, "bad")  # выключенному врачу не пишем
    if dt.minute not in (0, 30):
        return _back_redirect(back, adate, "bad")  # 30-мин сетка стартов
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
