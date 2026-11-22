"""Вкладка «Google Calendar»: перенос в журнал пачкой и автоматом (`modules/schedule/gcal_auto.py`).

Живой сервер программы и стенд Google из test_gapi, как у test_gcal_link: связь с аккаунтом —
настоящим входом (`Google.consent` → `/google/back`), право Plus / Basic / режим чтения — подписанным
файлом лицензии. Журнал, фиши, летопись и метка SMS читаются из базы набора (`sql`)."""
from __future__ import annotations

import json
import pathlib
import sqlite3
import tempfile
from datetime import datetime, timedelta

import test_gapi as tg
from harness import Client, Result, Server, TZ, _rmtree_settled, clinic_today, new_patient
from test_gcal import _day, cal, ev, listing, rows, sql, upload
from test_gcal_link import CAL, MAIN, client_file, env, google, login, put_license, wait_until

SRC = pathlib.Path(__file__).resolve().parents[1] / "bot" / "app" / "modules" / "schedule" / "gcal_auto.py"


def _j(r) -> dict:
    return json.loads(r.body)


def gev(uid: str, n: int, hhmm: str, minutes: int, title: str, desc: str = "", status: str = "confirmed") -> dict:
    d = clinic_today() + timedelta(days=n)
    h, m = (int(x) for x in hhmm.split(":"))
    start = datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)
    end = start + timedelta(minutes=minutes)
    out = {"id": uid, "iCalUID": f"{uid}@google.com", "status": status, "summary": title,
           "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Chisinau"},
           "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Chisinau"}}
    if desc:
        out["description"] = desc
    return out


def stand(events: list) -> tg.Google:
    g = tg.Google()
    g.calendars = [
        {"id": MAIN, "summary": "Clinica", "primary": True, "accessRole": "owner", "timeZone": "Europe/Chisinau"},
        {"id": CAL, "summary": "Programări", "accessRole": "owner", "timeZone": "Europe/Chisinau"},
    ]
    g.events = {MAIN: [], CAL: list(events)}
    return g


def connect(res: Result, s: Server, c: Client, g: tg.Google, tag: str) -> None:
    _url, back = login(res, s, c, g, tag)
    res.check(f"{tag}: вход в браузере завершён", back.status if back else None, 200)
    wait_until(lambda: (google(c) or {}).get("state") == "choose")
    r = c.post_json("/api/gcal/google/calendar", {"id": CAL})
    res.check(f"{tag}: календарь выбран и проверен", r.msg, "gc_g_calendar")


def by_title(data: dict) -> dict:
    return {x["title"]: x for x in rows(data)}


def preview(c: Client, auto: bool = False, q: str = "") -> dict:
    r = c.post_json(f"/api/gcal/batch/check?q={q}", {"auto": auto})
    if r.status != 200:
        raise AssertionError(f"предпросмотр не отдан: {r.status} {r.body[:200]}")
    return _j(r)["data"]["preview"]


def run(c: Client, pv: dict, auto: bool = False, q: str = ""):
    return c.post_json(f"/api/gcal/batch/run?q={q}", {"token": pv["token"], "auto": auto})


def why_of(pv: dict) -> dict:
    out = {x["title"]: "go" for x in pv["go"]}
    out.update({x["title"]: x["why"]["code"] for x in pv["stay"]})
    return out


def appts(s: Server, name: str) -> list:
    """(id, статус, начало UTC, длина, врач, sms_skip, комментарий) записей пациента по имени."""
    return sql(s, "SELECT a.id, a.status, a.starts_at, a.duration_min, a.doctor_id, a.sms_skip, a.comment "
                  "FROM appointments a JOIN patients p ON p.id = a.patient_id WHERE p.name = ? ORDER BY a.id", name)


def actors(s: Server, name: str) -> set:
    """Кто завёл фишу. Строку «Programare: …» журнал подписывает каналом («recepție») у любой записи."""
    return {r[0] for r in sql(s, "SELECT e.actor FROM activity e JOIN patients p ON p.id = e.patient_id "
                                 "WHERE p.name = ? AND e.kind = 'created'", name)}


def write(s: Server, query: str, *args) -> None:
    con = sqlite3.connect(str(s.dir / "dental.db"), timeout=5)
    try:
        con.execute(query, args)
        con.commit()
    finally:
        con.close()


def seed(c: Client) -> dict:
    ids = {name: new_patient(c, name, phone) for name, phone in (
        ("Rotaru Ana", "079555111"), ("Ceban Maria", "060700800"), ("Popa Maria", "069123456"),
        ("Grosu Ion", "069800900"), ("Lupu Vasile", "068777666"), ("Lupu Elena", "068777665"),
        ("Ursu Mihai", "079222333"), ("Bejan Olga", "068909808"))}
    return ids


