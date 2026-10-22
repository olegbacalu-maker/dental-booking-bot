"""JSON API журнала (DentPilot 2.0): неделя (C24), день и его действия (C25),
живой канал панели (C27), кресло.

Правила живут в `week.py` / `day.py` / `canvas.py` / `panel.py` и в
`routes.py`: состав колонок, счётчики, цвет чипа, список часов формы и все
пять правил записи считает сервер, клиент их только раскладывает.

⛔ Ни одного правила ЗДЕСЬ нет. Маршрут зовёт правило из `routes.py` и
возвращает его код (`MSG_BANNER`). Появись здесь своя проверка — окно записи
на «Programări» и диалог часа на панели приняли бы визит по-разному, и
увидела бы это клиника.

⚠️ Действие отвечает СВЕЖИМ ДНЁМ ЭКРАНА: `?date=&doctor=` — это «где я
стою», тело запроса — «что я делаю». Поэтому запись на другую дату (поле даты
в форме редактируемое) возвращает день, на который смотрят, а не тот, куда
уехал визит.

⛔ Маршруты под `/api/` зовут `api_guard`, никогда `_guard`: тот отвечает
редиректом 303 на экран входа, и `fetch` сходил бы по нему сам, вернув 200 с
формой входа — экран показал бы пустой журнал как «успех».

⚠️ Дни приезжают СПИСКОМ показанных, а не семью позициями. Закрытый день
исчезает, если в нём нет записей, поэтому колонок 5, 6 или 7, и раскладка по
`weekday()` поставила бы субботу под воскресенье — правдоподобно и неверно.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Request

from ... import db
from ... import engine as eng
from ...core.api import api_body, api_guard, live_envelope, live_reply
from ...core.auth import request_user
from ...core.layout import msg_json
from ...core.visits import _collect_cards, _parse_date, all_status_actions
from . import chair as pchair
from . import panel as ppanel
from .routes import (_AG_CLS, _add_appt, _add_note, _canvas_model, _day_model,
                     _move_appt, _of_doctor, _panel_live, _set_comment,
                     _set_status, _svc_colors, _week_model)

router = APIRouter()

# Коды удачи и коды спора с состоянием — как у фиши пациента (`patients/api`),
# чтобы клиент разбирал ответы журнала и фиши одинаково.
# ⚠️ Пустой код — это удача: так отвечает смена статуса, у которой баннера нет.
_OK = {"", "ok", "ok_note", "part_note", "ok_move", "ok_comment", "ok_past",
       "ok_other"}
_CONFLICT = {"conflict", "dup", "bad_off", "mv_gone", "mv_closed", "past", "bad_step"}
# какое поле формы подсветить при 422; отказ без поля оставляет его пустым
_FIELD = {"bad": "time", "bad_time": "time", "outside": "time",
          "outside_doc": "time", "bad_name": "name", "bad_phone": "phone",
          "bad_bd": "birth"}


# Поверхности, которым состояния НЕ отдаётся вовсе. ⛔ Это ПЕРЕЧИСЛЕНИЕ, а не
# «всё, кроме дня»: правило вида «всё, кроме X» живёт ровно до появления
# второго X (08-11, PLAN_ACTIVE), и вот он — фиша врача. Неизвестное значение
# `screen` по-прежнему получает день, и это нарочно: так ведёт себя и адрес
# страницы, у которого лишний параметр ничего не значит.
# `panel` — живая панель (C26.5.3): у неё ДРУГОЙ ключ колонки, и модель дня
# слила бы легаси-строку без `doctor_id` в колонку живого врача.
# `med` — фиша врача (C14+): у неё своя модель, и день журнала ей не подходит;
# свежие данные она берёт своим перечитыванием.
# `new_appt` — окно «Programare nouă» шапки вне дня журнала (22.10): дня
# экрана у него нет, после записи — плашка со ссылкой в журнал.
_NO_STATE = {"panel", "med", "new_appt"}


def _s(body: dict | None, key: str) -> str:
    v = (body or {}).get(key)
    return "" if v is None else str(v)


def _screen(date_q: str) -> date:
    """День, на который смотрят. Кривая дата молча открывает сегодняшний: адрес
    журнала набирают руками, и отказ вместо дня здесь бесполезен."""
    return _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()


async def _done(code: str, d: date, doctor: str, field: str | None = None,
                f: str = "", screen: str = ""):
    """Ответ действия: отказ — кодом без данных, удача — свежим днём экрана.

    ⚠️ Свежий день приезжает В ТОМ ЖЕ ОТБОРЕ, в котором на него смотрят: с
    плиткой-фильтром ответ без `f` подменил бы отфильтрованный список полным,
    и запись «исчезла бы» из фильтра прямо на глазах.

    ⛔ А ПОВЕРХНОСТИ СО СВОЕЙ МОДЕЛЬЮ (`_NO_STATE`) состояния не отдаётся вовсе —
    ни на удаче, ни на отказе (C26.5.3). Причин две, и обе стреляют у клиники.
    Первая: здесь строится модель ДНЯ, у которой ДРУГОЙ ключ колонки, чем у
    канвы, — легаси-строка без `doctor_id` слилась бы в колонку живого врача,
    визит исчез бы с панели, час выглядел бы свободным, и в него записали бы
    второго (разбор — `admin-contract.md` › 2). Вторая шире: состояние на
    живой поверхности выпускается ровно одной дверью — `live_reply` вместе со
    своим отпечатком. Ответ действия отпечатка не несёт, значит любое
    состояние в нём — второй источник истины, не участвующий в протоколе.
    Клиент после команды просто спрашивает канал (`refresh()`).
    """
    if code not in _OK:
        return msg_json(False, code,
                        field=_FIELD.get(code, "") if field is None else field,
                        status=409 if code in _CONFLICT else 422)
    if screen in _NO_STATE:
        return msg_json(True, code)
    data = await _day_model(d, doctor, f)
    if data is None:
        return msg_json(False, status=404)
    return msg_json(True, code, data=data)


@router.post("/api/schedule/desk/call/{aid}")
async def api_desk_call(request: Request, aid: int,
                        date_q: str = Query("", alias="date"),
                        doctor: str = Query(""), f: str = Query(""),
                        screen: str = Query("")):
    """Отметка звонка-подтверждения («De confirmat» на главной, 01.10; с 12.10
    и из карточки визита и меню на «Programări»): {result: ok | noanswer | ""}.
    Панели состояния не возвращает — как остальные её команды: экран спрашивает
    живой канал, и отметка доезжает до всех рабочих мест тем же конвертом.
    Дню журнала — свежий день в его отборе (`_done`), как после смены статуса."""
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    result = _s(body, "result")
    if result not in ("ok", "noanswer", ""):
        return msg_json(False, "bad", status=422)
    a = await db.appointment_brief(aid)
    if not a:
        return msg_json(False, "mv_gone", status=409)
    await db.set_appt_call(aid, result)
    if a.get("patient_id") and result:
        when = a["starts_at"].astimezone(eng.TZ).strftime("%d.%m %H:%M")
        await db.log_event(a["patient_id"], "call",
                           f"Confirmare telefonică ({when}): "
                           + ("confirmat" if result == "ok" else "nu răspunde"))
    return await _done("", _screen(date_q), doctor, field="", f=f, screen=screen)


@router.get("/api/schedule/week")
async def api_week(request: Request, date_q: str = Query("", alias="date")):
    """Неделя, в которую попал день: колонки, чипы, итог, соседние недели.

    ⚠️ Кривая дата молча открывает текущую неделю: адрес журнала набирают
    руками, и отказ вместо календаря здесь бесполезен.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    d = _screen(date_q)
    data = await _week_model(d)
    # день, от которого открыли неделю: ссылки «Zi» и «Săptămâna» ведут на
    # него, а не на понедельник
    data["day"] = d.isoformat()
    return msg_json(True, data=data)

