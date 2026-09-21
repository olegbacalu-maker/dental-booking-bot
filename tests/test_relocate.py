# -*- coding: utf-8 -*-
"""P2, шаги 1–3: Detect → Fingerprint → Decide.

⭐ Проверяется не «переехало ли» — на этих шагах переезжать нечему. Проверяется
ДВА свойства: решение принимается по правильным признакам, и ни один байт при
этом не пишется. Второе проверяется буквально — снимком дерева до и после.
Контракт — `docs/dentpilot-2/migration-contract.md`.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import legacy, relocate  # noqa: E402
from harness import Result  # noqa: E402


def _root(p: pathlib.Path, records: bool = True, enc: bool = False,
          wal: bool = False) -> pathlib.Path:
    """Корень с картотекой (или без неё), как он выглядит на диске."""
    (p / "data").mkdir(parents=True, exist_ok=True)
    if records:
        (p / "clinic.json").write_text("{}", encoding="utf-8")
        (p / "dental.env").write_text("PORT=8088\n", encoding="utf-8")
        head = b"XXXXXXXXXXXXXXXX" if enc else b"SQLite format 3\x00"
        (p / "data" / "dental.db").write_bytes(head + b"\x00" * 100)
        if wal:
            (p / "data" / "dental.db-wal").write_bytes(b"\x00" * 4096)
    return p


def _snapshot(root: pathlib.Path) -> dict:
    """Дерево целиком: путь → (размер, время правки). Для сравнения «до/после»."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            fp = pathlib.Path(dirpath) / f
            st = fp.stat()
            out[str(fp)] = (st.st_size, st.st_mtime_ns)
    return out


def suite_fingerprint(res: Result) -> None:
    """Шаг 2: что известно о корне БЕЗ его открытия."""
    with tempfile.TemporaryDirectory(prefix="dp_fp_") as td:
        root = pathlib.Path(td)
        live = _root(root / "live", wal=True)

        fp = relocate.fingerprint(live)
        res.ok("база найдена", fp["has_db"], f"{fp!r}")
        res.ok("размер снят", fp["db_size"] == 116, f"db_size={fp['db_size']}")
        res.ok("дата снята", fp["db_mtime"] is not None, "")
        res.ok("незашифрованная база опознана по заголовку",
               fp["encrypted"] is False, f"encrypted={fp['encrypted']!r}")
        # ⭐ горячий -wal — НОРМАЛЬНОЕ состояние покоя: лаунчер уходит через
        # os._exit(0), минуя закрытие соединения. Отказывать по нему значило бы
        # отказывать всегда, поэтому он часть полезной нагрузки, а не признак.
        res.ok("-wal замечен и измерен", fp["wal"] == 4096, f"wal={fp['wal']}")
        res.ok("хеш по умолчанию НЕ считается", fp["sha256"] is None,
               "считать хеш всей базы на каждом запуске — плата за вопрос, на "
               "который отвечают размер и дата")
        res.ok("но по требованию считается",
               relocate.fingerprint(live, digest=True)["sha256"] is not None, "")

        enc = _root(root / "enc", enc=True)
        res.ok("зашифрованная база опознана НЕ открытием",
               relocate.fingerprint(enc)["encrypted"] is True,
               "заголовок SQLCipher принят за обычную базу")

        empty = root / "pusto"
        empty.mkdir()
        fp = relocate.fingerprint(empty)
        res.ok("нет базы — так и сказано", fp["has_db"] is False, f"{fp!r}")
        # ⚠️ «не зашифрована» и «её нет» — разные ответы
        res.ok("и это НЕ «не зашифрована»", fp["encrypted"] is None,
               f"encrypted={fp['encrypted']!r} — отсутствие выглядит как факт")
        res.ok("картотеки в пустом корне нет",
               not relocate.carries_records(fp), "")


