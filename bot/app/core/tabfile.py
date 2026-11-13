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


@dataclass
class Table:
    kind: str                                     # xlsx | csv
    sheets: list
    enc: str = ""
    delim: str = ""


def read(blob: bytes, name: str = "", *, enc: str = "", delim: str = "") -> Table:
    if len(blob) > MAX_FILE:
        raise Refuse("too_big")
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if blob[:8] == _OLE or ext == "xls":
        raise Refuse("old_xls")
    if blob[:2] == b"PK":
        return Table("xlsx", _read_xlsx(blob))
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


def _iso_date(text: str):
    """Ячейка типа «дата» несёт ISO-текст; время и пояс отбрасываются, пояс
    не применяется — иначе день рождения сдвинулся бы на сутки."""
    try:
        return _dt.date.fromisoformat(text.strip()[:10])
    except ValueError:
        return text


def _read_xlsx(blob: bytes) -> list:
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
        out.append(Sheet(sh.get("name", ""), _sheet_rows(_xml(z, path), shared,
                                                         date_styles, date1904)))
    if not out:
        raise Refuse("empty")
    return out


def _sheet_rows(root, shared: list, date_styles: set, date1904: bool) -> list:
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
            val = _cell(c, shared, date_styles, date1904)
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


def _cell(c, shared: list, date_styles: set, date1904: bool):
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
        val = _iso_date(text) if text else None
    elif t == "b":
        val = "da" if text == "1" else None
    elif t == "e":
        val = None
    elif text:
        s = c.get("s", "0")
        if s.isdigit() and int(s) in date_styles:
            val = _serial_date(text, date1904)
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
