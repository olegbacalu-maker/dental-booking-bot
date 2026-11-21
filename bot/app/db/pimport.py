"""Импорт пациентов из файла: запись об импорте, метка фиши, индекс для
поиска дублей. Строки самого файла в базе не лежат."""
from __future__ import annotations

from .. import db
from .conn import _execute, _fetch, _iso, _utcnow_iso
from .events import _actor_now
from .patients import PATIENT_FIELDS

# В записи об импорте нет данных пациентов: только счётчики и имя файла.
IMPORT_DDL = """
CREATE TABLE IF NOT EXISTS patient_imports(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  file_name TEXT NOT NULL DEFAULT '',
  rows INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL DEFAULT 0,
  filled INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  removed INTEGER NOT NULL DEFAULT 0,
  undone_at TEXT
);
"""

IMPORT_FILL = ("birth_date", "gender", "idnp", "email", "address", "insurance", "file_no")


async def import_index() -> list[dict]:
    """Вся картотека одной выборкой — по ней импорт ищет дубли в памяти."""
    return await _fetch(
        "SELECT id, name, phone, birth_date, birth_year, idnp, archived, import_id, "
        + ", ".join(f for f in IMPORT_FILL if f not in ("birth_date", "idnp"))
        + " FROM patients")


async def import_open(file_name: str, rows: int) -> int:
    cur = await db._CONN.execute(
        "INSERT INTO patient_imports(at, actor, file_name, rows) VALUES(?, ?, ?, ?)",
        (_utcnow_iso(), _actor_now(), file_name[:200], int(rows)))
    await db._CONN.commit()
    iid = cur.lastrowid
    await cur.close()
    return int(iid)


async def import_get(iid: int) -> dict | None:
    rows = await _fetch("SELECT * FROM patient_imports WHERE id = ?", iid)
    return rows[0] if rows else None


async def import_list(limit: int = 50) -> list[dict]:
    return await _fetch(
        "SELECT * FROM patient_imports ORDER BY id DESC LIMIT ?", limit)


async def import_count(iid: int, created: int = 0, filled: int = 0, skipped: int = 0,
                       visits: int = 0, visits_past: int = 0, visits_skipped: int = 0) -> None:
    await _execute(
        "UPDATE patient_imports SET created = created + ?, filled = filled + ?, "
        "skipped = skipped + ?, visits = visits + ?, visits_past = visits_past + ?, "
        "visits_skipped = visits_skipped + ? WHERE id = ?",
        created, filled, skipped, visits, visits_past, visits_skipped, iid)


async def import_drop(iid: int) -> None:
    """Убрать запись об импорте, который ничего не завёл, не дописал и не поставил."""
    await _execute(
        "DELETE FROM patient_imports WHERE id = ? AND created = 0 AND filled = 0 AND visits = 0",
        iid)


# Отпечаток визита импорта: всё, что меняют руками из журнала и карточки визита. Одно выражение на
# запись и на сверку — разойдись они, отмена сочла бы тронутым каждый визит (или ни одного).
_APPT_SIG = ("(status || '|' || starts_at || '|' || COALESCE(duration_min, '') || '|' "
             "|| COALESCE(doctor_id, '') || '|' || COALESCE(service_id, '') || '|' "
             "|| COALESCE(room_id, '') || '|' || COALESCE(comment, '') || '|' "
             "|| COALESCE(waiting_at, '') || '|' || COALESCE(arrived_at, '') || '|' "
             "|| COALESCE(patient_id, ''))")

# Что висит на визите и делает его частью работы клиники: звонок-подтверждение, запись приёма,
# позиция плана, заказ в лабораторию, расход склада, SMS, событие Google, отметка «Rechemări».
_APPT_CHILDREN = (("appt_calls", "appointment_id"), ("visit_records", "appointment_id"),
                  ("plan_items", "appointment_id"), ("lab_orders", "appointment_id"),
                  ("stock_moves", "appointment_id"), ("sms_log", "appt_id"),
                  ("gcal_events", "appt_id"), ("recall_marks", "cycle_appt_id"))


async def import_appt_mark(aid: int, iid: int, sms_skip: bool) -> None:
    """Метка импорта и отпечаток — сразу после постановки, тем же выражением, что сверяет отмена."""
    await _execute(
        f"UPDATE appointments SET import_id = ?, sms_skip = ?, import_sig = {_APPT_SIG} "
        "WHERE id = ?", iid, int(bool(sms_skip)), aid)


