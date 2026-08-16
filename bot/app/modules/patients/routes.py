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
from . import acord as pacord
from . import anamneza as panam
from . import export as pexport
from . import fisa043 as pfisa
from . import plan_acord as pplan
from . import visit as pvisit
from ...core import xlsx
from ...core.auth import PERM_MONEY, _guard, can, request_user, require
from ...core.layout import (ALERT_KINDS, LIVE_STATUSES, STATUS_LABEL, js_json,
                            _age, _ic, _initials, msg_banner, _shell)
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
                f"title='Termen depășit'>{_ic('sos')} {txt}</span>")
    return txt


# ---------- карточка пациента (v1.6.0) ----------

# ⚠️ Имена состояний зуба — ОДИН словарь на программу, как STATUS_LABEL у
# статусов визита: дословная копия жила здесь и в teeth_svg, а с 08-16 те же
# слова пишет в летопись db.set_tooth. Три копии разошлись бы молча — на
# соседних экранах у одного состояния завелось бы три имени.
TOOTH_STATES = tsvg.STATE_RO


_FDI_UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]


_FDI_LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]


# молочный прикус: те же квадранты, что и постоянный, но по пять зубов
_FDI_MILK_UPPER = [55, 54, 53, 52, 51, 61, 62, 63, 64, 65]


_FDI_MILK_LOWER = [85, 84, 83, 82, 81, 71, 72, 73, 74, 75]


_FDI_ALL = _FDI_UPPER + _FDI_LOWER + _FDI_MILK_UPPER + _FDI_MILK_LOWER


# поверхности зуба: буква → румынское название. Порядок как в записи «MOD»,
# принятой в карте: медиальная, окклюзионная, дистальная, потом щёчная и нёбная
TOOTH_SURFACES = {"M": "mezial", "O": "ocluzal", "D": "distal",
                  "V": "vestibular", "L": "lingual"}


# ⛔ Значения уходят в <option>, куда разметку положить нельзя, поэтому знак не
# заменён иконкой, а вынесен в СОСЕДНИЙ словарь. Раньше значок доставали из этой
# же строки через .split()[0] — приём держался на том, что первым словом стоит
# эмодзи, и молча сломался бы от любой правки текста.
# ⚠️ Сами подписи (ALERT_KINDS) живут в core/layout.py: те же слова нужны
# выгрузке по 195-му, а она routes.py импортировать не может — routes.py
# импортирует её. Здесь остаётся только словарь значков.
_ALERT_ICON = {"allergy": _ic("sos"), "medication": _ic("pill"),
               "warning": _ic("alarm"), "info": _ic("info")}


# справочник вопросов — в modules/patients/anamneza.py (его читают ещё печать
# и выгрузка; см. докстринг там про то, почему он не здесь)
ANAMNEZA_FLAGS = panam.FLAGS["ro"]
ANAMNEZA_TEXTS = panam.TEXTS


DOC_CATEGORIES = {"radiografie": "Radiografie", "acord": "Acord / contract",
                  "trimitere": "Trimitere", "alt": "Alt document"}
_DOC_ICON = {"radiografie": _ic("xray"), "acord": _ic("note"),
             "trimitere": _ic("mail"), "alt": _ic("file")}


# Переходы плана НАПРАВЛЕННЫЕ, а не по кругу (просьба Олега 08-07: кнопка
# «следующий статус» гоняла процедуру по кольцу, и финал воскресал в
# «Planificat» одним случайным кликом). Из финала есть ровно один тихий выход —
# «Redeschide» обратно в работу, для исправления ошибки; пути «финал →
# запланировано» не существует. Охрана в маршруте смотрит на пару (откуда,
# куда): устаревшая вкладка не пришлёт запрещённое ребро.
# ОТКАЗ (08-11) — не четвёртая ступень, а боковой выход: ст.13(5) Legea
# 263/2005 требует, чтобы отказ пациента остался В МЕДДОКУМЕНТАЦИИ с указанием
# возможных последствий, а не был вычеркнут. Поэтому отказаться можно и от
# запланированного, и из работы, а вернуться — только в «Planificat»: заново
# начатая после отказа процедура это новое решение пациента, а не продолжение
# старого. ⛔ Из «Finalizat» в «Refuzat» ребра нет: отказаться от сделанного
# нельзя, ошибку исправляет «Redeschide».
_PLAN_EDGES = {("planificat", "in_lucru"), ("in_lucru", "finalizat"),
               ("finalizat", "in_lucru"),
               ("planificat", "refuzat"), ("in_lucru", "refuzat"),
               ("refuzat", "planificat")}

# переход, у которого причина ОБЯЗАТЕЛЬНА: «отказался» без «от чего именно
# предупредили» — это не запись по ст.13(5), а пустая отметка
_PLAN_NEEDS_MOTIV = ("refuzat",)


