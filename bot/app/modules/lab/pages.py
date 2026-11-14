"""«Laborator» — страницы-оболочки раздела: общий список заказов и каталог лабораторий.

Данные и команды — `api.py`, лист наряда — `routes.py`; здесь только `react_shell`.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.auth import PERM_LABS, _guard, require
from ...core.layout import react_shell, shell_model

router = APIRouter()


@router.get("/admin/lab", response_class=HTMLResponse)
async def admin_lab(request: Request):
    # заказы видят и пишут все вошедшие: врач — у кресла, стойка — у телефона
    if (deny := _guard(request)) is not None:
        return deny
    return react_shell("lab", request.url.path, shell_model("lab", ""))


@router.get("/admin/settings/lab", response_class=HTMLResponse)
async def admin_settings_lab(request: Request):
    if (deny := require(request, PERM_LABS)) is not None:
        return deny
    return react_shell("settings_lab", request.url.path, shell_model("set", ""))
