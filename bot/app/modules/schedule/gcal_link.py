"""Вкладка «Google Calendar»: связь с аккаунтом Google клиники — вход, файл связи, опрос.

Провод — core/gauth.py и core/gapi.py (чистые), клиент сборки — core/gclient.py, право — дата в файле
лицензии (`license.feature_until("gcal")`). Здесь — их связка с файлом, часами и вкладкой (`gcal.absorb`).

- Файл связи `google.json` лежит рядом с clinic.json, а не в картотеке: refresh-токен под DPAPI этой
  учётки Windows, привязан к device.json. Копии картотеки и архив его не берут. «Не расшифровался
  здесь» считается на лету и никуда не пишется: под второй учёткой Windows запись погасила бы рабочую
  связь первой.
- Опрос — раз в POLL_MINUTES, полным окном (сутки назад … +gcal.HORIZON_DAYS): `absorb` отличает
  «пропало» от «прошло» только по полному набору ключей.
- Право спрашивается на каждом подключении и каждом проходе, без кэша: None — пауза, файл не трогается.
- Токены, код входа, verifier и секрет клиента в лог и в базу не попадают нигде.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import pathlib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from ... import db, dpapi, paths
from ... import engine as eng
from ...core import demo, gapi, gauth, gclient
from ...core import license as lic
from ...core import license_state as lst
from ...core.auth import PERM_SCHEDULE_ALL, all_users, can, client_is_local, remote_notice, request_user
from ...core.layout import msg_text, msg_view
from . import gcal

log = logging.getLogger("gcal")

POLL_MINUTES = 10
TICK_ENV = "DENTART_GCAL_TICK_S"          # стенд: секунды вместо POLL_MINUTES
# Стенд Google прогона вместо настоящего: только вне exe, как DENTART_GOOGLE_CLIENT (gclient) —
# строка в dental.env собранной программы адрес Google не подменит.
STAND_ENV = "DENTART_GOOGLE_STAND"
FILE_NAME = "google.json"
BACK_PATH = "/google/back"
LOGIN_TTL = 600.0                         # секунд живёт начатый вход
LOGINS_MAX = 8
# Событие, которое в Google перенесли на вчера, иначе сочлось бы пропавшим, а не прошедшим.
LOOK_BACK = timedelta(days=1)
ACCESS_MARGIN = 60                        # access-токен считается истёкшим на минуту раньше
CALENDARS_MAX = 100
ACTOR = "sistem"
PRIVACY = {"href": "https://dentpilot.md/privacy.html#google", "label": "dentpilot.md/privacy.html#google"}
PLUS = {"href": "/admin/license", "label": "Licența"}

WORDS = {"connect": "Conectează contul Google", "disconnect": "Deconectează",
         "check": "Verifică acum", "calendar": "Alege calendarul"}
NOTICE = (
    "Programul citește evenimentele unui calendar Google ales de dvs. — de acum până la un an "
    f"înainte, din {POLL_MINUTES} în {POLL_MINUTES} minute — și le arată în această filă. Acces numai "
    "pentru citire: programul nu scrie nimic în Google și nu trimite acolo date ale pacienților. "
    "Evenimentele rămân doar pe acest calculator; furnizorul DentPilot nu le primește. Puteți "
    "deconecta oricând. Detalii: dentpilot.md/privacy.html#google")

S_OFF, S_CHOOSE, S_ON, S_PAUSED = "off", "choose", "on", "paused"
S_RECONNECT, S_PLUS, S_READONLY = "reconnect", "plus", "readonly"
DEAD_GRANT, DEAD_SCOPE = "invalid_grant", "no_scope"
_DEAD_CODE = {DEAD_GRANT: "gc_g_dead", DEAD_SCOPE: "gc_g_no_scope"}

# исход провода → код вкладки
_WIRE = {gauth.INVALID_GRANT: "gc_g_dead", gauth.INVALID_CLIENT: "gc_g_client",
         gauth.ADMIN_POLICY: "gc_g_admin", gauth.RATE_LIMITED: "gc_g_rate",
         gauth.OFFLINE: "gc_g_offline", gauth.BAD_REQUEST: "gc_g_failed",
         gapi.NO_SCOPE: "gc_g_no_scope", gapi.FORBIDDEN: "gc_g_failed",
         gapi.NOT_FOUND: "gc_g_not_found", gapi.TOO_MANY: "gc_g_too_many",
         gapi.UNAUTHORIZED: "gc_g_failed"}
# у обмена кода своё слово только там, где новый вход не поможет
_BACK_WIRE = {gauth.INVALID_CLIENT: "gc_g_client", gauth.ADMIN_POLICY: "gc_g_admin"}

_lock: asyncio.Lock | None = None
_wake: asyncio.Event | None = None
_task: asyncio.Task | None = None
_logins: dict = {}                        # state входа → verifier, адрес возврата, кто начал
_access: dict = {"token": "", "until": 0.0}
_last: dict = {"error": "", "quiet_until": 0.0}


@dataclass(frozen=True)
class _Ends:
    auth: str = gauth.AUTH_URL
    token: str = gauth.TOKEN_URL
    revoke: str = gauth.REVOKE_URL
    api: str = gapi.API


def _ends() -> _Ends:
    base = "" if paths.is_frozen() else os.environ.get(STAND_ENV, "").strip().rstrip("/")
    if not base:
        return _Ends()
    return _Ends(base + "/auth", base + "/token", base + "/revoke", base + "/calendar/v3")


def _agent() -> str:
    # Без личности машины и ключа лицензии: Google их знать незачем (Anexa 2).
    return f"DentPilot/{eng.APP_VERSION}"


def _actor() -> str:
    return (request_user() or {}).get("name") or ACTOR


def _client() -> gauth.Client | None:
    """Клиент Google — или None: блока связи нет (демо, сервер, сборка без клиента, нет DPAPI)."""
    if demo.on() or not dpapi.available() or not lic.applies():
        return None
    return gclient.client()


def _gate_code() -> str:
    s = lic.current()
    return "gc_g_plus" if s is not None and s.state in (lst.ACTIVE, lst.GRACE) else "gc_g_readonly"


# ---------- файл связи ----------


def _path() -> pathlib.Path | None:
    d = lic.folder()
    return d / FILE_NAME if d is not None else None


def _read() -> dict | None:
    p = _path()
    if p is None:
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("token"), str) else None


def _write(data: dict) -> bool:
    p = _path()
    if p is None:
        return False
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        log.warning("gcal: %s not written: %r", FILE_NAME, e)
        return False
    return True


def _remove() -> None:
    p = _path()
    if p is not None:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("gcal: %s not removed: %r", FILE_NAME, e)


def _token(link: dict) -> str | None:
    """refresh-токен связи; None — файл не с этого компьютера или не этой учётки Windows.
    Только шифротекст: открытый токен в файле — чужая запись, не наша."""
    stored = str(link.get("token") or "")
    if not stored.startswith(dpapi.PREFIX) or link.get("device") != lic.device_id():
        return None
    return dpapi.unprotect(stored) or None


def _calendar(link: dict) -> dict | None:
    cal = link.get("calendar")
    return cal if isinstance(cal, dict) and isinstance(cal.get("id"), str) and cal["id"] else None


def _calendars(link: dict) -> list:
    raw = link.get("calendars")
    return [c for c in raw if isinstance(c, dict) and isinstance(c.get("id"), str)] \
        if isinstance(raw, list) else []


def _lockd() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _forget_access() -> None:
    _access.update(token="", until=0.0)


# ---------- модель блока ----------


def _when(iso: str) -> dict | None:
    try:
        at = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return {"at": iso, "when": at.astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M")}


def _waiting() -> bool:
    now = time.monotonic()
    return any(not e["done"] and now - e["at"] < LOGIN_TTL for e in _logins.values())


def view(request) -> dict | None:
    """Блок связи в модели вкладки (`data.google`); None — блока нет. Экран рисует кнопки по `can`,
    слова — по `why`, `words` и `notice`: своих слов о связи у него нет."""
    if _client() is None:
        return None
    s = lic.current()
    if s is None or s.wall:
        return None
    link = _read()
    connected = link is not None
    token = _token(link) if link else None
    cal = _calendar(link) if link else None
    why = ""
    if s.state not in (lst.ACTIVE, lst.GRACE):
        state, why = S_READONLY, "gc_g_readonly"
    elif lic.feature_until("gcal") is None:
        state, why = S_PLUS, ("gc_g_plus_off" if connected else "gc_g_plus")
    elif not connected:
        state = S_OFF
    elif token is None:
        state, why = S_RECONNECT, "gc_g_elsewhere"
    elif link.get("dead") in _DEAD_CODE:
        state, why = S_RECONNECT, _DEAD_CODE[link["dead"]]
    elif cal is None:
        state, why = S_CHOOSE, ("gc_g_not_found" if _last["error"] == "gc_g_not_found" else "")
    elif link.get("paused"):
        state, why = S_PAUSED, "gc_g_paused"
    else:
        state, why = S_ON, _last["error"]
    here = remote_notice(request)
    local = here is None
    cals = [{"id": c["id"], "name": str(c.get("name") or c["id"]), "primary": c.get("primary") is True}
            for c in (_calendars(link) if link else [])]
    return {
        "state": state, "connected": connected,
        "account": str((link or {}).get("account") or ""),
        "calendar": {"id": cal["id"], "name": str(cal.get("name") or cal["id"])} if cal else None,
        "calendars": cals,
        "last": _when(str((link or {}).get("last_ok") or "")),
        "why": msg_view(why) if why else None,
        "notice": NOTICE, "privacy": dict(PRIVACY),
        "plus": dict(PLUS) if state == S_PLUS else None,
        "waiting": _waiting(), "remote": here, "every_min": POLL_MINUTES,
        "can": {"connect": local and state in (S_OFF, S_RECONNECT),
                "calendar": local and state in (S_CHOOSE, S_ON, S_PAUSED) and bool(cals),
                "check": state in (S_CHOOSE, S_ON, S_PAUSED),
                "disconnect": local and connected},
        "words": dict(WORDS),
    }


# ---------- вход ----------


def _port(request) -> int:
    """Порт, на котором слушает движок: адрес возврата обязан вести в этот же процесс."""
    server = request.scope.get("server")
    if isinstance(server, (tuple, list)) and len(server) == 2 and isinstance(server[1], int):
        return server[1]
    try:
        return int(os.environ.get("DENTART_PORT", "") or 8088)
    except ValueError:
        return 8088


def _prune_logins() -> None:
    now = time.monotonic()
    for k in [k for k, e in _logins.items() if now - e["at"] >= LOGIN_TTL]:
        del _logins[k]
    while len(_logins) >= LOGINS_MAX:
        del _logins[min(_logins, key=lambda k: _logins[k]["at"])]


async def start(request) -> tuple[str, str]:
    """«Conectează contul Google»: (код, адрес экрана Google). Адрес открывает браузер Windows —
    встроенное окно для входа Google запрещает правилами."""
    client = _client()
    if client is None:
        return "gc_g_none", ""
    if lic.feature_until("gcal") is None:
        return _gate_code(), ""
    me = request_user() or {}
    verifier, challenge = gauth.pkce()
    state = gauth.new_state()
    redirect = gauth.loopback(_port(request), BACK_PATH)
    _prune_logins()
    _logins[state] = {"verifier": verifier, "redirect": redirect, "at": time.monotonic(), "done": False,
                      "user": {"id": str(me.get("id") or ""), "role": str(me.get("role") or ""),
                               "name": str(me.get("name") or "")}}
    link = _read() or {}
    url = gauth.consent_url(client, redirect, state, challenge, auth_url=_ends().auth,
                            login_hint=str(link.get("account") or ""))
    return "gc_g_url", url


def _still_allowed(snap: dict) -> bool:
    """Право нажавшего — из файла учёток по id, как у входа: понижение действует сразу.
    Без файла учёток (вход по ключу сервера) людей нет — право снято при нажатии."""
    people = all_users()
    if not people:
        return can(snap, PERM_SCHEDULE_ALL)
    return can(next((u for u in people if u["id"] == snap.get("id")), None), PERM_SCHEDULE_ALL)


def _query_state(query: str) -> str:
    got = parse_qs(query or "", keep_blank_values=True).get("state") or [""]
    return got[0] if len(got) == 1 else ""


async def finish(request) -> tuple[str, int]:
    """Возврат из браузера Windows на 127.0.0.1. Адрес вне /admin и /api: куки программы в
    браузере нет, посредники его не видят, — поэтому всё проверяется здесь: пир соединения,
    state и PKCE своего входа, право нажавшего, гейт. В режиме восстановления и при битом
    профиле входа начать нельзя (гейт молчит без лицензии), и state не найдётся."""
    if not client_is_local(request):
        return "gc_g_back_local", 403
    query = request.url.query
    state = _query_state(query)
    entry = _logins.get(state)
    if entry is None or time.monotonic() - entry["at"] >= LOGIN_TTL:
        return "gc_g_back_state", 400
    if entry["done"]:
        return ("gc_g_back_again" if _read() is not None else "gc_g_back_state"), 200
    back = gauth.back(query, state)
    if back.code == gauth.BAD_STATE:
        return "gc_g_back_state", 400
    entry["done"] = True                  # код входа одноразовый: повтор адреса — уже не вход
    if back.code == gauth.ACCESS_DENIED:
        return "gc_g_back_denied", 200
    if back.code != gauth.OK:
        log.warning("gcal: login back refused: %s %s", back.code, back.reason)
        return "gc_g_back_failed", 400
    client = _client()
    if client is None:
        return "gc_g_none", 409
    if lic.feature_until("gcal") is None:
        return _gate_code(), 409
    if not _still_allowed(entry["user"]):
        return "gc_g_back_right", 403
    ends = _ends()
    r = await asyncio.to_thread(gauth.exchange, client, back.auth_code, entry["verifier"],
                                entry["redirect"], token_url=ends.token, agent=_agent())
    if r.code != gauth.OK:
        log.warning("gcal: exchange refused: %s %s", r.code, r.reason)
        return _BACK_WIRE.get(r.code, "gc_g_back_failed"), 400
    grant = r.grant
    missing = gauth.missing(grant.scopes or back.scopes)
    if gauth.EVENTS_READONLY in missing:
        await asyncio.to_thread(gauth.revoke, grant.refresh, revoke_url=ends.revoke, agent=_agent())
        return "gc_g_no_scope", 400
    protected = dpapi.protect(grant.refresh)
    if protected is None:
        return "gc_g_none", 409
    if gauth.CALENDARLIST_READONLY in missing:
        # без права на список Google отдаёт только основной календарь — по имени «primary»
        cals, account = [{"id": "primary", "name": "Calendarul principal", "primary": True}], ""
    else:
        got = await asyncio.to_thread(gapi.calendars, grant.access, base=ends.api, agent=_agent())
        cals = _cal_list(got) if got.code == gapi.OK else []
        account = next((c["id"] for c in cals if c["primary"] and "@" in c["id"]), "")
    async with _lockd():
        old = _read() or {}
        keep = _calendar(old)
        chosen = keep if keep and any(c["id"] == keep["id"] for c in cals) else (
            cals[0] if len(cals) == 1 else None)
        link = {"v": 1, "device": lic.device_id(), "token": protected, "account": account,
                "calendars": cals, "calendar": _cal_ref(chosen), "paused": False, "dead": "",
                "last_ok": "", "connected_at": _iso(datetime.now(timezone.utc)),
                "connected_by": entry["user"]["name"]}
        if not _write(link):
            return "gc_g_none", 409
        _access.update(token=grant.access, until=time.monotonic() + grant.expires_in - ACCESS_MARGIN)
        _last["error"] = ""
    await db.log_clinic_event("gcal", "Google Calendar: contul Google al clinicii a fost conectat",
                              entry["user"]["name"] or ACTOR)
    wake()
    return "gc_g_back_ok", 200


def back_page(code: str) -> str:
    """Страница в браузере Windows после возврата из Google — словами сервера."""
    return ("<!doctype html><html lang='ro'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>DentPilot</title></head><body style='font-family:system-ui,"
            "sans-serif;max-width:560px;margin:12vh auto;padding:0 16px;"
            "line-height:1.6;color:#162033'>"
            f"<p>{html.escape(msg_text(code) or msg_text('gc_g_back_failed'))}</p>"
            "</body></html>")


def _cal_list(reply: gapi.Reply) -> list:
    return [{"id": c.id, "name": c.name[:120], "primary": c.primary, "tz": c.tz}
            for c in reply.items[:CALENDARS_MAX]]


def _cal_ref(cal: dict | None) -> dict | None:
    return {"id": cal["id"], "name": str(cal.get("name") or cal["id"])[:120],
            "tz": str(cal.get("tz") or "")} if cal else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- проход ----------


async def _access_token(client: gauth.Client, link: dict, refresh_token: str, *, force: bool) -> str:
    """access-токен из памяти или новый по refresh-токену; '' — ошибка, код в _last['error']."""
    if not force and _access["token"] and time.monotonic() < _access["until"]:
        return _access["token"]
    r = await asyncio.to_thread(gauth.refresh, client, refresh_token, token_url=_ends().token,
                                agent=_agent())
    if r.code != gauth.OK:
        _forget_access()
        if r.code == gauth.INVALID_GRANT:
            link["dead"] = DEAD_GRANT
            _write(link)
        _last["error"] = _WIRE.get(r.code, "gc_g_failed")
        log.warning("gcal: refresh refused: %s %s", r.code, r.reason)
        return ""
    if r.grant.refresh and r.grant.refresh != refresh_token:
        protected = dpapi.protect(r.grant.refresh)
        if protected is not None:
            link["token"] = protected
            _write(link)
    _access.update(token=r.grant.access, until=time.monotonic() + r.grant.expires_in - ACCESS_MARGIN)
    return r.grant.access


async def _pass(*, manual: bool) -> tuple[str, dict | None]:
    """Один проход опроса под замком связи: (код исхода, счётчики слияния или None).
    `manual` — «Verifică acum»: снимает паузу и перечитывает список календарей."""
    client = _client()
    if client is None:
        return "gc_g_none", None
    if lic.feature_until("gcal") is None:
        return _gate_code(), None
    async with _lockd():
        link = _read()
        if link is None:
            return "gc_g_gone", None
        refresh_token = _token(link)
        if refresh_token is None:
            return "gc_g_elsewhere", None
        if link.get("dead") in _DEAD_CODE:
            return _DEAD_CODE[link["dead"]], None
        if link.get("paused"):
            if not manual:
                return "gc_g_paused", None
            link["paused"] = False
            _write(link)
        access = await _access_token(client, link, refresh_token, force=False)
        if not access:
            return _last["error"], None
        ends = _ends()
        if manual or not _calendars(link):
            got = await asyncio.to_thread(gapi.calendars, access, base=ends.api, agent=_agent())
            if got.code == gapi.UNAUTHORIZED:
                access = await _access_token(client, link, refresh_token, force=True)
                if not access:
                    return _last["error"], None
                got = await asyncio.to_thread(gapi.calendars, access, base=ends.api, agent=_agent())
            if got.code == gapi.OK:
                link["calendars"] = _cal_list(got)
                _write(link)
        cal = _calendar(link)
        if cal is None:
            return "gc_g_choose", None
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=gcal.HORIZON_DAYS)
        r = await asyncio.to_thread(gapi.events, access, cal["id"], now - LOOK_BACK, until,
                                    base=ends.api, agent=_agent())
        if r.code == gapi.UNAUTHORIZED:
            access = await _access_token(client, link, refresh_token, force=True)
            if not access:
                return _last["error"], None
            r = await asyncio.to_thread(gapi.events, access, cal["id"], now - LOOK_BACK, until,
                                        base=ends.api, agent=_agent())
        if r.code != gapi.OK:
            return _refused(link, r), None
        # окно опроса — свои часы: событие из вчерашних суток прошло, а не пропало
        local = now.astimezone(eng.TZ)
        got = await asyncio.to_thread(gcal.collect, gapi.occurrences(r.items, r.tz), local,
                                      until.astimezone(eng.TZ))
        count = await gcal.absorb(gcal.KIND_GOOGLE, cal["name"], got["items"], got["present"],
                                  actor=ACTOR, ext_id=cal["id"])
        link["last_ok"] = _iso(now)
        _write(link)
        _last["error"] = ""
        return "gc_g_checked", {**count, "past": got["past"], "beyond": got["beyond"]}


def _refused(link: dict, r: gapi.Reply) -> str:
    code = _WIRE.get(r.code, "gc_g_failed")
    if r.code == gapi.NO_SCOPE:
        link["dead"] = DEAD_SCOPE
        _write(link)
    elif r.code == gapi.NOT_FOUND:
        link["calendar"] = None
        _write(link)
    elif r.code == gapi.RATE_LIMITED and r.retry_after:
        _last["quiet_until"] = time.monotonic() + r.retry_after
    _last["error"] = code
    log.warning("gcal: events refused: %s %s", r.code, r.reason)
    return code


async def tick() -> str:
    """Проход цикла: гейт — на каждом, без кэша; предел Google — пропуск тиков."""
    if lic.feature_until("gcal") is None:
        return "off"
    if time.monotonic() < _last["quiet_until"]:
        return "gc_g_rate"
    code, _count = await _pass(manual=False)
    return code


def _tick_seconds() -> float:
    try:
        s = float(os.environ.get(TICK_ENV, "") or 0)
    except ValueError:
        s = 0
    return s if s > 0 else POLL_MINUTES * 60.0


async def _loop() -> None:
    global _wake
    _wake = asyncio.Event()
    while True:
        try:
            await tick()
        except Exception as e:  # noqa: BLE001 — фон не имеет права умереть
            log.warning("gcal: tick failed: %r", e)
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=_tick_seconds())
        except asyncio.TimeoutError:
            pass


def wake() -> None:
    if _wake is not None:
        _wake.set()


def poll_async() -> None:
    """Из хука старта main.py: опрос в фоне, старт его не ждёт."""
    global _task
    if _task is None:
        _task = asyncio.get_running_loop().create_task(_loop())


# ---------- команды экрана ----------


async def check() -> tuple[str, dict | None]:
    """«Verifică acum»: снимает паузу, перечитывает список календарей и события."""
    _last["quiet_until"] = 0.0
    return await _pass(manual=True)


async def choose(cal_id: str) -> tuple[str, dict | None]:
    """Выбор календаря и сразу первая проверка — человек ждёт событий, а не таймера."""
    if _client() is None:
        return "gc_g_none", None
    if lic.feature_until("gcal") is None:
        return _gate_code(), None
    async with _lockd():
        link = _read()
        if link is None:
            return "gc_g_gone", None
        cal = next((c for c in _calendars(link) if c["id"] == cal_id), None)
        if cal is None:
            return "gc_g_bad", None
        link["calendar"] = _cal_ref(cal)
        _write(link)
        _last["error"] = ""
    await db.log_clinic_event("gcal", f"Google Calendar: ales calendarul „{cal['name'][:120]}”",
                              _actor())
    code, count = await _pass(manual=True)
    return ("gc_g_calendar" if code == "gc_g_checked" else code), count


async def disconnect() -> str:
    """«Deconectează»: отзыв у Google и удаление файла связи. Гейт не спрашивается: уйти можно
    всегда, и в режиме чтения тоже. Google не ответил — файл всё равно удаляется."""
    async with _lockd():
        link = _read()
        if link is None:
            return "gc_g_gone"
        refresh_token = _token(link)
        revoked = False
        if refresh_token:
            r = await asyncio.to_thread(gauth.revoke, refresh_token, revoke_url=_ends().revoke,
                                        agent=_agent())
            revoked = r.code in (gauth.OK, gauth.INVALID_GRANT)
        _remove()
        _forget_access()
        _last.update(error="", quiet_until=0.0)
    await db.log_clinic_event("gcal", "Google Calendar: contul Google al clinicii a fost deconectat",
                              _actor())
    return "gc_g_off" if revoked else "gc_g_off_local"


async def clear_paused(clear) -> tuple[str, bool]:
    """«Șterge tot din Google» при живой связи: сперва пауза, потом стирание — под тем же замком,
    что проход, иначе опрос вернул бы стёртое через несколько минут."""
    async with _lockd():
        link = _read()
        held = link is not None and (bool(link.get("paused")) or _write({**link, "paused": True}))
        code = await clear()
    return code, held
