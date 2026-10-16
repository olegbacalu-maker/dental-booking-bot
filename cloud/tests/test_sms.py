"""SMS-пакет на сервере (S3): отправка без дубля, остаток, уведомление, ежедневная задача.

sms.md здесь — СТЕНД в процессе теста (http.server), единственное место, где он
существует: прод знает один адрес, DP_SMSMD_BASE_URL. Стенд говорит именами
спецификации docs.sms.md v3 (конверт status/httpCode/data, X-Api-Token,
POST /messages → id и segments, GET /messages с фильтрами, GET /messages/{id},
/account/balance, /sender-aliases) и умеет ломаться так, как ломается
настоящий: молчать, приняв сообщение («lost»), молчать, не приняв («drop»),
отказывать 422/429/402.

Главное из sms.md › «Сервер»: списание ДО вызова sms.md; повтор с тем же ключом —
одна SMS и одно списание; молчание → поиск по номеру, имени и времени, без
второй SMS; отказ по существу и 10/11 — возврат, 9 — нет; уведомление — только
сигнал, состояние перепроверяется запросом; номера и текста нет ни в базе, ни
в логе.
"""
import email
import email.policy
import http.server
import json
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone

from harness import CLOUD, Client, Result, Server, cid_from

sys.path.insert(0, str(CLOUD))
from app import sms, smsmd  # noqa: E402

TOKEN, DLR_SECRET = "smsmd-token-test", "dlr-secret-test"
BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}
PHONE, DIGITS = "+373 69 123 456", "69123456"       # известный номер прогона: его цифр не должно остаться
TEXT = "Buna ziua! Clinica Test va reaminteste ca maine, 17.10, la ora 12:00 aveti o programare la noi."
D = timedelta(days=1)
# Переходы времени Кишинёва 2025–2027 из tzdata 2026c (UTC): правило EET/EEST без tzdata
TRANSITIONS = [("2025-03-30T01:00:00", 3), ("2025-10-26T01:00:00", 2), ("2026-03-29T01:00:00", 3),
               ("2026-10-25T01:00:00", 2), ("2027-03-28T01:00:00", 3), ("2027-10-31T01:00:00", 2)]


