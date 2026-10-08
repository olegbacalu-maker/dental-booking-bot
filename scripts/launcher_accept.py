# -*- coding: utf-8 -*-
"""Приёмочный стенд лаунчера (08.10.2026): постоянный профиль окна, вход, один
экземпляр, выход — поведение ПРОДУКТА, а не отдельные функции.
    python scripts\\launcher_accept.py           оба режима: standalone и shared_pc
    python scripts\\launcher_accept.py shared_pc  только общий ПК
Запускается НАСТОЯЩИЙ `bot/desktop.py` из исходников — с окном WebView2 на
экране (~2 мин), поэтому не в CI и не в `.\\dev test`. Лаборатория: папка данных,
профиль окна и TEMP — во временной папке, порт 8101; окном правим по CDP
(`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=…`).

Сценарий standalone (вход переживает перезапуск):
  1. старт → экран установки PIN → PIN задан → журнал
  2. фиша пациента открыта, в localStorage метка настроек
  3. закрыть окно (подтверждение) → процесс вышел
  4. старт снова → журнал БЕЗ входа, метка на месте, в TEMP нет временных профилей
  5. второй запуск при открытой программе → вышел сам, окно одно, оно на переднем плане
  6. выход из учётки → закрыть → старт → экран входа
Сценарий shared_pc (вход НЕ переживает перезапуск): вход → закрыть → старт → экран входа.
⛔ Красный стенд называет шаг. Зелёный доказывает ровно эти шаги, не больше.
"""
from __future__ import annotations

import ctypes
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import Client  # noqa: E402
from odo_shots import CDP, Page  # noqa: E402

PY = ROOT / ".venv-desktop" / "Scripts" / "python.exe"     # там pywebview
PIN = "123456"                                             # PIN клиники: 4–6 цифр
PORT = 8101
# ⛔ Свой порт отладки: 9337–9349 заняты соседними стендами.
CDP_PORT = 9355
TITLE = f"DentPilot — registrul clinicii · :{PORT}"       # заголовок окна на этом порту
U32 = ctypes.windll.user32
WM_CLOSE, WM_COMMAND, IDOK = 0x0010, 0x0111, 1


