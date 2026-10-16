"""Провод SMS-пакета (S5): запросы программы к серверу лицензий одной стандартной библиотекой.

Контракт — docs/dentpilot-2/sms.md › «Сервер (cloud/)», ответы — cloud/app/sms.py
(`CODES`, `view`). Здесь только провод: собрать запрос, разобрать ответ ПО КОДУ.
Ни базы, ни текста напоминания, ни решения «слать ли» — это sms_loop.py. Модуль
не импортирует ничего из проекта (как license_renew.py), чтобы прогон сервера
мог позвать его по пути и убедиться, что ЭТОТ клиент понимает ЭТОТ сервер.

Адрес — origin `renew.url` принятого файла лицензии + `/v1/sms/…`, Bearer —
`renew.token` того же файла: у каждой активированной программы он уже есть, и
вводить нечего. Имени отправителя в запросах нет: его сервер берёт из записи
клиники по токену.

    GET  /v1/sms/account                    что видит Setări › SMS
    POST /v1/sms/send    {to, text, kind, idem}
    POST /v1/sms/status  {ids: […]}
    POST /v1/sms/sender  {name}
    POST /v1/sms/order   {pack: N} | {name: 1}

Исходы:
    OK       200 и `ok: true` — тело в ответе
    DENIED   отказ сервера словами: тело с `code` (sms.CODES) — 4xx/5xx
    REFUSED  401/403 без своего кода — токен не признан
    OFFLINE  сеть, таймаут, редирект, чужой ответ, 5xx без кода

⛔ Редиректам клиент не следует: заголовок с токеном не должен уехать на
чужой адрес (тот же приём, что у license_renew). ⛔ Тело читается с потолком.
⛔ Номер и текст в лог не пишутся нигде — ни здесь, ни у вызывающего.
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 10.0                  # секунд на запрос; цикл отправки старт не держит
MAX_BODY = 64 * 1024            # ответы сервера — сотни байт
PATH = "/v1/sms/"

OK = "ok"
DENIED = "denied"
REFUSED = "refused"
OFFLINE = "offline"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def base_of(renew_url: str) -> str:
    """`https://cloud.dentpilot.md/v1/sms/` из `renew.url` файла: тот же сервер,
    что выдал файл. Годность адреса проверяет вызывающий (rsa_verify)."""
    u = urllib.parse.urlsplit(renew_url or "")
    return f"{u.scheme}://{u.netloc}{PATH}" if u.scheme and u.netloc else ""


def _json(raw: bytes) -> dict:
    if len(raw) > MAX_BODY:
        return {}
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _call(base: str, op: str, token: str, payload: dict | None, timeout: float,
          agent: str, extra: dict | None) -> tuple[str, dict]:
    """Один запрос. Возвращает (исход, тело) и не бросает."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": agent, **(extra or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(base + op, data=data, headers=headers,
                                     method="GET" if payload is None else "POST")
        with _opener.open(req, timeout=timeout) as r:
            body = _json(r.read(MAX_BODY + 1))
            return (OK, body) if r.status == 200 and body.get("ok") is True else (OFFLINE, {})
    except urllib.error.HTTPError as e:
        try:
            body = _json(e.read(MAX_BODY + 1))
        except (OSError, http.client.HTTPException):
            body = {}
        code = body.get("code")
        if e.code in (401, 403) and code in ("token_missing", "token_unknown", None):
            return REFUSED, {}
        if isinstance(code, str) and (code.startswith("sms_") or code == "bad_json"):
            return DENIED, body
        return OFFLINE, {}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return OFFLINE, {}


def account(base: str, token: str, timeout: float = TIMEOUT, agent: str = "DentPilot",
            extra: dict | None = None) -> tuple[str, dict]:
    """Счёт клиники: offered, enabled, остаток, имя, пакеты, почему нельзя сейчас."""
    return _call(base, "account", token, None, timeout, agent, extra)


def send(base: str, token: str, to: str, text: str, kind: str, idem: str,
         timeout: float = TIMEOUT, agent: str = "DentPilot",
         extra: dict | None = None) -> tuple[str, dict]:
    """Одна SMS. Повтор с тем же `idem` сервер отвечает первым ответом — без
    второй SMS и второго списания, поэтому повторять можно без страха."""
    return _call(base, "send", token, {"to": to, "text": text, "kind": kind, "idem": idem},
                 timeout, agent, extra)


def status(base: str, token: str, ids: list[int], timeout: float = TIMEOUT,
           agent: str = "DentPilot", extra: dict | None = None) -> tuple[str, dict]:
    """Состояние своих сообщений: {items: [{id, state, error}]}."""
    return _call(base, "status", token, {"ids": list(ids)}, timeout, agent, extra)


def sender(base: str, token: str, name: str, timeout: float = TIMEOUT,
           agent: str = "DentPilot", extra: dict | None = None) -> tuple[str, dict]:
    """Заявка на имя отправителя; ответ — счёт, как у account()."""
    return _call(base, "sender", token, {"name": name}, timeout, agent, extra)


def order(base: str, token: str, pack: int = 0, name: bool = False,
          timeout: float = TIMEOUT, agent: str = "DentPilot",
          extra: dict | None = None) -> tuple[str, dict]:
    """Нота: пополнение на `pack` SMS или год своего имени (`name`)."""
    return _call(base, "order", token, {"name": 1} if name else {"pack": int(pack)},
                 timeout, agent, extra)
