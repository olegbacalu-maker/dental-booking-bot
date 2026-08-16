"""Слой БД с двумя бэкендами:
- PostgreSQL (asyncpg) — облачное издание (Docker/VPS);
- SQLite (aiosqlite)  — desktop-издание (.exe, файл data/dental.db).
Бэкенд выбирается по DATABASE_URL (sqlite:///... → SQLite).
Даты в SQLite храним как ISO-строки в UTC — сравнения лексикографичны."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

log = logging.getLogger("db")

# Версия схемы: шаги применяются по одному и записываются в schema_meta,
# поэтому по базе клиники всегда видно, докуда она домигрирована.
# ⚠️ Новый шаг в MIGRATIONS_* без поднятия версии — МЁРТВЫЙ код: цикл _migrate
# идёт range(have+1, SCHEMA_VERSION+1) и до него не дойдёт (так шаг 4 с
# 'waiting' в uq-индексах не исполнялся ни у одной клиники; держит
# test_structure).
SCHEMA_VERSION = 4

# Записи, которые ЗАНИМАЮТ слот врача. 'waiting' (пациент пришёл, ждёт в
# приёмной, 08-13) стоит между confirmed и arrived: физически человек уже в
# клинике, и слот его. 'arrived' (пациент в кабинете) обязан
# быть здесь: иначе отметка «пришёл» освобождает час и бот сажает второго.
ACTIVE_STATUSES = ("confirmed", "waiting", "arrived")
_ACT_SQL = "('confirmed','waiting','arrived')"

POOL = None          # asyncpg pool
_CONN = None         # aiosqlite connection
# Модуль DBAPI, которым ОТКРЫТА картотека: штатный sqlite3 или sqlcipher3.
# ⚠️ Ловить исключения обязательно ЧЕРЕЗ него. У sqlcipher3 своя иерархия, и
# `except sqlite3.IntegrityError` на зашифрованной базе не поймает ничего —
# защита от двойной записи отвалилась бы молча и только у той клиники, которая
# включила шифрование. Ставится в init(), до него значения нет.
_SQ = None

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
-- ВНИМАНИЕ: уникальных индексов слота здесь НЕТ намеренно (08-16). У них ОДИН
-- владелец — _slot_guard_apply, и он единственный, кто перед CREATE UNIQUE
-- INDEX спрашивает ДАННЫЕ. Эта схема исполняется при КАЖДОМ старте и ДО
-- миграций: оставленный тут CREATE падал бы у клиники с двойной бронью раньше,
-- чем сторож успеет хоть что-то сделать, и программа не открывалась бы вовсе.
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'bot';
ALTER TABLE appointments ALTER COLUMN patient_id DROP NOT NULL;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_day BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_2h BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS comment TEXT NOT NULL DEFAULT '';
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS waiting_at TIMESTAMPTZ;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS arrived_at TIMESTAMPTZ;
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
-- поверхности зуба (M/O/D/V/L) одной строкой: у состояния зуба их может быть
-- несколько сразу («MOD»), но состояние остаётся ОДНО на зуб
ALTER TABLE teeth ADD COLUMN IF NOT EXISTS surfaces TEXT NOT NULL DEFAULT '';
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
CREATE TABLE IF NOT EXISTS payments(
  id SERIAL PRIMARY KEY,
  patient_id INT NOT NULL REFERENCES patients(id),
  amount_mdl INT NOT NULL,
  method TEXT NOT NULL DEFAULT 'numerar',
  note TEXT NOT NULL DEFAULT '',
  taken_by TEXT NOT NULL DEFAULT '',
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pay_patient ON payments(patient_id, at DESC);
CREATE INDEX IF NOT EXISTS ix_pay_at ON payments(at DESC);
-- Дневник визита (consultația): запись приёма 1:1 к appointments — будущая
-- дневниковая часть формы 043/e. doctor — снапшот имени на момент приёма.
CREATE TABLE IF NOT EXISTS visit_records(
  id SERIAL PRIMARY KEY,
  appointment_id INT NOT NULL UNIQUE REFERENCES appointments(id),
  patient_id INT NOT NULL REFERENCES patients(id),
  doctor TEXT NOT NULL DEFAULT '',
  acuze TEXT NOT NULL DEFAULT '',
  examen TEXT NOT NULL DEFAULT '',
  diagnostic TEXT NOT NULL DEFAULT '',
  tratament TEXT NOT NULL DEFAULT '',
  recomandari TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_visit_patient ON visit_records(patient_id);
-- на каком приёме позиция плана была выполнена (NULL = финал без визита/не финал)
ALTER TABLE plan_items ADD COLUMN IF NOT EXISTS appointment_id INT;
-- отказ пациента от процедуры: ст.13(5) Legea 263/2005 требует, чтобы отказ
-- ОСТАЛСЯ в меддокументации с указанием возможных последствий, а не исчез
ALTER TABLE plan_items ADD COLUMN IF NOT EXISTS refuz_motiv TEXT NOT NULL DEFAULT '';
-- Анамнез: опросник «до кресла», один на пациента. Заполняет раздел 2 формы
-- 043/e. flags — отмеченные состояния одной строкой ('diabet,hepatita'),
-- чтобы добавление вопроса не требовало миграции у клиники.
CREATE TABLE IF NOT EXISTS anamneza(
  patient_id INT PRIMARY KEY REFERENCES patients(id),
  flags TEXT NOT NULL DEFAULT '',
  boli TEXT NOT NULL DEFAULT '',
  medicamente TEXT NOT NULL DEFAULT '',
  alergii TEXT NOT NULL DEFAULT '',
  anestezie TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS schema_meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# Предикат, который стоял у клиник ДО 08-13 (его ставили шаги 2–3). Это
# ЗАПАСНОЙ вариант шага 4: если развести двойную бронь может только человек,
# защита обязана остаться прежней, а не исчезнуть.
_OLD_ACT_SQL = "('confirmed','arrived')"

# ЛЕСТНИЦА предикатов, от самого широкого к запасному. Ступень выбирается ПО
# КАЖДОМУ индексу отдельно: берётся первая, под которой нет конфликтов ИМЕННО
# этого индекса; не подходит ни одна — этот индекс не трогается вовсе.
# ⛔ И сверх того: индекс НИКОГДА не заменяется на более УЗКИЙ. Существующий
# широкий индекс сам, своими данными, доказал, что широкий предикат выполним, —
# и спорить с ним подсчётом конфликтов соседнего индекса значит своими руками
# ослабить работающую защиту (08-16, измерено «отбито» → «прошло»).
# ⛔ Одной ступени мало, и это проверено опытом (08-16): база старше v1.7.0
# несёт пару confirmed+arrived в одном слоте — её пропускал ТОГДАШНИЙ базовый
# индекс (WHERE status='confirmed'), но не пропускает узкий предикат. Одна
# ступень означала «узкий тоже не лёг», а DROP при этом уже случился: работавшая
# защита снималась и не возвращалась НИКОГДА (каждый следующий старт повторял ту
# же неудачу). Отсюда правило: сначала выяснить, ляжет ли, и только потом сносить.
_UQ_LADDER = (_ACT_SQL, _OLD_ACT_SQL)

# Шаг миграции, который кладёт страховочные индексы. Именной, потому что он
# единственный, кому НЕЛЬЗЯ ронять старт (см. _slot_guard_apply).
UQ_GUARD_STEP = 4
# Метка незавершённости в schema_meta: широкие индексы не легли, стоит узкая
# страховка. Пока метка есть, КАЖДЫЙ старт пробует доложить широкие заново.
UQ_PENDING_KEY = "uq_waiting_pending"
# Почему сработало самолечение. ⚠️ Два РАЗНЫХ события, и текст в летописи у них
# разный: индексов не было вовсе / индексы были, но с более узким предикатом.
UQ_REPAIR_GONE = "gone"
UQ_REPAIR_NARROW = "narrow"

# ИСХОДЫ вердикта о страховке — ровно три, и смешивать их нельзя.
# ⭐ Третий заведён 08-16: неудачное чтение состояния давало пустой словарь, а
# пустой словарь читался как «в базе нет ни одной проверки» — и директору
# печаталось, что тот же час можно занять дважды без предупреждения. Это
# утверждение, которого никто не проверял: мы не ЗНАЕМ состояния, а не знаем,
# что его нет. Говорить только проверенное — то самое правило, ради которого
# переписывался и сам баннер.
UQ_NARROW = "narrow"      # все проверки в базе ЕСТЬ, но предикат уже нужного
UQ_BROKEN = "broken"      # каких-то проверок в базе НЕТ — прочитано
UQ_UNKNOWN = "unknown"    # состояние прочитать НЕ УДАЛОСЬ — не знаем ничего


def _uq_slot_sql(act_sql: str, names: tuple = ()) -> list[str]:
    """Пересоздание слотовых уникальных индексов под заданный предикат.

    ⚠️ ИМЕНА индексов обязаны остаться прежними: по ним же ловятся конфликты
    выше по коду.
    ⛔ Порядок «DROP и сразу CREATE, по одному индексу» — не вкус. У SQLite DDL
    идёт вне транзакции, и отказ одного CREATE (диск, блокировка, чужой объект с
    тем же именем) не имеет права уносить с собой индексы, которых он не
    касался. Снести все три и только потом класть значило бы, что первая же
    неудача оставляет картотеку вообще без защиты слота (08-16).
    ⭐ `names` — не украшение: ступень лестницы выбирается ПО КАЖДОМУ индексу
    отдельно, поэтому и перекладывается ровно тот, кому это нужно, и ровно под
    своим предикатом (08-16, см. _slot_guard_apply).
    """
    body = {
        "uq_doctor_slot":
            f"""CREATE UNIQUE INDEX uq_doctor_slot ON appointments(doctor, starts_at)
                WHERE status IN {act_sql}""",
        "uq_patient_slot":
            f"""CREATE UNIQUE INDEX uq_patient_slot ON appointments(patient_id, starts_at)
                WHERE status IN {act_sql}""",
        "uq_doctor_slot_id":
            f"""CREATE UNIQUE INDEX uq_doctor_slot_id ON appointments(doctor_id, starts_at)
                WHERE status IN {act_sql} AND doctor_id IS NOT NULL""",
    }
    out: list[str] = []
    for name in (names or tuple(body)):
        out.append(f"DROP INDEX IF EXISTS {name}")
        out.append(body[name])
    return out


# Индексы под горячие пути (день, история пациента, «новые из бота», карточка).
# ⛔ Уникальные индексы слота НЕ кладёт ни один обычный шаг: их владелец —
# _slot_guard_apply (см. UQ_GUARD_STEP). Обычный шаг исполняется циклом
# _migrate и обязан упасть, если не сделал своё дело; для CREATE UNIQUE INDEX
# «упасть» значит «клиника больше не открывает программу», а развести двойную
# бронь может только человек.
MIGRATIONS_PG = {
    1: [
        "CREATE INDEX IF NOT EXISTS ix_appt_starts ON appointments(starts_at)",
        "CREATE INDEX IF NOT EXISTS ix_appt_patient ON appointments(patient_id, starts_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_appt_created ON appointments(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_plan_patient ON plan_items(patient_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_patient ON documents(patient_id)",
    ],
    # 2 и 3 ПУСТЫ намеренно (08-16). Оба клали те же три уникальных индекса
    # слота — шаг 2 по имени врача и по пациенту, шаг 3 по doctor_id, — и оба
    # роняли старт НАВСЕГДА у клиники, чьи данные этим индексам противоречат
    # (переименованный врач = два визита в один час с одним doctor_id). Теперь у
    # слотовых индексов ОДИН владелец — _slot_guard_apply на шаге UQ_GUARD_STEP,
    # и он кладёт сразу нужный предикат: догонять шагами нечего.
    # ⚠️ Ключи остаются: по ним считается «версия схемы = последний шаг», и
    # клиника на версии 1 обязана дойти до 4, а не застрять на «шага нет».
    2: [],
    3: [],
    # 4 (08-13): статус 'waiting' вошёл в ACTIVE_STATUSES, а предикаты
    # уникальных индексов У УСТАНОВЛЕННЫХ клиник остались со старым списком —
    # waiting-визит выпал бы из защиты от двойной брони МОЛЧА. Саму работу
    # делает _slot_guard_apply (см. UQ_GUARD_STEP): расширение предиката
    # упирается в ЖИВЫЕ данные, и прямое исполнение роняло бы старт (08-16).
    # ⚠️ Список ПУСТ, но НЕ мёртв: _migrate исполняет его и на этом шаге, после
    # сторожа. Иначе дописанный сюда через месяц оператор молча не выполнился бы,
    # а версия схемы записалась бы как выполненная — то самое, ради чего рядом
    # стоит `raise RuntimeError('missing migration step')`.
    # ⛔ Ключ — ЧИСЛО, а не UQ_GUARD_STEP: сторож раскладки читает исходник
    # модулем ast и видит только литералы, с именем правило ослепло бы молча.
    4: [],
}
MIGRATIONS_LITE = {
    1: [
        "CREATE INDEX IF NOT EXISTS ix_appt_starts ON appointments(starts_at)",
        "CREATE INDEX IF NOT EXISTS ix_appt_patient ON appointments(patient_id, starts_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_appt_created ON appointments(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_plan_patient ON plan_items(patient_id)",
        "CREATE INDEX IF NOT EXISTS ix_doc_patient ON documents(patient_id)",
    ],
    # см. комментарий к шагам 2–4 в MIGRATIONS_PG
    2: [],
    3: [],
    4: [],
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
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  amount_mdl INTEGER NOT NULL,
  method TEXT NOT NULL DEFAULT 'numerar',
  note TEXT NOT NULL DEFAULT '',
  taken_by TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pay_patient ON payments(patient_id, at DESC);
CREATE INDEX IF NOT EXISTS ix_pay_at ON payments(at DESC);
CREATE TABLE IF NOT EXISTS visit_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  doctor TEXT NOT NULL DEFAULT '',
  acuze TEXT NOT NULL DEFAULT '',
  examen TEXT NOT NULL DEFAULT '',
  diagnostic TEXT NOT NULL DEFAULT '',
  tratament TEXT NOT NULL DEFAULT '',
  recomandari TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_visit_patient ON visit_records(patient_id);
CREATE TABLE IF NOT EXISTS anamneza(
  patient_id INTEGER PRIMARY KEY REFERENCES patients(id),
  flags TEXT NOT NULL DEFAULT '',
  boli TEXT NOT NULL DEFAULT '',
  medicamente TEXT NOT NULL DEFAULT '',
  alergii TEXT NOT NULL DEFAULT '',
  anestezie TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT
);
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
    # дневник визита: на каком приёме позиция плана была выполнена
    ("plan_items", "appointment_id INTEGER"),
    # отказ пациента от позиции плана — причина и последствия (ст.13(5))
    ("plan_items", "refuz_motiv TEXT NOT NULL DEFAULT ''"),
    # поверхности зуба (M/O/D/V/L), см. PG-схему
    ("teeth", "surfaces TEXT NOT NULL DEFAULT ''"),
    # 08-13: штампы конвейера приёма — «пришёл» и «зашёл в кабинет».
    # Разница пар = время ожидания в приёмной (метрика в Statistici)
    ("appointments", "waiting_at TEXT"),
    ("appointments", "arrived_at TEXT"),
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
-- ВНИМАНИЕ: уникальных индексов слота здесь НЕТ — тот же комментарий в PG_SCHEMA:
-- их кладёт _slot_guard_apply, единственный, кто сначала спрашивает данные.
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
            "last_at", "next_at", "done_at", "waiting_at", "arrived_at"}


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


# ---------- страховочные индексы слота ----------

# Три уникальных индекса, которые И ЕСТЬ защита от двойной брони. ⚠️ Владелец у
# них ОДИН — _slot_guard_apply: ни базовая схема, ни обычные шаги миграций их
# больше не создают. Причина в том, что CREATE UNIQUE INDEX — операция НАД
# ЖИВЫМИ ДАННЫМИ: у клиники с двойной бронью он падает, а падение в базовой
# схеме или в обычном шаге = «после обновления программа не открывается», и
# навсегда (08-16).
_UQ_SLOT = ("uq_doctor_slot", "uq_patient_slot", "uq_doctor_slot_id")

# Сколько всего проверок — числом. ⚠️ Литерал «3» в текстах живёт ровно до
# четвёртого индекса и расходится с _UQ_SLOT МОЛЧА: баннер начнёт считать
# «minus один», а строка летописи уедет неверной навсегда.
UQ_SLOT_COUNT = len(_UQ_SLOT)

# Состояние страховки в ЭТОМ процессе: баннер рисует layout синхронно, а
# спросить базу он не может. Устроено как TAMPER_ALERT у auth — тем же приёмом
# (метка в schema_meta + баннер директору), а не вторым механизмом.
#   pending — полная защита не встала, директору есть что сказать;
#   level   — UQ_NARROW все проверки в базе есть, но какая-то уже ожидаемой;
#             UQ_BROKEN какой-то проверки в базе НЕТ; UQ_UNKNOWN состояние
#             прочитать не удалось (это три разные новости, и текст у них
#             разный). ⛔ Ни одно из них не значит «защиты нет»: такого код не
#             проверяет и утверждать не вправе;
#   gone    — ИМЕННО те проверки, которых в базе нет (для честного текста);
#   rows    — что именно развести (тип, кто, час, сколько записей);
#   ran     — шаг уже отработал в этом запуске (миграция), второй раз не надо.
_SLOT_GUARD: dict = {"pending": False, "level": "", "rows": [], "gone": [],
                     "ran": False}


def slot_guard() -> dict:
    """Состояние страховки от двойной брони — для баннера директору."""
    return _SLOT_GUARD


# Слоты, в которых под ЗАДАННЫМ предикатом больше одной живой записи, то есть
# ровно то, обо что разбивается CREATE UNIQUE INDEX. Спрашиваем ДАННЫЕ заранее,
# а не ловим исключение постфактум: у SQLite DDL идёт вне транзакции, и упавший
# CREATE после трёх DROP оставил бы картотеку вообще без защиты слота.
# ⚠️ Предикат — АРГУМЕНТ, а не вшитый _ACT_SQL: спрашивать надо про КАЖДУЮ
# ступень лестницы, иначе «широкий не лёг» молча означало бы «узкий тоже», и
# запасной путь сносил бы работающую защиту вслепую (08-16, проверено опытом).
# ⚠️ min(...) вместо голой колонки не для красоты: в PG колонка не из GROUP BY
# в списке выбора — ошибка, и запрос отвалился бы только у облачного издания.
# ⚠️ Тип пары («medic»/«pacient») едет из запроса, а не угадывается по имени:
# смешать в одном списке имена врачей и пациентов значит дать директору совет,
# который для половины строк неверен (см. _slot_banner).
# ⭐ Первый элемент — ИМЯ ИНДЕКСА, к которому относится запрос. Связь была и
# раньше, но жила в голове (порядок кортежей), а нужна в коде: ступень лестницы
# выбирается по каждому индексу отдельно, и «под чьим предикатом конфликт»
# перестало быть риторическим вопросом (08-16).
def _slot_conflict_sql(act_sql: str) -> tuple[tuple[str, str, str], ...]:
    return (
        ("uq_doctor_slot", "medic",
         f"""SELECT a.doctor AS who, a.starts_at AS starts_at, count(*) AS n
               FROM appointments a
              WHERE a.status IN {act_sql}
              GROUP BY a.doctor, a.starts_at HAVING count(*) > 1"""),
        ("uq_doctor_slot_id", "medic",
         f"""SELECT min(a.doctor) AS who, a.starts_at AS starts_at, count(*) AS n
               FROM appointments a
              WHERE a.status IN {act_sql} AND a.doctor_id IS NOT NULL
              GROUP BY a.doctor_id, a.starts_at HAVING count(*) > 1"""),
        ("uq_patient_slot", "pacient",
         f"""SELECT min(p.name) AS who, a.starts_at AS starts_at, count(*) AS n
               FROM appointments a JOIN patients p ON p.id = a.patient_id
              WHERE a.status IN {act_sql} AND a.patient_id IS NOT NULL
              GROUP BY a.patient_id, a.starts_at HAVING count(*) > 1"""),
    )

# Что реально лежит в базе. ⭐ Спрашивать СУБД, а не помнить, что мы сделали:
# без этого «прежняя защита осталась» — обещание, которое баннер печатает
# директору, а код нигде не проверял.
_UQ_STATE_PG = ("SELECT indexname AS name, indexdef AS sql FROM pg_indexes "
                "WHERE indexname IN ('uq_doctor_slot','uq_patient_slot',"
                "'uq_doctor_slot_id')")
_UQ_STATE_LITE = ("SELECT name AS name, COALESCE(sql,'') AS sql "
                  "FROM sqlite_master WHERE type='index' AND name IN "
                  "('uq_doctor_slot','uq_patient_slot','uq_doctor_slot_id')")


async def _slot_conflicts(act_sql: str = _ACT_SQL) -> dict[str, list[dict]]:
    """Конфликтующие слоты ПОД ЗАДАННЫМ предикатом, ПО КАЖДОМУ индексу.

    Ответ разложен по именам индексов, а не сведён в один список, потому что
    решение принимается по каждому индексу своё: конфликт под широким предикатом
    у `uq_doctor_slot_id` (переименованный врач) ничего не говорит о том, ляжет
    ли широкий `uq_patient_slot`. Свести их в одну кучу значит опустить на
    запасную ступень все три — и уменьшить защиту, которая работала.
    Директорский список собирает `_slot_rows` — он же и схлопывает повторы.
    """
    out: dict[str, list[dict]] = {}
    for name, kind, sql in _slot_conflict_sql(act_sql):
        out[name] = [{"kind": kind, "who": r.get("who") or "",
                      "when": r["starts_at"], "n": int(r["n"])}
                     for r in await _fetch(sql, sql)]
    return out


def _slot_rows(by_index: dict[str, list[dict]]) -> list[dict]:
    """Один список для директора: что именно развести.

    Врач по имени и врач по id почти всегда называют ОДИН и тот же слот, поэтому
    пары схлопываются: директор должен увидеть список того, что разводить, а не
    тройной пересчёт одного часа. Пациент НЕ схлопывается с врачом даже при
    совпадении часа — это разные конфликты, и чинятся они по-разному.
    """
    seen: dict[tuple, dict] = {}
    for rows in by_index.values():
        for r in rows:
            key = (r["kind"], r["who"], r["when"])
            prev = seen.get(key)
            if prev is None or r["n"] > prev["n"]:
                seen[key] = dict(r)
    return sorted(seen.values(),
                  key=lambda x: (str(x["when"]), x["kind"], x["who"]))


async def _uq_index_state() -> dict[str, str]:
    """Имя слотового индекса → текст его определения, ПО ФАКТУ в базе."""
    return {r["name"]: str(r["sql"] or "")
            for r in await _fetch(_UQ_STATE_PG, _UQ_STATE_LITE)}


# Статусы из текста предиката или из определения индекса. ⭐ Сверяется НАБОР,
# а не одно слово-различитель: ступеней у лестницы больше двух не будет только
# до первой правки, а «есть ли в тексте 'waiting'» перестаёт различать предикаты
# ровно тогда, когда ступеней станет три, — и сломалось бы это тихо (индексы
# перекладывались бы каждый старт, потому что «не совпадает никогда»).
# У клиники старше v1.7.0 предикат вообще был `status='confirmed'`, и по одному
# слову он неотличим от запасного — набор различает их сразу.
_UQ_WORD = re.compile(r"'([a-z_]+)'")


def _uq_statuses(sql: str) -> frozenset:
    return frozenset(_UQ_WORD.findall(sql or ""))


def _uq_matches(state: dict[str, str], act_sql: str) -> bool:
    """Все три индекса на месте и ровно с тем предикатом, который заказан.

    Сверять побайтово нельзя — текст пишет сама СУБД (SQLite отдаёт наш CREATE,
    Postgres — свой разбор с ARRAY[...]::text), и равенство не сошлось бы
    никогда именно у облачного издания. Поэтому сверяется набор статусов: в
    определении слотового индекса других строк в кавычках нет ни у одного из
    бэкендов.
    """
    want = _uq_statuses(act_sql)
    return all(name in state and _uq_statuses(state[name]) == want
               for name in _UQ_SLOT)


# Как назвать проверку человеку. ⚠️ Имена индексов директору не показываются:
# «uq_doctor_slot_id» — это разговор с базой, а не с клиникой. Словарь живёт
# здесь, рядом с _UQ_SLOT: разъедься они, баннер назвал бы не ту проверку.
_UQ_RO = {
    "uq_doctor_slot": "aceeași oră la același medic",
    "uq_patient_slot": "aceeași oră la același pacient",
    "uq_doctor_slot_id": "aceeași oră la medicul redenumit",
}


def _uq_gone(state: dict[str, str]) -> list[str]:
    """Слотовые индексы, которых в базе НЕТ ВООБЩЕ.

    ⭐ Это единственное, что код про страховку знает наверняка, и потому
    единственное, о чём он имеет право говорить директору. «Предикат уже
    ожидаемого» — не «защиты нет»: такая проверка стоит и работает, просто не
    покрывает waiting-визиты.
    """
    return [name for name in _UQ_SLOT if name not in state]


def uq_gone_ro(gone: list[str]) -> str:
    """Пропавшие проверки словами, для летописи и баннера."""
    return ", ".join(_UQ_RO.get(name, name) for name in gone)


# Числительные словами: «lipsesc 2 verificări» читается как машинный текст ровно
# там, где от строки требуется доверие директора.
_RO_COUNT = {1: "una", 2: "două", 3: "trei", 4: "patru", 5: "cinci"}


def uq_event_text(level: str, gone: list[str], rows_n: int) -> str:
    """Строка ЛЕТОПИСИ о состоянии страховки — одна на все три исхода.

    ⚠️ Летопись режет текст по `EVENT_TEXT_MAX` и хранит его НАВСЕГДА:
    не влезшая строка обрезается посреди слова, переписать её нечем, а не влезал
    ровно самый тревожный случай — тот, где единственное важное слово
    («позвать поддержку») стояло в конце (08-16, измерено: 232 символа против
    потолка в 200). Поэтому строка собирается КОРОТКОЙ, а не режется: потолок
    поднимать нельзя (в колонке уже лежат строки старых клиник, и новый потолок
    к ним не относится), и полагаться на запас в пару символов тоже — имена
    проверок длиннее, чем кажется. Перечисление имён — единственная растущая
    часть, и она же первой уходит, когда строка перестаёт помещаться.
    ⭐ Здесь же и правило круга: сказано ровно то, что код ПРОВЕРИЛ. «Не
    прочитали состояние» — свой исход со своим текстом, а не «защиты нет».
    """
    tail = " — este nevoie de suport tehnic"
    if level == UQ_UNKNOWN:
        # ⛔ Ни одного утверждения о самих проверках: их состояние не прочитано.
        # Поддержка здесь не первый совет — причина бывает разовой (база занята,
        # диск), и следующий старт всё скажет сам.
        return ("Actualizare: starea verificărilor împotriva programărilor "
                "duble nu a putut fi citită — reporniți programul, iar dacă "
                "mesajul revine, este nevoie de suport tehnic")
    if level == UQ_BROKEN:
        n = len(gone)
        if n >= UQ_SLOT_COUNT:
            # Единственный случай, где имена не нужны: не хватает ВСЕХ.
            return (f"Actualizare: niciuna dintre cele {UQ_SLOT_COUNT} "
                    f"verificări împotriva programărilor duble nu este în "
                    f"evidență{tail}")
        head = (f"Actualizare: din {UQ_SLOT_COUNT} verificări împotriva "
                f"programărilor duble "
                f"{'lipsește' if n == 1 else 'lipsesc'} "
                f"{_RO_COUNT.get(n, n)}")
        full = f"{head}: {uq_gone_ro(gone)}{tail}"
        # ⚠️ Страховка на будущее, а не мёртвая ветка: четвёртая проверка или
        # более длинное имя однажды сделают перечисление длиннее потолка, и
        # тогда строка обязана остаться самодостаточной, а не обрезанной.
        return full if len(full) <= EVENT_TEXT_MAX else head + tail
    if not rows_n:
        # ⛔ Причина НЕ в данных: конфликтных часов код не нашёл ни одного (шаг
        # упёрся во что-то ещё — это в логе). Летопись хранит готовую строку
        # НАВСЕГДА, и «0 ore au mai multe programări active» осталось бы в ней
        # враньём про картотеку, которое нечем переписать.
        return ("Actualizare: protecția extinsă nu a putut fi aplicată — "
                "protecția de dinainte a rămas activă")
    what = f"{rows_n} ore au" if rows_n != 1 else "O oră are"
    return (f"Actualizare: {what} mai multe programări active — "
            f"protecția extinsă nu a putut fi aplicată")


# Строки самолечения и снятия метки — рядом с `uq_event_text` и по той же
# причине: у них общий потолок длины, и мерить их нужно всем списком сразу.
UQ_REPAIR_TEXT = {
    UQ_REPAIR_GONE: "Verificările împotriva programărilor duble lipseau din "
                    "evidență și au fost restabilite",
    UQ_REPAIR_NARROW: "Verificările împotriva programărilor duble erau mai "
                      "restrânse decât trebuie și au fost extinse",
}
UQ_CLEARED_TEXT = ("Orele duble au fost separate — protecția programărilor "
                   "este completă din nou")


def _uq_at_least(state: dict[str, str], name: str, act_sql: str) -> bool:
    """Индекс `name` в базе НЕ УЖЕ предиката act_sql.

    ⛔ Это и есть запрет «заменять существующий индекс на более узкий». Индекс,
    который в базе стоит с более широким набором статусов, СВОИМИ ДАННЫМИ
    доказал, что широкий предикат выполним; снести его и положить узкий значит
    ослабить работающую защиту. Так и случалось: v1.20.0 клала «три DROP, потом
    три CREATE», у клиники с переименованным врачом первые два индекса легли
    ШИРОКИМИ, а третий не лёг, — и одна ступень на все три увела бы такую базу
    с трёх широких на три узких (08-16, измерено «отбито» → «прошло»).
    """
    return name in state and _uq_statuses(state[name]) >= _uq_statuses(act_sql)


async def _apply_uq_indexes(plan: dict[str, str]) -> None:
    """Переложить слотовые индексы ПО ОДНОМУ, каждый под СВОИМ предикатом.

    ⛔ Отказ на одном не имеет права уносить остальные — ни соседний индекс, ни
    старт программы: каждый идёт своей парой DROP+CREATE и своим try. Сказать,
    что в итоге лежит в базе, — не наше дело: базу спрашивает
    `_slot_guard_verdict`, и только её ответ считается правдой.
    """
    for name, act_sql in plan.items():
        steps = _uq_slot_sql(act_sql, (name,))
        try:
            if IS_SQLITE:
                for sql in steps:
                    await _CONN.execute(sql)
                await _CONN.commit()
            else:
                # одна транзакция на ПАРУ: DROP и CREATE неразделимы, иначе краш
                # между ними оставит базу без этой проверки слота
                async with POOL.acquire() as c, c.transaction():
                    for sql in steps:
                        await c.execute(sql)
        except Exception as e:  # noqa: BLE001 — соседей это не касается
            log.error("uq-индекс %s (%s) не лёг: %r", name, act_sql, e)


async def _slot_guard_apply(repair: str = "") -> None:
    """Положить страховочные индексы, не рискуя стартом программы.

    Предикат выбирается ЛЕСТНИЦЕЙ (_UQ_LADDER) и ПО КАЖДОМУ ИНДЕКСУ ОТДЕЛЬНО:
    берётся самая широкая ступень, под которой нет конфликтов ИМЕННО этого
    индекса. Ни одна не подходит → этот индекс не трогаем вовсе: у клиники
    старше v1.7.0 там работающие индексы с ещё более узким предикатом, и снести
    их значило бы снять защиту, которая была, — навсегда, потому что следующий
    старт повторит ту же неудачу.
    ⛔ И отдельно: индекс, который в базе УЖЕ не уже выбранной ступени, не
    трогается совсем (`_uq_at_least`). Одна ступень на все три уводила базу,
    пришедшую от v1.20.0 с двумя широкими индексами, на три узких.
    ⛔ Разводить или удалять визиты автоматически нельзя ни при каких условиях:
    это записи клиники, и решает, кого перенести, человек.
    """
    _SLOT_GUARD["ran"] = True
    try:
        was_pending = await get_meta(UQ_PENDING_KEY) is not None
    except Exception as e:  # noqa: BLE001 — база не отвечает; старт важнее
        log.error("метка %s не прочитана: %r", UQ_PENDING_KEY, e)
        was_pending = False
    # ⭐ Метка ставится ДО работы и снимается ПОСЛЕ подтверждённого успеха.
    # Тогда падение ГДЕ УГОДНО — включая отказ самого set_meta и убитый процесс
    # между DROP и CREATE — оставляет метку, и следующий старт всё доделает.
    # Обратный порядок оставлял бы базу без защиты и без единого следа об этом.
    try:
        await set_meta(UQ_PENDING_KEY, "1")
    except Exception as e:  # noqa: BLE001
        log.error("метка %s не поставлена: %r", UQ_PENDING_KEY, e)
    rows: list[dict] = []
    try:
        state = await _uq_index_state()
        choice: dict[str, str] = {}
        left = list(_UQ_SLOT)
        for i, step in enumerate(_UQ_LADDER):
            if not left:
                break                # всем троим ступень нашлась на верхних
            conflicts = await _slot_conflicts(step)
            if i == 0:
                # Директору показываем конфликты ШИРОКОЙ ступени: их разведение
                # возвращает полную защиту, и они включают в себя конфликты всех
                # ступеней ниже. Список того, что чинить, обязан быть один.
                rows = _slot_rows(conflicts)
            for name in list(left):
                if not conflicts.get(name):
                    choice[name] = step
                    left.remove(name)
        if left:
            # ⛔ Именно здесь НЕ делается DROP: выполнимость CREATE для этих
            # индексов не установлена ни на одной ступени, а DDL в SQLite идёт
            # вне транзакции — снесённое не вернётся до следующего удачного
            # старта. Соседей это не касается: они кладутся своим предикатом.
            log.error("не кладутся ни на одной ступени: %s (%d конфликтных "
                      "слотов) — прежние оставлены как есть", ", ".join(left),
                      len(rows))
        # ⭐ Уже правильные и уже более ШИРОКИЕ индексы не трогаем. DROP+CREATE —
        # это окно, в котором защиты нет; открывать его ради работы, которой не
        # требуется (а то и ради сужения), значит повторять риск впустую.
        plan = {name: act for name, act in choice.items()
                if not _uq_at_least(state, name, act)}
        if plan:
            await _apply_uq_indexes(plan)
    except Exception as e:  # noqa: BLE001 — этот шаг НИКОГДА не роняет старт
        log.exception("страховочные uq-индексы: шаг не выполнен (%r)", e)
    await _slot_guard_verdict(rows, was_pending, repair)


async def _slot_guard_verdict(rows: list[dict], was_pending: bool,
                              repair: str = "") -> None:
    """Сказать ПРАВДУ о том, что в итоге лежит в базе, — спросив базу.

    ⛔ Не «мы выполнили CREATE, значит защита есть»: отказ CREATE после DROP
    оставляет картотеку без индексов, и ровно в этом состоянии баннер обязан
    звать чинить немедленно, а не сообщать, что всё под контролем.
    ⛔ И обратное: «broken» — это ровно «такого-то индекса в базе НЕТ», а не
    «защиты нет». Кода, который проверил бы, что защиты нет, не существует и не
    может существовать: у базы версии ≤2 индекса uq_doctor_slot_id нет ПО
    ОПРЕДЕЛЕНИЮ, а два остальных при этом целы и работают. Летопись хранит
    готовую строку навсегда, поэтому она обязана называть проверенное — что
    стоит и чего не хватает, — а не выносить приговор всей страховке (08-16).
    ⛔ И третье, из того же правила: НЕ ПРОЧИТАЛИ состояние — это свой исход
    (UQ_UNKNOWN), а не «в базе нет ничего». Пустой словарь после неудачного
    чтения читался как «нет ни одной проверки», и директор получал самый
    страшный текст («тот же час можно занять дважды без предупреждения») на
    базе, где все три индекса целы и работают (08-16).
    """
    unknown = False
    try:
        state = await _uq_index_state()
    except Exception as e:  # noqa: BLE001 — не знаем состояния = говорим об этом
        log.error("состояние uq-индексов не прочитано: %r", e)
        state, unknown = {}, True
    # ⚠️ «Не прочитали» не имеет права стать и УСПЕХОМ: молчание тут значило бы
    # снятую метку и погашенный баннер — то же необоснованное утверждение,
    # только в обратную сторону. Условие оставлено явным намеренно, хотя пустое
    # состояние и так не совпадёт: правило важнее, чем сегодняшняя реализация
    # `_uq_matches`.
    if not unknown and not rows and _uq_matches(state, _ACT_SQL):
        await _slot_guard_clear(was_pending, repair)
        return
    gone = [] if unknown else _uq_gone(state)
    level = UQ_UNKNOWN if unknown else (UQ_BROKEN if gone else UQ_NARROW)
    _SLOT_GUARD.update(pending=True, level=level, rows=rows, gone=gone)
    if level == UQ_NARROW:
        log.error("полная защита слота не встала: конфликтных слотов %d", len(rows))
    elif level == UQ_BROKEN:
        log.error("СЛОТОВЫХ ИНДЕКСОВ НЕТ В БАЗЕ: %r (на месте: %r)",
                  gone, sorted(state))
    else:
        log.error("состояние слотовых индексов НЕИЗВЕСТНО: база не ответила")
    try:
        await set_meta(UQ_PENDING_KEY, f"{level}:{len(rows)}")
    except Exception as e:  # noqa: BLE001 — метка уже стоит с «1», это уточнение
        log.error("метка %s не уточнена: %r", UQ_PENDING_KEY, e)
    if was_pending:
        # ⚠️ Строка в ленту — ОДИН раз на одно вмешательство, как у auth_alert:
        # баннер висит и так, а перезапуски не должны пополнять летопись.
        return
    # Текст — в `uq_event_text`, одним куском на все исходы: он же и единственное
    # место, где видно, что строка обязана уместиться в потолок летописи.
    await log_clinic_event("uq_guard", uq_event_text(level, gone, len(rows)))


async def _slot_guard_clear(was_pending: bool, repair: str = "") -> None:
    """Широкие индексы легли и ПРОВЕРЕНЫ. Если метка стояла с прошлого старта —
    клиника развела записи руками, и страховка встала сама."""
    _SLOT_GUARD.update(pending=False, level="", rows=[], gone=[])
    try:
        await del_meta(UQ_PENDING_KEY)
    except Exception as e:  # noqa: BLE001 — метка переживёт до следующего старта
        log.error("метка %s не снята: %r", UQ_PENDING_KEY, e)
        return
    if repair:
        # Самолечение без метки (внешняя правка базы, подмена файла, чужая
        # копия). Баннера тут нет и не нужно: страховка уже на месте. Но СЛЕД
        # обязан быть — иначе картотека однажды осталась бы без главной защиты,
        # и об этом не узнал бы никто.
        # ⚠️ Событий ДВА, и путать их нельзя: «индексов не было» и «индексы были,
        # но уже ожидаемого». Разницу знает тот, кто читал состояние базы, —
        # поэтому она и приезжает сюда причиной, а не додумывается здесь. Летопись
        # хранит готовую строку навсегда, и одна на два события всегда врёт про
        # одно из них (08-16).
        log.warning("слотовые индексы восстановлены на старте (%s)", repair)
        await log_clinic_event("uq_guard", UQ_REPAIR_TEXT[repair])
        return
    if not was_pending:
        return                       # обычная миграция, рассказывать нечего
    log.warning("двойные брони разведены — полная защита слота восстановлена")
    await log_clinic_event("uq_guard", UQ_CLEARED_TEXT)


async def _slot_guard_startup() -> None:
    """Состояние страховки читается на КАЖДОМ старте, а не только по метке.

    ⭐ Метка — СЛЕД для баннера, а не единственное условие повтора. Пока
    уникальные индексы стояли в базовой схеме, у них было самолечение: `CREATE
    UNIQUE INDEX IF NOT EXISTS` шёл при каждом старте и возвращал пропавшее. У
    единственного владельца этого нет — и база версии 4 без индексов и без метки
    стартовала бы МОЛЧА: ни баннера, ни следа, а слот не стережёт никто.
    Цена — один запрос к sqlite_master / pg_indexes (на 60 000 визитов ~0.03 с).
    """
    if _SLOT_GUARD["ran"]:
        return                       # шаг 4 уже отработал в этом запуске
    if await get_meta(UQ_PENDING_KEY) is not None:
        # Метка с прошлого старта: клиника могла развести записи руками, и тогда
        # широкие индексы встанут сами.
        await _slot_guard_apply()
        return
    try:
        state = await _uq_index_state()
    except Exception as e:  # noqa: BLE001 — состояние не прочиталось; старт важнее
        log.error("состояние uq-индексов на старте не прочитано: %r", e)
        return
    if _uq_matches(state, _ACT_SQL):
        return                       # всё на месте — обычный старт
    # ⚠️ Причина едет ОТСЮДА: только здесь ещё видно, чего не хватало ДО работы.
    # После _slot_guard_apply состояние уже другое, и различить «пропали» и
    # «были уже ожидаемого» будет нечем — а летопись пишет строку навсегда.
    why = UQ_REPAIR_GONE if _uq_gone(state) else UQ_REPAIR_NARROW
    log.error("слотовые индексы не на месте (%r, %s) — восстанавливаю",
              sorted(state), why)
    await _slot_guard_apply(repair=why)


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
        if v == UQ_GUARD_STEP:
            # ⛔ Единственный шаг, который НЕ имеет права уронить старт: он про
            # страховочный индекс, а не про данные, и расширение предиката
            # упирается в живые записи клиники. Упавший — оставлял бы версию
            # схемы прежней, то есть падал бы при КАЖДОМ запуске: у клиники это
            # «после обновления программа не открывается» (08-16).
            await _slot_guard_apply()
        # ⚠️ Список шага исполняется ВСЕГДА, в том числе у UQ_GUARD_STEP (там он
        # сегодня пуст). Пропустить его значило бы завести МЁРТВЫЙ список:
        # дописанный туда через месяц оператор молча не выполнился бы, а версия
        # схемы записалась бы как выполненная — ровно то, ради чего выше стоит
        # `raise RuntimeError('missing migration step')`. Строгость тут своя и
        # правильная: этот список меняет схему или данные, и падение уместно.
        if steps[v]:
            if IS_SQLITE:
                for sql in steps[v]:
                    await _CONN.execute(sql)
                await _CONN.commit()
            else:
                # один шаг = одна транзакция: половина применённого шага хуже
                # неприменённого — версия схемы описывала бы не то состояние
                async with POOL.acquire() as c, c.transaction():
                    for sql in steps[v]:
                        await c.execute(sql)
        await _set_schema_version(v)
    log.warning("DB migrated %s -> %s", have, SCHEMA_VERSION)


def _sqlite_driver(path: str):
    """(модуль DBAPI, функция открытия соединения) для картотеки на диске.

    Зашифрованную базу открывает sqlcipher3, обычную — штатный sqlite3, и
    решает это НАЛИЧИЕ ключа, а не настройка: флаг и файл однажды разошлись бы,
    и программа полезла бы читать шифр как открытый файл.

    ⚠️ Возвращается САМ МОДУЛЬ, а не только коннектор. У sqlcipher3 своя
    иерархия исключений и свой `Row`: `except sqlite3.OperationalError` ниже
    по коду перестал бы ловить ровно тогда, когда база зашифрована, — то есть
    у клиники и молча.
    ⚠️ `PRAGMA key` ставится ВНУТРИ коннектора, потому что она обязана быть
    первой операцией соединения; вынеси её наружу — и между открытием и ключом
    успеет пройти чужой запрос, а SQLCipher ответит «file is not a database».
    """
    # импорт здесь, а не в шапке: core.storage тянет за собой db, и на уровне
    # модуля это замкнуло бы круг
    from .core import dbkey

    key = dbkey.load()
    if key is None:
        if dbkey.enabled():
            # Ключ ЕСТЬ, но не читается: чужая учётка Windows или новый ПК.
            # Открывать базу штатным sqlite3 нельзя — он увидит мусор и решит,
            # что файл битый, а «битая база» толкает на восстановление из
            # бэкапа поверх целых данных. Падаем внятно.
            raise RuntimeError(
                "cheia bazei de date nu poate fi citită pe acest cont Windows "
                "— folosiți foaia de recuperare (Setări › Securitate)")
        import sqlite3
        return sqlite3, lambda: sqlite3.connect(path)

    import sqlcipher3.dbapi2 as sqlcipher
    pragma = dbkey.pragma_value(key)

    def _open():
        con = sqlcipher.connect(path)
        con.execute(f"PRAGMA key = {pragma}")
        return con

    return sqlcipher, _open


async def init(seed_rows: list | None = None) -> None:
    global POOL, _CONN, _SQ
    if IS_SQLITE:
        import aiosqlite
        path = DATABASE_URL.split("///", 1)[1]
        # ⚠️ Локальное имя `sqlite3` — не описка: ниже в этой же функции стоят
        # `except sqlite3.OperationalError`, и они обязаны смотреть на ТОТ
        # драйвер, которым база открыта. Назови переменную иначе — и следующий
        # написанный здесь except снова возьмёт стандартный модуль.
        sqlite3, connector = _sqlite_driver(path)
        _SQ = sqlite3
        _CONN = await aiosqlite.Connection(connector, 64)
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
    await _slot_guard_startup()
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
        # ⛔ по именам: позиционная распаковка через границу модуля уже
        # разъехалась однажды, молча (см. engine.build_seed_rows)
        await admin_add(**row)


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
    async with _BOOK_LOCK:
        if await patient_id_by_key(session_key) is None:
            # ⚠️ НОВОГО человека не заводим, пока слот не подтверждён: upsert
            # до проверки оставлял при отказе «интервал занят» карточку-сироту
            # без единого визита (всплывало в аудитах 08-04, починено 08-07).
            # Для СУЩЕСТВУЮЩЕГО порядок прежний: upsert обновляет имя/телефон
            # даже при отказе — пациент сам их продиктовал. Всё под ОДНИМ
            # замком: проверка вне его снова открыла бы окно для сироты.
            if await _conflicts(doctor_id, doctor, starts_at, duration_min):
                return None
        pid = await _upsert_patient(session_key, name, phone, lang, birth_year)
        return await _book_locked(pid, service, doctor, starts_at, source,
                                  doctor_id, service_id, duration_min)


async def _book(pid: int, service: str, doctor: str, starts_at: datetime,
                source: str, doctor_id: str | None, service_id: str | None,
                duration_min: int) -> int | str | None:
    """Вставка визита пациенту, который УЖЕ известен по id. Контракт возврата
    тот же, что у create_appointment (id / None / 'dup')."""
    async with _BOOK_LOCK:
        return await _book_locked(pid, service, doctor, starts_at, source,
                                  doctor_id, service_id, duration_min)


async def _book_locked(pid: int, service: str, doctor: str, starts_at: datetime,
                       source: str, doctor_id: str | None,
                       service_id: str | None,
                       duration_min: int) -> int | str | None:
    """Тело брони. Звать ТОЛЬКО под _BOOK_LOCK: asyncio.Lock не реентерабелен,
    и create_appointment, которому замок нужен раньше (проверка до создания
    пациента), иначе повис бы на самом себе."""
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
        except _SQ.IntegrityError as e:
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


async def _patient_ids_by_digits(digits: str) -> list[int]:
    """Пациенты, чей телефон совпадает ПО ЦИФРАМ — независимо от того, каким
    путём человек заведён (tg:… из бота, manual:… с рецепции). Телефон не
    ключ: семья делит номер, поэтому список, а решает вызывающий. Фильтр в
    Python, не в SQL: у SQLite нет regexp, а пациентов у клиники тысячи, не
    миллионы."""
    rows = await _fetch(
        "SELECT id, phone FROM patients WHERE phone IS NOT NULL",
        "SELECT id, phone FROM patients WHERE phone IS NOT NULL")
    return [r["id"] for r in rows
            if "".join(ch for ch in (r["phone"] or "") if ch.isdigit()) == digits]


async def patient_name_by_phone(phone: str) -> str | None:
    """Имя ЕДИНСТВЕННОГО пациента с этим номером. None — ноль или несколько.

    Нужна журналу, чтобы предупредить регистратуру: визит ляжет в чужую
    карточку (08-10). Семейный номер — норма, ребёнка записывают на телефон
    родителя, и `admin_add` в этом случае пишет визит РОДИТЕЛЮ, молча выбрасывая
    набранное имя. Запретить нельзя — по телефону записывают десятки раз в день;
    значит надо сказать, в чью карточку легло."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    ids = await _patient_ids_by_digits(digits)
    if len(ids) != 1:
        return None
    rows = await _fetch("SELECT name FROM patients WHERE id = $1",
                        "SELECT name FROM patients WHERE id = ?", ids[0])
    return rows[0]["name"] if rows else None


