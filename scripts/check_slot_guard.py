"""Канареечная проверка защиты слота (миграция, шаги 4 и 11).

Отвечает на вопрос, который обычным запуском канарейки НЕ проверяется: что
делает программа, когда в картотеке УЖЕ есть две живые записи на один час.
Такой пары на канарейке нет, поэтому её заводим искусственно — в КОПИИ базы.

  python scripts/check_slot_guard.py
  python scripts/check_slot_guard.py --db "D:\\другая\\копия\\data\\dental.db"
  python scripts/check_slot_guard.py --src     движок из исходников этого дерева

⛔ Живая база только ЧИТАЕТСЯ. Всё происходит в песочнице (копия движка + копия
базы во временной папке), боевая установка на 8088 не запускается и не
трогается ни одной записью.

Что проверяется, по шагам:
  1. копия базы приводится к состоянию «клиника до обновления» — версия схемы
     3 и УЗКИЕ уникальные индексы (без 'waiting'), как было до 1.20.0;
  2. в неё вносится конфликт: второй визит тому же врачу на тот же час со
     статусом 'waiting' — ровно то, обо что разбивался CREATE UNIQUE INDEX;
  3. песочница запускается: программа ОБЯЗАНА стартовать, поднять версию до 4,
     оставить узкую страховку, пометить незавершённость и показать директору
     баннер с этим слотом;
  4. конфликт разводится (лишняя запись убирается), песочница запускается
     снова: широкие индексы обязаны лечь сами, метка — сняться, баннер — уйти;
  5. отдельный ШАГ 3 — база, пришедшая от опубликованной 1.20.0: два индекса
     ШИРОКИЕ, третьего нет. Обновление не имеет права их СУЗИТЬ (08-16);
  6. ШАГ 4 — у врача две живые записи на один час в РАЗНЫХ кабинетах (шаг 11
     схемы: кабинет в ключе индексов врача). Такая база обязана стартовать без
     баннера, пара — остаться, а третья запись в занятый кабинет — отбиваться;
  7. ШАГ 5 — то же для полосы «Control» врача (`room_id = '~control'`): запись
     в полосе рядом с записью в кабинете законна, вторая в ту же полосу — нет.

Живая база может УЖЕ держать такие пары (врач в двух кабинетах или в кабинете
и в полосе Control на один час): они законны с шага 11, а индекс «до 1.20.0»
(врач + час, без кабинета) по ним не строится. У клиники до обновления пары
быть не могло, поэтому в КОПИИ лишние записи пары на шаги 1–3 откладываются
(статус вне индекса), а перед шагом 4 возвращаются как были: шаги 4–5 и повтор
шага 11 идут по базе с настоящими парами клиники.

Внесённые записи берут кабинет у живой записи как есть: новые записи несут
кабинет явно (`_book_locked`), и запись «без кабинета» рядом с ней в индексе врача не
сталкивается — ключ индекса сам `room_id`. Что пустой кабинет = первый кабинет
врача, знает только проверка под замком (`slots._lane`), индекс — нет.

Копия всегда приводится к базе ДО шага 11: индексы врача под прежними именами
(`UQ_OLD`, без кабинета в ключе). После старта в базе обязаны лежать новые
(`UQ`), а прежние — быть сняты.

⭐ Защита меряется ПОВЕДЕНИЕМ базы (пробная вставка + rollback), а не текстом
индекса: индекс, который существует, но ничего не стережёт, по тексту от
рабочего неотличим.
"""
import argparse
import http.cookiejar
import os
import pathlib
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
# С 21.09 (P1) данные живут в %ProgramData%, не рядом с программой: прежнее
# `C:\Users\Public\DentPilot` после переезда ушло в `.hold`, и проверка по
# умолчанию читала бы не ту картотеку или никакую (поймано на 1.41.0).
LIVE_DB = pathlib.Path(r"C:\ProgramData\DentPilot\data\dental.db")
KEY = "canary1234"
MARK = "CANARY-SLOT-GUARD"          # по нему находим и убираем внесённую запись
NARROW = "('confirmed','arrived')"  # предикат, каким он был до 1.20.0
WIDE = "('confirmed','waiting','arrived')"   # предикат, к которому ведёт шаг 4
UQ = ("uq_doc_room_slot", "uq_patient_slot", "uq_docid_room_slot")
UQ_OLD = ("uq_doctor_slot", "uq_doctor_slot_id")   # сняты шагом 11
ROOM = "r-canary-2"                 # второй кабинет врача в шаге 4
PARKED = "cancelled"                # статус вне слотовых индексов: отложенная запись пары

