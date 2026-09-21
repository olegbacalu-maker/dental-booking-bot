"""JSON API аналитики (C15). Один маршрут: весь раздел одним конвертом.

⭐ Одним, а не десятью — по той же причине, по какой старая страница делала
одну загрузку: секции НЕ независимы. Плитки, график, загрузка и деньги
считаются из одной выборки дня (`model.build`), и раздать их по ресурсам
значило бы сходить в базу шесть раз за теми же строками, да ещё и получить
шесть снимков с разным «сейчас».

Правила те же, что у соседнего `routes.py`: `core`, `db`, `engine` — да,
`main.py` — нет. Считает `model.py`, и он же считает для старой страницы: два
экземпляра этой арифметики разошлись бы молча, потому что цифры выглядят
правдоподобно всегда.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request

from ... import engine as eng
from ...core.api import api_require
from ...core.auth import PERM_MONEY
from ...core.layout import msg_json
from . import model
from .routes import period

router = APIRouter()


@router.get("/api/stats")
async def api_stats(request: Request,
                    from_q: str = Query("", alias="from"),
                    to_q: str = Query("", alias="to")):
    """Весь раздел за период. Пустой период — последние семь дней, те же, что
    открывает старая страница без параметров.

    ⛔ Негодный период — ОТКАЗ с кодом, а не молча другой период. Старая
    страница отвечала редиректом на себя, и человек, промахнувшийся по
    сегменту года (`<input type=date>` отдаёт и «0012-08-15»), получал вместо
    объяснения цифры за прошлую неделю под своими же датами в полях.
    """
    if (deny := api_require(request, PERM_MONEY)) is not None:
        return deny
    today = datetime.now(eng.TZ).date()
    # ⚠️ `_parse_date` не падает: негодная строка становится СЕГОДНЯ. Значит
    # отвергать период обязан `period_ok`, и он же ловит законную ISO-дату с
    # промахом по сегменту года.
    d1, d2 = period(from_q, to_q, today)
    if not model.period_ok(d1, d2, today):
        return msg_json(False, "bad_period", status=422, field="from")
    return msg_json(True, data=await model.build(d1, d2, today))
