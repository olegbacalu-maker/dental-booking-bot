"""Чтение файла календаря (.ics или .zip экспорта Google Calendar).

Модуль чистый, и ничего не пропадает молча: нечитаемый файл — Refused с кодом,
нечитаемое событие — Occurrence с problem и названием (человек внесёт его руками)."""
from __future__ import annotations

import calendar
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MAX_FILE = 20 * 1024 * 1024
MAX_EVENTS = 20000
MAX_STEPS = 5000
# Архив «все календари»: распакованное вместе ограничено кратным потолка одного файла.
ZIP_RATIO = 4
ZIP_CALENDARS = 50

# ---- отказ файла целиком ----

NOT_CALENDAR = "not_calendar"
NOT_UTF8 = "not_utf8"
TOO_BIG = "too_big"
TOO_MANY = "too_many"
BAD_ZIP = "bad_zip"
ZIP_EMPTY = "zip_empty"
REFUSALS = (NOT_CALENDAR, NOT_UTF8, TOO_BIG, TOO_MANY, BAD_ZIP, ZIP_EMPTY)

# ---- событие «не разобрано» ----

BAD_LINE = "bad_line"
BAD_DATE = "bad_date"
BAD_DURATION = "bad_duration"
UNKNOWN_TZ = "unknown_tz"
NO_UID = "no_uid"
NO_START = "no_start"
DUP_KEY = "dup_key"
RRULE_FREQ = "rrule_freq"
RRULE_PART = "rrule_part"
RRULE_VALUE = "rrule_value"
RRULE_MANY = "rrule_many"
RDATE = "rdate"
RANGE = "range"
ALLDAY_SERIES = "allday_series"
SERIES_LONG = "series_long"
PROBLEMS = (BAD_LINE, BAD_DATE, BAD_DURATION, UNKNOWN_TZ, NO_UID, NO_START, DUP_KEY,
            RRULE_FREQ, RRULE_PART, RRULE_VALUE, RRULE_MANY, RDATE, RANGE,
            ALLDAY_SERIES, SERIES_LONG)

# ---- пометка события, которое разобрано ----

ENDLESS = "endless"

CANCELLED = "CANCELLED"


class Refused(Exception):
    """Файл не читается целиком; code — из REFUSALS."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


class Unparsed(Exception):
    """Одно событие не читается; code — из PROBLEMS."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


@dataclass
class Event:
    uid: str = ""
    rid: date | datetime | None = None
    rid_range: bool = False
    start: date | datetime | None = None
    end: date | datetime | None = None
    duration: timedelta | None = None
    title: str = ""
    description: str = ""
    location: str = ""
    status: str = ""
    rrules: list = field(default_factory=list)
    exdates: list = field(default_factory=list)
    attendees: list = field(default_factory=list)
    problem: str = ""
    detail: str = ""


@dataclass
class Calendar:
    source: str = ""
    name: str = ""
    tz: ZoneInfo | None = None
    events: list = field(default_factory=list)
    refused: str = ""


@dataclass(frozen=True)
class Occurrence:
    """Готовое событие — вход конвертера; тот же вид соберёт и синхронизация по API."""
    key: str
    start: datetime | None = None
    minutes: int = 0
    day: date | None = None
    title: str = ""
    description: str = ""
    location: str = ""
    attendees: tuple = ()
    status: str = ""
    series: bool = False
    moved: bool = False
    note: str = ""
    problem: str = ""
    detail: str = ""


def occurrence_key(uid: str, day: date | None = None) -> str:
    """Ключ события для повторного импорта. У вхождения серии — дата, не момент:
    сдвиг времени всей серии оставляет ключи на месте."""
    return uid if day is None else f"{uid}|{day:%Y%m%d}"


_BOM = b"\xef\xbb\xbf"


