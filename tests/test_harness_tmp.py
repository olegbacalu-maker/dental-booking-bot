"""Уборка временного прогона: сам харнесс под проверкой.

Утечка во временное не падает и не краснеет — её выдаёт один диск C. 19.09
её чинили в `Server.__exit__`, а 26.09 в %TEMP% снова лежало 387 папок `dp_*`
из пяти ДРУГИХ мест (разбор — `map-modules.md` › «Тесты: наборы подробно»).
С тех пор всё временное процесса харнесса живёт в одной папке прогона, а
`run()` называет набор, оставивший там хоть что-то. Здесь — пары «красное на
сломанном, зелёное на целом» для каждого механизма: сторож без пары зеленел
бы и тогда, когда смотрит не туда.

⚠️ Отдельным файлом НАМЕРЕННО: сторож в `test_launcher.suite_port` считает
стендом любой файл, где рядом имя собранного exe и запуск процесса, — а здесь
процесс запускается (помощник для проверки сирот), exe же — никогда. Имени
exe в этом файле быть не должно, иначе сторож справедливо спросит.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from harness import (PYTHON, RUN_TMP, Result, Server,  # noqa: E402
                     _check_left, _rmtree_settled, _run_entries,
                     _sweep_dead_runs, _wait_released)


# Помощник для проверки сирот: импортирует харнесс (а с ним — задание Windows),
# заводит ребёнка, который держит файл, и ждёт, пока его убьют. Ребёнок идёт
# через venv-лаунчер, как настоящий сервер, — именно лаунчер отпускал внуков.
_SLEEPER = "import sys, time; f = open(sys.argv[1], 'w'); time.sleep(60)"
_HELPER = r"""
import os, subprocess, sys, time
sys.path.insert(0, sys.argv[2])
import harness
subprocess.Popen([sys.executable, "-c", sys.argv[3], sys.argv[1]])
deadline = time.time() + 20
while not os.path.exists(sys.argv[1]) and time.time() < deadline:
    time.sleep(0.05)
