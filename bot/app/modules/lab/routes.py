"""Лист наряда в лабораторию — серверная страница, как листы фиши.

Экраны раздела — React (оболочки `/admin/lab` и `/admin/settings/lab`), данные —
`api.py`. Каждое открытие листа пишет `tiparit`: это передача данных пациента
лаборатории (закон 195)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core import lab as clab
from ...core.auth import _guard, request_user
from . import sheet

router = APIRouter()

# «Înapoi» ведёт только на фишу или в список — чужой адрес в `back` был бы
# открытым редиректом
_BACK = re.compile(r"^/admin/(?:patient/\d+|lab)(?:[/?#][^\s\"'<>]*)?$")


@router.get("/admin/lab/{oid}/tipar", response_class=HTMLResponse)
async def admin_lab_print(request: Request, oid: int, back: str = ""):
    if (deny := _guard(request)) is not None:
        return deny
    try:
        data = await clab.sheet_data(request_user(), oid)
    except clab.LabError:
        return HTMLResponse("Comanda nu există", status_code=404)
    back = back if _BACK.match(back or "") else "/admin/lab"
    return HTMLResponse(sheet.render(data, back))
