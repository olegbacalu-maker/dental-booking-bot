"""Слой БД: SQLite (aiosqlite), файл картотеки из DATABASE_URL (sqlite:///…).
Даты храним как ISO-строки в UTC — сравнения лексикографичны.

Postgres-издание снято 12.10.2026 (на нём не работало ничего живого: демо
сайта — тот же SQLite); последний код с ним — тег `archive/pg-edition`."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import secrets
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL", "")

log = logging.getLogger("db")

# Версия схемы: шаги применяются по одному и записываются в schema_meta,
# поэтому по базе клиники всегда видно, докуда она домигрирована.
# ⚠️ Новый шаг в MIGRATIONS без поднятия версии — МЁРТВЫЙ код: цикл _migrate
# идёт range(have+1, SCHEMA_VERSION+1) и до него не дойдёт (так шаг 4 с
# 'waiting' в uq-индексах не исполнялся ни у одной клиники; держит
# test_structure).
SCHEMA_VERSION = 8

# Записи, которые ЗАНИМАЮТ слот врача. 'waiting' (пациент пришёл, ждёт в
# приёмной, 08-13) стоит между confirmed и arrived: физически человек уже в
# клинике, и слот его. 'arrived' (пациент в кабинете) обязан
# быть здесь: иначе отметка «пришёл» освобождает час и бот сажает второго.
ACTIVE_STATUSES = ("confirmed", "waiting", "arrived")
_ACT_SQL = "('confirmed','waiting','arrived')"

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
# guard в desktop.py) — процессного замка достаточно.
# ⛔ Напрямую _BOOK_LOCK не брать — только через _slot_lock(): одна точка входа
# у всех, кто занимает слот (правило держит test_structure). Появится второй
# процесс над той же базой — замок меняется в ОДНОМ месте.
_BOOK_LOCK = asyncio.Lock()


@contextlib.asynccontextmanager
async def _slot_lock():
    """Замок всех записей, занимающих слот (бронь, заметка, перенос, возврат
    статуса). Вставка коммитится ДО выхода отсюда — следующий владелец замка
    уже видит её в `_conflicts`."""
    async with _BOOK_LOCK:
        yield

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
# Прикус («Ocluzia», 26.10): одна запись на пациента — графа раздела 4 формы
# 043/e, до того жёлтый пропуск. Пусто = «не записано», никогда не «норма»:
# печатается только то, что врач вписал. Классы по Энглю, стороны — белые
# списки сервера (modules/patients/ocluzie.py); мм — строкой как прислали
# (нормализованная запятая), overbite бывает отрицательным. Медзапись: держит
# фишу от стирания, обезличивание не трёт, едет в выгрузку по 195-му.
# ⚠️ Текст ниже стоит и в SQLITE_CARD_SCHEMA — оба обязаны совпадать.
OCLUZIE_DDL = """CREATE TABLE IF NOT EXISTS ocluzie(
  patient_id INTEGER PRIMARY KEY REFERENCES patients(id),
  angle_dr TEXT NOT NULL DEFAULT '',
  angle_st TEXT NOT NULL DEFAULT '',
  overjet TEXT NOT NULL DEFAULT '',
  overbite TEXT NOT NULL DEFAULT '',
  incrucisata TEXT NOT NULL DEFAULT '',
  deschisa TEXT NOT NULL DEFAULT '',
  mediana_mm TEXT NOT NULL DEFAULT '',
  mediana_spre TEXT NOT NULL DEFAULT '',
  nota TEXT NOT NULL DEFAULT '',
  doctor TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT
)"""

# «Rechemări» (29.10, мини-CRM регистратуры): отметки обзвона по паре
# (пациент, услуга) — ЖУРНАЛ, только дописывается (append-only). Сам список
# «кому пора» не хранится: он считается при каждом запросе из done-визитов и
# срока у услуги (`core/recall.py`), поэтому пересчёт отметку не трогает —
# только читает. `cycle_appt_id` — последний done-визит на момент отметки:
# отметки прошлого цикла (кроме `stop`) перестают действовать сами, как
# только пациент пришёл снова. `until_date` — ГОЛАЯ дата (только `later`),
# `at` — UTC (псевдоним уже в _DT_COLS). Свободного текста нет намеренно: он
# стал бы личностью, которую нужно стирать при обезличивании.
# ⚠️ Текст ниже стоит и в SQLITE_CARD_SCHEMA — оба обязаны совпадать
# (`test_recall.suite_schema`).
RECALL_DDL = """CREATE TABLE IF NOT EXISTS recall_marks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  service_id TEXT NOT NULL,
  cycle_appt_id INTEGER,
  result TEXT NOT NULL,
  until_date TEXT,
  actor TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL
)"""
RECALL_IDX_DDL = ("CREATE INDEX IF NOT EXISTS ix_recall_pat "
                  "ON recall_marks(patient_id, service_id, id)")

MIGRATIONS = {
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
    # 5 (08-17): «în tratament» перестало быть состоянием и стало ОТМЕТКОЙ
    # поверх находки (teeth_svg.TOOTH_MARKS). У клиник такие зубы уже записаны
    # состоянием, а имени 'tratament' в STATE_RO больше нет — без этого шага
    # `state if state in STATE_RO else "ok"` показал бы их «Sănătos»: молча, и
    # на подписываемой 043/e тоже.
    # ⚠️ Строгость тут своя и правильная (шаг меняет ДАННЫЕ): не сработавший
    # UPDATE обязан уронить старт, а не записать версию схемы как выполненную.
    # Уронить он может только отсутствием колонки — а она добавляется выше, в
    # init, до _migrate.
    5: ["UPDATE teeth SET marks = 'tratament', state = 'ok' "
        "WHERE state = 'tratament'"],
    # 6 (25.10, «сравнить с визитом»): базовый снимок карты в teeth_history и
    # метка, С КАКОГО мгновения история полная. Работу делает
    # `_teeth_hist_base` (см. TEETH_HIST_STEP): время снимка обязано быть тем
    # же `_utcnow_iso`, что пишет записи зубов, а SQL-шаг параметров не берёт
    # (`strftime('now')` SQLite шёл бы мимо часов программы).
    # ⚠️ Список ПУСТ, но НЕ мёртв — как у 4: _migrate исполняет его после
    # `_teeth_hist_base`.
    6: [],
    # 7 (26.10, «Ocluzia» в 043/e, волна 3): таблица прикуса `ocluzie` — одна
    # запись на пациента, как `anamneza`. Тот же DDL стоит и в
    # SQLITE_CARD_SCHEMA (свежая база получает таблицу схемой); здесь — веха в
    # schema_meta: по версии базы видно, что у клиники графа прикуса уже есть.
    # Идемпотентно (IF NOT EXISTS), строго: DDL, упавший на старте, — повод
    # падать, а не писать версию как выполненную. Совпадение текста с схемой
    # держит `test_ocluzie.suite_schema`.
    7: [OCLUZIE_DDL],
    # 8 (29.10, «Rechemări»): журнал отметок обзвона `recall_marks` + индекс
    # по паре. Таблица новая и аддитивная — данных, которым она противоречит,
    # нет, падать нечему; строго, как 7. Тот же DDL — в SQLITE_CARD_SCHEMA.
    8: [RECALL_DDL, RECALL_IDX_DDL],
}
# Шаг, который кладёт базовый снимок истории зубов. В отличие от
# UQ_GUARD_STEP — СТРОГИЙ: он меняет данные, и недописанный снимок не имеет
# права записать версию схемы как выполненную.
TEETH_HIST_STEP = 6
# Ключ schema_meta: с какого мгновения `teeth_history` полная (ставит шаг 6).
TEETH_HIST_SINCE = "teeth_hist_since"
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
-- Дневник визита (consultația): запись приёма 1:1 к appointments — будущая
-- дневниковая часть формы 043/e. doctor — снапшот имени на момент приёма.
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
-- Анамнез: опросник «до кресла», один на пациента. Заполняет раздел 2 формы
-- 043/e. flags — отмеченные состояния одной строкой ('diabet,hepatita'),
-- чтобы добавление вопроса не требовало миграции у клиники.
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
-- Прикус (26.10, «Ocluzia» 043/e): одна запись на пациента, как anamneza.
-- Тот же текст стоит в OCLUZIE_DDL (шаг миграции 7); менять оба.
CREATE TABLE IF NOT EXISTS ocluzie(
  patient_id INTEGER PRIMARY KEY REFERENCES patients(id),
  angle_dr TEXT NOT NULL DEFAULT '',
  angle_st TEXT NOT NULL DEFAULT '',
  overjet TEXT NOT NULL DEFAULT '',
  overbite TEXT NOT NULL DEFAULT '',
  incrucisata TEXT NOT NULL DEFAULT '',
  deschisa TEXT NOT NULL DEFAULT '',
  mediana_mm TEXT NOT NULL DEFAULT '',
  mediana_spre TEXT NOT NULL DEFAULT '',
  nota TEXT NOT NULL DEFAULT '',
  doctor TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT
);
-- «Rechemări» (29.10): журнал отметок обзвона по паре пациент–услуга.
-- Тот же текст стоит в RECALL_DDL / RECALL_IDX_DDL (шаг миграции 8); менять оба.
CREATE TABLE IF NOT EXISTS recall_marks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  service_id TEXT NOT NULL,
  cycle_appt_id INTEGER,
  result TEXT NOT NULL,
  until_date TEXT,
  actor TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_recall_pat ON recall_marks(patient_id, service_id, id);
-- Мост (punte, 08-21, просьба пилота): конструкция ПОВЕРХ зубов, своя строка.
-- teeth — «47:stalp,46:corp,…» в порядке дуги (канон и разбор — teeth_svg,
-- роль у КАЖДОГО зуба: опора бывает и в середине); material — подпись под
-- скобкой («zirconiu» и т.п.); doctor — снапшот имени, как у teeth/plan_items.
CREATE TABLE IF NOT EXISTS bridges(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  teeth TEXT NOT NULL,
  material TEXT NOT NULL DEFAULT '',
  doctor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
-- История зуба СОСТОЯНИЯМИ («сравнить с визитом», волна 2 одонтограммы, 25.10):
-- строка на каждую запись зуба — каким он стал (`_put_tooth`, тот же `at`, что
-- teeth.updated_at), state NULL — строки зуба нет (здоров). Летопись хранит
-- СЛОВА, по ней прошлую карту не собрать; эта таблица копится с шага 6, а он
-- кладёт базовый снимок (`src` 'base') и метку начала `teeth_hist_since`.
-- Уникальных индексов нет и не надо: таблица только дописывается, и падать
-- на данных клиники ей нечему.
CREATE TABLE IF NOT EXISTS teeth_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  tooth INTEGER NOT NULL,
  at TEXT NOT NULL,
  state TEXT,
  note TEXT NOT NULL DEFAULT '',
  doctor TEXT NOT NULL DEFAULT '',
  surfaces TEXT NOT NULL DEFAULT '',
  surface_states TEXT NOT NULL DEFAULT '',
  marks TEXT NOT NULL DEFAULT '',
  src TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_teeth_hist ON teeth_history(patient_id, at);
-- Снятые мосты (25.10): `delete_bridge` переносит строку сюда, а не теряет —
-- иначе карта «на визит» рисовала бы без моста, который тогда стоял.
-- `bridge_id` — id прежней строки bridges (свой id — чтобы вставке нечему
-- было противоречить).
CREATE TABLE IF NOT EXISTS bridges_removed(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bridge_id INTEGER NOT NULL,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  teeth TEXT NOT NULL,
  material TEXT NOT NULL DEFAULT '',
  doctor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  removed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bridges_removed ON bridges_removed(patient_id);
-- Пародонтограмма: ОСМОТР целиком, а не «текущее состояние зуба». Смысл карты
-- пародонта — сравнение во времени (было 5 мм, стало 3), поэтому единица
-- хранения — датированный осмотр, а строки зубов принадлежат ему.
CREATE TABLE IF NOT EXISTS perio_exams(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id INTEGER NOT NULL REFERENCES patients(id),
  doctor TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS perio_teeth(
  exam_id INTEGER NOT NULL REFERENCES perio_exams(id) ON DELETE CASCADE,
  tooth INTEGER NOT NULL,
  pd TEXT NOT NULL DEFAULT '',
  rec TEXT NOT NULL DEFAULT '',
  bop TEXT NOT NULL DEFAULT '000000',
  mob INTEGER NOT NULL DEFAULT 0,
  furc INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (exam_id, tooth)
);
CREATE INDEX IF NOT EXISTS ix_perio_patient ON perio_exams(patient_id, created_at DESC);
-- Звонок-подтверждение визита регистратурой (01.10, список «De confirmat» на
-- главной): одна строка на визит — дозвонились / не отвечает, кто и когда.
CREATE TABLE IF NOT EXISTS appt_calls(
  appointment_id INTEGER PRIMARY KEY REFERENCES appointments(id),
  result TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- SMS-пакет (S5, 16.10; docs/dentpilot-2/sms.md › «Программа»): одно
-- напоминание — одна строка. Номер и текст живут ЗДЕСЬ, у клиники, — сервер
-- их не хранит. `idem` — ключ повтора `appt:{id}:{kind}:{starts_at}`: перенос
-- даёт новый ключ, повтор после обрыва — тот же, и вторую SMS сервер не шлёт.
-- `until_at` — конец окна отправки: текст «maine» после него стал бы неправдой.
-- Флаги Telegram (`reminded_day`/`reminded_2h`) здесь не участвуют.
CREATE TABLE IF NOT EXISTS sms_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  appt_id INTEGER REFERENCES appointments(id),
  patient_id INTEGER REFERENCES patients(id),
  kind TEXT NOT NULL,
  phone TEXT NOT NULL,
  text TEXT NOT NULL,
  segments INTEGER NOT NULL DEFAULT 1,
  idem TEXT NOT NULL UNIQUE,
  cloud_id INTEGER,
  state TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT '',
  until_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  state_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sms_appt ON sms_log(appt_id);
CREATE INDEX IF NOT EXISTS ix_sms_state ON sms_log(state, created_at);
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
    # отказ пациента от процедуры: ст.13(5) Legea 263/2005 требует, чтобы отказ
    # ОСТАЛСЯ в меддокументации с указанием возможных последствий, а не исчез
    ("plan_items", "refuz_motiv TEXT NOT NULL DEFAULT ''"),
    # поверхности зуба (M/O/D/V/L) одной строкой: у состояния зуба их может быть
    # несколько сразу («MOD»), но состояние остаётся ОДНО на зуб
    ("teeth", "surfaces TEXT NOT NULL DEFAULT ''"),
    # 08-16: у поверхностей могут быть РАЗНЫЕ состояния («M:carie,O:obturatie»).
    # Колонка добавляется пустой и НЕ переносит старые записи: пустая означает
    # ровно то, что означала прежняя пара state+surfaces (см. teeth_svg.surface_map),
    # поэтому шага миграции с UPDATE тут нет и падать нечему.
    ("teeth", "surface_states TEXT NOT NULL DEFAULT ''"),
    # 08-17: отметки зуба («tratament») — то, что живёт ПОВЕРХ находки, см.
    # teeth_svg.TOOTH_MARKS. Список строкой: вторая отметка не потребует колонки.
    # ВАЖНО: в отличие от surface_states, эта колонка ТРЕБУЕТ шага миграции (5):
    # «în tratament» было состоянием, и записи клиник надо перевести в отметку —
    # иначе они молча стали бы «Sănătos» (состояния с таким именем больше нет).
    ("teeth", "marks TEXT NOT NULL DEFAULT ''"),
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
    # SMS-пакет (S5, 16.10): «Fără remindere SMS» — отказ пациента от
    # напоминаний. Лист на стойке обещает «puteți renunța oricând, la recepție»
    # (acord.py, li4); цикл SMS такого пациента обходит (core/sms_loop.py).
    "sms_off INTEGER NOT NULL DEFAULT 0",
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
-- ВНИМАНИЕ: уникальных индексов слота здесь НЕТ намеренно (08-16). У них ОДИН
-- владелец — _slot_guard_apply, и он единственный, кто перед CREATE UNIQUE
-- INDEX спрашивает ДАННЫЕ. Эта схема исполняется при КАЖДОМ старте и ДО
-- миграций: оставленный тут CREATE падал бы у клиники с двойной бронью раньше,
-- чем сторож успеет хоть что-то сделать, и программа не открывалась бы вовсе.
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
# patients_visits: у выражения нет типа колонки, и SQLite отдаёт его строкой.
_DT_COLS = {"starts_at", "created_at", "uploaded_at", "updated_at", "at",
            "last_at", "next_at", "done_at", "waiting_at", "arrived_at",
            "state_at", "until_at", "visit_at", "removed_at"}


def _rowdict(row) -> dict:
    d = dict(row)
    for k in _DT_COLS & d.keys():
        if d[k] is not None:
            d[k] = _parse_dt(d[k])
    return d


# ---------- низкоуровневые помощники ----------

async def _fetch(sql: str, *args) -> list[dict]:
    cur = await _CONN.execute(sql, args)
    rows = await cur.fetchall()
    await cur.close()
    return [_rowdict(r) for r in rows]


async def _fetchval(sql: str, *args):
    cur = await _CONN.execute(sql, args)
    row = await cur.fetchone()
    await cur.close()
    await _CONN.commit()
    return row[0] if row else None


async def _execute(sql: str, *args) -> int:
    cur = await _CONN.execute(sql, args)
    await _CONN.commit()
    n = cur.rowcount
    await cur.close()
    return n


# ---------- init ----------

async def _schema_version() -> int:
    try:
        v = await _fetchval("SELECT value FROM schema_meta WHERE key = 'version'")
        return int(v) if v is not None else 0
    except Exception as e:  # noqa: BLE001 — обычно «таблицы ещё нет» = версия 0
        log.warning("schema_meta read failed (treating as v0): %r", e)
        return 0


async def _set_schema_version(v: int) -> None:
    await _execute(
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
            "SELECT value FROM schema_meta WHERE key = ?", key)
    except Exception as e:  # noqa: BLE001 — служебное значение не роняет старт
        log.warning("get_meta(%s) failed: %r", key, e)
        return None


async def set_meta(key: str, value: str) -> None:
    await _execute(
        """INSERT INTO schema_meta(key, value) VALUES(?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        key, value,
    )


