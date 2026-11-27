"""Ответ пациента ссылкой → отметка визита в журнале (Premium, волна 2а).

Единственный писатель журнала из ответа пациента: цикл `core/plink_loop.py` зовёт
`apply` крючком (`plink_loop.attach` в `main.py`) — core журнал не импортирует.

«Vin» → отметка `ok`, «Nu pot veni» → `cant`, обе с каналом `sms`: в окне визита
«Confirmat · SMS» / «Nu poate veni · SMS». Программа сама ничего не отменяет и не
переносит: «Nu pot veni» — повод стойке позвонить, запись остаётся в журнале.
Строка отметки на визит одна — действует последняя перемена по времени: ответ,
нажатый раньше звонка регистратуры, звонок не перебивает.
"""
from __future__ import annotations

from datetime import datetime

from ... import db
from ... import engine as eng
from ...core import plink_loop
from ...core.auth import request_user, set_request_user

PATIENT = {"id": "pacient", "role": "", "name": "pacient", "doctor_id": ""}
VIA = "sms"
RESULT = {db.LINK_YES: "ok", db.LINK_NO: "cant"}
WORD = {db.LINK_YES: "confirmat", db.LINK_NO: "nu poate veni"}


async def apply(link: dict, state: str, at: datetime) -> bool:
    """Поставить отметку по ответу пациента. False — не ставилась: права нет, визит
    отменён, перенесён (код другого начала), закрыт или звонок новее ответа."""
    if not plink_loop.allowed():
        return False
    if state not in RESULT:
        return False
    prev = request_user()
    set_request_user(PATIENT)
    try:
        aid = int(link["appt_id"])
        a = await db.appointment_brief(aid)
        if (not a or a["status"] != "confirmed" or not a.get("patient_id")
                or plink_loop.starts_key(a["starts_at"]) != link["starts_key"]):
            return False
        cur = (await db.appt_calls([aid])).get(aid)
        if cur is not None and cur["at"] > at:
            return False
        await db.set_appt_call(aid, RESULT[state], via=VIA, actor=PATIENT["name"], at=at)
        when = a["starts_at"].astimezone(eng.TZ).strftime("%d.%m %H:%M")
        await db.log_event(a["patient_id"], "call", f"Confirmare prin SMS ({when}): {WORD[state]}",
                           actor=PATIENT["name"])
        return True
    finally:
        set_request_user(prev)
