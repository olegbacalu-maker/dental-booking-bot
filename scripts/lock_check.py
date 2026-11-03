# -*- coding: utf-8 -*-
"""Lock-файлы не отстали от своих requirements (03.11.2026).

    python scripts/lock_check.py

CI ставит LOCK (`bot/requirements-desktop.lock`, `cloud/requirements.lock`),
а сборка exe и люди правят `requirements*.txt`. Подняли версию в `.txt` и
забыли пересобрать lock — CI молча проверяет старую, а клинике уезжает новая.
Здесь каждая закреплённая `имя==версия` из входа обязана стоять в lock той
же версией. Пересобрать lock — команда в его первых строках.

Только стандартная библиотека: идёт в работе lint, где ничего не ставится.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAIRS = [
    ("bot/requirements-desktop.txt", "bot/requirements-desktop.lock"),
    ("cloud/requirements.txt", "cloud/requirements.lock"),
]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^\s;\\]+)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(path: pathlib.Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = PIN.match(line.strip())
        if m:
            out[_norm(m.group(1))] = m.group(2)
    return out


def main() -> int:
    bad = []
    for src, lock in PAIRS:
        want, got = _pins(ROOT / src), _pins(ROOT / lock)
        if not want or not got:
            bad.append(f"{src} / {lock}: закреплённых строк не нашлось — разбор сломан")
        for name, ver in sorted(want.items()):
            if got.get(name) != ver:
                bad.append(f"{lock}: {name} {got.get(name)} ≠ {ver} из {src}")
    for line in bad:
        print(line)
    print("lock-файлы совпадают с requirements" if not bad else
          "пересобрать lock — команда в его шапке")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