_PLAN_LABEL = {"planificat": "Planificat", "in_lucru": "În lucru",
               "finalizat": "Finalizat", "refuzat": "Refuzat"}


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
    pays = await db.payments(pid)
    fin = await db.patient_finance(pid)
    docs = await db.documents(pid)
    visits = await db.patient_appointments(pid, 1000)
    recs = await db.visit_records_map(pid)
    anam = await db.anamneza(pid)
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

    banner = msg_banner(msg)

    # -- левая колонка: профиль --
    age = _p_age(p)
    chan = ("Telegram" if (p["session_key"] or "").startswith("tg:")
            else "recepție" if (p["session_key"] or "").startswith("manual:")
            else "web")
    meta = " · ".join(x for x in [f"{age} ani" if age else "", chan,
                                  f"dosar {e(p['file_no'])}" if p.get("file_no") else "",
                                  "arhivat" if p.get("archived") else ""] if x)

    def frow(label: str, val, icon: str = "") -> str:
        ic = f"<span class='ic'>{_ic(icon)}</span>" if icon else "<span class='ic'></span>"
        return (f"<div class='frow'><span>{label}</span>"
                f"<span class='v'>{e(str(val)) if val else '—'}</span>{ic}</div>")

    # дата рождения человеку — dd.mm.yyyy, а не сырой ISO из базы
    bd_h = (_pl_dmy(p["birth_date"]) if p.get("birth_date")
            else p.get("birth_year"))
    info_rows = (frow("Telefon", p.get("phone"), "phone")
                 + frow("Data nașterii", bd_h, "cal")
                 + frow("Gen", {"m": "M", "f": "F"}.get(p.get("gender") or "", p.get("gender")), "pat")
                 + frow("IDNP", p.get("idnp"), "id")
                 + frow("E-mail", p.get("email"), "mail")
                 + frow("Adresă", p.get("address"), "pin")
                 + frow("Asigurare", p.get("insurance"), "shield")
                 + frow("Medic curant", p.get("primary_doctor"), "med")
                 + frow("Pacient din",
                        p["created_at"].astimezone(eng.TZ).strftime("%d.%m.%Y"), "cal"))
    notes_html = (f"<div style='font-size:12px;color:var(--text2);background:var(--bg);"
                  f"border-radius:8px;padding:8px 10px;margin-top:8px'>{_ic('note')} {e(p['notes'])}</div>"
                  if p.get("notes") else "")

    doc_opts = "".join(f"<option value='{e(n)}'"
                       f"{' selected' if p.get('primary_doctor') == n else ''}>{e(n)}</option>"
                       for n in eng.DOCTORS.values())
    # отказ сохранения ПОКАЗЫВАЕТ виноватое поле: форма раскрыта, поле красное.
    # Баннер «Date invalide» без этого заставлял искать ошибку перебором
    bad_field = {"bad_card": "name", "bad_bd": "birth_date",
                 "bad_idnp": "idnp"}.get(msg, "")

    def _inv(field: str) -> str:
        return (" style='border-color:var(--red-t,#B91C1C);"
                "box-shadow:0 0 0 3px rgba(185,28,28,.12)'"
                if field == bad_field else "")

    edit_form = f"""
<form class='fform' id='pedit' method='post' action='{base}/save' style='display:{"block" if bad_field else "none"};margin-top:10px'>
  <input name='name' value="{e(p['name'] or '')}" placeholder='Nume' required{_inv('name')}>
  <input name='phone' value="{e(p['phone'] or '')}" placeholder='Telefon'>
  <div class='r2'><input type='date' name='birth_date' value="{e(p.get('birth_date') or '')}"
    max='{date.today().isoformat()}'{_inv('birth_date')}>
  <select name='gender'><option value=''>Gen —</option>
    <option value='m'{" selected" if p.get('gender') == 'm' else ''}>M</option>
    <option value='f'{" selected" if p.get('gender') == 'f' else ''}>F</option></select></div>
  <input name='idnp' value="{e(p.get('idnp') or '')}" placeholder='IDNP (opțional)'
    maxlength='13' inputmode='numeric'{_inv('idnp')}>
  <input name='email' value="{e(p.get('email') or '')}" placeholder='E-mail'>
  <input name='address' value="{e(p.get('address') or '')}" placeholder='Adresă'>
  <input name='insurance' value="{e(p.get('insurance') or '')}" placeholder='Asigurare (ex. CNAM activă)'>
  <div class='r2'><select name='primary_doctor'><option value=''>Medic curant —</option>{doc_opts}</select>
  <input name='file_no' value="{e(p.get('file_no') or '')}" placeholder='Nr. dosar'></div>
  <select name='lang' title='Limba documentelor tipărite'>
    <option value='ro'{" selected" if (p.get('lang') or 'ro') != 'ru' else ''}>Documente în română</option>
    <option value='ru'{" selected" if p.get('lang') == 'ru' else ''}>Документы по-русски</option>
  </select>
  <textarea name='notes' rows='2' placeholder='Notițe interne'>{e(p.get('notes') or '')}</textarea>
  <button>{_ic('save')} Salvează profilul</button>
</form>"""

    # -- анамнез: опросник, раскрывается по клику (заполняется один раз) --
    an_flags = set((anam.get("flags") or "").split(",")) if anam else set()
    an_boxes = "".join(
        f"<label><input type='checkbox' name='fl' value='{k}'"
        f"{' checked' if k in an_flags else ''}> {e(v)}</label>"
        for k, v in ANAMNEZA_FLAGS.items())
    an_texts = "".join(
        f"<label class='dlab'>{e(lab)}"
        f"<textarea name='{k}' rows='2' maxlength='500' placeholder='{e(ph)}'>"
        f"{e((anam.get(k) if anam else '') or '')}</textarea></label>"
        for k, lab, ph in ANAMNEZA_TEXTS)
    an_marked = [v for k, v in ANAMNEZA_FLAGS.items() if k in an_flags]
    # ⚠️ свободный текст — ТОЖЕ риск, и чаще всего именно там аллергия и
    # реакция на анестезию. Считать риски по одним галочкам значит показать
    # «fără riscuri» над записанной пенициллиновой аллергией
    an_free = [(lab, (anam.get(k) or "").strip())
               for k, lab, _ph in ANAMNEZA_TEXTS
               if anam and (anam.get(k) or "").strip()]
    if anam:
        an_when = (anam.get("updated_at") or anam.get("created_at"))
        an_sum = (f"<small class='hint' style='margin:0'>Completat: "
                  f"{an_when.astimezone(eng.TZ).strftime('%d.%m.%Y')} · "
                  f"{e(anam.get('author') or '—')}</small>")
        n_risk = len(an_marked) + len(an_free)
        an_head = (f"<span class='pill orange'>{n_risk} de reținut</span>"
                   if n_risk else "<span class='pill green'>fără riscuri</span>")
    else:
        an_sum = ("<small class='hint' style='margin:0'>Nu a fost completată — "
                  "întrebați pacientul înainte de tratament</small>")
        an_head = "<span class='pill red'>necompletată</span>"
    # свёрнутая секция обязана показывать САМО содержимое: врач смотрит на неё
    # перед анестезией и раскрывать «Chestionar» не будет
    an_chips = ([f"<span>{_ic('sos')} {e(x)}</span>" for x in an_marked]
                + [f"<span>{_ic('note')} {e(lab)}: {e(val[:70])}</span>"
                   for lab, val in an_free])
    an_list = (f"<div class='anlist'>{''.join(an_chips)}</div>"
               if an_chips else "")
    anam_card = f"""<div class='fcard' id='anamneza'>
<h3>Anamneză {an_head}</h3>{an_list}{an_sum}
<a class='anprint' href='{base}/anamneza/print' target='_blank'>{_ic('print')} Formular
  pentru pacient</a>
<details class='anform'{' open' if not anam else ''}>
  <summary>{_ic('pen')} Chestionar</summary>
  <form class='fform' method='post' action='{base}/anamneza'>
    <div class='anbox'>{an_boxes}</div>
    {an_texts}
    <button>{_ic('save')} Salvează anamneza</button>
  </form>
</details></div>"""

    alerts_html = "".join(
        f"<div class='alert {e(a['kind'])}'>{_ALERT_ICON.get(a['kind'], _ic('info'))} {ALERT_KINDS.get(a['kind'], '')} {e(a['text'])}"
        f"<form method='post' action='{base}/alert/{a['id']}/del'>"
        f"<button title='Șterge'>{_ic('close')}</button></form></div>"
        for a in alerts) or "<p class='hint' style='margin:0'>— fără atenționări —</p>"
    kind_opts = "".join(f"<option value='{k}'>{v}</option>" for k, v in ALERT_KINDS.items())
    alerts_card = f"""<div class='fcard'><h3>Atenționări medicale</h3>{alerts_html}
<form class='fform' method='post' action='{base}/alert' style='margin-top:9px'>
  <div class='r2'><select name='kind' style='width:130px'>{kind_opts}</select>
  <input name='text' placeholder='ex. Alergie: Penicilină' maxlength='120' required></div>
  <button>+ Adaugă</button></form></div>"""

    # -- центр: формула FDI + план --
    def tooth_div(n: int, lower: bool = False, milk: bool = False) -> str:
        t = tmap.get(n)
        st = t["state"] if t else "ok"
        note = t["note"] if t else ""
        sf = (t["surfaces"] if t else "") or ""
        # поверхности дописываются ПОСЛЕ заметки: подпись «11 · Carie · test»
        # читают и человек, и проверка, и её формат менять незачем
        title = (f"{n} · {TOOTH_STATES.get(st, st)}"
                 + (f" · {note}" if note else "")
                 + (f" · {sf}" if sf else ""))
        num = f"<span class='num'>{n}</span>"
        svg = tsvg.tooth_svg(n, st, width=28 if milk else 38, interactive=True)
        # номер всегда со стороны КОРНЕЙ: у верхней дуги сверху, у нижней снизу —
        # так цифры не лезут в межчелюстной зазор и читаются как в макете
        return (f"<button type='button' class='tooth-btn' title=\"{e(title)}\" "
                f"onclick='openTooth({n})' onmouseenter='toothTip(event,{n})' "
                f"onmouseleave='toothTipOff()' onfocus='toothTip(event,{n})' "
                f"onblur='toothTipOff()'>{svg + num if lower else num + svg}</button>")

    upper = "".join(tooth_div(n) for n in _FDI_UPPER)
    lower = "".join(tooth_div(n, lower=True) for n in _FDI_LOWER)
    milk_up = "".join(tooth_div(n, milk=True) for n in _FDI_MILK_UPPER)
    milk_lo = "".join(tooth_div(n, lower=True, milk=True) for n in _FDI_MILK_LOWER)
    # молочный прикус раскрывается сам, если по нему уже есть записи: детская
    # фиша не должна требовать лишнего клика, взрослая — видеть лишний ряд
    milk_open = any(n in tmap for n in _FDI_MILK_UPPER + _FDI_MILK_LOWER)
    # легенда показывает НАСТОЯЩИЙ зуб в каждом состоянии, а не цветной квадрат:
    # так видно, чем «коронка» отличается от «пломбы», без словаря
    legend = "".join(
        f"<span class='lg'>{tsvg.tooth_svg(36, k, width=20)} {v}</span>"
        for k, v in TOOTH_STATES.items() if k != "ok")
    # .replace("</", ...) — чтобы note вида "</script>..." не вырвался из тега
    def _tinfo(n: int) -> dict:
        t = tmap.get(n)
        if not t:
            return {"state": "ok", "note": "", "doctor": "", "at": "", "sf": ""}
        return {"state": t["state"], "note": t["note"] or "",
                "doctor": t["doctor"] or "", "sf": t["surfaces"] or "",
                "at": t["updated_at"].astimezone(eng.TZ).strftime("%d.%m.%Y")
                      if t["updated_at"] else ""}

    hist_by_tooth: dict[str, list] = {}
    for a in tooth_acts:
        at = a["at"].astimezone(eng.TZ) if hasattr(a["at"], "astimezone") else None
        hist_by_tooth.setdefault(str(a["tooth"]), []).append(
            {"at": at.strftime("%d.%m.%Y") if at else "", "text": a["text"]})
    teeth_json = js_json(
        {str(n): _tinfo(n) for n in
         _FDI_UPPER + _FDI_LOWER + _FDI_MILK_UPPER + _FDI_MILK_LOWER})
    thist_json = js_json(hist_by_tooth)
    state_opts = "".join(f"<option value='{k}'>{v}</option>" for k, v in TOOTH_STATES.items())
    state_ro_json = js_json(TOOTH_STATES)
    sf_boxes = "".join(
        f"<label><input type='checkbox' name='sf' value='{k}'>{k} <small>{v}</small></label>"
        for k, v in TOOTH_SURFACES.items())
    teeth_card = f"""<div class='fcard'>
<h3>Formula dentară <small>· notație FDI · click pe dinte</small></h3>
<div class='arch-wrap'>
  <div class='arch'>{upper}</div>
  <div class='arch-mid'></div>
  <div class='arch lower'>{lower}</div>
</div>
<details class='milk'{' open' if milk_open else ''}>
  <summary>{_ic('milk')} Dentiție temporară (dinți de lapte)</summary>
  <div class='arch-wrap'>
    <div class='arch milk-arch'>{milk_up}</div>
    <div class='arch-mid'></div>
    <div class='arch lower milk-arch'>{milk_lo}</div>
  </div>
</details>
<div class='tleg'>{legend}</div></div>
<div id='toothtip' class='toothtip'><b class='tt-n'></b><div class='tt-s'></div>
  <div class='tt-d'></div></div>
<dialog id='toothdlg'>
  <div class='dlg-head'><span id='t_title'>Dinte</span>
    <button type='button' onclick="document.getElementById('toothdlg').close()">{_ic('close')}</button></div>
  <form class='dlg-form' method='post' action='{base}/tooth'>
    <input type='hidden' name='tooth' id='t_num'>
    <select name='state' id='t_state'>{state_opts}</select>
    <select name='doctor' id='t_doc'><option value=''>Medic —</option>{doc_opts}</select>
    <div class='sfrow' id='t_sf'>{sf_boxes}</div>
    <input name='note' id='t_note' placeholder='Notiță (opțional)' maxlength='120'>
    <button>{_ic('save')} Salvează</button>
  </form>
  <div id='t_hist' class='thist'></div>
</dialog>
<script>
const TEETH = {teeth_json};
const STATE_RO = {state_ro_json};
const THIST = {thist_json};
// ВАЖНО: заметку зуба и строку истории пишет ЧЕЛОВЕК, а ниже они уезжают в
// innerHTML. Экранирование в JSON (замена "</") спасает только сам тег
// <script>, но не HTML-парсер innerHTML: "<img src=x onerror=…>" выполнялся
// бы при наведении на зуб. textContent тут не подходит — в разметке рядом
// есть свои теги, поэтому экранируем значения
function tesc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {{
    return {{'&': '&amp;', '<': '&lt;', '>': '&gt;',
             '\"': '&quot;', \"'\": '&#39;'}}[c];
  }});
}}
function openTooth(n) {{
  const t = TEETH[String(n)] || {{state: 'ok', note: '', doctor: ''}};
  document.getElementById('t_title').textContent = 'Dinte ' + n;
  document.getElementById('t_num').value = n;
  document.getElementById('t_state').value = t.state;
  document.getElementById('t_doc').value = t.doctor || '';
  document.getElementById('t_note').value = t.note;
  const sf = (t.sf || '');
  document.querySelectorAll('#t_sf input').forEach(function (b) {{
    b.checked = sf.indexOf(b.value) >= 0;
  }});
  const h = THIST[String(n)] || [];
  document.getElementById('t_hist').innerHTML = h.length
    ? '<div class="th-t">Istoria dintelui</div>' + h.map(function (x) {{
        return '<div class="th-r"><span>' + tesc(x.at) + '</span>'
               + tesc(x.text) + '</div>';
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
    (t.at ? '<div>Actualizat: <b>' + tesc(t.at) + '</b></div>' : '') +
    (t.doctor ? '<div>Medic: <b>' + tesc(t.doctor) + '</b></div>' : '') +
    (t.sf ? '<div>Suprafețe: <b>' + tesc(t.sf) + '</b></div>' : '') +
    (t.note ? '<div class="tt-note">' + tesc(t.note) + '</div>' : '');
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

    # порядок осмысленный, а не «как добавляли»: работа сверху, запланированное
    # по сроку, законченное свежим вперёд, отказы последними
    def _plan_key(it):
        st = it["status"]
        if st == "in_lucru":
            return (0, 0.0, it["id"])
        if st == "planificat":
            return (1, str(it.get("due_date") or "9999-99-99"), it["id"])
        da = it.get("done_at")
        return (2 if st == "finalizat" else 3,
                -(da.timestamp() if hasattr(da, "timestamp") else 0.0),
                -it["id"])

    cnt = {k: sum(1 for it in plan if it["status"] == k)
           for k in ("planificat", "in_lucru", "finalizat", "refuzat")}
    n_act = cnt["planificat"] + cnt["in_lucru"]
    # законченное по умолчанию спрятано; если активного не осталось — открываем
    # первую НЕПУСТУЮ вкладку, а не пустой экран. ⚠️ Раньше запасной была
    # «Finalizate»; с появлением отказов план из одних отказов открывался
    # пустым — вкладка есть, записи есть, а на экране ничего
    default_tab = ("act" if n_act or not plan
                   else "finalizat" if cnt["finalizat"] else "refuzat")
    # какие статусы показывает каждая вкладка — ОДИН словарь на сервер и на
    # planTab(); пока правило жило выражением «не finalizat», отказ попадал в
    # «Active» молча
    tab_states = {"act": db.PLAN_ACTIVE, "finalizat": ("finalizat",),
                  "refuzat": ("refuzat",)}
    plan_rows = []
    total = total_done = 0
    for it in sorted(plan, key=_plan_key):
        st = it["status"]
        if it["price_mdl"]:
            # ⚠️ отказ не деньги НИ В ОДНОЙ из двух сумм: он не ждёт оплаты
            # (не «plan activ») и не выполнен (не «finalizate»)
            if st in db.PLAN_ACTIVE:
                total += it["price_mdl"]
            elif st == "finalizat":
                total_done += it["price_mdl"]
        refuz = (f"<button type='button' class='pref' data-id='{it['id']}' "
                 f"data-p='{e(it['procedure'])}' onclick='openRefuz(this)' "
                 f"title='Pacientul refuză procedura — se consemnează în fișă'>"
                 f"{_ic('ban')} Refuz</button>")
        if st == "planificat":
            act = (f"<form method='post' action='{base}/plan/{it['id']}/status'>"
                   f"<input type='hidden' name='to' value='in_lucru'>"
                   f"<button class='pgo' title='Trece procedura în lucru'>"
                   f"{_ic('play')} Începe</button></form>{refuz}")
        elif st == "in_lucru":
            act = (f"<form method='post' action='{base}/plan/{it['id']}/status'>"
                   f"<input type='hidden' name='to' value='finalizat'>"
                   f"<button class='pgo fin' title='Marchează ca finalizată'>"
                   f"{_ic('check')} Finalizează</button></form>{refuz}")
        elif st == "refuzat":
            # возврат идёт в «Planificat», а не в работу: после отказа лечение
            # начинается заново, с нового согласия пациента
            act = (f"<form method='post' action='{base}/plan/{it['id']}/status' "
                   f"onsubmit=\"return confirm('Pacientul a revenit asupra "
                   f"refuzului? Procedura se întoarce în plan.')\">"
                   f"<input type='hidden' name='to' value='planificat'>"
                   f"<button class='pre' title='Pacientul a revenit — înapoi în plan'>"
                   f"{_ic('undo')} Reia</button></form>")
        else:
            act = (f"<form method='post' action='{base}/plan/{it['id']}/status' "
                   f"onsubmit=\"return confirm('Redeschideți procedura "
                   f"(înapoi în lucru)?')\">"
                   f"<input type='hidden' name='to' value='in_lucru'>"
                   f"<button class='pre' title='Redeschide — înapoi în lucru'>"
                   f"{_ic('undo')} Redeschide</button></form>")
        da = it.get("done_at")
        if st in db.PLAN_CLOSED and hasattr(da, "astimezone"):
            mark, ttl = ((_ic("check"), "Data finalizării") if st == "finalizat"
                         else (_ic("ban"), "Data refuzului"))
            due_html = (f"<span class='pdone' title='{ttl}'>"
                        f"{mark} {da.astimezone(eng.TZ).strftime('%d.%m.%Y')}</span>")
        else:
            due_html = f"<span class='pdue'>{_due_html(it.get('due_date'), st)}</span>"
        tooth_html = (f"<button type='button' class='pt' onclick='openTooth({it['tooth']})' "
                      f"title='Deschide dintele în formulă'>{it['tooth']}</button>"
                      if it["tooth"] else "<span class='pt'>—</span>")
        hidden = "" if st in tab_states[default_tab] else " style='display:none'"
        # причина отказа стоит ПОД процедурой, а не в подсказке: это и есть
        # запись по ст.13(5), и она обязана читаться с листа, а не с наведения
        motiv = (f"<em class='pmotiv'>{e(it.get('refuz_motiv') or '')}</em>"
                 if st == "refuzat" and it.get("refuz_motiv") else "")
        # ⛔ удалять можно только НЕТРОНУТОЕ: начатая, выполненная или
        # отказанная позиция — клинический факт, и закрывается статусом.
        # Кнопка «Șterge» тут стирала бы ровно то, что закон велит хранить
        pdel = (f"<form method='post' action='{base}/plan/{it['id']}/del' "
                f"onsubmit=\"return confirm('Ștergeți poziția din plan?')\">"
                f"<button class='pdel' title='Șterge poziția (doar cât nu a "
                f"fost începută)'>{_ic('close')}</button></form>"
                if st == "planificat" else "")
        plan_rows.append(
            f"<div class='plan-row{' done' if st in db.PLAN_CLOSED else ''}' "
            f"data-st='{e(st)}'{hidden}>"
            f"{tooth_html}"
            f"<span class='pp'>{e(it['procedure'])}{motiv}</span>"
            f"<span class='pd'>{e(it['doctor'] or '—')}</span>"
            f"{due_html}"
            f"<span class='pbadge {e(st)}'>{_PLAN_LABEL.get(st, st)}</span>"
            f"<span class='pm'>{f'{it['price_mdl']:,}'.replace(',', ' ') + ' MDL' if it['price_mdl'] else '—'}</span>"
            f"<span class='pact'>{act}{pdel}</span></div>")
    plan_html = "".join(plan_rows) or "<p class='hint' style='margin:6px 0'>— plan gol —</p>"
    # молочные — отдельной группой, иначе список из 52 номеров нечитаем
    tooth_opts = (
        "<option value=''>—</option>"
        + "".join(f"<option value='{n}'>{n}</option>"
                  for n in _FDI_UPPER + _FDI_LOWER)
        + "<optgroup label='Dinți de lapte'>"
        + "".join(f"<option value='{n}'>{n}</option>"
                  for n in _FDI_MILK_UPPER + _FDI_MILK_LOWER)
        + "</optgroup>")
    def _tab(key: str, label: str, n: int) -> str:
        on = " class='on'" if default_tab == key else ""
        return (f"<button{on} data-f='{key}' onclick='planTab(this)'>"
                f"{label} ({n})</button>")

    # вкладка отказов появляется, только когда отказы есть: пустая «Refuzate
    # (0)» на каждой фише — обещание проблемы, которой у клиники нет
    tabs = ("<div class='tabs'>"
            + _tab("act", "Active", n_act)
            + _tab("finalizat", "Finalizate", cnt["finalizat"])
            + (_tab("refuzat", "Refuzate", cnt["refuzat"]) if cnt["refuzat"] else "")
            + f"<button data-f='all' onclick='planTab(this)'>Toate ({len(plan)})</button>"
            "</div>")
    # ⚠️ прогресс считается от того, что клиника ещё может сделать: отказ из
    # знаменателя выпадает, иначе план из трёх процедур, одну из которых
    # пациент отверг, навсегда застревает на 66% «выполнено»
    n_track = len(plan) - cnt["refuzat"]
    pct_done = round(100 * cnt["finalizat"] / n_track) if n_track else 0
    prog = (f"<div class='plan-prog'><div class='statbar'>"
            f"<div style='width:{pct_done}%'></div></div>"
            f"<small>{cnt['finalizat']}/{n_track} finalizate"
            + (f" · {cnt['refuzat']} refuzate" if cnt["refuzat"] else "")
            + "</small></div>" if plan else "")
    done_total_html = (f"<span class='pt-done'> · finalizate: "
                       f"{f'{total_done:,}'.replace(',', ' ')} MDL</span>"
                       if total_done else "")
    # ⭐ Лист согласия стоит В ШАПКЕ плана, а не среди быстрых действий внизу:
    # ст.13(2) Legea 263/2005 требует подписи ДО вмешательства, то есть ровно в
    # тот момент, когда план на экране и обсуждается с пациентом
    acord_link = (f"<a class='pacord' href='{base}/plan-acord' "
                  f"title='Acord informat la plan — pentru semnătura pacientului "
                  f"și a medicului (art. 13 Legea nr. 263/2005)'>"
                  f"{_ic('clipboard')} Acord informat</a>" if plan else "")
    plan_card = f"""<div class='fcard' id='plan'>
