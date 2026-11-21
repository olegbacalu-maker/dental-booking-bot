"""Вход в Google для программы на ПК клиники: клиент «Desktop app», возврат на 127.0.0.1, PKCE S256.

Модуль чистый: ни базы, ни файлов, ни часов, ни импортов проекта (как core/sms.py). Ошибки — коды
из CODES, слова экрана даёт вызывающий. Срок токена приходит секундами (`expires_in`): момент
считает тот, у кого часы.

    consent_url → браузер Windows → возврат на loopback → back() → exchange()
    refresh()   — новый access-токен по refresh-токену
    revoke()    — отзыв у Google («Deconectează»)

Редиректам клиент не следует (токен в теле не уезжает на чужой адрес), тело читается с потолком.
Токены, код и секрет клиента не пишутся в лог нигде — ни здесь, ни у вызывающего.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

CALENDARLIST_READONLY = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
EVENTS_READONLY = "https://www.googleapis.com/auth/calendar.events.readonly"
# Права программы — только здесь: согласие, проверка выданного и заявка на проверку Google
# обязаны просить одно и то же.
SCOPES = (CALENDARLIST_READONLY, EVENTS_READONLY)

TIMEOUT = 15.0
MAX_BODY = 64 * 1024

# ---- исход запроса к Google ----

OK = "ok"
INVALID_GRANT = "invalid_grant"     # код или refresh-токен мёртв: отозван, истёк, чужой — нужен новый вход
INVALID_CLIENT = "invalid_client"   # Google не признал клиента сборки — новый вход не поможет
ADMIN_POLICY = "admin_policy"       # админ Workspace клиники закрыл доступ приложению
NO_REFRESH = "no_refresh"           # согласие без refresh-токена: опрашивать было бы нечем
RATE_LIMITED = "rate_limited"
OFFLINE = "offline"                 # сеть, таймаут, 5xx, редирект, чужой ответ — повторить позже
BAD_REQUEST = "bad_request"         # прочий 4xx — ошибка нашей стороны, `reason` — для лога
CODES = (OK, INVALID_GRANT, INVALID_CLIENT, ADMIN_POLICY, NO_REFRESH, RATE_LIMITED, OFFLINE, BAD_REQUEST)

# ---- что принёс браузер на адрес возврата ----

BAD_STATE = "bad_state"             # не наш вход: чужой или повторный адрес — кода не трогать
ACCESS_DENIED = "access_denied"     # человек нажал «Cancel» на экране Google
NO_CODE = "no_code"
FAILED = "failed"                   # Google вернул другую ошибку, она в `reason`
BACK_CODES = (OK, BAD_STATE, ACCESS_DENIED, NO_CODE, FAILED)


@dataclass(frozen=True)
class Client:
    id: str
    secret: str = ""


@dataclass(frozen=True)
class Grant:
    access: str
    expires_in: int
    refresh: str = ""               # у обновления обычно пусто: прежний refresh-токен остаётся в силе
    scopes: frozenset = frozenset()


@dataclass(frozen=True)
class Reply:
    code: str
    grant: Grant | None = None
    status: int = 0                 # HTTP-статус; 0 — ответа не было
    reason: str = ""                # код ошибки Google, для лога


@dataclass(frozen=True)
class Back:
    code: str
    auth_code: str = ""
    scopes: frozenset = frozenset()
    reason: str = ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def client_of(raw: bytes | str) -> Client | None:
    """JSON клиента из консоли Google (`{"installed": {...}}`) → Client; другой файл — None.
    Клиент «Web application» (`"web"`) не годится: loopback-вход он не примет."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    block = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return None
    cid, secret = block.get("client_id"), block.get("client_secret", "")
    if not isinstance(cid, str) or not cid.strip().endswith(".apps.googleusercontent.com"):
        return None
    return Client(cid.strip(), secret.strip() if isinstance(secret, str) else "")


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pkce() -> tuple[str, str]:
    """(verifier, challenge). 64 случайных байта дают 86 знаков — в пределах 43–128 RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    return verifier, challenge(verifier)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def loopback(port: int, path: str = "/") -> str:
    """Адрес возврата. Только 127.0.0.1: `localhost` Google не советует из-за брандмауэров.
    Адрес обязан совпасть буква в букву в согласии и в обмене — строить его одной функцией."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("port")
    if not path.startswith("/") or any(c in path for c in "?#\\ %"):
        raise ValueError("path")
    return f"http://127.0.0.1:{port}{path}"


