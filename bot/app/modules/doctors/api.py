"""JSON API врачей (DentPilot 2.0): список, фиша, услуги, фото.

Правила живут в routes.py (`_add_doctor`, `_save_doctor`, `_set_services`,
`_store_photo`, `_delete_photo`, `_reset_colors`) — они одни на старую форму и
на API, здесь только разбор запроса и сборка ответа. Каталог врачей лежит в
clinic.json, поэтому «данные» здесь — чтение профиля плюс те же две выборки
записей, что у старых страниц: 30 дней для цифр, неделя для фиши.

Правило то же: `core`, `db`, `engine` — да, `main.py` — нет.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, File, Request, UploadFile

from ... import db
from ... import engine as eng
from ...core.api import api_body, api_require
from ...core.auth import PERM_DOCTORS
from ...core.layout import (HOUR_MAX, HOUR_MIN, STATUS_LABEL, _DOC_STATE_RO,
                            _doc_hours_text, _initials, msg_json)
from ...core.visits import (_doc_hue, all_status_actions,
                            photo_url as _photo_url)
from .routes import (MAX_PHOTO_MB, _DOC_STATE_HINT, _add_doctor, _delete_photo,
                     _doc_rows, _doc_stats, _orphan_warning, _read_upload,
                     _reset_colors, _same_color, _save_doctor, _service_rows,
                     _set_services, _store_photo, _week_cells)

router = APIRouter()

# HTTP-код по коду ответа: отказ проверки — 422; спор с состоянием клиники
# (тёзка, последний активный, будущие записи, услуга без врача) — 409;
# не записался файл — 500. Сами коды и тексты — те же, что у формы.
_HTTP = {"bad_med": 422, "bad_photo": 422, "dup_med": 409, "last_med": 409,
         "arch_busy": 409, "svc_empty": 409, "save_err": 500}
_OK = {"ok_med", "new_med", "ok_svc_med", "ok_photo"}


def _reply(code: str, data=None, field: str = ""):
    ok = code in _OK
    return msg_json(ok, code, data=data, field=field,
                    status=200 if ok else _HTTP.get(code, 422))


async def _month_rows() -> tuple[list, list]:
    """Записи за последние 30 дней и сами дни — для цифр карточек."""
    today = datetime.now(eng.TZ).date()
    d1 = today - timedelta(days=29)
    start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    end = datetime(today.year, today.month, today.day, tzinfo=eng.TZ) + timedelta(days=1)
    rows = await db.day_appointments(start, end)
    return rows, [d1 + timedelta(days=i) for i in range(30)]


def _summary(dk: str, name: str, rows: list, days: list) -> dict:
    meta = eng.DOCTOR_META.get(dk, {})
    st = meta.get("status", "activ")
    return {
        "id": dk, "name": name, "spec": eng.DOCTOR_SPEC.get(dk, "") or "",
        "status": st, "room": meta.get("room", "") or "",
        "phone": meta.get("phone", "") or "", "hours": _doc_hours_text(dk),
        "color": _doc_hue(dk), "initials": _initials(name),
        "photo": _photo_url(dk), "archived": st == "arhivat",
        "stats": _doc_stats(dk, name, rows, days),
    }


def _today_rows(rows: list) -> list[dict]:
    """Сегодняшний список врача — те же строки, что у старой таблицы дня."""
    return [{
        "id": r["id"],
        "time": r["starts_at"].astimezone(eng.TZ).strftime("%H:%M"),
        "patient": r["name"] or "", "patient_id": r.get("patient_id"),
        "phone": r["phone"] or "", "service": r["service"],
        "status": r["status"],
        "status_label": STATUS_LABEL.get(r["status"], r["status"]),
        "note": r["source"] == "note", "comment": r["comment"] or "",
    } for r in rows]


async def _card(dk: str) -> dict:
    name = eng.DOCTORS[dk]
    meta = eng.DOCTOR_META.get(dk, {})
    st = meta.get("status", "activ")
    today = datetime.now(eng.TZ).date()
    wk_start = datetime(today.year, today.month, today.day, tzinfo=eng.TZ)
    wk_rows = await db.day_appointments(wk_start, wk_start + timedelta(days=7))
    mine_wk = _doc_rows(dk, name, wk_rows)
    today_rows = [r for r in mine_wk
                  if r["starts_at"].astimezone(eng.TZ).date() == today]
    rows, days = await _month_rows()
    future = await db.doctor_future_count(dk, name, datetime.now(eng.TZ))
    tpl, orphan_names = _orphan_warning(dk, st)
    return {
        "id": dk, "name": name, "spec": eng.DOCTOR_SPEC.get(dk, "") or "",
        "room": meta.get("room", "") or "", "phone": meta.get("phone", "") or "",
        "email": meta.get("email", "") or "", "status": st,
        "color": _doc_hue(dk), "auto_color": not meta.get("color"),
        "work_from": meta.get("work_from"), "work_to": meta.get("work_to"),
        "hours": {"min": HOUR_MIN, "max": HOUR_MAX},
        "initials": _initials(name), "photo": _photo_url(dk),
        "max_photo_mb": MAX_PHOTO_MB,
        "future": future, "stats": _doc_stats(dk, name, rows, days),
        "warning": tpl.format(svc=", ".join(orphan_names)) if tpl else "",
        "week": _week_cells(dk, mine_wk, today),
        "today": _today_rows(today_rows),
        # ⭐ Кнопки исхода — ТА ЖЕ матрица, что у списка дня
        # (`core.visits.status_actions`), а не свой набор рядом. Своя копия
        # «какие кнопки у завершённого визита» разошлась бы с журналом молча:
        # закрытая запись теряла бы кнопку возврата в одном месте и сохраняла
        # в другом, а увидеть это можно, только открыв оба экрана.
        "actions": all_status_actions(),
        "note_actions": all_status_actions(is_note=True),
        "services": _service_rows(dk),
        "states": {k: {"label": v, "hint": _DOC_STATE_HINT[k]}
                   for k, v in _DOC_STATE_RO.items()},
    }


@router.get("/api/doctors")
async def api_doctors(request: Request):
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    rows, days = await _month_rows()
    return msg_json(True, data={
        "doctors": [_summary(dk, name, rows, days) for dk, name in eng.DOCTORS.items()],
        "same_color": _same_color(),
        "states": dict(_DOC_STATE_RO),
    })


@router.post("/api/doctors")
async def api_doctor_add(request: Request):
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return _reply("bad_med", field="name")
    code, did = _add_doctor(str(body.get("name") or ""), str(body.get("spec") or ""))
    if not did:
        return _reply(code, field="name" if code == "bad_med" else "")
    return _reply(code, data={"id": did})


@router.post("/api/doctors/colors")
async def api_doctor_colors(request: Request):
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    return _reply(_reset_colors())


@router.get("/api/doctors/{dk}")
async def api_doctor(request: Request, dk: str):
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return msg_json(False, status=404)
    return msg_json(True, data=await _card(dk))


def _s(body: dict, key: str) -> str:
    v = body.get(key)
    return "" if v is None else str(v)


@router.post("/api/doctors/{dk}")
async def api_doctor_save(request: Request, dk: str):
    """Та же `_save_doctor`, что у формы: часы уезжают строками («» — как у
    клиники), автоцвет — флагом. Удача возвращает свежую фишу целиком."""
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return msg_json(False, status=404)
    body = await api_body(request)
    if body is None:
        return _reply("bad_med")
    code = await _save_doctor(
        dk, name=_s(body, "name"), spec=_s(body, "spec"), room=_s(body, "room"),
        phone=_s(body, "phone"), email=_s(body, "email"), color=_s(body, "color"),
        auto_color=bool(body.get("auto_color")),
        work_from=_s(body, "work_from"), work_to=_s(body, "work_to"),
        status=_s(body, "status") or "activ")
    if code != "ok_med":
        return _reply(code, field="name" if code in ("bad_med", "dup_med") and not _s(body, "name").strip() else "")
    return _reply(code, data=await _card(dk))


@router.post("/api/doctors/{dk}/services")
async def api_doctor_services(request: Request, dk: str):
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return msg_json(False, status=404)
    body = await api_body(request)
    ids = body.get("services") if body else None
    if not isinstance(ids, list):
        return _reply("bad_med")
    code = _set_services(dk, {str(x) for x in ids})
    return _reply(code, data={"services": _service_rows(dk)} if code in _OK else None)


@router.post("/api/doctors/{dk}/photo")
async def api_doctor_photo(request: Request, dk: str, file: UploadFile = File(...)):
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return msg_json(False, status=404)
    buf = await _read_upload(file)
    code = "bad_photo" if buf is None else _store_photo(dk, buf)
    return _reply(code, data={"photo": _photo_url(dk)} if code in _OK else None)


@router.post("/api/doctors/{dk}/photo/delete")
async def api_doctor_photo_delete(request: Request, dk: str):
    if (deny := api_require(request, PERM_DOCTORS)) is not None:
        return deny
    if dk not in eng.DOCTORS:
        return msg_json(False, status=404)
    code = _delete_photo(dk)
    return _reply(code, data={"photo": _photo_url(dk)} if code in _OK else None)
