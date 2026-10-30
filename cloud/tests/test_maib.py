"""Оплата картой через maib Checkout (L12): ссылка, callback, статус, ежедневная задача.

maib здесь — СТЕНД в процессе теста (http.server), и это единственное место,
где он существует: прод знает один адрес, DP_MAIB_BASE_URL. Стенд говорит
теми же именами, что документация maib e-Commerce Checkout API v2 (auth/token,
checkouts, checkouts/{id}, payments/{id}, payments/{payId}/refund,
payments/refunds/{id}; callback с подписью в заголовках; сверено 30.10.2026,
копии страниц, OpenAPI и Postman — D:\\DentProject\\sandbox\\maib-checkout\\docs),
отказывает так же, как она описывает (поля checkout — 42005/42006, POST без
Content-Type — 415, отозванный токен — 401, IP — 403, возврат неоплаченного —
44002, неизвестный checkout — 43001), и подписывает callback построчной записью
ПРИМЕРА maib на PHP (`hash_hmac('sha256', $json . '.' . $timestamp, $key,
true)`), независимой от app/maib.py. Сам пример проверяется образцом из
документации (`DOC_*`) — так провод сервера держится документированной формы,
а не самого себя.

Исходы callback из cloud.md: успешный (продление, файл, письмо), повторный
(ничего), битый (400, ничего), чужой (404, ничего). И главный инвариант:
callback — только сигнал; оплачено лишь то, про что сам maib (статус checkout)
сказал Completed с исполненным платежом.
"""
import base64
import email
import email.policy
import hashlib
import hmac
import http.server
import json
import logging
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from harness import CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path

sys.path.insert(0, str(CLOUD))
from app import mail  # noqa: E402 — константы писем
from app import payments as pay  # noqa: E402 — правило продления
from app import config  # noqa: E402 — прайс
from app import maib  # noqa: E402 — провод, его наборы зовут прямо (suite_wire)

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}
CLIENT, SECRET, SIGKEY = "749c564f-1a65-48e3-a4bf-b7932b6ae3db", "secret-test", "signature-key-test"
CALLBACK = "/v1/maib/callback"
HOST = "https://checkout.maib.md/"      # вид checkoutUrl из примера «Get checkout details»
D = timedelta(days=1)


# Образец из документации: «Callback Notifications» › «Signature Example»
# (docs.maibmerchants.md/checkout/api-reference/callback-notifications.md, 30.10.2026).
# Тело — ровно как там: пробелы после двоеточий и «50.00» — повторная сериализация
# (json.dumps) дала бы другие байты, поэтому подпись считается над сырым телом.
DOC_BODY = (
    '{"checkoutId": "5a4d27a4-79f5-426b-9403-cccdeee81747","terminalId": "T1234567","amount": 1234.56,'
    '"currency": "MDL","completedAt": "2024-11-23T19:35:00.6772285+02:00","payerName": "John",'
    '"payerEmail": "Smith","payerPhone": "37368473653","payerIp": "192.175.12.22","orderId": "ORDER-2025-0001",'
    '"orderDescription": "Online purchase of electronics","orderDeliveryAmount": 50.00,'
    '"orderDeliveryCurrency": "MDL","paymentId": "379b31a3-8283-43d4-8a7b-eef8c0736a32","paymentAmount": 1234.56,'
    '"paymentCurrency": "MDL","paymentStatus": "Executed","paymentExecutedAt": "2025-05-05T23:38:07.2760698+03:00",'
    '"senderIban": "NL43RABO1438227787","senderName": "Steven","senderCardNumber": "444433******1111",'
    '"retrievalReferenceNumber": "ABC324353245","processingStatus": "OK","processingStatusCode": "00",'
    '"approvalCode": "123456","threeDsResult": "Y","threeDsReason": null,"paymentMethod": "Card"}').encode("utf-8")
DOC_TS = "1761032516817"
DOC_KEY = "67be8e54-ac28-485d-9369-27f6d3c55a27"
DOC_SIGNATURE = "mtFkCMxfwj9t2wvY/7JASHLw+K/du4mY8azf1lV0ttg="


