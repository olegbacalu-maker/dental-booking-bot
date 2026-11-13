"""Чтение файла календаря (`app/core/ics.py`): сервер не поднимается.

Образцы `tests/fixtures/ics/*.tpl` — шаблоны: `{D3}` в них — дата «опорный
понедельник + 3 дня», а опорный понедельник считается от переданного «сейчас».
Жёсткие даты сгнили бы за неделю: все события ушли бы в прошлое, и проверки
вида «лишнего нет» позеленели бы на пустом списке. Поэтому наборы гоняют
образцы и от настоящего «сейчас», и от нескольких назначенных (по обе стороны
перевода часов), и первой проверкой требуют, что образцы нашлись.

Таблица правил повтора — наоборот, с буквальными датами: окно развёртки
приходит аргументом, и от сегодняшнего дня она не зависит.
"""
import ast
import io
import re
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from harness import BOT, ROOT, Result, clinic_now

sys.path.insert(0, str(BOT))
from app.core import ics  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "ics"
MODULE = BOT / "app" / "core" / "ics.py"
TZ = ZoneInfo("Europe/Chisinau")
ALLOWED_IMPORTS = {"__future__", "calendar", "html", "io", "re", "zipfile",
                   "dataclasses", "datetime", "zoneinfo"}
TEMPLATES = ("basic", "series", "shared")


# ---------- образцы ----------

def base_day(now: datetime) -> date:
    """Опорный понедельник: через одну-две недели от «сейчас» — дни недели
    образца не зависят от дня запуска."""
    d = now.astimezone(TZ).date()
    return d + timedelta(days=14 - d.weekday())


def day(now: datetime, n: int) -> date:
    return base_day(now) + timedelta(days=n)


def at(now: datetime, n: int, hour: int, minute: int = 0) -> datetime:
    d = day(now, n)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def render(name: str, now: datetime) -> str:
    text = (FIX / f"{name}.ics.tpl").read_text(encoding="utf-8")
    return re.sub(r"\{D(-?\d+)\}", lambda m: f"{day(now, int(m.group(1))):%Y%m%d}", text)


def fold75(text: str) -> bytes:
    """Перенос по 75 октетов с CRLF, как пишет Google, — нарочно режет
    кириллицу и диакритику посреди буквы."""
    out = []
    for line in text.strip("\n").split("\n"):
        b = line.encode("utf-8")
        chunks, rest = [b[:75]], b[75:]
        while rest:
            chunks.append(b" " + rest[:74])
            rest = rest[74:]
        out.append(b"\r\n".join(chunks))
    return b"\r\n".join(out) + b"\r\n"


def fold_chars(text: str) -> bytes:
    """Перенос по 75 ЗНАКОВ: так складывает сам Google — буквы целы, зато
    физическая строка с кириллицей вдвое длиннее 75 октетов."""
    out = []
    for line in text.strip("\n").split("\n"):
        out.append("\r\n ".join([line[:75]] + [line[i:i + 74] for i in range(75, len(line), 74)]))
    return ("\r\n".join(out) + "\r\n").encode("utf-8")


def sample(name: str, now: datetime) -> bytes:
    return fold75(render(name, now))


def window(now: datetime, days: int = 180) -> tuple[datetime, datetime]:
    return now, now + timedelta(days=days)


def nows() -> list[datetime]:
    """Настоящее «сейчас» и назначенные: зима, канун весеннего перевода, лето,
    канун осеннего перевода, полночь на стыке лет."""
    return [clinic_now(),
            datetime(2026, 11, 12, 10, 0, tzinfo=TZ),
            datetime(2027, 3, 19, 23, 30, tzinfo=TZ),
            datetime(2027, 7, 4, 8, 0, tzinfo=TZ),
            datetime(2027, 10, 22, 16, 0, tzinfo=TZ),
            datetime(2027, 12, 31, 23, 59, tzinfo=TZ)]


def refusal(fn) -> str:
    try:
        fn()
    except ics.Refused as ex:
        return ex.code
    return ""


