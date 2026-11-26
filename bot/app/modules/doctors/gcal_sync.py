"""Сверка журнала с календарями врачей в Google: что должно быть у врача и что ему уже отправлено.

К Google — только через дверь core/gdoc.py (ключ, право, замок врача) проводом core/gwrite.py: файла
связи, DPAPI и входа Google здесь нет. Отправленное — таблица `gdoc_sent` (db/gpush.py).

- Разница — по ВСЕЙ таблице отправленного, не по окну: отмена, перенос к другому врачу, стёртый или
  обезличенный пациент, уход из окна и смена уровня подробности находятся одним правилом.
- Пересохранение без правки — ни одного запроса: отпечаток тела только от видимого врачу.
- Темп: не больше BURST записей Google на врача за проход и PAUSE_S между ними; хвост догоняет
  следующий проход через CATCHUP_S. Проходы начинаются на LEAD_S раньше SYNC_MINUTES — обещание
  «не дольше SYNC_MINUTES» держится с запасом на сам проход.
- Права нет (Premium кончился, режим чтения): уход убирает из календаря врача все наши события и пишет
  в описании, что обновление остановлено; связь и ключ хранятся, право вернулось — окно вставляется
  заново из базы.
- Врач в архиве или пропал из списка — его календарь удаляется; не вышло — повтор следующим проходом.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from ... import db
from ... import engine as eng
from ...core import gdoc, gwrite
from ...core import license as lic

log = logging.getLogger("gdoc")

SYNC_MINUTES = 5
TICK_ENV = "DENTART_GDOC_TICK_S"          # стенд: секунды между проходами вместо SYNC_MINUTES
LEAD_S = 60.0
BACK, AHEAD = timedelta(days=30), timedelta(days=90)
BURST = 100                               # записей Google на врача за проход
PAUSE_S = 0.2                             # между записями: Google ограничивает частую запись в один календарь
CATCHUP_S = 30.0
QUIET_MAX = 64                            # потолок растущей паузы после предела Google, секунд
DESCRIBE_EVERY = 3600.0                   # имя и описание календаря — не чаще раза в час
META_PAUSED = "gdoc_paused:"              # + dk: проход ухода сделан, право ещё закрыто

NOTE = "Modificările — doar în DentPilot."
DESC_ON = "Programările medicului din DentPilot. Modificările — doar în DentPilot."
DESC_OFF = ("Actualizarea este oprită: DentPilot Premium nu este activ. Programările au fost scoase din "
            "calendar și revin singure după reînnoire.")

R_OK, R_MORE, R_PAUSED = "ok", "more", "paused"
E_FORBIDDEN, E_BAD = "forbidden", "bad_request"

_state: dict[str, dict] = {}              # dk → последний проход, ошибка, хвост, тишина предела
_wake: asyncio.Event | None = None
_task: asyncio.Task | None = None


def _st(dk: str) -> dict:
    got = _state.get(dk)
    if got is None:
        got = _state[dk] = {"last_ok": "", "error": "", "error_at": "", "pending": 0, "quiet_until": 0.0,
                            "backoff": 0, "described": None}
    return got


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(st: dict, code: str) -> None:
    # время ошибки — с её первого раза: экран говорит, с каких пор не выходит
    if code and st["error"] != code:
        st["error_at"] = _iso(datetime.now(timezone.utc))
    elif not code:
        st["error_at"] = ""
    st["error"] = code


def _fail(dk: str, code: str, wait: int = 0) -> str:
    st = _st(dk)
    if code == gdoc.A_RATE:
        st["backoff"] = min(QUIET_MAX, st["backoff"] * 2 or 2)
        st["quiet_until"] = time.monotonic() + (wait or st["backoff"])
    _error(st, code)
    return code


def _ok(dk: str, pending: int, more: bool, skipped: int) -> str:
    st = _st(dk)
    st.update(last_ok=_iso(datetime.now(timezone.utc)), pending=pending, backoff=0, quiet_until=0.0)
    _error(st, E_BAD if skipped else "")
    return R_MORE if more else R_OK


class _Run:
    """Один проход врача: ключ двери, уровень, что записано, на чём остановились."""

    def __init__(self, dk: str, a: gdoc.Access, level: str, *, leaving: bool = False) -> None:
        self.dk, self.a, self.level, self.leaving = dk, a, level, leaving
        self.wrote = False
        self.stop = ""
        self.wait = 0
        self.skipped = 0

    async def call(self, fn, *args, **kw) -> gwrite.Reply | None:
        """Запрос ключом двери; access-токен истёк — новый и один повтор. None — дверь закрылась."""
        r = await self._send(fn, args, kw)
        if r.code != gwrite.UNAUTHORIZED:
            return r
        await gdoc.report(self.dk, r.code)
        fresh = await gdoc.access(self.dk, leave=self.leaving, force=True)
        if fresh.code != gdoc.A_OK:
            self.stop, self.wait = fresh.code, fresh.retry_after
            return None
        self.a = fresh
        return await self._send(fn, args, kw)

    async def _send(self, fn, args, kw) -> gwrite.Reply:
        return await asyncio.to_thread(fn, self.a.token, self.a.cal_id, *args, base=self.a.api,
                                       agent=self.a.agent, **kw)

    async def refused(self, r: gwrite.Reply) -> None:
        """Отказ, после которого врач в этом проходе не продолжается; тело, которое Google не принял
        (ошибка нашей стороны), только пропускается. NOT_FOUND сюда доходит только про календарь."""
        log.warning("gdoc: %s sync refused: %s %s", self.dk, r.code, r.reason)
        if r.code == gwrite.BAD_REQUEST:
            self.skipped += 1
        elif r.code == gwrite.RATE_LIMITED:
            self.stop, self.wait = gdoc.A_RATE, r.retry_after
        elif r.code in (gwrite.NO_SCOPE, gwrite.NOT_FOUND, gwrite.GONE):
            await gdoc.report(self.dk, r.code)
            self.stop = gdoc.A_DEAD
        elif r.code == gwrite.FORBIDDEN:
            self.stop = E_FORBIDDEN
        else:
            self.stop = gdoc.A_OFFLINE

    def body(self, ap: gwrite.Appt, event_id: str) -> dict:
        return gwrite.event_body(self.level, ap, tag=self.a.tag, event_id=event_id, note=NOTE)


# ---------- проход врача ----------


def _appt(r: dict) -> gwrite.Appt:
    m = r["duration_min"]
    at = r["starts_at"]
    # база хранит UTC; строка без пояса иначе уронила бы проход врача целиком
    return gwrite.Appt(id=r["id"], start=at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc),
                       minutes=m if isinstance(m, int) and not isinstance(m, bool) and m > 0 else 60,
                       room=r["room"] or "", patient=r["patient"] or "", file_no=r["file_no"] or "",
                       service=r["service"] or "")


def _order(at: datetime | None, now: datetime) -> tuple:
    """Ближнее будущее, потом дальнее, потом прошлое от недавнего."""
    if at is None:
        return (2, 0.0)
    return (0, at.timestamp()) if at >= now else (1, -at.timestamp())


def _plan(run: _Run, rows: list, sent: dict, now: datetime) -> list:
    acts, want = [], set()
    for r in rows:
        ap = _appt(r)
        want.add(ap.id)
        stamp = gwrite.body_stamp(run.body(ap, gwrite.event_id(run.a.tag, run.a.epoch, ap.id, 0)))
        row = sent.get(ap.id)
        if row is None or not row["stamp"]:
            acts.append((_order(ap.start, now), "insert", ap, row["gen"] if row else 0, stamp))
        elif row["stamp"] != stamp:
            acts.append((_order(ap.start, now), "update", ap, row, stamp))
    for appt_id, row in sent.items():
        if appt_id not in want and row["stamp"]:
            acts.append((_order(row["starts_at"], now), "delete", appt_id, row, ""))
    acts.sort(key=lambda act: act[0])
    return acts


async def _insert(run: _Run, ap: gwrite.Appt, gen: int, stamp: str, *, again: bool = True) -> bool:
    eid = gwrite.event_id(run.a.tag, run.a.epoch, ap.id, gen)
    body = run.body(ap, eid)
    r = await run.call(gwrite.event_insert, body)
    if r is None:
        return False
    if r.code == gwrite.DUPLICATE:
        # свой id: вставка, ответ которой потерялся, или «надгробие» — то же тело поверх
        r = await run.call(gwrite.event_update, eid, body)
        if r is None:
            return False
        if r.code in (gwrite.NOT_FOUND, gwrite.GONE):
            # «надгробие» не воскресло — следующее поколение, новый id
            if again:
                return await _insert(run, ap, gen + 1, stamp, again=False)
            await db.gdoc_sent_put(run.dk, ap.id, eid, run.a.epoch, gen + 1, "", run.a.cal_id, ap.start)
            return False
    if r.code == gwrite.OK:
        await db.gdoc_sent_put(run.dk, ap.id, eid, run.a.epoch, gen, stamp, run.a.cal_id, ap.start)
        run.wrote = True
        return True
    await run.refused(r)
    return False


async def _update(run: _Run, ap: gwrite.Appt, row: dict, stamp: str) -> bool:
    eid = row["event_id"]
    r = await run.call(gwrite.event_update, eid, run.body(ap, eid))
    if r is None:
        return False
    if r.code == gwrite.OK:
        await db.gdoc_sent_put(run.dk, ap.id, eid, run.a.epoch, row["gen"], stamp, run.a.cal_id, ap.start)
        run.wrote = True
        return True
    if r.code in (gwrite.NOT_FOUND, gwrite.GONE):
        # событие у Google исчезло совсем — вставить заново следующим поколением
        return await _insert(run, ap, row["gen"] + 1, stamp)
    await run.refused(r)
    return False


async def _delete(run: _Run, appt_id: int, row: dict) -> bool:
    r = await run.call(gwrite.event_delete, row["event_id"])
    if r is None:
        return False
    if r.code in (gwrite.OK, gwrite.GONE, gwrite.NOT_FOUND):
        await db.gdoc_sent_off(run.dk, appt_id)
        run.wrote = run.wrote or r.code == gwrite.OK
        return True
    await run.refused(r)
    return False


async def _work(run: _Run, acts: list) -> int:
    """Первые BURST действий по порядку; сколько удалось."""
    n = 0
    for i, act in enumerate(acts[:BURST]):
        if i and PAUSE_S:
            await asyncio.sleep(PAUSE_S)
        _key, kind, what, extra, stamp = act
        if kind == "insert":
            n += await _insert(run, what, extra, stamp)
        elif kind == "update":
            n += await _update(run, what, extra, stamp)
        else:
            n += await _delete(run, what, extra)
        if run.stop:
            break
    return n


async def _describe(run: _Run, text: str) -> bool:
    """Имя календаря «DentPilot · клиника · врач» и описание с меткой связи. Только сразу после
    свежей сверки метки: старая установка с копией папки не перепишет метку новой."""
    if len(run.a.mark) != gwrite.MARK_LEN:
        _st(run.dk)["described"] = time.monotonic()
        return True
    name = gwrite.calendar_summary(eng.CLINIC_NAME, eng.DOCTORS.get(run.dk, ""))
    when = datetime.now(eng.TZ).strftime("%d.%m.%Y, %H:%M")
    r = await run.call(gwrite.calendar_patch, summary=name if name != run.a.name else None,
                       description=gwrite.calendar_description(run.a.mark, f"{text}\nUltima verificare: {when}"))
    if r is None:
        return False
    if r.code != gwrite.OK:
        await run.refused(r)
        return False
    if name != run.a.name:
        await gdoc.calendar_named(run.dk, name)
    _st(run.dk)["described"] = time.monotonic()
    return True


async def _clear(run: _Run) -> str | None:
    """Удалить у Google все наши события календаря врача — по списку Google, не по таблице: так уходят и
    те, о которых таблица не знает. Удалены все — таблица забыта и новая эпоха: «надгробие» прежнего id
    Google вставить не даст. None — календарь пуст; иначе — код прохода (хвост или отказ)."""
    r = await run.call(gwrite.events_ours, run.a.tag)
    if r is None:
        return _fail(run.dk, run.stop, run.wait)
    if r.code != gwrite.OK:
        await run.refused(r)
        return _fail(run.dk, run.stop or gdoc.A_OFFLINE, run.wait)
    items = [i for i in r.items if i["status"] != "cancelled"]
    n = 0
    for i, item in enumerate(items[:BURST]):
        if i and PAUSE_S:
            await asyncio.sleep(PAUSE_S)
        d = await run.call(gwrite.event_delete, item["id"])
        if d is None:
            break
        if d.code in (gwrite.OK, gwrite.GONE, gwrite.NOT_FOUND):
            n += 1
            continue
        await run.refused(d)
        if run.stop:
            break
    if run.stop:
        _st(run.dk)["pending"] = len(items) - n
        return _fail(run.dk, run.stop, run.wait)
    if n < len(items):
        return _ok(run.dk, len(items) - n, len(items) > BURST, run.skipped)
    await db.gdoc_sent_forget(run.dk)
    await gdoc.bump_epoch(run.dk)
    return None


async def _rebuild(run: _Run) -> str:
    """Картотеку восстановили из копии или календарь подхвачен заново: отправленному верить нельзя —
    календарь очищается, вставка — следующим проходом."""
    code = await _clear(run)
    if code is not None:
        return code
    _st(run.dk)["described"] = None
    return _ok(run.dk, 0, True, 0)


async def _finish(run: _Run, seq: int, left: int, more: bool) -> str:
    """Проход писал в Google — счётчик проходов вперёд, даже если дальше был отказ: строки таблицы уже
    говорят о записанном, и копия картотеки старше этого прохода должна это видеть."""
    if run.wrote:
        await gdoc.done(run.dk, seq)
    elif not run.stop:
        await gdoc.done(run.dk, seq, wrote=False)
    if run.stop:
        _st(run.dk)["pending"] = left
        return _fail(run.dk, run.stop, run.wait)
    return _ok(run.dk, left, more, run.skipped)


async def run_doctor(dk: str) -> str:
    """Проход одного врача под его замком: вход, «Deconectează» и уход ждут его конца."""
    async with gdoc.lock(dk):
        st = _st(dk)
        if time.monotonic() < st["quiet_until"]:
            return gdoc.A_RATE
        paused = await db.get_meta(META_PAUSED + dk) is not None
        due = paused or st["described"] is None or time.monotonic() - st["described"] >= DESCRIBE_EVERY
        a = await gdoc.access(dk, force=due)
        if a.code != gdoc.A_OK:
            return _fail(dk, a.code, a.retry_after)
        if len(a.tag) != gwrite.TAG_LEN:
            return _fail(dk, gdoc.A_NO_CLIENT)
        run = _Run(dk, a, await gdoc.level())
        await db.gdoc_sent_stale(dk, a.epoch, a.cal_id)
        if a.rebuild:
            return await _rebuild(run)
        if due:
            described = await _describe(run, DESC_ON)
            if run.stop:
                return await _finish(run, a.seq, 0, False)
            if paused and described:
                await db.del_meta(META_PAUSED + dk)
        now = datetime.now(timezone.utc)
        rows = await db.gdoc_desired(dk, eng.DOCTORS.get(dk), now - BACK, now + AHEAD)
        sent = {r["appt_id"]: r for r in await db.gdoc_sent_rows(dk)}
        acts = _plan(run, rows, sent, now)
        n = await _work(run, acts)
        await db.gdoc_sent_prune(dk, now - BACK)
        return await _finish(run, a.seq, len(acts) - n, len(acts) > BURST)


async def pause_doctor(dk: str) -> str:
    """Права нет: из календаря врача уходят ВСЕ наши события, и прошлые — стёртого после этого пациента
    сверка оттуда уже не убрала бы. Описание говорит, что обновление остановлено; связь и ключ хранятся.
    Метка паузы — только когда календарь пуст: оборванный уход доделывает следующий проход. Право
    вернулось — окно вставляется заново из базы новой эпохой."""
    async with gdoc.lock(dk):
        if await db.get_meta(META_PAUSED + dk) is not None:
            return R_PAUSED
        st = _st(dk)
        if time.monotonic() < st["quiet_until"]:
            return gdoc.A_RATE
        a = await gdoc.access(dk, leave=True, force=True)
        if a.code != gdoc.A_OK:
            return _fail(dk, a.code, a.retry_after)
        if len(a.tag) != gwrite.TAG_LEN:
            return _fail(dk, gdoc.A_NO_CLIENT)
        run = _Run(dk, a, await gdoc.level(), leaving=True)
        code = await _clear(run)
        if code is not None:
            return code
        await _describe(run, DESC_OFF)
        if run.stop:
            return _fail(dk, run.stop, run.wait)
        # описание не легло по нашей ошибке тела — календарь уже пуст, повтор очистки ничего не даст
        await db.set_meta(META_PAUSED + dk, _iso(datetime.now(timezone.utc)))
        st.update(pending=0, backoff=0, quiet_until=0.0)
        _error(st, "")
        return R_PAUSED


def _gone(dk: str) -> str:
    """Почему календарь врача пора удалить: '' — не пора."""
    if not eng.DOCTORS:
        return ""                         # справочник не прочитан — не повод удалять календари
    if dk not in eng.DOCTORS:
        return "removed"
    return "archived" if (eng.DOCTOR_META.get(dk) or {}).get("status") == "arhivat" else ""


async def retire_doctor(dk: str, why: str) -> str:
    """Врач в архиве или пропал из списка: календарь удаляется, ключ забывается. Google не ответил —
    ключ остаётся, следующий проход повторит: иначе календарь остался бы у Google навсегда."""
    async with gdoc.lock(dk):
        got = await gdoc.leave(dk, why, must_delete=True)
        if got == gdoc.L_KEPT:
            return _fail(dk, gdoc.A_OFFLINE)
        await db.gdoc_sent_forget(dk)
        await db.del_meta(META_PAUSED + dk)
    _state.pop(dk, None)
    return got


async def tick() -> str:
    """Проход по всем подключённым врачам. Право — на каждом, до сети, без кэша; архив и уход из
    списка права не спрашивают."""
    allowed = lic.feature_until(gdoc.SYNC_GATE) is not None
    out = R_OK if allowed else gdoc.A_GATE
    for dk in sorted(gdoc.linked()):
        why = _gone(dk)
        try:
            if why:
                code = await retire_doctor(dk, why)
            elif allowed:
                code = await run_doctor(dk)
            else:
                code = await pause_doctor(dk)
        except Exception as e:  # noqa: BLE001 — один врач не останавливает остальных
            log.warning("gdoc: %s sync failed: %r", dk, e)
            _fail(dk, gdoc.A_OFFLINE)
            continue
        if code == R_MORE:
            out = R_MORE
    return out


# ---------- для экрана и подключения ----------


def stats(dk: str) -> dict:
    """Через gdoc.sync_stats: последняя удачная сверка, ошибка с её первого раза, сколько ещё не
    доехало. До первого прохода после запуска — удача из файла связи."""
    st = _state.get(dk) or {}
    last = st.get("last_ok") or str((gdoc.linked().get(dk) or {}).get("last_ok") or "")
    return {"last_ok": last, "error": st.get("error", ""), "error_at": st.get("error_at", ""),
            "pending": int(st.get("pending", 0))}


def wake(dk: str | None = None) -> None:
    """После подключения врача и «Sincronizează acum»: проход сейчас; предел Google врача — заново."""
    if dk is not None and dk in _state:
        _state[dk].update(quiet_until=0.0, backoff=0)
    if _wake is not None:
        _wake.set()


# ---------- цикл ----------


def _tick_seconds() -> float:
    try:
        s = float(os.environ.get(TICK_ENV, "") or 0)
    except ValueError:
        s = 0
    return s if s > 0 else SYNC_MINUTES * 60.0 - LEAD_S


async def _loop() -> None:
    global _wake
    _wake = asyncio.Event()
    while True:
        started = time.monotonic()
        _wake.clear()
        try:
            code = await tick()
        except Exception as e:  # noqa: BLE001 — фон не имеет права умереть
            log.warning("gdoc: sync tick failed: %r", e)
            code = ""
        period = _tick_seconds()
        # хвост — после передышки; обычный проход — по расписанию от начала прошлого
        wait = min(CATCHUP_S, period) if code == R_MORE else max(1.0, period - (time.monotonic() - started))
        try:
            await asyncio.wait_for(_wake.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass


def poll_async() -> None:
    """Из старта main.py: сверка в фоне, старт её не ждёт; подключение будит её через дверь."""
    global _task
    gdoc.attach_sync(wake=wake, run=run_doctor, stats=stats)
    if _task is None:
        _task = asyncio.get_running_loop().create_task(_loop())
