"""Оплата картой через maib (L12): ссылка, callback, статус, ежедневная задача.

maib здесь — СТЕНД в процессе теста (http.server), и это единственное место,
где он существует: прод знает один адрес, DP_MAIB_BASE_URL. Стенд говорит
теми же именами, что документация maib e-Commerce API v1 (generate-token, pay,
pay-info, refund, callback с подписью; сверено 23.10.2026), отказывает так же,
как она описывает (поля /pay, Content-Type у pay-info, отозванный токен), и
подписывает callback построчной записью ПРИМЕРА maib на PHP, независимой от
app/maib.py. Сам пример проверяется своим образцом из документации
(`DOC_*`) — так провод сервера держится документированной формы, а не самого
себя.

Четыре исхода callback из cloud.md: успешный (продление, файл, письмо),
повторный (ничего), битый (400, ничего), чужой (404, ничего). И главный
инвариант: callback — только сигнал; оплачено лишь то, про что сам maib
(pay-info) сказал OK.
"""
import base64
import email
import email.policy
import hashlib
import http.server
import ipaddress
import json
import logging
import sqlite3
import subprocess
import sys
import threading
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
PROJECT, SECRET, SIGKEY = "proj-test", "secret-test", "signature-key-test"
CALLBACK = "/v1/maib/callback"
D = timedelta(days=1)


# Образец из документации: «Notifications on Callback Url» › «Callback signature»
# (docs.maibmerchants.md/e-commerce/notifications-on-callback-url.md, 23.10.2026).
DOC_KEY = "8508706b-3454-4733-8295-56e617c4abcf"
DOC_RESULT = {"payId": "f16a9006-128a-46bc-8e2a-77a6ee99df75", "orderId": "123", "status": "OK",
              "statusCode": "000", "statusMessage": "Approved", "threeDs": "AUTHENTICATED",
              "rrn": "331711380059", "approval": "327593", "cardNumber": "510218******1124",
              "amount": 10.25, "currency": "MDL"}
DOC_STRING = ("10.25:327593:510218******1124:MDL:123:f16a9006-128a-46bc-8e2a-77a6ee99df75:"
              "331711380059:OK:000:Approved:AUTHENTICATED:8508706b-3454-4733-8295-56e617c4abcf")
DOC_SIGNATURE = "5wHkZvm9lFeXxSeFF0ui2CnAp7pCEFSNmuHYFYJlC0s="


def _php_string(result: dict, key: str) -> str:
    """Пример maib на PHP (callbackUrl.php их SDK, тот же в документации), построчно
    и независимо от app/maib.py: sortByKeyRecursive, `$sorted[] = $key`,
    implodeRecursive(':', …) с `(string)$item`."""
    def sort_by_key_recursive(array):
        pairs = array.items() if isinstance(array, dict) else enumerate(array)
        out = []
        for k, value in sorted(pairs, key=lambda kv: str(kv[0])):     # ksort($array, SORT_STRING)
            out.append((k, sort_by_key_recursive(value) if isinstance(value, (dict, list)) else value))
        return out

    def php_string(item) -> str:                                        # (string)$item, precision=14
        if item is None or item is False:
            return ""
        if item is True:
            return "1"
        if isinstance(item, float):
            return format(item, ".14G")
        return str(item)

    def implode_recursive(separator, array) -> str:
        result_ = ""
        for _, item in array:
            result_ += (implode_recursive(separator, item) if isinstance(item, list) else php_string(item)) + separator
        return result_[:-1]                                             # substr($result, 0, -1)

    return implode_recursive(":", sort_by_key_recursive(result) + [(None, key)])


def _php_sign(result: dict, key: str) -> str:
    """base64_encode(hash('sha256', $signString, true))."""
    return base64.b64encode(hashlib.sha256(_php_string(result, key).encode("utf-8")).digest()).decode("ascii")


def _bad(param: str) -> dict:
    """Отказ maib по полю — форма из «Direct payment» › Error."""
    return {"ok": False, "errors": [{"errorCode": "12001", "errorMessage": f"Parameter '{param}' is invalid",
                                     "errorArgs": {"parameter": param}}]}


