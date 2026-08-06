"""Фиша пациента: профиль, зубная формула, план лечения, документы, запись.

Первый модуль, уехавший из main.py целиком. Внутри — пятнадцать маршрутов:
сама страница `/admin/patient/{pid}`, действия над ней и документы (они живут
на отдельных адресах `/admin/doc/…`, но принадлежат карточке — файл пациента
без карточки смысла не имеет).

Правило границы: отсюда можно обращаться в `core` (каркас страницы, вход) и в
`db`/`engine`, но НИКОГДА в main.py — иначе замкнётся круг: main подключает
этот роутер, а роутер требовал бы main.

Внутреннего деления на service/repository пока нет намеренно. Сейчас это
перенос без единой переписанной строки — так видно, что поведение не менялось.
Дробить содержимое (страница на 660 строк — очевидный кандидат) стоит отдельным
шагом, когда за спиной уже есть зелёный прогон на новом месте.
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import os
import pathlib
import re
import secrets
import shutil
import tempfile
import urllib.parse
from datetime import date, datetime, timedelta

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from starlette.background import BackgroundTask

from ... import db
from ... import engine as eng
from ... import teeth_svg as tsvg
from . import export as pexport
from ...core.auth import _guard
from ...core.layout import (LIVE_STATUSES, MSG_BANNER, STATUS_LABEL, _age, _ic,
                            _initials, _shell)
from ...core.storage import _data_dir

log = logging.getLogger("patients")
router = APIRouter()


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


@router.get("/admin/patient/{pid}", response_class=HTMLResponse)
async def admin_patient(request: Request, pid: int, msg: str = "", views: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    e = html.escape
    # журнал доступа (закон 195): КТО открывал карту — такое же требование,
    # как «кто менял». В ленте фиши эти записи не показываются
    # (patient_activity их прячет), но живут в данных и уходят в выгрузку.
    await db.log_event(pid, "view", "Fișa deschisă")
    alerts = await db.patient_alerts(pid)
    tmap = await db.teeth_map(pid)
    plan = await db.plan_items(pid)
    docs = await db.documents(pid)
    visits = await db.patient_appointments(pid, 1000)
    # ?views=1 — журнал доступа НА ЭКРАНЕ: лента дополняется просмотрами
    # (view/doc_view). По умолчанию их нет — рецепция открывает фишу десятки
    # раз в день; но по клику журнал обязан показываться, иначе «программа
    # ведёт журнал доступа» — заявление, которое нечем предъявить проверке.
    show_views = views == "1"
    acts = await db.patient_activity(pid, 60, include_views=show_views)
    tooth_acts = await db.tooth_activity(pid)
    erasure = await db.erasure_kind(pid)
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
                 "alert_add": "⚠️", "profile": "✏️", "archive": "🗄",
                 # выдача копии данных — событие, о котором спросят на проверке;
                 # в общей ленте оно обязано быть заметным, а не точкой по умолчанию
                 "export": "📦",
                 "view": "👁", "doc_view": "👁", "erase": "🧹"}
    act_rows = []
    for a in acts:
        at = a["at"].astimezone(eng.TZ) if hasattr(a["at"], "astimezone") else None
        when = at.strftime("%d.%m.%Y") if at else ""
        hhmm = at.strftime("%H:%M") if at else ""
        # с ролями подпись — это ИМЯ вошедшего; «recepție» осталось у событий,
        # записанных до учёток, и у фоновых задач, где человека нет
        who = ("🤖 bot" if a["actor"] == "bot"
               else f"🎧 {e(a['actor'] or 'recepție')}")
        act_rows.append(
            f"<div class='acti'><span class='ai'>{_ACT_ICON.get(a['kind'], '•')}</span>"
            f"<div class='ab'><b>{e(a['text'])}</b>"
            f"<small>{when} · {who}</small></div><span class='at'>{hhmm}</span></div>")
    shown, rest = act_rows[:10], act_rows[10:]
    more = (f"<div id='actmore' style='display:none'>{''.join(rest)}</div>"
            f"<button type='button' class='actmore' onclick=\"var m=document.getElementById('actmore');"
            f"m.style.display='block';this.remove()\">Toate evenimentele ({len(acts)})</button>"
            if rest else "")
    views_link = (
        f"<a href='{base}' style='font-size:12px;font-weight:400'>"
        f"ascunde accesările</a>" if show_views else
        f"<a href='{base}?views=1' style='font-size:12px;font-weight:400' "
        f"title='Jurnalul accesărilor — cine și când a deschis fișa (Legea 195)'>"
        f"👁 accesările</a>")
    act_card = (f"<div class='fcard'><h3>Istoric activitate "
                f"<small>· ce s-a întâmplat cu fișa</small> · {views_link}</h3>"
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
</form>
<a href='{base}/export' style='display:block;margin-top:8px;text-align:center;
  border:1px solid var(--line);border-radius:var(--r-ctl);height:40px;line-height:40px;
  font-size:13px;color:var(--text3);text-decoration:none'
  title='Copie completă a datelor — pentru cererea pacientului (Legea 195)'>
  📦 Descarcă datele pacientului</a>
{_erase_block(base, erasure)}</div>"""

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


