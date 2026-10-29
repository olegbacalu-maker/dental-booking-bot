"""JSON API «Rechemări» (29.10.2026): список и отметка.

Контракт — `docs/dentpilot-2/recall-api.md`. Правила те же, что у соседних
`api.py`: `core`, `db`, `engine` — да, `main.py` — нет; считает только
`core/recall.py`. Экран не живой поверхности (как Statistici): свой GET,
команда отметки состояния не возвращает — экран перечитывает список, главная
получает отметку конвертом живого канала.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Request

from ... import db
from ... import engine as eng
from ...core import recall
from ...core.api import api_body, api_require
from ...core.auth import PERM_RECALL, PERM_SETTINGS, can, request_user
from ...core.layout import msg_json

router = APIRouter()


def _today() -> date:
    return datetime.now(eng.TZ).date()


@router.get("/api/recall")
async def api_recall(request: Request):
    """Весь экран одним конвертом: услуги со сроком, строки, счётчики вкладок,
    имя и телефон клиники (для текста письма)."""
    if (deny := api_require(request, PERM_RECALL)) is not None:
        return deny
    d = await recall.model(_today())
    d["clinic"] = {"name": eng.CLINIC_NAME, "phone": eng.CLINIC_PHONE}
    # пустой экран ведёт в Setări › Servicii только того, кому они открыты;
    # право решает сервер, клиент его не вычисляет
    d["can_settings"] = can(request_user(), PERM_SETTINGS)
    return msg_json(True, data=d)


@router.post("/api/recall/mark")
async def api_recall_mark(request: Request):
    """Отметка пары (пациент, услуга): {pid, service_id, result, until?}.

    ⚠️ Отметка привязывается к ТЕКУЩЕМУ последнему done-визиту пары (цикл):
    без него отмечать нечего — 409 `recall_gone` (вкладка смотрела на
    устаревший список: визит удалили или сменили процедуру). `later` без
    годной даты — 422. Летопись получает ГОТОВУЮ строку.
    """
    if (deny := api_require(request, PERM_RECALL)) is not None:
        return deny
    b = await api_body(request) or {}
    try:
        pid = int(b.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    sid = str(b.get("service_id") or "")
    result = str(b.get("result") or "")
    if pid <= 0 or not sid or result not in recall.RESULTS:
        return msg_json(False, "bad_recall", status=422)
    until = ""
    if result == "later":
        try:
            until = date.fromisoformat(str(b.get("until") or "")[:10]).isoformat()
        except ValueError:
            return msg_json(False, "bad_recall", status=422, field="until")
    cycle = await recall.cycle_of(pid, sid)
    if cycle is None:
        return msg_json(False, "recall_gone", status=409)
    await db.add_recall_mark(pid, sid, cycle, result, until)
    label = eng.SERVICES.get(sid, {}).get("ro") or sid
    text = f"Rechemare {label}: {recall.WORD[result]}"
    if until:
        text += " până la " + date.fromisoformat(until).strftime("%d.%m.%Y")
    await db.log_event(pid, "recall", text)
    return msg_json(True, "ok_recall")
