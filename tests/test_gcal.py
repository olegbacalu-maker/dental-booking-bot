"""Вкладка «Google Calendar»: события календаря клиники и их перенос в журнал.

Файлы собираются здесь с датами от `clinic_today()`: образец с жёсткими
датами через неделю оказался бы целиком в прошлом, и набор позеленел бы на
пустом списке — поэтому каждая загрузка проверяет, что годных строк не ноль.
Старт не на получасе и длительность не из списка — `suite_after_grid`.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import tempfile
from datetime import timedelta

from harness import (FIXTURES, Client, Clock, Result, Server, _rmtree_settled, add_appt,
                     clinic_now, clinic_today, day_model, new_patient, shell_model)

NO_KEY = {"ADMIN_KEY": ""}
KEY_ENV = {"DENTART_LICENSE_KEYS": str(FIXTURES / "license" / "test-key.json")}
D2 = "Dr. Activ Doi"


# ---------- файл календаря ----------

def _day(n: int) -> str:
    return (clinic_today() + timedelta(days=n)).isoformat()


def _stamp(n: int, hhmm: str) -> str:
    return (clinic_today() + timedelta(days=n)).strftime("%Y%m%d") + "T" + hhmm.replace(":", "") + "00"


def ev(uid: str, n: int, hhmm: str, minutes: int, title: str, *, desc: str = "",
       status: str = "", allday: bool = False, rrule: str = "") -> str:
    """Одно событие: день — через `n` дней от сегодня клиники, часы — стенные
    часы Кишинёва."""
    if allday:
        d0 = (clinic_today() + timedelta(days=n)).strftime("%Y%m%d")
        d1 = (clinic_today() + timedelta(days=n + 1)).strftime("%Y%m%d")
        when = f"DTSTART;VALUE=DATE:{d0}\r\nDTEND;VALUE=DATE:{d1}"
    else:
        h, m = (int(x) for x in hhmm.split(":"))
        end = h * 60 + m + minutes
        when = (f"DTSTART;TZID=Europe/Chisinau:{_stamp(n, hhmm)}\r\n"
                f"DTEND;TZID=Europe/Chisinau:{_stamp(n, f'{end // 60:02d}:{end % 60:02d}')}")
    lines = ["BEGIN:VEVENT", when, f"SUMMARY:{title}", f"UID:{uid}@google.com",
             "DTSTAMP:20260101T070000Z"]
    if desc:
        lines.append(f"DESCRIPTION:{desc}")
    if status:
        lines.append(f"STATUS:{status}")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    return "\r\n".join(lines + ["END:VEVENT"])


def cal(events: list, name: str = "Clinica Test") -> bytes:
    head = ["BEGIN:VCALENDAR", "PRODID:-//Google Inc//Google Calendar 70.9054//EN", "VERSION:2.0",
            f"X-WR-CALNAME:{name}", "X-WR-TIMEZONE:Europe/Chisinau"]
    return ("\r\n".join(head + events + ["END:VCALENDAR"]) + "\r\n").encode("utf-8")


def base_events() -> list:
    return [
        ev("a1", 3, "09:00", 30, "Popescu Ion 069123456 consult"),
        ev("a2", 3, "10:30", 60, "Balan Stefan - Dr. Doi", desc="vine cu radiografie"),
        ev("a3", 4, "", 0, "Concediu", allday=True),
        ev("a4", 4, "11:00", 30, "Anulat Vasile", status="CANCELLED"),
        ev("a5", -2, "09:00", 30, "Ieri Trecut 069000111"),
        ev("a6", 5, "09:00", 30, "Zi de nastere", rrule="FREQ=YEARLY"),
        ev("a7", 3, "14:07", 23, "Rotund Maria +373 79 555 123"),
        ev("a8", 400, "09:00", 30, "Peste un an"),
        ev("a10", -1, "09:00", 30, "Ieri Anulat", status="CANCELLED"),
    ]


# ---------- помощники ----------

def _j(r) -> dict:
    return json.loads(r.body)


def upload(c: Client, raw: bytes, name: str = "calendar.ics"):
    return c.post_file("/api/gcal/file", "file", name, raw, mime="text/calendar")


def loaded(res: Result, c: Client, raw: bytes, tag: str) -> dict:
    """Загрузка, которая обязана пройти; отчёт загрузки."""
    r = upload(c, raw)
    res.check(f"{tag}: файл принят", (r.status, r.msg), (200, "gc_loaded"))
    return _j(r)["data"]["load"] if r.status == 200 else {}


def listing(c: Client, f: str = "", q: str = "") -> dict:
    r = c.get(f"/api/gcal?f={f}&q={q}")
    if r.status != 200:
        raise AssertionError(f"вкладка не отдана: {r.status} {r.body[:200]}")
    return _j(r)["data"]


def rows(data: dict) -> list:
    return [x for d in data["days"] for x in d["rows"]] + data["undated"]


def row(c: Client, title: str, f: str = "") -> dict:
    for x in rows(listing(c, f)):
        if x["title"].startswith(title):
            return x
    raise AssertionError(f"строки {title!r} в фильтре {f or 'nou'!r} нет")


def sql(s: Server, query: str, *args) -> list:
    con = sqlite3.connect(str(s.dir / "dental.db"))
    try:
        return list(con.execute(query, args))
    finally:
        con.close()


def nav_keys(c: Client) -> list:
    return [x["key"] for x in shell_model(c.get("/admin").body)["nav"]["sync"]]


def move_body(n: int, hhmm: str, name: str, phone: str = "", doctor: str = "d2", **more) -> dict:
    return {"date": _day(n), "time": hhmm, "doctor": doctor, "service": "consult",
            "name": name, "phone": phone, "nophone": not phone, **more}


# ---------- наборы ----------

def suite_load(res: Result) -> None:
    """Загрузка: что легло в список, что отложено само, что не сохранено;
    подсказки строки; повторная загрузка; меню и плитка."""
    with Server() as s:
        c = Client(s.url).login()
        res.ok("до загрузки пункта меню нет", "gcal" not in nav_keys(c), f"{nav_keys(c)}")
        tiles = {t["href"]: t for t in _j(c.get("/api/settings/hub"))["data"]["tiles"]}
        res.check("плитка «Google Calendar» в группе «Programări»",
                  tiles.get("/admin/google", {}).get("group"), "programari")
        res.check("пустой файл — отказ словом", (upload(c, b"").status, upload(c, b"").msg),
                  (422, "gc_no_file"))
        r = upload(c, b"<html><body>Sign in - Google Accounts</body></html>")
        res.check("страница входа вместо календаря — отказ файла", (r.status, r.msg),
                  (422, "gc_not_calendar"))
        res.ok("отказ несёт слова", bool(_j(r)["text"]), r.body[:200])
        res.check("отказанный файл ничего не оставил", sql(s, "SELECT COUNT(*) FROM gcal_events"),
                  [(0,)])

        got = loaded(res, c, cal(base_events()), "первая загрузка")
        res.ok("годных строк не ноль", got.get("new", 0) > 0, f"{got}")
        res.check("новых — три, прошлое и дальше года не сохранены",
                  (got["new"], got["past"], got["beyond"], got["skipped"], got["unparsed"]),
                  (3, 2, 1, 2, 1))
        res.check("прошлого и дальнего в таблице нет",
                  sql(s, "SELECT COUNT(*) FROM gcal_events WHERE title LIKE 'Ieri%' "
                         "OR title LIKE 'Peste%'"), [(0,)])
        d = listing(c)
        res.check("счётчики фильтров", d["counts"],
                  {"nou": 3, "mutat": 0, "omis": 2, "nerecunoscut": 1, "schimbat": 0})
        res.check("фильтр «Schimbate» не показывается пустым",
                  [x["key"] for x in d["filters"]], ["nou", "mutat", "omis", "nerecunoscut"])
        res.check("по дням, по времени", [(x["date"], x["time"]) for x in rows(d)],
                  [(_day(3), "09:00"), (_day(3), "10:30"), (_day(3), "14:07")])
        res.check("полоса источника: имя календаря", d["source"]["name"], "Clinica Test")
        res.ok("полоса источника: когда и кем", bool(d["source"]["loaded_at"]
                                                   and d["source"]["loaded_by"]), f"{d['source']}")

        a1, a2, a7 = rows(d)
        res.check("телефон из названия", (a1["hint"]["phone"], a1["preset"]["phone"]),
                  ("69123456", "069123456"))
        res.ok("имя-заготовка из названия", a1["hint"]["name"].startswith("Popescu Ion"),
               a1["hint"]["name"])
        res.check("однозначный врач — подсказка и заполнение",
                  ((a2["hint"]["doctor"] or {}).get("key"), a2["preset"]["doctor"]), ("d2", "d2"))
        res.check("без телефона окно откроется с «fără telefon»",
                  (a2["preset"]["phone"], a2["preset"]["nophone"]), ("", True))
        res.check("врача в названии нет — не угадывается", a1["preset"]["doctor"], "")
        res.check("некратное пяти округлено с пометкой",
                  (a7["round"], a7["preset"]["time"], a7["preset"]["duration"]),
                  ({"from": "14:07–14:30", "to": "14:05–14:30"}, "14:05", "25"))
        res.check("кратное пяти не округляется", a1["round"], None)
        res.check("описание едет в строке", a2["body"], "vine cu radiografie")

        om = {x["title"]: x for x in rows(listing(c, "omis"))}
        res.check("«весь день» и отменённое — сразу в «Omise», со словом причины",
                  {k: v["why"]["code"] for k, v in om.items()},
                  {"Concediu": "all_day", "Anulat Vasile": "cancelled"})
        res.ok("причина — словами сервера", all(v["why"]["text"] for v in om.values()), f"{om}")
        un = rows(listing(c, "nerecunoscut"))
        res.check("не разобранное — со словом причины",
                  [(x["title"], x["why"]["code"], x["state"]) for x in un],
                  [("Zi de nastere", "rrule_freq", "nerecunoscut")])

        res.check("поиск по названию без регистра", [x["title"] for x in rows(listing(c, q="POPESCU"))],
                  ["Popescu Ion 069123456 consult"])
        res.check("счётчики считают найденное", listing(c, q="popescu")["counts"]["nou"], 1)

        # фиша по телефону: номер в файле записан иначе, чем в фише
        pid = new_patient(c, "Maria Rotund", "079555123")
        a7 = row(c, "Rotund Maria")
        res.check("`+373 79…` файла находит фишу с `079…`",
                  [p["id"] for p in a7["hint"]["patients"]], [pid])
        res.check("телефона нет, имя не совпало — фиши не предлагаются",
                  row(c, "Balan Stefan")["hint"]["patients"], [])

        again = loaded(res, c, cal(base_events()), "вторая загрузка")
        res.check("загрузка дважды — ноль новых", (again["new"], again["updated"]), (0, 0))
        res.check("и счётчики те же", listing(c)["counts"],
                  {"nou": 3, "mutat": 0, "omis": 2, "nerecunoscut": 1, "schimbat": 0})

        res.ok("после загрузки пункт «Google Calendar» в «Sincronizări»", "gcal" in nav_keys(c),
               f"{nav_keys(c)}")
        item = next(x for x in shell_model(c.get("/admin").body)["nav"]["sync"] if x["key"] == "gcal")
        res.check("пункт несёт число не перенесённых", (item["href"], item["count"]),
                  ("/admin/google", 3))
        feed = [t[0] for t in sql(s, "SELECT text FROM activity WHERE kind = 'gcal'")]
        res.ok("загрузка — строкой в ленте клиники", len(feed) == 2 and "3 evenimente noi" in feed[0],
               f"{feed}")
        res.check("файл на диск не положен",
                  sorted(p.name for p in s.dir.rglob("*.ics")), [])

        # календарь переименовали в Google: те же события под другим именем
        renamed = loaded(res, c, cal(base_events(), "Alt nume"), "переименованный календарь")
        res.check("переименованный календарь не задваивает", renamed["new"], 0)
        d = listing(c)
        res.check("источник один, имя новое", ([x["name"] for x in d["sources"]], d["counts"]["nou"]),
                  (["Alt nume"], 3))

        # событие пропало из календаря и появилось новое
        gone = [e for e in base_events() if "UID:a2@" not in e] + [
            ev("a9", 6, "12:00", 30, "Nou Venit 068111222")]
        got = loaded(res, c, cal(gone, "Alt nume"), "изменённый календарь")
        res.check("одно новое, одно пропавшее", (got["new"], got["gone"]), (1, 1))
        res.check("пропавшее ушло в «Omise» со словом",
                  [x["why"]["code"] for x in rows(listing(c, "omis"))
                   if x["title"].startswith("Balan")], ["gone"])


def suite_move(res: Result) -> None:
    """Перенос в журнал тем же правилом, что окно записи; отказ тем же кодом;
    фиша по id; «Leagă»; «Nu muta» и обратно; изменившееся событие."""
    with Server() as s:
        c = Client(s.url).login()
        got = loaded(res, c, cal(base_events()), "загрузка")
        res.ok("годных строк не ноль", got.get("new", 0) > 0, f"{got}")
        a1 = row(c, "Popescu Ion")

        # ---- отказ: тем же кодом и полем, что окно записи журнала ----
        want = add_appt(c, _day(3), "23:00", "Ion Popescu", "069123456")
        r = c.post_json(f"/api/gcal/events/{a1['id']}/move",
                        move_body(3, "23:00", "Ion Popescu", "069123456"))
        res.check("вне часов клиники — как у окна записи", (r.status, r.msg, _j(r).get("field")),
                  (want.status, want.msg, _j(want).get("field")))
        res.ok("отказ — не удача", r.status == 422 and r.msg == "outside", f"{r!r}")
        r = c.post_json(f"/api/gcal/events/{a1['id']}/move", move_body(3, "09:00", "", "069123456"))
        res.check("пустое имя — отказ окна записи", (r.status, r.msg, _j(r).get("field")),
                  (422, "bad_name", "name"))
        res.check("после отказов событие на месте, записи нет",
                  (listing(c)["counts"]["nou"], len(day_model(c, _day(3))["list"])), (3, 0))

        # ---- перенос ----
        r = c.post_json(f"/api/gcal/events/{a1['id']}/move",
                        move_body(3, "09:00", "Ion Popescu", "069123456"))
        res.check("перенос прошёл кодом окна записи", (r.status, r.msg), (200, "ok"))
        data = _j(r)["data"]
        res.check("ответ — свежий список", (data["counts"]["nou"], data["counts"]["mutat"]), (2, 1))
        day = day_model(c, _day(3))["list"]
        res.check("запись в журнале: пациент и врач", [(x["name"], x["doctor"]) for x in day],
                  [("Ion Popescu", D2)])
        appt = sql(s, "SELECT id, comment, source, duration_min FROM appointments")
        res.check("название ушло в комментарий записи, источник — manual",
                  [(x[1], x[2]) for x in appt], [("Google: Popescu Ion 069123456 consult", "manual")])
        res.check("ответ назвал номер записи", data["appt_id"], appt[0][0])
        res.check("текст строки события стёрт, связь и отпечаток на месте",
                  sql(s, "SELECT title, body, state, appt_id, stamp_moved != '' FROM gcal_events "
                         "WHERE id = ?", a1["id"]), [("", "", "mutat", appt[0][0], 1)])
        m = rows(listing(c, "mutat"))
        res.check("«Mutate» показывает запись журнала, не текст Google",
                  [(x["title"], x["appt"]["patient"], x["appt"]["doctor"], x["appt"]["day_href"])
                   for x in m], [("", "Ion Popescu", D2, f"/admin/all?date={_day(3)}")])
        res.check("поиск находит перенесённое по имени пациента",
                  listing(c, "mutat", "popescu")["total"], 1)
        r = c.post_json(f"/api/gcal/events/{a1['id']}/move",
                        move_body(3, "09:00", "Ion Popescu", "069123456"))
        res.check("второй перенос того же события — отказ", (r.status, r.msg), (409, "gc_moved"))
        res.check("событие, которого нет, — отказ",
                  (c.post_json("/api/gcal/events/99999/move", move_body(3, "12:00", "X Y")).status,
                   c.post_json("/api/gcal/events/99999/skip", {"on": True}).msg), (409, "gc_gone"))

        # ---- занято: отказ журнала, событие остаётся ----
        a2 = row(c, "Balan Stefan")
        r = c.post_json(f"/api/gcal/events/{a2['id']}/move", move_body(3, "09:00", "Stefan Balan"))
        res.check("занятый час — отказ окна записи", (r.status, r.msg), (409, "conflict"))

        # ---- фиша по id: пациент без телефона не задваивается ----
        pid = new_patient(c, "Stefan Balan")
        before = sql(s, "SELECT COUNT(*) FROM patients")[0][0]
        res.check("точное имя одной фиши — подсказка",
                  [p["id"] for p in row(c, "Balan Stefan")["hint"]["patients"]], [pid])
        r = c.post_json(f"/api/gcal/events/{a2['id']}/move",
                        move_body(3, "10:30", "Balan Stefan", duration="60", pid=pid))
        res.check("перенос в выбранную фишу", (r.status, r.msg), (200, "ok"))
        res.check("запись легла этой фише, новой фиши нет, длительность — из события",
                  (sql(s, "SELECT patient_id, duration_min, duration_set, comment FROM appointments "
                          "WHERE starts_at LIKE ? ORDER BY id DESC LIMIT 1", _day(3) + "T%")[0],
                   sql(s, "SELECT COUNT(*) FROM patients")[0][0]),
                  ((pid, 60, 1, "Google: Balan Stefan - Dr. Doi — vine cu radiografie"), before))
        a7 = row(c, "Rotund Maria")
        r = c.post_json(f"/api/gcal/events/{a7['id']}/move",
                        move_body(3, "15:00", "Maria Rotund", pid=987654))
        res.check("фиши нет — отказ, событие на месте", (r.status, r.msg), (409, "gc_patient"))
        r = c.post_json(f"/api/gcal/events/{a7['id']}/move",
                        move_body(3, "23:00", "Maria Rotund", pid=pid))
        res.check("в фишу — те же часы клиники, что у окна записи", (r.status, r.msg),
                  (422, "outside"))

        # ---- «Leagă»: событие уже внесли руками ----
        res.check("запись руками на час события", add_appt(c, _day(3), "14:00", "Maria Rotund",
                                                            "079555123").msg, "ok")
        fresh = [ev("b1", 3, "14:00", 30, "Rotund Maria 079555123")]
        loaded(res, c, cal(base_events() + fresh), "событие на занятый час")
        b1 = row(c, "Rotund Maria 079")
        made = sql(s, "SELECT id FROM appointments WHERE comment = ''")[0][0]
        res.check("строка знает, что запись уже стоит", (b1["hint"]["exists"] or {}).get("appt_id"), made)
        n_before = sql(s, "SELECT COUNT(*) FROM appointments")[0][0]
        r = c.post_json(f"/api/gcal/events/{b1['id']}/link", {"appt_id": made})
        res.check("привязка", (r.status, r.msg), (200, "gc_linked"))
        res.check("второй записи нет, событие перенесено, комментарий записи получил название",
                  (sql(s, "SELECT COUNT(*) FROM appointments")[0][0],
                   sql(s, "SELECT state, appt_id, title FROM gcal_events WHERE id = ?", b1["id"]),
                   sql(s, "SELECT comment FROM appointments WHERE id = ?", made)),
                  (n_before, [("mutat", made, "")], [("Google: Rotund Maria 079555123",)]))
        res.check("привязка к записи, которой нет, — отказ",
                  (c.post_json(f"/api/gcal/events/{a7['id']}/link", {"appt_id": 99999}).msg), "gc_appt")

        # ---- «Nu muta» и обратно ----
        r = c.post_json(f"/api/gcal/events/{a7['id']}/skip", {"on": True})
        res.check("«Nu muta»", (r.status, r.msg, _j(r)["data"]["counts"]["omis"]), (200, "gc_skipped", 3))
        loaded(res, c, cal(base_events() + fresh), "загрузка после «Nu muta»")
        res.check("`omis` переживает загрузку",
                  sql(s, "SELECT state FROM gcal_events WHERE id = ?", a7["id"]), [("omis",)])
        r = c.post_json(f"/api/gcal/events/{a7['id']}/skip", {"on": False})
        res.check("«Readu în listă»", (r.status, r.msg, row(c, "Rotund Maria +373")["state"]),
                  (200, "gc_back", "nou"))
        a4 = row(c, "Anulat Vasile", "omis")
        c.post_json(f"/api/gcal/events/{a4['id']}/skip", {"on": False})
        loaded(res, c, cal(base_events() + fresh), "загрузка после возврата отменённого")
        res.check("возвращённое руками загрузка обратно не откладывает",
                  sql(s, "SELECT state FROM gcal_events WHERE id = ?", a4["id"]), [("nou",)])
        a6 = row(c, "Zi de nastere", "nerecunoscut")
        c.post_json(f"/api/gcal/events/{a6['id']}/skip", {"on": True})
        c.post_json(f"/api/gcal/events/{a6['id']}/skip", {"on": False})
        res.check("не разобранное возвращается не разобранным",
                  sql(s, "SELECT state FROM gcal_events WHERE id = ?", a6["id"]), [("nerecunoscut",)])
        res.check("кривое тело — отказ",
                  c.post_json(f"/api/gcal/events/{a7['id']}/skip", {"on": "da"}).status, 422)

        # ---- повторная загрузка не задваивает перенесённое; изменившееся — пометка ----
        n_appt = sql(s, "SELECT COUNT(*) FROM appointments")[0][0]
        shifted = [ev("a1", 4, "12:00", 30, "Popescu Ion 069123456 consult")] + [
            e for e in base_events() if "UID:a1@" not in e and "UID:a2@" not in e] + fresh
        got = loaded(res, c, cal(shifted), "событие сдвинули в Google после переноса")
        res.check("новых нет; сдвинутое и пропавшее — «изменилось»", (got["new"], got["changed"]), (0, 2))
        d = listing(c, "schimbat")
        res.check("фильтр «Schimbate în Google» появился", (d["counts"]["schimbat"],
                                                           d["filters"][-1]["key"]), (2, "schimbat"))
        ch = {x["appt"]["patient"]: x for x in rows(d)}
        res.check("сдвинутое: Google теперь в другом дне, запись — где была",
                  (ch["Ion Popescu"]["date"], ch["Ion Popescu"]["appt"]["when"]),
                  (_day(4), f"{_day(3)}T09:00"))
        res.check("пропавшее из календаря — со словом", ch["Stefan Balan"]["why"]["code"], "gone")
        res.check("журнал загрузкой не тронут",
                  (sql(s, "SELECT COUNT(*) FROM appointments")[0][0],
                   [x["time"] for x in day_model(c, _day(3))["list"]]),
                  (n_appt, ["09:00", "10:30", "14:00"]))


def suite_expiry(res: Result) -> None:
    """Срок: текст непереносённого события стирается через 7 дней после его
    даты, ключ остаётся; повторная загрузка строку не возвращает."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_test_"))
    try:
        _expiry(res, work)
    finally:
        _rmtree_settled(work)