def _php_sign(json_message: bytes, timestamp: str, key: str) -> str:
    """Пример maib на PHP («Signature Key Verification»), построчно и независимо от
    app/maib.py: $message = $jsonMessage . '.' . $timestamp;
    base64_encode(hash_hmac('sha256', $message, $signatureKey, true))."""
    message = json_message + b"." + timestamp.encode("ascii")
    computed_hash = hmac.new(key.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(computed_hash).decode("ascii")


def _err(http: int, code: str, message: str, **args) -> tuple[int, dict]:
    """Отказ maib — «API Errors» › Error Format."""
    e = {"errorCode": f"maib.merchant.payments-{code}", "errorMessage": message}
    if args:
        e["errorArgs"] = args
    return http, {"ok": False, "errors": [e]}


def _checkout_error(body: dict) -> tuple[int, dict] | None:
    """Первое поле checkout, которое maib не принял бы по документации; None — всё по ней."""
    def number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    for name in ("amount", "currency"):
        if name not in body:
            return _err(400, "42006", "A required field is missing.", field=name)
    if not number(body["amount"]) or body["amount"] <= 1:
        return _err(400, "42001", "Amount must be greater than zero.")
    if body["currency"] != "MDL":
        return _err(400, "42000", "The selected currency is invalid. Please review and try again.")
    if body.get("language", "ro") not in ("ro", "ru", "en"):
        return _err(400, "42004", "Language is not supported. Supported languages: RO, RU, EN.")
    order = body.get("orderInfo") or {}
    payer = body.get("payerInfo") or {}
    bad = next((f for f, good in (
        ("orderInfo.description", not isinstance(order.get("description"), str) or len(order["description"]) <= 125),
        ("payerInfo.email", "email" not in payer or "@" in str(payer["email"])),
        *((u, isinstance(body.get(u), str) and body[u].startswith("https://") and len(body[u]) <= 1000)
          for u in ("callbackUrl", "successUrl", "failUrl"))) if not good), "")
    return _err(400, "42005", "Field has invalid format.", field=bad) if bad else None


class _Records(logging.Handler):
    """Строки лога провода, когда он исполняется в самом прогоне (suite_wire)."""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds")


class FakeMaib:
    """Стенд maib Checkout: токен по clientId/clientSecret, checkout с checkoutUrl, статус,
    который ставит тест, платёж банка, возврат. `rotate()` отзывает выданный токен,
    `forbid` — запрос не с IP проекта. Счётчики `calls` по-старому: pay — создание
    checkout, info — его статус."""

    def __init__(self):
        self.calls = {"token": 0, "pay": 0, "info": 0, "refund": 0}
        self.pays: dict[str, dict] = {}         # checkoutId → {"body", "status", "payment"}
        self.refunds: dict[str, dict] = {}
        self.bodies: list[dict] = []
        self.heads: list[tuple[str, str, dict]] = []    # (метод, путь, заголовки) каждого запроса
        self.token_value = "tok-" + uuid.uuid4().hex[:8]
        self.forbid = False
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _json(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _refused(self) -> bool:
                """403 не с IP проекта, 401 без живого токена — ответ уже отдан."""
                fake.heads.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}))
                if fake.forbid:
                    self._json(403, {"ok": False, "errors": [{"errorCode": "common.error-403",
                                                              "errorMessage": "Forbidden"}]})
                    return True
                if self.path != "/v2/auth/token" and \
                        self.headers.get("Authorization") != f"Bearer {fake.token_value}":
                    self._json(401, {"ok": False, "errors": [{"errorCode": "common.error-401",
                                                              "errorMessage": "Unauthorized"}]})
                    return True
                return False

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                if self._refused():
                    return
                if n and (self.headers.get("Content-Type") or "").split(";")[0] != "application/json":
                    return self._json(415, {"ok": False, "errors": [{"errorMessage": "Unsupported Media Type"}]})
                body = json.loads(raw or b"{}")
                path = self.path.rstrip("/")
                if path == "/v2/auth/token":
                    fake.calls["token"] += 1
                    if (body.get("clientId"), body.get("clientSecret")) != (CLIENT, SECRET):
                        return self._json(401, {"ok": False, "errors": [{
                            "errorCode": "common.error-401", "errorMessage": "Invalid client credentials"}]})
                    return self._json(200, {"ok": True, "result": {
                        "accessToken": fake.token_value, "expiresIn": 300, "tokenType": "Bearer"}})
                if path == "/v2/checkouts":
                    fake.calls["pay"] += 1
                    fake.bodies.append(body)
                    bad = _checkout_error(body)
                    if bad:
                        return self._json(*bad)
                    cid = str(uuid.uuid4())
                    fake.pays[cid] = {"body": body, "status": "WaitingForInit", "payment": None,
                                      "created": datetime.now(timezone.utc)}
                    return self._json(200, {"ok": True, "errors": None, "result": {
                        "checkoutId": cid, "checkoutUrl": HOST + cid.replace("-", "")}})
                if path.startswith("/v2/payments/") and path.endswith("/refund"):
                    fake.calls["refund"] += 1
                    pid = path.split("/")[3]
                    found = fake.by_payment(pid)
                    if found is None:
                        return self._json(*_err(404, "43001", "The specified checkout does not exist or has expired."))
                    for name in ("amount", "reason"):
                        if name not in body:
                            return self._json(*_err(400, "42006", "A required field is missing.", field=name))
                    p = found["payment"]
                    left = round(p["amount"] - p["refundedAmount"], 2)
                    if p["status"] not in ("Executed", "PartiallyRefunded") or left <= 0:
                        return self._json(*_err(409, "44002", "The current status does not permit the operation "
                                                              "to be processed."))
                    if not isinstance(body["amount"], (int, float)) or not 0 < body["amount"] <= left:
                        return self._json(*_err(400, "42002", "Amount must be greater than or equal to zero."))
                    rid = str(uuid.uuid4())
                    p["refundedAmount"] = round(p["refundedAmount"] + body["amount"], 2)
                    p["status"] = "Refunded" if p["refundedAmount"] >= p["amount"] else "PartiallyRefunded"
                    fake.refunds[rid] = {"id": rid, "paymentId": pid, "amount": body["amount"], "currency": "MDL",
                                         "refundType": "Full" if p["status"] == "Refunded" else "Partial",
                                         "refundReason": body["reason"], "status": "Created",
                                         "executedAt": _iso(datetime.now(timezone.utc))}
                    return self._json(200, {"ok": True, "result": {"refundId": rid, "status": "Created"}})
                self._json(404, {"ok": False, "errors": [{"errorMessage": "Not found"}]})

            def do_GET(self):
                if self._refused():
                    return
                path = self.path.rstrip("/")
                if path.startswith("/v2/checkouts/"):
                    fake.calls["info"] += 1
                    cid = path.rsplit("/", 1)[1]
                    if cid not in fake.pays:
                        return self._json(*_err(404, "43001", "The specified checkout does not exist or has expired."))
                    return self._json(200, {"ok": True, "errors": None, "result": fake.checkout(cid)})
                if path.startswith("/v2/payments/refunds/"):
                    r = fake.refunds.get(path.rsplit("/", 1)[1])
                    if r is None:
                        return self._json(*_err(404, "43001", "Not found"))
                    return self._json(200, {"ok": True, "errors": None, "result": r})
                if path.startswith("/v2/payments/"):
                    found = fake.by_payment(path.rsplit("/", 1)[1])
                    if found is None:
                        return self._json(*_err(404, "43001", "Not found"))
                    p = found["payment"]
                    left = round(p["amount"] - p["refundedAmount"], 2)
                    return self._json(200, {"ok": True, "result": dict(
                        p, isRefundable=p["status"] in ("Executed", "PartiallyRefunded") and left > 0,
                        partialRefundAvailable=True, paymentEntryPoint="Checkout", refundableAmount=left)})
                self._json(404, {"ok": False})

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def env(self) -> dict:
        return {"DP_MAIB_BASE_URL": self.url, "DP_MAIB_CLIENT_ID": CLIENT,
                "DP_MAIB_CLIENT_SECRET": SECRET, "DP_MAIB_SIGNATURE_KEY": SIGKEY}

    def by_payment(self, payment_id: str) -> dict | None:
        return next((c for c in self.pays.values() if c["payment"] and c["payment"]["paymentId"] == payment_id), None)

    def checkout(self, cid: str) -> dict:
        """«Get checkout details»: поля и вид из примера ответа документации."""
        c = self.pays[cid]
        b, created = c["body"], c["created"]
        order = b.get("orderInfo") or {}
        return {"id": cid, "createdAt": _iso(created), "status": c["status"], "amount": b["amount"],
                "callbackUrl": b.get("callbackUrl"), "successUrl": b.get("successUrl"), "failUrl": b.get("failUrl"),
                "currency": b["currency"], "language": b.get("language", "ro"), "url": HOST + cid.replace("-", ""),
                "order": {"id": order.get("id"), "description": order.get("description"), "amount": None,
                          "currency": None, "deliveryAmount": None, "deliveryCurrency": None, "date": None,
                          "orderItems": None},
                "payer": dict({"name": None, "email": None, "phone": None, "ip": None, "userAgent": None},
                              **(b.get("payerInfo") or {})),
                "completedAt": c["payment"]["executedAt"] if c["status"] == "Completed" and c["payment"] else None,
                "expiresAt": _iso(created + timedelta(minutes=25)), "payment": c["payment"]}

    def set_status(self, cid: str, status: str, payment: str = "Executed") -> None:
        """Статус checkout; Completed — с платежом банка (по умолчанию исполненным)."""
        c = self.pays[cid]
        c["status"] = status
        if status == "Completed" and c["payment"] is None:
            c["payment"] = {"paymentId": str(uuid.uuid4()), "executedAt": _iso(datetime.now(timezone.utc)),
                            "status": payment, "amount": c["body"]["amount"], "currency": "MDL", "type": "MMC",
                            "providerType": "MMC", "referenceNumber": "603616098154", "mcc": "4511",
                            "orderId": (c["body"].get("orderInfo") or {}).get("id"), "terminalId": "01E12345",
                            "refundedAmount": 0.0, "paymentMethod": "Card", "approvalCode": "929776",
                            "requestedRefundAmount": 0.0}
        elif c["payment"] is not None:
            c["payment"]["status"] = payment

    def rotate(self) -> None:
        """maib отозвал токен раньше expiresIn: старый получает 401, новый выдаст auth/token."""
        self.token_value = "tok-" + uuid.uuid4().hex[:8]

    def notification(self, cid: str) -> dict:
        """Что maib присылает на callback — «Notification Parameters» и пример уведомления."""
        c = self.checkout(cid)
        p = c["payment"] or {}
        payer = c["payer"]
        return {"checkoutId": cid, "terminalId": p.get("terminalId"), "amount": c["amount"],
                "currency": c["currency"], "completedAt": c["completedAt"], "payerName": payer["name"],
                "payerEmail": payer["email"], "payerPhone": payer["phone"], "payerIp": payer["ip"],
                "orderId": c["order"]["id"], "orderDescription": c["order"]["description"],
                "orderDeliveryAmount": None, "orderDeliveryCurrency": None, "paymentId": p.get("paymentId"),
                "paymentAmount": p.get("amount"), "paymentCurrency": p.get("currency"),
                "paymentStatus": p.get("status"), "paymentExecutedAt": p.get("executedAt"), "senderIban": None,
                "senderName": "Test Test", "senderCardNumber": "510218******1124",
                "retrievalReferenceNumber": p.get("referenceNumber"), "processingStatus": "OK",
                "processingStatusCode": "00", "approvalCode": p.get("approvalCode"), "threeDsResult": "Y",
                "threeDsReason": None, "paymentMethod": p.get("paymentMethod")}

    def callback(self, cid: str, key: str = SIGKEY, ts: str | None = None, **override) -> tuple[bytes, dict]:
        """(тело, заголовки) callback: компактный JSON как есть (буквы — UTF-8, не \\u), подпись
        по примеру maib на PHP над этими байтами и меткой в миллисекундах."""
        raw = json.dumps(dict(self.notification(cid), **override), separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
        ts = ts or str(int(time.time() * 1000))
        return raw, {"X-Signature": "sha256=" + _php_sign(raw, ts, key), "X-Signature-Timestamp": ts}

    def post(self, c: Client, cid: str, **kw):
        """maib стучится на callback сервера."""
        raw, heads = self.callback(cid, **kw)
        return c._do(CALLBACK, raw, {"Content-Type": "application/json", **heads})

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _clinic(c: Client, **over) -> str:
    f = dict(name="Clinica Card", idno="1234567890123", contact_name="Ion", email="card@example.md", phone="")
    f.update(over)
    return cid_from(c.post("/admin/clinics", **f).location)


def _letters(s: Server) -> list[tuple[str, str, bool]]:
    """(тема, текст, есть ли вложение license.json) по порядку отправки."""
    out = []
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        out.append((m["Subject"], m.get_body(preferencelist=("plain",)).get_content(),
                    any(p.get_filename() == "license.json" for p in m.walk())))
    return out


def _payment(s: Server, cid: str, n: int = 0) -> sqlite3.Row:
    con = sqlite3.connect(s.dir / "cloud.db")
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM payments WHERE clinic_id=? ORDER BY id", (cid,)).fetchall()[n]
    finally:
        con.close()


def _run(s: Server, at: date) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "app.jobs", "daily", "--at", f"{at:%Y-%m-%d}T06:00:00Z"],
                       cwd=str(CLOUD), env=s.env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return p.returncode, p.stdout + p.stderr


