# -*- coding: utf-8 -*-
"""P3-min ступень 1: происхождение старой установки и намерение установщика.

⭐ Проверяется не «находит ли», а ПОРЯДОК доверия: кандидата называет только
источник, содержимое его подтверждает. Обратный порядок небезопасен — разбор
в `docs/dentpilot-2/storage.md` › «P3-min v1».
"""
from __future__ import annotations

import json
import pathlib
import struct
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import install_info, legacy  # noqa: E402
from harness import Result  # noqa: E402


def _lnk(target: str) -> bytes:
    """Минимальный, но НАСТОЯЩИЙ Shell Link на заданный путь.

    ⚠️ Собирается байтами намеренно: писать `.lnk` через COM значило бы тащить
    зависимость в окружение сборки, а копировать чужой ярлык с машины —
    привязать прогон к тому, что на ней сегодня лежит.
    Раскладка: заголовок 76 байт (без IDList), затем LinkInfo с ANSI-путём.
    """
    path_b = target.encode("mbcs") + b"\x00"
    hdr_size = 28                       # без Unicode-полей
    base_off = hdr_size
    suffix_off = base_off + len(path_b)
    li = struct.pack("<IIIIIII",
                     suffix_off + 1,    # LinkInfoSize
                     hdr_size,          # LinkInfoHeaderSize
                     0x1,               # VolumeIDAndLocalBasePath
                     0,                 # VolumeIDOffset (не читаем)
                     base_off,          # LocalBasePathOffset
                     0,                 # CommonNetworkRelativeLinkOffset
                     suffix_off)        # CommonPathSuffixOffset
    li += path_b + b"\x00"
    head = (b"\x4c\x00\x00\x00"
            + b"\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"
            + struct.pack("<I", 0x2)    # LinkFlags: только HasLinkInfo
            + b"\x00" * 52)
    return head + li


def _install(dirpath: pathlib.Path, name: str = "DentPilot.exe") -> pathlib.Path:
    """Папка, ВЫГЛЯДЯЩАЯ как установка: exe, профиль, env, база и деинсталлятор."""
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / name).write_bytes(b"MZ")
    (dirpath / "clinic.json").write_text("{}", encoding="utf-8")
    (dirpath / "dental.env").write_text("ADMIN_KEY=\n", encoding="utf-8")
    (dirpath / "unins000.dat").write_bytes(b"Inno Setup Uninstall Log (b) 64-bit")
    (dirpath / "data").mkdir(exist_ok=True)
    (dirpath / "data" / "dental.db").write_bytes(b"SQLite format 3\x00")
    return dirpath


def suite_origin(res: Result) -> None:
    """Источник называет, содержимое подтверждает."""
    with tempfile.TemporaryDirectory(prefix="dp_legacy_") as td:
        root = pathlib.Path(td)
        install = _install(root / "Public" / "DentPilot")
        links = root / "links"
        links.mkdir()

        # 1-3. каждый из трёх ярлыков в одиночку обязан находить установку
        for label in ("Start Menu", "Desktop", "Startup"):
            p = links / f"{label}.lnk"
            p.write_bytes(_lnk(str(install / "DentPilot.exe")))
            got = legacy.detect([p])
            res.ok(f"ярлык «{label}» находит установку",
                   got["found"] and got["path"] == install,
                   f"вернулось {got!r}")
            res.check(f"ярлык «{label}» — источник назван", got["origin"],
                      legacy.ORIGIN_SHORTCUT)

        # 4. ⛔ файл в произвольной папке НЕ является установкой: на него не
        # указывает ни один ярлык, а содержимое права голоса не имеет
        lonely = _install(root / "gde-to" / "DentPilot")
        got = legacy.detect([])
        res.check("папка без ярлыка не найдена", got["reason"], "no-origin")
        res.ok("папка без ярлыка не названа", got["path"] is None,
               f"назвали {got['path']!r} — содержимое получило право голоса")
        res.ok("но маркеры в ней ЕСТЬ (значит их одних мало)",
               len(legacy.confirm(lonely)) >= 4,
               "проверка бессмысленна: в подопытной папке нет маркеров")

        # 5. ⛔ полная байтовая копия установки — НЕ установка. Настоящий
        # случай: D:\DentProject\backups\pre-clean-install-*
        backup = _install(root / "backups" / "pre-clean-install-2026-08-05")
        res.ok("копия проходит проверку СОДЕРЖИМЫМ",
               len(legacy.confirm(backup)) >= 4,
               "подопытная копия собрана неверно — проверка ничего не значит")
        only_live = links / "Start Menu.lnk"
        got = legacy.detect([only_live])
        res.ok("но установкой копия НЕ считается",
               got["found"] and got["path"] == install and got["path"] != backup,
               f"вернулось {got!r} — миграция переехала бы резервную копию")

        # 8. источник есть, подтверждения нет — отдельный исход, не «нашли»
        gone = links / "gone.lnk"
        gone.write_bytes(_lnk(str(root / "udalili" / "DentPilot.exe")))
        got = legacy.detect([gone])
        res.check("ярлык на удалённую установку", got["reason"], "unconfirmed")
        res.ok("и ничего не назначено", got["path"] is None,
               f"назвали {got['path']!r} — это догадка")

        # ⚠️ мусор вместо ярлыка не должен ни падать, ни угадывать
        junk = links / "junk.lnk"
        junk.write_bytes(b"not a shortcut at all")
        res.ok("битый ярлык — None, без исключения",
               legacy.shortcut_target(junk) is None, "разобрался в мусоре")
        res.ok("несуществующий ярлык — None",
               legacy.shortcut_target(links / "net.lnk") is None, "")


