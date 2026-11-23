"""Запись в Google Calendar API v3: свой календарь врача и его события (право calendar.app.created).

Модуль чистый, как core/gapi.py: ни базы, ни файлов, ни часов, из проекта — ничего. Ошибки — коды
CODES, слова экрана даёт вызывающий; функции не бросают (кроме ValueError на ошибку программиста:
адрес не https, момент без пояса, незнакомый уровень). Токен — access-токен из core/gauth.py, в лог
он не попадает нигде.

    calendar_insert / calendar_get / calendar_patch / calendar_delete   свой календарь врача
    event_insert / event_update / event_delete                          событие по своему id
    events_ours(access, cal_id, tag)        все наши события календаря — весь набор или отказ
    event_body(level, appt, …)              тело события: только поля белого списка

Право calendar.app.created не даёт списка календарей: свой календарь находится только по
сохранённому id. Удалённое событие лежит у Google «надгробием», и тот же id вставить заново нельзя
(409) — поэтому в id есть поколение, а 409 на новый id значит «наша вставка, ответ потерялся».
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone

API = "https://www.googleapis.com/calendar/v3"
TZ = "Europe/Chisinau"
TIMEOUT = 20.0
MAX_BODY = 4 * 1024 * 1024
PAGE_SIZE = 2500                    # потолок events.list у Google
MAX_PAGES = 200
MAX_RETRY_AFTER = 3600
TEXT_MAX = 200                      # заголовок события и имя календаря

OK = "ok"                           # 200/204
DUPLICATE = "duplicate"             # 409: id уже есть — своя вставка без ответа или «надгробие»
GONE = "gone"                       # 410: уже удалено — для удаления это успех
NOT_FOUND = "not_found"             # 404: события или календаря нет, или аккаунт его не видит
UNAUTHORIZED = "unauthorized"       # 401: access-токен истёк — gauth.refresh и один повтор
NO_SCOPE = "no_scope"               # 403: право не выдано или снято
FORBIDDEN = "forbidden"             # 403 прочее: API не включён в проекте, писать нельзя
RATE_LIMITED = "rate_limited"       # 429 или 403 по причине предела; `retry_after` — если Google сказал
OFFLINE = "offline"                 # сеть, таймаут, 5xx, редирект, чужой ответ — повторить позже
BAD_REQUEST = "bad_request"         # прочий 4xx — ошибка нашей стороны, `reason` — для лога
CODES = (OK, DUPLICATE, GONE, NOT_FOUND, UNAUTHORIZED, NO_SCOPE, FORBIDDEN, RATE_LIMITED, OFFLINE,
         BAD_REQUEST)

_RATE = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded",
         "RATE_LIMIT_EXCEEDED"}
_SCOPE = {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}

CALENDAR_KEYS = ("id", "summary", "description", "timeZone", "dataOwner")
OURS_FIELDS = "nextPageToken,items(id,status,extendedProperties/private)"
EVENT_FIELDS = "id,status"

# Уровни подробности события: «doar ora» (умолчание), «inițiale», «nume și serviciu».
LEVELS = ("time", "initials", "name")
DEFAULT_LEVEL = "time"

# Белый список тела события: других ключей у события нет, поле с данными пациента сверх Appt
# в Google не попадёт. Держит test_structure.
EVENT_KEYS = ("id", "summary", "description", "start", "end", "status", "reminders",
              "transparency", "visibility", "extendedProperties")
# Отпечаток — только видимое врачу: смена поколения или эпохи без правки записи не переписывает
# события, а запросов нет вовсе.
STAMP_KEYS = tuple(k for k in EVENT_KEYS if k not in ("id", "extendedProperties"))

B32HEX = "0123456789abcdefghijklmnopqrstuv"
TAG_LEN = 10
MARK_LEN = 8
_MARK_LINE = "Actualizat de DentPilot · "
_MARK = re.compile(r"Actualizat de DentPilot · ([0-9a-v]{%d})\s*\Z" % MARK_LEN)


@dataclass(frozen=True)
class Reply:
    code: str
    data: dict | None = None        # отобранное: календарь (CALENDAR_KEYS) или событие {id, status}
    items: tuple = ()               # events_ours: ({id, status, appt}, …) — весь набор, иначе не OK
    status: int = 0                 # HTTP-статус; 0 — ответа не было
    reason: str = ""                # причина Google, для лога
    retry_after: int = 0


@dataclass(frozen=True)
class Appt:
    """Запись журнала для календаря врача. Белый список: других полей у события нет."""
    id: int
    start: datetime                 # с поясом
    minutes: int
    room: str = ""                  # имя кабинета — на всех уровнях (не данные пациента)
    patient: str = ""               # полное имя — только "initials" (буквы) и "name"
    file_no: str = ""               # номер фиши — только "initials"
    service: str = ""               # только "name"


APPT_FIELDS = tuple(f.name for f in fields(Appt))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


# ---------- календарь врача ----------


def calendar_insert(access: str, summary: str, description: str, *, tz: str = TZ, base: str = API,
                    timeout: float = TIMEOUT, agent: str = "DentPilot") -> Reply:
    """Новый календарь в аккаунте врача; `data` — его поля (id, dataOwner — почта аккаунта)."""
    r, body = _call("POST", base, "/calendars", access, timeout, agent,
                    body={"summary": _line(summary), "description": description, "timeZone": tz})
    return _calendar(r, body)


def calendar_get(access: str, cal_id: str, *, base: str = API, timeout: float = TIMEOUT,
                 agent: str = "DentPilot") -> Reply:
    r, body = _call("GET", base, f"/calendars/{_seg(cal_id)}", access, timeout, agent)
    return _calendar(r, body)


def calendar_patch(access: str, cal_id: str, *, summary: str | None = None,
                   description: str | None = None, base: str = API, timeout: float = TIMEOUT,
                   agent: str = "DentPilot") -> Reply:
    """Имя и описание — только переданное; ничего не передано — ошибка программиста."""
    patch = {}
    if summary is not None:
        patch["summary"] = _line(summary)
    if description is not None:
        patch["description"] = description
    if not patch:
        raise ValueError("patch")
    r, body = _call("PATCH", base, f"/calendars/{_seg(cal_id)}", access, timeout, agent, body=patch)
    return _calendar(r, body)


def calendar_delete(access: str, cal_id: str, *, base: str = API, timeout: float = TIMEOUT,
                    agent: str = "DentPilot") -> Reply:
    """OK, GONE и NOT_FOUND одинаково значат «календаря больше нет». Сразу после удаления Google
    ещё может отдавать календарь на get — это не отказ."""
    r, _ = _call("DELETE", base, f"/calendars/{_seg(cal_id)}", access, timeout, agent, empty=True)
    return r


def _calendar(r: Reply, body: dict) -> Reply:
    if r.code != OK:
        return r
    if not isinstance(body.get("id"), str) or not body["id"]:
        return Reply(OFFLINE, status=r.status, reason="bad_body")
    return Reply(OK, data={k: str(body.get(k) or "") for k in CALENDAR_KEYS}, status=r.status)


# ---------- события ----------


def event_insert(access: str, cal_id: str, body: dict, *, base: str = API, timeout: float = TIMEOUT,
                 agent: str = "DentPilot") -> Reply:
    """Вставка своим id (он в теле). DUPLICATE — id уже есть: обновить тем же телом."""
    r, got = _call("POST", base, f"/calendars/{_seg(cal_id)}/events", access, timeout, agent,
                   body=body, query={"fields": EVENT_FIELDS})
    return _event(r, got)


def event_update(access: str, cal_id: str, event_id: str, body: dict, *, base: str = API,
                 timeout: float = TIMEOUT, agent: str = "DentPilot") -> Reply:
    """Полным телом (PUT): событие наше целиком, а patch стоит у Google три единицы квоты.
    `status: confirmed` в теле возвращает и «надгробие»."""
    r, got = _call("PUT", base, f"/calendars/{_seg(cal_id)}/events/{_seg(event_id)}", access, timeout,
                   agent, body=body, query={"fields": EVENT_FIELDS})
    return _event(r, got)


def event_delete(access: str, cal_id: str, event_id: str, *, base: str = API,
                 timeout: float = TIMEOUT, agent: str = "DentPilot") -> Reply:
    """OK, GONE и NOT_FOUND одинаково значат «события больше нет»."""
    r, _ = _call("DELETE", base, f"/calendars/{_seg(cal_id)}/events/{_seg(event_id)}", access, timeout,
                 agent, empty=True)
    return r


def _event(r: Reply, body: dict) -> Reply:
    if r.code != OK:
        return r
    if not isinstance(body.get("id"), str) or not body["id"]:
        return Reply(OFFLINE, status=r.status, reason="bad_body")
    return Reply(OK, data={"id": body["id"], "status": str(body.get("status") or "")}, status=r.status)


def events_ours(access: str, cal_id: str, tag: str, *, show_deleted: bool = False, base: str = API,
                timeout: float = TIMEOUT, agent: str = "DentPilot", page_size: int = PAGE_SIZE) -> Reply:
    """Все события календаря с меткой клиники `tag` — для пересборки. Набор только целиком: сбой
    любой страницы — отказ всего вызова, иначе пересборка сочла бы недошедшие события чужими."""
    _check_url(base)
    params = {"privateExtendedProperty": f"dp={tag}", "maxResults": page_size, "fields": OURS_FIELDS}
    if show_deleted:
        params["showDeleted"] = "true"
    path = f"/calendars/{_seg(cal_id)}/events"
    out: list = []
    token, seen, status = "", set(), 0
    for _ in range(MAX_PAGES):
        q = {**params, "pageToken": token} if token else params
        r, body = _call("GET", base, path, access, timeout, agent, query=q)
        if r.code != OK:
            return r
        status = r.status
        items = body.get("items", [])
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            return Reply(OFFLINE, status=status, reason="bad_body")
        for ev in items:
            eid = ev.get("id")
            if not isinstance(eid, str) or not eid:
                return Reply(OFFLINE, status=status, reason="bad_body")
            ext = ev.get("extendedProperties")
            private = ext.get("private") if isinstance(ext, dict) else None
            raw = private.get("dp_appt") if isinstance(private, dict) else None
            appt = int(raw) if isinstance(raw, str) and raw.isdigit() else None
            out.append({"id": eid, "status": str(ev.get("status") or ""), "appt": appt})
        token = body.get("nextPageToken")
        if not token:
            return Reply(OK, items=tuple(out), status=status)
        # та же страница по кругу держала бы проход до потолка страниц
        if not isinstance(token, str) or token in seen:
            return Reply(OFFLINE, status=status, reason="page_loop")
        seen.add(token)
    return Reply(OFFLINE, status=status, reason="too_many")


# ---------- тело события ----------


def initials(name: str) -> str:
    """«Ion Rusu» → «I.R.»: первая буква каждого слова, не больше четырёх."""
    out = []
    for word in re.split(r"[\s\-]+", name or ""):
        letter = next((c for c in word if c.isalpha()), "")
        if letter:
            out.append(letter.upper() + ".")
    return "".join(out[:4])


def _summary(level: str, a: Appt) -> str:
    if level == "time":
        parts = ["Programare"]
    elif level == "initials":
        parts = [initials(a.patient) or "Programare", f"Fișa {_line(a.file_no)}" if _line(a.file_no) else ""]
    elif level == "name":
        parts = [_line(a.patient) or "Programare", _line(a.service)]
    else:
        raise ValueError("level")
    parts.append(_line(a.room))
    return _line(" · ".join(p for p in parts if p))


def event_body(level: str, a: Appt, *, tag: str, event_id: str, note: str, tz: str = TZ) -> dict:
    """Тело события для insert и update. Поля записи — только по уровню; описание — `note`
    (что правят только в DentPilot); напоминаний нет: телефон врача не звенит в момент приёма."""
    if a.start.tzinfo is None or a.start.utcoffset() is None:
        raise ValueError("naive datetime")
    if isinstance(a.minutes, bool) or not isinstance(a.minutes, int) or a.minutes < 1:
        raise ValueError("minutes")
    start = a.start.astimezone(timezone.utc)
    end = start + timedelta(minutes=a.minutes)
    return {
        "id": event_id,
        "summary": _summary(level, a),
        "description": note,
        "start": {"dateTime": _rfc3339(start), "timeZone": tz},
        "end": {"dateTime": _rfc3339(end), "timeZone": tz},
        "status": "confirmed",
        "reminders": {"useDefault": False},
        "transparency": "opaque",
        "visibility": "private",
        "extendedProperties": {"private": {"dp": tag, "dp_appt": str(a.id)}},
    }


def body_stamp(body: dict) -> str:
    """Отпечаток тела: 16 знаков sha256 от видимого (STAMP_KEYS) в каноническом JSON."""
    seen = {k: body.get(k) for k in STAMP_KEYS}
    raw = json.dumps(seen, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def clinic_tag(clinic_id: str) -> str:
    """Метка клиники в событиях: 10 знаков base32hex от sha256(clinic_id) — сам id лицензии в
    Google не уходит."""
    if not isinstance(clinic_id, str) or not clinic_id:
        raise ValueError("clinic_id")
    digest = hashlib.sha256(clinic_id.encode("utf-8")).digest()
    return base64.b32hexencode(digest).decode("ascii").lower()[:TAG_LEN]


def event_id(tag: str, epoch: int, appt_id: int, gen: int) -> str:
    """id события: только a–v и 0–9 (base32hex, 5–1024 знаков у Google), из него однозначно
    читаются эпоха связи, запись и поколение. Новое поколение — новый id."""
    if len(tag) != TAG_LEN or any(c not in B32HEX for c in tag):
        raise ValueError("tag")
    for n in (epoch, appt_id, gen):
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("number")
    return f"dp{tag}e{epoch}a{appt_id}g{gen}"


def calendar_summary(clinic: str, doctor: str) -> str:
    """Имя календаря врача у Google: «DentPilot · <клиника> · <врач>»."""
    return _line(" · ".join(p for p in ("DentPilot", _line(clinic), _line(doctor)) if p))


def calendar_description(mark: str, text: str = "") -> str:
    """Описание календаря: текст и последней строкой метка связи — по ней установка узнаёт, что
    календарь пишет она, а не другой компьютер с копией папки."""
    if len(mark) != MARK_LEN or any(c not in B32HEX for c in mark):
        raise ValueError("mark")
    head = (text or "").strip()
    return (head + "\n\n" if head else "") + _MARK_LINE + mark


def mark_of(description: str) -> str:
    """Метка связи из описания календаря; '' — метки нет."""
    m = _MARK.search(description or "")
    return m.group(1) if m else ""


def _line(text: str) -> str:
    return " ".join(str(text or "").split())[:TEXT_MAX]


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- запрос ----------


def _seg(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("id")
    return urllib.parse.quote(value, safe="")


def _check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if not (u.scheme == "https" and u.hostname) and not (u.scheme == "http" and u.hostname == "127.0.0.1"):
        raise ValueError("url")


def _call(method: str, base: str, path: str, access: str, timeout: float, agent: str, *,
          body: dict | None = None, query: dict | None = None, empty: bool = False) -> tuple[Reply, dict]:
    """Один запрос. Не бросает (кроме ValueError на адрес не https); редиректу не следует —
    токен в заголовке не уезжает на чужой адрес."""
    _check_url(base)
    url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {"Authorization": f"Bearer {access}", "Accept": "application/json", "User-Agent": agent}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _opener.open(req, timeout=timeout) as r:
            status, raw = r.status, r.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        try:
            got = _json(e.read(64 * 1024))
        except (OSError, http.client.HTTPException):
            got = {}
        return _failure(e.code, got, e.headers.get("Retry-After") if e.headers else None), {}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return Reply(OFFLINE), {}
    if status not in (200, 204):
        return Reply(OFFLINE, status=status), {}
    if empty:
        return Reply(OK, status=status), {}
    if len(raw) > MAX_BODY:
        return Reply(OFFLINE, status=status, reason="too_big"), {}
    got = _json(raw)
    if not got:
        return Reply(OFFLINE, status=status, reason="bad_body"), {}
    return Reply(OK, status=status), got


def _json(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _failure(status: int, body: dict, retry: str | None) -> Reply:
    err = body.get("error")
    err = err if isinstance(err, dict) else {}
    reasons = set()
    for part in (err.get("errors"), err.get("details")):
        for e in part if isinstance(part, list) else ():
            if isinstance(e, dict):
                reasons.add(str(e.get("reason") or ""))
    reasons.discard("")
    reason = (sorted(reasons)[0] if reasons else str(err.get("status") or ""))[:64]
    wait = int(retry) if isinstance(retry, str) and retry.strip().isdigit() else 0
    # По причине, не по домену: «API не включён» Google пишет тем же доменом usageLimits.
    if status == 429 or (status == 403 and reasons & _RATE):
        code = RATE_LIMITED
    elif status >= 500 or status < 400:
        code = OFFLINE
    elif status == 401:
        code = UNAUTHORIZED
    elif status == 403 and reasons & _SCOPE:
        code = NO_SCOPE
    elif status == 403:
        code = FORBIDDEN
    elif status == 404:
        code = NOT_FOUND
    elif status == 409:
        code = DUPLICATE
    elif status == 410:
        code = GONE
    else:
        code = BAD_REQUEST
    return Reply(code, status=status, reason=reason, retry_after=min(wait, MAX_RETRY_AFTER))