def cal_of(*events: str, head: str = "X-WR-TIMEZONE:Europe/Chisinau") -> bytes:
    body = "".join(f"BEGIN:VEVENT\n{e}\nEND:VEVENT\n" for e in events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\n{head}\n{body}END:VCALENDAR\n".encode("utf-8")


def occs(raw: bytes, win_from: datetime, win_to: datetime) -> list:
    (cal,) = ics.read(raw, TZ)
    return ics.occurrences(cal, win_from, win_to)


# ---------- файл ----------

def suite_file(res: Result) -> None:
    found = [n for n in TEMPLATES if (FIX / f"{n}.ics.tpl").is_file()]
    res.check("образцы нашлись", found, list(TEMPLATES))
    res.ok("образец «не календарь» нашёлся", (FIX / "not-calendar.ics").is_file())
    for now in nows():
        _basic(res, now)
    _text_rules(res)
    _refusals(res)
    _zip(res)


def _basic(res: Result, now: datetime) -> None:
    tag = f"[{now:%d.%m.%Y %H:%M}]"
    raw = sample("basic", now)
    physical = raw.split(b"\r\n")
    res.ok(f"{tag} образец сложен по 75 октетов", max(len(ln) for ln in physical) <= 75)

    def broken(ln: bytes) -> bool:
        try:
            ln.decode("utf-8")
        except UnicodeDecodeError:
            return True
        return False

    res.ok(f"{tag} перенос режет букву пополам — иначе склейка по байтам не проверена",
           any(broken(ln) for ln in physical))
    (cal,) = ics.read(raw, TZ)
    res.check(f"{tag} имя и пояс календаря", (cal.name, str(cal.tz), cal.source, cal.refused),
              ("Clinica Zâmbet", "Europe/Chisinau", "", ""))
    res.check(f"{tag} событий в файле (правила VTIMEZONE событиями не стали)", len(cal.events), 13)
    got = {o.key.split("@")[0]: o for o in ics.occurrences(cal, *window(now))}
    res.check(f"{tag} готовых событий", sorted(got, key=lambda k: int(k[1:])),
              [f"a{i}" for i in range(1, 14)])
    a = got
    res.check(f"{tag} время с TZID — стенные часы пояса", (a["a1"].start, a["a1"].minutes),
              (at(now, 0, 9, 10), 20))
    res.check(f"{tag} статус и название", (a["a1"].status, a["a1"].title),
              ("CONFIRMED", "Popescu Ion 069123456 consult"))
    d0 = day(now, 0)
    res.check(f"{tag} время с Z — UTC", (a["a2"].start, a["a2"].minutes),
              (datetime(d0.year, d0.month, d0.day, 12, 0, tzinfo=timezone.utc), 50))
    res.check(f"{tag} диакритика названия собрана", a["a2"].title, "Bălan Ștefăniță - Dr. Rusu")
    res.check(f"{tag} описание-разметка стало текстом", a["a2"].description,
              "Pacient nou\ntel: +373 79 555 123\nvine cu radiografie, plătește cash")
    res.check(f"{tag} кириллица и экранированные запятые", a["a3"].title,
              "Иванова Мария, имплант, тел 079-111-222")
    res.check(f"{tag} длинное описание, разрезанное переносами, собрано целиком", a["a3"].description,
              "Очень длинное описание, которое Google перенесёт на несколько строк: пациентка "
              "просила перезвонить накануне, боится уколов; аллергия на лидокаин — уточнить у "
              "врача. Второй номер мужа 068 222 333.")
    res.check(f"{tag} «весь день» — дата без времени", (a["a4"].start, a["a4"].day, a["a4"].problem),
              (None, day(now, 2), ""))
    res.check(f"{tag} отменённое событие несёт статус", a["a5"].status, ics.CANCELLED)
    res.check(f"{tag} прошедшее одиночное событие отдаётся как есть", a["a6"].start, at(now, -30, 10))
    res.check(f"{tag} экранированные «,» и «;» названия; место", (a["a7"].title, a["a7"].location),
              ("Ceban, Ana; control", "Cabinet 2"))
    res.check(f"{tag} участник: имя в кавычках с запятой и адрес", a["a7"].attendees,
              (("Rusu, Elena", "elena.rusu@example.com"),))
    res.check(f"{tag} текст напоминания VALARM в описание не подмешан", a["a7"].description, "")
    res.check(f"{tag} посторонние поля (X-MICROSOFT-…, CLASS) событию не мешают", a["a7"].problem, "")
    by_chars = fold_chars(render("basic", now))
    res.ok(f"{tag} перенос по знакам длиннее 75 октетов",
           max(len(ln) for ln in by_chars.split(b"\r\n")) > 75)
    (cal2,) = ics.read(by_chars, TZ)
    res.check(f"{tag} перенос по знакам читается так же, как по октетам",
              ics.occurrences(cal2, *window(now)), list(got.values()))
    d4 = day(now, 4)
    ny = datetime(d4.year, d4.month, d4.day, 3, 0, tzinfo=ZoneInfo("America/New_York"))
    res.check(f"{tag} чужой пояс — тот же момент", (a["a8"].start, a["a8"].minutes), (ny, 60))
    res.check(f"{tag} событие без названия не теряется", (a["a9"].title, a["a9"].start, a["a9"].problem),
              ("", at(now, 4, 16), ""))
    res.check(f"{tag} незнакомый пояс — «не разобрано» с названием и причиной",
              (a["a10"].problem, a["a10"].detail, a["a10"].title, a["a10"].start),
              (ics.UNKNOWN_TZ, "Mars/Olympus", "Pojar cu fus necunoscut", None))
    res.ok(f"{tag} суточное событие — около 1440 минут", 1380 <= a["a11"].minutes <= 1500,
           str(a["a11"].minutes))
    res.check(f"{tag} DURATION вместо DTEND", (a["a12"].start, a["a12"].minutes), (at(now, 7, 9, 30), 45))
    res.check(f"{tag} некратное время читается как записано", (a["a13"].start, a["a13"].minutes),
              (at(now, 8, 9, 7), 23))
    res.check(f"{tag} одиночные события — не серия, ключ = UID",
              sorted({(o.series, o.moved, o.key == f"{k}@google.com") for k, o in a.items()}),
              [(False, False, True)])


def _text_rules(res: Result) -> None:
    res.check("экранирование TEXT", ics.untext(r"a\, b\; c\\d\ne\Nf"), "a, b; c\\d\ne\nf")
    res.check("строка: параметр в кавычках с двоеточием и точкой с запятой",
              ics.split_line('attendee;CN="Rusu; Elena: dr";ROLE=X:mailto:a@b.md'),
              ("ATTENDEE", {"CN": "Rusu; Elena: dr", "ROLE": "X"}, "mailto:a@b.md"))
    res.check("разметка в текст: перенос, теги, сущности, пустые строки",
              ics.plain("<p>Unu &amp; doi</p><br><br><ul><li>a&nbsp;b</li></ul><a href='x'>link</a>"),
              "Unu & doi\na b\nlink")
    win = (datetime(2026, 11, 12, 10, 0, tzinfo=TZ), datetime(2027, 5, 11, 10, 0, tzinfo=TZ))
    raw = cal_of("UID:f1\nDTSTART:20261116T090000\nDTEND:20261116T093000\nSUMMARY:Fara fus",
                 "UID:f2\nDTSTART:20261116T090059\nDURATION:PT1H30M15S\nSUMMARY:Secunde",
                 "UID:f3\nDTSTART:20261116T090000\nDURATION:P1D\nSUMMARY:O zi",
                 "UID:f4\nDTSTART:20261116T090000\nSUMMARY:Fara sfarsit",
                 head="X-WR-TIMEZONE:Europe/Bucharest")
    got = {o.key: o for o in occs(raw, *win)}
    res.check("время без пояса читается в поясе календаря (X-WR-TIMEZONE)",
              got["f1"].start, datetime(2026, 11, 16, 9, 0, tzinfo=ZoneInfo("Europe/Bucharest")))
    res.check("секунды отбрасываются", (got["f2"].start.second, got["f2"].minutes), (0, 90))
    res.check("DURATION в днях", got["f3"].minutes, 1440)
    res.check("ни DTEND, ни DURATION — ноль минут, событие на месте",
              (got["f4"].minutes, got["f4"].problem), (0, ""))
    raw = cal_of("UID:g1\nDTSTART:20261116T090000\nDTEND:20261116T093000\nSUMMARY:Fara fus", head="X-A:1")
    res.check("календарь без своего пояса — время без пояса в поясе клиники",
              occs(raw, *win)[0].start, datetime(2026, 11, 16, 9, 0, tzinfo=TZ))
    raw = cal_of("UID:h1\nDTSTART:20261116T090000\nDTEND:20261116T093000\nSUMMARY:Plutitor",
                 "UID:h2\nDTSTART:20261116T090000Z\nDTEND:20261116T093000Z\nSUMMARY:Cu Z",
                 head="X-WR-TIMEZONE:Mars/Olympus")
    got = {o.key: o for o in occs(raw, *win)}
    res.check("незнакомый пояс календаря: время без пояса — «не разобрано», с поясом — читается",
              (got["h1"].problem, got["h2"].problem, got["h2"].minutes), (ics.UNKNOWN_TZ, "", 30))
    bad = {
        "дата не читается": ("UID:b1\nDTSTART:2026-11-16 09:00\nSUMMARY:x", ics.BAD_DATE),
        "месяц 13": ("UID:b1\nDTSTART:20261316T090000Z\nSUMMARY:x", ics.BAD_DATE),
        "DURATION не читается": ("UID:b1\nDTSTART:20261116T090000Z\nDURATION:45M\nSUMMARY:x", ics.BAD_DURATION),
        "нет DTSTART": ("UID:b1\nSUMMARY:x", ics.NO_START),
        "нет UID": ("DTSTART:20261116T090000Z\nSUMMARY:x", ics.NO_UID),
        "строка без двоеточия": ("UID:b1\nDTSTART:20261116T090000Z\nSUMMARY x", ics.BAD_LINE),
        "DTSTART со временем, DTEND датой": (
            "UID:b1\nDTSTART:20261116T090000Z\nDTEND;VALUE=DATE:20261117\nSUMMARY:x", ics.BAD_DATE),
        "путь вместо пояса": ("UID:b1\nDTSTART;TZID=../../etc/passwd:20261116T090000\nSUMMARY:x", ics.UNKNOWN_TZ),
    }
    for label, (body, code) in bad.items():
        (one,) = occs(cal_of(body), *win)
        res.check(f"«не разобрано»: {label}", one.problem, code)
    two = occs(cal_of("UID:d1\nDTSTART:20261116T090000Z\nSUMMARY:unu",
                      "UID:d1\nDTSTART:20261117T090000Z\nSUMMARY:doi"), *win)
    res.check("второй VEVENT с тем же ключом — «не разобрано», первый цел",
              [(o.title, o.problem) for o in two], [("unu", ""), ("doi", ics.DUP_KEY)])
    res.check("у каждого кода «не разобрано» есть имя в PROBLEMS, и повторов нет",
              (len(ics.PROBLEMS), len(set(ics.PROBLEMS))), (15, 15))


def _refusals(res: Result) -> None:
    now = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)
    raw = sample("basic", now)
    res.check("не календарь (страница входа вместо файла) — отказ",
              refusal(lambda: ics.read((FIX / "not-calendar.ics").read_bytes(), TZ)), ics.NOT_CALENDAR)
    res.check("пустой файл — отказ", refusal(lambda: ics.read(b"", TZ)), ics.NOT_CALENDAR)
    latin = raw.replace("Bălan".encode("utf-8"), "Bălan".encode("cp1250"))
    res.ok("образец не в UTF-8 отличается от исходного", latin != raw)
    res.check("не UTF-8 — отказ файла целиком, не импорт с мусором",
              refusal(lambda: ics.read(latin, TZ)), ics.NOT_UTF8)
    res.check("UTF-8 с BOM читается", len(ics.read(b"\xef\xbb\xbf" + raw, TZ)[0].events), 13)
    res.check("одиночные LF вместо CRLF читаются",
              len(ics.read(raw.replace(b"\r\n", b"\n"), TZ)[0].events), 13)
    res.check("потолок размера файла", refusal(lambda: ics.read(raw, TZ, max_bytes=len(raw) - 1)), ics.TOO_BIG)
    res.check("ровно потолок размера — читается", refusal(lambda: ics.read(raw, TZ, max_bytes=len(raw))), "")
    res.check("потолок числа событий", refusal(lambda: ics.read(raw, TZ, max_events=12)), ics.TOO_MANY)
    res.check("ровно потолок числа событий — читается", refusal(lambda: ics.read(raw, TZ, max_events=13)), "")
    res.check("коды отказа файла названы в REFUSALS",
              sorted(ics.REFUSALS), sorted({ics.NOT_CALENDAR, ics.NOT_UTF8, ics.TOO_BIG, ics.TOO_MANY,
                                            ics.BAD_ZIP, ics.ZIP_EMPTY}))


