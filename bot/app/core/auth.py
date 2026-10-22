"""Кто пускается в журнал.

Изданий два, и вход у них разный: у клиники PIN из 4–8 цифр, хранящийся
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

import asyncio
import contextvars
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import secrets
import time
import urllib.parse

from fastapi import Request
from fastapi.responses import RedirectResponse

from .. import db, privileged, relocate
from .storage import _data_dir

# --- защита журнала ---
# Desktop (SQLite): PIN 4–8 цифр, ставится в самом приложении (data/auth.json);
# «забыл PIN» = удалить этот файл → снова экран установки.
# Без PIN-файла (прогон, песочница, демо): ADMIN_KEY из .env.
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

# Длина PIN. Минимум прежний: 4 — регистратура набирает его десятки раз в
# день. Потолок поднят 08-13 с 6 до 8: пока всё жило на 127.0.0.1, 4–6 было
# честно, но форма входа теперь доступна из сети клиники (второй компьютер,
# телефоны) — желающим дать длиннее стало важно. Никого не принуждаем: правило
# проверяется только при УСТАНОВКЕ пароля, старые 4–6-значные работают как
# работали. Проверка длины — ТОЛЬКО отсюда: три формы (setup, смена, учётки)
# с собственными числами разъехались бы при первой правке.
PIN_MIN, PIN_MAX = 4, 8
# Минимум ПРИ ВКЛЮЧЁННОЙ СЕТИ (17.10, посторонний разбор): форма входа открыта
# всему Wi-Fi клиники, а 4 цифры — это 10 000 вариантов, которые даже с
# лестницей блокировок на устройство перебираются с десятка телефонов за
# вечер. Шесть — миллион, и подбор перестаёт быть вечерним занятием.
# Существующие короткие PIN не ломаются: правило проверяется при УСТАНОВКЕ
# пароля, а сеть не включается, пока у всех не ≥ 6 (`pin_readiness`).
PIN_MIN_LAN = 6


def lan_on() -> bool:
    """Процесс запущен с доступом из сети (DENTART_LAN=1 из dental.env).
    ⭐ Единственное чтение флага: `settings/lan.enabled()` берёт его отсюда,
    а переключатель ставит переменную тут же, не дожидаясь перезапуска."""
    return os.environ.get("DENTART_LAN", "").strip() == "1"


def pin_min() -> int:
    """Нижняя граница длины PIN — ПО СОСТОЯНИЮ СЕТИ, функцией, а не константой:
    переключатель сети меняет её на лету, и импорт заморозил бы старое."""
    return PIN_MIN_LAN if lan_on() else PIN_MIN


def pin_range_text() -> str:
    """«4–8 cifre» / «6–8 cifre» — для экранов. ⛔ Диапазон числами в тексте
    больше не пишется нигде (держит `test_structure`): он зависит от сети."""
    return f"{pin_min()}–{PIN_MAX} cifre"


def pin_len_ok(pin: str) -> bool:
    return pin.isdigit() and pin_min() <= len(pin) <= PIN_MAX

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
PERM_SMS = "sms"            # согласие пациента на SMS в окне записи

PERMS = {
    ROLE_DIRECTOR: {PERM_MONEY, PERM_SETTINGS, PERM_USERS, PERM_DOCTORS, PERM_SMS},
    # Регистратуре каталог врачей НУЖЕН: отметить отпуск, сузить часы приёма,
    # поправить услуги — операционка стойки, иначе любой чих требует директора.
    # SMS — тоже стойка: согласие пациента спрашивает тот, кто его записывает.
    ROLE_RECEPTIE: {PERM_DOCTORS, PERM_SMS},
    # Врачу — нет (канарейка 1.15.0, Олег): с телефона в LAN врач открывал
    # ЧУЖИЕ карточки и мог менять фото. Врачу — пациенты и записи; просмотр
    # своего расписания живёт в журнале, не в каталоге. SMS врач не видит
    # вовсе (Олег 22.10): согласие отмечает только регистратура.
    ROLE_MEDIC: set(),
}


def can(user: dict | None, perm: str) -> bool:
    """Разрешено ли. Неизвестная роль не получает НИЧЕГО — если однажды в файле
    окажется роль из будущей версии, она не должна открыть деньги по умолчанию."""
    if not user:
        return False
    return perm in PERMS.get(user.get("role", ""), set())


# Имя файла — константой, потому что спрашивают его ДВА раза и про РАЗНЫЕ
# корни: свой (_auth_path) и чужой (source_auth_file, экран раздвоения).
AUTH_NAME = "auth.json"


def _auth_path() -> pathlib.Path | None:
    d = _data_dir()
    return d / AUTH_NAME if d else None


def _pin_rec() -> dict | None:
    """Сырое содержимое auth.json любой версии — «PIN вообще установлен?»."""
    p = _auth_path()
    if p and p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _auth_broken() -> bool:
    """Файл ЕСТЬ, но не читается, — это состояние ошибки, а не «PIN не
    установлен». Различие принципиально: усечённый обрывом записи auth.json
    иначе неотличим от отсутствующего, и программа предложила бы ПЕРВИЧНУЮ
    установку PIN поверх живых учёток — любой за компьютером стал бы
    единственным директором, а сотрудники клиники молча пропали бы.
    Битый файл не перезаписываем и не удаляем: учётки восстановимы только из
    копии, и след для сигнализации auth_fp обязан остаться на диске."""
    p = _auth_path()
    if not p or not p.exists():
        return False
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return False
    except (OSError, json.JSONDecodeError):
        return True


def auth_blocked() -> bool:
    """Битый auth.json ЗАКРЫВАЕТ вход — но только там, где войти иначе нечем.

    ⚠️ Условие обязано быть одним на всю программу, и списывать его по месту
    нельзя. У битого файла `_pin_rec()` тоже None, поэтому `_secret()` отдаёт
    ADMIN_KEY: там, где ключ заполнен (песочница, весь харнесс, клиника, которой
    его вписали руками), вход по ключу исправен и auth.json в нём не участвует
    ни одной строкой. Безусловный отказ запирал бы такую установку наглухо —
    с советом восстановить копию, которая этой беде не помогает.
    """
    return not _secret() and _auth_broken()


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


def _cookie_sig(uid: str = "", role: str = "", sid: str = "", tok: str = "") -> str:
    """Подпись сессии. С `tok` (метка сессии, 17.10) — текущая форма.

    Без аргументов — СТАРАЯ форма, одна на всю клинику (до ролей). Её мы больше
    не выдаём, но продолжаем принимать: обновление не должно выкидывать клинику
    из журнала посреди приёма.

    Именная форма подписывает ещё и `sid` — случайную метку, которая меняется
    при смене пароля ИМЕННО этого человека. Без неё у директора был бы выбор из
    двух плохих: либо смена чужого пароля не закрывает чужие открытые вкладки,
    либо она разлогинивает заодно всех остальных.
    """
    msg = f"{uid}|{role}|{sid}".encode() if uid else b"dentart-admin-v1"
    if tok:
        msg += f"|{tok}".encode()
    return hmac.new(_secret().encode(), msg, hashlib.sha256).hexdigest()


# --- срок и отзыв сессии (17.10, посторонний разбор) ---
# В сети клиники канал — http, и кука видна любому в том же Wi-Fi. До 17.10
# она жила 30 дней, а «выход» лишь просил браузер её забыть: подсмотренное
# значение работало до смены PIN. Теперь у куки есть МЕТКА СЕССИИ `tok`
# (время выдачи + случайность), которую сервер:
#   * проверяет на срок — 12 часов при включённой сети (смена, а не месяц) и
#     прежние 30 дней без неё; срок считает СЕРВЕР по метке, max_age браузера
#     — лишь вежливость: подсмотренную куку браузером не ограничить;
#   * отзывает при выходе (`revoke_cookie`): метка ложится в
#     auth_revoked.json до истечения своего срока, и подсмотренная кука
#     умирает вместе с выходом человека.
# ⚠️ Куки без метки (выданы до 17.10) при включённой сети не принимаются —
# один повторный вход после обновления; без сети — как было, 30 дней.
COOKIE_TTL = 60 * 60 * 24 * 30
COOKIE_TTL_LAN = 60 * 60 * 12
_TOK_NONCE = 8                      # hex-знаков случайности после времени


def cookie_ttl() -> int:
    return COOKIE_TTL_LAN if lan_on() else COOKIE_TTL


def _new_tok() -> str:
    return f"{int(time.time()):x}{secrets.token_hex(_TOK_NONCE // 2)}"


def _tok_issued(tok: str) -> int | None:
    """Время выдачи из метки; None — метка не нашей формы."""
    head = tok[:-_TOK_NONCE]
    try:
        return int(head, 16) if head else None
    except ValueError:
        return None


def _set_auth_cookie(resp: RedirectResponse,
                     user: dict | None = None) -> RedirectResponse:
    u = user or {}
    uid = str(u.get("id") or "clinic")
    role = str(u.get("role") or ROLE_DIRECTOR)
    sid = str(u.get("sid") or "")
    tok = _new_tok()
    resp.set_cookie("admin_auth",
                    f"{uid}.{role}.{sid}.{tok}.{_cookie_sig(uid, role, sid, tok)}",
                    max_age=cookie_ttl(), httponly=True, samesite="lax")
    return resp


_revoked_mem: dict = {}        # без папки данных — в ОЗУ, как _fail_mem


def _revoked_path() -> pathlib.Path | None:
    d = _data_dir()
    return d / "auth_revoked.json" if d else None


def _revoked() -> dict:
    p = _revoked_path()
    return dict(_revoked_mem) if p is None else _state_read(p)


def revoke_cookie(request: Request) -> None:
    """Выход: метка сессии из куки запроса перестаёт приниматься — до конца
    своего срока, дальше хранить незачем. Подпись сверяется: чужую строку в
    список не кладём (он рос бы от любого мусора в куке)."""
    parts = request.cookies.get("admin_auth", "").split(".")
    if len(parts) != 5:
        return                          # старой куке отзывать нечего
    uid, role, sid, tok, sig = parts
    if not (_secret() and hmac.compare_digest(sig, _cookie_sig(uid, role, sid, tok))):
        return
    now = time.time()
    st = {k: v for k, v in _revoked().items()
          if isinstance(v, (int, float)) and v > now}
    st[tok] = (_tok_issued(tok) or int(now)) + COOKIE_TTL
    p = _revoked_path()
    if p is None:
        _revoked_mem.clear()
        _revoked_mem.update(st)
    else:
        _state_write(p, st)


def _session_alive(tok: str) -> bool:
    """Метка в сроке и не отозвана."""
    issued = _tok_issued(tok)
    if issued is None or time.time() - issued > cookie_ttl():
        return False
    return tok not in _revoked()


# --- сессия веб-чата (/chat) ---
# Пациент в журнал не входит, но ключ его сессии — это ЕДИНСТВЕННОЕ, чем он
# удостоверяется в движке: по `session_key` показываются «мои записи»,
# отменяется СВОЯ запись (db.cancel_appointment) и обновляется фиша
# (_upsert_patient). Значит выдавать его обязан сервер. Раньше /chat брал
# session_id прямо из тела запроса — а ключи рецепции строятся по угадываемому
# правилу `manual:<цифры телефона>` (db.admin_add, patients/routes), поэтому
# посторонний видел и отменял чужие визиты и переписывал имя в чужой фише.
# Приём тот же, что у куки журнала (_cookie_sig): значение подписывается
# секретом клиники, подделать его снаружи нечем.
# ⚠️ Telegram сюда не ходит: ключ `tg:<chat_id>` собирает сам адаптер на
# сервере из доверенного поля апдейта — это законное удостоверение.
CHAT_PREFIX = "web:"
# Облачное демо без ADMIN_KEY подписывать нечем: там _secret() пуст, и общий
# ключ был бы известен всем. Случайный ключ процесса честнее — сессии живут до
# перезапуска, ровно как сам диалог (engine.SESSIONS тоже в памяти).
_CHAT_FALLBACK = secrets.token_hex(32)


def _chat_sig(token: str) -> str:
    return hmac.new((_secret() or _CHAT_FALLBACK).encode(),
                    f"chat|{token}".encode(), hashlib.sha256).hexdigest()


def chat_session(raw: str) -> tuple[str, str]:
    """(session_key, что вернуть клиенту) по тому, что прислал браузер.

    Подпись не сошлась — это не отказ, а НОВАЯ сессия: так выглядит первый
    заход, чужая вкладка и смена пароля клиники (секрет подписи один). Пациенту
    незачем видеть ошибку — он просто начинает разговор сначала.
    """
    token, _, sig = (raw or "").partition(".")
    if not (token.isalnum() and len(token) <= 64 and sig
            and hmac.compare_digest(sig, _chat_sig(token))):
        token = secrets.token_hex(16)
        sig = _chat_sig(token)
    return CHAT_PREFIX + token, f"{token}.{sig}"


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
    if len(parts) == 5:
        uid, role, sid, tok, sig = parts
        if not hmac.compare_digest(sig, _cookie_sig(uid, role, sid, tok)):
            return None
        if not _session_alive(tok):
            return None            # срок вышел или человек вышел сам
        parts = [uid, role, sid, sig]
    elif lan_on():
        # кука без метки сессии (до 17.10): в сети у неё нет ни срока, ни
        # отзыва — один повторный вход после обновления
        return None
    if len(parts) == 4:
        uid, role, sid, sig = parts
        if len(raw.split(".")) == 4 and not hmac.compare_digest(
                sig, _cookie_sig(uid, role, sid)):
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
        if auth_blocked():
            # файл есть, но битый: НЕ первичная установка (она бы молча
            # стёрла учётки) — экран входа объяснит, что делать
            return RedirectResponse("/admin/login?err=broken", status_code=303)
        # без PIN — принудительная первичная установка
        return RedirectResponse("/admin/setup", status_code=303)
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
    вкладки ИМЕННО этого человека.

    `plen` — длина PIN (17.10). Нужна включению сети: «у кого PIN короче 6»
    по хешу не узнать, а перебирать 4–5-значные против PBKDF2 — часы. Унёсшему
    файл она почти ничего не даёт: он и так начинает с коротких, а 8-значных
    в 10 раз больше, чем всех остальных вместе. У записей до 17.10 поля нет —
    `verify_pin` доливает его при первом удачном входе (без вращения ключа).
    """
    salt = secrets.token_hex(16)
    return {"kdf": KDF, "iter": KDF_ITER, "salt": salt,
            "hash": _derive(pin, salt), "sid": secrets.token_hex(8),
            "plen": len(pin)}