def _expiry(res: Result, work: pathlib.Path) -> None:
    with Clock(clinic_now()) as clock:
        events = [ev("e1", 1, "10:00", 30, "Curand Trece 069222333", desc="de sunat"),
                  ev("e2", 20, "10:00", 30, "Mai Tarziu 069444555")]
        raw = cal(events)
        with Server(dir_=work) as s:
            c = Client(s.url).login()
            got = loaded(res, c, raw, "загрузка")
            res.ok("годных строк не ноль", got.get("new", 0) == 2, f"{got}")
            clock.set(clinic_now() + timedelta(days=6))
            res.check("дата прошла — в списке события уже нет",
                      [x["title"] for x in rows(listing(c))], ["Mai Tarziu 069444555"])
            res.check("а текст до срока ещё лежит",
                      sql(s, "SELECT title FROM gcal_events WHERE ext_key LIKE 'e1@%'"),
                      [("Curand Trece 069222333",)])
            clock.set(clinic_now() + timedelta(days=3))
            listing(c)
            res.check("срок вышел — текста нет, ключ остался",
                      sql(s, "SELECT title, body, ext_key FROM gcal_events WHERE ext_key LIKE 'e1@%'"),
                      [("", "", "e1@google.com")])
            res.check("у будущего события текст на месте",
                      sql(s, "SELECT title FROM gcal_events WHERE ext_key LIKE 'e2@%'"),
                      [("Mai Tarziu 069444555",)])
            again = loaded(res, c, raw, "тот же файл после срока")
            res.check("повторная загрузка не вернула строку",
                      (again["new"],
                       sql(s, "SELECT title FROM gcal_events WHERE ext_key LIKE 'e1@%'"),
                       sql(s, "SELECT COUNT(*) FROM gcal_events")[0][0]), (0, [("",)], 2))
            # «не переносить» текст оставляет, но срок у него тот же
            e2 = row(c, "Mai Tarziu")
            c.post_json(f"/api/gcal/events/{e2['id']}/skip", {"on": True})
            clock.set(clinic_now() + timedelta(days=30))
        with Server(dir_=work) as s2:
            # уборка на старте: вкладку никто не открывал
            res.check("старт программы убирает просроченный текст сам",
                      sql(s2, "SELECT title, state FROM gcal_events WHERE ext_key LIKE 'e2@%'"),
                      [("", "omis")])
            c = Client(s2.url).login()
            r = c.post_json(f"/api/gcal/events/{e2['id']}/skip", {"on": False})
            res.check("строку без текста вернуть в список нельзя", (r.status, r.msg),
                      (409, "gc_no_text"))


