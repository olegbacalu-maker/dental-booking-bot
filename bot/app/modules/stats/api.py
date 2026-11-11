"""JSON API аналитики. Один маршрут: весь раздел одним конвертом.

Одним, а не десятью: карточки, график, загрузка и деньги считаются из одной
выборки (`model.build`); по отдельным ресурсам это шесть походов в базу за
теми же строками и шесть снимков с разным «сейчас».
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request

from ... import engine as eng
from ...core.api import api_require
from ...core.auth import PERM_MONEY, remote_notice
from ...core.layout import msg_json
from . import model
from .routes import period

router = APIRouter()


@router.get("/api/stats")
async def api_stats(request: Request,
                    from_q: str = Query("", alias="from"),
                    to_q: str = Query("", alias="to")):
    """Весь раздел за период. Пустой период — последние семь дней, те же, что
    открывает страница раздела без параметров.

    Негодный период — отказ с кодом, а не молча другой период: иначе промах
    по сегменту года (`<input type=date>` отдаёт и «0012-08-15») показал бы
    цифры за прошлую неделю под чужими датами в полях.
    """
    if (deny := api_require(request, PERM_MONEY)) is not None:
        return deny
    today = datetime.now(eng.TZ).date()
    # `_parse_date` не падает (негодная строка = сегодня), поэтому отвергает
    # период только `period_ok`.
    d1, d2 = period(from_q, to_q, today)
    if not model.period_ok(d1, d2, today):
        return msg_json(False, "bad_period", status=422, field="from")
    # «Excel» периода — только с ПК программы (`auth.LOCAL_ONLY`)
    return msg_json(True, data={**await model.build(d1, d2, today),
                                "remote": remote_notice(request)})