<h3>Plan de tratament <small>· plan activ: {f'{total:,}'.replace(',', ' ')} MDL</small>{acord_link}</h3>
{prog}{tabs}
{plan_html}
<div class='ptotal'><span>Total plan activ</span><b>{f'{total:,}'.replace(',', ' ')} MDL</b>{done_total_html}</div>
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
        # дневник приёма: у заполненного визита — диагноз и ссылка, у
        # состоявшегося пустого — приглашение заполнить (будущие не зовём:
        # писать «лечение» вперёд — ошибка данных)
        vurl = f"/admin/visit/{v['id']}?back={urllib.parse.quote(base)}"
        r = recs.get(v["id"])
        if r:
            diag = (r["diagnostic"] or r["tratament"] or r["acuze"] or "").strip()
            consult = (f"<small style='overflow-wrap:anywhere'>{_ic('med')} "
                       f"<a href='{vurl}'>Consultație</a>"
                       + (f": {e(diag[:60])}" if diag else "") + "</small>")
        elif (v["status"] in ("done", "arrived", "waiting")
              or (v["status"] == "confirmed" and v["starts_at"] <= now)):
            consult = f"<small><a href='{vurl}'>+ Consultație</a></small>"
        else:
            consult = ""
        hist.append(
            f"<div class='tline{' next' if is_next else ''}'>"
            f"<div class='tdot'><i></i></div><div class='tb'>"
            f"<small>{dtv.strftime('%d.%m.%Y %H:%M')} · {STATUS_LABEL.get(v['status'], v['status'])}</small>"
            f"<b style='font-size:12.5px'>{e(v['service'])}</b>"
            f"<small>{e(v['doctor'])}</small>{consult}</div></div>")
    hist_card = (f"<div class='fcard'><h3>Istoric vizite <small>· ultimele {len(visits[:8])}</small></h3>"
                 + ("".join(hist) or "<p class='hint' style='margin:0'>— încă fără vizite —</p>")
                 + f"<a href='/admin/search?q={urllib.parse.quote(p['name'] or '')}' "
                 f"style='font-size:12px'>Vezi tot istoricul ›</a></div>")

    doc_meta: dict = {}

    def doc_card(dd) -> str:
        # картинку показываем ею же: файлы лежат локально, отдельный рендер
        # миниатюр — оптимизация следующего этапа, а не условие работы
        mime = dd["mime"] or ""
        is_img = mime.startswith("image/")
        thumb = (f"<img src='/admin/doc/{dd['id']}?thumb=1' alt='' loading='lazy'>" if is_img
                 else _DOC_ICON.get(dd["category"], _ic("file")))
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
                f"<button title='Șterge'>{_ic('close')}</button></form></div></div>")

    _ACT_ICON = {"appt_new": _ic("cal"), "appt_status": _ic("check"),
                 "appt_cancel": _ic("ban"), "tooth": _ic("tooth"),
                 "plan_add": _ic("plus"), "plan_status": _ic("refresh"),
                 "plan_del": _ic("minus"), "doc_add": _ic("clip"),
                 "doc_del": _ic("trash"), "alert_add": _ic("sos"),
                 "profile": _ic("pen"), "archive": _ic("box"),
                 # выдача копии данных — событие, о котором спросят на проверке;
                 # в общей ленте оно обязано быть заметным, а не точкой по умолчанию
                 "export": _ic("download"), "acord": _ic("clipboard"),
                 "plan_acord": _ic("clipboard"),
                 "consult": _ic("med"), "fisa043": _ic("print"),
                 "anamneza": _ic("note"), "view": _ic("eye"),
                 "doc_view": _ic("eye"), "erase": _ic("erase")}
    act_rows = []
    for a in acts:
        at = a["at"].astimezone(eng.TZ) if hasattr(a["at"], "astimezone") else None
        when = at.strftime("%d.%m.%Y") if at else ""
        hhmm = at.strftime("%H:%M") if at else ""
        # с ролями подпись — это ИМЯ вошедшего; «recepție» осталось у событий,
        # записанных до учёток, и у фоновых задач, где человека нет
        who = ("bot" if a["actor"] == "bot"
               else f"{e(a['actor'] or 'recepție')}")
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
        f"{_ic('eye')} accesările</a>")
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
    <label for='docfile'>{_ic('clip')} Alege fișierul</label>
    <span class='fname' id='docfile_n'>niciun fișier ales</span>
  </div>
  <button>{_ic('upload')} Încarcă document</button>