def suite_flow(res: Result) -> None:
    """Ссылка → callback: успешный, повторный, битый, чужой; кнопка «Проверить»; новая ссылка."""
    fake = FakeMaib()
    try:
        with Server(env={**BANK_ENV, **fake.env}) as s:
            c = Client(s.url).login()
            cid = _clinic(c)
            v = datetime.now(timezone.utc).date() + 60 * D
            c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")
            page = c.get(f"/admin/clinics/{cid}").body
            res.ok("карточка предлагает выбор: переводом или картой", "name='method'" in page and "Картой" in page)

            r = c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="1", method="card")
            res.check("платёж картой создан и отправлен", r.location, f"/admin/clinics/{cid}?msg=card_created_mailed")
            p = _payment(s, cid)
            ref = p["reference"]
            res.ok("строка: card, checkoutId и адрес страницы maib, ожидает",
                   p["method"] == "card" and p["provider_id"] in fake.pays
                   and p["pay_url"] == HOST + p["provider_id"].replace("-", "")
                   and p["status"] == "pending", dict(p))
            body = fake.bodies[-1]
            order, payer = body.get("orderInfo") or {}, body.get("payerInfo") or {}
            res.ok("maib получил: orderInfo.id = reference, сумма по тарифу, MDL, ro, адреса callback/success/fail "
                   "под DP_BASE_URL, e-mail клиники; IP 127.0.0.1 не передан",
                   order.get("id") == ref and body.get("amount") == float(config.PRICE_MONTH)
                   and body.get("currency") == "MDL" and body.get("language") == "ro"
                   and ref in order.get("description", "")
                   and body.get("callbackUrl") == "https://cloud.dentpilot.md" + CALLBACK
                   and body.get("successUrl") == "https://cloud.dentpilot.md/pay/ok"
                   and body.get("failUrl") == "https://cloud.dentpilot.md/pay/fail"
                   and payer == {"email": "card@example.md"}, body)
            res.check("токен взят один раз и переиспользован", fake.calls, {"token": 1, "pay": 1, "info": 0, "refund": 0})
            subj, text, _ = _letters(s)[-1]
            # ссылка maib живёт минуты (maib.PAY_TTL) — письмо несёт страницу оплаты, не checkoutUrl
            res.ok("письмо: карта — на странице оплаты (не ссылка maib), сумма, и перевод с тем же reference",
                   ref in subj and mail.CARD_NOTE in text and "/plata/" in text and p["pay_url"] not in text
                   and "MD00TEST0000000000000001" in text and f"Destinația plății: {ref}" in text, text[:400])
            res.ok("журнал: card_link с checkoutId", any(p["provider_id"] in d[0] for d in
                                                         _sql(s, "SELECT detail FROM audit WHERE what='card_link'")))

            # 1. callback, который врёт «Executed», пока сам maib ещё говорит WaitingForInit: только сигнал
            r = fake.post(c, p["provider_id"], paymentStatus="Executed", paymentId=str(uuid.uuid4()))
            res.ok("callback «Executed» при checkout WaitingForInit — принят как сигнал, исход waiting",
                   r.status == 200 and json.loads(r.body).get("outcome") == "waiting", f"{r.status} {r.body}")
            res.check("платёж по-прежнему ожидает, файла нет",
                      (_payment(s, cid)["status"], _sql(s, "SELECT count(*) FROM issues")[0][0]), ("pending", 1))
            res.check("сервер спросил maib", fake.calls["info"], 1)

            # 2. maib подтверждает: продление, файл, письмо
            fake.set_status(p["provider_id"], "Completed")
            n = len(_letters(s))
            r = fake.post(c, p["provider_id"], orderDescription="Abonament Plus, 1 lună — Clinica Ștefan Vodă")
            res.ok("успешный callback (тело с буквами UTF-8, подпись над сырыми байтами): 200, исход paid",
                   r.status == 200 and json.loads(r.body).get("outcome") == "paid", f"{r.status} {r.body}")
            p2 = _payment(s, cid)
            res.ok("платёж оплачен maib-ом, слова maib в строке",
                   p2["status"] == "paid" and p2["confirmed_by"] == "maib"
                   and p2["provider_status"].startswith("OK Completed/Executed"), dict(p2))
            code, claim = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/2/license.json").body, KEYS)
            v2 = pay.add_months(datetime(v.year, v.month, v.day, tzinfo=timezone.utc), 1).date()
            res.ok("файл seq 2 выдан, движок принимает, срок +1 месяц от прежнего конца",
                   code == "" and claim.seq == 2 and claim.valid_until.date() == v2, f"{code} {claim!r}")
            letters = _letters(s)
            res.ok("письмо о лицензии ушло (без файла — 02.10)",
                   len(letters) == n + 1 and "licența" in letters[-1][0].lower() and not letters[-1][2],
                   repr(letters[-1][:2]))
            res.check("журнал: payment_paid, issue, mail",
                      [r_[0] for r_ in _sql(s, "SELECT what FROM audit WHERE clinic_id=? ORDER BY id", cid)][-3:],
                      ["payment_paid", "issue", "mail"])
            card = c.get(f"/admin/clinics/{cid}").body
            res.ok("карточка: оплачен · maib, ссылка maib, действует", "maib" in card and "ссылка maib" in card)

            # 3. повторный callback — ничего
            r = fake.post(c, p["provider_id"])
            res.ok("повторный callback: 200, исход already", r.status == 200
                   and json.loads(r.body).get("outcome") == "already", f"{r.status} {r.body}")
            res.check("второго продления нет: выдач две, писем столько же",
                      (_sql(s, "SELECT count(*) FROM issues")[0][0], len(_letters(s))), (2, n + 1))

            # 4. битые callback — 400, ничего
            raw, heads = fake.callback(p["provider_id"])
            old = str(int(time.time() * 1000) - 3600 * 1000)
            for label, data, h in (
                    ("подпись чужим ключом", *fake.callback(p["provider_id"], key="wrong")),
                    ("метка часовой давности (повтор)", *fake.callback(p["provider_id"], ts=old)),
                    ("тело изменено после подписи", raw.replace(b'"amount":', b'"amount": '), heads),
                    ("подпись не ASCII (заголовок — latin-1)", raw, dict(heads, **{"X-Signature": "sha256=é" + heads["X-Signature"][8:]})),
                    ("без заголовков подписи", raw, {}),
                    ("метка не число", raw, dict(heads, **{"X-Signature-Timestamp": "abc"}))):
                r = c._do(CALLBACK, data, {"Content-Type": "application/json", **h})
                res.check(f"битый callback — {label}: 400", r.status, 400)
            ts = str(int(time.time() * 1000))
            for label, data in (("не JSON, но подписан", b"{oops"), ("JSON не объект, но подписан", b'"x"')):
                r = c._do(CALLBACK, data, {"Content-Type": "application/json", "X-Signature-Timestamp": ts,
                                           "X-Signature": "sha256=" + _php_sign(data, ts, SIGKEY)})
                res.ok(f"битый callback — {label}: 400 bad_json", r.status == 400 and "bad_json" in r.body, r.body)

            # 5. чужой callback — платёж не наш, 404
            fake.pays["not-ours"] = {"body": {"amount": 1.5, "currency": "MDL", "orderInfo": {"id": "DP-2026-999999"}},
                                     "status": "WaitingForInit", "payment": None, "created": datetime.now(timezone.utc)}
            fake.set_status("not-ours", "Completed")
            res.check("чужой callback с верной подписью: 404", fake.post(c, "not-ours").status, 404)
            res.check("подписанный callback без checkoutId: 404", fake.post(c, "not-ours", checkoutId=None).status, 404)
            res.check("после битых и чужого — выдач по-прежнему две", _sql(s, "SELECT count(*) FROM issues")[0][0], 2)

            # 6. кнопка «Проверить» — тот же вопрос maib; не прошёл → ждёт дальше со словами maib
            r = c.post(f"/admin/clinics/{cid}/payments", months="12", amount="", send="", method="card")
            res.check("второй платёж картой, без письма", r.location, f"/admin/clinics/{cid}?msg=card_created")
            q = _payment(s, cid, 1)
            fake.set_status(q["provider_id"], "Failed")
            r = c.post(f"/admin/payments/{q['id']}/check")
            res.check("проверить: не прошёл", r.location, f"/admin/clinics/{cid}?msg=card_failed")
            q2 = _payment(s, cid, 1)
            res.ok("остаётся в ожидании, слова maib записаны, журнал card_failed",
                   q2["status"] == "pending" and q2["provider_status"].startswith("FAILED Failed")
                   and _sql(s, "SELECT count(*) FROM audit WHERE what='card_failed'")[0][0] == 1, dict(q2))
            res.ok("карточка показывает слова maib", "FAILED" in c.get(f"/admin/clinics/{cid}").body)
            # новая ссылка — новый checkoutId, тот же reference
            r = c.post(f"/admin/payments/{q['id']}/link")
            res.check("новая ссылка создана и отправлена", r.location, f"/admin/clinics/{cid}?msg=card_link_mailed")
            q3 = _payment(s, cid, 1)
            res.ok("новый checkoutId, адрес, слова maib стёрты, reference прежний",
                   q3["provider_id"] != q["provider_id"] and q3["provider_id"] in fake.pays
                   and q3["provider_status"] == "" and q3["reference"] == q["reference"], dict(q3))
            res.ok("письмо с нотой — страница оплаты, не ссылка maib",
                   "/plata/" in _letters(s)[-1][1] and q3["pay_url"] not in _letters(s)[-1][1])
            fake.set_status(q3["provider_id"], "Completed")
            r = c.post(f"/admin/payments/{q['id']}/check")
            res.check("проверить: оплачен", r.location, f"/admin/clinics/{cid}?msg=card_paid")
            res.ok("третий файл выдан, письмо о лицензии ушло (без файла)",
                   _sql(s, "SELECT count(*) FROM issues")[0][0] == 3 and "licența" in _letters(s)[-1][0].lower()
                   and not _letters(s)[-1][2])
            r = c.post(f"/admin/payments/{q['id']}/check")
            res.check("проверить оплаченный: not_pending", r.location, f"/admin/clinics/{cid}?msg=payment_not_pending")
            res.check("ссылка к оплаченному не даётся", c.post(f"/admin/payments/{q['id']}/link").location,
                      f"/admin/clinics/{cid}?msg=payment_not_pending")
            # перевод без ссылки → «Ссылка на карту»
            c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="", method="transfer")
            t = _payment(s, cid, 2)
            res.ok("перевод: без checkoutId", not t["provider_id"] and t["method"] == "transfer")
            res.ok("у него кнопка «Ссылка на карту»", "Ссылка на карту" in c.get(f"/admin/clinics/{cid}").body)
            res.check("проверить платёж без ссылки — card_none", c.post(f"/admin/payments/{t['id']}/check").location,
                      f"/admin/clinics/{cid}?msg=card_none")
            r = c.post(f"/admin/payments/{t['id']}/link")
            res.ok("ссылка к переводу: платёж стал card, reference тот же",
                   r.location.endswith("msg=card_link_mailed") and _payment(s, cid, 2)["method"] == "card"
                   and _payment(s, cid, 2)["reference"] == t["reference"], r.location)
            # протухшая ссылка (Expired) — не «карта не прошла»: card_failed не пишется
            u = _payment(s, cid, 2)
            fake.set_status(u["provider_id"], "Expired")
            r = c.post(f"/admin/payments/{u['id']}/check")
            res.ok("Expired: «не прошёл» без строки card_failed, слова maib — TIMEOUT Expired",
                   r.location.endswith("msg=card_failed") and _payment(s, cid, 2)["provider_status"] == "TIMEOUT Expired"
                   and _sql(s, "SELECT count(*) FROM audit WHERE what='card_failed'")[0][0] == 1, r.location)

            # 7. страницы возврата — без слова «оплачено», с контактами
            ok = Client(s.url).get("/pay/ok")
            fail = Client(s.url).get("/pay/fail")
            res.ok("/pay/ok: спасибо, подтверждение письмом, без куки",
                   ok.status == 200 and "Mulțumim" in ok.body and "e-mail" in ok.body
                   and "set-cookie" not in ok.headers, ok.body[:200])
            res.ok("/pay/fail: не удалось, как ещё оплатить",
                   fail.status == 200 and "nu a reușit" in fail.body and "transfer bancar" in fail.body)
            # возврат браузера — параметры Checkout: checkoutId, checkoutStatus, orderId
            back = Client(s.url).get(f"/pay/ok?checkoutId={p['provider_id']}&checkoutStatus=Completed&orderId={ref}")
            res.ok("/pay/ok?checkoutId=…: № заказа оплаченной ноты и «plătită»",
                   back.status == 200 and ref in back.body and "plătită" in back.body, back.body[-800:])

            out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                                 capture_output=True, text=True, encoding="utf-8")
            res.ok("check: maib отвечает, Checkout v2, callback назван", "maib: токен получен" in out.stdout
                   and "Checkout v2" in out.stdout and CALLBACK in out.stdout, out.stdout[-500:])
    finally:
        fake.close()


