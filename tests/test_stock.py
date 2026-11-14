"""Склад материалов, ступень 1 — сервер (шаг схемы 14, `/api/stock/*`, лист
«De cumpărat», Excel движений, импорт каталога, права, закон 195).

Правила продукта: остаток — сумма журнала, журнал только дописывается
(исправление — `corectie`); минус разрешён; количества — тысячные единицы
расхода, деньги — бани; цены и суммы — только с правом на деньги, регистратура
вносит накладную «fără sume». Засев — путём клиники: материалы, накладные и
списания через API склада, фиша — API фиши; часы — подменные (`harness.Clock`).
"""
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import urllib.parse
import zipfile
from datetime import datetime, timedelta

from harness import (BOT, FIXTURES, Client, Clock, Result, Server, TZ, _rmtree_settled, clinic_today,
                     new_patient, panel_live)
from test_api import NO_KEY

sys.path.insert(0, str(BOT))
from app import db as appdb  # noqa: E402
from app.core import stock as cs  # noqa: E402
from app.core import stock_import as si  # noqa: E402

# суббота 14.11.2026: тестовый файл склада считает сроки «expiră» от этого дня
AT = datetime(2026, 11, 14, 10, 0, tzinfo=TZ)
# копия `design/import-test/stoc-catalog-si-rest.xlsx` (сроки в ней — от 14.11.2026)
XLSX = FIXTURES / "stock" / "stoc-catalog-si-rest.xlsx"


def _j(r) -> dict:
    return json.loads(r.body)


def _field(r) -> tuple:
    return r.msg, _j(r).get("field", "")


def _sql(s: Server, sql: str, *args) -> list:
    con = sqlite3.connect(str(s.dir / "dental.db"))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _get(c: Client, path: str) -> dict:
    r = c.get(path)
    if r.status != 200:
        raise AssertionError(f"{path}: {r.status} {r.body[:300]}")
    return _j(r)["data"]


def _ok(r, code: str):
    if r.msg != code:
        raise AssertionError(f"ждали {code}: {r.status} {r.body[:300]}")
    return _j(r).get("data")


def _item(c: Client, name: str, **kw) -> int:
    body = {"name": name, "unit": "buc", "pack_name": "cutie 50", "pack_qty_milli": 50000, **kw}
    return _ok(c.post_json("/api/stock/item", body), "ok_stock_item")["id"]


def _invoice(c: Client, lines: list, **kw) -> int:
    did = _ok(c.post_json("/api/stock/doc", {"kind": "factura", "nr": "F-1", **kw, "lines": lines}),
              "ok_stock_doc")["id"]
    _ok(c.post_json(f"/api/stock/doc/{did}/close", {}), "ok_stock_invoice")
    return did


def _row(c: Client, item_id: int) -> dict:
    return next(x for x in _get(c, "/api/stock")["items"] if x["id"] == item_id)


def _team(s: Server) -> tuple[Client, Client, Client]:
    """Директор (1111), регистратура «Ana Rusu» (4444), врач d3 (2222)."""
    boss = Client(s.url)
    boss.post("/admin/setup", pin1="1111", pin2="1111")
    for body in ({"uid": "d3", "name": "Dr. Activ Trei", "role": "medic", "doctor_id": "d3", "pin": "2222"},
                 {"uid": "ana", "name": "Ana Rusu", "role": "receptie", "pin": "4444"}):
        r = boss.post_json("/api/settings/users", body)
        if r.status != 200:
            raise AssertionError(f"учётка не заведена: {r.status} {r.body[:200]}")

    def login(pin):
        x = Client(s.url)
        x.post("/admin/login", password=pin, next="/admin")
        return x
    return boss, login("4444"), login("2222")


def _upload(c: Client, path: str, blob: bytes, name: str = "stoc.xlsx", opts: dict | None = None,
            **q) -> object:
    qs = {"name": name, **q}
    if opts is not None:
        qs["opts"] = json.dumps(opts)
    return c._do(f"{path}?{urllib.parse.urlencode(qs)}", blob, {"Content-Type": "application/octet-stream"})


# ---------- правила чистыми функциями ----------

