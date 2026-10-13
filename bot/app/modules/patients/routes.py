"""Фиша пациента: правила действий, печатные листы, файлы и адреса экранов.

С 13.10.2026 (снятие старого интерфейса, шаг 4) экраны фиши — только React:
`/admin/patient/{pid}`, `/odontograma`, `/parodontograma`, `/admin/visit/{aid}`
и `/admin/search` отдают рамку с узлом бандла, а данные и действия живут в
JSON API (`api.py`). Здесь остались:
- правила действий — функции, которые зовёт `api.py` (`_save_profile`,
  `_appoint`, `_save_tooth`, `_save_perio`, `_erase`, …): каждая отвечает
  КОДОМ из MSG_BANNER, а конверт строит API;
- печатные листы (acord, plan-acord, 043/e, анкета анамнеза, пародонтограмма)
  — серверные по замыслу: их печатает браузер, а не экран;
- файлы: документ пациента `/admin/doc/{id}`, выгрузка по 195-му `/export`,
  список книгой `/admin/patients.xlsx`.

Правило границы: отсюда можно обращаться в `core` (каркас страницы, вход) и в
`db`/`engine`, но НИКОГДА в main.py — иначе замкнётся круг: main подключает
этот роутер, а роутер требовал бы main.
"""
from __future__ import annotations

import html
import logging
import os
import pathlib
import re
import secrets
import shutil
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.background import BackgroundTask

from ... import db
from ... import engine as eng
from ... import teeth_svg as tsvg
from . import acord as pacord
from . import anamneza as panam
from . import card as pcard
from . import export as pexport
from . import fisa043 as pfisa
from . import odontogram as podo
from . import perio as pperio
from . import plan_acord as pplan
from . import visit as pvisit
from ...core import xlsx
from ...core.auth import _guard
from ...core.layout import (ALERT_KINDS, LIVE_STATUSES, _ic, _initials, react_shell,
                            shell_model)
from ...core.storage import _data_dir

log = logging.getLogger("patients")
router = APIRouter()


# ---------- фиша пациента ----------

# ⚠️ Имена состояний зуба — ОДИН словарь на программу, как STATUS_LABEL у
# статусов визита: дословная копия жила здесь и в teeth_svg, а с 08-16 те же
# слова пишет в летопись db.set_tooth. Три копии разошлись бы молча — на
# соседних экранах у одного состояния завелось бы три имени.
TOOTH_STATES = tsvg.STATE_RO


# Номера и поверхности живут в `odontogram.py` (их спрашивает и модель
# одонтограммы), а импорт возможен только В ОДНУ сторону (routes → odo),
# иначе круг. Здесь — для проверки зуба и позиции плана ниже.
_FDI_ALL = podo.FDI_ALL
TOOTH_SURFACES = podo.TOOTH_SURFACES


# справочник вопросов — в modules/patients/anamneza.py (его читают ещё печать
# и выгрузка; см. докстринг там про то, почему он не здесь)
ANAMNEZA_FLAGS = panam.FLAGS["ro"]


# Словари фиши (категории документов, переходы плана, потолок файла) живут в
# card.py с 18.09 — по ним же JSON API строит фишу. Здесь — для правил ниже.
DOC_CATEGORIES = pcard.DOC_CATEGORIES
_PLAN_EDGES = pcard.PLAN_EDGES
_PLAN_NEEDS_MOTIV = pcard.PLAN_NEEDS_MOTIV
MAX_DOC_MB = pcard.MAX_DOC_MB


def _files_dir(pid: int) -> pathlib.Path:
    base = _data_dir() or pathlib.Path("data")
    d = base / "files" / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    return d


# возраст считает card.age_of (одна арифметика на фишу, список и выгрузки);
# имя здесь сохранено — его импортирует api.py и зовут страницы ниже
_p_age = pcard.age_of


