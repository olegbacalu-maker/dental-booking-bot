"""Операции, которым нужны права администратора. Закрытый список, не запуск.

P4.1. Установщик с P1 работает от админа, поэтому запись «Программ и
компонентов» лежит в `HKLM`, а программа идёт БЕЗ повышения. Проверено на
машине: обычному процессу `HKLM\\...\\Uninstall` открыт на чтение, а создание
подключа и запись значений — «Отказано в доступе» (5). Прежний код ловил
`OSError` и молча сдавался: версия в «Программах и компонентах» оставалась той,
с которой клинику давно сняли, — а это единственное место, где её видно НЕ
открывая программу, и по телефону спрашивают именно там.

⛔ **Это НЕ «выполнить команду от администратора».** Так уже сделано у правила
брандмауэра (`settings/lan.py`): собирается командная строка `cmd.exe` и
целиком уходит под UAC. Сегодня безопасно — все куски свои, — но форма такова,
что первая же подстановка чужой строки станет запуском произвольной команды с
правами администратора. Здесь форма другая и расширять её нельзя:

  * исполняемый файл — ТОЛЬКО наш собственный `sys.executable`;
  * операция — имя из ЗАКРЫТОГО словаря `OPS`, а не путь и не команда;
  * аргументы проверяет САМА операция, и проверяет до всякого действия;
  * никакой оболочки: ни `cmd.exe`, ни `shell=True`, ни склейки строк.

⚠️ Проверять аргументы обязан ТОТ, КТО ИХ ИСПОЛНЯЕТ, а не тот, кто просит.
Просящий работает без повышения, и его проверку обойти ничего не стоит: чужой
процесс на той же машине может позвать `DentPilot.exe --privileged …` сам.
Единственная проверка, которая чего-то стоит, стоит ЗА UAC.

⛔ Ничего «на будущее» здесь не заводить. Новая операция = новая строка в `OPS`
плюс её собственная проверка аргументов плюс отрицательный тест.

⚠️ **Одно исключение из «здесь ничего не исполняется» — `install-setup`** (03.10,
docs/dentpilot-2/updates.md › «Порядок с 03.10», шаг 2): установщик программы
ЗАПУСКАЕТСЯ отсюда, потому что ставить в `Program Files` больше некому. Держится
исключение не на доверии к просящему, а на трёх проверках ЗА UAC, и все — над
КОПИЕЙ в папке программы, куда обычной учётке писать нельзя (исходник лежит в
папке клиники и мог смениться после проверки): sha256 и размер из описания,
подпись Authenticode именно нашим сертификатом (закрытый список `SIGNERS`, а не
«любая действительная подпись» — её купит кто угодно) и версия файла новее
стоящей программы (иначе настоящий старый установщик откатил бы программу назад
поверх уже мигрированной базы). Запускается установщик ОТДЕЛЬНО, и операция
сразу выходит: ждать она не может — установщик заменяет файлы программы, а этот
процесс и есть программа.

⚠️ Предзагрузочный слой: из проекта не импортируется ничего. Модуль зовёт
`desktop.py` первой же строкой, до того как приложение существует, — иначе
привилегированный запуск поднял бы ещё и сервер.
"""
from __future__ import annotations

import re
import shutil
import sys
import time

# Метка привилегированного запуска. Своя, а не позиционная: случайный аргумент
# (путь к файлу из «Открыть с помощью») не должен попадать в эту ветку.
FLAG = "--privileged"

# Ключ записи установщика. GUID из `installer/DentPilot.iss` (AppId), Inno
# дописывает `_is1`. ⛔ Ключ СОЗДАЁТ установщик; мы его только правим и никогда
# не создаём: установка копированием exe в реестре не числится, и выдумывать её
# нельзя — в «Программах и компонентах» появился бы пункт, который ничего не
# удаляет.
UNINST_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
              r"\{B8836ACC-EA41-4B1C-9FEB-DC61ADD35754}_is1")

# Ровно три числа. ⛔ Не «любая строка»: значение уходит в реестр машины, и
# `..\..` или перевод строки там не нужны никому.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class Refused(Exception):
    """Операция отклонена ДО всякого действия: имя не из списка или аргумент
    не прошёл проверку. Отдельный тип, чтобы отказ не путался со сбоем."""


