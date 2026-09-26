"""Автообновление файла лицензии (L13): запрос к `renew.url` одной стандартной библиотекой.

Контракт — docs/dentpilot-2/cloud.md › «Автообновление файла». Здесь только
провод: собрать запрос, разобрать ответ ПО КОДУ. Ни проверки подписи, ни
диска, ни состояния — это license.py: ответ сервера проходит тот же
`open_envelope`, что файл из письма, и то же правило `seq`. Модуль не
импортирует ничего из проекта, чтобы прогон сервера мог позвать его по пути
и убедиться, что ЭТОТ клиент понимает ЭТОТ сервер (cloud/tests/test_renew.py).

Запрос:  GET {renew.url}?seq={принятый seq}   Authorization: Bearer {renew.token}
Ответ:   200 — тело и есть файл (тот же текст, что скачивается и уходит письмом)
         204 — новее принятого у сервера нет
         401 — токен не признан (файл отозван, чужой сервер)
         всё остальное — «сервера нет»: сеть, таймаут, 5xx, редирект

⛔ Редиректам клиент не следует: заголовок с токеном не должен уехать на
чужой адрес. Сервер лицензий на этот адрес и не редиректит.
⛔ Тело читается с потолком: файл лицензии — полтора килобайта, и мегабайт
чужого ответа не должен ни занять память, ни дойти до разбора.

Заявка на пробный (26.09) — второй провод того же рода: POST JSON на
`/v1/trial` со страницы активации. 200 с `ok` — клиника заведена, в ответе
токен и адрес для запроса выше; 4xx с `text` — отказ словами сервера (поля,
повтор, лимит), программа показывает их как есть; остальное — «сервера нет».
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

TIMEOUT = 10.0                  # секунд на весь запрос; старт программы его не ждёт
MAX_BODY = 64 * 1024            # потолок тела: файл — ~1.5 КБ

NEWER = "newer"                 # 200: в теле файл, который сервер считает новее seq
SAME = "same"                   # 204: новее нет
REFUSED = "refused"             # 401/403: токен не признан
OFFLINE = "offline"             # сети нет, таймаут, 5xx, редирект, чужой ответ
ACCEPTED = "accepted"           # заявка: 200 {"ok": true, "token", "url", "state"}
REJECTED = "rejected"           # заявка: 4xx/503 с `text` — отказ словами сервера


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def request_url(url: str, seq: int) -> str:
    """`renew.url` с `?seq=N`: по нему сервер отвечает 204, когда новее нет."""
    return f"{url}{'&' if '?' in url else '?'}seq={int(seq)}"


def fetch(url: str, token: str, seq: int, timeout: float = TIMEOUT,
          agent: str = "DentPilot") -> tuple[str, str]:
    """Один запрос. Возвращает (исход, текст файла или '') и не бросает."""
    try:
        req = urllib.request.Request(request_url(url, seq), headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json",
            "User-Agent": agent})
        with _opener.open(req, timeout=timeout) as r:
            if r.status == 204:
                return SAME, ""
            if r.status != 200:
                return OFFLINE, ""
            body = r.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                return OFFLINE, ""
            return NEWER, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return (REFUSED if e.code in (401, 403) else OFFLINE), ""
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return OFFLINE, ""


def _json(raw: bytes) -> dict:
    """Тело ответа как словарь; чужое (не JSON, не объект, сверх потолка) — пусто."""
    if len(raw) > MAX_BODY:
        return {}
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def request_trial(url: str, fields: dict, timeout: float = TIMEOUT,
                  agent: str = "DentPilot") -> tuple[str, dict]:
    """Заявка на пробный: POST JSON на `url`. Возвращает (исход, ответ) и не бросает.

    ACCEPTED — ответ сервера с `token` и `url` (проверяет их вызывающий);
    REJECTED — отказ со словами сервера в `text`; OFFLINE — всё остальное,
    включая 404 у сервера без этого входа: заявку там принять некому."""
    try:
        req = urllib.request.Request(
            url, data=json.dumps(fields, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": agent})
        with _opener.open(req, timeout=timeout) as r:
            data = _json(r.read(MAX_BODY + 1))
            return (ACCEPTED, data) if r.status == 200 and data.get("ok") is True else (OFFLINE, {})
    except urllib.error.HTTPError as e:
        if e.code in (400, 409, 429, 503):
            data = _json(e.read(MAX_BODY + 1))
            if isinstance(data.get("text"), str) and data["text"]:
                return REJECTED, data
        return OFFLINE, {}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return OFFLINE, {}
