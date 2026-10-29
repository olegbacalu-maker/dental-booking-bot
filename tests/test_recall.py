"""«Rechemări» — мини-CRM регистратуры (29.10.2026).

Правило списка (`core/recall.compute`) проверяется и чистой функцией на
выборках, и через сервер на засеве, которым заводится бумажная история у
клиники: запись задним числом (`harness.add_appt`) → «Finalizat». Отметки —
журналом (`recall_marks`), пересчёт их только читает: два запроса подряд и
пересохранение услуг без правки обязаны дать то же самое. Права — строкой в
`PERMS` (врач не видит список, строку срока в фише видит). Часы — подменные
(`harness.Clock`): срок считается от «сегодня» клиники, вечером по UTC
прогон не краснеет.
"""
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta

from harness import BOT, Client, Clock, Result, Server, TZ, _rmtree_settled, add_appt, appt_id, day_model, new_patient
from test_api import NO_KEY

sys.path.insert(0, str(BOT))
from app import db as appdb  # noqa: E402
from app.core import recall  # noqa: E402

API = "/api/recall"
MARK = "/api/recall/mark"
SMS = "/api/recall/sms"
SVC_API = "/api/settings/services"
# вторник 06.10.2026, 10:00 — рабочий день фикстуры (часы 7–21)
AT = datetime(2026, 10, 6, 10, 0, tzinfo=TZ)
TODAY = AT.date()


def _j(r) -> dict:
    return json.loads(r.body)


def _rows(c: Client) -> dict:
    r = c.get(API)
    if r.status != 200:
        raise AssertionError(f"список не отдан: {r.status} {r.body[:200]}")
    return _j(r)["data"]


