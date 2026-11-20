"""Прайс «Servicii și tarife»: модель экрана, запись, импорт из таблицы, выгрузка.

Прайс — те же строки `clinic.json › services`, что типы записи агенды: ключ услуги
один, поэтому склад, лаборатория и шаблоны плана видят строки прайса сами. Где строка
показывается, говорит `where` (`eng.in_agenda` / `eng.in_plan`), группу — `cat` из
`service_cats`.

Этот модуль правит у строки только то, что принадлежит прайсу: имя, цену, категорию и
место «plan». Поля агенды (длительность, цвет, врачи, urgent, rechemare, tpl) переезжают
как есть: их правит «Setări › Servicii» под другим правом. Профиль пишется целиком
(`eng.save_config`), поэтому всё, чего запись не касается, кладётся обратно поимённо из
текущего профиля.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from .. import db
from .. import engine as eng
from . import prices, tabfile

NAME_MAX = 60
PRICE_LEN = 60
CAT_MAX = 60
CATS_MAX = 50
SERVICES_MAX = 1000
# Ответ наружу: место строкой, «оба» — своим словом (в файле — нет ключа).
WHERE_BOTH = "both"
WHERE_OUT = (WHERE_BOTH, eng.WHERE_AGENDA, eng.WHERE_PLAN)
_CAT_ID = re.compile(r"c(\d+)")
_SVC_ID = re.compile(r"s(\d+)")


class Refuse(Exception):
    """Отказ записи: код из `MSG_BANNER`, поле формы, данные для экрана, статус."""

    def __init__(self, code: str, field: str = "", data: dict | None = None, status: int = 422):
        super().__init__(code)
        self.code, self.field, self.data, self.status = code, field, data, status


def where_out(sid: str) -> str:
    return eng.service_where(sid) or WHERE_BOTH


def _price_str(raw) -> str:
    if isinstance(raw, dict):
        raw = raw.get("ro", "")
    return str(raw or "")


# ---------------------------------------------------------------- модель экрана

def model(can_edit: bool, remote: dict | None = None) -> dict:
    """Все услуги в порядке профиля (и «doar agendă» — экран решает, показывать
    ли их), категории по порядку с числом строк прайса, право правки."""
    rows = []
    for s in eng.CONFIG.get("services", []):
        sid = s["id"]
        amount, hint = prices.parse(s.get("price", ""))
        rows.append({"id": sid, "ro": s["ro"], "ru": s.get("ru", "") or s["ro"],
                     "price": _price_str(s.get("price")), "amount": amount, "price_hint": hint,
                     "cat": eng.service_cat(sid), "where": where_out(sid)})
    in_plan = [r for r in rows if eng.in_plan(r["id"])]
    return {
        "services": rows,
        "cats": [{"id": c["id"], "name": c["name"],
                  "n": sum(1 for r in in_plan if r["cat"] == c["id"])} for c in eng.SERVICE_CATS],
        "uncat": sum(1 for r in in_plan if not r["cat"]),
        "can_edit": bool(can_edit),
        "max": {"name": NAME_MAX, "price": PRICE_LEN, "cat": CAT_MAX, "cats": CATS_MAX,
                "services": SERVICES_MAX},
        "import": {"bytes": tabfile.MAX_FILE, "remote": remote},
    }


# ---------------------------------------------------------------- проверки полей

def _text(v, field: str, limit: int, *, empty_ok: bool = False) -> str:
    """Строка поля: не строка, пусто (где нельзя) или длиннее предела — отказ
    с полем. Обрезать молча нельзя: клиника увидела бы в прайсе не то, что
    написала."""
    if isinstance(v, bool) or not isinstance(v, (str, int)):
        raise Refuse("bad_tarif", field)
    t = " ".join(str(v).split())
    if (not t and not empty_ok) or len(t) > limit:
        raise Refuse("bad_tarif", field)
    return t


def _labels_ok(services: list[dict]) -> None:
    """Имена RO и RU уникальны без учёта регистра по ВСЕМУ списку — то же
    правило, что у «Setări › Servicii»: одинаковые подписи ломали бы
    сопоставление ключа по тексту и отчёты."""
    seen: dict[str, str] = {}
    for s in services:
        for label in {s["ro"].casefold(), (s.get("ru") or s["ro"]).casefold()}:
            if seen.get(label, s["id"]) != s["id"]:
                raise Refuse("dup_tarif", "ro", {"label": s["ro"] if label == s["ro"].casefold()
                                                  else s.get("ru", "")})
            seen[label] = s["id"]


def _seq_from(items: list, key: str, pattern: re.Pattern, seq: dict) -> int:
    n = int(seq.get(key, 0) or 0)
    for it in items:
        m = pattern.fullmatch(str(it.get("id", "")))
        if m:
            n = max(n, int(m.group(1)))
    return n


def _apply_plan(entry: dict, on: bool) -> bool:
    """Поставить/снять место «plan». False — строку надо удалить: снято
    последнее место."""
    where = entry.get("where")
    if on:
        if where == eng.WHERE_AGENDA:
            entry.pop("where")
        return True
    if where == eng.WHERE_PLAN:
        return False
    if where not in eng.SERVICE_WHERE:
        entry["where"] = eng.WHERE_AGENDA
    return True


# ---------------------------------------------------------------- запись

def _cats_step(body: dict, cats: list[dict], seq: dict) -> tuple[list[dict], dict, set, int | None]:
    """Категории: правка, новые, удаление, порядок. → (категории, ключ → id,
    удалённые, новый счётчик или None)."""
    by_id = {c["id"]: c for c in cats}
    for cid, ch in (body.get("cats") or {}).items():
        if cid not in by_id:
            raise Refuse("tarif_gone", status=409)
        if not isinstance(ch, dict):
            raise Refuse("bad_tarif", "name")
        if "name" in ch:
            by_id[cid]["name"] = _text(ch["name"], "name", CAT_MAX)
    removed = set()
    for cid in body.get("cats_removed") or []:
        if not isinstance(cid, str):
            raise Refuse("bad_tarif", "cat")
        removed.add(cid)          # уже удалённую в другой вкладке — желаемое и так достигнуто
    cats = [c for c in cats if c["id"] not in removed]
    seq_c = None
    keys: dict[str, str] = {}
    new = body.get("cats_new") or []
    if new:
        seq_c = _seq_from(eng.CONFIG.get("service_cats") or [], "service_cat", _CAT_ID, seq)
    for c in new:
        if not isinstance(c, dict) or not isinstance(c.get("key"), str) or not c["key"] \
                or c["key"] in keys:
            raise Refuse("bad_tarif", "cat")
        seq_c += 1
        cid = f"c{seq_c}"
        keys[c["key"]] = cid
        cats.append({"id": cid, "name": _text(c.get("name"), "name", CAT_MAX)})
    order = body.get("cats_order")
    if order is not None:
        if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
            raise Refuse("bad_tarif", "cat")
        pos = {keys.get(x, x): i for i, x in reversed(list(enumerate(order)))}
        cats = sorted(cats, key=lambda c: pos.get(c["id"], len(pos)))
    if len(cats) > CATS_MAX:
        raise Refuse("tarife_full")
    names: set[str] = set()
    for c in cats:
        if c["name"].casefold() in names:
            raise Refuse("dup_tarif", "name", {"label": c["name"]})
        names.add(c["name"].casefold())
    return cats, keys, removed, seq_c


def _cat_of(v, live: set, keys: dict, removed: set) -> str:
    if not isinstance(v, str):
        raise Refuse("bad_tarif", "cat")
    if v == "":
        return ""
    if v in keys:
        return keys[v]
    if v in live:
        return v
    if v in removed:
        raise Refuse("bad_tarif", "cat")
    raise Refuse("tarif_gone", status=409)


def _set_fields(entry: dict, ch: dict, live: set, keys: dict, removed: set) -> None:
    """Поля прайса у строки: ключа нет — не сообщали."""
    if "ro" in ch:
        entry["ro"] = _text(ch["ro"], "ro", NAME_MAX)
    if "ru" in ch:
        entry["ru"] = _text(ch["ru"], "ru", NAME_MAX, empty_ok=True) or entry["ro"]
    if "price" in ch:
        price = _text(ch["price"], "price", PRICE_LEN, empty_ok=True)
        if price:
            entry["price"] = price
        else:
            entry.pop("price", None)
    if "cat" in ch:
        cat = _cat_of(ch["cat"], live, keys, removed)
        if cat:
            entry["cat"] = cat
        else:
            entry.pop("cat", None)


def plan_cfg(body: dict) -> tuple[dict, dict]:
    """Новый профиль по телу экрана прайса (контракт — `side-session-notes\\
    2026-11-20\\tarife-contract.md` § 5) и что создано: `{services: [id],
    cats: {key: id}}`. Отказ — `Refuse`. Профиль не пишется."""
    if not isinstance(body, dict):
        raise Refuse("bad_tarif")
    for k, kind in (("services", dict), ("new", list), ("cats", dict), ("cats_new", list),
                    ("cats_removed", list)):
        if k in body and not isinstance(body[k], kind):
            raise Refuse("bad_tarif")
    cfg = eng.CONFIG
    seq = dict(cfg.get("seq") or {})
    cats0 = [dict(c) for c in eng.SERVICE_CATS]
    cats, keys, removed, seq_c = _cats_step(body, cats0, seq)
    live = {c["id"] for c in cats}

    services = [dict(s) for s in cfg["services"]]
    by_id = {s["id"]: s for s in services}
    drop: set[str] = set()
    for sid, ch in (body.get("services") or {}).items():
        if sid not in by_id:
            raise Refuse("tarif_gone", status=409)
        if not isinstance(ch, dict):
            raise Refuse("bad_tarif")
        entry = by_id[sid]
        _set_fields(entry, ch, live, keys, removed)
        if "plan" in ch:
            if not isinstance(ch["plan"], bool):
                raise Refuse("bad_tarif", "plan")
            if not _apply_plan(entry, ch["plan"]):
                drop.add(sid)
    services = [s for s in services if s["id"] not in drop]
    seq_s = None
    created = []
    new = body.get("new") or []
    if new:
        seq_s = _seq_from(cfg["services"], "service", _SVC_ID, seq)
    for row in new:
        if not isinstance(row, dict):
            raise Refuse("bad_tarif")
        seq_s += 1
        entry = {"id": f"s{seq_s}", "ro": "", "ru": ""}
        _set_fields(entry, {"ro": row.get("ro"), **{k: row[k] for k in ("ru", "price", "cat")
                                                    if k in row}}, live, keys, removed)
        entry["ru"] = entry["ru"] or entry["ro"]
        entry["where"] = eng.WHERE_PLAN
        services.append(entry)
        created.append(entry["id"])
    for s in services:                    # услуги удалённой категории — «Fără categorie»
        if s.get("cat") in removed:
            s.pop("cat")
    if len(services) > max(SERVICES_MAX, len(cfg["services"])):
        raise Refuse("tarife_full")
    _labels_ok(services)
    if not any(s.get("where") != eng.WHERE_PLAN for s in services):
        raise Refuse("svc_agenda_empty", "where")

    out = dict(cfg)
    out["services"] = services
    if cats != [dict(c) for c in eng.SERVICE_CATS] or "service_cats" in cfg:
        out["service_cats"] = cats
    if seq_s is not None or seq_c is not None:
        # прочие счётчики переезжают как есть: забытый начал бы выдавать id заново
        out["seq"] = {**seq, **({"service": seq_s} if seq_s is not None else {}),
                      **({"service_cat": seq_c} if seq_c is not None else {})}
    return out, {"services": created, "cats": keys}


def store(body: dict) -> tuple[str | None, dict]:
    """Одна дверь записи прайса: (ошибка записи | None, созданное). Тело,
    которое ничего не меняет, профиль не переписывает."""
    cfg, created = plan_cfg(body)
    if cfg == eng.CONFIG:
        return None, created
    return eng.save_config(cfg), created


# ---------------------------------------------------------------- выгрузка

HEAD_OUT = ["Categoria", "Denumire", "Denumire RU", "Preț"]


def export_rows() -> list[list[str]]:
    """Строки прайса (`in_plan`) по порядку категорий, «Fără categorie»
    последней — теми же колонками, что читает импорт."""
    out = []
    for o in prices.options(eng.WHERE_PLAN):
        svc = next(s for s in eng.CONFIG["services"] if s["id"] == o["id"])
        out.append([o["cat_name"], o["label"], o["ru"], _price_str(svc.get("price"))])
    return out


# ---------------------------------------------------------------- импорт

# Заголовки колонок по словам (без регистра и диакритики, `db.fold`).
_HEADS = {
    "ru": ("denumire ru", "denumirea ru", "ru", "rusa", "in rusa", "denumire rusa", "название",
           "наименование"),
    "cat": ("categoria", "categorie", "categorii", "categorie serviciu", "sectiune", "sectiunea",
            "category", "категория", "раздел"),
    "ro": ("denumire", "denumirea", "serviciu", "serviciul", "denumire serviciu",
           "denumirea serviciului", "procedura", "manopera", "услуга"),
    "price": ("pret", "pretul", "pret mdl", "pret lei", "tarif", "tariful", "cost", "suma",
              "цена", "стоимость"),
}


def _hkey(v) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zа-я]+", " ", db.fold(str(v or "")))).strip()


def _cell(v) -> str:
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    return " ".join(("" if v is None else str(v)).split())


def _columns(head: list) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, v in enumerate(head):
        h = _hkey(v)
        for field, words in _HEADS.items():
            if field not in cols and h in words:
                cols[field] = i
                break
    return cols


def parse(blob: bytes, name: str) -> list[dict]:
    """Строки файла: `{line, cat, ro, ru, price}`. Шапка — первая строка с
    колонкой «Denumire» на первом листе, где она нашлась. Строка-раздел
    (одна объединённая ячейка, `tabfile` bands) задаёт категорию следующим
    строкам, у которых своя ячейка категории пуста. Отказ — `Refuse`."""
    try:
        table = tabfile.read(blob, name)
    except tabfile.Refuse as e:
        raise Refuse(_FILE_REFUSE.get(e.code, "stock_not_table"),
                     status=413 if e.code == "too_big" else 422) from None
    for sheet in table.sheets:
        for k, (rno, cells) in enumerate(sheet.rows[:20]):
            cols = _columns(cells)
            if "ro" not in cols:
                continue
            out, band = [], ""
            for rno2, ln in sheet.rows[k + 1:]:
                vals = [_cell(x) for x in ln]
                if rno2 in sheet.bands:
                    band = next((x for x in vals if x), "")
                    continue

                def at(f: str) -> str:
                    i = cols.get(f)
                    return vals[i] if i is not None and i < len(vals) else ""
                if not any(vals):
                    continue
                out.append({"line": rno2, "cat": at("cat") or band, "ro": at("ro"), "ru": at("ru"),
                            "price": at("price")})
                if len(out) > SERVICES_MAX:
                    raise Refuse("tarife_rows")
            return out
    raise Refuse("tarife_import_cols")


_FILE_REFUSE = {"old_xls": "stock_old_xls", "not_table": "stock_not_table", "too_big": "stock_too_big",
                "too_many_rows": "tarife_rows", "bad_xml": "stock_not_table", "empty": "stock_file_empty"}


def _price_key(raw) -> str:
    return " ".join(_price_str(raw).split()).casefold()


def analyse(rows: list[dict]) -> tuple[list[dict], dict, list[str], dict]:
    """Что сделает импорт: строки с `act` ∈ new/changed/same/bad, счётчики,
    новые категории, тело для `plan_cfg`. Совпадение — по имени RO без учёта
    регистра с ЛЮБОЙ услугой; пустая ячейка у существующей = «не трогать».
    Ничего не удаляется; новые строки — «только plan»."""
    services = eng.CONFIG.get("services", [])
    by_ro = {s["ro"].casefold(): s for s in services}
    labels = {}
    for s in services:
        labels[s["ro"].casefold()] = s["id"]
        labels[(s.get("ru") or s["ro"]).casefold()] = s["id"]
    cat_by_name = {c["name"].casefold(): c["id"] for c in eng.SERVICE_CATS}
    cats_new: dict[str, str] = {}               # casefold → имя как в файле
    seen: set[str] = set()
    out, edits, new = [], {}, []
    for r in rows:
        res = {**r, "act": "", "id": "", "what": [], "old_price": "", "err": ""}
        ro, ru, cat, price = r["ro"], r["ru"], r["cat"], r["price"]
        err = ""
        if not ro or len(ro) > NAME_MAX or len(ru) > NAME_MAX or len(cat) > CAT_MAX:
            err = "name"
        elif len(price) > PRICE_LEN:
            err = "price"
        elif ro.casefold() in seen or (ru and ru.casefold() != ro.casefold() and ru.casefold() in seen):
            err = "dup"
        cur = by_ro.get(ro.casefold()) if not err else None
        if not err and cur is None:
            # новое имя не должно совпасть с чужой подписью (RU другой услуги)
            if ro.casefold() in labels or (ru and labels.get(ru.casefold())):
                err = "dup"
        elif not err and ru and labels.get(ru.casefold(), cur["id"]) != cur["id"]:
            err = "dup"
        if err:
            res.update(act="bad", err=err)
            out.append(res)
            continue
        seen.add(ro.casefold())
        if ru:
            seen.add(ru.casefold())
        cat_ref = ""
        if cat:
            cat_ref = cat_by_name.get(cat.casefold(), "")
            if not cat_ref:
                cats_new.setdefault(cat.casefold(), cat)
                cat_ref = "new:" + cat.casefold()
        if cur is None:
            res["act"] = "new"
            new.append({"ro": ro, "ru": ru, "price": price, "cat": cat_ref})
            out.append(res)
            continue
        sid = cur["id"]
        res["id"] = sid
        res["old_price"] = _price_str(cur.get("price"))
        ch: dict = {}
        if price and _price_key(price) != _price_key(cur.get("price")):
            ch["price"] = price
            res["what"].append("price")
        if cat and (cat_ref.startswith("new:") or cat_ref != eng.service_cat(sid)):
            ch["cat"] = cat_ref
            res["what"].append("cat")
        if ru and ru != (cur.get("ru") or cur["ro"]):
            ch["ru"] = ru
            res["what"].append("ru")
        if not eng.in_plan(sid):
            ch["plan"] = True
            res["what"].append("plan")
        res["act"] = "changed" if ch else "same"
        if ch:
            edits[sid] = ch
        out.append(res)
    counts = {a: sum(1 for x in out if x["act"] == a) for a in ("new", "changed", "same", "bad")}
    body = {"services": edits, "new": new,
            "cats_new": [{"key": "new:" + k, "name": v} for k, v in cats_new.items()]}
    return out, counts, list(cats_new.values()), body


def token(blob: bytes) -> str:
    """Отпечаток файла И нынешнего прайса: прайс поменяли после проверки —
    запуск отказывает, а не применяет предпросмотр, которого никто не видел."""
    now = json.dumps({"services": eng.CONFIG.get("services", []),
                      "cats": eng.CONFIG.get("service_cats") or []},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob + now.encode()).hexdigest()[:32]
