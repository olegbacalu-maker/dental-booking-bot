"""Скачивание с сайта (L15): /descarca ведёт на подписанный установщик последнего выпуска.

cloud.md › «Пять запретов»: второго канала выдачи файлов нет. Файл отдаёт
GitHub Releases; сервер только спрашивает у API, какой выпуск последний, и
отвечает 302 на его ассет `DentPilot-Setup-X.Y.Z.zip` — мастер установки едет
в zip, потому что второй .exe в релизе запрещён (scripts/release.py: клиника
выбирает ассет по имени и скачала бы установщик вместо программы).

Ответ API живёт в памяти CACHE_TTL: сайт с сотней посетителей в час не
упрётся в лимит анонимного API (60 запросов в час). API молчит, а памяти
ещё нет — 302 на страницу выпусков GitHub: кнопка «Descarcă» не бывает
мёртвой. Адрес API меняют только тесты (стенд GitHub в процессе теста).
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config

log = logging.getLogger("cloud.download")

CACHE_TTL = 600
TIMEOUT = 5
_ASSET = re.compile(r"^DentPilot-Setup-(\d+\.\d+\.\d+)\.zip$")
# Память без замка: два одновременных первых клика дадут два запроса к API —
# это не ошибка, а замок потребовал бы threading сверх списка импортов сервера.
_cache: tuple[float, "Release | None"] = (0.0, None)


@dataclass
class Release:
    tag: str          # v1.35.3
    version: str      # 1.35.3
    asset: str        # DentPilot-Setup-1.35.3.zip
    url: str          # browser_download_url


def _fetch() -> Release | None:
    req = urllib.request.Request(config.RELEASES_API, headers={"User-Agent": "dentpilot-cloud",
                                                                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read(512 * 1024).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("releases api: %r", e)
        return None
    if not isinstance(data, dict):
        return None
    for a in data.get("assets") or []:
        if not isinstance(a, dict):
            continue
        m = _ASSET.match(str(a.get("name") or ""))
        url = str(a.get("browser_download_url") or "")
        if m and url.startswith("https://"):
            return Release(str(data.get("tag_name") or ""), m.group(1), m.group(0), url)
    log.warning("releases api: в последнем выпуске нет DentPilot-Setup-*.zip")
    return None


def latest() -> Release | None:
    """Последний выпуск с установщиком — из памяти, если она не старше CACHE_TTL.
    Ответ «нет» тоже помнится CACHE_TTL: лежащий API не опрашивается каждым кликом."""
    global _cache
    at, rel = _cache
    if time.time() - at < CACHE_TTL:
        return rel
    rel = _fetch()
    _cache = (time.time(), rel)
    return rel


def target() -> tuple[str, Release | None]:
    """Куда вести /descarca: ассет последнего выпуска или страница выпусков."""
    rel = latest()
    return (rel.url if rel else config.RELEASES_PAGE), rel
