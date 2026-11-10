"""«Registre» — санитарные регистры клиники (МАКЕТ 10.11.2026, сессия san-registers).

⚠️ Макет этапа 1: данных на сервере нет, экран рисует заглушку клиента
(`frontend/src/features/registre/mock.ts`). Права и таблицы — этап 2, по выбору Олега.
Формы: 257/e (автоклав, Ordin MS 828/2011), 502/e (генеральная уборка) и 501/e
(УФ-лампы, Ordin MS 630/2016); регистр «fizic sau electronic» — HG 4/2026 п.141.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.auth import PERM_SETTINGS, _guard, require
from ...core.layout import react_shell, shell_model

router = APIRouter()


@router.get("/admin/registre", response_class=HTMLResponse)
async def admin_registre(request: Request):
    # пишут все вошедшие: права нет, но вход — обязателен
    if (deny := _guard(request)) is not None:
        return deny
    return react_shell("registre", request.url.path, shell_model("reg", ""))


@router.get("/admin/settings/registre", response_class=HTMLResponse)
async def admin_settings_registre(request: Request):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    return react_shell("settings_registre", request.url.path, shell_model("set", ""))