async def del_meta(key: str) -> None:
    await _execute("DELETE FROM schema_meta WHERE key = ?", key)


async def patients_total() -> int:
    """Пуста ли картотека — вопрос лицензии (core/license.py): на пустой без
    файла стоит стена активации, на живой — отсчёт льготы.
    ⚠️ Не `patients_count`: то имя занято счётчиком ОТФИЛЬТРОВАННОГО списка
    ниже, и одноимённая функция молча перекрыла бы его (поймано 24.09)."""
    n = await _fetchval("SELECT count(*) FROM patients")
    return int(n or 0)


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
# min(...) вместо голой колонки — стандартный SQL: колонка не из GROUP BY в
# списке выбора разрешена только SQLite, и значение её не определено.
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
_UQ_STATE = ("SELECT name AS name, COALESCE(sql,'') AS sql "
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
                     for r in await _fetch(sql)]
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
            for r in await _fetch(_UQ_STATE)}


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

    Сверять побайтово нельзя: SQLite хранит текст CREATE таким, каким его
    прислала версия программы, клавшая индекс, а отступы и перенос строк у
    версий разные. Поэтому сверяется набор статусов: в определении слотового
    индекса других строк в кавычках нет.
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
# ⛔ Вторая строка на ВТОРОЙ исход, и разъединять их обязательно. Метка
# снимается не только там, где двойные часы были и клиника их развела: она
# снимается и после исхода, где конфликтных часов не было НИ ОДНОГО (`unknown:0`
# — состояние не прочиталось; `broken:0`/`narrow:0` — шаг упёрся не в данные).
# Одна строка на оба случая записывает клинике, у которой двойной брони не было
# ни дня, что её разводили, — отчёт о работе, которой не было, и летопись
# хранит его НАВСЕГДА (08-16). Сколько часов насчитал прошлый старт, знает сама
# метка: она стоит как `level:rows`, и спрашивать об этом больше некого — к
# моменту снятия конфликтов уже нет по определению.
UQ_COMPLETE_TEXT = ("Protecția programărilor împotriva orelor duble este "
                    "completă din nou")


def _uq_mark_rows(mark: str | None) -> int:
    """Сколько конфликтных часов насчитал ПРОШЛЫЙ старт — из самой метки.

    ⚠️ Ответ -1 значит «счётчика в метке нет», и это НЕ ноль. Так выглядит метка
    «1», поставленная ДО работы: процесс не дожил до вердикта, и о конфликтах
    неизвестно ничего. Утверждать «разводить было нечего» тут так же нельзя, как
    и «часы разведены», — поэтому обе ветки текста читают именно «> 0».
    """
    text = str(mark or "")
    if ":" not in text:
        return -1
    try:
        return int(text.rsplit(":", 1)[1])
    except ValueError:
        return -1


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
            for sql in steps:
                await _CONN.execute(sql)
            await _CONN.commit()
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
        # ⭐ Едет дальше ЗНАЧЕНИЕ метки, а не «она была». В значении лежит
        # счётчик конфликтных часов прошлого старта, и без него строка о снятии
        # метки не может отличить «часы развели» от «разводить было нечего».
        mark = await get_meta(UQ_PENDING_KEY)
    except Exception as e:  # noqa: BLE001 — база не отвечает; старт важнее
        log.error("метка %s не прочитана: %r", UQ_PENDING_KEY, e)
        mark = None
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
    await _slot_guard_verdict(rows, mark, repair)


async def _slot_guard_verdict(rows: list[dict], mark: str | None,
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
        await _slot_guard_clear(mark, repair)
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
    if mark is not None:
        # ⚠️ Строка в ленту — ОДИН раз на одно вмешательство, как у auth_alert:
        # баннер висит и так, а перезапуски не должны пополнять летопись.
        return
    # Текст — в `uq_event_text`, одним куском на все исходы: он же и единственное
    # место, где видно, что строка обязана уместиться в потолок летописи.
    await log_clinic_event("uq_guard", uq_event_text(level, gone, len(rows)))


async def _slot_guard_clear(mark: str | None, repair: str = "") -> None:
    """Широкие индексы легли и ПРОВЕРЕНЫ.

    ⚠️ Метка с прошлого старта — это ещё не «клиника развела записи»: тем же
    путём снимаются метки исходов, где конфликтных часов не было вовсе. Что
    именно случилось, говорит счётчик В САМОЙ МЕТКЕ (`level:rows`), поэтому сюда
    приезжает её ЗНАЧЕНИЕ, а не «она была».
    """
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
    if mark is None:
        return                       # обычная миграция, рассказывать нечего
    # ⛔ «Часы разведены» говорится ТОЛЬКО там, где часы были: счётчик в метке и
    # есть то, что прошлый старт про них знал. Ноль (и метка без счётчика —
    # оборванный старт) значит, что разводить было нечего, и рассказ о
    # разведении был бы отчётом о работе, которой не было (08-16).
    n = _uq_mark_rows(mark)
    log.warning("полная защита слота восстановлена (конфликтных часов было: %s)",
                n if n >= 0 else "неизвестно")
    await log_clinic_event("uq_guard",
                           UQ_CLEARED_TEXT if n > 0 else UQ_COMPLETE_TEXT)


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


async def _teeth_hist_base() -> None:
    """Шаг 6: базовый снимок КАЖДОЙ строки teeth в teeth_history и метка
    `teeth_hist_since` — одной транзакцией. С этого мгновения карта на любую
    дату известна: что было записано, лежит снимком, а зуба без строки в
    teeth тогда не было — он здоров.

    Идемпотентно по метке: обрыв между этим commit и записью версии схемы
    повторит шаг на следующем старте, и второй базовый снимок не ляжет.
    ⛔ Ошибки не глотаются (`_fetchval`, а не `get_meta`): «метки не
    прочитали» ≠ «метки нет», и второй снимок поверх первого лёг бы молча."""
    if await _fetchval("SELECT value FROM schema_meta WHERE key = ?", TEETH_HIST_SINCE):
        return
    at = _utcnow_iso()
    try:
        # Снимок датирован ПОСЛЕДНЕЙ записью зуба (`updated_at`): с неё он такой
        # и есть, и дата зуба на карте «на визит» та же, что у экрана. Не позже
        # метки: строка «из будущего» (часы машины шагали назад) иначе не вошла
        # бы в карту между меткой и своей датой — зуб показался бы здоровым.
        await _CONN.execute(
            """INSERT INTO teeth_history(patient_id, tooth, at, state, note, doctor,
                                         surfaces, surface_states, marks, src)
               SELECT patient_id, tooth, MIN(updated_at, ?), state, note, doctor,
                      surfaces, surface_states, marks, 'base' FROM teeth""", (at,))
        await _CONN.execute("INSERT INTO schema_meta(key, value) VALUES(?, ?)",
                            (TEETH_HIST_SINCE, at))
        await _CONN.commit()
    except Exception:
        await _CONN.rollback()
        raise


async def _migrate() -> None:
    """Пошаговые миграции: каждый шаг применяется один раз и фиксируется.
    Раньше состояние базы можно было понять только по наличию колонок."""
    have = await _schema_version()
    if have >= SCHEMA_VERSION:
        return
    steps = MIGRATIONS
    for v in range(have + 1, SCHEMA_VERSION + 1):
        if v not in steps:
            # забытый список SQL = молчаливый no-op с записанной версией; лучше упасть
            raise RuntimeError(f"missing migration step {v} for "
                               f"{'sqlite'}")
        if v == UQ_GUARD_STEP:
            # ⛔ Единственный шаг, который НЕ имеет права уронить старт: он про
            # страховочный индекс, а не про данные, и расширение предиката
            # упирается в живые записи клиники. Упавший — оставлял бы версию
            # схемы прежней, то есть падал бы при КАЖДОМ запуске: у клиники это
            # «после обновления программа не открывается» (08-16).
            await _slot_guard_apply()
        if v == TEETH_HIST_STEP:
            # строгий: исключение роняет старт, версия остаётся прежней
            await _teeth_hist_base()
        # ⚠️ Список шага исполняется ВСЕГДА, в том числе у UQ_GUARD_STEP (там он
        # сегодня пуст). Пропустить его значило бы завести МЁРТВЫЙ список:
        # дописанный туда через месяц оператор молча не выполнился бы, а версия
        # схемы записалась бы как выполненная — ровно то, ради чего выше стоит
        # `raise RuntimeError('missing migration step')`. Строгость тут своя и
        # правильная: этот список меняет схему или данные, и падение уместно.
        if steps[v]:
            for sql in steps[v]:
                await _CONN.execute(sql)
            await _CONN.commit()
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
    global _CONN, _SQ
    import aiosqlite
    from . import paths            # ⭐ один разборщик $DATABASE_URL на проект
    path = str(paths.db_file())
    # ⚠️ Локальное имя `sqlite3` — не описка: ниже в этой же функции стоят
    # `except sqlite3.OperationalError`, и они обязаны смотреть на ТОТ
    # драйвер, которым база открыта. Назови переменную иначе — и следующий
    # написанный здесь except снова возьмёт стандартный модуль.
    sqlite3, connector = _sqlite_driver(path)
    _SQ = sqlite3
    _CONN = await aiosqlite.Connection(connector, 64)
    _CONN.row_factory = sqlite3.Row
    # Функции для серверного списка пациентов (`patients_rows`): та же
    # свёртка диакритики и те же «только цифры», что у Python (`fold`,
    # `_digits`: ими разбирается запрос), — иначе «Bălan» запроса и «Bălan»
    # картотеки считались бы разными людьми. Только чтение: регистрируем на
    # единственном соединении, которым ходит `_fetch`.
    await _CONN.create_function("dp_fold", 1, _fold, deterministic=True)
    await _CONN.create_function("dp_digits", 1, _digits, deterministic=True)
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
    await _migrate()
    await _slot_guard_startup()
    await _backfill_activity()
    await seed(seed_rows)


async def close() -> None:
    """Закрыть картотеку (гашение приложения, `main.shutdown`; Т5, 18.10).
    ⛔ Без этого процесс не выходит: поток соединения aiosqlite НЕ фоновый, и
    после остановки uvicorn интерпретатор ждёт его вечно. Закрытие последнего
    соединения сбрасывает `-wal` в базу. Повторный вызов и вызов до `init`
    (восстановление, битый профиль) — ничего не делают."""
    global _CONN
    conn, _CONN = _CONN, None
    if conn is not None:
        await conn.close()


async def backfill_ids(doc_map: dict, svc_map: dict) -> None:
    """Проставляет doctor_id/service_id старым записям по ТЕКУЩЕМУ конфигу
    (имя→id, подпись ro/ru→id). Идемпотентно: трогает только NULL. Записи
    врачей, переименованных ДО этого обновления, остаются с NULL — их
    восстановить не по чему, канва показывает их отдельной колонкой."""
    for name, did in doc_map.items():
        try:
            await _execute(
                "UPDATE appointments SET doctor_id = ? WHERE doctor_id IS NULL AND doctor = ?",
                did, name,
            )
        except Exception as e:  # noqa: BLE001 — конфликт uq_doctor_slot_id на патологии
            log.warning("backfill doctor_id failed for %r: %r", name, e)
            await _CONN.rollback()
    for label, sid_ in svc_map.items():
        try:
            await _execute(
                """UPDATE appointments SET service_id = ?
                   WHERE service_id IS NULL AND service = ? AND source != 'note'""",
                sid_, label,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("backfill service_id failed for %r: %r", label, e)
            await _CONN.rollback()


async def relink_doctor(old_name: str, doctor_id: str) -> int:
    """Переприкрепляет сиротские строки (doctor_id IS NULL, старое имя) к врачу.
    Лечит записи, осиротевшие при переименовании ещё ДО v1.7.1 — включая
    будущие брони, невидимые для проверки занятости."""
    try:
        return await _execute(
            "UPDATE appointments SET doctor_id = ? WHERE doctor_id IS NULL AND doctor = ?",
            doctor_id, old_name,
        )
    except Exception as e:  # noqa: BLE001 — конфликт uq_doctor_slot_id (двойник часа)
        log.warning("relink %r -> %s failed: %r", old_name, doctor_id, e)
        await _CONN.rollback()
        return -1


async def seed(rows: list | None) -> None:
    """Демо-записи (из конфига клиники) — только в пустую БД."""
    if not rows:
        return
    n = await _fetchval("SELECT count(*) FROM appointments")
    if n:
        return
    for row in rows:
        # ⛔ по именам: позиционная распаковка через границу модуля уже
        # разъехалась однажды, молча (см. engine.build_seed_rows)
        await admin_add(**row)


# ---------- пациенты и записи ----------

async def _upsert_patient(session_key: str, name: str, phone: str,
                          lang: str, birth_year: int | None) -> int:
    # Пустой телефон — NULL, и нормализация именно ЗДЕСЬ, в единственной точке
    # записи: строка '' прошла бы фильтр phone IS NOT NULL и совпала бы по
    # цифрам с любым другим безтелефонным (см. _patient_ids_by_digits)
    phone = phone or None
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
    async with _slot_lock():
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
    async with _slot_lock():
        return await _book_locked(pid, service, doctor, starts_at, source,
                                  doctor_id, service_id, duration_min)


async def _book_locked(pid: int, service: str, doctor: str, starts_at: datetime,
                       source: str, doctor_id: str | None,
                       service_id: str | None,
                       duration_min: int) -> int | str | None:
    """Тело брони. Звать ТОЛЬКО под _slot_lock: asyncio.Lock не реентерабелен,
    и create_appointment, которому замок нужен раньше (проверка до создания
    пациента), иначе повис бы на самом себе."""
    # ⚠️ «у пациента уже есть запись» спрашиваем ЗАРАНЕЕ, а не ловим по
    # тексту IntegrityError: SQLite называет в нём колонки, а не индекс, и
    # проверка на 'uq_patient_slot' не срабатывала никогда — дубль пациента
    # показывался регистратуре как «интервал занят у этого врача».
    # Проверка идёт первой: она точнее, чем конфликт врача, и под _slot_lock
    # так же надёжна, как индекс.
    if await _patient_busy_at(pid, starts_at):
        return "dup"
    # интервальная проверка: uq-индексы ловят только одинаковые старты,
    # пересечение 10:00(60') с 10:30(60') обязано отсекаться здесь
    if await _conflicts(doctor_id, doctor, starts_at, duration_min):
        return None
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


def manual_key(digits: str) -> str:
    """Ключ пациента, заведённого с рецепции, — ЕДИНСТВЕННОЕ место, где он
    собирается (08-20: раньше фиша и журнал собирали его каждый сам, и ветка
    «без телефона» жила только у фиши). С цифрами — склейка по номеру, как
    было всегда. Без цифр (галочка «fără telefon») склеивать не по чему — ключ
    уникальный, но того же вида: по префиксу manual: весь код узнаёт «заведён
    вручную».
    ⛔ f"manual:{digits}" с пустыми digits дал бы ОДИН ключ на всех
    безтелефонных: второй такой пациент молча склеился бы с первым, а
    _upsert_patient ещё и переписал бы имя — всплыло бы на подписываемой
    043/e с чужой одонтограммой."""
    return f"manual:{digits}" if digits else f"manual:c{secrets.token_hex(5)}"


async def _patient_ids_by_digits(digits: str) -> list[int]:
    """Пациенты, чей телефон совпадает ПО ЦИФРАМ — независимо от того, каким
    путём человек заведён (tg:… из бота, manual:… с рецепции). Телефон не
    ключ: семья делит номер, поэтому список, а решает вызывающий. Фильтр в
    Python, не в SQL: у SQLite нет regexp, а пациентов у клиники тысячи, не
    миллионы.
    ⛔ Пустые цифры — пустой ответ, и это сторож КЛАССА ошибки, а не удобство:
    пациент без телефона хранит NULL, но одна строка с phone='' (легаси, ручная
    правка базы) — и «все безтелефонные» совпали бы друг с другом по пустой
    строке: запись уехала бы первому попавшемуся."""
    if not digits:
        return []
    rows = await _fetch(
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
    rows = await _fetch("SELECT name FROM patients WHERE id = ?", ids[0])
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
    key = manual_key(digits)
    existing_name, has_bd = None, False
    if len(ids) == 1:
        pid = ids[0]
        rows_p = await _fetch(
            "SELECT name, birth_date FROM patients WHERE id = ?", pid)
        if rows_p:
            existing_name = rows_p[0]["name"]
            has_bd = bool(rows_p[0]["birth_date"])
        r = await _book(pid, service, doctor, starts_at, "manual",
                        doctor_id, service_id, duration_min)
    else:
        r = await create_appointment(
            key, name, phone, "ro", service, doctor, starts_at,
            source="manual", birth_year=birth_year,
            doctor_id=doctor_id, service_id=service_id, duration_min=duration_min,
        )
        pid = await patient_id_by_key(key)
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
                "UPDATE patients SET birth_date = ?, birth_year = ? WHERE id = ?",
                birth_date, birth_year, pid)
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
    _slot_lock. Пересечения по длительности здесь намеренно не ищем: индекс их
    тоже не запрещает, а регистратура ставит пациента к двум врачам подряд.

    ⚠️ `exclude_id` обязателен для ПЕРЕНОСА: визит, переезжающий к другому врачу
    на тот же час, находит сам себя и без него получил бы «у пациента уже есть
    запись на это время» — то есть отказ из-за себя самого."""
    rows = await _fetch(
        f"""SELECT id FROM appointments
           WHERE patient_id = ? AND starts_at = ? AND status IN {_ACT_SQL}
           LIMIT 2""",
        pid, (_iso(starts_at)),
    )
    return any(r["id"] != exclude_id for r in rows)


async def _conflicts(doctor_id: str | None, doctor: str, starts_at: datetime,
                     duration_min: int, exclude_id: int | None = None) -> bool:
    """Пересекается ли интервал с уже занятыми у этого врача. Вызывать ПОД
    _slot_lock — уникальные индексы ловят только совпадающие старты."""
    from datetime import timedelta
    pad = timedelta(minutes=240)
    rows = await _fetch(
        f"""SELECT id, starts_at, duration_min FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL} AND starts_at >= ? AND starts_at < ?""",
        doctor_id or "", doctor, _iso(starts_at - pad), _iso(starts_at + pad),
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
    async with _slot_lock():
        # заметка тоже обязана уважать интервалы (иначе ложится поверх визита)
        if await _conflicts(doctor_id, doctor, starts_at, 60):
            return None
        return await _insert_note(doctor, starts_at, text, doctor_id)


async def _insert_note(doctor: str, starts_at: datetime, text: str,
                       doctor_id: str | None) -> int | None:
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


async def booked_intervals(doctor_key: str, doctor_name: str,
                           start: datetime, end: datetime) -> list:
    """Занятые ИНТЕРВАЛЫ врача: [(старт, длительность_мин)]. Матчим по
    стабильному doctor_id, легаси-строки без id — по снапшоту имени.
    NULL-длительность (записи до v1.8.0) считается 60 минутами."""
    rows = await _fetch(
        f"""SELECT starts_at, duration_min FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL}
             AND starts_at >= ? AND starts_at < ?""",
        doctor_key, doctor_name, _iso(start), _iso(end),
    )
    return [(r["starts_at"], int(r["duration_min"] or 60)) for r in rows]


async def doctor_future_count(doctor_key: str, doctor_name: str,
                              now: datetime) -> int:
    """Сколько живых записей у врача впереди — замок на архивацию (v1.9.0).
    Матчинг тот же, что в booked_intervals: id, легаси-строки — по имени."""
    return await _fetchval(
        f"""SELECT COUNT(*) FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL} AND starts_at >= ?""",
        doctor_key, doctor_name, _iso(now),
    ) or 0


async def my_appointments(session_key: str, now: datetime) -> list:
    # arrived тоже показываем: пациент «в кресле» не должен пропадать из «мои
    # записи»; status нужен движку — у arrived НЕ рисуем кнопку отмены
    return await _fetch(
        f"""SELECT a.id, a.service, a.doctor, a.doctor_id, a.starts_at, a.status
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE p.session_key = ? AND a.status IN {_ACT_SQL} AND a.starts_at > ?
           ORDER BY a.starts_at""",
        session_key, _iso(now),
    )


async def cancel_appointment(session_key: str, appt_id: int) -> int:
    """Отмена ТОЛЬКО своей записи (ownership через session_key)."""
    return await _execute(
        """UPDATE appointments SET status = 'cancelled'
           WHERE id = ? AND status = 'confirmed'
             AND patient_id = (SELECT id FROM patients WHERE session_key = ?)""",
        appt_id, session_key,
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
             AND a.starts_at > ? AND a.starts_at <= ?
             AND a.created_at < ?
             AND (a.reminded_day = 0 OR a.reminded_2h = 0)""",
        _iso(now), _iso(h24), _iso(m30),
    )


