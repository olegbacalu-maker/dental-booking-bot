"""Вход администратора: один человек, пароль из окружения, кука с подписью.

Тот же приём, что у движка (core/auth.py): pbkdf2-sha256 с солью, кука
HttpOnly/SameSite=Lax с HMAC, проверка Origin на POST, лимит попыток входа.
Аргументов «второй администратор» и «роли» здесь нет намеренно — это
инструмент одного человека (cloud.md › «Админка»).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit

from fastapi import Request

from . import config

COOKIE = "dp_admin"
SESSION_TTL = 12 * 3600
KDF_ITER = 600_000
MAX_FAILS = 5
LOCK_SECONDS = 60

_SECRET = (config.SECRET or secrets.token_hex(32)).encode("utf-8")
_fails: dict[str, list[float]] = {}


# ---------- пароль ----------


def make_hash(password: str, iters: int = KDF_ITER) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), iters).hex()
    return f"pbkdf2-sha256${iters}${salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2-sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iters)).hex()
        return hmac.compare_digest(got, digest)
    except (ValueError, AttributeError):
        return False


# ---------- попытки ----------


def locked(ip: str) -> int:
    """Сколько секунд ещё ждать после MAX_FAILS неудач; 0 — можно."""
    stamps = [t for t in _fails.get(ip, []) if time.time() - t < LOCK_SECONDS]
    _fails[ip] = stamps
    if len(stamps) >= MAX_FAILS:
        return int(LOCK_SECONDS - (time.time() - stamps[0])) + 1
    return 0


def note_fail(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())


def note_ok(ip: str) -> None:
    _fails.pop(ip, None)


# ---------- сессия ----------


def _sign(user: str, exp: int) -> str:
    return hmac.new(_SECRET, f"{user}|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()


def session_cookie(user: str) -> str:
    exp = int(time.time()) + SESSION_TTL
    return f"{user}|{exp}|{_sign(user, exp)}"


def current_user(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE, "")
    try:
        user, exp_s, mac = raw.split("|")
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < time.time() or not hmac.compare_digest(mac, _sign(user, exp)):
        return None
    return user if user == config.ADMIN_USER else None


def same_origin_post(request: Request) -> bool:
    """POST без Origin (curl, тесты) — пропуск; с чужим Origin — отказ."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.headers.get("host", "")