def _set_uninstall_version(args: list[str], data_root=None, base=None) -> str:
    """`DisplayVersion` (и версия внутри `DisplayName`) в записи установщика.

    ⚠️ Ключ не создаётся никогда: нет записи — нечего и править, это установка
    копированием. Возвращаем словами, что произошло; печатает их вызывающий.
    """
    if len(args) != 1 or not VERSION_RE.match(args[0]):
        raise Refused(f"версия должна быть ровно тремя числами, получено {args!r}")
    version = args[0]
    import winreg

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, UNINST_KEY, 0,
                                winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                cur = str(winreg.QueryValueEx(k, "DisplayVersion")[0])
                if cur == version:
                    return f"уже {version}"
                winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
                try:
                    name = str(winreg.QueryValueEx(k, "DisplayName")[0])
                    if cur and cur in name:
                        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ,
                                          name.replace(cur, version))
                except OSError:
                    pass
                return f"{cur} -> {version}"
        except FileNotFoundError:
            continue
    return "записи установщика нет — править нечего"


# Имена в рабочей папке обновления. ⛔ Их знают ОБЕ стороны и ни одна не
# передаёт другой путь: просящий кладёт файлы по этим именам, исполнитель по
# ним же их и ищет. Путь в аргументах был бы ровно той дырой, ради которой
# список операций и закрыт.
WORK_SUBDIR = "updates"
REQUEST_NAME = "install.request"
RESULT_NAME = "install.result"

# Сколько может весить установщик. Нижняя граница — от оборванной закачки
# (urllib не считает обрыв ошибкой), верхняя — чтобы не класть в Program Files
# что попало.
MIN_EXE, MAX_EXE = 5_000_000, 300_000_000


def _self_exe() -> "pathlib.Path":
    """Свой файл — по нему `_layout` узнаёт раскладку программы. ⭐ Своя
    функция, а не выражение по месту: это ШОВ для проверок — иначе набор
    рассуждал бы о python.exe, которым сам и запущен.
    ⛔ Значение берётся у процесса, а НЕ из аргументов: снаружи назвать
    программу нельзя ничем."""
    import pathlib
    return pathlib.Path(sys.executable).resolve()


def _layout(base=None) -> tuple:
    """(корень программы, файл программы, это ли движок Tauri) — Т10, 18.10.

    ⭐ За UAC с 18.10 бывает движок оболочки: `engine\\DentPilot-Engine.exe`.
    Программа у него — папка, корень — папка оболочки `DentPilot.exe` (родитель
    `engine\\`, контракт § 1), и всё «рядом с программой» (копия установщика,
    версия стоящей программы) живёт там, а не в `engine\\`: папку движка
    мастер переписывает целиком. Корень передаёт ЛАУНЧЕР (`desktop.BASE`) — он
    один знает раскладку; без него (прогон) — то же правило по имени exe.
    ⛔ Опознаётся ПО ИМЕНИ своего файла, а не окружением: повышенный процесс
    окружения оболочки не получает."""
    import pathlib

    from .sidecar import ENGINE_EXE            # константа предзагрузочного слоя
    exe = _self_exe()
    engine = exe.name.lower() == ENGINE_EXE.lower()
    if base is not None:
        root = pathlib.Path(base)
    else:
        root = exe.parent.parent if engine else exe.parent
    return root, (root / "DentPilot.exe" if engine else exe), engine


# ---------- обновление установщиком (03.10) ----------

# Имена (как у описания и итога выше): обе стороны их знают, путей никто не передаёт.
SETUP_NEW = "DentPilot-Setup.new.exe"     # в папке клиники: кладёт обычный процесс
SETUP_DIR = "updates"                     # в папке программы: пишет только администратор
SETUP_NAME = "DentPilot-Setup.exe"
SETUP_LOG = "setup.log"
SETUP_LOG_PREV = "setup.prev.log"         # журнал прошлой попытки: /LOG= перезаписывает
STARTED = "started"                       # итог «мастер УЖЕ запущен»: программа гасит себя сама
# Как запускается мастер: отдельно, без консоли — и ВНЕ «задания» оболочки
# (`_spawn_setup`). Числа из WinBase.h: в `subprocess` их нет.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
# Чьей подписи верить. ⛔ Закрытый список ОТПЕЧАТКОВ: действительную подпись
# Authenticode купит кто угодно, и «подписан» значило бы «подписан кем-то».
# Сертификат Certum на Oleg Bacalu действует до 29.09.2027 (code-signing-wired).
# ⚠️ ПЕРЕД продлением — выпуск с ДВУМЯ отпечатками, старым и новым: программа,
# знающая только старый, отвергнет установщик с новым, и обновить её можно будет
# лишь установкой руками или выездом.
SIGNERS = frozenset({"07D3BC7B7B63F6F0A54553034A2E27019D3A9C2C"})
# Тихая установка поверх: без окон и вопросов, без перезагрузки; программу
# установщик закроет сам (Restart Manager), если она ещё открыта.
SETUP_FLAGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
               "/FORCECLOSEAPPLICATIONS", "/SP-")


