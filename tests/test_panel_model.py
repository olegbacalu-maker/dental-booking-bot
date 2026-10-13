"""Правая колонка панели данными: повестка дня (C27.2) и мини-календарь.

⛔ **Чистые** наборы подают строки словарями и НАЗЫВАЮТ момент: только так
тройное состояние `future`/`current`/`past` проверяется на границах и не
зависит от того, в котором часу запустили прогон. Набор, считающий «сейчас» из
настоящих часов, был бы зелёным днём и красным в полночь — ровно та болезнь,
из-за которой в проекте берут `harness.clinic_today()`, а не `date.today()`.

⚠️ **Живой** (`suite_agenda_live`) — что живой канал отдаёт ту же повестку на
настоящем сервере, с ожиданиями числами. До 13.10 он сверял модель со старой
страницей; страницы нет, а сверка модели с самой собой не проверяла бы ничего.
Плиток «Azi» с трендами здесь больше нет вовсе — их сняли со старой панелью
(React их не рисует с 01.10).
"""
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

from harness import Client, Result, Server, clinic_today, panel_live

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import engine as eng                                      # noqa: E402
from app.modules.schedule.panel import agenda, agenda_state, minical  # noqa: E402
from app.modules.schedule.routes import (_AG_CLS, _svc_colors,     # noqa: E402
                                        _RO_MONTHS as MONTHS)

from test_admin_canvas import _add, _ids                            # noqa: E402

DAY = date(2026, 9, 23)                  # среда, заведомо не «сегодня»
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=eng.TZ)


def _row(hh: int, mm: int = 0, **kw) -> dict:
    """Строка дня в том виде, в каком её отдаёт `db.day_appointments`."""
    r = {"id": kw.get("id", hh * 100 + mm), "patient_id": kw.get("patient_id", 1),
         "service": kw.get("service", "Consultație"),
         "doctor": "Dr. Activ Doi", "doctor_id": "d2", "service_id": "consult",
         "starts_at": datetime(DAY.year, DAY.month, DAY.day, hh, mm, tzinfo=eng.TZ),
         "duration_min": kw.get("duration_min", 60),
         "status": kw.get("status", "confirmed"),
         "source": kw.get("source", "panel"),
         "name": kw.get("name", "Pacient"), "phone": "069000000",
         "birth_year": None, "comment": kw.get("comment", ""), "reminded_day": None,
         "waiting_at": kw.get("waiting_at"), "arrived_at": kw.get("arrived_at"),
         "has_rec": False,
         # отметка звонка-подтверждения (03.10) — колонка той же выборки
         "call_result": kw.get("call_result")}
    return r


def _ag(rows: list, cards=None, now: datetime = NOW, d: date = DAY) -> dict:
    return agenda(d, rows, cards if cards is not None else {}, _svc_colors,
                  _AG_CLS, now)


