"""Образцы таблиц для `test_pimport`: книги .xlsx, собранные «как из Excel» и
«как из библиотеки», и тексты CSV. Все люди выдуманы.

Писатель программы (`core/xlsx.book`) даёт только строки inline — здесь то,
чего он не пишет: общая таблица строк с «богатым текстом», даты стилем,
1904-я система дат, объединённые ячейки, несколько листов, ячейки типа «дата»
с ISO-текстом и теги с приставкой пространства имён.
"""
from __future__ import annotations

import datetime as dt
import io
import zipfile

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
EPOCH = dt.date(1899, 12, 30)
D = dt.date


def col(i: int) -> str:
    name, i = "", i + 1
    while i:
        i, rem = divmod(i - 1, 26)
        name = chr(65 + rem) + name
    return name


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;")


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, t in files.items():
            z.writestr(n, t)
    return buf.getvalue()


def excel_book(sheets: list, date1904: bool = False, hidden: tuple = ()) -> bytes:
    """Книга «как из Excel». `sheets` — [(имя, строки, объединения)]; строка
    None — пропущенная; ячейка: str, число, date (встроенный стиль 14),
    ("c", date) — свой формат даты."""
    sst: list[str] = []

    def s_idx(t: str) -> int:
        if t not in sst:
            sst.append(t)
        return sst.index(t)

    files = {}
    for k, (_name, rows, merges) in enumerate(sheets, start=1):
        x = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{M}"><sheetData>']
        for rn, row in enumerate(rows, start=1):
            if row is None:
                continue
            x.append(f'<row r="{rn}">')
            for ci, v in enumerate(row):
                if v is None:
                    continue
                ref = f"{col(ci)}{rn}"
                if isinstance(v, dt.date):
                    x.append(f'<c r="{ref}" s="1"><v>{(v - EPOCH).days - (1462 if date1904 else 0)}</v></c>')
                elif isinstance(v, tuple):
                    x.append(f'<c r="{ref}" s="2"><v>{(v[1] - EPOCH).days}</v></c>')
                elif isinstance(v, (int, float)):
                    x.append(f'<c r="{ref}"><v>{v!r}</v></c>')
                else:
                    x.append(f'<c r="{ref}" t="s"><v>{s_idx(v)}</v></c>')
            x.append("</row>")
        x.append("</sheetData>")
        if merges:
            x.append(f'<mergeCells count="{len(merges)}">'
                     + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>")
        x.append("</worksheet>")
        files[f"xl/worksheets/sheet{k}.xml"] = "".join(x)
    # длинные строки — двумя кусками «богатого текста», как после правки шрифта в ячейке
    files["xl/sharedStrings.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{M}">'
        + "".join(f'<si><r><t>{_esc(t[:2])}</t></r><r><t xml:space="preserve">{_esc(t[2:])}</t></r></si>'
                  if len(t) > 6 else f"<si><t>{_esc(t)}</t></si>" for t in sst) + "</sst>")
    files["xl/styles.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{M}">'
        '<numFmts count="1"><numFmt numFmtId="170" formatCode="dd/mm/yyyy;@"/></numFmts>'
        '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="170"/></cellXfs>'
        "</styleSheet>")
    files["xl/workbook.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{M}" xmlns:r="{R}">'
        + ('<workbookPr date1904="1"/>' if date1904 else "") + "<sheets>"
        + "".join(f'<sheet name="{_esc(n)}" sheetId="{k}" r:id="rId{k}"'
                  + (' state="hidden"' if n in hidden else "") + "/>"
                  for k, (n, _r, _m) in enumerate(sheets, 1))
        + "</sheets></workbook>")
    files["xl/_rels/workbook.xml.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{P}">'
        + "".join(f'<Relationship Id="rId{k}" Type="x" Target="worksheets/sheet{k}.xml"/>'
                  for k in range(1, len(sheets) + 1)) + "</Relationships>")
    files["[Content_Types].xml"] = "<Types/>"
    return _zip(files)


def library_book(header: list, rows: list) -> bytes:
    """Книга «как из библиотеки»: теги с приставкой `x:`, текст в ячейках
    типа `str`, дата — ISO-текстом с временем и «Z» в ячейке типа `d`."""
    x = [f'<?xml version="1.0" encoding="UTF-8"?><x:worksheet xmlns:x="{M}"><x:sheetData>']
    for rn, row in enumerate([header, *rows], start=1):
        x.append(f'<x:row r="{rn}">')
        for ci, v in enumerate(row):
            if v is None:
                continue
            ref = f"{col(ci)}{rn}"
            if isinstance(v, dt.date):
                x.append(f'<x:c r="{ref}" t="d"><x:v>{v.isoformat()}T00:00:00.000Z</x:v></x:c>')
            elif isinstance(v, (int, float)):
                x.append(f'<x:c r="{ref}"><x:v>{v!r}</x:v></x:c>')
            else:
                x.append(f'<x:c r="{ref}" t="str"><x:v>{_esc(str(v))}</x:v></x:c>')
        x.append("</x:row>")
    x.append("</x:sheetData></x:worksheet>")
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": (f'<?xml version="1.0" encoding="UTF-8"?><x:workbook xmlns:x="{M}" '
                            f'xmlns:r="{R}"><x:sheets><x:sheet name="Pacienți" sheetId="1" '
                            'r:id="rId1"/></x:sheets></x:workbook>'),
        "xl/_rels/workbook.xml.rels": (f'<?xml version="1.0" encoding="UTF-8"?><Relationships '
                                       f'xmlns="{P}"><Relationship Id="rId1" Type="x" '
                                       'Target="/xl/worksheets/sheet1.xml"/></Relationships>'),
        "xl/worksheets/sheet1.xml": "".join(x),
    })