</form>
<p class='hint' style='margin-top:8px'>Click pe fișier — pozele și PDF-urile se deschid aici,
restul în programul potrivit (Word, Excel). Fișierele rămân local, în folderul
programului (data\\files).</p></div>"""

    # ---- hero: кто перед врачом, одним взглядом ----
    # бейджи собираются из УЖЕ имеющихся данных: алерты, страховка, импланты
    pills = []
    if p.get("archived"):
        pills.append(f"<span class='pill grey'>{_ic('box')} Arhivat</span>")
    else:
        pills.append(f"<span class='pill green'>{_ic('check')} Pacient activ</span>")
    for a in alerts[:3]:
        tone = {"allergy": "orange", "medication": "orange",
                "warning": "red"}.get(a["kind"], "grey")
        icon = _ALERT_ICON.get(a["kind"], _ic("info"))
        pills.append(f"<span class='pill {tone}'>{icon} {e(a['text'][:38])}</span>")
    if p.get("insurance"):
        pills.append(f"<span class='pill green'>{_ic('shield')} {e(p['insurance'][:28])}</span>")
    # долг видит и рецепция — ей его и взыскивать; сводные суммы по клинике
    # остаются за директором (PERM_MONEY в статистике)
    debt = fin["charged"] - fin["paid"]
    if debt > 0:
        pills.append(f"<span class='pill red'>{_ic('money')} De achitat: "
                     f"{f'{debt:,}'.replace(',', ' ')} MDL</span>")
    elif debt < 0:
        pills.append(f"<span class='pill green'>{_ic('money')} Avans: "
                     f"{f'{-debt:,}'.replace(',', ' ')} MDL</span>")
    n_impl = sum(1 for t in tmap.values() if t["state"] == "implant")
    if n_impl:
        pills.append(f"<span class='pill purple'>{_ic('set')} {n_impl} implant"
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
    # 043/e — документ, за которым тянутся чаще всего (проверка, выписка,
    # передача пациента): его место наверху, а не в конце страницы среди
    # быстрых действий, куда надо доскроллить
    acts.append(f"<a href='{base}/fisa043'>{_ic('file')} Fișa 043/e</a>")

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
    n_active = sum(1 for it in plan if it["status"] in db.PLAN_ACTIVE)
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
        return f"<a class='lmore' href='{href}' onclick='closeKpi()'>{txt} ›</a>"

    live_visits = [v for v in visits if v["status"] != "cancelled"]
    canc = len(visits) - len(live_visits)
    act_items = [it for it in plan if it["status"] in db.PLAN_ACTIVE]
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
                    f"onclick='closeKpi();openAppt()'>{_ic('cal')} Programează acum</button>")),
        "done": ("Proceduri finalizate",
                 "".join(_prow(it) for it in done_items)
                 or _empty("încă nimic finalizat")),
    }
    kpis = [
        ("visits", _ic("clipboard"), len(live_visits), "Vizite în total",
         "din " + p["created_at"].astimezone(eng.TZ).strftime("%Y")),
        ("active", _ic("tooth"), n_active, "Proceduri active", "în planul de tratament"),
        ("last", _ic("clock"), (f"{days_ago} zile" if days_ago else "azi") if lastv else "—",
         "Ultima vizită",
         lastv["starts_at"].astimezone(eng.TZ).strftime("%d.%m.%Y") if lastv else "—"),
        ("next", _ic("cal"), nextv["starts_at"].astimezone(eng.TZ).strftime("%d.%m") if nextv else "—",
         "Următoarea vizită",
         nextv["starts_at"].astimezone(eng.TZ).strftime("%H:%M") if nextv else "neprogramat"),
        ("done", _ic("check"), n_done, "Proceduri finalizate", "istoric complet"),
    ]
    kpi_html = "<div class='kpi5'>" + "".join(
        f"<button type='button' class='kpi' onclick=\"openKpi('{key}')\" "
        f"title='{lbl} — click pentru detalii'>"
        f"<span class='ki'>{ic}</span><div style='min-width:0'>"
        f"<b>{val}</b><span>{lbl}</span><small>{sub}</small></div></button>"
        for key, ic, val, lbl, sub in kpis) + "</div>"

    arch_label = (_ic("undo") + " Scoate din arhivă" if p.get("archived")
                  else _ic("box") + " Arhivează pacientul")
    profile_card = f"""<div class='fcard'><h3>Date pacient</h3>
{info_rows}{notes_html}
<button style='width:100%;margin-top:12px;background:none;border:1px solid var(--line);
  border-radius:var(--r-ctl);height:var(--h-ctl);cursor:pointer;font-size:14px;
  font-weight:600;color:var(--text2)'
  onclick="var f=document.getElementById('pedit');f.style.display=f.style.display==='none'?'flex':'none'">
  {_ic('pen')} Editează profilul</button>
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
  {_ic('download')} Descarcă datele pacientului</a>
<a href='{base}/acord' style='display:block;margin-top:8px;text-align:center;
  border:1px solid var(--line);border-radius:var(--r-ctl);height:40px;line-height:40px;
  font-size:13px;color:var(--text3);text-decoration:none'
  title='Formular de informare cu datele pacientului, pentru semnare (Legea 195)'>
  {_ic('clipboard')} Informare / acord — tipărire</a>
{_erase_block(base, erasure)}</div>"""

    # ---- платежи и баланс (08-07, модуль финансов, шаг 1) ----
    _PAY_ICO = {"numerar": _ic("cash"), "card": _ic("card"), "transfer": _ic("bank")}
    can_del_pay = can(request_user(), PERM_MONEY)
    chg = f"{fin['charged']:,}".replace(",", " ")
    pd_s = f"{fin['paid']:,}".replace(",", " ")
    if debt > 0:
        sold = (f"<div class='sold bad'><span>De achitat</span>"
                f"<b>{f'{debt:,}'.replace(',', ' ')} MDL</b></div>")
    elif debt < 0:
        sold = (f"<div class='sold plus'><span>Avans</span>"
                f"<b>{f'{-debt:,}'.replace(',', ' ')} MDL</b></div>")
    elif fin["charged"]:
        sold = "<div class='sold ok'><span>Sold</span><b>achitat integral</b></div>"
    else:
        sold = ""
    pay_rows = []
    for pl in pays:
        when = (pl["at"].astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M")
                if hasattr(pl["at"], "astimezone") else "")
        amt = f"{abs(pl['amount_mdl']):,}".replace(",", " ")
        neg = pl["amount_mdl"] < 0
        who = f" · {e(pl['taken_by'])}" if pl["taken_by"] else ""
        del_f = (f"<form method='post' action='{base}/pay/{pl['id']}/del' "
                 f"onsubmit=\"return confirm('Ștergeți plata? Rămâne urmă în "
                 f"istoricul fișei.')\">"
                 f"<button title='Șterge plata (doar director)'>{_ic('close')}</button></form>"
                 if can_del_pay else "")
        pay_rows.append(
            f"<div class='pay-row{' neg' if neg else ''}'>"
            f"<span class='pw'>{when}</span>"
            f"<span class='pi' title='{e(pl['method'])}'>"
            f"{_PAY_ICO.get(pl['method'], _ic('cash'))}</span>"
            f"<b class='pa'>{'- ' if neg else ''}{amt} MDL</b>"
            f"<span class='pn'>{e(pl['note'] or '')}{who}</span>{del_f}</div>")
    method_opts = "".join(f"<option value='{m}'>{_PAY_ICO[m]} {m}</option>"
                          for m in db.PAY_METHODS)
    fin_card = f"""<div class='fcard' id='plati'>
<h3>Plăți și sold <small>· lucrări finalizate: {chg} MDL · plătit: {pd_s} MDL</small></h3>
{sold}
{''.join(pay_rows) or "<p class='hint' style='margin:6px 0'>— încă fără plăți —</p>"}
<form class='fform' method='post' action='{base}/pay' style='margin-top:10px'>
  <div class='r2'>
    <input name='amount' type='number' required min='-1000000' max='1000000'
           placeholder='Suma MDL (cu minus = restituire)'>
    <select name='method' style='width:160px'>{method_opts}</select></div>
  <input name='note' placeholder='Notă (opțional, ex. avans coroană)' maxlength='120'>
  <button>＋ Înregistrează plata</button>
