"""JSON API «Laborator»: заказы в зуботехническую лабораторию и каталог.

Правила — `core/lab.py`, запись — `db/lab.py`. Заказы видят и ведут все
вошедшие (врач — как картотеку, вся); каталог — `PERM_LABS`, настройки наряда —
`PERM_SETTINGS`, цену лаборатории — только `PERM_MONEY` (решает `core/lab`).
Команды состояния не возвращают — экран перечитывает свою модель.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import db
from ...core import lab as clab
from ...core.api import api_body, api_guard, api_require
from ...core.auth import PERM_LABS, PERM_SETTINGS, request_user
from ...core.layout import msg_json

router = APIRouter()


def _fail(e: clab.LabError):
    return msg_json(False, e.code, field=e.field, status=e.status)


async def _data(coro):
    try:
        return msg_json(True, data=await coro)
    except clab.LabError as e:
        return _fail(e)


async def _run(code: str, coro):
    try:
        await coro
    except clab.LabError as e:
        return _fail(e)
    return msg_json(True, code)


def _int_or_none(v: str) -> int | None:
    return int(v) if v and v.isdigit() else None


@router.get("/api/lab")
async def api_lab_list(request: Request, f: str = "", q: str = "", lab: str = ""):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _data(clab.list_model(request_user(), f, q, lab))


@router.get("/api/lab/patient/{pid}")
async def api_lab_patient(request: Request, pid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _data(clab.patient_model(request_user(), pid))


@router.get("/api/lab/form")
async def api_lab_form(request: Request, pid: str = "", plan_item: str = ""):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _data(clab.form_model(request_user(), _int_or_none(pid), _int_or_none(plan_item)))


@router.get("/api/lab/due")
async def api_lab_due(request: Request, lab: str = "", sent: str = ""):
    if (deny := api_guard(request)) is not None:
        return deny
    lab_id = _int_or_none(lab)
    if lab_id is None:
        return msg_json(False, "lab_bad", field="lab", status=422)
    try:
        when = clab._date_in({"sent": sent}, "sent", "sent_on")
        due = await clab.due_for(lab_id, when)
    except clab.LabError as e:
        return _fail(e)
    return msg_json(True, data={"due_on": due.isoformat()})


@router.get("/api/lab/order/{oid}")
async def api_lab_order(request: Request, oid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _data(clab.order_model(request_user(), oid))


@router.post("/api/lab/order")
async def api_lab_create(request: Request):
    if (deny := api_guard(request)) is not None:
        return deny
    try:
        oid, nr = await clab.create(request_user(), await api_body(request) or {})
    except clab.LabError as e:
        return _fail(e)
    return msg_json(True, "ok_lab_new", data={"id": oid, "nr": nr})


@router.post("/api/lab/order/{oid}")
async def api_lab_edit(request: Request, oid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run("ok_lab_save", clab.edit(request_user(), oid, await api_body(request) or {}))


@router.post("/api/lab/order/{oid}/step")
async def api_lab_step(request: Request, oid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run("ok_lab_step", clab.step(request_user(), oid, await api_body(request) or {}))


@router.post("/api/lab/order/{oid}/etapa")
async def api_lab_etapa(request: Request, oid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run("ok_lab_etapa", clab.etapa(request_user(), oid, await api_body(request) or {}))


@router.post("/api/lab/order/{oid}/refacere")
async def api_lab_refacere(request: Request, oid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run("ok_lab_refacere", clab.refacere(request_user(), oid, await api_body(request) or {}))


@router.post("/api/lab/order/{oid}/undo")
async def api_lab_undo(request: Request, oid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run("ok_lab_undo", clab.undo(request_user(), oid))


@router.post("/api/lab/order/{oid}/cancel")
async def api_lab_cancel(request: Request, oid: int):
    if (deny := api_guard(request)) is not None:
        return deny
    return await _run("ok_lab_cancel", clab.cancel(request_user(), oid, await api_body(request) or {}))


# ---------- каталог и настройки (Setări › Laboratoare) ----------

@router.get("/api/settings/lab")
async def api_settings_lab(request: Request):
    if (deny := api_require(request, PERM_LABS)) is not None:
        return deny
    return await _data(clab.settings_model(request_user()))


@router.post("/api/settings/lab/item")
async def api_settings_lab_item(request: Request):
    if (deny := api_require(request, PERM_LABS)) is not None:
        return deny
    try:
        lab = await clab.clean_lab(await api_body(request) or {})
    except clab.LabError as e:
        return _fail(e)
    return msg_json(True, "ok_lab_item", data={"id": await db.lab_save(lab)})


@router.post("/api/settings/lab/item/{lab_id}/delete")
async def api_settings_lab_delete(request: Request, lab_id: int):
    if (deny := api_require(request, PERM_LABS)) is not None:
        return deny
    if not await db.lab_get(lab_id):
        return msg_json(False, "lab_lab_gone", status=404)
    if not await db.lab_delete(lab_id):
        return msg_json(False, "lab_has_orders", status=409)
    return msg_json(True, "ok_lab_del")


@router.post("/api/settings/lab/prefs")
async def api_settings_lab_prefs(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return await _run("ok_lab_prefs", clab.save_prefs(await api_body(request) or {}))
