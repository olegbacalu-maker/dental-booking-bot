"""Таблица Excel одним файлом — без сторонних библиотек.

Зачем вообще, если есть CSV: CSV не несёт ТИПОВ, и Excel их угадывает. На
выгрузке журнала он угадывает дважды и оба раза плохо — `022447788`
превращается в число `22447788` (в Молдове все номера с нуля, то есть звонить
по такой таблице нельзя), а дата не влезает в колонку по умолчанию и выходит
как `########`. Первое незаметно, и это хуже: `########` кричит, а укороченный
номер выглядит нормальным.

Здесь xlsx пишется руками: это zip с несколькими XML внутри, а `zipfile` —
стандартная библиотека. ⛔ Ставить openpyxl нельзя: `.venv-desktop` — окружение
сборки, всё лишнее уезжает в exe (единственное исключение, pyzipper, живёт В
САМОЙ программе ради зашифрованного бэкапа).

Умеет ровно то, что нужно журналу: строка (остаётся строкой), число, дата,
жирная шапка, ширины колонок, закреплённая первая строка и автофильтр.
⛔ Порядок элементов внутри `<worksheet>` задан схемой OOXML и произволен быть
не может: cols → sheetData → autoFilter. Переставишь — Excel объявит файл
повреждённым, причём молча предложит «восстановить».
"""
from __future__ import annotations

import datetime as _dt
import io
import zipfile

# Точка отсчёта дат в Excel — 1899-12-30, а не 1900-01-01: в нём намеренно
# оставлена ошибка Lotus 1-2-3 (1900 год считается високосным), и смещение на
# два дня компенсирует её для всех дат после 1900-03-01.
_EPOCH = _dt.date(1899, 12, 30)

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WB_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# ⚠️ Два наполнения (fills) обязательны, даже если оба пустые: Excel требует
# none + gray125 первыми и без них считает книгу повреждённой.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="dd\\.mm\\.yyyy"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

S_PLAIN, S_HEAD, S_DATE = 0, 1, 2


def _esc(text: str) -> str:
    """XML-экранирование + выброс управляющих символов.

    ⚠️ Управляющие символы Excel не прощает: комментарий регистратуры с \\x0b
    внутри сделал бы книгу «повреждённой» — а вставляют туда что угодно, вплоть
    до текста из Word.
    """
    out = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
               .replace('"', "&quot;"))
    return "".join(c for c in out if c >= " " or c in "\t\n")[:32000]


def _col(i: int) -> str:
    """Номер колонки → буквенное имя (0 → A, 26 → AA)."""
    name = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell(ref: str, value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):                      # раньше int: bool это int
        value = "da" if value else ""
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    if isinstance(value, _dt.datetime):
        value = value.date()
    if isinstance(value, _dt.date):
        return f'<c r="{ref}" s="{S_DATE}"><v>{(value - _EPOCH).days}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    # ⭐ Всё остальное — СТРОКА, и это главное отличие от CSV: телефон
    # `022447788` доедет до клиники с нулём, а не числом.
    txt = _esc(str(value))
    if not txt:
        return ""
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{txt}</t></is></c>'


def book(header: list, rows: list, widths: list | None = None,
         sheet_name: str = "Programari") -> bytes:
    """Одна таблица → байты .xlsx. `widths` — в знаках, по колонкам."""
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        # закреплённая шапка: в журнале на сотню строк без неё не понять,
        # какая колонка какая, уже на втором экране
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" '
        'topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
    ]
    if widths:
        out.append("<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)) + "</cols>")
    out.append("<sheetData>")
    out.append('<row r="1">' + "".join(
        f'<c r="{_col(i)}1" s="{S_HEAD}" t="inlineStr"><is><t>{_esc(str(h))}</t></is></c>'
        for i, h in enumerate(header)) + "</row>")
    for n, row in enumerate(rows, start=2):
        cells = "".join(_cell(f"{_col(i)}{n}", v) for i, v in enumerate(row))
        out.append(f'<row r="{n}">{cells}</row>')
    out.append("</sheetData>")
    # автофильтр — после sheetData (порядок задан схемой): клиника фильтрует
    # выгрузку по врачу или статусу, не переписывая её
    out.append(f'<autoFilter ref="A1:{_col(len(header) - 1)}{len(rows) + 1}"/>')
    out.append("</worksheet>")
    sheet_xml = "".join(out)

    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          f'<sheets><sheet name="{_esc(sheet_name)[:31]}" sheetId="1" r:id="rId1"/></sheets>'
          "</workbook>")

    buf = io.BytesIO()
    # ⚠️ Дата в zip фиксированная: без неё архив зависит от часов машины, и два
    # одинаковых экспорта дают разные байты — сравнивать нечем ни в проверках,
    # ни глазами.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("[Content_Types].xml", _CT), ("_rels/.rels", _RELS),
                           ("xl/workbook.xml", wb), ("xl/_rels/workbook.xml.rels", _WB_RELS),
                           ("xl/styles.xml", _STYLES),
                           ("xl/worksheets/sheet1.xml", sheet_xml)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()
