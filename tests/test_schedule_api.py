"""Журнал (C24): `GET /api/schedule/week` повторяет старую страницу данными.

Пин поведения самой страницы живёт в `test_admin.suite_week` — здесь
проверяется, что JSON говорит О ТОМ ЖЕ: те же дни в том же порядке, те же
счётчики, те же чипы и те же цвета. Расхождение здесь значит, что React-экран
покажет не то, что показывает страница, а увидит это клиника.

⚠️ Дни сверяются СПИСКОМ ДАТ, а не количеством: закрытый день исчезает из
недели, только если в нём нет записей, поэтому колонок 5, 6 или 7, и
«столько же колонок» — не доказательство совпадения.
"""
import json
import re

from harness import Client, Result, Server, clinic_today
from datetime import timedelta

from test_admin import _week_cols


def _j(r) -> dict:
    return json.loads(r.body)


def _seed(c: Client, monday):
    """Неделя с записью, заметкой стойки, неявкой и отменой."""
    d = lambda i: (monday + timedelta(days=i)).isoformat()  # noqa: E731
    c.post("/admin/add", adate=d(1), atime="09:00", adoctor="d2",
           aservice="consult", aname="Ion Popa", aphone="069120120")
    c.post("/admin/add", adate=d(1), atime="10:30", adoctor="d3",
           aservice="pain", aname="Maria Rusu", aphone="069120121")
    c.post("/admin/note", ndate=d(1), ntime="12:00", ndoctor="d2",
           ntext="Livrare materiale")
    c.post("/admin/add", adate=d(3), atime="16:00", adoctor="d2",
           aservice="hygiene", aname="Vasile Lupu", aphone="069120122")
    aids = re.findall(r"data-appt='(\d+)'", c.get(f"/admin?date={d(1)}").body)
    if len(aids) >= 2:
        c.post(f"/admin/status/{aids[0]}", to="noshow", back=f"/admin?date={d(1)}")
    return d


def suite_api(res: Result) -> None:
    """Состав ответа, паритет со страницей и охрана маршрута."""
    with Server() as s:
        res.check("без входа — 401",
                  Client(s.url).get("/api/schedule/week").status, 401)
        c = Client(s.url).login()
        monday = clinic_today() + timedelta(days=7 - clinic_today().weekday())
        d = _seed(c, monday)

        j = _j(c.get(f"/api/schedule/week?date={d(1)}"))["data"]
        res.check("состав", sorted(j),
                  sorted(["monday", "sunday", "prev", "next", "span", "total",
                          "days", "day"]))
        res.check("границы недели и соседние недели",
                  (j["monday"], j["sunday"], j["prev"], j["next"], j["day"]),
                  (monday.isoformat(), d(6),
                   (monday - timedelta(days=7)).isoformat(),
                   (monday + timedelta(days=7)).isoformat(), d(1)))
        res.check("диапазон словами — как в шапке страницы", j["span"],
                  f"{monday.strftime('%d.%m')} – "
                  f"{(monday + timedelta(days=6)).strftime('%d.%m.%Y')}")

        page = c.get(f"/admin/week?date={d(1)}").body
        cols = _week_cols(page)
        res.check("дни: тот же список дат и в том же порядке",
                  [x["date"] for x in j["days"]], [x["date"] for x in cols])
        res.check("счётчики дней совпадают",
                  [x["count"] for x in j["days"]], [x["count"] for x in cols])
        res.check("подписи дней совпадают",
                  [x["label"] for x in j["days"]],
                  [x["label"].split()[0] for x in cols])
        res.check("«сегодня» отмечено там же",
                  [x["today"] for x in j["days"]], [x["today"] for x in cols])
        res.ok("итог недели — как в шапке страницы",
               f"{j['total']} programări" in page,
               f"в JSON {j['total']}, на странице иначе")

        tue = next(x for x in j["days"] if x["date"] == d(1))
        page_tue = next(x for x in cols if x["date"] == d(1))
        res.check("во вторнике три чипа: две записи и заметка",
                  ([x["kind"] for x in tue["items"]], len(page_tue["chips"])),
                  (["appt", "appt", "note"], 3))
        res.check("чип записи: час, имя, услуга — те же, что на странице",
                  [(x["time"], x["name"], x["service"]) for x in tue["items"]
                   if x["kind"] == "appt"],
                  [("09:00", "Ion Popa", "Consultație"),
                   ("10:30", "Maria Rusu", "Durere acută")])
        res.check("заметка стойки — своим видом и без имени пациента",
                  [x for x in tue["items"] if x["kind"] == "note"],
                  [{"kind": "note", "time": "12:00", "text": "Livrare materiale"}])
        res.ok("цвет приезжает переменной темы, а не хексом",
               all(x["bg"].startswith("var(--") and x["bar"].startswith("var(--")
                   for x in tue["items"] if x["kind"] == "appt"),
               "в JSON зашитый цвет — он останется зелёным на синей теме")
        res.check("неявка помечена и там, и там",
                  ([x["noshow"] for x in tue["items"] if x["kind"] == "appt"],
                   " noshow" in page_tue["chips"]),
                  ([True, False], True))
        res.ok("цвет неявки — красный, как на странице",
               next(x for x in tue["items"] if x.get("noshow"))["bg"] == "var(--red-soft)",
               "неявка не покраснела")

        # отмена: запись исчезает из обоих представлений
        aid = next(x["id"] for x in tue["items"] if x["kind"] == "appt" and not x["noshow"])
        c.post(f"/admin/status/{aid}", to="cancelled", back=f"/admin?date={d(1)}")
        j2 = _j(c.get(f"/api/schedule/week?date={d(1)}"))["data"]
        tue2 = next(x for x in j2["days"] if x["date"] == d(1))
        res.check("отменённая запись ушла и из списка, и из счётчика",
                  ([x["kind"] for x in tue2["items"]], tue2["count"]),
                  (["appt", "note"], 1))

        # любая дата недели даёт ту же неделю, кривая — текущую
        res.check("любой день недели открывает ту же неделю",
                  _j(c.get(f"/api/schedule/week?date={d(4)}"))["data"]["monday"],
                  monday.isoformat())
        res.check("кривая дата — текущая неделя, а не отказ",
                  _j(c.get("/api/schedule/week?date=2026-13-99"))["data"]["monday"],
                  (clinic_today() - timedelta(days=clinic_today().weekday())).isoformat())


