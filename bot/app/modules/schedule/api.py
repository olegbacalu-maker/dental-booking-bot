"""JSON API журнала (DentPilot 2.0): неделя (C24), день и его действия (C25).

Правила живут в `week.py` / `day.py` и в `routes.py` и одни на старую страницу
и на эти маршруты: состав колонок, счётчики, цвет чипа, список часов формы и
все пять правил записи считает сервер, клиент их только раскладывает.

⛔ Ни одного правила ЗДЕСЬ нет. Маршрут зовёт ту же функцию, что и обработчик
формы, и возвращает тот же код (`MSG_BANNER`), который уезжает в `?msg=`.
Появись здесь своя проверка — React принимал бы визит, который старая
страница отвергает, и наоборот; увидела бы это клиника.

⚠️ Действие отвечает СВЕЖИМ ДНЁМ ЭКРАНА: `?date=&doctor=` — это «где я
стою», тело запроса — «что я делаю». Поэтому запись на другую дату (поле даты
в форме редактируемое) возвращает день, на который смотрят, а не тот, куда
уехал визит, — ровно как `back` у старой формы.

⛔ Маршруты под `/api/` зовут `api_guard`, никогда `_guard`: тот отвечает
редиректом 303 на экран входа, и `fetch` сходил бы по нему сам, вернув 200 с
формой входа — экран показал бы пустой журнал как «успех».

⚠️ Дни приезжают СПИСКОМ показанных, а не семью позициями. Закрытый день
исчезает, если в нём нет записей, поэтому колонок 5, 6 или 7, и раскладка по
`weekday()` поставила бы субботу под воскресенье — правдоподобно и неверно.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Query, Request

from ... import engine as eng
from ...core.api import api_body, api_guard, live_reply
from ...core.layout import LIVE_RELOAD, msg_json, react_on
from ...core.visits import _parse_date
from .routes import (_add_appt, _add_note, _canvas_model, _day_model,
                     _move_appt, _panel_live, _set_comment, _set_status,
                     _week_model)

router = APIRouter()

# Коды удачи и коды спора с состоянием — как у фиши пациента (`patients/api`),
# чтобы клиент разбирал ответы журнала и фиши одинаково.
# ⚠️ Пустой код — это удача: так отвечает смена статуса, у которой баннера нет
# и на старой странице.
_OK = {"", "ok", "ok_note", "part_note", "ok_move", "ok_comment", "ok_past",
       "ok_other"}
_CONFLICT = {"conflict", "dup", "bad_off", "mv_gone", "mv_closed", "past"}
# какое поле формы подсветить при 422; отказ без поля оставляет его пустым
_FIELD = {"bad": "time", "bad_time": "time", "outside": "time",
          "outside_doc": "time", "bad_name": "name", "bad_phone": "phone",
          "bad_bd": "birth"}


def _s(body: dict | None, key: str) -> str:
    v = (body or {}).get(key)
    return "" if v is None else str(v)


def _screen(date_q: str) -> date:
    """День, на который смотрят. Кривая дата молча открывает сегодняшний — как
    у страницы: адрес журнала набирают руками."""
    return _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()


async def _done(code: str, d: date, doctor: str, field: str | None = None,
                f: str = ""):
    """Ответ действия: отказ — кодом без данных, удача — свежим днём экрана.

    ⚠️ Свежий день приезжает В ТОМ ЖЕ ОТБОРЕ, в котором на него смотрят: с
    плиткой-фильтром ответ без `f` подменил бы отфильтрованный список полным,
    и запись «исчезла бы» из фильтра прямо на глазах.
    """
    if code not in _OK:
        return msg_json(False, code,
                        field=_FIELD.get(code, "") if field is None else field,
                        status=409 if code in _CONFLICT else 422)
    data = await _day_model(d, doctor, f)
    if data is None:
        return msg_json(False, status=404)
    return msg_json(True, code, data=data)


@router.get("/api/schedule/week")
async def api_week(request: Request, date_q: str = Query("", alias="date")):
    """Неделя, в которую попал день: колонки, чипы, итог, соседние недели.

    ⚠️ Кривая дата молча открывает текущую неделю — как у страницы: адрес
    журнала набирают руками, и отказ вместо календаря здесь бесполезен.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    d = _screen(date_q)
    data = await _week_model(d)
    # день, от которого открыли неделю: ссылки «Zi» и «Săptămâna» ведут на
    # него, а не на понедельник — так же, как на старой странице
    data["day"] = d.isoformat()
    return msg_json(True, data=data)