async def admin_add(
    name: str, phone: str, service: str, doctor: str, starts_at: datetime,
    birth_year: int | None = None, birth_date: str | None = None,
    doctor_id: str | None = None, service_id: str | None = None,
    duration_min: int = 60,
) -> int | str | None:
    """Ручная запись из журнала клиники. Пациент дедуплицируется по телефону."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    # Пациента ищем по НОМЕРУ среди существующих, а не по ключу manual:<цифры>
    # (08-07): у пациента из Telegram ключ tg:…, и путь по ключу заводил
    # карточку-двойника — визит задним числом уезжал не тому человеку.
    # Ровно одно совпадение цифр → пишем визит по id; попутно это перестало
    # переименовывать существующего («Ion P.» из формы журнала больше не
    # затирает «Ion Popescu» в фише). Ноль совпадений → новый manual-пациент,
    # как раньше. Несколько (семейный номер) → прежняя склейка по ключу:
    # выбрать «правильного» из двоих тут не из чего.
    ids = await _patient_ids_by_digits(digits)
    existing_name, has_bd = None, False
    if len(ids) == 1:
        pid = ids[0]
        rows_p = await _fetch(
            "SELECT name, birth_date FROM patients WHERE id = $1",
            "SELECT name, birth_date FROM patients WHERE id = ?", pid)
        if rows_p:
            existing_name = rows_p[0]["name"]
            has_bd = bool(rows_p[0]["birth_date"])
        r = await _book(pid, service, doctor, starts_at, "manual",
                        doctor_id, service_id, duration_min)
    else:
        r = await create_appointment(
            f"manual:{digits}", name, phone, "ro", service, doctor, starts_at,
            source="manual", birth_year=birth_year,
            doctor_id=doctor_id, service_id=service_id, duration_min=duration_min,
        )
        pid = await patient_id_by_key(f"manual:{digits}")
    # дата рождения — тем же правилом, что год в upsert: новое значение, если
    # оно задано. Пишем и при dup/conflict — пациент уже существует, а дату
    # регистратура ввела про него же. В ветке по id upsert не выполнялся,
    # поэтому одиночный год (устаревшая вкладка) дописывается здесь же
    # ⛔ Дату рождения НЕ писать поверх чужой карточки (08-10, находка аудита).
    # Семейный номер — норма: ребёнка записывают на телефон родителя. Ветка
    # `len(ids) == 1` находит родителя по цифрам и пишет визит ему, а дальше
    # сюда приходила дата рождения РЕБЁНКА и затирала родительскую — без
    # истории и без предупреждения, зелёным баннером «ok». Год рождения уже
    # был осторожнее (`elif ... len(ids) == 1`), у полной даты этой оглядки не
    # было. Теперь дату принимает только карточка, у которой её ещё нет, либо
    # та, чьё имя совпало с набранным.
    same_person = (not name) or not existing_name or \
        existing_name.strip().lower() == name.strip().lower()
    if pid is not None:
        if birth_date and (same_person or not has_bd):
            await _execute(
                "UPDATE patients SET birth_date = $2, birth_year = $3 WHERE id = $1",
                "UPDATE patients SET birth_date = ?, birth_year = ? WHERE id = ?",
                *((pid, birth_date, birth_year) if not IS_SQLITE
                  else (birth_date, birth_year, pid)))
        elif birth_year and len(ids) == 1:
            await set_birth_year(pid, birth_year)
    return r


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


async def _patient_busy_at(pid: int, starts_at: datetime,
                           exclude_id: int | None = None) -> bool:
    """Есть ли у пациента активная запись РОВНО на этот старт — то же, что
    стережёт uq_patient_slot, но ответом, а не исключением. Вызывать под
    _BOOK_LOCK. Пересечения по длительности здесь намеренно не ищем: индекс их
    тоже не запрещает, а регистратура ставит пациента к двум врачам подряд.

    ⚠️ `exclude_id` обязателен для ПЕРЕНОСА: визит, переезжающий к другому врачу
    на тот же час, находит сам себя и без него получил бы «у пациента уже есть
    запись на это время» — то есть отказ из-за себя самого."""
    rows = await _fetch(
        f"""SELECT id FROM appointments
           WHERE patient_id = $1 AND starts_at = $2 AND status IN {_ACT_SQL}
           LIMIT 2""",
        f"""SELECT id FROM appointments
           WHERE patient_id = ? AND starts_at = ? AND status IN {_ACT_SQL}
           LIMIT 2""",
        pid, (starts_at if not IS_SQLITE else _iso(starts_at)),
    )
    return any(r["id"] != exclude_id for r in rows)


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
        except _SQ.IntegrityError:
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
    # has_rec — «консультация записана»: не дата, в _DT_COLS ему не место
    return await _fetch(
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id, a.service_id,
                  a.starts_at, a.duration_min, a.status, a.source,
                  a.reminded_day, a.comment, a.waiting_at, a.arrived_at,
                  p.name, p.phone, p.birth_year,
                  (vr.id IS NOT NULL) AS has_rec
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
                LEFT JOIN visit_records vr ON vr.appointment_id = a.id
           WHERE a.starts_at >= $1 AND a.starts_at < $2
           ORDER BY a.starts_at, a.doctor""",
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id, a.service_id,
                  a.starts_at, a.duration_min, a.status, a.source,
                  a.reminded_day, a.comment, a.waiting_at, a.arrived_at,
                  p.name, p.phone, p.birth_year,
                  (vr.id IS NOT NULL) AS has_rec
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
                LEFT JOIN visit_records vr ON vr.appointment_id = a.id
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
    """Незавершённые пункты плана — по ним пациент считается «в лечении».

    ⚠️ Перечисляем активные статусы ПОИМЁННО, а не «<> finalizat»: отказанная
    позиция закрыта, и пациент с одним отказом не находится в лечении."""
    sql = ("SELECT patient_id, COUNT(*) AS n FROM plan_items "
           "WHERE status IN ('planificat', 'in_lucru') GROUP BY patient_id")
    return await _fetch(sql, sql)


