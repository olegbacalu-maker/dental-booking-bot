"""Канва дня: колонка-сирота, геометрия блоков, шапка врача, повестка и
мини-календарь панели (пины C26.2, с 13.10 — по модели).

Канву рисует только React (старая панель снята 13.10), и одна и та же канва
стоит на «Panoul principal» и на «Programări» (06.10). Наборы читают её
ДАННЫМИ — `GET /api/schedule/canvas` и живой канал панели
(`/api/schedule/live`), — то есть ровно то, что получает экран. До 13.10 здесь
же сверялась старая страница с моделью (паритет C26.4); паритет стал
буквальными ожиданиями на известном засеве: сверка модели с самой собой не
проверяла бы ничего.

⛔ **Сперва якорь, потом правило.** Каждый набор начинается с проверки, что в
фикстуре ВООБЩЕ есть предмет разговора. Правило C26 после находки `all([])`:
проверка над пустотой — не проверка. Сирота, у которого не оказалось колонки,
обязан краснеть на якоре, а не молча пройти шесть правил о своей колонке.

⚠️ **Сравнивается СМЫСЛ, а не снимок.** Ожидание считается из данных фикстуры
(«эти два визита пересекаются, значит делят ширину пополам»), а не списывается
с сегодняшнего ответа: снимок пережил бы любую подмену, которая сохранила
строки.
"""
import json
import re
import sqlite3
from datetime import datetime, timedelta

from harness import TZ, Client, Result, Server, clinic_today, day_model, panel_live


# ⚠️ Длиннее 80 намеренно: обе границы показа (80 и 40) обязаны быть
# РАЗНЫМИ на этом тексте, иначе пин перестанет их различать.
NOTE_LONG = ("Livrare materiale pentru cabinetul doi: freze, anestezic,"
             " manusi marimea M si doua truse de unica folosinta")


def _sql(s: Server, q: str, *args) -> None:
    """Правка ПРЯМО в базе песочницы.

    ⚠️ Так и только так: через интерфейс ни пересечения у одного врача
    (`db._conflicts` не даст), ни записи на врача, которого нет в справочнике,
    не создать. А у клиник, обновившихся с версий до v1.7.1, ровно такие
    строки и лежат — ради них канва и умеет и сирот, и кластеры. Тот же приём,
    что в `test_schedule_api.suite_day_orphan`.
    """
    con = sqlite3.connect(s.dir / "dental.db")
    con.execute(q, args)
    con.commit()
    con.close()


def _utc(day: str, hh: int, mm: int = 0) -> str:
    """Старт в том виде, в каком его хранит база: UTC, ISO с поясом.

    ⚠️ Кишинёв летом +3, и 09:00 у клиники — это 06:00 в базе. Ошибись здесь —
    визит уедет на три часа, а проверка будет ругаться на геометрию.
    """
    from datetime import timezone
    local = datetime(*(int(x) for x in day.split("-")), hh, mm, tzinfo=TZ)
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def _add(c: Client, day: str, hh: str, dk: str, name: str, i: int,
         svc: str = "consult") -> None:
    c.post_json("/api/schedule/appointments", {"date": day, "time": hh, "doctor": dk,
                                              "service": svc, "name": name,
                                              "phone": f"0691900{i:02d}"})


def _ids(c: Client, day: str) -> list[int]:
    """Номера строк «Lista zilei» дня — по времени, вместе с заметками и
    отменёнными (так их разбирал и прежний набор со страницы)."""
    return [r["id"] for r in day_model(c, day)["list"]]


def _canvas(c: Client, day: str) -> dict:
    """Канва дня глазами экрана. ⛔ Через настоящий маршрут `/api/`, а не
    прямым вызовом функции: иначе проверка не заметила бы ни охраны, ни
    конверта ответа — а клиент видит именно их."""
    r = c.get(f"/api/schedule/canvas?date={day}")
    assert r.status == 200, f"канва не отдана: {r.status}"
    return json.loads(r.body)["data"]


def _col(cv: dict, dk: str) -> dict:
    return next((x for x in cv["columns"] if x["id"] == dk), {})


def _hours(cv: dict) -> list[int]:
    return [h["h"] for h in cv["hours"]]


def _weekday_after(d, wd: int):
    """Ближайший (не раньше `d`) день недели `wd`: 0 — понедельник.

    ⚠️ Фикстура, привязанная к «сегодня плюс N», ездит по дням недели, а у
    клиники график по дням РАЗНЫЙ. Такой набор краснеет в один день недели из
    семи — и выглядит это как поломка последнего коммита.
    """
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


# --------------------------------------------------------- колонка-сирота


