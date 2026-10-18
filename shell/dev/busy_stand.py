# -*- coding: utf-8 -*-
"""Стенд: профиль окна занят другим WebView2 (18.10, к 2.0.1).

    .venv-desktop\\Scripts\\python.exe shell\\dev\\busy_stand.py --prog dist\\DentPilot [--hold 4]

Оболочка 2.0.0 падала (`c0000409`), когда WebView2 не создавался: ошибку
`setup` Tauri делает паникой, а у release `panic = "abort"`. На стенде Т9 так
вышло на повторном старте — WebView2 прошлого запуска ещё держал профиль
(ERROR_BUSY). Здесь без гонки: профиль держит сторож (`--watch`) той же
оболочки на ТОМ ЖЕ профиле с другими аргументами браузера — WebView2 программы
на нём не создастся, пока держатель жив (0x8007139F).

  --hold 4    держатель уходит через 4 с: оболочка повторяет и поднимается,
              выход словом — код 0
  --hold 30   дольше ожидания оболочки (20 с): окно Windows с текстом (стенд
              нажимает OK сам), выход с кодом 1, в журнале «cannot start»

⛔ Процессы — только по PID (задания стенда): `DentPilot.exe` — имя и
установленной программы Олега. Лаборатория — `shell_check.Lab` (TEMP).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import pathlib
import re
import sys
import time
from ctypes import wintypes

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import shell_check as sc  # noqa: E402
from harness import _end_job, _start_in_own_job  # noqa: E402

WAIT = 20.0          # WEBVIEW_WAIT оболочки (main.rs)
CANNOT = "DentPilot nu a putut deschide fereastra programului."


def dialogs(pid: int) -> list[tuple[int, str]]:
    """Окна-сообщения (#32770) процесса `pid`: (окно, текст)."""
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u32.GetDlgItemTextW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPWSTR, ctypes.c_int]
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    found = []

    def each(hwnd, _lp):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u32.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(hwnd, cls, 64)
            if cls.value == "#32770":
                text = ctypes.create_unicode_buffer(2048)
                u32.GetDlgItemTextW(hwnd, 0xFFFF, text, 2048)
                found.append((hwnd, text.value))
        return True

    u32.EnumWindows(proc(each), 0)
    return found


def press_ok(hwnd: int) -> None:
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE: у окна «OK» — то же, что OK


def run(prog: pathlib.Path, hold: float) -> dict:
    lab = sc.Lab(prog)
    rep: dict = {"hold": hold}
    holder = sh = None
    try:
        proof = lab.dir / "holder.run"
        env = lab.env()
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--disable-features=msSmartScreenProtection"
        # сторож ждёт итога, которого не будет (9 мин), — держит окно на профиле
        argv = [str(lab.shell), "--watch", str(proof), "DPBusyStandNoTask", str(lab.dir / "never.result"),
                "0", "stand", "#0E9F8A", str(lab.profile), str(lab.shell)]
        hproc, holder = _start_in_own_job(argv, cwd=str(lab.prog), env=env)
        t0 = time.time()
        while not proof.exists() and time.time() - t0 < 10:
            time.sleep(0.1)
        time.sleep(4.0)                           # окно сторожа и его браузер
        rep["holder_alive"] = hproc.poll() is None

        sh = sc.Shell(lab, "--tray")
        t1 = time.time()
        box = ""
        while time.time() - t1 < WAIT + 30:
            if holder is not None and time.time() - t1 >= hold:
                _end_job(holder)
                holder = None
                rep["released_at"] = round(time.time() - t1, 1)
            if sh.proc.poll() is not None or b'"dentpilot"' in sc.health(lab.port):
                break
            for hwnd, text in dialogs(sh.proc.pid):
                if not box:
                    rep["box_at"] = round(time.time() - t1, 1)
                box = text
                press_ok(hwnd)
            time.sleep(0.2)
        rep["ready"] = b'"dentpilot"' in sc.health(lab.port)
        code = sh.wait(10.0)
        rep["exit_at"] = round(time.time() - t1, 1)
        rep["code"] = code
        rep["box"] = box
        log = lab.shell_log.read_text("utf-8", "replace") if lab.shell_log.exists() else ""
        rep["retries"] = len(re.findall(r"WebView2 \w+: not created \(try \d+\)", log))
        rep["first_error"] = (re.findall(r"not created \(try 1\): (.*)", log) or [""])[0][:200]
        rep["created"] = re.findall(r"WebView2 \w+: created on try \d+, [\d.]+ s", log)
        rep["panic"] = re.findall(r"PANIC .*", log)
        rep["cannot_start"] = bool(re.search(r"cannot start: ", log))
        if rep["ready"]:
            origin = f"http://127.0.0.1:{lab.port}"
            target = sc.page_target(lab.cdp, origin + "/", 30.0)
            sent = sc.page_eval(target, origin, "window.dpShell ? (dpShell.send('win/quit'), 1) : 0") if target else None
            asked = sc.answer_dialog(sh.proc.pid, sc.QUIT_TEXT, 10.0) if sent == 1 else ""
            rep["quit_code"] = sh.wait(sc.QUIT_LIMIT) if asked else None
    finally:
        if sh is not None:
            sh.close()
        if holder is not None:
            _end_job(holder)
        lab.drop()
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prog", required=True, help="папка программы: DentPilot.exe + engine\\")
    ap.add_argument("--hold", type=float, default=4.0, help="сколько секунд держать профиль")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    prog = pathlib.Path(a.prog)
    rep = run((prog if prog.is_absolute() else ROOT / prog).resolve(), a.hold)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if a.hold < WAIT:
        want = {"держатель жив до старта": rep.get("holder_alive"),
                "оболочка повторяла": rep["retries"] > 0,
                "WebView создан повтором": bool(rep["created"]),
                "программа поднялась": rep["ready"],
                "выход словом — код 0": rep.get("quit_code") == 0}
    else:
        want = {"держатель жив до старта": rep.get("holder_alive"),
                "окно с текстом": CANNOT in rep["box"],
                "выход с кодом 1": rep["code"] == 1,
                "в журнале cannot start": rep["cannot_start"]}
    want["паники нет"] = not rep["panic"] and rep["code"] != 0xC0000409
    for k, v in want.items():
        print(f"   {'OK ' if v else 'RED'}  {k}")
    return 0 if all(want.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