def suite_duplicate(res: Result) -> None:
    """Карта прошла ПОСЛЕ того, как нота закрыта другим путём (02.10): деньги клиники у нас
    дважды — второй платёж зачитывается следующим периодом, один раз, и callback, и
    ежедневная задача, если callback потерялся."""
    fake = FakeMaib()
    try:
        with Server(env={**BANK_ENV, **fake.env}) as s:
            c = Client(s.url).login()

            def card_note(cid: str):
                c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="", method="card")
                return _payment(s, cid, len(_sql(s, "SELECT id FROM payments WHERE clinic_id=?", cid)) - 1)

            # 1. нота со ссылкой на карту закрыта ПЕРЕВОДОМ, потом клиника платит картой
            cid = _clinic(c)
            c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until="2027-01-31", grace_days="14")
            p = card_note(cid)
            c.post(f"/admin/payments/{p['id']}/confirm")
            res.ok("нота закрыта переводом: paid, via transfer, ссылка maib осталась",
                   (_payment(s, cid, 0)["status"], _payment(s, cid, 0)["paid_via"]) == ("paid", "transfer")
                   and _payment(s, cid, 0)["provider_id"] == p["provider_id"], dict(_payment(s, cid, 0)))
            fake.set_status(p["provider_id"], "Completed")
            n = len(_letters(s))
            r = fake.post(c, p["provider_id"])
            res.ok("callback карты по закрытой ноте: paid (зачтено), а не already",
                   r.status == 200 and json.loads(r.body).get("outcome") == "paid", f"{r.status} {r.body}")
            old, new = _payment(s, cid, 0), _payment(s, cid, 1)
            res.ok("новая строка: новый reference, оплачена картой, checkoutId переехал; у старой ссылки нет",
                   new["reference"] != old["reference"] and new["status"] == "paid" and new["paid_via"] == "card"
                   and new["provider_id"] == p["provider_id"] and old["provider_id"] is None, f"{dict(old)} {dict(new)}")
            res.check("срок: два периода по якорю — 28.02 и 31.03",
                      _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid)[0][0][:10], "2027-03-31")
            res.ok("письмо о лицензии ушло", len(_letters(s)) == n + 1 and "licența" in _letters(s)[-1][0].lower())
            res.check("журнал: payment_repeat", _sql(s, "SELECT count(*) FROM audit WHERE what='payment_repeat'")[0][0], 1)
            issues = _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0]
            r = fake.post(c, p["provider_id"])
            res.ok("повторный callback того же платежа: already, третьего периода нет",
                   json.loads(r.body).get("outcome") == "already"
                   and _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0] == issues, r.body)
            res.ok("в карточке зачтённая строка — «картой»", "картой" in c.get(f"/admin/clinics/{cid}").body)

            # 2. то же, но callback потерялся — зачитывает ежедневная задача
            cid2 = _clinic(c, name="Clinica Fără Callback", email="fara@example.md")
            c.post(f"/admin/clinics/{cid2}/issue", kind="dates", valid_until="2027-01-15", grace_days="14")
            q = card_note(cid2)
            c.post(f"/admin/payments/{q['id']}/confirm")
            fake.set_status(q["provider_id"], "Completed")
            code, out = _run(s, datetime.now(timezone.utc).date())
            res.ok("ежедневная задача нашла карту по закрытой ноте и зачла её",
                   code == 0 and len(_sql(s, "SELECT id FROM payments WHERE clinic_id=?", cid2)) == 2
                   and _payment(s, cid2, 1)["paid_via"] == "card", out[-400:])
            res.check("срок второй клиники: 15.02 и 15.03",
                      _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid2)[0][0][:10], "2027-03-15")
            code, out = _run(s, datetime.now(timezone.utc).date())
            res.check("второй проход задачи ничего не прибавляет",
                      len(_sql(s, "SELECT id FROM payments WHERE clinic_id=?", cid2)), 2)

            # 3. нота ОТКЛОНЕНА, а карта по её ссылке прошла — деньги тоже не теряем
            cid3 = _clinic(c, name="Clinica Respinsă", email="resp@example.md")
            c.post(f"/admin/clinics/{cid3}/issue", kind="dates", valid_until="2027-01-10", grace_days="14")
            t = card_note(cid3)
            c.post(f"/admin/payments/{t['id']}/reject", reason="другая сумма")
            fake.set_status(t["provider_id"], "Completed")
            r = fake.post(c, t["provider_id"])
            res.ok("карта по отклонённой ноте: зачтена, срок +1 месяц",
                   json.loads(r.body).get("outcome") == "paid"
                   and _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid3)[0][0][:10] == "2027-02-10",
                   r.body)

            # 4. оплаченная ЭТОЙ ЖЕ картой — по-прежнему already
            cid4 = _clinic(c, name="Clinica Card Simplu", email="simplu@example.md")
            c.post(f"/admin/clinics/{cid4}/issue", kind="dates", valid_until="2027-01-20", grace_days="14")
            u = card_note(cid4)
            fake.set_status(u["provider_id"], "Completed")
            fake.post(c, u["provider_id"])
            r = fake.post(c, u["provider_id"])
            res.ok("нота, закрытая этой картой: второй callback — already, строка одна",
                   json.loads(r.body).get("outcome") == "already"
                   and len(_sql(s, "SELECT id FROM payments WHERE clinic_id=?", cid4)) == 1
                   and _payment(s, cid4, 0)["paid_via"] == "card", r.body)
    finally:
        fake.close()


