"""Импорт каталога материалов и начальных остатков из .xlsx / .csv.

Файл читает `core/tabfile.py` (как у импорта пациентов); здесь — узнать
колонки по шапке, разобрать строки, сверить с каталогом и записать одним
документом `import`. Материал, который уже есть в каталоге, пропускается
целиком: остаток не прибавляется, иначе повторный файл удвоил бы склад.
Тот же файл дважды не импортируется (отпечаток), пока прежний импорт не отменён.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta

from .. import db
from . import stock as cs
from .labels import STOCK_UNITS

MAX_ROWS = 2000

FIELDS = (("name", "Denumirea"), ("cat", "Categoria"), ("unit", "Unitatea (buc, g, ml)"),
          ("pack", "Ambalajul"), ("pack_qty", "Câte într-un ambalaj"), ("qty", "Restul pe raft"),
          ("min", "Pragul"), ("price", "Prețul unei unități, lei"), ("exp", "Valabil până la"),
          ("lot", "Lot / serie"), ("supplier", "Furnizor"), ("raft", "Raft / loc"))
_FIELD_IDS = {f for f, _ in FIELDS}

ERR_TEXT = {"no_name": "fără denumire", "name_long": "denumirea e prea lungă", "unit": "unitate necunoscută",
            "qty": "restul nu e număr", "pack_qty": "cantitatea în ambalaj nu e număr",
            "min": "pragul nu e număr", "price": "prețul nu e număr", "date": "data nu e zi.lună.an"}

_UNIT_ALIAS = {"buc": "buc", "bucata": "buc", "bucati": "buc", "bc": "buc", "pcs": "buc", "шт": "buc",
               "g": "g", "gr": "g", "gram": "g", "grame": "g", "ml": "ml", "cm": "cm", "cutie": "cutie",
               "cutii": "cutie", "pachet": "pachet", "pachete": "pachet", "pac": "pachet"}


def _hkey(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", db.fold(str(s or "")))).strip()


def guess_field(title) -> str:
    """Поле по словам шапки: «Buc./g în ambalaj» → pack_qty, «Stoc minim» → min."""
    h = _hkey(title)
    if not h:
        return ""
    w = set(h.split())
    if w & {"denumire", "denumirea", "material", "materialul", "produs", "articol", "nume"}:
        return "name"
    if w & {"categorie", "categoria", "grupa"}:
        return "cat"
    if "ambalaj" in w or "ambalajul" in w:
        return "pack_qty" if w & {"buc", "cate", "cantitate", "cantitatea", "in", "g"} else "pack"
    if w & {"minim", "prag", "pragul", "min"}:
        return "min"
    if w & {"valabil", "expira", "expirare", "expirarii", "termen", "valabilitate"}:
        return "exp"
    if w & {"pret", "pretul"}:
        return "price"
    if w & {"lot", "serie", "seria", "partida"}:
        return "lot"
    if w & {"furnizor", "furnizorul"}:
        return "supplier"
    if w & {"raft", "loc", "locul", "dulap"}:
        return "raft"
    if h in ("um", "u m", "unit") or w & {"unitate", "unitatea"}:
        return "unit"
    if w & {"stoc", "rest", "restul", "cantitate", "cantitatea"}:
        return "qty"
    return ""


def parse_opts(raw: str) -> dict | None:
    if not raw:
        return {"sheet": None, "header": None, "cols": None, "choices": {}}
    try:
        o = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(o, dict):
        return None
    out = {"sheet": o.get("sheet"), "header": o.get("header"), "cols": None, "choices": {}}
    for k in ("sheet", "header"):
        if out[k] is not None and (not isinstance(out[k], int) or isinstance(out[k], bool) or out[k] < 0):
            return None
    if o.get("cols") is not None:
        cols = o["cols"]
        if not isinstance(cols, dict):
            return None
        out["cols"] = {}
        for k, v in cols.items():
            if not str(k).isdigit() or not isinstance(v, str) or (v and v not in _FIELD_IDS):
                return None
            if v:
                out["cols"][int(k)] = v
    ch = o.get("choices") or {}
    if not isinstance(ch, dict) or not all(str(k).isdigit() and v in ("same", "new") for k, v in ch.items()):
        return None
    out["choices"] = {int(k): v for k, v in ch.items()}
    return out


def _text(v) -> str:
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def resolve(table, opts: dict) -> dict | None:
    """Лист, строка шапки и колонки: присланные или узнанные по шапке."""
    sheets = table.sheets
    order = [opts["sheet"]] if opts["sheet"] is not None else range(len(sheets))
    for si in order:
        if not 0 <= si < len(sheets):
            return None
        rows = sheets[si].rows
        cands = [r for r in rows if r[0] == opts["header"]] if opts["header"] is not None else rows[:10]
        for rno, line in cands:
            guessed = {}
            for i, cell in enumerate(line):
                f = guess_field(cell)
                if f and f not in guessed.values():
                    guessed[i] = f
            if opts["cols"] is not None:
                return {"sheet": si, "header": rno, "cols": dict(opts["cols"])}
            if "name" in guessed.values() and len(guessed) >= 2:
                return {"sheet": si, "header": rno, "cols": guessed}
        if opts["sheet"] is not None or opts["header"] is not None:
            head = cands[0][0] if cands else (rows[0][0] if rows else 0)
            return {"sheet": si, "header": head, "cols": dict(opts["cols"] or {})}
    return {"sheet": 0, "header": sheets[0].rows[0][0] if sheets and sheets[0].rows else 0, "cols": {}}


def ready(res: dict) -> bool:
    return {"name", "unit"} <= set(res["cols"].values())


def _num(s: str) -> float | None:
    t = re.sub(r"[\s\u00a0']", "", s).replace(",", ".")
    return float(t) if re.fullmatch(r"-?\d*\.?\d+", t) else None


def _milli(v: float) -> int:
    return int(round(v * 1000))


def parse_date(v) -> str | None | bool:
    """Голая дата ISO; None — пусто; False — не дата. «06.2027» — последний день
    месяца (так печатают срок на упаковке)."""
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v.isoformat()
    s = _text(v)
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})", s)
    try:
        if m:
            y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(y, int(m[2]), int(m[1])).isoformat()
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.fullmatch(r"(\d{1,2})[./](\d{4})", s)
        if m:
            first = date(int(m[2]), int(m[1]), 1)
            nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
            return (nxt - timedelta(days=1)).isoformat()
    except ValueError:
        return False
    return False


def build(table, res: dict, money: bool) -> list:
    """Строки файла как записи с ошибкой или без; сверка с каталогом — `analyse`."""
    sheet = table.sheets[res["sheet"]]
    cols = res["cols"]
    out = []
    for rno, line in sheet.rows:
        if rno <= res["header"]:
            continue
        cell = {f: (line[i] if i < len(line) else None) for i, f in cols.items()}
        if not any(_text(v) for v in cell.values()):
            continue
        g = {f: _text(v) for f, v in cell.items()}
        name = g.get("name", "")
        raw_unit = g.get("unit", "")
        unit = _UNIT_ALIAS.get(db.fold(raw_unit).rstrip("."), "")
        qty = _num(g["qty"]) if g.get("qty") else 0.0
        pq = _num(g["pack_qty"]) if g.get("pack_qty") else 1.0
        mn = _num(g["min"]) if g.get("min") else None
        price = _num(g["price"]) if g.get("price") else None
        exp = parse_date(cell.get("exp"))
        err = ""
        if not name:
            err = "no_name"
        elif len(name) > cs.NAME_MAX:
            err = "name_long"
        elif unit not in STOCK_UNITS:
            err = "unit"
        elif qty is None or abs(qty) * 1000 > cs.QTY_MAX:
            err = "qty"
        elif pq is None or pq <= 0 or pq * 1000 > cs.QTY_MAX:
            err = "pack_qty"
        elif g.get("min") and (mn is None or mn < 0 or mn * 1000 > cs.QTY_MAX):
            err = "min"
        elif g.get("price") and (price is None or price < 0 or price > 10 ** 7):
            err = "price"
        elif exp is False:
            err = "date"
        text = ERR_TEXT.get(err, "")
        if err == "unit":
            text = f"unitate necunoscută „{raw_unit}”" if raw_unit else "fără unitate"
        rec = {"line": rno, "name": name, "cat": g.get("cat", "")[:cs.CAT_MAX], "unit": unit or raw_unit,
               "pack_name": (g.get("pack", "") or unit)[:cs.PACK_MAX],
               "pack_qty_milli": _milli(pq) if not err else 0, "qty_milli": _milli(qty) if not err else 0,
               "min_milli": _milli(mn) if mn is not None and not err else None,
               "exp_on": exp if exp else None, "lot": g.get("lot", "")[:cs.LOT_MAX],
               "supplier": g.get("supplier", "")[:cs.NAME_MAX], "raft": g.get("raft", "")[:cs.PACK_MAX],
               "err": err, "err_text": text, "act": "error" if err else "new", "similar": None, "choice": "new"}
        if money and price is not None and not err:
            rec["price_bani"] = round(price * 100, 4)
        out.append(rec)
    return out


def _sim_key(name: str) -> list:
    base = re.sub(r"\s*\([^)]*\)\s*$", "", cs.norm_name(name))
    return [t for t in re.split(r"[\s,;/]+", base) if t]


def _similar(a: list, b: list) -> bool:
    """Похоже: то же без пробелов («Z550» / «Z 550») или одно — начало другого
    целыми словами («Ubistesin 3%» / «Ubistesin 3% 1:200 000»). «A3» и «A3.5» —
    разные слова: оттенки не путаются."""
    if not a or not b:
        return False
    if "".join(a) == "".join(b):
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 2 and len("".join(short)) >= 8 and long_[:len(short)] == short


def analyse(recs: list, catalog: list, choices: dict) -> None:
    """Новое / уже в каталоге / повтор строки выше / ошибка; «похоже на…»."""
    exact = {cs.norm_name(it["name"]): it for it in catalog}
    seen: dict[str, dict] = {}
    for r in recs:
        if r["err"]:
            continue
        key = cs.norm_name(r["name"])
        r["choice"] = choices.get(r["line"], "new")
        if key in exact:
            r["act"], r["into"] = "exists", exact[key]["id"]
            continue
        if key in seen:
            r["act"], r["into_line"] = "merged", seen[key]["line"]
            continue
        sk = _sim_key(r["name"])
        sim = next(({"kind": "item", "id": it["id"], "name": it["name"]} for it in catalog
                    if _similar(sk, _sim_key(it["name"]))), None)
        if sim is None:
            sim = next(({"kind": "row", "line": x["line"], "name": x["name"]} for x in seen.values()
                        if _similar(sk, _sim_key(x["name"]))), None)
        r["similar"] = sim
        if sim and r["choice"] == "same":
            if sim["kind"] == "item":
                r["act"], r["into"] = "exists", sim["id"]
            else:
                r["act"], r["into_line"] = "merged", sim["line"]
            continue
        r["act"] = "new"
        seen[key] = r


def summary(recs: list) -> dict:
    new = [r for r in recs if r["act"] == "new"]
    qty = {r["line"]: r["qty_milli"] for r in new}
    for r in recs:
        if r["act"] == "merged" and r["into_line"] in qty:
            qty[r["into_line"]] += r["qty_milli"]
    return {"new": len(new), "exists": sum(r["act"] == "exists" for r in recs),
            "merged": sum(r["act"] == "merged" for r in recs), "errors": sum(r["act"] == "error" for r in recs),
            "rests": sum(1 for v in qty.values() if v), "similar": sum(r["similar"] is not None for r in recs)}


def fingerprint(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def token(blob: bytes, res: dict, opts: dict) -> str:
    key = json.dumps({"res": {**res, "cols": {str(k): v for k, v in res["cols"].items()}},
                      "choices": {str(k): v for k, v in sorted(opts["choices"].items())}}, sort_keys=True)
    return hashlib.sha256(blob + key.encode()).hexdigest()[:32]


def row_out(r: dict) -> dict:
    keep = ("line", "name", "cat", "unit", "pack_name", "pack_qty_milli", "qty_milli", "min_milli", "price_bani",
            "exp_on", "lot", "supplier", "raft", "act", "err", "err_text", "similar", "choice")
    return {k: r[k] for k in keep if k in r}


async def run(me, recs: list, name: str, blob: bytes) -> dict:
    """Запись одной транзакцией. Строки-повторы одного материала дают каждая
    свою строку начального остатка: у них может быть своя партия и свой срок."""
    actor, aid = cs.who(me)
    sups = {cs.norm_name(s["name"]): s for s in await db.stock_suppliers()}
    new_sups: dict[str, dict] = {}
    items, idx, moves = [], {}, []
    for r in recs:
        if r["act"] != "new":
            continue
        sk = cs.norm_name(r["supplier"])
        sid = sups[sk]["id"] if sk in sups else None
        if sk and sid is None and sk not in new_sups:
            new_sups[sk] = {"key": sk, "name": r["supplier"], "idno": "", "phone": "", "email": "", "note": "",
                            "active": 1}
        idx[r["line"]] = len(items)
        items.append({"name": r["name"], "category": r["cat"], "unit": r["unit"], "pack_name": r["pack_name"],
                      "pack_qty_milli": r["pack_qty_milli"], "min_milli": r["min_milli"],
                      "costly": int(bool(r["lot"])), "track_expiry": int(bool(r["exp_on"])),
                      "bulk": int(cs.norm_name(r["cat"]) == "consumabile diverse"), "supplier_id": sid,
                      "supplier_key": sk if sid is None and sk else "", "note": "", "active": 1, "sort": 0,
                      "data": {"raft": r["raft"]} if r["raft"] else {}})
    for r in recs:
        target = r["line"] if r["act"] == "new" else r.get("into_line") if r["act"] == "merged" else None
        if target not in idx or not r["qty_milli"]:
            continue
        price = r.get("price_bani")
        moves.append({"item": idx[target], "kind": "inventar", "item_name": r["name"] if r["act"] == "new"
                      else items[idx[target]]["name"], "qty_milli": r["qty_milli"],
                      "cost_bani": None if price is None else round(r["qty_milli"] / 1000 * price),
                      "lot": r["lot"], "expiry": r["exp_on"], "source": "import", "note": "rest inițial",
                      "supplier": r["supplier"], "actor": actor, "actor_id": aid})
    for it in items:
        if it["supplier_id"] is None and not it["supplier_key"]:
            it["supplier_key"] = ""
    head = {"nr": name[:cs.NR_MAX], "doc_date": cs.today().isoformat(), "supplier_id": None, "supplier": "",
            "note": f"{len(recs)} rânduri", "cur": "", "cur_amount": None, "rate": "",
            "fingerprint": fingerprint(blob), "actor": actor, "actor_id": aid,
            "data": {"file": name[:200], "rows": len(recs), "created": len(items), "rests": len(moves)}}
    did, _ids, _sids = await db.stock_import_write(head, list(new_sups.values()), items, moves)
    await db.log_clinic_event("import", f"Import stoc: {len(items)} materiale noi, {len(moves)} resturi"
                              f" („{name[:60]}”)", actor=actor)
    return {"id": did, "created": len(items), "rests": len(moves),
            "skipped": sum(r["act"] in ("exists", "error") for r in recs)}


async def history(me) -> list:
    out = []
    for d in await db.stock_docs(kind="import"):
        data = d["data"]
        ids = await db.stock_import_items(d["id"])
        used = await db.stock_import_foreign_moves(d["id"], ids)
        out.append({"id": d["id"], "at": cs._iso(d["created_at"]), "actor": d["actor"],
                    "file": data.get("file") or d["nr"], "rows": data.get("rows", 0),
                    "created": data.get("created", 0), "rests": data.get("rests", 0),
                    "undone": d["status"] == "anulat", "can_undo": d["status"] == "inchis" and not used})
    return out


async def undo(me, doc_id: int) -> None:
    d = await db.stock_doc(doc_id)
    if d is None or d["kind"] != "import":
        raise cs.StockError("stock_doc_gone", status=404)
    if d["status"] != "inchis":
        raise cs.StockError("stock_doc_closed", status=409)
    ids = await db.stock_import_items(doc_id)
    if await db.stock_import_foreign_moves(doc_id, ids):
        raise cs.StockError("stock_import_used", status=409)
    actor, aid = cs.who(me)
    rev = [{"kind": "corectie", "item_id": m["item_id"], "item_name": m["item_name"], "qty_milli": -m["qty_milli"],
            "cost_bani": None if m["cost_bani"] is None else -m["cost_bani"], "lot": m["lot"],
            "expiry": m["expiry"], "source": "import", "reason": "import_anulat", "fixes": m["id"],
            "actor": actor, "actor_id": aid}
           for m in await db.stock_moves_query(doc=doc_id, limit=MAX_ROWS * 2) if m["kind"] == "inventar"]
    if not await db.stock_doc_undo(doc_id, rev, by=actor, why="import anulat", items=ids,
                                   suppliers=await db.stock_import_suppliers(doc_id)):
        raise cs.StockError("stock_doc_closed", status=409)
    await db.log_clinic_event("import", f"Import stoc anulat („{(d['data'].get('file') or d['nr'])[:60]}”)",
                              actor=actor)
