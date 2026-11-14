"""Заказы в зуботехническую лабораторию: каталог лабораторий, шапка заказа,
строки (работы) и история событий.

Правила (переходы, сроки, пересчёт шапки из истории) — `core/lab.py`; здесь
только чтение и запись. `lab_events` только дописывается, заказ не удаляется
(держит `test_structure`)."""
from __future__ import annotations

import json

from .. import db
from .conn import _execute, _fetch, _fetchval, _utcnow_iso

# Открытые и закрытые статусы — перечислением: новый статус обязан встать в
# один из списков, а не попасть в «всё остальное».
LAB_OPEN = ("trimis", "gata", "primit", "proba")
LAB_CLOSED = ("finalizat", "anulat")
LAB_STATUSES = LAB_OPEN + LAB_CLOSED

_LAB_COLS = ("name", "phone", "email", "contact", "days", "workdays", "active", "sort")
_ORDER_COLS = ("doctor_id", "doctor", "lab_id", "lab", "appointment_id", "urgent",
               "impression", "note")
_HEAD_COLS = ("status", "stage", "sent_on", "due_on", "received_on", "done_on")
_ITEM_COLS = ("plan_item_id", "service_id", "work", "material", "shade", "teeth", "qty",
              "grp", "price_bani")


def _js(row: dict, key: str = "data") -> dict:
    try:
        v = json.loads(row.get(key) or "{}")
    except ValueError:
        v = {}
    row[key] = v if isinstance(v, dict) else {}
    return row


# ---------- каталог лабораторий ----------

async def labs_all() -> list:
    marks = ",".join("?" for _ in LAB_OPEN)
    rows = await _fetch(
        f"""SELECT l.*, (SELECT COUNT(*) FROM lab_orders o WHERE o.lab_id = l.id) AS orders,
                   (SELECT COUNT(*) FROM lab_orders o WHERE o.lab_id = l.id
                     AND o.status IN ({marks})) AS open
            FROM labs l ORDER BY l.active DESC, l.sort, l.name COLLATE NOCASE""", *LAB_OPEN)
    return [_js(r) for r in rows]


async def lab_get(lab_id: int) -> dict | None:
    rows = await _fetch("SELECT * FROM labs WHERE id = ?", lab_id)
    return _js(rows[0]) if rows else None


async def lab_by_name(name: str) -> dict | None:
    rows = await _fetch("SELECT * FROM labs WHERE lower(trim(name)) = lower(trim(?)) ORDER BY id", name)
    return _js(rows[0]) if rows else None


async def lab_save(lab: dict) -> int:
    vals = [lab[c] for c in _LAB_COLS]
    data = json.dumps(lab.get("data") or {}, ensure_ascii=False, sort_keys=True)
    now = _utcnow_iso()
    if lab.get("id"):
        sets = ", ".join(f"{c} = ?" for c in _LAB_COLS)
        await _execute(f"UPDATE labs SET {sets}, data = ?, updated_at = ? WHERE id = ?",
                       *vals, data, now, lab["id"])
        return int(lab["id"])
    cols = ", ".join(_LAB_COLS)
    cur = await db._CONN.execute(
        f"INSERT INTO labs({cols}, data, created_at) VALUES({', '.join('?' for _ in _LAB_COLS)}, ?, ?)",
        (*vals, data, now))
    await db._CONN.commit()
    return int(cur.lastrowid)


async def lab_delete(lab_id: int) -> bool:
    """Только лабораторию без единого заказа: заказ держит её снимком и ссылкой."""
    n = await _execute(
        "DELETE FROM labs WHERE id = ? AND NOT EXISTS (SELECT 1 FROM lab_orders WHERE lab_id = ?)",
        lab_id, lab_id)
    return n == 1


# ---------- заказы ----------

