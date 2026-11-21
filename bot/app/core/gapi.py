"""Чтение Google Calendar API v3 и переходник «событие Google → ics.Occurrence».

Из проекта модуль знает только core/ics.py: событие API становится тем же Occurrence, что даёт файл
.ics, и дальше идёт тем же путём (gimport.convert → gcal.absorb). Ни базы, ни часов, ни файлов;
ошибки — коды CODES, слова экрана даёт вызывающий. Токен — access-токен из core/gauth.py.

    calendars(access)                        calendarList.list, все страницы
    events(access, cal_id, time_min, time_max)  events.list с singleEvents=true, все страницы
    occurrences(items, tz)                   сырые события → Occurrence с ключом ics.occurrence_key

Набор окна — только целиком. absorb отличает «пропало» от «прошло» по полному набору ключей:
половина страниц, отданная как успех, пометила бы остальное пропавшим. Сбой на любой странице —
отказ всего вызова.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import ics

API = "https://www.googleapis.com/calendar/v3"
TIMEOUT = 20.0
PAGE_SIZE = 1000
MAX_PAGE = 16 * 1024 * 1024
MAX_EVENTS = ics.MAX_EVENTS
MAX_PAGES = 200
MAX_RETRY_AFTER = 3600

# Только то, что читает переходник: лишние поля события (гости с ответами, ссылки, вложения) на ПК
# клиники не нужны.
EVENT_FIELDS = ("nextPageToken,timeZone,items(id,iCalUID,status,summary,description,location,"
                "start,end,originalStartTime,recurringEventId,attendees(email,displayName))")
LIST_FIELDS = "nextPageToken,items(id,summary,summaryOverride,primary,accessRole,timeZone)"

OK = "ok"
UNAUTHORIZED = "unauthorized"       # 401: access-токен истёк или отозван — gauth.refresh и повтор
NO_SCOPE = "no_scope"               # 403: человек не выдал право (галочка на экране согласия)
FORBIDDEN = "forbidden"             # 403 прочее: API не включён в проекте, нет доступа к календарю
NOT_FOUND = "not_found"             # календаря нет или он больше не виден этому аккаунту
RATE_LIMITED = "rate_limited"       # 429 или 403 usageLimits; `retry_after` — секунды, если Google сказал
TOO_MANY = "too_many"               # событий в окне больше MAX_EVENTS — набор не отдаётся частью
OFFLINE = "offline"                 # сеть, таймаут, 5xx, редирект, чужой ответ — повторить позже
BAD_REQUEST = "bad_request"         # прочий 4xx — ошибка нашей стороны, `reason` — для лога
CODES = (OK, UNAUTHORIZED, NO_SCOPE, FORBIDDEN, NOT_FOUND, RATE_LIMITED, TOO_MANY, OFFLINE, BAD_REQUEST)

_RATE = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded",
         "RATE_LIMIT_EXCEEDED"}
_SCOPE = {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}


@dataclass(frozen=True)
class Calendar:
    id: str
    name: str
    primary: bool = False
    role: str = ""                  # owner | writer | reader
    tz: str = ""


@dataclass(frozen=True)
class Reply:
    code: str
    items: tuple = ()               # Calendar либо сырые события (dict) — весь набор, иначе не OK
    tz: str = ""                    # пояс календаря из ответа events.list
    status: int = 0                 # HTTP-статус; 0 — ответа не было
    reason: str = ""                # код ошибки Google, для лога
    retry_after: int = 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("naive datetime")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def calendars(access: str, *, timeout: float = TIMEOUT, base: str = API,
              agent: str = "DentPilot") -> Reply:
    """Календари аккаунта, из которых можно читать события (`minAccessRole=reader`: у
    календаря «только занятость» названий событий нет)."""
    r = _pages(base, "/users/me/calendarList",
               {"minAccessRole": "reader", "maxResults": 250, "fields": LIST_FIELDS},
               access, timeout, agent, cap=MAX_EVENTS)
    if r.code != OK:
        return r
    out = []
    for c in r.items:
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            return Reply(OFFLINE, status=r.status, reason="bad_body")
        name = c.get("summaryOverride") or c.get("summary") or cid
        out.append(Calendar(id=cid, name=" ".join(str(name).split()), primary=c.get("primary") is True,
                            role=str(c.get("accessRole") or ""), tz=str(c.get("timeZone") or "")))
    return Reply(OK, items=tuple(out), status=r.status)


def events(access: str, calendar_id: str, time_min: datetime, time_max: datetime, *,
           timeout: float = TIMEOUT, base: str = API, agent: str = "DentPilot",
           page_size: int = PAGE_SIZE, max_events: int = MAX_EVENTS) -> Reply:
    """Все события окна, серии развёрнуты самим Google. Google отбирает по концу события
    (`timeMin`) и по началу (`timeMax`): идущее сейчас событие тоже придёт."""
    path = f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events"
    return _pages(base, path, {"timeMin": rfc3339(time_min), "timeMax": rfc3339(time_max),
                               "singleEvents": "true", "maxResults": page_size, "fields": EVENT_FIELDS},
                  access, timeout, agent, cap=max_events)


def _check_url(url: str) -> None:
    u = urllib.parse.urlsplit(url)
    if not (u.scheme == "https" and u.hostname) and not (u.scheme == "http" and u.hostname == "127.0.0.1"):
        raise ValueError("url")


def _pages(base: str, path: str, params: dict, access: str, timeout: float, agent: str, *,
           cap: int) -> Reply:
    _check_url(base)
    out: list = []
    token, seen, tz, status = "", set(), "", 0
    for _ in range(MAX_PAGES):
        q = {**params, "pageToken": token} if token else params
        r, body = _get(f"{base}{path}?{urllib.parse.urlencode(q)}", access, timeout, agent)
        if r.code != OK:
            return r
        status = r.status
        items = body.get("items", [])
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            return Reply(OFFLINE, status=status, reason="bad_body")
        out.extend(items)
        if len(out) > cap:
            return Reply(TOO_MANY, status=status)
        if not tz and isinstance(body.get("timeZone"), str):
            tz = body["timeZone"]
        token = body.get("nextPageToken")
        if not token:
            return Reply(OK, items=tuple(out), tz=tz, status=status)
        # Google, отдающий ту же страницу по кругу, иначе держал бы опрос до потолка страниц.
        if not isinstance(token, str) or token in seen:
            return Reply(OFFLINE, status=status, reason="page_loop")
        seen.add(token)
    return Reply(TOO_MANY, status=status)


def _get(url: str, access: str, timeout: float, agent: str) -> tuple[Reply, dict]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access}",
                                               "Accept": "application/json", "User-Agent": agent})
    try:
        with _opener.open(req, timeout=timeout) as r:
            status, raw = r.status, r.read(MAX_PAGE + 1)
    except urllib.error.HTTPError as e:
        try:
            body = _json(e.read(64 * 1024))
        except (OSError, http.client.HTTPException):
            body = {}
        return _failure(e.code, body, e.headers.get("Retry-After") if e.headers else None), {}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return Reply(OFFLINE), {}
    if status != 200:
        return Reply(OFFLINE, status=status), {}
    if len(raw) > MAX_PAGE:
        return Reply(TOO_MANY, status=status, reason="page_size"), {}
    body = _json(raw)
    if not body:
        return Reply(OFFLINE, status=status, reason="bad_body"), {}
    return Reply(OK, status=status), body


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
    # По причине, не по домену: «API не включён в проекте» Google тоже пишет доменом usageLimits.
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
    elif status in (404, 410):
        code = NOT_FOUND
    else:
        code = BAD_REQUEST
    return Reply(code, status=status, reason=reason, retry_after=min(wait, MAX_RETRY_AFTER))


# ---- переходник: событие Google → ics.Occurrence ----

_MOMENT = re.compile(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::\d\d(?:\.\d{1,9})?)?(Z|[+-]\d\d:\d\d)")
_DAY = re.compile(r"(\d{4})-(\d\d)-(\d\d)")


def _moment(text: str) -> datetime:
    """Момент с поясом; секунды отбрасываются, как в ics: журнал считает минутами."""
    m = _MOMENT.fullmatch(text.strip()) if isinstance(text, str) else None
    if not m:
        raise ics.Unparsed(ics.BAD_DATE, str(text)[:40])
    y, mo, d, h, mi = (int(x) for x in m.groups()[:5])
    off = m.group(6)
    if off == "Z":
        tz = timezone.utc
    else:
        sign = -1 if off[0] == "-" else 1
        tz = timezone(sign * timedelta(hours=int(off[1:3]), minutes=int(off[4:6])))
    try:
        return datetime(y, mo, d, h, mi, tzinfo=tz)
    except ValueError:
        raise ics.Unparsed(ics.BAD_DATE, text[:40]) from None


def _when(part) -> date | datetime:
    if not isinstance(part, dict):
        raise ics.Unparsed(ics.NO_START)
    if part.get("dateTime"):
        return _moment(part["dateTime"])
    text = part.get("date")
    m = _DAY.fullmatch(text.strip()) if isinstance(text, str) else None
    if not m:
        raise ics.Unparsed(ics.NO_START if text is None else ics.BAD_DATE, str(text or "")[:40])
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise ics.Unparsed(ics.BAD_DATE, text[:40]) from None


def _series_day(orig: dict, ev: dict, cal_tz: str) -> date:
    """Дата вхождения серии для ключа — по стенным часам пояса СЕРИИ, как у ics
    (`RECURRENCE-ID` и развёртка считаются в поясе DTSTART серии): вхождение в 00:30 по Кишинёву
    в UTC ещё вчера, и ключ по UTC разошёлся бы с ключом файла."""
    when = _when(orig)
    if not isinstance(when, datetime):
        return when
    start = ev.get("start") if isinstance(ev.get("start"), dict) else {}
    name = orig.get("timeZone") or start.get("timeZone") or cal_tz
    if not name:
        return when.date()
    tz = ics.zone(str(name))
    if tz is None:
        raise ics.Unparsed(ics.UNKNOWN_TZ, str(name)[:64])
    return when.astimezone(tz).date()


def occurrence(ev: dict, tz: str = "") -> ics.Occurrence:
    """Одно событие `events.list` (singleEvents=true) → Occurrence. `tz` — пояс календаря
    (`Reply.tz`): им считается дата вхождения, если у самого события пояса нет.

    Ключ — `ics.occurrence_key`: у одиночного — `iCalUID`, у вхождения серии — `iCalUID|ГГГГММДД`
    по `originalStartTime` (у всех вхождений серии `iCalUID` общий, `id` — разный)."""
    def text(name: str) -> str:
        v = ev.get(name)
        return v if isinstance(v, str) else ""

    people = ev.get("attendees") if isinstance(ev.get("attendees"), list) else []
    orig = ev.get("originalStartTime")
    series = bool(text("recurringEventId")) or isinstance(orig, dict)
    base = dict(title=" ".join(text("summary").split()), description=ics.plain(text("description")),
                location=" ".join(text("location").split()),
                attendees=tuple((str(a.get("displayName") or ""), str(a.get("email") or ""))
                                for a in people if isinstance(a, dict)),
                status=text("status").upper(), series=series)
    uid = text("iCalUID").strip()
    if not uid:
        return ics.Occurrence(key="", problem=ics.NO_UID, **base)
    key, start = uid, None
    try:
        if isinstance(orig, dict):
            key = ics.occurrence_key(uid, _series_day(orig, ev, tz))
        start = _when(ev.get("start"))
        moved = isinstance(orig, dict) and _when(orig) != start
        if not isinstance(start, datetime):
            return ics.Occurrence(key=key, day=start, moved=moved, **base)
        minutes = 0
        if ev.get("end") is not None:
            end = _when(ev.get("end"))
            if not isinstance(end, datetime):
                raise ics.Unparsed(ics.BAD_DATE, "start/end")
            # Разность через UTC: в ночь перевода часов стенные часы ошиблись бы на час.
            minutes = int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() // 60)
        return ics.Occurrence(key=key, start=start, minutes=minutes, moved=moved, **base)
    except ics.Unparsed as ex:
        return ics.Occurrence(key=key, start=start if isinstance(start, datetime) else None,
                              problem=ex.code, detail=ex.detail, **base)


def occurrences(items, tz: str = "") -> list[ics.Occurrence]:
    """Весь набор окна; повтор ключа — `ics.DUP_KEY`, как у файла."""
    out = [occurrence(ev, tz) for ev in items]
    seen: set[str] = set()
    for i, occ in enumerate(out):
        if occ.key and occ.key in seen and not occ.problem:
            out[i] = ics.Occurrence(**{**occ.__dict__, "problem": ics.DUP_KEY, "detail": occ.key[:64]})
        seen.add(occ.key)
    return out