@router.get("/admin/patient/{pid}", response_class=HTMLResponse)
async def admin_patient(request: Request, pid: int, msg: str = "", views: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    # DentPilot 2.0 (C18): та же рамка, узел React с номером фиши и режимом
    # ленты; данные и запись открытия в журнал доступа — у GET
    # /api/patients/{pid}, который клиент зовёт сразу после монтирования.
    # Форма зуба из куска одонтограммы по-прежнему возвращает сюда с
    # ?msg= — плашку рисует msg_banner, как у любой React-страницы.
    params = {"pid": str(pid), **({"views": "1"} if views == "1" else {})}
    # ⭐ B1: оболочку рисует React, сервер печатает голову и модель.
    # подпись печатает сам экран (08.10): крошки «Pacienți › Nume»
    return react_shell("patient_card", f"/admin/patient/{pid}",
                       shell_model("pat", "", msg=msg, title=p["name"]),
                       params)


# ---- правила действий фиши: их зовёт JSON API (api.py) ----
# Каждая функция отвечает КОДОМ из MSG_BANNER (пустая строка — тихий успех),
# api.py превращает его в конверт. Вынесены 18.09 (C18) из обработчиков
# старых форм без единой переписанной проверки; формы сняты 13.10.

async def _save_profile(pid: int, prev: dict, get) -> str:
    """Профиль: `get(поле)` отдаёт сырую строку формы или тела запроса."""
    data = {}
    for f in db.PATIENT_FIELDS:
        v = get(f).strip()[:200 if f != "notes" else 500]
        data[f] = v or None
    # каждая причина отказа называет себя И подсвечивает своё поле в форме
    # (msg → поле, см. card.BAD_FIELD): «Date invalide» без указания куда
    # смотреть читалось как «программа не работает» (Олег, 08-07)
    if not data.get("name"):
        return "bad_card"
    bd = data.get("birth_date")
    bd_year = None
    if bd:
        try:
            parsed = date.fromisoformat(bd)
        except ValueError:
            return "bad_bd"
        if not (1900 <= parsed.year and parsed <= date.today()):
            return "bad_bd"
        data["birth_date"] = parsed.isoformat()
        bd_year = parsed.year
    if data.get("idnp") and not re.fullmatch(r"[0-9]{13}", data["idnp"]):
        return "bad_idnp"
    await db.update_patient(pid, data)
    if bd_year:
        # возраст в поиске/сетке/книге Excel считается по birth_year — держим в синке
        await db.set_birth_year(pid, bd_year)
    elif prev.get("birth_date"):
        # дату ОЧИСТИЛИ — год из неё больше не правда: несброшенный birth_year
        # продолжал бы показывать возраст от удалённой даты в фише, списке и
        # выгрузках. ⚠️ Только когда дата БЫЛА: у пациента из бота год живёт
        # без даты, и обнулять его за пустое поле формы нельзя
        await db.set_birth_year(pid, None)
    # язык печатных документов — мимо PATIENT_FIELDS: колонка NOT NULL, а там
    # пустое поле превращается в NULL
    await db.set_patient_lang(pid, get("lang"))
    # Телефон, вписанный ЗАДНИМ числом, может совпасть с чужим (08-20): дальше
    # запись из журнала по этому номеру уедет «единственному совпавшему», и
    # угадать кому — нельзя. Сохранение проходит (может, это осознанный
    # семейный номер), но названо вслух. ⚠️ Себя исключаем: иначе КАЖДОЕ
    # пересохранение фиши с телефоном предупреждало бы про самого себя, и
    # баннер перестали бы читать раньше, чем он окажется прав (болезнь ok_past
    # на мгновенной границе).
    tel_digits = _pl_digits(data.get("phone"))
    if len(tel_digits) >= 3:
        others = [x for x in await db._patient_ids_by_digits(tel_digits)
                  if x != pid]
        if others:
            return "ok_tel_dup"
    return "ok_card"


async def _free_slots(date_q: str, doctor: str, service: str) -> list[str]:
    """Свободные старты у врача на дату — для окна записи прямо из фиши.
    Тот же eng.free_starts, что у бота: одна правда о занятости на всех.
    Чужой врач, чужая услуга, кривая дата, врач не по услуге — пусто."""
    if doctor not in eng.DOCTORS or service not in eng.SERVICES:
        return []
    try:
        d = date.fromisoformat(date_q)
    except ValueError:
        return []
    allowed = [k for k, _n in eng.allowed_doc_items(service)]
    if doctor not in allowed:
        return []  # услугу этот врач не выполняет
    free = await eng.free_starts(doctor, d, eng.svc_duration(service), allowed)
    return [x.strftime("%H:%M") for x in free]


async def _appoint(pid: int, adate: str, atime: str, adoctor: str, aservice: str) -> str:
    """Запись из фиши: пациент берётся по id, а не по имени/телефону из формы —
    визит физически не может уехать однофамильцу."""
    try:
        d = date.fromisoformat(adate)
        hh, mm = atime.split(":")
        dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return "bad"
    doctor = eng.DOCTORS.get(adoctor)
    svc = eng.SERVICES.get(aservice)
    if not doctor or not svc or dt.minute not in (0, 30):
        return "bad"
    if not eng.DOCTOR_META.get(adoctor, {}).get("active", True):
        return "bad_off"   # выключенному врачу не пишем
    if adoctor not in [k for k, _n in eng.allowed_doc_items(aservice)]:
        return "bad"
    # окно даёт только свободные будущие часы, но вкладку могли открыть утром:
    # к обеду её список устарел и без этой проверки визит уехал бы в прошлое
    if eng.is_past(dt):
        return "past"
    dur = eng.svc_duration(aservice)
    if not eng.fits_clinic(dt, dur):
        return "outside"
    r = await db.add_visit_for_patient(pid, svc["ro"], doctor, dt,
                                       doctor_id=adoctor, service_id=aservice,
                                       duration_min=dur)
    return "ok" if isinstance(r, int) else ("dup" if r == "dup" else "conflict")


async def _add_alert(pid: int, kind: str, text: str) -> str:
    if kind not in ALERT_KINDS or not text.strip():
        return "bad_card"
    await db.add_alert(pid, kind, text.strip()[:120])
    return "ok_card"


def _back_to_card(pid: int, back: str) -> str:
    """Куда ведёт «назад» с печатного листа: на ту ВКЛАДКУ фиши, с которой лист
    открыли (`?back=` в адресе листа), а не на Rezumat (01.10, Олег: «назад»
    с анкеты вёл не туда). Принимается только адрес ЭТОЙ фиши: чужой путь в
    `back` — открытый редирект, и он молча заменяется фишей."""
    base = f"/admin/patient/{pid}"
    if back == base or back.startswith(base + "?"):
        return back
    return base


@router.get("/admin/patient/{pid}/anamneza/print", response_class=HTMLResponse)
async def patient_anamneza_print(request: Request, pid: int, lang: str = "",
                                 back: str = ""):
    """Пустой бланк опросника пациенту на руки. Спрашивать двенадцать пунктов
    голосом через стойку долго и неловко: пациент заполняет лист, пока ждёт,
    рецепция переносит ответы в фишу."""
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    # лист с именем пациента на руки — событие обработки, как acord и 043/e;
    # вид свой: «anamneza» пишет и сохранение опросника (см. card.FORMS)
    await db.log_event(pid, "anamneza_print", "Chestionar medical generat pentru tipărire")
    return panam.render_form(p, _doc_lang(p, lang), _back_to_card(pid, back))


async def _save_anamneza(pid: int, checked: set[str], fields: dict) -> str:
    """Опросник анамнеза. Пустой не сохраняем: «фиша с пустым анамнезом» и
    «анамнез не собирали» — разные вещи, и вторая обязана быть видна."""
    flags = ",".join(k for k in ANAMNEZA_FLAGS if k in checked)
    if not flags and not any(v.strip() for v in fields.values()):
        # пустая форма на ПУСТОМ опроснике — промах, а не ответ: «фиша с
        # пустым анамнезом» и «анамнез не собирали» это разные вещи.
        # Но если опросник УЖЕ есть, пустое сохранение — законное снятие
        # ошибочной отметки (поставили «HIV» не тому), и запретить его
        # значит оставить неверную запись в первичной документации
        if not (await db.anamneza(pid)):
            return "bad_anam"
    await db.save_anamneza(pid, flags, fields)
    return "ok_anam"


@router.get("/admin/patient/{pid}/odontograma", response_class=HTMLResponse)
async def patient_odontogram(request: Request, pid: int, t: str = Query(""),
                             msg: str = Query("")):
    """Детальная одонтограмма отдельной страницей.

    ⚠️ Сайдбар здесь СВОРАЧИВАЕТСЯ (`rail=True`). Причина арифметическая, а не
    вкусовая: дуге нужно 16×38 + 15×10 + поля ≈ 794px, а на 1366 при обычном
    сайдбаре и панели 320 остаётся 762 — тот же расчёт, что записан в panel.css
    над медиазапросом `.pv2`. Со свёрнутым сайдбаром остаётся 922.
    """
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    # DentPilot 2.0 (C21): та же рамка с узким сайдбаром, узел React с
    # фишей и выбранным зубом; данные — GET /api/patients/{pid}/odontogram
    params = {"pid": str(pid)}
    if t.strip().isdecimal() and int(t) in _FDI_ALL:
        params["t"] = t.strip()
    # ⭐ B1: оболочку рисует React; узкий сайдбар — поле модели.
    return react_shell("odontogram", f"/admin/patient/{pid}/odontograma",
                       shell_model("pat", f"odontogramă · #{pid}",
                                   rail=True, msg=msg, title=p["name"]),
                       params)


async def _add_bridge(pid: int, teeth, material: str, material_alt: str,
                      doctor: str) -> str:
    """Мост: `teeth` — список пар [[47, 'stalp'], …] из JSON (строкой
    «47:stalp,…» его слала форма старой фиши; строка и сейчас то, что
    разбирает parse_bridge по белым спискам), порядок и правила дуги —
    bridge_norm. bad_punte — набор мостом быть не может; dup_punte — зуб уже
    в другом мосту."""
    if not isinstance(teeth, str):
        teeth = ",".join(f"{t[0]}:{t[1]}" for t in teeth
                         if isinstance(t, (list, tuple)) and len(t) == 2)
    norm = podo.bridge_norm(tsvg.parse_bridge(teeth))
    if norm is None:
        return "bad_punte"
    mat = (material_alt if material == "alt" else material).strip()[:40]
    # врач — из формы и только из справочника, как у зуба: поле «Medic» в
    # экспорте-195 и летописи — снапшот ЛЕЧАЩЕГО, а вошедшая учётка (нередко
    # «Director» или регистратура) там была бы враньём; автора события и так
    # подписывает летопись сама (ACTOR_HOOK). Пусто — честнее, чем не тот.
    doc = doctor.strip() if doctor.strip() in set(eng.DOCTORS.values()) else ""
    r = await db.add_bridge(pid, norm, mat, doc)
    return "dup_punte" if r == "dup" else "ok_punte"


async def _del_bridge(pid: int, bid: int) -> str:
    return "ok_punte_del" if await db.delete_bridge(bid, pid) else "bad"


# ---------- пародонтограмма ----------

def _perio_absent(tmap: dict) -> set:
    """Зубы, которых по одонтограмме нет. Карта их ПОКАЗЫВАЕТ приглушёнными, но
    ввод не запрещает: одонтограмма может быть не заполнена, а измерение — это
    то, что врач нашёл во рту, и отказ терял бы находку."""
    return {n for n, r in (tmap or {}).items()
            if (r.get("state") or "") in ("lipsa", "extras")}


async def _perio_ctx(pid: int, want: str):
    """Пациент, выбранный осмотр и его строки. Осмотр — из ?exam=, иначе самый
    свежий. ⚠️ Чужой id сюда прийти может (адрес набирают руками), поэтому
    выбор всегда идёт по СПИСКУ осмотров этого пациента, а не по одному id."""
    exams = await db.perio_exams(pid)
    exam = None
    if want.strip().isdecimal():
        exam = next((x for x in exams if x["id"] == int(want)), None)
    return exams, (exam or (exams[0] if exams else None))


# Больше в колонку SQLite INTEGER не влезает. ⛔ Проверять ДЛИНУ, а не только
# «состоит из цифр»: миллион цифр в адресе — это ещё и ValueError самого
# int() (у Python с 3.11 потолок на разбор), то есть 500 вместо отказа.
_EXAM_ID_MAX = 2 ** 63 - 1


def _exam_id(value) -> int | None:
    """Номер осмотра из адреса или формы; None — «такого номера быть не может».

    ⛔ Не просто `isdecimal`: число больше 2^63−1 драйвер SQLite принять не
    может и бросает OverflowError уже внутри `db`. Маршрут отвечал бы голым
    500 «Internal Server Error» вместо конверта с отказом «осмотр не
    найден» (нашло ревью C23 18.09).
    """
    v = str(value).strip()
    if not v.isdecimal() or len(v) > 19:
        return None
    n = int(v)
    return n if 0 < n <= _EXAM_ID_MAX else None


def _perio_doctor(value: str | None, current: str = "") -> str | None:
    """Врач осмотра — снимок ЛЕЧАЩЕГО из справочника, а не вошедшего.

    ⚠️ Три значения, а не два: None — «форма врача не показывала» (ничего не
    трогаем), пустая строка — «стереть», имя из справочника — записать.
    Чужое имя приходит пустотой, а не ошибкой: подпись осмотра не повод
    отказать в сохранении измерений.
    ⚠️ `current` — подпись, которая УЖЕ стоит на осмотре: её врача могли
    переименовать или отправить в архив, и тогда снимка нет в справочнике.
    Без этой ветки первое же дописанное измерение стирало бы подпись
    прошлогоднего осмотра — молча и навсегда, потому что снимок больше нигде
    не хранится.
    """
    if value is None:
        return None
    v = value.strip()
    if v and v == (current or "").strip():
        return v
    return v if v in set(eng.DOCTORS.values()) else ""


async def _save_perio(pid: int, exam: str, parsed: list, covers: set,
                      doctor: str | None, note: str | None,
                      rev: str = "") -> str:
    """Записать измерения осмотра (зовёт `POST /api/patients/{pid}/perio/{eid}`).
    `doctor` приходит СЫРЫМ (как его прислал экран) — сверяет со справочником
    и с прежней подписью `_perio_doctor`, ему для этого нужен сам осмотр.

    ⛔ `covers` — зубы, О КОТОРЫХ экран сообщает: те, что на нём тронули.
    Стираются только они и только неприсланные (db.perio_save): пустой зуб,
    названный в `covers`, значит «измерений больше нет», зуб вне `covers` —
    «не трогали», и это разные вещи (08-16, две потери данных ровно на этом
    различии; 18.09 — потеря чужого зуба при двух рабочих местах).
    ⚠️ `rev` — отпечаток осмотра НА ЗАГРУЗКЕ экрана. Расхождение не отказ:
    запись проходит (безопасной её делает `covers`), но ответ иной — человек
    обязан узнать, что лист под ним успело поправить второе место.
    ⚠️ Отпечаток снимается ДО записи и вне замка `perio_save`: это слово, а не
    замок, и совпавшие по времени сохранения оно просто не заметит.
    """
    eid = _exam_id(exam)
    cur = await db.perio_exam(pid, eid) if eid is not None else None
    if cur is None:
        return "bad_perio"
    merged = bool(rev) and rev != pperio.rev(cur, await db.perio_rows(cur["id"]))
    await db.perio_save(pid, cur["id"], pperio.chart_norm(parsed), covers,
                        doctor=_perio_doctor(doctor, cur.get("doctor") or ""),
                        note=None if note is None else note.strip()[:200])
    return "ok_perio_merged" if merged else "ok_perio"


async def _perio_del(pid: int, eid) -> str:
    """Снять ПУСТОЙ осмотр. Осмотр с измерениями — медицинская запись.
    ⚠️ Несуществующий осмотр — «не найден», а не «в нём есть измерения»:
    `db.perio_drop` отвечает False на оба случая, и человеку доставалась
    фраза про измерения там, где осмотра нет вовсе."""
    n = _exam_id(eid)
    if n is None or not (await db.perio_exam(pid, n)):
        return "bad_perio"
    return "ok_perio_del" if await db.perio_drop(pid, n) else "bad_perio_del"


@router.get("/admin/patient/{pid}/parodontograma", response_class=HTMLResponse)
async def patient_perio(request: Request, pid: int, exam: str = Query(""),
                        msg: str = Query("")):
    """Лист пародонтограммы. ⚠️ Сайдбар свёрнут (`rail=True`) по той же
    арифметике, что у детальной одонтограммы: шестнадцать зубов по шесть точек
    шире, чем окно с обычным сайдбаром.
    ⛔ GET ничего не создаёт: пустой карте — экран «начните осмотр» с кнопкой.
    Иначе каждое обновление страницы плодило бы пустые осмотры."""
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    # DentPilot 2.0 (C23): та же рамка с узким сайдбаром, узел React с
    # фишей и выбранным осмотром; данные — GET /api/patients/{pid}/perio.
    # ⚠️ Проверка id осмотра остаётся серверной (`_perio_ctx`): сюда едет
    # только то, что пришло в адресе, а чужой номер клиент и не увидит.
    params = {"pid": str(pid)}
    if exam.strip().isdecimal():
        params["exam"] = exam.strip()
    # ⭐ B1: оболочку рисует React; узкий сайдбар — поле модели.
    return react_shell("perio", f"/admin/patient/{pid}/parodontograma",
                       shell_model("pat", f"parodontogramă · #{pid}",
                                   rail=True, msg=msg, title=p["name"]),
                       params)


@router.get("/admin/patient/{pid}/parodontograma/print",
            response_class=HTMLResponse)
async def patient_perio_print(request: Request, pid: int,
                              exam: str = Query("")):
    """Печатный лист. Как и 043/e с acord, печать — событие обработки данных и
    пишется в летопись: закон 195 спрашивает, кто и когда доставал карту."""
    if (deny := _guard(request)) is not None:
        return deny
    p = await db.get_patient(pid)
    if not p:
        return RedirectResponse("/admin/search", status_code=303)
    _exams, cur = await _perio_ctx(pid, exam)
    if cur is None:
        return RedirectResponse(
            f"/admin/patient/{pid}/parodontograma?msg=bad_perio",
            status_code=303)
    rows = await db.perio_rows(cur["id"])
    await db.log_event(pid, "perio",
                       f"Parodontogramă {pperio._day(cur['created_at'])} "
                       f"generată pentru tipărire")
    return pperio.print_sheet(p, cur, rows)


def _sf_letters(raw) -> str:
    """Буквы поверхностей из списка или строки — только известные и в
    каноническом порядке MODVL: «OM» и «MO» это одно и то же, а в карте и на
    печати должно читаться одинаково."""
    items = raw if isinstance(raw, (list, tuple)) else list(str(raw))
    got = {str(x).strip().upper() for x in items}
    return "".join(k for k in TOOTH_SURFACES if k in got)


def _sf_map(raw: dict) -> dict:
    """Карта {поверхность: состояние} из словаря тела запроса — по белым
    спискам: буквы из TOOTH_SURFACES, состояния из tsvg.SURFACE_STATES. Одно
    место разбора: пять отдельных полей дали бы пять мест, где проверку можно
    забыть. (Строку «M:carie,O:obturatie» слала форма старой фиши, снятая
    13.10.)"""
    out = {}
    for k, v in raw.items():
        k, v = str(k).strip().upper(), str(v).strip()
        if k in TOOTH_SURFACES and v in tsvg.SURFACE_STATES:
            out[k] = v
    return out


async def _save_tooth(pid: int, tooth: int, state: str, note: str, doctor: str, *,
                      sf: str | None, sfmap: dict | None, state0: str | None,
                      marks: list | None) -> str:
    """Запись зуба (зовёт `POST /api/patients/{pid}/teeth/{n}`; до 13.10 — и
    диалог старой фиши с инспектором детальной страницы). `sf`/`sfmap`/`marks`
    = None означает «экран не сообщал», а не «пусто» (прайор 08-16, две потери
    данных); `state0` — состояние, как его показал экран. Врач — только из
    справочника: свободный текст тут — будущий «Иванов»/«Иванова» в истории
    зуба."""
    if tooth not in _FDI_ALL or state not in TOOTH_STATES:
        return "bad_card"
    doc = doctor.strip() if doctor.strip() in set(eng.DOCTORS.values()) else ""
    await db.set_tooth(pid, tooth, state, note.strip()[:120], doc, sf, sfmap=sfmap,
                       state0=state0 if state0 in TOOTH_STATES else None, marks=marks)
    return "ok_card"


async def _add_plan(pid: int, tooth: str, procedure: str, doctor: str,
                    price: str, due_date: str) -> str:
    """Позиция плана: зуб и цена приходят строками, как из формы; чужой
    номер зуба и кривой срок молча обнуляются, цена режется до миллиона."""
    if not procedure.strip():
        return "bad_card"
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
    return "ok_card"


async def _add_pay(pid: int, amount: str, method: str, note: str) -> str:
    """Платёж записывает ЛЮБАЯ роль: деньги физически берёт рецепция (решение
    Олега 08-07). Минус — возврат. Удаление — только директор."""
    try:
        amt = int(amount.strip())
    except (ValueError, AttributeError):
        return "bad_pay"
    if amt == 0 or abs(amt) > 1_000_000 or method not in db.PAY_METHODS:
        return "bad_pay"
    await db.add_payment(pid, amt, method, note.strip()[:120])
    return "ok_pay"


async def _plan_status(pid: int, item_id: int, to: str, motiv: str) -> str:
    """Переход позиции плана по РЕБРУ (откуда → куда), а не только по цели:
    направление — правило сервера, а не рисунок кнопок; устаревшая вкладка
    не воскресит финал."""
    cur = await db.plan_item_status(item_id, pid)
    if cur is None or (cur, to) not in _PLAN_EDGES:
        return "bad_card"
    why = motiv.strip()[:300]
    # ⭐ Причина требуется СЕРВЕРОМ, а не только атрибутом required в форме:
    # без неё отказ не является записью по ст.13(5) Legea 263/2005 («cu
    # indicarea consecinţelor posibile»), а браузерная проверка обходится
    # любым запросом мимо страницы
    if to in _PLAN_NEEDS_MOTIV and not why:
        return "bad_refuz"
    await db.set_plan_status(item_id, pid, to, motiv=why)
    return "ok_refuz" if to == "refuzat" else ""


async def _plan_del(pid: int, item_id: int) -> str:
    """Удалить можно ТОЛЬКО нетронутую позицию.

    Начатая, выполненная или отказанная — уже медицинская запись: закон велит
    её хранить (043/e — 5 лет), а отказ ст.13(5) прямо требует оставить в
    документации. Опечатку в свежедобавленной строке чинит удаление, всё
    остальное — статус. ⛔ Проверять здесь, а не только прятать кнопку:
    страница живёт в открытой вкладке дольше, чем позиция в «Planificat».
    Позиции у пациента нет — plan_gone, а не тихий успех (см. `api._GONE`).
    """
    cur = await db.plan_item_status(item_id, pid)
    if cur is None:
        return "plan_gone"
    if cur != "planificat":
        return "bad_pdel"
    return "" if await db.delete_plan_item(item_id, pid) else "plan_gone"


async def _store_doc(pid: int, file: UploadFile, category: str) -> str:
    """Файл в папку пациента кусками с потолком MAX_DOC_MB; пустой и
    переполненный не оставляют огрызка на диске."""
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
                    return "bad_doc"
                out.write(chunk)
    except OSError:
        stored.unlink(missing_ok=True)  # диск полон и т.п. — не оставляем огрызок
        return "bad_doc"
    finally:
        await file.close()
    if size == 0:
        stored.unlink(missing_ok=True)
        return "bad_doc"
    await db.add_document(pid, orig, str(stored), size, file.content_type or "", category)
    return "ok_doc"


async def _store_bytes(pid: int, filename: str, data: bytes, mime: str,
                       category: str) -> str:
    """Готовый файл в документы пациента (скан, собранный программой, 01.10):
    та же папка, тот же потолок и та же запись в базе, что у загрузки."""
    if category not in DOC_CATEGORIES:
        category = "alt"
    if not data or len(data) > MAX_DOC_MB * 1024 * 1024:
        return "bad_doc"
    name = pathlib.Path(filename or "document").name[:120] or "document"
    ext = pathlib.Path(name).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,9}", ext):
        ext = ""
    stored = _files_dir(pid) / f"{secrets.token_hex(8)}{ext}"
    try:
        stored.write_bytes(data)
    except OSError:
        stored.unlink(missing_ok=True)
        return "bad_doc"
    await db.add_document(pid, name, str(stored), len(data), mime, category)
    return "ok_doc"