async def patients_debt() -> dict:
    """Долг каждого пациента: финализированный план − оплачено. Минус = аванс.

    Та же формула, что в `patient_finance`, но на всю картотеку двумя запросами
    вместо двух НА ПАЦИЕНТА: список зовёт это один раз на страницу.
    Полного внешнего соединения в SQLite нет, поэтому две выборки сводятся в
    Python — заодно не приходится писать двум диалектам разный SQL.
    """
    chg = ("SELECT patient_id, COALESCE(SUM(price_mdl), 0) AS n FROM plan_items "
           "WHERE status = 'finalizat' GROUP BY patient_id")
    pay = ("SELECT patient_id, COALESCE(SUM(amount_mdl), 0) AS n FROM payments "
           "GROUP BY patient_id")
    out: dict[int, int] = {}
    for r in await _fetch(chg, chg):
        out[r["patient_id"]] = int(r["n"] or 0)
    for r in await _fetch(pay, pay):
        out[r["patient_id"]] = out.get(r["patient_id"], 0) - int(r["n"] or 0)
    return out


async def payments_day(start: datetime, end: datetime) -> list:
    """Платежи за окно, с именем пациента — для печатного отчёта кассы.

    ⚠️ `at` возвращается в UTC, как все даты (`_DT_COLS`). Печать читает
    человек, поэтому переводить в `eng.TZ` обязан вызывающий: иначе платёж,
    принятый в 09:00, встанет в отчёт как 06:00 — дата верна, час чужой.
    """
    sql = ("SELECT pm.amount_mdl, pm.method, pm.at, pm.note, pm.taken_by, "
           "       pm.patient_id, p.name AS patient "
           "FROM payments pm LEFT JOIN patients p ON p.id = pm.patient_id "
           "WHERE pm.at >= {0} AND pm.at < {1} ORDER BY pm.at")
    return await _fetch(
        sql.format("$1", "$2"), sql.format("?", "?"),
        *((start, end) if not IS_SQLITE else (_iso(start), _iso(end))),
    )


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