@router.get("/api/schedule/day")
async def api_day(request: Request, date_q: str = Query("", alias="date"),
                  doctor: str = Query(""), f: str = Query("")):
    """День «Programări»: все врачи или один (`?doctor=dk`) — тот же построитель.

    ⚠️ Врачи и колонки канвы приезжают СПИСКОМ: врачей бывает ноль, один или
    все, и раскладка по фиксированным местам сломалась бы на первом
    выключенном.
    ⛔ Поля перетаскивания (`min`, `dur`, `busy`, `movable`) у блока канвы те
    же, что у панели: канва одна на оба экрана дня (06.10).
    """
    if (deny := api_guard(request)) is not None:
        return deny
    d = _screen(date_q)
    data = await _day_model(d, doctor, f)
    if data is None:
        return msg_json(False, status=404)
    return msg_json(True, data=data)


# Экраны живого канала: имя → построитель состояния.
# ⚠️ Словарь отвечает «КАКОЙ ЭКРАН», а не «какой клиент»: построитель решает,
# есть ли у экрана живое состояние вообще.
# ⛔ Ключа раскладки старых страниц (`LIVE_RELOAD`) здесь НЕТ и не было: свяжи
# с ним канал — и со снятием старой панели (13.10) React-панель у клиники
# молча перестала бы получать состояние, отвечая «я не живая» сама себе.
_LIVE_SCREENS = {"panel": _panel_live}