def suite_reserved(res: Result) -> None:
    """9. Резерв обязан ОСТАВАТЬСЯ резервом.

    ⛔ Правило против тихого расползания: решение 20.09 — запущенный процесс,
    WMI и перебор профилей в v1 не реализуем. Если кто-то добавит их «заодно»,
    это должно стать видно здесь, а не у клиники.
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "bot" / "app" / "legacy.py").read_text(encoding="utf-8")
    res.ok("модуль детекции на месте", len(src) > 500, "файл переехал")
    for token, why in (("CreateToolhelp32Snapshot", "перебор процессов"),
                       ("QueryFullProcessImageName", "путь чужого процесса"),
                       ("WbemScripting", "WMI"),
                       ("ProfileList", "перебор профилей Windows"),
                       ("win32com", "COM-зависимость")):
        # ⚠️ ищем ВЫЗОВ, а не упоминание: слово может законно стоять в разборе
        # причин. Отсюда скобка — то, что исчезнет при удалении кода.
        res.ok(f"RESERVED не реализован: {why}", f"{token}(" not in src,
               f"в v1 появился {token} — это отдельное решение, не «заодно»")


def suite_install_info(res: Result) -> None:
    """6-7. Намерение установщика: читается точно, битое — громко."""
    with tempfile.TemporaryDirectory(prefix="dp_ii_") as td:
        root = pathlib.Path(td)

        # ⭐ нет файла — это НЕ ошибка: запуск из исходников, прогон, песочница
        res.ok("нет install.json — None, а не отказ",
               install_info.read(root) is None, "")

        install_info.path(root).write_text(
            json.dumps({"mode": "shared_pc", "channel": "beta"}), encoding="utf-8")
        got = install_info.read(root)
        res.check("режим прочитан", got["mode"], "shared_pc")
        res.check("канал прочитан", got["channel"], "beta")

        install_info.path(root).write_text('{"mode": "standalone"}', encoding="utf-8")
        res.check("канал по умолчанию", install_info.read(root)["channel"], "stable")

        # ⛔ битое и неизвестное — отказ, а не умолчание: молчаливый `stable`
        # на канареечной машине и есть та беда, ради которой файл заведён
        for bad, why in (("{не json", "мусор вместо JSON"),
                         ("[1,2,3]", "не объект"),
                         ('{"mode":"клиника"}', "неизвестный режим"),
                         ('{"channel":"beta "}', "канал с пробелом")):
            install_info.path(root).write_text(bad, encoding="utf-8")
            try:
                install_info.read(root)
                res.ok(f"отказ на «{why}»", False, "прочиталось молча")
            except install_info.InstallInfoError:
                res.ok(f"отказ на «{why}»", True, "")


def suite_channel_seed(res: Result) -> None:
    """Ступень 3: что лаунчер допишет в ТОЛЬКО ЧТО созданный dental.env.

    ⭐ Проверяется чистая функция, потому что тело `desktop.py` тестами
    неимпортируемо: харнесс поднимает `app.main` напрямую и лаунчер не
    исполняет ни строкой. Что вызов стоит В НУЖНОМ МЕСТЕ — держит
    `test_launcher`; что канал доезжает до живой машины — ступень 4.
    """
    res.check("install.json нет — канал не навязываем",
              install_info.channel_line(None), "")
    res.check("stable не пишем: это умолчание продукта",
              install_info.channel_line({"channel": "stable"}), "")
    for chan in ("beta", "draft"):
        line = install_info.channel_line({"channel": chan})
        res.ok(f"канал {chan} доезжает строкой",
               f"DENTART_CHANNEL={chan}\n" in line, f"вернулось {line!r}")
        # ⚠️ Ключ обязан быть тем самым, что читает update._beta(): имя
        # переменной — контракт между установщиком, лаунчером и обновлятором.
        res.ok(f"канал {chan} — ровно тот ключ, что читает обновлятор",
               line.count("DENTART_CHANNEL=") == 1
               and not line.startswith("DENTART_CHANNEL"),
               "строка без пояснения или с лишними ключами: " + repr(line))


def suite_real_shortcuts(res: Result) -> None:
    """Разбор против НАСТОЯЩИХ ярлыков машины, если они есть.

    ⚠️ Пропуск печатается вслух: молчаливый пропуск — это ложное зелёное.
    Синтетические ярлыки выше проверяют правило, этот — формат.
    """
    real = [p for p in legacy.shortcut_paths() if p.exists()]
    if not real:
        res.ok("настоящих ярлыков на машине нет — разбор формата пропущен",
               True, "")
        return
    for p in real:
        t = legacy.shortcut_target(p)
        res.ok(f"настоящий ярлык разобран: {p.parent.name}",
               t is not None and t.name.lower() == "dentpilot.exe",
               f"вернулось {t!r}")