RULE_EVENTS = [
    gev("r1", 3, "09:00", 30, "Lungu Petru 069111222 - dr Doi"),
    gev("r2", 3, "10:00", 45, "Rotaru Ana 079555111 igienizare Dr. Trei"),
    gev("r3", 3, "11:00", 30, "Ceban Maria - Dr. Patru"),
    gev("r4", 3, "12:00", 30, "Sandu Ion control"),
    gev("r5", 3, "13:00", 30, "Popa Ion 069123456 dr Doi"),
    gev("r6", 3, "14:00", 30, "Moraru Tatiana 060123456 - Doi / Trei"),
    gev("r7", 3, "15:00", 30, "Cebotari Olga - dr Trei"),
    gev("r8", 3, "16:00", 60, "Grosu Natalia 068444555 - dr Doi"),
    gev("r9", 3, "17:00", 300, "Vieru Sergiu 068111000 implant dr Doi"),
    gev("r10", 4, "09:00", 30, "Lupu Andrei 068777666 dr Trei"),
    gev("r11", 4, "10:00", 30, "Ursu Mihai 079222333 dr Doi"),
    gev("r12", 4, "11:00", 30, "Bejan Olga 068909808 dr Trei"),
    gev("r13", 4, "12:00", 30, "Gutu Vasile 069777888", desc="Trimis la Dr. Patru"),
    gev("r14", 4, "13:00", 30, "Botnaru Ion 069555444", desc="Patru"),
    gev("r15", 4, "14:00", 30, "Lazar Dan 069404505 dr Unu"),
    gev("r16", 4, "15:00", 30, "Ceban Maria 060999888 dr Trei"),
    gev("r17", 4, "16:00", 30, "Ion 069300300 dr Doi"),
    gev("r18", 4, "17:00", 30, "Pavel Ion 069301301 dr Patru"),
    gev("r19", 4, "17:00", 30, "Pavel Ana 069302302 dr Patru"),
]


# ---------- правило ----------


