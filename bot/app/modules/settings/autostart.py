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
⛔ Только в режиме движка (`DENTART_SHELL=tauri`) у собранной программы: у
окна pywebview и в браузере оболочки, которую запускать, нет.
⛔ Прогон настоящую автозагрузку разработчика не трогает: из исходников
галочка есть только с подставным ключом и exe (`KEY_ENV`, `EXE_ENV`), а у
собранной программы эти переменные не читаются вовсе.
"""
from __future__ import annotations

import os
import pathlib
import sys

from ... import paths
from . import lan

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "DentPilot"
TRAY_ARG = "--tray"
KEY_ENV = "DENTART_AUTOSTART_KEY"        # прогон: подключ HKCU вместо Run
EXE_ENV = "DENTART_AUTOSTART_EXE"        # прогон: путь «оболочки» вместо BASE

LAN_HINT = ("Accesul din rețea este pornit: fără această bifă, după repornirea "
            "calculatorului telefoanele și celelalte calculatoare nu deschid jurnalul "
            "până nu pornește cineva programul.")
OTHER = "Acum Windows pornește alt DentPilot:"
FAIL = "Windows nu a permis schimbarea pornirii automate — reîncercați."


def shell_mode() -> bool:
    """Движок под оболочкой Tauri (контракт § 2)."""
    return os.environ.get("DENTART_SHELL", "").strip().lower() == "tauri"


def shell_exe() -> pathlib.Path | None:
    """`<BASE>\\DentPilot.exe` — что записать в Run; None — галочке не место.

    ⚠️ ВРЕМЕННАЯ: BASE режима движка вводит Т5 (контракт § 1 — родитель папки
    `engine\\`, где лежит движок). Тело заменяется его функцией, имя остаётся."""
    if not paths.is_frozen():
        raw = os.environ.get(EXE_ENV, "").strip()
        return pathlib.Path(raw) if raw and os.environ.get(KEY_ENV, "").strip() else None
    return pathlib.Path(sys.executable).resolve().parent.parent / "DentPilot.exe"


def _key() -> str:
    alt = "" if paths.is_frozen() else os.environ.get(KEY_ENV, "").strip()
    return alt or RUN_KEY


def command(exe: pathlib.Path) -> str:
    return f'"{exe}" {TRAY_ARG}'


def _read() -> str | None:
    """Значение в реестре как записано; None — значения нет."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _key()) as k:
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
    exe = shell_exe()
    if sys.platform != "win32" or not shell_mode() or exe is None or not exe.is_file():
        return None
    cur = _read()
    on = cur is not None and _same(cur, command(exe))
    return {"on": on, "other": f"{OTHER} {cur}" if cur and not on else "",
            "hint": LAN_HINT if lan.enabled() and not on else ""}


def apply(on: bool) -> bool:
    """Включить или снять. False — Windows не дал (права на ключ, политика).
    Снятие убирает только НАШЕ имя значения: чужие записи Run не наши."""
    import winreg
    exe = shell_exe()
    if exe is None:
        return False
    try:
        if on:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _key(), 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command(exe))
        elif _read() is not None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _key(), 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, VALUE)
    except OSError:
        return False
    return True
