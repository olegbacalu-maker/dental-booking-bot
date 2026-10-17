"""Запись и отказы: журнал, фиша, интервалы, границы прошлого.

Это ядро продукта — если что-то из этого молча изменится, клиника посадит двух
пациентов в одно кресло или потеряет визит в прошлом.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta

from harness import (TG_ON, TZ, Bot, Client, Result, Server, add_appt, appt_id, clinic_today,
                     day_model, panel_live, pid_by_phone)

PHONE = "022111222"


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def add(c: Client, day: str, time: str, doctor: str = "d2",
        service: str = "consult", name: str = "Ion Testescu",
        phone: str = PHONE, birth: str = "") -> str:
    """Ручная запись окном «Programare nouă» — код ответа."""
    return add_appt(c, day, time, name, phone, doctor, service, birth=birth).msg


def _rows(c: Client, q: str) -> list[dict]:
    """Строки списка «Pacienți» по поиску (`GET /api/patients?q=`)."""
    return json.loads(c.get(f"/api/patients?q={q}").body)["data"]["rows"]


def _card(c: Client, pid) -> dict:
    """Фиша данными (`GET /api/patients/{pid}`) — то, что рисует экран."""
    return json.loads(c.get(f"/api/patients/{pid}").body)["data"]


def suite(res: Result) -> None:
    # grandfather-клиника: в середине набора идёт проверка «визит задним числом
    # tg-пациенту», а канал бота живёт только за tg_configured (заморозка 08-08)
    with Server(env=TG_ON) as s:
        c = Client(s.url).login()

        # --- обычная запись ---
        # ⛔ Семейный телефон (находка аудита 08-10). Ребёнка записывают на
        # номер родителя — в Молдове это норма. Ветка «ровно одно совпадение
        # цифр» пишет визит родителю, и дальше дата рождения РЕБЁНКА затирала
        # родительскую: без истории, без предупреждения, с зелёным «ok».
        # Дальше одонтограмма и 043/e ребёнка печатались под именем матери.
        # Склейку визита чинит отдельное решение (переспросить регистратуру),
        # а вот чужую дату рождения принимать нельзя ни при каких условиях.
        # ⚠️ ОТДЕЛЬНЫЙ день: соседние проверки набора считают слоты _d(1)
        # своими, и две записи здесь ломали им «тот же пациент, другой час».
        FAM = "069777111"
        res.check("мать записана", add(c, _d(6), "11:00", name="Maria Popescu",
                                       phone=FAM, birth="1984-03-05"), "ok")
        # ⛔ Визит проходит, но регистратуре ГОВОРЯТ, что он лёг в чужую
        # карточку: молчаливое «ok» здесь и есть способ потерять историю
        # ребёнка внутри карточки матери.
        res.check("чужое имя на том же номере — предупреждение, а не тихое ok",
                  add(c, _d(6), "12:00", name="Andrei Popescu",
                      phone=FAM, birth="2016-07-19"), "ok_other")
        res.check("то же имя на том же номере проходит молча",
                  add(c, _d(6), "13:00", name="Maria Popescu", phone=FAM), "ok")
        res.check("дата рождения матери уцелела (в списке одна фиша, дата её)",
                  [r["birth"] for r in _rows(c, FAM)], ["05.03.1984"])

        res.check("первая запись проходит", add(c, _d(1), "10:00"), "ok")
        res.check("час занят у этого врача",
                  add(c, _d(1), "10:00", name="Alt Pacient", phone="022999888"),
                  "conflict")
        res.check("тот же час у другого врача — свободен",
                  add(c, _d(1), "10:00", doctor="d3", name="Alt Pacient",
                      phone="022999888"), "ok")

        # --- отказ не заводит пациента-сироту (08-07) ---
        # upsert шёл ДО проверки занятости, и «интервал занят» оставлял
        # карточку без единого визита — она копилась в списке пациентов
        res.check("занятый час — отказ", add(c, _d(1), "10:00",
                  name="Orfan Test", phone="022808080"), "conflict")
        res.check("отказ НЕ завёл карточку-сироту", _rows(c, "022808080"), [])

        # --- дубль пациента: тот же человек на тот же час ---
        # ⚠️ ловилось по тексту ошибки SQLite и не срабатывало никогда (1.11.1)
        res.check("тот же пациент, другой врач — дубль",
                  add(c, _d(1), "10:00", doctor="d4"), "dup")
        res.check("тот же пациент, другой час — проходит",
                  add(c, _d(1), "11:00"), "ok")

        # --- интервалы: длинная услуга накрывает соседние получасы ---
        res.check("длинная услуга (120') записалась",
                  add(c, _d(2), "12:00", service="long", name="Lung Unu",
                      phone="022700100"), "ok")
        res.check("старт внутри длинного визита занят",
                  add(c, _d(2), "13:00", service="consult", name="Lung Doi",
                      phone="022700200"), "conflict")
        res.check("старт сразу после длинного визита свободен",
                  add(c, _d(2), "14:00", service="consult", name="Lung Trei",
                      phone="022700300"), "ok")

        # --- границы прошлого: запрет мгновенный, предупреждение дневное ---
        res.check("вчерашний день — принимаем, но предупреждаем",
                  add(c, _d(-1), "10:00", name="Ieri", phone="022700400"),
                  "ok_past")
        res.check("опечатка в годе — тоже предупреждение",
                  add(c, f"{clinic_today().year - 1}-{clinic_today():%m-%d}", "09:00",
                      name="Typo", phone="022700500"), "ok_past")
        now = datetime.now(TZ)
        if 9 <= now.hour <= 21:      # «два часа назад» должно попасть в график 7–21
            res.check("сегодня в прошедший час — обычная работа, без баннера",
                      add(c, _d(0), f"{now.hour - 2:02d}:00", doctor="d4",
                          name="Walk In", phone="022700600"), "ok")

        # --- телефон: 6–15 цифр, иностранные номера принимаются (08-07) ---
        res.check("телефон короче 6 цифр",
                  add(c, _d(3), "10:00", phone="060"), "bad_phone")
        res.check("телефон длиннее 15 цифр",
                  add(c, _d(3), "10:00", phone="+00 1234567890123456"),
                  "bad_phone")
        res.check("немецкий номер проходит",
                  add(c, _d(3), "10:00", name="Hans Weber",
                      phone="+49 151 2345678"), "ok")
        res.check("короткий европейский (6 цифр) проходит",
                  add(c, _d(3), "13:00", name="Kort Nummer",
                      phone="123456"), "ok")

        # --- полная дата рождения из формы записи (была только год, 08-07) ---
        res.check("запись с датой рождения проходит",
                  add(c, _d(3), "14:00", name="Cu Data", phone="022700700",
                      birth="1990-05-15"), "ok")
        res.check("дата рождения видна в фише целиком (dd.mm.yyyy)",
                  _card(c, pid_by_phone(c, "022700700"))["profile"]["birth"], "15.05.1990")
        res.check("дата рождения в будущем — именованный отказ",
                  add(c, _d(3), "14:30", name="Viitor", phone="022700800",
                      birth=_d(30)), "bad_bd")

        # --- визит задним числом пациенту из БОТА (08-07) ---
        # раньше ручная запись искала по ключу manual:<цифры>, а у пациента из бота
        # ключ свой (tg:… у Telegram, web:… у веб-чата) — и вчерашний визит
        # уезжал КАРТОЧКЕ-ДВОЙНИКУ. Теперь пациент ищется по цифрам номера
        # среди всех существующих.
        tgb = Bot(Client(s.url), "t-tg-past")
        tgb.say("/start"); tgb.say("lang:ro"); tgb.say("book")
        tgb.say("svc:consult"); tgb.say("doc:d2"); tgb.say(f"day:{_d(4)}")
        tgb.say(f"time:{_d(4)}T09:00"); tgb.say("Ion Telegram")
        tgb.say("skip_year"); tgb.say("069010203"); tgb.say("confirm")
        res.check("вчерашний визит tg-пациенту принимается (др. формат номера)",
                  add(c, _d(-2), "12:00", name="Ion T.",
                      phone="069 010 203"), "ok_past")
        found = [r["id"] for r in _rows(c, "069010203")]
        res.ok("карточка ОДНА — двойник не завёлся", len(found) == 1,
               f"нашлось {len(found)} карточек")
        card = _card(c, found[0])
        res.ok("визит задним числом лёг в ту же карточку",
               any(v["when"] == f"{(clinic_today() - timedelta(days=2)):%d.%m.%Y} 12:00"
                   for v in card["visits"]["history"]),
               f"вчерашнего визита нет в фише tg-пациента: {card['visits']['history']}")
        res.check("имя из формы журнала не переименовало пациента",
                  card["name"], "Ion Telegram")

        # --- прочие отказы, каждый со своим текстом ---
        res.check("пустое имя", add(c, _d(3), "10:30", name="   "), "bad_name")
        res.check("врач в архиве", add(c, _d(3), "11:00", doctor="d1"), "bad_off")
        res.check("время не по получасовой сетке",
                  add(c, _d(3), "11:15"), "bad_time")
        res.check("неизвестная услуга",
                  add(c, _d(3), "12:00", service="nope"), "bad")
        res.check("неизвестный врач",
                  add(c, _d(3), "12:30", doctor="d9"), "bad")


def suite_card(res: Result) -> None:
    """Запись из фиши пациента: пишется ПО ID, прошлое не принимает."""
    with Server() as s:
        c = Client(s.url).login()
        add(c, _d(1), "09:00", name="Fisa Pacient", phone="022123456")

        pid = str(pid_by_phone(c, "022123456"))
        res.ok("пациент найден поиском", pid.isdigit(), f"pid={pid!r}")

        def appoint(day: str, time: str, doctor: str = "d3",
                    service: str = "consult") -> str:
            return c.post_json(f"/api/patients/{pid}/appoint", {"date": day, "time": time,
                                                               "doctor": doctor,
                                                               "service": service}).msg

        res.check("из фиши в будущее — проходит", appoint(_d(2), "15:00"), "ok")
        res.check("из фиши во вчера — запрет", appoint(_d(-1), "10:00"), "past")
        now = datetime.now(TZ)
        if 9 <= now.hour <= 21:
            res.check("из фиши в прошедший час сегодня — запрет",
                      appoint(_d(0), f"{now.hour - 2:02d}:00"), "past")
        res.check("из фиши к архивному врачу", appoint(_d(2), "16:00", "d1"),
                  "bad_off")
        res.check("из фиши дубль своего часа",
                  appoint(_d(2), "15:00", doctor="d4"), "dup")

        # визит из фиши обязан лежать в ЭТОЙ карточке, а не у двойника
        hist = _card(c, pid)["visits"]["history"]
        res.ok("визит виден в карточке пациента",
               any(v["when"] == f"{(clinic_today() + timedelta(days=2)):%d.%m.%Y} 15:00"
                   for v in hist), f"в карточке нет визита в 15:00: {hist}")
        res.check("двойник не появился: по номеру в списке одна фиша, эта",
                  [str(r["id"]) for r in _rows(c, "022123456")], [pid])


def _row_of(c: Client, day: str, name: str) -> dict:
    """Строка «Lista zilei» с этим пациентом — чтобы читать врача и час."""
    return next((r for r in day_model(c, day)["list"] if r["name"] == name), {})


def _block(canvas: dict, name: str = "", aid: int = 0) -> dict:
    """Блок визита на канве — по номеру записи или по имени пациента (панель
    и «Programări» рисуют одну канву — 06.10). ⚠️ У пациента может быть два
    визита в дне: тогда искать по номеру, имя найдёт первый по колонкам."""
    return next((b for col in canvas["columns"] for b in col["blocks"]
                 if (b.get("id") == aid if aid else b.get("name") == name)), {})


def suite_move(res: Result) -> None:
    """Перенос визита перетаскиванием: маршрут переноса и поля канвы обоих
    экранов дня.

    ⚠️ Проверять надо СЕРВЕР, а не мышь: перетаскивание живёт в браузере
    (`DashCanvas`), но решение принимает маршрут. Он же — единственная защита
    от устаревшей вкладки: пока визит тянули, час мог занять бот.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        add(c, day, "10:00", doctor="d2", name="Mutat Unu", phone="022700111")
        aid = appt_id(c, day, "Mutat Unu")

        def move(to_time: str, to_doc: str = "d3", appt: int = 0) -> str:
            return c.post_json(f"/api/schedule/appointments/{appt or aid}/move",
                               {"date": day, "time": to_time, "doctor": to_doc}).msg

        # --- перенос к другому врачу НА ТОТ ЖЕ ЧАС ---
        # ⛔ Тот самый случай, ради которого _patient_busy_at получил exclude_id:
        # визит находит САМ СЕБЯ на этом старте и без исключения отказал бы
        # «у пациента уже есть запись» — то есть из-за себя же.
        res.check("перенос к другому врачу на тот же час", move("10:00"), "ok_move")
        res.check("визит переехал к новому врачу",
                  _row_of(c, day, "Mutat Unu").get("doctor"), "Dr. Activ Trei")

        # ⚠️ Перенос — событие фиши, а не только сетки: закон 195 спрашивает
        # «кто именно двигал визит», и без строки в летописи ответить нечем.
        feed = [a["text"] for a in _card(c, pid_by_phone(c, "022700111"))["activity"]["items"]]
        res.ok("перенос записан в летопись пациента — с новым врачом",
               any("Vizită mutată" in t and "Activ Trei" in t for t in feed),
               "фиша не помнит переноса — по журналу доступа не восстановить, кто двигал")

        # --- полчаса и час ---
        res.check("перенос на полчаса вперёд", move("10:30"), "ok_move")
        res.check("новый час виден в списке",
                  _row_of(c, day, "Mutat Unu").get("time"), "10:30")
        res.check("четверть часа не принимается", move("10:15"), "bad_time")
        res.check("выключенному врачу не переносим", move("11:00", "d1"), "bad_off")

        # --- занятый интервал ---
        add(c, day, "12:00", doctor="d2", name="Ocupa Ora", phone="022700222")
        res.check("перенос в занятый интервал отбит", move("12:00", "d2"), "conflict")
        res.check("отбитый визит остался на месте",
                  _row_of(c, day, "Mutat Unu").get("time"), "10:30")

        # --- у ПАЦИЕНТА уже есть визит на этот час ---
        add(c, day, "15:00", doctor="d2", name="Mutat Unu", phone="022700111")
        res.check("двойник у пациента отбит", move("15:00", "d3"), "dup")

        # --- закрытые записи не двигаются ---
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "done"})
        res.check("завершённый визит не переносится", move("16:00"), "mv_closed")
        res.check("несуществующая запись", move("16:00", appt=999999), "mv_gone")

        # --- поля перетаскивания: договор один на ОБА экрана дня ---
        for where, canvas in (("панель", panel_live(c, day)["canvas"]),
                              ("«Programări»", day_model(c, day)["canvas"])):
            live = _block(canvas, "Ocupa Ora")
            res.check(f"{where}: активный визит можно тащить, и он занимает час",
                      (live.get("movable"), live.get("busy")), (True, True))
            done = _block(canvas, aid=aid)
            res.check(f"{where}: завершённый визит не тащится и не занимает час",
                      (done.get("id"), done.get("movable"), done.get("busy")),
                      (aid, False, False))

    # закрытый час не принимает бросок: сервер отбивает, канва не предлагает
    # (клиника 07-21, врачи 09-17, обед 13-14)
    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        day = _d(1)
        add(c, day, "10:00", doctor="d2", name="Pauza Drop", phone="022700333")
        res.check("перенос в обеденный час отбит",
                  c.post_json(f"/api/schedule/appointments/{appt_id(c, day, 'Pauza Drop')}/move",
                              {"date": day, "time": "13:00", "doctor": "d2"}).msg, "outside")
        canvas = panel_live(c, day)["canvas"]
        hours = [h["h"] for h in canvas["hours"]]
        col = next((x for x in canvas["columns"] if x["id"] == "d2"), None)
        res.ok("обеденная ячейка канвы не мишень",
               col is not None and 13 in hours and not col["cells"][hours.index(13)],
               f"закрытый час канвы принимает бросок: ряды {hours}")


