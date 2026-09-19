"""Правая колонка панели данными: повестка дня (C27.2).

Два набора и разделение между ними несущее.

⛔ **Чистый** (`suite_agenda_pure`) подаёт строки словарями и НАЗЫВАЕТ момент:
только так тройное состояние `future`/`current`/`past` проверяется на границах
и не зависит от того, в котором часу запустили прогон. Набор, считающий «сейчас»
из настоящих часов, был бы зелёным днём и красным в полночь — ровно та болезнь,
из-за которой в проекте берут `harness.clinic_today()`, а не `date.today()`.

⛔ **Паритетный** (`suite_agenda_parity`) сверяет модель с тем, что печатает
страница, и сравнивает их в ОДИН момент времени: `past` у страницы и `state` у
модели обязаны говорить одно и то же, какой бы ни был час.

⚠️ Оба набора нужны вместе. Чистый не заметит, что страница печатает другое;
паритетный не заметит, что оба считают неверно — он сверяет их между собой.
"""
import pathlib
import re
import sys
from datetime import date, datetime, timedelta

from harness import Client, Result, Server, clinic_today

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import engine as eng                                      # noqa: E402
from app.modules.schedule.panel import (agenda, agenda_state,      # noqa: E402
                                        series_of, spark_span, tiles)
from app.modules.schedule.routes import _AG_CLS, _svc_colors       # noqa: E402

from test_admin_canvas import _add, _agenda, _ids                   # noqa: E402