def _server_with_flag() -> Server:
    s = Server()
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["schedule_week"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_switch(res: Result) -> None:
    """Флаг `schedule_week`: узел React вместо колонок — и НИКАКОГО живого
    опроса у недели, при этом день с тем же ключом остаётся живым.

    ⛔ Это главная проверка C24. Ключ живого раздела `dash` один на две
    страницы, а React-дерево внутри `#live` умирает при первой подмене:
    panel.js переписывает innerHTML под смонтированным деревом, и клик по
    свежему узлу молча перестаёт работать. Снять ключ насовсем нельзя — вместе
    с неделей погас бы день, до которого очередь дойдёт только в C26.
    """
    with Server() as s:
        c = Client(s.url).login()
        res.ok("без флага — старая неделя с колонками",
               "class='wcol'" in c.get("/admin/week").body, "не старая")

    s = _server_with_flag()
    with s:
        c = Client(s.url).login()
        monday = clinic_today() + timedelta(days=7 - clinic_today().weekday())
        page = c.get(f"/admin/week?date={monday.isoformat()}").body
        res.ok("узел React на месте",
               '<div id="root" data-screen="schedule_week"' in page
               and "/static/js/bundle.js?v=" in page, "узла нет")
        params = json.loads(page.split('data-params="', 1)[1].split('"', 1)[0]
                            .replace("&quot;", '"'))
        res.check("дата экрана — параметром узла", params,
                  {"date": monday.isoformat()})
        res.ok("старой разметки нет", "class='wcol'" not in page, "две разметки")

        res.check("НЕДЕЛЯ БОЛЬШЕ НЕ ЖИВАЯ: ни обёртки, ни метки опроса",
                  ('id="live"' in page, 'data-reload="12"' in page),
                  (False, False))
        # ⚠️ Прежняя формулировка была «status != 200 ИЛИ в теле есть id=root»
        # и зеленела по ВТОРОМУ дизъюнкту: сервер отвечал опросу 200 с ПОЛНЫМ
        # документом, `panel.js` вклеивал его внутрь `#live`, сайдбар и шапка
        # задваивались — каждые 12 секунд, пока открыта вкладка, отрисованная
        # до включения флага. Проверка это разрешала. Теперь позитив: ответ
        # ровно один и означает «перерисуйся целиком».
        poll = c.get(f"/admin/week?date={monday.isoformat()}",
                     headers={"X-DP-Live": "1"})
        res.check("ОПРОС от старой вкладки получает 205, а не документ",
                  (poll.status, poll.body.strip()), (205, ""))
        res.ok("и несёт версию с запретом кеша — чтобы перезагрузка была честной",
               poll.header("X-DP-V") != ""
               and poll.header("Cache-Control") == "no-store",
               "вкладка перезагрузится в кеш и увидит ту же старую разметку")

        day = c.get("/admin").body
        res.check("ДЕНЬ при этом остался живым: ключ dash снимать рано",
                  ('id="live"' in day, 'data-reload="12"' in day), (True, True))
        res.ok("день по-прежнему старый, без узла React",
               'id="root"' not in day, "флаг недели задел день")

        res.ok("?ui=legacy возвращает старую неделю",
               "class='wcol'" in c.get("/admin/week?ui=legacy").body, "нет")
        res.check("без входа закрыта", Client(s.url).get("/admin/week").status, 303)


# --- C25.4: паритет сетки дня ----------------------------------------------
# ⚠️ Сверяется не «похоже», а поле за полем: колонки, ряды часов, исход каждой
# ячейки, мишень переноса и поля самого перетаскивания. Расхождение здесь
# значит, что React-экран покажет не то, что показывает страница, а увидит это
# клиника — и увидит не сразу.

_TR = re.compile(r"<tr class='(hrow[^']*)'>(.*?)</tr>", re.S)
_TD = re.compile(r"(<td[^>]*>.*?</td>)", re.S)


def _grid_of(body: str) -> dict:
    """Разобрать таблицу страницы в сравнимый вид."""
    grid = body.split("<table class='grid'>", 1)[1].split("</table>", 1)[0]
    heads = re.findall(r"<a class='dh-n'[^>]*>([^<]+)</a>", grid)
    specs = re.findall(r"<span class='dh-s'>([^<]*)</span>", grid)
    rows = []
    for cls, tr in _TR.findall(grid):
        tds = _TD.findall(tr)
        hour = re.sub(r"<[^>]+>", " ", tds[0]).split()[0]
        closed = ("pauza" if "pauză" in tds[0] else
                  "inchis" if "închis" in tds[0] else "")
        cells = []
        for td in tds[1:]:
            if "class='goff'" in td:
                kind = "off"
            elif "appt busy" in td:
                kind = "busy"
            elif "data-appt=" in td:
                kind = "appts"
            else:
                kind = "free"
            cells.append({
                "kind": kind,
                "drop": " data-dk=" in td.split(">", 1)[0],
                "ids": re.findall(r"data-appt='(\d+)'", td),
                "min": re.findall(r"data-min='(\d+)'", td),
                "dur": re.findall(r"data-dur='(\d+)'", td),
                "busy": [bool(x) for x in re.findall(r"(data-busy='1')", td)],
                "mv": [bool(x) for x in re.findall(r"(data-mv='1')", td)],
            })
        rows.append({"hour": hour, "closed": closed, "now": " now" in cls,
                     "cells": cells})
    return {"heads": heads, "specs": specs, "rows": rows}


def _model_of(j: dict) -> dict:
    """То же из JSON — теми же именами, чтобы сравнение было прямым."""
    return {
        "heads": [x["name"] for x in j["doctors"]],
        "specs": [x["spec"] for x in j["doctors"]],
        "rows": [{
            "hour": h["label"], "closed": h["closed"], "now": h["now"],
            "cells": [{
                "kind": c["kind"], "drop": c["drop"],
                "ids": [str(x["id"]) for x in c["items"]],
                "min": [str(x["min"]) for x in c["items"]],
                "dur": [str(x["dur"]) for x in c["items"]],
                "busy": [True for x in c["items"] if x["busy"]],
                "mv": [True for x in c["items"] if x["movable"]],
            } for c in h["cells"]],
        } for h in j["hours"]],
    }


def _seed_full(c: Client, day: str) -> None:
    """День, задевающий каждое правило сетки."""
    c.post("/admin/add", adate=day, atime="09:00", adoctor="d2",
           aservice="consult", aname="Ion Popa", aphone="069170170")
    c.post("/admin/add", adate=day, atime="10:00", adoctor="d3",
           aservice="pain", aname="Maria Rusu", aphone="069170171")
    c.post("/admin/add", adate=day, atime="11:00", adoctor="d2",
           aservice="long", aname="Vasile Lupu", aphone="069170172")
    c.post("/admin/add", adate=day, atime="12:30", adoctor="d2",
           aservice="consult", aname="Ana Gheorghiu", aphone="069170173")
    c.post("/admin/note", ndate=day, ntime="15:00", ndoctor="d2",
           ntext="Livrare materiale")
    ids = re.findall(r"data-appt='(\d+)'", c.get(f"/admin/all?date={day}").body)
    if len(ids) >= 2:
        c.post(f"/admin/status/{ids[0]}", to="noshow", back=f"/admin/all?date={day}")
        c.post(f"/admin/status/{ids[1]}", to="cancelled", back=f"/admin/all?date={day}")


def suite_day_parity(res: Result) -> None:
    """JSON сетки дня повторяет страницу поле за полем — на обоих экранах."""
    with Server() as s:
        res.check("без входа — 401",
                  Client(s.url).get("/api/schedule/day").status, 401)
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=3)).isoformat()
        _seed_full(c, day)

        page = _grid_of(c.get(f"/admin/all?date={day}").body)
        model = _model_of(_j(c.get(f"/api/schedule/day?date={day}"))["data"])
        res.check("колонки: имена совпадают", model["heads"], page["heads"])
        res.check("колонки: подписи совпадают", model["specs"], page["specs"])
        res.check("ряды часов: те же метки и в том же порядке",
                  [r["hour"] for r in model["rows"]], [r["hour"] for r in page["rows"]])
        res.check("закрытые часы названы одинаково",
                  [r["closed"] for r in model["rows"]],
                  [r["closed"] for r in page["rows"]])
        res.check("подсветка текущего часа совпадает",
                  [r["now"] for r in model["rows"]], [r["now"] for r in page["rows"]])
        res.check("исход каждой ячейки совпадает",
                  [[c_["kind"] for c_ in r["cells"]] for r in model["rows"]],
                  [[c_["kind"] for c_ in r["cells"]] for r in page["rows"]])
        res.check("мишень переноса стоит там же",
                  [[c_["drop"] for c_ in r["cells"]] for r in model["rows"]],
                  [[c_["drop"] for c_ in r["cells"]] for r in page["rows"]])
        res.check("записи лежат в тех же ячейках и в том же порядке",
                  [[c_["ids"] for c_ in r["cells"]] for r in model["rows"]],
                  [[c_["ids"] for c_ in r["cells"]] for r in page["rows"]])
        res.check("поля перетаскивания совпадают: минуты, длительность, занятость",
                  [[(c_["min"], c_["dur"], c_["busy"], c_["mv"]) for c_ in r["cells"]]
                   for r in model["rows"]],
                  [[(c_["min"], c_["dur"], c_["busy"], c_["mv"]) for c_ in r["cells"]]
                   for r in page["rows"]])

        # содержимое карточки — то же, что печатает страница
        j = _j(c.get(f"/api/schedule/day?date={day}"))["data"]
        items = [x for h in j["hours"] for cl in h["cells"] for x in cl["items"]]
        body = c.get(f"/admin/all?date={day}").body
        appt = next(x for x in items if x["kind"] == "appt" and x["status"] == "noshow")
        res.ok("неявка помечена и статусом, и цветом",
               appt["bg"] == "var(--red-soft)" and "s-noshow" in body,
               "неявка в модели и на странице разошлись")
        note = next(x for x in items if x["kind"] == "note")
        res.check("заметка стойки — своим видом и текстом",
                  (note["kind"], note["text"]), ("note", "Livrare materiale"))
        res.ok("отменённая запись не попала ни в модель, ни в сетку",
               all(x["kind"] != "appt" or x["status"] != "cancelled" for x in items),
               "отменённая запись видна в сетке")

        # --- день врача: тот же построитель, другие данные ---
        page1 = _grid_of(c.get(f"/admin/doctor/d2?date={day}").body)
        model1 = _model_of(_j(c.get(f"/api/schedule/day?date={day}&doctor=d2"))["data"])
        res.check("день врача: одна колонка и та же",
                  (model1["heads"], page1["heads"]),
                  (["Dr. Activ Doi"], ["Dr. Activ Doi"]))
        res.check("день врача: ряды и ячейки совпадают",
                  [[c_["kind"] for c_ in r["cells"]] for r in model1["rows"]],
                  [[c_["kind"] for c_ in r["cells"]] for r in page1["rows"]])
        res.check("день врача: записи те же",
                  [[c_["ids"] for c_ in r["cells"]] for r in model1["rows"]],
                  [[c_["ids"] for c_ in r["cells"]] for r in page1["rows"]])
        res.check("чужой врач — 404, а не пустая сетка",
                  c.get("/api/schedule/day?doctor=d999").status, 404)


