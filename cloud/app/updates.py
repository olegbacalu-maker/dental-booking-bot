"""Сервер обновлений (03.10): программа спрашивает здесь, какая версия свежая для её канала.

Зачем свой адрес, если файлы лежат на GitHub. Анонимный API GitHub — 60 запросов
в час на адрес, а клиника сидит за NAT провайдера и делит квоту с чужими
программами (02.10 на машине Олега было 0 из 60). Сервер спрашивает GitHub сам,
не чаще раза в UPDATE_CACHE_S на канал, и отдаёт программам готовый ответ: версия,
ссылка на файл выпуска, размер, sha256. Сами файлы по-прежнему качаются с
GitHub по веб-адресу /releases/download/ — он лимитом API не связан.

⛔ Сервер не условие обновления: молчит — программа идёт прежними путями к
GitHub (`bot/app/update.py`). И не командует ею: канал называет программа, сервер
только отвечает, что для этого канала свежее (plan-fleet-admin: канал односторонний).
⛔ Ссылки — только на выпуски нашего репозитория (`config.RELEASES_DOWNLOAD`), и
программа проверяет это сама (`bot/app/update_server.py`): сервер не может
подсунуть чужой файл, только назвать один из настоящих выпусков, а более старый,
чем стоит, программа не возьмёт.

Источники — те же, что у канарейки в программе: `/releases/latest` (то, что видит
stable), атом-фид (все выпуски вместе с пре-) и точечный `/releases/tags/{tag}`
(флаг prerelease и файлы с sha256). Список `/releases` у этого репозитория
ненадёжен (то пусто, то 504), поэтому его здесь нет.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from . import config

log = logging.getLogger("cloud.updates")

API_PATH = "/v1/update"
CHANNELS = ("stable", "beta")
TIMEOUT = 8
MAX_BODY = 1024 * 1024
EXE_NAME = "DentPilot.exe"
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_SETUP = re.compile(r"^DentPilot-Setup-(\d+\.\d+\.\d+)\.zip$")
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
# Память без замка, как в download.py: два одновременных первых вопроса дадут
# два запроса к GitHub — не ошибка.
_cache: dict[str, tuple[float, "Release | None"]] = {}


@dataclass
class Asset:
    name: str
    url: str
    size: int
    sha256: str


@dataclass
class Release:
    tag: str
    version: str
    prerelease: bool
    page: str
    exe: Asset | None
    setup: Asset | None

    def as_dict(self) -> dict:
        return {"tag": self.tag, "version": self.version, "prerelease": self.prerelease,
                "page": self.page, "exe": asdict(self.exe) if self.exe else None,
                "setup": asdict(self.setup) if self.setup else None}


def ver(text: str) -> tuple[int, int, int] | None:
    """`v1.2.3` или `1.2.3` → (1, 2, 3); всё остальное — None."""
    m = _TAG.match("v" + str(text).lstrip("vV"))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "dentpilot-cloud",
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_BODY + 1)
            return body if len(body) <= MAX_BODY else None
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("github %s: %r", url, e)
        return None


def _asset(a: dict, tag: str) -> Asset | None:
    """Файл выпуска — только залитый, с sha256 от GitHub и ссылкой на наш репозиторий."""
    url = str(a.get("browser_download_url") or "")
    m = _DIGEST.match(str(a.get("digest") or "").lower())
    size = a.get("size")
    if (str(a.get("state") or "uploaded") != "uploaded" or not m or not isinstance(size, int)
            or size <= 0 or not url.startswith(f"{config.RELEASES_DOWNLOAD}{tag}/")):
        return None
    return Asset(str(a.get("name") or ""), url, size, m.group(1))


def parse(data: object) -> Release | None:
    """Ответ API GitHub о выпуске → Release; чужое и неполное — None."""
    if not isinstance(data, dict) or data.get("draft"):
        return None
    tag = str(data.get("tag_name") or "")
    v = ver(tag)
    if v is None or not tag.startswith("v"):
        return None
    version = "%d.%d.%d" % v
    exe = setup = None
    for a in data.get("assets") or []:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        if name == EXE_NAME:
            exe = _asset(a, tag) or exe
        elif (m := _SETUP.match(name)) and m.group(1) == version:
            setup = _asset(a, tag) or setup
    page = str(data.get("html_url") or "")
    if not page.startswith("https://github.com/"):
        page = config.RELEASES_PAGE
    return Release(tag, version, bool(data.get("prerelease")), page, exe, setup)


def _json(url: str) -> object:
    body = _get(url)
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return None


def _newest_atom_tag() -> str:
    body = _get(config.RELEASES_ATOM)
    if body is None:
        return ""
    tags = [urllib.parse.unquote(t) for t in
            re.findall(r"/releases/tag/([^\"'<>&?#]+)", body.decode("utf-8", "replace"))]
    tags = [t for t in tags if ver(t) and t.startswith("v")]
    return max(tags, key=ver, default="")


def _fetch(channel: str) -> Release | None:
    """Свежий выпуск канала у GitHub. stable — только /releases/latest (пре-релизов
    он не отдаёт по устройству GitHub); beta — свежее из latest и атом-фида."""
    cand = [parse(_json(config.RELEASES_API))]
    if channel == "beta":
        tag = _newest_atom_tag()
        if tag:
            cand.append(parse(_json(config.RELEASES_TAG_API.format(tag=urllib.parse.quote(tag)))))
    cand = [r for r in cand if r is not None]
    # при равной версии — запись С файлом программы: обновиться можно только ею
    return max(cand, key=lambda r: (ver(r.version), r.exe is not None), default=None)


def release(channel: str) -> Release | None:
    """Свежий выпуск канала — из памяти, если она моложе UPDATE_CACHE_S.

    ⭐ GitHub не ответил, а прежний ответ есть — отдаём прежний: выпуски не
    отзываются (правило «только вперёд»), и вчерашний ответ лучше молчания.
    None — не знаем вовсе (GitHub молчит с самого старта)."""
    at, prev = _cache.get(channel, (0.0, None))
    if time.time() - at < config.UPDATE_CACHE_S:
        return prev
    rel = _fetch(channel)
    if rel is None and prev is not None:
        log.warning("github молчит — канал %s отдаёт прежний ответ %s", channel, prev.tag)
        rel = prev
    _cache[channel] = (time.time(), rel)
    return rel


def answer(channel: str, current: str) -> tuple[int, dict | None]:
    """(код HTTP, тело) для /v1/update. 200 — есть выпуск новее `current`;
    204 — новее нет; 503 — сервер не знает (программа идёт к GitHub сама).
    Канал вне списка — stable: черновиков сервер не видит, а «draft» — это
    канал разработчика, ему отвечает то же, что канарейке."""
    ch = "beta" if channel in ("beta", "draft") else "stable"
    rel = release(ch)
    if rel is None:
        return 503, {"ok": False, "code": "unknown"}
    cur = ver(current) or (0, 0, 0)
    if ver(rel.version) <= cur:
        return 204, None
    return 200, {"ok": True, "channel": ch, **rel.as_dict()}
