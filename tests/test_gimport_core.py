"""Конвертер импорта (`app/core/gimport.py`): готовое событие -> заготовка
строки. Сервер не поднимается; образцы и их даты «от сейчас» — те же, что у
test_ics (там же объяснено, почему образцы — шаблоны).
"""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import test_ics as t
from harness import BOT, Result

sys.path.insert(0, str(BOT))
from app.core import gimport as gi  # noqa: E402
from app.core import ics  # noqa: E402

MODULE = BOT / "app" / "core" / "gimport.py"
TZ = t.TZ
ALLOWED_IMPORTS = {"__future__", "hashlib", "re", "unicodedata", "dataclasses", "datetime"}
DOCTORS = {"d1": "Dr. Andrei Munteanu", "d2": "Dr. Elena Rusu", "d3": "Dr. Ștefan Țurcanu"}


def drafts(name: str, now: datetime, text: str | None = None, **kw) -> dict:
    raw = t.fold75(text if text is not None else t.render(name, now))
    (cal,) = ics.read(raw, TZ)
    out = gi.convert_all(ics.occurrences(cal, *t.window(now)), tz=TZ, now=now, doctors=DOCTORS, **kw)
    return {d.key.replace("@google.com", ""): d for d in out}


def occ(start: datetime | None, minutes: int = 30, title: str = "", **kw) -> ics.Occurrence:
    return ics.Occurrence(key=kw.pop("key", "k1"), start=start, minutes=minutes, title=title, **kw)


def suite_samples(res: Result) -> None:
    res.check("образцы нашлись", [n for n in t.TEMPLATES if (t.FIX / f"{n}.ics.tpl").is_file()],
              list(t.TEMPLATES))
    for now in t.nows():
        _basic(res, now)
        _shared(res, now)
        _again(res, now)


