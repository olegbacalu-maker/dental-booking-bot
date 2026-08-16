"""Лаунчер и dental.env: разбор файла клиники, порт, автокопия базы.

dental.env клиника правит Блокнотом — это норма, записанная в самом envfile.py.
Поэтому проверяется не «идеальный» файл, а тот, который реально приезжает:
ANSI с диакритикой, UTF-16, BOM, файл, придержанный антивирусом.

⚠️ Сам bot/desktop.py тестами НЕ импортируется: его тело — это запуск
программы (webview, копирование clinic.json рядом с собой). Проверяемая логика
вынесена в импортируемые модули: envfile.py (разбор файла и порт) и
app/core/autobackup.py (копия базы). Что лаунчер их действительно зовёт,
проверяется ТЕКСТОМ desktop.py — тем же приёмом, каким test_dbcrypt смотрит в
Build-Desktop.ps1.
"""
import codecs
import ctypes
import os
import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import envfile  # noqa: E402

from harness import BOT, Result  # noqa: E402

_GENERIC_READ = 0x80000000
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3


def _hold_no_read(path: pathlib.Path) -> int:
    """Открыть файл так, как его держит антивирус/бэкап-агент: другим можно
    ПИСАТЬ, но не читать. Ровно эта комбинация превращала set_value в
    «прочитать не смог -> записал одну строку» (находка волны 1)."""
    return ctypes.windll.kernel32.CreateFileW(
        str(path), _GENERIC_READ, _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0, None)


# ---------- 1. dental.env: чтение и запись ----------

def suite_envfile(res: Result) -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_env_"))
    try:
        # -- кодировки Блокнота: ANSI, UTF-16, UTF-8 c BOM --
        f = tmp / "ansi.env"
        # cp1251-комментарий «пароль» — не-UTF-8 байты в первой же строке
        f.write_bytes(b"# \xef\xe0\xf0\xee\xeb\xfc\nADMIN_KEY=secret\n"
                      b"DENTART_PORT=9010\n")
        try:
            got, err = envfile.read_all(f), None
        except Exception as e:  # noqa: BLE001 — падение и есть проверяемый дефект
            got, err = {}, e
        res.ok("ANSI-файл из Блокнота читается без падения",
               err is None and got.get("ADMIN_KEY") == "secret",
               f"err={err!r}, got={got}")

        f = tmp / "utf16.env"
        f.write_bytes("# parolă\nADMIN_KEY=secret16\n".encode("utf-16"))
        try:
            got, err = envfile.read_all(f), None
        except Exception as e:  # noqa: BLE001
            got, err = {}, e
        res.ok("UTF-16-файл из Блокнота читается",
               err is None and got.get("ADMIN_KEY") == "secret16",
               f"err={err!r}, got={got}")

        f = tmp / "bom.env"
        f.write_bytes(codecs.BOM_UTF8 + b"TELEGRAM_TOKEN=abc\n")
        got = {}
        try:
            got = envfile.read_all(f)
        except Exception:  # noqa: BLE001
            pass
        res.ok("BOM не въезжает в имя первого ключа",
               got.get("TELEGRAM_TOKEN") == "abc",
               f"ключи: {list(got)}")

        # -- ошибка чтения СУЩЕСТВУЮЩЕГО файла = отказ, а не запись --
        f = tmp / "dental.env"
        body = "# comentariu\nTELEGRAM_TOKEN=tok\nADMIN_KEY=key\nDENTART_PORT=8090\n"
        f.write_text(body, encoding="utf-8")
        h = _hold_no_read(f)
        if h in (0, -1):
            res.ok("файл удалось придержать чужим хэндлом", False,
                   "CreateFileW не дал хэндл — окружение не Windows?")
        else:
            try:
                try:
                    envfile.set_value(f, "TELEGRAM_TOKEN", "nou")
                    raised = None
                except OSError as e:
                    raised = e
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
            res.ok("set_value на нечитаемом файле бросает OSError",
                   isinstance(raised, OSError),
                   "ошибка чтения проглочена — файл будет переписан")
            res.check("файл не тронут: все ключи на месте",
                      f.read_text(encoding="utf-8"), body)

        # -- файл в неопознаваемой кодировке: отказ той же OSError --
        f = tmp / "garbage.env"
        garbage = codecs.BOM_UTF16_LE + b"\x00\xd8"      # одинокий суррогат
        f.write_bytes(garbage)
        try:
            envfile.set_value(f, "X", "1")
            raised = None
        except Exception as e:  # noqa: BLE001
            raised = e
        res.ok("нечитаемая кодировка = OSError, который ловят вызывающие",
               isinstance(raised, OSError),
               f"вылетело {type(raised).__name__ if raised else 'ничего'} — "
               f"настройки ответят голым 500")
        res.check("и файл не переписан", f.read_bytes(), garbage)

        # -- обычная работа не сломана --
        f = tmp / "ok.env"
        f.write_text("# pastreaza-ma\nA=1\nB=2\n", encoding="utf-8")
        envfile.set_value(f, "B", "3")
        envfile.set_value(f, "C", "4")
        lines = f.read_text(encoding="utf-8").splitlines()
        res.check("замена и добавление сохраняют комментарий и порядок",
                  lines, ["# pastreaza-ma", "A=1", "B=3", "C=4"])
        res.ok("временных огрызков после записи нет",
               not list(tmp.glob("*.tmp")),
               f"остались: {[p.name for p in tmp.glob('*.tmp')]}")

        # -- отсутствие файла — законный первый случай --
        f = tmp / "new.env"
        envfile.set_value(f, "A", "1")
        res.check("новый файл создаётся", envfile.read_all(f), {"A": "1"})

        # ⭐ Обрыв питания посреди записи не проверить убийством процесса —
        # смотрим в сам приём, как test_dbcrypt смотрит в Build-Desktop.ps1:
        # запись обязана идти во временный файл с fsync и вставать на место
        # атомарным os.replace (тот же приём, что в dbkey.store).
        src = (BOT / "app" / "envfile.py").read_text(encoding="utf-8")
        res.ok("запись dental.env атомарная (tmp + fsync + os.replace)",
               "os.replace" in src and "fsync" in src,
               "truncate+write: обрыв питания оставляет усечённый dental.env")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 2. DENTART_PORT ----------