</form>
<p class='hint' style='margin-top:8px'>Soldul = lucrările <b>finalizate</b> din plan
(cu preț) minus plățile. Plata nu se leagă de o procedură anume — banii acoperă
soldul fișei.</p></div>"""

    quick = f"""<div class='fcard'><h3>Acțiuni rapide</h3><div class='qa'>
  <button type='button' onclick='openAppt()'>{_ic('plus')} Vizită nouă</button>
  <a href='#plan'>{_ic('tooth')} Plan de tratament</a>
  <a href='#docs'>{_ic('camera')} Încarcă document</a>
  <button type='button' onclick="openNote()">{_ic('note')} Notiță</button>
  <button type='button' onclick="window.print()">{_ic('print')} Printează fișa</button>
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
    kpi_json = js_json(kpi_panels)
    docs_json = js_json(doc_meta)
    tabs_json = js_json({k: list(v) for k, v in tab_states.items()})
    base_json = js_json(base)
    dialogs = f"""<dialog id='apptdlg'>
  <div class='dlg-head'><span>{_ic('cal')} Programare — {e(p['name'] or '—')}</span>
    <button type='button' onclick="document.getElementById('apptdlg').close()">{_ic('close')}</button></div>
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
    <button type='button' onclick='closeKpi()'>{_ic('close')}</button></div>
  <div class='lbody' id='kpi_b'></div>
</dialog>
<dialog id='docdlg' class='wide'>
  <div class='dlg-head'><span id='dv_t'>—</span>
    <button type='button' onclick="document.getElementById('docdlg').close()">{_ic('close')}</button></div>
  <div class='dvbody' id='dv_b'></div>
  <div class='dvacts'>
    <button type='button' onclick='sysOpen(DV_ID)'>{_ic('monitor')} Deschide în alt program</button>
    <a id='dv_dl' href='#'>{_ic('download')} Salvează pe disc</a>
  </div>
</dialog>
<dialog id='refuzdlg'>
  <div class='dlg-head'><span>{_ic('ban')} Refuzul pacientului</span>
    <button type='button' onclick="document.getElementById('refuzdlg').close()">{_ic('close')}</button></div>
  <form class='dlg-form' method='post' id='refuzform'>
    <input type='hidden' name='to' value='refuzat'>
    <p class='hint' style='margin:0'>Procedura: <b id='rf_p'>—</b></p>
    <label class='dlab'>Motivul refuzului și consecințele explicate pacientului
      <textarea name='motiv' id='rf_m' rows='3' maxlength='300' required
        placeholder='Ex.: pacientul refuză extracția; i s-au explicat riscul de infecție și pierderea dinților vecini'></textarea></label>
    <p class='hint' style='margin:0'>Se consemnează în fișă și apare în Fișa
      043/e și în acordul informat, conform art. 13 alin. (5) din Legea
      nr. 263/2005. Foaia tipărită se semnează de pacient și de medic.</p>
    <button>{_ic('ban')} Înregistrează refuzul</button>
  </form>
</dialog>"""

    body = f"""{banner}
<div class='nav'><a href='/admin/search'>{_ic('chev-l')} Pacienți</a>
<a href='/admin/all'>{_ic('clipboard')} Programări</a></div>
{hero}
{kpi_html}
<div class='pv2'>
  <div class='pv2-main'>{teeth_card}{plan_card}{fin_card}{docs_card}{quick}</div>
  <!-- Порядок правой колонки (Олег, 08-09, по живому экрану): ближайший визит,
       кто это, чем опасен приём, что было. «Istoric activitate» — журнал
       доступа по 195-му: он обязан быть виден, но наверху занимал место у
       того, ради чего фишу открывают, и уехал вниз, к истории визитов. -->
  <div class='pv2-side'>{next_html}{profile_card}{alerts_card}{anam_card}{act_card}{hist_card}</div>
</div>
{dialogs}
<script>
const BASE = "{base}";
const AP_DOCS = {js_json(ap_svc_docs)};
const AP_NAMES = {js_json(dict(eng.ACTIVE_DOCTORS))};
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
// ---- цифра -> список, из которого она посчитана ----
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
  el.textContent = 'copiat';
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
// какие статусы показывает вкладка — приезжает С СЕРВЕРА (tab_states), тем же
// словарём, которым посчитаны скрытые строки при отрисовке. Раньше правило
// жило здесь выражением «не finalizat», и появление отказа развело серверную
// и браузерную версии одного фильтра
const PLAN_TABS = {tabs_json};
function planTab(btn) {{
  document.querySelectorAll('.tabs button').forEach(function (b) {{
    b.classList.toggle('on', b === btn);
  }});
  var f = btn.dataset.f;
  document.querySelectorAll('.plan-row').forEach(function (r) {{
    var show = f === 'all' || (PLAN_TABS[f] || []).indexOf(r.dataset.st) >= 0;
    r.style.display = show ? '' : 'none';
  }});
}}
// отказ — единственное действие плана, которому нужен ТЕКСТ: ст.13(5) требует
// записать не только сам отказ, но и объяснённые пациенту последствия
function openRefuz(btn) {{
  const f = document.getElementById('refuzform');
  f.action = {base_json} + '/plan/' + btn.dataset.id + '/status';
  document.getElementById('rf_p').textContent = btn.dataset.p;
  document.getElementById('rf_m').value = '';
  document.getElementById('refuzdlg').showModal();
  document.getElementById('rf_m').focus();
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
    prev = await db.get_patient(pid)
    if not prev:
        return RedirectResponse("/admin/search", status_code=303)
    data = {}
    for f in db.PATIENT_FIELDS:
        v = str(form.get(f) or "").strip()[:200 if f != "notes" else 500]
        data[f] = v or None
    # каждая причина отказа называет себя И подсвечивает своё поле в форме
    # (msg → поле, см. _BAD_FIELD): «Date invalide» без указания куда смотреть
    # читалось как «программа не работает» (Олег, 08-07)
    if not data.get("name"):
        return _card_redirect(pid, "bad_card")
    bd = data.get("birth_date")
    bd_year = None
    if bd:
        try:
            parsed = date.fromisoformat(bd)
        except ValueError:
            return _card_redirect(pid, "bad_bd")
        if not (1900 <= parsed.year and parsed <= date.today()):
            return _card_redirect(pid, "bad_bd")
        data["birth_date"] = parsed.isoformat()
        bd_year = parsed.year
    if data.get("idnp") and not re.fullmatch(r"[0-9]{13}", data["idnp"]):
        return _card_redirect(pid, "bad_idnp")
    await db.update_patient(pid, data)
    if bd_year:
        # возраст в поиске/сетке/CSV считается по birth_year — держим в синке
        await db.set_birth_year(pid, bd_year)
    elif prev.get("birth_date"):
        # дату ОЧИСТИЛИ — год из неё больше не правда: несброшенный birth_year
        # продолжал бы показывать возраст от удалённой даты в фише, списке и
        # выгрузках. ⚠️ Только когда дата БЫЛА: у пациента из бота год живёт
        # без даты, и обнулять его за пустое поле формы нельзя
        await db.set_birth_year(pid, None)
    # язык печатных документов — мимо PATIENT_FIELDS: колонка NOT NULL, а там
    # пустое поле превращается в NULL
    await db.set_patient_lang(pid, str(form.get("lang") or ""))
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
    return _card_redirect(pid, "ok_arh" if on == "1" else "ok_unarh")


@router.post("/admin/patient/{pid}/alert")
async def patient_alert_add(request: Request, pid: int,
                            kind: str = Form(...), text: str = Form(...)):
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    if kind not in ALERT_KINDS or not text.strip():
        return _card_redirect(pid, "bad_card")
    await db.add_alert(pid, kind, text.strip()[:120])
    return _card_redirect(pid, "ok_card")


@router.get("/admin/patient/{pid}/anamneza/print", response_class=HTMLResponse)
async def patient_anamneza_print(request: Request, pid: int, lang: str = ""):
    """Пустой бланк опросника пациенту на руки. Спрашивать двенадцать пунктов
    голосом через стойку долго и неловко: пациент заполняет лист, пока ждёт,
    рецепция переносит ответы в фишу."""
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    return panam.render_form(p, _doc_lang(p, lang))


@router.post("/admin/patient/{pid}/anamneza")
async def patient_anamneza(request: Request, pid: int):
    """Опросник анамнеза. Пустой не сохраняем: «фиша с пустым анамнезом» и
    «анамнез не собирали» — разные вещи, и вторая обязана быть видна."""
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    form = await request.form()
    flags = ",".join(k for k in ANAMNEZA_FLAGS
                     if k in {str(x) for x in form.getlist("fl")})
    fields = {k: str(form.get(k) or "") for k, *_ in ANAMNEZA_TEXTS}
    if not flags and not any(v.strip() for v in fields.values()):
        # пустая форма на ПУСТОМ опроснике — промах, а не ответ: «фиша с
        # пустым анамнезом» и «анамнез не собирали» это разные вещи.
        # Но если опросник УЖЕ есть, пустое сохранение — законное снятие
        # ошибочной отметки (поставили «HIV» не тому), и запретить его
        # значит оставить неверную запись в первичной документации
        if not (await db.anamneza(pid)):
            return _card_redirect(pid, "bad_anam")
    await db.save_anamneza(pid, flags, fields)
    return _card_redirect(pid, "ok_anam")


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
    if tooth not in _FDI_ALL or state not in TOOTH_STATES:
        return _card_redirect(pid, "bad_card")
    # врача принимаем только из справочника: свободный текст тут — будущий
    # «Иванов»/«Иванова» в истории зуба
    doc = doctor.strip() if doctor.strip() in set(eng.DOCTORS.values()) else ""
    # поверхности — только известные буквы и в каноническом порядке MODVL:
    # «OM» и «MO» это одно и то же, а в карте и на печати должно читаться одинаково
    form = await request.form()
    sf = "".join(k for k in TOOTH_SURFACES
                 if k in {str(x).strip().upper() for x in form.getlist("sf")})
    await db.set_tooth(pid, tooth, state, note.strip()[:120], doc, sf)
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
    if t is not None and t not in _FDI_ALL:
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


@router.post("/admin/patient/{pid}/pay")
async def patient_pay(request: Request, pid: int, amount: str = Form(...),
                      method: str = Form("numerar"), note: str = Form("")):
    """Платёж записывает ЛЮБАЯ роль: деньги физически берёт рецепция (решение
    Олега 08-07). Минус — возврат. Удаление — только директор, ниже."""
    if (deny := _guard(request)) is not None:
        return deny
    if not (await db.get_patient(pid)):
        return RedirectResponse("/admin/search", status_code=303)
    try:
        amt = int(amount.strip())
    except (ValueError, AttributeError):
        return _card_redirect(pid, "bad_pay")
    if amt == 0 or abs(amt) > 1_000_000 or method not in db.PAY_METHODS:
        return _card_redirect(pid, "bad_pay")
    await db.add_payment(pid, amt, method, note.strip()[:120])
    return _card_redirect(pid, "ok_pay")


@router.post("/admin/patient/{pid}/pay/{pay_id}/del")
async def patient_pay_del(request: Request, pid: int, pay_id: int):
    if (deny := require(request, PERM_MONEY)) is not None:
        return deny
    await db.delete_payment(pay_id, pid)
    return _card_redirect(pid, "pay_del")


@router.post("/admin/patient/{pid}/plan/{item_id}/status")
async def patient_plan_status(request: Request, pid: int, item_id: int,
                              to: str = Form(...), motiv: str = Form("")):
    if (deny := _guard(request)) is not None:
        return deny
    # проверяем РЕБРО (откуда → куда), а не только цель: направление — правило
    # сервера, а не рисунок кнопок; устаревшая вкладка не воскресит финал
    cur = await db.plan_item_status(item_id, pid)
    if cur is None or (cur, to) not in _PLAN_EDGES:
        return _card_redirect(pid, "bad_card")
    why = motiv.strip()[:300]
    # ⭐ Причина требуется СЕРВЕРОМ, а не только атрибутом required в форме:
    # без неё отказ не является записью по ст.13(5) Legea 263/2005 («cu
    # indicarea consecinţelor posibile»), а браузерная проверка обходится
    # любым запросом мимо страницы
    if to in _PLAN_NEEDS_MOTIV and not why:
        return _card_redirect(pid, "bad_refuz")
    await db.set_plan_status(item_id, pid, to, motiv=why)
    return _card_redirect(pid, "ok_refuz" if to == "refuzat" else "")


@router.post("/admin/patient/{pid}/plan/{item_id}/del")
async def patient_plan_del(request: Request, pid: int, item_id: int):
    """Удалить можно ТОЛЬКО нетронутую позицию.

    Начатая, выполненная или отказанная — уже медицинская запись: закон велит
    её хранить (043/e — 5 лет), а отказ ст.13(5) прямо требует оставить в
    документации. Опечатку в свежедобавленной строке чинит удаление, всё
    остальное — статус. ⛔ Проверять здесь, а не только прятать кнопку:
    страница живёт в открытой вкладке дольше, чем позиция в «Planificat».
    """
    if (deny := _guard(request)) is not None:
        return deny
    cur = await db.plan_item_status(item_id, pid)
    if cur is not None and cur != "planificat":
        return _card_redirect(pid, "bad_pdel")
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


def _doc_lang(p: dict, lang: str) -> str:
    """Язык печатного листа: явный выбор в адресе, иначе язык пациента.
    Русский заполнен осмысленно только у пришедших из бота — остальным его
    ставит рецепция в профиле; дефолт остаётся румынским."""
    if lang in pacord.LANGS:
        return lang
    return (p.get("lang") or "ro") if (p.get("lang") in pacord.LANGS) else "ro"


@router.get("/admin/patient/{pid}/acord", response_class=HTMLResponse)
async def patient_acord(request: Request, pid: int, lang: str = ""):
    """Печатный «Informare și acord» с данными этого пациента (закон 195).

    Генерация формы пишется в летопись: выдача листа с персональными данными —
    само по себе событие обработки, как и выдача копии. Подписанный экземпляр
    регистратура сканирует и грузит в документы пациента — так факт подписи
    остаётся в фише и уезжает в выгрузку по 195-му.
    """
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    await db.log_event(pid, "acord",
                       "Formular «Informare și acord» generat pentru tipărire")
    return pacord.render(p, _doc_lang(p, lang))


@router.get("/admin/patient/{pid}/plan-acord", response_class=HTMLResponse)
async def patient_plan_acord(request: Request, pid: int, lang: str = ""):
    """Печатный «Acord informat» к плану лечения (ст. 13 Legea 263/2005).

    ⚠️ Не путать с `/acord`: тот — информирование по 195-му (персональные
    данные), этот — согласие на само вмешательство. Разные основания, разные
    подписи, и один другого не заменяет.

    Диагноз берём из ПОСЛЕДНЕЙ записи приёма, где он заполнен, — той же
    формулой, что 043/e: другого места для диагноза в фише нет, а лист без
    него начинался бы с пустой строки в самом верху.
    """
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    plan = await db.plan_items(pid)
    recs = await db.patient_visit_records(pid)
    diag = next((r["diagnostic"].strip() for r in recs
                 if (r.get("diagnostic") or "").strip()), "")
    await db.log_event(pid, "plan_acord",
                       "Acord informat la planul de tratament generat "
                       "pentru tipărire")
    return pplan.render(p, plan, diag, _doc_lang(p, lang))


# ---------- дневник визита (consultația) ----------

@router.get("/admin/visit/{appt_id}", response_class=HTMLResponse)
async def visit_page(request: Request, appt_id: int, back: str = "",
                     msg: str = ""):
    """Страница «Consultație»: запись приёма 1:1 к визиту (см. visit.py).
    Доступна любому вошедшему, как и остальные операции фиши: приём пишет
    врач, но постфактум вносит и рецепция."""
    if (deny := _guard(request)) is not None:
        return deny
    a = await db.appointment_brief(appt_id)
    if not a or not a.get("patient_id") or a.get("source") == "note":
        return RedirectResponse("/admin", status_code=303)
    rec = await db.visit_record(appt_id)
    items = await db.plan_items(a["patient_id"])
    if not back.startswith("/admin"):
        back = f"/admin/patient/{a['patient_id']}"
    return HTMLResponse(pvisit.page(a, rec, items, back, msg))


@router.post("/admin/visit/{appt_id}")
async def visit_save(request: Request, appt_id: int):
    if (deny := _guard(request)) is not None:
        return deny
    a = await db.appointment_brief(appt_id)
    if not a or not a.get("patient_id") or a.get("source") == "note":
        return RedirectResponse("/admin", status_code=303)
    pid = a["patient_id"]
    form = await request.form()
    back = str(form.get("back") or "")
    if not back.startswith("/admin"):
        back = f"/admin/patient/{pid}"
    dest = f"/admin/visit/{appt_id}?back={urllib.parse.quote(back)}"
    if a["status"] in pvisit.NO_FORM_STATUSES:
        return RedirectResponse(dest + "&msg=bad_vst", status_code=303)
    fields = {k: str(form.get(k) or "")[:2000] for k in db.VISIT_FIELDS}
    if not any(v.strip() for v in fields.values()):
        return RedirectResponse(dest + "&msg=bad_visit", status_code=303)
    await db.save_visit_record(appt_id, pid, a["doctor"], fields)
    # отмеченные позиции плана выполнены НА этом визите: финализируем из
    # любого нефинального статуса (дневник фиксирует факт, церемония
    # in_lucru тут ни при чём) и привязываем к визиту
    for raw in form.getlist("done"):
        try:
            iid = int(raw)
        except ValueError:
            continue
        cur = await db.plan_item_status(iid, pid)
        # ⚠️ финализируем только АКТИВНОЕ: отказ (refuzat) в списке галочек не
        # показывается, но устаревшая вкладка прислала бы его id — и запись по
        # ст.13(5) молча превратилась бы в «выполнено»
        if cur in db.PLAN_ACTIVE:
            await db.set_plan_status(iid, pid, "finalizat", appt_id)
    return RedirectResponse(dest + "&msg=ok_visit", status_code=303)


@router.get("/admin/patient/{pid}/fisa043", response_class=HTMLResponse)
async def patient_fisa043(request: Request, pid: int, lang: str = ""):
    """Печатная «Fișa medicală a bolnavului stomatologic» (formular 043/e).

    Генерация листа с меддокументацией — событие обработки, как и acord:
    пишется в летопись. Дневник — хронологически (recs приходят DESC)."""
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    alerts = await db.patient_alerts(pid)
    teeth = await db.teeth_map(pid)
    plan = await db.plan_items(pid)
    recs = await db.patient_visit_records(pid)
    docs = await db.documents(pid)
    rx = sum(1 for d in docs if d["category"] == "radiografie")
    anam = await db.anamneza(pid)
    await db.log_event(pid, "fisa043", "Fișa 043/e generată pentru tipărire")
    doc_lang = _doc_lang(p, lang)
    # подписи отметок — на языке ЛИСТА: иначе русский бланк печатал бы
    # «Diabet zaharat» в русской же строке «Перенесённые заболевания»
    return pfisa.render(p, alerts, teeth, plan, list(reversed(recs)), rx,
                        _p_age(p), anam, panam.labels(doc_lang), doc_lang)


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


_PL_CANAL = {"tg": "Telegram", "manual": "recepție", "web": "web"}


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


def _pl_money(n: int) -> str:
    """2550 → «2 550». Разделитель тысяч — просьба Олега: без него четырёх- и
    пятизначные суммы читаются с запинкой."""
    return f"{n:,}".replace(",", " ")


def _pl_sold(debt: int) -> str:
    """Ячейка «Sold»: долг красным, аванс зелёным, рассчитавшийся — прочерком.
    Бейджи те же, что у статуса (bad/act) — своих классов не заводим."""
    if not debt:
        return "<span class='dim'>—</span>"
    if debt > 0:
        return f"<span class='pl-badge bad'>{_pl_money(debt)} MDL</span>"
    return f"<span class='pl-badge act'>avans {_pl_money(-debt)}</span>"


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
    """Все пациенты клиники со сведёнными агрегатами. Шесть запросов на
    страницу — независимо от того, десять в списке строк или тысяча."""
    people = await db.all_patients(include_archived=True)
    vis = {r["patient_id"]: r for r in await db.patients_visits(now)}
    alerts = {r["patient_id"]: r["n"] for r in await db.patients_alert_counts()}
    plans = {r["patient_id"]: r["n"] for r in await db.patients_plan_counts()}
    docs = {r["patient_id"]: r["doctor"] for r in await db.patients_last_doctor()}
    debts = await db.patients_debt()
    out = []
    for p in people:
        v = vis.get(p["id"]) or {}
        row = dict(p)
        row.update({"last_at": v.get("last_at"), "next_at": v.get("next_at"),
                    "n_visits": v.get("n_visits") or 0,
                    "n_alerts": alerts.get(p["id"], 0),
                    "n_plan": plans.get(p["id"], 0),
                    # долг = финализированный план − оплачено, минус = аванс.
                    # Та же формула, что в фише, и считается там же (db), чтобы
                    # список и карточка не разошлись в цифре
                    "debt": debts.get(p["id"], 0)})
        # «Medic» = врач из фиши, а если его не проставили — тот, кто вёл
        # последний визит. doctor_own отличает одно от другого: выведенного
        # врача показываем приглушённо, чтобы он не читался как назначение.
        row["doctor"] = p["primary_doctor"] or docs.get(p["id"], "")
        row["doctor_own"] = bool(p["primary_doctor"])
        row["status"] = _pl_status(row, now)
        out.append(row)
    return out


def _pl_filter(rows: list[dict], now: datetime, q: str, med: str, st: str,
               ch: str, sort: str, dat: str = "") -> list[dict]:
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
        # «Datorie» — только должники, «Avans» — только переплатившие. Ноль не
        # попадает ни туда, ни туда: рассчитавшийся пациент не должен всплывать
        # в списке, который регистратура открывает, чтобы кому-то позвонить.
        if dat == "da" and p["debt"] <= 0:
            continue
        if dat == "avans" and p["debt"] >= 0:
            continue
        out.append(p)
    if sort == "name":
        out.sort(key=lambda p: db.fold(p["name"]))
    elif sort == "new":
        out.sort(key=lambda p: p["created_at"], reverse=True)
    elif sort == "debt":    # самый крупный долг сверху, авансы в самом конце
        out.sort(key=lambda p: p["debt"], reverse=True)
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
    cls, arrow = ("up", _ic("caret-u")) if pct > 0 else ("dn", _ic("caret-d"))
    return f"<span class='{cls}'>{arrow} {abs(pct):.0f}%</span> față de luna trecută"


@router.get("/admin/search", response_class=HTMLResponse)
async def admin_search(request: Request, q: str = "", med: str = "", st: str = "",
                       ch: str = "", sort: str = "last", page: int = 1,
                       per: int = 20, msg: str = "", dat: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    e = html.escape
    q = q.strip()[:60]
    sort = sort if sort in ("last", "name", "new", "debt") else "last"
    dat = dat if dat in ("da", "avans") else ""
    per = per if per in _PL_PER else 20
    now = datetime.now(eng.TZ)

    everyone = await _pl_rows(now)
    rows = _pl_filter(everyone, now, q, med, st, ch, sort, dat)

    # ---- три числа над списком (карточки макета; денежной среди них нет) ----
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    next_start = (month_start + timedelta(days=32)).replace(day=1)
    appts = [r for r in await db.day_appointments(prev_start, next_start)
             if r["source"] != "note" and r["status"] != "cancelled"]
    n_appt = sum(1 for r in appts if r["starts_at"] >= month_start)
    n_appt_prev = len(appts) - n_appt
    n_total = sum(1 for p in everyone if not p["archived"])
    n_arh = sum(1 for p in everyone if p["archived"])
    n_new = sum(1 for p in everyone if p["created_at"] >= month_start)
    n_new_prev = sum(1 for p in everyone if prev_start <= p["created_at"] < month_start)

    def tile(ico: str, tone: str, val, label: str, foot: str, href: str = "") -> str:
        inner = (f"<span class='ico {tone}'>{ico}</span><div class='pl-tv'>"
                 f"<span>{label}</span><b>{val}</b><small>{foot}</small></div>")
        return (f"<a class='pl-tile' href='{href}'>{inner}</a>" if href
                else f"<div class='pl-tile'>{inner}</div>")

    tiles = ("<div class='pl-tiles'>"
             + tile(_ic("users"), "g", f"{n_total:,}".replace(",", " "), "Total pacienți",
                    (f"<span class='up'>+{n_new}</span> luna aceasta" if n_new
                     else "niciun pacient nou luna aceasta"))
             + tile(_ic("med"), "b", n_new, "Pacienți noi (luna aceasta)",
                    _pl_trend(n_new, n_new_prev))
             + tile(_ic("cal"), "v", n_appt, "Programări (luna aceasta)",
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

    base = {"q": q, "med": med, "st": st, "ch": ch, "sort": sort, "per": per,
            "dat": dat}

    def url(**over) -> str:
        d = {k: v for k, v in {**base, **over}.items()
             if v not in ("", None, 0) and (k, v) != ("sort", "last")
             and (k, v) != ("per", 20)}
        qs = urllib.parse.urlencode(d)
        # адрес уходит прямо в href: '&' между параметрами обязан быть '&amp;',
        # иначе браузер вправе прочитать хвост как имя сущности
        return "/admin/search" + (f"?{qs.replace('&', '&amp;')}" if qs else "")

    dirty = any([q, med, st, ch, dat]) or sort != "last" or per != 20
    reset = (f"<a class='pl-btn' href='/admin/search' title='Scoate toate filtrele'>"
             f"{_ic('close')} Resetează</a>" if dirty else "")
    xlsx_url = "/admin/patients.xlsx" + url()[len("/admin/search"):]
    # Telegram заморожен (08-08), и опция канала здесь идёт ПО ДАННЫМ, а не по
    # tg_configured(): у канарейки-демо токен настроен (grandfather), но
    # пациентов из бота нет — и «Telegram» в фильтре продавал бы замороженный
    # канал на каждом показе программы (08-13, увидел Олег). Клинике, у которой
    # tg-пациенты ЕСТЬ, фильтр остаётся: происхождение пациента — данные, а
    # данные заморозка не прячет (подпись канала в строке и в CSV — та же
    # логика: появляются только у настоящих tg-пациентов).
    canal_items = [(k, v) for k, v in _PL_CANAL.items()
                   if k != "tg" or any(_pl_canal(x) == "tg" for x in everyone)]
    bar = f"""<form class='pl-bar' method='get' action='/admin/search'>
  <label class='pl-search'>{_ic('search')}
    <input name='q' value="{e(q)}" placeholder='Caută pacient, telefon, e-mail…'></label>
  <select name='med' onchange='this.form.submit()'>
    {opts([("-", "— fără medic —")] + [(n, n) for n in doc_names], med, "Toți medicii")}</select>
  <select name='st' onchange='this.form.submit()'>
    {opts([(k, v[0]) for k, v in _PL_BADGE.items()], st, "Toate statusurile")}</select>
  <select name='ch' onchange='this.form.submit()'>
    {opts(canal_items, ch, "Toate canalele")}</select>
  <select name='dat' onchange='this.form.submit()'>
    {opts([("da", "Doar cu datorie"), ("avans", "Doar cu avans")], dat,
          "Orice sold")}</select>
  <input type='hidden' name='sort' value='{sort}'>
  <input type='hidden' name='per' value='{per}'>
  <button class='pl-btn'>Caută</button>{reset}
  <span style='flex:1'></span>
  <a class='pl-btn' href='{xlsx_url}' title='Lista filtrată, ca registru Excel'>
    {_ic('download')} Exportă</a>
  <button type='button' class='pl-btn primary' onclick='newPat()'>＋ Adaugă pacient</button>
