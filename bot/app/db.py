"""Слой БД с двумя бэкендами:
- PostgreSQL (asyncpg) — облачное издание (Docker/VPS);
- SQLite (aiosqlite)  — desktop-издание (.exe, файл data/dental.db).
Бэкенд выбирается по DATABASE_URL (sqlite:///... → SQLite).
Даты в SQLite храним как ISO-строки в UTC — сравнения лексикографичны."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

log = logging.getLogger("db")

# Версия схемы: шаги применяются по одному и записываются в schema_meta,
# поэтому по базе клиники всегда видно, докуда она домигрирована.
SCHEMA_VERSION = 3

# Записи, которые ЗАНИМАЮТ слот врача. 'arrived' (пациент в кабинете) обязан
# быть здесь: иначе отметка «пришёл» освобождает час и бот сажает второго.
ACTIVE_STATUSES = ("confirmed", "arrived")
_ACT_SQL = "('confirmed','arrived')"

POOL = None          # asyncpg pool
_CONN = None         # aiosqlite connection

# Сериализация бронирований: интервальное пересечение уникальным индексом не
# ловится (индекс защищает только одинаковые старты), поэтому проверка
# «пересекается ли» и INSERT идут под замком. Процесс один (single-instance
# guard в desktop.py) — замка на уровне процесса достаточно.
_BOOK_LOCK = asyncio.Lock()

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
ALTER TABLE patients ADD COLUMN IF NOT EXISTS birth_date TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS idnp TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS insurance TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS primary_doctor TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS file_no TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS patient_alerts(
  id SERIAL PRIMARY KEY,
  patient_id INT NOT NULL REFERENCES patients(id),
  kind TEXT NOT NULL DEFAULT 'warning',
  text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS teeth(
  patient_id INT NOT NULL REFERENCES patients(id),
  tooth INT NOT NULL,
  state TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(patient_id, tooth)
);
CREATE TABLE IF NOT EXISTS plan_items(
  id SERIAL PRIMARY KEY,
  patient_id INT NOT NULL REFERENCES patients(id),
  tooth INT,
  procedure TEXT NOT NULL,
  doctor TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'planificat',
  price_mdl INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  done_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS documents(
  id SERIAL PRIMARY KEY,
  patient_id INT NOT NULL REFERENCES patients(id),
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  size INT NOT NULL,
  mime TEXT NOT NULL DEFAULT '',
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'alt';
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS doctor_id TEXT;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS service_id TEXT;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS duration_min INT;
-- этап 2 фиши пациента: срок позиции плана и врач, поставивший состояние зуба
ALTER TABLE plan_items ADD COLUMN IF NOT EXISTS due_date TEXT;
ALTER TABLE teeth ADD COLUMN IF NOT EXISTS doctor TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS activity(
  id SERIAL PRIMARY KEY,
  patient_id INT REFERENCES patients(id),
  at TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor TEXT NOT NULL DEFAULT 'recepție',
  kind TEXT NOT NULL,
  tooth INT,
  text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_act_patient ON activity(patient_id, at DESC);
CREATE INDEX IF NOT EXISTS ix_act_tooth ON activity(patient_id, tooth, at DESC);
"""

# Индексы под горячие пути (день, история пациента, «новые из бота», карточка).
# Уникальные индексы слота пересоздаются: предикат расширен на 'arrived' —
# ИМЕНА обязаны остаться прежними (create_appointment ловит их в тексте ошибки).
MIGRATIONS_PG = {
    1: [
        "CREATE INDEX IF NOT EXISTS ix_appt_starts ON appointments(starts_at)",
        "CREATE INDEX IF NOT EXISTS ix_appt_patient ON appointments(patient_id, starts_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_appt_created ON appointments(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_plan_patient ON plan_items(patient_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_patient ON documents(patient_id)",
    ],
    2: [
        "DROP INDEX IF EXISTS uq_doctor_slot",
        "DROP INDEX IF EXISTS uq_patient_slot",
        f"""CREATE UNIQUE INDEX uq_doctor_slot ON appointments(doctor, starts_at)
            WHERE status IN {_ACT_SQL}""",
        f"""CREATE UNIQUE INDEX uq_patient_slot ON appointments(patient_id, starts_at)
            WHERE status IN {_ACT_SQL}""",
    ],
    3: [
        # уникальность по СТАБИЛЬНОМУ ключу: переименование врача больше не
        # обходит защиту от двойной брони; NULL-ы (легаси до бэкфилла) не
        # конфликтуют; индекс по имени остаётся вторым поясом
        "DROP INDEX IF EXISTS uq_doctor_slot_id",
        f"""CREATE UNIQUE INDEX uq_doctor_slot_id ON appointments(doctor_id, starts_at)
            WHERE status IN {_ACT_SQL} AND doctor_id IS NOT NULL""",
    ],
}
MIGRATIONS_LITE = {
    1: [
        "CREATE INDEX IF NOT EXISTS ix_appt_starts ON appointments(starts_at)",
        "CREATE INDEX IF NOT EXISTS ix_appt_patient ON appointments(patient_id, starts_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_appt_created ON appointments(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_plan_patient ON plan_items(patient_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_patient ON documents(patient_id)",
    ],
    2: [
        "DROP INDEX IF EXISTS uq_doctor_slot",
        "DROP INDEX IF EXISTS uq_patient_slot",
        f"""CREATE UNIQUE INDEX uq_doctor_slot ON appointments(doctor, starts_at)
            WHERE status IN {_ACT_SQL}""",
        f"""CREATE UNIQUE INDEX uq_patient_slot ON appointments(patient_id, starts_at)
            WHERE status IN {_ACT_SQL}""",
    ],
    3: [
        "DROP INDEX IF EXISTS uq_doctor_slot_id",
        f"""CREATE UNIQUE INDEX uq_doctor_slot_id ON appointments(doctor_id, starts_at)
            WHERE status IN {_ACT_SQL} AND doctor_id IS NOT NULL""",
    ],
}

# Этап A2+A4 (v1.6.0) — карточка пациента: алерты, формула FDI, план лечения, документы
SQLITE_CARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  kind TEXT NOT NULL DEFAULT 'warning',
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teeth(
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  tooth INTEGER NOT NULL,
  state TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY(patient_id, tooth)
);
CREATE TABLE IF NOT EXISTS plan_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  tooth INTEGER,
  procedure TEXT NOT NULL,
  doctor TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'planificat',
  price_mdl INTEGER,
  created_at TEXT NOT NULL,
  done_at TEXT
);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  size INTEGER NOT NULL,
  mime TEXT NOT NULL DEFAULT '',
  uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER REFERENCES patients(id),
  at TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT 'recepție',
  kind TEXT NOT NULL,
  tooth INTEGER,
  text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_act_patient ON activity(patient_id, at DESC);