@router.get("/api/schedule/live")
async def api_live(request: Request, screen: str = Query("panel"),
                   date_q: str = Query("", alias="date")):
    """Живое состояние экрана ДАННЫМИ: 204 «прежнее» или 200 со снимком.

    ⛔ Это не «ещё один способ получить канву». Живой журнал держится ровно на
    том, что сервер умеет сказать «не менялось», и цена ошибки тут не в лишнем
    запросе: отпечаток, считающийся не от того, что отправлено, заставит React
    перерисовывать панель каждые 12 секунд — на неизменном дне, молча, и
    увидеть это можно, только простояв на странице полминуты.

    ⛔ Канал НЕ СПРАШИВАЕТ, кто рисует экран: состояние одного и того же дня
    всегда одно и то же. До 19.09 он отвечал `live:false` и пустотой, увидев
    флаг React, — то есть отнимал состояние ровно у того клиента, ради
    которого делался. (С 13.10 старой панели нет, и спрашивать стало нечего:
    заголовок поверхности `X-DP-Surface` снят вместе с ней.)
    ⚠️ Версии в состоянии НЕТ намеренно: она едет заголовком `X-DP-V`. Положи
    её в данные — и отпечаток менялся бы при каждом обновлении exe, хотя день
    тот же; клиент и так перезагружается по заголовку.
    ⏳ `updated` (максимум отметок данных дня) тоже нет: отпечаток уже
    отвечает «менялось или нет», а поле, посчитанное неосторожно от
    `datetime.now()`, вернуло бы ровно ту болезнь, от которой ушли 08-20.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    build = _LIVE_SCREENS.get(screen)
    if build is None:
        return msg_json(False, status=422, field="screen")
    d = _screen(date_q)
    return live_reply(request,
                      live_envelope(screen, d, await build(d, datetime.now(eng.TZ))))


@router.get("/api/schedule/canvas")
async def api_canvas(request: Request, date_q: str = Query("", alias="date")):
    """Канва панели дня: ряды, колонки, блоки с геометрией.

    ⛔ Это НЕ `/api/schedule/day` в другой раскладке. Ключ колонки у канвы
    свой: легаси-строка без `doctor_id`, но с именем живого врача, получает
    здесь ОТДЕЛЬНУЮ колонку с формой relink, а день сливает её в колонку
    врача. Возьми клиент панели данные дня — визит выпавшего из справочника
    врача исчез бы с экрана, а час выглядел бы свободным.
    ⚠️ `?doctor=` здесь нет намеренно: панель показывает день целиком.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    return msg_json(True, data=await _canvas_model(_screen(date_q)))


@router.post("/api/schedule/appointments")
async def api_add(request: Request, date_q: str = Query("", alias="date"),
                  doctor: str = Query(""), f: str = Query(""),
                  screen: str = Query("")):
    """Ручная запись: {date, time, doctor, service, name, phone, nophone, birth}.

    ⚠️ `nophone` — намерение ИЗ ФОРМЫ, а не «телефон пустой» (прайор 08-16):
    пустой номер без галочки остаётся отказом `bad_phone`.
    ⚠️ `screen` — «я поверхность со своей моделью, состояния мне не давай»
    (`panel`, `med`, `new_appt`; разбор в `_done`). ⛔ Параметр обязан быть ОБЪЯВЛЕН, а не
    просто послан: неизвестный параметр строки запроса FastAPI молча
    игнорирует, и маршрут
    ответил бы полной моделью дня, не сказав об этом ничем.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", status=422)
    code = await _add_appt(_s(body, "date"), _s(body, "time"), _s(body, "doctor"),
                           _s(body, "service"), _s(body, "name"), _s(body, "phone"),
                           "1" if body.get("nophone") else "", _s(body, "birth"))
    return await _done(code, _screen(date_q), doctor, f=f, screen=screen)


@router.post("/api/schedule/notes")
async def api_note(request: Request, date_q: str = Query("", alias="date"),
                   doctor: str = Query(""), f: str = Query(""),
                   screen: str = Query("")):
    """Заметка стойки: {date, time, doctor, text, until}. `until` — ГОЛЫЙ час
    (18, не «18:00»), верхняя граница открытая.

    ⚠️ Поле отказа всегда «text»: `bad` здесь означает и пустой текст, и
    границы задом наперёд, и неизвестного врача, а правит человек в этом
    диалоге ровно одно поле — текст. Врач и час приходят из ячейки.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", field="text", status=422)
    code = await _add_note(_s(body, "date"), _s(body, "time"), _s(body, "doctor"),
                           _s(body, "text"), _s(body, "until"))
    return await _done(code, _screen(date_q), doctor, field="text", f=f,
                       screen=screen)


