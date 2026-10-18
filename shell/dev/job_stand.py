# -*- coding: utf-8 -*-
"""Живой стенд «мастер обновления переживает задание оболочки» (18.10, 2.0.2) —
на СОБРАННОЙ оболочке, без окна UAC.

    <app>\\.venv-desktop\\Scripts\\python.exe shell\\dev\\job_stand.py --shell <DentPilot.exe>
        [--root D:\\DentProject\\sandbox\\update-job\\stand] [--bot <папка bot>]

То же, что `test_privileged.suite_setup_outlives_shell`, но задание настоящее:
его создаёт сама оболочка (`Engine::start`) вокруг подставного движка
(`shell\\dev\\fake_engine.py`). Процесс «за UAC» создаётся от имени движка
атрибутом родителя — как его создаёт служба UAC — и исполняет `install-setup`
из `--bot` (по умолчанию — этой копии; `bot` прежней версии с оболочкой
прежней версии повторяет живой проход 2.0.0 → 2.0.1). В миг «started»
оболочка снимается по PID: ручка задания закрывается, как при выходе, и
Windows гасит всё, что в нём. Подставной мастер обязан выжить и написать «ok».

⛔ Процессы — только по PID своих запусков (`DentPilot.exe` — имя и
установленной программы Олега); порт не 8088; данные, профиль WebView2 и
лаборатория — в `--root`. На экране на несколько секунд — окно оболочки.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

APP = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / "tests"))

import jobstand  # noqa: E402

PY = getattr(sys, "_base_executable", sys.executable)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shell", required=True, type=pathlib.Path)
    ap.add_argument("--root", type=pathlib.Path, default=pathlib.Path(r"D:\DentProject\sandbox\update-job\stand"))
    ap.add_argument("--bot", type=pathlib.Path, default=APP / "bot")
    ap.add_argument("--port", type=int, default=8196)
    a = ap.parse_args()
    if a.port == 8088:
        raise SystemExit("8088 — живая установка; другой порт")
    root = a.root.resolve()
    # `--bot` бывает чужой копией (прежняя версия в общем app\) — без __pycache__ в ней
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if root.exists():
        shutil.rmtree(root)
    inst = root / "inst"
    inst.mkdir(parents=True)
    prog = inst / "DentPilot.exe"
    shutil.copy2(a.shell, prog)               # без engine\ рядом — движок разработки
    (root / "stand-data").mkdir()
    env = {**os.environ, "DENTPILOT_DEV_APP": str(APP),
           "DENTPILOT_DEV_ENGINE": str(APP / "shell" / "dev" / "fake_engine.py"),
           "DP_FAKE": "demo", "DENTART_PORT": str(a.port),
           "DENTART_DATA_DIR": str(root / "stand-data"), "DENTART_PROFILE_DIR": str(root / "stand-webview"),
           "DENTART_UPDATE_CHECK": "off"}
    lab = root / "lab"
    work, child = jobstand.make_lab(lab, PY)
    result, log = work / "install.result", work / "setup.log"
    out: dict = {"shell": str(a.shell), "bot": str(a.bot)}
    kill: list[int] = []
    shell = subprocess.Popen([str(prog)], cwd=str(inst), env=env)
    kill.append(shell.pid)
    try:
        # движок оболочки: ребёнок оболочки (пускач venv), в её задании
        t0 = time.monotonic()
        engine = 0
        while not engine and time.monotonic() - t0 < 30:
            engine = next((pid for pid, name in jobstand.children_of(shell.pid)
                           if name.lower() == "python.exe"), 0)
            time.sleep(0.1)
        if not engine:
            out["error"] = "движок оболочки не появился за 30 с"
            return report(out, False)
        kill += [engine, *(pid for pid, _n in jobstand.children_of(engine))]
        out["engine_in_a_job"] = jobstand.in_any_job(engine)
        time.sleep(1.0)                        # движок поднялся (как перед кнопкой «Actualizează»)
        parent = jobstand.open_pid(engine)
        uac = jobstand.start([PY, str(child), str(a.bot), str(lab)], parent=parent)
        kill.append(uac.pid)
        said = jobstand.wait_text(result, lambda t: t.strip() != "", 30).strip()
        out["said"] = said
        t_said = time.monotonic()
        jobstand.kill_pid(shell.pid)           # оболочка вышла: ручка задания закрыта
        try:
            shell.wait(10)
            out["shell_gone"] = True
        except subprocess.TimeoutExpired:
            out["shell_gone"] = False
        out["engine_gone"] = jobstand.wait_pid(engine, 5)
        # процесс «за UAC»: вышел сам или погашен заданием. ⚠️ Код выхода не
        # различает (у погашенного закрытием задания — тоже 0): различает ВРЕМЯ —
        # 2.0.0/2.0.1 после «started» спят 3 с, и исчезнуть раньше им нечем, кроме задания
        uac.wait(5)
        out["uac_exit"] = uac.exit_code()
        out["uac_gone_after_started_s"] = round(time.monotonic() - t_said, 2)
        final = jobstand.wait_text(result, lambda t: t.strip() == "ok", 15).strip()
        out["final"] = final
        out["setup_log"] = log.exists()
        if log.exists():
            head = log.read_text(encoding="utf-8", errors="replace")
            if "pid=" in head:
                kill.append(int(head.split("pid=", 1)[1].split()[0]))
        ok = said == "started" and final == "ok" and out["engine_gone"]
        return report(out, ok)
    finally:
        for pid in kill:
            if not jobstand.wait_pid(pid, 0.1):
                jobstand.kill_pid(pid)


def report(out: dict, ok: bool) -> int:
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("ЗЕЛЁНОЕ: мастер пережил выход оболочки и написал «ok»" if ok
          else "КРАСНОЕ: мастер не пережил выход оболочки")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