def _erase_block(base: str, erasure: str) -> str:
    """Свёрнутая опасная зона в фише. Свёрнутая — потому что стирание нужно
    несколько раз в год, а стоять на виду рядом с «Editează» ему нельзя.
    Какая ветка достанется пациенту, честно написано ДО нажатия: «удалю всё»
    и «сотру личность, лечение останется» — разные обещания."""
    if erasure == "delete":
        what = ("Pacientul nu are înregistrări medicale — fișa va fi "
                "<b>ștearsă definitiv</b>, împreună cu programările.")
        btn = "Șterge definitiv"
    else:
        what = ("Pacientul are înregistrări medicale, pe care clinica e obligată "
                "să le păstreze. Se șterg <b>datele de identitate</b> (nume, "
                "telefon, IDNP, adresă…); tratamentul rămâne sub numărul fișei.")
        btn = "Șterge datele personale"
    return f"""<details style='margin-top:8px'>
  <summary style='font-size:12px;color:var(--text3);cursor:pointer'>
    Ștergerea datelor (Legea 195)</summary>
  <div style='border:1px solid var(--red-t,#B91C1C);border-radius:var(--r-ctl);
       padding:10px;margin-top:6px;font-size:12px;color:var(--text2)'>
    <p style='margin:0 0 8px'>{what} Acțiunea este <b>ireversibilă</b>.</p>
    <form method='post' action='{base}/erase'
          onsubmit="return confirm('Acțiunea este ireversibilă. Continuați?')">
      <input name='confirm' placeholder='scrieți STERG' required
             autocomplete='off' style='width:120px;text-transform:uppercase'>
      <button style='background:none;border:1px solid var(--red-t,#B91C1C);
        color:var(--red-t,#B91C1C);border-radius:var(--r-ctl);height:32px;
        padding:0 10px;cursor:pointer;font-size:12px'>{btn}</button>
    </form>
  </div></details>"""


@router.post("/admin/patient/{pid}/save")
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


@router.get("/admin/patient/{pid}/slots")
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


@router.post("/admin/patient/{pid}/appoint")
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
        return _card_redirect(pid, "bad_off")   # выключенному врачу не пишем
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


@router.post("/admin/patient/{pid}/archive")
async def patient_archive(request: Request, pid: int, on: str = Form("1")):
    """Архив = скрыть из списков; история и файлы остаются на месте."""
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    await db.set_archived(pid, on == "1")
    return _card_redirect(pid, "ok_card")


@router.post("/admin/patient/{pid}/alert")
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


@router.post("/admin/patient/{pid}/alert/{aid}/del")
async def patient_alert_del(request: Request, pid: int, aid: int):
    if (deny := _guard(request)) is not None:
        return deny
    await db.delete_alert(aid, pid)
    return _card_redirect(pid)


@router.post("/admin/patient/{pid}/tooth")
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


@router.post("/admin/patient/{pid}/plan")
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


@router.post("/admin/patient/{pid}/plan/{item_id}/status")
async def patient_plan_status(request: Request, pid: int, item_id: int,
                              to: str = Form(...)):
    if (deny := _guard(request)) is not None:
        return deny
    if to not in _PLAN_LABEL:
        return _card_redirect(pid, "bad_card")
    await db.set_plan_status(item_id, pid, to)
    return _card_redirect(pid)


@router.post("/admin/patient/{pid}/plan/{item_id}/del")
async def patient_plan_del(request: Request, pid: int, item_id: int):
    if (deny := _guard(request)) is not None:
        return deny
    await db.delete_plan_item(item_id, pid)
    return _card_redirect(pid)


@router.post("/admin/patient/{pid}/doc")
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


@router.get("/admin/doc/{doc_id}")
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
    # журнал доступа: открытие ДОКУМЕНТА (снимок, согласие) — отдельное событие.
    # Миниатюры выше не в счёт: их грузит сама карточка пачкой, это не «открыл
    # снимок», а «открыл фишу», и оно уже записано
    await db.log_event(d["patient_id"], "doc_view",
                       f"Document deschis: {d['filename']}")
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


@router.post("/admin/doc/{doc_id}/open")
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
    await db.log_event(d["patient_id"], "doc_view",
                       f"Document deschis: {d['filename']}")
    try:
        # startfile не блокирует: ShellExecute возвращает управление сразу,
        # не дожидаясь, пока Word нарисует окно
        os.startfile(_open_copy(src, d["filename"]))
    except OSError as ex:                     # нет ассоциации у расширения и т.п.
        log.warning("startfile doc=%s: %r", doc_id, ex)
        return JSONResponse({"ok": False, "err": "os"})
    return JSONResponse({"ok": True})


@router.post("/admin/patient/{pid}/erase")
async def patient_erase(request: Request, pid: int, confirm: str = Form("")):
    """Право на стирание. Ветку выбирает НЕ рецепция, а состояние фиши
    (db.erasure_kind): физическое удаление доступно только контакту без
    лечения, у пациента с медзаписями стирается личность, клиника остаётся.

    Подтверждение — переписанное слово, не галочка: действие необратимо, а
    кнопка стоит в фише рядом с обычными. confirm сверяется здесь, на сервере —
    JS-диалог легко проскочить двойным Enter.
    """
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    if confirm.strip().upper() != "STERG":
        return _card_redirect(pid, "bad_erase")
    kind = await db.erasure_kind(pid)
    if kind == "delete":
        # файлы удаляются ДО строк: наоборот, упади программа между шагами,
        # остались бы файлы-сироты без единой записи о том, чьи они
        docs = await db.documents_with_paths(pid)
        for d in docs:
            pathlib.Path(d["stored_path"]).unlink(missing_ok=True)
            _thumb_path(d["stored_path"]).unlink(missing_ok=True)
        shutil.rmtree(_files_dir(pid), ignore_errors=True)
        await db.delete_patient_fully(pid)
        return RedirectResponse("/admin/search?msg=ok_del", status_code=303)
    await db.anonymize_patient(pid)
    # событие — в летопись, которая у обезличенного остаётся: проверяющему
    # видно, что стирание состоялось и когда
    await db.log_event(pid, "erase", "Date personale șterse (anonimizare)")
    return _card_redirect(pid, "ok_anon")