def suite_agenda_pure(res: Result) -> None:
    """Правила повестки: порядок, состав, слово состояния, тройное состояние."""
    urgent_svc = next(iter(eng.URGENT_LABELS))
    rows = [_row(14, name="Trei"), _row(9, name="Unu"), _row(11, name="Doi")]
    m = _ag(rows)
    if not res.check("якорь: три строки разобраны",
                     [x["name"] for x in m["items"]], ["Unu", "Doi", "Trei"]):
        return

    res.check("порядок — ПО ВРЕМЕНИ, а не по номеру записи",
              [x["time"] for x in m["items"]], ["09:00", "11:00", "14:00"])
    res.check("счётчик равен числу строк", m["count"], len(m["items"]))

    # --- состав: чего в повестке НЕТ ---
    mixed = _ag([_row(9, name="Visita"),
                 _row(10, source="note", service="Livrare", name=None),
                 _row(11, status="cancelled", name="Anulat")])
    res.check("заметка стойки и отменённая в повестку не попадают",
              [x["name"] for x in mixed["items"]], ["Visita"])

    # --- слово и класс ---
    words = _ag([_row(9, status="confirmed"), _row(10, status="waiting"),
                 _row(11, status="arrived"), _row(12, status="done"),
                 _row(13, status="noshow")])
    res.check("класс бейджа — из _AG_CLS, по одному на статус; запись до звонка — контуром",
              [x["badge"]["cls"] for x in words["items"]],
              ["pln", "wai", "trt", "act", "bad"])

    # --- звонок-подтверждение (03.10, слово Олега: «confirmat» — только после
    # галочки в «De confirmat»): статус тот же, меняются слово и класс ---
    calls = _ag([_row(9, name="Nesunat"), _row(10, name="Da", call_result="ok"),
                 _row(11, name="Nu", call_result="noanswer"),
                 _row(12, name="Venit", status="waiting", call_result="ok"),
                 _row(13, name="Urg", service=urgent_svc, call_result="ok")])
    res.check("до звонка «Programată», после ✓ «Confirmată», после ✗ «Nu răspunde»; "
              "пришедшему и срочной звонок слова не меняет",
              [(x["name"], x["badge"]["cls"], x["badge"]["label"]) for x in calls["items"]],
              [("Nesunat", "pln", "Programată"), ("Da", "act", "Confirmată"),
               ("Nu", "att", "Nu răspunde"), ("Venit", "wai", "A venit"),
               ("Urg", "bad", "Urgent")])
    res.check("комментарий визита едет в строку повестки полностью (значок и подсказка)",
              [x["comment"] for x in _ag([_row(9, comment="alergie"), _row(10)])["items"]],
              ["alergie", ""])
    res.ok("слово состояния приходит ГОТОВЫМ и с заглавной",
           all(x["badge"]["label"] and x["badge"]["label"][0].isupper()
               for x in words["items"])
           and words["items"][0]["badge"]["label"] != "confirmed",
           "статус уехал кодом — в браузере завёлся бы второй словарь: "
           f"{[x['badge']['label'] for x in words['items']]}")

    # --- срочность ---
    urg = _ag([_row(9, service=urgent_svc, status="confirmed", name="Acum"),
               _row(10, service=urgent_svc, status="done", name="Gata")])
    res.check("«Urgent» — только у ПОДТВЕРЖДЁННОЙ; у завершённой снова состояние",
              [(x["name"], x["urgent"], x["badge"]["cls"], x["badge"]["label"])
               for x in urg["items"]],
              [("Acum", True, "bad", "Urgent"),
               ("Gata", False, "act",
                urg["items"][1]["badge"]["label"])])
    res.ok("и слово у завершённой — не «Urgent»",
           urg["items"][1]["badge"]["label"] != "Urgent",
           "срочность у закрытого визита читается как «горит»")

    # --- ТРОЙНОЕ СОСТОЯНИЕ, на границах ---
    day_rows = [_row(10, name="Pas", duration_min=60),      # 10:00–11:00
                _row(12, name="Acum", duration_min=60),     # 12:00–13:00
                _row(15, name="Vii", duration_min=60)]
    st = {x["name"]: x["state"] for x in _ag(day_rows)["items"]}
    res.check("прошедшее, идущее и будущее различаются ЯВНО",
              (st["Pas"], st["Acum"], st["Vii"]), ("past", "current", "future"))
    res.check("граница старта принадлежит ИДУЩЕМУ, граница конца — ПРОШЕДШЕМУ",
              (agenda_state(DAY, NOW, 60, NOW),
               agenda_state(DAY, NOW - timedelta(minutes=60), 60, NOW)),
              ("current", "past"))
    res.check("в ЧУЖОМ дне состояния нет вовсе — страница его тоже не считает",
              ([x["state"] for x in _ag(day_rows, now=NOW + timedelta(days=1))["items"]],
               _ag(day_rows, now=NOW + timedelta(days=1))["today"]),
              ([None, None, None], False))

    # --- ожидание: отметка, а не строка ---
    ws = datetime(DAY.year, DAY.month, DAY.day, 11, 30, tzinfo=eng.TZ)
    waits = _ag([_row(9, status="waiting", waiting_at=ws, name="Asteapta"),
                 _row(10, status="waiting", name="FaraMarca"),
                 _row(11, status="confirmed", waiting_at=ws, name="Nu")])
    res.check("минуты ожидания НЕ считаются на сервере — уезжает отметка",
              [x["wait_since"] for x in waits["items"]],
              [int(ws.timestamp() * 1000), None, None])

    # --- поток пациента (03.10): вкладки Întârzie / A venit / În cabinet ---
    # ⛔ Минуты («опаздывает», «сверх плана») считает браузер: сервер шлёт
    # только отметки и ГОТОВЫЕ часы в поясе клиники.
    came = datetime(DAY.year, DAY.month, DAY.day, 7, 7, tzinfo=timezone.utc)  # 10:07 в Кишинёве
    fl = _ag([_row(10, duration_min=45, status="arrived", arrived_at=came, name="InCab"),
              _row(11, status="waiting", waiting_at=ws, arrived_at=came, name="Wait"),
              _row(12, status="done", arrived_at=came, name="Done")])
    st10 = datetime(DAY.year, DAY.month, DAY.day, 10, 0, tzinfo=eng.TZ)
    res.check("поток: начало и плановый конец — отметками, конец и вход в кабинет — "
              "часами в поясе клиники (база хранит UTC)",
              {k: fl["items"][0][k] for k in ("start_ms", "end_ms", "end", "in_at")},
              {"start_ms": int(st10.timestamp() * 1000),
               "end_ms": int((st10 + timedelta(minutes=45)).timestamp() * 1000),
               "end": "10:45", "in_at": "10:07"})
    res.check("«в кабинете с» — только у того, кто в кабинете сейчас",
              [x["in_at"] for x in fl["items"]], ["10:07", "", ""])
    res.check("врач, его ключ и телефон пациента едут в строку (вкладки сводят по врачу)",
              {k: fl["items"][1][k] for k in ("doctor", "doctor_id", "phone")},
              {"doctor": "Dr. Activ Doi", "doctor_id": "d2", "phone": "069000000"})
    late = NOW + timedelta(minutes=7)
    res.check("⛔ модель повестки от минуты НЕ зависит (кроме перехода state) — "
              "иначе отпечаток живого канала менялся бы каждый опрос",
              [{k: v for k, v in x.items() if k != "state"} for x in _ag(day_rows, now=late)["items"]],
              [{k: v for k, v in x.items() if k != "state"} for x in _ag(day_rows)["items"]])

    # --- кнопка зубов и карточка ---
    who = _ag([_row(9, name="Cu"), _row(10, patient_id=None, name="Fara")],
              cards={900: 1})
    res.check("кнопка одонтограммы — только у визита С ПАЦИЕНТОМ",
              [x["patient_id"] for x in who["items"]], [1, None])
    res.check("карточка открывается только у того, у кого она есть",
              [x["clickable"] for x in who["items"]], [True, False])
    res.check("пустой день говорит числом, а не отсутствием поля",
              (_ag([])["count"], _ag([])["items"]), (0, []))