def _lines(raw: bytes) -> list[str]:
    if raw.startswith(_BOM):
        raw = raw[len(_BOM):]
    if not raw.lstrip()[:15].upper().startswith(b"BEGIN:VCALENDAR"):
        raise Refused(NOT_CALENDAR)
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    # Склейка до декодирования: перенос режет строку по октетам и вправе
    # разрезать многобайтовую букву пополам.
    raw = raw.replace(b"\n ", b"").replace(b"\n\t", b"")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(NOT_UTF8) from None
    return [ln for ln in text.split("\n") if ln.strip()]


_PARAM = re.compile(r'(?:[^;"]|"[^"]*")+')


def split_line(line: str) -> tuple[str, dict, str]:
    """`ИМЯ;ПАРАМ=знач;ПАРАМ="зн:ач":ЗНАЧЕНИЕ` -> (имя, параметры, значение)."""
    quoted, cut = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            cut = i
            break
    if cut <= 0:
        raise Unparsed(BAD_LINE, line[:40])
    parts = _PARAM.findall(line[:cut])
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.strip().upper()] = v.strip().strip('"')
    return parts[0].strip().upper(), params, line[cut + 1:]


def untext(value: str) -> str:
    """Экранирование значения TEXT: `\\n`, `\\,`, `\\;`, `\\\\`."""
    out, i = [], 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


_BREAK = re.compile(r"(?i)<br\s*/?>|</p>|</li>|</div>")
_TAG = re.compile(r"<[^<>]{1,300}>")


def plain(text: str) -> str:
    """Описание Google бывает разметкой; дальше идёт только текст."""
    s = html.unescape(_TAG.sub("", _BREAK.sub("\n", text)))
    rows = [r.strip() for r in s.replace("\xa0", " ").split("\n")]
    return "\n".join(r for r in rows if r)


_TZID = re.compile(r"[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+)*")
_DATE = re.compile(r"(\d{4})(\d\d)(\d\d)")
_STAMP = re.compile(r"(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)(Z?)")


def zone(name: str) -> ZoneInfo | None:
    name = (name or "").strip()
    if not _TZID.fullmatch(name) or len(name) > 64:
        return None
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return None


def _when(value: str, params: dict, cal_tz: ZoneInfo | None) -> date | datetime:
    """Дата «весь день» либо момент с поясом; секунды отбрасываются: журнал считает минутами."""
    v = value.strip()
    try:
        m = _DATE.fullmatch(v)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _STAMP.fullmatch(v)
        if not m or params.get("VALUE", "").upper() == "DATE":
            raise Unparsed(BAD_DATE, v[:40])
        y, mo, d, h, mi = (int(x) for x in m.groups()[:5])
        naive = datetime(y, mo, d, h, mi)
    except ValueError:
        raise Unparsed(BAD_DATE, v[:40]) from None
    if m.group(7):
        return naive.replace(tzinfo=timezone.utc)
    tzid = params.get("TZID")
    if tzid:
        tz = zone(tzid)
        if tz is None:
            raise Unparsed(UNKNOWN_TZ, tzid[:64])
        return naive.replace(tzinfo=tz)
    if cal_tz is None:
        raise Unparsed(UNKNOWN_TZ, "X-WR-TIMEZONE")
    return naive.replace(tzinfo=cal_tz)


_DUR = re.compile(r"([+-]?)P(?:(\d{1,6})W)?(?:(\d{1,6})D)?(?:T(?:(\d{1,6})H)?(?:(\d{1,6})M)?(?:(\d{1,6})S)?)?")


def _duration(value: str) -> timedelta:
    v = value.strip()
    m = _DUR.fullmatch(v)
    if not m or v.lstrip("+-") in ("P", "PT"):
        raise Unparsed(BAD_DURATION, v[:40])
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    td = timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return -td if m.group(1) == "-" else td


def _header(lines: list[str], name: str) -> str | None:
    head = name + ":"
    for ln in lines:
        if ln[:len(head)].upper() == head:
            return ln[len(head):]
        if ln.upper().startswith("BEGIN:VEVENT"):
            break
    return None


