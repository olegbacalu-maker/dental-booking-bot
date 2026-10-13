"""Список пациентов (Search): `GET /api/patients` — отбор, порядок и страница
считаются в базе (`db.patients_rows`), а не в памяти.

Главное, что стережётся: на засеве с каждой веткой статуса для каждого
отбора и порядка — ТЕ люди в ТОМ порядке с ТЕМИ статусами. До 13.10 правило
жило дважды (Python старой страницы и SQL API), и выдачи сверялись строка в
строку (`suite_parity`); старая страница снята, а её выдача — снятая на
последнем коде, где паритет держался, — записана здесь буквально. Ту же
выборку отдаёт книга `/admin/patients.xlsx` (её держит `test_admin`).
"""
import json
import re
import sqlite3

from harness import Client, Result, Server, new_patient, pid_by_phone
from test_admin import _d
from test_settings_api import NO_KEY, _j


def _seed(c: Client) -> dict[str, int]:
    """Картотека с каждой веткой статуса, долгом и авансом, врачом из фиши и
    врачом с последнего визита, вторым номером в заметке, датой рождения,
    диакритикой и добором до второй страницы. id идут по порядку заведения."""

    def add(name: str, phone: str, day: int, time: str, doc: str) -> int:
        c.post_json("/api/schedule/appointments", {"date": _d(day), "time": time,
                                                  "doctor": doc, "service": "consult",
                                                  "name": name, "phone": phone})
        return pid_by_phone(c, phone)

    def charge(pid: int, price: int) -> None:
        r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Plombă", "tooth": "11",
                                                     "price": str(price)})
        iid = _j(r)["data"]["plan"]["items"][0]["id"]
        c.post_json(f"/api/patients/{pid}/plan/{iid}/status", {"to": "in_lucru"})
        c.post_json(f"/api/patients/{pid}/plan/{iid}/status", {"to": "finalizat"})

    p = {}
    p["balan"] = add("Elena Bălan", "068111222", -400, "10:00", "d2")      # 1: год без визита
    p["ganea"] = add("Dumitru Ganea", "069222444", -5, "11:00", "d3")      # 2: аллергия
    p["ionescu"] = add("Maria Ionescu", "069987654", -10, "12:00", "d2")   # 3: план
    p["ciobanu"] = add("Svetlana Ciobanu", "078333555", -12, "13:00", "d4")  # 4: архив
    p["marin"] = add("Radu Marin", "079444666", 2, "14:00", "d2")          # 5: только будущий визит, долг
    p["popescu"] = add("Avans Popescu", "022220022", -3, "15:00", "d2")    # 6: аванс, активен
    c.post_json(f"/api/patients/{p['balan']}/profile", {"name": "Elena Bălan",
                                                       "phone": "068111222",
                                                       "email": "elena@example.com"})
    c.post_json(f"/api/patients/{p['ganea']}/profile", {"name": "Dumitru Ganea",
                                                       "phone": "069222444", "file_no": "D-77"})
    c.post_json(f"/api/patients/{p['ganea']}/alerts", {"kind": "allergy", "text": "Penicilină"})
    c.post_json(f"/api/patients/{p['ionescu']}/plan", {"procedure": "Coroană", "price": "1200"})
    c.post_json(f"/api/patients/{p['ciobanu']}/archive", {"on": True})
    c.post_json(f"/api/patients/{p['marin']}/profile", {"name": "Radu Marin",
                                                       "phone": "079444666",
                                                       "notes": "soția: 069 555 444"})
    charge(p["marin"], 1200)
    charge(p["popescu"], 500)
    c.post_json(f"/api/patients/{p['popescu']}/payments", {"amount": "800", "method": "card"})
    # 7: без телефона, с датой рождения и медиком курантом из фиши
    p["turcanu"] = new_patient(c, "Ion Țurcanu", birth_date="2003-01-01",
                               primary_doctor="Dr. Activ Trei")
    for i in range(8):                                                      # 8..15
        c.post_json("/api/patients", {"name": f"Pacient Masiv {i}", "phone": f"0611000{i:02d}"})
    return p