</form>"""

    # ---- страница списка ----
    total = len(rows)
    pages = max(1, -(-total // per))
    page = max(1, min(page, pages))
    shown = rows[(page - 1) * per: page * per]

    def head(key: str, label: str) -> str:
        arrow = " " + _ic("caret-d") if sort == key else ""
        return f"<th><a href='{url(sort=key, page=0)}'>{label}{arrow}</a></th>"

    trs = []
    for p in shown:
        label, cls = _PL_BADGE[p["status"]]
        age = _p_age(p)
        mail = (f"<small>{e(p['email'])}</small>" if p["email"]
                else f"<small class='dim'>{_PL_CANAL[_pl_canal(p)]}</small>")
        nxt = (f"<small class='nx' title='Următoarea vizită'>› "
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
            f"<td>{_pl_sold(p['debt'])}</td>"
            f"<td><span class='pl-badge {cls}'>{label}</span></td>"
            f"<td class='pl-acts'>"
            f"<button type='button' title='Previzualizare' "
            f"onclick='event.stopPropagation();peek({p['id']})'>{_ic('eye')}</button>"
            f"<a href='/admin/patient/{p['id']}' title='Deschide fișa' "
            f"onclick='event.stopPropagation()'>{_ic('id')}</a></td></tr>")

    if shown:
        table = (f"<div class='pl-scroll'><table class='pl-tbl'><thead><tr>"
                 f"{head('name', 'Pacient')}<th>Telefon</th>"
                 f"<th class='pl-hide'>Data nașterii</th><th>Medic</th>"
                 f"{head('last', 'Ultima vizită')}{head('debt', 'Sold')}"
                 f"<th>Status</th><th></th>"
                 f"</tr></thead><tbody>{''.join(trs)}</tbody></table></div>")
    elif q or med or st or ch or dat:
        table = (f"<div class='pl-empty'>{_ic('search')}<b>Nimic găsit</b>"
                 "<span>Încercați alt nume, telefon sau scoateți filtrele.</span>"
                 f"<a class='pl-btn' href='/admin/search'>Vezi toți pacienții</a></div>")
    elif n_arh:
        # все живые фиши в архиве. Без этой ветки экран говорил бы «Încă niciun
        # pacient» — то есть «картотека пуста» там, где она просто спрятана
        table = (f"<div class='pl-empty'>{_ic('box')}<b>Toți pacienții sunt în arhivă</b>"
                 f"<span>În listă nu rămâne nimeni: {n_arh} "
                 f"{'fișă arhivată' if n_arh == 1 else 'fișe arhivate'}.</span>"
                 f"<a class='pl-btn' href='{url(st='arhivat', page=0)}'>"
                 f"Arată arhiva</a></div>")
    else:
        table = (f"<div class='pl-empty'>{_ic('users')}<b>Încă niciun pacient</b>"
                 "<span>Fișele apar aici odată cu prima programare — "
                 "din registru sau din bot.</span>"
                 "<button type='button' class='pl-btn primary' onclick='newPat()'>"
                 "＋ Adaugă primul pacient</button></div>")

    # Архивные скрыты из списка намеренно, но молча — и человек, только что
    # отправивший фишу в архив, не находит её и решает, что потерял. Список
    # обязан признаться, что кого-то прячет, и дать дверь.
    hidden_arh = n_arh if not (q or st == "arhivat") else 0
    arh_hint = (f" · {_ic('box')} {hidden_arh} "
                f"{'arhivat' if hidden_arh == 1 else 'arhivați'} "
                f"<a href='{url(st='arhivat', page=0)}'>arată</a>"
                if hidden_arh else "")

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
             f"din {total} pacienți{arh_hint}</span>"
             f"<div class='pl-pgs'>{prev_a}{''.join(nums)}{next_a}</div>"
             f"<form method='get' action='/admin/search'>"
             + "".join(f"<input type='hidden' name='{k}' value=\"{e(str(v))}\">"
                       for k, v in base.items() if v and k != "per")
             + f"<select name='per' onchange='this.form.submit()'>{per_opts}</select>"
             f"</form></div>") if total else ""

    banner = msg_banner(msg)

    body = f"""{banner}