def pin_readiness() -> tuple[list[dict], list[dict]]:
    """Готовы ли учётки к сети: (PIN короче `PIN_MIN_LAN`, длина неизвестна).

    Неизвестна — запись до 17.10, человек ещё не входил после обновления.
    ⭐ Переключатель (`settings/routes._set_lan`) держат ТОЛЬКО короткие:
    первая версия (17.10 днём) держала и неизвестных, и у канарейки сеть
    стало нельзя включить вовсе — вторая учётка (регистратура) не входила
    после обновления, а директор на экране видел кнопку, которая «не
    работает» (Олег 17.10 вечером). Неизвестная длина — янтарная подсказка
    на странице «Acces din rețea» («не проверена: войти один раз или задать
    новый PIN»), а короткая (известно < 6) — закрытая кнопка с причиной
    словами. Директор чинит короткий за минуту — новый PIN в учётках.
    """
    short, unknown = [], []
    for u in _users(_pin_rec()):
        n = u.get("plen")
        if n is None:
            unknown.append(_as_user(u))
        elif int(n) < PIN_MIN_LAN:
            short.append(_as_user(u))
    return short, unknown


def _note_plen(uid: str, n: int) -> None:
    """Долить длину PIN в запись (первый вход после обновления 17.10). Без
    вращения ключа: это не смена пароля, и выкидывать всех из журнала нельзя."""
    users = _users(_pin_rec())
    for u in users:
        if u.get("id") == uid:
            u["plen"] = n
    _save_users(users, rotate=False)


