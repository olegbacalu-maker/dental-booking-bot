"""Вкладка «Google Calendar»: правила.

Модуль стоит в журнале: переносу нужно правило записи журнала, а модуль соседа не импортирует."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

from ... import db
from ... import engine as eng
from ...core import gimport, ics
from ...core.auth import PERM_SETTINGS, can, request_user
from ...core.labels import STATUS_LABEL
from . import day as pday
from . import panel as ppanel
from . import routes as sroutes

log = logging.getLogger("gcal")

# Серия без конца иначе развернулась бы в тысячи строк.
HORIZON_DAYS = 365
KEEP_DAYS = 7
MAX_FILE = ics.MAX_FILE
TITLE_MAX = 300
BODY_MAX = 2000
COMMENT_MAX = 300
SWEEP_EVERY_S = 24 * 3600

KIND_ICS = "ics"

F_NEW, F_MOVED, F_SKIPPED, F_UNPARSED, F_CHANGED = "nou", "mutat", "omis", "nerecunoscut", "schimbat"
FILTERS = (F_NEW, F_MOVED, F_SKIPPED, F_UNPARSED, F_CHANGED)
FILTER_LABEL = {F_NEW: "De mutat", F_MOVED: "Mutate", F_SKIPPED: "Omise",
                F_UNPARSED: "Nerecunoscute", F_CHANGED: "Schimbate în Google"}

G_CANCELLED, G_GONE = "cancelled", "gone"
W_ALL_DAY, W_CANCELLED, W_GONE = "all_day", "cancelled", "gone"

_SERIES = "repetare pe care programul nu o poate desfășura"
WHY_TEXT = {
    W_ALL_DAY: "eveniment pe toată ziua",
    W_CANCELLED: "anulat în Google",
    W_GONE: "nu mai este în calendarul Google",
    gimport.CHECK_LONG: "durează peste 4 ore — verificați durata",
    gimport.CHECK_NONE: "fără durată în Google — alegeți durata",
    ics.RRULE_FREQ: _SERIES, ics.RRULE_PART: _SERIES, ics.RRULE_VALUE: _SERIES,
    ics.RRULE_MANY: _SERIES, ics.RDATE: _SERIES, ics.RANGE: _SERIES,
    ics.ALLDAY_SERIES: "serie de evenimente pe toată ziua",
    ics.SERIES_LONG: "serie prea lungă pentru a fi desfășurată",
    ics.UNKNOWN_TZ: "fus orar necunoscut",
    ics.BAD_DATE: "data nu a putut fi citită",
    ics.BAD_DURATION: "durata nu a putut fi citită",
    ics.BAD_LINE: "rând deteriorat în fișier",
    ics.NO_UID: "eveniment fără identificator",
    ics.NO_START: "eveniment fără dată de început",
    ics.DUP_KEY: "identificator repetat în fișier",
}
WHY_UNKNOWN = "eveniment care nu a putut fi citit"

HELP = (
    "În Google Calendar, pe calculator: „Calendarele mele” › treceți cu mouse-ul peste calendar › "
    "„Mai multe” (trei puncte) › „Setări și permiterea accesului”.",
    "Apăsați „Exportă calendarul” — se descarcă un fișier .ics (sau o arhivă .zip).",
    "Încărcați fișierul aici. Fișierul este citit de program pe acest calculator și nu este "
    "trimis nicăieri.",
)


def why_view(code: str) -> dict | None:
    if not code:
        return None
    return {"code": code, "text": WHY_TEXT.get(code, WHY_UNKNOWN)}


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(eng.TZ)


def _actor() -> str:
    return (request_user() or {}).get("name") or "recepție"


@dataclass(frozen=True)
class Item:
    key: str
    state: str
    why: str = ""
    start: datetime | None = None
    minutes: int = 0
    title: str = ""
    body: str = ""
    series: bool = False
    stamp: str = ""


def _body(d: gimport.Draft) -> str:
    people = ", ".join(n or m for n, m in d.attendees if n or m)
    parts = [d.description.strip(),
             f"Loc: {d.location.strip()}" if d.location.strip() else "",
             f"Invitați: {people}" if people else ""]
    return "\n".join(p for p in parts if p)[:BODY_MAX]


def _item(occ: ics.Occurrence, now: datetime, until: datetime) -> Item | str:
    """Строка для слияния либо слово, почему событие не хранится."""
    d = gimport.convert(occ, tz=eng.TZ, now=now, doctors=dict(eng.DOCTORS), until=until)
    base = dict(key=d.key, title=d.title.strip()[:TITLE_MAX], body=_body(d), series=d.series)
    if d.kind == gimport.OK:
        return Item(state=db.GCAL_NEW, why=d.check, start=d.src_start, minutes=d.src_minutes,
                    stamp=d.stamp, **base)
    if d.kind == gimport.SKIPPED:
        if d.why == gimport.BEYOND:
            return d.why
        start = d.src_start
        if start is None and occ.day is not None:
            start = datetime.combine(occ.day, time(0, 0), tzinfo=eng.TZ)
            # День ещё идёт — событие «на весь день» не прошлое.
            if occ.day < now.date():
                return gimport.PAST
        elif start is not None and start <= now:
            return gimport.PAST
        if start is not None and start > until:
            return gimport.BEYOND
        return Item(state=db.GCAL_SKIPPED, why=d.why, start=start, minutes=max(0, d.src_minutes),
                    stamp=gimport.stamp(start, d.src_minutes, d.title) if start else "", **base)
    start = d.src_start
    if d.series:
        # Дата неразвёрнутой серии — её начало, часто давнее.
        start = start if start is not None and start > now else None
    elif start is not None and start <= now:
        return gimport.PAST
    return Item(state=db.GCAL_UNPARSED, why=d.why or ics.NO_START, start=start,
                stamp=gimport.stamp(start, 0, d.title) if start else "", **base)


def read_file(raw: bytes, now: datetime) -> list:
    """Файл → календари с событиями. Без базы: зовётся в потоке."""
    until = now + timedelta(days=HORIZON_DAYS)
    out = []
    for cal in ics.read(raw, eng.TZ, max_bytes=MAX_FILE):
        name = (cal.name or cal.source or "").strip()[:120]
        if cal.refused:
            out.append({"name": name, "refused": cal.refused})
            continue
        items: dict = {}
        present: set = set()
        dropped = {gimport.PAST: 0, gimport.BEYOND: 0}
        for occ in ics.occurrences(cal, now, until):
            present.add(occ.key)
            it = _item(occ, now, until)
            if isinstance(it, str):
                dropped[it] += 1
                continue
            # Один ключ дважды в файле: годное событие сильнее своей тени.
            had = items.get(it.key)
            if had is None or (had.state == db.GCAL_UNPARSED and it.state != db.GCAL_UNPARSED):
                items[it.key] = it
        out.append({"name": name, "refused": "", "items": list(items.values()),
                    "present": present, "past": dropped[gimport.PAST],
                    "beyond": dropped[gimport.BEYOND]})
    return out


COUNTED = ("new", "updated", "same", "changed", "gone", "unparsed", "skipped", "all_day", "cancelled")


def _core(stamp: str) -> str:
    """Отпечаток без названия: у перенесённого события текст стёрт, и смену
    одного названия сравнить не с чем."""
    return stamp.rsplit("|", 1)[0] if stamp else ""


def changed(row: dict) -> bool:
    return row["state"] == db.GCAL_MOVED and (
        row["gstatus"] in (G_CANCELLED, G_GONE)
        or _core(row["stamp"]) != _core(row["stamp_moved"]))


async def absorb(kind: str, name: str, items: list, present: set, *,
                 actor: str, names: tuple = ()) -> dict:
    """Слить пришедший набор событий источника с лежащим. `present` — ключи всех событий,
    включая прошедшие: по ним «пропало» отличается от «прошло»."""
    sid = await db.gcal_source_put(kind, name, actor)
    have = await db.gcal_events_by_keys([it.key for it in items])
    now = db._utcnow_iso()
    count = dict.fromkeys(COUNTED, 0)
    inserts, updates, deletes = [], [], []
    renamed = set()
    for it in items:
        row = have.get(it.key)
        start = _utc(it.start) if it.start else None
        gstatus = G_CANCELLED if it.why == W_CANCELLED else ""
        count["unparsed"] += it.state == db.GCAL_UNPARSED
        count["skipped"] += it.state == db.GCAL_SKIPPED
        count["all_day"] += it.state == db.GCAL_SKIPPED and it.why == W_ALL_DAY
        count["cancelled"] += it.state == db.GCAL_SKIPPED and it.why == W_CANCELLED
        if row is None:
            inserts.append(dict(source_id=sid, ext_key=it.key, starts_at=start, minutes=it.minutes,
                                title=it.title, body=it.body, series=int(it.series),
                                gstatus=gstatus, state=it.state, why=it.why, stamp=it.stamp,
                                seen_at=now, created_at=now))
            count["new"] += it.state == db.GCAL_NEW
            continue
        if row["state"] == db.GCAL_ERASED:
            continue
        if row["source_id"] != sid:
            renamed.add(row["source_id"])
        if row["state"] == db.GCAL_MOVED:
            upd = dict(source_id=sid, seen_at=now, gstatus=gstatus)
            if it.stamp:
                upd.update(stamp=it.stamp, starts_at=start, minutes=it.minutes)
            was = changed(row)
            updates.append((row["id"], upd))
            count["changed"] += changed({**row, **upd}) and not was
            continue
        upd = dict(source_id=sid, starts_at=start, minutes=it.minutes, title=it.title,
                   body=it.body, series=int(it.series), gstatus=gstatus, why=it.why,
                   stamp=it.stamp, seen_at=now)
        if not row["by_hand"]:
            upd["state"] = it.state
        same = row["stamp"] == it.stamp and upd.get("state", row["state"]) == row["state"]
        count["same" if same else "updated"] += 1
        updates.append((row["id"], upd))
    # События пришли под новым именем, старого в загрузке нет: календарь переименован.
    olds = [r for r in await db.gcal_sources() if r["id"] in renamed and r["name"] not in names]
    for old in olds:
        await db.gcal_source_merge(old["id"], sid)
    for row in await db.gcal_source_future(sid):
        if row["ext_key"] in present or row["gstatus"] == G_GONE:
            continue
        if row["state"] == db.GCAL_UNPARSED:
            deletes.append(row["id"])
        elif row["state"] == db.GCAL_MOVED:
            updates.append((row["id"], dict(gstatus=G_GONE)))
            count["changed"] += not changed(row)
        else:
            upd = dict(gstatus=G_GONE, why=W_GONE)
            if not row["by_hand"]:
                upd["state"] = db.GCAL_SKIPPED
            updates.append((row["id"], upd))
        count["gone"] += 1
    await db.gcal_write(inserts, updates, deletes)
    await db.gcal_sources_prune()
    await db.gcal_menu_refresh()
    return count


async def load(raw: bytes) -> dict:
    """Загрузка файла; отказ файла целиком — `ics.Refused` наверх."""
    cals = await asyncio.to_thread(read_file, raw, _now())
    names = tuple(c["name"] for c in cals)
    total = dict.fromkeys((*COUNTED, "past", "beyond"), 0)
    refused = []
    actor = _actor()
    for cal in cals:
        if cal["refused"]:
            refused.append({"name": cal["name"], "code": cal["refused"]})
            continue
        got = await absorb(KIND_ICS, cal["name"], cal["items"], cal["present"],
                           actor=actor, names=names)
        for k, v in got.items():
            total[k] += v
        total["past"] += cal["past"]
        total["beyond"] += cal["beyond"]
    await db.log_clinic_event(
        "gcal", f"Google Calendar: fișier încărcat — {total['new']} evenimente noi, "
                f"{total['updated']} actualizate, {total['gone']} dispărute", actor)
    return {**total, "refused": refused}


async def sweep() -> int:
    """Текст непереносённого события старше срока стирается; ключ остаётся."""
    return await db.gcal_expire(_utc(_now() - timedelta(days=KEEP_DAYS)))


async def startup() -> None:
    await sweep()
    await db.gcal_menu_refresh()


async def _loop() -> None:
    while True:
        await asyncio.sleep(SWEEP_EVERY_S)
        try:
            await sweep()
        except Exception as e:  # noqa: BLE001 — цикл уборки живёт дольше одной ошибки
            log.warning("уборка текста событий календаря не прошла: %r", e)


_tasks: list = []


def sweep_async() -> None:
    """Программа у клиники работает неделями: одного прохода на старте мало."""
    if not _tasks:
        _tasks.append(asyncio.get_running_loop().create_task(_loop()))


def _local(dt: datetime) -> datetime:
    return dt.astimezone(eng.TZ)


def _span(start: datetime, minutes: int) -> str:
    end = start + timedelta(minutes=minutes)
    return f"{_local(start):%H:%M}–{_local(end):%H:%M}"


class _People:

    def __init__(self, patients: list):
        self.by_phone: dict = {}
        self.by_name: dict = {}
        for p in patients:
            brief = {"id": p["id"], "name": p["name"] or "", "phone": p["phone"] or ""}
            for k in db.gcal_phone_keys(p["phone"] or ""):
                self.by_phone.setdefault(k, []).append(brief)
                # Чужой номер разбор отдаёт с плюсом, в фише он бывает без.
                self.by_phone.setdefault("+" + k.lstrip("+"), []).append(brief)
            words = frozenset(gimport.fold(p["name"] or "").split())
            if len(words) >= 2:
                self.by_name.setdefault(words, []).append(brief)

    def find(self, phones: tuple, name: str) -> list:
        out, seen = [], set()
        for ph in phones:
            for p in self.by_phone.get(ph, ()):
                if p["id"] not in seen:
                    seen.add(p["id"])
                    out.append(p)
        if not out and not phones:
            out = list(self.by_name.get(frozenset(gimport.fold(name).split()), ()))
        return out


def _hint(row: dict, start: datetime | None, people: _People, journal: dict) -> dict:
    doctors = dict(eng.DOCTORS)
    text = row["title"] + "\n" + row["body"]
    phones = gimport.phones(text)
    name = gimport.patient_guess(row["title"], doctors)
    dk, _hits = gimport.doctor_hint(row["title"], doctors)
    patients = people.find(phones, name)
    exists = None
    if start is not None:
        ids = {p["id"] for p in patients}
        folded = frozenset(gimport.fold(name).split())
        for a in journal.get(_utc(start), ()):
            if a["patient_id"] in ids or (
                    not ids and len(folded) >= 2
                    and frozenset(gimport.fold(a["name"] or "").split()) == folded):
                exists = {"appt_id": a["id"],
                          "text": f"{a['name']} · {a['doctor']} · {_local(a['starts_at']):%d.%m %H:%M}"}
                break
    return {"phone": phones[0] if phones else "", "phones": list(phones), "name": name,
            "doctor": ({"key": dk, "name": doctors[dk]} if dk else None),
            "patients": patients[:5], "exists": exists}


def _preset(row: dict, start: datetime | None, minutes: int, hint: dict, service: str) -> dict:
    """Заполнение окна записи — в том виде, в каком окно шлёт журналу."""
    dk = (hint["doctor"] or {}).get("key", "")
    if dk and not eng.DOCTOR_META.get(dk, {}).get("active", True):
        dk = ""
    phone = hint["phone"]
    if phone and not phone.startswith("+"):
        phone = "0" + phone
    loc = _local(start) if start else None
    return {"date": loc.date().isoformat() if loc else "",
            "time": f"{loc:%H:%M}" if loc and row["why"] != W_ALL_DAY else "",
            "duration": str(minutes) if minutes else "",
            "doctor": dk, "service": service if service in eng.SERVICES else "",
            "name": hint["name"], "phone": phone, "nophone": not phone}


def _view(row: dict, people: _People, journal: dict, service: str) -> dict:
    src = row["starts_at"]
    moved = row["state"] == db.GCAL_MOVED
    start, minutes, rounded = src, int(row["minutes"] or 0), None
    if src is not None and row["why"] != W_ALL_DAY and row["state"] != db.GCAL_UNPARSED:
        begin, minutes = gimport.round_slot(src, int(row["minutes"] or 0))
        start = begin
        if _utc(begin) != _utc(src) or minutes != int(row["minutes"] or 0) and row["minutes"] > 0:
            rounded = {"from": _span(src, int(row["minutes"] or 0)), "to": _span(begin, minutes)}
    loc = _local(src) if src else None
    out = {"id": row["id"],
           "when": loc.strftime("%Y-%m-%dT%H:%M") if loc else "",
           "date": loc.date().isoformat() if loc else "",
           "time": f"{loc:%H:%M}" if loc and row["why"] != W_ALL_DAY else "",
           "minutes": int(row["minutes"] or 0),
           "title": row["title"], "body": row["body"], "series": bool(row["series"]),
           "state": row["state"], "changed": changed(row), "gstatus": row["gstatus"],
           "why": why_view(row["why"]), "round": rounded,
           "hint": None, "preset": None, "appt": None}
    if moved:
        if row["appt_when"]:
            at = _local(db._parse_dt(row["appt_when"]))
            out["appt"] = {"id": row["appt_id"], "pid": row["appt_pid"],
                           "patient": row["appt_patient"] or "", "doctor": row["appt_doctor"] or "",
                           "when": at.strftime("%Y-%m-%dT%H:%M"),
                           "minutes": int(row["appt_minutes"] or 60),
                           "status": {"code": row["appt_status"],
                                      "text": STATUS_LABEL.get(row["appt_status"], row["appt_status"])},
                           "day_href": f"/admin/all?date={at.date().isoformat()}"}
        if out["changed"]:
            out["why"] = why_view(W_CANCELLED if row["gstatus"] == G_CANCELLED
                                  else W_GONE if row["gstatus"] == G_GONE else "")
    else:
        hint = _hint(row, start, people, journal)
        out["hint"] = hint
        out["preset"] = _preset(row, start, minutes, hint, service)
    out["can"] = {"move": not moved, "link": not moved,
                  "skip": row["state"] in (db.GCAL_NEW, db.GCAL_UNPARSED),
                  "back": row["state"] == db.GCAL_SKIPPED}
    return out


def _bucket(row: dict) -> tuple:
    if row["state"] == db.GCAL_MOVED:
        return (F_MOVED, F_CHANGED) if changed(row) else (F_MOVED,)
    return (row["state"],)


def _matches(row: dict, needle: str) -> bool:
    hay = " ".join((row["title"], row["body"], row.get("appt_patient") or ""))
    return needle in gimport.fold(hay)


def _source_view(src: dict) -> dict:
    try:
        settings = json.loads(src["settings"] or "{}")
    except ValueError:
        settings = {}
    at = db._parse_dt(src["loaded_at"]).astimezone(eng.TZ) if src["loaded_at"] else None
    return {"id": src["id"], "kind": src["kind"], "name": src["name"],
            "loaded_at": at.strftime("%d.%m.%Y %H:%M") if at else "",
            "loaded_by": src["loaded_by"],
            "service": settings.get("service", "") if settings.get("service") in eng.SERVICES else ""}


def _form() -> dict:
    """Часы дня окно записи спрашивает у журнала само, по выбранной дате."""
    return {"doctors": [{"key": k, "name": n} for k, n in eng.DOCTORS.items()
                        if eng.DOCTOR_META.get(k, {}).get("active", True)],
            "services": [{"key": k, "label": v["ro"], "minutes": eng.svc_duration(k),
                          "docs": list(v.get("docs") or [])} for k, v in eng.SERVICES.items()],
            "sms": pday.sms_box()}


PAGE = "/admin/google"


def _iso_day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def _month(days: set, f: str, q: str, day: date | None, month: date | None) -> dict:
    """Месяц вкладки — построителем журнала; ссылка дня оставляет вкладку и поиск."""
    today = _now().date()
    cal = ppanel.minical(day or month or today, today, pday.RO_MONTHS, base=PAGE, busy=days)
    tail = "".join(f"&{k}={quote(v)}" for k, v in (("f", f), ("q", q)) if v)
    for week in cal["weeks"]:
        for c in week:
            c["href"] += tail
            c["selected"] = day is not None and c["date"] == day.isoformat()
    for k in ("prev", "next"):
        cal[k]["href"] = f"{PAGE}?month={cal[k]['date']}{tail}"
    return cal


async def listing(f: str = "", q: str = "", day: str = "", month: str = "") -> dict:
    """Вкладка данными; `day` оставляет в списке один день, счётчики вкладок от него не зависят."""
    await sweep()
    f = f if f in FILTERS else F_NEW
    needle = gimport.fold(q.strip())[:80]
    rows = await db.gcal_rows()
    if needle:
        rows = [r for r in rows if _matches(r, needle)]
    counts = dict.fromkeys(FILTERS, 0)
    shown = []
    for r in rows:
        buckets = _bucket(r)
        for b in buckets:
            counts[b] += 1
        if f in buckets:
            shown.append(r)
    sources = [_source_view(s) for s in await db.gcal_sources()]
    service = sources[0]["service"] if sources else ""
    people, journal = _People([]), {}
    todo = [r for r in shown if r["state"] != db.GCAL_MOVED]
    if todo:
        people = _People(await db.gcal_patients())
        dated = [r["starts_at"] for r in todo if r["starts_at"] is not None]
        if dated:
            pad = timedelta(minutes=gimport.STEP)
            for a in await db.gcal_journal(_utc(min(dated) - pad), _utc(max(dated) + pad)):
                journal.setdefault(_utc(a["starts_at"]), []).append(a)
    only = _iso_day(day)
    days: dict = {}
    undated = []
    for r in shown:
        v = _view(r, people, journal, service)
        if v["date"]:
            days.setdefault(v["date"], []).append(v)
        else:
            undated.append(v)
    cal = _month({date.fromisoformat(d) for d in days}, f, q.strip()[:80], only, _iso_day(month))
    if only is not None:
        days = {d: v for d, v in days.items() if d == only.isoformat()}
        undated = []
        shown = [x for v in days.values() for x in v]
    me = request_user()
    return {"source": sources[0] if sources else None, "sources": sources,
            "f": f, "q": q.strip()[:80], "counts": counts,
            "date": only.isoformat() if only else "", "minical": cal,
            "filters": [{"key": k, "label": FILTER_LABEL[k], "n": counts[k]} for k in FILTERS
                        if k != F_CHANGED or counts[k]],
            "days": [{"date": d, "rows": days[d]} for d in sorted(days)],
            "undated": undated, "total": len(shown),
            "form": _form(), "help": list(HELP),
            "keep_days": KEEP_DAYS, "horizon_days": HORIZON_DAYS,
            "max_mb": MAX_FILE // (1024 * 1024),
            "can": {"clear": can(me, PERM_SETTINGS) or me is None}}


OK_CODES = frozenset({"ok", "ok_other", "ok_past", "ok_past_done", "room_busy"})


def _s(body: dict, key: str) -> str:
    v = body.get(key)
    return "" if v is None else str(v)


def _when(body: dict) -> datetime | None:
    try:
        d = date.fromisoformat(_s(body, "date"))
        hh, mm = _s(body, "time").split(":")
        return datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=eng.TZ)
    except (ValueError, AttributeError):
        return None


async def _journal_add(body: dict, pid: int | None) -> tuple:
    """Шов с журналом: (код окна записи, номер созданной записи). Ветка «фиша
    выбрана» своя: правило журнала принимает имя и телефон, не номер фиши."""
    sms = body.get("sms")
    sms = sms if isinstance(sms, bool) else None
    dk, adur, room = _s(body, "doctor"), _s(body, "duration"), _s(body, "room")
    if pid is None:
        return await sroutes._book_appt(
            _s(body, "date"), _s(body, "time"), dk, _s(body, "service"), _s(body, "name"),
            _s(body, "phone"), "1" if body.get("nophone") else "", _s(body, "birth"),
            sms, body.get("done") is True, adur, room)
    dt = _when(body)
    doctor, svc = eng.DOCTORS.get(dk), eng.SERVICES.get(_s(body, "service"))
    if dt is None or not doctor or not svc:
        return "bad", None
    dur = eng.svc_duration(_s(body, "service"))
    if adur:
        if not adur.isdigit() or not eng.dur_ok(int(adur)):
            return "bad_dur", None
        dur = int(adur)
    if code := eng.place_refusal(dk, dt, dur):
        return code, None
    if room and room not in eng.doctor_rooms(dk):
        return "bad_room", None
    plan = eng.room_plan(dk)
    r = await db.add_visit_for_patient(pid, svc["ro"], doctor, dt, doctor_id=dk,
                                       service_id=_s(body, "service"), duration_min=dur,
                                       rooms=plan, room=room or None)
    if not isinstance(r, int):
        return ("dup" if r == "dup" else "conflict"), None
    if adur:
        await db.gcal_duration_by_hand(r)
    await sroutes._apply_sms(r, sms)
    if eng.is_past_day(dt.date()):
        return "ok_past", r
    return ("room_busy" if await db.appt_room_busy(r, plan) else "ok"), r


def _comment(row: dict) -> str:
    """Что от события остаётся в записи: название, исходные часы (если округлены), начало описания."""
    text = "Google: " + (row["title"] or "(fără titlu)")
    src = row["starts_at"]
    if src is not None and row["why"] != W_ALL_DAY and row["minutes"] > 0:
        begin, minutes = gimport.round_slot(src, int(row["minutes"]))
        if _utc(begin) != _utc(src) or minutes != int(row["minutes"]):
            text += f" ({_span(src, int(row['minutes']))})"
    first = next((ln.strip() for ln in row["body"].splitlines() if ln.strip()), "")
    if first:
        text += " — " + first
    return text[:COMMENT_MAX]


async def move(eid: int, body: dict) -> tuple:
    """Событие → запись журнала: (код окна записи, номер записи или None)."""
    row = await db.gcal_event(eid)
    if row is None or row["state"] == db.GCAL_ERASED:
        return "gc_gone", None
    if row["state"] == db.GCAL_MOVED:
        return "gc_moved", None
    pid = body.get("pid")
    if pid is not None:
        if not isinstance(pid, int) or isinstance(pid, bool) or not await db.get_patient(pid):
            return "gc_patient", None
    code, appt_id = await _journal_add(body, pid)
    if code not in OK_CODES or appt_id is None:
        return code, None
    await db.set_comment(appt_id, _comment(row))
    await db.gcal_mark_moved(eid, appt_id, _actor())
    return code, appt_id


async def link(eid: int, appt_id) -> str:
    """Связать со стоящей записью, второй не создавая; её комментарий не трогается."""
    row = await db.gcal_event(eid)
    if row is None or row["state"] == db.GCAL_ERASED:
        return "gc_gone"
    if row["state"] == db.GCAL_MOVED:
        return "gc_moved"
    if not isinstance(appt_id, int) or isinstance(appt_id, bool):
        return "gc_appt"
    a = await db.appointment_brief(appt_id)
    if a is None or a["source"] == "note" or a["patient_id"] is None:
        return "gc_appt"
    if not (a["comment"] or "").strip():
        await db.set_comment(appt_id, _comment(row))
    await db.gcal_mark_moved(eid, appt_id, _actor())
    return "gc_linked"


async def skip(eid: int, on: bool) -> str:
    """«Nu muta» и обратно: не разобранное возвращается не разобранным."""
    row = await db.gcal_event(eid)
    if row is None or row["state"] == db.GCAL_ERASED:
        return "gc_gone"
    if row["state"] == db.GCAL_MOVED:
        return "gc_moved"
    if on:
        await db.gcal_set_state(eid, db.GCAL_SKIPPED, (db.GCAL_NEW, db.GCAL_UNPARSED))
        return "gc_skipped"
    if not row["title"] and not row["body"]:
        return "gc_no_text"
    back = db.GCAL_UNPARSED if row["why"] in ics.PROBLEMS else db.GCAL_NEW
    await db.gcal_set_state(eid, back, (db.GCAL_SKIPPED,))
    return "gc_back"


async def clear() -> str:
    n = await db.gcal_clear()
    await db.log_clinic_event(
        "gcal", f"Google Calendar: toate evenimentele au fost șterse ({n} nemutate)", _actor())
    return "gc_cleared"


async def set_service(service: str) -> str:
    if service and service not in eng.SERVICES:
        return "gc_bad"
    sources = await db.gcal_sources()
    if not sources:
        return "gc_gone"
    await db.gcal_source_settings(sources[0]["id"], json.dumps({"service": service}))
    return "gc_set"
