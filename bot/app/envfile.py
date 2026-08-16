"""Правка dental.env — файла, который клиника иногда открывает блокнотом.

Отдельный модуль, потому что писать в него умеют ДВОЕ: лаунчер (перешифровка
токена при старте) и страница настроек (сохранение токена из интерфейса). Пока
одна и та же логика жила в двух местах, ошибка в ней чинилась бы только в одном.

⚠️ Раз файл правят Блокнотом, читать его надо во всех кодировках, в которых
Блокнот умеет сохранять: UTF-8 (с BOM и без) и UTF-16; ANSI (cp1251) —
последним прибежищем. Прежний «только utf-8» ронял и лаунчер, и настройки
UnicodeDecodeError'ом, причём лаунчер — до подмены stderr, то есть молча.

⚠️ Записывать через `\\n`, а НЕ `\\r\\n`: файл открывается с newline=None, и
Python сам переводит `\\n` в os.linesep. Явный `\\r\\n` давал `\\r\\r\\n`,
а splitlines() видит в этом ДВА перевода строки — файл РОС ВДВОЕ на каждом
сохранении (замерено: 2 строки -> 8 -> 16 -> 32). Прочие ключи при этом
уцелевали, поэтому поломка была видна только глазами, открывшими файл.

⚠️ Лежит в корне `app/`, как paths.py и dpapi.py: лаунчер зовёт его ДО того,
как собрано приложение, поэтому импортов проекта тут нет.
"""
from __future__ import annotations

import codecs
import os
import pathlib


def _decode(data: bytes, name: str) -> str:
    """Байты файла -> текст, как их понял бы Блокнот.

    UTF-16 пробуется ТОЛЬКО по BOM: без него почти любой файл чётной длины
    «успешно» декодируется в иероглифы, и все ключи молча пропали бы.
    utf-8-sig покрывает и чистый UTF-8, и UTF-8 c BOM — иначе U+FEFF въезжает
    в имя первого ключа, и ключ перестаёт находиться (грабля BOM из карты).
    Полный провал — OSError: вызывающие уже умеют его ловить, а отдать
    полфайла или молча переписать его было бы хуже честного отказа."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16")
        except UnicodeError:
            raise OSError(f"{name}: fișierul nu poate fi citit (UTF-16 rupt)")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise OSError(f"{name}: fișierul nu poate fi citit (codare necunoscută)")


def read_all(path: pathlib.Path) -> dict[str, str]:
    """Пары ключ=значение; комментарии и пустые строки пропускаются.
    Нечитаемый файл = пустой словарь: у лаунчера на этом пути ещё нет ни
    stderr, ни лога, и падение здесь гасило бы программу без следа."""
    out: dict[str, str] = {}
    try:
        text = _decode(path.read_bytes(), path.name)
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def set_value(path: pathlib.Path, key: str, value: str) -> None:
    """Заменить одно значение, сохранив комментарии и порядок прочих строк.

    ⛔ Ошибка чтения СУЩЕСТВУЮЩЕГО файла = отказ (OSError наверх), а не запись.
    Прежний `except OSError: lines = []` при файле, придержанном антивирусом
    или OneDrive, молча сводил весь dental.env к одной строке — вместе с
    ADMIN_KEY, каналом обновления и портом. Отсутствие файла — законный
    первый случай: писать можно.

    Запись атомарная (tmp + fsync + os.replace, тот же приём, что в
    dbkey.store): прямой write_text сначала усекал файл, и обрыв питания
    между усечением и записью оставлял пустой dental.env — а «пустой env»
    для программы неотличим от «клиника ничего не настраивала».
    """
    lines: list[str] = []
    if path.exists():
        lines = _decode(path.read_bytes(), path.name).splitlines()
    out, done = [], False
    for ln in lines:
        # пустые не переносим: у уже раздутых файлов это лечит прошлые сохранения
        if not ln.strip():
            continue
        if ln.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{key}={value}")
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def parse_port(value: str | None) -> int | None:
    """DENTART_PORT из dental.env -> порт, или None про мусор и пустоту.

    Значение правит сама клиника — диалог «портул e ocupat» это прямо
    советует, — поэтому «8О88» с кириллической О или «80 88» тут ожидаемый
    ввод, а не исключение. Раньше голый int() падал на верхнем уровне
    desktop.py, до excepthook и до любого окна: двойной клик по ярлыку
    «не делал ничего». Только ASCII-цифры: int() молча принял бы и
    восточные цифры."""
    s = (value or "").strip()
    if not s.isascii() or not s.isdigit():
        return None
    port = int(s)
    return port if 1 <= port <= 65535 else None