def suite_agenda_live(res: Result) -> None:
    """Повестка живого канала на настоящем сервере: те же правила, что у
    чистого набора, — над записями из базы, а не над словарями."""
    day = clinic_today().isoformat()
    urgent_svc = "pain"
    with Server() as s:
        c = Client(s.url).login()
        _add(c, day, "09:00", "d3", "Par Unu", 1, svc=urgent_svc)
        _add(c, day, "10:00", "d2", "Par Doi", 2)
        _add(c, day, "11:00", "d2", "Par Trei", 3, svc=urgent_svc)
        ids = _ids(c, day)
        # срочная ЗАВЕРШЁННАЯ: ветка, в которой «Urgent» обязан исчезнуть
        c.post_json(f"/api/schedule/appointments/{ids[0]}/status", {"to": "done"})
        # и пациент в приёмной — у него отметка времени
        c.post_json(f"/api/schedule/appointments/{ids[1]}/status", {"to": "waiting"})
        m = panel_live(c, day)["agenda"]

        if not res.check("якорь: три строки и счётчик",
                         (len(m["items"]), m["count"], m["today"]), (3, 3, True)):
            return
        res.check("записи — по времени, со своими часом, именем и услугой",
                  [(x["id"], x["time"], x["name"], x["service"]) for x in m["items"]],
                  [(ids[0], "09:00", "Par Unu", "Durere acută"),
                   (ids[1], "10:00", "Par Doi", "Consultație"),
                   (ids[2], "11:00", "Par Trei", "Durere acută")])
        res.check("БЕЙДЖ: у завершённой срочной — «Finalizată», у пришедшего — «A venit», "
                  "у ждущей срочной — «Urgent»",
                  [(x["badge"]["cls"], x["badge"]["label"], x["urgent"]) for x in m["items"]],
                  [("act", "Finalizată", False), ("wai", "A venit", False),
                   ("bad", "Urgent", True)])
        res.ok("полоса — цвет услуги, переменной темы",
               all(x["bar"].startswith("var(--") for x in m["items"]),
               f"{[x['bar'] for x in m['items']]}")
        res.ok("сегодня у каждой строки есть состояние",
               all(x["state"] in ("past", "current", "future") for x in m["items"]),
               f"{[x['state'] for x in m['items']]}")
        res.check("карточка открывается у всех, и у всех есть фиша",
                  [(x["clickable"], x["patient_id"] is not None) for x in m["items"]],
                  [(True, True)] * 3)
        res.check("ожидание приехало отметкой — только у пришедшего",
                  [isinstance(x["wait_since"], int) for x in m["items"]],
                  [False, True, False])
        # ⚠️ ВЧЕРАШНИЙ день: «в чужом дне „прошло" не значит ничего», и модель
        # обязана сказать `None`, а не «past». Детерминировано в любой час.
        yday = (clinic_today() - timedelta(days=1)).isoformat()
        _add(c, yday, "09:00", "d2", "Ieri Unu", 4)
        m_y = panel_live(c, yday)["agenda"]
        res.check("в ЧУЖОМ дне модель не выдумывает «past»",
                  ([x["state"] for x in m_y["items"]], m_y["today"]), ([None], False))


