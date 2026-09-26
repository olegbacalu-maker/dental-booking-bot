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
import ast
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

    # ⛔ Кодировка лога. Без явной `encoding` FileHandler открывает файл в ANSI
    # МАШИНЫ, а у клиники Windows румынская: cp1250, кириллицы нет. Русское
    # сообщение там не искажается — `logging` ВЫБРАСЫВАЕТ запись целиком, и в
    # файле её нет вовсе. В продукте 40 русских сообщений, включая диагностику
    # неудавшейся миграции индексов.
    # ⚠️ На машине разработчика дефект НЕВИДИМ: здесь ANSI это cp1251.
    # ⚠️ Скобку ищем СЧЁТОМ, а не первым `)`: внутри вызова стоит
    # `str(data_dir / "dentpilot.log")`, и наивная нарезка обрывала бы вызов
    # раньше аргумента, который проверяем. Первая версия этого правила так и
    # сделала — покраснела на ПРАВИЛЬНОМ коде.
    head = desk.find("logging.basicConfig(")
    i, depth = head + len("logging.basicConfig("), 1
    while i < len(desk) and depth:
        depth += {"(": 1, ")": -1}.get(desk[i], 0)
        i += 1
    cfg = desk[head:i]
    res.ok("лог пишется в utf-8, а не в ANSI машины",
           'encoding="utf-8"' in cfg,
           "без encoding= русские строки лога у румынской клиники пропадают "
           "молча — а читают их ровно тогда, когда что-то сломалось")

    # ⛔ P2, шаги 1–3. Находка корня обязана случиться ДО того, как лаунчер
    # объявит корень приложению и создаст в нём папку данных: спросишь позже —
    # журнал назначения уже заведён, и всякий ответ превращается в «картотека
    # в обоих корнях», то есть в раздвоение, созданное самой проверкой.
    # ⛔ Ищем САМО ПРИСВАИВАНИЕ, а не имя модуля: голое `relocate` стоит в
    # комментарии рядом, и правило позеленело бы, не проверив ничего (на этом
    # уже наступали дважды за один день).
    call = desk.find("relocate.root_for(")
    res.ok("лаунчер спрашивает находку корня", call > 0,
           "root_for исчез — обновление на месте снова заведёт пустой журнал "
           "рядом с настоящей картотекой")
    res.ok("и спрашивает ДО объявления корня приложению",
           0 < call < desk.find('os.environ["DENTART_DATA_DIR"] = str(ROOT)'),
           "корень объявлен раньше находки — приложение получит не тот путь")
    res.ok("и ДО создания папки данных",
           0 < call < desk.find("data_dir.mkdir("),
           "папка назначения создана раньше находки — раздвоение делает сама "
           "проверка")

    # ⛔ Вердикт доезжает до приложения переменной окружения, и у этой переменной
    # есть дыра подделки: ниже окружение пополняется ВСЕМИ ключами `dental.env`
    # подряд, а сам файл лежит В КОРНЕ и правится клиникой. Строка
    # `DENTART_SPLIT_SOURCE=...` в нём нарисовала бы экран раздвоения на здоровой
    # машине — при чистом логе, верной раскладке и без единого признака подвоха.
    # Значит переменная обязана ставиться И СНИМАТЬСЯ жёстко, обеими ветками, и
    # обе правки — ВЫШЕ слияния. «В нормальной ветке не трогаем» и есть дыра.
    # ⚠️ Прогон этого не видит никогда: харнесс `desktop.py` не исполняет.
    # ⛔ Ищем САМИ ОПЕРАЦИИ, а не имя переменной: голое имя стоит в комментарии
    # рядом, и правило позеленело бы, не проверив ничего.
    # ⛔ P4.1. Привилегированный запуск обязан отработать ПЕРВЫМ и выйти. Ниже
    # начинаются побочные действия, и процесс под администратором не должен ни
    # создавать папку клиники (она досталась бы админу, и обычный запуск
    # потерял бы к ней доступ), ни поднимать сервер.
    # ⚠️ Прогон этого не видит: харнесс поднимает `app.main` напрямую и
    # `desktop.py` не исполняет ни строкой.
    # ⚠️ Ищем ВЫЗОВ, а не строку целиком: дописанный аргумент (резолвер
    # раскладки) уже однажды сделал этот сторож красным на исправном коде.
    priv = desk.find("privileged.handle_argv(")
    res.ok("лаунчер спрашивает привилегированный запуск", priv > 0,
           "вызова нет — операция за UAC никогда не исполнится")
    res.ok("и спрашивает ДО вычисления корня",
           0 < priv < desk.find("ROOT = data_root()"),
           "корень считается раньше — привилегированный процесс уже потрогал "
           "раскладку клиники")
    res.ok("и ДО создания папки данных",
           0 < priv < desk.find("data_dir.mkdir("),
           "папку клиники создаст процесс администратора — обычный запуск "
           "потеряет к ней доступ")

    set_at = desk.find("os.environ[relocate.SPLIT_ENV] = str(")
    pop_at = desk.find("os.environ.pop(relocate.SPLIT_ENV, None)")
    merge = desk.find("envfile.read_all(env_path)")
    res.ok("вердикт объявляется приложению", set_at > 0,
           "экран раздвоения не откроется: приложение о находке не узнает")
    res.ok("и СНИМАЕТСЯ во всех прочих ветках", pop_at > 0,
           "переменная только ставится — строка в dental.env нарисует "
           "раздвоение на здоровой машине")
    res.ok("слияние dental.env на месте", merge > 0,
           "точка слияния переехала — правило ниже проверяет несуществующее")
    res.ok("обе правки ВЫШЕ слияния dental.env",
           0 < set_at < merge and 0 < pop_at < merge,
           f"set={set_at}, pop={pop_at}, слияние={merge} — клиника сможет "
           "подделать вердикт строкой в своём же файле")

    # ⛔ Стенды, которые запускают СОБРАННЫЙ exe, обязаны назвать себя корнем
    # данных. До P1 папку данных давало место exe, и лаборатория получала её
    # даром; теперь лаунчер спрашивает $DENTART_DATA_DIR и, не найдя, уходит в
    # %ProgramData% — то есть в НАСТОЯЩУЮ картотеку машины. Стенд при этом не
    # падает: он молча проверяет не тот экземпляр и пишет не в ту папку.
    # ⚠️ Прогон этого не видит НИКОГДА: харнесс поднимает app.main напрямую и
    # desktop.py не исполняет ни строкой (прайор карты). Поэтому правило здесь.
    # ⛔ Ищем САМО ПРИСВАИВАНИЕ, а не имя переменной. Голое имя находится в
    # комментарии рядом, и правило зеленеет, не проверив ничего: наступлено
    # дважды за один день — сперва на `envfile.read_all` строкой выше, потом
    # на этом же правиле. Текстовый сторож обязан искать то, что СЛОМАЕТСЯ
    # при удалении кода, а не то, что объясняет код.
    BENCHES = {"Build-Installer.ps1": "$env:DENTART_DATA_DIR = $lab",
               "scripts/check_slot_guard.py": '"DENTART_DATA_DIR": str(lab)',
               "scripts/smoke_build.py": '"DENTART_DATA_DIR": str(lab)',
               # ⚠️ У этого стенда назначение и есть изолируемая папка: он
               # проверяет, что программа туда НЕ пошла. Поэтому имя другое.
               "scripts/check_relocate_live.py": '"DENTART_DATA_DIR": str(anchor)',
               # ⚠️ И у этого назначение — изолируемая папка: он проверяет, что
               # подтверждение в неё почти ничего не пишет.
               "scripts/check_split_live.py": '"DENTART_DATA_DIR": str(anchor)'}
    for rel, want in BENCHES.items():
        f = BOT.parent / rel
        # сторож за сторожом: переименуют файл — правило обязано упасть, а не
        # позеленеть на пустом месте
        if not res.ok(f"стенд {rel} на месте", f.exists(),
                      "файл переехал — правило ниже проверяет несуществующее"):
            continue
        res.ok(f"стенд {rel} назначает себя корнем данных",
               want in f.read_text(encoding="utf-8", errors="replace"),
               f"нет строки {want!r} — лаборатория запустит exe поверх "
               "настоящей картотеки машины")

    # ⛔ (09-26) И TEMP программы — внутри лаборатории. Стенд гасит exe через
    # taskkill /F, а загрузчик onefile убирает свою распаковку (_MEI*, 52 МБ)
    # только при штатном выходе: каждая сборка оставляла в %TEMP% три такие
    # папки, 25.09 — 1.2 ГБ за день на диске C в 100 ГБ. Список ОБЯЗАН совпадать
    # с BENCHES: новый стенд без этой строки снова течёт молча.
    TEMP_IN_LAB = {"Build-Installer.ps1": "$env:TEMP = $tmp",
                   "scripts/check_slot_guard.py": '"TEMP": str(tmp)',
                   "scripts/smoke_build.py": '"TEMP": str(tmp)',
                   "scripts/check_relocate_live.py": '"TEMP": str(tmp)',
                   "scripts/check_split_live.py": '"TEMP": str(tmp)'}
    res.ok("у каждого стенда есть правило про TEMP", set(TEMP_IN_LAB) == set(BENCHES),
           f"списки разошлись: {sorted(set(TEMP_IN_LAB) ^ set(BENCHES))}")
    for rel, want in TEMP_IN_LAB.items():
        f = BOT.parent / rel
        if f.exists():
            res.ok(f"стенд {rel} распаковывает exe внутри лаборатории",
                   want in f.read_text(encoding="utf-8", errors="replace"),
                   f"нет строки {want!r} — после taskkill в %TEMP% останется "
                   "распаковка _MEI* на 52 МБ")

    # ⭐ И обратная сторона, без которой список выше — как раз тот гниющий
    # список-включатель из прайора карты: он проверяет ровно тех, кого в нём
    # назвали, и НОВЫЙ стенд проходит мимо молча. Поэтому ищем нарушителей:
    # всякий, кто ЗАПУСКАЕТ собранный exe и в списке не значится.
    # ⚠️ Правило намеренно чуть жадное. Ложное срабатывание здесь — громкий
    # вопрос человеку («это стенд? изолируй или впиши с причиной»), а пропуск
    # — тихий запуск поверх настоящей картотеки клиники.
    root = BOT.parent
    # ⚠️ Файл самого правила исключён: в нём написаны искомые литералы, и без
    # этого он ловит сам себя. Единственное исключение, и оно самоочевидно —
    # сторож ничего не запускает.
    skip = set(BENCHES) | {"tests/test_launcher.py"}
    cand = [p for p in list(root.glob("*.ps1")) + list((root / "scripts").glob("*.py"))
            + list((root / "tests").glob("*.py"))
            if str(p.relative_to(root)).replace("\\", "/") not in skip]
    rogue = []
    for p in cand:
        txt = p.read_text(encoding="utf-8", errors="replace")
        if "DentPilot.exe" not in txt:
            continue
        if any(s in txt for s in ("Start-Process", "subprocess.Popen(", "os.startfile(")):
            rogue.append(str(p.relative_to(root)).replace("\\", "/"))
    res.ok("собранный exe запускают только известные стенды", not rogue,
           "стенд вне списка — изолируй ему DENTART_DATA_DIR или впиши "
           "в BENCHES с причиной: " + ", ".join(rogue))

    # ⛔ Сборка обязана ЗАПУСКАТЬ то, что собрала. До 21.09 `Build-Desktop.ps1`
    # кончалась строкой «OK: dist\DentPilot.exe (33.3 MB)», и означала она ровно
    # одно: файл существует. Правка лаунчера, верная в исходниках, в бинарнике
    # может не исполниться — между правилом и поведением стоят PyInstaller,
    # планировщик и файловая система, и за один день там нашлись три дефекта
    # подряд. ⚠️ Прогон этого не заменяет НИКОГДА: харнесс поднимает app.main
    # напрямую и desktop.py не исполняет ни строкой (прайор карты).
    # ⚠️ Сторож за сторожом: проверяем и то, что оба стенда на месте. Иначе
    # переименование файла оставит правило искать несуществующее имя, оно
    # найдёт ноль нарушителей и позеленеет навсегда — та самая полярность
    # списка-включателя из прайора карты.
    build = root / "Build-Desktop.ps1"
    if res.ok("Build-Desktop.ps1 на месте", build.exists(),
              "сборки нет — правило ниже проверяет несуществующий файл"):
        txt = build.read_text(encoding="utf-8", errors="replace")
        for rel in ("scripts/smoke_build.py", "scripts/check_relocate_live.py"):
            name = rel.split("/")[1]
            res.ok(f"стенд {rel} существует", (root / rel).exists(),
                   "стенд переехал — строка ниже ищет несуществующее имя")
            res.ok(f"сборка зовёт {rel}", name in txt,
                   f"{name} выпал из Build-Desktop.ps1 — «сборка зелёная» "
                   "снова означает только «файл существует»")
        # ⛔ И код возврата обязан быть ПРОЧИТАН. Вызов без проверки хуже, чем
        # отсутствие вызова: красный стенд напечатает жалобу в середину вывода,
        # сборка объявит OK, и человек поверит второму.
        # ⚠️ Окно — 400 символов ПОСЛЕ вызова, и это не придирка к форматированию.
        # В файле уже несколько таких проверок (npm, sync_version, PyInstaller):
        # поиск «где-нибудь в файле» зеленел бы на любой чужой, то есть не
        # проверял бы ничего. ⛔ Поэтому окно не расширять, чтобы «не мешало»:
        # расширенное до размера файла, оно делает правило зелёным навсегда.
        # Мешает оно ровно тогда, когда между вызовом и проверкой вклинилось
        # что-то, чего там быть не должно.
        for rel in ("scripts/smoke_build.py", "scripts/check_relocate_live.py"):
            name = rel.split("/")[1]
            i = txt.find(name)
            res.ok(f"и читает код возврата {rel}",
                   i >= 0 and "$LASTEXITCODE -ne 0" in txt[i:i + 400],
                   "вызов есть, а проверки нет — красный стенд не остановит "
                   "сборку, и она объявит OK")

    # ⛔ Канал засевается при ПЕРВОМ создании dental.env, а не сверяется на
    # каждом старте. Разница не косметическая: сверка на каждом старте отняла
    # бы у клиники возможность переключить канал руками и завела бы файлу
    # ВТОРОГО писателя. Проверяем разбором, а не текстом: запись обязана
    # стоять ВНУТРИ ветки «файла ещё нет».
    tree = ast.parse(desk)
    guarded, total = 0, 0
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "write_text"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "env_path"):
            continue
        total += 1
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        src = ast.dump(n.test)
        if "env_path" not in src or "exists" not in src or "Not" not in src:
            continue
        for m in ast.walk(n):
            if (isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute)
                    and m.func.attr == "write_text"
                    and isinstance(m.func.value, ast.Name)
                    and m.func.value.id == "env_path"):
                guarded += 1
    res.ok("dental.env пишется только при ПЕРВОМ создании",
           total > 0 and guarded == total,
           f"записей всего {total}, под охраной «файла ещё нет» — {guarded}")
    res.ok("канал берётся из install.json одной функцией",
           "install_info.channel_line(" in desk,
           "засев переписан на месте — знание о канале раздвоилось")


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
