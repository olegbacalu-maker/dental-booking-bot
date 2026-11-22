"""Вкладка «Google Calendar»: JSON API; правила — в `gcal.py`, связь с аккаунтом — в `gcal_link.py`.
Врачу вкладка закрыта."""
from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse

from ...core import demo, ics
from ...core import license as lic
from ...core import license_state as lst
from ...core.api import api_body, api_require
from ...core.auth import PERM_SCHEDULE_ALL, PERM_SETTINGS, client_is_local, local_only, require
from ...core.layout import msg_json, react_shell, shell_model
from . import gcal, gcal_auto, gcal_link
from .api import _CONFLICT, _FIELD

router = APIRouter()

_GONE = {"gc_gone", "gc_moved", "gc_appt", "gc_patient", "gc_no_text", "gc_a_stale", "gc_a_undo_gone",
         "gc_a_nochange", "gc_a_touched"}
# отказ команды связи до её работы: состояние, а не ошибка ввода
_LINK_REFUSED = {"gc_g_none", "gc_g_plus", "gc_g_readonly", "gc_g_gone"}


async def _list(request: Request) -> dict:
    at = request.query_params
    data = await gcal.listing(at.get("f", ""), at.get("q", ""), at.get("date", ""), at.get("month", ""))
    data["google"] = gcal_link.view(request)
    await gcal_auto.annotate(data, link_auto=(data["google"] or {}).get("auto"))
    data["automove"]["batch"]["can"] = _batch_can(request)
    return data


def _batch_can(request: Request) -> bool:
    """Пачка — с ПК программы (как импорт Excel), не в демо и не в режиме чтения."""
    s = lic.current()
    return (client_is_local(request) and not demo.on()
            and (s is None or s.state in (lst.ACTIVE, lst.GRACE)))


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
    """multipart `file`; на диск не кладётся: в файле имена и телефоны."""
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
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    code, held = await gcal_link.clear_paused(gcal.clear)
    return await _reply("gc_cleared_paused" if held else code, request)


# ---------- связь с аккаунтом Google (gcal_link.py) ----------

@router.post("/api/gcal/google/connect")
async def api_gcal_google_connect(request: Request):
    """Адрес экрана Google в `data.url`; открывает его браузер Windows (оболочка), не окно программы."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    code, url = await gcal_link.start(request)
    if code != "gc_g_url":
        return msg_json(False, code, status=409)
    return await _reply(code, request, url=url)


@router.post("/api/gcal/google/cancel")
async def api_gcal_google_cancel(request: Request):
    """«Renunță» у ожидания браузера: начатый вход умирает, `waiting` гаснет."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    return await _reply(gcal_link.cancel(), request)


