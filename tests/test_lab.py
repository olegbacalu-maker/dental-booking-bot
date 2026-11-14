"""Заказы в зуботехническую лабораторию — сервер (шаг схемы 13, `/api/lab/*`,
лист наряда, права, закон 195).

Правила продукта: статусы trimis › gata › primit › probă
› finalizat (+ anulat); после примерки — «etapa» (новый этап) и «refacere»
(брак: причина, кто платит); отмена шага — событие; заказ не удаляется, номер
сквозной. Цена лаборатории — только с правом на деньги. Каталог — директор и
регистратура (`PERM_LABS`). Засев — путём клиники: фиша и план через API фиши,
визит — окном записи; часы — подменные (`harness.Clock`).
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

from harness import (BOT, Client, Clock, Result, Server, TZ, _rmtree_settled, add_appt, new_patient,
                     panel_live)
from test_api import NO_KEY

sys.path.insert(0, str(BOT))
from app import db as appdb  # noqa: E402
from app.core import lab as clab  # noqa: E402

# пятница 13.11.2026, 09:00 — рабочий день; сроки считаются в рабочих днях
AT = datetime(2026, 11, 13, 9, 0, tzinfo=TZ)
# четверг: «завтра» — рабочая пятница, визит на завтра записывается
THU = datetime(2026, 11, 12, 9, 0, tzinfo=TZ)


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


def _plan(c: Client, s: Server, pid: int, procedure: str, tooth: str = "") -> int:
    r = c.post_json(f"/api/patients/{pid}/plan", {"tooth": tooth, "procedure": procedure,
                                                  "doctor": "Dr. Activ Doi", "price": "", "due_date": ""})
    if r.msg != "ok_card":
        raise AssertionError(f"позиция плана не заведена: {r.status} {r.body[:200]}")
    return _sql(s, "SELECT MAX(id) FROM plan_items WHERE patient_id = ?", pid)[0][0]


def _lab(c: Client, name: str, **kw) -> int:
    r = c.post_json("/api/settings/lab/item", {"name": name, **kw})
    if r.msg != "ok_lab_item":
        raise AssertionError(f"лаборатория не заведена: {r.status} {r.body[:200]}")
    return _j(r)["data"]["id"]


def _order(c: Client, pid: int, lab_id: int | None = None, **kw) -> tuple[int, int]:
    body = {"pid": pid, "lab_id": lab_id, "doctor_id": "d2",
            "items": [{"work": "Coroană", "material": "Zirconiu", "shade": "A2", "teeth": [26]}], **kw}
    r = c.post_json("/api/lab/order", body)
    if r.msg != "ok_lab_new":
        raise AssertionError(f"заказ не заведён: {r.status} {r.body[:300]}")
    d = _j(r)["data"]
    return d["id"], d["nr"]


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


# ---------- правила чистыми функциями ----------

def suite_rules(res: Result) -> None:
    """Срок в рабочих днях и шапка из истории — без сервера."""
    fri = AT.date()
    res.check("7 рабочих дней пн–пт от пятницы", clab.add_workdays(fri, 7, "12345").isoformat(), "2026-11-24")
    res.check("3 рабочих дня с субботой", clab.add_workdays(fri, 3, "123456").isoformat(), "2026-11-17")
    res.check("0 дней — в день отправки", clab.add_workdays(fri, 0, "12345"), fri)

    def ev(i, kind, **kw):
        return {"id": i, "kind": kind, "data": kw.pop("data", {}), **kw}
    evs = [ev(1, "trimis", on_date="2026-11-01", due_on="2026-11-10"),
           ev(2, "gata", on_date="2026-11-08"), ev(3, "primit", on_date="2026-11-09"),
           ev(4, "proba", on_date="2026-11-10"), ev(5, "etapa", on_date="2026-11-11", due_on="2026-11-18")]
    head, undone, target = clab.replay(evs)
    res.check("etapa: статус trimis, этап 2, новый срок, приёмка сброшена",
              (head["status"], head["stage"], head["sent_on"], head["due_on"], head["received_on"], target),
              ("trimis", 2, "2026-11-11", "2026-11-18", None, 5))
    head, undone, target = clab.replay(evs + [ev(6, "anulare_pas", data={"undoes": 5})])
    res.check("отмена etapa: снова «La probă», этап 1, прежний срок, следующая отмена — шаг probă",
              (head["status"], head["stage"], head["due_on"], head["received_on"], undone, target),
              ("proba", 1, "2026-11-10", "2026-11-09", {5}, 4))
    head, _, _ = clab.replay(evs[:4] + [ev(6, "refacere", on_date="2026-11-11", due_on="2026-11-20", cause="culoare")])
    res.check("refacere: trimis, этап НЕ растёт", (head["status"], head["stage"], head["due_on"]),
              ("trimis", 1, "2026-11-20"))
    head, _, target = clab.replay(evs[:1] + [ev(2, "termen", due_on="2026-11-12")])
    res.check("termen меняет срок; первый trimis не отменяется", (head["due_on"], target), ("2026-11-12", None))
    res.check("шаги из «trimis» без отмены: gata главная, primit, cancel",
              [(x["act"], x["main"]) for x in clab.steps("trimis", False)],
              [("gata", True), ("primit", False), ("cancel", False)])
    res.check("сводка: одинаковые работы — числом, мост — одним изделием",
              clab.work_summary([{"work": "Fațetă", "qty": 1, "grp": None}, {"work": "fațetă", "qty": 1, "grp": None},
                                 {"work": "Punte", "qty": 1, "grp": 1}, {"work": "Punte", "qty": 1, "grp": 1},
                                 {"work": "Coroană", "qty": 3, "grp": None}]),
              "Fațetă ×2 · Punte · Coroană ×3")
    res.check("шаги из «finalizat»: только отмена шага", [x["act"] for x in clab.steps("finalizat", True)], ["undo"])
    res.check("открытые и закрытые статусы — перечислением, без пересечения и без пропуска",
              (set(appdb.LAB_OPEN) & set(appdb.LAB_CLOSED), set(appdb.LAB_STATUSES)),
              (set(), {"trimis", "gata", "primit", "proba", "finalizat", "anulat"}))


def suite_schema(res: Result) -> None:
    """Шаг 13: четыре таблицы и индексы, каждый оператор IF NOT EXISTS; имени
    пациента в заказе нет."""
    step = next((k for k, v in appdb.MIGRATIONS.items() if v is appdb.LAB_DDL), None)
    res.ok("LAB_DDL — шаг миграции, и он последний", step == appdb.SCHEMA_VERSION, f"шаг {step}")
    res.ok("каждый оператор — IF NOT EXISTS (шаг переживает повтор)",
           all(" IF NOT EXISTS " in x for x in appdb.LAB_DDL), "")
    res.ok("уникальный индекс номера назван ix_, не uq_ (uq_ — слотовые)",
           not any(" uq_" in x for x in appdb.LAB_DDL) and any("UNIQUE INDEX IF NOT EXISTS ix_lab_nr" in x
                                                               for x in appdb.LAB_DDL), "")
    orders = next(x for x in appdb.LAB_DDL if "TABLE IF NOT EXISTS lab_orders(" in x)
    res.ok("в шапке заказа нет имени пациента (только patient_id)",
           "patient_id" in orders and "\n  patient " not in orders and "patient_name" not in orders, orders[:200])
    with Server() as s:
        names = {r[0] for r in _sql(s, "SELECT name FROM sqlite_master WHERE name LIKE 'lab%' OR name LIKE 'ix_lab%'")}
        res.check("свежая база получила таблицы и индексы", names,
                  {"labs", "lab_orders", "lab_order_items", "lab_events", "ix_lab_nr", "ix_lab_patient",
                   "ix_lab_status", "ix_lab_items_order", "ix_lab_items_plan", "ix_lab_events_order"})
        res.check("версия схемы", _sql(s, "SELECT value FROM schema_meta WHERE key='version'")[0][0],
                  str(appdb.SCHEMA_VERSION))


def suite_retry(res: Result) -> None:
    """Шаг 13 приходит повторно: всё уже есть, оборвался посередине, обычное
    обновление с 12 — старт проходит, таблицы на месте, раздел отвечает."""
    step = next(k for k, v in appdb.MIGRATIONS.items() if v is appdb.LAB_DDL)
    drops = {"всё уже есть": (),
             "оборвался после шапки": ("DROP TABLE lab_events", "DROP INDEX ix_lab_items_plan"),
             "обычное обновление": ("DROP TABLE lab_events", "DROP TABLE lab_order_items",
                                    "DROP TABLE lab_orders", "DROP TABLE labs")}
    for tag, todo in drops.items():
        work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_lab_"))
        try:
            dbfile = work / "dental.db"
            with Server(dir_=work):
                pass
            con = sqlite3.connect(str(dbfile))
            try:
                for sql in todo:
                    con.execute(sql)
                con.execute("UPDATE schema_meta SET value = ? WHERE key = 'version'", (str(step - 1),))
                con.commit()
            finally:
                con.close()
            with Server(dir_=work) as s:
                c = Client(s.url).login()
                res.check(f"{tag}: версия доведена", _sql(s, "SELECT value FROM schema_meta WHERE key='version'")[0][0],
                          str(appdb.SCHEMA_VERSION))
                res.check(f"{tag}: список отвечает", c.get("/api/lab").status, 200)
                pid = new_patient(c, "Retry Lab", "069111222")
                lid = _lab(c, "Lab Retry")
                res.check(f"{tag}: заказ пишется", _order(c, pid, lid)[1], 1)
        finally:
            _rmtree_settled(work)


# ---------- поток заказа ----------

def suite_flow(res: Result) -> None:
    """Заказ от отправки до конца: номер, срок, шаги, этап, переделка, отмена шага,
    отмена заказа, правка с событиями, летопись фиши."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Ion Popescu", "069100200")
        lid = _lab(c, "Dental Lab Prim", phone="022 123 456", days=7)
        crown = _plan(c, s, pid, "Coroană zirconiu 26", "26")
        bridge = _plan(c, s, pid, "Punte 44-46")
        res.check("заказ без пациента — lab_bad/pid", _field(c.post_json("/api/lab/order", {"items": [{"work": "X"}]})),
                  ("lab_bad", "pid"))
        res.check("без лаборатории — lab_need_lab", _field(c.post_json("/api/lab/order", {"pid": pid, "items": [{"work": "X"}]})),
                  ("lab_need_lab", "lab"))
        res.check("без работ — lab_bad/items",
                  _field(c.post_json("/api/lab/order", {"pid": pid, "lab_id": lid, "items": []})), ("lab_bad", "items"))
        res.check("зуб не FDI — поле строки",
                  _field(c.post_json("/api/lab/order", {"pid": pid, "lab_id": lid, "items": [{"work": "X", "teeth": [19]}]})),
                  ("lab_bad", "items.0.teeth"))
        res.check("чужая позиция плана — поле строки",
                  _field(c.post_json("/api/lab/order", {"pid": pid, "lab_id": lid,
                                                        "items": [{"work": "X", "plan_item_id": 999999}]})),
                  ("lab_bad", "items.0.plan"))
        res.check("отправка в будущем — lab_bad/sent_on",
                  _field(c.post_json("/api/lab/order", {"pid": pid, "lab_id": lid, "sent_on": "2026-11-20",
                                                        "items": [{"work": "X"}]})), ("lab_bad", "sent_on"))
        res.check("ни одной неудачи в базе", _sql(s, "SELECT COUNT(*) FROM lab_orders")[0][0], 0)
        due = _get(c, f"/api/lab/due?lab={lid}&sent=2026-11-13")
        res.check("срок по лаборатории: 7 рабочих дней от пятницы", due["due_on"], "2026-11-24")

        oid, nr = _order(c, pid, lid, urgent=True, impression="scanare", note="Umăr ceramic.",
                         items=[{"plan_item_id": crown, "work": "Coroană", "material": "Zirconiu", "shade": "A2 la colet",
                                 "teeth": [26], "price_bani": 180000},
                                {"work": "Punte", "material": "Zirconiu", "teeth": [44, 45, 46], "grp": 1,
                                 "plan_item_id": bridge, "price_bani": 420000}])
        oid2, nr2 = _order(c, pid, lid, sent_on="2026-11-10")
        res.check("номер сквозной: 1, затем 2", (nr, nr2), (1, 2))
        o = _get(c, f"/api/lab/order/{oid}")["order"]
        res.check("шапка: trimis, срок по лаборатории, срочно, оттиск",
                  (o["status"], o["status_label"], o["stage"], o["sent_on"], o["due_on"], o["urgent"], o["impression"]),
                  ("trimis", "Trimis la laborator", 1, "2026-11-13", "2026-11-24", True, "scanare"))
        res.check("строки: позиция плана, зубы, цвет свободным текстом, цена у директора",
                  [(i["plan_item_id"], i["teeth"], i["shade"], i["price_bani"], i["grp"]) for i in o["items"]],
                  [(crown, [26], "A2 la colet", 180000, None), (bridge, [44, 45, 46], None or "", 420000, 1)])
        res.check("сводка и сумма", (o["work"], o["total_bani"], o["teeth"]), ("Coroană · Punte", 600000, [26, 44, 45, 46]))
        res.check("история — одно событие trimis со сроком",
                  [(e["kind"], e["due_on"], e["actor"] != "") for e in o["events"]], [("trimis", "2026-11-24", True)])
        res.check("имени пациента в таблицах заказа нет",
                  _sql(s, "SELECT COUNT(*) FROM lab_orders WHERE note LIKE '%Popescu%' OR lab LIKE '%Popescu%'")[0][0], 0)
        res.check("врач — снимок имени", (o["doctor_id"], o["doctor"]), ("d2", "Dr. Activ Doi"))

        pm = _get(c, f"/api/lab/patient/{pid}")
        res.check("значки плана: обе позиции знают заказ nr 1",
                  {k: (v["nr"], v["status"]) for k, v in pm["plan"].items()},
                  {str(crown): (1, "trimis"), str(bridge): (1, "trimis")})
        res.check("заказы пациента — новые сверху", [x["nr"] for x in pm["orders"]], [2, 1])

        base = f"/api/lab/order/{oid}"
        res.check("проба из trimis — lab_step 409", (lambda r: (r.status, r.msg))(c.post_json(base + "/step", {"to": "proba"})),
                  (409, "lab_step"))
        res.check("переделка из trimis — lab_step", c.post_json(base + "/refacere", {"cause": "culoare", "payer": "clinica"}).msg,
                  "lab_step")
        res.check("отменять нечего — lab_no_undo", c.post_json(base + "/undo", {}).msg, "lab_no_undo")
        res.check("gata — ok", c.post_json(base + "/step", {"to": "gata"}).msg, "ok_lab_step")
        res.check("primit — ok", c.post_json(base + "/step", {"to": "primit"}).msg, "ok_lab_step")
        res.check("gata «вчера» у заказа, отправленного раньше, — ok",
                  c.post_json(f"/api/lab/order/{oid2}/step", {"to": "gata", "on_date": "2026-11-12"}).msg, "ok_lab_step")
        res.check("primit раньше отправки — lab_bad/on_date",
                  _field(c.post_json(f"/api/lab/order/{oid2}/step", {"to": "primit", "on_date": "2026-11-01"})),
                  ("lab_bad", "on_date"))
        res.check("proba — ok", c.post_json(base + "/step", {"to": "proba"}).msg, "ok_lab_step")
        res.check("etapa — ok", c.post_json(base + "/etapa", {"note": "Ajustare ocluzie 46"}).msg, "ok_lab_etapa")
        o = _get(c, base)["order"]
        res.check("после etapa: trimis, этап 2, новый срок от сегодня, приёмка сброшена",
                  (o["status"], o["stage"], o["sent_on"], o["due_on"], o["received_on"]),
                  ("trimis", 2, "2026-11-13", "2026-11-24", None))
        for to in ("gata", "primit"):
            c.post_json(base + "/step", {"to": to})
        res.check("переделка без причины — поле cause", _field(c.post_json(base + "/refacere", {"payer": "laborator"})),
                  ("lab_bad", "cause"))
        res.check("переделка без «кто платит» — поле payer", _field(c.post_json(base + "/refacere", {"cause": "culoare"})),
                  ("lab_bad", "payer"))
        res.check("«altă cauză» без текста — поле note",
                  _field(c.post_json(base + "/refacere", {"cause": "alta", "payer": "laborator"})), ("lab_bad", "note"))
        res.check("переделка — ok", c.post_json(base + "/refacere", {"cause": "culoare", "payer": "laborator",
                                                                       "due_on": "2026-11-18"}).msg, "ok_lab_refacere")
        o = _get(c, base)["order"]
        res.check("после переделки: trimis, этап тот же, свой срок", (o["status"], o["stage"], o["due_on"]),
                  ("trimis", 2, "2026-11-18"))
        rf = [e for e in o["events"] if e["kind"] == "refacere"][0]
        res.check("событие переделки словами", (rf["cause_label"], rf["payer_label"]),
                  ("Culoare", "Laboratorul (garanție)"))
        res.check("отмена шага — ok", c.post_json(base + "/undo", {}).msg, "ok_lab_undo")
        o = _get(c, base)["order"]
        res.check("после отмены: снова primit, прежний срок, переделка в истории помечена",
                  (o["status"], o["due_on"], [e["undone"] for e in o["events"] if e["kind"] == "refacere"],
                   o["events"][-1]["kind"]),
                  ("primit", "2026-11-24", [True], "anulare_pas"))
        n_ev = len(o["events"])
        res.check("главная кнопка из primit — Probă", [(x["act"], x["label"]) for x in _get(c, base)["steps"] if x["main"]],
                  [("proba", "Probă")])

        # правка: срок — событие termen; пересохранение без правки — ничего
        res.check("правка срока раньше отправки — lab_bad/due_on", _field(c.post_json(base, {"due_on": "2026-11-01"})),
                  ("lab_bad", "due_on"))
        res.check("правка срока — ok", c.post_json(base, {"due_on": "2026-11-27"}).msg, "ok_lab_save")
        o = _get(c, base)["order"]
        res.check("termen в истории и в шапке", (o["due_on"], o["events"][-1]["kind"], o["events"][-1]["note"]),
                  ("2026-11-27", "termen", "24.11.2026 › 27.11.2026"))
        same = {"due_on": o["due_on"], "note": o["note"], "urgent": o["urgent"], "doctor_id": o["doctor_id"],
                "items": [{k: i[k] for k in ("id", "plan_item_id", "work", "material", "shade", "teeth", "qty", "grp",
                                             "price_bani")} for i in o["items"]]}
        res.check("пересохранение без правки — ok", c.post_json(base, same).msg, "ok_lab_save")
        res.check("…и ни одного нового события", len(_get(c, base)["order"]["events"]), n_ev + 1)
        two = dict(same, items=same["items"][:1] + [dict(same["items"][1], price_bani=400000)])
        c.post_json(base, two)
        o = _get(c, base)["order"]
        res.check("смена цены — событие pret с суммами", (o["events"][-1]["kind"], o["events"][-1]["note"], o["total_bani"]),
                  ("pret", "6000 lei › 5800 lei", 580000))
        lab2 = _lab(c, "ArtDent Laborator", days=5)
        c.post_json(base, {"lab_id": lab2})
        o = _get(c, base)["order"]
        res.check("смена лаборатории — снимок и событие", (o["lab"], o["events"][-1]["kind"]), ("ArtDent Laborator", "laborator"))

        # конец и отмена
        c.post_json(base + "/step", {"to": "finalizat"})
        res.check("finalizat из primit (без примерки)", _get(c, base)["order"]["status"], "finalizat")
        res.check("правка закрытого — lab_closed 409", (lambda r: (r.status, r.msg))(c.post_json(base, {"note": "x"})),
                  (409, "lab_closed"))
        base2 = f"/api/lab/order/{oid2}"
        res.check("отмена без причины — поле why", _field(c.post_json(base2 + "/cancel", {"why": " "})), ("lab_bad", "why"))
        res.check("отмена — ok", c.post_json(base2 + "/cancel", {"why": "Pacientul a amânat"}).msg, "ok_lab_cancel")
        res.check("отменённый заказ остался в базе с номером",
                  _sql(s, "SELECT nr, status FROM lab_orders WHERE id = ?", oid2), [(2, "anulat")])
        res.check("отмену можно отменить (ошибочный щелчок)", c.post_json(base2 + "/undo", {}).msg, "ok_lab_undo")
        res.check("…и заказ снова там, где был", _get(c, base2)["order"]["status"], "gata")
        res.check("третий заказ — номер 3", _order(c, pid, lid)[1], 3)
        texts = [r[0] for r in _sql(s, "SELECT text FROM activity WHERE patient_id = ? AND kind = 'lab' ORDER BY id", pid)]
        res.ok("летопись фиши: отправка и шаги словами",
               texts and texts[0].startswith("Laborator: comanda nr 1 — Coroană · Punte — trimisă la Dental Lab Prim")
               and any("› Primit în clinică" in t for t in texts) and any("anulată" in t for t in texts), repr(texts[:4]))
        res.check("неизвестный заказ — 404 lab_gone", (lambda r: (r.status, r.msg))(c.get("/api/lab/order/99999")),
                  (404, "lab_gone"))


