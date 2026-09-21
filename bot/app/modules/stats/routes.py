"""Аналитика клиники: KPI со сравнением периодов, график по дням, источники,
загрузка, врачи, услуги, последние события. Раздел директора (PERM_MONEY).

⚠️ Считается здесь, а не в базе: в `db.py` нет ни одного агрегата. Цифры
собираются из дневных выборок и прайса из `clinic.json`, поэтому «выручка» —
это оценка по прайсу, а не бухгалтерия. Когда появятся настоящие деньги
(оплаты, долги), у модуля появится свой repository, и вот тогда SQL.

Пересобран 08-06 по макету Олега. Чего из макета тут НЕТ и почему:
- «Surse: Google / Instagram» — программа не знает таких источников; пациент
  приходит из Telegram, от регистратуры или через веб-чат. Рисовать Google —
  показать директору выдуманное число, по которому он решит про рекламу.
- «Ocuparea cabinetelor» — кабинетов в модели нет, `room` у врача — подпись.
- «Bună ziua, Liviu!» — приветствие живёт в топбаре (чип вошедшего), а не в
  заголовке раздела.

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
from ...core.layout import _shell, msg_banner, react_mount, react_on
from ...core.visits import _parse_date
from . import casa, model, render

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
    if react_on(request, "stats"):
        # период уезжает ПАРАМЕТРАМИ узла, а не разбором адреса на клиенте:
        # адрес принадлежит серверу, и клиент не должен его угадывать
        body = react_mount("stats", request.url.path,
                           {"from": d1.isoformat(), "to": d2.isoformat()})
        return _shell(msg_banner(msg) + body,
                      "statistici · perioadă selectabilă · doar director",
                      active="stat")
    d = await model.build(d1, d2, today)
    return _shell(msg_banner(msg) + render.page(d),
                  "statistici · perioadă selectabilă · doar director",
                  active="stat")


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