# ----------------------------------------------------- мини-календарь


def suite_minical_pure(res: Result) -> None:
    """Календарь: полные недели, три независимые метки, соседи по первому числу.

    ⚠️ Дни названы ЯВНО, а не «сегодня плюс N»: сентябрь 2026 начинается во
    вторник и укладывается ровно в пять недель — набор, считающий от текущей
    даты, проверял бы каждый месяц другую раскладку и однажды покраснел бы без
    единой правки кода.
    """
    sep = date(2026, 9, 19)          # суббота
    today = date(2026, 9, 21)        # понедельник, НЕ выбранный день
    m = minical(sep, today, MONTHS)
    if not res.check("якорь: сентябрь 2026 укладывается в ПЯТЬ недель по семь дней",
                     (len(m["weeks"]), sorted({len(w) for w in m["weeks"]})),
                     (5, [7])):
        return

    res.check("подпись — месяц словом и год", m["title"], "Septembrie 2026")
    res.check("шапка недели начинается с понедельника и кончается воскресеньем",
              (m["weekdays"][0], m["weekdays"][-1], len(m["weekdays"])),
              ("Lu", "Du", 7))
    res.check("ПЕРВАЯ неделя начинается с понедельника — даже из прошлого месяца",
              (m["weeks"][0][0]["date"], m["weeks"][0][0]["other"]),
              ("2026-08-31", True))
    res.check("и первое число месяца стоит во ВТОРНИКЕ, а не в первой клетке",
              (m["weeks"][0][1]["date"], m["weeks"][0][1]["other"]),
              ("2026-09-01", False))
    res.check("последняя неделя дотянута до воскресенья чужими днями",
              (m["weeks"][-1][-1]["date"], m["weeks"][-1][-1]["other"]),
              ("2026-10-04", True))

    flat = [c for w in m["weeks"] for c in w]
    res.check("дни идут подряд, без пропусков и повторов",
              (len(flat), len({c["date"] for c in flat})), (35, 35))
    res.check("ТРИ МЕТКИ независимы: чужой месяц, сегодня и выбранный",
              ([c["date"] for c in flat if c["today"]],
               [c["date"] for c in flat if c["selected"]],
               sum(1 for c in flat if c["other"])),
              (["2026-09-21"], ["2026-09-19"], 5))
    both = minical(sep, sep, MONTHS)
    res.ok("один и тот же день бывает СРАЗУ сегодняшним и выбранным",
           any(c["today"] and c["selected"] for w in both["weeks"] for c in w),
           "метки склеены — день перестанет быть и тем, и другим одновременно")
    oth_today = minical(date(2026, 9, 19), date(2026, 8, 31), MONTHS)
    res.ok("и день из ЧУЖОГО месяца тоже помечается сегодняшним",
           any(c["other"] and c["today"]
               for w in oth_today["weeks"] for c in w),
           "хвост прошлого месяца перестал подсвечиваться как сегодня")

    res.check("соседние месяцы ведут на ПЕРВОЕ число, а не на тот же день",
              (m["prev"]["date"], m["next"]["date"]), ("2026-08-01", "2026-10-01"))
    feb = minical(date(2026, 3, 31), today, MONTHS)
    res.check("и короткий месяц это не ломает: 31 марта → февраль и апрель",
              (feb["prev"]["date"], feb["next"]["date"]),
              ("2026-02-01", "2026-04-01"))
    res.ok("адрес каждой клетки несёт СВОЙ день",
           all(c["href"].endswith(c["date"]) for c in flat)
           and len({c["href"] for c in flat}) == 35,
           "клетки ведут на один адрес — по календарю нельзя перейти")
    res.check("шесть недель тоже бывает — март 2026 начинается в воскресенье",
              len(minical(date(2026, 3, 15), today, MONTHS)["weeks"]), 6)
    # точки (08.10): четвёртая метка, независимая от трёх, по множеству дат
    dotted = minical(sep, today, MONTHS, busy={date(2026, 9, 19), date(2026, 8, 31)})
    res.check("день с записью помечен точкой, в том числе чужой и выбранный",
              [c["date"] for w in dotted["weeks"] for c in w if c["busy"]],
              ["2026-08-31", "2026-09-19"])
    res.ok("без множества дат точек нет ни у кого",
           not any(c["busy"] for c in flat), "точка без записи")
