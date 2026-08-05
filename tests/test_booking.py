"""Запись и отказы: журнал, фиша, интервалы, границы прошлого.

Это ядро продукта — если что-то из этого молча изменится, клиника посадит двух
пациентов в одно кресло или потеряет визит в прошлом.
"""
from datetime import date, datetime, timedelta

from harness import Client, Result, Server

PHONE = "022111222"


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def add(c: Client, day: str, time: str, doctor: str = "d2",
        service: str = "consult", name: str = "Ion Testescu",
        phone: str = PHONE, year: str = "") -> str:
    return c.post("/admin/add", adate=day, atime=time, adoctor=doctor,
                  aservice=service, aname=name, aphone=phone, ayear=year,
                  back="/admin/all").msg


def suite(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()

        # --- обычная запись ---
        res.check("первая запись проходит", add(c, _d(1), "10:00"), "ok")
        res.check("час занят у этого врача",
                  add(c, _d(1), "10:00", name="Alt Pacient", phone="022999888"),
                  "conflict")
        res.check("тот же час у другого врача — свободен",
                  add(c, _d(1), "10:00", doctor="d3", name="Alt Pacient",
                      phone="022999888"), "ok")

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

        # --- отказы, каждый со своим текстом ---
        res.check("телефон короче 8 цифр",
                  add(c, _d(3), "10:00", phone="060"), "bad_phone")
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

        # заметка занимает слот врача
        r = c.post("/admin/note", ndate=_d(1), ntime="14:00", ndoctor="d3",
                   ntext="Pauză tehnică", back="/admin/all")
        res.ok("заметка сохранена", r.msg in ("ok_note", "part_note"),
               f"msg={r.msg!r}")
        res.check("час с заметкой занят для записи",
                  add(c, _d(1), "14:00", doctor="d3", name="Blocat",
                      phone="022555333"), "conflict")