def _current_version(exe) -> tuple | None:
    """Версия стоящей программы — из свойств её файла. Шов для проверок: из
    исходников `sys.executable` — это python.exe со своей версией."""
    from . import authenticode
    return authenticode.file_version(exe)


def _spawn_setup(setup, result, log) -> None:
    """Запустить установщик ОТДЕЛЬНО и не ждать. Шов для проверок: настоящий
    установщик в прогоне не запустить. ⛔ Без оболочки: список аргументов, и
    первый — наша проверенная копия. Итог пишет сам установщик в `result`.

    ⛔ `CREATE_BREAKAWAY_FROM_JOB` (18.10, живой проход 2.0.0 → 2.0.1 встал):
    этот процесс служба UAC создаёт «от имени» движка, и он наследует его
    «задание» — у оболочки Tauri это KILL_ON_JOB_CLOSE. Всё, что запущено
    отсюда без просьбы о выходе, остаётся внутри и гибнет, когда оболочка
    закрывается по «started». Оболочка выход разрешает (`engine.rs::JOB_LIMITS`,
    BREAKAWAY_OK); задание, которое не разрешает, отвечает отказом (`OSError`),
    и это правильно — мастер внутри него погиб бы на середине. Вне задания
    (окно pywebview) флаг ничего не меняет."""
    import subprocess
    subprocess.Popen([str(setup), *SETUP_FLAGS, f"/LOG={log}", f"/RESULT={result}"],
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                     | CREATE_BREAKAWAY_FROM_JOB,
                     close_fds=True)


