"""Соединение картотеки: выборки, даты, schema_meta как словарь.

Соединение одно (`db._CONN`, ставит `schema.init`), запросы идут через
`_fetch`/`_fetchval`/`_execute`. Даты в базе — ISO-строки в UTC; в объекты их
превращает `_rowdict` по СПИСКУ имён `_DT_COLS`."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from .. import db


DATABASE_URL = os.environ.get("DATABASE_URL", "")

log = logging.getLogger("db")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _utcnow_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


# колонки-даты: в SQLite это ISO-строки, наверх обязаны уходить datetime.
# Забыть здесь новую колонку = дата молча исчезнет из интерфейса (так и
# случилось с activity.at на первом прогоне).
# last_at/next_at — вычисляемые псевдонимы (MAX/MIN по starts_at) из
# patients_visits: у выражения нет типа колонки, и SQLite отдаёт его строкой.
_DT_COLS = {"starts_at", "created_at", "uploaded_at", "updated_at", "at",
            "last_at", "next_at", "done_at", "waiting_at", "arrived_at",
            "state_at", "until_at", "visit_at", "removed_at"}


def _rowdict(row) -> dict:
    d = dict(row)
    for k in _DT_COLS & d.keys():
        if d[k] is not None:
            d[k] = _parse_dt(d[k])
    return d


# ---------- низкоуровневые помощники ----------

async def _fetch(sql: str, *args) -> list[dict]:
    cur = await db._CONN.execute(sql, args)
    rows = await cur.fetchall()
    await cur.close()
    return [_rowdict(r) for r in rows]


async def _fetchval(sql: str, *args):
    cur = await db._CONN.execute(sql, args)
    row = await cur.fetchone()
    await cur.close()
    await db._CONN.commit()
    return row[0] if row else None


async def _execute(sql: str, *args) -> int:
    cur = await db._CONN.execute(sql, args)
    await db._CONN.commit()
    n = cur.rowcount
    await cur.close()
    return n


# Служебные пары ключ-значение ЖИВУТ В schema_meta намеренно: таблица есть у
# каждой клиники с первой версии, значит новой миграции не нужно. Ключи не
# пересекаются с 'version' — он занят номером схемы.

async def get_meta(key: str) -> str | None:
    try:
        return await _fetchval(
            "SELECT value FROM schema_meta WHERE key = ?", key)
    except Exception as e:  # noqa: BLE001 — служебное значение не роняет старт
        log.warning("get_meta(%s) failed: %r", key, e)
        return None


async def set_meta(key: str, value: str) -> None:
    await _execute(
        """INSERT INTO schema_meta(key, value) VALUES(?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        key, value,
    )


async def del_meta(key: str) -> None:
    await _execute("DELETE FROM schema_meta WHERE key = ?", key)
