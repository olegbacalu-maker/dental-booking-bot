"""Production-hardening (аудит 08-20): границы, которые не видны обычному
прогону, потому что нарушаются не запросом, а ОБСТОЯТЕЛЬСТВАМИ — адресом
клиента, битым файлом на диске, гонкой двух запросов, конфигом, изменившимся
посреди диалога.

Часть проверок ходит НЕ через harness.Server: uvicorn в тестах слушает только
127.0.0.1, и «запрос из сети клиники» через него не предъявить. Такие проверки
зовут приложение как ASGI напрямую (worker-* в этом же файле, отдельным
интерпретатором: остальные наборы уже импортировали app.db с чужим
DATABASE_URL, и в общем процессе издание не переключить).
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from harness import BOT, FIXTURES, PYTHON, Client, Result, Server

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def _run_worker(name: str, tmpdir: pathlib.Path, extra_env: dict | None = None) -> dict:
    """Запустить worker-функцию этого же файла отдельным интерпретатором и
    собрать её ответ (строки вида `ключ значение`)."""
    env = dict(os.environ)
    env.update(extra_env or {})
    r = subprocess.run(
        [str(PYTHON), str(pathlib.Path(__file__).resolve()), name, str(tmpdir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=env,
    )
    out: dict[str, str] = {}
    for line in (r.stdout or "").splitlines():
        if " " in line:
            k, v = line.split(" ", 1)
            out[k] = v
    out["_rc"] = str(r.returncode)
    out["_stderr"] = (r.stderr or "")[-1500:]
    return out


# ---------- ШАГ 1: первичная установка PIN — только с этого компьютера ----------

def _worker_setup(tmpdir: str) -> None:
    """Живое приложение, вызванное как ASGI: адрес клиента задаём сами."""
    import asyncio
    import urllib.parse

    base = pathlib.Path(tmpdir)
    os.environ.update({
        "CLINIC_CONFIG": str(base / "clinic.json"),
        "DATABASE_URL": f"sqlite:///{base / 'dental.db'}",
        "ADMIN_KEY": "",                 # ветка PIN-файла, как у клиники
        "DENTART_NO_RESTART": "1",
        "TELEGRAM_TOKEN": "",
    })
    sys.path.insert(0, str(BOT))
    from app import db
    from app.main import app

    async def call(method: str, path: str, client_ip: str,
                   form: dict | None = None, headers: dict | None = None):
        body = urllib.parse.urlencode(form).encode() if form else b""
        hdrs = [(b"host", b"127.0.0.1:8088")]
        for k, v in (headers or {}).items():
            hdrs.append((k.lower().encode(), v.encode()))
        if body:
            hdrs += [(b"content-type", b"application/x-www-form-urlencoded"),
                     (b"content-length", str(len(body)).encode())]
        scope = {"type": "http", "asgi": {"version": "3.0"},
                 "http_version": "1.1", "method": method, "scheme": "http",
                 "path": path, "raw_path": path.encode(), "query_string": b"",
                 "root_path": "", "headers": hdrs,
                 "client": (client_ip, 40000), "server": ("127.0.0.1", 8088)}
        got = {"body": b""}

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                got["status"] = msg["status"]
                got["headers"] = {k.decode().lower(): v.decode()
                                  for k, v in msg.get("headers", [])}
            elif msg["type"] == "http.response.body":
                got["body"] += msg.get("body", b"")

        await app(scope, receive, send)
        return (got["status"], got.get("headers", {}).get("location", ""),
                got["body"].decode("utf-8", "replace"))

    async def main() -> None:
        async with app.router.lifespan_context(app):
            await _probes()

    async def _probes() -> None:
        try:
            st, _loc, body = await call("GET", "/admin/setup", "192.168.1.50")
            print("lan_get", st)
            print("lan_get_explains", "calculatorul clinicii" in body)
            st, _loc, _b = await call("POST", "/admin/setup", "192.168.1.50",
                                      {"pin1": "4321", "pin2": "4321"})
            print("lan_post", st)
            print("auth_after_lan", (base / "auth.json").exists())
            st, _loc, _b = await call("GET", "/admin/setup", "127.0.0.1")
            print("local_get", st)
            st, loc, _b = await call("POST", "/admin/setup", "127.0.0.1",
                                     {"pin1": "4321", "pin2": "4321"})
            print("local_post", st, loc)
            print("auth_after_local", (base / "auth.json").exists())
            # после установки PIN обычная работа из сети живёт как раньше
            st, _loc, _b = await call("GET", "/admin/login", "192.168.1.7")
            print("lan_login_page", st)
            st, loc, _b = await call("POST", "/admin/login", "192.168.1.7",
                                     {"password": "4321", "next": "/admin"})
            print("lan_login", st, loc)
            # битый auth.json: setup закрыт и локально (правило suite_broken)
            (base / "auth.json").write_text('{"v":2,"users":[{"id"',
                                            encoding="utf-8")
            st, _loc, _b = await call("GET", "/admin/setup", "127.0.0.1")
            print("broken_local_get", st)
        finally:
            if db._CONN is not None:
                await db._CONN.close()   # иначе поток aiosqlite держит процесс

    asyncio.run(main())


def suite_setup_local(res: Result) -> None:
    """Первичная установка PIN (P0 аудита 08-20): пока auth.json нет, журнал
    не защищён ничем, и /admin/setup обязан отвечать только самому компьютеру
    клиники — из сети (Acces din rețea) первый PIN не назначить."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_setup_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", base / "clinic.json")
        got = _run_worker("worker-setup", base)
        if not res.ok("проба поднялась", got["_rc"] == "0",
                      f"rc={got['_rc']}: {got['_stderr']}"):
            return
        res.check("экран установки из сети закрыт", got.get("lan_get"), "403")
        res.check("и объясняет, где ставить PIN",
                  got.get("lan_get_explains"), "True")
        res.check("POST установки из сети отбит", got.get("lan_post"), "403")
        res.check("PIN из сети НЕ записан", got.get("auth_after_lan"), "False")
        res.check("с самого компьютера экран открыт", got.get("local_get"), "200")
        res.ok("локальная установка проходит",
               (got.get("local_post") or "").startswith("303 /admin"),
               f"получено {got.get('local_post')!r}")
        res.check("PIN записан", got.get("auth_after_local"), "True")
        res.check("после установки вход из сети открыт",
                  got.get("lan_login_page"), "200")
        res.ok("и пускает по PIN",
               (got.get("lan_login") or "").startswith("303 /admin")
               and "err=" not in (got.get("lan_login") or ""),
               f"получено {got.get('lan_login')!r}")
        res.check("битый auth.json держит setup закрытым и локально",
                  got.get("broken_local_get"), "303")
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ШАГ 2: битый clinic.json не подменяется демо-клиникой ----------

