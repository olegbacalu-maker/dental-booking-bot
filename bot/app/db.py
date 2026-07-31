"""Слой БД с двумя бэкендами:
- PostgreSQL (asyncpg) — облачное издание (Docker/VPS);
- SQLite (aiosqlite)  — desktop-издание (.exe, файл data/dental.db).
Бэкенд выбирается по DATABASE_URL (sqlite:///... → SQLite).
Даты в SQLite храним как ISO-строки в UTC — сравнения лексикографичны."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

POOL = None          # asyncpg pool
_CONN = None         # aiosqlite connection

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients(
  id SERIAL PRIMARY KEY,
  session_key TEXT UNIQUE NOT NULL,
  name TEXT,
  phone TEXT,
  lang TEXT NOT NULL DEFAULT 'ro',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS appointments(
  id SERIAL PRIMARY KEY,
  patient_id INT REFERENCES patients(id),
  service TEXT NOT NULL,
  doctor TEXT NOT NULL,
  starts_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_doctor_slot
  ON appointments(doctor, starts_at) WHERE status = 'confirmed';
CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_slot
  ON appointments(patient_id, starts_at) WHERE status = 'confirmed';
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'bot';
ALTER TABLE appointments ALTER COLUMN patient_id DROP NOT NULL;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_day BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_2h BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS comment TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS birth_year INT;
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_key TEXT UNIQUE NOT NULL,
  name TEXT,
  phone TEXT,
  lang TEXT NOT NULL DEFAULT 'ro',
  birth_year INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER REFERENCES patients(id),
  service TEXT NOT NULL,
  doctor TEXT NOT NULL,
  starts_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed',
  source TEXT NOT NULL DEFAULT 'bot',
  reminded_day INTEGER NOT NULL DEFAULT 0,
  reminded_2h INTEGER NOT NULL DEFAULT 0,
  comment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_doctor_slot
  ON appointments(doctor, starts_at) WHERE status = 'confirmed';
CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_slot
  ON appointments(patient_id, starts_at) WHERE status = 'confirmed';
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _utcnow_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


_DT_COLS = {"starts_at", "created_at"}


def _rowdict(row) -> dict:
    d = dict(row)
    for k in _DT_COLS & d.keys():
        if d[k] is not None:
            d[k] = _parse_dt(d[k])
    return d


# ---------- низкоуровневые помощники ----------

async def _fetch(pg_sql: str, lite_sql: str, *args) -> list[dict]:
    if IS_SQLITE:
        cur = await _CONN.execute(lite_sql, args)
        rows = await cur.fetchall()
        await cur.close()
        return [_rowdict(r) for r in rows]
    async with POOL.acquire() as c:
        rows = await c.fetch(pg_sql, *args)
    return [_rowdict(r) for r in rows]


async def _fetchval(pg_sql: str, lite_sql: str, *args):
    if IS_SQLITE:
        cur = await _CONN.execute(lite_sql, args)
        row = await cur.fetchone()
        await cur.close()
        await _CONN.commit()
        return row[0] if row else None
    async with POOL.acquire() as c:
        return await c.fetchval(pg_sql, *args)


async def _execute(pg_sql: str, lite_sql: str, *args) -> int:
    if IS_SQLITE:
        cur = await _CONN.execute(lite_sql, args)
        await _CONN.commit()
        n = cur.rowcount
        await cur.close()
        return n
    async with POOL.acquire() as c:
        res = await c.execute(pg_sql, *args)
    try:
        return int(res.split()[-1])
    except (ValueError, IndexError):
        return 0


# ---------- init ----------

async def init(seed_rows: list | None = None) -> None:
    global POOL, _CONN
    if IS_SQLITE:
        import aiosqlite
        import sqlite3
        path = DATABASE_URL.split("///", 1)[1]
        _CONN = await aiosqlite.connect(path)
        _CONN.row_factory = sqlite3.Row
        await _CONN.execute("PRAGMA journal_mode=WAL")
        await _CONN.execute("PRAGMA foreign_keys=ON")
        await _CONN.executescript(SQLITE_SCHEMA)
        await _CONN.commit()
    else:
        import asyncpg
        last: Exception | None = None
        for _ in range(60):
            try:
                POOL = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
                break
            except Exception as e:  # noqa: BLE001 - retry until db is up
                last = e
                await asyncio.sleep(1)
        if POOL is None:
            raise RuntimeError(f"DB unreachable: {last}")
        async with POOL.acquire() as c:
            await c.execute(PG_SCHEMA)
    await seed(seed_rows)


async def seed(rows: list | None) -> None:
    """Демо-записи (из конфига клиники) — только в пустую БД."""
    if not rows:
        return
    n = await _fetchval("SELECT count(*) FROM appointments",
                        "SELECT count(*) FROM appointments")
    if n:
        return
    for row in rows:
        await admin_add(*row)


# ---------- пациенты и записи ----------

async def _upsert_patient(session_key: str, name: str, phone: str,
                          lang: str, birth_year: int | None) -> int:
    pg = """INSERT INTO patients(session_key, name, phone, lang, birth_year)
            VALUES($1, $2, $3, $4, $5)
            ON CONFLICT (session_key) DO UPDATE
              SET name = EXCLUDED.name, phone = EXCLUDED.phone, lang = EXCLUDED.lang,
                  birth_year = COALESCE(EXCLUDED.birth_year, patients.birth_year)
            RETURNING id"""
    if IS_SQLITE:
        await _CONN.execute(
            """INSERT INTO patients(session_key, name, phone, lang, birth_year, created_at)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_key) DO UPDATE
                 SET name = excluded.name, phone = excluded.phone, lang = excluded.lang,
                     birth_year = COALESCE(excluded.birth_year, patients.birth_year)""",
            (session_key, name, phone, lang, birth_year, _utcnow_iso()),
        )
        await _CONN.commit()
        cur = await _CONN.execute(
            "SELECT id FROM patients WHERE session_key = ?", (session_key,))
        row = await cur.fetchone()
        await cur.close()
        return row[0]
    async with POOL.acquire() as c:
        return await c.fetchval(pg, session_key, name, phone, lang, birth_year)


async def create_appointment(
    session_key: str, name: str, phone: str, lang: str,
    service: str, doctor: str, starts_at: datetime,
    source: str = "bot", birth_year: int | None = None,
) -> int | str | None:
    """id записи; None — слот занят у этого врача; 'dup' — у пациента
    уже есть своя запись на это время."""
    pid = await _upsert_patient(session_key, name, phone, lang, birth_year)
    if IS_SQLITE:
        import sqlite3
        try:
            cur = await _CONN.execute(
                """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                            source, created_at)
                   VALUES(?, ?, ?, ?, ?, ?)""",
                (pid, service, doctor, _iso(starts_at), source, _utcnow_iso()),
            )
            await _CONN.commit()
            appt_id = cur.lastrowid
            await cur.close()
            return appt_id
        except sqlite3.IntegrityError as e:
            await _CONN.rollback()
            return "dup" if "uq_patient_slot" in str(e) else None
    import asyncpg
    async with POOL.acquire() as c:
        try:
            return await c.fetchval(
                """INSERT INTO appointments(patient_id, service, doctor, starts_at, source)
                   VALUES($1, $2, $3, $4, $5) RETURNING id""",
                pid, service, doctor, starts_at, source,
            )
        except asyncpg.UniqueViolationError as e:
            return "dup" if e.constraint_name == "uq_patient_slot" else None


async def admin_add(
    name: str, phone: str, service: str, doctor: str, starts_at: datetime,
    birth_year: int | None = None,
) -> int | str | None:
    """Ручная запись из журнала клиники. Пациент дедуплицируется по телефону."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return await create_appointment(
        f"manual:{digits}", name, phone, "ro", service, doctor, starts_at,
        source="manual", birth_year=birth_year,
    )


