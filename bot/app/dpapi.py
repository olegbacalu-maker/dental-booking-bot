"""Шифрование секретов средствами Windows (DPAPI), без внешних пакетов.

Что это даёт честно: файл, унесённый С ЭТОГО компьютера, бесполезен — ключ
держит Windows и отдаёт его только той же учётной записи на той же машине.
Чего это НЕ даёт: секрет не спрятан от самого пользователя. Программа работает
под его учёткой, значит всё, что расшифровывает она, расшифрует и он. Клинике
нельзя обещать «ключ недоступен» — можно обещать «унесённый файл мёртв».

Отсюда же главная опасность: переустановка Windows, новый компьютер или работа
под другой учётной записью делают шифротекст нечитаемым НАВСЕГДА. Поэтому
здесь шифруется только то, что клиника может ввести заново (пароль внешней
копии) или чему есть печатная запасная (ключ картотеки — лист восстановления),
и никогда — данные, которых больше нигде нет. По той же причине `unprotect`
отличает «не расшифровалось» (None) от «пусто» (""): молча пустой секрет
читается интерфейсом как «не настроено», и клиника пойдёт искать
несуществующую ошибку настройки вместо того, чтобы ввести его заново.

⚠️ Лежит в корне `app/` намеренно, как и paths.py: лаунчер (`desktop.py`)
зовёт его ДО того, как собрано приложение, поэтому импортов проекта тут нет.
"""
from __future__ import annotations

import base64
import sys


# Метка в dental.env. Со «своим» префиксом — шифротекст, без него — открытый
# токен старой установки: формат обязан читаться в обе стороны, иначе
# обновление у клиники, где токен уже вписан руками, погасит бота.
PREFIX = "dpapi:"

_WIN = sys.platform == "win32"

if _WIN:
    import ctypes
    import ctypes.wintypes as wt

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _call(fn, data: bytes) -> bytes | None:
        src, dst = _BLOB(), _BLOB()
        # буфер обязан пережить вызов: пока он жив, жива и ссылка в src
        buf = ctypes.create_string_buffer(data, len(data))
        src.cbData = len(data)
        src.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
        ok = fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst))
        if not ok:
            return None
        try:
            return ctypes.string_at(dst.pbData, dst.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(dst.pbData)


def available() -> bool:
    """Есть ли DPAPI. Облачное издание живёт в Linux-контейнере — там нет."""
    return _WIN


def protect(text: str) -> str | None:
    """Открытый текст -> строка для файла. None — зашифровать не вышло."""
    if not text or not _WIN:
        return None
    raw = _call(ctypes.windll.crypt32.CryptProtectData, text.encode("utf-8"))
    return PREFIX + base64.b64encode(raw).decode() if raw else None


def unprotect(stored: str) -> str | None:
    """Строка из файла -> открытый текст.

    "" — значения не было. None — значение ЕСТЬ, но не расшифровывается:
    сменилась учётка или машина. Это разные беды и разные подсказки клинике.
    """
    stored = (stored or "").strip()
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        return stored                      # открытый токен старой установки
    if not _WIN:
        return None
    try:
        raw = base64.b64decode(stored[len(PREFIX):], validate=True)
    except ValueError:                     # binascii.Error — подкласс ValueError
        return None
    out = _call(ctypes.windll.crypt32.CryptUnprotectData, raw)
    return out.decode("utf-8", "replace") if out else None
