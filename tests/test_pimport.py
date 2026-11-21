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
import time
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


def _undo(c: Client, iid: int) -> dict:
    """Отмена так, как её ведёт экран: визиты, потом фиши, порциями; ответ последней порции и сумма
    снятого (`removed`, `visits_removed`)."""
    phase, after, removed, vrem, last = "v", 0, 0, 0, {}
    for _ in range(1000):
        r = c._do(f"/api/pimport/undo?id={iid}&phase={phase}&after={after}", b"", {})
        last = _j(r)
        if r.status != 200:
            return last
        removed += last["data"]["removed"]
        vrem += last["data"]["visits_removed"]
        if last["data"]["done"]:
            break
        phase, after = last["data"]["phase"], last["data"]["after"]
    last["sum"] = {"removed": removed, "visits_removed": vrem}
    return last


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
        return t, r, pi.build(t, r, {f"d{i}": n for i, n in enumerate(doctors)})[0]

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
                           "Dr. Activ Doi", "17", "Recepție", "Activ", 3, 0]])
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
    res.check("группы через пробел — один номер, и когда вторая группа начинается с нуля",
              [ph([x]) for x in ("060 000 205", "079 012 345", "+373 600 00 203", "(060) 000-223",
                                 "0600-00-222", "060.000.205", "tel. 060 000 226", "0 69 555 101")],
              [(["060000205"], []), (["079012345"], []), (["060000203"], []), (["060000223"], []),
               (["060000222"], []), (["060000205"], []), (["060000226"], []), (["069555101"], [])])
    res.check("два номера: по запятой, «;», «/», строке — и когда каждая часть сама полный номер",
              [ph([x])[0] for x in ("079 012 345, 060 000 205", "079 012 345; 060 000 205",
                                    "079012345/060000205", "079 012 345\n060 000 205",
                                    "069555103 022555104", "079 012 345 060 000 205",
                                    "079-012-345-060-000-205", "mob. 079 012 345 fix 022 555 104")],
              [["079012345", "060000205"]] * 4 + [["069555103", "022555104"]]
              + [["079012345", "060000205"]] * 2 + [["079012345", "022555104"]])
    res.check("иностранный после нашего: по «+» и по длине; один иностранный не делится",
              [ph([x]) for x in ("060 000 205 +40 700 000 209", "069555101 89115550107", "+40 700 000 209")],
              [(["060000205", "+40700000209"], [("tel_foreign", "")]),
               (["069555101", "89115550107"], [("tel_foreign", "")]),
               (["+40700000209"], [("tel_foreign", "")])])
    res.check("непрочитанное остаётся непрочитанным", (ph(["12345"]), ph(["060 000"])),
              (([], [("tel_bad", "12345")]), ([], [("tel_bad", "060 000")])))

    res.check("шапка «как в жизни»: «Дата рожд.» и «Notă» узнаются, «Vârstă» и «Nr.» — нет",
              g(["Nr.", "ФИО", "Tel.", "Дата рожд.", "IDNP", "Пол", "Адрес", "Notă", "Vârstă"]),
              {1: "full", 2: "phone", 3: "birth", 4: "idnp", 5: "gender", 6: "address", 7: "notes"})
    res.check("дата рождения сокращённо: Д.Р., Г.Р., год рожд., D.N., Data naș., Data n., Anul nașt.",
              [g(["Nume", h]).get(1) for h in ("Д.Р.", "Г.Р.", "год рожд.", "D.N.", "Data naș.",
                                               "Data n.", "Data nasc.", "Anul nașt.")], ["birth"] * 8)
    res.check("врач: Medic, Dr., Doctor, Лечащий врач, Стоматолог, Medic stomatolog",
              [g(["Nume", h]).get(1) for h in ("Medic", "Dr.", "Doctor", "Лечащий врач", "Стоматолог",
                                               "Medic stomatolog")], ["doctor"] * 6)
    res.check("чужое не перехвачено: место рождения пропущено, «Nota medicului» — заметки, "
              "«Data programării» — запись",
              g(["Nume", "Locul nașterii", "Место рождения", "Nota medicului", "Data programării",
                 "Data nașterii", "Medic curant"]),
              {0: "full", 3: "notes", 4: "appt", 5: "birth", 6: "doctor"})

    book = S.excel_book([("S", [["Nume", "Telefon", "Data nașterii", "Notă"],
                                ["Ianuarie 2024"],
                                ["Popescu Ion", "060 000 205", D(1985, 3, 14), "x"],
                                ["Total: 2 înregistrări"],
                                ["Gîscă Petru"],
                                ["Rusu Ana 2", "069555120"]], ["A2:D2"])])
    _t, r, recs = recs_of(book)
    by = {x["line"]: x for x in recs}
    res.check("строка-раздел (одна ячейка на всю ширину) пропущена молча; «Total» в колонке имени — "
              "«Nu intră» словами; одно имя — пациент",
              (sorted(by), by[4]["err"], pi.why(by[4]["err"], by[4]["name"]), by[5]["err"]),
              ([3, 4, 5, 6], "title", "pare un titlu, nu un pacient („Total: 2 înregistrări”)", ""))
    res.check("имя с цифрой, но с телефоном — не титул", (by[6]["err"], by[6]["phone"]), ("", "069555120"))
    res.check("номер «060 000 205» в строке — чистый, без пометок",
              (by[3]["phone"], by[3]["notes_w"], by[3]["notes"]), ("060000205", [], "x"))

    docs = {"d1": "Dr. Elena Rusu", "d2": "Ion Rusu", "d3": "Ciobanu Gheorghe", "d4": "Țurcanu Maria"}
    dd = pi.Doctors(docs)
    auto = {v: dd.auto(pi.doc_key(v), v) for v in (
        "Dr. Elena Rusu", "rusu elena", "Rusu E.", "E. Rusu", "E.R.", "Е. Русу", "Русу Елена", "д-р Чобану",
        "Чобану Георге", "Dr Ciobanu", "Цуркану М.", "TURCANU MARIA", "Врач Русу Ион", "Dr. Rusu",
        "Popescu", "Dr.")}
    res.check("врач узнан: полное имя в любом порядке, «Rusu E.», инициалы, без регистра и диакритики, "
              "кириллица, «д-р» и «врач»",
              {v: a[0] for v, a in auto.items()},
              {"Dr. Elena Rusu": "d1", "rusu elena": "d1", "Rusu E.": "d1", "E. Rusu": "d1", "E.R.": "d1",
               "Е. Русу": "d1", "Русу Елена": "d1", "д-р Чобану": "d3", "Чобану Георге": "d3",
               "Dr Ciobanu": "d3", "Цуркану М.": "d4", "TURCANU MARIA": "d4", "Врач Русу Ион": "d2",
               "Dr. Rusu": "", "Popescu": "", "Dr.": ""})
    res.check("двое подошли одинаково — не угадывается, оба названы", auto["Dr. Rusu"][1], ["d1", "d2"])
    rows = [["Nume", "Medic"], ["Unu Test", "Rusu E."], ["Doi Test", "rusu  e"], ["Trei Test", "Dr. Rusu"],
            ["Patru Test", "Popescu"], ["Cinci Test", "Popescu"], [None, "Popescu"]]
    blob = S.excel_book([("S", rows, [])])
    t = tabfile.read(blob, "a.xlsx")
    r = pi.resolve(t, pi.parse_opts(""))
    recs = pi.build(t, r, docs)[0]
    res.check("без выбора: узнанный — врач фиши; не узнанный — пометка и заметка",
              [(x["primary_doctor"], x["notes"]) for x in recs[:4]],
              [("Dr. Elena Rusu", ""), ("Dr. Elena Rusu", ""), ("", "Medic: Dr. Rusu"), ("", "Medic: Popescu")])
    res.check("шаг «Medici»: одно написание — одна строка (регистр и точки не важны), сперва не узнанные",
              [(x["value"], x["rows"], x["auto"], x["cands"], x["choice"])
               for x in pi.doctor_list(recs, docs)],
              [("Popescu", 2, "", [], ""), ("Dr. Rusu", 1, "", ["d1", "d2"], ""), ("Rusu E.", 2, "d1", [], "")])
    pick = {pi.doc_key("Dr. Rusu"): "d2", pi.doc_key("Popescu"): pi.NO_DOCTOR, pi.doc_key("Rusu E."): "d9"}
    r = pi.resolve(t, {**pi.parse_opts(json.dumps({"docs": pick})), "sheet": 0})
    recs = pi.build(t, r, docs)[0]
    res.check("выбор человека: «Dr. Rusu» → Ion Rusu, «Popescu» → fără medic (без пометки), "
              "врача, которого нет, выбор не меняет",
              [(x["primary_doctor"], x["notes"], x["notes_w"]) for x in recs],
              [("Dr. Elena Rusu", "", [])] * 2 + [("Ion Rusu", "", [])] + [("", "", [])] * 3)
    res.check("выбор едет в отпечатке", pi.token(blob, r) != pi.token(blob, pi.resolve(t, pi.parse_opts(""))),
              True)
    res.check("слишком много решений — кривой выбор",
              pi.parse_opts(json.dumps({"docs": {str(i): "d1" for i in range(pi.DOCS_CAP + 1)}})), None)
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

    # ---- дата и час визита: `read(times=True)` и `when` (импорт с записями) ----
    from zoneinfo import ZoneInfo

    T, DT, nov = dt.time, dt.datetime, D(2026, 11, 21)
    blob = S.timed_book([
        ["Data", "Ora"],
        [(2, DT(2026, 11, 21, 9, 30))],                        # 2: встроенный «m/d/yy h:mm»
        [(1, nov), (3, T(9, 30))],                             # 3: дата и «h:mm» раздельно
        [(6, DT(2026, 11, 21, 14, 7)), (4, T(14, 7))],         # 4: «dd.mm.yyyy hh:mm» и «hh:mm»
        [(1, nov), (5, T(1, 30))],                             # 5: «[h]:mm»
        [(1, DT(2026, 11, 21, 9, 30))],                        # 6: формат даты, в значении час
        [(7, DT(1990, 3, 14))],                                # 7: полночь — дата без часа
        [("d", "2026-11-21T09:30:00"), ("d", "1899-12-30T10:15:00")],   # 8: тип «дата» ISO
        [("d", "2026-11-21T00:00:00")],                        # 9: ISO полночь
        [(5, 1.0625)],                                         # 10: «[h]:mm» больше суток
    ])
    old = dict(tabfile.read(blob, "p.xlsx").sheets[0].rows)
    new = dict(tabfile.read(blob, "p.xlsx", times=True).sheets[0].rows)
    res.check("без times — как было: дата Excel — дата, час отброшен (склад, прайс, день рождения)",
              [old[2][0], old[4][0], old[6][0], old[8][0]], [nov] * 4)
    res.check("с times: дата-время одной ячейкой — стенное datetime",
              [new[2][0], new[4][0], new[6][0], new[8][0]],
              [DT(2026, 11, 21, 9, 30), DT(2026, 11, 21, 14, 7), DT(2026, 11, 21, 9, 30),
               DT(2026, 11, 21, 9, 30)])
    res.check("с times: час встроенным, своим и «[h]:mm» форматом, ISO до 1900 — time",
              [new[3][1], new[4][1], new[5][1], new[8][1]], [T(9, 30), T(14, 7), T(1, 30), T(10, 15)])
    res.check("полночь и с times — дата без часа", [new[3][0], new[7][0], new[9][0]],
              [nov, D(1990, 3, 14), nov])
    res.check("«[h]:mm» больше суток — числом, как набрали", new[10][0], "1.0625")
    res.check("день рождения ячейкой с часом — та же дата", pi.parse_date(DT(1990, 3, 14, 10, 0)),
              (D(1990, 3, 14), None, ""))

    W, tz = tabfile.when, ZoneInfo("Europe/Chisinau")

    def w(day, hour=None):
        x = W(day, hour)
        return (x.day, x.start, x.minutes, x.source, x.problem)

    res.check("дата-время одной ячейкой: число Excel, datetime, ISO, текст с точкой, с запятой",
              [w(x)[:3] for x in ("46347.395833333336", DT(2026, 11, 21, 9, 30), "2026-11-21T09:30",
                                  "21.11.2026 09:30", "21.11.2026, 9.30", "21/11/26 9h30",
                                  "21.11.2026 ora 9:30")],
              [(nov, T(9, 30), None)] * 7)
    res.check("дата и час раздельно: время Excel, текст, доля суток, одно число часа, am/pm",
              [w(nov, h)[1] for h in (T(9, 30), "09:30", "9.30", "0.395833333", "9", "9:30 am",
                                      "2:30 pm")],
              [T(9, 30)] * 4 + [T(9, 0), T(9, 30), T(14, 30)])
    res.check("час колонки сильнее часа в ячейке даты", w("21.11.2026 08:00", "11:00")[1], T(11, 0))
    res.check("диапазон — начало и длительность, исходное — как в файле",
              [w("21.11.2026 9:30-10:00"), w(nov, "09:30–10:45"), w(nov, "9:30 - 10:30")],
              [(nov, T(9, 30), 30, "09:30–10:00", ""), (nov, T(9, 30), 75, "09:30–10:45", ""),
               (nov, T(9, 30), 60, "09:30–10:30", "")])
    res.check("дата без часа — «без часа», не 00:00: текст, дата, число Excel, полночь, пустой час",
              [w(x, h)[4] for x, h in (("21.11.2026", None), (nov, None), ("46347", None),
                                       ("21.11.2026 00:00", None), (nov, "  "))],
              ["no_time"] * 5)
    res.check("что не прочитать — код, не угадка",
              [w(x, h)[4] for x, h in ((None, None), ("", "9:00"), ("abc", None), ("31.02.2026", "9:00"),
                                       (T(9, 0), None), ("12345", None), (nov, "25:00"),
                                       (nov, "10:00-09:00"), ("21.11.2026 09:30 consult", None),
                                       (nov, D(2026, 11, 21)), (nov, "13:00 pm"))],
              ["no_date", "no_date", "bad_date", "bad_date", "bad_date", "bad_date", "bad_time",
               "bad_range", "bad_time", "bad_time", "bad_time"])
    res.check("коды — из списка WHEN_PROBLEMS", set(tabfile.WHEN_PROBLEMS),
              {"no_date", "bad_date", "no_time", "bad_time", "bad_range"})

    def slot(x, h=None):
        got = W(x, h).slot(tz)
        return got and (got[0].isoformat(), got[1])

    res.check("к сетке 5 минут правилом Google: начало к ближайшим, длина вверх, исходное не тронуто",
              [slot(nov, "09:07"), slot(nov, "09:08"), slot(nov, "9:30-9:53"), slot(nov, "23:58"),
               slot(nov, "09:30")],
              [("2026-11-21T09:05:00+02:00", None), ("2026-11-21T09:10:00+02:00", None),
               ("2026-11-21T09:30:00+02:00", 25), ("2026-11-22T00:00:00+02:00", None),
               ("2026-11-21T09:30:00+02:00", None)])
    res.check("сдвинутое округлением названо — исходный час в комментарий",
              [W(nov, h).rounded(tz) for h in ("09:07", "09:30", "9:30-9:53", "9:30-10:00")],
              [True, False, True, False])
    res.check("без часа и с отказом слота нет", [slot(nov), slot("abc")], [None, None])
    res.check("летнее время: тот же час по часам клиники",
              slot(D(2027, 7, 1), "09:30"), ("2027-07-01T09:30:00+03:00", None))

    # колонка «Durata» визита: минуты числом и текстом, время Excel, доля суток; к 5 минутам вверх
    from app import engine as eng
    res.check("длительность визита из колонки «Durata»",
              [pi._minutes(x) for x in ("30", "45 min", "1:30", "1h30", "2 ore", dt.time(1, 30), "0.0625", "7",
                                        "300", "abc", "0")],
              [30, 45, 90, 90, 120, 90, 90, 10, None, None, None])
    saved = dict(eng.SERVICES)
    try:
        eng.SERVICES.clear()
        eng.SERVICES.update({"pain": {"ro": "Durere acută", "ru": "", "urgent": True},
                             "plan": {"ro": "Coroană", "ru": "", "where": "plan"},
                             "fill": {"ro": "Obturație", "ru": "Пломба"},
                             "cons": {"ro": "Consultație inițială", "ru": ""}})
        first = pi.default_service("")
        eng.SERVICES.pop("cons")
        calm = pi.default_service("")
        res.check("процедура по умолчанию: консультация, иначе первая не срочная услуга агенды; выбор — сильнее",
                  (first, calm, pi.default_service("pain"), pi.default_service("plan")),
                  ("cons", "fill", "pain", "fill"))
        res.check("процедура из файла: то же название без диакритики, ru, единственная по части; прайс плана — нет",
                  [pi.svc_match(x) for x in ("obturatie", "Пломба", "Obtura", "Coroană", "", "zzz")],
                  ["fill", "fill", "fill", "", "", ""])
    finally:
        eng.SERVICES.clear()
        eng.SERVICES.update(saved)


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
               home["fields"][0] == {"id": "", "label": "Nu importa"} and len(home["fields"]) == 21)
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
        # канал — по метке импорта, хотя ключ у фиши `manual:` (ORIGIN_SQL)
        sm = _j(c.get("/api/patients/summary"))["data"]
        res.check("канал фиши импорта: строка списка, шапка фиши, пункт фильтра словами",
                  (_find(c, "Testescu1 Ana")[0]["channel"], prof["channel"],
                   [(x["id"], x["label"]) for x in sm["channels"]]),
                  ("excel", "Import Excel", [("manual", "Recepție"), ("excel", "Import Excel")]))
        res.check("фильтр «Import Excel» — 19 фиш файла, «Recepție» — заведённая руками",
                  (_j(c.get("/api/patients?ch=excel&per=50"))["data"]["total"],
                   [r["name"] for r in _j(c.get("/api/patients?ch=manual&per=50"))["data"]["rows"]]),
                  (19, ["Testescu0 Ana"]))
        sheet = _sheet_text(c.get("/admin/patients.xlsx").raw)
        res.ok("книга Excel: колонка «Canal» — подпись словаря целиком",
               "Import Excel</t>" in sheet and "Recepție</t>" in sheet, sheet[:300])
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
        # у каждой строки файла дата записи без часа: визит не встал — строка в отчёте с колонкой «Programare»
        res.check("отчёт после импорта: «există deja» только у заведённого руками, свои с пометкой — "
                  "«fișă nouă, cu observații»; строки, чей визит не встал (без часа), — тоже в отчёте",
                  (rep.status, text.count(">există deja<"), text.count(">fișă nouă, cu observații<"),
                   text.count("<row "), text.count("programare fără oră")),
                  (200, 1, cnt["noted"], cnt["rows"] + 1, cnt["rows"]))

        add_appt(c, (clinic_today() + dt.timedelta(days=5)).isoformat(), "10:00", "Testescu5 Ana",
                 "069560005")
        c.post_json(f"/api/patients/{p4}/alerts", {"kind": "allergy", "text": "latex"})
        und = _undo(c, run["id"])
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


