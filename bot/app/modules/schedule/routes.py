"""Журнал клиники: адреса экранов и правила, которые зовёт `api.py`.

С 13.10 (снятие старого интерфейса, шаг 5) экраны журнала — панель дня
`/admin`, неделя, «Programări» (`/admin/all`, день врача) и кресло — рисует
только React: обработчик здесь отдаёт оболочку (`react_shell`), данные идут
через `/api/schedule/*` (`api.py`). Здесь остались:
- модели, которые собирает и панель, и день (`_panel_live`, `_day_model`,
  `_week_model`) — из одной выборки, тем же цветом (`_svc_colors`);
- правила действий журнала (`_add_appt`, `_add_note`, `_set_comment`,
  `_move_appt`, `_set_service`, `_set_status`): JSON API зовёт их, своих
  проверок у него нет;
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
from ...core.layout import msg_view, react_shell, shell_model
from ...core.risks import denied_since, merge as merge_risks
from ...core.visits import (SVC_PALETTE, _collect_cards, _parse_date,
                            all_status_actions, mine, my_scope, of_doctor,
                            service_refusal, status_actions)
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


def _notice(scope: str | None) -> dict | None:
    """Подсказка-состояние журнала (22.10): у учётки врача без привязки
    (`scope == ""`) — «contul nu e legat de un medic», иначе None. Слова —
    `MSG_BANNER` через `msg_view`; ключ `notice` один у дня, панели, недели
    и кресла, экран печатает его состоянием, а не плашкой."""
    return msg_view("no_doctor_link") if scope == "" else None


def _only(scope: str | None, doctor: str = "") -> str:
    """Чья колонка на канве: `doctor` — день этого врача; иначе по журналу
    вошедшего — все (пусто), свой врач или никого (`canvas.NOBODY`).
    ⛔ `scope == ""` и `scope is None` — РАЗНЫЕ ответы: пустая строка в `only`
    значила бы «все колонки», то есть ровно то, что учётке без врача не положено."""
    if scope == "":
        return pcanvas.NOBODY
    return doctor or scope or ""


async def _week_model(d: date, scope: str | None = None) -> dict:
    """Неделя данными: ОДИН запрос к базе на всю неделю вместо семи.

    ⚠️ Правила живут в `week.py` и ничего не знают о разметке — их же возьмёт
    JSON API. Цвет передаётся функцией: он общий с днём и агендой, а импорт
    `routes` из `week` замкнул бы круг.
    `scope` — журнал вошедшего (`visits.my_scope`, 22.10): врач видит неделю
    только своих визитов, учётка без врача — пустую с подсказкой `notice`.
    """
    monday = pweek.monday_of(d)
    start, end = pweek.week_span(monday)
    rows = [r for r in await db.day_appointments(start, end) if mine(r, scope)]
    m = pweek.model(monday, pweek.by_day(rows),
                    datetime.now(eng.TZ).date(), _svc_colors)
    m["notice"] = _notice(scope)
    return m


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
    # права врача (22.10): в выгрузке — те же строки, что в его журнале
    rows = [r for r in await db.day_appointments(start, end) if mine(r, my_scope())]

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


# `_of_doctor` жил здесь до 22.10 — теперь `core.visits.of_doctor` (его зовёт и
# `desk.py`, который этот модуль импортирует сам); правило то же, одно.


async def _day_model(d: date, doctor: str = "", f: str = "",
                     scope: str | None = None) -> dict | None:
    """День экрана «Programări» — один на «Toți medicii» и на день врача.

    `doctor` пуст — все врачи и все записи; иначе один врач и ТОЛЬКО его
    записи, включая легаси-строки без `doctor_id`, найденные по снимку имени.
    None — такого врача в справочнике нет.
    `scope` — журнал вошедшего (`visits.my_scope`, 22.10, права врача): у
    врача общий день — это ЕГО день (одна колонка, форма только на него, его
    факты и календарь), у учётки без врача — пустой день с подсказкой
    `notice`. Чужой `doctor` при суженном журнале отбивает маршрут (403),
    сюда он не доходит.
    """
    day_start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = [r for r in await db.day_appointments(day_start, day_start + timedelta(days=1))
            if mine(r, scope)]
    one = _only(scope, doctor)      # чей это день: ключ врача или никого
    if scope == "":
        # учётка врача без привязки: ни колонок, ни формы — на экране `notice`
        items, form_items = [], None
    elif doctor or scope:
        if one not in eng.DOCTORS:
            return None
        name = eng.DOCTORS[one]
        rows = [r for r in rows if of_doctor(r, one)]
        items = [(one, name)]
        # у выключенного врача формы нет вовсе — как на его странице
        form_items = (items if eng.DOCTOR_META.get(one, {}).get("active", True)
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
    m["canvas"] = pcanvas.model(d, rows, cards, _svc_colors, only=one)
    if one and one in eng.DOCTORS:
        # ⭐ (22.10, вариант A + H Олега) Только у дня ОДНОГО врача — по адресу
        # или по праву: факты о пациенте карточки визита и календарь шапки.
        # ⛔ Не в `appt_view` и не в `canvas.blocks`: они едут в каждом конверте
        # живого канала главной, и канва общего дня обязана совпадать с ним
        # (`suite_day_parity`).
        m["extras"] = await _visit_facts(d, rows)
        m["minical"] = ppanel.minical(d, datetime.now(eng.TZ).date(), _RO_MONTHS,
                                      base=f"/admin/doctor/{doctor}" if doctor else "/admin/all",
                                      busy=await _busy_days(d, one))
    m["notice"] = _notice(scope)
    return m


async def _busy_days(d: date, doctor: str = "") -> set:
    """Точки мини-календаря (08.10): дни окна месяца с живой записью — у
    главной всех врачей, у шапки дня врача (22.10) только его (`_of_doctor`).
    Окно — те же полные недели, что рисует `panel.minical` (с понедельника
    перед первым числом, шесть недель с запасом); выборка лёгкая.
    ⚠️ Правило «живая запись» то же, что у повестки и загрузки: без
    отменённых и без заметок стойки."""
    first = d.replace(day=1)
    m_start = first - timedelta(days=first.weekday())
    m0 = datetime(m_start.year, m_start.month, m_start.day, tzinfo=eng.TZ)
    return {r["starts_at"].astimezone(eng.TZ).date()
            for r in await db.appointment_days(m0, m0 + timedelta(days=42))
            if r["status"] != "cancelled" and r["source"] != "note"
            and (not doctor or of_doctor(r, doctor))}


async def _visit_facts(d: date, rows: list) -> dict:
    """Факты карточки визита дня врача по id визита (22.10, вариант A):
    риски (`core.risks.merge` — atenționări и анамнез без дублей), состояние
    анамнеза, активный план, какой это визит пациента и прошлый визит.

    ⛔ Ни одного «сейчас»: прошлый визит — последний ДО этого визита, счёт —
    по визитам до него, давность считает браузер от дня экрана по дате
    `last.date`. Ответ меняется только с данными. Выборки — `db.day_patient_facts`,
    четыре на день, а не по запросу на визит. ⛔ Денег нет (Олег 22.10).
    """
    own = [r for r in rows if r.get("patient_id") and r["source"] != "note"
           and r["status"] != "cancelled"]
    if not own:
        return {}
    day_end = datetime(d.year, d.month, d.day, tzinfo=eng.TZ) + timedelta(days=1)
    f = await db.day_patient_facts(sorted({r["patient_id"] for r in own}), day_end)
    out: dict[str, dict] = {}
    for r in own:
        pid = r["patient_id"]
        prior = [v for v in f["visits"].get(pid, [])
                 if v["starts_at"] < r["starts_at"] and v["id"] != r["id"]]
        last = prior[-1] if prior else None
        anam = f["anam"].get(pid)
        risks = merge_risks(f["alerts"].get(pid, []), anam)
        out[str(r["id"])] = {
            "nth": len(prior) + 1,
            "last": ({"date": last["starts_at"].astimezone(eng.TZ).date().isoformat(),
                      "what": (last.get("tratament") or "").strip() or last["service"] or ""}
                     if last else None),
            "risks": risks,
            # собран ли анамнез: нет — экран ставит серое «Anamneză necompletată»
            "anam": anam is not None,
            # заявил, что здоров (23.10, `anamneza.NONE_KEY`): дата опроса ISO —
            # экран ставит серое «Neagă afecțiunile din chestionar» с ней;
            # дата из данных (последнее сохранение опросника), не «сейчас»
            "denies": (since.astimezone(eng.TZ).date().isoformat()
                       if (since := denied_since(anam)) else None),
            "plan": [{"tooth": it["tooth"], "proc": it["procedure"],
                      "work": it["status"] == "in_lucru"}
                     for it in f["plan"].get(pid, [])],
        }
    return out


async def _panel_live(d: date, now: datetime, scope: str | None = None) -> dict:
    """Живое состояние панели данными: канва, повестка и загрузка — от ОДНОЙ
    выборки дня.
    `scope` — журнал вошедшего (`visits.my_scope`, 22.10, права врача): врач
    получает панель только своих визитов (колонка, повестка, загрузка,
    точки календаря, списки стойки), учётка без врача — пустую с подсказкой
    `notice`. У одного человека ответ по-прежнему детерминирован при
    неизменных данных: отпечаток клиент сравнивает со своим же прошлым ответом.

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
    rows = [r for r in await db.day_appointments(day_start, day_start + timedelta(days=1))
            if mine(r, scope)]
    cards = _collect_cards(rows)
    # ёмкость загрузки — кресла, которые человек видит: все активные, своё
    # или ни одного (иначе врач видел бы «3% ocupare» на свой полный день)
    active_dks = ([dk for dk in eng.DOCTORS
                   if eng.DOCTOR_META.get(dk, {}).get("active", True)] if scope is None
                  else [scope] if scope else [])
    busy_days = await _busy_days(d, scope or "") if scope != "" else set()
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
        "canvas": pcanvas.model(d, rows, cards, _svc_colors, only=_only(scope)),
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
        "desk": await pdesk.desk_model(now, scope),
        # подсказка учётки без врача (22.10) — состоянием, в том же конверте
        "notice": _notice(scope),
    }