class Lab:
    """Временная папка: данные, профиль окна и TEMP лаунчера — всё внутри."""

    def __init__(self, mode: str) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_launcher_"))
        self.lab = self.tmp / "data"
        self.profile = self.tmp / "webview"
        self.mode = mode

    def env(self) -> dict:
        tmp, lab = self.tmp, self.lab
        return {**os.environ,
                "DENTART_DATA_DIR": str(lab), "TEMP": str(tmp), "TMP": str(tmp),
                "DENTART_PORT": str(PORT), "DENTART_PROFILE_DIR": str(self.profile),
                "DENTART_MODE": self.mode, "PYTHONIOENCODING": "utf-8",
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS":
                    f"--remote-debugging-port={CDP_PORT} --remote-allow-origins=*"}

    def drop(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def http_ok(url: str, timeout: float = 1.0) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def pick(value, pred):
    """`value`, если `pred(value)`, иначе None — условие для `wait`."""
    return value if pred(value) else None


def wait(cond, timeout: float, step: float = 0.25):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


def windows_of(pid: int | None = None, cls: str | None = None) -> list[int]:
    """Видимые верхние окна: по процессу и/или классу; без класса — окно программы
    на НАШЕМ порту (заголовок с портом: окно настоящей установки на 8088 не в счёт)."""
    out: list[int] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not U32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        U32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if pid is not None and owner.value != pid:
            return True
        if cls:
            buf = ctypes.create_unicode_buffer(64)
            U32.GetClassNameW(hwnd, buf, 64)
            if buf.value != cls:
                return True
        else:
            n = U32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            U32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value != TITLE:
                return True
        out.append(hwnd)
        return True
    U32.EnumWindows(proto(cb), 0)
    return out


class Run:
    """Один запуск лаунчера: процесс, окно, CDP-страница окна."""

    def __init__(self, lab: Lab) -> None:
        self.lab = lab
        self.before = set(windows_of())
        # ⚠️ `.venv-desktop\Scripts\python.exe` — редиректор venv: окно и сервер
        # живут у его ДОЧЕРНЕГО процесса, поэтому pid окна берётся с самого окна
        self.proc = subprocess.Popen([str(PY), str(BOT / "desktop.py")], cwd=str(BOT),
                                     env=lab.env(), stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self.cdp: CDP | None = None
        self.page: Page | None = None
        self.hwnd = 0
        self.pid = 0

    def attach(self, timeout: float = 60.0) -> str:
        """Дождаться сервера и окна; вернуть адрес, на котором окно встало после заставки."""
        if not wait(lambda: http_ok(f"http://127.0.0.1:{PORT}/health"), timeout):
            raise RuntimeError("сервер не поднялся")

        def target():
            raw = http_ok(f"http://127.0.0.1:{CDP_PORT}/json/list", 1.0)
            if not raw:
                return None
            pages = [t for t in json.loads(raw) if t.get("type") == "page"]
            return pages[0]["webSocketDebuggerUrl"] if pages else None
        ws = wait(target, timeout)
        if not ws:
            raise RuntimeError("окно WebView2 не открыло порт отладки")
        self.cdp = CDP(ws)
        for dom in ("Page", "Runtime"):
            self.cdp.cmd(f"{dom}.enable")
        self.page = Page(self.cdp, f"http://127.0.0.1:{PORT}")
        # заставка (about:blank/html) → журнал: ждём адрес нашего сервера
        href = wait(lambda: pick(self.href(), lambda h: h.startswith("/")), timeout)
        if not href:
            raise RuntimeError("окно не ушло с заставки")
        self.cdp.drain(1.0)
        self.hwnd = wait(lambda: next((h for h in windows_of() if h not in self.before), None), 20.0) or 0
        if self.hwnd:
            owner = wintypes.DWORD()
            U32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(owner))
            self.pid = owner.value
        return self.href()

    def href(self) -> str:
        try:
            v = self.page.js("location.href")
        except Exception:  # noqa: BLE001 — страница перегружается
            return ""
        base = f"http://127.0.0.1:{PORT}"
        return v[len(base):] if isinstance(v, str) and v.startswith(base) else ""

    def submit(self, fields: dict, timeout: float = 15.0) -> str:
        """Заполнить форму на текущей странице и отправить; вернуть новый адрес."""
        js = "".join(f"document.querySelector('input[name={k}]').value={json.dumps(v)};"
                     for k, v in fields.items())
        before = self.href()
        self.page.js(js + "document.querySelector('form').submit(); 1")
        return wait(lambda: pick(self.href(), lambda h: h and h != before), timeout) or self.href()

    def close(self, timeout: float = 25.0) -> bool:
        """Закрыть окно крестиком: WM_CLOSE → подтверждение (MessageBox) → OK."""
        if not self.hwnd:
            return False
        U32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        dlg = wait(lambda: (d := windows_of(self.pid, "#32770")) and d[0], 10.0)
        if dlg:
            U32.SendMessageW(dlg, WM_COMMAND, IDOK, 0)
        try:
            self.proc.wait(timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def kill(self) -> None:
        """Снести дерево процесса (редиректор + python с окном)."""
        if self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                pass


def temp_profiles(tmp: pathlib.Path) -> list[str]:
    """Временные профили WebView2 в TEMP лаборатории — их не должно быть."""
    return [p.name for p in tmp.glob("tmp*") if (p / "EBWebView").exists()]


def scenario_standalone(res: list) -> None:
    lab = Lab("standalone")
    run = Run(lab)
    second = None
    try:
        href = run.attach()
        res.append(("1 первый старт — экран установки PIN", href.startswith("/admin/setup"), href))
        href = run.submit({"pin1": PIN, "pin2": PIN})
        if href.startswith("/admin/login"):
            href = run.submit({"password": PIN})
        res.append(("1 PIN задан — журнал", href.startswith("/admin") and "login" not in href
                    and "setup" not in href, href))

        c = Client(f"http://127.0.0.1:{PORT}").login(PIN)
        r = c.post("/admin/patients/new", name="Proba Launcher", phone="069555001")
        pid = (r.location or "").split("/admin/patient/")[-1].split("?")[0]
        run.page.go(f"/admin/patient/{pid}")
        ok = bool(wait(lambda: run.page.js("!!document.querySelector('.hero')"), 15.0))
        res.append(("2 фиша пациента открыта в окне", ok, run.href()))
        run.page.js("localStorage.setItem('dp_bench', 'ok'); 1")

        res.append(("3 окно закрыто подтверждением, процесс вышел", run.close(), f"код {run.proc.poll()}"))
        res.append(("3 профиль окна постоянный (EBWebView в папке профиля)",
                    (lab.profile / "EBWebView").exists(), str(lab.profile)))

        run = Run(lab)
        href = run.attach()
        res.append(("4 второй старт — журнал без входа", href.startswith("/admin") and "login" not in href
                    and "setup" not in href, href))
        kept = run.page.js("localStorage.getItem('dp_bench')")
        res.append(("4 метка настроек пережила перезапуск", kept == "ok", repr(kept)))
        junk = temp_profiles(lab.tmp)
        res.append(("4 временных профилей WebView2 в TEMP нет", not junk, ", ".join(junk) or "чисто"))

        hwnd1 = run.hwnd
        second = subprocess.Popen([str(PY), str(BOT / "desktop.py")], cwd=str(BOT), env=lab.env(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            code = second.wait(30)
        except subprocess.TimeoutExpired:
            code = None
        time.sleep(0.8)
        wins = windows_of()
        fg = U32.GetForegroundWindow()
        res.append(("5 второй запуск вышел сам", code == 0, f"код {code}"))
        res.append(("5 окно одно", len(wins) == 1, f"окон DentPilot: {len(wins)}"))
        res.append(("5 первое окно на переднем плане", fg == hwnd1 and bool(hwnd1),
                    f"foreground={fg:#x}, первое={hwnd1:#x}"))
        res.append(("5 первое окно живо, сервер отвечает", run.proc.poll() is None
                    and bool(http_ok(f"http://127.0.0.1:{PORT}/health")), ""))

        run.page.go("/admin/logout")
        href = wait(lambda: pick(run.href(), lambda h: h.startswith("/admin/login")), 10.0) or run.href()
        res.append(("6 выход из учётки — экран входа", href.startswith("/admin/login"), href))
        res.append(("6 окно закрыто", run.close(), f"код {run.proc.poll()}"))
        run = Run(lab)
        href = run.attach()
        res.append(("6 старт после выхода — экран входа", href.startswith("/admin/login"), href))
        res.append(("6 закрыто", run.close(), ""))
    finally:
        if second is not None and second.poll() is None:
            second.kill()
        run.kill()
        lab.drop()


def scenario_shared(res: list) -> None:
    lab = Lab("shared_pc")
    run = Run(lab)
    try:
        href = run.attach()
        href = run.submit({"pin1": PIN, "pin2": PIN})
        if href.startswith("/admin/login"):
            href = run.submit({"password": PIN})
        res.append(("S вход на общем ПК — журнал", href.startswith("/admin") and "login" not in href, href))
        res.append(("S окно закрыто", run.close(), f"код {run.proc.poll()}"))
        run = Run(lab)
        href = run.attach()
        res.append(("S старт снова — экран входа (вход не пережил перезапуск)",
                    href.startswith("/admin/login"), href))
        res.append(("S профиль при этом постоянный", (lab.profile / "EBWebView").exists(), ""))
        res.append(("S закрыто", run.close(), ""))
    finally:
        run.kill()
        lab.drop()


def main(argv: list[str]) -> int:
    only = argv[0] if argv else ""
    if not PY.exists():
        print(f"нет {PY}")
        return 2
    res: list = []
    try:
        if only in ("", "standalone"):
            scenario_standalone(res)
        if only in ("", "shared_pc"):
            scenario_shared(res)
    except Exception as e:  # noqa: BLE001
        res.append((f"стенд оборван: {e.__class__.__name__}", False, str(e)[:200]))
    bad = [r for r in res if not r[1]]
    for name, ok, detail in res:
        print(f"{'OK ' if ok else '✗  '} {name}" + (f"  [{detail}]" if detail and not ok else ""))
    print(f"\n{len(res) - len(bad)}/{len(res)}: лаунчер — профиль, вход, один экземпляр, выход"
          + ("" if not bad else " — НЕТ"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
