"""Провод к sms.md (S3): единственный модуль, который знает их API v3.

Контракт — docs/dentpilot-2/sms.md › «sms.md — что известно» и спецификация
`docs.sms.md` (OpenAPI 3.1, сверена 16.10): `https://api.sms.md/v3`, заголовок
`X-Api-Token`, ответ в конверте `{status, httpCode, data}` (у списков ещё
`meta`), отказ — `{status: "error", httpCode, code, errors}`; ветвиться по
`code`, не по `message` (в проде он «An error occurred.»). Что делать с
ответом — sms.py: здесь только запросы и их разбор, как maib.py у карт.

Два вида неудачи, и путать их нельзя — от этого зависит, платит ли клиника:
- `Unanswered` — ответа нет (таймаут, обрыв, 5xx, не JSON): sms.md МОГ
  поставить SMS в очередь и списать деньги. Повтор вслепую — вторая SMS;
  сперва ищут (`find`).
- `Refused` — sms.md ответил отказом 4xx: в очередь не поставлено, денег не
  взято. `http` и `code` говорят, временный ли он (429, наш баланс, токен)
  или по существу (422: номер, имя, текст).

⛔ Номер и текст SMS не попадают ни в лог, ни в текст исключения: запрос к
sms.md несёт их в теле (отправка) и в адресе (поиск), поэтому ошибки
называют запрос меткой, а не адресом. ⛔ Mock-провайдера здесь нет и не
будет: тесты поднимают свой стенд и подставляют адрес через DP_SMSMD_BASE_URL.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("cloud.smsmd")

TIMEOUT = 10.0          # sms.md отвечает до доставки; программа ждёт сервер дольше (S5)
FIND_PAGES = 3          # страниц по 15 при поиске потерянного ответа
ALIAS_PAGES = 20        # страниц по 16 при сверке имён

# Статусы сообщения — GET /v3/messages/statuses (1, 2, 3, 8, 9, 10) и письмо
# sms.md 16.10 (11 Rejected). Не оплачиваются только 10 и 11.
QUEUED, SENT, DELIVERED, UNKNOWN, UNDELIVERED, FAILED, REJECTED = 1, 2, 3, 8, 9, 10, 11
FINAL = frozenset({DELIVERED, UNDELIVERED, FAILED, REJECTED})
# Статусы имени отправителя (GET /v3/sender-aliases): 1 Active, 2 On Confirmation,
# 3 Blocked, 4 Removed (в список не попадает), 5 On Moderation, 6 Disabled.
ALIAS_ACTIVE = 1
ALIAS_DEAD = frozenset({3, 4, 6})


class Unanswered(RuntimeError):
    """Ответа нет — принято ли сообщение, неизвестно. Текст — без номера и текста SMS."""


class Refused(RuntimeError):
    """sms.md отказал (4xx): не поставлено в очередь. `code` — их машинный код,
    `fields` — имена полей отказа валидации (без самих сообщений: в них бывает номер)."""

    def __init__(self, what: str, http: int, code: str, fields: tuple[str, ...] = ()):
        super().__init__(f"{what}: HTTP {http} {code}{(' ' + ','.join(fields)) if fields else ''}")
        self.http, self.code, self.fields = http, code, fields


def enabled() -> bool:
    return bool(config.SMSMD_TOKEN)


def _call(method: str, path: str, what: str, body: dict | None = None,
          query: dict | None = None) -> tuple:
    """Запрос → (data, meta). `what` — метка запроса для ошибок вместо адреса."""
    url = config.SMSMD_BASE_URL.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Accept": "application/json", "X-Api-Token": config.SMSMD_TOKEN}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            payload = {}
        if e.code >= 500:
            raise Unanswered(f"{what}: HTTP {e.code}") from None
        payload = payload if isinstance(payload, dict) else {}
        errs = payload.get("errors")
        fields = tuple(sorted(str(k) for k in errs)) if isinstance(errs, dict) else ()
        raise Refused(what, e.code, str(payload.get("code") or "HTTP_" + str(e.code)), fields) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Unanswered(f"{what}: {e.__class__.__name__}") from None
    if not isinstance(payload, dict) or payload.get("status") != "success" or "data" not in payload:
        raise Unanswered(f"{what}: ответ не в конверте success")
    return payload["data"], payload.get("meta") if isinstance(payload.get("meta"), dict) else {}


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def send(sender: str, to: str, text: str) -> dict:
    """POST /v3/messages → {id, segments, encoding}. `to` — восемь цифр (sms_rule.phone).
    `sendAt` не шлётся никогда: отменить его нельзя (sms.md › «Сервер»)."""
    data, _ = _call("POST", "/messages", "POST /messages", {"from": sender, "to": to, "text": text})
    pid = data.get("id") if isinstance(data, dict) else None
    if not isinstance(pid, str) or not pid:
        # принято или нет — по такому ответу не сказать: как молчание
        raise Unanswered("POST /messages: в ответе нет id")
    return {"id": pid, "segments": _int(data.get("segments")), "encoding": str(data.get("encoding") or "")}


def message(pid: str) -> dict:
    """GET /v3/messages/{id} → {status, segments} — истина о сообщении (уведомление — только сигнал)."""
    data, _ = _call("GET", "/messages/" + urllib.parse.quote(pid, safe=""), "GET /messages/{id}")
    status = data.get("status") if isinstance(data, dict) else None
    sid = _int(status.get("id") if isinstance(status, dict) else status, -1)
    if sid < 0:
        raise Unanswered("GET /messages/{id}: в ответе нет status.id")
    return {"status": sid, "segments": _int(data.get("smsCount"))}


def find(to: str, sender: str, after_local: str) -> list[tuple[str, str]]:
    """Сообщения на номер от имени после момента (местное время Кишинёва
    «Y-m-d H:i:s») → [(id, текст)], новые сверху. Совет sms.md: своего id у
    сообщения нет — «найти по номеру, отправителю и дате»."""
    out: list[tuple[str, str]] = []
    for page in range(1, FIND_PAGES + 1):
        data, meta = _call("GET", "/messages", "GET /messages?…",
                           query={"receiverNumber": to, "senderName": sender,
                                  "dateCreated[after]": after_local, "page": page})
        for m in data if isinstance(data, list) else ():
            if isinstance(m, dict) and isinstance(m.get("id"), str):
                out.append((m["id"], str(m.get("text") or "")))
        if page >= _int(meta.get("lastPage"), 1):
            break
    return out


def balance() -> str:
    """GET /v3/account/balance → баланс в леях строкой (так его отдаёт sms.md — без потери точности)."""
    data, _ = _call("GET", "/account/balance", "GET /account/balance")
    value = data.get("balance") if isinstance(data, dict) else None
    if value is None:
        raise Unanswered("GET /account/balance: в ответе нет balance")
    return str(value)


def aliases() -> dict[str, int]:
    """GET /v3/sender-aliases, все страницы → {имя: статус}."""
    out: dict[str, int] = {}
    for page in range(1, ALIAS_PAGES + 1):
        data, meta = _call("GET", "/sender-aliases", "GET /sender-aliases", query={"page": page})
        for a in data if isinstance(data, list) else ():
            if isinstance(a, dict) and isinstance(a.get("name"), str):
                st = a.get("status")
                out[a["name"]] = _int(st.get("id") if isinstance(st, dict) else st, -1)
        if page >= _int(meta.get("lastPage"), 1):
            break
    return out


def dlr(raw: bytes) -> tuple[str, int] | None:
    """Тело уведомления о доставке → (id, status_id) или None. Берутся только эти
    два поля: `phone` и `text` в теле есть (пока sms.md их не убрал), но дальше
    этой функции не идут и не логируются."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or not isinstance(body.get("id"), str) or not body["id"]:
        return None
    sid = _int(body.get("status_id"), -1)
    return (body["id"][:64], sid) if sid >= 0 else None
