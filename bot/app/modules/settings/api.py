"""JSON API настроек — первые эндпоинты DentPilot 2.0 (экран «Clinica»).

Правила те же, что у соседнего routes.py: `core`, `db`, `engine` — да,
`main.py` — нет. Проверки и слияние профиля берутся ИЗ routes.py, а не
переписываются: `_val_clinic` и `_finish_cfg` — единственные, кто знает, как
кусок настроек ложится в clinic.json, а старая форма и новый экран правят ОДИН
файл. Второй экземпляр этой логики разошёлся бы с первым молча.

Адреса — от сущности, не от страницы (docs/dentpilot-2/api.md), и полным
путём, без prefix у роутера: карта экранов и сторож раскладки читают адрес
из декоратора.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import engine as eng
from ...core.api import api_body, api_require
from ...core.auth import PERM_SETTINGS
from ...core.layout import SETUP_HINT, msg_json, tg_refresh_meta
from .routes import _finish_cfg, _val_clinic

router = APIRouter()


def _clinic_data() -> dict:
    cfg = eng.CONFIG
    addr = cfg.get("address") or {}
    return {
        "name": cfg.get("name", ""),
        "phone": cfg.get("phone", ""),
        "address": {"ro": addr.get("ro", ""), "ru": addr.get("ru", "")},
        # профиль ещё шаблонный (демо-данные): экран говорит об этом тем же
        # текстом, что и баннер каркаса, — источник у фразы один
        "template": bool(cfg.get("template")),
        "hint": f"{SETUP_HINT[0]} {SETUP_HINT[1]}{SETUP_HINT[2]}",
    }


@router.get("/api/settings/clinic")
async def api_clinic_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=_clinic_data())


@router.post("/api/settings/clinic")
async def api_clinic_save(request: Request):
    """Тот же путь, что у `POST /admin/settings/save part=clinic`: проверка,
    слияние с профилем, атомарная запись, обновление профиля бота. Отличие
    одно — ответ JSON вместо 303 с ?msg=."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_set", status=422)
    addr = body.get("address") if isinstance(body.get("address"), dict) else {}
    try:
        cfg = _finish_cfg(**_val_clinic({
            "name": body.get("name", ""), "phone": body.get("phone", ""),
            "address": {"ro": addr.get("ro", ""), "ru": addr.get("ru", "")}}))
    except ValueError as e:
        # _val_clinic называет виновное поле («name» / «phone») — оно уезжает
        # клиенту, чтобы подсветить именно его; прочие ValueError без поля
        field = str(e) if str(e) in ("name", "phone") else ""
        return msg_json(False, "bad_set", status=422, field=field)
    except (KeyError, TypeError):
        return msg_json(False, "bad_set", status=422)
    if eng.save_config(cfg) is not None:
        return msg_json(False, "save_err", status=500)
    tg_refresh_meta()   # имя и телефон уезжают и в профиль бота — как у формы
    return msg_json(True, "ok_set", data=_clinic_data())