def _count(text: str) -> int:
    """Счёт сегментов стенда — независимая, грубая запись правила (ASCII = GSM-7)."""
    if text.isascii():
        return 1 if len(text) <= 160 else -(-len(text) // 153)
    return 1 if len(text) <= 70 else -(-len(text) // 67)


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class FakeSmsMd:
    """Стенд sms.md: сообщения, статусы, баланс, имена; режим поломки ставит тест."""

    STATUS = {1: "Queued", 2: "Sent", 3: "Delivered", 8: "Unknown", 9: "Undelivered", 10: "Failed", 11: "Rejected"}

    def __init__(self):
        self.calls = {"send": 0, "list": 0, "message": 0, "balance": 0, "aliases": 0}
        self.msgs: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.mode = "ok"                 # ok | lost | drop | 422 | 429 | 402 | 500
        self.segments_override = None
        self.balance = "500.00"
        self.aliases: dict[str, int] = {"DentPilot": 1}
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _json(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _err(self, status: int, code: str, errors: dict | None = None) -> None:
                body = {"status": "error", "httpCode": status, "code": code, "message": "An error occurred."}
                if errors:
                    body["errors"] = errors
                self._json(status, body)

            def _ok(self, data, meta: dict | None = None) -> None:
                body = {"status": "success", "httpCode": 200, "data": data}
                if meta is not None:
                    body["meta"] = meta
                self._json(200, body)

            def _authed(self) -> bool:
                if self.headers.get("X-Api-Token") == TOKEN:
                    return True
                self._err(401, "INVALID_API_TOKEN")
                return False

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path != "/v3/messages":
                    return self._err(404, "NOT_FOUND")
                if not self._authed():
                    return
                fake.calls["send"] += 1
                if fake.mode == "drop":
                    self.close_connection = True
                    return
                if fake.mode == "500":
                    return self._err(500, "INTERNAL_ERROR")
                if fake.mode == "422":
                    return self._err(422, "VALIDATION_ERROR", {"to": ["The to field is invalid."]})
                if fake.mode == "429":
                    return self._err(429, "RATE_LIMIT_EXCEEDED")
                if fake.mode == "402":
                    return self._err(402, "INSUFFICIENT_BALANCE")
                pid = str(uuid.uuid4())
                segs = fake.segments_override or _count(body.get("text") or "")
                fake.msgs[pid] = {"from": body.get("from"), "to": body.get("to"), "text": body.get("text"),
                                  "status": 1, "segments": segs,
                                  "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
                fake.sent.append(dict(fake.msgs[pid], id=pid))
                if fake.mode == "lost":
                    self.close_connection = True
                    return
                self._ok({"message": "Message has been queued successfully.", "id": pid,
                          "scheduledAt": "2026-10-16 12:00:00", "to": body.get("to"), "text": body.get("text"),
                          "characters": len(body.get("text") or ""), "segments": segs, "encoding": "gsm-7",
                          "cost": f"{0.30 * segs:.2f}", "currency": "MDL", "destination": "moldova",
                          "countryIso": "MD", "countryName": "Moldova"})

            def _message(self, pid: str, m: dict) -> dict:
                return {"id": pid, "senderName": m["from"], "receiverNumber": m["to"], "text": m["text"],
                        "smsCount": m["segments"], "messageId": "sms_x", "externalId": None,
                        "carrier": {"id": 1, "name": "Moldcell"}, "source": {"id": 2, "name": "API"},
                        "status": {"id": m["status"], "name": fake.STATUS.get(m["status"], "?")},
                        "dateCreated": m["created"], "dateUpdated": None, "dateToSend": None, "dateSent": None}

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                if not self._authed():
                    return
                if u.path == "/v3/messages":
                    fake.calls["list"] += 1
                    rows = [self._message(pid, m) for pid, m in reversed(list(fake.msgs.items()))
                            if m["to"] == q.get("receiverNumber") and m["from"] == q.get("senderName")]
                    return self._ok(rows, {"currentPage": 1, "lastPage": 1 if rows else 0,
                                           "totalItems": len(rows), "perPage": 15})
                if u.path.startswith("/v3/messages/"):
                    fake.calls["message"] += 1
                    pid = u.path.rsplit("/", 1)[1]
                    if pid not in fake.msgs:
                        return self._err(404, "NOT_FOUND")
                    return self._ok(self._message(pid, fake.msgs[pid]))
                if u.path == "/v3/account/balance":
                    fake.calls["balance"] += 1
                    return self._ok({"balance": fake.balance, "currency": "MDL"})
                if u.path == "/v3/sender-aliases":
                    fake.calls["aliases"] += 1
                    rows = [{"id": str(uuid.uuid4()), "name": n, "status": {"id": st, "name": "x"},
                             "dateCreated": "2026-10-01T00:00:00+00:00", "dateUpdated": None}
                            for n, st in fake.aliases.items()]
                    return self._ok(rows, {"currentPage": 1, "lastPage": 1, "totalItems": len(rows), "perPage": 16})
                self._err(404, "NOT_FOUND")

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def env(self, **extra) -> dict:
        # цены — тестовые: настоящие живут только в cloud.env Олега
        e = {"DP_SMSMD_TOKEN": TOKEN, "DP_SMSMD_BASE_URL": self.url + "/v3", "DP_SMSMD_DLR_SECRET": DLR_SECRET,
             "DP_SMS_PACKS": "100:50,500:200", "DP_SMS_NAME_PRICE": "77", "DP_SMS_QUIET": "0-0",
             "DP_TRIAL_NOTIFY": "oleg@example.md", "DP_SMS_OFFERED": "1", **BANK_ENV}
        e.update(extra)
        return e

    def set_status(self, pid: str, status: int) -> None:
        self.msgs[pid]["status"] = status

    def dlr(self, pid: str, status: int) -> bytes:
        m = self.msgs.get(pid) or {"to": "37369000000", "text": "x"}
        return json.dumps({"id": pid, "phone": "373" + str(m["to"]), "text": m["text"], "status_id": status,
                           "status_name": self.STATUS.get(status, "?"),
                           "date_created": "2026-10-16 12:00:00"}).encode()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


# ---------- помощники ----------


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def _one(s: Server, sql: str, *args):
    rows = _sql(s, sql, *args)
    return rows[0][0] if rows else None


def _dump(s: Server) -> str:
    """Вся база словами (данные включая -wal): для сторожа «номера нет»."""
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return "\n".join(con.iterdump())
    finally:
        con.close()


def _letters(s: Server) -> list[tuple[str, str, str]]:
    out = []
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        # длинная тема сворачивается в заголовке и при разборе получает двойной пробел — не дефект письма
        out.append((m["To"], " ".join(m["Subject"].split()), m.get_body(preferencelist=("plain",)).get_content()))
    return out


def _clinic_with_license(admin: Client, s: Server, name: str = "Clinica Test", email_: str = "sms@example.md") -> tuple[str, str]:
    """Клиника с абонементом на 60 дней → (cid, токен программы)."""
    cid = cid_from(admin.post("/admin/clinics", name=name, idno="1234567890123", contact_name="Ion",
                              email=email_, phone="").location)
    v = datetime.now(timezone.utc).date() + 60 * D
    admin.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")
    return cid, _one(s, "SELECT renew_token FROM clinics WHERE id=?", cid)


class Program:
    """Клиент программы: JSON с Bearer-токеном."""

    def __init__(self, base: str, token: str):
        self.c, self.token = Client(base), token

    def _h(self) -> dict:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                "User-Agent": "DentPilot/1.43.0", "X-DentPilot-Device": "d_0123456789ab"}

    def get(self, path: str):
        r = self.c.get(path, headers=self._h())
        return r.status, json.loads(r.body or "{}")

    def post(self, path: str, **body):
        r = self.c._do(path, json.dumps(body).encode(), self._h())
        return r.status, json.loads(r.body or "{}")

    def send(self, idem: str, to: str = PHONE, text: str = TEXT, kind: str = "day_before"):
        return self.post("/v1/sms/send", to=to, text=text, kind=kind, idem=idem)


def _run_daily(s: Server, at: datetime | None = None) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "app.jobs", "daily"]
    if at:
        cmd += ["--at", at.strftime("%Y-%m-%dT%H:%M:%SZ")]
    p = subprocess.run(cmd, cwd=str(CLOUD), env=s.env, capture_output=True, text=True, encoding="utf-8", timeout=90)
    return p.returncode, p.stdout + p.stderr


def _wait(pred, seconds: float = 8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < seconds:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


def _state(s: Server, mid: int) -> str:
    return _one(s, "SELECT state FROM sms_messages WHERE id=?", mid)


def _bal(s: Server, cid: str) -> int:
    return _one(s, "SELECT COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=?", cid)


# ---------- наборы ----------


def suite_rules(res: Result) -> None:
    """Чистые правила: время Кишинёва без tzdata, тихие часы, имя, разбор уведомления, копейки."""
    for ts, off in TRANSITIONS:
        at = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        before = sms.utc_offset(at - timedelta(minutes=1))
        res.ok(f"переход {ts}: сдвиг {off} с момента перехода, до него другой",
               sms.utc_offset(at) == off and before != off, f"{before} → {sms.utc_offset(at)}")
    res.check("23:30 по Кишинёву зимой — тот же день по местным часам",
              sms.local(datetime(2026, 1, 10, 21, 30, tzinfo=timezone.utc)).isoformat(), "2026-01-10T23:30:00")
    res.check("00:30 по Кишинёву летом = 21:30 UTC накануне",
              sms.local(datetime(2026, 7, 10, 21, 30, tzinfo=timezone.utc)).isoformat(), "2026-07-11T00:30:00")
    res.check("полночь 11.07 по Кишинёву — 21:00 UTC 10.07",
              sms.day_start(date(2026, 7, 11)).isoformat(), "2026-07-10T21:00:00+00:00")
    res.check("полночь 10.01 по Кишинёву — 22:00 UTC 09.01",
              sms.day_start(date(2026, 1, 10)).isoformat(), "2026-01-09T22:00:00+00:00")
    import app.config as cfg
    saved = cfg.SMS_QUIET
    try:
        cfg.SMS_QUIET = "21-8"
        res.ok("тихие часы 21–8: 22:00 и 07:59 тихо, 08:00 и 20:59 — нет",
               sms.quiet(datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc)) and sms.quiet(datetime(2026, 1, 10, 5, 59, tzinfo=timezone.utc))
               and not sms.quiet(datetime(2026, 1, 10, 6, 0, tzinfo=timezone.utc)) and not sms.quiet(datetime(2026, 1, 10, 18, 59, tzinfo=timezone.utc)))
        cfg.SMS_QUIET = "0-0"
        res.ok("равные границы — окна нет", not sms.quiet(datetime(2026, 1, 10, 22, 0, tzinfo=timezone.utc)))
        cfg.SMS_QUIET = "мусор"
        res.check("кривое значение — умолчание 21–8", sms.quiet_window(), (21, 8))
    finally:
        cfg.SMS_QUIET = saved
    res.check("имя из названия: без диакритики, до 11 знаков", sms.suggest("Zâmbet Dent Chișinău"), "Zambet Dent")
    res.ok("имя: латиница/цифры/пробел/точка/тире до 11, хоть одна буква",
           sms.SENDER_RE.match("Zambet Dent") and sms.SENDER_RE.match("Dr.Pop-2") and not sms.SENDER_RE.match("12345678")
           and not sms.SENDER_RE.match("Prea Lung Nume") and not sms.SENDER_RE.match("Zâmbet") and not sms.SENDER_RE.match(""))
    res.check("уведомление: id и status_id, остальное не читается",
              smsmd.dlr(b'{"id":"abc","phone":"37369123456","text":"x","status_id":3}'), ("abc", 3))
    res.ok("уведомление: мусор, без id, без status_id — None",
           smsmd.dlr(b"xx") is None and smsmd.dlr(b'{"status_id":3}') is None and smsmd.dlr(b'{"id":"a"}') is None)
    res.ok("копейки без float: 123.45 → 12345, 7 → 700, мусор — None",
           sms._cents("123.45") == 12345 and sms._cents("7") == 700 and sms._cents("1,5") == 150 and sms._cents("x") is None)
    res.ok("сгорание: остаток минус начисленное после, в пределах пакета",
           sms.expired_part(80, 50, 100) == 30 and sms.expired_part(300, 50, 100) == 100 and sms.expired_part(20, 50, 100) == 0)
    res.ok("коды ответов программе: каждый с HTTP и румынским текстом",
           all(isinstance(v[0], int) and v[1] for v in sms.CODES.values())
           and sms.CODES["sms_balance"][0] == 402 and sms.CODES["sms_off"][0] == 423 and sms.CODES["sms_cap"][0] == 429)
    res.check("состояния: одно имя — одна группа сводки", set(sms.GROUP), set(sms.STATES))
    res.check("возврат — только где sms.md денег не взял: отказ, не сейчас, 10, 11",
              sms.REFUNDED, {sms.RETRY, sms.REFUSED, sms.FAILED, sms.REJECTED})


def suite_send(res: Result) -> None:
    """Отправка: план, имя, пакет через ноту, повтор без дубля, молчание и поиск, отказы, потолок, статусы."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid = cid_from(admin.post("/admin/clinics", name="Clinica Test", idno="1234567890123",
                                      contact_name="Ion", email="sms@example.md", phone="").location)
            token0 = _one(s, "SELECT renew_token FROM clinics WHERE id=?", cid)
            res.ok("без выдачи у клиники нет токена — программе нечем спрашивать", not token0)
            v = datetime.now(timezone.utc).date() + 60 * D
            admin.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")
            token = _one(s, "SELECT renew_token FROM clinics WHERE id=?", cid)
            prog = Program(s.url, token)
            res.check("чужой токен — 401", Program(s.url, "nope").get("/v1/sms/account")[0], 401)
            st, acc = prog.get("/v1/sms/account")
            res.ok("счёт: предложен, включён, имени нет — от DentPilot, остаток 0 (абонемент, не пробный), "
                   "пакеты и цена имени из окружения, не заблокировано",
                   st == 200 and acc["offered"] and acc["enabled"] and acc["sender_state"] == "none" and acc["balance"] == 0
                   and acc["packs"] == [{"units": 100, "price": 50}, {"units": 500, "price": 200}]
                   and acc["name_price"] == 77 and acc["blocked"] == "" and acc["from"] == "DentPilot", acc)
            st, r = prog.send("appt:1:day_before:2026-10-17T12:00")
            res.ok("остаток 0 — 402 sms_balance, sms.md не звали",
                   st == 402 and r["code"] == "sms_balance" and r["balance"] == 0 and fake.calls["send"] == 0)
            # заявка на имя из программы
            st, r = prog.post("/v1/sms/sender", name="Prea Lung Nume")
            res.ok("имя длиннее 11 — 400 sms_name", st == 400 and r["code"] == "sms_name")
            st, r = prog.post("/v1/sms/order", name=1)
            res.ok("год имени без заявки на имя — 409 sms_name_none", st == 409 and r["code"] == "sms_name_none")
            st, r = prog.post("/v1/sms/sender", name="Clinica T")
            res.ok("заявка на имя: requested, в журнале sms_sender, SMS пока от DentPilot",
                   st == 200 and r["sender"] == "Clinica T" and r["sender_state"] == "requested" and r["from"] == "DentPilot"
                   and _one(s, "SELECT count(*) FROM audit WHERE what='sms_sender' AND clinic_id=?", cid) == 1, r)
            # год имени: нота kind=sms_name, подтверждение — год ждёт одобрения (prepaid)
            st, r = prog.post("/v1/sms/order", name=1)
            res.ok("нота за год имени: kind sms_name, 77 MDL", st == 200 and r["created"] and r["kind"] == "sms_name"
                   and r["amount"] == 77 and r["units"] is None, r)
            nref = r["reference"]
            res.ok("письмо с нотой за имя: «Clinica T», год с одобрения",
                   nref in _letters(s)[-1][1] and "Clinica T" in _letters(s)[-1][1] and "aprobă numele" in _letters(s)[-1][2])
            npid = _one(s, "SELECT id FROM payments WHERE reference=?", nref)
            admin.post(f"/admin/payments/{npid}/confirm")
            res.ok("имя оплачено до одобрения — prepaid 1, until пуст, письмо «este plătit» без даты",
                   _sql(s, "SELECT sender_prepaid, sender_until FROM sms_accounts WHERE clinic_id=?", cid) == [(1, None)]
                   and "este plătit" in _letters(s)[-1][1] and "aprobă numele" in _letters(s)[-1][2]
                   and _one(s, "SELECT count(*) FROM audit WHERE what='sms_name'") == 1,
                   repr((_sql(s, "SELECT sender_prepaid, sender_until FROM sms_accounts WHERE clinic_id=?", cid),
                         _letters(s)[-1][:2], _one(s, "SELECT count(*) FROM audit WHERE what='sms_name'"))))
            # имя одобрено (сверку делает задача — suite_daily); здесь — состояние руками, год начался
            until = (datetime.now(timezone.utc) + 365 * D).strftime("%Y-%m-%dT%H:%M:%SZ")
            _sql(s, "UPDATE sms_accounts SET sender_state='active', sender_live='Clinica T', sender_until=?, "
                    "sender_prepaid=0 WHERE clinic_id=?", until, cid)
            st, acc = prog.get("/v1/sms/account")
            res.ok("имя одобрено и оплачено — SMS от имени клиники", acc["from"] == "Clinica T" and acc["sender_until"] == until)
            # пакет: нота из программы → письмо → подтверждение админом → начисление
            st, r = prog.post("/v1/sms/order", pack=250)
            res.ok("пакета 250 нет — 400 sms_pack с пакетами", st == 400 and r["code"] == "sms_pack" and r["packs"])
            st, r = prog.post("/v1/sms/order", pack=100)
            res.ok("нота за пакет 100: reference, 50 MDL, создана", st == 200 and r["created"] and r["amount"] == 50
                   and r["units"] == 100 and r["reference"].startswith("DP-"), r)
            ref = r["reference"]
            st, r2 = prog.post("/v1/sms/order", pack=500)
            res.ok("вторая нота за пакет не плодится — та же", st == 200 and not r2["created"] and r2["reference"] == ref)
            letters = _letters(s)
            res.ok("письмо с нотой за пакет: reference, 100 SMS, реквизиты",
                   letters and letters[-1][0] == "sms@example.md" and ref in letters[-1][1] and "100 SMS" in letters[-1][1]
                   and "MD00TEST0000000000000001" in letters[-1][2], letters[-1][:2] if letters else "нет писем")
            pid = _one(s, "SELECT id FROM payments WHERE reference=?", ref)
            res.check("платёж вида sms с 100 единицами, months 0",
                      _sql(s, "SELECT kind, sms_units, months, status FROM payments WHERE id=?", pid), [("sms", 100, 0, "pending")])
            issues = _one(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)
            r = admin.post(f"/admin/payments/{pid}/confirm")
            res.check("подтверждение — payment_confirmed_mailed", r.location, f"/admin/clinics/{cid}?msg=payment_confirmed_mailed")
            res.ok("пакет начислен: +100 строкой pack, файлов лицензии не прибавилось, журнал sms_pack",
                   _bal(s, cid) == 100 and _one(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid) == issues
                   and _sql(s, "SELECT reason, delta, payment_id FROM sms_ledger WHERE clinic_id=?", cid) == [("pack", 100, pid)]
                   and _one(s, "SELECT count(*) FROM audit WHERE what='sms_pack'") == 1)
            res.ok("письмо «pachetul SMS a fost activat» с остатком 100",
                   "pachetul SMS a fost activat" in _letters(s)[-1][1] and "Soldul actual: 100 SMS" in _letters(s)[-1][2])
            res.check("второе подтверждение — не в ожидании", admin.post(f"/admin/payments/{pid}/confirm").location,
                      f"/admin/clinics/{cid}?msg=payment_not_pending")
            # отправка
            st, r = prog.send("appt:1:day_before:2026-10-17T12:00")
            res.ok("отправлено: 200, 1 сегмент, остаток 99, состояние queued",
                   st == 200 and r["ok"] and r["segments"] == 1 and r["balance"] == 99 and r["state"] == "queued", r)
            mid1 = r["id"]
            res.ok("sms.md получил: от имени клиники, восемь цифр, текст как есть",
                   fake.sent[-1]["from"] == "Clinica T" and fake.sent[-1]["to"] == DIGITS and fake.sent[-1]["text"] == TEXT)
            st, r = prog.send("appt:1:day_before:2026-10-17T12:00")
            res.ok("повтор с тем же ключом — тот же ответ, одна SMS, одно списание",
                   st == 200 and r["id"] == mid1 and r["balance"] == 99 and fake.calls["send"] == 1, r)
            st, r = prog.send("appt:2:day_before:2026-10-17T12:00", to="77 123 456")
            res.ok("77… — 400 sms_phone left_bank", st == 400 and r["code"] == "sms_phone" and r["reason"] == "left_bank")
            st, r = prog.send("appt:3:x", text="")
            res.ok("пустой текст — sms_text", st == 400 and r["code"] == "sms_text")
            st, r = prog.send("appt:3:x", text="a" * 500)
            res.ok("4 сегмента — sms_text", st == 400 and r["code"] == "sms_text" and r["segments"] == 4)
            st, r = prog.send("appt:3:x", kind="promo")
            res.ok("чужой вид — sms_kind", st == 400 and r["code"] == "sms_kind")
            st, r = prog.send("не ключ")
            res.ok("кривой ключ — sms_idem", st == 400 and r["code"] == "sms_idem")
            res.check("ничего из отказанного sms.md не видел", fake.calls["send"], 1)
            # молчание sms.md, сообщение принято им: поиск, а не вторая SMS
            fake.mode = "lost"
            st, r = prog.send("appt:4:day_before:2026-10-18T10:00")
            mid4 = r["id"]
            res.ok("sms.md молчит — 503 sms_retry, списано, состояние unanswered",
                   st == 503 and r["code"] == "sms_retry" and _state(s, mid4) == "unanswered" and _bal(s, cid) == 98, r)
            fake.mode = "ok"
            st, r = prog.send("appt:4:day_before:2026-10-18T10:00")
            res.ok("повтор сразу — ждём первую попытку, без поиска и без SMS",
                   st == 503 and fake.calls["list"] == 0 and fake.calls["send"] == 2)
            back = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
            _sql(s, "UPDATE sms_messages SET sent_at=?, state_at=? WHERE id=?", back, back, mid4)
            st, r = prog.send("appt:4:day_before:2026-10-18T10:00")
            res.ok("повтор через 2 мин: найдено у sms.md по номеру и имени — 200, второй SMS нет, списание одно",
                   st == 200 and r["id"] == mid4 and r["state"] == "queued" and fake.calls["list"] == 1
                   and fake.calls["send"] == 2 and _bal(s, cid) == 98
                   and _one(s, "SELECT provider_id FROM sms_messages WHERE id=?", mid4) == fake.sent[-1]["id"], r)
            # молчание, сообщение НЕ принято: поиск пуст → отправка
            fake.mode = "drop"
            st, r = prog.send("appt:5:same_day:2026-10-18T10:00")
            mid5 = r["id"]
            _sql(s, "UPDATE sms_messages SET sent_at=?, state_at=? WHERE id=?", back, back, mid5)
            fake.mode = "ok"
            st, r = prog.send("appt:5:same_day:2026-10-18T10:00")
            res.ok("обрыв без приёма: поиск пуст, отправлено заново — у sms.md три принятых, остаток 97",
                   st == 200 and r["id"] == mid5 and fake.calls["list"] == 2 and fake.calls["send"] == 4
                   and sum(1 for m in fake.sent if m["text"] == TEXT) == 3 and _bal(s, cid) == 97, r)
            # отказ по существу: возврат, повтор не идёт к sms.md
            fake.mode = "422"
            st, r = prog.send("appt:6:booked:2026-10-19T09:00")
            res.ok("422 — 502 sms_refused с кодом и полем, возврат, состояние refused",
                   st == 502 and r["code"] == "sms_refused" and r["error"] == "VALIDATION_ERROR:to"
                   and _state(s, r["id"]) == "refused" and _bal(s, cid) == 97, r)
            fake.mode = "ok"
            n = fake.calls["send"]
            st, r = prog.send("appt:6:booked:2026-10-19T09:00")
            res.ok("повтор отказанного — тот же отказ без запроса", st == 502 and fake.calls["send"] == n)
            # «не сейчас»: возврат и повтор уходит
            fake.mode = "429"
            st, r = prog.send("appt:7:changed:2026-10-19T09:00")
            res.ok("429 — 503 sms_retry, возврат, состояние retry",
                   st == 503 and r["code"] == "sms_retry" and _state(s, r["id"]) == "retry" and _bal(s, cid) == 97)
            fake.mode = "ok"
            st, r = prog.send("appt:7:changed:2026-10-19T09:00")
            res.ok("после 429 повтор уходит: 200, списано снова один раз", st == 200 and _bal(s, cid) == 96
                   and _sql(s, "SELECT reason FROM sms_ledger WHERE message_id=? ORDER BY id", r["id"]) == [("send",), ("refund",), ("send",)])
            # 402 у sms.md — наш счёт пуст: тревога Олегу
            fake.mode = "402"
            before = len(_letters(s))
            st, r = prog.send("appt:8:day_before:2026-10-20T09:00")
            res.ok("402 sms.md — sms_retry, возврат и письмо Олегу про депозит",
                   st == 503 and _bal(s, cid) == 96 and len(_letters(s)) == before + 1
                   and _letters(s)[-1][0] == "oleg@example.md" and "INSUFFICIENT_BALANCE" in _letters(s)[-1][1]
                   and "депозит" in _letters(s)[-1][2])
            prog.send("appt:9:day_before:2026-10-20T09:00")
            res.ok("вторая тревога в тот же день не шлётся", len(_letters(s)) == before + 1)
            fake.mode = "ok"
            # sms.md насчитал иначе: его число истинно, строка fix, письмо Олегу
            fake.segments_override = 2
            before = len(_letters(s))
            st, r = prog.send("appt:10:day_before:2026-10-21T09:00")
            res.ok("сегменты разошлись: списано 2, строка fix −1, письмо Олегу",
                   st == 200 and r["segments"] == 2 and _bal(s, cid) == 94
                   and _sql(s, "SELECT reason, delta FROM sms_ledger WHERE message_id=? ORDER BY id", r["id"]) == [("send", -1), ("fix", -1)]
                   and len(_letters(s)) == before + 1 and "сегментов" in _letters(s)[-1][1], r)
            fake.segments_override = None
            # потолок и выключатель
            _sql(s, "UPDATE sms_accounts SET daily_cap=6 WHERE clinic_id=?", cid)
            st, r = prog.send("appt:11:day_before:2026-10-21T09:00")
            res.ok("потолок 6 при 6 ушедших сегодня — 429 sms_cap", st == 429 and r["code"] == "sms_cap" and r["daily_cap"] == 6, r)
            _sql(s, "UPDATE sms_accounts SET daily_cap=300, enabled=0 WHERE clinic_id=?", cid)
            st, r = prog.send("appt:11:day_before:2026-10-21T09:00")
            res.ok("выключено Олегом — 423 sms_off", st == 423 and r["code"] == "sms_off")
            _sql(s, "UPDATE sms_accounts SET enabled=1 WHERE clinic_id=?", cid)
            st, r = prog.post("/v1/sms/status", ids=[mid1, mid4, 999999, "x"])
            res.check("статусы своих сообщений, чужие и мусор пропущены",
                      (st, [(i["id"], i["state"]) for i in r["items"]]), (200, [(mid1, "queued"), (mid4, "queued")]))
            st, acc = prog.get("/v1/sms/account")
            res.ok("счёт после всего: остаток 94, от имени Clinica Test, использовано сегодня 6",
                   acc["balance"] == 94 and acc["from"] == "Clinica T" and acc["used_today"] == 6 and acc["blocked"] == "", acc)
            # ⛔ номер и текст — ни в базе, ни в логе, ни в журнале
            dump, log = _dump(s), s.log()
            res.ok("цифр номера и текста SMS нет в базе", DIGITS not in dump and "reaminteste" not in dump and "69 123" not in dump)
            res.ok("цифр номера и текста SMS нет в логе сервера", DIGITS not in log and "reaminteste" not in log, log[-1500:])
            res.ok("в журнале нет строк на сообщения",
                   _one(s, "SELECT count(*) FROM audit WHERE what LIKE 'sms_%'") == 3)   # sms_sender, sms_name, sms_pack
            # год имени истёк — снова от DentPilot, без блокировки
            _sql(s, "UPDATE sms_accounts SET sender_until='2026-01-01T00:00:00Z' WHERE clinic_id=?", cid)
            st, acc = prog.get("/v1/sms/account")
            res.ok("год имени кончился — от DentPilot, не заблокировано", acc["from"] == "DentPilot" and acc["blocked"] == "")
            st, r = prog.post("/v1/sms/order", name=1)
            npid = _one(s, "SELECT id FROM payments WHERE reference=?", r["reference"])
            admin.post(f"/admin/payments/{npid}/confirm")
            new_until = _one(s, "SELECT sender_until FROM sms_accounts WHERE clinic_id=?", cid)
            res.ok("продление истёкшего имени — год от сегодня, снова от имени клиники",
                   new_until[:4] == str(datetime.now(timezone.utc).year + 1) and prog.get("/v1/sms/account")[1]["from"] == "Clinica T"
                   and "până la" in _letters(s)[-1][2], new_until)
            # пробный период: 30 SMS бесплатно, один раз
            cid_t = cid_from(admin.post("/admin/clinics", name="Clinica Probă", idno="3334567890123",
                                        contact_name="X", email="proba@example.md", phone="").location)
            admin.post(f"/admin/clinics/{cid_t}/issue", kind="trial")
            prog_t = Program(s.url, _one(s, "SELECT renew_token FROM clinics WHERE id=?", cid_t))
            st, acc = prog_t.get("/v1/sms/account")
            res.ok("пробный: 30 SMS бонусом, SMS разрешены, от DentPilot",
                   acc["balance"] == 30 and acc["blocked"] == "" and acc["from"] == "DentPilot", acc)
            prog_t.get("/v1/sms/account")
            res.ok("бонус один раз", _bal(s, cid_t) == 30
                   and _sql(s, "SELECT reason, note FROM sms_ledger WHERE clinic_id=?", cid_t) == [("bonus", "perioada de probă")])
            st, r = prog_t.send("appt:1:day_before:x")
            res.ok("пробный шлёт от DentPilot", st == 200 and fake.sent[-1]["from"] == "DentPilot" and r["balance"] == 29)
            # второй сервер: тихие часы вокруг текущего часа Кишинёва
        h = sms.local(datetime.now(timezone.utc)).hour
        with Server(env=fake.env(DP_SMS_QUIET=f"{h}-{(h + 1) % 24}")) as s2:
            admin = Client(s2.url).login()
            cid, token = _clinic_with_license(admin, s2)
            _sql(s2, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who) VALUES(?,10,'bonus','2026-10-01T00:00:00Z','t')", cid)
            st, r = Program(s2.url, token).send("appt:1:day_before:x")
            res.ok("тихие часы — 423 sms_quiet, списания нет", st == 423 and r["code"] == "sms_quiet" and _bal(s2, cid) == 10, r)
        with Server(env=fake.env(DP_SMS_OFFERED="")) as s4:
            admin = Client(s4.url).login()
            cid, token = _clinic_with_license(admin, s4)
            st, acc = Program(s4.url, token).get("/v1/sms/account")
            res.ok("токен есть, DP_SMS_OFFERED пуст — плитке не предлагается, 503 sms_not_offered на отправку",
                   acc["offered"] is False and acc["blocked"] == "sms_not_offered"
                   and Program(s4.url, token).send("appt:1:day_before:x")[0] == 503, acc)
            _sql(s4, "UPDATE sms_accounts SET pilot=1 WHERE clinic_id=?", cid)
            st, acc = Program(s4.url, token).get("/v1/sms/account")
            res.ok("пилот у этой клиники — предложено ей одной", acc["offered"] is True and acc["blocked"] == "sms_balance" or acc["blocked"] == "", acc)
        with Server(env=fake.env(DP_SMSMD_TOKEN="")) as s3:
            admin = Client(s3.url).login()
            cid, token = _clinic_with_license(admin, s3)
            st, r = Program(s3.url, token).send("appt:1:day_before:x")
            res.ok("без DP_SMSMD_TOKEN — 503 sms_unconfigured", st == 503 and r["code"] == "sms_unconfigured")
            res.ok("лог старта говорит про пустой токен", "DP_SMSMD_TOKEN пуст" in s3.log())
    finally:
        fake.close()


def suite_dlr(res: Result) -> None:
    """Уведомление о доставке: чужой секрет 404, верный — 200 сразу и перепроверка запросом; 9 без возврата, 10 с возвратом."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s)
            _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who) VALUES(?,10,'bonus','2026-10-01T00:00:00Z','t')", cid)
            prog = Program(s.url, token)
            ids = [prog.send(f"appt:{i}:day_before:x")[1]["id"] for i in range(1, 5)]
            pids = [_one(s, "SELECT provider_id FROM sms_messages WHERE id=?", i) for i in ids]
            anon = Client(s.url)
            res.check("чужой секрет — 404", anon.post_raw("/v1/smsmd/dlr/wrong", fake.dlr(pids[0], 3)).status, 404)
            res.check("без секрета — 404", anon.post_raw("/v1/smsmd/dlr/", fake.dlr(pids[0], 3)).status, 404)
            res.ok("уведомление не применилось", _state(s, ids[0]) == "queued" and fake.calls["message"] == 0)
            path = f"/v1/smsmd/dlr/{DLR_SECRET}"
            fake.set_status(pids[0], 3)
            r = anon.post_raw(path, fake.dlr(pids[0], 3))
            res.ok("верный секрет — 200 сразу", r.status == 200 and json.loads(r.body) == {"ok": True})
            res.ok("состояние перепроверено запросом — delivered",
                   _wait(lambda: _state(s, ids[0]) == "delivered") and fake.calls["message"] == 1, _state(s, ids[0]))
            n = fake.calls["message"]
            anon.post_raw(path, fake.dlr(pids[0], 3))
            res.ok("дубль того же уведомления — без запроса", _wait(lambda: fake.calls["message"] == n, 1.0) and fake.calls["message"] == n)
            # уведомление врёт «доставлено», истина — 10: сигнал, не истина
            fake.set_status(pids[1], 10)
            anon.post_raw(path, fake.dlr(pids[1], 3))
            res.ok("уведомление «3» при истине 10 — failed и возврат",
                   _wait(lambda: _state(s, ids[1]) == "failed") and _bal(s, cid) == 7
                   and _sql(s, "SELECT reason, delta FROM sms_ledger WHERE message_id=? ORDER BY id", ids[1]) == [("send", -1), ("refund", 1)])
            fake.set_status(pids[2], 9)
            anon.post_raw(path, fake.dlr(pids[2], 9))
            res.ok("9 Undelivered — без возврата", _wait(lambda: _state(s, ids[2]) == "undelivered") and _bal(s, cid) == 7)
            fake.set_status(pids[2], 3)
            n = fake.calls["message"]
            anon.post_raw(path, fake.dlr(pids[2], 3))
            time.sleep(0.5)
            res.ok("конечное состояние не трогается и не перепроверяется", _state(s, ids[2]) == "undelivered" and fake.calls["message"] == n)
            r = anon.post_raw(path, fake.dlr("00000000-0000-0000-0000-000000000000", 3))
            res.ok("чужой id — 200 и без запроса", r.status == 200 and fake.calls["message"] == n)
            r = anon.post_raw(path, b"not json")
            res.ok("мусор в теле — 200 (повтора sms.md на 4xx не будет), ничего не сломано",
                   r.status == 200 and fake.calls["message"] == n)
            fake.set_status(pids[3], 2)
            anon.post_raw(path, fake.dlr(pids[3], 2))
            res.ok("2 Sent — sent, остаток прежний", _wait(lambda: _state(s, ids[3]) == "sent") and _bal(s, cid) == 7)
            time.sleep(0.3)
            dump, log = _dump(s), s.log()
            res.ok("после уведомлений цифр номера нет ни в базе, ни в логе",
                   "69123456" not in dump and "37369123456" not in log and "69123456" not in log, log[-800:])
    finally:
        fake.close()


def suite_daily(res: Result) -> None:
    """Ежедневная задача: опрос статусов до 26 ч, сверка имён, «Au rămas N SMS», баланс sms.md против долга."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s)
            cid2 = cid_from(admin.post("/admin/clinics", name="Clinica Doi", idno="2234567890123",
                                       contact_name="X", email="doi@example.md", phone="").location)
            _sql(s, "INSERT INTO sms_accounts(clinic_id, daily_cap, updated_at, sender, sender_state, sender_live, sender_until) "
                    "VALUES(?,300,'x','Clinica Test','active','Clinica Test','2099-01-01T00:00:00Z')", cid)
            _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, payment_id, at, who) VALUES(?,60,'pack',NULL,'2026-10-01T00:00:00Z','t')", cid)
            prog = Program(s.url, token)
            ids = [prog.send(f"appt:{i}:day_before:x")[1]["id"] for i in range(1, 4)]
            pids = [_one(s, "SELECT provider_id FROM sms_messages WHERE id=?", i) for i in ids]
            now = datetime.now(timezone.utc)
            # 1-е — 2 часа назад (опрашивается), 2-е — 27 часов (окно вышло), 3-е — только что (рано)
            for mid, hours in ((ids[0], 2), (ids[1], 27)):
                back = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
                _sql(s, "UPDATE sms_messages SET sent_at=? WHERE id=?", back, mid)
            fake.set_status(pids[0], 3)
            fake.set_status(pids[1], 3)
            fake.set_status(pids[2], 3)
            # имена: вторая клиника подала с заявлением — sms.md одобрил; первая — заблокирована
            _sql(s, "INSERT INTO sms_accounts(clinic_id, daily_cap, updated_at, sender, sender_state, sender_paper_at, sender_prepaid) "
                    "VALUES(?,300,'x','Clinica Doi','submitted','2026-10-10T00:00:00Z',1)", cid2)
            fake.aliases = {"DentPilot": 1, "Clinica Doi": 1, "Clinica Test": 3}
            rc, out = _run_daily(s)
            res.ok("задача прошла: статусов 1, имён одобрено 1, отказано 1, писем об остатке 0",
                   rc == 0 and "статусов 1" in out and "имён одобрено 1, отказано 1" in out and "писем об остатке 0" in out, out[-600:])
            res.check("опрошено только сообщение старше часа и моложе 26 ч",
                      [_state(s, i) for i in ids], ["delivered", "queued", "queued"])
            row2 = _sql(s, "SELECT sender_state, sender_live, sender_prepaid, sender_until FROM sms_accounts WHERE clinic_id=?", cid2)[0]
            res.ok("вторая клиника: active, SMS от её имени, оплаченный год начался с одобрения",
                   row2[:3] == ("active", "Clinica Doi", 0) and row2[3][:4] == str(now.year + 1), row2)
            res.check("первая: имя заблокировано у sms.md — rejected, живого имени нет",
                      _sql(s, "SELECT sender_state, sender_live, sender_note FROM sms_accounts WHERE clinic_id=?", cid),
                      [("rejected", "", "sms.md: статус 3")])
            res.ok("баланс sms.md 500 MDL против долга — тревоги нет", "баланс sms.md 500.00 MDL" in out and "тревога" not in out)
            res.ok("журнал: имена, итог daily", _one(s, "SELECT count(*) FROM audit WHERE what='sms_sender'") == 2
                   and "SMS:" in _one(s, "SELECT detail FROM audit WHERE what='daily' ORDER BY id DESC LIMIT 1"))
            # остаток на пороге: 57 → письмо нет (порог 50); списать до 50 → письмо, раз за пакет
            _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who) VALUES(?,-7,'fix','2026-10-02T00:00:00Z','t')", cid)
            n = len(_letters(s))
            rc, out = _run_daily(s)
            res.ok("остаток 50 — письмо «au rămas 50 SMS» клинике", "писем об остатке 1" in out and len(_letters(s)) == n + 1
                   and _letters(s)[-1][0] == "sms@example.md" and "au rămas 50 SMS" in _letters(s)[-1][1], out[-400:])
            rc, out = _run_daily(s)
            res.ok("второй запуск — письма нет", "писем об остатке 0" in out and len(_letters(s)) == n + 1)
            _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who) VALUES(?,100,'pack','2026-10-03T00:00:00Z','t')", cid)
            _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who) VALUES(?,-110,'fix','2026-10-03T00:00:01Z','t')", cid)
            rc, out = _run_daily(s)
            res.ok("новый пакет и снова на пороге — новое письмо", "писем об остатке 1" in out and len(_letters(s)) == n + 2)
            # баланс sms.md ниже проданного: 40 сегм. × 0.30 = 12 MDL > 1.00
            fake.balance = "1.00"
            n = len(_letters(s))
            rc, out = _run_daily(s)
            res.ok("баланс 1.00 MDL ниже долга — тревога Олегу раз в сутки",
                   "тревога Олегу" in out and len(_letters(s)) == n + 1 and _letters(s)[-1][0] == "oleg@example.md"
                   and "меньше, чем продано" in _letters(s)[-1][1], out[-400:])
            rc, out = _run_daily(s)
            res.ok("повтор — тревога не дублируется", "тревога Олегу" not in out and len(_letters(s)) == n + 1)
            # sms.md лёг: задача не падает, в отчёте «пропущено»
            fake.close()
            rc, out = _run_daily(s)
            res.ok("sms.md недоступен — код 0, пропущено про имена и баланс, письма о подписках не затронуты",
                   rc == 0 and "имена sms.md не сверены" in out and "баланс sms.md не получен" in out, out[-600:])
            res.ok("лог сервера и вывод задачи без цифр номера", DIGITS not in s.log() and DIGITS not in out)
    finally:
        try:
            fake.close()
        except Exception:  # noqa: BLE001 — стенд уже закрыт набором
            pass
