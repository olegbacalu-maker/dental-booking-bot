"""Кабинет клиники (шаг 3 плана, 01.10): вход через Google, учётная запись, привязка к клинике.

cloud.md › «Кабинет клиники». Клиника входит на cloud.dentpilot.md/cont своим
аккаунтом Google (OpenID Connect: код авторизации, обмен кода на id_token
делает СЕРВЕР, с client_secret). Пароля у нас нет и не будет — его держит
Google; нам приходят только идентификатор аккаунта (`sub`), e-mail и имя.
Учётная запись (`accounts`) — это «кто вошёл»; клиника — отдельная строка,
к которой запись привязана (`clinic_id`), и у одной клиники записей может
быть несколько (директор и администратор).

Привязка — по ПОДТВЕРЖДЁННОМУ Google e-mail: клиника с тем же ящиком (в
канонической форме, как у формы /proba — trial.canonical) уже есть → это
она, кабинет открывается сразу; нет → страница регистрации: та же заявка на
пробный, что у /proba и у программы (trial.submit, те же правила и лимиты),
только e-mail берётся из Google и не редактируется. Повтор по IDNO при
другом ящике — отказ словами и письмо Олегу: чужой IDNO в заявке — его
решение, не автомата. Отсюда же смена директора: Олег вписывает клинике
новый e-mail и отвязывает старую запись; новый директор входит через Google
и попадает в кабинет по ящику, старый на входе получает регистрацию, а она
по IDNO отказывает.

⛔ Подпись id_token здесь не проверяется — намеренно. Токен приходит не от
браузера, а прямым HTTPS-запросом сервера к Google с client_secret, и Google
в документации говорит ровно это: токен, полученный так, можно не проверять
по подписи. Проверяются iss, aud, exp, nonce и email_verified — то, что
отличает «этот человек в этом входе» от чужого токена. Второй разбор JWT с
JWKS — слой, который однажды разошёлся бы с первым.

Адреса Google (config.GOOGLE_AUTH_URL / GOOGLE_TOKEN_URL) меняют только
тесты: стенд Google живёт в процессе теста, прод знает одни адреса.
"""
from __future__ import annotations

import base64
import json
import logging
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import auth, config, db, trial

log = logging.getLogger("cloud.account")

CALLBACK_PATH = "/auth/google/callback"
SCOPE = "openid email profile"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
TIMEOUT = 10                     # обмен кода на токен: Google отвечает за доли секунды
ADDRESS_MAX = 200
# Коды отказа входа — ключи views.CONT_MSG
DENIED, EXPIRED, FAILED, UNVERIFIED, OFF = "google_denied", "google_expired", "google_failed", "google_unverified", "google_off"


@dataclass
class Identity:
    sub: str
    email: str
    name: str


def enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def callback_url() -> str:
    """Тот же адрес, что вписан в консоли Google как Authorized redirect URI."""
    return config.BASE_URL.rstrip("/") + CALLBACK_PATH


# ---------- шаг 1: к Google ----------


def begin() -> tuple[str, str]:
    """(адрес Google, значение куки dp_oauth). Кука несёт state и nonce: state
    сверяется с ответом Google (чужой callback не пройдёт), nonce — с id_token."""
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {"client_id": config.GOOGLE_CLIENT_ID, "redirect_uri": callback_url(),
              "response_type": "code", "scope": SCOPE, "state": state, "nonce": nonce,
              "prompt": "select_account", "access_type": "online"}
    return config.GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params), auth.oauth_cookie(f"{state}|{nonce}")


# ---------- шаг 2: от Google ----------


