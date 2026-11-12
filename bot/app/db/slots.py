"""Защита слотов от двойной записи: замок брони, страховочные индексы, бронь.

Здесь всё, на чём держится «один врач — один пациент в один час»: процессный
замок `_slot_lock`, прикладная проверка пересечений (`_conflicts`,
`_patient_busy_at`), сама вставка `_book_locked` и три уникальных индекса с
лестницей предикатов — их кладёт ТОЛЬКО `_slot_guard_apply`, сперва спросив
данные (урок 1.20.0: у клиники с двумя местами программа перестала
стартовать)."""
from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import datetime

from .. import db
from .conn import _fetch, _iso, _utcnow_iso, del_meta, get_meta, log, set_meta
from .events import _log_booking, EVENT_TEXT_MAX, log_clinic_event


# Записи, которые ЗАНИМАЮТ слот врача. 'waiting' (пациент пришёл, ждёт в
# приёмной, 08-13) стоит между confirmed и arrived: физически человек уже в
# клинике, и слот его. 'arrived' (пациент в кабинете) обязан
# быть здесь: иначе отметка «пришёл» освобождает час и бот сажает второго.
ACTIVE_STATUSES = ("confirmed", "waiting", "arrived")
_ACT_SQL = "('confirmed','waiting','arrived')"

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
# Шаг, на котором индексы врача получают кабинет в ключе; старт не роняет.
UQ_ROOM_STEP = 11
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
    # COALESCE обязателен: NULL в уникальном индексе не равен NULL, и две
    # записи без кабинета на один час индекс пропустил бы.
    body = {
        "uq_doc_room_slot":
            f"""CREATE UNIQUE INDEX uq_doc_room_slot
                ON appointments(doctor, COALESCE(room_id, ''), starts_at)
                WHERE status IN {act_sql}""",
        "uq_patient_slot":
            f"""CREATE UNIQUE INDEX uq_patient_slot ON appointments(patient_id, starts_at)
                WHERE status IN {act_sql}""",
        "uq_docid_room_slot":
            f"""CREATE UNIQUE INDEX uq_docid_room_slot
                ON appointments(doctor_id, COALESCE(room_id, ''), starts_at)
                WHERE status IN {act_sql} AND doctor_id IS NOT NULL""",
    }
    out: list[str] = []
    for name in (names or tuple(body)):
        out.append(f"DROP INDEX IF EXISTS {name}")
        out.append(body[name])
    return out


# ---------- страховочные индексы слота ----------

# Три уникальных индекса, которые И ЕСТЬ защита от двойной брони. ⚠️ Владелец у
# них ОДИН — _slot_guard_apply: ни базовая схема, ни обычные шаги миграций их
# больше не создают. Причина в том, что CREATE UNIQUE INDEX — операция НАД
# ЖИВЫМИ ДАННЫМИ: у клиники с двойной бронью он падает, а падение в базовой
# схеме или в обычном шаге = «после обновления программа не открывается», и
# навсегда (08-16).
_UQ_SLOT = ("uq_doc_room_slot", "uq_patient_slot", "uq_docid_room_slot")

# Индексы врача без кабинета в ключе и их преемники. Снимаются, только когда
# преемник уже лежит: до того старый индекс и есть защита. Старая версия
# программы после отката кладёт их снова — отсюда проверка на каждом старте.
_UQ_RETIRED = {"uq_doctor_slot": "uq_doc_room_slot",
               "uq_doctor_slot_id": "uq_docid_room_slot"}

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
        ("uq_doc_room_slot", "medic",
         f"""SELECT a.doctor AS who, a.starts_at AS starts_at, count(*) AS n
               FROM appointments a
              WHERE a.status IN {act_sql}
              GROUP BY a.doctor, COALESCE(a.room_id, ''), a.starts_at
             HAVING count(*) > 1"""),
        ("uq_docid_room_slot", "medic",
         f"""SELECT min(a.doctor) AS who, a.starts_at AS starts_at, count(*) AS n
               FROM appointments a
              WHERE a.status IN {act_sql} AND a.doctor_id IS NOT NULL
              GROUP BY a.doctor_id, COALESCE(a.room_id, ''), a.starts_at
             HAVING count(*) > 1"""),
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
             "FROM sqlite_master WHERE type='index' AND name IN ("
             + ",".join(f"'{n}'" for n in (*_UQ_SLOT, *_UQ_RETIRED)) + ")")


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
    """Имя слотового индекса → текст его определения, ПО ФАКТУ в базе. Вместе
    с действующими сюда попадают и снятые с вооружения (`_UQ_RETIRED`)."""
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
    "uq_doc_room_slot": "aceeași oră la același medic",
    "uq_patient_slot": "aceeași oră la același pacient",
    "uq_docid_room_slot": "aceeași oră la medicul redenumit",
}