# Куда обязана доехать база после старта. Из константы ИСХОДНИКОВ, а не числом:
# бинарник собран из этого же дерева, а записанное число отставало бы при каждом
# новом шаге миграции — и канарейка краснела бы ровно на той правке, ради
# которой её и зовут (RELEASE.md шаг 3a). Так она отстала на шаге 5, 08-17.
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
from app.db import CONTROL_LANE, SCHEMA_VERSION  # noqa: E402 — только константы, не соединение
from engine_check import READY_LIMIT, STOP_LIMIT, Engine  # noqa: E402 — тот же разговор, что у оболочки
from harness import RUN_TMP  # noqa: E402

SCHEMA_TARGET = str(SCHEMA_VERSION)
OK, BAD = "  [ок] ", "  [!!] "
fails = 0


def say(ok: bool, text: str, detail: str = "") -> None:
    global fails
    if not ok:
        fails += 1
    print((OK if ok else BAD) + text + (f" — {detail}" if detail and not ok else ""))


def free_port(start: int = 8110) -> int:
    import socket
    port = start
    while port < start + 40:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    sys.exit("свободный порт не нашёлся")


def copy_db(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Копия базы средствами SQLite: живая открывается ТОЛЬКО на чтение, а
    записанное в её `-wal` в копию попадает (копия одного файла под
    работающей программой его теряет). Не открылась только на чтение (папка
    без права записи, программа не запущена — SQLite негде держать `-shm`) —
    остаётся копия файла."""
    try:
        con = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
        try:
            out = sqlite3.connect(str(dst))
            try:
                con.backup(out)
            finally:
                out.close()
        finally:
            con.close()
    except sqlite3.Error:
        dst.unlink(missing_ok=True)
        shutil.copy2(src, dst)


def prepare_lab(db_src: pathlib.Path, exe: pathlib.Path | None) -> pathlib.Path:
    """Песочница — она же папка программы и папка данных: движок папкой в
    `engine\\` (корень программы — над ним, там `demo.flag`), данные рядом.
    Без `exe` движок идёт из исходников: программы в песочнице нет, а профиль
    клиники кладётся тот же, какой собранный взял бы по `demo.flag`.
    ⚠️ В папке прогона харнесса: её сносит выход; красная песочница
    оставляется для разбора — поэтому она в обычном TEMP рядом."""
    lab = pathlib.Path(tempfile.mkdtemp(prefix="dp_slotguard_", dir=str(RUN_TMP.parent)))
    (lab / "data").mkdir()
    copy_db(db_src, lab / "data" / "dental.db")          # ⛔ только копия
    if exe is not None:
        shutil.copytree(exe.parent, lab / "engine")
    else:
        shutil.copy2(ROOT / "bot" / "app" / "clinic.json", lab / "clinic.json")
    # ADMIN_KEY — чтобы песочница пускала без экрана установки PIN (auth.json
    # с канарейки НЕ копируем: чужие пароли в лаборатории не нужны)
    (lab / "dental.env").write_text(f"ADMIN_KEY={KEY}\n", encoding="utf-8")
    (lab / "demo.flag").write_text("1", encoding="utf-8")
    return lab


def sql(db: pathlib.Path, *statements: str) -> None:
    con = sqlite3.connect(str(db))
    try:
        for st in statements:
            con.execute(st)
        con.commit()
    finally:
        con.close()


def rows(db: pathlib.Path, query: str, args: tuple = ()) -> list:
    con = sqlite3.connect(str(db))
    try:
        return con.execute(query, args).fetchall()
    finally:
        con.close()


def index_state(db: pathlib.Path) -> dict:
    """Имя слотового индекса → его определение, по факту в базе."""
    return {name: (sql_text or "") for name, sql_text in rows(
        db, "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'uq_%slot%'")}


def park_parallel(db: pathlib.Path) -> list[tuple]:
    """Отложить в копии лишние записи законных пар врача на один час.

    Пара «один врач, один час, разные кабинеты» (или кабинет и полоса Control)
    законна с шага 11, а база «до обновления» знала один индекс на врача и
    час — по такой паре он не строится. Первая запись часа остаётся, остальные
    уходят в статус вне индексов; `unpark` возвращает их перед шагом 4.
    Записи в ОДНОМ кабинете не трогаются: это настоящий конфликт, его обязана
    назвать сама программа. Возвращает [(id, статус, врач, час, кабинет)]."""
    live = rows(db, "SELECT id, doctor, doctor_id, starts_at, COALESCE(room_id, ''), status "
                    f"FROM appointments WHERE status IN {WIDE} ORDER BY id")
    held, parked = {}, []
    for aid, doctor, did, starts_at, room, status in live:
        # два ключа — как два прежних индекса: по имени врача и по doctor_id
        keys = [k for k, v in ((("n", doctor, starts_at), doctor),
                               (("i", did, starts_at), did)) if v is not None]
        if any(held.get(k, room) != room for k in keys):
            parked.append((aid, status, doctor, starts_at, room))
            continue
        for k in keys:
            held.setdefault(k, room)
    con = sqlite3.connect(str(db))
    try:
        con.executemany("UPDATE appointments SET status = ? WHERE id = ?",
                        [(PARKED, p[0]) for p in parked])
        con.commit()
    finally:
        con.close()
    return parked


def unpark(db: pathlib.Path, parked: list[tuple]) -> bool:
    """Вернуть отложенным записям их статусы — разом или никак. Отказ базы
    значит, что живая пара не проходит НОВЫЕ индексы: это находка, не шум."""
    con = sqlite3.connect(str(db))
    try:
        con.executemany("UPDATE appointments SET status = ? WHERE id = ? AND status = ?",
                        [(p[1], p[0], PARKED) for p in parked])
        con.commit()
        return True
    except sqlite3.IntegrityError as e:
        con.rollback()
        print(f"      (отложенные записи не вернулись: {e})")
        return False
    finally:
        con.close()


def downgrade(db: pathlib.Path) -> None:
    """Копия базы становится такой, какой она была у клиники до 1.20.0."""
    sql(db,
        *(f"DROP INDEX IF EXISTS {n}" for n in (*UQ, *UQ_OLD)),
        f"""CREATE UNIQUE INDEX uq_doctor_slot ON appointments(doctor, starts_at)
            WHERE status IN {NARROW}""",
        f"""CREATE UNIQUE INDEX uq_patient_slot
            ON appointments(patient_id, starts_at) WHERE status IN {NARROW}""",
        f"""CREATE UNIQUE INDEX uq_doctor_slot_id
            ON appointments(doctor_id, starts_at)
            WHERE status IN {NARROW} AND doctor_id IS NOT NULL""",
        "UPDATE schema_meta SET value='3' WHERE key='version'",
        "DELETE FROM schema_meta WHERE key='uq_waiting_pending'")


def inject_conflict(db: pathlib.Path) -> tuple[str, str]:
    """Второй визит тому же врачу на тот же час, статус 'waiting'."""
    live = rows(db, "SELECT patient_id, service, doctor, starts_at, doctor_id, room_id "
                    "FROM appointments WHERE status IN ('confirmed','arrived') "
                    "ORDER BY starts_at DESC LIMIT 1")
    if not live:
        sys.exit("в базе нет ни одной активной записи — конфликт не из чего "
                 "сделать; проверьте на базе с реальным расписанием")
    pid, service, doctor, starts_at, did, room = live[0]
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
            " status, source, created_at, doctor_id, comment, room_id)"
            " VALUES(?,?,?,?,'waiting','admin',?,?,?,?)",
            (pid, service, doctor, starts_at,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK, room))
        con.commit()
    finally:
        con.close()
    return doctor, starts_at


def from_1200(db: pathlib.Path) -> None:
    """Копия базы становится такой, какой её оставила ОПУБЛИКОВАННАЯ 1.20.0.

    Её шаг 4 шёл «три DROP, потом три CREATE», поэтому у клиники с
    переименованным врачом падал ТРЕТИЙ CREATE — а первые два уже легли
    ШИРОКИМИ и автокоммитнулись. Версия схемы осталась 3, программа не
    открывалась. Такая база приходит к нам на обновление, и обновление не имеет
    права её защиту СУЗИТЬ.
    """
    sql(db,
        *(f"DROP INDEX IF EXISTS {n}" for n in (*UQ, *UQ_OLD)),
        f"""CREATE UNIQUE INDEX uq_doctor_slot ON appointments(doctor, starts_at)
            WHERE status IN {WIDE}""",
        f"""CREATE UNIQUE INDEX uq_patient_slot
            ON appointments(patient_id, starts_at) WHERE status IN {WIDE}""",
        "UPDATE schema_meta SET value='3' WHERE key='version'",
        "DELETE FROM schema_meta WHERE key='uq_waiting_pending'")


def inject_renamed(db: pathlib.Path):
    """Переименованный врач: тот же doctor_id и час, ДРУГОЕ имя, другой пациент.

    Широким индексам по имени врача и по пациенту эта пара не мешает — они и
    легли; мешает она только индексу по doctor_id, которого в базе нет. Свободные
    пациенты выбираются запросом, а не наугад: занятый час у них означал бы, что
    вставка разбилась о ту самую широкую защиту, которую мы собрались мерить.
    """
    live = rows(db, "SELECT patient_id, service, doctor, starts_at, doctor_id, room_id "
                    "FROM appointments WHERE status IN ('confirmed','arrived') "
                    "AND doctor_id IS NOT NULL ORDER BY starts_at DESC LIMIT 1")
    if not live:
        return None
    pid, service, doctor, starts_at, did, room = live[0]
    spare = [r[0] for r in rows(
        db, "SELECT id FROM patients WHERE id NOT IN (SELECT patient_id FROM "
            f"appointments WHERE starts_at = '{starts_at}' AND patient_id IS "
            "NOT NULL) ORDER BY id LIMIT 2")]
    if len(spare) < 2:
        return None
    renamed = f"{doctor} (redenumit)"
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
            " status, source, created_at, doctor_id, comment, room_id)"
            " VALUES(?,?,?,?,'waiting','admin',?,?,?,?)",
            (spare[0], service, renamed, starts_at,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK, room))
        con.commit()
    finally:
        con.close()
    return renamed, starts_at, spare[0], spare[1], room


def live_at(db: pathlib.Path, did, starts_at) -> int:
    """Сколько живых записей у врача в этот час."""
    return rows(db, "SELECT count(*) FROM appointments WHERE starts_at = ? AND doctor_id = ? "
                    "AND status IN ('confirmed','arrived')", (starts_at, did))[0][0]


def inject_parallel(db: pathlib.Path, lane: str = ROOM):
    """Ещё одна живая запись тому же врачу на тот же час — в ДРУГОМ кабинете
    (`lane`; полоса Control — тот же ключ индекса под своим именем).
    Образец — запись врача, у которого этот час в `lane` свободен: в живой
    базе полоса бывает уже занята, и вставку отбил бы индекс. Пациент берётся
    свободный в этот час: иначе вставку отбил бы индекс пациента, и шаг мерил
    бы не то. Последним в ответе — сколько живых записей у врача в этот час
    было ДО вставки (у живой пары их уже две)."""
    live = rows(db, "SELECT a.service, a.doctor, a.starts_at, a.doctor_id, a.room_id "
                "FROM appointments a WHERE a.status IN ('confirmed','arrived') "
                "AND a.doctor_id IS NOT NULL AND a.patient_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM appointments b "
                "  WHERE b.starts_at = a.starts_at AND COALESCE(b.room_id, '') = ? "
                f"  AND b.status IN {WIDE} "
                "  AND (b.doctor_id = a.doctor_id OR b.doctor = a.doctor)) "
                "ORDER BY a.starts_at DESC, a.id DESC LIMIT 1", (lane,))
    if not live:
        return None
    service, doctor, starts_at, did, room = live[0]
    before = live_at(db, did, starts_at)
    spare = [r[0] for r in rows(
        db, "SELECT id FROM patients WHERE id NOT IN (SELECT patient_id FROM "
            f"appointments WHERE starts_at = '{starts_at}' AND patient_id IS "
            "NOT NULL) ORDER BY id LIMIT 2")]
    if len(spare) < 2:
        return None
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
            " status, source, created_at, doctor_id, comment, room_id)"
            " VALUES(?,?,?,?,'confirmed','admin',?,?,?,?)",
            (spare[0], service, doctor, starts_at,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK, lane))
        con.commit()
    finally:
        con.close()
    return doctor, starts_at, did, spare[1], room, before, 1


def live_in_lane(db: pathlib.Path, lane: str):
    """Живая запись, которая УЖЕ стоит в полосе, и пациент, свободный в её
    час. Когда полоса занята у каждого образца, вставлять нечего: запись
    полосы в базе настоящая, меряется отказ второй записи в ту же полосу."""
    live = rows(db, "SELECT doctor, starts_at, doctor_id FROM appointments "
                "WHERE status IN ('confirmed','arrived') AND doctor_id IS NOT NULL "
                "AND room_id = ? ORDER BY starts_at DESC, id DESC LIMIT 1", (lane,))
    if not live:
        return None
    doctor, starts_at, did = live[0]
    spare = rows(db, "SELECT id FROM patients WHERE id NOT IN (SELECT patient_id FROM "
                     "appointments WHERE starts_at = ? AND patient_id IS NOT NULL) "
                     "ORDER BY id LIMIT 1", (starts_at,))
    if not spare:
        return None
    return doctor, starts_at, did, spare[0][0], lane, live_at(db, did, starts_at), 0


def blocked_room(db: pathlib.Path, pid, doctor, starts_at, did, room) -> bool:
    """Отбивает ли САМА база запись в этот кабинет. Вставка откатывается."""
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
            " status, source, created_at, doctor_id, comment, room_id)"
            " VALUES(?,'Consultație',?,?,'confirmed','admin',?,?,?,?)",
            (pid, doctor, starts_at,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK, room))
        return False
    except sqlite3.IntegrityError:
        return True
    finally:
        con.rollback()
        con.close()


def blocked_null_pair(db: pathlib.Path, doctor, did) -> bool:
    """Две записи врачу без кабинета на один час: вторую обязан отбить индекс
    (COALESCE в ключе). Час далеко впереди — проверка не зависит от того, есть
    ли в картотеке записи без кабинета. Обе вставки откатываются."""
    when = "2099-01-05T06:00:00+00:00"
    pids = [r[0] for r in rows(db, "SELECT id FROM patients ORDER BY id LIMIT 2")]
    if len(pids) < 2:
        return False
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    con = sqlite3.connect(str(db))
    try:
        for pid in pids:
            con.execute(
                "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
                " status, source, created_at, doctor_id, comment, room_id)"
                " VALUES(?,'Consultație',?,?,'confirmed','admin',?,?,?,NULL)",
                (pid, doctor, when, stamp, did, MARK))
        return False
    except sqlite3.IntegrityError:
        return True
    finally:
        con.rollback()
        con.close()


class Lab:
    """Что нужно `engine_check.Engine`: exe, папка для stderr, корень данных
    (для хвоста лога) и окружение запуска."""

    def __init__(self, lab: pathlib.Path, exe_name: str | None) -> None:
        self.dir, self.data = lab, lab
        self.exe = lab / "engine" / exe_name if exe_name else None

    def env(self, port: int) -> dict:
        lab = self.dir
        # ⛔ (09-26) TEMP — внутри песочницы, а не в общем %TEMP%.
        tmp = lab / "tmp"
        tmp.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("DENTART_")}
        # ⛔ DENTART_DATA_DIR обязателен с P1: лаунчер не считает папку данных
        # от места exe. Без него песочница запустила бы движок поверх
        # НАСТОЯЩЕЙ картотеки в %ProgramData%, а проверяла бы подготовленную копию.
        env.update({"DENTART_SHELL": "tauri", "DENTART_SHELL_TOKEN": secrets.token_hex(16),
                    "DENTART_PORT": str(port), "ADMIN_KEY": KEY,
                    "DENTART_DATA_DIR": str(lab), "TEMP": str(tmp), "TMP": str(tmp),
                    "DENTART_PROFILE_DIR": str(lab / "webview"),
                    "DENTART_UPDATE_CHECK": "off"})
        return env


def run_lab(lab: pathlib.Path, exe_name: str | None, port: int):
    """Движок так, как его запускает оболочка: `DENTART_SHELL=tauri`, трубы
    `DP1`, своё задание Windows (`engine_check.Engine`). Без имени exe — тот
    же лаунчер из исходников."""
    e = Engine(Lab(lab, exe_name), port).start()
    ev = e.wait_event({"ready", "busy", "fatal"}, READY_LIMIT)
    alive = ev is not None and ev.get("event") == "ready"
    if not alive:
        print(f"      (движок не сказал ready: {ev!r}){e.tail()}")
    return e, f"http://127.0.0.1:{port}", alive


def admin_page(base: str) -> str:
    """Страница журнала глазами директора.

    ⚠️ Вход — POST /admin/login с куки-джаром, как у человека. Ключ в адресе
    (`/admin?key=…`) и самодельная кука программа не принимает НИКОГДА: такой
    запрос уезжает редиректом на страницу входа, и проверка «баннер виден»
    молча отвечала бы «нет» на любой сборке.
    """
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode({"password": KEY, "next": "/admin"}).encode()
    try:
        op.open(base + "/admin/login", data, timeout=15).read()
        with op.open(base + "/admin", timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print("      (страницу журнала открыть не удалось: %r)" % (e,))
        return ""


def banner_visible(base: str) -> bool:
    """Виден ли директору баннер про неразведённые часы."""
    return "Protecția împotriva programărilor duble" in admin_page(base)


def blocked(db: pathlib.Path, pid, doctor, starts_at, status, did, room=None) -> bool:
    """Отбивает ли САМА база такую запись. Вставка откатывается."""
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
            " status, source, created_at, doctor_id, comment, room_id)"
            " VALUES(?,'Consultație',?,?,?,'admin',?,?,?,?)",
            (pid, doctor, starts_at, status,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK, room))
        return False
    except sqlite3.IntegrityError:
        return True
    finally:
        con.rollback()
        con.close()


def stop(e, port: int) -> None:
    """Остановить движок СЛОВОМ (база закрыта, `-wal` сброшен — следующий шаг
    читает базу обычным sqlite3), погасить его задание и дождаться, пока порт
    освободится.

    ⛔ Порт ждём не для красоты: процесс, оставшийся жить, держит порт, а
    следующий запуск в этой же лаборатории молча разговаривал бы со СТАРЫМ:
    база не перечитывается, и шаг про «после разведения записей защита встаёт
    сама» проваливается на ровном месте, хотя программа исправна. Ровно так
    эта проверка и соврала 08-16 (тогда — onefile-загрузчик и его ребёнок).
    """
    if e.proc is not None and e.proc.poll() is None:
        try:
            e.wait_exit(e.send_stop(), STOP_LIMIT + 5)
        except OSError:
            pass
    e.close()
    import socket
    for _ in range(40):                      # порт освобождается не мгновенно
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.5)
    print(f"      ⚠️ порт {port} всё ещё занят — следующий шаг может соврать")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(LIVE_DB), help="боевая база (только чтение)")
    ap.add_argument("--exe", default=str(ROOT / "dist" / "DentPilot-Engine" / "DentPilot-Engine.exe"))
    ap.add_argument("--src", action="store_true",
                    help="движок из исходников этого дерева — проверить сам скрипт или правку "
                         "до сборки; шаг 3a выпуска гоняется БЕЗ этого ключа, на собранном")
    args = ap.parse_args()

    db_src = pathlib.Path(args.db)
    exe = None if args.src else pathlib.Path(args.exe)
    exe_name = exe.name if exe else None
    if not db_src.exists():
        sys.exit(f"базы нет: {db_src}")
    if exe is not None and not exe.exists():
        sys.exit(f"движка нет: {exe} — соберите Build-Engine.ps1 или укажите --exe")
    try:
        sqlite3.connect(str(db_src)).execute("SELECT 1 FROM schema_meta LIMIT 1")
    except sqlite3.DatabaseError:
        sys.exit("база не открывается обычным sqlite3 — она ЗАШИФРОВАНА.\n"
                 "Проверку делать на незашифрованной копии или на демо-базе: "
                 "внести конфликт в шифрованную мимо программы нечем.")

    port = free_port()
    lab = prepare_lab(db_src, exe)
    db = lab / "data" / "dental.db"
    print(f"песочница: {lab}\nпорт: {port}\nбоевая база НЕ тронута: {db_src}")
    print("движок: " + (str(exe) if exe else
                        "из исходников (не шаг 3a выпуска: тот — на собранном)") + "\n")

    parked = park_parallel(db)
    if parked:
        print(f"в копии отложено записей: {len(parked)} — законные пары врача на один час "
              "(два кабинета или кабинет и полоса Control);\n"
              "до обновления такой пары у клиники быть не могло, перед шагом 4 они вернутся:")
        for _, _, doc, at, room in parked[:5]:
            print(f"      {doc} · {at} · {room or 'без кабинета'}")
        if len(parked) > 5:
            print(f"      … и ещё {len(parked) - 5}")
        print()
    downgrade(db)
    doctor, when = inject_conflict(db)
    print(f"конфликт заведён: {doctor} · {when} — две живые записи\n")

    print("ШАГ 1. Запуск на базе с конфликтом")
    e, base, alive = run_lab(lab, exe_name, port)
    say(alive, "программа запустилась", "не ответила на /health — это ТОТ САМЫЙ дефект")
    if alive:
        meta = dict(rows(db, "SELECT key, value FROM schema_meta"))
        say(meta.get("version") == SCHEMA_TARGET,
            f"версия схемы поднялась до {SCHEMA_TARGET}",
            f"версия {meta.get('version')!r}")
        say(bool(meta.get("uq_waiting_pending")), "метка незавершённости стоит")
        idx = index_state(db)
        say(all(n in idx for n in UQ), "все три проверки на месте",
            f"индексы: {sorted(idx)}")
        say(not any(n in idx for n in UQ_OLD),
            "прежние индексы врача (без кабинета в ключе) сняты",
            f"индексы: {sorted(idx)}")
        say(all("waiting" not in idx.get(n, "") for n in UQ),
            "страховка осталась узкой, а не расширилась мимо данных",
            f"индексы: {sorted(idx)}")
        say(banner_visible(base), "директор видит баннер про неразведённые часы")
    stop(e, port)

    print("\nШАГ 2. Конфликт разведён, запуск снова")
    sql(db, f"DELETE FROM appointments WHERE comment = '{MARK}'")
    e, base, alive = run_lab(lab, exe_name, port)
    say(alive, "программа запустилась")
    if alive:
        meta = dict(rows(db, "SELECT key, value FROM schema_meta"))
        say(not meta.get("uq_waiting_pending"), "метка снялась сама")
        idx = index_state(db)
        say(all("waiting" in idx.get(n, "") for n in UQ),
            "широкие индексы легли сами", f"индексы: {sorted(idx)}")
        say(not banner_visible(base), "баннер исчез")
    stop(e, port)

    # ---- ШАГ 3: база, пришедшая от опубликованной 1.20.0 ----
    # ⛔ Обновление не имеет права уменьшить защиту, которая у клиники РАБОТАЛА.
    # Ступень лестницы, выбранная одна на все три индекса, делала ровно это.
    print("\nШАГ 3. База от 1.20.0: два индекса широкие, третьего нет")
    sql(db, f"DELETE FROM appointments WHERE comment = '{MARK}'")
    try:
        from_1200(db)
        made = inject_renamed(db)
    except sqlite3.IntegrityError as e:
        made = None
        print(f"      (состояние 1.20.0 на этой базе не собирается: {e})")
    if not made:
        print("      ПРОПУЩЕН: в базе нет активной записи с doctor_id или двух "
              "пациентов, свободных в тот час. Сценарий закрыт прогоном "
              "(test_migrate.suite_from_1200); на бинарнике — только тут.")
    else:
        renamed, when, busy_pid, free_pid, room = made
        doc_dup = (free_pid, renamed, when, "waiting", "zz-canary", room)
        pat_dup = (busy_pid, "Dr. Canary Nobody", when, "waiting", "zz-canary")
        say(blocked(db, *doc_dup), "до обновления: широкая защита врача работает",
            "фикстура не воспроизводит состояние после 1.20.0")
        say(blocked(db, *pat_dup),
            "до обновления: широкая защита пациента работает",
            "фикстура не воспроизводит состояние после 1.20.0")
        e, base, alive = run_lab(lab, exe_name, port)
        say(alive, "программа запустилась")
        if alive:
            say(blocked(db, *doc_dup), "обновление НЕ сузило защиту врача",
                "работавший ШИРОКИЙ индекс заменён на узкий — это сделали мы")
            say(blocked(db, *pat_dup), "обновление НЕ сузило защиту пациента",
                "тот же слом на индексе пациента")
            idx = index_state(db)
            say("waiting" in idx.get("uq_doc_room_slot", "")
                and "waiting" in idx.get("uq_patient_slot", ""),
                "широкие индексы остались широкими", f"индексы: {sorted(idx)}")
            say("uq_docid_room_slot" in idx,
                "недостающая проверка положена (пусть и узкой)",
                f"индексы: {sorted(idx)}")
        stop(e, port)

    # ---- ШАГ 4: врач в двух кабинетах ----
    # Пара заводится ПОСЛЕ обновления (колонка кабинета появляется на старте)
    # и проверяется вторым запуском: сторож сверяет индексы на каждом старте.
    print("\nШАГ 4. Врач в двух кабинетах: две записи на один час")
    sql(db, f"DELETE FROM appointments WHERE comment = '{MARK}'")
    e, base, alive = run_lab(lab, exe_name, port)   # развести шаг 3, довести индексы
    stop(e, port)
    if alive and parked:
        say(unpark(db, parked),
            f"законные пары живой базы возвращены ({len(parked)}): новые индексы их принимают",
            "живая пара не проходит индексы обновлённой базы")
    pairs = 0
    for title, lane, what in (
            (None, ROOM, "параллельной парой"),
            ("ШАГ 5. Полоса Control: запись в полосе рядом с записью в кабинете",
             CONTROL_LANE, "парой «кабинет + полоса Control»")):
        if title:
            print("\n" + title)
        made = inject_parallel(db, lane) if alive else None
        if alive and not made and lane == CONTROL_LANE:
            made = live_in_lane(db, lane)
        if not made:
            print("      ПРОПУЩЕН: в базе нет активной записи с doctor_id и пациентом, "
                  "у врача которой этот час в полосе свободен, или двух пациентов, "
                  "свободных в тот час. Сценарий закрыт прогоном "
                  "(test_migrate.suite_v11_rooms, test_rooms); на бинарнике — только тут.")
            continue
        pairs += 1
        doctor, when, did, free_pid, room, before, added = made
        if not added:
            print("      (полоса занята у каждого образца — меряется живая запись полосы)")
        e, base, alive = run_lab(lab, exe_name, port)
        say(alive, f"программа запустилась на базе с {what}")
        if alive:
            meta = dict(rows(db, "SELECT key, value FROM schema_meta"))
            say(not meta.get("uq_waiting_pending"), "метки незавершённости нет")
            say(not banner_visible(base), "баннера нет: пара законна")
            idx = index_state(db)
            say(sorted(idx) == sorted(UQ) and all("waiting" in idx[n] for n in UQ),
                "в базе три широких индекса под новыми именами", f"индексы: {idx}")
            now = live_at(db, did, when)
            say(now == before + added, "записи этого часа на месте",
                f"записей в этот час: {now}, ждали {before + added}")
            if lane == ROOM:
                say(blocked_room(db, free_pid, doctor, when, did, ROOM),
                    "третья запись в занятый кабинет отбита базой")
                say(blocked_room(db, free_pid, doctor, when, did, room),
                    "третья запись в кабинет первой записи пары отбита базой")
                say(blocked_null_pair(db, doctor, did),
                    "две записи без кабинета на один час отбиты базой (COALESCE в ключе)")
            else:
                say(blocked_room(db, free_pid, doctor, when, did, CONTROL_LANE),
                    "вторая запись в ту же полосу Control отбита базой")
        stop(e, port)
    if pairs or (alive and parked):
        # версия назад — как после оборванного старта: шаг 11 идёт второй раз
        print("\nПовтор шага 11 по базе с параллельными парами")
        sql(db, "UPDATE schema_meta SET value='10' WHERE key='version'")
        e, base, alive = run_lab(lab, exe_name, port)
        say(alive, "программа запустилась")
        if alive:
            meta = dict(rows(db, "SELECT key, value FROM schema_meta"))
            say(meta.get("version") == SCHEMA_TARGET and not meta.get("uq_waiting_pending"),
                f"версия снова {SCHEMA_TARGET}, метки нет", f"{meta.get('version')!r}")
            say(not banner_visible(base), "баннера нет")
            idx = index_state(db)
            say(sorted(idx) == sorted(UQ) and all("waiting" in idx[n] for n in UQ),
                "индексы те же три, широкие", f"индексы: {idx}")
        stop(e, port)
    sql(db, f"DELETE FROM appointments WHERE comment = '{MARK}'")

    print()
    if fails:
        print(f"ИТОГ: не сошлось {fails} — показать это перед публикацией.")
        print(f"песочница оставлена для разбора: {lab}")
        return 1
    print("ИТОГ: всё сошлось. Клиника с двойной бронью запустится и узнает,")
    print("      какие часы развести; после этого страховка встанет сама.")
    # Windows отпускает файлы погашенного процесса с задержкой: повтор, и
    # вслух, если нет
    for _ in range(10):
        shutil.rmtree(lab, ignore_errors=True)
        if not lab.exists():
            break
        time.sleep(0.5)
    else:
        print(f"⚠️  песочница НЕ удалена: {lab}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