async def set_birth_year(pid: int, year: int | None) -> None:
    """Синк года из birth_date: возраст в поиске/сетке считается по birth_year.
    None стирает год — так очищенная дата рождения забирает с собой и возраст."""
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


# ПОТОЛОК текста события. ⚠️ Обрезка ЖЁСТКАЯ и посреди слова, а строка хранится
# навсегда — переписать её нечем. ⛔ Поднимать это число «чтобы влезло» нельзя:
# в колонке уже лежат строки, обрезанные прежним потолком, и новый к ним не
# относится — картотека станет разноформатной, а обрезанное не вернётся. Строку
# сокращают, а не потолок поднимают (08-16, `uq_event_text`).
EVENT_TEXT_MAX = 200


async def log_event(patient_id: int | None, kind: str, text: str, *,
                    actor: str = "", tooth: int | None = None) -> None:
    """Событие карты пациента. Никогда не роняет основную операцию: журнал —
    это летопись, а не транзакция; потерянная строка хуже, чем упавшая запись
    к врачу, только в одном случае — если из-за неё не состоялась сама запись.

    ⚠️ Хранится ГОТОВАЯ строка, и переписывать её потом нельзя: летопись
    отвечает на вопрос «кто что сделал», а не «как это выглядит сегодня».
    Отсюда правило для вызывающих: внутренний код (`in_lucru`, `noshow`,
    `obturatie`) разворачивается в СЛОВО здесь и сейчас — ту же строку читает
    и лента фиши, и выгрузка по 195-му, где она обязана быть «в понятной
    форме». Словари слов лежат по месту их смысла (`core.layout.STATUS_LABEL`,
    `fisa043.PLAN_RO`, `teeth_svg.STATE_RO`) и берутся ОТЛОЖЕННЫМ импортом:
    db лежит ниже слоя интерфейса, и на уровне модуля это замкнуло бы круг.
    """
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
            *((patient_id, actor, kind, tooth, text[:EVENT_TEXT_MAX])
              if not IS_SQLITE else
              (patient_id, _utcnow_iso(), actor, kind, tooth,
               text[:EVENT_TEXT_MAX])),
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
            *((actor, kind, text[:EVENT_TEXT_MAX]) if not IS_SQLITE
              else (_utcnow_iso(), actor, kind, text[:EVENT_TEXT_MAX])),
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
    # Летопись читает человек: час обязан быть часом КЛИНИКИ, как в живом пути
    # (_log_booking печатает дату, построенную в eng.TZ), а _fetch отдаёт
    # starts_at в UTC — без перевода перенесённый визит на 09:00 записался бы
    # «06:00» навсегда, текст события строка и не пересчитывается.
    # Импорт отложенный: engine импортирует db, на уровне модуля был бы круг.
    from . import engine as eng
    n = 0
    for r in rows:
        when = r["starts_at"]
        txt = f"Programare: {r['service']} · {r['doctor']}"
        if hasattr(when, "strftime"):
            if getattr(when, "tzinfo", None) is not None:
                # переводить только значения С поясом: astimezone на наивном
                # подставил бы пояс машины и мог сдвинуть день
                when = when.astimezone(eng.TZ)
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
        """SELECT tooth, state, note, doctor, surfaces, updated_at
           FROM teeth WHERE patient_id = $1""",
        """SELECT tooth, state, note, doctor, surfaces, updated_at
           FROM teeth WHERE patient_id = ?""",
        pid)
    return {r["tooth"]: r for r in rows}


