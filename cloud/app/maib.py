"""maib e-commerce (L12): hosted-страница оплаты картой, callback, статус.

Контракт — cloud.md › «Оплата › Шаг 2 — maib». Здесь только провод к maib:
токен, создать платёж, спросить статус, проверить подпись callback. Что
делать с ответом — payments.settle: там правило одно на callback, кнопку
«Проверить» и ежедневную задачу.

Имена методов и полей — по документации maib ecommerce API v2
(docs.maibmerchants.md) в том виде, в каком она известна на 25.09:
`POST /generate-token` (projectId, projectSecret → accessToken, expiresIn),
`POST /pay` (amount, currency, clientIp, orderId, callbackUrl, okUrl, failUrl
→ payId, payUrl), `GET /pay-info/{payId}` (status, statusCode, statusMessage…),
callback POST-ом `{"result": {…}, "signature": "…"}`, подпись —
base64(sha256(значения result по алфавиту ключей через «:» + «:» + signatureKey)).
⚠️ Сверить с песочницей maib до боевого включения: имена, формат суммы в
подписи, набор статусов. Ошибка здесь не пропускает чужие деньги — callback
только сигнал, а истина о платеже спрашивается у maib отдельно.

⛔ Mock-провайдера здесь нет и не будет: тесты поднимают свой сервер и
подставляют его адрес через DP_MAIB_BASE_URL. Прод знает один адрес — maib.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("cloud.maib")

TIMEOUT = 15.0
CALLBACK_PATH = "/v1/maib/callback"     # maib зовёт сюда после оплаты
OK_PATH, FAIL_PATH = "/pay/ok", "/pay/fail"   # куда maib возвращает браузер клиники
STATUS_OK = "OK"                        # единственный статус, который значит «оплачено»
WAITING = ("CREATED", "PENDING")        # платёж ещё идёт; всё остальное — не прошёл


class MaibError(RuntimeError):
    """maib не ответил или ответил не то. Текст — для лога и ?msg=, без секретов."""


def enabled() -> bool:
    return bool(config.MAIB_PROJECT_ID and config.MAIB_PROJECT_SECRET and config.MAIB_SIGNATURE_KEY)


# ---------- провод ----------


def _errors(payload) -> str:
    if isinstance(payload, dict):
        errs = payload.get("errors")
        if isinstance(errs, list) and errs:
            return "; ".join(str(e.get("errorMessage") or e.get("errorCode") or e)
                             if isinstance(e, dict) else str(e) for e in errs)[:200]
    return "ответ без result"


def _call(method: str, path: str, body: dict | None = None, bearer: str = "") -> dict:
    """Запрос к maib; их ответ {"ok": true, "result": {…}} → result, иначе MaibError."""
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
        raise MaibError(f"{method} {path}: HTTP {e.code}, {_errors(payload)}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MaibError(f"{method} {path}: {e.__class__.__name__}: {e}") from None
    if not isinstance(payload, dict) or not payload.get("ok") or not isinstance(payload.get("result"), dict):
        raise MaibError(f"{method} {path}: {_errors(payload)}")
    return payload["result"]


_token = {"value": "", "until": 0.0}


def token() -> str:
    """accessToken проекта; живёт expiresIn секунд, берётся заново за полминуты до конца."""
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


def create(amount: int, order_id: str, description: str, email: str = "",
           client_ip: str = "127.0.0.1") -> tuple[str, str]:
    """Платёж у maib → (payId, адрес hosted-страницы). orderId — наш reference."""
    base = config.BASE_URL.rstrip("/")
    body = {"amount": float(amount), "currency": "MDL", "clientIp": client_ip or "127.0.0.1",
            "language": "ro", "description": description[:124], "orderId": order_id[:36],
            "callbackUrl": base + CALLBACK_PATH, "okUrl": base + OK_PATH, "failUrl": base + FAIL_PATH}
    if email:
        body["email"] = email
    r = _call("POST", "/pay", body, bearer=token())
    pay_id, pay_url = r.get("payId"), r.get("payUrl")
    if not (isinstance(pay_id, str) and pay_id and isinstance(pay_url, str)
            and pay_url.startswith("https://")):
        raise MaibError("pay: в ответе нет payId или payUrl")
    return pay_id, pay_url


def info(pay_id: str) -> dict:
    """Статус платежа у maib — источник истины (инвариант 2)."""
    return _call("GET", f"/pay-info/{pay_id}", bearer=token())


# ---------- подпись callback ----------


def _as_text(v) -> str:
    """Значение поля так, как его склеил бы пример maib на PHP: true → 1, false и
    null → пусто, целое число без дробной части, дробное — как есть."""
    if v is None or v is False:
        return ""
    if v is True:
        return "1"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def signature(result: dict) -> str:
    """base64(sha256(значения result по алфавиту ключей через «:» + «:» + signatureKey))."""
    raw = ":".join(_as_text(result[k]) for k in sorted(result)) + ":" + config.MAIB_SIGNATURE_KEY
    return base64.b64encode(hashlib.sha256(raw.encode("utf-8")).digest()).decode("ascii")


def signed(payload) -> dict | None:
    """Тело callback → result, если подпись сошлась; None — битый или чужой ключ."""
    if (not isinstance(payload, dict) or not isinstance(payload.get("result"), dict)
            or not isinstance(payload.get("signature"), str) or not config.MAIB_SIGNATURE_KEY):
        return None
    if not hmac.compare_digest(signature(payload["result"]), payload["signature"]):
        return None
    return payload["result"]
