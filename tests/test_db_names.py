"""Имена `db` — те же, что до пакета (03.11.2026).

`bot/app/db.py` на 4 тысячи строк разнесён на пакет `bot/app/db/` БЕЗ правок у
вызывающих: `from . import db` и `db.что-угодно` обязаны значить ровно то же,
что значили. Отсюда три вопроса, и каждый ломается молча:

- имя пропало из пакета — `AttributeError` только на той ветке, которая его
  зовёт (у клиники, на экране, которого прогон не обходит);
- реэкспорт смотрит НЕ на тот объект, что живёт в модуле-владельце, — имя
  подмодуля совпало с именем функции (`db.payments` — функция; модуль с таким
  именем перекрыл бы её или она его), или подмодуль переприсвоил своё имя;
- переприсваиваемое состояние (`_CONN`, `_SQ`, `ACTOR_HOOK`) завелось в
  подмодуле: `db.ACTOR_HOOK = …` из `main.py` попадает в пакет, а читал бы
  подмодуль своё — подпись летописи молча стала бы «recepție».

`SNAPSHOT` — имена верхнего уровня `db.py` на `4a92eeb` (без импортов). Новое
имя в db — строка здесь; убранное — тоже, словом в коммите.
"""
import ast
import importlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone

from harness import BOT, ROOT, Result

sys.path.insert(0, str(BOT))
from app import db  # noqa: E402

PKG = BOT / "app" / "db"
# Переприсваиваемое на ходу: живёт в __init__ и только там (подмодули — через
# пакет, `db._CONN`).
STATE = ("_CONN", "_SQ", "ACTOR_HOOK")

# Что прежний db.py импортировал в шапке — его атрибуты, но не его имена.
_IMPORTED = {"annotations", "datetime", "timezone"}

