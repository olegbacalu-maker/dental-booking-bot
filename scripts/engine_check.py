# -*- coding: utf-8 -*-
"""Стенд движка Tauri (Т5, 18.10.2026): оболочка-харнесс на Python.

    .venv-desktop\\Scripts\\python.exe scripts\\engine_check.py
    .venv-desktop\\Scripts\\python.exe scripts\\engine_check.py --exe dist\\DentPilot-Engine\\DentPilot-Engine.exe

Движок запускается так, как его запустит оболочка DentPilot.exe (контракт
`docs/dentpilot-2/tauri-contract.md` § 2): `DENTART_SHELL=tauri`, трубы на
stdin и stdout, БЕЗ консоли (CREATE_NO_WINDOW), в своём задании Windows. Из
исходников — `bot\\desktop.py` под `.venv-desktop` (так оболочка запускает
его в разработке, `DENTPILOT_DEV_APP`); с `--exe` — собранный движок папкой,
скопированный в лабораторию как `<lab>\\prog\\engine\\` с `demo.flag` в
`<lab>\\prog\\` — раскладка установленной программы.

Сценарии — каждый своим процессом, лаборатория одна, порт свой:
  stop   hello → stage… → ready; /health отвечает; строка stop → код 0 не
         дольше 10 с, порт свободен, `-wal` сброшен, в stdout только `DP1`
  eof    ready → закрытый stdin (оболочка исчезла) → то же
  busy   второй экземпляр на том же порту → hello, busy с адресом первого,
         код 3; первый жив и останавливается сам
  fatal  порт держит чужая программа → fatal про порт, код 2
  early  stdin закрыт сразу после hello → код 0, ready не было: сервер не
         поднимали
  base   (--exe) корень программы — родитель `engine\\`: `demo.flag` оттуда
         дал демо-профиль клиники, битый `install.json` оттуда — `warn`
         после `hello`, запуск идёт
Из исходников тот же список гоняет прогон (`test_launcher.suite_engine`);
собранный — сборка движка (`Build-Engine.ps1`).
⛔ Лаборатория называет себя корнем данных и TEMP (правило стендов
`test_launcher.suite_port`): без DENTART_DATA_DIR движок ушёл бы в
%ProgramData% — в настоящую картотеку машины.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(BOT))

from harness import (PYTHON, Result, _end_job, _rmtree_settled,  # noqa: E402
                     _start_in_own_job, free_port)

from app import sidecar  # noqa: E402

CREATE_NO_WINDOW = 0x08000000
STOP_LIMIT = 10.0          # контракт § 2: потом оболочка снимает задание
READY_LIMIT = 90.0         # первый старт: миграции, копия — с большим запасом
STAGES = ["Se pornește DentPilot…", "Se pregătește baza de date…",
          "Se face copia de rezervă…", "Se pornește registrul…"]
SMOKE_KEY = "smoke1234"    # пароль серверной ветки для обхода страниц (smoke_exe.py)


def app_version() -> str:
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"',
                  (BOT / "app" / "engine.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


class Lab:
    """Временная папка: данные, TEMP и (для собранного) сама программа.
    `smoke` — лаборатория обхода страниц: без demo.flag (стена активации
    свежей установки) и с dental.env дымового теста (`smoke_build.py`)."""

    def __init__(self, exe: pathlib.Path | None = None, smoke: bool = False) -> None:
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_engine_"))
        self.data = self.dir / "data"
        self.tmp = self.dir / "tmp"
        self.tmp.mkdir()
        self.smoke = smoke
        self.exe = None
        if exe is not None:
            prog = self.dir / "prog"
            shutil.copytree(exe.parent, prog / "engine")
            if not smoke:
                (prog / "demo.flag").write_text("", encoding="ascii")
                # битый install.json: при первом старте — warn, запуск идёт
                (prog / "install.json").write_text("{stricat", encoding="ascii")
            self.exe = prog / "engine" / exe.name
        if smoke:
            self.data.mkdir()
            (self.data / "dental.env").write_text(
                "TELEGRAM_TOKEN=dpapi:smoke-nu-rasshifruesh\n"
                f"ADMIN_KEY={SMOKE_KEY}\n", encoding="utf-8")

    def env(self, port: int) -> dict:
        lab, tmp = self.data, self.tmp
        env = {k: v for k, v in os.environ.items() if not k.startswith("DENTART_")}
        env.update({"DENTART_SHELL": "tauri", "DENTART_SHELL_TOKEN": secrets.token_hex(16),
                    "DENTART_DATA_DIR": str(lab), "TEMP": str(tmp), "TMP": str(tmp),
                    "DENTART_PORT": str(port),
                    "DENTART_PROFILE_DIR": str(self.dir / "webview"),
                    "DENTART_UPDATE_CHECK": "off"})
        if not self.smoke:            # обход страниц: токен из dental.env (grandfather)
            env["TELEGRAM_TOKEN"] = ""
        else:
            env.pop("TELEGRAM_TOKEN", None)
        return env

    def drop(self) -> None:
        _rmtree_settled(self.dir)


class Engine:
    """Один запуск движка: трубы, чтение событий, код выхода."""

    _n = 0

    def __init__(self, lab: Lab, port: int) -> None:
        Engine._n += 1
        self.lab, self.port, self.n = lab, port, Engine._n
        self.lines: list[str] = []
        self.events: list[dict] = []
        self._cv = threading.Condition()
        self._eof = False
        self.proc = self.job = None
        self._err = None
        self._reader = None

    def start(self) -> "Engine":
        if self.lab.exe is not None:
            args, cwd = [str(self.lab.exe)], str(self.lab.exe.parent)
        else:
            args, cwd = [str(PYTHON), str(BOT / "desktop.py")], str(BOT)
        self._err = (self.lab.dir / f"engine-{self.n}.err").open("wb")
        self.proc, self.job = _start_in_own_job(
            args, flags=CREATE_NO_WINDOW, cwd=cwd, env=self.lab.env(self.port),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        return self

    def _read(self) -> None:
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            with self._cv:
                self.lines.append(line)
                if line.startswith(sidecar.PREFIX):
                    try:
                        self.events.append(json.loads(line[len(sidecar.PREFIX):]))
                    except ValueError:
                        pass
                self._cv.notify_all()
        with self._cv:
            self._eof = True
            self._cv.notify_all()

    def wait_event(self, names: set, timeout: float) -> dict | None:
        end = time.time() + timeout
        with self._cv:
            while True:
                for ev in self.events:
                    if ev.get("event") in names:
                        return ev
                left = end - time.time()
                if left <= 0 or self._eof:
                    return None
                self._cv.wait(left)

    def kinds(self) -> list[str]:
        with self._cv:
            return [ev.get("event", "?") for ev in self.events]

    def send_stop(self) -> float:
        self.proc.stdin.write(b'{"v":1,"cmd":"stop"}\n')
        self.proc.stdin.flush()
        return time.time()

    def close_stdin(self) -> float:
        self.proc.stdin.close()
        return time.time()

    def wait_exit(self, since: float, timeout: float) -> tuple[int | None, float]:
        try:
            code = self.proc.wait(timeout=max(0.1, since + timeout - time.time()))
        except subprocess.TimeoutExpired:
            return None, time.time() - since
        if self._reader is not None:
            self._reader.join(3)
        return code, time.time() - since

    def tail(self) -> str:
        err = ""
        try:
            self._err.flush()
            err = (self.lab.dir / f"engine-{self.n}.err").read_text("utf-8", "replace")[-800:]
        except (OSError, ValueError):
            pass
        log = ""
        try:
            log = (self.lab.data / "data" / "dentpilot.log").read_text("utf-8", "replace")[-1200:]
        except OSError:
            pass
        return (f"\n  stdout: {self.lines[-6:]}\n  stderr: {err}\n  dentpilot.log: …{log}")

    def close(self) -> None:
        """Погасить всё дерево (живое или нет) и отпустить файлы."""
        if self.job is not None:
            _end_job(self.job)
            self.job = None
        elif self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)
        for f in (getattr(self.proc, "stdin", None), getattr(self.proc, "stdout", None), self._err):
            try:
                if f is not None:
                    f.close()
            except OSError:
                pass


def port_free(port: int) -> bool:
    """Никто не слушает: обычный bind проходит. ⚠️ Не EXCLUSIVE: соединения
    сервера в TIME_WAIT держат порт от исключительной привязки и после выхода."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def health(port: int) -> bytes:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return r.read()
    except OSError:
        return b""


