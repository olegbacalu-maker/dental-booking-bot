"""Ротация `data\\dentpilot.log` (Т5, 18.10.2026; `sidecar.md` › «Лог»).

До 18.10 лог рос без предела. При оболочке Tauri у движка появляется надзор с
перезапуском, и цикл перезапусков растил бы файл неограниченно; то же делает и
ошибка в маршруте, который опрашивают каждые несколько секунд со всех мест
клиники. Предзагрузочный слой: зовёт `desktop.py` до сборки приложения.

⛔ Windows не даёт переименовать файл, открытый другим процессом, а открыт он
бывает: второй запуск программы пишет в тот же лог, пока первый жив. Штатный
`RotatingFileHandler` на этом теряет записи — поток закрыт до переименования,
отказ уходит в `handleError` вместе с записью, и следующая запись пробует
снова. Поэтому здесь: сперва переименовать сам лог во временное имя (не
вышло — ничего не тронуто), потом сдвинуть старые; отказ — запись идёт в тот
же файл, повтор не раньше чем через `RETRY_S`.
"""
from __future__ import annotations

import logging.handlers
import os
import pathlib
import time

LIMIT = 2 * 1024 * 1024        # 2 МБ; у Олега за четыре недели — 170 КБ
KEEP = 2                       # dentpilot.log.1, dentpilot.log.2
RETRY_S = 60.0


def roll(path, keep: int = KEEP) -> bool:
    """Сдвинуть `path` → `.1` → `.2` …; False — файл держит другой процесс
    (или его нет), и ничего не тронуто."""
    path = pathlib.Path(path)
    hold = path.with_name(path.name + ".rolling")
    try:
        os.replace(path, hold)
    except OSError:
        return False
    for i in range(keep - 1, 0, -1):
        older = path.with_name(f"{path.name}.{i}")
        if older.exists():
            try:
                os.replace(older, path.with_name(f"{path.name}.{i + 1}"))
            except OSError:
                pass
    try:
        os.replace(hold, path.with_name(f"{path.name}.1"))
    except OSError:
        pass
    return True


def roll_if_big(path, limit: int = LIMIT) -> bool:
    """Для файлов, которые открываются один раз на запуск (`dentpilot.err.log`)."""
    try:
        if pathlib.Path(path).stat().st_size < limit:
            return False
    except OSError:
        return False
    return roll(path)


class Handler(logging.handlers.RotatingFileHandler):
    """`RotatingFileHandler`, который не теряет записей на занятом файле."""

    retry_s = RETRY_S

    def __init__(self, filename, limit: int = LIMIT, keep: int = KEEP) -> None:
        # ⛔ utf-8 ЯВНО: без него файл открывается в ANSI машины, у румынской
        # клиники это cp1250, и русские строки лога выбрасываются целиком
        # (desktop.py, 21.09)
        super().__init__(filename, maxBytes=limit, backupCount=keep, encoding="utf-8")
        self._next_try = 0.0

    def shouldRollover(self, record) -> bool:
        if time.monotonic() < self._next_try:
            return False
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        if not roll(self.baseFilename, self.backupCount):
            self._next_try = time.monotonic() + self.retry_s
        self.stream = self._open()


def handler(path) -> Handler:
    return Handler(str(path))