def suite_daily(res: Result) -> None:
    """Ежедневная задача с maib: в счёте — страница оплаты (ссылка maib рождается по клику,
    23.10), оплата картой замечена без callback."""
    fake = FakeMaib()
    try:
        with Server(env={**BANK_ENV, **fake.env}) as s:
            c = Client(s.url).login()
            cid = _clinic(c, name="Clinica Zilnic Card", email="zc@example.md")
            v = datetime.now(timezone.utc).date() + 60 * D
            c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")
            rc, out = _run(s, v - 14 * D)
            res.ok("за 14 дней: счёт ушёл, код 0", rc == 0 and "писем: 1" in out, out[-300:])
            p = _payment(s, cid)
            res.ok("платёж задачи без ссылки maib: та живёт минуты и рождается по клику",
                   not p["provider_id"] and fake.calls["pay"] == 0, dict(p))
            subj, text, _ = _letters(s)[0]
            res.ok("счёт: страница оплаты с картой и перевод с reference",
                   mail.CARD_NOTE in text and "/plata/" in text and f"Destinația plății: {p['reference']}" in text,
                   text[:400])
            # клиника открыла страницу из письма и нажала «Plătește cu cardul» (за галочкой)
            page = "/plata/" + text.split("/plata/", 1)[1].split()[0]
            r = Client(s.url).post(page, tier="plus", months="1", method="card", terms="1")
            p = _payment(s, cid)
            res.ok("клик на странице из письма: ссылка maib родилась сейчас, браузер — на неё",
                   r.status == 303 and r.location == p["pay_url"] and p["provider_id"] in fake.pays
                   and fake.calls["pay"] == 1, f"{r.status} {r.location} {dict(p)}")
            rc, out = _run(s, v - 13 * D)
            res.ok("на следующий день: maib спрошен, оплаты нет, писем нет",
                   rc == 0 and "писем: 0" in out and "картой оплачено: 0" in out and fake.calls["info"] == 1, out[-300:])
            fake.set_status(p["provider_id"], "Completed")
            n = len(_letters(s))
            rc, out = _run(s, v - 12 * D)
            res.ok("клиника заплатила картой, callback не дошёл: задача заметила",
                   rc == 0 and f"оплачено картой {p['reference']}" in out and "картой оплачено: 1" in out, out[-300:])
            p2 = _payment(s, cid)
            res.ok("платёж оплачен задачей от имени daily, файл выдан и отправлен",
                   p2["status"] == "paid" and p2["confirmed_by"] == "daily"
                   and _sql(s, "SELECT count(*) FROM issues")[0][0] == 2 and len(_letters(s)) == n + 1
                   and "licența" in _letters(s)[-1][0].lower() and not _letters(s)[-1][2], dict(p2))
            v2 = pay.add_months(datetime(v.year, v.month, v.day, tzinfo=timezone.utc), 1).date()
            res.check("срок продлён на месяц от прежнего конца",
                      _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid)[0][0][:10], f"{v2:%Y-%m-%d}")
            res.ok("журнал daily считает оплату картой",
                   any("картой оплачено: 1" in d[0] for d in _sql(s, "SELECT detail FROM audit WHERE what='daily'")))
            rc, out = _run(s, v - 11 * D)
            res.ok("дальше по старому периоду писем нет, новых вопросов maib нет",
                   "писем: 0" in out and fake.calls["info"] == 2)

        # maib молчит: счёт уходит с одним reference, задача не падает
        fake.close()
        with Server(env={**BANK_ENV, **fake.env}) as s:
            c = Client(s.url).login()
            cid = _clinic(c, name="Fara Maib", email="fm@example.md")
            v = datetime.now(timezone.utc).date() + 60 * D
            c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")
            rc, out = _run(s, v - 14 * D)
            p = _payment(s, cid)
            subj, text, _ = _letters(s)[0]
            res.ok("maib недоступен: письмо с переводом, без ссылки, код 0",
                   rc == 0 and not p["provider_id"] and p["method"] == "transfer"
                   and HOST not in text and f"Destinația plății: {p['reference']}" in text, out[-300:])
            r = c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="1", method="card")
            res.check("платёж картой при молчащем maib: maib_failed", r.location, f"/admin/clinics/{cid}?msg=maib_failed")
            res.check("строка откатилась: платёж один, reference не потрачен",
                      _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=?", cid)[0][0], 1)
            out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                                 capture_output=True, text=True, encoding="utf-8")
            res.ok("check: maib не отвечает — препятствие", out.returncode == 1 and "maib не отвечает" in out.stdout,
                   out.stdout[-400:])
    finally:
        fake.close()


