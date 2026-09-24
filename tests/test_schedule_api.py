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

from harness import TZ, Client, Result, Server, clinic_today
from datetime import datetime, timedelta

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
                  [{"kind": "note", "time": "12:00", "text_cut": "Livrare materiale"}])
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

    ✅ Ветка `live: false` (C26.5.2). По проводу она больше не достижима — и
    это усиление, а не потеря: `live` теперь ИМЯ ТОГО ЖЕ ФАКТА, что и состав
    конверта, а состав есть у всякого экрана, который вообще числится в
    `_LIVE_SCREENS`. Обе полярности исполняет чистая функция `live_envelope`
    (`test_api.suite_live_react`), и исполняет в КАЖДОМ прогоне, а не только
    когда у кого-то включён флаг. Чем ветка была раньше — «канал увидел флаг
    React и отнял состояние у того самого клиента, ради которого делался», —
    разобрано в `suite_dash_flag`.
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

        # --- 4a. КАНОНИЧЕСКОЕ значение, а не проекция показа (C26.5.2) ---
        # ⛔ Три разных вопроса, и ответить надо на все три: изменение ВНУТРИ
        # видимой границы (а), изменение ЗА ней при совпадающем начале (б) и
        # доезжает ли полное значение ДО КЛИЕНТА (в). Без (в) можно получить
        # верный отпечаток при неверном теле — и найти это уже на React.
        # ⚠️ Граница показа у комментария 60 знаков, у заметки 80. Тексты
        # длиннее границы и совпадают ДО неё: иначе проверка сравнивала бы не
        # то и зеленела бы по неверной причине.
        aid = int(ids["Live Unu"])
        head = "Alergie la penicilina, de sunat inainte, vine cu mama, X"  # 56
        cmt_a = head + "AAAA" + "1" * 60
        cmt_b = head + "AAAA" + "2" * 60      # совпадает первые 60, дальше нет
        cmt_c = head + "BBBB" + "1" * 60      # отличие ВНУТРИ первых 60
        assert cmt_a[:60] == cmt_b[:60] and cmt_a[:60] != cmt_c[:60], "фикстура"

        def _cmt(txt):
            r = c.post_json(f"/api/schedule/appointments/{aid}/comment",
                            {"comment": txt})
            assert r.status == 200, (r.status, r.body[:120])
            rr = c.get(url)
            blk = next(b for col in _j(rr)["data"]["canvas"]["columns"]
                       for b in col["blocks"] if b.get("id") == aid)
            return rr.header("X-DP-Hash"), blk

        h_a, blk_a = _cmt(cmt_a)
        h_c, _ = _cmt(cmt_c)
        res.check("(а) правка ВНУТРИ видимой границы двигает отпечаток",
                  h_c != h_a, True)
        h_a2, _ = _cmt(cmt_a)
        h_b, blk_b = _cmt(cmt_b)
        res.check("(б) ТО ЖЕ начало и другой хвост — тоже двигает отпечаток",
                  (blk_a["comment_cut"] == blk_b["comment_cut"], h_b != h_a2),
                  (True, True))
        res.check("(в) полное значение доезжает ДО КЛИЕНТА, а не только до хеша",
                  (blk_b["comment"], len(blk_b["comment_cut"])), (cmt_b, 60))
        # ⭐ Заметка: её полное значение (`text`) лежало в конверте и до
        # C26.5.2 — побочным следствием того, что канва берёт вид у
        # `day.appt_view`. Следствие стало решением, и теперь оно пиннится.
        note_txt = "Sedinta de dimineata cu tot personalul clinicii, sala mare" \
                   " si proiectorul nou, " + "9" * 60
        assert len(note_txt) > 80
        c.post("/admin/note", ndate=day, ntime="15:00", ndoctor="d3",
               ntext=note_txt, back="/admin")
        nb = next(b for col in _j(c.get(url))["data"]["canvas"]["columns"]
                  for b in col["blocks"] if b.get("kind") == "note")
        # ⚠️ 120 — потолок САМОЙ заметки (`_add_note`), а не показа: полным
        # считается то, что легло в базу, и сравнивать надо с ним.
        res.check("у заметки в конверте ПОЛНЫЙ текст, а обрезки — рядом и с "
                  "другими именами",
                  (nb["text"], len(nb["title"]), len(nb["label"])),
                  (note_txt[:120], 80, 40))

        # --- 4b. то, чем живут диалоги, и чего в конверте не было (C26.5.3-a) ---
        env = _j(c.get(url))["data"]
        res.check("диалог собирается из КОНВЕРТА: кнопки, концы заметки, форма",
                  (sorted(env["actions"]), "cancelled" in env["note_actions"],
                   sorted(env["slotform"]),
                   all(isinstance(x, int) for x in env["note_ends"])),
                  (sorted(env["actions"]), True, ["birth_max", "services"], True))
        # ⛔ Потолок даты рождения — СЕГОДНЯ В ЧАСАХ КЛИНИКИ. Считанный от
        # `date.today()`, он переворачивал бы отпечаток в полночь по часам
        # машины и расходился бы под `TZ=UTC0` с остальной моделью.
        res.check("потолок даты рождения — сегодня КЛИНИКИ, а не машины",
                  env["slotform"]["birth_max"], clinic_today().isoformat())
        # --- 4c. заметка: состояние в блоке, и им ИНДЕКСИРУЕТСЯ матрица (d) ---
        # ⛔ `note_actions` лежал в конверте с шага `a`, но спросить его было
        # нечем: блок заметки состояния не нёс. Клиенту пришлось бы считать её
        # «confirmed» по умолчанию — то есть завести в браузере ВТОРОЕ знание о
        # состоянии, а эта пара расходилась молча уже дважды (08-12, 08-16).
        # ⚠️ Матрица знает ДВА состояния из шести: у заметки нет прихода и
        # исхода, есть «убрать» и «вернуть».
        res.check("состояние заметки приезжает блоком и спрашивает её кнопку",
                  (nb.get("status"),
                   [b["label"] for b in env["note_actions"].get(nb.get("status", ""), [])],
                   sorted(env["note_actions"])),
                  ("confirmed", ["Șterge"], ["cancelled", "confirmed"]))
        blk = next(b for col in env["canvas"]["columns"] for b in col["blocks"]
                   if b.get("id") == aid)
        res.check("в блоке есть всё, что нужно диалогу, и ничего сверх",
                  sorted(k for k in ("doctor", "pid", "rec", "status", "comment")
                         if k in blk),
                  ["comment", "doctor", "pid", "rec", "status"])

        # --- 4b2. команда ЖИВОЙ поверхности не возвращает состояния (C26.5.3) ---
        # ⛔ Состояние выпускается ровно одной дверью — конвертом с его
        # отпечатком. Ответ действия отпечатка не несёт, значит любое
        # состояние в нём — второй источник истины, не участвующий в
        # протоколе; клиент после команды спрашивает канал сам.
        # ⚠️ Контраст обязателен: без него проверка зелена и у маршрута,
        # который данных не отдаёт НИКОМУ, — а день на них живёт.
        panel_ok = c.post_json(
            f"/api/schedule/appointments/{aid}/comment?screen=panel", {"comment": "x"})
        day_ok = c.post_json(
            f"/api/schedule/appointments/{aid}/comment?date={day}", {"comment": "x"})
        res.check("панели — код без состояния, дню — свежий день",
                  (panel_ok.status, "data" in _j(panel_ok),
                   day_ok.status, "data" in _j(day_ok)),
                  (200, False, 200, True))
        # ⚠️ 409 у этих двух команд недостижим (комментарий и исход ни с чем
        # не спорят), поэтому «отказ без состояния» пинится на достижимом
        # 422 — слове не из конвейера. Названо, чтобы не искали дыру.
        bad_to = c.post_json(
            f"/api/schedule/appointments/{aid}/status?screen=panel", {"to": "nope"})
        res.check("отказ тоже без состояния, и он JSON, а не редирект",
                  (bad_to.status, "data" in _j(bad_to), _j(bad_to)["ok"]),
                  (422, False, False))

        # --- 4c. ⭐ ОТМЕНЁННАЯ запись отпечаток не двигает ---
        # Этот сторож возможен ТОЛЬКО потому, что карточка не поехала в
        # конверт отдельной структурой: `_collect_cards` несёт отменённые, а
        # на панели их негде нажать — и правка у невидимой записи гнала бы
        # перерисовку, в которой на экране не меняется ничего. Проверка
        # доказывает, что решение осталось в силе.
        c.post(f"/admin/status/{aid}", to="cancelled", back="/admin")
        gone = c.get(url)
        res.ok("отменённая запись ушла с канвы",
               not any(b.get("id") == aid
                       for col in _j(gone)["data"]["canvas"]["columns"]
                       for b in col["blocks"]),
               "отменённая осталась на канве — сторож ниже проверял бы не то")
        h_before = gone.header("X-DP-Hash")
        r_cmt = c.post_json(f"/api/schedule/appointments/{aid}/comment",
                            {"comment": "правка у невидимой записи"})
        res.check("правка принята сервером (иначе сторож ниже зелен впустую)",
                  r_cmt.status, 200)
        res.check("⭐ и отпечаток панели НЕ двинулся: на экране не изменилось ничего",
                  c.get(url).header("X-DP-Hash"), h_before)

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


