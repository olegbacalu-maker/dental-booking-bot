import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg

TZ = ZoneInfo("Europe/Chisinau")

POOL: asyncpg.Pool | None = None

SCHEMA = """
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
  patient_id INT NOT NULL REFERENCES patients(id),
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


async def init(seed_rows: list | None = None) -> None:
    global POOL
    last: Exception | None = None
    for _ in range(60):
        try:
            POOL = await asyncpg.create_pool(
                os.environ["DATABASE_URL"], min_size=1, max_size=5
            )
            break
        except Exception as e:  # noqa: BLE001 - retry until db is up
            last = e
            await asyncio.sleep(1)
    if POOL is None:
        raise RuntimeError(f"DB unreachable: {last}")
    async with POOL.acquire() as c:
        await c.execute(SCHEMA)
    await seed(seed_rows)


async def seed(rows: list | None) -> None:
    """Демо-записи (из конфига клиники) — только в пустую БД."""
    if not rows:
        return
    async with POOL.acquire() as c:
        if await c.fetchval("SELECT count(*) FROM appointments"):
            return
    for row in rows:
        await admin_add(*row)


async def booked(doctor: str, start: datetime, end: datetime) -> set[datetime]:
    async with POOL.acquire() as c:
        rows = await c.fetch(
            """SELECT starts_at FROM appointments
               WHERE doctor = $1 AND status = 'confirmed'
                 AND starts_at >= $2 AND starts_at < $3""",
            doctor, start, end,
        )
    return {r["starts_at"] for r in rows}


async def create_appointment(
    session_key: str, name: str, phone: str, lang: str,
    service: str, doctor: str, starts_at: datetime,
    source: str = "bot", birth_year: int | None = None,
) -> int | str | None:
    """id записи; None — слот занят у этого врача; 'dup' — у пациента
    уже есть своя запись на это время."""
    async with POOL.acquire() as c:
        pid = await c.fetchval(
            """INSERT INTO patients(session_key, name, phone, lang, birth_year)
               VALUES($1, $2, $3, $4, $5)
               ON CONFLICT (session_key) DO UPDATE
                 SET name = EXCLUDED.name, phone = EXCLUDED.phone, lang = EXCLUDED.lang,
                     birth_year = COALESCE(EXCLUDED.birth_year, patients.birth_year)
               RETURNING id""",
            session_key, name, phone, lang, birth_year,
        )
        try:
            return await c.fetchval(
                """INSERT INTO appointments(patient_id, service, doctor, starts_at, source)
                   VALUES($1, $2, $3, $4, $5) RETURNING id""",
                pid, service, doctor, starts_at, source,
            )
        except asyncpg.UniqueViolationError as e:
            if e.constraint_name == "uq_patient_slot":
                return "dup"
            return None


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


async def my_appointments(session_key: str) -> list:
    async with POOL.acquire() as c:
        return await c.fetch(
            """SELECT a.id, a.service, a.doctor, a.starts_at
               FROM appointments a JOIN patients p ON p.id = a.patient_id
               WHERE p.session_key = $1 AND a.status = 'confirmed'
                 AND a.starts_at > now()
               ORDER BY a.starts_at""",
            session_key,
        )


async def next_upcoming(session_key: str):
    rows = await my_appointments(session_key)
    return rows[0] if rows else None


async def cancel_appointment(session_key: str, appt_id: int) -> int:
    """Отмена ТОЛЬКО своей записи (ownership через session_key)."""
    async with POOL.acquire() as c:
        res = await c.execute(
            """UPDATE appointments a SET status = 'cancelled'
               FROM patients p
               WHERE a.patient_id = p.id AND p.session_key = $1
                 AND a.id = $2 AND a.status = 'confirmed'""",
            session_key, appt_id,
        )
    return int(res.split()[-1])


async def day_appointments(day_start: datetime, day_end: datetime) -> list:
    # LEFT JOIN: заметки ресепшена живут без пациента (patient_id IS NULL)
    async with POOL.acquire() as c:
        return await c.fetch(
            """SELECT a.id, a.service, a.doctor, a.starts_at, a.status, a.source,
                      a.reminded_day, a.comment, p.name, p.phone, p.birth_year
               FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
               WHERE a.starts_at >= $1 AND a.starts_at < $2
               ORDER BY a.starts_at, a.doctor""",
            day_start, day_end,
        )


async def tg_due_reminders() -> list:
    """Telegram-записи, которым пора напомнить (окно 24ч; свежесозданные не трогаем)."""
    async with POOL.acquire() as c:
        return await c.fetch(
            """SELECT a.id, a.service, a.doctor, a.starts_at,
                      a.reminded_day, a.reminded_2h, p.session_key, p.lang
               FROM appointments a JOIN patients p ON p.id = a.patient_id
               WHERE a.status = 'confirmed'
                 AND p.session_key LIKE 'tg:%'
                 AND a.starts_at > now()
                 AND a.starts_at <= now() + interval '24 hours'
                 AND a.created_at < now() - interval '30 minutes'
                 AND (a.reminded_day = FALSE OR a.reminded_2h = FALSE)"""
        )


async def mark_reminded(appt_id: int, day: bool, soon: bool) -> None:
    async with POOL.acquire() as c:
        await c.execute(
            """UPDATE appointments
               SET reminded_day = reminded_day OR $2,
                   reminded_2h = reminded_2h OR $3
               WHERE id = $1""",
            appt_id, day, soon,
        )


async def add_note(doctor: str, starts_at: datetime, text: str) -> int | None:
    """Заметка/блокировка слота от ресепшена: без пациента, но занимает
    слот врача (uq_doctor_slot), поэтому бот это время не предложит."""
    async with POOL.acquire() as c:
        try:
            return await c.fetchval(
                """INSERT INTO appointments(patient_id, service, doctor, starts_at, source)
                   VALUES(NULL, $1, $2, $3, 'note') RETURNING id""",
                text, doctor, starts_at,
            )
        except asyncpg.UniqueViolationError:
            return None


async def search_patients(q: str) -> list:
    """Поиск пациента по имени (ILIKE) или телефону (по цифрам, формат не важен)."""
    q = q.strip()
    digits = "".join(ch for ch in q if ch.isdigit())
    if len(q) < 2:
        return []
    async with POOL.acquire() as c:
        return await c.fetch(
            r"""SELECT p.id, p.name, p.phone, p.session_key, p.birth_year
               FROM patients p
               WHERE (p.name ILIKE '%' || $1 || '%')
                  OR ($2 <> '' AND length($2) >= 3
                      AND regexp_replace(coalesce(p.phone, ''), '\D', '', 'g')
                          LIKE '%' || $2 || '%')
               ORDER BY p.name
               LIMIT 30""",
            q, digits,
        )


async def patient_appointments(patient_id: int) -> list:
    async with POOL.acquire() as c:
        return await c.fetch(
            """SELECT id, service, doctor, starts_at, status, source, comment
               FROM appointments
               WHERE patient_id = $1
               ORDER BY starts_at DESC
               LIMIT 20""",
            patient_id,
        )


async def set_comment(appt_id: int, text: str) -> None:
    async with POOL.acquire() as c:
        await c.execute(
            "UPDATE appointments SET comment = $2 WHERE id = $1", appt_id, text
        )


async def set_status(appt_id: int, status: str) -> None:
    async with POOL.acquire() as c:
        await c.execute(
            "UPDATE appointments SET status = $2 WHERE id = $1", appt_id, status
        )