def suite_config_fallback(res: Result) -> None:
    """P0 аудита 08-20: clinic.json и его .bak оба нечитаемы → программа
    поднимается ЭКРАНОМ ОШИБКИ, а не вшитой демо-клиникой: на «Dr. Elena Rusu»,
    которой в клинике нет, записали бы живого человека. Ветки «жив .bak» и
    «файлов нет вовсе» (запуск из исходников) обязаны остаться как были."""
    import json as _json

    # оба кандидата есть, но не читаются — так выглядит порча на диске
    s = Server()
    (s.dir / "clinic.json").write_text('{"name": "Clinica', encoding="utf-8")
    (s.dir / "clinic.json.bak").write_text("tot rupt", encoding="utf-8")
    with s:
        c = Client(s.url)
        res.check("лаунчер видит живой сервер (/health)",
                  c.get("/health").status, 200)
        r = c.get("/admin")
        res.ok("журнал отвечает экраном ошибки",
               r.status == 503 and "clinic.json" in r.body
               and "Profilul clinicii" in r.body,
               f"код {r.status} — журнал открылся на битом профиле")
        res.ok("экран говорит, что делать",
               "restaurați" in r.body and "reporniți" in r.body,
               "нет инструкции восстановления")
        res.ok("демо-клиника не подставлена",
               "DentPilot Demo" not in r.body and "Elena Rusu" not in r.body,
               "в журнале чужие демо-врачи")
        res.check("вход тоже за шлюзом", c.get("/admin/login").status, 503)
        res.check("канал записи закрыт",
                  c.post_json("/chat", {"message": "/start"}).status, 503)

    # главный битый, .bak жив → работаем на .bak (прежнее поведение)
    s = Server()
    cfg = _json.loads((FIXTURES / "clinic_test.json").read_text(encoding="utf-8"))
    cfg["name"] = "Clinica Bak"
    (s.dir / "clinic.json").write_text("{rupt", encoding="utf-8")
    (s.dir / "clinic.json.bak").write_text(_json.dumps(cfg, ensure_ascii=False),
                                           encoding="utf-8")
    with s:
        c = Client(s.url)
        page = c.get("/admin/login")
        res.ok("живой .bak спасает как раньше",
               page.status == 200 and "Clinica Bak" in page.body,
               f"код {page.status} — запасной профиль не подхвачен")
        res.check("журнал за ним работает",
                  Client(s.url).login().get("/admin").status, 200)

    # файлов нет вовсе — законный путь запуска из исходников: живёт демо
    s = Server()
    (s.dir / "clinic.json").unlink()
    with s:
        page = Client(s.url).get("/admin/login")
        res.ok("без файлов профиль-демо жив (dev-путь)",
               page.status == 200 and "DentPilot Demo" in page.body,
               f"код {page.status} — dev-запуск без $CLINIC_CONFIG сломан")


