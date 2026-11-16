"""`scripts/dev.py` — рутина разработки: то, что в ней решает за человека.

`.\\dev check` отвечает, есть ли что выпускать, и ошибка в обе стороны стоит
дорого: ложное «нечего» прячет готовую правку от клиник, ложное «изменено»
зовёт выпустить релиз, который не откатить и который везёт клиникам 30 МБ.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import pathlib
import re
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
        commit({"bot/app/version.py": 'APP_VERSION = "1.0.0"\n',
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


def suite_up_listener(res: Result) -> None:
    """`up` находит прошлый сервер на порту (09.11.2026).

    На Windows 11 26300 у слушающего сокета поле состояния — мусор (`CLOSED`,
    `FIN_WAIT_1`, а с числом 0 netstat строку не печатает вовсе), и разбор
    netstat по `LISTENING` молча не находил прошлый сервер: второй `up` падал
    10048, а запросы продолжал получать старый процесс. Проверка — живым
    сокетом этого же прогона: слушатель обязан найтись с первого раза и при
    IPv4, и при IPv6, а привязанный, но не слушающий сокет — нет.
    """
    if sys.platform != "win32":
        res.ok("слушатели порта — только на Windows (пропуск)", True)
        return
    import socket
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")
    me = str(os.getpid())
    for family, host, name in ((socket.AF_INET, "127.0.0.1", "IPv4"),
                               (socket.AF_INET6, "::1", "IPv6")):
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.bind((host, 0))
        except OSError as e:
            res.ok(f"{name}: сокет не завёлся — пропуск", True, str(e))
            continue
        with s:
            port = s.getsockname()[1]
            res.ok(f"{name}: привязанный без listen — не слушатель",
                   me not in dev._listener_pids(port), f"порт {port}")
            s.listen()
            hits = sum(me in dev._listener_pids(port) for _ in range(10))
            res.ok(f"{name}: слушатель находится каждый раз (10 из 10)",
                   hits == 10, f"порт {port}: {hits} из 10")
        res.ok(f"{name}: закрытый сокет — не слушатель",
               me not in dev._listener_pids(port), f"порт {port}")


def _workflow() -> str:
    return (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")


def suite_ci_parts(res: Result) -> None:
    """Части прогона CI — все наборы ровно по разу (10.11).

    Движок в CI идёт N работами, каждая — `run_tests.py --part k/N`. Потерянный
    набор не краснеет нигде: его просто никто не гонит. Поэтому здесь — что
    деление покрывает всё при любом N, и что список частей в workflow — ровно
    1..N, а N в команде — число работ, а не второе число, которое можно забыть
    поднять.
    """
    rt = sys.modules.get("run_tests") or importlib.import_module("run_tests")
    suites = rt.SUITES
    res.ok("наборы нашлись", len(suites) > 100, f"наборов {len(suites)}")
    for n in (1, 2, 3, 4, 6, 7, 10):
        parts = [rt.part(suites, k, n) for k in range(1, n + 1)]
        ids = [id(s) for p in parts for s in p]
        res.ok(f"n={n}: каждый набор ровно в одной части",
               sorted(ids) == sorted(id(s) for s in suites),
               f"в частях {len(ids)}, наборов {len(suites)}")
        sizes = [len(p) for p in parts]
        res.ok(f"n={n}: части ровные (разница не больше одного)",
               max(sizes) - min(sizes) <= 1, str(sizes))
    for bad in ((0, 3), (4, 3), (1, 0)):
        try:
            rt.part(suites, *bad)
            res.ok(f"часть {bad[0]}/{bad[1]} отвергнута", False, "прошла")
        except ValueError:
            res.ok(f"часть {bad[0]}/{bad[1]} отвергнута", True)

    wf = _workflow()
    for label, bad in _ci_parts_problems(wf):
        res.ok(label, not bad, bad)
    got = _ci_parts_list(_job_block(wf, "engine"))
    res.ok("частей движка шесть или больше: три шли по 5–6.5 мин",
           len(got) >= 6, str(got))
    # Сам сторож — на сломанных workflow: каждый обязан краснеть. Иначе
    # потерянная часть прошла бы мимо так же молча, как мимо прогона.
    line = re.search(r"^\s*part:\s*\[[^\]]*\]", wf, re.M)
    run = r"--part ${{ matrix.part }}/${{ strategy.job-total }}"
    broken = {
        "часть потерялась (1, 2, 3, 5, 6)": wf.replace(line.group(0), "part: [1, 2, 3, 5, 6]")
        if line else "",
        "часть дважды (1, 2, 2, 3)": wf.replace(line.group(0), "part: [1, 2, 2, 3]")
        if line else "",
        "N в команде числом, а не числом работ": wf.replace(run, "--part ${{ matrix.part }}/6"),
        "одна часть": wf.replace(line.group(0), "part: [1]") if line else "",
        "списка частей нет": wf.replace(line.group(0), "") if line else "",
    }
    for what, text in broken.items():
        red = [lb for lb, bad in _ci_parts_problems(text) if bad]
        res.ok(f"сторож частей краснеет: {what}", bool(red), "зелёный на сломанном workflow")


def _ci_parts_list(wf: str) -> list[int]:
    m = re.search(r"^\s*part:\s*\[([^\]]*)\]", wf, re.M)
    try:
        return [int(x) for x in m.group(1).split(",")] if m else []
    except ValueError:
        return []


def _ci_parts_problems(wf: str) -> list[tuple[str, str]]:
    """(проверка, что не так) по тексту workflow; пустое «что не так» — зелёная."""
    got = _ci_parts_list(_job_block(wf, "engine"))
    run = r"tests\run_tests.py --part ${{ matrix.part }}/${{ strategy.job-total }}"
    return [
        ("в workflow есть список частей движка", "" if got else "нет `part: [...]`"),
        ("список частей — ровно 1..N подряд",
         "" if got == list(range(1, len(got) + 1)) else f"{got}"),
        ("частей больше одной", "" if len(got) > 1 else str(got)),
        ("часть гонится с N = числом работ", "" if run in wf else f"нет строки {run!r}"),
        # облако зовёт свой tests/run_tests.py через «/», движок — через «\»
        ("полного прогона движка без --part нет",
         "есть" if re.search(r"tests\\run_tests\.py\s*$", wf, re.M) else ""),
    ]


def suite_parts_summary(res: Result) -> None:
    """Сводка `.\\dev test` частями красная, если красна хоть одна часть, часть
    упала без отчёта или в отчётах нет набора, который обязан был пройти.

    Итог по частям — сумма чужих отчётов, и «всё зелёное» в ней значит лишь
    «красного не прислали»: упавшая часть и потерянный набор не присылают
    ничего. Поэтому каждое такое молчание здесь — красное."""
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")

    class _Proc:
        def __init__(self, code):
            self.returncode = code

    class _Fake:
        def __init__(self, label, code, rep):
            self.label, self.proc, self._rep, self.log = label, _Proc(code), rep, "log"

        def result(self):
            return self._rep

    def rep(*names, failed=()):
        return {"passed": len(names), "total": len(names) + len(failed),
                "failed": [list(f) for f in failed],
                "suites": [{"name": n, "checks": 1, "secs": 1.0, "red": 0} for n in names]}

    def code(parts, expected):
        with contextlib.redirect_stdout(io.StringIO()):
            return dev._summary(parts, expected, 1.0)

    good = [_Fake("часть 1/2", 0, rep("a", "b")), _Fake("часть 2/2", 0, rep("c"))]
    res.check("все части зелёные, все наборы на месте — зелёный", code(good, ["a", "b", "c"]), 0)
    res.check("красная проверка в части — красный",
              code([good[0], _Fake("часть 2/2", 1, rep("c", failed=[("x", "y")]))],
                   ["a", "b", "c"]), 1)
    res.check("часть упала без отчёта — красный",
              code([good[0], _Fake("часть 2/2", 3221225786, None)], ["a", "b", "c"]), 1)
    res.check("часть с отчётом, но кодом аварии — красный",
              code([good[0], _Fake("часть 2/2", 3221225786, rep("c"))], ["a", "b", "c"]), 1)
    res.check("набор не прошёл ни в одной части — красный", code(good, ["a", "b", "c", "d"]), 1)
    res.check("набор прошёл дважды — красный",
              code([good[0], _Fake("часть 2/2", 0, rep("c", "a"))], ["a", "b", "c"]), 1)
    res.check("-j: число и формы записи",
              [dev._parse_jobs(a)[0] for a in (["-j", "3"], ["-j4"], ["--jobs=2"], ["x"])],
              [3, 4, 2, None])
    res.check("-j: фильтр проходит дальше как был", dev._parse_jobs(["-j", "3", "рутина"])[1],
              ["рутина"])
    for bad in (["-j", "0"], ["-j", "x"]):
        try:
            dev._parse_jobs(bad)
            res.ok(f"-j отвергает {bad[1]!r}", False, "принял")
        except ValueError:
            res.ok(f"-j отвергает {bad[1]!r}", True)
    res.ok("частей по умолчанию — хотя бы одна и не больше потолка",
           1 <= dev.default_jobs() <= dev.JOBS_MAX, str(dev.default_jobs()))


def suite_serial(res: Result) -> None:
    """Наборы «только по одному» (`run_tests.SERIAL`) — в списке наборов.

    `.\\dev test` гонит части разом, а эти наборы — после, по одному. Список
    ВКЛЮЧАЮЩИЙ: набор, убранный из SUITES, но оставшийся здесь, значит, что
    список не читали при правке, — а рядом мог появиться новый общий ресурс
    без пометки. И деление: «разом» и «по одному» вместе — все наборы по разу."""
    rt = sys.modules.get("run_tests") or importlib.import_module("run_tests")
    res.ok("SERIAL не пуст", len(rt.SERIAL) > 0, "")
    res.check("каждый набор SERIAL есть в SUITES", rt.serial_unknown(), [])
    alone = {id(f) for f in rt.SERIAL}
    par, _ = rt.select(["--no-serial"])
    ser, _ = rt.select(["--serial"])
    res.check("--serial берёт ровно SERIAL", sorted(id(f) for _, f in ser), sorted(alone))
    res.ok("--no-serial не берёт ни одного из SERIAL",
           not any(id(f) in alone for _, f in par), "")
    res.check("вместе — все наборы ровно по разу",
              sorted(id(f) for _, f in par + ser), sorted(id(f) for _, f in rt.SUITES))
    # части параллельного прогона: фильтр до деления, объединение — всё
    for n in (1, 5, 8, 12):
        parts = [rt.select(["--no-serial", "--part", f"{k}/{n}"])[0] for k in range(1, n + 1)]
        res.check(f"части разом n={n}: объединение = всё, кроме SERIAL",
                  sorted(id(f) for p in parts for _, f in p), sorted(id(f) for _, f in par))
    flt, _ = rt.select(["рутина"])
    parts = [rt.select(["рутина", "--part", f"{k}/4"])[0] for k in range(1, 5)]
    res.ok("фильтр — до деления: ни одна из 4 частей не пуста",
           len(flt) >= 4 and all(parts), f"наборов по фильтру {len(flt)}, "
           f"части {[len(p) for p in parts]}")


def suite_ci_mutation(res: Result) -> None:
    """Мутация в CI — только когда тронуты сторожа, правило одно с `dev test` (10.11).

    ⛔ Ошибка в сторону «не гнать» молчит: сторож сломан, мутации нет, всё
    зелёное. Поэтому каждый неясный случай обязан давать «гнать», и пары ниже
    это держат так же, как случай «не нужно».
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")
    res.check("сторожа в рабочем дереве (как пишет git status на Windows)",
              dev.guards_in([r"tests\mutate.py", "tests/test_structure.py",
                             "scripts/mutate.py", "tests/test_dev.py"]),
              [r"tests\mutate.py", "tests/test_structure.py"])
    # событие → база
    sha = "a" * 40
    res.check("push — before события", dev.ci_base("push", {"before": sha}), sha)
    res.check("push новой ветки (нули) — гнать", dev.ci_base("push", {"before": "0" * 40}), None)
    res.check("push без before — гнать", dev.ci_base("push", {}), None)
    res.check("PR — база PR",
              dev.ci_base("pull_request", {"pull_request": {"base": {"sha": sha}}}), sha)
    res.check("ручной запуск — родитель", dev.ci_base("workflow_dispatch", {"inputs": {}}), "HEAD^")
    res.check("ручной с галкой — гнать",
              dev.ci_base("workflow_dispatch", {"inputs": {"mutation": "true"}}), None)
    res.check("ручной с галкой булевой — гнать",
              dev.ci_base("workflow_dispatch", {"inputs": {"mutation": True}}), None)
    res.check("ночь — гнать", dev.ci_base("schedule", {}), None)
    res.check("неизвестное событие — гнать", dev.ci_base("merge_group", {}), None)

    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        empty = pathlib.Path(tmp) / "empty.gitconfig"
        empty.write_text("", encoding="utf-8")
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
        base = commit({"tests/mutate.py": "1\n", "tests/test_structure.py": "1\n",
                       "tests/test_dev.py": "1\n", "scripts/mutate.py": "1\n"})
        other = commit({"tests/test_dev.py": "2\n", "scripts/mutate.py": "2\n"})
        guard = commit({"tests/mutate.py": "2\n"})
        real = dev.ROOT
        dev.ROOT = repo
        old_env = {k: os.environ.get(k) for k in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL")}
        os.environ.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(empty)})
        try:
            res.check("правка не сторожей (и mutate.py вне tests/) — не гнать",
                      dev.mutation_needed(base, other)[0], False)
            res.check("правка mutate.py — гнать", dev.mutation_needed(other, guard)[0], True)
            res.check("пуш из нескольких коммитов: сторож в середине — гнать",
                      dev.mutation_needed(base, guard)[0], True)
            res.check("ручной запуск: HEAD^ видит последний коммит (сторож) — гнать",
                      dev.mutation_needed("HEAD^")[0], True)
            res.check("неизвестная база (force-push, мелкий клон) — гнать",
                      dev.mutation_needed("f" * 40)[0], True)
            res.check("базы нет — гнать", dev.mutation_needed(None)[0], True)
        finally:
            dev.ROOT = real
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    wf = _workflow()
    res.ok("работа мутации ждёт решения `dev.py ci-mutate`",
           "scripts/dev.py ci-mutate" in wf
           and "if: needs.guards.outputs.mutate == 'true'" in wf, "")
    res.ok("ночное расписание есть", re.search(r"^\s*schedule:\s*$", wf, re.M) is not None, "")