@router.get("/api/schedule/day")
async def api_day(request: Request, date_q: str = Query("", alias="date"),
                  doctor: str = Query(""), f: str = Query("")):
    """Сетка дня: все врачи или один (`?doctor=dk`) — тот же построитель.

    ⚠️ Колонки приезжают СПИСКОМ, ячейка ссылается на позицию в нём: врачей
    бывает ноль, один или все, и раскладка по фиксированным местам сломалась
    бы на первом выключенном.
    ⛔ Поля перетаскивания (`min`, `dur`, `busy`, `movable`) те же, что у
    `_move_attrs` старой страницы: договор с переносом один на оба экрана.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    d = _screen(date_q)
    data = await _day_model(d, doctor, f)
    if data is None:
        return msg_json(False, status=404)
    return msg_json(True, data=data)


# Экраны живого канала: имя → (ключ раскладки, имя React-экрана).
# ⚠️ Наполнение сегодня есть только у панели: канва — единственная часть живого
# среза, у которой уже есть модель (C26.4). Правая колонка (мини-календарь,
# повестка, плитки, колокольчик) приедет своими полями, и конверт от этого не
# изменится — в этом и был смысл делать конверт первым.
_LIVE_SCREENS = {"panel": ("dash", "schedule_dash")}


@router.get("/api/schedule/live")
async def api_live(request: Request, screen: str = Query("panel"),
                   date_q: str = Query("", alias="date")):
    """Живое состояние экрана ДАННЫМИ: 204 «прежнее» или 200 со снимком.

    ⛔ Это не «ещё один способ получить канву». Живой журнал держится ровно на
    том, что сервер умеет сказать «не менялось», и цена ошибки тут не в лишнем
    запросе: отпечаток, считающийся не от того, что отправлено, заставит React
    перерисовывать панель каждые 12 секунд — на неизменном дне, молча, и
    увидеть это можно, только простояв на странице полминуты.

    ⚠️ `live` — ЯВНОЕ поле, а не догадка по отсутствию заголовка. Экран
    перестаёт быть живым по ДВУМ причинам сразу (ключ ушёл из `LIVE_RELOAD`
    или экран отдаётся React-ом), и вкладка, открытая до включения флага,
    обязана узнать об этом словом, а не молчанием.
    ⚠️ Версии в состоянии НЕТ намеренно: она едет заголовком `X-DP-V`. Положи
    её в данные — и отпечаток менялся бы при каждом обновлении exe, хотя день
    тот же; клиент и так перезагружается по заголовку.
    ⏳ `updated` (максимум отметок данных дня) тоже нет: отпечаток уже
    отвечает «менялось или нет», а поле, посчитанное неосторожно от
    `datetime.now()`, вернуло бы ровно ту болезнь, от которой ушли 08-20.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    spec = _LIVE_SCREENS.get(screen)
    if spec is None:
        return msg_json(False, status=422, field="screen")
    key, react_name = spec
    d = _screen(date_q)
    live = key in LIVE_RELOAD and not react_on(request, react_name)
    data: dict = {"screen": screen, "date": d.isoformat(), "live": live}
    if live:
        data.update(await _panel_live(d, datetime.now(eng.TZ)))
    return live_reply(request, data)


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
                  doctor: str = Query(""), f: str = Query("")):
    """Ручная запись: {date, time, doctor, service, name, phone, nophone, birth}.

    ⚠️ `nophone` — намерение ИЗ ФОРМЫ, а не «телефон пустой» (прайор 08-16):
    пустой номер без галочки остаётся отказом `bad_phone`, как и у страницы.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", status=422)
    code = await _add_appt(_s(body, "date"), _s(body, "time"), _s(body, "doctor"),
                           _s(body, "service"), _s(body, "name"), _s(body, "phone"),
                           "1" if body.get("nophone") else "", _s(body, "birth"))
    return await _done(code, _screen(date_q), doctor, f=f)


@router.post("/api/schedule/notes")
async def api_note(request: Request, date_q: str = Query("", alias="date"),
                   doctor: str = Query(""), f: str = Query("")):
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
    return await _done(code, _screen(date_q), doctor, field="text", f=f)


@router.post("/api/schedule/appointments/{appt_id}/comment")
async def api_comment(request: Request, appt_id: int,
                      date_q: str = Query("", alias="date"),
                      doctor: str = Query(""), f: str = Query("")):
    """Комментарий ресепшена: {comment}. Пустая строка стирает его."""
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", field="comment", status=422)
    return await _done(await _set_comment(appt_id, _s(body, "comment")),
                       _screen(date_q), doctor, f=f)


@router.post("/api/schedule/appointments/{appt_id}/status")
async def api_status(request: Request, appt_id: int,
                     date_q: str = Query("", alias="date"),
                     doctor: str = Query(""), f: str = Query("")):
    """Исход визита: {to}. Удача отвечает ПУСТЫМ кодом — баннера у неё нет и
    на старой странице; отказ называет, ЧТО занято (conflict / dup).

    ⚠️ Слово не из конвейера старая страница глотает молча, а здесь это 422:
    вкладка, приславшая небывалый статус, обязана услышать отказ, иначе
    покажет пациента «в кресле», когда он туда не переходил.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", status=422)
    return await _done(await _set_status(appt_id, _s(body, "to")),
                       _screen(date_q), doctor, field="", f=f)


@router.post("/api/schedule/appointments/{appt_id}/move")
async def api_move(request: Request, appt_id: int,
                   date_q: str = Query("", alias="date"),
                   doctor: str = Query(""), f: str = Query("")):
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
    return await _done(code, _screen(date_q), doctor, f=f)