async def lab_order_create(head: dict, items: list, first: dict) -> tuple[int, int]:
    """Шапка, строки и первое событие одной транзакцией. Номер — MAX+1 в самом
    INSERT: два заказа одновременно не получат один номер, а уникальный индекс
    это подтверждает. (id, nr)."""
    now = _utcnow_iso()
    cols = _ORDER_COLS + _HEAD_COLS
    try:
        cur = await db._CONN.execute(
            f"""INSERT INTO lab_orders(nr, patient_id, {', '.join(cols)}, data, actor, actor_id, created_at)
                VALUES((SELECT COALESCE(MAX(nr), 0) + 1 FROM lab_orders), ?,
                       {', '.join('?' for _ in cols)}, ?, ?, ?, ?)""",
            (head["patient_id"], *[head[c] for c in cols],
             json.dumps(head.get("data") or {}, ensure_ascii=False, sort_keys=True),
             head.get("actor", ""), head.get("actor_id", ""), now))
        oid = int(cur.lastrowid)
        await _items_insert(oid, items)
        await _event_insert(oid, first, now)
        await db._CONN.commit()
    except Exception:
        await db._CONN.rollback()
        raise
    nr = await _fetchval("SELECT nr FROM lab_orders WHERE id = ?", oid)
    return oid, int(nr)


async def _items_insert(oid: int, items: list) -> None:
    for i, it in enumerate(items):
        await db._CONN.execute(
            f"INSERT INTO lab_order_items(order_id, sort, {', '.join(_ITEM_COLS)}) "
            f"VALUES(?, ?, {', '.join('?' for _ in _ITEM_COLS)})",
            (oid, i, *[it.get(c) for c in _ITEM_COLS]))