def _save_users(users: list[dict], *, rotate: bool) -> None:
    rec = _pin_rec() or {}
    key = rec.get("cookie_key") or ""
    if rotate or not key:
        key = secrets.token_hex(32)
    # Запись атомарная, как dbkey.store: обрыв посреди прямого write_text
    # оставил бы усечённый auth.json — а он раньше был неотличим от «PIN не
    # установлен», и все учётки клиники молча пропадали. tmp — в ТОЙ ЖЕ папке:
    # os.replace атомарен только в пределах одного тома.
    p = _auth_path()
    tmp = p.with_name(p.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"v": 2, "cookie_key": key, "users": users},
                               indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


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

    ⛔ **Против ЧУЖОГО корня эту функцию звать нельзя** — ни здесь, ни в
    миграции. Строчка выше про «переписывается в v2» и есть причина: удачная
    проверка ПИШЕТ в корень. Для источника есть `verify_source_pin` — он читает
    по явному пути и не пишет туда ничего.
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
            if u.get("plen") != len(pin):
                # запись до 17.10: длина нужна включению сети (pin_readiness);
                # единственный момент, когда PIN в руках, — вот он
                _note_plen(u.get("id", "clinic"), len(pin))
                return {**u, "plen": len(pin)}
            return u
    return None