async def set_tooth(pid: int, tooth: int, state: str, note: str,
                    doctor: str = "", surfaces: str = "") -> None:
    """'ok' без заметки и без врача = зуб здоров → строка удаляется (карта sparse).
    doctor — СНАПШОТ имени на момент записи, как в plan_items: переименование
    врача не должно переписывать историю зуба.
    surfaces — буквы поверхностей одной строкой («MOD»); проверяет маршрут."""
    # состояние в летопись — СЛОВОМ (см. log_event): «obturatie» и «lipsa» это
    # ключи одонтограммы, а строку читают регистратура и пациент в выгрузке
    from .teeth_svg import STATE_RO
    if state == "ok" and not note and not doctor:
        await _execute("DELETE FROM teeth WHERE patient_id = $1 AND tooth = $2",
                       "DELETE FROM teeth WHERE patient_id = ? AND tooth = ?", pid, tooth)
        await log_event(pid, "tooth", f"Dinte {tooth}: {STATE_RO['ok']}",
                        tooth=tooth)
        return
    pg = """INSERT INTO teeth(patient_id, tooth, state, note, doctor, surfaces,
                              updated_at)
            VALUES($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (patient_id, tooth) DO UPDATE
              SET state = EXCLUDED.state, note = EXCLUDED.note,
                  doctor = EXCLUDED.doctor, surfaces = EXCLUDED.surfaces,
                  updated_at = now()"""
    lt = """INSERT INTO teeth(patient_id, tooth, state, note, doctor, surfaces,
                              updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(patient_id, tooth) DO UPDATE
              SET state = excluded.state, note = excluded.note,
                  doctor = excluded.doctor, surfaces = excluded.surfaces,
                  updated_at = excluded.updated_at"""
    await _execute(pg, lt,
                   *((pid, tooth, state, note, doctor, surfaces) if not IS_SQLITE
                     else (pid, tooth, state, note, doctor, surfaces,
                           _utcnow_iso())))
    txt = f"Dinte {tooth}: {STATE_RO.get(state, state)}"
    if surfaces:
        txt += f" ({surfaces})"
    if doctor:
        txt += f" · {doctor}"
    if note:
        txt += f" · {note}"
    await log_event(pid, "tooth", txt, tooth=tooth)


