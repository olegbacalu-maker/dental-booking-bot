"""Врачи (этап 2 миграции): три старых POST, которые не проверял ни один
набор, JSON API раздела и рубильник React/старая страница.

Главное, что здесь стережётся: старая форма и React-экран правят ОДИН
clinic.json одними правилами (`_add_doctor`, `_save_doctor`, `_set_services`,
`_store_photo`) — отказ, который отбивает форма, обязан отбивать и API, с тем
же кодом и с тем же словом.
"""
import json
import sqlite3

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app.core.visits import all_status_actions  # noqa: E402

from datetime import datetime, time  # noqa: E402

from harness import TZ, Client, Result, Server, clinic_today  # noqa: E402

NO_KEY = {"ADMIN_KEY": ""}      # ветка PIN-файла — то, что получает клиника
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120
FLAGS = ["settings_clinic", "doctors_list", "doctor_card"]


def _j(r) -> dict:
    return json.loads(r.body)


def _cfg(s: Server) -> dict:
    return json.loads(s.clinic.read_text(encoding="utf-8"))


def _doc(s: Server, dk: str) -> dict:
    return next(d for d in _cfg(s)["doctors"] if d["id"] == dk)


def _svc(s: Server, sid: str) -> dict:
    return next(x for x in _cfg(s)["services"] if x["id"] == sid)


def _new_patient(c: Client, name: str, phone: str) -> int:
    r = c.post("/admin/patients/new", name=name, phone=phone)
    return int(r.location.split("/admin/patient/")[1].split("?")[0])


def _insert_appt(s: Server, pid: int, doctor: str, dk, starts: str,
                 status: str = "confirmed") -> None:
    """Строка записи мимо сервера — так выглядят и легаси-сироты (doctor_id
    NULL), и будущая бронь, которую нужно получить без формы. Сервер работает
    в WAL и увидит строку на следующем запросе."""
    con = sqlite3.connect(str(s.dir / "dental.db"))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at, status, "
            "source, created_at, doctor_id) VALUES(?, 'Consultație', ?, ?, ?, 'admin', "
            "'2026-01-10T08:05:00+00:00', ?)", (pid, doctor, starts, status, dk))
        con.commit()
    finally:
        con.close()


