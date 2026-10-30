"""maib e-Commerce Checkout (L12): hosted-страница оплаты, callback, статус, возврат.

Контракт — cloud.md › «Оплата › Шаг 2 — maib». Здесь только провод к maib:
токен, создать checkout, спросить статус, вернуть деньги, проверить подпись
callback. Что делать с ответом — payments.settle: там правило одно на callback,
кнопку «Проверить» и ежедневную задачу.

Сверено 30.10.2026 с документацией maib Checkout API v2
(docs.maibmerchants.md/checkout; у каждой страницы есть .md-версия, плюс их
OpenAPI checkout-swagger.json и коллекция Postman; копии —
D:\\DentProject\\sandbox\\maib-checkout\\docs):
`POST /v2/auth/token` (clientId, clientSecret → accessToken, expiresIn, tokenType),
`POST /v2/checkouts` (amount, currency, language, orderInfo{id, description ≤125},
payerInfo{email, ip}, callbackUrl, successUrl, failUrl → checkoutId, checkoutUrl),
`GET /v2/checkouts/{id}` (status, payment{paymentId, status, amount, refundedAmount…}),
`GET /v2/payments/{id}`, `POST /v2/payments/{payId}/refund` (amount, reason →
refundId, status Created), `GET /v2/payments/refunds/{id}`. Callback — POST с
плоским JSON (checkoutId, paymentId, paymentStatus…) и подписью в заголовках
`X-Signature: sha256=<base64>` / `X-Signature-Timestamp` (мс):
HMAC-SHA256(SignatureKey, «сырое тело.метка»), образец документации сходится
байт в байт. Песочница — https://sandbox.maibmerchants.md, боевой —
https://api.maibmerchants.md; пути и тела одинаковы, ключи разные.

⭐ Наш «payId» (payments.provider_id, pay_attempts, `result["payId"]` для
payments.settle) — это checkoutId: его даёт создание, по нему спрашивается
статус, его приносят callback и возврат браузера. paymentId банка (нужен
только возврату денег) провод достаёт из checkout сам. Ответ Checkout провод
переводит в прежние слова (`info()`): OK — оплачено, CREATED/PENDING — ждём,
TIMEOUT — ссылка протухла, прочее — не прошёл; поэтому payments.settle не
знает, какой у maib API.
⚠️ Видно только живым платежом: сколько живёт ссылка (PAY_TTL — по примеру
документации), чем Checkout кодирует подпись на деле (документация допускает
hex или Base64 — принимаем оба), секунды или миллисекунды в метке, каким
статусом checkout говорит о возвращённом платеже. Ошибка здесь не пропускает
чужие деньги — callback только сигнал, а истина о платеже спрашивается у maib
отдельно.

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
OK_PATH, FAIL_PATH = "/pay/ok", "/pay/fail"   # куда maib возвращает браузер (?checkoutId=…&checkoutStatus=…&orderId=…)
STATUS_OK = "OK"                        # единственный наш статус, который значит «оплачено»
WAITING = ("CREATED", "PENDING")        # платёж ещё идёт; FAILED, CANCELLED, TIMEOUT — не прошёл
PAY_TTL = 25 * 60                       # ⚠️ checkout живёт expiresAt − createdAt: 25 минут в примере документации
SIGNATURE_SKEW = 10 * 60                # секунд: метка callback дальше от наших часов — повтор чужого, не принимать
REFUNDED = ("Created", "Requested", "Accepted")   # возврат принят банком; Rejected, Manual — нет
DESCRIPTION_MAX = 125                   # orderInfo.description, знаков
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# Статус checkout → наш (payments.settle). Completed — только вместе со статусом платежа.
_WAIT = {"WaitingForInit": "CREATED", "Initialized": "PENDING", "PaymentMethodSelected": "PENDING"}
_GONE = {"Expired": "TIMEOUT", "Abandoned": "TIMEOUT", "Cancelled": "CANCELLED", "Failed": "FAILED"}
_PAID = ("Executed", "PartiallyRefunded")       # деньги у нас (частичный возврат — не повод отнять срок)


class MaibError(RuntimeError):
    """maib не ответил или ответил не то. Текст — для лога и ?msg=, без секретов;
    `http` — код ответа maib (0 — до ответа не дошло)."""

    def __init__(self, text: str, http: int = 0):
        super().__init__(text)
        self.http = http


def enabled() -> bool:
    return bool(config.MAIB_CLIENT_ID and config.MAIB_CLIENT_SECRET and config.MAIB_SIGNATURE_KEY)


# ---------- провод ----------


def _errors(payload) -> str:
    """errors maib → «код текст; …» — то, что их поддержка просит прислать вместе с HTTP-кодом."""
    if isinstance(payload, dict):
        errs = payload.get("errors")
        if isinstance(errs, list) and errs:
            return "; ".join(" ".join(str(x) for x in (e.get("errorCode"), e.get("errorMessage")) if x) or str(e)
                             if isinstance(e, dict) else str(e) for e in errs)[:200]
    return "ответ без result"


def _call(method: str, path: str, body: dict | None = None, auth: str = "") -> dict:
    """Запрос к maib; их ответ {"ok": true, "result": {…}} → result, иначе MaibError.
    Без тела — без Content-Type (так GET-ы в их коллекции Postman)."""
    url = config.MAIB_BASE_URL.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if auth:
        headers["Authorization"] = auth
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
        hint = " (доступ закрыт: IP сервера или ключи проекта в maibmerchants)" if e.code == 403 else ""
        raise MaibError(f"{method} {path}: HTTP {e.code}{hint}, {_errors(payload)}", e.code) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MaibError(f"{method} {path}: {e.__class__.__name__}: {e}") from None
    if not isinstance(payload, dict) or not payload.get("ok") or not isinstance(payload.get("result"), dict):
        raise MaibError(f"{method} {path}: {_errors(payload)}")
    return payload["result"]


_token = {"value": "", "until": 0.0}


def token() -> str:
    """«{tokenType} {accessToken}» для Authorization; живёт expiresIn секунд, берётся
    заново за полминуты до конца (refresh у Checkout нет: снова clientId/clientSecret)."""
    if _token["value"] and time.time() < _token["until"]:
        return _token["value"]
    r = _call("POST", "/v2/auth/token", {"clientId": config.MAIB_CLIENT_ID,
                                         "clientSecret": config.MAIB_CLIENT_SECRET})
    value = r.get("accessToken")
    if not isinstance(value, str) or not value:
        raise MaibError("auth/token: в ответе нет accessToken")
    try:
        ttl = int(r.get("expiresIn", 300))
    except (TypeError, ValueError):
        ttl = 300
    kind = r.get("tokenType") if isinstance(r.get("tokenType"), str) and r.get("tokenType") else "Bearer"
    _token.update(value=f"{kind} {value}", until=time.time() + max(30, ttl - 30))
    return _token["value"]


def _authed(method: str, path: str, body: dict | None = None) -> dict:
    """Запрос с токеном. 401 — maib отозвал токен раньше срока: один раз берётся новый."""
    auth = token()
    try:
        return _call(method, path, body, auth=auth)
    except MaibError as e:
        if e.http != 401:
            raise
    _token.update(value="", until=0.0)
    return _call(method, path, body, auth=token())


def _id(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _payer_ip(value: str) -> str:
    """payerInfo.ip: IPv4 или IPv6 как есть (callback Checkout несёт оба), IPv4 в обёртке
    IPv6 — его IPv4; «?» и пусто — поле не передаётся (оно необязательное)."""
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return ""
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return "" if ip.is_loopback else str(ip)


def create(amount: int, order_id: str, description: str, email: str = "",
           client_ip: str = "") -> tuple[str, str]:
    """Checkout у maib → (checkoutId, адрес hosted-страницы). orderInfo.id — наш reference.
    ⚠️ Адрес живёт PAY_TTL: дальше checkout Expired."""
    base = config.BASE_URL.rstrip("/")
    body: dict = {"amount": float(amount), "currency": "MDL", "language": "ro",
                  "orderInfo": {"id": order_id, "description": description[:DESCRIPTION_MAX]},
                  "callbackUrl": base + CALLBACK_PATH, "successUrl": base + OK_PATH, "failUrl": base + FAIL_PATH}
    payer = {}
    email = (email or "").strip()
    if _EMAIL.fullmatch(email):
        payer["email"] = email      # необязательное: кривой адрес отказал бы checkout целиком (42005)
    ip = _payer_ip(client_ip)
    if ip:
        payer["ip"] = ip
    if payer:
        body["payerInfo"] = payer
    r = _authed("POST", "/v2/checkouts", body)
    cid, url = r.get("checkoutId"), r.get("checkoutUrl")
    if not (isinstance(cid, str) and cid and isinstance(url, str) and url.startswith("https://")):
        raise MaibError("checkouts: в ответе нет checkoutId или checkoutUrl")
    return cid, url


def checkout(checkout_id: str) -> dict:
    """Checkout как его отдаёт maib (`GET /v2/checkouts/{id}`), без перевода."""
    return _authed("GET", "/v2/checkouts/" + _id(checkout_id))


def _payment_of(c: dict) -> dict:
    p = c.get("payment")
    return p if isinstance(p, dict) else {}


def _payment_id(p: dict) -> str:
    """paymentId (так в примере ответа; в таблице той же страницы — PaymentId)."""
    v = p.get("paymentId") or p.get("PaymentId")
    return v if isinstance(v, str) else ""


def ours(c: dict) -> dict:
    """Checkout → ответ в словах payments.settle: payId (= checkoutId), status (OK /
    CREATED / PENDING / TIMEOUT / CANCELLED / FAILED / REFUNDED), statusCode — слова
    maib «статус checkout/статус платежа», statusMessage — способ оплаты. Незнакомый
    статус — ждём (спросим ещё раз), а не «не прошёл»: так новое слово maib не
    закроет попытку, по которой деньги ещё могут прийти."""
    st = str(c.get("status") or "")
    p = _payment_of(c)
    pst = str(p.get("status") or "")
    if st == "Completed" and pst in _PAID:
        status = STATUS_OK
    elif st == "Completed" and pst == "Refunded":
        status = "REFUNDED"
    elif st == "Completed" and pst == "Failed":
        status = "FAILED"
    elif st in _GONE:
        status = _GONE[st]
    elif st in _WAIT:
        status = _WAIT[st]
    else:
        if st != "Completed":
            log.warning("maib: незнакомый статус checkout %r — считаю ожиданием", st)
        status = "PENDING"
    return {"payId": c.get("id"), "status": status, "statusCode": "/".join(x for x in (st, pst) if x),
            "statusMessage": str(p.get("paymentMethod") or ""), "paymentId": _payment_id(p),
            "amount": p.get("amount", c.get("amount")), "currency": c.get("currency"),
            "refundedAmount": p.get("refundedAmount"), "expiresAt": c.get("expiresAt")}


def info(checkout_id: str) -> dict:
    """Статус у maib — источник истины (инвариант 2), в словах payments.settle (`ours`)."""
    c = checkout(checkout_id)
    if not c.get("id"):
        c = dict(c, id=checkout_id)
    return ours(c)


def payment(payment_id: str) -> dict:
    """Платёж банка (`GET /v2/payments/{id}`): status Executed / PartiallyRefunded /
    Refunded / Failed, refundableAmount, isRefundable."""
    return _authed("GET", "/v2/payments/" + _id(payment_id))


def refund(checkout_id: str, amount: int | float | None = None,
           reason: str = "Returnare la cererea clientului") -> dict:
    """Вернуть деньги по оплаченному checkout → result maib (refundId, status Created) и
    paymentId. amount=None — всё, что ещё можно вернуть (refundableAmount платежа).
    Наш учёт (срок, нота) — не здесь: провод только просит банк."""
    p = _payment_of(checkout(checkout_id))
    pid = _payment_id(p)
    if not pid:
        raise MaibError("refund: у checkout нет платежа")
    if amount is None:
        bank = payment(pid)
        if bank.get("isRefundable") is False:
            raise MaibError(f"refund: платёж {pid} возврату не подлежит ({bank.get('status')})")
        amount = bank.get("refundableAmount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise MaibError(f"refund: вернуть нечего ({bank.get('status')}, refundableAmount={amount!r})")
    r = _authed("POST", f"/v2/payments/{_id(pid)}/refund", {"amount": float(amount), "reason": reason[:500]})
    status = str(r.get("status") or "")
    if status not in REFUNDED:
        raise MaibError(f"refund: {status or 'без статуса'}")
    return dict(r, paymentId=pid)


def refund_info(refund_id: str) -> dict:
    """Возврат по его id (`GET /v2/payments/refunds/{id}`): status Created / Requested /
    Accepted / Rejected / Manual."""
    return _authed("GET", "/v2/payments/refunds/" + _id(refund_id))


# ---------- подпись callback ----------


def signature(raw: bytes, timestamp: str, key: str) -> bytes:
    """HMAC_SHA256(secretKey, rawBody.timestamp) — «Callback Notifications» › «Signing
    Algorithm»: сырые байты тела как пришли, точка, метка из X-Signature-Timestamp."""
    return hmac.new(key.encode("utf-8"), raw + b"." + timestamp.encode("ascii"), hashlib.sha256).digest()


def verify(raw: bytes, header: str, timestamp: str, now: float | None = None) -> bool:
    """Подпись callback сошлась и метка свежая. `header` — X-Signature («sha256=…»),
    `timestamp` — X-Signature-Timestamp (мс; секунды тоже понимаем). Сравнение —
    байтами и за постоянное время; документация допускает Base64 и hex — принимаем оба."""
    key = config.MAIB_SIGNATURE_KEY
    if not key or not isinstance(raw, bytes):
        return False
    sig = (header or "").strip()
    if sig[:7].lower() == "sha256=":
        sig = sig[7:]
    ts = (timestamp or "").strip()
    if not sig or not ts.isdigit() or not ts.isascii():
        log.warning("maib: callback без подписи или метки (X-Signature %s, метка %r)",
                    "есть" if sig else "нет", ts[:20])
        return False
    sent = int(ts) / (1000 if int(ts) > 10 ** 11 else 1)
    skew = (time.time() if now is None else now) - sent
    if abs(skew) > SIGNATURE_SKEW:
        log.warning("maib: метка callback не свежая (%+.0f с от наших часов)", skew)
        return False
    digest = signature(raw, ts, key)
    got = sig.encode("utf-8")
    if hmac.compare_digest(base64.b64encode(digest), got) or hmac.compare_digest(digest.hex().encode("ascii"),
                                                                                  got.lower()):
        return True
    # длина тела и подписи — чтобы в песочнице было видно, в чём расхождение (ключа в логе нет)
    log.warning("maib: подпись не сошлась; тело %d байт, подпись %d знаков, метка %s", len(raw), len(sig), ts)
    return False