def suite_orphan(res: Result) -> None:
    """Врач, которого нет в справочнике: своя колонка, свои записи, relink.

    ⛔ Это ЕДИНСТВЕННОЕ место в программе, где видно записи выпавшего врача, и
    единственный вход в `POST /admin/relink`. Шапка врачей модели дня
    (`schedule/day.py`) про сирот не знает, поэтому канву на ней построить
    нельзя, а потеря колонки не покраснела бы нигде, кроме здесь.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        _add(c, day, "09:00", "d2", "Pacient Orfan", 1)
        _add(c, day, "10:00", "d2", "Pacient Viu", 2)
        _add(c, day, "11:00", "d2", "Pacient Tiz", 3)
        gone, alive, twin = _ids(c, day)
        # врач ушёл из справочника ПОСЛЕ визита: id нет, осталось имя-снимок
        _sql(s, "UPDATE appointments SET doctor_id = NULL, doctor = ?"
                " WHERE id = ?", "Dr. Plecat Demult", gone)
        # ⭐ ТЁЗКА: id нет, а имя — живого врача. Канва даёт ему СВОЮ колонку
        # рядом с колонкой d2: ключ колонки `n:` и `k:` — разные, даже когда
        # имя совпадает (`canvas.row_col`).
        _sql(s, "UPDATE appointments SET doctor_id = NULL WHERE id = ?", twin)
        cv = _canvas(c, day)

        # --- якорь: предмет разговора в фикстуре ЕСТЬ ---
        # активных врачей в справочнике трое, и колонка есть у каждого, даже
        # без записей; плюс две сиротские
        # ⛔ якорь ОСТАНАВЛИВАЕТ набор: без сиротской колонки шесть правил о
        # ней проверяли бы пустоту
        if not res.check("якорь: колонки активных врачей и ДВЕ сиротские",
                         ([x["id"] for x in cv["columns"] if x["id"]],
                          sum(1 for x in cv["columns"] if x["orphan"])),
                         (["d2", "d3", "d4"], 2)):
            return
        orph = next(x for x in cv["columns"] if x["orphan"]
                    and any(b["id"] == gone for b in x["blocks"]))

        res.check("ЗАПИСЬ СИРОТЫ стоит в его колонке, а не у живого врача",
                  ([b["id"] for b in orph["blocks"]],
                   [b["id"] for b in _col(cv, "d2")["blocks"]]),
                  ([gone], [alive]))

        # --- личность колонки ---
        res.check("КОЛОНКА НАЗВАНА именем из самой записи и считает свои записи",
                  (orph["name"], orph["id"], orph["count"]), ("Dr. Plecat Demult", None, 1))
        res.check("ТЁЗКА живого врача получает СВОЮ колонку, а не сливается с ним",
                  [b["id"] for x in cv["columns"] if x["orphan"]
                   and any(y["id"] == twin for y in x["blocks"]) for b in x["blocks"]],
                  [twin])
        res.check("и в шапке он назван дважды: живым и «вне списка»",
                  [x["name"] for x in cv["columns"]].count("Dr. Activ Doi"), 2)
        res.check("колонка сироты приглушена и без загрузки и свободного часа",
                  (orph["off"], orph["occupancy"], orph["free"]), (True, None, None))

        # --- вход в relink: отдельной проверкой, теряется отдельно ---
        # ⛔ Список — ВЕСЬ справочник (d1 выключен), а не показанные колонки
        res.check("ВХОД В RELINK у сироты: имя-снимок и все врачи справочника",
                  (orph["relink"]["name"], sorted(o["id"] for o in orph["relink"]["options"])),
                  ("Dr. Plecat Demult", ["d1", "d2", "d3", "d4"]))
        res.ok("а у живой колонки его нет",
               all(x["relink"] is None for x in cv["columns"] if not x["orphan"]),
               "форма переприкрепления предложена там, где прикреплять нечего")

        # --- неподвижность: тащить неоткуда и бросать некуда ---
        res.check("ЗАПИСЬ СИРОТЫ НЕ ТАЩИТСЯ: адреса переноса у неё нет",
                  ([b["movable"] for b in orph["blocks"]],
                   [b["movable"] for b in _col(cv, "d2")["blocks"]]),
                  ([False], [True]))
        res.check("и в колонку сироты нельзя бросить: ни одной приёмной ячейки",
                  (any(orph["cells"]), len(orph["cells"]) > 0), (False, True))

        # --- relink действительно чинит то, ради чего он есть ---
        # (форма relink шлётся со всего React-экрана — она осталась серверной)
        res.check("relink отвечает переходом назад на панель",
                  c.post("/admin/relink", old_name="Dr. Plecat Demult", dk="d3",
                         back=f"/admin?date={day}").status, 303)
        cv2 = _canvas(c, day)
        res.check("колонка выпавшего врача исчезла вместе с причиной, "
                  "а колонка тёзки осталась — она про другое",
                  ([x["name"] for x in cv2["columns"]].count("Dr. Plecat Demult"),
                   sum(1 for x in cv2["columns"] if x["orphan"]),
                   [b["id"] for b in _col(cv2, "d3")["blocks"]]),
                  (0, 1, [gone]))


# ------------------------------------------------- геометрия и кластеры


def suite_geometry(res: Result) -> None:
    """Блок стоит по минутам, а пересекающиеся делят ширину.

    ⚠️ Ожидание считается ИЗ ДАННЫХ: «визит на 09:30 при первом часе 09:00 —
    это 0.5 ячейки сверху», «три пересекающихся — это of=3 и col=0,1,2».
    ⚠️ Пересечения у ОДНОГО врача через интерфейс не создать (`db._conflicts`),
    поэтому строки кладутся в базу напрямую — как у клиник с историей.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server(clinic="clinic_hours.json") as s:   # 07–21, обед 13–14, врачи 9–17
        c = Client(s.url).login()
        for i, hh in enumerate(("09:00", "10:00", "11:00", "15:00")):
            _add(c, day, hh, "d2", f"Cluster {i}", i)
        a, b, e, solo = _ids(c, day)
        # ⭐ Случай, РАЗЛИЧАЮЩИЙ алгоритмы: A(09:00-11:00), B(09:30-10:00),
        # C(10:30-11:00). B и C между собой НЕ пересекаются, но обе — с A.
        # Правильный разбор («пересекается хоть с одной из кластера») даёт один
        # кластер на три; наивный («пересекается с предыдущей») отколол бы C, и
        # она встала бы во всю ширину поверх A. Два визита на одном месте — это
        # спрятанный пациент, а выглядит совершенно правдоподобно.
        _sql(s, "UPDATE appointments SET duration_min = 120 WHERE id = ?", a)
        _sql(s, "UPDATE appointments SET starts_at = ?, duration_min = 30"
                " WHERE id = ?", _utc(day, 9, 30), b)
        _sql(s, "UPDATE appointments SET starts_at = ?, duration_min = 30"
                " WHERE id = ?", _utc(day, 10, 30), e)
        _sql(s, "UPDATE appointments SET duration_min = 30 WHERE id = ?", solo)
        by_id = {x["id"]: x for x in _col(_canvas(c, day), "d2").get("blocks", [])}

        # --- якорь ---
        if not res.check("якорь: все четыре блока на канве",
                         sorted(by_id), sorted((a, b, e, solo))):
            return

        first_hour = 9   # у врачей 9–17, края дня срезаны в полоски
        res.check("ПОЗИЦИЯ считается от первого оставленного часа, в долях часа",
                  (by_id[a]["top"], by_id[b]["top"], by_id[solo]["top"]),
                  (0.0, 0.5, float(15 - first_hour)))
        res.check("ВЫСОТА — длительность в долях часа",
                  (by_id[a]["height"], by_id[b]["height"], by_id[solo]["height"]),
                  (2.0, 0.5, 0.5))
        res.check("ПЕРЕСЕКАЮЩИЕСЯ делят ширину: один кластер на три визита",
                  sorted((by_id[x]["of"], by_id[x]["col"]) for x in (a, b, e)),
                  [(3, 0), (3, 1), (3, 2)])
        res.check("НЕ пересекающийся остаётся во всю ширину",
                  (by_id[solo]["of"], by_id[solo]["col"]), (1, 0))

        # --- границы кластера: визит впритык НЕ пересекается ---
        _add(c, day, "09:00", "d3", "Tight Unu", 7)
        _add(c, day, "10:00", "d3", "Tight Doi", 8)
        tight, tight2 = [x for x in _ids(c, day) if x not in (a, b, e, solo)]
        g3 = {x["id"]: x for x in _col(_canvas(c, day), "d3").get("blocks", [])}
        if not res.check("якорь: оба визита впритык на канве", sorted(g3),
                         sorted((tight, tight2))):
            return
        res.check("СТЫК впритык (10:00 сразу после 09:00–10:00) — не кластер",
                  [g3[x]["of"] for x in (tight, tight2)], [1, 1])