def suite_lists(res: Result) -> None:
    """Список, опоздание, «gata de ridicat», визит без работы, плашка главной."""
    with Clock(THU) as clock, Server() as s:
        c = Client(s.url).login()
        lid = _lab(c, "Dental Lab Prim", days=3)
        late_p = new_patient(c, "Ana Balan", "069100301")
        ready_p = new_patient(c, "Elena Cara", "069100302")
        visit_p = new_patient(c, "Mihai Donos", "069100303")
        o_late, _ = _order(c, late_p, lid, sent_on="2026-11-02", due_on="2026-11-10")
        o_ready, _ = _order(c, ready_p, lid, sent_on="2026-11-05")
        c.post_json(f"/api/lab/order/{o_ready}/step", {"to": "gata"})
        o_visit, _ = _order(c, visit_p, lid)
        tomorrow = (THU + timedelta(days=1)).date()
        r = add_appt(c, tomorrow.isoformat(), "10:00", "Mihai Donos", "069100303")
        res.ok("визит записан", r.msg.startswith("ok"), r.body[:200])
        m = _get(c, "/api/lab")
        rows = {x["id"]: x for x in m["orders"]}
        res.check("опоздание: trimis после срока, на сколько дней",
                  (rows[o_late]["late"], rows[o_late]["days_late"], rows[o_late]["due_in"]), (True, 2, -2))
        res.check("готовая — не опоздание, а «gata de ridicat»", (rows[o_ready]["late"], rows[o_ready]["ready"]),
                  (False, True))
        nxt = rows[o_visit]["next_appt"]
        res.check("ближайший визит пациента — завтра", (nxt["date"], nxt["time"], nxt["day"], rows[o_visit]["visit_wait"]),
                  (tomorrow.isoformat(), "10:00", "maine", True))
        res.check("просроченные сверху", m["orders"][0]["id"], o_late)
        res.check("счётчики фильтров",
                  {k: m["counts"][k] for k in ("lucru", "intarziate", "ridicat", "toate")},
                  {"lucru": 3, "intarziate": 1, "ridicat": 1, "toate": 3})
        res.check("фильтр «De ridicat»", [x["id"] for x in _get(c, "/api/lab?f=ridicat")["orders"]], [o_ready])
        res.check("поиск без диакритики и регистра", [x["id"] for x in _get(c, "/api/lab?f=toate&q=elena%20cara")["orders"]],
                  [o_ready])
        res.check("поиск по № заказа", len(_get(c, f"/api/lab?f=toate&q={rows[o_late]['nr']}")["orders"]) >= 1, True)
        res.check("отдельной двери плашки нет — она в конверте панели", c.get("/api/lab/dash").status, 404)
        d = panel_live(c)["lab"]
        res.check("плашка в конверте: опоздание и готовая",
                  ([x["id"] for x in d["late"]], [x["id"] for x in d["ready"]], d["counts"]["late"], d["counts"]["ready"]),
                  ([o_late], [o_ready], 1, 1))
        res.check("плашка: визит завтра, работа не пришла", [x["id"] for x in d["visit"]], [o_visit])
        res.ok("в плашке нет цен", "bani" not in json.dumps(d), "")
        r1 = c.get("/api/schedule/live?screen=panel")
        r2 = c.get("/api/schedule/live?screen=panel", headers={"X-DP-Hash": r1.header("X-DP-Hash")})
        res.check("два опроса при неизменных заказах — тот же отпечаток (204)", r2.status, 204)
        clock.set(THU + timedelta(minutes=40))
        res.check("…и через 40 минут того же дня плашка та же", panel_live(c)["lab"], d)
        c.post_json(f"/api/lab/order/{o_visit}/step", {"to": "primit"})
        r3 = c.get("/api/schedule/live?screen=panel", headers={"X-DP-Hash": r1.header("X-DP-Hash")})
        res.check("работа пришла — отпечаток сдвинулся, строка визита ушла",
                  (r3.status, [x["id"] for x in _j(r3)["data"]["lab"]["visit"]]), (200, []))
        res.check("кнопки шагов — в строке списка",
                  [(x["act"], x["main"]) for x in rows[o_ready]["steps"]],
                  [("primit", True), ("undo", False), ("cancel", False)])
        res.check("настройка «готовая незабранная = опоздание» — ok",
                  c.post_json("/api/settings/lab/prefs", {"late_gata": True}).msg, "ok_lab_prefs")
        clock.set(THU + timedelta(days=3))
        rows = {x["id"]: x for x in _get(c, "/api/lab?f=toate")["orders"]}
        res.check("с настройкой готовая после срока — опоздание", rows[o_ready]["late"], True)
        res.check("prefs: неизвестное «кто в наряде» — поле who",
                  _field(c.post_json("/api/settings/lab/prefs", {"who": "idnp"})), ("lab_bad", "who"))


