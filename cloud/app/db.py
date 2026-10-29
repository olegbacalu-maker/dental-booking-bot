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

SCHEMA_VERSION = 20
TS = "%Y-%m-%dT%H:%M:%SZ"


def _hash_idem(con: sqlite3.Connection) -> None:
    """Шаг 19: `sms_messages.idem` — хешем. Ключ программы `appt:<id визита>:<kind>:<начало UTC>`
    нёс время приёма пациента, а тексты обещают «только идентификатор» (план 29.10 § 2.4 п. 1).
    Дедупликация — по тому же столбцу, поэтому хешируются и старые строки; SQLite sha256 не знает —
    Python. Строка, уже похожая на хеш (64 hex), не трогается: шаг переживает повтор."""
    import hashlib
    rows = con.execute("SELECT id, idem FROM sms_messages").fetchall()
    for mid, idem in rows:
        if len(idem) == 64 and all(ch in "0123456789abcdef" for ch in idem):
            continue
        con.execute("UPDATE sms_messages SET idem=? WHERE id=?",
                    (hashlib.sha256(idem.encode("utf-8")).hexdigest(), mid))

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
    # SMS-пакет (S3, docs/dentpilot-2/sms.md › «Сервер»). Счёт клиники — `sms_accounts`
    # (выключатель Олега, имя отправителя и его путь, потолок); остаток НЕ хранится —
    # это SUM(delta) журнала `sms_ledger`. `sms_messages` — по строке на SMS ради
    # повтора без дубля (UNIQUE клиника + ключ программы) и статуса: ⛔ колонок для
    # номера и текста нет и не будет — они живут в памяти запроса к sms.md.
    # `sender_live` — одобренное имя (прежнее работает, пока новая заявка не одобрена);
    # SMS уходят от него, пока оплачен год — `sender_until` (отсчёт с одобрения;
    # `sender_prepaid` — оплаченные годы, ещё не начавшиеся), иначе от общего имени.
    # Платёж за пополнение или за имя — та же таблица payments с kind.
    11: [
        """CREATE TABLE IF NOT EXISTS sms_accounts(
            clinic_id TEXT PRIMARY KEY REFERENCES clinics(id),
            enabled INTEGER NOT NULL DEFAULT 1,
            sender TEXT NOT NULL DEFAULT '', sender_state TEXT NOT NULL DEFAULT 'none',
            sender_note TEXT NOT NULL DEFAULT '', sender_paper_at TEXT,
            sender_live TEXT NOT NULL DEFAULT '', sender_until TEXT,
            sender_prepaid INTEGER NOT NULL DEFAULT 0,
            pilot INTEGER NOT NULL DEFAULT 0,
            daily_cap INTEGER NOT NULL, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sms_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            idem TEXT NOT NULL, provider_id TEXT UNIQUE, kind TEXT NOT NULL,
            sender TEXT NOT NULL, segments INTEGER NOT NULL,
            state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
            sent_at TEXT NOT NULL, state_at TEXT NOT NULL, checked_at TEXT,
            UNIQUE(clinic_id, idem))""",
        "CREATE INDEX IF NOT EXISTS ix_sms_messages_clinic ON sms_messages(clinic_id, sent_at)",
        "CREATE INDEX IF NOT EXISTS ix_sms_messages_open ON sms_messages(state, sent_at)",
        """CREATE TABLE IF NOT EXISTS sms_ledger(
            id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            delta INTEGER NOT NULL, reason TEXT NOT NULL,
            payment_id INTEGER REFERENCES payments(id), message_id INTEGER REFERENCES sms_messages(id),
            at TEXT NOT NULL, who TEXT NOT NULL, note TEXT NOT NULL DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS ix_sms_ledger_clinic ON sms_ledger(clinic_id, at)",
        "ALTER TABLE payments ADD COLUMN kind TEXT NOT NULL DEFAULT 'license'",
        "ALTER TABLE payments ADD COLUMN sms_units INTEGER",
    ],
    # 12 (S6, 16.10): личный текст клиники — «свой текст по заявке» (sms.md ›
    # «Шаблоны и сегменты»): Олег вписывает в карточке, программа получает в
    # /v1/sms/account и предлагает вариант «Textul clinicii». Пусто = нет.
    12: [
        "ALTER TABLE sms_accounts ADD COLUMN custom_ro TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE sms_accounts ADD COLUMN custom_ru TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE sms_accounts ADD COLUMN custom_on INTEGER NOT NULL DEFAULT 0",
    ],
    # 13 (17.10): cont de plată после оплаты (receipts.py) — снимок оплаченного платежа:
    # реквизиты обеих сторон, предмет, сумма, чем оплачено (JSON в `data`); PDF
    # рисуется из снимка при запросе. Номер = reference платежа; одна строка на платёж.
    13: [
        """CREATE TABLE IF NOT EXISTS receipts(
            payment_id INTEGER PRIMARY KEY REFERENCES payments(id),
            clinic_id TEXT NOT NULL REFERENCES clinics(id),
            number TEXT NOT NULL UNIQUE, issued_at TEXT NOT NULL, data TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_receipts_clinic ON receipts(clinic_id, issued_at)",
    ],
    # 14 (17.10): подписанное заявление клиники на имя отправителя (бланк sms.md),
    # загруженное в кабинете (sms_paper.py). Файл — в БАЗЕ, а не на диске: так он
    # уезжает в ежедневную копию на ПК Олега вместе со всем остальным. Строки не
    # удаляются — это бумага для sms.md; `sender_paper_id` — заявление ТЕКУЩЕЙ
    # заявки (новая заявка на имя его обнуляет вместе с sender_paper_at).
    14: [
        """CREATE TABLE IF NOT EXISTS sms_papers(
            id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            sender TEXT NOT NULL, body BLOB NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
            filename TEXT NOT NULL DEFAULT '', uploaded_at TEXT NOT NULL, who TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_sms_papers_clinic ON sms_papers(clinic_id, id)",
        "ALTER TABLE sms_accounts ADD COLUMN sender_paper_id INTEGER",
    ],
    # 15 (23.10): два варианта абонемента — DentPilot Basic без модуля SMS и Plus с ним
    # (tiers.py). `subscriptions.tier` — вариант подписки, `sms_until` — до какого момента
    # модуль SMS ещё работает у Basic (конец периода, шедшего при переходе, условия § 4.2).
    # `payments.tier` — за какой вариант нота абонемента (у SMS-нот пусто), `terms_at` —
    # когда клиника отметила «Am citit și accept Termenii» перед этой оплатой (требование
    # maib; у нот админки и ежедневной задачи пусто). Всё, что было до шага, — Plus: пробный
    # и прежний единственный тариф включали SMS; цены существующих подписок не трогаются.
    # Там же — попытки оплаты картой: ссылка maib живёт 10 минут (maib.PAY_TTL), поэтому она
    # создаётся по клику «Plătește cu cardul», и у одной ноты их может быть несколько.
    # `payments.provider_id`/`pay_url` — последняя; `pay_attempts` — КАЖДАЯ: оплата во вкладке
    # со старой ссылкой должна узнаваться (callback, задача), а не прийти «не нашей».
    # `final` — maib дал окончательный ответ (OK, FAILED, TIMEOUT…): задача больше не спрашивает;
    # `counted` — деньги этой попытки зачтены (ноту закрыла она или зачёт повторного платежа).
    15: [
        "ALTER TABLE subscriptions ADD COLUMN tier TEXT NOT NULL DEFAULT 'plus'",
        "ALTER TABLE subscriptions ADD COLUMN sms_until TEXT",
        "ALTER TABLE payments ADD COLUMN tier TEXT",
        "ALTER TABLE payments ADD COLUMN terms_at TEXT",
        "UPDATE payments SET tier='plus' WHERE kind='license'",
        """CREATE TABLE IF NOT EXISTS pay_attempts(
            provider_id TEXT PRIMARY KEY, payment_id INTEGER NOT NULL REFERENCES payments(id),
            pay_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '', final INTEGER NOT NULL DEFAULT 0,
            counted INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS ix_pay_attempts_payment ON pay_attempts(payment_id)",
        "CREATE INDEX IF NOT EXISTS ix_pay_attempts_open ON pay_attempts(final, created_at)",
        """INSERT OR IGNORE INTO pay_attempts(provider_id, payment_id, pay_url, created_at, status, final, counted)
           SELECT provider_id, id, COALESCE(pay_url, ''), created_at, provider_status,
                  CASE WHEN paid_via='card' THEN 1 ELSE 0 END, CASE WHEN paid_via='card' THEN 1 ELSE 0 END
           FROM payments WHERE provider_id IS NOT NULL""",
    ],
    # 16 (26.10): филиал = ещё одна клиника в том же кабинете (Олег 26.10, cabinet.py).
    # `account_clinics` — к каким клиникам у учётной записи кабинета вход; каждой прежней записи —
    # её нынешняя клиника. `accounts.clinic_id` остаётся: клиника, открытая в кабинете последней.
    # `cabinet_codes` — код активации компьютера из кабинета (7 цифр: поле кода программы 2.0.9 —
    # maxlength 7), хешем; одноразовый, срок account.CODE_TTL. `payment_lines` — строки общей ноты
    # кабинета (payments.kind='cabinet'): клиника, вариант, срок и сумма строки.
    16: [
        """CREATE TABLE IF NOT EXISTS account_clinics(
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            clinic_id TEXT NOT NULL REFERENCES clinics(id),
            added_at TEXT NOT NULL, how TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(account_id, clinic_id))""",
        "CREATE INDEX IF NOT EXISTS ix_account_clinics_clinic ON account_clinics(clinic_id)",
        """INSERT OR IGNORE INTO account_clinics(account_id, clinic_id, added_at, how)
           SELECT id, clinic_id, created_at, 'clinica contului' FROM accounts WHERE clinic_id IS NOT NULL""",
        """CREATE TABLE IF NOT EXISTS cabinet_codes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            code_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            used_at TEXT, device TEXT NOT NULL DEFAULT '', who TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_cabinet_codes_hash ON cabinet_codes(code_hash, expires_at)",
        "CREATE INDEX IF NOT EXISTS ix_cabinet_codes_clinic ON cabinet_codes(clinic_id, created_at)",
        """CREATE TABLE IF NOT EXISTS payment_lines(
            payment_id INTEGER NOT NULL REFERENCES payments(id), clinic_id TEXT NOT NULL REFERENCES clinics(id),
            tier TEXT NOT NULL, months INTEGER NOT NULL, amount INTEGER NOT NULL,
            PRIMARY KEY(payment_id, clinic_id))""",
        "CREATE INDEX IF NOT EXISTS ix_payment_lines_clinic ON payment_lines(clinic_id)",
    ],
    # 17 (27.10, план В): подтверждение e-mail клиники (emailconf.py). `email_confirmed_at` — когда
    # ящик доказан (ссылка или код из письма, вход в кабинет на него); пусто — не подтверждён,
    # директору напоминание, Олегу метка. `email_confirms` — ссылка (`id` = хеш ключа) и код (хешем)
    # на АДРЕС `email`: после смены ящика старые не подтверждают новый. Клиники, заведённые до
    # шага, подтверждены, если журнал знает доказательство ящика: код второго компьютера ушёл на
    # него и был введён (`code_ok`), или в кабинет вошли учётной записью с этим ящиком.
    17: [
        "ALTER TABLE clinics ADD COLUMN email_confirmed_at TEXT",
        """CREATE TABLE IF NOT EXISTS email_confirms(
            id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            email TEXT NOT NULL, code_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, used_at TEXT, who TEXT NOT NULL DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS ix_email_confirms_clinic ON email_confirms(clinic_id, created_at)",
        """UPDATE clinics SET email_confirmed_at = COALESCE(
               (SELECT MIN(at) FROM audit WHERE what='code_ok' AND audit.clinic_id = clinics.id),
               (SELECT MIN(COALESCE(a.last_login_at, a.created_at)) FROM accounts a
                  JOIN account_clinics ac ON ac.account_id = a.id
                 WHERE ac.clinic_id = clinics.id AND lower(a.email) = lower(clinics.email)))
           WHERE email <> ''""",
        """INSERT INTO audit(at, who, what, clinic_id, detail)
           SELECT email_confirmed_at, 'migration', 'email_confirmed', id,
                  email || ' — din jurnal: cod pe al doilea calculator sau intrare în cont'
           FROM clinics WHERE email_confirmed_at IS NOT NULL""",
    ],
    # 18 (27.10): вход в кабинет кнопкой программы «Deschide contul clinicii» (contlink.py). Строка —
    # одноразовая ссылка: хеш её id (сам id живёт только в ответе программе), срок 5 минут, когда
    # погашена и с какого адреса (только для журнала: к IP вход не привязан).
    18: [
        """CREATE TABLE IF NOT EXISTS cont_links(
            id_hash TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT, used_ip TEXT NOT NULL DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS ix_cont_links_clinic ON cont_links(clinic_id, created_at)",
    ],
    # 19 (29.10, terms.py): акт акцепта условий — клиника, версия (дата «Ultima actualizare»), кто
    # принял, когда, адрес, компьютер и версия программы, откуда (заявка, код, оплата, повтор из
    # программы), хеш текста, если клиент его назвал. До шага сервер знал только `consent_at`.
    # Тем же шагом `sms_messages.idem` становится хешем (`_hash_idem`) — шаг со строкой-функцией:
    # init() зовёт её с соединением (SQLite sha256 не знает).
    19: [
        """CREATE TABLE IF NOT EXISTS terms_acceptances(
            id TEXT PRIMARY KEY, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            version TEXT NOT NULL, actor TEXT NOT NULL DEFAULT '', at TEXT NOT NULL,
            ip TEXT NOT NULL DEFAULT '', device TEXT NOT NULL DEFAULT '', app_version TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL CHECK(source IN ('trial','verify','pay','program')),
            terms_sha256 TEXT NOT NULL DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS ix_terms_acceptances_clinic ON terms_acceptances(clinic_id, at)",
        _hash_idem,
    ],
    # 20 (29.10, contracts.py; Олег: «не слишком сложно — в кабинете бумаги, подписанные мною»): договор
    # лицензии и соглашение об обработке — ОБЩИЕ PDF, подписанные Олегом один раз на версию и положенные на
    # сервер как декларация (DP_CONTRACT, DP_DPA); клиника в тексте не именуется, её акцепт — у terms-evidence
    # (шаг 19). Здесь — только экземпляр, который клиника ПО ЖЕЛАНИЮ подписала своей КЭП (или скан) и
    # загрузила в кабинете: строка на загрузку, файл на диске data/contracts/<clinic_id>/<id>.pdf
    # (contracts.folder(); подписанный КЭП PDF — мегабайты, в ежедневной копии базы ему не место — папку
    # увозит pull-backups.ps1), в базе имя и sha256. Без состояний и без подписи поставщика в ответ.
    20: [
        """CREATE TABLE IF NOT EXISTS clinic_contracts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, clinic_id TEXT NOT NULL REFERENCES clinics(id),
            doc TEXT NOT NULL CHECK(doc IN ('contract','dpa')), version TEXT NOT NULL DEFAULT '',
            file TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0,
            uploaded_at TEXT NOT NULL, who TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_clinic_contracts_clinic ON clinic_contracts(clinic_id, id)",
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


def apply_step(con: sqlite3.Connection, step: int) -> None:
    """Один шаг схемы: строки — SQL, функция — шаг, которому мало SQL (хеш строк, шаг 19).
    ⭐ Кто воспроизводит схему сам (тесты на `:memory:`), зовёт это, а не `con.execute` по списку."""
    for sql in MIGRATIONS[step]:
        if callable(sql):
            sql(con)
        else:
            con.execute(sql)


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
            apply_step(con, step)
            con.execute("INSERT INTO schema_meta(key, value) VALUES('version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(step),))
            con.execute("COMMIT")
    finally:
        con.close()


def audit(con: sqlite3.Connection, who: str, what: str, clinic_id: str | None = None,
          detail: str = "") -> None:
    con.execute("INSERT INTO audit(at, who, what, clinic_id, detail) VALUES(?,?,?,?,?)",
                (now_iso(), who, what, clinic_id, detail[:500]))
