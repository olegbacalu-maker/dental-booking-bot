"""Платёж переводом (L8): reference, ожидание, подтверждение, отказ, продление.

cloud.md › «Оплата › Шаг 1 — transfer bancar». Reference уникален (год +
порядковый номер), печатается в письме и в админке, клиника пишет его в
назначении платежа. Подтверждение идемпотентно: второе подтверждение того же
платежа — отказ, а не второе продление. Каждое действие — строка в audit.

⭐ Правило продления: N месяцев от БОЛЬШЕЙ из дат — сегодня или конца
действующего срока. Ранняя оплата не крадёт дни, поздняя не дарит. Каждое
продление = новая выдача файла (seq+1): файл и есть истина о сроке.
"""
from __future__ import annotations

import calendar
import sqlite3
from datetime import datetime, timedelta, timezone

from . import db, license

PENDING, PAID, REJECTED = "pending", "paid", "rejected"
TRANSFER = "transfer"
MONTHS = (1, 3, 6, 12)


def add_months(dt: datetime, n: int) -> datetime:
    """Календарные месяцы: 31.01 + 1 = 28/29.02, время суток сохраняется."""
    month0 = dt.month - 1 + n
    year, month = dt.year + month0 // 12, month0 % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def extend_from(valid_until: datetime | None, months: int, now: datetime) -> datetime:
    base = now if valid_until is None or valid_until < now else valid_until
    return add_months(base, months)


def next_reference(con: sqlite3.Connection, now: datetime) -> str:
    year = now.year
    row = con.execute("SELECT reference FROM payments WHERE reference LIKE ? ORDER BY reference DESC LIMIT 1",
                      (f"DP-{year}-%",)).fetchone()
    last = int(row[0].rsplit("-", 1)[1]) if row else 0
    return f"DP-{year}-{last + 1:06d}"


def create(con: sqlite3.Connection, clinic: sqlite3.Row, months: int, amount: int, who: str) -> sqlite3.Row:
    if months not in MONTHS:
        raise ValueError("months")
    if amount <= 0:
        raise ValueError("amount")
    now = datetime.now(timezone.utc)
    ref = next_reference(con, now)
    con.execute("""INSERT INTO payments(clinic_id, amount, currency, method, status, reference, months, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (clinic["id"], amount, "MDL", TRANSFER, PENDING, ref, months, db.now_iso()))
    db.audit(con, who, "payment_new", clinic["id"], f"{ref}: {amount} MDL за {months} мес., перевод")
    return con.execute("SELECT * FROM payments WHERE reference=?", (ref,)).fetchone()


def confirm(con: sqlite3.Connection, payment: sqlite3.Row, who: str) -> tuple[int, str]:
    """Подтвердить поступление: продлить и выдать файл. Возвращает (seq, текст файла).
    ⛔ Не в ожидании — ValueError('not_pending'): продление не повторяется."""
    if payment["status"] != PENDING:
        raise ValueError("not_pending")
    clinic = con.execute("SELECT * FROM clinics WHERE id=?", (payment["clinic_id"],)).fetchone()
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    current = db.parse_ts(sub["valid_until"]) if sub else None
    valid = extend_from(current, int(payment["months"]), now)
    grace = valid + timedelta(days=license.GRACE_DAYS)
    con.execute("UPDATE payments SET status=?, paid_at=?, confirmed_by=? WHERE id=? AND status=?",
                (PAID, db.now_iso(), who, payment["id"], PENDING))
    db.audit(con, who, "payment_paid", clinic["id"],
             f"{payment['reference']}: {payment['amount']} MDL, срок до {valid.strftime(db.TS)}")
    return license.issue(con, clinic, "standard", valid, grace,
                         f"платёж {payment['reference']}", who)


def reject(con: sqlite3.Connection, payment: sqlite3.Row, reason: str, who: str) -> None:
    if payment["status"] != PENDING:
        raise ValueError("not_pending")
    con.execute("UPDATE payments SET status=?, confirmed_by=? WHERE id=? AND status=?",
                (REJECTED, who, payment["id"], PENDING))
    db.audit(con, who, "payment_rejected", payment["clinic_id"],
             f"{payment['reference']}: {reason or 'без причины'}")