def _server_with_flags() -> Server:
    s = Server()
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": list(FLAGS)}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_legacy(res: Result) -> None:
    """Старые POST без единой проверки: добавление врача, сброс цветов,
    перепривязка сирот. Плюс их охрана правом (регистратура может, врач нет)."""
    with Server() as s:
        c = Client(s.url).login()
        r = c.post("/admin/medici/add", name="Dr. Cinci", spec="Ortodonție")
        res.check("новый врач — new_med", r.msg, "new_med")
        res.ok("ведёт в его фишу", r.location.startswith("/admin/doctor-card/d5"),
               r.location)
        d5 = _doc(s, "d5")
        res.check("id по счётчику — d5 (d1..d4 заняты)", d5["id"], "d5")
        res.check("специализация записана", d5.get("spec"), "Ortodonție")
        res.check("новый врач активен", d5.get("status"), "activ")
        res.check("счётчик seq.doctor = 5", _cfg(s).get("seq", {}).get("doctor"), 5)
        res.check("пустое имя — bad_med", c.post("/admin/medici/add", name="  ").msg,
                  "bad_med")
        res.check("тёзка (без учёта регистра) — dup_med",
                  c.post("/admin/medici/add", name="dr. activ doi").msg, "dup_med")
        res.check("врачей по-прежнему пять", len(_cfg(s)["doctors"]), 5)

        # цвета: всем один и тот же → страница предлагает сброс → сброс чистит
        for dk in ("d1", "d2", "d3", "d4", "d5"):
            c.post(f"/admin/doctor-card/{dk}/save", name=_doc(s, dk)["name"],
                   color="#112233", status=_doc(s, dk).get("status", "activ"))
        res.ok("одинаковый цвет у всех — страница предлагает «Culori automate»",
               "/admin/medici/colors" in c.get("/admin/medici").body,
               "подсказки сброса нет")
        r = c.post("/admin/medici/colors")
        res.check("сброс цветов — ok_med", r.msg, "ok_med")
        res.ok("цвета сняты у всех", all("color" not in d for d in _cfg(s)["doctors"]),
               f"{[d.get('color') for d in _cfg(s)['doctors']]}")
        res.ok("подсказка сброса исчезла",
               "/admin/medici/colors" not in c.get("/admin/medici").body,
               "подсказка осталась после сброса")

        # перепривязка: сирота (старое имя, doctor_id NULL) → к врачу d2
        pid = _new_patient(c, "Orfan Test", "060000111")
        _insert_appt(s, pid, "Dr. Vechi", None, "2026-12-01T08:00:00+00:00")
        r = c.post("/admin/relink", old_name="Dr. Vechi", dk="d2", back="/admin/all?date=2026-12-01")
        res.check("перепривязка — ok_set", r.msg, "ok_set")
        res.ok("возврат туда, откуда звали", r.location.startswith("/admin/all?date=2026-12-01"),
               r.location)
        con = sqlite3.connect(str(s.dir / "dental.db"))
        try:
            got = con.execute("SELECT doctor_id FROM appointments WHERE doctor = 'Dr. Vechi'"
                              ).fetchone()
        finally:
            con.close()
        res.check("сирота получил doctor_id", got[0] if got else None, "d2")
        r = c.post("/admin/relink", old_name="Dr. Vechi", dk="d9", back="/admin/all")
        res.ok("неизвестный врач — назад на панель без записи",
               r.status == 303 and r.location == "/admin", f"{r!r}")
        r = c.post("/admin/relink", old_name="Nimeni", dk="d2", back="http://evil/x")
        res.ok("чужой back не пускает наружу", r.location.startswith("/admin?"), r.location)

    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        boss.post("/admin/users/save", uid="d2", name="Dr. Liviu", role="medic",
                  doctor_id="d2", pin="2222")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        res.check("регистратура добавляет врача",
                  ana.post("/admin/medici/add", name="Dr. Sase").msg, "new_med")
        res.check("регистратура сбрасывает цвета",
                  ana.post("/admin/medici/colors").msg, "ok_med")
        res.check("регистратура перепривязывает",
                  ana.post("/admin/relink", old_name="X", dk="d2").msg, "ok_set")
        med = Client(s.url)
        med.post("/admin/login", password="2222", next="/admin")
        for path, kw in (("/admin/medici/add", {"name": "Dr. Hack"}),
                         ("/admin/medici/colors", {}),
                         ("/admin/relink", {"old_name": "X", "dk": "d2"})):
            r = med.post(path, **kw)
            res.ok(f"врачу закрыт POST {path}", r.status == 303 and r.msg == "no_access",
                   f"{r!r}")