def suite_dash_flag(res: Result) -> None:
    """Флаг панели: что происходит с живым каналом и со старой вкладкой (C26.5.1).

    ⛔ Имя `schedule_dash` заведено РАНЬШЕ самого экрана, и это осознанный
    риск: пока флаг включён, панель отдаёт пустой узел. Взамен ветка «этот
    экран больше не живой» перестаёт быть непроверяемой — а отвечает она
    вкладке, которую регистратура открыла ДО того, как директор включил флаг.

    ⛔ Безопасность доказывается не словами «флаг выключен», а проверкой: при
    ВЫКЛЮЧЕННОМ флаге ни страница, ни канал не меняются ни в чём.

    ⭐ C26.5.2 развернул здесь главное: канал ДАННЫХ перестал спрашивать, кто
    рисует экран. Раньше он отвечал `live:false` и пустотой, увидев флаг, —
    ответ, у которого не было ни одного потребителя (старая вкладка
    опрашивает адрес СТРАНИЦЫ и получает 205), зато будущая React-панель
    оставалась без единственного источника данных. Теперь состояние одно и то
    же при любом флаге, поверхность едет заголовком `X-DP-Surface`, и обе
    половины отката проверяются здесь: 205 старой вкладке на включение флага и
    «здесь теперь legacy» React-вкладке на выключение.
    """
    day = clinic_today().isoformat()
    with Server() as s:
        c = Client(s.url).login()
        page = c.get(f"/admin?date={day}").body
        r_off = c.get(f"/api/schedule/live?date={day}")
        data = _j(r_off)["data"]
        if not res.check("ЯКОРЬ: с выключенным флагом всё по-прежнему",
                         ('id="live"' in page, 'data-reload="12"' in page,
                          'id="root"' in page, data["live"],
                          sorted(k for k in data if k not in ("screen", "date", "live"))),
                         (True, True, False, True,
                          ["actions", "agenda", "canvas", "minical", "note_actions",
                    "note_ends", "occupancy", "slotform", "tiles"])):
            return
        # ⭐ Вторая половина отката (C26.5.2). Вкладка, открытая React-ом,
        # узнаёт о ВЫКЛЮЧЕНИИ флага единственным способом, который у неё есть:
        # канал говорит, что по этому адресу теперь живёт другая поверхность.
        # Прямая половина — 205 старой вкладке на ВКЛЮЧЕНИЕ флага — ниже.
        res.check("с выключенным флагом канал называет поверхность «legacy»",
                  r_off.header("X-DP-Surface"), "legacy")
        # день в обоих профилях пустой и одинаковый — сравнение ниже про то,
        # что от ФЛАГА состояние не зависит, а не про содержимое дня
        body_off, hash_off = r_off.body, r_off.header("X-DP-Hash")
        # ⚠️ Час снимаем ЗДЕСЬ: сравнение ниже идёт уже на ДРУГОМ сервере,
        # а между ними — подъём второго процесса. Текущий час лежит в теле
        # конверта законно (canvas: "now": h == nh), поэтому смена часа
        # между снимками меняет тело на исправном коде (D0b, 20.09).
        hour_off = datetime.now(TZ).hour

    s2 = Server()
    cfg = json.loads(s2.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["schedule_dash"]}
    s2.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    with s2:
        c2 = Client(s2.url).login()
        page2 = c2.get(f"/admin?date={day}").body
        res.check("с флагом — узел React, и панель БОЛЬШЕ НЕ ЖИВАЯ",
                  ('<div id="root" data-screen="schedule_dash"' in page2,
                   'id="live"' in page2, 'data-reload="12"' in page2),
                  (True, False, False))
        params = json.loads(page2.split('data-params="', 1)[1].split('"', 1)[0]
                            .replace("&quot;", '"'))
        res.check("дата уехала параметром узла", params["date"], day)
        # ⛔ А `?msg=` — НЕ параметром узла (переписано в C26.5.2). Прежняя
        # проверка сверяла `data-params["msg"]` и была зелена по неверной
        # причине: сервер параметр честно клал, а читать его в клиенте было
        # некому — отказ в правах оставался молчаливым переходом на панель.
        # Теперь баннер печатает СЕРВЕР снаружи узла, и виден он при ПЕРВОЙ
        # отрисовке.
        deny = c2.get("/admin?msg=no_access").body
        res.check("отказ в правах виден СРАЗУ, и его печатает сервер",
                  ("rezervată directorului" in deny, '"msg"' in deny,
                   '<div id="root" data-screen="schedule_dash"' in deny),
                  (True, False, True))
        # ⭐ B1: шапку дня печатает ЭКРАН, а не сервер. Проверяется ПАРОЙ —
        # ссылки на неделю в серверном HTML больше нет, а подпись дня, без
        # которой экран шапку не нарисует, приехала параметром узла и готова
        # к ПЕРВОЙ отрисовке. Одной половины мало: «сервер не печатает» само по
        # себе зеленело бы и на экране, потерявшем шапку совсем.
        # ⛔ Подпись НЕ в модели канала намеренно: оттуда она приходила бы
        # вторым кругом, и шапка мигала бы на каждом переходе по дате.
        # ⛔ Поля выбора даты в шапке нет с 24.09: день выбирают в
        # мини-календаре правой колонки, а третья запись даты съедала ширину,
        # из-за которой шапка не вставала в ряд с заголовком на 1366.
        res.check("шапка дня уехала к экрану, подпись готова к первой отрисовке",
                  (f"/admin/week?date={day}" in page2,
                   params["day_label"].endswith("." + day[:4]),
                   "class='dpickf'" in page2),
                  (False, True, False))

        # --- канал НЕ СПРАШИВАЕТ, кто рисует экран (C26.5.2) ---
        # ⛔ До 19.09 он отвечал здесь `live:false` и пустотой — то есть
        # отнимал состояние ровно у того клиента, ради которого делался, а
        # старая вкладка этого ответа не видела никогда (она опрашивает адрес
        # СТРАНИЦЫ и получает 205 ниже). Теперь состояние одно и то же при
        # любом флаге, а поверхность едет заголовком.
        r_on = c2.get(f"/api/schedule/live?date={day}")
        live = _j(r_on)["data"]
        res.check("с включённым флагом канал везёт состояние ЦЕЛИКОМ",
                  (live["live"], live["screen"], live["date"],
                   sorted(k for k in live if k not in ("screen", "date", "live"))),
                  (True, "panel", day,
                   ["actions", "agenda", "canvas", "minical", "note_actions",
                    "note_ends", "occupancy", "slotform", "tiles"]))
        res.check("а поверхность отвечает ЗАГОЛОВКОМ, и это «react»",
                  r_on.header("X-DP-Surface"), "react")
        # ⛔ Отпечаток от флага не зависит. Течь поверхности в `data` — это
        # перерисовка панели за чужое действие: директор включил флаг на
        # соседнем рабочем месте, и день, в котором не изменилось ничего,
        # приехал бы как изменившийся.
        r_leg = c2.get(f"/api/schedule/live?date={day}&ui=legacy")
        res.check("?ui=legacy НА КАНАЛЕ не меняет ни тела, ни отпечатка",
                  (r_leg.body == r_on.body,
                   r_leg.header("X-DP-Hash") == r_on.header("X-DP-Hash")),
                  (True, True))
        # ⛔ Час мог смениться между снимками — тогда тело разошлось ЗАКОННО,
        # и требовать совпадения значит краснеть на исправном коде (D0b).
        # ⛔ Ретрая тут нет и быть не должно: проверка стоит ради настоящей
        # потери детерминизма (мигание панели, C26.5.2), а ретрай замаскировал
        # бы именно её. Поэтому — пропуск, и обязательно ВСЛУХ: метку
        # прошедшей проверки прогон не печатает, и молчаливый пропуск стал бы
        # ложным зелёным.
        if datetime.now(TZ).hour != hour_off:
            print("    \u26a0\ufe0f  между снимками сменился час: сверка тела и "
                  "отпечатка пропущена (D0b)")
            res.ok("ОДИН И ТОТ ЖЕ день при разных флагах — час сменился, "
                   "сверка пропущена", True, "")
        else:
            res.check("ОДИН И ТОТ ЖЕ день при разных флагах — один отпечаток",
                      (r_on.body == body_off,
                       r_on.header("X-DP-Hash") == hash_off),
                      (True, True))
        # ⭐ Вторая половина отката: заголовок едет и на 204, поэтому вкладка
        # узнаёт «здесь больше не моя поверхность» даже в тихий день, когда
        # тела нет вовсе. Поле в `data` на 204 не приехало бы никогда.
        same = c2.get(f"/api/schedule/live?date={day}",
                      headers={"X-DP-Hash": r_on.header("X-DP-Hash")})
        res.check("на 204 поверхность тоже приезжает",
                  (same.status, same.header("X-DP-Surface")), (204, "react"))

        # --- старая вкладка узнаёт об этом и перерисовывается ---
        poll = c2.get(f"/admin?date={day}", headers={"X-DP-Live": "1"})
        res.check("ОПРОС старой вкладки на панели → 205, а не документ",
                  (poll.status, poll.body.strip()), (205, ""))

        # --- откат мгновенный ---
        back = c2.get(f"/admin?date={day}&ui=legacy").body
        res.check("?ui=legacy возвращает СТАРУЮ панель, и она снова живая",
                  ('id="root"' in back, 'id="live"' in back,
                   "Agenda zilei" in back), (False, True, True))

        # --- соседние экраны флаг панели не задевает ---
        allp = c2.get(f"/admin/all?date={day}").body
        res.check("флаг панели не трогает день: он остался старым и живым",
                  ('id="root"' in allp, 'id="live"' in allp), (False, True))

        # --- граница владения с panel.js (C26.5.3-f) ---
        # ⛔ Экранные куски скрипта ищут узлы сетки по классам и атрибутам — и
        # находят React-овские. Перенос до этого шага молчал ПО СЛУЧАЙНОСТИ: у
        # React-панели нет узла `movedlg`, и выход стоял на нём. Случайность
        # снята охраной — а охрана обязана читать УЖЕ ПОСЧИТАННОЕ значение:
        # `var` поднимается, значение нет, и охрана ВЫШЕ объявления прочитала бы
        # `undefined`. Выглядела бы написанной и не работала.
        js = c2.get("/static/js/panel.js").body
        anchors = ("var dlg = document.getElementById('movedlg')",
                   "function markFresh() {", "function placeNowline() {",
                   "function paintWaits() {")
        # ⭐ Список с ВКЛЮЧАЮЩЕЙ полярностью: он ПЕРЕЧИСЛЯЕТ куски, и
        # переименуй кто-нибудь `placeNowline` — правило искало бы
        # несуществующее имя, нашло бы ноль нарушителей и позеленело навсегда.
        # Поэтому сперва проверяется, что имена ещё есть (прайор о полярности).
        res.check("ЯКОРЬ: экранные куски panel.js на месте — список не протух",
                  [a for a in anchors if a not in js], [])
        decl = js.find("var DP_REACT")
        guards = [m.start() for m in re.finditer(r"if \(DP_REACT\) return;", js)]
        naked = [a for a in anchors if "if (DP_REACT) return;"
                 not in js[max(0, js.find(a) - 300):js.find(a) + 300]]
        res.check("каждый экранный кусок под охраной, и объявление ВЫШЕ охран",
                  (naked, decl >= 0, bool(guards), all(g > decl for g in guards)),
                  ([], True, True, True))