def _zipped(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _zip(res: Result) -> None:
    now = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)
    basic, series = sample("basic", now), sample("series", now)
    cals = ics.read(_zipped({"clinica.ics": basic, "orto/ortodontie.ics": series,
                             "citeste.txt": "nu e calendar", "__MACOSX/._clinica.ics": b"\x00\x05"}), TZ)
    res.check("архив: два календаря, посторонние файлы пропущены",
              [(c.source, c.name, len(c.events), c.refused) for c in cals],
              [("clinica.ics", "Clinica Zâmbet", 13, ""), ("orto/ortodontie.ics", "Ortodonție", 10, "")])
    cals = ics.read(_zipped({"bun.ics": basic, "stricat.ics": b"<html>"}), TZ)
    res.check("архив: календарь, который не читается, назван с причиной, остальные целы",
              [(c.source, c.refused) for c in cals], [("bun.ics", ""), ("stricat.ics", ics.NOT_CALENDAR)])
    res.check("архив, где не читается ни один календарь, — отказ",
              refusal(lambda: ics.read(_zipped({"a.ics": b"<html>", "b.ics": b"x"}), TZ)), ics.NOT_CALENDAR)
    res.check("архив без .ics — отказ", refusal(lambda: ics.read(_zipped({"a.txt": "x"}), TZ)), ics.ZIP_EMPTY)
    res.check("обрывок архива — отказ", refusal(lambda: ics.read(_zipped({"a.ics": basic})[:60], TZ)), ics.BAD_ZIP)
    # Бомба: килобайтный архив с заявленным размером больше потолка. Отказ
    # обязан прийти по оглавлению — чтение содержимого здесь запрещено.
    bomb = _zipped({"mare.ics": b"BEGIN:VCALENDAR\n" + b"X-A:" + b"0" * 400_000 + b"\nEND:VCALENDAR\n"})
    res.ok("бомба сжата в сотни раз", len(bomb) < 4000, str(len(bomb)))
    opened = []
    real_open = zipfile.ZipFile.open

    def spy(self, *a, **kw):
        opened.append(a[0] if a else kw.get("name"))
        return real_open(self, *a, **kw)

    zipfile.ZipFile.open = spy
    try:
        code = refusal(lambda: ics.read(bomb, TZ, max_bytes=50_000))
        res.check("архив: потолок по заявленному размеру, до распаковки", (code, opened), (ics.TOO_BIG, []))
        opened.clear()
        code = refusal(lambda: ics.read(bomb, TZ, max_bytes=500_000))
        res.check("архив в пределах потолка распаковывается", (code, len(opened)), ("", 1))
    finally:
        zipfile.ZipFile.open = real_open
    big = b"BEGIN:VCALENDAR\n" + b"X-A:" + b"0" * 400_000 + b"\nEND:VCALENDAR\n"
    five = _zipped({f"c{i}.ics": big for i in range(5)})
    zipfile.ZipFile.open = spy
    try:
        opened.clear()
        code = refusal(lambda: ics.read(five, TZ, max_bytes=450_000))
        res.check("архив: каждый календарь под потолком, вместе — больше; отказ до распаковки",
                  (code, opened), (ics.TOO_BIG, []))
    finally:
        zipfile.ZipFile.open = real_open
    many = _zipped({f"c{i}.ics": b"BEGIN:VCALENDAR\nEND:VCALENDAR\n" for i in range(ics.ZIP_CALENDARS + 1)})
    res.check("архив: потолок числа календарей", refusal(lambda: ics.read(many, TZ)), ics.TOO_BIG)