_UQ_WAS = {new: old for old, new in _UQ_RETIRED.items()}


def _uq_stale(state: dict[str, str]) -> list[str]:
    """Снятые с вооружения индексы, которые в базе ещё лежат."""
    return [name for name in _UQ_RETIRED if name in state]


def _uq_gone(state: dict[str, str]) -> list[str]:
    """Слотовые индексы, которых в базе НЕТ ВООБЩЕ.

    ⭐ Это единственное, что код про страховку знает наверняка, и потому
    единственное, о чём он имеет право говорить директору. «Предикат уже
    ожидаемого» — не «защиты нет»: такая проверка стоит и работает, просто не
    покрывает waiting-визиты.
    """
    # пока преемник не лёг, его работу делает прежний индекс — он строже
    return [name for name in _UQ_SLOT
            if name not in state and _UQ_WAS.get(name) not in state]


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
                await db._CONN.execute(sql)
            await db._CONN.commit()
        except Exception as e:  # noqa: BLE001 — соседей это не касается
            log.error("uq-индекс %s (%s) не лёг: %r", name, act_sql, e)


async def _retire_old_uq() -> None:
    """Снять прежние индексы врача там, где преемник уже лежит и не уже.
    Каждый своим try: отказ не трогает ни соседа, ни старт."""
    state = await _uq_index_state()
    for old, new in _UQ_RETIRED.items():
        if old not in state or new not in state:
            continue
        if not _uq_statuses(state[new]) >= _uq_statuses(state[old]):
            continue
        try:
            await db._CONN.execute(f"DROP INDEX IF EXISTS {old}")
            await db._CONN.commit()
        except Exception as e:  # noqa: BLE001 — старт важнее
            log.error("прежний uq-индекс %s не снят: %r", old, e)


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
        await _retire_old_uq()
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
    if (not unknown and not rows and _uq_matches(state, _ACT_SQL)
            and not _uq_stale(state)):
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
        if _uq_stale(state):
            # прежние индексы вернула старая версия после отката; снять их —
            # не починка, строки в летописи нет
            await _slot_guard_apply()
        return                       # всё на месте — обычный старт
    # ⚠️ Причина едет ОТСЮДА: только здесь ещё видно, чего не хватало ДО работы.
    # После _slot_guard_apply состояние уже другое, и различить «пропали» и
    # «были уже ожидаемого» будет нечем — а летопись пишет строку навсегда.
    why = UQ_REPAIR_GONE if _uq_gone(state) else UQ_REPAIR_NARROW
    log.error("слотовые индексы не на месте (%r, %s) — восстанавливаю",
              sorted(state), why)
    await _slot_guard_apply(repair=why)


async def _book(pid: int, service: str, doctor: str, starts_at: datetime,
                source: str, doctor_id: str | None, service_id: str | None,
                duration_min: int, rooms: dict | None = None,
                room: str | None = None) -> int | str | None:
    """Вставка визита пациенту, который УЖЕ известен по id. Контракт возврата
    тот же, что у create_appointment (id / None / 'dup')."""
    async with _slot_lock():
        return await _book_locked(pid, service, doctor, starts_at, source,
                                  doctor_id, service_id, duration_min,
                                  rooms=rooms, room=room)


