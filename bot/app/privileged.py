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

⚠️ Предзагрузочный слой: из проекта не импортируется ничего. Модуль зовёт
`desktop.py` первой же строкой, до того как приложение существует, — иначе
привилегированный запуск поднял бы ещё и сервер.
"""
from __future__ import annotations

import re
import shutil
import sys

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


def _set_uninstall_version(args: list[str], data_root=None) -> str:
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
NEW_SUFFIX = ".new.exe"
OLD_SUFFIX = ".old.exe"
REQUEST_NAME = "install.request"
RESULT_NAME = "install.result"

# Сколько может весить программа. Нижняя граница — от оборванной закачки
# (urllib не считает обрыв ошибкой), верхняя — чтобы не двигать в Program Files
# что попало.
MIN_EXE, MAX_EXE = 5_000_000, 300_000_000


def _self_exe() -> "pathlib.Path":
    """Что именно подменяем. ⭐ Своя функция, а не выражение по месту: это ШОВ
    для проверок — иначе набор подменял бы python.exe, которым сам и запущен.
    ⛔ Значение по-прежнему берётся у процесса, а НЕ из аргументов: снаружи
    назвать цель нельзя ничем."""
    import pathlib
    return pathlib.Path(sys.executable).resolve()


def _install_update(args: list[str], data_root=None) -> str:
    """Подменить файл программы новым. ⛔ Ни одного аргумента, ни одного пути.

    Источник и назначение исполнитель вычисляет САМ: назначение — это он сам
    (`sys.executable`), источник — условленное имя в папке клиники, которую он
    находит тем же способом, что лаунчер.

    ⛔ **Здесь ничего не ИСПОЛНЯЕТСЯ.** Это и есть главный инвариант: файл
    только перемещается. Запусти мы новую программу отсюда — она пошла бы от
    администратора, а всё, что она пишет, стало бы недоступно клинике при
    следующем обычном запуске; и подменённый кем-то файл получил бы права,
    которых у него нет. Перезапуск делает обычный процесс, обычным пользователем.

    ⚠️ Проверка повторяется ЗДЕСЬ, хотя обычный процесс уже проверял: между его
    проверкой и этим моментом файл могли подменить. Она ловит гонку и порчу.
    ⛔ Чего она НЕ ловит — подмену тем, кто уже работает с правами клиники:
    и файл, и записанный рядом отпечаток лежат в папке, куда он пишет. Закрыть
    это может только подпись Authenticode, и она в «закалке»; но и цена такой
    подмены ограничена тем, что сказано выше: файл не исполняется, а попадает в
    папку, откуда его запустит обычный пользователь.
    """
    if args:
        raise Refused(f"операция не принимает аргументов, получено {args!r}")
    import hashlib
    import json
    import pathlib

    exe = _self_exe()
    root = data_root() if callable(data_root) else data_root
    if root is None:
        raise Refused("папка клиники не найдена — источник обновления неизвестен")
    work = pathlib.Path(root) / WORK_SUBDIR
    new = work / (exe.stem + NEW_SUFFIX)
    result = work / RESULT_NAME

    def done(text: str) -> str:
        # ⭐ Итог пишем ФАЙЛОМ: обычный процесс не видит ни кода возврата за
        # UAC, ни вывода, и без этого ему осталось бы гадать.
        try:
            result.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return text

    if not new.exists():
        return done("нет файла обновления")
    size = new.stat().st_size
    if not MIN_EXE <= size <= MAX_EXE:
        return done(f"размер не годится: {size}")
    with open(new, "rb") as f:
        if f.read(2) != b"MZ":
            # ⛔ Опознаём по СИГНАТУРЕ, а не по расширению — тот же прайор, что
            # у логотипа клиники.
            return done("это не программа Windows")
    try:
        want = json.loads((work / REQUEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return done("нет описания обновления")
    if str(want.get("size")) != str(size):
        return done("размер разошёлся с описанием")
    h = hashlib.sha256()
    with open(new, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != str(want.get("sha256", "")).lower():
        return done("отпечаток разошёлся с описанием")

    old = exe.with_name(exe.stem + OLD_SUFFIX)
    # ⛔ Порядок тот же, что у скрипта переносимой раскладки, и по той же
    # причине (08-10): сперва увести рабочий файл, потом класть новый. При
    # прямой замене любой сбой ПОСЛЕ неё не оставлял на диске ни одной копии
    # программы, и все ярлыки вели в никуда.
    try:
        old.unlink(missing_ok=True)
        exe.rename(old)
    except OSError as e:
        return done(f"не удалось убрать рабочий файл: {e}")
    try:
        shutil.move(str(new), str(exe))
    except OSError as e:
        try:
            old.rename(exe)          # неудачное обновление ≠ удаление программы
        except OSError:
            pass
        return done(f"не удалось положить новый файл: {e}")
    return done("ok")


# Закрытый список. Имя → обработчик. ⛔ Ни `getattr`, ни импорта по имени:
# словарь и есть граница того, что вообще может случиться за UAC.
OPS = {"uninstall-version": _set_uninstall_version,
       "install-update": _install_update}


def run_op(name: str, args: list[str], data_root=None) -> str:
    """Исполнить операцию. Зовётся УЖЕ в привилегированном процессе.

    ⚠️ `data_root` передаёт ЛАУНЧЕР своей же функцией. Считать раскладку здесь
    вторым способом нельзя: у неё три ветки (`$DENTART_DATA_DIR`, портативный
    флаг, `%ProgramData%`), и второй вычислитель разошёлся бы с первым молча.
    ⛔ Это НЕ путь из аргументов: значение приходит из кода, а не из argv.
    """
    op = OPS.get(name)
    if op is None:
        raise Refused(f"операции {name!r} не существует; известны {sorted(OPS)}")
    # ⛔ Без «а если не примет» — все операции принимают резолвер одинаково.
    # Запасной вызов по `TypeError` ловил бы и ошибку ВНУТРИ операции и звал бы
    # её второй раз с другими аргументами: за UAC это худшее, что можно
    # придумать, и выглядело бы как случайный сбой.
    return op(list(args), data_root)


def handle_argv(argv: list[str], data_root=None) -> int | None:
    """`None` — обычный запуск; число — код возврата привилегированного.

    ⚠️ Зовётся ПЕРВОЙ строкой лаунчера. Привилегированный процесс обязан
    сделать ровно одно дело и выйти: подними он заодно сервер, у клиники
    оказалась бы программа, работающая от администратора, — и всё, что она
    пишет, стало бы недоступно ей же самой при следующем обычном запуске.
    """
    if len(argv) < 2 or argv[0] != FLAG:
        return None
    try:
        print(run_op(argv[1], argv[2:], data_root))
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