def _set(ev: Event, name: str, params: dict, value: str, cal_tz: ZoneInfo | None) -> None:
    if name == "UID":
        ev.uid = value.strip()
    elif name == "SUMMARY":
        ev.title = " ".join(untext(value).split())
    elif name == "DESCRIPTION":
        ev.description = plain(untext(value))
    elif name == "LOCATION":
        ev.location = " ".join(untext(value).split())
    elif name == "STATUS":
        ev.status = value.strip().upper()
    elif name == "DTSTART":
        ev.start = _when(value, params, cal_tz)
    elif name == "DTEND":
        ev.end = _when(value, params, cal_tz)
    elif name == "DURATION":
        ev.duration = _duration(value)
    elif name == "RECURRENCE-ID":
        ev.rid_range = "RANGE" in params
        ev.rid = _when(value, params, cal_tz)
    elif name == "RRULE":
        ev.rrules.append(value.strip())
    elif name in ("RDATE", "EXRULE"):
        raise Unparsed(RDATE, name)
    elif name == "EXDATE":
        for part in value.split(","):
            if part.strip():
                ev.exdates.append(_when(part, params, cal_tz))
    elif name == "ATTENDEE":
        mail = value.strip()
        if mail[:7].lower() == "mailto:":
            mail = mail[7:]
        ev.attendees.append((params.get("CN", ""), mail))


def parse(raw: bytes, tz: ZoneInfo, *, max_bytes: int = MAX_FILE,
          max_events: int = MAX_EVENTS, source: str = "") -> Calendar:
    """Один файл .ics; `tz` — пояс клиники для времени без пояса."""
    if len(raw) > max_bytes:
        raise Refused(TOO_BIG)
    lines = _lines(raw)
    cal = Calendar(source=source, tz=tz)
    name = _header(lines, "X-WR-CALNAME")
    if name is not None:
        cal.name = " ".join(untext(name).split())
    own = _header(lines, "X-WR-TIMEZONE")
    if own is not None:
        # Незнакомый пояс календаря не заменяется догадкой: время без пояса
        # в таком файле станет «не разобрано», остальное читается.
        cal.tz = zone(own)
    stack: list[str] = []
    ev: Event | None = None
    for ln in lines:
        up = ln[:6].upper()
        if up == "BEGIN:":
            stack.append(ln[6:].strip().upper())
            if stack[-1] == "VEVENT" and ev is None:
                ev = Event()
            continue
        if up[:4] == "END:":
            closing = ln[4:].strip().upper()
            if closing == "VEVENT" and ev is not None:
                cal.events.append(ev)
                ev = None
                if len(cal.events) > max_events:
                    raise Refused(TOO_MANY)
            if stack:
                stack.pop()
            continue
        # Свойства вложенных частей (напоминание VALARM несёт своё DESCRIPTION)
        # событию не принадлежат.
        if ev is None or stack[-1:] != ["VEVENT"]:
            continue
        try:
            _set(ev, *split_line(ln), cal.tz)
        except Unparsed as ex:
            if not ev.problem:
                ev.problem, ev.detail = ex.code, ex.detail
    return cal


