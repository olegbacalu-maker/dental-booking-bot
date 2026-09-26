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
"""
from __future__ import annotations

import http.client
import urllib.error
import urllib.request

TIMEOUT = 10.0                  # секунд на весь запрос; старт программы его не ждёт
MAX_BODY = 64 * 1024            # потолок тела: файл — ~1.5 КБ

NEWER = "newer"                 # 200: в теле файл, который сервер считает новее seq
SAME = "same"                   # 204: новее нет
REFUSED = "refused"             # 401/403: токен не признан
OFFLINE = "offline"             # сети нет, таймаут, 5xx, редирект, чужой ответ


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