def suite_status(res: Result) -> None:
    """Статусы визита и заметки-блокировки слота."""
    with Server() as s:
        c = Client(s.url).login()
        add(c, _d(1), "10:00", name="Status Test", phone="022555111")
        aid1 = appt_id(c, _d(1), "Status Test")

        # ⚠️ С 17.10 переход — по ребру матрицы кнопок: из «finalizată» в
        # «отмену» дороги нет, сперва «Redeschide» (confirmed), как на экране
        for status in ("arrived", "done", "confirmed", "cancelled"):
            r = c.post_json(f"/api/schedule/appointments/{aid1}/status", {"to": status})
            res.check(f"статус → {status}", (r.status, r.msg), (200, ""))

        # отменённый час освободился
        res.check("после отмены час снова свободен",
                  add(c, _d(1), "10:00", name="Dupa Anulare", phone="022555222"),
                  "ok")

        # ⛔ переоткрыть в занятый час нельзя: слот 10:00 уже держит «Dupa
        # Anulare», и возврат обязан ответить «intervalul e ocupat», а не
        # посадить двоих в одно кресло
        res.check("возврат в занятый час отбит",
                  c.post_json(f"/api/schedule/appointments/{aid1}/status",
                              {"to": "confirmed"}).msg, "conflict")

        # --- кнопки исхода зависят от СОСТОЯНИЯ записи (08-12) ---
        # Кнопки карточки и «Lista zilei» экран берёт из матрицы `actions` по
        # состоянию записи из `cards` — оба ответа сервера; своих кнопок у
        # клиента нет. Поэтому и проверка идёт по ним.
        add(c, _d(2), "10:00", name="Buton Test", phone="022555444")
        bid = appt_id(c, _d(2), "Buton Test")

        def buttons() -> dict:
            """{куда: спрашивает ли} — кнопки исхода записи `bid` сейчас."""
            m = day_model(c, _d(2))
            st = m["cards"][str(bid)]["status"]
            return {a["to"]: bool(a["confirm"]) for a in m["actions"][st]}

        def row() -> dict:
            return _row_of(c, _d(2), "Buton Test")

        # 03.10, слово Олега: «Anulează сразу удаляет… нужно сначала спросить» —
        # вопрос у отмены, и ТОЛЬКО у неё среди шагов приёма
        res.check("записи предложены все пять исходов, спрашивает только «Anulează»",
                  buttons(), {"waiting": False, "arrived": False, "done": False,
                              "noshow": False, "cancelled": True})

        c.post_json(f"/api/schedule/appointments/{bid}/status", {"to": "arrived"})
        b = buttons()
        res.ok("тому, кто уже в кресле, «A sosit» и «Nu a venit» не предлагают",
               "arrived" not in b and "noshow" not in b and "done" in b,
               f"кнопки в кресле не сузились — предлагаем записать неправду: {b}")

        c.post_json(f"/api/schedule/appointments/{bid}/status", {"to": "done"})
        res.check("у закрытой записи остаётся ровно возврат",
                  list(buttons()), ["confirmed"])
        # плашка обязана звать статус словом кнопки, а не «a venit»
        res.check("плашка статуса в списке — «finalizată»",
                  (row().get("status"), row().get("status_label")), ("done", "finalizată"))
        blk = _block(day_model(c, _d(2))["canvas"], "Buton Test")
        res.check("та же отметка стоит и на канве «Programări»",
                  (blk.get("status"), blk.get("status_label")), ("done", "finalizată"))

        res.check("возврат открывает запись заново",
                  c.post_json(f"/api/schedule/appointments/{bid}/status",
                              {"to": "confirmed"}).msg, "")
        b = buttons()
        res.ok("после возврата исходы снова доступны",
               "arrived" in b and "confirmed" not in b,
               f"возврат не вернул запись в работу: {b}")

        # --- «A venit» (waiting, 08-13): пациент пришёл и ждёт в приёмной ---
        r = c.post_json(f"/api/schedule/appointments/{bid}/status", {"to": "waiting"})
        res.check("статус → waiting принят", (r.status, r.msg), (200, ""))
        b = buttons()
        res.ok("пришедшему не предлагают «Nu a venit», но дают ход дальше",
               "noshow" not in b and "arrived" in b and "done" in b,
               f"кнопки waiting предлагают неправду или прячут следующий шаг: {b}")
        res.check("плашка «a venit» стоит словом и в списке, и на канве",
                  (row().get("status_label"),
                   _block(day_model(c, _d(2))["canvas"], "Buton Test").get("status_label")),
                  ("a venit", "a venit"))
        # «așteaptă N min» (08-21): сервер кладёт ТОЛЬКО отметку `wait_since`
        # (блоку канвы и пункту повестки), минуты считает браузер — серверная
        # строка минут делала бы отпечаток живого состояния всегда другим, и
        # экран перерисовывался бы каждый опрос (ревью 08-22: фича была без
        # единой проверки). Дом ожидания — панель дня (канва + повестка).
        live = panel_live(c, _d(2))
        item = next((x for x in live["agenda"]["items"] if x["name"] == "Buton Test"), {})
        res.ok("отметка ожидания стоит на канве панели",
               isinstance(_block(live["canvas"], "Buton Test").get("wait_since"), int),
               "wait_since не доехал до канвы — браузеру нечего считать")
        res.ok("отметка ожидания стоит в повестке",
               isinstance(item.get("wait_since"), int),
               f"wait_since не доехал до повестки дня: {item}")
        res.ok("минуты ожидания сервер не печатает",
               "așteaptă" not in json.dumps(live, ensure_ascii=False),
               "серверные минуты = недетерминированный живой отпечаток")
        # слот пришедшего ЗАНЯТ: ACTIVE_STATUSES и предикаты uq-индексов
        # обязаны знать waiting, иначе двойная бронь проходит молча
        res.check("час пришедшего занят для новой записи",
                  add(c, _d(2), "10:00", name="Peste Waiting", phone="022555666"),
                  "conflict")
        # второй шаг конвейера необязателен: из приёмной можно сразу в финал
        c.post_json(f"/api/schedule/appointments/{bid}/status", {"to": "done"})
        res.check("из «a venit» можно сразу в «finalizată»",
                  row().get("status"), "done")
        c.post_json(f"/api/schedule/appointments/{bid}/status", {"to": "confirmed"})

        # --- время ожидания (08-13): пара штампов waiting_at→arrived_at ---
        # Полный конвейер на отдельном визите. Карточку «Așteptare medie»
        # рисовала только старая страница статистики (снята 12.10), поэтому
        # смотрим сами штампы в базе: пара обязана записаться.
        def stamps(aid: str) -> tuple:
            con = sqlite3.connect(str(s.dir / "dental.db"))
            try:
                return con.execute("SELECT waiting_at, arrived_at FROM appointments "
                                   "WHERE id = ?", (int(aid),)).fetchone()
            finally:
                con.close()

        add(c, _d(3), "11:00", name="Metrica Wait", phone="022555777")
        wid = appt_id(c, _d(3), "Metrica Wait")
        c.post_json(f"/api/schedule/appointments/{wid}/status", {"to": "waiting"})
        c.post_json(f"/api/schedule/appointments/{wid}/status", {"to": "arrived"})
        res.ok("пара штампов ожидания записана",
               all(stamps(wid)), f"штампы: {stamps(wid)!r}")
        # возврат в confirmed стирает ОБА штампа: исправленный промах «A venit»
        # не имеет права оставить мусорную пару в измерении
        c.post_json(f"/api/schedule/appointments/{wid}/status", {"to": "confirmed"})
        res.check("возврат в confirmed стирает оба штампа", stamps(wid), (None, None))

        # --- возврат визита, когда занят ПАЦИЕНТ, а не врач (08-16) ---
        # ⛔ Отказ у смены статуса ОДИН, а причин две, и они чинятся
        # по-разному. Здесь час у Dr. Activ Doi свободен, занят пациент —
        # регистратура, прочитавшая «intervalul e ocupat la acest medic»,
        # смотрит на пустой час врача и сделать не может ничего.
        # ⚠️ Причину спрашивают у ДАННЫХ: текст исключения у двух бэкендов
        # разный, и ветка сообщения отмерла бы молча (грабли _book).
        d4 = _d(4)
        res.check("визит к первому врачу заведён",
                  add(c, d4, "12:00", doctor="d2", name="Dubla Pacient",
                      phone="022555999"), "ok")
        did = appt_id(c, d4, "Dubla Pacient")
        c.post_json(f"/api/schedule/appointments/{did}/status", {"to": "cancelled"})
        res.check("тот же пациент записан на тот же час к другому врачу",
                  add(c, d4, "12:00", doctor="d3", name="Dubla Pacient",
                      phone="022555999"), "ok")
        res.check("возврат отбит словами про ПАЦИЕНТА, а не про медика",
                  c.post_json(f"/api/schedule/appointments/{did}/status",
                              {"to": "confirmed"}).msg, "dup")

        # заметка занимает слот врача
        r = c.post_json("/api/schedule/notes", {"date": _d(1), "time": "14:00", "doctor": "d3",
                                               "text": "Pauză tehnică"})
        res.ok("заметка сохранена", r.msg in ("ok_note", "part_note"),
               f"msg={r.msg!r}")
        res.check("час с заметкой занят для записи",
                  add(c, _d(1), "14:00", doctor="d3", name="Blocat",
                      phone="022555333"), "conflict")
