"""Аналитика директора (C15): модель раздела и её JSON.

Цифры СЧИТАЮТСЯ ОДИН РАЗ — в `stats.model`; React-экран рисует `board` и
списки модели. Старая страница и поля, которые читала только она (плитки,
график, кольцо источников, денежные карточки), сняты 12.10, поэтому карточки
сверяются не со старой страницей, а с засеянными данными: цифры выглядят
правдоподобно всегда, и расхождение иначе не увидеть.

⚠️ «Сегодня» берётся у клиники (`harness.clinic_today`), а не у раннера: движок
считает день по Кишинёву, CI — по UTC, и между 21:00 и 24:00 UTC даты разные.
"""
import json
from datetime import date, datetime, timedelta

from harness import TZ, Client, Clock, Result, Server, add_appt, appt_id, clinic_today



def _j(r) -> dict:
    return json.loads(r.body)


def _seed(c: Client) -> str:
    """Две записи на сегодня: разным врачам, чтобы в модели было что делить."""
    d = clinic_today().isoformat()
    c.post_json("/api/schedule/appointments", {"date": d, "time": "09:00", "doctor": "d2",
                                              "service": "consult", "name": "Stat API Unu",
                                              "phone": "069000021"})
    c.post_json("/api/schedule/appointments", {"date": d, "time": "11:00", "doctor": "d3",
                                              "service": "consult", "name": "Stat API Doi",
                                              "phone": "069000022"})
    return d


def suite_stats(res: Result) -> None:
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/stats").status, 401)
        c = Client(s.url).login()
        day = _seed(c)

        d = _j(c.get("/api/stats"))["data"]
        res.check("по умолчанию — семь дней", d["period"]["days"], 7)
        res.check("и они кончаются сегодня", d["period"]["to"], day)
        k = {x["key"]: x for x in d["board"]["kpis"]}
        res.check("прошлый период назван по имени",
                  k["programari"]["trend"]["label"], "față de săptămâna trecută")
        res.ok("выгрузка Excel — на тот же период",
               d["export_url"].endswith(f"from={d['period']['from']}&to={day}"),
               d["export_url"])
        # «Anul trecut» — только январь–март; его границы стережёт suite_presets
        want = ["azi", "d7", "luna", "luna_trecuta", "d30", "anul"]
        if clinic_today().month <= 3:
            want.append("anul_trecut")
        res.check("готовые периоды: сегодня, 7, месяц, прошлый месяц, 30, год",
                  [p["key"] for p in d["presets"]], want)

        # Бот удалён 03.11.2026: доли «prin bot» в разборе нет.
        res.ok("без бота доли бота в разборе записей нет",
               "prin bot" not in k["programari"]["sub"], k["programari"]["sub"])
        res.check("записи посчитаны", k["programari"]["value"], 2)
        res.ok("у карточки записей свой ряд по дням, длиной в период",
               len(k["programari"]["series"]) == 7 and sum(k["programari"]["series"]) == 2,
               f"{k['programari']['series']}")

        # ⚠️ Прошлая неделя пуста: процентов от нуля не бывает, и тренд обязан
        # сказать это словом, а не «+∞%».
        tr = k["programari"]["trend"]
        res.check("сравнение с пустым периодом — штуками", tr["value"], "+2")
        res.check("и вслух сказано, что тогда было ноль", tr["note"], " (atunci 0)")
        res.check("стрелки у такого сравнения нет", tr["icon"], "")
        res.check("неизменное — пустое направление, а не ноль процентов",
                  k["incasari"]["trend"]["dir"], "")
        m = d["board"]["money"]
        res.ok("потери названы деньгами", m["loss"].startswith("cca "), m["loss"])
        res.check("и ведут на лист кассы за СЕГОДНЯ", m["link"]["href"], "/admin/casa")

        res.ok("врачи отсортированы по загрузке",
               [x["pct"] for x in d["doctors"]] == sorted(
                   (x["pct"] for x in d["doctors"]), reverse=True),
               f"{[x['pct'] for x in d['doctors']]}")
        res.ok("услуга названа и посчитана",
               any(x["cnt"] == 2 for x in d["services"]), f"{d['services']}")
        res.ok("лента событий ведёт на фиши",
               all(x["patient_id"] is None or isinstance(x["patient_id"], int)
                   for x in d["activity"]) and d["activity"], f"{d['activity'][:2]}")

        # поля старой страницы сняты 12.10 вместе с ней — в конверте их нет
        res.ok("полей старой страницы в конверте нет",
               not {"tiles", "chart", "sources", "occupancy", "money", "compare"} & set(d),
               f"{sorted(d)}")

        # ⛔ Негодный период — ОТКАЗ, а не молча другой период. `<input
        # type=date>` отдаёт и «0012-09-15»: промах по сегменту года выглядит
        # законной ISO-датой, а период из неё выходит в 735 000 дней.
        r = c.get("/api/stats?from=0012-09-15&to=" + day)
        res.check("год мимо — 422", r.status, 422)
        res.check("и назван код", _j(r)["code"], "bad_period")
        res.check("и названо поле", _j(r)["field"], "from")
        res.check("период длиннее года — тоже отказ",
                  c.get(f"/api/stats?from=2024-01-01&to={day}").status, 422)
        # перевёрнутый период разворачивается, а не отвергается
        r = c.get(f"/api/stats?from={day}&to={day}")
        res.check("день — период в один день", _j(r)["data"]["period"]["days"], 1)
        res.check("и сравнивается со вчера", _j(r)["data"]["board"]["prev_name"],
                  "ziua precedentă")