@router.post("/api/schedule/appointments/{appt_id}/comment")
async def api_comment(request: Request, appt_id: int,
                      date_q: str = Query("", alias="date"),
                      doctor: str = Query(""), f: str = Query(""),
                      screen: str = Query("")):
    """Комментарий ресепшена: {comment}. Пустая строка стирает его.

    ⚠️ `screen` — «я поверхность со своей моделью, состояния мне не давай»
    (`panel`, `med`; разбор в `_done`).
    """
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", field="comment", status=422)
    return await _done(await _set_comment(appt_id, _s(body, "comment")),
                       _screen(date_q), doctor, f=f, screen=screen)


@router.get("/api/chair")
async def api_chair(request: Request, doctor: str = Query(""),
                    date_q: str = Query("", alias="date")):
    """Экран «у кресла» (контракт `docs/dentpilot-2/chair-mode.md`): кто у
    врача в кресле, кто не завершён, кто в очереди, и матрица кнопок исхода.

    Чей экран — `chair.resolve_doctor`: `?doctor=`, иначе врач учётки;
    никого — `doctor: null` и список врачей для выбора. `?date=` — для
    проверок и «посмотреть вчера»; экран живёт сегодняшним днём.
    ⚠️ Строки берутся тем же `_of_doctor`, что у сетки врача, а слово статуса
    и форма строки — той же `panel.agenda`, что у панели: второй сборки нет.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    d = _screen(date_q)
    dk = pchair.resolve_doctor(doctor, request_user(), eng.DOCTORS)
    data = {"date": d.isoformat(),
            "doctors": [{"dk": k, "name": n} for k, n in eng.ACTIVE_DOCTORS.items()],
            "doctor": None, "chair": None, "stale": [], "queue": [],
            "actions": all_status_actions()}
    if not dk:
        return msg_json(True, data=data)
    start = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    rows = [r for r in await db.day_appointments(start, start + timedelta(days=1))
            if _of_doctor(r, dk)]
    agenda = ppanel.agenda(d, rows, _collect_cards(rows), _svc_colors, _AG_CLS,
                           datetime.now(eng.TZ))
    data.update(pchair.model(rows, agenda["items"]),
                doctor={"dk": dk, "name": eng.DOCTORS[dk]}, today=agenda["today"])
    return msg_json(True, data=data)


@router.post("/api/schedule/appointments/{appt_id}/status")
async def api_status(request: Request, appt_id: int,
                     date_q: str = Query("", alias="date"),
                     doctor: str = Query(""), f: str = Query(""),
                     screen: str = Query("")):
    """Исход визита: {to}. Удача отвечает ПУСТЫМ кодом — баннера у неё нет;
    отказ называет, ЧТО занято (conflict / dup).

    ⚠️ Слово не из конвейера — 422: вкладка, приславшая небывалый статус,
    обязана услышать отказ, иначе покажет пациента «в кресле», когда он туда
    не переходил.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", status=422)
    return await _done(await _set_status(appt_id, _s(body, "to")),
                       _screen(date_q), doctor, field="", f=f, screen=screen)


@router.post("/api/schedule/appointments/{appt_id}/move")
async def api_move(request: Request, appt_id: int,
                   date_q: str = Query("", alias="date"),
                   doctor: str = Query(""), f: str = Query(""),
                   screen: str = Query("")):
    """Перенос: {date, time, doctor} — тот же маршрут, что у перетаскивания.

    ⚠️ Проверки серверные и в полном составе: браузер не кладёт блок в
    закрытую ячейку, но верить ему нельзя — часы клиники и график врача
    меняются на другом экране, а вкладка живёт долго.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", status=422)
    code = await _move_appt(appt_id, _s(body, "date"), _s(body, "time"),
                            _s(body, "doctor"))
    return await _done(code, _screen(date_q), doctor, f=f, screen=screen)