def suite_rights(res: Result) -> None:
    """Каталог — директор и регистратура; врач видит все заказы и создаёт их, но
    не заводит лабораторию; цена — только с правом на деньги."""
    with Clock(AT), Server(env=NO_KEY) as s:
        boss, ana, med = _team(s)
        res.check("врачу каталог закрыт — 403 no_access", (lambda r: (r.status, r.msg))(med.get("/api/settings/lab")),
                  (403, "no_access"))
        res.check("регистратуре каталог открыт", ana.get("/api/settings/lab").status, 200)
        res.check("врач не пишет каталог", med.post_json("/api/settings/lab/item", {"name": "X"}).status, 403)
        pid = new_patient(ana, "Vasile Rotaru", "069100400")
        res.check("врач не заводит лабораторию из окна заказа — 403 no_access",
                  (lambda r: (r.status, r.msg))(med.post_json("/api/lab/order", {
                      "pid": pid, "lab_name": "Lab Nou", "items": [{"work": "Coroană"}]})), (403, "no_access"))
        res.check("…и каталог остался пуст", _sql(s, "SELECT COUNT(*) FROM labs")[0][0], 0)
        r = ana.post_json("/api/lab/order", {"pid": pid, "lab_name": "Lab Nou", "doctor_id": "d2",
                                             "items": [{"work": "Coroană", "price_bani": 99900}]})
        res.check("регистратура пишет имя — заказ и новая лаборатория", r.msg, "ok_lab_new")
        res.check("лаборатория в каталоге, цена без права не записана",
                  (_sql(s, "SELECT name FROM labs"), _sql(s, "SELECT price_bani FROM lab_order_items")),
                  ([("Lab Nou",)], [(None,)]))
        oid = _j(r)["data"]["id"]
        lid = _sql(s, "SELECT id FROM labs")[0][0]
        res.check("врач пишет заказ к ЧУЖОМУ врачу из каталога — ok (картотека вся)",
                  med.post_json("/api/lab/order", {"pid": pid, "lab_name": "lab nou", "doctor_id": "d2",
                                                   "items": [{"work": "Gutieră"}]}).msg, "ok_lab_new")
        res.check("имя той же лаборатории другим регистром — та же, двойника нет",
                  _sql(s, "SELECT COUNT(*) FROM labs")[0][0], 1)
        res.check("врач видит все заказы", len(_get(med, "/api/lab")["orders"]), 2)
        res.check("директор ставит цену", boss.post_json(f"/api/lab/order/{oid}", {"items": [
            {"id": _get(boss, f"/api/lab/order/{oid}")["order"]["items"][0]["id"], "work": "Coroană",
             "price_bani": 150000}]}).msg, "ok_lab_save")
        o_boss = _get(boss, f"/api/lab/order/{oid}")["order"]
        o_ana = _get(ana, f"/api/lab/order/{oid}")["order"]
        res.check("директор видит цену и сумму", (o_boss["items"][0]["price_bani"], o_boss["total_bani"]), (150000, 150000))
        res.check("регистратура цены не видит", ("price_bani" in o_ana["items"][0], "total_bani" in o_ana), (False, False))
        res.check("подсказка прошлой цены — только директору",
                  ([(x["lab_id"], x["work"], x["price_bani"]) for x in _get(boss, f"/api/lab/form?pid={pid}")["last_prices"]],
                   "last_prices" in _get(ana, f"/api/lab/form?pid={pid}")),
                  ([(lid, "Coroană", 150000)], False))
        item = o_ana["items"][0]
        res.check("регистратура правит строку без цены",
                  ana.post_json(f"/api/lab/order/{oid}", {"items": [{"id": item["id"], "work": "Coroană", "shade": "A3",
                                                                    "price_bani": 1}]}).msg, "ok_lab_save")
        res.check("…цена директора не стёрта и не подменена",
                  _sql(s, "SELECT shade, price_bani FROM lab_order_items WHERE order_id = ?", oid), [("A3", 150000)])
        res.check("врач меняет «что в наряде» — 403", med.post_json("/api/settings/lab/prefs", {"who": "fisa"}).status, 403)
        res.check("регистратура тоже нет (решает директор)", ana.post_json("/api/settings/lab/prefs", {"who": "fisa"}).status, 403)
        res.check("can в модели врача", _get(med, "/api/lab")["can"], {"money": False, "labs": False, "settings": False})
        res.check("can в модели регистратуры", _get(ana, "/api/lab")["can"], {"money": False, "labs": True, "settings": False})
        res.check("без входа — 401", Client(s.url).get("/api/lab").status, 401)
        res.check("чужой Origin на команду — 403",
                  ana.post_json(f"/api/lab/order/{oid}/step", {"to": "gata"}, headers={"Origin": "http://evil.example"}).status,
                  403)
        res.check("форма врача предлагает его самого", _get(med, f"/api/lab/form?pid={pid}")["doctor_id"], "d3")
        late = {"pid": pid, "lab_id": lid, "sent_on": "2026-11-02", "due_on": "2026-11-05", "items": [{"work": "Punte"}]}
        own = _j(boss.post_json("/api/lab/order", dict(late, doctor_id="d3")))["data"]["id"]
        other = _j(boss.post_json("/api/lab/order", dict(late, doctor_id="d2")))["data"]["id"]
        res.check("плашка панели врача — только заказы его врача (журнал по праву)",
                  [x["id"] for x in panel_live(med)["lab"]["late"]], [own])
        res.check("плашка стойки — все", sorted(x["id"] for x in panel_live(ana)["lab"]["late"]), sorted([own, other]))