def read(raw: bytes, tz: ZoneInfo, *, max_bytes: int = MAX_FILE,
         max_events: int = MAX_EVENTS) -> list[Calendar]:
    """Файл клиники: .ics либо архив; вид опознаётся содержимым, не именем."""
    if len(raw) > max_bytes:
        raise Refused(TOO_BIG)
    if raw[:2] != b"PK":
        return [parse(raw, tz, max_bytes=max_bytes, max_events=max_events)]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos = [i for i in z.infolist()
                     if i.filename.lower().endswith(".ics") and not i.is_dir()
                     and not i.filename.startswith("__MACOSX/")]
            if not infos:
                raise Refused(ZIP_EMPTY)
            # Размер берётся из оглавления архива, до распаковки: иначе
            # килобайтный файл развернулся бы в гигабайты уже в памяти.
            if len(infos) > ZIP_CALENDARS or sum(i.file_size for i in infos) > max_bytes * ZIP_RATIO:
                raise Refused(TOO_BIG)
            out = []
            for info in infos:
                try:
                    if info.file_size > max_bytes:
                        raise Refused(TOO_BIG)
                    # Оглавление может врать о размере — чтение ограничено само.
                    with z.open(info) as f:
                        data = f.read(max_bytes + 1)
                    out.append(parse(data, tz, max_bytes=max_bytes, max_events=max_events,
                                     source=info.filename))
                except Refused as ex:
                    out.append(Calendar(source=info.filename, refused=ex.code))
                except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
                    out.append(Calendar(source=info.filename, refused=BAD_ZIP))
    except zipfile.BadZipFile:
        raise Refused(BAD_ZIP) from None
    if all(c.refused for c in out):
        raise Refused(out[0].refused, out[0].source)
    return out


_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_RULE_KEYS = {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "COUNT", "UNTIL", "WKST"}
_BYDAY = re.compile(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)")


def _number(rule: dict, key: str, default: int | None) -> int | None:
    if key not in rule:
        return default
    v = rule[key]
    if not v.isascii() or not v.isdigit() or not 1 <= int(v) <= 100000:
        raise Unparsed(RRULE_VALUE, f"{key}={v[:20]}")
    return int(v)


def _rule(text: str) -> dict:
    """Разобранное правило повтора. Чего не умеем — уходит в «не разобрано» целой
    серией: половина правила, понятая по-своему, дала бы записи не в те дни."""
    rule: dict = {}
    for part in text.split(";"):
        if not part.strip():
            continue
        k, _, v = part.partition("=")
        k = k.strip().upper()
        if k not in _RULE_KEYS or k in rule:
            raise Unparsed(RRULE_PART, k[:20])
        rule[k] = v.strip().upper()
    freq = rule.get("FREQ", "")
    if freq not in ("DAILY", "WEEKLY", "MONTHLY"):
        raise Unparsed(RRULE_FREQ, freq[:20])
    out: dict = {"freq": freq, "interval": _number(rule, "INTERVAL", 1),
                 "count": _number(rule, "COUNT", None), "until": rule.get("UNTIL"),
                 "byday": [], "bymonthday": []}
    wkst = rule.get("WKST", "MO")
    if wkst not in _DAYS:
        raise Unparsed(RRULE_VALUE, f"WKST={wkst[:20]}")
    out["wkst"] = _DAYS[wkst]
    if "BYDAY" in rule:
        for tok in rule["BYDAY"].split(","):
            m = _BYDAY.fullmatch(tok.strip())
            nth = int(m.group(1)) if m and m.group(1) else 0
            if not m or (m.group(1) and not 1 <= abs(nth) <= 5):
                raise Unparsed(RRULE_VALUE, f"BYDAY={tok[:20]}")
            if nth and freq != "MONTHLY":
                raise Unparsed(RRULE_PART, f"BYDAY={tok[:20]}")
            out["byday"].append((nth, _DAYS[m.group(2)]))
    if "BYMONTHDAY" in rule:
        if freq != "MONTHLY" or out["byday"]:
            raise Unparsed(RRULE_PART, "BYMONTHDAY")
        for tok in rule["BYMONTHDAY"].split(","):
            t = tok.strip()
            if not re.fullmatch(r"[+-]?\d{1,2}", t) or not 1 <= abs(int(t)) <= 31:
                raise Unparsed(RRULE_VALUE, f"BYMONTHDAY={tok[:20]}")
            out["bymonthday"].append(int(t))
    return out


