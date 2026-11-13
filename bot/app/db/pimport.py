"""Импорт пациентов из файла: запись об импорте, метка фиши, индекс для
поиска дублей. Строки самого файла в базе не лежат."""
from __future__ import annotations

from .. import db
from .conn import _execute, _fetch, _utcnow_iso
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


async def import_count(iid: int, created: int = 0, filled: int = 0, skipped: int = 0) -> None:
    await _execute(
        "UPDATE patient_imports SET created = created + ?, filled = filled + ?, "
        "skipped = skipped + ? WHERE id = ?", created, filled, skipped, iid)


async def import_drop(iid: int) -> None:
    """Убрать запись об импорте, который ничего не завёл и не дописал."""
    await _execute(
        "DELETE FROM patient_imports WHERE id = ? AND created = 0 AND filled = 0", iid)


async def import_mark(pid: int, iid: int) -> None:
    await _execute("UPDATE patients SET import_id = ? WHERE id = ?", iid, pid)


async def import_pids(iid: int, after: int = 0, limit: int = 200) -> list[int]:
    rows = await _fetch(
        "SELECT id FROM patients WHERE import_id = ? AND id > ? ORDER BY id LIMIT ?",
        iid, after, limit)
    return [r["id"] for r in rows]


async def import_untouched(pid: int) -> bool:
    """Просмотр фиши не считается правкой: иначе отмена оставляла бы всё открытое."""
    rows = await _fetch(
        "SELECT (SELECT COUNT(*) FROM appointments WHERE patient_id = ?) AS appts, "
        "(SELECT COUNT(*) FROM activity WHERE patient_id = ? "
        " AND kind NOT IN ('created', 'view')) AS acts", pid, pid)
    return not rows[0]["appts"] and not rows[0]["acts"]


async def import_undone(iid: int, removed: int, final: bool) -> None:
    await _execute(
        "UPDATE patient_imports SET removed = removed + ? WHERE id = ?", removed, iid)
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
