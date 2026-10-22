"""JSON API журнала: неделя (C24), день «Programări» (C25), живой канал
панели (C27) и команды экранов.

Экраны журнала с 13.10 рисует только React: всё, что видит регистратура, —
ответы этих маршрутов. До снятия старых страниц здесь же сверялся JSON со
страницей поле за полем (паритет C24/C25); паритет стал буквальными
ожиданиями на известном засеве — сверка модели с самой собой не проверяла бы
ничего.

⚠️ Дни недели сверяются СПИСКОМ ДАТ, а не количеством: закрытый день исчезает
из недели, только если в нём нет записей, поэтому колонок 5, 6 или 7, и
«столько же колонок» — не доказательство совпадения.
"""
import json
import pathlib
import sys
from datetime import datetime, timedelta

from harness import (TG_ON, Client, Result, Server, add_appt, appt_id, clinic_today,
                     day_model, shell_model)

# правило сведения рисков (`core.risks`) проверяется и чистым вызовом
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

# Сокращения дней недели — те же, что у движка (`engine.RO_DOW`): подпись дня
# в шапке «Jo 24.09.2026» строит сервер, и здесь она проверяется буквально.
_DOW = ("Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du")


def _j(r) -> dict:
    return json.loads(r.body)


def _label(day: str) -> str:
    """Подпись дня так, как её обязан построить сервер (`day.day_title`)."""
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return f"{_DOW[d.weekday()]} {d.strftime('%d.%m')}.{d.year}"


def _seed(c: Client, monday):
    """Неделя с записью, заметкой стойки, неявкой и отменой."""
    d = lambda i: (monday + timedelta(days=i)).isoformat()  # noqa: E731
    c.post_json("/api/schedule/appointments", {"date": d(1), "time": "09:00", "doctor": "d2",
                                              "service": "consult", "name": "Ion Popa",
                                              "phone": "069120120"})
    c.post_json("/api/schedule/appointments", {"date": d(1), "time": "10:30", "doctor": "d3",
                                              "service": "pain", "name": "Maria Rusu",
                                              "phone": "069120121"})
    c.post_json("/api/schedule/notes", {"date": d(1), "time": "12:00", "doctor": "d2",
                                       "text": "Livrare materiale"})
    c.post_json("/api/schedule/appointments", {"date": d(3), "time": "16:00", "doctor": "d2",
                                              "service": "hygiene", "name": "Vasile Lupu",
                                              "phone": "069120122"})
    c.post_json(f"/api/schedule/appointments/{appt_id(c, d(1), 'Ion Popa')}/status",
                {"to": "noshow"})
    return d


def suite_api(res: Result) -> None:
    """Неделя данными: состав, дни, счётчики, чипы, цвета — и охрана маршрута."""
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
        res.check("диапазон словами — для шапки экрана", j["span"],
                  f"{monday.strftime('%d.%m')} – "
                  f"{(monday + timedelta(days=6)).strftime('%d.%m.%Y')}")
        # у фикстуры открыты все семь дней — колонок семь, по порядку
        res.check("дни: все семь, датами и по порядку",
                  [x["date"] for x in j["days"]], [d(i) for i in range(7)])
        res.check("счётчики дней — пациенты, без заметки",
                  [x["count"] for x in j["days"]], [0, 2, 0, 1, 0, 0, 0])
        res.check("подписи дней — сокращения по-румынски, с понедельника",
                  [x["label"] for x in j["days"]], list(_DOW))
        res.check("«сегодня» на будущей неделе не отмечено",
                  [x["today"] for x in j["days"]], [False] * 7)
        res.check("итог недели — сумма пациентов", j["total"], 3)

        tue = next(x for x in j["days"] if x["date"] == d(1))
        res.check("во вторнике три чипа: две записи и заметка",
                  [x["kind"] for x in tue["items"]], ["appt", "appt", "note"])
        res.check("чип записи: час, имя, услуга",
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
        res.check("неявка помечена",
                  [x["noshow"] for x in tue["items"] if x["kind"] == "appt"], [True, False])
        res.ok("цвет неявки — красный",
               next(x for x in tue["items"] if x.get("noshow"))["bg"] == "var(--red-soft)",
               "неявка не покраснела")

        # отмена: запись исчезает и из чипов, и из счётчика
        aid = next(x["id"] for x in tue["items"] if x["kind"] == "appt" and not x["noshow"])
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "cancelled"})
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


def _node_params(page: str) -> dict:
    if 'data-params="' not in page:
        return {}
    return json.loads(page.split('data-params="', 1)[1].split('"', 1)[0]
                      .replace("&quot;", '"'))


def suite_switch(res: Result) -> None:
    """Неделя — узел React с датой параметром, раздел «Programări».

    (До 13.10 здесь перебирались значения ключа `ui.react` и `?ui=legacy`:
    старой недели нет, а шагом 6 сняты и ключ, и ссылка.)
    """
    with Server() as s:
        c = Client(s.url).login()
        monday = clinic_today() + timedelta(days=7 - clinic_today().weekday())
        page = c.get(f"/admin/week?date={monday.isoformat()}").body
        res.ok("узел React на месте",
               '<div id="root" data-screen="schedule_week"' in page
               and "/static/js/bundle.js?v=" in page, "узла нет")
        res.check("дата экрана — параметром узла",
                  _node_params(page), {"date": monday.isoformat()})
        # ⭐ (06.10, Олег) Неделя — раздел «Programări»: его пункт меню
        # подсвечен, и страница называется его словом.
        shell = shell_model(page)
        res.check("неделя — раздел «Programări»",
                  (shell["nav"]["active"], shell["frame"]["title"]),
                  ("prog", "Programări"))
        res.check("без входа закрыта", Client(s.url).get("/admin/week").status, 303)


# --- C25: день «Programări» данными -----------------------------------------


