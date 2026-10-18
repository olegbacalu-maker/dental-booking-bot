# -*- coding: utf-8 -*-
"""Стенд собранной программы Tauri (Т9, 18.10.2026): оболочка и движок вместе.

    .venv-desktop\\Scripts\\python.exe scripts\\shell_check.py --prog dist\\DentPilot
    .venv-desktop\\Scripts\\python.exe scripts\\shell_check.py --prog dist\\DentPilot --out итог.json

`--prog` — папка программы так, как её кладёт мастер установки (контракт
`docs/dentpilot-2/tauri-contract.md` § 1): `DentPilot.exe` — оболочка Tauri,
`engine\\DentPilot-Engine.exe` — движок папкой. Стенд копирует её в
лабораторию как «установленную» и запускает ОБОЛОЧКУ — так, как её запустят
ярлык и автозапуск (`--tray`: окна нет, значок у часов есть); движок
поднимает она сама, в своём задании Windows.

Сценарии — по порядку, лаборатория одна, порт свой:
  start   оболочка `--tray` → движок рядом с ней (`engine\\`, не исходники)
          отвечает `/health` версией программы
  shell   страница программы получила `window.dpShell` v1 с версией оболочки
          (порт отладки WebView2 — как глазами Т6)
  wall    обход страниц свежей установки (`tests/smoke_exe.py wall`, сеет
          пациента для следующей фазы)
  second  второй `DentPilot.exe --tray` выходит с кодом 0, второго движка нет
  quit    честный выход путём человека: `dpShell.send('win/quit')` → вопрос
          оболочки «Închideți DentPilot complet?» → «Да» → оболочка выходит
          с кодом 0, движок остановлен словом (код 0 в журнале оболочки),
          порт свободен, `-wal` сброшен
  grace   тот же exe заново на живой картотеке (`smoke_exe.py grace`)
  kill    снятие процесса оболочки (как «Снять задачу») гасит движок:
          задание Windows оболочки закрывается вместе с ней
⚠️ На `quit` на секунду появляется окно-вопрос оболочки (поверх всех) —
стенд сам нажимает «Да» по PID своей оболочки. Чужие окна не трогаются.

Зачем отдельно от `engine_check.py`: тот запускает движок харнессом на
Python вместо оболочки и проверяет протокол DP1; здесь — что собранная
ОБОЛОЧКА находит собранный движок, говорит с ним и гасит его.
⛔ Лаборатория называет себя корнем данных и TEMP (правило стендов
`test_launcher.suite_port`): без DENTART_DATA_DIR движок ушёл бы в
%ProgramData% — в настоящую картотеку машины. ⛔ Процессы — только по PID:
`DentPilot.exe` — имя и установленной программы Олега (порт 8088).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(BOT))

from harness import Result, _end_job, _rmtree_settled, _start_in_own_job, free_port  # noqa: E402

from engine_check import SMOKE_KEY, app_version, health, port_free  # noqa: E402

SHELL_EXE = "DentPilot.exe"
ENGINE_EXE = "DentPilot-Engine.exe"
READY_LIMIT = 90.0         # первый старт: миграции, копия — с большим запасом
QUIT_LIMIT = 15.0          # оболочка ждёт движок 10 с (контракт § 2), потом снимает задание
KILL_LIMIT = 10.0
QUIT_TEXT = "Închideți DentPilot complet?"     # вопрос оболочки (shell/src/win.rs)


class Lab:
    """Временная папка: «установленная» программа, данные, TEMP, профиль окна.
    Профиль (`DENTART_PROFILE_DIR`) делает оболочку стендом: свой замок
    «один экземпляр» и свой `shell.json`/`shell.log` рядом с профилем —
    иначе второй запуск показал бы окно установленной программы."""

    def __init__(self, prog: pathlib.Path) -> None:
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_shell_"))
        self.prog = self.dir / "prog"
        shutil.copytree(prog, self.prog)
        self.shell = self.prog / SHELL_EXE
        self.engine = self.prog / "engine" / ENGINE_EXE
        self.data = self.dir / "data"
        self.tmp = self.dir / "tmp"
        self.profile = self.dir / "profile" / "webview"
        for d in (self.data, self.tmp, self.profile.parent):
            d.mkdir(parents=True)
        # свежая установка без demo.flag, бот «настроен» (grandfather) —
        # как у дымового теста прежней сборки: так обход видит и /chat
        (self.data / "dental.env").write_text(
            "TELEGRAM_TOKEN=dpapi:smoke-nu-rasshifruesh\n"
            f"ADMIN_KEY={SMOKE_KEY}\n", encoding="utf-8")
        self.port = free_port()
        self.cdp = free_port()

    @property
    def shell_log(self) -> pathlib.Path:
        return self.profile.parent / "shell.log"

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DENTART_", "DENTPILOT_", "WEBVIEW2_"))
               and k not in ("TELEGRAM_TOKEN", "ADMIN_KEY")}
        env.update({"DENTART_DATA_DIR": str(self.data), "TEMP": str(self.tmp),
                    "TMP": str(self.tmp), "DENTART_PORT": str(self.port),
                    "DENTART_PROFILE_DIR": str(self.profile),
                    "DENTART_UPDATE_CHECK": "off",
                    # глаза стенда: страница программы по протоколу отладки
                    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={self.cdp}"})
        return env

    def drop(self) -> None:
        _rmtree_settled(self.dir, budget=15.0)


class Shell:
    """Один запуск оболочки в своём задании (вложенном в задание стенда)."""

    def __init__(self, lab: Lab, *args: str) -> None:
        self.lab = lab
        self.t0 = time.time()
        self.proc, self.job = _start_in_own_job([str(lab.shell), *args], cwd=str(lab.prog),
                                                env=lab.env())

    def wait(self, timeout: float) -> int | None:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def close(self) -> None:
        """Погасить всё, что осталось (дерево оболочки и WebView2)."""
        if self.job is not None:
            _end_job(self.job)
            self.job = None
        elif self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)


# ---------- Windows: процессы и окно-вопрос ----------

def _k32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return k32


def process_image(pid: int) -> str | None:
    """Путь exe ЖИВОГО процесса; None — процесса нет (или он уже вышел)."""
    import ctypes
    from ctypes import wintypes
    k32 = _k32()
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        k32.CloseHandle(h)


def gone(pid: int, timeout: float) -> float | None:
    """Секунды до исчезновения процесса; None — жив и после `timeout`."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if process_image(pid) is None:
            return time.time() - t0
        time.sleep(0.05)
    return None


