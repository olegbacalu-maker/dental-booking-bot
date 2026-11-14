"""Склад материалов: поставщики, каталог, документы (накладная, инвентаризация,
импорт) и журнал движений.

Правила (остаток, средняя цена, кто что может) — `core/stock.py`; здесь только
чтение и запись. `stock_moves` только дописывается: исправление — новая строка
`corectie` с `fixes` (держит `test_structure`). Документы-черновики журнала не
касаются и удаляются целиком."""
from __future__ import annotations

import json

from .. import db
from .conn import _execute, _fetch, _fetchval, _utcnow_iso

# Виды движений, причины и статусы документов — перечислением: новый код
# обязан встать в список, а не попасть в «всё остальное».
STOCK_KINDS = ("intrare", "consum", "casare", "inventar", "corectie")
STOCK_OUT_REASONS = ("pacient", "deschis", "expirat", "defect", "pierdut", "altul")
STOCK_FIX_REASONS = ("anulare", "storno", "suma", "import_anulat")
STOCK_DOC_KINDS = ("factura", "inventar", "import")
STOCK_DOC_OPEN = ("ciorna",)
STOCK_DOC_CLOSED = ("inchis", "anulat")
# Отмена, после которой исходного движения как бы не было (сумма — нет:
# она только дописывает цену).
STOCK_UNDOES = ("anulare", "storno", "import_anulat")

_ST_SUP_COLS = ("name", "idno", "phone", "email", "note", "active")
_ST_ITEM_COLS = ("name", "category", "unit", "pack_name", "pack_qty_milli", "min_milli", "costly",
              "track_expiry", "bulk", "supplier_id", "note", "active", "sort")
_ST_DOC_COLS = ("nr", "doc_date", "supplier_id", "supplier", "note", "cur", "cur_amount", "rate")
_ST_LINE_COLS = ("item_id", "qty_milli", "prog_milli", "cost_bani", "lot", "expiry", "note")
_ST_MOVE_COLS = ("kind", "item_id", "item_name", "qty_milli", "cost_bani", "place", "doc_id", "line_id",
              "lot", "expiry", "patient_id", "appointment_id", "plan_item_id", "service_id",
              "doctor_id", "doctor", "supplier", "source", "reason", "note", "actor", "actor_id",
              "doer", "fixes", "why")


def _st_js(row: dict, key: str = "data") -> dict:
    try:
        v = json.loads(row.get(key) or "{}")
    except ValueError:
        v = {}
    row[key] = v if isinstance(v, dict) else {}
    return row


def _st_dump(v) -> str:
    return json.dumps(v or {}, ensure_ascii=False, sort_keys=True)


async def _st_tx(work):
    """Одна транзакция на общем соединении: всё или ничего."""
    try:
        out = await work()
        await db._CONN.commit()
    except Exception:
        await db._CONN.rollback()
        raise
    return out


async def _st_insert(table: str, cols: tuple, row: dict, extra: dict | None = None) -> int:
    names = list(cols) + list((extra or {}).keys())
    vals = [row.get(c) for c in cols] + list((extra or {}).values())
    cur = await db._CONN.execute(
        f"INSERT INTO {table}({', '.join(names)}) VALUES({', '.join('?' for _ in names)})", vals)
    return int(cur.lastrowid)


# ---------- поставщики ----------

