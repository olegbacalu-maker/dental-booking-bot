"""Импорт пациентов из .xlsx / .csv (`/api/pimport/*`) и четыре починки рядом.
Из сети и в режиме чтения отказывают общие сторожа; здесь — что маршруты
импорта в их списки попали."""
from __future__ import annotations

import datetime as dt
import io
import json
import pathlib
import shutil
import sys
import tempfile
import urllib.parse
import zipfile

from harness import (BOT, FIXTURES, Client, Result, Server, _rmtree_settled, add_appt,
                     clinic_today, new_patient, shell_model)
import pimport_samples as S

sys.path.insert(0, str(BOT))

FIX = FIXTURES / "pimport"
NO_KEY = {"ADMIN_KEY": ""}
D = dt.date


PAGE = "/admin/patients/import"


def _j(r) -> dict:
    return json.loads(r.body)


def _send(c: Client, what: str, blob: bytes, name: str = "pacienti.xlsx", opts: dict | None = None,
          **q):
    query = {"name": name, **({"opts": json.dumps(opts)} if opts is not None else {}),
             **{k: str(v) for k, v in q.items()}}
    return c._do(f"/api/pimport/{what}?" + urllib.parse.urlencode(query), blob,
                 {"Content-Type": "application/octet-stream"})


def _check(c: Client, blob: bytes, name: str = "pacienti.xlsx", opts: dict | None = None) -> dict:
    r = _send(c, "check", blob, name, opts)
    if r.status != 200:
        raise AssertionError(f"проверка не прошла: {r.status} {r.body[:200]}")
    return _j(r)["data"]


def _run_all(c: Client, blob: bytes, name: str = "pacienti.xlsx", opts: dict | None = None) -> dict:
    """Весь импорт так, как его ведёт экран: проверка, затем порции."""
    chk = _check(c, blob, name, opts)
    iid, last = 0, {}
    for part in range(max(chk["parts"], 1)):
        r = _send(c, "run", blob, name, opts, token=chk["token"], part=part, **{"import": iid})
        if r.status != 200:
            raise AssertionError(f"порция {part}: {r.status} {r.body[:200]}")
        last = _j(r)
        iid = last["data"]["import"]
    return {"check": chk, "last": last, "id": iid, "total": last["data"]["total"]}


def _total(c: Client) -> int:
    return int(_j(c.get("/api/patients?per=10"))["data"]["total"])


def _find(c: Client, q: str) -> list:
    return _j(c.get("/api/patients?q=" + urllib.parse.quote(q)))["data"]["rows"]


def _card(c: Client, pid: int) -> dict:
    return _j(c.get(f"/api/patients/{pid}"))["data"]


def _lines(c: Client, pid: int) -> list[str]:
    return [a["text"] for a in _card(c, pid)["activity"]["items"]]


def _sheet_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read("xl/worksheets/sheet1.xml").decode("utf-8")


