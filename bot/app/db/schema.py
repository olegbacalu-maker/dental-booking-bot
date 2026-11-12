"""Схема картотеки: DDL, миграции, версия схемы, открытие и закрытие.

`init` открывает файл (sqlite3 или sqlcipher3 — `_sqlite_driver`), ставит
`db._CONN`/`db._SQ` в пакете и доводит схему: базовые таблицы, шаги
`MIGRATIONS` до `SCHEMA_VERSION`, страж слотов, backfill летописи, демо-засев."""
from __future__ import annotations

import re

from .. import db
from .conn import _execute, _fetchval, _utcnow_iso, log
from .events import _backfill_activity
from .slots import _slot_guard_apply, _slot_guard_startup, UQ_GUARD_STEP
from .patients import _digits, _fold
from .schedule import seed
from .teeth import TEETH_HIST_SINCE


# Версия схемы: шаги применяются по одному и записываются в schema_meta,
# поэтому по базе клиники всегда видно, докуда она домигрирована.
# ⚠️ Новый шаг в MIGRATIONS без поднятия версии — МЁРТВЫЙ код: цикл _migrate
# идёт range(have+1, SCHEMA_VERSION+1) и до него не дойдёт (так шаг 4 с
# 'waiting' в uq-индексах не исполнялся ни у одной клиники; держит
# test_structure).
SCHEMA_VERSION = 11


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

# «Registre» (10.11.2026, санитарные регистры 257/e, 502/e, 501/e): записи
# БЕЗ пациентов — ни одной ссылки на `patients`, стирание по 195 их не
# касается. Каталог `san_equipment` правится (директор), три журнала — только
# дописываются: исправление = НОВАЯ строка с `fixes` = id исправленной и
# причиной `why`; правки строки на месте нет, кроме ОДНОКРАТНОГО закрытия
# открытой записи (конец цикла и тесты, итог биотеста, выключение лампы,
# подпись проверяющего — каждое пишется только в пустое поле). Удаление —
# мягкое (`deleted_at`/`deleted_by`, только директор): строка уходит с экрана
# и листа, но остаётся в базе. Подпись строки — `actor`/`actor_id` вошедшего
# и время программы (UTC ISO); имена оборудования — СНИМКОМ, как врач у визита.
# Даты-моменты (`*_at`) — UTC ISO-строки; `plan_date`/`done_date` — голые даты.
# Шаг 9 аддитивный: новых таблиц не запрещают никакие данные, падать нечему;
# строго, как 7 и 8 (свежая база проходит шаги с нуля и получает их так же).
SAN_DDL = [
    """CREATE TABLE IF NOT EXISTS san_equipment(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  nr TEXT NOT NULL DEFAULT '',
  room TEXT NOT NULL DEFAULT '',
  data TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT
)""",
    """CREATE TABLE IF NOT EXISTS san_cycles(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ster_id INTEGER,
  ster TEXT NOT NULL,
  program TEXT NOT NULL DEFAULT '',
  pressure TEXT NOT NULL DEFAULT '',
  temp TEXT NOT NULL DEFAULT '',
  arts TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  ended_at TEXT,
  chem TEXT NOT NULL DEFAULT '',
  term TEXT NOT NULL DEFAULT '',
  bio TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  end_actor TEXT NOT NULL DEFAULT '',
  bio_actor TEXT NOT NULL DEFAULT '',
  bio_at TEXT,
  fixes INTEGER,
  why TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  deleted_at TEXT,
  deleted_by TEXT NOT NULL DEFAULT ''
)""",
    """CREATE TABLE IF NOT EXISTS san_cleanings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id INTEGER,
  room TEXT NOT NULL,
  plan_date TEXT NOT NULL DEFAULT '',
  done_date TEXT NOT NULL,
  solution TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  sup_actor TEXT NOT NULL DEFAULT '',
  sup_id TEXT NOT NULL DEFAULT '',
  sup_at TEXT,
  fixes INTEGER,
  why TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  deleted_at TEXT,
  deleted_by TEXT NOT NULL DEFAULT ''
)""",
    """CREATE TABLE IF NOT EXISTS san_uv(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lamp_id INTEGER,
  lamp TEXT NOT NULL,
  room TEXT NOT NULL DEFAULT '',
  cond TEXT NOT NULL DEFAULT '',
  on_at TEXT NOT NULL,
  off_at TEXT,
  minutes INTEGER,
  rest_hours INTEGER,
  actor TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  off_actor TEXT NOT NULL DEFAULT '',
  fixes INTEGER,
  why TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  deleted_at TEXT,
  deleted_by TEXT NOT NULL DEFAULT ''
)""",
    "CREATE INDEX IF NOT EXISTS ix_san_cycles_at ON san_cycles(started_at)",
    "CREATE INDEX IF NOT EXISTS ix_san_clean_at ON san_cleanings(done_date)",
    "CREATE INDEX IF NOT EXISTS ix_san_uv_at ON san_uv(lamp_id, on_at)",
]