def suite_rule(res: Result) -> None:
    """Какое событие переносится само: врач в названии или с меткой в описании, пациент без человека,
    свободный час; остальное — с причиной."""
    res.ok("исходник автопереноса нашёлся", SRC.is_file(), str(SRC))
    g = stand(RULE_EVENTS)
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        put_license(d, 1, 30)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            seed(c)
            write(s, "UPDATE patients SET phone = '068777666' WHERE name = 'Lupu Elena'")
            for name, phone, day, hhmm, doctor in (("Grosu Ion", "069800900", 3, "16:00", "d2"),
                                                   ("Ursu Mihai", "079222333", 4, "10:00", "d2"),
                                                   ("Bejan Olga", "068909808", 4, "11:00", "d2")):
                r = c.post_json("/api/schedule/appointments", {"date": _day(day), "time": hhmm, "doctor": doctor,
                                                               "service": "consult", "name": name, "phone": phone})
                res.ok(f"засев: запись {name}", r.msg in ("ok", "ok_other"), r.msg)
            connect(res, s, c, g, "правило")
            pv = preview(c)
            got = why_of(pv)
            want = {
                "Lungu Petru 069111222 - dr Doi": "go",
                "Rotaru Ana 079555111 igienizare Dr. Trei": "go",
                "Ceban Maria - Dr. Patru": "go",
                "Sandu Ion control": "a_doctor",
                "Popa Ion 069123456 dr Doi": "a_other",
                "Moraru Tatiana 060123456 - Doi / Trei": "a_doctors",
                "Cebotari Olga - dr Trei": "a_nobody",
                "Grosu Natalia 068444555 - dr Doi": "conflict",
                "Vieru Sergiu 068111000 implant dr Doi": "a_check",
                "Lupu Andrei 068777666 dr Trei": "a_family",
                "Ursu Mihai 079222333 dr Doi": "go",
                "Bejan Olga 068909808 dr Trei": "a_exists",
                "Gutu Vasile 069777888": "go",
                "Botnaru Ion 069555444": "a_doctor",
                "Lazar Dan 069404505 dr Unu": "a_doctor_off",
                "Ceban Maria 060999888 dr Trei": "a_name_phone",
                "Ion 069300300 dr Doi": "a_name",
                "Pavel Ion 069301301 dr Patru": "go",
                "Pavel Ana 069302302 dr Patru": "conflict",
            }
            for title, code in want.items():
                res.check(f"правило: «{title}»", got.get(title), code)
            go = {x["title"]: x for x in pv["go"]}
            res.check("новая фиша: имя без слов врача, телефон с нулём",
                      (go["Lungu Petru 069111222 - dr Doi"]["patient"], go["Lungu Petru 069111222 - dr Doi"]["fresh"],
                       go["Lungu Petru 069111222 - dr Doi"]["phone"]), ("Lungu Petru", True, "069111222"))
            res.check("по телефону — фиша номера, слово услуги в названии не мешает",
                      (go["Rotaru Ana 079555111 igienizare Dr. Trei"]["patient"],
                       go["Rotaru Ana 079555111 igienizare Dr. Trei"]["fresh"]), ("Rotaru Ana", False))
            res.check("уже стоит в журнале у того же врача — «Leagă», второй записи нет",
                      go["Ursu Mihai 079222333 dr Doi"]["link"], True)
            res.check("врач из описания — только с меткой «Dr.»", go["Gutu Vasile 069777888"]["doctor"], "Dr. Activ Patru")
            stay = {x["title"]: x["why"]["text"] for x in pv["stay"]}
            res.check("причина словами: телефон чужой фиши называет её",
                      stay["Popa Ion 069123456 dr Doi"], "telefonul este al fișei Popa Maria")
            res.check("причина часа журнала — словами", stay["Grosu Natalia 068444555 - dr Doi"], "ora este ocupată")
            res.check("счётчики предпросмотра (второе событие того же врача на тот же час — занято пачкой)",
                      pv["counts"], {"go": 6, "fresh": 3, "stay": 13, "all": 19})
            # список вкладки: те же причины у строк, полоса считает годные без часа журнала
            data = listing(c)
            rws = by_title(data)
            res.check("строка списка: причина «nu se mută singur»",
                      (rws["Sandu Ion control"]["auto"]["why"] or {}).get("code"), "a_doctor")
            res.check("строка списка: причина часа журнала запомнена предпросмотром",
                      (rws["Grosu Natalia 068444555 - dr Doi"]["auto"]["why"] or {}).get("code"), "conflict")
            res.check("строка списка: годная — без причины", rws["Lungu Petru 069111222 - dr Doi"]["auto"]["why"], None)
            res.check("полоса пачки: годных и всего (час журнала и пачки она не считает)",
                      (data["automove"]["batch"]["go"], data["automove"]["batch"]["all"]), (6, 19))
            # решение человека: «Nu muta» и «Readu în listă» — строка больше не переносится сама
            rid = rws["Lungu Petru 069111222 - dr Doi"]["id"]
            c.post_json(f"/api/gcal/events/{rid}/skip", {"on": True})
            c.post_json(f"/api/gcal/events/{rid}/skip", {"on": False})
            res.check("возвращённая человеком в список — «lăsat de dvs.»",
                      why_of(preview(c)).get("Lungu Petru 069111222 - dr Doi"), "a_hand")
            res.ok("предпросмотр ничего не перенёс", not sql(s, "SELECT 1 FROM gcal_events WHERE state = 'mutat'"))
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- пачка ----------


