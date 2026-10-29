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
from ...core import recall, sms_loop
from ...core.api import api_body, api_require
from ...core.auth import PERM_RECALL, PERM_SETTINGS, can, request_user
from ...core.layout import msg_json

# отказы ДО сервера лицензий — свои коды MSG_BANNER (`sms_loop.RECALL_*`);
# код сервера едет его же словами (`WHY`), как у экрана Setări › SMS
_OWN = frozenset({sms_loop.RECALL_OFF, sms_loop.RECALL_NO_PHONE, sms_loop.RECALL_BAD_PHONE,
                  sms_loop.RECALL_QUIET, sms_loop.RECALL_DUP})
_WIRE = {sms_loop.wire.OFFLINE: "sms_offline", sms_loop.wire.REFUSED: "sms_token"}

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
    # статистика одной строкой (В4 → Б, Олег 29.10): то же право, что у списка
    d["stats"] = await recall.stats(_today())
    # кнопка «SMS» (30.10): текст и сегменты — сервера (шаблоны клиент не знает);
    # блок только у экрана — тихие часы зависят от часа, конверт главной — нет
    d["sms"] = recall.sms_head()
    if d["sms"]:
        for r in d["rows"]:
            if r.get("sms"):
                text, segs = sms_loop.recall_preview(r["lang"])
                r["sms"].update(text=text, segments=segs)
    return msg_json(True, data=d)


def _pair_args(b: dict) -> tuple[int, str]:
    try:
        pid = int(b.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return pid, str(b.get("service_id") or "")


@router.post("/api/recall/sms")
async def api_recall_sms(request: Request):
    """SMS пациенту из строки списка: {pid, service_id} (30.10, В1 = А).

    Текст, ключ и отправку делает `sms_loop.send_recall` (синхронно, мимо
    очереди, с записью в `sms_log`); здесь — право, пара, отказ пациента и
    отметка `sms` после ответа сервера. При отказе — ничего не пишется.
    """
    if (deny := api_require(request, PERM_RECALL)) is not None:
        return deny
    b = await api_body(request) or {}
    pid, sid = _pair_args(b)
    if pid <= 0 or not sid:
        return msg_json(False, "bad_recall", status=422)
    row = await recall.pair(pid, sid)
    if row is None:
        return msg_json(False, "recall_gone", status=409)
    if row.get("sms_off"):
        return msg_json(False, "recall_sms_refused", status=409)
    label = eng.SERVICES.get(sid, {}).get("ro") or sid
    outcome, body = await sms_loop.send_recall(pid, sid, int(row["aid"]), row.get("phone") or "",
                                               row.get("lang") or "ro", label)
    if outcome == sms_loop.wire.OK:
        await db.add_recall_mark(pid, sid, int(row["aid"]), "sms")
        return msg_json(True, "ok_recall_sms", data={"state": body.get("state"),
                                                     "balance": body.get("balance")})
    if outcome == sms_loop.wire.DENIED:
        code = str(body.get("code") or "sms_refused")
        if code in _OWN:
            return msg_json(False, code, status=409)
        return msg_json(False, "sms_denied", status=409,
                        text=sms_loop.WHY.get(code) or body.get("text") or code)
    return msg_json(False, _WIRE.get(outcome, "sms_offline"), status=503)


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
    pid, sid = _pair_args(b)
    result = str(b.get("result") or "")
    # `sms` руками не ставится — только `/api/recall/sms` после ответа сервера
    if pid <= 0 or not sid or result not in recall.MANUAL:
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