# ---------- ШАГ 3: гонка за один слот ----------

def suite_booking_race(res: Result) -> None:
    """P1 аудита 08-20: два ОДНОВРЕМЕННЫХ запроса на один слот. Ровно одна
    запись проходит, вторая получает честный conflict — и никогда две. Гонка
    настоящая: клиенты стартуют по общему барьеру из разных потоков.

    ⚠️ Advisory-половину _slot_lock (Postgres, несколько воркеров) прогон НЕ
    исполняет: все харнессы поднимают SQLite, облако заморожено (прайор
    карты). Сторож класса — правило раскладки «замок брони берётся только
    через _slot_lock» + мутации на него."""
    import concurrent.futures
    import threading
    from datetime import date, timedelta

    day = (date.today() + timedelta(days=1)).isoformat()

    with Server() as s:
        def race(entries: list[dict]) -> list[str]:
            barrier = threading.Barrier(len(entries))

            def fire(kw: dict) -> str:
                c = Client(s.url).login()     # вход ДО барьера: гонка — про add
                barrier.wait()
                return c.post("/admin/add", back="/admin/all", **kw).msg

            with concurrent.futures.ThreadPoolExecutor(len(entries)) as ex:
                return sorted(ex.map(fire, entries))

        got = race([
            {"adate": day, "atime": "10:00", "adoctor": "d2",
             "aservice": "consult", "aname": "Race Unu", "aphone": "060111111"},
            {"adate": day, "atime": "10:00", "adoctor": "d2",
             "aservice": "consult", "aname": "Race Doi", "aphone": "060222222"},
        ])
        res.check("тот же старт: ровно один успех", got, ["conflict", "ok"])

        # пересечение ДЛИТЕЛЬНОСТЬЮ, а не совпадение стартов: 14:00(60′) и
        # 14:30(60′) — уникальный индекс такое не ловит, только замок+_conflicts
        got = race([
            {"adate": day, "atime": "14:00", "adoctor": "d2",
             "aservice": "consult", "aname": "Race Trei", "aphone": "060333333"},
            {"adate": day, "atime": "14:30", "adoctor": "d2",
             "aservice": "consult", "aname": "Race Patru", "aphone": "060444444"},
        ])
        res.check("пересечение по длительности: ровно один успех",
                  got, ["conflict", "ok"])

        got = race([
            {"adate": day, "atime": "16:00", "adoctor": "d3",
             "aservice": "consult", "aname": "Race Cinci", "aphone": "060555555"},
            {"adate": day, "atime": "16:00", "adoctor": "d4",
             "aservice": "consult", "aname": "Race Sase", "aphone": "060666666"},
        ])
        res.check("разные врачи не мешают друг другу", got, ["ok", "ok"])

        c = Client(s.url).login()
        res.check("слот после гонки действительно занят",
                  c.post("/admin/add", adate=day, atime="10:00", adoctor="d2",
                         aservice="consult", aname="Al Treilea",
                         aphone="060777777", back="/admin/all").msg, "conflict")


