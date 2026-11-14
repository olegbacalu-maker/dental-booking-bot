"""«Stoc» — серверные страницы склада: лист «De cumpărat» и Excel движений
месяца для бухгалтера.

Экраны раздела — React (оболочка `/admin/stoc` — `pages.py`), данные — `api.py`."""
from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ...core import stock as cs
from ...core import xlsx
from ...core.auth import PERM_STOCK, local_only, request_user, require
from . import sheet

router = APIRouter()

# «Înapoi» ведёт только в раздел склада — чужой адрес в `back` был бы открытым редиректом
_BACK = re.compile(r"^/admin/stoc(?:[/?#][^\s\"'<>]*)?$")
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/admin/stoc/cumparat/tipar", response_class=HTMLResponse)
async def admin_stock_buy_print(request: Request, q: str = "", back: str = ""):
    if (deny := require(request, PERM_STOCK)) is not None:
        return deny
    data = await cs.buy_sheet(request_user(), cs.parse_pick(q))
    return HTMLResponse(sheet.render(data, back if _BACK.match(back or "") else "/admin/stoc"))


@router.get("/admin/stoc/miscari.xlsx")
async def admin_stock_moves_xlsx(request: Request, month: str = ""):
    # движения файлом — только с ПК программы (`auth.LOCAL_ONLY`), как журнал Excel
    if (deny := require(request, PERM_STOCK)) is not None:
        return deny
    if (deny := local_only(request, page=True)) is not None:
        return deny
    span = cs.month_bounds(month) or cs.month_bounds(cs.today().strftime("%Y-%m"))
    head, rows, widths = await cs.month_rows(request_user(), *span)
    blob = xlsx.book(head, rows, widths=widths, sheet_name="Miscari")
    return Response(blob, media_type=_XLSX, headers={
        "Content-Disposition": f'attachment; filename="stoc-miscari-{span[0].strftime("%Y-%m")}.xlsx"'})