def suite_catalog(res: Result) -> None:
    """Каталог: двойник, рабочие дни, IDNO, удаление только без заказов, выключенная
    лаборатория в окне не предлагается."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        lid = _lab(c, "Dental Lab Prim", workdays="123456", days=3, data={"idno": "1003600 012345", "own": True})
        res.check("двойник по имени — lab_dup 422 с полем (экран подсвечивает поле)", (lambda r: (r.status, *_field(r)))(
            c.post_json("/api/settings/lab/item", {"name": " dental lab prim "})), (422, "lab_dup", "name"))
        res.check("рабочие дни с повтором — поле workdays",
                  _field(c.post_json("/api/settings/lab/item", {"name": "B", "workdays": "115"})), ("lab_bad", "workdays"))
        res.check("IDNO не 13 цифр — поле idno",
                  _field(c.post_json("/api/settings/lab/item", {"name": "B", "data": {"idno": "123"}})), ("lab_bad", "idno"))
        res.check("e-mail без @ — поле email",
                  _field(c.post_json("/api/settings/lab/item", {"name": "B", "email": "lab.md"})), ("lab_bad", "email"))
        m = _get(c, "/api/settings/lab")
        lab = m["labs"][0]
        res.check("каталог: дни, IDNO без пробелов, своя лаборатория, счётчики",
                  (lab["workdays"], lab["days"], lab["data"]["idno"], lab["data"]["own"], lab["orders"], lab["open"]),
                  ("123456", 3, "1003600012345", True, 0, 0))
        res.check("срок с субботой", _get(c, f"/api/lab/due?lab={lid}&sent=2026-11-13")["due_on"], "2026-11-17")
        pid = new_patient(c, "Ion Lab", "069100500")
        _order(c, pid, lid)
        res.check("лабораторию с заказом не удалить — 409 lab_has_orders",
                  (lambda r: (r.status, r.msg))(c.post_json(f"/api/settings/lab/item/{lid}/delete", {})), (409, "lab_has_orders"))
        res.check("переименование: старый заказ держит прежнее имя снимком",
                  (c.post_json("/api/settings/lab/item", {"id": lid, "name": "Prim Dental", "active": False}).msg,
                   _get(c, "/api/lab")["orders"][0]["lab"]), ("ok_lab_item", "Dental Lab Prim"))
        res.check("выключенная — не в окне заказа, но в фильтре списка",
                  (_get(c, f"/api/lab/form?pid={pid}")["labs"], [x["active"] for x in _get(c, "/api/lab")["labs"]]),
                  ([], [False]))
        res.check("правка каталога не стёрла IDNO (нет поля — не сообщали)",
                  _get(c, "/api/settings/lab")["labs"][0]["data"]["idno"], "1003600012345")
        empty = _lab(c, "Fără comenzi")
        res.check("без заказов — удаляется", c.post_json(f"/api/settings/lab/item/{empty}/delete", {}).msg, "ok_lab_del")
        res.check("нет такой — 404", c.post_json(f"/api/settings/lab/item/{empty}/delete", {}).status, 404)


def suite_print(res: Result) -> None:
    """Лист наряда: что о пациенте (имя / № фиши), чего на нём нет, событие печати."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Maria Exemplu", "069100600", birth_date="1980-05-06")
        r = c.post_json(f"/api/patients/{pid}/profile", {"name": "Maria Exemplu", "phone": "069100600",
                                                         "birth_date": "1980-05-06", "idnp": "2001234567890",
                                                         "file_no": "F-77"})
        res.check("профиль: IDNP и № фиши", r.msg, "ok_card")
        lid = _lab(c, "Dental Lab Prim", contact="Andrei", phone="022 123 456")
        oid, nr = _order(c, pid, lid, urgent=True, note="Umăr <b>ceramic</b>",
                         items=[{"work": "Punte", "material": "Zirconiu", "teeth": [44, 45], "grp": 1, "price_bani": 420000},
                                {"work": "Punte", "material": "Zirconiu", "teeth": [46], "grp": 1}])
        r = c.get(f"/admin/lab/{oid}/tipar?back=" + urllib.parse.quote(f"/admin/patient/{pid}?tab=plan"))
        page = r.body
        res.check("лист открылся", r.status, 200)
        res.ok("номер, лаборатория, имя и № фиши, URGENT, мост одной строкой",
               f"nr {nr}" in page and "Dental Lab Prim" in page and "Maria Exemplu" in page and "F-77" in page
               and "URGENT" in page and page.count("<td>Punte</td>") == 1 and "44, 45, 46" in page, page[:400])
        res.ok("нет телефона пациента, IDNP, даты рождения, цены",
               "069100600" not in page and "2001234567890" not in page and "06.05.1980" not in page
               and "4200" not in page and "lei" not in page, "")
        res.ok("указания экранированы", "Umăr &lt;b&gt;ceramic&lt;/b&gt;" in page, "")
        res.ok("«Înapoi» — на фишу", f'href="/admin/patient/{pid}?tab=plan"' in page, "")
        res.ok("чужой адрес в back — список", 'href="/admin/lab"' in c.get(f"/admin/lab/{oid}/tipar?back=https://evil.example").body, "")
        res.ok("колонтитулы браузера погашены", "@page{margin:0" in page, "")
        evs = _get(c, f"/api/lab/order/{oid}")["order"]["events"]
        res.check("печать — событие tiparit (дважды открыт — два)", [e["kind"] for e in evs].count("tiparit"), 2)
        res.ok("и строка в летописи фиши",
               _sql(s, "SELECT COUNT(*) FROM activity WHERE patient_id = ? AND kind = 'lab_print'", pid)[0][0] == 2, "")
        c.post_json("/api/settings/lab/prefs", {"who": "fisa"})
        page = c.get(f"/admin/lab/{oid}/tipar").body
        res.ok("выбор клиники «№ фиши»: имени на листе нет", "Maria Exemplu" not in page and "Fișa nr. F-77" in page, "")
        res.ok("событие печати говорит, что ушло", "pacient: nr. fișă" in _get(c, f"/api/lab/order/{oid}")["order"]["events"][-1]["note"], "")
        res.check("нет заказа — 404", c.get("/admin/lab/9999/tipar").status, 404)
        res.check("без входа — на вход", Client(s.url).get(f"/admin/lab/{oid}/tipar").status in (303, 307), True)


