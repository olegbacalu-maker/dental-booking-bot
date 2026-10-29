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
Повтор несёт `verify_id`: код ушёл на e-mail клиники, и третий провод —
`/v1/verify` — меняет код на тот же токен.

Четвёртый (02.10) — «Plătește acum»: POST на `/v1/pay-link` с тем же Bearer,
что у суточного запроса файла. 200 с `ok` — адрес страницы оплаты `/plata/<id>`
и срок её жизни (проверяет адрес license.py); 401/403 — токен не признан;
остальное — «сервера нет». Тела запрос не несёт: клинику сервер знает по токену.

Пятый (27.10) — подтверждение e-mail клиники: POST JSON на `/v1/email/code`,
`/v1/email/confirm`, `/v1/email/change` с тем же Bearer. 200 с `ok` — ящик и
подтверждён ли он; 4xx/502 с `text` — отказ словами сервера (код, лимит, ящик
занят); 401/403 — токен не признан. Суточный ответ `/v1/license` (200 и 204)
несёт то же двумя заголовками — `fetch(meta=…)` их читает: в подписанный файл
состояние ящика не входит.

Шестой (29.10) — акт акцепта условий: POST JSON `{terms, actor}` на `/v1/terms/accept` с тем же
Bearer — повторное принятие новой версии условий из программы (и досылка квитанции, записанной
без сервера). 200 с `ok` — квитанция `{id, version, at}`; исходы — как у e-mail. Суточный ответ
`/v1/license` несёт заголовок `X-DentPilot-Terms` — старшую версию, которую клиника уже приняла
(с любого своего компьютера); `fetch(meta=…)` кладёт её в `meta["terms"]`.
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 10.0                  # секунд на весь запрос; старт программы его не ждёт
MAX_BODY = 64 * 1024            # потолок тела: файл — ~1.5 КБ

NEWER = "newer"                 # 200: в теле файл, который сервер считает новее seq
SAME = "same"                   # 204: новее нет
REFUSED = "refused"             # 401/403: токен не признан
OFFLINE = "offline"             # сети нет, таймаут, 5xx, редирект, чужой ответ
ACCEPTED = "accepted"           # заявка: 200 {"ok": true, "token", "url", "state"}
REJECTED = "rejected"           # заявка: 4xx/503 с `text` — отказ словами сервера
# Заголовки ответа /v1/license о ящике клиники (27.10): «1»/«0» и адрес в %-кодировке
H_EMAIL_CONFIRMED, H_EMAIL = "X-DentPilot-Email-Confirmed", "X-DentPilot-Email"
# Заголовок ответа /v1/license (29.10): последняя принятая клиникой версия условий — дата dd.mm.yyyy
H_TERMS = "X-DentPilot-Terms"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def request_url(url: str, seq: int) -> str:
    """`renew.url` с `?seq=N`: по нему сервер отвечает 204, когда новее нет."""
    return f"{url}{'&' if '?' in url else '?'}seq={int(seq)}"


def mailbox(headers) -> dict | None:
    """Состояние ящика клиники из заголовков ответа /v1/license: {email, confirmed} или None —
    сервер о нём не сказал (старый сервер, клиника без ящика, чужой ответ)."""
    flag, raw = headers.get(H_EMAIL_CONFIRMED), headers.get(H_EMAIL)
    if flag not in ("0", "1") or not raw:
        return None
    email = urllib.parse.unquote(raw)[:200]
    return {"email": email, "confirmed": flag == "1"} if "@" in email else None


def terms_version(headers) -> str:
    """Версия условий из заголовка ответа /v1/license: дата dd.mm.yyyy или '' — сервер не сказал
    (старый сервер, акта у клиники нет) или прислал не дату."""
    raw = (headers.get(H_TERMS) or "").strip()
    parts = raw.split(".")
    ok = (len(raw) == 10 and len(parts) == 3 and all(x.isdigit() for x in parts)
          and len(parts[0]) == 2 and len(parts[1]) == 2 and len(parts[2]) == 4)
    return raw if ok else ""