async def mark_reminded(appt_id: int, day: bool, soon: bool) -> None:
    await _execute(
        """UPDATE appointments
           SET reminded_day = MAX(reminded_day, ?), reminded_2h = MAX(reminded_2h, ?)
           WHERE id = ?""",
        int(day), int(soon), appt_id,
    )


# ---------- SMS-пакет (S5): очередь напоминаний ----------
#
# Состояние напоминания живёт ЗДЕСЬ (`sms_log`), а не во флагах визита:
# `reminded_day`/`reminded_2h` принадлежат Telegram (tg_due_reminders,
# mark_reminded, сброс при переносе) — SMS их не читает и не пишет. Решения
# «кому и когда» принимает core/sms_loop.py; здесь только выборки и записи.

SMS_QUEUED, SMS_SENT, SMS_DELIVERED = "queued", "sent", "delivered"
SMS_UNDELIVERED, SMS_FAILED, SMS_EXPIRED = "undelivered", "failed", "expired"
SMS_STATES = (SMS_QUEUED, SMS_SENT, SMS_DELIVERED, SMS_UNDELIVERED, SMS_FAILED, SMS_EXPIRED)
# «напомнили» для колокольчика журнала: SMS принята сервером или доставлена.
# Недоставленная (телефон выключен сутки) колокольчик не зажигает: пациент её
# не видел, и стойке лучше позвонить.
_SMS_REMINDED_SQL = "('sent','delivered')"


async def sms_candidates(now: datetime, horizon: datetime) -> list:
    """Визиты, которым может понадобиться SMS: programată (`confirmed` — до
    звонка и после, вид решает `status_view`), с пациентом, у которого есть
    телефон, не архивным и без «Fără remindere SMS», начало в окне. Годность
    номера (мобильный Молдовы) решает правило sms_rule у вызывающего."""
    return await _fetch(
        """SELECT a.id, a.starts_at, a.created_at, a.patient_id,
                  p.phone, p.lang, p.session_key
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status = 'confirmed' AND a.source <> 'note'
             AND a.starts_at > ? AND a.starts_at < ?
             AND p.phone IS NOT NULL AND p.phone <> ''
             AND COALESCE(p.archived, 0) = 0 AND COALESCE(p.sms_off, 0) = 0
           ORDER BY a.starts_at, a.id""",
        _iso(now), _iso(horizon))


async def sms_known_idems(now: datetime, horizon: datetime) -> set:
    """Ключи повтора, по которым строка уже есть, — для визитов окна."""
    rows = await _fetch(
        """SELECT s.idem FROM sms_log s JOIN appointments a ON a.id = s.appt_id
           WHERE a.starts_at > ? AND a.starts_at < ?""", _iso(now), _iso(horizon))
    return {r["idem"] for r in rows}


async def sms_enqueue(appt_id: int, patient_id: int, kind: str, phone: str, text: str,
                      segments: int, idem: str, until_at: datetime) -> bool:
    """Поставить напоминание в очередь. Повтор ключа — молча нет: вторая копия
    программы или второй проход цикла строку не удваивают."""
    n = await _execute(
        """INSERT OR IGNORE INTO sms_log(appt_id, patient_id, kind, phone, text, segments,
                                       idem, state, until_at, created_at, state_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        appt_id, patient_id, kind, phone, text, segments, idem, SMS_QUEUED,
        _iso(until_at), _utcnow_iso(), _utcnow_iso())
    return n > 0


async def sms_queue(limit: int = 50) -> list:
    """Очередь на отправку — с визитом и пациентом, какими они стали к моменту
    отправки: отменённый визит, перенос (другое начало — другой ключ) и
    поставленная после постановки галочка отказа видны здесь, а не в момент
    постановки."""
    return await _fetch(
        """SELECT s.*, a.status AS appt_status, a.starts_at AS visit_at,
                  COALESCE(p.sms_off, 0) AS sms_off, COALESCE(p.archived, 0) AS archived
           FROM sms_log s JOIN appointments a ON a.id = s.appt_id
                JOIN patients p ON p.id = s.patient_id
           WHERE s.state = ? ORDER BY s.created_at, s.id LIMIT ?""",
        SMS_QUEUED, limit)


async def sms_set(sms_id: int, **cols) -> None:
    """Обновить строку: состояние, id сервера, ошибка. `state_at` — при смене
    состояния; остальное как передано."""
    if "state" in cols:
        cols.setdefault("state_at", _utcnow_iso())
    sets = ", ".join(f"{k} = ?" for k in cols)
    await _execute(f"UPDATE sms_log SET {sets} WHERE id = ?", *cols.values(), sms_id)


async def sms_delete(sms_id: int) -> None:
    """Снять строку, которая ещё не уходила: отменённый визит, выключенное
    событие, отказ пациента после постановки. Летописи у неё не было."""
    await _execute("DELETE FROM sms_log WHERE id = ? AND state = ?", sms_id, SMS_QUEUED)


async def sms_drop_kind(kind: str) -> int:
    """Событие выключили в настройках — его очередь снимается целиком."""
    return await _execute("DELETE FROM sms_log WHERE kind = ? AND state = ?", kind, SMS_QUEUED)


async def sms_overdue(now: datetime) -> list:
    """Строки, чьё окно отправки прошло, а SMS так и не ушла: сервер молчал,
    пакет кончился, программа была выключена. Вызывающий переводит их в
    `expired` и пишет летопись с причиной."""
    return await _fetch(
        """SELECT s.*, a.starts_at AS visit_at FROM sms_log s
           LEFT JOIN appointments a ON a.id = s.appt_id
           WHERE s.state = ? AND s.until_at <= ? ORDER BY s.id""",
        SMS_QUEUED, _iso(now))


async def sms_pending(since: datetime) -> list:
    """Принятые сервером, но без конечного состояния — кого опрашивать."""
    return await _fetch(
        """SELECT s.*, a.starts_at AS visit_at FROM sms_log s
           LEFT JOIN appointments a ON a.id = s.appt_id
           WHERE s.state = ? AND s.cloud_id IS NOT NULL AND s.created_at >= ?
           ORDER BY s.id""", SMS_SENT, _iso(since))


async def sms_rows(appt_id: int) -> list:
    """Строки SMS одного визита — карточке визита и проверкам."""
    return await _fetch(
        "SELECT * FROM sms_log WHERE appt_id = ? ORDER BY id", appt_id)


async def sms_by_idem(idem: str) -> dict | None:
    """Строка по ключу повтора — есть ли уже такая SMS (любое состояние)."""
    rows = await _fetch("SELECT * FROM sms_log WHERE idem = ?", idem)
    return rows[0] if rows else None


async def sms_log_sent(patient_id: int, kind: str, phone: str, text: str, segments: int,
                       idem: str, cloud_id: int | None) -> int | None:
    """Уже ОТПРАВЛЕННАЯ мимо очереди SMS («Rechemări», 30.10): строка сразу
    `sent`, без визита (`appt_id NULL` — колокольчик `_SMS_REMINDED_SQL`
    смотрит по визиту и её не видит), окно = момент отправки. Повтор ключа —
    None: первая запись выиграла. Доставку опрашивает штатный цикл."""
    now = _utcnow_iso()
    n = await _execute(
        """INSERT OR IGNORE INTO sms_log(appt_id, patient_id, kind, phone, text, segments,
                                       idem, cloud_id, state, until_at, created_at, state_at)
           VALUES(NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        patient_id, kind, phone, text, segments, idem, cloud_id, SMS_SENT, now, now, now)
    if n <= 0:
        return None
    rows = await _fetch("SELECT id FROM sms_log WHERE idem = ?", idem)
    return int(rows[0]["id"]) if rows else None


async def sms_states_by_kind(kind: str, patient_id: int | None = None) -> list:
    """Ключ, состояние и момент состояния всех SMS вида — `core/recall` сводит
    их со строками списка по ключу (одна выборка на картотеку)."""
    if patient_id is None:
        return await _fetch("SELECT idem, state, state_at FROM sms_log WHERE kind = ?", kind)
    return await _fetch("SELECT idem, state, state_at FROM sms_log WHERE kind = ? AND patient_id = ?",
                        kind, patient_id)


async def sms_counts(day_start: datetime) -> dict:
    """Цифры экрана Setări › SMS: в очереди; ушло и доставлено с начала дня."""
    row = await _fetch(
        """SELECT SUM(state = 'queued') AS queued,
                  SUM(state IN ('sent','delivered','undelivered') AND created_at >= ?) AS today,
                  SUM(state = 'delivered' AND created_at >= ?) AS delivered,
                  SUM(state IN ('failed','expired') AND created_at >= ?) AS failed
           FROM sms_log""", _iso(day_start), _iso(day_start), _iso(day_start))
    r = row[0] if row else {}
    return {k: int(r.get(k) or 0) for k in ("queued", "today", "delivered", "failed")}


async def sms_spent(since: datetime) -> int:
    """Сегменты, ушедшие оператору с `since` (списанные: sent, delivered,
    undelivered) — расход для прогноза остатка."""
    v = await _fetchval(
        """SELECT COALESCE(SUM(segments), 0) FROM sms_log
           WHERE state IN ('sent','delivered','undelivered') AND created_at >= ?""",
        _iso(since))
    return int(v or 0)


async def sms_visits_month(start: datetime, end: datetime) -> int:
    """Сколько визитов с телефоном пациента было в окне — основа прогноза
    расхода в месяц: каждое включённое событие — по SMS на визит."""
    v = await _fetchval(
        """SELECT COUNT(*) FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status <> 'cancelled' AND a.source <> 'note'
             AND a.starts_at >= ? AND a.starts_at < ?
             AND p.phone IS NOT NULL AND p.phone <> ''
             AND COALESCE(p.archived, 0) = 0 AND COALESCE(p.sms_off, 0) = 0""",
        _iso(start), _iso(end))
    return int(v or 0)


# Строка летописи об отказе пациента от SMS — ОДНА на оба места, где его
# отмечают: фишу («Fără remindere SMS») и галочку окна записи («SMS reminder»).
SMS_OFF_EVENT = {True: "Remindere SMS oprite — la cererea pacientului",
                 False: "Remindere SMS pornite din nou"}


async def set_sms_off(pid: int, on: bool) -> bool:
    """«Fără remindere SMS» в фише. Летопись — вызывающий маршрут (он знает,
    кто поставил). Ответ — изменилось ли значение: окно записи пишет строку
    летописи только на перемене, а не на каждой записи."""
    return await _execute(
        "UPDATE patients SET sms_off = ? WHERE id = ? AND COALESCE(sms_off, 0) <> ?",
        int(bool(on)), pid, int(bool(on))) > 0


async def manual_patient_sms_off(phone: str) -> bool | None:
    """`sms_off` пациента, в чью карточку ЛЯЖЕТ ручная запись с этим номером;
    None — карточки ещё нет (запись заведёт новую).

    ⚠️ Правило выбора — то же, что у `admin_add`: ровно одно совпадение по
    цифрам — он; иначе склейка по ключу `manual:<цифры>`. Галочка окна
    показывает ЭТОГО пациента: ребёнок на номере родителя — значит родителя,
    туда же уйдёт и визит. Пишет галочку не этот ответ, а сама запись по id
    созданного визита (`appt_patient_id`), так что разойтись здесь может
    только показ."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    ids = await _patient_ids_by_digits(digits)
    pid = ids[0] if len(ids) == 1 else await patient_id_by_key(manual_key(digits))
    if pid is None:
        return None
    return bool(await _fetchval(
        "SELECT COALESCE(sms_off, 0) FROM patients WHERE id = ?", pid))


async def appt_patient_id(appt_id: int) -> int | None:
    """Пациент записи — по её id (окно записи узнаёт, кому досталась запись)."""
    v = await _fetchval("SELECT patient_id FROM appointments WHERE id = ?", appt_id)
    return int(v) if v is not None else None


# ---------- журнал/поиск/статусы ----------

async def day_appointments(day_start: datetime, day_end: datetime) -> list:
    # has_rec — «консультация записана»: не дата, в _DT_COLS ему не место
    # sms_sent — SMS-напоминание принято сервером или доставлено (S5): второй
    # источник колокольчика «Reminder trimis» рядом с reminded_day Telegram
    # call_result — отметка звонка-подтверждения (`appt_calls`, 03.10): по ней
    # «programată» становится «confirmată» в повестке и списке дня. Ключ
    # первичный — строк не размножает. ⚠️ Не `AS call`: в стандарте SQL это слово занято.
    # ⛔ Тай-брейк `a.id` в ORDER BY несущий, а не косметика. Ничья по
    # (starts_at, doctor) достижима — заметка стойки и визит на одну минуту у
    # одного врача (`_conflicts` заметки не стережёт), две заметки в слоте, — и
    # она тянется ВНИЗ: канва сортирует кластеры устойчиво, то есть наследует
    # порядок базы, а порядок внутри кластера решает `col`/`of`, то есть
    # геометрию блоков. SQLite на практике стабилен, но стандарт не обещает
    # ничего. Без тай-брейка два опроса живого журнала
    # при НЕИЗМЕННОМ дне дали бы разное тело, подмена шла бы каждые 12 секунд —
    # мигание, от которого ушли 08-20, и только у той клиники, где кто-то
    # поставил заметку поверх визита.
    return await _fetch(
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id, a.service_id,
                  a.starts_at, a.duration_min, a.status, a.source,
                  a.reminded_day, a.comment, a.waiting_at, a.arrived_at,
                  p.name, p.phone, p.birth_year,
                  (vr.id IS NOT NULL) AS has_rec, ac.result AS call_result,
                  EXISTS(SELECT 1 FROM sms_log s WHERE s.appt_id = a.id
                         AND s.state IN """ + _SMS_REMINDED_SQL + """) AS sms_sent
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
                LEFT JOIN visit_records vr ON vr.appointment_id = a.id
                LEFT JOIN appt_calls ac ON ac.appointment_id = a.id
           WHERE a.starts_at >= ? AND a.starts_at < ?
           ORDER BY a.starts_at, a.doctor, a.id""",
        _iso(day_start), _iso(day_end),
    )


