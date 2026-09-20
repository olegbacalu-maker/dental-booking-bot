"""Где лежала СТАРАЯ установка — если она вообще была.

Нужно миграции (P2): прежде чем что-то переносить, надо доказать, откуда.
Разбор и решения — `docs/dentpilot-2/storage.md` › «P3-min v1».

⭐ ГЛАВНОЕ ПРАВИЛО, и оно выражено формой этого модуля: **кандидата называет
ТОЛЬКО источник происхождения, содержимое папки его подтверждает.** Обратный
порядок — «тут лежит DentPilot.exe и база, значит это установка клиники» —
небезопасен, и это не теория: на машине разработчика есть
`D:\\DentProject\\backups\\pre-clean-install-2026-08-05\\` — полная байтовая
копия установки со всеми маркерами. Она пройдёт любую проверку по содержимому.
Миграция, доверяющая содержимому, однажды переедет резервную копию поверх
работающей картотеки.

Поэтому `confirm()` не умеет возвращать путь, а `detect()` перебирает ТОЛЬКО
то, что вернул `origins()`. Нет источника — нет кандидата, и это не ошибка
разбора, а ответ.

⛔ **RESERVED, в v1 не реализовано:** запущенный процесс, профили других
пользователей (`ProfileList`), чужие `AppData`, WMI, ключ деинсталляции в
реестре, поиск по диску. Причины — в storage.md. Добавлять по одному, вместе
со сценарием реальной клиники и проверкой к нему; не «на всякий случай».

⚠️ Модуль предзагрузочного слоя: импортов проекта тут нет и быть не может.
"""
from __future__ import annotations

import os
import pathlib
import struct

# Имя программы, чей ярлык ищем. ⚠️ Совпадает с именем ассета обновления и с
# тем, что кладёт установщик, — но это РАЗНЫЕ знания, и связывать их импортом
# нельзя: этот модуль живёт до сборки приложения.
EXE_NAME = "DentPilot.exe"

# Маркеры, которыми папка ПОДТВЕРЖДАЕТ себя. Ни один из них не назначает.
MARKERS = ("clinic.json", "dental.env", EXE_NAME, "unins000.dat")

ORIGIN_SHORTCUT = "shortcut"


def shortcut_paths() -> list[pathlib.Path]:
    """Три места, где ярлык создаём МЫ САМИ, у ТЕКУЩЕГО пользователя.

    ⭐ Почему только текущий: чужие профили — резерв. Ярлык есть у каждого
    пути установки, который мы отгружаем: `[Icons]` кладёт запись в меню
    «Пуск» безусловно, `Install-DentPilot.ps1` — на стол и в автозагрузку.
    """
    appdata = os.environ.get("APPDATA", "")
    home = os.environ.get("USERPROFILE", "")
    out = []
    if home:
        out.append(pathlib.Path(home) / "Desktop" / "DentPilot.lnk")
    if appdata:
        base = pathlib.Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        out += [base / "DentPilot.lnk", base / "Startup" / "DentPilot.lnk"]
    return out


