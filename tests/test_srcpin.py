# -*- coding: utf-8 -*-
"""P2, экран раздвоения: подтверждение ИСТОЧНИКА его собственным PIN.

Контракт — `docs/dentpilot-2/split-contract.md` › «Чем подтверждается выбор».
Проверяется здесь не «пускает ли верный PIN» — это самая простая половина.
Проверяется ВТОРАЯ: что источник после проверки побайтно тот же, каким его
нашли. ⚠️ И особенно при УДАЧЕ: `verify_pin` при удачной проверке молча
переписывает auth.json v1 → v2, и позвать его против чужого корня значило бы
изменить корень, который мы ещё даже не решили копировать.

⭐ Порядок снимка ровно тот, что задан на словах: снимок ДО → проверка →
снимок ПОСЛЕ → совпадение байт в байт. Размер, время правки в наносекундах и
sha256 содержимого — плюс сам набор путей, иначе новый файл рядом остался бы
незамеченным.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app.core import auth  # noqa: E402
from harness import Result  # noqa: E402


def _snapshot(root: pathlib.Path) -> dict:
    """Дерево целиком: путь → (размер, время правки, sha256). И сами папки —
    иначе пустой каталог, созданный по дороге, не был бы замечен."""
    out: dict = {}
    for dirpath, _dirs, files in os.walk(root):
        out["dir:" + os.path.relpath(dirpath, root)] = None
        for f in files:
            fp = pathlib.Path(dirpath) / f
            st = fp.stat()
            out["file:" + os.path.relpath(fp, root)] = (
                st.st_size, st.st_mtime_ns,
                hashlib.sha256(fp.read_bytes()).hexdigest())
    return out


def _diff(before: dict, after: dict) -> str:
    """Чем именно разошлись снимки — чтобы красная проверка называла файл."""
    gone = sorted(set(before) - set(after))
    born = sorted(set(after) - set(before))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    parts = []
    if born:
        parts.append("появилось: " + ", ".join(born))
    if gone:
        parts.append("исчезло: " + ", ".join(gone))
    if changed:
        parts.append("изменилось: " + ", ".join(changed))
    return "; ".join(parts) or "содержимое"


def _root_v2(p: pathlib.Path, pins: dict[str, str]) -> pathlib.Path:
    """Корень с auth.json формата v2 — ровно такого, какой пишет программа.

    ⭐ Поля считает `_secret_fields`, тот же код, что и при установке PIN: своя
    формула в фикстуре означала бы, что набор проверяет не тот файл, который
    клиника носит на диске.
    """
    (p / "data").mkdir(parents=True, exist_ok=True)
    (p / "data" / "dental.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
    users = [{"id": uid, "role": auth.ROLE_DIRECTOR, "name": uid,
              **auth._secret_fields(pin)} for uid, pin in pins.items()]
    (p / "data" / "auth.json").write_text(
        json.dumps({"v": 2, "cookie_key": "c0ffee" * 10, "users": users}, indent=1),
        encoding="utf-8")
    return p


def _root_v1(p: pathlib.Path, pin: str) -> pathlib.Path:
    """Корень клиники, не входившей после обновления 08-06: формат v1.

    ⛔ Самый опасный случай во всём наборе. Именно его `verify_pin` при УДАЧЕ
    переписывает в v2 — и переписал бы источник, оставив после «просто
    проверки» другой файл и другой ключ подписи сессий.
    """
    (p / "data").mkdir(parents=True, exist_ok=True)
    (p / "data" / "dental.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
    salt = "5a1751a1751a5a17"
    (p / "data" / "auth.json").write_text(
        json.dumps({"salt": salt,
                    "hash": auth._derive(pin, salt, auth.KDF_LEGACY, 1)}),
        encoding="utf-8")
    return p


def _dest(p: pathlib.Path) -> auth.SourcePinAttempts:
    """Назначение — там, где писать МОЖНО. Рядом кладётся auth_fail.json со
    своим счётчиком: он принадлежит входу в журнал и трогать его нельзя."""
    p.mkdir(parents=True, exist_ok=True)
    (p / "auth_fail.json").write_text(json.dumps({"fails": 3, "until": 0}),
                                      encoding="utf-8")
    return auth.SourcePinAttempts(p)


def _verify(src, pin, attempts) -> dict:
    return asyncio.run(auth.verify_source_pin(src, pin, attempts))


def suite_verify(res: Result) -> None:
    """Сам оракул: подходит — не подходит, в обоих форматах файла."""
    with tempfile.TemporaryDirectory(prefix="dp_srcpin_") as td:
        root = pathlib.Path(td)
        src = _root_v2(root / "old", {"dir": "4321", "reg": "9876"})
        att = _dest(root / "new")

        v = _verify(src, "4321", att)
        res.check("верный PIN директора подтверждает источник",
                  v["outcome"], auth.SRC_OK)
        res.ok("и это ok", v["ok"] is True, f"{v!r}")

        res.check("PIN второго сотрудника — тоже источник",
                  _verify(src, "9876", att)["outcome"], auth.SRC_OK)

        v = _verify(src, "1111", att)
        res.check("чужой PIN не подтверждает", v["outcome"], auth.SRC_BAD)
        res.ok("и это НЕ ok", v["ok"] is False, f"{v!r}")

        # ⛔ Подтверждается ПРОИСХОЖДЕНИЕ, а не личность: вердикт не должен
        # нести запись вошедшего — иначе он станет вторым входом в журнал по
        # файлу из корня, который ещё не признан настоящим.
        got = _verify(src, "4321", att)
        res.ok("вердикт не несёт ни имени, ни роли, ни sid",
               not ({"id", "role", "sid", "name", "hash", "salt"} & set(got)),
               f"в вердикте лишнее: {sorted(got)}")

        old = _root_v1(root / "v1", "5555")
        res.check("клиника с прошлой версии: v1 подтверждается",
                  _verify(old, "5555", att)["outcome"], auth.SRC_OK)
        res.check("и чужой PIN к v1 не подходит",
                  _verify(old, "5556", att)["outcome"], auth.SRC_BAD)


def suite_untouched(res: Result) -> None:
    """⛔ Главное свойство: источник после проверки побайтно тот же.

    Обе половины, и вторая важнее первой: при НЕУДАЧЕ писать в источник нечего
    и по случайности, а при УДАЧЕ существующая проверка как раз мигрирует файл.
    """
    with tempfile.TemporaryDirectory(prefix="dp_srcro_") as td:
        root = pathlib.Path(td)
        att = _dest(root / "new")

        for name, mk, good, bad in (
                ("v2", lambda p: _root_v2(p, {"dir": "4321"}), "4321", "0000"),
                ("v1", lambda p: _root_v1(p, "5555"), "5555", "0000")):
            src = mk(root / name)

            before = _snapshot(src)
            v = _verify(src, good, att)
            after = _snapshot(src)
            res.check(f"{name}: PIN подошёл", v["outcome"], auth.SRC_OK)
            res.ok(f"{name}: после УДАЧНОЙ проверки источник байт в байт тот же",
                   before == after, _diff(before, after))

            before = _snapshot(src)
            v = _verify(src, bad, att)
            after = _snapshot(src)
            res.check(f"{name}: PIN не подошёл", v["outcome"], auth.SRC_BAD)
            res.ok(f"{name}: после НЕУДАЧНОЙ проверки источник байт в байт тот же",
                   before == after, _diff(before, after))

            # ⭐ Отдельной строкой то, чего снимок не называет вслух: формат
            # файла остался прежним. Снимок это ловит, но красная строка
            # «изменилось: file:data\\auth.json» не объясняет, ЧТО случилось.
            rec = json.loads((src / "data" / "auth.json").read_text(encoding="utf-8"))
            res.check(f"{name}: формат auth.json не мигрировал",
                      rec.get("v"), 2 if name == "v2" else None)
            res.ok(f"{name}: счётчика попыток в источнике нет",
                   not (src / "data" / auth.SRC_FAIL_NAME).exists()
                   and not (src / "data" / "auth_fail.json").exists(),
                   "оракул завёл своё состояние в чужом корне")


def suite_no_auth(res: Result) -> None:
    """⛔ Нечем подтвердить — это ОСТАНОВКА. Не пропуск и не запасной путь."""
    with tempfile.TemporaryDirectory(prefix="dp_srcna_") as td:
        root = pathlib.Path(td)
        att = _dest(root / "new")

        bare = root / "bare"
        (bare / "data").mkdir(parents=True)
        (bare / "data" / "dental.db").write_bytes(b"SQLite format 3\x00")
        v = _verify(bare, "4321", att)
        res.check("источник без auth.json: исход назван", v["outcome"],
                  auth.SRC_NO_AUTH)
        res.ok("это остановка", v["stop"] is True and v["ok"] is False, f"{v!r}")
        # ⚠️ И попытку это не жжёт: человек ничего не угадывал, угадывать нечего.
        res.check("попытка не засчитана", att.fails(), 0)

        broken = root / "broken"
        (broken / "data").mkdir(parents=True)
        (broken / "data" / "auth.json").write_text('{"v": 2, "users": [',
                                                   encoding="utf-8")
        v = _verify(broken, "4321", att)
        res.check("битый auth.json — СВОЙ исход, а не «PIN не ставили»",
                  v["outcome"], auth.SRC_BROKEN)
        res.ok("тоже остановка", v["stop"] is True, f"{v!r}")

        empty = root / "empty"
        (empty / "data").mkdir(parents=True)
        (empty / "data" / "auth.json").write_text(
            json.dumps({"v": 2, "cookie_key": "k", "users": []}), encoding="utf-8")
        v = _verify(empty, "4321", att)
        res.check("файл читается, а учёток нет", v["outcome"], auth.SRC_NO_USERS)
        res.ok("и это остановка", v["stop"] is True, f"{v!r}")

        # ⛔ Ни один из трёх исходов не подтверждает источник ПУСТЫМ PIN.
        res.ok("пустой PIN ничего не подтверждает",
               all(_verify(p, "", att)["ok"] is False
                   for p in (bare, broken, empty)), "пустой PIN прошёл")

        # ⛔ И ни один не оставил следа в источнике — ни .tmp, ни счётчика.
        res.ok("остановка ничего не создала в источнике",
               all(not any(x.name.startswith(("auth_fail", "srcpin"))
                           for x in (p / "data").iterdir())
                   for p in (bare, broken, empty)),
               "в остановленном источнике появился файл")


def suite_counter(res: Result) -> None:
    """Счётчик попыток: своя лестница в НАЗНАЧЕНИИ, чужие счётчики не тронуты."""
    with tempfile.TemporaryDirectory(prefix="dp_srccnt_") as td:
        root = pathlib.Path(td)
        src = _root_v2(root / "old", {"dir": "4321"})
        dest = root / "new"
        att = _dest(dest)

        res.check("до первой ошибки счётчик пуст", att.fails(), 0)
        _verify(src, "0000", att)
        res.check("неудача засчитана", att.fails(), 1)
        res.ok("состояние легло в назначение",
               (dest / auth.SRC_FAIL_NAME).exists(),
               f"нет {dest / auth.SRC_FAIL_NAME}")

        # ⛔ Счётчик входа в журнал — ЧУЖОЙ. Общий означал бы, что перебор на
        # экране миграции закрывает вход клинике, которая в эту минуту
        # принимает: при `split` назначение — рабочая картотека.
        res.check("auth_fail.json назначения не тронут",
                  json.loads((dest / "auth_fail.json").read_text(
                      encoding="utf-8")).get("fails"), 3)

        # Лестница та же, что у входа: счётчик доводится напрямую, чтобы набор
        # не платил задержкой за каждую из пяти неудач.
        for _ in range(3):
            att.count_fail()
        res.check("накоплено четыре", att.fails(), 4)
        v = _verify(src, "0000", att)
        res.check("пятая закрывает", v["lock_left"] > 0, True)
        res.check("и ступень та же, что у входа", v["lock_left"],
                  auth._lock_for(5))

        # ⭐ Блокировка сильнее ВЕРНОГО PIN — и это же доказывает, что источник
        # в закрытом состоянии вообще не спрашивают.
        v = _verify(src, "4321", att)
        res.check("закрыто даже для верного PIN", v["outcome"], auth.SRC_LOCKED)
        res.ok("и осталось сколько-то секунд", v["lock_left"] > 0, f"{v!r}")

        # ⚠️ Снимаем блокировку руками: ждать полминуты в прогоне незачем.
        auth._state_write(att.path, {"fails": 4, "until": 0})
        v = _verify(src, "4321", att)
        res.check("после снятия верный PIN проходит", v["outcome"], auth.SRC_OK)
        res.check("удача обнуляет счётчик", att.fails(), 0)


def suite_guard(res: Result) -> None:
    """⛔ Счётчик внутри источника — ошибка ГРОМКАЯ, а не тихий лишний файл."""
    with tempfile.TemporaryDirectory(prefix="dp_srcg_") as td:
        root = pathlib.Path(td)
        src = _root_v2(root / "old", {"dir": "4321"})

        raised = ""
        try:
            _verify(src, "4321", auth.SourcePinAttempts(src / "data"))
        except ValueError as e:
            raised = str(e)
        res.ok("состояние внутри источника отвергнуто", bool(raised),
               "счётчик приняли внутрь источника — copy-only сломан молча")
        res.ok("и в отказе назван путь", str(src) in raised, raised)
        res.ok("файла в источнике всё равно не появилось",
               not (src / "data" / auth.SRC_FAIL_NAME).exists(),
               "проверка успела записать до отказа")

        # ⭐ Папка обязана быть названа явно: `SourcePinAttempts()` без неё не
        # существует, потому что «сам знаю, куда писать» — это и есть ловушка
        # `note_fail`, из-за которой понадобился отдельный оракул.
        raised = ""
        try:
            auth.SourcePinAttempts(None)
        except (ValueError, TypeError) as e:
            raised = str(e)
        res.ok("счётчик без папки назначения не создаётся", bool(raised),
               "место записи осталось подразумеваемым")