def suite_rules(res: Result) -> None:
    """Остаток, средняя, партии, отмена, предложение «купить», разбор импорта — без сервера."""
    def mv(i, kind, q, cost=None, lot="", exp=None, reason="", fixes=None):
        return {"id": i, "kind": kind, "qty_milli": q, "cost_bani": cost, "lot": lot, "expiry": exp,
                "reason": reason, "fixes": fixes}
    moves = [mv(1, "intrare", 10000, 10000, lot="A", exp="2027-01-01"),
             mv(2, "intrare", 10000, 30000, lot="B", exp="2026-12-01"),
             mv(3, "consum", -3000, -6000, lot="A"),
             mv(4, "casare", -2000, -4000)]
    lv = cs.level(moves, set(), {})
    res.check("остаток — сумма журнала, средняя — по приходам с суммой (бани за 1)",
              (lv["qty_milli"], lv["avg_bani"]), (15000, 2000.0))
    res.check("партии: расход с лотом — из своей, без лота — ближайшая по сроку",
              [(x["lot"], x["qty_milli"]) for x in lv["lots"]], [("A", 7000), ("B", 8000)])
    res.check("ближайший срок того, что лежит", lv["exp_on"], "2026-12-01")
    undone = cs.level(moves + [mv(5, "corectie", 3000, 6000, lot="A", reason="anulare", fixes=3)],
                      {3}, {})
    res.check("отменённое движение и его отмена гасят друг друга (и в партиях)",
              (undone["qty_milli"], [(x["lot"], x["qty_milli"]) for x in undone["lots"]]),
              (18000, [("A", 10000), ("B", 8000)]))
    nosum = cs.level([mv(1, "intrare", 4000, None), mv(2, "intrare", 4000, 8000)], set(), {1: 4000})
    res.check("сумма дописана позже (строка suma) — входит в среднюю", nosum["avg_bani"], 1500.0)
    res.check("без приходов с суммой средней нет", cs.level([mv(1, "intrare", 4000, None)], set(), {})["avg_bani"],
              None)
    res.check("минус — просто отрицательный остаток", cs.level([mv(1, "consum", -5000)], set(), {})["qty_milli"],
              -5000)
    it = {"min_milli": 25000, "pack_qty_milli": 50000}
    res.check("«De cumpărat»: до двух порогов целыми упаковками; выше порога — 0",
              (cs.buy_packs(it, 10000), cs.buy_packs(it, -60000), cs.buy_packs(it, 25000),
               cs.buy_packs({"min_milli": None, "pack_qty_milli": 1}, 0)), (1, 3, 0, 0))
    res.check("ключ двойника: регистр, диакритика, пробелы",
              cs.norm_name("  MĂNUȘI   nitril M "), cs.norm_name("Manusi nitril m"))
    res.check("шапка файла узнаётся по словам",
              [si.guess_field(x) for x in ("Denumire", "Categorie", "UM", "Ambalaj", "Buc./g în ambalaj", "Stoc",
                                            "Stoc minim", "Preț", "Valabil până la", "Raft", "Lot", "Furnizor")],
              ["name", "cat", "unit", "pack", "pack_qty", "qty", "min", "price", "exp", "raft", "lot", "supplier"])
    res.check("даты в нескольких видах; «06.2027» — последний день; «iunie 2027» — не дата",
              [si.parse_date(x) for x in ("05.12.2026", "5/12/26", "2026-12-05", "06.2027", "iunie 2027", "",
                                          "31.02.2027")],
              ["2026-12-05", "2026-12-05", "2026-12-05", "2027-06-30", False, None, False])
    recs = [{"line": n, "name": nm, "err": "", "act": "new", "similar": None, "choice": "new", "qty_milli": 1000}
            for n, nm in ((2, "Ubistesin Forte 4%"), (3, "Ubistesin Forte 4% (articaină)"), (4, "Filtek Z550 A2"),
                          (5, "Filtek Z 550 A2"), (6, "Mănuși nitril M"), (7, "MĂNUȘI NITRIL M"),
                          (8, "Manusi nitril L"), (9, "Septanest 1:100 000"))]
    si.analyse(recs, [{"id": 7, "name": "Septanest 1:100 000"}], {5: "same"})
    res.check("сверка: похожие, точный повтор, уже в каталоге, выбор «тот же»",
              [(r["line"], r["act"], (r["similar"] or {}).get("line") or (r["similar"] or {}).get("id"))
               for r in recs],
              [(2, "new", None), (3, "new", 2), (4, "new", None), (5, "merged", 4), (6, "new", None),
               (7, "merged", None), (8, "new", None), (9, "exists", None)])
    res.check("виды и причины — перечислением, без пересечения",
              (set(appdb.STOCK_DOC_OPEN) & set(appdb.STOCK_DOC_CLOSED),
               set(appdb.STOCK_OUT_REASONS) & set(appdb.STOCK_FIX_REASONS),
               set(appdb.STOCK_UNDOES) <= set(appdb.STOCK_FIX_REASONS)), (set(), set(), True))


# ---------- схема ----------

_TABLES = {"stock_suppliers", "stock_items", "stock_docs", "stock_doc_lines", "stock_moves"}


def suite_schema(res: Result) -> None:
    """Шаг 14: пять таблиц и индексы, каждый оператор IF NOT EXISTS; имени пациента в журнале нет."""
    step = next((k for k, v in appdb.MIGRATIONS.items() if v is appdb.STOCK_DDL), None)
    res.ok("STOCK_DDL — шаг миграции, и он последний", step == appdb.SCHEMA_VERSION == 14, f"шаг {step}")
    res.ok("каждый оператор — IF NOT EXISTS (шаг переживает повтор)",
           all(" IF NOT EXISTS " in x for x in appdb.STOCK_DDL), "")
    res.ok("уникальных индексов uq_ нет (uq_ — слотовые)", not any(" uq_" in x for x in appdb.STOCK_DDL), "")
    moves = next(x for x in appdb.STOCK_DDL if "TABLE IF NOT EXISTS stock_moves(" in x)
    res.ok("в журнале нет имени пациента (только patient_id), есть место и партия",
           "patient_id" in moves and "patient_name" not in moves and "\n  place " in moves
           and "\n  lot " in moves and "\n  qty_milli INTEGER NOT NULL" in moves, moves[:200])
    with Clock(AT), Server() as s:
        names = {r[0] for r in _sql(s, "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'stock%'")}
        res.check("свежая база получила таблицы", names, _TABLES)
        res.check("версия схемы", _sql(s, "SELECT value FROM schema_meta WHERE key='version'")[0][0],
                  str(appdb.SCHEMA_VERSION))