def shortcut_target(lnk: pathlib.Path) -> pathlib.Path | None:
    """Куда ведёт ярлык. Разбор формата Shell Link, только стандартная библиотека.

    ⛔ Не через COM и не через PowerShell: `.venv-desktop` — окружение сборки,
    и лишние пакеты уезжают в exe; вызывать оболочку из лаунчера ради одного
    пути — тем более. Формат стабилен и документирован, а берём из него ровно
    одно поле.

    ⚠️ Любая неожиданность = None, а не исключение и не догадка: ярлык мог
    быть создан чем угодно, а неверно разобранный путь хуже неразобранного.
    """
    try:
        b = lnk.read_bytes()
    except OSError:
        return None
    if len(b) < 76 or b[:4] != b"\x4c\x00\x00\x00":
        return None
    try:
        flags = struct.unpack("<I", b[20:24])[0]
        off = 76
        if flags & 0x1:                       # HasLinkTargetIDList — пропускаем
            off += 2 + struct.unpack("<H", b[off:off + 2])[0]
        if not flags & 0x2:                   # HasLinkInfo
            return None
        hdr = struct.unpack("<I", b[off + 4:off + 8])[0]
        li_flags = struct.unpack("<I", b[off + 8:off + 12])[0]
        if not li_flags & 0x1:                # VolumeIDAndLocalBasePath
            return None
        if hdr >= 0x24:                       # есть поля в Unicode
            base = _zstr(b, off + struct.unpack("<I", b[off + 28:off + 32])[0], True)
            suffix = _zstr(b, off + struct.unpack("<I", b[off + 32:off + 36])[0], True)
        else:
            base = _zstr(b, off + struct.unpack("<I", b[off + 16:off + 20])[0], False)
            suffix = _zstr(b, off + struct.unpack("<I", b[off + 24:off + 28])[0], False)
    except (struct.error, IndexError):
        return None
    full = (base + suffix).strip("\x00").strip()
    return pathlib.Path(full) if full else None


def _zstr(b: bytes, start: int, unicode: bool) -> str:
    if start <= 0 or start >= len(b):
        return ""
    if unicode:
        end = b.find(b"\x00\x00", start)
        chunk = b[start:end + 1 if end > 0 else len(b)]
        return chunk.decode("utf-16-le", "replace")
    end = b.find(b"\x00", start)
    return b[start:end if end > 0 else len(b)].decode("mbcs", "replace")


def origins(shortcuts: list[pathlib.Path] | None = None) -> list[dict]:
    """Кандидаты, НАЗВАННЫЕ источником. Единственный вход в детекцию.

    Возвращает `[{"path": папка, "origin": ..., "source": файл-ярлык}]`,
    без дубликатов, в порядке обхода.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for lnk in (shortcut_paths() if shortcuts is None else shortcuts):
        target = shortcut_target(lnk)
        if target is None or target.name.lower() != EXE_NAME.lower():
            continue
        folder = target.parent
        key = str(folder).rstrip("\\/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": folder, "origin": ORIGIN_SHORTCUT, "source": lnk})
    return out


def confirm(folder: pathlib.Path) -> list[str]:
    """Какие маркеры нашлись в НАЗВАННОЙ папке.

    ⛔ Функция принимает путь и не умеет его искать — это не удобство, а
    защита: искать по содержимому нельзя (см. шапку модуля).
    """
    try:
        return [m for m in MARKERS if (folder / m).exists()]
    except OSError:
        return []


def detect(shortcuts: list[pathlib.Path] | None = None) -> dict:
    """Итог: `{"found", "path", "origin", "source", "markers", "reason"}`.

    Три исхода, и все три названы явно:
      * `found=True`  — источник назвал папку, маркеры её подтвердили;
      * `found=False`, `reason="no-origin"` — источников нет вовсе;
      * `found=False`, `reason="unconfirmed"` — источник назвал, но папки с
        маркерами там нет (ярлык на удалённую установку — обычное дело).

    ⛔ Четвёртого исхода «похоже, что вон та папка» не существует и появиться
    не может: перебирается только то, что вернул `origins()`.
    ⚠️ `found=False` НЕ означает «чистая машина». Чистой машина считается по
    положительному признаку, иначе первый же сбой детекции выглядит как новая
    клиника — и программа заводит пустой журнал рядом с живой картотекой.
    """
    cand = origins(shortcuts)
    if not cand:
        return {"found": False, "path": None, "origin": None, "source": None,
                "markers": [], "reason": "no-origin"}
    for c in cand:
        markers = confirm(c["path"])
        if markers:
            return {"found": True, "path": c["path"], "origin": c["origin"],
                    "source": c["source"], "markers": markers, "reason": "ok"}
    first = cand[0]
    return {"found": False, "path": None, "origin": first["origin"],
            "source": first["source"], "markers": [], "reason": "unconfirmed"}