# ------------------------------------------- отбор «Lista zilei» по адресу


def suite_tiles(res: Result) -> None:
    """Отбор «Lista zilei» (`/admin/all?f=…`) берёт ровно свои строки.

    До 01.10 сюда вели плитки «Azi» панели, и набор сверял цифру плитки с
    числом строк её отбора. Плиток больше нет (React — с 01.10, старая
    панель — с 13.10), а отбор остался у дня «Programări»: здесь его правило
    названо буквально.
    """
    day = clinic_today().isoformat()
    with Server() as s:
        c = Client(s.url).login()
        for i, (hh, svc, who) in enumerate((("09:00", "pain", "d2"),
                                            ("10:00", "pain", "d3"),
                                            ("11:00", "consult", "d2"),
                                            ("12:00", "hygiene", "d3"))):
            _add(c, day, hh, who, f"Tile {i}", 10 + i, svc=svc)
        # ⭐ отменённая СРОЧНАЯ: отбор обязан пройти мимо неё. Без такой строки
        # мутация «считать и отменённые» не задела бы фикстуру вовсе.
        _add(c, day, "16:00", "d2", "Tile Anulat", 8, svc="pain")
        ids = _ids(c, day)
        c.post_json(f"/api/schedule/appointments/{ids[0]}/status", {"to": "noshow"})
        c.post_json(f"/api/schedule/appointments/{ids[-1]}/status", {"to": "cancelled"})

        if not res.check("якорь: в дне пять строк, без отбора — все",
                         len(day_model(c, day)["list"]), 5):
            return
        for key, names in (("rec", ["Tile 0", "Tile 1", "Tile 2", "Tile 3"]),
                           ("urg", ["Tile 0", "Tile 1"]),
                           ("noshow", ["Tile 0"]),
                           ("bot", [])):
            m = day_model(c, day, f=key)
            res.check(f"отбор «{key}»: свои строки, и счётчик равен им",
                      ([r["name"] for r in m["list"]], (m["filter"] or {}).get("count")),
                      (names, len(names)))
        res.check("чужой ключ отбора сервер отбрасывает — список целиком",
                  (day_model(c, day, f="nope")["filter"],
                   len(day_model(c, day, f="nope")["list"])), (None, 5))


# ------------------------------------------------- шапка колонки врача