# Что отдавать inline (растр) и что смотреть своим просмотрщиком (PDF) —
# множества в card.py: по ним же API говорит клиенту, чем открывать файл.
# ⛔ SVG и HTML в растр НЕ входят: файл с того же origin, показанный inline, —
# это чужой скрипт в нашем журнале.
_INLINE_MIME = pcard.INLINE_MIME
_PDF_MIME = pcard.PDF_MIME


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


async def _open_doc(request: Request, doc_id: int) -> str:
    """Открыть документ программой этого же компьютера (Word, Excel, просмотр
    фото). Только настольное издание и только локальный запрос: журнал не
    должен запускать программы на компьютере клиники по команде из сети.
    Пустая строка — открыто; иначе причина отказа (not_local / missing /
    ext / os), и вызывающий откатывается на скачивание."""
    host = request.client.host if request.client else ""
    if os.name != "nt" or host not in ("127.0.0.1", "::1"):
        return "not_local"
    d = await db.get_document(doc_id)
    if not d or not pathlib.Path(d["stored_path"]).exists():
        return "missing"
    src = pathlib.Path(d["stored_path"])
    if src.suffix.lower() not in _OPEN_EXT:
        return "ext"
    await db.log_event(d["patient_id"], "doc_view",
                       f"Document deschis: {d['filename']}")
    try:
        # startfile не блокирует: ShellExecute возвращает управление сразу,
        # не дожидаясь, пока Word нарисует окно
        os.startfile(_open_copy(src, d["filename"]))
    except OSError as ex:                     # нет ассоциации у расширения и т.п.
        log.warning("startfile doc=%s: %r", doc_id, ex)
        return "os"
    return ""


