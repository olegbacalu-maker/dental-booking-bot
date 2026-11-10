"""«Registre» — санитарные регистры 257/e, 502/e, 501/e (10.11.2026, san-registers).

Решения Олега 10.11 (вариант B): пишут все вошедшие, подпись строки — вошедший
и время программы; исправление — новой строкой с причиной, старая остаётся
(зачёркнутой на листе); удаляет только директор, мягко; «a supervizat» —
другой человек своим входом; ресурс лампы считает программа.
Проверяется через сервер тем же путём, что у клиники: каталог — маршрутом
настроек, записи — API раздела, лист и Excel — адресами печати. Часы —
подменные (`harness.Clock`): время подписи, длительность сеанса лампы и план
уборки считаются от «сейчас» программы.
"""
import io
import json
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta

from harness import BOT, Client, Clock, Result, Server, TZ, shell_model
from test_api import NO_KEY

sys.path.insert(0, str(BOT))
from app import db as appdb  # noqa: E402

API = "/api/registre"
CAT = "/api/settings/registre"
# вторник 10.11.2026, 09:00 — рабочий день
AT = datetime(2026, 11, 10, 9, 0, tzinfo=TZ)


def _j(r) -> dict:
    return json.loads(r.body)


def _model(c: Client, month: str = "") -> dict:
    r = c.get(API + (f"?month={month}" if month else ""))
    if r.status != 200:
        raise AssertionError(f"регистры не отданы: {r.status} {r.body[:200]}")
    return _j(r)["data"]


def _sql(s: Server, sql: str, *args) -> list:
    con = sqlite3.connect(str(s.dir / "dental.db"))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _team(s: Server) -> tuple[Client, Client, Client]:
    """Директор (PIN 1111), регистратура «Ana Rusu» (4444), врач (2222)."""
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


def _catalog(boss: Client) -> dict:
    """Каталог тем же маршрутом, каким его заводит директор."""
    items = [
        {"kind": "ster", "name": "Melag 23 B+", "nr": "23-11845", "room": "Sala de sterilizare",
         "data": {"type": "abur", "programs": [{"label": "Universal 134 °C", "temp": "134", "pressure": "2,1", "min": 5},
                                               {"label": "Delicat 121 °C", "temp": "121", "pressure": "1,1", "min": 20}]}},
        {"kind": "ster", "name": "GP-40", "nr": "0412",
         "data": {"type": "aer", "programs": [{"label": "Aer 180 °C", "temp": "180", "pressure": "", "min": 60}]}},
        {"kind": "lamp", "name": "OBN-150", "nr": "2", "room": "Cabinet 1",
         "data": {"m3": 45, "hours": 100, "base": 60, "since": "2026-01-01", "screened": False}},
        {"kind": "lamp", "name": "Dezar-3", "nr": "7", "room": "Cabinet 2",
         "data": {"m3": 42, "hours": 9000, "base": 0, "since": "2026-01-01", "screened": True}},
        {"kind": "room", "name": "Cabinet 1", "data": {"every": 7}},
        {"kind": "solution", "name": "Septodor Forte 0,2 % · 60 min"},
        {"kind": "article", "name": "Instrumentar stomatologic"},
        {"kind": "pack", "name": "Pungă"},
        {"kind": "norms", "data": {"text": "HG nr. 4/2026"}},
    ]
    for it in items:
        r = boss.post_json("/api/settings/registre/item", it)
        if r.msg != "ok_san_item":
            raise AssertionError(f"каталог: {it['kind']} {r.status} {r.body[:200]}")
    return _j(boss.get(CAT))["data"]["items"]


def suite_schema(res: Result) -> None:
    """Шаг 9: четыре таблицы без единой ссылки на пациентов; версия схемы 9+."""
    res.ok("версия схемы не ниже 9", appdb.SCHEMA_VERSION >= 9, str(appdb.SCHEMA_VERSION))
    res.ok("шаг 9 — это SAN_DDL", appdb.MIGRATIONS.get(9) is appdb.SAN_DDL, "")
    ddl = "\n".join(appdb.SAN_DDL)
    res.ok("san_* не ссылаются на patients (закон 195 их не касается)", "patients" not in ddl, ddl[:200])
    with Server() as s:
        names = {r[0] for r in _sql(s, "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'san_%'")}
        res.check("свежая база получила таблицы", names, {"san_equipment", "san_cycles", "san_cleanings", "san_uv"})