async def add_note(doctor: str, starts_at: datetime, text: str) -> int | None:
    """Заметка/блокировка слота: без пациента, но занимает слот врача."""
    if IS_SQLITE:
        import sqlite3
        try:
            cur = await _CONN.execute(
                """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                            source, created_at)
                   VALUES(NULL, ?, ?, ?, 'note', ?)""",
                (text, doctor, _iso(starts_at), _utcnow_iso()),
            )
            await _CONN.commit()
            note_id = cur.lastrowid
            await cur.close()
            return note_id
        except sqlite3.IntegrityError:
            await _CONN.rollback()
            return None
    import asyncpg
    async with POOL.acquire() as c:
        try:
            return await c.fetchval(
                """INSERT INTO appointments(patient_id, service, doctor, starts_at, source)
                   VALUES(NULL, $1, $2, $3, 'note') RETURNING id""",
                text, doctor, starts_at,
            )
        except asyncpg.UniqueViolationError:
            return None


async def booked(doctor: str, start: datetime, end: datetime) -> set:
    rows = await _fetch(
        """SELECT starts_at FROM appointments
           WHERE doctor = $1 AND status = 'confirmed'
             AND starts_at >= $2 AND starts_at < $3""",
        """SELECT starts_at FROM appointments
           WHERE doctor = ? AND status = 'confirmed'
             AND starts_at >= ? AND starts_at < ?""",
        *((doctor, start, end) if not IS_SQLITE
          else (doctor, _iso(start), _iso(end))),
    )
    return {r["starts_at"] for r in rows}