async def import_appts(iid: int) -> list[dict]:
    """Визиты импорта, которые ещё стоят: отчёт после импорта отличает «поставлен этим импортом»
    от «уже был»."""
    return await _fetch(
        "SELECT id, patient_id, starts_at FROM appointments WHERE import_id = ?", iid)


async def import_appt_ids(iid: int, after: int = 0, limit: int = 200) -> list[int]:
    rows = await _fetch(
        "SELECT id FROM appointments WHERE import_id = ? AND id > ? ORDER BY id LIMIT ?",
        iid, after, limit)
    return [r["id"] for r in rows]


async def import_appt_drop(aid: int) -> bool:
    """Снять визит импорта, если с ним ничего не делали: отпечаток тот же и на нём ничего не
    висит. Проверка и удаление — одним оператором, между ними чужая правка не вклинится."""
    free = " AND ".join(f"NOT EXISTS (SELECT 1 FROM {t} WHERE {c} = appointments.id)"
                        for t, c in _APPT_CHILDREN)
    n = await _execute(
        f"DELETE FROM appointments WHERE id = ? AND import_id IS NOT NULL "
        f"AND import_sig = {_APPT_SIG} AND {free}", aid)
    return bool(n)


async def import_visit_exists(pid: int, start) -> bool:
    """У фиши уже стоит визит на этот момент, в любом статусе: повтор того же файла. Прошлый визит
    «finalizată» занятость не держит (`_patient_busy` — только активные), и без этой сверки
    история из файла задваивалась бы при каждом повторе."""
    return bool(await _fetch(
        "SELECT 1 FROM appointments WHERE patient_id = ? AND starts_at = ? AND source <> 'note' LIMIT 1",
        pid, _iso(start)))


async def import_set_notes(pid: int, notes: str) -> None:
    """Заметки только что заведённой фиши: визит из её строки не встал — дата и врач в заметки."""
    await _execute("UPDATE patients SET notes = ? WHERE id = ?", notes or None, pid)


async def import_mark(pid: int, iid: int) -> None:
    await _execute("UPDATE patients SET import_id = ? WHERE id = ?", iid, pid)


async def import_pids(iid: int, after: int = 0, limit: int = 200) -> list[int]:
    rows = await _fetch(
        "SELECT id FROM patients WHERE import_id = ? AND id > ? ORDER BY id LIMIT ?",
        iid, after, limit)
    return [r["id"] for r in rows]


async def import_untouched(pid: int) -> bool:
    """Просмотр фиши не считается правкой: иначе отмена оставляла бы всё открытое. Строки
    летописи о визитах (`appt_new`, `appt_status`) — визиты самого импорта: к этому шагу отмена
    сняла нетронутые, а визит, который трогали, остаётся и держит фишу (визиты не удаляются
    ничем, кроме стирания пациента)."""
    rows = await _fetch(
        "SELECT (SELECT COUNT(*) FROM appointments WHERE patient_id = ?) AS appts, "
        "(SELECT COUNT(*) FROM activity WHERE patient_id = ? "
        " AND kind NOT IN ('created', 'view', 'appt_new', 'appt_status')) AS acts", pid, pid)
    return not rows[0]["appts"] and not rows[0]["acts"]


async def import_undone(iid: int, removed: int, final: bool, visits_removed: int = 0) -> None:
    await _execute(
        "UPDATE patient_imports SET removed = removed + ?, visits_removed = visits_removed + ? "
        "WHERE id = ?", removed, visits_removed, iid)
    if final:
        await _execute(
            "UPDATE patient_imports SET undone_at = ? WHERE id = ? AND undone_at IS NULL",
            _utcnow_iso(), iid)


async def fill_patient_blanks(pid: int, data: dict) -> list[str]:
    """Заполненное не трогается; ответ — какие поля легли."""
    done = []
    for f in IMPORT_FILL:
        v = data.get(f)
        if not v or f not in PATIENT_FIELDS:
            continue
        n = await _execute(
            f"UPDATE patients SET {f} = ? WHERE id = ? AND ({f} IS NULL OR {f} = '')",
            v, pid)
        if n:
            done.append(f)
    if "birth_date" in done:
        await _execute(
            "UPDATE patients SET birth_year = ? WHERE id = ?", int(str(data["birth_date"])[:4]), pid)
    return done
