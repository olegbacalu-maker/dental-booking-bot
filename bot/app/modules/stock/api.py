"""JSON API «Stoc»: склад материалов, ступень 1.

Правила — `core/stock.py`, импорт файла — `core/stock_import.py`, запись —
`db/stock.py`. Раздел ведут директор и регистратура (`PERM_STOCK`); цены и
суммы — только `PERM_MONEY` (решает `core/stock`). Команды состояния не
возвращают — экран перечитывает свою модель.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ... import db
from ...core import stock as cs
from ...core import stock_import as si
from ...core import tabfile, xlsx
from ...core.api import api_body, api_guard, api_require
from ...core.auth import PERM_MONEY, PERM_SETTINGS, PERM_STOCK, can, local_only, remote_notice, request_user
from ...core.layout import msg_json

router = APIRouter()

_REFUSE = {"old_xls": "stock_old_xls", "not_table": "stock_not_table", "too_big": "stock_too_big",
           "too_many_rows": "stock_rows", "bad_xml": "stock_not_table", "empty": "stock_file_empty"}


def _fail(e: cs.StockError):
    return msg_json(False, e.code, field=e.field, status=e.status)


async def _data(coro):
    try:
        return msg_json(True, data=await coro)
    except cs.StockError as e:
        return _fail(e)


async def _run(code: str, coro):
    try:
        got = await coro
    except cs.StockError as e:
        return _fail(e)
    return msg_json(True, code, data=got if isinstance(got, dict) else None)


async def _body(request: Request) -> dict:
    return await api_body(request) or {}


# ---------- чтение ----------

@router.get("/api/stock")
async def api_stock(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _data(cs.main_model(request_user()))


@router.get("/api/stock/item/{item_id}")
async def api_stock_item(request: Request, item_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _data(cs.item_model(request_user(), item_id))


@router.get("/api/stock/moves")
async def api_stock_moves(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _data(cs.moves_model(request_user(), dict(request.query_params)))


@router.get("/api/stock/docs")
async def api_stock_docs(request: Request, kind: str = "", status: str = ""):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _data(cs.docs_model(request_user(), kind, status))


@router.get("/api/stock/doc/{doc_id}")
async def api_stock_doc(request: Request, doc_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _data(cs.doc_model(request_user(), doc_id))


@router.get("/api/stock/buy")
async def api_stock_buy(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _data(cs.buy_model(request_user()))


@router.get("/api/stock/patient/{pid}")
async def api_stock_patient(request: Request, pid: int):
    # медзапись фиши (имплант и его лот): видит любой вошедший, как саму фишу
    if (deny := api_guard(request)) is not None:
        return deny
    return await _data(cs.patient_model(pid))


# ---------- материалы и поставщики ----------

@router.post("/api/stock/item")
async def api_stock_item_save(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    try:
        iid = await cs.save_item(request_user(), await _body(request))
    except cs.StockError as e:
        return _fail(e)
    return msg_json(True, "ok_stock_item", data={"id": iid})


@router.post("/api/stock/item/{item_id}/delete")
async def api_stock_item_delete(request: Request, item_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_item_del", cs.delete_item(request_user(), item_id))


@router.post("/api/stock/supplier")
async def api_stock_supplier_save(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    try:
        sid = await cs.save_supplier(await _body(request))
    except cs.StockError as e:
        return _fail(e)
    return msg_json(True, "ok_stock_supplier", data={"id": sid})


@router.post("/api/stock/supplier/{sid}/delete")
async def api_stock_supplier_delete(request: Request, sid: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_supplier_del", cs.delete_supplier(sid))


# ---------- движения ----------

@router.post("/api/stock/out")
async def api_stock_out(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_out", cs.take_out(request_user(), await _body(request)))


@router.post("/api/stock/open")
async def api_stock_open(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_open", cs.open_pack(request_user(), await _body(request)))


@router.post("/api/stock/move/{mid}/undo")
async def api_stock_undo(request: Request, mid: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_undo", cs.undo_move(request_user(), mid, await _body(request)))


# ---------- документы ----------

@router.post("/api/stock/doc")
async def api_stock_doc_new(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    try:
        did = await cs.create_doc(request_user(), await _body(request))
    except cs.StockError as e:
        return _fail(e)
    return msg_json(True, "ok_stock_doc", data={"id": did})


@router.post("/api/stock/doc/{doc_id}")
async def api_stock_doc_edit(request: Request, doc_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_doc", cs.edit_doc(request_user(), doc_id, await _body(request)))


@router.post("/api/stock/doc/{doc_id}/delete")
async def api_stock_doc_delete(request: Request, doc_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_doc_del", cs.delete_doc(doc_id))


@router.post("/api/stock/doc/{doc_id}/close")
async def api_stock_doc_close(request: Request, doc_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    try:
        code = await cs.close_doc(request_user(), doc_id)
    except cs.StockError as e:
        return _fail(e)
    return msg_json(True, code)


@router.post("/api/stock/doc/{doc_id}/sums")
async def api_stock_doc_sums(request: Request, doc_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    if (deny := api_require(request, PERM_MONEY)) is not None:
        return deny
    return await _run("ok_stock_sums", cs.doc_sums(request_user(), doc_id, await _body(request)))


@router.post("/api/stock/doc/{doc_id}/storno")
async def api_stock_doc_storno(request: Request, doc_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    if (deny := api_require(request, PERM_MONEY)) is not None:
        return deny
    return await _run("ok_stock_storno", cs.storno_doc(request_user(), doc_id, await _body(request)))


# ---------- «Comandat» и настройки ----------

@router.post("/api/stock/order")
async def api_stock_order(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_order", cs.order(request_user(), await _body(request)))


@router.post("/api/stock/order/{item_id}/cancel")
async def api_stock_unorder(request: Request, item_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return await _run("ok_stock_unorder", cs.unorder(item_id))


@router.post("/api/stock/prefs")
async def api_stock_prefs(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return await _run("ok_stock_prefs", cs.save_prefs(await _body(request)))


# ---------- импорт из файла ----------

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


def _parse(blob: bytes, name: str, opts: dict, money: bool):
    """Разбор или код отказа. Тяжёлая — в потоке, не в цикле событий."""
    try:
        table = tabfile.read(blob, name)
    except tabfile.Refuse as e:
        return _REFUSE[e.code]
    res = si.resolve(table, opts)
    if res is None:
        return "stock_import_opts"
    recs = si.build(table, res, money) if si.ready(res) else []
    if len(recs) > si.MAX_ROWS:
        return "stock_rows"
    return table, res, recs


async def _load(request: Request):
    q = request.query_params
    opts = si.parse_opts(q.get("opts", ""))
    if opts is None:
        return msg_json(False, "stock_import_opts", status=422)
    blob = await _blob(request)
    if blob is None:
        return msg_json(False, "stock_too_big", status=413)
    name = q.get("name", "").strip()[:200]
    got = await asyncio.to_thread(_parse, blob, name, opts, can(request_user(), PERM_MONEY))
    if isinstance(got, str):
        return msg_json(False, got, status=413 if got == "stock_too_big" else 422)
    table, res, recs = got
    si.analyse(recs, await db.stock_items(), opts["choices"])
    return blob, name, opts, table, res, recs


@router.get("/api/stock/import")
async def api_stock_import(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    return msg_json(True, data={
        "imports": await si.history(request_user()),
        "fields": [{"id": f, "label": label} for f, label in si.FIELDS],
        "limits": {"bytes": tabfile.MAX_FILE, "rows": si.MAX_ROWS}, "units": list(cs.STOCK_UNITS),
        "remote": remote_notice(request), "can": cs.can_map(request_user())})


@router.post("/api/stock/import/check")
async def api_stock_import_check(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    got = await _load(request)
    if isinstance(got, Response):
        return got
    blob, name, opts, table, res, recs = got
    sheet = table.sheets[res["sheet"]]
    head = next((ln for rno, ln in sheet.rows if rno == res["header"]), [])
    width = max([len(head)] + [max(res["cols"], default=-1) + 1])
    dup = await db.stock_import_doc_by_print(si.fingerprint(blob))
    return msg_json(True, data={
        "file": {"name": name, "kind": table.kind, "size": len(blob),
                 "sheets": [{"name": s.name, "rows": len(s.rows)} for s in table.sheets]},
        "opts": {"sheet": res["sheet"], "header": res["header"],
                 "cols": {str(k): v for k, v in res["cols"].items()}},
        "columns": [{"index": i, "letter": xlsx._col(i), "title": si._text(head[i]) if i < len(head) else "",
                     "field": res["cols"].get(i, "")} for i in range(width)],
        "preview": [{"line": rno, "cells": [si._text(v) for v in ln[:width]]}
                    for rno, ln in sheet.rows if rno > res["header"]][:6],
        "ready": si.ready(res), "rows": [si.row_out(r) for r in recs], "counts": si.summary(recs),
        "dup": ({"id": dup["id"], "at": cs._iso(dup["created_at"]), "file": dup["data"].get("file") or dup["nr"]}
                if dup else None),
        "token": si.token(blob, res, opts)})


@router.post("/api/stock/import/run")
async def api_stock_import_run(request: Request):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    got = await _load(request)
    if isinstance(got, Response):
        return got
    blob, name, opts, _table, res, recs = got
    if not si.ready(res):
        return msg_json(False, "stock_import_cols", status=422)
    if request.query_params.get("token", "") != si.token(blob, res, opts):
        return msg_json(False, "stock_import_stale", status=409)
    if await db.stock_import_doc_by_print(si.fingerprint(blob)):
        return msg_json(False, "stock_import_dup", status=409)
    if not any(r["act"] == "new" for r in recs):
        return msg_json(False, "stock_import_empty", status=422)
    return msg_json(True, "ok_stock_import", data=await si.run(request_user(), recs, name, blob))


@router.post("/api/stock/import/{doc_id}/undo")
async def api_stock_import_undo(request: Request, doc_id: int):
    if (deny := api_require(request, PERM_STOCK)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    return await _run("ok_stock_import_undo", si.undo(request_user(), doc_id))
