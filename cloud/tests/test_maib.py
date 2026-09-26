"""Оплата картой через maib (L12): ссылка, callback, статус, ежедневная задача.

maib здесь — СТЕНД в процессе теста (http.server), и это единственное место,
где он существует: прод знает один адрес, DP_MAIB_BASE_URL. Стенд говорит
теми же именами, что документация maib ecommerce API v2 (generate-token, pay,
pay-info, callback с подписью), и подписывает callback своей, независимой
записью того же правила — так проверяется, что провод сервера понимает
документированную форму, а не сам себя.

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
import json
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

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}
PROJECT, SECRET, SIGKEY = "proj-test", "secret-test", "signature-key-test"
CALLBACK = "/v1/maib/callback"
D = timedelta(days=1)


def _as_text(v) -> str:
    """Правило подписи maib, записанное здесь независимо от app/maib.py."""
    if v is None or v is False:
        return ""
    if v is True:
        return "1"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class FakeMaib:
    """Стенд maib: токен по проекту, платёж с payUrl, pay-info со статусом, который ставит тест."""

    def __init__(self):
        self.calls = {"token": 0, "pay": 0, "info": 0}
        self.pays: dict[str, dict] = {}
        self.bodies: list[dict] = []
        self.token_value = "tok-" + uuid.uuid4().hex[:8]
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _json(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self) -> bool:
                return self.headers.get("Authorization") == f"Bearer {fake.token_value}"

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/v1/generate-token":
                    fake.calls["token"] += 1
                    if (body.get("projectId"), body.get("projectSecret")) != (PROJECT, SECRET):
                        return self._json(401, {"ok": False, "errors": [{"errorCode": "401",
                                                                          "errorMessage": "Unauthorized"}]})
                    return self._json(200, {"ok": True, "result": {
                        "accessToken": fake.token_value, "expiresIn": 300, "refreshToken": "r",
                        "refreshExpiresIn": 1800, "tokenType": "Bearer"}})
                if self.path == "/v1/pay":
                    if not self._authed():
                        return self._json(401, {"ok": False, "errors": [{"errorMessage": "Unauthorized"}]})
                    fake.calls["pay"] += 1
                    fake.bodies.append(body)
                    pid = str(uuid.uuid4())
                    fake.pays[pid] = {"orderId": body.get("orderId"), "amount": body.get("amount"),
                                      "currency": body.get("currency"), "status": "CREATED"}
                    return self._json(200, {"ok": True, "result": {
                        "payId": pid, "orderId": body.get("orderId"),
                        "payUrl": f"https://maib.ecommerce.md/checkout/{pid}"}})
                self._json(404, {"ok": False, "errors": [{"errorMessage": "Not found"}]})

            def do_GET(self):
                if self.path.startswith("/v1/pay-info/"):
                    if not self._authed():
                        return self._json(401, {"ok": False, "errors": [{"errorMessage": "Unauthorized"}]})
                    fake.calls["info"] += 1
                    pid = self.path.rsplit("/", 1)[1]
                    if pid not in fake.pays:
                        return self._json(404, {"ok": False, "errors": [{"errorMessage": "Payment not found"}]})
                    return self._json(200, {"ok": True, "result": fake.result(pid)})
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
        """Что maib рассказывает о платеже — в pay-info и в callback."""
        p = self.pays[pid]
        ok = p["status"] == "OK"
        return {"payId": pid, "orderId": p["orderId"], "status": p["status"],
                "statusCode": "000" if ok else ("116" if p["status"] == "FAILED" else None),
                "statusMessage": "Approved" if ok else ("Declined" if p["status"] == "FAILED" else None),
                "amount": p["amount"], "currency": p["currency"],
                "threeDs": "AUTHENTICATED" if ok else None, "rrn": "123456789012" if ok else None,
                "approval": "ABC123" if ok else None, "cardNumber": "510218******0027" if ok else None,
                "paymentDate": "2026-09-25 12:00:00" if ok else None}

    def set_status(self, pid: str, status: str) -> None:
        self.pays[pid]["status"] = status

    def callback(self, pid: str, key: str = SIGKEY, **override) -> bytes:
        """Тело callback с подписью по документированному правилу."""
        result = dict(self.result(pid), **override)
        raw = ":".join(_as_text(result[k]) for k in sorted(result)) + ":" + key
        sig = base64.b64encode(hashlib.sha256(raw.encode("utf-8")).digest()).decode("ascii")
        return json.dumps({"result": result, "signature": sig}).encode("utf-8")

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
                   body.get("orderId") == ref and body.get("amount") == 399.0 and body.get("currency") == "MDL"
                   and body.get("callbackUrl") == "https://cloud.dentpilot.md" + CALLBACK
                   and body.get("okUrl") == "https://cloud.dentpilot.md/pay/ok"
                   and body.get("failUrl") == "https://cloud.dentpilot.md/pay/fail"
                   and body.get("clientIp") and body.get("email") == "card@example.md", body)
            res.check("токен взят один раз и переиспользован", fake.calls, {"token": 1, "pay": 1, "info": 0})
            subj, text, _ = _letters(s)[-1]
            res.ok("письмо: ссылка на карту, сумма, и перевод с тем же reference",
                   ref in subj and mail.CARD_NOTE in text and p["pay_url"] in text
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
            res.ok("письмо с файлом ушло", len(letters) == n + 1 and letters[-1][2], repr(letters[-1][:2]))
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
                               ("не JSON", b"{oops"),
                               ("без result", json.dumps({"signature": "x"}).encode()),
                               ("result строкой", json.dumps({"result": "x", "signature": "y"}).encode())):
                r = c.post_raw(CALLBACK, raw)
                res.check(f"битый callback — {label}: 400", r.status, 400)

            # 5. чужой callback — платёж не наш, 404
            fake.pays["not-ours"] = {"orderId": "DP-2026-999999", "amount": 1.0, "currency": "MDL", "status": "OK"}
            r = c.post_raw(CALLBACK, fake.callback("not-ours"))
            res.check("чужой callback с верной подписью: 404", r.status, 404)
            res.check("после битых и чужого — выдач по-прежнему две", _sql(s, "SELECT count(*) FROM issues")[0][0], 2)

            # 6. кнопка «Проверить» — тот же вопрос maib; не прошёл → ждёт дальше со словами maib
            r = c.post(f"/admin/clinics/{cid}/payments", months="3", amount="", send="", method="card")
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
            res.ok("письмо с новой ссылкой", q3["pay_url"] in _letters(s)[-1][1])
            fake.set_status(q3["provider_id"], "OK")
            r = c.post(f"/admin/payments/{q['id']}/check")
            res.check("проверить: оплачен", r.location, f"/admin/clinics/{cid}?msg=card_paid")
            res.ok("третий файл выдан, письмо с ним ушло",
                   _sql(s, "SELECT count(*) FROM issues")[0][0] == 3 and _letters(s)[-1][2])
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


def suite_daily(res: Result) -> None:
    """Ежедневная задача с maib: ссылка в счёте, оплата картой замечена без callback."""
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
            res.ok("платёж задачи получил ссылку maib до письма",
                   p["method"] == "card" and p["provider_id"] in fake.pays and fake.calls["pay"] == 1, dict(p))
            subj, text, _ = _letters(s)[0]
            res.ok("счёт: ссылка на карту и перевод с reference",
                   p["pay_url"] in text and f"Destinația plății: {p['reference']}" in text, text[:400])
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
                   and _letters(s)[-1][2], dict(p2))
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
