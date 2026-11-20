"""«Servicii și tarife» — страница экрана и выгрузка прайса в Excel.

Данные и команды — `api.py`; правила — `core/tarife.py`. Смотрит прайс любой
вошедший; править на экране — по `can_edit` модели (`PERM_PRICES`).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from ...core import tarife as ct
from ...core import xlsx
from ...core.auth import _guard
from ...core.layout import react_shell, shell_model

router = APIRouter()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/admin/tarife.xlsx")
async def admin_tarife_xlsx(request: Request):
    """Прайс файлом — теми же колонками, что читает импорт: выгрузил, поправил,
    загрузил. Данных пациентов в нём нет, поэтому и из сети открыт."""
    if (deny := _guard(request)) is not None:
        return deny
    blob = xlsx.book(ct.HEAD_OUT, ct.export_rows(), widths=[24, 48, 40, 16], sheet_name="Tarife")
    return Response(blob, media_type=_XLSX, headers={
        "Content-Disposition": 'attachment; filename="servicii-si-tarife.xlsx"'})


@router.get("/admin/tarife", response_class=HTMLResponse)
async def admin_tarife(request: Request):
    """Экран прайса (React): смотрит любой вошедший, правит — по `can_edit` модели."""
    if (deny := _guard(request)) is not None:
        return deny
    return react_shell("tarife", request.url.path, shell_model("tarife", ""))