async def change_pin(old_pin: str, new1: str, new2: str,
                     peer: str = "") -> tuple[str, dict | None]:
    """Смена СВОЕГО PIN: (код ответа, запись вошедшего для свежей куки).

    Зовёт JSON API (`settings/api.py`): старый PIN проверяется тем же
    оракулом, что и вход, и считает те же неудачи (`peer` — устройство, как у
    входа); новый обязан быть уникальным
    (вход идёт по одному лишь паролю — совпавший с чужим означал бы молчаливую
    смену роли); ключ подписи вращается, поэтому вызывающий ОБЯЗАН выдать
    свежую куку ответом, иначе первый же переход выкинет на вход.
    Коды: lock_pin / bad_pin / dup_user / ok_pin.
    """
    if not _pin_rec():
        return "bad_pin", None
    # своё сообщение, а не bad_pin: «старый PIN неверен» при блокировке — ровно
    # тот случай, когда экран врёт, и человек начинает перебирать верный PIN
    if lock_left(peer) > 0:
        return "lock_pin", None
    # форма смены — второй оракул для того же PIN, поэтому считает те же неудачи
    if (who := verify_pin(old_pin.strip())) is None:
        note_fail(peer)
        await asyncio.sleep(FAIL_DELAY)
        return "bad_pin", None
    note_ok(peer)
    n1, n2 = new1.strip(), new2.strip()
    if n1 != n2 or not pin_len_ok(n1):
        return "bad_pin", None
    # ⚠️ та же проверка, что в учётках, и по той же причине: verify_pin отдаёт
    # ПЕРВОГО совпавшего, а сменивший пароль ложится в конец списка —
    # проигрывает всегда именно он: директор со следующего входа получает куку
    # регистратуры и вернуть себе роль уже не может.
    if not pin_free(n1, except_uid=who.get("id", "clinic")):
        return "dup_user", None
    # роль и id берутся у вошедшего: смена своего PIN не должна никого повышать
    _write_pin(n1, role=who.get("role", ROLE_DIRECTOR), uid=who.get("id", "clinic"))
    await remember_auth_file()
    return "ok_pin", find_user(who.get("id", "clinic"))


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
    # _auth_broken отдельно: для _pin_rec битый файл тоже None, но предлагать
    # первичную установку поверх него нельзя — она бы стёрла живые учётки
    return _pin_rec() is None and not ADMIN_KEY and not _auth_broken()


def reset_grant(used: str) -> tuple[str, str]:
    """Разрешение администратора Windows на новый первый PIN поверх
    ИСЧЕЗНУВШЕГО auth.json (17.10): (метка, кто подтвердил), если метка
    `privileged.auth_reset_mark` свежее `RESET_WINDOW` и ещё не потрачена
    (`used` — meta `auth_reset_used`); ('', '') — разрешения нет. Зачем
    вообще — у `privileged._auth_reset`: папку данных пишут все учётки
    машины намеренно, и удаление файла было путём чужой учётки в директора.
    Сброс отличают от первой установки по отпечатку в базе (`auth_fp`
    непустой) — решает `entry/routes`; оно же пишет строку в ленту."""
    stamp, who = privileged.auth_reset_mark()
    if not stamp.isdigit() or stamp == used:
        return "", ""
    if time.time() - int(stamp) > privileged.RESET_WINDOW:
        return "", ""
    return stamp, who


def same_origin_post(request: Request) -> bool:
    """POST пришёл со СВОЕЙ страницы, а не с чужого сайта в браузере клиники.

    Все аутентифицированные формы от CSRF закрыты кукой: она SameSite=Lax, и
    на чужой POST браузер её не шлёт — маршрут отвечает редиректом на вход.
    Но три маршрута живут ДО куки — setup, login, recover, — и страница
    злоумышленника, открытая в браузере на машине клиники, могла бы отправить
    их сама: поставить первый PIN (пока auth.json нет) или накрутить счётчик
    подбора до блокировки. Браузер шлёт Origin на каждый POST; сравниваем его
    хост с Host запроса. Запрос БЕЗ Origin пропускается: это не браузер
    (тесты, curl), и CSRF там не существует. «null» (file://, sandbox) —
    отказ: непрозрачный origin неотличим от чужого.
    """
    origin = request.headers.get("origin", "")
    if not origin:
        return True
    if origin == "null":
        return False
    host = urllib.parse.urlsplit(origin).netloc
    return bool(host) and host.lower() == request.headers.get("host", "").lower()