def _claims(id_token: str) -> dict | None:
    """Полезная нагрузка JWT без проверки подписи (почему — в шапке модуля)."""
    parts = id_token.split(".")
    if len(parts) != 3:
        return None
    try:
        raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def exchange(code: str) -> dict | None:
    """Код → ответ Google (id_token внутри). None — Google не ответил или отказал."""
    body = urllib.parse.urlencode({"code": code, "client_id": config.GOOGLE_CLIENT_ID,
                                   "client_secret": config.GOOGLE_CLIENT_SECRET,
                                   "redirect_uri": callback_url(),
                                   "grant_type": "authorization_code"}).encode("ascii")
    req = urllib.request.Request(config.GOOGLE_TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read(64 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        log.warning("google token: %s %s", e.code, e.read(500)[:500])
        return None
    except (OSError, ValueError) as e:
        log.warning("google token: %r", e)
        return None
    return data if isinstance(data, dict) else None


def verify(claims: dict, nonce: str, now: float | None = None) -> tuple[Identity | None, str]:
    """Проверка claim'ов id_token → (личность, '') или (None, код отказа)."""
    now = now or time.time()
    try:
        exp = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        exp = 0
    if (claims.get("iss") not in ISSUERS or claims.get("aud") != config.GOOGLE_CLIENT_ID
            or exp <= now or not nonce or claims.get("nonce") != nonce):
        return None, FAILED
    sub, email = str(claims.get("sub") or ""), str(claims.get("email") or "").strip()
    if not sub or not email:
        return None, FAILED
    if claims.get("email_verified") is not True:
        return None, UNVERIFIED
    name = " ".join(str(claims.get("name") or "").split())[:trial.CONTACT_MAX]
    return Identity(sub, email[:trial.EMAIL_MAX], name), ""


def finish(code: str, state: str, cookie: str) -> tuple[Identity | None, str]:
    """Callback Google: state против куки, обмен кода, проверка токена."""
    saved = auth.read_oauth_cookie(cookie)
    if saved is None:
        return None, EXPIRED
    want_state, _, nonce = saved.partition("|")
    if not code or not state or not secrets.compare_digest(state, want_state):
        return None, EXPIRED
    data = exchange(code)
    if not data or not isinstance(data.get("id_token"), str):
        return None, FAILED
    claims = _claims(data["id_token"])
    if claims is None:
        return None, FAILED
    return verify(claims, nonce)


# ---------- учётные записи ----------


def find(con: sqlite3.Connection, sub: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM accounts WHERE provider='google' AND subject=?", (sub,)).fetchone()


def get(con: sqlite3.Connection, aid: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()


def login(con: sqlite3.Connection, ident: Identity, ip: str) -> sqlite3.Row:
    """Вошедший Google-аккаунт → строка accounts (новая или прежняя). Запись без
    клиники тут же привязывается к клинике с тем же подтверждённым ящиком, если
    такая есть и не скрыта."""
    now = db.now_iso()
    acc = find(con, ident.sub)
    if acc is None:
        aid = "a_" + secrets.token_hex(6)
        con.execute("INSERT INTO accounts(id, provider, subject, email, name, created_at, last_login_at) "
                    "VALUES(?,?,?,?,?,?,?)", (aid, "google", ident.sub, ident.email, ident.name, now, now))
        db.audit(con, ident.email, "account_new", None, f"Google, {ip}")
    else:
        aid = acc["id"]
        con.execute("UPDATE accounts SET email=?, name=?, last_login_at=? WHERE id=?",
                    (ident.email, ident.name, now, aid))
    acc = get(con, aid)
    if not acc["clinic_id"]:
        same = trial.existing(con, "", ident.email)
        if same is not None:
            link(con, acc, same["id"], f"по e-mail {ident.email}")
            acc = get(con, aid)
    db.audit(con, ident.email, "account_login", acc["clinic_id"], ip)
    return acc


def link(con: sqlite3.Connection, acc: sqlite3.Row, clinic_id: str, how: str) -> None:
    con.execute("UPDATE accounts SET clinic_id=? WHERE id=?", (clinic_id, acc["id"]))
    db.audit(con, acc["email"], "account_link", clinic_id, how)


def detach(con: sqlite3.Connection, acc: sqlite3.Row, who: str) -> None:
    """Отвязать и удалить запись: следующий вход этого аккаунта — как первый."""
    con.execute("DELETE FROM accounts WHERE id=?", (acc["id"],))
    db.audit(con, who, "account_detach", acc["clinic_id"], f"{acc['email']} ({acc['id']})")


def of_clinic(con: sqlite3.Connection, clinic_id: str) -> list:
    return con.execute("SELECT * FROM accounts WHERE clinic_id=? ORDER BY created_at", (clinic_id,)).fetchall()


def register(con: sqlite3.Connection, acc: sqlite3.Row, f: dict, ip: str) -> tuple[str, sqlite3.Row]:
    """Регистрация клиники из кабинета: заявка на пробный теми же правилами, что
    /proba (trial.submit), e-mail — ящик Google. Не повтор → запись привязана."""
    outcome, clinic = trial.submit(con, dict(f, email=acc["email"]), ip, who=acc["email"],
                                   origin=trial.ORIGIN_CONT)
    if outcome != trial.DUPLICATE:
        link(con, acc, clinic["id"], "регистрация в кабинете")
    return outcome, clinic


def clean_edit(fields: dict) -> tuple[dict, str]:
    """Реквизиты из кабинета: те же границы, что у заявки; IDNO — 13 цифр или пусто."""
    f = {k: " ".join((fields.get(k) or "").split()) for k in ("name", "idno", "contact_name", "phone", "address")}
    f["idno"] = f["idno"].replace(" ", "")
    if not 2 <= len(f["name"]) <= trial.NAME_MAX:
        return f, "bad_name"
    if f["idno"] and not trial.IDNO_RE.match(f["idno"]):
        return f, "bad_idno"
    if (len(f["contact_name"]) > trial.CONTACT_MAX or len(f["phone"]) > trial.PHONE_MAX
            or len(f["address"]) > ADDRESS_MAX):
        return f, "too_long"
    return f, ""


def idno_taken(con: sqlite3.Connection, idno: str, clinic_id: str) -> bool:
    """Тот же IDNO у другой живой клиники — кабинету его не присвоить."""
    if not idno:
        return False
    return con.execute("SELECT 1 FROM clinics WHERE idno=? AND id<>? AND declined_at IS NULL",
                       (idno, clinic_id)).fetchone() is not None
