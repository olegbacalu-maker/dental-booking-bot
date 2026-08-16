"""Миграции базы и разовый backfill летописи — на базе, какой она БЫВАЕТ у
клиники, а не на пустой.

Два набора и два разных вопроса:

* `suite_v4` — база, домигрированная до версии 3 кодом до 08-13: uq-индексы
  со старым предикатом IN ('confirmed','arrived'). Шаг 4 существовал в обоих
  словарях миграций, но SCHEMA_VERSION осталась 3, и цикл _migrate до него не
  доходил НИКОГДА — waiting-визит был вне страховки от двойной брони, молча.
  Сторож «missing migration step» ловит только отсутствующие шаги, не лишние.
* `suite_v4_conflict` — та же база, но с двойной бронью, которую старый
  предикат пропускал. Шаг 4 упирается в неё, и вопрос набора один: программа
  ОТКРЫВАЕТСЯ ли. Развести записи может только человек, поэтому цена ошибки
  здесь — не «защита слабее», а «клиника осталась без программы». Здесь же
  проверяется ПОВЕДЕНИЕ узкой страховки, а не текст её индексов: двойная бронь
  под ней действительно отбивается базой.
* `suite_v0_conflict` — база СТАРШЕ v1.7.0: предикат её индексов ещё уже
  запасного (`status='confirmed'`), и пара confirmed+arrived, которую он
  пропускал, нарушает ОБЕ ступени лестницы. Вопрос набора: осталась ли у
  клиники та защита, которая у неё БЫЛА. Замер до и после — поведением базы, а
  не текстом индексов.
* `suite_from_1200` — база, пришедшая от ОПУБЛИКОВАННОЙ v1.20.0: два индекса
  успели лечь ШИРОКИМИ, третий не лёг. Вопрос набора один и главный:
  обновление не имеет права уменьшить защиту, которая у клиники РАБОТАЛА.
  Ступень, выбранная одна на все три, уводила такую базу на три узких.
* `suite_selfheal` — база версии 4 без слотовых индексов и без метки. Пока
  индексы стояли в базовой схеме, пропавшее возвращал `CREATE … IF NOT EXISTS`
  при каждом старте; у единственного владельца самолечения не было, и такая
  база стартовала МОЛЧА — ни защиты, ни следа.
* `suite_selfheal_narrow` — та же ветка, но событие ДРУГОЕ: индексы стояли и
  работали, просто узкие. Одна строка летописи на два события врёт про одно из
  них, а хранится она готовой и навсегда.
* `suite_step4_list` — список шага 4 не мёртв: дописанный в него оператор
  ИСПОЛНЯЕТСЯ. Иначе через месяц туда допишут ALTER, прогон останется зелёным,
  а у клиники операция не выполнится, и версия схемы соврёт, что выполнена.
* `suite_slot_guard_no_data` — шаг упёрся НЕ в данные (отказал сам подсчёт
  конфликтов). Баннер и летопись обязаны описывать то, что есть: строка
  «0 ore au mai multe programări active» уезжает в летопись навсегда.
* `suite_v2_conflict` — база, застрявшая на ВЕРСИИ 2 (клиника установлена на
  v1.7.0 и не обновлялась), у которой переименовали врача. Шаги 2 и 3 клали те
  же уникальные индексы обычной веткой цикла и роняли старт навсегда — защита
  шага 4 их не касалась. С 08-16 у слотовых индексов один владелец.
* `suite_uq_apply_fails` — раскладка индексов ОТКАЗАЛА. Единственный вопрос:
  говорит ли баннер правду. Обещание «прежняя защита цела» без проверки хуже
  молчания: директор читает, что всё под контролем, а двойная запись проходит.
* `suite_uq_event_len` — ни одна строка летописи про страховку не упирается в
  потолок колонки. Обрезка идёт посреди слова и навсегда, и не влезал ровно
  самый тревожный случай — тот, где в конце стояло «позовите поддержку».
* `suite_uq_all_gone` — в базе не осталось НИ ОДНОЙ проверки: этот текст и не
  влезал. Здесь он меряется на живой базе, а не арифметикой.
* `suite_uq_state_unreadable` — состояние индексов прочитать НЕ УДАЛОСЬ. Третий
  исход: пустой ответ прежде читался как «в базе нет ничего», и директор получал
  приговор всей защите на картотеке, где все три индекса целы и работают.
* `suite_slot_banner_roles` — кому этот баннер виден. Он про устройство базы, а
  не про работу стойки: регистратура и врач починить это не могут, и строка,
  которую нельзя погасить, у них превратилась бы в фон.
* `suite_backfill_tz` — перенос старых визитов в летопись. Живой путь
  (_log_booking) печатает час клиники, backfill печатал UTC: у клиники с
  историей каждая перенесённая строка показывала бы чужой час НАВСЕГДА —
  текст события хранится строкой и не пересчитывается.

Фикстурная база собирается сырым sqlite3 — это ТЕСТ-СТОРОНА (как в
test_dbcrypt._plain_db), программа по-прежнему ходит только через db.
"""
import pathlib
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import db as appdb  # noqa: E402 — только константы схем, не соединение

from harness import BOT, Client, Result, Server  # noqa: E402

# Предикат, который шаги 2–3 ставили ДО появления 'waiting' (08-13): ровно так
# выглядят индексы у реальной клиники, чья база остановилась на версии 3.
_OLD_ACT = "('confirmed','arrived')"

# Предикат, к которому ведёт шаг 4. Литерал, а не appdb._ACT_SQL, намеренно:
# фикстура описывает состояние, которое у клиники БЫЛО, и уехать вслед за
# константой она не имеет права — иначе однажды опишет то, чего не бывало.
_WIDE_ACT = "('confirmed','waiting','arrived')"

_UQ = ("uq_doctor_slot", "uq_patient_slot", "uq_doctor_slot_id")

_APPT_SQL = ("INSERT INTO appointments(patient_id, service, doctor, starts_at, "
             "status, source, created_at, doctor_id) "
             "VALUES(?, 'Consultație', ?, ?, ?, 'admin', "
             "'2026-01-10T08:05:00+00:00', ?)")


def _base_db(path: pathlib.Path) -> sqlite3.Connection:
    """Пустая база по СЕГОДНЯШНИМ схемам программы + колонка doctor_id
    (в проде её добавляет init через SQLITE_EXTRA_COLS)."""
    con = sqlite3.connect(str(path))
    con.executescript(appdb.SQLITE_SCHEMA)
    con.executescript(appdb.SQLITE_CARD_SCHEMA)
    con.execute("ALTER TABLE appointments ADD COLUMN doctor_id TEXT")
    return con


def _index_sql(dbfile: pathlib.Path) -> dict[str, str]:
    con = sqlite3.connect(str(dbfile))
    try:
        rows = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'uq_%'").fetchall()
        return {name: sql or "" for name, sql in rows}
    finally:
        con.close()