def suite_flow(res: Result) -> None:
    """Автоклав, уборка, лампа: подпись сервера, однократное закрытие, исправление, удаление."""
    with Clock(AT) as clock, Server(env=NO_KEY) as s:
        boss, ana, med = _team(s)
        items = _catalog(boss)
        melag, gp = items["ster"][0]["id"], items["ster"][1]["id"]
        obn, dezar = items["lamp"][0]["id"], items["lamp"][1]["id"]
        room = items["room"][0]["id"]
        res.ok("каталог: две программы у Melag", len(items["ster"][0]["data"]["programs"]) == 2, repr(items["ster"][0]))
        res.check("каталог без программ — отказ полем",
                  (lambda r: (r.msg, _j(r).get("field")))(boss.post_json("/api/settings/registre/item", {"kind": "ster", "name": "X", "data": {"type": "abur"}})),
                  ("bad_san", "programs"))

        # --- 257/e: цикл ---
        arts = [{"name": "Instrumentar stomatologic", "qty": 12, "pack": "Pungă"}]
        r = ana.post_json("/api/registre/257", {"ster_id": melag, "program": 0, "arts": arts,
                                         "actor": "Подделка", "started_at": "2020-01-01"})
        res.check("старт цикла — ok", r.msg, "ok_san_start")
        res.check("второй старт на том же автоклаве — san_busy", ana.post_json("/api/registre/257", {"ster_id": melag, "arts": arts}).msg, "san_busy")
        res.check("без предметов — bad_san/arts", (lambda r: (r.msg, _j(r).get("field")))(ana.post_json("/api/registre/257", {"ster_id": gp, "arts": []})),
                  ("bad_san", "arts"))
        m = _model(ana)
        run = m["sters"][0]["running"]
        res.check("подпись и время — сервера, не клиента", (run["actor"], run["start"], run["date"], run["temp"], run["pressure"]),
                  ("Ana Rusu", "09:00", "10.11.2026", "134", "2,1"))
        res.ok("в ленте «Azi» — идущий цикл", any(x["reg"] == "257" and x["open"] for x in m["feed"]), repr(m["feed"]))
        cid = run["id"]
        clock.set(AT + timedelta(minutes=45))
        res.check("исправить идущий — san_open", boss.post_json(f"{API}/257/{cid}/fix", {"why": "x"}).msg, "san_open")
        r = med.post_json(f"{API}/257/{cid}/finish", {"chem": "ok", "term": "ok", "bio": "wait"})
        res.check("врач закрывает цикл — ok (пишут все вошедшие)", r.msg, "ok_san_finish")
        res.check("повтор закрытия — san_closed", med.post_json(f"{API}/257/{cid}/finish", {"chem": "fail"}).msg, "san_closed")
        row = _model(ana)["rows"]["257"][0]
        res.check("конец, тесты, кто закрыл", (row["end"], row["chem"], row["bio"], row["end_actor"], row["actor"]),
                  ("09:45", "ok", "wait", "Dr. Activ Trei", "Ana Rusu"))
        res.check("итог биотеста — ok", ana.post_json(f"{API}/257/{cid}/bio", {"bio": "ok"}).msg, "ok_san_bio")
        res.check("итог биотеста второй раз — san_closed", ana.post_json(f"{API}/257/{cid}/bio", {"bio": "fail"}).msg, "san_closed")
        # исправление: новой строкой, причина обязательна, старая — fixed_by
        res.check("исправление без причины — san_why", ana.post_json(f"{API}/257/{cid}/fix", {"why": "  "}).msg, "san_why")
        r = ana.post_json(f"{API}/257/{cid}/fix", {"why": "12 pungi, nu 10", "arts": [{"name": "Instrumentar stomatologic", "qty": 10, "pack": "Pungă"}]})
        res.check("исправление — ok", r.msg, "ok_san_fix")
        rows = _model(ana)["rows"]["257"]
        res.check("две строки: старая исправлена новой, новая ссылается и несёт причину",
                  (len(rows), rows[0]["fixed_by"], rows[1]["fixes"], rows[1]["why"], rows[1]["arts"][0]["qty"], rows[0]["arts"][0]["qty"]),
                  (2, rows[1]["id"], cid, "12 pungi, nu 10", 10, 12))
        res.check("биотест переехал в исправление", (rows[1]["bio"], rows[1]["bio_actor"]), ("ok", "Ana Rusu"))
        res.check("повторное исправление старой — san_fixed", ana.post_json(f"{API}/257/{cid}/fix", {"why": "x"}).msg, "san_fixed")
        res.check("в базе старая строка не тронута", _sql(s, "SELECT arts FROM san_cycles WHERE id=?", cid)[0][0],
                  json.dumps(arts, ensure_ascii=False))

        # --- 502/e: уборка ---
        res.check("уборка — ok", ana.post_json("/api/registre/502", {"room_id": room, "solution": "Septodor Forte 0,2 % · 60 min"}).msg, "ok_san_clean")
        m = _model(ana)
        cl = m["rows"]["502"][0]
        res.check("план — сегодня (не было), сделано сегодня, автор", (cl["plan"], cl["done"], cl["actor"]),
                  ("10.11.2026", "10.11.2026", "Ana Rusu"))
        res.check("следующая — через 7 дней, сегодня не к сроку", (m["rooms"][0]["next"], m["rooms"][0]["due"]), ("17.11.2026", False))
        res.check("ждёт проверки", [w["id"] for w in m["waiting"]], [cl["id"]])
        res.check("сам себя не проверяет — san_self_check", ana.post_json(f"{API}/502/{cl['id']}/sup", {}).msg, "san_self_check")
        res.check("проверяет директор — ok", boss.post_json(f"{API}/502/{cl['id']}/sup", {}).msg, "ok_san_sup")
        res.check("вторая проверка — san_closed", med.post_json(f"{API}/502/{cl['id']}/sup", {}).msg, "san_closed")
        m = _model(ana)
        res.check("проверено директором, ожидающих нет", (m["rows"]["502"][0]["sup_actor"], m["waiting"]), ("Director", []))
        r = ana.post_json(f"{API}/502/{cl['id']}/fix", {"why": "altă soluție", "solution": "Clorantoin 0,1 %"})
        m = _model(ana)
        res.check("исправление уборки снова ждёт проверки (подпись не переезжает)",
                  (r.msg, [w["fixes"] for w in m["waiting"]]), ("ok_san_fix", [cl["id"]]))

        # --- 501/e: лампы ---
        res.check("лампа без экрана при людях — san_uv_people",
                  ana.post_json("/api/registre/501", {"lamp_id": obn, "cond": "prezenta"}).msg, "san_uv_people")
        res.check("включение — ok", ana.post_json("/api/registre/501", {"lamp_id": obn, "cond": "fara"}).msg, "ok_san_uv_on")
        res.check("второе включение — san_uv_on", ana.post_json("/api/registre/501", {"lamp_id": obn, "cond": "fara"}).msg, "san_uv_on")
        uid = _model(ana)["lamps"][0]["on"]["id"]
        clock.set(AT + timedelta(minutes=45 + 90))
        res.check("выключение — ok", med.post_json(f"{API}/501/{uid}/off", {}).msg, "ok_san_uv_off")
        m = _model(ana)
        u = m["rows"]["501"][0]
        res.check("минуты, остаток, кто выключил", (u["minutes"], u["rest"], u["off_actor"], u["cond"]),
                  (90, 39, "Dr. Activ Trei", "fără persoane"))
        res.check("ресурс лампы: 60 база + 1 ч, остаток 39 из 100 — на исходе", (m["lamps"][0]["used"], m["lamps"][0]["rest"], m["lamps"][0]["low"]),
                  (61, 39, True))
        r = ana.post_json(f"{API}/501/{uid}/fix", {"why": "a uitat să oprească", "minutes": 30})
        m = _model(ana)
        res.check("исправление сеанса считает ресурс по исправлению", (r.msg, m["lamps"][0]["used"], m["rows"]["501"][1]["minutes"]),
                  ("ok_san_fix", 60, 30))
        res.check("«Lampă nouă» — ok", boss.post_json(f"{CAT}/lamp/{obn}/new", {}).msg, "ok_san_lamp_new")
        lamp = next(x for x in _j(boss.get(CAT))["data"]["items"]["lamp"] if x["id"] == obn)
        res.check("новая лампа: отсчёт с нуля, дата замены", (lamp["used"], lamp["rest"], lamp["data"]["since"], len(lamp["data"]["changes"])),
                  (0, 100, "2026-11-10", 1))
        res.check("правка лампы формой не стирает историю замен",
                  (boss.post_json("/api/settings/registre/item", {**lamp, "data": {**lamp["data"], "changes": []}}).msg,
                   len(next(x for x in _j(boss.get(CAT))["data"]["items"]["lamp"] if x["id"] == obn)["data"]["changes"])),
                  ("ok_san_item", 1))
        res.check("экранированная при людях — ok", ana.post_json("/api/registre/501", {"lamp_id": dezar, "cond": "prezenta"}).msg, "ok_san_uv_on")

        # --- удаление: только директор, мягко ---
        rid = _model(ana)["rows"]["257"][1]["id"]
        res.check("регистратура удаляет — 403", ana.post_json(f"{API}/257/{rid}/delete", {}).status, 403)
        res.check("врач удаляет — 403", med.post_json(f"{API}/257/{rid}/delete", {}).status, 403)
        res.check("директор удаляет — ok", boss.post_json(f"{API}/257/{rid}/delete", {}).msg, "ok_san_del")
        res.check("строка ушла с экрана, в базе осталась с автором удаления",
                  ([x["id"] for x in _model(ana)["rows"]["257"]], _sql(s, "SELECT deleted_by FROM san_cycles WHERE id=?", rid)[0][0]),
                  ([cid], "Director"))
        res.check("исправленная строка снова «свободна» (исправление удалено)", _model(ana)["rows"]["257"][0]["fixed_by"], None)
        ev = _sql(s, "SELECT text FROM activity WHERE kind='registru'")
        res.ok("летопись клиники: удаление названо", any(f"nr. {rid}" in t[0] for t in ev), repr(ev))
        res.check("удалить ещё раз — 404", boss.post_json(f"{API}/257/{rid}/delete", {}).status, 404)
        res.check("два запроса подряд — то же", _model(ana), _model(ana))
        res.check("без входа — 401", Client(s.url).get(API).status, 401)