# ---------- ШАГ 4/7: сессия переживает hot-reload конфига ----------

def _worker_stale(tmpdir: str) -> None:
    """Диалог бота, под которым посреди флоу сменился clinic.json."""
    import asyncio
    import copy
    from datetime import date, timedelta

    base = pathlib.Path(tmpdir)
    os.environ.update({
        "CLINIC_CONFIG": str(base / "clinic.json"),
        "DATABASE_URL": f"sqlite:///{base / 'dental.db'}",
        "ADMIN_KEY": "", "TELEGRAM_TOKEN": "",
    })
    sys.path.insert(0, str(BOT))
    from app import db
    from app import engine as eng

    day = (date.today() + timedelta(days=1)).isoformat()

    async def to_confirm(sid: str, doc: str = "d2"):
        """Прогнать диалог до шага подтверждения, вернуть сессию."""
        s = eng.get_session(sid)
        await eng.handle(s, sid, "/start")
        await eng.handle(s, sid, "lang:ro")
        await eng.handle(s, sid, "book")
        await eng.handle(s, sid, "svc:consult")
        await eng.handle(s, sid, f"doc:{doc}")
        _texts, rows = await eng.handle(s, sid, f"day:{day}")
        slot = next(b["value"] for row in rows for b in row
                    if b["value"].startswith("time:"))
        await eng.handle(s, sid, slot)
        await eng.handle(s, sid, "Ion Stale")
        await eng.handle(s, sid, "skip_year")
        await eng.handle(s, sid, "069111222")
        return s

    def cfg_without_service(key: str) -> dict:
        cfg = copy.deepcopy(eng.CONFIG)
        cfg["services"] = [x for x in cfg["services"] if x["id"] != key]
        return cfg

    def cfg_doctor_off(dk: str) -> dict:
        cfg = copy.deepcopy(eng.CONFIG)
        for d in cfg["doctors"]:
            if d["id"] == dk:
                d["status"] = "concediu"
        return cfg

    async def main() -> None:
        await db.init([])
        try:
            fresh = copy.deepcopy(eng.CONFIG)

            # услугу удалили, пока пациент вводил имя и телефон
            s = await to_confirm("web:stale1")
            eng.apply_config(cfg_without_service("consult"))
            texts, _rows = await eng.handle(s, "web:stale1", "confirm")
            print("svc_gone_text", "actualizat" in " ".join(texts))
            print("svc_gone_state", s.state)
            from datetime import datetime
            mine = await db.my_appointments("web:stale1", datetime.now(eng.TZ))
            print("svc_gone_booked", len(mine))

            # врача выключили после выбора
            eng.apply_config(fresh)
            s = await to_confirm("web:stale2", doc="d2")
            eng.apply_config(cfg_doctor_off("d2"))
            texts, rows = await eng.handle(s, "web:stale2", "confirm")
            print("doc_off_text", "nu mai este disponibil" in " ".join(texts))
            print("doc_off_state", s.state)
            print("doc_off_offers",
                  any(b["value"].startswith("doc:") for row in rows for b in row))
            mine = await db.my_appointments("web:stale2", datetime.now(eng.TZ))
            print("doc_off_booked", len(mine))

            # услуга пропала, когда пациент только выбирал день
            eng.apply_config(fresh)
            s = eng.get_session("web:stale3")
            await eng.handle(s, "web:stale3", "/start")
            await eng.handle(s, "web:stale3", "lang:ro")
            await eng.handle(s, "web:stale3", "book")
            await eng.handle(s, "web:stale3", "svc:consult")
            await eng.handle(s, "web:stale3", "doc:d2")
            eng.apply_config(cfg_without_service("consult"))
            texts, _rows = await eng.handle(s, "web:stale3", f"day:{day}")
            print("day_stale_text", "actualizat" in " ".join(texts))

            # живой конфиг: тот же путь ДОЛЖЕН бронировать (валидация не
            # перетянула — иначе бот отбивал бы здоровые записи)
            eng.apply_config(fresh)
            s = await to_confirm("web:alive", doc="d3")
            texts, _rows = await eng.handle(s, "web:alive", "confirm")
            print("alive_booked", "Gata!" in " ".join(texts))
        finally:
            if db._CONN is not None:
                await db._CONN.close()

    asyncio.run(main())