async def _canvas_model(d: date, scope: str | None = None) -> dict:
    """Данные канвы панели — ТЕ ЖЕ строки и карточки, что везёт живой канал.

    ⛔ Отбора по врачу АДРЕСОМ здесь нет и не будет: канва показывает день
    целиком, включая колонку выпавшего из справочника врача, которой на дне
    врача просто неоткуда взяться. Отбор ПО ПРАВУ вошедшего (`scope`, 22.10)
    — тот же, что у живого канала: врач видит свою колонку и там, и здесь.
    ⚠️ Собирается ТЕМ ЖЕ путём, что живое состояние: своя вторая сборка канвы
    разошлась бы с живой молча, и отличить это можно было бы только сверкой
    двух маршрутов между собой.
    """
    return (await _panel_live(d, datetime.now(eng.TZ), scope))["canvas"]


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
    dk = _chair_doctor(doctor)
    return react_shell("chair", "/admin/cabinet", shell_model("prog", "cabinet"),
                       {"doctor": dk} if dk else None)


def _chair_doctor(asked: str) -> str:
    """Чьё кресло: при полном праве — `chair.resolve_doctor` (адрес, иначе врач
    учётки); у врача — только своё, чужой `?doctor=` молча заменяется своим
    (22.10, права врача); у учётки без врача — ничьё. Одно правило на
    страницу `/admin/cabinet` и `GET /api/chair`."""
    scope = my_scope()
    if scope is None:
        return pchair.resolve_doctor(asked, request_user(), eng.DOCTORS)
    return scope


