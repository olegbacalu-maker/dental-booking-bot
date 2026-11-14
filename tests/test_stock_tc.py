"""Склад, ступень 2 — техкарта услуги и списание по позиции плана (сервер).

Правила продукта: техкарта — в базе по ключу услуги прайса; при `finalizat`
позиции режим клиники решает: `confirmare` (по умолчанию — предложение и окно),
`automat` (сразу), `fara` (ничего). На позицию — один живой набор; «Redeschide»
сторнирует; минус разрешён. Засев — путём клиники: позиция плана из прайса
через API фиши, статусы — кнопками плана и «Consultație».
"""
import json
import sqlite3
import sys
from datetime import datetime

from harness import BOT, Client, Clock, Result, Server, TZ, add_appt, new_patient, panel_live
from test_api import NO_KEY

sys.path.insert(0, str(BOT))
from app import db as appdb  # noqa: E402

AT = datetime(2026, 11, 16, 10, 0, tzinfo=TZ)


def _j(r) -> dict:
    return json.loads(r.body)


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
    return _ok(c.post_json("/api/stock/item", {"name": name, "unit": "buc", **kw}), "ok_stock_item")["id"]


def _stock(c: Client, item_id: int) -> int:
    return next(x for x in _get(c, "/api/stock")["items"] if x["id"] == item_id)["qty_milli"]


def _plan(c: Client, s: Server, pid: int, procedure: str = "Igienizare", service_id: str = "hygiene") -> int:
    r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": procedure, "service_id": service_id,
                                                  "doctor": "Dr. Activ Doi", "tooth": "", "price": "",
                                                  "due_date": ""})
    if r.msg != "ok_card":
        raise AssertionError(f"позиция плана не заведена: {r.status} {r.body[:200]}")
    return _sql(s, "SELECT MAX(id) FROM plan_items WHERE patient_id = ?", pid)[0][0]


def _to(c: Client, pid: int, iid: int, to: str) -> str:
    r = c.post_json(f"/api/patients/{pid}/plan/{iid}/status", {"to": to})
    if r.status != 200:
        raise AssertionError(f"статус {to}: {r.status} {r.body[:200]}")
    return r.msg


def _setup(c: Client) -> tuple[int, int, int, int]:
    """Перчатки (обязательно), флюорид (необязательно), имплант с партиями, архивный."""
    glv = _item(c, "Mănuși nitril M", shelf_milli=10000)
    flu = _item(c, "Lac Duraphat", unit="ml", shelf_milli=5000)
    imp = _item(c, "Implant TS III", costly=True)
    did = _ok(c.post_json("/api/stock/doc", {"kind": "factura", "lines": [
        {"item_id": imp, "qty_milli": 1000, "cost_bani": 800000, "lot": "LATE", "exp_on": "2028-01-01"},
        {"item_id": imp, "qty_milli": 1000, "cost_bani": 800000, "lot": "SOON", "exp_on": "2027-01-01"}]}),
        "ok_stock_doc")["id"]
    _ok(c.post_json(f"/api/stock/doc/{did}/close", {}), "ok_stock_invoice")
    old = _item(c, "Pastă veche")
    _ok(c.post_json("/api/stock/tehcard/hygiene", {"lines": [
        {"item_id": glv, "qty_milli": 2000}, {"item_id": flu, "qty_milli": 500, "optional": True},
        {"item_id": imp, "qty_milli": 1000}, {"item_id": old, "qty_milli": 1000}]}), "ok_stock_tc")
    _ok(c.post_json("/api/stock/item", {"id": old, "active": False}), "ok_stock_item")
    return glv, flu, imp, old


