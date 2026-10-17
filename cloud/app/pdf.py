"""PDF одним файлом — без сторонних библиотек (тот же приём, что xlsx.py).

Зачем: клинике после оплаты уходит cont de plată (receipts.py) — лист A4,
который бухгалтер кладёт в папку. Библиотеки PDF в `cloud/.venv` нет и ставить
её ради одного листа не стоит: формат прост, а `zlib` и `struct` — стандартная
библиотека. Умеет ровно то, что нужно листу: текст двумя начертаниями, линии,
прямоугольники, перенос строк, выравнивание вправо, одна страница.

Шрифт. Стандартные 14 шрифтов PDF (Helvetica) не несут ă/â/î/ș/ț — румынский
документ ими не набрать. Поэтому в файл ВШИВАЕТСЯ TrueType из `app/assets`
(Inter — тот же, что на сайте и в программе; лицензия OFL разрешает) как
Type0/Identity-H: текст пишется номерами глифов, ширины берутся из таблицы
`hmtx`, ToUnicode даёт поиск и копирование текста. Подмножество не режется —
файл шрифта едет целиком, сжатый (≈200 КБ на документ; клинике это раз в месяц).
⛔ Без файла шрифта — запасной режим: Helvetica, диакритика снимается
(ă→a, ș→s, ț→t): документ читается, но «Cont de plata». Режим молчал бы, поэтому
о нём говорит `python -m app.tools check` (`font_status`), а не день, когда
клиника спросит, почему без ș.
"""
from __future__ import annotations

import pathlib
import re
import struct
import zlib
from datetime import datetime, timezone

A4 = (595.28, 841.89)
ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
REGULAR, BOLD = "Inter-Regular.ttf", "Inter-SemiBold.ttf"

# Запасной режим: что сделать с буквами, которых нет в WinAnsi (cp1252)
_TRANSLIT = str.maketrans({"ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
                           "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ş": "S", "Ț": "T", "Ţ": "T",
                           "«": '"', "»": '"', "„": '"', "”": '"', "’": "'", "—": "-", "–": "-",
                           " ": " ", "·": "-"})

# Ширины Helvetica / Helvetica-Bold (AFM, тысячные em) для знаков 32–126 — только
# чтобы выравнивать вправо и переносить строки; остальным знакам — 556
_W_REG = (278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
          556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778,
          722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
          278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
          556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584)
_W_BOLD = (278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
           556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778,
           722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333,
           278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
           611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584)


def _esc(s: bytes) -> bytes:
    return s.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class Standard:
    """Один из 14 стандартных шрифтов, WinAnsiEncoding; румынские буквы упрощаются."""

    embedded = False

    def __init__(self, base: str, widths: tuple):
        self.base, self._w = base, widths

    def plain(self, s: str) -> str:
        return s.translate(_TRANSLIT)

    def width(self, s: str) -> float:
        return sum(self._w[ord(ch) - 32] if 32 <= ord(ch) <= 126 else 556 for ch in self.plain(s))

    def show(self, s: str) -> bytes:
        return b"(" + _esc(self.plain(s).encode("cp1252", "replace")) + b")"

    def objects(self, doc: "Document") -> int:
        return doc.add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{self.base} /Encoding /WinAnsiEncoding >>"
                       .encode("ascii"))


