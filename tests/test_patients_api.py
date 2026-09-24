"""Список пациентов (Search): поведение старой страницы зафиксировано и
сверено строка в строку с `GET /api/patients`, который считает отбор, порядок и
страницу в базе, а не в памяти.

Главное, что стережётся: у старой страницы (`_pl_rows` + `_pl_filter`, всё в
Python) и у API (`db.patients_rows`, SQL) ОДНА выдача на одних данных — те же
люди в том же порядке с теми же статусами, для каждого фильтра и порядка.
Правило живёт в двух местах осознанно (старая страница не меняется до конца
миграции), поэтому расхождение обязано краснеть здесь, а не у клиники.
"""
import json
import re

from harness import Client, Result, Server
from test_admin import _d
from test_settings_api import FLAGS, NO_KEY, _cfg, _j, _server_with_flags

STATUS_WORDS = {"Arhivat", "Necesită atenție", "În tratament", "Inactiv", "Activ"}


def _ids(page: str) -> list[int]:
    """Порядок строк старой страницы — по id из `<tr id='plr…'>`."""
    return [int(x) for x in re.findall(r"<tr id='plr(\d+)'", page)]


def _statuses(page: str) -> dict[int, str]:
    """Бейдж статуса каждой строки. У ячейки «Sold» тот же класс pl-badge,
    поэтому берём ту подпись, что из словаря статусов."""
    out = {}
    for m in re.finditer(r"<tr id='plr(\d+)'.*?</tr>", page, re.S):
        words = re.findall(r"<span class='pl-badge \w+'>([^<]+)</span>", m.group(0))
        out[int(m.group(1))] = next((w for w in words if w in STATUS_WORDS), "")
    return out


def _total(page: str) -> int:
    m = re.search(r"din (\d+) pacienți", page)
    return int(m.group(1)) if m else 0


def _hidden(page: str) -> int:
    m = re.search(r"(\d+) arhiva(?:t|ți) <a", page)
    return int(m.group(1)) if m else 0


def _options(page: str, name: str) -> list[str]:
    block = page.split(f"<select name='{name}'", 1)[1].split("</select>", 1)[0]
    return re.findall(r"<option value='([^']*)'", block)


def _seed(c: Client) -> dict[str, int]:
    """Картотека с каждой веткой статуса, долгом и авансом, врачом из фиши и
    врачом с последнего визита, вторым номером в заметке, датой рождения,
    диакритикой и добором до второй страницы. id идут по порядку заведения."""

    def add(name: str, phone: str, day: int, time: str, doc: str) -> int:
        c.post("/admin/add", adate=_d(day), atime=time, adoctor=doc,
               aservice="consult", aname=name, aphone=phone, back="/admin/all")
        return int(c.get(f"/admin/search?q={phone}").body.split(
            "<tr id='plr", 1)[1].split("'", 1)[0])

    def charge(pid: int, price: int) -> None:
        c.post(f"/admin/patient/{pid}/plan", procedure="Plombă", tooth="11",
               price=str(price))
        iid = re.findall(r"/plan/(\d+)/status", c.get(f"/admin/patient/{pid}").body)[-1]
        c.post(f"/admin/patient/{pid}/plan/{iid}/status", to="in_lucru")
        c.post(f"/admin/patient/{pid}/plan/{iid}/status", to="finalizat")

    p = {}
    p["balan"] = add("Elena Bălan", "068111222", -400, "10:00", "d2")      # 1: год без визита
    p["ganea"] = add("Dumitru Ganea", "069222444", -5, "11:00", "d3")      # 2: аллергия
    p["ionescu"] = add("Maria Ionescu", "069987654", -10, "12:00", "d2")   # 3: план
    p["ciobanu"] = add("Svetlana Ciobanu", "078333555", -12, "13:00", "d4")  # 4: архив
    p["marin"] = add("Radu Marin", "079444666", 2, "14:00", "d2")          # 5: только будущий визит, долг
    p["popescu"] = add("Avans Popescu", "022220022", -3, "15:00", "d2")    # 6: аванс, активен
    c.post(f"/admin/patient/{p['balan']}/save", name="Elena Bălan", phone="068111222",
           email="elena@example.com")
    c.post(f"/admin/patient/{p['ganea']}/save", name="Dumitru Ganea", phone="069222444",
           file_no="D-77")
    c.post(f"/admin/patient/{p['ganea']}/alert", kind="allergy", text="Penicilină")
    c.post(f"/admin/patient/{p['ionescu']}/plan", procedure="Coroană", price="1200")
    c.post(f"/admin/patient/{p['ciobanu']}/archive", on="1")
    c.post(f"/admin/patient/{p['marin']}/save", name="Radu Marin", phone="079444666",
           notes="soția: 069 555 444")
    charge(p["marin"], 1200)
    charge(p["popescu"], 500)
    c.post(f"/admin/patient/{p['popescu']}/pay", amount="800", method="card")
    # 7: без телефона, с датой рождения и медиком курантом из фиши
    r = c.post("/admin/patients/new", name="Ion Țurcanu", birth_date="2003-01-01",
               primary_doctor="Dr. Activ Trei")
    p["turcanu"] = int(r.location.split("/admin/patient/")[1].split("?")[0])
    for i in range(8):                                                      # 8..15
        c.post("/admin/patients/new", name=f"Pacient Masiv {i}", phone=f"0611000{i:02d}")
    return p


