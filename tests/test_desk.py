"""«La recepție» (01.10): рабочие списки регистратуры в правой колонке
главной — тем же конвертом живого канала, что и канва.

Что стережётся: списки считаются от СЕГОДНЯ клиники (часы прогона
подменены: вторник, 10:00), звонок-подтверждение — командой с отметкой и
строкой в летописи, деньги — только тому, кому положены (PERM_MONEY).
"""
import json
import re
from datetime import datetime, timedelta

from harness import FIXTURES, TZ, Client, Clock, Result, Server
from test_api import NO_KEY

_DOW = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return int(c.get(f"/admin/search?q={phone}").body.split(
        "<tr id='plr", 1)[1].split("'", 1)[0])


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
            c.post("/admin/add", adate=d.isoformat(), atime=t, adoctor=doc,
                   aservice="consult", aname=name, aphone=phone, back="/admin/all")
            return _pid(c, phone)

        # сегодня, 09:00 (уже прошло): долг 300 после финала 500 и оплаты 200
        pa = add("Datornic Azi", "069800001", today, "09:00")
        c.post(f"/admin/patient/{pa}/plan", procedure="Coroană", tooth="11", price="500")
        iid = re.findall(r"/plan/(\d+)/status", c.get(f"/admin/patient/{pa}").body)[-1]
        c.post(f"/admin/patient/{pa}/plan/{iid}/status", to="in_lucru")
        c.post(f"/admin/patient/{pa}/plan/{iid}/status", to="finalizat")
        c.post(f"/admin/patient/{pa}/pay", amount="200", method="numerar")
        # план без записи вперёд (визит только сегодняшний, прошедший)
        pb = add("Plan Fara", "069800002", today, "09:30", "d3")
        c.post(f"/admin/patient/{pb}/plan", procedure="Implant", tooth="36", price="9000")
        # план И будущая запись — в список не попадает
        pc = add("Plan Cu", "069800003", nxt + timedelta(days=1), "11:00", "d3")
        c.post(f"/admin/patient/{pc}/plan", procedure="Obturație", tooth="26", price="700")
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

    # ---- деньги — только тому, кому положены (PERM_MONEY) ----
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        res.ok("директор видит кассу и долги", isinstance(_desk(boss)["collect"], dict), "collect None")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        d = _desk(ana)
        res.check("регистратура: collect = null, остальные списки есть",
                  (d["collect"], sorted(d)), (None, ["collect", "confirm", "free", "unscheduled"]))
