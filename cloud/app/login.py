"""Вход в кабинет без Google (02.10, слово Олега «надо тоже сделать возможность»):
код на e-mail, без пароля.

Директор вводит ящик → письмо с кодом из 6 цифр → код → учётная запись
`accounts(provider='email', subject=<ящик в канонической форме>)` и та же кука
`dp_cont`, что у входа через Google (account.login_email). Клиника с тем же
ящиком уже есть → кабинет сразу, как у Google-входа; нет → регистрация с этим
ящиком (e-mail клиники = ящик входа, не редактируется).

Код живёт CODE_TTL (как код активации программы), одноразовый, CODE_ATTEMPTS
ошибок на код; на один ящик — CODES_PER_HOUR кодов в час (письма не станут
спамом), с одного адреса — REQUESTS_PER_HOUR запросов (перебор ящиков);
проверки кода — общий trial.verify_limited. Хранится только хеш кода.
⛔ Ответ на запрос кода одинаков для любого годного ящика: страница — не
оракул о том, кто у нас зарегистрирован (новый ящик всё равно идёт дальше —
на регистрацию).
⛔ Это НЕ activation_codes: тот код привязан к клинике (`clinic_id NOT NULL`),
а ящик при входе клиники может ещё не иметь — отсюда своя таблица login_codes.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import db, trial

PROVIDER = "email"
CODE_TTL = trial.CODE_TTL
CODE_ATTEMPTS = trial.CODE_ATTEMPTS
CODES_PER_HOUR = 3               # кодов на один ящик в час
REQUESTS_PER_HOUR = 10           # запросов кода с одного адреса (IPv6 — /64) в час
_hits: dict[str, list[float]] = {}


def email_ok(email: str) -> bool:
    return bool(email) and len(email) <= trial.EMAIL_MAX and bool(trial._EMAIL.match(email))


def request_limited(ip: str) -> bool:
    """Больше REQUESTS_PER_HOUR запросов кода с адреса за час — отказ (перебор ящиков)."""
    now = time.time()
    key = trial.bucket(ip)
    stamps = [t for t in _hits.get(key, []) if now - t < 3600]
    _hits[key] = stamps + [now]
    return len(stamps) >= REQUESTS_PER_HOUR


def _code_hash(vid: str, code: str) -> str:
    return hashlib.sha256(f"login:{vid}:{code}".encode("utf-8")).hexdigest()


def new_code(con: sqlite3.Connection, email: str, ip: str) -> tuple[str, str]:
    """Код для ящика → (verify_id, код) или ('', ''): лимит кодов на ящик за час.
    Письмо шлёт вызывающий — после транзакции."""
    canon = trial.canonical(email)
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).strftime(db.TS)
    recent = con.execute("SELECT count(*) FROM login_codes WHERE canon=? AND created_at > ?",
                         (canon, hour_ago)).fetchone()[0]
    if recent >= CODES_PER_HOUR:
        db.audit(con, email, "login_code_limit", None, ip)
        return "", ""
    vid = secrets.token_urlsafe(18)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    con.execute("INSERT INTO login_codes(id, email, canon, code_hash, created_at, expires_at) "
                "VALUES(?,?,?,?,?,?)", (vid, email, canon, _code_hash(vid, code), now.strftime(db.TS),
                                        (now + CODE_TTL).strftime(db.TS)))
    db.audit(con, email, "login_code_sent", None, ip)
    return vid, code


def check_code(con: sqlite3.Connection, vid: str, code: str, ip: str) -> str | None:
    """Верный живой код → ящик, на который он ушёл (код погашен); иначе None, и
    ошибка засчитана коду."""
    row = con.execute("SELECT * FROM login_codes WHERE id=?", (vid,)).fetchone()
    now = datetime.now(timezone.utc)
    if (row is None or row["used_at"] or row["attempts"] >= CODE_ATTEMPTS
            or (db.parse_ts(row["expires_at"]) or now) <= now):
        return None
    if not hmac.compare_digest(row["code_hash"], _code_hash(vid, code)):
        con.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE id=?", (vid,))
        db.audit(con, row["email"], "login_code_bad", None, ip)
        return None
    con.execute("UPDATE login_codes SET used_at=? WHERE id=?", (now.strftime(db.TS), vid))
    db.audit(con, row["email"], "login_code_ok", None, ip)
    return row["email"]
