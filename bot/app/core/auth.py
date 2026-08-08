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

import contextvars
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

# --- роли (08-06, по просьбе первой клиники) ---
# Роль — это НАБОР РАЗРЕШЕНИЙ, а не строка, которую сравнивают по месту:
# сравнение `role == "director"` расползлось бы по маршрутам, и первая же
# просьба «старшему администратору тоже нужны отчёты» потребовала бы найти их
# все. Здесь одна таблица, и новая роль — это новая строка в ней.
ROLE_DIRECTOR = "director"
ROLE_RECEPTIE = "receptie"
ROLE_MEDIC = "medic"

ROLE_LABEL = {ROLE_DIRECTOR: "Director", ROLE_RECEPTIE: "Recepție",
              ROLE_MEDIC: "Medic"}

# Что роль умеет. Всё, чего в наборе НЕТ, закрыто — список разрешает, а не
# запрещает: забытое право означает «нельзя», а не «можно всем».
PERM_MONEY = "money"        # выручка, статистика, отчёты
PERM_SETTINGS = "settings"  # настройки клиники, токен бота, бэкап, обновление
PERM_USERS = "users"        # учётные записи сотрудников
PERM_DOCTORS = "doctors"    # каталог врачей: карточки, фото, услуги, часы

PERMS = {
    ROLE_DIRECTOR: {PERM_MONEY, PERM_SETTINGS, PERM_USERS, PERM_DOCTORS},
    # Регистратуре каталог врачей НУЖЕН: отметить отпуск, сузить часы приёма,
    # поправить услуги — операционка стойки, иначе любой чих требует директора.
    ROLE_RECEPTIE: {PERM_DOCTORS},
    # Врачу — нет (канарейка 1.15.0, Олег): с телефона в LAN врач открывал
    # ЧУЖИЕ карточки и мог менять фото. Врачу — пациенты и записи; просмотр
    # своего расписания живёт в журнале, не в каталоге.
    ROLE_MEDIC: set(),
}


def can(user: dict | None, perm: str) -> bool:
    """Разрешено ли. Неизвестная роль не получает НИЧЕГО — если однажды в файле
    окажется роль из будущей версии, она не должна открыть деньги по умолчанию."""
    if not user:
        return False
    return perm in PERMS.get(user.get("role", ""), set())


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


def _cookie_sig(uid: str = "", role: str = "", sid: str = "") -> str:
    """Подпись сессии.

    Без аргументов — СТАРАЯ форма, одна на всю клинику (до ролей). Её мы больше
    не выдаём, но продолжаем принимать: обновление не должно выкидывать клинику
    из журнала посреди приёма.

    Именная форма подписывает ещё и `sid` — случайную метку, которая меняется
    при смене пароля ИМЕННО этого человека. Без неё у директора был бы выбор из
    двух плохих: либо смена чужого пароля не закрывает чужие открытые вкладки,
    либо она разлогинивает заодно всех остальных.
    """
    msg = f"{uid}|{role}|{sid}".encode() if uid else b"dentart-admin-v1"
    return hmac.new(_secret().encode(), msg, hashlib.sha256).hexdigest()


