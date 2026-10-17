"""Cont de plată клинике после оплаты (шаг 3 оплаты, 17.10.2026) — PDF из снимка.

Что это за документ. Поставщик — antreprenor independent (Legea 228/2025, гл. 10⁴
НК): не плательщик TVA, бухучёта не ведёт, factura fiscală через e-Factura не
выписывает — доход подтверждают банковские счета, учтённые SFS. Бухгалтеру
клиники после оплаты всё же нужен лист с реквизитами обеих сторон, предметом,
суммой и отметкой об оплате: это он и есть — «Cont de plată nr. …» с отметкой
ACHITAT, без TVA и без претензии быть фискальным документом (разбор — память
сессии, `legal-invoicing-antreprenor-independent`). SRL и e-Factura — позже;
тогда этот модуль остаётся снимком, а меняется только то, что печатается.

Устройство:
- строка `receipts` рождается в `payments.confirm` — на КАЖДЫЙ оплаченный платёж
  любого вида (абонемент, пакет SMS, имя отправителя), один раз (payment_id —
  ключ). Номер документа = reference платежа: он уже напечатан в ноте и в
  назначении перевода, второй нумерации бухгалтеру не нужно;
- `data` — СНИМОК на момент оплаты (реквизиты продавца из окружения, клиники из
  её строки, предмет, сумма, чем оплачено): клиника потом правит адрес или
  название, а документ, который уже у бухгалтера, не меняется;
- PDF рисуется из снимка при каждом запросе (`render`), в базе не хранится —
  снимок мал, а шрифт тяжёл;
- платежи, оплаченные ДО этой таблицы, получают снимок при первом запросе
  (`ensure`) — из того, что известно сейчас; ссылка на PDF у оплаченного платежа
  поэтому ведёт на документ всегда.
⛔ Константы видов платежа здесь — строки, равные payments.LICENSE/SMS/SMS_NAME:
импорт payments отсюда замкнул бы круг (payments импортирует этот модуль).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime

from . import config, db, pdf, sms

NUMBER_RE = re.compile(r"^DP-\d{4}-\d{6}$")
# то же, что в config.BANK: продавец — Олег, статус из закона 228/2025
SELLER_FORM = "antreprenor independent (Legea nr. 228/2025)"
TEAL = (0.055, 0.624, 0.541)
GREEN = (0.09, 0.55, 0.3)
GREY = (0.42, 0.45, 0.5)
LIGHT = (0.95, 0.96, 0.97)
INK = (0.1, 0.12, 0.15)
METHOD = {"card": "plată cu cardul (maib)", "transfer": "transfer bancar"}


def filename(number: str) -> str:
    # без диакритики: почтовые программы и браузеры переносят имя как есть
    return f"Cont-de-plata-{number}.pdf"


def _d(ts: str | None) -> str:
    """Отметка UTC из базы → день по Кишинёву dd.mm.yyyy (как видит клиника)."""
    at = db.parse_ts(ts)
    return sms.local(at).strftime("%d.%m.%Y") if at else ""


def money(v: int | float) -> str:
    """5489 → «5 489,00»: разряды пробелом, копейки запятой — как в банковских документах РМ."""
    whole, frac = f"{float(v):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return " ".join(groups) + "," + frac


def item_for(con: sqlite3.Connection, p: sqlite3.Row, period: tuple[datetime, datetime] | None = None) -> dict:
    """Предмет платежа строкой документа. `period` — срок абонемента (от, до), когда
    известен (в confirm); иначе — только длительность."""
    kind = p["kind"] if "kind" in p.keys() else "license"
    if kind == "sms":
        return {"title": "Pachet SMS DentPilot", "detail": f"{p['sms_units']} SMS — remindere pentru pacienți"}
    if kind == "sms_name":
        row = con.execute("SELECT sender FROM sms_accounts WHERE clinic_id=?", (p["clinic_id"],)).fetchone()
        name = (row["sender"] if row else "") or "—"
        return {"title": "Nume de expeditor SMS", "detail": f"«{name}» — un an"}
    months = int(p["months"] or 0)
    luni = f"{months} {'lună' if months == 1 else 'luni'}"
    detail = f"abonament pentru {luni}"
    if period:
        detail += f", {sms.local(period[0]).strftime('%d.%m.%Y')} – {sms.local(period[1]).strftime('%d.%m.%Y')}"
    return {"title": "Abonament DentPilot — program de evidență pentru clinica stomatologică", "detail": detail}


def get(con: sqlite3.Connection, payment_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM receipts WHERE payment_id=?", (payment_id,)).fetchone()


def by_number(con: sqlite3.Connection, number: str) -> sqlite3.Row | None:
    if not NUMBER_RE.match(number or ""):
        return None
    return con.execute("SELECT * FROM receipts WHERE number=?", (number,)).fetchone()


def create(con: sqlite3.Connection, payment_id: int, who: str,
           period: tuple[datetime, datetime] | None = None) -> sqlite3.Row:
    """Снимок оплаченного платежа — один раз; повтор возвращает прежний.
    ⛔ Неоплаченный — ValueError('not_paid'): документа об оплате без оплаты нет."""
    have = get(con, payment_id)
    if have is not None:
        return have
    p = con.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if p is None or p["status"] != "paid":
        raise ValueError("not_paid")
    c = con.execute("SELECT * FROM clinics WHERE id=?", (p["clinic_id"],)).fetchone()
    b = config.BANK
    data = {
        "number": p["reference"], "issued_at": p["paid_at"] or db.now_iso(),
        "seller": {"name": b["beneficiary"], "form": SELLER_FORM, "idno": b["code"], "iban": b["iban"],
                   "bank": b["bank"], "address": config.SELLER_ADDRESS,
                   "email": config.SUPPORT_EMAIL, "phone": config.SUPPORT_PHONE},
        "buyer": {"name": c["name"], "idno": c["idno"], "address": c["address"], "email": c["email"]},
        "item": item_for(con, p, period),
        "amount": int(p["amount"]), "currency": p["currency"] or "MDL",
        "paid_at": p["paid_at"], "paid_via": p["paid_via"] or "transfer", "reference": p["reference"],
        "kind": p["kind"] if "kind" in p.keys() else "license",
    }
    # без строки в журнале: документ — следствие payment_paid, а не отдельное действие
    # (test_payments держит последовательность журнала оплаты)
    con.execute("INSERT INTO receipts(payment_id, clinic_id, number, issued_at, data) VALUES(?,?,?,?,?)",
                (payment_id, p["clinic_id"], data["number"], data["issued_at"],
                 json.dumps(data, ensure_ascii=False)))
    return get(con, payment_id)


def ensure(con: sqlite3.Connection, payment: sqlite3.Row, who: str) -> sqlite3.Row | None:
    """Документ оплаченного платежа; для оплаченных до таблицы — снимок сейчас.
    None — платёж не оплачен."""
    if payment["status"] != "paid":
        return None
    return create(con, payment["id"], who)


def render(row: sqlite3.Row) -> bytes:
    """PDF из снимка. Одна страница A4; порядок блоков — шапка, стороны, таблица,
    итог, отметка об оплате, примечания."""
    d = json.loads(row["data"])
    s, b, it = d["seller"], d["buyer"], d["item"]
    doc = pdf.Document(f"Cont de plată {d['number']} — DentPilot")
    L, R = 48.0, doc.w - 48.0
    width = R - L
    # шапка: бренд слева, отметка ACHITAT справа
    doc.text(L, 64, "DentPilot", 20, bold=True, color=TEAL)
    doc.text(L, 80, "program de evidență pentru clinica stomatologică · dentpilot.md", 8.5, color=GREY)
    doc.rect(R - 96, 46, 96, 26, (0.89, 0.96, 0.92))
    doc.text(R - 48, 64, "ACHITAT", 12, bold=True, color=GREEN, align="center")
    doc.text(R, 92, f"Data: {_d(d['issued_at'])}", 9.5, color=GREY, align="right")
    doc.text(L, 122, f"Cont de plată nr. {d['number']}", 17, bold=True, color=INK)
    doc.line(L, 134, R, 134, 0.8, TEAL)
    # стороны
    col = width / 2 - 12
    y0 = 158.0
    doc.text(L, y0, "FURNIZOR", 8, bold=True, color=GREY)
    doc.text(L + col + 24, y0, "BENEFICIAR", 8, bold=True, color=GREY)
    y = y0 + 16
    y = doc.paragraph(L, y, s["name"] or "—", 11, col, bold=True, color=INK)
    for line in (s["form"], f"IDNO {s['idno']}" if s["idno"] else "",
                 f"IBAN {s['iban']}" if s["iban"] else "", f"Banca: {s['bank']}" if s["bank"] else "",
                 s["address"], f"{s['email']} · {s['phone']}"):
        if line:
            y = doc.paragraph(L, y, line, 9.5, col, color=INK)
    y_left = y
    x2, y = L + col + 24, y0 + 16
    y = doc.paragraph(x2, y, b["name"] or "—", 11, col, bold=True, color=INK)
    for line in (f"IDNO {b['idno']}" if b["idno"] else "IDNO —", b["address"], b["email"]):
        if line:
            y = doc.paragraph(x2, y, line, 9.5, col, color=INK)
    y = max(y, y_left) + 14
    # таблица
    # колонки: Nr | Denumire | Cant. | Preț | Suma — правые края числовых колонок
    # с запасом: ширина «5 489,00» (10 pt) ≈ 34 pt, шапки «Preț, MDL» (8.5 pt) ≈ 38 pt
    name_x, name_end, qty_r, price_r, sum_r = L + 28, L + 310, L + 352, L + 424, R - 4
    doc.rect(L, y - 12, width, 20, LIGHT)
    doc.text(L + 4, y + 2, "Nr.", 8.5, bold=True, color=GREY)
    doc.text(name_x, y + 2, "Denumirea serviciului", 8.5, bold=True, color=GREY)
    doc.text(qty_r, y + 2, "Cant.", 8.5, bold=True, color=GREY, align="right")
    doc.text(price_r, y + 2, "Preț, MDL", 8.5, bold=True, color=GREY, align="right")
    doc.text(sum_r, y + 2, "Suma, MDL", 8.5, bold=True, color=GREY, align="right")
    y += 26
    amount = money(d["amount"])
    doc.text(L + 4, y, "1", 10, color=INK)
    doc.text(qty_r, y, "1", 10, color=INK, align="right")
    doc.text(price_r, y, amount, 10, color=INK, align="right")
    doc.text(sum_r, y, amount, 10, bold=True, color=INK, align="right")
    y = doc.paragraph(name_x, y, it["title"], 10, name_end - name_x, bold=True, color=INK)
    y = doc.paragraph(name_x, y, it["detail"], 9, name_end - name_x, color=GREY)
    y += 4
    doc.line(L, y, R, y, 0.6, (0.8, 0.82, 0.85))
    y += 22
    total = f"{amount} {d['currency']}"
    doc.text(sum_r, y, total, 13, bold=True, color=INK, align="right")
    doc.text(sum_r - doc.width(total, 13, True) - 10, y, "Total de plată:", 11, color=INK, align="right")
    y += 16
    doc.text(R - 4, y, "Fără TVA — furnizorul nu este plătitor de TVA.", 8.5, color=GREY, align="right")
    # отметка об оплате
    y += 26
    doc.rect(L, y - 14, width, 40, (0.89, 0.96, 0.92))
    doc.text(L + 12, y + 2, f"Achitat la {_d(d['paid_at'])} prin {METHOD.get(d['paid_via'], d['paid_via'])}.",
             10.5, bold=True, color=GREEN)
    doc.text(L + 12, y + 17, f"Referința plății: {d['reference']}. Serviciul este prestat; plata a fost primită integral.",
             9, color=INK)
    # примечания
    y += 56
    notes = (
        "Furnizorul activează în regimul fiscal al antreprenorului independent (Legea nr. 228/2025) și nu "
        "emite factură fiscală; prezentul cont, împreună cu extrasul bancar al plății, confirmă serviciul și plata.",
        "Document generat electronic de DentPilot Cloud și valabil fără semnătură și ștampilă. Îl găsiți oricând "
        f"în contul clinicii, {config.BASE_URL.rstrip('/')}/cont.",
    )
    for note in notes:
        y = doc.paragraph(L, y, note, 8.5, width, color=GREY) + 4
    return doc.build()


def attachment(con: sqlite3.Connection, payment: sqlite3.Row, who: str) -> tuple[str, bytes] | None:
    """(имя файла, PDF) для письма об оплате или None — платёж не оплачен."""
    row = ensure(con, payment, who)
    if row is None:
        return None
    return filename(row["number"]), render(row)
