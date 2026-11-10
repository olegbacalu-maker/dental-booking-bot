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
    registre  санитарные регистры 257/e, 502/e, 501/e (без пациентов)
    schema    схема, миграции, init/close

⛔ **Переприсваиваемое состояние живёт ЗДЕСЬ и только здесь** — `_CONN`, `_SQ`,
`ACTOR_HOOK`: это тот объект, который снаружи видят как `db`, и `db.ACTOR_HOOK
= …` из `main.py` должен попасть туда, где его читают. Подмодули берут его
ЧЕРЕЗ ПАКЕТ (`from .. import db` → `db._CONN`), никогда `from . import _CONN`:
импорт заморозил бы `None` до `init()` навсегда (правило CLAUDE.md, держит
`test_structure`)."""
from __future__ import annotations

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
    MKT_SOURCES, MKT_EVENT, set_mkt,
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
    sms_log_sent, sms_states_by_kind, sms_counts, sms_visits_month,
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
    set_appt_call, set_comment, move_appointment, set_appt_service, set_appt_duration,
    set_status,
)
from .teeth import (
    TEETH_HIST_SINCE, teeth_map, teeth_hist_since, teeth_map_at, teeth_history_rows,
    bridges_removed_rows, bridges_at, set_tooth, _put_tooth, set_teeth, _same_tooth,
    preview_teeth, _tooth_next, bridges, _bridge_words, add_bridge, delete_bridge,
)
from .perio import (
    perio_exams, perio_exam, perio_rows, perio_new, perio_save, perio_drop, perio_last,
)
from .records import (
    VISIT_FIELDS, appointment_brief, visit_record, save_visit_record, ANAMNEZA_FIELDS,
    set_patient_lang, anamneza, save_anamneza, OCLUZIE_FIELDS, ocluzie, save_ocluzie,
    visit_records_map, patient_visit_records,
)
from .docs import (
    documents, documents_with_paths, add_document, get_document, delete_document,
)
from .finance import (
    payments_day, PAY_METHODS, payments, add_payment, get_payment, delete_payment,
    patient_finance, payments_range,
)
from .erasure import (
    erasure_kind, _PATIENT_CHILD_TABLES, _PATIENT_GRAND_CHILDREN, delete_patient_fully,
    anonymize_patient,
)
from .registre import (
    SAN_TABLES, SAN_KINDS, san_items, san_item, _san_insert_id, san_item_save, san_insert, san_close,
    san_delete, san_row, san_rows, san_open, san_fixed_ids, san_lamp_minutes, san_last_clean,
    san_last_cycle, _SAN_COLS, _SAN_CLOSE, _SAN_WHEN, _san_table,
)
from .schema import (
    SCHEMA_VERSION, OCLUZIE_DDL, RECALL_DDL, RECALL_IDX_DDL, SAN_DDL, SAN_PEOPLE_DDL, MIGRATIONS, TEETH_HIST_STEP,
    SQLITE_CARD_SCHEMA, SQLITE_EXTRA_COLS, SQLITE_PATIENT_COLS, SQLITE_SCHEMA,
    _schema_version, _set_schema_version, _teeth_hist_base, _migrate, _sqlite_driver, init,
    close,
)

_CONN = None         # aiosqlite connection
# Модуль DBAPI, которым ОТКРЫТА картотека: штатный sqlite3 или sqlcipher3.
# ⚠️ Ловить исключения обязательно ЧЕРЕЗ него. У sqlcipher3 своя иерархия, и
# `except sqlite3.IntegrityError` на зашифрованной базе не поймает ничего —
# защита от двойной записи отвалилась бы молча и только у той клиники, которая
# включила шифрование. Ставится в init(), до него значения нет.
_SQ = None


# Кто сейчас за журналом. Ставится приложением при старте (main.py), потому что
# db лежит НИЖЕ слоя доступа и импортировать его не может — иначе получился бы
# круг db → core.auth → db. Без хука всё работает как раньше: «recepție».
ACTOR_HOOK = None
