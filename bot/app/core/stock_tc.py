"""Склад, ступень 2: техкарта услуги и списание материалов по позиции плана.

Техкарта живёт в базе (`service_materials`), а не в `clinic.json`: строка
ссылается на id материала, а «Setări › Servicii» переписывает `clinic.json`
целиком. Позиция плана берёт техкарту по `plan_items.service_id`; списание —
строки `consum` с `plan_item_id` и `source='tehcard'`. На позицию — ровно один
живой набор: повторный `finalizat` не списывает дважды, «Redeschide»
сторнирует (журнал не правится). Режим клиники — `fara` / `confirmare` /
`automat` в `schema_meta`.
"""
from __future__ import annotations

from datetime import timedelta

from .. import db
from .. import engine as eng
from . import stock as cs
from .auth import PERM_MONEY, can
from .labels import TC_MODE_LABEL

LINES_MAX = 40
REPORT_BY = ("doctor", "service", "patient", "item")


# ---------- режим ----------

async def mode() -> str:
    return (await cs.prefs())["tc_mode"]


def words() -> dict:
    return dict(TC_MODE_LABEL)


# ---------- техкарта ----------

def service_name(sid: str | None) -> str:
    svc = eng.SERVICES.get(sid or "")
    return (svc.get("ro") or sid) if svc else ""


def _line_out(r: dict) -> dict:
    return {"item_id": r["item_id"], "item": r["item_name"] or "", "unit": r["unit"] or "",
            "qty_milli": r["qty_milli"], "optional": bool(r["optional"]),
            "active": bool(r["item_active"]) and r["item_deleted"] is None}


async def tehcard_model(me) -> dict:
    by: dict[str, list] = {}
    for r in await db.stock_tc_rows():
        by.setdefault(r["service_id"], []).append(_line_out(r))
    out = []
    for sid, svc in eng.SERVICES.items():
        lines = by.pop(sid, [])
        out.append({"id": sid, "name": svc.get("ro") or sid, "lines": lines,
                    "warn": sum(not x["active"] for x in lines)})
    for sid, lines in by.items():
        out.append({"id": sid, "name": sid, "lines": lines, "warn": sum(not x["active"] for x in lines),
                    "gone": True})
    items = [{"id": it["id"], "name": it["name"], "unit": it["unit"], "cat": it["category"],
              "active": bool(it["active"])} for it in await db.stock_items()]
    return {"services": out, "items": items, "can": cs.can_map(me)}


async def save_tehcard(service_id: str, body: dict) -> dict:
    known = {sid for sid in eng.SERVICES} | set(await db.stock_tc_services())
    if service_id not in known:
        raise cs.StockError("stock_service_gone", status=404)
    raw = body.get("lines")
    if not isinstance(raw, list) or len(raw) > LINES_MAX:
        raise cs.StockError("stock_bad", "lines")
    items = {it["id"]: it for it in await db.stock_items()}
    lines, seen, warn = [], set(), []
    for x in raw:
        if not isinstance(x, dict):
            raise cs.StockError("stock_bad", "lines")
        iid = x.get("item_id")
        if not isinstance(iid, int) or iid not in items or iid in seen:
            raise cs.StockError("stock_bad", "lines")
        seen.add(iid)
        qty = cs._int(x.get("qty_milli"), 1, cs.QTY_MAX, "lines")
        opt = cs._bool(x.get("optional", False), "lines")
        if not items[iid]["active"]:
            warn.append(iid)
        lines.append({"item_id": iid, "qty_milli": qty, "optional": int(opt)})
    await db.stock_tc_put(service_id, lines)
    return {"warn": warn}


async def replace_item(body: dict) -> dict:
    a = await db.stock_item(cs._int(body.get("from_item"), 1, 2 ** 62, "from_item"))
    b = await db.stock_item(cs._int(body.get("to_item"), 1, 2 ** 62, "to_item"))
    if a is None or b is None:
        raise cs.StockError("stock_item_gone", status=404)
    if a["id"] == b["id"]:
        raise cs.StockError("stock_bad", "to_item")
    if a["unit"] != b["unit"]:
        raise cs.StockError("stock_tc_unit", "to_item", 409)
    return {"services": await db.stock_tc_replace(a["id"], b["id"])}


