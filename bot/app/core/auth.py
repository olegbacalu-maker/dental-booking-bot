"""Кто пускается в журнал.

Изданий два, и вход у них разный: у клиники PIN из 4–6 цифр, хранящийся
хешем рядом с базой, у облачного демо — ADMIN_KEY из окружения. Общего кода
тут немного, но он нужен КАЖДОМУ маршруту админки, поэтому живёт в core:
модуль, который захочет свою копию проверки, рано или поздно разойдётся с
остальными в том, кого считать вошедшим.

PIN короткий по замыслу — регистратура набирает его десятки раз в день. Значит
защищать его надо ДВУМЯ разными вещами, потому что и перебор бывает двух видов:

  * онлайн, через форму  → лечится только счётчиком попыток (`lock_left`);
  * офлайн, по унесённому auth.json → лечится только дорогой функцией (PBKDF2).

Одно другим не заменяется, и это главное, что тут стоит помнить: 600 000
итераций ничем не мешают скрипту долбить `/admin/login`, а счётчик попыток
ничего не значит для того, у кого файл уже на руках.

Оговорка про масштаб пользы: auth.json лежит в одной папке с dental.db. Кто
добрался до хеша — уже унёс и саму картотеку. Стойкий хеш защищает поэтому не
базу, а ПЕРЕИСПОЛЬЗОВАННЫЙ PIN — тот же, что у человека на карте или телефоне.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import secrets
import time
import urllib.parse

from fastapi import Request
from fastapi.responses import RedirectResponse

from .. import db
from .storage import _data_dir

# --- защита журнала ---
# Desktop (SQLite): PIN 4–6 цифр, ставится в самом приложении (data/auth.json);
# «забыл PIN» = удалить этот файл → снова экран установки.
# Cloud (Postgres): по-прежнему ADMIN_KEY из .env.
ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()

# --- формат auth.json ---
# v1 (до 08-06): {"salt": …, "hash": …} — sha256 в ОДНУ итерацию. Читается
#   только ради миграции: 10^4–10^6 вариантов такого хеша перебираются на
#   ноутбуке за секунду, соль от этого не спасает (она бьёт радужные таблицы,
#   а не перебор крошечного пространства).
# v2: {"v":2, "cookie_key": …, "users":[{id, role, kdf, iter, salt, hash}]}
#   Список, а не один пользователь, — чтобы роли (врач/администратор/директор)
#   добавлялись записью в users, а не ВТОРОЙ миграцией файла у всех клиник.
#   cookie_key отдельный, а не хеш PIN: иначе подпись сессии привязана к
#   конкретному человеку, и с появлением второго её пришлось бы переделывать.
KDF = "pbkdf2-sha256"
KDF_ITER = 600_000
KDF_LEGACY = "sha256-1"
ROLE_DIRECTOR = "director"


def _auth_path() -> pathlib.Path | None:
    d = _data_dir()
    return d / "auth.json" if d else None


def _pin_rec() -> dict | None:
    """Сырое содержимое auth.json любой версии — «PIN вообще установлен?»."""
    p = _auth_path()
    if p and p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _derive(pin: str, salt: str, kdf: str = KDF, iters: int = KDF_ITER) -> str:
    if kdf == KDF_LEGACY:
        return hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), iters).hex()


def _users(rec: dict | None) -> list[dict]:
    """Пользователи в форме v2, каким бы ни был файл на диске."""
    if not rec:
        return []
    if rec.get("v") == 2:
        return rec.get("users") or []
    if rec.get("hash"):                                   # v1
        return [{"id": "clinic", "role": ROLE_DIRECTOR, "kdf": KDF_LEGACY,
                 "iter": 1, "salt": rec.get("salt", ""), "hash": rec["hash"]}]
    return []


def _secret() -> str:
    rec = _pin_rec()
    if rec:
        if rec.get("v") == 2:
            return rec.get("cookie_key", "")
        return rec.get("hash", "")                        # v1: подпись = хеш PIN
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


def verify_pin(pin: str) -> dict | None:
    """Проверить PIN, вернуть запись вошедшего (None — не подошёл).

    Файл v1 при удачной проверке молча переписывается в v2 — другого момента
    нет: сам PIN нигде не хранится, и пересчитать хеш можно ровно тогда, когда
    его ввели. Подпись сессии при этом меняется, поэтому вызывающий ОБЯЗАН
    выдать свежую куку сразу после удачи, иначе вход «удастся» и тут же
    отвалится на первом же переходе.
    """
    rec = _pin_rec()
    for u in _users(rec):
        want = u.get("hash", "")
        got = _derive(pin, u.get("salt", ""), u.get("kdf", KDF),
                      int(u.get("iter") or KDF_ITER))
        if want and hmac.compare_digest(got, want):
            if u.get("kdf") != KDF:
                _write_pin(pin, role=u.get("role", ROLE_DIRECTOR),
                           uid=u.get("id", "clinic"))
            return u
    return None


def _write_pin(pin: str, role: str = ROLE_DIRECTOR, uid: str = "clinic") -> None:
    salt = secrets.token_hex(16)
    users = [u for u in _users(_pin_rec()) if u.get("id") != uid]
    users.append({"id": uid, "role": role, "kdf": KDF, "iter": KDF_ITER,
                  "salt": salt, "hash": _derive(pin, salt)})
    _auth_path().write_text(json.dumps({
        "v": 2,
        # ключ подписи меняется вместе с PIN: смена PIN обязана разлогинивать
        # чужие открытые вкладки, иначе она не защищает ровно ни от чего
        "cookie_key": secrets.token_hex(32),
        "users": users,
    }, indent=1), encoding="utf-8")


def _setup_allowed() -> bool:
    return db.IS_SQLITE and _pin_rec() is None and not ADMIN_KEY


# --- защита от подбора через форму ---
# 4-значный PIN — это 10 000 вариантов; без лестницы ниже скрипт перебирает их
# по локалхосту за минуты, и стойкость хеша в этом вообще не участвует.
# Ступени от строгой к мягкой: сколько неудач подряд -> на сколько секунд закрыть.
_LOCK_STEPS = ((12, 900), (8, 300), (5, 30))
# Пауза на КАЖДОЙ неудаче, ещё до блокировки: превращает «10 000 попыток за
# минуту» в часы, а живому человеку стоит одного мгновения.
FAIL_DELAY = 0.7
_fail_mem: dict = {}          # облачное издание: папки рядом нет, помним в ОЗУ


def _fail_path() -> pathlib.Path | None:
    d = _data_dir()
    return d / "auth_fail.json" if d else None


def _fail_state() -> dict:
    p = _fail_path()
    if p is None:
        return dict(_fail_mem)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _fail_save(st: dict) -> None:
    p = _fail_path()
    if p is None:
        _fail_mem.clear()
        _fail_mem.update(st)
        return
    try:
        p.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass          # сбой записи не должен превращаться в отказ во входе


def lock_left() -> int:
    """Сколько секунд вход закрыт (0 — открыт)."""
    return max(0, int(_fail_state().get("until", 0) - time.time()))


def note_fail() -> int:
    """Записать неудачу, вернуть срок блокировки в секундах (0 — ещё пускаем).

    Счётчик после снятия блокировки НЕ обнуляется намеренно: иначе перебор
    продолжается пачками по пять, а так каждая следующая ошибка снова стоит
    полминуты. Обнуляет только удачный вход.
    """
    n = int(_fail_state().get("fails", 0)) + 1
    lock = next((sec for cnt, sec in _LOCK_STEPS if n >= cnt), 0)
    _fail_save({"fails": n, "until": time.time() + lock if lock else 0})
    return lock


def note_ok() -> None:
    _fail_save({"fails": 0, "until": 0})
