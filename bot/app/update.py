"""Проверка обновлений через GitHub Releases (бесплатный update-сервер).
v1 = уведомление + ссылка на релиз; автозамена exe — следующая итерация."""
from __future__ import annotations

import json
import threading
import urllib.request

from . import engine as eng

REPO = "olegbacalu-maker/dental-booking-bot"

STATE = {"latest": "", "url": "", "checked": False, "error": ""}


def _ver(tag: str) -> tuple:
    parts = []
    for p in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def newer_available() -> bool:
    return bool(STATE["latest"]) and _ver(STATE["latest"]) > _ver(eng.APP_VERSION)


def _check() -> None:
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"User-Agent": "dentart-desktop"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        STATE.update(latest=data.get("tag_name", ""),
                     url=data.get("html_url", ""), checked=True, error="")
    except Exception as e:  # noqa: BLE001 — оффлайн/404 не должны ничего ломать
        STATE.update(checked=True, error=str(e))


def check_async() -> None:
    threading.Thread(target=_check, daemon=True).start()