def _month_days(y: int, m: int, rule: dict, base_day: int) -> list[int]:
    last = calendar.monthrange(y, m)[1]
    if rule["byday"]:
        out = set()
        for nth, wd in rule["byday"]:
            days = [d for d in range(1, last + 1) if date(y, m, d).weekday() == wd]
            if not nth:
                out.update(days)
            elif abs(nth) <= len(days):
                out.add(days[nth - 1] if nth > 0 else days[nth])
        return sorted(out)
    if rule["bymonthday"]:
        days = {n if n > 0 else last + 1 + n for n in rule["bymonthday"]}
        return sorted(d for d in days if 1 <= d <= last)
    # Серия «каждое 31-е»: месяц без такого числа пропускается, не сдвигается.
    return [base_day] if base_day <= last else []


def _candidates(rule: dict, base: datetime, skip: int):
    """Стенные часы вхождений по возрастанию, начиная с периода skip."""
    step, k = rule["interval"], skip
    if rule["freq"] == "DAILY":
        wds = {wd for _, wd in rule["byday"]}
        while True:
            c = base + timedelta(days=k * step)
            if not wds or c.weekday() in wds:
                yield c
            else:
                yield None
            k += 1
    elif rule["freq"] == "WEEKLY":
        wkst = rule["wkst"]
        offs = sorted({(wd - wkst) % 7 for _, wd in rule["byday"]} or {(base.weekday() - wkst) % 7})
        week0 = base - timedelta(days=(base.weekday() - wkst) % 7)
        while True:
            for off in offs:
                c = week0 + timedelta(weeks=k * step, days=off)
                yield c if c >= base else None
            k += 1
    else:
        while True:
            idx = base.month - 1 + k * step
            y, m = base.year + idx // 12, idx % 12 + 1
            days = _month_days(y, m, rule, base.day)
            for d in days:
                c = base.replace(year=y, month=m, day=d)
                yield c if c >= base else None
            if not days:
                yield None
            k += 1