# Лист «как ведёт клиника»: лента-заголовок, шапка в третьей строке, пустая
# строка, итог в конце, номера и IDNP числами, даты в трёх видах.
CLINIC = [
    ["Clinica „Zâmbet Test” — lista pacienților", None, None, None, None, None],
    None,
    ["Nr.", "Nume", "Prenume", "Telefon", "Data nașterii", "IDNP", "Adresă", "E-mail", "Observații"],
    [1, "Popescu", "Ion", 69555101, D(1985, 3, 14), 2001234567893.0, "Chișinău, str. Test 1",
     "ion@example.md", "alergie penicilină"],
    [2, "BĂLAN", "MARIA-ELENA", "+373 (79) 555-102", ("c", D(1990, 12, 1)), "2003456789012", None, None, None],
    [3, "Ţurcanu", "Ștefan", "069 555 103, 022 55 51 04", "14.07.1978", None, "Bălți", None, "fratele lui Ion"],
    None,
    [4, "Rusu", "Ana", "0695 55 105", "1/2/03", 200123456789, None, "ANA@EXAMPLE.MD", None],
    [5, "Popescu", "Ion", "069555101", D(1985, 3, 14), None, None, None, "dublu în fișier"],
    [6, None, None, "069555106", None, None, None, None, None],
    [7, "Ceban", "Vasile", "12", "31.02.1990", "12345", None, None, None],
    [8, "Munteanu", "Dan", None, 1975, None, None, None, None],
    ["Total: 8", None, None, None, None, None],
]
RU_SHEET = [["Doctor", "ФИО", "Телефон", "Дата рождения", "Примечание"],
            ["Dr. Activ Doi", "Иванов Пётр Сергеевич", "8 (911) 555-01-07", "5 марта 1969 г.", None],
            [None, "сидорова анна", "+37369555108 / 079555109", "1988-11-30", "VIP"],
            [None, "Гуцу Елена", 79555110, 31485, None]]

# Тот же вид, что у файла, с которого началась задача: два столбца телефона с
# одним номером, «IDNP (demo)», дата будущей записи, часть людей без телефона.
LIB_HEADER = ["ID", "Nume și prenume", "Data nașterii", "Data programării", "IDNP (demo)",
              "Telefon internațional", "Telefon local"]


def lib_rows(n: int, start: int = 0) -> list:
    out = []
    for i in range(start, start + n):
        tel = None if i % 5 == 4 else f"0695{60000 + i:05d}"
        out.append([i + 1, f"Testescu{i} Ana", D(1950 + i % 60, 1 + i % 12, 1 + i % 28),
                    D(2027, 1, 1 + i % 28),
                    None if i % 4 == 3 else f"999{i:010d}",
                    ("+373" + tel[1:]) if tel else None, tel])
    return out


CSV_RU = ("ФИО;Телефон;Дата рождения;Адрес\r\n"
          "Иванов Пётр;069555111;14.03.1985;Кишинёв, ул. Тестовая 1\r\n"
          "\"Сидорова; Анна\";+37379555112;;\r\n")
CSV_RO_COMMA = ("Nume,Prenume,Telefon,Data nașterii\n"
                "Țurcanu,Ștefan,069555113,14.07.1978\n"
                "\"Bălan, jr.\",Ion,079555114,\n")
CSV_RO_1250 = ("Nume;Prenume;Telefon\r\n"
               "Ţurcanu;Ştefan;069555115\r\n"
               "Bălan;Ion;079555116\r\n"
               "Râşcanu;Călin;068555117\r\n")
