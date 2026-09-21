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

Источников в v1 **три**, и порядок здесь — порядок ДОВЕРИЯ:

* `human` — путь, НАЗВАННЫЙ человеком. Без него детекция слепа на машине, где
  папку однажды передвинули: ярлыки сняты вместе со старой программой, а
  переименование не предсказывает ни одно правило. Проверено на стенде 21.09 —
  `detect()` вернул `no-origin` при живой картотеке в
  `C:\\Users\\Public\\DentPilot.hold`. Человек не ослабляет правило
  «происхождение доказывает место», он самый авторитетный его случай.
* `self` — папка, из которой ЗАПУЩЕН сам процесс (решение Олега 21.09).
  ⭐ Это не содержимое каталога и не эвристика, а **происхождение процесса**:
  программе не нужно спрашивать «нет ли где-нибудь подозрительной папки», она
  уже знает, откуда её запустили. Закрывает дыру, которой не закрывает ничто
  другое: одноклик-обновление подменяет exe НА МЕСТЕ и перезапускает его из
  планировщика, то есть в чистом окружении без `$DENTART_DATA_DIR`, —
  установщик при этом не зовётся вовсе и отказать не может.
  ⛔ И ровно поэтому `self` НОМИНИРУЕТ, но ничего не решает: дальше тот же
  контракт — отпечаток, маркеры данных, решение. Автоматической миграции по
  факту «я отсюда запущен» нет.
* `shortcut` — ярлыки, которые кладём мы сами: свои И общие
  (`shortcut_paths()`).

⚠️ Источник `install` (`install.json` называет корень) назван Олегом в том же
решении, но в v1 НЕ реализован, и это не забывчивость. Файл пишет только новый
установщик, а он поверх старой раскладки ставиться отказывается — значит
старый корень он не назовёт никогда; называет он ДРУГОЕ, папку назначения.
Источником он станет в тот день, когда установщик начнёт записывать то, что
нашёл `LegacyDir()`, — вместе со сценарием и проверкой, как и все остальные.

⛔ **Подтверждает папку только маркер ДАННЫХ** (`MARKERS_DATA`). `DentPilot.exe`
и `unins000.dat` несёт и СЕГОДНЯШНЯЯ установка в `Program Files`, где данных
нет вовсе, — а её ярлык лежит ровно там, куда этот модуль теперь смотрит.
Принимай мы маркеры программы за подтверждение, P2 поехал бы переносить
программу саму в себя. Старую раскладку определяет одно: картотека лежит
РЯДОМ с exe.

⛔ **Папка НАЗНАЧЕНИЯ кандидатом не становится** (`anchor_roots()`): в
portable-раскладке папка данных и есть папка программы, и без этого `self`
назвал бы источником переезда ту самую папку, в которую мы переезжаем, — P2
получил бы «перенеси из X в X».

⛔ **RESERVED, в v1 не реализовано:** запущенный процесс, профили других
пользователей (перебор `ProfileList` в реестре), чужие `AppData`, ярлыки
других учёток, WMI, ключ деинсталляции в реестре, поиск по диску. Причины — в
storage.md. Добавлять по одному, вместе со сценарием реальной клиники и
проверкой к нему; не «на всякий случай».

