"""Дверь к Google врачей: файл связи, токены, замок врача, уровень подробности событий.

Подключение врача пишет запись только через store(); сверка журнала с календарём спрашивает
access(), report(), done(), bump_epoch(), leave(), level() — файл, DPAPI и вход Google знает только
этот модуль. Провод — core/gauth.py (токены) и core/gwrite.py (календарь и события).

- Файл `google-medici.json` лежит рядом с clinic.json, не в картотеке: refresh-токены под DPAPI этой
  учётки Windows, привязаны к device.json; копии картотеки его не берут. «Не расшифровался здесь»
  считается на лету и в файл не пишется: под второй учёткой Windows запись погасила бы рабочую
  связь первой.
- Право — дата `gcal_doctor` в файле лицензии, на каждом входе в дверь, без кэша. Уход
  (`leave=True`) права не спрашивает: убрать календарь можно и после конца права.
- Отзыва у Google здесь нет: он проектный и оборвал бы все связи аккаунта — календари других врачей
  на том же аккаунте и связь клиники.
- Запись врача в файл — целиком, без await между чтением и записью: замок у каждого врача свой, и
  проходы двух врачей не теряют записей друг друга.
- Восстановленную из копии картотеку ловит счётчик проходов: `seq` файла ≠ `seq` в schema_meta.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .. import db, dpapi, version
from . import demo, gauth, gclient, gwrite
from . import license as lic

log = logging.getLogger("gdoc")

FILE_NAME = "google-medici.json"
SYNC_GATE = "gcal_doctor"
META_CAL, META_SEQ, META_LEVEL = "gdoc_cal:", "gdoc_seq:", "gdoc_level"
ACTOR = "sistem"
ACCESS_MARGIN = 60                  # access-токен считается истёкшим на минуту раньше
MARK_EVERY = 3600.0                 # метку календаря проверять не чаще раза в час
LEVEL_WORDS = {"time": "doar ora", "initials": "inițiale", "name": "nume și serviciu"}

A_OK, A_NONE, A_GATE = "ok", "none", "gate"
A_ELSEWHERE, A_DEAD, A_FOREIGN = "elsewhere", "dead", "foreign"
A_RATE, A_OFFLINE, A_NO_CLIENT = "rate", "offline", "no_client"
ACCESS_CODES = (A_OK, A_NONE, A_GATE, A_ELSEWHERE, A_DEAD, A_FOREIGN, A_RATE, A_OFFLINE, A_NO_CLIENT)

# почему связь мертва (поле `dead` файла): новый вход нужен в каждом случае
DEAD_GRANT, DEAD_SCOPE, DEAD_GONE = "invalid_grant", "no_scope", "gone"
DEAD_REASONS = (DEAD_GRANT, DEAD_SCOPE, DEAD_GONE)

S_ON, S_RECONNECT, S_FOREIGN = "on", "reconnect", "foreign"

L_DELETED, L_LOCAL, L_KEPT, L_NONE = "deleted", "local", "kept", "none"
LEAVE_WHY = {"disconnect": "deconectat", "archived": "medicul a fost arhivat",
             "removed": "medicul nu mai este în listă"}
# Отсюда календарь удалить ещё можно: сеть, предел Google, другая учётка Windows, сборка без клиента.
_LATER = (A_OFFLINE, A_RATE, A_ELSEWHERE, A_NO_CLIENT)

LV_SET, LV_SAME, LV_BAD = "set", "same", "bad"


@dataclass(frozen=True)
class Access:
    code: str
    token: str = ""                 # access-токен Google — только при A_OK; не в лог и не в базу
    cal_id: str = ""
    name: str = ""                  # имя календаря у Google по последней проверке
    mark: str = ""                  # метка связи — последняя строка описания календаря
    epoch: int = 0
    seq: int = 0                    # счётчик проходов, писавших в Google, — из файла
    tag: str = ""                   # gwrite.clinic_tag(clinic_id лицензии)
    rebuild: bool = False           # картотеку восстановили из копии или календарь подхвачен заново
    api: str = gwrite.API           # куда слать запросы gwrite (стенд прогона — вне exe)
    agent: str = ""
    reason: str = ""                # исход провода для лога и слов экрана
    retry_after: int = 0


@dataclass(frozen=True)
class Ends:
    auth: str = gauth.AUTH_URL
    token: str = gauth.TOKEN_URL
    api: str = gwrite.API


class DoctorLock:
    """Замок врача, повторно входимый той же задачей: проход сверки держит его целиком и зовёт
    дверь, которая берёт его сама. Задача, порождённая внутри, — уже другая и будет ждать."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None
        self._depth = 0

    def locked(self) -> bool:
        return self._lock.locked()

    async def __aenter__(self) -> DoctorLock:
        me = asyncio.current_task()
        if me is not None and self._owner is me:
            self._depth += 1
            return self
        await self._lock.acquire()
        self._owner, self._depth = me, 1
        return self

    async def __aexit__(self, *exc) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