def _basic(res: Result, now: datetime) -> None:
    tag = f"[{now:%d.%m.%Y %H:%M}]"
    d = drafts("basic", now)
    kinds = {k: [n for n, x in d.items() if x.kind == k] for k in gi.KINDS}
    res.ok(f"{tag} годных строк не ноль", len(kinds[gi.OK]) > 0)
    res.check(f"{tag} годные", sorted(kinds[gi.OK], key=lambda n: int(n[1:])),
              ["a1", "a2", "a3", "a7", "a8", "a9", "a11", "a12", "a13"])
    res.check(f"{tag} пропущенные — с причиной",
              sorted((n, d[n].why) for n in kinds[gi.SKIPPED]),
              [("a4", gi.ALL_DAY), ("a5", gi.CANCELLED), ("a6", gi.PAST)])
    res.check(f"{tag} не разобранные — с причиной и названием",
              [(n, d[n].why, d[n].detail, d[n].title) for n in kinds[gi.UNPARSED]],
              [("a10", ics.UNKNOWN_TZ, "Mars/Olympus", "Pojar cu fus necunoscut")])
    res.check(f"{tag} 9:10 на 20 минут ложится как есть",
              (d["a1"].start, d["a1"].minutes, d["a1"].rounded, d["a1"].check),
              (t.at(now, 0, 9, 10), 20, False, ""))
    d0 = t.day(now, 0)
    utc = datetime(d0.year, d0.month, d0.day, 12, 0, tzinfo=timezone.utc)
    res.check(f"{tag} событие в UTC — в поясе клиники",
              (d["a2"].start, str(d["a2"].start.tzinfo), d["a2"].start.hour, d["a2"].minutes),
              (utc, "Europe/Chisinau", 12 + int(utc.astimezone(TZ).utcoffset().total_seconds() // 3600), 50))
    d4 = t.day(now, 4)
    ny = datetime(d4.year, d4.month, d4.day, 3, 0, tzinfo=ZoneInfo("America/New_York"))
    res.check(f"{tag} событие из чужого пояса — тот же момент по часам клиники",
              (d["a8"].start, str(d["a8"].start.tzinfo)), (ny, "Europe/Chisinau"))
    res.ok(f"{tag} по Кишинёву это 9:00–10:00 (разница с Нью-Йорком 6–7 часов)", d["a8"].start.hour in (9, 10))
    res.check(f"{tag} телефоны — в одном виде, из названия и описания",
              [d[n].phones for n in ("a1", "a2", "a3", "a8")],
              [("69123456",), ("79555123",), ("79111222", "68222333"), ("78444555",)])
    res.check(f"{tag} дата рождения и сумма — не телефон", d["a12"].phones, ())
    res.check(f"{tag} врач, названный со словом «dr»", (d["a2"].doctor, d["a2"].doctor_hits), ("d2", ("d2",)))
    res.check(f"{tag} пациент — тёзка врача по фамилии («Țurcan» не «Țurcanu») подсказки не даёт",
              (d["a13"].doctor, d["a13"].doctor_hits), ("", ()))
    res.check(f"{tag} имя пациента — заготовка: услуга прилипает, врач и цифры убраны",
              [d[n].patient for n in ("a1", "a2", "a3", "a7")],
              ["Popescu Ion consult", "Bălan Ștefăniță", "Иванова Мария имплант", "Ceban Ana control"])
    res.check(f"{tag} место и участники доходят до заготовки", (d["a7"].location, d["a7"].attendees),
              ("Cabinet 2", (("Rusu, Elena", "elena.rusu@example.com"),)))
    res.check(f"{tag} суточное событие — «проверить», не отказ", (d["a11"].kind, d["a11"].check),
              (gi.OK, gi.CHECK_LONG))
    res.check(f"{tag} округление 9:07–9:30 -> 9:05, 25 минут; исходное сохранено",
              (d["a13"].start, d["a13"].minutes, d["a13"].rounded, d["a13"].src_start, d["a13"].src_minutes),
              (t.at(now, 8, 9, 5), 25, True, t.at(now, 8, 9, 7), 23))
    res.check(f"{tag} с округлением — ровно одна строка",
              [n for n in kinds[gi.OK] if d[n].rounded], ["a13"])
    res.check(f"{tag} период: позже конца — «пропущено», не потеря",
              sorted(n for n, x in drafts("basic", now, until=t.at(now, 4, 0)).items() if x.why == gi.BEYOND),
              ["a11", "a12", "a13", "a8", "a9"])
    starts = [x.start for x in d.values() if x.start]
    res.check(f"{tag} заготовки идут по времени", starts, sorted(starts))


def _shared(res: Result, now: datetime) -> None:
    tag = f"[{now:%d.%m.%Y %H:%M}]"
    d = drafts("shared", now)
    res.check(f"{tag} общий календарь: врач по строке названия",
              [(n, d[n].doctor, d[n].doctor_hits) for n in ("c1", "c2", "c3", "c4", "c5")],
              [("c1", "d2", ("d2",)), ("c2", "d2", ("d2",)), ("c3", "d1", ("d1",)),
               ("c4", "", ("d1", "d3")), ("c5", "", ())])
    res.check(f"{tag} общий календарь: заготовки имён",
              [d[n].patient for n in ("c1", "c3", "c4", "c5")],
              ["Popa Vasile", "Lungu Elena", "turcanu Andrei Munteanu jr", "Sandu Maria extracție"])
    rows = [(n, x.doctor, x.start, x.minutes) for n, x in d.items()]
    res.check(f"{tag} пересечение у одного врача найдено до записи", gi.overlaps(rows), [("c1", "c2")])


def _again(res: Result, now: datetime) -> None:
    tag = f"[{now:%d.%m.%Y %H:%M}]"
    first = drafts("basic", now)
    stored = {x.key: x.stamp for x in first.values() if x.kind == gi.OK}
    res.check(f"{tag} тот же файл второй раз — всё «уже есть»",
              set(gi.compare(first.values(), stored).values()), {gi.SAME})
    d0, d9 = f"{t.day(now, 0):%Y%m%d}", f"{t.day(now, 9):%Y%m%d}"
    text = t.render("basic", now)
    v2 = (text.replace(f"{d0}T091000", f"{d0}T094000").replace(f"{d0}T093000", f"{d0}T100000")
          .replace("Ceban\\, Ana\\; control", "Ceban Ana control + detartraj")
          .replace("END:VCALENDAR", "BEGIN:VEVENT\nUID:a14@google.com\n"
                   f"DTSTART;TZID=Europe/Chisinau:{d9}T100000\nDTEND;TZID=Europe/Chisinau:{d9}T103000\n"
                   "SUMMARY:Nou venit 069000999\nEND:VEVENT\nEND:VCALENDAR"))
    res.ok(f"{tag} второй файл отличается от первого", v2 != text)
    got = gi.compare(drafts("basic", now, text=v2).values(), stored)
    marks = {m: sorted(k.split("@")[0] for k, v in got.items() if v == m) for m in (gi.NEW, gi.CHANGED, gi.SAME)}
    res.check(f"{tag} изменённый файл: перенос и новое название — «изменилась», добавленное — «новая»",
              marks, {gi.NEW: ["a14"], gi.CHANGED: ["a1", "a7"],
                      gi.SAME: ["a11", "a12", "a13", "a2", "a3", "a8", "a9"]})
    res.check(f"{tag} округлённое событие второй раз — «уже есть»: отпечаток от значений файла",
              got["a13@google.com"], gi.SAME)

    series = t.render("series", now)
    before = {x.key: x.stamp for x in drafts("series", now).values() if x.kind == gi.OK}
    s2 = sorted(k for k in before if k.startswith("s2@"))
    res.check(f"{tag} серия «через день» дала пять ключей", len(s2), 5)
    shifted = series.replace(f"{d0}T083000", f"{d0}T093000").replace(f"{d0}T090000", f"{d0}T100000")
    res.ok(f"{tag} сдвиг серии применился к образцу", shifted != series)
    got = gi.compare(drafts("series", now, text=shifted).values(), before)
    res.check(f"{tag} сдвиг всей серии на час: ключ по дате даёт «изменилась», не «новая»",
              ([got[k] for k in s2], gi.NEW in got.values()), ([gi.CHANGED] * 5, False))
    res.check(f"{tag} после сдвига серии ключи те же — висящих и лишних нет", set(got), set(before))
    d1, d8 = f"{t.day(now, 1):%Y%m%d}", f"{t.day(now, 8):%Y%m%d}"
    key8 = f"s1@google.com|{d8}"
    plain_series = series.replace(f"RECURRENCE-ID;TZID=Europe/Chisinau:{d8}T150000", "RECURRENCE-ID:20000101T000000Z")
    once = {x.key: x.stamp for x in drafts("series", now, text=plain_series).values() if x.kind == gi.OK}
    res.ok(f"{tag} до переноса вхождение стояло своим ключом", key8 in once and f"s1@google.com|{d1}" in once)
    res.check(f"{tag} одно вхождение перенесли на другой день: тот же ключ, «изменилась»",
              gi.compare(drafts("series", now).values(), once)[key8], gi.CHANGED)


NOW = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)


def _at(h: int, m: int = 0, day: int = 16) -> datetime:
    return datetime(2026, 11, day, h, m, tzinfo=TZ)


def suite_rules(res: Result) -> None:
    def conv(o, **kw):
        return gi.convert(o, tz=TZ, now=NOW, doctors=DOCTORS, **kw)

    rounding = [
        ("9:07–9:30 -> 9:05, 25 минут", (9, 7), 23, (9, 5), 25, True),
        ("9:10–9:30 как есть", (9, 10), 20, (9, 10), 20, False),
        ("9:00 на 23 минуты -> 25", (9, 0), 23, (9, 0), 25, True),
        ("11:08 на 30 минут -> 11:10, длина та же", (11, 8), 30, (11, 10), 30, True),
        ("11:07 на 30 минут -> 11:05, длина та же", (11, 7), 30, (11, 5), 30, True),
        ("11:12 -> 11:10", (11, 12), 30, (11, 10), 30, True),
        ("11:13 -> 11:15", (11, 13), 30, (11, 15), 30, True),
        ("11:11 -> 11:10", (11, 11), 45, (11, 10), 45, True),
        ("11:14 -> 11:15", (11, 14), 45, (11, 15), 45, True),
        ("9:58 на 3 минуты -> 10:00, 5 минут", (9, 58), 3, (10, 0), 5, True),
        ("9:03 на 1 минуту -> 9:05, 5 минут", (9, 3), 1, (9, 5), 5, True),
        ("9:05 на 5 минут как есть", (9, 5), 5, (9, 5), 5, False),
        ("9:00 на 236 минут -> 240, без пометки", (9, 0), 236, (9, 0), 240, True),
        ("ровно 240 минут — без пометки", (9, 0), 240, (9, 0), 240, False),
    ]
    res.ok("таблица округления не пуста", len(rounding) >= 10)
    d = conv(occ(_at(23, 58), 30))
    res.check("23:58 -> полночь следующего дня", (d.start, d.minutes), (_at(0, 0, day=17), 30))
    for label, (h, m), mins, (wh, wm), wmin, wr in rounding:
        d = conv(occ(_at(h, m), mins))
        res.check(f"округление: {label}", (d.start, d.minutes, d.rounded, d.check, d.kind),
                  (_at(wh, wm), wmin, wr, "", gi.OK))
        res.ok(f"округление: {label} — сдвиг начала не больше двух минут, визит не короче, исходное на месте",
               abs(d.start - d.src_start) <= timedelta(minutes=2) and 0 <= d.minutes - mins < 5
               and (d.src_start, d.src_minutes) == (_at(h, m), mins))
    d = conv(occ(_at(9), 241))
    res.check("241 минута -> 245 и «проверить»", (d.minutes, d.check, d.kind), (245, gi.CHECK_LONG, gi.OK))
    d = conv(occ(_at(9), 0))
    res.check("событие без длительности: 5 минут и «проверить»", (d.minutes, d.check, d.rounded),
              (5, gi.CHECK_NONE, False))
    d = conv(occ(_at(9, 7), -30))
    res.check("конец раньше начала: «проверить», старт округлён", (d.start, d.minutes, d.check),
              (_at(9, 5), 5, gi.CHECK_NONE))
    spring = datetime(2027, 3, 28, 2, 37, tzinfo=TZ)
    d = gi.convert(occ(spring, 50), tz=TZ, now=NOW, doctors={})
    res.check("округление в ночь перевода часов не теряет час",
              (d.start.astimezone(timezone.utc), d.minutes),
              (datetime(2027, 3, 28, 0, 35, tzinfo=timezone.utc), 50))
    summer = datetime(2027, 7, 5, 6, 0, tzinfo=timezone.utc)
    d = gi.convert(occ(summer, 30), tz=TZ, now=NOW, doctors={})
    res.check("лето: 06:00 UTC — это 9:00 клиники", (d.start.hour, d.start.utcoffset()), (9, timedelta(hours=3)))

    res.check("старт ровно «сейчас» — прошлое", conv(occ(NOW)).why, gi.PAST)
    res.check("старт через минуту — годная", conv(occ(NOW + timedelta(minutes=1))).kind, gi.OK)
    skipped = conv(occ(NOW - timedelta(days=1), title="Vechi 069123456"))
    res.check("пропущенная: ни подсказок, ни отпечатка, название на месте",
              (skipped.kind, skipped.phones, skipped.stamp, skipped.title, skipped.start),
              (gi.SKIPPED, (), "", "Vechi 069123456", None))
    res.check("отменённая в прошлом — «отменена»", conv(occ(NOW - timedelta(days=1), status="CANCELLED")).why,
              gi.CANCELLED)
    res.check("статус из API строчными", conv(occ(_at(9), status="cancelled")).why, gi.CANCELLED)
    res.check("«весь день»", conv(ics.Occurrence(key="k", day=_at(9).date())).why, gi.ALL_DAY)
    none = conv(ics.Occurrence(key="k"))
    res.check("ни времени, ни дня — «не разобрано»", (none.kind, none.why), (gi.UNPARSED, ics.NO_START))
    bad = conv(occ(_at(9), title="Serie", problem=ics.RRULE_FREQ, detail="YEARLY", series=True))
    res.check("«не разобрано» несёт причину, название и время начала серии",
              (bad.kind, bad.why, bad.detail, bad.title, bad.src_start, bad.series),
              (gi.UNPARSED, ics.RRULE_FREQ, "YEARLY", "Serie", _at(9), True))
    res.check("конец периода включён", (conv(occ(_at(9)), until=_at(9)).kind, conv(occ(_at(9, 5)), until=_at(9)).why),
              (gi.OK, gi.BEYOND))
    res.check("коды причин названы и не пересекаются",
              len(set(gi.SKIPS) | set(ics.PROBLEMS)), len(gi.SKIPS) + len(ics.PROBLEMS))

    a, b = conv(occ(_at(9, 7), 23, "Popa Ion")), conv(occ(_at(9, 5), 25, "Popa Ion"))
    res.ok("отпечаток — от значений файла: 9:07/23′ и 9:05/25′ ложатся одинаково, а отпечатки разные",
           (a.start, a.minutes) == (b.start, b.minutes) and a.stamp != b.stamp)
    res.check("отпечаток: момент UTC, минуты, хеш названия — без самого названия",
              (a.stamp[:18], "Popa" in a.stamp, len(a.stamp)), ("20261116T0707Z|23|", False, 34))
    res.ok("отпечаток меняется от названия и не меняется от описания",
           a.stamp != conv(occ(_at(9, 7), 23, "Popa Ioan")).stamp
           and a.stamp == conv(occ(_at(9, 7), 23, "Popa Ion", description="alt text")).stamp)
    res.check("ключи: одиночное, вхождение серии", (gi.key("u@g"), gi.key("u@g", _at(9).date())),
              ("u@g", "u@g|20261116"))


PHONES = [
    ("069123456", ("69123456",)),
    ("69123456", ("69123456",)),
    ("+373 69 123 456", ("69123456",)),
    ("+37369123456", ("69123456",)),
    ("373 69 123 456", ("69123456",)),
    ("0037369123456", ("69123456",)),
    ("+373 0 69 123 456", ("69123456",)),
    ("079-111-222", ("79111222",)),
    ("(069) 12-34-56", ("69123456",)),
    ("069.123.456", ("69123456",)),
    ("tel:069123456.", ("69123456",)),
    ("022 123 456 fix", ("22123456",)),
    ("Popa 069123456 600 lei", ("69123456",)),
    ("Popa 069 123 456 600 lei", ("69123456",)),
    ("14 30 069123456", ("69123456",)),
    ("069123456 068222333", ("69123456", "68222333")),
    ("069123456, +373 69 123 456", ("69123456",)),
    ("Ion +40 721 123 456 Iași", ("+40721123456",)),
    ("n. 12.03.1985", ()),
    ("12/03/1985 069123456", ("69123456",)),
    ("069-12-34-56", ("69123456",)),
    ("069.12.03.85", ("69120385",)),
    ("n. 5.3.85, 079111222", ("79111222",)),
    ("2026-11-16 ora 09:30", ()),
    ("600 lei", ()),
    ("12 000 lei avans 5 000", ()),
    ("IDNP 2001234567890", ()),
    ("dinți 64 65 74 75", ()),
    ("40 721 123 456", ()),
    ("0691234567", ()),
    ("06912345", ()),
    ("12345678", ()),
    ("", ()),
]

DOCTOR = [
    ("Dr. Rusu: Popa Vasile", "d2", ("d2",)),
    ("Popa Vasile - dr Rusu", "d2", ("d2",)),
    ("RUSU / Popa Vasile", "d2", ("d2",)),
    ("Popa Vasile (Țurcanu)", "d3", ("d3",)),
    ("Popa Vasile (Turcanu)", "d3", ("d3",)),
    ("Popa Vasile (Ţurcanu)", "d3", ("d3",)),
    ("AM - Lungu Elena", "d1", ("d1",)),
    ("MA Lungu Elena", "d1", ("d1",)),
    ("Am venit cu Lungu Elena", "", ()),
    ("Lungu Elena AM", "", ()),
    ("Lungu Elena", "", ()),
    ("Lungu Andrei consult", "", ()),
    ("Munteanu Andrei jr / turcanu", "", ("d1", "d3")),
    ("Munteanu Ion - Dr. Rusu", "d2", ("d1", "d2")),
    ("Munteanu Ion - Dr. Elena Rusu", "d2", ("d1", "d2")),
    ("Dr Rusu Elena - Munteanu Ion", "d2", ("d1", "d2")),
    ("Dr . Vasilache - Moraru M - consult", "", ()),
    ("dr Rusu, dr Munteanu: consiliu", "", ("d1", "d2")),
    ("Rusufan Ion", "", ()),
    ("", "", ()),
]


def suite_hints(res: Result) -> None:
    res.ok("таблицы подсказок не пусты", len(PHONES) >= 25 and len(DOCTOR) >= 12)
    for text, want in PHONES:
        res.check(f"телефон в {text!r}", gi.phones(text), want)
    for title, want, hits in DOCTOR:
        res.check(f"врач в {title!r}", gi.doctor_hint(title, DOCTORS), (want, hits))
    res.check("две фамилии-тёзки среди врачей — подсказки нет",
              gi.doctor_hint("Dr. Rusu: Popa", {"a": "Dr. Elena Rusu", "b": "Dr. Ion Rusu"}), ("", ("a", "b")))
    res.check("врач без имени в списке не роняет подсказку", gi.doctor_hint("Popa", {"a": "", "b": "Dr."}), ("", ()))
    names = [
        ("Dr. Elena Rusu: Popa Vasile 068111222", "Popa Vasile"),
        ("AM - Lungu Elena 079000111", "Lungu Elena"),
        ("Popescu-Rusu Ana tel 069123456", "Popescu-Rusu Ana"),
        ("Rusu Ion", "Rusu Ion"),
        ("069123456", ""),
        ("unu doi trei patru cinci sase", "unu doi trei patru"),
    ]
    for title, want in names:
        res.check(f"заготовка имени из {title!r}", gi.patient_guess(title, DOCTORS), want)

    rows = [("a", "d1", _at(10), 60), ("b", "d1", _at(10, 30), 20), ("c", "d1", _at(11), 30),
            ("d", "d2", _at(10), 60), ("e", "", _at(10), 60), ("f", "d1", _at(10, 45), 30),
            ("g", "d2", None, 30)]
    res.check("пересечения: только внутри группы, касание концом не в счёт, без врача не сравнивается",
              sorted(gi.overlaps(rows)), [("a", "b"), ("a", "f"), ("b", "f"), ("f", "c")])
    res.check("пересечения не зависят от порядка строк", sorted(gi.overlaps(rows[::-1])),
              [("a", "b"), ("a", "f"), ("b", "f"), ("f", "c")])
    utc = datetime(2026, 11, 16, 8, 30, tzinfo=timezone.utc)
    res.check("пересечения считаются по моменту, а не по записи пояса",
              gi.overlaps([("a", "d1", _at(10), 60), ("b", "d1", utc, 20)]), [("a", "b")])
    res.check("пересечений нет — пусто", gi.overlaps([("a", "d1", _at(10), 30), ("b", "d1", _at(10, 30), 30)]), [])


def suite_pure(res: Result) -> None:
    t.pure(res, MODULE, ALLOWED_IMPORTS, {"ics"})
    res.check("шаг и потолок длительности — как у журнала", (gi.STEP, gi.MAX_MINUTES), (5, 240))