# Выдача списка на засеве `_seed` — для каждого отбора (строка запроса как в
# адресе): (люди по порядку, счёт всего, страница). До 13.10 её сверяли со
# старой страницей; записана с последнего кода, где паритет держался.
# Имена — ключи `_seed`, «mass» — восемь «Pacient Masiv» по порядку заведения.
_DEFAULT = ["popescu", "ganea", "ionescu", "balan", "marin", "turcanu", "mass"]
QUERIES = {
    "": (_DEFAULT, 14, 1),
    "sort=name": (["popescu", "ganea", "balan", "turcanu", "ionescu", "mass", "marin"], 14, 1),
    # «новые первыми» — по created_at, а он у засева совпадает до секунды
    # кусками: ничьи решает id, и порядок зависит от того, на какую секунду
    # пришёлся засев. Ожидание считается из базы (см. suite_list)
    "sort=new": (None, 14, 1),
    "sort=debt": (["marin", "balan", "ganea", "ionescu", "turcanu", "mass", "popescu"], 14, 1),
    "sort=zzz": (_DEFAULT, 14, 1),
    "q=balan": (["balan"], 1, 1), "q=elena@example": (["balan"], 1, 1),
    "q=444+666": (["marin"], 1, 1), "q=069555444": (["marin"], 1, 1),
    "q=d-77": (["ganea"], 1, 1),
    "q=01.01.2003": (["turcanu"], 1, 1), "q=1.1.2003": (["turcanu"], 1, 1),
    "q=02.01.2003": ([], 0, 1), "q=x": ([], 0, 1),
    "q=Pacient+Masiv": (["mass"], 8, 1),
    "q=Svetlana": (["ciobanu"], 1, 1), "q=svetlana&st=arhivat": (["ciobanu"], 1, 1),
    "st=atentie": (["ganea"], 1, 1), "st=tratament": (["ionescu"], 1, 1),
    "st=arhivat": (["ciobanu"], 1, 1),
    "st=activ": (["popescu", "ganea", "ionescu"], 3, 1),
    "st=inactiv": (["balan", "marin", "turcanu", "mass"], 11, 1),
    "med=-": (["mass"], 8, 1),
    "med=Dr.+Activ+Trei": (["ganea", "turcanu"], 2, 1),
    "med=Dr.+Activ+Doi&sort=name": (["popescu", "balan", "ionescu", "marin"], 4, 1),
    "ch=manual": (_DEFAULT, 14, 1), "ch=tg": ([], 0, 1), "ch=web": ([], 0, 1),
    "dat=da": (["marin"], 1, 1), "dat=avans": (["popescu"], 1, 1),
    "per=10": (["popescu", "ganea", "ionescu", "balan", "marin", "turcanu", "mass[:4]"], 14, 1),
    "per=10&page=2": (["mass[4:]"], 14, 2), "per=10&page=99": (["mass[4:]"], 14, 2),
    "per=7": (_DEFAULT, 14, 1),
    "per=50&sort=debt": (["marin", "balan", "ganea", "ionescu", "turcanu", "mass", "popescu"], 14, 1),
    "q=Pacient&st=inactiv&sort=name": (["mass"], 8, 1),
    "st=inactiv&dat=da": (["marin"], 1, 1),
    "med=-&per=10&page=2": (["mass"], 8, 1),
}
# статус строки выводится из данных (`_pl_status`): архив, предупреждение, план,
# давность визита; у восьми «Pacient Masiv» визитов нет — неактивны
STATUSES = {"balan": "inactiv", "ganea": "atentie", "ionescu": "tratament", "ciobanu": "arhivat",
            "marin": "inactiv", "popescu": "activ", "turcanu": "inactiv", "mass": "inactiv"}


def _expand(p: dict, names: list) -> list[int]:
    """Имена таблицы → id засева; «mass» — восемь подряд, со срезом страницы."""
    mass = list(range(p["turcanu"] + 1, p["turcanu"] + 9))
    part = {"mass": mass, "mass[:4]": mass[:4], "mass[4:]": mass[4:]}
    out: list[int] = []
    for n in names:
        out += part[n] if n in part else [p[n]]
    return out