def suite_batch(res: Result) -> None:
    """Пачка: переносится ровно то, что видели; метка SMS — по настройке вкладки; летопись — человек;
    мутация в истории."""
    g = stand([gev("b1", 3, "09:00", 30, "Lungu Petru 069111222 - dr Doi"),
               gev("b2", 3, "10:00", 45, "Rotaru Ana 079555111 Dr. Trei"),
               gev("b3", 3, "11:00", 30, "Sandu Ion control")])
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        put_license(d, 1, 30)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            seed(c)
            connect(res, s, c, g, "пачка")
            pv = preview(c)
            res.check("до пачки: SMS выключены по умолчанию", pv["sms"]["on"], False)
            # событие сдвинули в Google между предпросмотром и запуском — отпечаток не тот
            for k in ("start", "end"):
                t = datetime.fromisoformat(g.events[CAL][0][k]["dateTime"]) + timedelta(minutes=60)
                g.events[CAL][0][k]["dateTime"] = t.isoformat()
            c.post_json("/api/gcal/google/check", {})
            r = run(c, pv)
            res.check("список изменился после предпросмотра — «gc_a_stale», ничего не перенесено",
                      (r.status, r.msg, sql(s, "SELECT COUNT(*) FROM gcal_events WHERE state = 'mutat'")[0][0]),
                      (409, "gc_a_stale", 0))
            pv = preview(c)
            r = run(c, pv)
            body = _j(r)
            res.check("пачка: перенесено два, новая фиша одна", (r.status, r.msg, body["data"]["batch"]["n"],
                                                                body["data"]["batch"]["fresh"]),
                      (200, "gc_a_moved", 2, 1))
            lungu, rotaru = appts(s, "Lungu Petru"), appts(s, "Rotaru Ana")
            res.check("запись Lungu: врач, длина из Google, без SMS",
                      [(x[4], x[3], x[5]) for x in lungu], [("d2", 30, 1)])
            res.ok("комментарий записи — название из Google", lungu and lungu[0][6].startswith("Google: Lungu Petru"),
                   repr(lungu))
            res.check("запись Rotaru: фиша номера, врач из названия", [(x[4], x[5]) for x in rotaru], [("d3", 1)])
            res.check("летопись — человек, не «sistem»", actors(s, "Lungu Petru"), {"Director"})
            res.check("события: как и кем перенесены", sorted(sql(
                s, "SELECT moved_how, moved_by FROM gcal_events WHERE state = 'mutat'")),
                [("batch", "Director"), ("batch", "Director")])
            data = listing(c)
            mv = data["automove"]["moves"]
            res.check("история: одна мутация пачкой", [(m["how"], m["n"], m["fresh"], m["undone"]) for m in mv],
                      [("batch", 2, 1, None)])
            res.check("«Mutate»: строка знает, что перенесена пачкой",
                      sorted(x["auto"]["how"] for x in rows(listing(c, "mutat"))), ["batch", "batch"])
            # SMS включены — следующая пачка без метки
            r = c.post_json("/api/gcal/sms", {"on": True})
            res.check("галочка SMS: ответ и состояние", (r.msg, _j(r)["data"]["automove"]["sms"]["on"]),
                      ("gc_a_sms_on", True))
            g.events[CAL].append(gev("b4", 5, "09:00", 30, "Ceban Maria - Dr. Patru"))
            c.post_json("/api/gcal/google/check", {})
            r = run(c, preview(c))
            res.check("SMS включены: запись пачки без метки «без SMS»", (r.msg, [x[5] for x in appts(s, "Ceban Maria")]),
                      ("gc_a_moved", [0]))
            r = run(c, preview(c))
            res.check("переносить нечего — «gc_a_none»", (r.status, r.msg), (200, "gc_a_none"))
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- автоперенос ----------