def suite_read(res: Result) -> None:
    """Читатель таблиц: что прочитано из книги и CSV и на что он отказывает."""
    from app.core import tabfile
    from app.core import xlsx as our_xlsx
    from app.modules.patients import pimport as pi

    res.ok("исходники нашлись", (BOT / "app" / "core" / "tabfile.py").exists()
           and (FIX / "biblioteca.xlsx").exists())

    def recs_of(blob, name="a.xlsx", sheet=0, doctors=()):
        t = tabfile.read(blob, name)
        r = pi.resolve(t, {**pi.parse_opts(""), "sheet": sheet})
        return t, r, pi.build(t, r, list(doctors))[0]

    book = S.excel_book([("Pacienți", S.CLINIC, ["A1:F1"]), ("Ascuns", [["Nume"], ["Nimeni"]], []),
                         ("Русский", S.RU_SHEET, ["A2:A4"])], hidden=("Ascuns",))
    t, r, recs = recs_of(book)
    res.check("скрытый лист не читается, видимые — оба", [s.name for s in t.sheets],
              ["Pacienți", "Русский"])
    res.check("шапка найдена в третьей строке", r["header"], 3)
    res.check("колонки узнаны: фамилия, имя, телефон, дата, IDNP, адрес, e-mail, заметки",
              r["cols"], {1: "last", 2: "first", 3: "phone", 4: "birth", 5: "idnp", 6: "address",
                          7: "email", 8: "notes"})
    by = {x["line"]: x for x in recs}
    res.check("пустая строка и «Total: 8» записью не стали", sorted(by), [4, 5, 6, 8, 9, 10, 11, 12])
    res.check("телефон числом: ноль возвращён, с пометкой",
              (by[4]["phone"], ("tel_zero", "") in by[4]["notes_w"]), ("069555101", True))
    res.check("дата стилем Excel — дата", by[4]["birth_date"], "1985-03-14")
    res.check("IDNP числом с плавающей точкой — все 13 цифр", by[4]["idnp"], "2001234567893")
    res.check("общие строки «богатым текстом» склеены", by[4]["address"], "Chișinău, str. Test 1")
    res.check("ЗАГЛАВНЫЕ — к обычному виду, дефис цел", by[5]["name"], "Bălan Maria-Elena")
    res.check("«+373 (79) 555-102» хранится как 079555102", by[5]["phone"], "079555102")
    res.check("свой формат даты (dd/mm/yyyy;@) — дата", by[5]["birth_date"], "1990-12-01")
    res.check("два номера в ячейке: первый в телефон, второй в заметки",
              (by[6]["phone"], by[6]["notes"]), ("069555103", "Tel. 2: 022555104; fratele lui Ion"))
    res.check("дата текстом, день первым", (by[6]["birth_date"], by[8]["birth_date"]),
              ("1978-07-14", "2003-02-01"))
    res.check("IDNP из 12 цифр: ноль спереди, с пометкой",
              (by[8]["idnp"], ("idnp_zero", "") in by[8]["notes_w"]), ("0200123456789", True))
    res.check("строка с одним телефоном — «нет имени», а не пропуск", by[10]["err"], "no_name")
    res.check("31.02, «12» и короткий IDNP: фиша без этих полей, три пометки",
              (by[11]["birth_date"], by[11]["phone"], by[11]["idnp"],
               sorted(c for c, _a in by[11]["notes_w"])),
              ("", "", "", ["bd_bad", "idnp_len", "tel_bad"]))
    res.check("непрочитанный телефон остался в заметках", by[11]["notes"], "Telefon în fișier: 12")
    res.check("только год — год без даты", (by[12]["birth_date"], by[12]["birth_year"]), ("", 1975))

    _t, r2, ru = recs_of(book, sheet=1, doctors=["Dr. Activ Doi"])
    res.check("русская шапка: врач, ФИО, телефон, дата, заметки", r2["cols"],
              {0: "doctor", 1: "full", 2: "phone", 3: "birth", 4: "notes"})
    res.check("врач из объединённой ячейки размножен вниз и узнан",
              [x["primary_doctor"] for x in ru], ["Dr. Activ Doi"] * 3)
    res.check("«5 марта 1969 г.» и иностранный номер", (ru[0]["birth_date"], ru[0]["phone"]),
              ("1969-03-05", "89115550107"))
    res.check("строчные — к обычному виду; второй номер в заметки",
              (ru[1]["name"], ru[1]["phone"], ru[1]["notes"]),
              ("Сидорова Анна", "069555108", "Tel. 2: 079555109; VIP"))
    res.check("дата числом без формата — дата с пометкой",
              (ru[2]["birth_date"], ("bd_serial", "") in ru[2]["notes_w"]), ("1986-03-14", True))

    b1904 = S.excel_book([("S", [["Nume", "Data nașterii"], ["Test Unu", D(1985, 3, 14)]], [])],
                         date1904=True)
    res.check("книга с отсчётом от 1904 года — та же дата", recs_of(b1904)[2][0]["birth_date"],
              "1985-03-14")

    # книга «как из библиотеки»: приставка x:, ячейки str и d (ISO с временем и Z)
    lib = (FIX / "biblioteca.xlsx").read_bytes()
    t, r, recs = recs_of(lib)
    res.check("шапка по ключевому слову: скобки отброшены, два телефона, ID пропущен",
              r["cols"], {1: "full", 2: "birth", 3: "appt", 4: "idnp", 5: "phone", 6: "phone2"})
    res.check("20 строк, дата из ISO-текста без сдвига дня",
              (len(recs), recs[0]["birth_date"], recs[11]["birth_date"]),
              (20, "1950-01-01", "1961-12-12"))
    res.check("два столбца с одним номером — один телефон, заметки без «Tel. 2»",
              (recs[0]["phone"], recs[0]["notes"]), ("069560000", "Programare în fișier: 01.01.2027"))
    res.check("без телефона — пусто, не ошибка", (recs[4]["phone"], recs[4]["err"]), ("", ""))

    ours = our_xlsx.book(["Nume", "Telefon", "E-mail", "Data nașterii", "Vârstă", "Gen", "Medic",
                          "Nr. dosar", "Canal", "Status", "Vizite", "Sold (MDL)"],
                         [["Popescu Ion", "069555101", "", D(1985, 3, 14), 41, "M",
                           "Dr. Activ Doi", "17", "manual", "Activ", 3, 0]])
    _t, r, recs = recs_of(ours, doctors=["Dr. Activ Doi"])
    res.check("книга самой программы: поля узнаны, счётные колонки пропущены", r["cols"],
              {0: "full", 1: "phone", 2: "email", 3: "birth", 5: "gender", 6: "doctor", 7: "file_no"})
    res.check("и читается целиком",
              (recs[0]["name"], recs[0]["phone"], recs[0]["birth_date"], recs[0]["gender"],
               recs[0]["primary_doctor"], recs[0]["file_no"]),
              ("Popescu Ion", "069555101", "1985-03-14", "m", "Dr. Activ Doi", "17"))

    for fname, enc, delim, first in (("ru-utf8-bom.csv", "utf-8", ";", "Иванов Пётр"),
                                     ("ru-cp1251.csv", "cp1251", ";", "Иванов Пётр"),
                                     ("ro-utf8-virgula.csv", "utf-8", ",", "Țurcanu Ștefan"),
                                     ("ro-cp1250.csv", "cp1250", ";", "Ţurcanu Ştefan")):
        t, _r, recs = recs_of((FIX / fname).read_bytes(), fname)
        res.check(f"{fname}: кодировка, разделитель, первое имя",
                  (t.kind, t.enc, t.delim, recs[0]["name"]), ("csv", enc, delim, first))
    _t, _r, recs = recs_of((FIX / "ru-utf8-bom.csv").read_bytes(), "a.csv")
    res.check("кавычки: разделитель внутри имени не режет", recs[1]["name"], "Сидорова; Анна")
    _t, _r, recs = recs_of((FIX / "ro-utf8-virgula.csv").read_bytes(), "a.csv")
    res.check("запятая в кавычках — часть имени", recs[1]["name"], "Bălan, jr. Ion")
    t = tabfile.read((FIX / "ru-cp1251.csv").read_bytes(), "a.csv", enc="cp1250", delim=",")
    res.check("кодировка и разделитель руками берут верх над угадыванием", (t.enc, t.delim),
              ("cp1250", ","))
    t = tabfile.read(S.CSV_RU.replace(";", "\t").encode("utf-16"), "a.csv")
    res.check("Excel «Text Unicode»: UTF-16 и табуляция", (t.enc, t.delim, len(t.sheets[0].rows)),
              ("utf-16", "\t", 3))

    def refuse(blob, name="a.xlsx"):
        try:
            tabfile.read(blob, name)
        except tabfile.Refuse as e:
            return e.code
        return "принят"

    def zipped(name, data):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(name, data)
        return buf.getvalue()

    res.check("старый .xls (и книга под паролем) — просьба пересохранить",
              refuse(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600), "old_xls")
    res.check("текст под именем .xls — тот же отказ", refuse(b"Nume;Telefon\nA;1\n", "a.xls"), "old_xls")
    res.check("PDF — не таблица", refuse(b"%PDF-1.7 ..."), "not_table")
    res.check(".docx (zip без книги) — не таблица", refuse(zipped("word/document.xml", "<w/>")),
              "not_table")
    res.check("zip-бомба отбита по заголовкам, до распаковки",
              refuse(zipped("xl/workbook.xml", b"0" * (tabfile.MAX_UNPACKED + 1))), "too_big")
    res.check("файл больше потолка", refuse(b"a;b\n" * (tabfile.MAX_FILE // 4 + 1), "a.csv"), "too_big")
    evil = S.excel_book([("S", [["Nume"], ["Test"]], [])])
    with zipfile.ZipFile(io.BytesIO(evil)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["xl/workbook.xml"] = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
                                + parts["xl/workbook.xml"].split(b"?>", 1)[1])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in parts.items():
            z.writestr(n, d)
    res.check("XML с DOCTYPE не разбирается", refuse(buf.getvalue()), "bad_xml")
    res.check("строк больше потолка",
              refuse(("Nume;Telefon\n" + "Test Om;069555000\n" * (tabfile.MAX_ROWS + 30)).encode(),
                     "a.csv"), "too_many_rows")
    res.check("пустой файл", refuse(b"  \n", "a.csv"), "empty")

    g = pi.guess_columns
    res.check("одиночное «Nume» — имя целиком", g(["Nr.", "Nume", "Tel."]), {1: "full", 2: "phone"})
    res.check("«Nume» рядом с «Prenume» — фамилия", g(["Nume", "Prenume"]), {0: "last", 1: "first"})
    res.check("шапка с двоеточием, регистром и старой диакритикой",
              g(["PACIENT:", "DATA NAŞTERII", "Nr. de telefon", "Cod personal (IDNP)"]),
              {0: "full", 1: "birth", 2: "phone", 3: "idnp"})
    res.check("выбор без имени не готов; с именем — готов",
              (pi.ready({"cols": {0: "phone"}}), pi.ready({"cols": {0: "first"}})), (False, True))
    res.check("кривой выбор не разбирается",
              [pi.parse_opts(x) for x in ('{"cols": {"1": "parola"}}', '{"sheet": -1}', "[1]", "{")],
              [None] * 4)
    ph = pi.phones
    res.check("номер в одном виде: пробелы, дефисы, +373, 00373, 373, без нуля",
              [ph([x])[0] for x in ("069 555 101", "069-55-51-01", "+373 69 555 101",
                                    "0037369555101", "37369555101", 69555101)],
              [["069555101"]] * 6)
    res.check("два столбца с одним номером — один; с разными — оба",
              (ph(["+37369555101", "069555101"])[0], ph(["069555101", "022555104"])[0]),
              (["069555101"], ["069555101", "022555104"]))
    res.check("иностранный остаётся как есть, с плюсом", ph(["+7 911 555-01-07"])[0], ["+79115550107"])
    today = dt.date.today()
    pd = pi.parse_date
    res.check("двузначный год: больше текущего — прошлый век",
              (pd(f"14-07-{(today.year + 1) % 100:02d}")[0].year, pd("14-07-05")[0].year),
              (1900 + (today.year + 1) % 100, 2005))
    res.check("ISO со временем и Z — тот же день", pd("1950-01-01T00:00:00.000Z")[0], D(1950, 1, 1))
    res.check("«5 mar 1969»", pd("5 mar 1969")[0], D(1969, 3, 5))
    rec = pi._record(2, {"full": [("", "Test Om")],
                         "birth": [("", (today + dt.timedelta(days=1)).isoformat())],
                         "idnp": [("", "2001234567890")],
                         "notes": [("Obs", "x" * 400), ("Alt", "y" * 400)]}, {})
    res.check("будущая дата — пусто с пометкой; IDNP с неверной контрольной — записан и помечен; "
              "длинные заметки обрезаны",
              (rec["birth_date"], rec["idnp"], len(rec["notes"]), sorted(c for c, _a in rec["notes_w"])),
              ("", "2001234567890", 500, ["bd_bad", "idnp_check", "notes_cut"]))
    res.ok("несколько колонок в заметки — с названием колонки", rec["notes"].startswith("Obs: xxx"))

    def R(line, name, phone="", birth="", idnp=""):
        return {"line": line, "name": name, "phone": phone, "birth_date": birth, "idnp": idnp,
                "birth_year": None, "notes_w": [], "err": ""}

    base = [{"id": 1, "name": "Popescu Ion", "phone": "+373 69 555 101", "birth_date": "1985-03-14",
             "idnp": "2001234567893", "archived": 0, "import_id": None},
            {"id": 2, "name": "Rusu Ana", "phone": None, "birth_date": None, "idnp": None,
             "archived": 1, "import_id": None, "address": ""}]
    rs = [R(2, "Altcineva Complet", "079555199", "", "2001234567893"),
          R(3, "ion POPESCU", "069555101"),
          R(4, "Popescu Ion", "", "1985-03-14"),
          R(5, "Popescu Maria", "069555101"),
          R(6, "Rusu Ana"),
          R(7, "Rusu Ana", "069555120"),
          R(8, "Nou Unu", "069555121", "1990-01-01"),
          R(9, "Unu Nou", "37369555121"),
          R(10, "Nou Unu", "", "1990-01-01"),
          R(11, "Nou Doi"), R(12, "Doi Nou")]
    pi.analyse(rs, base, [])
    acts = {x["line"]: (x["act"], x["reason"][:22]) for x in rs}
    res.check("IDNP совпал — тот же человек", acts[2], ("exists", "există deja (același I"))
    res.check("телефон в другом виде и имя в другом порядке — тот же", acts[3][0], "exists")
    res.check("имя и дата рождения — «posibil», можно снять пропуск",
              (acts[4][0], rs[2]["forceable"]), ("exists", True))
    res.check("телефон тот же, имя другое — семейный номер: новая фиша с пометкой",
              (acts[5][0], rs[3]["notes_w"]), ("new", [("family", "Popescu Ion")]))
    res.check("одно имя при пустых прочих данных с обеих сторон — тот же; архивный помечен",
              (acts[6][0], rs[4]["notes_w"]), ("exists", [("archived", "")]))
    res.check("одно имя, но у строки есть телефон — однофамилец, заводится", acts[7][0], "new")
    res.check("дубли внутри файла по трём признакам",
              (acts[8][0], acts[9], acts[10], acts[11][0], acts[12]),
              ("new", ("dup", "dublu al rândului 8 (a"), ("dup", "posibil dublu al rându"), "new",
               ("dup", "dublu al rândului 11 (")))
    rs2 = [R(4, "Popescu Ion", "", "1985-03-14"), R(5, "Popescu Ion", "069555101", "1985-03-14")]
    pi.analyse(rs2, base, [4, 5])
    res.check("снятый пропуск «posibil» заводит фишу; совпавшую до последнего признака — нет",
              [x["act"] for x in rs2], ["new", "exists"])


def suite_fixes(res: Result) -> None:
    """Четыре починки: номер в одном виде, дата рождения «Pacient nou»,
    IDNP без отказа по контрольной цифре, строка «fișă creată»."""
    from app import db
    res.check("номер для сравнения: шесть записей одного номера",
              {db.phone_key(x) for x in ("069555201", "+373 69 555 201", "0037369555201",
                                         "37369555201", "69555201", "373069555201")}, {"069555201"})
    res.check("чужой номер и пустое — как есть", (db.phone_key("+7 911 555 01 07"), db.phone_key(None)),
              ("79115550107", ""))
    res.check("ключ фиши собирается из того же вида",
              db.manual_key("37369555201"), db.manual_key("069555201"))
    day = (clinic_today() + dt.timedelta(days=4)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Tel Unu", "069555201")
        r = c.post_json("/api/patients", {"name": "Tel Unu", "phone": "+373 69 555 201"})
        res.check("«Pacient nou» с +373 открывает ту же фишу", (r.msg, _j(r)["data"]["id"]),
                  ("dup_pat", pid))
        res.check("запись из журнала с +373 ложится в ту же фишу",
                  (add_appt(c, day, "10:00", "Tel Unu", "+37369555201").msg, _total(c)), ("ok", 1))
        res.check("привязка SMS находит фишу по номеру в другом виде",
                  (c.post_json(f"/api/patients/{pid}/sms-off", {"off": True}).status,
                   _j(c.post_json("/api/schedule/sms-of", {"phone": "0037369555201"}))["data"]["sms"]),
                  (200, False))
        old = new_patient(c, "Tel Vechi", "+373 69 555 202")
        r = c.post_json("/api/patients", {"name": "Tel Vechi", "phone": "069555202"})
        res.check("номер, записанный с +373, находится по 069; хранимое не переписано",
                  (r.msg, _j(r)["data"]["id"], _card(c, old)["profile"]["phone"]),
                  ("dup_pat", old, "+373 69 555 202"))

        before = _total(c)
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        for bad in (tomorrow, "1800-01-01", "1990-02-31", "ieri"):
            r = c.post_json("/api/patients", {"name": "Data Rea", "phone": "", "birth_date": bad})
            res.check(f"«Pacient nou», дата {bad}: отказ bad_bd с полем",
                      (r.status, r.msg, _j(r).get("field")), (422, "bad_bd", "birth_date"))
        res.check("после отказов фиша не заведена", _total(c), before)
        ok = new_patient(c, "Data Buna", "", birth_date="1990-02-28")
        res.check("верная дата проходит, год посчитан",
                  (_card(c, ok)["profile"]["birth_date"], _find(c, "Data Buna")[0]["age"] is not None),
                  ("1990-02-28", True))

        r = c.post_json(f"/api/patients/{ok}/profile", {"name": "Data Buna", "idnp": "2001234567890"})
        res.check("IDNP с неверной контрольной цифрой фиша по-прежнему принимает", r.msg, "ok_card")

        res.check("летопись «Pacient nou»: одна строка «Fișă creată», без «actualizată»",
                  _lines(c, old), ["Fișă creată"])
        add_appt(c, day, "11:00", "Din Registru", "069555203")
        jr = _find(c, "Din Registru")[0]["id"]
        add_appt(c, day, "12:00", "Din Registru", "069555203")
        lines = _lines(c, jr)
        res.check("запись из журнала: строка «creată la programare» одна, и после второй записи",
                  [x for x in lines if x.startswith("Fișă creată")],
                  ["Fișă creată la programarea din registru"])
        res.check("у фиши, заведённой до этой записи, второй строки «creată» нет",
                  [x for x in _lines(c, pid) if x.startswith("Fișă creată")], ["Fișă creată"])


def suite_import(res: Result) -> None:
    """Проверка, порции, повтор, «+373», семейный номер, дополнение пустых
    полей, отпечаток, обрыв между порциями, круг с выгрузкой, отчёт, отмена."""
    lib = (FIX / "biblioteca.xlsx").read_bytes()
    with Server() as s:
        c = Client(s.url).login()
        home = _j(c.get("/api/pimport"))["data"]
        res.check("экран: импортов нет, потолки и порция, подсказки сети нет",
                  (home["imports"], home["limits"], home["remote"]),
                  ([], {"bytes": 10 * 1024 * 1024, "rows": 20000, "batch": 200}, None))
        res.ok("список полей для выбора колонки начинается с «Nu importa»",
               home["fields"][0] == {"id": "", "label": "Nu importa"} and len(home["fields"]) == 17)
        res.check("вход по ключу сервера: кнопка «Importă» в списке пациентов есть",
                  _j(c.get("/api/patients"))["data"]["can_import"], True)
        m = c.get("/api/pimport/model.xlsx")
        res.ok("файл-модель — книга с шапкой, которую импорт узнаёт сам",
               m.status == 200 and m.raw[:2] == b"PK" and "Nume și prenume" in _sheet_text(m.raw))
        r = _send(c, "check", m.raw, "model.xlsx")
        res.check("пустая модель: колонки узнаны, записей ноль",
                  (r.status, _j(r)["data"]["ready"], _j(r)["data"]["counts"]["rows"]), (200, True, 0))
        res.check("импорт пустого файла — отказ",
                  _send(c, "run", m.raw, "model.xlsx", token=_j(r)["data"]["token"]).msg, "pi_empty")

        res.check(".xls — 422 словами про «salvați ca .xlsx»",
                  (lambda r: (r.status, r.msg, ".xlsx" in _j(r)["text"]))(
                      _send(c, "check", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, "vechi.xls")),
                  (422, "pi_old_xls", True))
        res.check("больше 10 МБ — 413", _send(c, "check", b"a;b\n" * 2700000, "mare.csv").status, 413)
        res.check("кривой выбор колонок — 422", _send(c, "check", lib, "a.xlsx",
                                                     {"cols": {"1": "parola"}}).msg, "pi_opts")
        res.check("лист, которого нет, — 422", _send(c, "check", lib, "a.xlsx", {"sheet": 3}).msg,
                  "pi_opts")

        hand = new_patient(c, "Testescu0 Ana", "+373 69 560 000")
        chk = _check(c, lib, "biblioteca.xlsx")
        res.check("файл: вид, листы, шапка, предпросмотр",
                  (chk["file"]["kind"], chk["file"]["sheets"], chk["opts"]["header"],
                   len(chk["preview"]), chk["preview"][0]["cells"][1:3]),
                  ("xlsx", [{"name": "Pacienți", "rows": 21}], 1, 8, ["Testescu0 Ana", "01.01.1950"]))
        res.check("колонки: буква, название, угаданное поле",
                  [(x["letter"], x["title"], x["field"]) for x in chk["columns"]][:2] + [chk["columns"][4]],
                  [("A", "ID", ""), ("B", "Nume și prenume", "full"),
                   {"index": 4, "letter": "E", "title": "IDNP (demo)", "field": "idnp"}])
        cnt = chk["counts"]
        res.check("счётчики: 20 записей, 19 новых, один уже есть (заведён руками с +373)",
                  (cnt["rows"], cnt["create"], cnt["exists"], cnt["dup"], cnt["bad"], chk["parts"]),
                  (20, 19, 1, 0, 0, 1))
        ex = next(g for g in chk["groups"] if g["id"] == "exists")["rows"][0]
        res.check("строка «există deja»: номер строки файла, причина словами, кто совпал",
                  (ex["line"], ex["reason"], ex["match"]),
                  (2, "există deja (același telefon și nume): Testescu0 Ana",
                   {"id": hand, "name": "Testescu0 Ana"}))
        res.ok("IDNP с неверной контрольной цифрой — в «Cu observații», а не в отказе",
               any("cifra de control" in n for g in chk["groups"] if g["id"] == "noted"
                   for row in g["rows"] for n in row["notes"]))
        res.check("проверка ничего не записала", (_total(c), _j(c.get("/api/pimport"))["data"]["imports"]),
                  (1, []))

        res.check("без отпечатка — 409", _send(c, "run", lib, "biblioteca.xlsx").msg, "pi_stale")
        res.check("другой выбор колонок с прежним отпечатком — 409",
                  _send(c, "run", lib, "biblioteca.xlsx", {"cols": {"1": "full"}},
                        token=chk["token"]).msg, "pi_stale")
        res.check("другой файл с прежним отпечатком — 409",
                  _send(c, "run", S.library_book(S.LIB_HEADER, S.lib_rows(3)), "biblioteca.xlsx",
                        token=chk["token"]).msg, "pi_stale")
        res.check("отказы ничего не записали", _total(c), 1)

        run = _run_all(c, lib, "biblioteca.xlsx")
        res.check("импорт: 19 новых, одна пропущена, ответ «Import finalizat»",
                  (run["last"]["code"], run["total"]["created"], run["total"]["skipped"], _total(c)),
                  ("pi_done", 19, 1, 20))
        p2 = _find(c, "Testescu1 Ana")[0]["id"]
        prof = _card(c, p2)["profile"]
        res.check("фиша из файла: телефон 069…, дата, IDNP, запись в заметках",
                  (prof["phone"], prof["birth_date"], prof["idnp"], prof["notes"]),
                  ("069560001", "1951-02-02", "9990000000001", "Programare în fișier: 02.01.2027"))
        res.check("летопись фиши: одна строка — откуда человек",
                  _lines(c, p2), ["Fișă creată prin import din fișier „biblioteca.xlsx”"])
        imp = _j(c.get("/api/pimport"))["data"]["imports"]
        res.check("запись об импорте: файл, счётчики, можно отменить",
                  [(x["file"], x["rows"], x["created"], x["skipped"], x["undone"], x["can_undo"])
                   for x in imp], [("biblioteca.xlsx", 20, 19, 1, False, True)])
        res.ok("лента клиники: одна строка на весь импорт",
               "Import pacienți: 19 fișe noi, 1 omise („biblioteca.xlsx”)" in c.get("/api/stats").body,
               "строки импорта в ленте нет")

        again = _run_all(c, lib, "biblioteca.xlsx")
        res.check("тот же файл ещё раз — ноль новых (и безтелефонные не задвоились)",
                  (again["check"]["counts"]["create"], again["total"]["created"], _total(c)), (0, 0, 20))
        res.check("пустой повтор в списке импортов не остаётся",
                  len(_j(c.get("/api/pimport"))["data"]["imports"]), 1)
        plus = S.library_book(["Nume și prenume", "Telefon"],
                              [[r[1], r[5]] for r in S.lib_rows(20) if r[5]])
        again = _run_all(c, plus, "cu-plus.xlsx")
        res.check("те же люди с номерами +373… — ноль новых",
                  (again["check"]["counts"]["rows"], again["total"]["created"], _total(c)), (16, 0, 20))

        fam = S.library_book(["Nume", "Telefon", "Adresă", "IDNP"],
                             [["Testescu1 Copil", "069560001", "str. Test 5", None],
                              ["Testescu1 Ana", "069 560 001", "str. Test 7", "1111111111116"],
                              ["Testescu3 Ana", "069560003", "str. Test 9", "2001234567893"]])
        chk = _check(c, fam, "familie.xlsx")
        res.check("семейный номер: ребёнок — новая фиша с пометкой; двое уже есть, обоим есть что дописать",
                  (chk["counts"]["create"], chk["counts"]["family"], chk["counts"]["exists"],
                   chk["counts"]["fill"]), (1, 1, 2, 2))
        res.check("что именно допишется, сказано словами",
                  [row["fill"] for g in chk["groups"] if g["id"] == "exists" for row in g["rows"]],
                  [["adresă"], ["idnp".upper(), "adresă"]])
        _run_all(c, fam, "familie.xlsx")
        kid = _find(c, "Testescu1 Copil")
        res.check("ребёнок заведён с тем же телефоном; родитель не переименован",
                  ([x["phone"] for x in kid], _card(c, p2)["profile"]["name"]), (["069560001"], "Testescu1 Ana"))
        res.check("переключатель выключен — в существующую фишу ничего не дописано",
                  _card(c, p2)["profile"]["address"], "")
        fill = _run_all(c, fam, "familie.xlsx", {"fill": True})
        p4 = _find(c, "Testescu3 Ana")[0]["id"]
        res.check("включён — пустое дописано, заполненное (IDNP) не тронуто",
                  (fill["total"]["filled"], _card(c, p2)["profile"]["address"],
                   _card(c, p2)["profile"]["idnp"], _card(c, p4)["profile"]["idnp"]),
                  (2, "str. Test 7", "9990000000001", "2001234567893"))
        res.check("летопись называет дописанные поля", _lines(c, p4)[0],
                  "Fișă completată prin import: IDNP, adresă")
        res.check("ещё раз с переключателем — дописывать нечего",
                  _run_all(c, fam, "familie.xlsx", {"fill": True})["total"]["filled"], 0)

        rep = _send(c, "report", lib, "biblioteca.xlsx", **{"import": run["id"]})
        text = _sheet_text(rep.raw) if rep.raw[:2] == b"PK" else rep.body
        res.check("отчёт после импорта: «există deja» только у заведённого руками, свои с пометкой — "
                  "«fișă nouă, cu observații», вошедших без пометки в отчёте нет",
                  (rep.status, text.count(">există deja<"), text.count(">fișă nouă, cu observații<"),
                   text.count("<row ")), (200, 1, cnt["noted"], cnt["noted"] + 2))

        add_appt(c, (clinic_today() + dt.timedelta(days=5)).isoformat(), "10:00", "Testescu5 Ana",
                 "069560005")
        c.post_json(f"/api/patients/{p4}/alerts", {"kind": "allergy", "text": "latex"})
        r = c._do(f"/api/pimport/undo?id={run['id']}", b"", {})
        und = _j(r)
        res.check("отмена: убраны пустые фиши импорта; с записью, с правкой руками и дописанные — остались",
                  (und["code"], und["data"]["done"], und["data"]["total"]["removed"], und["data"]["kept"],
                   und["data"]["total"]["undone"]), ("pi_undone", True, 16, 3, True))
        res.check("в картотеке: заведённый руками, ребёнок и три оставшиеся",
                  (_total(c), len(_find(c, "Testescu5 Ana")), len(_find(c, "Testescu7 Ana"))), (5, 1, 0))
        res.check("импорта, которого нет, — 404", c._do("/api/pimport/undo?id=999", b"", {}).status, 404)

    big = S.library_book(S.LIB_HEADER, S.lib_rows(450))
    with Server() as s:
        c = Client(s.url).login()
        chk = _check(c, big, "mare.xlsx")
        res.check("450 записей — три порции; группы режутся до 300 строк, остаток числом",
                  (chk["counts"]["create"], chk["parts"],
                   [(len(g["rows"]), g["more"]) for g in chk["groups"] if g["id"] == "noted"]),
                  (450, 3, [(300, chk["counts"]["noted"] - 300)]))
        r = _j(_send(c, "run", big, "mare.xlsx", token=chk["token"], part=0))
        res.check("первая порция: 200 фиш, импорт не закончен",
                  (r["code"], r["data"]["created"], r["data"]["done"], _total(c)), ("", 200, False, 200))
        res.check("порция за краем — 422", _send(c, "run", big, "mare.xlsx", token=chk["token"],
                                                 part=3).msg, "pi_opts")
        res.check("повтор той же порции ничего не заводит",
                  (_j(_send(c, "run", big, "mare.xlsx", token=chk["token"], part=0,
                            **{"import": r["data"]["import"]}))["data"]["created"], _total(c)), (0, 200))
        # окно закрыли; тот же файл запущен заново
        rest = _run_all(c, big, "mare.xlsx")
        res.check("после обрыва новый запуск доводит остальное: 200 уже есть, 250 новых",
                  (rest["check"]["counts"]["exists"], rest["total"]["created"], _total(c)), (200, 250, 450))
        xl = c.get("/admin/patients.xlsx")
        chk = _check(c, xl.raw, "pacienti_export.xlsx")
        res.check("круг: книга, выгруженная программой, загружена обратно — ноль новых",
                  (chk["counts"]["rows"], chk["counts"]["create"]), (450, 0))


def suite_rights(res: Result) -> None:
    """Директор и регистратура — да, врач — 403; демо — отказ; маршруты стоят
    в списках «только с этого ПК» и в воротах режима чтения."""
    from app.core import auth, demo, license_state
    lib = (FIX / "biblioteca.xlsx").read_bytes()
    res.ok("право импорта — у директора и регистратуры, у врача нет",
           auth.can({"role": "director"}, auth.PERM_IMPORT)
           and auth.can({"role": "receptie"}, auth.PERM_IMPORT)
           and not auth.can({"role": "medic"}, auth.PERM_IMPORT))
    posts = {"/api/pimport/check", "/api/pimport/run", "/api/pimport/report", "/api/pimport/undo"}
    res.check("все пишущие и читающие файл маршруты — «только с этого ПК»",
              {p for p in auth.LOCAL_ONLY if "pimport" in p}, posts)
    res.ok("ни один не разрешён в режиме чтения",
           not any(license_state.allowed(p) for p in posts))
    res.ok("демо закрывает раздел целиком: и маршруты, и страницу",
           {"/api/pimport", PAGE} <= set(demo.BLOCKED))
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        for body in ({"uid": "d2", "name": "Dr. Activ Doi", "role": "medic", "doctor_id": "d2",
                      "pin": "2222"},
                     {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "4444"}):
            boss.post_json("/api/settings/users", body)
        med, ana = Client(s.url), Client(s.url)
        med.post("/admin/login", password="2222", next="/admin")
        ana.post("/admin/login", password="4444", next="/admin")
        for path in ("/api/pimport", "/api/pimport/model.xlsx"):
            res.check(f"врач: GET {path} — 403", med.get(path).status, 403)
        for what in ("check", "run", "report", "undo"):
            r = _send(med, what, lib)
            res.check(f"врач: {what} — 403 no_access", (r.status, r.msg), (403, "no_access"))
        res.check("регистратура видит экран", ana.get("/api/pimport").status, 200)
        page = ana.get(PAGE)
        res.ok("страница экрана у регистратуры — узел React в разделе «Pacienți»",
               page.status == 200 and 'data-screen="patients_import"' in page.body
               and "/admin/settings" not in json.dumps(shell_model(page.body)["frame"]["crumbs"]),
               f"{page.status}")
        res.ok("врач: страница закрыта", med.get(PAGE).status in (303, 307), "")
        res.check("кнопка «Importă» в списке пациентов — по праву: директор, регистратура, врач",
                  [_j(c.get("/api/patients"))["data"]["can_import"] for c in (boss, ana, med)],
                  [True, True, False])
        tiles = {t["href"]: t for t in _j(boss.get("/api/settings/hub"))["data"]["tiles"]}
        res.check("плитка «Import pacienți» у директора в группе «Date și rețea»",
                  tiles.get(PAGE, {}).get("group"), "date")
        run = _run_all(ana, lib, "biblioteca.xlsx")
        res.check("регистратура импортирует; в записи об импорте — её имя",
                  (run["total"]["created"], run["total"]["actor"]), (20, "Ana R"))
        pid = _find(boss, "Testescu2 Ana")[0]["id"]
        res.check("в летописи фиши автор — она же",
                  _card(boss, pid)["activity"]["items"][0]["who"], "Ana R")
        res.check("директор отменяет импорт",
                  _j(boss._do(f"/api/pimport/undo?id={run['id']}", b"", {}))["data"]["total"]["removed"], 20)
        res.check("без входа — 401", _send(Client(s.url), "check", lib).status, 401)
    with Server(env={"DENTART_DEMO": "1"}) as s:
        c = Client(s.url).login()
        res.check("демо: проверка файла — 403 demo_off", (lambda r: (r.status, r.msg))(_send(c, "check", lib)),
                  (403, "demo_off"))
        res.check("демо: экран импорта — 403 demo_off", c.get("/api/pimport").msg, "demo_off")
        res.ok("демо: страницы импорта нет, плитки в настройках тоже",
               'data-screen="patients_import"' not in c.get(PAGE).body
               and PAGE not in c.get("/api/settings/hub").body, "")
        res.check("демо: кнопки «Importă» в списке пациентов нет",
                  _j(c.get("/api/patients"))["data"]["can_import"], False)


def suite_encrypted(res: Result) -> None:
    """Зашифрованная картотека: импорт идёт через `db`, имён в файле базы нет."""
    from app.core import dbkey
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pimport_crypt_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", tmp / "clinic.json")
        if not dbkey.store(dbkey.generate(), tmp):
            res.failed.append(("ключ не сохранился под DPAPI", "не Windows или DPAPI отказал"))
            return
        with Server(dir_=tmp) as s:
            c = Client(s.url).login()
            run = _run_all(c, S.library_book(["Nume", "Telefon"], [["Criptescu Marcaj", "069555301"],
                                                                 ["Criptescu Doi", "069555302"]]),
                           "cript.xlsx")
            res.check("импорт на зашифрованной картотеке", (run["total"]["created"], _total(c)), (2, 2))
            res.check("повтор — ноль новых",
                      _run_all(c, S.library_book(["Nume", "Telefon"], [["Criptescu Marcaj", "+37369555301"]]),
                               "cript.xlsx")["total"]["created"], 0)
        raw = (tmp / "dental.db").read_bytes()
        res.ok("имя из файла не лежит в базе открытым текстом",
               b"Criptescu" not in raw and not raw.startswith(b"SQLite format 3"))
    finally:
        _rmtree_settled(tmp)