async def my_appointments(session_key: str, now: datetime) -> list:
    return await _fetch(
        """SELECT a.id, a.service, a.doctor, a.starts_at
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE p.session_key = $1 AND a.status = 'confirmed' AND a.starts_at > $2
           ORDER BY a.starts_at""",
        """SELECT a.id, a.service, a.doctor, a.starts_at
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE p.session_key = ? AND a.status = 'confirmed' AND a.starts_at > ?
           ORDER BY a.starts_at""",
        *((session_key, now) if not IS_SQLITE else (session_key, _iso(now))),
    )


async def cancel_appointment(session_key: str, appt_id: int) -> int:
    """Отмена ТОЛЬКО своей записи (ownership через session_key)."""
    return await _execute(
        """UPDATE appointments a SET status = 'cancelled'
           FROM patients p
           WHERE a.patient_id = p.id AND p.session_key = $1
             AND a.id = $2 AND a.status = 'confirmed'""",
        """UPDATE appointments SET status = 'cancelled'
           WHERE id = ? AND status = 'confirmed'
             AND patient_id = (SELECT id FROM patients WHERE session_key = ?)""",
        *((session_key, appt_id) if not IS_SQLITE else (appt_id, session_key)),
    )


# ---------- напоминания ----------

async def tg_due_reminders(now: datetime) -> list:
    """Telegram-записи, которым пора напомнить (окно 24ч; свежие < 30 мин не трогаем)."""
    from datetime import timedelta
    h24, m30 = now + timedelta(hours=24), now - timedelta(minutes=30)
    return await _fetch(
        """SELECT a.id, a.service, a.doctor, a.starts_at,
                  a.reminded_day, a.reminded_2h, p.session_key, p.lang
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status = 'confirmed'
             AND p.session_key LIKE 'tg:%'
             AND a.starts_at > $1 AND a.starts_at <= $2
             AND a.created_at < $3
             AND (a.reminded_day = FALSE OR a.reminded_2h = FALSE)""",
        """SELECT a.id, a.service, a.doctor, a.starts_at,
                  a.reminded_day, a.reminded_2h, p.session_key, p.lang
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status = 'confirmed'
             AND p.session_key LIKE 'tg:%'
             AND a.starts_at > ? AND a.starts_at <= ?
             AND a.created_at < ?
             AND (a.reminded_day = 0 OR a.reminded_2h = 0)""",
        *((now, h24, m30) if not IS_SQLITE
          else (_iso(now), _iso(h24), _iso(m30))),
    )


async def mark_reminded(appt_id: int, day: bool, soon: bool) -> None:
    await _execute(
        """UPDATE appointments
           SET reminded_day = reminded_day OR $2, reminded_2h = reminded_2h OR $3
           WHERE id = $1""",
        """UPDATE appointments
           SET reminded_day = MAX(reminded_day, ?), reminded_2h = MAX(reminded_2h, ?)
           WHERE id = ?""",
        *((appt_id, day, soon) if not IS_SQLITE
          else (int(day), int(soon), appt_id)),
    )


# ---------- журнал/поиск/статусы ----------