def suite_day_orphan(res: Result) -> None:
    """Легаси-строка без `doctor_id` стоит в одной и той же колонке у обоих.

    ⚠️ Такую строку не создать через интерфейс: `/admin/add` всегда пишет
    `doctor_id`. Поэтому она делается прямо в базе песочницы — это ровно то,
    что лежит у клиник, обновившихся с версий до v1.7.1, и единственный
    способ проверить вторую половину правила «id, иначе снимок имени».
    """
    import sqlite3
    with Server() as s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=4)).isoformat()
        c.post("/admin/add", adate=day, atime="09:00", adoctor="d2",
               aservice="consult", aname="Legacy Pacient", aphone="069180180")
        c.post("/admin/add", adate=day, atime="10:00", adoctor="d3",
               aservice="consult", aname="Nou Pacient", aphone="069180181")
        ids = re.findall(r"data-appt='(\d+)'", c.get(f"/admin/all?date={day}").body)
        con = sqlite3.connect(s.dir / "dental.db")
        con.execute("UPDATE appointments SET doctor_id = NULL WHERE id = ?", (ids[0],))
        con.commit()
        con.close()

        page = _grid_of(c.get(f"/admin/all?date={day}").body)
        model = _model_of(_j(c.get(f"/api/schedule/day?date={day}"))["data"])
        res.check("легаси-запись стоит в той же ячейке, что на странице",
                  [[c_["ids"] for c_ in r["cells"]] for r in model["rows"]],
                  [[c_["ids"] for c_ in r["cells"]] for r in page["rows"]])
        res.ok("и она вообще видна", any(ids[0] in c_["ids"] for r in model["rows"]
                                         for c_ in r["cells"]),
               "запись без doctor_id исчезла из модели")
        res.ok("и не задвоилась у соседнего врача",
               sum(1 for r in model["rows"] for c_ in r["cells"] if ids[0] in c_["ids"]) == 1,
               "запись показана дважды")
        # ⚠️ Запись-сирота ЛЕЖИТ В КОЛОНКЕ НАСТОЯЩЕГО врача (её нашли по снимку
        # имени), поэтому тащить её можно: адрес переноса — id колонки, и он
        # есть. Колонка-сирота, у которой своего id нет вовсе, бывает на канве
        # дня — это уже C26, и правило про «переносить оттуда некуда» живёт там.
        cell = next(c_ for r in model["rows"] for c_ in r["cells"] if ids[0] in c_["ids"])
        res.check("из колонки настоящего врача запись-сироту перенести можно",
                  cell["mv"], [True])