def suite_auto(res: Result) -> None:
    """Автоперенос: включается предпросмотром, переносит на опросе и на «Verifică acum», подписан
    «sistem», стоит при Basic и в режиме чтения, выключается сменой календаря и отключением."""
    g = stand([gev("u1", 3, "09:00", 30, "Lungu Petru 069111222 - dr Doi"),
               gev("u2", 3, "10:00", 30, "Sandu Ion control")])
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        put_license(d, 1, 30)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            seed(c)
            r = run(c, {"token": "x"}, auto=True)
            res.check("без связи автоперенос не включить", (r.status, r.msg), (409, "gc_a_auto_no"))
            connect(res, s, c, g, "авто")
            b = google(c)
            res.check("галочка: выключена, включить можно", b["auto"], {"on": False, "can_on": True, "can_off": False,
                                                                       "stopped": False})
            pv = preview(c, auto=True)
            res.check("предпросмотр включения — то же правило", why_of(pv),
                      {"Lungu Petru 069111222 - dr Doi": "go", "Sandu Ion control": "a_doctor"})
            r = run(c, pv, auto=True)
            res.check("«Mută și pornește»: перенос и включение", (r.status, r.msg, _j(r)["data"]["google"]["auto"]["on"]),
                      (200, "gc_a_auto_on", True))
            res.check("первая пачка подписана человеком", actors(s, "Lungu Petru"), {"Director"})
            res.ok("галочка лежит в файле связи", json.loads((d / "google.json").read_text("utf-8"))["auto"]["on"])
            # новое событие пришло в Google — «Verifică acum» переносит его само
            g.events[CAL].append(gev("u3", 4, "09:00", 30, "Ursu Ion 069700700 dr Trei"))
            r = c.post_json("/api/gcal/google/check", {})
            res.check("«Verifică acum»: новое событие в журнале", (r.msg, [x[4] for x in appts(s, "Ursu Ion")]),
                      ("gc_g_checked", ["d3"]))
            res.check("автоперенос подписан «sistem»: фиша и событие", (actors(s, "Ursu Ion"), sql(
                s, "SELECT moved_how, moved_by FROM gcal_events WHERE ext_key LIKE 'u3%'")),
                ({"sistem"}, [("auto", "sistem")]))
            res.check("летопись клиники: строка автопереноса — «sistem»", sql(
                s, "SELECT actor FROM activity WHERE kind = 'gcal' AND text LIKE '%(automat)%'"), [("sistem",)])
            mv = listing(c)["automove"]
            res.check("история и «Ultima»: автоперенос одной записи", (mv["moves"][0]["how"], mv["moves"][0]["n"],
                                                                     (mv["last"] or {}).get("n")), ("auto", 1, 1))
            res.check("строка без врача осталась в «De mutat»", [x["title"] for x in rows(listing(c))],
                      ["Sandu Ion control"])
        # фоновый опрос раз в секунду: перенос без запроса, подпись — «sistem»
        with Server(dir_=d, env=env(g, client, tick="1")) as s:
            c = Client(s.url).login()
            g.events[CAL].append(gev("u4", 5, "09:00", 30, "Bejan Ana 068500500 dr Patru"))
            res.ok("опрос сам перенёс новое событие", wait_until(lambda: bool(appts(s, "Bejan Ana"))),
                   repr(appts(s, "Bejan Ana")))
            res.check("фоновый перенос подписан «sistem»", actors(s, "Bejan Ana"), {"sistem"})
        # Basic: опрос и автоперенос стоят, галочка хранится
        put_license(d, 2, None)
        with Server(dir_=d, env=env(g, client, tick="1")) as s:
            c = Client(s.url).login()
            g.events[CAL].append(gev("u5", 6, "09:00", 30, "Basic Ion 068600600 dr Doi"))
            r = c.post_json("/api/gcal/google/check", {})
            res.check("Basic: проверки нет", (r.status, r.msg), (409, "gc_g_plus"))
            b = google(c)
            res.check("Basic: галочка видна включённой, но стоит", (b["state"], b["auto"]["on"], b["auto"]["can_on"],
                                                                   b["auto"]["stopped"]), ("plus", True, False, True))
            res.ok("Basic: ничего не перенеслось", not wait_until(lambda: bool(appts(s, "Basic Ion")), 3.0))
            pv = preview(c)
            res.check("Basic: пачка по файлу и вкладке работает", pv["counts"]["all"] >= 1, True)
        # режим чтения: автоперенос стоит, выключить можно
        put_license(d, 3, 30, readonly=True)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            res.check("режим чтения: пачка — 423", run(c, {"token": "x"}).status, 423)
            r = c.post_json("/api/gcal/auto", {"on": False})
            res.check("режим чтения: выключить автоперенос можно", (r.status, r.msg), (200, "gc_a_auto_off"))
            res.ok("…и ничего не перенеслось", not appts(s, "Basic Ion"))
        put_license(d, 4, 30)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            res.check("включить — только предпросмотром", c.post_json("/api/gcal/auto", {"on": True}).status, 422)
            r = run(c, preview(c, auto=True), auto=True)
            res.check("снова включён", r.msg, "gc_a_auto_on")
            r = c.post_json("/api/gcal/google/calendar", {"id": MAIN})
            res.check("другой календарь — автоперенос выключен", (r.msg, google(c)["auto"]["on"]),
                      ("gc_g_calendar", False))
            c.post_json("/api/gcal/google/calendar", {"id": CAL})
            run(c, preview(c, auto=True), auto=True)
            c.post_json("/api/gcal/google/disconnect", {})
            res.check("«Deconectează» уносит галочку с файлом связи", google(c)["auto"], None)
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- отмена ----------


