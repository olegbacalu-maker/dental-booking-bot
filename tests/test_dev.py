"""`scripts/dev.py` — рутина разработки: то, что в ней решает за человека.

`.\\dev check` отвечает, есть ли что выпускать, и ошибка в обе стороны стоит
дорого: ложное «нечего» прячет готовую правку от клиник, ложное «изменено»
зовёт выпустить релиз, который не откатить и который везёт клиникам 30 МБ.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from harness import ROOT, Result  # noqa: E402


def suite_release_content(res: Result) -> None:
    """Тесты клиента лежат в frontend/src, но содержанием выпуска не считаются.

    ⛔ 07.10: коммит из одних тестов клиента `dev check` назвал «изменено
    файлов: 2». История здесь своя, во временном репозитории: раннер CI
    забирает исходники без истории и тегов.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        empty = pathlib.Path(tmp) / "empty.gitconfig"
        empty.write_text("", encoding="utf-8")
        # Конфиг машины фикстуре не нужен (подпись, хуки, autocrlf — у каждой
        # свои), а имени автора на раннере нет вовсе: без него commit откажет.
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(empty),
               "GIT_AUTHOR_NAME": "dp", "GIT_AUTHOR_EMAIL": "dp@example.invalid",
               "GIT_COMMITTER_NAME": "dp", "GIT_COMMITTER_EMAIL": "dp@example.invalid"}

        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=repo, env=env, check=True,
                                  capture_output=True, text=True).stdout.strip()

        def commit(files: dict) -> str:
            for rel, text in files.items():
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(text, encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "x")
            return git("rev-parse", "HEAD")

        git("init", "-q")
        commit({"bot/app/engine.py": 'APP_VERSION = "1.0.0"\n',
                "frontend/src/main.tsx": "1\n",
                "frontend/src/features/Day.tsx": "1\n",
                "frontend/src/features/Day.test.tsx": "1\n",
                "frontend/src/test/setup.ts": "1\n",
                "frontend/src/utils/latest.ts": "1\n"})
        git("tag", "v1.0.0")
        # тест рядом с экраном, помощник и тест прямо в src: `**/` — это и
        # ноль папок
        tests_only = commit({"frontend/src/features/Day.test.tsx": "2\n",
                             "frontend/src/test/setup.ts": "2\n",
                             "frontend/src/main.test.ts": "1\n"})
        # правка экрана — и файл с «test» в имени, который не тест
        client = commit({"frontend/src/features/Day.tsx": "2\n",
                         "frontend/src/utils/latest.ts": "2\n"})

        real = dev.ROOT
        dev.ROOT = repo
        try:
            stat, tests = dev.shipped_since("v1.0.0", tests_only)
            res.check("коммит из одних тестов клиента — не содержание выпуска", stat, [])
            res.check("вычтенные тесты названы числом", tests, 3)
            # ⚠️ Пара: БЕЗ вычета те же тесты обязаны посчитаться — иначе
            # пустой счёт выше значил бы «git их не увидел», а не «вычтены».
            keep = dev.CLIENT_TESTS
            dev.CLIENT_TESTS = ()
            try:
                bare = dev.shipped_since("v1.0.0", tests_only)[0]
            finally:
                dev.CLIENT_TESTS = keep
            res.check("без вычета те же тесты посчитались бы", len(bare), 3)

            stat, tests = dev.shipped_since(tests_only, client)
            res.check("правка экрана считается, latest.ts — не тест",
                      [l.split("\t")[2] for l in stat],
                      ["frontend/src/features/Day.tsx", "frontend/src/utils/latest.ts"])
            res.check("в правке экрана тестов нет", tests, 0)
        finally:
            dev.ROOT = real