def suite_doctors(res: Result) -> None:
    """Врач фиши из колонки файла: что узнано, выбор человека на одно написание,
    выключенный врач, ничего до «Importă», отмена снимает фиши вместе с врачом."""
    rows = [["Nume", "Telefon", "Medic"],
            ["Medicescu Unu", "069561001", "Activ Doi"],
            ["Medicescu Doi", "069561002", "dr. activ doi"],
            ["Medicescu Trei", "069561003", "Д-р Актив Трей"],
            ["Medicescu Patru", "069561004", "A. Patru"],
            ["Medicescu Cinci", "069561005", "Arhivat U."],
            ["Medicescu Sase", "069561006", "Dr. Activ"],
            ["Medicescu Sapte", "069561007", "Popescu"],
            ["Medicescu Opt", "069561008", "Popescu"],
            ["Medicescu Noua", "069561009", None]]
    blob = S.excel_book([("Pacienți", rows, [])])
    with Server() as s:
        c = Client(s.url).login()
        chk = _check(c, blob, "medici.xlsx")
        res.check("колонка «Medic» узнана сама", chk["opts"]["cols"], {"0": "full", "1": "phone", "2": "doctor"})
        res.check("врачи клиники для выбора: все, выключенный помечен",
                  [(d["id"], d["active"]) for d in chk["clinic_doctors"]],
                  [("d1", False), ("d2", True), ("d3", True), ("d4", True)])
        res.check("шаг «Medici»: написание → врач (звание и регистр не важны); не узнанные первыми, "
                  "с кандидатами",
                  [(d["value"], d["rows"], d["auto"], d["cands"]) for d in chk["doctors"]],
                  [("Popescu", 2, "", []), ("Dr. Activ", 1, "", ["d2", "d3", "d4"]),
                   ("Activ Doi", 2, "d2", []), ("A. Patru", 1, "d4", []), ("Д-р Актив Трей", 1, "d3", []),
                   ("Arhivat U.", 1, "d1", [])])
        noted = {row["name"]: row["notes"] for g in chk["groups"] for row in g["rows"]}
        res.check("не узнанный без выбора — пометка в строке", noted["Medicescu Sapte"],
                  ["medicul „Popescu” nu este în lista clinicii, trecut în notițe"])
        res.check("проверка ничего не записала", _total(c), 0)

        key = {d["value"]: d["key"] for d in chk["doctors"]}
        opts = {"docs": {key["Dr. Activ"]: "d3", key["Popescu"]: "-"}}
        chk2 = _check(c, blob, "medici.xlsx", opts)
        res.check("выбор человека виден в ответе и снимает пометки",
                  ([d["choice"] for d in chk2["doctors"]][:2], chk2["counts"]["noted"]), (["-", "d3"], 0))
        res.check("со старым отпечатком после выбора — 409",
                  _send(c, "run", blob, "medici.xlsx", opts, token=chk["token"]).msg, "pi_stale")
        run = _run_all(c, blob, "medici.xlsx", opts)
        res.check("импорт: девять фиш", run["total"]["created"], 9)
        doc = {x["name"]: _card(c, x["id"])["profile"]["primary_doctor"]
               for x in _j(c.get(f"/api/patients?imp={run['id']}&per=50"))["data"]["rows"]}
        res.check("врач фиши — как «Setează medicul»: имя врача клиники; выключенный — тоже; "
                  "«fără medic» и пустая ячейка — без врача",
                  doc, {"Medicescu Unu": "Dr. Activ Doi", "Medicescu Doi": "Dr. Activ Doi",
                        "Medicescu Trei": "Dr. Activ Trei", "Medicescu Patru": "Dr. Activ Patru",
                        "Medicescu Cinci": "Dr. Arhivat Unu", "Medicescu Sase": "Dr. Activ Trei",
                        "Medicescu Sapte": "", "Medicescu Opt": "", "Medicescu Noua": ""})
        und = _undo(c, run["id"])
        res.check("отмена убирает фиши вместе с врачом", (und["data"]["total"]["removed"], _total(c)), (9, 0))


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
        new_patient(boss, "Testescu2 Strain", "069555990")
        iid = run["id"]

        def lst(c, more=""):
            return _j(c.get(f"/api/patients?per=50&imp={iid}{more}"))["data"]

        only = lst(boss)
        res.check("список по импорту: только его фиши, подпись — файл и сколько осталось",
                  (only["total"], only["import"]["file"], only["import"]["left"], only["import"]["gone"]),
                  (20, "biblioteca.xlsx", 20, False))
        res.ok("заведённый руками в отбор не попал",
               "Testescu2 Strain" not in [r["name"] for r in only["rows"]]
               and len(_find(boss, "Testescu2")) > lst(boss, "&q=Testescu2")["total"] > 0, "")
        res.check("поиск внутри отбора", [r["name"] for r in lst(boss, "&q=Testescu2+Ana")["rows"]],
                  ["Testescu2 Ana"])
        res.check("врач видит картотеку — тот же отбор по прямому адресу", lst(med)["total"], 20)
        gone = _j(boss.get("/api/patients?imp=99999"))
        res.check("импорта с таким номером нет — пустой список со словом, не отказ",
                  (gone["ok"], gone["data"]["total"], gone["data"]["import"]["gone"],
                   bool(gone["data"]["import"]["text"])), (True, 0, True, True))
        res.check("без отбора подписи нет", _j(boss.get("/api/patients"))["data"]["import"], None)
        res.ok("страница списка несёт отбор в параметрах узла",
               "&quot;imp&quot;: &quot;%d&quot;" % iid in boss.get(f"/admin/search?imp={iid}").body
               or '"imp": "%d"' % iid in boss.get(f"/admin/search?imp={iid}").body, "")
        booked = add_appt(boss, (clinic_today() + dt.timedelta(days=5)).isoformat(), "10:00", "Testescu2 Ana",
                          _find(boss, "Testescu2 Ana")[0]["phone"])
        res.ok("у импортированного пациента появилась запись", booked.msg.startswith("ok"), booked.msg)
        res.check("директор отменяет импорт: фиша с записью остаётся",
                  _undo(boss, iid)["data"]["total"]["removed"], 19)
        left = lst(boss)
        res.check("после отмены отбор ведёт к оставшимся фишам",
                  ([r["name"] for r in left["rows"]], left["import"]["left"], left["import"]["undone"]),
                  (["Testescu2 Ana"], 1, True))
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


