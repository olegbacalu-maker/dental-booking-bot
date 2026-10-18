"""Запуск вместе с Windows (Tauri, пункт Т8; контракт docs/dentpilot-2/
tauri-contract.md § 2 «Запуск вместе с Windows»).

Галочка в Setări › Stare sistem (Олег 18.10): по учётке Windows, по умолчанию
выключена; на ПК с «Acces din rețea» — подсказка включить: после перезагрузки
телефоны врачей не откроют журнал, пока кто-нибудь не кликнет ярлык.

Пишет её ДВИЖОК — он работает под учёткой человека: значение `DentPilot` в
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run =
`"<BASE>\\DentPilot.exe" --tray`. Оболочка с `--tray` стартует сразу у часов,
без окна.

⭐ Состояние — ФАКТ из реестра, а не запись в настройках: галочку снимают и в
«Диспетчере задач › Автозагрузка», и экран обязан это увидеть.
⛔ Только у собранного движка под оболочкой: путь даёт `sidecar.shell_exe()`
(корень программы считает ОДИН лаунчер — `desktop.exe_dir`), None — галочки
нет (окно pywebview, сервер, исходники).
⛔ Прогон настоящую автозагрузку разработчика не трогает: из исходников
строка есть только у стенда прогона — `DENTART_SHELL=tauri` и ОБЕ его
переменные (`KEY_ENV` — свой подключ HKCU, `EXE_ENV` — «оболочка»); у
собранной программы они не читаются вовсе.
"""
from __future__ import annotations

import os
import pathlib
import sys

from ... import paths, sidecar
from . import lan

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "DentPilot"
TRAY_ARG = "--tray"
KEY_ENV = "DENTART_AUTOSTART_KEY"        # стенд прогона: подключ HKCU вместо Run
EXE_ENV = "DENTART_AUTOSTART_EXE"        # стенд прогона: путь «оболочки»

LAN_HINT = ("Accesul din rețea este pornit: fără această bifă, după repornirea "
            "calculatorului telefoanele și celelalte calculatoare nu deschid jurnalul "
            "până nu pornește cineva programul.")
OTHER = "Acum Windows pornește alt DentPilot:"
FAIL = "Windows nu a permis schimbarea pornirii automate — reîncercați."


def shell_exe() -> pathlib.Path | None:
    """`<BASE>\\DentPilot.exe` — что записать в Run; None — галочки нет."""
    return sidecar.shell_exe()


def _stand() -> tuple[str, pathlib.Path] | None:
    """Стенд прогона (только исходники): свой подключ и своя «оболочка»."""
    if paths.is_frozen() or not sidecar.active():
        return None
    key = os.environ.get(KEY_ENV, "").strip()
    exe = os.environ.get(EXE_ENV, "").strip()
    return (key, pathlib.Path(exe)) if key and exe else None


def _target() -> tuple[str, pathlib.Path] | None:
    """(подключ HKCU, exe оболочки) — куда и что писать; None — строки нет."""
    stand = _stand()
    if stand is not None:
        return stand
    exe = shell_exe()
    return (RUN_KEY, exe) if exe is not None else None


def command(exe: pathlib.Path) -> str:
    return f'"{exe}" {TRAY_ARG}'


def _read(key: str) -> str | None:
    """Значение в реестре как записано; None — значения нет."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return str(winreg.QueryValueEx(k, VALUE)[0])
    except OSError:
        return None


def _same(a: str, b: str) -> bool:
    """Пути Windows без учёта регистра и лишних пробелов."""
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def state() -> dict | None:
    """Модель строки «Pornire» экрана Stare sistem; None — строки нет.
    `other` — наше значение указывает на ДРУГОЙ exe (старая папка, флешка):
    галочка снята, а включение перепишет его на этот."""
    t = _target()
    if sys.platform != "win32" or t is None or not t[1].is_file():
        return None
    key, exe = t
    cur = _read(key)
    on = cur is not None and _same(cur, command(exe))
    return {"on": on, "other": f"{OTHER} {cur}" if cur and not on else "",
            "hint": LAN_HINT if lan.enabled() and not on else ""}


def apply(on: bool) -> bool:
    """Включить или снять. False — Windows не дал (права на ключ, политика).
    Снятие убирает только НАШЕ имя значения: чужие записи Run не наши."""
    import winreg
    t = _target()
    if t is None:
        return False
    key, exe = t
    try:
        if on:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command(exe))
        elif _read(key) is not None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, VALUE)
    except OSError:
        return False
    return True
