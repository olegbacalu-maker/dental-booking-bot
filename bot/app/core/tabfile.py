"""Чтение .xlsx и .csv стандартной библиотекой: сторонний читатель уехал бы
в собранную программу. Файл чужой — потолки считаются до распаковки."""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

MAX_FILE = 10 * 1024 * 1024
MAX_UNPACKED = 80 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLS = 60
MAX_SHEETS = 20
MAX_CELL = 2000

ENCODINGS = ("utf-8", "utf-16", "cp1250", "cp1251")
DELIMITERS = (";", ",", "\t", "|")

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EPOCH = _dt.date(1899, 12, 30)
_BUILTIN_DATE = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
# встроенные форматы только времени (h:mm, h:mm AM/PM, mm:ss, [h]:mm:ss): с `times` — время, не 30.12.1899
_BUILTIN_TIME = {18, 19, 20, 21, 45, 46, 47}


class Refuse(Exception):
    """Файл не читается; `code` — причина: old_xls, not_table, too_big,
    too_many_rows, bad_xml, empty."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Sheet:
    name: str
    rows: list = field(default_factory=list)      # [(номер строки, [ячейки])]
    bands: set = field(default_factory=set)       # строки-разделы: одна ячейка на всю ширину


@dataclass
class Table:
    kind: str                                     # xlsx | csv
    sheets: list
    enc: str = ""
    delim: str = ""


def read(blob: bytes, name: str = "", *, enc: str = "", delim: str = "",
         times: bool = False) -> Table:
    """`times` — ячейки Excel со временем: дата-время — `datetime` (стенное, без пояса), только
    время — `time`. Без него дата Excel — всегда `date` (время отброшено): так читают склад, прайс и
    день рождения. Полночь — `date` и с `times`: дата без часа хранится как полночь."""
    if len(blob) > MAX_FILE:
        raise Refuse("too_big")
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if blob[:8] == _OLE or ext == "xls":
        raise Refuse("old_xls")
    if blob[:2] == b"PK":
        return Table("xlsx", _read_xlsx(blob, times))
    if not blob.strip() or blob[:5] == b"%PDF-":
        raise Refuse("empty" if not blob.strip() else "not_table")
    rows, enc, delim = _read_csv(blob, enc, delim)
    return Table("csv", [Sheet("", rows)], enc, delim)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(el, name: str) -> list:
    return [c for c in el if _local(c.tag) == name]


def _kid(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _xml(z: zipfile.ZipFile, name: str):
    raw = z.read(name)
    # внешние сущности и «миллиард смеха» объявляются только через DOCTYPE
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise Refuse("bad_xml")
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise Refuse("bad_xml") from None


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _is_date_fmt(code: str) -> bool:
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code.lower())
    if re.search(r"[dy]", code):
        return True
    return "m" in code and not re.search(r"[hs0#]", code)


def _is_time_fmt(code: str) -> bool:
    """Только время: часы или секунды без дня и года (`hh:mm`, `[h]:mm`, `h:mm am/pm`)."""
    code = re.sub(r'"[^"]*"|\\.|am/pm|a/p', "", code.lower())
    code = re.sub(r"\[(h+|m+|s+)\]", r"\1", code)
    code = re.sub(r"\[[^\]]*\]", "", code)
    return not re.search(r"[dy0#]", code) and bool(re.search(r"[hs]", code))


def _number(text: str) -> str:
    """Число как его набрали: 69123456.0 — «69123456», 2.0012345678930E12 —
    все тринадцать цифр (телефон и IDNP Excel хранит числом)."""
    try:
        f = float(text)
    except ValueError:
        return text
    return str(int(f)) if f == int(f) and abs(f) < 1e15 else text


def _serial_date(text: str, date1904: bool):
    try:
        days = int(float(text)) + (1462 if date1904 else 0)
        return _EPOCH + _dt.timedelta(days=days)
    except (ValueError, OverflowError):
        return text


def _serial_moment(text: str, date1904: bool):
    """Дата Excel со временем: дробь суток — минуты (до ближайшей); полночь — `date`."""
    try:
        f = float(text)
        minutes = round(f * 1440)
        day = _EPOCH + _dt.timedelta(days=minutes // 1440 + (1462 if date1904 else 0))
    except (ValueError, OverflowError):
        return text
    if f < 0 or minutes % 1440 == 0:
        return text if f < 0 else day
    return _dt.datetime.combine(day, _dt.time(minutes % 1440 // 60, minutes % 60))


def _serial_time(text: str):
    """Время Excel — доля суток; сутки и больше (`[h]:mm`, 25:30) — числом, как набрали."""
    try:
        minutes = round(float(text) * 1440)
    except (ValueError, OverflowError):
        return text
    if not 0 <= minutes < 1440:
        return _number(text)
    return _dt.time(minutes // 60, minutes % 60)


def _iso_date(text: str, times: bool = False):
    """Ячейка типа «дата» несёт ISO-текст; пояс не применяется — иначе день рождения сдвинулся
    бы на сутки. Время отбрасывается; с `times` — стенное время без пояса (полночь — `date`,
    день до 1900 — только время)."""
    try:
        day = _dt.date.fromisoformat(text.strip()[:10])
    except ValueError:
        return text
    m = re.match(r"T(\d\d):(\d\d)", text.strip()[10:])
    if not times or not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return day
    at = _dt.time(int(m.group(1)), int(m.group(2)))
    if day.year < 1900:
        return at
    return day if at == _dt.time(0, 0) else _dt.datetime.combine(day, at)


def _read_xlsx(blob: bytes, times: bool = False) -> list:
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise Refuse("not_table") from None
    if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
        raise Refuse("too_big")
    names = set(z.namelist())
    if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
        raise Refuse("not_table")

    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in _kids(_xml(z, "xl/sharedStrings.xml"), "si"):
            # куски «богатого текста» склеиваются; фонетические подсказки rPh — нет
            parts = [t.text or "" for t in _kids(si, "t")]
            for r in _kids(si, "r"):
                parts += [t.text or "" for t in _kids(r, "t")]
            shared.append("".join(parts))

    date_styles: set[int] = set()
    time_styles: set[int] = set()
    if "xl/styles.xml" in names:
        st = _xml(z, "xl/styles.xml")
        custom = {}
        for box in _kids(st, "numFmts"):
            for n in _kids(box, "numFmt"):
                custom[n.get("numFmtId", "")] = n.get("formatCode", "")
        for box in _kids(st, "cellXfs"):
            for i, xf in enumerate(_kids(box, "xf")):
                fid = xf.get("numFmtId", "0")
                if (fid.isdigit() and int(fid) in _BUILTIN_DATE) or (
                        fid in custom and _is_date_fmt(custom[fid])):
                    date_styles.add(i)
                if (fid.isdigit() and int(fid) in _BUILTIN_TIME) or (
                        fid in custom and _is_time_fmt(custom[fid])):
                    time_styles.add(i)
    fmt = _Formats(date_styles, time_styles if times else set(), times)

    wb = _xml(z, "xl/workbook.xml")
    pr = _kid(wb, "workbookPr")
    date1904 = pr is not None and pr.get("date1904") in ("1", "true")
    rels = {r.get("Id"): r.get("Target", "")
            for r in _kids(_xml(z, "xl/_rels/workbook.xml.rels"), "Relationship")}
    out = []
    box = _kid(wb, "sheets")
    for sh in (_kids(box, "sheet") if box is not None else [])[:MAX_SHEETS]:
        if sh.get("state") in ("hidden", "veryHidden"):
            continue
        rid = next((v for k, v in sh.attrib.items() if _local(k) == "id" and k != "id"), "")
        target = rels.get(rid, "")
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if path not in names:
            continue
        bands: set = set()
        out.append(Sheet(sh.get("name", ""), _sheet_rows(_xml(z, path), shared,
                                                         fmt, date1904, bands), bands))
    if not out:
        raise Refuse("empty")
    return out


@dataclass(frozen=True)
class _Formats:
    dates: set                                    # номера стилей ячеек с датой
    times: set                                    # только время (с `times`)
    moments: bool = False                         # дробь суток у даты — время (с `times`)


def _sheet_rows(root, shared: list, fmt: _Formats, date1904: bool,
                bands: set | None = None) -> list:
    data = _kid(root, "sheetData")
    rows: dict[int, list] = {}
    last = 0
    for row in (_kids(data, "row") if data is not None else []):
        r = row.get("r", "")
        rno = int(r) if r.isdigit() else last + 1
        last = rno
        line: list = []
        for k, c in enumerate(_kids(row, "c")):
            ci = _col_index(c.get("r", "")) if c.get("r") else k
            if not 0 <= ci < MAX_COLS:
                continue
            val = _cell(c, shared, fmt, date1904)
            if val is None:
                continue
            while len(line) <= ci:
                line.append(None)
            line[ci] = val
        if line:
            rows[rno] = line
            if len(rows) > MAX_ROWS + 25:
                raise Refuse("too_many_rows")
    # объединение по вертикали хранит значение только в верхней ячейке
    for box in _kids(root, "mergeCells"):
        for m in _kids(box, "mergeCell"):
            g = re.fullmatch(r"([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)", m.get("ref", ""))
            if (g and bands is not None and g.group(2) == g.group(4)
                    and _col_index(g.group(3)) - _col_index(g.group(1)) >= 2):
                bands.add(int(g.group(2)))
            if not g or g.group(1).upper() != g.group(3).upper():
                continue
            ci, top, bottom = _col_index(g.group(1)), int(g.group(2)), int(g.group(4))
            head = rows.get(top, [])
            if not (0 <= ci < len(head)) or head[ci] is None or bottom - top > MAX_ROWS:
                continue
            for rno in range(top + 1, bottom + 1):
                line = rows.get(rno)
                if line is None:
                    continue           # строки без других данных не воскрешаем
                while len(line) <= ci:
                    line.append(None)
                if line[ci] is None:
                    line[ci] = head[ci]
    return sorted(rows.items())


def _cell(c, shared: list, fmt: _Formats, date1904: bool):
    t, v = c.get("t", "n"), _kid(c, "v")
    text = v.text if v is not None else None
    val = None
    if t == "s":
        if text and text.isdigit() and int(text) < len(shared):
            val = shared[int(text)]
    elif t == "inlineStr":
        val = "".join(x.text or "" for x in c.iter() if _local(x.tag) == "t")
    elif t == "str":
        val = text
    elif t == "d":
        val = _iso_date(text, fmt.moments) if text else None
    elif t == "b":
        val = "da" if text == "1" else None
    elif t == "e":
        val = None
    elif text:
        s = c.get("s", "0")
        if s.isdigit() and int(s) in fmt.times:
            val = _serial_time(text)
        elif s.isdigit() and int(s) in fmt.dates:
            val = _serial_moment(text, date1904) if fmt.moments else _serial_date(text, date1904)
        else:
            val = _number(text)
    if isinstance(val, str):
        val = _clean(val.replace("_x000D_", ""))
    return val


def _clean(s: str) -> str | None:
    s = "".join(ch if ch >= " " else " " for ch in s).strip()[:MAX_CELL]
    return s or None


_RO = set("ăâîșțĂÂÎȘȚşţŞŢ")


def _decode(blob: bytes, enc: str) -> tuple[str, str]:
    if enc in ENCODINGS:
        raw = blob[3:] if enc == "utf-8" and blob[:3] == b"\xef\xbb\xbf" else blob
        return raw.decode(enc, "replace"), enc
    if blob[:3] == b"\xef\xbb\xbf":
        return blob[3:].decode("utf-8", "replace"), "utf-8"
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return blob.decode("utf-16", "replace"), "utf-16"
    try:
        return blob.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    # в русском тексте старшие байты почти все буквы, в румынском их мало
    a, b = blob.decode("cp1251", "replace"), blob.decode("cp1250", "replace")
    cyr = sum(1 for ch in a if "а" <= ch.lower() <= "я" or ch in "ёЁ")
    ro = sum(1 for ch in b if ch in _RO)
    hi = sum(1 for x in blob if x >= 0x80) or 1
    if cyr / hi > 0.9 and cyr > ro * 3:
        return a, "cp1251"
    return b, "cp1250"


def _guess_delim(text: str) -> str:
    head = [ln for ln in text.splitlines()[:30] if ln.strip()]
    best, delim = -1.0, ";"
    for d in DELIMITERS:
        counts = [len(next(csv.reader([ln], delimiter=d), [])) - 1 for ln in head]
        if not counts or max(counts) <= 0:
            continue
        mode = max(set(counts), key=counts.count)
        score = (counts.count(mode) / len(counts) if mode > 0 else 0) + min(mode, 8) / 100
        if score > best:
            best, delim = score, d
    return delim


def _read_csv(blob: bytes, enc: str, delim: str) -> tuple[list, str, str]:
    if b"\x00" in blob[:2000] and blob[:2] not in (b"\xff\xfe", b"\xfe\xff") and enc != "utf-16":
        raise Refuse("not_table")
    text, enc = _decode(blob, enc)
    if delim not in DELIMITERS:
        delim = _guess_delim(text)
    rows = []
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    try:
        for r in reader:
            line = [_clean(c) if c else None for c in r[:MAX_COLS]]
            if any(c is not None for c in line):
                rows.append((reader.line_num, line))
                if len(rows) > MAX_ROWS + 25:
                    raise Refuse("too_many_rows")
    except csv.Error:
        raise Refuse("not_table") from None
    if not rows:
        raise Refuse("empty")
    return rows, enc, delim


# ---------------------------------------------------------------- дата и час визита

NO_DATE, BAD_DATE, NO_TIME, BAD_TIME, BAD_RANGE = "no_date", "bad_date", "no_time", "bad_time", "bad_range"
# Коды, а не слова: слова причины даёт показывающий. `NO_TIME` — дата есть, часа нет: визит не
# ставится (выдуманный час занял бы чужое время в журнале).
WHEN_PROBLEMS = (NO_DATE, BAD_DATE, NO_TIME, BAD_TIME, BAD_RANGE)

_SERIAL_MIN, _SERIAL_MAX = 36526, 73051          # 01.01.2000 … 01.01.2100 числом Excel
_DAY_DMY = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)")
_DAY_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_CLOCK = r"(\d{1,2})(?:\s*[:.h]\s*(\d{2}))?(?::\d{2})?\s*(am|pm)?"
_HOURS = re.compile(rf"{_CLOCK}(?:\s*(?:-|–|—|până la|pana la|до)\s*{_CLOCK})?", re.I)
_LEAD = re.compile(r"^(?:[,;]|\s|t(?=\d)|ora\b|orele\b|la\b|în\b|в\b|с\b)+", re.I)


@dataclass(frozen=True)
class When:
    """Дата и час визита из ячеек файла — как в файле, до округления к сетке журнала."""
    day: _dt.date | None = None
    start: _dt.time | None = None
    minutes: int | None = None                    # из диапазона «09:30–10:30»
    source: str = ""                              # час как в файле: «09:07», «09:30–10:30»
    problem: str = ""                             # код из WHEN_PROBLEMS или ""

    def slot(self, tz) -> tuple[_dt.datetime, int | None] | None:
        """(начало по стенным часам `tz`, длина) к сетке 5 минут — правилом Google
        (`gimport.round_slot`): начало к ближайшим, длина вверх. Без даты и часа — None."""
        if self.problem or self.day is None or self.start is None:
            return None
        from . import gimport
        begin, minutes = gimport.round_slot(_dt.datetime.combine(self.day, self.start, tzinfo=tz),
                                            self.minutes or 0)
        return begin.astimezone(tz), (minutes if self.minutes else None)

    def rounded(self, tz) -> bool:
        """Округление сдвинуло начало или длину: исходный час — в комментарий записи."""
        got = self.slot(tz)
        return got is not None and (got[0].time() != self.start or got[1] != self.minutes)


def _hhmm(t: _dt.time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _clock(h: str, m: str | None, ampm: str | None) -> _dt.time | None:
    hour, minute = int(h), int(m) if m else 0
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    return _dt.time(hour, minute)


def _hours(text: str) -> tuple[_dt.time | None, _dt.time | None, str]:
    """Час или диапазон текстом: (начало, конец, код). Пусто — `NO_TIME`."""
    s = _LEAD.sub("", text.strip()).strip()
    if not s:
        return None, None, NO_TIME
    m = _HOURS.fullmatch(s.rstrip(" .,;"))
    if not m:
        return None, None, BAD_TIME
    begin = _clock(m.group(1), m.group(2), m.group(3) or m.group(6))
    if begin is None:
        return None, None, BAD_TIME
    if m.group(4) is None:
        return begin, None, ""
    end = _clock(m.group(4), m.group(5), m.group(6) or m.group(3))
    if end is None:
        return None, None, BAD_TIME
    return begin, end, "" if end > begin else BAD_RANGE


def _day_text(s: str) -> tuple[_dt.date | None, str, str]:
    """Дата в начале текста: (дата, остаток — час, код). День первым: «1/2/26» — первое февраля."""
    if re.fullmatch(r"\d{5}(?:\.\d+)?", s):
        if not _SERIAL_MIN <= float(s) < _SERIAL_MAX:
            return None, "", BAD_DATE
        v = _serial_moment(s, False)
        if isinstance(v, _dt.datetime):
            return v.date(), _hhmm(v.time()), ""
        return v, "", ""
    if m := _DAY_ISO.match(s):
        y, mo, da = map(int, m.groups())
    elif m := _DAY_DMY.match(s):
        da, mo, y = map(int, m.groups())
        y += 2000 if y < 100 else 0
    else:
        return None, "", BAD_DATE
    try:
        return _dt.date(y, mo, da), s[m.end():], ""
    except ValueError:
        return None, "", BAD_DATE


def _time_cell(v) -> tuple[_dt.time | None, _dt.time | None, str]:
    if isinstance(v, _dt.datetime):
        v = v.time()
    if isinstance(v, _dt.time):
        return v, None, ""
    if isinstance(v, _dt.date):
        return None, None, BAD_TIME
    s = str(v).strip()
    if re.fullmatch(r"0?\.\d+", s):               # время, потерявшее формат ячейки: доля суток
        t = _serial_time(s)
        return (t, None, "") if isinstance(t, _dt.time) else (None, None, BAD_TIME)
    return _hours(s)


def when(day, hour=None) -> When:
    """Дата и час визита из ячеек `read(..., times=True)`: дата-время одной ячейкой (числом Excel,
    ISO или текстом «21.11.2026 09:30», «21.11.2026, 9.30», «2026-11-21T09:30»), или дата и час
    раздельными колонками (`hour` — время Excel, «09:30», «9.30», «9h30», «9», «09:30–10:30»).
    Диапазон даёт длительность. Час колонки `hour` сильнее часа в ячейке даты. Полночь — «без
    часа» (`NO_TIME`): Excel хранит дату без часа как полночь."""
    if isinstance(day, str):
        day = day.strip() or None
    if day is None:
        return When(problem=NO_DATE)
    rest = ""
    if isinstance(day, _dt.datetime):
        d, rest = day.date(), _hhmm(day.time())
    elif isinstance(day, _dt.date):
        d = day
    elif isinstance(day, _dt.time):
        return When(problem=BAD_DATE)
    else:
        d, rest, code = _day_text(str(day))
        if code:
            return When(problem=code)
    if d.year < 1900:
        return When(problem=BAD_DATE)
    if hour is not None and str(hour).strip():
        begin, end, code = _time_cell(hour)
    else:
        begin, end, code = _hours(rest)
    if not code and begin == _dt.time(0, 0) and end is None:
        code = NO_TIME
    if code:
        return When(day=d, problem=code)
    span = None
    source = _hhmm(begin)
    if end is not None:
        span = (end.hour * 60 + end.minute) - (begin.hour * 60 + begin.minute)
        source += "–" + _hhmm(end)
    return When(day=d, start=begin, minutes=span, source=source)