CREATE INDEX IF NOT EXISTS ix_act_tooth ON activity(patient_id, tooth, at DESC);
CREATE TABLE IF NOT EXISTS schema_meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# Аддитивные колонки SQLite (нет ADD COLUMN IF NOT EXISTS) — по одной с игнором
# «duplicate column»; всё остальное поднимаем наверх, чтобы не терять молча.
SQLITE_EXTRA_COLS = [
    ("documents", "category TEXT NOT NULL DEFAULT 'alt'"),
    # v1.7.1: стабильные ключи; doctor/service остаются СНАПШОТАМИ имени на
    # момент записи (история, CSV, напоминания показывают то, что называли)
    ("appointments", "doctor_id TEXT"),
    ("appointments", "service_id TEXT"),
    # v1.8.0: длительность визита в минутах; NULL = легаси-строка = 60
    ("appointments", "duration_min INTEGER"),
    # этап 2 фиши: срок позиции плана (ISO-дата) и врач-автор состояния зуба
    ("plan_items", "due_date TEXT"),
    ("teeth", "doctor TEXT NOT NULL DEFAULT ''"),
]

# Этап A1 (v1.5.0): полный профиль пациента. Все поля опциональны — клиника может
# по-прежнему вести только имя+телефон. SQLite не умеет ADD COLUMN IF NOT EXISTS,
# поэтому колонки добавляются по одной с игнором «duplicate column».
SQLITE_PATIENT_COLS = [
    "birth_date TEXT", "gender TEXT", "idnp TEXT", "email TEXT", "address TEXT",
    "insurance TEXT", "primary_doctor TEXT", "file_no TEXT", "notes TEXT",
    "archived INTEGER NOT NULL DEFAULT 0",
]

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


# колонки-даты: в SQLite это ISO-строки, наверх обязаны уходить datetime.
# Забыть здесь новую колонку = дата молча исчезнет из интерфейса (так и
# случилось с activity.at на первом прогоне).
# last_at/next_at — вычисляемые псевдонимы (MAX/MIN по starts_at) из
# patients_visits: в PG они приходят datetime, в SQLite остались бы строкой.
_DT_COLS = {"starts_at", "created_at", "uploaded_at", "updated_at", "at",
            "last_at", "next_at"}


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

async def _schema_version() -> int:
    try:
        v = await _fetchval("SELECT value FROM schema_meta WHERE key = 'version'",
                            "SELECT value FROM schema_meta WHERE key = 'version'")
        return int(v) if v is not None else 0
    except Exception as e:  # noqa: BLE001 — обычно «таблицы ещё нет» = версия 0
        log.warning("schema_meta read failed (treating as v0): %r", e)
        return 0