def suite_195(res: Result) -> None:
    """Закон 195: заказ держит фишу от физического стирания; копия несёт заказы;
    состав выгрузки = состав удаления."""
    res.ok("состав удаления: шапка — ребёнок, строки и история — внуки",
           "lab_orders" in appdb._PATIENT_CHILD_TABLES
           and {("lab_order_items", "order_id", "lab_orders"), ("lab_events", "order_id", "lab_orders")}
           <= set(appdb._PATIENT_GRAND_CHILDREN), "")
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Pavel Lungu", "069100700")
        lid = _lab(c, "Dental Lab Prim")
        oid, _ = _order(c, pid, lid, note="Indicații")
        c.post_json(f"/api/lab/order/{oid}/cancel", {"why": "amânat"})
        r = c.get(f"/admin/patient/{pid}/export")
        z = zipfile.ZipFile(io.BytesIO(r.raw))
        data = json.loads(z.read("date-pacient.json"))
        lab = data.get("laborator") or [{}]
        res.check("машинная копия: заказ словами, без цены",
                  (lab[0].get("nr"), lab[0].get("stare"), lab[0].get("laborator"), "price_bani" in json.dumps(lab)),
                  (1, "Anulat", "Dental Lab Prim", False))
        html = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("читаемая копия — раздел заказов", "Comenzi la laboratorul dentar (1)" in html, "")
        res.check("отменённый заказ тоже держит фишу — обезличивание, не удаление",
                  c.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"}).msg, "ok_anon")
        res.check("заказ остался под номером фиши", _sql(s, "SELECT COUNT(*) FROM lab_orders WHERE patient_id = ?", pid)[0][0], 1)
        res.check("в списке — обезличенное имя (имя берётся из фиши)",
                  _get(c, "/api/lab?f=toate")["orders"][0]["patient"], f"Pacient anonimizat #{pid}")
        free = new_patient(c, "Fără lucrări", "069100701")
        res.check("фиша без заказов и лечения — физическое удаление проходит",
                  c.post_json(f"/api/patients/{free}/erase", {"confirm": "STERG"}).msg, "ok_del")