async def appointment_days(start: datetime, end: datetime) -> list:
    """Записи окна ТРЕМЯ колонками — для точек мини-календаря (08.10): день,
    в который есть хоть одна живая запись. Полная выборка `day_appointments`
    на шесть недель тянула бы пациентов и визиты ради одной даты на строку.
    Что считается живой записью (без отменённых и заметок стойки), решает
    вызывающий, как и у повестки: правило одно, живёт рядом с выборкой дня."""
    # doctor_id/doctor — точки календаря в шапке дня ОДНОГО врача (22.10): его
    # записи отбирает `routes._of_doctor`, тем же правилом, что и сам день
    return await _fetch(
        """SELECT starts_at, status, source, doctor_id, doctor FROM appointments
           WHERE starts_at >= ? AND starts_at < ?""",
        _iso(start), _iso(end),
    )


async def day_patient_facts(pids: list, before: datetime) -> dict:
    """Что карточка визита дня ОДНОГО врача знает о его пациентах (22.10,
    вариант A Олега): прошлые визиты с графой «Tratament» дневника,
    предупреждения фиши, анамнез, активный план.

    ⭐ ЧЕТЫРЕ выборки на весь день по списку пациентов, а не запрос на визит:
    день врача с двенадцатью визитами стоил бы полсотни запросов на каждое
    открытие и на каждый ответ действия (`_done` отдаёт свежий день).
    Визиты — только до `before` (конец дня экрана): прошлое ЭТОГО дня, а не
    сегодняшнего, поэтому ответ зависит от данных, а не от часов.
    Отменённые и неявки визитом не считаются; заметок здесь нет (у них нет
    пациента). Активный план — перечислением (`PLAN_ACTIVE`).
    ⛔ Денег здесь нет (Олег 22.10: «не думаю что врачу эта информация
    нужна»): долг живёт в фише и у статистики, на дне врача его не видит и
    директор.
    """
    if not pids:
        return {"visits": {}, "alerts": {}, "anam": {}, "plan": {}}
    lite = ",".join("?" for _ in pids)
    act = ",".join("?" for _ in PLAN_ACTIVE)
    visits: dict[int, list] = {}
    for r in await _fetch(
            f"""SELECT a.id, a.patient_id, a.starts_at, a.service, vr.tratament
                FROM appointments a LEFT JOIN visit_records vr ON vr.appointment_id = a.id
                WHERE a.patient_id IN ({lite}) AND a.starts_at < ?
                  AND a.status NOT IN ('cancelled', 'noshow')
                ORDER BY a.starts_at, a.id""", *pids, _iso(before)):
        visits.setdefault(r["patient_id"], []).append(r)
    alerts: dict[int, list] = {}
    for r in await _fetch(
            f"SELECT patient_id, kind, text FROM patient_alerts WHERE patient_id IN ({lite}) "
            "ORDER BY id", *pids):
        alerts.setdefault(r["patient_id"], []).append(r)
    # created_at/updated_at — дата опроса для «neagă afecțiunile» дня врача
    anam = {r["patient_id"]: r for r in await _fetch(
        f"""SELECT patient_id, flags, boli, medicamente, alergii, anestezie,
                   created_at, updated_at
            FROM anamneza WHERE patient_id IN ({lite})""", *pids)}
    plan: dict[int, list] = {}
    for r in await _fetch(
            f"""SELECT patient_id, tooth, procedure, status FROM plan_items
                WHERE patient_id IN ({lite}) AND status IN ({act}) ORDER BY id""",
            *pids, *PLAN_ACTIVE):
        plan.setdefault(r["patient_id"], []).append(r)
    return {"visits": visits, "alerts": alerts, "anam": anam, "plan": plan}


_PLIST_COLS = ("id, name, phone, email, session_key, birth_year, birth_date, "
               "gender, insurance, primary_doctor, file_no, notes, created_at, "
               "archived")


async def all_patients() -> list:
    """Живые (не архивные) пациенты клиники строками — для рабочих списков
    стойки на главной (`schedule/desk`), которые сводят их с `patients_visits`
    и `patients_debt` сами. Список «Pacienți» отбирает в SQL (`patients_rows`)."""
    return await _fetch(
        f"""SELECT {_PLIST_COLS} FROM patients
            WHERE COALESCE(archived, 0) = 0 ORDER BY id""")


async def patients_visits(now: datetime) -> list:
    """По пациенту: последний прошедший визит, ближайший будущий и сколько
    всего (отменённые не в счёт). Один проход по таблице вместо запроса на
    каждую строку списка — иначе страница пациентов стоила бы сотню запросов.
    Заметки-блокировки сюда не попадают: у них patient_id = NULL."""
    return await _fetch(
        f"""SELECT patient_id,
                   MAX(CASE WHEN starts_at <= ? THEN starts_at END) AS last_at,
                   MIN(CASE WHEN starts_at > ? AND status IN {_ACT_SQL}
                            THEN starts_at END) AS next_at,
                   COUNT(*) AS n_visits
              FROM appointments
             WHERE patient_id IS NOT NULL AND status <> 'cancelled'
             GROUP BY patient_id""",
        _iso(now), _iso(now),
    )


async def patients_debt() -> dict:
    """Долг каждого пациента: финализированный план − оплачено. Минус = аванс.

    Та же формула, что в `patient_finance`, но на всю картотеку двумя запросами
    вместо двух НА ПАЦИЕНТА (рабочие списки стойки зовут это раз на главную).
    Полного внешнего соединения в SQLite нет, поэтому две выборки сводятся в
    Python — заодно не приходится писать двум диалектам разный SQL.
    """
    chg = ("SELECT patient_id, COALESCE(SUM(price_mdl), 0) AS n FROM plan_items "
           "WHERE status = 'finalizat' GROUP BY patient_id")
    pay = ("SELECT patient_id, COALESCE(SUM(amount_mdl), 0) AS n FROM payments "
           "GROUP BY patient_id")
    out: dict[int, int] = {}
    for r in await _fetch(chg):
        out[r["patient_id"]] = int(r["n"] or 0)
    for r in await _fetch(pay):
        out[r["patient_id"]] = out.get(r["patient_id"], 0) - int(r["n"] or 0)
    return out


# ---------- рабочие списки регистратуры на главной (01.10, schedule/desk) ----------

async def plan_open_summary() -> list:
    """Активный план по пациенту: сколько позиций, на какую сумму и с какого
    дня висит — список «Plan fără programare». ⚠️ Псевдоним даты —
    `created_at` (он в `_DT_COLS`): иначе в SQLite MIN() остался бы строкой
    (прайор 08-06). Активное — перечислением, как везде."""
    sql = ("SELECT patient_id, COUNT(*) AS n, COALESCE(SUM(price_mdl), 0) AS total, "
           "MIN(created_at) AS created_at FROM plan_items "
           "WHERE status IN ('planificat', 'in_lucru') GROUP BY patient_id")
    return await _fetch(sql)


async def appt_calls(ids: list) -> dict:
    """Отметки звонка-подтверждения по визитам: {appointment_id: строка}."""
    if not ids:
        return {}
    lite = ",".join("?" for _ in ids)
    rows = await _fetch(
        f"SELECT appointment_id, result, actor, at FROM appt_calls WHERE appointment_id IN ({lite})",
        *ids)
    return {r["appointment_id"]: r for r in rows}


async def set_appt_call(aid: int, result: str) -> None:
    """«ok» — дозвонились, визит подтверждён; «noanswer» — не ответил;
    пустое — снять отметку. Автор — вошедший (ACTOR_HOOK), как в летописи."""
    if not result:
        await _execute("DELETE FROM appt_calls WHERE appointment_id = ?", aid)
        return
    now = datetime.now(timezone.utc)
    await _execute(
        """INSERT INTO appt_calls(appointment_id, result, actor, at) VALUES(?, ?, ?, ?)
           ON CONFLICT(appointment_id) DO UPDATE SET result = excluded.result,
             actor = excluded.actor, at = excluded.at""",
        aid, result, _actor_now(), _iso(now))


# ---------- «Rechemări» (29.10): выборки для core/recall ----------
#
# Правило списка живёт в `core/recall.py` чистой функцией; здесь только
# выборки, каждая — одним запросом на всю картотеку (раздел едет в конверте
# живого канала главной, опрос постоянный).

async def recall_done_last(service_ids: list, patient_id: int | None = None) -> list:
    """Последний ЗАВЕРШЁННЫЙ визит каждой пары (пациент, услуга) по услугам со
    сроком: `aid` — его id (цикл отметок), `last_at` — его начало (псевдоним
    в _DT_COLS: иначе SQLite отдал бы строку). Только `done`: неявка, отмена и
    «programată» часы отзыва не заводят. Архивные (и обезличенные — у них
    archived=1) не участвуют.
    ⚠️ Голые колонки при MAX() SQLite берёт из строки максимума — это
    документированное поведение, на нём и держится `aid`/`doctor`."""
    if not service_ids:
        return []
    lite = ",".join("?" for _ in service_ids)
    one = " AND a.patient_id = ?" if patient_id is not None else ""
    args = [*service_ids] + ([patient_id] if patient_id is not None else [])
    return await _fetch(
        f"""SELECT a.patient_id, a.service_id, a.id AS aid, a.doctor,
                   MAX(a.starts_at) AS last_at,
                   p.name, p.phone, p.email, COALESCE(p.lang, 'ro') AS lang,
                   COALESCE(p.sms_off, 0) AS sms_off
              FROM appointments a JOIN patients p ON p.id = a.patient_id
             WHERE a.status = 'done' AND a.service_id IN ({lite})
               AND COALESCE(p.archived, 0) = 0{one}
             GROUP BY a.patient_id, a.service_id""", *args)


async def recall_future(day_start: datetime) -> list:
    """Ближайшая будущая ЖИВАЯ запись каждой пары (пациент, услуга) от начала
    дня: записанный вперёд на ту же услугу из списка уходит, на другую —
    получает пометку. Граница — начало дня, не «сейчас» (конверт живого канала
    обязан быть одинаковым весь день)."""
    return await _fetch(
        f"""SELECT patient_id, service_id, service, MIN(starts_at) AS next_at
              FROM appointments
             WHERE patient_id IS NOT NULL AND status IN {_ACT_SQL} AND starts_at >= ?
             GROUP BY patient_id, service_id""", _iso(day_start))


async def recall_marks(patient_id: int | None = None) -> list:
    """Все отметки обзвона по порядку записи (одного пациента или всей
    картотеки): действующую выбирает `core/recall` по последней строке и
    циклу, здесь ничего не интерпретируется."""
    if patient_id is None:
        return await _fetch("SELECT * FROM recall_marks ORDER BY id")
    return await _fetch("SELECT * FROM recall_marks WHERE patient_id = ? ORDER BY id",
                        patient_id)


async def recall_contacts_since(since_iso: str) -> list:
    """Отметки «sunat — revine»/«e-mail trimis»/«SMS trimis» (30.10, В7 = А) с
    момента `since_iso` (UTC ISO): пара (пациент, услуга) и её ПЕРВАЯ такая
    отметка в окне — для статистики «contactați · programați» (журнал
    читается, не интерпретируется)."""
    return await _fetch(
        """SELECT patient_id, service_id, MIN(at) AS at
             FROM recall_marks WHERE result IN ('contacted', 'emailed', 'sms') AND at >= ?
            GROUP BY patient_id, service_id""", since_iso)


async def recall_bookings_since(since_iso: str) -> list:
    """Записи (живые или завершённые), СОЗДАННЫЕ с `since_iso`, по парам
    (пациент, услуга) с ПОСЛЕДНЕЙ датой создания: «после отметки создана
    запись» ⇔ последняя созданная позже отметки (первая была бы визитом,
    который сам список и завёл). Сравнивает core/recall, не SQL."""
    return await _fetch(
        f"""SELECT patient_id, service_id, MAX(created_at) AS created_at
              FROM appointments
             WHERE patient_id IS NOT NULL AND created_at >= ?
               AND status IN ('confirmed', 'waiting', 'arrived', 'done')
             GROUP BY patient_id, service_id""", since_iso)