def _shell_of(page: str) -> dict:
    """Модель оболочки со страницы; `{}` — её на узле нет.

    ⚠️ Пустой словарь, а не исключение: страница со СТАРОЙ оболочкой — это
    ровно то, что сторож ловит, и падение набора назвало бы её «IndexError»
    вместо «модели нет». Проверено парой: возврат одной поверхности на `_shell`
    красит проверку, а не роняет набор.
    """
    if 'data-shell="' not in page:
        return {}
    return json.loads(page.split('data-shell="', 1)[1].split('"', 1)[0]
                      .replace("&quot;", '"'))


def suite_live_shell(res: Result) -> None:
    """Четыре живых экрана на ОБЩЕЙ оболочке React (B1, последняя вертикаль).

    ⭐ Проверки СТРУКТУРНЫЕ, а не по литералу разметки: узел, модель оболочки,
    её значения — и отрицательная половина, что серверного каркаса на странице
    больше нет. Литерал ломался бы от любого нового атрибута узла, и это уже
    случилось: появление `data-shell` покрасило шесть проверок в пяти наборах.

    ⛔ Отрицательная половина обязательна. «Узел с моделью есть» зеленело бы и
    на странице, где оболочку печатают ОБА — а это ровно то, что B1 исключает.
    """
    day = clinic_today().isoformat()
    srv = Server()
    cfg = json.loads(srv.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["schedule_dash", "schedule_week", "schedule_all",
                           "schedule_doctor"]}
    srv.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    dk = next(d["id"] for d in cfg["doctors"] if d.get("status") != "arhivat")
    with srv:
        c = Client(srv.url).login()
        want = {"/admin": ("schedule_dash", "dash"),
                "/admin/week": ("schedule_week", "dash"),
                "/admin/all": ("schedule_all", "prog"),
                f"/admin/doctor/{dk}": ("schedule_doctor", "prog")}
        for path, (screen, active) in want.items():
            page = c.get(f"{path}?date={day}").body
            shell = _shell_of(page)
            res.check(f"{path}: узел экрана и модель оболочки на нём",
                      (f'<div id="root" data-screen="{screen}"' in page,
                       shell.get("nav", {}).get("active"),
                       bool(shell.get("frame", {}).get("sub"))),
                      (True, active, True))
            # ⚠️ `panel.js` ищется ТЕГОМ, а не именем: имя встречается в
            # пояснении к скрипту анимаций, которое печатает голова документа,
            # и проверка по имени краснела бы на исправном коде (прайор о
            # ложном красном стенде — поймано этим же стендом 24.09).
            res.check(f"{path}: серверного каркаса нет",
                      ('<aside class="side' in page, '<div class="top"' in page,
                       "<h1><a href=" in page, 'src="/static/js/panel.js' in page),
                      (False, False, False, False))


