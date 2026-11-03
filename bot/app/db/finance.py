"""Платежи пациента и выборки денег по дням."""
from __future__ import annotations

from datetime import datetime

from .conn import _execute, _fetch, _fetchval, _iso, _utcnow_iso
from .events import _actor_now, log_event


async def payments_day(start: datetime, end: datetime) -> list:
    """Платежи за окно, с именем пациента — для печатного отчёта кассы.

    ⚠️ `at` возвращается в UTC, как все даты (`_DT_COLS`). Печать читает
    человек, поэтому переводить в `eng.TZ` обязан вызывающий: иначе платёж,
    принятый в 09:00, встанет в отчёт как 06:00 — дата верна, час чужой.
    """
    sql = ("SELECT pm.amount_mdl, pm.method, pm.at, pm.note, pm.taken_by, "
           "       pm.patient_id, p.name AS patient "
           "FROM payments pm LEFT JOIN patients p ON p.id = pm.patient_id "
           "WHERE pm.at >= {0} AND pm.at < {1} ORDER BY pm.at")
    return await _fetch(
        sql.format("?", "?"),
        _iso(start), _iso(end),
    )


# ---------- право на стирание (закон 195) ----------
# Веток ДВЕ, и это не перестраховка. Право пациента на стирание не отменяет
# обязанность клиники хранить медицинскую документацию, поэтому:
#   * контакт БЕЗ лечения (записался и не пришёл, отменил) — удаляется физически;
#   * пациент С лечением — ОБЕЗЛИЧИВАЕТСЯ: личность стирается, клиническая
#     часть остаётся под номером фиши.
# ⚠️ Состав таблиц здесь обязан совпадать с modules/patients/export.py: обе
# стороны отвечают на вопрос «где в базе лежит этот человек». Разойдутся —
# получится либо неполная выдача, либо неполное удаление, и заметить неоткуда.

# ---------- платежи (08-07, модуль финансов, шаг 1) ----------
# Модель по решению Олега: долг = завершённые позиции плана с ценой минус
# платежи; платёж — сумма НА ПАЦИЕНТА, без привязки к конкретной процедуре
# (наличные так не делятся). Переплата = аванс. Записывает рецепция (деньги
# физически берёт она), удаляет только директор, всё поимённо в летописи.

PAY_METHODS = ("numerar", "card", "transfer")


async def payments(pid: int) -> list:
    return await _fetch(
        """SELECT id, amount_mdl, method, note, taken_by, at
           FROM payments WHERE patient_id = ? ORDER BY at DESC, id DESC""", pid)


async def add_payment(pid: int, amount: int, method: str, note: str) -> None:
    actor = _actor_now()
    await _execute(
        """INSERT INTO payments(patient_id, amount_mdl, method, note, taken_by, at)
           VALUES(?, ?, ?, ?, ?, ?)""",
        pid, amount, method, note, actor, _utcnow_iso(),
    )
    verb = "Plată" if amount > 0 else "Restituire"
    await log_event(pid, "pay", f"{verb} {abs(amount)} MDL ({method})"
                    + (f" — {note}" if note else ""))


async def get_payment(pay_id: int, pid: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, amount_mdl, method, note FROM payments
           WHERE id = ? AND patient_id = ?""", pay_id, pid)
    return rows[0] if rows else None


async def delete_payment(pay_id: int, pid: int) -> bool:
    """Удаление платежа — исправление ошибки ввода, не бухгалтерская операция.
    Право на него только у директора (маршрут), а след остаётся в летописи —
    ПОСЛЕ DELETE и только за реально снятую строку (как у `delete_bridge`)."""
    p = await get_payment(pay_id, pid)
    if p is None:
        return False
    n = await _execute("DELETE FROM payments WHERE id = ? AND patient_id = ?",
                       pay_id, pid)
    if n != 1:
        return False
    await log_event(pid, "pay_del",
                    f"Plată ștearsă: {p['amount_mdl']} MDL ({p['method']})")
    return True


async def patient_finance(pid: int) -> dict:
    """Начислено (завершённые позиции плана с ценой) и оплачено. Долг считает
    вызывающий: charged − paid; минус = аванс."""
    charged = await _fetchval(
        """SELECT COALESCE(SUM(price_mdl), 0) FROM plan_items
           WHERE patient_id = ? AND status = 'finalizat'""", pid)
    paid = await _fetchval(
        "SELECT COALESCE(SUM(amount_mdl), 0) FROM payments WHERE patient_id = ?",
        pid)
    return {"charged": int(charged or 0), "paid": int(paid or 0)}


async def payments_range(start: datetime, end: datetime) -> list:
    """Платежи за окно времени — для «Încasări» в статистике."""
    return await _fetch(
        """SELECT amount_mdl, method, at FROM payments
           WHERE at >= ? AND at < ?""",
        _iso(start), _iso(end),
    )