def answer_dialog(pid: int, want: str, timeout: float) -> str:
    """Найти окно-вопрос (класс #32770) процесса `pid` с текстом `want` и
    нажать «Да». Возвращает текст вопроса; пусто — окна не было."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u32.GetDlgItemTextW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPWSTR, ctypes.c_int]
    u32.IsWindowVisible.argtypes = [wintypes.HWND]
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    end = time.time() + timeout
    while time.time() < end:
        found: list[tuple[int, str]] = []

        def each(hwnd, _lp):
            owner = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and u32.IsWindowVisible(hwnd):
                cls = ctypes.create_unicode_buffer(64)
                u32.GetClassNameW(hwnd, cls, 64)
                if cls.value == "#32770":
                    text = ctypes.create_unicode_buffer(1024)
                    u32.GetDlgItemTextW(hwnd, 0xFFFF, text, 1024)   # текст MessageBox
                    found.append((hwnd, text.value))
            return True

        u32.EnumWindows(proc(each), 0)
        for hwnd, text in found:
            if want in text:
                u32.PostMessageW(hwnd, 0x0111, 6, 0)               # WM_COMMAND, IDYES
                return text
        time.sleep(0.1)
    return ""


# ---------- протокол отладки WebView2 (CDP) без сторонних пакетов ----------

class _WS:
    """Самый простой клиент WebSocket (RFC 6455): текстовые кадры, без
    расширений. В `.venv-desktop` чужих пакетов не ставим — всё лишнее там
    однажды уедет в exe."""

    def __init__(self, url: str, timeout: float) -> None:
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("CDP: соединение закрыто при рукопожатии")
            self.buf += chunk
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"CDP: {head[:80]!r}")

    def send(self, text: str) -> None:
        data, mask = text.encode(), os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + n.to_bytes(2, "big") if n < 65536 else
                                bytes([0x80 | 127]) + n.to_bytes(8, "big"))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _take(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("CDP: соединение закрыто")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self) -> str:
        msg = b""
        while True:
            b0, b1 = self._take(2)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._take(2), "big")
            elif n == 127:
                n = int.from_bytes(self._take(8), "big")
            mask = self._take(4) if b1 & 0x80 else b""
            data = self._take(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            op = b0 & 0x0F
            if op == 8:
                raise ConnectionError("CDP: страница закрыла соединение")
            if op in (9, 10):
                continue
            msg += data
            if b0 & 0x80:
                return msg.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


def page_target(cdp: int, origin: str, timeout: float) -> dict | None:
    """Вкладка WebView2 с адресом движка (полоса меню — своя страница, не она)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{cdp}/json/list", timeout=3) as r:
                for t in json.load(r):
                    if t.get("type") == "page" and str(t.get("url", "")).startswith(origin):
                        return t
        except (OSError, ValueError):
            pass
        time.sleep(0.3)
    return None


