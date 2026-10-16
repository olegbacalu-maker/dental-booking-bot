"""Журнал клиники: адреса экранов и правила, которые зовёт `api.py`.

С 13.10 (снятие старого интерфейса, шаг 5) экраны журнала — панель дня
`/admin`, неделя, «Programări» (`/admin/all`, день врача) и кресло — рисует
только React: обработчик здесь отдаёт оболочку (`react_shell`), данные идут
через `/api/schedule/*` (`api.py`). Здесь остались:
- модели, которые собирает и панель, и день (`_panel_live`, `_day_model`,
  `_week_model`) — из одной выборки, тем же цветом (`_svc_colors`);
- правила действий журнала (`_add_appt`, `_add_note`, `_set_comment`,
  `_move_appt`, `_set_status`): JSON API зовёт их, своих проверок у него нет;
- выгрузка дня в Excel (кнопка «Excel» на «Programări» и в статистике).

Правило то же, что у пациентов: сюда можно смотреть в `core`, `db` и `engine`,
и нельзя — в `main.py`.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ... import db
from ... import engine as eng
from ...core.auth import _guard, request_user
from ...core import xlsx
from ...core.layout import react_shell, shell_model
from ...core.visits import (SVC_PALETTE, _collect_cards, _parse_date,
                            all_status_actions)
from . import canvas as pcanvas
from . import chair as pchair
from . import day as pday
from . import desk as pdesk
from . import panel as ppanel
from . import week as pweek

router = APIRouter()


_SVC_CAT = [
    (re.compile(r"urgent|sos|durere|acut", re.I), ("var(--red-soft)", "var(--red)")),
    (re.compile(r"implant|extract|chirur|sinus", re.I), ("var(--blue-soft)", "var(--blue)")),
    (re.compile(r"hyg|igien|airflow|detartraj|fluor", re.I), ("var(--amber-soft)", "var(--amber)")),
    (re.compile(r"whiten|albire|estet|fatet|venir", re.I), ("var(--violet-soft)", "var(--violet)")),
]


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


# месяцы словами — список модели дня (`day.RO_MONTHS`): мини-календарь панели
# и дата словами
_RO_MONTHS = pday.RO_MONTHS


# бейдж строки повестки: тот же компонент, что в списке пациентов (.pl-badge) —
# один вид состояния на всю программу, а не свой значок на каждом экране
# Плашка повестки: ЦВЕТ здесь, а ТЕКСТ — из layout.STATUS_LABEL. Своя пара
# «класс + слово» держалась ровно до тех пор, пока слова совпадали: 08-12
# оказалось, что один статус зовут «Finalizat» в повестке, «a venit» в списке
# дня и «finalizată» в летописи пациента — три имени одного состояния на
# соседних экранах.
# waiting — свой класс «wai» (фиолетовый), а не жёлтый «att»: цвет статуса
# обязан совпадать со .stat s-waiting в «Lista zilei» — один статус, один цвет
# 03.10: «programată» — контуром (ещё не подтверждена), зелёный — только
# «confirmată» после звонка, «nu răspunde» — янтарный. Ключи — из
# layout.status_view, а не коды базы: звонок статуса не меняет.
# «finalizată» — зелёная (09.10, разбор: серая на серой карточке не читалась),
# тот же цвет, что у слова статуса на блоке сетки (.stat.s-done в panel.css).
_AG_CLS = {"confirmed": "pln", "called": "act", "noanswer": "att",
           "waiting": "wai", "arrived": "trt", "done": "act", "noshow": "bad"}


@router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, date_q: str = Query("", alias="date"), msg: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    # DentPilot 2.0 (C26.5): данные — GET /api/schedule/live?screen=panel;
    # старой панели нет с 13.10.
    # ⭐ B1: оболочку рисует React. Требование «увидеть при ПЕРВОЙ
    # отрисовке» держит баннер: `msg` едет моделью оболочки (`frame.msg`)
    # и первого ответа канала не ждёт. На `/admin` приземляется
    # `no_access` со ВСЕЙ программы (двенадцать проверок прав сверяют
    # редирект сюда), поэтому требование и названо.
    # ⛔ Дня в узле НЕТ — ни даты, ни подписи (решение Олега 24.09). Узел
    # описывает ДОКУМЕНТ, то есть момент загрузки: день из него застывал,
    # и вкладка, оставленная на ночь, утром показывала вчера, хотя старая
    # панель на том же адресе переходила на новый день сама. Экран берёт
    # день из АДРЕСА (пусто — «сегодня» сервера), а шапку строит по эху
    # канала (`date`, `day_label`). Цена названа: шапка приходит вместе с
    # панелью первым ответом канала, а не первым кадром.
    # ⛔ «Zi liberă» сервер больше НЕ печатает, и это исправление, а не
    # переезд: фраза выводилась ДВАЖДЫ — баннером по `hours_for` (только
    # график) и холстом по `hours_of` (график И записи). В закрытом дне, где
    # запись осталась с тех пор, когда день был рабочим, баннер сообщал
    # «clinica este închisă» прямо над нарисованной записью. Владелец
    # остался один — холст, у него условие полное.
    # ⭐ Подзаголовок панели печатает САМ экран (08.10, промпт 1): дата
    # словами и сводка дня приезжают конвертом канала (`day_long`, повестка,
    # загрузка), и у оболочки для него строки нет — пустая не рисуется.
    return react_shell("schedule_dash", "/admin",
                       shell_model("dash", "", msg=msg))


async def _week_model(d: date) -> dict:
    """Неделя данными: ОДИН запрос к базе на всю неделю вместо семи.

    ⚠️ Правила живут в `week.py` и ничего не знают о разметке — их же возьмёт
    JSON API. Цвет передаётся функцией: он общий с днём и агендой, а импорт
    `routes` из `week` замкнул бы круг.
    """
    monday = pweek.monday_of(d)
    start, end = pweek.week_span(monday)
    rows = await db.day_appointments(start, end)
    return pweek.model(monday, pweek.by_day(rows),
                       datetime.now(eng.TZ).date(), _svc_colors)


@router.get("/admin/week", response_class=HTMLResponse)
async def admin_week(request: Request, date_q: str = Query("", alias="date")):
    """Недельный календарь: колонки рабочих дней, компактные чипы записей."""
    if (deny := _guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    # DentPilot 2.0 (C24): данные — GET /api/schedule/week.
    # ⭐ (06.10, Олег) Неделя — раздел «Programări», а не панель: ключ
    # `prog` подсвечивает его пункт меню и называет страницу его словом.
    # ⭐ B1: оболочку рисует React.
    return react_shell("schedule_week", "/admin/week",
                       shell_model("prog",
                                   "calendar săptămânal · culori după tipul procedurii"),
                       {"date": d.isoformat()})


# ⭐ Выгрузка дня — книгой Excel с ТИПАМИ. CSV их не несёт, и Excel угадывает:
# телефон `022447788` он считает числом и роняет ведущий ноль (в Молдове все
# номера с нуля — по такой таблице не позвонить), а дату не вмещает в колонку
# по умолчанию и рисует `########`. Второе кричит, первое молчит — потому эта
# кнопка и стала основной, а CSV-выгрузка `/admin/export` снята вовсе (слово
# Олега 12.10: «CSV удаляем, остаётся xlsx»).
@router.get("/admin/export.xlsx")
async def admin_export_xlsx(
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

    data = []
    for r in rows:
        dt = r["starts_at"].astimezone(eng.TZ)
        data.append([
            dt.date(), dt.strftime("%H:%M"),
            r["name"] or ("— notiță —" if r["source"] == "note" else ""),
            int(r["birth_year"]) if r["birth_year"] else "",
            r["phone"] or "", r["service"], r["doctor"], r["source"], r["status"],
            "da" if r["reminded_day"] or r.get("sms_sent") else "", r["comment"] or "",
        ])
    blob = xlsx.book(
        ["Data", "Ora", "Pacient", "An naștere", "Telefon", "Serviciu",
         "Medic", "Sursă", "Status", "Reminder", "Comentariu"],
        data,
        # ширины в знаках — под самое длинное, что в колонке реально бывает:
        # это и есть вторая половина ответа на «дата не влезает»
        widths=[11, 7, 22, 11, 14, 26, 22, 9, 12, 10, 34],
    )
    fname = f"programari_{d1.isoformat()}_{d2.isoformat()}.xlsx"
    return Response(
        blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _of_doctor(r: dict, dk: str) -> bool:
    """Строка дня принадлежит врачу `dk`: по `doctor_id`, а у легаси-строки
    без него — по снимку имени. ⛔ Одно правило на всех, кто режет день по
    врачу (сетка врача, его страница, экран кресла): третья копия условия
    однажды забыла бы легаси-ветку, и старая запись пропала бы с одного экрана,
    оставаясь на другом."""
    return (r.get("doctor_id") == dk
            or (not r.get("doctor_id") and r["doctor"] == eng.DOCTORS.get(dk)))


async def _day_model(d: date, doctor: str = "", f: str = "") -> dict | None:
    """День экрана «Programări» — один на «Toți medicii» и на день врача.

    `doctor` пуст — все врачи и все записи; иначе один врач и ТОЛЬКО его
    записи, включая легаси-строки без `doctor_id`, найденные по снимку имени.
    None — такого врача в справочнике нет.
    """
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = await db.day_appointments(day_start, day_start + timedelta(days=1))
    if doctor:
        if doctor not in eng.DOCTORS:
            return None
        name = eng.DOCTORS[doctor]
        rows = [r for r in rows if _of_doctor(r, doctor)]
        items = [(doctor, name)]
        # у выключенного врача формы нет вовсе — как на его странице
        form_items = (items if eng.DOCTOR_META.get(doctor, {}).get("active", True)
                      else None)
    else:
        # неактивный врач остаётся колонкой, пока у него есть записи этого дня
        busy_keys = {r.get("doctor_id") for r in rows if r["status"] != "cancelled"}
        busy_names = {r["doctor"] for r in rows if r["status"] != "cancelled"}
        items = [(dk, n) for dk, n in eng.DOCTORS.items()
                 if eng.DOCTOR_META.get(dk, {}).get("active", True)
                 or dk in busy_keys or n in busy_names]
        # ⛔ форме — АКТИВНЫЕ справочника: выключенному запись ответит bad_off
        form_items = list(eng.ACTIVE_DOCTORS.items()) or items
    # ⚠️ отбор «Lista zilei» — только у общего дня: день врача его не читает
    cards = _collect_cards(rows)
    m = pday.model(d, items, cards, form_items, rows, "" if doctor else f)
    # ⭐ (06.10) Экран «Programări» рисует ТУ ЖЕ канву, что панель дня: те же
    # шапки врачей, цвета и геометрия. Канва строится тем же `canvas.model`
    # из тех же строк — у общего дня она совпадает с канвой панели того же
    # дня (держит test_schedule_api), у дня врача в ней одна колонка.
    m["canvas"] = pcanvas.model(d, rows, cards, _svc_colors, only=doctor)
    return m


async def _panel_live(d: date, now: datetime) -> dict:
    """Живое состояние панели данными: канва, повестка и загрузка — от ОДНОЙ
    выборки дня.

    ⛔ Выборка одна не ради скорости. Части панели обязаны отвечать про один и
    тот же день: два запроса к базе подряд — это два РАЗНЫХ дня, если между
    ними кто-то записался со второго рабочего места, и живой канал отдал бы
    состояние, которого никогда не было ни на одном экране.
    ⚠️ Окно — ОДИН день. До 13.10 оно было двухнедельным: из него брались
    плитки «Azi» с трендами к вчера и ряды мини-графиков, а с ними — тренд
    загрузки «ieri X% › azi Y%». Плитки React не рисует с 01.10 (их цифры —
    строкой в подзаголовке), и со старой панелью ушли и они, и их окно.
    ⚠️ `now` приходит АРГУМЕНТОМ: от него зависит `state` повестки, и проверке
    нужна возможность назвать момент.
    """
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = await db.day_appointments(day_start, day_start + timedelta(days=1))
    cards = _collect_cards(rows)
    active_dks = [dk for dk in eng.DOCTORS
                  if eng.DOCTOR_META.get(dk, {}).get("active", True)]
    # Точки мини-календаря (08.10): дни окна месяца с живой записью. Окно —
    # те же полные недели, что рисует `panel.minical` (с понедельника перед
    # первым числом, шесть недель с запасом); выборка лёгкая, три колонки.
    # ⚠️ Правило «живая запись» то же, что у повестки и загрузки: без
    # отменённых и без заметок стойки.
    first = d.replace(day=1)
    m_start = first - timedelta(days=first.weekday())
    m0 = datetime(m_start.year, m_start.month, m_start.day, tzinfo=eng.TZ)
    busy_days = {r["starts_at"].astimezone(eng.TZ).date()
                 for r in await db.appointment_days(m0, m0 + timedelta(days=42))
                 if r["status"] != "cancelled" and r["source"] != "note"}
    return {
        # ⭐ Подпись дня для шапки — В КОНВЕРТЕ, рядом с эхом `date` (решение
        # Олега 24.09). Адрес панели без `?date=` значит «сегодня сервера», и в
        # полночь новый день приезжает ОДНИМ ответом — дата, подпись и данные
        # вместе. Из узла подпись застывала на моменте загрузки. Отпечаток она
        # не шевелит: для одного дня она одна и та же, меняется вместе с датой.
        "day_label": pday.day_title(d),
        # дата словами — под заголовок панели (08.10, макет); та же причина
        # быть в конверте, что у `day_label`
        "day_long": pday.day_long(d, _RO_MONTHS),
        "canvas": pcanvas.model(d, rows, cards, _svc_colors),
        "agenda": ppanel.agenda(d, rows, cards, _svc_colors, _AG_CLS, now),
        # ⚠️ `now.date()`, а не `d`: «сегодня» в календаре — это сегодня, а не
        # день, на который смотрят. Подставь `d` — и метка «tdy» поедет вслед
        # за листанием, перестав отвечать на вопрос, ради которого она есть.
        "minical": ppanel.minical(d, now.date(), _RO_MONTHS, busy=busy_days),
        # загрузка кресел дня — подзаголовок панели («N programări · X% grad
        # de ocupare»); та же формула, что у «Statistici» и карточки врача
        "occupancy": {"value": ppanel.occupancy_pct(d, rows, active_dks)},
        # ---- то, чем живут диалоги (C26.5.3-a) ----
        # ⭐ В КОНВЕРТЕ, а не вторым каналом, и это решение. Матрица кнопок и
        # списки диалога постоянны — значит отпечаток они не двигают НИКОГДА,
        # и правило «отпечаток двинулся ⇒ на экране что-то изменилось» цело.
        # Второй канал (параметр узла, отдельный GET) — это второе место, где
        # можно забыть, а цена забывания — диалог без кнопок на одном экране
        # из двух. Модель дня возит их тем же способом, то есть способ один.
        # ⚠️ Цена названа: около килограмма с небольшим байт на каждый ответ
        # 200 по 127.0.0.1.
        "actions": all_status_actions(),
        "note_actions": all_status_actions(is_note=True),
        "note_ends": pday.note_ends(d),
        "slotform": pday.slot_form(d),
        # ---- «La recepție» (01.10): списки стойки — тем же конвертом ----
        # ⭐ Про СЕГОДНЯ (`now`), а не про день, на который смотрят: звонки на
        # завтра и касса не зависят от листания календаря. В конверте — чтобы
        # отметка звонка со второго места доехала живым каналом, как запись.
        "desk": await pdesk.desk_model(now),
    }


async def _canvas_model(d: date) -> dict:
    """Данные канвы панели — ТЕ ЖЕ строки и карточки, что везёт живой канал.

    ⛔ Отбора по врачу здесь нет и не будет: канва показывает день целиком,
    включая колонку выпавшего из справочника врача, которой на дне врача
    просто неоткуда взяться.
    ⚠️ Собирается ТЕМ ЖЕ путём, что живое состояние: своя вторая сборка канвы
    разошлась бы с живой молча, и отличить это можно было бы только сверкой
    двух маршрутов между собой.
    """
    return (await _panel_live(d, datetime.now(eng.TZ)))["canvas"]


@router.get("/admin/all", response_class=HTMLResponse)
async def admin_all(request: Request, date_q: str = Query("", alias="date"),
                    f: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    # DentPilot 2.0 (C25.5a): данные — GET /api/schedule/day. Ключ `prog`
    # общий с днём врача и неделей — раздел «Programări».
    # ⚠️ отбор «Lista zilei» уезжает параметром узла, но ТОЛЬКО известный:
    # чужое `?f=` сервер молча игнорирует, и клиент не должен узнать о нём
    # иначе
    params = {"date": d.isoformat()}
    if f in pday.TILE_FILTERS:
        params["f"] = f
    # ⭐ B1: оболочку рисует React.
    return react_shell("schedule_all", "/admin/all",
                       # подзаголовок печатает экран (08.10): дата словами и сводка дня
                       shell_model("prog", ""), params)


@router.get("/admin/cabinet", response_class=HTMLResponse)
async def admin_cabinet(request: Request, doctor: str = ""):
    """Экран «у кресла» (контракт docs/dentpilot-2/chair-mode.md): планшет
    врача над креслом. Кто в кресле — `GET /api/chair`, здесь только оболочка.
    Старой страницы у кресла не было никогда.
    """
    if (deny := _guard(request)) is not None:
        return deny
    dk = pchair.resolve_doctor(doctor, request_user(), eng.DOCTORS)
    return react_shell("chair", "/admin/cabinet", shell_model("prog", "cabinet"),
                       {"doctor": dk} if dk else None)


@router.get("/admin/doctor/{dk}", response_class=HTMLResponse)
async def admin_doctor(request: Request, dk: str,
                       date_q: str = Query("", alias="date")):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin")
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    # ⭐ B1: оболочку рисует React.
    return react_shell("schedule_doctor", f"/admin/doctor/{dk}",
                       # подзаголовок печатает экран (08.10): врач, дата словами, сводка
                       shell_model("prog", ""),
                       {"date": d.isoformat(), "dk": dk})


async def _add_appt(adate: str, atime: str, adoctor: str, aservice: str,
                    aname: str, aphone: str = "", anophone: str = "",
                    abirth: str = "") -> str:
    """Ручная запись (окно «Programare nouă»): код ответа — из `MSG_BANNER`.

    Правило живёт здесь, а не в маршруте `api.py`: его зовут и окно записи
    «Programări», и диалог часа на панели, и проверок у маршрута своих нет —
    вторая копия разошлась бы молча, и один экран принимал бы визит, который
    другой отвергает.
    """
    try:
        d = date.fromisoformat(adate)
        hh, mm = atime.split(":")
        dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return "bad"
    doctor = eng.DOCTORS.get(adoctor)
    svc = eng.SERVICES.get(aservice)
    name = aname.strip()[:80]
    phone = aphone.strip()[:25]
    # Галочка «fără telefon» — намерение ИЗ ФОРМЫ (прайор 08-16, потеря данных
    # от угадывания), а не «поле пустое»: пустой телефон БЕЗ галочки — это
    # недозаполненное окно, и он отбивается bad_phone. С галочкой набранный
    # телефон отбрасывается: галочка, поставленная руками, весит больше
    # забытого в поле текста (окно и само чистит поле).
    if anophone:
        phone = ""
    digits = "".join(ch for ch in phone if ch.isdigit())
    # ⚠️ пять разных причин отвечали одним «Date invalide — verificați
    # câmpurile». По такому баннеру не видно, какое поле чинить, и отказ
    # читается как «программа не работает». Каждая причина называет себя.
    if not doctor or not svc:
        return "bad"
    if not name:
        return "bad_name"
    # 6–15 цифр: у стран номера от 6 национальных цифр, E.164 даёт максимум 15.
    # Жёсткий молдавский формат отверг бы иностранца у стойки (просьба 08-07)
    if not anophone and not 6 <= len(digits) <= 15:
        return "bad_phone"
    if not eng.DOCTOR_META.get(adoctor, {}).get("active", True):
        return "bad_off"  # выключенному не пишем
    if dt.minute not in (0, 30):
        return "bad_time"  # 30-мин сетка стартов
    if not eng.fits_clinic(dt, eng.svc_duration(aservice)):
        # визит не помещается в рабочее окно клиники (закрытие/обед)
        return "outside"
    # личный график врача (work_from/work_to) — той же проверкой окон, из
    # которой free_starts предлагает слоты.
    # ⚠️ Гейт применяется ТОЛЬКО к будущему: его смысл — не обещать пациенту
    # час, когда врача нет, а у состоявшегося приёма обещать уже нечего. График
    # могли сузить ПОСЛЕ визита, и тогда внести его постфактум стало бы нечем:
    # фиша прошлое не берёт по замыслу, журнал — единственный вход.
    # Граница здесь МГНОВЕННАЯ (is_past), а не дневная: «приём был сегодня
    # утром, а график сузили после обеда» — тот же постфактум, и на дневной
    # границе он остался бы невозможным. Дневная граница ниже про другое — она
    # решает, показывать ли предупреждение, а не пускать ли запись.
    fits_doc = eng.fits_doctor(adoctor, dt, eng.svc_duration(aservice))
    if not eng.is_past(dt) and not fits_doc:
        return "outside_doc"
    # полная дата рождения (просьба 08-07: был только год; отдельное поле
    # года для вкладки, открытой до обновления, ушло 13.10 вместе с формой)
    year, bdate = None, None
    if abirth.strip():
        try:
            parsed = date.fromisoformat(abirth.strip()[:10])
        except ValueError:
            return "bad_bd"
        if not (1900 <= parsed.year and parsed <= date.today()):
            return "bad_bd"
        year, bdate = parsed.year, parsed.isoformat()
    # ⚠️ Спрашиваем ДО записи: после неё карточка уже может быть создана этой же
    # записью, и «существующий пациент» перестанет отличаться от нового.
    existing = await db.patient_name_by_phone(phone)
    r = await db.admin_add(name, phone, svc["ro"], doctor, dt, birth_year=year,
                           birth_date=bdate,
                           doctor_id=adoctor, service_id=aservice,
                           duration_min=eng.svc_duration(aservice))
    msg = "ok" if isinstance(r, int) else ("dup" if r == "dup" else "conflict")
    # ⛔ Визит лёг в ЧУЖУЮ карточку — по номеру нашёлся пациент с другим именем
    # (08-10). Чаще всего это ребёнок на телефоне родителя, и это норма; но
    # молча приклеивать к родителю нельзя: дальше туда пойдут одонтограмма,
    # дневник и 043/e, и обнаружится это на распечатанном бланке. Запись
    # проходит — регистратуре нужна скорость, — но она названа вслух.
    # ⚠️ Сравниваем ЛИЧНОЕ ИМЯ, а не строку целиком. Целиком не годится: тот же
    # человек записан в боте как «Ion», а регистратура пишет «Ion Popescu» —
    # предупреждение загоралось бы на обычной работе, и его перестали бы
    # читать раньше, чем оно окажется право (та же болезнь, что у ok_past на
    # мгновенной границе). Разные ЛИЧНЫЕ имена — уже другой человек.
    if msg == "ok" and existing and name.strip():
        was, now = existing.strip().lower().split(), name.strip().lower().split()
        if was and now and was[0] != now[0]:
            msg = "ok_other"
    # ручную запись задним числом НЕ запрещаем (визит вносят постфактум), но и
    # молчать нельзя: запись на закрытый день чаще всего опечатка, а она просто
    # исчезает из журнала — её никто больше не увидит. Граница ДНЕВНАЯ: визит в
    # уже прошедший час сегодня — обычная работа регистратуры, а не ошибка
    if msg == "ok" and eng.is_past_day(dt.date()):
        msg = "ok_past"
    return msg


async def _add_note(ndate: str, ntime: str, ndoctor: str, ntext: str,
                    nuntil: str = "") -> str:
    """Заметка стойки: блокировка ЧАСОВ приёма (вкладка «Notiță» диалога
    часа). Код ответа — из `MSG_BANNER`.

    ⚠️ Верхняя граница ОТКРЫТАЯ: «с 15 до 18» блокирует 15, 16 и 17. И часы
    берутся из `day_slots`, поэтому обеденный час внутри диапазона
    перепрыгивается, а не блокируется дважды.
    ⚠️ Выключенному врачу здесь отвечает «bad», а не «bad_off», как у записи.
    Расхождение старое; оно пиннуто, и менять его при снятии старого
    интерфейса нельзя — это отдельное решение, а не уборка.
    """
    try:
        d = date.fromisoformat(ndate)
        start_h = int(ntime.split(":")[0])
        until_h = int(nuntil) if nuntil.strip() else start_h + 1
    except (ValueError, AttributeError):
        return "bad"
    doctor = eng.DOCTORS.get(ndoctor)
    text = ntext.strip()[:120]
    day_hours = [x.hour for x in eng.day_slots(d)]
    hours = [h for h in day_hours if start_h <= h < until_h]
    if not doctor or not text or not hours or until_h <= start_h:
        return "bad"
    if not eng.DOCTOR_META.get(ndoctor, {}).get("active", True):
        return "bad"
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
    return msg


async def _set_comment(appt_id: int, comment: str) -> str:
    """Комментарий ресепшена. 300 знаков режет СЕРВЕР, а не только поле:
    `maxlength` у устаревшей вкладки может быть другим, а в фишу и в 043/e
    уезжает то, что легло в базу."""
    await db.set_comment(appt_id, comment.strip()[:300])
    return "ok_comment"


async def _move_appt(appt_id: int, mdate: str, mtime: str, mdoctor: str) -> str:
    """Перенос визита перетаскиванием: другой час и/или другой врач.

    ⚠️ Проверки те же, что у ручной записи, и по той же причине: перетащить —
    это назначить визит на новое место, а не «подвинуть картинку». Браузер
    отказывается класть блок в закрытую ячейку ещё до отправки, но верить ему
    нельзя: вкладка живёт долго (панель опрашивает канал раз в 12 с), а часы
    клиники и график врача меняются на другом экране.
    ⛔ Прошлое здесь НЕ проверяется, и это намеренно: визит уже существует, а
    перенос на утро того же дня — обычная работа регистратуры.
    """
    try:
        d = date.fromisoformat(mdate)
        hh, mm = mtime.split(":")
        dt = datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return "bad"
    doctor = eng.DOCTORS.get(mdoctor)
    if not doctor:
        return "bad"
    if not eng.DOCTOR_META.get(mdoctor, {}).get("active", True):
        return "bad_off"
    if dt.minute not in (0, 30):
        return "bad_time"
    if not eng.fits_clinic(dt, 30):
        # 30 минут, а не полная длительность: визит УЖЕ существует, и требовать
        # от него влезть в окно целиком значило бы отказывать в переносе тем,
        # кого клиника принимает внахлёст с закрытием (так их и записали).
        return "outside"
    # график врача — та причина серверной перепроверки, которую называет
    # докстринг: часы врача меняются на другом экране, а вкладка устаревает
    if not eng.fits_doctor(mdoctor, dt, 30):
        return "outside_doc"
    code = await db.move_appointment(appt_id, mdoctor, doctor, dt,
                                     when=dt.strftime("%H:%M"))
    return {"": "ok_move", "gone": "mv_gone",
            "closed": "mv_closed"}.get(code, code)


async def _set_status(appt_id: int, to: str) -> str:
    """Смена исхода визита: «» — сделано, «bad» — слово не из конвейера,
    иначе код отказа.

    ⚠️ На «bad» JSON API отвечает отказом 422: вкладка, приславшая статус,
    которого нет, обязана это услышать, а не считать, что сделано. (Старая
    страница, снятая 13.10, глотала такое слово молча.)
    """
    if to not in {"waiting", "arrived", "done", "noshow", "cancelled", "confirmed"}:
        return "bad"
    # код отказа, а не «не получилось»: «занято у медика» и «у пациента уже
    # есть запись на этот час» чинятся по-разному, и регистратуре нужно
    # знать, ЧТО именно занято (см. db.set_status)
    code = await db.set_status(appt_id, to)
    if not code:
        return ""
    return code if code in {"conflict", "dup"} else "conflict"