# отборы, на которых сверяются обе выдачи: строка запроса как в адресе
QUERIES = [
    "", "sort=name", "sort=new", "sort=debt", "sort=zzz",
    "q=balan", "q=elena@example", "q=444+666", "q=069555444", "q=d-77",
    "q=01.01.2003", "q=1.1.2003", "q=02.01.2003", "q=x", "q=Pacient+Masiv",
    "q=Svetlana", "q=svetlana&st=arhivat",
    "st=atentie", "st=tratament", "st=arhivat", "st=activ", "st=inactiv",
    "med=-", "med=Dr.+Activ+Trei", "med=Dr.+Activ+Doi&sort=name",
    "ch=manual", "ch=tg", "ch=web", "dat=da", "dat=avans",
    "per=10", "per=10&page=2", "per=10&page=99", "per=7", "per=50&sort=debt",
    "q=Pacient&st=inactiv&sort=name", "st=inactiv&dat=da", "med=-&per=10&page=2",
]


def suite_parity(res: Result) -> None:
    """Старая страница — эталон: её порядок и статусы записаны руками, а API
    обязан повторить их для каждого отбора из QUERIES."""
    with Server() as s:
        c = Client(s.url).login()
        p = _seed(c)
        b, g, i, cb, m, po, t = (p["balan"], p["ganea"], p["ionescu"], p["ciobanu"],
                                 p["marin"], p["popescu"], p["turcanu"])
        mass = list(range(t + 1, t + 9))

        # ---- поведение `_pl_rows`/`_pl_filter`, записанное руками ----
        page = c.get("/admin/search").body
        res.check("порядок по умолчанию: последний визит, потом никогда не бывшие по id",
                  _ids(page), [po, g, i, b, m, t] + mass)
        res.check("статусы выведены из данных", {k: _statuses(page)[k] for k in (b, g, i, m, po, t)},
                  {b: "Inactiv", g: "Necesită atenție", i: "În tratament",
                   m: "Inactiv", po: "Activ", t: "Inactiv"})
        res.check("архивный скрыт и посчитан", (cb in _ids(page), _hidden(page)), (False, 1))
        res.check("архив: свой статус", _statuses(c.get("/admin/search?st=arhivat").body).get(cb),
                  "Arhivat")
        res.check("сортировка по имени — без диакритики, хвост по id",
                  _ids(c.get("/admin/search?sort=name").body), [po, g, b, t, i] + mass + [m])
        res.check("сортировка по долгу: должник, нули по id, аванс последним",
                  _ids(c.get("/admin/search?sort=debt").body), [m, b, g, i, t] + mass + [po])
        res.check("«активные» — визит за год, свежие первыми",
                  _ids(c.get("/admin/search?st=activ").body), [po, g, i])
        res.check("«неактивные» — давний визит, потом никогда не бывшие",
                  _ids(c.get("/admin/search?st=inactiv").body), [b, m, t] + mass)
        res.check("без врача — только заведённые без визита и без медика куранта",
                  _ids(c.get("/admin/search?med=-").body), mass)
        res.check("врач из фиши и врач последнего визита — под одним фильтром",
                  _ids(c.get("/admin/search?med=Dr.+Activ+Trei").body), [g, t])
        res.check("цифры ищутся и в заметке", _ids(c.get("/admin/search?q=069555444").body), [m])
        res.check("номер дела ищется", _ids(c.get("/admin/search?q=d-77").body), [g])
        res.check("одна буква не находит никого", _ids(c.get("/admin/search?q=x").body), [])
        res.check("вторая страница — остаток", _ids(c.get("/admin/search?per=10&page=2").body),
                  mass[-4:])
        res.check("врачи в фильтре: каталог плюс те, кто есть в строках",
                  _options(page, "med"),
                  ["", "-", "Dr. Activ Doi", "Dr. Activ Patru", "Dr. Activ Trei", "Dr. Arhivat Unu"])
        res.check("каналы в фильтре: без Telegram, пока таких пациентов нет",
                  _options(page, "ch"), ["", "manual", "web"])

        # ---- API повторяет страницу для каждого отбора ----
        for qs in QUERIES:
            old = c.get("/admin/search" + (f"?{qs}" if qs else "")).body
            r = c.get("/api/patients" + (f"?{qs}" if qs else ""))
            d = _j(r)["data"]
            res.check(f"[{qs or 'без фильтров'}] те же люди в том же порядке",
                      [row["id"] for row in d["rows"]], _ids(old))
            res.check(f"[{qs or 'без фильтров'}] те же статусы",
                      {row["id"]: row["status"] for row in d["rows"]},
                      {k: {"Arhivat": "arhivat", "Necesită atenție": "atentie",
                           "În tratament": "tratament", "Inactiv": "inactiv",
                           "Activ": "activ"}[v] for k, v in _statuses(old).items()})
            # подсказка «N arhivați» у старой страницы живёт в пагинаторе, а его
            # у пустого списка нет — сверяем её только там, где она есть
            res.check(f"[{qs or 'без фильтров'}] тот же счёт и скрытый архив",
                      (d["total"], d["hidden_arh"] if _total(old) else 0),
                      (_total(old), _hidden(old)))

        # ---- то, что над списком ----
        sm = _j(c.get("/api/patients/summary"))["data"]
        vals = re.findall(r"<div class='pl-tv'>\s*<span>[^<]*</span><b>([^<]*)</b>", page)
        res.check("карточки: те же три числа", [t_["value"] for t_ in sm["tiles"]], vals)
        feet = re.findall(r"<small>(.*?)</small></div>",
                          page.split("<div class='pl-tiles'>", 1)[1].split("<div class='pl-grid'>", 1)[0],
                          re.S)
        res.check("карточки: те же подписи под числами",
                  [t_["foot"] for t_ in sm["tiles"]][:len(feet)], feet)
        res.check("врачи фильтра — те же", sm["doctors"], _options(page, "med")[2:])
        res.check("каналы — те же", [x["id"] for x in sm["channels"]], _options(page, "ch")[1:])
        res.check("статусы — тот же порядок словаря", [x["id"] for x in sm["statuses"]],
                  _options(page, "st")[1:])
        res.check("подписи статусов — те же слова",
                  [x["label"] for x in sm["statuses"]],
                  re.findall(r"<option value='\w+'>([^<]+)</option>",
                             page.split("<select name='st'", 1)[1].split("</select>", 1)[0]))
        peek_old = c.get(f"/admin/patient/{i}/peek").body
        res.check("предпросмотр — тот же кусок разметки",
                  _j(c.get(f"/api/patients/{i}/peek"))["data"]["html"], peek_old)


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
        res.ok("новый пациент виден и на старой странице",
               "Grigore Nou" in c.get("/admin/search?q=060777888").body, "нет в списке")
        card = c.get(f"/admin/patient/{new_id}").body
        res.ok("дата рождения и врач сохранены", "1978-02-02" in card and "Dr. Activ Doi" in card,
               "поля не легли")
        r = c.post_json("/api/patients", {"name": "Alt Nume", "phone": "060777888"})
        d = _j(r)
        res.check("тот же телефон — та же фиша, не двойник",
                  (r.status, d["code"], d["data"]["id"], d["tone"]), (200, "dup_pat", new_id, "warn"))
        res.ok("имя существующего не перезаписано", "Grigore Nou" in c.get(f"/admin/patient/{new_id}").body,
               "имя затёрлось")
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
    """Флаг patients_search: узел React с отбором из адреса, ?ui=legacy
    возвращает старый список, старые адреса живут рядом."""
    with Server() as s:
        c = Client(s.url).login()
        res.ok("без флага — старый список", "pl-tbl" in c.get("/admin/search").body
               and 'id="root"' not in c.get("/admin/search").body, "не старый")

    s = _server_with_flags()
    with s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Flag Test", phone="060333444")
        page = c.get("/admin/search").body
        res.ok("узел React в рамке раздела",
               '<div id="root" data-screen="patients_search"' in page
               and "pacienții clinicii" in page and "/static/js/bundle.js?v=" in page, "узла нет")
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
        res.ok("?ui=legacy — старый список",
               "pl-tbl" in c.get("/admin/search?ui=legacy").body, "не вернулся")
        res.ok("?msg= на React-странице — плашка сервера",
               "dp_toast" in c.get("/admin/search?msg=new_pat").body, "плашки нет")
        r = c.post("/admin/patients/new", name="Flag Doi", phone="060555666")
        res.ok("старая форма при флаге работает", r.msg == "new_pat", f"{r!r}")
        res.ok("экспорт при флаге отдаётся", c.get("/admin/patients.xlsx").status == 200, "нет")
        res.ok("флаги пережили правку", _cfg(s).get("ui") == {"react": FLAGS}, f"{_cfg(s).get('ui')}")
        res.check("без входа React-страница закрыта", Client(s.url).get("/admin/search").status, 303)

    s = _server_with_flags()
    s.extra_env = dict(NO_KEY)
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana", role="receptie", pin="2222")
        rec = Client(s.url)
        rec.post("/admin/login", password="2222", next="/admin")
        res.ok("регистратуре список открыт и по PIN",
               'data-screen="patients_search"' in rec.get("/admin/search").body, "закрыт")
        res.check("и API по PIN отвечает", rec.get("/api/patients").status, 200)
