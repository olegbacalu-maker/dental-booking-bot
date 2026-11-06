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
import sqlite3
import threading
import time

from harness import Client, Result, Server, cid_from

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
        self.con.execute("UPDATE schema_meta SET value=value WHERE key='version'")

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
    fields = dict(name="Clinica Lacat", idno="1234567890123", contact_name="Ion",
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
