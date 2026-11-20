"""JSON API «Servicii și tarife»: прайс клиники для плана лечения.

Правила, запись и импорт — `core/tarife.py`; контракт —
`side-session-notes\\2026-11-20\\tarife-contract.md`. Смотрит прайс любой вошедший
(цены плана и так видны всем), правит — `PERM_PRICES` (директор и регистратура).
Импорт — файл ТЕЛОМ, только с ПК программы (`auth.LOCAL_ONLY`), как у склада.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from ...core import tabfile
from ...core import tarife as ct
from ...core.api import api_body, api_guard, api_require
from ...core.auth import PERM_PRICES, can, local_only, remote_notice, request_user
from ...core.layout import msg_json

router = APIRouter()


def _model(request: Request) -> dict:
    return ct.model(can(request_user(), PERM_PRICES), remote_notice(request))


def _fail(e: ct.Refuse):
    return msg_json(False, e.code, field=e.field, data=e.data, status=e.status)


@router.get("/api/tarife")
async def api_tarife(request: Request):
    if (deny := api_guard(request)) is not None:
        return deny
    return msg_json(True, data=_model(request))


@router.post("/api/tarife")
async def api_tarife_save(request: Request):
    """Тело — только тронутое (контракт § 5); отказ — код с полем."""
    if (deny := api_require(request, PERM_PRICES)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_tarif", status=422)
    try:
        err, created = ct.store(body)
    except ct.Refuse as e:
        return _fail(e)
    except (KeyError, TypeError, AttributeError):
        return msg_json(False, "bad_tarif", status=422)
    if err is not None:
        return msg_json(False, "save_err", status=500)
    return msg_json(True, "ok_tarife", data={**_model(request), "created": created})


async def _blob(request: Request) -> bytes | None:
    """None — больше потолка; лишнее дочитывается, чтобы отказ дошёл словами."""
    buf, over = bytearray(), False
    async for chunk in request.stream():
        if not over:
            buf += chunk
            if len(buf) > tabfile.MAX_FILE:
                over = True
                buf.clear()
    return None if over else bytes(buf)


async def _check(request: Request):
    """(файл, имя, строки, счётчики, новые категории, тело записи) или отказ."""
    blob = await _blob(request)
    if blob is None:
        return msg_json(False, "stock_too_big", status=413)
    name = request.query_params.get("name", "").strip()[:200]
    try:
        rows = await asyncio.to_thread(ct.parse, blob, name)
    except ct.Refuse as e:
        return _fail(e)
    return (blob, name, *ct.analyse(rows))


@router.post("/api/tarife/import/check")
async def api_tarife_import_check(request: Request):
    """Предпросмотр: что добавится, что сменится, что без изменений. Ничего не пишет."""
    if (deny := api_require(request, PERM_PRICES)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    got = await _check(request)
    if not isinstance(got, tuple):
        return got
    blob, name, rows, counts, cats_new, _body = got
    return msg_json(True, data={"file": {"name": name, "size": len(blob)}, "rows": rows,
                                "counts": counts, "cats_new": cats_new, "token": ct.token(blob)})


@router.post("/api/tarife/import/run")
async def api_tarife_import_run(request: Request):
    """Тот же файл телом и `token` проверки: прайс поменялся после неё — 409."""
    if (deny := api_require(request, PERM_PRICES)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    got = await _check(request)
    if not isinstance(got, tuple):
        return got
    blob, _name, _rows, counts, _cats, body = got
    if request.query_params.get("token", "") != ct.token(blob):
        return msg_json(False, "tarife_import_stale", status=409)
    if not counts["new"] and not counts["changed"]:
        return msg_json(False, "tarife_import_empty", status=422)
    try:
        err, _created = ct.store(body)
    except ct.Refuse as e:
        return _fail(e)
    if err is not None:
        return msg_json(False, "save_err", status=500)
    return msg_json(True, "ok_tarife_import", data={**_model(request), "imported": counts})