def evaluate(target: dict, expr: str, timeout: float = 10.0):
    ws = _WS(target["webSocketDebuggerUrl"], timeout)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "returnByValue": True}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 1:
                return ((m.get("result") or {}).get("result") or {}).get("value")
    finally:
        ws.close()


_WAIT = "__dp_wait__"


def page_eval(target: dict, origin: str, expr: str, timeout: float = 20.0):
    """`expr` в ЗАГРУЖЕННОЙ странице движка. ⚠️ Адрес вкладки в /json/list
    меняется уже в начале перехода, а исполнение ещё идёт в прежнем документе
    — заставке оболочки, где `dpShell` нет (поймано стендом: 1 из 3 прогонов
    читал `null`). Поэтому сперва документ: свой адрес и readyState."""
    guard = (f"(location.origin === {json.dumps(origin)} && document.readyState === 'complete')"
             f" ? ({expr}) : {json.dumps(_WAIT)}")
    end = time.time() + timeout
    while True:
        try:
            got = evaluate(target, guard)
        except (OSError, ValueError, ConnectionError):
            got = _WAIT
        if got != _WAIT or time.time() > end:
            return None if got == _WAIT else got
        time.sleep(0.2)


# ---------- сценарии ----------

def wait_health(lab: Lab, sh: "Shell", timeout: float) -> tuple[dict | None, str]:
    """`/health` движка под оболочкой `sh`. Не ответил — вторым значением
    причина: оболочка вышла, движок сказал `fatal`/`busy` (журнал оболочки
    пишет каждое его слово), или просто не успел. Ждать весь потолок, когда
    исход уже известен, незачем."""
    end = time.time() + timeout
    while time.time() < end:
        raw = health(lab.port)
        if b'"dentpilot"' in raw:
            try:
                return json.loads(raw), ""
            except ValueError:
                return None, f"/health не разобрался: {raw[:120]!r}"
        if sh.proc.poll() is not None:
            return None, f"оболочка вышла с кодом {sh.proc.returncode}"
        try:
            log = lab.shell_log.read_text("utf-8", "replace")
        except OSError:
            log = ""
        for word in ("fatal", "busy"):
            if f'"event":"{word}"' in log:
                return None, f"движок сказал {word}"
        time.sleep(0.3)
    return None, f"за {timeout:.0f} с ответа нет, оболочка жива"


