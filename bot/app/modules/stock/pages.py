"""«Stoc» — страницы-оболочки склада материалов и его настроек.

Данные и команды — `api.py`; здесь только `react_shell`.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.auth import PERM_STOCK, require
from ...core.layout import react_shell, shell_model

router = APIRouter()


@router.get("/admin/stoc", response_class=HTMLResponse)
async def admin_stoc(request: Request):
    if (deny := require(request, PERM_STOCK)) is not None:
        return deny
    return react_shell("stock", request.url.path, shell_model("stoc", ""))


@router.get("/admin/settings/stoc", response_class=HTMLResponse)
async def admin_settings_stoc(request: Request):
    if (deny := require(request, PERM_STOCK)) is not None:
        return deny
    return react_shell("settings_stock", request.url.path, shell_model("set", ""))
