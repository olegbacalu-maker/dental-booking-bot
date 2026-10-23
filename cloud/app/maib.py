"""maib e-commerce (L12): hosted-страница оплаты картой, callback, статус, возврат.

Контракт — cloud.md › «Оплата › Шаг 2 — maib». Здесь только провод к maib:
токен, создать платёж, спросить статус, вернуть деньги, проверить подпись
callback. Что делать с ответом — payments.settle: там правило одно на callback,
кнопку «Проверить» и ежедневную задачу.

Сверено 23.10.2026 с документацией maib e-Commerce API v1
(docs.maibmerchants.md/e-commerce; у каждой страницы есть .md-версия) и с
официальным PHP SDK (github.com/maib-ecomm/maib-sdk-php):
`POST /generate-token` (projectId, projectSecret → accessToken, expiresIn),
`POST /pay` (amount, currency, clientIp, language, description, email, orderId,
callbackUrl, okUrl, failUrl → payId, payUrl), `GET /pay-info/{payId}` (status,
statusCode, statusMessage, amount…), `POST /refund` (payId, refundAmount →
status OK или REVERSED), callback POST-ом `{"result": {…}, "signature": "…"}`;
подпись — `signature()`, дословно по примеру maib. Тестовый проект ходит на тот
же адрес, что боевой, со своими ключами; запрос не с IP проекта — 403.
⚠️ Видно только живым платежом в тестовом проекте: как maib пишет в callback
целую сумму (400 или 400.00 — от этого подпись), принимает ли IPv6 длиннее 15
знаков, каким статусом pay-info говорит о возвращённом платеже. Ошибка здесь
не пропускает чужие деньги — callback только сигнал, а истина о платеже
спрашивается у maib отдельно.

⛔ Mock-провайдера здесь нет и не будет: тесты поднимают свой сервер и
подставляют его адрес через DP_MAIB_BASE_URL. Прод знает один адрес — maib.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("cloud.maib")

TIMEOUT = 15.0
CALLBACK_PATH = "/v1/maib/callback"     # maib зовёт сюда после оплаты
OK_PATH, FAIL_PATH = "/pay/ok", "/pay/fail"   # куда maib возвращает браузер клиники (?payId=…&orderId=…)
STATUS_OK = "OK"                        # единственный статус, который значит «оплачено»
WAITING = ("CREATED", "PENDING")        # платёж ещё идёт; FAILED, DECLINED, TIMEOUT — не прошёл
PAY_TTL = 10 * 60                       # ⚠️ payUrl живёт 10 минут от ответа /pay, потом платёж TIMEOUT
REFUNDED = ("OK", "REVERSED")           # ответ /refund: вернули сейчас / уже были возвращены раньше
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class MaibError(RuntimeError):
    """maib не ответил или ответил не то. Текст — для лога и ?msg=, без секретов;
    `http` — код ответа maib (0 — до ответа не дошло)."""

    def __init__(self, text: str, http: int = 0):
        super().__init__(text)
        self.http = http


def enabled() -> bool:
    return bool(config.MAIB_PROJECT_ID and config.MAIB_PROJECT_SECRET and config.MAIB_SIGNATURE_KEY)


# ---------- провод ----------


def _errors(payload) -> str:
    """errors maib → «код текст; …» — то, что их поддержка просит прислать вместе с HTTP-кодом."""
    if isinstance(payload, dict):
        errs = payload.get("errors")
        if isinstance(errs, list) and errs:
            return "; ".join(" ".join(str(x) for x in (e.get("errorCode"), e.get("errorMessage")) if x) or str(e)
                             if isinstance(e, dict) else str(e) for e in errs)[:200]
    return "ответ без result"


def _call(method: str, path: str, body: dict | None = None, bearer: str = "") -> dict:
    """Запрос к maib; их ответ {"ok": true, "result": {…}} → result, иначе MaibError.
    Без тела — без Content-Type: pay-info с ним maib не принимает."""
    url = config.MAIB_BASE_URL.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            payload = {}
        hint = " (запрос не с IP проекта в maibmerchants)" if e.code == 403 else ""
        raise MaibError(f"{method} {path}: HTTP {e.code}{hint}, {_errors(payload)}", e.code) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MaibError(f"{method} {path}: {e.__class__.__name__}: {e}") from None
    if not isinstance(payload, dict) or not payload.get("ok") or not isinstance(payload.get("result"), dict):
        raise MaibError(f"{method} {path}: {_errors(payload)}")
    return payload["result"]


_token = {"value": "", "until": 0.0}


def token() -> str:
    """accessToken проекта; живёт expiresIn секунд, берётся заново за полминуты до конца.
    Refresh Token не нужен: документация разрешает снова спросить по projectId/projectSecret."""
    if _token["value"] and time.time() < _token["until"]:
        return _token["value"]
    r = _call("POST", "/generate-token", {"projectId": config.MAIB_PROJECT_ID,
                                          "projectSecret": config.MAIB_PROJECT_SECRET})
    value = r.get("accessToken")
    if not isinstance(value, str) or not value:
        raise MaibError("generate-token: в ответе нет accessToken")
    try:
        ttl = int(r.get("expiresIn", 300))
    except (TypeError, ValueError):
        ttl = 300
    _token.update(value=value, until=time.time() + max(30, ttl - 30))
    return value


def _authed(method: str, path: str, body: dict | None = None) -> dict:
    """Запрос с токеном. 401 — maib отозвал токен раньше срока: один раз берётся новый."""
    bearer = token()
    try:
        return _call(method, path, body, bearer=bearer)
    except MaibError as e:
        if e.http != 401:
            raise
    _token.update(value="", until=0.0)
    return _call(method, path, body, bearer=token())


def _cut(text: str, limit: int) -> str:
    """Не длиннее `limit` байт UTF-8 и без разрезанной буквы: SDK maib меряет поля
    strlen, то есть байтами, а «ă» — два байта."""
    return text.encode("utf-8")[:limit].decode("utf-8", "ignore")


def _client_ip(value: str) -> str:
    """clientIp обязателен, string(15): IPv4 как есть, IPv4 в обёртке IPv6 — его IPv4.
    Длинный IPv6, «?» и пусто — 127.0.0.1: иначе maib отказал бы платежу целиком."""
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return "127.0.0.1"
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip) if len(str(ip)) <= 15 else "127.0.0.1"


def create(amount: int, order_id: str, description: str, email: str = "",
           client_ip: str = "127.0.0.1") -> tuple[str, str]:
    """Платёж у maib → (payId, адрес hosted-страницы). orderId — наш reference.
    ⚠️ Адрес живёт PAY_TTL: дальше он ведёт на мёртвый платёж (TIMEOUT)."""
    base = config.BASE_URL.rstrip("/")
    body = {"amount": float(amount), "currency": "MDL", "clientIp": _client_ip(client_ip),
            "language": "ro", "description": _cut(description, 124), "orderId": _cut(order_id, 36),
            "callbackUrl": base + CALLBACK_PATH, "okUrl": base + OK_PATH, "failUrl": base + FAIL_PATH}
    email = (email or "").strip()
    if len(email) <= 40 and _EMAIL.fullmatch(email):
        body["email"] = email       # необязательное string(40): кривой адрес отказал бы платежу целиком
    r = _authed("POST", "/pay", body)
    pay_id, pay_url = r.get("payId"), r.get("payUrl")
    if not (isinstance(pay_id, str) and pay_id and isinstance(pay_url, str)
            and pay_url.startswith("https://")):
        raise MaibError("pay: в ответе нет payId или payUrl")
    return pay_id, pay_url


def info(pay_id: str) -> dict:
    """Статус платежа у maib — источник истины (инвариант 2)."""
    return _authed("GET", "/pay-info/" + urllib.parse.quote(pay_id, safe=""))


def refund(pay_id: str, amount: int | None = None) -> dict:
    """Вернуть деньги по платежу → result maib (status OK — вернули, REVERSED — уже
    были возвращены). Возврат у maib один на платёж: полный (amount=None) или
    частичный; остаток после частичного — только через ecom@maib.md. Наш учёт
    (срок, нота) — не здесь: провод только просит банк."""
    body: dict = {"payId": pay_id}
    if amount is not None:
        body["refundAmount"] = float(amount)
    r = _authed("POST", "/refund", body)
    status = str(r.get("status") or "").upper()
    if status not in REFUNDED:
        raise MaibError(f"refund: {status or 'без статуса'} {r.get('statusCode') or ''} "
                        f"{r.get('statusMessage') or ''}".strip())
    return r


# ---------- подпись callback ----------


def _as_text(v) -> str:
    """(string)$item примера maib на PHP: true → 1, false и null → пусто, целое
    число без дробной части (400.0 → 400), дробное — как есть (10.25)."""
    if v is None or v is False:
        return ""
    if v is True:
        return "1"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def _sorted(v) -> list:
    """sortByKeyRecursive: значения по ключам, ksort SORT_STRING — и у списка, чьи
    индексы PHP сравнивает строками («10» раньше «2»)."""
    if isinstance(v, dict):
        return [v[k] for k in sorted(v, key=str)]
    return [v[i] for i in sorted(range(len(v)), key=str)]


def _implode(items: list) -> str:
    """implodeRecursive(':'): значения через «:», вложенный объект или список — тем же правилом."""
    return ":".join(_implode(_sorted(x)) if isinstance(x, (dict, list)) else _as_text(x) for x in items)


def signature(result: dict, key: str) -> str:
    """Base64(sha256(Implode(Sort(Params) + SignatureKey, ':'))) — «Notifications on
    Callback Url» › «Callback signature»: значения result по алфавиту ключей, в
    конце Signature Key, всё через «:»; sha256 в байтах, не в hex."""
    raw = _implode(_sorted(result) + [key])
    return base64.b64encode(hashlib.sha256(raw.encode("utf-8")).digest()).decode("ascii")


def signed(payload) -> dict | None:
    """Тело callback → result, если подпись сошлась; None — битый или чужой ключ."""
    if (not isinstance(payload, dict) or not isinstance(payload.get("result"), dict)
            or not isinstance(payload.get("signature"), str) or not config.MAIB_SIGNATURE_KEY):
        return None
    result = payload["result"]
    if not hmac.compare_digest(signature(result, config.MAIB_SIGNATURE_KEY).encode("ascii"),
                               payload["signature"].encode("utf-8")):
        # ключи и сумма — чтобы в песочнице было видно, чем строка maib отличается от нашей
        log.warning("maib: подпись не сошлась; поля %s, amount=%r", ",".join(sorted(result)), result.get("amount"))
        return None
    return result