def _set_auth_cookie(resp: RedirectResponse,
                     user: dict | None = None) -> RedirectResponse:
    u = user or {}
    uid = str(u.get("id") or "clinic")
    role = str(u.get("role") or ROLE_DIRECTOR)
    sid = str(u.get("sid") or "")
    resp.set_cookie("admin_auth", f"{uid}.{role}.{sid}.{_cookie_sig(uid, role, sid)}",
                    max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return resp


def current_user(request: Request) -> dict | None:
    """Кто в этой сессии. None — не вошёл.

    ⚠️ Роль берётся ИЗ ФАЙЛА по id, а не из куки: иначе понижение сотрудника
    не действовало бы до тех пор, пока он сам не выйдет. По той же причине
    исчезнувшая учётка немедленно перестаёт пускать.
    """
    # ⚠️ Ни одна ветка ниже не выдаёт человека без ПРОВЕРЕННОЙ подписи. Первая
    # версия этой функции возвращала директора сразу, когда auth.json нет
    # (облачный режим по ADMIN_KEY), — и открывала журнал вообще всем, потому
    # что _guard спрашивает именно её. Поймали тесты «без входа не отдаётся».
    if not _secret():
        return None                    # проверять нечем — решение за _guard
    raw = request.cookies.get("admin_auth", "")
    if not raw:
        return None
    rec = _pin_rec()
    users = _users(rec)
    parts = raw.split(".")
    if len(parts) == 4:
        uid, role, sid, sig = parts
        if not hmac.compare_digest(sig, _cookie_sig(uid, role, sid)):
            return None
        if rec is None:
            return _as_user({"id": uid, "role": role})   # облако: людей нет
        found = next((u for u in users if u.get("id") == uid), None)
        if found is None or str(found.get("sid") or "") != sid:
            return None            # учётку удалили или сменили ей пароль
        return _as_user(found)
    # старая кука без имени: она могла появиться только у того, кто знал PIN
    # единственного тогда пользователя. Как только их стало больше, она уже не
    # говорит, КТО это, и перестаёт годиться — человек перевойдёт один раз.
    if hmac.compare_digest(raw, _cookie_sig()):
        if rec is None:
            return _as_user({"id": "admin", "role": ROLE_DIRECTOR})
        if len(users) == 1:
            return _as_user(users[0])
    return None


# Кто в ЭТОМ запросе — на время запроса. Каркас страницы (сайдбар, верхний
# угол) рисуется глубоко внутри и запроса не видит, а протаскивать пользователя
# через полтора десятка вызовов `_shell` значило бы, что забытый вызов молча
# покажет врачу чужое меню. Ставится один раз посредником в main.py.
# ⚠️ Это ТОЛЬКО для показа. Решение «пускать или нет» принимает require(),
# которому запрос передан явно.
_REQ_USER: contextvars.ContextVar = contextvars.ContextVar("dp_user", default=None)


def set_request_user(u: dict | None) -> None:
    _REQ_USER.set(u)


def request_user() -> dict | None:
    return _REQ_USER.get()


def _as_user(u: dict) -> dict:
    role = u.get("role") or ROLE_DIRECTOR
    return {"id": u.get("id", "clinic"), "role": role,
            "name": u.get("name") or ROLE_LABEL.get(role, u.get("id", "")),
            "doctor_id": u.get("doctor_id", "")}


def _guard(request: Request) -> RedirectResponse | None:
    sec = _secret()
    if not sec:
        if db.IS_SQLITE:
            # desktop без PIN — принудительная первичная установка
            return RedirectResponse("/admin/setup", status_code=303)
        return None  # облачный демо-режим без ключа
    if current_user(request) is not None:
        return None
    q = str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(
        f"/admin/login?next={urllib.parse.quote(q, safe='')}", status_code=303)


def require(request: Request, perm: str) -> RedirectResponse | None:
    """Охрана раздела по праву: сперва вход, потом разрешение.

    ⚠️ Звать в КАЖДОМ маршруте раздела, включая POST-ы. Спрятанный пункт меню —
    это не защита: адрес набирается руками, а форма отправляется из чего угодно.
    """
    if (deny := _guard(request)) is not None:
        return deny
    if can(current_user(request), perm):
        return None
    return RedirectResponse("/admin?msg=no_access", status_code=303)


def _secret_fields(pin: str) -> dict:
    """Хеш пароля + новая метка сессий: смена пароля обязана закрывать открытые
    вкладки ИМЕННО этого человека."""
    salt = secrets.token_hex(16)
    return {"kdf": KDF, "iter": KDF_ITER, "salt": salt,
            "hash": _derive(pin, salt), "sid": secrets.token_hex(8)}


def _save_users(users: list[dict], *, rotate: bool) -> None:
    rec = _pin_rec() or {}
    key = rec.get("cookie_key") or ""
    if rotate or not key:
        key = secrets.token_hex(32)
    _auth_path().write_text(
        json.dumps({"v": 2, "cookie_key": key, "users": users}, indent=1),
        encoding="utf-8")


def all_users() -> list[dict]:
    return [_as_user(u) for u in _users(_pin_rec())]


def find_user(uid: str) -> dict | None:
    """СЫРАЯ запись сотрудника — вместе с `sid`, который нужен _set_auth_cookie.
    Наружу для показа берут all_users(): там уже без секретов."""
    return next((u for u in _users(_pin_rec()) if u.get("id") == uid), None)


def n_directors(excluding: str = "") -> int:
    """Сколько директоров останется, если не считать этого. Клиника обязана
    сохранить хотя бы одного: иначе настройки и деньги закроются НАВСЕГДА —
    некому будет выдать право обратно."""
    return sum(1 for u in _users(_pin_rec())
               if (u.get("role") or ROLE_DIRECTOR) == ROLE_DIRECTOR
               and u.get("id") != excluding)


def pin_free(pin: str, except_uid: str = "") -> bool:
    """Не занят ли пароль другим сотрудником.

    Вход возможен по одному лишь паролю (регистратура набирает его десятки раз
    в день, и требовать ещё и логин — это трение на ровном месте). Значит
    пароль ОБЯЗАН определять человека однозначно: два одинаковых, и журнал
    доступа начнёт называть чужое имя.
    """
    for u in _users(_pin_rec()):
        if u.get("id") == except_uid:
            continue
        got = _derive(pin, u.get("salt", ""), u.get("kdf", KDF),
                      int(u.get("iter") or KDF_ITER))
        if u.get("hash") and hmac.compare_digest(got, u["hash"]):
            return False
    return True


def save_user(uid: str, *, name: str, role: str, doctor_id: str = "",
              pin: str | None = None) -> None:
    """Завести или поправить сотрудника. Ключ подписи НЕ вращаем: правка одной
    учётки не должна выкидывать из журнала всех остальных посреди приёма."""
    rec = _pin_rec()
    old = next((u for u in _users(rec) if u.get("id") == uid), {})
    rest = [u for u in _users(rec) if u.get("id") != uid]
    u = {**old, "id": uid, "role": role, "name": name, "doctor_id": doctor_id}
    if pin:
        u.update(_secret_fields(pin))
    _save_users(rest + [u], rotate=False)


def delete_user(uid: str) -> bool:
    rest = [u for u in _users(_pin_rec()) if u.get("id") != uid]
    if len(rest) == len(_users(_pin_rec())):
        return False
    _save_users(rest, rotate=False)
    return True


def verify_pin(pin: str, uid: str = "") -> dict | None:
    """Проверить PIN, вернуть запись вошедшего (None — не подошёл).

    Файл v1 при удачной проверке молча переписывается в v2 — другого момента
    нет: сам PIN нигде не хранится, и пересчитать хеш можно ровно тогда, когда
    его ввели. Подпись сессии при этом меняется, поэтому вызывающий ОБЯЗАН
    выдать свежую куку сразу после удачи, иначе вход «удастся» и тут же
    отвалится на первом же переходе.
    """
    rec = _pin_rec()
    for u in _users(rec):
        if uid and u.get("id") != uid:
            continue          # логин указан явно — сверяем только с ним
        want = u.get("hash", "")
        got = _derive(pin, u.get("salt", ""), u.get("kdf", KDF),
                      int(u.get("iter") or KDF_ITER))
        if want and hmac.compare_digest(got, want):
            if u.get("kdf") != KDF or not u.get("sid"):
                # заодно чиним запись без sid: до ролей его не было, а без него
                # именная кука не отличит «пароль сменили» от «не меняли»
                _write_pin(pin, role=u.get("role", ROLE_DIRECTOR),
                           uid=u.get("id", "clinic"))
                return next((x for x in _users(_pin_rec())
                             if x.get("id") == u.get("id", "clinic")), u)
            return u
    return None


def _write_pin(pin: str, role: str = ROLE_DIRECTOR, uid: str = "clinic") -> None:
    """Смена СВОЕГО пароля: пишет хеш и ВРАЩАЕТ ключ подписи, то есть закрывает
    все открытые сессии клиники. Для смены PIN это правильно — его меняют
    тогда, когда он утёк. Заведение и правку чужих учёток делает save_user,
    она чужую работу не прерывает."""
    rec = _pin_rec()
    old = next((u for u in _users(rec) if u.get("id") == uid), {})
    rest = [u for u in _users(rec) if u.get("id") != uid]
    # {**old, ...} — чтобы смена пароля не стирала имя, роль и привязку к врачу
    _save_users(rest + [{**old, **_secret_fields(pin), "id": uid, "role": role}],
                rotate=True)


def _setup_allowed() -> bool:
    return db.IS_SQLITE and _pin_rec() is None and not ADMIN_KEY


# --- сигнализация auth.json (08-06) ---
# Файл лежит рядом с базой, и человек с доступом к папке может переписать его
# или удалить (удаление — наш же документированный путь «забыл PIN»). Замка тут
# не построить: у кого файл, у того и незашифрованная база рядом, и любой ключ
# проверки подписи лежал бы в той же папке. Поэтому НЕ замок, а след: отпечаток
# файла хранится в БД, расхождение при старте видно директору и остаётся в
# ленте. Канцелярское любопытство — самый реальный сценарий в клинике на три
# человека — перестаёт быть тихим; решительного человека это не остановит.

TAMPER_ALERT = ""          # текст непогашенного предупреждения (один процесс)


def set_tamper_alert(text: str) -> None:
    global TAMPER_ALERT
    TAMPER_ALERT = text


def tamper_alert() -> str:
    return TAMPER_ALERT


def auth_file_fp() -> str:
    """Отпечаток auth.json как БАЙТОВ на диске; '' — файла нет. Именно байты, а
    не разобранный JSON: переформатирование файла руками — тоже вмешательство."""
    p = _auth_path()
    try:
        return (hashlib.sha256(p.read_bytes()).hexdigest()
                if p and p.exists() else "")
    except OSError:
        return ""


async def remember_auth_file() -> None:
    """Запомнить отпечаток ПОСЛЕ СВОЕЙ записи auth.json. Звать в каждом
    маршруте, который файл трогает, — иначе следующая проверка при старте
    примет собственную правку за чужую и напугает клинику ложной тревогой."""
    await db.set_meta("auth_fp", auth_file_fp())


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