def suite_decide(res: Result) -> None:
    """Шаг 3: четыре исхода, и «догадаться» среди них нет."""
    with tempfile.TemporaryDirectory(prefix="dp_dec_") as td:
        root = pathlib.Path(td)
        old = _root(root / "Public" / "DentPilot")
        anchor = root / "ProgramData" / "DentPilot"
        anchor.mkdir(parents=True)

        det = legacy.detect([], exclude=[anchor], self_root=old)
        got = relocate.decide(det, anchor)
        res.check("один корень, назначение пусто", got["outcome"], "unique")
        res.check("и только здесь едем", got["action"], "migrate")

        # ⛔ назначение не пусто — выбирает человек, а не программа
        _root(anchor)
        got = relocate.decide(det, anchor)
        res.check("картотека в обоих корнях", got["outcome"], "split")
        res.check("остановка", got["action"], "stop")
        res.ok("и оба корня показаны человеку",
               got["source"]["has_db"] and got["anchor"]["has_db"], f"{got!r}")

        # ⚠️ ⛔ «есть ли там пациенты» для различения НЕПРИГОДНО: клиника,
        # внёсшая неделю работы не в тот корень, не должна получить свою работу
        # отодвинутой как «свежий профиль». Поэтому маркеров достаточно.
        res.ok("разница решается маркерами, а не числом записей",
               relocate.carries_records(relocate.fingerprint(anchor)),
               "только что созданный корень не опознан как непустой")

        # источник назвал, данные не подтвердили
        bare = root / "Program Files" / "DentPilot"
        bare.mkdir(parents=True)
        (bare / "DentPilot.exe").write_bytes(b"MZ")
        det2 = legacy.detect([], exclude=[anchor], self_root=bare)
        got = relocate.decide(det2, anchor)
        res.check("программа есть, картотеки нет", got["outcome"], "unconfirmed")
        res.check("остановка без догадок", got["action"], "stop")

        # не назвал никто
        det3 = legacy.detect([], exclude=[anchor])
        got = relocate.decide(det3, anchor)
        res.check("источников нет вовсе", got["outcome"], "no-origin")
        res.ok("⚠️ и это НЕ «чистая машина»", got["action"] == "stop",
               "молчание детекции принято за разрешение завести пустой журнал")


def suite_blockers(res: Result) -> None:
    """⛔ Незавершённый приказ шифрования останавливает даже идеальный `unique`.

    Печатный лист восстановления клинике уже отдан; переезд поверх приказа
    разошёлся бы с ним, а восстановить картотеку было бы нечем.
    """
    with tempfile.TemporaryDirectory(prefix="dp_blk_") as td:
        root = pathlib.Path(td)
        old = _root(root / "old")
        anchor = root / "new"
        anchor.mkdir()
        det = legacy.detect([], exclude=[anchor], self_root=old)

        res.check("без приказа едем", relocate.decide(det, anchor)["action"],
                  "migrate")
        for order in ("db-key.pending", "db-decrypt.request"):
            p = old / "data" / order
            p.write_text("x", encoding="utf-8")
            got = relocate.decide(det, anchor)
            res.check(f"приказ «{order}» останавливает", got["action"], "stop")
            # ⭐ исход НЕ подменяется: человек должен видеть И что нашли,
            # И почему не поехали
            res.check(f"но находка не стёрта: {order}", got["outcome"], "unique")
            res.ok(f"и причина названа: {order}",
                   any(order in b for b in got["blockers"]), f"{got['blockers']!r}")
            p.unlink()


def suite_read_only(res: Result) -> None:
    """⛔ Главное свойство шагов 1–3: НИ ОДНОГО ЗАПИСАННОГО БАЙТА.

    Проверяется не намерением и не чтением кода, а снимком обоих деревьев до и
    после полного прохода — с размерами и временем правки в наносекундах.
    ⚠️ Особенно это про базу: любое открытие её штатным драйвером закрывалось бы
    checkpoint'ом, а он переписывает главный файл и съедает `-wal`.
    """
    with tempfile.TemporaryDirectory(prefix="dp_ro_") as td:
        root = pathlib.Path(td)
        old = _root(root / "old", wal=True)
        anchor = _root(root / "new")

        before_old, before_new = _snapshot(old), _snapshot(anchor)
        det = legacy.detect([], exclude=[anchor], self_root=old)
        got = relocate.decide(det, anchor)
        relocate.fingerprint(old, digest=True)
        after_old, after_new = _snapshot(old), _snapshot(anchor)

        res.check("проход дошёл до решения", got["outcome"], "split")
        res.ok("старый корень не тронут", before_old == after_old,
               f"изменилось: {set(before_old) ^ set(after_old) or 'содержимое'}")
        res.ok("новый корень не тронут", before_new == after_new,
               f"изменилось: {set(before_new) ^ set(after_new) or 'содержимое'}")
        res.ok("-wal на месте и той же длины",
               (old / "data" / "dental.db-wal").stat().st_size == 4096,
               "checkpoint съел журнал — значит базу кто-то открыл")
        # ⛔ и ни одного нового файла: ни migration.json, ни .tmp, ни копии
        res.ok("новых файлов не появилось",
               len(after_old) == len(before_old) and len(after_new) == len(before_new),
               "шаги 1–3 что-то создали — это уже шаг 4")


