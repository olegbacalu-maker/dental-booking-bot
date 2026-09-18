# -*- coding: utf-8 -*-
"""Один источник версии на всю программу — `bot/app/engine.py`.

    python scripts\\sync_version.py           # привести всех потребителей к нему
    python scripts\\sync_version.py --check   # только проверить, ничего не писать

Потребителей версии в проекте несколько, и живут они в разных мирах: номер в
`engine.py` показывает сама программа и по нему решает, обновляться ли;
`frontend/package.json` его дублирует; свойства файла в Windows берут его из
ресурса, который PyInstaller вшивает ключом `--version-file`. Разойтись им
нечего стоит, а заметить расхождение трудно: exe запускается и работает, в
свойствах просто стоит не то.

⛔ Ресурс версии для PyInstaller ГЕНЕРИРУЕТСЯ здесь, а не лежит правленым
файлом. Правленый файл — это ещё один источник правды, который обязан был бы
обновляться руками при каждом выпуске; ровно ради этого и заведён скрипт.

⚠️ `--check` НИЧЕГО не пишет и годится для CI и `.\\dev check`. Красное здесь
значит «номера разошлись», а не «сборка сломана».
"""
import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE = ROOT / "bot" / "app" / "engine.py"
PACKAGE = ROOT / "frontend" / "package.json"
VERSION_FILE = ROOT / "build" / "version_info.txt"

# Свойства файла, которые видит Windows. ⚠️ Имена полей фиксированы Microsoft;
# «DentPilot» здесь — и ProductName, и InternalName, потому что обновление
# ищет ассет по имени файла `DentPilot.exe` (RELEASE.md, правило 2).
COMPANY = "DentPilot"
PRODUCT = "DentPilot"
DESCRIPTION = "DentPilot — registrul clinicii stomatologice"
COPYRIGHT = "© DentPilot"


def app_version() -> str:
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"',
                  ENGINE.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("в engine.py нет APP_VERSION")
    v = m.group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise SystemExit(f"APP_VERSION = {v!r} — нужны ровно три числа")
    return v


def version_info(version: str) -> str:
    """Ресурс VERSIONINFO для PyInstaller.

    ⚠️ Четвёртое число — ноль: у Windows версия из ЧЕТЫРЁХ чисел, а у нас из
    трёх, и дописывать туда номер сборки нечем — он не хранится нигде и после
    пересборки того же кода стал бы другим.
    """
    a, b, c = version.split(".")
    quad = f"({a}, {b}, {c}, 0)"
    return f'''# Сгенерировано scripts/sync_version.py из bot/app/engine.py. Не править руками.
VSVersionInfo(
  ffi=FixedFileInfo(filevers={quad}, prodvers={quad}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable(
        "040904B0",
        [StringStruct("CompanyName", "{COMPANY}"),
         StringStruct("FileDescription", "{DESCRIPTION}"),
         StringStruct("FileVersion", "{version}"),
         StringStruct("InternalName", "DentPilot"),
         StringStruct("OriginalFilename", "DentPilot.exe"),
         StringStruct("ProductName", "{PRODUCT}"),
         StringStruct("ProductVersion", "{version}"),
         StringStruct("LegalCopyright", "{COPYRIGHT}")])]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])])
  ]
)
'''


def package_version() -> str:
    return json.loads(PACKAGE.read_text(encoding="utf-8")).get("version", "")


def check() -> list[str]:
    """Расхождения словами. Пустой список — всё сходится."""
    v = app_version()
    bad = []
    if package_version() != v:
        bad.append(f"frontend/package.json: {package_version()!r}, а в engine.py {v!r}")
    # ⚠️ Отсутствие ресурса — НЕ расхождение: `build\` в .gitignore, и на
    # чистом клоне его нет по замыслу. Его делает сборка (Build-Desktop.ps1
    # зовёт этот же скрипт первым шагом). Красным здесь он был бы красным
    # ВСЕГДА в CI — а сторож, краснеющий на ровном месте, перестают читать.
    if VERSION_FILE.exists() and VERSION_FILE.read_text(encoding="utf-8") != version_info(v):
        bad.append(f"{VERSION_FILE.relative_to(ROOT)} описывает не {v}")
    return bad


def write() -> str:
    v = app_version()
    pkg = json.loads(PACKAGE.read_text(encoding="utf-8"))
    if pkg.get("version") != v:
        # ⚠️ Правим ОДНО поле текстом, а не перезаписываем json.dumps: порядок
        # ключей и отступы package.json читает и человек, и npm-инструменты.
        raw = PACKAGE.read_text(encoding="utf-8")
        raw = re.sub(r'("version"\s*:\s*")[^"]+(")', rf'\g<1>{v}\g<2>', raw, count=1)
        PACKAGE.write_text(raw, encoding="utf-8")
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(version_info(v), encoding="utf-8")
    return v


def main() -> int:
    # ⚠️ Переключение вывода — ТОЛЬКО при запуске из консоли, не при импорте.
    # Модуль импортируют `dev check` и набор проверок, и там stdout бывает
    # подменён StringIO: у него нет `reconfigure`, и импорт падал бы
    # AttributeError — то есть библиотечная строка роняла бы чужой прогон.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="только проверить; красное = номера разошлись")
    args = ap.parse_args()
    if args.check:
        bad = check()
        for b in bad:
            print(f"  [!!]  {b}")
        if not bad:
            print(f"  [ок]  версия всюду одна: {app_version()}")
        return 1 if bad else 0
    v = write()
    print(f"  [ок]  версия разослана из engine.py: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
