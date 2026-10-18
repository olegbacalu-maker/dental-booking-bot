# -*- coding: utf-8 -*-
"""Стенд сторожа обновления оболочки (Т10, 18.10.2026) — без установки и без UAC.

    <app>\\.venv-desktop\\Scripts\\python.exe shell\\dev\\watch_stand.py --shell <собранный DentPilot.exe>
        [--root D:\\DentProject\\sandbox\\tauri-update\\stand] [--only update|cancelled|restart]

Что делает (папка `--root` — песочница на D:, ⛔ не `Program Files` и не 8088):
- `update`: копия оболочки → `<root>\\data\\updates\\DentPilot-watch.exe`, НАСТОЯЩАЯ
  задача планировщика (`update._schtasks_run`, аргументы — `restartwatch.argv_for`,
  как у движка), подставной «мастер» пишет в файл итога «started», потом «ok»
  БЕЗ перевода строки; «старая программа» — спящий процесс, его pid в плане.
  Ждём: метка «пошёл», окно сторожа на экране (снимок — `<root>\\shots`), до «ok»
  и до выхода старого процесса программа НЕ запускается, после — запускается
  (подставная: пишет метку), сторож выходит, задача снята.
- `cancelled`: итог «cancelled» — сторож закрывается, программу не запускает.
- `restart`: без итога, pid 0 — ждать сторожу некого, КРОМЕ процесса того же
  файла `DentPilot.exe` в своём сеансе: старая оболочка — стенд с подставным
  движком (`DP_FAKE=quit`, сама просит закрыться через 6 с), сторож запущен
  прямо (с окружением стенда, чтобы новая оболочка тоже была стендом, а не
  программой учётки) и поднимает её только после выхода старой.
- `engine` (с `--engine <dist\\DentPilot-Engine>`): настоящий собранный движок под
  настоящей оболочкой, перезапуск маршрутом программы — `quit`, честная
  остановка движка, сторож задачей планировщика, новая оболочка и движок.
⛔ Процессы снимаются только по PID.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

APP = pathlib.Path(__file__).resolve().parents[2]
BOT = APP / "bot"
PY = pathlib.Path(sys.executable)
NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def windows_of(pid: int) -> list[tuple[str, bool]]:
    """Окна верхнего уровня процесса: (заголовок, видно ли)."""
    u = ctypes.windll.user32
    out: list = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(hwnd, buf, 256)
            if buf.value:
                out.append((buf.value, bool(u.IsWindowVisible(hwnd))))
        return True

    u.EnumWindows(proto(cb), 0)
    return out


def pids_of(image: pathlib.Path) -> list[int]:
    """PID процессов с этим файлом (по полному пути, без учёта регистра)."""
    want = str(image.resolve()).lower()
    k32 = ctypes.windll.kernel32
    r = subprocess.run(["tasklist", "/fo", "csv", "/nh", "/fi", f"imagename eq {image.name}"],
                       capture_output=True, text=True, creationflags=NO_WIN)
    found = []
    for line in r.stdout.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) < 2 or not parts[1].isdigit():
            continue
        pid = int(parts[1])
        h = k32.OpenProcess(0x1000, False, pid)            # QUERY_LIMITED_INFORMATION
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and buf.value.lower() == want:
            found.append(pid)
        k32.CloseHandle(h)
    return found


def alive(pid: int) -> bool:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == 258
    finally:
        k32.CloseHandle(h)


def kill(pid: int) -> None:
    subprocess.run(["taskkill", "/pid", str(pid), "/t", "/f"], capture_output=True, creationflags=NO_WIN)


def shot(root: pathlib.Path, name: str) -> str:
    try:
        from PIL import ImageGrab
        d = root / "shots"
        d.mkdir(exist_ok=True)
        p = d / f"{name}.png"
        ImageGrab.grab(all_screens=True).save(p)
        return str(p)
    except Exception as e:  # noqa: BLE001 — снимок украшает отчёт
        return f"(снимка нет: {e!r})"


def wait_until(cond, timeout: float, step: float = 0.1) -> float | None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return time.monotonic() - t0
        time.sleep(step)
    return None


class Report:
    def __init__(self) -> None:
        self.bad = 0

    def ok(self, name: str, cond: bool, why: str = "") -> None:
        print(f"  {'OK ' if cond else 'BAD'} {name}" + ("" if cond else f" — {why}"))
        self.bad += 0 if cond else 1


def _marker_cmd(root: pathlib.Path, out: pathlib.Path) -> list[str]:
    """Подставная «программа»: копия cmd.exe под своим именем пишет метку со
    своей рабочей папкой. ⚠️ Не python.exe: сторож ждёт выхода ЛЮБОГО процесса
    того же файла в сеансе (`watch.rs::same_exe_alive`), а python.exe у
    разработчика живёт десятками — сторож честно ждал бы потолок 60 с."""
    prog = root / "prog" / "launch-stand.exe"
    prog.parent.mkdir(parents=True, exist_ok=True)
    if not prog.exists():
        shutil.copy2(pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe", prog)
    return [str(prog), "/c", f'cd > "{out}"']


def scenario_task(root: pathlib.Path, shell: pathlib.Path, verdict: str, rep: Report) -> None:
    """update / cancelled: настоящий планировщик, копия оболочки, подставной мастер."""
    os.environ["DENTART_DATA_DIR"] = str(root / "data")
    sys.path.insert(0, str(BOT))
    from app import restartwatch as rw
    from app import update as upd

    work = upd.work_dir()
    for p in work.glob("*"):
        if p.is_file():
            p.unlink()
    watch = work / "DentPilot-watch.exe"
    shutil.copy2(shell, watch)
    result = work / "install.result"
    marker = root / f"launched-{verdict}.txt"
    marker.unlink(missing_ok=True)
    old = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-c",
                            "import time; time.sleep(600)"], creationflags=NO_WIN)
    task = f"DentPilotStand{verdict.capitalize()}"
    plan = rw.Plan(proof=work / f"{task}.run", task=task, result=result, pid=old.pid,
                   label="1.46.1 › 9.9.9", primary="#2563EB", profile=root / "webview-watch",
                   launch=_marker_cmd(root, marker))
    print(f"\n== {verdict}: сторож {watch} задачей {task}, старая программа pid {old.pid}")
    t0 = time.monotonic()
    err = upd._schtasks_run(task, str(watch), rw.argv_for(plan), plan.proof, 30.0)
    rep.ok(f"{verdict}: задача планировщика запустила сторожа (метка «пошёл»)", err is None, str(err))
    if err is not None:
        kill(old.pid)
        return
    print(f"     метка через {time.monotonic() - t0:.2f} с")
    wpids: list = []

    def found() -> bool:
        wpids[:] = pids_of(watch)
        return bool(wpids)

    wait_until(found, 5)
    rep.ok(f"{verdict}: процесс сторожа — копия в папке данных", bool(wpids), "не найден по пути")
    wpid = wpids[0] if wpids else 0
    seen = wait_until(lambda: any(t == "DentPilot" and v for t, v in windows_of(wpid)), 15)
    rep.ok(f"{verdict}: окно сторожа «DentPilot» на экране", seen is not None, repr(windows_of(wpid)))
    if seen is not None:
        print(f"     окно через {seen:.2f} с после метки")
    time.sleep(2.5)                     # заставка дорисовалась
    print(f"     снимок: {shot(root, verdict + '-1-installing')}")
    result.write_text("started", encoding="utf-8")
    time.sleep(1.5)
    rep.ok(f"{verdict}: на «started» сторож ждёт", alive(wpid) and not marker.exists(), "")
    result.write_bytes(verdict.encode("ascii"))    # «ok» / «cancelled» без перевода строки
    if verdict == "cancelled":
        gone = wait_until(lambda: not alive(wpid), 10)
        rep.ok("cancelled: сторож закрылся сам", gone is not None, "жив")
        time.sleep(1)
        rep.ok("cancelled: программу НЕ запускал", not marker.exists(), "метка запуска есть")
        kill(old.pid)
    else:
        time.sleep(2.0)
        rep.ok("ok: старая программа жива — запуска ещё нет", not marker.exists() and alive(wpid),
               "сторож не дождался выхода старой")
        print(f"     снимок: {shot(root, 'ok-2-closing')}")
        t_kill = time.time()
        kill(old.pid)
        got = wait_until(marker.exists, 10, 0.02)
        rep.ok("ok: старая вышла — программа запущена", got is not None, "метки запуска нет")
        if got is not None:
            time.sleep(0.3)
            cwd = marker.read_text(encoding="mbcs", errors="replace").strip()
            print(f"     запуск через {marker.stat().st_mtime - t_kill:.2f} с после выхода старой")
            rep.ok("ok: запуск — в папке программы", pathlib.Path(cwd).resolve()
                   == pathlib.Path(plan.launch[0]).resolve().parent, cwd)
        gone = wait_until(lambda: not alive(wpid), 10)
        rep.ok("ok: сторож вышел", gone is not None, "жив")
    q = subprocess.run(["schtasks", "/query", "/tn", task], capture_output=True, creationflags=NO_WIN)
    rep.ok(f"{verdict}: задача снята", q.returncode != 0, "задача осталась")
    if q.returncode == 0:
        subprocess.run(["schtasks", "/delete", "/tn", task, "/f"], capture_output=True, creationflags=NO_WIN)
    log = work / "watch.log"
    print("     watch.log:\n       " + "\n       ".join(
        log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else ["(нет)"]))
    if alive(wpid):
        kill(wpid)


def scenario_restart(root: pathlib.Path, shell: pathlib.Path, rep: Report) -> None:
    """restart: ждать по ФАЙЛУ (pid 0) — старая оболочка-стенд сама просит закрыться."""
    sys.path.insert(0, str(BOT))
    from app import restartwatch as rw

    inst = root / "inst"
    inst.mkdir(parents=True, exist_ok=True)
    prog = inst / "DentPilot.exe"
    shutil.copy2(shell, prog)
    env = {**os.environ, "DENTPILOT_DEV_APP": str(APP),
           "DENTPILOT_DEV_ENGINE": str(APP / "shell" / "dev" / "fake_engine.py"),
           "DP_FAKE": "quit", "DP_FAKE_AFTER": "6", "DENTART_PORT": "8193",
           "DENTART_DATA_DIR": str(root / "stand-data"), "DENTART_PROFILE_DIR": str(root / "stand-webview"),
           "DENTART_UPDATE_CHECK": "off"}
    (root / "stand-data").mkdir(exist_ok=True)
    print(f"\n== restart: старая оболочка-стенд {prog} (подставной движок, quit через 6 с)")
    old = subprocess.Popen([str(prog)], cwd=str(inst), env=env)
    up = wait_until(lambda: any(v for _t, v in windows_of(old.pid)), 20)
    rep.ok("restart: старая оболочка на экране", up is not None, "окна нет")
    work = root / "restart-work"
    work.mkdir(exist_ok=True)
    plan = rw.Plan(proof=work / "DentPilotRestart.run", task="DentPilotStandNone", result=None, pid=0,
                   label="1.46.1", primary="#0E9F8A", profile=root / "webview-watch",
                   launch=[str(prog)])
    watcher = subprocess.Popen([str(prog), *rw.argv_for(plan)], cwd=str(inst), env=env)
    t0 = time.time()
    rep.ok("restart: сторож — сама оболочка, при живой старой не закрылся (замка нет)",
           wait_until(plan.proof.exists, 10) is not None and alive(watcher.pid), "метки нет или вышел")
    old_gone = wait_until(lambda: not alive(old.pid), 30)
    rep.ok("restart: старая оболочка закрылась по quit", old_gone is not None, "жива")
    t_old = time.time()
    new: list = []

    def fresh() -> bool:
        new[:] = [p for p in pids_of(prog) if p not in (old.pid, watcher.pid)]
        return bool(new)

    wait_until(fresh, 20)
    rep.ok("restart: сторож поднял новую оболочку", bool(new), "новой нет")
    if new:
        print(f"     новая оболочка pid {new[0]} через {time.time() - t_old:.2f} с после выхода старой "
              f"(всего {time.time() - t0:.1f} с)")
        # ⚠️ Поднятая слишком рано, она отдала бы запуск старой и закрылась:
        # доказательство — её СОБСТВЕННОЕ окно на экране
        win = wait_until(lambda: any(v for _t, v in windows_of(new[0])), 15)
        rep.ok("restart: у новой оболочки своё окно (не отдала запуск старой)", win is not None,
               repr(windows_of(new[0])))
        print(f"     снимок: {shot(root, 'restart-new-shell')}")
    rep.ok("restart: сторож вышел", wait_until(lambda: not alive(watcher.pid), 10) is not None, "жив")
    # новая — тоже стенд с подставным движком «quit»: закроется сама; не закрылась — по PID
    for p in new:
        if wait_until(lambda: not alive(p), 20) is None:
            kill(p)
    log = work / "watch.log"
    print("     watch.log:\n       " + "\n       ".join(
        log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else ["(нет)"]))


def _get(url: str, opener=None, timeout: float = 2.0):
    import urllib.request
    try:
        with (opener or urllib.request.build_opener()).open(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, repr(e)


def scenario_engine(root: pathlib.Path, shell: pathlib.Path, engine: pathlib.Path,
                    rep: Report, port: int = 8197) -> None:
    """engine: НАСТОЯЩИЙ движок (сборка папкой) под настоящей оболочкой, переносимая
    папка в песочнице. Перезапуск маршрутом программы (`/api/settings/lan` off —
    `restart_app`): движок заводит сторожа задачей планировщика, просит оболочку
    закрыться (`quit`), оболочка останавливает движок, сторож поднимает новую.
    ⚠️ Оболочка, поднятая планировщиком, — НЕ стенд (окружения у задачи нет):
    её `shell.json`/`shell.log` ложатся в %LOCALAPPDATA%\\DentPilot — стенд их
    убирает, если их там не было."""
    import secrets
    import urllib.request
    from http.cookiejar import CookieJar

    inst = root / "inst-engine"
    if inst.exists():
        shutil.rmtree(inst)
    (inst / "engine").parent.mkdir(parents=True, exist_ok=True)
    prog = inst / "DentPilot.exe"
    shutil.copy2(shell, prog)
    shutil.copytree(engine, inst / "engine")
    (inst / "portable.flag").write_text("", encoding="ascii")
    key = secrets.token_hex(16)
    (inst / "dental.env").write_text(f"DENTART_PORT={port}\nDENTART_UPDATE_CHECK=off\n"
                                     f"ADMIN_KEY={key}\n", encoding="utf-8")
    local = pathlib.Path(os.environ["LOCALAPPDATA"]) / "DentPilot"
    had = {n: (local / n).exists() for n in ("shell.json", "shell.log", "shell.log.1")}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DENTART_", "DENTPILOT_", "DP_"))}
    base = f"http://127.0.0.1:{port}"
    print(f"\n== engine: {prog} + engine\\ (порт {port}, данные — в папке программы)")
    first = subprocess.Popen([str(prog)], cwd=str(inst), env=env)
    t0 = time.monotonic()
    up = wait_until(lambda: _get(base + "/health")[0] == 200, 60, 0.3)
    rep.ok("engine: оболочка подняла собранный движок", up is not None, "/health молчит")
    if up is None:
        kill(first.pid)
        return
    print(f"     /health через {up:.1f} с")
    engines = pids_of(inst / "engine" / "DentPilot-Engine.exe")
    jar = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.open(urllib.request.Request(base + "/admin/login", method="POST",
                                   data=f"password={key}&next=/admin".encode()), timeout=10)
    req = urllib.request.Request(base + "/api/settings/lan", method="POST",
                                 data=b'{"mode":"off"}',
                                 headers={"Content-Type": "application/json", "Origin": base})
    t_req = time.monotonic()
    try:
        body = op.open(req, timeout=20).read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — оболочка могла уйти раньше ответа
        body = repr(e)
    print(f"     ответ маршрута: {body[:160]}")
    gone = wait_until(lambda: not alive(first.pid), 20)
    rep.ok("engine: оболочка закрылась по просьбе движка (quit)", gone is not None, "жива")
    if gone is not None:
        print(f"     оболочка вышла через {gone:.2f} с после запроса; код {first.wait(1)}")
    rep.ok("engine: прежний движок остановлен", all(not alive(p) for p in engines), repr(engines))
    log = (inst / "data" / "dentpilot.log").read_text(encoding="utf-8", errors="replace")
    rep.ok("engine: движок остановился словом оболочки, а не os._exit",
           "остановка по слову оболочки" in log, "в dentpilot.log нет строки остановки")
    new: list = []

    def fresh() -> bool:
        new[:] = [p for p in pids_of(prog) if p != first.pid and windows_of(p)]
        return bool(new)

    got = wait_until(fresh, 40, 0.3)
    rep.ok("engine: сторож поднял новую оболочку с окном", got is not None, "новой нет")
    back = wait_until(lambda: _get(base + "/health")[0] == 200, 60, 0.3)
    rep.ok("engine: новая оболочка подняла движок — программа снова отвечает", back is not None, "")
    if back is not None:
        print(f"     программа снова на ногах через {time.monotonic() - t_req:.1f} с после запроса")
        time.sleep(2)
        print(f"     снимок: {shot(root, 'engine-after-restart')}")
    work = inst / "updates"
    wlog = work / "watch.log"
    print("     watch.log:\n       " + "\n       ".join(
        wlog.read_text(encoding="utf-8", errors="replace").splitlines() if wlog.exists() else ["(нет)"]))
    q = subprocess.run(["schtasks", "/query", "/tn", "DentPilotRestart"], capture_output=True,
                       creationflags=NO_WIN)
    rep.ok("engine: задача перезапуска снята", q.returncode != 0, "осталась")
    # уборка: новую оболочку — её же выходом из меню нечем, гасим по PID (движок — заданием)
    for p in new:
        kill(p)
    wait_until(lambda: _get(base + "/health")[0] == 0, 15)
    time.sleep(1)
    for n, was in had.items():
        if not was:
            (local / n).unlink(missing_ok=True)
    print(f"     всего {time.monotonic() - t0:.1f} с; %LOCALAPPDATA%\\DentPilot убран до прежнего")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shell", required=True)
    ap.add_argument("--engine", default="", help="папка собранного движка (dist\\DentPilot-Engine)")
    ap.add_argument("--root", default=r"D:\DentProject\sandbox\tauri-update\stand")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    root = pathlib.Path(a.root)
    if not str(root).lower().startswith("d:\\dentproject\\sandbox"):
        print("⛔ стенд — только в D:\\DentProject\\sandbox")
        return 2
    root.mkdir(parents=True, exist_ok=True)
    shell = pathlib.Path(a.shell).resolve()
    rep = Report()
    for v in ("update", "cancelled", "restart", "engine"):
        if a.only and a.only != v:
            continue
        if v == "engine":
            if a.engine:
                scenario_engine(root, shell, pathlib.Path(a.engine).resolve(), rep)
            elif a.only:
                print("engine: нужен --engine <dist\\DentPilot-Engine>")
                rep.bad += 1
        elif v == "restart":
            scenario_restart(root, shell, rep)
        else:
            scenario_task(root, shell, "ok" if v == "update" else "cancelled", rep)
    print(f"\n{'всё сошлось' if not rep.bad else f'НЕ СОШЛОСЬ: {rep.bad}'}")
    return 1 if rep.bad else 0


if __name__ == "__main__":
    sys.exit(main())
