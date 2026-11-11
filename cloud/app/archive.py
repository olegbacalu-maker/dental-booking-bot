"""Архив клиник и удаление из архива (11.11.2026, Олег: «как мне удалить из списка клиники демо? … отправить в
архив, а оттуда что бы можно было удалить» → «Да, с умолчаниями»).

Архив — метка на строке клиники (шаг схемы 23): клиника уходит из списка, фильтров состояний, заявок, флота и
писем ежедневной задачи во вкладку «Архив»; «Вернуть из архива» снимает метку. ⭐ Архив — не отзыв: действующий
файл программы он не трогает (окно предлагает сначала «Отозвать», revoke.py). IDNO, ящик и компьютер архивной
клиники остаются заняты (`trial.existing`/`device_owner` смотрят только `declined_at`) — нового пробного на них нет.

«Удалить навсегда» — только из архива: причина, вписанное слово УДАЛИТЬ, одна транзакция. Стирается клиника и всё,
что на ней держится (`CLEARED`); IDNO, ящик и компьютер освобождаются; учётная запись кабинета остаётся (человек),
снимается только привязка. Строки журнала клиники остаются, к ним — строка `clinic_deleted` с именем и IDNO.
⛔ Удалить нельзя (`blockers`), пока на клинике держится то, что хранится: деньги (ноты и платежи любого статуса,
строки общей ноты, cont de plată, попытки оплаты картой), отправленные SMS и их списания (сверка с фактурой sms.md),
подписанные клиникой бумаги (экземпляры договора, заявление на имя SMS). Решение — по живой базе в транзакции
POST, не по странице. ⛔ Новая таблица со ссылкой на clinics(id) — строкой здесь (`CLEARED` или `BLOCKERS`):
иначе удаление упадёт на внешнем ключе (держит test_archive.suite_schema).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import db, license, revoke

CONFIRM_WORD = "УДАЛИТЬ"
REASON_MAX = 300

ARCHIVED, UNARCHIVED, DELETED = "archived", "unarchived", "deleted"
ALREADY, NOT_ARCHIVED, NEED_REASON, NEED_WORD, BLOCKED = (
    "archive_already", "archive_not", "delete_reason", "delete_word", "delete_blocked")

# (таблица, что это словами, условие на клинику `?`) — пока хоть одна строка есть, удалить нельзя
BLOCKERS = (
    ("payments", "ноты и платежи", "clinic_id=?"),
    ("payment_lines", "строки общей ноты", "clinic_id=?"),
    ("receipts", "cont de plată", "clinic_id=?"),
    ("pay_attempts", "попытки оплаты картой",
     "payment_id IN (SELECT id FROM payments WHERE clinic_id=?1 UNION SELECT payment_id FROM payment_lines "
     "WHERE clinic_id=?1)"),
    ("sms_messages", "отправленные SMS", "clinic_id=?"),
    ("sms_ledger", "списания и пакеты SMS",
     "clinic_id=? AND (reason IN ('send', 'pack', 'refund') OR message_id IS NOT NULL OR payment_id IS NOT NULL)"),
    ("clinic_contracts", "подписанные клиникой документы", "clinic_id=?"),
    ("sms_papers", "подписанные заявления на имя SMS", "clinic_id=?"),
)
# стирается при удалении — дети раньше родителя (foreign_keys=ON)
CLEARED = ("pay_links", "cont_links", "email_confirms", "activation_codes", "cabinet_codes", "devices",
           "account_clinics", "sms_ledger", "sms_accounts", "terms_acceptances", "issues", "subscriptions")
# ссылки на клинику без удаления строки: учётная запись кабинета — человек, у неё снимается открытая клиника
DETACHED = ("accounts",)


def is_archived(row: sqlite3.Row | None) -> bool:
    return row is not None and "archived_at" in row.keys() and bool(row["archived_at"])


def _clean(reason: str) -> str:
    return " ".join((reason or "").split())[:REASON_MAX]


def blockers(con: sqlite3.Connection, clinic_id: str) -> list[tuple[str, int]]:
    """Что не даёт удалить клинику: [(словами, сколько)] — только ненулевые. Пусто — удалить можно."""
    out = []
    for table, label, where in BLOCKERS:
        n = con.execute(f"SELECT count(*) FROM {table} WHERE {where}", (clinic_id,)).fetchone()[0]
        if n:
            out.append((label, n))
    return out


def live_until(con: sqlite3.Connection, clinic: sqlite3.Row, now: datetime | None = None) -> str:
    """До какой даты программа клиники ещё работает (срок или льгота), если лицензия не отозвана; '' — нет."""
    if revoke.is_revoked(clinic):
        return ""
    sub = con.execute("SELECT valid_until, grace_days FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    if sub is None or not sub["valid_until"]:
        return ""
    vu = db.parse_ts(sub["valid_until"])
    st = license.state(vu, sub["grace_days"] or 0, now or datetime.now(timezone.utc))
    if st not in ("active", "grace"):
        return ""
    row = con.execute("SELECT grace_until FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1",
                      (clinic["id"],)).fetchone()
    return (row["grace_until"] if row is not None else sub["valid_until"])[:10]


def archive(con: sqlite3.Connection, clinic: sqlite3.Row, reason: str, who: str) -> str:
    if is_archived(clinic):
        return ALREADY
    reason = _clean(reason)
    con.execute("UPDATE clinics SET archived_at=?, archived_by=?, archived_reason=? WHERE id=?",
                (db.now_iso(), who, reason, clinic["id"]))
    live = live_until(con, clinic)
    db.audit(con, who, "archive", clinic["id"],
             (reason or "без причины") + (f"; лицензия действует до {live} — архив её не отзывает" if live else ""))
    return ARCHIVED


def unarchive(con: sqlite3.Connection, clinic: sqlite3.Row, who: str) -> str:
    if not is_archived(clinic):
        return NOT_ARCHIVED
    con.execute("UPDATE clinics SET archived_at=NULL, archived_by='', archived_reason='' WHERE id=?", (clinic["id"],))
    db.audit(con, who, "unarchive", clinic["id"], "")
    return UNARCHIVED


def delete(con: sqlite3.Connection, clinic: sqlite3.Row, reason: str, word: str, who: str) -> str:
    """Удалить навсегда — в транзакции вызывающего (immediate): проверки по живой базе, потом строки детей и клиника."""
    cid = clinic["id"]
    if not is_archived(clinic):
        return NOT_ARCHIVED
    reason = _clean(reason)
    if not reason:
        return NEED_REASON
    if (word or "").strip().upper() != CONFIRM_WORD:
        return NEED_WORD
    stop = blockers(con, cid)
    if stop:
        db.audit(con, who, "delete_refused", cid, "; ".join(f"{label}: {n}" for label, n in stop))
        return BLOCKED
    live = live_until(con, clinic)
    con.execute("DELETE FROM reminders WHERE subscription_id=?", (cid,))
    for table in CLEARED:
        con.execute(f"DELETE FROM {table} WHERE clinic_id=?", (cid,))
    # открытая клиника учётной записи — другая её клиника, если есть, иначе никакой (вход начнётся с регистрации)
    con.execute("UPDATE accounts SET clinic_id=(SELECT ac.clinic_id FROM account_clinics ac "
                "WHERE ac.account_id=accounts.id ORDER BY ac.added_at LIMIT 1) WHERE clinic_id=?", (cid,))
    con.execute("DELETE FROM clinics WHERE id=?", (cid,))
    db.audit(con, who, "clinic_deleted", cid,
             f"«{clinic['name']}», IDNO {clinic['idno'] or '—'}, заведена {clinic['created_at'][:10]}: {reason}"
             + (f"; программа доработает по своему файлу до {live}" if live else ""))
    return DELETED