_locks: dict[str, DoctorLock] = {}
_tokens: dict[str, dict] = {}       # dk → {"token", "until"} — access-токены только в памяти
_checked: dict[str, float] = {}     # dk → когда метка календаря сверена (monotonic)
# Сверка регистрирует себя здесь: подключение будит её и ждёт прохода врача, не импортируя соседний модуль.
_sync: dict = {"wake": None, "run": None, "stats": None}
_runs: set = set()                  # проходы, которых перестали ждать: цикл держит задачу слабо


def lock(dk: str) -> DoctorLock:
    """Один замок врача: вход (запись файла), «Deconectează», уход, проход сверки."""
    got = _locks.get(dk)
    if got is None:
        got = _locks[dk] = DoctorLock()
    return got


def ends() -> Ends:
    base = gclient.stand_base()
    return Ends(base + "/auth", base + "/token", base + "/calendar/v3") if base else Ends()


def agent() -> str:
    # Без личности машины и ключа лицензии: Google их знать незачем (Anexa 2).
    return f"DentPilot/{version.APP_VERSION}"


def client() -> gauth.Client | None:
    """Клиент Google — или None: демо, сервер, нет DPAPI, лицензия не применяется, сборка без клиента."""
    if demo.on() or not dpapi.available() or not lic.applies():
        return None
    return gclient.client()


def new_mark() -> str:
    return "".join(secrets.choice(gwrite.B32HEX) for _ in range(gwrite.MARK_LEN))


# ---------- файл связи ----------


def _path() -> pathlib.Path | None:
    d = lic.folder()
    return d / FILE_NAME if d is not None else None


def _load() -> tuple[dict, bool]:
    """(врачи, можно ли писать). Не прочитался из-за диска — писать нельзя: запись одного врача
    стёрла бы остальных."""
    p = _path()
    if p is None:
        return {}, False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, True
    except ValueError:
        return {}, True
    except OSError as e:
        log.warning("gdoc: %s not read: %r", FILE_NAME, e)
        return {}, False
    docs = data.get("doctors") if isinstance(data, dict) else None
    if not isinstance(docs, dict):
        return {}, True
    return {k: v for k, v in docs.items() if isinstance(k, str) and isinstance(v, dict)}, True


def _entry(dk: str) -> dict | None:
    e = _load()[0].get(dk)
    return dict(e) if e is not None else None


def _put(dk: str, entry: dict | None) -> bool:
    """Запись врача целиком; None — забыть врача. Только под lock(dk)."""
    p = _path()
    docs, ok = _load()
    if p is None or not ok:
        return False
    if entry is None:
        docs.pop(dk, None)
    else:
        docs[dk] = entry
    try:
        if not docs:
            p.unlink(missing_ok=True)
            return True
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"v": 1, "doctors": docs}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        log.warning("gdoc: %s not written: %r", FILE_NAME, e)
        return False
    return True


def _refresh_of(e: dict) -> str | None:
    """refresh-токен врача; None — запись не с этого компьютера или не этой учётки Windows.
    Только шифротекст: открытый токен в файле — чужая запись, не наша."""
    stored = str(e.get("token") or "")
    if not stored.startswith(dpapi.PREFIX) or e.get("device") != lic.device_id():
        return None
    return dpapi.unprotect(stored) or None


def _cal(e: dict) -> dict:
    cal = e.get("calendar")
    return cal if isinstance(cal, dict) and isinstance(cal.get("id"), str) and cal["id"] else {}


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


def _tag() -> str:
    s = lic.current()
    return gwrite.clinic_tag(s.claim.clinic_id) if s is not None and s.claim is not None else ""


def _forget_access(dk: str) -> None:
    _tokens.pop(dk, None)
    _checked.pop(dk, None)


# ---------- вход в дверь ----------


async def access(dk: str, *, leave: bool = False, force: bool = False) -> Access:
    """Ключ к календарю врача. `leave` — уход (Deconectează, архив, уборка после конца права):
    право не спрашивается. `force` — новый access-токен и свежая сверка метки календаря."""
    c = client()
    if c is None:
        return Access(A_NO_CLIENT)
    if not leave and lic.feature_until(SYNC_GATE) is None:
        return Access(A_GATE)
    async with lock(dk):
        e = _entry(dk)
        if e is None or not _cal(e):
            return Access(A_NONE)
        was = json.dumps(e, sort_keys=True)
        got = await _open(c, dk, e, force=force)
        if json.dumps(e, sort_keys=True) != was:
            _put(dk, e)
    return got