def suite_rights(res: Result) -> None:
    """Меню у всех вошедших; каталог и удаление — только директор."""
    with Clock(AT), Server(env=NO_KEY) as s:
        boss, ana, med = _team(s)
        for who, c in (("директор", boss), ("регистратура", ana), ("врач", med)):
            keys = [i["key"] for i in shell_model(c.get("/admin").body)["nav"]["items"]]
            res.ok(f"{who}: пункт «Registre» в меню", "reg" in keys, f"{keys}")
            res.check(f"{who}: страница раздела открывается", c.get("/admin/registre").status, 200)
            res.check(f"{who}: модель отдаётся", c.get(API).status, 200)
        res.check("регистратура: каталог — 403", (ana.get(CAT).status, ana.post_json("/api/settings/registre/item", {"kind": "room", "name": "X"}).status), (403, 403))
        res.check("врач: каталог — 403, страница каталога — отказ", (med.get(CAT).status, med.get("/admin/settings/registre").status in (303, 403)), (403, True))
        res.check("права в модели: директор может удалять, регистратура нет",
                  (_model(boss)["can"]["delete"], _model(ana)["can"]["delete"]), (True, False))
        res.check("без входа: страница уводит на вход", Client(s.url).get("/admin/registre").status, 303)


def suite_print(res: Result) -> None:
    """Лист за месяц колонками бланка и Excel: зачёркнутая строка, удалённой нет."""
    with Clock(AT) as clock, Server(env=NO_KEY) as s:
        boss, ana, _ = _team(s)
        items = _catalog(boss)
        melag, obn, room = items["ster"][0]["id"], items["lamp"][0]["id"], items["room"][0]["id"]
        arts = [{"name": "Instrumentar stomatologic", "qty": 12, "pack": "Pungă"}]
        ids = []
        for i in range(3):
            ana.post_json("/api/registre/257", {"ster_id": melag, "program": 0, "arts": arts})
            cid = _model(ana)["sters"][0]["running"]["id"]
            clock.set(AT + timedelta(minutes=50 * (i + 1)))
            ana.post_json(f"{API}/257/{cid}/finish", {"chem": "fail" if i == 1 else "ok", "term": "ok"})
            ids.append(cid)
        ana.post_json(f"{API}/257/{ids[0]}/fix", {"why": "cantitatea", "arts": [{**arts[0], "qty": 11}]})
        boss.post_json(f"{API}/257/{ids[2]}/delete", {})
        ana.post_json("/api/registre/502", {"room_id": room, "solution": "Septodor"})
        ana.post_json("/api/registre/501", {"lamp_id": obn, "cond": "fara"})
        r = ana.get("/admin/registre/tipar/257?month=2026-11")
        page = r.body
        res.check("лист 257/e — 200", r.status, 200)
        for want in ("Formular nr. 257/e", "828 din 31.10.2011", "CONTROLULUI LUCRULUI".lower(), "Test-control",
                     "Biologic", "Termic", "Chimic", "corectată prin nr.", "corectează nr. %d: cantitatea" % ids[0],
                     "HG nr. 4/2026", "Responsabil de registru", "L.Ș.", "Extras din registrul electronic DentPilot",
                     "<b>incorect</b>", "Perioada: 01.11.2026 – 30.11.2026"):
            res.ok(f"на листе: {want}", want.lower() in page.lower(), "")
        res.ok("номер страницы константой не пишется", "Pagina" not in page, "")
        res.ok("удалённая строка не печатается", f"nr. {ids[2]}" not in page, "")
        res.ok("A4 альбом", "size:A4 landscape" in page, "")
        res.ok("13 номеров колонок", all(f"<th>{i}</th>" in page for i in range(1, 14)), "")
        p502 = ana.get("/admin/registre/tipar/502?month=2026-11")
        t502 = p502.body
        res.ok("лист 502/e: колонки и срок хранения", all(w in t502 for w in ("A supervizat", "Data planificării", "3 ani", "Formular nr. 502/e")), "")
        p501 = ana.get("/admin/registre/tipar/501?month=2026-11")
        t501 = p501.body
        res.ok("лист 501/e: паспорт лампы и «в работе»", all(w in t501 for w in ("Rezerva orelor de lucru", "OBN-150 nr. 2", "în curs", "fără persoane")), "")
        res.check("лист неизвестного регистра — 404", ana.get("/admin/registre/tipar/999").status, 404)
        res.check("лист без входа — на вход", Client(s.url).get("/admin/registre/tipar/257").status, 303)
        x = ana.get("/admin/registre/excel/257?month=2026-11")
        res.check("Excel — 200 и вложение", (x.status, "registru_257e_2026-11-01.xlsx" in x.header("content-disposition")), (200, True))
        # ⚠️ .raw, а не .body: тело декодируется с "replace", и zip ломается
        z = zipfile.ZipFile(io.BytesIO(x.raw))
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        res.ok("Excel: шапка и пометка исправления", "Test" not in sheet and "Sterilizator" in sheet and "corectată prin nr." in sheet, sheet[:300])
        res.ok("Excel: удалённой строки нет", sheet.count("<row ") == 1 + 3, str(sheet.count("<row ")))


