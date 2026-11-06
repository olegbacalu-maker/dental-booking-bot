"""Письма — после commit (06.11): почта думает не под замком записи и не внутри транзакции.

До 06.11 вне оплаты письма уходили ВНУТРИ транзакции, и вреда было два.
А. Письмо до первой записи в отложенной транзакции (письмо о сроке у пробных, «Au rămas N SMS»,
   тревога о балансе sms.md, «отправить файл письмом» админки): сосед, записавший за время
   отправки, ронял отметку «отправлено» («database is locked») — письмо ушло, отметки нет,
   назавтра второе такое же, Олегу — 500 после ушедшего письма.
Б. SMTP под замком записи (письмо о сроке у платных, нота SMS из программы, пробный из формы /
   программы / кабинета, «Adaugă clinică», файл письмом после выдачи, тревоги sms.md): почта
   думает до 30 с — `/v1/license` соседней клиники ждёт 10 с и получает 500.
Лекарство одно: письмо собирается в транзакции, уходит после её commit (payments.outbox,
mail.deliver), отметка — после удачной отправки.

Стенд почты здесь ПРИНИМАЕТ письма (STARTTLS со своим сертификатом — mail.send его требует) и
даёт тесту три рычага: `delay` — пауза до приветствия (сервер уже внутри mail.send), `hold` —
пауза после приёма письма до ответа «250», `fail` — отказ. Пока почта думает, сосед — соединение
теста к базе сервера — берёт замок записи с ожиданием 0,2 с и пишет: на старом коде у вида Б он
получает «database is locked», у вида А его запись роняет отметку.
"""
import email
import email.policy
import json
import pathlib
import socketserver
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

from harness import CLOUD, Client, Result, Server, cid_from

from app import jobs, paylink  # noqa: E402 — виды писем задачи, адрес страницы оплаты

BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}
D = timedelta(days=1)
THINK = 1.5         # сколько почта «думает»: с запасом на пробу соседа, меньше таймаутов клиентов


# ---------- стенд почты ----------


