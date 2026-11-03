"""Слой БД: SQLite (aiosqlite), файл картотеки из DATABASE_URL (sqlite:///…).
Даты храним как ISO-строки в UTC — сравнения лексикографичны.

Postgres-издание снято 12.10.2026 (на нём не работало ничего живого: демо
сайта — тот же SQLite); последний код с ним — тег `archive/pg-edition`.

Пакет с 03.11.2026 (до того — один `db.py` на 4 тысячи строк). Для вызывающих
ничего не поменялось: `from . import db` и `db.что-угодно` — здесь
реэкспортировано каждое имя прежнего модуля (снимок держит
`tests/test_db_names.py`). Раскладка снизу вверх, в порядке импорта:

    conn      соединение, выборки, даты, schema_meta как словарь
    events    летопись пациента и клиники, кто за журналом
    slots     ⭐ защита слотов: замок брони, страховочные индексы, бронь
    patients  фиша: поиск, поля, предупреждения, свёртка диакритики
    plist     список «Pacienți» одной выборкой
    sms       очередь SMS-напоминаний
    recall    Rechemări
    plans     план лечения
    schedule  визиты и журнал: запись, заметки, день, перенос, статус
    teeth     одонтограмма, история зубов, мосты
    perio     пародонтограмма
    records   дневник визита, анамнез, прикус
    docs      документы пациента
    finance   платежи
    erasure   закон 195: стирание и обезличивание
    schema    схема, миграции, init/close

⛔ **Переприсваиваемое состояние живёт ЗДЕСЬ и только здесь** — `_CONN`, `_SQ`,
`ACTOR_HOOK`: это тот объект, который снаружи видят как `db`, и `db.ACTOR_HOOK
= …` из `main.py` должен попасть туда, где его читают. Подмодули берут его
ЧЕРЕЗ ПАКЕТ (`from .. import db` → `db._CONN`), никогда `from . import _CONN`:
импорт заморозил бы `None` до `init()` навсегда (правило CLAUDE.md, держит
`test_structure`)."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from .conn import (
    DATABASE_URL, log, _iso, _utcnow_iso, _parse_dt, _DT_COLS, _rowdict, _fetch, _fetchval,
    _execute, get_meta, set_meta, del_meta,
)
from .events import (
    _actor_now, EVENT_TEXT_MAX, log_event, log_clinic_event, _log_booking,
    patient_activity, recent_activity, tooth_activity, tooth_records_since,
    _backfill_activity,
)
from .slots import (
    ACTIVE_STATUSES, _ACT_SQL, _BOOK_LOCK, _slot_lock, _OLD_ACT_SQL, _UQ_LADDER,
    UQ_GUARD_STEP, UQ_PENDING_KEY, UQ_REPAIR_GONE, UQ_REPAIR_NARROW, UQ_NARROW, UQ_BROKEN,
    UQ_UNKNOWN, _uq_slot_sql, _UQ_SLOT, UQ_SLOT_COUNT, _SLOT_GUARD, slot_guard,
    _slot_conflict_sql, _UQ_STATE, _slot_conflicts, _slot_rows, _uq_index_state, _UQ_WORD,
    _uq_statuses, _uq_matches, _UQ_RO, _uq_gone, uq_gone_ro, _RO_COUNT, uq_event_text,
    UQ_REPAIR_TEXT, UQ_CLEARED_TEXT, UQ_COMPLETE_TEXT, _uq_mark_rows, _uq_at_least,
    _apply_uq_indexes, _slot_guard_apply, _slot_guard_verdict, _slot_guard_clear,
    _slot_guard_startup, _book, _book_locked, _patient_busy_at, _conflicts,
)
from .patients import (
    patients_total, _upsert_patient, manual_key, _patient_ids_by_digits,
    patient_name_by_phone, _digits, patient_id_by_key, create_patient, set_archived, _DIA,
    _fold, fold, patient_appointments, PATIENT_FIELDS, get_patient, update_patient,
    set_primary_doctor, set_birth_year, patient_alerts, add_alert, delete_alert,
)
from .plist import (
    _PLIST_COLS, all_patients, patients_visits, patients_debt, _PL_LAST_DOC_OF, _PL_DOCTOR,
    _PL_DEBT, _PL_CANAL, _PL_FROM, _PL_COLS, _PL_ORDER, _PL_DIALECT, _PlQuery,
    patients_count, patients_rows, patients_doctors, patients_archived, patients_have_tg,
    patients_counts,
)
from .sms import (
    SMS_QUEUED, SMS_SENT, SMS_DELIVERED, SMS_UNDELIVERED, SMS_FAILED, SMS_EXPIRED,
    SMS_STATES, _SMS_REMINDED_SQL, sms_candidates, sms_known_idems, sms_enqueue, sms_queue,
    sms_set, sms_delete, sms_drop_kind, sms_overdue, sms_pending, sms_rows, sms_by_idem,
    sms_log_sent, sms_states_by_kind, sms_counts, sms_spent, sms_visits_month,
    SMS_OFF_EVENT, set_sms_off, manual_patient_sms_off,
)
from .recall import (
    recall_done_last, recall_future, recall_marks, recall_contacts_since,
    recall_bookings_since, add_recall_mark, recall_auto_sent,
)
from .plans import (
    plan_open_summary, PLAN_ACTIVE, PLAN_CLOSED, plan_items, last_events, plan_item_status,
    add_plan_item, set_plan_status, delete_plan_item,
)
from .schedule import (
    backfill_ids, relink_doctor, seed, create_appointment, admin_add,
    add_visit_for_patient, add_note, _insert_note, booked_intervals, doctor_future_count,
    appt_patient_id, day_appointments, appointment_days, day_patient_facts, appt_calls,
    set_appt_call, set_comment, move_appointment, set_appt_service, set_status,
)
from .teeth import (
    TEETH_HIST_SINCE, teeth_map, teeth_hist_since, teeth_map_at, teeth_history_rows,
    bridges_removed_rows, bridges_at, set_tooth, _put_tooth, set_teeth, _same_tooth,
    preview_teeth, _tooth_next, bridges, _bridge_words, add_bridge, delete_bridge,
)
from .perio import (
    perio_exams, perio_exam, perio_rows, perio_new, perio_save, perio_drop, perio_last,
)

# Версия схемы: шаги применяются по одному и записываются в schema_meta,
# поэтому по базе клиники всегда видно, докуда она домигрирована.
# ⚠️ Новый шаг в MIGRATIONS без поднятия версии — МЁРТВЫЙ код: цикл _migrate
# идёт range(have+1, SCHEMA_VERSION+1) и до него не дойдёт (так шаг 4 с
# 'waiting' в uq-индексах не исполнялся ни у одной клиники; держит
# test_structure).
SCHEMA_VERSION = 8

_CONN = None         # aiosqlite connection
# Модуль DBAPI, которым ОТКРЫТА картотека: штатный sqlite3 или sqlcipher3.
# ⚠️ Ловить исключения обязательно ЧЕРЕЗ него. У sqlcipher3 своя иерархия, и
# `except sqlite3.IntegrityError` на зашифрованной базе не поймает ничего —
# защита от двойной записи отвалилась бы молча и только у той клиники, которая
# включила шифрование. Ставится в init(), до него значения нет.
_SQ = None


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
    from ..core import dbkey

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
    from .. import paths            # ⭐ один разборщик $DATABASE_URL на проект
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


# Кто сейчас за журналом. Ставится приложением при старте (main.py), потому что
# db лежит НИЖЕ слоя доступа и импортировать его не может — иначе получился бы
# круг db → core.auth → db. Без хука всё работает как раньше: «recepție».
ACTOR_HOOK = None


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
