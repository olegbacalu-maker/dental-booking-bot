# -*- coding: utf-8 -*-
"""P3-min ступень 1: происхождение старой установки и намерение установщика.

⭐ Проверяется не «находит ли», а ПОРЯДОК доверия: кандидата называет только
источник, содержимое его подтверждает. Обратный порядок небезопасен — разбор
в `docs/dentpilot-2/storage.md` › «P3-min v1».
"""
from __future__ import annotations

import json
import os
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


def suite_shortcut_places(res: Result) -> None:
    """ГДЕ модуль ищет ярлыки — и почему общих мест теперь два.

    ⛔ Не косметика. `[Icons]` нового установщика исполняется от админа, значит
    `{autoprograms}`/`{autodesktop}` резолвятся в `%ProgramData%\\Microsoft\\…`
    и `%PUBLIC%\\Desktop`. Пока этих путей тут не было, детекция была слепа
    ровно к тому, что мы отгружаем СЕГОДНЯ, — и молча: список без них не
    краснеет, он просто ничего не находит.
    """
    keep = {k: os.environ.get(k) for k in
            ("USERPROFILE", "APPDATA", "PUBLIC", "ProgramData", "ALLUSERSPROFILE")}
    try:
        os.environ["USERPROFILE"] = r"X:\u"
        os.environ["APPDATA"] = r"X:\u\AppData\Roaming"
        os.environ["PUBLIC"] = r"X:\Public"
        os.environ["ProgramData"] = r"X:\PD"
        os.environ.pop("ALLUSERSPROFILE", None)
        got = [str(p) for p in legacy.shortcut_paths()]
        os.environ.pop("ProgramData", None)
        os.environ["ALLUSERSPROFILE"] = r"X:\PD"
        fallback = [str(p) for p in legacy.shortcut_paths()]
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    menu = r"Microsoft\Windows\Start Menu\Programs\DentPilot.lnk"
    for want, why in (
            (r"X:\u\Desktop\DentPilot.lnk", "свой стол"),
            (r"X:\u\AppData\Roaming\%s" % menu, "своё меню «Пуск»"),
            (r"X:\u\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
             r"\Startup\DentPilot.lnk", "своя автозагрузка (Install-DentPilot.ps1)"),
            (r"X:\Public\Desktop\DentPilot.lnk", "ОБЩИЙ стол — {autodesktop} от админа"),
            (r"X:\PD\%s" % menu, "ОБЩЕЕ меню — {autoprograms} от админа"),
    ):
        res.ok(f"ищем ярлык: {why}", want in got, f"нет в {got!r}")

    res.ok("общей автозагрузки в списке НЕТ",
           not any(g.startswith(r"X:\PD") and "Startup" in g for g in got),
           "туда не пишет ни установщик, ни Install-DentPilot.ps1: путь, по "
           "которому ничто не создаёт ярлыка, зеленел бы сам по себе")
    res.ok("ProgramData нет — берётся ALLUSERSPROFILE",
           r"X:\PD\%s" % menu in fallback, f"вернулось {fallback!r}")


def suite_program_only(res: Result) -> None:
    """⛔ Папка программы без картотеки — НЕ старая установка.

    Прямой случай сегодняшней машины: общий ярлык ведёт в
    `C:\\Program Files\\DentPilot`, где лежат exe и `unins000.dat`, а данные —
    в `%ProgramData%`. Считай мы маркеры программы подтверждением, P2 получил
    бы корнем переезда СВОЮ ЖЕ установку. Проверка появилась вместе с общими
    ярлыками: до них этот ярлык был просто не виден.
    """
    with tempfile.TemporaryDirectory(prefix="dp_prog_") as td:
        root = pathlib.Path(td)
        new = root / "Program Files" / "DentPilot"
        new.mkdir(parents=True)
        (new / "DentPilot.exe").write_bytes(b"MZ")
        (new / "unins000.dat").write_bytes(b"Inno Setup Uninstall Log (b) 64-bit")
        lnk = root / "common.lnk"
        lnk.write_bytes(_lnk(str(new / "DentPilot.exe")))

        got = legacy.detect([lnk], exclude=[])
        res.check("установка без картотеки не подтверждена", got["reason"],
                  "unconfirmed")
        res.ok("и корнем переезда не названа", got["path"] is None,
               f"назвали {got['path']!r} — P2 переносил бы программу в себя")
        res.ok("но найденное человеку показано",
               "DentPilot.exe" in got["markers"],
               f"markers={got['markers']!r}: разница между «пусто» и «программа "
               "есть, картотеки нет» потеряна, а решать по ней человеку")
        res.ok("маркеры программы подтверждением не считаются",
               not legacy.carries_data(["DentPilot.exe", "unins000.dat"]),
               "exe и деинсталлятор несёт любая установка")
        for m in legacy.MARKERS_DATA:
            res.ok(f"а маркер данных — считается: {m}", legacy.carries_data([m]), "")

        # ⭐ та же папка, но с картотекой рядом, — это и есть старая раскладка
        (new / "clinic.json").write_text("{}", encoding="utf-8")
        got = legacy.detect([lnk], exclude=[])
        res.ok("появилась картотека рядом — старая раскладка найдена",
               got["found"] and got["path"] == new, f"вернулось {got!r}")