print("ready" if os.path.exists(sys.argv[1]) else "no-child", flush=True)
time.sleep(60)
"""


def suite_run_tmp(res: Result) -> None:
    """Уборка временного прогона — пары «красное на сломанном, зелёное на целом».

    Утечка во временное не падает и не краснеет: её выдаёт один диск C
    (26.09 — 387 папок `dp_*` за три дня, хотя 19.09 уборку уже чинили).
    Здесь проверяются САМИ механизмы уборки харнесса: сторож без пары
    зеленел бы и тогда, когда смотрит не туда.
    """
    lab = RUN_TMP / "guard-lab"
    lab.mkdir()
    try:
        # 1. Сторож прогона: оставленное называется именем набора и сносится.
        leak, before = Result(), _run_entries()
        (RUN_TMP / "dp_leak_probe").mkdir()
        _check_left(leak, "проба", before)
        res.ok("оставленное называется именем набора",
               [label for label, _ in leak.failed] == ["проба: оставил временное"],
               f"сторож ответил {leak.failed!r}")
        res.ok("и сносится сразу, чтобы не краснел следующий набор",
               not (RUN_TMP / "dp_leak_probe").exists(), "проба осталась лежать")
        clean = Result()
        _check_left(clean, "проба", _run_entries())
        res.ok("чистый набор не краснеет", not clean.failed, f"{clean.failed!r}")

        if os.name != "nt":
            res.ok("замок и признак смерти сервера — только Windows (пропуск)", True)
        else:
            # 2. Брошенный прогон сносится, живой — никогда: по замку, не по возрасту.
            old = time.time() - 3600
            live, dead = lab / "dp_run_live", lab / "dp_run_dead"
            young, other = lab / "dp_run_young", lab / "dp_test_other"
            for d in (live, dead, young, other):
                d.mkdir()
            held = open(live / ".lock", "w", encoding="utf-8")
            (dead / ".lock").write_text("pid 0", encoding="utf-8")
            (dead / "dental.db").write_bytes(b"x")
            for d in (live, dead, other):
                os.utime(d, (old, old))
            try:
                _sweep_dead_runs(lab)
            finally:
                held.close()
            res.ok("живой прогон (замок держат) не тронут",
                   (live / ".lock").exists(),
                   "уборка снесла папку работающего прогона — чужая сессия упадёт")
            res.ok("брошенный прогон (замок свободен) снесён", not dead.exists(),
                   "убитый прогон так и лежит в %TEMP%")
            res.ok("свежий прогон без замка не тронут", young.exists(),
                   "снесён прогон, который только открывает замок")
            res.ok("чужой префикс не тронут", other.exists(),
                   "уборка прогонов снесла то, что заводила не она")

            # 3. Признак смерти сервера: ждём, пока файл держат, и возвращаем имя.
            log = lab / "server.log"
            log.write_text("x", encoding="utf-8")
            holder = open(log, "a", encoding="utf-8")
            threading.Timer(0.4, holder.close).start()
            t0 = time.time()
            _wait_released(log, budget=5)
            waited = time.time() - t0
            res.ok("ждёт, пока лог держат", waited >= 0.3,
                   f"вернулся через {waited:.2f} с — уборка снова пойдёт в "
                   f"окно, когда сервер ещё жив")
            res.ok("и возвращает логу имя", log.exists()
                   and not log.with_name("server.log.probe").exists(),
                   "лог остался под именем пробы — наборы его не найдут")
            t0 = time.time()
            _wait_released(log, budget=5)
            res.ok("свободный лог не ждёт", time.time() - t0 < 0.2,
                   f"ждал {time.time() - t0:.2f} с на свободном файле")

            # 4. Прогон, убитый ОДНИМ процессом (не деревом), не оставляет
            # сирот: без задания Windows ребёнок помощника переживал его и
            # держал файл ещё минуту — как сервер держал песочницу вечно.
            held_by_kid = lab / "kid.hold"
            helper = subprocess.Popen(
                [str(PYTHON), "-c", _HELPER, str(held_by_kid),
                 str(pathlib.Path(__file__).resolve().parent), _SLEEPER],
                stdout=subprocess.PIPE, text=True,
                env={**os.environ, "TMPDIR": str(lab), "TEMP": str(lab),
                     "TMP": str(lab)})
            ready = (helper.stdout.readline() or "").strip()
            helper.kill()                    # ТОЛЬКО верхний процесс, как Stop-Process
            helper.wait()
            helper.stdout.close()
            _wait_released(held_by_kid, budget=5)
            try:
                os.replace(held_by_kid, lab / "kid.free")
                freed = True
            except OSError:
                freed = False
            res.ok("ребёнок прогона умирает вместе с ним", ready == "ready" and freed,
                   f"помощник: {ready!r}; файл ребёнка {'свободен' if freed else 'ЗАНЯТ'} "
                   f"— сирота жив и держит своё от уборки")

        # 5. Сервер: свой %TEMP%, keep_dir + drop(), несостоявшийся старт.
        s = Server(keep_dir=True)
        with s:
            tmp = s.tmp
            res.ok("у сервера свой %TEMP%, пока он жив",
                   tmp is not None and tmp.is_dir(), f"tmp = {tmp!r}")
        res.ok("и он уходит вместе с сервером",
               tmp is not None and not tmp.exists(), f"остался {tmp}")
        res.ok("keep_dir: папка пережила выход сервера", s.dir.exists(),
               "папка снесена — второму серверу стенда не с чем работать")
        s.drop()
        res.ok("drop() её сносит", not s.dir.exists(), f"осталась {s.dir}")

        empty = lab / "no-bot"
        empty.mkdir()
        bad = Server(bot=empty)          # uvicorn не найдёт app.main и выйдет
        why = ""
        try:
            with bad:
                pass
        except RuntimeError as e:
            why = str(e)
        res.ok("несостоявшийся старт — исключение с причиной из лога",
               "No module named 'app'" in why, f"сообщение: {why[-300:]!r}")
        res.ok("и песочница не остаётся", not bad.dir.exists(),
               f"осталась {bad.dir} — `with` не зовёт __exit__ после отказа старта")
    finally:
        _rmtree_settled(lab)
