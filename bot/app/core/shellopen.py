"""Открыть файл программой Windows ВНЕ задания оболочки Tauri (18.10, 2.0.3).

Оболочка держит движок в «задании» Windows с KILL_ON_JOB_CLOSE
(`shell/src/engine.rs::JOB_LIMITS`): закрыли DentPilot — Windows гасит всех
внутри. `os.startfile` — это ShellExecute в процессе движка, и классическая
программа (Word, Acrobat, просмотрщик снимков) рождается его ребёнком в
задании и гаснет вместе с DentPilot — с несохранённой правкой врача.
Приложения Store запускает брокер, они не страдали (опыт 18.10: обработчик
`.vbs`, открытый `os.startfile` из задания, погиб при его закрытии).

Открывает `explorer.exe` — так же, как двойной щелчок:
- новый explorer отдаёт открытие COM-серверу `explorer.exe /factory,…
  -Embedding`, которого запускает DCOM, а не движок; обработчик рождается у
  него, вне задания, даже без флага;
- `CREATE_BREAKAWAY_FROM_JOB` выводит из задания и сам explorer — обработчик
  вне задания, даже если explorer откроет файл сам. Задание без
  BREAKAWAY_OK (оболочка до 2.0.2, задание харнесса) отвечает на флаг
  отказом, WinError 5, — тогда без флага, на одном COM-сервере.
⛔ Путь — строкой в кавычках, НЕ списком: `list2cmdline` не берёт в кавычки
путь без пробелов, а explorer режет аргумент по запятой —
`Radiografie,12.10.pdf` молча не открывался (опыт 18.10).
⚠️ Код выхода explorer ничего не значит (всегда 1): `OSError` — только если
explorer не запустился. Файл без ассоциации — диалог Windows «чем открыть»,
ровно как у прежнего `os.startfile` (опыт 18.10, Windows 11).
rundll32 `ShellExec_RunDLL` тоже выживает, но только с флагом, и это
известный антивирусам приём (LOLBin) — не он.

Стенд: `test_patient_card.suite_doc_outlives_shell` (`tests/jobstand.py`).
"""
from __future__ import annotations

import os
import pathlib
import subprocess

BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)


def _explorer() -> str:
    """Полный путь, а не имя: CreateProcess ищет имя сперва в папке движка."""
    return str(pathlib.Path(os.environ.get("SystemRoot") or r"C:\Windows") / "explorer.exe")


def open_file(path: pathlib.Path | str) -> None:
    """Открыть файл программой по умолчанию; не ждёт. `OSError` — не запустилось."""
    line = f'"{_explorer()}" "{pathlib.Path(path)}"'
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True)
    try:
        subprocess.Popen(line, creationflags=BREAKAWAY, **kw)
    except PermissionError:
        subprocess.Popen(line, **kw)
