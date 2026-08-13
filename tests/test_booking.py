"""Запись и отказы: журнал, фиша, интервалы, границы прошлого.

Это ядро продукта — если что-то из этого молча изменится, клиника посадит двух
пациентов в одно кресло или потеряет визит в прошлом.
"""
import re
from datetime import date, datetime, timedelta

from harness import TG_ON, Bot, Client, Result, Server

PHONE = "022111222"


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def add(c: Client, day: str, time: str, doctor: str = "d2",
        service: str = "consult", name: str = "Ion Testescu",
        phone: str = PHONE, year: str = "", birth: str = "") -> str:
    return c.post("/admin/add", adate=day, atime=time, adoctor=doctor,
                  aservice=service, aname=name, aphone=phone, ayear=year,
                  abirth=birth, back="/admin/all").msg


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
        card = c.get(f"/admin/search?q={FAM}").body
        res.ok("дата рождения матери уцелела",
               "1984" in card and "2016" not in card,
               "дата ребёнка затёрла родительскую — так теряется анамнез")

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
        res.ok("отказ НЕ завёл карточку-сироту",
               not re.findall(r"/admin/patient/(\d+)",
                              c.get("/admin/search?q=022808080").body),
               "пациент без визита появился в списке")

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
                  add(c, f"{date.today().year - 1}-{date.today():%m-%d}", "09:00",
                      name="Typo", phone="022700500"), "ok_past")
        now = datetime.now()
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
        pid = c.get("/admin/search?q=022700700").body.split(
            "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]
        card = c.get(f"/admin/patient/{pid}").body
        res.ok("дата рождения видна в фише целиком (dd.mm.yyyy)",
               "15.05.1990" in card, "в фише нет дня и месяца")
        res.check("дата рождения в будущем — именованный отказ",
                  add(c, _d(3), "14:30", name="Viitor", phone="022700800",
                      birth=_d(30)), "bad_bd")
        res.check("год отдельным полем (устаревшая вкладка) ещё принимается",
                  add(c, _d(3), "15:00", name="Doar An", phone="022700900",
                      year="1980"), "ok")

        # --- визит задним числом пациенту из БОТА (08-07) ---
        # раньше /admin/add искал по ключу manual:<цифры>, у tg-пациента ключ
        # tg:… — и вчерашний визит уезжал КАРТОЧКЕ-ДВОЙНИКУ. Теперь пациент
        # ищется по цифрам номера среди всех существующих.
        tgb = Bot(Client(s.url), "t-tg-past")
        tgb.say("/start"); tgb.say("lang:ro"); tgb.say("book")
        tgb.say("svc:consult"); tgb.say("doc:d2"); tgb.say(f"day:{_d(4)}")
        tgb.say(f"time:{_d(4)}T09:00"); tgb.say("Ion Telegram")
        tgb.say("skip_year"); tgb.say("069010203"); tgb.say("confirm")
        res.check("вчерашний визит tg-пациенту принимается (др. формат номера)",
                  add(c, _d(-2), "12:00", name="Ion T.",
                      phone="069 010 203"), "ok_past")
        found = set(re.findall(r"/admin/patient/(\d+)",
                               c.get("/admin/search?q=069010203").body))
        res.ok("карточка ОДНА — двойник не завёлся", len(found) == 1,
               f"нашлось {len(found)} карточек")
        card = c.get(f"/admin/patient/{sorted(found)[0]}").body
        res.ok("визит задним числом лёг в ту же карточку", "12:00" in card,
               "вчерашнего визита нет в фише tg-пациента")
        res.ok("имя из формы журнала не переименовало пациента",
               "Ion Telegram" in card, "«Ion T.» затёр имя из бота")

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

        html = c.get("/admin/search?q=022123456").body
        pid = html.split("/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]
        res.ok("пациент найден поиском", pid.isdigit(), f"pid={pid!r}")

        def appoint(day: str, time: str, doctor: str = "d3",
                    service: str = "consult") -> str:
            return c.post(f"/admin/patient/{pid}/appoint", adate=day, atime=time,
                          adoctor=doctor, aservice=service).msg

        res.check("из фиши в будущее — проходит", appoint(_d(2), "15:00"), "ok")
        res.check("из фиши во вчера — запрет", appoint(_d(-1), "10:00"), "past")
        now = datetime.now()
        if 9 <= now.hour <= 21:
            res.check("из фиши в прошедший час сегодня — запрет",
                      appoint(_d(0), f"{now.hour - 2:02d}:00"), "past")
        res.check("из фиши к архивному врачу", appoint(_d(2), "16:00", "d1"),
                  "bad_off")
        res.check("из фиши дубль своего часа",
                  appoint(_d(2), "15:00", doctor="d4"), "dup")

        # визит из фиши обязан лежать в ЭТОЙ карточке, а не у двойника
        card = c.get(f"/admin/patient/{pid}").body
        res.ok("визит виден в карточке пациента", "15:00" in card,
               "в карточке нет времени 15:00")
        res.ok("двойник не появился",
               c.get("/admin/search?q=022123456").body.count("/admin/patient/") >= 1,
               "пациент пропал из поиска")


def _row_of(page: str, name: str) -> str:
    """Строка «Lista zilei» с этим пациентом — чтобы читать врача и час.

    ⚠️ Ищем ПОСЛЕ заголовка списка: выше на странице стоит сетка дня, её ряды
    тоже `<tr>` и тоже содержат имя пациента — но без кнопок статуса.
    """
    page = page.split("Lista zilei", 1)[-1]
    for m in re.finditer(r"<tr class='[^']*'>.*?</tr>", page, re.S):
        if name in m.group(0):
            return m.group(0)
    return ""


def suite_move(res: Result) -> None:
    """Перенос визита перетаскиванием: /admin/move и разметка обеих страниц.

    ⚠️ Проверять надо СЕРВЕР, а не мышь: браузерное перетаскивание живёт в
    panel.js, но решение принимает маршрут. Он же — единственная защита от
    устаревшей вкладки: пока визит тянули, час мог занять бот.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        add(c, day, "10:00", doctor="d2", name="Mutat Unu", phone="022700111")
        page = c.get(f"/admin/all?date={day}").body
        aid = _row_of(page, "Mutat Unu").split("/admin/status/", 1)[1].split("'")[0]

        def move(to_time: str, to_doc: str = "d3", appt: str = "") -> str:
            return c.post(f"/admin/move/{appt or aid}", mdate=day, mtime=to_time,
                          mdoctor=to_doc, back=f"/admin/all?date={day}").msg

        # --- перенос к другому врачу НА ТОТ ЖЕ ЧАС ---
        # ⛔ Тот самый случай, ради которого _patient_busy_at получил exclude_id:
        # визит находит САМ СЕБЯ на этом старте и без исключения отказал бы
        # «у пациента уже есть запись» — то есть из-за себя же.
        res.check("перенос к другому врачу на тот же час", move("10:00"), "ok_move")
        page = c.get(f"/admin/all?date={day}").body
        res.ok("визит переехал в колонку нового врача",
               "Activ Trei" in _row_of(page, "Mutat Unu"),
               "врач в списке не сменился")

        # ⚠️ Перенос — событие фиши, а не только сетки: закон 195 спрашивает
        # «кто именно двигал визит», и без строки в летописи ответить нечем.
        pid = c.get("/admin/search?q=022700111").body.split(
            "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]
        card = c.get(f"/admin/patient/{pid}").body
        res.ok("перенос записан в летопись пациента",
               "Vizită mutată" in card and "Activ Trei" in card,
               "фиша не помнит переноса — по журналу доступа не восстановить, кто двигал")

        # --- полчаса и час ---
        res.check("перенос на полчаса вперёд", move("10:30"), "ok_move")
        res.ok("новый час виден в списке",
               "10:30" in _row_of(c.get(f"/admin/all?date={day}").body, "Mutat Unu"),
               "час в списке прежний")
        res.check("четверть часа не принимается", move("10:15"), "bad_time")
        res.check("выключенному врачу не переносим", move("11:00", "d1"), "bad_off")

        # --- занятый интервал ---
        add(c, day, "12:00", doctor="d2", name="Ocupa Ora", phone="022700222")
        res.check("перенос в занятый интервал отбит", move("12:00", "d2"), "conflict")
        page = c.get(f"/admin/all?date={day}").body
        res.ok("отбитый визит остался на месте",
               "10:30" in _row_of(page, "Mutat Unu"),
               "визит уехал, хотя перенос отклонён")

        # --- у ПАЦИЕНТА уже есть визит на этот час ---
        add(c, day, "15:00", doctor="d2", name="Mutat Unu", phone="022700111")
        res.check("двойник у пациента отбит", move("15:00", "d3"), "dup")

        # --- закрытые записи не двигаются ---
        c.post(f"/admin/status/{aid}", to="done", back=f"/admin/all?date={day}")
        res.check("завершённый визит не переносится", move("16:00"), "mv_closed")
        res.check("несуществующая запись", move("16:00", appt="999999"), "mv_gone")

        # --- разметка перетаскивания: договор один на ОБЕ страницы ---
        for path in (f"/admin?date={day}", f"/admin/all?date={day}"):
            body = c.get(path).body
            live = re.search(r"<div class='[^']*'[^>]*data-appt='\d+'[^>]*"
                             r"data-nm=\"Ocupa Ora\"[^>]*>", body)
            res.ok(f"{path}: активный визит можно тащить",
                   bool(live) and "data-mv='1'" in live.group(0)
                   and "draggable='true'" in live.group(0)
                   and "data-busy='1'" in live.group(0),
                   f"блок без атрибутов переноса: {live.group(0)[:120] if live else 'не найден'}")
            done = re.search(r"<div class='[^']*'[^>]*data-appt='" + aid
                             + r"'[^>]*data-nm=\"Mutat Unu\"[^>]*>", body)
            res.ok(f"{path}: завершённый визит не тащится и не занимает час",
                   bool(done) and "data-mv" not in done.group(0)
                   and "data-busy" not in done.group(0),
                   "закрытый визит остался перетаскиваемым")
            res.ok(f"{path}: подсказка про перетаскивание на месте",
                   "trageți o programare" in body.lower(),
                   "страница не говорит, что визит можно перетащить")

    # закрытый час не принимает бросок — ни на канве, ни в таблице
    # (клиника 07-21, врачи 09-17, обед 13-14)
    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        day = _d(1)
        add(c, day, "10:00", doctor="d2", name="Pauza Drop", phone="022700333")
        res.check("перенос в обеденный час отбит",
                  c.post(f"/admin/move/{_row_of(c.get(f'/admin/all?date={day}').body, 'Pauza Drop').split('/admin/status/', 1)[1].split(chr(39))[0]}",
                         mdate=day, mtime="13:00", mdoctor="d2",
                         back=f"/admin/all?date={day}").msg, "outside")
        canvas = c.get(f"/admin?date={day}").body
        res.ok("закрытая ячейка канвы не мишень",
               "class='gcell off' data-h" not in canvas
               and "<div class='gcell off'></div>" in canvas,
               "закрытый час канвы принимает бросок")
        grid = c.get(f"/admin/all?date={day}").body
        res.ok("закрытая ячейка таблицы не мишень",
               "<td class='goff'></td>" in grid and "goff' data-dk" not in grid,
               "закрытый час таблицы принимает бросок")


def suite_status(res: Result) -> None:
    """Статусы визита и заметки-блокировки слота."""
    with Server() as s:
        c = Client(s.url).login()
        add(c, _d(1), "10:00", name="Status Test", phone="022555111")
        row = c.get(f"/admin/all?date={_d(1)}").body
        appt_id = row.split("/admin/status/", 1)[1].split("'")[0].split('"')[0]
        res.ok("id визита найден в журнале", appt_id.isdigit(), f"id={appt_id!r}")

        for status in ("arrived", "done", "cancelled"):
            r = c.post(f"/admin/status/{appt_id}", to=status, back="/admin/all")
            res.ok(f"статус → {status}", r.status in (303, 200), f"код {r.status}")

        # отменённый час освободился
        res.check("после отмены час снова свободен",
                  add(c, _d(1), "10:00", name="Dupa Anulare", phone="022555222"),
                  "ok")

        # ⛔ переоткрыть в занятый час нельзя: слот 10:00 уже держит «Dupa
        # Anulare», и возврат обязан ответить «intervalul e ocupat», а не
        # посадить двоих в одно кресло
        res.check("возврат в занятый час отбит",
                  c.post(f"/admin/status/{appt_id}", to="confirmed",
                         back="/admin/all").msg, "conflict")

        # --- кнопки исхода зависят от СОСТОЯНИЯ записи (08-12) ---
        # ⚠️ Ищем `class='b-…'` в одинарных кавычках — это список дня; у
        # модалки карточки те же кнопки идут как class="bstat b-…", и без
        # различия проверка была бы зелёной всегда.
        add(c, _d(2), "10:00", name="Buton Test", phone="022555444")
        day2 = f"/admin/all?date={_d(2)}"
        page = c.get(day2).body
        bid = page.split("/admin/status/", 1)[1].split("'")[0].split('"')[0]
        res.ok("подтверждённой записи предложены все пять исходов",
               all(f"class='{k}'" in page
                   for k in ("b-waiting", "b-arrived", "b-done", "b-noshow",
                             "b-cancel")),
               "в списке дня не хватает кнопок исхода")

        c.post(f"/admin/status/{bid}", to="arrived", back=day2)
        page = c.get(day2).body
        res.ok("тому, кто уже в кресле, «A sosit» и «Nu a venit» не предлагают",
               "class='b-arrived'" not in page and "class='b-noshow'" not in page
               and "class='b-done'" in page,
               "кнопки в кресле не сузились — предлагаем записать неправду")

        c.post(f"/admin/status/{bid}", to="done", back=day2)
        page = c.get(day2).body
        res.ok("у закрытой записи остаётся ровно возврат",
               "class='b-reopen'" in page and "class='b-done'" not in page,
               "закрытая запись без кнопки возврата — промах неисправим")
        # плашка обязана звать статус словом кнопки, а не «a venit»
        badge = re.search(r"class='stat s-done'>(.*?)</span>", page, re.S)
        res.ok("плашка статуса — «finalizată» со значком",
               bool(badge) and "finalizat" in badge.group(1)
               and "<svg" in badge.group(1),
               f"плашка: {badge.group(1)[:80] if badge else 'нет'!r}")
        res.ok("та же отметка стоит и в сетке «Programări»",
               "class='appt done" in page and "class='stt'" in page,
               "в сетке дня статус виден только фоном — на панели значок есть")

        res.check("возврат открывает запись заново",
                  c.post(f"/admin/status/{bid}", to="confirmed", back=day2).msg, "")
        page = c.get(day2).body
        res.ok("после возврата исходы снова доступны",
               "class='b-arrived'" in page and "class='b-reopen'" not in page,
               "возврат не вернул запись в работу")

        # --- «A venit» (waiting, 08-13): пациент пришёл и ждёт в приёмной ---
        r = c.post(f"/admin/status/{bid}", to="waiting", back=day2)
        res.ok("статус → waiting принят", r.status == 303, f"код {r.status}")
        page = c.get(day2).body
        res.ok("пришедшему не предлагают «Nu a venit», но дают ход дальше",
               "class='b-noshow'" not in page and "class='b-arrived'" in page
               and "class='b-done'" in page,
               "кнопки waiting предлагают неправду или прячут следующий шаг")
        badge = re.search(r"class='stat s-waiting'>(.*?)</span>", page, re.S)
        res.ok("плашка «a venit» стоит словом на карточке сетки",
               "class='appt waiting" in page and bool(badge)
               and "a venit" in badge.group(1),
               f"плашка waiting: {badge.group(1)[:60] if badge else 'нет'!r}")
        # слот пришедшего ЗАНЯТ: ACTIVE_STATUSES и предикаты uq-индексов
        # обязаны знать waiting, иначе двойная бронь проходит молча
        res.check("час пришедшего занят для новой записи",
                  add(c, _d(2), "10:00", name="Peste Waiting", phone="022555666"),
                  "conflict")
        # второй шаг конвейера необязателен: из приёмной можно сразу в финал
        c.post(f"/admin/status/{bid}", to="done", back=day2)
        res.ok("из «a venit» можно сразу в «finalizată»",
               "class='b-reopen'" in c.get(day2).body,
               "перескок waiting→done не сработал")
        c.post(f"/admin/status/{bid}", to="confirmed", back=day2)

        # заметка занимает слот врача
        r = c.post("/admin/note", ndate=_d(1), ntime="14:00", ndoctor="d3",
                   ntext="Pauză tehnică", back="/admin/all")
        res.ok("заметка сохранена", r.msg in ("ok_note", "part_note"),
               f"msg={r.msg!r}")
        res.check("час с заметкой занят для записи",
                  add(c, _d(1), "14:00", doctor="d3", name="Blocat",
                      phone="022555333"), "conflict")
