"""JSON API «Registre» (10.11.2026): санитарные регистры 257/e, 502/e, 501/e.

Правила — `core/registre.py`, запись — `db/registre.py`. Пишут ВСЕ вошедшие
(`api_guard`). КТО СДЕЛАЛ — человек из окна (`doer`, «Personal»), учётка —
кто внёс (registre-people, 10.11).
Удаляет и правит каталог только директор (`PERM_SETTINGS`). Учётку и время
ставит сервер: клиент их не присылает. Команды состояния не
возвращают — экран перечитывает `GET /api/registre`.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import db
from ...core import registre as reg
from ...core.api import api_body, api_guard, api_require
from ...core.auth import PERM_SETTINGS, can, request_user
from ...core.layout import msg_json

router = APIRouter()

# слово летописи клиники при удалении — готовой строкой (летопись не переписывается)
_FORM = {"257": "257/e", "502": "502/e", "501": "501/e"}


def _fail(e: reg.RegError):
    return msg_json(False, e.code, field=e.field, status=e.status)


async def _run(request: Request, code: str, coro):
    """Вход проверен вызывающим; ошибка правила — её код и поле."""
    try:
        await coro
    except reg.RegError as e:
        return _fail(e)
    return msg_json(True, code)


@router.get("/api/registre")
async def api_registre(request: Request, month: str = ""):
    if (deny := api_guard(request)) is not None:
        return deny
    me = request_user()
    return msg_json(True, data=await reg.model(month, me, can(me, PERM_SETTINGS), can(me, PERM_SETTINGS)))


@router.post("/api/registre/257")
async def api_cycle_start(request: Request):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_start", reg.start_cycle(request_user(), await api_body(request) or {}))


@router.post("/api/registre/257/{row_id}/finish")
async def api_cycle_finish(request: Request, row_id: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_finish",
                      reg.finish_cycle(request_user(), row_id, await api_body(request) or {}))


@router.post("/api/registre/257/{row_id}/bio")
async def api_cycle_bio(request: Request, row_id: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_bio", reg.bio_result(request_user(), row_id, await api_body(request) or {}))


@router.post("/api/registre/502")
async def api_clean_add(request: Request):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_clean", reg.add_clean(request_user(), await api_body(request) or {}))


@router.post("/api/registre/502/{row_id}/sup")
async def api_clean_sup(request: Request, row_id: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_sup", reg.supervise(request_user(), row_id, await api_body(request) or {}))


@router.post("/api/registre/501")
async def api_uv_on(request: Request):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_uv_on", reg.uv_on(request_user(), await api_body(request) or {}))


@router.post("/api/registre/501/{row_id}/off")
async def api_uv_off(request: Request, row_id: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_uv_off", reg.uv_off(request_user(), row_id))


@router.post("/api/registre/{form}/{row_id}/fix")
async def api_fix(request: Request, form: str, row_id: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run(request, "ok_san_fix", reg.fix(form, request_user(), row_id, await api_body(request) or {}))


@router.post("/api/registre/{form}/{row_id}/delete")
async def api_delete(request: Request, form: str, row_id: int):
    # только директор; мягко — строка уходит с экрана и листа, в базе остаётся
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if form not in reg.REGS:
        return msg_json(False, "san_gone", status=404)
    who = (request_user() or {}).get("name") or "director"
    if not await db.san_delete(form, row_id, who):
        return msg_json(False, "san_gone", status=404)
    await db.log_clinic_event("registru", f"Registrul {_FORM[form]}: înregistrarea nr. {row_id} ștearsă", who)
    return msg_json(True, "ok_san_del")


# ---------- каталог (Setări › Registre sanitare) ----------

@router.get("/api/settings/registre")
async def api_settings_registre(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=await reg.catalog())


@router.post("/api/settings/registre/item")
async def api_settings_registre_item(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    b = await api_body(request) or {}
    try:
        item = reg.clean_item(str(b.get("kind") or ""), b)
        if item.get("id"):
            old = await db.san_item(item["id"])
            if not old or old["kind"] != item["kind"]:
                return msg_json(False, "san_gone", status=404)
            if item["kind"] == "lamp":
                # история замен ведётся «Lampă nouă», а не формой
                item["data"]["changes"] = (old.get("data") or {}).get("changes") or []
        elif item["kind"] == "norms":
            have = await db.san_items("norms")
            if have:
                item["id"] = have[0]["id"]
    except reg.RegError as e:
        return _fail(e)
    new_id = await db.san_item_save(item)
    return msg_json(True, "ok_san_item", data={"id": new_id})


@router.post("/api/settings/registre/lamp/{lamp_id}/new")
async def api_settings_lamp_new(request: Request, lamp_id: int):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return await _run(request, "ok_san_lamp_new", reg.lamp_new(request_user(), lamp_id))