async def _erase(pid: int, confirm: str) -> str:
    """Право на стирание. Ветку выбирает НЕ рецепция, а состояние фиши
    (db.erasure_kind): физическое удаление доступно только контакту без
    лечения (ok_del — фиши больше нет), у пациента с медзаписями стирается
    личность, клиника остаётся (ok_anon).

    Подтверждение — переписанное слово, не галочка: действие необратимо, а
    кнопка стоит в фише рядом с обычными. confirm сверяется здесь, на сервере —
    JS-диалог легко проскочить двойным Enter.
    """
    if confirm.strip().upper() != "STERG":
        return "bad_erase"
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
        return "ok_del"
    await db.anonymize_patient(pid)
    # событие — в летопись, которая у обезличенного остаётся: проверяющему
    # видно, что стирание состоялось и когда
    await db.log_event(pid, "erase", "Date personale șterse (anonimizare)")
    return "ok_anon"


def _doc_lang(p: dict, lang: str) -> str:
    """Язык печатного листа: явный выбор в адресе, иначе язык пациента.
    Русский заполнен осмысленно только у пришедших из бота — остальным его
    ставит рецепция в профиле; дефолт остаётся румынским."""
    if lang in pacord.LANGS:
        return lang
    return (p.get("lang") or "ro") if (p.get("lang") in pacord.LANGS) else "ro"