def suite_undo(res: Result) -> None:
    """Отмена мутации снимает только нетронутые записи без детей и пустые новые фиши; события — снова
    в «De mutat» решением человека, автоперенос их не берёт."""
    g = stand([gev("n1", 3, "09:00", 30, "Lungu Petru 069111222 - dr Doi"),
               gev("n2", 3, "10:00", 30, "Rotaru Ana 079555111 Dr. Trei"),
               gev("n3", 3, "11:00", 30, "Ceban Maria - Dr. Patru"),
               gev("n4", 3, "12:00", 30, "Bejan Ana 068500500 dr Doi")])
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        put_license(d, 1, 30)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            seed(c)
            connect(res, s, c, g, "отмена")
            r = run(c, preview(c))
            key = _j(r)["data"]["batch"]["key"]
            res.check("пачка: четыре записи", _j(r)["data"]["batch"]["n"], 4)
            rot, ceb = appts(s, "Rotaru Ana")[0][0], appts(s, "Ceban Maria")[0][0]
            r = c.post_json(f"/api/schedule/appointments/{rot}/comment", {"comment": "vine cu mama"})
            res.check("запись Rotaru тронута комментарием", r.msg in ("ok_comment", "ok"), True)
            r = c.post_json(f"/api/schedule/desk/call/{ceb}", {"result": "ok"})
            res.ok("у записи Ceban — отметка звонка (ребёнок)", r.status == 200, r.msg)
            pid_bejan = sql(s, "SELECT id FROM patients WHERE name = 'Bejan Ana'")[0][0]
            write(s, "UPDATE patients SET notes = 'alergie' WHERE id = ?", pid_bejan)
            write(s, "INSERT INTO activity(patient_id, at, actor, kind, text) VALUES(?, ?, 'Director', 'edit', 'x')",
                  pid_bejan, datetime.now(TZ).isoformat())
            r = c.post_json("/api/gcal/moves/undo", {"key": key})
            u = _j(r)["data"]["undo"]
            res.check("отмена: снято две, осталось две", (r.status, r.msg, u["removed"], u["kept"]),
                      (200, "gc_a_undone", 2, 2))
            res.check("снята нетронутая запись и её пустая новая фиша; тронутая фиша осталась",
                      (appts(s, "Lungu Petru"), bool(sql(s, "SELECT 1 FROM patients WHERE name = 'Lungu Petru'")),
                       bool(sql(s, "SELECT 1 FROM patients WHERE name = 'Bejan Ana'")), appts(s, "Bejan Ana")),
                      ([], False, True, []))
            res.check("тронутые записи остались", (len(appts(s, "Rotaru Ana")), len(appts(s, "Ceban Maria"))), (1, 1))
            back = rows(listing(c))
            res.check("события снятых — снова в «De mutat», решением человека (текст вернёт опрос)",
                      sorted((v["title"], (v["auto"]["why"] or {}).get("code")) for v in back),
                      [("", "a_hand"), ("", "a_hand")])
            res.check("история: мутация отменена", listing(c)["automove"]["moves"][0]["undone"]["removed"], 2)
            r = c.post_json("/api/gcal/moves/undo", {"key": key})
            res.check("вторая отмена — «gc_a_undo_gone»", (r.status, r.msg), (409, "gc_a_undo_gone"))
            run(c, preview(c, auto=True), auto=True)
            c.post_json("/api/gcal/google/check", {})
            res.check("автоперенос снятых не берёт", (appts(s, "Lungu Petru"), appts(s, "Bejan Ana")), ([], []))
            res.check("опрос вернул текст снятых событий",
                      sorted(by_title(listing(c))), ["Bejan Ana 068500500 dr Doi", "Lungu Petru 069111222 - dr Doi"])
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- изменилось в Google ----------


