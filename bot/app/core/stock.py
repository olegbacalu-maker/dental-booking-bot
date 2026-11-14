"""Склад материалов, ступень 1: правила и модели экранов.

Остаток не хранится и руками не правится: он сумма журнала `stock_moves`,
исправление — новая строка `corectie` с `fixes`. Количества — целые тысячные
единицы расхода, деньги — целые бани; минус разрешён (накладную часто вносят
позже расхода). Цена расхода — средняя по приходам с суммой на момент списания.
Цены и суммы видит и пишет только `PERM_MONEY`; без него присланная сумма
молча не принимается. Запись — `db/stock.py`, импорт файла — `core/stock_import.py`.
Ошибка ввода — `StockError(code, field, status)`: код уходит в `msg_json`.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta, timezone

from .. import db
from .. import engine as eng
from .auth import PERM_MONEY, PERM_SETTINGS, PERM_STOCK, can
from .labels import (STOCK_DOC_KIND_LABEL, STOCK_DOC_STATUS_LABEL, STOCK_KIND_LABEL, STOCK_REASON_LABEL,
                     STOCK_UNITS, TC_MODE_LABEL)

# Категории макета — подсказки; поле свободное.
CATS = ("Anestezice", "Compozite și adezive", "Endodonție", "Cimenturi", "Amprentare", "Implantologie",
        "Profilaxie", "Dezinfecție", "Consumabile diverse")
CURRENCIES = ("MDL", "EUR", "USD")

NAME_MAX, CAT_MAX, PACK_MAX, NOTE_MAX, WHY_MAX, LOT_MAX, NR_MAX = 120, 60, 60, 500, 300, 60, 40
QTY_MAX = 10 ** 9            # тысячные: миллион единиц
COST_MAX = 10 ** 10          # бани: сто миллионов лей
LINES_MAX, IDS_MAX, MOVES_LIMIT = 300, 300, 1000

_META_EXP, _META_ORDER, _META_TC = "stock_exp_days", "stock_order_days", "stock_tc_mode"
EXP_DAYS, ORDER_DAYS = 60, 7

_IN_KINDS = ("intrare", "inventar")          # приходы, из которых считается средняя
_UNDOABLE = ("consum", "casare")             # ручные списания, которые можно отменить


class StockError(ValueError):
    def __init__(self, code: str, field: str = "", status: int = 422):
        super().__init__(code)
        self.code, self.field, self.status = code, field, status


# ---------- время ----------

def today() -> date:
    return datetime.now(eng.TZ).date()


def day_start_utc(d: date) -> str:
    return datetime.combine(d, time(0), tzinfo=eng.TZ).astimezone(timezone.utc).isoformat(timespec="seconds")


def _dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(v) -> str | None:
    d = _dt(v)
    return d.isoformat(timespec="seconds") if d else None


def _local_day(v) -> date | None:
    d = _dt(v)
    return d.astimezone(eng.TZ).date() if d else None


def _d(v) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


# ---------- кто ----------

def who(me: dict | None) -> tuple[str, str]:
    me = me or {}
    return (me.get("name") or "director"), str(me.get("id") or "")


def can_map(me: dict | None) -> dict:
    return {"stock": can(me, PERM_STOCK), "money": can(me, PERM_MONEY), "settings": can(me, PERM_SETTINGS)}


def _money(me) -> bool:
    return can(me, PERM_MONEY)


def words() -> dict:
    return {"units": {u: u for u in STOCK_UNITS}, "kinds": dict(STOCK_KIND_LABEL),
            "reasons": dict(STOCK_REASON_LABEL), "doc_kinds": dict(STOCK_DOC_KIND_LABEL),
            "doc_status": dict(STOCK_DOC_STATUS_LABEL), "tc_modes": dict(TC_MODE_LABEL)}


# ---------- настройки ----------

async def prefs() -> dict:
    async def num(key, dflt, lo, hi):
        v = await db.get_meta(key)
        return int(v) if v and v.isdigit() and lo <= int(v) <= hi else dflt
    tc = await db.get_meta(_META_TC)
    return {"exp_days": await num(_META_EXP, EXP_DAYS, 1, 365),
            "order_days": await num(_META_ORDER, ORDER_DAYS, 1, 60),
            "tc_mode": tc if tc in db.STOCK_TC_MODES else "confirmare"}


async def save_prefs(body: dict) -> None:
    vals = {}
    for key, meta, lo, hi in (("exp_days", _META_EXP, 1, 365), ("order_days", _META_ORDER, 1, 60)):
        if key in body:
            vals[meta] = _int(body[key], lo, hi, key)
    if "tc_mode" in body:
        if body["tc_mode"] not in db.STOCK_TC_MODES:
            raise StockError("stock_bad", "tc_mode")
        vals[_META_TC] = body["tc_mode"]
    for meta, v in vals.items():
        await db.set_meta(meta, str(v))


# ---------- ввод ----------

def norm_name(s: str) -> str:
    """Ключ двойника: без регистра, диакритики и лишних пробелов."""
    return re.sub(r"\s+", " ", db.fold(s or "")).strip()


def _text(body: dict, key: str, mx: int, field: str = "", required: bool = False) -> str:
    v = body.get(key)
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise StockError("stock_bad", field or key)
    v = re.sub(r"\s+", " ", v).strip()
    if len(v) > mx or (required and not v):
        raise StockError("stock_bad", field or key)
    return v


def _int(v, lo: int, hi: int, field: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
        raise StockError("stock_bad", field)
    v = int(v)
    if not lo <= v <= hi:
        raise StockError("stock_bad", field)
    return v


def _opt_int(v, lo: int, hi: int, field: str) -> int | None:
    return None if v is None else _int(v, lo, hi, field)


def _bool(v, field: str) -> bool:
    if not isinstance(v, bool):
        raise StockError("stock_bad", field)
    return v


def _date_in(v, field: str, *, future: bool = True) -> str | None:
    if v in (None, ""):
        return None
    d = _d(v) if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None
    if d is None or (not future and d > today()):
        raise StockError("stock_bad", field)
    return d.isoformat()


# ---------- остаток, средняя, партии ----------

def _fix_maps(fixed: dict) -> tuple[set, dict]:
    undone = {mid for mid, fx in fixed.items() if any(f["reason"] in db.STOCK_UNDOES for f in fx)}
    sums = {mid: sum(f["cost_bani"] or 0 for f in fx if f["reason"] == "suma")
            for mid, fx in fixed.items() if any(f["reason"] == "suma" for f in fx)}
    return undone, sums


def level(moves: list, undone: set, sums: dict) -> dict:
    """Остаток, средняя цена единицы (бани за 1, не за тысячную) и партии одного
    материала по его журналу (порядок внесения). Отменённое движение и его
    отмена гасят друг друга и в партиях не участвуют."""
    qty = sum(m["qty_milli"] for m in moves)
    in_q = in_c = 0
    lots: list[dict] = []
    pool = {"lot": "", "exp_on": None, "qty_milli": 0}
    for m in moves:
        if m["id"] in undone or (m["kind"] == "corectie" and m["reason"] in db.STOCK_UNDOES):
            continue
        if m["kind"] == "corectie" and m["reason"] == "suma":
            continue
        q = m["qty_milli"]
        if q > 0 and m["kind"] in _IN_KINDS and (m["cost_bani"] is not None or m["id"] in sums):
            in_q += q
            in_c += (m["cost_bani"] or 0) + sums.get(m["id"], 0)
        if q > 0:
            lot, exp = m["lot"] or "", m["expiry"] or None
            if not lot and not exp:
                pool["qty_milli"] += q
                continue
            same = next((x for x in lots if x["lot"] == lot and x["exp_on"] == exp), None)
            if same:
                same["qty_milli"] += q
            else:
                lots.append({"lot": lot, "exp_on": exp, "qty_milli": q})
        elif q < 0:
            left = -q
            order = sorted((x for x in lots + [pool] if x["qty_milli"] > 0),
                           key=lambda x: (not (m["lot"] and x["lot"] == m["lot"]),
                                          x is pool, x["exp_on"] or "9999-12-31"))
            for x in order:
                take = min(x["qty_milli"], left)
                x["qty_milli"] -= take
                left -= take
                if not left:
                    break
    avg = round(in_c / (in_q / 1000), 2) if in_q else None
    live = [x for x in lots if x["qty_milli"] > 0]
    exp = min((x["exp_on"] for x in live if x["exp_on"]), default=None)
    return {"qty_milli": qty, "avg_bani": avg, "lots": live, "exp_on": exp}


async def levels(item_ids: list[int] | None = None) -> dict[int, dict]:
    moves = await db.stock_moves_all(item_ids)
    undone, sums = _fix_maps(await db.stock_fixed())
    by: dict[int, list] = {}
    for m in moves:
        by.setdefault(m["item_id"], []).append(m)
    ids = item_ids if item_ids is not None else list(by)
    return {i: level(by.get(i, []), undone, sums) for i in ids}


def cost_of(qty_milli: int, avg: float | None) -> int | None:
    """Стоимость количества по средней; None — средней ещё нет (приходов с суммой не было)."""
    return None if avg is None else round(qty_milli / 1000 * avg)


def buy_packs(it: dict, qty: int) -> int:
    """Предложение «De cumpărat»: довести до двух порогов целыми упаковками."""
    mn = it["min_milli"]
    if mn is None or qty >= mn:
        return 0
    return max(1, math.ceil((mn * 2 - qty) / max(1, it["pack_qty_milli"])))


def _ordered(it: dict, td: date, p: dict) -> dict | None:
    on = _local_day(it.get("ordered_at"))
    if on is None:
        return None
    days = (td - on).days
    return {"at": _iso(it["ordered_at"]), "on": on.isoformat(), "by": it.get("ordered_by") or "",
            "days": days, "late": days > p["order_days"]}


def item_row(it: dict, lv: dict, money: bool, td: date, p: dict) -> dict:
    qty = lv["qty_milli"]
    exp = _d(lv["exp_on"])
    exp_days = (exp - td).days if exp else None
    row = {
        "id": it["id"], "name": it["name"], "cat": it["category"], "unit": it["unit"],
        "pack_name": it["pack_name"], "pack_qty_milli": it["pack_qty_milli"], "min_milli": it["min_milli"],
        "costly": bool(it["costly"]), "track_expiry": bool(it["track_expiry"]), "bulk": bool(it["bulk"]),
        "supplier_id": it["supplier_id"], "supplier": it.get("supplier_name") or "",
        "active": bool(it["active"]), "note": it["note"],
        "data": {k: it["data"][k] for k in ("raft", "code", "barcodes") if k in it["data"]},
        "qty_milli": qty, "low": it["min_milli"] is not None and qty < it["min_milli"], "neg": qty < 0,
        "lots": lv["lots"], "exp_on": lv["exp_on"], "exp_days": exp_days,
        "soon": exp_days is not None and 0 <= exp_days <= p["exp_days"],
        "expired": exp_days is not None and exp_days < 0,
        "ordered": _ordered(it, td, p), "buy_packs": buy_packs(it, qty), "moves": int(it.get("moves") or 0),
    }
    if money:
        row["avg_bani"] = lv["avg_bani"]
        row["value_bani"] = cost_of(max(qty, 0), lv["avg_bani"]) or 0
    return row


async def _rows(me, td: date | None = None) -> tuple[list, dict]:
    td = td or today()
    p = await prefs()
    items = await db.stock_items()
    lv = await levels([it["id"] for it in items])
    money = _money(me)
    return [item_row(it, lv[it["id"]], money, td, p) for it in items], p


def _fresh(r: dict) -> bool:
    """Свежая отметка «Comandat»; истёкшая — строка снова обычная («n-a venit»)."""
    return bool(r["ordered"]) and not r["ordered"]["late"]


def _late(r: dict) -> bool:
    return bool(r["ordered"]) and r["ordered"]["late"]


def _counts(rows: list) -> dict:
    act = [r for r in rows if r["active"]]
    return {"all": len(act), "low": sum(r["low"] for r in act), "neg": sum(r["neg"] for r in act),
            "soon": sum(r["soon"] for r in act), "expired": sum(r["expired"] for r in act),
            "ordered": sum(_fresh(r) for r in act), "late": sum(_late(r) for r in act),
            "archive": len(rows) - len(act),
            "bulk": sum(r["bulk"] for r in act)}


def supplier_out(s: dict) -> dict:
    return {"id": s["id"], "name": s["name"], "idno": s["idno"], "phone": s["phone"], "email": s["email"],
            "note": s["note"], "active": bool(s["active"]), "items": int(s.get("items") or 0),
            "docs": int(s.get("docs") or 0)}


# ---------- модели экранов ----------

async def main_model(me) -> dict:
    td = today()
    rows, p = await _rows(me, td)
    cats = list(CATS) + sorted({r["cat"] for r in rows if r["cat"] and r["cat"] not in CATS}, key=str.casefold)
    drafts = {"factura": 0, "inventar": 0}
    for d in await db.stock_docs(status="ciorna"):
        if d["kind"] in drafts:
            drafts[d["kind"]] += 1
    return {"today": td.isoformat(), "prefs": p, "words": words(), "cats": cats, "counts": _counts(rows),
            "items": rows, "suppliers": [supplier_out(s) for s in await db.stock_suppliers()],
            "drafts": drafts, "can": can_map(me)}


def _fisa(r: dict) -> str | None:
    if r.get("patient_id") is None:
        return None
    return (r.get("file_no") or "").strip() or str(r["patient_id"])


def move_out(m: dict, money: bool, undone: set, done_by_fix: set, td: date | None = None) -> dict:
    on = _local_day(m["at"])
    row = {
        "id": m["id"], "at": _iso(m["at"]), "on": on.isoformat() if on else None,
        "kind": m["kind"], "kind_label": STOCK_KIND_LABEL.get(m["kind"], m["kind"]),
        "item_id": m["item_id"], "item": m["item_name"], "unit": m.get("unit") or "",
        "qty_milli": m["qty_milli"],
        "doc": ({"id": m["doc_id"], "kind": m.get("doc_kind") or "", "nr": m.get("doc_nr") or "",
                 "supplier": m.get("doc_supplier") or m.get("supplier") or ""} if m["doc_id"] else None),
        "lot": m["lot"], "exp_on": m["expiry"],
        "pid": m["patient_id"], "patient": m.get("patient") if m["patient_id"] is not None else None,
        "fisa": _fisa(m),
        "reason": m["reason"], "reason_label": STOCK_REASON_LABEL.get(m["reason"], ""),
        "note": m["note"], "actor": m["actor"], "source": m["source"], "fixes": m["fixes"],
        "undone": m["id"] in undone,
        "undoable": (m["kind"] in _UNDOABLE and m["doc_id"] is None and m["source"] == "manual"
                     and m["id"] not in done_by_fix),
    }
    if money:
        row["cost_bani"] = m["cost_bani"]
    return row


async def _fix_sets() -> tuple[set, set]:
    fixed = await db.stock_fixed()
    undone, _ = _fix_maps(fixed)
    return undone, set(fixed)


async def item_model(me, item_id: int) -> dict:
    it = await db.stock_item(item_id)
    if it is None:
        raise StockError("stock_item_gone", status=404)
    td, p, money = today(), await prefs(), _money(me)
    lv = (await levels([item_id]))[item_id]
    undone, fixed = await _fix_sets()
    moves = await db.stock_moves_query(item=item_id, limit=30)
    out = {"item": item_row(it, lv, money, td, p),
           "moves": [move_out(m, money, undone, fixed) for m in moves], "can": can_map(me)}
    if money:
        prices, fixmap = [], await db.stock_fixed()
        for m in await db.stock_moves_query(item=item_id, kind="intrare", limit=200):
            if m["id"] in undone or m["qty_milli"] <= 0:
                continue
            cost = m["cost_bani"]
            extra = sum(f["cost_bani"] or 0 for f in fixmap.get(m["id"], []) if f["reason"] == "suma")
            if cost is None and not extra:
                continue
            cost = (cost or 0) + extra
            on = _local_day(m["at"])
            prices.append({"on": on.isoformat() if on else None, "nr": m.get("doc_nr") or "",
                           "supplier": m.get("doc_supplier") or m["supplier"], "qty_milli": m["qty_milli"],
                           "cost_bani": cost, "unit_bani": round(cost / (m["qty_milli"] / 1000), 2)})
            if len(prices) >= 20:
                break
        out["prices"] = prices
    return out


async def moves_model(me, q: dict) -> dict:
    def num(key):
        v = str(q.get(key) or "")
        return int(v) if v.isdigit() else None
    since = until = ""
    if (f := _d(q.get("from"))) is not None:
        since = day_start_utc(f)
    if (t := _d(q.get("to"))) is not None:
        until = day_start_utc(t + timedelta(days=1))
    kind = q.get("kind") or ""
    if kind and kind not in db.STOCK_KINDS:
        raise StockError("stock_bad", "kind")
    limit = min(num("limit") or 300, MOVES_LIMIT)
    rows = await db.stock_moves_query(item=num("item"), kind=kind, since_utc=since, until_utc=until,
                                      actor=q.get("actor") or "", supplier=num("supplier"), pid=num("pid"),
                                      limit=limit + 1)
    undone, fixed = await _fix_sets()
    money = _money(me)
    return {"moves": [move_out(m, money, undone, fixed) for m in rows[:limit]], "more": len(rows) > limit,
            "actors": await db.stock_actors(), "can": can_map(me)}


async def _storno_ok(d: dict) -> bool:
    if d["kind"] != "factura" or d["status"] != "inchis":
        return False
    items = [ln["item_id"] for ln in await db.stock_doc_lines(d["id"])]
    return not await db.stock_inventory_docs_after(items, d["closed_at"] or "")


async def doc_row(d: dict, me) -> dict:
    row = {"id": d["id"], "kind": d["kind"], "kind_label": STOCK_DOC_KIND_LABEL.get(d["kind"], d["kind"]),
           "nr": d["nr"], "doc_date": d["doc_date"], "supplier_id": d["supplier_id"], "supplier": d["supplier"],
           "status": d["status"], "status_label": STOCK_DOC_STATUS_LABEL.get(d["status"], d["status"]),
           "no_sums": bool(d["no_sums"]), "lines": int(d.get("lines") or 0), "actor": d["actor"],
           "created_at": _iso(d["created_at"]), "closed_at": _iso(d["closed_at"]), "note": d["note"],
           "can_storno": _money(me) and await _storno_ok(d)}
    if _money(me):
        row["total_bani"] = d.get("lines_bani") if d.get("lines_bani") is not None else d["total_bani"]
    return row


async def docs_model(me, kind: str = "", status: str = "") -> dict:
    if kind and kind not in db.STOCK_DOC_KINDS:
        raise StockError("stock_bad", "kind")
    if status and status not in db.STOCK_DOC_OPEN + db.STOCK_DOC_CLOSED:
        raise StockError("stock_bad", "status")
    return {"docs": [await doc_row(d, me) for d in await db.stock_docs(kind, status)], "can": can_map(me)}


async def _doc(doc_id: int) -> dict:
    d = await db.stock_doc(doc_id)
    if d is None:
        raise StockError("stock_doc_gone", status=404)
    return d


async def doc_model(me, doc_id: int) -> dict:
    d = await _doc(doc_id)
    rows = await db.stock_docs()
    d = next((x for x in rows if x["id"] == doc_id), d)
    lines = await db.stock_doc_lines(doc_id)
    money = _money(me)
    lv = await levels(list({ln["item_id"] for ln in lines}))
    out_lines = []
    for ln in lines:
        x = {"id": ln["id"], "item_id": ln["item_id"], "item": ln["item_name"] or "", "unit": ln["unit"] or "",
             "pack_qty_milli": ln["pack_qty_milli"], "qty_milli": ln["qty_milli"], "lot": ln["lot"],
             "exp_on": ln["expiry"], "note": ln["note"]}
        if d["kind"] == "inventar":
            prog = ln["prog_milli"] if d["status"] != "ciorna" else lv[ln["item_id"]]["qty_milli"]
            x["prog_milli"] = prog
            x["diff_milli"] = None if ln["qty_milli"] is None or prog is None else ln["qty_milli"] - prog
        if money and d["kind"] == "factura":
            x["cost_bani"] = ln["cost_bani"]
            if ln["cost_bani"] is not None and ln["qty_milli"]:
                x["unit_bani"] = round(ln["cost_bani"] / (ln["qty_milli"] / 1000), 2)
            x["avg_bani"] = lv[ln["item_id"]]["avg_bani"]
        out_lines.append(x)
    row = await doc_row(d, me)
    row.update(cur=d["cur"], cur_amount=d["cur_amount"], rate=d["rate"], lines=out_lines)
    return {"doc": row, "can": can_map(me)}


async def buy_model(me) -> dict:
    td = today()
    rows, p = await _rows(me, td)
    sups = {s["id"]: s for s in await db.stock_suppliers()}
    money = _money(me)
    groups: dict = {}
    counts = {"low": 0, "ordered": 0, "late": 0}
    for r in rows:
        if not (r["active"] and r["low"]):
            continue
        counts["low"] += 1
        counts["ordered"] += _fresh(r)
        counts["late"] += _late(r)
        s = sups.get(r["supplier_id"])
        g = groups.setdefault(r["supplier_id"] if s else None, {
            "supplier_id": s["id"] if s else None, "supplier": s["name"] if s else "Fără furnizor",
            "phone": s["phone"] if s else "", "email": s["email"] if s else "", "rows": []})
        b = {"item_id": r["id"], "name": r["name"], "unit": r["unit"], "pack_name": r["pack_name"],
             "pack_qty_milli": r["pack_qty_milli"], "qty_milli": r["qty_milli"], "min_milli": r["min_milli"],
             "neg": r["neg"], "buy_packs": r["buy_packs"], "ordered": r["ordered"]}
        if money:
            b["est_bani"] = cost_of(r["buy_packs"] * r["pack_qty_milli"], r.get("avg_bani"))
        g["rows"].append(b)
    out = sorted(groups.values(), key=lambda g: (g["supplier_id"] is None, g["supplier"].casefold()))
    for g in out:
        g["rows"].sort(key=lambda b: b["name"].casefold())
    return {"today": td.isoformat(), "prefs": p, "groups": out, "counts": counts, "can": can_map(me)}


async def patient_model(pid: int) -> dict:
    if not await db.get_patient(pid):
        raise StockError("stock_patient_gone", status=404)
    undone, _ = await _fix_sets()
    rows = []
    for m in await db.stock_moves_patient(pid):
        if m["kind"] != "consum":
            continue
        on = _local_day(m["at"])
        rows.append({"id": m["id"], "at": _iso(m["at"]), "on": on.isoformat() if on else None,
                     "item": m["item_name"], "unit": m.get("unit") or "", "qty_milli": -m["qty_milli"],
                     "lot": m["lot"], "exp_on": m["expiry"], "note": m["note"], "actor": m["actor"],
                     "undone": m["id"] in undone, "plan_item_id": m["plan_item_id"], "source": m["source"]})
    return {"rows": rows}


async def dash_model(me, td: date) -> dict | None:
    """Плашка главной в конверте живого канала. Только от дня `td`, ни одного
    «сейчас»: отпечаток канала стоит весь день при тех же данных. Без права
    склада и при пустом складе — None (плашки нет)."""
    if me is not None and not can(me, PERM_STOCK):
        return None
    rows, _ = await _rows(me, td)
    act = [r for r in rows if r["active"]]
    if not act:
        return None
    low = sorted((r for r in act if r["low"]),
                 key=lambda r: (r["qty_milli"] - r["min_milli"]) / max(1, r["min_milli"]))
    exp = sorted((r for r in act if r["soon"] or r["expired"]), key=lambda r: r["exp_days"])
    if not low and not exp:
        return None
    return {"low": len(low), "neg": sum(r["neg"] for r in act), "ordered": sum(_fresh(r) for r in low),
            "late": sum(_late(r) for r in low),
            "soon": sum(r["soon"] for r in act), "expired": sum(r["expired"] for r in act),
            "low_items": [{"id": r["id"], "name": r["name"]} for r in low[:3]],
            "exp_items": [{"id": r["id"], "name": r["name"], "exp_on": r["exp_on"], "days": r["exp_days"]}
                          for r in exp[:3]]}


# ---------- материалы и поставщики ----------

async def _dup_item(name: str, skip: int | None) -> bool:
    key = norm_name(name)
    return any(norm_name(x["name"]) == key and x["id"] != skip for x in await db.stock_items())


async def save_item(me, body: dict) -> int:
    old = None
    if body.get("id") is not None:
        old = await db.stock_item(_int(body["id"], 1, 2 ** 62, "id"))
        if old is None:
            raise StockError("stock_item_gone", status=404)
    it = dict(old or {"name": "", "category": "", "unit": "", "pack_name": "", "pack_qty_milli": 1000,
                      "min_milli": None, "costly": 0, "track_expiry": 0, "bulk": 0, "supplier_id": None,
                      "note": "", "active": 1, "sort": 0, "data": {}})
    if old is None or "name" in body:
        it["name"] = _text(body, "name", NAME_MAX, required=True)
        if await _dup_item(it["name"], old["id"] if old else None):
            raise StockError("stock_dup", "name", 409)
    if "cat" in body:
        it["category"] = _text(body, "cat", CAT_MAX)
    if old is None or "unit" in body:
        unit = body.get("unit")
        if unit not in STOCK_UNITS:
            raise StockError("stock_bad", "unit")
        if old is not None and unit != old["unit"] and old["moves"]:
            raise StockError("stock_unit_locked", "unit", 409)
        it["unit"] = unit
    if "pack_name" in body:
        it["pack_name"] = _text(body, "pack_name", PACK_MAX)
    if "pack_qty_milli" in body:
        it["pack_qty_milli"] = _int(body["pack_qty_milli"], 1, QTY_MAX, "pack_qty_milli")
    if "min_milli" in body:
        it["min_milli"] = _opt_int(body["min_milli"], 0, QTY_MAX, "min_milli")
    for key, col in (("costly", "costly"), ("track_expiry", "track_expiry"), ("bulk", "bulk"),
                     ("active", "active")):
        if key in body:
            it[col] = int(_bool(body[key], key))
    if "supplier_id" in body:
        sid = _opt_int(body["supplier_id"], 1, 2 ** 62, "supplier_id")
        if sid is not None and not await db.stock_supplier(sid):
            raise StockError("stock_bad", "supplier_id")
        it["supplier_id"] = sid
    if "note" in body:
        it["note"] = _text(body, "note", NOTE_MAX)
    if "data" in body:
        it["data"] = _data_in(body["data"], it.get("data") or {})
    first = None
    if old is None and body.get("shelf_milli") not in (None, 0):
        shelf = _int(body["shelf_milli"], -QTY_MAX, QTY_MAX, "shelf_milli")
        actor, aid = who(me)
        first = {"kind": "inventar", "item_name": it["name"], "qty_milli": shelf, "cost_bani": None,
                 "note": "rest inițial", "actor": actor, "actor_id": aid}
    return await db.stock_item_save(it, first)


def _data_in(v, old: dict) -> dict:
    if not isinstance(v, dict):
        raise StockError("stock_bad", "data")
    out = dict(old)
    for key in ("raft", "code"):
        if key in v:
            out[key] = _text(v, key, PACK_MAX, f"data.{key}")
    if "barcodes" in v:
        bc = v["barcodes"]
        if not isinstance(bc, list) or len(bc) > 10 or not all(isinstance(x, str) and len(x) <= 60 for x in bc):
            raise StockError("stock_bad", "data.barcodes")
        out["barcodes"] = [x.strip() for x in bc if x.strip()]
    return out


async def delete_item(me, item_id: int) -> None:
    it = await db.stock_item(item_id)
    if it is None:
        raise StockError("stock_item_gone", status=404)
    if not await db.stock_item_delete(item_id, who(me)[0]):
        raise StockError("stock_has_moves", status=409)


async def save_supplier(body: dict) -> int:
    old = None
    if body.get("id") is not None:
        old = await db.stock_supplier(_int(body["id"], 1, 2 ** 62, "id"))
        if old is None:
            raise StockError("stock_supplier_gone", status=404)
    s = dict(old or {"name": "", "idno": "", "phone": "", "email": "", "note": "", "active": 1})
    if old is None or "name" in body:
        s["name"] = _text(body, "name", NAME_MAX, required=True)
        key = norm_name(s["name"])
        if any(norm_name(x["name"]) == key and x["id"] != (old or {}).get("id")
               for x in await db.stock_suppliers()):
            raise StockError("stock_dup", "name", 409)
    if "idno" in body:
        s["idno"] = _text(body, "idno", 13)
        if s["idno"] and not re.fullmatch(r"\d{13}", s["idno"]):
            raise StockError("stock_bad", "idno")
    if "phone" in body:
        s["phone"] = _text(body, "phone", 40)
    if "email" in body:
        s["email"] = _text(body, "email", 120)
        if s["email"] and "@" not in s["email"]:
            raise StockError("stock_bad", "email")
    if "note" in body:
        s["note"] = _text(body, "note", NOTE_MAX)
    if "active" in body:
        s["active"] = int(_bool(body["active"], "active"))
    return await db.stock_supplier_save(s)


async def delete_supplier(sid: int) -> None:
    if not await db.stock_supplier(sid):
        raise StockError("stock_supplier_gone", status=404)
    if not await db.stock_supplier_delete(sid):
        raise StockError("stock_supplier_used", status=409)


async def _supplier_by_name(name: str) -> dict | None:
    key = norm_name(name)
    return next((s for s in await db.stock_suppliers() if norm_name(s["name"]) == key), None)


# ---------- списание ----------

async def _live_item(item_id) -> dict:
    iid = _int(item_id, 1, 2 ** 62, "item_id")
    it = await db.stock_item(iid)
    if it is None:
        raise StockError("stock_item_gone", status=404)
    if not it["active"]:
        raise StockError("stock_item_off", status=409)
    return it


async def take_out(me, body: dict) -> dict:
    it = await _live_item(body.get("item_id"))
    qty = _int(body.get("qty_milli"), 1, QTY_MAX, "qty_milli")
    reason = body.get("reason")
    if reason not in db.STOCK_OUT_REASONS:
        raise StockError("stock_bad", "reason")
    note = _text(body, "note", WHY_MAX, required=reason == "altul")
    lot = _text(body, "lot", LOT_MAX)
    pid = appt = None
    if reason == "pacient":
        if body.get("pid") is None:
            raise StockError("stock_bad", "pid")
        pid = _int(body["pid"], 1, 2 ** 62, "pid")
        if not await db.get_patient(pid):
            raise StockError("stock_patient_gone", "pid", 404)
        if body.get("appointment_id") is not None:
            appt = _int(body["appointment_id"], 1, 2 ** 62, "appointment_id")
            if await db.lab_appt_patient(appt) != pid:
                raise StockError("stock_bad", "appointment_id")
    return await _out(me, it, qty, reason, note=note, lot=lot, pid=pid, appt=appt)


async def _out(me, it: dict, qty: int, reason: str, *, note: str = "", lot: str = "",
               pid: int | None = None, appt: int | None = None) -> dict:
    lv = (await levels([it["id"]]))[it["id"]]
    actor, aid = who(me)
    expiry = next((x["exp_on"] for x in lv["lots"] if lot and x["lot"] == lot), None)
    cost = cost_of(qty, lv["avg_bani"])
    mid = await db.stock_move_add({
        "kind": "consum" if reason == "pacient" else "casare", "item_id": it["id"], "item_name": it["name"],
        "qty_milli": -qty, "cost_bani": None if cost is None else -cost, "lot": lot, "expiry": expiry,
        "patient_id": pid, "appointment_id": appt, "reason": reason, "note": note,
        "actor": actor, "actor_id": aid})
    if pid is not None:
        await db.log_event(pid, "stock", _short(
            f"Material: {it['name']} — {fmt_qty(qty)} {it['unit']}" + (f", lot {lot}" if lot else "")),
            actor=actor)
    left = lv["qty_milli"] - qty
    return {"id": mid, "qty_milli": left, "neg": left < 0}


async def open_pack(me, body: dict) -> dict:
    it = await _live_item(body.get("item_id"))
    return await _out(me, it, it["pack_qty_milli"], "deschis")


async def undo_move(me, mid: int, body: dict) -> None:
    m = await db.stock_move(mid)
    if m is None:
        raise StockError("stock_move_gone", status=404)
    why = _text(body, "why", WHY_MAX)
    if (m["kind"] not in _UNDOABLE or m["doc_id"] is not None or m["source"] != "manual"
            or mid in await db.stock_fixed()):
        raise StockError("stock_no_undo", status=409)
    actor, aid = who(me)
    await db.stock_move_add({
        "kind": "corectie", "item_id": m["item_id"], "item_name": m["item_name"], "qty_milli": -m["qty_milli"],
        "cost_bani": None if m["cost_bani"] is None else -m["cost_bani"], "lot": m["lot"], "expiry": m["expiry"],
        "patient_id": m["patient_id"], "appointment_id": m["appointment_id"], "reason": "anulare",
        "note": "", "fixes": mid, "why": why, "actor": actor, "actor_id": aid})
    if m["patient_id"] is not None:
        await db.log_event(m["patient_id"], "stock", _short(f"Material anulat: {m['item_name']}"), actor=actor)


def fmt_qty(milli: int) -> str:
    v = milli / 1000
    return (f"{v:.3f}".rstrip("0").rstrip(".")).replace(".", ",")


def _short(s: str, n: int = 190) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------- документы ----------

async def _lines_in(raw, kind: str, money: bool, old: dict[int, dict]) -> list:
    if not isinstance(raw, list) or len(raw) > LINES_MAX:
        raise StockError("stock_bad", "lines")
    out, seen = [], set()
    items = {it["id"]: it for it in await db.stock_items()}
    for x in raw:
        if not isinstance(x, dict):
            raise StockError("stock_bad", "lines")
        lid = x.get("id")
        if lid is not None and (not isinstance(lid, int) or lid not in old):
            raise StockError("stock_bad", "lines")
        iid = x.get("item_id")
        if not isinstance(iid, int) or iid not in items:
            raise StockError("stock_bad", "lines")
        if not items[iid]["active"] and (lid is None or old[lid]["item_id"] != iid):
            raise StockError("stock_item_off", "lines", 409)
        if kind == "inventar":
            if iid in seen:
                raise StockError("stock_bad", "lines")
            seen.add(iid)
        qty = _opt_int(x.get("qty_milli"), 0, QTY_MAX, "lines")
        line = {"id": lid, "item_id": iid, "qty_milli": qty, "prog_milli": None,
                "lot": _text(x, "lot", LOT_MAX, "lines"), "expiry": _date_in(x.get("exp_on"), "lines"),
                "note": _text(x, "note", WHY_MAX, "lines"), "cost_bani": None}
        if kind == "factura":
            if money and "cost_bani" in x:
                line["cost_bani"] = _opt_int(x["cost_bani"], 0, COST_MAX, "lines")
            elif lid is not None:
                line["cost_bani"] = old[lid]["cost_bani"]
        out.append(line)
    return out


async def _head_in(body: dict, head: dict) -> dict | None:
    """Поля шапки (нет поля — не менять) и новый поставщик, если назван именем."""
    new_sup = None
    if "nr" in body:
        head["nr"] = _text(body, "nr", NR_MAX)
    if "doc_date" in body:
        head["doc_date"] = _date_in(body["doc_date"], "doc_date", future=False) or today().isoformat()
    if "note" in body:
        head["note"] = _text(body, "note", WHY_MAX)
    if "cur" in body:
        cur = body["cur"] or ""
        if cur not in CURRENCIES + ("",):
            raise StockError("stock_bad", "cur")
        head["cur"] = cur
    if "cur_amount" in body:
        head["cur_amount"] = _opt_int(body["cur_amount"], 0, COST_MAX, "cur_amount")
    if "rate" in body:
        head["rate"] = _text(body, "rate", 20)
    if body.get("supplier_id") is not None:
        s = await db.stock_supplier(_int(body["supplier_id"], 1, 2 ** 62, "supplier_id"))
        if s is None:
            raise StockError("stock_bad", "supplier_id")
        head["supplier_id"], head["supplier"] = s["id"], s["name"]
    elif "supplier_name" in body and (name := _text(body, "supplier_name", NAME_MAX)):
        s = await _supplier_by_name(name)
        if s:
            head["supplier_id"], head["supplier"] = s["id"], s["name"]
        else:
            idno = _text(body, "supplier_idno", 13)
            if idno and not re.fullmatch(r"\d{13}", idno):
                raise StockError("stock_bad", "supplier_idno")
            new_sup = {"name": name, "idno": idno, "phone": "", "email": "", "note": "", "active": 1}
            head["supplier"] = name
    elif "supplier_id" in body:
        head["supplier_id"], head["supplier"] = None, ""
    return new_sup


async def create_doc(me, body: dict) -> int:
    kind = body.get("kind")
    if kind not in ("factura", "inventar"):
        raise StockError("stock_bad", "kind")
    actor, aid = who(me)
    head = {"kind": kind, "nr": "", "doc_date": today().isoformat(), "supplier_id": None, "supplier": "",
            "note": "", "cur": "", "cur_amount": None, "rate": "", "actor": actor, "actor_id": aid}
    new_sup = await _head_in(body, head)
    if kind == "inventar" and "lines" not in body:
        cats = body.get("cats") or []
        if not isinstance(cats, list) or not all(isinstance(c, str) for c in cats):
            raise StockError("stock_bad", "cats")
        want = {norm_name(c) for c in cats}
        lines = [{"item_id": it["id"], "qty_milli": None, "prog_milli": None, "cost_bani": None, "lot": "",
                  "expiry": None, "note": ""}
                 for it in await db.stock_items() if it["active"]
                 and (not want or norm_name(it["category"]) in want)]
    else:
        lines = await _lines_in(body.get("lines") or [], kind, _money(me), {})
    return await db.stock_doc_create(head, lines, new_sup)


async def edit_doc(me, doc_id: int, body: dict) -> None:
    d = await _doc(doc_id)
    if d["status"] != "ciorna":
        raise StockError("stock_doc_closed", status=409)
    head: dict = {}
    new_sup = await _head_in(body, head)
    lines = None
    if "lines" in body:
        old = {ln["id"]: ln for ln in await db.stock_doc_lines(doc_id)}
        lines = await _lines_in(body["lines"], d["kind"], _money(me), old)
    if not await db.stock_doc_write(doc_id, head, lines, new_sup):
        raise StockError("stock_doc_closed", status=409)


async def delete_doc(doc_id: int) -> None:
    await _doc(doc_id)
    if not await db.stock_doc_delete(doc_id):
        raise StockError("stock_doc_closed", status=409)


async def close_doc(me, doc_id: int) -> str:
    d = await _doc(doc_id)
    if d["status"] != "ciorna":
        raise StockError("stock_doc_closed", status=409)
    lines = await db.stock_doc_lines(doc_id)
    actor, aid = who(me)
    at = None
    if d["doc_date"] and d["doc_date"] < today().isoformat():
        # приход по смыслу случился в день накладной, внесён — сейчас
        at = datetime.combine(_d(d["doc_date"]), time(12), tzinfo=eng.TZ).astimezone(
            timezone.utc).isoformat(timespec="seconds")
    moves, prog = [], {}
    base = {"actor": actor, "actor_id": aid, "supplier": d["supplier"]}
    if d["kind"] == "factura":
        for ln in lines:
            if not ln["qty_milli"]:
                continue
            moves.append({**base, "at": at, "kind": "intrare", "item_id": ln["item_id"],
                          "item_name": ln["item_name"], "qty_milli": ln["qty_milli"], "cost_bani": ln["cost_bani"],
                          "line_id": ln["id"], "lot": ln["lot"], "expiry": ln["expiry"], "note": ln["note"]})
        if not moves:
            raise StockError("stock_empty")
        priced = [m["cost_bani"] for m in moves if m["cost_bani"] is not None]
        ok = await db.stock_doc_close(doc_id, moves, by=actor, no_sums=len(priced) < len(moves),
                                      total=sum(priced) if priced else None,
                                      unorder=sorted({m["item_id"] for m in moves}))
        code = "ok_stock_invoice"
    else:
        lv = await levels(list({ln["item_id"] for ln in lines}))
        for ln in lines:
            if ln["qty_milli"] is None:
                continue
            cur = lv[ln["item_id"]]
            prog[ln["id"]] = cur["qty_milli"]
            diff = ln["qty_milli"] - cur["qty_milli"]
            if not diff:
                continue
            moves.append({**base, "supplier": "", "kind": "inventar", "item_id": ln["item_id"],
                          "item_name": ln["item_name"], "qty_milli": diff,
                          "cost_bani": cost_of(diff, cur["avg_bani"]), "line_id": ln["id"],
                          "note": "pe raft mai mult" if diff > 0 else "pe raft mai puțin"})
        if not prog:
            raise StockError("stock_empty")
        ok = await db.stock_doc_close(doc_id, moves, by=actor, no_sums=False, total=None, prog=prog)
        code = "ok_stock_inventory"
    if not ok:
        raise StockError("stock_doc_closed", status=409)
    return code


async def doc_sums(me, doc_id: int, body: dict) -> None:
    d = await _doc(doc_id)
    if d["kind"] != "factura" or d["status"] != "inchis":
        raise StockError("stock_doc_closed", status=409)
    raw = body.get("lines")
    if not isinstance(raw, list) or not raw:
        raise StockError("stock_bad", "lines")
    lines = {ln["id"]: ln for ln in await db.stock_doc_lines(doc_id)}
    moves = {m["line_id"]: m for m in await db.stock_moves_query(doc=doc_id, limit=LINES_MAX * 4)
             if m["kind"] == "intrare"}
    costs, fix = {}, []
    actor, aid = who(me)
    for x in raw:
        if not isinstance(x, dict) or x.get("id") not in lines:
            raise StockError("stock_bad", "lines")
        v = _int(x.get("cost_bani"), 0, COST_MAX, "lines")
        ln, m = lines[x["id"]], moves.get(x["id"])
        if m is None or v == ln["cost_bani"]:
            continue
        costs[ln["id"]] = v
        fix.append({"kind": "corectie", "item_id": ln["item_id"], "item_name": m["item_name"], "qty_milli": 0,
                    "cost_bani": v - (ln["cost_bani"] or 0), "line_id": ln["id"], "reason": "suma",
                    "fixes": m["id"], "supplier": d["supplier"], "actor": actor, "actor_id": aid})
    if not fix:
        return
    after = {i: costs.get(i, ln["cost_bani"]) for i, ln in lines.items() if i in moves}
    priced = [v for v in after.values() if v is not None]
    await db.stock_doc_sums(doc_id, costs, fix, no_sums=len(priced) < len(after),
                            total=sum(priced) if priced else None)


async def storno_doc(me, doc_id: int, body: dict) -> None:
    d = await _doc(doc_id)
    why = _text(body, "why", WHY_MAX, required=True)
    if d["kind"] != "factura" or d["status"] != "inchis":
        raise StockError("stock_doc_closed", status=409)
    if not await _storno_ok(d):
        raise StockError("stock_inv_after", status=409)
    actor, aid = who(me)
    rev, fixmap = [], await db.stock_fixed()
    for m in await db.stock_moves_query(doc=doc_id, limit=LINES_MAX * 4):
        if m["kind"] != "intrare":
            continue
        cost = m["cost_bani"]
        extra = sum(f["cost_bani"] or 0 for f in fixmap.get(m["id"], []) if f["reason"] == "suma")
        total = None if cost is None and not extra else (cost or 0) + extra
        rev.append({"kind": "corectie", "item_id": m["item_id"], "item_name": m["item_name"],
                    "qty_milli": -m["qty_milli"], "cost_bani": None if total is None else -total,
                    "line_id": m["line_id"], "lot": m["lot"], "expiry": m["expiry"], "reason": "storno",
                    "fixes": m["id"], "why": why, "supplier": d["supplier"], "actor": actor, "actor_id": aid})
    if not await db.stock_doc_undo(doc_id, rev, by=actor, why=why):
        raise StockError("stock_doc_closed", status=409)


# ---------- «Comandat» ----------

async def order(me, body: dict) -> None:
    ids = body.get("ids")
    if (not isinstance(ids, list) or not ids or len(ids) > IDS_MAX
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
        raise StockError("stock_bad", "ids")
    known = {it["id"] for it in await db.stock_items()}
    if not set(ids) <= known:
        raise StockError("stock_item_gone", "ids", 404)
    await db.stock_order_mark(sorted(set(ids)), who(me)[0])


async def unorder(item_id: int) -> None:
    if not await db.stock_item(item_id):
        raise StockError("stock_item_gone", status=404)
    await db.stock_order_clear(item_id)


# ---------- лист «De cumpărat» ----------

def parse_pick(q: str) -> dict[int, int] | None:
    """`q=12:3,15:1` — материал:упаковок, отмеченное на экране. None — весь список."""
    if not q:
        return None
    out = {}
    for part in q.split(","):
        m = re.fullmatch(r"\s*(\d{1,12}):(\d{1,6})\s*", part)
        if m:
            out[int(m[1])] = int(m[2])
    return out


async def buy_sheet(me, pick: dict[int, int] | None) -> dict:
    model = await buy_model(me)
    groups = []
    for g in model["groups"]:
        rows = []
        for r in g["rows"]:
            if pick is not None:
                if r["item_id"] not in pick:
                    continue
                r = {**r, "buy_packs": pick[r["item_id"]]}
                if "est_bani" in r:
                    r["est_bani"] = None
            rows.append(r)
        if rows:
            groups.append({**g, "rows": rows})
    return {"today": model["today"], "groups": groups, "money": _money(me), "clinic": eng.CLINIC_NAME}


# ---------- Excel движений за месяц ----------

def month_bounds(month: str) -> tuple[date, date] | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})", month or "")
    if not m or not 1 <= int(m[2]) <= 12:
        return None
    a = date(int(m[1]), int(m[2]), 1)
    b = date(a.year + (a.month == 12), a.month % 12 + 1, 1)
    return a, b


async def month_rows(me, a: date, b: date) -> tuple[list, list, list]:
    """Шапка, строки, ширины. Пациента нет: бухгалтеру он не нужен (закон 195)."""
    money = _money(me)
    head = ["Data", "Tip", "Document", "Furnizor", "Material", "Unitatea", "Cantitatea", "Lot",
            "Valabil până la", "Motivul", "Notă", "Cine"]
    widths = [11, 14, 18, 24, 34, 9, 11, 14, 13, 18, 30, 16]
    if money:
        head.append("Suma, lei")
        widths.append(12)
    rows = []
    for m in await db.stock_moves_range(day_start_utc(a), day_start_utc(b)):
        on = _local_day(m["at"])
        doc = ""
        if m["doc_id"]:
            doc = f"{STOCK_DOC_KIND_LABEL.get(m['doc_kind'] or '', '')} {m['doc_nr'] or ''}".strip()
        reason = STOCK_REASON_LABEL.get(m["reason"], "")
        row = [on or "", STOCK_KIND_LABEL.get(m["kind"], m["kind"]), doc,
               m["supplier"], m["item_name"], m.get("unit") or "", m["qty_milli"] / 1000, m["lot"],
               _d(m["expiry"]) or "", reason, m["note"], m["actor"]]
        if money:
            row.append(None if m["cost_bani"] is None else m["cost_bani"] / 100)
        rows.append(row)
    return head, rows, widths


# ---------- закон 195: копия данных пациента ----------

async def export_rows(pid: int) -> list:
    """Материалы, ушедшие пациенту, словами — та же таблица держит фишу от
    физического стирания."""
    undone, _ = await _fix_sets()
    out = []
    for m in reversed(await db.stock_moves_patient(pid)):
        on = _local_day(m["at"])
        out.append({"data": on.isoformat() if on else None,
                    "tip": STOCK_KIND_LABEL.get(m["kind"], m["kind"]), "material": m["item_name"],
                    "cantitate": fmt_qty(-m["qty_milli"]), "unitate": m.get("unit") or "", "lot": m["lot"],
                    "valabil": m["expiry"], "nota": m["note"], "cine": m["actor"],
                    "anulat": m["id"] in undone or m["kind"] == "corectie"})
    return out