async def _open(c: gauth.Client, dk: str, e: dict, *, force: bool) -> Access:
    """Токен и метка; меняет только `e` — файл пишет access() под замком."""
    if e.get("foreign"):
        return Access(A_FOREIGN)
    if e.get("dead") in DEAD_REASONS:
        return Access(A_DEAD, reason=e["dead"])
    refresh = _refresh_of(e)
    if refresh is None:
        return Access(A_ELSEWHERE)
    where, who = ends(), agent()
    cached = _tokens.get(dk)
    token = cached["token"] if cached and not force and time.monotonic() < cached["until"] else ""
    if not token:
        token, bad = await _renew(c, dk, e, refresh, where)
        if bad is not None:
            return bad
    cal_id = _cal(e)["id"]
    seen = _checked.get(dk)
    if force or seen is None or time.monotonic() - seen >= MARK_EVERY:
        r = await asyncio.to_thread(gwrite.calendar_get, token, cal_id, base=where.api, agent=who)
        if r.code == gwrite.UNAUTHORIZED:
            token, bad = await _renew(c, dk, e, refresh, where)
            if bad is not None:
                return bad
            r = await asyncio.to_thread(gwrite.calendar_get, token, cal_id, base=where.api, agent=who)
        bad = _looked(dk, e, r)
        if bad is not None:
            return bad
    seq = _int(e.get("seq"))
    stored = await db.get_meta(META_SEQ + dk)
    # нет отметки в картотеке, а проходы уже писали — картотека старше календаря
    behind = stored != str(seq) if stored is not None else seq > 0
    return Access(A_OK, token=token, cal_id=cal_id, name=str(_cal(e).get("name") or ""),
                  mark=str(e.get("mark") or ""), epoch=max(1, _int(e.get("epoch"))), seq=seq,
                  tag=_tag(), rebuild=bool(e.get("rebuild")) or behind, api=where.api, agent=who)


async def _renew(c: gauth.Client, dk: str, e: dict, refresh: str, where: Ends) -> tuple[str, Access | None]:
    r = await asyncio.to_thread(gauth.refresh, c, refresh, token_url=where.token, agent=agent())
    if r.code != gauth.OK:
        _tokens.pop(dk, None)
        log.warning("gdoc: %s refresh refused: %s %s", dk, r.code, r.reason)
        if r.code == gauth.INVALID_GRANT:
            e["dead"] = DEAD_GRANT
            return "", Access(A_DEAD, reason=DEAD_GRANT)
        return "", Access(A_RATE if r.code == gauth.RATE_LIMITED else A_OFFLINE, reason=r.code)
    if r.grant.refresh and r.grant.refresh != refresh:
        protected = dpapi.protect(r.grant.refresh)
        if protected is not None:
            e["token"] = protected
    _tokens[dk] = {"token": r.grant.access, "until": time.monotonic() + r.grant.expires_in - ACCESS_MARGIN}
    return r.grant.access, None


def _looked(dk: str, e: dict, r: gwrite.Reply) -> Access | None:
    """Исход сверки метки календаря; None — календарь наш и на месте."""
    if r.code == gwrite.OK:
        got = gwrite.mark_of(r.data["description"])
        # Чужая метка — календарь пишет другая установка (старый ПК с копией папки). Пустое
        # описание — правка врача в Google: календарь наш, описание вернёт сверка.
        if got and got != e.get("mark"):
            e["foreign"] = True
            return Access(A_FOREIGN)
        if r.data["dataOwner"]:
            e["account"] = r.data["dataOwner"]
        e["calendar"] = {**_cal(e), "name": r.data["summary"] or _cal(e).get("name", "")}
        e["checked_at"] = _now()
        _checked[dk] = time.monotonic()
        return None
    if r.code in (gwrite.NOT_FOUND, gwrite.GONE):
        e["dead"] = DEAD_GONE
        return Access(A_DEAD, reason=DEAD_GONE)
    if r.code == gwrite.NO_SCOPE:
        e["dead"] = DEAD_SCOPE
        return Access(A_DEAD, reason=DEAD_SCOPE)
    log.warning("gdoc: %s calendar check refused: %s %s", dk, r.code, r.reason)
    if r.code == gwrite.RATE_LIMITED:
        return Access(A_RATE, reason=r.reason or r.code, retry_after=r.retry_after)
    return Access(A_OFFLINE, reason=r.reason or r.code)