async def stock_suppliers() -> list:
    rows = await _fetch(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM stock_items i WHERE i.supplier_id = s.id
                    AND i.deleted_at IS NULL) AS items,
                  (SELECT COUNT(*) FROM stock_docs d WHERE d.supplier_id = s.id) AS docs
           FROM stock_suppliers s ORDER BY s.active DESC, s.name COLLATE NOCASE""")
    return [_st_js(r) for r in rows]


async def stock_supplier(sid: int) -> dict | None:
    rows = await _fetch("SELECT * FROM stock_suppliers WHERE id = ?", sid)
    return _st_js(rows[0]) if rows else None


async def stock_supplier_save(s: dict) -> int:
    now = _utcnow_iso()
    if s.get("id"):
        sets = ", ".join(f"{c} = ?" for c in _ST_SUP_COLS)
        await _execute(f"UPDATE stock_suppliers SET {sets}, updated_at = ? WHERE id = ?",
                       *[s[c] for c in _ST_SUP_COLS], now, s["id"])
        return int(s["id"])
    return await _st_tx(lambda: _st_insert("stock_suppliers", _ST_SUP_COLS, s, {"created_at": now}))


async def stock_supplier_delete(sid: int) -> bool:
    """Только поставщика без материалов и документов: оба держат его ссылкой."""
    n = await _execute(
        """DELETE FROM stock_suppliers WHERE id = ?
           AND NOT EXISTS (SELECT 1 FROM stock_items WHERE supplier_id = ?)
           AND NOT EXISTS (SELECT 1 FROM stock_docs WHERE supplier_id = ?)""", sid, sid, sid)
    return n == 1


# ---------- каталог ----------

async def stock_items(with_deleted: bool = False) -> list:
    where = "" if with_deleted else "WHERE i.deleted_at IS NULL"
    rows = await _fetch(
        f"""SELECT i.*, s.name AS supplier_name,
                   (SELECT COUNT(*) FROM stock_moves m WHERE m.item_id = i.id) AS moves
            FROM stock_items i LEFT JOIN stock_suppliers s ON s.id = i.supplier_id
            {where} ORDER BY i.category COLLATE NOCASE, i.sort, i.name COLLATE NOCASE""")
    return [_st_js(r) for r in rows]


async def stock_item(item_id: int) -> dict | None:
    rows = await _fetch(
        """SELECT i.*, s.name AS supplier_name,
                  (SELECT COUNT(*) FROM stock_moves m WHERE m.item_id = i.id) AS moves
           FROM stock_items i LEFT JOIN stock_suppliers s ON s.id = i.supplier_id
           WHERE i.id = ? AND i.deleted_at IS NULL""", item_id)
    return _st_js(rows[0]) if rows else None


async def stock_item_save(it: dict, first: dict | None = None) -> int:
    """Новый материал или правка. `first` — начальный остаток нового
    («acum pe raft»): движение в той же транзакции, что и материал."""
    now = _utcnow_iso()
    if it.get("id"):
        sets = ", ".join(f"{c} = ?" for c in _ST_ITEM_COLS)
        await _execute(f"UPDATE stock_items SET {sets}, data = ?, updated_at = ? WHERE id = ?",
                       *[it[c] for c in _ST_ITEM_COLS], _st_dump(it.get("data")), now, it["id"])
        return int(it["id"])

    async def work():
        iid = await _st_insert("stock_items", _ST_ITEM_COLS, it, {"data": _st_dump(it.get("data")), "created_at": now})
        if first:
            await _stock_move_insert({**first, "item_id": iid}, now)
        return iid
    return await _st_tx(work)


async def stock_item_delete(item_id: int, by: str) -> bool:
    """Мягко и только без движений: строка журнала держит материал ссылкой."""
    n = await _execute(
        """UPDATE stock_items SET deleted_at = ?, deleted_by = ? WHERE id = ? AND deleted_at IS NULL
           AND NOT EXISTS (SELECT 1 FROM stock_moves WHERE item_id = ?)""",
        _utcnow_iso(), by, item_id, item_id)
    return n == 1


async def stock_order_mark(ids: list[int], by: str) -> int:
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    return await _execute(
        f"UPDATE stock_items SET ordered_at = ?, ordered_by = ? WHERE id IN ({marks}) AND deleted_at IS NULL",
        _utcnow_iso(), by, *ids)


async def stock_order_clear(item_id: int) -> int:
    return await _execute("UPDATE stock_items SET ordered_at = NULL, ordered_by = '' WHERE id = ?", item_id)


# ---------- журнал движений ----------

async def _stock_move_insert(m: dict, at: str) -> int:
    """Единственная запись в журнал: только INSERT. `at` — когда случилось,
    `created_at` — когда внесено (накладную вносят позже прихода)."""
    row = {"place": "", "source": "manual", **m}
    for k in ("lot", "doctor_id", "doctor", "supplier", "reason", "note", "actor", "actor_id", "doer", "why"):
        row[k] = row.get(k) or ""
    return await _st_insert("stock_moves", _ST_MOVE_COLS, row, {"at": m.get("at") or at, "created_at": at})


async def stock_move_add(m: dict) -> int:
    return await _st_tx(lambda: _stock_move_insert(m, _utcnow_iso()))


async def stock_moves_all(item_ids: list[int] | None = None) -> list:
    """Журнал для расчёта остатков и средних: по порядку внесения."""
    if item_ids is not None:
        if not item_ids:
            return []
        marks = ",".join("?" for _ in item_ids)
        return await _fetch(f"SELECT * FROM stock_moves WHERE deleted_at IS NULL AND item_id IN ({marks}) "
                            "ORDER BY id", *item_ids)
    return await _fetch("SELECT * FROM stock_moves WHERE deleted_at IS NULL ORDER BY id")


async def stock_move(mid: int) -> dict | None:
    rows = await _fetch("SELECT * FROM stock_moves WHERE id = ? AND deleted_at IS NULL", mid)
    return rows[0] if rows else None


async def stock_moves_query(*, item: int | None = None, kind: str = "", since_utc: str = "",
                            until_utc: str = "", actor: str = "", supplier: int | None = None,
                            pid: int | None = None, doc: int | None = None, limit: int = 300) -> list:
    """Журнал для экрана «Mișcări», новые сверху; имя и № фиши — на сейчас."""
    where, args = ["m.deleted_at IS NULL"], []
    for cond, val in (("m.item_id = ?", item), ("m.kind = ?", kind or None), ("m.at >= ?", since_utc or None),
                      ("m.at < ?", until_utc or None), ("m.actor = ?", actor or None),
                      ("m.patient_id = ?", pid), ("m.doc_id = ?", doc)):
        if val is not None:
            where.append(cond)
            args.append(val)
    if supplier is not None:
        where.append("d.supplier_id = ?")
        args.append(supplier)
    return await _fetch(
        f"""SELECT m.*, d.kind AS doc_kind, d.nr AS doc_nr, d.supplier AS doc_supplier,
                   i.unit AS unit, p.name AS patient, p.file_no AS file_no
            FROM stock_moves m
            LEFT JOIN stock_docs d ON d.id = m.doc_id
            LEFT JOIN stock_items i ON i.id = m.item_id
            LEFT JOIN patients p ON p.id = m.patient_id
            WHERE {' AND '.join(where)} ORDER BY m.at DESC, m.id DESC LIMIT ?""", *args, limit)


async def stock_fixed() -> dict[int, list]:
    """Какие движения исправлены и чем: id → строки `corectie`."""
    out: dict[int, list] = {}
    for r in await _fetch("SELECT id, fixes, reason, cost_bani FROM stock_moves "
                          "WHERE fixes IS NOT NULL AND deleted_at IS NULL"):
        out.setdefault(r["fixes"], []).append(r)
    return out


async def stock_actors() -> list[str]:
    return [r["actor"] for r in await _fetch(
        "SELECT DISTINCT actor FROM stock_moves WHERE actor != '' ORDER BY actor")]


async def stock_moves_patient(pid: int) -> list:
    return await _fetch(
        """SELECT m.*, i.unit AS unit FROM stock_moves m LEFT JOIN stock_items i ON i.id = m.item_id
           WHERE m.patient_id = ? AND m.deleted_at IS NULL ORDER BY m.at DESC, m.id DESC""", pid)


async def stock_moves_range(since_utc: str, until_utc: str) -> list:
    return await _fetch(
        """SELECT m.*, d.kind AS doc_kind, d.nr AS doc_nr, d.doc_date AS doc_date, i.unit AS unit
           FROM stock_moves m LEFT JOIN stock_docs d ON d.id = m.doc_id
           LEFT JOIN stock_items i ON i.id = m.item_id
           WHERE m.deleted_at IS NULL AND m.at >= ? AND m.at < ? ORDER BY m.at, m.id""", since_utc, until_utc)


# ---------- документы ----------

async def stock_docs(kind: str = "", status: str = "") -> list:
    where, args = [], []
    if kind:
        where.append("d.kind = ?")
        args.append(kind)
    if status:
        where.append("d.status = ?")
        args.append(status)
    rows = await _fetch(
        f"""SELECT d.*, (SELECT COUNT(*) FROM stock_doc_lines l WHERE l.doc_id = d.id) AS lines,
                   (SELECT SUM(l.cost_bani) FROM stock_doc_lines l WHERE l.doc_id = d.id) AS lines_bani
            FROM stock_docs d {('WHERE ' + ' AND '.join(where)) if where else ''}
            ORDER BY d.id DESC""", *args)
    return [_st_js(r) for r in rows]


async def stock_doc(doc_id: int) -> dict | None:
    rows = await _fetch("SELECT * FROM stock_docs WHERE id = ?", doc_id)
    return _st_js(rows[0]) if rows else None


async def stock_doc_lines(doc_id: int) -> list:
    return await _fetch(
        """SELECT l.*, i.name AS item_name, i.unit AS unit, i.pack_qty_milli AS pack_qty_milli,
                  i.active AS item_active
           FROM stock_doc_lines l LEFT JOIN stock_items i ON i.id = l.item_id
           WHERE l.doc_id = ? ORDER BY l.sort, l.id""", doc_id)


async def _st_lines_put(doc_id: int, lines: list) -> None:
    keep = [int(x["id"]) for x in lines if x.get("id")]
    marks = ",".join("?" for _ in keep)
    await db._CONN.execute("DELETE FROM stock_doc_lines WHERE doc_id = ?"
                           + (f" AND id NOT IN ({marks})" if keep else ""), (doc_id, *keep))
    sets = ", ".join(f"{c} = ?" for c in _ST_LINE_COLS)
    for i, ln in enumerate(lines):
        if ln.get("id"):
            await db._CONN.execute(f"UPDATE stock_doc_lines SET sort = ?, {sets} WHERE id = ? AND doc_id = ?",
                                   (i, *[ln.get(c) for c in _ST_LINE_COLS], int(ln["id"]), doc_id))
        else:
            await _st_insert("stock_doc_lines", _ST_LINE_COLS, ln, {"doc_id": doc_id, "sort": i})


async def stock_doc_create(head: dict, lines: list, supplier: dict | None = None) -> int:
    """Черновик (или импорт) одной транзакцией; `supplier` — новый поставщик
    из окна накладной, заводится вместе с ней."""
    now = _utcnow_iso()

    async def work():
        h = dict(head)
        if supplier:
            h["supplier_id"] = await _st_insert("stock_suppliers", _ST_SUP_COLS, supplier, {"created_at": now})
        did = await _st_insert("stock_docs", _ST_DOC_COLS, h, {
            "kind": h["kind"], "status": h.get("status", "ciorna"), "data": _st_dump(h.get("data")),
            "actor": h.get("actor", ""), "actor_id": h.get("actor_id", ""), "created_at": now})
        await _st_lines_put(did, lines)
        return did
    return await _st_tx(work)


async def stock_doc_write(doc_id: int, head: dict | None, lines: list | None,
                          supplier: dict | None = None) -> bool:
    """Правка черновика: известные поля шапки и, если прислан, весь список строк.
    False — документ уже не черновик (закрыли в соседнем окне)."""
    now = _utcnow_iso()

    async def work():
        h = dict(head or {})
        if supplier:
            h["supplier_id"] = await _st_insert("stock_suppliers", _ST_SUP_COLS, supplier, {"created_at": now})
        keys = [k for k in h if k in _ST_DOC_COLS]
        cur = await db._CONN.execute(
            f"UPDATE stock_docs SET {''.join(f'{k} = ?, ' for k in keys)}updated_at = ? "
            "WHERE id = ? AND status = 'ciorna'", (*[h[k] for k in keys], now, doc_id))
        if cur.rowcount != 1:
            return False
        if lines is not None:
            await _st_lines_put(doc_id, lines)
        return True
    return await _st_tx(work)


async def stock_doc_delete(doc_id: int) -> bool:
    """Только черновик: в журнал он ещё ничего не писал."""
    async def work():
        cur = await db._CONN.execute("DELETE FROM stock_doc_lines WHERE doc_id = ? AND EXISTS "
                                     "(SELECT 1 FROM stock_docs WHERE id = ? AND status = 'ciorna')",
                                     (doc_id, doc_id))
        cur = await db._CONN.execute("DELETE FROM stock_docs WHERE id = ? AND status = 'ciorna'", (doc_id,))
        return cur.rowcount == 1
    return await _st_tx(work)


async def stock_doc_close(doc_id: int, moves: list, *, by: str, no_sums: bool, total: int | None,
                          prog: dict[int, int] | None = None, unorder: list[int] | None = None) -> bool:
    """Черновик → журнал одной транзакцией: движения строк, «în program» строк
    инвентаризации, снятие отметки «Comandat», статус. False — уже закрыт."""
    now = _utcnow_iso()

    async def work():
        cur = await db._CONN.execute(
            "UPDATE stock_docs SET status = 'inchis', closed_at = ?, closed_by = ?, no_sums = ?, "
            "total_bani = ?, updated_at = ? WHERE id = ? AND status = 'ciorna'",
            (now, by, int(no_sums), total, now, doc_id))
        if cur.rowcount != 1:
            return False
        for line_id, v in (prog or {}).items():
            await db._CONN.execute("UPDATE stock_doc_lines SET prog_milli = ? WHERE id = ? AND doc_id = ?",
                                   (v, line_id, doc_id))
        for m in moves:
            await _stock_move_insert({**m, "doc_id": doc_id}, now)
        if unorder:
            marks = ",".join("?" for _ in unorder)
            await db._CONN.execute(f"UPDATE stock_items SET ordered_at = NULL, ordered_by = '' "
                                   f"WHERE id IN ({marks})", tuple(unorder))
        return True
    return await _st_tx(work)


async def stock_doc_sums(doc_id: int, costs: dict[int, int], moves: list, *, no_sums: bool,
                         total: int | None) -> None:
    """Суммы, дописанные директором: цена строки документа и строки `suma` в
    журнал на разницу — количество не трогается."""
    now = _utcnow_iso()

    async def work():
        for line_id, v in costs.items():
            await db._CONN.execute("UPDATE stock_doc_lines SET cost_bani = ? WHERE id = ? AND doc_id = ?",
                                   (v, line_id, doc_id))
        for m in moves:
            await _stock_move_insert({**m, "doc_id": doc_id}, now)
        await db._CONN.execute("UPDATE stock_docs SET no_sums = ?, total_bani = ?, updated_at = ? WHERE id = ?",
                               (int(no_sums), total, now, doc_id))
    await _st_tx(work)


async def stock_doc_undo(doc_id: int, moves: list, *, by: str, why: str,
                         items: list[int] = (), suppliers: list[int] = ()) -> bool:
    """Сторно накладной или отмена импорта: обратные строки в журнал, документ
    `anulat`; у импорта — его материалы и поставщики мягко/целиком из списков."""
    now = _utcnow_iso()

    async def work():
        cur = await db._CONN.execute(
            "UPDATE stock_docs SET status = 'anulat', undone_at = ?, undone_by = ?, why = ?, updated_at = ? "
            "WHERE id = ? AND status = 'inchis'", (now, by, why, now, doc_id))
        if cur.rowcount != 1:
            return False
        for m in moves:
            await _stock_move_insert({**m, "doc_id": doc_id}, now)
        for iid in items:
            await db._CONN.execute("UPDATE stock_items SET deleted_at = ?, deleted_by = ? WHERE id = ?",
                                   (now, by, iid))
        for sid in suppliers:
            cur = await db._CONN.execute(
                """SELECT 1 FROM stock_suppliers WHERE id = ? AND import_doc = ?
                   AND NOT EXISTS (SELECT 1 FROM stock_items WHERE supplier_id = ? AND deleted_at IS NULL)
                   AND NOT EXISTS (SELECT 1 FROM stock_docs WHERE supplier_id = ?)""", (sid, doc_id, sid, sid))
            if await cur.fetchone() is None:
                continue
            await db._CONN.execute("UPDATE stock_items SET supplier_id = NULL WHERE supplier_id = ?", (sid,))
            await db._CONN.execute("DELETE FROM stock_suppliers WHERE id = ?", (sid,))
        return True
    return await _st_tx(work)


async def stock_import_write(head: dict, suppliers: list, items: list, moves: list) -> tuple[int, list, list]:
    """Импорт одной транзакцией: документ, новые поставщики (по имени), новые
    материалы и их начальные остатки. `items[i]["supplier_key"]` — имя нового
    поставщика из `suppliers` или уже известный `supplier_id`; `moves[j]["item"]`
    — индекс в `items`. → (doc_id, ids материалов, ids поставщиков)."""
    now = _utcnow_iso()

    async def work():
        did = await _st_insert("stock_docs", _ST_DOC_COLS, head, {
            "kind": "import", "status": "inchis", "data": _st_dump(head.get("data")),
            "fingerprint": head.get("fingerprint", ""), "actor": head.get("actor", ""),
            "actor_id": head.get("actor_id", ""), "closed_at": now, "closed_by": head.get("actor", ""),
            "created_at": now})
        sup_ids: dict[str, int] = {}
        for s in suppliers:
            sup_ids[s["key"]] = await _st_insert("stock_suppliers", _ST_SUP_COLS, s,
                                              {"import_doc": did, "created_at": now})
        item_ids = []
        for it in items:
            row = dict(it)
            if row.get("supplier_key"):
                row["supplier_id"] = sup_ids.get(row["supplier_key"], row.get("supplier_id"))
            item_ids.append(await _st_insert("stock_items", _ST_ITEM_COLS, row,
                                          {"data": _st_dump(row.get("data")), "import_doc": did, "created_at": now}))
        for m in moves:
            mm = {k: v for k, v in m.items() if k != "item"}
            await _stock_move_insert({**mm, "item_id": item_ids[m["item"]], "doc_id": did}, now)
        return did, item_ids, list(sup_ids.values())
    return await _st_tx(work)


async def stock_import_doc_by_print(fingerprint: str) -> dict | None:
    rows = await _fetch("SELECT * FROM stock_docs WHERE kind = 'import' AND status = 'inchis' "
                        "AND fingerprint = ? ORDER BY id DESC", fingerprint)
    return _st_js(rows[0]) if rows else None


async def stock_import_items(doc_id: int) -> list[int]:
    return [r["id"] for r in await _fetch("SELECT id FROM stock_items WHERE import_doc = ? "
                                          "AND deleted_at IS NULL", doc_id)]


async def stock_import_suppliers(doc_id: int) -> list[int]:
    return [r["id"] for r in await _fetch("SELECT id FROM stock_suppliers WHERE import_doc = ?", doc_id)]


async def stock_import_foreign_moves(doc_id: int, item_ids: list[int]) -> int:
    """Движения материалов импорта, сделанные не самим импортом."""
    if not item_ids:
        return 0
    marks = ",".join("?" for _ in item_ids)
    return int(await _fetchval(
        f"SELECT COUNT(*) FROM stock_moves WHERE item_id IN ({marks}) AND (doc_id IS NULL OR doc_id != ?)",
        *item_ids, doc_id) or 0)


async def stock_inventory_docs_after(item_ids: list[int], after_iso: str) -> int:
    """Закрытые не раньше `after_iso` инвентаризации, в строках которых есть эти
    материалы — и с разницей, и с совпадением (пересчитали — значит сверили)."""
    if not item_ids:
        return 0
    marks = ",".join("?" for _ in item_ids)
    return int(await _fetchval(
        f"""SELECT COUNT(DISTINCT d.id) FROM stock_docs d JOIN stock_doc_lines l ON l.doc_id = d.id
            WHERE d.kind = 'inventar' AND d.status = 'inchis' AND d.closed_at >= ?
              AND l.qty_milli IS NOT NULL AND l.item_id IN ({marks})""", after_iso, *item_ids) or 0)