def suite_board(res: Result) -> None:
    """Раскладка экрана B8 (27.09): карточки, график, деньги. Цифра карточки,
    разошедшаяся с данными, выглядела бы правдоподобно — поэтому она сверяется
    с засеянным: две записи, два платежа (1 500 картой, 500 наличными)."""
    with Server() as s:
        c = Client(s.url).login()
        _seed(c)
        # платежи сегодня — чтобы доли способов и ряд денег было с чем сверить
        rows = _j(c.get("/api/patients?q=Stat%20API%20Unu"))["data"]["rows"]
        pid = rows[0]["id"]
        c.post_json(f"/api/patients/{pid}/payments", {"amount": "1500", "method": "card",
                                                     "note": ""})
        c.post_json(f"/api/patients/{pid}/payments", {"amount": "500", "method": "numerar",
                                                     "note": ""})
        d = _j(c.get("/api/stats"))["data"]
        b = d["board"]
        k = {x["key"]: x for x in b["kpis"]}
        res.check("четыре карточки в порядке чтения директора",
                  [x["key"] for x in b["kpis"]],
                  ["incasari", "programari", "prezenta", "ocupare"])
        res.check("прошлый период назван по имени, без «față de»",
                  b["prev_name"], "săptămâna trecută")
        res.check("деньги карточки = записанные платежи", k["incasari"]["value"], 2000)
        res.check("и строкой — та же", k["incasari"]["text"], "2 000 MDL")
        res.check("записи карточки = засеянные", k["programari"]["value"], 2)
        # ни одного закрытого визита — процента нет вовсе, а не «0%»
        res.check("явка без закрытых визитов — прочерк, а не ноль",
                  (k["prezenta"]["value"], k["prezenta"]["text"]), (None, "—"))
        # 2 консультации × 60′ из 3 активных врачей × 840′ × 7 рабочих дней
        res.ok("загрузка — минуты записей из рабочих минут активных врачей",
               0 < k["ocupare"]["value"] < 5, k["ocupare"])
        # прошлая неделя пуста: процентов от нуля не бывает
        res.check("рост от нуля — «nou», а не «+∞%»", k["programari"]["badge"]["text"], "nou")
        res.ok("доли сравниваются в процентных пунктах",
               k["ocupare"]["badge"]["text"].endswith("p.p."), k["ocupare"]["badge"])
        res.check("явке не с чем сравнить — метки нет", k["prezenta"]["badge"]["text"], "")
        res.ok("минус — дефисом, а не U+2212 (его нет во вшитом Inter)",
               all("−" not in x["badge"]["text"] for x in b["kpis"]), b["kpis"])
        s_ = b["series"]
        res.check("неделя — семь корзин по дням",
                  (s_["bucket"], len(s_["labels"]), len(s_["appts"]), len(s_["hints"])),
                  ("day", 7, 7, 7))
        res.check("ряд записей сходится с карточкой", sum(s_["appts"]), k["programari"]["value"])
        res.check("ряд денег сходится с карточкой", sum(s_["income"]), k["incasari"]["value"])
        res.check("и у каждого дня есть строка денег", len(s_["income_text"]), 7)
        res.check("способы оплаты — три", [p["key"] for p in b["parts"]],
                  ["numerar", "card", "transfer"])
        res.check("и в сумме — вся касса", sum(p["value"] for p in b["parts"]),
                  k["incasari"]["value"])
        res.check("доля карты", next(p["pct"] for p in b["parts"] if p["key"] == "card"), 75)
        res.ok("у врача аватар считает сервер",
               d["doctors"] and all(x["initials"] and x["color"] and "id" in x
                                    for x in d["doctors"]), d["doctors"][:1])
        res.ok("у услуги сумма есть и числом",
               d["services"] and all(isinstance(x["val_n"], int) for x in d["services"]),
               d["services"][:1])
        res.check("лист кассы — за сегодня", b["money"]["link"]["href"], "/admin/casa")
        res.ok("без бота доли бота в разборе нет",
               "prin bot" not in k["programari"]["sub"], k["programari"]["sub"])
        # длинный период — по неделям, и ряд всё равно сходится
        d2 = clinic_today()
        d1 = d2 - timedelta(days=59)
        b2 = _j(c.get(f"/api/stats?from={d1.isoformat()}&to={d2.isoformat()}"))["data"]["board"]
        res.check("60 дней — по неделям", b2["series"]["bucket"], "week")
        res.ok("недель — от восьми до десяти", 8 <= len(b2["series"]["labels"]) <= 10,
               b2["series"]["labels"])
        res.check("и ряд по неделям сходится с карточкой", sum(b2["series"]["appts"]),
                  next(x["value"] for x in b2["kpis"] if x["key"] == "programari"))