async def _event_insert(oid: int, ev: dict, at: str) -> int:
    cur = await db._CONN.execute(
        """INSERT INTO lab_events(order_id, item_id, kind, on_date, due_on, cause, payer, note,
                                  data, actor, actor_id, doer, at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (oid, ev.get("item_id"), ev["kind"], ev.get("on_date"), ev.get("due_on"),
         ev.get("cause") or "", ev.get("payer") or "", ev.get("note") or "",
         json.dumps(ev.get("data") or {}, ensure_ascii=False, sort_keys=True),
         ev.get("actor") or "", ev.get("actor_id") or "", ev.get("doer") or "", at))
    return int(cur.lastrowid)


async def lab_order_write(oid: int, *, head: dict | None = None, items: list | None = None,
                          events: list | None = None) -> None:
    """Правка заказа одной транзакцией: поля шапки (`head`, только известные
    колонки), весь новый список строк (`items`; строка с `id` правится, без —
    вставляется, не названная — уходит) и события. События только дописываются."""
    now = _utcnow_iso()
    try:
        if head:
            keys = [k for k in head if k in _ORDER_COLS + _HEAD_COLS or k == "data"]
            vals = [json.dumps(head[k], ensure_ascii=False, sort_keys=True) if k == "data" else head[k]
                    for k in keys]
            sets = ", ".join(f"{k} = ?" for k in keys)
            await db._CONN.execute(f"UPDATE lab_orders SET {sets}, updated_at = ? WHERE id = ?",
                                   (*vals, now, oid))
        if items is not None:
            keep = [int(it["id"]) for it in items if it.get("id")]
            marks = ",".join("?" for _ in keep)
            await db._CONN.execute(
                "DELETE FROM lab_order_items WHERE order_id = ?"
                + (f" AND id NOT IN ({marks})" if keep else ""), (oid, *keep))
            sets = ", ".join(f"{c} = ?" for c in _ITEM_COLS)
            for i, it in enumerate(items):
                if it.get("id"):
                    await db._CONN.execute(
                        f"UPDATE lab_order_items SET sort = ?, {sets} WHERE id = ? AND order_id = ?",
                        (i, *[it.get(c) for c in _ITEM_COLS], int(it["id"]), oid))
                else:
                    await db._CONN.execute(
                        f"INSERT INTO lab_order_items(order_id, sort, {', '.join(_ITEM_COLS)}) "
                        f"VALUES(?, ?, {', '.join('?' for _ in _ITEM_COLS)})",
                        (oid, i, *[it.get(c) for c in _ITEM_COLS]))
        for ev in events or []:
            await _event_insert(oid, ev, now)
        await db._CONN.commit()
    except Exception:
        await db._CONN.rollback()
        raise


async def lab_order_head(oid: int) -> dict | None:
    rows = await _fetch("SELECT * FROM lab_orders WHERE id = ?", oid)
    return _js(rows[0]) if rows else None


async def lab_orders_rows(pid: int | None = None) -> list:
    """Шапки заказов с именем и № фиши пациента НА СЕЙЧАС (в заказе их нет)."""
    where, args = ("WHERE o.patient_id = ?", (pid,)) if pid is not None else ("", ())
    rows = await _fetch(
        f"""SELECT o.*, p.name AS patient, p.file_no AS file_no
            FROM lab_orders o LEFT JOIN patients p ON p.id = o.patient_id
            {where} ORDER BY o.id DESC""", *args)
    return [_js(r) for r in rows]


async def lab_items(order_ids: list[int]) -> dict[int, list]:
    if not order_ids:
        return {}
    marks = ",".join("?" for _ in order_ids)
    rows = await _fetch(
        f"""SELECT i.*, p.procedure AS plan_procedure, p.tooth AS plan_tooth, p.status AS plan_status
            FROM lab_order_items i LEFT JOIN plan_items p ON p.id = i.plan_item_id
            WHERE i.order_id IN ({marks}) ORDER BY i.order_id, i.sort, i.id""", *order_ids)
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(r["order_id"], []).append(r)
    return out


async def lab_events(order_ids: list[int]) -> dict[int, list]:
    if not order_ids:
        return {}
    marks = ",".join("?" for _ in order_ids)
    rows = await _fetch(f"SELECT * FROM lab_events WHERE order_id IN ({marks}) ORDER BY order_id, id",
                        *order_ids)
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(r["order_id"], []).append(_js(r))
    return out


async def lab_order_ids(pid: int) -> list[int]:
    return [r["id"] for r in await _fetch("SELECT id FROM lab_orders WHERE patient_id = ? ORDER BY id", pid)]


async def lab_last_prices(limit: int = 2000) -> list:
    """Цены строк, новые сверху — подсказка «прошлая цена той же работы у этой
    лаборатории». Отменённые заказы не советуют."""
    return await _fetch(
        """SELECT o.lab_id, i.work, i.price_bani, o.nr, o.sent_on
           FROM lab_order_items i JOIN lab_orders o ON o.id = i.order_id
           WHERE i.price_bani IS NOT NULL AND o.status != 'anulat' AND o.lab_id IS NOT NULL
           ORDER BY o.id DESC, i.sort LIMIT ?""", limit)


async def lab_next_appts(pids: list[int], since_utc: str) -> dict[int, dict]:
    """Ближайший живой визит каждого пациента с момента `since_utc` (начало дня
    клиники — модель от минуты не зависит)."""
    if not pids:
        return {}
    from .slots import _ACT_SQL
    marks = ",".join("?" for _ in pids)
    rows = await _fetch(
        f"""SELECT id, patient_id, starts_at, doctor FROM appointments
            WHERE patient_id IN ({marks}) AND status IN {_ACT_SQL} AND starts_at >= ?
              AND source != 'note'
            ORDER BY starts_at, id""", *pids, since_utc)
    out: dict[int, dict] = {}
    for r in rows:
        out.setdefault(r["patient_id"], r)
    return out


async def lab_plan_item(item_id: int, pid: int) -> dict | None:
    """Позиция плана этого пациента целиком: ключ услуги и врача — колонки,
    которых у старой схемы плана может не быть, поэтому `*`."""
    rows = await _fetch("SELECT * FROM plan_items WHERE id = ? AND patient_id = ?", item_id, pid)
    return rows[0] if rows else None


async def lab_appt_patient(appt_id: int) -> int | None:
    return await _fetchval("SELECT patient_id FROM appointments WHERE id = ?", appt_id)