# Имена сервера сверх своих: `DENTART_HOSTS=registru.clinica.md,…` в dental.env
# (клиника, которая завела своё DNS-имя, или шлюз перед сервером). Читается
# один раз — это настройка запуска, как ADMIN_KEY.
_EXTRA_HOSTS = frozenset(
    h.strip().lower() for h in os.environ.get("DENTART_HOSTS", "").split(",") if h.strip())


def host_allowed(request: Request) -> bool:
    """Заголовок Host называет ЭТОТ сервер, а не чужое DNS-имя (17.10).

    Закрывает DNS rebinding: страница злоумышленника, открытая в браузере на
    компьютере клиники, заводит имя `x.atacator.md`, которое через минуту
    начинает указывать на 127.0.0.1, — и её скрипт шлёт запросы прямо в
    программу, уже как «свой сайт»: `same_origin_post` их пропускал, потому
    что Origin и Host совпадали — оба были этим чужим именем (проверено
    посторонним разбором 17.10). Программа отвечает только на имена, которыми
    её открывают по-настоящему:
    - адрес числом (127.0.0.1, 192.168.1.10 с телефона, [::1]) — его в DNS не
      подменить;
    - `localhost` и `*.localhost`;
    - имя без точки (`receptie:8088` — компьютер в сети клиники): такое
      разрешается не публичным DNS, а самой сетью, снаружи его не завести;
    - имена из `DENTART_HOSTS`.
    Пустой Host — не браузер (HTTP/1.0, старые пробники): у браузера он есть
    всегда, а rebinding приходит именно с ним. Демо за шлюзом снимает проверку
    САМО (`demo.on()` в `main`): туда Host едет нетронутым (demo/gate.py).
    """
    raw = request.headers.get("host", "").strip().lower()
    if not raw:
        return True
    if raw.startswith("["):                      # [::1]:8088
        host = raw[1:raw.find("]")] if "]" in raw else raw
    else:
        host = raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw
    if host == "localhost" or host.endswith(".localhost") or "." not in host:
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return host in _EXTRA_HOSTS


def client_is_local(request: Request) -> bool:
    """Запрос пришёл с ЭТОГО компьютера, а не из сети клиники.

    Нужна первичной установке PIN: пока auth.json нет, журнал не защищён ничем,
    и при включённом «Acces din rețea» (bind 0.0.0.0, флаг переживает
    переустановку) любой компьютер сети мог бы назначить себе первый PIN и
    стать единственным директором. Спрашиваем ПИРА соединения, а не заголовки:
    X-Forwarded-* пишет кто угодно, а uvicorn без --proxy-headers их и не
    разбирает. Пустой адрес — отказ: неоткуда не значит «отсюда».
    """
    host = (request.client.host or "") if request.client else ""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    # dual-stack отдаёт loopback как ::ffff:127.0.0.1, а у ipaddress такой
    # адрес НЕ is_loopback — разворачиваем в честный IPv4
    mapped = getattr(addr, "ipv4_mapped", None)
    return (mapped or addr).is_loopback


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
# Пороги лестницы — наружу для журнала: всплеск подбора пишется в ленту на
# СТУПЕНЯХ, а не на каждой неудаче. Считать от _LOCK_STEPS, не копией: копия
# разъехалась бы при первой правке лестницы.
LOCK_STEP_COUNTS = tuple(cnt for cnt, _sec in _LOCK_STEPS)
# Пауза на КАЖДОЙ неудаче, ещё до блокировки: превращает «10 000 попыток за
# минуту» в часы, а живому человеку стоит одного мгновения.
FAIL_DELAY = 0.7
_fail_mem: dict = {}          # без папки данных (нет DATABASE_URL) — помним в ОЗУ


def _fail_path() -> pathlib.Path | None:
    d = _data_dir()
    return d / "auth_fail.json" if d else None


def _state_read(p: pathlib.Path) -> dict:
    """Состояние счётчика с диска. Нечитаемое — это ПУСТО, а не отказ во входе:
    иначе повреждённый файл запирал бы клинику наглухо."""
    if p.exists():
        try:
            got = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return got if isinstance(got, dict) else {}
    return {}


def _state_write(p: pathlib.Path, st: dict) -> None:
    """Атомарно, тем же приёмом, что auth.json (_save_users): обрыв посреди
    прямой записи оставлял усечённый файл, а читается он как ПУСТОЙ — счётчик
    подбора молча обнулялся ровно тому, кто перебирает (аудит 08-20). tmp в той
    же папке: os.replace атомарен в пределах тома."""
    tmp = p.with_name(p.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(st))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError:
        # сбой записи не должен превращаться в отказ во входе; прежнее
        # состояние файла при этом цело — replace до него не дошёл
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _fail_state() -> dict:
    p = _fail_path()
    return dict(_fail_mem) if p is None else _state_read(p)


def _fail_save(st: dict) -> None:
    p = _fail_path()
    if p is None:
        _fail_mem.clear()
        _fail_mem.update(st)
        return
    _state_write(p, st)


def _lock_for(n: int) -> int:
    """На сколько секунд закрыть после n неудач подряд.

    ⭐ Вычислитель один на все формы, спрашивающие PIN. Второй счётчик (у
    подтверждения источника, P2) считает СВОИ неудачи, но лестница у него та
    же — и получает он её отсюда, а не копией: копия разъехалась бы при первой
    же правке `_LOCK_STEPS`, и разъехалась бы молча.
    """
    return next((sec for cnt, sec in _LOCK_STEPS if n >= cnt), 0)