def _pay_error(body: dict) -> str:
    """Первое поле /pay, которое maib не принял бы по документации; пусто — всё по ней."""
    def number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def text(v, n):
        return isinstance(v, str) and len(v.encode("utf-8")) <= n

    def ip(v):
        try:
            ipaddress.ip_address(v)
        except ValueError:
            return False
        return isinstance(v, str) and len(v) <= 15

    checks = (("amount", number(body.get("amount")) and body.get("amount") >= 1),
              ("currency", body.get("currency") in ("MDL", "EUR", "USD")),
              ("clientIp", ip(body.get("clientIp"))),
              ("language", body.get("language") in ("ro", "en", "ru")),
              ("description", "description" not in body or text(body["description"], 124)),
              ("email", "email" not in body or (text(body["email"], 40) and "@" in body["email"])),
              ("orderId", "orderId" not in body or text(body["orderId"], 36)),
              *((u, isinstance(body.get(u), str) and body[u].startswith("https://"))
                for u in ("callbackUrl", "okUrl", "failUrl")))
    return next((name for name, good in checks if not good), "")


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


class FakeMaib:
    """Стенд maib: токен по проекту, платёж с payUrl, pay-info со статусом, который ставит
    тест, возврат. `rotate()` отзывает выданный токен, `forbid` — запрос не с IP проекта."""

    def __init__(self):
        self.calls = {"token": 0, "pay": 0, "info": 0, "refund": 0}
        self.pays: dict[str, dict] = {}
        self.bodies: list[dict] = []
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
                if fake.forbid:
                    self._json(403, {"ok": False, "errors": [{"errorMessage": "Forbidden"}]})
                    return True
                if self.path != "/v1/generate-token" and \
                        self.headers.get("Authorization") != f"Bearer {fake.token_value}":
                    self._json(401, {"ok": False, "errors": [{"errorMessage": "Unauthorized"}]})
                    return True
                return False

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self._refused():
                    return
                if self.path == "/v1/generate-token":
                    fake.calls["token"] += 1
                    if (body.get("projectId"), body.get("projectSecret")) != (PROJECT, SECRET):
                        return self._json(401, {"ok": False, "errors": [{
                            "errorCode": "11001", "errorMessage": "Invalid credentials. Please check "
                                                                  "'projectId' and 'projectSecret' parameters"}]})
                    return self._json(200, {"ok": True, "result": {
                        "accessToken": fake.token_value, "expiresIn": 300, "refreshToken": "r",
                        "refreshExpiresIn": 1800, "tokenType": "Bearer"}})
                if self.path == "/v1/pay":
                    fake.calls["pay"] += 1
                    fake.bodies.append(body)
                    bad = _pay_error(body)
                    if bad:
                        return self._json(400, _bad(bad))
                    pid = str(uuid.uuid4())
                    fake.pays[pid] = {"body": body, "status": "CREATED", "refunded": None}
                    return self._json(200, {"ok": True, "result": {
                        "payId": pid, "orderId": body.get("orderId"),
                        "payUrl": f"https://maib.ecommerce.md/checkout/{pid}"}})
                if self.path == "/v1/refund":
                    fake.calls["refund"] += 1
                    p = fake.pays.get(body.get("payId"))
                    if p is None:
                        return self._json(404, {"ok": False, "errors": [{
                            "errorCode": "13002", "errorMessage": f"Payment ID '{body.get('payId')}' not found"}]})
                    amount = body.get("refundAmount", p["body"]["amount"])
                    if p["status"] != "OK" or not isinstance(amount, (int, float)) \
                            or not 0.01 <= amount <= p["body"]["amount"]:
                        return self._json(400, _bad("refundAmount" if p["status"] == "OK" else "payId"))
                    first = p["refunded"] is None
                    if first:
                        p["refunded"] = amount
                    return self._json(200, {"ok": True, "result": {
                        "payId": body["payId"], "orderId": p["body"].get("orderId"),
                        "status": "OK" if first else "REVERSED", "statusCode": "400",
                        "statusMessage": "Accepted", "refundAmount": p["refunded"]}})
                self._json(404, {"ok": False, "errors": [{"errorMessage": "Not found"}]})

            def do_GET(self):
                if self._refused():
                    return
                if self.path.startswith("/v1/pay-info/"):
                    fake.calls["info"] += 1
                    # «Ensure that the Content-Type header and body are excluded» — документация pay-info
                    if self.headers.get("Content-Type") or int(self.headers.get("Content-Length") or 0):
                        return self._json(415, {"ok": False, "errors": [{"errorMessage": "Unsupported Media Type"}]})
                    pid = self.path.rsplit("/", 1)[1]
                    if pid not in fake.pays:
                        return self._json(404, {"ok": False, "errors": [{
                            "errorCode": "13002", "errorMessage": f"Payment ID '{pid}' not found"}]})
                    return self._json(200, {"ok": True, "result": fake.info(pid)})
                self._json(404, {"ok": False})

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def env(self) -> dict:
        return {"DP_MAIB_BASE_URL": self.url + "/v1", "DP_MAIB_PROJECT_ID": PROJECT,
                "DP_MAIB_PROJECT_SECRET": SECRET, "DP_MAIB_SIGNATURE_KEY": SIGKEY}

    def result(self, pid: str) -> dict:
        """Что maib присылает на callback — поля «Final response» из «Direct payment»."""
        p = self.pays[pid]
        ok = p["status"] == "OK"
        return {"payId": pid, "orderId": p["body"].get("orderId"), "status": p["status"],
                "statusCode": "000" if ok else ("116" if p["status"] == "FAILED" else None),
                "statusMessage": "Approved" if ok else ("Declined" if p["status"] == "FAILED" else None),
                "threeDs": "AUTHENTICATED" if ok else None, "rrn": "123456789012" if ok else None,
                "approval": "ABC123" if ok else None, "cardNumber": "510218******1124" if ok else None,
                "amount": p["body"]["amount"], "currency": p["body"]["currency"]}

    def info(self, pid: str) -> dict:
        """pay-info: то же и что maib помнит из /pay; после возврата — refundAmount."""
        p = self.pays[pid]
        out = dict(self.result(pid), description=p["body"].get("description"),
                   clientIp=p["body"].get("clientIp"), email=p["body"].get("email"))
        if p["refunded"] is not None:
            out["refundAmount"] = p["refunded"]
        return out

    def set_status(self, pid: str, status: str) -> None:
        self.pays[pid]["status"] = status

    def rotate(self) -> None:
        """maib отозвал токен раньше expiresIn: старый получает 401, новый выдаст generate-token."""
        self.token_value = "tok-" + uuid.uuid4().hex[:8]

    def callback(self, pid: str, key: str = SIGKEY, **override) -> bytes:
        """Тело callback с подписью по примеру maib."""
        result = dict(self.result(pid), **override)
        return json.dumps({"result": result, "signature": _php_sign(result, key)}).encode("utf-8")

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
            res.ok("строка: card, payId и адрес страницы maib, ожидает",
                   p["method"] == "card" and p["provider_id"] in fake.pays
                   and p["pay_url"] == f"https://maib.ecommerce.md/checkout/{p['provider_id']}"
                   and p["status"] == "pending", dict(p))
            body = fake.bodies[-1]
            res.ok("maib получил: orderId = reference, сумма по тарифу, MDL, адреса callback/ok/fail под DP_BASE_URL",
                   body.get("orderId") == ref and body.get("amount") == float(config.PRICE_MONTH) and body.get("currency") == "MDL"
                   and body.get("callbackUrl") == "https://cloud.dentpilot.md" + CALLBACK
                   and body.get("okUrl") == "https://cloud.dentpilot.md/pay/ok"
                   and body.get("failUrl") == "https://cloud.dentpilot.md/pay/fail"
                   and body.get("clientIp") and body.get("email") == "card@example.md", body)
            res.check("токен взят один раз и переиспользован", fake.calls, {"token": 1, "pay": 1, "info": 0, "refund": 0})
            subj, text, _ = _letters(s)[-1]
            # 23.10: ссылка maib живёт 10 минут (maib.PAY_TTL) — письмо несёт страницу оплаты, не payUrl
            res.ok("письмо: карта — на странице оплаты (не ссылка maib), сумма, и перевод с тем же reference",
                   ref in subj and mail.CARD_NOTE in text and "/plata/" in text and p["pay_url"] not in text
                   and "MD00TEST0000000000000001" in text and f"Destinația plății: {ref}" in text, text[:400])
            res.ok("журнал: card_link с payId", any(p["provider_id"] in d[0] for d in
                                                     _sql(s, "SELECT detail FROM audit WHERE what='card_link'")))

            # 1. callback, который врёт «OK», пока сам maib ещё говорит CREATED: только сигнал
            r = c.post_raw(CALLBACK, fake.callback(p["provider_id"], status="OK", statusCode="000",
                                                   statusMessage="Approved"))
            res.ok("callback «OK» при pay-info CREATED — принят как сигнал, исход waiting",
                   r.status == 200 and json.loads(r.body).get("outcome") == "waiting", f"{r.status} {r.body}")
            res.check("платёж по-прежнему ожидает, файла нет",
                      (_payment(s, cid)["status"], _sql(s, "SELECT count(*) FROM issues")[0][0]), ("pending", 1))
            res.check("сервер спросил maib", fake.calls["info"], 1)

            # 2. maib подтверждает: продление, файл, письмо
            fake.set_status(p["provider_id"], "OK")
            n = len(_letters(s))
            r = c.post_raw(CALLBACK, fake.callback(p["provider_id"]))
            res.ok("успешный callback: 200, исход paid", r.status == 200 and json.loads(r.body).get("outcome") == "paid",
                   f"{r.status} {r.body}")
            p2 = _payment(s, cid)
            res.ok("платёж оплачен maib-ом, слова maib в строке",
                   p2["status"] == "paid" and p2["confirmed_by"] == "maib" and p2["provider_status"].startswith("OK"),
                   dict(p2))
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
            r = c.post_raw(CALLBACK, fake.callback(p["provider_id"]))
            res.ok("повторный callback: 200, исход already", r.status == 200
                   and json.loads(r.body).get("outcome") == "already", f"{r.status} {r.body}")
            res.check("второго продления нет: выдач две, писем столько же",
                      (_sql(s, "SELECT count(*) FROM issues")[0][0], len(_letters(s))), (2, n + 1))

            # 4. битые callback — 400, ничего
            for label, raw in (("подпись чужим ключом", fake.callback(p["provider_id"], key="wrong")),
                               ("подпись не ASCII", json.dumps({"result": fake.result(p["provider_id"]),
                                                                "signature": "ș"}).encode()),
                               ("не JSON", b"{oops"),
                               ("без result", json.dumps({"signature": "x"}).encode()),
                               ("result строкой", json.dumps({"result": "x", "signature": "y"}).encode())):
                r = c.post_raw(CALLBACK, raw)
                res.check(f"битый callback — {label}: 400", r.status, 400)

            # 5. чужой callback — платёж не наш, 404
            fake.pays["not-ours"] = {"body": {"orderId": "DP-2026-999999", "amount": 1.0, "currency": "MDL"},
                                     "status": "OK", "refunded": None}
            r = c.post_raw(CALLBACK, fake.callback("not-ours"))
            res.check("чужой callback с верной подписью: 404", r.status, 404)
            res.check("после битых и чужого — выдач по-прежнему две", _sql(s, "SELECT count(*) FROM issues")[0][0], 2)

            # 6. кнопка «Проверить» — тот же вопрос maib; не прошёл → ждёт дальше со словами maib
            r = c.post(f"/admin/clinics/{cid}/payments", months="12", amount="", send="", method="card")
            res.check("второй платёж картой, без письма", r.location, f"/admin/clinics/{cid}?msg=card_created")
            q = _payment(s, cid, 1)
            fake.set_status(q["provider_id"], "FAILED")
            r = c.post(f"/admin/payments/{q['id']}/check")
            res.check("проверить: не прошёл", r.location, f"/admin/clinics/{cid}?msg=card_failed")
            q2 = _payment(s, cid, 1)
            res.ok("остаётся в ожидании, слова maib записаны, журнал card_failed",
                   q2["status"] == "pending" and q2["provider_status"].startswith("FAILED")
                   and _sql(s, "SELECT count(*) FROM audit WHERE what='card_failed'")[0][0] == 1, dict(q2))
            res.ok("карточка показывает слова maib", "FAILED" in c.get(f"/admin/clinics/{cid}").body)
            # новая ссылка — новый payId, тот же reference
            r = c.post(f"/admin/payments/{q['id']}/link")
            res.check("новая ссылка создана и отправлена", r.location, f"/admin/clinics/{cid}?msg=card_link_mailed")
            q3 = _payment(s, cid, 1)
            res.ok("новый payId, адрес, слова maib стёрты, reference прежний",
                   q3["provider_id"] != q["provider_id"] and q3["provider_id"] in fake.pays
                   and q3["provider_status"] == "" and q3["reference"] == q["reference"], dict(q3))
            res.ok("письмо с нотой — страница оплаты, не ссылка maib",
                   "/plata/" in _letters(s)[-1][1] and q3["pay_url"] not in _letters(s)[-1][1])
            fake.set_status(q3["provider_id"], "OK")
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
            res.ok("перевод: без payId", not t["provider_id"] and t["method"] == "transfer")
            res.ok("у него кнопка «Ссылка на карту»", "Ссылка на карту" in c.get(f"/admin/clinics/{cid}").body)
            res.check("проверить платёж без ссылки — card_none", c.post(f"/admin/payments/{t['id']}/check").location,
                      f"/admin/clinics/{cid}?msg=card_none")
            r = c.post(f"/admin/payments/{t['id']}/link")
            res.ok("ссылка к переводу: платёж стал card, reference тот же",
                   r.location.endswith("msg=card_link_mailed") and _payment(s, cid, 2)["method"] == "card"
                   and _payment(s, cid, 2)["reference"] == t["reference"], r.location)

            # 7. страницы возврата — без слова «оплачено», с контактами
            ok = Client(s.url).get("/pay/ok")
            fail = Client(s.url).get("/pay/fail")
            res.ok("/pay/ok: спасибо, подтверждение письмом, без куки",
                   ok.status == 200 and "Mulțumim" in ok.body and "e-mail" in ok.body
                   and "set-cookie" not in ok.headers, ok.body[:200])
            res.ok("/pay/fail: не удалось, как ещё оплатить",
                   fail.status == 200 and "nu a reușit" in fail.body and "transfer bancar" in fail.body)

            out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                                 capture_output=True, text=True, encoding="utf-8")
            res.ok("check: maib отвечает, callback назван", "maib: токен получен" in out.stdout
                   and CALLBACK in out.stdout, out.stdout[-500:])
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
            fake.set_status(p["provider_id"], "OK")
            n = len(_letters(s))
            r = c.post_raw(CALLBACK, fake.callback(p["provider_id"]))
            res.ok("callback карты по закрытой ноте: paid (зачтено), а не already",
                   r.status == 200 and json.loads(r.body).get("outcome") == "paid", f"{r.status} {r.body}")
            old, new = _payment(s, cid, 0), _payment(s, cid, 1)
            res.ok("новая строка: новый reference, оплачена картой, payId переехал; у старой ссылки нет",
                   new["reference"] != old["reference"] and new["status"] == "paid" and new["paid_via"] == "card"
                   and new["provider_id"] == p["provider_id"] and old["provider_id"] is None, f"{dict(old)} {dict(new)}")
            res.check("срок: два периода по якорю — 28.02 и 31.03",
                      _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid)[0][0][:10], "2027-03-31")
            res.ok("письмо о лицензии ушло", len(_letters(s)) == n + 1 and "licența" in _letters(s)[-1][0].lower())
            res.check("журнал: payment_repeat", _sql(s, "SELECT count(*) FROM audit WHERE what='payment_repeat'")[0][0], 1)
            issues = _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0]
            r = c.post_raw(CALLBACK, fake.callback(p["provider_id"]))
            res.ok("повторный callback того же платежа: already, третьего периода нет",
                   json.loads(r.body).get("outcome") == "already"
                   and _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0] == issues, r.body)
            res.ok("в карточке зачтённая строка — «картой»", "картой" in c.get(f"/admin/clinics/{cid}").body)

            # 2. то же, но callback потерялся — зачитывает ежедневная задача
            cid2 = _clinic(c, name="Clinica Fără Callback", email="fara@example.md")
            c.post(f"/admin/clinics/{cid2}/issue", kind="dates", valid_until="2027-01-15", grace_days="14")
            q = card_note(cid2)
            c.post(f"/admin/payments/{q['id']}/confirm")
            fake.set_status(q["provider_id"], "OK")
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
            fake.set_status(t["provider_id"], "OK")
            r = c.post_raw(CALLBACK, fake.callback(t["provider_id"]))
            res.ok("карта по отклонённой ноте: зачтена, срок +1 месяц",
                   json.loads(r.body).get("outcome") == "paid"
                   and _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid3)[0][0][:10] == "2027-02-10",
                   r.body)

            # 4. оплаченная ЭТОЙ ЖЕ картой — по-прежнему already
            cid4 = _clinic(c, name="Clinica Card Simplu", email="simplu@example.md")
            c.post(f"/admin/clinics/{cid4}/issue", kind="dates", valid_until="2027-01-20", grace_days="14")
            u = card_note(cid4)
            fake.set_status(u["provider_id"], "OK")
            c.post_raw(CALLBACK, fake.callback(u["provider_id"]))
            r = c.post_raw(CALLBACK, fake.callback(u["provider_id"]))
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
            res.ok("платёж задачи без ссылки maib: та живёт 10 минут и рождается по клику",
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
            fake.set_status(p["provider_id"], "OK")
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
                   and "maib.ecommerce.md" not in text and f"Destinația plății: {p['reference']}" in text, out[-300:])
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