def suite_api(res: Result) -> None:
    """JSON API врачей: те же правила и коды, что у форм, плюс форма ответа."""
    with Server() as s:
        c = Client(s.url).login()
        res.check("без входа — 401", Client(s.url).get("/api/doctors").status, 401)

        d = _j(c.get("/api/doctors"))["data"]
        names = [x["id"] for x in d["doctors"]]
        res.check("список: четыре врача в порядке профиля", names, ["d1", "d2", "d3", "d4"])
        d1 = d["doctors"][0]
        res.ok("архивный помечен", d1["archived"] and d1["status"] == "arhivat", f"{d1}")
        d2 = d["doctors"][1]
        res.check("имя", d2["name"], "Dr. Activ Doi")
        res.check("специализация", d2["spec"], "Chirurgie")
        res.ok("цифры за 30 дней", set(d2["stats"]) == {"n", "pct", "noshow"}, f"{d2['stats']}")
        res.ok("цвет, инициалы, часы", d2["color"].startswith("#") and d2["initials"]
               and d2["hours"], f"{d2}")
        res.check("фото нет — пустая строка", d2["photo"], "")
        res.check("подписи состояний — с сервера", set(d["states"]),
                  {"activ", "concediu", "arhivat"})
        res.check("цвета не одинаковые", d["same_color"], False)

        r = c.post_json("/api/doctors", {"name": "Dr. Cinci", "spec": "Orto"})
        res.check("добавление — 200", r.status, 200)
        res.check("код new_med", _j(r)["code"], "new_med")
        res.check("id нового — d5", _j(r)["data"]["id"], "d5")
        res.check("файл: пять врачей", len(_cfg(s)["doctors"]), 5)
        r = c.post_json("/api/doctors", {"name": " "})
        res.ok("пустое имя — 422 bad_med, поле name",
               r.status == 422 and _j(r)["code"] == "bad_med" and _j(r).get("field") == "name",
               r.body)
        r = c.post_json("/api/doctors", {"name": "DR. CINCI"})
        res.ok("тёзка — 409 dup_med с текстом", r.status == 409 and _j(r)["code"] == "dup_med"
               and "unic" in _j(r)["text"], r.body)

        r = c.get("/api/doctors/d2")
        res.check("фиша — 200", r.status, 200)
        card = _j(r)["data"]
        res.check("фиша: имя", card["name"], "Dr. Activ Doi")
        res.ok("фиша: автоцвет и цвет палитры", card["auto_color"] and card["color"].startswith("#"),
               f"{card['color']} {card['auto_color']}")
        res.ok("фиша: часы «как у клиники»", card["work_from"] is None and card["work_to"] is None,
               f"{card['work_from']}")
        res.check("фиша: диапазон часов из констант", card["hours"], {"min": 7, "max": 21})
        res.check("фиша: неделя из 7 ячеек", len(card["week"]), 7)
        res.check("фиша: первая ячейка — Azi", card["week"][0]["label"], "Azi")
        res.ok("фиша: ячейка знает дату и открыт ли день",
               set(card["week"][0]) == {"date", "label", "dm", "count", "open"}, f"{card['week'][0]}")
        res.check("фиша: сегодня пусто", card["today"], [])
        # ⭐ C14+: кнопки исхода — ТА ЖЕ матрица, что у списка дня. Своя копия
        # разошлась бы с журналом молча: закрытая запись теряла бы кнопку
        # возврата в одном месте и сохраняла в другом.
        res.check("фиша: матрица кнопок — из core.visits",
                  card["actions"], all_status_actions())
        res.check("фиша: у заметки СВОЯ матрица",
                  card["note_actions"], all_status_actions(is_note=True))
        res.ok("у завершённой записи ровно одна кнопка — возврат, и он спрашивает",
               [b["to"] for b in card["actions"]["done"]] == ["confirmed"]
               and card["actions"]["done"][0]["confirm"], f"{card['actions']['done']}")

        # --- C14+: исход из фиши врача идёт ЖУРНАЛЬНЫМ маршрутом ---
        # ⛔ Менять состояние визита умеет ровно одно место; второй адрес под
        # `/doctors/` был бы вторым владельцем одного правила.
        day = clinic_today().isoformat()
        # ⚠️ Час брони — ОДНОЙ константой на бронь и на ожидание «будущих» ниже:
        # две копии одного часа разошлись бы молча (поймано имитацией ночи).
        book_at = time(9, 0)
        c.post("/admin/add", adate=day, atime=book_at.strftime("%H:%M"), adoctor="d2",
               aservice="consult", aname="Medic Card Unu", aphone="069000031",
               back="/admin/all")
        row = _j(c.get("/api/doctors/d2"))["data"]["today"][0]
        res.check("запись видна в сегодняшнем списке врача", row["status"], "confirmed")
        aid = row["id"]
        # ⚠️ Контраст обязателен: без него проверка зелена и у маршрута,
        # который данных не отдаёт НИКОМУ, — а день на них живёт.
        med_ok = c.post_json(
            f"/api/schedule/appointments/{aid}/status?screen=med", {"to": "waiting"})
        day_ok = c.post_json(
            f"/api/schedule/appointments/{aid}/status?date={day}", {"to": "arrived"})
        res.check("фише врача — код без состояния, дню — свежий день",
                  (med_ok.status, "data" in _j(med_ok),
                   day_ok.status, "data" in _j(day_ok)),
                  (200, False, 200, True))
        res.check("исход действительно применился",
                  _j(c.get("/api/doctors/d2"))["data"]["today"][0]["status"], "arrived")
        svc = {x["id"]: x for x in card["services"]}
        res.ok("фиша: consult у всех, hygiene не у d2",
               svc["consult"]["checked"] and svc["consult"]["note"] == "toți medicii"
               and not svc["hygiene"]["checked"] and svc["hygiene"]["note"] == "1 medic", f"{svc}")
        res.ok("фиша: состояния с подписью и подсказкой",
               card["states"]["concediu"]["label"] == "În concediu"
               and card["states"]["concediu"]["hint"], f"{card['states']}")
        res.check("фиша: будущих записей нет", card["future"], 0)
        # d2 — единственный АКТИВНЫЙ врач у «pain» (d1 в архиве) и «long»:
        # фиша предупреждает заранее, тем же текстом, что старая страница
        res.ok("фиша: предупреждение «если станет неактивен» — текст сервера",
               card["warning"].startswith("Atenție")
               and "Durere acută" in card["warning"] and "Tratament lung" in card["warning"],
               card["warning"])
        res.check("неизвестный врач — 404", c.get("/api/doctors/d9").status, 404)

        # ---- сохранение: те же правила, что у формы ----
        body = {"name": "Dr. Doi Nou", "spec": "Chirurgie", "room": "3", "phone": "101",
                "email": "doi@x.md", "color": "#123456", "auto_color": False,
                "work_from": 9, "work_to": 15, "status": "activ"}
        r = c.post_json("/api/doctors/d2", body)
        res.check("сохранение — 200", r.status, 200)
        res.check("код ok_med", _j(r)["code"], "ok_med")
        card = _j(r)["data"]
        res.ok("ответ несёт свежую фишу", card["name"] == "Dr. Doi Nou" and card["room"] == "3"
               and card["work_from"] == 9 and card["work_to"] == 15
               and card["color"] == "#123456" and not card["auto_color"], f"{card}")
        f = _doc(s, "d2")
        res.ok("файл: поля записаны", f["name"] == "Dr. Doi Nou" and f["email"] == "doi@x.md"
               and f["work_from"] == 9 and f["color"] == "#123456", f"{f}")
        res.ok("старая фиша видит новое имя (один файл)",
               "Dr. Doi Nou" in c.get("/admin/doctor-card/d2").body, "старая фиша отстала")
        before = s.clinic.read_bytes()
        c.post_json("/api/doctors/d2", body)
        res.ok("повторный POST того же тела тождествен", s.clinic.read_bytes() == before,
               "файл изменился без правки")
        r = c.post_json("/api/doctors/d2", {**body, "auto_color": True})
        res.ok("автоцвет снимает свой цвет", _j(r)["data"]["auto_color"]
               and "color" not in _doc(s, "d2"), f"{_doc(s, 'd2').get('color')}")
        r = c.post_json("/api/doctors/d2", {**body, "name": "dr. activ trei"})
        res.ok("тёзка — 409 dup_med", r.status == 409 and _j(r)["code"] == "dup_med", r.body)
        r = c.post_json("/api/doctors/d2", {**body, "work_from": 12, "work_to": 10})
        res.ok("часы задом наперёд — 422 bad_med", r.status == 422 and _j(r)["code"] == "bad_med",
               r.body)
        r = c.post_json("/api/doctors/d2", {**body, "color": "red"})
        res.ok("цвет не hex — 422", r.status == 422, r.body)
        r = c.post_json("/api/doctors/d2", {**body, "name": ""})
        res.ok("пустое имя — 422, поле name", r.status == 422 and _j(r).get("field") == "name",
               r.body)
        res.check("отказы файл не тронули", _doc(s, "d2")["name"], "Dr. Doi Nou")
        r = c.post_json("/api/doctors/d2", {**body, "status": "concediu"})
        res.check("в отпуск — ok", _j(r)["code"], "ok_med")
        res.check("статус в файле", _doc(s, "d2")["status"], "concediu")
        r = c.post_json("/api/doctors/d3", {"name": "Dr. Activ Trei", "status": "concediu"})
        res.check("второй в отпуск — ok", _j(r)["code"], "ok_med")
        r = c.post_json("/api/doctors/d5", {"name": "Dr. Cinci", "status": "concediu"})
        res.check("третий в отпуск — ok", _j(r)["code"], "ok_med")
        r = c.post_json("/api/doctors/d4", {"name": "Dr. Activ Patru", "status": "concediu"})
        res.ok("последний активный в отпуск нельзя — 409 last_med",
               r.status == 409 and _j(r)["code"] == "last_med", r.body)
        card = _j(c.get("/api/doctors/d2"))["data"]
        res.ok("фиша отпускника предупреждает об услугах без врача",
               "Tratament lung" in card["warning"] and "nu pot fi programate" in card["warning"],
               card["warning"])
        c.post_json("/api/doctors/d2", {**body, "status": "activ"})
        pid = _new_patient(c, "Viitor Test", "060000222")
        _insert_appt(s, pid, "Dr. Doi Nou", "d2", "2099-01-10T08:00:00+00:00")
        r = c.post_json("/api/doctors/d2", {**body, "status": "arhivat"})
        res.ok("в архив с будущей записью нельзя — 409 arch_busy",
               r.status == 409 and _j(r)["code"] == "arch_busy", r.body)
        # ⚠️ Бронь «сегодня в book_at» (выше, C14+) — тоже ЖИВАЯ, и счётчик
        # считает её честно: пока этот час по Кишинёву не наступил, она впереди.
        # Зашитая единица держала проверку зелёной только с 09:00 до полуночи —
        # ночной прогон 22.09 покраснел без единой правки кода. Ожидание
        # считается от часов клиники (`TZ`, не машины), причём ДВАЖДЫ — до
        # запроса и после: сервер берёт своё «сейчас» где-то между, и в секунду
        # ровно 09:00:00 верны оба ответа. Что проверяется, не изменилось:
        # запись 2099 года видна счётчику и запирает архивацию.
        booked = datetime.combine(clinic_today(), book_at, tzinfo=TZ)
        before = datetime.now(TZ)
        got = _j(c.get("/api/doctors/d2"))["data"]["future"]
        after = datetime.now(TZ)
        expected = {1 + (1 if booked >= t else 0) for t in (before, after)}
        res.ok("фиша считает будущие", got in expected,
               f"получено {got}, ожидалось {sorted(expected)} "
               f"(сегодняшняя бронь {'ещё впереди' if booked >= after else 'уже прошла'})")

        # ---- услуги ----
        r = c.post_json("/api/doctors/d3/services", {"services": ["hygiene"]})
        res.check("услуги d3 — только hygiene: ok_svc_med", _j(r)["code"], "ok_svc_med")
        res.ok("consult материализован без d3",
               sorted(_svc(s, "consult")["docs"]) == ["d1", "d2", "d4", "d5"],
               f"{_svc(s, 'consult').get('docs')}")
        res.ok("ответ несёт свежие галочки",
               not next(x for x in _j(r)["data"]["services"] if x["id"] == "consult")["checked"],
               r.body[:200])
        r = c.post_json("/api/doctors/d3/services", {"services": ["consult"]})
        res.ok("снять себя с услуги, где ты последний, — 409 svc_empty",
               r.status == 409 and _j(r)["code"] == "svc_empty", r.body)
        r = c.post_json("/api/doctors/d3/services", {"services": "hygiene"})
        res.check("не список — 422", r.status, 422)

        # ---- фото ----
        r = c.post_file("/api/doctors/d2/photo", "file", "a.png", PNG)
        res.check("фото PNG — 200", r.status, 200)
        res.ok("код ok_photo и адрес фото", _j(r)["code"] == "ok_photo"
               and _j(r)["data"]["photo"].startswith("/admin/doctor-photo/d2?v="), r.body)
        res.ok("файл фото в профиле", _doc(s, "d2").get("photo", "").startswith("d2_"),
               f"{_doc(s, 'd2').get('photo')}")
        r = c.get("/admin/doctor-photo/d2")
        res.ok("фото отдаётся", r.status == 200 and r.raw[:8] == PNG[:8], f"код {r.status}")
        res.ok("список показывает фото", _j(c.get("/api/doctors"))["data"]["doctors"][1]["photo"] != "",
               "фото нет в списке")
        r = c.post_file("/api/doctors/d2/photo", "file", "x.png", b"not an image at all")
        res.ok("мусор — 422 bad_photo", r.status == 422 and _j(r)["code"] == "bad_photo", r.body)
        r = c.post_json("/api/doctors/d2/photo/delete", {})
        res.ok("удаление — ok_med, фото пусто", _j(r)["code"] == "ok_med"
               and _j(r)["data"]["photo"] == "", r.body)
        res.check("фото снято из профиля", _doc(s, "d2").get("photo", ""), "")

        # ---- цвета ----
        for dk in ("d1", "d2", "d3", "d4", "d5"):
            c.post(f"/admin/doctor-card/{dk}/save", name=_doc(s, dk)["name"],
                   color="#112233", status=_doc(s, dk).get("status", "activ"))
        res.check("одинаковые цвета видны списку", _j(c.get("/api/doctors"))["data"]["same_color"], True)
        r = c.post_json("/api/doctors/colors", {})
        res.check("сброс — ok_med", _j(r)["code"], "ok_med")
        res.check("после сброса — не одинаковые", _j(c.get("/api/doctors"))["data"]["same_color"], False)

    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
        boss.post("/admin/users/save", uid="d2", name="Dr. Liviu", role="medic",
                  doctor_id="d2", pin="2222")
        ana = Client(s.url)
        ana.post("/admin/login", password="3333", next="/admin")
        res.check("регистратуре API врачей открыт", ana.get("/api/doctors").status, 200)
        med = Client(s.url)
        med.post("/admin/login", password="2222", next="/admin")
        r = med.get("/api/doctors")
        res.ok("врачу закрыт — 403 no_access", r.status == 403 and _j(r)["code"] == "no_access",
               r.body)
        res.check("врачу закрыт и POST", med.post_json("/api/doctors/d2", {"name": "X"}).status, 403)