def _meta(dbfile: pathlib.Path, key: str):
    con = sqlite3.connect(str(dbfile))
    try:
        row = con.execute("SELECT value FROM schema_meta WHERE key = ?",
                          (key,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _activity(dbfile: pathlib.Path, kind: str) -> list[str]:
    con = sqlite3.connect(str(dbfile))
    try:
        return [r[0] for r in con.execute(
            "SELECT text FROM activity WHERE kind = ? ORDER BY id", (kind,))]
    finally:
        con.close()


def _blocked(dbfile: pathlib.Path, *args) -> bool:
    """Отбивает ли САМА база вторую запись в занятый слот.

    ⭐ Вопрос к ПОВЕДЕНИЮ, а не к тексту индекса: индекс, который существует, но
    ничего не стережёт (предикат мимо статусов), по тексту неотличим от рабочего.
    Запись откатывается — база остаётся такой, какой была до вопроса.
    """
    con = sqlite3.connect(str(dbfile))
    try:
        con.execute(_APPT_SQL, args)
        return False
    except sqlite3.IntegrityError:
        return True
    finally:
        con.rollback()
        con.close()


def _patched_bot(work: pathlib.Path, patch: str) -> pathlib.Path:
    """Копия дерева `bot\\` с дописанным в конец `app/db.py` кодом.

    Тот же приём, что в mutate.py, и по той же причине: настоящее дерево не
    трогается. Нужен там, где проверяемое поведение снаружи не вызвать —
    исполняется ли список шага миграции; что говорит программа, когда отказал не
    CREATE, а сам подсчёт конфликтов (подделать это данными нечем).
    """
    dst = work / "bot"
    shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
    f = dst / "app" / "db.py"
    f.write_text(f.read_text(encoding="utf-8") + patch, encoding="utf-8")
    return dst


def _patients(con: sqlite3.Connection, *names: str) -> None:
    for i, name in enumerate(names, 1):
        con.execute("INSERT INTO patients(session_key, name, phone, created_at) "
                    "VALUES(?, ?, ?, '2026-01-10T08:00:00+00:00')",
                    (f"manual:6000000{i}", name, f"06000000{i}"))


def _v2_db(dbfile: pathlib.Path) -> sqlite3.Connection:
    """База клиники, застрявшей на ВЕРСИИ 2: индексы по имени врача и по
    пациенту уже узкие, а uq_doctor_slot_id ещё НЕТ — его кладёт шаг 3."""
    con = _base_db(dbfile)
    for name in _UQ:
        con.execute(f"DROP INDEX IF EXISTS {name}")
    con.execute(f"""CREATE UNIQUE INDEX uq_doctor_slot
        ON appointments(doctor, starts_at) WHERE status IN {_OLD_ACT}""")
    con.execute(f"""CREATE UNIQUE INDEX uq_patient_slot
        ON appointments(patient_id, starts_at) WHERE status IN {_OLD_ACT}""")
    con.execute("INSERT INTO schema_meta(key, value) VALUES('version', '2')")
    con.execute("INSERT INTO schema_meta(key, value) VALUES('act_backfill', '1')")
    return con


def _v0_db(dbfile: pathlib.Path) -> sqlite3.Connection:
    """База клиники СТАРШЕ v1.7.0: schema_meta пуста (версии нет вовсе), а
    слотовые индексы — те, что клала тогдашняя базовая схема: предикат
    `status='confirmed'`, ещё уже запасного, и без uq_doctor_slot_id (его завёл
    шаг 3). Пару confirmed+arrived такой индекс пропускал — в этом и дыра."""
    con = _base_db(dbfile)
    for name in _UQ:
        con.execute(f"DROP INDEX IF EXISTS {name}")
    con.execute("""CREATE UNIQUE INDEX uq_doctor_slot
        ON appointments(doctor, starts_at) WHERE status='confirmed'""")
    con.execute("""CREATE UNIQUE INDEX uq_patient_slot
        ON appointments(patient_id, starts_at) WHERE status='confirmed'""")
    return con


def _v1200_db(dbfile: pathlib.Path) -> sqlite3.Connection:
    """База, пришедшая от ОПУБЛИКОВАННОЙ v1.20.0, у которой шаг 4 не доделался.

    Её шаг 4 шёл «три DROP, потом три CREATE», поэтому у клиники с
    переименованным врачом падал ТРЕТИЙ CREATE — а первые два уже легли
    ШИРОКИМИ и автокоммитнулись (DDL в SQLite вне транзакции). Версия схемы при
    этом осталась 3: исключение пробрасывалось наружу, и программа не
    открывалась. Ровно такая база и приходит к нам на обновление.
    ⚠️ Предикат тут ШИРОКИЙ, и это главное: у клиники уже работает защита, до
    которой мы только собираемся её довести.
    """
    con = _base_db(dbfile)
    for name in _UQ:
        con.execute(f"DROP INDEX IF EXISTS {name}")
    con.execute(f"""CREATE UNIQUE INDEX uq_doctor_slot
        ON appointments(doctor, starts_at) WHERE status IN {_WIDE_ACT}""")
    con.execute(f"""CREATE UNIQUE INDEX uq_patient_slot
        ON appointments(patient_id, starts_at) WHERE status IN {_WIDE_ACT}""")
    con.execute("INSERT INTO schema_meta(key, value) VALUES('version', '3')")
    con.execute("INSERT INTO schema_meta(key, value) VALUES('act_backfill', '1')")
    return con


def _v3_db(dbfile: pathlib.Path) -> sqlite3.Connection:
    """База клиники, домигрированная до версии 3 кодом ДО 08-13: uq-индексы со
    старым предикатом и летопись, уже перенесённая (эти наборы не про backfill).
    """
    con = _base_db(dbfile)
    for name in ("uq_doctor_slot", "uq_patient_slot", "uq_doctor_slot_id"):
        con.execute(f"DROP INDEX IF EXISTS {name}")
    con.execute(f"""CREATE UNIQUE INDEX uq_doctor_slot
        ON appointments(doctor, starts_at) WHERE status IN {_OLD_ACT}""")
    con.execute(f"""CREATE UNIQUE INDEX uq_patient_slot
        ON appointments(patient_id, starts_at) WHERE status IN {_OLD_ACT}""")
    con.execute(f"""CREATE UNIQUE INDEX uq_doctor_slot_id
        ON appointments(doctor_id, starts_at)
        WHERE status IN {_OLD_ACT} AND doctor_id IS NOT NULL""")
    con.execute("INSERT INTO schema_meta(key, value) VALUES('version', '3')")
    con.execute("INSERT INTO schema_meta(key, value) VALUES('act_backfill', '1')")
    return con


def suite_v4(res: Result) -> None:
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_"))
    try:
        dbfile = work / "dental.db"
        # индексы в том виде, в каком их оставили шаги 2–3 у клиники
        con = _v3_db(dbfile)
        # индексы пересоздаются НАД данными, а не над пустой таблицей
        con.execute("INSERT INTO patients(session_key, name, phone, created_at) "
                    "VALUES('manual:60000001', 'Ion Test', '060000001', "
                    "'2026-01-10T08:00:00+00:00')")
        con.execute("INSERT INTO appointments(patient_id, service, doctor, "
                    "starts_at, status, source, created_at, doctor_id) "
                    "VALUES(1, 'Consultație', 'Dr. Activ Doi', "
                    "'2026-01-12T07:00:00+00:00', 'confirmed', 'admin', "
                    "'2026-01-10T08:05:00+00:00', 'd2')")
        con.commit()
        con.close()

        with Server(dir_=work):
            pass                              # старт = init + _migrate

        con = sqlite3.connect(str(dbfile))
        ver = con.execute(
            "SELECT value FROM schema_meta WHERE key='version'").fetchone()[0]
        con.close()
        res.check("база с версии 3 домигрирована до 4", ver, "4")

        idx = _index_sql(dbfile)
        for name in ("uq_doctor_slot", "uq_patient_slot", "uq_doctor_slot_id"):
            res.ok(f"{name} покрывает 'waiting'", "waiting" in idx.get(name, ""),
                   f"предикат остался старым: {idx.get(name)!r}")
        # ⚠️ Метка незавершённости на чистой базе не имеет права остаться: она
        # заставляет КАЖДЫЙ старт заново перекладывать индексы и держит баннер
        res.check("метки незавершённости нет", _meta(dbfile, "uq_waiting_pending"),
                  None)
        # ⚠️ Метку шаг ставит ДО работы и снимает ПОСЛЕ успеха (чтобы падение
        # где угодно оставило след). Отсюда риск: «защита восстановлена» в ленте
        # у КАЖДОЙ клиники, которой чинить было нечего. Событие пишется только
        # тогда, когда метка досталась от прошлого старта.
        res.check("обычная миграция не пишет в летопись",
                  len(_activity(dbfile, "uq_guard")), 0)

        # идемпотентность: второй старт на уже домигрированной базе
        with Server(dir_=work):
            pass
        con = sqlite3.connect(str(dbfile))
        ver = con.execute(
            "SELECT value FROM schema_meta WHERE key='version'").fetchone()[0]
        con.close()
        res.check("повторный старт ничего не ломает (версия та же)", ver, "4")
        idx = _index_sql(dbfile)
        res.ok("повторный старт не откатывает предикат",
               all("waiting" in idx.get(n, "")
                   for n in ("uq_doctor_slot", "uq_patient_slot",
                             "uq_doctor_slot_id")),
               f"индексы после рестарта: {idx!r}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _schema_cookie(dbfile: pathlib.Path) -> int:
    """Счётчик изменений схемы SQLite. Растёт на КАЖДОМ DDL — по нему видно,
    перекладывались индексы или нет, а по тексту индекса этого не узнать."""
    con = sqlite3.connect(str(dbfile))
    try:
        return int(con.execute("PRAGMA schema_version").fetchone()[0])
    finally:
        con.close()


def suite_v4_conflict(res: Result) -> None:
    """База версии 3, в которой ДВЕ живые записи стоят в одном слоте.

    Старый предикат IN ('confirmed','arrived') такую пару пропускал — в этом и
    дыра, которую закрывает шаг 4, — поэтому у клиники с двумя рабочими местами
    (LAN, 08-13) или после возврата отменённого визита в работу она реальна. До
    08-16 CREATE UNIQUE INDEX на ней падал, init пробрасывал исключение, версия
    схемы оставалась 3 — и падение повторялось при КАЖДОМ запуске: у клиники
    это «после обновления программа не открывается».

    Конфликта здесь ДВА и они разного рода: час, занятый дважды у ВРАЧА, и час,
    на который дважды записан ПАЦИЕНТ. Второй чинится только сменой ЧАСА —
    перенос к другому медику ту же пару оставляет, — поэтому баннер обязан их
    различать.
    """
    # 09:00 и 10:00 Кишинёва: баннер называет час КЛИНИКИ, а в базе лежит UTC
    tz = ZoneInfo("Europe/Chisinau")
    doc_at = datetime(2026, 1, 12, 9, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")
    pat_at = datetime(2026, 1, 12, 10, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_cf_"))
    try:
        dbfile = work / "dental.db"
        con = _v3_db(dbfile)
        _patients(con, "Ion Test", "Maria Test")
        # двойная бронь у ВРАЧА: тот же врач и час, confirmed + waiting
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", doc_at, "confirmed", "d2"))
        con.execute(_APPT_SQL, (2, "Dr. Activ Doi", doc_at, "waiting", "d2"))
        # двойная бронь у ПАЦИЕНТА: один человек, один час, РАЗНЫЕ врачи —
        # у медиков часы при этом свободны, и совет «перенесите к другому» тут
        # не помогает вовсе
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", pat_at, "confirmed", "d2"))
        con.execute(_APPT_SQL, (1, "Dr. Activ Trei", pat_at, "waiting", "d3"))
        con.commit()
        con.close()

        with Server(dir_=work) as s:
            # сам факт входа в блок и есть главная проверка: до 08-16 сервер
            # не поднимался вовсе, и Server бросал «не ответил на /health»
            res.ok("программа стартует, несмотря на конфликт", True)
            body = Client(s.url).login().get("/admin").body

        res.check("версия схемы всё равно поднята до 4",
                  _meta(dbfile, "version"), "4")
        res.check("метка незавершённости стоит",
                  _meta(dbfile, "uq_waiting_pending") is not None, True)

        idx = _index_sql(dbfile)
        for name in _UQ:
            sql = idx.get(name, "")
            res.ok(f"{name} существует с прежним, узким предикатом",
                   "confirmed" in sql and "waiting" not in sql,
                   f"защита слабее прежней или её нет: {sql!r}")

        res.ok("конфликт врача назван врачом",
               "<b>Medic:</b> Dr. Activ Doi · 12.01.2026 09:00 · 2 programări"
               in body,
               "директор не видит, ЧТО разводить; в ответе нет ни имени врача, "
               "ни часа (UTC был бы 07:00), либо не сказано, что это медик")
        res.ok("конфликт пациента назван пациентом",
               "<b>Pacient:</b> Ion Test · 12.01.2026 10:00 · 2 programări"
               in body,
               "имя пациента стоит в одном списке с врачами без признака — "
               "директор пойдёт искать несуществующего медика")
        res.ok("пациенту советуют менять ЧАС, а не врача",
               "schimbați <b>ora</b>" in body
               and "mutarea la alt medic nu ajută" in body,
               "совет «перенесите одну из записей» для конфликта пациента "
               "неверен: та же пара «пациент + час» остаётся")
        res.ok("баннер не обещает того, чего не проверял",
               "toate cele 3 verificări sunt în evidență (verificat)" in body,
               "текст утверждает целость прежней защиты, не спросив базу")

        # ---- ПОВЕДЕНИЕ узкой страховки, а не текст её предиката ----
        # ⭐ Набор до 08-16 сверял SQL индексов и был бы зелёным на индексе,
        # который существует, но ничего не стережёт.
        con = sqlite3.connect(str(dbfile))
        try:
            blocked = False
            try:
                con.execute(_APPT_SQL,
                            (1, "Dr. Altul", doc_at, "confirmed", "dX"))
            except sqlite3.IntegrityError:
                blocked = True
            res.ok("под узкой страховкой двойная бронь отбивается базой",
                   blocked,
                   "второй активный визит того же пациента на тот же час "
                   "прошёл — индекс есть, а защиты нет")
            # обратная сторона той же узости, и она ИЗВЕСТНА: 'waiting' в
            # предикат не входит, пока клиника не развела часы. Проверка стоит
            # здесь, чтобы «узкая» не превратилась однажды в «никакую» молча.
            passed = True
            try:
                con.execute(_APPT_SQL,
                            (2, "Dr. Activ Doi", doc_at, "waiting", "d2"))
            except sqlite3.IntegrityError:
                passed = False
            res.ok("узкая страховка именно узкая: waiting ещё вне предиката",
                   passed, "предикат оказался шире заявленного")
        finally:
            con.rollback()
            con.close()

        events = _activity(dbfile, "uq_guard")
        res.check("вмешательство описано в летописи один раз", len(events), 1)

        # ---- перезапуск: ни лишних строк в ленте, ни лишней перекладки ----
        cookie = _schema_cookie(dbfile)
        with Server(dir_=work):
            pass
        res.check("перезапуск не плодит строки в летописи",
                  len(_activity(dbfile, "uq_guard")), 1)
        res.check("перезапуск не перекладывает уже правильные индексы",
                  _schema_cookie(dbfile), cookie)

        # клиника развела записи руками — лишние визиты убраны
        con = sqlite3.connect(str(dbfile))
        con.execute("DELETE FROM appointments WHERE status = 'waiting'")
        con.commit()
        con.close()

        with Server(dir_=work) as s:
            body = Client(s.url).login().get("/admin").body
        idx = _index_sql(dbfile)
        res.ok("после разведения индексы стали широкими",
               all("waiting" in idx.get(n, "") for n in _UQ),
               f"страховка так и осталась узкой: {idx!r}")
        res.check("метка снялась сама",
                  _meta(dbfile, "uq_waiting_pending"), None)
        res.ok("баннер исчез", "Dr. Activ Doi · 12.01.2026 09:00" not in body,
               "предупреждение висит после того, как разводить нечего")
        res.check("возврат защиты записан в летопись",
                  len(_activity(dbfile, "uq_guard")), 2)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_v2_conflict(res: Result) -> None:
    """База, застрявшая на ВЕРСИИ 2, у которой переименовали врача.

    Ровно та патология, ради которой написан шаг 3: два визита в один час с
    одним doctor_id и РАЗНЫМИ именами. Индекс по имени их пропускает, индекс по
    id — нет. До 08-16 защиту получил только шаг 4, а шаги 2 и 3 остались
    обычной веткой цикла и роняли старт навсегда: версия схемы не росла, и
    падение повторялось при каждом запуске.

    ⭐ Здесь же видно, ЗАЧЕМ ступень выбирается по каждому индексу отдельно:
    мешает эта пара ровно одному индексу из трёх. Опустить на запасную ступень
    всех троих значит оставить waiting-визиты вне защиты у врача и у пациента —
    там, где широкий предикат ложится без единого возражения.
    """
    local = datetime(2026, 1, 13, 9, 0, tzinfo=ZoneInfo("Europe/Chisinau"))
    starts = local.astimezone(timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_v2_"))
    try:
        dbfile = work / "dental.db"
        con = _v2_db(dbfile)
        _patients(con, "Ion Test", "Maria Test", "Vasile Test")
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", starts, "confirmed", "d2"))
        con.execute(_APPT_SQL, (2, "Dr. Doi Redenumit", starts, "waiting", "d2"))
        con.commit()
        con.close()

        with Server(dir_=work) as s:
            res.ok("клиника с версии 2 стартует, несмотря на конфликт", True)
            body = Client(s.url).login().get("/admin").body

        res.check("версия схемы доведена до 4", _meta(dbfile, "version"), "4")
        idx = _index_sql(dbfile)
        for name in ("uq_doctor_slot", "uq_patient_slot"):
            sql = idx.get(name, "")
            res.ok(f"{name} лёг ШИРОКИМ: конфликт был не у него",
                   "waiting" in sql,
                   f"ступень опущена всем троим ради одного: {sql!r}")
        sql = idx.get("uq_doctor_slot_id", "")
        res.ok("uq_doctor_slot_id лёг узким: под широким он не ложится",
               "confirmed" in sql and "waiting" not in sql,
               f"защиты нет или она шире данных: {sql!r}")
        # ⭐ И то же поведением: индекс, который существует, но ничего не
        # стережёт, по тексту неотличим от рабочего.
        res.ok("широкая защита врача действительно работает",
               _blocked(dbfile, 3, "Dr. Doi Redenumit", starts, "waiting", "dX"),
               "предикат по имени врача шире только на бумаге")
        res.ok("широкая защита пациента действительно работает",
               _blocked(dbfile, 2, "Dr. Cineva", starts, "waiting", "dZ"),
               "предикат по пациенту шире только на бумаге")
        res.ok("директору названы врач и час",
               "<b>Medic:</b> Dr. Activ Doi · 13.01.2026 09:00" in body,
               "баннер не назвал переименованного врача")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_v0_conflict(res: Result) -> None:
    """База старше v1.7.0: конфликт нарушает ОБЕ ступени лестницы.

    Предикат тогдашних индексов — `status='confirmed'`, и пара confirmed+arrived
    у одного врача на один час для них законна. Для широкой ступени она конфликт,
    и для запасной ('confirmed','arrived') — тоже. Одноступенчатый откат в этом
    месте сносил три индекса и не клал ни одного: замер до обновления — «отбито,
    отбито», после — «прошло, прошло», и НАВСЕГДА, потому что следующий старт
    повторяет ту же неудачу. Поэтому вопрос набора не про текст индексов, а про
    поведение базы: осталась ли у клиники защита, которая у неё БЫЛА.

    Второй вопрос — что читает директор. Защиты нет вовсе (баннер это говорит),
    и именно здесь совет «что развести» нужнее всего: разведение тех самых часов
    возвращает полную защиту на ближайшем старте само.
    """
    tz = ZoneInfo("Europe/Chisinau")
    at = datetime(2026, 1, 16, 9, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_v0_"))
    try:
        dbfile = work / "dental.db"
        con = _v0_db(dbfile)
        _patients(con, "Ion Test", "Maria Test")
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", at, "confirmed", "d2"))
        con.execute(_APPT_SQL, (2, "Dr. Activ Doi", at, "arrived", "d2"))
        con.commit()
        con.close()

        # ЗАМЕР ДО: слот врача и слот пациента база стережёт сама
        res.ok("до обновления: занятый час врача отбит базой",
               _blocked(dbfile, 2, "Dr. Activ Doi", at, "confirmed", "d2"),
               "фикстура не воспроизводит рабочую защиту — набор ничего не мерит")
        res.ok("до обновления: занятый час пациента отбит базой",
               _blocked(dbfile, 1, "Dr. Altul", at, "confirmed", "dX"),
               "фикстура не воспроизводит рабочую защиту — набор ничего не мерит")

        with Server(dir_=work) as s:
            res.ok("доверсионная база стартует", True)
            body = Client(s.url).login().get("/admin").body

        res.check("версия схемы доведена до 4", _meta(dbfile, "version"), "4")

        # ЗАМЕР ПОСЛЕ: то же самое, тем же способом
        res.ok("обновление НЕ сняло защиту врача",
               _blocked(dbfile, 2, "Dr. Activ Doi", at, "confirmed", "d2"),
               "работавший индекс снесён, а новый не лёг: у клиники двойная "
               "бронь теперь проходит молча, и так будет при каждом старте")
        res.ok("обновление НЕ сняло защиту пациента",
               _blocked(dbfile, 1, "Dr. Altul", at, "confirmed", "dX"),
               "тот же слом на индексе пациента")
        idx = _index_sql(dbfile)
        res.ok("прежние индексы на месте",
               "uq_doctor_slot" in idx and "uq_patient_slot" in idx,
               f"DROP сделан до того, как выяснилось, что CREATE не ляжет: {idx!r}")

        res.check("метка незавершённости стоит",
                  _meta(dbfile, "uq_waiting_pending") is not None, True)
        res.ok("баннер говорит, что защита не полная",
               "nu este completă" in body,
               "директор не предупреждён, что часть проверок отсутствует")
        res.ok("в состоянии broken директору сказано, ЧТО делать",
               "La <b>medic</b>: mutați" in body,
               "совет собирается только в ветке narrow: директор видит список "
               "конфликтных часов и ни слова о том, как их развести")
        res.ok("конфликтный час назван",
               "<b>Medic:</b> Dr. Activ Doi · 16.01.2026 09:00" in body,
               "разводить нечего — список пуст или час не в поясе клиники")
        # ⛔ «Защиты нет» здесь было бы неправдой, измеримой двумя строками
        # выше: обе прежние проверки на месте и отбивают двойную запись.
        events = _activity(dbfile, "uq_guard")
        res.ok("летопись не объявляет защиту отсутствующей",
               events and "nu este activă" not in events[0],
               f"замер показал работающую защиту, а записано обратное: {events!r}")
        res.ok("летопись называет, чего именно не хватает",
               events and "aceeași oră la medicul redenumit" in events[0],
               f"строка не описывает проверенное: {events!r}")

        # клиника развела записи руками — лишний визит убран
        con = sqlite3.connect(str(dbfile))
        con.execute("DELETE FROM appointments WHERE status = 'arrived'")
        con.commit()
        con.close()
        with Server(dir_=work):
            pass
        idx = _index_sql(dbfile)
        res.ok("после разведения легла полная защита",
               all("waiting" in idx.get(n, "") for n in _UQ),
               f"страховка не встала сама: {idx!r}")
        res.check("метка снялась", _meta(dbfile, "uq_waiting_pending"), None)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_from_1200(res: Result) -> None:
    """Клиника пришла от 1.20.0: два индекса ШИРОКИЕ, третьего нет.

    ⛔ Главный вопрос круга: обновление не имеет права УМЕНЬШИТЬ защиту, которая
    у клиники работала. Ступень лестницы, выбранная одна на все три индекса,
    делала ровно это: конфликт под широким предикатом есть только у
    `uq_doctor_slot_id` (переименованный врач), но опускались на запасную
    ступень все три — и база уходила с обновления с тремя УЗКИМИ. Замер до и
    после в одном прогоне это и ловит: «отбито» обязано остаться «отбито».

    Существующий широкий индекс — сам себе доказательство: раз он стоит, данные
    ему не противоречат, и спрашивать про них подсчёт конфликтов соседа незачем.
    """
    tz = ZoneInfo("Europe/Chisinau")
    at = datetime(2026, 1, 19, 9, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_1200_"))
    try:
        dbfile = work / "dental.db"
        con = _v1200_db(dbfile)
        _patients(con, "Ion Test", "Maria Test", "Vasile Test")
        # переименованный врач: один doctor_id, два разных имени, один час.
        # Широким индексам по ИМЕНИ и по ПАЦИЕНТУ эта пара не мешает — они и
        # легли; мешает она только индексу по doctor_id, которого в базе нет.
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", at, "confirmed", "d2"))
        con.execute(_APPT_SQL, (2, "Dr. Doi Redenumit", at, "waiting", "d2"))
        con.commit()
        con.close()

        # ЗАМЕР ДО: обе широкие проверки работают, и работают ИМЕННО по waiting
        doc_dup = (3, "Dr. Doi Redenumit", at, "waiting", "dX")
        pat_dup = (2, "Dr. Cineva", at, "waiting", "dZ")
        res.ok("до обновления: широкая защита врача работает",
               _blocked(dbfile, *doc_dup),
               "фикстура не воспроизводит состояние после 1.20.0 — набор "
               "ничего не мерит")
        res.ok("до обновления: широкая защита пациента работает",
               _blocked(dbfile, *pat_dup),
               "фикстура не воспроизводит состояние после 1.20.0 — набор "
               "ничего не мерит")

        with Server(dir_=work) as s:
            res.ok("база от 1.20.0 стартует", True)
            body = Client(s.url).login().get("/admin").body

        res.check("версия схемы доведена до 4", _meta(dbfile, "version"), "4")

        # ЗАМЕР ПОСЛЕ: тем же способом, теми же вставками
        res.ok("обновление НЕ сузило защиту врача", _blocked(dbfile, *doc_dup),
               "работавший ШИРОКИЙ индекс заменён на узкий: waiting-визит снова "
               "вне страховки, и сделали это мы сами")
        res.ok("обновление НЕ сузило защиту пациента",
               _blocked(dbfile, *pat_dup),
               "тот же слом на индексе пациента: конфликт был у соседа, а "
               "ступень опустили всем троим")
        idx = _index_sql(dbfile)
        res.ok("широкие индексы остались широкими",
               "waiting" in idx.get("uq_doctor_slot", "")
               and "waiting" in idx.get("uq_patient_slot", ""),
               f"предикат сузился: {idx!r}")
        res.ok("третий индекс лёг тем, чем смог — узким",
               "confirmed" in idx.get("uq_doctor_slot_id", "")
               and "waiting" not in idx.get("uq_doctor_slot_id", ""),
               f"недостающая проверка не появилась вовсе: {idx!r}")
        res.ok("третья проверка не просто существует, а стережёт",
               _blocked(dbfile, 3, "Dr. Oarecare", at, "confirmed", "d2"),
               "индекс по doctor_id есть, а двойную запись к тому же врачу "
               "под другим именем пропускает")

        # ---- что читает директор ----
        res.check("метка незавершённости стоит",
                  _meta(dbfile, "uq_waiting_pending") is not None, True)
        res.ok("баннер не объявляет проверки пропавшими",
               "nu este completă" not in body,
               "все три проверки в базе есть, а директору сказано, что чего-то "
               "не хватает — он пойдёт в поддержку вместо того, чтобы развести час")
        res.ok("баннер называет час, который надо развести",
               "<b>Medic:</b> Dr. Activ Doi · 19.01.2026 09:00" in body,
               "директор не видит, ЧТО разводить")
        events = _activity(dbfile, "uq_guard")
        res.check("вмешательство описано в летописи один раз", len(events), 1)
        res.ok("летопись не объявляет защиту отсутствующей",
               events and "suport tehnic" not in events[0],
               f"строка хранится готовой и навсегда: {events!r}")

        # клиника развела час — полная защита встаёт сама
        con = sqlite3.connect(str(dbfile))
        con.execute("DELETE FROM appointments WHERE status = 'waiting'")
        con.commit()
        con.close()
        with Server(dir_=work):
            pass
        idx = _index_sql(dbfile)
        res.ok("после разведения легли все три широких",
               all("waiting" in idx.get(n, "") for n in _UQ),
               f"страховка не встала сама: {idx!r}")
        res.check("метка снялась", _meta(dbfile, "uq_waiting_pending"), None)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_selfheal_narrow(res: Result) -> None:
    """Самолечение расширило УЗКИЕ индексы — и сказало об этом правду.

    Ветка та же, что у `suite_selfheal` (метки нет, состояние читается на
    старте), но событие ДРУГОЕ: ничего не пропадало, проверки стояли и
    работали — просто предикат был уже ожидаемого. Одна строка на два события
    всегда врёт про одно из них, а летопись хранит её ГОТОВОЙ и навсегда:
    директор читает «проверки отсутствовали» про базу, которая всё это время
    была под защитой.
    """
    tz = ZoneInfo("Europe/Chisinau")
    at = datetime(2026, 1, 20, 9, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_heal_n_"))
    try:
        dbfile = work / "dental.db"
        con = _v3_db(dbfile)                    # три УЗКИХ индекса
        con.execute("UPDATE schema_meta SET value='4' WHERE key='version'")
        _patients(con, "Ion Test", "Maria Test", "Vasile Test")
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", at, "confirmed", "d2"))
        con.commit()
        con.close()

        res.ok("до старта узкая защита РАБОТАЕТ",
               _blocked(dbfile, 2, "Dr. Activ Doi", at, "confirmed", "dX"),
               "фикстура собрана неверно: индексов нет, и это уже другой случай")
        res.ok("до старта waiting вне защиты — это и есть узость",
               not _blocked(dbfile, 2, "Dr. Activ Doi", at, "waiting", "dX"),
               "предикат оказался шире заявленного, расширять нечего")

        with Server(dir_=work):
            pass

        res.ok("старт расширил защиту",
               _blocked(dbfile, 2, "Dr. Activ Doi", at, "waiting", "dX"),
               "версия схемы 4, метки нет — и предикат никто не сверил")
        events = _activity(dbfile, "uq_guard")
        res.check("расширение отмечено в летописи один раз", len(events), 1)
        res.ok("летопись НЕ говорит, что проверки пропадали",
               events and "lipseau" not in events[0],
               f"проверки стояли и работали, а записано обратное: {events!r}")
        res.ok("летопись называет то, что было: предикат был уже",
               events and "mai restrânse" in events[0],
               f"событие не описано вовсе: {events!r}")

        with Server(dir_=work):
            pass
        res.check("исправная база строк в летопись не добавляет",
                  len(_activity(dbfile, "uq_guard")), 1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_selfheal(res: Result) -> None:
    """База версии 4 БЕЗ слотовых индексов и БЕЗ метки.

    Пока `CREATE UNIQUE INDEX IF NOT EXISTS` стоял в базовой схеме, у страховки
    было самолечение: пропавший индекс возвращался при каждом старте. У
    единственного владельца его нет, и такая база стартовала бы молча — ни
    баннера, ни метки, ни строки в летописи, а слот не стережёт никто.
    Внутреннего пути в это состояние нет (метка ставится ДО работы), поэтому
    триггер внешний: ручная правка sqlite, подмена файла, чужая копия.
    """
    tz = ZoneInfo("Europe/Chisinau")
    at = datetime(2026, 1, 17, 9, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_heal_"))
    try:
        dbfile = work / "dental.db"
        con = _base_db(dbfile)                 # базовая схема слотовых uq не кладёт
        _patients(con, "Ion Test", "Maria Test")
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", at, "confirmed", "d2"))
        con.execute("INSERT INTO schema_meta(key, value) VALUES('version', '4')")
        con.execute("INSERT INTO schema_meta(key, value) VALUES('act_backfill', '1')")
        con.commit()
        con.close()
        res.ok("до старта база слот не стережёт",
               not _blocked(dbfile, 2, "Dr. Activ Doi", at, "confirmed", "d2"),
               "фикстура собрана неверно: индексы на месте, лечить нечего")

        with Server(dir_=work) as s:
            body = Client(s.url).login().get("/admin").body

        res.ok("старт восстановил защиту слота",
               _blocked(dbfile, 2, "Dr. Activ Doi", at, "confirmed", "d2"),
               "версия схемы 4, метки нет — и состояние индексов никто не "
               "спросил: картотека работает день без страховки слота")
        idx = _index_sql(dbfile)
        res.ok("легли все три индекса, широкие",
               all("waiting" in idx.get(n, "") for n in _UQ),
               f"восстановлено не всё: {idx!r}")
        res.check("метки после починки не остаётся",
                  _meta(dbfile, "uq_waiting_pending"), None)
        res.ok("баннера нет: чинить директору нечего",
               "nu este completă" not in body and "nu a putut fi extinsă" not in body,
               "директору показано предупреждение о том, что уже исправлено")
        events = _activity(dbfile, "uq_guard")
        res.check("пропажа отмечена в летописи", len(events), 1)
        # ⚠️ Вторая половина той же пары — в suite_selfheal_narrow. Порознь они
        # обе зелены на ОДНОЙ строке на два события: врёт она ровно про одно.
        res.ok("летопись говорит именно о пропаже",
               events and "lipseau" in events[0],
               f"событие названо не тем, чем было: {events!r}")

        with Server(dir_=work):
            pass
        res.check("исправная база строк в летопись не добавляет",
                  len(_activity(dbfile, "uq_guard")), 1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_step4_list(res: Result) -> None:
    """Список шага 4 исполняется, а не только объявлен.

    Шаг 4 уходит в защищённый путь (_slot_guard_apply), и пока его список при
    этом не читался, он был МЁРТВЫМ: дописанный туда через месяц оператор —
    естественное место, «шаг 4 про индексы, добавлю сюда ещё один» — молча не
    выполнился бы, а версия схемы записалась бы как выполненная. Повторить его
    после этого нечем: цикл идёт range(have+1, …).
    """
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_step4_"))
    try:
        bot = _patched_bot(work, "\n# тест: оператор, дописанный в шаг 4\n"
                                 "_MUT = \"CREATE TABLE step4_mark(x INTEGER)\"\n"
                                 "MIGRATIONS_PG[4].append(_MUT)\n"
                                 "MIGRATIONS_LITE[4].append(_MUT)\n")
        data = work / "data"
        data.mkdir()
        with Server(dir_=data, bot=bot):
            pass                              # чистая установка: 0 → 4

        dbfile = data / "dental.db"
        res.check("версия схемы 4", _meta(dbfile, "version"), "4")
        con = sqlite3.connect(str(dbfile))
        try:
            got = con.execute("SELECT count(*) FROM sqlite_master "
                              "WHERE type='table' AND name='step4_mark'"
                              ).fetchone()[0]
        finally:
            con.close()
        res.ok("оператор, дописанный в шаг 4, выполнен", got == 1,
               "список шага 4 никто не исполняет: операция пропущена молча, а "
               "версия схемы говорит, что шаг сделан")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_slot_guard_no_data(res: Result) -> None:
    """Шаг упёрся НЕ в данные: отказал сам подсчёт конфликтов.

    Состояние «страховка узкая, а конфликтных часов не найдено ни одного»
    достижимо (в PG — откат транзакции возвращает прежние индексы на место; в
    SQLite — отказ самого запроса). Тексты в нём обязаны описывать то, что есть:
    баннер называл причиной «ore cu mai multe programări active», а в летопись
    уезжала строка «0 ore au mai multe programări active» — навсегда и без
    возможности переписать.

    ⚠️ Отказ подделан правкой КОПИИ дерева: данными его не подделать — запрос
    валиден на любой картотеке.
    """
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_nodata_"))
    try:
        bot = _patched_bot(work, "\n# тест: подсчёт конфликтов отказал\n"
                                 "async def _slot_conflicts(act_sql=_ACT_SQL):\n"
                                 "    raise RuntimeError('нет ответа')\n")
        data = work / "data"
        data.mkdir()
        dbfile = data / "dental.db"
        con = _v3_db(dbfile)
        _patients(con, "Ion Test")
        con.commit()
        con.close()

        with Server(dir_=data, bot=bot) as s:
            res.ok("отказ подсчёта не роняет старт", True)
            body = Client(s.url).login().get("/admin").body

        idx = _index_sql(dbfile)
        res.ok("прежние узкие индексы остались на месте",
               all(n in idx and "waiting" not in idx[n] for n in _UQ),
               f"подделка отказа не сработала, набор ничего не проверяет: {idx!r}")
        res.ok("баннер не выдумывает конфликтных часов",
               "există ore cu mai multe programări active" not in body,
               "директору названа причина, которой код не нашёл: он пойдёт "
               "искать часы с двойной записью, а их нет")
        res.ok("баннер называет то, что есть", "operația nu s-a încheiat" in body,
               "причина не названа вовсе")
        events = _activity(dbfile, "uq_guard")
        res.check("вмешательство описано в летописи один раз", len(events), 1)
        res.ok("в летописи не осталось «0 ore»",
               events and "0 ore" not in events[0],
               f"строка хранится готовой и навсегда: {events!r}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_uq_apply_fails(res: Result) -> None:
    """Раскладка индексов ОТКАЗАЛА — что читает директор.

    Отказ подделан самым дешёвым способом, какой даёт SQLite: в базе лежит
    ТАБЛИЦА с именем одного из индексов, и `CREATE UNIQUE INDEX` на неё падает.
    Программе это неотличимо от настоящей причины (диск полон, база залочена,
    процесс убит в окне), а проверяется ровно то, что важно: баннер не имеет
    права утверждать, что защита цела, не спросив базу. У SQLite DDL идёт вне
    транзакции, поэтому упавший CREATE после DROP оставляет картотеку БЕЗ
    индексов — и в этот день двойная запись проходит молча.
    """
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_fail_"))
    try:
        dbfile = work / "dental.db"
        con = _v3_db(dbfile)
        con.execute("DROP INDEX uq_doctor_slot_id")
        con.execute("CREATE TABLE uq_doctor_slot_id(x)")
        _patients(con, "Ion Test")
        con.commit()
        con.close()

        with Server(dir_=work) as s:
            res.ok("отказ раскладки не роняет старт", True)
            body = Client(s.url).login().get("/admin").body

        idx = _index_sql(dbfile)
        res.ok("индексы действительно легли не все", len(idx) < 3,
               f"подделка отказа не сработала, набор ничего не проверяет: {idx!r}")
        res.ok("баннер НЕ утверждает, что защита цела",
               "rămas activă" not in body and "rămâne activă" not in body,
               "директору обещана прежняя защита, которой в базе нет")
        res.ok("баннер говорит о неполной защите и зовёт чинить сегодня",
               "nu este completă" in body and "contactați suportul astăzi" in body,
               "отказ раскладки прошёл как обычное предупреждение")
        # ⛔ И ровно столько, сколько проверено. Два индекса из трёх легли и
        # работают; «защиты нет» — приговор, которого код не выносил, а строка
        # летописи хранится ГОТОВОЙ и навсегда.
        res.ok("баннер называет, какой проверки не хватает",
               "aceeași oră la medicul redenumit" in body,
               "директору сказано «чего-то не хватает» без единого имени: "
               "проверить это ему нечем")
        res.ok("баннер не объявляет отсутствующими все проверки",
               "niciuna dintre cele 3" not in body,
               "две проверки из трёх стоят и работают, а сказано обратное")
        res.check("метка незавершённости стоит",
                  _meta(dbfile, "uq_waiting_pending") is not None, True)
        events = _activity(dbfile, "uq_guard")
        res.check("отказ описан в летописи один раз", len(events), 1)
        res.ok("летопись НЕ объявляет защиту отсутствующей",
               events and "nu este activă" not in events[0],
               f"два индекса из трёх работают, а записано, что защиты нет: "
               f"{events!r}")
        # ⚠️ Формулировка считает НЕДОСТАЮЩИЕ, а не оставшиеся: «din 3 … lipsește
        # una» короче, чем «2 din 3 … sunt în evidență; lipsește protecția
        # pentru», и обе половины по-прежнему названы. Длина тут не косметика —
        # у колонки летописи есть потолок, и прежняя формулировка в него не
        # влезала ровно в самом тревожном состоянии (08-16, suite_uq_all_gone).
        res.ok("летопись называет, скольких проверок нет и какой именно",
               events and f"din {appdb.UQ_SLOT_COUNT}" in events[0]
               and "lipsește una" in events[0]
               and "aceeași oră la medicul redenumit" in events[0],
               f"строка не описывает проверенное: {events!r}")

        with Server(dir_=work):
            pass
        res.check("перезапуск не плодит строки об отказе",
                  len(_activity(dbfile, "uq_guard")), 1)
        res.check("метка держится до починки",
                  _meta(dbfile, "uq_waiting_pending") is not None, True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # ---- отказ на ПЕРВОМ индексе: он не имеет права уносить соседей ----
    # DDL в SQLite идёт вне транзакции. Пока раскладка шла «сначала все три
    # DROP, потом три CREATE», первая же неудача оставляла картотеку вообще без
    # защиты слота — хотя два индекса из трёх легли бы без вопросов.
    tz = ZoneInfo("Europe/Chisinau")
    at = datetime(2026, 1, 18, 9, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_fail1_"))
    try:
        dbfile = work / "dental.db"
        con = _v3_db(dbfile)
        con.execute("DROP INDEX uq_doctor_slot")
        con.execute("CREATE TABLE uq_doctor_slot(x)")   # тот же способ подделки
        _patients(con, "Ion Test")
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", at, "confirmed", "d2"))
        con.commit()
        con.close()

        with Server(dir_=work):
            res.ok("отказ на первом индексе не роняет старт", True)

        idx = _index_sql(dbfile)
        res.ok("индексы, которых отказ не касался, остались",
               "uq_patient_slot" in idx and "uq_doctor_slot_id" in idx,
               f"снесены все три ради одного, который не лёг: {idx!r}")
        res.ok("уцелевшая защита работает",
               _blocked(dbfile, 1, "Dr. Altul", at, "confirmed", "dX"),
               "второй визит того же пациента на тот же час прошёл — "
               "картотека осталась без страховки, которой отказ не касался")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_uq_event_len(res: Result) -> None:
    """Ни одна строка летописи про страховку не упирается в потолок колонки.

    ⚠️ Летопись режет текст по `db.EVENT_TEXT_MAX` ЖЁСТКО — посреди слова — и
    хранит его навсегда. Не влезал ровно самый тревожный случай: «нет ни одной
    проверки» перечисляла все три имени и на 232-м символе теряла хвост
    «— este nevoie de suport tehnic», то есть единственное, ради чего в этом
    состоянии летопись и пишется. Сервер тут не нужен: строка собирается чистой
    функцией, и проверить её можно ВО ВСЕХ состояниях сразу, а не в тех, до
    которых довели фикстуры.
    """
    names = list(appdb._UQ_SLOT)
    cases: list[tuple[str, str]] = []
    for n in range(1, len(names) + 1):
        for i in range(len(names) - n + 1):
            gone = names[i:i + n]
            cases.append((f"broken {len(gone)}/{len(names)}",
                          appdb.uq_event_text(appdb.UQ_BROKEN, gone, 0)))
    cases.append(("broken все", appdb.uq_event_text(appdb.UQ_BROKEN, names, 3)))
    cases.append(("unknown", appdb.uq_event_text(appdb.UQ_UNKNOWN, [], 0)))
    for n in (0, 1, 2, 12, 999):
        cases.append((f"narrow rows={n}",
                      appdb.uq_event_text(appdb.UQ_NARROW, [], n)))
    for why, text in appdb.UQ_REPAIR_TEXT.items():
        cases.append((f"самолечение {why}", text))
    cases.append(("метка снята", appdb.UQ_CLEARED_TEXT))

    limit = appdb.EVENT_TEXT_MAX
    long = [(what, len(t)) for what, t in cases if len(t) > limit]
    res.ok("ни одна строка не длиннее потолка летописи", not long,
           f"потолок {limit}, обрезка идёт посреди слова и навсегда: {long!r}")
    # ⭐ Не только «влезла», но и «осталась самодостаточной»: в состоянии, где
    # директору нужно позвать поддержку, эти слова обязаны доехать до базы.
    need = [what for what, t in cases
            if what.startswith(("broken", "unknown"))
            and "suport tehnic" not in t]
    res.ok("зовущие поддержку строки не теряют этих слов", not need,
           f"строка обрезана до совета: {need!r}")
    res.ok("проверено больше одного состояния", len(cases) > 8,
           f"набор сторожит пустоту: состояний {len(cases)}")


def suite_uq_all_gone(res: Result) -> None:
    """Самое тревожное состояние: в базе НЕ ОСТАЛОСЬ ни одной проверки.

    Ровно тут строка летописи и не влезала в колонку: 232 символа против
    потолка в 200, и обрезка съедала «— este nevoie de suport tehnic» — то
    единственное, ради чего в этом состоянии строка и пишется. Хранится она
    навсегда, переписать её нечем.

    Отказ подделан тем же способом, что в `suite_uq_apply_fails`, но на ВСЕХ
    трёх индексах: в базе лежат ТАБЛИЦЫ с их именами, и CREATE UNIQUE INDEX
    падает на каждом.
    """
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_allgone_"))
    try:
        dbfile = work / "dental.db"
        con = _v3_db(dbfile)
        for name in _UQ:
            con.execute(f"DROP INDEX {name}")
            con.execute(f"CREATE TABLE {name}(x)")
        _patients(con, "Ion Test")
        con.commit()
        con.close()

        with Server(dir_=work) as s:
            res.ok("отказ на всех трёх не роняет старт", True)
            body = Client(s.url).login().get("/admin").body

        res.ok("подделка сработала: индексов не осталось", not _index_sql(dbfile),
               f"набор ничего не проверяет: {_index_sql(dbfile)!r}")
        res.ok("баннер называет состояние своим именем",
               f"niciuna dintre cele {appdb.UQ_SLOT_COUNT}" in body,
               "директору не сказано, что в базе нет ни одной проверки")
        events = _activity(dbfile, "uq_guard")
        res.check("состояние описано в летописи один раз", len(events), 1)
        text = events[0] if events else ""
        res.ok("строка летописи не обрезана", len(text) < appdb.EVENT_TEXT_MAX,
               f"в колонку уехало {len(text)} символов при потолке "
               f"{appdb.EVENT_TEXT_MAX} — конец строки потерян навсегда: "
               f"{text!r}")
        res.ok("летопись зовёт поддержку", "suport tehnic" in text,
               f"в самом тревожном состоянии совет не доехал до базы: {text!r}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_uq_state_unreadable(res: Result) -> None:
    """Состояние индексов ПРОЧИТАТЬ НЕ УДАЛОСЬ — третий исход, а не приговор.

    Неудачное чтение давало пустой словарь, а пустой словарь читался как «в базе
    нет ни одной проверки»: директор получал самый страшный текст («aceeași oră
    poate fi ocupată de două ori fără avertisment») на картотеке, где все три
    индекса целы и работают. Утверждение, которого никто не проверял, — тот же
    класс, что и «защиты нет» в соседней ветке: мы не ЗНАЕМ состояния, а не
    знаем, что его нет.

    ⚠️ Отказ подделан правкой КОПИИ дерева: данными его не подделать — запрос к
    sqlite_master валиден на любой картотеке.
    """
    tz = ZoneInfo("Europe/Chisinau")
    at = datetime(2026, 1, 22, 9, 0, tzinfo=tz).astimezone(
        timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_unread_"))
    try:
        bot = _patched_bot(work, "\n# тест: состояние индексов не читается\n"
                                 "async def _uq_index_state():\n"
                                 "    raise RuntimeError('база не ответила')\n")
        data = work / "data"
        data.mkdir()
        dbfile = data / "dental.db"
        con = _v3_db(dbfile)                    # три УЗКИХ индекса, все рабочие
        _patients(con, "Ion Test", "Maria Test")
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", at, "confirmed", "d2"))
        con.commit()
        con.close()

        with Server(dir_=data, bot=bot) as s:
            res.ok("неудачное чтение не роняет старт", True)
            body = Client(s.url).login().get("/admin").body

        idx = _index_sql(dbfile)
        res.ok("индексы на месте — подделка ничего не сломала",
               all(n in idx for n in _UQ),
               f"набор проверяет не то состояние, о котором говорит: {idx!r}")
        res.ok("защита в базе РАБОТАЕТ",
               _blocked(dbfile, 2, "Dr. Activ Doi", at, "confirmed", "dX"),
               "фикстура собрана неверно: слот не стережёт никто, и тогда "
               "тревожный текст был бы правдой")
        res.ok("баннер НЕ объявляет проверки отсутствующими",
               "niciuna dintre cele" not in body,
               "код не прочитал состояние, а директору сказано, что защиты "
               "нет ни одной — все три индекса при этом целы")
        res.ok("баннер НЕ обещает двойную запись",
               "poate fi ocupată de două ori" not in body,
               "директору обещано то, чего база не допускает")
        res.ok("баннер называет то, что есть: состояние не прочитано",
               "nu a putut fi citită" in body,
               "третьего исхода нет — «не знаем» слито с «сломано»")
        res.check("метка незавершённости стоит",
                  _meta(dbfile, "uq_waiting_pending") is not None, True)
        events = _activity(dbfile, "uq_guard")
        res.check("исход описан в летописи один раз", len(events), 1)
        text = events[0] if events else ""
        res.ok("летопись НЕ считает проверки отсутствующими",
               "nu este în evidență" not in text and "din 3" not in text,
               f"строка хранится навсегда, а описывает не то, что было: {text!r}")
        res.ok("летопись называет причину: состояние не прочитано",
               "nu a putut fi citită" in text,
               f"событие не описано вовсе: {text!r}")
        res.ok("строка летописи не обрезана", len(text) < appdb.EVENT_TEXT_MAX,
               f"{len(text)} символов при потолке {appdb.EVENT_TEXT_MAX}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_slot_banner_roles(res: Result) -> None:
    """Кому виден баннер о неполной страховке.

    Он про устройство базы: разводит часы и зовёт поддержку директор. У
    регистратуры и врача такой строки нет — погасить её они не могут, а
    несменяемое предупреждение на каждом экране перестаёт читаться через день.
    ⚠️ Сервер здесь без ADMIN_KEY: роли живут только в ветке PIN-файла, и на
    облачной ветке request_user() вернул бы None — проверка смотрела бы мимо.
    """
    local = datetime(2026, 1, 14, 9, 0, tzinfo=ZoneInfo("Europe/Chisinau"))
    starts = local.astimezone(timezone.utc).isoformat(timespec="seconds")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_mig_role_"))
    try:
        dbfile = work / "dental.db"
        con = _v3_db(dbfile)
        _patients(con, "Ion Test", "Maria Test")
        con.execute(_APPT_SQL, (1, "Dr. Activ Doi", starts, "confirmed", "d2"))
        con.execute(_APPT_SQL, (2, "Dr. Activ Doi", starts, "waiting", "d2"))
        con.commit()
        con.close()

        with Server(dir_=work, env={"ADMIN_KEY": ""}) as s:
            boss = Client(s.url)
            boss.post("/admin/setup", pin1="1111", pin2="1111")
            boss.post("/admin/users/save", uid="ana", name="Ana R",
                      role="receptie", pin="3333")
            boss.post("/admin/users/save", uid="d2", name="Dr. Liviu",
                      role="medic", doctor_id="d2", pin="2222")
            mark = "<b>Medic:</b> Dr. Activ Doi"
            res.ok("директор видит, что разводить", mark in boss.get("/admin").body,
                   "тот единственный, кто может починить, ничего не узнал")
            for pin, who in (("3333", "регистратуре"), ("2222", "врачу")):
                cl = Client(s.url)
                cl.post("/admin/login", password=pin, next="/admin")
                page = cl.get("/admin").body
                res.ok(f"{who} баннер не показан",
                       page.count("Registrul Clinicii") > 0 and mark not in page,
                       "несменяемое предупреждение висит у того, кто не может "
                       "его закрыть")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite_backfill_tz(res: Result) -> None:
    # 09:00 Кишинёва; UTC-эквивалент считается zoneinfo, а не руками — иначе
    # тест сам наступил бы на грабли летнего/зимнего времени
    local = datetime(2026, 1, 15, 9, 0, tzinfo=ZoneInfo("Europe/Chisinau"))
    starts = local.astimezone(timezone.utc).isoformat(timespec="seconds")
    utc_hhmm = local.astimezone(timezone.utc).strftime("%H:%M")

    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_bf_"))
    try:
        con = _base_db(work / "dental.db")
        con.execute("INSERT INTO patients(session_key, name, phone, created_at) "
                    "VALUES('manual:60000002', 'Ana Test', '060000002', "
                    "'2026-01-10T08:00:00+00:00')")
        con.execute("INSERT INTO appointments(patient_id, service, doctor, "
                    "starts_at, status, source, created_at, doctor_id) "
                    "VALUES(1, 'Igienizare', 'Dr. Activ Trei', ?, 'confirmed', "
                    "'admin', '2026-01-10T08:05:00+00:00', 'd3')", (starts,))
        con.commit()
        con.close()

        with Server(dir_=work):
            pass                              # старт = init + _backfill_activity

        con = sqlite3.connect(str(work / "dental.db"))
        rows = con.execute("SELECT text FROM activity "
                           "WHERE kind='appt_new'").fetchall()
        con.close()
        res.check("backfill перенёс визит в летопись", len(rows), 1)
        text = rows[0][0] if rows else ""
        res.ok("час в тексте события — час клиники, не UTC",
               "09:00" in text,
               f"визит на 09:00 Кишинёва записан как {text!r} "
               f"(UTC был бы {utc_hhmm})")
    finally:
        shutil.rmtree(work, ignore_errors=True)