def suite_stale_session(res: Result) -> None:
    """P1 аудита 08-20: clinic.json обновился ПОД живой сессией бота — услуги
    нет, врач в отпуске. Диалог обязан ответить словами и предложить выбор
    заново; трейсбек или запись к выключенному врачу — поломка."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_stale_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", base / "clinic.json")
        got = _run_worker("worker-stale", base)
        if not res.ok("проба поднялась", got["_rc"] == "0",
                      f"rc={got['_rc']}: {got['_stderr']}"):
            return
        res.check("удалённая услуга: ответ словами", got.get("svc_gone_text"),
                  "True")
        res.check("и выбор начинается заново", got.get("svc_gone_state"), "svc")
        res.check("запись НЕ создана", got.get("svc_gone_booked"), "0")
        res.check("выключенный врач: ответ словами", got.get("doc_off_text"),
                  "True")
        res.check("и предложен выбор врача", got.get("doc_off_offers"), "True")
        res.check("запись к выключенному НЕ создана", got.get("doc_off_booked"),
                  "0")
        res.check("пропажа услуги на шаге дня — тоже словами",
                  got.get("day_stale_text"), "True")
        res.check("живой конфиг бронирует как раньше", got.get("alive_booked"),
                  "True")
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ШАГ 5: удаление пациента атомарно ----------

def _worker_delete(tmpdir: str) -> None:
    """delete_patient_fully с искусственным обрывом ПОСРЕДИ удаления."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    base = pathlib.Path(tmpdir)
    os.environ.update({
        "CLINIC_CONFIG": str(base / "clinic.json"),
        "DATABASE_URL": f"sqlite:///{base / 'dental.db'}",
        "ADMIN_KEY": "", "TELEGRAM_TOKEN": "",
    })
    sys.path.insert(0, str(BOT))
    from app import db

    async def counts(pid: int) -> dict:
        out = {}
        for t in ("payments", "patient_alerts", "appointments", "activity"):
            out[t] = await db._fetchval(
                f"SELECT COUNT(*) FROM {t} WHERE patient_id = $1",
                f"SELECT COUNT(*) FROM {t} WHERE patient_id = ?", pid)
        out["patients"] = await db._fetchval(
            "SELECT COUNT(*) FROM patients WHERE id = $1",
            "SELECT COUNT(*) FROM patients WHERE id = ?", pid)
        return out

    async def main() -> None:
        await db.init([])
        try:
            pid = await db.create_patient("manual:c1rb", "Ion Rollback",
                                          "069000111")
            await db.add_payment(pid, 500, "numerar", "avans")
            await db.add_alert(pid, "warning", "alergie test")
            dt = datetime.now(timezone.utc) + timedelta(days=1)
            await db.add_visit_for_patient(pid, "Consultație", "Dr. Activ Doi",
                                           dt, doctor_id="d2",
                                           service_id="consult")
            before = await counts(pid)
            print("before_rows", sum(before.values()))
            # обрыв: седьмая таблица скрипта переименована, DELETE по ней
            # падает — всё удалённое ДО неё обязано откатиться целиком
            await db._CONN.execute("ALTER TABLE anamneza RENAME TO anamneza_x")
            await db._CONN.commit()
            try:
                await db.delete_patient_fully(pid)
                print("raised", False)
            except Exception:  # noqa: BLE001 — обрыв и есть проверяемое
                print("raised", True)
            print("intact", await counts(pid) == before)
            await db._CONN.execute("ALTER TABLE anamneza_x RENAME TO anamneza")
            await db._CONN.commit()
            await db.delete_patient_fully(pid)
            print("all_deleted", sum((await counts(pid)).values()) == 0)
        finally:
            if db._CONN is not None:
                await db._CONN.close()

    asyncio.run(main())