def consent_url(client: Client, redirect_uri: str, state: str, code_challenge: str, *,
                scopes: tuple = SCOPES, login_hint: str = "", auth_url: str = AUTH_URL) -> str:
    """Адрес экрана согласия Google — открыть в браузере Windows, не во встроенном окне:
    встроенное окно для входа Google запрещает правилами."""
    _check_url(auth_url)
    q = {"client_id": client.id, "redirect_uri": redirect_uri, "response_type": "code",
         "scope": " ".join(scopes), "code_challenge": code_challenge,
         "code_challenge_method": "S256", "state": state}
    if login_hint:
        q["login_hint"] = login_hint
    return auth_url + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def back(query: str, state: str) -> Back:
    """Разбор возврата из браузера: строка запроса адреса возврата и `state` своего входа.
    `state` сверяется первым, и при ошибке тоже: чужой адрес не должен ни менять, ни гасить вход."""
    q = urllib.parse.parse_qs(query or "", keep_blank_values=True)
    one = {k: v[0] for k, v in q.items() if len(v) == 1}
    got = one.get("state", "")
    if not state or not got or not hmac.compare_digest(got.encode("utf-8"), state.encode("utf-8")):
        return Back(BAD_STATE)
    if "error" in q:
        err = one.get("error", "")
        return Back(ACCESS_DENIED if err == "access_denied" else FAILED, reason=err[:64])
    code = one.get("code", "")
    if not code:
        return Back(NO_CODE)
    return Back(OK, auth_code=code, scopes=frozenset(one.get("scope", "").split()))


def missing(scopes: frozenset, wanted: tuple = SCOPES) -> tuple:
    """Права, которые человек снял галочкой на экране согласия: Google выдаёт их по отдельности."""
    return tuple(s for s in wanted if s not in scopes)


def exchange(client: Client, code: str, verifier: str, redirect_uri: str, *,
             timeout: float = TIMEOUT, token_url: str = TOKEN_URL, agent: str = "DentPilot") -> Reply:
    """Код из возврата → токены. Без refresh-токена — NO_REFRESH, а не OK."""
    r = _post(token_url, {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                          "redirect_uri": redirect_uri, "client_id": client.id},
              client.secret, timeout, agent, grant=True)
    if r.code == OK and not r.grant.refresh:
        return Reply(NO_REFRESH, status=r.status)
    return r


def refresh(client: Client, refresh_token: str, *, timeout: float = TIMEOUT,
            token_url: str = TOKEN_URL, agent: str = "DentPilot") -> Reply:
    """Новый access-токен. `grant.refresh` непустой — Google выдал новый refresh-токен, хранить его."""
    return _post(token_url, {"grant_type": "refresh_token", "refresh_token": refresh_token,
                             "client_id": client.id},
                 client.secret, timeout, agent, grant=True)


def revoke(token: str, *, timeout: float = TIMEOUT, revoke_url: str = REVOKE_URL,
           agent: str = "DentPilot") -> Reply:
    """Отзыв у Google. Токен, которого Google уже не знает, — INVALID_GRANT: связь и так мертва,
    и для «Deconectează» это тот же успех."""
    return _post(revoke_url, {"token": token}, "", timeout, agent, grant=False)


def _check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if not (u.scheme == "https" and u.hostname) and not (u.scheme == "http" and u.hostname == "127.0.0.1"):
        raise ValueError("url")


def _json(raw: bytes) -> dict:
    if len(raw) > MAX_BODY:
        return {}
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _post(url: str, form: dict, secret: str, timeout: float, agent: str, *, grant: bool) -> Reply:
    """Один запрос формой. Возвращает Reply и не бросает (кроме ValueError на адрес не https)."""
    _check_url(url)
    if secret:
        form = {**form, "client_secret": secret}
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode("ascii"), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json", "User-Agent": agent})
    try:
        with _opener.open(req, timeout=timeout) as r:
            status, raw = r.status, r.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        try:
            body = _json(e.read(MAX_BODY + 1))
        except (OSError, http.client.HTTPException):
            body = {}
        return _failure(e.code, body)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return Reply(OFFLINE)
    if status != 200:
        return Reply(OFFLINE, status=status)
    if not grant:
        return Reply(OK, status=status)
    body = _json(raw)
    access, ttl, kind = body.get("access_token"), body.get("expires_in"), body.get("token_type")
    if (not isinstance(access, str) or not access or isinstance(ttl, bool) or not isinstance(ttl, int)
            or ttl <= 0 or not isinstance(kind, str) or kind.lower() != "bearer"):
        return Reply(OFFLINE, status=status, reason="bad_body")
    ref, scope = body.get("refresh_token"), body.get("scope")
    return Reply(OK, Grant(access=access, expires_in=ttl, refresh=ref if isinstance(ref, str) else "",
                           scopes=frozenset(scope.split()) if isinstance(scope, str) else frozenset()),
                 status=status)


def _failure(status: int, body: dict) -> Reply:
    err = body.get("error")
    err = err if isinstance(err, str) else ""
    if status == 429:
        code = RATE_LIMITED
    elif status >= 500 or status < 400:
        code = OFFLINE
    elif err in ("invalid_grant", "invalid_token"):
        code = INVALID_GRANT
    elif err in ("invalid_client", "unauthorized_client") or status == 401:
        code = INVALID_CLIENT
    elif err == "admin_policy_enforced":
        code = ADMIN_POLICY
    else:
        code = BAD_REQUEST
    return Reply(code, status=status, reason=err[:64])