def suite_schema(res: Result) -> None:
    """Техкарта и отметки позиции — в шаге 14; отметка — внук пациента через план."""
    names = " ".join(appdb.STOCK_DDL)
    res.ok("service_materials и stock_plan_marks — в STOCK_DDL, IF NOT EXISTS",
           "TABLE IF NOT EXISTS service_materials(" in names and "TABLE IF NOT EXISTS stock_plan_marks(" in names, "")
    res.check("режимы — перечислением", appdb.STOCK_TC_MODES, ("fara", "confirmare", "automat"))
    res.ok("отметка позиции — во внуках пациента (через план)",
           ("stock_plan_marks", "plan_item_id", "plan_items") in appdb._PATIENT_GRAND_CHILDREN, "")


def suite_tehcard(res: Result) -> None:
    """Техкарта: весь список разом, двойник и чужой материал — отказ, архивный — предупреждение,
    замена материала во всех услугах."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        a = _item(c, "Mănuși M")
        b = _item(c, "Mănuși L")
        g = _item(c, "Gel", unit="g")
        res.check("неизвестная услуга — 404 stock_service_gone",
                  c.post_json("/api/stock/tehcard/nope", {"lines": []}).msg, "stock_service_gone")
        res.check("материал дважды — stock_bad lines", (lambda r: (r.msg, _j(r).get("field")))(c.post_json(
            "/api/stock/tehcard/hygiene", {"lines": [{"item_id": a, "qty_milli": 1}, {"item_id": a, "qty_milli": 2}]})),
            ("stock_bad", "lines"))
        _ok(c.post_json("/api/stock/item", {"id": b, "active": False}), "ok_stock_item")
        res.check("архивный материал — можно, но в warn", _ok(c.post_json("/api/stock/tehcard/consult", {"lines": [
            {"item_id": a, "qty_milli": 1000}, {"item_id": b, "qty_milli": 1000}]}), "ok_stock_tc")["warn"], [b])
        _ok(c.post_json("/api/stock/tehcard/hygiene", {"lines": [{"item_id": b, "qty_milli": 2000}]}), "ok_stock_tc")
        m = {x["id"]: x for x in _get(c, "/api/stock/tehcard")["services"]}
        res.check("модель: строки по услугам прайса, предупреждение об архиве",
                  ([(x["item"], x["qty_milli"], x["active"]) for x in m["consult"]["lines"]], m["consult"]["warn"]),
                  ([("Mănuși M", 1000, True), ("Mănuși L", 1000, False)], 1))
        res.check("замена с другой единицей — 409 stock_tc_unit",
                  c.post_json("/api/stock/tehcard/replace", {"from_item": b, "to_item": g}).msg, "stock_tc_unit")
        res.check("замена во всех услугах; где новый уже есть — количества сложены", (
            _ok(c.post_json("/api/stock/tehcard/replace", {"from_item": b, "to_item": a}), "ok_stock_tc_replace"),
            {sid: [(x["item"], x["qty_milli"]) for x in v["lines"]]
             for sid, v in ((x["id"], x) for x in _get(c, "/api/stock/tehcard")["services"]) if v["lines"]}),
            ({"services": 2}, {"consult": [("Mănuși M", 2000)], "hygiene": [("Mănuși M", 2000)]}))
        res.check("пустой список — техкарты нет", (
            c.post_json("/api/stock/tehcard/consult", {"lines": []}).msg,
            [x["lines"] for x in _get(c, "/api/stock/tehcard")["services"] if x["id"] == "consult"]),
            ("ok_stock_tc", [[]]))


def suite_confirm(res: Result) -> None:
    """Режим по умолчанию — «confirmare»: позиция ждёт подтверждения; подтверждение с правками,
    второй раз не списывается, «Redeschide» возвращает, повторный finalizat снова ждёт; «Fără materiale»."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        glv, flu, imp, old = _setup(c)
        pid = new_patient(c, "Ion Tehcard", "069500100")
        iid = _plan(c, s, pid)
        free = _plan(c, s, pid, "Igienizare + fluor", "hygiene")
        _to(c, pid, iid, "in_lucru")
        res.check("finalizat — код склада «есть что подтвердить»", _to(c, pid, iid, "finalizat"), "ok_stock_tc_pending")
        res.check("свободный текст (без ключа услуги) — ничего не предлагается",
                  (_to(c, pid, free, "in_lucru"), _to(c, pid, free, "finalizat"),
                   _get(c, f"/api/stock/plan/{free}")["state"]), ("", "", "none"))
        m = _get(c, f"/api/stock/plan/{iid}")
        res.check("предложение: режим, состояние, галочки по умолчанию, FEFO-лот у дорогого",
                  (m["mode"], m["state"], [(x["item"], x["on"], x["lot"]) for x in m["lines"]]),
                  ("confirmare", "pending", [("Mănuși nitril M", True, None), ("Lac Duraphat", False, None),
                                             ("Implant TS III", True, "SOON"), ("Pastă veche", False, None)]))
        res.check("партии у дорогого и остаток", ([x["lot"] for x in m["lines"][2]["lots"]], m["lines"][2]["stock_milli"]),
                  (["LATE", "SOON"], 2000))
        res.check("plan-pending фиши — эта позиция", [x["plan_item_id"] for x in
                                                     _get(c, f"/api/stock/plan-pending?pid={pid}")["rows"]], [iid])
        res.check("архивный материал не списывается — 409", c.post_json(f"/api/stock/plan/{iid}/consume", {
            "lines": [{"item_id": old, "qty_milli": 1000}]}).msg, "stock_item_off")
        got = _ok(c.post_json(f"/api/stock/plan/{iid}/consume", {"lines": [
            {"item_id": glv, "qty_milli": 12000}, {"item_id": imp, "qty_milli": 1000, "lot": "LATE"}]}),
            "ok_stock_tc_consume")
        res.check("подтверждено с правкой: минус разрешён и назван", (got["moves"], got["neg"], _stock(c, glv)),
                  (2, [glv], -2000))
        row = _sql(s, "SELECT plan_item_id, patient_id, service_id, doctor_id, doctor, source, reason, lot "
                      "FROM stock_moves WHERE item_id = ? AND kind = 'consum'", imp)
        res.check("движение несёт позицию, пациента, услугу, врача, источник, лот",
                  row, [(iid, pid, "hygiene", "d2", "Dr. Activ Doi", "tehcard", "pacient", "LATE")])
        res.check("второй раз — 409 stock_tc_done", c.post_json(f"/api/stock/plan/{iid}/consume", {
            "lines": [{"item_id": glv, "qty_milli": 1000}]}).msg, "stock_tc_done")
        res.check("состояние done, ожидающих нет; ручная отмена строки техкарты закрыта",
                  (_get(c, f"/api/stock/plan/{iid}")["state"], _get(c, f"/api/stock/plan-pending?pid={pid}")["rows"],
                   [x["undoable"] for x in _get(c, f"/api/stock/plan/{iid}")["moves"]]), ("done", [], [False, False]))
        res.check("Redeschide — материалы вернулись, код склада", (_to(c, pid, iid, "in_lucru"), _stock(c, glv),
                                                                  _stock(c, imp)), ("ok_stock_tc_back", 10000, 2000))
        res.check("снова finalizat — снова ждёт (прежнее сторнировано, не задвоено)",
                  (_to(c, pid, iid, "finalizat"), _get(c, f"/api/stock/plan/{iid}")["state"]),
                  ("ok_stock_tc_pending", "pending"))
        _ok(c.post_json(f"/api/stock/plan/{iid}/skip", {}), "ok_stock_tc_skip")
        res.check("«Fără materiale»: позиция не ждёт, склад не тронут",
                  (_get(c, f"/api/stock/plan/{iid}")["state"], _get(c, f"/api/stock/plan-pending?pid={pid}")["rows"],
                   _stock(c, glv)), ("fara", [], 10000))
        _to(c, pid, iid, "in_lucru")
        res.check("Redeschide снимает «Fără materiale»: следующий finalizat снова спрашивает",
                  _to(c, pid, iid, "finalizat"), "ok_stock_tc_pending")
        _ok(c.post_json(f"/api/stock/plan/{iid}/consume", {"lines": [{"item_id": glv, "qty_milli": 2000}]}),
            "ok_stock_tc_consume")
        _ok(c.post_json(f"/api/stock/plan/{iid}/undo", {}), "ok_stock_tc_undo")
        res.check("«Anulează materialele»: склад назад, позиция снова ждёт",
                  (_stock(c, glv), _get(c, f"/api/stock/plan/{iid}")["state"]), (10000, "pending"))
        res.check("нечего отменять — 409", c.post_json(f"/api/stock/plan/{iid}/undo", {}).msg, "stock_no_undo")
        res.check("не finalizat — consume 409 stock_tc_open", (_to(c, pid, iid, "in_lucru"), c.post_json(
            f"/api/stock/plan/{iid}/consume", {"lines": []}).msg), ("", "stock_tc_open"))
        res.check("журнал только дописывался", _sql(s, "SELECT COUNT(*) = MAX(id) FROM stock_moves")[0][0], 1)