SNAPSHOT = frozenset((
    # «Registre» (10.11.2026): санитарные регистры, db/registre.py + SAN_DDL шага 9
    "SAN_DDL", "SAN_TABLES", "SAN_KINDS", "san_items", "san_item", "san_item_save", "san_insert",
    "san_close", "san_delete", "san_row", "san_rows", "san_open", "san_fixed_ids", "san_lamp_minutes",
    "san_last_clean", "san_last_cycle",
    "_ACT_SQL", "ACTIVE_STATUSES", "ACTOR_HOOK", "_actor_now", "add_alert",
    "add_bridge", "add_document", "add_note", "add_payment", "add_plan_item",
    "add_recall_mark", "add_visit_for_patient", "admin_add", "all_patients",
    "anamneza", "ANAMNEZA_FIELDS", "anonymize_patient", "_apply_uq_indexes",
    "appointment_brief", "appointment_days", "appt_calls", "appt_patient_id",
    "_backfill_activity", "backfill_ids", "_book", "_BOOK_LOCK", "_book_locked",
    "booked_intervals", "_bridge_words", "bridges", "bridges_at",
    "bridges_removed_rows", "close", "_conflicts", "_CONN", "create_appointment",
    "create_patient", "DATABASE_URL", "day_appointments", "day_patient_facts",
    "del_meta", "delete_alert", "delete_bridge", "delete_document",
    "delete_patient_fully", "delete_payment", "delete_plan_item", "_DIA", "_digits",
    "doctor_future_count", "documents", "documents_with_paths", "_DT_COLS",
    "erasure_kind", "EVENT_TEXT_MAX", "_execute", "_fetch", "_fetchval", "_fold",
    "fold", "get_document", "get_meta", "get_patient", "get_payment", "init",
    "_insert_note", "_iso", "last_events", "log", "_log_booking", "log_clinic_event",
    "log_event", "manual_key", "MKT_EVENT", "MKT_SOURCES", "manual_patient_sms_off", "_migrate", "MIGRATIONS",
    "move_appointment", "ocluzie", "OCLUZIE_DDL", "OCLUZIE_FIELDS", "_OLD_ACT_SQL",
    "_parse_dt", "patient_activity", "patient_alerts", "patient_appointments",
    "_patient_busy_at", "_PATIENT_CHILD_TABLES", "PATIENT_FIELDS", "patient_finance",
    "_PATIENT_GRAND_CHILDREN", "patient_id_by_key", "_patient_ids_by_digits",
    "patient_name_by_phone", "patient_visit_records", "patients_archived",
    "patients_count", "patients_counts", "patients_debt", "patients_doctors",
    "patients_have_tg", "patients_rows", "patients_total", "patients_visits",
    "PAY_METHODS", "payments", "payments_day", "payments_range", "perio_drop",
    "perio_exam", "perio_exams", "perio_last", "perio_new", "perio_rows", "perio_save",
    "_PL_CANAL", "_PL_COLS", "_PL_DEBT", "_PL_DIALECT", "_PL_DOCTOR", "_PL_FROM",
    "_PL_LAST_DOC_OF", "_PL_ORDER", "PLAN_ACTIVE", "PLAN_CLOSED", "plan_item_status",
    "plan_items", "plan_open_summary", "_PLIST_COLS", "_PlQuery", "preview_teeth",
    "_put_tooth", "recall_auto_sent", "recall_bookings_since", "recall_contacts_since",
    "RECALL_DDL", "recall_done_last", "recall_future", "RECALL_IDX_DDL",
    "recall_marks", "recent_activity", "relink_doctor", "_RO_COUNT", "_rowdict",
    "_same_tooth", "save_anamneza", "save_ocluzie", "save_visit_record",
    "SCHEMA_VERSION", "_schema_version", "seed", "set_appt_call", "set_appt_service", "set_appt_duration",
    "set_archived", "set_birth_year", "set_comment", "set_meta", "set_patient_lang",
    "set_plan_status", "set_mkt", "set_primary_doctor", "_set_schema_version", "set_sms_off",
    "set_status", "set_teeth", "set_tooth", "_slot_conflict_sql", "_slot_conflicts",
    "slot_guard", "_slot_guard_apply", "_slot_guard_clear", "_slot_guard_startup",
    "_slot_guard_verdict", "_slot_lock", "_slot_rows", "sms_by_idem", "sms_candidates",
    "sms_counts", "sms_delete", "SMS_DELIVERED", "sms_drop_kind", "sms_enqueue",
    "SMS_EXPIRED", "SMS_FAILED", "sms_known_idems", "sms_log_sent", "SMS_OFF_EVENT",
    "sms_overdue", "sms_pending", "sms_queue", "SMS_QUEUED", "_SMS_REMINDED_SQL",
    "sms_rows", "SMS_SENT", "sms_set", "SMS_STATES", "sms_states_by_kind",
    "SMS_UNDELIVERED", "sms_visits_month", "_SQ", "SQLITE_CARD_SCHEMA",
    "_sqlite_driver", "SQLITE_EXTRA_COLS", "SQLITE_PATIENT_COLS", "SQLITE_SCHEMA",
    "_teeth_hist_base", "TEETH_HIST_SINCE", "teeth_hist_since", "TEETH_HIST_STEP",
    "teeth_history_rows", "teeth_map", "teeth_map_at", "tooth_activity", "_tooth_next",
    "tooth_records_since", "update_patient", "_upsert_patient", "_uq_at_least",
    "UQ_BROKEN", "UQ_CLEARED_TEXT", "UQ_COMPLETE_TEXT", "uq_event_text", "_uq_gone",
    "uq_gone_ro", "UQ_GUARD_STEP", "_uq_index_state", "_UQ_LADDER", "_uq_mark_rows",
    "_uq_matches", "UQ_NARROW", "UQ_PENDING_KEY", "UQ_REPAIR_GONE", "UQ_REPAIR_NARROW",
    "UQ_REPAIR_TEXT", "_UQ_RO", "_UQ_SLOT", "UQ_SLOT_COUNT", "_uq_slot_sql",
    "_UQ_STATE", "_uq_statuses", "UQ_UNKNOWN", "_UQ_WORD", "_utcnow_iso",
    "VISIT_FIELDS", "visit_record", "visit_records_map",
))


# Подмена имени db из тестов и скриптов: `db.X = …`, `appdb.X += …`, `setattr(db, …)` —
# и в коде строк для `python -c`, поэтому текстом, а не деревом.
_ASSIGN = re.compile(r"\b(?:app)?db\.(\w+)\s*[-+]?=(?!=)")
_SETATTR = re.compile(r"\b(?:set|del)attr\(\s*(?:app)?db\b")
# Сторожа сами пишут такие строки: текст правила и мутация, которая его ломает.
_GUARDS = {"test_db_names.py", "test_structure.py", "mutate.py"}
# Часы харнесса (`tests/fakeclock`) подменяют `datetime` в глобалах модулей `app.*`
# ПОСЛЕ исполнения тела: подмодуль, куда часы не дотянулись, жил бы по настоящему
# времени, и набор под `harness.Clock` проверял бы не тот день — зелёным.
_CLOCK_CODE = """
import importlib, pkgutil, datetime as real
from app import db
print('_utcnow_iso', db._utcnow_iso())
for m in sorted(n for _, n, _ in pkgutil.iter_modules(db.__path__)):
    mod = importlib.import_module('app.db.' + m)
    if 'datetime' in vars(mod):
        print(m, mod.datetime.now(real.timezone.utc).isoformat())
"""


