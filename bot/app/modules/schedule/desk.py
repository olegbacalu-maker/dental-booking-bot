"""«La recepție» — рабочие списки регистратуры в правой колонке главной
(01.10, вместо карточки «Azi» с плитками-аналитикой).

Слово Олега 28.09: колонке «Azi» «там не место … то, что надо регистратуре»;
на показ прототипа — «выглядит очень серьёзно, мне очень нравится». Принцип
стоек SaaS: не цифры «как вчера», а СПИСКИ людей, у каждой строки — одно
действие. Цифры дня сжаты в одну строку в шапке карточки.

1. De confirmat — визиты следующего рабочего дня; звонок регистратуры вместо
   замороженных напоминаний бота. Отметка звонка — `appt_calls`, строка в
   летописи пациента.
2. De încasat azi — сегодняшние пациенты с долгом + касса дня (PERM_MONEY:
   директор; регистратура блока не видит).
3. Primul loc liber — ближайшее свободное время у каждого врача (под
   консультацию, 30 мин): ответ на звонок «когда можно прийти?».
4. Plan fără programare — активный план есть, будущей записи нет.

⭐ Едет В КОНВЕРТЕ живого канала (`_panel_live` → `desk`), а не своим GET:
состояние живой поверхности выпускается одной дверью, вместе с отпечатком;
отметка звонка — командой, после которой экран спрашивает канал. Отсюда
правило: тело детерминировано при неизменных данных (никаких «сейчас» в
строках) — иначе подмена шла бы каждый опрос (прайор 08-20).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ... import db
from ... import engine as eng
from ...core.auth import PERM_MONEY, can, request_user

_WD = ("Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du")
# статусы, при которых пациент «сегодня был/будет» — перечислением
_ST = {"confirmed": "confirmată", "waiting": "a venit", "arrived": "în cabinet",
       "done": "finalizată"}
SHOW = 8          # строк «Plan fără programare» в колонке; остальное — «încă N»
SLOT_MIN = 30     # «primul loc liber» — под консультацию
FREE_DAYS = 10    # сколько дней вперёд искать окно


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _day_word(d: date, today: date) -> str:
    if d == today:
        return "azi"
    if d == today + timedelta(days=1):
        return "mâine"
    return f"{_WD[d.weekday()]} {d.strftime('%d.%m')}"


def next_open(d: date) -> date:
    """Первый рабочий день клиники начиная с `d` (две недели вперёд, иначе `d`)."""
    for _ in range(14):
        if eng.hours_for(d):
            return d
        d += timedelta(days=1)
    return d


def _bounds(d: date) -> tuple[datetime, datetime]:
    s = datetime(d.year, d.month, d.day, tzinfo=eng.TZ)
    return s, s + timedelta(days=1)


def _local(v) -> datetime | None:
    return v.astimezone(eng.TZ) if hasattr(v, "astimezone") else None


async def _confirm(today: date) -> dict:
    d = next_open(today + timedelta(days=1))
    rows = [r for r in await db.day_appointments(*_bounds(d))
            if r["patient_id"] and r["status"] == "confirmed"]
    calls = await db.appt_calls([r["id"] for r in rows])
    items = []
    for r in rows:
        c = calls.get(r["id"])
        at = _local(c["at"]) if c else None
        items.append({
            "id": r["id"], "pid": r["patient_id"],
            "time": _local(r["starts_at"]).strftime("%H:%M"),
            "name": r["name"] or "—", "phone": r["phone"] or "",
            "doctor": r["doctor"] or "", "service": r["service"] or "",
            "call": c["result"] if c else "",
            "call_at": at.strftime("%H:%M") if at else "",
            "call_by": (c["actor"] if c else "") or "",
        })
    # ещё не звонили — сверху, по времени визита; отмеченные — вниз
    items.sort(key=lambda x: (x["call"] == "ok", x["call"] == "noanswer", x["time"]))
    return {"day": _day_word(d, today), "date": d.isoformat(), "items": items,
            "n": len(items), "n_ok": sum(1 for x in items if x["call"] == "ok"),
            "n_left": sum(1 for x in items if not x["call"])}


async def _unscheduled(now: datetime) -> dict:
    nxt = {r["patient_id"]: r["next_at"] for r in await db.patients_visits(now)}
    pats = {p["id"]: p for p in await db.all_patients()}
    items = []
    for r in await db.plan_open_summary():
        pid = r["patient_id"]
        p = pats.get(pid)
        if not p or nxt.get(pid):
            continue
        since = _local(r["created_at"])
        days = (now - since).days if since else 0
        items.append({"pid": pid, "name": p["name"] or "—", "phone": p["phone"] or "",
                      "n": int(r["n"]), "total": int(r["total"] or 0),
                      "total_s": _money(int(r["total"] or 0)), "days": days})
    items.sort(key=lambda x: (-x["total"], -x["days"], x["pid"]))
    return {"items": items[:SHOW], "n": len(items),
            "sum_s": _money(sum(x["total"] for x in items))}


async def _collect(today: date) -> dict:
    s, e = _bounds(today)
    debt = await db.patients_debt()
    seen: set = set()
    items = []
    for r in await db.day_appointments(s, e):
        pid = r["patient_id"]
        if not pid or pid in seen or r["status"] not in _ST:
            continue
        seen.add(pid)
        owe = debt.get(pid, 0)
        if owe > 0:
            items.append({"pid": pid, "name": r["name"] or "—",
                          "time": _local(r["starts_at"]).strftime("%H:%M"),
                          "status": r["status"], "status_label": _ST[r["status"]],
                          "debt": owe, "debt_s": _money(owe)})
    by: dict = {}
    for p in await db.payments_day(s, e):
        by[p["method"]] = by.get(p["method"], 0) + int(p["amount_mdl"] or 0)
    return {"items": items, "n": len(items),
            "sum_s": _money(sum(x["debt"] for x in items)),
            "cash": {"total_s": _money(sum(by.values())),
                     "parts": [{"method": m, "sum_s": _money(v)}
                               for m, v in sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))]},
            "casa_href": f"/admin/casa?d={today.isoformat()}"}


async def _free(today: date) -> list:
    out = []
    for dk, name in eng.ACTIVE_DOCTORS.items():
        d, first = today, None
        for _ in range(FREE_DAYS):
            if eng.hours_for(d):
                starts = await eng.free_starts(dk, d, SLOT_MIN)
                if starts:
                    first = starts[0].astimezone(eng.TZ)
                    break
            d += timedelta(days=1)
        out.append({"dk": dk, "name": name,
                    "when": (f"{_day_word(first.date(), today)} {first.strftime('%H:%M')}"
                             if first else "—"),
                    "today": bool(first and first.date() == today),
                    "href": f"/admin?date={first.date().isoformat()}" if first else ""})
    out.sort(key=lambda x: (not x["today"], x["when"], x["dk"]))
    return out


async def desk_model(now: datetime) -> dict:
    """Все четыре списка на момент `now` (день клиники — из него). Касса и
    долги — только тому, кому положены деньги (PERM_MONEY): регистратура
    получает `collect: null`, и карточка блока не рисует."""
    today = now.date()
    money = can(request_user(), PERM_MONEY)
    return {
        "confirm": await _confirm(today),
        "unscheduled": await _unscheduled(now),
        "collect": await _collect(today) if money else None,
        "free": await _free(today),
    }
