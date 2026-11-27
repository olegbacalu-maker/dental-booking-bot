"""Выбор существующей фиши в окне записи журнала: повторного пациента не вписывают заново и не
плодят двойников.

- `POST /api/schedule/appointments` с `pid` — визит выбранной фише по номеру (`book.book_visit`):
  имя и телефон тела не читаются, фиша не переписывается, новая не заводится; номер, которому
  верить нельзя (не число, нет такой, обезличена), — отказ `pick_gone` словами, а не фиша по имени;
  врач — как без `pid`, только в свой журнал.
- `POST /api/schedule/pick/recent` — недавние записанные для пустого поля, фиша экрана первой,
  врачу только свои; `POST /api/schedule/pick/match` — чья фиша совпала по номеру (правило записи
  по телефону) и по имени (любой порядок слов).
"""
import json
import sqlite3
from datetime import timedelta

from harness import Client, Result, Server, clinic_today, new_patient
import test_stock

NO_KEY = {"ADMIN_KEY": ""}


def _j(r) -> dict:
    return json.loads(r.body)


def _workday(ahead: int) -> str:
    d = clinic_today() + timedelta(days=ahead)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _book(c: Client, day: str, time: str, pid, doctor: str = "d2", **extra):
    return c.post_json("/api/schedule/appointments",
                       {"date": day, "time": time, "doctor": doctor, "service": "consult",
                        "name": extra.pop("name", "Alt Nume"), "phone": extra.pop("phone", "060000001"),
                        "nophone": False, "birth": "", "pid": pid, **extra})


def _count(s: Server, sql: str, *args) -> int:
    con = sqlite3.connect(str(s.dir / "dental.db"))
    try:
        return int(con.execute(sql, args).fetchone()[0])
    finally:
        con.close()


def suite_book(res: Result) -> None:
    """Запись по номеру фиши: визит ей, имя и телефон окна не читаются; отказы словами; права врача."""
    with Server(env=NO_KEY) as s:
        boss, ana, med = test_stock._team(s)
        ion = new_patient(boss, "Ion Popescu", "069123456")
        day = _workday(3)
        before = _count(s, "SELECT count(*) FROM patients")
        r = _book(ana, day, "10:00", ion, name="Ion P.", phone="060999999")
        res.check("регистратура: визит в выбранную фишу — удача", (r.status, r.msg), (200, "ok"))
        res.check("новая фиша не заведена", _count(s, "SELECT count(*) FROM patients"), before)
        res.check("визит лёг выбранной фише",
                  _count(s, "SELECT count(*) FROM appointments WHERE patient_id = ?", ion), 1)
        res.check("имя и телефон окна фишу не переписали",
                  [_count(s, f"SELECT count(*) FROM patients WHERE id = ? AND {w}", ion)
                   for w in ("name = 'Ion Popescu'", "phone = '069123456'")], [1, 1])
        r = _book(ana, day, "10:00", ion)
        res.check("тот же час у той же фиши — `dup`, как у записи по телефону", (r.status, r.msg), (409, "dup"))

        for label, pid in (("нет такой фиши", 999999), ("номер строкой", str(ion)), ("не номер, а да/нет", True)):
            n = _count(s, "SELECT count(*) FROM patients")
            r = _book(ana, day, "11:00", pid)
            body = _j(r)
            res.check(f"{label}: отказ `pick_gone` словами, новая фиша не заведена",
                      (r.status, body.get("code"), bool(body.get("text")), _count(s, "SELECT count(*) FROM patients")),
                      (409, "pick_gone", True, n))

        anon = new_patient(boss, "Pacient Sters", "069777111")
        con = sqlite3.connect(str(s.dir / "dental.db"))
        try:
            con.execute("UPDATE patients SET session_key = ? WHERE id = ?", (f"anon:{anon}", anon))
            con.commit()
        finally:
            con.close()
        r = _book(ana, day, "12:00", anon)
        res.check("обезличенная фиша — `pick_gone`, визит ей не поставлен",
                  (r.msg, _count(s, "SELECT count(*) FROM appointments WHERE patient_id = ?", anon)),
                  ("pick_gone", 0))

        r = _book(med, day, "13:00", ion, doctor="d2")
        res.check("врач: в чужой журнал и с номером фиши — отказ", r.status, 403)
        r = _book(med, day, "13:00", ion, doctor="d3")
        res.check("врач: в свой журнал — удача", (r.status, r.msg), (200, "ok"))

        r = _book(ana, day, "15:00", None, name="Vasile Nou", phone="060123987")
        res.check("без `pid` — запись по имени и телефону, как была",
                  (r.msg, _count(s, "SELECT count(*) FROM patients WHERE name = 'Vasile Nou'")), ("ok", 1))