async def add_recall_mark(patient_id: int, service_id: str, cycle: int | None,
                          result: str, until: str = "") -> None:
    """Дописать отметку (журнал, не состояние). Автор — вошедший
    (ACTOR_HOOK), как у отметки звонка; время — UTC программы."""
    await _execute(
        """INSERT INTO recall_marks(patient_id, service_id, cycle_appt_id, result,
                                    until_date, actor, at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        patient_id, service_id, cycle, result, until or None, _actor_now(),
        _iso(datetime.now(timezone.utc)))


# ---------- список пациентов: поиск, фильтры, порядок и страница — в SQL ----------
#
# Экран «Pacienți» (`/api/patients`) и книга `/admin/patients.xlsx` отбирают
# ОДНОЙ выборкой: агрегаты (визиты, предупреждения, план, долг) — подзапросы,
# соединённые с patients, чтобы WHERE, ORDER BY и LIMIT считала база. Отбор
# словарём собирает модуль (`routes._pl_select`), статус строки выводит он же
# (`_pl_status`). ⭐ До 13.10 то же правило жило ещё и в Python старой страницы
# (паритет держал набор); она снята, и правило отбора теперь одно.


def _digits(s) -> str:
    """Только цифры — телефон «069-12 34» и «0691234» обязаны совпадать."""
    return "".join(ch for ch in (s or "") if ch.isdigit())


# врач последнего визита (включая будущий): подзапрос по индексу patient_id,
# а не оконная функция по всей таблице — на 20 000 записей она стоила ~50 мс
# на КАЖДЫЙ запрос списка, а нужна двадцати строкам страницы (и всем — только
# под фильтром по врачу)
_PL_LAST_DOC_OF = ("(SELECT a.doctor FROM appointments a WHERE a.patient_id = p.id "
                   "AND a.status <> 'cancelled' ORDER BY a.starts_at DESC LIMIT 1)")
# врач строки: медик курант из фиши, а если его не проставили — тот, кто вёл
# последний визит (так его показывают экран и книга Excel): `primary_doctor`
# проставляют руками, и без запасного колонка «Medic» пустовала бы почти у
# всех, хотя врач у пациента фактически есть — тот, к кому он ходит
_PL_DOCTOR = f"COALESCE(NULLIF(p.primary_doctor, ''), {_PL_LAST_DOC_OF}, '')"
# долг = финализированный план − оплачено; минус — аванс (как `patients_debt`)
_PL_DEBT = "(COALESCE(chg.n, 0) - COALESCE(pay.n, 0))"
# канал по префиксу ключа — как `_pl_canal`; substr, а не LIKE: у LIKE в SQLite
# регистр не в счёт, а ключи сравниваются буква в букву
_PL_CANAL = ("CASE WHEN substr(p.session_key, 1, 3) = 'tg:' THEN 'tg' "
             "WHEN substr(p.session_key, 1, 7) = 'manual:' THEN 'manual' "
             "ELSE 'web' END")
# pl — «в лечении»: активные статусы ПОИМЁННО (те же, что PLAN_ACTIVE), а не
# «<> finalizat»: отказанная позиция закрыта, и пациент с одним отказом не
# находится в лечении
_PL_FROM = f"""
      FROM patients p
      LEFT JOIN (SELECT patient_id,
                        MAX(CASE WHEN starts_at <= {{now1}} THEN starts_at END) AS last_at,
                        MIN(CASE WHEN starts_at > {{now2}} AND status IN {_ACT_SQL}
                                 THEN starts_at END) AS next_at,
                        COUNT(*) AS n_visits
                   FROM appointments
                  WHERE patient_id IS NOT NULL AND status <> 'cancelled'
                  GROUP BY patient_id) v ON v.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COUNT(*) AS n FROM patient_alerts
                  GROUP BY patient_id) al ON al.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COUNT(*) AS n FROM plan_items
                  WHERE status IN ('planificat', 'in_lucru')
                  GROUP BY patient_id) pl ON pl.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COALESCE(SUM(price_mdl), 0) AS n FROM plan_items
                  WHERE status = 'finalizat' GROUP BY patient_id) chg ON chg.patient_id = p.id
      LEFT JOIN (SELECT patient_id, COALESCE(SUM(amount_mdl), 0) AS n FROM payments
                  GROUP BY patient_id) pay ON pay.patient_id = p.id"""
_PL_COLS = ("p.id, p.name, p.phone, p.email, p.session_key, p.birth_year, p.birth_date, "
            "p.gender, p.primary_doctor, p.file_no, p.notes, p.created_at, p.archived, "
            "v.last_at, v.next_at, COALESCE(v.n_visits, 0) AS n_visits, "
            "COALESCE(al.n, 0) AS n_alerts, COALESCE(pl.n, 0) AS n_plan, "
            f"{_PL_LAST_DOC_OF} AS last_doctor, {_PL_DEBT} AS debt, "
            # счёт всего отбора той же выборкой: второй проход по агрегатам
            # ради COUNT(*) стоил столько же, сколько сама страница
            "COUNT(*) OVER () AS total")
_PL_ORDER = {
    "name": "{fold_name}, p.id",
    "new": "p.created_at DESC, p.id",
    "debt": _PL_DEBT + " DESC, p.id",
    # по последнему визиту; кто ещё не был — в конце, в порядке заведения
    "last": "(v.last_at IS NULL), v.last_at DESC, p.id",
}


# Как пишутся куски отбора: архив (0/1), свёртка диакритики и «только цифры»
# (функции dp_fold/dp_digits, регистрирует init), «содержит», заполнитель и
# вид даты.
_PL_DIALECT = {"arch": "COALESCE(p.archived, 0) <> 0",
               "fold": lambda col: f"dp_fold({col})",
               "digits": lambda col: f"dp_digits({col})",
               "has": lambda hay, needle: f"instr({hay}, {needle}) > 0",
               "ph": lambda n: "?", "dt": _iso}


class _PlQuery:
    """Текст запроса списка и его аргументы по порядку.

    `f` — отбор словарём (см. `patients_count`): q/terms, med, st, ch, dat,
    show_archived, stale_cut, now. Каждое значение добавляется ровно там, где
    стоит его заполнитель в тексте.
    """

    def __init__(self, f: dict):
        self.d = _PL_DIALECT
        self.args: list = []
        d = self.d
        self.base = _PL_FROM.format(now1=self.arg(f["now"], dt=True),
                                    now2=self.arg(f["now"], dt=True))
        conds = []
        if not f.get("show_archived"):
            conds.append(f"NOT ({d['arch']})")
        if f.get("q"):
            t = f.get("terms") or {}
            alts = []
            if t.get("fold"):
                for col in ("p.name", "p.email", "p.file_no"):
                    alts.append(d["has"](d["fold"](col), self.arg(t["fold"])))
            if t.get("birth"):
                alts.append(f"substr(COALESCE(p.birth_date, ''), 1, 10) = "
                            f"{self.arg(t['birth'])}")
            if t.get("digits"):
                # notes — номер второго человека на семейном телефоне (решение
                # 08-18). ⚠️ РАЗДЕЛЬНО от телефона, не общей строкой: на стыке
                # «конец телефона + начало заметки» находились бы номера,
                # которых нет
                for col in ("p.phone", "p.notes"):
                    alts.append(d["has"](d["digits"](col), self.arg(t["digits"])))
            # запрос без единого пригодного куска (одна буква) не находит
            # никого
            conds.append("(" + " OR ".join(alts) + ")" if alts else "1 = 0")
        med = f.get("med") or ""
        if med == "-":
            conds.append(f"{_PL_DOCTOR} = ''")
        elif med:
            conds.append(f"{_PL_DOCTOR} = {self.arg(med)}")
        st = f.get("st") or ""
        if st == "arhivat":
            conds.append(d["arch"])
        elif st == "atentie":
            conds.append("COALESCE(al.n, 0) > 0")
        elif st == "tratament":
            conds.append("COALESCE(pl.n, 0) > 0")
        elif st == "inactiv":
            conds.append(f"(v.last_at IS NULL OR v.last_at <= "
                         f"{self.arg(f['stale_cut'], dt=True)})")
        elif st == "activ":
            conds.append(f"(v.last_at IS NOT NULL AND v.last_at > "
                         f"{self.arg(f['stale_cut'], dt=True)})")
        if f.get("ch"):
            conds.append(f"{_PL_CANAL} = {self.arg(f['ch'])}")
        # ноль — ни в долг, ни в аванс: рассчитавшийся пациент не должен
        # всплывать в списке, который регистратура открывает, чтобы звонить
        if f.get("dat") == "da":
            conds.append(f"{_PL_DEBT} > 0")
        elif f.get("dat") == "avans":
            conds.append(f"{_PL_DEBT} < 0")
        if conds:
            self.base += "\n     WHERE " + "\n       AND ".join(conds)

    def arg(self, value, *, dt: bool = False) -> str:
        self.args.append(self.d["dt"](value) if dt else value)
        return self.d["ph"](len(self.args))

    def page_sql(self, sort: str, limit: int | None, offset: int) -> str:
        order = _PL_ORDER.get(sort, _PL_ORDER["last"]).format(
            fold_name=self.d["fold"]("p.name"))
        sql = f"SELECT {_PL_COLS}{self.base}\n     ORDER BY {order}"
        if limit is None:          # книга Excel: вся выборка, а не страница
            return sql
        return sql + f"\n     LIMIT {self.arg(limit)} OFFSET {self.arg(offset)}"


async def patients_count(f: dict) -> int:
    """Сколько строк проходит отбор `f` — знаменатель страниц.

    Отбор: `q` с разобранными кусками `terms` (fold / birth / digits — что
    именно ищется, решает модуль, `_pl_terms`), `med` (имя врача или «-» =
    без врача), `st` (arhivat / atentie / tratament / inactiv / activ,
    включающий), `ch` (tg / manual / web), `dat` (da / avans),
    `show_archived`, `stale_cut` (последний визит не позже — неактивен),
    `now` (граница прошлого и будущего визита).
    """
    q = _PlQuery(f)
    n = await _fetchval(f"SELECT COUNT(*){q.base}", *q.args)
    return int(n or 0)


async def patients_rows(f: dict, sort: str, limit: int | None, offset: int) -> list:
    """Страница списка: строки с агрегатами (`last_at`, `next_at`, `n_visits`,
    `n_alerts`, `n_plan`, `last_doctor`, `debt`) в порядке `sort`
    (last / name / new / debt) и с `total` — счётом всего отбора в каждой
    строке (окно). Пустая страница счёта не несёт: тогда `patients_count`.
    `limit=None` — вся выборка (книга Excel). Статус строки выводит модуль
    (`_pl_status`)."""
    q = _PlQuery(f)
    sql = q.page_sql(sort, limit, offset)
    return await _fetch(sql, *q.args)


async def patients_doctors() -> list[str]:
    """Врачи, по которым список можно отобрать: тот же вывод, что у колонки
    «Medic» (медик курант, иначе врач последнего визита)."""
    sql = f"SELECT DISTINCT {_PL_DOCTOR} AS doctor FROM patients p"
    return sorted(r["doctor"] for r in await _fetch(sql) if r["doctor"])


async def patients_archived() -> int:
    """Сколько фиш в архиве — для подсказки «N arhivați» под списком."""
    return int(await _fetchval(
        "SELECT COUNT(*) FROM patients WHERE COALESCE(archived, 0) <> 0") or 0)


async def patients_have_tg() -> bool:
    """Есть ли пациенты из бота — фильтр канала «Telegram» идёт ПО ДАННЫМ."""
    sql = "SELECT COUNT(*) FROM patients WHERE substr(session_key, 1, 3) = 'tg:'"
    return bool(await _fetchval(sql))


async def patients_counts(month_start: datetime, prev_start: datetime) -> dict:
    """Числа над списком: живых, в архиве, новых за этот месяц и за прошлый.
    Новые считаются по всей картотеке, включая архив, — как на странице."""
    lt = """SELECT SUM(CASE WHEN COALESCE(archived, 0) <> 0 THEN 0 ELSE 1 END) AS n_total,
                   SUM(CASE WHEN COALESCE(archived, 0) <> 0 THEN 1 ELSE 0 END) AS n_arh,
                   SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS n_new,
                   SUM(CASE WHEN created_at >= ? AND created_at < ?
                            THEN 1 ELSE 0 END) AS n_new_prev
              FROM patients"""
    rows = await _fetch(lt, _iso(month_start), _iso(prev_start), _iso(month_start))
    r = rows[0] if rows else {}
    return {k: int(r.get(k) or 0) for k in ("n_total", "n_arh", "n_new", "n_new_prev")}


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
        sql.format("?", "?"),
        _iso(start), _iso(end),
    )


async def patient_id_by_key(session_key: str) -> int | None:
    """Есть ли уже пациент с таким ключом. Нужен до создания карточки вручную:
    `_upsert_patient` при совпадении ПЕРЕЗАПИСАЛ бы имя существующего, и
    «Ion Popescu» тихо стал бы «Ion P.» из-за общего семейного номера."""
    return await _fetchval(
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
        "UPDATE patients SET archived = ? WHERE id = ?",
        int(on), pid,
    )


async def patient_lang(session_key: str) -> str | None:
    """Язык пациента — чтобы после рестарта отвечать возвращённому на его языке."""
    return await _fetchval(
        "SELECT lang FROM patients WHERE session_key = ?",
        session_key,
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
           FROM appointments WHERE patient_id = ?
           ORDER BY starts_at DESC LIMIT ?""",
        patient_id, limit,
    )


# ---------- карточка пациента (v1.6.0: A2 зубы+план, A4 документы) ----------

PATIENT_FIELDS = ["name", "phone", "birth_date", "gender", "idnp", "email",
                  "address", "insurance", "primary_doctor", "file_no", "notes"]


async def get_patient(pid: int) -> dict | None:
    cols = ("id, session_key, name, phone, lang, birth_year, created_at, archived, sms_off, "
            + ", ".join(PATIENT_FIELDS[2:]))
    rows = await _fetch(
        f"SELECT {cols} FROM patients WHERE id = ?", pid)
    return rows[0] if rows else None


async def update_patient(pid: int, data: dict) -> None:
    await log_event(pid, "profile", "Fișa pacientului a fost actualizată")
    """Обновление профиля: только известные поля, явным списком колонок."""
    sets_lt =", ".join(f"{f} = ?" for f in PATIENT_FIELDS)
    vals = [data.get(f) for f in PATIENT_FIELDS]
    await _execute(
        f"UPDATE patients SET {sets_lt} WHERE id = ?",
        *vals, pid,
    )


async def set_primary_doctor(pid: int, name: str | None) -> None:
    """Медик курант одним полем (шапка фиши, 14.10) — мимо `update_patient`,
    который пишет ВСЕ поля профиля и стёр бы остальные. None — снять."""
    await log_event(pid, "profile", f"Medic curant: {name}" if name else "Medic curant scos")
    await _execute("UPDATE patients SET primary_doctor = ? WHERE id = ?", name, pid)


async def set_birth_year(pid: int, year: int | None) -> None:
    """Синк года из birth_date: возраст в поиске/сетке считается по birth_year.
    None стирает год — так очищенная дата рождения забирает с собой и возраст."""
    await _execute(
        "UPDATE patients SET birth_year = ? WHERE id = ?",
        year, pid,
    )


async def patient_alerts(pid: int) -> list:
    return await _fetch(
        "SELECT id, kind, text FROM patient_alerts WHERE patient_id = ? ORDER BY id", pid)


async def add_alert(pid: int, kind: str, text: str) -> None:
    await log_event(pid, "alert_add", f"Atenționare adăugată: {text}")
    await _execute(
        "INSERT INTO patient_alerts(patient_id, kind, text, created_at) VALUES(?, ?, ?, ?)",
        pid, kind, text, _utcnow_iso(),
    )


async def delete_alert(alert_id: int, pid: int) -> bool:
    """Снять предупреждение. След в летописи обязателен: снятая аллергия на
    пенициллин — клинически значимое событие, и «кто её снял» спросят громче,
    чем «кто записал» (до 24.09 удаление не оставляло строки вовсе). Летопись
    — ПОСЛЕ DELETE и только за реально снятую строку, как у `delete_bridge`.
    False — у пациента такого предупреждения нет (чужое, выдуманное, уже
    снятое с другого места)."""
    rows = await _fetch(
        "SELECT text FROM patient_alerts WHERE id = ? AND patient_id = ?", alert_id, pid)
    if not rows:
        return False
    n = await _execute(
        "DELETE FROM patient_alerts WHERE id = ? AND patient_id = ?", alert_id, pid)
    if n != 1:
        return False
    await log_event(pid, "alert_del", f"Atenționare ștearsă: {rows[0]['text']}")
    return True


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
            """INSERT INTO activity(patient_id, at, actor, kind, tooth, text)
               VALUES(?, ?, ?, ?, ?, ?)""",
            patient_id, _utcnow_iso(), actor, kind, tooth,
               text[:EVENT_TEXT_MAX],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("activity %s/%s failed: %r", patient_id, kind, e)


async def log_clinic_event(kind: str, text: str, actor: str = "sistem") -> None:
    """Событие УРОВНЯ КЛИНИКИ — patient_id NULL. Попадает в ленту «Activitate
    recentă» (её LEFT JOIN такие строки переживает), но ни в одну фишу:
    фишам чужие события не принадлежат."""
    try:
        await _execute(
            """INSERT INTO activity(patient_id, at, actor, kind, text)
               VALUES(NULL, ?, ?, ?, ?)""",
            _utcnow_iso(), actor, kind, text[:EVENT_TEXT_MAX],
        )
    except Exception as e:  # noqa: BLE001 — летопись не роняет операцию
        log.warning("clinic event %s failed: %r", kind, e)


async def _log_booking(pid: int, service: str, doctor: str,
                       starts_at: datetime, source: str) -> None:
    """Событие «записался» — одно на все пути брони, поэтому вынесено."""
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
               WHERE patient_id = ? ORDER BY at DESC, id DESC LIMIT ?""",
            pid, limit)
    return await _fetch(
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
           ORDER BY a.at DESC, a.id DESC LIMIT ?""", limit)


async def tooth_activity(pid: int) -> list:
    """События по зубам — для истории конкретного зуба в диалоге."""
    return await _fetch(
        """SELECT at, actor, tooth, text FROM activity
           WHERE patient_id = ? AND tooth IS NOT NULL ORDER BY at DESC, id DESC""", pid)


async def tooth_records_since(pid: int, since: datetime) -> list:
    """Строки летописи по зубам и мостам С мгновения `since`, свежие первыми, —
    «сравнить с визитом» для даты раньше начала истории зубов (25.10): там
    состояния на ту дату нет, и экран показывает ДОСЛОВНО, что записывали
    после, а не догадку о том, каким зуб был. Мосты в летописи без номера
    зуба (`kind` 'bridge'), поэтому идут отдельным условием."""
    return await _fetch(
        """SELECT at, tooth, text FROM activity
           WHERE patient_id = ? AND (tooth IS NOT NULL OR kind = 'bridge') AND at >= ?
           ORDER BY at DESC, id DESC""", pid, _iso(since))


