"""Правка dental.env — файла, который клиника иногда открывает блокнотом.

Отдельный модуль, потому что писать в него умеют ДВОЕ: лаунчер (перешифровка
токена при старте) и страница настроек (сохранение токена из интерфейса). Пока
одна и та же логика жила в двух местах, ошибка в ней чинилась бы только в одном.

⚠️ Записывать через `\\n`, а НЕ `\\r\\n`: write_text открывает файл с
newline=None и сам переводит `\\n` в os.linesep. Явный `\\r\\n` давал `\\r\\r\\n`,
а splitlines() видит в этом ДВА перевода строки — файл РОС ВДВОЕ на каждом
сохранении (замерено: 2 строки -> 8 -> 16 -> 32). Прочие ключи при этом
уцелевали, поэтому поломка была видна только глазами, открывшими файл.

⚠️ Лежит в корне `app/`, как paths.py и dpapi.py: лаунчер зовёт его ДО того,
как собрано приложение, поэтому импортов проекта тут нет.
"""
from __future__ import annotations

import pathlib


def read_all(path: pathlib.Path) -> dict[str, str]:
    """Пары ключ=значение; комментарии и пустые строки пропускаются."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def set_value(path: pathlib.Path, key: str, value: str) -> None:
    """Заменить одно значение, сохранив комментарии и порядок прочих строк."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
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
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
