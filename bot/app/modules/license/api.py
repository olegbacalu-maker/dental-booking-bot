"""JSON API лицензии (DentPilot 2.0). Правило то же: `core`, `db`, `engine` —
да, `main.py` — нет."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ...core import license as lic
from ...core.api import api_body, api_guard, api_require
from ...core.auth import PERM_SETTINGS, current_user
from ...core.layout import msg_json

router = APIRouter()


@router.get("/api/license")
async def license_api(request: Request) -> Response:
    """Состояние лицензии для клиента: баннер рисует каркас страницы, а это —
    для экранов, которым нужно знать «сегодня можно писать?» без перезагрузки."""
    if (deny := api_guard(request)) is not None:
        return deny
    return msg_json(True, data=lic.as_json())


@router.post("/api/license/terms")
async def license_terms_api(request: Request) -> Response:
    """Повторное принятие условий (29.10) JSON-ом: `{"accept": true}` от директора → квитанция, летопись,
    акт на сервер; ответ — `terms` из /api/license. Без `accept: true` — `license_terms`, как у формы."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if not body or body.get("accept") is not True:
        return msg_json(False, lic.TERMS_CODE, status=422)
    me = current_user(request)
    code = await lic.accept_terms((me or {}).get("name") or "director")
    return msg_json(True, code, data=lic.terms_state())