def suite_changed(res: Result) -> None:
    """«Schimbate în Google»: журнал сам не меняется; «Mută și programarea» — правилом перетаскивания,
    метка «без SMS» остаётся; «Anulează programarea»; «Lasă cum e» переживает следующий опрос."""
    g = stand([gev("c1", 3, "09:00", 30, "Lungu Petru 069111222 - dr Doi"),
               gev("c2", 3, "10:00", 30, "Rotaru Ana 079555111 Dr. Trei"),
               gev("c3", 3, "11:00", 30, "Ceban Maria - Dr. Patru"),
               gev("c4", 3, "12:00", 30, "Bejan Ana 068500500 dr Doi")])
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_"))
    try:
        client = client_file(work)
        d = work / "data"
        d.mkdir()
        put_license(d, 1, 30)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            seed(c)
            connect(res, s, c, g, "изменилось")
            run(c, preview(c))
            start0 = appts(s, "Lungu Petru")[0][2]
            bejan = appts(s, "Bejan Ana")[0][0]
            r = c.post_json(f"/api/schedule/appointments/{bejan}/move", {"date": _day(3), "time": "13:00",
                                                                         "doctor": "d2"})
            res.ok("запись Bejan передвинули в DentPilot", r.msg in ("ok_move", "room_busy"), r.msg)
            ev_ = {e["id"]: e for e in g.events[CAL]}
            for uid in ("c1", "c4"):
                for k in ("start", "end"):
                    t = datetime.fromisoformat(ev_[uid][k]["dateTime"]) + timedelta(minutes=60)
                    ev_[uid][k]["dateTime"] = t.isoformat()
            ev_["c2"]["status"] = "cancelled"
            ev_["c3"]["status"] = "cancelled"
            c.post_json("/api/gcal/google/check", {})
            ch = {x["appt"]["patient"]: x for x in rows(listing(c, "schimbat"))}
            res.check("в «Schimbate» — четыре", sorted(ch), ["Bejan Ana", "Ceban Maria", "Lungu Petru", "Rotaru Ana"])
            res.check("кнопки: час сдвинут — «Mută și programarea»",
                      {k: v for k, v in ch["Lungu Petru"]["can"].items() if k in ("follow", "cancel_appt", "keep")},
                      {"follow": True, "cancel_appt": False, "keep": True})
            res.check("кнопки: отменено в Google — «Anulează programarea»",
                      (ch["Rotaru Ana"]["can"]["follow"], ch["Rotaru Ana"]["can"]["cancel_appt"]), (False, True))
            res.check("тронутая в DentPilot — только «Lasă cum e»",
                      (ch["Bejan Ana"]["auto"]["dp"], ch["Bejan Ana"]["can"]["follow"], ch["Bejan Ana"]["can"]["keep"]),
                      (True, False, True))
            res.check("журнал сам не изменился", appts(s, "Lungu Petru")[0][2], start0)
            r = c.post_json(f"/api/gcal/events/{ch['Lungu Petru']['id']}/follow", {})
            lungu = appts(s, "Lungu Petru")[0]
            want = (datetime.fromisoformat(ev_["c1"]["start"]["dateTime"])).astimezone(TZ).strftime("%H:%M")
            got = datetime.fromisoformat(lungu[2]).astimezone(TZ).strftime("%H:%M")
            res.check("«Mută și programarea»: запись на новом часе, метка «без SMS» осталась",
                      (r.msg, got, lungu[5]), ("gc_a_followed", want, 1))
            r = c.post_json(f"/api/schedule/appointments/{lungu[0]}/move", {"date": _day(3), "time": "15:00",
                                                                           "doctor": "d2"})
            res.check("…а перенос той же записи руками в журнале метку снимает, как раньше",
                      (r.msg, appts(s, "Lungu Petru")[0][5]), ("ok_move", 0))
            r = c.post_json(f"/api/gcal/events/{ch['Bejan Ana']['id']}/follow", {})
            res.check("тронутую в DentPilot за Google не двигаем", (r.status, r.msg), (409, "gc_a_touched"))
            r = c.post_json(f"/api/gcal/events/{ch['Rotaru Ana']['id']}/cancel-appt", {})
            res.check("«Anulează programarea»", (r.msg, [x[1] for x in appts(s, "Rotaru Ana")]),
                      ("gc_a_cancelled", ["cancelled"]))
            r = c.post_json(f"/api/gcal/events/{ch['Ceban Maria']['id']}/keep", {})
            res.check("«Lasă cum e»: запись цела", (r.msg, [x[1] for x in appts(s, "Ceban Maria")]),
                      ("gc_a_kept", ["confirmed"]))
            c.post_json("/api/gcal/google/check", {})
            left = sorted(x["appt"]["patient"] for x in rows(listing(c, "schimbat")))
            res.check("после опроса принятые не возвращаются в «Schimbate»", left, ["Bejan Ana"])
            r = c.post_json(f"/api/gcal/events/{ch['Ceban Maria']['id']}/keep", {})
            res.check("принятое второй раз — «nu s-a schimbat»", (r.status, r.msg), (409, "gc_a_nochange"))
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- права ----------


def suite_rights(res: Result) -> None:
    """Пачка и отмена в демо закрыты; файл у Basic — пачкой тоже (у всех тарифов)."""
    g = stand([])
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_"))
    try:
        client = client_file(work)
        d = work / "demo"
        d.mkdir()
        put_license(d, 1, 30)
        with Server(dir_=d, env=env(g, client, DENTART_DEMO="1")) as s:
            c = Client(s.url).login()
            for path, body in (("/api/gcal/batch/check", {}), ("/api/gcal/batch/run", {"token": "x"}),
                               ("/api/gcal/moves/undo", {"key": "x"})):
                res.check(f"демо: {path} — закрыт", c.post_json(path, body).status, 403)
        d = work / "basic"
        d.mkdir()
        put_license(d, 1, None)
        with Server(dir_=d, env=env(g, client)) as s:
            c = Client(s.url).login()
            seed(c)
            res.check("Basic: файл загружен", upload(c, cal([ev("f1", 3, "09:00", 30, "Lungu Petru 069111222 - dr Doi"),
                                                             ev("f2", 3, "10:00", 30, "Sandu Ion")])).msg,
                      "gc_loaded")
            data = listing(c)
            res.check("Basic: строки автопереноса нет, полоса пачки есть",
                      (data["google"]["auto"], data["automove"]["batch"]), (None, {"go": 1, "all": 2, "can": True}))
            pv = preview(c)
            res.check("Basic: SMS в предпросмотре не показываются", pv["sms"]["show"], False)
            r = run(c, pv)
            res.check("Basic: пачка из файла", (r.msg, [x[4] for x in appts(s, "Lungu Petru")]), ("gc_a_moved", ["d2"]))
            r = run(c, {"token": "x"}, auto=True)
            res.check("Basic: автоперенос не включить", (r.status, r.msg), (409, "gc_a_auto_no"))
    finally:
        g.close()
        _rmtree_settled(work)


# ---------- колонки событий после шагов миграции ----------

NEW_COLS = ("moved_how", "move_key", "move_pid", "appt_sig", "auto_why", "ack")


