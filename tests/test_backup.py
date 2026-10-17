"""Копии картотеки (17.10): сквозной путь, кнопка восстановления, расписание.

Посторонний разбор 17.10 назвал копии риском №1 и заметил: ни один тест не
распаковывал копию и не стартовал на ней программу. Здесь это и делается:

* `suite_roundtrip`      — архив с живого сервера → ПУСТАЯ папка данных →
                           сервер на ней видит тех же пациентов и документ.
* `suite_restore_button` — заказ со страницы (`/api/settings/backup/restore/*`),
                           исполнение «лаунчером» (`restore.apply_pending`),
                           старая база в стороне с датой, строка в ленте.
* `suite_restore_edges`  — архив в зашифрованную картотеку (переезд под
                           ключ), чужой пароль, чужой файл, zip-slip.
* `suite_schedule`       — локальная и внешняя копии раз в сутки под
                           поддельными часами, ротация, память дат.
* `suite_failure`        — отказ внешней копии: одна строка ленты на полосу,
                           баннер директора, снимается первой удачей.

⚠️ Сам `desktop.py` тестами неимпортируем; что он зовёт `restore` в нужном
порядке, проверяет `test_launcher.suite_autobackup` текстом.
"""
import io
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app.core import autobackup, dbkey, restore  # noqa: E402

from harness import (FIXTURES, TZ, Client, Clock, Result, Server, _rmtree_settled,  # noqa: E402
                     add_appt, clinic_now, clinic_today, new_patient, shell_signal)

PW = "parola-de-rezerva-2026"
TICK = {"DENTART_BACKUP_TICK_S": "0.3"}
NAMES = ("Restaurare Unu", "Restaurare Doi", "Restaurare Trei")


def _j(r) -> dict:
    return json.loads(r.body)


def _auto(c: Client) -> dict:
    return _j(c.get("/api/settings/backup"))["data"]["auto"]


def _auto_if(c: Client, failed: bool) -> dict | None:
    """Состояние внешней копии, когда отказ есть (failed) или снят."""
    a = _auto(c)
    return a if bool(a["ext_error"]) == failed else None