def suite_free_day_owner(res: Result) -> None:
    """«Zi liberă» — ОДИН владелец (исправление 24.09, найдено при переносе).

    Фраза печаталась ДВАЖДЫ: баннером сервера по `eng.hours_for` (только
    график) и холстом React по `hours_of` (график И записи). Условия разные,
    поэтому в закрытом дне с уцелевшей записью баннер сообщал «clinica este
    închisă» прямо над нарисованной записью.

    ⛔ Фикстура с ЗАКРЫТЫМ днём обязательна: у `clinic_test.json` открыты все
    семь дней, и дубль на ней не воспроизводится вовсе — проверка зеленела бы,
    ничего не проверив. `clinic_panel.json` закрывает воскресенье (`sun: null`).
    """
    srv = Server(clinic="clinic_panel.json")
    cfg = json.loads(srv.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["schedule_dash"]}
    srv.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    with srv:
        c = Client(srv.url).login()
        d = clinic_today()
        sun = d + timedelta(days=(6 - d.weekday()) % 7 or 7)
        page = c.get(f"/admin?date={sun.isoformat()}").body
        res.check("закрытый день: сервер фразу больше НЕ печатает",
                  page.count("Zi liber"), 0)
        # ⚠️ И вторая половина пары: владелец, который остался, эту фразу
        # действительно скажет — модель холста объявляет день пустым. Без неё
        # проверка выше зеленела бы и на экране, потерявшем сообщение совсем.
        cv = _j(c.get(f"/api/schedule/canvas?date={sun.isoformat()}"))["data"]
        res.check("а холст закрытый день видит и объявляет пустым",
                  (cv["empty"], cv["hours"]), (True, []))


