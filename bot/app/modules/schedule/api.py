"""JSON API журнала (DentPilot 2.0). Пока — недельный календарь (C24).

Правила живут в `week.py` и одни на старую страницу и на этот маршрут: состав
колонок, счётчики и цвет чипа считает сервер, клиент их только раскладывает.

⛔ Маршруты под `/api/` зовут `api_guard`, никогда `_guard`: тот отвечает
редиректом 303 на экран входа, и `fetch` сходил бы по нему сам, вернув 200 с
формой входа — экран показал бы пустой журнал как «успех».

⚠️ Дни приезжают СПИСКОМ показанных, а не семью позициями. Закрытый день
исчезает, если в нём нет записей, поэтому колонок 5, 6 или 7, и раскладка по
`weekday()` поставила бы субботу под воскресенье — правдоподобно и неверно.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request

from ... import engine as eng
from ...core.api import api_guard
from ...core.layout import msg_json
from ...core.visits import _parse_date
from .routes import _day_model, _week_model

router = APIRouter()


@router.get("/api/schedule/week")
async def api_week(request: Request, date_q: str = Query("", alias="date")):
    """Неделя, в которую попал день: колонки, чипы, итог, соседние недели.

    ⚠️ Кривая дата молча открывает текущую неделю — как у страницы: адрес
    журнала набирают руками, и отказ вместо календаря здесь бесполезен.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    data = await _week_model(d)
    # день, от которого открыли неделю: ссылки «Zi» и «Săptămâna» ведут на
    # него, а не на понедельник — так же, как на старой странице
    data["day"] = d.isoformat()
    return msg_json(True, data=data)

@router.get("/api/schedule/day")
async def api_day(request: Request, date_q: str = Query("", alias="date"),
                  doctor: str = Query("")):
    """Сетка дня: все врачи или один (`?doctor=dk`) — тот же построитель.

    ⚠️ Колонки приезжают СПИСКОМ, ячейка ссылается на позицию в нём: врачей
    бывает ноль, один или все, и раскладка по фиксированным местам сломалась
    бы на первом выключенном.
    ⛔ Поля перетаскивания (`min`, `dur`, `busy`, `movable`) те же, что у
    `_move_attrs` старой страницы: договор с переносом один на оба экрана.
    """
    if (deny := api_guard(request)) is not None:
        return deny
    d = _parse_date(date_q) if date_q else datetime.now(eng.TZ).date()
    data = await _day_model(d, doctor)
    if data is None:
        return msg_json(False, status=404)
    return msg_json(True, data=data)