<div class='pl-head'><div><h2>Pacienți</h2>
  <p>Gestionează și caută pacienții clinicii</p></div></div>
{bar}
{tiles}
<div class='pl-grid'>
  <div class='pl-card'>{table}{pager}</div>
  <aside class='ppanel' id='ppanel'>
    <button type='button' class='pp-x' onclick='peekOff()' title='Închide'>{_ic('close')}</button>
    <div id='pp_body'><div class='pp-empty'>{_ic('eye')}<span>Alegeți un pacient din listă
      pentru previzualizare — fără să părăsiți lista</span></div></div>
  </aside>
</div>
<div class='pp-veil' id='pp_veil' onclick='peekOff()'></div>
<dialog id='npdlg'>
  <div class='dlg-head'><span>＋ Pacient nou</span>
    <button type='button' onclick="document.getElementById('npdlg').close()">{_ic('close')}</button></div>
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
/* Предпросмотр обязан ПЕРЕЖИВАТЬ автоперезагрузку журнала (12 с, panel.js):
   выбранный пациент лежит в sessionStorage, после обновления панель
   открывается снова и тянет свежие данные, а кеш прошлой разметки убирает
   мигание «Se încarcă…». Глушить само обновление было бы хуже: у панели на
   широком экране нет кнопки «закрыть», и журнал протухал бы навсегда. */