def _seed_full(c: Client, day: str) -> None:
    """День, задевающий каждое правило дня: два врача, длинный визит, неявка,
    отмена и заметка стойки."""
    c.post_json("/api/schedule/appointments", {"date": day, "time": "09:00", "doctor": "d2",
                                              "service": "consult", "name": "Ion Popa",
                                              "phone": "069170170"})
    c.post_json("/api/schedule/appointments", {"date": day, "time": "10:00", "doctor": "d3",
                                              "service": "pain", "name": "Maria Rusu",
                                              "phone": "069170171"})
    c.post_json("/api/schedule/appointments", {"date": day, "time": "11:00", "doctor": "d2",
                                              "service": "long", "name": "Vasile Lupu",
                                              "phone": "069170172"})
    c.post_json("/api/schedule/appointments", {"date": day, "time": "12:30", "doctor": "d2",
                                              "service": "consult", "name": "Ana Gheorghiu",
                                              "phone": "069170173"})
    c.post_json("/api/schedule/notes", {"date": day, "time": "15:00", "doctor": "d2",
                                       "text": "Livrare materiale"})
    c.post_json(f"/api/schedule/appointments/{appt_id(c, day, 'Ion Popa')}/status",
                {"to": "noshow"})
    c.post_json(f"/api/schedule/appointments/{appt_id(c, day, 'Maria Rusu')}/status",
                {"to": "cancelled"})


def _blocks(canvas: dict) -> list:
    return [b for col in canvas["columns"] for b in col["blocks"]]


def suite_day_parity(res: Result) -> None:
    """День «Programări»: шапка, врачи, канва — у общего дня и у дня врача."""
    with Server() as s:
        res.check("без входа — 401",
                  Client(s.url).get("/api/schedule/day").status, 401)
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=3)).isoformat()
        _seed_full(c, day)
        m = day_model(c, day)

        res.check("врачи дня: активные справочника, с подписью",
                  [(x["id"], x["name"], x["spec"]) for x in m["doctors"]],
                  [("d2", "Dr. Activ Doi", "Chirurgie"), ("d3", "Dr. Activ Trei", "Igienă"),
                   ("d4", "Dr. Activ Patru", "Protetică")])
        # Шапка дня (06.10): React-экран «Programări» показывал голую ISO-дату —
        # подпись дня едет моделью, и сборка у неё одна (`day.day_title`).
        res.check("подпись дня — сокращение дня недели и полная дата",
                  m["day_label"], _label(day))
        # ⭐ (06.10) «Programări» рисует ТУ ЖЕ канву, что панель: у общего дня
        # канва модели дня обязана совпасть с канвой живого канала панели того
        # же дня — иначе два экрана одного дня снова заговорят разным видом.
        canvas_panel = _j(c.get(f"/api/schedule/live?screen=panel&date={day}"))["data"]["canvas"]
        res.ok("канва общего дня — та же, что у панели этого дня",
               m["canvas"] == canvas_panel,
               f"колонки {[x['id'] for x in m['canvas'].get('columns', [])]} против "
               f"{[x['id'] for x in canvas_panel.get('columns', [])]}")
        d2_ids = sorted(b["id"] for x in canvas_panel["columns"] if x["id"] == "d2"
                        for b in x["blocks"])
        one = day_model(c, day, doctor="d2")["canvas"]
        res.ok("у врача d2 в этом дне есть записи — иначе проверка ниже пустая",
               len(d2_ids) >= 2, f"{d2_ids}")
        res.check("у дня врача в канве — только его колонка, с его записями",
                  ([x["id"] for x in one["columns"]],
                   sorted(b["id"] for b in one["columns"][0]["blocks"]) if one["columns"] else []),
                  (["d2"], d2_ids))
        res.check("«Sursă» без бота не показывается", m["source_col"], False)

        blocks = _blocks(m["canvas"])
        noshow = next(b for b in blocks if b.get("status") == "noshow")
        res.check("неявка на канве — своим словом и красным",
                  (noshow["name"], noshow["status_label"], noshow["bg"]),
                  ("Ion Popa", "nu a venit", "var(--red-soft)"))
        note = next(b for b in blocks if b["kind"] == "note")
        res.check("заметка стойки — своим видом и текстом",
                  (note["kind"], note["text"]), ("note", "Livrare materiale"))
        res.check("отменённая запись не на канве, но в «Lista zilei» и в карточках",
                  ("Maria Rusu" in [b.get("name") for b in blocks],
                   [r["status"] for r in m["list"] if r["name"] == "Maria Rusu"],
                   str(appt_id(c, day, "Maria Rusu")) in m["cards"]),
                  (False, ["cancelled"], True))

        # --- день врача: тот же построитель, другие данные ---
        one_m = day_model(c, day, doctor="d2")
        res.check("день врача: один врач, и в его списке только его записи",
                  ([x["id"] for x in one_m["doctors"]],
                   sorted({r["doctor"] for r in one_m["list"]})),
                  (["d2"], ["Dr. Activ Doi"]))
        res.check("чужой врач — 404, а не пустая сетка",
                  c.get("/api/schedule/day?doctor=d999").status, 404)


def suite_day_source(res: Result) -> None:
    """«Sursă» в «Lista zilei» — по боту (06.10): у клиники с ботом колонка есть.

    ⚠️ Половина «без бота — нет» живёт в `suite_day_parity`; без этой
    половины флаг мог бы быть просто всегда ложным, и обе проверки молчали бы."""
    with Server(env=TG_ON) as s:
        c = Client(s.url).login()
        res.check("у клиники с ботом «Sursă» показывается",
                  _j(c.get("/api/schedule/day"))["data"].get("source_col"), True)


def suite_day_orphan(res: Result) -> None:
    """Легаси-строка без `doctor_id` (имя — живого врача) на дне ЭТОГО врача.

    ⚠️ Такую строку не создать через интерфейс: запись всегда пишет
    `doctor_id`. Поэтому она делается прямо в базе песочницы — это ровно то,
    что лежит у клиник, обновившихся с версий до v1.7.1.
    ⭐ День врача находит её по снимку имени (`routes._of_doctor`) и ставит
    СВОЕЙ колонкой-сиротой рядом с колонкой врача (06.10, канва): в колонку
    врача она не сливается, переносить её неоткуда — путь у неё один, relink.
    """
    import sqlite3
    with Server() as s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=4)).isoformat()
        c.post_json("/api/schedule/appointments", {"date": day, "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Legacy Pacient", "phone": "069180180"})
        c.post_json("/api/schedule/appointments", {"date": day, "time": "10:00",
                                                  "doctor": "d3", "service": "consult",
                                                  "name": "Nou Pacient", "phone": "069180181"})
        legacy = appt_id(c, day, "Legacy Pacient")
        con = sqlite3.connect(s.dir / "dental.db")
        con.execute("UPDATE appointments SET doctor_id = NULL WHERE id = ?", (legacy,))
        con.commit()
        con.close()

        one = day_model(c, day, doctor="d2")
        cols = [(x["id"], x["name"], [b["id"] for b in x["blocks"]])
                for x in one["canvas"]["columns"]]
        res.check("день врача: его колонка и рядом сирота с легаси-записью",
                  cols, [("d2", "Dr. Activ Doi", []), (None, "Dr. Activ Doi", [legacy])])
        res.check("и в «Lista zilei» врача она есть",
                  [r["id"] for r in one["list"]], [legacy])
        everyone = _blocks(day_model(c, day)["canvas"])
        res.check("на общем дне — ровно один раз, не задвоилась",
                  sum(1 for b in everyone if b["id"] == legacy), 1)
        res.check("из колонки-сироты переносить неоткуда — адреса у неё нет",
                  [b["movable"] for b in _blocks(one["canvas"]) if b["id"] == legacy],
                  [False])


