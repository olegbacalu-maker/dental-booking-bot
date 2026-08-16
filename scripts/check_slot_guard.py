"""Канареечная проверка защиты слота (миграция, шаг 4).

Отвечает на вопрос, который обычным запуском канарейки НЕ проверяется: что
делает программа, когда в картотеке УЖЕ есть две живые записи на один час.
Такой пары на канарейке нет, поэтому её заводим искусственно — в КОПИИ базы.

  python scripts/check_slot_guard.py
  python scripts/check_slot_guard.py --db "C:\\Users\\Public\\DentPilot\\data\\dental.db"

⛔ Живая база только ЧИТАЕТСЯ. Всё происходит в песочнице (копия exe + копия
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
     ШИРОКИЕ, третьего нет. Обновление не имеет права их СУЗИТЬ (08-16).

⭐ Защита меряется ПОВЕДЕНИЕМ базы (пробная вставка + rollback), а не текстом
индекса: индекс, который существует, но ничего не стережёт, по тексту от
рабочего неотличим.
"""
import argparse
import http.cookiejar
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE_DB = pathlib.Path(r"C:\Users\Public\DentPilot\data\dental.db")
KEY = "canary1234"
MARK = "CANARY-SLOT-GUARD"          # по нему находим и убираем внесённую запись
NARROW = "('confirmed','arrived')"  # предикат, каким он был до 1.20.0
WIDE = "('confirmed','waiting','arrived')"   # предикат, к которому ведёт шаг 4
UQ = ("uq_doctor_slot", "uq_patient_slot", "uq_doctor_slot_id")
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


def prepare_lab(db_src: pathlib.Path, exe: pathlib.Path) -> pathlib.Path:
    lab = pathlib.Path(tempfile.mkdtemp(prefix="dp_slotguard_"))
    (lab / "data").mkdir()
    shutil.copy2(db_src, lab / "data" / "dental.db")     # ⛔ только копия
    shutil.copy2(exe, lab / exe.name)
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


def rows(db: pathlib.Path, query: str) -> list:
    con = sqlite3.connect(str(db))
    try:
        return con.execute(query).fetchall()
    finally:
        con.close()


def index_state(db: pathlib.Path) -> dict:
    """Имя слотового индекса → его определение, по факту в базе."""
    return {name: (sql_text or "") for name, sql_text in rows(
        db, "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'uq_%slot%'")}


def downgrade(db: pathlib.Path) -> None:
    """Копия базы становится такой, какой она была у клиники до 1.20.0."""
    sql(db,
        "DROP INDEX IF EXISTS uq_doctor_slot",
        "DROP INDEX IF EXISTS uq_patient_slot",
        "DROP INDEX IF EXISTS uq_doctor_slot_id",
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
    live = rows(db, "SELECT patient_id, service, doctor, starts_at, doctor_id "
                    "FROM appointments WHERE status IN ('confirmed','arrived') "
                    "ORDER BY starts_at DESC LIMIT 1")
    if not live:
        sys.exit("в базе нет ни одной активной записи — конфликт не из чего "
                 "сделать; проверьте на базе с реальным расписанием")
    pid, service, doctor, starts_at, did = live[0]
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
            " status, source, created_at, doctor_id, comment)"
            " VALUES(?,?,?,?,'waiting','admin',?,?,?)",
            (pid, service, doctor, starts_at,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK))
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
        "DROP INDEX IF EXISTS uq_doctor_slot",
        "DROP INDEX IF EXISTS uq_patient_slot",
        "DROP INDEX IF EXISTS uq_doctor_slot_id",
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
    live = rows(db, "SELECT patient_id, service, doctor, starts_at, doctor_id "
                    "FROM appointments WHERE status IN ('confirmed','arrived') "
                    "AND doctor_id IS NOT NULL ORDER BY starts_at DESC LIMIT 1")
    if not live:
        return None
    pid, service, doctor, starts_at, did = live[0]
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
            " status, source, created_at, doctor_id, comment)"
            " VALUES(?,?,?,?,'waiting','admin',?,?,?)",
            (spare[0], service, renamed, starts_at,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK))
        con.commit()
    finally:
        con.close()
    return renamed, starts_at, spare[0], spare[1]


def run_lab(lab: pathlib.Path, exe_name: str, port: int, seconds: int = 90):
    env = dict(os.environ)
    env.update({"DENTART_BROWSER_MODE": "1", "DENTART_NO_BROWSER": "1",
                "DENTART_PORT": str(port), "ADMIN_KEY": KEY})
    proc = subprocess.Popen([str(lab / exe_name)], cwd=str(lab), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return proc, base, False          # процесс умер, не дождавшись
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as r:
                json.loads(r.read())
                return proc, base, True
        except Exception:
            time.sleep(1)
    return proc, base, False


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


def blocked(db: pathlib.Path, pid, doctor, starts_at, status, did) -> bool:
    """Отбивает ли САМА база такую запись. Вставка откатывается."""
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at,"
            " status, source, created_at, doctor_id, comment)"
            " VALUES(?,'Consultație',?,?,?,'admin',?,?,?)",
            (pid, doctor, starts_at, status,
             time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), did, MARK))
        return False
    except sqlite3.IntegrityError:
        return True
    finally:
        con.rollback()
        con.close()