def _wait(cond, timeout: float = 15.0, every: float = 0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = cond()
        if got:
            return got
        time.sleep(every)
    return cond()


def _seed(c: Client) -> int:
    """Три пациента, визит, документ у первого. Возвращает id первого."""
    pids = [new_patient(c, n, phone=f"0690000{i:02d}") for i, n in enumerate(NAMES)]
    add_appt(c, (clinic_today() + timedelta(days=1)).isoformat(), "10:00", NAMES[0], "069000000")
    c.post_file(f"/api/patients/{pids[0]}/documents", "file", "radiografie.png",
                b"\x89PNG\r\n\x1a\n" + b"x" * 64, mime="image/png", category="radiografie")
    return pids[0]


def _names(c: Client) -> set:
    r = c.get("/api/patients?q=Restaurare&per=50")
    rows = _j(r)["data"]["rows"] if r.status == 200 else []
    return {row["name"] for row in rows}


def _docs(c: Client, pid: int) -> list:
    r = c.get(f"/api/patients/{pid}")
    return (_j(r)["data"].get("documents") or []) if r.status == 200 else []


def _feed(c: Client, kind_word: str) -> list:
    """Строки ленты «Activitate recentă» (аналитика) с нужным словом."""
    r = c.get("/api/stats")
    if r.status != 200:
        return []
    return [a for a in _j(r)["data"].get("activity", []) if kind_word in a["text"]]


def _export(c: Client, dest: pathlib.Path) -> pathlib.Path:
    r = c.post("/admin/backup/export", parola=PW)
    assert r.status == 200 and r.raw[:2] == b"PK", f"экспорт: {r.status} {r.body[:200]}"
    dest.write_bytes(r.raw)
    return dest


def _count(db_path: pathlib.Path, key: bytes | None = None) -> int:
    if key is None:
        con = sqlite3.connect(str(db_path))
    else:
        import sqlcipher3.dbapi2 as sqlcipher
        con = sqlcipher.connect(str(db_path))
        con.execute(f"PRAGMA key = {dbkey.pragma_value(key)}")
    try:
        return con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    finally:
        con.close()


# ---------- 1. архив → пустая папка → те же пациенты ----------

def suite_roundtrip(res: Result) -> None:
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_bk_rt_"))
    try:
        with Server() as s:
            c = Client(s.url).login()
            pid = _seed(c)
            res.check("логотип клиники загружен", c.post_file(
                "/api/settings/theme/logo", "file", "logo.png",
                b"\x89PNG\r\n\x1a\n" + b"x" * 64).msg, "ok_logo")
            archive = _export(c, work / "clinica.zip")

        # пустая папка данных: ни базы, ни clinic.json — так выглядит новый ПК
        empty = work / "nou"
        empty.mkdir()
        summary = restore.stage_archive(empty, archive, PW)
        res.check("приёмка видит трёх пациентов", summary["patients"], 3)
        res.check("приёмка видит документ", summary["documents"], 1)
        res.check("приёмка видит визит", summary["appointments"], 1)
        res.ok("приёмка называет клинику из архива", summary["clinic"],
               f"сводка: {summary}")
        res.ok("до подтверждения живого ничего нет: базы в папке нет",
               not (empty / "dental.db").exists() and restore.summary(empty) is not None,
               "приёмка тронула место живой базы")
        res.ok("заказ ложится файлом", restore.request(empty) and restore.pending(empty))
        out = restore.apply_pending(empty, empty)
        res.ok("лаунчер исполнил заказ", (out or "").startswith("restored"), f"ответ {out!r}")
        res.ok("заказа и приёмки больше нет",
               not restore.pending(empty) and not restore.stage_dir(empty).exists())
        res.ok("база, документы, профиль и логотип на месте",
               (empty / "dental.db").exists() and (empty / "clinic.json").exists()
               and (empty / "clinic-logo.png").exists()
               and any((empty / "files").rglob("*")),
               f"в папке: {sorted(p.name for p in empty.iterdir())}")
        res.ok("старой базы не было — и в сторону откладывать нечего",
               not list(empty.glob("dental.before-restore-*")))

        with Server(dir_=empty) as s2:
            c2 = Client(s2.url).login()
            res.check("сервер на восстановленной папке видит тех же пациентов",
                      _names(c2), set(NAMES))
            docs = _docs(c2, pid)
            res.ok("документ пациента открывается после восстановления",
                   any(d.get("filename") == "radiografie.png" for d in docs)
                   and c2.get(f"/admin/doc/{docs[0]['id']}").status == 200 if docs else False,
                   f"документы: {docs}")
            res.check("профиль клиники — из архива",
                      _j(c2.get("/api/settings/system"))["data"]["version"] != "", True)
            res.ok("запись о восстановлении — в ленте клиники",
                   _wait(lambda: _feed(c2, "restaurată")),
                   "лаунчер исполнил, а программа о нём не сказала")
            page = c2.get("/admin")
            res.ok("ложной тревоги auth.json после восстановления нет",
                   not shell_signal(page.body, "tamper")["shown"],
                   "восстановленная база помнила чужой отпечаток файла доступа")
    finally:
        _rmtree_settled(work)


# ---------- 2. кнопка: заказ со страницы, старая база в стороне ----------

def suite_restore_button(res: Result) -> None:
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_bk_btn_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", d / "clinic.json")
        with Server(dir_=d) as s:
            c = Client(s.url).login()
            _seed(c)
            made = autobackup.make_backup(d)       # копия «при старте» — как у лаунчера
            res.ok("локальная копия есть", made is not None and made.exists())
            # четвёртый пациент ПОСЛЕ копии: по нему видно, что вернулось старое
            new_patient(c, "Restaurare Patru", phone="069000099")

            data = _j(c.get("/api/settings/backup"))["data"]
            # копий может быть две: свою первую делает и цикл приложения
            res.ok("экран перечисляет локальные копии",
                   made.name in [x["name"] for x in data["restore"]["local"]],
                   f"список: {data['restore']['local']}")
            res.ok("заказа ещё нет", not data["restore"]["pending"] and data["restore"]["staged"] is None)

            res.check("подтверждать нечего — отказ", c.post_json(
                "/api/settings/backup/restore/confirm", {}).msg, "bad_rst_none")
            res.check("чужое имя копии отбито", c.post_json(
                "/api/settings/backup/restore/stage",
                {"kind": "local", "name": "../dental.db"}).msg, "bad_rst_src")

            r = c.post_json("/api/settings/backup/restore/stage",
                            {"kind": "local", "name": made.name})
            res.check("копия принята", r.msg, "ok_rst_staged")
            st = _j(r)["data"]["restore"]["staged"]
            res.ok("перед подтверждением видно, что внутри: 3 пациента (не 4)",
                   st and st["patients"] == 3 and st["kind"] == "local", f"сводка: {st}")
            res.check("отказ снимает приёмку", _j(c.post_json(
                "/api/settings/backup/restore/cancel", {}))["data"]["restore"]["staged"], None)

            c.post_json("/api/settings/backup/restore/stage", {"kind": "local", "name": made.name})
            r = c.post_json("/api/settings/backup/restore/confirm", {})
            res.check("восстановление заказано", r.msg, "ok_rst_ordered")
            res.ok("заказ лежит рядом с базой", restore.pending(d))
            res.ok("живая база НЕ тронута, пока программа работает",
                   _names(c) == set(NAMES) | {"Restaurare Patru"},
                   "подмена под открытым соединением")

        # «следующий старт»: лаунчер исполняет заказ до старта приложения
        out = restore.apply_pending(d, d)
        res.ok("лаунчер исполнил заказ", (out or "").startswith("restored"), f"ответ {out!r}")
        aside = sorted(d.glob("dental.before-restore-*.db"))
        res.ok("старая база ушла в сторону с датой, не удалена", len(aside) == 1,
               f"найдено: {[p.name for p in aside]}")
        res.check("в отложенной базе — все четверо", _count(aside[0]) if aside else -1, 4)
        res.ok("-wal/-shm старой базы не остались под новой",
               not (d / "dental.db-wal").exists() and not (d / "dental.db-shm").exists())
        res.ok("повторный старт ничего не делает", restore.apply_pending(d, d) is None)

        with Server(dir_=d) as s:
            c = Client(s.url).login()
            res.check("после перезапуска — трое, четвёртого нет", _names(c), set(NAMES))
            res.ok("лента: восстановлено из копии, старая база названа",
                   any("before-restore" in a["text"] for a in _wait(lambda: _feed(c, "restaurată")) or []),
                   "строки о восстановлении нет или она не называет отложенную базу")
            res.ok("тревоги auth.json нет",
                   not shell_signal(c.get("/admin").body, "tamper")["shown"])
    finally:
        _rmtree_settled(d)


# ---------- 3. края: шифрование, чужой пароль, чужой файл, zip-slip ----------

def suite_restore_edges(res: Result) -> None:
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_bk_edge_"))
    try:
        with Server() as s:
            c = Client(s.url).login()
            _seed(c)
            archive = _export(c, work / "clinica.zip")

        # -- чужой пароль / чужой файл / нет файла --
        empty = work / "a"
        empty.mkdir()
        for label, src, pw, code in (
                ("неверный пароль", archive, "parola-gresita!!", "bad_rst_pass"),
                ("не архив", work / "clinica.zip", None, None),
                ("файла нет", work / "lipsa.zip", PW, "bad_rst_src")):
            if code is None:
                continue
            try:
                restore.stage_archive(empty, src, pw)
                got = "ok"
            except restore.RestoreError as e:
                got = e.code
            res.check(f"{label} — {code}", got, code)
        plain = work / "plain.zip"
        with zipfile.ZipFile(plain, "w") as z:
            z.writestr("data/dental.db", b"not a database at all")
        try:
            restore.stage_archive(empty, plain, PW)
            got = "ok"
        except restore.RestoreError as e:
            got = e.code
        res.check("не наша база внутри — bad_rst_file", got, "bad_rst_file")
        res.ok("после отказа приёмка пуста", restore.summary(empty) is None
               and not restore.stage_dir(empty).exists())

        # -- zip-slip: имя записи не выводит за приёмку --
        import pyzipper
        evil = work / "evil.zip"
        src_db = work / "src.db"
        con = sqlite3.connect(str(src_db))
        con.executescript("CREATE TABLE patients(id INTEGER PRIMARY KEY); "
                          "CREATE TABLE appointments(id INTEGER PRIMARY KEY); "
                          "CREATE TABLE documents(id INTEGER PRIMARY KEY); "
                          "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT);")
        con.commit()
        con.close()
        with pyzipper.AESZipFile(evil, "w", encryption=pyzipper.WZ_AES) as z:
            z.setpassword(PW.encode())
            z.write(src_db, "data/dental.db")
            z.writestr("../evil.txt", "x")
            z.writestr("data/files/../../evil2.txt", "x")
            z.writestr("dental.env", "TELEGRAM_TOKEN=stolen")
        restore.stage_archive(empty, evil, PW)
        res.ok("записи с `..` и чужие файлы не распакованы",
               not (work / "evil.txt").exists() and not (empty / "evil.txt").exists()
               and not (empty / "evil2.txt").exists()
               and not (restore.stage_dir(empty) / "dental.env").exists(),
               f"в work: {sorted(p.name for p in work.iterdir())}")
        restore.cancel(empty)

        # -- архив в ЗАШИФРОВАННУЮ картотеку: база переезжает под ключ --
        enc = work / "enc"
        enc.mkdir()
        key = dbkey.generate()
        if not dbkey.store(key, enc):
            res.ok("DPAPI доступен для ключа", False, "не Windows — ветка шифрования не проверена")
            return
        restore.stage_archive(enc, archive, PW)
        restore.request(enc)
        out = restore.apply_pending(enc, enc)
        res.ok("заказ исполнен и на шифре", (out or "").startswith("restored"), f"{out!r}")
        res.ok("восстановленная база лежит ПОД КЛЮЧОМ клиники",
               dbkey.opens_with(enc / "dental.db", key) and not dbkey.opens_with(enc / "dental.db", None),
               "база из архива осталась открытой рядом с db.key")
        with Server(dir_=enc) as s:
            c = Client(s.url).login()
            res.check("программа на шифре видит восстановленных пациентов", _names(c), set(NAMES))
            # локальная копия ПОД КЛЮЧОМ принимается; «чужая» (открытая) — тоже,
            # как копия до включения шифрования; мусор — нет
            made = autobackup.make_backup(enc)
            r = c.post_json("/api/settings/backup/restore/stage", {"kind": "local", "name": made.name})
            res.ok("копия под ключом принята и посчитана", r.msg == "ok_rst_staged"
                   and _j(r)["data"]["restore"]["staged"]["patients"] == 3
                   and _j(r)["data"]["restore"]["staged"]["encrypted"], r.body[:300])
            (enc / "backups" / "dental_20200101_000000_1.db").write_bytes(b"garbage" * 10)
            r = c.post_json("/api/settings/backup/restore/stage",
                            {"kind": "local", "name": "dental_20200101_000000_1.db"})
            res.check("мусор под именем копии — bad_rst_file", r.msg, "bad_rst_file")
    finally:
        _rmtree_settled(work)


# ---------- 4. расписание ----------

def _env_server(d: pathlib.Path, dest: pathlib.Path | None = None, **extra) -> Server:
    env_path = d / "dental.env"
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")
    return Server(dir_=d, env={**TICK, "DENTART_ENV_FILE": str(env_path), **extra})


def _local(d: pathlib.Path) -> list:
    return sorted((d / "backups").glob("dental_*.db")) if (d / "backups").is_dir() else []


def _ext(dest: pathlib.Path) -> list:
    return sorted(dest.glob("dentpilot-auto-*.zip"))


def suite_schedule(res: Result) -> None:
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_bk_sch_"))
    dest = pathlib.Path(tempfile.mkdtemp(prefix="dp_bk_dest_"))
    shutil.copy(FIXTURES / "clinic_test.json", d / "clinic.json")
    try:
        start = clinic_now().replace(microsecond=0)
        with Clock(start) as clock:
            with _env_server(d) as s:
                c = Client(s.url).login()
                _seed(c)
                res.ok("без лаунчера локальная копия всё равно появляется",
                       _wait(lambda: _local(d)), "цикл не сделал первую копию")
                n_local = len(_local(d))

                # -- настройка внешней копии --
                res.check("папка внутри папки данных отбита", c.post_json(
                    "/api/settings/backup/auto", {"folder": str(d), "password": PW}).msg, "bad_bkp_inside")
                res.check("несуществующая папка отбита", c.post_json(
                    "/api/settings/backup/auto", {"folder": str(dest / "nu-exista"), "password": PW}).msg,
                    "bad_bkp_folder")
                res.check("короткий пароль отбит", c.post_json(
                    "/api/settings/backup/auto", {"folder": str(dest), "password": "scurt"}).msg,
                    "bad_bkp_pass")
                res.check("папка без пароля отбита", c.post_json(
                    "/api/settings/backup/auto", {"folder": str(dest), "password": ""}).msg,
                    "bad_bkp_pass")
                res.check("«сделать сейчас» до настройки — отказ", c.post_json(
                    "/api/settings/backup/auto/run", {}).msg, "bad_bkp_unset")
                r = c.post_json("/api/settings/backup/auto", {"folder": str(dest), "password": PW})
                res.check("внешняя копия настроена", r.msg, "ok_bkp_auto")
                res.ok("первый архив — сразу после настройки", _wait(lambda: _ext(dest)),
                       "цикл не проснулся по wake()")
                env_text = (d / "dental.env").read_text(encoding="utf-8")
                res.ok("пароль — в dental.env и не открытым текстом",
                       "DENTART_BACKUP_PASS=" in env_text and PW not in env_text,
                       env_text[:200])
                data = _j(c.get("/api/settings/backup"))["data"]
                res.ok("экран показывает дату внешней копии фактом",
                       data["auto"]["ext_at"] and data["auto"]["has_pass"] and not data["auto"]["alert"],
                       repr(data["auto"]))
                sysd = _j(c.get("/api/settings/system"))["data"]["backup"]
                res.ok("Stare sistem называет папку и дату", str(dest) in sysd["external"]
                       and sysd["tone"] == "ok" and sysd["local"] not in ("", "încă nu s-a făcut"), repr(sysd))
                res.ok("архивы перечислены для восстановления",
                       [a["name"] for a in data["restore"]["archives"]] == [p.name for p in _ext(dest)][::-1],
                       repr(data["restore"]["archives"]))

                # -- архив открывается тем же паролем, тем же форматом --
                import pyzipper
                z = pyzipper.AESZipFile(io.BytesIO(_ext(dest)[0].read_bytes()))
                z.setpassword(PW.encode())
                res.ok("архив — тот же формат, что у ручного экспорта",
                       {"CITESTE-MA.txt", "data/dental.db", "clinic.json"} <= set(z.namelist())
                       and z.read("data/dental.db")[:15] == b"SQLite format 3", str(z.namelist()))

                # -- через два часа ничего нового --
                n_ext = len(_ext(dest))
                clock.set(start + timedelta(hours=2))
                time.sleep(1.2)
                res.ok("через два часа копий не прибавилось",
                       len(_local(d)) == n_local and len(_ext(dest)) == n_ext,
                       f"local {len(_local(d))}/{n_local}, ext {len(_ext(dest))}/{n_ext}")
                # -- через сутки с небольшим — обе снова --
                clock.set(start + timedelta(hours=25))
                res.ok("через сутки — новая локальная копия",
                       _wait(lambda: len(_local(d)) > n_local), f"{len(_local(d))}")
                res.ok("через сутки — новый внешний архив",
                       _wait(lambda: len(_ext(dest)) > n_ext), f"{len(_ext(dest))}")
                # -- ротация своих: лишние уходят, чужой zip не трогается --
                for i in range(10):
                    (dest / f"dentpilot-auto-2020010{i}_0000.zip").write_bytes(b"old")
                (dest / "dentpilot-backup-manual.zip").write_bytes(b"manual")
                clock.set(start + timedelta(hours=50))
                _wait(lambda: not (dest / "dentpilot-auto-20200100_0000.zip").exists())
                res.ok("ротация держит не больше KEEP_EXT своих архивов",
                       len(_ext(dest)) <= 7, f"{len(_ext(dest))}")
                res.ok("ручной архив в той же папке ротация не трогает",
                       (dest / "dentpilot-backup-manual.zip").exists())
                # -- выключение --
                res.check("выключить — пустая папка", c.post_json(
                    "/api/settings/backup/auto", {"folder": "", "password": ""}).msg, "ok_bkp_off")
                r = c.post_json("/api/settings/backup/auto", {"folder": str(dest), "password": ""})
                res.check("включить снова без пароля — сохранённый остаётся", r.msg, "ok_bkp_auto")

            # память переживает перезапуск: дата и пароль
            with _env_server(d) as s:
                c = Client(s.url).login()
                data = _j(c.get("/api/settings/backup"))["data"]
                res.ok("после перезапуска: папка, пароль и дата помнятся",
                       data["auto"]["folder"] == str(dest) and data["auto"]["has_pass"]
                       and data["auto"]["ext_at"], repr(data["auto"]))
    finally:
        _rmtree_settled(d)
        _rmtree_settled(dest)


# ---------- 5. неудача: лента и баннер ----------

def suite_failure(res: Result) -> None:
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_bk_fail_"))
    dest = pathlib.Path(tempfile.mkdtemp(prefix="dp_bk_fdest_"))
    shutil.copy(FIXTURES / "clinic_test.json", d / "clinic.json")
    try:
        start = clinic_now().replace(microsecond=0)
        with Clock(start) as clock:
            with _env_server(d) as s:
                c = Client(s.url).login()
                _seed(c)
                c.post_json("/api/settings/backup/auto", {"folder": str(dest), "password": PW})
                res.ok("первый архив сделан", _wait(lambda: _ext(dest)))
                res.ok("баннера нет, пока всё в порядке",
                       not shell_signal(c.get("/admin").body, "backup")["shown"])

                # папка исчезла (флешку вынули) — следующая суточная копия падает
                shutil.rmtree(dest)
                clock.set(start + timedelta(hours=25))
                data = _wait(lambda: _auto_if(c, True))
                res.ok("отказ виден на экране словами", bool(data and data["ext_error"]), repr(data))
                rows = _wait(lambda: _feed(c, "externă nu s-a făcut"))
                res.check("в ленте клиники — одна строка об отказе", len(rows or []), 1)
                sig = shell_signal(c.get("/admin").body, "backup")
                res.ok("директор видит янтарный баннер на главной",
                       sig["shown"] and "nu s-a făcut" in sig["html"] and "/admin/settings/backup" in sig["html"],
                       repr(sig))
                res.check("Stare sistem — тон warn", _j(c.get("/api/settings/system"))["data"]["backup"]["tone"],
                          "warn")
                r = c.post_json("/api/settings/backup/auto/run", {})
                res.ok("«сделать сейчас» отвечает отказом с причиной",
                       r.msg == "bad_bkp_auto" and r.status == 500, r.body[:200])

                # полоса одинаковых отказов — по-прежнему одна строка
                clock.set(start + timedelta(hours=26))
                time.sleep(1.5)
                res.check("повторный отказ строку не дублирует",
                          len(_feed(c, "externă nu s-a făcut")), 1)

                # папка вернулась — копия удаётся, баннер гаснет
                dest.mkdir()
                clock.set(start + timedelta(hours=27))
                res.ok("после возвращения папки копия удалась", _wait(lambda: _ext(dest)))
                data = _wait(lambda: _auto_if(c, False))
                res.ok("отказ снят", bool(data) and data["ext_error"] == "", repr(data))
                res.ok("баннер погас", not shell_signal(c.get("/admin").body, "backup")["shown"])

            # отказ помнится через перезапуск, пока копия не удастся
            shutil.rmtree(dest)
            with Clock(start + timedelta(hours=52)) as clock:
                with _env_server(d) as s:
                    c = Client(s.url).login()
                    data = _wait(lambda: _auto_if(c, True))
                    res.ok("после перезапуска отказ снова виден", bool(data), "память отказа не пережила старт")
                    # удача между отказами закрыла прежнюю полосу: новая полоса —
                    # новая строка (вторая), а её повторы — нет
                    res.check("новая полоса отказов — вторая строка, не третья",
                              len(_feed(c, "externă nu s-a făcut")), 2)
                    clock.set(start + timedelta(hours=53))
                    time.sleep(1.5)
                    res.check("повтор в той же полосе после перезапуска строку не дублирует",
                              len(_feed(c, "externă nu s-a făcut")), 2)
    finally:
        _rmtree_settled(d)
        if dest.exists():
            _rmtree_settled(dest)