var PEEK = 0;
function peekLoad(id) {{
  var body = document.getElementById('pp_body');
  var seq = ++PEEK;
  fetch('/admin/patient/' + id + '/peek')
    .then(function (r) {{ return r.text(); }})
    .then(function (t) {{
      if (seq !== PEEK) return;
      body.innerHTML = t;
      try {{ sessionStorage.setItem('dp_peek_html', t); }} catch (e) {{}}
    }})
    .catch(function () {{
      if (seq === PEEK) body.innerHTML =
        '<div class="pp-empty"><span>Nu am putut încărca fișa.</span></div>';
    }});
}}
function peekShow(id) {{
  document.querySelectorAll('.pl-tbl tr.on').forEach(function (r) {{
    r.classList.remove('on');
  }});
  var row = document.getElementById('plr' + id);
  if (row) row.classList.add('on');
  document.getElementById('ppanel').classList.add('open');
  document.getElementById('pp_veil').classList.add('on');
}}
function peek(id) {{
  try {{ sessionStorage.setItem('dp_peek', String(id)); }} catch (e) {{}}
  peekShow(id);
  document.getElementById('pp_body').innerHTML =
    '<div class="pp-empty"><span>Se încarcă…</span></div>';
  peekLoad(id);
}}
function peekOff() {{
  document.getElementById('ppanel').classList.remove('open');
  document.getElementById('pp_veil').classList.remove('on');
  document.querySelectorAll('.pl-tbl tr.on').forEach(function (r) {{
    r.classList.remove('on');
  }});
  try {{
    sessionStorage.removeItem('dp_peek');
    sessionStorage.removeItem('dp_peek_html');
  }} catch (e) {{}}
}}
(function () {{
  var id = null, cached = null;
  try {{
    id = sessionStorage.getItem('dp_peek');
    cached = sessionStorage.getItem('dp_peek_html');
  }} catch (e) {{}}
  if (!id) return;
  /* скрипт стоит в конце body и выполняется ДО первой отрисовки, но выезд
     панели на узком экране — transition, его глушим на один кадр: иначе
     каждые 12 секунд панель заново выезжала бы сбоку */
  var p = document.getElementById('ppanel');
  p.style.transition = 'none';
  peekShow(id);
  requestAnimationFrame(function () {{ p.style.transition = ''; }});
  if (cached) document.getElementById('pp_body').innerHTML = cached;
  peekLoad(id);
}})();
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
           "n_plan": sum(1 for it in plan if it["status"] in db.PLAN_ACTIVE),
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
        # ⚠️ Тот же счёт, что в фише: отказ (refuzat) не входит ни в сумму, ни
        # в знаменатель прогресса — иначе предпросмотр показывал бы «1/2, 50%»
        # там, где фиша говорит «1/1, 100%», и пациент навсегда «в лечении».
        # Статусы — ПЕРЕЧИСЛЕНИЕМ (db.PLAN_ACTIVE), не «всё, что не …».
        done = sum(1 for it in plan if it["status"] == "finalizat")
        n_track = done + sum(1 for it in plan if it["status"] in db.PLAN_ACTIVE)
        paid = sum(it["price_mdl"] or 0 for it in plan if it["status"] == "finalizat")
        tot = paid + sum(it["price_mdl"] or 0 for it in plan
                         if it["status"] in db.PLAN_ACTIVE)
        pct = round(done * 100 / n_track) if n_track else 0
        money = (f"<small>{f'{paid:,}'.replace(',', ' ')} MDL / "
                 f"{f'{tot:,}'.replace(',', ' ')} MDL</small>" if tot else "")
        plan_block = (f"<div class='pp-b'><div class='pp-t'>Plan de tratament"
                      f"<span>{done} / {n_track} finalizate</span></div>"
                      f"<div class='statbar'><div style='width:{pct}%'></div></div>"
                      f"{money}</div>")

    notes = "".join(f"<div class='pp-note {e(a['kind'])}'>"
                    f"{ALERT_KINDS.get(a['kind'], 'ℹ️')} {e(a['text'])}</div>"
                    for a in alerts)
    if p.get("notes"):
        notes += f"<div class='pp-note info'>{_ic('note')} {e(p['notes'])}</div>"
    notes_block = (f"<div class='pp-b'><div class='pp-t'>Notițe</div>{notes}</div>"
                   if notes else "")

    docs_block = ""
    if docs:
        items = []
        for d in docs[:3]:
            kb = d["size"] // 1024
            size = f"{kb} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"
            items.append(f"<a class='pp-doc' href='/admin/doc/{d['id']}'>"
                         f"<span>{_ic('file')}</span><div><b>{e(d['filename'])}</b>"
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
<a class='pl-btn' href='/admin/patient/{pid}'>{_ic('pen')} Editează fișa</a>
{next_block}{last_block}{plan_block}{notes_block}{docs_block}
<div class='pp-foot'><span>{len(live)} vizite în total</span>
  <a class='pl-btn primary' href='/admin/patient/{pid}'>Vezi profilul complet ›</a></div>""")


@router.get("/admin/patients.csv")
async def patients_csv(request: Request, q: str = "", med: str = "", st: str = "",
                       ch: str = "", sort: str = "last", per: int = 20,
                       page: int = 1, dat: str = ""):
    """Тот же список, что на экране, теми же фильтрами — файлом для Excel.
    Страницы намеренно игнорируются: выгружают ВЫБОРКУ, а не её первую сотню."""
    if (deny := _guard(request)) is not None:
        return deny
    now = datetime.now(eng.TZ)
    rows = _pl_filter(await _pl_rows(now), now, q.strip()[:60], med, st, ch, sort,
                      dat if dat in ("da", "avans") else "")

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    # «Sold» числом со знаком, а не «1 200 MDL»: файл открывают в Excel, и
    # разделитель тысяч с валютой превратили бы колонку в текст — по ней не
    # просуммировать и не отсортировать. Минус здесь означает аванс.
    w.writerow(["Nume", "Telefon", "E-mail", "Data nașterii", "Vârstă", "Gen",
                "Medic", "Nr. dosar", "Canal", "Status", "Ultima vizită",
                "Următoarea vizită", "Vizite", "Sold (MDL)", "Înregistrat"])
    for p in rows:
        w.writerow([
            p["name"] or "", p["phone"] or "", p["email"] or "",
            _pl_dmy(p["birth_date"]).replace("—", ""), _p_age(p) or "",
            (p["gender"] or "").upper(), p["doctor"],
            p["file_no"] or "", _PL_CANAL[_pl_canal(p)].split()[-1],
            _PL_BADGE[p["status"]][0], _pl_dmy(p["last_at"]).replace("—", ""),
            _pl_dmy(p["next_at"]).replace("—", ""), p["n_visits"], p["debt"],
            _pl_dmy(p["created_at"]),
        ])
    csv_text = "﻿" + buf.getvalue()   # BOM: иначе Excel ломает диакритику
    fname = f"pacienti_{now.date().isoformat()}.csv"
    return Response(csv_text.encode("utf-8"),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/admin/patients.xlsx")
async def patients_xlsx(request: Request, q: str = "", med: str = "", st: str = "",
                        ch: str = "", sort: str = "last", per: int = 20,
                        page: int = 1, dat: str = ""):
    """Тот же список — КНИГОЙ Excel; кнопка «Exportă» ведёт сюда. CSV не несёт
    типов, и Excel съедал ведущий ноль телефона, а даты показывал решёткой —
    та же беда, что у выгрузки дня до 1.19.23 (скриншот Олега 08-13, разбор в
    хронике). CSV-маршрут жив: его читают интеграции, у которых типы свои.
    Страницы намеренно игнорируются: выгружают ВЫБОРКУ, а не её первую сотню."""
    if (deny := _guard(request)) is not None:
        return deny
    now = datetime.now(eng.TZ)
    rows = _pl_filter(await _pl_rows(now), now, q.strip()[:60], med, st, ch, sort,
                      dat if dat in ("da", "avans") else "")

    def _d(v):
        """Дата для книги. ⚠️ Значение С поясом — в eng.TZ до взятия даты;
        голую birth_date (ISO-текст) НЕ трогать: astimezone на наивном
        подставил бы пояс машины и сдвинул день (грабля «время в базе UTC»)."""
        if isinstance(v, datetime):
            return v.astimezone(eng.TZ).date()
        try:
            return date.fromisoformat(str(v)[:10]) if v else ""
        except ValueError:
            return ""

    data = [[
        p["name"] or "", p["phone"] or "", p["email"] or "",
        _d(p["birth_date"]), _p_age(p) or "",
        (p["gender"] or "").upper(), p["doctor"], p["file_no"] or "",
        _PL_CANAL[_pl_canal(p)].split()[-1], _PL_BADGE[p["status"]][0],
        _d(p["last_at"]), _d(p["next_at"]), p["n_visits"], p["debt"],
        _d(p["created_at"]),
    ] for p in rows]
    blob = xlsx.book(
        ["Nume", "Telefon", "E-mail", "Data nașterii", "Vârstă", "Gen",
         "Medic", "Nr. dosar", "Canal", "Status", "Ultima vizită",
         "Următoarea vizită", "Vizite", "Sold (MDL)", "Înregistrat"],
        data,
        # ширины в знаках — под самое длинное, что в колонке реально бывает
        widths=[24, 14, 26, 13, 8, 6, 22, 10, 10, 16, 13, 13, 8, 11, 12],
        sheet_name="Pacienti",
    )
    fname = f"pacienti_{now.date().isoformat()}.xlsx"
    return Response(
        blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
        # Дубликат ищется по ЦИФРАМ среди ВСЕХ пациентов, а не только по ключу
        # manual:{digits} (та же починка, что в /admin/add 08-07): у пациента
        # из бота ключ tg:…, и путь по ключу заводил ему фишу-двойника —
        # вопреки обещанию формы «nu se dublează». Сначала manual-ключ (прежнее
        # поведение при семейном номере), затем любое совпадение цифр.
        exist = await db.patient_id_by_key(key)
        if exist is None:
            ids = await db._patient_ids_by_digits(digits)
            exist = ids[0] if ids else None
        if exist is not None:
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