async def report(dk: str, code: str) -> None:
    """Исход провода у сверки. NO_SCOPE — право снято; NOT_FOUND и GONE — календаря нет
    (так отвечает вставка или повтор после 404): связь мертва до нового входа."""
    if code == gwrite.UNAUTHORIZED:
        _tokens.pop(dk, None)
        return
    dead = {gwrite.NO_SCOPE: DEAD_SCOPE, gwrite.NOT_FOUND: DEAD_GONE, gwrite.GONE: DEAD_GONE}.get(code)
    if dead is None:
        return
    async with lock(dk):
        e = _entry(dk)
        if e is None or e.get("dead"):
            return
        e["dead"] = dead
        _put(dk, e)
    _forget_access(dk)
    log.warning("gdoc: %s stopped: %s", dk, dead)


async def done(dk: str, seq: int, *, wrote: bool = True) -> int:
    """Проход удался. `wrote` — он писал в Google: счётчик +1 сначала в файле, потом в картотеке;
    упала запись файла — картотека не трогается, иначе разошлись бы без восстановления."""
    async with lock(dk):
        e = _entry(dk)
        if e is None:
            return seq
        new = seq + 1 if wrote else _int(e.get("seq"))
        e["seq"] = new
        e["last_ok"] = _now()
        if _put(dk, e) and wrote:
            await db.set_meta(META_SEQ + dk, str(new))
    return new


async def bump_epoch(dk: str) -> int:
    """После пересборки (все наши события удалены): новая эпоха — новые id событий; счётчик
    файла — в картотеку."""
    async with lock(dk):
        e = _entry(dk)
        if e is None:
            return 0
        e["epoch"] = max(1, _int(e.get("epoch"))) + 1
        e.pop("rebuild", None)
        if _put(dk, e):
            await db.set_meta(META_SEQ + dk, str(_int(e.get("seq"))))
    return e["epoch"]


async def calendar_named(dk: str, name: str) -> None:
    """Сверка переименовала календарь у Google — то же имя в файл."""
    async with lock(dk):
        e = _entry(dk)
        if e is not None and _cal(e):
            e["calendar"] = {**_cal(e), "name": name}
            _put(dk, e)


async def store(dk: str, *, refresh: str, account: str, cal_id: str, cal_name: str, mark: str,
                actor: str, reused: bool, access_token: str = "", expires_in: int = 0) -> bool:
    """Запись врача после входа. `reused` — календарь найден по id из картотеки, а не создан:
    в нём могут лежать события прошлой связи — первая сверка пересоберёт его."""
    if not dk or not cal_id or len(mark) != gwrite.MARK_LEN:
        raise ValueError("entry")
    protected = dpapi.protect(refresh)
    if protected is None:
        return False
    async with lock(dk):
        old = _entry(dk) or {}
        epoch = max(1, _int(old.get("epoch")))
        entry = {"device": lic.device_id(), "token": protected, "account": account,
                 "calendar": {"id": cal_id, "name": cal_name}, "mark": mark,
                 "epoch": epoch + 1 if old and not reused else epoch,
                 "seq": _int(old.get("seq")) if reused else 0,
                 "connected_at": _now(), "connected_by": actor, "dead": "", "foreign": False,
                 "checked_at": _now(), "last_ok": ""}
        if reused:
            entry["rebuild"] = True
        if not _put(dk, entry):
            return False
        _forget_access(dk)
        if access_token and expires_in > ACCESS_MARGIN:
            _tokens[dk] = {"token": access_token, "until": time.monotonic() + expires_in - ACCESS_MARGIN}
            _checked[dk] = time.monotonic()
        await db.set_meta(META_CAL + dk, cal_id)
        if not reused:
            await db.set_meta(META_SEQ + dk, "0")
    await db.log_clinic_event("gdoc", f"Calendarele medicilor: „{cal_name[:120]}” — conectat", actor)
    return True