# ---------- сценарии ----------

def _ready(res: Result, e: Engine, tag: str) -> dict | None:
    ev = e.wait_event({"ready", "busy", "fatal"}, READY_LIMIT)
    if res.ok(f"{tag}: движок сказал ready", ev is not None and ev.get("event") == "ready",
              f"пришло {ev!r}, события {e.kinds()}{e.tail()}"):
        return ev
    return None


def _stopped(res: Result, e: Engine, tag: str, since: float, timing: dict) -> None:
    code, secs = e.wait_exit(since, STOP_LIMIT + 5)
    timing[tag] = secs
    res.check(f"{tag}: код выхода 0", code, sidecar.EXIT_STOP)
    res.ok(f"{tag}: остановка не дольше {STOP_LIMIT:.0f} с", secs <= STOP_LIMIT,
           f"{secs:.1f} с{e.tail()}")
    res.ok(f"{tag}: порт свободен", port_free(e.port), f"порт {e.port} всё ещё занят")


def scenario_stop(res: Result, lab: Lab, timing: dict) -> None:
    tag = "stop"
    e = Engine(lab, free_port())
    t0 = time.time()
    e.start()
    try:
        ready = _ready(res, e, tag)
        if ready is None:
            return
        timing["ready"] = time.time() - t0
        first = e.events[0]
        res.check("hello — первое слово движка", first.get("event"), "hello")
        res.check("hello: версия программы", first.get("version"), app_version())
        res.ok("hello: цвет темы #RRGGBB",
               bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", str(first.get("color", "")))), repr(first))
        if lab.exe is not None:       # из исходников pid у настоящего python, не у пускача venv
            res.check("hello: pid процесса движка", first.get("pid"), e.proc.pid)
        else:
            res.ok("hello: pid — число", isinstance(first.get("pid"), int), repr(first))
        if lab.exe is not None:
            warns = [ev for ev in e.events if ev.get("event") == "warn"]
            res.ok("битый install.json: warn после hello, запуск идёт",
                   len(warns) == 1 and "install.json" in warns[0].get("text", "")
                   and e.kinds().index("warn") == 1, repr(e.kinds()) + repr(warns))
        stages = [ev for ev in e.events if ev.get("event") == "stage"]
        res.check("stage: те же этапы, что у заставки окна",
                  [s.get("text") for s in stages], STAGES)
        pcts = [s.get("pct") for s in stages]
        res.ok("stage: полоска только вперёд", pcts == sorted(pcts) and all(
            isinstance(p, int) for p in pcts), repr(pcts))
        res.check("ready: поля контракта",
                  {k: ready.get(k) for k in ("v", "url", "port", "session", "data", "lan")},
                  {"v": 1, "url": f"http://127.0.0.1:{e.port}/admin", "port": e.port,
                   "session": "keep", "data": str(lab.data), "lan": False})
        res.ok("после ready /health отвечает отпечатком DentPilot",
               b'"dentpilot"' in health(e.port), "нет ответа")
        _stopped(res, e, tag, e.send_stop(), timing)
        data = lab.data / "data"
        res.ok("база закрыта: -wal и -shm сброшены",
               not (data / "dental.db-wal").exists() and not (data / "dental.db-shm").exists(),
               f"в папке: {sorted(p.name for p in data.glob('dental.db*'))}")
        res.ok("в stdout — только строки DP1",
               bool(e.lines) and all(ln.startswith(sidecar.PREFIX) for ln in e.lines),
               f"чужие строки: {[ln for ln in e.lines if not ln.startswith(sidecar.PREFIX)][:3]}")
        log = (data / "dentpilot.log").read_text("utf-8", "replace")
        res.ok("лог: остановка по слову оболочки, сервер остановлен",
               "остановка по слову оболочки (stop)" in log and "сервер остановлен за" in log,
               log[-600:])
    finally:
        e.close()


def scenario_eof(res: Result, lab: Lab, timing: dict) -> None:
    tag = "eof"
    e = Engine(lab, free_port()).start()
    try:
        if _ready(res, e, tag) is None:
            return
        _stopped(res, e, tag, e.close_stdin(), timing)
    finally:
        e.close()


def scenario_busy(res: Result, lab: Lab, timing: dict) -> None:
    tag = "busy"
    port = free_port()
    a = Engine(lab, port).start()
    b = None
    try:
        if _ready(res, a, tag + " (первый)") is None:
            return
        b = Engine(lab, port)
        t0 = time.time()
        b.start()
        ev = b.wait_event({"busy", "ready", "fatal"}, 40)
        res.check("второй экземпляр: busy с адресом первого",
                  (ev or {}).get("event") and {"event": ev.get("event"), "url": ev.get("url")},
                  {"event": "busy", "url": f"http://127.0.0.1:{port}/admin"})
        res.check("второй экземпляр: hello, потом busy", b.kinds(), ["hello", "busy"])
        code, secs = b.wait_exit(t0, 30)
        timing["busy"] = secs
        res.check("второй экземпляр: код выхода 3", code, sidecar.EXIT_BUSY)
        res.ok("первый жив после второго", b'"dentpilot"' in health(port), "первый не отвечает")
        _stopped(res, a, tag + " (первый)", a.send_stop(), timing)
    finally:
        if b is not None:
            b.close()
        a.close()


def scenario_fatal(res: Result, lab: Lab, timing: dict) -> None:
    port = free_port()
    hold = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        hold.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    hold.bind(("127.0.0.1", port))
    hold.listen(8)
    e = Engine(lab, port)
    try:
        t0 = time.time()
        e.start()
        ev = e.wait_event({"fatal", "ready", "busy"}, 40)
        res.ok("чужая программа на порту: fatal про порт",
               (ev or {}).get("event") == "fatal" and f"portul {port}" in ev.get("text", "")
               and ev.get("log", "").endswith("dentpilot.log"), f"пришло {ev!r}{e.tail()}")
        code, secs = e.wait_exit(t0, 30)
        timing["fatal"] = secs
        res.check("fatal: код выхода 2", code, sidecar.EXIT_FATAL)
    finally:
        e.close()
        hold.close()


def scenario_early(res: Result, lab: Lab, timing: dict) -> None:
    e = Engine(lab, free_port()).start()
    try:
        hello = e.wait_event({"hello"}, 40)
        if not res.ok("early: hello пришёл", hello is not None, e.tail()):
            return
        code, secs = e.wait_exit(e.close_stdin(), 30)
        timing["early"] = secs
        res.check("stdin закрыт под заставкой: код 0", code, sidecar.EXIT_STOP)
        res.ok("и сервер не поднимался: ready не было", "ready" not in e.kinds(), repr(e.kinds()))
    finally:
        e.close()


def scenario_base(res: Result, lab: Lab, timing: dict) -> None:
    """Собранный: корень программы — родитель engine\\. Профиль клиники при
    первом старте берётся по `BASE\\demo.flag` — демо, а не пустой шаблон."""
    got = json.loads((lab.data / "clinic.json").read_text(encoding="utf-8"))
    demo = json.loads((BOT / "app" / "clinic.json").read_text(encoding="utf-8"))
    res.ok("корень программы — папка над engine\\ (demo.flag оттуда)", got == demo,
           "профиль клиники — не демо: лаунчер искал demo.flag/install.json "
           "в engine\\, а не в папке DentPilot.exe")


def scenario_pages(res: Result, exe: pathlib.Path, timing: dict) -> None:
    """Собранный: страницы открываются (`tests/smoke_exe.py`, фаза `wall`) —
    `/health` отвечает и без единого файла на диске, а потерянный `--add-data`
    виден только обходом. Своя лаборатория: свежая установка без demo.flag."""
    lab = Lab(exe, smoke=True)
    e = Engine(lab, free_port())
    try:
        e.start()
        if _ready(res, e, "pages") is None:
            return
        t0 = time.time()
        out = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "smoke_exe.py"), f"http://127.0.0.1:{e.port}",
             SMOKE_KEY, "wall", str(lab.data)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        timing["pages"] = time.time() - t0
        said = out.stdout or ""
        oks = said.count("   OK  ")
        # ⚠️ И код, и сами проверки: обход, не нашедший что проверять, тоже 0
        res.ok(f"страницы собранного движка открываются (smoke_exe wall, {oks} проверок)",
               out.returncode == 0 and "дымовой тест собранной программы [wall]: OK" in said
               and oks >= 10, (said + (out.stderr or ""))[-1500:])
        _stopped(res, e, "pages", e.send_stop(), timing)
    finally:
        e.close()
        lab.drop()


