"""Провод к серверу обновлений DentPilot (03.10): какая версия свежая для канала.

Здесь только провод и проверка ответа — без состояния и без импортов проекта,
чтобы облачный прогон мог загрузить файл по пути и убедиться, что ЭТОТ клиент
понимает ЭТОТ сервер (cloud/tests/test_update.py). Тот же приём, что у
`core/license_renew.py`. Решение — что делать с ответом — `update.py`.

Запрос:  GET {сервер}/v1/update?channel=stable|beta&current=X.Y.Z  + заголовки личности
Ответ:   200 {ok, tag, version, prerelease, page, exe:{name,url,size,sha256}, setup:{…}}
         204 — новее нет
         всё остальное — «сервера нет»: программа идёт прежними путями к GitHub

⛔ Ответ сервера не принимается на веру. Ссылка на файл — только на выпуск НАШЕГО
репозитория с тем же тегом и точным именем файла, sha256 — 64 знака, размер —
разумный, версия — новее стоящей. Иначе ответ отбрасывается целиком, как будто
сервера нет: сервер может назвать один из настоящих выпусков, но не подсунуть
чужой файл и не откатить программу назад.
⛔ Редиректам клиент не следует: ответ обязан прийти от самого сервера.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request

PATH = "/v1/update"
TIMEOUT = 10.0
MAX_BODY = 64 * 1024
# Сколько может весить файл обновления — те же границы, что у привилегированной
# подмены (`privileged.MIN_EXE/MAX_EXE`): обрубок и мусор не проходят и здесь.
MIN_SIZE, MAX_SIZE = 5_000_000, 300_000_000
EXE_NAME = "DentPilot.exe"

NEWER = "newer"       # 200: выпуск новее, ответ прошёл проверку
SAME = "same"         # 204: новее нет
OFFLINE = "offline"   # сервер молчит, ответил не то или ответ не прошёл проверку

_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def ver(text: str) -> tuple[int, int, int] | None:
    """`v1.2.3` или `1.2.3` → (1, 2, 3); всё остальное — None."""
    m = _TAG.match("v" + str(text).lstrip("vV"))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _asset(a: object, prefix: str, name: str) -> dict | None:
    if not isinstance(a, dict):
        return None
    url = str(a.get("url") or "")
    sha = str(a.get("sha256") or "").lower()
    size = a.get("size")
    if (a.get("name") != name or url != prefix + urllib.parse.quote(name)
            or not _SHA.match(sha) or not isinstance(size, int) or isinstance(size, bool)
            or not MIN_SIZE <= size <= MAX_SIZE):
        return None
    return {"name": name, "url": url, "size": size, "sha256": sha}


def check(data: object, repo: str, current: str) -> dict | None:
    """Проверенный ответ сервера → {tag, version, prerelease, page, exe, setup};
    чужое, старое или без единого годного файла — None."""
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None
    tag = str(data.get("tag") or "")
    v = ver(tag)
    if v is None or not tag.startswith("v") or v <= (ver(current) or (0, 0, 0)):
        return None
    version = "%d.%d.%d" % v
    prefix = f"https://github.com/{repo}/releases/download/{tag}/"
    exe = _asset(data.get("exe"), prefix, EXE_NAME)
    setup = _asset(data.get("setup"), prefix, f"DentPilot-Setup-{version}.zip")
    if exe is None and setup is None:
        return None
    page = str(data.get("page") or "")
    if not page.startswith(f"https://github.com/{repo}/releases/"):
        page = f"https://github.com/{repo}/releases/tag/{tag}"
    return {"tag": tag, "version": version, "prerelease": bool(data.get("prerelease")),
            "page": page, "exe": exe, "setup": setup}


def ask(server: str, channel: str, current: str, repo: str, timeout: float = TIMEOUT,
        agent: str = "DentPilot", extra: dict | None = None) -> tuple[str, dict]:
    """Один вопрос серверу. Возвращает (исход, проверенный выпуск или {}) и не бросает."""
    url = f"{server.rstrip('/')}{PATH}?" + urllib.parse.urlencode(
        {"channel": channel, "current": current})
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": agent, **(extra or {})})
        with _opener.open(req, timeout=timeout) as r:
            if r.status == 204:
                return SAME, {}
            if r.status != 200:
                return OFFLINE, {}
            body = r.read(MAX_BODY + 1)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return OFFLINE, {}
    if len(body) > MAX_BODY:
        return OFFLINE, {}
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError:
        return OFFLINE, {}
    rel = check(data, repo, current)
    return (NEWER, rel) if rel else (OFFLINE, {})