# ---------- позиция плана ----------

async def _plan(plan_item_id: int) -> dict:
    p = await db.stock_plan_item(plan_item_id)
    if p is None:
        raise cs.StockError("stock_plan_gone", status=404)
    return p


async def _plan_moves(plan_item_id: int) -> tuple[list, list]:
    """(все движения позиции по техкарте, живые из них)."""
    moves = await db.stock_moves_plan(plan_item_id)
    fixed = await db.stock_fixed()
    undone, _ = cs._fix_maps(fixed)
    live = [m for m in moves if m["kind"] == "consum" and m["id"] not in undone]
    return moves, live


def _state(p: dict, lines: list, live: list, marked: bool) -> str:
    if live:
        return "done"
    if p["status"] != "finalizat" or not lines:
        return "none"
    return "fara" if marked else "pending"


async def _proposal(p: dict, money: bool) -> list:
    rows = await db.stock_tc_rows(p.get("service_id")) if p.get("service_id") else []
    if not rows:
        return []
    lv = await cs.levels([r["item_id"] for r in rows])
    out = []
    for r in rows:
        x = _line_out(r)
        live_lots = [lot for lot in lv[r["item_id"]]["lots"] if lot["qty_milli"] > 0]
        costly = bool(r["item_costly"])
        first = sorted(live_lots, key=lambda z: z["exp_on"] or "9999-12-31")
        stock = lv[r["item_id"]]["qty_milli"]
        x.update(on=not x["optional"] and x["active"], costly=costly,
                 lot=(first[0]["lot"] if first and first[0]["lot"] else "") if costly else None,
                 lots=live_lots if costly else [], stock_milli=stock, neg_after=stock - r["qty_milli"] < 0)
        if money:
            c = cs.cost_of(r["qty_milli"], lv[r["item_id"]]["avg_bani"])
            x["cost_bani"] = c
        out.append(x)
    return out


def _plan_out(p: dict) -> dict:
    return {"id": p["id"], "pid": p["patient_id"], "procedure": p["procedure"], "tooth": p["tooth"],
            "status": p["status"], "service_id": p.get("service_id"), "service": service_name(p.get("service_id")),
            "doctor_id": p.get("doctor_id") or "", "doctor": p.get("doctor") or "",
            "appointment_id": p.get("appointment_id"), "done_at": cs._iso(p.get("done_at"))}


async def plan_model(me, plan_item_id: int) -> dict:
    p = await _plan(plan_item_id)
    money = can(me, PERM_MONEY)
    lines = await _proposal(p, money)
    moves, live = await _plan_moves(plan_item_id)
    undone, fixed = await cs._fix_sets()
    return {"plan": _plan_out(p), "mode": await mode(),
            "state": _state(p, lines, live, await db.stock_plan_marked(plan_item_id)),
            "lines": lines, "moves": [cs.move_out(m, money, undone, fixed) for m in moves if m["kind"] == "consum"],
            "can": cs.can_map(me)}


async def pending(pid: int) -> dict:
    if not await db.get_patient(pid):
        raise cs.StockError("stock_patient_gone", status=404)
    if await mode() == "fara":
        return {"rows": []}
    rows = []
    for p in await db.stock_plan_finalized(pid):
        if not p.get("service_id") or not await db.stock_tc_rows(p["service_id"]):
            continue
        _, live = await _plan_moves(p["id"])
        if live or await db.stock_plan_marked(p["id"]):
            continue
        rows.append({"plan_item_id": p["id"], "procedure": p["procedure"], "tooth": p["tooth"],
                     "done_at": cs._iso(p.get("done_at"))})
    return {"rows": rows}