def engine_pid(lab: Lab, timeout: float = 10.0) -> tuple[int, str]:
    """PID и путь движка — из журнала оболочки («engine started pid=…: …»)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            log = lab.shell_log.read_text("utf-8", "replace")
        except OSError:
            log = ""
        found = re.findall(r"engine started pid=(\d+): (.+)", log)
        if found:
            return int(found[-1][0]), found[-1][1].strip()
        time.sleep(0.2)
    return 0, ""


def shell_tail(lab: Lab) -> str:
    try:
        return "\n  shell.log: …" + lab.shell_log.read_text("utf-8", "replace")[-1200:]
    except OSError:
        return "\n  shell.log: нет"


def pages(res: Result, lab: Lab, phase: str, timing: dict) -> None:
    t0 = time.time()
    out = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "smoke_exe.py"), f"http://127.0.0.1:{lab.port}",
         SMOKE_KEY, phase, str(lab.data)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    timing[phase] = time.time() - t0
    said = out.stdout or ""
    oks = said.count("   OK  ")
    # ⚠️ И код, и сами проверки: обход, не нашедший что проверять, тоже 0
    res.ok(f"{phase}: страницы собранной программы открываются (smoke_exe, {oks} проверок)",
           out.returncode == 0 and f"дымовой тест собранной программы [{phase}]: OK" in said
           and oks >= 10, (said + (out.stderr or ""))[-1500:])


def start(res: Result, lab: Lab, tag: str, timing: dict) -> tuple[Shell, dict | None, int]:
    # ⚠️ Порт выбран один раз на лабораторию, а между запусками он свободен:
    # прогон соседней сессии мог взять его себе (free_port). Тогда движок честно
    # скажет fatal про чужой порт — это не дефект сборки, поэтому — новый порт.
    if not port_free(lab.port):
        lab.port = free_port()
    sh = Shell(lab, "--tray")
    h, why = wait_health(lab, sh, READY_LIMIT)
    timing[f"ready{tag}"] = time.time() - sh.t0
    res.ok(f"start{tag}: оболочка подняла движок, /health отвечает", h is not None,
           f"{why}; порт {lab.port} {'свободен' if port_free(lab.port) else 'занят'}" + shell_tail(lab))
    pid, what = engine_pid(lab)
    image = process_image(pid) if pid else None
    res.ok(f"start{tag}: движок — собранный, из engine\\ рядом с оболочкой",
           bool(image) and pathlib.Path(image).resolve() == lab.engine.resolve(),
           f"pid {pid}, журнал: {what!r}, процесс: {image!r}, ждали {lab.engine}")
    return sh, h, pid


def scenario_all(res: Result, lab: Lab, timing: dict, facts: dict) -> None:
    want = app_version()
    sh, h, pid = start(res, lab, "", timing)
    try:
        if h is None:
            return
        facts["version"] = h.get("version", "")
        res.check("/health: версия программы = APP_VERSION", facts["version"], want)

        origin = f"http://127.0.0.1:{lab.port}"
        target = page_target(lab.cdp, origin + "/", 30.0)
        shell_obj = None
        if res.ok("shell: страница программы в окне оболочки (порт отладки WebView2)",
                  target is not None, f"вкладки с {origin}/ нет за 30 с"):
            shell_obj = page_eval(target, origin, "JSON.stringify(window.dpShell ? {v: dpShell.v, "
                                                  "version: dpShell.version, send: typeof dpShell.send} : null)")
            shell_obj = json.loads(shell_obj) if isinstance(shell_obj, str) else None
            facts["shell_version"] = (shell_obj or {}).get("version", "")
            res.check("shell: странице выдан dpShell v1 с версией оболочки = APP_VERSION",
                      shell_obj, {"v": 1, "version": want, "send": "function"})

        pages(res, lab, "wall", timing)

        second = Shell(lab, "--tray")
        code = second.wait(15.0)
        timing["second"] = time.time() - second.t0
        second.close()
        res.check("second: второй запуск уходит сам, код 0", code, 0)
        res.ok("second: первый жив и движок прежний",
               b'"dentpilot"' in health(lab.port) and engine_pid(lab, 1.0)[0] == pid,
               shell_tail(lab))

        if target is None:
            return
        sent = page_eval(target, origin, "window.dpShell ? (dpShell.send('win/quit'), 1) : 0")
        asked = answer_dialog(sh.proc.pid, QUIT_TEXT, 10.0) if sent == 1 else ""
        t0 = time.time()
        if not res.ok("quit: оболочка спросила «закрыть совсем?» — стенд ответил «Да»",
                      bool(asked), (f"dpShell.send не позван (ответ страницы {sent!r})" if sent != 1
                                    else "окна-вопроса оболочки не было за 10 с") + shell_tail(lab)):
            return
        code = sh.wait(QUIT_LIMIT)
        timing["quit"] = time.time() - t0
        res.check("quit: оболочка вышла с кодом 0", code, 0)
        res.ok("quit: движка нет", gone(pid, 5.0) is not None, f"pid {pid} жив")
        res.ok("quit: порт свободен", port_free(lab.port), f"порт {lab.port} занят")
        log = shell_tail(lab)
        stopped = re.search(r"exit: engine stopped in ([\d.]+) s, code Some\(0\)", log)
        res.ok("quit: движок остановлен словом, код 0 (журнал оболочки)", bool(stopped), log)
        if stopped:
            timing["engine-stop"] = float(stopped.group(1))
        dbs = sorted(p.name for p in (lab.data / "data").glob("dental.db*"))
        res.ok("quit: база закрыта, -wal и -shm сброшены",
               "dental.db" in dbs and not any(n.endswith(("-wal", "-shm")) for n in dbs), repr(dbs))
        try:
            elog = (lab.data / "data" / "dentpilot.log").read_text("utf-8", "replace")
        except OSError:
            elog = ""
        res.ok("quit: в журнале движка — остановка по слову оболочки",
               "остановка по слову оболочки (stop)" in elog, elog[-600:])
    finally:
        sh.close()

    sh, h, pid = start(res, lab, " (2)", timing)
    try:
        if h is None:
            return
        pages(res, lab, "grace", timing)
        t0 = time.time()
        sh.proc.kill()                       # только оболочку: задание движка — её
        sh.proc.wait(10)
        secs = gone(pid, KILL_LIMIT)
        timing["kill"] = time.time() - t0
        res.ok("kill: снятие оболочки гасит движок", secs is not None,
               f"движок pid {pid} жив через {KILL_LIMIT:.0f} с после оболочки")
        end = time.time() + 5
        while not port_free(lab.port) and time.time() < end:
            time.sleep(0.1)
        res.ok("kill: порт свободен", port_free(lab.port), f"порт {lab.port} занят")
    finally:
        sh.close()


def file_version(path: pathlib.Path) -> str:
    from app import authenticode
    v = authenticode.file_version(path)
    return ".".join(str(n) for n in v[:3]) if v else ""


def run(res: Result, prog: pathlib.Path) -> tuple[dict, dict]:
    facts = {"shell_file": file_version(prog / SHELL_EXE),
             "engine_file": file_version(prog / "engine" / ENGINE_EXE)}
    want = app_version()
    res.check("свойства DentPilot.exe: версия = APP_VERSION", facts["shell_file"], want)
    res.check("свойства DentPilot-Engine.exe: версия = APP_VERSION", facts["engine_file"], want)
    lab = Lab(prog)
    timing: dict = {}
    try:
        scenario_all(res, lab, timing, facts)
    finally:
        lab.drop()
    return timing, facts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prog", required=True, help="папка программы: DentPilot.exe + engine\\")
    ap.add_argument("--out", help="итог JSON для сборки (версии, замеры, ok)")
    a = ap.parse_args()
    prog = pathlib.Path(a.prog)
    prog = (prog if prog.is_absolute() else ROOT / prog).resolve()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for f in (prog / SHELL_EXE, prog / "engine" / ENGINE_EXE):
        if not f.exists():
            print(f"нет файла {f}")
            return 2
    res = Result()
    timing, facts = run(res, prog)
    for label in res.passed:
        print(f"   OK   {label}")
    for label, why in res.failed:
        print(f"   RED  {label}\n        {why}")
    print("   замеры: " + ", ".join(f"{k} {v:.1f} с" for k, v in timing.items()))
    total = len(res.passed) + len(res.failed)
    print(f"   оболочка + движок: {len(res.passed)}/{total} проверок")
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(
            {"ok": not res.failed, **facts, "timing": {k: round(v, 2) for k, v in timing.items()},
             "passed": len(res.passed), "total": total}, ensure_ascii=False), encoding="utf-8")
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit(main())
