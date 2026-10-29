"""«La recepție» (01.10): рабочие списки регистратуры в правой колонке
главной — тем же конвертом живого канала, что и канва.

Что стережётся: списки считаются от СЕГОДНЯ клиники (часы прогона
подменены: вторник, 10:00), звонок-подтверждение — командой с отметкой и
строкой в летописи, деньги — только тому, кому положены (PERM_MONEY).
"""
import json
import sqlite3
from datetime import datetime, timedelta

from harness import Client, Clock, FIXTURES, Result, Server, TZ, pid_by_phone
from test_api import NO_KEY

_DOW = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return pid_by_phone(c, phone)


def _hours() -> dict:
    return json.loads((FIXTURES / "clinic_test.json").read_text(encoding="utf-8"))["hours"]


def _next_open(d):
    h = _hours()
    for _ in range(14):
        if h.get(_DOW[d.weekday()]):
            return d
        d += timedelta(days=1)
    return d


def _desk(c: Client) -> dict:
    return _j(c.get("/api/schedule/live"))["data"]["desk"]


def suite_desk(res: Result) -> None:
    # вторник 06.10.2026, 10:00 — рабочий день; «завтра» — среда
    with Clock(datetime(2026, 10, 6, 10, 0, tzinfo=TZ)), Server() as s:
        c = Client(s.url).login()
        today = datetime(2026, 10, 6).date()
        nxt = _next_open(today + timedelta(days=1))
        res.check("следующий рабочий день по часам клиники — среда", nxt.isoformat(), "2026-10-07")

        def add(name: str, phone: str, d, t: str, doc: str = "d2") -> int:
            c.post_json("/api/schedule/appointments", {"date": d.isoformat(), "time": t,
                                                      "doctor": doc, "service": "consult",
                                                      "name": name, "phone": phone})
            return _pid(c, phone)

        # сегодня, 09:00 (уже прошло): долг 300 после финала 500 и оплаты 200
        pa = add("Datornic Azi", "069800001", today, "09:00")
        r = c.post_json(f"/api/patients/{pa}/plan", {"procedure": "Coroană", "tooth": "11",
                                                    "price": "500"})
        iid = json.loads(r.body)["data"]["plan"]["items"][0]["id"]
        c.post_json(f"/api/patients/{pa}/plan/{iid}/status", {"to": "in_lucru"})
        c.post_json(f"/api/patients/{pa}/plan/{iid}/status", {"to": "finalizat"})
        c.post_json(f"/api/patients/{pa}/payments", {"amount": "200", "method": "numerar"})
        # план без записи вперёд (визит только сегодняшний, прошедший)
        pb = add("Plan Fara", "069800002", today, "09:30", "d3")
        c.post_json(f"/api/patients/{pb}/plan", {"procedure": "Implant", "tooth": "36",
                                                "price": "9000"})
        # план И будущая запись — в список не попадает
        pc = add("Plan Cu", "069800003", nxt + timedelta(days=1), "11:00", "d3")
        c.post_json(f"/api/patients/{pc}/plan", {"procedure": "Obturație", "tooth": "26",
                                                "price": "700"})
        # завтра: двое на подтверждение
        pd = add("Suna Unu", "069800004", nxt, "10:00")
        pe = add("Suna Doi", "069800005", nxt, "11:00", "d3")

        d = _desk(c)
        cf = d["confirm"]
        res.check("De confirmat: завтрашние, по времени, никому не звонили",
                  (cf["day"], cf["date"], [x["name"] for x in cf["items"]], cf["n"], cf["n_left"],
                   cf["items"][0]["phone"], cf["items"][0]["call"]),
                  ("mâine", nxt.isoformat(), ["Suna Unu", "Suna Doi"], 2, 2, "069800004", ""))
        aid = cf["items"][0]["id"]
        pe_id = next(x["id"] for x in cf["items"] if x["pid"] == pe)
        res.check("Plan fără programare: только пациент без будущей записи, сумма",
                  ([x["name"] for x in d["unscheduled"]["items"]], d["unscheduled"]["n"],
                   d["unscheduled"]["sum_s"], d["unscheduled"]["items"][0]["n"]),
                  (["Plan Fara"], 1, "9 000", 1))
        res.ok("должник с финалом в активный план не попал",
               pa not in [x["pid"] for x in d["unscheduled"]["items"]], "финал считается планом")
        col = d["collect"]
        res.check("De încasat azi: сегодняшний пациент с долгом, касса дня по способам",
                  ([(x["name"], x["debt_s"], x["time"]) for x in col["items"]], col["sum_s"],
                   col["cash"]["total_s"], col["cash"]["parts"], col["casa_href"]),
                  ([("Datornic Azi", "300", "09:00")], "300", "200",
                   [{"method": "numerar", "sum_s": "200"}], "/admin/casa?d=2026-10-06"))
        res.ok("Primul loc liber: по каждому активному врачу, окно найдено, сегодняшние сверху",
               len(d["free"]) >= 3 and all(x["when"] and x["href"] for x in d["free"])
               and d["free"][0]["today"] and d["free"][0]["when"].startswith("azi "),
               f"{d['free']}")

        # ---- звонок-подтверждение — командой, как статус ----
        r = c.post_json(f"/api/schedule/desk/call/{aid}?screen=panel", {"result": "ok"})
        res.check("отметка «confirmat» — 200 без состояния", (r.status, "data" in _j(r)), (200, False))
        cf = _desk(c)["confirm"]
        done = next(x for x in cf["items"] if x["id"] == aid)
        res.check("в конверте: отмеченный ушёл вниз, call/автор/время, осталось обзвонить одного",
                  ([x["name"] for x in cf["items"]], done["call"], done["call_by"],
                   len(done["call_at"]), cf["n_left"], cf["n_ok"]),
                  (["Suna Doi", "Suna Unu"], "ok", "Director", 5, 1, 1))
        res.ok("в летописи пациента — строка о звонке",
               any("Confirmare telefonică" in a["text"] and "confirmat" in a["text"]
                   for a in _j(c.get(f"/api/patients/{pd}/activity"))["data"]["items"]),
               "звонок не записан")
        c.post_json(f"/api/schedule/desk/call/{aid}?screen=panel", {"result": "noanswer"})
        cf = _desk(c)["confirm"]
        res.check("«nu răspunde» — своя отметка, в счёт «осталось» не входит",
                  (next(x for x in cf["items"] if x["id"] == aid)["call"], cf["n_left"]),
                  ("noanswer", 1))
        c.post_json(f"/api/schedule/desk/call/{aid}?screen=panel", {"result": ""})
        cf = _desk(c)["confirm"]
        res.check("пустой результат снимает отметку",
                  (next(x for x in cf["items"] if x["id"] == aid)["call"], cf["n_left"]), ("", 2))
        res.check("чужой результат — 422",
                  c.post_json(f"/api/schedule/desk/call/{aid}", {"result": "maybe"}).status, 422)
        r = c.post_json("/api/schedule/desk/call/999999", {"result": "ok"})
        res.check("визита нет — 409 mv_gone", (r.status, _j(r)["code"]), (409, "mv_gone"))
        res.check("без входа — 401", Client(s.url).post_json(
            f"/api/schedule/desk/call/{aid}", {"result": "ok"}).status, 401)
        res.ok("pe отмечен не был", next(x for x in cf["items"] if x["pid"] == pe)["call"] == "",
               "отметка уехала не тому")

        # ---- «De confirmat azi» (12.10, слово Олега: «вчера не сделал — хочу сегодня») ----
        pz = add("Azi Nesunat", "069800006", today, "14:00")
        py = add("Azi Ieri", "069800007", today, "15:00", "d3")
        ct = _desk(c)["confirm_today"]
        res.check("De confirmat azi: сегодняшние programată с пациентом, по времени (пришедший и прошлый — тоже, пока статус confirmed)",
                  (ct["day"], ct["date"], [x["name"] for x in ct["items"]], ct["n_left"]),
                  ("azi", today.isoformat(), ["Datornic Azi", "Plan Fara", "Azi Nesunat", "Azi Ieri"], 4))
        a_y = next(x for x in ct["items"] if x["pid"] == py)["id"]
        c.post_json(f"/api/schedule/desk/call/{a_y}?screen=panel", {"result": "ok"})
        ct = _desk(c)["confirm_today"]
        res.check("отметка сегодня строку не убирает — ход обзвона виден, «осталось» меньше",
                  (next(x for x in ct["items"] if x["id"] == a_y)["call"], ct["n_left"], ct["n_ok"]), ("ok", 3, 1))
        con = sqlite3.connect(s.dir / "dental.db")
        con.execute("UPDATE appt_calls SET at = ? WHERE appointment_id = ?", ("2026-10-05T15:00:00+00:00", a_y))
        con.commit()
        con.close()
        ct = _desk(c)["confirm_today"]
        res.ok("подтверждённый ВЧЕРА (из списка на завтра) в «azi» не показывается — уже сделан",
               a_y not in [x["id"] for x in ct["items"]] and ct["n"] == 3, f"{[x['name'] for x in ct['items']]}")
        a_z = next(x for x in ct["items"] if x["pid"] == pz)["id"]
        c.post_json(f"/api/schedule/appointments/{a_z}/status?screen=panel", {"to": "waiting"})
        res.ok("пришедший уходит из «azi» сам — его статус уже не confirmed",
               a_z not in [x["id"] for x in _desk(c)["confirm_today"]["items"]], "остался в списке")

        # ---- отметка из карточки визита (12.10): поля call/callable у блока и карточки дня ----
        live = _j(c.get("/api/schedule/live"))["data"]
        blk = {b["id"]: b for col in live["canvas"]["columns"] for b in col["blocks"] if b.get("kind") == "appt"}
        res.check("блок канвы: отметка и «можно ли звонить» — сегодня programată да, пришедший нет",
                  ((blk[a_y]["call"], blk[a_y]["callable"]), (blk[a_z]["call"], blk[a_z]["callable"])),
                  (("ok", True), ("", False)))
        yday = (today - timedelta(days=1)).isoformat()
        add("Ieri Programat", "069800008", today - timedelta(days=1), "12:00")
        day_old = _j(c.get(f"/api/schedule/day?date={yday}"))["data"]
        old_card = next(v for v in day_old["cards"].values() if v["name"] == "Ieri Programat")
        res.check("вчерашняя запись — отметку не ставят (callable false), сервер решает, не браузер",
                  (old_card["status"], old_card["callable"]), ("confirmed", False))
        day_tom = _j(c.get(f"/api/schedule/day?date={nxt.isoformat()}"))["data"]
        res.ok("завтрашняя programată в карточке дня — callable", all(v["callable"] for v in day_tom["cards"].values()
               if v["status"] == "confirmed"), f"{day_tom['cards']}")
        r = c.post_json(f"/api/schedule/desk/call/{pe_id}?date={nxt.isoformat()}", {"result": "noanswer"})
        j = _j(r)
        res.ok("дню журнала отметка отвечает СВЕЖИМ днём (как смена статуса), в карточке — отметка",
               r.status == 200 and "data" in j and any(v["call"] == "noanswer" for v in j["data"]["cards"].values()),
               f"{r.status} {list(j)}")

    # ---- деньги — только тому, кому положены (PERM_MONEY) ----
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "3333"})
        res.ok("директор видит кассу и долги", isinstance(_desk(boss)["collect"], dict), "collect None")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        d = _desk(ana)
        res.check("регистратура: collect = null, остальные списки есть",
                  (d["collect"], sorted(d)), (None, ["collect", "confirm", "confirm_today", "free", "recall", "unscheduled"]))