async def consume(me, plan_item_id: int, body: dict) -> dict:
    p = await _plan(plan_item_id)
    if p["status"] != "finalizat":
        raise cs.StockError("stock_tc_open", status=409)
    raw = body.get("lines")
    if not isinstance(raw, list) or len(raw) > LINES_MAX:
        raise cs.StockError("stock_bad", "lines")
    lines = []
    for x in raw:
        if not isinstance(x, dict):
            raise cs.StockError("stock_bad", "lines")
        iid = x.get("item_id")
        if not isinstance(iid, int):
            raise cs.StockError("stock_bad", "lines")
        it = await db.stock_item(iid)
        if it is None:
            raise cs.StockError("stock_bad", "lines")
        if not it["active"]:
            raise cs.StockError("stock_item_off", "lines", 409)
        lines.append((it, cs._int(x.get("qty_milli"), 1, cs.QTY_MAX, "lines"), cs._text(x, "lot", cs.LOT_MAX, "lines")))
    return await _write(me, p, lines)


async def _write(me, p: dict, lines: list) -> dict:
    _, live = await _plan_moves(p["id"])
    if live:
        raise cs.StockError("stock_tc_done", status=409)
    if not lines:
        await db.stock_plan_mark(p["id"], cs.who(me)[0])
        return {"moves": 0, "neg": []}
    actor, aid = cs.who(me)
    lv = await cs.levels([it["id"] for it, _, _ in lines])
    moves, neg = [], []
    for it, qty, lot in lines:
        cur = lv[it["id"]]
        cost = cs.cost_of(qty, cur["avg_bani"])
        expiry = next((x["exp_on"] for x in cur["lots"] if lot and x["lot"] == lot), None)
        moves.append({"kind": "consum", "item_id": it["id"], "item_name": it["name"], "qty_milli": -qty,
                      "cost_bani": None if cost is None else -cost, "lot": lot, "expiry": expiry,
                      "patient_id": p["patient_id"], "appointment_id": p.get("appointment_id"),
                      "plan_item_id": p["id"], "service_id": p.get("service_id"),
                      "doctor_id": p.get("doctor_id") or "", "doctor": p.get("doctor") or "",
                      "source": "tehcard", "reason": "pacient", "actor": actor, "actor_id": aid})
        if cur["qty_milli"] - qty < 0:
            neg.append(it["id"])
    if not await db.stock_plan_consume(p["id"], moves):
        raise cs.StockError("stock_tc_done", status=409)
    await db.log_event(p["patient_id"], "stock", cs._short(
        f"Materiale: {p['procedure']} — " + ", ".join(
            f"{it['name']} {cs.fmt_qty(q)} {it['unit']}" + (f" lot {lot}" if lot else "") for it, q, lot in lines)),
        actor=actor)
    return {"moves": len(moves), "neg": neg}


async def skip(me, plan_item_id: int) -> None:
    p = await _plan(plan_item_id)
    if p["status"] != "finalizat":
        raise cs.StockError("stock_tc_open", status=409)
    await _write(me, p, [])


async def undo(me, plan_item_id: int, why: str = "") -> int:
    p = await _plan(plan_item_id)
    _, live = await _plan_moves(plan_item_id)
    await db.stock_plan_unmark(plan_item_id)
    if not live:
        return 0
    actor, aid = cs.who(me)
    rev = [{"kind": "corectie", "item_id": m["item_id"], "item_name": m["item_name"], "qty_milli": -m["qty_milli"],
            "cost_bani": None if m["cost_bani"] is None else -m["cost_bani"], "lot": m["lot"], "expiry": m["expiry"],
            "patient_id": m["patient_id"], "appointment_id": m["appointment_id"], "plan_item_id": m["plan_item_id"],
            "service_id": m["service_id"], "doctor_id": m["doctor_id"], "doctor": m["doctor"],
            "source": "tehcard", "reason": "anulare", "fixes": m["id"], "why": why, "actor": actor,
            "actor_id": aid} for m in live]
    await db.stock_plan_consume(plan_item_id, rev, reverse=True)
    await db.log_event(p["patient_id"], "stock", cs._short(f"Materiale anulate: {p['procedure']}"), actor=actor)
    return len(rev)