# ⭐ «Активная» позиция плана — это planificat|in_lucru, а НЕ «всё, что не
# finalizat». Пока статусов было три, две формулировки совпадали; с появлением
# ОТКАЗА (refuzat, ст.13(5) Legea 263/2005) вторая стала враньём: отказанная
# процедура навсегда осталась бы «в лечении» — в KPI фиши, в колонке списка и
# в сумме активного плана. Считать активность только через этот кортеж.
PLAN_ACTIVE = ("planificat", "in_lucru")
# закрытые: у них проставлен done_at и они не ждут работы
PLAN_CLOSED = ("finalizat", "refuzat")


async def plan_items(pid: int) -> list:
    return await _fetch(
        """SELECT id, tooth, procedure, doctor, status, price_mdl, due_date,
                  done_at, appointment_id, refuz_motiv
           FROM plan_items WHERE patient_id = $1 ORDER BY id""",
        """SELECT id, tooth, procedure, doctor, status, price_mdl, due_date,
                  done_at, appointment_id, refuz_motiv
           FROM plan_items WHERE patient_id = ? ORDER BY id""", pid)


async def plan_item_status(item_id: int, pid: int) -> str | None:
    """Текущий статус позиции — для проверки, что переход допустим. Стрелки
    статусов НАПРАВЛЕННЫЕ (см. _PLAN_EDGES в модуле пациентов), и охрана
    обязана смотреть на «откуда», а не только на «куда»."""
    return await _fetchval(
        "SELECT status FROM plan_items WHERE id = $1 AND patient_id = $2",
        "SELECT status FROM plan_items WHERE id = ? AND patient_id = ?",
        item_id, pid)


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


async def set_plan_status(item_id: int, pid: int, status: str,
                          appt_id: int | None = None, motiv: str = "") -> None:
    """appt_id — визит, НА котором позицию выполнили (страница консультации).
    Привязка живёт только у финализированной позиции: «Redeschide» означает
    «на самом деле не сделано», и ссылка на визит снимается вместе с done_at.

    ⚠️ `done_at` — дата ЗАКРЫТИЯ позиции, а не «выполнения»: её получает и
    отказ (refuzat). Иначе пришлось бы завести пятую колонку-дату ради того же
    смысла, а лист согласия и 043/e спрашивают у отказа ровно дату и причину.
    Возврат в работу (Redeschide / Reia) чистит и дату, и причину: позиция
    снова ждёт работы, и старая причина отказа врала бы о ней.
    """
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = $1 AND patient_id = $2",
                        "SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
                        item_id, pid)
    if rows:
        # причина отказа уходит в летопись ВМЕСТЕ с переходом: лента —
        # единственное место, где видно, кто и когда отказ оформил
        tail = f" ({motiv})" if status == "refuzat" and motiv else ""
        # статус позиции — СЛОВОМ (см. log_event): тем же словарём, каким его
        # называют бумажный бланк 043/e и выгрузка по 195-му
        from .modules.patients.fisa043 import PLAN_RO
        await log_event(pid, "plan_status",
                        f"Plan: {rows[0]['procedure']} › "
                        f"{PLAN_RO.get(status, status)}{tail}",
                        tooth=rows[0]["tooth"])
    if status in PLAN_CLOSED:
        # к визиту привязывается только ВЫПОЛНЕННОЕ: отказ ни на каком приёме
        # не «сделан», и appointment_id у него обязан остаться пустым
        appt = appt_id if status == "finalizat" else None
        why = motiv if status == "refuzat" else ""
        await _execute(
            """UPDATE plan_items SET status = $1, done_at = now(),
                  appointment_id = $4, refuz_motiv = $5
                WHERE id = $2 AND patient_id = $3""",
            """UPDATE plan_items SET status = ?, done_at = ?,
                  appointment_id = ?, refuz_motiv = ?
                WHERE id = ? AND patient_id = ?""",
            *((status, item_id, pid, appt, why) if not IS_SQLITE
              else (status, _utcnow_iso(), appt, why, item_id, pid)),
        )
    else:
        await _execute(
            """UPDATE plan_items SET status = $1, done_at = NULL,
                  appointment_id = NULL, refuz_motiv = ''
                WHERE id = $2 AND patient_id = $3""",
            """UPDATE plan_items SET status = ?, done_at = NULL,
                  appointment_id = NULL, refuz_motiv = ''
                WHERE id = ? AND patient_id = ?""",
            status, item_id, pid,
        )


async def delete_plan_item(item_id: int, pid: int) -> None:
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = $1 AND patient_id = $2",
                        "SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
                        item_id, pid)
    if rows:
        await log_event(pid, "plan_del", f"Plan: - {rows[0]['procedure']}",
                        tooth=rows[0]["tooth"])
    await _execute(
        "DELETE FROM plan_items WHERE id = $1 AND patient_id = $2",
        "DELETE FROM plan_items WHERE id = ? AND patient_id = ?", item_id, pid)


# ---------- дневник визита (consultația) ----------
# Запись приёма 1:1 к визиту: acuze / examen / diagnostic / tratament /
# recomandari — графы дневника формы 043/e. Кнопки удаления НЕТ намеренно:
# медзапись правится (updated_at + author), но не исчезает; обе версии
# события остаются в летописи.

VISIT_FIELDS = ("acuze", "examen", "diagnostic", "tratament", "recomandari")


async def appointment_brief(appt_id: int) -> dict | None:
    """Один визит с именем пациента — шапка страницы консультации.
    patient_id отсюда — источник истины «чей визит»: маршруты обязаны брать
    его из этой выборки, а не из формы."""
    rows = await _fetch(
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.starts_at,
                  a.duration_min, a.status, a.source, a.comment, p.name
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.id = $1""",
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.starts_at,
                  a.duration_min, a.status, a.source, a.comment, p.name
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.id = ?""", appt_id)
    return rows[0] if rows else None


