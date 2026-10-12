"""Аналитика клиники: страница раздела (оболочка React) и печатный отчёт кассы.
Раздел директора (PERM_MONEY).

Цифры считает `model.py` (в `db.py` агрегатов нет: выборки дня и прайс из
`clinic.json`, поэтому «выручка» — оценка по прайсу, а не бухгалтерия),
отдаёт `api.py`, рисует React-экран (раскладка B8). Старая серверная страница
снята 12.10 (docs/dentpilot-2/legacy-removal.md).

⛔ Источников, которых программа не знает (Google, Instagram), нет и не будет:
нарисованное число директор примет за правду и решит по нему про рекламу.

Каждый период сравнивается С ТАКИМ ЖЕ ПО ДЛИНЕ куском сразу перед ним: у
недели это прошлая неделя, у «сегодня» — вчера. Сравнение с «прошлым месяцем»
для произвольного периода врало бы — периоды разной длины несравнимы.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ... import db
from ... import engine as eng
from ...core.auth import PERM_MONEY, require
from ...core.layout import react_shell, shell_model
from ...core.visits import _parse_date
from . import casa, model

router = APIRouter()


@router.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(
    request: Request,
    from_q: str = Query("", alias="from"),
    to_q: str = Query("", alias="to"),
    msg: str = "",
):
    # деньги — единственное, что закрыто от врача и регистратуры (решение
    # Олега 08-06); проверка ЗДЕСЬ, а не только в меню: адрес набирается руками
    if (deny := require(request, PERM_MONEY)) is not None:
        return deny
    today = datetime.now(eng.TZ).date()
    d1, d2 = period(from_q, to_q, today)
    if not model.period_ok(d1, d2, today):
        return RedirectResponse("/admin/stats?msg=bad_period", status_code=303)
    # период уезжает ПАРАМЕТРАМИ узла, а не разбором адреса на клиенте:
    # адрес принадлежит серверу, и клиент не должен его угадывать
    # ⭐ B1: оболочку рисует React, сервер печатает голову и модель.
    # подпись печатает сам экран (08.10): период и «comparat cu …»
    return react_shell("stats", request.url.path,
                       shell_model("stat", "", msg=msg),
                       {"from": d1.isoformat(), "to": d2.isoformat()})


def period(from_q: str, to_q: str, today) -> tuple:
    """Границы отбора — ОДНИ на страницу и на JSON. По умолчанию последние
    семь дней; перевёрнутый период разворачивается, а не отвергается."""
    d1 = _parse_date(from_q) if from_q else today - timedelta(days=6)
    d2 = _parse_date(to_q) if to_q else today
    return (d2, d1) if d2 < d1 else (d1, d2)


@router.get("/admin/casa", response_class=HTMLResponse)
async def admin_casa(request: Request, d: str = ""):
    """Печатный отчёт кассы за день. `?d=YYYY-MM-DD`, по умолчанию сегодня.

    За `PERM_MONEY`, как и вся страница статистики: это выручка клиники, а не
    долг конкретного пациента (тот виден любой роли — и в фише, и в списке).
    Проверка здесь, а не только в ссылке: адрес набирается руками.
    """
    if (deny := require(request, PERM_MONEY)) is not None:
        return deny
    day = _parse_date(d) if d else datetime.now(eng.TZ).date()
    start = datetime(day.year, day.month, day.day, tzinfo=eng.TZ)
    rows = await db.payments_day(start, start + timedelta(days=1))
    return HTMLResponse(casa.render(day, rows))
