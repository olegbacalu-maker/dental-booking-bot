# -*- coding: utf-8 -*-
"""P2, шаг 4: экран раздвоения — показать два корня, спросить, записать ответ.

Контракт — `docs/dentpilot-2/split-contract.md`. Три утверждения оттуда, и
проверяются они здесь, а не глазами:

1. при двух картотеках программа СТАРТУЕТ и журнал назначения работает;
2. директор видит сигнал, а страница называет оба корня ФАКТАМИ;
3. до ответа человека оба дерева побайтно неизменны, и `migration.json` не
   создан.

⚠️ И отрицательная сторона, без которой первые три ничего не стоят: набор обязан
краснеть на сломанном коде. Красная половина — в `scripts/check_split_red.py`.

⭐ Снимок дерева тот же, что у `test_srcpin`, и это не копипаста: он ТАМ и
берётся. Второй снимок со своей формулой разошёлся бы с первым молча — и
разошёлся бы ровно в том, чего не проверяет (у слабого варианта нет ни sha256,
ни папок, и подмена файла тем же размером проходит незамеченной).
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import migstate  # noqa: E402
from app.core import auth  # noqa: E402
from harness import PIN, Client, Result, Server  # noqa: E402
from test_srcpin import _diff, _root_v1, _root_v2, _snapshot  # noqa: E402


def _seed(dir_: pathlib.Path, src: pathlib.Path) -> dict:
    """Окружение машины, на которой раздвоение НАЙДЕНО лаунчером.

    ⚠️ `DENTART_DATA_DIR` харнесс не ставит (у него нет лаунчера), а экран без
    него не существует: ответ записывать некуда. Ставим его сами — ровно так,
    как это делает `desktop.py` перед стартом приложения.
    """
    return {"DENTART_DATA_DIR": str(dir_), "DENTART_SPLIT_SOURCE": str(src)}


def suite_state(res: Result) -> None:
    """`migration.json` — граница транзакции: состояний ровно столько, сколько
    разных ответов на вопрос «что делать сейчас»."""
    with tempfile.TemporaryDirectory(prefix="dp_mst_") as td:
        root = pathlib.Path(td)

        st = migstate.state(root)
        res.ok("файла нет — переезд не начинался",
               not st["present"] and not st["broken"] and not st["chosen"], f"{st!r}")
        res.check("и вопрос считается не отвеченным", migstate.settled(root), False)

        migstate.record_choice(root, old="C:\\old", new=str(root),
                               choice=migstate.CHOICE_OLD, at="2026-09-21T12:00:00+03:00")
        st = migstate.state(root)
        res.check("ответ «старый корень» записан", st["chosen"], migstate.CHOICE_OLD)
        res.check("отвергнутый корень назван тоже", st["old"], "C:\\old")
        res.check("и вопрос закрыт", migstate.settled(root), True)
        res.ok("но авторитет НЕ переписан: копия ещё не начиналась",
               st["authoritative"] == "", f"authoritative={st['authoritative']!r}")

        # ⛔ Третьего ответа не существует, и попытка записать его — ошибка,
        # а не молчаливое умолчание.
        raised = ""
        try:
            migstate.record_choice(root, old="a", new="b", choice="merge", at="x")
        except ValueError as e:
            raised = str(e)
        res.ok("ответа «объедини» не существует", bool(raised), "принят третий ответ")

        # Битый файл — СВОЙ исход, и он не равен «файла нет»: иначе следующий
        # запуск предложил бы выбрать заново поверх начатого переезда.
        (root / migstate.NAME).write_text('{"schema": 1, "chosen": ', encoding="utf-8")
        st = migstate.state(root)
        res.ok("битый файл опознан как битый",
               st["present"] and st["broken"] and not st["chosen"], f"{st!r}")
        res.check("и вопрос считается отвеченным", migstate.settled(root), True)

        # Файл из будущей версии — тот же ответ: чужую схему мы не понимаем.
        (root / migstate.NAME).write_text(json.dumps({"schema": 99, "chosen": "old"}),
                                          encoding="utf-8")
        res.check("чужая схема — тоже «не понимаю»", migstate.state(root)["broken"], True)

        # ⛔ Огрызка .tmp после удачной записи не остаётся.
        (root / migstate.NAME).unlink()
        migstate.record_choice(root, old="a", new="b",
                               choice=migstate.CHOICE_NEW, at="t")
        res.ok("огрызок .tmp не остался",
               not (root / (migstate.NAME + ".tmp")).exists(), "мусор рядом с файлом")


def suite_screen(res: Result) -> None:
    """Экран: показывает факты обоих корней и НЕ трогает ни один байт."""
    with tempfile.TemporaryDirectory(prefix="dp_split_") as td:
        root = pathlib.Path(td)
        src = _root_v2(root / "old", {"dir": "4321"})

        dst = root / "new"
        dst.mkdir()
        before = _snapshot(src)

        with Server(dir_=dst) as s:
            # Пока лаунчер молчит, экрана нет вовсе.
            res.check("без вердикта страницы не существует",
                      Client(s.url).get("/admin/migration").status, 303)

        with Server(env=_seed(dst, src), dir_=dst) as s:
            c = Client(s.url)

            r = c.get("/admin/migration")
            res.check("страница открывается без входа", r.status, 200)
            res.ok("назван источник", str(src) in r.body, "путь источника не показан")
            res.ok("назначение названо тоже", str(dst) in r.body, "путь назначения нет")
            res.ok("показан размер картотеки", "KB" in r.body or "MB" in r.body,
                   "размер базы не показан")
            res.ok("показано состояние шифрования", "necriptat" in r.body,
                   "состояние шифрования не показано")
            # ⛔ Числа пациентов на экране НЕТ и быть не может: счёт живёт внутри
            # базы, а базу этот слой не открывает никаким драйвером. Страница
            # обязана сказать это ВСЛУХ — молчание читается как «данных нет».
            res.ok("страница объясняет, почему числа записей нет",
                   "Numărul de pacienți nu este" in r.body,
                   "экран молчит о том, чего не показывает")

            # Журнал при этом РАБОТАЕТ: экран не стена.
            res.check("журнал назначения открыт", c.login().get("/admin").status, 200)
            res.ok("директор видит сигнал в каркасе",
                   "/admin/migration" in c.get("/admin").body,
                   "баннера раздвоения нет на странице журнала")

            after = _snapshot(src)
            res.ok("до ответа источник побайтно тот же", before == after,
                   _diff(before, after))
            res.ok("до ответа migration.json не создан",
                   not (dst / migstate.NAME).exists(),
                   "файл появился раньше ответа человека")

            # --- неверный PIN ---
            r = c.post("/admin/migration/confirm", choice="old", pin="0000")
            res.check("отказ уводит обратно на экран", r.status, 303)
            # ⛔ Кода ответа тут мало: 303 стоит и на успехе, и на отказе.
            # Проверка «назван mig_bad» пережила бы экран, который с тем же
            # кодом уводит на /admin как с удачи — поймано красным стендом.
            res.ok("и это именно экран, а не «готово»",
                   r.location.startswith("/admin/migration"), r.location)
            res.ok("и называет причину", "msg=mig_bad" in r.location, r.location)
            res.ok("источник по-прежнему побайтно тот же",
                   _snapshot(src) == before, _diff(before, _snapshot(src)))
            res.ok("migration.json так и не создан",
                   not (dst / migstate.NAME).exists(), "отказ записал выбор")
            res.ok("⭐ единственное изменение в назначении — счётчик попыток",
                   (dst / auth.SRC_FAIL_NAME).exists(),
                   "счётчик не записан — перебор ничем не ограничен")

            # --- верный PIN ---
            r = c.post("/admin/migration/confirm", choice="old", pin="4321")
            res.check("подтверждение принято", r.status, 303)
            res.ok("и говорит, что данные ЕЩЁ не перенесены", "msg=mig_ok" in r.location,
                   r.location)
            res.ok("источник побайтно тот же и ПОСЛЕ удачи",
                   _snapshot(src) == before, _diff(before, _snapshot(src)))
            st = migstate.state(dst)
            res.check("выбор записан", st["chosen"], migstate.CHOICE_OLD)
            res.check("источник назван в записи", st["old"], str(src))
            res.ok("копия не объявлена начатой", st["authoritative"] == "", f"{st!r}")

            # --- вопрос закрыт: экран и баннер уходят ---
            res.check("экран больше не открывается",
                      c.get("/admin/migration").status, 303)
            res.ok("и баннера в каркасе больше нет",
                   "/admin/migration" not in c.get("/admin").body,
                   "баннер вернулся после ответа — его перестанут читать")


def suite_guard(res: Result) -> None:
    """Охрана формы: чужой origin и ответ «остаюсь» — разными ключами."""
    with tempfile.TemporaryDirectory(prefix="dp_splitg_") as td:
        root = pathlib.Path(td)
        src = _root_v1(root / "old", "5555")
        dst = root / "new"
        dst.mkdir()
        with Server(env=_seed(dst, src), dir_=dst) as s:
            c = Client(s.url)

            # Форма живёт ДО куки, поэтому SameSite её не закрывает.
            r = c.post("/admin/migration/confirm",
                       headers={"Origin": "http://evil.example"},
                       choice="old", pin="5555")
            res.check("чужой origin отвергнут", r.status, 403)
            res.ok("и выбор не записан", not (dst / migstate.NAME).exists(),
                   "чужая страница записала выбор клиники")

            # ⭐ Свой корень подтверждается своим же правом, а не PIN источника.
            r = Client(s.url).post("/admin/migration/confirm", choice="new")
            # ⚠️ И здесь 303 тоже стоит на обоих исходах: смотреть надо на то,
            # ЧТО записано, а не на код.
            res.check("«остаюсь» без входа отвечает редиректом", r.status, 303)
            res.ok("«остаюсь» без входа ничего не записывает",
                   "msg=mig_kept" not in r.location
                   and not (dst / migstate.NAME).exists(), r.location)

            r = c.login().post("/admin/migration/confirm", choice="new")
            res.check("директор подтверждает свой корень", r.status, 303)
            res.ok("и ответ записан", "msg=mig_kept" in r.location, r.location)
            res.check("это второй ответ, а не первый",
                      migstate.state(dst)["chosen"], migstate.CHOICE_NEW)
            # ⛔ Клиника с прошлой версии: v1 источника НЕ мигрировал.
            rec = json.loads((src / "data" / "auth.json").read_text(encoding="utf-8"))
            res.ok("формат auth.json источника не тронут", rec.get("v") is None,
                   f"источник мигрировал в v2: {rec!r}")