class SlowSmtp:
    """Стенд SMTP: приветствие через `delay` секунд, STARTTLS не умеет — mail.send бросает
    SMTPNotSupportedError, письмо уходит в `mail_failed`, оплата не откатывается. Так письмо
    после оплаты становится заметной паузой ровно там, где сервер его шлёт: сервер теста —
    отдельный процесс, подменить в нём mail.send нечем (и не нужно)."""

    def __init__(self, delay: float = 0.8):
        self.delay = delay
        self.sessions = 0
        self._lock = threading.Lock()
        stand = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                with stand._lock:
                    stand.sessions += 1
                time.sleep(stand.delay)
                self.wfile.write(b"220 stand ESMTP\r\n")
                for line in self.rfile:
                    verb = line[:4].upper()
                    if verb == b"EHLO":
                        self.wfile.write(b"250-stand\r\n250 SIZE 1000000\r\n")
                    elif verb == b"HELO":
                        self.wfile.write(b"250 stand\r\n")
                    elif verb == b"QUIT":
                        self.wfile.write(b"221 bye\r\n")
                        return
                    else:
                        self.wfile.write(b"502 not implemented\r\n")

        class S(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

            def handle_error(self, request, client_address):
                pass

        self.srv = S(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def env(self) -> dict:
        return {"DP_SMTP_HOST": "127.0.0.1", "DP_SMTP_PORT": str(self.srv.server_address[1]),
                "DP_SMTP_USER": "", "DP_SMTP_PASS": ""}

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def _together(*calls) -> list:
    """Вызовы из своих потоков, отпущенные разом (Barrier); ответ или исключение — по порядку."""
    gate = threading.Barrier(len(calls))
    out: list = [None] * len(calls)

    def go(i, fn):
        gate.wait()
        try:
            out[i] = fn()
        except Exception as e:  # noqa: BLE001 — исключение тоже ответ
            out[i] = e

    threads = [threading.Thread(target=go, args=(i, fn), daemon=True) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    return out


def suite_race(res: Result) -> None:
    """maib почти одновременно шлёт callback и возвращает браузер на /pay/ok (30.10, ревью):
    обе ветки читают платёж и зовут settle. В отложенной транзакции WAL та, что прочитала
    до коммита соседки, при записи сразу получает «database is locked» (busy timeout не
    ждёт устаревший снимок) — 500. settle обязан идти под замком записи с начала
    (db.connect(immediate=True)): вторая ждёт первую, перечитывает и видит «уже оплачено».
    Пауза внутри первой транзакции — письмо после оплаты на медленный стенд SMTP.
    Второй круг — то же втроём, с кнопкой «Проверить» админки."""
    fake, smtp = FakeMaib(), SlowSmtp()
    try:
        with Server(env={**BANK_ENV, **fake.env, **smtp.env}) as s:
            c = Client(s.url).login()
            for n, name, admin in ((1, "Clinica Cursa", False), (2, "Clinica Cursa Trei", True)):
                cid = _clinic(c, name=name, email=f"cursa{n}@example.md")
                v = datetime.now(timezone.utc).date() + 60 * D
                c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")
                c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="", method="card")
                p = _payment(s, cid)
                fake.set_status(p["provider_id"], "Completed")
                issues = _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0]
                sessions = smtp.sessions
                maib_cb, browser = Client(s.url), Client(s.url)
                calls = [lambda: fake.post(maib_cb, p["provider_id"]),
                         lambda: browser.get(f"/pay/ok?checkoutId={p['provider_id']}&checkoutStatus=Completed"
                                             f"&orderId={p['reference']}")]
                if admin:
                    calls.append(lambda: c.post(f"/admin/payments/{p['id']}/check"))
                got = _together(*calls)
                cb, ok = got[0], got[1]
                tag = f"круг {n}"
                res.ok(f"{tag}: callback — 200, исход paid или already",
                       getattr(cb, "status", None) == 200
                       and json.loads(cb.body).get("outcome") in ("paid", "already"),
                       repr(cb) if isinstance(cb, Exception) else f"{cb.status} {cb.body[:300]}")
                res.ok(f"{tag}: /pay/ok — 200 и «plătită»",
                       getattr(ok, "status", None) == 200 and "plătită" in ok.body,
                       repr(ok) if isinstance(ok, Exception) else f"{ok.status} {ok.body[:300]}")
                if admin:
                    ch = got[2]
                    res.ok(f"{tag}: «Проверить» — 303 card_paid или payment_not_pending",
                           getattr(ch, "status", None) == 303
                           and ch.location.split("msg=")[-1] in ("card_paid", "payment_not_pending"),
                           repr(ch) if isinstance(ch, Exception) else f"{ch.status} {ch.location} {ch.body[:300]}")
                rows = _sql(s, "SELECT id, status FROM payments WHERE clinic_id=?", cid)
                res.check(f"{tag}: нота одна и оплачена", [r[1] for r in rows], ["paid"])
                res.check(f"{tag}: выдача по ней ровно одна новая",
                          _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0], issues + 1)
                res.check(f"{tag}: cont de plată — одна строка",
                          _sql(s, "SELECT count(*) FROM receipts WHERE payment_id=?", p["id"])[0][0], 1)
                res.check(f"{tag}: журнал — один payment_paid",
                          _sql(s, "SELECT count(*) FROM audit WHERE what='payment_paid' AND clinic_id=?", cid)[0][0], 1)
                v2 = pay.add_months(datetime(v.year, v.month, v.day, tzinfo=timezone.utc), 1).date()
                res.check(f"{tag}: срок продлён ровно на месяц",
                          _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid)[0][0][:10],
                          f"{v2:%Y-%m-%d}")
                res.ok(f"{tag}: письмо после оплаты дошло до медленного стенда SMTP (пауза была)",
                       smtp.sessions > sessions, f"{smtp.sessions} > {sessions}")
            log_ = s.log()
            res.ok("в логе сервера ни «database is locked», ни трейсбека",
                   "database is locked" not in log_ and "Traceback" not in log_, log_[-1500:])
    finally:
        smtp.close()
        fake.close()