def _defined(path) -> list[str]:
    """Имена верхнего уровня файла — то, что модуль определяет сам."""
    out = []
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            out += [x.id for t in targets for x in ast.walk(t) if isinstance(x, ast.Name)]
    return out


def suite(res: Result) -> None:
    subs = sorted(p.stem for p in PKG.glob("*.py") if p.stem != "__init__")
    # Якорь: пустой обход сделал бы все проверки ниже зелёными разом.
    res.ok("исходники пакета db нашлись", (PKG / "__init__.py").exists() and len(subs) >= 10,
           f"в {PKG} подмодулей: {subs}")

    missing = sorted(n for n in SNAPSHOT if not hasattr(db, n))
    res.ok("каждое имя прежнего db.py есть в пакете", not missing,
           "пропали (AttributeError у вызывающего): " + ", ".join(missing))

    extra = sorted(n for n, v in vars(db).items()
                   if not n.startswith("_") and n not in SNAPSHOT and n not in subs
                   and not isinstance(v, types.ModuleType) and n not in _IMPORTED)
    res.ok("у db нет новых публичных имён мимо снимка", not extra,
           "новое имя — строка в SNAPSHOT: " + ", ".join(extra))

    clash = sorted(set(subs) & SNAPSHOT)
    res.ok("имя подмодуля не совпадает с именем db", not clash,
           "подмодуль и функция делят одно имя пакета, одно перекроет другое: "
           + ", ".join(clash))

    stale, owners = [], {}
    for sub in subs:
        mod = importlib.import_module(f"app.db.{sub}")
        for name in _defined(PKG / f"{sub}.py"):
            owners.setdefault(name, []).append(sub)
            if getattr(db, name, None) is not getattr(mod, name):
                stale.append(f"{sub}.{name}")
    res.ok("db.X — тот же объект, что у модуля-владельца", not stale,
           "реэкспорт смотрит не туда: " + ", ".join(stale))
    twice = sorted(f"{n}: {', '.join(o)}" for n, o in owners.items() if len(o) > 1)
    res.ok("у имени db один модуль-владелец", not twice, "; ".join(twice))
    lost = sorted(n for n in SNAPSHOT - set(STATE) if n not in owners)
    res.ok("каждое имя снимка живёт в подмодуле", not lost,
           "имя осталось в __init__ или пропало: " + ", ".join(lost))

    scanned, swapped = 0, []
    for top in ("tests", "scripts", "demo"):
        for f in sorted((ROOT / top).rglob("*.py")):
            if f.name in _GUARDS:
                continue
            scanned += 1
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                hit = [a for a in _ASSIGN.findall(line) if a not in STATE]
                if hit or _SETATTR.search(line):
                    swapped.append(f"{f.relative_to(ROOT).as_posix()}:{i}")
    res.ok("тесты и скрипты не подменяют имена db", scanned > 50 and not swapped,
           f"просмотрено файлов {scanned}; подмена через пакет не дойдёт до вызовов из "
           f"подмодулей — подменять в модуле-владельце: " + ", ".join(swapped))

    shift = tempfile.NamedTemporaryFile("w", suffix=".shift", delete=False)
    shift.write(str(400 * 86400))                        # +400 суток
    shift.close()
    try:
        env = dict(os.environ, PYTHONPATH=str(ROOT / "tests" / "fakeclock"),
                   FAKECLOCK_FILE=shift.name)
        p = subprocess.run([sys.executable, "-c", _CLOCK_CODE], cwd=BOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        pathlib.Path(shift.name).unlink(missing_ok=True)
    rows = dict(ln.split(" ", 1) for ln in p.stdout.splitlines()
                if ln and not ln.startswith("[fakeclock]"))
    soon = datetime.now(timezone.utc) + timedelta(days=300)
    stuck = sorted(m for m, at in rows.items() if datetime.fromisoformat(at) < soon)
    res.ok("часы харнесса двигают все подмодули db",
           p.returncode == 0 and "_utcnow_iso" in rows and len(rows) >= 6 and not stuck,
           f"код {p.returncode}; подмодули с datetime: {sorted(rows)}; мимо часов: "
           f"{stuck}; {p.stderr[-300:]}")

    leaked = sorted(f"{o}.{n}" for n in STATE for o in owners.get(n, []))
    res.ok("состояние db живёт только в __init__", not leaked and
           all(n in _defined(PKG / "__init__.py") for n in STATE),
           "переприсваиваемое имя завелось в подмодуле — db.X = … его не увидит: "
           + ", ".join(leaked))