async def visit_record(appt_id: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, appointment_id, patient_id, doctor, acuze, examen,
                  diagnostic, tratament, recomandari, author, created_at,
                  updated_at
           FROM visit_records WHERE appointment_id = $1""",
        """SELECT id, appointment_id, patient_id, doctor, acuze, examen,
                  diagnostic, tratament, recomandari, author, created_at,
                  updated_at
           FROM visit_records WHERE appointment_id = ?""", appt_id)
    return rows[0] if rows else None


async def save_visit_record(appt_id: int, pid: int, doctor: str,
                            fields: dict) -> str:
    """Upsert записи приёма; возвращает 'created' | 'updated'.
    author — последний редактировавший; кто вписал первым, видно в летописи."""
    vals = tuple((fields.get(k) or "").strip() for k in VISIT_FIELDS)
    actor = _actor_now()
    existing = await _fetchval(
        "SELECT id FROM visit_records WHERE appointment_id = $1",
        "SELECT id FROM visit_records WHERE appointment_id = ?", appt_id)
    result = "created" if existing is None else "updated"
    # один upsert, а не SELECT+ветка: два открытых окна консультации иначе
    # вставляют наперегонки, и второе падает на UNIQUE(appointment_id).
    # ON CONFLICT одинаков в PG и SQLite; created_at при обновлении не трогаем
    # (в SET его нет), гонка может лишь перепутать глагол в летописи
    await _execute(
        """INSERT INTO visit_records(appointment_id, patient_id, doctor,
             acuze, examen, diagnostic, tratament, recomandari, author)
           VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT(appointment_id) DO UPDATE SET
             doctor = EXCLUDED.doctor, acuze = EXCLUDED.acuze,
             examen = EXCLUDED.examen, diagnostic = EXCLUDED.diagnostic,
             tratament = EXCLUDED.tratament,
             recomandari = EXCLUDED.recomandari,
             author = EXCLUDED.author, updated_at = now()""",
        """INSERT INTO visit_records(appointment_id, patient_id, doctor,
             acuze, examen, diagnostic, tratament, recomandari, author,
             created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(appointment_id) DO UPDATE SET
             doctor = excluded.doctor, acuze = excluded.acuze,
             examen = excluded.examen, diagnostic = excluded.diagnostic,
             tratament = excluded.tratament,
             recomandari = excluded.recomandari,
             author = excluded.author, updated_at = ?""",
        *((appt_id, pid, doctor, *vals, actor) if not IS_SQLITE
          else (appt_id, pid, doctor, *vals, actor, _utcnow_iso(),
                _utcnow_iso())),
    )
    # в летопись — самое информативное из заполненного: диагноз, лечение, жалобы
    snippet = next((v for v in (vals[2], vals[3], vals[0]) if v), "")
    verb = "Consultație" if result == "created" else "Consultație actualizată"
    await log_event(pid, "consult", f"{verb}: {snippet[:120] or '—'}")
    return result


# ---------- анамнез (опросник пациента) ----------
# Один на пациента, правится, не удаляется — как дневник визита. Это МЕДДАННЫЕ:
# держит фишу от физического стирания и переживает обезличивание под номером
# фиши (см. erasure_kind / anonymize_patient).

ANAMNEZA_FIELDS = ("boli", "medicamente", "alergii", "anestezie")


async def set_patient_lang(pid: int, lang: str) -> None:
    """Язык пациента — отдельным маршрутом, а НЕ через PATIENT_FIELDS:
    там пустое поле превращается в NULL, а колонка NOT NULL DEFAULT 'ro'."""
    if lang not in ("ro", "ru"):
        return
    await _execute("UPDATE patients SET lang = $2 WHERE id = $1",
                   "UPDATE patients SET lang = ? WHERE id = ?",
                   *((pid, lang) if not IS_SQLITE else (lang, pid)))


async def anamneza(pid: int) -> dict | None:
    rows = await _fetch(
        """SELECT patient_id, flags, boli, medicamente, alergii, anestezie,
                  author, created_at, updated_at
           FROM anamneza WHERE patient_id = $1""",
        """SELECT patient_id, flags, boli, medicamente, alergii, anestezie,
                  author, created_at, updated_at
           FROM anamneza WHERE patient_id = ?""", pid)
    return rows[0] if rows else None


async def save_anamneza(pid: int, flags: str, fields: dict) -> str:
    """Upsert опросника; возвращает 'created' | 'updated'."""
    vals = tuple((fields.get(k) or "").strip()[:500] for k in ANAMNEZA_FIELDS)
    actor = _actor_now()
    existed = await _fetchval(
        "SELECT 1 FROM anamneza WHERE patient_id = $1",
        "SELECT 1 FROM anamneza WHERE patient_id = ?", pid)
    await _execute(
        """INSERT INTO anamneza(patient_id, flags, boli, medicamente, alergii,
             anestezie, author)
           VALUES($1, $2, $3, $4, $5, $6, $7)
           ON CONFLICT(patient_id) DO UPDATE SET
             flags = EXCLUDED.flags, boli = EXCLUDED.boli,
             medicamente = EXCLUDED.medicamente, alergii = EXCLUDED.alergii,
             anestezie = EXCLUDED.anestezie, author = EXCLUDED.author,
             updated_at = now()""",
        """INSERT INTO anamneza(patient_id, flags, boli, medicamente, alergii,
             anestezie, author, created_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(patient_id) DO UPDATE SET
             flags = excluded.flags, boli = excluded.boli,
             medicamente = excluded.medicamente, alergii = excluded.alergii,
             anestezie = excluded.anestezie, author = excluded.author,
             updated_at = ?""",
        *((pid, flags, *vals, actor) if not IS_SQLITE
          else (pid, flags, *vals, actor, _utcnow_iso(), _utcnow_iso())),
    )
    await log_event(pid, "anamneza",
                    "Anamneza actualizată" if existed else "Anamneza completată")
    return "updated" if existed else "created"


async def visit_records_map(pid: int) -> dict[int, dict]:
    """appointment_id → запись приёма: фиша красит историю визитов одним
    запросом, а не по одному на строку."""
    rows = await _fetch(
        """SELECT appointment_id, doctor, acuze, examen, diagnostic, tratament,
                  recomandari, author, created_at, updated_at
           FROM visit_records WHERE patient_id = $1""",
        """SELECT appointment_id, doctor, acuze, examen, diagnostic, tratament,
                  recomandari, author, created_at, updated_at
           FROM visit_records WHERE patient_id = ?""", pid)
    return {r["appointment_id"]: r for r in rows}


async def patient_visit_records(pid: int) -> list:
    """Записи приёмов с датой и услугой визита — для выгрузки данных пациента.

    ⚠️ `a.status` отдаётся вместе с записью и НЕ фильтруется здесь: копия по
    195-му обязана содержать всё, что клиника о пациенте хранит. Отсеивает
    отменённое и неявки печатный бланк 043/e — там строка читается как
    проведённое лечение (см. fisa043.render).
    """
    return await _fetch(
        """SELECT a.starts_at, a.service, a.status, v.doctor, v.acuze, v.examen,
                  v.diagnostic, v.tratament, v.recomandari, v.author,
                  v.created_at, v.updated_at
           FROM visit_records v JOIN appointments a ON a.id = v.appointment_id
           WHERE v.patient_id = $1 ORDER BY a.starts_at DESC""",
        """SELECT a.starts_at, a.service, a.status, v.doctor, v.acuze, v.examen,
                  v.diagnostic, v.tratament, v.recomandari, v.author,
                  v.created_at, v.updated_at
           FROM visit_records v JOIN appointments a ON a.id = v.appointment_id
           WHERE v.patient_id = ? ORDER BY a.starts_at DESC""", pid)


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

# ---------- платежи (08-07, модуль финансов, шаг 1) ----------
# Модель по решению Олега: долг = завершённые позиции плана с ценой минус
# платежи; платёж — сумма НА ПАЦИЕНТА, без привязки к конкретной процедуре
# (наличные так не делятся). Переплата = аванс. Записывает рецепция (деньги
# физически берёт она), удаляет только директор, всё поимённо в летописи.

PAY_METHODS = ("numerar", "card", "transfer")


async def payments(pid: int) -> list:
    return await _fetch(
        """SELECT id, amount_mdl, method, note, taken_by, at
           FROM payments WHERE patient_id = $1 ORDER BY at DESC, id DESC""",
        """SELECT id, amount_mdl, method, note, taken_by, at
           FROM payments WHERE patient_id = ? ORDER BY at DESC, id DESC""", pid)


async def add_payment(pid: int, amount: int, method: str, note: str) -> None:
    actor = _actor_now()
    await _execute(
        """INSERT INTO payments(patient_id, amount_mdl, method, note, taken_by)
           VALUES($1, $2, $3, $4, $5)""",
        """INSERT INTO payments(patient_id, amount_mdl, method, note, taken_by, at)
           VALUES(?, ?, ?, ?, ?, ?)""",
        *((pid, amount, method, note, actor) if not IS_SQLITE
          else (pid, amount, method, note, actor, _utcnow_iso())),
    )
    verb = "Plată" if amount > 0 else "Restituire"
    await log_event(pid, "pay", f"{verb} {abs(amount)} MDL ({method})"
                    + (f" — {note}" if note else ""))


async def get_payment(pay_id: int, pid: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, amount_mdl, method, note FROM payments
           WHERE id = $1 AND patient_id = $2""",
        """SELECT id, amount_mdl, method, note FROM payments
           WHERE id = ? AND patient_id = ?""", pay_id, pid)
    return rows[0] if rows else None


async def delete_payment(pay_id: int, pid: int) -> bool:
    """Удаление платежа — исправление ошибки ввода, не бухгалтерская операция.
    Право на него только у директора (маршрут), а след остаётся в летописи."""
    p = await get_payment(pay_id, pid)
    if p is None:
        return False
    await log_event(pid, "pay_del",
                    f"Plată ștearsă: {p['amount_mdl']} MDL ({p['method']})")
    await _execute("DELETE FROM payments WHERE id = $1 AND patient_id = $2",
                   "DELETE FROM payments WHERE id = ? AND patient_id = ?",
                   pay_id, pid)
    return True


async def patient_finance(pid: int) -> dict:
    """Начислено (завершённые позиции плана с ценой) и оплачено. Долг считает
    вызывающий: charged − paid; минус = аванс."""
    charged = await _fetchval(
        """SELECT COALESCE(SUM(price_mdl), 0) FROM plan_items
           WHERE patient_id = $1 AND status = 'finalizat'""",
        """SELECT COALESCE(SUM(price_mdl), 0) FROM plan_items
           WHERE patient_id = ? AND status = 'finalizat'""", pid)
    paid = await _fetchval(
        "SELECT COALESCE(SUM(amount_mdl), 0) FROM payments WHERE patient_id = $1",
        "SELECT COALESCE(SUM(amount_mdl), 0) FROM payments WHERE patient_id = ?",
        pid)
    return {"charged": int(charged or 0), "paid": int(paid or 0)}


async def payments_range(start: datetime, end: datetime) -> list:
    """Платежи за окно времени — для «Încasări» в статистике."""
    return await _fetch(
        """SELECT amount_mdl, method, at FROM payments
           WHERE at >= $1 AND at < $2""",
        """SELECT amount_mdl, method, at FROM payments
           WHERE at >= ? AND at < ?""",
        *((start, end) if not IS_SQLITE else (_iso(start), _iso(end))),
    )


async def erasure_kind(pid: int) -> str:
    """'delete' — можно физически, 'anon' — только обезличивание.

    Лечением считается: запись о зубе, план, документ, визит со статусом
    done/arrived ЛИБО подтверждённый визит в прошлом (раз не отменён и не
    отмечен «не пришёл» — приём, скорее всего, состоялся, и вычеркнуть его —
    значит переписать медицинскую историю задним числом).
    ПЛАТЁЖ тоже держит фишу от физического удаления: деньги — финансовый след
    клиники, и вычеркнуть его — значит переписать кассу задним числом.
    """
    async def _n(pg: str, lt: str, *a) -> int:
        return int(await _fetchval(pg, lt, *a) or 0)

    pays = await _n("SELECT COUNT(*) FROM payments WHERE patient_id = $1",
                    "SELECT COUNT(*) FROM payments WHERE patient_id = ?", pid)
    teeth = await _n("SELECT COUNT(*) FROM teeth WHERE patient_id = $1",
                     "SELECT COUNT(*) FROM teeth WHERE patient_id = ?", pid)
    plan = await _n("SELECT COUNT(*) FROM plan_items WHERE patient_id = $1",
                    "SELECT COUNT(*) FROM plan_items WHERE patient_id = ?", pid)
    docs = await _n("SELECT COUNT(*) FROM documents WHERE patient_id = $1",
                    "SELECT COUNT(*) FROM documents WHERE patient_id = ?", pid)
    # запись приёма — лечение по определению, даже если визит формально
    # будущий/отменённый: врач уже вписал клинический текст
    consult = await _n("SELECT COUNT(*) FROM visit_records WHERE patient_id = $1",
                       "SELECT COUNT(*) FROM visit_records WHERE patient_id = ?",
                       pid)
    # анамнез — медицинская запись: фиша с одним опросником обезличивается,
    # а не стирается физически
    anam = await _n("SELECT COUNT(*) FROM anamneza WHERE patient_id = $1",
                    "SELECT COUNT(*) FROM anamneza WHERE patient_id = ?", pid)
    now = datetime.now(timezone.utc)
    happened = await _n(
        """SELECT COUNT(*) FROM appointments WHERE patient_id = $1
           AND (status IN ('done','arrived','waiting')
                OR (status = 'confirmed' AND starts_at < $2))""",
        """SELECT COUNT(*) FROM appointments WHERE patient_id = ?
           AND (status IN ('done','arrived','waiting')
                OR (status = 'confirmed' AND starts_at < ?))""",
        *((pid, now) if not IS_SQLITE else (pid, _iso(now))))
    return ("anon" if (teeth or plan or docs or happened or pays or consult
                       or anam) else "delete")


async def delete_patient_fully(pid: int) -> None:
    """Физическое удаление: строка пациента и ВСЁ, что на неё ссылается.

    Порядок — дети раньше родителя: в PG внешние ключи иначе откажут, а SQLite
    молча оставил бы сирот, которых потом нашла бы только выгрузка чужого id.
    Файлы документов на диске удаляет ВЫЗЫВАЮЩИЙ (маршрут): db не знает про
    раскладку файлов, и это его единственная граница.
    """
    for pg, lt in (
        ("DELETE FROM payments WHERE patient_id = $1",
         "DELETE FROM payments WHERE patient_id = ?"),
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
        ("DELETE FROM anamneza WHERE patient_id = $1",
         "DELETE FROM anamneza WHERE patient_id = ?"),
        # дневники приёмов раньше визитов: FK на appointments
        ("DELETE FROM visit_records WHERE patient_id = $1",
         "DELETE FROM visit_records WHERE patient_id = ?"),
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
    Дневник приёма (visit_records) НЕ трогаем: acuze/diagnostic/tratament —
    та самая клиническая запись, ради которой фиша и хранится под номером.
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
    # платежи остаются (касса клиники под номером фиши), но заметка платежа —
    # свободный текст рецепции, то есть потенциально личность: стираем
    await _execute("UPDATE payments SET note = '' WHERE patient_id = $1",
                   "UPDATE payments SET note = '' WHERE patient_id = ?", pid)
    await _execute(
        "UPDATE appointments SET comment = '' WHERE patient_id = $1",
        "UPDATE appointments SET comment = '' WHERE patient_id = ?", pid)
    # летопись — тот же свободный текст ЭХОМ: log_event дублирует туда заметку
    # платежа («Plată 500 MDL — transfer de la fratele …») и имя загруженного
    # файла. Строки пациента удаляются целиком, как в delete_patient_fully;
    # платёжные данные живут в payments и остаются. Событие «erase» пишет
    # вызывающий маршрут ПОСЛЕ — след стирания в летописи сохраняется.
    await _execute("DELETE FROM activity WHERE patient_id = $1",
                   "DELETE FROM activity WHERE patient_id = ?", pid)
    # имя документа дал человек («radiografie-popescu.png») — это личность;
    # сам снимок остаётся (это ЧТО лечили), скрытое имя на диске и так hex.
    # Расширение сохраняем: по нему работает белый список открытия (_OPEN_EXT)
    for d in await _fetch(
            "SELECT id, stored_path FROM documents WHERE patient_id = $1",
            "SELECT id, stored_path FROM documents WHERE patient_id = ?", pid):
        neutral = f"document-{d['id']}{os.path.splitext(d['stored_path'])[1]}"
        await _execute(
            "UPDATE documents SET filename = $2 WHERE id = $1",
            "UPDATE documents SET filename = ? WHERE id = ?",
            *((d["id"], neutral) if not IS_SQLITE else (neutral, d["id"])))
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


async def move_appointment(appt_id: int, doctor_id: str, doctor: str,
                           starts_at: datetime, when: str = "") -> str:
    """Перенос визита на другое время и/или к другому врачу (перетаскивание).

    Ответ — КОД, а не bool: у переноса четыре разных отказа, и один «False» на
    все заставил бы журнал гадать, что показать регистратуре.
    `''` — перенесено; `conflict` — интервал занят у врача; `dup` — у пациента
    уже есть запись ровно на этот час; `gone` — записи больше нет;
    `closed` — визит не активен (завершён/отменён), такие не двигаем.

    ⚠️ Проверки те же и в том же порядке, что у новой брони, и обязательно ПОД
    `_BOOK_LOCK`: уникальные индексы ловят только совпадающие старты, а
    пересечение 10:00(60′) с 10:30(60′) — нет.
    ⚠️ `when` — время НОВОГО старта в часах клиники, уже строкой: db не знает
    про часовой пояс (в базе UTC), а летопись читает человек.
    """
    async with _BOOK_LOCK:
        rows = await _fetch(
            """SELECT patient_id, duration_min, status, service, starts_at
               FROM appointments WHERE id = $1""",
            """SELECT patient_id, duration_min, status, service, starts_at
               FROM appointments WHERE id = ?""", appt_id)
        if not rows:
            return "gone"
        r = rows[0]
        if r["status"] not in ACTIVE_STATUSES:
            return "closed"
        dur = int(r["duration_min"] or 60)
        if await _conflicts(doctor_id, doctor, starts_at, dur, exclude_id=appt_id):
            return "conflict"
        if r["patient_id"] and await _patient_busy_at(r["patient_id"], starts_at,
                                                      exclude_id=appt_id):
            return "dup"
        # ⚠️ Перенос ВРЕМЕНИ снимает отметки напоминаний. Флаг значит «пациенту
        # уже сказали про ЭТОТ час», а час стал другим: без сброса суточное
        # напоминание с новым временем не уходит вовсе (telegram._send_reminder
        # выходит по reminded_day), и пациент приезжает к прежнему часу — а
        # журнал рядом с визитом продолжает показывать «Reminder trimis».
        # Переезд к другому врачу в тот же час отметку не трогает: про час
        # сказано верно, а имя врача напоминание берёт актуальное.
        moved = rows[0]["starts_at"] != starts_at
        rem = ", reminded_day = FALSE, reminded_2h = FALSE" if moved else ""
        rem_lite = ", reminded_day = 0, reminded_2h = 0" if moved else ""
        try:
            await _execute(
                f"""UPDATE appointments SET doctor = $2, doctor_id = $3,
                   starts_at = $4{rem} WHERE id = $1""",
                f"""UPDATE appointments SET doctor = ?, doctor_id = ?,
                   starts_at = ?{rem_lite} WHERE id = ?""",
                *((appt_id, doctor, doctor_id, starts_at) if not IS_SQLITE
                  else (doctor, doctor_id, _iso(starts_at), appt_id)),
            )
        except Exception as e:  # noqa: BLE001 — uq_doctor_slot/uq_patient_slot
            if "uq_" in str(e) or "unique" in str(e).lower():
                if IS_SQLITE:
                    await _CONN.rollback()
                return "conflict"
            raise
        if r["patient_id"]:
            await log_event(r["patient_id"], "appt_move",
                            f"Vizită mutată: {when} · {doctor} — {r['service']}")
        return ""


async def set_status(appt_id: int, status: str) -> str:
    """'' = получилось. Иначе КОД отказа, и их два разных:

    * 'conflict' — час занят У ВРАЧА (вернули визит, а слот уже отдан другому);
    * 'dup' — у ПАЦИЕНТА уже есть активная запись на этот час.

    ⚠️ Разница не косметическая. Регистратура, прочитавшая «интервал занят у
    этого медика» про час, который у медика свободен, чинить ничего не может:
    занят он у пациента, и переносить надо ЧАС. Ровно эта подмена уже записана
    в грабли для _book.
    ⚠️ Причину спрашиваем У ДАННЫХ (`_patient_busy_at`, как это делает _book), а
    не разбираем текст исключения: два бэкенда пишут его по-разному, и ветка
    сообщения отмерла бы молча.
    """
    async with _BOOK_LOCK:
        rows = await _fetch(
            """SELECT patient_id, doctor, doctor_id, starts_at, duration_min, status
               FROM appointments WHERE id = $1""",
            """SELECT patient_id, doctor, doctor_id, starts_at, duration_min, status
               FROM appointments WHERE id = ?""", appt_id)
        r = rows[0] if rows else None
        if r and status in ACTIVE_STATUSES and r["status"] not in ACTIVE_STATUSES:
            # возврат в активный статус = та же пара проверок, что при новой
            # брони: uq-индексы ловят лишь совпадающие старты
            if await _conflicts(r["doctor_id"], r["doctor"], r["starts_at"],
                                int(r["duration_min"] or 60), exclude_id=appt_id):
                return "conflict"
            if r["patient_id"] and await _patient_busy_at(
                    r["patient_id"], r["starts_at"], exclude_id=appt_id):
                return "dup"
        try:
            # Штампы конвейера (08-13): «пришёл» и «зашёл в кабинет» пишутся в
            # сам визит — разница пары даёт время ожидания в приёмной.
            # ⚠️ Возврат в confirmed (reopen/промах «A venit») сбрасывает ОБА:
            # иначе мусорная пара от исправленного клика попала бы в среднее.
            if status == "waiting":
                await _execute(
                    "UPDATE appointments SET status = $2, waiting_at = now() WHERE id = $1",
                    "UPDATE appointments SET status = ?, waiting_at = ? WHERE id = ?",
                    *((appt_id, status) if not IS_SQLITE
                      else (status, _utcnow_iso(), appt_id)),
                )
            elif status == "arrived":
                await _execute(
                    "UPDATE appointments SET status = $2, arrived_at = now() WHERE id = $1",
                    "UPDATE appointments SET status = ?, arrived_at = ? WHERE id = ?",
                    *((appt_id, status) if not IS_SQLITE
                      else (status, _utcnow_iso(), appt_id)),
                )
            elif status == "confirmed":
                await _execute(
                    """UPDATE appointments SET status = $2,
                       waiting_at = NULL, arrived_at = NULL WHERE id = $1""",
                    """UPDATE appointments SET status = ?,
                       waiting_at = NULL, arrived_at = NULL WHERE id = ?""",
                    *((appt_id, status) if not IS_SQLITE else (status, appt_id)),
                )
            else:
                await _execute(
                    "UPDATE appointments SET status = $2 WHERE id = $1",
                    "UPDATE appointments SET status = ? WHERE id = ?",
                    *((appt_id, status) if not IS_SQLITE else (status, appt_id)),
                )
            own = await _fetch(
                "SELECT patient_id, service FROM appointments WHERE id = $1",
                "SELECT patient_id, service FROM appointments WHERE id = ?", appt_id)
            if own and own[0]["patient_id"]:
                # статус визита зовётся ОДНИМ словом на всю программу
                # (см. log_event): свой словарь тут уже расходился с журналом —
                # кнопка ставила «nu a venit», а летопись писала «neprezentare»
                from .core.layout import STATUS_LABEL
                await log_event(own[0]["patient_id"], "appt_status",
                                f"Vizită {STATUS_LABEL.get(status, status)}: "
                                f"{own[0]['service']}")
            return ""
        except Exception as e:  # noqa: BLE001 — uq_doctor_slot/uq_patient_slot
            if "uq_" in str(e) or "unique" in str(e).lower():
                if IS_SQLITE:
                    await _CONN.rollback()
                # ⚠️ КАКОЙ индекс сработал, движок в тексте не называет —
                # спрашиваем данные. Под УЗКОЙ страховкой (шаг 4 не доложен)
                # сюда доходит и переход между активными статусами.
                if r and r["patient_id"] and await _patient_busy_at(
                        r["patient_id"], r["starts_at"], exclude_id=appt_id):
                    return "dup"
                return "conflict"
            raise