def _server_day_flag() -> Server:
    s = Server()
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["schedule_all", "schedule_doctor"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_day_switch(res: Result) -> None:
    """Флаги дневных экранов: узел React вместо таблицы, живой опрос снят у
    обоих, а панель дня (`/admin`, ключ `dash`) остаётся живой.

    ⚠️ Оба экрана сидят на ключе `prog`. После этого коммита живых страниц у
    ключа не остаётся — но снимать его нельзя до C26/C27: панель дня опрашивает
    свой ключ, и правило «узел React не внутри #live» держится телом страницы,
    а не именем ключа.
    """
    with Server() as s:
        c = Client(s.url).login()
        res.ok("без флага — старая таблица",
               "<table class='grid'>" in c.get("/admin/all").body, "не старая")

    s = _server_day_flag()
    with s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=2)).isoformat()
        page = c.get(f"/admin/all?date={day}").body
        res.ok("узел React на «Toți medicii»",
               '<div id="root" data-screen="schedule_all"' in page, "узла нет")
        res.check("дата — параметром узла",
                  json.loads(page.split('data-params="', 1)[1].split('"', 1)[0]
                             .replace("&quot;", '"')), {"date": day})
        res.check("«Toți medicii» больше не живая",
                  ('id="live"' in page, 'data-reload="12"' in page), (False, False))
        res.ok("старой таблицы нет", "<table class='grid'>" not in page, "две разметки")

        doc = c.get(f"/admin/doctor/d2?date={day}").body
        res.ok("узел React на дне врача",
               '<div id="root" data-screen="schedule_doctor"' in doc, "узла нет")
        res.check("врач и дата — параметрами узла",
                  json.loads(doc.split('data-params="', 1)[1].split('"', 1)[0]
                             .replace("&quot;", '"')), {"date": day, "dk": "d2"})
        res.check("день врача больше не живой",
                  ('id="live"' in doc, 'data-reload="12"' in doc), (False, False))

        # ⛔ Вкладка, открытая ДО включения флага, продолжает опрашивать по
        # старому договору — и узнать «я больше не живая» ей неоткуда: признак
        # стоит на <body>, снаружи подменяемого куска. Ответ 205 — её
        # единственный путь к перерисовке. Обоим дневным адресам, а не одному:
        # флаг включают на каждый экран отдельно.
        for path in (f"/admin/all?date={day}", f"/admin/doctor/d2?date={day}"):
            poll = c.get(path, headers={"X-DP-Live": "1"})
            res.check(f"опрос старой вкладки на {path.split('?')[0]} → 205",
                      (poll.status, poll.body.strip()), (205, ""))

        panel = c.get("/admin").body
        res.check("ПАНЕЛЬ ДНЯ осталась живой и старой",
                  ('id="live"' in panel, 'data-reload="12"' in panel,
                   'id="root"' in panel), (True, True, False))

        res.ok("?ui=legacy возвращает старую таблицу",
               "<table class='grid'>" in c.get(f"/admin/all?date={day}&ui=legacy").body,
               "нет")
        res.check("чужой врач при флаге — на журнал",
                  c.get("/admin/doctor/d999").status, 307)
        res.check("без входа закрыта", Client(s.url).get("/admin/all").status, 303)