@router.get("/admin/doctor/{dk}", response_class=HTMLResponse)
async def admin_doctor(request: Request, dk: str,
                       date_q: str = Query("", alias="date")):
    if (deny := _guard(request)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return RedirectResponse("/admin")
    scope = my_scope()
    if scope is not None and dk != scope:
        # права врача (22.10): день чужого врача не открывается — на свой журнал
        return RedirectResponse("/admin/all")
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    # ⭐ B1: оболочку рисует React.
    return react_shell("schedule_doctor", f"/admin/doctor/{dk}",
                       # подзаголовок печатает экран (08.10): врач, дата словами, сводка
                       shell_model("prog", ""),
                       {"date": d.isoformat(), "dk": dk})


async def _add_appt(adate: str, atime: str, adoctor: str, aservice: str,
                    aname: str, aphone: str = "", anophone: str = "",
                    abirth: str = "", asms: bool | None = None) -> str:
    """Ручная запись (окно «Programare nouă»): код ответа — из `MSG_BANNER`.

    `asms` — галочка «SMS reminder»: True/False — что сказал пациент, None —
    галочки в окне не было (разбор у `_apply_sms`).

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
    if isinstance(r, int) and not anophone:
        await _apply_sms(r, asms)
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


async def _apply_sms(appt_id: int, want: bool | None) -> None:
    """Галочка «SMS reminder» окна записи → `patients.sms_off` того, кому
    досталась запись (Олег 19.10: регистратор спросил — сразу отметил).

    ⛔ Нет поля — нет записи (прайор 08-16, «отсутствие поля — не сообщали»):
    галочки не было в окне (SMS не работают, нет права, старый клиент) —
    `sms_off` пациента не трогается вовсе. ⛔ Поле принимается ровно там, где
    форма его рисует, — тем же `day.sms_box()`, а не доверием браузеру: врач
    без `PERM_SMS` присланным полем согласие не тронет. Цена названа: пакет
    выключили, пока окно было открыто, — отметка этого окна не запишется
    (SMS в этот момент и так не уходят, фиша остаётся).
    ⚠️ Пишется только на успехе и только перемена: строка летописи — та же,
    что у фиши, и на каждой записи постоянного пациента она бы множилась.
    Безтелефонному (`fără telefon`) нечего напоминать — окно галочку
    выключает, сервер её не читает.
    """
    if want is None or not pday.sms_box():
        return
    pid = await db.appt_patient_id(appt_id)
    if pid is None:
        return
    off = not want
    if await db.set_sms_off(pid, off):
        await db.log_event(pid, "sms_off", db.SMS_OFF_EVENT[off])


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


async def _set_service(appt_id: int, sid: str) -> str:
    """Смена процедуры у стоящей записи (окно визита, 22.10; Олег: только
    смена — вторая услуга в одну запись НЕ делается). Код — из `MSG_BANNER`.

    Проверки — по образцу ручной записи (`_add_appt`): услуга есть, врач её
    делает, новая длительность влезает в часы клиники и врача, и в общем
    составе с данными под `_slot_lock` (`db.set_appt_service`).
    ⭐ Кто и что вправе менять — ОДНО правило с окном (`visits.service_refusal`):
    по нему окно строит список, по нему же сервер отказывает.
    ⚠️ Часы проверяются, только когда визит ДЛИННЕЕ прежнего — по той же
    причине, что у переноса (`fits_clinic(dt, 30)`): короче он лежит внутри
    интервала, который уже занимал, и отказ «не влезает» не дал бы даже
    сократить визит, записанный внахлёст с закрытием.
    ⚠️ График врача — только у БУДУЩЕГО старта, как у `_add_appt`: у визита,
    который уже идёт («a venit», «în cabinet») или забыт открытым со вчера,
    обещать пациенту нечего, а график могли сузить после записи.
    ⭐ Решено 22.10 (совет главного окна): менять можно у ЛЮБОГО активного
    визита — будущего, прошедшего незакрытого, «a venit» и «în cabinet»;
    регистратура как раз у кресла и узнаёт, что делают на самом деле.
    Закрытый (finalizat / nu a venit / anulat) — `svc_closed`.
    """
    cur = await db.appointment_brief(appt_id)
    if cur is None:
        return "mv_gone"
    if code := service_refusal(cur, sid):
        return code
    if cur["service_id"] == sid:
        return ""
    dk = cur["doctor_id"]
    dur = eng.svc_duration(sid)
    if dur > int(cur["duration_min"] or 60):
        start = cur["starts_at"].astimezone(eng.TZ)
        if not eng.fits_clinic(start, dur):
            return "outside"
        if not eng.is_past(start) and not eng.fits_doctor(dk, start, dur):
            return "outside_doc"
    code = await db.set_appt_service(appt_id, sid, eng.SERVICES[sid]["ro"], dur)
    return {"": "ok_svc", "gone": "mv_gone",
            "closed": "svc_closed"}.get(code, code)


async def _set_status(appt_id: int, to: str) -> str:
    """Смена исхода визита: «» — сделано, «bad» — слово не из конвейера,
    «mv_gone» — визита нет, «bad_step» — переход, которого матрица кнопок из
    текущего состояния не даёт, иначе код отказа занятого часа.

    ⚠️ На «bad» JSON API отвечает отказом 422: вкладка, приславшая статус,
    которого нет, обязана это услышать, а не считать, что сделано. (Старая
    страница, снятая 13.10, глотала такое слово молча.)
    ⭐ Переход проверяется ПО РЕБРУ (откуда → куда), как у плана лечения
    (`patients._plan_status`), и ТОЙ ЖЕ матрицей, что рисует кнопки
    (`visits.status_actions`). До 17.10 сервер принимал любое слово конвейера
    из любого состояния — «не пришёл» визиту на завтра, «ждёт в приёмной»
    пациенту, который уже в кресле, — и ложь уезжала в статистику неявок и
    загрузки врачей. Кнопки такого не дают; вторая вкладка, устаревшее окно
    и ошибка клиента — дают. Повтор того же статуса — тихий успех: двойной
    клик по «Finalizat» не ошибка, и штамп прихода при этом не двигается.
    """
    if to not in {"waiting", "arrived", "done", "noshow", "cancelled", "confirmed"}:
        return "bad"
    cur = await db.appointment_brief(appt_id)
    if cur is None:
        return "mv_gone"
    if cur["status"] == to:
        return ""
    # ⚠️ Возврат в «programată» разрешён ИЗ ЛЮБОГО состояния, не только из
    # закрытого: это исправление промаха («A venit» не тому, «În cabinet»
    # раньше времени), и db.set_status на нём стирает оба штампа ожидания —
    # иначе мусорная пара попала бы в среднее (08-13). Кнопки у живых
    # состояний его не рисуют, но карточка и повестка им чинят промах.
    allowed = {a["to"] for a in status_actions(cur["status"], cur["source"] == "note")}
    if to != "confirmed" and to not in allowed:
        return "bad_step"
    # код отказа, а не «не получилось»: «занято у медика» и «у пациента уже
    # есть запись на этот час» чинятся по-разному, и регистратуре нужно
    # знать, ЧТО именно занято (см. db.set_status)
    code = await db.set_status(appt_id, to)
    if not code:
        return ""
    return code if code in {"conflict", "dup"} else "conflict"