@router.get("/admin/patient/{pid}/acord", response_class=HTMLResponse)
async def patient_acord(request: Request, pid: int, lang: str = "", back: str = ""):
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
    return pacord.render(p, _doc_lang(p, lang), _back_to_card(pid, back))


@router.get("/admin/patient/{pid}/plan-acord", response_class=HTMLResponse)
async def patient_plan_acord(request: Request, pid: int, lang: str = "",
                             back: str = ""):
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
    return pplan.render(p, plan, diag, _doc_lang(p, lang), _back_to_card(pid, back))


# ---------- дневник визита (consultația) ----------

# ---- дневник визита: контекст и правило сохранения (C19; зовёт api.py) ----

async def _visit_ctx(appt_id: int):
    """(визит, запись приёма, позиции плана пациента) или None — визита нет,
    это заметка без пациента. patient_id отсюда — источник истины «чей
    визит»: маршруты берут его из выборки, а не из формы."""
    a = await db.appointment_brief(appt_id)
    if not a or not a.get("patient_id") or a.get("source") == "note":
        return None
    return a, await db.visit_record(appt_id), await db.plan_items(a["patient_id"])


def _visit_back(back: str, pid: int) -> str:
    """Куда ведёт «Înapoi»: только адрес журнала, иначе фиша пациента —
    чужая строка здесь была бы открытым редиректом."""
    return back if back.startswith("/admin") else f"/admin/patient/{pid}"


