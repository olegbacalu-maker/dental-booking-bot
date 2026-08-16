"""Шифрование картотеки (08-09): ключ, переезд базы, работа на шифре.

Три набора и три разных вопроса:

* `suite_key`     — код восстановления: то, что клиника переписывает с бумаги.
* `suite_convert` — переезд базы. Самое опасное место продукта: ошибка здесь
  не роняет программу, а тихо теряет картотеку.
* `suite_live`    — программа НА зашифрованной базе, целиком через HTTP.

⚠️ Проверка «в файле нет открытого имени» смотрит в сырые байты. Иначе весь
набор был бы зелёным и при выключенном шифровании: библиотека подключается и
молча пишет обычный SQLite, если `PRAGMA key` не была первой операцией.
"""
import os
import pathlib
import re
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app.core import dbkey  # noqa: E402

from harness import FIXTURES, Client, Result, Server  # noqa: E402

MARK = "Ionescu-Test-Criptare"


def _plain_db(path: pathlib.Path, rows: int = 3) -> None:
    import sqlite3
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE patients(id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE appointments(id INTEGER PRIMARY KEY, note TEXT)")
    for i in range(rows):
        con.execute("INSERT INTO patients(name) VALUES (?)", (f"{MARK}-{i}",))
    con.commit()
    con.close()


# ---------- 1. код восстановления ----------

def suite_key(res: Result) -> None:
    key = dbkey.generate()
    res.check("ключ ровно 256 бит", len(key), 32)

    code = dbkey.format_recovery(key)
    res.ok("код разбит на группы по 6", all(len(g) == 6 for g in code.split("-")[:-1]),
           f"код: {code}")
    # ⭐ Ценно не отсутствие букв O и I (они есть), а отсутствие ЦИФР 0/1/8/9:
    # тогда «O» читается только как буква, а единицу не с чем спутать.
    res.ok("в коде нет цифр, которые путают с буквами",
           not (set("0189") & set(code.replace("-", ""))),
           f"в коде встретились 0/1/8/9: {code}")
    res.check("код возвращает тот же ключ", dbkey.parse_recovery(code), key)

    # человек перепишет иначе, чем напечатано, — это норма, а не ошибка
    for label, text in (("нижним регистром", code.lower()),
                        ("без дефисов", code.replace("-", "")),
                        ("с пробелами", code.replace("-", " ")),
                        ("с переносом строки", code.replace("-", "\n", 1))):
        res.check(f"код читается {label}", dbkey.parse_recovery(text), key)

    for label, bad in (("пустой", ""), ("мусор", "не-код-вовсе"),
                       ("обрезанный", code[:12]), ("None", None)):
        res.ok(f"{label} код отвергнут", dbkey.parse_recovery(bad) is None,
               "принят как ключ")

    # ⭐ 0 и O в алфавите base32 отсутствуют, и «исправлять» их нельзя: замена
    # превратила бы опечатку в ДРУГОЙ валидный ключ, а тот открыл бы базу
    # ошибкой «файл не является базой» вместо честного «код неверный».
    # ⚠️ Раньше подмена делалась как code.replace("O", "0") под условием «если
    # O вообще попалась», и проверка то выполнялась, то нет — код-то
    # случайный. Счёт прогона гулял на единицу между запусками, а плавающий
    # счёт хуже отсутствующей проверки: скачок списывают на шум ровно тогда,
    # когда он означает потерянного сторожа (так и случилось 08-10, полчаса
    # искал). Подменяем ПЕРВЫЙ знак — цифры 0 в алфавите base32 нет, поэтому
    # проверка одна и та же при любом коде.
    res.ok("знак вне алфавита не подменяется молча",
           dbkey.parse_recovery("0" + code[1:]) != key,
           "принял чужой код как верный — опечатка стала бы другим ключом")

    # ⚠️ SQLCipher импортируется ВНУТРИ функции (нужен только клинике с
    # шифрованием), и PyInstaller такое замечает не всегда. Без явного
    # --hidden-import exe соберётся, дымовой тест пройдёт, а шифрование
    # откажет ровно у той клиники, которая его включит.
    build = (pathlib.Path(__file__).resolve().parents[1] / "Build-Desktop.ps1"
             ).read_text(encoding="utf-8", errors="replace")
    res.ok("sqlcipher3 явно назван сборке hidden-import'ом",
           "--hidden-import sqlcipher3" in build,
           "PyInstaller может не положить модуль в exe")
    # ⛔ И его обязан СТАВИТЬ файл зависимостей. Найдено ревью 08-09: модуль
    # стоял в окружении руками, а `--hidden-import` отсутствующего модуля
    # PyInstaller ошибкой не считает. Чистая машина собрала бы программу без
    # шифрования, дымовой тест (обычная база) прошёл бы, и обнаружилось бы это
    # у той клиники, которая шифрование включит.
    reqs = (pathlib.Path(__file__).resolve().parents[1] / "bot"
            / "requirements-desktop.txt").read_text(encoding="utf-8")
    res.ok("sqlcipher3 стоит в requirements-desktop.txt", "sqlcipher3" in reqs,
           "чистое окружение сборки соберёт exe БЕЗ шифрования")

    val = dbkey.pragma_value(key)
    # ⚠️ Двойные кавычки снаружи — не украшение: без них ATTACH … KEY падает с
    # syntax error, и переезд базы обрывается на середине (поймано тестом)
    res.ok("ключ уходит в SQL строкой с сырым ключом внутри",
           val.startswith('"x\'') and val.endswith('\'"')
           and all(c in "0123456789abcdef" for c in val[3:-2]),
           f"в запрос попало: {val!r}")


# ---------- 2. переезд базы ----------

def suite_convert(res: Result) -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbcrypt_"))
    try:
        db = tmp / "dental.db"
        _plain_db(db, rows=5)
        raw = db.read_bytes()
        res.ok("до переезда имя пациента лежит в файле открыто",
               MARK.encode() in raw, "проверка бессмысленна: имени нет и так")

        key = dbkey.generate()
        counts = dbkey.convert(db, key)
        res.check("переезд сохранил все строки", counts.get("patients"), 5)
        res.ok("после переезда имени в файле нет",
               MARK.encode() not in db.read_bytes(), "данные остались открытыми")

        # ⚠️ Соединение закрываем ЯВНО, даже когда запрос упал: на Windows
        # объект соединения доживает в traceback упавшего запроса и держит файл,
        # а следующий шаг теста получает «Отказано в доступе» вместо результата.
        import sqlite3
        con = sqlite3.connect(str(db))
        try:
            con.execute("SELECT 1 FROM patients").fetchone()
            opened = True
        except sqlite3.DatabaseError:
            opened = False
        finally:
            con.close()
        res.ok("штатный sqlite3 зашифрованную базу не открывает", not opened,
               "открыл — значит шифрования нет")

        import sqlcipher3.dbapi2 as sq
        con = sq.connect(str(db))
        con.execute(f"PRAGMA key = {dbkey.pragma_value(dbkey.generate())}")
        try:
            con.execute("SELECT 1 FROM patients").fetchone()
            wrong_ok = True
        except sq.DatabaseError:
            wrong_ok = False
        con.close()
        res.ok("чужой ключ не открывает", not wrong_ok, "открылось чужим ключом")

        con = sq.connect(str(db))
        con.execute(f"PRAGMA key = {dbkey.pragma_value(key)}")
        got = con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        con.close()
        res.check("верный ключ отдаёт все записи", got, 5)

        # обратный ход обязан существовать: клиника вправе передумать, и это же
        # аварийный выход, если ключ решат вынести на другой носитель
        back = dbkey.convert(db, None, was=key)
        res.check("обратный переезд сохранил строки", back.get("patients"), 5)
        res.ok("после расшифровки файл снова читается штатным sqlite3",
               MARK.encode() in db.read_bytes(), "данные не вернулись")

        # ⚠️ WAL прежнего файла рядом с новым — порча при первом открытии
        db.with_name(db.name + "-wal").write_bytes(b"gunoi")
        dbkey.convert(db, dbkey.generate())
        res.ok("хвост -wal от прежнего файла удалён",
               not db.with_name(db.name + "-wal").exists(),
               "старый WAL остался и докатится поверх новой базы")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 3. программа на зашифрованной базе ----------

def suite_live(res: Result) -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbcrypt_live_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", tmp / "clinic.json")
        key = dbkey.generate()
        if not dbkey.store(key, tmp):
            res.failed.append(("ключ не сохранился под DPAPI",
                               "не Windows или DPAPI отказал"))
            return
        res.check("состояние ключа читается", dbkey.state(tmp), dbkey.OK)

        with Server(dir_=tmp) as s:
            c = Client(s.url).login()
            r = c.post("/admin/patients/new", name=MARK, phone="069555444")
            res.ok("пациент заводится на зашифрованной базе",
                   r.status in (200, 303), f"код {r.status}")
            res.ok("и находится поиском", MARK in c.get(f"/admin/search?q={MARK}").body,
                   "поиск не нашёл только что созданного пациента")

            # ⛔ Находка ревью 08-09: «Pregătește criptarea» при уже включённом
            # шифровании заводило ВТОРОЙ ключ. Переезд под него не мог
            # выполниться никогда, экран навсегда застревал на «подготовлено»,
            # а лист печатался с ключом, который не открывает ничего. Открытая
            # в соседней вкладке страница — обычное дело в регистратуре.
            again = c.post("/admin/settings/crypt/prepare")
            res.check("повторная подготовка при живом шифровании отклонена",
                      again.msg, "crypt_on")
            res.ok("второй ключ не заведён",
                   not (tmp / dbkey.PENDING_FILE).exists(),
                   "ожидающий ключ создан поверх рабочего — лист станет ложным")
            res.check("рабочий ключ не тронут", dbkey.state(tmp), dbkey.OK)

            # ⚠️ FAQ версионируется вместе с поведением. Ответ про переезд на
            # другой компьютер обещал, что заново вводить надо только токен
            # бота, — с шифрованием это враньё, и цена ему картотека: директор
            # увёз бы папку без листа восстановления.
            faq = c.get("/admin/settings/faq").body
            res.ok("FAQ про переезд называет лист восстановления",
                   "Mutăm programul" in faq and "foaia de recuperare" in faq,
                   "ответ про новый ПК молчит про лист — папку увезут без него")

        raw = (tmp / "dental.db").read_bytes()
        res.ok("имя пациента в файле базы не лежит открытым",
               MARK.encode() not in raw,
               "программа записала данные мимо шифрования")
        res.ok("файл начинается не как обычный SQLite",
               not raw.startswith(b"SQLite format 3"),
               f"заголовок: {raw[:16]!r}")

        # ключ унесли — база обязана честно не открыться, а не притвориться битой
        (tmp / dbkey.KEY_FILE).write_text("dpapi:мусор", encoding="utf-8")
        res.check("испорченный ключ виден как «не читается»",
                  dbkey.state(tmp), dbkey.UNREADABLE)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 4. отложенный переезд (его делает лаунчер) ----------

def suite_pending(res: Result) -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbcrypt_pend_"))
    try:
        db = tmp / "dental.db"
        _plain_db(db, rows=4)
        key = dbkey.generate()
        res.ok("заказ на шифрование принят", dbkey.request_encrypt(tmp, key),
               "ключ не удалось положить в ожидание")
        res.ok("до перезапуска шифрование ещё выключено", not dbkey.enabled(tmp),
               "ключ встал на место рано — программа не откроет открытую базу")
        res.check("лист печатается из ожидающего ключа",
                  dbkey.load_pending(tmp), key)

        # ⛔ Прежние ежедневные копии — полная картотека открытым текстом рядом
        # с зашифрованной базой (находка ревью 08-09). Оставить их значит и
        # свести шифрование к нулю, и соврать на экране настроек, где написано,
        # что копии зашифрованы.
        (tmp / "backups").mkdir()
        old_copy = tmp / "backups" / "dental_20260101_1.db"
        _plain_db(old_copy, rows=2)
        res.ok("до переезда старая копия лежит открытой",
               MARK.encode() in old_copy.read_bytes(), "копия и так не читается")

        res.ok("лаунчер выполнил переезд",
               (dbkey.apply_pending(tmp) or "").startswith("encrypted"),
               "переезд не выполнен")
        res.ok("прежние ежедневные копии переехали под ключ",
               MARK.encode() not in old_copy.read_bytes(),
               "полная картотека осталась открытой рядом с зашифрованной базой")
        res.check("ключ встал на место", dbkey.state(tmp), dbkey.OK)
        res.ok("данных в открытом виде нет", MARK.encode() not in db.read_bytes(),
               "база осталась открытой")
        res.ok("повторный проход ничего не делает", dbkey.apply_pending(tmp) is None,
               "лаунчер пытается переехать второй раз")

        # ⭐ Обрыв питания МЕЖДУ переездом и укладкой ключа: база уже зашифрована,
        # заказ ещё лежит. Второй проход по флагу «в лоб» зашифровал бы шифр и
        # убил картотеку — поэтому apply_pending смотрит на состояние файла.
        shutil.copy(tmp / dbkey.KEY_FILE, tmp / dbkey.PENDING_FILE)
        (tmp / dbkey.KEY_FILE).unlink()
        res.check("недоделанный переезд доводится до конца",
                  dbkey.apply_pending(tmp), "encrypted")
        res.check("после доводки ключ читается", dbkey.state(tmp), dbkey.OK)
        import sqlcipher3.dbapi2 as sq
        con = sq.connect(str(db))
        con.execute(f"PRAGMA key = {dbkey.pragma_value(dbkey.load(tmp))}")
        got = con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        con.close()
        res.check("картотека цела после доводки", got, 4)

        # ⛔ Находка враждебного ревью 08-09, класс «потеря картотеки».
        # Заказ на выключение + переставший читаться ключ (сброс пароля
        # Windows, другой ПК). Безусловный unlink стирал db.key, база
        # оставалась зашифрованной, `enabled()` говорил «шифрования нет», и
        # экран восстановления становился недостижим — при ПРАВИЛЬНОМ листе
        # на руках. Ключ имеет право исчезнуть только после того, как база
        # действительно открылась без него.
        good = (tmp / dbkey.KEY_FILE).read_text(encoding="utf-8")
        (tmp / dbkey.KEY_FILE).write_text("dpapi:AAAA", encoding="utf-8")
        dbkey.request_decrypt(tmp)
        res.check("нечитаемый ключ не даёт соврать про расшифровку",
                  dbkey.apply_pending(tmp), "decrypt-failed")
        res.ok("файл ключа на месте — путь в восстановление сохранён",
               (tmp / dbkey.KEY_FILE).exists(),
               "ключ стёрт: база зашифрована, а войти нечем")
        res.check("состояние честное", dbkey.state(tmp), dbkey.UNREADABLE)
        (tmp / dbkey.KEY_FILE).write_text(good, encoding="utf-8")

        dbkey.request_decrypt(tmp)
        res.check("обратный заказ выполнен", dbkey.apply_pending(tmp), "decrypted")
        res.check("после расшифровки шифрование выключено", dbkey.state(tmp), dbkey.OFF)
        res.ok("данные вернулись в открытый вид", MARK.encode() in db.read_bytes(),
               "база не расшифровалась")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 5. режим восстановления ----------

def suite_recover(res: Result) -> None:
    """Ключ не читается (новый ПК). Программа обязана подняться и дать экран."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbcrypt_rec_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", tmp / "clinic.json")
        key = dbkey.generate()
        dbkey.store(key, tmp)
        with Server(dir_=tmp) as s:          # обычный старт: база создаётся
            Client(s.url).login().get("/admin")

        # ключ «остался на прошлой машине»
        (tmp / dbkey.KEY_FILE).write_text("dpapi:AAAA", encoding="utf-8")
        with Server(dir_=tmp) as s:
            c = Client(s.url)
            r = c.get("/admin")
            res.ok("журнал уводит на экран восстановления",
                   r.status == 303 and "/admin/recover" in r.location,
                   f"код {r.status}, location {r.location!r}")
            page = c.get("/admin/recover")
            res.ok("экран восстановления открывается",
                   page.status == 200 and "recuperare" in page.body.lower(),
                   f"код {page.status}")
            bad = c.post("/admin/recover", code="XXXXXX-YYYYYY")
            res.ok("неверный код отвергнут",
                   bad.status == 303 and "err=1" in bad.location,
                   f"ответ {bad!r}")
            res.check("после отказа ключ всё ещё не читается",
                      dbkey.state(tmp), dbkey.UNREADABLE)
            ok = c.post("/admin/recover", code=dbkey.format_recovery(key))
            res.ok("верный код принят", ok.status == 200 and "restabil" in ok.body,
                   f"ответ {ok!r}")
            res.check("ключ снова читается на этой машине",
                      dbkey.state(tmp), dbkey.OK)

        with Server(dir_=tmp) as s:          # после перезапуска — обычная работа
            res.check("после перезапуска журнал открывается",
                      Client(s.url).login().get("/admin").status, 200)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 6. выключение шифрования и ежедневные копии ----------

def suite_off_backups(res: Result) -> None:
    """Ветка decrypt обязана зеркалить ветку encrypt: копии data/backups
    переехали под ключ при включении — при выключении обязаны вернуться в
    открытый вид ДО того, как исчезнет db.key. Иначе откат «на вчера» после
    выключения подкладывает зашифрованный файл машине, у которой ключа уже
    нет, — и восстановиться нечем (находка волны 1)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbcrypt_off_"))
    try:
        db = tmp / "dental.db"
        _plain_db(db, rows=3)
        (tmp / "backups").mkdir()
        c1 = tmp / "backups" / "dental_20260101_1.db"
        c2 = tmp / "backups" / "dental_20260102_1.db"
        _plain_db(c1, rows=2)
        _plain_db(c2, rows=1)

        key = dbkey.generate()
        dbkey.request_encrypt(tmp, key)
        res.ok("включение переехало вместе с копиями",
               (dbkey.apply_pending(tmp) or "").startswith("encrypted")
               and MARK.encode() not in c1.read_bytes(),
               "включение не прошло — проверять выключение не на чем")

        dbkey.request_decrypt(tmp)
        res.check("выключение выполнено", dbkey.apply_pending(tmp), "decrypted")
        res.ok("основная база открыта", MARK.encode() in db.read_bytes(),
               "dental.db не расшифровалась")
        for copy in (c1, c2):
            res.ok(f"копия {copy.name} расшифрована",
                   MARK.encode() in copy.read_bytes(),
                   "копия осталась под SQLCipher, а единственный ключ удалён — "
                   "откат на вчера станет «file is not a database»")
        res.ok("ключ удалён после расшифровки всего", not dbkey.enabled(tmp),
               "db.key остался при открытой базе")

        # -- копия, которую расшифровать не вышло: ключ обязан уцелеть --
        dbkey.request_encrypt(tmp, key)
        dbkey.apply_pending(tmp)
        os.chmod(c1, stat.S_IREAD)           # замена файла откажет (Windows)
        try:
            dbkey.request_decrypt(tmp)
            out = dbkey.apply_pending(tmp)
            res.ok("операция не завершена при застрявшей копии",
                   out != "decrypted", f"вернулось {out!r}")
            res.ok("ключ на месте — копию ещё можно спасти",
                   (tmp / dbkey.KEY_FILE).exists(),
                   "db.key удалён, а копия осталась под ключом")
            res.ok("основная база не расшифрована раньше копий",
                   MARK.encode() not in db.read_bytes(),
                   "dental.db открыта, ключ жив — но копии под ключом: "
                   "полудоделанное состояние")
        finally:
            os.chmod(c1, stat.S_IREAD | stat.S_IWRITE)
        dbkey.request_decrypt(tmp)
        res.check("после снятия помехи выключение доводится до конца",
                  dbkey.apply_pending(tmp), "decrypted")
        res.ok("и застрявшая копия расшифрована",
               MARK.encode() in c1.read_bytes(), "копия так и не вернулась")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 7. заказ на шифрование — только после подтверждения листа ----------

def suite_confirm(res: Result) -> None:
    """Включение ТРЕБУЕТ подтверждения, что лист сохранён (докстринг dbkey) —
    значит заказ (pending-файл) имеет право появиться только на галочке
    «Am tipărit foaia». Раньше его создавал сам /crypt/prepare: директор
    закрывал страницу листа, не печатая, а следующий старт молча шифровал
    картотеку — без листа на бумаге это потеря базы при первой смене ПК."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbcrypt_conf_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", tmp / "clinic.json")
        with Server(dir_=tmp) as s:
            c = Client(s.url).login()
            r = c.post("/admin/settings/crypt/prepare")
            res.ok("подготовка ведёт на лист",
                   r.status == 303 and "sheet" in r.location, f"{r!r}")
            res.ok("закрытая страница листа не оставляет заказа",
                   not (tmp / dbkey.PENDING_FILE).exists(),
                   "pending создан ДО подтверждения — следующий старт "
                   "зашифрует без листа на бумаге")
            if not (tmp / dbkey.PENDING_FILE).exists():
                res.ok("лаунчеру нечего применять",
                       dbkey.apply_pending(tmp) is None,
                       "переезд заказан без галочки")

            sheet = c.get("/admin/settings/crypt/sheet")
            res.check("лист открывается", sheet.status, 200)
            m = re.search(r'class="code">([A-Z2-7\-]+)<', sheet.body)
            code = m.group(1) if m else ""
            res.ok("на листе напечатан код", bool(m), "кода нет в разметке")

            c.post("/admin/settings/crypt/confirm", ack="")
            res.ok("без галочки заказа по-прежнему нет",
                   not (tmp / dbkey.PENDING_FILE).exists(),
                   "заказ создан без подтверждения")

            c.post("/admin/settings/crypt/confirm", ack="1")
            res.ok("после подтверждения заказ лежит",
                   (tmp / dbkey.PENDING_FILE).exists(),
                   "галочка не создала заказ — шифрование не включится")
            res.check("заказан ровно тот ключ, что на листе",
                      dbkey.load_pending(tmp), dbkey.parse_recovery(code))

            # повторная подготовка не перевыпускает ключ (находка 08-09)
            c.post("/admin/settings/crypt/prepare")
            sheet2 = c.get("/admin/settings/crypt/sheet")
            res.ok("код на листе не изменился от второго нажатия",
                   code in sheet2.body,
                   "второй ключ поверх — напечатанный лист стал ложным")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 8. экспорт бэкапа при нечитаемом ключе + инструкции про db.key ----

def suite_export_err(res: Result) -> None:
    """Отказ экспорта — баннером, не голым 500; и без незашифрованного снимка
    базы, забытого в %TEMP% (находка волны 2). Заодно: обе инструкции
    восстановления обязаны называть db.key — плоская база из архива на машине
    с включённым шифрованием иначе открывается ключом и выглядит битой."""
    from app.modules.settings import backup as bkp_mod

    res.ok("CITESTE-MA.txt называет db.key", "db.key" in bkp_mod._readme(),
           "восстановление из архива при включённом шифровании даст "
           "«file is not a database» без единой подсказки")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dbcrypt_exp_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", tmp / "clinic.json")
        key = dbkey.generate()
        if not dbkey.store(key, tmp):
            res.failed.append(("ключ не сохранился под DPAPI",
                               "не Windows или DPAPI отказал"))
            return
        with Server(dir_=tmp) as s:
            c = Client(s.url).login()

            faq = c.get("/admin/settings/faq").body
            seg = (faq.split("Cum deschid arhiva", 1)[1].split("<details", 1)[0]
                   if "Cum deschid arhiva" in faq else "")
            res.ok("FAQ про восстановление архива называет db.key",
                   "db.key" in seg,
                   "инструкция молчит про ключ — восстановленная база "
                   "выглядит битой")

            # ключ «унесли» посреди работы (переезд учётки) — база живёт на
            # соединении, открытом при старте, а экспорт читает ключ заново
            (tmp / dbkey.KEY_FILE).write_text("dpapi:мусор", encoding="utf-8")
            troot = pathlib.Path(tempfile.gettempdir())
            before = {p.name for p in troot.glob("dp_backup_*")}
            r = c.post("/admin/backup/export", parola="parola-foarte-buna")
            res.check("отказ показан баннером, а не 500", r.msg, "bad_bkp")
            after = {p.name for p in troot.glob("dp_backup_*")}
            res.ok("снимок базы не остался в %TEMP%", after == before,
                   f"остались: {sorted(after - before)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