def suite_hints(res: Result) -> None:
    """«Recenți» и совпадения: порядок, фиша экрана, журнал врача, номер в любом виде, семейный номер."""
    with Server(env=NO_KEY) as s:
        boss, ana, med = test_stock._team(s)
        day = _workday(3)
        ion = new_patient(boss, "Ion Popescu", "+373 69 123 456")
        irina = new_patient(boss, "Irina Ceban", "068555444")
        # семейный номер: вторая фиша получает его правкой (новая фиша с тем же номером открыла бы первую)
        sofia = new_patient(boss, "Sofia Ceban", "060222333")
        boss.post_json(f"/api/patients/{sofia}/profile", {"name": "Sofia Ceban", "phone": "068 555 444"})
        ana_p = new_patient(boss, "Ana Rusu", "078111222")
        boss.post_json(f"/api/patients/{ion}/profile", {"name": "Ion Popescu", "phone": "+373 69 123 456",
                                                       "file_no": "D-142", "birth_date": "1985-03-12"})
        for pid, t, dk in ((ion, "09:00", "d2"), (irina, "10:00", "d3"), (ana_p, "11:00", "d2"), (ion, "12:00", "d2")):
            r = _book(boss, day, t, pid, doctor=dk)
            if r.msg != "ok":
                raise AssertionError(f"засев: {r.status} {r.body[:200]}")

        rec = _j(ana.post_json("/api/schedule/pick/recent", {}))["data"]["rows"]
        res.check("«Recenți»: последние записанные, новые первыми, без повторов",
                  [x["id"] for x in rec], [ion, ana_p, irina])
        res.check("строка: имя, телефон, год, № дела, последний визит (будущий не в счёт)",
                  {k: rec[0][k] for k in ("name", "phone", "year", "file_no", "last")},
                  {"name": "Ion Popescu", "phone": "+373 69 123 456", "year": "1985", "file_no": "D-142", "last": ""})
        rec = _j(ana.post_json("/api/schedule/pick/recent", {"here": sofia}))["data"]["rows"]
        res.check("фиша экрана — первой, остальные следом", [x["id"] for x in rec], [sofia, ion, ana_p, irina])
        rec = _j(med.post_json("/api/schedule/pick/recent", {}))["data"]["rows"]
        res.check("врачу — только записанные к нему", [x["id"] for x in rec], [irina])
        res.check("без входа — 401", Client(s.url).post_json("/api/schedule/pick/recent", {}).status, 401)

        def match(phone: str, name: str = "") -> tuple:
            d = _j(ana.post_json("/api/schedule/pick/match", {"phone": phone, "name": name}))["data"]
            return (d["phone"] and d["phone"]["id"], [x["id"] for x in d["name"]])

        res.check("номер в любом виде — та фиша, куда запись положит визит по телефону",
                  [match(p)[0] for p in ("069123456", "+37369123456", "0037369123456", "69 12 34 56")],
                  [ion, ion, ion, ion])
        res.check("семейный номер (две фиши) — не подсказан: запись по телефону его не выберет", match("068555444")[0], None)
        res.check("имя в любом порядке, регистр и диакритика — не помеха",
                  [match("", n)[1] for n in ("popescu ion", "ION  POPESCU", "Ion Popescu")], [[ion], [ion], [ion]])
        res.check("часть имени — не то же имя", match("", "Popescu")[1], [])
        res.check("однофамильцы — каждый своим именем", match("", "Ceban Sofia")[1], [sofia])

        rows = _j(ana.get("/api/patients?q=popescu"))["data"]["rows"]
        res.check("строка списка несёт год и № дела для окна записи",
                  [(x["year"], x["file_no"]) for x in rows], [("1985", "D-142")])
