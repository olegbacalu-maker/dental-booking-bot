"""Обновления через GitHub Releases.
- Проверка при старте и каждые 6 часов (баннер в шапке + блок в настройках).
- self_update(): скачивает exe-ассет релиза, подменяет себя через bat-скрипт
  и перезапускается — «обновление в один клик» для desktop-издания.
Для теста механики без релиза: env DENTART_FAKE_UPDATE_URL=<url exe>."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

from . import engine as eng

REPO = "olegbacalu-maker/dental-booking-bot"

STATE = {"latest": "", "url": "", "asset_url": "", "checked": False, "error": ""}


def _ver(tag: str) -> tuple:
    parts = []
    for p in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def newer_available() -> bool:
    return bool(STATE["latest"]) and _ver(STATE["latest"]) > _ver(eng.APP_VERSION)


def is_desktop() -> bool:
    return bool(getattr(sys, "frozen", False))


def can_self_update() -> bool:
    return is_desktop() and newer_available() and bool(STATE["asset_url"])


def _check() -> None:
    fake = os.environ.get("DENTART_FAKE_UPDATE_URL", "").strip()
    if fake:
        STATE.update(latest="v9.9.9", asset_url=fake,
                     url=f"https://github.com/{REPO}/releases", checked=True, error="")
        return
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"User-Agent": "dentart-desktop"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        asset_url = ""
        for a in data.get("assets", []):
            if str(a.get("name", "")).lower().endswith(".exe"):
                asset_url = a.get("browser_download_url", "")
                break
        STATE.update(latest=data.get("tag_name", ""), url=data.get("html_url", ""),
                     asset_url=asset_url, checked=True, error="")
    except Exception as e:  # noqa: BLE001 — оффлайн/404 не должны ничего ломать
        STATE.update(checked=True, error=str(e))
    finally:
        t = threading.Timer(6 * 3600, _check)
        t.daemon = True
        t.start()


def check_async() -> None:
    threading.Thread(target=_check, daemon=True).start()


def self_update() -> str | None:
    """Скачивает новый exe и перезапускает программу. None = пошло, str = ошибка."""
    if not is_desktop():
        return "self-update доступен только в desktop-версии"
    if not STATE["asset_url"]:
        return "в релизе нет exe-файла"
    exe = pathlib.Path(sys.executable).resolve()
    new_path = exe.with_name("DentArt.new.exe")
    try:
        req = urllib.request.Request(STATE["asset_url"],
                                     headers={"User-Agent": "dentart-desktop"})
        with urllib.request.urlopen(req, timeout=120) as r, open(new_path, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:  # noqa: BLE001
        return f"descărcarea a eșuat: {e}"
    if new_path.stat().st_size < 5_000_000:
        new_path.unlink(missing_ok=True)
        return "fișier descărcat invalid (prea mic)"
    bat = exe.with_name("dentart_update.bat")
    # ping вместо timeout (timeout требует консоль), CREATE_NO_WINDOW даёт cmd
    # скрытую консоль — start/ping работают, окна не мелькают
    bat.write_text(
        "@echo off\r\n"
        f'cd /d "%~dp0"\r\n'
        ":try\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        f'move /y "{new_path.name}" "{exe.name}" >nul 2>&1 || goto try\r\n'
        f'start "" /D "%~dp0" "{exe.name}"\r\n'
        "schtasks /delete /tn DentArtUpdate /f >nul 2>&1\r\n"
        'del "%~f0"\r\n',
        encoding="ascii",
    )
    # Перезапуск через Планировщик Windows: bat стартует сервисом Task Scheduler,
    # ПОЛНОСТЬЮ вне нашего дерева процессов и Job-объектов — смерть старого
    # процесса не задевает новый (прямой Popen наследовал Job и новый умирал).
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    tn = "DentArtUpdate"
    subprocess.run(
        ["schtasks", "/create", "/tn", tn, "/tr", f'"{bat}"',
         "/sc", "once", "/st", "23:59", "/f"],
        creationflags=no_win, capture_output=True, check=False,
    )
    subprocess.run(["schtasks", "/run", "/tn", tn],
                   creationflags=no_win, capture_output=True, check=False)

    def _die() -> None:
        time.sleep(1.2)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()
    return None