@router.get("/google/back", response_class=HTMLResponse)
async def google_back(request: Request):
    """Возврат из браузера Windows: вне /admin и /api, куки программы там нет — все проверки
    в `gcal_link.finish`. Адрес совпадает с `gcal_link.BACK_PATH`."""
    code, status = await gcal_link.finish(request)
    return HTMLResponse(gcal_link.back_page(code), status_code=status,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/api/gcal/google/calendar")
async def api_gcal_google_calendar(request: Request):
    """{id} — календарь из `google.calendars`; сразу первая проверка."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None or not isinstance(body.get("id"), str):
        return msg_json(False, "gc_g_bad", status=422)
    code, count = await gcal_link.choose(body["id"])
    if code == "gc_g_bad":
        return msg_json(False, code, status=422)
    if code in _LINK_REFUSED:
        return msg_json(False, code, status=409)
    return await _reply(code, request, load=count)


@router.post("/api/gcal/google/check")
async def api_gcal_google_check(request: Request):
    """«Verifică acum»: код ответа — исход проверки, тон — из словаря."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    code, count = await gcal_link.check()
    if code in _LINK_REFUSED:
        return msg_json(False, code, status=409)
    return await _reply(code, request, load=count)


@router.post("/api/gcal/google/disconnect")
async def api_gcal_google_disconnect(request: Request):
    """«Deconectează»: открыта и в режиме чтения (`READONLY_ALLOW`), гейт её не касается."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    code = await gcal_link.disconnect()
    if code == "gc_g_gone":
        return msg_json(False, code, status=409)
    return await _reply(code, request)


# ---------- перенос пачкой и автоматом (gcal_auto.py) ----------

def _demo_deny():
    """Пачка и отмена в демо закрыты, как импорт Excel."""
    return msg_json(False, "demo_off", status=403) if demo.on() else None


@router.post("/api/gcal/batch/check")
async def api_gcal_batch_check(request: Request):
    """{auto} — что перенесётся из показанного списка «De mutat» (`q`, `date` адреса). Не переносит."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    if (deny := _demo_deny()) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "gc_bad", status=422)
    at = request.query_params
    preview = await gcal_auto.preview(at.get("q", ""), at.get("date", ""), body.get("auto") is True)
    return msg_json(True, data={"preview": preview})


@router.post("/api/gcal/batch/run")
async def api_gcal_batch_run(request: Request):
    """{token, auto} — перенос того, что показал предпросмотр; `auto` — и включить автоперенос."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    if (deny := _demo_deny()) is not None:
        return deny
    body = await api_body(request)
    if body is None or not isinstance(body.get("token"), str):
        return msg_json(False, "gc_bad", status=422)
    auto = body.get("auto") is True
    if auto:
        link = gcal_link.view(request)
        if not link or not (link.get("auto") or {}).get("can_on"):
            return msg_json(False, "gc_a_auto_no", status=409)
    at = request.query_params
    code, got = await gcal_auto.run(at.get("q", ""), at.get("date", ""), body["token"], auto)
    if code in _GONE:
        return _refuse(code)
    if auto:
        # пачка уже легла: ответ несёт свежий список, а слово — что вышло с галочкой
        code = await gcal_link.set_auto(True)
    return await _reply(code, request, batch=got)


@router.post("/api/gcal/moves/undo")
async def api_gcal_moves_undo(request: Request):
    """{key} — отменить мутацию: снять её нетронутые записи и пустые новые фиши."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    if (deny := _demo_deny()) is not None:
        return deny
    body = await api_body(request)
    if body is None or not isinstance(body.get("key"), str):
        return msg_json(False, "gc_bad", status=422)
    code, got = await gcal_auto.undo(body["key"])
    return _refuse(code) if code in _GONE else await _reply(code, request, undo=got)


@router.post("/api/gcal/auto")
async def api_gcal_auto(request: Request):
    """{on: false} — выключить автоперенос; включают предпросмотром (`/api/gcal/batch/run`, `auto`).
    Открыт и в режиме чтения (`READONLY_ALLOW`)."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None or body.get("on") is not False:
        return msg_json(False, "gc_bad", status=422)
    code = await gcal_link.set_auto(False)
    return msg_json(False, code, status=409) if code == "gc_g_gone" else await _reply(code, request)


@router.post("/api/gcal/sms")
async def api_gcal_sms(request: Request):
    """{on} — SMS-напоминания записям, перенесённым пачкой и автоматом; перенос по одному — как всегда."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    if (deny := local_only(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None or not isinstance(body.get("on"), bool):
        return msg_json(False, "gc_bad", status=422)
    return await _reply(await gcal_auto.set_sms(body["on"]), request)


async def _changed(request: Request, eid: int, act) -> object:
    code = await act(eid)
    if code in _GONE:
        return _refuse(code)
    if code not in ("gc_a_kept", "gc_a_followed", "gc_a_cancelled", "room_busy"):
        return msg_json(False, code, status=409)
    return await _reply(code, request)


@router.post("/api/gcal/events/{eid}/follow")
async def api_gcal_follow(request: Request, eid: int):
    """«Mută și programarea»: запись идёт за часом из Google правилом перетаскивания."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    return await _changed(request, eid, gcal_auto.follow)


@router.post("/api/gcal/events/{eid}/cancel-appt")
async def api_gcal_cancel_appt(request: Request, eid: int):
    """«Anulează programarea»: событие отменили или удалили в Google."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    return await _changed(request, eid, gcal_auto.cancel_appt)


@router.post("/api/gcal/events/{eid}/keep")
async def api_gcal_keep(request: Request, eid: int):
    """«Lasă cum e»: изменение в Google принято, запись не трогается."""
    if (deny := api_require(request, PERM_SCHEDULE_ALL)) is not None:
        return deny
    return await _changed(request, eid, gcal_auto.keep)