# --- счётчик на устройство (17.10, посторонний разбор) ---
# До 17.10 счётчик был один на клинику: телефон, перебирающий PIN из Wi-Fi,
# запирал и стойку, а каждый удачный вход сотрудника обнулял счётчик
# подборщику. Теперь ДВА слоя в одном auth_fail.json:
#   * на устройство — ключ `client_peer`: loopback целиком = "local" (скрипт
#     на самом ПК может слать с любого 127.x.x.x), иначе адрес. Та же лестница,
#     обнуляет только удачный вход С ЭТОГО устройства;
#   * общий по сети — прежние `fails/until` как заслон от смены адресов
#     (подборщик с ноутбука берёт себе хоть 254 адреса). Та же лестница, но
#     ступени втрое выше (`_NET_FACTOR`): промахи трёх телефонов за утро не
#     должны запирать четвёртый. Стойку (local) он не запирает и удачным
#     входом не обнуляется — распадается сам после 15 минут тишины
#     (`_QUIET`), иначе клиника копила бы чужие промахи месяцами и каждая
#     опечатка стоила бы 15 минут всем телефонам.
# ⚠️ Пустой peer (за шлюзом демо все приходят с одного адреса; нет адреса) —
# поведение до 17.10 целиком: один общий счётчик, обнуляется удачным входом.
PEER_LOCAL = "local"
_NET_FACTOR = 3
# Ступени общего заслона — для ленты (как LOCK_STEP_COUNTS у устройства)
NET_STEP_COUNTS = tuple(cnt * _NET_FACTOR for cnt in LOCK_STEP_COUNTS)
_QUIET = max(sec for _n, sec in _LOCK_STEPS)      # распад общего счётчика
_PEER_KEEP = 24 * 3600                              # забытые устройства уходят
_PEER_CAP = 500                                     # потолок записей в файле


def client_peer(request: Request) -> str:
    """Ключ устройства для счётчика неудач по ПИРУ соединения (не по
    заголовкам: X-Forwarded-* пишет кто угодно). '' — считать по-старому."""
    from . import demo                 # core → core; у demo импортов auth нет
    if demo.on():
        return ""
    host = (request.client.host or "") if request.client else ""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return ""
    addr = getattr(addr, "ipv4_mapped", None) or addr
    return PEER_LOCAL if addr.is_loopback else str(addr)


def peer_label(peer: str) -> str:
    """Как назвать устройство в ленте клиники."""
    return "acest calculator" if peer == PEER_LOCAL else peer


def _peer_of(st: dict, peer: str) -> dict:
    p = (st.get("peers") or {}).get(peer)
    return p if isinstance(p, dict) else {}


def _global_fails(st: dict, now: float, decays: bool) -> int:
    """Общий счётчик с распадом после тишины — только у слоя на устройство."""
    if decays and now - float(st.get("at") or 0) > _QUIET:
        return 0
    return int(st.get("fails", 0))


def lock_left(peer: str = "") -> int:
    """Сколько секунд вход закрыт для этого устройства (0 — открыт):
    своя блокировка и, кроме стойки, общая по сети."""
    st, now = _fail_state(), time.time()
    left = 0
    if peer != PEER_LOCAL:
        left = max(left, int(float(st.get("until") or 0) - now))
    if peer:
        left = max(left, int(float(_peer_of(st, peer).get("until") or 0) - now))
    return max(0, left)