class TrueType:
    """TrueType из файла, вшитый целиком как CIDFontType2 (Identity-H)."""

    embedded = True

    def __init__(self, data: bytes, name: str):
        self.data = data
        self.tables: dict[str, tuple[int, int]] = {}
        if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"true"):
            raise ValueError("не TrueType (OpenType с CFF и woff не годятся)")
        num = struct.unpack(">H", data[4:6])[0]
        for i in range(num):
            tag, _, off, ln = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
            self.tables[tag.decode("latin-1")] = (off, ln)
        head = self._table("head")
        self.upem = struct.unpack(">H", head[18:20])[0] or 1000
        self.bbox = struct.unpack(">4h", head[36:44])
        hhea = self._table("hhea")
        self.ascent, self.descent = struct.unpack(">2h", hhea[4:8])
        nhm = struct.unpack(">H", hhea[34:36])[0]
        hmtx = self._table("hmtx")
        self.adv = [struct.unpack(">H", hmtx[4 * i:4 * i + 2])[0] for i in range(nhm)]
        self.cmap = self._cmap()
        self.name = re.sub(r"[^A-Za-z0-9-]", "", name) or "Embedded"
        self.cap = 0
        if "OS/2" in self.tables:
            os2 = self._table("OS/2")
            if len(os2) >= 90:
                self.cap = struct.unpack(">h", os2[88:90])[0]
        if self.cap <= 0:
            self.cap = int(self.upem * 0.7)
        self.used: dict[int, int] = {}          # глиф → знак (для /W и ToUnicode)
        self.fallback = self.cmap.get(ord("?"), 0)

    def _table(self, tag: str) -> bytes:
        off, ln = self.tables[tag]
        return self.data[off:off + ln]

    def _cmap(self) -> dict[int, int]:
        sub = self._table("cmap")
        n = struct.unpack(">H", sub[2:4])[0]
        best = None
        for i in range(n):
            pid, _eid, off = struct.unpack(">HHI", sub[4 + 8 * i:12 + 8 * i])
            fmt = struct.unpack(">H", sub[off:off + 2])[0]
            rank = {12: 2, 4: 1}.get(fmt)
            if rank and pid in (0, 3) and (best is None or rank > best[0]):
                best = (rank, fmt, off)
        if best is None:
            raise ValueError("cmap: нет подтаблицы формата 4 или 12")
        _, fmt, off = best
        m: dict[int, int] = {}
        if fmt == 4:
            segx2 = struct.unpack(">H", sub[off + 6:off + 8])[0]
            seg = segx2 // 2
            ends = struct.unpack(f">{seg}H", sub[off + 14:off + 14 + segx2])
            p = off + 16 + segx2
            starts = struct.unpack(f">{seg}H", sub[p:p + segx2])
            p += segx2
            deltas = struct.unpack(f">{seg}h", sub[p:p + segx2])
            p += segx2
            ro_pos = p
            ros = struct.unpack(f">{seg}H", sub[p:p + segx2])
            for i in range(seg):
                for ch in range(starts[i], min(ends[i], 0xFFFE) + 1):
                    if ros[i] == 0:
                        g = (ch + deltas[i]) & 0xFFFF
                    else:
                        gp = ro_pos + 2 * i + ros[i] + 2 * (ch - starts[i])
                        g = struct.unpack(">H", sub[gp:gp + 2])[0]
                        if g:
                            g = (g + deltas[i]) & 0xFFFF
                    if g:
                        m[ch] = g
        else:
            ngroups = struct.unpack(">I", sub[off + 12:off + 16])[0]
            for i in range(ngroups):
                s, e, g = struct.unpack(">III", sub[off + 16 + 12 * i:off + 28 + 12 * i])
                for ch in range(s, min(e, 0xFFFF) + 1):
                    m[ch] = g + (ch - s)
        return m

    def _gid(self, ch: str) -> int:
        return self.cmap.get(ord(ch), self.fallback)

    def _adv(self, gid: int) -> float:
        return self.adv[min(gid, len(self.adv) - 1)] * 1000.0 / self.upem

    def width(self, s: str) -> float:
        return sum(self._adv(self._gid(ch)) for ch in s)

    def show(self, s: str) -> bytes:
        out = []
        for ch in s:
            g = self._gid(ch)
            self.used.setdefault(g, ord(ch))
            out.append(f"{g:04X}")
        return b"<" + "".join(out).encode("ascii") + b">"

    def objects(self, doc: "Document") -> int:
        scale = 1000.0 / self.upem
        prog = zlib.compress(self.data, 6)
        ff = doc.add(f"<< /Length {len(prog)} /Length1 {len(self.data)} /Filter /FlateDecode >>".encode("ascii"),
                     prog)
        bbox = " ".join(str(int(round(v * scale))) for v in self.bbox)
        fd = doc.add((f"<< /Type /FontDescriptor /FontName /{self.name} /Flags 32 /FontBBox [{bbox}] "
                      f"/ItalicAngle 0 /Ascent {int(round(self.ascent * scale))} "
                      f"/Descent {int(round(self.descent * scale))} /CapHeight {int(round(self.cap * scale))} "
                      f"/StemV 80 /FontFile2 {ff} 0 R >>").encode("ascii"))
        w = " ".join(f"{g} [{int(round(self._adv(g)))}]" for g in sorted(self.used))
        cid = doc.add((f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{self.name} "
                       f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
                       f"/FontDescriptor {fd} 0 R /DW 1000 /W [{w}] /CIDToGIDMap /Identity >>").encode("ascii"))
        tu = doc.add(b"", self._tounicode())
        return doc.add((f"<< /Type /Font /Subtype /Type0 /BaseFont /{self.name} /Encoding /Identity-H "
                        f"/DescendantFonts [{cid} 0 R] /ToUnicode {tu} 0 R >>").encode("ascii"))

    def _tounicode(self) -> bytes:
        pairs = sorted(self.used.items())
        chunks = []
        for i in range(0, len(pairs), 100):
            part = pairs[i:i + 100]
            body = "\n".join(f"<{g:04X}> <{_utf16(ch)}>" for g, ch in part)
            chunks.append(f"{len(part)} beginbfchar\n{body}\nendbfchar")
        text = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
                "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
                "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
                "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
                + "\n".join(chunks) + "\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n")
        return text.encode("ascii")