def suite_panel_cmds(res: Result) -> None:
    """`screen=panel` у СОЗДАЮЩИХ команд: ни удача, ни отказ не несут состояния.

    ⛔ Написано ПЕРВЫМ шагом `e`, до клиента, и причина механическая: **FastAPI
    молча игнорирует неизвестный параметр строки запроса.** Маршрут, который
    `screen` не объявил, на `?screen=panel` отвечает ПОЛНОЙ моделью дня — у
    которой ДРУГОЙ ключ колонки, чем у канвы, — и не говорит об этом ничем: ни
    отказом, ни предупреждением. Увидеть такую дыру можно только тогда, когда
    клиент однажды начнёт это состояние читать, то есть у клиники.
    ⚠️ Контраст с дневным вызовом обязателен в каждой паре: без него проверка
    зелена и у маршрута, который данных не отдаёт НИКОМУ, а день на них живёт.
    ⭐ Здесь же пинится `part_note`: частичная блокировка — это УДАЧА (200), и
    приезжает она КОДОМ, а слово к коду подбирает `MSG_BANNER`, не клиент.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = clinic_today().isoformat()
        base = {"date": day, "doctor": "d2", "service": "consult",
                "nophone": False, "birth": ""}

        def add(hh: str, nm: str, phone: str, panel: bool):
            q = f"?screen=panel&date={day}" if panel else f"?date={day}"
            return c.post_json(f"/api/schedule/appointments{q}",
                               {**base, "time": hh, "name": nm, "phone": phone})

        def note(hh: str, txt: str, until: int, panel: bool):
            q = f"?screen=panel&date={day}" if panel else f"?date={day}"
            return c.post_json(f"/api/schedule/notes{q}",
                               {"date": day, "time": hh, "doctor": "d2",
                                "text": txt, "until": until})

        ok_panel = add("09:00", "Panel Unu", "069800101", True)
        ok_day = add("10:00", "Panel Doi", "069800102", False)
        if not res.check("запись: панели — код без состояния, дню — свежий день",
                         (ok_panel.status, _j(ok_panel)["code"],
                          "data" in _j(ok_panel),
                          ok_day.status, "data" in _j(ok_day)),
                         (200, "ok", False, 200, True)):
            return

        busy = add("09:00", "Panel Trei", "069800103", True)
        res.check("отказ записи — 409, JSON, и тоже без состояния",
                  (busy.status, _j(busy)["code"], "data" in _j(busy),
                   _j(busy)["ok"]),
                  (409, "conflict", False, False))

        n_panel = note("12:00", "Pauză de masă", 13, True)
        n_day = note("14:00", "Ședință", 15, False)
        res.check("заметка: панели — код без состояния, дню — свежий день",
                  (n_panel.status, _j(n_panel)["code"], "data" in _j(n_panel),
                   n_day.status, "data" in _j(n_day)),
                  (200, "ok_note", False, 200, True))

        # 10:00 занят визитом, 11:00 свободен: часть легла, часть нет
        part = note("10:00", "Blocare parțială", 12, True)
        res.check("⭐ `part_note` — это УДАЧА, и она приезжает КОДОМ",
                  (part.status, _j(part)["code"], "data" in _j(part),
                   _j(part)["ok"]),
                  (200, "part_note", False, True))

        clash = note("09:00", "Peste tot ocupat", 10, True)
        res.check("отказ заметки — 409 и без состояния, поле отказа «text»",
                  (clash.status, _j(clash)["code"], "data" in _j(clash),
                   _j(clash).get("field")),
                  (409, "conflict", False, "text"))

        # --- перенос (C26.5.3-f): тот же договор у третьего маршрута ---
        rows = _j(c.get(f"/api/schedule/day?date={day}"))["data"]["list"]
        mid = next(r["id"] for r in rows if r["name"] == "Panel Doi")

        def move(hh: str, panel: bool):
            q = f"?screen=panel&date={day}" if panel else f"?date={day}"
            return c.post_json(f"/api/schedule/appointments/{mid}/move{q}",
                               {"date": day, "time": hh, "doctor": "d2"})

        mv_panel = move("15:00", True)
        mv_day = move("16:00", False)
        res.check("перенос: панели — код без состояния, дню — свежий день",
                  (mv_panel.status, _j(mv_panel)["code"], "data" in _j(mv_panel),
                   mv_day.status, "data" in _j(mv_day)),
                  (200, "ok_move", False, 200, True))

        # 09:00 занят другим визитом — правду говорит сервер, а не подсказка
        mv_busy = move("09:00", True)
        res.check("занятый час — отказ сервера, 409 и без состояния",
                  (mv_busy.status, _j(mv_busy)["code"], "data" in _j(mv_busy),
                   _j(mv_busy)["ok"]),
                  (409, "conflict", False, False))
