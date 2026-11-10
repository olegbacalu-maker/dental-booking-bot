"""«Registre» (10.11.2026): правила санитарных регистров 257/e, 502/e, 501/e.

Бланки — образцы ANSP: 257/e «controlul lucrului sterilizatoarelor» (Ordin MS
828/2011), 502/e «curățenia generală» и 501/e «lămpi bactericide» (Ordin MS
630/2016); электронный регистр с подписью ответственного и временем разрешает
HG 4/2026 п.141. Разведка и колонки — side-session-notes/2026-11-10/san-registers.md.

Решения Олега 10.11 (вариант B): пишут ВСЕ вошедшие; подпись строки — вошедший
и время ПРОГРАММЫ (клиент их не присылает и не может подменить); исправление —
новой строкой с причиной, старая остаётся зачёркнутой; удаляет только директор
(`PERM_SETTINGS`), мягко; «a supervizat» — другой человек своим входом; ресурс
лампы считает программа.
Здесь — проверка того, что пришло, и сборка модели экрана; запись — `db/registre.py`.
⚠️ Ошибка ввода — `RegError(code, field)`: код уходит в `msg_json` (MSG_BANNER).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone

from .. import db
from .. import engine as eng

REGS = ("257", "502", "501")
# вид → регистр (подпись вида в каталоге — клиента)
KINDS = ("ster", "lamp", "room", "solution", "article", "pack", "norms")
TESTS = ("ok", "fail")
BIO = ("wait", "ok", "fail")
# условия облучения 501/e: ключ API → слово бланка
COND = {"fara": "fără persoane", "prezenta": "în prezența persoanelor"}
WHY_MAX = 200
NAME_MAX = 120
QTY_MAX = 999
ARTS_MAX = 20
# лампа «на исходе»: остаток ≤ 2 % ресурса, но не меньше 50 часов
LOW_SHARE, LOW_MIN = 0.02, 50


class RegError(ValueError):
    def __init__(self, code: str, field: str = "", status: int = 422):
        super().__init__(code)
        self.code, self.field, self.status = code, field, status


# ---------- время ----------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return datetime.now(eng.TZ).date()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(v) -> datetime | None:
    """Момент из базы: строка UTC ISO или уже `datetime` (`_DT_COLS`)."""
    if not v:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        dt = datetime.fromisoformat(str(v))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _loc(v) -> datetime | None:
    dt = _parse(v)
    return dt.astimezone(eng.TZ) if dt else None


def dmy(d) -> str:
    """Голая дата ISO или date → «dd.mm.yyyy»; пусто — пусто."""
    if not d:
        return ""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return d.strftime("%d.%m.%Y")


def hm(v) -> str:
    dt = _loc(v)
    return dt.strftime("%H:%M") if dt else ""


def stamp(v) -> str:
    dt = _loc(v)
    return dt.strftime("%d.%m.%Y %H:%M") if dt else ""


def day_bounds(d1: date, d2: date) -> tuple[str, str]:
    """[начало d1, начало d2) по часам клиники → UTC ISO для моментов."""
    a = datetime.combine(d1, time(0), tzinfo=eng.TZ)
    b = datetime.combine(d2, time(0), tzinfo=eng.TZ)
    return _iso(a), _iso(b)


def month_of(s: str | None) -> date:
    """«YYYY-MM» → первое число месяца; пусто или мусор — текущий месяц."""
    try:
        y, m = (int(x) for x in (s or "").split("-")[:2])
        return date(y, m, 1)
    except (ValueError, TypeError):
        t = today()
        return date(t.year, t.month, 1)


def next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def period(month: str | None = None, frm: str | None = None, to: str | None = None) -> tuple[date, date]:
    """Период [d1, d2): `from`/`to` (включительно) или месяц."""
    try:
        if frm and to:
            d1, d2 = date.fromisoformat(frm), date.fromisoformat(to) + timedelta(days=1)
            if d1 < d2 and (d2 - d1).days <= 400:
                return d1, d2
    except ValueError:
        pass
    m = month_of(month)
    return m, next_month(m)


# ---------- проверка ввода ----------

def _text(v, field: str, need: bool = True, cap: int = NAME_MAX) -> str:
    s = " ".join(str(v or "").split())[:cap]
    if need and not s:
        raise RegError("bad_san", field)
    return s


def _int(v, field: str, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise RegError("bad_san", field) from None
    if not lo <= n <= hi:
        raise RegError("bad_san", field)
    return n


def _choice(v, allowed, field: str, empty_ok: bool = True) -> str:
    s = str(v or "")
    if s in ("", "none") and empty_ok:
        return ""
    if s not in allowed:
        raise RegError("bad_san", field)
    return s


def _why(v) -> str:
    s = _text(v, "why", need=False, cap=WHY_MAX)
    if not s:
        raise RegError("san_why", "why")
    return s


def _arts(v, packs: list[str]) -> list[dict]:
    if not isinstance(v, list) or not v or len(v) > ARTS_MAX:
        raise RegError("bad_san", "arts")
    out = []
    for a in v:
        if not isinstance(a, dict):
            raise RegError("bad_san", "arts")
        out.append({"name": _text(a.get("name"), "arts"),
                    "qty": _int(a.get("qty"), "arts", 1, QTY_MAX),
                    "pack": _text(a.get("pack"), "arts", need=False, cap=40)})
    return out


def _hm(v, field: str) -> time:
    try:
        h, m = (int(x) for x in str(v).split(":"))
        return time(h, m)
    except (ValueError, TypeError):
        raise RegError("bad_san", field) from None


# ---------- каталог ----------

def clean_item(kind: str, b: dict) -> dict:
    """Строка каталога из тела запроса; `data` — только известные ключи вида."""
    if kind not in KINDS:
        raise RegError("bad_san", "kind")
    item = {"kind": kind, "active": bool(b.get("active", True)), "sort": 0, "data": {}}
    if b.get("id"):
        item["id"] = _int(b.get("id"), "id", 1, 10**9)
    d = b.get("data") if isinstance(b.get("data"), dict) else {}
    if kind == "norms":
        item.update(name="norms", data={"text": str(d.get("text") or "")[:2000]})
        return item
    item["name"] = _text(b.get("name"), "name")
    item["nr"] = _text(b.get("nr"), "nr", need=False, cap=40)
    item["room"] = _text(b.get("room"), "room", need=False)
    if kind == "ster":
        progs = d.get("programs") if isinstance(d.get("programs"), list) else []
        clean = []
        for p in progs[:12]:
            if not isinstance(p, dict) or not str(p.get("label") or "").strip():
                continue
            clean.append({"label": _text(p.get("label"), "programs", cap=60),
                          "temp": _text(p.get("temp"), "programs", need=False, cap=10),
                          "pressure": _text(p.get("pressure"), "programs", need=False, cap=10),
                          "min": _int(p.get("min") or 0, "programs", 0, 600)})
        if not clean:
            raise RegError("bad_san", "programs")
        item["data"] = {"type": _choice(d.get("type"), ("abur", "aer"), "type", empty_ok=False),
                        "programs": clean}
    elif kind == "lamp":
        since = str(d.get("since") or "")
        try:
            date.fromisoformat(since)
        except ValueError:
            raise RegError("bad_san", "since") from None
        item["data"] = {"m3": _int(d.get("m3") or 0, "m3", 0, 10000),
                        "hours": _int(d.get("hours"), "hours", 1, 100000),
                        "base": _int(d.get("base") or 0, "base", 0, 100000),
                        "since": since, "screened": bool(d.get("screened")),
                        "changes": d.get("changes") if isinstance(d.get("changes"), list) else []}
    elif kind == "room":
        item["data"] = {"every": _int(d.get("every") or 7, "every", 1, 365)}
    return item


# Стартовый каталог (2.14.1, канарейка 2.14.0): без предметов окно «Ciclu nou»
# было тупиком — выбрать нечего, «Pornește ciclul» серая. Подставляется ОДИН
# раз на вид: ключ `schema_meta` говорит «каталог этого вида уже заводили», и
# клиника, выключившая все стартовые строки, второй раз их не получит
# (отсутствие ≠ «стереть», 08-16). Решает КЛЮЧ, а не пустота списка; у вида,
# где клиника успела завести свои строки, старт не подкладывается, ключ ставится.
STARTER = {
    "article": ("Instrumentar stomatologic", "Freze și pile", "Piese de mână", "Tăvițe și pense",
                "Material textil"),
    "pack": ("Pungă", "Casetă", "Bix"),
}
STARTER_KEY = "san_starter_{kind}"


async def ensure_starter() -> None:
    for kind, names in STARTER.items():
        key = STARTER_KEY.format(kind=kind)
        if await db.get_meta(key) is not None:
            continue
        if not await db.san_items(kind):
            for i, name in enumerate(names):
                await db.san_item_save({"kind": kind, "name": name, "active": True, "sort": i, "data": {}})
        await db.set_meta(key, today().isoformat())


async def catalog() -> dict:
    """Каталог по видам (активные и архивные) + текст нормативов."""
    await ensure_starter()
    rows = await db.san_items()
    out = {k: [] for k in KINDS if k != "norms"}
    norms = {"id": None, "text": ""}
    for r in rows:
        if r["kind"] == "norms":
            norms = {"id": r["id"], "text": r["data"].get("text", "")}
        elif r["kind"] in out:
            out[r["kind"]].append(_item_out(r))
    for lamp in out["lamp"]:
        lamp.update(await lamp_state(lamp))
    return {"items": out, "norms": norms}


def _item_out(r: dict) -> dict:
    return {"id": r["id"], "kind": r["kind"], "name": r["name"], "nr": r.get("nr") or "",
            "room": r.get("room") or "", "data": r.get("data") or {}, "active": bool(r.get("active"))}


def label(item: dict) -> str:
    """Снимок имени оборудования в строку журнала: «Melag 23 B+ nr. 23-11845»."""
    return f"{item['name']} nr. {item['nr']}" if item.get("nr") else item["name"]


async def lamp_state(lamp: dict) -> dict:
    """Ресурс лампы: часы до замены (база каталога + закрытые сеансы с даты
    ввода), остаток, «на исходе»."""
    d = lamp.get("data") or {}
    hours = int(d.get("hours") or 0)
    since = d.get("since") or "1970-01-01"
    try:
        since_iso, _ = day_bounds(date.fromisoformat(since), date.fromisoformat(since))
    except ValueError:
        since_iso = "1970-01-01T00:00:00+00:00"
    minutes = await db.san_lamp_minutes(int(lamp["id"]), since_iso)
    used = int(d.get("base") or 0) + minutes // 60
    rest = max(hours - used, 0)
    return {"used": used, "rest": rest, "low": rest <= max(LOW_MIN, math.ceil(hours * LOW_SHARE))}


async def _active(kind: str, item_id) -> dict:
    try:
        it = await db.san_item(int(item_id))
    except (TypeError, ValueError):
        it = None
    if not it or it["kind"] != kind or not it.get("active"):
        raise RegError("bad_san", {"ster": "ster_id", "lamp": "lamp_id", "room": "room_id"}[kind])
    return it


async def room_next(room: dict) -> date:
    """Плановый день генеральной уборки: последняя + частота; не было — сегодня."""
    last = await db.san_last_clean(int(room["id"]))
    every = int((room.get("data") or {}).get("every") or 7)
    return date.fromisoformat(last) + timedelta(days=every) if last else today()


# ---------- записи ----------

def _who(user: dict | None) -> tuple[str, str]:
    u = user or {}
    return (u.get("name") or "recepție"), str(u.get("id") or "")


async def start_cycle(user: dict | None, b: dict) -> int:
    ster = await _active("ster", b.get("ster_id"))
    progs = (ster.get("data") or {}).get("programs") or []
    p = _int(b.get("program", 0), "program", 0, max(len(progs) - 1, 0))
    prog = progs[p] if progs else {"label": "", "temp": "", "pressure": ""}
    arts = _arts(b.get("arts"), [])
    if any(int(r["ster_id"] or 0) == ster["id"] for r in await db.san_open("257")):
        raise RegError("san_busy", "ster_id", 409)
    name, uid = _who(user)
    return await db.san_insert("257", {
        "ster_id": ster["id"], "ster": label(ster), "program": prog["label"],
        "pressure": _text(b.get("pressure", prog.get("pressure")), "pressure", need=False, cap=10),
        "temp": _text(b.get("temp", prog.get("temp")), "temp", need=False, cap=10),
        "arts": arts, "started_at": _iso(now_utc()), "actor": name, "actor_id": uid})


async def finish_cycle(user: dict | None, row_id: int, b: dict) -> None:
    vals = {"chem": _choice(b.get("chem"), TESTS, "chem"), "term": _choice(b.get("term"), TESTS, "term"),
            "bio": _choice(b.get("bio"), BIO, "bio"), "ended_at": _iso(now_utc()),
            "end_actor": _who(user)[0]}
    if not await db.san_close("257", row_id, "ended_at", vals):
        raise RegError("san_closed", "", 409)


async def bio_result(user: dict | None, row_id: int, b: dict) -> None:
    bio = _choice(b.get("bio"), ("ok", "fail"), "bio", empty_ok=False)
    row = await db.san_row("257", row_id)
    if not row or row.get("deleted_at") or row.get("bio") != "wait":
        raise RegError("san_closed", "", 409)
    if not await db.san_close("257", row_id, "bio_at", {"bio": bio, "bio_actor": _who(user)[0],
                                                         "bio_at": _iso(now_utc())}):
        raise RegError("san_closed", "", 409)


async def add_clean(user: dict | None, b: dict) -> int:
    room = await _active("room", b.get("room_id"))
    plan = await room_next(room)
    name, uid = _who(user)
    return await db.san_insert("502", {
        "room_id": room["id"], "room": room["name"], "plan_date": plan.isoformat(),
        "done_date": today().isoformat(), "solution": _text(b.get("solution"), "solution"),
        "actor": name, "actor_id": uid})


async def supervise(user: dict | None, row_id: int) -> None:
    row = await db.san_row("502", row_id)
    if not row or row.get("deleted_at"):
        raise RegError("san_gone", "", 404)
    name, uid = _who(user)
    if uid and uid == (row.get("actor_id") or ""):
        raise RegError("san_self_check", "", 409)
    if not await db.san_close("502", row_id, "sup_at", {"sup_actor": name, "sup_id": uid,
                                                         "sup_at": _iso(now_utc())}):
        raise RegError("san_closed", "", 409)


async def uv_on(user: dict | None, b: dict) -> int:
    lamp = await _active("lamp", b.get("lamp_id"))
    cond = _choice(b.get("cond"), tuple(COND), "cond", empty_ok=False)
    if cond == "prezenta" and not (lamp.get("data") or {}).get("screened"):
        # лампа без экрана при людях — запрещено самим режимом облучения
        raise RegError("san_uv_people", "cond", 409)
    if any(int(r["lamp_id"] or 0) == lamp["id"] for r in await db.san_open("501")):
        raise RegError("san_uv_on", "lamp_id", 409)
    name, uid = _who(user)
    return await db.san_insert("501", {
        "lamp_id": lamp["id"], "lamp": label(lamp), "room": lamp.get("room") or "",
        "cond": COND[cond], "on_at": _iso(now_utc()), "actor": name, "actor_id": uid})


async def uv_off(user: dict | None, row_id: int) -> None:
    row = await db.san_row("501", row_id)
    if not row or row.get("deleted_at") or row.get("off_at"):
        raise RegError("san_closed", "", 409)
    now = now_utc()
    minutes = max(1, math.ceil((now - _parse(row["on_at"])).total_seconds() / 60))
    rest = None
    lamp = await db.san_item(int(row["lamp_id"] or 0))
    if lamp:
        # остаток ПОСЛЕ этого сеанса: тот же счёт, что у `lamp_state`, плюс он
        d = lamp.get("data") or {}
        since_iso, _ = day_bounds(*(date.fromisoformat(d.get("since") or "1970-01-01"),) * 2)
        done = await db.san_lamp_minutes(int(lamp["id"]), since_iso)
        rest = max(int(d.get("hours") or 0) - int(d.get("base") or 0) - (done + minutes) // 60, 0)
    if not await db.san_close("501", row_id, "off_at", {"off_at": _iso(now), "minutes": minutes,
                                                        "rest_hours": rest, "off_actor": _who(user)[0]}):
        raise RegError("san_closed", "", 409)


async def fix(reg: str, user: dict | None, row_id: int, b: dict) -> int:
    """Исправление — НОВАЯ строка с `fixes` = id исправленной и причиной.
    Исправляют только закрытую, неудалённую и ещё не исправленную строку."""
    if reg not in REGS:
        raise RegError("san_gone", "", 404)
    old = await db.san_row(reg, row_id)
    if not old or old.get("deleted_at"):
        raise RegError("san_gone", "", 404)
    if row_id in await db.san_fixed_ids(reg):
        raise RegError("san_fixed", "", 409)
    why = _why(b.get("why"))
    name, uid = _who(user)
    base = {"fixes": row_id, "why": why, "actor": name, "actor_id": uid}
    if reg == "257":
        if not old.get("ended_at"):
            raise RegError("san_open", "", 409)
        start, end = _loc(old["started_at"]), _loc(old["ended_at"])
        s_t = _hm(b.get("start", start.strftime("%H:%M")), "start")
        e_t = _hm(b.get("end", end.strftime("%H:%M")), "end")
        s_dt = datetime.combine(start.date(), s_t, tzinfo=eng.TZ)
        e_dt = datetime.combine(start.date(), e_t, tzinfo=eng.TZ)
        if e_dt < s_dt:
            e_dt += timedelta(days=1)
        return await db.san_insert("257", {
            **base, "ster_id": old["ster_id"], "ster": old["ster"],
            "program": _text(b.get("program", old["program"]), "program", need=False, cap=60),
            "pressure": _text(b.get("pressure", old["pressure"]), "pressure", need=False, cap=10),
            "temp": _text(b.get("temp", old["temp"]), "temp", need=False, cap=10),
            "arts": _arts(b["arts"], []) if "arts" in b else _json_list(old["arts"]),
            "started_at": _iso(s_dt), "ended_at": _iso(e_dt), "end_actor": name,
            "chem": _choice(b.get("chem", old["chem"]), TESTS, "chem"),
            "term": _choice(b.get("term", old["term"]), TESTS, "term"),
            "bio": _choice(b.get("bio", old["bio"]), BIO, "bio"),
            **({"bio_actor": old["bio_actor"], "bio_at": old["bio_at"]} if old.get("bio_at") else {})})
    if reg == "502":
        room_id, room = old["room_id"], old["room"]
        if b.get("room_id") and int(b["room_id"]) != int(old["room_id"] or 0):
            r = await _active("room", b["room_id"])
            room_id, room = r["id"], r["name"]
        # проверка подписывает уборку, а не исправление: исправленную строку
        # проверяют заново (подпись не переезжает на текст, которого не видели)
        return await db.san_insert("502", {
            **base, "room_id": room_id, "room": room, "plan_date": old["plan_date"],
            "done_date": old["done_date"],
            "solution": _text(b.get("solution", old["solution"]), "solution")})
    if not old.get("off_at"):
        raise RegError("san_open", "", 409)
    minutes = _int(b.get("minutes", old["minutes"]), "minutes", 1, 24 * 60)
    on = _parse(old["on_at"])
    cond = b.get("cond")
    cond_word = COND[_choice(cond, tuple(COND), "cond", empty_ok=False)] if cond else old["cond"]
    rest = old.get("rest_hours")
    if rest is not None:
        rest = max(int(rest) + (int(old["minutes"] or 0) - minutes) // 60, 0)
    return await db.san_insert("501", {
        **base, "lamp_id": old["lamp_id"], "lamp": old["lamp"], "room": old["room"],
        "cond": cond_word, "on_at": old["on_at"], "off_at": _iso(on + timedelta(minutes=minutes)),
        "minutes": minutes, "rest_hours": rest, "off_actor": name})


async def lamp_new(user: dict | None, lamp_id: int) -> None:
    """«Lampă nouă»: дата замены по факту, отсчёт часов с нуля (паспорт 501/e)."""
    lamp = await _active("lamp", lamp_id)
    if any(int(r["lamp_id"] or 0) == lamp["id"] for r in await db.san_open("501")):
        raise RegError("san_uv_on", "lamp_id", 409)
    d = dict(lamp.get("data") or {})
    t = today().isoformat()
    d["changes"] = [*(d.get("changes") or []), {"date": t, "actor": _who(user)[0]}][-20:]
    d.update(since=t, base=0)
    await db.san_item_save({**lamp, "data": d})


def _json_list(v) -> list:
    if isinstance(v, list):
        return v
    try:
        x = json.loads(v or "[]")
        return x if isinstance(x, list) else []
    except ValueError:
        return []


# ---------- строки для экрана, листа и Excel ----------

def row_out(reg: str, r: dict, fixed: dict) -> dict:
    base = {"id": r["id"], "reg": reg, "actor": r["actor"], "at": stamp(r["created_at"]),
            "fixes": r.get("fixes"), "fixed_by": fixed.get(r["id"]), "why": r.get("why") or ""}
    if reg == "257":
        return {**base, "date": dmy(_loc(r["started_at"]).date()), "start": hm(r["started_at"]),
                "end": hm(r.get("ended_at")), "open": not r.get("ended_at"), "ster_id": r.get("ster_id"),
                "ster": r["ster"], "program": r["program"], "pressure": r["pressure"], "temp": r["temp"],
                "arts": _json_list(r["arts"]), "chem": r["chem"], "term": r["term"], "bio": r["bio"],
                "end_actor": r.get("end_actor") or "", "bio_actor": r.get("bio_actor") or "",
                "bio_at": stamp(r.get("bio_at")), "started_at": _iso(_parse(r["started_at"]))}
    if reg == "502":
        return {**base, "room_id": r.get("room_id"), "room": r["room"], "plan": dmy(r.get("plan_date")),
                "done": dmy(r["done_date"]), "solution": r["solution"], "sup_actor": r.get("sup_actor") or "",
                "sup_at": stamp(r.get("sup_at")), "actor_id": r.get("actor_id") or ""}
    return {**base, "date": dmy(_loc(r["on_at"]).date()), "lamp_id": r.get("lamp_id"), "lamp": r["lamp"],
            "room": r.get("room") or "", "cond": r["cond"], "on": hm(r["on_at"]), "off": hm(r.get("off_at")),
            "open": not r.get("off_at"), "minutes": r.get("minutes"), "rest": r.get("rest_hours"),
            "off_actor": r.get("off_actor") or "", "on_at": _iso(_parse(r["on_at"]))}


async def rows(reg: str, d1: date, d2: date) -> list[dict]:
    if reg == "502":
        raw = await db.san_rows(reg, d1.isoformat(), d2.isoformat())
    else:
        a, b = day_bounds(d1, d2)
        raw = await db.san_rows(reg, a, b)
    fixed = await db.san_fixed_ids(reg)
    return [row_out(reg, r, fixed) for r in raw]


async def model(month: str | None, user: dict | None, can_delete: bool, can_settings: bool) -> dict:
    """Экран целиком одним конвертом: «Azi» (оборудование и что идёт сейчас)
    и журналы за месяц для «Istoric». Минуты идущего цикла и лампы считает
    браузер по `started_at`/`on_at` — сервер «сейчас» не присылает."""
    cat = await catalog()
    items = cat["items"]
    t = today()
    open257 = {int(r["ster_id"] or 0): r for r in await db.san_open("257")}
    open501 = {int(r["lamp_id"] or 0): r for r in await db.san_open("501")}
    f257, f501, f502 = (await db.san_fixed_ids("257"), await db.san_fixed_ids("501"),
                        await db.san_fixed_ids("502"))
    sters = []
    for s in items["ster"]:
        if not s["active"]:
            continue
        run = open257.get(s["id"])
        last = await db.san_last_cycle(s["id"])
        sters.append({**s, "running": row_out("257", run, f257) if run else None,
                      "last": row_out("257", last, f257) if last else None})
    lamps = []
    for lamp in items["lamp"]:
        if not lamp["active"]:
            continue
        on = open501.get(lamp["id"])
        lamps.append({**lamp, "on": row_out("501", on, f501) if on else None})
    rooms = []
    for r in items["room"]:
        if not r["active"]:
            continue
        nxt = await room_next(r)
        last = await db.san_last_clean(r["id"])
        rooms.append({**r, "next": dmy(nxt), "last": dmy(last), "due": nxt <= t, "late": nxt < t})
    waiting = [row_out("502", r, f502) for r in await db.san_open("502")]
    m = month_of(month)
    d1, d2 = m, next_month(m)
    feed = []
    for reg in REGS:
        for r in await rows(reg, t, t + timedelta(days=1)):
            feed.append(r)
    name, uid = _who(user)
    return {
        "today": t.isoformat(), "month": m.strftime("%Y-%m"),
        "prev": date(m.year - (m.month == 1), (m.month - 2) % 12 + 1, 1).strftime("%Y-%m"),
        "next": next_month(m).strftime("%Y-%m"),
        "me": {"name": name, "id": uid}, "can": {"delete": can_delete, "settings": can_settings},
        "sters": sters, "lamps": lamps, "rooms": rooms, "waiting": waiting,
        "solutions": [x["name"] for x in items["solution"] if x["active"]],
        "articles": [x["name"] for x in items["article"] if x["active"]],
        "packs": [x["name"] for x in items["pack"] if x["active"]],
        "empty": not (items["ster"] or items["lamp"] or items["room"]),
        "feed": feed,
        "rows": {reg: await rows(reg, d1, d2) for reg in REGS},
    }