def suite_off(res: Result) -> None:
    """Без DP_MAIB_*: карт нет, всё остальное как в шаге 1."""
    with Server(env={**BANK_ENV, "DP_MAIB_PROJECT_ID": "v1-project"}) as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        page = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: выбора нет, сказано почему", "name='method'" not in page and "DP_MAIB_* не заданы" in page)
        r = c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="1", method="card")
        res.check("картой без maib: no_maib, платёж не создан", r.location, f"/admin/clinics/{cid}?msg=no_maib")
        res.check("платежей нет", _sql(s, "SELECT count(*) FROM payments")[0][0], 0)
        r = c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="1")
        res.check("переводом — как раньше", r.location, f"/admin/clinics/{cid}?msg=payment_created_mailed")
        p = _payment(s, cid)
        res.ok("без ссылки, без кнопок карты",
               not p["provider_id"] and "Ссылка на карту" not in c.get(f"/admin/clinics/{cid}").body)
        res.check("ссылка без maib: no_maib", c.post(f"/admin/payments/{p['id']}/link").location, "/admin/payments?msg=no_maib")
        ts = str(int(time.time() * 1000))
        data = b'{"checkoutId": "x"}'
        r = c._do(CALLBACK, data, {"Content-Type": "application/json", "X-Signature-Timestamp": ts,
                                   "X-Signature": "sha256=" + _php_sign(data, ts, "")})
        res.check("callback без ключа подписи: 400", r.status, 400)
        out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                             capture_output=True, text=True, encoding="utf-8")
        res.ok("check: карты выключены — предупреждение", "DP_MAIB_* пусты" in out.stdout, out.stdout[-300:])
        res.ok("check: имя e-Commerce v1 в окружении — предупреждение, что оно не читается",
               "DP_MAIB_PROJECT_ID: имена e-Commerce v1" in out.stdout, out.stdout[-400:])


