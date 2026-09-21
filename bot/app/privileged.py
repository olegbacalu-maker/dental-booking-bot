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


def _set_uninstall_version(args: list[str]) -> str:
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


# Закрытый список. Имя → обработчик. ⛔ Ни `getattr`, ни импорта по имени:
# словарь и есть граница того, что вообще может случиться за UAC.
OPS = {"uninstall-version": _set_uninstall_version}


def run_op(name: str, args: list[str]) -> str:
    """Исполнить операцию. Зовётся УЖЕ в привилегированном процессе."""
    op = OPS.get(name)
    if op is None:
        raise Refused(f"операции {name!r} не существует; известны {sorted(OPS)}")
    return op(list(args))


def handle_argv(argv: list[str]) -> int | None:
    """`None` — обычный запуск; число — код возврата привилегированного.

    ⚠️ Зовётся ПЕРВОЙ строкой лаунчера. Привилегированный процесс обязан
    сделать ровно одно дело и выйти: подними он заодно сервер, у клиники
    оказалась бы программа, работающая от администратора, — и всё, что она
    пишет, стало бы недоступно ей же самой при следующем обычном запуске.
    """
    if len(argv) < 2 or argv[0] != FLAG:
        return None
    try:
        print(run_op(argv[1], argv[2:]))
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
