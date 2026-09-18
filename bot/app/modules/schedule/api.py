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
from .routes import _week_model

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