def fetch(url: str, token: str, seq: int, timeout: float = TIMEOUT,
          agent: str = "DentPilot", extra: dict | None = None,
          meta: dict | None = None) -> tuple[str, str]:
    """Один запрос. Возвращает (исход, текст файла или '') и не бросает.
    `extra` — заголовки личности машины (X-DentPilot-*, собирает license.py):
    по ним сервер ведёт флот — кто на какой версии (02.10). `meta` — словарь,
    куда положить состояние ящика клиники из заголовков ответа (`mailbox`, 27.10)."""
    try:
        req = urllib.request.Request(request_url(url, seq), headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json",
            "User-Agent": agent, **(extra or {})})
        with _opener.open(req, timeout=timeout) as r:
            if meta is not None and r.status in (200, 204) and (box := mailbox(r.headers)) is not None:
                meta["mailbox"] = box
            if meta is not None and r.status in (200, 204) and (tv := terms_version(r.headers)):
                meta["terms"] = tv
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
                  agent: str = "DentPilot", extra: dict | None = None) -> tuple[str, dict]:
    """Заявка на пробный: POST JSON на `url`. Возвращает (исход, ответ) и не бросает.

    ACCEPTED — ответ сервера с `token` и `url` (проверяет их вызывающий);
    REJECTED — отказ со словами сервера в `text` (у повтора — и `verify_id`);
    OFFLINE — всё остальное, включая 404 у сервера без этого входа."""
    return _post_json(url, fields, timeout, agent, extra)


def verify_code(url: str, verify_id: str, code: str, timeout: float = TIMEOUT,
                agent: str = "DentPilot", extra: dict | None = None, more: dict | None = None) -> tuple[str, dict]:
    """Код из письма: POST JSON на `url` (/v1/verify). Исходы — как у заявки. `more` — ещё поля тела:
    версия условий и кто принял (`terms`, `actor`, 29.10) — акт акцепта на сервере."""
    return _post_json(url, {"verify_id": verify_id, "code": code, **(more or {})}, timeout, agent, extra)


def pay_link(url: str, token: str, timeout: float = TIMEOUT, agent: str = "DentPilot",
             extra: dict | None = None) -> tuple[str, dict]:
    """Ссылка на оплату (02.10): POST на `url` (/v1/pay-link) с Bearer-токеном файла.
    Возвращает (исход, ответ) и не бросает: ACCEPTED — {url, expires_at}, адрес
    проверяет вызывающий; REFUSED — 401/403; OFFLINE — всё остальное."""
    try:
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": agent, **(extra or {})})
        with _opener.open(req, timeout=timeout) as r:
            data = _json(r.read(MAX_BODY + 1))
            return (ACCEPTED, data) if r.status == 200 and data.get("ok") is True else (OFFLINE, {})
    except urllib.error.HTTPError as e:
        return (REFUSED if e.code in (401, 403) else OFFLINE), {}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return OFFLINE, {}


def email_call(url: str, token: str, payload: dict, timeout: float = TIMEOUT, agent: str = "DentPilot",
               extra: dict | None = None) -> tuple[str, dict]:
    """Подтверждение ящика клиники (27.10): POST JSON на `url` (/v1/email/…) с Bearer-токеном файла.
    Возвращает (исход, ответ) и не бросает: ACCEPTED — {email, confirmed, sent}; REJECTED — отказ
    словами сервера в `text`; REFUSED — 401/403; OFFLINE — всё остальное."""
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": agent, **(extra or {})})
        with _opener.open(req, timeout=timeout) as r:
            data = _json(r.read(MAX_BODY + 1))
            return (ACCEPTED, data) if r.status == 200 and data.get("ok") is True else (OFFLINE, {})
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return REFUSED, {}
        if e.code in (400, 409, 429, 502, 503):
            data = _json(e.read(MAX_BODY + 1))
            if isinstance(data.get("text"), str) and data["text"]:
                return REJECTED, data
        return OFFLINE, {}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return OFFLINE, {}


def terms_accept(url: str, token: str, payload: dict, timeout: float = TIMEOUT, agent: str = "DentPilot",
                 extra: dict | None = None) -> tuple[str, dict]:
    """Акт акцепта условий (29.10): POST JSON `{terms, actor}` на `url` (/v1/terms/accept) с Bearer-токеном
    файла. Тот же провод, что у e-mail: ACCEPTED — квитанция {id, version, at}; REJECTED — отказ словами
    сервера (версия не дата, лимит); REFUSED — 401/403; OFFLINE — всё остальное."""
    return email_call(url, token, payload, timeout, agent, extra)


def _post_json(url: str, payload: dict, timeout: float, agent: str,
               extra: dict | None = None) -> tuple[str, dict]:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": agent, **(extra or {})})
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