def suite_root_for(res: Result) -> None:
    """Из какого корня РАБОТАТЬ запуску, пока шаги 4–8 не написаны.

    ⭐ Правило живёт здесь, а не в лаунчере, ровно потому, что лаунчер прогоном
    не исполняется ни строкой (харнесс поднимает `app.main` напрямую) — прайор
    карты. В `desktop.py` остаётся вызов, и его МЕСТО держит `test_launcher`.

    ⚠️ `shortcuts=[]` во всех вызовах — не формальность. Без него детекция
    читает НАСТОЯЩИЕ ярлыки машины, а на машине разработчика DentPilot
    установлен: проверка «чистая машина» падала на `unconfirmed`, потому что
    видела `C:\\Program Files\\DentPilot`. Поймано этой же проверкой при первом
    прогоне — временная папка не делает набор герметичным, пока код смотрит в
    окружение.
    """
    with tempfile.TemporaryDirectory(prefix="dp_rf_") as td:
        root = pathlib.Path(td)
        old = _root(root / "Public" / "DentPilot")
        anchor = root / "ProgramData" / "DentPilot"
        anchor.mkdir(parents=True)

        # ⛔ Главный случай: одноклик-обновление подменило exe на месте,
        # перезапустило его из планировщика, окружение чистое. Картотека —
        # рядом со старым exe, назначение пусто. Работаем ТАМ, где картотека.
        got, verdict = relocate.root_for(anchor, shortcuts=[], self_root=old)
        res.check("назначение пусто — работаем в старом корне", got, old)
        res.check("и это исход unique", verdict["outcome"], "unique")

        # ⚠️ Приказ шифрования запрещает КОПИРОВАТЬ, а не работать: вместо
        # пустого журнала клиника получила бы закрытую программу.
        (old / "data" / "db-key.pending").write_text("x", encoding="utf-8")
        got, verdict = relocate.root_for(anchor, shortcuts=[], self_root=old)
        res.check("приказ шифрования работу в старом корне не отменяет",
                  got, old)
        res.ok("но в вердикте он назван", verdict["blockers"], "молчком")
        (old / "data" / "db-key.pending").unlink()

        # ⛔ Картотека в обоих — стартуем в назначении, а НЕ отказываем:
        # программа, не открывшаяся из-за спорной находки, закрыла бы клинику
        # на день. Выбор — экран того же класса, что режим восстановления.
        _root(anchor)
        got, verdict = relocate.root_for(anchor, shortcuts=[], self_root=old)
        res.check("раздвоение — стартуем в назначении", got, anchor)
        res.check("и это исход split", verdict["outcome"], "split")

        # ⛔ И самое неочевидное: unconfirmed — НОРМА здоровой установки.
        # Общий ярлык и сам процесс называют папку программы, данных там нет и
        # быть не должно. Останавливать по нему запуск значило бы не пускать в
        # программу каждую правильно установленную клинику.
        pf = root / "Program Files" / "DentPilot"
        pf.mkdir(parents=True)
        (pf / "DentPilot.exe").write_bytes(b"MZ")
        got, verdict = relocate.root_for(anchor, shortcuts=[], self_root=pf)
        res.check("установка без картотеки рядом — это unconfirmed",
                  verdict["outcome"], "unconfirmed")
        res.check("и запуск идёт обычным порядком", got, anchor)

        # чистая машина: никто ничего не назвал
        got, verdict = relocate.root_for(anchor, shortcuts=[], self_root=None)
        res.check("источников нет — корень назначения", got, anchor)
        res.check("исход назван", verdict["outcome"], "no-origin")


def suite_no_drivers(res: Result) -> None:
    """⛔ Сторож полярности: источник не открывается НИКАКИМ драйвером.

    ⚠️ Проверка смотрит на ИСХОДНИК, потому что поведение «не открыл» никаким
    прогоном не докажешь положительно: можно лишь не найти следов. Ищем вызов,
    а не упоминание — слово может законно стоять в разборе причин.
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "bot" / "app" / "relocate.py").read_text(encoding="utf-8")
    res.ok("модуль на месте", len(src) > 500, "файл переехал — проверки ниже пусты")
    for token, why in (("sqlite3.connect", "штатный драйвер"),
                       ("sqlcipher3", "драйвер шифрованной базы"),
                       ("opens_with", "проба ключа из dbkey"),
                       ("shutil.copy", "копирование — это шаг 4"),
                       ("os.replace", "переключение — это шаг 8")):
        res.ok(f"не зовётся: {why}", f"{token}(" not in src,
               f"в шагах 1–3 появился {token} — это другой шаг контракта")
    # ⭐ и наоборот: чем ИМЕННО снимается шифрование, названо явно
    res.ok("шифрование определяется заголовком", "SQLITE_MAGIC" in src,
           "проба заголовка исчезла — значит появился другой способ")