def suite_wire(res: Result) -> None:
    """Провод app/maib.py напрямую против документации Checkout (30.10.2026): образец
    подписи, поля checkout, перевод статусов, отозванный токен, 403, возврат денег."""
    res.check("пример PHP на стенде даёт подпись образца документации", _php_sign(DOC_BODY, DOC_TS, DOC_KEY),
              DOC_SIGNATURE)
    res.check("провод: подпись образца документации",
              base64.b64encode(maib.signature(DOC_BODY, DOC_TS, DOC_KEY)).decode("ascii"), DOC_SIGNATURE)
    res.ok("…а пересобранное тело (json.dumps) даёт другую — подпись только над сырыми байтами",
           _php_sign(json.dumps(json.loads(DOC_BODY)).encode(), DOC_TS, DOC_KEY) != DOC_SIGNATURE)

    saved = {k: getattr(config, k) for k in ("MAIB_BASE_URL", "MAIB_CLIENT_ID", "MAIB_CLIENT_SECRET",
                                             "MAIB_SIGNATURE_KEY", "BASE_URL")}
    fake = FakeMaib()
    seen = _Records()
    wire_log = logging.getLogger("cloud.maib")
    wire_log.addHandler(seen)
    wire_log.propagate = False
    at = int(DOC_TS) / 1000
    try:
        config.MAIB_SIGNATURE_KEY = DOC_KEY
        res.ok("verify: образец документации принят (sha256=…, метка в мс)",
               maib.verify(DOC_BODY, "sha256=" + DOC_SIGNATURE, DOC_TS, now=at + 30) and not seen.lines)
        hexsig = maib.signature(DOC_BODY, DOC_TS, DOC_KEY).hex()
        res.ok("verify: та же подпись в hex (документация допускает оба вида)",
               maib.verify(DOC_BODY, "sha256=" + hexsig.upper(), DOC_TS, now=at))
        res.ok("verify: подпись без префикса sha256= тоже принята", maib.verify(DOC_BODY, DOC_SIGNATURE, DOC_TS, now=at))
        res.ok("verify: метка в секундах понята",
               maib.verify(DOC_BODY, _php_sign(DOC_BODY, DOC_TS[:-3], DOC_KEY), DOC_TS[:-3], now=at))
        res.ok("verify: подпись не ASCII — False, без исключения",
               maib.verify(DOC_BODY, "sha256=mtFkCMxfwj9t2wvY/7JASHLw+K/du4mY8azf1lV0ttș=", DOC_TS, now=at) is False)
        res.ok("verify: чужой ключ — False", maib.verify(DOC_BODY, _php_sign(DOC_BODY, DOC_TS, "alt"), DOC_TS, now=at)
               is False)
        res.ok("verify: метка старше SIGNATURE_SKEW — False (повтор)",
               maib.verify(DOC_BODY, "sha256=" + DOC_SIGNATURE, DOC_TS, now=at + maib.SIGNATURE_SKEW + 5) is False)
        res.ok("verify: метка из будущего за окном — False",
               maib.verify(DOC_BODY, "sha256=" + DOC_SIGNATURE, DOC_TS, now=at - maib.SIGNATURE_SKEW - 5) is False)
        res.ok("verify: без ключа подписи — False", (setattr(config, "MAIB_SIGNATURE_KEY", "")
                                                    or maib.verify(DOC_BODY, DOC_SIGNATURE, DOC_TS, now=at)) is False)
        res.ok("несошедшаяся подпись в логе: длины и метка, без ключа и без тела",
               any("подпись не сошлась" in x for x in seen.lines)
               and not any(DOC_KEY in x or "John" in x for x in seen.lines), seen.lines)

        config.MAIB_BASE_URL, config.MAIB_CLIENT_ID = fake.url, CLIENT
        config.MAIB_CLIENT_SECRET, config.BASE_URL = SECRET, "https://cloud.dentpilot.md"
        config.MAIB_SIGNATURE_KEY = SIGKEY
        maib._token.update(value="", until=0.0)
        long_ip = "2a02:2f0e:5b0d:a700:1c4e:8f2a:3b9d:12ef"
        cid, url = maib.create(400, "DP-2026-000001", "DentPilot DP-2026-000001: " + "Clinica Ștefan Vodă " * 10,
                               "x" * 50 + "@example.md", long_ip)
        body = fake.bodies[-1]
        res.ok("create: maib принял, checkoutId и checkoutUrl", cid in fake.pays and url.startswith(HOST), body)
        res.ok("описание ≤ 125 знаков, IPv6 и длинный e-mail переданы как есть (у Checkout нет предела 15/40)",
               len(body["orderInfo"]["description"]) == 125 and body["payerInfo"] == {"email": "x" * 50 + "@example.md",
                                                                                      "ip": long_ip}, body)
        heads = fake.heads[-1][2]
        res.ok("create: Bearer-токен и Content-Type application/json",
               heads.get("authorization") == f"Bearer {fake.token_value}"
               and heads.get("content-type") == "application/json", heads)
        maib.create(400, "DP-2026-000002", "DentPilot", "clinica@example.md", "::ffff:93.115.12.7")
        res.check("IPv4 в обёртке IPv6 → его IPv4", fake.bodies[-1]["payerInfo"],
                  {"email": "clinica@example.md", "ip": "93.115.12.7"})
        maib.create(400, "DP-2026-000003", "DentPilot", "не адрес", "?")
        res.ok("«?» вместо адреса и кривой e-mail — payerInfo не передан", "payerInfo" not in fake.bodies[-1],
               fake.bodies[-1])
        maib.create(400, "DP-2026-000004", "DentPilot", "", "127.0.0.1")
        res.ok("127.0.0.1 (запрос из админки) — не адрес плательщика, не передан", "payerInfo" not in fake.bodies[-1])
        try:
            maib._authed("POST", "/v2/checkouts", dict(fake.bodies[-1], orderInfo={"id": "x", "description": "d" * 126}))
            res.ok("стенд отказывает в поле не по документации", False)
        except maib.MaibError as e:
            res.ok("стенд отказывает в поле не по документации: HTTP 400, 42005",
                   e.http == 400 and "maib.merchant.payments-42005" in str(e), str(e))

        res.check("статус: WaitingForInit → CREATED, payId = checkoutId", (maib.info(cid)["status"],
                                                                           maib.info(cid)["payId"]), ("CREATED", cid))
        heads = fake.heads[-1][2]
        res.ok("GET статуса без тела и без Content-Type (как в коллекции Postman)",
               "content-type" not in heads and fake.heads[-1][0] == "GET", heads)
        for st, pst, want in (("Initialized", None, "PENDING"), ("PaymentMethodSelected", None, "PENDING"),
                              ("Expired", None, "TIMEOUT"), ("Abandoned", None, "TIMEOUT"),
                              ("Cancelled", None, "CANCELLED"), ("Failed", None, "FAILED"),
                              ("Somewhere", None, "PENDING"),
                              ("Waitingforinit", None, "CREATED")):     # так ответила живая песочница 30.10
            fake.set_status(cid, st)
            res.check(f"статус: {st} → {want}", maib.info(cid)["status"], want)
        res.ok("незнакомый статус — ожидание и строка в логе",
               any("незнакомый статус" in x and "Somewhere" in x for x in seen.lines), seen.lines)
        res.check("токен до сих пор один", fake.calls["token"], 1)
        fake.rotate()
        res.check("отозванный токен: 401 → один раз новый, ответ есть", maib.info(cid)["payId"], cid)
        res.check("токен взят второй раз", fake.calls["token"], 2)

        fake.set_status(cid, "Initialized")
        try:
            maib.refund(cid)
            res.ok("возврат неоплаченного — ошибка", False)
        except maib.MaibError as e:
            res.ok("возврат неоплаченного — ошибка провода (у checkout нет платежа)", "нет платежа" in str(e), str(e))
        fake.set_status(cid, "Completed")
        got = maib.info(cid)
        res.ok("Completed/Executed → OK, paymentId платежа, способ оплаты",
               got["status"] == "OK" and got["paymentId"] == fake.pays[cid]["payment"]["paymentId"]
               and got["statusCode"] == "Completed/Executed" and got["statusMessage"] == "Card", got)
        fake.pays[cid]["status"], fake.pays[cid]["payment"]["status"] = "COMPLETED", "executed"
        res.check("регистр слов maib не важен: COMPLETED/executed → OK", maib.info(cid)["status"], "OK")
        fake.pays[cid]["status"], fake.pays[cid]["payment"]["status"] = "Completed", "Executed"
        r = maib.refund(cid)
        rq = fake.heads[-1]
        res.ok("полный возврат: Created, refundId, запрос на /v2/payments/{paymentId}/refund",
               r["status"] == "Created" and r["refundId"] in fake.refunds
               and rq[1] == f"/v2/payments/{got['paymentId']}/refund", (r, rq[:2]))
        res.ok("сумма возврата — refundableAmount платежа (400), причина передана",
               fake.refunds[r["refundId"]]["amount"] == 400.0 and fake.refunds[r["refundId"]]["refundReason"], fake.refunds)
        res.check("возврат по id: Created", maib.refund_info(r["refundId"])["status"], "Created")
        res.check("после полного возврата: Completed/Refunded → REFUNDED", maib.info(cid)["status"], "REFUNDED")
        try:
            maib.refund(cid)
            res.ok("второй возврат того же — ошибка", False)
        except maib.MaibError as e:
            res.ok("второй возврат того же: «возврату не подлежит», без запроса к refund",
                   "не подлежит" in str(e) and fake.calls["refund"] == 1, str(e))
        cid2, _ = maib.create(600, "DP-2026-000005", "DentPilot")
        fake.set_status(cid2, "Completed")
        r = maib.refund(cid2, 150)
        res.ok("частичный возврат: 150 числом, платёж PartiallyRefunded — для нас всё ещё OK",
               fake.refunds[r["refundId"]]["amount"] == 150.0 and maib.info(cid2)["status"] == "OK"
               and maib.payment(r["paymentId"])["status"] == "PartiallyRefunded", fake.refunds[r["refundId"]])
        try:
            maib.refund(cid2, 1000)
            res.ok("возврат больше остатка — ошибка", False)
        except maib.MaibError as e:
            res.ok("возврат больше остатка — HTTP 400 от maib", e.http == 400, str(e))
        try:
            maib.info("f16a9006-0000-0000-0000-000000000000")
            res.ok("чужой checkoutId — ошибка", False)
        except maib.MaibError as e:
            res.ok("чужой checkoutId — HTTP 404, код и текст maib", e.http == 404 and "43001" in str(e), str(e))

        config.MAIB_CLIENT_SECRET = "wrong"
        maib._token.update(value="", until=0.0)
        try:
            maib.token()
            res.ok("неверные ключи — ошибка", False)
        except maib.MaibError as e:
            res.ok("неверные ключи: HTTP 401 на auth/token", e.http == 401 and "auth/token" in str(e), str(e))
        config.MAIB_CLIENT_SECRET = SECRET
        fake.forbid = True
        maib._token.update(value="", until=0.0)
        try:
            maib.token()
            res.ok("403: не с IP проекта", False)
        except maib.MaibError as e:
            res.ok("403: подсказка про IP сервера и ключи проекта", e.http == 403 and "IP сервера" in str(e), str(e))
    finally:
        for k, v in saved.items():
            setattr(config, k, v)
        maib._token.update(value="", until=0.0)
        wire_log.removeHandler(seen)
        wire_log.propagate = True
        fake.close()
