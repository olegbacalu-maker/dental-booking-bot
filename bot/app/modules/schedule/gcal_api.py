"""Вкладка «Google Calendar»: JSON API.

Правила — в `gcal.py`. Перенос отвечает кодами и полями окна записи журнала:
окно показывает отказ одинаково, откуда бы его ни открыли. Врачу вкладка
закрыта: в общем календаре пациенты всех врачей.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse

from ...core import ics
from ...core.api import api_body, api_require
from ...core.auth import PERM_SCHEDULE_ALL, PERM_SETTINGS, require
from ...core.layout import msg_json, react_shell, shell_model
from . import gcal
from .api import _CONFLICT, _FIELD

router = APIRouter()

_GONE = {"gc_gone", "gc_moved", "gc_appt", "gc_patient", "gc_no_text"}


async def _list(request: Request) -> dict:
    """Список в том отборе, в каком стоит экран: вкладка, поиск, день, месяц."""
    at = request.query_params
    return await gcal.listing(at.get("f", ""), at.get("q", ""), at.get("date", ""), at.get("month", ""))


async def _reply(code: str, request: Request, **extra):
    data = await _list(request)
    data.update(extra)
    return msg_json(True, code, data=data)


def _refuse(code: str):
    return msg_json(False, code, status=409 if code in _GONE else 422)


@router.get("/admin/google", response_class=HTMLResponse)
async def admin_gcal(request: Request):
    if (deny := require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    return react_shell("gcal", request.url.path, shell_model("gcal", ""))


@router.get("/api/gcal")
async def api_gcal(request: Request):
    """`f` — nou | mutat | omis | nerecunoscut | schimbat; `q` — поиск;
    `date` — один день; `month` — какой месяц показать в календаре."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    return msg_json(True, data=await _list(request))


@router.post("/api/gcal/file")
async def api_gcal_file(request: Request, file: UploadFile = File(...)):
    """multipart `file`. На диск не кладётся: в файле имена и телефоны, а
    папка данных зашифрована не у всех."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    chunks, size = [], 0
    try:
        while chunk := await file.read(1024 * 256):
            size += len(chunk)
            if size > gcal.MAX_FILE:
                return msg_json(False, "gc_too_big", field="file", status=422)
            chunks.append(chunk)
    finally:
        await file.close()
    if not size:
        return msg_json(False, "gc_no_file", field="file", status=422)
    try:
        report = await gcal.load(b"".join(chunks))
    except ics.Refused as e:
        return msg_json(False, f"gc_{e.code}", field="file", status=422)
    return await _reply("gc_loaded", request, load=report)


@router.post("/api/gcal/events/{eid}/move")
async def api_gcal_move(request: Request, eid: int):
    """Тело окна записи журнала плюс `pid`, если выбрана существующая фиша."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad", status=422)
    code, appt_id = await gcal.move(eid, body)
    if code in _GONE:
        return _refuse(code)
    if code not in gcal.OK_CODES:
        return msg_json(False, code, field=_FIELD.get(code, ""),
                        status=409 if code in _CONFLICT else 422)
    return await _reply(code, request, appt_id=appt_id)


@router.post("/api/gcal/events/{eid}/skip")
async def api_gcal_skip(request: Request, eid: int):
    """{on: true} — «Nu muta», {on: false} — «Readu în listă»."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    body = await api_body(request)
    if body is None or not isinstance(body.get("on"), bool):
        return msg_json(False, "gc_bad", status=422)
    code = await gcal.skip(eid, body["on"])
    return _refuse(code) if code in _GONE else await _reply(code, request)


@router.post("/api/gcal/events/{eid}/link")
async def api_gcal_link(request: Request, eid: int):
    """{appt_id} — событие уже стоит в журнале."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "gc_bad", status=422)
    code = await gcal.link(eid, body.get("appt_id"))
    return _refuse(code) if code in _GONE else await _reply(code, request)


@router.post("/api/gcal/source")
async def api_gcal_source(request: Request):
    """{service} — процедура, с которой открывается окно записи."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "gc_bad", status=422)
    code = await gcal.set_service(str(body.get("service") or ""))
    if code != "gc_set":
        return _refuse(code)
    return await _reply(code, request)


@router.post("/api/gcal/clear")
async def api_gcal_clear(request: Request):
    """«Șterge tot din Google» — только директор."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    code = await gcal.clear()
    return msg_json(True, code, data=await gcal.listing())
