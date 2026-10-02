"""База сервера: SQLite в режиме WAL, шаги миграций тем же приёмом, что db.py движка.

Соединение на запрос, а не одно на процесс: обработчики FastAPI синхронные и
идут в пуле потоков, а sqlite3 не любит чужих потоков. Для десятков клиник
этого больше чем достаточно; PostgreSQL — когда придёт шаг 3 (cloud.md).

⚠️ Новый шаг в MIGRATIONS без поднятия SCHEMA_VERSION — мёртвый код: цикл
идёт range(have+1, SCHEMA_VERSION+1) и до него не дойдёт.
"""
from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA_VERSION = 10
TS = "%Y-%m-%dT%H:%M:%SZ"

MIGRATIONS = {
    1: [
        """CREATE TABLE IF NOT EXISTS clinics(
               id TEXT PRIMARY KEY, name TEXT NOT NULL, idno TEXT NOT NULL DEFAULT '',
               contact_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
               phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
               country TEXT NOT NULL DEFAULT 'MD', created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS subscriptions(
               clinic_id TEXT PRIMARY KEY REFERENCES clinics(id),
               plan TEXT NOT NULL DEFAULT 'trial', price INTEGER NOT NULL DEFAULT 399,
               currency TEXT NOT NULL DEFAULT 'MDL', valid_until TEXT,
               grace_days INTEGER NOT NULL DEFAULT 14, cancelled_at TEXT,
               updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS issues(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               clinic_id TEXT NOT NULL REFERENCES clinics(id), seq INTEGER NOT NULL,
               kid TEXT NOT NULL, payload TEXT NOT NULL, sig TEXT NOT NULL,
               issued_at TEXT NOT NULL, valid_until TEXT NOT NULL, grace_until TEXT NOT NULL,
               reason TEXT NOT NULL DEFAULT '', UNIQUE(clinic_id, seq))""",
        """CREATE TABLE IF NOT EXISTS payments(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               clinic_id TEXT NOT NULL REFERENCES clinics(id),
               amount INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'MDL',
               method TEXT NOT NULL, status TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
               months INTEGER NOT NULL DEFAULT 1, provider_id TEXT UNIQUE,
               created_at TEXT NOT NULL, paid_at TEXT, confirmed_by TEXT)""",
        """CREATE TABLE IF NOT EXISTS reminders(
               subscription_id TEXT NOT NULL, kind TEXT NOT NULL, period TEXT NOT NULL,
               sent_at TEXT NOT NULL, PRIMARY KEY(subscription_id, kind, period))""",
        """CREATE TABLE IF NOT EXISTS audit(
               id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, who TEXT NOT NULL,
               what TEXT NOT NULL, clinic_id TEXT, detail TEXT NOT NULL DEFAULT '')""",
    ],
    # L13, автообновление: токен клиники (уезжает в поле renew файла, рождается с
    # первой выдачей — license.renew_token) и след последнего запроса программы:
    # когда спрашивала и какой seq у неё был. Пусто у клиник до миграции — до их
    # следующей выдачи.
    2: [
        "ALTER TABLE clinics ADD COLUMN renew_token TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE clinics ADD COLUMN renew_at TEXT",
        "ALTER TABLE clinics ADD COLUMN renew_seq INTEGER",
    ],
    # L12, карты: адрес hosted-страницы maib и последний статус, который назвал
    # сам maib (pay-info). `provider_id` (payId) и его UNIQUE — с первой схемы.
    3: [
        "ALTER TABLE payments ADD COLUMN pay_url TEXT",
        "ALTER TABLE payments ADD COLUMN provider_status TEXT NOT NULL DEFAULT ''",
    ],
    # L14, форма пробного периода: откуда клиника (admin | form), когда попросила,
    # когда согласилась с условиями, когда заявку скрыли (пробный не выдан).
    4: [
        "ALTER TABLE clinics ADD COLUMN origin TEXT NOT NULL DEFAULT 'admin'",
        "ALTER TABLE clinics ADD COLUMN requested_at TEXT",
        "ALTER TABLE clinics ADD COLUMN consent_at TEXT",
        "ALTER TABLE clinics ADD COLUMN declined_at TEXT",
    ],
    # Активация на новом компьютере (26.09): код на e-mail клиники. `id` — то,
    # что знает программа (verify_id); сам код хранится только хешем.
    5: [
        """CREATE TABLE IF NOT EXISTS activation_codes(
            id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            code_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, used_at TEXT)""",
        "CREATE INDEX IF NOT EXISTS ix_codes_clinic ON activation_codes(clinic_id, created_at)",
    ],
    # Кабинет клиники (шаг 3, 01.10): учётная запись — кто вошёл через Google
    # (`subject` = sub из id_token, один навсегда), к какой клинике привязана.
    # Пароля нет: его держит Google. `clinic_id` пуст у записи, которая вошла,
    # но клинику ещё не зарегистрировала. `clinics.origin` получает значение `cont`.
    6: [
        """CREATE TABLE IF NOT EXISTS accounts(
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, subject TEXT NOT NULL,
            email TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
            clinic_id TEXT REFERENCES clinics(id),
            created_at TEXT NOT NULL, last_login_at TEXT, UNIQUE(provider, subject))""",
        "CREATE INDEX IF NOT EXISTS ix_accounts_clinic ON accounts(clinic_id)",
    ],
    # Флот (шаг 3, 02.10): компьютеры клиник, как они назвались серверу в
    # заголовках X-DentPilot-* при запросе файла или заявке (fleet.py).
    # `id` — личность машины из device.json программы (P7); версия — из
    # User-Agent; `last_seq` — какой файл у программы был при последнем запросе.
    7: [
        """CREATE TABLE IF NOT EXISTS devices(
            id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            version TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '',
            os TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
            last_seq INTEGER)""",
        "CREATE INDEX IF NOT EXISTS ix_devices_clinic ON devices(clinic_id, last_seen_at)",
    ],
    # Вход в кабинет кодом на e-mail (02.10, login.py): код хранится хешем,
    # `canon` — ящик в канонической форме для лимита «кодов на ящик в час».
    # Не activation_codes: тот привязан к клинике, а ящик при входе её может не иметь.
    8: [
        """CREATE TABLE IF NOT EXISTS login_codes(
            id TEXT PRIMARY KEY, email TEXT NOT NULL, canon TEXT NOT NULL,
            code_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, used_at TEXT)""",
        "CREATE INDEX IF NOT EXISTS ix_login_codes_canon ON login_codes(canon, created_at)",
    ],
    # Оплата из программы (02.10, paylink.py): одноразовая ссылка /plata/<id> на сутки,
    # которую программа получает по своему токену и открывает в браузере.
    9: [
        """CREATE TABLE IF NOT EXISTS pay_links(
            id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_pay_links_clinic ON pay_links(clinic_id, expires_at)",
    ],
    # 02.10, вопрос Олега «чтобы потом не проснуться с детской проблемой»:
    # anchor_day — число, от которого считается помесячное продление (31.01 → 28.02 →
    # 31.03, а не 28.03 навсегда); paid_via — чем ЗАКРЫТА нота. `method` ноты со ссылкой
    # maib — «card» с момента ссылки, и по нему не понять, что карта пришла ВТОРОЙ,
    # после подтверждённого перевода. Оплаченные до этого шага — только переводом:
    # maib на боевом сервере не включался.
    10: [
        "ALTER TABLE subscriptions ADD COLUMN anchor_day INTEGER",
        "ALTER TABLE payments ADD COLUMN paid_via TEXT",
        "UPDATE payments SET paid_via='transfer' WHERE status='paid'",
    ],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(TS)


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, TS).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@contextlib.contextmanager
def connect(immediate: bool = False):
    """`immediate` — транзакция сразу берёт замок записи: для маршрута, который
    сперва читает, потом пишет по прочитанному (форма пробного — «уже есть?» →
    INSERT); две такие заявки одновременно иначе упирались бы в «database is
    locked» вместо того, чтобы вторая дождалась первой и увидела её строку."""
    con = sqlite3.connect(config.DB_PATH, isolation_level=None, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def init() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = con.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        have = int(row[0]) if row else 0
        for step in range(have + 1, SCHEMA_VERSION + 1):
            con.execute("BEGIN")
            for sql in MIGRATIONS[step]:
                con.execute(sql)
            con.execute("INSERT INTO schema_meta(key, value) VALUES('version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(step),))
            con.execute("COMMIT")
    finally:
        con.close()


def audit(con: sqlite3.Connection, who: str, what: str, clinic_id: str | None = None,
          detail: str = "") -> None:
    con.execute("INSERT INTO audit(at, who, what, clinic_id, detail) VALUES(?,?,?,?,?)",
                (now_iso(), who, what, clinic_id, detail[:500]))
