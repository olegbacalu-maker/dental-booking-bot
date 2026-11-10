"""«Registre» (10.11.2026): санитарные регистры — каталог оборудования и три журнала.

Только выборки и запись; правила (кто, когда, что можно закрыть, ресурс
лампы) — `core/registre.py`. Таблицы — `schema.SAN_DDL` (шаг 9).
⛔ Журналы только дописываются: здесь нет UPDATE строки журнала, кроме
`san_close` — однократного заполнения ПУСТОГО поля (условие `IS NULL` /
`= ''` стоит в самом SQL, поэтому повтор — ноль строк, а не перезапись), и
мягкого удаления `san_delete`. Имена таблиц и колонок — только из белых
списков ниже: в SQL они вставляются текстом."""
from __future__ import annotations

import json

from .. import db
from .conn import _execute, _fetch, _fetchval, _utcnow_iso

# ключ регистра → таблица журнала (номер формы — ключ API и адресов)
SAN_TABLES = {"257": "san_cycles", "502": "san_cleanings", "501": "san_uv"}
# что пишет вставка (остальное — значения по умолчанию схемы)
_SAN_COLS = {
    "san_cycles": ("ster_id", "ster", "program", "pressure", "temp", "arts", "started_at",
                   "ended_at", "chem", "term", "bio", "actor", "actor_id", "end_actor",
                   "bio_actor", "bio_at", "fixes", "why", "created_at"),
    "san_cleanings": ("room_id", "room", "plan_date", "done_date", "solution", "actor",
                      "actor_id", "fixes", "why", "created_at"),
    "san_uv": ("lamp_id", "lamp", "room", "cond", "on_at", "off_at", "minutes", "rest_hours",
               "actor", "actor_id", "off_actor", "fixes", "why", "created_at"),
}
# поле-замок однократного закрытия → что вместе с ним пишется
_SAN_CLOSE = {
    ("san_cycles", "ended_at"): ("ended_at", "chem", "term", "bio", "end_actor"),
    ("san_cycles", "bio_at"): ("bio", "bio_actor", "bio_at"),
    ("san_cleanings", "sup_at"): ("sup_actor", "sup_id", "sup_at"),
    ("san_uv", "off_at"): ("off_at", "minutes", "rest_hours", "off_actor"),
}
# колонка периода у журнала: момент начала или голая дата уборки
_SAN_WHEN = {"san_cycles": "started_at", "san_cleanings": "done_date", "san_uv": "on_at"}
SAN_KINDS = ("ster", "lamp", "room", "solution", "article", "pack", "norms")


def _san_table(reg: str) -> str:
    t = SAN_TABLES.get(reg)
    if t is None:
        raise ValueError(f"registru necunoscut: {reg!r}")
    return t


# ---------- каталог ----------

async def san_items(kind: str | None = None, active_only: bool = False) -> list:
    """Каталог (все виды или один), `data` разобран в словарь."""
    where, args = [], []
    if kind:
        where.append("kind = ?"); args.append(kind)
    if active_only:
        where.append("active = 1")
    sql = "SELECT * FROM san_equipment" + (" WHERE " + " AND ".join(where) if where else "")
    rows = await _fetch(sql + " ORDER BY kind, sort, id", *args)
    for r in rows:
        try:
            r["data"] = json.loads(r.get("data") or "{}")
        except ValueError:
            r["data"] = {}
    return rows


async def san_item(item_id: int) -> dict | None:
    rows = await _fetch("SELECT * FROM san_equipment WHERE id = ?", item_id)
    if not rows:
        return None
    r = rows[0]
    try:
        r["data"] = json.loads(r.get("data") or "{}")
    except ValueError:
        r["data"] = {}
    return r


async def _san_insert_id(sql: str, *args) -> int:
    """Вставка с id новой строки — тем же курсором (`lastrowid`): `MAX(id)`
    вторым запросом мог бы вернуть чужую вставку из соседней корутины."""
    cur = await db._CONN.execute(sql, args)
    await db._CONN.commit()
    new_id = cur.lastrowid
    await cur.close()
    return int(new_id)


