"""Замок записи на пути программы (06.11): запрос, который пишет, ждёт соседа, а не падает 500.

Боевое облако 06.11 07:27:45 UTC: программа при старте шлёт три запроса разом, и `GET /v1/license`
ответил 500 — `sqlite3.OperationalError: database is locked`. Транзакция маршрута была отложенной
(`BEGIN`): прочла клинику и выдачу, потом захотела писать след запроса. У SQLite транзакция, которая
УЖЕ читает, замок записи не ждёт: занят соседом (или сосед успел закоммитить после её чтения) —
отказ сразу, `timeout=10` соединения тут не работает (busy handler зовётся только у транзакции,
которая ещё ничего не читала). Лечится замком с начала — `db.connect(immediate=True)`: `BEGIN
IMMEDIATE` ждёт соседа до 10 с и читает уже после него.

Гонка здесь не «сто раз подряд и надеяться»: сосед-писатель — соединение ТЕСТА к базе сервера,
которое держит `BEGIN IMMEDIATE` (ровно то, что делает соседний маршрут под `immediate`), пока
запрос программы не ответит или не пройдёт HOLD. Сервер теста — отдельный процесс, подменить в нём
функцию нечем (и не нужно): замок записи у SQLite один на файл, чей бы процесс его ни держал.
Ответ при удержанном замке — значит, маршрут не ждал: на отложенной транзакции это 500.
"""
import email
import email.policy
import json
import pathlib
import re
import shutil
import sqlite3
import tempfile
import threading
import time

from harness import Client, Result, Server, cid_from

from app import config as srv_config  # noqa: E402 — путь к базе для db.connect (harness уже добавил cloud/ в путь)
from app import db as srv_db  # noqa: E402

HOLD = 1.0          # сколько сосед держит замок записи; ⚠️ меньше timeout=10 у db.connect
DEVICE = "d_0123456789ab"


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def _program(token: str) -> dict:
    """Заголовки программы: токен файла и личность компьютера (флот пишет строку — fleet.touch)."""
    return {"Authorization": f"Bearer {token}", "User-Agent": "DentPilot/2.10.0", "X-DentPilot-Device": DEVICE,
            "X-DentPilot-Channel": "stable", "X-DentPilot-OS": "Windows 11"}


class Neighbour:
    """Сосед-писатель: своё соединение к базе сервера под `BEGIN IMMEDIATE` с настоящей записью —
    как `_sms_view` соседнего запроса той же программы. `release` коммитит: запрос, прочитавший до
    этого, остался бы с устаревшим снимком."""

    def __init__(self, s: Server):
        self.con = sqlite3.connect(s.dir / "cloud.db", isolation_level=None, timeout=10)

    def take(self) -> None:
        self.con.execute("BEGIN IMMEDIATE")
        # счётчик растёт — запись настоящая. ⚠️ `UPDATE … SET value=value` SQLite записью не считает
        # (байты те же — страница не трогается, в WAL ничего не ложится): сосед только подержал бы замок
        self.con.execute("INSERT INTO schema_meta(key, value) VALUES('test_neighbour', '1') "
                         "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")

    def release(self) -> None:
        self.con.execute("COMMIT")

    def close(self) -> None:
        self.con.close()        # незакрытая транзакция откатывается — замок не остаётся


def held(s: Server, call, hold: float = HOLD) -> tuple:
    """`call()` из своего потока, пока сосед держит замок записи → (ответ или исключение, ответил
    ли при удержанном замке, секунд до ответа). Замок отпускается, когда запрос ответил или прошло
    `hold`: на отложенной транзакции ответ (500) приходит сразу — при любой нагрузке машины."""
    out: dict = {}

    def go():
        t0 = time.monotonic()
        try:
            out["r"] = call()
        except Exception as e:  # noqa: BLE001 — исключение тоже ответ
            out["r"] = e
        out["took"] = time.monotonic() - t0

    n = Neighbour(s)
    try:
        n.take()
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(timeout=hold)
        early = not t.is_alive()
        n.release()
        t.join(timeout=30)
    finally:
        n.close()
    return out.get("r"), early, out.get("took", 0.0)


def waits(res: Result, s: Server, label: str, call, want: int) -> None:
    """Запрос при занятом замке записи: не отвечает, пока сосед не отпустил, и отвечает `want`."""
    r, early, took = held(s, call)
    status = getattr(r, "status", None)
    res.ok(f"{label}: при занятом замке записи ждёт соседа, а не отвечает сразу",
           not early, f"ответ {status if status is not None else r!r} за {took:.2f} с при удержанном замке")
    res.ok(f"{label}: после соседа — {want}", status == want,
           repr(r) if isinstance(r, Exception) else f"{r.status} {r.body[:300]}")


