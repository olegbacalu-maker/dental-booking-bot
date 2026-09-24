"""База сервера: SQLite в режиме WAL, шаги миграций тем же приёмом, что db.py движка.

Соединение на запрос, а не одно на процесс: обработчики FastAPI синхронные и
идут в пуле потоков, а sqlite3 не любит чужих потоков. Для десятков клиник
этого больше чем достаточно; PostgreSQL — когда придёт шаг 3 (cloud.md).

⚠️ Новый шаг в MIGRATIONS без поднятия SCHEMA_VERSION — мёртвый код: цикл
идёт range(have+1, SCHEMA_VERSION+1) и до него не дойдёт.
"""
from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA_VERSION = 1
TS = "%Y-%m-%dT%H:%M:%SZ"

MIGRATIONS = {
    1: [
        """CREATE TABLE IF NOT EXISTS clinics(
               id TEXT PRIMARY KEY, name TEXT NOT NULL, idno TEXT NOT NULL DEFAULT '',
               contact_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
               phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
               country TEXT NOT NULL DEFAULT 'MD', created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS subscriptions(
               clinic_id TEXT PRIMARY KEY REFERENCES clinics(id),
               plan TEXT NOT NULL DEFAULT 'trial', price INTEGER NOT NULL DEFAULT 399,
               currency TEXT NOT NULL DEFAULT 'MDL', valid_until TEXT,
               grace_days INTEGER NOT NULL DEFAULT 14, cancelled_at TEXT,
               updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS issues(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               clinic_id TEXT NOT NULL REFERENCES clinics(id), seq INTEGER NOT NULL,
               kid TEXT NOT NULL, payload TEXT NOT NULL, sig TEXT NOT NULL,
               issued_at TEXT NOT NULL, valid_until TEXT NOT NULL, grace_until TEXT NOT NULL,
               reason TEXT NOT NULL DEFAULT '', UNIQUE(clinic_id, seq))""",
        """CREATE TABLE IF NOT EXISTS payments(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               clinic_id TEXT NOT NULL REFERENCES clinics(id),
               amount INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'MDL',
               method TEXT NOT NULL, status TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
               months INTEGER NOT NULL DEFAULT 1, provider_id TEXT UNIQUE,
               created_at TEXT NOT NULL, paid_at TEXT, confirmed_by TEXT)""",
        """CREATE TABLE IF NOT EXISTS reminders(
               subscription_id TEXT NOT NULL, kind TEXT NOT NULL, period TEXT NOT NULL,
               sent_at TEXT NOT NULL, PRIMARY KEY(subscription_id, kind, period))""",
        """CREATE TABLE IF NOT EXISTS audit(
               id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, who TEXT NOT NULL,
               what TEXT NOT NULL, clinic_id TEXT, detail TEXT NOT NULL DEFAULT '')""",
    ],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(TS)


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, TS).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@contextlib.contextmanager
def connect():
    con = sqlite3.connect(config.DB_PATH, isolation_level=None, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        con.execute("BEGIN")
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def init() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = con.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        have = int(row[0]) if row else 0
        for step in range(have + 1, SCHEMA_VERSION + 1):
            con.execute("BEGIN")
            for sql in MIGRATIONS[step]:
                con.execute(sql)
            con.execute("INSERT INTO schema_meta(key, value) VALUES('version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(step),))
            con.execute("COMMIT")
    finally:
        con.close()


def audit(con: sqlite3.Connection, who: str, what: str, clinic_id: str | None = None,
          detail: str = "") -> None:
    con.execute("INSERT INTO audit(at, who, what, clinic_id, detail) VALUES(?,?,?,?,?)",
                (now_iso(), who, what, clinic_id, detail[:500]))