async def _save_visit(appt_id: int, a: dict, fields: dict, done: list) -> str:
    """Запись приёма: отменённому/неявившемуся не пишется (bad_vst), пустая
    не сохраняется (bad_visit); отмеченные позиции плана финализируются НА
    этом визите."""
    pid = a["patient_id"]
    if a["status"] in pvisit.NO_FORM_STATUSES:
        return "bad_vst"
    fields = {k: str(fields.get(k) or "")[:2000] for k in db.VISIT_FIELDS}
    if not any(v.strip() for v in fields.values()):
        return "bad_visit"
    await db.save_visit_record(appt_id, pid, a["doctor"], fields)
    # отмеченные позиции плана выполнены НА этом визите: финализируем из
    # любого нефинального статуса (дневник фиксирует факт, церемония
    # in_lucru тут ни при чём) и привязываем к визиту
    for raw in done:
        try:
            iid = int(raw)
        except (TypeError, ValueError):
            continue
        cur = await db.plan_item_status(iid, pid)
        # ⚠️ финализируем только АКТИВНОЕ: отказ (refuzat) в списке галочек не
        # показывается, но устаревшая вкладка прислала бы его id — и запись по
        # ст.13(5) молча превратилась бы в «выполнено»
        if cur in db.PLAN_ACTIVE:
            await db.set_plan_status(iid, pid, "finalizat", appt_id)
    return "ok_visit"


