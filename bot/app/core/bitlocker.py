"""Состояние BitLocker на диске с данными клиники — глазами программы.

Решение 08-07: шифрование к закону 195 закрывается BitLocker-ом (SQLCipher —
отдельный план на осень). Значит программа обязана УМЕТЬ СКАЗАТЬ, включён ли
он на самом деле: подписанный акт из lege-195 без проверки — бумага о
намерении. Особо важна ловушка новых ПК, измеренная вживую на машине Олега
08-06: диск «Encrypted 100%», но Protection OFF — ключ лежит открытым рядом с
данными, реальная защита ноль, и выглядит это «всё зашифровано».

Как спрашиваем: Shell COM `System.Volume.BitLockerProtection` — работает БЕЗ
прав администратора (manage-bde и WMI Win32_EncryptableVolume требуют их).
Зовём через PowerShell: COM из ctypes без зависимостей — это страница кода, а
проверка нужна один раз при старте, в фоне. Коды (сверены с живой машиной:
до активации C: отдавал 8, после — 1):
  1 включён и защищает · 2 не зашифрован · 3 шифруется · 5 приостановлен ·
  8 зашифрован, но защита ВЫКЛЮЧЕНА (та самая ловушка).
"""
from __future__ import annotations

import logging
import pathlib
import subprocess
import sys
import threading

log = logging.getLogger("bitlocker")

# None в state = ещё не спрашивали или спросить не вышло (не Windows, таймаут)
STATE: dict = {"code": None, "drive": ""}

_OK, _WARN, _ALARM = "ok", "warn", "alarm"

_CODES = {
    1: (_OK, "activ — discul {d} este criptat și protejat"),
    3: (_OK, "criptarea discului {d} este în curs"),
    2: (_WARN, "discul {d} NU este criptat — porniți BitLocker "
               "(instrucțiunea din mapa Legea 195)"),
    5: (_WARN, "protecția discului {d} este SUSPENDATĂ — reporniți-o"),
    8: (_ALARM, "discul {d} pare criptat, dar protecția este OPRITĂ și cheia "
                "stă lângă date — activați BitLocker în Panoul de control "
                "(capcana calculatoarelor noi)"),
}


def describe(code: int | None, drive: str = "") -> tuple[str, str]:
    """(тон, текст по-румынски) для интерфейса. Неизвестное — честное «не
    удалось проверить», а не тревога: пугать клинику гаданием нельзя."""
    if code is None:
        return ("unknown", "starea BitLocker nu a putut fi verificată")
    tone, txt = _CODES.get(code, ("unknown",
                                  f"stare BitLocker necunoscută (cod {code})"))
    return tone, txt.format(d=drive or "?")


def _probe(drive: str) -> int | None:
    ps = ("(New-Object -ComObject Shell.Application).NameSpace('"
          + drive + "\\').Self.ExtendedProperty("
          "'System.Volume.BitLockerProtection')")
    try:
        no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=20, creationflags=no_win)
        out = (p.stdout or "").strip()
        return int(out) if out.lstrip("-").isdigit() else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        log.warning("BitLocker probe failed: %r", e)
        return None


def check_async(data_dir: pathlib.Path | None) -> None:
    """Разовая фоновая проверка при старте. Диск берём у ПАПКИ ДАННЫХ: закон
    спрашивает про картотеку, а не про диск, куда поставили программу."""
    if sys.platform != "win32" or data_dir is None:
        return
    drive = pathlib.Path(data_dir).resolve().drive  # 'C:'
    if not drive:
        return

    def _run() -> None:
        STATE.update(code=_probe(drive), drive=drive)
        tone, txt = describe(STATE["code"], drive)
        if tone in (_WARN, _ALARM):
            log.warning("BitLocker: %s", txt)

    threading.Thread(target=_run, daemon=True).start()