# ---------- правила повтора: буквальные даты ----------

WIN = (datetime(2026, 11, 12, 10, 0, tzinfo=TZ), datetime(2027, 5, 11, 10, 0, tzinfo=TZ))

# (что проверяется, DTSTART по Кишинёву, правило, ожидаемые дни по порядку)
RRULES = [
    ("через день, пять раз", "20261116T083000", "FREQ=DAILY;INTERVAL=2;COUNT=5",
     ["2026-11-16", "2026-11-18", "2026-11-20", "2026-11-22", "2026-11-24"]),
    ("COUNT считает от начала серии, не от окна", "20261110T150000", "FREQ=DAILY;COUNT=3",
     ["2026-11-12"]),
    ("ежедневно по дням недели", "20261116T090000", "FREQ=DAILY;BYDAY=MO,WE,FR;COUNT=4",
     ["2026-11-16", "2026-11-18", "2026-11-20", "2026-11-23"]),
    ("вторник и четверг до UNTIL с Z", "20261117T150000",
     "FREQ=WEEKLY;WKST=MO;UNTIL=20261210T215959Z;BYDAY=TU,TH",
     ["2026-11-17", "2026-11-19", "2026-11-24", "2026-11-26",
      "2026-12-01", "2026-12-03", "2026-12-08", "2026-12-10"]),
    ("UNTIL датой — день включён", "20261116T090000", "FREQ=WEEKLY;UNTIL=20261130",
     ["2026-11-16", "2026-11-23", "2026-11-30"]),
    ("еженедельно без BYDAY — день недели начала", "20261116T090000", "FREQ=WEEKLY;COUNT=4",
     ["2026-11-16", "2026-11-23", "2026-11-30", "2026-12-07"]),
    ("через неделю, понедельник и пятница", "20261116T090000", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR;COUNT=5",
     ["2026-11-16", "2026-11-20", "2026-11-30", "2026-12-04", "2026-12-14"]),
    ("через неделю, неделя с воскресенья (WKST=SU)", "20261117T090000",
     "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,SU;WKST=SU;COUNT=4",
     ["2026-11-17", "2026-11-29", "2026-12-01", "2026-12-13"]),
    ("то же правило, неделя с понедельника (WKST=MO)", "20261117T090000",
     "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,SU;WKST=MO;COUNT=4",
     ["2026-11-17", "2026-11-22", "2026-12-01", "2026-12-06"]),
    ("второй понедельник месяца (2MO)", "20261109T100000", "FREQ=MONTHLY;BYDAY=2MO;COUNT=4",
     ["2026-12-14", "2027-01-11", "2027-02-08"]),
    ("последняя пятница месяца (-1FR)", "20261127T100000", "FREQ=MONTHLY;BYDAY=-1FR;COUNT=3",
     ["2026-11-27", "2026-12-25", "2027-01-29"]),
    ("15-е и последний день месяца (BYMONTHDAY)", "20261115T120000", "FREQ=MONTHLY;BYMONTHDAY=15,-1;COUNT=4",
     ["2026-11-15", "2026-11-30", "2026-12-15", "2026-12-31"]),
    ("каждое 31-е: месяцы без него пропускаются", "20261031T120000", "FREQ=MONTHLY;COUNT=4",
     ["2026-12-31", "2027-01-31", "2027-03-31"]),
    ("раз в квартал без конца — только окно", "20261120T120000", "FREQ=MONTHLY;INTERVAL=3",
     ["2026-11-20", "2027-02-20"]),
    ("как пишет Google: число месяца с WKST, серия начата до окна", "20261025T193000",
     "FREQ=MONTHLY;WKST=TU;BYMONTHDAY=25",
     ["2026-11-25", "2026-12-25", "2027-01-25", "2027-02-25", "2027-03-25", "2027-04-25"]),
    ("через перевод часов 28.03.2027","20270315T090000", "FREQ=WEEKLY;COUNT=4",
     ["2027-03-15", "2027-03-22", "2027-03-29", "2027-04-05"]),
]