def suite_erase(res: Result) -> None:
    """Стирание и обезличивание пациента убирают события его записей и
    непереносённые события с его телефоном; «Șterge tot» оставляет только
    ключи перенесённого; в базе не остаётся ни имени, ни номера."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_test_"))
    try:
        with Server(dir_=work) as s:
            c = Client(s.url).login()
            events = [ev("m1", 3, "09:00", 30, "Zqmarcaj Ion 07100230045"),
                      ev("m2", 5, "09:00", 30, "Zqmarcaj din nou", desc="tel 071-002-300-45"),
                      ev("m3", 3, "11:00", 30, "Alt Om 069333444"),
                      ev("m4", 6, "09:00", 30, "Platitor Petru 069777888"),
                      ev("m5", 6, "11:00", 30, "Ramane Sus 069555666")]
            got = loaded(res, c, cal(events), "загрузка")
            res.ok("годных строк не ноль", got.get("new", 0) == 5, f"{got}")
            m1 = row(c, "Zqmarcaj Ion")
            r = c.post_json(f"/api/gcal/events/{m1['id']}/move",
                            move_body(3, "09:00", "Ion Zqmarcaj", "07100230045"))
            res.check("перенос", r.msg, "ok")
            pid = sql(s, "SELECT patient_id FROM appointments")[0][0]
            r = c.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"})
            res.check("фиша с одной будущей записью стирается целиком", r.msg, "ok_del")
            res.check("запись ушла; событие записи и событие с его номером — пустые ключи",
                      (sql(s, "SELECT COUNT(*) FROM appointments")[0][0],
                       sql(s, "SELECT state, title, body, appt_id, stamp FROM gcal_events "
                              "WHERE ext_key IN ('m1@google.com', 'm2@google.com') ORDER BY ext_key")),
                      (0, [("sters", "", "", None, ""), ("sters", "", "", None, "")]))
            d = listing(c)
            res.check("в списках их нет, чужие события на месте",
                      (sorted(x["title"] for x in rows(d)), d["counts"]["mutat"]),
                      (["Alt Om 069333444", "Platitor Petru 069777888", "Ramane Sus 069555666"], 0))
            again = loaded(res, c, cal(events), "тот же файл после стирания")
            res.check("загрузка не возвращает стёртого человека",
                      (again["new"], sorted(x["title"] for x in rows(listing(c)))),
                      (0, ["Alt Om 069333444", "Platitor Petru 069777888", "Ramane Sus 069555666"]))

            # обезличивание: фиша с платежом остаётся под номером
            pid2 = new_patient(c, "Petru Platitor", "069777888")
            c.post_json(f"/api/patients/{pid2}/payments", {"amount": "300", "method": "card"})
            r = c.post_json(f"/api/patients/{pid2}/erase", {"confirm": "STERG"})
            res.check("фиша с платежом обезличивается", r.msg, "ok_anon")
            res.check("непереносённое событие с его номером — пустой ключ",
                      sql(s, "SELECT state, title FROM gcal_events WHERE ext_key = 'm4@google.com'"),
                      [("sters", "")])

            # «Șterge tot»
            m3 = row(c, "Alt Om")
            c.post_json(f"/api/gcal/events/{m3['id']}/move", move_body(3, "11:00", "Alt Om", "069333444"))
            r = c.post_json("/api/gcal/clear", {})
            res.check("«Șterge tot din Google»", (r.status, r.msg), (200, "gc_cleared"))
            res.check("остались только ключи перенесённого и стёртого, текста нет нигде",
                      (sql(s, "SELECT DISTINCT state FROM gcal_events ORDER BY state"),
                       sql(s, "SELECT COUNT(*) FROM gcal_events WHERE title != '' OR body != ''"),
                       sql(s, "SELECT COUNT(*) FROM gcal_sources WHERE name != '' OR loaded_at "
                              "IS NOT NULL")),
                      ([("mutat",), ("sters",)], [(0,)], [(0,)]))
            res.ok("пункта меню больше нет", "gcal" not in nav_keys(c), f"{nav_keys(c)}")
            res.check("вкладка пуста, полосы источника нет",
                      (listing(c)["source"], listing(c, "mutat")["total"]), (None, 1))
            feed = [t[0] for t in sql(s, "SELECT text FROM activity WHERE kind = 'gcal'")]
            res.ok("стирание — строкой в ленте клиники", "șterse" in feed[-1], f"{feed}")
            n_appt = sql(s, "SELECT COUNT(*) FROM appointments")[0][0]
            again = loaded(res, c, cal(events), "тот же файл после «Șterge tot»")
            res.check("повторная загрузка не задваивает перенесённое и не возвращает стёртое",
                      (again["new"], sorted(x["title"] for x in rows(listing(c))),
                       sql(s, "SELECT COUNT(*) FROM appointments")[0][0]),
                      (1, ["Ramane Sus 069555666"], n_appt))
            res.ok("пункт меню вернулся", "gcal" in nav_keys(c), f"{nav_keys(c)}")
            c.post_json("/api/gcal/clear", {})
        # ни имени, ни номера стёртого — ни в одной таблице
        con = sqlite3.connect(str(work / "dental.db"))
        try:
            found = []
            for (t,) in list(con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")):
                for r_ in con.execute(f'SELECT * FROM "{t}"'):
                    blob = " · ".join(str(v) for v in r_)
                    if "Zqmarcaj" in blob or "07100230045" in blob or "071-002" in blob:
                        found.append(f"{t}: {blob[:120]}")
            tables = [r_[0] for r_ in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        finally:
            con.close()
        res.ok("обход нашёл таблицы календаря", {"gcal_events", "gcal_sources"} <= set(tables),
               f"{tables}")
        res.check("стёртого человека нет ни в одной таблице", found, [])
    finally:
        _rmtree_settled(work)


def suite_rights(res: Result) -> None:
    """Вкладку видят директор и регистратура; врач — 403 и без пункта меню;
    «Șterge tot» — только директор; режим «только чтение» — 423."""
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        for body in ({"uid": "d2", "name": D2, "role": "medic", "doctor_id": "d2", "pin": "2222"},
                     {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "4444"}):
            res.check(f"учётка {body['role']} заведена",
                      boss.post_json("/api/settings/users", body).msg, "ok_user")
        got = loaded(res, boss, cal(base_events()), "директор загружает")
        res.ok("годных строк не ноль", got.get("new", 0) > 0, f"{got}")
        res.check("итог называет причины пропуска: на весь день, отменено, прошло, дальше года",
                  (got.get("all_day"), got.get("cancelled"), got.get("past"), got.get("beyond")),
                  (1, 1, 2, 1))
        a1 = row(boss, "Popescu Ion")

        med = Client(s.url)
        med.post("/admin/login", password="2222", next="/admin")
        r = med.get("/api/gcal")
        res.check("врач: список — 403", (r.status, r.msg), (403, "no_access"))
        for path, body in ((f"/api/gcal/events/{a1['id']}/move", move_body(3, "09:00", "Ion Popescu")),
                           (f"/api/gcal/events/{a1['id']}/skip", {"on": True}),
                           (f"/api/gcal/events/{a1['id']}/link", {"appt_id": 1}),
                           ("/api/gcal/source", {"service": "consult"}),
                           ("/api/gcal/clear", {})):
            res.check(f"врач: {path.rsplit('/', 1)[-1]} — 403", med.post_json(path, body).status, 403)
        res.check("врач: загрузка — 403", upload(med, cal(base_events())).status, 403)
        res.ok("врач: страница закрыта", med.get("/admin/google").status in (303, 307), "")
        res.ok("врач: пункта меню нет", "gcal" not in nav_keys(med), f"{nav_keys(med)}")
        res.check("врач ничего не изменил", listing(boss)["counts"]["nou"], 3)

        ana = Client(s.url)
        ana.post("/admin/login", password="4444", next="/admin")
        res.check("регистратура: список открыт", ana.get("/api/gcal").status, 200)
        page = ana.get("/admin/google")
        res.ok("регистратура: страница — экран gcal",
               page.status == 200 and 'data-screen="gcal"' in page.body, f"{page.status}")
        res.ok("регистратура: пункт меню есть", "gcal" in nav_keys(ana), f"{nav_keys(ana)}")
        res.check("регистратура: стирать всё нельзя — кнопки нет и маршрут закрыт",
                  (listing(ana)["can"]["clear"], ana.post_json("/api/gcal/clear", {}).status),
                  (False, 403))
        r = ana.post_json(f"/api/gcal/events/{a1['id']}/move",
                          move_body(3, "09:00", "Ion Popescu", "069123456"))
        res.check("регистратура переносит", (r.status, r.msg), (200, "ok"))
        res.check("перенос подписан именем вошедшего",
                  sql(s, "SELECT moved_by FROM gcal_events WHERE id = ?", a1["id"]), [("Ana R",)])
        res.check("директор: процедура по умолчанию",
                  (boss.post_json("/api/gcal/source", {"service": "consult"}).msg,
                   row(boss, "Balan Stefan")["preset"]["service"],
                   boss.post_json("/api/gcal/source", {"service": "nu-exista"}).status),
                  ("gc_set", "consult", 422))
        res.check("директор: стирать всё можно",
                  (listing(boss)["can"]["clear"], boss.post_json("/api/gcal/clear", {}).msg),
                  (True, "gc_cleared"))

    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_gcal_ro_"))
    try:
        shutil.copy(FIXTURES / "license" / "expired.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            res.ok("сервер в режиме чтения", "license: state=readonly" in s.log_text())
            c = Client(s.url).login()
            res.check("чтение: список открыт", c.get("/api/gcal").status, 200)
            for path in ("/api/gcal/events/1/move", "/api/gcal/events/1/skip",
                         "/api/gcal/events/1/link", "/api/gcal/source", "/api/gcal/clear"):
                r = c.post_json(path, {})
                res.check(f"чтение: {path} — 423", (r.status, r.msg), (423, "license_readonly"))
            r = upload(c, cal(base_events()))
            res.check("чтение: загрузка — 423", (r.status, r.msg), (423, "license_readonly"))
            res.check("в режиме чтения ничего не легло", sql(s, "SELECT COUNT(*) FROM gcal_events"),
                      [(0,)])
    finally:
        _rmtree_settled(d)


def suite_round(res: Result) -> None:
    """Начало и длина окна записи — из конвертера: начало к ближайшим пяти
    минутам, длина как в Google, некратная пяти — вверх. В таблице время
    остаётся как в календаре."""
    with Server() as s:
        c = Client(s.url).login()
        got = loaded(res, c, cal([ev("r1", 3, "11:08", 30, "Tarziu Dan 068333222"),
                                  ev("r2", 3, "14:07", 23, "Rotund Maria 079555123"),
                                  ev("r3", 3, "16:00", 30, "Exact Ana 069111000"),
                                  ev("r4", 3, "17:03", 5, "Scurt Ion 069111001")]), "загрузка")
        res.ok("годных строк не ноль", got.get("new", 0) == 4, f"{got}")
        r1, r2, r3, r4 = rows(listing(c))
        res.check("11:08 на 30 минут → окно 11:10 на 30",
                  (r1["time"], r1["minutes"], r1["preset"]["time"], r1["preset"]["duration"], r1["round"]),
                  ("11:08", 30, "11:10", "30", {"from": "11:08–11:38", "to": "11:10–11:40"}))
        res.check("14:07 на 23 минуты → окно 14:05 на 25",
                  (r2["preset"]["time"], r2["preset"]["duration"], r2["round"]),
                  ("14:05", "25", {"from": "14:07–14:30", "to": "14:05–14:30"}))
        res.check("кратное пяти — без пометки",
                  (r3["preset"]["time"], r3["preset"]["duration"], r3["round"]), ("16:00", "30", None))
        res.check("17:03 на 5 минут → окно 17:05 на 5",
                  (r4["preset"]["time"], r4["preset"]["duration"]), ("17:05", "5"))
        res.check("в таблице — время и длина как в календаре",
                  sql(s, "SELECT substr(starts_at, 15, 2), minutes FROM gcal_events ORDER BY starts_at"),
                  [("08", 30), ("07", 23), ("00", 30), ("03", 5)])
        again = loaded(res, c, cal([ev("r1", 3, "11:08", 30, "Tarziu Dan 068333222"),
                                    ev("r2", 3, "14:07", 23, "Rotund Maria 079555123"),
                                    ev("r3", 3, "16:00", 30, "Exact Ana 069111000"),
                                    ev("r4", 3, "17:03", 5, "Scurt Ion 069111001")]), "вторая загрузка")
        res.check("округлённое не выглядит изменившимся при повторной загрузке",
                  (again["new"], again["updated"]), (0, 0))
        # запись на час округлённого события узнаётся как уже стоящая
        res.check("запись руками на 14:00", add_appt(c, _day(3), "14:00", "Maria Rotund", "079555123").msg, "ok")
        res.check("запись на другом старте за округлённое событие не принимается",
                  row(c, "Rotund Maria")["hint"]["exists"], None)


def suite_after_grid(res: Result) -> None:
    """Старт не на :00/:30 и длительность 20 минут ложатся как есть. Верно
    только с правилом «старт с шагом 5 минут, длительность кратно 5»."""
    with Server() as s:
        c = Client(s.url).login()
        got = loaded(res, c, cal([ev("g1", 3, "09:10", 20, "Scurt Vasile 069123123"),
                                  ev("g3", 3, "11:08", 30, "Tarziu Dan 068333222"),
                                  ev("g2", 3, "14:07", 23, "Rotund Maria 079555123")]), "загрузка")
        res.ok("годных строк не ноль", got.get("new", 0) == 3, f"{got}")
        g1, g3, g2 = rows(listing(c))
        for r_, name in ((g1, "Vasile Scurt"), (g3, "Dan Tarziu"), (g2, "Maria Rotund")):
            p = r_["preset"]
            r = c.post_json(f"/api/gcal/events/{r_['id']}/move",
                            {**p, "name": name, "service": "consult", "doctor": "d2"})
            res.check(f"{p['time']} на {p['duration']} минут — перенос", (r.status, r.msg), (200, "ok"))
        res.check("записи легли с часами и длиной события",
                  sql(s, "SELECT substr(starts_at, 12, 5), duration_min, duration_set "
                         "FROM appointments ORDER BY starts_at"),
                  [(x, y, 1) for x, y in _utc_times(("09:10", 20), ("11:10", 30), ("14:05", 25))])
        res.check("исходные часы округлённого — в комментарии",
                  [x[0] for x in sql(s, "SELECT comment FROM appointments ORDER BY starts_at")][1:],
                  ["Google: Tarziu Dan 068333222 (11:08–11:38)",
                   "Google: Rotund Maria 079555123 (14:07–14:30)"])


def _utc_times(*pairs) -> list:
    """Стенные часы Кишинёва дня +3 → часы UTC, как их хранит база."""
    from datetime import datetime, timezone
    from harness import TZ
    out = []
    d = clinic_today() + timedelta(days=3)
    for hhmm, minutes in pairs:
        h, m = (int(x) for x in hhmm.split(":"))
        at = datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).astimezone(timezone.utc)
        out.append((f"{at:%H:%M}", minutes))
    return out
