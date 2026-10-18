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
                "frontend/src/utils/latest.ts": "1\n",
                "shell/src/main.rs": "1\n",
                "shell/dev/run.ps1": "1\n",
                "installer/DentPilot.iss": "1\n"})
        git("tag", "v1.0.0")
        # тест рядом с экраном, помощник и тест прямо в src: `**/` — это и
        # ноль папок
        tests_only = commit({"frontend/src/features/Day.test.tsx": "2\n",
                             "frontend/src/test/setup.ts": "2\n",
                             "frontend/src/main.test.ts": "1\n"})
        # правка экрана — и файл с «test» в имени, который не тест
        client = commit({"frontend/src/features/Day.tsx": "2\n",
                         "frontend/src/utils/latest.ts": "2\n"})
        # ⛔ 18.10: с Tauri клинике едут оболочка и мастер — а стенды оболочки нет
        stands = commit({"shell/dev/run.ps1": "2\n"})
        native = commit({"shell/src/main.rs": "2\n", "installer/DentPilot.iss": "2\n"})

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

            stat, tests = dev.shipped_since(client, stands)
            res.check("правка стенда оболочки (shell/dev) — не содержание выпуска", stat, [])
            res.check("вычтенный стенд назван числом", tests, 1)
            keep = dev.SHELL_STANDS
            dev.SHELL_STANDS = ()
            try:
                bare = dev.shipped_since(client, stands)[0]
            finally:
                dev.SHELL_STANDS = keep
            res.check("без вычета стенд посчитался бы", len(bare), 1)
            stat, _ = dev.shipped_since(stands, native)
            res.check("правка оболочки и мастера установки — содержание выпуска",
                      [l.split("\t")[2] for l in stat],
                      ["installer/DentPilot.iss", "shell/src/main.rs"])
        finally:
            dev.ROOT = real
        # список ВКЛЮЧАЕТ требование — гниёт молча: переедет папка, и счёт
        # станет нулём навсегда (CLAUDE.md, тесты)
        missing = [p for p in dev.SHIPPED if not (ROOT / p).exists()]
        res.check("пути содержания выпуска есть в дереве", missing, [])
        res.check("строка проверки называет папки из SHIPPED", dev.shipped_areas(),
                  "bot/, frontend/, shell/, installer/")


def suite_child_temp(res: Result) -> None:
    """Временное запусков dev — на диске проекта, а не в %TEMP% (14.10).

    Диск C у Олега на 100 ГБ и вечно полон, а мутация держит до конца около 110
    копий дерева, прогон — сотни песочниц серверов. Вернись TEMP детей на C —
    заметно было бы только по заполняющемуся диску, а не по красному.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")
    was = os.environ.pop("DP_TEMP", None)
    try:
        default = dev.temp_dir()
        res.ok("по умолчанию — sandbox/temp рядом с главным репозиторием",
               default.parts[-2:] == ("sandbox", "temp"), str(default))
        # внутри репозитория `check` увидел бы грязное дерево и отказал выпуску
        res.ok("по умолчанию — вне репозитория",
               not default.resolve().is_relative_to(ROOT.resolve()), str(default))
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DP_TEMP"] = str(pathlib.Path(tmp) / "t")
            env = dev.child_env({**os.environ, "DP_MARK": "1", "TEMP": r"C:\elsewhere"})
            res.ok("TEMP, TMP и TMPDIR детей — в папке dev",
                   all(env[k] == os.environ["DP_TEMP"] for k in ("TEMP", "TMP", "TMPDIR")),
                   repr({k: env.get(k) for k in ("TEMP", "TMP", "TMPDIR")}))
            res.ok("остальное окружение не тронуто", env.get("DP_MARK") == "1")
            out = subprocess.run(
                [sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"],
                env=dev.child_env(), capture_output=True, text=True).stdout.strip()
            res.ok("ребёнок видит её как tempfile.gettempdir()",
                   pathlib.Path(out) == pathlib.Path(os.environ["DP_TEMP"]), out)
    finally:
        os.environ.pop("DP_TEMP", None)
        if was is not None:
            os.environ["DP_TEMP"] = was


def suite_sandbox_dir(res: Result) -> None:
    """Песочница `up` — на диске проекта, а не в %LOCALAPPDATA% (17.10).

    Claude Desktop (пакет MSIX) уводит запись своих процессов в AppData в свою
    LocalCache: у окна Олега и у сессии Claude были РАЗНЫЕ `dental.db` при
    общих `-wal`/`-shm`, и база ломалась то одной стороне («malformed»), то
    другой («locked»). Вернись песочница туда — красного не будет нигде, только
    «у меня не запускается» у человека в обычном окне.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")
    was = os.environ.pop("DP_SANDBOX", None)
    try:
        default = dev.sandbox_dir()
        res.ok("по умолчанию — sandbox/dev-up рядом с главным репозиторием",
               default.parts[-2:] == ("sandbox", "dev-up"), str(default))
        res.ok("по умолчанию — вне репозитория",
               not default.resolve().is_relative_to(ROOT.resolve()), str(default))
        local = os.environ.get("LOCALAPPDATA")
        res.ok("по умолчанию — не в %LOCALAPPDATA%",
               not local or not default.resolve().is_relative_to(pathlib.Path(local).resolve()),
               f"{default} / {local}")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DP_SANDBOX"] = str(pathlib.Path(tmp) / "box")
            res.ok("DP_SANDBOX перевешивает",
                   dev.sandbox_dir() == pathlib.Path(os.environ["DP_SANDBOX"]),
                   str(dev.sandbox_dir()))
    finally:
        os.environ.pop("DP_SANDBOX", None)
        if was is not None:
            os.environ["DP_SANDBOX"] = was