# (что проверяется, тело события после UID, код причины)
UNSUPPORTED = [
    ("ежегодно", "DTSTART:20261201T090000Z\nRRULE:FREQ=YEARLY", ics.RRULE_FREQ),
    ("ежечасно", "DTSTART:20261201T090000Z\nRRULE:FREQ=HOURLY", ics.RRULE_FREQ),
    ("правило без FREQ", "DTSTART:20261201T090000Z\nRRULE:COUNT=3", ics.RRULE_FREQ),
    ("BYSETPOS", "DTSTART:20261201T090000Z\nRRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", ics.RRULE_PART),
    ("BYMONTH", "DTSTART:20261201T090000Z\nRRULE:FREQ=MONTHLY;BYMONTH=3", ics.RRULE_PART),
    ("2MO у недельного повтора", "DTSTART:20261201T090000Z\nRRULE:FREQ=WEEKLY;BYDAY=2MO", ics.RRULE_PART),
    ("BYDAY вместе с BYMONTHDAY", "DTSTART:20261201T090000Z\nRRULE:FREQ=MONTHLY;BYDAY=MO;BYMONTHDAY=1",
     ics.RRULE_PART),
    ("BYMONTHDAY у недельного повтора", "DTSTART:20261201T090000Z\nRRULE:FREQ=WEEKLY;BYMONTHDAY=1", ics.RRULE_PART),
    ("INTERVAL=0", "DTSTART:20261201T090000Z\nRRULE:FREQ=DAILY;INTERVAL=0", ics.RRULE_VALUE),
    ("COUNT не число", "DTSTART:20261201T090000Z\nRRULE:FREQ=DAILY;COUNT=x", ics.RRULE_VALUE),
    ("день недели не читается", "DTSTART:20261201T090000Z\nRRULE:FREQ=WEEKLY;BYDAY=XX", ics.RRULE_VALUE),
    ("UNTIL не читается", "DTSTART:20261201T090000Z\nRRULE:FREQ=DAILY;UNTIL=maine", ics.RRULE_VALUE),
    ("два правила у одного события", "DTSTART:20261201T090000Z\nRRULE:FREQ=DAILY;COUNT=2\nRRULE:FREQ=WEEKLY",
     ics.RRULE_MANY),
    ("RDATE", "DTSTART:20261201T090000Z\nRDATE:20261205T090000Z", ics.RDATE),
    ("серия «весь день»", "DTSTART;VALUE=DATE:20261201\nRRULE:FREQ=WEEKLY", ics.ALLDAY_SERIES),
    ("серия длиннее предохранителя", "DTSTART:20000101T090000Z\nRRULE:FREQ=DAILY;COUNT=100000", ics.SERIES_LONG),
]