def suite_day_switch(res: Result) -> None:
    """Дневные экраны — узел React с параметрами из адреса.

    (До 13.10 — при любом значении `ui.react` и с `?ui=legacy`; шагом 6 ключ и
    ссылка сняты.) Живой у журнала только канал панели (`/api/schedule/live`).
    """
    with Server() as s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=2)).isoformat()
        for path, screen, params in (
                (f"/admin/all?date={day}", "schedule_all", {"date": day}),
                (f"/admin/doctor/d2?date={day}", "schedule_doctor",
                 {"date": day, "dk": "d2"})):
            page = c.get(path).body
            res.ok(f"{path}: узел React",
                   f'<div id="root" data-screen="{screen}"' in page, "узла нет")
            res.check(f"{path}: параметры узла", _node_params(page), params)
        res.check("отбор «Lista zilei» — параметром узла, только известный",
                  (_node_params(c.get(f"/admin/all?date={day}&f=urg").body).get("f"),
                   "f" in _node_params(c.get(f"/admin/all?date={day}&f=nope").body)),
                  ("urg", False))
        res.check("чужой врач в адресе — на журнал",
                  c.get("/admin/doctor/d999").status, 307)
        res.check("без входа закрыта", Client(s.url).get("/admin/all").status, 303)


# ------------------------------------------- живой канал ДАННЫМИ (C27.1)


def suite_live_envelope(res: Result) -> None:
    """Конверт живого канала: `GET /api/schedule/live`.

    ⛔ Главное свойство живого журнала — сервер умеет сказать «не менялось».
    У старого канала (опрос страницы, снят 13.10) это держалось ПОСТРОЕНИЕМ:
    `data-hash` обёртки и `X-DP-Hash` фрагмента считались от одной строки
    разметки. Здесь проверяется то же самое про ДАННЫЕ: отпечаток обязан
    считаться ОТ ТОГО ЖЕ, что уехало клиенту.

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
    (`test_api.suite_live_react`).
    """
    with Server() as s:
        c = Client(s.url).login()
        day = clinic_today().isoformat()
        for i, (hh, nm) in enumerate((("09:00", "Live Unu"), ("10:00", "Live Doi"),
                                      ("11:00", "Live Trei"))):
            c.post_json("/api/schedule/appointments", {"date": day, "time": hh, "doctor": "d2",
                                                      "service": "consult", "name": nm,
                                                      "phone": f"06980010{i}"})
        ids = {nm: appt_id(c, day, nm) for nm in ("Live Unu", "Live Doi", "Live Trei")}
        c.post_json(f"/api/schedule/appointments/{ids['Live Unu']}/status", {"to": "waiting"})
        for nm in ("Live Doi", "Live Trei"):
            c.post_json(f"/api/schedule/appointments/{ids[nm]}/status", {"to": "done"})
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
        if a.body != b.body:
            # ⚠️ Могли пересечь границу часа между запросами: подсветка
            # текущего часа дискретна и меняться ВПРАВЕ раз в час. Второй шанс
            # отличает редкий переход от настоящего недетерминизма.
            a, b = c.get(url), c.get(url)
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
        # ⛔ Заголовка поверхности больше нет (13.10): старой панели нет, и
        # спрашивать «кто рисует экран» некому. Вернись он со значением
        # «legacy» у профиля `ui.react: []` — React-панель перезагружалась бы
        # по кругу (`nextLive` › reload).
        res.check("заголовка поверхности нет ни на 200, ни на 204",
                  (a.header("X-DP-Surface"), same.header("X-DP-Surface")), ("", ""))

        # --- 4. изменение двигает ИМЕННО относящееся ---
        c.post_json("/api/schedule/appointments", {"date": day, "time": "14:00",
                                                  "doctor": "d3", "service": "consult",
                                                  "name": "Live Nou", "phone": "069800199"})
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
        aid = ids["Live Unu"]
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
        c.post_json("/api/schedule/notes", {"date": day, "time": "15:00", "doctor": "d3",
                                           "text": note_txt})
        nb = next(b for col in _j(c.get(url))["data"]["canvas"]["columns"]
                  for b in col["blocks"] if b.get("kind") == "note")
        # ⚠️ 120 — потолок САМОЙ заметки (`_add_note`), а не показа: полным
        # считается то, что легло в базу, и сравнивать надо с ним.
        res.check("у заметки в конверте ПОЛНЫЙ текст, а обрезки — рядом и с "
                  "другими именами",
                  (nb["text"], len(nb["title"]), len(nb["label"])),
                  (note_txt[:120], 80, 40))

        # --- 4b. то, чем живут диалоги (C26.5.3-a) ---
        env = _j(c.get(url))["data"]
        res.check("диалог собирается из КОНВЕРТА: кнопки, концы заметки, форма",
                  (sorted(env["actions"]), "cancelled" in env["note_actions"],
                   sorted(env["slotform"]),
                   all(isinstance(x, int) for x in env["note_ends"])),
                  (sorted(env["actions"]), True, ["birth_max", "services", "sms"], True))
        # ⛔ Потолок даты рождения — СЕГОДНЯ В ЧАСАХ КЛИНИКИ. Считанный от
        # `date.today()`, он переворачивал бы отпечаток в полночь по часам
        # машины и расходился бы под `TZ=UTC0` с остальной моделью.
        res.check("потолок даты рождения — сегодня КЛИНИКИ, а не машины",
                  env["slotform"]["birth_max"], clinic_today().isoformat())
        # --- 4c. заметка: состояние в блоке, и им ИНДЕКСИРУЕТСЯ матрица (d) ---
        # ⛔ Без состояния в блоке клиенту пришлось бы считать заметку
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
        # перерисовку, в которой на экране не меняется ничего.
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "cancelled"})
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
        res.check("кривая дата молча открывает сегодняшний день",
                  (bad.status, _j(bad)["data"]["date"]), (200, clinic_today().isoformat()))
        res.check("неизвестный экран отбивается с полем, а не молча пустотой",
                  (c.get("/api/schedule/live?screen=nope").status,
                   _j(c.get("/api/schedule/live?screen=nope")).get("field")),
                  (422, "screen"))

        # --- 7. адрес без даты — «сегодня сервера» на КАЖДЫЙ запрос (24.09) ---
        # ⭐ React-панель опрашивает адрес без даты КАК ЕСТЬ, и в полночь новый
        # день приезжает сюда же одним ответом: эхо даты и подпись этого дня
        # вместе. До 24.09 клиент подставлял день из узла, то есть момент
        # загрузки, и вкладка, оставленная на ночь, утром показывала вчера.
        # ⚠️ «Сегодня» теста и сервера сравниваются окном: запрос, попавший на
        # полночь, законно отвечает любым из двух дней.
        before = clinic_today().isoformat()
        bare = _j(c.get("/api/schedule/live?screen=panel"))["data"]
        after = clinic_today().isoformat()
        res.check("без даты — сегодняшний день клиники и подпись ЭТОГО дня",
                  (bare["date"] in (before, after), bare["day_label"] == _label(bare["date"])),
                  (True, True))
        # ⛔ И подпись идёт за ЭХОМ, а не за часами: собери её от `now` — и
        # оба «сегодняшних» случая выше зеленели бы, а панель любого другого
        # дня называла бы себя сегодняшним.
        other = (clinic_today() + timedelta(days=9)).isoformat()
        far = _j(c.get(f"/api/schedule/live?date={other}"))["data"]
        res.check("подпись другого дня — его собственная",
                  (far["date"], far["day_label"], far["day_label"] != bare["day_label"]),
                  (other, _label(other), True))