@router.get("/admin/visit/{appt_id}", response_class=HTMLResponse)
async def visit_page(request: Request, appt_id: int, back: str = "",
                     msg: str = ""):
    """Страница «Consultație»: запись приёма 1:1 к визиту (см. visit.py).
    Доступна любому вошедшему, как и остальные операции фиши: приём пишет
    врач, но постфактум вносит и рецепция."""
    if (deny := _guard(request)) is not None:
        return deny
    ctx = await _visit_ctx(appt_id)
    if ctx is None:
        return RedirectResponse("/admin", status_code=303)
    a, rec, items = ctx
    back = _visit_back(back, a["patient_id"])
    # DentPilot 2.0 (C19): та же рамка, узел React с номером визита и
    # адресом возврата; данные — у GET /api/visits/{aid}
    # ⭐ B1: оболочку рисует React, сервер печатает голову и модель.
    return react_shell("visit", f"/admin/visit/{appt_id}",
                       shell_model("pat", f"consultație · vizita #{appt_id}", msg=msg,
                                   title=a.get("name") or ""),
                       {"aid": str(appt_id), "back": back})


@router.get("/admin/patient/{pid}/fisa043", response_class=HTMLResponse)
async def patient_fisa043(request: Request, pid: int, lang: str = "", back: str = ""):
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
    punti = await db.bridges(pid)
    # ⚠️ Строка пародонта — из ПОСЛЕДНЕГО осмотра С ИЗМЕРЕНИЯМИ, и на языке
    # листа: бланк бывает русским, а слова итога живут в perio._SUM_WORDS.
    p_exam, p_rows = await db.perio_last(pid)
    await db.log_event(pid, "fisa043", "Fișa 043/e generată pentru tipărire")
    doc_lang = _doc_lang(p, lang)
    # подписи отметок — на языке ЛИСТА: иначе русский бланк печатал бы
    # «Diabet zaharat» в русской же строке «Перенесённые заболевания»
    return pfisa.render(p, alerts, teeth, plan, list(reversed(recs)), rx,
                        _p_age(p), anam, panam.labels(doc_lang), doc_lang,
                        punti, pperio.summary_line(p_exam, p_rows, doc_lang),
                        _back_to_card(pid, back))


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
        return RedirectResponse(f"/admin/patient/{pid}?msg=bad_export", status_code=303)
    if data is None:
        shutil.rmtree(tmp, ignore_errors=True)
        return RedirectResponse("/admin/search", status_code=303)
    await db.log_event(pid, "export", "Copie a datelor personale eliberată")
    return FileResponse(
        dest, filename=pexport.archive_name(data), media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


async def _drop_doc(pid: int, doc_id: int) -> bool:
    """Файл и миниатюра с диска, строка из базы; чужой документ не трогается.
    False — у пациента такого документа нет."""
    d = await db.get_document(doc_id)
    if not d or d["patient_id"] != pid:
        return False
    pathlib.Path(d["stored_path"]).unlink(missing_ok=True)
    _thumb_path(d["stored_path"]).unlink(missing_ok=True)
    return await db.delete_document(doc_id, pid)


# ---------- раздел «Pacienți»: список клиники (макет Олега 08-06) ----------
#
# Экран — React (`GET /api/patients`): отбор, порядок и страницу считает база
# (`db.patients_rows`). Здесь — общее у экрана и книги `.xlsx`: словари
# статусов и каналов, разбор запроса, отбор словарём, подписи карточек.
# ⭐ До 13.10 правило отбора жило ДВАЖДЫ — Python старой страницы и SQL API
# (паритет держал набор). Старая страница снята, а с ней и копия: книга Excel
# берёт ту же выборку, что экран, и разойтись им негде.

_PL_PER = (10, 20, 50)

_PL_SORTS = ("last", "name", "new", "debt")

_PL_INACTIVE_DAYS = 365


# Статуса пациента в базе НЕТ — он выводится из того, что уже есть: архив,
# медицинские предупреждения, незакрытый план, давность последнего визита.
# Порядок словаря = приоритет бейджа: первым показываем то, ради чего список
# вообще открывают. Фильтр по статусу, наоборот, ВКЛЮЧАЮЩИЙ (`db._PlQuery`):
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


def _pl_digits(s) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _pl_terms(q: str) -> dict:
    """Что именно ищется по строке запроса — куски для `db.patients_rows`
    (отбор пишется на SQL, `db._PlQuery`): имя, e-mail и
    номер дела без учёта диакритики (от двух знаков), дата рождения как её
    диктуют на стойке (01.01.2003, принимаем и без ведущих нулей — 1.1.2003),
    цифры телефона от трёх ('069 12' и '069-12' обязаны искать одинаково;
    цифры ищутся и в notes, где живёт номер второго человека на семейном
    телефоне). Невозможные день/месяц (99.99.2003) дают ISO, которого нет ни
    у кого. Пустой словарь — запрос не находит никого."""
    out: dict = {}
    qf = db.fold(q)
    if len(qf) >= 2:
        out["fold"] = qf
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", q.strip())
    if m:
        out["birth"] = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    digits = _pl_digits(q)
    if len(digits) >= 3:
        out["digits"] = digits
    return out


def _pl_stale_cut(now: datetime) -> datetime:
    """Граница «неактивен» для SQL: `_pl_stale` считает `(now - last).days > 365`,
    а это ровно «последний визит не позже, чем now − 366 дней»."""
    return now - timedelta(days=_PL_INACTIVE_DAYS + 1)


def _pl_select(now: datetime, q: str, med: str, st: str, ch: str, dat: str) -> dict:
    """Отбор списка словарём для `db.patients_rows` — один на экран (`GET
    /api/patients`) и на книгу `.xlsx`: кто виден в списке, тот и уезжает в
    Excel. Неизвестные st/ch/dat откатываются к «все». Архивные скрыты, пока
    их не спросили явно — поиском или фильтром: фишу с историей лечения
    нельзя терять, её именно прячут."""
    q = q.strip()[:60]
    st = st if st in _PL_BADGE else ""
    ch = ch if ch in _PL_CANAL else ""
    dat = dat if dat in ("da", "avans") else ""
    return {"q": q, "terms": _pl_terms(q), "med": med, "st": st, "ch": ch, "dat": dat,
            "show_archived": bool(q) or st == "arhivat",
            "stale_cut": _pl_stale_cut(now), "now": now}


def _pl_money(n: int) -> str:
    """2550 → «2 550». Разделитель тысяч — просьба Олега: без него четырёх- и
    пятизначные суммы читаются с запинкой."""
    return f"{n:,}".replace(",", " ")


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


def _pl_new_foot(n_new: int) -> str:
    """Подпись первой карточки над списком: сколько новых за месяц."""
    return (f"<span class='up'>+{n_new}</span> luna aceasta" if n_new
            else "niciun pacient nou luna aceasta")


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
    # отбор из адреса уезжает параметрами узла, чтобы ссылки «?q=телефон»
    # из фиши и журнала открывали тот же список
    params = {k: v for k, v in (("q", q.strip()[:60]), ("med", med),
                                ("st", st), ("ch", ch), ("dat", dat)) if v}
    if sort != "last":
        params["sort"] = sort
    if page != 1:
        params["page"] = str(page)
    if per != 20:
        params["per"] = str(per)
    # ⭐ B1: оболочку рисует React, сервер печатает голову и модель.
    # подпись печатает сам экран (08.10): «12 afișați din 19 · +9 luna
    # aceasta» — числа списка, а не описание раздела
    return react_shell("patients_search", request.url.path,
                       shell_model("pat", "", msg=msg),
                       params or None)


async def _peek_html(pid: int) -> str | None:
    """Кусок предпросмотра для `GET /api/patients/{pid}/peek`: экран списка
    вставляет его как есть. Это сводка фиши словами сервера, все значения
    экранированы здесь, поэтому второго рисовальщика у неё нет. None — фиши
    нет."""
    p = await db.get_patient(pid)
    if not p:
        return None
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

    # `last` — экран React красит этот блок серым (макет 08.10)
    last_block = ("<div class='pp-b last'><div class='pp-t'>Ultima vizită"
                  f"<span>{_pl_dmy(lastv['starts_at'])}</span></div>"
                  f"<b>{e(lastv['service'])}</b><small>{e(lastv['doctor'])}</small></div>"
                  if lastv else
                  "<div class='pp-b last'><div class='pp-t'>Ultima vizită</div>"
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

    return f"""<div class='pp-head'>
  <span class='pp-av'>{e(_initials(p['name'] or '?'))}</span>
  <div class='pp-id'><b>{e(p['name'] or '—')}</b>
    <span class='pl-badge {cls}'>{label}</span></div>
</div>
<div class='pp-info'>{info}</div>
{next_block}{last_block}{plan_block}{notes_block}{docs_block}
<div class='pp-foot'><span>{len(live)} vizite în total</span>
  <div class='pp-btns'><a class='pl-btn' href='/admin/patient/{pid}'>{_ic('pen')} Editează</a>
  <a class='pl-btn primary' href='/admin/patient/{pid}'>Profil complet ›</a></div></div>"""


@router.get("/admin/patients.xlsx")
async def patients_xlsx(request: Request, q: str = "", med: str = "", st: str = "",
                        ch: str = "", sort: str = "last", dat: str = ""):
    """Список КНИГОЙ Excel; кнопка «Exportă» экрана ведёт сюда с его отбором.
    Выборка та же, что у экрана (`_pl_select` → `db.patients_rows`), только
    целиком: выгружают ВЫБОРКУ, а не её страницу. Книга, а не CSV: CSV не
    несёт типов, и Excel съедал ведущий ноль телефона, а даты показывал
    решёткой — та же беда, что у выгрузки дня до 1.19.23 (скриншот Олега
    08-13, разбор в хронике). CSV-маршрут снят 13.10 (слово Олега 12.10)."""
    if (deny := _guard(request)) is not None:
        return deny
    now = datetime.now(eng.TZ)
    rows = await db.patients_rows(_pl_select(now, q, med, st, ch, dat),
                                  sort if sort in _PL_SORTS else "last", None, 0)

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
        # врач строки — как у экрана: медик курант, иначе врач последнего визита
        (p["gender"] or "").upper(), p["primary_doctor"] or p["last_doctor"] or "",
        p["file_no"] or "",
        _PL_CANAL[_pl_canal(p)].split()[-1], _PL_BADGE[_pl_status(p, now)][0],
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


async def _new_patient(name: str, phone: str, birth_date: str, email: str,
                       primary_doctor: str) -> tuple[str, int | None]:
    """Правило новой фиши (`POST /api/patients`, диалог «Pacient nou»): (код,
    id фиши). bad_pat — без имени; dup_pat — фиша с таким телефоном уже есть,
    и открывается ОНА; new_pat — заведена.

    ⚠️ Ключ `manual:{цифры}` СКЛЕИВАЕТ пациентов по телефону — на то он и
    заведён, чтобы бот и регистратура не плодили двойников. Поэтому при
    совпадении открываем существующую фишу, а не создаём: `_upsert_patient`
    на конфликте перезаписал бы имя, и семейный номер тихо переименовал бы
    родителя в ребёнка."""
    name = name.strip()[:120]
    if not name:
        return "bad_pat", None
    phone = phone.strip()[:40]
    digits = _pl_digits(phone)
    if len(digits) >= 3:
        key = db.manual_key(digits)
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
            return "dup_pat", exist
    else:
        # без телефона склеивать не по чему — ключ уникальный (db.manual_key,
        # с 08-20 ЕДИНСТВЕННОЕ место сборки: журнал ходит туда же)
        key = db.manual_key("")
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
    return "new_pat", pid
