"""Заявление клиники на имя отправителя SMS (бланк sms.md) — кабинет, 17.10.2026.

Зачем. sms.md клиник не знает: все имена висят на нашем аккаунте, а то, что
имя принадлежит клинике и она разрешила DentPilot им пользоваться, доказывает
только её подписанное заявление на бланке sms.md («Cerere pentru
activarea/crearea alias-ului SMS», получен 16.10). Кабинет даёт его двумя шагами:

1. `render` — PDF уже заполненный: реквизиты из строки клиники (те же, что в
   ноте и лицензии), имя из заявки, представитель — с формы кабинета (по
   умолчанию контактное лицо), даты — сегодня по Кишинёву. ⛔ Текст бланка —
   ИХ, без правок, с их опечатками: форма принадлежит sms.md. Заполнены только
   пропуски, в том числе кто пользуется именем и платформа (п. 2).
2. `attach` — подписанный PDF (ручкой и скан или подписью MSign) в базу;
   загрузка ставит отметку «Заявление получено» (`sender_paper_at`), дальше
   шаг Олега «Подано в sms.md».

⛔ Файл хранится в БАЗЕ (`sms_papers`), не на диске: копию базы увозит ПК
Олега, отдельный файл в неё не попал бы. Строки не удаляются — это бумага для
sms.md; заявление текущей заявки — `sms_accounts.sender_paper_id`.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone

from . import db, pdf, sms

MAX_BYTES = 5 * 1024 * 1024
REP_MAX = 80
# получатель бланка — реквизиты sms.md, как в их бланке
TO = ("Către: ROCK SOFT S.R.L", "IDNO: 1021600014623",
      "Adresa: mun. Chisinau, sec. Centru, str Doctor Tudor Strisca, 8/1, of 266")
# пропуски п. 2 бланка — заполняет поставщик (docs/dentpilot-2/sms.md › «Заявление клиники»)
USER = "Oleg Bacalu, antreprenor independent, IDNO 1026023148339"
PLATFORM = "DentPilot"
TITLE = "CERERE PENTRU ACTIVAREA/CREAREA ALIAS-ULUI SMS"
INK = (0.07, 0.07, 0.07)


def missing(c: sqlite3.Row) -> list[str]:
    """Каких реквизитов клиники не хватает бланку: пустую строку в подписываемой
    бумаге sms.md не примет, а заметно это станет уже после подписи."""
    out = []
    if not re.fullmatch(r"\d{13}", c["idno"] or ""):
        out.append("IDNO (13 cifre)")
    if not (c["address"] or "").strip():
        out.append("adresa")
    if not (c["phone"] or "").strip():
        out.append("telefonul")
    if not (c["email"] or "").strip():
        out.append("e-mailul")
    return out


def clean_rep(s: str) -> str:
    """Имя и фамилия представителя: пробелы схлопнуты, до REP_MAX; '' — не годится."""
    s = " ".join((s or "").split())[:REP_MAX]
    return s if len(s) >= 3 and re.search(r"[^\W\d_]", s) else ""


def filename(sender: str) -> str:
    # имя отправителя — латиница, цифры, пробел, точка, тире (sms.SENDER_RE)
    return f"Cerere-alias-SMS-{re.sub(r'[^A-Za-z0-9.-]+', '-', sender).strip('-') or 'DentPilot'}.pdf"


def _rich(doc: pdf.Document, x: float, y: float, parts: list[tuple[str, bool]], size: float,
          max_w: float, lead: float) -> float:
    """Абзац из кусков (текст, жирный) с переносом по словам: заполненное — жирным,
    чтобы директор сверил его перед подписью. Возвращает `y` следующей строки."""
    cur, space = x, False
    for text, bold in parts:
        for m in re.finditer(r"(\s*)(\S+)", text):
            gap, space = space or bool(m.group(1)), False
            word = m.group(2)
            sp = doc.width(" ", size, bold) if (gap and cur > x) else 0.0
            w = doc.width(word, size, bold)
            if cur > x and cur + sp + w > x + max_w:
                y += lead
                cur, sp = x, 0.0
            doc.text(cur + sp, y, word, size, bold, INK)
            cur += sp + w
        space = space or text[-1:].isspace()     # пробел в конце куска — перед словом следующего
    return y + lead


def render(c: sqlite3.Row, sender: str, rep: str, now: datetime | None = None) -> bytes:
    """Бланк sms.md, заполненный данными клиники. Одна страница A4."""
    now = now or datetime.now(timezone.utc)
    day = sms.local(now).strftime("%d.%m.%Y")
    doc = pdf.Document(f"Cerere alias SMS «{sender}» — {c['name']}")
    L, R = 64.0, doc.w - 64.0
    W = R - L
    size, lead = 11.0, 17.0
    y = 92.0
    doc.text(doc.w / 2, y, TITLE, 13, bold=True, color=INK, align="center")
    y += 40
    for line in TO:
        doc.text(L, y, line, size, color=INK)
        y += lead
    y += 14
    y = _rich(doc, L, y, [("Subsemnatul, ", False), (rep, True), (" in calitate de reprezentant legal al companiei ", False),
                          (c["name"], True), (",", False)], size, W, lead)
    for label, value in (("IDNO: ", c["idno"]), ("Adresa juridica: ", c["address"]),
                         ("Email ", c["email"]), ("Telefon ", c["phone"])):
        y = _rich(doc, L, y, [(label, False), (value or "", True)], size, W, lead)
    y += 14
    y = _rich(doc, L, y, [("prin prezenta solicit activarea Alias-ului SMS după cum urmeaza:", False)], size, W, lead)
    y = _rich(doc, L, y, [("Alias propus: ", False), (sender, True)], size, W, lead)
    y += 14
    y = _rich(doc, L, y, [("Confirm că:", False)], size, W, lead)
    points = (
        [("Alias-ul mentionat mai sus reprezintă denumirea comercială a companiei mele sau o marca "
          "utilizata in mod legal", False)],
        [("Sunt de acord ca acest Alias sa fie folosit de către ", False), (USER, True),
         (", exclusiv pentru transmiterea mesajelor SMS automate sau promotionale in numele companiei mele, "
          "către clientii programati prin platforma ", False), (PLATFORM, True)],
        [("Imi asum responsabilitatea pentru corectitudinea informatilor furnizate si pentru eventualele "
          "plângeri privind utilizarea neautorizat a denumirii.", False)],
    )
    for i, parts in enumerate(points, 1):
        doc.text(L + 8, y, f"{i}.", size, color=INK)
        y = _rich(doc, L + 26, y, parts, size, W - 26, lead) + 4
    y += 10
    y = _rich(doc, L, y, [("Solicit activarea Alias-ului incepând cu data de ", False), (day, True), (".", False)],
              size, W, lead)
    y += 30
    for parts in ([("Data: ", False), (day, True)], [("Nume si prenume: ", False), (rep, True)],
                  [("Semnatura: _______________________", False)]):
        y = _rich(doc, L, y, parts, size, W, lead + 8)
    return doc.build()


def is_pdf(body: bytes) -> bool:
    """PDF по сигнатуре, не по имени файла (спецификация разрешает мусор до неё в первом КБ)."""
    return b"%PDF-" in body[:1024]


def _clean_name(name: str) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    return "".join(ch for ch in base if ch.isprintable())[:120]


def attach(con: sqlite3.Connection, clinic_id: str, body: bytes, name: str, who: str) -> str:
    """Подписанное заявление из кабинета → строка sms_papers и отметка «Заявление
    получено» у ТЕКУЩЕЙ заявки. '' или код отказа. Повторная загрузка заменяет
    ссылку на новый файл (прежний остаётся в таблице)."""
    acc = sms.ensure(con, clinic_id)
    if acc["sender_state"] != sms.S_REQUESTED or not acc["sender"]:
        return "sms_paper_state"
    if not body:
        return "sms_paper_empty"
    if len(body) > MAX_BYTES:
        return "sms_paper_big"
    if not is_pdf(body):
        return "sms_paper_pdf"
    now = db.now_iso()
    cur = con.execute("INSERT INTO sms_papers(clinic_id, sender, body, size, sha256, filename, uploaded_at, who) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (clinic_id, acc["sender"], body, len(body), hashlib.sha256(body).hexdigest(),
                       _clean_name(name), now, who))
    con.execute("UPDATE sms_accounts SET sender_paper_at=?, sender_paper_id=?, updated_at=? WHERE clinic_id=?",
                (now, cur.lastrowid, now, clinic_id))
    db.audit(con, who, "sms_sender", clinic_id,
             f"заявление на «{acc['sender']}» загружено в кабинете ({max(1, len(body) // 1024)} КБ)")
    return ""


def current(con: sqlite3.Connection, clinic_id: str, body: bool = False) -> sqlite3.Row | None:
    """Заявление текущей заявки клиники (без тела, если body=False) или None."""
    cols = "p.*" if body else "p.id, p.clinic_id, p.sender, p.size, p.sha256, p.filename, p.uploaded_at, p.who"
    return con.execute(f"SELECT {cols} FROM sms_papers p JOIN sms_accounts a ON a.sender_paper_id = p.id "
                       f"WHERE a.clinic_id=?", (clinic_id,)).fetchone()