def suite_presence(res: Result) -> None:
    """Явка — только по ЗАКРЫТЫМ визитам (S1, разведка 16.11): делитель —
    finalizată + nu a venit. Прошлый визит без отметки — не неявка: раньше он
    шёл в делитель, и при нуле неявок карточка показывала «0%» и «-100 p.p.».
    Будущие записи в явку не идут никак. Часы поддельные: «уже началось» и
    «ещё впереди» зависят от часа прогона."""
    # среда 11.11.2026, 15:00 по Кишинёву
    with Clock(datetime(2026, 11, 11, 15, 0, tzinfo=TZ)), Server() as s:
        c = Client(s.url).login()
        mon, today = "2026-11-09", "2026-11-11"
        for t, name, ph in (("10:00", "Prez Gata", "069000031"),
                            ("11:00", "Prez Lipsa", "069000032"),
                            ("12:00", "Prez Uitat", "069000033")):
            r = add_appt(c, mon, t, name, ph)
            res.ok(f"прошлая запись {t} заведена", r.msg in ("ok", "ok_past"), r.msg)
        add_appt(c, today, "09:00", "Prez Azi", "069000034")
        add_appt(c, today, "17:00", "Prez Viitor", "069000035")

        def st(a: str = "", b: str = "") -> dict:
            q = f"?from={a}&to={b}" if a else ""
            return json.loads(c.get("/api/stats" + q).body)["data"]

        def prez(d: dict) -> dict:
            return next(x for x in d["board"]["kpis"] if x["key"] == "prezenta")

        # только сегодня: 09:00 началось и не закрыто, 17:00 ещё впереди
        p = prez(st(today, today))
        res.check("незакрытые визиты — не неявка: процента нет, а не «0%»",
                  (p["value"], p["text"]), (None, "—"))
        res.check("незакрытый — один: будущий в счёт не идёт", p["open"]["n"], 1)
        res.check("и назван словами", p["open"]["text"], "1 programare neînchisă")
        res.check("ссылка — в журнал этого дня", p["open"]["href"], f"/admin/all?date={today}")
        res.check("метки сравнения нет", p["badge"]["text"], "")

        for name, to in (("Prez Gata", "done"), ("Prez Lipsa", "noshow")):
            r = c.post_json(f"/api/schedule/appointments/{appt_id(c, mon, name)}/status",
                            {"to": to})
            res.ok(f"исход «{to}» отмечен", r.status == 200, f"{r.status} {r.body[:200]}")
        d = st()
        p = prez(d)
        res.check("делитель — только закрытые: 1 из (1 + 1 неявка)", p["value"], 50)
        res.check("текстом — тот же процент", p["text"], "50%")
        res.check("незакрытых два: забытый в понедельник и сегодняшний 09:00",
                  p["open"]["text"], "2 programări neînchise")
        res.check("ссылка — на последний день с незакрытыми",
                  p["open"]["href"], f"/admin/all?date={today}")
        res.ok("неявка в разборе — одна", p["sub"].startswith("1 neprezentări"), p["sub"])
        d2 = next(x for x in d["doctors"] if x["id"] == "d2")
        res.check("явка врача — та же формула", d2["pres"], 50)
        res.ok("у врача без закрытых визитов процента нет",
               all(x["pres"] is None for x in d["doctors"] if x["id"] != "d2"), d["doctors"])

        # ⭐ Ровно случай разведки: неявок ноль, есть незакрытые — не «0%»
        # неявку отменяют возвратом в «programată», потом визит закрывают
        lipsa = appt_id(c, mon, "Prez Lipsa")
        for to in ("confirmed", "done"):
            c.post_json(f"/api/schedule/appointments/{lipsa}/status", {"to": to})
        p = prez(st())
        res.check("ноль неявок при незакрытых визитах — 100%, а не 0%",
                  (p["value"], p["sub"].split(" ")[0]), (100, "0"))
        res.check("незакрытые по-прежнему названы", p["open"]["n"], 2)

        # всё закрыто — строки о незакрытых нет
        for name, day in (("Prez Uitat", mon), ("Prez Azi", today)):
            c.post_json(f"/api/schedule/appointments/{appt_id(c, day, name)}/status",
                        {"to": "done"})
        res.check("всё закрыто — незакрытых нет", prez(st())["open"], None)