def suite_list(res: Result) -> None:
    """Выдача списка для каждого отбора и порядка — люди, порядок, статусы,
    счёт и страница — на засеве с каждой веткой; карточки и фильтры над
    списком; предпросмотр."""
    with Server() as s:
        c = Client(s.url).login()
        p = _seed(c)
        who = {v: k for k, v in p.items()}
        con = sqlite3.connect(str(s.dir / "dental.db"))
        try:
            created = dict(con.execute("SELECT id, created_at FROM patients"))
        finally:
            con.close()
        live = _expand(p, _DEFAULT)
        for qs, (names, total, page) in QUERIES.items():
            d = _j(c.get("/api/patients" + (f"?{qs}" if qs else "")))["data"]
            # created_at — ISO одного вида: строкой сравнивается как временем;
            # свежие первыми, при равенстве — по id
            want = (_expand(p, names) if names is not None
                    else sorted(live, key=lambda i: (created[i], -i), reverse=True))
            res.check(f"[{qs or 'без фильтров'}] те люди в том порядке, счёт и страница",
                      ([r["id"] for r in d["rows"]], d["total"], d["page"]), (want, total, page))
            res.check(f"[{qs or 'без фильтров'}] статусы выведены из данных",
                      {r["id"]: r["status"] for r in d["rows"]},
                      {i: STATUSES[who.get(i, "mass")] for i in want})
        res.check("архивный скрыт и посчитан, пока его не спросили",
                  [_j(c.get("/api/patients" + q))["data"]["hidden_arh"]
                   for q in ("", "?q=Svet", "?st=arhivat")], [1, 0, 0])

        sm = _j(c.get("/api/patients/summary"))["data"]
        res.check("врачи в фильтре: каталог плюс те, кто есть в строках",
                  sm["doctors"], ["Dr. Activ Doi", "Dr. Activ Patru", "Dr. Activ Trei", "Dr. Arhivat Unu"])
        res.check("каналы в фильтре: без Telegram, пока таких пациентов нет",
                  [x["id"] for x in sm["channels"]], ["manual", "web"])
        res.check("статусы — порядок словаря и слова",
                  [(x["id"], x["label"]) for x in sm["statuses"]],
                  [("arhivat", "Arhivat"), ("atentie", "Necesită atenție"),
                   ("tratament", "În tratament"), ("inactiv", "Inactiv"), ("activ", "Activ")])
        peek = _j(c.get(f"/api/patients/{p['ionescu']}/peek"))["data"]["html"]
        res.ok("предпросмотр — сводка фиши словами сервера: имя, статус, план",
               "Maria Ionescu" in peek and "În tratament" in peek and "Plan de tratament" in peek,
               peek[:200])