async def _book_locked(pid: int, service: str, doctor: str, starts_at: datetime,
                       source: str, doctor_id: str | None,
                       service_id: str | None,
                       duration_min: int, rooms: dict | None = None,
                       room: str | None = None) -> int | str | None:
    """Тело брони. Звать ТОЛЬКО под _slot_lock: asyncio.Lock не реентерабелен,
    и create_appointment, которому замок нужен раньше (проверка до создания
    пациента), иначе повис бы на самом себе."""
    # ⚠️ «у пациента уже есть запись» спрашиваем ЗАРАНЕЕ, а не ловим по
    # тексту IntegrityError: SQLite называет в нём колонки, а не индекс, и
    # проверка на 'uq_patient_slot' не срабатывала никогда — дубль пациента
    # показывался регистратуре как «интервал занят у этого врача».
    # Проверка идёт первой: она точнее, чем конфликт врача, и под _slot_lock
    # так же надёжна, как индекс.
    if await _patient_busy(pid, doctor_id, doctor, starts_at, duration_min):
        return "dup"
    # интервальная проверка: uq-индексы ловят только одинаковые старты,
    # пересечение 10:00(60') с 10:30(60') обязано отсекаться здесь
    lane = await _pick_room(doctor_id, doctor, starts_at, duration_min,
                            rooms, room)
    if lane is None:
        return None
    try:
        cur = await db._CONN.execute(
            """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                        source, doctor_id, service_id,
                                        duration_min, room_id, room, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, service, doctor, _iso(starts_at), source,
             doctor_id, service_id, duration_min, lane or None,
             _room_label(rooms, lane), _utcnow_iso()),
        )
        await db._CONN.commit()
        appt_id = cur.lastrowid
        await cur.close()
        await _log_booking(pid, service, doctor, starts_at, source)
        return appt_id
    except db._SQ.IntegrityError as e:
        await db._CONN.rollback()
        # страховка на случай гонки мимо замка. Текст SQLite —
        # «UNIQUE constraint failed: appointments.patient_id,
        # appointments.starts_at», имени индекса в нём НЕТ.
        return "dup" if "patient_id" in str(e) else None


async def _patient_busy_at(pid: int, starts_at: datetime,
                           exclude_id: int | None = None) -> bool:
    """Есть ли у пациента активная запись РОВНО на этот старт — то же, что
    стережёт uq_patient_slot, но ответом, а не исключением. Вызывать под
    _slot_lock.

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


async def _patient_busy(pid: int, doctor_id: str | None, doctor: str,
                        starts_at: datetime, duration_min: int,
                        exclude_id: int | None = None) -> bool:
    """Занят ли пациент: тот же старт у кого угодно либо пересечение по
    минутам у ЭТОГО врача (в двух его кабинетах сразу человек не сидит). У
    разных врачей пересечение намеренно не ищем — пациента ставят к двум
    врачам подряд."""
    if await _patient_busy_at(pid, starts_at, exclude_id):
        return True
    return any(r["patient_id"] == pid for r in await _doctor_overlaps(
        doctor_id, doctor, starts_at, duration_min, exclude_id))


async def _doctor_overlaps(doctor_id: str | None, doctor: str,
                           starts_at: datetime, duration_min: int,
                           exclude_id: int | None = None) -> list:
    """Активные записи врача, пересекающие интервал по минутам."""
    from datetime import timedelta
    pad = timedelta(minutes=240)
    rows = await _fetch(
        f"""SELECT id, patient_id, starts_at, duration_min, room_id, source
           FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL} AND starts_at >= ? AND starts_at < ?""",
        doctor_id or "", doctor, _iso(starts_at - pad), _iso(starts_at + pad),
    )
    end = starts_at + timedelta(minutes=duration_min)
    return [r for r in rows
            if r["id"] != exclude_id and r["starts_at"] < end
            and starts_at < r["starts_at"] + timedelta(
                minutes=int(r["duration_min"] or 60))]


def _lane(room_id: str | None, own: tuple) -> str:
    """Кабинет, который запись занимает у врача с кабинетами `own`: свой, пока
    он числится за врачом, иначе первый (записи без кабинета и в убранном
    кабинете). Пусто — у врача кабинетов нет."""
    return room_id if room_id in own else (own[0] if own else "")


def _room_label(rooms: dict | None, lane: str | None) -> str:
    """Имя кабинета для снимка в записи."""
    return str(((rooms or {}).get("names") or {}).get(lane, "")) if lane else ""


async def _pick_room(doctor_id: str | None, doctor: str, starts_at: datetime,
                     duration_min: int, rooms: dict | None = None,
                     room: str | None = None, prefer: str | None = None,
                     exclude_id: int | None = None,
                     note: bool = False) -> str | None:
    """В какой кабинет врача ложится интервал; None — некуда (занято).

    `room` — кабинет назначен, другой не подставляется; иначе `prefer`
    (кабинет, где запись уже стоит), затем первый свободный по порядку. Заметка
    стойки занимает врача целиком — в обе стороны. Без `rooms` у врача одна
    запись в один момент. Под _slot_lock, когда за ответом следует запись."""
    own = tuple((rooms or {}).get("own") or ())
    if room and room not in own:
        return None
    busy = await _doctor_overlaps(doctor_id, doctor, starts_at, duration_min,
                                  exclude_id)
    if busy and (note or any(r["source"] == "note" for r in busy)):
        return None
    taken = {_lane(r["room_id"], own) for r in busy}
    if room:
        return None if room in taken else room
    order = ([prefer] if prefer and prefer in own else []) + list(own or ("",))
    return next((x for x in order if x not in taken), None)


async def _conflicts(doctor_id: str | None, doctor: str, starts_at: datetime,
                     duration_min: int, exclude_id: int | None = None,
                     rooms: dict | None = None, room: str | None = None,
                     note: bool = False) -> bool:
    """Некуда ли поставить интервал у этого врача. Вызывать ПОД _slot_lock —
    уникальные индексы ловят только совпадающие старты."""
    return await _pick_room(doctor_id, doctor, starts_at, duration_min, rooms,
                            room, exclude_id=exclude_id, note=note) is None


async def room_busy(room_id: str | None, starts_at: datetime, duration_min: int,
                    doctor_id: str | None, rooms: dict | None,
                    exclude_id: int | None = None) -> bool:
    """Стоит ли в этом кабинете в это время запись ДРУГОГО врача. Повод
    предупредить, не отказать: клиники делят кабинет между врачами по сменам.
    Заметки стойки не считаются."""
    from datetime import timedelta
    if not room_id:
        return False
    by_doctor = (rooms or {}).get("by_doctor") or {}
    pad = timedelta(minutes=240)
    rows = await _fetch(
        f"""SELECT id, doctor_id, starts_at, duration_min, room_id
           FROM appointments
           WHERE doctor_id IS NOT NULL AND doctor_id != ? AND source != 'note'
             AND status IN {_ACT_SQL} AND starts_at >= ? AND starts_at < ?""",
        doctor_id or "", _iso(starts_at - pad), _iso(starts_at + pad),
    )
    end = starts_at + timedelta(minutes=duration_min)
    return any(
        r["id"] != exclude_id and r["starts_at"] < end
        and starts_at < r["starts_at"] + timedelta(
            minutes=int(r["duration_min"] or 60))
        and _lane(r["room_id"],
                  tuple(by_doctor.get(r["doctor_id"]) or ())) == room_id
        for r in rows)


async def appt_room_busy(appt_id: int, rooms: dict | None) -> bool:
    """`room_busy` для уже стоящей записи."""
    rows = await _fetch(
        """SELECT doctor_id, starts_at, duration_min, room_id
           FROM appointments WHERE id = ?""", appt_id)
    if not rows or not rows[0]["room_id"]:
        return False
    r = rows[0]
    return await room_busy(r["room_id"], r["starts_at"],
                           int(r["duration_min"] or 60), r["doctor_id"], rooms,
                           exclude_id=appt_id)


async def slot_probe(doctor_id: str | None, doctor: str, starts_at: datetime,
                     duration_min: int, rooms: dict | None = None,
                     room: str | None = None, exclude_id: int | None = None,
                     pid: int | None = None) -> dict:
    """Занятость «на сухую» — правилом брони, без замка и без записи (для
    предпросмотра; правду скажет сама бронь): `room` — куда легла бы запись
    (None — занято), `room_busy` — кабинет занят другим врачом, `dup` — пациент
    `pid` в это время занят."""
    lane = await _pick_room(doctor_id, doctor, starts_at, duration_min, rooms,
                            room, exclude_id=exclude_id)
    return {
        "free": lane is not None, "room": lane,
        "room_busy": bool(lane) and await room_busy(
            lane, starts_at, duration_min, doctor_id, rooms, exclude_id),
        "dup": pid is not None and await _patient_busy(
            pid, doctor_id, doctor, starts_at, duration_min, exclude_id),
    }
