"""Провод ответа пациента ссылкой (Premium): запросы программы к серверу лицензий.

Контракт — `review/premium-w2-ready-2026-11-26.md` § 2.3 (волна 2а: только подтверждение,
без `slots` и `result`); сервер — `cloud/app/plink.py`. Здесь только провод: собрать
запрос, разобрать ответ ПО КОДУ и проверить его форму. Ни базы, ни решения «выдавать ли»
— это `plink_loop.py`. Модуль не импортирует ничего из проекта (как `sms.py`): прогон
сервера грузит его по пути и сверяет двойник `CODE_RE` со своим.

    POST /v1/link/new    {kind:"confirm", until, langs:[…], label, phone} → {host, codes:[…]}
    GET  /v1/link/inbox?after=N                                         → {seq, items:[…]}
    POST /v1/link/close  {codes:[…]}                                    → {}

Через сервер едут только коды, ответы и время ответа, подпись и телефон КЛИНИКИ — ни
имени, ни телефона, ни времени визита пациента (`until` — срок кода, не час приёма:
сервер его не печатает).

Исходы — те же, что у `sms.py`: OK, DENIED (отказ словами, код `link_*` или `bad_json`),
REFUSED (токен не признан), OFFLINE (сеть, таймаут, редирект, чужой ответ). Ответ с
кривой формой — OFFLINE: программа живёт так, будто сервер молчал.

Редиректам клиент не следует (токен не уезжает на чужой адрес). Тело читается с
потолком. Код и адрес ссылки в лог не пишутся нигде: по коду открывается страница
ответа пациента.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 10.0
MAX_BODY = 64 * 1024
PATH = "/v1/link/"
NEW_MAX = 200                   # кодов за один запрос (и закрытий)
CONFIRM = "confirm"
STATES = ("yes", "no", "closed")  # что сервер сообщает о коде подтверждения в волне 2а

# Двойник правила облака (`cloud/app/plink.py::CODE_RE`): 32 знака без I O 0 1, длина 6.
# Держит прогон облака: он грузит этот файл по пути и сравнивает строки.
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{6}$")
HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")

OK = "ok"
DENIED = "denied"
REFUSED = "refused"
OFFLINE = "offline"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def base_of(renew_url: str) -> str:
    """`https://cloud.dentpilot.md/v1/link/` из `renew.url` файла лицензии — тот же сервер."""
    u = urllib.parse.urlsplit(renew_url or "")
    return f"{u.scheme}://{u.netloc}{PATH}" if u.scheme and u.netloc else ""


def url(host: str, code: str) -> str:
    """Адрес в SMS — без схемы (`v.dentpilot.md/K7Q2MX`); пусто, если хост или код кривые."""
    return f"{host}/{code}" if isinstance(host, str) and HOST_RE.match(host) and code_ok(code) else ""


PHONE_MAX = 32                  # правило сервера для телефона клиники на странице
LABEL_MAX = 60                  # правило сервера для подписи клиники
_PHONE_OK = re.compile(r"[0-9 +()\-]")


def page_phone(raw) -> str:
    """Телефон клиники для кнопки звонка на странице — по правилу сервера (цифры, пробел,
    `+ ( ) -`, до PHONE_MAX). В профиле бывает «022 123 456, 069 123 456» или «022/123»:
    берётся первый номер, прочие знаки выбрасываются; без цифр — пусто (кнопки нет).
    Кривой телефон сервер отверг бы `link_bad`, и все напоминания ушли бы без ссылки."""
    first = re.split(r"[,;/]", raw if isinstance(raw, str) else "", maxsplit=1)[0]
    out = " ".join("".join(c for c in first if _PHONE_OK.match(c)).split())[:PHONE_MAX].strip()
    return out if any(c.isdigit() for c in out) else ""


def page_label(raw) -> str:
    """Подпись клиники для страницы — 1–LABEL_MAX знаков, иначе сервер отказал бы `link_bad`."""
    out = " ".join((raw if isinstance(raw, str) else "").split())[:LABEL_MAX].strip()
    return out or "Clinica"


def code_ok(code) -> bool:
    return isinstance(code, str) and bool(CODE_RE.match(code))


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
        if isinstance(code, str) and (code.startswith("link_") or code == "bad_json"):
            return DENIED, body
        return OFFLINE, {}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return OFFLINE, {}


def new(base: str, token: str, until: str, langs: list[str], label: str, phone: str,
        timeout: float = TIMEOUT, agent: str = "DentPilot",
        extra: dict | None = None) -> tuple[str, dict]:
    """Коды подтверждения, по одному на язык из `langs`, в том же порядке: {host, codes}.
    Ответ, где кодов не столько, сколько просили, или код/хост кривые, — OFFLINE."""
    outcome, body = _call(base, "new", token, {"kind": CONFIRM, "until": until, "langs": list(langs),
                                                "label": label, "phone": phone},
                          timeout, agent, extra)
    if outcome != OK:
        return outcome, body
    codes, host = body.get("codes"), body.get("host")
    if (not isinstance(codes, list) or len(codes) != len(langs) or not all(code_ok(c) for c in codes)
            or len(set(codes)) != len(codes) or not isinstance(host, str) or not HOST_RE.match(host)):
        return OFFLINE, {}
    return OK, {"host": host, "codes": list(codes)}


def inbox(base: str, token: str, after: int, timeout: float = TIMEOUT, agent: str = "DentPilot",
          extra: dict | None = None) -> tuple[str, dict]:
    """Перемены после номера `after`: {seq, items:[{code, seq, state, at}]}. Строки с кривым
    кодом, незнакомым состоянием или без времени отбрасываются; `seq` ответа — не меньше
    последней принятой строки."""
    outcome, body = _call(base, f"inbox?after={max(0, int(after))}", token, None, timeout, agent, extra)
    if outcome != OK:
        return outcome, body
    seq = body.get("seq")
    raw = body.get("items")
    if not isinstance(seq, int) or isinstance(seq, bool) or not isinstance(raw, list):
        return OFFLINE, {}
    items = []
    for it in raw[:1000]:
        if not isinstance(it, dict):
            continue
        s = it.get("seq")
        if (not code_ok(it.get("code")) or it.get("state") not in STATES or not isinstance(s, int)
                or isinstance(s, bool) or not isinstance(it.get("at"), str) or len(it["at"]) > 40):
            continue
        items.append({"code": it["code"], "seq": s, "state": it["state"], "at": it["at"]})
    items.sort(key=lambda x: x["seq"])
    top = max([seq] + [x["seq"] for x in items])
    return OK, {"seq": top, "items": items, "more": body.get("more") is True}


def close(base: str, token: str, codes: list[str], timeout: float = TIMEOUT,
          agent: str = "DentPilot", extra: dict | None = None) -> tuple[str, dict]:
    """Закрыть коды (перенос, отмена, «Fără SMS», архив, стирание): страница пациента
    говорит «Programarea a fost modificată» и больше не принимает ответ."""
    return _call(base, "close", token, {"codes": [c for c in codes if code_ok(c)][:NEW_MAX]},
                 timeout, agent, extra)