def suite_api(res: Result) -> None:
    """Форма ответа, откаты чужих параметров, охрана, новая фиша."""
    with Server() as s:
        anon = Client(s.url)
        for path in ("/api/patients", "/api/patients/summary", "/api/patients/1/peek"):
            res.check(f"без входа {path} — 401", anon.get(path).status, 401)
        res.check("без входа фиша не заводится — 401",
                  anon.post_json("/api/patients", {"name": "X"}).status, 401)

        c = Client(s.url).login()
        p = _seed(c)
        d = _j(c.get("/api/patients?per=10"))["data"]
        res.check("страница: счёт, страницы, размер", (d["total"], d["pages"], d["per"], d["page"]),
                  (14, 2, 10, 1))
        res.check("строк на странице — per", len(d["rows"]), 10)
        by = {r["id"]: r for r in d["rows"]}
        pop = by[p["popescu"]]
        res.check("строка: поля для стойки", sorted(pop),
                  sorted(["id", "name", "initials", "phone", "email", "channel", "birth", "age",
                          "doctor", "doctor_own", "last", "next", "n_visits", "debt", "status",
                          "archived"]))
        res.ok("даты уже в виде dd.mm.yyyy", re.fullmatch(r"\d\d\.\d\d\.\d{4}", pop["last"]),
               f"{pop['last']!r}")
        res.check("аванс — отрицательный долг", pop["debt"], -300)
        res.check("врач с последнего визита — не «свой»",
                  (pop["doctor"], pop["doctor_own"]), ("Dr. Activ Doi", False))
        mar = by[p["marin"]]
        res.ok("ближайший визит — dd.mm HH:MM", re.fullmatch(r"\d\d\.\d\d \d\d:\d\d", mar["next"]),
               f"{mar['next']!r}")
        res.check("долг, без прошлого визита", (mar["debt"], mar["last"], mar["n_visits"]),
                  (1200, "", 1))
        tur = by[p["turcanu"]]
        res.check("медик курант из фиши — «свой», дата рождения и возраст",
                  (tur["doctor"], tur["doctor_own"], tur["birth"], tur["phone"], tur["channel"]),
                  ("Dr. Activ Trei", True, "01.01.2003", "", "manual"))
        res.ok("возраст посчитан", isinstance(tur["age"], int) and tur["age"] >= 23, f"{tur['age']}")
        res.check("инициалы с сервера", by[p["balan"]]["initials"], "EB")

        res.check("page за пределом — последняя",
                  _j(c.get("/api/patients?per=10&page=99"))["data"]["page"], 2)
        res.check("page=0 — первая", _j(c.get("/api/patients?page=0"))["data"]["page"], 1)
        res.check("чужой per — 20", _j(c.get("/api/patients?per=7"))["data"]["per"], 20)
        res.check("чужой sort — last", _j(c.get("/api/patients?sort=zzz"))["data"]["sort"], "last")
        res.check("чужой статус — все", _j(c.get("/api/patients?st=zzz"))["data"]["total"], 14)
        res.check("архив в счёте только по запросу",
                  (_j(c.get("/api/patients"))["data"]["hidden_arh"],
                   _j(c.get("/api/patients?q=Svet"))["data"]["hidden_arh"],
                   _j(c.get("/api/patients?st=arhivat"))["data"]["hidden_arh"]), (1, 0, 0))
        res.check("длинный запрос режется до 60 знаков — как форма",
                  _j(c.get("/api/patients?q=" + "b" * 70))["data"]["total"], 0)

        sm = _j(c.get("/api/patients/summary"))["data"]
        res.check("карточки: всего живых и новых за месяц",
                  [t["value"] for t in sm["tiles"]][:2], ["14", "15"])
        res.check("карточка записей ведёт в статистику", sm["tiles"][2]["href"], "/admin/stats")
        res.check("варианты «на страницу»", sm["per"], [10, 20, 50])
        res.check("врачи диалога — каталог клиники", sm["clinic_doctors"],
                  ["Dr. Arhivat Unu", "Dr. Activ Doi", "Dr. Activ Trei", "Dr. Activ Patru"])

        r = c.get(f"/api/patients/{p['ganea']}/peek")
        res.ok("предпросмотр: кусок с аллергией", r.status == 200
               and "Penicilină" in _j(r)["data"]["html"], f"{r.status}")
        res.check("предпросмотр несуществующего — 404", c.get("/api/patients/9999/peek").status, 404)

        r = c.post_json("/api/patients", {"name": "Grigore Nou", "phone": "060 777 888",
                                          "birth_date": "1978-02-02", "email": "gn@example.com",
                                          "primary_doctor": "Dr. Activ Doi"})
        d = _j(r)
        res.check("новая фиша: код и адрес фиши", (r.status, d["code"]), (200, "new_pat"))
        new_id = d["data"]["id"]
        res.check("адрес ведёт в фишу с плашкой", d["data"]["url"], f"/admin/patient/{new_id}?msg=new_pat")
        res.check("новый пациент виден в списке",
                  [x["name"] for x in _j(c.get("/api/patients?q=060777888"))["data"]["rows"]],
                  ["Grigore Nou"])
        prof = _j(c.get(f"/api/patients/{new_id}"))["data"]["profile"]
        res.check("дата рождения и врач сохранены", (prof["birth"], prof["primary_doctor"]),
                  ("02.02.1978", "Dr. Activ Doi"))
        r = c.post_json("/api/patients", {"name": "Alt Nume", "phone": "060777888"})
        d = _j(r)
        res.check("тот же телефон — та же фиша, не двойник",
                  (r.status, d["code"], d["data"]["id"], d["tone"]), (200, "dup_pat", new_id, "warn"))
        res.check("имя существующего не перезаписано",
                  _j(c.get(f"/api/patients/{new_id}"))["data"]["name"], "Grigore Nou")
        r = c.post_json("/api/patients", {"name": "  "})
        res.check("без имени — 422 с полем", (r.status, _j(r)["code"], _j(r).get("field")),
                  (422, "bad_pat", "name"))
        res.check("имя не строкой — 422", c.post_json("/api/patients", {"name": ["x"]}).status, 422)
        res.check("не JSON — 422", c.post("/api/patients", name="X").status, 422)
        res.check("чужой Origin — 403",
                  c.post_json("/api/patients", {"name": "Csrf"},
                              headers={"Origin": "http://evil.example"}).status, 403)
        res.check("без телефона заводится", _j(c.post_json("/api/patients", {"name": "Fara Tel"}))["code"],
                  "new_pat")