def _gcal_cols(con) -> list:
    """Сколько раз каждая новая колонка есть в gcal_events (ровно по разу — не задвоилась)."""
    have = [r[1] for r in con.execute("PRAGMA table_info(gcal_events)")]
    return [have.count(c) for c in NEW_COLS]


def _to_2231(con) -> None:
    """База как у 2.23.1: колонок переноса без человека ещё нет, данные вкладки — есть."""
    for c in NEW_COLS:
        con.execute(f"ALTER TABLE gcal_events DROP COLUMN {c}")
    con.commit()


def suite_columns(res: Result) -> None:
    """Колонки событий добавляются ПОСЛЕ шагов миграции (таблицу создаёт шаг 12): новая пустая база,
    база 2.23.1 с данными вкладки, повторный старт — и то же на зашифрованной картотеке."""
    from app.db import schema as appschema  # noqa: E402 — только список колонок
    res.check("список колонок — тот, что проверяет набор",
              [c.split()[0] for c in appschema.SQLITE_GCAL_COLS], list(NEW_COLS))
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_cols_"))
    try:
        dbfile = work / "dental.db"
        with Server(dir_=work) as s:
            c = Client(s.url).login()
            con = sqlite3.connect(str(dbfile))
            try:
                res.check("новая пустая база: колонки на месте, по одной", _gcal_cols(con), [1] * len(NEW_COLS))
            finally:
                con.close()
            res.check("данные вкладки: файл загружен", upload(c, cal([
                ev("k1", 3, "09:00", 30, "Lungu Petru 069111222 dr Doi"),
                ev("k2", 3, "10:00", 30, "Sandu Ion control")])).msg, "gc_loaded")
            rid = next(x["id"] for x in rows(listing(c)) if x["title"].startswith("Lungu"))
            r = c.post_json(f"/api/gcal/events/{rid}/move", {"date": _day(3), "time": "09:00", "doctor": "d2",
                                                              "service": "consult", "name": "Lungu Petru",
                                                              "phone": "069111222", "nophone": False})
            res.check("данные вкладки: событие перенесено", r.msg, "ok")
        con = sqlite3.connect(str(dbfile))
        try:
            _to_2231(con)
            res.check("база как у 2.23.1: новых колонок нет", _gcal_cols(con), [0] * len(NEW_COLS))
        finally:
            con.close()
        for tag in ("база 2.23.1 с данными", "повторный старт"):
            with Server(dir_=work) as s:
                c = Client(s.url).login()
                con = sqlite3.connect(str(dbfile))
                try:
                    res.check(f"{tag}: колонки на месте, по одной", _gcal_cols(con), [1] * len(NEW_COLS))
                    res.check(f"{tag}: перенесённое — с пустыми полями переноса", con.execute(
                        "SELECT state, moved_how, move_key, appt_sig, ack FROM gcal_events WHERE ext_key LIKE 'k1%'"
                    ).fetchall(), [("mutat", "", "", "", "")])
                finally:
                    con.close()
                res.check(f"{tag}: вкладка видит обе строки",
                          (len(rows(listing(c))), len(rows(listing(c, "mutat")))), (1, 1))
        _columns_crypt(res)
    finally:
        _rmtree_settled(work)


def _columns_crypt(res: Result) -> None:
    """Зашифрованная картотека: отказ «колонка уже есть» — класс sqlcipher3, не sqlite3."""
    from app.core import dbkey  # noqa: E402
    import sqlcipher3.dbapi2 as sqlcipher  # noqa: E402
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_gauto_colsx_"))
    try:
        key = dbkey.generate()
        if not dbkey.store(key, tmp):
            res.failed.append(("ключ не сохранился под DPAPI", "не Windows или DPAPI отказал"))
            return
        dbfile = tmp / "dental.db"

        def crypt():
            con = sqlcipher.connect(str(dbfile))
            con.execute(f"PRAGMA key = {dbkey.pragma_value(key)}")
            return con

        with Server(dir_=tmp):
            pass
        con = crypt()
        try:
            res.check("зашифрованная новая база: колонки на месте", _gcal_cols(con), [1] * len(NEW_COLS))
            _to_2231(con)
        finally:
            con.close()
        for tag in ("зашифрованная база 2.23.1", "зашифрованная, повторный старт"):
            with Server(dir_=tmp) as s:
                res.check(f"{tag}: вкладка отвечает", Client(s.url).login().get("/api/gcal").status, 200)
            con = crypt()
            try:
                res.check(f"{tag}: колонки на месте, по одной", _gcal_cols(con), [1] * len(NEW_COLS))
            finally:
                con.close()
    finally:
        _rmtree_settled(tmp)
