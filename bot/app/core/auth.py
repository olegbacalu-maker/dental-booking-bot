"""Кто пускается в журнал.

Изданий два, и вход у них разный: у клиники PIN из 4–6 цифр, хранящийся
солёным хешем рядом с базой, у облачного демо — ADMIN_KEY из окружения.
Общего кода тут немного, но он нужен КАЖДОМУ маршруту админки, поэтому живёт
в core: модуль, который захочет свою копию проверки, рано или поздно разойдётся
с остальными в том, кого считать вошедшим.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import secrets
import urllib.parse

from fastapi import Request
from fastapi.responses import RedirectResponse

from .. import db
from .storage import _data_dir

# --- защита журнала ---
# Desktop (SQLite): PIN 4–6 цифр, ставится в самом приложении (data/auth.json,
# hash+salt); «забыл PIN» = удалить этот файл → снова экран установки.
# Cloud (Postgres): по-прежнему ADMIN_KEY из .env.
ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()


def _auth_path() -> pathlib.Path | None:
    d = _data_dir()
    return d / "auth.json" if d else None


def _pin_rec() -> dict | None:
    p = _auth_path()
    if p and p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _pin_hash(pin: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()


def _secret() -> str:
    rec = _pin_rec()
    if rec:
        return rec.get("hash", "")
    return ADMIN_KEY


def _sec_warn() -> str:
    if _secret() or db.IS_SQLITE:
        return ""
    return " · ⚠️ fără parolă — setați ADMIN_KEY în .env"


def _cookie_sig() -> str:
    return hmac.new(_secret().encode(), b"dentart-admin-v1", hashlib.sha256).hexdigest()


def _set_auth_cookie(resp: RedirectResponse) -> RedirectResponse:
    resp.set_cookie("admin_auth", _cookie_sig(), max_age=60 * 60 * 24 * 30,
                    httponly=True, samesite="lax")
    return resp


def _guard(request: Request) -> RedirectResponse | None:
    sec = _secret()
    if not sec:
        if db.IS_SQLITE:
            # desktop без PIN — принудительная первичная установка
            return RedirectResponse("/admin/setup", status_code=303)
        return None  # облачный демо-режим без ключа
    if hmac.compare_digest(request.cookies.get("admin_auth", ""), _cookie_sig()):
        return None
    q = str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(
        f"/admin/login?next={urllib.parse.quote(q, safe='')}", status_code=303)


def _write_pin(pin: str) -> None:
    salt = secrets.token_hex(8)
    _auth_path().write_text(
        json.dumps({"salt": salt, "hash": _pin_hash(pin, salt)}),
        encoding="utf-8",
    )


def _setup_allowed() -> bool:
    return db.IS_SQLITE and _pin_rec() is None and not ADMIN_KEY