async def _set_schema_version(v: int) -> None:
    await _execute(
        """INSERT INTO schema_meta(key, value) VALUES('version', $1)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        """INSERT INTO schema_meta(key, value) VALUES('version', ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        str(v),
    )


# Служебные пары ключ-значение ЖИВУТ В schema_meta намеренно: таблица есть у
# каждой клиники с первой версии, значит новой миграции не нужно. Ключи не
# пересекаются с 'version' — он занят номером схемы.

async def get_meta(key: str) -> str | None:
    try:
        return await _fetchval(
            "SELECT value FROM schema_meta WHERE key = $1",
            "SELECT value FROM schema_meta WHERE key = ?", key)
    except Exception as e:  # noqa: BLE001 — служебное значение не роняет старт
        log.warning("get_meta(%s) failed: %r", key, e)
        return None


async def set_meta(key: str, value: str) -> None:
    await _execute(
        """INSERT INTO schema_meta(key, value) VALUES($1, $2)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        """INSERT INTO schema_meta(key, value) VALUES(?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        key, value,
    )


async def del_meta(key: str) -> None:
    await _execute("DELETE FROM schema_meta WHERE key = $1",
                   "DELETE FROM schema_meta WHERE key = ?", key)


async def _migrate() -> None:
    """Пошаговые миграции: каждый шаг применяется один раз и фиксируется.
    Раньше состояние базы можно было понять только по наличию колонок."""
    have = await _schema_version()
    if have >= SCHEMA_VERSION:
        return
    steps = MIGRATIONS_LITE if IS_SQLITE else MIGRATIONS_PG
    for v in range(have + 1, SCHEMA_VERSION + 1):
        if v not in steps:
            # забытый список SQL = молчаливый no-op с записанной версией; лучше упасть
            raise RuntimeError(f"missing migration step {v} for "
                               f"{'sqlite' if IS_SQLITE else 'postgres'}")
        if IS_SQLITE:
            for sql in steps[v]:
                await _CONN.execute(sql)
            await _CONN.commit()
        else:
            # один шаг = одна транзакция: DROP и CREATE uq-индексов неразделимы,
            # иначе краш между ними оставит базу без защиты от двойной брони
            async with POOL.acquire() as c, c.transaction():
                for sql in steps[v]:
                    await c.execute(sql)
        await _set_schema_version(v)
    log.warning("DB migrated %s -> %s", have, SCHEMA_VERSION)


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
        for coldef in SQLITE_PATIENT_COLS:
            try:
                await _CONN.execute(f"ALTER TABLE patients ADD COLUMN {coldef}")
            except sqlite3.OperationalError as e:
                # «duplicate column» = уже мигрировано; всё прочее (база залочена,
                # I/O) НЕ глотаем — иначе колонка тихо пропадёт и всплывёт позже
                if "duplicate column" not in str(e).lower():
                    raise
        await _CONN.executescript(SQLITE_CARD_SCHEMA)
        for table, coldef in SQLITE_EXTRA_COLS:
            try:
                await _CONN.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
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
    await _migrate()
    await _backfill_activity()
    await seed(seed_rows)


async def backfill_ids(doc_map: dict, svc_map: dict) -> None:
    """Проставляет doctor_id/service_id старым записям по ТЕКУЩЕМУ конфигу
    (имя→id, подпись ro/ru→id). Идемпотентно: трогает только NULL. Записи
    врачей, переименованных ДО этого обновления, остаются с NULL — их
    восстановить не по чему, канва показывает их отдельной колонкой."""
    for name, did in doc_map.items():
        try:
            await _execute(
                "UPDATE appointments SET doctor_id = $2 WHERE doctor_id IS NULL AND doctor = $1",
                "UPDATE appointments SET doctor_id = ? WHERE doctor_id IS NULL AND doctor = ?",
                *((name, did) if not IS_SQLITE else (did, name)),
            )
        except Exception as e:  # noqa: BLE001 — конфликт uq_doctor_slot_id на патологии
            log.warning("backfill doctor_id failed for %r: %r", name, e)
            if IS_SQLITE:
                await _CONN.rollback()
    for label, sid_ in svc_map.items():
        try:
            await _execute(
                """UPDATE appointments SET service_id = $2
                   WHERE service_id IS NULL AND service = $1 AND source != 'note'""",
                """UPDATE appointments SET service_id = ?
                   WHERE service_id IS NULL AND service = ? AND source != 'note'""",
                *((label, sid_) if not IS_SQLITE else (sid_, label)),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("backfill service_id failed for %r: %r", label, e)
            if IS_SQLITE:
                await _CONN.rollback()


async def relink_doctor(old_name: str, doctor_id: str) -> int:
    """Переприкрепляет сиротские строки (doctor_id IS NULL, старое имя) к врачу.
    Лечит записи, осиротевшие при переименовании ещё ДО v1.7.1 — включая
    будущие брони, невидимые для проверки занятости."""
    try:
        return await _execute(
            "UPDATE appointments SET doctor_id = $2 WHERE doctor_id IS NULL AND doctor = $1",
            "UPDATE appointments SET doctor_id = ? WHERE doctor_id IS NULL AND doctor = ?",
            *((old_name, doctor_id) if not IS_SQLITE else (doctor_id, old_name)),
        )
    except Exception as e:  # noqa: BLE001 — конфликт uq_doctor_slot_id (двойник часа)
        log.warning("relink %r -> %s failed: %r", old_name, doctor_id, e)
        if IS_SQLITE:
            await _CONN.rollback()
        return -1


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
    doctor_id: str | None = None, service_id: str | None = None,
    duration_min: int = 60,
) -> int | str | None:
    """id записи; None — интервал занят у этого врача; 'dup' — у пациента
    уже есть своя запись на это время. doctor/service = снапшоты подписи,
    doctor_id/service_id = стабильные ключи; duration_min = снапшот
    длительности услуги на момент брони."""
    pid = await _upsert_patient(session_key, name, phone, lang, birth_year)
    return await _book(pid, service, doctor, starts_at, source,
                       doctor_id, service_id, duration_min)


async def _book(pid: int, service: str, doctor: str, starts_at: datetime,
                source: str, doctor_id: str | None, service_id: str | None,
                duration_min: int) -> int | str | None:
    """Вставка визита пациенту, который УЖЕ известен по id. Контракт возврата
    тот же, что у create_appointment (id / None / 'dup')."""
    async with _BOOK_LOCK:
        # ⚠️ «у пациента уже есть запись» спрашиваем ЗАРАНЕЕ, а не ловим по
        # тексту IntegrityError: SQLite называет в нём колонки, а не индекс, и
        # проверка на 'uq_patient_slot' не срабатывала никогда — дубль пациента
        # показывался регистратуре как «интервал занят у этого врача».
        # Проверка идёт первой: она точнее, чем конфликт врача, и под _BOOK_LOCK
        # так же надёжна, как индекс.
        if await _patient_busy_at(pid, starts_at):
            return "dup"
        # интервальная проверка: uq-индексы ловят только одинаковые старты,
        # пересечение 10:00(60') с 10:30(60') обязано отсекаться здесь
        if await _conflicts(doctor_id, doctor, starts_at, duration_min):
            return None
        if IS_SQLITE:
            import sqlite3
            try:
                cur = await _CONN.execute(
                    """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                                source, doctor_id, service_id,
                                                duration_min, created_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, service, doctor, _iso(starts_at), source,
                     doctor_id, service_id, duration_min, _utcnow_iso()),
                )
                await _CONN.commit()
                appt_id = cur.lastrowid
                await cur.close()
                await _log_booking(pid, service, doctor, starts_at, source)
                return appt_id
            except sqlite3.IntegrityError as e:
                await _CONN.rollback()
                # страховка на случай гонки мимо замка. Текст SQLite —
                # «UNIQUE constraint failed: appointments.patient_id,
                # appointments.starts_at», имени индекса в нём НЕТ.
                return "dup" if "patient_id" in str(e) else None
        import asyncpg
        async with POOL.acquire() as c:
            try:
                new_id = await c.fetchval(
                    """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                                source, doctor_id, service_id, duration_min)
                       VALUES($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                    pid, service, doctor, starts_at, source,
                    doctor_id, service_id, duration_min,
                )
            except asyncpg.UniqueViolationError as e:
                return "dup" if e.constraint_name == "uq_patient_slot" else None
        await _log_booking(pid, service, doctor, starts_at, source)
        return new_id


async def admin_add(
    name: str, phone: str, service: str, doctor: str, starts_at: datetime,
    birth_year: int | None = None,
    doctor_id: str | None = None, service_id: str | None = None,
    duration_min: int = 60,
) -> int | str | None:
    """Ручная запись из журнала клиники. Пациент дедуплицируется по телефону."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return await create_appointment(
        f"manual:{digits}", name, phone, "ro", service, doctor, starts_at,
        source="manual", birth_year=birth_year,
        doctor_id=doctor_id, service_id=service_id, duration_min=duration_min,
    )


async def add_visit_for_patient(
    pid: int, service: str, doctor: str, starts_at: datetime,
    doctor_id: str | None = None, service_id: str | None = None,
    duration_min: int = 60,
) -> int | str | None:
    """Запись ИЗ ФИШИ: пациент уже известен по id, дедупликация по телефону
    здесь была бы вредна. Общий путь (`manual:{цифры}`) склеивает пациентов по
    номеру, а у телеграм-пациента session_key 'tg:…' — визит из его же фиши
    уехал бы новому пациенту-двойнику или соседу с тем же семейным номером."""
    return await _book(pid, service, doctor, starts_at, "manual",
                       doctor_id, service_id, duration_min)


async def _patient_busy_at(pid: int, starts_at: datetime) -> bool:
    """Есть ли у пациента активная запись РОВНО на этот старт — то же, что
    стережёт uq_patient_slot, но ответом, а не исключением. Вызывать под
    _BOOK_LOCK. Пересечения по длительности здесь намеренно не ищем: индекс их
    тоже не запрещает, а регистратура ставит пациента к двум врачам подряд."""
    rows = await _fetch(
        f"""SELECT id FROM appointments
           WHERE patient_id = $1 AND starts_at = $2 AND status IN {_ACT_SQL}
           LIMIT 1""",
        f"""SELECT id FROM appointments
           WHERE patient_id = ? AND starts_at = ? AND status IN {_ACT_SQL}
           LIMIT 1""",
        pid, (starts_at if not IS_SQLITE else _iso(starts_at)),
    )
    return bool(rows)


async def _conflicts(doctor_id: str | None, doctor: str, starts_at: datetime,
                     duration_min: int, exclude_id: int | None = None) -> bool:
    """Пересекается ли интервал с уже занятыми у этого врача. Вызывать ПОД
    _BOOK_LOCK — уникальные индексы ловят только совпадающие старты."""
    from datetime import timedelta
    pad = timedelta(minutes=240)
    rows = await _fetch(
        f"""SELECT id, starts_at, duration_min FROM appointments
           WHERE (doctor_id = $1 OR (doctor_id IS NULL AND doctor = $2))
             AND status IN {_ACT_SQL} AND starts_at >= $3 AND starts_at < $4""",
        f"""SELECT id, starts_at, duration_min FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL} AND starts_at >= ? AND starts_at < ?""",
        *((doctor_id or "", doctor, starts_at - pad, starts_at + pad)
          if not IS_SQLITE
          else (doctor_id or "", doctor, _iso(starts_at - pad), _iso(starts_at + pad))),
    )
    end = starts_at + timedelta(minutes=duration_min)
    for r in rows:
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        b_start = r["starts_at"]
        if b_start < end and starts_at < b_start + timedelta(minutes=int(r["duration_min"] or 60)):
            return True
    return False


async def add_note(doctor: str, starts_at: datetime, text: str,
                   doctor_id: str | None = None) -> int | None:
    """Заметка/блокировка слота: без пациента, но занимает слот врача."""
    async with _BOOK_LOCK:
        # заметка тоже обязана уважать интервалы (иначе ложится поверх визита)
        if await _conflicts(doctor_id, doctor, starts_at, 60):
            return None
        return await _insert_note(doctor, starts_at, text, doctor_id)


async def _insert_note(doctor: str, starts_at: datetime, text: str,
                       doctor_id: str | None) -> int | None:
    if IS_SQLITE:
        import sqlite3
        try:
            cur = await _CONN.execute(
                """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                            source, doctor_id, created_at)
                   VALUES(NULL, ?, ?, ?, 'note', ?, ?)""",
                (text, doctor, _iso(starts_at), doctor_id, _utcnow_iso()),
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
                """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                            source, doctor_id)
                   VALUES(NULL, $1, $2, $3, 'note', $4) RETURNING id""",
                text, doctor, starts_at, doctor_id,
            )
        except asyncpg.UniqueViolationError:
            return None


async def booked_intervals(doctor_key: str, doctor_name: str,
                           start: datetime, end: datetime) -> list:
    """Занятые ИНТЕРВАЛЫ врача: [(старт, длительность_мин)]. Матчим по
    стабильному doctor_id, легаси-строки без id — по снапшоту имени.
    NULL-длительность (записи до v1.8.0) считается 60 минутами."""
    rows = await _fetch(
        f"""SELECT starts_at, duration_min FROM appointments
           WHERE (doctor_id = $1 OR (doctor_id IS NULL AND doctor = $2))
             AND status IN {_ACT_SQL}
             AND starts_at >= $3 AND starts_at < $4""",
        f"""SELECT starts_at, duration_min FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL}
             AND starts_at >= ? AND starts_at < ?""",
        *((doctor_key, doctor_name, start, end) if not IS_SQLITE
          else (doctor_key, doctor_name, _iso(start), _iso(end))),
    )
    return [(r["starts_at"], int(r["duration_min"] or 60)) for r in rows]


async def doctor_future_count(doctor_key: str, doctor_name: str,
                              now: datetime) -> int:
    """Сколько живых записей у врача впереди — замок на архивацию (v1.9.0).
    Матчинг тот же, что в booked_intervals: id, легаси-строки — по имени."""
    return await _fetchval(
        f"""SELECT COUNT(*) FROM appointments
           WHERE (doctor_id = $1 OR (doctor_id IS NULL AND doctor = $2))
             AND status IN {_ACT_SQL} AND starts_at >= $3""",
        f"""SELECT COUNT(*) FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL} AND starts_at >= ?""",
        *((doctor_key, doctor_name, now) if not IS_SQLITE
          else (doctor_key, doctor_name, _iso(now))),
    ) or 0


async def my_appointments(session_key: str, now: datetime) -> list:
    # arrived тоже показываем: пациент «в кресле» не должен пропадать из «мои
    # записи»; status нужен движку — у arrived НЕ рисуем кнопку отмены
    return await _fetch(
        f"""SELECT a.id, a.service, a.doctor, a.doctor_id, a.starts_at, a.status
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE p.session_key = $1 AND a.status IN {_ACT_SQL} AND a.starts_at > $2
           ORDER BY a.starts_at""",
        f"""SELECT a.id, a.service, a.doctor, a.doctor_id, a.starts_at, a.status
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE p.session_key = ? AND a.status IN {_ACT_SQL} AND a.starts_at > ?
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
        """SELECT a.id, a.service, a.doctor, a.doctor_id, a.starts_at,
                  a.reminded_day, a.reminded_2h, p.session_key, p.lang
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status = 'confirmed'
             AND p.session_key LIKE 'tg:%'
             AND a.starts_at > $1 AND a.starts_at <= $2
             AND a.created_at < $3
             AND (a.reminded_day = FALSE OR a.reminded_2h = FALSE)""",
        """SELECT a.id, a.service, a.doctor, a.doctor_id, a.starts_at,
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
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id, a.service_id,
                  a.starts_at, a.duration_min, a.status, a.source,
                  a.reminded_day, a.comment, p.name, p.phone, p.birth_year
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.starts_at >= $1 AND a.starts_at < $2
           ORDER BY a.starts_at, a.doctor""",
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id, a.service_id,
                  a.starts_at, a.duration_min, a.status, a.source,
                  a.reminded_day, a.comment, p.name, p.phone, p.birth_year
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.starts_at >= ? AND a.starts_at < ?
           ORDER BY a.starts_at, a.doctor""",
        *((day_start, day_end) if not IS_SQLITE
          else (_iso(day_start), _iso(day_end))),
    )


_PLIST_COLS = ("id, name, phone, email, session_key, birth_year, birth_date, "
               "gender, insurance, primary_doctor, file_no, notes, created_at, "
               "archived")


async def all_patients(include_archived: bool = False) -> list:
    """Все пациенты клиники — основа списка «Pacienți» с фильтрами и страницами.

    Отдаёт только СТРОКИ. Сколько у кого визитов, планов и предупреждений,
    добирают соседние выборки (`patients_visits`, `patients_alert_counts`,
    `patients_plan_counts`), а сводит их модуль. LIMIT/OFFSET здесь был бы
    неверен: страница сортируется и фильтруется по этим самым агрегатам, и
    база отрезала бы не тех. База клиники — тысячи строк, не миллионы.
    """
    if include_archived:
        return await _fetch(f"SELECT {_PLIST_COLS} FROM patients ORDER BY id",
                            f"SELECT {_PLIST_COLS} FROM patients ORDER BY id")
    return await _fetch(
        f"""SELECT {_PLIST_COLS} FROM patients
            WHERE COALESCE(archived, FALSE) = FALSE ORDER BY id""",
        f"""SELECT {_PLIST_COLS} FROM patients
            WHERE COALESCE(archived, 0) = 0 ORDER BY id""")


async def patients_visits(now: datetime) -> list:
    """По пациенту: последний прошедший визит, ближайший будущий и сколько
    всего (отменённые не в счёт). Один проход по таблице вместо запроса на
    каждую строку списка — иначе страница пациентов стоила бы сотню запросов.
    Заметки-блокировки сюда не попадают: у них patient_id = NULL."""
    return await _fetch(
        f"""SELECT patient_id,
                   MAX(CASE WHEN starts_at <= $1 THEN starts_at END) AS last_at,
                   MIN(CASE WHEN starts_at > $1 AND status IN {_ACT_SQL}
                            THEN starts_at END) AS next_at,
                   COUNT(*) AS n_visits
              FROM appointments
             WHERE patient_id IS NOT NULL AND status <> 'cancelled'
             GROUP BY patient_id""",
        f"""SELECT patient_id,
                   MAX(CASE WHEN starts_at <= ? THEN starts_at END) AS last_at,
                   MIN(CASE WHEN starts_at > ? AND status IN {_ACT_SQL}
                            THEN starts_at END) AS next_at,
                   COUNT(*) AS n_visits
              FROM appointments
             WHERE patient_id IS NOT NULL AND status <> 'cancelled'
             GROUP BY patient_id""",
        *((now,) if not IS_SQLITE else (_iso(now), _iso(now))),
    )


async def patients_last_doctor() -> list:
    """Кто вёл ПОСЛЕДНИЙ визит — по пациенту. Колонка «Medic» в списке иначе
    пуста почти у всех: `primary_doctor` в фише проставляют руками, а врач у
    пациента фактически есть — тот, к кому он ходит. Оконная функция здесь
    одна на оба движка (PG и SQLite с 3.25), поэтому SQL-текст один."""
    sql = """SELECT patient_id, doctor FROM (
               SELECT patient_id, doctor,
                      ROW_NUMBER() OVER (PARTITION BY patient_id
                                         ORDER BY starts_at DESC) AS rn
                 FROM appointments
                WHERE patient_id IS NOT NULL AND status <> 'cancelled') t
             WHERE rn = 1"""
    return await _fetch(sql, sql)


async def patients_alert_counts() -> list:
    """Сколько медицинских предупреждений у каждого пациента (аллергии и т.п.)."""
    sql = "SELECT patient_id, COUNT(*) AS n FROM patient_alerts GROUP BY patient_id"
    return await _fetch(sql, sql)


async def patients_plan_counts() -> list:
    """Незавершённые пункты плана — по ним пациент считается «в лечении»."""
    sql = ("SELECT patient_id, COUNT(*) AS n FROM plan_items "
           "WHERE status <> 'finalizat' GROUP BY patient_id")
    return await _fetch(sql, sql)


async def patient_id_by_key(session_key: str) -> int | None:
    """Есть ли уже пациент с таким ключом. Нужен до создания карточки вручную:
    `_upsert_patient` при совпадении ПЕРЕЗАПИСАЛ бы имя существующего, и
    «Ion Popescu» тихо стал бы «Ion P.» из-за общего семейного номера."""
    return await _fetchval(
        "SELECT id FROM patients WHERE session_key = $1",
        "SELECT id FROM patients WHERE session_key = ?", session_key)


async def create_patient(session_key: str, name: str, phone: str,
                         birth_year: int | None = None) -> int:
    """Карточка без визита: регистратура завела пациента заранее (звонок,
    первичный приём без времени). Остальные поля дописывает update_patient."""
    return await _upsert_patient(session_key, name, phone, "ro", birth_year)


async def set_archived(pid: int, on: bool) -> None:
    """Архивация пациента: скрывает из списков, историю не трогает."""
    await log_event(pid, "archive",
                    "Pacient arhivat" if on else "Pacient scos din arhivă")
    await _execute(
        "UPDATE patients SET archived = $2 WHERE id = $1",
        "UPDATE patients SET archived = ? WHERE id = ?",
        *((pid, on) if not IS_SQLITE else (int(on), pid)),
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
        """SELECT a.id, a.service, a.doctor, a.doctor_id, a.starts_at, a.created_at,
                  p.name, p.phone
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.source = 'bot' AND a.status = 'confirmed' AND a.created_at >= $1
           ORDER BY a.created_at DESC LIMIT $2""",
        """SELECT a.id, a.service, a.doctor, a.doctor_id, a.starts_at, a.created_at,
                  p.name, p.phone
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.source = 'bot' AND a.status = 'confirmed' AND a.created_at >= ?
           ORDER BY a.created_at DESC LIMIT ?""",
        *((since, limit) if not IS_SQLITE else (_iso(since), limit)),
    )


# Диакритика румынского: поиск «Balan» должен находить «Bălan» и наоборот.
_DIA = str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaissttAAISSTT")


def _fold(s: str) -> str:
    return (s or "").translate(_DIA).lower()


# публичное имя для модулей: таблица диакритики обязана быть ОДНА на программу,
# иначе список пациентов и поиск разойдутся в том, что считать «Bălan»
fold = _fold


async def patient_appointments(patient_id: int, limit: int = 20) -> list:
    """Визиты пациента, свежие первыми. Предел по умолчанию — 20: столько
    хватает боковому предпросмотру списка. Фише нужен ВЕСЬ список (она зовёт с
    limit=1000): на ней стоит цифра «визитов всего», и с двадцаткой она врала
    бы у давнего пациента."""
    return await _fetch(
        """SELECT id, service, doctor, starts_at, status, source, comment
           FROM appointments WHERE patient_id = $1
           ORDER BY starts_at DESC LIMIT $2""",
        """SELECT id, service, doctor, starts_at, status, source, comment
           FROM appointments WHERE patient_id = ?
           ORDER BY starts_at DESC LIMIT ?""",
        patient_id, limit,
    )


# ---------- карточка пациента (v1.6.0: A2 зубы+план, A4 документы) ----------

PATIENT_FIELDS = ["name", "phone", "birth_date", "gender", "idnp", "email",
                  "address", "insurance", "primary_doctor", "file_no", "notes"]


async def get_patient(pid: int) -> dict | None:
    cols = ("id, session_key, name, phone, lang, birth_year, created_at, archived, "
            + ", ".join(PATIENT_FIELDS[2:]))
    rows = await _fetch(
        f"SELECT {cols} FROM patients WHERE id = $1",
        f"SELECT {cols} FROM patients WHERE id = ?", pid)
    return rows[0] if rows else None


async def update_patient(pid: int, data: dict) -> None:
    await log_event(pid, "profile", "Fișa pacientului a fost actualizată")
    """Обновление профиля: только известные поля, явным списком колонок."""
    sets_pg = ", ".join(f"{f} = ${i + 2}" for i, f in enumerate(PATIENT_FIELDS))
    sets_lt = ", ".join(f"{f} = ?" for f in PATIENT_FIELDS)
    vals = [data.get(f) for f in PATIENT_FIELDS]
    await _execute(
        f"UPDATE patients SET {sets_pg} WHERE id = $1",
        f"UPDATE patients SET {sets_lt} WHERE id = ?",
        *((pid, *vals) if not IS_SQLITE else (*vals, pid)),
    )


async def set_birth_year(pid: int, year: int) -> None:
    """Синк года из birth_date: возраст в поиске/сетке считается по birth_year."""
    await _execute(
        "UPDATE patients SET birth_year = $2 WHERE id = $1",
        "UPDATE patients SET birth_year = ? WHERE id = ?",
        *((pid, year) if not IS_SQLITE else (year, pid)),
    )


async def patient_alerts(pid: int) -> list:
    return await _fetch(
        "SELECT id, kind, text FROM patient_alerts WHERE patient_id = $1 ORDER BY id",
        "SELECT id, kind, text FROM patient_alerts WHERE patient_id = ? ORDER BY id", pid)


async def add_alert(pid: int, kind: str, text: str) -> None:
    await log_event(pid, "alert_add", f"Atenționare adăugată: {text}")
    await _execute(
        "INSERT INTO patient_alerts(patient_id, kind, text) VALUES($1, $2, $3)",
        "INSERT INTO patient_alerts(patient_id, kind, text, created_at) VALUES(?, ?, ?, ?)",
        *((pid, kind, text) if not IS_SQLITE else (pid, kind, text, _utcnow_iso())),
    )


async def delete_alert(alert_id: int, pid: int) -> None:
    await _execute(
        "DELETE FROM patient_alerts WHERE id = $1 AND patient_id = $2",
        "DELETE FROM patient_alerts WHERE id = ? AND patient_id = ?", alert_id, pid)


# Кто сейчас за журналом. Ставится приложением при старте (main.py), потому что
# db лежит НИЖЕ слоя доступа и импортировать его не может — иначе получился бы
# круг db → core.auth → db. Без хука всё работает как раньше: «recepție».
ACTOR_HOOK = None


def _actor_now(default: str = "recepție") -> str:
    """Имя вошедшего для летописи. Любая осечка молча даёт прежнюю подпись:
    журнал не имеет права уронить саму операцию."""
    try:
        return (ACTOR_HOOK() if ACTOR_HOOK else None) or default
    except Exception:                                   # noqa: BLE001
        return default


async def log_event(patient_id: int | None, kind: str, text: str, *,
                    actor: str = "", tooth: int | None = None) -> None:
    """Событие карты пациента. Никогда не роняет основную операцию: журнал —
    это летопись, а не транзакция; потерянная строка хуже, чем упавшая запись
    к врачу, только в одном случае — если из-за неё не состоялась сама запись."""
    if patient_id is None:
        return
    # подпись по умолчанию — ИМЯ вошедшего, а не канал: закон 195 спрашивает
    # «кто именно открыл фишу», и «recepție» на этот вопрос не отвечает
    actor = actor or _actor_now()
    try:
        await _execute(
            """INSERT INTO activity(patient_id, actor, kind, tooth, text)
               VALUES($1, $2, $3, $4, $5)""",
            """INSERT INTO activity(patient_id, at, actor, kind, tooth, text)
               VALUES(?, ?, ?, ?, ?, ?)""",
            *((patient_id, actor, kind, tooth, text[:200]) if not IS_SQLITE
              else (patient_id, _utcnow_iso(), actor, kind, tooth, text[:200])),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("activity %s/%s failed: %r", patient_id, kind, e)


async def log_clinic_event(kind: str, text: str, actor: str = "sistem") -> None:
    """Событие УРОВНЯ КЛИНИКИ — patient_id NULL. Попадает в ленту «Activitate
    recentă» (её LEFT JOIN такие строки переживает), но ни в одну фишу:
    фишам чужие события не принадлежат."""
    try:
        await _execute(
            """INSERT INTO activity(patient_id, actor, kind, text)
               VALUES(NULL, $1, $2, $3)""",
            """INSERT INTO activity(patient_id, at, actor, kind, text)
               VALUES(NULL, ?, ?, ?, ?)""",
            *((actor, kind, text[:200]) if not IS_SQLITE
              else (_utcnow_iso(), actor, kind, text[:200])),
        )
    except Exception as e:  # noqa: BLE001 — летопись не роняет операцию
        log.warning("clinic event %s failed: %r", kind, e)


async def _log_booking(pid: int, service: str, doctor: str,
                       starts_at: datetime, source: str) -> None:
    """Событие «записался» — одинаковое для обоих бэкендов, поэтому вынесено:
    у SQLite и PG разные пути возврата id, и логика легко разъезжается."""
    await log_event(pid, "appt_new",
                    f"Programare: {service} · {doctor} · "
                    f"{starts_at.strftime('%d.%m.%Y %H:%M')}",
                    actor="bot" if source == "bot" else "recepție")


async def patient_activity(pid: int, limit: int = 50, *,
                           include_views: bool = False) -> list:
    """История фиши. По умолчанию БЕЗ просмотров: журнал доступа (кто открывал
    карточку — требование закона 195) пишется в ту же таблицу, но в ленте фиши
    ему не место — рецепция открывает карточку по многу раз на дню, и лента из
    «Fișa deschisă» перестала бы читаться. Выгрузка данных пациента зовёт с
    include_views=True: в КОПИИ обязаны быть и просмотры — это тоже обработка."""
    if include_views:
        return await _fetch(
            """SELECT id, at, actor, kind, tooth, text FROM activity
               WHERE patient_id = $1 ORDER BY at DESC, id DESC LIMIT $2""",
            """SELECT id, at, actor, kind, tooth, text FROM activity
               WHERE patient_id = ? ORDER BY at DESC, id DESC LIMIT ?""",
            pid, limit)
    return await _fetch(
        """SELECT id, at, actor, kind, tooth, text FROM activity
           WHERE patient_id = $1 AND kind NOT IN ('view','doc_view')
           ORDER BY at DESC, id DESC LIMIT $2""",
        """SELECT id, at, actor, kind, tooth, text FROM activity
           WHERE patient_id = ? AND kind NOT IN ('view','doc_view')
           ORDER BY at DESC, id DESC LIMIT ?""", pid, limit)


async def recent_activity(limit: int = 10) -> list:
    """Последние события ПО ВСЕЙ клинике — лента «Activitate recentă» в
    аналитике. Просмотры отфильтрованы по той же причине, что в ленте фиши:
    рецепция открывает карточки десятки раз на дню, и лента из «Fișa deschisă»
    перестала бы читаться (журнал доступа живёт своей страницей)."""
    return await _fetch(
        """SELECT a.id, a.at, a.actor, a.kind, a.text, a.patient_id, p.name
           FROM activity a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.kind NOT IN ('view','doc_view')
           ORDER BY a.at DESC, a.id DESC LIMIT $1""",
        """SELECT a.id, a.at, a.actor, a.kind, a.text, a.patient_id, p.name
           FROM activity a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.kind NOT IN ('view','doc_view')
           ORDER BY a.at DESC, a.id DESC LIMIT ?""", limit)


async def tooth_activity(pid: int) -> list:
    """События по зубам — для истории конкретного зуба в диалоге."""
    return await _fetch(
        """SELECT at, actor, tooth, text FROM activity
           WHERE patient_id = $1 AND tooth IS NOT NULL ORDER BY at DESC, id DESC""",
        """SELECT at, actor, tooth, text FROM activity
           WHERE patient_id = ? AND tooth IS NOT NULL ORDER BY at DESC, id DESC""", pid)


async def _backfill_activity() -> None:
    """Разовый перенос уже существующих визитов в журнал: иначе у клиники,
    которая работает полгода, таймлайн стартует с пустого места, хотя история
    визитов у нас есть. Идемпотентно — отмечается флагом в schema_meta."""
    done = await _fetchval("SELECT value FROM schema_meta WHERE key = 'act_backfill'",
                           "SELECT value FROM schema_meta WHERE key = 'act_backfill'")
    if done:
        return
    rows = await _fetch(
        """SELECT id, patient_id, service, doctor, starts_at, created_at, source
           FROM appointments WHERE patient_id IS NOT NULL ORDER BY created_at""",
        """SELECT id, patient_id, service, doctor, starts_at, created_at, source
           FROM appointments WHERE patient_id IS NOT NULL ORDER BY created_at""")
    n = 0
    for r in rows:
        when = r["starts_at"]
        txt = f"Programare: {r['service']} · {r['doctor']}"
        if hasattr(when, "strftime"):
            txt += " · " + when.strftime("%d.%m.%Y %H:%M")
        await _execute(
            """INSERT INTO activity(patient_id, at, actor, kind, text)
               VALUES($1, $2, $3, $4, $5)""",
            """INSERT INTO activity(patient_id, at, actor, kind, text)
               VALUES(?, ?, ?, ?, ?)""",
            *((r["patient_id"], r["created_at"],
               "bot" if r["source"] == "bot" else "recepție", "appt_new", txt[:200])
              if not IS_SQLITE else
              (r["patient_id"], _iso(r["created_at"]) if hasattr(r["created_at"], "strftime")
               else str(r["created_at"]),
               "bot" if r["source"] == "bot" else "recepție", "appt_new", txt[:200])),
        )
        n += 1
    await _execute(
        """INSERT INTO schema_meta(key, value) VALUES('act_backfill', $1)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        """INSERT INTO schema_meta(key, value) VALUES('act_backfill', ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""", str(n))
    if n:
        log.warning("activity backfill: %s programări перенесены в журнал", n)