def _series(start: str, rule: str, extra: str = "") -> bytes:
    end = start[:9] + f"{int(start[9:11]) + 1:02d}" + start[11:]
    return cal_of(f"UID:r1\nDTSTART;TZID=Europe/Chisinau:{start}\nDTEND;TZID=Europe/Chisinau:{end}\n"
                  f"RRULE:{rule}\nSUMMARY:Serie{extra}")


def _every(first: date, step: int, lo: date, hi: date) -> list[str]:
    out, d = [], first
    while d <= hi:
        if d >= lo:
            out.append(f"{d:%Y-%m-%d}")
        d += timedelta(days=step)
    return out


def suite_rrule(res: Result) -> None:
    res.ok("таблица правил не пуста", len(RRULES) >= 12 and len(UNSUPPORTED) >= 10)
    for label, start, rule, want in RRULES:
        got = occs(_series(start, rule), *WIN)
        res.check(f"правило: {label}", [f"{o.start:%Y-%m-%d}" for o in got], want)
        wall = {(o.start.hour, o.start.minute, str(o.start.tzinfo), o.minutes, o.problem) for o in got}
        res.check(f"правило: {label} — час тот же, пояс серии, длительность серии", wall,
                  {(int(start[9:11]), int(start[11:13]), "Europe/Chisinau", 60, "")})
        res.check(f"правило: {label} — ключ по дате вхождения",
                  [o.key for o in got], [f"r1|{d.replace('-', '')}" for d in want])
    forms = " ".join(r for _, _, r, _ in RRULES)
    for part in ("FREQ=DAILY", "FREQ=WEEKLY", "FREQ=MONTHLY", "INTERVAL=", "BYDAY=2MO", "BYDAY=-1FR",
                 "BYMONTHDAY=", "COUNT=", "UNTIL=", "WKST=SU"):
        res.ok(f"в таблице есть форма {part}", part in forms)

    got = occs(_series("20270315T090000", "FREQ=WEEKLY;COUNT=4"), *WIN)
    res.check("перевод часов: приём в 9:00 остаётся в 9:00, момент UTC сдвигается на час",
              [o.start.astimezone(timezone.utc).hour for o in got], [7, 7, 6, 6])
    got = occs(_series("20261120T120000", "FREQ=MONTHLY;INTERVAL=3"), *WIN)
    res.check("серия без конца помечена", {o.note for o in got}, {ics.ENDLESS})
    got = occs(_series("20261116T090000", "FREQ=WEEKLY;COUNT=4"), *WIN)
    res.check("серия с концом не помечена", {o.note for o in got}, {""})
    got = occs(_series("20150105T090000", "FREQ=WEEKLY"), WIN[0], datetime(2026, 11, 30, 23, 59, tzinfo=TZ))
    res.check("серия без конца, начатая годы назад, доходит до окна (предохранитель не срабатывает)",
              [f"{o.start:%Y-%m-%d %H:%M}" for o in got],
              ["2026-11-16 09:00", "2026-11-23 09:00", "2026-11-30 09:00"])
    got = occs(_series("20100101T090000", "FREQ=DAILY"), WIN[0], datetime(2026, 11, 14, 23, 59, tzinfo=TZ))
    res.check("ежедневная серия без конца длиннее предохранителя в днях доходит до окна",
              [f"{o.start:%Y-%m-%d}" for o in got], ["2026-11-13", "2026-11-14"])
    got = occs(_series("20100104T090000", "FREQ=WEEKLY;INTERVAL=2"), WIN[0],
               datetime(2026, 12, 15, 23, 59, tzinfo=TZ))
    res.check("давняя серия «через неделю» не сбивается с чётности",
              [f"{o.start:%Y-%m-%d}" for o in got], _every(date(2010, 1, 4), 14, date(2026, 11, 13), date(2026, 12, 15)))
    got = occs(_series("20200131T090000", "FREQ=MONTHLY"), WIN[0], datetime(2027, 3, 31, 23, 59, tzinfo=TZ))
    res.check("давняя месячная серия «каждое 31-е» в окне",
              [f"{o.start:%Y-%m-%d}" for o in got], ["2026-12-31", "2027-01-31", "2027-03-31"])
    got = occs(_series("20260105T090000", "FREQ=WEEKLY;COUNT=10"), *WIN)
    res.check("серия, закончившаяся до окна, ничего не даёт", got, [])

    ex = "\nEXDATE;TZID=Europe/Chisinau:20261123T090000,20261207T090000"
    got = occs(_series("20261116T090000", "FREQ=WEEKLY;COUNT=5", ex), *WIN)
    res.check("EXDATE (два значения в строке): вхождения убраны, COUNT их считает",
              [f"{o.start:%Y-%m-%d}" for o in got], ["2026-11-16", "2026-11-30", "2026-12-14"])
    got = occs(_series("20261116T090000", "FREQ=WEEKLY;COUNT=3", "\nEXDATE:20261123T070000Z"), *WIN)
    res.check("EXDATE в UTC убирает то же вхождение",
              [f"{o.start:%Y-%m-%d}" for o in got], ["2026-11-16", "2026-11-30"])

    for label, body, code in UNSUPPORTED:
        (one,) = occs(cal_of(f"UID:u1\n{body}\nSUMMARY:Serie neinteleasa"), *WIN)
        res.check(f"«не разобрано»: {label}", (one.problem, one.title, one.key, one.series),
                  (code, "Serie neinteleasa", "u1", True))
    codes = {c for _, _, c in UNSUPPORTED}
    series_codes = {ics.RRULE_FREQ, ics.RRULE_PART, ics.RRULE_VALUE, ics.RRULE_MANY, ics.RDATE,
                    ics.ALLDAY_SERIES, ics.SERIES_LONG}
    res.check("у каждой причины отказа серии есть строка таблицы", sorted(series_codes - codes), [])