@router.get("/admin/patient/{pid}/export")
async def patient_export(request: Request, pid: int):
    """Копия ВСЕХ данных пациента архивом — право на доступ и переносимость.

    Архив пишется во временную папку, а не в память: у пациента с историей
    рентгенов это десятки мегабайт, и держать их в ОЗУ ради одной выдачи
    незачем. Папка сносится фоновой задачей ПОСЛЕ того, как файл ушёл клиенту.

    ⚠️ Выдача копии — сама по себе событие обработки, и на проверке спросят
    именно её: кому и когда выдавали. Поэтому пишется в летопись пациента.
    """
    if (deny := _guard(request)) is not None:
        return deny
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_export_"))
    dest = tmp / "export.zip"
    try:
        data = await pexport.write_archive(pid, dest)
    except OSError as ex:                       # нет места, файл занят антивирусом
        log.warning("export pid=%s: %r", pid, ex)
        shutil.rmtree(tmp, ignore_errors=True)
        return _card_redirect(pid, "bad_export")
    if data is None:
        shutil.rmtree(tmp, ignore_errors=True)
        return RedirectResponse("/admin/search", status_code=303)
    await db.log_event(pid, "export", "Copie a datelor personale eliberată")
    return FileResponse(
        dest, filename=pexport.archive_name(data), media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@router.post("/admin/patient/{pid}/doc/{doc_id}/del")
async def patient_doc_del(request: Request, pid: int, doc_id: int):
    if (deny := _guard(request)) is not None:
        return deny
    d = await db.get_document(doc_id)
    if d and d["patient_id"] == pid:
        pathlib.Path(d["stored_path"]).unlink(missing_ok=True)
        _thumb_path(d["stored_path"]).unlink(missing_ok=True)
        await db.delete_document(doc_id, pid)
    return _card_redirect(pid)


# ---------- раздел «Pacienți»: список клиники (макет Олега 08-06) ----------
#
# Раньше страница была поиском: пустой запрос показывал 20 последних, а по
# запросу разворачивал КАЖДОМУ найденному всю историю визитов — двадцать
# таблиц на экране. Теперь это рабочий список (фильтры, страницы, боковой
# предпросмотр), а история осталась там, где ей место: в фише.

_PL_PER = (10, 20, 50)


_PL_INACTIVE_DAYS = 365


_PL_NEVER = datetime(1900, 1, 1, tzinfo=eng.TZ)   # «никогда не был» при сортировке


# Статуса пациента в базе НЕТ — он выводится из того, что уже есть: архив,
# медицинские предупреждения, незакрытый план, давность последнего визита.
# Порядок словаря = приоритет бейджа: первым показываем то, ради чего список
# вообще открывают. Фильтр по статусу, наоборот, ВКЛЮЧАЮЩИЙ (см. _pl_has_status):
# пациент с аллергией и незакрытым планом обязан находиться под обоими, хотя
# бейдж у него один.
_PL_BADGE = {
    "arhivat": ("Arhivat", "arh"),
    "atentie": ("Necesită atenție", "att"),
    "tratament": ("În tratament", "trt"),
    "inactiv": ("Inactiv", "off"),
    "activ": ("Activ", "act"),
}


_PL_CANAL = {"tg": "📱 Telegram", "manual": "✍️ recepție", "web": "🌐 web"}


def _pl_canal(p: dict) -> str:
    key = p.get("session_key") or ""
    return ("tg" if key.startswith("tg:")
            else "manual" if key.startswith("manual:") else "web")


def _pl_status(p: dict, now: datetime) -> str:
    if p.get("archived"):
        return "arhivat"
    if p["n_alerts"]:
        return "atentie"
    if p["n_plan"]:
        return "tratament"
    if _pl_stale(p, now):
        return "inactiv"
    return "activ"


def _pl_stale(p: dict, now: datetime) -> bool:
    last = p.get("last_at")
    return last is None or (now - last).days > _PL_INACTIVE_DAYS


def _pl_has_status(p: dict, st: str, now: datetime) -> bool:
    """Фильтр по статусу — включающий, а не «тот же приоритет, что у бейджа»."""
    if st == "arhivat":
        return bool(p.get("archived"))
    if st == "atentie":
        return bool(p["n_alerts"])
    if st == "tratament":
        return bool(p["n_plan"])
    if st == "inactiv":
        return _pl_stale(p, now)
    if st == "activ":
        return not _pl_stale(p, now)
    return True


def _pl_digits(s) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _pl_match_q(p: dict, q: str) -> bool:
    """Имя (без учёта диакритики), e-mail, номер дела — подстрокой; телефон —
    по цифрам, от трёх: '069 12' и '069-12' обязаны искать одинаково."""
    qf = db.fold(q)
    if len(qf) >= 2 and (qf in db.fold(p["name"]) or qf in db.fold(p["email"])
                         or qf in db.fold(p.get("file_no"))):
        return True
    digits = _pl_digits(q)
    return len(digits) >= 3 and digits in _pl_digits(p["phone"])


def _pl_doc(p: dict) -> str:
    """Врач в строке списка. Выведенный из последнего визита — приглушённо и с
    подсказкой: иначе он читается как «медик курант», которого никто не ставил."""
    if not p["doctor"]:
        return "—"
    name = html.escape(p["doctor"])
    if p["doctor_own"]:
        return name
    return (f"<span class='dim' title='Medicul ultimei vizite — în fișă nu este "
            f"setat un medic curant'>{name}</span>")


def _pl_dmy(v) -> str:
    """dd.mm.yyyy из datetime или из ISO-строки (birth_date хранится текстом)."""
    if not v:
        return "—"
    if isinstance(v, datetime):
        return v.astimezone(eng.TZ).strftime("%d.%m.%Y")
    try:
        return date.fromisoformat(str(v)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return "—"


async def _pl_rows(now: datetime) -> list[dict]:
    """Все пациенты клиники со сведёнными агрегатами. Четыре запроса на
    страницу — независимо от того, десять в списке строк или тысяча."""
    people = await db.all_patients(include_archived=True)
    vis = {r["patient_id"]: r for r in await db.patients_visits(now)}
    alerts = {r["patient_id"]: r["n"] for r in await db.patients_alert_counts()}
    plans = {r["patient_id"]: r["n"] for r in await db.patients_plan_counts()}
    docs = {r["patient_id"]: r["doctor"] for r in await db.patients_last_doctor()}
    out = []
    for p in people:
        v = vis.get(p["id"]) or {}
        row = dict(p)
        row.update({"last_at": v.get("last_at"), "next_at": v.get("next_at"),
                    "n_visits": v.get("n_visits") or 0,
                    "n_alerts": alerts.get(p["id"], 0),
                    "n_plan": plans.get(p["id"], 0)})
        # «Medic» = врач из фиши, а если его не проставили — тот, кто вёл
        # последний визит. doctor_own отличает одно от другого: выведенного
        # врача показываем приглушённо, чтобы он не читался как назначение.
        row["doctor"] = p["primary_doctor"] or docs.get(p["id"], "")
        row["doctor_own"] = bool(p["primary_doctor"])
        row["status"] = _pl_status(row, now)
        out.append(row)
    return out


def _pl_filter(rows: list[dict], now: datetime, q: str, med: str, st: str,
               ch: str, sort: str) -> list[dict]:
    """Отбор и порядок. Архивные скрыты, пока их не спросили явно — поиском
    или фильтром: фишу с историей лечения нельзя терять, её именно прячут."""
    out = []
    for p in rows:
        if p["archived"] and not q and st != "arhivat":
            continue
        if q and not _pl_match_q(p, q):
            continue
        if med == "-" and p["doctor"]:
            continue
        if med and med != "-" and p["doctor"] != med:
            continue
        if st and not _pl_has_status(p, st, now):
            continue
        if ch and _pl_canal(p) != ch:
            continue
        out.append(p)
    if sort == "name":
        out.sort(key=lambda p: db.fold(p["name"]))
    elif sort == "new":
        out.sort(key=lambda p: p["created_at"], reverse=True)
    else:   # по последнему визиту, кто ещё не был — в конце
        out.sort(key=lambda p: (p["last_at"] is not None, p["last_at"] or _PL_NEVER),
                 reverse=True)
    return out


def _pl_trend(cur: int, prev: int) -> str:
    """Сравнение с прошлым месяцем. Проценты от нуля не считаем: «+∞%» —
    не цифра, а шум."""
    if not prev:
        return (f"<span class='up'>+{cur}</span> față de luna trecută (0)"
                if cur else "la fel ca luna trecută (0)")
    pct = (cur - prev) * 100 / prev
    if abs(pct) < 0.5:
        return "la fel ca luna trecută"
    cls, arrow = ("up", "↑") if pct > 0 else ("dn", "↓")
    return f"<span class='{cls}'>{arrow} {abs(pct):.0f}%</span> față de luna trecută"


@router.get("/admin/search", response_class=HTMLResponse)
async def admin_search(request: Request, q: str = "", med: str = "", st: str = "",
                       ch: str = "", sort: str = "last", page: int = 1,
                       per: int = 20, msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    e = html.escape
    q = q.strip()[:60]
    sort = sort if sort in ("last", "name", "new") else "last"
    per = per if per in _PL_PER else 20
    now = datetime.now(eng.TZ)

    everyone = await _pl_rows(now)
    rows = _pl_filter(everyone, now, q, med, st, ch, sort)

    # ---- три числа над списком (карточки макета; денежной среди них нет) ----
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    next_start = (month_start + timedelta(days=32)).replace(day=1)
    appts = [r for r in await db.day_appointments(prev_start, next_start)
             if r["source"] != "note" and r["status"] != "cancelled"]
    n_appt = sum(1 for r in appts if r["starts_at"] >= month_start)
    n_appt_prev = len(appts) - n_appt
    n_total = sum(1 for p in everyone if not p["archived"])
    n_new = sum(1 for p in everyone if p["created_at"] >= month_start)
    n_new_prev = sum(1 for p in everyone if prev_start <= p["created_at"] < month_start)

    def tile(ico: str, tone: str, val, label: str, foot: str, href: str = "") -> str:
        inner = (f"<span class='ico {tone}'>{ico}</span><div class='pl-tv'>"
                 f"<span>{label}</span><b>{val}</b><small>{foot}</small></div>")
        return (f"<a class='pl-tile' href='{href}'>{inner}</a>" if href
                else f"<div class='pl-tile'>{inner}</div>")

    tiles = ("<div class='pl-tiles'>"
             + tile("👥", "g", f"{n_total:,}".replace(",", " "), "Total pacienți",
                    (f"<span class='up'>+{n_new}</span> luna aceasta" if n_new
                     else "niciun pacient nou luna aceasta"))
             + tile("🧑‍⚕️", "b", n_new, "Pacienți noi (luna aceasta)",
                    _pl_trend(n_new, n_new_prev))
             + tile("📅", "v", n_appt, "Programări (luna aceasta)",
                    _pl_trend(n_appt, n_appt_prev), href="/admin/stats")
             + "</div>")

    # ---- фильтры ----
    doc_names = sorted(set(eng.DOCTORS.values())
                       | {p["doctor"] for p in everyone if p["doctor"]})

    def opts(items, cur: str, zero: str) -> str:
        out = [f"<option value=''>{zero}</option>"]
        for val, label in items:
            sel = " selected" if val == cur else ""
            out.append(f"<option value='{e(val)}'{sel}>{e(label)}</option>")
        return "".join(out)

    base = {"q": q, "med": med, "st": st, "ch": ch, "sort": sort, "per": per}

    def url(**over) -> str:
        d = {k: v for k, v in {**base, **over}.items()
             if v not in ("", None, 0) and (k, v) != ("sort", "last")
             and (k, v) != ("per", 20)}
        qs = urllib.parse.urlencode(d)
        # адрес уходит прямо в href: '&' между параметрами обязан быть '&amp;',
        # иначе браузер вправе прочитать хвост как имя сущности
        return "/admin/search" + (f"?{qs.replace('&', '&amp;')}" if qs else "")

    dirty = any([q, med, st, ch]) or sort != "last" or per != 20
    reset = (f"<a class='pl-btn' href='/admin/search' title='Scoate toate filtrele'>"
             f"✕ Resetează</a>" if dirty else "")
    csv_url = "/admin/patients.csv" + url()[len("/admin/search"):]
    bar = f"""<form class='pl-bar' method='get' action='/admin/search'>
  <label class='pl-search'>{_ic('search')}
    <input name='q' value="{e(q)}" placeholder='Caută pacient, telefon, e-mail…'></label>
  <select name='med' onchange='this.form.submit()'>
    {opts([("-", "— fără medic —")] + [(n, n) for n in doc_names], med, "Toți medicii")}</select>
  <select name='st' onchange='this.form.submit()'>
    {opts([(k, v[0]) for k, v in _PL_BADGE.items()], st, "Toate statusurile")}</select>
  <select name='ch' onchange='this.form.submit()'>
    {opts(list(_PL_CANAL.items()), ch, "Toate canalele")}</select>
  <input type='hidden' name='sort' value='{sort}'>
  <input type='hidden' name='per' value='{per}'>
  <button class='pl-btn'>Caută</button>{reset}
  <span style='flex:1'></span>
  <a class='pl-btn' href='{csv_url}' title='Lista filtrată, ca fișier pentru Excel'>
    ⬇ Exportă</a>
  <button type='button' class='pl-btn primary' onclick='newPat()'>＋ Adaugă pacient</button>
</form>"""

    # ---- страница списка ----
    total = len(rows)
    pages = max(1, -(-total // per))
    page = max(1, min(page, pages))
    shown = rows[(page - 1) * per: page * per]

    def head(key: str, label: str) -> str:
        arrow = " ↓" if sort == key else ""
        return f"<th><a href='{url(sort=key, page=0)}'>{label}{arrow}</a></th>"

    trs = []
    for p in shown:
        label, cls = _PL_BADGE[p["status"]]
        age = _p_age(p)
        mail = (f"<small>{e(p['email'])}</small>" if p["email"]
                else f"<small class='dim'>{_PL_CANAL[_pl_canal(p)]}</small>")
        nxt = (f"<small class='nx' title='Următoarea vizită'>→ "
               f"{p['next_at'].astimezone(eng.TZ).strftime('%d.%m %H:%M')}</small>"
               if p["next_at"] else "")
        trs.append(
            f"<tr id='plr{p['id']}' onclick='peek({p['id']})'>"
            f"<td><div class='pl-who'><span class='pl-av'>{e(_initials(p['name'] or '?'))}</span>"
            f"<div class='pl-nm'><b>{e(p['name'] or '—')}</b>{mail}</div></div></td>"
            f"<td>{e(p['phone'] or '—')}</td>"
            f"<td class='pl-hide'>{_pl_dmy(p['birth_date'])}"
            f"{f'<small> · {age} ani</small>' if age else ''}</td>"
            f"<td>{_pl_doc(p)}</td>"
            f"<td>{_pl_dmy(p['last_at'])}{nxt}</td>"
            f"<td><span class='pl-badge {cls}'>{label}</span></td>"
            f"<td class='pl-acts'>"
            f"<button type='button' title='Previzualizare' "
            f"onclick='event.stopPropagation();peek({p['id']})'>👁</button>"
            f"<a href='/admin/patient/{p['id']}' title='Deschide fișa' "
            f"onclick='event.stopPropagation()'>📇</a></td></tr>")

    if shown:
        table = (f"<div class='pl-scroll'><table class='pl-tbl'><thead><tr>"
                 f"{head('name', 'Pacient')}<th>Telefon</th>"
                 f"<th class='pl-hide'>Data nașterii</th><th>Medic</th>"
                 f"{head('last', 'Ultima vizită')}<th>Status</th><th></th>"
                 f"</tr></thead><tbody>{''.join(trs)}</tbody></table></div>")
    elif q or med or st or ch:
        table = ("<div class='pl-empty'>🔍<b>Nimic găsit</b>"
                 "<span>Încercați alt nume, telefon sau scoateți filtrele.</span>"
                 f"<a class='pl-btn' href='/admin/search'>Vezi toți pacienții</a></div>")
    else:
        table = ("<div class='pl-empty'>👥<b>Încă niciun pacient</b>"
                 "<span>Fișele apar aici odată cu prima programare — "
                 "din registru sau din bot.</span>"
                 "<button type='button' class='pl-btn primary' onclick='newPat()'>"
                 "＋ Adaugă primul pacient</button></div>")

    first = (page - 1) * per + 1 if total else 0
    nums = []
    for n in range(1, pages + 1):
        if n in (1, pages) or abs(n - page) <= 1:
            cls = " on" if n == page else ""
            nums.append(f"<a class='pl-pg{cls}' href='{url(page=n)}'>{n}</a>")
        elif not nums or nums[-1] != "<span class='pl-gap'>…</span>":
            nums.append("<span class='pl-gap'>…</span>")
    prev_a = (f"<a class='pl-pg' href='{url(page=page - 1)}'>‹</a>" if page > 1
              else "<span class='pl-pg off'>‹</span>")
    next_a = (f"<a class='pl-pg' href='{url(page=page + 1)}'>›</a>" if page < pages
              else "<span class='pl-pg off'>›</span>")
    per_opts = "".join(f"<option value='{n}'{' selected' if n == per else ''}>"
                       f"{n} / pagină</option>" for n in _PL_PER)
    # у пустого списка «Afișare 0–0 din 0» и стрелки листания — только шум
    pager = (f"<div class='pl-pag'><span>Afișare {first}–{min(page * per, total)} "
             f"din {total} pacienți</span>"
             f"<div class='pl-pgs'>{prev_a}{''.join(nums)}{next_a}</div>"
             f"<form method='get' action='/admin/search'>"
             + "".join(f"<input type='hidden' name='{k}' value=\"{e(str(v))}\">"
                       for k, v in base.items() if v and k != "per")
             + f"<select name='per' onchange='this.form.submit()'>{per_opts}</select>"
             f"</form></div>") if total else ""

    banner = ""
    if msg in MSG_BANNER:
        cls, text = MSG_BANNER[msg]
        banner = f"<div class='banner {cls}'>{text}</div>"

    body = f"""{banner}
<div class='pl-head'><div><h2>Pacienți</h2>
  <p>Gestionează și caută pacienții clinicii</p></div></div>
{bar}
{tiles}
<div class='pl-grid'>
  <div class='pl-card'>{table}{pager}</div>
  <aside class='ppanel' id='ppanel'>
    <button type='button' class='pp-x' onclick='peekOff()' title='Închide'>✕</button>
    <div id='pp_body'><div class='pp-empty'>👁<span>Alegeți un pacient din listă
      pentru previzualizare — fără să părăsiți lista</span></div></div>
  </aside>
</div>
<div class='pp-veil' id='pp_veil' onclick='peekOff()'></div>
<dialog id='npdlg'>
  <div class='dlg-head'><span>＋ Pacient nou</span>
    <button type='button' onclick="document.getElementById('npdlg').close()">✕</button></div>
  <form class='dlg-form' method='post' action='/admin/patients/new'>
    <label class='dlab'>Nume și prenume
      <input name='name' maxlength='120' required autofocus></label>
    <label class='dlab'>Telefon
      <input name='phone' maxlength='40' placeholder='ex. 069 123 456'></label>
    <label class='dlab'>Data nașterii
      <input type='date' name='birth_date'></label>
    <label class='dlab'>E-mail
      <input type='email' name='email' maxlength='120'></label>
    <label class='dlab'>Medic curant
      <select name='primary_doctor'><option value=''>—</option>
        {"".join(f"<option>{e(n)}</option>" for n in eng.DOCTORS.values())}</select></label>
    <p class='hint' style='margin:0'>Fișa se deschide imediat după salvare —
      acolo completați dinții, planul și documentele. Pacientul cu același
      telefon nu se dublează.</p>
    <button>Adaugă pacientul</button>
  </form>
</dialog>
<script>
var PEEK = 0;
function peek(id) {{
  var body = document.getElementById('pp_body');
  document.querySelectorAll('.pl-tbl tr.on').forEach(function (r) {{
    r.classList.remove('on');
  }});
  var row = document.getElementById('plr' + id);
  if (row) row.classList.add('on');
  document.getElementById('ppanel').classList.add('open');
  document.getElementById('pp_veil').classList.add('on');
  body.innerHTML = '<div class="pp-empty"><span>Se încarcă…</span></div>';
  var seq = ++PEEK;
  fetch('/admin/patient/' + id + '/peek')
    .then(function (r) {{ return r.text(); }})
    .then(function (t) {{ if (seq === PEEK) body.innerHTML = t; }})
    .catch(function () {{
      if (seq === PEEK) body.innerHTML =
        '<div class="pp-empty"><span>Nu am putut încărca fișa.</span></div>';
    }});
}}
function peekOff() {{
  document.getElementById('ppanel').classList.remove('open');
  document.getElementById('pp_veil').classList.remove('on');
  document.querySelectorAll('.pl-tbl tr.on').forEach(function (r) {{
    r.classList.remove('on');
  }});
}}
function newPat() {{ document.getElementById('npdlg').showModal(); }}
document.addEventListener('keydown', function (ev) {{
  if (ev.key === 'Escape') peekOff();
}});
</script>"""
    return _shell(body, "pacienții clinicii · filtre, previzualizare, export",
                  active="pat")


@router.get("/admin/patient/{pid}/peek", response_class=HTMLResponse)
async def patient_peek(request: Request, pid: int):
    """Боковой предпросмотр фиши: то, ради чего регистратура открывала карточку
    и возвращалась назад — телефон, последний визит, план, аллергии, документы.
    Отдаётся куском разметки: список уже нарисован, перерисовывать его незачем."""
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return HTMLResponse("<div class='pp-empty'><span>Fișa nu mai există.</span></div>",
                            status_code=404)
    e = html.escape
    now = datetime.now(eng.TZ)
    alerts = await db.patient_alerts(pid)
    plan = await db.plan_items(pid)
    docs = await db.documents(pid)
    visits = await db.patient_appointments(pid, 1000)

    live = [v for v in visits if v["status"] != "cancelled"]
    past = [v for v in live if v["starts_at"] <= now]
    future = [v for v in visits if v["status"] in LIVE_STATUSES and v["starts_at"] > now]
    lastv = max(past, key=lambda v: v["starts_at"]) if past else None
    nextv = min(future, key=lambda v: v["starts_at"]) if future else None

    row = {**p, "n_alerts": len(alerts),
           "n_plan": sum(1 for it in plan if it["status"] != "finalizat"),
           "last_at": lastv["starts_at"] if lastv else None}
    label, cls = _PL_BADGE[_pl_status(row, now)]
    age = _p_age(p)

    def line(icon: str, val, href: str = "") -> str:
        if not val:
            return ""
        txt = f"<a href='{href}'>{e(str(val))}</a>" if href else e(str(val))
        return f"<div class='pp-row'><span class='ic'>{_ic(icon)}</span>{txt}</div>"

    birth = _pl_dmy(p.get("birth_date")) if p.get("birth_date") else (p.get("birth_year") or "")
    info = (line("phone", p.get("phone"), f"tel:{e(p['phone'] or '')}")
            + line("mail", p.get("email"), f"mailto:{e(p['email'] or '')}")
            + line("cal", f"{birth}" + (f" ({age} ani)" if age else "") if birth else "")
            + line("pin", p.get("address"))
            + line("shield", p.get("insurance"))
            + line("med", p.get("primary_doctor")
                   or (lastv["doctor"] if lastv else "")))

    last_block = ("<div class='pp-b'><div class='pp-t'>Ultima vizită"
                  f"<span>{_pl_dmy(lastv['starts_at'])}</span></div>"
                  f"<b>{e(lastv['service'])}</b><small>{e(lastv['doctor'])}</small></div>"
                  if lastv else
                  "<div class='pp-b'><div class='pp-t'>Ultima vizită</div>"
                  "<small>încă fără vizite</small></div>")
    next_block = (f"<div class='pp-b next'><div class='pp-t'>Următoarea vizită"
                  f"<span>{nextv['starts_at'].astimezone(eng.TZ).strftime('%d.%m.%Y · %H:%M')}"
                  f"</span></div><b>{e(nextv['service'])}</b>"
                  f"<small>{e(nextv['doctor'])}</small></div>" if nextv else "")

    plan_block = ""
    if plan:
        done = sum(1 for it in plan if it["status"] == "finalizat")
        paid = sum(it["price_mdl"] or 0 for it in plan if it["status"] == "finalizat")
        tot = sum(it["price_mdl"] or 0 for it in plan)
        pct = round(done * 100 / len(plan))
        money = (f"<small>{f'{paid:,}'.replace(',', ' ')} MDL / "
                 f"{f'{tot:,}'.replace(',', ' ')} MDL</small>" if tot else "")
        plan_block = (f"<div class='pp-b'><div class='pp-t'>Plan de tratament"
                      f"<span>{done} / {len(plan)} finalizate</span></div>"
                      f"<div class='statbar'><div style='width:{pct}%'></div></div>"
                      f"{money}</div>")

    notes = "".join(f"<div class='pp-note {e(a['kind'])}'>"
                    f"{_ALERT_KINDS.get(a['kind'], 'ℹ️')} {e(a['text'])}</div>"
                    for a in alerts)
    if p.get("notes"):
        notes += f"<div class='pp-note info'>📝 {e(p['notes'])}</div>"
    notes_block = (f"<div class='pp-b'><div class='pp-t'>Notițe</div>{notes}</div>"
                   if notes else "")

    docs_block = ""
    if docs:
        items = []
        for d in docs[:3]:
            kb = d["size"] // 1024
            size = f"{kb} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"
            items.append(f"<a class='pp-doc' href='/admin/doc/{d['id']}'>"
                         f"<span>📄</span><div><b>{e(d['filename'])}</b>"
                         f"<small>{_pl_dmy(d['uploaded_at'])} · {size}</small></div></a>")
        more = (f"<a class='pp-all' href='/admin/patient/{pid}#docs'>Vezi toate "
                f"({len(docs)})</a>" if len(docs) > 3 else "")
        docs_block = (f"<div class='pp-b'><div class='pp-t'>Documente{more}</div>"
                      + "".join(items) + "</div>")

    return HTMLResponse(f"""<div class='pp-head'>
  <span class='pp-av'>{e(_initials(p['name'] or '?'))}</span>
  <div class='pp-id'><b>{e(p['name'] or '—')}</b>
    <span class='pl-badge {cls}'>{label}</span></div>
</div>
<div class='pp-info'>{info}</div>
<a class='pl-btn' href='/admin/patient/{pid}'>✏️ Editează fișa</a>
{next_block}{last_block}{plan_block}{notes_block}{docs_block}
<div class='pp-foot'><span>{len(live)} vizite în total</span>
  <a class='pl-btn primary' href='/admin/patient/{pid}'>Vezi profilul complet →</a></div>""")


@router.get("/admin/patients.csv")
async def patients_csv(request: Request, q: str = "", med: str = "", st: str = "",
                       ch: str = "", sort: str = "last", per: int = 20,
                       page: int = 1):
    """Тот же список, что на экране, теми же фильтрами — файлом для Excel.
    Страницы намеренно игнорируются: выгружают ВЫБОРКУ, а не её первую сотню."""
    if (deny := _guard(request)) is not None:
        return deny
    now = datetime.now(eng.TZ)
    rows = _pl_filter(await _pl_rows(now), now, q.strip()[:60], med, st, ch, sort)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Nume", "Telefon", "E-mail", "Data nașterii", "Vârstă", "Gen",
                "Medic", "Nr. dosar", "Canal", "Status", "Ultima vizită",
                "Următoarea vizită", "Vizite", "Înregistrat"])
    for p in rows:
        w.writerow([
            p["name"] or "", p["phone"] or "", p["email"] or "",
            _pl_dmy(p["birth_date"]).replace("—", ""), _p_age(p) or "",
            (p["gender"] or "").upper(), p["doctor"],
            p["file_no"] or "", _PL_CANAL[_pl_canal(p)].split()[-1],
            _PL_BADGE[p["status"]][0], _pl_dmy(p["last_at"]).replace("—", ""),
            _pl_dmy(p["next_at"]).replace("—", ""), p["n_visits"],
            _pl_dmy(p["created_at"]),
        ])
    csv_text = "﻿" + buf.getvalue()   # BOM: иначе Excel ломает диакритику
    fname = f"pacienti_{now.date().isoformat()}.csv"
    return Response(csv_text.encode("utf-8"),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/admin/patients/new")
async def patient_new(request: Request, name: str = Form(""), phone: str = Form(""),
                      birth_date: str = Form(""), email: str = Form(""),
                      primary_doctor: str = Form("")):
    """Карточка без визита: пациента завели заранее (звонок, первичный приём).

    ⚠️ Ключ `manual:{цифры}` СКЛЕИВАЕТ пациентов по телефону — на то он и
    заведён, чтобы бот и регистратура не плодили двойников. Поэтому при
    совпадении мы открываем существующую фишу, а не создаём: `_upsert_patient`
    на конфликте перезаписал бы имя, и семейный номер тихо переименовал бы
    родителя в ребёнка."""
    if (deny := _guard(request)) is not None:
        return deny
    name = name.strip()[:120]
    if not name:
        return RedirectResponse("/admin/search?msg=bad_pat", status_code=303)
    phone = phone.strip()[:40]
    digits = _pl_digits(phone)
    if len(digits) >= 3:
        key = f"manual:{digits}"
        if (exist := await db.patient_id_by_key(key)) is not None:
            return _card_redirect(exist, "dup_pat")
    else:
        # без телефона склеивать не по чему — ключ уникальный, но того же вида:
        # весь остальной код узнаёт по нему «заведён на рецепции»
        key = f"manual:c{secrets.token_hex(5)}"
    bd, year = birth_date.strip()[:10], None
    if bd:
        try:
            year = date.fromisoformat(bd).year
        except ValueError:
            bd = ""
    pid = await db.create_patient(key, name, phone, year)
    data = {f: None for f in db.PATIENT_FIELDS}
    doc = primary_doctor.strip()
    data.update({"name": name, "phone": phone or None, "birth_date": bd or None,
                 "email": email.strip()[:120] or None,
                 "primary_doctor": doc if doc in set(eng.DOCTORS.values()) else None})
    await db.update_patient(pid, data)
    return _card_redirect(pid, "new_pat")