VIS_HEAD = ["Nume", "Telefon", "Data programării", "Ora", "Medic", "Procedură", "Durata", "Comentariu programare"]


def _dmy(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def _visit_rows(f: dt.date, p: dt.date) -> list:
    """Строки файла с визитами: каждая проверяет одно правило (порядок важен — раньше в файле первым)."""
    F, F1, P = _dmy(f), _dmy(f + dt.timedelta(days=1)), _dmy(p)
    return [
        ["Vizita Unu", "069570001", F, "09:00", "Activ Doi", "Consultație", None, "adus de fiică"],   # 2 новый
        ["Vizita Doi", "069570002", F, "09:30", "Activ Doi", None, None, None],          # 3 врач занят строкой 2
        ["Vizita Trei", "069570003", F, None, "Activ Trei", None, None, None],           # 4 без часа
        ["Vizita Patru", "069570004", P, "10:00", "Activ Trei", "Igienizare", None, None],  # 5 прошлое
        ["Vizita Cinci", "069570005", F, "11:00", "Popescu", None, None, None],          # 6 врача нет в клинике
        ["Vizita Unu", "069570001", F1, "10:00", "Activ Doi", "Tratament lung", None, None],  # 7 тот же пациент
        ["Vizita Sase", "069570006", F, "9:07–9:50", "Activ Patru", "Detartraj", None, None],  # 8 округление
        ["Vizita Sapte", "069570007", F, "10:00", "Arhivat Unu", None, None, None],      # 9 врач в архиве
        ["Vizita Opt", "069570008", F, "06:00", "Activ Doi", None, None, None],          # 10 до часов клиники
        ["Exist Ana", "069570010", F, "12:00", "Activ Doi", None, None, None],           # 11 фиша уже есть
        ["Vizita Noua", "069570009", F, "13:00", "Activ Doi", None, "1:30", None],       # 12 своя длительность
        ["Vizita Zece", "069570011", F, "15:00", "Activ Trei", None, None, None],        # 13 занято в журнале
        ["Vizita Unsprezece", "069570012", F, "25:00", "Activ Doi", None, None, None],   # 14 час не читается
        ["Istoric Devreme", "069570013", P, "06:00", "Activ Doi", None, None, None],     # 15 история до часов клиники
        ["Istoric Arhivat", "069570014", P, "11:00", "Arhivat Unu", None, None, None],   # 16 история у врача в архиве
    ]


def _db_rows(s: Server, sql: str, *args) -> list[dict]:
    import sqlite3
    con = sqlite3.connect(str(s.dir / "dental.db"), timeout=5)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def _appts(s: Server) -> dict:
    """Визиты по имени пациента: [(день, час по клинике, статус, врач, услуга, минуты, комментарий,
    импорт, без SMS)], по времени."""
    from harness import TZ
    out: dict = {}
    for r in _db_rows(s, "SELECT p.name, a.* FROM appointments a JOIN patients p ON p.id = a.patient_id "
                         "ORDER BY a.starts_at"):
        at = dt.datetime.fromisoformat(r["starts_at"].replace("Z", "+00:00")).astimezone(TZ)
        out.setdefault(r["name"], []).append(
            (at.date(), at.strftime("%H:%M"), r["status"], r["doctor_id"], r["service_id"], r["duration_min"],
             r["comment"], bool(r["import_id"]), r["sms_skip"]))
    return out


def suite_visits(res: Result) -> None:
    """Импорт с записями: строка «пациент + дата/час + врач» становится визитом журнала — через
    `book.book_visit`, будущее «programată», прошлое «finalizată»; без часа, без врача, занято —
    визита нет, дата в заметках; предпросмотр ничего не пишет; отмена снимает и визиты."""
    from harness import set_rooms  # noqa: F401 — кабинеты врача не трогаются: один кабинет
    import test_recall as tr

    res.ok("исходники нашлись", (BOT / "app" / "core" / "book.py").exists()
           and (BOT / "app" / "modules" / "patients" / "pimport.py").exists())
    today = clinic_today()
    f, p = today + dt.timedelta(days=3), today - dt.timedelta(days=200)
    blob = S.library_book(VIS_HEAD, _visit_rows(f, p))
    with Server() as s:
        c = Client(s.url).login()
        tr._set_recall(c, {"hygiene": 6})
        new_patient(c, "Exist Ana", "069570010")
        res.check("в журнале занят d3 на 15:00", add_appt(c, f.isoformat(), "15:00", "Ocupat Deja",
                                                          "069570099", doctor="d3").msg, "ok")
        before = _appts(s)
        chk = _check(c, blob, "programari.xlsx")
        res.check("колонки узнаны сами: дата, час, врач, процедура, длительность, комментарий записи",
                  chk["opts"]["cols"], {"0": "full", "1": "phone", "2": "appt", "3": "appt_time", "4": "doctor",
                                        "5": "appt_svc", "6": "appt_dur", "7": "appt_note"})
        res.check("умолчания: прошлые — в историю, SMS выключены, процедура — первая услуга агенды",
                  (chk["opts"]["past"], chk["opts"]["sms"], chk["opts"]["svc"],
                   [x["id"] for x in chk["services"]][:2]), (True, False, "consult", ["consult", "pain"]))
        vis = chk["visits"]
        res.check("предпросмотр визитов: новые, история, не ставятся",
                  {g["id"]: g["count"] for g in vis["groups"]}, {"v_new": 5, "v_past": 3, "v_no": 7})
        why_ = {r["line"]: r["reason"] for g in vis["groups"] for r in g["rows"]}
        res.check("почему не ставится — словами, у каждой строки своя причина",
                  {ln: why_[ln] for ln in (3, 4, 6, 9, 10, 13, 14)},
                  {3: "ocupat — rândul 2 are programare la același medic în acest timp",
                   4: "programare fără oră — data trecută în notițe",
                   6: "medic necunoscut („Popescu”) — data și medicul trecute în notițe",
                   9: "medic inactiv în clinică",
                   10: "în afara programului clinicii",
                   13: "ocupat — medicul are altă programare în acest timp",
                   14: "ora necitită („25:00”) — data trecută în notițe"})
        rows = {r["line"]: r for g in vis["groups"] for r in g["rows"]}
        res.check("строка-дубль несёт визит в фишу первой строки; существующая фиша — названа",
                  (rows[7]["notes"][:1], rows[11]["notes"][:1]),
                  (["programarea se adaugă la fișa din rândul 2"],
                   ["programarea se adaugă la fișa existentă: Exist Ana"]))
        res.check("округление к сетке и чужая процедура — пометками строки",
                  (rows[8]["when"], rows[8]["service"], rows[8]["notes"]),
                  (f"{_dmy(f)} 09:05", "Consultație",
                   ["ora din fișier rotunjită la grila de 5 minute: 09:07–09:50 › 09:05",
                    "procedura „Detartraj” nu este în lista clinicii — programare cu procedura aleasă"]))
        res.check("проверка ничего не записала", (_appts(s), _total(c)), (before, 2))

        run = _run_all(c, blob, "programari.xlsx")
        last = run["last"]["data"]
        res.check("импорт: визиты поставлены, прошлые в истории, остальные названы; «Rechemări» посчитаны",
                  (run["total"]["created"], last["visits"], last["visits_past"], last["visits_skipped"],
                   run["total"]["visits"], run["total"]["visits_skipped"], last["recall"]),
                  (13, 8, 3, 7, 8, 7, 1))
        got = _appts(s)
        res.check("будущий визит — programată у врача из файла, услуга по названию, комментарий записи, "
                  "без SMS",
                  got["Vizita Unu"], [(f, "09:00", "confirmed", "d2", "consult", 60, "adus de fiică", True, 1),
                                      (f + dt.timedelta(days=1), "10:00", "confirmed", "d2", "long", 120, "",
                                       True, 1)])
        res.check("прошлый — finalizată (история), услуга со сроком",
                  [x[:5] for x in got["Vizita Patru"]], [(p, "10:00", "done", "d3", "hygiene")])
        res.check("история не проверяет часы клиники и «врач выключен»: визит уже был, график и врачи сменились; "
                  "будущее до часов клиники и у врача в архиве — по-прежнему нет",
                  ([x[:4] for x in got.get("Istoric Devreme", [])], [x[:4] for x in got.get("Istoric Arhivat", [])],
                   "Vizita Opt" in got, "Vizita Sapte" in got),
                  ([(p, "06:00", "done", "d2")], [(p, "11:00", "done", "d1")], False, False))
        res.check("округлённый час: начало к сетке, длина из диапазона вверх, исходный час — в комментарии",
                  [x[1:7] for x in got["Vizita Sase"]],
                  [("09:05", "confirmed", "d4", "consult", 45,
                    "Fișier: 09:07–09:50; Procedură în fișier: Detartraj")])
        res.check("длительность из колонки «Durata» (1:30 = 90 минут)",
                  [x[5] for x in got["Vizita Noua"]], [90])
        res.check("существующей фише — визит, ничего больше",
                  ([x[:3] for x in got["Exist Ana"]], _card(c, _find(c, "Exist Ana")[0]["id"])["profile"]["notes"]),
                  ([(f, "12:00", "confirmed")], ""))
        res.ok("не поставлено ничего лишнего: ни у врача в архиве, ни до часов клиники, ни поверх занятого",
               not ({"Vizita Doi", "Vizita Trei", "Vizita Cinci", "Vizita Sapte", "Vizita Opt", "Vizita Zece",
                     "Vizita Unsprezece"} & set(got)) and got["Ocupat Deja"] == before["Ocupat Deja"],
               repr(sorted(got)))
        notes = {n: _card(c, _find(c, n)[0]["id"])["profile"]["notes"]
                 for n in ("Vizita Doi", "Vizita Trei", "Vizita Cinci", "Vizita Opt")}
        res.check("визит не встал — дата в заметках фиши (и при отказе в момент записи)", notes,
                  {"Vizita Doi": f"Programare în fișier: {_dmy(f)} 09:30",
                   "Vizita Trei": f"Programare în fișier: {_dmy(f)}",
                   "Vizita Cinci": f"Medic: Popescu; Programare în fișier: {_dmy(f)} 11:00",
                   "Vizita Opt": f"Programare în fișier: {_dmy(f)} 06:00"})
        pid4 = _find(c, "Vizita Patru")[0]["id"]
        res.check("летопись фиши с историей: заведена, визит, finalizată", _lines(c, pid4)[::-1],
                  ["Fișă creată prin import din fișier „programari.xlsx”",
                   f"Programare: Igienizare · Dr. Activ Trei · {_dmy(p)} 10:00", "Vizită finalizată: Igienizare"])
        rec = _j(c.get("/api/recall"))["data"]
        res.ok("«Rechemări»: пациент с прошлой гигиеной — в списке",
               any(r["name"] == "Vizita Patru" and r["tab"] == "due" for r in rec["rows"]), repr(rec["rows"][:3]))

        rep = _send(c, "report", blob, "programari.xlsx", **{"import": run["id"]})
        text = _sheet_text(rep.raw)
        res.check("отчёт после импорта: колонка «Programare»; поставленные (строки с пометкой) — этим импортом, "
                  "не «у пациента уже есть запись»",
                  (text.count(">Programare<"), text.count("programată: "), text.count("pacientul are deja")),
                  (1, 2, 0))
        res.check("отчёт: в книге только строки с пометкой, и визит каждой назван",
                  text.count("nu s-a programat: "), 7)

        again = _check(c, blob, "programari.xlsx")
        res.check("тот же файл ещё раз — визитов не прибавится: у пациента уже есть запись",
                  {g["id"]: g["count"] for g in again["visits"]["groups"]}, {"v_new": 0, "v_past": 0, "v_no": 15})
        rerun = _run_all(c, blob, "programari.xlsx")
        res.check("повтор: ни фиш, ни визитов; в списке импортов не остаётся",
                  (rerun["total"]["created"], rerun["last"]["data"]["visits"], len(_appts(s)["Vizita Unu"]),
                   len(_j(c.get("/api/pimport"))["data"]["imports"])), (0, 0, 2, 1))

        # трогаем визит «Vizita Noua» — отмена его не снимет, и фиша останется
        aid = _db_rows(s, "SELECT a.id FROM appointments a JOIN patients p ON p.id = a.patient_id "
                          "WHERE p.name = 'Vizita Noua'")[0]["id"]
        r = c.post_json(f"/api/schedule/appointments/{aid}/comment?date={f.isoformat()}", {"comment": "sunat"})
        res.check("регистратура поменяла комментарий визита из файла", r.msg, "ok_comment")
        und = _undo(c, run["id"])
        res.check("отмена: визиты сняты, кроме тронутого; фиши — кроме той, где визит остался",
                  (und["code"], und["sum"]["visits_removed"], und["sum"]["removed"], und["data"]["kept"],
                   und["data"]["visits_kept"]), ("pi_undone", 7, 12, 1, 1))
        left = _appts(s)
        res.check("после отмены: руками заведённое и тронутое — на месте",
                  sorted(left), ["Ocupat Deja", "Vizita Noua"])
        res.check("существующая фиша осталась, её визит из файла снят",
                  (len(_find(c, "Exist Ana")), "Exist Ana" in left), (1, False))
        imp = _j(c.get("/api/pimport"))["data"]["imports"][0]
        res.check("запись об импорте: счётчики визитов",
                  (imp["visits"], imp["visits_past"], imp["visits_skipped"], imp["visits_removed"], imp["undone"]),
                  (8, 3, 7, 7, True))

    # без галочки «Importă și vizitele trecute» прошлое — в заметки, будущее ставится
    with Server() as s:
        c = Client(s.url).login()
        chk = _check(c, blob, "programari.xlsx", {"past": False})
        res.check("прошлые выключены: строка с прошлым визитом не ставится и сказано почему",
                  next(r["reason"] for g in chk["visits"]["groups"] for r in g["rows"] if r["line"] == 5),
                  "vizită trecută — neimportată (bifa „Importă și vizitele trecute”)")
        run = _run_all(c, blob, "programari.xlsx", {"past": False, "sms": True, "svc": "pain"})
        got = _appts(s)
        res.check("прошлого визита нет, дата в заметках",
                  ("Vizita Patru" in got, _card(c, _find(c, "Vizita Patru")[0]["id"])["profile"]["notes"]),
                  (False, f"Programare în fișier: {_dmy(p)} 10:00, Igienizare"))
        res.check("SMS включены галочкой — визиты без пометки «без SMS»; процедура по умолчанию — выбранная",
                  ([x[8] for x in got["Vizita Unu"]], [x[4] for x in got["Vizita Sase"]]), ([0, 0], ["pain"]))
        res.ok("отпечаток выбора: смена галочки SMS — другой отпечаток",
               _check(c, blob, "programari.xlsx", {"past": False, "sms": True})["token"] != chk["token"])

    # будущий визит в Excel числом: дата-время одной ячейкой и час отдельной ячейкой формата времени
    when1 = dt.datetime.combine(f, dt.time(14, 0))
    timed = S.timed_book([["Nume", "Telefon", "Data programării", "Ora", "Medic"],
                          ["Excel Unu", "069570021", (6, when1), None, "Activ Doi"],
                          ["Excel Doi", "069570022", (1, f), (4, dt.time(16, 30)), "Activ Doi"],
                          ["Excel Trei", "069570023", (1, f), None, "Activ Doi"]])
    with Server() as s:
        c = Client(s.url).login()
        chk = _check(c, timed, "excel.xlsx")
        res.check("ячейки Excel: дата-время, дата + время, дата без часа",
                  [(r["line"], r["when"], r["reason"]) for g in chk["visits"]["groups"] for r in g["rows"]],
                  [(2, f"{_dmy(f)} 14:00", ""), (3, f"{_dmy(f)} 16:30", ""),
                   (4, _dmy(f), "programare fără oră — data trecută în notițe")])
        _run_all(c, timed, "excel.xlsx")
        res.check("поставлены по стенным часам клиники",
                  {n: [x[1] for x in v] for n, v in _appts(s).items()},
                  {"Excel Unu": ["14:00"], "Excel Doi": ["16:30"]})


def suite_visit_sms(res: Result) -> None:
    """SMS-напоминание: визит из файла без галочки SMS цикл обходит, визит с галочкой, записанный руками и
    перенесённый регистратурой руками — получают. Живой цикл SMS под поддельными часами, сервер лицензий — стенд `test_sms`."""
    import test_sms as ts
    from harness import Clock
    stand = ts.Stand()
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_pisms_"))
    fri, mon = (2026, 11, 6), dt.date(2026, 11, 9)
    try:
        ts._clinic_weekdays(d)
        (d / "license.json").write_text(ts.lr._file(5, {"url": stand.url, "token": ts.TOKEN}), encoding="utf-8")
        with Clock(ts._at(*fri, 9, 0)) as clock:
            with Server(dir_=d, env={**ts.KEY_ENV, **ts.TICK}) as s:
                c = Client(s.url).login()
                M = _dmy(mon)
                off = S.library_book(VIS_HEAD[:5], [["Sms Fisier Unu", "069580001", M, "12:00", "Activ Doi"],
                                                    ["Sms Fisier Trei", "069580004", M, "15:00", "Activ Doi"]])
                on = S.library_book(VIS_HEAD[:5], [["Sms Fisier Doi", "069580002", M, "13:00", "Activ Doi"]])
                chk = _check(c, off, "fara-sms.xlsx")
                res.check("пакет SMS работает: галочка видна, по умолчанию выключена",
                          (chk["sms_on"], chk["opts"]["sms"]), (True, False))
                _run_all(c, off, "fara-sms.xlsx")
                _run_all(c, on, "cu-sms.xlsx", {"sms": True})
                res.check("визит руками", add_appt(c, mon.isoformat(), "14:00", "Sms Manual", "069580003").msg, "ok")
                aid = ts._rows(d, "SELECT a.id FROM appointments a JOIN patients p ON p.id = a.patient_id "
                                  "WHERE p.name = 'Sms Fisier Trei'")[0]["id"]
                r = c.post_json(f"/api/schedule/appointments/{aid}/move?date={mon.isoformat()}",
                                {"date": mon.isoformat(), "time": "16:00", "doctor": "d2"})
                res.check("регистратура перенесла визит из файла руками", r.msg, "ok_move")
                res.check("перенос снял пометку «без SMS» только у перенесённого",
                          [(x["name"], x["sms_skip"]) for x in ts._rows(
                              d, "SELECT p.name, a.sms_skip FROM appointments a JOIN patients p ON p.id = a.patient_id "
                                 "WHERE p.name LIKE 'Sms Fisier%' ORDER BY p.name")],
                          [("Sms Fisier Doi", 0), ("Sms Fisier Trei", 0), ("Sms Fisier Unu", 1)])
                clock.set(ts._at(*fri, 10, 0, 30))
                ts._wait(lambda: len(stand.sends) >= 3)
                time.sleep(1.5)
                to = sorted(x["json"].get("to") for x in stand.sends)
                res.check("напоминание ушло визиту с галочкой, визиту руками и перенесённому руками визиту из файла; "
                          "визиту из файла без галочки — нет",
                          to, ["69580002", "69580003", "69580004"])
                res.check("и строки очереди у него нет",
                          [r["phone"] for r in ts._sms_log(d) if r["phone"].endswith("580001")], [])
    finally:
        stand.close()
        _rmtree_settled(d)


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