def suite_port(res: Result) -> None:
    """Порт правит сама клиника (диалог «портул e ocupat» это прямо советует),
    поэтому мусор в нём — ожидаемый ввод: раньше int() падал на верхнем уровне
    модуля, до excepthook и до любого окна, и ярлык «не делал ничего»."""
    parse = getattr(envfile, "parse_port", None)
    if parse is None:
        res.ok("envfile.parse_port существует", False,
               "валидации порта нет — лаунчер умирает на int() без окна")
        return
    res.check("обычный порт", parse("8088"), 8088)
    res.check("порт с пробелами по краям", parse(" 8099 "), 8099)
    for label, bad in (("пустое значение", ""), ("None", None),
                      ("кириллическая О", "8О88"), ("пробел внутри", "80 88"),
                      ("не число", "abc"), ("ноль", "0"),
                      ("за пределом", "65536"), ("минус", "-1"),
                      ("восточные цифры", "٨٠٨٨")):
        res.ok(f"отвергнуто: {label}", parse(bad) is None,
               f"parse_port({bad!r}) = {parse(bad)!r}")

    desk = (BOT / "desktop.py").read_text(encoding="utf-8")
    res.ok("лаунчер берёт порт через parse_port", "parse_port" in desk,
           "голый int(DENTART_PORT) упадёт до excepthook — ярлык молча мёртв")
    res.ok("голого int() вокруг DENTART_PORT больше нет",
           'int(os.environ.get("DENTART_PORT"' not in desk,
           "опечатка клиники в dental.env валит запуск без окна")
    # env читается ДО подмены stderr — падение на нём умирало без следа.
    # Порядок в файле: настройка лога обязана стоять выше первого read_all.
    res.ok("лог и stderr настраиваются раньше чтения dental.env",
           desk.find("logging.basicConfig") < desk.find("envfile.read_all"),
           "разбор dental.env идёт до подмены stderr — краш без следа в логе")


# ---------- 3. автокопия базы при старте ----------

def suite_autobackup(res: Result) -> None:
    try:
        from app.core import autobackup
    except ImportError as e:
        res.ok("модуль автокопии импортируется", False,
               f"логика живёт только в desktop.py и тестом недостижима: {e!r}")
        return

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_ab_"))
    try:
        src = tmp / "dental.db"
        con = sqlite3.connect(str(src))
        con.execute("CREATE TABLE patients(id INTEGER PRIMARY KEY, name TEXT)")
        con.executemany("INSERT INTO patients(name) VALUES (?)",
                        [("Ionescu",), ("Popescu",), ("Rusu",)])
        con.commit()
        con.close()

        made = autobackup.make_backup(tmp)
        res.ok("копия создана", made is not None and made.exists(),
               f"вернулось {made!r}")
        res.ok("копия лежит в data/backups по маске dental_*.db",
               made is not None and made.parent == tmp / "backups"
               and made.match("dental_*.db"), f"путь {made!r}")
        if made is not None and made.exists():
            con = sqlite3.connect(str(made))
            got = con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
            con.close()
            res.check("в копии все строки", got, 3)
        res.ok("временных огрызков после успеха нет",
               not list((tmp / "backups").glob("*.tmp")),
               "остался .tmp — при следующем сбое он собьёт с толку")

        # -- сбой посреди копирования: битый файл НЕ выдаёт себя за бэкап --
        bad_dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_ab_bad_"))
        try:
            (bad_dir / "dental.db").write_bytes(
                b"SQLite format 3\x00" + b"\x07" * 200)
            try:
                autobackup.make_backup(bad_dir)
                failed = False
            except Exception:  # noqa: BLE001 — сбой и должен быть громким
                failed = True
            res.ok("сбой копирования виден исключением", failed,
                   "битый источник скопировался «успешно»")
            leftovers = list((bad_dir / "backups").glob("dental_*.db"))
            res.ok("после сбоя файла-обманки нет", not leftovers,
                   f"битый {[p.name for p in leftovers]} неотличим от бэкапа "
                   f"и вытеснит исправные копии из ротации")
        finally:
            import shutil
            shutil.rmtree(bad_dir, ignore_errors=True)

        # -- ротация видит только финальные имена --
        for i in range(20):
            (tmp / "backups" / f"dental_20250101_0000{i:02d}_1.db").write_bytes(
                b"vechi")
        autobackup.make_backup(tmp)
        left = sorted((tmp / "backups").glob("dental_*.db"))
        res.check("ротация держит ровно 14 копий", len(left), 14)

        desk = (BOT / "desktop.py").read_text(encoding="utf-8")
        res.ok("лаунчер делает копию через autobackup", "autobackup" in desk,
               "desktop.py копирует сам — логика раздвоится и уйдёт из-под тестов")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