def suite_off(res: Result) -> None:
    """Без DP_MAIB_*: карт нет, всё остальное как в шаге 1."""
    with Server(env=BANK_ENV) as s:
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
        r = c.post_raw(CALLBACK, b'{"result": {"payId": "x"}, "signature": "y"}')
        res.check("callback без ключа подписи: 400", r.status, 400)
        out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                             capture_output=True, text=True, encoding="utf-8")
        res.ok("check: карты выключены — предупреждение", "DP_MAIB_* пусты" in out.stdout, out.stdout[-300:])


def suite_wire(res: Result) -> None:
    """Провод app/maib.py напрямую против документации maib (23.10.2026): образец
    подписи, поля /pay в пределах, pay-info без Content-Type, отозванный токен, 403,
    возврат денег."""
    res.check("пример PHP на стенде даёт строку документации", _php_string(DOC_RESULT, DOC_KEY), DOC_STRING)
    res.check("…и её подпись", _php_sign(DOC_RESULT, DOC_KEY), DOC_SIGNATURE)
    res.check("провод: подпись образца документации", maib.signature(DOC_RESULT, DOC_KEY), DOC_SIGNATURE)
    nested = {"payId": "p", "amount": 400.0, "ok": True, "no": False, "none": None, "currency": "MDL",
              "items": [{"name": f"n{i}", "price": 2.5, "id": str(i)} for i in range(12)], "empty": {}}
    res.check("провод = пример PHP на вложенном (список длиннее 10, true/false/null, целая сумма)",
              maib.signature(nested, DOC_KEY), _php_sign(nested, DOC_KEY))

    saved = {k: getattr(config, k) for k in ("MAIB_BASE_URL", "MAIB_PROJECT_ID", "MAIB_PROJECT_SECRET",
                                             "MAIB_SIGNATURE_KEY", "BASE_URL")}
    fake = FakeMaib()
    seen = _Records()
    wire_log = logging.getLogger("cloud.maib")
    wire_log.addHandler(seen)
    wire_log.propagate = False
    try:
        config.MAIB_SIGNATURE_KEY = DOC_KEY
        res.ok("signed: образец документации принят",
               maib.signed({"result": DOC_RESULT, "signature": DOC_SIGNATURE}) == DOC_RESULT and not seen.lines)
        res.ok("signed: подпись не ASCII — None, без исключения",
               maib.signed({"result": DOC_RESULT, "signature": "5wHkZvm9lFeXxSeFF0ui2CnAp7pCEFSNmuHYFYJlC0ș="}) is None)
        res.ok("signed: тот же образец чужим ключом — None",
               maib.signed({"result": DOC_RESULT, "signature": _php_sign(DOC_RESULT, "alt")}) is None)
        res.ok("несошедшаяся подпись в логе: ключи и сумма, без ключа подписи",
               len(seen.lines) == 2 and "amount,approval,cardNumber" in seen.lines[-1] and "10.25" in seen.lines[-1]
               and DOC_KEY not in seen.lines[-1], seen.lines)

        config.MAIB_BASE_URL, config.MAIB_PROJECT_ID = fake.url + "/v1", PROJECT
        config.MAIB_PROJECT_SECRET, config.BASE_URL = SECRET, "https://cloud.dentpilot.md"
        maib._token.update(value="", until=0.0)
        pid, url = maib.create(400, "DP-2026-000001", "DentPilot DP-2026-000001: " + "Clinica Ștefan Vodă " * 10,
                               "x" * 30 + "@example.md", "2a02:2f0e:5b0d:a700:1c4e:8f2a:3b9d:12ef")
        body = fake.bodies[-1]
        res.ok("create: maib принял, payId и payUrl", pid in fake.pays and url.startswith("https://"), body)
        res.ok("длинный IPv6 → 127.0.0.1, описание ≤ 124 байт без разрезанной буквы, длинный e-mail опущен",
               body["clientIp"] == "127.0.0.1" and len(body["description"].encode("utf-8")) <= 124
               and "�" not in body["description"] and "email" not in body, body)
        maib.create(400, "DP-2026-000002", "DentPilot", "clinica@example.md", "::ffff:93.115.12.7")
        res.ok("IPv4 в обёртке IPv6 → его IPv4, нормальный e-mail передан",
               fake.bodies[-1]["clientIp"] == "93.115.12.7" and fake.bodies[-1]["email"] == "clinica@example.md",
               fake.bodies[-1])
        maib.create(400, "DP-2026-000003", "DentPilot", "не адрес", "?")
        res.ok("«?» вместо адреса → 127.0.0.1, кривой e-mail опущен",
               fake.bodies[-1]["clientIp"] == "127.0.0.1" and "email" not in fake.bodies[-1], fake.bodies[-1])
        try:
            maib._authed("POST", "/pay", dict(fake.bodies[-1], clientIp="2a02:2f0e:5b0d:a700:1c4e:8f2a:3b9d:12ef"))
            res.ok("стенд отказывает в поле не по документации", False)
        except maib.MaibError as e:
            res.ok("стенд отказывает в поле не по документации: HTTP 400, 12001 clientIp",
                   e.http == 400 and "12001" in str(e) and "clientIp" in str(e), str(e))

        res.check("pay-info без Content-Type: стенд отвечает", maib.info(pid)["status"], "CREATED")
        try:
            maib._call("GET", f"/pay-info/{pid}", {}, bearer=maib.token())
            res.ok("pay-info с Content-Type стенд не принимает", False)
        except maib.MaibError as e:
            res.check("pay-info с Content-Type стенд не принимает", e.http, 415)
        res.check("токен до сих пор один", fake.calls["token"], 1)
        fake.rotate()
        res.check("отозванный токен: 401 → один раз новый, ответ есть", maib.info(pid)["payId"], pid)
        res.check("токен взят второй раз", fake.calls["token"], 2)

        try:
            maib.refund(pid)
            res.ok("возврат неоплаченного — ошибка", False)
        except maib.MaibError as e:
            res.ok("возврат неоплаченного — ошибка maib", e.http == 400, str(e))
        fake.set_status(pid, "OK")
        r = maib.refund(pid)
        res.ok("полный возврат: OK, сумма платежа, без refundAmount в запросе",
               r["status"] == "OK" and r["refundAmount"] == 400.0, r)
        res.check("pay-info помнит возврат", maib.info(pid).get("refundAmount"), 400.0)
        res.check("второй возврат того же платежа: REVERSED, не ошибка", maib.refund(pid)["status"], "REVERSED")
        pid2, _ = maib.create(600, "DP-2026-000004", "DentPilot")
        fake.set_status(pid2, "OK")
        res.check("частичный возврат: refundAmount уходит числом", maib.refund(pid2, 150)["refundAmount"], 150.0)
        try:
            maib.refund("f16a9006-0000-0000-0000-000000000000")
            res.ok("возврат чужого payId — ошибка", False)
        except maib.MaibError as e:
            res.ok("возврат чужого payId — HTTP 404, код и текст maib", e.http == 404 and "13002" in str(e), str(e))

        fake.forbid = True
        maib._token.update(value="", until=0.0)
        try:
            maib.token()
            res.ok("403: не с IP проекта", False)
        except maib.MaibError as e:
            res.ok("403: подсказка про IP проекта в maibmerchants", e.http == 403 and "IP проекта" in str(e), str(e))
    finally:
        for k, v in saved.items():
            setattr(config, k, v)
        maib._token.update(value="", until=0.0)
        wire_log.removeHandler(seen)
        wire_log.propagate = True
        fake.close()