def _sql(s: Server, sql: str, *args) -> list:
    """Первая колонка выборки из базы сервера; соединение закрывается сразу —
    открытое держит файл, и папка прогона не убирается."""
    con = sqlite3.connect(str(s.dir / "dental.db"))
    try:
        return [r[0] for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def _by(c: Client, name: str, sid: str = "hygiene") -> dict | None:
    return next((x for x in _rows(c)["rows"] if x["name"] == name and x["service_id"] == sid), None)


def _set_recall(c: Client, months: dict) -> None:
    """Срок у услуг тем же маршрутом, каким его задаёт директор."""
    rows = _j(c.get(SVC_API))["data"]["services"]
    for r in rows:
        if r["id"] in months:
            r["recall"] = months[r["id"]]
    r = c.post_json(SVC_API, {"services": rows})
    if r.msg != "ok_set":
        raise AssertionError(f"срок не сохранён: {r.status} {r.body[:200]}")


def _visit(c: Client, day: date, name: str, phone: str, status: str = "done",
           service: str = "hygiene", doctor: str = "d3", time: str = "09:00") -> int:
    """Визит задним числом со статусом — так заводится бумажная история."""
    r = add_appt(c, day.isoformat(), time, name, phone, doctor=doctor, service=service)
    if r.msg not in ("ok", "ok_past", "ok_other"):
        raise AssertionError(f"визит {name} {day}: {r.msg} {r.body[:200]}")
    aid = appt_id(c, day.isoformat(), name)
    if status != "confirmed":
        rs = c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": status})
        if rs.status != 200:
            raise AssertionError(f"статус {status}: {rs.status} {rs.body[:200]}")
    return aid


def _mk(result: str, cycle: int = 1, at: datetime | None = None, until: str = "") -> dict:
    return {"patient_id": 1, "service_id": "hygiene", "cycle_appt_id": cycle,
            "result": result, "until_date": until or None, "actor": "Ana",
            "at": at or datetime(2026, 10, 1, 8, 0, tzinfo=TZ)}


def suite_rule(res: Result) -> None:
    """Правило § 1 чистой функцией: только done, окно, горизонт, записан вперёд,
    прижатие месяца, отметки по циклу."""
    svcs = [{"id": "hygiene", "ro": "Igienizare", "months": 6, "since": "2026-10-01"}]

    def done(last: datetime, pid: int = 1, aid: int = 1, sid: str = "hygiene") -> dict:
        return {"patient_id": pid, "service_id": sid, "aid": aid, "doctor": "Dr. T",
                "last_at": last, "name": f"P{pid}", "phone": "0600", "email": "", "lang": "ro"}

    res.check("31.08 + 6 → 28.02 (прижатие к концу месяца)",
              recall.add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
    res.check("31.08.2027 + 6 → 29.02.2028 (високосный)",
              recall.add_months(date(2027, 8, 31), 6), date(2028, 2, 29))
    res.check("минус месяцы — тот же прижим", recall.add_months(date(2026, 3, 31), -1), date(2026, 2, 28))

    d = recall.compute([done(datetime(2026, 4, 6, 9, 0, tzinfo=TZ))], [], [], svcs, TODAY)
    res.check("done полгода назад — в списке, срок сегодня, late 0",
              [(x["pid"], x["due"], x["late_days"], x["late"], x["tab"]) for x in d["rows"]],
              [(1, "2026-10-06", 0, "azi", "due")])
    d = recall.compute([done(datetime(2026, 4, 20, 9, 0, tzinfo=TZ))], [], [], svcs, TODAY)
    res.check("срок через 14 дней — ещё в окне (В2 = 14)", [x["late"] for x in d["rows"]], ["peste 14 zile"])
    d = recall.compute([done(datetime(2026, 4, 21, 9, 0, tzinfo=TZ))], [], [], svcs, TODAY)
    res.check("срок через 15 дней — вне окна", d["rows"], [])
    d = recall.compute([done(datetime(2025, 10, 1, 9, 0, tzinfo=TZ))], [], [], svcs, TODAY)
    res.check("просрочка ровно один интервал от включения (due = since − 6 мес.) — в списке",
              [x["late"] for x in d["rows"]], ["întârziere 6 luni"])
    d = recall.compute([done(datetime(2025, 9, 30, 9, 0, tzinfo=TZ))], [], [], svcs, TODAY)
    res.check("старше горизонта — нет", d["rows"], [])
    res.check("услуга без срока — перечисление: строк нет",
              recall.compute([done(datetime(2026, 4, 6, tzinfo=TZ), sid="consult")], [], [], svcs, TODAY)["rows"], [])
    res.check("слово просрочки", [recall.late_word(TODAY - timedelta(days=n), TODAY) for n in (-2, -1, 1, 13, 14, 59, 60)],
              ["peste 2 zile", "mâine", "întârziere 1 zi", "întârziere 13 zile", "întârziere 2 săpt.",
               "întârziere 8 săpt.", "întârziere 2 luni"])

    # записан вперёд
    fut_same = [{"patient_id": 1, "service_id": "hygiene", "service": "Igienizare",
                 "next_at": datetime(2026, 11, 3, 9, 0, tzinfo=TZ)}]
    fut_other = [{"patient_id": 1, "service_id": "filling", "service": "Plombă",
                  "next_at": datetime(2026, 11, 3, 9, 0, tzinfo=TZ)}]
    base = [done(datetime(2026, 4, 6, 9, 0, tzinfo=TZ))]
    res.check("записан вперёд на ту же услугу — строки нет",
              recall.compute(base, fut_same, [], svcs, TODAY)["rows"], [])
    res.check("на другую — строка с пометкой",
              recall.compute(base, fut_other, [], svcs, TODAY)["rows"][0]["booked"],
              {"date": "03.11", "service": "Plombă"})

    # отметки по циклу
    tab = lambda marks: recall.compute(base, [], marks, svcs, TODAY)["rows"][0]["tab"]  # noqa: E731
    res.check("contacted сегодня — snoozed 14 дней", tab([_mk("contacted", at=AT)]), "snoozed")
    res.check("contacted 14 дней назад — снова due",
              tab([_mk("contacted", at=AT - timedelta(days=14))]), "due")
    res.check("later до завтра — snoozed, until датой",
              (tab([_mk("later", until="2026-10-07")]),
               recall.compute(base, [], [_mk("later", until="2026-10-07")], svcs, TODAY)["rows"][0]["mark"]["until"]),
              ("snoozed", "2026-10-07"))
    res.check("later до сегодня — due", tab([_mk("later", until="2026-10-06")]), "due")
    res.check("stop — stop, и через цикл", (tab([_mk("stop")]), tab([_mk("stop", cycle=99)])), ("stop", "stop"))
    res.check("отметка чужого цикла не действует", tab([_mk("contacted", cycle=99, at=AT)]), "due")
    r = recall.compute(base, [], [_mk("noanswer"), _mk("noanswer", at=AT)], svcs, TODAY)["rows"][0]
    res.check("noanswer считает попытки, остаётся в due",
              (r["tab"], r["mark"]["n_noanswer"], r["mark"]["word"], r["mark"]["at"]), ("due", 2, "nu răspunde", "06.10"))
    res.check("clear снимает последнюю", tab([_mk("stop"), _mk("clear")]), "due")
    res.check("clear снимает только последнюю: stop остаётся",
              tab([_mk("stop"), _mk("contacted", at=AT), _mk("clear")]), "stop")
    res.check("снятый stop прошлого цикла не воскресает в новом",
              tab([_mk("stop", cycle=99), _mk("clear", cycle=99)]), "due")
    # порядок: без отметки сверху, просроченные первыми, nu răspunde внизу
    many = [done(datetime(2026, 3, 1, 9, 0, tzinfo=TZ), pid=1, aid=1),
            done(datetime(2026, 2, 1, 9, 0, tzinfo=TZ), pid=2, aid=2),
            done(datetime(2026, 1, 20, 9, 0, tzinfo=TZ), pid=3, aid=3)]
    marks = [{**_mk("noanswer", cycle=3), "patient_id": 3}]
    res.check("порядок строк", [x["pid"] for x in recall.compute(many, [], marks, svcs, TODAY)["rows"]], [2, 1, 3])
    res.check("счётчики по вкладкам",
              recall.compute(many, [], [{**_mk("stop", cycle=2), "patient_id": 2}], svcs, TODAY)["counts"],
              {"due": 2, "snoozed": 0, "stop": 1})


def suite_server(res: Result) -> None:
    """Через сервер: срок у услуги, бумажная история, список, отметки, фиша,
    главная; всё вычислимое пересобирается, отметка переживает пересчёт."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        d = _rows(c)
        res.check("без услуг со сроком — пусто и services=[]",
                  (d["services"], d["rows"], d["counts"]), ([], [], {"due": 0, "snoozed": 0, "stop": 0}))
        res.check("имя и телефон клиники для письма", d["clinic"], {"name": "Clinica Test", "phone": "+373 60 000 000"})
        _set_recall(c, {"hygiene": 6})
        cfg = json.loads((s.dir / "clinic.json").read_text(encoding="utf-8"))
        hy = next(x for x in cfg["services"] if x["id"] == "hygiene")
        res.check("файл: months и since сегодняшней датой клиники",
                  hy.get("recall"), {"months": 6, "since": "2026-10-06"})
        res.check("экран услуг отдаёт срок и белый список",
                  (next(x["recall"] for x in _j(c.get(SVC_API))["data"]["services"] if x["id"] == "hygiene"),
                   _j(c.get(SVC_API))["data"]["recalls"]), (6, [0, 3, 4, 6, 9, 12, 24]))
        res.check("число вне белого списка — 422",
                  c.post_json(SVC_API, {"services": [{**x, "recall": 5} if x["id"] == "hygiene" else x
                                                     for x in _j(c.get(SVC_API))["data"]["services"]]}).status, 422)
        # смена месяцев since не трогает; пересохранение БЕЗ ключа — тождественно
        _set_recall(c, {"hygiene": 9})
        cfg = json.loads((s.dir / "clinic.json").read_text(encoding="utf-8"))
        res.check("смена месяцев: since цела", next(x for x in cfg["services"] if x["id"] == "hygiene")["recall"],
                  {"months": 9, "since": "2026-10-06"})
        rows = [{k: v for k, v in x.items() if k != "recall"} for x in _j(c.get(SVC_API))["data"]["services"]]
        c.post_json(SVC_API, {"services": rows})
        cfg2 = json.loads((s.dir / "clinic.json").read_text(encoding="utf-8"))
        res.check("строки без ключа recall (старая вкладка) — срок цел, конфиг тот же",
                  cfg2["services"], cfg["services"])
        _set_recall(c, {"hygiene": 6})

        # бумажная история: визит задним числом + «Finalizat»
        p_due = _visit(c, date(2026, 4, 2), "Maria Scadent", "069810001")          # срок 02.10, просрочка 4 дня
        _visit(c, date(2026, 4, 2), "Noshow Nu", "069810002", status="noshow", time="10:00")
        _visit(c, date(2026, 4, 2), "Cancel Nu", "069810003", status="cancelled", time="11:00")
        _visit(c, date(2026, 4, 2), "Programat Nu", "069810004", status="confirmed", time="12:00")
        _visit(c, date(2026, 4, 2), "Consult Nu", "069810005", service="consult", doctor="d2", time="13:00")
        p_same = _visit(c, date(2026, 4, 3), "Ion Rezervat", "069810006")
        p_other = _visit(c, date(2026, 4, 3), "Elena Altul", "069810007", time="10:00")
        _visit(c, date(2026, 4, 21), "Irina Devreme", "069810008")                 # срок 21.10 — через 15 дней, вне окна
        _visit(c, date(2025, 9, 1), "Ana Veche", "069810009")                      # старше горизонта
        pid_same = _j(c.get(f"/api/schedule/day?date=2026-04-03"))  # noqa: F841 — прогрев дня
        # записи вперёд
        add_appt(c, "2026-11-03", "09:00", "Ion Rezervat", "069810006", doctor="d3", service="hygiene")
        add_appt(c, "2026-11-03", "10:00", "Elena Altul", "069810007", doctor="d2", service="long")

        d = _rows(c)
        res.check("в списке только done в окне и горизонте; записанный на ту же услугу — нет",
                  sorted(x["name"] for x in d["rows"]), ["Elena Altul", "Maria Scadent"])
        m = _by(c, "Maria Scadent")
        res.check("строка: даты датами, просрочка, врач, язык, вкладка",
                  (m["last_at"], m["due"], m["late_days"], m["late"], m["doctor"], m["lang"], m["tab"], m["months"]),
                  ("2026-04-02", "2026-10-02", 4, "întârziere 4 zile", "Dr. Activ Trei", "ro", "due", 6))
        e = _by(c, "Elena Altul")
        res.check("записан на другую услугу — пометка", e["booked"], {"date": "03.11", "service": "Tratament lung"})
        res.check("счётчики", d["counts"], {"due": 2, "snoozed": 0, "stop": 0})

        # отметки
        pid_m = m["pid"]
        res.check("незнакомая отметка — 422", c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "x"}).status, 422)
        res.check("later без даты — 422 с полем",
                  (c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "later"}).status,
                   _j(c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "later", "until": "azi"})).get("field")),
                  (422, "until"))
        res.check("пары без done-визита — 409",
                  c.post_json(MARK, {"pid": pid_m, "service_id": "consult", "result": "stop"}).msg, "recall_gone")
        res.check("noanswer — ok", c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "noanswer"}).msg, "ok_recall")
        c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "noanswer"})
        m = _by(c, "Maria Scadent")
        res.check("nu răspunde ×2, автор, дата; строка ушла вниз",
                  (m["mark"]["result"], m["mark"]["n_noanswer"], m["mark"]["actor"], m["mark"]["at"], m["tab"],
                   [x["name"] for x in _rows(c)["rows"]]),
                  ("noanswer", 2, "Director", "06.10", "due", ["Elena Altul", "Maria Scadent"]))
        feed = [a["text"] for a in _j(c.get(f"/api/patients/{pid_m}/activity"))["data"]["items"]]
        res.ok("летопись: готовая строка", "Rechemare Igienizare: nu răspunde" in feed, f"{feed[:3]}")
        res.check("later до даты — snoozed с until",
                  (c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "later", "until": "2026-11-28"}).msg,
                   _by(c, "Maria Scadent")["tab"], _by(c, "Maria Scadent")["mark"]["until"], _rows(c)["counts"]),
                  ("ok_recall", "snoozed", "2026-11-28", {"due": 1, "snoozed": 1, "stop": 0}))
        res.ok("летопись: amânat с датой", any(t == "Rechemare Igienizare: amânat până la 28.11.2026" for t in
                                              [a["text"] for a in _j(c.get(f"/api/patients/{pid_m}/activity"))["data"]["items"]]),
               "строка без даты")
        c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "clear"})
        res.check("clear возвращает прежнюю (nu răspunde ×2)",
                  (_by(c, "Maria Scadent")["tab"], _by(c, "Maria Scadent")["mark"]["n_noanswer"]), ("due", 2))
        c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "contacted"})
        res.check("contacted — snoozed до +14", (_by(c, "Maria Scadent")["tab"], _by(c, "Maria Scadent")["mark"]["until"]),
                  ("snoozed", "2026-10-20"))
        c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "stop"})
        res.check("stop — вкладка stop", (_by(c, "Maria Scadent")["tab"], _rows(c)["counts"]["stop"]), ("stop", 1))

        # отметка переживает пересчёт: два запроса и пересохранение услуг без правки
        before = _rows(c)
        rows_svc = _j(c.get(SVC_API))["data"]["services"]
        c.post_json(SVC_API, {"services": rows_svc})
        res.check("два запроса подряд и пересохранение услуг — тот же список", (_rows(c), _rows(c)), (before, before))
        res.check("таблица отметок — только дописывалась",
                  _sql(s, "SELECT result FROM recall_marks ORDER BY id"),
                  ["noanswer", "noanswer", "later", "clear", "contacted", "stop"])

        # фиша: строка срока; stop → can_clear у директора
        card = _j(c.get(f"/api/patients/{pid_m}"))["data"]
        res.check("фиша: строка срока", card["recall"],
                  [{"service": "Igienizare", "service_id": "hygiene", "last": "02.04.2026", "next": "02.10.2026",
                    "late_days": 4, "late": "întârziere 4 zile", "stop": True, "can_clear": True,
                    "mark": {"result": "stop", "word": "nu mai reamintim", "until": "", "n_noanswer": 2,
                             "at": "06.10", "actor": "Director"}}])
        res.check("фиша пациента вне окна — строка тоже есть (факт, не список)",
                  [(x["next"], x["late"]) for x in _j(c.get(f"/api/patients/{p_other and _by(c, 'Elena Altul')['pid']}"))["data"]["recall"]],
                  [("03.10.2026", "întârziere 3 zile")])
        c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "clear"})

        # главная: раздел в конверте, первые строки due, детерминизм
        live = _j(c.get("/api/schedule/live?screen=panel"))["data"]["desk"]["recall"]
        res.check("desk.recall: счётчик и строки due (Maria — snoozed после clear: действует contacted)",
                  (live["n"], [x["name"] for x in live["items"]], _by(c, "Maria Scadent")["tab"]),
                  (1, ["Elena Altul"], "snoozed"))
        r1 = c.get("/api/schedule/live?screen=panel")
        r2 = c.get("/api/schedule/live?screen=panel", headers={"X-DP-Hash": r1.header("X-DP-Hash")})
        res.check("два опроса при неизменных данных — тот же отпечаток (204)", r2.status, 204)

        # всё вычислимое пересобирается: новый done гасит отметки кроме stop
        c.post_json(MARK, {"pid": pid_m, "service_id": "hygiene", "result": "noanswer"})
        _visit(c, date(2026, 10, 5), "Maria Scadent", "069810001", time="14:00")
        res.check("новый done той же услуги — строки нет (срок через 6 мес.), отметка не действует",
                  _by(c, "Maria Scadent"), None)
        card = _j(c.get(f"/api/patients/{pid_m}"))["data"]["recall"]
        res.check("фиша: новый цикл без отметки", (card[0]["last"], card[0]["next"], card[0]["mark"]),
                  ("05.10.2026", "05.04.2027", None))
        # смена процедуры визита — список новый без записи в recall_marks
        aid_e = appt_id(c, "2026-04-03", "Elena Altul")
        r = c.post_json(f"/api/schedule/appointments/{aid_e}/service", {"service_id": "consult"})
        res.ok("смена процедуры закрытого визита — отказ (svc_closed), как у окна", r.msg == "svc_closed", r.msg)
        # снятый срок — список пуст, отметки лежат без дела; вернули — вернулись
        _set_recall(c, {"hygiene": 0})
        res.check("срок снят — пусто", (_rows(c)["services"], _rows(c)["rows"]), ([], []))
        cfg = json.loads((s.dir / "clinic.json").read_text(encoding="utf-8"))
        res.ok("снятие убирает и since", "recall" not in next(x for x in cfg["services"] if x["id"] == "hygiene"), "since осталась")
        _set_recall(c, {"hygiene": 6})
        res.check("вернули срок — Elena снова в списке, Maria нет (новый цикл)",
                  [x["name"] for x in _rows(c)["rows"]], ["Elena Altul"])
        res.check("since заново — сегодня (горизонт от нового включения)",
                  _rows(c)["services"][0]["since"], "2026-10-06")


def suite_past_done(res: Result) -> None:
    """Галочка «Vizita a avut loc» (В3 = А): запись на прошедший день ложится
    сразу finalizată и заводит часы; на сегодня — игнорируется."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        _set_recall(c, {"hygiene": 6})
        r = add_appt(c, "2026-04-02", "09:00", "Hartie Veche", "069820001", doctor="d3", service="hygiene", done=True)
        res.check("ответ — ok_past_done", r.msg, "ok_past_done")
        aid = appt_id(c, "2026-04-02", "Hartie Veche")
        row = next(x for x in _j(c.get("/api/schedule/day?date=2026-04-02"))["data"]["list"] if x["id"] == aid)
        res.check("статус done", row["status"], "done")
        res.check("и в списке отзыва", [x["name"] for x in _rows(c)["rows"]], ["Hartie Veche"])
        r = add_appt(c, TODAY.isoformat(), "15:00", "Azi Nu", "069820002", doctor="d3", service="hygiene", done=True)
        res.check("на сегодня галочка игнорируется: обычный ok, визит programată",
                  (r.msg, next(x for x in _j(c.get(f"/api/schedule/day?date={TODAY.isoformat()}"))["data"]["list"]
                               if x["name"] == "Azi Nu")["status"]), ("ok", "confirmed"))
        r = add_appt(c, "2026-04-02", "10:00", "Fara Bifa", "069820003", doctor="d3", service="hygiene")
        res.check("без галочки — как было: ok_past, programată",
                  (r.msg, next(x for x in _j(c.get("/api/schedule/day?date=2026-04-02"))["data"]["list"]
                               if x["name"] == "Fara Bifa")["status"]), ("ok_past", "confirmed"))


def suite_rights(res: Result) -> None:
    """Права: врач — 403 на /api/recall*, desk.recall null, пункта меню нет,
    строку срока в фише видит без can_clear; регистратура — всё."""
    with Clock(AT), Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        for body in ({"uid": "d3", "name": "Dr. Activ Trei", "role": "medic", "doctor_id": "d3", "pin": "2222"},
                     {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "4444"}):
            boss.post_json("/api/settings/users", body)
        _set_recall(boss, {"hygiene": 6})
        pid = _visit(boss, date(2026, 4, 2), "Drept Test", "069830001")
        boss.post_json(MARK, {"pid": pid, "service_id": "hygiene", "result": "stop"})

        def login(pin):
            x = Client(s.url)
            x.post("/admin/login", password=pin, next="/admin")
            return x
        med, rec = login("2222"), login("4444")
        res.check("врач: список, отметка и SMS — 403",
                  (med.get(API).status, med.post_json(MARK, {"pid": pid, "service_id": "hygiene", "result": "clear"}).status,
                   med.post_json(SMS, {"pid": pid, "service_id": "hygiene"}).status), (403, 403, 403))
        res.check("врач: страница — отказ", med.get("/admin/rechemari").status in (303, 403), True)
        res.check("врач: desk.recall = null", _j(med.get("/api/schedule/live?screen=panel"))["data"]["desk"]["recall"], None)
        from harness import shell_model
        keys = [i["key"] for i in shell_model(med.get("/admin").body)["nav"]["items"]]
        res.ok("врач: пункта «Rechemări» нет в меню", "rec" not in keys, f"{keys}")
        card = _j(med.get(f"/api/patients/{pid}"))["data"]
        res.check("врач: строку срока видит, снять stop не может",
                  (card["recall"][0]["stop"], card["recall"][0]["can_clear"]), (True, False))
        res.check("регистратура: список, отметка, меню, can_clear",
                  (rec.get(API).status, rec.post_json(MARK, {"pid": pid, "service_id": "hygiene", "result": "clear"}).msg,
                   "rec" in [i["key"] for i in shell_model(rec.get("/admin").body)["nav"]["items"]],
                   _j(rec.get(f"/api/patients/{pid}"))["data"]["recall"][0]["can_clear"]),
                  (200, "ok_recall", True, False))
        res.ok("регистратура: desk.recall есть",
               _j(rec.get("/api/schedule/live?screen=panel"))["data"]["desk"]["recall"]["n"] == 1, "раздела нет")
        res.check("без входа — 401", Client(s.url).get(API).status, 401)


def suite_195(res: Result) -> None:
    """Закон 195: отметки в выгрузке, стираются с фишей, обезличенный из списка уходит."""
    with Clock(AT), Server() as s:
        c = Client(s.url).login()
        _set_recall(c, {"hygiene": 6})
        pid = _visit(c, date(2026, 4, 2), "Lege Test", "069840001")
        c.post_json(MARK, {"pid": pid, "service_id": "hygiene", "result": "noanswer"})
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.check("отметки в машинной копии", [(m["result"], m["service_id"]) for m in data["rechemari"]], [("noanswer", "hygiene")])
        html = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("и в читаемой", "<h2>Rechemări (1)</h2>" in html and "nu răspunde" in html, "HTML-копия без отметок")
        res.ok("состав выгрузки = состав удаления", "recall_marks" in appdb._PATIENT_CHILD_TABLES, "нет в _PATIENT_CHILD_TABLES")
        res.check("обезличивание (визит — медзапись) проходит",
                  c.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"}).msg, "ok_anon")
        res.check("обезличенный из списка ушёл", _rows(c)["rows"], [])
        res.check("отметки остались (в них нет личности)",
                  _sql(s, "SELECT COUNT(*) FROM recall_marks WHERE patient_id = ?", pid), [1])
        pid2 = new_patient(c, "Sterg Test", "069840002")
        res.check("физическое удаление фиши без медзаписей проходит",
                  c.post_json(f"/api/patients/{pid2}/erase", {"confirm": "STERG"}).msg, "ok_del")


def suite_stats(res: Result) -> None:
    """Статистика одной строкой (В4 → Б, Олег 29.10): отметка → запись на ту
    же услугу → счёт; на другую — не считается; пустой месяц — нули;
    чистая функция по дню клиники; тело детерминировано в пределах дня."""
    ct = lambda **k: {"patient_id": 1, "service_id": "hygiene", "at": datetime(2026, 10, 3, 9, 0, tzinfo=TZ), **k}  # noqa: E731
    bk = lambda **k: {"patient_id": 1, "service_id": "hygiene", "created_at": datetime(2026, 10, 3, 12, 0, tzinfo=TZ), **k}  # noqa: E731
    cur, nxt, prev = date(2026, 10, 1), date(2026, 11, 1), date(2026, 9, 1)
    res.check("начала месяцев", (recall.month_start(TODAY), recall.month_start(TODAY, 1), recall.month_start(date(2026, 1, 15), 1)),
              (cur, prev, date(2025, 12, 1)))
    res.check("пусто — нули", recall.count_stats([], [], cur, nxt), {"contacted": 0, "booked": 0})
    res.check("отметка без записи — contactați 1", recall.count_stats([ct()], [], cur, nxt), {"contacted": 1, "booked": 0})
    res.check("запись после отметки на ту же услугу — programați 1",
              recall.count_stats([ct()], [bk()], cur, nxt), {"contacted": 1, "booked": 1})
    res.check("запись ДО отметки — не считается",
              recall.count_stats([ct()], [bk(created_at=datetime(2026, 10, 3, 8, 0, tzinfo=TZ))], cur, nxt), {"contacted": 1, "booked": 0})
    res.check("запись на другую услугу — не считается",
              recall.count_stats([ct()], [bk(service_id="consult")], cur, nxt), {"contacted": 1, "booked": 0})
    res.check("пациент с двумя услугами — один раз",
              recall.count_stats([ct(), ct(service_id="consult")], [bk()], cur, nxt), {"contacted": 1, "booked": 1})
    res.check("отметка прошлого месяца — в prev, не в month",
              (recall.count_stats([ct(at=datetime(2026, 9, 30, 23, 30, tzinfo=TZ))], [], cur, nxt),
               recall.count_stats([ct(at=datetime(2026, 9, 30, 23, 30, tzinfo=TZ))], [], prev, cur)),
              ({"contacted": 0, "booked": 0}, {"contacted": 1, "booked": 0}))
    res.check("граница месяца — по дню клиники (01.10 00:30 Кишинёв = 30.09 UTC)",
              recall.count_stats([ct(at=datetime(2026, 10, 1, 0, 30, tzinfo=TZ))], [], cur, nxt), {"contacted": 1, "booked": 0})

    with Clock(AT) as clock, Server() as s:
        c = Client(s.url).login()
        _set_recall(c, {"hygiene": 6})
        res.check("сервер: пустой журнал — stats null (строки нет, нули не рисуются)", _rows(c)["stats"], None)
        p1 = _visit(c, date(2026, 4, 2), "Stat Unu", "069850001")
        p2 = _visit(c, date(2026, 4, 2), "Stat Doi", "069850002", time="10:00")
        p3 = _visit(c, date(2026, 4, 2), "Stat Trei", "069850003", time="11:00")
        for pid, resu in ((p1, "contacted"), (p2, "emailed"), (p3, "noanswer")):
            c.post_json(MARK, {"pid": pid, "service_id": "hygiene", "result": resu})
        res.check("contactați — только sunat/e-mail (noanswer не считается)", _rows(c)["stats"]["month"], {"contacted": 2, "booked": 0})
        # запись ПОСЛЕ отметки — часы вперёд на минуту (в одну секунду с отметкой «после» нет)
        clock.set(AT + timedelta(minutes=1))
        add_appt(c, "2026-11-03", "09:00", "Stat Unu", "069850001", doctor="d3", service="hygiene")
        add_appt(c, "2026-11-03", "10:00", "Stat Doi", "069850002", doctor="d2", service="long")
        res.check("записался на ту же услугу — programați 1; на другую — нет", _rows(c)["stats"]["month"], {"contacted": 2, "booked": 1})
        res.check("прошлый месяц рядом с живым — нули", _rows(c)["stats"]["prev"], {"contacted": 0, "booked": 0})
        res.check("два запроса подряд — то же", _rows(c)["stats"], _rows(c)["stats"])


def suite_schema(res: Result) -> None:
    """DDL шага 8 и схемы — один текст; версия схемы 8."""
    res.ok("RECALL_DDL дословно в SQLITE_CARD_SCHEMA",
           appdb.RECALL_DDL in appdb.SQLITE_CARD_SCHEMA and appdb.RECALL_IDX_DDL in appdb.SQLITE_CARD_SCHEMA,
           "текст таблицы в схеме и в шаге 8 разошёлся")
    res.check("шаг 8 кладёт именно его", appdb.MIGRATIONS[8], [appdb.RECALL_DDL, appdb.RECALL_IDX_DDL])
    res.check("версия схемы — 8", appdb.SCHEMA_VERSION, 8)
    with Server() as s:
        res.check("чистая установка: таблица и индекс есть",
                  sorted(_sql(s, "SELECT name FROM sqlite_master WHERE name IN ('recall_marks', 'ix_recall_pat')")),
                  ["ix_recall_pat", "recall_marks"])


def suite_sms(res: Result) -> None:
    """SMS из списка (30.10, Олег «все А»): гейт — `enabled()`, не `offered()`
    (у Basic offered тоже true); кнопка по данным строки; отправка синхронно
    с записью в sms_log (kind recall, appt_id NULL), отметкой `sms` и
    летописью от вошедшего; повтор — dup; отказы сервера словами, без записи;
    недоставленная возвращает в due; SMS в «contactați»; галочка в Setări › SMS
    переживает пересохранение; `active()` следует за ней."""
    import test_license_renew as lr
    from test_sms import KEY_ENV, TICK, TOKEN, Stand, _at, _clinic_weekdays, _events, _sms_log, _wait

    # чистые куски: кнопка по данным, недоставленная — в due, ключ
    base = {"patient_id": 1, "phone": "069 123 456", "sms_off": 0}
    ctx = {"on": True, "clinic_phone": True}
    res.check("кнопка: мобильный — can", recall.sms_button(base, 5, "hygiene", ctx, {}), {"can": True, "why": ""})
    res.check("кнопка: отказ пациента", recall.sms_button({**base, "sms_off": 1}, 5, "hygiene", ctx, {}),
              {"can": False, "why": "sms_off"})
    res.check("кнопка: стационарный", recall.sms_button({**base, "phone": "022 123 456"}, 5, "hygiene", ctx, {}),
              {"can": False, "why": "phone"})
    res.check("кнопка: без телефона клиники", recall.sms_button(base, 5, "hygiene", {"on": True, "clinic_phone": False}, {}),
              {"can": False, "why": "no_clinic_phone"})
    res.check("кнопка: гейт закрыт — None; SMS цикла уже есть — None",
              (recall.sms_button(base, 5, "hygiene", None, {}),
               recall.sms_button(base, 5, "hygiene", ctx, {"recall:1:hygiene:5": {"state": "sent"}})), (None, None))
    key = recall.splan.recall_idem(1, "hygiene", 1)
    res.check("ключ", key, "recall:1:hygiene:1")
    ev = [_mk("sms")]
    res.check("отметка sms, SMS sent — snoozed со словом «SMS trimis»",
              recall.mark_state(ev, 1, TODAY, {key: {"state": "sent"}}),
              ("snoozed", {"result": "sms", "word": "SMS trimis", "until": "2026-10-15", "n_noanswer": 0, "at": "01.10",
                           "actor": "Ana", "sms": {"state": "sent", "word": "SMS trimis"}}))
    res.check("отметка sms, SMS undelivered — сразу due, слово «SMS nelivrat»",
              recall.mark_state(ev, 1, TODAY, {key: {"state": "undelivered"}})[0:1]
              + (recall.mark_state(ev, 1, TODAY, {key: {"state": "undelivered"}})[1]["sms"],),
              ("due", {"state": "undelivered", "word": "SMS nelivrat"}))
    res.check("отметка sms, failed — due", recall.mark_state(ev, 1, TODAY, {key: {"state": "failed"}})[0], "due")
    res.check("отметка sms прошлого цикла не действует", recall.mark_state(ev, 2, TODAY, {})[0], "due")

    stand = Stand()
    stand.account["blocked"] = "sms_basic"          # Basic: предложен, но не пускает
    renew = {"url": stand.url, "token": TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_rcsms_"))
    env = {**KEY_ENV, **TICK}
    try:
        _clinic_weekdays(d)
        (d / "license.json").write_text(lr._file(5, renew), encoding="utf-8")
        with Clock(AT) as clock, Server(dir_=d, env=env) as s:
            c = Client(s.url).login()
            _set_recall(c, {"hygiene": 6})
            pid = _visit(c, date(2026, 4, 2), "Sms Rechem", "069870001")
            pid_fix = _visit(c, date(2026, 4, 2), "Sms Fix", "022123456", time="10:00")
            pid_ref = _visit(c, date(2026, 4, 2), "Sms Refuz", "069870003", time="11:00")
            pid4 = _visit(c, date(2026, 4, 2), "Sms Patru", "069870004", time="12:00")
            pid5 = _visit(c, date(2026, 4, 2), "Sms Cinci", "069870005", time="13:00")
            c.post_json(f"/api/patients/{pid_ref}/sms-off", {"on": True})
            acc = _wait(lambda: (lambda x: x if x.get("offered") else None)(_j(c.get("/api/settings/sms"))["data"]))
            res.ok("стенд: счёт прочитан, offered true, blocked sms_basic", acc and acc["blocked"] == "sms_basic", repr(acc)[:300])
            d0 = _rows(c)
            res.check("Basic: sms null, у строк кнопки нет — гейт enabled(), не offered()",
                      (d0["sms"], [r["sms"] for r in d0["rows"]]), (None, [None] * 5))
            res.check("Basic: POST — recall_sms_off", c.post_json(SMS, {"pid": pid, "service_id": "hygiene"}).msg, "recall_sms_off")
            res.ok("pure: recall_on false, active false (события по умолчанию: накануне вкл. — но сервер не пускает)",
                   not _j(c.get("/api/settings/sms"))["data"]["active"])

            # Plus
            stand.account["blocked"] = ""
            c.post_json("/api/settings/sms/refresh", {})
            d1 = _rows(c)
            res.check("Plus: блок sms — остаток 100, не тихие часы", d1["sms"], {"on": True, "balance": 100, "quiet": False})
            by = {x["name"]: x for x in d1["rows"]}
            res.check("кнопки по данным: мобильный — can; стационарный — phone; отказ — sms_off",
                      (by["Sms Rechem"]["sms"]["can"], by["Sms Fix"]["sms"]["why"], by["Sms Refuz"]["sms"]["why"]),
                      (True, "phone", "sms_off"))
            t = by["Sms Rechem"]["sms"]
            res.ok("текст строки: клиника и телефон, без услуги, даты и цен; один сегмент",
                   "Clinica Test" in t["text"] and "+373 60 000 000" in t["text"] and "Igienizare" not in t["text"]
                   and "controlul periodic" in t["text"] and t["segments"] == 1 and "%" not in t["text"], repr(t))
            live = _j(c.get("/api/schedule/live?screen=panel"))["data"]["desk"]["recall"]
            res.ok("главная: строки без текста SMS и без «сейчас» (блок данных, не часа)",
                   live["items"] and all("text" not in (it.get("sms") or {}) for it in live["items"]), repr(live)[:300])

            # отказы до сервера
            clock.set(_at(2026, 10, 6, 21, 30))
            res.check("тихие часы: quiet true в конверте, POST — recall_sms_quiet",
                      (_rows(c)["sms"]["quiet"], c.post_json(SMS, {"pid": pid, "service_id": "hygiene"}).msg),
                      (True, "recall_sms_quiet"))
            clock.set(AT + timedelta(minutes=1))      # вперёд, не назад: отметки позже визитов
            res.check("отказ пациента — recall_sms_refused", c.post_json(SMS, {"pid": pid_ref, "service_id": "hygiene"}).msg, "recall_sms_refused")
            res.check("стационарный — recall_sms_phone", c.post_json(SMS, {"pid": pid_fix, "service_id": "hygiene"}).msg, "recall_sms_phone")
            res.check("пары без визита — recall_gone", c.post_json(SMS, {"pid": pid, "service_id": "consult"}).msg, "recall_gone")
            res.check("кривое тело — 422", c.post_json(SMS, {"pid": "x"}).status, 422)
            res.check("отметку sms руками — 422", c.post_json(MARK, {"pid": pid, "service_id": "hygiene", "result": "sms"}).status, 422)
            res.check("без входа — 401", Client(s.url).post_json(SMS, {"pid": pid, "service_id": "hygiene"}).status, 401)

            # отказы сервера — словами, без записи
            stand.send_mode = "balance"
            r = c.post_json(SMS, {"pid": pid, "service_id": "hygiene"})
            res.ok("нет остатка: sms_denied словами WHY, ни строки, ни отметки",
                   r.msg == "sms_denied" and r.status == 409 and "pachetul SMS s-a terminat" in _j(r)["text"]
                   and _sms_log(d) == [] and _sql(s, "SELECT COUNT(*) FROM recall_marks") == [0], r.body[:300])
            stand.send_mode = "down"
            r = c.post_json(SMS, {"pid": pid, "service_id": "hygiene"})
            res.check("сервер молчит — sms_offline 503, записи нет", (r.msg, r.status, _sms_log(d)), ("sms_offline", 503, []))
            stand.send_mode = "ok"

            # отправка
            r = c.post_json(SMS, {"pid": pid, "service_id": "hygiene"})
            res.check("ok_recall_sms: sent, остаток 99", (r.msg, _j(r)["data"]), ("ok_recall_sms", {"state": "sent", "balance": 99}))
            aid = appt_id(c, "2026-04-02", "Sms Rechem")
            sent = stand.sends[-1]["json"]
            res.ok("серверу: kind recall, ключ recall:<pid>:hygiene:<aid>, восемь цифр, текст строки",
                   sent["kind"] == "recall" and sent["idem"] == f"recall:{pid}:hygiene:{aid}" and sent["to"] == "69870001"
                   and sent["text"] == t["text"], repr(sent))
            rows = _sms_log(d)
            res.ok("sms_log: одна строка kind recall, appt_id NULL, sent, cloud_id",
                   len(rows) == 1 and rows[0]["kind"] == "recall" and rows[0]["appt_id"] is None
                   and rows[0]["state"] == "sent" and rows[0]["cloud_id"] == 1 and rows[0]["patient_id"] == pid, repr(rows))
            row = _by(c, "Sms Rechem")
            res.check("строка: отметка sms, слово доставки, snoozed, кнопки нет",
                      (row["mark"]["result"], row["mark"]["word"], row["mark"]["sms"], row["tab"], row["sms"], row["mark"]["actor"]),
                      ("sms", "SMS trimis", {"state": "sent", "word": "SMS trimis"}, "snoozed", None, "Director"))
            feed = _j(c.get(f"/api/patients/{pid}/activity"))["data"]["items"]
            hit = next((a for a in feed if str(a.get("text", "")).startswith("SMS trimis (rechemare Igienizare)")), None)
            res.ok("летопись: «SMS trimis (rechemare Igienizare)» от имени вошедшего, не sistem",
                   hit is not None and hit.get("who") == "Director", repr(feed[:3]))
            res.ok("колокольчик прошлого визита не горит (appt_id NULL)",
                   not next(x for x in day_model(c, "2026-04-02")["list"] if x["name"] == "Sms Rechem")["reminded"])
            res.ok("остаток на экране SMS — 99", _j(c.get("/api/settings/sms"))["data"]["account"]["balance"] == 99)
            # повтор
            r = c.post_json(SMS, {"pid": pid, "service_id": "hygiene"})
            res.check("второе нажатие — recall_sms_dup, у стенда одна SMS", (r.msg, len(stand._by_idem)), ("recall_sms_dup", 1))
            c.post_json(MARK, {"pid": pid, "service_id": "hygiene", "result": "clear"})
            row = _by(c, "Sms Rechem")
            res.check("«Anulează marcajul»: строка в due, кнопки всё равно нет — решает sms_log",
                      (row["tab"], row["mark"], row["sms"]), ("due", None, None))

            # доставка: undelivered возвращает в due, delivered — тишина
            c.post_json(SMS, {"pid": pid4, "service_id": "hygiene"})
            c.post_json(SMS, {"pid": pid5, "service_id": "hygiene"})
            aid4, aid5 = appt_id(c, "2026-04-02", "Sms Patru"), appt_id(c, "2026-04-02", "Sms Cinci")
            stand.states = {stand._by_idem[f"recall:{pid4}:hygiene:{aid4}"]: "undelivered",
                            stand._by_idem[f"recall:{pid5}:hygiene:{aid5}"]: "delivered"}
            clock.set(AT + timedelta(minutes=6))
            got = _wait(lambda: (lambda x: x if x and x["mark"] and x["mark"]["sms"]["state"] == "undelivered" else None)(_by(c, "Sms Patru")))
            res.ok("недоставленная: строка снова в «De sunat» с «SMS nelivrat», кнопки нет",
                   got is not None and got["tab"] == "due" and got["mark"]["sms"]["word"] == "SMS nelivrat" and got["sms"] is None,
                   repr(got))
            r5 = _by(c, "Sms Cinci")
            res.check("доставленная: snoozed, «SMS livrat»", (r5["tab"], r5["mark"]["sms"]), ("snoozed", {"state": "delivered", "word": "SMS livrat"}))
            res.ok("летопись pid4: SMS nelivrat (rechemare) от sistem",
                   any(t_.startswith("SMS nelivrat (rechemare)") for t_ in _events(d, pid4)), repr(_events(d, pid4)))
            card = _j(c.get(f"/api/patients/{pid4}"))["data"]["recall"][0]
            res.check("фиша: отметка sms со словом доставки", (card["mark"]["result"], card["mark"]["sms"]["word"]), ("sms", "SMS nelivrat"))
            res.check("статистика: SMS — в contactați (3 пациента, clear не вычитает)",
                      _rows(c)["stats"]["month"], {"contacted": 3, "booked": 0})

            # галочка в Setări › SMS
            s0 = _j(c.get("/api/settings/sms"))["data"]["settings"]
            c.post_json("/api/settings/sms", {**s0, "recall": {"on": False, "variant": "standard"}})
            res.check("галочка снята: sms null, POST — recall_sms_off",
                      (_rows(c)["sms"], c.post_json(SMS, {"pid": pid_fix, "service_id": "hygiene"}).msg), (None, "recall_sms_off"))
            s1 = _j(c.get("/api/settings/sms"))["data"]["settings"]
            c.post_json("/api/settings/sms", s1)
            res.check("пересохранение без правки — тождественно (ключ recall не стёрт)", _j(c.get("/api/settings/sms"))["data"]["settings"], s1)
            c.post_json("/api/settings/sms", {**s1, "day_before": {**s1["day_before"], "on": False}})
            res.ok("события и галочка выключены — active false (точка меню off)", not _j(c.get("/api/settings/sms"))["data"]["active"])
            c.post_json("/api/settings/sms", {**s1, "day_before": {**s1["day_before"], "on": False}, "recall": {"on": True, "variant": "scurt"}})
            res.ok("галочка стоит, события выключены — active true (лист acord с SMS)",
                   _j(c.get("/api/settings/sms"))["data"]["active"])
            res.ok("вариант scurt — короткий текст в строке",
                   _by(c, "Sms Fix")["sms"]["text"].startswith("Clinica Test: e timpul pentru controlul periodic"),
                   repr(_by(c, "Sms Fix")["sms"]))
            res.check("два запроса подряд — то же", _rows(c), _rows(c))
    finally:
        stand.close()
        _rmtree_settled(d)
