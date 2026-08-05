"""Где лежат ДАННЫЕ клиники — в отличие от paths.py, который знает, где лежит
сама программа.

Разница существенная: `paths.resource()` указывает внутрь сборки (только
чтение, в exe это временная распаковка), а здесь — рабочая папка с базой,
PIN-файлом, документами пациентов и бэкапами. У облачного издания её нет
вовсе: там всё в Postgres, поэтому функция честно возвращает None, и каждый
вызывающий обязан этот случай обработать.
"""
from __future__ import annotations

import pathlib

from .. import db


def _data_dir() -> pathlib.Path | None:
    if db.IS_SQLITE:
        return pathlib.Path(db.DATABASE_URL.split("///", 1)[1]).parent
    return None