def suite_auto(res: Result) -> None:
    """«automat»: списание сразу при finalizat (и из «Consultație»), только обязательное и не архивное;
    «fara»: ничего."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        glv, flu, imp, old = _setup(c)
        res.check("режим — только PERM_SETTINGS-полем tc_mode; чужое слово — stock_bad", (
            (lambda r: (r.msg, _j(r).get("field")))(c.post_json("/api/stock/prefs", {"tc_mode": "x"})),
            c.post_json("/api/stock/prefs", {"tc_mode": "automat"}).msg, _get(c, "/api/stock")["prefs"]["tc_mode"]),
            (("stock_bad", "tc_mode"), "ok_stock_prefs", "automat"))
        pid = new_patient(c, "Ana Automat", "069500200")
        iid = _plan(c, s, pid)
        _to(c, pid, iid, "in_lucru")
        res.check("finalizat — списано сразу, код склада", _to(c, pid, iid, "finalizat"), "ok_stock_tc_auto")
        res.check("списано обязательное, без необязательного и архивного; дорогое — FEFO-лот",
                  sorted(_sql(s, "SELECT item_name, -qty_milli, lot FROM stock_moves WHERE plan_item_id = ? "
                                 "AND kind = 'consum'", iid)),
                  [("Implant TS III", 1000, "SOON"), ("Mănuși nitril M", 2000, "")])
        _to(c, pid, iid, "in_lucru")
        _to(c, pid, iid, "finalizat")
        res.check("Redeschide + finalizat: живой набор один",
                  (_stock(c, glv), _get(c, f"/api/stock/plan/{iid}")["state"]), (8000, "done"))
        res.ok("летопись фиши: материалы позиции", any("Materiale: Igienizare" in t for (t,) in _sql(
            s, "SELECT text FROM activity WHERE patient_id = ? AND kind = 'stock'", pid)), "")
        r = add_appt(c, AT.date().isoformat(), "11:00", "Ana Automat", "069500200")
        if not r.msg.startswith("ok"):
            raise AssertionError(f"визит не записан: {r.status} {r.body[:200]}")
        appt = _sql(s, "SELECT MAX(id) FROM appointments WHERE patient_id = ?", pid)[0][0]
        visit_item = _plan(c, s, pid)
        r = c.post_json(f"/api/visits/{appt}", {"acuze": "control", "done": [visit_item]})
        res.check("«Consultație» с галочкой позиции — тот же крючок", (r.msg, _sql(
            s, "SELECT COUNT(*), MAX(appointment_id) FROM stock_moves WHERE plan_item_id = ? AND kind = 'consum'",
            visit_item)), ("ok_stock_tc_auto", [(2, appt)]))
        _ok(c.post_json("/api/stock/prefs", {"tc_mode": "fara"}), "ok_stock_prefs")
        other = _plan(c, s, pid)
        _to(c, pid, other, "in_lucru")
        res.check("«fara»: finalizat ничего не пишет и не ждёт",
                  (_to(c, pid, other, "finalizat"), _get(c, f"/api/stock/plan-pending?pid={pid}")["rows"],
                   _sql(s, "SELECT COUNT(*) FROM stock_moves WHERE plan_item_id = ?", other)[0][0]), ("", [], 0))


def suite_report(res: Result) -> None:
    """Расход по врачу / услуге / пациенту / материалу: только consum, отменённое не в счёт,
    суммы — директору."""
    with Clock(AT), Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        for body in ({"uid": "d3", "name": "Dr. Activ Trei", "role": "medic", "doctor_id": "d3", "pin": "2222"},
                     {"uid": "ana", "name": "Ana Rusu", "role": "receptie", "pin": "4444"}):
            boss.post_json("/api/settings/users", body)
        ana, med = Client(s.url), Client(s.url)
        ana.post("/admin/login", password="4444", next="/admin")
        med.post("/admin/login", password="2222", next="/admin")
        glv, flu, imp, old = _setup(boss)
        pid = new_patient(boss, "Report Pacient", "069500300")
        iid = _plan(boss, s, pid)
        _to(boss, pid, iid, "in_lucru")
        _to(boss, pid, iid, "finalizat")
        res.check("врач закрывает позицию у кресла: видит предложение и подтверждает",
                  (_get(med, f"/api/stock/plan/{iid}")["state"], med.post_json(f"/api/stock/plan/{iid}/consume", {
                      "lines": [{"item_id": imp, "qty_milli": 1000, "lot": "SOON"}]}).msg),
                  ("pending", "ok_stock_tc_consume"))
        res.check("цены в предложении — только директору",
                  ("cost_bani" in _get(med, f"/api/stock/plan/{iid}")["lines"][2],
                   _get(boss, f"/api/stock/plan/{iid}")["lines"][2]["cost_bani"]), (False, 800000))
        res.check("врачу техкарты и отчёт закрыты, регистратуре — режим", (
            med.get("/api/stock/tehcard").status, med.get("/api/stock/report").status,
            ana.post_json("/api/stock/prefs", {"tc_mode": "automat"}).status), (403, 403, 403))
        m = _ok(boss.post_json("/api/stock/out", {"item_id": glv, "qty_milli": 1000, "reason": "pacient",
                                                  "pid": pid}), "ok_stock_out")
        _ok(boss.post_json(f"/api/stock/move/{m['id']}/undo", {}), "ok_stock_undo")
        boss.post_json("/api/stock/out", {"item_id": glv, "qty_milli": 3000, "reason": "defect"})
        rep = _get(boss, "/api/stock/report?by=doctor")
        res.check("по врачу: снимок имени, сумма по средней; отменённое и casare не в счёт",
                  [(r["label"], r["qty_rows"], r["cost_bani"]) for r in rep["rows"]], [("Dr. Activ Doi", 1, 800000)])
        res.check("по услуге и материалу", (
            [(r["label"], r["qty_rows"]) for r in _get(boss, "/api/stock/report?by=service")["rows"]],
            [(r["label"], r["items"][0]["qty_milli"]) for r in _get(boss, "/api/stock/report?by=item")["rows"]]),
            ([("Igienizare", 1)], [("Implant TS III", 1000)]))
        res.check("по пациенту — имя на сейчас", [r["label"] for r in _get(boss, "/api/stock/report?by=patient")["rows"]],
                  ["Report Pacient"])
        rr = _get(ana, "/api/stock/report?by=doctor")
        res.check("регистратура: отчёт без сумм", ("cost_bani" in rr["rows"][0], "total_bani" in rr), (False, False))
        res.check("период вне — пусто", _get(boss, "/api/stock/report?by=doctor&from=2026-10-01&to=2026-10-31")["rows"],
                  [])
        res.check("материал позиции держит фишу — обезличивание",
                  boss.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"}).msg, "ok_anon")
        res.check("плашка главной жива", panel_live(boss)["stock"] is None or "low" in panel_live(boss)["stock"], True)