def suite_delete_rollback(res: Result) -> None:
    """P1 аудита 08-20: физическое стирание пациента (закон 195) обязано быть
    атомарным. Обрыв посреди раньше оставлял ПОЛУпациента: платежи стёрты,
    фиша на месте — и довершить нечем."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_del_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", base / "clinic.json")
        got = _run_worker("worker-delete", base)
        if not res.ok("проба поднялась", got["_rc"] == "0",
                      f"rc={got['_rc']}: {got['_stderr']}"):
            return
        res.ok("данные пациента на месте до удаления",
               int(got.get("before_rows", "0")) >= 5,
               f"before_rows={got.get('before_rows')!r}")
        res.check("обрыв посреди удаления — ошибка, не тишина",
                  got.get("raised"), "True")
        res.check("и НИ ОДНА строка не потеряна (откат целиком)",
                  got.get("intact"), "True")
        res.check("повторное удаление сносит всё", got.get("all_deleted"),
                  "True")
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ШАГ 6: сессии диалога — TTL и очистка PII ----------

def _worker_session(tmpdir: str) -> None:
    import asyncio
    import time
    from datetime import date, datetime, timedelta

    base = pathlib.Path(tmpdir)
    os.environ.update({
        "CLINIC_CONFIG": str(base / "clinic.json"),
        "DATABASE_URL": f"sqlite:///{base / 'dental.db'}",
        "ADMIN_KEY": "", "TELEGRAM_TOKEN": "",
    })
    sys.path.insert(0, str(BOT))
    from app import db
    from app import engine as eng

    day = (date.today() + timedelta(days=1)).isoformat()

    async def main() -> None:
        await db.init([])
        try:
            sid = "web:pii1"
            s = eng.get_session(sid)
            await eng.handle(s, sid, "/start")
            await eng.handle(s, sid, "lang:ro")
            await eng.handle(s, sid, "book")
            await eng.handle(s, sid, "svc:consult")
            await eng.handle(s, sid, "doc:d2")
            _t, rows = await eng.handle(s, sid, f"day:{day}")
            slot = next(b["value"] for row in rows for b in row
                        if b["value"].startswith("time:"))
            await eng.handle(s, sid, slot)
            await eng.handle(s, sid, "Ion Confidențial")
            await eng.handle(s, sid, "1985")
            await eng.handle(s, sid, "069555111")
            texts, _r = await eng.handle(s, sid, "confirm")
            print("booked", "Gata!" in " ".join(texts))
            print("pii_keys", ",".join(sorted(s.data)) or "-")
            leaked = any("Confidențial" in str(v) or "069555111" in str(v)
                         for v in s.data.values())
            print("pii_leaked", leaked)
            # «мои записи» и отмена живут по sid через БАЗУ — очистка сессии
            # их не задевает
            texts, rows = await eng.handle(s, sid, "my")
            print("my_lists", "Consultație" in " ".join(texts))
            cancel = next((b["value"] for row in rows for b in row
                           if b["value"].startswith("cancel:")), "")
            # чужая сессия с УГАДАННЫМ id: отмену фильтрует sid в самой БД
            s2 = eng.get_session("web:strain")
            await eng.handle(s2, "web:strain", "/start")
            await eng.handle(s2, "web:strain", "lang:ro")
            texts2, _r = await eng.handle(s2, "web:strain", cancel)
            print("foreign_cancel_refused",
                  "nu mai este activ" in " ".join(texts2))
            print("appt_survived_foreign", len(await db.my_appointments(
                sid, datetime.now(eng.TZ))))
            texts, _r = await eng.handle(s, sid, cancel)
            print("cancel_own", "anulat" in " ".join(texts).lower())

            # TTL: молчавшая сессия выметается, живая остаётся
            eng.get_session("web:old").last_seen = (
                time.time() - eng.SESSION_TTL - 60)
            eng.get_session("web:fresh")
            eng._last_sweep = 0.0            # форсируем подметание
            eng.get_session("web:trigger")
            print("old_evicted", "web:old" not in eng.SESSIONS)
            print("fresh_alive", "web:fresh" in eng.SESSIONS)
            print("stamped",
                  eng.SESSIONS["web:fresh"].last_seen > 0)
        finally:
            if db._CONN is not None:
                await db._CONN.close()

    asyncio.run(main())


def suite_session_pii(res: Result) -> None:
    """P1 аудита 08-20: SESSIONS рос вечно, а имя/телефон жили в ОЗУ бессрочно.
    После успешной брони в сессии остаётся только номер визита; молчавшие
    сессии выметаются по TTL — и ни то ни другое не задевает «мои записи» и
    отмену (они живут по sid через базу)."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_pii_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", base / "clinic.json")
        got = _run_worker("worker-session", base)
        if not res.ok("проба поднялась", got["_rc"] == "0",
                      f"rc={got['_rc']}: {got['_stderr']}"):
            return
        res.check("бронь через диалог прошла", got.get("booked"), "True")
        res.check("в сессии остался только номер визита",
                  got.get("pii_keys"), "last_appt")
        res.check("имя и телефон из ОЗУ убраны", got.get("pii_leaked"), "False")
        res.check("«мои записи» после очистки живы", got.get("my_lists"), "True")
        res.check("чужая сессия не отменяет по угаданному id",
                  got.get("foreign_cancel_refused"), "True")
        res.check("и запись при этом цела", got.get("appt_survived_foreign"),
                  "1")
        res.check("отмена своей записи жива", got.get("cancel_own"), "True")
        res.check("молчавшая сессия выметена по TTL", got.get("old_evicted"),
                  "True")
        res.check("живая сессия уцелела", got.get("fresh_alive"), "True")
        res.check("last_seen проставляется", got.get("stamped"), "True")
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------- ШАГ 7: CSRF на маршрутах без куки ----------