def suite_retry(res: Result) -> None:
    """Шаг 14 приходит повторно: всё уже есть, оборвался посередине, обычное обновление с 13."""
    drops = {"всё уже есть": (),
             "оборвался после каталога": ("DROP TABLE stock_moves", "DROP INDEX ix_stock_lines_doc"),
             "обычное обновление": ("DROP TABLE stock_moves", "DROP TABLE stock_doc_lines", "DROP TABLE stock_docs",
                                    "DROP TABLE stock_items", "DROP TABLE stock_suppliers")}
    for tag, todo in drops.items():
        work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_stock_"))
        try:
            with Server(dir_=work):
                pass
            con = sqlite3.connect(str(work / "dental.db"))
            try:
                for sql in todo:
                    con.execute(sql)
                con.execute("UPDATE schema_meta SET value = '13' WHERE key = 'version'")
                con.commit()
            finally:
                con.close()
            with Server(dir_=work) as s:
                c = Client(s.url).login()
                res.check(f"{tag}: версия доведена", _sql(s, "SELECT value FROM schema_meta WHERE key='version'")[0][0],
                          "14")
                iid = _item(c, "Retry Material")
                _invoice(c, [{"item_id": iid, "qty_milli": 5000, "cost_bani": 1000}])
                res.check(f"{tag}: склад отвечает и пишет", _row(c, iid)["qty_milli"], 5000)
        finally:
            _rmtree_settled(work)


# ---------- поток ----------

