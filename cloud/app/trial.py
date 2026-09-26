"""Форма пробного периода (L14): публичная страница /proba на сервере лицензий.

cloud.md › «Сайт»: страница живёт здесь, а не на статике сайта — ссылка, не
форма на чужом origin. Клиника оставляет название, IDNO, контакт, e-mail и
согласие с условиями; дальше — по DP_TRIAL_MODE:

  approve  (по умолчанию)  клиника заведена как заявка, Олегу письмо, файл
                           выдаёт админка кнопкой «Выдать пробный»;
  auto                     файл выдаётся и уходит письмом сразу, Олегу копия.

⛔ Второго пробного по той же клинике нет: IDNO (если назван) и ящик e-mail
(в канонической форме: регистр, `+метка`, точки gmail) сверяются со всеми
клиниками — заявка, выданный пробный или абонемент, кроме скрытых, — и
повтор не даёт файла. ⭐ Повтор клинике не объявляется: страница та же, что
у принятой заявки, — иначе форма была бы оракулом «эта клиника уже клиент
DentPilot»; о повторе узнаёт Олег письмом и отвечает сам. Правило — в
`existing`, одно на оба режима.

Спам держат три вещи, и ни одна не требует капчи: скрытое поле, которое
человек не видит и не заполняет; лимит заявок с одного адреса (IPv6 — сети
/64) в час и общий потолок на всех; согласие галочкой. Всё, что за ними, —
в журнале с адресом.
"""
from __future__ import annotations

import ipaddress
import re
import secrets
import sqlite3
import time

from . import config, db, license, mail

MODE_AUTO, MODE_APPROVE = "auto", "approve"
MAX_PER_HOUR = 5                 # заявок с одного адреса (IPv6 — с одной /64) в час
MAX_TOTAL_PER_HOUR = 60          # заявок со всех адресов в час: потолок на случай ротации адресов
_hits: dict[str, list[float]] = {}
_all: list[float] = []
HONEYPOT = "website"             # поле, которого нет для человека
ISSUED, ISSUED_UNMAILED, REQUESTED, DUPLICATE = "issued", "issued_unmailed", "requested", "duplicate"
NAME_MAX, EMAIL_MAX, CONTACT_MAX, PHONE_MAX = 120, 120, 80, 40
# Голый адрес: одна «@», без пробелов и знаков, которыми в заголовке письма
# отделяют имя от адреса или один адрес от другого.
_EMAIL = re.compile(r"^[^@\s<>\"(),;:\[\]]+@[^@\s<>\"(),;:\[\]]+\.[A-Za-z0-9-]{2,}$")
_IDNO = re.compile(r"^[0-9]{13}$")
_DOT_BLIND = ("gmail.com", "googlemail.com")   # точки в имени ящика ничего не значат


def mode() -> str:
    return MODE_AUTO if config.TRIAL_MODE.lower() == MODE_AUTO else MODE_APPROVE


# ---------- спам ----------


def bucket(ip: str) -> str:
    """Ключ лимита: IPv4 — адрес, IPv6 — сеть /64 (у любого клиента их не меньше)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return ip


def limited(ip: str) -> bool:
    """Больше MAX_PER_HOUR заявок с адреса за час, или больше MAX_TOTAL_PER_HOUR со
    всех, — отказ, тем же приёмом, что лимит входа. Считаются и принятые, и
    отказанные после проверки полей: перебор адресов тоже заявки."""
    now = time.time()
    key = bucket(ip)
    stamps = [t for t in _hits.get(key, []) if now - t < 3600]
    if stamps:
        _hits[key] = stamps
    else:
        _hits.pop(key, None)
    _all[:] = [t for t in _all if now - t < 3600]
    return len(stamps) >= MAX_PER_HOUR or len(_all) >= MAX_TOTAL_PER_HOUR


def note(ip: str) -> None:
    now = time.time()
    _hits.setdefault(bucket(ip), []).append(now)
    _all.append(now)


# ---------- поля ----------


def clean(fields: dict) -> tuple[dict, str]:
    """(чистые поля, код ошибки или ''). Коды — ключи views.TRIAL_MSG.
    Пробелы и переводы строк внутри полей схлопываются в один пробел: поле
    уходит в заголовок письма, а перевод строки там — второй заголовок."""
    f = {k: " ".join((fields.get(k) or "").split()) for k in ("name", "idno", "contact_name", "email", "phone")}
    f["idno"] = f["idno"].replace(" ", "")
    f["email"] = f["email"].replace(" ", "")
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


def canonical(email: str) -> str:
    """Один ящик — одна форма: регистр не важен, `+метка` в имени ящика отбрасывается,
    у gmail точки в имени ничего не значат. Хранится и в письмо идёт адрес, как
    его написали; сравнивается — эта форма."""
    local, _, domain = email.lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in _DOT_BLIND:
        local = local.replace(".", "")
    return f"{local}@{domain}"


def existing(con: sqlite3.Connection, idno: str, email: str) -> sqlite3.Row | None:
    """Клиника с тем же IDNO или тем же ящиком — заявка, пробный или абонемент.
    Скрытая заявка не считается: «Скрыть» освобождает IDNO и e-mail."""
    want = canonical(email)
    domain = want.partition("@")[2]
    rows = con.execute("SELECT * FROM clinics WHERE declined_at IS NULL AND ((? <> '' AND idno = ?) "
                       "OR lower(email) LIKE ?) ORDER BY created_at", (idno, idno, "%@" + domain)).fetchall()
    for r in rows:
        if (idno and r["idno"] == idno) or canonical(r["email"]) == want:
            return r
    return None


# ---------- заявка ----------


def submit(con: sqlite3.Connection, f: dict, ip: str, who: str = "form") -> tuple[str, sqlite3.Row]:
    """Заявка → (исход, клиника). Исход: DUPLICATE — уже есть, ничего не сделано;
    REQUESTED — заведена, ждёт админа; ISSUED — пробный выдан и отправлен."""
    old = existing(con, f["idno"], f["email"])
    if old is not None:
        # без clinic_id: чужой текст не должен ложиться в карточку клиники
        db.audit(con, who, "trial_duplicate", None,
                 f"{f['name']}, IDNO {f['idno'] or '—'}, {f['email']}, {ip} — уже есть {old['id']} ({old['name']})")
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
        return ISSUED_UNMAILED, clinic
    return ISSUED, clinic


def notify(clinic: sqlite3.Row, outcome: str, ip: str, fields: dict | None = None) -> str:
    """Письмо Олегу о заявке — как вышло; отказ почты не ломает заявку."""
    subject, body = mail.trial_notice(clinic, outcome, ip, fields)
    try:
        return mail.send(config.TRIAL_NOTIFY, subject, body)
    except (RuntimeError, OSError, ValueError):
        return ""


def acknowledge(clinic: sqlite3.Row) -> str:
    """Клинике в режиме approve: заявка принята, файл придёт. Отказ почты — молча."""
    subject, body = mail.trial_received(clinic["name"], license.TRIAL_DAYS)
    try:
        return mail.send(clinic["email"], subject, body)
    except (RuntimeError, OSError, ValueError):
        return ""