def _cert(folder: pathlib.Path) -> tuple[str, str]:
    """Самоподписанный сертификат стенда: smtplib.starttls() без контекста его не проверяет."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - D).not_valid_after(now + 2 * D)
            .sign(key, hashes.SHA256()))
    c, k = folder / "stand.crt", folder / "stand.key"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    return str(c), str(k)


class Smtp:
    """Стенд SMTP, который принимает письма. `sessions` — сколько раз к нему подключились (сервер
    вошёл в mail.send), `accepted` — сколько писем принято; `messages` — (кому, тема, текст, имена
    вложений) по порядку. Рычаги — в шапке файла."""

    def __init__(self):
        self.delay = 0.0
        self.hold = 0.0
        self.fail = False
        self.sessions = 0
        self.accepted = 0
        self.messages: list[tuple[str, str, str, list]] = []
        self._dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_smtp_"))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*_cert(self._dir))
        stand = self

        class H(socketserver.StreamRequestHandler):
            def say(self, text: str) -> None:
                self.wfile.write(text.encode("ascii") + b"\r\n")
                self.wfile.flush()

            def handle(self):
                stand.sessions += 1
                time.sleep(stand.delay)
                self.say("220 stand ESMTP")
                tls = False
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    verb = line[:4].upper()
                    if verb == b"EHLO":
                        self.say("250 stand" if tls else "250-stand\r\n250 STARTTLS")
                    elif verb == b"STAR":
                        self.say("220 go ahead")
                        self.request = ctx.wrap_socket(self.request, server_side=True)
                        self.rfile, self.wfile, tls = self.request.makefile("rb"), self.request.makefile("wb"), True
                    elif verb == b"DATA":
                        if stand.fail:
                            self.say("451 stand says no")
                            continue
                        self.say("354 go")
                        raw = []
                        while (row := self.rfile.readline()) and row != b".\r\n":
                            raw.append(row[1:] if row.startswith(b"..") else row)
                        m = email.message_from_bytes(b"".join(raw), policy=email.policy.default)
                        # перевод строки в проводе SMTP — CRLF: это транспорт, не текст письма
                        stand.messages.append((m["To"], " ".join(str(m["Subject"]).split()),
                                               m.get_body(preferencelist=("plain",)).get_content().replace("\r\n", "\n"),
                                               [p.get_filename() for p in m.walk() if p.get_filename()]))
                        stand.accepted += 1
                        time.sleep(stand.hold)
                        self.say("250 accepted")
                    elif verb == b"QUIT":
                        self.say("221 bye")
                        return
                    else:
                        self.say("250 ok")          # MAIL, RCPT, RSET, NOOP, HELO

        class S(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

            def handle_error(self, request, client_address):
                pass                                # убитый отправитель рвёт сокет — это и проверяется

        self.srv = S(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def env(self) -> dict:
        return {"DP_SMTP_HOST": "127.0.0.1", "DP_SMTP_PORT": str(self.srv.server_address[1]),
                "DP_SMTP_USER": "", "DP_SMTP_PASS": ""}

    def to(self, box: str) -> list[tuple[str, str, str, list]]:
        return [m for m in self.messages if m[0] == box]

    def wait(self, what: str, n: int, seconds: float = 20.0) -> bool:
        """Дождаться, пока `sessions` или `accepted` дойдёт до `n`."""
        end = time.time() + seconds
        while time.time() < end:
            if getattr(self, what) >= n:
                return True
            time.sleep(0.02)
        return False

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        for f in self._dir.iterdir():
            f.unlink()
        self._dir.rmdir()


# ---------- помощники ----------


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db", timeout=10)
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


# Запись соседа — НАСТОЯЩАЯ: счётчик в schema_meta растёт. ⚠️ `UPDATE … SET value=value` записью не
# является: SQLite сравнивает байты и страницу не трогает — в WAL ничего не ложится, снимок чужой
# транзакции не устаревает, и «сосед записал» значило бы «сосед подержал замок» (так проверка вида А
# проходила на старом коде).
NEIGHBOUR_WRITE = ("INSERT INTO schema_meta(key, value) VALUES('test_neighbour', '1') "
                   "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")


def write_free(s: Server) -> bool:
    """Сосед: берёт замок записи базы сервера с ожиданием 0,2 с, пишет и коммитит. True — замок
    был свободен (и запись соседа легла — следующая запись сервера идёт уже после неё)."""
    con = sqlite3.connect(s.dir / "cloud.db", isolation_level=None, timeout=0.2)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(NEIGHBOUR_WRITE)
        con.execute("COMMIT")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def thinking(smtp: Smtp, s: Server, call) -> tuple:
    """`call()` в своём потоке при думающей почте → (ответ или исключение, был ли свободен замок
    записи, пока почта думала). Проба соседа — в момент, когда сервер подключился к почте."""
    out: dict = {}

    def go():
        try:
            out["r"] = call()
        except Exception as e:  # noqa: BLE001 — исключение тоже ответ
            out["r"] = e

    n, smtp.delay = smtp.sessions, THINK
    t = threading.Thread(target=go, daemon=True)
    t.start()
    free = smtp.wait("sessions", n + 1) and write_free(s)
    t.join(timeout=60)
    smtp.delay = 0.0
    return out.get("r"), free


def _same(got: tuple, want: tuple[str, str]) -> bool:
    """Письмо на стенде — то же, что отдал сборщик: тема и текст байт в байт (тема — с точностью
    до свёртки длинного заголовка, текст — до перевода строки в конце, его ставит EmailMessage)."""
    return got[1] == " ".join(want[0].split()) and got[2].rstrip("\n") == want[1].rstrip("\n")


_BUILD = """
import json, sys
from datetime import datetime, timezone
from app import mail
sys.stdout.reconfigure(encoding="utf-8")
args = [datetime.strptime(a["dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if isinstance(a, dict) and set(a) == {"dt"} else a for a in json.loads(sys.argv[2])]
print(json.dumps(getattr(mail, sys.argv[1])(*args)))
"""


def built(s: Server, name: str, *args) -> tuple[str, str]:
    """(тема, текст) сборщика `mail.<name>` — в окружении СЕРВЕРА (реквизиты банка, адрес, цены —
    из его env; у процесса теста их нет). Дата — {"dt": "YYYY-MM-DDTHH:MM:SSZ"}."""
    p = subprocess.run([sys.executable, "-c", _BUILD, name, json.dumps(args)], cwd=str(CLOUD), env=s.env,
                       capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[-600:]
    subject, body = json.loads(p.stdout.decode("utf-8"))
    return subject, body


def _daily(s: Server, at: datetime | None = None) -> subprocess.Popen:
    """Задача как из cron: отдельный процесс, окружение сервера."""
    cmd = [sys.executable, "-m", "app.jobs", "daily"] + (["--at", at.strftime("%Y-%m-%dT%H:%M:%SZ")] if at else [])
    return subprocess.Popen(cmd, cwd=str(CLOUD), env=s.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _end(p: subprocess.Popen) -> tuple[int, str]:
    out, _ = p.communicate(timeout=90)
    return p.returncode, out.decode("utf-8", "replace")


def _run(s: Server, at: datetime | None = None) -> tuple[int, str]:
    return _end(_daily(s, at))


def _marks(s: Server, cid: str) -> list:
    return [r[0] for r in _sql(s, "SELECT kind FROM reminders WHERE subscription_id=? ORDER BY sent_at, rowid", cid)]


def _at(day) -> datetime:
    return datetime(day.year, day.month, day.day, 6, 0, 0, tzinfo=timezone.utc)


def _quiet(res: Result, s: Server) -> None:
    log_ = s.log()
    res.ok("в логе сервера ни «database is locked», ни трейсбека",
           "database is locked" not in log_ and "Traceback" not in log_, log_[-1500:])


# ---------- ежедневная задача: письмо о сроке ----------


def _reminder(s: Server, cid: str, kind: str) -> tuple[str, str]:
    """Письмо о сроке, как его соберёт сборщик сервера по тому, что лежит в базе."""
    c = _sql(s, "SELECT name FROM clinics WHERE id=?", cid)[0]
    plan, valid_until, grace_days = _sql(s, "SELECT plan, valid_until, grace_days FROM subscriptions "
                                            "WHERE clinic_id=?", cid)[0]
    valid = datetime.strptime(valid_until, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    grace = (valid + grace_days * D).strftime("%Y-%m-%dT%H:%M:%SZ")
    pay = None
    if plan != "trial":
        ref, amount, months, tier = _sql(s, "SELECT reference, amount, months, tier FROM payments WHERE clinic_id=? "
                                            "AND status='pending' ORDER BY id DESC LIMIT 1", cid)[0]
        page = paylink.url_for(_sql(s, "SELECT id FROM pay_links WHERE clinic_id=? ORDER BY created_at DESC LIMIT 1",
                                    cid)[0][0])
        pay = {"reference": ref, "amount": int(amount), "months": int(months), "url": None, "page": page, "tier": tier}
    return built(s, "reminder_letter", kind, c[0], plan, {"dt": valid_until}, {"dt": grace}, int(grace_days), pay)


def suite_daily(res: Result) -> None:
    """Письмо о сроке (jobs.daily) — после commit: почта думает при свободном замке записи; сосед,
    записавший за время отправки, отметку не роняет; почта отказала или процесс умер до отправки —
    письмо не потеряно и не удвоено; процесс умер между ответом почты и отметкой — второе письмо
    (цена порядка «отправить → отметить», названа в mail.deliver)."""
    smtp = Smtp()
    try:
        with Server(env={**BANK_ENV, **smtp.env}) as s:
            c = Client(s.url).login()
            box = "platit@example.md"
            cid = cid_from(c.post("/admin/clinics", name="Clinica Platita", idno="1234567890123", contact_name="Ion",
                                  email=box, phone="").location)
            v = datetime.now(timezone.utc).date() + 60 * D
            c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")

            # 1) платная клиника (вид Б): нота и ссылка страницы оплаты пишутся ДО письма
            n, smtp.delay = smtp.sessions, THINK
            p = _daily(s, _at(v - 14 * D))
            free = smtp.wait("sessions", n + 1) and write_free(s)
            rc, out = _end(p)
            smtp.delay = 0.0
            res.ok("нота за 14 дней: почта думает — замок записи свободен, сосед записал", free, out[-300:])
            res.ok("задача: код 0, одно письмо", rc == 0 and "писем: 1" in out and len(smtp.to(box)) == 1, out[-400:])
            res.ok("письмо — то же, что собирает сборщик (тема и текст байт в байт)",
                   bool(smtp.to(box)) and _same(smtp.to(box)[0], _reminder(s, cid, jobs.INVOICE)),
                   repr(smtp.to(box)[:1])[:600])
            res.check("отметка «отправлено» записана после письма — запись соседа её не уронила",
                      _marks(s, cid), [jobs.INVOICE])
            ref = _sql(s, "SELECT reference FROM payments WHERE clinic_id=?", cid)[0][0]
            line = _sql(s, "SELECT who, detail FROM audit WHERE what='reminder' AND clinic_id=?", cid)
            res.check("журнал: строка reminder тем же текстом, что раньше",
                      line, [("daily", f"invoice, период до {v:%Y-%m-%d}, на {box} (smtp)")])
            rc, out = _run(s, _at(v - 14 * D))
            res.ok("второй проход в тот же день — ни письма", "писем: 0" in out and len(smtp.to(box)) == 1, out[-200:])

            # 2) почта отказала: отметки нет, следующий проход присылает — ровно одно письмо
            smtp.fail = True
            rc, out = _run(s, _at(v - 3 * D))
            smtp.fail = False
            res.ok("почта отказала: код 1, «ошибок: 1», письма нет",
                   rc == 1 and "ошибок: 1" in out and "писем: 0" in out and len(smtp.to(box)) == 1, out[-400:])
            res.check("отказ почты: отметки нет, строки reminder нет",
                      (_marks(s, cid), _sql(s, "SELECT count(*) FROM audit WHERE what='reminder'")[0][0]),
                      ([jobs.INVOICE], 1))
            rc, out = _run(s, _at(v - 3 * D))
            res.ok("следующий проход: письмо ушло — одно, не два",
                   rc == 0 and len(smtp.to(box)) == 2 and _marks(s, cid) == [jobs.INVOICE, jobs.EXPIRING],
                   f"{out[-300:]} {_marks(s, cid)}")
            res.ok("…и это то же письмо «expiră în 3 zile» с прежней нотой",
                   _same(smtp.to(box)[1], _reminder(s, cid, jobs.EXPIRING)) and ref in smtp.to(box)[1][2])

            # 3) процесс умер между commit и отправкой (почта ещё не приняла письмо)
            n, smtp.delay = smtp.sessions, 30.0
            p = _daily(s, _at(v))
            inside = smtp.wait("sessions", n + 1)
            p.kill()
            p.communicate(timeout=30)
            smtp.delay = 0.0
            res.ok("процесс убит внутри отправки: письма нет, отметки нет",
                   inside and len(smtp.to(box)) == 2 and _marks(s, cid) == [jobs.INVOICE, jobs.EXPIRING],
                   f"{inside} {len(smtp.to(box))} {_marks(s, cid)}")
            rc, out = _run(s, _at(v))
            res.ok("следующий проход присылает письмо: не потеряно, одно",
                   rc == 0 and len(smtp.to(box)) == 3 and _marks(s, cid)[-1] == jobs.EXPIRED, out[-300:])
            res.check("нота та же: второй задача не завела",
                      _sql(s, "SELECT reference FROM payments WHERE clinic_id=?", cid), [(ref,)])

            # 4) процесс умер между ответом почты и отметкой: письмо принято, отметки нет → второе
            n, smtp.hold = smtp.accepted, 30.0
            p = _daily(s, _at(v + 13 * D))
            taken = smtp.wait("accepted", n + 1)
            p.kill()
            p.communicate(timeout=30)
            smtp.hold = 0.0
            res.ok("процесс убит после приёма письма почтой: письмо есть, отметки нет",
                   taken and len(smtp.to(box)) == 4 and jobs.LAST_WARNING not in _marks(s, cid),
                   f"{taken} {len(smtp.to(box))} {_marks(s, cid)}")
            rc, out = _run(s, _at(v + 13 * D))
            res.ok("цена порядка «отправить → отметить»: следующий проход шлёт то же письмо второй раз",
                   rc == 0 and len(smtp.to(box)) == 5 and smtp.to(box)[3][1:3] == smtp.to(box)[4][1:3]
                   and _marks(s, cid)[-1] == jobs.LAST_WARNING, out[-300:])
            rc, out = _run(s, _at(v + 13 * D))
            res.ok("…и третьего не будет: отметка записана", "писем: 0" in out and len(smtp.to(box)) == 5, out[-200:])

            # 5) пробная клиника (вид А): до письма транзакция ничего не пишет
            tbox = "proba@example.md"
            tid = cid_from(c.post("/admin/clinics", name="Clinica Proba", idno="", contact_name="Ana",
                                  email=tbox, phone="").location)
            c.post(f"/admin/clinics/{tid}/issue", kind="trial")
            tv = datetime.strptime(_sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", tid)[0][0][:10],
                                   "%Y-%m-%d").date()
            n, smtp.delay = smtp.sessions, THINK
            p = _daily(s, _at(tv - 3 * D))
            free = smtp.wait("sessions", n + 1) and write_free(s)
            rc, out = _end(p)
            smtp.delay = 0.0
            res.ok("пробный, «expiră în 3 zile»: сосед записал, пока почта думала, — код 0, отметка есть",
                   free and rc == 0 and len(smtp.to(tbox)) == 1 and _marks(s, tid) == [jobs.EXPIRING],
                   f"{free} {rc} {out[-300:]} {_marks(s, tid)}")
            res.ok("письмо пробному — то же, что собирает сборщик",
                   bool(smtp.to(tbox)) and _same(smtp.to(tbox)[0], _reminder(s, tid, jobs.EXPIRING)))
            rc, out = _run(s, _at(tv - 3 * D))
            res.ok("второй проход — второго письма пробному нет", len(smtp.to(tbox)) == 1, out[-200:])
    finally:
        smtp.close()


# ---------- SMS: тревоги Олегу и «Au rămas N SMS» ----------


def suite_sms(res: Result) -> None:
    """Тревога Олегу из отправки SMS (сегменты разошлись, sms.md отказывает 402) собирается в
    транзакции итога и уходит после её commit — почта думает при свободном замке записи; раз в
    сутки на вид. Ежедневная задача: «Au rămas N SMS» клинике и тревога о балансе sms.md — вне
    транзакции; сосед, записавший за время отправки, отметку не роняет; почта отказала — отметки
    нет, следующий проход присылает."""
    from test_sms import FakeSmsMd, Program, _clinic_with_license
    fake, smtp = FakeSmsMd(), Smtp()
    oleg, box = "oleg@example.md", "sms@example.md"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with Server(env={**fake.env(), **smtp.env}) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s)
            prog = Program(s.url, token)
            prog.get("/v1/sms/account")                          # счёт заведён
            _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who, note) VALUES(?,?,?,?,?,?)",
                 cid, 100, "pack", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "test", "")
            pack = _sql(s, "SELECT MAX(id) FROM sms_ledger WHERE clinic_id=? AND reason='pack'", cid)[0][0]

            # 1) сегменты разошлись: тревога из транзакции «sms.md принял»
            fake.segments_override = 3
            (st, r), free = thinking(smtp, s, lambda: prog.send("mesaj-1"))
            fake.segments_override = None
            res.ok("SMS принято, сегменты разошлись: 200, почта думала при свободном замке записи",
                   st == 200 and free, f"{st} {r} замок свободен: {free}")
            mid = r.get("id")
            want = (f"Сообщение {mid} клиники {cid}: sms.md насчитал 3 сегм., сервер — 1. Списано по счёту sms.md "
                    f"(строка fix в журнале). Сверить cloud/app/sms_rule.py и bot/app/core/sms_rule.py с правилом "
                    f"sms.md (S2).")
            res.ok("тревога о сегментах дошла Олегу тем же текстом",
                   len(smtp.to(oleg)) == 1 and _same(smtp.to(oleg)[0], (
                       "DentPilot Cloud: правило сегментов разошлось с sms.md", want)), repr(smtp.to(oleg))[:500])
            res.check("отметка тревоги за сегодня — после отправки",
                      _sql(s, "SELECT kind, period FROM reminders WHERE subscription_id='_sms'"), [("sms_segments", day)])

            # 2) sms.md отказывает (402): тревога из транзакции отказа, деньги клинике возвращены
            bal = _sql(s, "SELECT COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=?", cid)[0][0]
            fake.mode = "402"
            (st, r), free = thinking(smtp, s, lambda: prog.send("mesaj-2"))
            res.ok("sms.md 402: sms_retry, почта думала при свободном замке записи, сегмент возвращён",
                   st == 503 and r.get("code") == "sms_retry" and free
                   and _sql(s, "SELECT COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=?", cid)[0][0] == bal,
                   f"{st} {r} замок свободен: {free}")
            res.ok("тревога «sms.md отказывает» дошла Олегу тем же текстом",
                   len(smtp.to(oleg)) == 2 and _same(smtp.to(oleg)[1], (
                       "DentPilot Cloud: sms.md отказывает (INSUFFICIENT_BALANCE)",
                       "sms.md ответил 402 INSUFFICIENT_BALANCE на отправку: на нашем счёте sms.md нет денег — "
                       "пополнить депозит. SMS клиник не уходят, пакеты возвращаются; программа повторит сама.")),
                   repr(smtp.to(oleg)[1:])[:500])
            st, r = prog.send("mesaj-3")
            fake.mode = "ok"
            res.ok("второй отказ в тот же день — второй тревоги нет (отметка записана)",
                   st == 503 and len(smtp.to(oleg)) == 2, f"{st} {len(smtp.to(oleg))}")

            # 3) задача: остаток на пороге и баланс sms.md меньше проданного; сперва почта отказала
            bal = _sql(s, "SELECT COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=?", cid)[0][0]
            _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who, note) VALUES(?,?,?,?,?,?)",
                 cid, 20 - bal, "credit", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "test", "")
            fake.balance = "1.00"
            smtp.fail = True
            rc, out = _run(s)
            smtp.fail = False
            res.ok("почта отказала: ни письма об остатке, ни тревоги, ни отметок",
                   len(smtp.to(box)) == 0 and len(smtp.to(oleg)) == 2
                   and not _sql(s, "SELECT 1 FROM reminders WHERE kind IN ('sms_low', 'sms_float')"), out[-400:])
            n, smtp.delay = smtp.sessions, THINK
            p = _daily(s)
            free1 = smtp.wait("sessions", n + 1) and write_free(s)
            free2 = smtp.wait("sessions", n + 2) and write_free(s)
            rc, out = _end(p)
            smtp.delay = 0.0
            res.ok("следующий проход: сосед писал, пока почта думала над каждым из двух писем, — код 0",
                   free1 and free2 and rc == 0, f"{free1} {free2} {rc} {out[-500:]}")
            name = _sql(s, "SELECT name FROM clinics WHERE id=?", cid)[0][0]
            res.ok("«Au rămas 20 SMS» клинике — то же, что собирает сборщик; одно",
                   len(smtp.to(box)) == 1 and _same(smtp.to(box)[0], built(s, "sms_low_letter", name, 20)),
                   repr(smtp.to(box))[:400])
            res.check("отметка и строка журнала письма об остатке — после отправки, прежним текстом",
                      (_sql(s, "SELECT period FROM reminders WHERE subscription_id=? AND kind='sms_low'", cid),
                       _sql(s, "SELECT who, detail FROM audit WHERE what='mail' AND clinic_id=?", cid)),
                      ([(str(pack),)], [("daily", f"остаток SMS 20 на {box} (smtp)")]))
            res.ok("тревога о балансе sms.md дошла Олегу, отметка за сегодня есть",
                   len(smtp.to(oleg)) == 3 and smtp.to(oleg)[2][1] == "DentPilot Cloud: на счёте sms.md меньше, чем продано"
                   and smtp.to(oleg)[2][2].startswith("Баланс sms.md: 1.00 MDL. Продано клиникам и не потрачено: 20 сегм.")
                   and "тревога Олегу" in out
                   and _sql(s, "SELECT period FROM reminders WHERE subscription_id='_sms' AND kind='sms_float'") == [(day,)],
                   f"{smtp.to(oleg)[2:]} {out[-300:]}")
            rc, out = _run(s)
            res.ok("ещё проход — ни второго письма об остатке, ни второй тревоги",
                   rc == 0 and len(smtp.to(box)) == 1 and len(smtp.to(oleg)) == 3, out[-300:])
            _quiet(res, s)
    finally:
        smtp.close()
        fake.close()