def note_fail(peer: str = "") -> int:
    """Записать неудачу, вернуть срок блокировки для ЭТОГО устройства в
    секундах (0 — ещё пускаем).

    Счётчик после снятия блокировки НЕ обнуляется намеренно: иначе перебор
    продолжается пачками по пять, а так каждая следующая ошибка снова стоит
    полминуты. Обнуляет только удачный вход (с того же устройства).
    """
    st, now = _fail_state(), time.time()
    if peer != PEER_LOCAL:
        n = _global_fails(st, now, decays=bool(peer)) + 1
        # с устройством общий слой — заслон, ступени втрое выше; без него
        # (старый режим) — прежняя лестница как есть
        lock = _lock_for(n // _NET_FACTOR if peer else n)
        st.update({"fails": n, "until": now + lock if lock else 0, "at": now})
    if peer:
        peers = {k: v for k, v in (st.get("peers") or {}).items()
                 if isinstance(v, dict) and now - float(v.get("at") or 0) <= _PEER_KEEP}
        m = int(_peer_of(st, peer).get("fails", 0)) + 1
        lock = _lock_for(m)
        peers[peer] = {"fails": m, "until": now + lock if lock else 0, "at": now}
        if len(peers) > _PEER_CAP:          # подборщик со сменой адресов не
            for k in sorted(peers, key=lambda k: peers[k]["at"])[:-_PEER_CAP]:
                peers.pop(k)                # раздует файл до бесконечности
        st["peers"] = peers
    _fail_save(st)
    return lock_left(peer)


def note_ok(peer: str = "") -> None:
    """Удачный вход: своё устройство прощено. Общий счётчик — только в старом
    режиме (без устройства): иначе каждый вход сотрудника с телефона давал бы
    подборщику новые попытки — ровно то, что нашёл разбор 17.10."""
    st = _fail_state()
    if peer:
        peers = dict(st.get("peers") or {})
        peers.pop(peer, None)
        st["peers"] = peers
    else:
        st.update({"fails": 0, "until": 0})
    _fail_save(st)


def fail_count(peer: str = "") -> int:
    """Сколько неудач подряд накоплено — у устройства (peer) или общих по сети.
    Для журнала входов: сам счётчик обнуляется удачным входом, и серия подбора
    иначе исчезала бы без следа."""
    st = _fail_state()
    if peer:
        return int(_peer_of(st, peer).get("fails", 0))
    # распад здесь безвреден и для старого режима: ленту спрашивают сразу
    # после note_fail, когда `at` — только что
    return _global_fails(st, time.time(), decays=True)


# --- подтверждение ЧУЖОГО корня (P2, экран раздвоения) ---------------------
# Контракт — `docs/dentpilot-2/split-contract.md`. Вопрос там ровно один и он
# про ПРОИСХОЖДЕНИЕ: «какая из двух картотек настоящая», и ответ подтверждается
# PIN выбранного ИСТОЧНИКА, а не личностью того, кто сидит за машиной.
#
# ⛔ Позвать для этого `verify_pin` нельзя, и причин две, обе молчаливые:
#   1. при удаче он переписывает файл v1→v2 — то есть ПИШЕТ в корень, который
#      мы ещё не решили копировать, да ещё и меняет ключ подписи сессий той
#      установки. Copy-only ломается до того, как начнётся;
#   2. и он, и счётчик попыток привязаны к папке, В КОТОРОЙ ИДЁТ ПРОГРАММА
#      (`_data_dir`), а спрашивают нас про ДРУГОЙ корень — тот, что назвал
#      человек. Переиспользовать их против чужого корня нельзя вовсе.
#
# ⭐ Хорошая новость, без которой это не сошлось бы: auth.json — обычный файл
# рядом с базой, а не внутри неё. Прочитать его можно, НЕ ОТКРЫВАЯ базу никаким
# драйвером, то есть не нарушая ни правила шага 2, ни copy-only.

SRC_OK = "ok"              # PIN подошёл — источник подтверждён
SRC_BAD = "bad"            # не подошёл: попытка засчитана в НАЗНАЧЕНИИ
SRC_LOCKED = "locked"      # подбор: закрыто на N секунд, оракул не спрошен
SRC_NO_AUTH = "no-auth"    # в источнике нет auth.json — подтверждать нечем
SRC_BROKEN = "broken"      # auth.json есть, но не читается
SRC_NO_USERS = "no-users"  # читается, но учётных записей в нём нет

# ⛔ Исходы, на которых миграция ОСТАНАВЛИВАЕТСЯ, и подтверждения не будет
# вовсе. Ни один из них не «пропустить» и не «считать подтверждённым»: это тот
# же случай, что забытый PIN старой установки — честная остановка, а не скрытая
# ветка внутри миграции. Молчаливый пропуск означал бы, что картотеку клиники
# выбирает любой, кто сел за машину.
# ⚠️ Их три, а не один, потому что различать их обязан экран: «PIN не ставили»
# и «файл повреждён» ведут человека в разные стороны, и второе нельзя
# показывать как первое (тот же прайор, что у `_auth_broken`).
SRC_STOP = (SRC_NO_AUTH, SRC_BROKEN, SRC_NO_USERS)

# Счётчик подтверждения источника — ОТДЕЛЬНЫЙ файл, не auth_fail.json.
# ⚠️ Это не аккуратность, а развод двух разных секретов. PIN источника и PIN
# назначения лежат в разных файлах и совпадать не обязаны; общий счётчик
# означал бы, что перебор на экране миграции закрывает вход в журнал, в котором
# клиника В ЭТУ МИНУТУ принимает (при `split` назначение — рабочая картотека),
# и наоборот — что рабочий день с парой опечаток на входе запрещает миграцию.
SRC_FAIL_NAME = "srcpin_fail.json"


def source_auth_file(source_root: pathlib.Path | str) -> pathlib.Path:
    """Где в ЧУЖОМ корне лежит auth.json.

    ⚠️ Раскладка берётся у `relocate`, а не собирается здесь строкой: внутри
    работающей программы то же место считает `paths.db_dir()` от
    `$DATABASE_URL`, но у чужого корня такого ответа нет — его никто не
    запускал. Второй вычислитель раскладки однажды заглянет мимо и доложит
    «PIN не ставили» про установку, где он есть.
    """
    return pathlib.Path(source_root) / relocate.DATA_REL / AUTH_NAME


class SourcePinAttempts:
    """Счётчик попыток подтверждения источника. Живёт в НАЗНАЧЕНИИ — всегда.

    ⭐ Разрешение противоречия из контракта: отказаться от счётчика нельзя
    (стойкость хеша и счётчик попыток лечат РАЗНЫЕ переборы, и одно другого не
    заменяет), а писать в источник нельзя тем более. Значит состояние живёт там,
    где писать можно: в папке данных работающей программы.

    ⚠️ Папка передаётся ЯВНО, и `_data_dir()` внутри не спрашивается намеренно.
    Ambient-путь — ровно та ловушка, из-за которой нельзя переиспользовать
    `note_fail`: он «сам знает», куда писать, и знает не то. Здесь место
    выбирает вызывающий, а `verify_source_pin` проверяет его выбор.
    """

    def __init__(self, dest_dir: pathlib.Path | str):
        if dest_dir is None:
            raise ValueError("счётчику попыток нужна папка назначения")
        self.dir = pathlib.Path(dest_dir)
        self.path = self.dir / SRC_FAIL_NAME

    def closed_for(self) -> int:
        """Сколько секунд подтверждение закрыто (0 — открыто)."""
        return max(0, int(_state_read(self.path).get("until", 0) - time.time()))

    def fails(self) -> int:
        return int(_state_read(self.path).get("fails", 0))

    def count_fail(self) -> int:
        """Записать неудачу, вернуть срок блокировки. Лестница общая
        (`_lock_for`), счётчик свой."""
        n = self.fails() + 1
        lock = _lock_for(n)
        _state_write(self.path,
                     {"fails": n, "until": time.time() + lock if lock else 0})
        return lock

    def clear(self) -> None:
        _state_write(self.path, {"fails": 0, "until": 0})


def destination_attempts() -> SourcePinAttempts:
    """Счётчик там, где программа работает СЕЙЧАС, — то есть в назначении."""
    d = _data_dir()
    if d is None:
        raise RuntimeError("папка данных не названа — подтверждать негде")
    return SourcePinAttempts(d)


def _src(outcome: str, why: str, attempts: SourcePinAttempts,
         lock: int = 0) -> dict:
    return {"outcome": outcome, "ok": outcome == SRC_OK, "lock_left": lock,
            "fails": attempts.fails(), "stop": outcome in SRC_STOP, "why": why}


async def verify_source_pin(source_root: pathlib.Path | str, pin: str,
                            attempts: SourcePinAttempts) -> dict:
    """Подтвердить право на ЧУЖОЙ корень его собственным PIN. Чистое чтение.

    Возвращает вердикт: `outcome` (одно из `SRC_*`), `ok`, `lock_left`, `fails`,
    `stop`, `why`. ⛔ Запись вошедшего НЕ возвращается, и это не экономия:
    подтверждается ПРОИСХОЖДЕНИЕ, а не личность. Вернув пользователя, функция
    стала бы вторым входом в журнал — по файлу из корня, который ещё даже не
    признан настоящим.

    Чего эта функция не делает, и ради чего написана отдельно:
      * не открывает базу — ни одним драйвером, ни на чтение;
      * не переписывает auth.json источника, в том числе v1 → v2 при УДАЧЕ;
      * не трогает ключ подписи сессий источника;
      * не создаёт в источнике ни `auth_fail.json`, ни любого другого файла;
      * ничего не пишет в источник вообще — ни при удаче, ни при неудаче.

    ⚠️ Самый опасный дефект здесь — именно УДАЧНАЯ проверка: неудачная ничего
    записать и не пробует, а удачная в `verify_pin` как раз мигрирует файл. Оба
    исхода проверяются снимком дерева побайтно (`tests/test_srcpin.py`).
    """
    src = pathlib.Path(source_root)
    # ⛔ Инвариант в КОДЕ, а не в тексте: состояние счётчика не может оказаться
    # внутри источника. Явный аргумент за тем и введён — но явный аргумент
    # можно и передать неверно, а такая ошибка обязана быть громкой: тихо она
    # выглядела бы как исправная миграция, оставившая в источнике лишний файл.
    try:
        inside = (attempts.path.resolve().is_relative_to(src.resolve())
                  if src.exists() else False)
    except OSError:
        inside = False
    if inside:
        raise ValueError(
            f"счётчик попыток внутри источника ({attempts.path}) — "
            f"подтверждение обязано оставить {src} нетронутым")

    # Блокировка спрашивается ДО источника: закрытое подтверждение не читает
    # чужой файл вовсе, и перебор упирается в ту же лестницу, что вход.
    if (lock := attempts.closed_for()) > 0:
        return _src(SRC_LOCKED, "подбор: подтверждение закрыто", attempts, lock)

    p = source_auth_file(src)
    if not p.exists():
        return _src(SRC_NO_AUTH, f"в источнике нет {p.name}", attempts)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _src(SRC_BROKEN, f"{p.name} не читается", attempts)
    users = _users(rec) if isinstance(rec, dict) else []
    if not users:
        return _src(SRC_NO_USERS, f"в {p.name} нет учётных записей", attempts)

    for u in users:
        want = u.get("hash", "")
        try:
            got = _derive(pin, u.get("salt", ""), u.get("kdf", KDF),
                          int(u.get("iter") or KDF_ITER))
        except (TypeError, ValueError):
            continue        # запись из будущей версии: не наше дело её чинить
        if want and hmac.compare_digest(got, want):
            # ⛔ И ВОТ ЗДЕСЬ `verify_pin` записал бы файл v1→v2. Мы — нет:
            # источник остаётся байт в байт таким, каким его нашли, и чинить
            # его формат будет уже перенесённая копия, если понадобится.
            attempts.clear()
            return _src(SRC_OK, "источник подтверждён", attempts)

    lock = attempts.count_fail()
    await asyncio.sleep(FAIL_DELAY)
    return _src(SRC_BAD, "PIN не подошёл", attempts, lock)


# --- то, что зовёт ЭКРАН, и больше ничего ---------------------------------
# ⭐ Экран раздвоения не имеет права знать, как устроены auth.json, хеши, счётчик
# и его лестница: страница, повторившая любую из этих деталей, станет вторым
# местом, где живёт правда о PIN, и разойдётся с первым молча.
# ⚠️ Явный аргумент у `verify_source_pin` при этом остаётся, и обёртка его не
# отменяет: там он защищает от записи в источник, а называть назначение обязан
# тот, кто знает, где можно писать, — то есть этот модуль.


async def confirm_source(source_root: pathlib.Path | str, pin: str) -> dict:
    """Подтвердить выбранный корень его PIN. Счётчик — там, где писать можно."""
    return await verify_source_pin(source_root, pin, destination_attempts())


def source_pin_closed_for() -> int:
    """На сколько секунд подтверждение закрыто подбором (0 — открыто)."""
    return destination_attempts().closed_for()