async def san_item_save(item: dict) -> int:
    """Вставка (нет `id`) или правка строки каталога; вид не меняется."""
    now = _utcnow_iso()
    data = json.dumps(item.get("data") or {}, ensure_ascii=False)
    if item.get("id"):
        await _execute(
            """UPDATE san_equipment SET name = ?, nr = ?, room = ?, data = ?, active = ?,
                      sort = ?, updated_at = ? WHERE id = ?""",
            item["name"], item.get("nr", ""), item.get("room", ""), data,
            1 if item.get("active", True) else 0, int(item.get("sort") or 0), now, int(item["id"]))
        return int(item["id"])
    return await _san_insert_id(
        """INSERT INTO san_equipment(kind, name, nr, room, data, active, sort, created_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        item["kind"], item["name"], item.get("nr", ""), item.get("room", ""), data,
        1 if item.get("active", True) else 0, int(item.get("sort") or 0), now)


# ---------- журналы ----------

async def san_insert(reg: str, row: dict) -> int:
    """Новая строка журнала; `created_at` — часы программы."""
    t = _san_table(reg)
    cols = [c for c in _SAN_COLS[t] if c in row or c == "created_at"]
    vals = [row.get(c) if c != "created_at" else (row.get(c) or _utcnow_iso()) for c in cols]
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in vals]
    return await _san_insert_id(f"INSERT INTO {t}({', '.join(cols)}) VALUES({', '.join('?' for _ in cols)})",
                            *vals)


async def san_close(reg: str, row_id: int, lock: str, values: dict) -> bool:
    """Однократное закрытие: пишет поля замка `lock`, только если он ещё ПУСТ
    и строка не удалена. False — уже закрыта (или удалена, или нет такой)."""
    t = _san_table(reg)
    cols = _SAN_CLOSE.get((t, lock))
    if cols is None:
        raise ValueError(f"închidere necunoscută: {t}.{lock}")
    sets = [c for c in cols if c in values]
    if lock not in sets:
        raise ValueError(f"închiderea {t}.{lock} fără valoarea câmpului-lacăt")
    n = await _execute(f"UPDATE {t} SET {', '.join(f'{c} = ?' for c in sets)} "
                       f"WHERE id = ? AND {lock} IS NULL AND deleted_at IS NULL",
                       *[values[c] for c in sets], row_id)
    return n > 0


async def san_delete(reg: str, row_id: int, actor: str) -> bool:
    t = _san_table(reg)
    n = await _execute(f"UPDATE {t} SET deleted_at = ?, deleted_by = ? "
                       "WHERE id = ? AND deleted_at IS NULL", _utcnow_iso(), actor, row_id)
    return n > 0


async def san_row(reg: str, row_id: int) -> dict | None:
    t = _san_table(reg)
    rows = await _fetch(f"SELECT * FROM {t} WHERE id = ?", row_id)
    return rows[0] if rows else None


async def san_rows(reg: str, since: str, until: str) -> list:
    """Строки журнала за период [since, until) по моменту начала (у уборки —
    по дню), без удалённых, по номеру. Границы — той же формы, что колонка:
    UTC ISO у моментов, голая дата у уборки."""
    t = _san_table(reg)
    w = _SAN_WHEN[t]
    return await _fetch(f"SELECT * FROM {t} WHERE deleted_at IS NULL AND {w} >= ? AND {w} < ? "
                        "ORDER BY id", since, until)


async def san_open(reg: str) -> list:
    """Открытые записи: идущие циклы, включённые лампы, уборки без проверки."""
    t = _san_table(reg)
    lock = {"san_cycles": "ended_at", "san_uv": "off_at", "san_cleanings": "sup_at"}[t]
    return await _fetch(f"SELECT * FROM {t} WHERE deleted_at IS NULL AND {lock} IS NULL "
                        f"AND id NOT IN (SELECT fixes FROM {t} WHERE fixes IS NOT NULL "
                        "AND deleted_at IS NULL) ORDER BY id")


async def san_fixed_ids(reg: str) -> dict:
    """{id исправленной: id исправления} — живые исправления журнала."""
    t = _san_table(reg)
    rows = await _fetch(f"SELECT id, fixes FROM {t} WHERE fixes IS NOT NULL AND deleted_at IS NULL")
    return {int(r["fixes"]): int(r["id"]) for r in rows}


async def san_lamp_minutes(lamp_id: int, since: str) -> int:
    """Минуты работы лампы с момента `since` (UTC ISO) по закрытым сеансам —
    исправленные считаются по исправлению, удалённые не считаются."""
    v = await _fetchval(
        """SELECT COALESCE(SUM(minutes), 0) FROM san_uv
            WHERE lamp_id = ? AND on_at >= ? AND off_at IS NOT NULL AND deleted_at IS NULL
              AND id NOT IN (SELECT fixes FROM san_uv WHERE fixes IS NOT NULL
                             AND deleted_at IS NULL)""", lamp_id, since)
    return int(v or 0)


async def san_last_clean(room_id: int) -> str:
    """Последний день генеральной уборки помещения ('' — не было)."""
    v = await _fetchval("""SELECT MAX(done_date) FROM san_cleanings
                            WHERE room_id = ? AND deleted_at IS NULL""", room_id)
    return v or ""


async def san_last_cycle(ster_id: int) -> dict | None:
    rows = await _fetch("""SELECT * FROM san_cycles WHERE ster_id = ? AND deleted_at IS NULL
                            AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1""", ster_id)
    return rows[0] if rows else None