async def teeth_map(pid: int) -> dict:
    rows = await _fetch(
        "SELECT tooth, state, note, doctor, updated_at FROM teeth WHERE patient_id = $1",
        "SELECT tooth, state, note, doctor, updated_at FROM teeth WHERE patient_id = ?",
        pid)
    return {r["tooth"]: r for r in rows}


async def set_tooth(pid: int, tooth: int, state: str, note: str,
                    doctor: str = "") -> None:
    """'ok' без заметки и без врача = зуб здоров → строка удаляется (карта sparse).
    doctor — СНАПШОТ имени на момент записи, как в plan_items: переименование
    врача не должно переписывать историю зуба."""
    if state == "ok" and not note and not doctor:
        await _execute("DELETE FROM teeth WHERE patient_id = $1 AND tooth = $2",
                       "DELETE FROM teeth WHERE patient_id = ? AND tooth = ?", pid, tooth)
        await log_event(pid, "tooth", f"Dinte {tooth}: sănătos", tooth=tooth)
        return
    pg = """INSERT INTO teeth(patient_id, tooth, state, note, doctor, updated_at)
            VALUES($1, $2, $3, $4, $5, now())
            ON CONFLICT (patient_id, tooth) DO UPDATE
              SET state = EXCLUDED.state, note = EXCLUDED.note,
                  doctor = EXCLUDED.doctor, updated_at = now()"""
    lt = """INSERT INTO teeth(patient_id, tooth, state, note, doctor, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(patient_id, tooth) DO UPDATE
              SET state = excluded.state, note = excluded.note,
                  doctor = excluded.doctor, updated_at = excluded.updated_at"""
    await _execute(pg, lt, *((pid, tooth, state, note, doctor) if not IS_SQLITE
                             else (pid, tooth, state, note, doctor, _utcnow_iso())))
    txt = f"Dinte {tooth}: {state}"
    if doctor:
        txt += f" · {doctor}"
    if note:
        txt += f" · {note}"
    await log_event(pid, "tooth", txt, tooth=tooth)