def suite_head(res: Result) -> None:
    """Шапка колонки врача на канве: счёт, первый свободный час, загрузка.

    ⚠️ «liber HH:00» — не «первый час без записи», а первый РАБОЧИЙ час без
    ПЕРЕСЕЧЕНИЙ: визит на 09:00 длиной два часа занимает и 10:00, хотя записи
    в десять нет. Ошибка здесь предлагает регистратуре час, в который сервер
    откажет.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server(clinic="clinic_hours.json") as s:   # врачи 9–17, обед 13–14
        c = Client(s.url).login()
        _add(c, day, "09:00", "d2", "Cap Unu", 1)
        _sql(s, "UPDATE appointments SET duration_min = 120 WHERE id = ?",
             _ids(c, day)[0])
        _add(c, day, "11:00", "d2", "Cap Doi", 2)
        _add(c, day, "09:00", "d3", "Cap Trei", 3)
        cv = _canvas(c, day)

        if not res.check("якорь: колонки врачей на месте",
                         [x["name"] for x in cv["columns"]],
                         ["Dr. Activ Doi", "Dr. Activ Trei", "Dr. Activ Patru"]):
            return
        d2, d3, d4 = _col(cv, "d2"), _col(cv, "d3"), _col(cv, "d4")
        res.check("счётчик — записи ЭТОГО врача",
                  (d2["count"], d3["count"], d4["count"]), (2, 1, 0))
        res.check("ПЕРВЫЙ СВОБОДНЫЙ ЧАС считается по пересечениям, "
                  "а не по «в этот час записи нет»",
                  (d2["free"], d3["free"], d4["free"]), ("12:00", "10:00", "09:00"))
        res.check("ЗАГРУЗКА КРЕСЛА: занятые минуты из рабочих минут ЕГО дня",
                  ((d2["occupancy"]["busy"], d2["occupancy"]["cap"]),
                   (d4["occupancy"]["busy"], d4["occupancy"]["cap"])),
                  ((180, 420), (0, 420)))
        res.check("без фото — инициалы, а не пустой кружок",
                  (d2["photo"], d2["initials"]), ("", "AD"))

        # день забит целиком — свободного часа нет («complet» на экране)
        for hh in ("09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00"):
            _add(c, day, hh, "d4", f"Plin {hh}", 20 + int(hh[:2]))
        full = _col(_canvas(c, day), "d4")
        res.check("ЗАБИТЫЙ ДЕНЬ: свободного часа нет, записей семь",
                  (full["free"], full["count"]), (None, 7))

        # выключенный врач: колонка держится, пока есть записи, и помечена
        c.post_json("/api/doctors/d3", {"name": "Dr. Activ Trei", "status": "concediu"})
        off = _col(_canvas(c, day), "d3")
        res.check("ВЫКЛЮЧЕННЫЙ помечен и приглушён, но остаётся с записями",
                  (off.get("off"), off.get("count")), (True, 1))


# ------------------------------------------------------ мини-календарь


def suite_minical(res: Result) -> None:
    """Мини-календарь панели: месяц полными неделями Пн–Вс, метки и точки.

    ⚠️ Недели ПОЛНЫЕ: первая начинается с понедельника, даже если он из
    прошлого месяца, — иначе числа поедут по столбцам и вторник встанет под
    средой. Чистые правила — `test_panel_model.suite_minical_pure`; здесь —
    что живой канал отдаёт их на настоящем сервере, и точки дней с записями.
    """
    from datetime import date as _date
    day = "2026-09-19"      # суббота; сентябрь 2026 начинается во вторник
    with Server() as s:
        c = Client(s.url).login()
        # ⭐ точки (08.10): только ЖИВАЯ запись — отменённая и заметка стойки
        # дня не помечают (то же правило, что у повестки)
        _add(c, "2026-09-21", "10:00", "d2", "Cal Viu", 1)
        _add(c, "2026-09-22", "10:00", "d2", "Cal Anulat", 2)
        c.post_json(f"/api/schedule/appointments/{_ids(c, '2026-09-22')[0]}/status",
                    {"to": "cancelled"})
        c.post_json("/api/schedule/notes", {"date": "2026-09-23", "time": "10:00",
                                           "doctor": "d2", "text": "Doar notiță"})
        m = panel_live(c, day)["minical"]
        cells = [x for w in m["weeks"] for x in w]
        if not res.check("якорь: календарь пришёл неделями по семь дней",
                         (len(m["weeks"]), sorted({len(w) for w in m["weeks"]})), (5, [7])):
            return

        res.check("шапка недели начинается с понедельника", m["weekdays"],
                  ["Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du"])
        res.check("месяц назван по-румынски и с годом", m["title"], "Septembrie 2026")
        res.check("сентябрь 2026 — пять недель с хвостами соседних месяцев",
                  (len(cells), cells[0]["date"], cells[-1]["date"],
                   _date.fromisoformat(cells[0]["date"]).weekday()),
                  (35, "2026-08-31", "2026-10-04", 0))
        res.check("чужие месяцы помечены, свой — нет",
                  (sum(1 for x in cells if x["other"]),
                   next(x["other"] for x in cells if x["date"] == day)), (5, False))
        res.check("ВЫБРАННЫЙ день помечен ровно один, и это он",
                  [x["date"] for x in cells if x["selected"]], [day])
        res.check("перелистывание ведёт на ПЕРВОЕ число соседнего месяца",
                  (m["prev"]["href"], m["next"]["href"]),
                  ("/admin?date=2026-08-01", "/admin?date=2026-10-01"))
        res.check("точка — только у дня с живой записью",
                  [x["date"] for x in cells if x["busy"]], ["2026-09-21"])

        today = clinic_today()
        tcells = [x for w in panel_live(c, today.isoformat())["minical"]["weeks"] for x in w]
        res.check("«сегодня» помечено ровно один раз и это сегодня",
                  [x["date"] for x in tcells if x["today"]], [today.isoformat()])


# ----------------------------------------------------- повестка дня


def _agenda(c: Client, day: str) -> dict:
    return panel_live(c, day)["agenda"]


def _row(c: Client, day: str, name: str) -> dict:
    return next((x for x in _agenda(c, day)["items"] if x["name"] == name), {})


def suite_agenda(res: Result) -> None:
    """«Agenda zilei»: порядок, слова состояния, срочность и приглушение.

    ⚠️ Слово берётся из `STATUS_LABEL`, а класс — из `_AG_CLS`: пара «свой
    класс + своё слово» держалась ровно до тех пор, пока слова совпадали
    (08-12: один статус звался тремя словами на соседних экранах).
    ⛔ «Urgent» перебивает состояние ТОЛЬКО у подтверждённой записи: у
    завершённой срочность уже ничего не значит, а красный бейдж читался бы как
    «горит».
    """
    day = clinic_today().isoformat()
    with Server() as s:
        c = Client(s.url).login()
        empty = _agenda(c, day)
        res.check("пустой день — ноль строк числом", (empty["count"], empty["items"]), (0, []))

        _add(c, day, "10:00", "d2", "Ag Doi", 1)
        _add(c, day, "09:00", "d3", "Ag Unu", 2, svc="pain")
        _add(c, day, "11:00", "d2", "Ag Trei", 3, svc="pain")
        ids = _ids(c, day)
        ag = _agenda(c, day)
        if not res.check("якорь: три строки повестки",
                         [x["name"] for x in ag["items"]], ["Ag Unu", "Ag Doi", "Ag Trei"]):
            return

        res.check("порядок — по времени, а не по номеру записи",
                  [x["time"] for x in ag["items"]], ["09:00", "10:00", "11:00"])
        res.check("счётчик равен числу строк", ag["count"], len(ag["items"]))
        res.check("СРОЧНАЯ подтверждённая помечена «Urgent», обычная — состоянием",
                  [(x["name"], x["badge"]["cls"], x["badge"]["label"]) for x in ag["items"]],
                  [("Ag Unu", "bad", "Urgent"), ("Ag Doi", "pln", "Programată"),
                   ("Ag Trei", "bad", "Urgent")])
        # 03.10: «Confirmată» — только после звонка в «De confirmat»; та же
        # отметка в «Lista zilei» (вид `called`), а статус в базе прежний
        doi = ids[1]                       # 10:00 — обычная, не срочная
        r = c.post_json(f"/api/schedule/desk/call/{doi}?screen=panel&date={day}",
                        {"result": "ok"})
        res.check("отметка звонка принята", r.status, 200)
        row = _row(c, day, "Ag Doi")
        res.check("после звонка ✓ повестка говорит «Confirmată» зелёным",
                  (row["badge"]["cls"], row["badge"]["label"]), ("act", "Confirmată"))
        lst = next(x for x in day_model(c, day)["list"] if x["name"] == "Ag Doi")
        res.check("и «Lista zilei» — тем же видом и словом, статус в базе прежний",
                  (lst["status"], lst["status_view"], lst["status_label"]),
                  ("confirmed", "called", "confirmată"))
        c.post_json(f"/api/schedule/desk/call/{doi}?screen=panel&date={day}",
                    {"result": "noanswer"})
        row = _row(c, day, "Ag Doi")
        res.check("«не отвечает» — янтарным «Nu răspunde»",
                  (row["badge"]["cls"], row["badge"]["label"]), ("att", "Nu răspunde"))
        c.post_json(f"/api/schedule/desk/call/{doi}?screen=panel&date={day}",
                    {"result": ""})
        res.ok("строка открывает карточку визита, и у записи с фишей есть зубы",
               all(x["clickable"] and x["patient_id"] for x in ag["items"]),
               f"{[(x['name'], x['clickable'], x['patient_id']) for x in ag['items']]}")

        # срочность у ЗАКРЫТОЙ записи больше не «Urgent»
        c.post_json(f"/api/schedule/appointments/{ids[0]}/status", {"to": "done"})
        done = _row(c, day, "Ag Unu")
        # «Finalizată» — зелёная с 09.10 (разбор: серая на серой не читалась)
        res.check("у ЗАВЕРШЁННОЙ срочность больше не горит — состояние словом",
                  (done["urgent"], done["badge"]["cls"], done["badge"]["label"]),
                  (False, "act", "Finalizată"))

        # минуты ожидания — ОТМЕТКА, а не текст сервера
        c.post_json(f"/api/schedule/appointments/{ids[1]}/status", {"to": "waiting"})
        wait = _row(c, day, "Ag Doi")
        res.ok("ожидание уезжает отметкой wait_since, без минут текстом",
               isinstance(wait.get("wait_since"), int)
               and not any(isinstance(v, str) and re.search(r"\d+\s*min", v)
                           for v in wait.values()),
               f"строка: {wait}")

        # приглушение — только СЕГОДНЯ: в чужом дне состояния нет вовсе
        soon = (clinic_today() + timedelta(days=2)).isoformat()
        _add(c, soon, "08:00", "d2", "Ag Maine", 4)
        res.check("в БУДУЩЕМ дне не приглушено ничего — состояния нет",
                  [x["state"] for x in _agenda(c, soon)["items"]], [None])
        # ⛔ И в ПРОШЛОМ тоже: «прошло» там не значит ничего, а тусклый список
        # читается как отменённый. Без этого дня проверка выше не ловит потерю
        # условия «только сегодня» — в будущем оно и так не срабатывает.
        past_day = (clinic_today() - timedelta(days=2)).isoformat()
        _add(c, past_day, "08:00", "d2", "Ag Ieri", 5)
        res.check("в ПРОШЛОМ дне не приглушено ничего — состояния нет",
                  [x["state"] for x in _agenda(c, past_day)["items"]], [None])

        # приглушение считается по КОНЦУ визита: идущий прямо сейчас — не «past»
        now = datetime.now(TZ)
        # ⚠️ Проверке нужен визит, который ИДЁТ ПРЯМО СЕЙЧАС: начался раньше,
        # кончится позже. Такой существует только ВНУТРИ рабочих часов клиники
        # — вне их бронь на «час назад» просто не создаётся, и проверка
        # краснела бы на исправном коде. Поймано 20.09 в 23:05 (D0c).
        # ⛔ Час НЕ подгоняем под окно: подогнанный визит перестал бы быть
        # «идущим сейчас», и проверка стала бы зелёной, ничего не проверяя.
        # Вне окна — пропуск ВСЛУХ, как в сценах браузера.
        _wd = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[now.weekday()]
        _win = (json.loads(s.clinic.read_text(encoding="utf-8"))
                .get("hours", {}).get(_wd))
        _fits = bool(_win) and _win[0] <= now.hour - 1 < _win[1]
        if not _fits:
            # ⛔ Пропуск печатается, а не только заводится проверкой: метку
            # прошедшей проверки прогон не показывает, и пропуск остался бы
            # невидимым — то самое ложное зелёное, от которого защищаемся.
            print(f"    ⚠️  {now:%H:%M} вне рабочего окна {_win}: проверка "
                  f"«идущий сейчас визит» пропущена")
            res.ok(f"идущий сейчас визит: {now:%H:%M} вне рабочего окна "
                   f"{_win} — проверка пропущена", True, "")
        if now.hour >= 2 and _fits:   # иначе «час назад» уедет во вчера
            _add(c, day, f"{now.hour - 1:02d}:00", "d4", "Ag Acum", 6)
            # ⚠️ Берём НОВЕЙШУЮ запись — ту, что только что добавили: список дня
            # идёт по ВРЕМЕНИ, и визит «час назад» встаёт в его СЕРЕДИНУ.
            live_id = max(_ids(c, day))
            _sql(s, "UPDATE appointments SET duration_min = 180 WHERE id = ?", live_id)
            res.check("идущий СЕЙЧАС визит не приглушён — считается КОНЕЦ, не начало",
                      _row(c, day, "Ag Acum").get("state"), "current")


# --------------------------------------- модель канвы на «дорогом» засеве


def suite_model(res: Result) -> None:
    """Модель канвы на засеве из самых дорогих случаев разом.

    ⚠️ Сирота, кластер пересечения, заметка стойки, визит в ожидании и профиль
    со СДВИНУТЫМ графиком (края дня срезаются в полоски, и `base_min` после
    среза другой). Простая фикстура прошла бы этот набор зелёной мимо всего,
    ради чего он написан. До 13.10 модель сверялась со страницей (C26.4);
    теперь ожидания названы числами — они выводятся из фикстуры
    (`clinic_panel.json`: клиника 07–21 с обедом 13–14, врачи 09–17).
    """
    # ⚠️ День выбирается ПО ДНЮ НЕДЕЛИ, а не «сегодня плюс три»: у профиля со
    # сдвинутым графиком часы приёма разные по дням, и плавающая фикстура была
    # бы зелёной сегодня и красной в воскресенье — без единой правки кода.
    day = _weekday_after(clinic_today(), 2).isoformat()
    with Server(clinic="clinic_panel.json") as s:
        c = Client(s.url).login()
        _add(c, day, "09:00", "d2", "Pacient Lung", 1)
        _add(c, day, "10:00", "d2", "Pacient Sub", 2)
        _add(c, day, "11:00", "d3", "Pacient Orfan", 3)
        _add(c, day, "12:00", "d3", "Pacient Astept", 4)
        lung, sub, orfan, astept = _ids(c, day)[:4]
        # ⚠️ Заметка заводится ПОСЛЕ разбора id: `_ids` читает строки дня в
        # порядке ВРЕМЕНИ, а заметка на 09:00 встала бы первой и сдвинула весь
        # разбор на единицу. Час её — ПЕРВЫЙ рабочий у d4: только так видно, что
        # заметка занимает час, не попадая в счёт пациентов. И не 13:00 — там
        # обед, и заметку отвергли бы (`bad`).
        c.post_json("/api/schedule/notes", {"date": day, "time": "09:00", "doctor": "d4",
                                           "text": NOTE_LONG})
        # кластер: визит на 09:00 длиной два часа накрывает соседний в 10:00
        _sql(s, "UPDATE appointments SET duration_min = 120 WHERE id = ?", lung)
        # сирота: врач выпал из справочника, осталось имя-снимок
        _sql(s, "UPDATE appointments SET doctor_id = NULL, doctor = ?"
                " WHERE id = ?", "Dr. Plecat Demult", orfan)
        # ожидание в приёмной: отметка есть, минуты считает браузер
        _sql(s, "UPDATE appointments SET status = 'waiting', waiting_at = ?"
                " WHERE id = ?",
             datetime.now(TZ).isoformat(timespec="seconds"), astept)
        m = _canvas(c, day)

        # --- якорь: в фикстуре есть всё, о чём набор говорит ---
        if not res.check(
                "якорь: колонка-сирота, кластер, заметка и срезанный край НА МЕСТЕ",
                (sum(1 for x in m["columns"] if x["orphan"]),
                 max((b["of"] for x in m["columns"] for b in x["blocks"]), default=0),
                 sum(1 for x in m["columns"] for b in x["blocks"]
                     if b["kind"] == "note"),
                 bool(m["bands"]["top"] or m["bands"]["bottom"])),
                (1, 2, 1, True)):
            return

        # --- ряды: края срезаны, обед остался рядом ---
        res.check("ЧАСЫ — рабочие часы врачей, обед РЯДОМ, без дыр",
                  _hours(m), list(range(9, 17)))
        # ⚠️ Подсветки текущего часа здесь нет НАМЕРЕННО: день не сегодняшний.
        # Она живёт в `suite_model_now`, где час действительно есть.
        res.check("СРЕЗАННЫЕ КРАЯ — полосками с часами закрытия",
                  m["bands"], {"top": {"from": "07:00", "to": "09:00"},
                               "bottom": {"from": "17:00", "to": "21:00"}})
        res.check("и начало координат — первый ОСТАВЛЕННЫЙ час", m["base_min"], 540)

        # --- колонки ---
        res.check("КОЛОНКИ: активные врачи справочника, затем сирота",
                  [(x["id"], x["name"]) for x in m["columns"]],
                  [("d2", "Dr. Activ Doi"), ("d3", "Dr. Activ Trei"),
                   ("d4", "Dr. Activ Patru"), (None, "Dr. Plecat Demult")])
        res.check("выключенного d1 без записей на канве нет, живые не приглушены",
                  [x["off"] for x in m["columns"]], [False, False, False, True])
        hues = {dk: json.loads(c.get(f"/api/doctors/{dk}").body)["data"]["color"]
                for dk in ("d2", "d3", "d4")}
        res.check("цвет колонки — тот же, что у врача в /api/doctors",
                  {x["id"]: x["hue"] for x in m["columns"] if x["id"]}, hues)
        # ⚠️ Счёт записей и первый свободный час питаются РАЗНЫМИ списками, и
        # это не описка: «N prog.» считает пациентов (заметки не в счёт), а
        # «liber HH:00» смотрит на ЗАНЯТОСТЬ — заметка стойки занимает час
        # наравне с визитом. Сведи их к одному списку, и модель начнёт звать
        # записываться в час, заблокированный заметкой.
        res.check("счётчик записей и первый свободный час (заметка часа держит)",
                  [(x["count"], x["free"]) for x in m["columns"] if not x["orphan"]],
                  [(2, "11:00"), (1, "09:00"), (0, "10:00")])
        res.check("кабинет и телефон врача приезжают полями, и подсказкой тоже",
                  [(x["room"], x["phone"], x["title"]) for x in m["columns"]
                   if x["id"] == "d2"],
                  [("Cab. 2", "069123456", "Dr. Activ Doi · Cab. 2 · 069123456")])
        # 60′+120′ из 7 рабочих часов (09–17 без обеда) = 180/420 = 43%
        res.check("загрузка кресла: минуты и процент ЕГО дня",
                  [(x["occupancy"]["busy"], x["occupancy"]["cap"], x["occupancy"]["pct"])
                   for x in m["columns"] if not x["orphan"]],
                  [(180, 420, 43), (60, 420, 14), (0, 420, 0)])
        res.check("ужимать карточки или нет — решает сервер (колонок четыре — нет)",
                  m["tight"], False)

        # --- ячейки: куда можно записать и куда можно бросить ---
        res.check("ПРИЁМНЫЕ ЧАСЫ колонок: все, кроме обеда; у сироты — ни одного",
                  [x["cells"] for x in m["columns"]],
                  [[h != 13 for h in range(9, 17)]] * 3 + [[False] * 8])

        # --- блоки: геометрия и договор переноса ---
        res.check("БЛОКИ стоят в своих колонках: кластер d2, ожидание d3, заметка d4, сирота",
                  [[b["id"] for b in x["blocks"]] for x in m["columns"]],
                  [[lung, sub], [astept], [max(_ids(c, day))], [orfan]])
        res.check("ГЕОМЕТРИЯ каждого блока: верх, высота, место в кластере",
                  [(b["top"], b["height"], b["col"], b["of"])
                   for x in m["columns"] for b in x["blocks"]],
                  [(0.0, 2.0, 0, 2), (1.0, 1.0, 1, 2), (3.0, 1.0, 0, 1),
                   (0.0, 1.0, 0, 1), (2.0, 1.0, 0, 1)])
        res.check("ДОГОВОР ПЕРЕНОСА: живые тащатся, сирота — нет",
                  [b["movable"] for x in m["columns"] for b in x["blocks"]],
                  [True, True, True, True, False])

        # --- то, чего на экране не видно, но без чего он соврёт ---
        note = next(b for x in m["columns"] for b in x["blocks"]
                    if b["kind"] == "note")
        # ⛔ Текст фикстуры ДЛИННЕЕ обеих границ, и числа записаны числами. До
        # 19.09 здесь стояло `min(80, len(текст))` при тексте в 38 знаков:
        # обе величины равнялись 38, и перестановка 80 и 40 местами прошла бы
        # незамеченной — проверка была зелена по неверной причине.
        # ⭐ Третьим членом — полная длина: именно `text` закрывает дыру
        # живого канала (правка после 80-го знака), live-contract › 6c.
        res.check("ЗАМЕТКА приезжает В ТРЁХ ВИДАХ: полный текст, 80 в "
                  "подсказке, 40 в блоке",
                  (note["text"], len(note["title"]), len(note["label"])),
                  (NOTE_LONG, 80, 40))
        wait = next(b for x in m["columns"] for b in x["blocks"]
                    if b.get("status") == "waiting")
        res.ok("ОЖИДАНИЕ приезжает ОТМЕТКОЙ, а не минутами",
               isinstance(wait["wait_since"], int) and wait["wait_since"] > 0,
               "минуты в теле меняли бы отпечаток живого канала каждую минуту — "
               "экран перерисовывался бы без единой правки данных")
        res.ok("слово статуса приходит с сервера — второго словаря в браузере нет",
               wait.get("status_label") and wait["status_label"] != wait["status"],
               f"статус приехал кодом: {wait.get('status_label')!r}")
        orph = next(x for x in m["columns"] if x["orphan"])
        # ⛔ Список relink — ВЕСЬ справочник, а не показанные колонки. Врач,
        # к которому надо переприкрепить легаси-строки, может быть временно
        # выключен: собери список из колонок — и записи выпавшего врача не
        # переприкрепить уже никогда, а это единственный вход в relink.
        res.check("у сироты ВХОД В RELINK — весь справочник, даже выключенный d1",
                  (orph["relink"]["name"], [o["id"] for o in orph["relink"]["options"]]),
                  ("Dr. Plecat Demult", ["d1", "d2", "d3", "d4"]))
        res.ok("а у живой колонки его нет",
               all(x["relink"] is None for x in m["columns"] if not x["orphan"]),
               "форма переприкрепления предложена там, где прикреплять нечего")


def suite_model_now(res: Result) -> None:
    """Подсветка ТЕКУЩЕГО часа: модель метит ровно один ряд, и это сейчас.

    ⚠️ Час берётся живой, поэтому запись ставится прямо в базу на текущий час
    — так ряд существует даже в день, когда клиника закрыта (`row_hours`
    держит час, в котором что-то стоит). Иначе набор молча пропускал бы
    воскресенье.
    ⛔ Линии «сейчас» в модели нет: она двигается НЕПРЕРЫВНО и потому живёт в
    браузере (`DashCanvas`). Подсветка часа — серверная, и это разные вещи: она
    меняется раз в час, и её смена — честное изменение состояния.
    """
    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        far = _weekday_after(clinic_today() + timedelta(days=7), 2).isoformat()
        _add(c, far, "09:00", "d2", "Pacient Acum", 1)
        aid = _ids(c, far)[0]
        today = clinic_today().isoformat()
        for attempt in range(2):
            hour = datetime.now(TZ).hour
            _sql(s, "UPDATE appointments SET starts_at = ? WHERE id = ?",
                 _utc(today, hour), aid)
            m = _canvas(c, today)
            marked = [h["h"] for h in m["hours"] if h["now"]]
            # час мог смениться МЕЖДУ запросами — тогда пробуем ещё раз, а не
            # краснеем: это не поломка, а граница часа
            if marked == [hour] or attempt:
                break
        if not res.check("якорь: текущий час вообще есть в сетке",
                         hour in _hours(m), True):
            return
        res.check("ПОМЕЧЕН РОВНО ОДИН час, и это текущий", marked, [hour])
        res.check("в чужом дне подсветки «сейчас» нет",
                  [h["h"] for h in _canvas(c, far)["hours"] if h["now"]], [])
        res.ok("линии «сейчас» в модели нет — её двигает браузер",
               all("nowline" not in k for k in m),
               "непрерывная величина в состоянии меняла бы отпечаток живого "
               "канала каждый опрос — мигание, от которого ушли 08-20")


def suite_model_empty(res: Result) -> None:
    """День без графика и без записей: модель говорит «пусто» признаком.

    ⚠️ Проверка отдельным набором: в общей фикстуре этой ветки не бывает, а
    ошибка в ней стоит дорого — модель, вернувшая ноль часов вместо признака
    «закрыто», дала бы React пустую сетку без единого слова о причине.
    """
    with Server(clinic="clinic_panel.json") as s:
        c = Client(s.url).login()
        # воскресенье: у этого профиля клиника закрыта (`hours.sun = null`)
        m = _canvas(c, _weekday_after(clinic_today(), 6).isoformat())
        res.check("день пуст — признаком, а не нулём часов",
                  (m["empty"], m["hours"], m["columns"], m["base_min"]),
                  (True, [], [], None))
        res.check("и полосок закрытых краёв не выдумывает",
                  m["bands"], {"top": None, "bottom": None})


# ------------------------------------------- цвет врача: одна формула на все


def _card_hue(c: Client, dk: str) -> str:
    """Цвет аватара на КАРТОЧКЕ врача — то, что карточка получает от сервера.

    ⚠️ Читается из ответа `/api/doctors/{dk}`, а не считается формулой заново:
    проверка, повторяющая формулу, зеленела бы вместе с ней — в том числе на
    двух экранах, которые уже разъехались.
    """
    r = c.get(f"/api/doctors/{dk}")
    return json.loads(r.body)["data"]["color"] if r.status == 200 else ""


def _head_hues(c: Client, day: str) -> dict:
    """Цвет колонки каждого врача на канве дня — по имени врача."""
    return {x["name"]: x["hue"] for x in _canvas(c, day)["columns"]}


def suite_hue(res: Result) -> None:
    """Цвет врача считает ОДНА формула — `core.visits._doc_hue` (19.09).

    ⛔ До 19.09 их было две. Карточка врача, `/api/doctors` и аватар брали
    место врача в СПРАВОЧНИКЕ, а канва панели — место среди ПОКАЗАННЫХ в этот
    день колонок. Сходились они только там, где показаны все: стоило одному
    врачу выпасть из дня, и у соседа справа цвет колонки расходился с его же
    аватаром. Один врач, два цвета, и ни одной ошибки нигде.
    ⚠️ Хуже расхождения было ПЛАВАНИЕ: цвет колонки менялся ото дня ко дню от
    того, у кого ещё есть записи. Регистратура держит цвет за признак врача —
    «синий кабинет» говорят про человека, а не про день, — поэтому оба случая
    проверяются здесь порознь.
    ⚠️ Набор читает КАНВУ и КАРТОЧКУ, а не одну формулу дважды: предмет
    проверки — согласие двух экранов, и только их сравнение его выражает.
    """
    wed = _weekday_after(clinic_today(), 2)
    day_a, day_b = wed.isoformat(), (wed + timedelta(days=1)).isoformat()
    with Server(clinic="clinic_panel.json") as s:
        c = Client(s.url).login()
        # d1 в фикстуре «arhivat»: колонка ему положена ровно в тот день, где
        # у него есть записи, — в day_a она есть, в day_b её нет. Запись
        # заводится мимо окна записи: выключенного врача оно не предложит (тот
        # же приём, что у сироты в `suite_model`).
        _add(c, day_a, "09:00", "d2", "Pacient Arhivat", 1)
        _sql(s, "UPDATE appointments SET doctor_id = 'd1', doctor = ?"
                " WHERE id = ?", "Dr. Arhivat Unu", _ids(c, day_a)[0])

        hues_a, hues_b = _head_hues(c, day_a), _head_hues(c, day_b)
        card = _card_hue(c, "d3")
        d3 = json.loads(c.get("/api/doctors/d3").body)["data"]

        # --- якорь: предмет разговора в фикстуре ЕСТЬ ---
        # ⛔ Без него набор зеленел бы над врачом СО СВОИМ цветом (там формулы
        # и не расходились никогда) или над двумя днями, в которых показаны
        # одни и те же колонки, — то есть над пустотой.
        if not res.check(
                "якорь: у d3 цвет ЗАПАСНОЙ, и слева от него колонка то есть, то нет",
                (d3["auto_color"], "Dr. Arhivat Unu" in hues_a,
                 "Dr. Arhivat Unu" in hues_b, bool(card)),
                (True, True, False, True)):
            return

        res.check("ЦВЕТ КОЛОНКИ на канве = цвет аватара на карточке того же врача",
                  hues_b.get("Dr. Activ Trei"), card)
        res.check("и тот же цвет отдаёт /api/doctors — экранов три, формула одна",
                  d3["color"], card)
        res.check("и НЕ ЗАВИСИТ от того, у кого ещё есть записи в этот день",
                  hues_a.get("Dr. Activ Trei"), hues_b.get("Dr. Activ Trei"))
        # ⚠️ Вторая половина `_doc_hue`, и без неё правило читалось бы как
        # «цвет всегда из палитры»: свой цвет врача сильнее места в справочнике.
        c.post_json("/api/doctors/d3", {"name": "Dr. Activ Trei", "status": "activ",
                                       "color": "#123456"})
        res.check("СВОЙ цвет врача сильнее палитры — и на канве, и на карточке",
                  (_head_hues(c, day_a).get("Dr. Activ Trei"), _card_hue(c, "d3")),
                  ("#123456", "#123456"))
