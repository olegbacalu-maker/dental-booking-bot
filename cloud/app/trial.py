"""Форма пробного периода (L14): публичная страница /proba на сервере лицензий.

cloud.md › «Сайт»: страница живёт здесь, а не на статике сайта — ссылка, не
форма на чужом origin. Клиника оставляет название, IDNO, контакт, e-mail и
согласие с условиями; дальше — по DP_TRIAL_MODE:

  approve  (по умолчанию)  клиника заведена как заявка, Олегу письмо, файл
                           выдаёт админка кнопкой «Выдать пробный»;
  auto                     файл выдаётся и уходит письмом сразу, Олегу копия.

⛔ Второго пробного по той же клинике нет: IDNO (если назван) и e-mail
сверяются со всеми клиниками — заявка, выданный пробный или абонемент —
и повтор получает «уже есть», а не второй файл. Правило — в `existing`, одно
на оба режима.

Спам держат три вещи, и ни одна не требует капчи: скрытое поле, которое
человек не видит и не заполняет; лимит заявок с одного адреса в час;
согласие галочкой. Всё, что за ними, — в журнале с адресом.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import time

from . import config, db, license, mail

MODE_AUTO, MODE_APPROVE = "auto", "approve"
MAX_PER_HOUR = 5                 # заявок с одного адреса в час
_hits: dict[str, list[float]] = {}
HONEYPOT = "website"             # поле, которого нет для человека
ISSUED, REQUESTED, DUPLICATE = "issued", "requested", "duplicate"
NAME_MAX, EMAIL_MAX, CONTACT_MAX, PHONE_MAX = 120, 120, 80, 40
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_IDNO = re.compile(r"^[0-9]{13}$")


def mode() -> str:
    return MODE_AUTO if config.TRIAL_MODE.lower() == MODE_AUTO else MODE_APPROVE


# ---------- спам ----------


def limited(ip: str) -> bool:
    """Больше MAX_PER_HOUR заявок с адреса за час — отказ, тем же приёмом, что лимит входа."""
    now = time.time()
    stamps = [t for t in _hits.get(ip, []) if now - t < 3600]
    _hits[ip] = stamps
    return len(stamps) >= MAX_PER_HOUR


def note(ip: str) -> None:
    _hits.setdefault(ip, []).append(time.time())


# ---------- поля ----------


def clean(fields: dict) -> tuple[dict, str]:
    """(чистые поля, код ошибки или ''). Коды — ключи views.TRIAL_MSG."""
    f = {k: (fields.get(k) or "").strip() for k in ("name", "idno", "contact_name", "email", "phone")}
    f["idno"] = f["idno"].replace(" ", "")
    if not 2 <= len(f["name"]) <= NAME_MAX:
        return f, "bad_name"
    if f["idno"] and not _IDNO.match(f["idno"]):
        return f, "bad_idno"
    if not f["email"] or len(f["email"]) > EMAIL_MAX or not _EMAIL.match(f["email"]):
        return f, "bad_email"
    if len(f["contact_name"]) > CONTACT_MAX or len(f["phone"]) > PHONE_MAX:
        return f, "too_long"
    if (fields.get("consent") or "") != "1":
        return f, "no_consent"
    return f, ""


def existing(con: sqlite3.Connection, idno: str, email: str) -> sqlite3.Row | None:
    """Клиника с тем же IDNO или e-mail — заявка, пробный или абонемент, скрытая тоже."""
    return con.execute("SELECT * FROM clinics WHERE (? <> '' AND idno = ?) OR lower(email) = lower(?) "
                       "ORDER BY created_at LIMIT 1", (idno, idno, email)).fetchone()


# ---------- заявка ----------


def submit(con: sqlite3.Connection, f: dict, ip: str, who: str = "form") -> tuple[str, sqlite3.Row]:
    """Заявка → (исход, клиника). Исход: DUPLICATE — уже есть, ничего не сделано;
    REQUESTED — заведена, ждёт админа; ISSUED — пробный выдан и отправлен."""
    old = existing(con, f["idno"], f["email"])
    if old is not None:
        db.audit(con, who, "trial_duplicate", old["id"], f"{f['name']}, IDNO {f['idno'] or '—'}, {f['email']}, {ip}")
        return DUPLICATE, old
    cid = "c_" + secrets.token_hex(6)
    now = db.now_iso()
    con.execute("INSERT INTO clinics(id, name, idno, contact_name, email, phone, address, created_at, "
                "origin, requested_at, consent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (cid, f["name"], f["idno"], f["contact_name"], f["email"], f["phone"], "", now, "form", now, now))
    db.audit(con, who, "trial_request", cid, f"{f['name']}, IDNO {f['idno'] or '—'}, {f['email']}, {ip}")
    clinic = con.execute("SELECT * FROM clinics WHERE id=?", (cid,)).fetchone()
    if mode() != MODE_AUTO:
        return REQUESTED, clinic
    valid, grace = license.trial_dates()
    try:
        license.issue(con, clinic, "trial", valid, grace, "formular de probă", who)
    except RuntimeError as e:
        # ключа выдачи нет: заявка остаётся заявкой, а не откатывается пятисотой
        db.audit(con, who, "trial_no_key", cid, str(e)[:200])
        return REQUESTED, clinic
    code = license.mail_latest(con, clinic, who)
    if code:
        db.audit(con, who, "mail_failed", cid, f"пробный из формы не ушёл: {code}")
    return ISSUED, clinic


def notify(clinic: sqlite3.Row, outcome: str, ip: str) -> str:
    """Письмо Олегу о заявке — как вышло; отказ почты не ломает заявку."""
    subject, body = mail.trial_notice(clinic, outcome, ip)
    try:
        return mail.send(config.TRIAL_NOTIFY, subject, body)
    except (RuntimeError, OSError):
        return ""


def acknowledge(clinic: sqlite3.Row) -> str:
    """Клинике в режиме approve: заявка принята, файл придёт. Отказ почты — молча."""
    subject, body = mail.trial_received(clinic["name"])
    try:
        return mail.send(clinic["email"], subject, body)
    except (RuntimeError, OSError):
        return ""
