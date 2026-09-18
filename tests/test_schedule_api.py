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
        res.ok("и опрос ей больше не отвечает фрагментом",
               c.get(f"/admin/week?date={monday.isoformat()}",
                     headers={"X-DP-Live": "1"}).status != 200
               or 'id="root"' in c.get(f"/admin/week?date={monday.isoformat()}",
                                       headers={"X-DP-Live": "1"}).body,
               "неделя отвечает живым фрагментом, хотя в ней React")

        day = c.get("/admin").body
        res.check("ДЕНЬ при этом остался живым: ключ dash снимать рано",
                  ('id="live"' in day, 'data-reload="12"' in day), (True, True))
        res.ok("день по-прежнему старый, без узла React",
               'id="root"' not in day, "флаг недели задел день")

        res.ok("?ui=legacy возвращает старую неделю",
               "class='wcol'" in c.get("/admin/week?ui=legacy").body, "нет")
        res.check("без входа закрыта", Client(s.url).get("/admin/week").status, 303)