def suite_dash_flag(res: Result) -> None:
    """Панель дня — узел React; канал не спрашивает, кто рисует.

    ⭐ До 13.10 здесь проверялись обе половины отката (C26.5.1–2): 205 старой
    вкладке на включение флага и заголовок `X-DP-Surface` React-вкладке на
    выключение. Старой панели больше нет, ключ `ui.react` снят шагом 6, а
    заголовка поверхности нет вовсе. ⛔ Его отсутствие проверяется: с
    заголовком «legacy» React-панель перезагружалась бы по кругу.
    """
    day = clinic_today().isoformat()
    keys = ["actions", "agenda", "canvas", "day_label", "day_long", "desk",
            "minical", "note_actions", "note_ends", "occupancy", "slotform"]
    with Server() as s:
        c = Client(s.url).login()
        page = c.get(f"/admin?date={day}").body
        res.check("узел React панели",
                  '<div id="root" data-screen="schedule_dash"' in page, True)
        # ⛔ Дня в узле НЕТ — ни даты, ни подписи (24.09, решение Олега).
        # Узел описывает ДОКУМЕНТ, то есть момент загрузки, и день из него
        # застывал: вкладка, оставленная на ночь, утром показывала вчера.
        # Экран берёт день из адреса, шапку — из эха канала.
        res.check("в узле панели нет дня — ни даты, ни подписи",
                  ("date" in _node_params(page), "day_label" in _node_params(page)),
                  (False, False))
        r = c.get(f"/api/schedule/live?date={day}")
        live = _j(r)["data"]
        res.check("канал везёт состояние ЦЕЛИКОМ",
                  (live["live"], live["screen"], live["date"],
                   sorted(k for k in live if k not in ("screen", "date", "live"))),
                  (True, "panel", day, keys))
        res.check("и не называет поверхность", r.header("X-DP-Surface"), "")
        # ⛔ А `?msg=` — НЕ параметром узла (C26.5.2): баннер едет моделью
        # оболочки и виден при ПЕРВОЙ отрисовке, первого ответа канала не
        # ждёт. На `/admin` приземляется отказ в правах со всей программы.
        deny = c.get("/admin?msg=no_access").body
        res.check("отказ в правах виден СРАЗУ, его печатает сервер",
                  ("rezervată directorului" in shell_model(deny)["frame"]["msg"],
                   "msg" in _node_params(deny)),
                  (True, False))
    # Загрузка кресел — подзаголовок панели: одно число, без тренда к вчера
    # (тренд и мини-график жили на плитках «Azi», снятых со старой панелью).
    with Server() as s:
        c = Client(s.url).login()
        tomorrow = (clinic_today() + timedelta(days=1)).isoformat()
        c.post_json("/api/schedule/appointments", {"date": tomorrow, "time": "09:00",
                                                  "doctor": "d2", "service": "long",
                                                  "name": "Ocupat Lung", "phone": "069800300"})
        # 120′ из 3 активных врачей × 14 рабочих часов (07–21) = 120/2520 ≈ 5%
        res.check("загрузка кресел дня — одно число по активным врачам",
                  _j(c.get(f"/api/schedule/live?date={tomorrow}"))["data"]["occupancy"],
                  {"value": 5})