def _install_setup(args: list[str], data_root=None, base=None) -> str:
    """Поставить новую версию подписанным установщиком. ⛔ Ни одного аргумента.

    Источник — условленное имя в папке клиники, назначение копии — папка
    программы (`SETUP_DIR` в её корне); оба исполнитель вычисляет сам.
    Порядок: копия (исходник убран) → проверки копии → установщик отдельно,
    вне задания оболочки → итог «started». Дальше итог («ok»/«fail») пишет
    установщик, а перезапуск делает задача планировщика от обычного пользователя,
    заведённая программой ДО запроса прав.
    ⛔ «started» — ПОСЛЕДНЕЕ действие (18.10): по нему оболочка закрывается, а
    этот процесс живёт в её задании, и всё, что стоит после записи, может не
    исполниться никогда. 2.0.0/2.0.1 писали «started» и спали 3 с до запуска —
    и гибли во сне. Ждать выхода программы — дело мастера: тихое обновление
    ждёт оба exe по пути до 30 с (Т9, `WaitAppExit` в DentPilot.iss).
    ⚠️ У движка Tauri (Т10) корень — папка оболочки, а не `engine\\`
    (`_layout`): копия мастера в `engine\\updates` лежала бы в папке, которую
    сам мастер переписывает, и стоящую версию надо спрашивать у `DentPilot.exe`
    — это и есть программа, которую видит клиника.
    """
    if args:
        raise Refused(f"операция не принимает аргументов, получено {args!r}")
    import hashlib
    import json
    import pathlib
    from . import authenticode

    prog_root, exe, _engine = _layout(base)
    root = data_root() if callable(data_root) else data_root
    if root is None:
        raise Refused("папка клиники не найдена — источник обновления неизвестен")
    work = pathlib.Path(root) / WORK_SUBDIR
    src = work / SETUP_NEW
    result = work / RESULT_NAME

    def done(text: str) -> str:
        try:
            result.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return text

    if not src.exists():
        return done("нет установщика")
    try:
        want = json.loads((work / REQUEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return done("нет описания обновления")
    # ⛔ Дальше — только КОПИЯ: исходник в папке клиники мог смениться после проверки
    dst = prog_root / SETUP_DIR / SETUP_NAME
    try:
        dst.parent.mkdir(exist_ok=True)
        dst.unlink(missing_ok=True)
        shutil.copyfile(src, dst)
    except OSError as e:
        return done(f"установщик не скопирован: {e}")
    # Исходник больше не нужен: всё дальше — над копией. Не убрать его здесь —
    # 38 МБ в папке клиники до следующего обновления: при «started» программа
    # гасится и прибрать за собой уже не может (канарейка 03.10).
    try:
        src.unlink()
    except OSError:
        pass
    size = dst.stat().st_size
    if not MIN_EXE <= size <= MAX_EXE:
        return done(f"размер не годится: {size}")
    with open(dst, "rb") as f:
        if f.read(2) != b"MZ":
            return done("это не программа Windows")
    if str(want.get("size")) != str(size):
        return done("размер разошёлся с описанием")
    h = hashlib.sha256()
    with open(dst, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != str(want.get("sha256", "")).lower():
        return done("отпечаток разошёлся с описанием")
    signer = authenticode.signer_thumbprint(dst)
    if signer not in SIGNERS:
        return done("установщик подписан не DentPilot" if signer
                    else "у установщика нет действительной подписи")
    new = authenticode.file_version(dst)
    cur = _current_version(exe)
    if new is None or (cur is not None and tuple(new[:3]) <= tuple(cur[:3])):
        return done("установщик не новее стоящей программы")
    # Журнал прошлой попытки — в сторону, а не под новый: /LOG= установщика
    # перезаписывает файл, и при «встало со второго раза» (канарейка 1.41.2,
    # 12.10) журнал первой, неудачной, пропал — причину пришлось искать в
    # журнале событий Windows.
    try:
        if (work / SETUP_LOG).exists():
            (work / SETUP_LOG).replace(work / SETUP_LOG_PREV)
        result.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        _spawn_setup(dst, result, work / SETUP_LOG)
    except OSError as e:
        # Программа ещё жива — она ждёт «started» — и уберёт за собой сама
        # («cancelled» сторожу). Поэтому отказ словами, как у проверок выше, а
        # НЕ «fail»: «fail» сторож понял бы как «запускай» при живой программе.
        return done(f"установщик не запустился: {e}")
    try:
        # «x»: мастер мог успеть написать свой итог раньше — его слово главнее
        with open(result, "x", encoding="utf-8") as f:
            f.write(STARTED)
    except FileExistsError:
        try:
            return result.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    except OSError:
        pass
    return STARTED


# --- новый PIN поверх исчезнувшего auth.json (17.10, посторонний разбор) ---
# «Забыл PIN» у поддержки = удалить data\auth.json → экран первой установки.
# Тем же путём чужая учётка Windows на компьютере клиники (папка данных общая
# для всех учёток НАМЕРЕННО — вторая смена; права на файлы не сузить, их пишет
# сама программа от обычной учётки) делала себя единственным директором.
# Теперь, если база помнит отпечаток файла, новый первый PIN ставится только
# с подтверждением администратора Windows: эта операция кладёт метку времени
# в HKLM (неадмину туда не записать), экран установки принимает её 15 минут и
# один раз (`core/auth.reset_grant`). Аргументов нет — проверять нечего.
# ⚠️ Из исходников (прогон, песочница) и пишется, и читается HKCU: у прогона
# нет повышения. У собранной программы HKCU не читается — иначе любая учётка
# выписала бы разрешение себе сама.
RESET_KEY = r"Software\DentPilot"
RESET_VALUE = "AuthResetAt"
RESET_BY = "AuthResetBy"        # учётка Windows, подтвердившая, — для ленты
RESET_WINDOW = 15 * 60


def _reset_hive():
    import winreg
    return (winreg.HKEY_LOCAL_MACHINE if getattr(sys, "frozen", False)
            else winreg.HKEY_CURRENT_USER)


def _auth_reset(args: list[str], data_root=None, base=None) -> str:
    if args:
        raise Refused(f"у операции нет аргументов, получено {args!r}")
    import getpass
    import winreg
    with winreg.CreateKeyEx(_reset_hive(), RESET_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, RESET_VALUE, 0, winreg.REG_SZ, str(int(time.time())))
        # кто подтвердил: процесс идёт от учётки, назвавшей себя в UAC
        winreg.SetValueEx(k, RESET_BY, 0, winreg.REG_SZ, getpass.getuser()[:64])
    return "un PIN nou se poate seta în următoarele 15 minute"


def auth_reset_mark() -> tuple[str, str]:
    """(метка времени как записана, учётка подтвердившего); ('', '') — нет.
    Срок и однократность судит `core/auth.reset_grant`; здесь только чтение
    — и только из улья, куда обычной учётке не записать (см. `_reset_hive`)."""
    try:
        import winreg
        with winreg.OpenKey(_reset_hive(), RESET_KEY) as k:
            stamp = str(winreg.QueryValueEx(k, RESET_VALUE)[0])
            try:
                who = str(winreg.QueryValueEx(k, RESET_BY)[0])
            except OSError:
                who = ""
            return stamp, who
    except (OSError, ImportError):
        return "", ""


# Закрытый список. Имя → обработчик. ⛔ Ни `getattr`, ни импорта по имени:
# словарь и есть граница того, что вообще может случиться за UAC.
OPS = {"uninstall-version": _set_uninstall_version,
       "install-setup": _install_setup,
       "auth-reset": _auth_reset}


def run_op(name: str, args: list[str], data_root=None, base=None) -> str:
    """Исполнить операцию. Зовётся УЖЕ в привилегированном процессе.

    ⚠️ `data_root` передаёт ЛАУНЧЕР своей же функцией. Считать раскладку здесь
    вторым способом нельзя: у неё две ветки (`$DENTART_DATA_DIR`,
    `%ProgramData%`), и второй вычислитель разошёлся бы с первым молча.
    `base` — корень программы от него же (`desktop.BASE`; у движка Tauri —
    папка оболочки над `engine\\`, `_layout`).
    ⛔ Это НЕ путь из аргументов: значение приходит из кода, а не из argv.
    """
    op = OPS.get(name)
    if op is None:
        raise Refused(f"операции {name!r} не существует; известны {sorted(OPS)}")
    # ⛔ Без «а если не примет» — все операции принимают резолвер одинаково.
    # Запасной вызов по `TypeError` ловил бы и ошибку ВНУТРИ операции и звал бы
    # её второй раз с другими аргументами: за UAC это худшее, что можно
    # придумать, и выглядело бы как случайный сбой.
    return op(list(args), data_root, base)


def handle_argv(argv: list[str], data_root=None, base=None) -> int | None:
    """`None` — обычный запуск; число — код возврата привилегированного.

    ⚠️ Зовётся ПЕРВОЙ строкой лаунчера. Привилегированный процесс обязан
    сделать ровно одно дело и выйти: подними он заодно сервер, у клиники
    оказалась бы программа, работающая от администратора, — и всё, что она
    пишет, стало бы недоступно ей же самой при следующем обычном запуске.
    """
    if len(argv) < 2 or argv[0] != FLAG:
        return None
    try:
        print(run_op(argv[1], argv[2:], data_root, base))
        return 0
    except Refused as e:
        print(f"отклонено: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"не удалось: {e}", file=sys.stderr)
        return 1


def request(name: str, *args: str, _shell=None) -> bool:
    """Попросить Windows выполнить операцию с повышением (UAC).

    `True` — запрос ПОКАЗАН, а не «сделано»: итог UAC отсюда не виден, и
    врать об этом нельзя. Вызывающий перечитывает состояние после.

    ⛔ Аргументы проверяются и здесь тоже — не ради безопасности (её даёт
    проверка за UAC), а чтобы не показывать человеку окно UAC ради заведомо
    отклонённой операции.
    """
    if name not in OPS:
        raise Refused(f"операции {name!r} не существует")
    run_op_args = list(args)
    if name == "uninstall-version" and (len(run_op_args) != 1
                                        or not VERSION_RE.match(run_op_args[0])):
        raise Refused(f"аргументы не годятся: {run_op_args!r}")
    if name == "auth-reset" and run_op_args:
        raise Refused(f"аргументы не годятся: {run_op_args!r}")
    if not getattr(sys, "frozen", False):
        # Из исходников поднимать нечего: `sys.executable` — это python.exe,
        # и UAC показал бы клинике окно про интерпретатор.
        return False
    # ⛔ Кавычки вокруг каждого аргумента и НИКАКОЙ оболочки. Единственное, что
    # запускается, — наш собственный exe.
    line = " ".join(f'"{a}"' for a in [FLAG, name, *run_op_args])
    shell = _shell
    if shell is None:                       # шов для проверок: настоящий UAC
        import ctypes                       # в прогоне не показать
        shell = ctypes.windll.shell32.ShellExecuteW
    try:
        return shell(None, "runas", sys.executable, line, None, 0) > 32
    except (OSError, AttributeError):
        return False