def suite_switch(res: Result) -> None:
    """Список — узел React (старая страница снята 13.10): отбор из адреса,
    экспорт отдаётся."""
    with Server() as s:
        c = Client(s.url).login()
        res.ok("без флага — тоже React (старого списка нет)",
               '<div id="root" data-screen="patients_search"' in c.get("/admin/search").body,
               "узла нет")

    s = Server()
    with s:
        c = Client(s.url).login()
        new_patient(c, "Flag Test", "060333444")
        page = c.get("/admin/search").body
        # подпись раздела печатает сам экран (08.10) — сервер отдаёт пустую
        res.ok("узел React в рамке раздела",
               '<div id="root" data-screen="patients_search"' in page
               and "pacienții clinicii" not in page and "/static/js/bundle.js?v=" in page, "узла нет")
        # ⭐ B1: модель оболочки приезжает ИНЛАЙНОМ тем же узлом.
        res.ok("модель оболочки на узле", 'data-shell="' in page, "модели нет")
        # ⛔ Негативный сторож B1: серверного каркаса на React-маршруте нет.
        res.ok("серверного каркаса нет",
               "<aside" not in page and 'class="top"' not in page, "две оболочки разом")
        res.ok("старой таблицы нет", "pl-tbl" not in page and "npdlg" not in page, "две разметки")
        res.ok("не внутри #live", 'id="live"' not in page, "живой кусок")
        page = c.get("/admin/search?q=balan&st=inactiv&per=10&sort=last&page=1").body
        params = json.loads(page.split("data-params=\"", 1)[1].split("\"", 1)[0]
                            .replace("&quot;", '"'))
        res.check("отбор из адреса — параметрами узла, без значений по умолчанию",
                  params, {"q": "balan", "st": "inactiv", "per": "10"})
        res.ok("?msg= на React-странице — плашка сервера",
               "dp_toast" in c.get("/admin/search?msg=new_pat").body, "плашки нет")
        res.ok("экспорт отдаётся", c.get("/admin/patients.xlsx").status == 200, "нет")
        res.check("без входа React-страница закрыта", Client(s.url).get("/admin/search").status, 303)

    s = Server()
    s.extra_env = dict(NO_KEY)
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana", "role": "receptie", "pin": "2222"})
        rec = Client(s.url)
        rec.post("/admin/login", password="2222", next="/admin")
        res.ok("регистратуре список открыт и по PIN",
               'data-screen="patients_search"' in rec.get("/admin/search").body, "закрыт")
        res.check("и API по PIN отвечает", rec.get("/api/patients").status, 200)