def suite_self(res: Result) -> None:
    """⛔ Себя самого источником переезда не называем.

    Случай не выдуманный: в portable-раскладке (`portable.flag` рядом с exe)
    папка данных и есть папка программы, а ярлык на неё создаём мы сами.
    Без исключения P2 получил бы задание «перенеси из X в X».
    """
    with tempfile.TemporaryDirectory(prefix="dp_self_") as td:
        root = pathlib.Path(td)
        here = _install(root / "DentPilot")
        lnk = root / "self.lnk"
        lnk.write_bytes(_lnk(str(here / "DentPilot.exe")))

        res.ok("без исключения такая папка находится (иначе проверка пуста)",
               legacy.detect([lnk], exclude=[])["found"], "")
        got = legacy.detect([lnk], exclude=[here])
        res.check("свой корень — отдельный исход", got["reason"], "self")
        res.ok("и он не назначен", got["path"] is None,
               f"назвали {got['path']!r} — копировали бы папку внутрь неё самой")

        # ⚠️ сравнение путей: ни регистр, ни «..» не делают из своего чужой
        sneaky = pathlib.Path(str(here).upper()) / ".." / here.name
        res.check("тот же корень через «..» и в другом регистре — всё ещё свой",
                  legacy.detect([lnk], exclude=[sneaky])["reason"], "self")

        # ⭐ умолчание берётся у paths.data_root(), а не заводится второй раз
        keep = os.environ.get("DENTART_DATA_DIR")
        os.environ["DENTART_DATA_DIR"] = str(here)
        try:
            res.check("умолчание = папка данных, названная лаунчером",
                      legacy.detect([lnk])["reason"], "self")
        finally:
            if keep is None:
                os.environ.pop("DENTART_DATA_DIR", None)
            else:
                os.environ["DENTART_DATA_DIR"] = keep


def suite_human(res: Result) -> None:
    """Путь, НАЗВАННЫЙ человеком, — второй источник v1.

    ⭐ Заведён не для полноты: 21.09 на стенде `detect()` вернул `no-origin`
    при живой картотеке — ярлыки сняты вместе с программой, а папка
    переименована человеком в `DentPilot.hold`. Переименование не предсказывает
    ни одно правило, поэтому источником и становится человек.
    ⛔ Но подтверждения содержимым он НЕ отменяет.
    """
    with tempfile.TemporaryDirectory(prefix="dp_human_") as td:
        root = pathlib.Path(td)
        hold = _install(root / "Public" / "DentPilot.hold")

        res.check("без человека на такой машине — no-origin",
                  legacy.detect([], exclude=[])["reason"], "no-origin")

        got = legacy.detect([], named=str(hold), exclude=[])
        res.ok("человек назвал — папка найдена",
               got["found"] and got["path"] == hold, f"вернулось {got!r}")
        res.check("и источник назван честно", got["origin"], legacy.ORIGIN_HUMAN)

        # ⚠️ путь из копипаста приезжает в кавычках и с пробелом
        res.ok("кавычки и пробелы сняты",
               legacy.detect([], named=f'  "{hold}" ', exclude=[])["found"],
               "путь из проводника не разобрался")

        empty = root / "pusto"
        empty.mkdir()
        got = legacy.detect([], named=str(empty), exclude=[])
        res.check("названа пустая папка — unconfirmed, а не «нашли»",
                  got["reason"], "unconfirmed")
        res.ok("и она не назначена", got["path"] is None,
               f"назвали {got['path']!r} — человек назвал МЕСТО, а не картотеку")

        # ⚠️ относительный путь места не называет: ответ зависел бы от cwd
        res.check("относительный путь источником не становится",
                  legacy.detect([], named="DentPilot", exclude=[])["reason"],
                  "no-origin")

        # ⭐ порядок доверия: человек впереди ярлыка
        other = _install(root / "Public" / "DentPilot")
        lnk = root / "l.lnk"
        lnk.write_bytes(_lnk(str(other / "DentPilot.exe")))
        got = legacy.detect([lnk], named=str(hold), exclude=[])
        res.ok("человек важнее ярлыка",
               got["path"] == hold and got["origin"] == legacy.ORIGIN_HUMAN,
               f"вернулось {got!r} — ярлык перебил человека")


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

        # ⛔ BOM. Установщик писал файл через SaveStringsToUTF8File, тот ставит
        # BOM, и разбор JSON падал на ПЕРВОМ символе — программа поднималась с
        # окном об ошибке вместо канала. Поймано только живой установкой 21.09:
        # ни компиляция `ISCC`, ни разбор текста `.iss`, ни прогон кодировку
        # готового файла не видят. Чинится с ДВУХ сторон — установщик пишет без
        # BOM, а чтение его терпит: файл может открыть Блокнот.
        install_info.path(root).write_bytes(
            b"\xef\xbb\xbf" + json.dumps({"channel": "beta"}).encode("utf-8"))
        got = install_info.read(root)
        res.ok("файл с BOM читается, а не роняет запуск",
               got is not None and got["channel"] == "beta", f"вернулось {got!r}")

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