async def day_appointments(day_start: datetime, day_end: datetime) -> list:
    return await _fetch(
        """SELECT a.id, a.service, a.doctor, a.starts_at, a.status, a.source,
                  a.reminded_day, a.comment, p.name, p.phone, p.birth_year
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.starts_at >= $1 AND a.starts_at < $2
           ORDER BY a.starts_at, a.doctor""",
        """SELECT a.id, a.service, a.doctor, a.starts_at, a.status, a.source,
                  a.reminded_day, a.comment, p.name, p.phone, p.birth_year
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.starts_at >= ? AND a.starts_at < ?
           ORDER BY a.starts_at, a.doctor""",
        *((day_start, day_end) if not IS_SQLITE
          else (_iso(day_start), _iso(day_end))),
    )


async def patient_lang(session_key: str) -> str | None:
    """Язык пациента — чтобы после рестарта отвечать возвращённому на его языке."""
    return await _fetchval(
        "SELECT lang FROM patients WHERE session_key = $1",
        "SELECT lang FROM patients WHERE session_key = ?",
        session_key,
    )


async def recent_bot_appointments(since: datetime, limit: int = 10) -> list:
    """Свежие записи ИЗ БОТА по времени создания — независимо от даты визита.
    Урок полевого демо 07-31: запись на неделю вперёд невидима в дневных видах."""
    return await _fetch(
        """SELECT a.id, a.service, a.doctor, a.starts_at, a.created_at,
                  p.name, p.phone
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.source = 'bot' AND a.status = 'confirmed' AND a.created_at >= $1
           ORDER BY a.created_at DESC LIMIT $2""",
        """SELECT a.id, a.service, a.doctor, a.starts_at, a.created_at,
                  p.name, p.phone
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.source = 'bot' AND a.status = 'confirmed' AND a.created_at >= ?
           ORDER BY a.created_at DESC LIMIT ?""",
        *((since, limit) if not IS_SQLITE else (_iso(since), limit)),
    )


async def search_patients(q: str) -> list:
    """Поиск по имени (без регистра) или телефону (по цифрам)."""
    q = q.strip()
    digits = "".join(ch for ch in q if ch.isdigit())
    if len(q) < 2:
        return []
    if IS_SQLITE:
        rows = await _fetch(
            "", "SELECT id, name, phone, session_key, birth_year FROM patients")
        ql = q.lower()
        out = []
        for r in rows:
            nm = (r["name"] or "").lower()
            ph = "".join(ch for ch in (r["phone"] or "") if ch.isdigit())
            if ql in nm or (len(digits) >= 3 and digits in ph):
                out.append(r)
        out.sort(key=lambda r: r["name"] or "")
        return out[:30]
    return await _fetch(
        r"""SELECT p.id, p.name, p.phone, p.session_key, p.birth_year
           FROM patients p
           WHERE (p.name ILIKE '%' || $1 || '%')
              OR ($2 <> '' AND length($2) >= 3
                  AND regexp_replace(coalesce(p.phone, ''), '\D', '', 'g')
                      LIKE '%' || $2 || '%')
           ORDER BY p.name
           LIMIT 30""",
        "", q, digits,
    )


async def patient_appointments(patient_id: int) -> list:
    return await _fetch(
        """SELECT id, service, doctor, starts_at, status, source, comment
           FROM appointments WHERE patient_id = $1
           ORDER BY starts_at DESC LIMIT 20""",
        """SELECT id, service, doctor, starts_at, status, source, comment
           FROM appointments WHERE patient_id = ?
           ORDER BY starts_at DESC LIMIT 20""",
        patient_id,
    )


async def set_comment(appt_id: int, text: str) -> None:
    await _execute(
        "UPDATE appointments SET comment = $2 WHERE id = $1",
        "UPDATE appointments SET comment = ? WHERE id = ?",
        *((appt_id, text) if not IS_SQLITE else (text, appt_id)),
    )


async def set_status(appt_id: int, status: str) -> None:
    await _execute(
        "UPDATE appointments SET status = $2 WHERE id = $1",
        "UPDATE appointments SET status = ? WHERE id = ?",
        *((appt_id, status) if not IS_SQLITE else (status, appt_id)),
    )