def suite_csrf_origin(res: Result) -> None:
    """P2 аудита 08-20. Аутентифицированные формы от CSRF закрыты кукой
    SameSite=Lax; но setup/login/recover живут ДО куки, и страница чужого
    сайта в браузере НА машине клиники могла бы отправить их сама: поставить
    первый PIN или накрутить счётчик подбора. Чужой Origin — отказ; свой и
    отсутствующий (не-браузер) — работают как раньше."""
    with Server(env={"ADMIN_KEY": ""}) as s:
        c = Client(s.url)
        evil = {"Origin": "http://atacator.example"}
        own = {"Origin": f"http://127.0.0.1:{s.port}"}

        r = c.post("/admin/setup", headers=evil, pin1="4321", pin2="4321")
        res.check("чужой Origin не ставит первый PIN", r.status, 403)
        res.ok("auth.json не создан", not (s.dir / "auth.json").exists(),
               "чужая страница назначила PIN клинике")
        r = c.post("/admin/setup", headers=own, pin1="4321", pin2="4321")
        res.ok("свой Origin (браузер программы) проходит",
               r.status == 303 and (s.dir / "auth.json").exists(),
               f"код {r.status}")

        # накрутка счётчика чужой страницей: пять «неудач» с чужим Origin
        # не должны стоить клинике блокировки
        for _ in range(5):
            Client(s.url).post("/admin/login", headers=evil,
                               password="0000", next="/admin")
        good = Client(s.url)
        r = good.post("/admin/login", password="4321", next="/admin")
        res.ok("чужие POST-ы не накрутили блокировку",
               "err=lock" not in r.location and good.get("/admin").status == 200,
               f"location {r.location!r} — счётчик посчитал чужой сайт")
        r = Client(s.url).post("/admin/login", headers=evil,
                               password="4321", next="/admin")
        res.check("вход с чужим Origin отбит даже с верным PIN", r.status, 403)
        ok2 = Client(s.url)
        r = ok2.post("/admin/login", headers=own, password="4321", next="/admin")
        res.ok("вход со своим Origin работает",
               r.status == 303 and ok2.get("/admin").status == 200,
               f"код {r.status}")