def suite_live_shell(res: Result) -> None:
    """Четыре экрана журнала на ОБЩЕЙ оболочке React (B1, последняя вертикаль).

    ⭐ Проверки СТРУКТУРНЫЕ, а не по литералу разметки: узел, модель оболочки,
    её значения — и отрицательная половина, что серверного каркаса на странице
    больше нет. Литерал ломался бы от любого нового атрибута узла.

    ⛔ Отрицательная половина обязательна. «Узел с моделью есть» зеленело бы и
    на странице, где оболочку печатают ОБА — а это ровно то, что B1 исключает.
    """
    day = clinic_today().isoformat()
    with Server() as srv:
        cfg = json.loads(srv.clinic.read_text(encoding="utf-8"))
        dk = next(d["id"] for d in cfg["doctors"] if d.get("status") != "arhivat")
        c = Client(srv.url).login()
        # ⭐ С 06.10 неделя — раздел «Programări» (`prog`), а не панель.
        # ⭐ С 08.10 панели и дню (промпт 2) сервер отдаёт ПУСТОЙ подзаголовок:
        # дату словами и сводку печатает сам экран из конверта (`day_long`),
        # двух подписей в одной области шапки не бывает. У недели подпись
        # сервера.
        want = {"/admin": ("schedule_dash", "dash", False),
                "/admin/week": ("schedule_week", "prog", True),
                "/admin/all": ("schedule_all", "prog", False),
                f"/admin/doctor/{dk}": ("schedule_doctor", "prog", False)}
        for path, (screen, active, has_sub) in want.items():
            page = c.get(f"{path}?date={day}").body
            shell = shell_model(page)
            res.check(f"{path}: узел экрана и модель оболочки на нём",
                      (f'<div id="root" data-screen="{screen}"' in page,
                       shell.get("nav", {}).get("active"),
                       bool(shell.get("frame", {}).get("sub"))),
                      (True, active, has_sub))
            # ⚠️ `panel.js` ищется ТЕГОМ, а не именем: имя встречается в
            # пояснении к скрипту анимаций, которое печатает голова документа,
            # и проверка по имени краснела бы на исправном коде (прайор о
            # ложном красном стенде — поймано этим же стендом 24.09).
            res.check(f"{path}: серверного каркаса нет",
                      ('<aside class="side' in page, '<div class="top"' in page,
                       "<h1>" in page, 'src="/static/js/panel.js' in page),
                      (False, False, False, False))


def suite_free_day_owner(res: Result) -> None:
    """«Zi liberă» — ОДИН владелец (исправление 24.09, найдено при переносе).

    Фраза печаталась ДВАЖДЫ: баннером сервера по `eng.hours_for` (только
    график) и холстом React по `hours_of` (график И записи). Условия разные,
    поэтому в закрытом дне с уцелевшей записью баннер сообщал «clinica este
    închisă» прямо над нарисованной записью. (Баннер сервера жил на старой
    панели и ушёл 13.10 вместе с ней.)

    ⛔ Фикстура с ЗАКРЫТЫМ днём обязательна: у `clinic_test.json` открыты все
    семь дней, и дубль на ней не воспроизводится вовсе — проверка зеленела бы,
    ничего не проверив. `clinic_panel.json` закрывает воскресенье (`sun: null`).
    """
    with Server(clinic="clinic_panel.json") as srv:
        c = Client(srv.url).login()
        d = clinic_today()
        sun = d + timedelta(days=(6 - d.weekday()) % 7 or 7)
        page = c.get(f"/admin?date={sun.isoformat()}").body
        res.check("закрытый день: сервер фразу НЕ печатает",
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
        mid = appt_id(c, day, "Panel Doi")

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


def suite_status_edges(res: Result) -> None:
    """17.10 (посторонний разбор). Сервер принимал любое слово конвейера из
    любого состояния: «не пришёл» визиту на завтра, «ждёт в приёмной» тому, кто
    уже в кресле, смена статуса несуществующего визита — «успех». Теперь
    переход проверяется по ребру ТОЙ ЖЕ матрицы, что рисует кнопки
    (`visits.status_actions`), как у плана лечения; повтор статуса — тихий
    успех; визита нет — `mv_gone`."""
    with Server() as s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=2)).isoformat()
        for hh, nm in (("09:00", "Edge Unu"), ("10:00", "Edge Doi"), ("11:00", "Edge Trei")):
            c.post_json("/api/schedule/appointments",
                        {"date": day, "time": hh, "doctor": "d2", "service": "consult",
                         "name": nm, "phone": "0691" + hh.replace(":", "")})
        a1, a2, a3 = (appt_id(c, day, nm) for nm in ("Edge Unu", "Edge Doi", "Edge Trei"))

        def to(aid: int, st: str):
            r = c.post_json(f"/api/schedule/appointments/{aid}/status?screen=panel", {"to": st})
            return r.status, _j(r)["code"]

        def status_of(aid: int) -> str:
            return next(r["status"] for r in day_model(c, day)["list"] if r["id"] == aid)

        # матрица — та, что отдаётся клиенту: проверяем против неё, а не копии
        actions = day_model(c, day)["actions"]
        res.ok("матрица кнопок приехала", set(actions) >= {"confirmed", "waiting", "arrived",
                                                             "done", "noshow", "cancelled"},
               str(sorted(actions)))

        # programată → arrived (в кабинет) — есть ребро
        res.check("confirmed → arrived: ребро есть", to(a1, "arrived"), (200, ""))
        # из кресла назад в приёмную ребра нет; «не пришёл» тому, кто в кресле, — тоже
        res.check("arrived → waiting: ребра нет — 409 bad_step", to(a1, "waiting"), (409, "bad_step"))
        res.check("arrived → noshow: ребра нет", to(a1, "noshow"), (409, "bad_step"))
        res.check("статус не тронут", status_of(a1), "arrived")
        res.check("arrived → done: ребро есть", to(a1, "done"), (200, ""))
        # у закрытого — только возврат в programată
        res.check("done → noshow: ребра нет", to(a1, "noshow"), (409, "bad_step"))
        res.check("done → cancelled: ребра нет", to(a1, "cancelled"), (409, "bad_step"))
        res.check("done → confirmed (Redeschide): ребро есть", to(a1, "confirmed"), (200, ""))

        # повтор того же статуса — тихий успех, штамп прихода не двигается
        res.check("confirmed → waiting", to(a2, "waiting"), (200, ""))
        res.check("waiting → waiting: повтор — тихий успех", to(a2, "waiting"), (200, ""))
        res.check("повтор статус не переписал", status_of(a2), "waiting")

        # слово не из конвейера — 422, визита нет — 409 mv_gone (не «успех»)
        res.check("слово не из конвейера — 422 bad", to(a3, "nope"), (422, "bad"))
        res.check("визита нет — 409 mv_gone, а не успех", to(999999, "done"), (409, "mv_gone"))
        res.check("третий визит не тронут", status_of(a3), "confirmed")

        # заметка стойки — своя матрица: убрать и вернуть, исхода у неё нет
        c.post_json("/api/schedule/notes", {"date": day, "time": "14:00", "doctor": "d2",
                                           "text": "Edge notă"})
        nid = next(r["id"] for r in day_model(c, day)["list"] if r["is_note"])
        res.check("заметка → done: ребра нет", to(nid, "done"), (409, "bad_step"))
        res.check("заметка → cancelled (Șterge): ребро есть", to(nid, "cancelled"), (200, ""))
        res.check("заметка → confirmed (Restabilește): ребро есть", to(nid, "confirmed"), (200, ""))