def suite_test_mutation(res: Result) -> None:
    """`dev test` зовёт мутацию и тогда, когда сторожа тронуты В КОММИТАХ.

    Ветка, принёсшая правило в `test_structure.py` коммитами, на посадке в
    локальный main мутацию не звала: смотрелось только рабочее дерево, а в
    нём было чисто. База — точка расхождения HEAD с `origin/main`, без fetch.
    ⛔ Ошибка в сторону «не гнать» молчит, поэтому неясное — «гнать».
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")
    res.check("база — origin/main", dev.TEST_BASE, "origin/main")
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        empty = pathlib.Path(tmp) / "empty.gitconfig"
        empty.write_text("", encoding="utf-8")
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(empty),
               "GIT_AUTHOR_NAME": "dp", "GIT_AUTHOR_EMAIL": "dp@example.invalid",
               "GIT_COMMITTER_NAME": "dp", "GIT_COMMITTER_EMAIL": "dp@example.invalid"}

        def git(*args: str, cwd: pathlib.Path = repo) -> str:
            return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                                  capture_output=True, text=True).stdout.strip()

        def write(files: dict, cwd: pathlib.Path = repo) -> None:
            for rel, text in files.items():
                (cwd / rel).parent.mkdir(parents=True, exist_ok=True)
                (cwd / rel).write_text(text, encoding="utf-8")

        def commit(files: dict, cwd: pathlib.Path = repo) -> str:
            write(files, cwd)
            git("add", "-A", cwd=cwd)
            git("commit", "-q", "-m", "x", cwd=cwd)
            return git("rev-parse", "HEAD", cwd=cwd)

        def need() -> bool:
            return dev.test_mutation_needed()[0]

        def why() -> str:
            return " | ".join(dev.test_mutation_needed()[1])

        git("init", "-q", "-b", "main")
        base = commit({"tests/mutate.py": "1\n", "tests/test_structure.py": "1\n",
                       "tests/test_dev.py": "1\n", "scripts/mutate.py": "1\n"})
        real = dev.ROOT
        dev.ROOT = repo
        old_env = {k: os.environ.get(k) for k in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL")}
        os.environ.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(empty)})
        try:
            # ссылки нет: как раньше — только рабочее дерево, и вслух
            res.check("нет origin/main, чисто — не гнать", need(), False)
            res.ok("нет origin/main — сказано строкой", "origin/main нет" in why(), why())
            write({"tests/mutate.py": "dirty\n"})
            res.check("нет origin/main, правка сторожа в дереве — гнать", need(), True)
            git("checkout", "-q", "--", "tests/mutate.py")

            git("update-ref", "refs/remotes/origin/main", base)
            res.check("main = origin/main, чисто — не гнать", need(), False)
            res.ok("причина называет базу и точку расхождения",
                   "origin/main" in why() and base[:8] in why(), why())
            other = commit({"tests/test_dev.py": "2\n", "scripts/mutate.py": "2\n"})
            res.check("main впереди коммитом не сторожей (и mutate.py вне tests/) — не гнать",
                      need(), False)
            guard = commit({"tests/test_structure.py": "2\n"})
            res.check("main впереди коммитом в test_structure.py (посадка) — гнать", need(), True)
            res.ok("причина называет файл из коммитов", "tests/test_structure.py" in why(), why())
            commit({"tests/test_dev.py": "3\n"})
            res.check("сторож в середине незапушенных коммитов — гнать", need(), True)

            git("update-ref", "refs/remotes/origin/main", guard)
            res.check("всё запушено, чисто — не гнать", need(), False)
            write({"tests/test_structure.py": "dirty\n"})
            res.check("незакоммиченная правка сторожа — гнать", need(), True)
            res.ok("причина называет рабочее дерево", "в рабочем дереве: tests/test_structure.py"
                   in why(), why())
            git("checkout", "-q", "--", "tests/test_structure.py")
            write({"tests/test_structure.py": "staged\n"})
            git("add", "tests/test_structure.py")
            res.check("сторож только в индексе — гнать", need(), True)
            git("reset", "-q", "--hard")
            write({"tests/new/mutate.py": "1\n"})
            res.check("новый неотслеживаемый сторож в новой папке — гнать", need(), True)
            (repo / "tests/new/mutate.py").unlink()
            git("mv", "tests/mutate.py", "tests/mutate_old.py")
            res.check("сторож переименован (уходит старое имя) — гнать", need(), True)
            git("reset", "-q", "--hard")
            res.check("после отката чисто — не гнать", need(), False)

            # origin/main ушёл вперёд чужим сторожем: наше дерево он не трогает
            head = git("rev-parse", "HEAD")
            git("checkout", "-q", "-b", "elsewhere")
            ahead = commit({"tests/mutate.py": "remote\n"})
            git("checkout", "-q", "main")
            git("update-ref", "refs/remotes/origin/main", ahead)
            res.check("origin/main впереди сторожем, которого у нас нет — не гнать",
                      need(), False)
            git("update-ref", "refs/remotes/origin/main", head)

            git("checkout", "-q", "--detach", other)
            git("update-ref", "refs/remotes/origin/main", base)
            res.check("detached HEAD без сторожей — не гнать", need(), False)
            git("checkout", "-q", "--detach", guard)
            res.check("detached HEAD с коммитом сторожа — гнать", need(), True)
            git("checkout", "-q", "main")

            git("checkout", "-q", "--orphan", "lonely")
            orphan = commit({"x.txt": "1\n"})
            git("checkout", "-q", "-f", "main")
            git("clean", "-qfd")
            git("update-ref", "refs/remotes/origin/main", orphan)
            res.check("нет общей истории с origin/main — гнать", need(), True)
            git("update-ref", "refs/remotes/origin/main", head)

            wt = pathlib.Path(tmp) / "wt"
            git("worktree", "add", "-q", "-b", "feature", str(wt), "main")
            dev.ROOT = wt
            res.check("worktree, ветка без правок — не гнать", need(), False)
            commit({"tests/mutate.py": "wt\n"}, cwd=wt)
            res.check("worktree, коммит сторожа в ветке — гнать", need(), True)
        finally:
            dev.ROOT = real
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v



def _mutate_cli(*args: str) -> subprocess.CompletedProcess:
    """`mutate.py` подпроцессом: он импортирует `app.db` с деревом программы, а
    в процессе прогона это чужой модуль (как у `test_layout_names`)."""
    return subprocess.run([sys.executable, str(ROOT / "tests" / "mutate.py"), *args],
                          cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _job_block(wf: str, job: str) -> str:
    """Текст работы `job:` в workflow — до следующей работы. Частями идут две
    работы, и список `part:` надо брать у своей: первый в файле — чужой."""
    m = re.search(rf"^  {job}:\s*$", wf, re.M)
    if not m:
        return ""
    rest = wf[m.end():]
    nxt = re.search(r"^  \S", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _ci_mutation_problems(wf: str) -> list[tuple[str, str]]:
    """(проверка, что не так) по работе мутации в workflow; пусто — зелёная."""
    block = _job_block(wf, "mutation")
    got = _ci_parts_list(block)
    run = r"tests\mutate.py --part ${{ matrix.part }}/${{ strategy.job-total }}"
    return [
        ("в workflow есть работа мутации", "" if block else "нет `mutation:`"),
        ("у мутации есть список частей", "" if got else "нет `part: [...]`"),
        ("части мутации — ровно 1..N подряд",
         "" if got == list(range(1, len(got) + 1)) else f"{got}"),
        ("частей мутации больше одной", "" if len(got) > 1 else str(got)),
        ("часть мутации гонится с N = числом работ", "" if run in block else f"нет {run!r}"),
        ("имя работы — «<имя> k/N» (его читает release.ci_verdict)",
         "" if re.search(r"^\s*name:.*\$\{\{ matrix\.part \}\}/\$\{\{ strategy\.job-total \}\}\s*$",
                         block, re.M) else "имя без k/N"),
        # облако зовёт свой tests/mutate.py через «/», движок — через «\»
        ("мутации целиком без --part нет",
         "есть" if re.search(r"tests\\mutate\.py\s*$", block, re.M) else ""),
    ]


def _cover_problems(every: list, parts: list) -> list[str]:
    """Что не так с делением: потерянные, двойные и чужие ключи."""
    flat = [k for p in parts for k in p]
    return ([f"нет {k}" for k in every if k not in flat]
            + [f"дважды {k}" for k in sorted(set(flat)) if flat.count(k) > 1]
            + [f"чужой {k}" for k in sorted(set(flat) - set(every))])


def suite_mutate_parts(res: Result) -> None:
    """Части мутации — каждая правка ровно по разу, итог частями молчанием не зеленеет.

    Мутация идёт частями (`mutate.py --part k/N`): `.\\dev mutate -j N` разом и
    CI матрицей. Потерянная мутация не краснеет нигде — её просто никто не
    гонит, и сломанный сторож остаётся незамеченным. Поэтому здесь — что
    деление тем же кодом, что у прогона, покрывает всё при любом N; что работа
    CI — ровно 1..N частей; что сводка `dev mutate` красна при любом молчании;
    и сами эти проверки — на сломанных вариантах, каждый обязан краснеть.
    """
    import json
    sys.path.insert(0, str(ROOT / "scripts"))
    dev = importlib.import_module("dev")

    r = _mutate_cli("--list")
    every = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else []
    res.ok("мутации нашлись", len(every) > 100, f"код {r.returncode}, ключей {len(every)}")
    res.check("ключи не повторяются", len(set(every)), len(every))
    for n in (1, 2, 3, 4, 6, 10):
        r = _mutate_cli("--list", "--parts", str(n))
        parts = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else []
        res.check(f"n={n}: частей {n}", len(parts), n)
        res.check(f"n={n}: каждая правка ровно в одной части", _cover_problems(every, parts), [])
        sizes = [len(p) for p in parts] or [0]
        res.ok(f"n={n}: части ровные (разница не больше одного)",
               max(sizes) - min(sizes) <= 1, str(sizes))
    # сторож деления сам краснеет на сломанном делении
    halves = [every[::2], every[1::2]]
    for what, broken in {"правка потерялась": [halves[0], halves[1][:-1]],
                         "правка дважды": [halves[0] + halves[1][:1], halves[1]],
                         "чужой ключ": [halves[0], halves[1] + ["M99999"]]}.items():
        res.ok(f"сторож деления краснеет: {what}", bool(_cover_problems(every, broken)),
               "зелёный на сломанном делении")
    for bad in ("0/3", "4/3", "x"):
        r = _mutate_cli("--part", bad)
        res.check(f"часть {bad} отвергнута до работы", r.returncode, 2)

    wf = _workflow()
    for label, why in _ci_mutation_problems(wf):
        res.ok(label, not why, why)
    block = _job_block(wf, "mutation")
    line = re.search(r"^\s*part:\s*\[[^\]]*\]", block, re.M)
    run = r"tests\mutate.py --part ${{ matrix.part }}/${{ strategy.job-total }}"

    def swap(old: str, new: str) -> str:
        return wf.replace(block, block.replace(old, new)) if old else ""

    lst = line.group(0) if line else ""
    broken = {
        "часть потерялась (1, 2, 4)": swap(lst, "part: [1, 2, 4]"),
        "часть дважды (1, 2, 2)": swap(lst, "part: [1, 2, 2]"),
        "одна часть": swap(lst, "part: [1]"),
        "списка частей нет": swap(lst, ""),
        "N в команде числом": swap(run, r"tests\mutate.py --part ${{ matrix.part }}/4"),
        "мутация целиком": swap(run, r"tests\mutate.py"),
        "имя без k/N": swap("Мутация сторожей ${{ matrix.part }}/${{ strategy.job-total }}",
                            "Мутация сторожей"),
    }
    for what, text in broken.items():
        red = [lb for lb, why in _ci_mutation_problems(text) if why]
        res.ok(f"сторож CI мутации краснеет: {what}", bool(red), "зелёный на сломанном workflow")

    # сводка `dev mutate -j`
    class _Proc:
        def __init__(self, code):
            self.returncode = code

    class _Fake:
        def __init__(self, label, code, rep):
            self.label, self.proc, self._rep, self.log = label, _Proc(code), rep, "log"

        def result(self):
            return self._rep

    def rep(*keys, bad=()):
        return {"part": None, "ran": list(keys), "bad": list(bad), "clean": [], "secs": 1.0}

    def code(parts, expected):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = dev._mutate_summary(parts, expected, 1.0)
        return got, out.getvalue()

    exp = ["M0", "M1", "L0"]
    good = [_Fake("часть 1/2", 0, rep("M0", "L0")), _Fake("часть 2/2", 0, rep("M1"))]
    res.check("все части зелёные, все правки на месте — зелёный", code(good, exp)[0], 0)
    res.check("сторож молчит в части — красный",
              code([good[0], _Fake("часть 2/2", 1, rep("M1", bad=["правило «x» молчит"]))],
                   exp)[0], 1)
    res.check("часть упала без отчёта — красный",
              code([good[0], _Fake("часть 2/2", 3221225786, None)], exp)[0], 1)
    res.check("часть с отчётом, но кодом аварии — красный",
              code([good[0], _Fake("часть 2/2", 3221225786, rep("M1"))], exp)[0], 1)
    res.check("часть с кодом 1 без находок — красный",
              code([good[0], _Fake("часть 2/2", 1, rep("M1"))], exp)[0], 1)
    res.check("правка не прошла ни в одной части — красный", code(good, exp + ["M2"])[0], 1)
    res.check("правка прошла дважды — красный",
              code([good[0], _Fake("часть 2/2", 0, rep("M1", "M0"))], exp)[0], 1)
    twin = ["набор красный ДО мутаций — сначала почини правило"]
    _, text = code([_Fake("часть 1/2", 1, rep("M0", "L0", bad=twin)),
                    _Fake("часть 2/2", 1, rep("M1", bad=twin))], exp)
    res.check("одинаковая находка двух частей — одной строкой", text.count(twin[0]), 1)

    # кто куда зовёт: -j 1 — по-старому, -j N — частями, `dev test` — теми же частями
    calls: list = []
    saved = dev.run, dev.run_mutate_parts, dev.cmd_mutate, dev.test_mutation_needed
    try:
        dev.run = lambda cmd, *a, **k: calls.append(("run", [str(c) for c in cmd])) or 0
        dev.run_mutate_parts = lambda jobs: calls.append(("parts", jobs)) or 0
        with contextlib.redirect_stdout(io.StringIO()):
            dev.cmd_mutate(["-j", "1"])
            dev.cmd_mutate(["-j", "4"])
            dev.cmd_mutate(["--part", "2/3"])
        res.check("dev mutate -j 1 — одним процессом, без частей",
                  [c[0] for c in calls], ["run", "parts", "run"])
        res.ok("dev mutate -j 1 зовёт mutate.py без аргументов",
               calls[0][1][-1].endswith("mutate.py"), str(calls[0][1]))
        res.check("dev mutate -j 4 — четыре части", calls[1][1], 4)
        res.check("dev mutate --part 2/3 — уходит в mutate.py как есть",
                  calls[2][1][-2:], ["--part", "2/3"])
        got: list = []
        dev.test_mutation_needed = lambda *a, **k: (True, ["тронуты"])
        dev.cmd_mutate = lambda argv: got.append(list(argv)) or 1
        with contextlib.redirect_stdout(io.StringIO()):
            stop = [dev.cmd_test(["-j", "3"]), dev.cmd_test(["-j", "1"])]
        res.check("dev test зовёт мутацию теми же частями", got, [["-j", "3"], ["-j", "1"]])
        res.check("красная мутация останавливает прогон", stop, [1, 1])
    finally:
        dev.run, dev.run_mutate_parts, dev.cmd_mutate, dev.test_mutation_needed = saved