def suite_authfail_atomic(res: Result) -> None:
    """P2 аудита 08-20: auth_fail.json писался напрямую, и рваная запись
    (питание, антивирус) молча обнуляла счётчик подбора — битый файл читается
    как пустой. Теперь запись атомарная: сбой посреди оставляет ПРЕЖНЕЕ
    состояние, а не мусор."""
    import json as _json

    sys.path.insert(0, str(BOT))
    from app.core import auth

    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_fail_"))
    p = tmp_dir / "auth_fail.json"
    orig_path, orig_fsync = auth._fail_path, os.fsync
    try:
        auth._fail_path = lambda: p
        auth._fail_save({"fails": 3, "until": 0})
        res.check("состояние записано и читается",
                  _json.loads(p.read_text(encoding="utf-8")).get("fails"), 3)

        def cut(fd):
            raise OSError("simulated power loss")

        os.fsync = cut
        auth._fail_save({"fails": 0, "until": 0})   # «обрыв» посреди записи
        os.fsync = orig_fsync
        got = _json.loads(p.read_text(encoding="utf-8"))
        res.check("после обрыва счётчик НЕ обнулился", got.get("fails"), 3)
        res.ok("огрызок .tmp не остался",
               not p.with_name(p.name + ".tmp").exists(), "мусор рядом с файлом")
        auth._fail_save({"fails": 0, "until": 0})
        res.check("удачный вход по-прежнему обнуляет",
                  _json.loads(p.read_text(encoding="utf-8")).get("fails"), 0)
    finally:
        auth._fail_path = orig_path
        os.fsync = orig_fsync
        shutil.rmtree(tmp_dir, ignore_errors=True)


def suite_doc_ownership(res: Result) -> None:
    """P2 аудита 08-20 — проверка, что документ пациента не достаётся ни без
    входа, ни через ЧУЖУЮ фишу: скачивание за _guard, удаление сверяет
    patient_id и в маршруте, и в SQL."""
    with Server() as s:
        c = Client(s.url).login()
        pid_a = c.post("/admin/patients/new", name="Doc Owner",
                       phone="069010101").location.rsplit("/", 1)[-1].split("?")[0]
        pid_b = c.post("/admin/patients/new", name="Alt Pacient",
                       phone="069020202").location.rsplit("/", 1)[-1].split("?")[0]
        r = c.post_file(f"/admin/patient/{pid_a}/doc", "file", "scan.png",
                        b"\x89PNG\r\n\x1a\n" + b"x" * 64, category="alt")
        res.check("документ загружен", r.msg, "ok_doc")
        res.check("владелец скачивает", c.get("/admin/doc/1").status, 200)

        anon = Client(s.url)
        res.ok("без входа документ не отдаётся",
               anon.get("/admin/doc/1").status == 303
               and "/admin/login" in anon.get("/admin/doc/1").location,
               "файл пациента доступен без входа")
        res.check("и «открыть программой» без входа закрыто",
                  anon.post("/admin/doc/1/open").status, 303)
        anon.post(f"/admin/patient/{pid_a}/doc/1/del")
        res.check("удаление без входа не прошло", c.get("/admin/doc/1").status,
                  200)

        c.post(f"/admin/patient/{pid_b}/doc/1/del")   # чужая фиша в адресе
        res.check("удаление через чужую фишу не прошло",
                  c.get("/admin/doc/1").status, 200)
        c.post(f"/admin/patient/{pid_a}/doc/1/del")
        res.check("удаление владельцем работает", c.get("/admin/doc/1").status,
                  303)


_WORKERS = {
    "worker-setup": _worker_setup,
    "worker-stale": _worker_stale,
    "worker-delete": _worker_delete,
    "worker-session": _worker_session,
}

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in _WORKERS:
        _WORKERS[sys.argv[1]](sys.argv[2])
    else:
        print("Это файл наборов. Запускать: python tests\\run_tests.py hardening")
        sys.exit(2)