def _clinic(c: Client, **over) -> str:
    fields = dict(name="Clinica Lacat", idno="1234567890122", contact_name="Ion",
                  email="lacat@example.md", phone="")
    fields.update(over)
    return cid_from(c.post("/admin/clinics", **fields).location)


def _quiet(res: Result, s: Server) -> None:
    log_ = s.log()
    res.ok("в логе сервера ни «database is locked», ни трейсбека",
           "database is locked" not in log_ and "Traceback" not in log_, log_[-1500:])


def suite_license(res: Result) -> None:
    """`GET /v1/license` при соседе-писателе: 204 и 200 приходят после соседа, след запроса записан."""
    with Server() as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        c.post(f"/admin/clinics/{cid}/issue", kind="trial")
        token = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]
        res.ok("клиника с файлом и токеном программы", len(token) >= 32, repr(token))
        prog = Client(s.url)
        r, early, _ = held(s, lambda: prog.get("/health"))
        res.ok("стенд: запрос без базы отвечает и при занятом замке (замок держит сосед, не сервер)",
               early and getattr(r, "status", None) == 200, repr(r))
        waits(res, s, "/v1/license, новее нет (204)",
              lambda: prog.get("/v1/license?seq=5", headers=_program(token)), 204)
        res.check("след запроса записан: seq программы и компьютер во флоте",
                  (_sql(s, "SELECT renew_seq FROM clinics WHERE id=?", cid)[0][0],
                   _sql(s, "SELECT clinic_id, last_seq FROM devices WHERE id=?", DEVICE)), (5, [(cid, 5)]))
        waits(res, s, "/v1/license, файл новее (200)",
              lambda: prog.get("/v1/license?seq=0", headers=_program(token)), 200)
        res.check("выдача файла программе — строкой в журнале",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='renew' AND clinic_id=?", cid)[0][0], 1)
        _quiet(res, s)


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
        t.join(timeout=60)
    return out


ROUNDS = 15


def suite_program(res: Result) -> None:
    """Соседи `/v1/license` у той же программы — `/v1/sms/*`: каждый сперва читает клинику и пишет
    флот (`_sms_clinic`). При соседе-писателе ждут; и живая тройка старта программы разом, ROUNDS
    кругов — ни одного 500 (подстраховка: без удержанного замка гонка случайна)."""
    with Server() as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        c.post(f"/admin/clinics/{cid}/issue", kind="trial")
        token = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]
        h = _program(token)
        prog = Client(s.url)
        waits(res, s, "/v1/sms/account", lambda: prog.get("/v1/sms/account", headers=h), 200)
        res.check("флот: компьютер записан запросом счёта SMS",
                  _sql(s, "SELECT clinic_id FROM devices WHERE id=?", DEVICE), [(cid,)])
        waits(res, s, "/v1/sms/status",
              lambda: prog._do("/v1/sms/status", json.dumps({"ids": []}).encode(),
                               {**h, "Content-Type": "application/json"}), 200)
        bad = []
        for n in range(ROUNDS):
            a, b, d = Client(s.url), Client(s.url), Client(s.url)
            got = _together(lambda: a.get(f"/v1/license?seq={n % 2}", headers=h),
                            lambda: b.get("/v1/sms/account", headers=h),
                            lambda: d._do("/v1/sms/status", json.dumps({"ids": []}).encode(),
                                          {**h, "Content-Type": "application/json"}))
            bad += [f"круг {n}: {getattr(r, 'status', r)!r}" for r in got
                    if getattr(r, "status", None) not in (200, 204)]
        res.check(f"три запроса программы разом, {ROUNDS} кругов: только 200 и 204", bad, [])
        _quiet(res, s)


def _enter(s: Server, mail_to: str) -> Client:
    """Вход в кабинет кодом на e-mail — так же, как человек (ящик клиники из админки — её кабинет)."""
    c = Client(s.url)
    r = c.post("/cont/login/email", email=mail_to)
    vid = re.search(r"name='verify_id' value='([^']+)'", r.body).group(1)
    body = ""
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        if m["To"] == mail_to:
            body = m.get_body(preferencelist=("plain",)).get_content()
    r = c.post("/cont/login/cod", verify_id=vid, code=re.search(r": (\d{6})\n", body).group(1), email=mail_to)
    assert r.status == 303, f"вход {mail_to}: {r.status} {r.location}"
    return c


