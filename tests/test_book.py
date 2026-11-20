"""Визит фише по номеру — `core/book.py`: одно правило для переноса из Google и импорта.

Правило зовётся из движка, маршрута у него нет, поэтому набор гоняет его отдельным интерпретатором
на своей папке клиники (как `test_rooms.suite_room_race`): в общем процессе `app.db` уже открыт с
чужим `DATABASE_URL`. Даты — от сегодня клиники, иначе набор позеленел бы, когда «будущее» уйдёт
в прошлое.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone

from harness import BOT, FIXTURES, PYTHON, Result, _rmtree_settled

SRC = BOT / "app" / "core" / "book.py"


def _worker(tmpdir: str) -> None:
    import asyncio

    base = pathlib.Path(tmpdir)
    os.environ.update({"CLINIC_CONFIG": str(base / "clinic.json"),
                       "DATABASE_URL": f"sqlite:///{base / 'dental.db'}", "ADMIN_KEY": ""})
    sys.path.insert(0, str(BOT))
    from app import db
    from app import engine as eng
    from app.core import book

    out: dict = {}

    async def row(aid):
        r = await db._fetch("SELECT patient_id, doctor_id, starts_at, duration_min, duration_set, "
                            "status, comment, service_id, source FROM appointments WHERE id = ?", aid)
        if not r:
            return None
        x = dict(r[0])
        x["starts_at"] = x["starts_at"].isoformat() if hasattr(x["starts_at"], "isoformat") \
            else x["starts_at"]
        return x

    async def raw_start(aid):
        con = db._CONN
        cur = await con.execute("SELECT starts_at FROM appointments WHERE id = ?", (aid,))
        got = await cur.fetchone()
        await cur.close()
        return got[0]

    async def main() -> None:
        await db.init([])
        try:
            today = datetime.now(eng.TZ).date()
            fut, past = today + timedelta(days=3), today - timedelta(days=3)
            pid = await db.create_patient("manual:bk1", "Bk Unu", "")
            other = await db.create_patient("manual:bk2", "Bk Doi", "")
            at = book.wall(fut, time(10, 0))
            out["wall_tz"] = str(at.tzinfo)

            b = await book.book_visit(pid, "d2", at, "consult", comment="Fișier: 09:58")
            out["ok"] = [b.code, b.ok]
            out["ok_row"] = await row(b.appt_id)
            out["ok_raw"] = await raw_start(b.appt_id)
            out["ok_sms"] = await db._fetchval("SELECT sms_off FROM patients WHERE id = ?", pid)
            n0 = await db._fetchval("SELECT COUNT(*) FROM appointments")

            out["dup"] = (await book.book_visit(pid, "d3", at, "consult")).code
            out["conflict"] = (await book.book_visit(other, "d2", at + timedelta(minutes=30),
                                                     "consult")).code
            out["refusals"] = {
                "bad_doctor": (await book.book_visit(other, "dX", at, "consult")).code,
                "bad_service": (await book.book_visit(other, "d2", at, "nope")).code,
                "no_start": (await book.book_visit(other, "d2", None, "consult")).code,
                "not_agenda": (await book.book_visit(other, "d2", at, "onlyplan")).code,
                "dur_7": (await book.book_visit(other, "d3", at, "consult", minutes=7)).code,
                "dur_0": (await book.book_visit(other, "d3", at, "consult", minutes=0)).code,
                "dur_300": (await book.book_visit(other, "d3", at, "consult", minutes=300)).code,
                "off": (await book.book_visit(other, "d1", at, "consult")).code,
                "minute": (await book.book_visit(other, "d3", at + timedelta(minutes=7),
                                                 "consult")).code,
                "night": (await book.book_visit(other, "d3", book.wall(fut, time(22, 0)),
                                                "consult")).code,
                "room": (await book.book_visit(other, "d3", at, "consult", room="nope")).code,
            }
            out["refused_wrote"] = await db._fetchval("SELECT COUNT(*) FROM appointments") - n0

            b = await book.book_visit(other, "d3", at, "consult", minutes=45)
            out["minutes"] = [b.code, await row(b.appt_id)]

            b = await book.book_visit(pid, "d2", book.wall(past, time(11, 0)), "consult", done=True)
            out["past_done"] = [b.code, await row(b.appt_id)]
            b = await book.book_visit(other, "d2", book.wall(past, time(11, 0)), "consult")
            out["past"] = [b.code, await row(b.appt_id)]

            n1 = await db._fetchval("SELECT COUNT(*) FROM appointments")
            out["probe"] = {
                "free": await book.probe(pid, "d2", at + timedelta(hours=2), "consult"),
                "taken": await book.probe(None, "d2", at, "consult"),
                "dup": await book.probe(pid, "d4", at, "consult"),
                "past": await book.probe(pid, "d2", book.wall(past, time(15, 0)), "consult"),
                "refusal": await book.probe(pid, "d2", at, "consult", minutes=7),
                "other_doctor": await book.probe(None, "d4", at, "consult"),
            }
            out["probe_wrote"] = await db._fetchval("SELECT COUNT(*) FROM appointments") - n1
            # перевод часов: 28.03.2027 Кишинёв уходит с UTC+2 на UTC+3
            out["dst"] = [book.wall(date(2027, 3, 27), time(9, 0)).utcoffset().total_seconds(),
                          book.wall(date(2027, 3, 29), time(9, 0)).utcoffset().total_seconds()]
        finally:
            await db.close()
        print(json.dumps(out, ensure_ascii=False, default=str))

    asyncio.run(main())


def suite(res: Result) -> None:
    """Отказы и удачи кодами окна записи журнала; проба не пишет; время клиники → UTC."""
    if not res.ok("исходники нашлись", SRC.exists(), str(SRC)):
        return
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_book_"))
    try:
        cfg = json.loads((FIXTURES / "clinic_test.json").read_text(encoding="utf-8"))
        cfg["services"].append({"id": "onlyplan", "ro": "Doar în plan", "ru": "Только план",
                                "where": "plan", "price": "100 MDL"})
        (base / "clinic.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([str(PYTHON), str(pathlib.Path(__file__).resolve()), "worker", str(base)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, env=dict(os.environ))
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("{")]
        if not res.ok("проба поднялась", r.returncode == 0 and len(lines) == 1,
                      f"rc={r.returncode}: {(r.stdout or '')[-600:]} {(r.stderr or '')[-1500:]}"):
            return
        got = json.loads(lines[0])
    finally:
        _rmtree_settled(base)

    ok_row = got["ok_row"] or {}
    res.check("визит будущего — «ok», запись есть", got["ok"], ["ok", True])
    res.check("визит лёг этой фише, врачу и услуге, источник manual, комментарий записан",
              [ok_row.get(k) for k in ("doctor_id", "service_id", "source", "comment", "duration_min",
                                       "duration_set")],
              ["d2", "consult", "manual", "Fișier: 09:58", 60, 0])
    res.check("стенное время клиники", got["wall_tz"], "Europe/Chisinau")
    raw = got["ok_raw"]
    stored = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    res.ok("в базе — UTC, тот же момент, что 10:00 по часам клиники",
           stored.utcoffset() == timedelta(0) and stored.astimezone(timezone.utc).hour in (7, 8),
           raw)
    res.check("галочки SMS не было — согласие пациента не тронуто", got["ok_sms"], 0)
    res.check("у пациента уже есть запись на этот час — «dup», раньше занятости врача",
              got["dup"], "dup")
    res.check("врач занят пересечением по минутам — «conflict»", got["conflict"], "conflict")
    res.check("отказы — коды окна записи журнала, в порядке его проверок", got["refusals"], {
        "bad_doctor": "bad", "bad_service": "bad", "no_start": "bad", "not_agenda": "svc_not_agenda",
        "dur_7": "bad_dur", "dur_0": "bad_dur", "dur_300": "bad_dur", "off": "bad_off",
        "minute": "bad_time", "night": "outside", "room": "bad_room"})
    res.check("отказ ничего не записал", got["refused_wrote"], 0)
    code, m = got["minutes"]
    res.check("длительность не услуги — своя длина и признак «задана руками»",
              [code, m["duration_min"], m["duration_set"]], ["ok", 45, 1])
    code, pd = got["past_done"]
    res.check("прошедший день с done — «finalizată» одним шагом", [code, pd["status"]],
              ["ok_past_done", "done"])
    code, p = got["past"]
    res.check("прошедший день без done — предупреждение, статус не тронут",
              [code, p["status"] != "done"], ["ok_past", True])
    res.check("проба отвечает тем же кодом, что дала бы запись", got["probe"], {
        "free": "ok", "taken": "conflict", "dup": "dup", "past": "ok_past", "refusal": "bad_dur",
        "other_doctor": "ok"})
    res.check("проба ничего не записала", got["probe_wrote"], 0)
    res.check("перевод часов учтён поясом: 09:00 до и после — разный сдвиг",
              got["dst"], [7200.0, 10800.0])


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        _worker(sys.argv[2])
    else:
        print("Это файл наборов. Запускать: python tests\\run_tests.py «Визит фише»")
        sys.exit(2)
