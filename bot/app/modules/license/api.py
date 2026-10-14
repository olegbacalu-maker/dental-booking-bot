"""JSON API лицензии (DentPilot 2.0). Правило то же: `core`, `db`, `engine` —
да, `main.py` — нет."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ...core import license as lic
from ...core.api import api_guard
from ...core.layout import msg_json

router = APIRouter()


@router.get("/api/license")
async def license_api(request: Request) -> Response:
    """Состояние лицензии для клиента: баннер рисует каркас страницы, а это —
    для экранов, которым нужно знать «сегодня можно писать?» без перезагрузки."""
    if (deny := api_guard(request)) is not None:
        return deny
    return msg_json(True, data=lic.as_json())