# ---------- серии образца: удалённое, изменённое, отменённое ----------

def suite_series(res: Result) -> None:
    res.ok("образец серий нашёлся", (FIX / "series.ics.tpl").is_file())
    for now in nows():
        tag = f"[{now:%d.%m.%Y %H:%M}]"
        (cal,) = ics.read(sample("series", now), TZ)
        got = ics.occurrences(cal, *window(now))
        by = {}
        for o in got:
            by.setdefault(o.key.split("@")[0], []).append(o)

        def keys(n: list[int]) -> list[str]:
            return [f"s1@google.com|{day(now, i):%Y%m%d}" for i in n]

        s1 = sorted(by["s1"], key=lambda o: o.key)
        res.check(f"{tag} вт/чт четыре недели: удалённое (EXDATE) ушло, изменённые — своей строкой",
                  [o.key for o in s1], keys([1, 8, 10, 15, 17, 22, 24]))
        moved = next(o for o in s1 if o.key == keys([8])[0])
        res.check(f"{tag} перенесённое вхождение: ключ прежней даты, время новое",
                  (moved.start, moved.minutes, moved.moved, moved.title.endswith("(mutat)")),
                  (at(now, 9, 17), 20, True, True))
        gone = next(o for o in s1 if o.key == keys([15])[0])
        res.check(f"{tag} отменённое вхождение — статус, не пропажа", (gone.status, gone.moved),
                  (ics.CANCELLED, True))
        plain_ones = [o for o in s1 if not o.moved]
        res.check(f"{tag} обычные вхождения серии: 15:00, 20 минут, серия",
                  {(o.start.hour, o.start.minute, o.minutes, o.series, o.status) for o in plain_ones},
                  {(15, 0, 20, True, "")})
        res.check(f"{tag} через день пять раз", [o.start for o in by["s2"]],
                  [at(now, n, 8, 30) for n in (0, 2, 4, 6, 8)])
        s3 = by["s3"]
        res.ok(f"{tag} серия без конца: только окно, помечена",
               20 <= len(s3) <= 27 and {o.note for o in s3} == {ics.ENDLESS}
               and max(o.start for o in s3) <= now + timedelta(days=180), str(len(s3)))
        res.check(f"{tag} серии, которых не понимаем: одна строка с названием и причиной",
                  [(k, len(by[k]), by[k][0].problem, bool(by[k][0].title)) for k in ("s4", "s5", "s7", "s8")],
                  [("s4", 1, ics.RRULE_FREQ, True), ("s5", 1, ics.RRULE_PART, True),
                   ("s7", 1, ics.RDATE, True), ("s8", 1, ics.ALLDAY_SERIES, True)])
        res.ok(f"{tag} давно закончившаяся серия ничего не даёт", "s6" not in by)
        res.check(f"{tag} ключи не повторяются", len({o.key for o in got}), len(got))


# ---------- чистота модуля ----------

def pure(res: Result, module, allowed: set, project: set) -> None:
    res.ok(f"{module.name}: модуль нашёлся", module.is_file(), str(module))
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported, relative = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            relative.update(f"{node.module}." + a.name if node.module else a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    res.check(f"{module.name}: импорты — только из разрешённого списка", sorted(imported - allowed), [])
    res.check(f"{module.name}: из проекта — только названное", sorted(relative), sorted(project))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    res.ok(f"{module.name}: ни open, ни __file__, ни environ, ни «сейчас»",
           not ({"open", "__file__"} & names or {"environ", "now", "today", "utcnow"} & attrs))


def suite_pure(res: Result) -> None:
    pure(res, MODULE, ALLOWED_IMPORTS, set())
    res.ok("пояс клиники находится тем же пакетом, что едет в собранную программу",
           ics.zone("Europe/Chisinau") is not None and ics.zone("America/New_York") is not None)
    req = (BOT / "requirements-desktop.txt").read_text(encoding="utf-8")
    res.ok("tzdata — в зависимостях настольной сборки", re.search(r"(?m)^tzdata==", req) is not None)