SCENARIOS = [scenario_stop, scenario_eof, scenario_busy, scenario_fatal, scenario_early]


def run(res: Result, exe: pathlib.Path | None = None) -> dict:
    """Все сценарии на одной лаборатории. Возвращает замеры, секунды."""
    lab = Lab(exe)
    timing: dict = {}
    try:
        for sc in SCENARIOS + ([scenario_base] if exe is not None else []):
            sc(res, lab, timing)
    finally:
        lab.drop()
    if exe is not None:
        scenario_pages(res, exe, timing)
    return timing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", help="собранный движок: …\\DentPilot-Engine\\DentPilot-Engine.exe")
    a = ap.parse_args()
    exe = None
    if a.exe:
        exe = pathlib.Path(a.exe)
        exe = (exe if exe.is_absolute() else ROOT / exe).resolve()
        if not exe.exists():
            print(f"нет файла {exe}")
            return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    res = Result()
    timing = run(res, exe)
    for label, why in res.failed:
        print(f"RED {label}\n    {why}")
    print("замеры: " + ", ".join(f"{k} {v:.1f} с" for k, v in timing.items()))
    print(f"{len(res.passed)}/{len(res.passed) + len(res.failed)} проверок, "
          f"{'собранный' if exe else 'исходники'}")
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit(main())