async def on_plan_status(me, item_id: int, old: str | None, new: str) -> str:
    """Крючок перехода позиции плана; код склада для ответа фиши или ''.
    Никогда не роняет переход: позиция уже записана, склад — следствие."""
    try:
        if old == "finalizat" and new != "finalizat":
            return "ok_stock_tc_back" if await undo(me, item_id, "poziția din plan redeschisă") else ""
        if new != "finalizat" or old == "finalizat":
            return ""
        m = await mode()
        if m == "fara":
            return ""
        p = await _plan(item_id)
        lines = await _proposal(p, False)
        if not lines:
            return ""
        if m == "confirmare":
            return "ok_stock_tc_pending"
        pick = []
        for x in lines:
            if not x["on"]:
                continue
            it = await db.stock_item(x["item_id"])
            if it is not None and it["active"]:
                pick.append((it, x["qty_milli"], x["lot"] or ""))
        if not pick:
            return ""
        await _write(me, p, pick)
        return "ok_stock_tc_auto"
    except cs.StockError:
        return ""


# ---------- отчёт расхода ----------

async def report_model(me, q: dict) -> dict:
    by = q.get("by") or "doctor"
    if by not in REPORT_BY:
        raise cs.StockError("stock_bad", "by")
    td = cs.today()
    a = cs._d(q.get("from")) or td.replace(day=1)
    b = cs._d(q.get("to")) or td
    if b < a:
        a, b = b, a
    money = can(me, PERM_MONEY)
    undone, _ = cs._fix_maps(await db.stock_fixed())
    groups: dict = {}
    for m in await db.stock_moves_range(cs.day_start_utc(a), cs.day_start_utc(b + timedelta(days=1))):
        if m["kind"] != "consum" or m["id"] in undone:
            continue
        if by == "doctor":
            key, label = m["doctor_id"] or m["doctor"] or "", m["doctor"] or "Fără medic"
        elif by == "service":
            key = m["service_id"] or ""
            label = (service_name(key) or key) if key else "Fără serviciu"
        elif by == "patient":
            key, label = m["patient_id"], None
        else:
            key, label = m["item_id"], m["item_name"]
        g = groups.setdefault(key, {"key": key, "label": label, "qty_rows": 0, "cost": 0, "items": {}})
        g["qty_rows"] += 1
        g["cost"] += -(m["cost_bani"] or 0)
        it = g["items"].setdefault(m["item_id"], {"item_id": m["item_id"], "item": m["item_name"],
                                                  "unit": m.get("unit") or "", "qty_milli": 0, "cost": 0})
        it["qty_milli"] += -m["qty_milli"]
        it["cost"] += -(m["cost_bani"] or 0)
    if by == "patient":
        for g in groups.values():
            pt = await db.get_patient(g["key"]) if g["key"] is not None else None
            g["label"] = ((pt.get("name") or "") + (f" · fișa {pt['file_no']}" if pt and pt.get("file_no") else "")
                          if pt else "Fără pacient")
    rows = []
    for g in groups.values():
        items = sorted(g["items"].values(), key=lambda x: -x["cost"] if money else -x["qty_milli"])
        row = {"key": g["key"], "label": g["label"], "qty_rows": g["qty_rows"],
               "items": [{k: v for k, v in x.items() if k != "cost"} | ({"cost_bani": x["cost"]} if money else {})
                         for x in items]}
        if money:
            row["cost_bani"] = g["cost"]
        rows.append(row)
    rows.sort(key=lambda r: (-(r.get("cost_bani") or 0), -r["qty_rows"], str(r["label"]).casefold()))
    out = {"by": by, "from": a.isoformat(), "to": b.isoformat(), "rows": rows, "can": cs.can_map(me)}
    if money:
        out["total_bani"] = sum(r["cost_bani"] for r in rows)
    return out