async def plan_items(pid: int) -> list:
    return await _fetch(
        """SELECT id, tooth, procedure, doctor, status, price_mdl, due_date
           FROM plan_items WHERE patient_id = $1 ORDER BY id""",
        """SELECT id, tooth, procedure, doctor, status, price_mdl, due_date
           FROM plan_items WHERE patient_id = ? ORDER BY id""", pid)


async def add_plan_item(pid: int, tooth: int | None, procedure: str,
                        doctor: str, price_mdl: int | None,
                        due_date: str = "") -> None:
    await _execute(
        """INSERT INTO plan_items(patient_id, tooth, procedure, doctor, price_mdl,
                                  due_date) VALUES($1, $2, $3, $4, $5, $6)""",
        """INSERT INTO plan_items(patient_id, tooth, procedure, doctor, price_mdl,
                                  due_date, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        *((pid, tooth, procedure, doctor, price_mdl, due_date or None) if not IS_SQLITE
          else (pid, tooth, procedure, doctor, price_mdl, due_date or None,
                _utcnow_iso())),
    )
    await log_event(pid, "plan_add",
                    f"Plan: + {procedure}" + (f" (dinte {tooth})" if tooth else ""),
                    tooth=tooth)


async def set_plan_status(item_id: int, pid: int, status: str) -> None:
    done = status == "finalizat"
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = $1 AND patient_id = $2",
                        "SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
                        item_id, pid)
    if rows:
        await log_event(pid, "plan_status",
                        f"Plan: {rows[0]['procedure']} → {status}",
                        tooth=rows[0]["tooth"])
    await _execute(
        f"""UPDATE plan_items SET status = $1,
              done_at = {'now()' if done else 'NULL'}
            WHERE id = $2 AND patient_id = $3""",
        f"""UPDATE plan_items SET status = ?,
              done_at = {'?' if done else 'NULL'}
            WHERE id = ? AND patient_id = ?""",
        *((status, item_id, pid) if not IS_SQLITE
          else ((status, _utcnow_iso(), item_id, pid) if done
                else (status, item_id, pid))),
    )


async def delete_plan_item(item_id: int, pid: int) -> None:
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = $1 AND patient_id = $2",
                        "SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
                        item_id, pid)
    if rows:
        await log_event(pid, "plan_del", f"Plan: − {rows[0]['procedure']}",
                        tooth=rows[0]["tooth"])
    await _execute(
        "DELETE FROM plan_items WHERE id = $1 AND patient_id = $2",
        "DELETE FROM plan_items WHERE id = ? AND patient_id = ?", item_id, pid)


async def documents(pid: int) -> list:
    return await _fetch(
        """SELECT id, filename, size, mime, category, uploaded_at
           FROM documents WHERE patient_id = $1 ORDER BY id DESC""",
        """SELECT id, filename, size, mime, category, uploaded_at
           FROM documents WHERE patient_id = ? ORDER BY id DESC""", pid)


# ---------- право на стирание (закон 195) ----------
# Веток ДВЕ, и это не перестраховка. Право пациента на стирание не отменяет
# обязанность клиники хранить медицинскую документацию, поэтому:
#   * контакт БЕЗ лечения (записался и не пришёл, отменил) — удаляется физически;
#   * пациент С лечением — ОБЕЗЛИЧИВАЕТСЯ: личность стирается, клиническая
#     часть остаётся под номером фиши.
# ⚠️ Состав таблиц здесь обязан совпадать с modules/patients/export.py: обе
# стороны отвечают на вопрос «где в базе лежит этот человек». Разойдутся —
# получится либо неполная выдача, либо неполное удаление, и заметить неоткуда.

async def erasure_kind(pid: int) -> str:
    """'delete' — можно физически, 'anon' — только обезличивание.

    Лечением считается: запись о зубе, план, документ, визит со статусом
    done/arrived ЛИБО подтверждённый визит в прошлом (раз не отменён и не
    отмечен «не пришёл» — приём, скорее всего, состоялся, и вычеркнуть его —
    значит переписать медицинскую историю задним числом).
    """
    async def _n(pg: str, lt: str, *a) -> int:
        return int(await _fetchval(pg, lt, *a) or 0)

    teeth = await _n("SELECT COUNT(*) FROM teeth WHERE patient_id = $1",
                     "SELECT COUNT(*) FROM teeth WHERE patient_id = ?", pid)
    plan = await _n("SELECT COUNT(*) FROM plan_items WHERE patient_id = $1",
                    "SELECT COUNT(*) FROM plan_items WHERE patient_id = ?", pid)
    docs = await _n("SELECT COUNT(*) FROM documents WHERE patient_id = $1",
                    "SELECT COUNT(*) FROM documents WHERE patient_id = ?", pid)
    now = datetime.now(timezone.utc)
    happened = await _n(
        """SELECT COUNT(*) FROM appointments WHERE patient_id = $1
           AND (status IN ('done','arrived')
                OR (status = 'confirmed' AND starts_at < $2))""",
        """SELECT COUNT(*) FROM appointments WHERE patient_id = ?
           AND (status IN ('done','arrived')
                OR (status = 'confirmed' AND starts_at < ?))""",
        *((pid, now) if not IS_SQLITE else (pid, _iso(now))))
    return "anon" if (teeth or plan or docs or happened) else "delete"


async def delete_patient_fully(pid: int) -> None:
    """Физическое удаление: строка пациента и ВСЁ, что на неё ссылается.

    Порядок — дети раньше родителя: в PG внешние ключи иначе откажут, а SQLite
    молча оставил бы сирот, которых потом нашла бы только выгрузка чужого id.
    Файлы документов на диске удаляет ВЫЗЫВАЮЩИЙ (маршрут): db не знает про
    раскладку файлов, и это его единственная граница.
    """
    for pg, lt in (
        ("DELETE FROM activity WHERE patient_id = $1",
         "DELETE FROM activity WHERE patient_id = ?"),
        ("DELETE FROM patient_alerts WHERE patient_id = $1",
         "DELETE FROM patient_alerts WHERE patient_id = ?"),
        ("DELETE FROM teeth WHERE patient_id = $1",
         "DELETE FROM teeth WHERE patient_id = ?"),
        ("DELETE FROM plan_items WHERE patient_id = $1",
         "DELETE FROM plan_items WHERE patient_id = ?"),
        ("DELETE FROM documents WHERE patient_id = $1",
         "DELETE FROM documents WHERE patient_id = ?"),
        ("DELETE FROM appointments WHERE patient_id = $1",
         "DELETE FROM appointments WHERE patient_id = ?"),
        ("DELETE FROM patients WHERE id = $1",
         "DELETE FROM patients WHERE id = ?"),
    ):
        await _execute(pg, lt, pid)
    log.warning("patient %s deleted (erasure request, no medical records)", pid)


async def anonymize_patient(pid: int) -> None:
    """Обезличивание: стереть, КТО это, оставив, ЧТО лечили.

    Стираются поля личности; клиника (зубы, план, визиты, документы-снимки)
    остаётся под номером фиши. session_key получает вид 'anon:<id>' —
    колонка UNIQUE NOT NULL, а прежний ключ содержит телефон или tg-id, то
    есть сам по себе личность. archived ставится тут же: обезличенная фиша
    не должна показываться в живых списках.

    ⚠️ Комментарии визитов и заметки стираются тоже: это свободный текст, и
    рецепция пишет туда что угодно — вплоть до «сестра Иона Попеску».
    """
    await _execute(
        """UPDATE patients SET name = $2, phone = NULL, email = NULL,
             birth_date = NULL, birth_year = NULL, gender = NULL, idnp = NULL,
             address = NULL, insurance = NULL, notes = NULL,
             session_key = $3, archived = TRUE WHERE id = $1""",
        """UPDATE patients SET name = ?, phone = NULL, email = NULL,
             birth_date = NULL, birth_year = NULL, gender = NULL, idnp = NULL,
             address = NULL, insurance = NULL, notes = NULL,
             session_key = ?, archived = 1 WHERE id = ?""",
        *((pid, f"Pacient anonimizat #{pid}", f"anon:{pid}") if not IS_SQLITE
          else (f"Pacient anonimizat #{pid}", f"anon:{pid}", pid)))
    await _execute(
        "UPDATE appointments SET comment = '' WHERE patient_id = $1",
        "UPDATE appointments SET comment = '' WHERE patient_id = ?", pid)
    log.warning("patient %s anonymized (erasure request, has medical records)", pid)


async def documents_with_paths(pid: int) -> list:
    """То же, что documents(), но с путём к файлу на диске.

    Отдельной функцией, а не полем в documents(): путь нужен ровно двум местам —
    выгрузке данных пациента и удалению — и не должен попадать на страницы,
    откуда его видно в исходном коде HTML.
    """
    return await _fetch(
        """SELECT id, filename, stored_path, size, mime, category, uploaded_at
           FROM documents WHERE patient_id = $1 ORDER BY id""",
        """SELECT id, filename, stored_path, size, mime, category, uploaded_at
           FROM documents WHERE patient_id = ? ORDER BY id""", pid)


async def add_document(pid: int, filename: str, stored_path: str,
                       size: int, mime: str, category: str = "alt") -> None:
    await _execute(
        """INSERT INTO documents(patient_id, filename, stored_path, size, mime, category)
           VALUES($1, $2, $3, $4, $5, $6)""",
        """INSERT INTO documents(patient_id, filename, stored_path, size, mime,
                                 category, uploaded_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        *((pid, filename, stored_path, size, mime, category) if not IS_SQLITE
          else (pid, filename, stored_path, size, mime, category, _utcnow_iso())),
    )
    await log_event(pid, "doc_add", f"Document încărcat: {filename}")


async def get_document(doc_id: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, patient_id, filename, stored_path, size, mime
           FROM documents WHERE id = $1""",
        """SELECT id, patient_id, filename, stored_path, size, mime
           FROM documents WHERE id = ?""", doc_id)
    return rows[0] if rows else None


async def delete_document(doc_id: int, pid: int) -> None:
    d = await get_document(doc_id)
    if d and d["patient_id"] == pid:
        await log_event(pid, "doc_del", f"Document șters: {d['filename']}")
    await _execute(
        "DELETE FROM documents WHERE id = $1 AND patient_id = $2",
        "DELETE FROM documents WHERE id = ? AND patient_id = ?", doc_id, pid)


async def set_comment(appt_id: int, text: str) -> None:
    await _execute(
        "UPDATE appointments SET comment = $2 WHERE id = $1",
        "UPDATE appointments SET comment = ? WHERE id = ?",
        *((appt_id, text) if not IS_SQLITE else (text, appt_id)),
    )


_STATUS_RO = {"confirmed": "confirmată", "arrived": "în cabinet",
              "done": "finalizată", "noshow": "neprezentare",
              "cancelled": "anulată"}


async def set_status(appt_id: int, status: str) -> bool:
    """False = смена статуса нарушила бы занятость (вернули confirmed, а
    интервал уже занят новой записью) — журнал показывает «интервал занят»."""
    async with _BOOK_LOCK:
        if status in ACTIVE_STATUSES:
            # возврат в активный статус = та же интервальная проверка, что
            # при новой брони: uq-индексы ловят лишь совпадающие старты
            rows = await _fetch(
                """SELECT doctor, doctor_id, starts_at, duration_min, status
                   FROM appointments WHERE id = $1""",
                """SELECT doctor, doctor_id, starts_at, duration_min, status
                   FROM appointments WHERE id = ?""", appt_id)
            if rows:
                r = rows[0]
                if r["status"] not in ACTIVE_STATUSES and await _conflicts(
                        r["doctor_id"], r["doctor"], r["starts_at"],
                        int(r["duration_min"] or 60), exclude_id=appt_id):
                    return False
        try:
            await _execute(
                "UPDATE appointments SET status = $2 WHERE id = $1",
                "UPDATE appointments SET status = ? WHERE id = ?",
                *((appt_id, status) if not IS_SQLITE else (status, appt_id)),
            )
            own = await _fetch(
                "SELECT patient_id, service FROM appointments WHERE id = $1",
                "SELECT patient_id, service FROM appointments WHERE id = ?", appt_id)
            if own and own[0]["patient_id"]:
                await log_event(own[0]["patient_id"], "appt_status",
                                f"Vizită {_STATUS_RO.get(status, status)}: "
                                f"{own[0]['service']}")
            return True
        except Exception as e:  # noqa: BLE001 — uq_doctor_slot/uq_patient_slot
            if "uq_" in str(e) or "unique" in str(e).lower():
                if IS_SQLITE:
                    await _CONN.rollback()
                return False
            raise