⚠️ Модуль предзагрузочного слоя: из проекта импортируется только `paths` —
тот же слой и ЕДИНСТВЕННЫЙ владелец `$DENTART_DATA_DIR`. Разбирать переменную
здесь во второй раз значило бы завести второе место, где это знание живёт.
"""
from __future__ import annotations

import os
import pathlib
import struct
import sys

from . import paths

# Имя программы, чей ярлык ищем. ⚠️ Совпадает с именем ассета обновления и с
# тем, что кладёт установщик, — но это РАЗНЫЕ знания, и связывать их импортом
# нельзя: этот модуль живёт до сборки приложения.
EXE_NAME = "DentPilot.exe"
LNK_NAME = "DentPilot.lnk"

# Маркеры ДАННЫХ: ими папка доказывает, что картотека лежит В НЕЙ. Только они
# подтверждают старую раскладку.
MARKERS_DATA = ("clinic.json", "dental.env", os.path.join("data", "dental.db"))
# Маркеры ПРОГРАММЫ: их несёт любая установка, включая сегодняшнюю. Полезны
# отчёту человеку («программа там есть, картотеки нет»), но не подтверждают.
MARKERS_PROGRAM = (EXE_NAME, "unins000.dat")
# Ни один из них не НАЗНАЧАЕТ — назначает источник происхождения.
MARKERS = MARKERS_DATA + MARKERS_PROGRAM

ORIGIN_HUMAN = "human"
ORIGIN_SELF = "self"
ORIGIN_SHORTCUT = "shortcut"


def _key(p: pathlib.Path | str) -> str:
    """ОДИН способ сравнивать пути на весь модуль.

    ⚠️ Две разные ловушки в одной строке. NTFS регистронезависим, а Python
    сравнивает строки побайтно. И «..» внутри пути разворачивает Windows при
    ОТКРЫТИИ, а не при разборе — 21.09 такой путь доехал до экрана установщика
    как `C:\\Users\\Public\\Documents\\..\\DentPilot`; сравнение его с той же
    папкой без «..» дало бы «разные».
    """
    return os.path.normcase(os.path.normpath(str(p))).rstrip("\\/")


def shortcut_paths() -> list[pathlib.Path]:
    """Места, где ярлык создаём МЫ САМИ: три у текущего пользователя и два общих.

    ⭐ Общие добавлены 21.09, и это не «на всякий случай». Новый установщик
    работает от админа, поэтому `{autoprograms}`/`{autodesktop}` в
    `DentPilot.iss` резолвятся в ОБЩИЕ папки (`%ProgramData%\\Microsoft\\…`,
    `%PUBLIC%\\Desktop`). Без них утверждение «ярлык есть у каждого пути
    установки, который мы отгружаем» перестало быть верным для того, что мы
    отгружаем СЕГОДНЯ. Пользовательские нужны по-прежнему: их кладут прежний
    установщик и `Install-DentPilot.ps1`.

    ⚠️ Общей автозагрузки здесь НЕТ намеренно: туда не пишет ни установщик, ни
    `Install-DentPilot.ps1`. Путь, по которому ничто не создаёт ярлыка, — не
    источник, а строка, которая зеленеет сама по себе.
    ⛔ Чужие пользовательские ярлыки остаются резервом: это перебор профилей.
    """
    out = []
    home = os.environ.get("USERPROFILE", "")
    if home:
        out.append(pathlib.Path(home) / "Desktop" / LNK_NAME)
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        base = pathlib.Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        out += [base / LNK_NAME, base / "Startup" / LNK_NAME]
    public = os.environ.get("PUBLIC", "")
    if public:
        out.append(pathlib.Path(public) / "Desktop" / LNK_NAME)
    common = os.environ.get("ProgramData", "") or os.environ.get("ALLUSERSPROFILE", "")
    if common:
        out.append(pathlib.Path(common) / "Microsoft" / "Windows" / "Start Menu"
                   / "Programs" / LNK_NAME)
    return out


def running_root() -> pathlib.Path | None:
    """Папка, из которой запущен САМ процесс, — источник `self`.

    ⭐ Происхождение процесса, а не содержимое папки: программа не ищет, она
    знает. Единственный источник, доживающий до одноклик-обновления — там exe
    подменён на месте и перезапущен планировщиком, ярлыки ни при чём,
    окружение чистое, а установщик не звался вовсе и отказать не мог.

    ⚠️ Только у СОБРАННОЙ программы. Из исходников `sys.executable` — это
    `python.exe` в `.venv-desktop\\Scripts`, и папка интерпретатора кандидатом
    на переезд картотеки не может быть ни при каких обстоятельствах.
    """
    if not getattr(sys, "frozen", False):
        return None
    return pathlib.Path(sys.executable).resolve().parent


def anchor_roots() -> list[pathlib.Path]:
    """Папка НАЗНАЧЕНИЯ — та, в которую переезжаем. Кандидатом не бывает.

    ⛔ Без этого portable-раскладка (`portable.flag` рядом с exe — данные и
    программа в одной папке) дала бы `self`-кандидата, равного назначению, и
    P2 получил бы «перенеси из X в X», то есть копирование папки внутрь неё
    самой.
    """
    root = paths.data_root()
    return [] if root is None else [root]


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


def origins(shortcuts: list[pathlib.Path] | None = None,
            named: str | pathlib.Path | None = None,
            self_root: pathlib.Path | None = None) -> list[dict]:
    """Кандидаты, НАЗВАННЫЕ источником. Единственный вход в детекцию.

    Возвращает `[{"path": папка, "origin": ..., "source": чем названа}]`,
    без дубликатов, в порядке ДОВЕРИЯ: человек → сам процесс → ярлыки.

    ⭐ Почему человек впереди `self`: человек видит обе папки и знает, какая
    из них картотека, а процесс знает только, откуда его запустили. На машине,
    где старый exe остался рядом со старой базой, а работать надо с новой,
    прав человек.

    ⚠️ `named` — путь, введённый человеком. Не абсолютный отбрасывается: он не
    называет МЕСТО (тот же выбор, что у `paths.data_root()`), а разрешать его
    от текущей папки значило бы отвечать по-разному на один и тот же ввод.
    Кавычки и пробелы по краям снимаются: путь приходит из копипаста.
    ⚠️ `self_root=None` — вычислить самим (`running_root()`); из исходников
    там `None`, поэтому в прогоне источник `self` молчит, пока его не передали
    явно.
    """
    seen: set[str] = set()
    out: list[dict] = []
    if named is not None:
        p = pathlib.Path(str(named).strip().strip("\"'"))
        if p.is_absolute():
            seen.add(_key(p))
            out.append({"path": p, "origin": ORIGIN_HUMAN, "source": p})
    mine = running_root() if self_root is None else pathlib.Path(self_root)
    if mine is not None and _key(mine) not in seen:
        seen.add(_key(mine))
        out.append({"path": mine, "origin": ORIGIN_SELF, "source": mine})
    for lnk in (shortcut_paths() if shortcuts is None else shortcuts):
        target = shortcut_target(lnk)
        if target is None or target.name.lower() != EXE_NAME.lower():
            continue
        folder = target.parent
        key = _key(folder)
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


def carries_data(markers: list[str]) -> bool:
    """Доказывают ли найденные маркеры СТАРУЮ раскладку — картотеку рядом с exe.

    ⛔ Маркеров программы для этого недостаточно, и это не строгость ради
    строгости: сегодняшняя установка в `Program Files` несёт их обе, а данных
    не имеет вовсе.
    """
    return any(m in MARKERS_DATA for m in markers)


def detect(shortcuts: list[pathlib.Path] | None = None,
           named: str | pathlib.Path | None = None,
           exclude: list[pathlib.Path] | None = None,
           self_root: pathlib.Path | None = None) -> dict:
    """Итог: `{"found", "path", "origin", "source", "markers", "reason"}`.

    Четыре исхода, и все четыре названы явно:
      * `found=True`  — источник назвал папку, маркеры ДАННЫХ её подтвердили;
      * `found=False`, `reason="no-origin"` — источников нет вовсе;
      * `found=False`, `reason="unconfirmed"` — источник назвал, но картотеки
        там нет: ярлык на удалённую установку (обычное дело) или ярлык на
        СЕГОДНЯШНЮЮ установку, у которой данные лежат отдельно. В `markers`
        при этом остаётся найденное — человеку нужна разница между «пусто» и
        «программа есть, картотеки нет»;
      * `found=False`, `reason="destination"` — источники назвали только ту
        папку, в которую мы и переезжаем (portable-раскладка).

    ⛔ Пятого исхода «похоже, что вон та папка» не существует и появиться не
    может: перебирается только то, что вернул `origins()`.
    ⭐ `found=True` — это НОМИНАЦИЯ, а не разрешение мигрировать. Дальше по
    контракту идут отпечаток и решение; `origin="self"` тут ничем не
    привилегированнее прочих, хотя и знает про себя больше всех.
    ⚠️ `found=False` НЕ означает «чистая машина». Чистой машина считается по
    положительному признаку, иначе первый же сбой детекции выглядит как новая
    клиника — и программа заводит пустой журнал рядом с живой картотекой.
    """
    skip = {_key(p) for p in (anchor_roots() if exclude is None else exclude)}
    mine = False
    first: dict | None = None
    for c in origins(shortcuts, named, self_root):
        if _key(c["path"]) in skip:
            mine = True
            continue
        markers = confirm(c["path"])
        if carries_data(markers):
            return {"found": True, "path": c["path"], "origin": c["origin"],
                    "source": c["source"], "markers": markers, "reason": "ok"}
        if first is None:
            first = dict(c, markers=markers)
    if first is not None:
        return {"found": False, "path": None, "origin": first["origin"],
                "source": first["source"], "markers": first["markers"],
                "reason": "unconfirmed"}
    return {"found": False, "path": None, "origin": None, "source": None,
            "markers": [], "reason": "destination" if mine else "no-origin"}