# Шаг 10 (10.11, registre-people — «Вариант 1» Олега): КТО СДЕЛАЛ — выбранный
# человек клиники (каталог «Personal», вид `staff`), а не учётка: в клинике одна
# учётка на всех, а убирает и стерилизует младший персонал без входа. Учётка
# остаётся в `actor` / `end_actor` / `sup_by` как «кто внёс запись». Старые
# строки получают '' — экран и лист показывают их по-прежнему, словом
# «cont (înreg. veche)». Колонки только ДОБАВЛЯЮТСЯ; журналы по-прежнему
# только дописываются (`end_doer` и `sup_by` пишет `san_close` под замком).
SAN_PEOPLE_DDL = [
    "ALTER TABLE san_cycles ADD COLUMN doer TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE san_cycles ADD COLUMN end_doer TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE san_cleanings ADD COLUMN doer TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE san_cleanings ADD COLUMN sup_by TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE san_uv ADD COLUMN doer TEXT NOT NULL DEFAULT ''",
]

# Вкладка «Google Calendar». Ключ события уникален по всей таблице, а не
# внутри источника: календарь переименовывают, и с ключом «источник + UID» он
# вернул бы перенесённые события как новые. `title`/`body` стираются после
# переноса и по сроку, строка остаётся ради ключа. Время — как в календаре,
# без округления: от него считается отпечаток `stamp`.
# Каждый оператор — IF NOT EXISTS: шаг миграции повторяется.
GCAL_DDL = [
    """CREATE TABLE IF NOT EXISTS gcal_sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'ics',
  name TEXT NOT NULL DEFAULT '',
  ext_id TEXT NOT NULL DEFAULT '',
  settings TEXT NOT NULL DEFAULT '',
  loaded_at TEXT,
  loaded_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS gcal_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL REFERENCES gcal_sources(id),
  ext_key TEXT NOT NULL,
  starts_at TEXT,
  minutes INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  series INTEGER NOT NULL DEFAULT 0,
  gstatus TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'nou',
  why TEXT NOT NULL DEFAULT '',
  by_hand INTEGER NOT NULL DEFAULT 0,
  stamp TEXT NOT NULL DEFAULT '',
  stamp_moved TEXT NOT NULL DEFAULT '',
  appt_id INTEGER REFERENCES appointments(id),
  moved_at TEXT,
  moved_by TEXT NOT NULL DEFAULT '',
  seen_at TEXT NOT NULL,
  created_at TEXT NOT NULL
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_gcal_key ON gcal_events(ext_key)",
    "CREATE INDEX IF NOT EXISTS ix_gcal_state ON gcal_events(state, starts_at)",
    "CREATE INDEX IF NOT EXISTS ix_gcal_appt ON gcal_events(appt_id)",
]

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
    # 9 (10.11, «Registre»): санитарные регистры — каталог и три журнала
    # (`SAN_DDL` выше). Аддитивно и строго, как 7 и 8.
    9: SAN_DDL,
    # 10 (10.11, registre-people): кто сделал — человек, не учётка
    # (`SAN_PEOPLE_DDL` выше). Колонки с DEFAULT '' — старым строкам противоречить
    # нечему; строго, как 7–9.
    10: SAN_PEOPLE_DDL,
    # Таблицы вкладки «Google Calendar»: аддитивно и строго, как 7–10.
    11: GCAL_DDL,
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
    # 10.11.2026: длительность задана РУКАМИ (окно визита или окно записи), а не
    # снята с услуги. 1 — смена процедуры её не трогает: клиника поставила 30′
    # сознательно. Признак, а не сравнение с услугой: длительность услуги в
    # настройках меняют, и «не совпадает с услугой» соврало бы (прайор 08-16 —
    # намерение из формы, не угадывать по базе). Старые строки — 0, как было.
    ("appointments", "duration_set INTEGER NOT NULL DEFAULT 0"),
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
    # Согласие на маркетинг (10.11, слово Олега): ответ пациента на «acorduri
    # opționale › marketing» листа 195. NULL — не спрашивали, 1 — DA, 0 — NU;
    # `mkt_at` — когда (UTC), `mkt_src` — `ecran` (подпись листа на экране) или
    # `manual` (бумажный лист, отметка регистратуры). Nullable, без индекса и
    # без шага миграции: ADD COLUMN переживает любые данные клиники.
    "mkt_ok INTEGER", "mkt_at TEXT", "mkt_src TEXT",
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
        await db._CONN.execute(
            """INSERT INTO teeth_history(patient_id, tooth, at, state, note, doctor,
                                         surfaces, surface_states, marks, src)
               SELECT patient_id, tooth, MIN(updated_at, ?), state, note, doctor,
                      surfaces, surface_states, marks, 'base' FROM teeth""", (at,))
        await db._CONN.execute("INSERT INTO schema_meta(key, value) VALUES(?, ?)",
                            (TEETH_HIST_SINCE, at))
        await db._CONN.commit()
    except Exception:
        await db._CONN.rollback()
        raise


# `ALTER TABLE … ADD COLUMN` в списке шага. SQLite не знает ADD COLUMN IF NOT
# EXISTS, а цикл ниже коммитит операторы шага ДО записи версии: шаг, оборванный
# между ними (выключили ПК, упал старт посреди шага), при следующем старте
# повторяется по базе, где часть колонок уже есть, — и «duplicate column» ронял
# бы старт при КАЖДОМ запуске (2.14.2, шаг 10, класс 1.20.0). Поэтому у ADD
# COLUMN — тот же приём, что у SQLITE_EXTRA_COLS в `init`: «duplicate column» =
# колонка уже есть, всё прочее — наверх.
_ADD_COLUMN = re.compile(r"\s*ALTER\s+TABLE\s+\S+\s+ADD\s+(?:COLUMN\s+)?\S", re.I)


def _already_added(sql: str, err: BaseException) -> bool:
    """Оператор шага — ADD COLUMN, а отказ — «колонка уже есть». Только это;
    залоченная база, I/O, опечатка в DDL поднимаются как были."""
    return bool(_ADD_COLUMN.match(sql)) and "duplicate column" in str(err).lower()


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
                try:
                    await db._CONN.execute(sql)
                except db._SQ.OperationalError as e:
                    # ⛔ `db._SQ`, а не модуль sqlite3: у sqlcipher3 (картотека
                    # зашифрована) свои классы исключений, не наследники
                    # sqlite3, — `except sqlite3.…` у такой клиники не поймал бы
                    # ничего. Текст отказа у обоих драйверов один.
                    if not _already_added(sql, e):
                        raise
            await db._CONN.commit()
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
    import aiosqlite
    from .. import paths            # ⭐ один разборщик $DATABASE_URL на проект
    path = str(paths.db_file())
    # ⚠️ Локальное имя `sqlite3` — не описка: ниже в этой же функции стоят
    # `except sqlite3.OperationalError`, и они обязаны смотреть на ТОТ
    # драйвер, которым база открыта. Назови переменную иначе — и следующий
    # написанный здесь except снова возьмёт стандартный модуль.
    sqlite3, connector = _sqlite_driver(path)
    db._SQ = sqlite3
    db._CONN = await aiosqlite.Connection(connector, 64)
    db._CONN.row_factory = sqlite3.Row
    # Функции для серверного списка пациентов (`patients_rows`): та же
    # свёртка диакритики и те же «только цифры», что у Python (`fold`,
    # `_digits`: ими разбирается запрос), — иначе «Bălan» запроса и «Bălan»
    # картотеки считались бы разными людьми. Только чтение: регистрируем на
    # единственном соединении, которым ходит `_fetch`.
    await db._CONN.create_function("dp_fold", 1, _fold, deterministic=True)
    await db._CONN.create_function("dp_digits", 1, _digits, deterministic=True)
    await db._CONN.execute("PRAGMA journal_mode=WAL")
    await db._CONN.execute("PRAGMA foreign_keys=ON")
    await db._CONN.executescript(SQLITE_SCHEMA)
    for coldef in SQLITE_PATIENT_COLS:
        try:
            await db._CONN.execute(f"ALTER TABLE patients ADD COLUMN {coldef}")
        except sqlite3.OperationalError as e:
            # «duplicate column» = уже мигрировано; всё прочее (база залочена,
            # I/O) НЕ глотаем — иначе колонка тихо пропадёт и всплывёт позже
            if "duplicate column" not in str(e).lower():
                raise
    await db._CONN.executescript(SQLITE_CARD_SCHEMA)
    for table, coldef in SQLITE_EXTRA_COLS:
        try:
            await db._CONN.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    await db._CONN.commit()
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
    conn, db._CONN = db._CONN, None
    if conn is not None:
        await conn.close()