def suite_service(res: Result) -> None:
    """Смена процедуры у стоящей записи (22.10, Олег 19.10: «сменить процедуру,
    не удаляя запись»; вторая услуга в одну запись — НЕ делается).

    Маршрут `POST /api/schedule/appointments/{id}/service` {service_id}: пишет
    ключ услуги, снимок подписи и снимок длительности; выросшая длительность
    проверяется по часам клиники и по соседу под `_slot_lock`; врач обязан
    делать услугу; закрытый визит и заметка стойки не меняются. Список услуг
    окна (`GET …/service`) — тем же правилом (`visits.service_refusal`); в
    карточке и в блоке канвы — только ключ и флаг `service_edit`: список в
    каждом блоке раздул бы каждый опрос главной.
    Засев клиники теста: d2 делает consult (60), pain (60), long (120), но не
    hygiene (только d3); клиника 7–21.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=2)).isoformat()
        for hh, nm in (("09:00", "Svc Unu"), ("10:00", "Svc Doi"), ("13:00", "Svc Trei"),
                       ("15:00", "Svc Patru"), ("20:00", "Svc Cinci")):
            add_appt(c, day, hh, nm, "0697" + hh.replace(":", ""))
        a1, a2, a3, a4, a5 = (appt_id(c, day, nm) for nm in (
            "Svc Unu", "Svc Doi", "Svc Trei", "Svc Patru", "Svc Cinci"))

        def svc(aid: int, sid: str, panel: bool = True):
            q = f"?screen=panel&date={day}" if panel else f"?date={day}"
            return c.post_json(f"/api/schedule/appointments/{aid}/service{q}",
                               {"service_id": sid})

        def row(aid: int) -> tuple:
            m = day_model(c, day)
            lst = next(r for r in m["list"] if r["id"] == aid)
            blk = next(b for col in m["canvas"]["columns"] for b in col["blocks"]
                       if b["id"] == aid)
            return lst["service"], m["cards"][str(aid)]["service_id"], blk["dur"]

        def feed(aid: int) -> list[str]:
            pid = day_model(c, day)["cards"][str(aid)]["pid"]
            return [a["text"] for a in _j(c.get(
                f"/api/patients/{pid}/activity?views=1"))["data"]["items"]]

        def opts(aid: int) -> tuple:
            r = c.get(f"/api/schedule/appointments/{aid}/service")
            d = _j(r).get("data") or {}
            return r.status, d.get("service_id"), [o["id"] for o in d.get("options", [])]

        m = day_model(c, day)
        blk1 = next(b for col in m["canvas"]["columns"] for b in col["blocks"] if b["id"] == a1)
        res.check("карточка и блок канвы: ключ процедуры и флаг, без списка",
                  ({k: m["cards"][str(a1)][k] for k in ("service_id", "service_edit")},
                   {k: blk1[k] for k in ("service_id", "service_edit")},
                   "service_opts" in blk1),
                  ({"service_id": "consult", "service_edit": True},
                   {"service_id": "consult", "service_edit": True}, False))
        res.check("GET …/service: услуги ЭТОГО врача, подписями (без hygiene d3)",
                  opts(a1), (200, "consult", ["consult", "pain", "long"]))
        res.check("GET …/service: визита нет — 409", opts(999999)[0], 409)

        # длинная упирается в соседа 10:00 — отказ, запись цела
        r = svc(a1, "long")
        res.check("09:00 → long (120) наезжает на 10:00 — 409 conflict, без состояния",
                  (r.status, r.msg, "data" in _j(r)), (409, "conflict", False))
        res.check("отказ: запись не тронута", row(a1), ("Consultație", "consult", 60))

        # длинная без соседа: 13:00–15:00, сосед ровно в 15:00 — не наезд
        r = svc(a3, "long", panel=False)
        res.check("13:00 → long — удача, дню свежий день",
                  (r.status, r.msg, "data" in _j(r)), (200, "ok_svc", True))
        res.check("сменены подпись, ключ и длительность", row(a3),
                  ("Tratament lung", "long", 120))
        res.ok("строка в летописи: было › стало",
               "Procedura schimbată: Consultație › Tratament lung" in feed(a3),
               str(feed(a3)[:3]))

        # короткая: 120 → 60 — проверки соседа нет, интервал сжался
        r = svc(a3, "pain")
        res.check("long → pain (короче) — удача, панели без состояния",
                  (r.status, r.msg, "data" in _j(r)), (200, "ok_svc", False))
        res.check("короткая: подпись, ключ, длительность", row(a3),
                  ("Durere acută", "pain", 60))

        # повтор той же услуги — тихий успех, летопись не пишется
        n = len(feed(a3))
        r = svc(a3, "pain")
        res.check("та же услуга — тихий успех", (r.status, r.msg), (200, ""))
        res.check("повтор летопись не пишет", len(feed(a3)), n)

        # услуга не этого врача
        r = svc(a1, "hygiene")
        res.check("hygiene (только d3) у d2 — 409 svc_doc", (r.status, r.msg), (409, "svc_doc"))
        r = svc(a1, "nope")
        res.check("неизвестная услуга — 422 bad", (r.status, r.msg), (422, "bad"))

        # 20:00 + 120 = 22:00 при закрытии в 21:00
        r = svc(a5, "long")
        res.check("20:00 → long не влезает в часы клиники — outside",
                  (r.status, r.msg), (422, "outside"))
        res.check("отказ часов: запись цела", row(a5), ("Consultație", "consult", 60))

        # «în cabinet» — активный визит, процедуру уточняют как раз у кресла
        c.post_json(f"/api/schedule/appointments/{a4}/status?screen=panel", {"to": "arrived"})
        r = svc(a4, "pain")
        res.check("«în cabinet» → pain — удача", (r.status, r.msg), (200, "ok_svc"))

        # закрытый визит
        c.post_json(f"/api/schedule/appointments/{a2}/status?screen=panel", {"to": "done"})
        res.check("закрытый: флаг снят, список пуст",
                  (day_model(c, day)["cards"][str(a2)]["service_edit"], opts(a2)[2]),
                  (False, []))
        r = svc(a2, "pain")
        res.check("закрытый — 409 svc_closed", (r.status, r.msg), (409, "svc_closed"))
        res.check("закрытый не тронут", row(a2), ("Consultație", "consult", 60))
        r = svc(999999, "pain")
        res.check("визита нет — 409 mv_gone", (r.status, r.msg), (409, "mv_gone"))

        # заметка стойки: в `service` у неё ТЕКСТ — не процедура
        c.post_json("/api/schedule/notes", {"date": day, "time": "17:00", "doctor": "d2",
                                           "text": "Livrare materiale"})
        nid = next(r["id"] for r in day_model(c, day)["list"] if r["is_note"])
        r = svc(nid, "pain")
        res.check("заметка — 422 bad", (r.status, r.msg), (422, "bad"))
        res.check("текст заметки цел",
                  next(r["service"] for r in day_model(c, day)["list"] if r["id"] == nid),
                  "Livrare materiale")

        # статистика считает по НОВОМУ ключу: consult бесплатна, long — 2000 MDL
        today = clinic_today().isoformat()
        add_appt(c, today, "07:00", "Svc Stat", "069707000")
        sid_ = appt_id(c, today, "Svc Stat")
        r = c.post_json(f"/api/schedule/appointments/{sid_}/service?screen=panel",
                        {"service_id": "long"})
        res.check("визит дня (07:00, обычно уже прошёл) → long — удача",
                  (r.status, r.msg), (200, "ok_svc"))
        st = _j(c.get(f"/api/stats?from={today}&to={today}"))["data"]["services"]
        res.check("статистика: услуга и цена — по новому ключу",
                  [(x["label"], x["cnt"], x["val_n"]) for x in st],
                  [("Tratament lung", 1, 2000)])


def suite_doctor_day(res: Result) -> None:
    """День ОДНОГО врача (22.10, вариант A + H Олега): факты карточки визита
    (`extras`) и календарь шапки (`minical`) — только у него.

    ⛔ Не в `appt_view` и не в `canvas.blocks`: те едут в каждом конверте
    живого канала главной, а канва общего дня обязана совпадать с ним
    (`suite_day_parity`). Здесь — что факты есть у дня врача и только там,
    что они буквальны на известном засеве (дубли atenționări и анамнеза
    сведены одним правилом `core.risks.merge`) и что в них нет «сейчас».
    Засев: d2 — Pavel (два прошлых визита, отмена и неявка, дневник у
    второго; риски, анамнез с дублями, план, долг 700 — чтобы было что не
    показать), Ana (новая, беременность и в фише, и галочкой), Vasile (анамнез
    не собран), заметка; d3 — Ion.
    ⛔ Денег в фактах нет (Олег 22.10, «не думаю что врачу эта информация
    нужна»): долг остаётся в фише и у статистики.
    """
    from app.core import risks
    from app.modules.patients import anamneza as panam

    # ⭐ Списки имён гниют молча (`_AUTH_WRITERS`): новая галочка анамнеза без
    # корней дублировалась бы в колонке, новое поле — пропало бы из неё.
    res.check("корни галочек — на каждую галочку анамнеза",
              sorted(risks.FLAG_ROOTS), sorted(panam.FLAGS["ro"]))
    res.check("порядок свободных полей — все поля анамнеза",
              sorted(risks.FREE_ORDER), sorted(k for k, *_ in panam.TEXTS))
    res.check("сведение без анамнеза — только atenționări",
              [x["text"] for x in risks.merge([{"kind": "allergy", "text": "Alergie: latex"}],
                                              None)],
              ["Alergie: latex"])
    res.check("«alergie la …» узнаётся по веществу, а не по слову «alergie»",
              [x["text"] for x in risks.merge(
                  [{"kind": "allergy", "text": "Alergie: penicilină"}],
                  {"flags": "", "alergii": "alergie la latex; Penicilina"})],
              ["Alergie: penicilină", "alergie la latex"])

    with Server() as s:
        c = Client(s.url).login()
        today = clinic_today()
        d0 = today + timedelta(days=3)
        day = d0.isoformat()
        # день того же месяца, где есть только чужой врач: точка у главной, не у d2
        other = (d0 - timedelta(days=1) if d0.day > 1 else d0 + timedelta(days=1)).isoformat()
        past = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
        tel = "069300300"
        add_appt(c, past(70), "09:00", "Pavel Moraru", tel)
        add_appt(c, past(40), "10:00", "Pavel Moraru", tel, service="pain")
        add_appt(c, past(30), "11:00", "Pavel Moraru", tel)
        add_appt(c, past(20), "11:00", "Pavel Moraru", tel)
        c.post_json(f"/api/schedule/appointments/{appt_id(c, past(30), 'Pavel Moraru')}/status",
                    {"to": "cancelled"})
        c.post_json(f"/api/schedule/appointments/{appt_id(c, past(20), 'Pavel Moraru')}/status",
                    {"to": "noshow"})
        r = c.post_json(f"/api/visits/{appt_id(c, past(40), 'Pavel Moraru')}",
                        {"tratament": "Extracție 46", "done": []})
        res.check("засев: дневник прошлого визита записан", r.msg, "ok_visit")
        add_appt(c, day, "09:00", "Pavel Moraru", tel, service="long")
        add_appt(c, day, "12:00", "Ana Nouă", "069300301")
        add_appt(c, day, "14:00", "Vasile Lupu", "069300302")
        add_appt(c, day, "10:00", "Ion Strain", "069300303", doctor="d3")
        add_appt(c, other, "10:00", "Ion Strain", "069300303", doctor="d3")
        c.post_json("/api/schedule/notes", {"date": day, "time": "16:00", "doctor": "d2",
                                           "text": "Livrare materiale"})
        blocks = {b["name"]: b for b in _blocks(day_model(c, day)["canvas"])
                  if b["kind"] == "appt"}
        pav, ana = blocks["Pavel Moraru"]["pid"], blocks["Ana Nouă"]["pid"]
        for kind, text in (("allergy", "Alergie: penicilină"),
                           ("medication", "Anticoagulant: Xarelto 20 mg")):
            c.post_json(f"/api/patients/{pav}/alerts", {"kind": kind, "text": text})
        c.post_json(f"/api/patients/{pav}/anamneza",
                    {"flags": ["cardio", "coagulare"], "boli": "", "anestezie": "",
                     "medicamente": "Xarelto 20 mg/zi, Concor 5 mg",
                     "alergii": "penicilină, latex"})
        c.post_json(f"/api/patients/{ana}/alerts",
                    {"kind": "warning", "text": "Sarcină, trimestrul II"})
        c.post_json(f"/api/patients/{ana}/anamneza", {"flags": ["sarcina"]})
        for tooth, proc, price in (("46", "Implant", "9500"), ("45", "Obturație compozit", "900"),
                                   ("36", "Tratament endodontic", "1200")):
            c.post_json(f"/api/patients/{pav}/plan", {"tooth": tooth, "procedure": proc,
                                                     "doctor": "Dr. Activ Doi", "price": price,
                                                     "due_date": ""})
        items = {it["procedure"]: it["id"] for it in
                 _j(c.get(f"/api/patients/{pav}"))["data"]["plan"]["items"]}
        endo = items["Tratament endodontic"]
        c.post_json(f"/api/patients/{pav}/plan/{items['Implant']}/status", {"to": "in_lucru"})
        c.post_json(f"/api/patients/{pav}/plan/{endo}/status", {"to": "in_lucru"})
        c.post_json(f"/api/patients/{pav}/plan/{endo}/status", {"to": "finalizat"})
        c.post_json(f"/api/patients/{pav}/payments", {"amount": "500", "method": "card", "note": ""})

        m = day_model(c, day, doctor="d2")
        ids = {b["name"]: str(b["id"]) for b in _blocks(m["canvas"]) if b["kind"] == "appt"}
        x = m.get("extras") or {}
        res.check("факты — у каждого визита дня врача с пациентом, без заметки и чужих",
                  sorted(x), sorted(ids[n] for n in ("Pavel Moraru", "Ana Nouă", "Vasile Lupu")))
        p = x.get(ids["Pavel Moraru"], {})
        res.check("Pavel: третий визит, прошлый — с графой «Tratament» дневника "
                  "(отмена и неявка — не визиты)",
                  (p.get("nth"), p.get("last")),
                  (3, {"date": past(40), "what": "Extracție 46"}))
        res.check("Pavel: риски без дублей — «Xarelto» и «penicilină» анамнеза и "
                  "галочка «coagulare» ушли, «Concor» и «latex» остались",
                  [(r_["text"], r_["tone"], r_["icon"]) for r_ in p.get("risks", [])],
                  [("Alergie: penicilină", "orange", "sos"),
                   ("Anticoagulant: Xarelto 20 mg", "orange", "pill"),
                   ("latex", "amber", "sos"), ("Concor 5 mg", "amber", "pill"),
                   ("Boli cardiovasculare", "amber", "")])
        res.check("подсказка свободного поля называет поле, галочки — полностью",
                  [r_["title"] for r_ in p.get("risks", [])][2:],
                  ["Alergii: latex", "Medicamente: Concor 5 mg",
                   "Boli cardiovasculare / hipertensiune"])
        res.check("Pavel: активный план с номерами зубов, «în lucru» отмечен; "
                  "финализированное — не план",
                  (p.get("plan"), p.get("anam")),
                  ([{"tooth": 46, "proc": "Implant", "work": True},
                    {"tooth": 45, "proc": "Obturație compozit", "work": False}], True))
        # ⛔ Пятёрка ключей, а не «нет debt»: деньги вернулись бы и под другим
        # именем (balance, sold), а у Pavel долг 700 есть — было бы что везти.
        res.check("денег в фактах нет (Олег 22.10): ни debt, ни ключа сверх пяти",
                  sorted({k for v in x.values() for k in v}),
                  ["anam", "last", "nth", "plan", "risks"])
        a = x.get(ids["Ana Nouă"], {})
        res.check("Ana: новая, «Sarcină» галочкой не дублирует atenționare",
                  (a.get("nth"), a.get("last"), [r_["text"] for r_ in a.get("risks", [])],
                   a.get("plan")),
                  (1, None, ["Sarcină, trimestrul II"], []))
        v = x.get(ids["Vasile Lupu"], {})
        res.check("Vasile: анамнез не собран — флагом, слово рисует экран",
                  (v.get("anam"), v.get("risks")), (False, []))
        res.ok("факты не зависят от момента запроса (ни одного «сейчас»)",
               day_model(c, day, doctor="d2")["extras"] == x)

        general = day_model(c, day)
        live = _j(c.get(f"/api/schedule/live?screen=panel&date={day}"))["data"]
        res.check("у общего дня и у живого канала фактов нет",
                  ("extras" in general, "extras" in live), (False, False))
        res.ok("блоки канвы фактов не несут (едут в каждый опрос главной)",
               not any(k in b for b in _blocks(live["canvas"]) for k in ("risks", "nth", "plan")),
               f"{sorted(_blocks(live['canvas'])[0])}")
        res.check("у общего дня календаря в модели нет (он у главной — в канале)",
                  "minical" in general, False)

        cal = m.get("minical") or {}
        cells = {c_["date"]: c_ for w in cal.get("weeks", []) for c_ in w}
        res.check("календарь врача: ссылки дня и месяца — на день этого врача",
                  (cells.get(day, {}).get("href"),
                   cal.get("next", {}).get("href", "").split("?")[0]),
                  (f"/admin/doctor/d2?date={day}", "/admin/doctor/d2"))
        live_busy = {c_["date"]: c_["busy"] for w in live["minical"]["weeks"] for c_ in w}
        res.check("точки — дни с записями ЭТОГО врача: свой день есть, день "
                  "одного d3 — только у главной",
                  (cells.get(day, {}).get("busy"), cells.get(other, {}).get("busy"),
                   live_busy.get(other)),
                  (True, False, True))
        res.check("выбранный день — день экрана", cells.get(day, {}).get("selected"), True)

        # ответ действия — свежий день экрана, с фактами (`_done`)
        r = c.post_json(f"/api/schedule/appointments/{ids['Vasile Lupu']}/comment"
                        f"?date={day}&doctor=d2", {"comment": "Sună înainte"})
        res.check("ответ действия на дне врача несёт факты",
                  (r.msg, sorted(_j(r).get("data", {}).get("extras", {}))),
                  ("ok_comment", sorted(x)))