# Плитка «Azi» на странице: класс, адрес, число и подпись.
# ⚠️ Разбор идёт по АТРИБУТАМ (`href`, `data-count`), а не по тексту: адрес
# отбора и оформление особой плитки живут именно там, и проверка по содержимому
# тега зеленела бы над сломанной ссылкой.
_TILE_RE = re.compile(
    r"<a class='rk-i([^']*)' href='([^']*)'>.*?<b data-count='(\d+)'>\d+</b>"
    r"<span class='rk-l'>([^<]+)</span>", re.S)

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
         "birth_year": None, "comment": "", "reminded_day": None,
         "waiting_at": kw.get("waiting_at"), "arrived_at": None, "has_rec": False}
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
    res.check("класс бейджа — из _AG_CLS, по одному на статус",
              [x["badge"]["cls"] for x in words["items"]],
              ["act", "wai", "trt", "off", "bad"])
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
               ("Gata", False, "off",
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

    # --- кнопка зубов и карточка ---
    who = _ag([_row(9, name="Cu"), _row(10, patient_id=None, name="Fara")],
              cards={900: 1})
    res.check("кнопка одонтограммы — только у визита С ПАЦИЕНТОМ",
              [x["patient_id"] for x in who["items"]], [1, None])
    res.check("карточка открывается только у того, у кого она есть",
              [x["clickable"] for x in who["items"]], [True, False])
    res.check("пустой день говорит числом, а не отсутствием поля",
              (_ag([])["count"], _ag([])["items"]), (0, []))


def suite_agenda_parity(res: Result) -> None:
    """Модель повестки говорит ТО ЖЕ, что печатает страница."""
    day = clinic_today().isoformat()
    urgent_svc = "pain"
    with Server() as s:
        c = Client(s.url).login()
        _add(c, day, "09:00", "d3", "Par Unu", 1, svc=urgent_svc)
        _add(c, day, "10:00", "d2", "Par Doi", 2)
        _add(c, day, "11:00", "d2", "Par Trei", 3, svc=urgent_svc)
        ids = _ids(c, day)
        # срочная ЗАВЕРШЁННАЯ: ветка, в которой «Urgent» обязан исчезнуть
        c.post(f"/admin/status/{ids[0]}", to="done", back=f"/admin?date={day}")
        # и пациент в приёмной — у него отметка времени
        c.post(f"/admin/status/{ids[1]}", to="waiting", back=f"/admin?date={day}")

        page = _agenda(c.get(f"/admin?date={day}&ui=legacy").body)
        import json as _json
        m = _json.loads(c.get(f"/api/schedule/live?date={day}").body)["data"]["agenda"]

        if not res.check("якорь: строки есть и там, и там",
                         (len(m["items"]), len(page["rows"]), m["count"]),
                         (3, 3, 3)):
            return
        res.check("ТЕ ЖЕ записи в ТОМ ЖЕ порядке",
                  [x["id"] for x in m["items"]], [int(r["id"]) for r in page["rows"]])
        res.check("час, имя и услуга совпадают",
                  [(x["time"], x["name"], x["service"]) for x in m["items"]],
                  [(r["time"], r["name"], r["service"]) for r in page["rows"]])
        res.check("цвет полосы — тот же",
                  [x["bar"] for x in m["items"]], [r["bar"] for r in page["rows"]])
        res.check("БЕЙДЖ: класс и слово — те же",
                  [(x["badge"]["cls"], x["badge"]["label"]) for x in m["items"]],
                  [(r["cls"], r["label"]) for r in page["rows"]])
        res.ok("и «Urgent» исчез у завершённой — ветка в фикстуре ЕСТЬ",
               any(r["label"] == "Urgent" for r in page["rows"])
               and not m["items"][0]["urgent"],
               "срочная завершённая не проверена: "
               f"{[(x['name'], x['urgent']) for x in m['items']]}")
        res.check("ПРИГЛУШЕНИЕ страницы и состояние модели говорят одно",
                  [x["state"] == "past" for x in m["items"]],
                  [r["past"] for r in page["rows"]])
        res.check("карточка открывается у тех же",
                  [x["clickable"] for x in m["items"]],
                  [bool(r["click"]) for r in page["rows"]])
        res.check("кнопка зубов — у тех же",
                  [x["patient_id"] is not None for x in m["items"]],
                  ["ag-odo" in r["tail"] for r in page["rows"]])
        # ⚠️ Сверка «приглушение = past» выше доказывает мало, если прогон идёт
        # утром: прошедших строк нет, и обе стороны пусты. Различающий случай —
        # ВЧЕРАШНИЙ день: страница там не приглушает НИЧЕГО намеренно («в чужом
        # дне „прошло" не значит ничего»), и модель обязана сказать `None`, а не
        # «past». Этот случай детерминирован в любой час.
        yday = (clinic_today() - timedelta(days=1)).isoformat()
        _add(c, yday, "09:00", "d2", "Ieri Unu", 4)
        p_y = _agenda(c.get(f"/admin?date={yday}&ui=legacy").body)
        m_y = _json.loads(c.get(f"/api/schedule/live?date={yday}").body)["data"]["agenda"]
        res.check("в ЧУЖОМ дне страница не приглушает, а модель не выдумывает «past»",
                  ([r["past"] for r in p_y["rows"]],
                   [x["state"] for x in m_y["items"]], m_y["today"]),
                  ([False], [None], False))

        res.ok("ожидание приехало отметкой, и на странице она та же",
               any(x["wait_since"] for x in m["items"])
               and all(f"data-wait-since='{x['wait_since']}'" in r["tail"]
                       for x, r in zip(m["items"], page["rows"]) if x["wait_since"]),
               "отметка ожидания разошлась со страницей — минуты у React и у "
               "старого экрана пошли бы вразнобой")


# --------------------------------------------- плитки «Azi» и их тренды


def suite_tiles_pure(res: Result) -> None:
    """Плитки списком, полярность неявок и четыре формы подписи."""
    span = [DAY - timedelta(days=13 - i) for i in range(14)]
    series = [[i for i in range(14)] for _ in range(5)]

    off = tiles(DAY, (10, 3, 7, 2, 1), (8, 2, 6, 2, 1), series,
                tg_on=False, bot_new=0)
    on = tiles(DAY, (10, 3, 7, 2, 1), (8, 2, 6, 2, 1), series,
               tg_on=True, bot_new=2)
    if not res.check("якорь: без бота плиток ЧЕТЫРЕ, с ботом — пять",
                     (len(off), len(on)), (4, 5)):
        return

    res.check("⛔ плитка бота ОТСУТСТВУЕТ, а не приезжает пустым местом",
              [x["key"] for x in off], ["total", "rec", "urg", "noshow"])
    res.check("и остальные сохраняют и порядок, и личность",
              [(x["key"], x["label"], x["value"]) for x in off],
              [(x["key"], x["label"], x["value"]) for x in on if x["key"] != "bot"])

    # --- ПОЛЯРНОСТЬ ---
    up = {x["key"]: x["sub"] for x in tiles(DAY, (10, 0, 7, 2, 3), (8, 0, 6, 2, 1),
                                            series, tg_on=False, bot_new=0)}
    res.check("рост ЗАПИСЕЙ — это `up`, рост НЕЯВОК — это `dn`",
              (up["total"]["dir"], up["total"]["diff"],
               up["noshow"]["dir"], up["noshow"]["diff"]),
              ("up", 2, "dn", 2))
    down = {x["key"]: x["sub"] for x in tiles(DAY, (6, 0, 7, 2, 0), (8, 0, 6, 2, 2),
                                              series, tg_on=False, bot_new=0)}
    res.check("и наоборот: меньше записей — `dn`, меньше неявок — `up`",
              (down["total"]["dir"], down["noshow"]["dir"]), ("dn", "up"))
    res.ok("направление приезжает ГОТОВЫМ, а не выводится из знака разницы",
           down["noshow"]["diff"] < 0 and down["noshow"]["dir"] == "up",
           "у неявок знак и направление совпали — общая функция направления "
           "забрала неявки себе, и рост неявок позеленеет")

    # --- ЧЕТЫРЕ ФОРМЫ ПОДПИСИ ---
    same = {x["key"]: x["sub"] for x in tiles(DAY, (8, 0, 6, 2, 1), (8, 0, 6, 2, 1),
                                              series, tg_on=False, bot_new=0)}
    res.check("«столько же, сколько вчера» — своя форма, без стрелки и разницы",
              (same["total"]["kind"], same["total"]["dir"],
               same["total"]["diff"], same["total"]["text"]),
              ("same", None, 0, "la fel ca ieri"))
    res.check("«на столько-то» — своя, с направлением и знаком",
              (up["total"]["kind"], up["total"]["text"]), ("delta", "față de ieri"))
    res.check("у СРОЧНЫХ тренда нет вовсе — у них постоянная подпись",
              (same["urg"]["kind"], same["urg"]["text"]),
              ("static", "intercalate azi"))
    res.check("а у бота — своя, про новые за сегодня",
              [(x["sub"]["kind"], x["sub"].get("new")) for x in on if x["key"] == "bot"],
              [("bot_new", 2)])
    res.check("и «ничего нового» — тоже отдельная, а не ноль в той же",
              [x["sub"]["kind"] for x in
               tiles(DAY, (10, 0, 7, 2, 1), (8, 0, 6, 2, 1), series,
                     tg_on=True, bot_new=0) if x["key"] == "bot"],
              ["static"])

    # --- АДРЕС ОТБОРА ---
    res.check("«Programări» ведёт в ВЕСЬ день — отбора у неё нет намеренно",
              [(x["key"], x["filter"]) for x in off],
              [("total", None), ("rec", "rec"), ("urg", "urg"), ("noshow", "noshow")])
    res.ok("и адрес у каждой свой, а не один на всех",
           len({x["href"] for x in off}) == len(off)
           and off[0]["href"] == f"/admin/all?date={DAY.isoformat()}",
           f"адреса совпали: {[x['href'] for x in off]}")

    # --- РЯДЫ ---
    res.check("ряд у каждой плитки — СВОЙ, длиной в две недели",
              [len(x["series"]) for x in off], [14, 14, 14, 14])
    metric = tiles(DAY, (10, 0, 7, 2, 1), (8, 0, 6, 2, 1),
                   [[1] * 14, [2] * 14, [3] * 14, [4] * 14, [5] * 14],
                   tg_on=False, bot_new=0)
    res.check("и ряд принадлежит СВОЕЙ метрике, а не соседней",
              {x["key"]: x["series"][0] for x in metric},
              {"total": 1, "rec": 3, "urg": 4, "noshow": 5})
    res.check("порядок ряда — от старого к новому, заканчивая днём экрана",
              (spark_span(DAY)[0], spark_span(DAY)[-1], len(spark_span(DAY))),
              (DAY - timedelta(days=13), DAY, 14))
    holes = {DAY - timedelta(days=13 - i): [] for i in range(14)}
    holes[DAY] = [_row(9), _row(10)]
    holes[DAY - timedelta(days=5)] = [_row(9, status="noshow")]
    ser = series_of(holes, spark_span(DAY))
    res.check("пустые дни — НУЛИ на своём месте, а не пропуски в ряду",
              (len(ser[0]), ser[0][-1], ser[0][0], ser[4][8]), (14, 2, 0, 1))


def suite_tiles_parity(res: Result) -> None:
    """Плитки модели против карточки «Azi» на странице — и с ботом, и без."""
    day = clinic_today().isoformat()
    import json as _json

    def _page_tiles(body: str) -> list:
        block = re.search(r"<div class='rkpi'>.*?(?=<div class='rk-occ'>)", body, re.S)
        if not block:
            return []
        return [{"cls": m.group(1).strip(), "href": m.group(2).replace("&amp;", "&"),
                 "value": int(m.group(3)), "label": m.group(4)}
                for m in _TILE_RE.finditer(block.group(0))]

    with Server() as s:
        c = Client(s.url).login()
        _add(c, day, "09:00", "d2", "Kpi Unu", 1)
        _add(c, day, "10:00", "d3", "Kpi Doi", 2, svc="pain")
        page = _page_tiles(c.get(f"/admin?date={day}&ui=legacy").body)
        m = _json.loads(c.get(f"/api/schedule/live?date={day}").body)["data"]
        if not res.check("якорь: у клиники без бота плиток четыре и там, и там",
                         (len(page), len(m["tiles"])), (4, 4)):
            return
        res.check("те же плитки, в том же порядке, с теми же числами",
                  [(x["label"], x["value"]) for x in m["tiles"]],
                  [(x["label"], x["value"]) for x in page])
        res.check("и адреса отбора — те же",
                  [x["href"] for x in m["tiles"]], [x["href"] for x in page])
        res.check("и оформление особых плиток — то же",
                  [x["cls"] for x in m["tiles"]], [x["cls"] for x in page])
        res.ok("загрузка кресел приехала отдельно от плиток — у неё нет ссылки",
               m["occupancy"]["value"] == int(
                   re.search(r"data-count='(\d+)' data-suffix='%'",
                             c.get(f"/admin?date={day}&ui=legacy").body).group(1)),
               "процент загрузки разошёлся со страницей")

    # ⛔ Вторая ветка — с ботом. Без неё мутация «вернуть плитку бота» осталась
    # бы зелёной: у клиники без бота её и так нет, и проверка «плиток четыре»
    # прошла бы над кодом, который просто не умеет её строить.
    with Server(env={"DENTART_TOKEN_UNREADABLE": "1"}) as s2:
        c2 = Client(s2.url).login()
        _add(c2, day, "09:00", "d2", "Kpi Bot", 3)
        page2 = _page_tiles(c2.get(f"/admin?date={day}&ui=legacy").body)
        m2 = _json.loads(c2.get(f"/api/schedule/live?date={day}").body)["data"]
        res.check("у grandfather-клиники плитка бота ЕСТЬ — и там, и там",
                  ([x["label"] for x in m2["tiles"]],
                   [x["label"] for x in page2]),
                  (["Programări", "Prin bot", "Recepție", "Urgențe", "Neprezentări"],
                   ["Programări", "Prin bot", "Recepție", "Urgențe", "Neprezentări"]))
        res.check("и стоит она ВТОРОЙ, а не в конце",
                  [x["key"] for x in m2["tiles"]][:2], ["total", "bot"])
