"""Миграции базы и разовый backfill летописи — на базе, какой она БЫВАЕТ у
клиники, а не на пустой.

Два набора и два разных вопроса:

* `suite_v4` — база, домигрированная до версии 3 кодом до 08-13: uq-индексы
  со старым предикатом IN ('confirmed','arrived'). Шаг 4 существовал в обоих
  словарях миграций, но SCHEMA_VERSION осталась 3, и цикл _migrate до него не
  доходил НИКОГДА — waiting-визит был вне страховки от двойной брони, молча.
  Сторож «missing migration step» ловит только отсутствующие шаги, не лишние.
* `suite_backfill_tz` — перенос старых визитов в летопись. Живой путь
  (_log_booking) печатает час клиники, backfill печатал UTC: у клиники с
  историей каждая перенесённая строка показывала бы чужой час НАВСЕГДА —
  текст события хранится строкой и не пересчитывается.

Фикстурная база собирается сырым sqlite3 — это ТЕСТ-СТОРОНА (как в
test_dbcrypt._plain_db), программа по-прежнему ходит только через db.
"""
import pathlib
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import db as appdb  # noqa: E402 — только константы схем, не соединение

from harness import Result, Server  # noqa: E402

# Предикат, который шаги 2–3 ставили ДО появления 'waiting' (08-13): ровно так
# выглядят индексы у реальной клиники, чья база остановилась на версии 3.
_OLD_ACT = "('confirmed','arrived')"


def _base_db(path: pathlib.Path) -> sqlite3.Connection:
    """Пустая база по СЕГОДНЯШНИМ схемам программы + колонка doctor_id
    (в проде её добавляет init через SQLITE_EXTRA_COLS)."""
    con = sqlite3.connect(str(path))
    con.executescript(appdb.SQLITE_SCHEMA)
    con.executescript(appdb.SQLITE_CARD_SCHEMA)
    con.execute("ALTER TABLE appointments ADD COLUMN doctor_id TEXT")
    return con


def _index_sql(dbfile: pathlib.Path) -> dict[str, str]:
    con = sqlite3.connect(str(dbfile))
    try:
        rows = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'uq_%'").fetchall()
        return {name: sql or "" for name, sql in rows}
    finally:
        con.close()


def suite_v4(res: Result) -> None:
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_"))
    try:
        dbfile = work / "dental.db"
        con = _base_db(dbfile)
        # индексы в том виде, в каком их оставили шаги 2–3 у клиники
        for name in ("uq_doctor_slot", "uq_patient_slot", "uq_doctor_slot_id"):
            con.execute(f"DROP INDEX IF EXISTS {name}")
        con.execute(f"""CREATE UNIQUE INDEX uq_doctor_slot
            ON appointments(doctor, starts_at) WHERE status IN {_OLD_ACT}""")
        con.execute(f"""CREATE UNIQUE INDEX uq_patient_slot
            ON appointments(patient_id, starts_at) WHERE status IN {_OLD_ACT}""")
        con.execute(f"""CREATE UNIQUE INDEX uq_doctor_slot_id
            ON appointments(doctor_id, starts_at)
            WHERE status IN {_OLD_ACT} AND doctor_id IS NOT NULL""")
        con.execute("INSERT INTO schema_meta(key, value) VALUES('version', '3')")
        # летопись уже перенесена — этот набор не про backfill
        con.execute("INSERT INTO schema_meta(key, value) VALUES('act_backfill', '1')")
        # индексы пересоздаются НАД данными, а не над пустой таблицей
        con.execute("INSERT INTO patients(session_key, name, phone, created_at) "
                    "VALUES('manual:60000001', 'Ion Test', '060000001', "
                    "'2026-01-10T08:00:00+00:00')")
        con.execute("INSERT INTO appointments(patient_id, service, doctor, "
                    "starts_at, status, source, created_at, doctor_id) "
                    "VALUES(1, 'Consultație', 'Dr. Activ Doi', "
                    "'2026-01-12T07:00:00+00:00', 'confirmed', 'admin', "
                    "'2026-01-10T08:05:00+00:00', 'd2')")
        con.commit()
        con.close()

        with Server(dir_=work):
            pass                              # старт = init + _migrate

        con = sqlite3.connect(str(dbfile))
        ver = con.execute(
            "SELECT value FROM schema_meta WHERE key='version'").fetchone()[0]
        con.close()
        res.check("база с версии 3 домигрирована до 4", ver, "4")

        idx = _index_sql(dbfile)
        for name in ("uq_doctor_slot", "uq_patient_slot", "uq_doctor_slot_id"):
            res.ok(f"{name} покрывает 'waiting'", "waiting" in idx.get(name, ""),
                   f"предикат остался старым: {idx.get(name)!r}")

        # идемпотентность: второй старт на уже домигрированной базе
        with Server(dir_=work):
            pass
        con = sqlite3.connect(str(dbfile))
        ver = con.execute(
            "SELECT value FROM schema_meta WHERE key='version'").fetchone()[0]
        con.close()
        res.check("повторный старт ничего не ломает (версия та же)", ver, "4")
        idx = _index_sql(dbfile)
        res.ok("повторный старт не откатывает предикат",
               all("waiting" in idx.get(n, "")
                   for n in ("uq_doctor_slot", "uq_patient_slot",
                             "uq_doctor_slot_id")),
               f"индексы после рестарта: {idx!r}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_backfill_tz(res: Result) -> None:
    # 09:00 Кишинёва; UTC-эквивалент считается zoneinfo, а не руками — иначе
    # тест сам наступил бы на грабли летнего/зимнего времени
    local = datetime(2026, 1, 15, 9, 0, tzinfo=ZoneInfo("Europe/Chisinau"))
    starts = local.astimezone(timezone.utc).isoformat(timespec="seconds")
    utc_hhmm = local.astimezone(timezone.utc).strftime("%H:%M")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_bf_"))
    try:
        con = _base_db(work / "dental.db")
        con.execute("INSERT INTO patients(session_key, name, phone, created_at) "
                    "VALUES('manual:60000002', 'Ana Test', '060000002', "
                    "'2026-01-10T08:00:00+00:00')")
        con.execute("INSERT INTO appointments(patient_id, service, doctor, "
                    "starts_at, status, source, created_at, doctor_id) "
                    "VALUES(1, 'Igienizare', 'Dr. Activ Trei', ?, 'confirmed', "
                    "'admin', '2026-01-10T08:05:00+00:00', 'd3')", (starts,))
        con.commit()
        con.close()

        with Server(dir_=work):
            pass                              # старт = init + _backfill_activity

        con = sqlite3.connect(str(work / "dental.db"))
        rows = con.execute("SELECT text FROM activity "
                           "WHERE kind='appt_new'").fetchall()
        con.close()
        res.check("backfill перенёс визит в летопись", len(rows), 1)
        text = rows[0][0] if rows else ""
        res.ok("час в тексте события — час клиники, не UTC",
               "09:00" in text,
               f"визит на 09:00 Кишинёва записан как {text!r} "
               f"(UTC был бы {utc_hhmm})")
    finally:
        shutil.rmtree(work, ignore_errors=True)