def suite_flow(res: Result) -> None:
    """Материал → накладная (черновик → журнал) → списание в минус → «Deschis» и отмена →
    инвентаризация → суммы позже → сторно и его запрет после инвентаризации."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        sid = _ok(c.post_json("/api/stock/supplier", {"name": "Dental Supply Moldova", "phone": "022 000 000"}),
                  "ok_stock_supplier")["id"]
        res.check("двойник поставщика без регистра — 409 stock_dup name",
                  _field(c.post_json("/api/stock/supplier", {"name": "dental supply MOLDOVA"})), ("stock_dup", "name"))
        sep = _item(c, "Septanest 1:100 000", min_milli=25000, costly=True, track_expiry=True, supplier_id=sid,
                    cat="Anestezice")
        res.check("двойник материала (диакритика, пробелы) — 409", _field(c.post_json(
            "/api/stock/item", {"name": "septanest  1:100 000", "unit": "buc"})), ("stock_dup", "name"))
        res.check("единица не из списка — stock_bad unit",
                  _field(c.post_json("/api/stock/item", {"name": "Gel", "unit": "tub"})), ("stock_bad", "unit"))
        row = _row(c, sep)
        res.check("новый материал: остаток 0, ниже порога, предложение 1 коробка, удалить можно",
                  (row["qty_milli"], row["low"], row["buy_packs"], row["moves"], row["supplier"]),
                  (0, True, 1, 0, "Dental Supply Moldova"))
        _ok(c.post_json("/api/stock/order", {"ids": [sep]}), "ok_stock_order")
        res.check("«Comandat»: отметка с днём и кем", (lambda o: (o["on"], o["days"], o["late"]))(_row(c, sep)["ordered"]),
                  (AT.date().isoformat(), 0, False))

        did = _ok(c.post_json("/api/stock/doc", {"kind": "factura", "nr": "SP 7781", "supplier_id": sid,
                                                 "lines": [{"item_id": sep, "qty_milli": 100000, "cost_bani": 140000,
                                                            "lot": "L1", "exp_on": "2027-01-12"}]}), "ok_stock_doc")["id"]
        res.check("черновик склад не меняет", _row(c, sep)["qty_milli"], 0)
        res.check("черновик правится: строка по id, сумма та же",
                  c.post_json(f"/api/stock/doc/{did}", {"nr": "SP 7782"}).msg, "ok_stock_doc")
        doc = _get(c, f"/api/stock/doc/{did}")["doc"]
        res.check("модель черновика: строка, цена единицы, поставщик снимком",
                  (doc["status"], doc["nr"], doc["supplier"], doc["lines"][0]["unit_bani"], doc["lines"][0]["qty_milli"]),
                  ("ciorna", "SP 7782", "Dental Supply Moldova", 1400.0, 100000))
        _ok(c.post_json(f"/api/stock/doc/{did}/close", {}), "ok_stock_invoice")
        row = _row(c, sep)
        res.check("накладная вошла: остаток, средняя, партия со сроком, отметка «Comandat» снята",
                  (row["qty_milli"], row["avg_bani"], row["lots"], row["ordered"], row["low"]),
                  (100000, 1400.0, [{"lot": "L1", "exp_on": "2027-01-12", "qty_milli": 100000}], None, False))
        res.check("закрытую не правят — 409 stock_doc_closed",
                  c.post_json(f"/api/stock/doc/{did}", {"nr": "x"}).msg, "stock_doc_closed")
        res.check("закрытую не удаляют", c.post_json(f"/api/stock/doc/{did}/delete", {}).msg, "stock_doc_closed")
        res.check("единица материала с движениями не меняется — 409",
                  c.post_json("/api/stock/item", {"id": sep, "unit": "g"}).msg, "stock_unit_locked")
        res.check("материал с движениями не удаляется — 409",
                  c.post_json(f"/api/stock/item/{sep}/delete", {}).msg, "stock_has_moves")

        pid = new_patient(c, "Ion Lot", "069200100")
        res.check("на пациента без pid — stock_bad pid", _field(c.post_json(
            "/api/stock/out", {"item_id": sep, "qty_milli": 1000, "reason": "pacient"})), ("stock_bad", "pid"))
        res.check("«altul» без заметки — stock_bad note", _field(c.post_json(
            "/api/stock/out", {"item_id": sep, "qty_milli": 1000, "reason": "altul"})), ("stock_bad", "note"))
        out = _ok(c.post_json("/api/stock/out", {"item_id": sep, "qty_milli": 2000, "reason": "pacient",
                                                 "pid": pid, "lot": "L1"}), "ok_stock_out")
        res.check("списание на пациента: остаток после, не минус", (out["qty_milli"], out["neg"]), (98000, False))
        mv = _get(c, f"/api/stock/moves?pid={pid}")["moves"]
        res.check("в журнале: Pe pacient, лот, срок партии, цена по средней, пациент ссылкой",
                  [(m["kind_label"], m["lot"], m["exp_on"], m["cost_bani"], m["patient"], m["undoable"]) for m in mv],
                  [("Pe pacient", "L1", "2027-01-12", -2800, "Ion Lot", True)])
        res.ok("летопись фиши: материал и лот",
               any("Septanest" in t and "lot L1" in t for (t,) in _sql(
                   s, "SELECT text FROM activity WHERE patient_id = ? AND kind = 'stock'", pid)), "")
        big = _ok(c.post_json("/api/stock/out", {"item_id": sep, "qty_milli": 120000, "reason": "expirat"}),
                  "ok_stock_out")
        res.check("минус разрешён: остаток красный", (big["qty_milli"], big["neg"], _row(c, sep)["neg"]),
                  (-22000, True, True))
        _ok(c.post_json(f"/api/stock/move/{big['id']}/undo", {"why": "greșit"}), "ok_stock_undo")
        res.check("отмена: остаток вернулся, движение осталось с undone", (_row(c, sep)["qty_milli"], [
            (m["undone"], m["undoable"]) for m in _get(c, "/api/stock/moves?kind=casare")["moves"]]),
            (98000, [(True, False)]))
        res.check("второй раз не отменяется — 409",
                  c.post_json(f"/api/stock/move/{big['id']}/undo", {}).msg, "stock_no_undo")
        res.check("строку накладной отменой движения не снять — 409 (только сторно)",
                  c.post_json(f"/api/stock/move/{_get(c, '/api/stock/moves?kind=intrare')['moves'][0]['id']}/undo",
                              {}).msg, "stock_no_undo")

        glov = _item(c, "Mănuși nitril M", unit="cutie", pack_name="cutie 100", pack_qty_milli=1000, bulk=True,
                     shelf_milli=3000, min_milli=4000)
        res.check("новый материал с «acum pe raft» — начальный остаток строкой журнала",
                  (_row(c, glov)["qty_milli"], _row(c, glov)["bulk"]), (3000, True))
        op = _ok(c.post_json("/api/stock/open", {"item_id": glov}), "ok_stock_open")
        res.check("«Deschis»: минус одна упаковка", op["qty_milli"], 2000)
        _ok(c.post_json(f"/api/stock/move/{op['id']}/undo", {}), "ok_stock_undo")
        res.check("«Anulează» после «Deschis» — снова 3", _row(c, glov)["qty_milli"], 3000)

        inv = _ok(c.post_json("/api/stock/doc", {"kind": "inventar", "cats": ["Anestezice"]}), "ok_stock_doc")["id"]
        lines = _get(c, f"/api/stock/doc/{inv}")["doc"]["lines"]
        res.check("инвентаризация по категории: строки — её материалы, «în program» сейчас",
                  [(ln["item_id"], ln["prog_milli"], ln["qty_milli"]) for ln in lines], [(sep, 98000, None)])
        _ok(c.post_json(f"/api/stock/doc/{inv}", {"lines": [{"id": lines[0]["id"], "item_id": sep,
                                                             "qty_milli": 95000}]}), "ok_stock_doc")
        _ok(c.post_json(f"/api/stock/doc/{inv}/close", {}), "ok_stock_inventory")
        res.check("«Aplică»: разница строкой журнала, остаток = на полке",
                  (_row(c, sep)["qty_milli"], [(m["qty_milli"], m["note"]) for m in
                                               _get(c, "/api/stock/moves?kind=inventar")["moves"] if m["item_id"] == sep]),
                  (95000, [(-3000, "pe raft mai puțin")]))
        res.check("закрытая инвентаризация помнит «în program» на момент «Aplică»",
                  _get(c, f"/api/stock/doc/{inv}")["doc"]["lines"][0]["diff_milli"], -3000)
        res.check("сторно накладной после инвентаризации по её материалу — 409 stock_inv_after",
                  c.post_json(f"/api/stock/doc/{did}/storno", {"why": "greșit"}).msg, "stock_inv_after")

        comp = _item(c, "Filtek Z550 A2", unit="g", pack_name="seringă 4 g", pack_qty_milli=4000)
        f2 = _invoice(c, [{"item_id": comp, "qty_milli": 8000}, {"item_id": glov, "qty_milli": 5000,
                                                                  "cost_bani": 47500}])
        d2 = _get(c, f"/api/stock/doc/{f2}")["doc"]
        res.check("строка без суммы — накладная «fără sume», средней у материала нет",
                  (d2["no_sums"], _row(c, comp)["avg_bani"]), (True, None))
        _ok(c.post_json(f"/api/stock/doc/{f2}/sums", {"lines": [{"id": d2["lines"][0]["id"], "cost_bani": 140000}]}),
            "ok_stock_sums")
        res.check("сумма дописана: средняя есть, количество то же, «fără sume» снята",
                  (_row(c, comp)["avg_bani"], _row(c, comp)["qty_milli"],
                   _get(c, f"/api/stock/doc/{f2}")["doc"]["no_sums"]), (17500.0, 8000, False))
        res.check("в журнал сумма — строкой corectie «Sumă completată» с нулевым количеством",
                  [(m["qty_milli"], m["cost_bani"], m["reason_label"]) for m in
                   _get(c, f"/api/stock/moves?item={comp}&kind=corectie")["moves"]], [(0, 140000, "Sumă completată")])
        res.check("сторно без причины — stock_bad why",
                  _field(c.post_json(f"/api/stock/doc/{f2}/storno", {})), ("stock_bad", "why"))
        _ok(c.post_json(f"/api/stock/doc/{f2}/storno", {"why": "factură greșită"}), "ok_stock_storno")
        res.check("сторно: остатки назад, документ «Anulat», строки остались",
                  (_row(c, comp)["qty_milli"], _row(c, glov)["qty_milli"],
                   _get(c, f"/api/stock/doc/{f2}")["doc"]["status_label"],
                   _sql(s, "SELECT COUNT(*) FROM stock_moves WHERE doc_id = ?", f2)[0][0]), (0, 3000, "Anulat", 5))
        res.check("сторно дважды — 409", c.post_json(f"/api/stock/doc/{f2}/storno", {"why": "x"}).msg,
                  "stock_doc_closed")

        dr = _ok(c.post_json("/api/stock/doc", {"kind": "factura", "supplier_name": "Implant Prof",
                                                "lines": [{"item_id": comp, "qty_milli": 4000}]}), "ok_stock_doc")["id"]
        res.check("черновик с новым поставщиком — поставщик заведён",
                  _sql(s, "SELECT COUNT(*) FROM stock_suppliers WHERE name = 'Implant Prof'")[0][0], 1)
        res.check("черновик удаляется", c.post_json(f"/api/stock/doc/{dr}/delete", {}).msg, "ok_stock_doc_del")
        res.check("пустая накладная не регистрируется — stock_empty", c.post_json(
            f"/api/stock/doc/{_ok(c.post_json('/api/stock/doc', {'kind': 'factura'}), 'ok_stock_doc')['id']}/close",
            {}).msg, "stock_empty")
        tmp = _item(c, "Material de probă")
        res.check("материал без движений удаляется (мягко) и пропадает из списка",
                  (c.post_json(f"/api/stock/item/{tmp}/delete", {}).msg,
                   any(x["id"] == tmp for x in _get(c, "/api/stock")["items"])), ("ok_stock_item_del", False))
        res.check("выключенный материал не списывается — 409 stock_item_off", (
            c.post_json("/api/stock/item", {"id": comp, "active": False}).msg,
            c.post_json("/api/stock/out", {"item_id": comp, "qty_milli": 1, "reason": "defect"}).msg),
            ("ok_stock_item", "stock_item_off"))
        res.check("журнал только дописывался: ни одной строки не стёрто",
                  _sql(s, "SELECT COUNT(*) = MAX(id) FROM stock_moves")[0][0], 1)


# ---------- списки и плашка ----------

def suite_lists(res: Result) -> None:
    """«De cumpărat» по поставщикам, «Comandat» гаснет через N дней, сроки, плашка главной."""
    with Clock(AT) as clock, Server() as s:
        c = Client(s.url).login()
        sid = _ok(c.post_json("/api/stock/supplier", {"name": "MedDent", "phone": "079"}), "ok_stock_supplier")["id"]
        a = _item(c, "Alginat", unit="g", pack_name="pachet 500 g", pack_qty_milli=500000, min_milli=400000,
                  supplier_id=sid)
        _item(c, "Ac 27G", min_milli=100000, shelf_milli=20000)
        e = _item(c, "Duraphat", unit="ml", pack_qty_milli=10000, track_expiry=True)
        _invoice(c, [{"item_id": a, "qty_milli": 100000, "cost_bani": 5000},
                     {"item_id": e, "qty_milli": 10000, "cost_bani": 30000, "exp_on": "2026-12-20"}])
        buy = _get(c, "/api/stock/buy")
        res.check("«De cumpărat»: по поставщикам, без поставщика — последним; предложение упаковками",
                  [(g["supplier"], [(r["name"], r["buy_packs"]) for r in g["rows"]]) for g in buy["groups"]],
                  [("MedDent", [("Alginat", 2)]), ("Fără furnizor", [("Ac 27G", 4)])])
        res.check("оценка — директору (упаковки × средняя)", buy["groups"][0]["rows"][0]["est_bani"], 50000)
        _ok(c.post_json("/api/stock/order", {"ids": [a]}), "ok_stock_order")
        res.check("отметка не прячет строку и не убирает из «sub prag»",
                  (_get(c, "/api/stock/buy")["counts"], _get(c, "/api/stock")["counts"]["low"]),
                  ({"low": 2, "ordered": 1, "late": 0}, 2))
        row = _row(c, e)
        res.check("срок через 36 дней — «expiră în curând»", (row["exp_days"], row["soon"], row["expired"]),
                  (36, True, False))
        live = panel_live(c)["stock"]
        res.check("плашка главной: ниже порога, из них заказано, сроки",
                  (live["low"], live["ordered"], live["soon"], [x["name"] for x in live["exp_items"]]),
                  (2, 1, 1, ["Duraphat"]))
        res.check("плашка детерминирована в пределах дня", panel_live(c)["stock"], live)
        res.check("порог в настройках: 30 дней — срок уже не «скоро»", (
            c.post_json("/api/stock/prefs", {"exp_days": 30}).msg, _row(c, e)["soon"]), ("ok_stock_prefs", False))
        res.check("настройка вне границ — stock_bad", _field(c.post_json("/api/stock/prefs", {"order_days": 0})),
                  ("stock_bad", "order_days"))
        clock.set(AT + timedelta(days=8))
        o = _row(c, a)["ordered"]
        res.check("через 8 дней без накладной отметка истекла — «n-a venit»", (o["days"], o["late"]), (8, True))
        res.check("истёкшая отметка — не «din care comandate»: везде отдельным late",
                  (_get(c, "/api/stock/buy")["counts"], (lambda k: (k["ordered"], k["late"]))(_get(c, "/api/stock")["counts"]),
                   (lambda k: (k["ordered"], k["late"]))(panel_live(c)["stock"])),
                  ({"low": 2, "ordered": 0, "late": 1}, (0, 1), (0, 1)))
        clock.set(AT + timedelta(days=40))
        res.check("срок прошёл — «expirat»", (_row(c, e)["expired"], panel_live(c)["stock"]["expired"]), (True, 1))
        _ok(c.post_json(f"/api/stock/order/{a}/cancel", {}), "ok_stock_unorder")
        res.check("«Anulează» отметки", _row(c, a)["ordered"], None)
        sheet = c.get(f"/admin/stoc/cumparat/tipar?q={a}:5&back=https://evil.example/")
        res.check("лист: отмеченное с количеством экрана, чужой «back» заменён",
                  (sheet.status, "Alginat" in sheet.body, "Ac 27G" in sheet.body, "<b>5</b>" in sheet.body,
                   "evil.example" in sheet.body), (200, True, False, True, False))
        full = c.get("/admin/stoc/cumparat/tipar").body
        res.check("лист без отбора — весь список, телефон поставщика", ("Ac 27G" in full, "079" in full), (True, True))
        x = c.get(f"/admin/stoc/miscari.xlsx?month={AT.strftime('%Y-%m')}")
        z = zipfile.ZipFile(io.BytesIO(x.raw))
        sh = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        res.check("Excel месяца: движения есть, сумма — директору, пациента нет",
                  (x.status, "Alginat" in sh, "Suma, lei" in sh, "Pacient" in sh), (200, True, True, False))


# ---------- права ----------

def suite_rights(res: Result) -> None:
    """Склад — директор и регистратура; врачу нет. Цены и суммы — только директору;
    регистратура вносит накладную без сумм, директор дописывает."""
    with Clock(AT), Server(env=NO_KEY) as s:
        boss, ana, med = _team(s)
        res.check("врачу склад закрыт — 403 no_access", (lambda r: (r.status, r.msg))(med.get("/api/stock")),
                  (403, "no_access"))
        res.check("врач не пишет", med.post_json("/api/stock/item", {"name": "X", "unit": "buc"}).status, 403)
        res.check("…и страницы-листа нет", med.get("/admin/stoc/cumparat/tipar").status in (303, 403), True)
        iid = _item(ana, "Bio-Gide 25x25", costly=True)
        did = _ok(ana.post_json("/api/stock/doc", {"kind": "factura", "lines": [
            {"item_id": iid, "qty_milli": 2000, "cost_bani": 999999}]}), "ok_stock_doc")["id"]
        res.check("сумма регистратуры МОЛЧА не записана",
                  _sql(s, "SELECT cost_bani FROM stock_doc_lines WHERE doc_id = ?", did), [(None,)])
        _ok(ana.post_json(f"/api/stock/doc/{did}/close", {}), "ok_stock_invoice")
        d_ana = _get(ana, f"/api/stock/doc/{did}")["doc"]
        res.check("регистратура: «fără sume», ни сумм, ни цен в ответах",
                  (d_ana["no_sums"], "total_bani" in d_ana, "cost_bani" in d_ana["lines"][0],
                   "avg_bani" in _row(ana, iid), "cost_bani" in _get(ana, "/api/stock/moves")["moves"][0]),
                  (True, False, False, False, False))
        res.check("can у регистратуры", _get(ana, "/api/stock")["can"], {"stock": True, "money": False,
                                                                        "settings": False})
        res.check("регистратура не дописывает суммы и не сторнирует — 403",
                  (ana.post_json(f"/api/stock/doc/{did}/sums", {"lines": []}).status,
                   ana.post_json(f"/api/stock/doc/{did}/storno", {"why": "x"}).status), (403, 403))
        res.check("регистратура не правит настройки склада — 403",
                  ana.post_json("/api/stock/prefs", {"exp_days": 30}).status, 403)
        line = _get(boss, f"/api/stock/doc/{did}")["doc"]["lines"][0]
        _ok(boss.post_json(f"/api/stock/doc/{did}/sums", {"lines": [{"id": line["id"], "cost_bani": 300000}]}),
            "ok_stock_sums")
        res.check("директор дописал: цена у материала, «fără sume» снята",
                  (_row(boss, iid)["avg_bani"], _get(boss, f"/api/stock/doc/{did}")["doc"]["no_sums"],
                   _get(boss, f"/api/stock/doc/{did}")["doc"]["can_storno"]), (150000.0, False, True))
        res.check("регистратура видит накладную без кнопки сторно",
                  _get(ana, f"/api/stock/docs?kind=factura")["docs"][0]["can_storno"], False)
        pid = new_patient(ana, "Pacient Implant", "069300100")
        res.check("что ушло пациенту — видит и врач (медзапись фиши)", (
            _ok(ana.post_json("/api/stock/out", {"item_id": iid, "qty_milli": 1000, "reason": "pacient", "pid": pid,
                                                 "lot": "BG-77"}), "ok_stock_out")["qty_milli"],
            [(r["item"], r["lot"], r["qty_milli"]) for r in _get(med, f"/api/stock/patient/{pid}")["rows"]]),
            (1000, [("Bio-Gide 25x25", "BG-77", 1000)]))
        live = panel_live(med)
        res.check("плашки склада у врача нет", live.get("stock"), None)


# ---------- импорт ----------

def suite_import(res: Result) -> None:
    """Тестовый файл `stoc-catalog-si-rest.xlsx`: 54 новых, 1 повтор, 5 ошибок, 2 «похоже на…»;
    повторный файл — отказ; отмена — пока нет других движений."""
    blob = XLSX.read_bytes()
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        res.check("модель импорта: поля и потолки", (lambda d: (len(d["fields"]), d["limits"]["rows"], d["imports"]))(
            _get(c, "/api/stock/import")), (12, 2000, []))
        r = _upload(c, "/api/stock/import/check", blob)
        d = _j(r)["data"]
        res.check("предпросмотр — сырые ячейки первых строк под шапкой",
                  ([p["line"] for p in d["preview"]], d["preview"][0]["cells"][:3], len(d["preview"][0]["cells"])),
                  ([2, 3, 4, 5, 6, 7], ["Ubistesin Forte 4%", "Anestezice", "buc"], 12))
        res.check("колонки узнаны сами (все двенадцать)", sorted(d["opts"]["cols"].values()),
                  sorted(f for f, _ in si.FIELDS))
        res.check("счёт проверки", d["counts"], {"new": 54, "exists": 0, "merged": 1, "errors": 5, "rests": 53,
                                                 "similar": 2})
        errs = {x["line"]: x["err_text"] for x in d["rows"] if x["act"] == "error"}
        res.check("пять ошибок с причинами", errs, {11: "fără denumire", 22: "unitate necunoscută „tub”",
                                                    33: "restul nu e număr", 44: "cantitatea în ambalaj nu e număr",
                                                    55: "data nu e zi.lună.an"})
        by = {x["line"]: x for x in d["rows"]}
        res.check("«похоже на…»: Ubistesin (articaină) и Filtek Z 550",
                  {ln: by[ln]["similar"]["line"] for ln in by if by[ln]["similar"]}, {3: 2, 15: 12})
        res.check("точный повтор в файле — одна позиция", (by[54]["act"], by[51]["act"]), ("merged", "new"))
        res.check("дробные, срок, лот, поставщик, полка — прочитаны",
                  (by[2]["qty_milli"], by[2]["pack_qty_milli"], by[2]["exp_on"], by[2]["lot"], by[2]["supplier"],
                   by[2]["raft"], by[2]["price_bani"]),
                  (64000, 50000, "2027-03-30", "UB2403", "Dental Supply Moldova", "dulap 1", 1450.0))
        res.check("run с чужим токеном — 409 stock_import_stale",
                  _upload(c, "/api/stock/import/run", blob, token="x").msg, "stock_import_stale")
        opts = {"choices": {"15": "same"}}
        tok = _j(_upload(c, "/api/stock/import/check", blob, opts=opts))["data"]["token"]
        run = _upload(c, "/api/stock/import/run", blob, opts=opts, token=tok)
        got = _ok(run, "ok_stock_import")
        res.check("импорт: материалы, начальные остатки, пропуски", (got["created"], got["rests"], got["skipped"]),
                  (53, 54, 5))
        items = {x["name"]: x for x in _get(c, "/api/stock")["items"]}
        res.check("выбор «тот же»: Filtek Z550 A2 = 12 + 4 g, одной позицией",
                  (items["Filtek Z550 A2"]["qty_milli"], "Filtek Z 550 A2" in items), (16000, False))
        res.check("повтор Mănuși nitril M сложен; поставщики заведены; лот → «scump», срок → «termen»",
                  (items["Mănuși nitril M"]["qty_milli"], len(_get(c, "/api/stock")["suppliers"]),
                   items["Ubistesin Forte 4%"]["costly"], items["Ubistesin Forte 4%"]["track_expiry"],
                   items["Mănuși nitril M"]["bulk"]), (11000, 3, True, True, True))
        res.check("сроки файла от 14.11: просрочен Duraphat, скоро — три",
                  (items["Lac cu fluor Duraphat"]["expired"],
                   sorted(n for n, x in items.items() if x["soon"])),
                  (True, sorted(["Filtek Z550 A2", "Cement endodontic AH Plus", "Septanest 1:100 000"])))
        res.check("ниже порога — семь (повторы сложены), нулевой остаток — Septanest 1:200 000",
                  (sum(x["low"] for x in items.values()), items["Septanest 1:200 000"]["qty_milli"]), (7, 0))
        res.check("цена из файла — средняя директора", items["Ubistesin Forte 4%"]["avg_bani"], 1450.0)
        again = _j(_upload(c, "/api/stock/import/check", blob))["data"]
        res.check("тот же файл снова: «уже импортирован», заведённое — «deja în catalog», похожее — снова новое",
                  (again["dup"] is not None, again["counts"]["exists"], again["counts"]["new"]), (True, 54, 1))
        res.check("…и run отказывает — 409 stock_import_dup",
                  _upload(c, "/api/stock/import/run", blob, token=again["token"]).msg, "stock_import_dup")
        hist = _get(c, "/api/stock/import")["imports"]
        res.check("история импорта", [(h["created"], h["can_undo"]) for h in hist], [(53, True)])
        _ok(c.post_json("/api/stock/out", {"item_id": items["Ubistesin Forte 4%"]["id"], "qty_milli": 1000,
                                           "reason": "defect"}), "ok_stock_out")
        res.check("после другого движения отмена закрыта — 409 stock_import_used", (
            c.post_json(f"/api/stock/import/{got['id']}/undo", {}).msg,
            _get(c, "/api/stock/import")["imports"][0]["can_undo"]), ("stock_import_used", False))
        mv = _get(c, "/api/stock/moves?kind=casare")["moves"][0]
        _ok(c.post_json(f"/api/stock/move/{mv['id']}/undo", {}), "ok_stock_undo")
        res.check("отмена своего списания движение не стирает — импорт всё ещё занят",
                  c.post_json(f"/api/stock/import/{got['id']}/undo", {}).msg, "stock_import_used")

    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        tok = _j(_upload(c, "/api/stock/import/check", blob))["data"]["token"]
        got = _ok(_upload(c, "/api/stock/import/run", blob, token=tok), "ok_stock_import")
        _ok(c.post_json(f"/api/stock/import/{got['id']}/undo", {}), "ok_stock_import_undo")
        res.check("отмена импорта: материалов, остатков и поставщиков нет, документ «Anulat»",
                  (len(_get(c, "/api/stock")["items"]), len(_get(c, "/api/stock")["suppliers"]),
                   _get(c, "/api/stock/import")["imports"][0]["undone"],
                   _sql(s, "SELECT SUM(qty_milli) FROM stock_moves")[0][0]), (0, 0, True, 0))
        tok = _j(_upload(c, "/api/stock/import/check", blob))["data"]["token"]
        res.check("после отмены тот же файл импортируется снова",
                  _upload(c, "/api/stock/import/run", blob, token=tok).msg, "ok_stock_import")
        res.check("не таблица — 422 stock_not_table",
                  (lambda r: (r.status, r.msg))(_upload(c, "/api/stock/import/check", b"\x00\x01garbage", "x.xlsx")),
                  (422, "stock_not_table"))
        res.check("опции не читаются — 422", c._do("/api/stock/import/check?name=x.xlsx&opts=%7Bbad", blob, {
            "Content-Type": "application/octet-stream"}).msg, "stock_import_opts")


# ---------- закон 195 ----------

def suite_195(res: Result) -> None:
    """Материал на пациента держит фишу от физического стирания; копия несёт его с лотом."""
    res.check("состав удаления: журнал склада — ребёнок пациента", "stock_moves" in appdb._PATIENT_CHILD_TABLES,
              True)
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        imp = _item(c, "Implant Osstem TS III 4.0x10", costly=True)
        _invoice(c, [{"item_id": imp, "qty_milli": 3000, "cost_bani": 840000, "lot": "OS-2211"}])
        pid = new_patient(c, "Pavel Implant", "069400100")
        mid = _ok(c.post_json("/api/stock/out", {"item_id": imp, "qty_milli": 1000, "reason": "pacient", "pid": pid,
                                                 "lot": "OS-2211"}), "ok_stock_out")["id"]
        _ok(c.post_json(f"/api/stock/move/{mid}/undo", {}), "ok_stock_undo")
        r = c.get(f"/admin/patient/{pid}/export")
        z = zipfile.ZipFile(io.BytesIO(r.raw))
        data = json.loads(z.read("date-pacient.json"))
        mats = data.get("materiale") or [{}]
        res.check("машинная копия: материал с лотом, без цены, отмена видна",
                  ([(m["material"], m["lot"], m["anulat"]) for m in mats], "cost_bani" in json.dumps(mats)),
                  ([("Implant Osstem TS III 4.0x10", "OS-2211", True), ("Implant Osstem TS III 4.0x10", "OS-2211",
                                                                         True)], False))
        html = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("читаемая копия — раздел материалов", "Materiale folosite (2)" in html, "")
        res.check("материал держит фишу — обезличивание, не удаление",
                  c.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"}).msg, "ok_anon")
        res.check("журнал склада цел под номером фиши",
                  (_sql(s, "SELECT COUNT(*) FROM stock_moves WHERE patient_id = ?", pid)[0][0], _row(c, imp)["qty_milli"]),
                  (2, 3000))
        res.check("в журнале — обезличенное имя (берётся из фиши)",
                  _get(c, f"/api/stock/moves?pid={pid}")["moves"][0]["patient"], f"Pacient anonimizat #{pid}")
        free = new_patient(c, "Fără materiale", "069400101")
        res.check("фиша без материалов и лечения — физическое удаление проходит",
                  c.post_json(f"/api/patients/{free}/erase", {"confirm": "STERG"}).msg, "ok_del")
    res.ok("сегодня прогона — у харнесса", clinic_today() is not None, "")