# ------------------------------------------- живой канал ДАННЫМИ (C27.1)


def suite_live_envelope(res: Result) -> None:
    """Конверт живого канала: `GET /api/schedule/live`.

    ⛔ Главное свойство живого журнала — сервер умеет сказать «не менялось».
    У старого канала это держалось ПОСТРОЕНИЕМ: `data-hash` обёртки и
    `X-DP-Hash` фрагмента считались от одной строки разметки, и второго рендера
    «для опроса» не было. Здесь проверяется то же самое, но про ДАННЫЕ, и
    именно про данные, а не про отпечаток HTML: отпечаток обязан считаться ОТ
    ТОГО ЖЕ, что уехало клиенту.

    ⚠️ День собран из всего, обо что отпечаток спотыкается: пациент в приёмной
    (минуты ждать браузеру), визит «сейчас» (подсветка часа), и НИЧЬЯ в
    сортировке — две законченные записи на одну минуту у одного врача.
    Уникальный индекс слота частичный (`WHERE status IN (активные)`), поэтому
    две законченные ложатся, а порядок таких строк без тай-брейка по `a.id`
    наследуется от базы и решает геометрию блоков.

    ⏳ ЧЕГО ЗДЕСЬ НЕТ и почему: ветка `live: false` не исполняется ни одной
    проверкой. Она включается флагом React у экрана панели, а `react_on`
    отклоняет имя, которого нет в `REACT_SCREENS`; `schedule_dash` появится там
    только в C26.5. Принято сознательно: заводить имя экрана раньше самого
    экрана значило бы разрешить включить панели флаг, за которым ничего нет.
    ⛔ Закрыть эту ветку — первая обязанность C26.5, а не «когда-нибудь»:
    вкладка, открытая до включения флага, узнаёт «я больше не живая» ровно
    отсюда.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = clinic_today().isoformat()
        for i, (hh, nm) in enumerate((("09:00", "Live Unu"), ("10:00", "Live Doi"),
                                      ("11:00", "Live Trei"))):
            c.post("/admin/add", adate=day, atime=hh, adoctor="d2",
                   aservice="consult", aname=nm, aphone=f"06980010{i}")
        ids = {m.group(2): m.group(1) for m in re.finditer(
            r"<tr class='[a-z]+'><td>(\d+)</td>.*?(Live \w+)",
            c.get(f"/admin/all?date={day}").body, re.S)}
        assert {"Live Unu", "Live Doi", "Live Trei"} <= set(ids), sorted(ids)
        c.post(f"/admin/status/{ids['Live Unu']}", to="waiting", back="/admin")
        for nm in ("Live Doi", "Live Trei"):
            c.post(f"/admin/status/{ids[nm]}", to="done", back="/admin")
        import sqlite3 as _sq
        con = _sq.connect(s.dir / "dental.db")
        con.execute("UPDATE appointments SET starts_at = (SELECT starts_at FROM"
                    " appointments WHERE id = ?) WHERE id = ?",
                    (ids["Live Doi"], ids["Live Trei"]))
        con.commit()
        con.close()

        url = f"/api/schedule/live?date={day}"
        a = c.get(url)
        if not res.check("якорь: канал отвечает состоянием панели",
                         (a.status, _j(a)["data"]["live"],
                          "canvas" in _j(a)["data"],
                          len(_j(a)["data"]["canvas"]["columns"]) > 0),
                         (200, True, True, True)):
            return

        # --- 1. детерминизм: ДАННЫЕ, а не разметка ---
        b = c.get(url)
        res.check("два запроса при неизменном дне дают ОДНИ И ТЕ ЖЕ данные",
                  (a.body == b.body,
                   a.header("X-DP-Hash") == b.header("X-DP-Hash")),
                  (True, True))
        res.ok("и в дне ЕСТЬ то, обо что отпечаток спотыкается",
               any(x.get("wait_since") for col in _j(a)["data"]["canvas"]["columns"]
                   for x in col["blocks"])
               and any(b2["of"] == 2 for col in _j(a)["data"]["canvas"]["columns"]
                       for b2 in col["blocks"]),
               "ни ожидающего, ни ничьей — проверка шла бы мимо своего предмета")

        # --- 2. отпечаток считается ОТ ТОГО ЖЕ, что отправлено ---
        canon = json.dumps(_j(a)["data"], sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
        import hashlib as _h
        res.check("ОТПЕЧАТОК — от отправленных данных, а не от чего-то рядом",
                  _h.md5(canon.encode("utf-8")).hexdigest(), a.header("X-DP-Hash"))

        # --- 3. совпал — 204 без тела ---
        same = c.get(url, headers={"X-DP-Hash": a.header("X-DP-Hash")})
        res.check("совпавший отпечаток → 204 и пустое тело",
                  (same.status, same.body.strip()), (204, ""))
        res.ok("у 204 те же заголовки: версия и запрет кеша",
               same.header("X-DP-V") != "" and same.header("X-DP-Hash") != ""
               and same.header("Cache-Control") == "no-store",
               "без X-DP-V клиент не узнает об обновлении exe, без no-store "
               "WebView2 вправе отдать вчерашний ответ")

        # --- 4. изменение двигает ИМЕННО относящееся ---
        c.post("/admin/add", adate=day, atime="14:00", adoctor="d3",
               aservice="consult", aname="Live Nou", aphone="069800199")
        after = c.get(url, headers={"X-DP-Hash": a.header("X-DP-Hash")})
        blocks = lambda r: [x["id"] for col in _j(r)["data"]["canvas"]["columns"]  # noqa: E731
                            for x in col["blocks"]]
        res.check("новая запись меняет отпечаток и приезжает В КАНВЕ",
                  (after.status,
                   after.header("X-DP-Hash") != a.header("X-DP-Hash"),
                   len(blocks(after)) == len(blocks(a)) + 1),
                  (200, True, True))
        res.check("а то, чего она не касается, осталось прежним",
                  (_j(after)["data"]["screen"], _j(after)["data"]["date"],
                   _j(after)["data"]["live"]),
                  (_j(a)["data"]["screen"], _j(a)["data"]["date"], True))

        # --- 5. охрана: JSON 401, а не редирект на форму входа ---
        anon = Client(s.url).get(url)
        res.check("опрос без входа → JSON 401, НЕ 303",
                  (anon.status, _j(anon).get("ok")), (401, False))

        # --- 6. эхо параметров и кривая дата ---
        res.check("экран и дата возвращаются эхом",
                  (_j(a)["data"]["screen"], _j(a)["data"]["date"]), ("panel", day))
        bad = c.get("/api/schedule/live?date=31-31-31")
        res.check("кривая дата молча открывает сегодняшний день — как у страницы",
                  (bad.status, _j(bad)["data"]["date"]), (200, clinic_today().isoformat()))
        res.check("неизвестный экран отбивается с полем, а не молча пустотой",
                  (c.get("/api/schedule/live?screen=nope").status,
                   _j(c.get("/api/schedule/live?screen=nope")).get("field")),
                  (422, "screen"))