def suite_presets(res: Result) -> None:
    """Готовые периоды (S3) — по дню КЛИНИКИ, не по UTC. В первые часы
    1 января по Кишинёву в UTC ещё 31 декабря: сервер, считающий по UTC,
    показал бы «Anul acesta» прошлым годом. «Anul trecut» — только январь–март."""
    def presets(c: Client) -> dict:
        d = json.loads(c.get("/api/stats").body)["data"]
        return {p["key"]: (p["from"], p["to"]) for p in d["presets"]}

    with Clock(datetime(2027, 1, 1, 0, 30, tzinfo=TZ)) as clock, Server() as s:
        c = Client(s.url).login()
        p = presets(c)
        res.check("1 января 00:30: год — уже новый", p["anul"], ("2027-01-01", "2027-01-01"))
        res.check("прошлый месяц — декабрь целиком", p["luna_trecuta"],
                  ("2026-12-01", "2026-12-31"))
        res.check("в январе есть прошлый год целиком", p.get("anul_trecut"),
                  ("2026-01-01", "2026-12-31"))
        r = c.get("/api/stats?from=2026-01-01&to=2026-12-31")
        res.check("и сервер этот период принимает", r.status, 200)

        clock.set(datetime(2026, 12, 31, 23, 30, tzinfo=TZ))
        p = presets(c)
        res.check("31 декабря 23:30: год ещё этот", p["anul"], ("2026-01-01", "2026-12-31"))
        res.ok("в декабре прошлого года нет", "anul_trecut" not in p, p)
        res.check("прошлый месяц — ноябрь", p["luna_trecuta"], ("2026-11-01", "2026-11-30"))

        clock.set(datetime(2027, 3, 31, 23, 50, tzinfo=TZ))
        res.ok("31 марта прошлый год ещё есть", "anul_trecut" in presets(c), presets(c))
        clock.set(datetime(2027, 4, 1, 0, 10, tzinfo=TZ))
        p = presets(c)
        res.ok("1 апреля 00:10 — уже нет", "anul_trecut" not in p, p)
        res.check("прошлый месяц — март", p["luna_trecuta"], ("2027-03-01", "2027-03-31"))
        res.check("порядок кнопок", list(p),
                  ["azi", "d7", "luna", "luna_trecuta", "d30", "anul"])
        # февраль високосного года — последний день месяца, а не 28-е
        clock.set(datetime(2028, 3, 5, 12, 0, tzinfo=TZ))
        res.check("прошлый месяц — февраль високосного года",
                  presets(c)["luna_trecuta"], ("2028-02-01", "2028-02-29"))
        res.ok("сегодня берётся у клиники", date(2028, 3, 5).isoformat()
               == presets(c)["azi"][0], presets(c)["azi"])


def suite_switch(res: Result) -> None:
    """Страница — React при любом `ui.react` (старая снята 12.10); право PERM_MONEY."""
    s = Server(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "3333"})
        boss.post_json("/api/settings/users", {"uid": "ion", "name": "Ion M", "role": "medic", "pin": "4444"})
        page = boss.get("/admin/stats").body
        res.ok("узел React", 'data-screen="stats"' in page, "узла нет")
        res.ok("период уезжает параметрами узла", "data-params=" in page
               and "from" in page, "параметров нет")
        res.ok("старой разметки нет", "class='tiles'" not in page, "две разметки")

        # ⛔ Деньги закрыты не только в меню: адрес набирается руками.
        for who, pin in (("регистратуре", "3333"), ("врачу", "4444")):
            cl = Client(s.url)
            cl.post("/admin/login", password=pin, next="/admin")
            res.check(f"{who} JSON закрыт", cl.get("/api/stats").status, 403)
            r = cl.get("/admin/stats")
            res.ok(f"{who} закрыта и страница",
                   r.status == 303 and r.msg == "no_access", f"{r!r}")