def _skip(rule: dict, base: datetime, win_from: datetime) -> int:
    """Сколько периодов серии заведомо лежит до окна. Серия со счётчиком
    считается с начала: COUNT — число вхождений от первого, не от окна."""
    if rule["count"] is not None:
        return 0
    days = (win_from.date() - base.date()).days
    if rule["freq"] == "MONTHLY":
        periods = (win_from.year - base.year) * 12 + win_from.month - base.month
    else:
        periods = days // (7 if rule["freq"] == "WEEKLY" else 1)
    return max(0, periods // rule["interval"] - 1)


def _expand(ev: Event, win_from: datetime, win_to: datetime) -> tuple[list[datetime], bool]:
    """Старты серии в окне и признак «серия без конца». Счёт идёт по стенным
    часам пояса серии: приём в 9:00 остаётся в 9:00 через перевод часов."""
    if len(ev.rrules) != 1:
        raise Unparsed(RRULE_MANY)
    if not isinstance(ev.start, datetime):
        raise Unparsed(ALLDAY_SERIES)
    rule = _rule(ev.rrules[0])
    tz = ev.start.tzinfo
    base = ev.start.replace(tzinfo=None)
    until = None
    if rule["until"]:
        try:
            until = _when(rule["until"], {}, tz)
        except Unparsed:
            raise Unparsed(RRULE_VALUE, f"UNTIL={rule['until'][:20]}") from None
    out, made = [], 0
    local_from = win_from.astimezone(tz).replace(tzinfo=None)
    for steps, c in enumerate(_candidates(rule, base, _skip(rule, base, local_from))):
        # Серия, до окна которой не дойти за разумное число шагов, целиком
        # уходит в «не разобрано»: оборванная молча потеряла бы хвост.
        if steps >= MAX_STEPS:
            raise Unparsed(SERIES_LONG)
        if c is None:
            continue
        aware = c.replace(tzinfo=tz)
        if isinstance(until, datetime) and aware > until:
            break
        if until is not None and not isinstance(until, datetime) and c.date() > until:
            break
        if rule["count"] is not None and made >= rule["count"]:
            break
        made += 1
        if aware > win_to:
            break
        if aware >= win_from:
            out.append(aware)
    return out, rule["count"] is None and until is None


def _series_day(when: date | datetime, tz) -> date:
    if isinstance(when, datetime):
        return when.astimezone(tz).date() if tz is not None else when.date()
    return when


def _minutes(ev: Event) -> int:
    if ev.end is not None:
        if not isinstance(ev.end, datetime) or not isinstance(ev.start, datetime):
            raise Unparsed(BAD_DATE, "DTSTART/DTEND")
        # Разность через UTC: у двух моментов одного пояса вычитание шло бы по
        # стенным часам и ошибалось на час в ночь перевода.
        delta = ev.end.astimezone(timezone.utc) - ev.start.astimezone(timezone.utc)
        return int(delta.total_seconds() // 60)
    if ev.duration is not None:
        return int(ev.duration.total_seconds() // 60)
    return 0


def _one(ev: Event, key: str, start, *, series: bool, moved: bool = False,
         note: str = "", problem: tuple[str, str] | None = None) -> Occurrence:
    code, detail = problem or (ev.problem, ev.detail)
    day, minutes = None, 0
    if not code:
        try:
            if isinstance(start, datetime):
                minutes = _minutes(ev)
            elif isinstance(start, date):
                day, start = start, None
            else:
                raise Unparsed(NO_START)
        except Unparsed as ex:
            code, detail = ex.code, ex.detail
    if not isinstance(start, datetime):
        start = None
    return Occurrence(key=key, start=start, minutes=minutes, day=day, title=ev.title,
                      description=ev.description, location=ev.location,
                      attendees=tuple(ev.attendees), status=ev.status, series=series,
                      moved=moved, note=note, problem=code, detail=detail)


def occurrences(cal: Calendar, win_from: datetime, win_to: datetime) -> list[Occurrence]:
    """Готовые события: одиночные — все, и прошедшие (решает конвертер); серия — только
    в окне, иначе серия без конца дала бы записи на годы."""
    masters: dict[str, Event] = {}
    changed: dict[str, set] = {}
    for ev in cal.events:
        if ev.uid and ev.rid is None and ev.rrules and ev.uid not in masters:
            masters[ev.uid] = ev

    def series_tz(uid: str):
        m = masters.get(uid)
        return m.start.tzinfo if m is not None and isinstance(m.start, datetime) else None

    for ev in cal.events:
        if ev.uid and ev.rid is not None:
            changed.setdefault(ev.uid, set()).add(_series_day(ev.rid, series_tz(ev.uid)))

    out: list[Occurrence] = []
    for ev in cal.events:
        if not ev.uid:
            out.append(_one(ev, "", ev.start, series=bool(ev.rrules), problem=(NO_UID, "")))
        elif ev.rid is not None:
            key = occurrence_key(ev.uid, _series_day(ev.rid, series_tz(ev.uid)))
            out.append(_one(ev, key, ev.start, series=True, moved=True,
                            problem=(RANGE, "") if ev.rid_range and not ev.problem else None))
        elif not ev.rrules:
            out.append(_one(ev, ev.uid, ev.start, series=ev.problem == RDATE))
        elif ev.problem or ev.status == CANCELLED:
            out.append(_one(ev, ev.uid, ev.start, series=True))
        else:
            try:
                starts, endless = _expand(ev, win_from, win_to)
                _minutes(ev)
            except Unparsed as ex:
                out.append(_one(ev, ev.uid, ev.start, series=True, problem=(ex.code, ex.detail)))
                continue
            tz = ev.start.tzinfo
            gone = {_series_day(x, tz) for x in ev.exdates} | changed.get(ev.uid, set())
            for st in starts:
                if st.date() not in gone:
                    out.append(_one(ev, occurrence_key(ev.uid, st.date()), st, series=True,
                                    note=ENDLESS if endless else ""))
    seen: set[str] = set()
    for i, occ in enumerate(out):
        if occ.key and occ.key in seen and not occ.problem:
            out[i] = Occurrence(**{**occ.__dict__, "problem": DUP_KEY, "detail": occ.key[:64]})
        seen.add(occ.key)
    return out