async def leave(dk: str, why: str, actor: str = ACTOR, *, must_delete: bool = False) -> str:
    """Уход врача: удалить его календарь у Google и забыть ключ, без отзыва доступа. `must_delete`
    (архив, уборка) — не удалось удалить по причине, которая пройдёт, — ключ остаётся (L_KEPT),
    следующий проход повторит; иначе календарь остался бы у Google навсегда."""
    text = LEAVE_WHY.get(why)
    if text is None:
        raise ValueError("why")
    async with lock(dk):
        e = _entry(dk)
        if e is None:
            return L_NONE
        a = await access(dk, leave=True, force=True)
        deleted = a.code == A_DEAD and a.reason == DEAD_GONE
        later = a.code in _LATER
        if a.code == A_OK:
            r = await asyncio.to_thread(gwrite.calendar_delete, a.token, a.cal_id, base=a.api, agent=a.agent)
            deleted = r.code in (gwrite.OK, gwrite.GONE, gwrite.NOT_FOUND)
            later = not deleted and r.code != gwrite.NO_SCOPE
            if not deleted:
                log.warning("gdoc: %s calendar not deleted: %s %s", dk, r.code, r.reason)
        if must_delete and later:
            return L_KEPT
        name = str(_cal(e).get("name") or dk)
        if not _put(dk, None):
            return L_KEPT
        _forget_access(dk)
        if deleted:
            await db.del_meta(META_CAL + dk)
        await db.del_meta(META_SEQ + dk)
    await db.log_clinic_event("gdoc", f"Calendarele medicilor: „{name[:120]}” — {text}", actor)
    return L_DELETED if deleted else L_LOCAL


# ---------- для экранов ----------


def linked() -> dict[str, dict]:
    """dk → состояние связи без сети: для экранов и предупреждения «Deconectează» связи клиники."""
    out = {}
    for dk, e in sorted(_load()[0].items()):
        cal = _cal(e)
        if e.get("foreign"):
            state, why = S_FOREIGN, "foreign"
        elif e.get("dead") in DEAD_REASONS:
            state, why = S_RECONNECT, e["dead"]
        elif _refresh_of(e) is None:
            state, why = S_RECONNECT, "elsewhere"
        else:
            state, why = S_ON, ""
        out[dk] = {"state": state, "why": why, "account": str(e.get("account") or ""),
                   "calendar": {"id": cal["id"], "name": str(cal.get("name") or "")} if cal else None,
                   "connected_at": str(e.get("connected_at") or ""),
                   "connected_by": str(e.get("connected_by") or ""),
                   "last_ok": str(e.get("last_ok") or ""), "checked_at": str(e.get("checked_at") or "")}
    return out


def same_account(email: str) -> list[str]:
    """Врачи на том же аккаунте Google: отзыв связи клиники оборвёт и их календари."""
    want = (email or "").strip().lower()
    return [dk for dk, v in linked().items() if want and v["account"].strip().lower() == want]


async def level() -> str:
    got = await db.get_meta(META_LEVEL)
    return got if got in gwrite.LEVELS else gwrite.DEFAULT_LEVEL


async def set_level(chosen: str, actor: str) -> str:
    """Уровень один на клинику; смена меняет отпечатки — сверка перепишет события сама."""
    if chosen not in gwrite.LEVELS:
        return LV_BAD
    if await level() == chosen:
        return LV_SAME
    await db.set_meta(META_LEVEL, chosen)
    await db.log_clinic_event("gdoc", f"Calendarele medicilor: nivelul „{LEVEL_WORDS[chosen]}”", actor)
    return LV_SET


# ---------- сверка: крючки ----------


def attach_sync(*, wake, run, stats) -> None:
    """Сверка при старте: `wake(dk | None)`, корутина `run(dk) -> str` (берёт lock(dk) сама),
    `stats(dk) -> dict`. Повторный вызов заменяет; None — сверки нет."""
    _sync.update(wake=wake, run=run, stats=stats)


def sync_wake(dk: str | None = None) -> None:
    fn = _sync["wake"]
    if fn is not None:
        fn(dk)


async def sync_run(dk: str, timeout: float) -> str | None:
    """Прогнать врача и ждать до `timeout`; None — сверки нет, не успела или упала. Проход, которого
    перестали ждать, доходит до конца: оборванный посреди записи пришлось бы догонять. Из прохода
    врача не звать — новый проход ждал бы его замка до конца ожидания."""
    fn = _sync["run"]
    if fn is None:
        return None
    task = asyncio.ensure_future(fn(dk))
    _runs.add(task)
    task.add_done_callback(_run_done)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except TimeoutError:
        return None
    except Exception:  # noqa: BLE001 — экран ждёт ответа, а не 500; в лог пишет _run_done
        return None


def _run_done(task: asyncio.Task) -> None:
    _runs.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.warning("gdoc: sync run failed: %r", task.exception())


def sync_stats(dk: str) -> dict:
    """{} без сверки; иначе её ответ как есть: {last_ok, error, error_at, pending}."""
    fn = _sync["stats"]
    return fn(dk) if fn is not None else {}