def suite_switch(res: Result) -> None:
    """Флаги doctors_list и doctor_card: React-узел в той же рамке, параметры
    экрана атрибутом, ?ui=legacy возвращает старую страницу, старые POST
    работают при включённом флаге."""
    with Server() as s:
        c = Client(s.url).login()
        page = c.get("/admin/medici").body
        res.ok("без флага — старый список", "class='medgrid'" in page and 'id="root"' not in page,
               "не старый список")
        res.ok("без флага — старая фиша", "name='name'" in c.get("/admin/doctor-card/d2").body,
               "не старая фиша")

    s = _server_with_flags()
    with s:
        c = Client(s.url).login()
        page = c.get("/admin/medici").body
        res.ok("список: узел React", '<div id="root" data-screen="doctors_list"' in page,
               "узла нет")
        # ⭐ B1: модель оболочки приезжает ИНЛАЙНОМ тем же узлом — оболочка,
        # ждущая fetch, рисовала бы пустой сайдбар на первом кадре.
        res.ok("список: модель оболочки на узле", 'data-shell="' in page, "модели нет")
        # ⛔ Негативный сторож B1: сервер каркас больше НЕ печатает. Иначе на
        # экране было бы по два сайдбара, и увидеть это можно только глазами.
        res.ok("список: серверного каркаса нет", "<aside" not in page
               and 'class="top"' not in page, "две оболочки разом")
        res.ok("список: рамка (подпись раздела и бандл)",
               "medicii clinicii" in page and "/static/js/bundle.js?v=" in page, "рамка потеряна")
        res.ok("список: старой разметки нет", "class='medgrid'" not in page, "две разметки")
        res.ok("список: не внутри #live", 'id="live"' not in page, "живой кусок на экране React")
        page = c.get("/admin/doctor-card/d2").body
        res.ok("фиша: узел React с параметром dk",
               'data-screen="doctor_card"' in page and 'data-params="{&quot;dk&quot;: &quot;d2&quot;}"' in page,
               page[page.find("id=\"root\""):page.find("id=\"root\"") + 120])
        res.ok("фиша: подпись с именем врача", "fișa medicului · Dr. Activ Doi" in page, "подписи нет")
        res.ok("фиша: неизвестный врач по-прежнему ведёт в список",
               c.get("/admin/doctor-card/d9").location == "/admin/medici", "иначе")
        res.ok("?ui=legacy — старый список",
               "class='medgrid'" in c.get("/admin/medici?ui=legacy").body, "не вернулся")
        res.ok("?ui=legacy — старая фиша",
               "name='name'" in c.get("/admin/doctor-card/d2?ui=legacy").body, "не вернулась")
        res.ok("?msg= на React-странице — плашка сервера",
               "dp_toast" in c.get("/admin/medici?msg=ok_med").body, "плашки нет")
        r = c.post("/admin/medici/add", name="Dr. Flag")
        res.ok("старый POST при флаге работает и ведёт в фишу",
               r.msg == "new_med" and r.location.startswith("/admin/doctor-card/d5"), f"{r!r}")
        res.ok("флаги пережили правку профиля", _cfg(s).get("ui") == {"react": FLAGS},
               f"{_cfg(s).get('ui')}")
        r = c.post_json("/api/doctors/d5", {"name": "Dr. Flag", "status": "activ"})
        res.ok("флаги пережили правку через API", r.status == 200 and _cfg(s).get("ui") == {"react": FLAGS},
               f"{_cfg(s).get('ui')}")
        res.ok("экран клиники всё ещё за флагом",
               'data-screen="settings_clinic"' in c.get("/admin/settings/clinic").body, "иначе")

    s = _server_with_flags()
    s.extra_env = dict(NO_KEY)
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post("/admin/users/save", uid="d2", name="Dr. Liviu", role="medic",
                  doctor_id="d2", pin="2222")
        med = Client(s.url)
        med.post("/admin/login", password="2222", next="/admin")
        for path in ("/admin/medici", "/admin/doctor-card/d2"):
            r = med.get(path)
            res.ok(f"врачу React-страница {path} закрыта, как и старая",
                   r.status == 303 and r.msg == "no_access", f"{r!r}")
