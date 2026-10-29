"""«Rechemări» (29.10.2026): страница раздела — оболочка React.

Экран регистратуры и директора (`PERM_RECALL`, В1 = А: врач списка не видит,
строку срока в фише — видит). Данные — `api.py` (`/api/recall`), правило
списка — `core/recall.py`, контракт — `docs/dentpilot-2/recall-api.md`.
Счётчика в пункте меню нет намеренно: он стоил бы запроса на каждой странице
и стал бы баннером, который перестают читать; счётчик живёт на главной.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.auth import PERM_RECALL, require
from ...core.layout import react_shell, shell_model

router = APIRouter()


@router.get("/admin/rechemari", response_class=HTMLResponse)
async def admin_recall(request: Request):
    # право проверяется ЗДЕСЬ, а не только в меню: адрес набирается руками
    if (deny := require(request, PERM_RECALL)) is not None:
        return deny
    return react_shell("recall", request.url.path, shell_model("rec", ""))