def suite_pages(res: Result) -> None:
    """Формы кабинета и админки, которые читают и потом пишут: при соседе-писателе ждут — директор
    и Олег не видят 500 оттого, что в эту секунду программа клиники вышла на связь."""
    with Server() as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        c.post(f"/admin/clinics/{cid}/issue", kind="trial")
        fields = dict(name="Clinica Lacat Nou", idno="1234567890122", contact_name="Ion", phone="022000111",
                      address="str. Test 1")
        cab = _enter(s, "lacat@example.md")
        res.ok("кабинет открыт на клинике из админки", cab.get("/cont").status == 200)
        r, early, took = held(s, lambda: cab.post("/cont/date", **fields))
        res.ok("кабинет, реквизиты (/cont/date): ждёт соседа и сохраняет",
               not early and getattr(r, "status", None) == 303 and "saved" in r.location,
               repr(r) if isinstance(r, Exception) else f"{r.status} {r.location} за {took:.2f} с, early={early}")
        res.check("реквизиты из кабинета записаны",
                  _sql(s, "SELECT name, phone FROM clinics WHERE id=?", cid), [("Clinica Lacat Nou", "022000111")])
        r, early, took = held(s, lambda: c.post(f"/admin/clinics/{cid}/edit", email="lacat@example.md",
                                                **dict(fields, name="Clinica Lacat Admin")))
        res.ok("админка, карточка (/admin/clinics/<id>/edit): ждёт соседа и сохраняет",
               not early and getattr(r, "status", None) == 303 and r.location.endswith("msg=saved"),
               repr(r) if isinstance(r, Exception) else f"{r.status} {r.location} за {took:.2f} с, early={early}")
        res.check("реквизиты из админки записаны",
                  _sql(s, "SELECT name FROM clinics WHERE id=?", cid), [("Clinica Lacat Admin",)])
        _quiet(res, s)


def suite_snapshot(res: Result) -> None:
    """Второй вид той же гонки — сосед УСПЕЛ закоммитить между нашим чтением и нашей записью: замок
    уже свободен, а запись отложенной транзакции всё равно падает сразу (снимок устарел, ждать
    нечего). Через HTTP его не поставить без паузы внутри сервера, поэтому — на самом `db.connect`
    сервера, без сервера: две транзакции в процессе теста на своей базе. И обратное: под
    `immediate=True` сосед к нам между чтением и записью не попадает — ждёт commit и видит нашу строку."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_lock_"))
    keep = srv_config.DB_PATH
    srv_config.DB_PATH = tmp / "cloud.db"
    try:
        srv_db.init()
        err, t0 = "", time.monotonic()
        try:
            with srv_db.connect() as con:                         # отложенная, как license_renew до 06.11
                con.execute("SELECT count(*) FROM audit").fetchone()
                with srv_db.connect(immediate=True) as other:     # сосед: записал и закоммитил
                    srv_db.audit(other, "vecin", "lock_test")
                t0 = time.monotonic()
                srv_db.audit(con, "noi", "lock_test")             # замок свободен — а снимок устарел
        except sqlite3.OperationalError as e:
            err = str(e)
        took = time.monotonic() - t0
        res.ok("отложенная: прочла, сосед закоммитил, её запись — «database is locked» сразу, при свободном замке",
               "database is locked" in err and took < 2.0, f"{err!r} за {took:.2f} с")
        with srv_db.connect() as con:
            res.check("запись соседа на месте, наша откатилась",
                      [r[0] for r in con.execute("SELECT who FROM audit ORDER BY id")], ["vecin"])
        seen: dict = {}

        def neighbour():
            try:
                with srv_db.connect(immediate=True) as other:
                    seen["ours"] = other.execute("SELECT count(*) FROM audit WHERE who='noi'").fetchone()[0]
                    srv_db.audit(other, "vecin", "lock_test")
            except Exception as e:  # noqa: BLE001 — исключение тоже ответ
                seen["error"] = repr(e)

        with srv_db.connect(immediate=True) as con:               # как license_renew теперь
            con.execute("SELECT count(*) FROM audit").fetchone()
            t = threading.Thread(target=neighbour, daemon=True)
            t.start()
            t.join(timeout=HOLD)
            waited = t.is_alive()                                 # сосед стоит на BEGIN IMMEDIATE
            srv_db.audit(con, "noi", "lock_test")
        t.join(timeout=30)
        res.ok("immediate: сосед между нашим чтением и записью не попал — ждал commit и увидел нашу строку",
               waited and seen == {"ours": 1}, f"ждал={waited} {seen!r}")
        with srv_db.connect() as con:
            res.check("обе записи на месте, по порядку: сосед, мы, сосед",
                      [r[0] for r in con.execute("SELECT who FROM audit ORDER BY id")], ["vecin", "noi", "vecin"])
    finally:
        srv_config.DB_PATH = keep
        for _ in range(10):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.3)