async def _backfill_activity() -> None:
    """Разовый перенос уже существующих визитов в журнал: иначе у клиники,
    которая работает полгода, таймлайн стартует с пустого места, хотя история
    визитов у нас есть. Идемпотентно — отмечается флагом в schema_meta."""
    done = await _fetchval("SELECT value FROM schema_meta WHERE key = 'act_backfill'")
    if done:
        return
    rows = await _fetch(
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
               VALUES(?, ?, ?, ?, ?)""",
            r["patient_id"], _iso(r["created_at"]) if hasattr(r["created_at"], "strftime")
               else str(r["created_at"]),
               "bot" if r["source"] == "bot" else "recepție", "appt_new", txt[:200],
        )
        n += 1
    await _execute(
        """INSERT INTO schema_meta(key, value) VALUES('act_backfill', ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""", str(n))
    if n:
        log.warning("activity backfill: %s programări перенесены в журнал", n)


async def teeth_map(pid: int) -> dict:
    rows = await _fetch(
        """SELECT tooth, state, note, doctor, surfaces, surface_states, marks,
                  updated_at FROM teeth WHERE patient_id = ?""",
        pid)
    return {r["tooth"]: r for r in rows}


async def teeth_hist_since() -> datetime | None:
    """Начало истории зубов (UTC); None — метки нет, и тогда карту на дату не
    знаем НИКОГДА: «нет данных» честнее догадки."""
    v = await get_meta(TEETH_HIST_SINCE)
    try:
        return _parse_dt(v) if v else None
    except ValueError:
        log.warning("%s unreadable: %r", TEETH_HIST_SINCE, v)
        return None


async def teeth_map_at(pid: int, before: datetime) -> dict:
    """Карта зубов (вид `teeth_map`) такой, какой она была до мгновения
    `before`: последний снимок каждого зуба из `teeth_history`. Верна только
    при `before` не раньше `teeth_hist_since()` — это проверяет вызывающий.
    ⚠️ Последний — по id, а не по `at`: снимки дописываются по ходу записи, и
    id растёт вместе с ними даже там, где часы машины шагнули назад."""
    rows = await _fetch(
        """SELECT tooth, state, note, doctor, surfaces, surface_states, marks,
                  at AS updated_at FROM teeth_history
           WHERE id IN (SELECT MAX(id) FROM teeth_history
                        WHERE patient_id = ? AND at < ? GROUP BY tooth)
             AND state IS NOT NULL""", pid, _iso(before))
    return {r["tooth"]: r for r in rows}


async def teeth_history_rows(pid: int) -> list:
    """История зубов пациента целиком, по порядку записи — выгрузка по 195-му
    (состав выгрузки = состав удаления, `_PATIENT_CHILD_TABLES`). `state`
    None — строки зуба не было (здоров); `src` 'base' — снимок шага 6."""
    return await _fetch(
        """SELECT tooth, at, state, note, doctor, surfaces, surface_states, marks, src
           FROM teeth_history WHERE patient_id = ? ORDER BY id""", pid)


async def bridges_removed_rows(pid: int) -> list:
    """Снятые мосты пациента — выгрузка по 195-му, как `teeth_history_rows`."""
    return await _fetch(
        """SELECT bridge_id, teeth, material, doctor, created_at, removed_at
           FROM bridges_removed WHERE patient_id = ? ORDER BY id""", pid)


async def bridges_at(pid: int, before: datetime) -> list:
    """Мосты (вид `bridges`), стоявшие до мгновения `before`: поставленные
    раньше и ещё стоящие плюс снятые позже. Мост, снятый до начала истории,
    к такому мгновению уже не стоял — для дат после `teeth_hist_since()`
    ответ полный."""
    b = _iso(before)
    return await _fetch(
        """SELECT id, teeth, material, doctor, created_at FROM bridges
           WHERE patient_id = ? AND created_at < ?
           UNION ALL
           SELECT bridge_id AS id, teeth, material, doctor, created_at
           FROM bridges_removed
           WHERE patient_id = ? AND created_at < ? AND removed_at >= ?
           ORDER BY id""", pid, b, pid, b, b)


async def set_tooth(pid: int, tooth: int, state: str, note: str,
                    doctor: str = "", surfaces: str | None = None,
                    sfmap: dict | None = None, state0: str | None = None,
                    marks: list | None = None) -> None:
    """Запись одного зуба (`POST /api/patients/{pid}/teeth/{n}`). Что ляжет в
    строку и в летопись, решает `_tooth_next`; замок — тот же, что у записи
    пачкой (`set_teeth`): иначе одиночная запись вклинилась бы между её
    сверкой и записью, и пачка молча переписала бы чужое."""
    async with _slot_lock():
        rows = await _fetch(
            """SELECT state, note, doctor, surfaces, surface_states, marks FROM teeth
               WHERE patient_id = ? AND tooth = ?""", pid, tooth)
        row, txt = _tooth_next(rows[0] if rows else None, tooth, state, note, doctor,
                               surfaces, sfmap, state0, marks)
        await _put_tooth(pid, tooth, row, _utcnow_iso())
        await _CONN.commit()
    await log_event(pid, "tooth", txt, tooth=tooth)


async def _put_tooth(pid: int, tooth: int, row: dict | None, at: str) -> None:
    """Строка зуба по решению `_tooth_next` — БЕЗ commit: его делает
    вызывающий (одна запись или вся пачка разом).

    ⭐ Здесь же — снимок в `teeth_history` («сравнить с визитом», 25.10): в той
    же транзакции и под тем же замком, что строка зуба, поэтому история и
    карта не расходятся ни на одной записи. `None` — строки зуба нет."""
    v = (row["state"], row["note"], row["doctor"], row["surfaces"],
         row["surface_states"], row["marks"]) if row else (None, "", "", "", "", "")
    await _CONN.execute(
        """INSERT INTO teeth_history(patient_id, tooth, at, state, note, doctor,
                                     surfaces, surface_states, marks)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""", (pid, tooth, at, *v))
    if row is None:
        await _CONN.execute("DELETE FROM teeth WHERE patient_id = ? AND tooth = ?",
                            (pid, tooth))
        return
    await _CONN.execute(
        """INSERT INTO teeth(patient_id, tooth, state, note, doctor, surfaces,
                             surface_states, marks, updated_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(patient_id, tooth) DO UPDATE
             SET state = excluded.state, note = excluded.note,
                 doctor = excluded.doctor, surfaces = excluded.surfaces,
                 surface_states = excluded.surface_states,
                 marks = excluded.marks,
                 updated_at = excluded.updated_at""",
        (pid, tooth, row["state"], row["note"], row["doctor"], row["surfaces"],
         row["surface_states"], row["marks"], at))


async def set_teeth(pid: int, items: list[dict]) -> int | None:
    """Запись НЕСКОЛЬКИХ зубов одним действием («Salvează tot», волна 2
    одонтограммы, 25.10): None — записаны все; номер — зуб, который изменился
    с тех пор, как экран начал его править, и тогда НЕ записано НИЧЕГО.

    `items` — те же поля, что у `set_tooth` (`tooth`, `state`, `note`,
    `doctor`, `surfaces`, `sfmap`, `state0`, `marks`), плюс `base` — каким
    экран ПОКАЗАЛ зуб, когда начал правку (`state`, `sfst`, `marks`,
    `doctor`, `note`). Сверка — с той же выжимкой строки, что едет экрану
    (`teeth_svg.tooth_fields`), поэтому «не менялся» значит «выглядел бы так
    же», а не «тот же updated_at».

    Сверка и запись — под ОДНИМ `_slot_lock` (его берёт и `set_tooth`):
    иначе чужая запись встала бы между ними. Строки — одной транзакцией, один
    commit в конце, при исключении rollback.
    ⚠️ Принятый риск (тот же, что у `delete_patient_fully`): соединение
    aiosqlite общее, и чужой `_execute` между нашими await может закоммитить
    часть пачки раньше; разорвать её может только ошибка диска посреди записи.
    Откаты чужих операций в рабочем пути идут под тем же замком или после
    упавшей операции. Отдельное соединение ради этого окна не заводим.
    Летопись — как у одиночной записи: строка на зуб через `log_event` после
    commit (журнал не роняет запись)."""
    from .teeth_svg import tooth_fields
    nums = [it["tooth"] for it in items]
    async with _slot_lock():
        rows = await _fetch(
            f"""SELECT tooth, state, note, doctor, surfaces, surface_states, marks
                FROM teeth WHERE patient_id = ? AND tooth IN ({','.join('?' * len(nums))})""",
            pid, *nums)
        prev = {r["tooth"]: r for r in rows}
        for it in items:
            if not _same_tooth(tooth_fields(prev.get(it["tooth"])), it["base"]):
                return it["tooth"]
        plan = [(it["tooth"], *_tooth_next(prev.get(it["tooth"]), it["tooth"], it["state"],
                                           it["note"], it["doctor"], it["surfaces"], it["sfmap"],
                                           it["state0"], it["marks"]))
                for it in items]
        at = _utcnow_iso()
        try:
            for tooth, row, _txt in plan:
                await _put_tooth(pid, tooth, row, at)
            await _CONN.commit()
        except Exception:
            await _CONN.rollback()
            raise
        for tooth, _row, txt in plan:
            await log_event(pid, "tooth", txt, tooth=tooth)
    return None


def _same_tooth(cur: dict, base: dict) -> bool:
    """Выжимка строки (`tooth_fields`) против того, что экран прислал как
    `base`: отметки — набором, поверхности — без пустых значений."""
    return (cur["state"] == base["state"] and cur["note"] == base["note"]
            and cur["doctor"] == base["doctor"]
            and sorted(cur["mk"]) == sorted(base["marks"])
            and {k: v for k, v in cur["sfst"].items() if v}
            == {k: v for k, v in base["sfst"].items() if v})


async def preview_teeth(pid: int, items: list[dict]) -> dict:
    """Карта зубов (`teeth_map`) такой, какой её сделала бы запись `items`, —
    БЕЗ записи: ни строки зуба, ни летописи. Решает тот же `_tooth_next`, что
    у записи, поэтому предпросмотр экрана и записанное не расходятся."""
    tmap = await teeth_map(pid)
    now = datetime.now(timezone.utc)
    for it in items:
        n = it["tooth"]
        row, _txt = _tooth_next(tmap.get(n), n, it["state"], it["note"], it["doctor"],
                                it["surfaces"], it["sfmap"], it["state0"], it["marks"])
        if row is None:
            tmap.pop(n, None)
        else:
            tmap[n] = {"tooth": n, **row, "updated_at": now}
    return tmap


def _tooth_next(prev: dict | None, tooth: int, state: str, note: str, doctor: str,
                surfaces: str | None, sfmap: dict | None, state0: str | None,
                marks: list | None) -> tuple[dict | None, str]:
    """(строка зуба | None — строку удалить, строка летописи) — чистое решение
    записи по прежней строке `prev`. Его зовут запись (`set_tooth`,
    `set_teeth`) и предпросмотр (`preview_teeth`).

    'ok' без заметки и без врача = зуб здоров → строка удаляется (карта sparse).
    doctor — СНАПШОТ имени на момент записи, как в plan_items: переименование
    врача не должно переписывать историю зуба.
    surfaces — буквы поверхностей одной строкой («MOD»); проверяет маршрут.
    sfmap — {поверхность: состояние}, когда они РАЗНЫЕ.
    state0 — состояние в том виде, В КАКОМ ЕГО ПОКАЗАЛА ФОРМА; None = не
    сообщала (открытая вкладка со старой разметкой).
    marks — отметки ПОВЕРХ находки («tratament»), см. teeth_svg.TOOTH_MARKS;
    None = форма о них не сообщала.

    ⭐ Три колонки (`state`, `surfaces`, `surface_states`) описывают одно и то
    же, поэтому согласует их ОДНО место — это. `surfaces` и `state` при
    непустом sfmap ВЫЧИСЛЯЮТСЯ из него: иначе печатная 043/e и выгрузка по
    195-му рано или поздно показали бы «Carie», когда кариеса на зубе уже нет,
    и заметить это было бы нечем — обе читают только `state`.

    ⚠️ `None` у `surfaces` и `sfmap` значит «экран об этом НЕ СООБЩАЛ», а не
    «пусто». Запрос знает или буквы (`surfaces` списком — так до 13.10 слал
    флажки диалог старой фиши, без состояний поверхностей), или карту (так
    шлёт React и слал инспектор детальной страницы — буквы из неё
    вычисляются). Принять молчание одного за стирание — значит терять клинику
    на сохранении, в котором врач ничего не менял: так пломба уходила с
    подписываемой 043/e. Поэтому не сообщённое берётся ИЗ ЗАПИСИ, и решается
    это здесь же, где сходятся все три колонки.
    """
    # состояние в летопись — СЛОВОМ (см. log_event): «obturatie» и «lipsa» это
    # ключи одонтограммы, а строку читают регистратура и пациент в выгрузке
    from .teeth_svg import (MARK_RO, STATE_RO, SURFACE_ORDER, SURFACE_STATES,
                            mark_list, pack_marks, pack_surfaces, surface_map,
                            surface_summary, tooth_state_of)
    if surfaces is None:
        surfaces = (prev["surfaces"] or "") if prev else ""
    # ⚠️ То же правило, что у поверхностей: «поля нет» ≠ «снято». Экран, не
    # сообщивший про отметки (`marks` = None), молчит — и молчание обязано
    # СОХРАНИТЬ отметку, а не снять её; снять все — пустой список. Иначе
    # «сохранить фишу» тихо снимало бы «в лечении» с каждого зуба. (У форм
    # старой фиши снятая галочка не слала ничего, и о факте они сообщали
    # отдельным полем `mk0`; сняты 13.10.)
    marks = mark_list(marks if marks is not None
                      else (prev["marks"] or "") if prev else "")
    if sfmap is None:
        # Буквы без карты (`surfaces` списком; до 13.10 так слали флажки
        # диалога фиши) о состояниях не сообщают. Сохранённые — держим, а
        # буква, отмеченная ВПЕРВЫЕ, получает состояние зуба: «одно состояние
        # на все отмеченные» и есть смысл флажков.
        # ⚠️ Смена состояния В ДИАЛОГЕ — это и есть сообщение: тогда прежняя
        # смесь не держится, иначе выбор врача молча пропал бы. Отличаем по
        # тому, пришло ли состояние тем же, каким диалог его и ПОКАЗАЛ, —
        # и говорит это сама форма (`state0`).
        # ⭐ Сравнение с БАЗОЙ делало один и тот же ввод то правкой, то
        # пустышкой: на зубе, где показанное совпало с сохранённым, «отметить
        # кариес на обеих поверхностях» молча не срабатывало, а на соседнем
        # срабатывало. Врач видит форму, а не колонку, поэтому «форма сообщила»
        # обязано быть фактом ФОРМЫ. Запрос без `state0` (открытая вкладка,
        # старая разметка) остаётся при прежнем сравнении — иначе у уже
        # отправляемых запросов молча сменился бы смысл.
        was = state0 if state0 is not None else (prev["state"] if prev else "")
        keep = (surface_map(prev["state"], prev["surfaces"] or "",
                            prev["surface_states"] or "")
                if prev is not None and state == was else {})
        sfmap = {k: keep.get(k, state) for k in SURFACE_ORDER if k in surfaces}
    sfmap = {k: v for k, v in sfmap.items()
             if k in SURFACE_ORDER and v in SURFACE_STATES}
    # ⭐ «Sănătos» — не утверждение о зубе, а значение списка ПО УМОЛЧАНИЮ:
    # инспектор его не поднимает, когда врач размечает поверхность, и «ok +
    # M:carie» значит «кариес мезиально», а не «зуб здоров». Коронка, имплант,
    # удаление — наоборот, сказаны про ВЕСЬ зуб и карту отменяют.
    if state not in SURFACE_STATES and state != "ok":
        # у состояний ЗУБА поверхностей нет, но буквы записи остаются как есть,
        # их печатает 043/e
        # ⭐ Форма, сообщившая карту, буквы этим и НАЗНАЧАЕТ: «какие поверхности
        # под коронкой» иначе вводилось бы только флажками фиши, а инспектор
        # принимал бы ввод, который сам же подсветил, и не сохранял.
        if sfmap:
            surfaces = "".join(k for k in SURFACE_ORDER if k in sfmap)
        sfmap = {}
    elif (state in SURFACE_STATES and not sfmap and surfaces
            and prev is not None and prev["state"] not in SURFACE_STATES):
        # Обратный переход: буквы пережили коронку/имплант/лечение, а карты под
        # ними нет и быть не могло — у состояний ЗУБА она пуста по замыслу,
        # поэтому инспектор кнопок не зажигает и прислать их не может. Считать
        # его молчание стиранием значило бы терять с подписываемой 043/e то,
        # какие поверхности поражены; новое состояние ложится на прежние буквы
        # ровно так же, как это делают флажки фиши.
        sfmap = {k: state for k in SURFACE_ORDER if k in surfaces}
    if sfmap:
        # ⚠️ ДО ветки удаления: иначе отмеченная поверхность исчезала бы вместе
        # со строкой зуба, а экран отвечал бы «сохранено» (грабля карты «303 не
        # отличает успех от отказа»)
        state = tooth_state_of(sfmap, state)
    # ⚠️ Отметка держит строку наравне с заметкой и врачом: «здоровый зуб, но
    # сейчас в работе» — законная запись, а без этого условия она удалялась бы
    # сразу после сохранения, и экран отвечал бы «сохранено» (грабля карты
    # «303 не отличает успех от отказа»).
    if state == "ok" and not note and not doctor and not marks:
        return None, f"Dinte {tooth}: {STATE_RO['ok']}"
    if state in SURFACE_STATES:
        # у поверхностного состояния буквы и карта — одно знание, поэтому буквы
        # ВЫЧИСЛЯЮТСЯ: сняли поражение с поверхности — ушла и буква
        surfaces = "".join(k for k in SURFACE_ORDER if k in sfmap)
    row = {"state": state, "note": note, "doctor": doctor, "surfaces": surfaces,
           "surface_states": pack_surfaces(sfmap), "marks": pack_marks(marks)}
    txt = f"Dinte {tooth}: {STATE_RO.get(state, state)}"
    # ⚠️ Летопись хранит ГОТОВУЮ строку, поэтому смесь разворачивается СЕЙЧАС:
    # «Carie (M), Obturație (OD)». Однородный случай даёт ровно прежний вид —
    # «Carie (MO)», и старые записи с новыми читаются одинаково
    parts = surface_summary(sfmap)
    if len(parts) > 1:
        txt = (f"Dinte {tooth}: "
               + ", ".join(f"{STATE_RO[st]} ({ls})" for st, ls in parts))
    elif surfaces:
        txt += f" ({surfaces})"
    # Отметка — отдельным словом ПОСЛЕ находки: «Carie (MO) · În tratament».
    # Так строка отвечает на оба вопроса разом, а прежние записи (у которых
    # отметок нет) выглядят ровно как выглядели.
    for m in marks:
        txt += f" · {MARK_RO[m]}"
    if doctor:
        txt += f" · {doctor}"
    if note:
        txt += f" · {note}"
    return row, txt


# ---------- мосты (punte, 08-21, просьба пилота) ----------
# Мост — конструкция ПОВЕРХ зубов: состояние зуба (teeth.state) не мутируется,
# кариес под опорой и «lipsă» под промежутком остаются правдой самого зуба.
# Роль у КАЖДОГО зуба (опора бывает и в середине — пример врача: 47-43 с
# опорами 47/45/43); печать и рисование читают строку teeth через
# teeth_svg.parse_bridge — второго разбора не заводить.

async def bridges(pid: int) -> list:
    return await _fetch(
        """SELECT id, teeth, material, doctor, created_at
           FROM bridges WHERE patient_id = ? ORDER BY id""", pid)


def _bridge_words(teeth: list, material: str) -> str:
    """Мост словами для летописи: «Punte dentară 47–43 din zirconiu; stâlpi:
    47, 45, 43; intermediari: 46, 44». Летопись хранит ГОТОВУЮ строку навсегда
    (см. log_event), поэтому роли разворачиваются в слова здесь и сейчас."""
    span = f"{teeth[0][0]}–{teeth[-1][0]}"
    stalpi = ", ".join(str(n) for n, r in teeth if r == "stalp")
    corp = ", ".join(str(n) for n, r in teeth if r == "corp")
    out = f"Punte dentară {span}"
    if material:
        out += f" din {material}"
    out += f"; stâlpi: {stalpi}"
    if corp:
        out += f"; intermediari: {corp}"
    return out


async def add_bridge(pid: int, teeth: list, material: str,
                     doctor: str = "") -> int | str | None:
    """id — записан; 'dup' — какой-то зуб уже в другом мосту (два моста на
    одном зубе — вздор, и молча перекрывать чужую конструкцию нельзя).
    `teeth` приходит УЖЕ нормализованным (odontogram.bridge_norm) — db
    порядка дуги не знает. Проверка и INSERT — под _slot_lock: инвариант
    «зуб в одном мосту» держится только check-then-insert'ом (у таблицы нет
    уникального индекса — зубы лежат упакованной строкой), и без замка два
    конкурентных сохранения оба видят «свободно» (ревью 08-22)."""
    from .teeth_svg import pack_bridge, parse_bridge
    mine = {n for n, _r in teeth}
    async with _slot_lock():
        for row in await bridges(pid):
            if mine & {n for n, _r in parse_bridge(row["teeth"])}:
                return "dup"
        packed = pack_bridge(teeth)
        cur = await _CONN.execute(
            """INSERT INTO bridges(patient_id, teeth, material, doctor,
                                   created_at) VALUES(?, ?, ?, ?, ?)""",
            (pid, packed, material, doctor, _utcnow_iso()))
        await _CONN.commit()
        new_id = cur.lastrowid
        await cur.close()
    txt = _bridge_words(teeth, material)
    if doctor:
        txt += f" · {doctor}"
    await log_event(pid, "bridge", txt)
    return new_id


async def delete_bridge(bid: int, pid: int) -> bool:
    """Снять мост. След в летописи остаётся: конструкцию ставили и снимали —
    это события лечения, а не оформление. Летопись пишется ПОСЛЕ удаления и
    только если DELETE реально снял строку: log_event коммитится собственной
    транзакцией, и записанное ДО было бы враньём навсегда при отказе DELETE
    или втором конкурентном удалении (ревью 08-22). Замок — тот же, что у
    add_bridge: SELECT и DELETE иначе гоняются с ним."""
    from .teeth_svg import parse_bridge
    async with _slot_lock():
        rows = await _fetch(
            "SELECT teeth, material, doctor, created_at FROM bridges "
            "WHERE id = ? AND patient_id = ?", bid, pid)
        if not rows:
            return False
        # снятый мост уходит в bridges_removed той же транзакцией («сравнить с
        # визитом», 25.10): карта на дату, когда он стоял, обязана его рисовать
        b = rows[0]
        try:
            await _CONN.execute(
                """INSERT INTO bridges_removed(bridge_id, patient_id, teeth, material,
                                               doctor, created_at, removed_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (bid, pid, b["teeth"], b["material"], b["doctor"], _iso(b["created_at"]),
                 _utcnow_iso()))
            cur = await _CONN.execute(
                "DELETE FROM bridges WHERE id = ? AND patient_id = ?", (bid, pid))
            n = cur.rowcount
            await cur.close()
            if n != 1:
                await _CONN.rollback()
                return False
            await _CONN.commit()
        except Exception:
            await _CONN.rollback()
            raise
    t = parse_bridge(rows[0]["teeth"])
    span = f"{t[0][0]}–{t[-1][0]}" if t else "?"
    await log_event(pid, "bridge", f"Punte dentară {span} ștearsă")
    return True


# ---------- пародонтограмма (perio) ----------

async def perio_exams(pid: int) -> list:
    """Осмотры пациента, свежие сверху, с числом измеренных зубов.
    ⚠️ `teeth` — СЧЁТЧИК, а не строка зубов: имя короткое, потому что колонка
    так и называется на экране («28 dinți»)."""
    return await _fetch(
        """SELECT e.id, e.doctor, e.note, e.created_at,
                  COUNT(t.tooth) AS teeth
           FROM perio_exams e LEFT JOIN perio_teeth t ON t.exam_id = e.id
           WHERE e.patient_id = ?
           GROUP BY e.id, e.doctor, e.note, e.created_at
           ORDER BY e.created_at DESC, e.id DESC""", pid)


async def perio_exam(pid: int, eid: int) -> dict | None:
    """Шапка осмотра. ⚠️ Всегда И по пациенту: id осмотра приходит из формы, и
    без второго условия чужой осмотр открывался бы по прямому адресу."""
    rows = await _fetch(
        """SELECT id, patient_id, doctor, note, created_at
           FROM perio_exams WHERE id = ? AND patient_id = ?""", eid, pid)
    return rows[0] if rows else None


async def perio_rows(eid: int) -> list:
    """Измерения одного осмотра, по порядку номеров зуба."""
    return await _fetch(
        """SELECT tooth, pd, rec, bop, mob, furc FROM perio_teeth
           WHERE exam_id = ? ORDER BY tooth""", eid)


async def perio_new(pid: int, doctor: str = "", note: str = "") -> int:
    """Новый (пустой) осмотр. Летопись пишется при СОХРАНЕНИИ измерений, а не
    здесь: пустой осмотр — это ещё не находка, а открытый лист."""
    cur = await _CONN.execute(
        """INSERT INTO perio_exams(patient_id, doctor, note, created_at)
           VALUES(?, ?, ?, ?)""",
        (pid, doctor, note, _utcnow_iso()))
    await _CONN.commit()
    new_id = cur.lastrowid
    await cur.close()
    return int(new_id)


async def perio_save(pid: int, eid: int, rows: list, covers: set,
                     doctor: str | None = None,
                     note: str | None = None) -> int:
    """Записать измерения в осмотр. Возвращает число сохранённых зубов.

    ⛔ `covers` — зубы, О КОТОРЫХ это сохранение СООБЩАЕТ: экран прислал их
    измерения или сказал, что измерений у них больше нет. Стирается
    `covers − keep`, и только оно. Зуб вне `covers` не пишется и НЕ СТИРАЕТСЯ:
    про него не сказано ничего, а «не сообщали» никогда не значит «стереть»
    (08-16, две потери данных ровно на этом различии).
    ⭐ Отсюда два рабочих места правят ОДИН осмотр, не отнимая работу друг у
    друга (18.09). Прежнее правило стирало «показанные, но не присланные», а
    показывал лист всегда все 32 зуба: место, загрузившее осмотр раньше,
    сносило чужой зуб целиком и возвращало чужие числа к тем, что видело само
    — ответ 200, в летописи обычная вторая строка.
    ⚠️ Врач и заметка — только если ПРИСЛАНЫ (None ≠ пустая строка): форма
    печати их не шлёт, и None не должен затирать подпись осмотра.
    ⚠️ Сообщать нечего — не делается НИЧЕГО, включая строку летописи: пустое
    сохранение это не находка осмотра, а промах по кнопке.
    """
    from .modules.patients.perio import ledger_words
    if not rows and not covers and doctor is None and note is None:
        return 0
    keep = {int(r["tooth"]) for r in rows}
    async with _slot_lock():
        for tooth in sorted(covers - keep):
            await _execute(
                "DELETE FROM perio_teeth WHERE exam_id = ? AND tooth = ?",
                eid, int(tooth))
        for r in rows:
            await _execute(
                """INSERT INTO perio_teeth(exam_id, tooth, pd, rec, bop, mob, furc)
                   VALUES(?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(exam_id, tooth) DO UPDATE SET
                     pd = excluded.pd, rec = excluded.rec, bop = excluded.bop,
                     mob = excluded.mob, furc = excluded.furc""",
                eid, int(r["tooth"]), r["pd_packed"], r["rec_packed"],
                r["bop"], int(r["mob"]), int(r["furc"]))
        if doctor is not None or note is not None:
            await _execute(
                """UPDATE perio_exams SET doctor = COALESCE(?, doctor),
                          note = COALESCE(?, note)
                   WHERE id = ? AND patient_id = ?""",
                doctor, note, eid, pid)
    exam = await perio_exam(pid, eid)
    when = exam["created_at"] if exam else None
    await log_event(pid, "perio", ledger_words(await perio_rows(eid), when))
    return len(rows)


async def perio_drop(pid: int, eid: int) -> bool:
    """Снять ПУСТОЙ осмотр (двойной клик по «Examen nou»).
    ⛔ Осмотр с измерениями не удаляется никем: это медицинская запись, её
    правят, а не заставляют исчезнуть — то же правило, что у дневника визита.
    """
    if await _fetchval("SELECT COUNT(*) FROM perio_teeth WHERE exam_id = ?",
                       eid):
        return False
    n = await _execute(
        "DELETE FROM perio_exams WHERE id = ? AND patient_id = ?", eid, pid)
    return n == 1


async def perio_last(pid: int) -> tuple:
    """Последний осмотр С ИЗМЕРЕНИЯМИ и его строки — для 043/e и выгрузки-195.
    ⚠️ Именно с измерениями: пустой лист, открытый и не заполненный, не должен
    подменять собой прошлую настоящую карту на подписываемой бумаге."""
    for e in await perio_exams(pid):
        if e["teeth"]:
            return e, await perio_rows(e["id"])
    return None, []


# ⭐ «Активная» позиция плана — это planificat|in_lucru, а НЕ «всё, что не
# finalizat». Пока статусов было три, две формулировки совпадали; с появлением
# ОТКАЗА (refuzat, ст.13(5) Legea 263/2005) вторая стала враньём: отказанная
# процедура навсегда осталась бы «в лечении» — в KPI фиши, в колонке списка и
# в сумме активного плана. Считать активность только через этот кортеж.
PLAN_ACTIVE = ("planificat", "in_lucru")
# закрытые: у них проставлен done_at и они не ждут работы
PLAN_CLOSED = ("finalizat", "refuzat")


async def plan_items(pid: int) -> list:
    # created_at — когда позиция появилась в плане: по нему статус «acord
    # informat» говорит «план изменён после подписи» (01.10)
    # visit_doctor — врач визита, на котором позицию выполнили (22.10): кто
    # ЗАПЛАНИРОВАН, лежит в `doctor` и не переписывается — «Redeschide»
    # обязан вернуть его. Кого печатать — fisa043.plan_doctor. Подзапрос, а
    # не JOIN: doctor/status/id/created_at есть в обеих таблицах.
    return await _fetch(
        """SELECT id, tooth, procedure, doctor, status, price_mdl, due_date,
                  done_at, appointment_id, refuz_motiv, created_at,
                  (SELECT a.doctor FROM appointments a
                    WHERE a.id = plan_items.appointment_id) AS visit_doctor
           FROM plan_items WHERE patient_id = ? ORDER BY id""", pid)


async def last_events(pid: int, kinds: tuple) -> dict:
    """Когда в последний раз случалось событие каждого вида — статусы бланков
    фиши («tipărit DD.MM»). Лента фиши для этого не годится: она режется
    шестьюдесятью строками, и печать месячной давности из неё выпадает.
    ⚠️ Псевдоним `at` — в `_DT_COLS`: иначе в SQLite MAX() остался бы строкой."""
    if not kinds:
        return {}
    lite = ",".join("?" for _ in kinds)
    rows = await _fetch(
        f"""SELECT kind, MAX(at) AS at FROM activity
            WHERE patient_id = ? AND kind IN ({lite}) GROUP BY kind""",
        pid, *kinds)
    return {r["kind"]: r["at"] for r in rows}


async def plan_item_status(item_id: int, pid: int) -> str | None:
    """Текущий статус позиции — для проверки, что переход допустим. Стрелки
    статусов НАПРАВЛЕННЫЕ (см. _PLAN_EDGES в модуле пациентов), и охрана
    обязана смотреть на «откуда», а не только на «куда»."""
    return await _fetchval(
        "SELECT status FROM plan_items WHERE id = ? AND patient_id = ?",
        item_id, pid)


async def add_plan_item(pid: int, tooth: int | None, procedure: str,
                        doctor: str, price_mdl: int | None,
                        due_date: str = "") -> None:
    await _execute(
        """INSERT INTO plan_items(patient_id, tooth, procedure, doctor, price_mdl,
                                  due_date, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        pid, tooth, procedure, doctor, price_mdl, due_date or None,
                _utcnow_iso(),
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
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
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
            """UPDATE plan_items SET status = ?, done_at = ?,
                  appointment_id = ?, refuz_motiv = ?
                WHERE id = ? AND patient_id = ?""",
            status, _utcnow_iso(), appt, why, item_id, pid,
        )
    else:
        await _execute(
            """UPDATE plan_items SET status = ?, done_at = NULL,
                  appointment_id = NULL, refuz_motiv = ''
                WHERE id = ? AND patient_id = ?""",
            status, item_id, pid,
        )


async def delete_plan_item(item_id: int, pid: int) -> bool:
    """Летопись — ПОСЛЕ DELETE и только за реально снятую строку (как у
    `delete_bridge`). False — позиции у пациента нет."""
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
                        item_id, pid)
    if not rows:
        return False
    n = await _execute(
        "DELETE FROM plan_items WHERE id = ? AND patient_id = ?", item_id, pid)
    if n != 1:
        return False
    await log_event(pid, "plan_del", f"Plan: - {rows[0]['procedure']}",
                    tooth=rows[0]["tooth"])
    return True


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
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id,
                  a.service_id, a.starts_at, a.duration_min, a.status, a.source,
                  a.comment, p.name
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.id = ?""", appt_id)
    return rows[0] if rows else None


async def visit_record(appt_id: int) -> dict | None:
    rows = await _fetch(
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
        "SELECT id FROM visit_records WHERE appointment_id = ?", appt_id)
    result = "created" if existing is None else "updated"
    # один upsert, а не SELECT+ветка: два открытых окна консультации иначе
    # вставляют наперегонки, и второе падает на UNIQUE(appointment_id).
    # created_at при обновлении не трогаем
    # (в SET его нет), гонка может лишь перепутать глагол в летописи
    await _execute(
        """INSERT INTO visit_records(appointment_id, patient_id, doctor,
             acuze, examen, diagnostic, tratament, recomandari, author,
             created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(appointment_id) DO UPDATE SET
             doctor = excluded.doctor, acuze = excluded.acuze,
             examen = excluded.examen, diagnostic = excluded.diagnostic,
             tratament = excluded.tratament,
             recomandari = excluded.recomandari,
             author = excluded.author, updated_at = ?""",
        appt_id, pid, doctor, *vals, actor, _utcnow_iso(),
                _utcnow_iso(),
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
    await _execute("UPDATE patients SET lang = ? WHERE id = ?",
                   lang, pid)


async def anamneza(pid: int) -> dict | None:
    rows = await _fetch(
        """SELECT patient_id, flags, boli, medicamente, alergii, anestezie,
                  author, created_at, updated_at
           FROM anamneza WHERE patient_id = ?""", pid)
    return rows[0] if rows else None


async def save_anamneza(pid: int, flags: str, fields: dict) -> str:
    """Upsert опросника; возвращает 'created' | 'updated'."""
    vals = tuple((fields.get(k) or "").strip()[:500] for k in ANAMNEZA_FIELDS)
    actor = _actor_now()
    existed = await _fetchval(
        "SELECT 1 FROM anamneza WHERE patient_id = ?", pid)
    await _execute(
        """INSERT INTO anamneza(patient_id, flags, boli, medicamente, alergii,
             anestezie, author, created_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(patient_id) DO UPDATE SET
             flags = excluded.flags, boli = excluded.boli,
             medicamente = excluded.medicamente, alergii = excluded.alergii,
             anestezie = excluded.anestezie, author = excluded.author,
             updated_at = ?""",
        pid, flags, *vals, actor, _utcnow_iso(), _utcnow_iso(),
    )
    await log_event(pid, "anamneza",
                    "Anamneza actualizată" if existed else "Anamneza completată")
    return "updated" if existed else "created"


# Поля записи прикуса — в порядке колонок; маршрут принимает только их.
OCLUZIE_FIELDS = ("angle_dr", "angle_st", "overjet", "overbite", "incrucisata",
                  "deschisa", "mediana_mm", "mediana_spre", "nota", "doctor")


async def ocluzie(pid: int) -> dict | None:
    rows = await _fetch(
        f"""SELECT patient_id, {", ".join(OCLUZIE_FIELDS)}, author, created_at,
                   updated_at
            FROM ocluzie WHERE patient_id = ?""", pid)
    return rows[0] if rows else None


async def save_ocluzie(pid: int, fields: dict, prev_line: str = "") -> str:
    """Upsert записи прикуса; возвращает 'created' | 'updated'. `fields` —
    УЖЕ слитые с прежней записью значения всех OCLUZIE_FIELDS (правило
    «не сообщали ≠ стереть» живёт у маршрута, здесь пишется всё).
    `prev_line` — прежняя запись готовой строкой: при перезаписи она уходит
    в летопись, чтобы история прикуса не пропадала молча (летопись хранит
    готовое, разбирать её назад никто не будет)."""
    vals = tuple((fields.get(k) or "") for k in OCLUZIE_FIELDS)
    actor = _actor_now()
    existed = await _fetchval("SELECT 1 FROM ocluzie WHERE patient_id = ?", pid)
    sets = ", ".join(f"{k} = excluded.{k}" for k in OCLUZIE_FIELDS)
    await _execute(
        f"""INSERT INTO ocluzie(patient_id, {", ".join(OCLUZIE_FIELDS)}, author,
                                created_at)
            VALUES(?, {", ".join("?" * len(OCLUZIE_FIELDS))}, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET {sets},
              author = excluded.author, updated_at = ?""",
        pid, *vals, actor, _utcnow_iso(), _utcnow_iso(),
    )
    text = "Ocluzia actualizată" if existed else "Ocluzia înregistrată"
    if existed and prev_line:
        text += f" (anterior: {prev_line})"
    await log_event(pid, "ocluzie", text)
    return "updated" if existed else "created"


async def visit_records_map(pid: int) -> dict[int, dict]:
    """appointment_id → запись приёма: фиша красит историю визитов одним
    запросом, а не по одному на строку."""
    rows = await _fetch(
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
           WHERE v.patient_id = ? ORDER BY a.starts_at DESC""", pid)


async def documents(pid: int) -> list:
    return await _fetch(
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
           FROM payments WHERE patient_id = ? ORDER BY at DESC, id DESC""", pid)


async def add_payment(pid: int, amount: int, method: str, note: str) -> None:
    actor = _actor_now()
    await _execute(
        """INSERT INTO payments(patient_id, amount_mdl, method, note, taken_by, at)
           VALUES(?, ?, ?, ?, ?, ?)""",
        pid, amount, method, note, actor, _utcnow_iso(),
    )
    verb = "Plată" if amount > 0 else "Restituire"
    await log_event(pid, "pay", f"{verb} {abs(amount)} MDL ({method})"
                    + (f" — {note}" if note else ""))


async def get_payment(pay_id: int, pid: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, amount_mdl, method, note FROM payments
           WHERE id = ? AND patient_id = ?""", pay_id, pid)
    return rows[0] if rows else None


async def delete_payment(pay_id: int, pid: int) -> bool:
    """Удаление платежа — исправление ошибки ввода, не бухгалтерская операция.
    Право на него только у директора (маршрут), а след остаётся в летописи —
    ПОСЛЕ DELETE и только за реально снятую строку (как у `delete_bridge`)."""
    p = await get_payment(pay_id, pid)
    if p is None:
        return False
    n = await _execute("DELETE FROM payments WHERE id = ? AND patient_id = ?",
                       pay_id, pid)
    if n != 1:
        return False
    await log_event(pid, "pay_del",
                    f"Plată ștearsă: {p['amount_mdl']} MDL ({p['method']})")
    return True


async def patient_finance(pid: int) -> dict:
    """Начислено (завершённые позиции плана с ценой) и оплачено. Долг считает
    вызывающий: charged − paid; минус = аванс."""
    charged = await _fetchval(
        """SELECT COALESCE(SUM(price_mdl), 0) FROM plan_items
           WHERE patient_id = ? AND status = 'finalizat'""", pid)
    paid = await _fetchval(
        "SELECT COALESCE(SUM(amount_mdl), 0) FROM payments WHERE patient_id = ?",
        pid)
    return {"charged": int(charged or 0), "paid": int(paid or 0)}


async def payments_range(start: datetime, end: datetime) -> list:
    """Платежи за окно времени — для «Încasări» в статистике."""
    return await _fetch(
        """SELECT amount_mdl, method, at FROM payments
           WHERE at >= ? AND at < ?""",
        _iso(start), _iso(end),
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
    async def _n(sql: str, *a) -> int:
        return int(await _fetchval(sql, *a) or 0)

    pays = await _n("SELECT COUNT(*) FROM payments WHERE patient_id = ?", pid)
    teeth = await _n("SELECT COUNT(*) FROM teeth WHERE patient_id = ?", pid)
    plan = await _n("SELECT COUNT(*) FROM plan_items WHERE patient_id = ?", pid)
    docs = await _n("SELECT COUNT(*) FROM documents WHERE patient_id = ?", pid)
    # запись приёма — лечение по определению, даже если визит формально
    # будущий/отменённый: врач уже вписал клинический текст
    consult = await _n("SELECT COUNT(*) FROM visit_records WHERE patient_id = ?",
                       pid)
    # анамнез — медицинская запись: фиша с одним опросником обезличивается,
    # а не стирается физически
    anam = await _n("SELECT COUNT(*) FROM anamneza WHERE patient_id = ?", pid)
    # мост — протезная работа, то есть лечение: держит фишу от физического
    # стирания наравне с зубами и планом
    punti = await _n("SELECT COUNT(*) FROM bridges WHERE patient_id = ?", pid)
    # пародонтограмма — такая же медицинская запись, как зубы и дневник:
    # осмотр с измерениями держит фишу от физического стирания
    perio = await _n("SELECT COUNT(*) FROM perio_exams WHERE patient_id = ?",
                     pid)
    # прикус (26.10) — запись объективного осмотра, графа 043/e: медзапись,
    # как анамнез
    occl = await _n("SELECT COUNT(*) FROM ocluzie WHERE patient_id = ?", pid)
    now = datetime.now(timezone.utc)
    happened = await _n(
        """SELECT COUNT(*) FROM appointments WHERE patient_id = ?
           AND (status IN ('done','arrived','waiting')
                OR (status = 'confirmed' AND starts_at < ?))""",
        pid, _iso(now))
    return ("anon" if (teeth or plan or docs or happened or pays or consult
                       or anam or punti or perio or occl) else "delete")


# Таблицы, ссылающиеся на пациента, — в порядке удаления: дети раньше родителя
# (с foreign_keys=ON внешние ключи иначе откажут, без него остались бы сироты). Дневники
# приёмов стоят раньше визитов: FK на appointments. ⚠️ Состав обязан совпадать
# с export.py — обе стороны отвечают «где в базе лежит этот человек».
_PATIENT_CHILD_TABLES = ("payments", "activity", "patient_alerts", "teeth",
                         "teeth_history", "plan_items", "documents", "anamneza",
                         "ocluzie", "bridges", "bridges_removed", "recall_marks",
                         "perio_exams", "visit_records", "sms_log", "appointments")

# ⚠️ Внуки: таблицы, которые висят НЕ на пациенте, а на его записи. У
# `perio_teeth` нет patient_id вовсе, и общий шаблон «DELETE ... WHERE
# patient_id» её не касается. Каскад внешнего ключа сделал бы это сам, но
# полагаться на него нельзя: включённость `PRAGMA foreign_keys` — свойство
# СОЕДИНЕНИЯ, и на чужом (восстановление, ремонт базы, другой драйвер)
# измерения пережили бы стирание пациента молча. Удаляются ПЕРВЫМИ.
_PATIENT_GRAND_CHILDREN = (("perio_teeth", "exam_id", "perio_exams"),)


async def delete_patient_fully(pid: int) -> None:
    """Физическое удаление: строка пациента и ВСЁ, что на неё ссылается.

    Файлы документов на диске удаляет ВЫЗЫВАЮЩИЙ (маршрут): db не знает про
    раскладку файлов, и это его единственная граница.

    ⭐ АТОМАРНО (аудит 08-20). Раньше десять DELETE шли каждый со своим
    COMMIT, и обрыв посреди (питание, убитый процесс, залоченная база)
    оставлял ПОЛУпациента: платежи стёрты, фиша на месте — выглядит как
    «программа сама что-то удалила», а довершить нечем. Теперь либо целиком,
    либо ничего. У SQLite — executescript ОДНИМ вызовом: очередь aiosqlite
    исполняет его как одну операцию, чужой запрос не вклинится в середину и
    не закоммитит половину (у общего соединения commit общий). Параметров
    executescript не принимает, поэтому pid подставляется в текст — он int
    по построению, и int() рядом это закрепляет.
    """
    pid = int(pid)
    script = "BEGIN IMMEDIATE;\n" + "\n".join(
        [f"DELETE FROM {t} WHERE {key} IN "
         f"(SELECT id FROM {parent} WHERE patient_id = {pid});"
         for t, key, parent in _PATIENT_GRAND_CHILDREN]
        + [f"DELETE FROM {t} WHERE patient_id = {pid};"
           for t in _PATIENT_CHILD_TABLES]
    ) + f"\nDELETE FROM patients WHERE id = {pid};\nCOMMIT;"
    try:
        await _CONN.executescript(script)
    except Exception:
        # обрыв посреди скрипта оставляет транзакцию открытой — вернуть
        # базу в исходное; вне транзакции rollback безвреден.
        # ⚠️ Принятый риск (ревью 08-22): между этим исключением и
        # rollback чужая операция очереди может успеть commit — общий
        # commit зафиксировал бы полу-удаление. Предусловие — сам скрипт
        # упал, а падает он только на уже-битой базе (диск, коррупция),
        # где атомарность уже не главная беда; отдельное соединение ради
        # этого окна не заводим.
        await _CONN.rollback()
        raise
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
        """UPDATE patients SET name = ?, phone = NULL, email = NULL,
             birth_date = NULL, birth_year = NULL, gender = NULL, idnp = NULL,
             address = NULL, insurance = NULL, notes = NULL,
             session_key = ?, archived = 1 WHERE id = ?""",
        f"Pacient anonimizat #{pid}", f"anon:{pid}", pid)
    # платежи остаются (касса клиники под номером фиши), но заметка платежа —
    # свободный текст рецепции, то есть потенциально личность: стираем
    await _execute("UPDATE payments SET note = '' WHERE patient_id = ?", pid)
    await _execute(
        "UPDATE appointments SET comment = '' WHERE patient_id = ?", pid)
    # Будущие живые записи — отменяются (17.10, посторонний разбор): человека
    # больше нет, звонить некому, а час у врача оставался занятым, и
    # «Pacient anonimizat #N» без телефона висел в «De confirmat — sunați».
    # Прошлое не трогаем: состоявшийся приём — медицинская история под номером.
    await _execute(
        f"""UPDATE appointments SET status = 'cancelled'
            WHERE patient_id = ? AND status IN {_ACT_SQL} AND starts_at > ?""",
        pid, _utcnow_iso())
    # летопись — тот же свободный текст ЭХОМ: log_event дублирует туда заметку
    # платежа («Plată 500 MDL — transfer de la fratele …») и имя загруженного
    # файла. Строки пациента удаляются целиком, как в delete_patient_fully;
    # платёжные данные живут в payments и остаются. Событие «erase» пишет
    # вызывающий маршрут ПОСЛЕ — след стирания в летописи сохраняется.
    await _execute("DELETE FROM activity WHERE patient_id = ?", pid)
    # журнал SMS — номер телефона и день визита, то есть личность и ничего из
    # лечения: уходит целиком, как летопись (S5)
    await _execute("DELETE FROM sms_log WHERE patient_id = ?", pid)
    # имя документа дал человек («radiografie-popescu.png») — это личность;
    # сам снимок остаётся (это ЧТО лечили), скрытое имя на диске и так hex.
    # Расширение сохраняем: по нему работает белый список открытия (_OPEN_EXT)
    for d in await _fetch(
            "SELECT id, stored_path FROM documents WHERE patient_id = ?", pid):
        neutral = f"document-{d['id']}{os.path.splitext(d['stored_path'])[1]}"
        await _execute(
            "UPDATE documents SET filename = ? WHERE id = ?",
            neutral, d["id"])
    log.warning("patient %s anonymized (erasure request, has medical records)", pid)


async def documents_with_paths(pid: int) -> list:
    """То же, что documents(), но с путём к файлу на диске.

    Отдельной функцией, а не полем в documents(): путь нужен ровно двум местам —
    выгрузке данных пациента и удалению — и не должен попадать на страницы,
    откуда его видно в исходном коде HTML.
    """
    return await _fetch(
        """SELECT id, filename, stored_path, size, mime, category, uploaded_at
           FROM documents WHERE patient_id = ? ORDER BY id""", pid)


async def add_document(pid: int, filename: str, stored_path: str,
                       size: int, mime: str, category: str = "alt") -> None:
    await _execute(
        """INSERT INTO documents(patient_id, filename, stored_path, size, mime,
                                 category, uploaded_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        pid, filename, stored_path, size, mime, category, _utcnow_iso(),
    )
    await log_event(pid, "doc_add", f"Document încărcat: {filename}")


async def get_document(doc_id: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, patient_id, filename, stored_path, size, mime
           FROM documents WHERE id = ?""", doc_id)
    return rows[0] if rows else None


async def delete_document(doc_id: int, pid: int) -> bool:
    """Строка документа (файл с диска снимает маршрут, `_drop_doc`). Летопись —
    ПОСЛЕ DELETE и только за реально снятую строку (как у `delete_bridge`).
    False — документа у пациента нет."""
    d = await get_document(doc_id)
    if not d or d["patient_id"] != pid:
        return False
    n = await _execute(
        "DELETE FROM documents WHERE id = ? AND patient_id = ?", doc_id, pid)
    if n != 1:
        return False
    await log_event(pid, "doc_del", f"Document șters: {d['filename']}")
    return True


async def set_comment(appt_id: int, text: str) -> None:
    await _execute(
        "UPDATE appointments SET comment = ? WHERE id = ?",
        text, appt_id,
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
    `_slot_lock`: уникальные индексы ловят только совпадающие старты, а
    пересечение 10:00(60′) с 10:30(60′) — нет.
    ⚠️ `when` — время НОВОГО старта в часах клиники, уже строкой: db не знает
    про часовой пояс (в базе UTC), а летопись читает человек.
    """
    async with _slot_lock():
        rows = await _fetch(
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
        rem_lite =", reminded_day = 0, reminded_2h = 0" if moved else ""
        try:
            await _execute(
                f"""UPDATE appointments SET doctor = ?, doctor_id = ?,
                   starts_at = ?{rem_lite} WHERE id = ?""",
                doctor, doctor_id, _iso(starts_at), appt_id,
            )
        except Exception as e:  # noqa: BLE001 — uq_doctor_slot/uq_patient_slot
            if "uq_" in str(e) or "unique" in str(e).lower():
                await _CONN.rollback()
                return "conflict"
            raise
        if r["patient_id"]:
            await log_event(r["patient_id"], "appt_move",
                            f"Vizită mutată: {when} · {doctor} — {r['service']}")
        return ""


async def set_appt_service(appt_id: int, service_id: str, service: str,
                           duration_min: int) -> str:
    """Смена процедуры у стоящей записи (22.10): ключ услуги, СНИМОК подписи и
    СНИМОК длительности — те же три колонки, что пишет бронь.

    Ответ — КОД, как у переноса: `''` — сменено (или уже та же услуга);
    `gone` — записи нет; `closed` — визит не активен; `conflict` — выросшая
    длительность наезжает на соседа у того же врача.
    ⚠️ Состояние перечитывается ПОД `_slot_lock`, а не берётся у вызывающего:
    пока регистратура выбирала услугу, вторая вкладка могла завершить визит,
    поставить соседа вплотную или уже сменить процедуру. Наезд спрашиваем у
    ДАННЫХ (`_conflicts`) до записи — текст ошибки движка индекс не называет.
    ⚠️ Проверка наезда — только когда визит ДЛИННЕЕ прежнего: короче или
    столько же — он лежит внутри уже занятого им интервала, и отказ «занято»
    из-за чужой старой ошибки (наезд, записанный до 08-13) не дал бы даже
    сократить визит.
    ⛔ Заметку стойки (`source='note'`) здесь не тронуть: у неё в `service`
    лежит ТЕКСТ заметки, а не процедура; правило вызывающего её не пропускает,
    а условие ниже держит то же на уровне данных.
    """
    async with _slot_lock():
        rows = await _fetch(
            """SELECT patient_id, doctor, doctor_id, starts_at, duration_min,
                      status, source, service, service_id
               FROM appointments WHERE id = ?""", appt_id)
        if not rows or rows[0]["source"] == "note":
            return "gone"
        r = rows[0]
        if r["status"] not in ACTIVE_STATUSES:
            return "closed"
        if r["service_id"] == service_id:
            return ""
        if duration_min > int(r["duration_min"] or 60) and await _conflicts(
                r["doctor_id"], r["doctor"], r["starts_at"], duration_min,
                exclude_id=appt_id):
            return "conflict"
        await _execute(
            """UPDATE appointments SET service = ?, service_id = ?, duration_min = ?
               WHERE id = ? AND source != 'note'""",
            service, service_id, duration_min, appt_id)
        if r["patient_id"]:
            # «›», а не стрелка: стрелки нет во вшитом шрифте (CLAUDE.md)
            await log_event(r["patient_id"], "appt_service",
                            f"Procedura schimbată: {r['service']} › {service}")
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
    async with _slot_lock():
        rows = await _fetch(
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
                    "UPDATE appointments SET status = ?, waiting_at = ? WHERE id = ?",
                    status, _utcnow_iso(), appt_id,
                )
            elif status == "arrived":
                await _execute(
                    "UPDATE appointments SET status = ?, arrived_at = ? WHERE id = ?",
                    status, _utcnow_iso(), appt_id,
                )
            elif status == "confirmed":
                await _execute(
                    """UPDATE appointments SET status = ?,
                       waiting_at = NULL, arrived_at = NULL WHERE id = ?""",
                    status, appt_id,
                )
            else:
                await _execute(
                    "UPDATE appointments SET status = ? WHERE id = ?",
                    status, appt_id,
                )
            own = await _fetch(
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
                await _CONN.rollback()
                # ⚠️ КАКОЙ индекс сработал, движок в тексте не называет —
                # спрашиваем данные. Под УЗКОЙ страховкой (шаг 4 не доложен)
                # сюда доходит и переход между активными статусами.
                if r and r["patient_id"] and await _patient_busy_at(
                        r["patient_id"], r["starts_at"], exclude_id=appt_id):
                    return "dup"
                return "conflict"
            raise