def _utf16(cp: int) -> str:
    return "".join(f"{b:02X}" for b in chr(cp).encode("utf-16-be"))


def load(path: pathlib.Path):
    """TrueType из файла или None: файла нет, или это не TrueType."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        return TrueType(data, path.stem)
    except (ValueError, KeyError, struct.error):
        return None


def fonts() -> tuple:
    """(обычный, жирный): Inter из app/assets, если лежит; иначе Helvetica.
    Жирного файла нет, а обычный есть — жирный ТОТ ЖЕ Inter (документ без
    выделений лучше смеси Inter с Helvetica)."""
    regular = load(ASSETS / REGULAR)
    if regular is None:
        return Standard("Helvetica", _W_REG), Standard("Helvetica-Bold", _W_BOLD)
    return regular, load(ASSETS / BOLD) or regular


def font_status() -> tuple[bool, str]:
    """(вшивается ли шрифт, строка для `tools check`)."""
    regular, bold = fonts()
    if not regular.embedded:
        return False, (f"шрифта {REGULAR} нет в {ASSETS}: cont de plată уходит Helvetica, без диакритики "
                       f"(ă→a, ș→s, ț→t) — положите Inter (OFL) в app/assets")
    extra = "" if bold is not regular else f"; {BOLD} нет — выделения тем же начертанием"
    return True, f"шрифт PDF: {REGULAR} вшивается в cont de plată{extra}"


def _n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _rgb(c: tuple) -> str:
    return " ".join(_n(x) for x in c)


class Document:
    """Один лист A4. Координаты — в пунктах от ЛЕВОГО ВЕРХНЕГО угла (как в CSS),
    в PDF переводятся при записи."""

    def __init__(self, title: str, regular=None, bold=None):
        self.w, self.h = A4
        self.title = title
        if regular is None:
            regular, bold = fonts()
        self._fonts = {"F1": regular, "F2": bold or regular}
        self.ops: list[str] = []
        self._objs: list[bytes] = []

    # ---------- рисование ----------

    def _font(self, bold: bool):
        return ("F2", self._fonts["F2"]) if bold else ("F1", self._fonts["F1"])

    def width(self, s: str, size: float, bold: bool = False) -> float:
        return self._font(bold)[1].width(s) * size / 1000.0

    def text(self, x: float, y: float, s: str, size: float = 10, bold: bool = False,
             color: tuple = (0, 0, 0), align: str = "left") -> float:
        """Строка с базовой линией на высоте `y` от верха. Возвращает ширину."""
        if not s:
            return 0.0
        fid, font = self._font(bold)
        w = font.width(s) * size / 1000.0
        if align == "right":
            x -= w
        elif align == "center":
            x -= w / 2
        self.ops.append(f"BT /{fid} {_n(size)} Tf {_rgb(color)} rg 1 0 0 1 {_n(x)} {_n(self.h - y)} Tm "
                        + font.show(s).decode("latin-1") + " Tj ET")
        return w

    def wrap(self, s: str, size: float, max_w: float, bold: bool = False) -> list[str]:
        """Перенос по словам; слово шире строки остаётся как есть."""
        lines, cur = [], ""
        for word in s.split():
            cand = f"{cur} {word}" if cur else word
            if cur and self.width(cand, size, bold) > max_w:
                lines.append(cur)
                cur = word
            else:
                cur = cand
        if cur:
            lines.append(cur)
        return lines

    def paragraph(self, x: float, y: float, s: str, size: float, max_w: float, bold: bool = False,
                  color: tuple = (0, 0, 0), leading: float | None = None) -> float:
        """Абзац с переносом; возвращает `y` базовой линии следующей строки."""
        lead = leading or size * 1.4
        for line in self.wrap(s, size, max_w, bold):
            self.text(x, y, line, size, bold, color)
            y += lead
        return y

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.6,
             color: tuple = (0, 0, 0)) -> None:
        self.ops.append(f"{_rgb(color)} RG {_n(width)} w {_n(x1)} {_n(self.h - y1)} m "
                        f"{_n(x2)} {_n(self.h - y2)} l S")

    def rect(self, x: float, y: float, w: float, h: float, color: tuple) -> None:
        self.ops.append(f"{_rgb(color)} rg {_n(x)} {_n(self.h - y - h)} {_n(w)} {_n(h)} re f")

    # ---------- запись ----------

    def add(self, head: bytes, stream: bytes | None = None) -> int:
        """Объект: словарь (+ поток). Возвращает его номер."""
        if stream is None:
            body = head
        else:
            dic = head if head else f"<< /Length {len(stream)} >>".encode("ascii")
            body = dic + b"\nstream\n" + stream + b"\nendstream"
        self._objs.append(body)
        return len(self._objs)

    def build(self) -> bytes:
        self._objs = []
        content = zlib.compress("\n".join(self.ops).encode("latin-1"), 6)
        # шрифты первыми: они не ссылаются на страницу, страница ссылается на них
        f1 = self._fonts["F1"].objects(self)
        f2 = f1 if self._fonts["F2"] is self._fonts["F1"] else self._fonts["F2"].objects(self)
        font_refs = {"F1": f1, "F2": f2}
        cont = self.add(f"<< /Length {len(content)} /Filter /FlateDecode >>".encode("ascii"), content)
        res = " ".join(f"/{fid} {n} 0 R" for fid, n in font_refs.items())
        pages_no = len(self._objs) + 2          # страница ссылается на Pages, который идёт за ней
        page = self.add((f"<< /Type /Page /Parent {pages_no} 0 R /MediaBox [0 0 {_n(self.w)} {_n(self.h)}] "
                         f"/Resources << /Font << {res} >> >> /Contents {cont} 0 R >>").encode("ascii"))
        pages = self.add(f"<< /Type /Pages /Kids [{page} 0 R] /Count 1 >>".encode("ascii"))
        assert pages == pages_no
        root = self.add(f"<< /Type /Catalog /Pages {pages} 0 R >>".encode("ascii"))
        when = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
        title = "FEFF" + "".join(f"{b:02X}" for b in self.title.encode("utf-16-be"))
        info = self.add(f"<< /Title <{title}> /Producer (DentPilot Cloud) /CreationDate ({when}) >>"
                        .encode("ascii"))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(self._objs, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(self._objs) + 1}\n0000000000 65535 f \n".encode("ascii")
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode("ascii")
        out += (f"trailer\n<< /Size {len(self._objs) + 1} /Root {root} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode("ascii")
        return bytes(out)