def suite_fresh(res: Result) -> None:
    """2.14.1 (канарейка 2.14.0): свежая клиника завела только автоклав — окно
    «Ciclu nou» не тупик. Стартовые предметы и упаковки подставляются ОДИН раз
    по ключу schema_meta; выключенные клиникой второй раз не навязываются;
    своё слово — только в запись, на листе экранировано."""
    with Clock(AT), Server(env=NO_KEY) as s:
        boss, ana, _ = _team(s)
        r = boss.post_json("/api/settings/registre/item", {"kind": "ster", "name": "Dent", "data": {
            "type": "abur", "programs": [{"label": "134 °C", "temp": "134", "pressure": "2,1", "min": 5}]}})
        res.check("свежая клиника: заведён один автоклав", r.msg, "ok_san_item")
        m = _model(ana)
        from app.core import registre as reg  # noqa: E402 — только слова старта
        res.check("стартовые предметы — в каталоге", m["articles"], list(reg.STARTER["article"]))
        res.check("стартовые упаковки — в каталоге", m["packs"], list(reg.STARTER["pack"]))
        res.check("ключи старта записаны", sorted(x[0] for x in _sql(s, "SELECT key FROM schema_meta WHERE key LIKE 'san_starter_%'")),
                  ["san_starter_article", "san_starter_pack"])
        ster = m["sters"][0]["id"]
        r = ana.post_json("/api/registre/257", {"ster_id": ster, "program": 0,
                                                "arts": [{"name": m["articles"][0], "qty": 3, "pack": m["packs"][0]}]})
        res.check("цикл запускается со стартовым предметом", r.msg, "ok_san_start")
        res.check("второй запрос — старт не задваивается", len(_model(ana)["articles"]), len(reg.STARTER["article"]))
        # клиника выключила все стартовые предметы — пустота её выбор, не повод подложить снова
        for it in _j(boss.get(CAT))["data"]["items"]["article"]:
            boss.post_json("/api/settings/registre/item", {**it, "active": False})
        res.check("выключила все — список пуст", _model(ana)["articles"], [])
        res.check("и остаётся пустым (решает ключ, не пустота)", (_model(ana)["articles"],
                  len(_sql(s, "SELECT id FROM san_equipment WHERE kind='article'"))), ([], len(reg.STARTER["article"])))
        # своё слово в окне: только в запись, экранировано, длина обрезана сервером
        cid = _model(ana)["sters"][0]["running"]["id"]
        ana.post_json(f"{API}/257/{cid}/finish", {"chem": "ok", "term": "ok"})
        own = "Spatulă <b>x</b> " + "z" * 300
        r = ana.post_json("/api/registre/257", {"ster_id": ster, "program": 0, "arts": [{"name": own, "qty": 1, "pack": ""}]})
        res.check("своё слово — цикл запускается", r.msg, "ok_san_start")
        row = _model(ana)["rows"]["257"][-1]
        res.check("своё слово обрезано до 120", len(row["arts"][0]["name"]), 120)
        res.check("в каталог своё слово не попало", _model(ana)["articles"], [])
        page = ana.get("/admin/registre/tipar/257?month=2026-11").body
        res.ok("на листе своё слово экранировано", "Spatulă &lt;b&gt;x&lt;/b&gt;" in page and "<b>x</b>" not in page, "")
        res.check("уборка со своим раствором словом",
                  (boss.post_json("/api/settings/registre/item", {"kind": "room", "name": "Cabinet 1", "data": {"every": 7}}).msg,
                   ana.post_json("/api/registre/502", {"room_id": _model(ana)["rooms"][0]["id"], "solution": "Clorhexidină 0,05 %"}).msg),
                  ("ok_san_item", "ok_san_clean"))
    with Clock(AT), Server(env=NO_KEY) as s:
        boss, ana, _ = _team(s)
        # клиника, которая завела свои предметы раньше первого чтения, — без старта
        boss.post_json("/api/settings/registre/item", {"kind": "article", "name": "Freze"})
        res.check("свой список раньше старта — старт не подкладывается", _model(ana)["articles"], ["Freze"])
        res.check("упаковки при этом стартовые (свой вид — свой ключ)", len(_model(ana)["packs"]), 3)