def stop(proc) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(LIVE_DB), help="боевая база (только чтение)")
    ap.add_argument("--exe", default=str(ROOT / "dist" / "DentPilot.exe"))
    args = ap.parse_args()

    db_src, exe = pathlib.Path(args.db), pathlib.Path(args.exe)
    if not db_src.exists():
        sys.exit(f"базы нет: {db_src}")
    if not exe.exists():
        sys.exit(f"exe нет: {exe} — соберите Build-Installer.ps1 или укажите --exe")
    try:
        sqlite3.connect(str(db_src)).execute("SELECT 1 FROM schema_meta LIMIT 1")
    except sqlite3.DatabaseError:
        sys.exit("база не открывается обычным sqlite3 — она ЗАШИФРОВАНА.\n"
                 "Проверку делать на незашифрованной копии или на демо-базе: "
                 "внести конфликт в шифрованную мимо программы нечем.")

    port = free_port()
    lab = prepare_lab(db_src, exe)
    db = lab / "data" / "dental.db"
    print(f"песочница: {lab}\nпорт: {port}\nбоевая база НЕ тронута: {db_src}\n")

    downgrade(db)
    doctor, when = inject_conflict(db)
    print(f"конфликт заведён: {doctor} · {when} — две живые записи\n")

    print("ШАГ 1. Запуск на базе с конфликтом")
    proc, base, alive = run_lab(lab, exe.name, port)
    say(alive, "программа запустилась", "не ответила на /health — это ТОТ САМЫЙ дефект")
    if alive:
        meta = dict(rows(db, "SELECT key, value FROM schema_meta"))
        say(meta.get("version") == "4", "версия схемы поднялась до 4",
            f"версия {meta.get('version')!r}")
        say(bool(meta.get("uq_waiting_pending")), "метка незавершённости стоит")
        idx = index_state(db)
        say(all(n in idx for n in UQ), "все три проверки на месте",
            f"индексы: {sorted(idx)}")
        say(all("waiting" not in idx.get(n, "") for n in UQ),
            "страховка осталась узкой, а не расширилась мимо данных",
            f"индексы: {sorted(idx)}")
        say(banner_visible(base), "директор видит баннер про неразведённые часы")
    stop(proc)

    print("\nШАГ 2. Конфликт разведён, запуск снова")
    sql(db, f"DELETE FROM appointments WHERE comment = '{MARK}'")
    proc, base, alive = run_lab(lab, exe.name, port)
    say(alive, "программа запустилась")
    if alive:
        meta = dict(rows(db, "SELECT key, value FROM schema_meta"))
        say(not meta.get("uq_waiting_pending"), "метка снялась сама")
        idx = index_state(db)
        say(all("waiting" in idx.get(n, "") for n in UQ),
            "широкие индексы легли сами", f"индексы: {sorted(idx)}")
        say(not banner_visible(base), "баннер исчез")
    stop(proc)

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
        renamed, when, busy_pid, free_pid = made
        doc_dup = (free_pid, renamed, when, "waiting", "zz-canary")
        pat_dup = (busy_pid, "Dr. Canary Nobody", when, "waiting", "zz-canary")
        say(blocked(db, *doc_dup), "до обновления: широкая защита врача работает",
            "фикстура не воспроизводит состояние после 1.20.0")
        say(blocked(db, *pat_dup),
            "до обновления: широкая защита пациента работает",
            "фикстура не воспроизводит состояние после 1.20.0")
        proc, base, alive = run_lab(lab, exe.name, port)
        say(alive, "программа запустилась")
        if alive:
            say(blocked(db, *doc_dup), "обновление НЕ сузило защиту врача",
                "работавший ШИРОКИЙ индекс заменён на узкий — это сделали мы")
            say(blocked(db, *pat_dup), "обновление НЕ сузило защиту пациента",
                "тот же слом на индексе пациента")
            idx = index_state(db)
            say("waiting" in idx.get("uq_doctor_slot", "")
                and "waiting" in idx.get("uq_patient_slot", ""),
                "широкие индексы остались широкими", f"индексы: {sorted(idx)}")
            say("uq_doctor_slot_id" in idx,
                "недостающая проверка положена (пусть и узкой)",
                f"индексы: {sorted(idx)}")
        stop(proc)

    print()
    if fails:
        print(f"ИТОГ: не сошлось {fails} — показать это перед публикацией.")
        print(f"песочница оставлена для разбора: {lab}")
        return 1
    print("ИТОГ: всё сошлось. Клиника с двойной бронью запустится и узнает,")
    print("      какие часы развести; после этого страховка встанет сама.")
    shutil.rmtree(lab, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
