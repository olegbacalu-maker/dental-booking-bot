"""«Rechemări» — кому пора на повторную процедуру (29.10.2026, мини-CRM стойки).

Срок задаётся у УСЛУГИ (`clinic.json › services[].recall = {months, since}`),
в код не зашит; участвуют только услуги, у которых срок задан, — это
перечисление, а не «все, кроме X». Список не хранится: он считается при
каждом запросе из done-визитов и конфига (`compute`, чистая функция), а
хранится только отметка регистратуры (`recall_marks`, журнал). Отсюда:
удалили визит, сменили процедуру или срок — список новый без единой записи,
а отметка переживает любой пересчёт, потому что пересчёт её только читает.

Живёт в `core`, а не в модуле: правило зовут ТРИ модуля (schedule/desk —
раздел на главной, patients — строка в фише, recall — экран), и сосед не
импортирует соседа. План и контракт — `docs/dentpilot-2/recall-api.md`,
review/plan-crm-rechemari-2026-10-29.md.

Правило (§ 1 плана), для каждой услуги `s` со сроком `m` и пациента `p`:
1. `last` — последний `done`-визит `p` с `service_id = s` (только done:
   неявка, отмена, «programată» часы не заводят); нет — строки нет.
2. `due` = местная дата `last` + `m` календарных месяцев, день прижат к
   концу месяца (31.08 + 6 → 28/29.02). Считает Python, не SQLite.
3. Окно показа: `due ≤ сегодня + LEAD` (В2 = А: за 14 дней).
4. Горизонт: `due ≥ since − m` — при включении «просрочка не больше одного
   интервала»; после включения ставший должным из списка сам не выпадает.
5. Записан вперёд (живой статус, от НАЧАЛА сегодняшнего дня — конверт
   обязан быть одинаковым весь день): на ту же услугу — строки нет, на
   другую — пометка `booked`.
6. Новый `done` той же услуги сдвигает `last` — цикл начинается заново.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from .. import db
from .. import engine as eng

LEAD = 14          # В2 = А: строка появляется за 14 дней до срока
SNOOZE = 14        # «Sunat — revine» / «E-mail trimis» прячут строку на 14 дней
SHOW_DESK = 3      # строк раздела на главной; остальное — «încă N · toată lista»
# белый список сроков (месяцев) — один на валидатор настроек и на экран
MONTHS = (3, 4, 6, 9, 12, 24)
RESULTS = ("contacted", "emailed", "noanswer", "later", "stop", "clear")
TABS = ("due", "snoozed", "stop")
# слово отметки — одно на строку списка, главную, фишу и летопись
WORD = {"contacted": "sunat — revine", "emailed": "e-mail trimis",
        "noanswer": "nu răspunde", "later": "amânat", "stop": "nu mai reamintim",
        "clear": "marcaj anulat"}


def services() -> list[dict]:
    """Услуги со сроком — из применённого конфига (`eng.SERVICES`): id, подпись
    RO, месяцы, дата включения (`since` ставит валидатор настроек; у строки,
    вписанной в файл руками без даты, — сегодня клиники)."""
    out = []
    for sid, s in eng.SERVICES.items():
        r = s.get("recall") or {}
        months = int(r.get("months") or 0)
        if months in MONTHS:
            out.append({"id": sid, "ro": s["ro"], "months": months,
                        "since": str(r.get("since") or datetime.now(eng.TZ).date().isoformat())})
    return out


def add_months(d: date, m: int) -> date:
    """Календарные месяцы с прижатием дня к концу месяца (31.08 + 6 → 28.02)."""
    y, mo = divmod(d.month - 1 + m, 12)
    y, mo = d.year + y, mo + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def late_word(due: date, today: date) -> str:
    """Просрочка словом: «peste 9 zile» · «mâine» · «azi» · «întârziere 3 zile /
    2 săpt. / 3 luni». Зависит только от дня — тело конверта в пределах дня
    неизменно."""
    n = (today - due).days
    if n < 0:
        return "mâine" if n == -1 else f"peste {-n} zile"
    if n == 0:
        return "azi"
    if n == 1:
        return "întârziere 1 zi"
    if n < 14:
        return f"întârziere {n} zile"
    if n < 60:
        return f"întârziere {n // 7} săpt."
    return f"întârziere {n // 30} luni"


def _dmy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _local_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.astimezone(eng.TZ).date()
    return None


def mark_state(events: list[dict], cycle: int | None, today: date) -> tuple[str, dict | None]:
    """(вкладка, действующая отметка) пары по её журналу.

    Действует последняя строка: `stop` — всегда, через циклы; остальные —
    только пока `cycle_appt_id` равен текущему последнему done-визиту (пришёл
    на новую гигиену — старые «nu răspunde» и «amânat» перестают действовать
    сами). `clear` снимает строку перед собой. `later` прячет до даты
    (голая дата, пояс не применяется); `contacted`/`emailed` — на SNOOZE дней
    от местной даты отметки; `noanswer` оставляет строку и считает попытки.
    """
    # `clear` снимает строку перед собой В ПОРЯДКЕ ЗАПИСИ, до отбора по циклу:
    # снятый «nu mai reamintim» прошлого цикла не должен воскреснуть, когда
    # пациент пришёл снова (отбор по циклу отбросил бы сам `clear`)
    stack: list[dict] = []
    for e in events:
        if e["result"] == "clear":
            if stack:
                stack.pop()
        else:
            stack.append(e)
    live = [e for e in stack if e["result"] == "stop" or e.get("cycle_appt_id") == cycle]
    if not live:
        return "due", None
    last = live[-1]
    at = _local_date(last.get("at"))
    mk = {"result": last["result"], "word": WORD.get(last["result"], ""),
          "until": "", "n_noanswer": sum(1 for e in live if e["result"] == "noanswer"),
          "at": at.strftime("%d.%m") if at else "", "actor": last.get("actor") or ""}
    if last["result"] == "stop":
        return "stop", mk
    if last["result"] == "later":
        try:
            u = date.fromisoformat(str(last.get("until_date") or ""))
        except ValueError:
            return "due", mk
        mk["until"] = u.isoformat()
        return ("snoozed" if u > today else "due"), mk
    if last["result"] in ("contacted", "emailed") and at and (today - at).days < SNOOZE:
        mk["until"] = (at + timedelta(days=SNOOZE)).isoformat()
        return "snoozed", mk
    return "due", mk


def _by_pair(marks: list[dict]) -> dict[tuple[int, str], list[dict]]:
    out: dict[tuple[int, str], list[dict]] = {}
    for m in marks:
        out.setdefault((m["patient_id"], m["service_id"]), []).append(m)
    return out


def compute(done: list[dict], future: list[dict], marks: list[dict],
            svcs: list[dict], today: date) -> dict:
    """Список по правилу § 1 — чистая функция от выборок (проверяется без
    сервера). `done` — `db.recall_done_last`, `future` — `db.recall_future`,
    `marks` — `db.recall_marks`, `svcs` — `services()`."""
    by_sid = {s["id"]: s for s in svcs}
    fut: dict[int, list[dict]] = {}
    for r in future:
        fut.setdefault(r["patient_id"], []).append(r)
    pair_marks = _by_pair(marks)
    rows = []
    for r in done:
        s = by_sid.get(r["service_id"])
        last = _local_date(r.get("last_at"))
        if not s or not last:
            continue
        due = add_months(last, s["months"])
        since = date.fromisoformat(s["since"])
        if due > today + timedelta(days=LEAD) or due < add_months(since, -s["months"]):
            continue
        f = fut.get(r["patient_id"], [])
        if any(x["service_id"] == s["id"] for x in f):
            continue
        other = min(f, key=lambda x: x["next_at"]) if f else None
        tab, mk = mark_state(pair_marks.get((r["patient_id"], s["id"]), []), r["aid"], today)
        rows.append({
            "pid": r["patient_id"], "name": r.get("name") or "—",
            "phone": r.get("phone") or "", "email": r.get("email") or "",
            "lang": "ru" if r.get("lang") == "ru" else "ro",
            "service_id": s["id"], "service": s["ro"], "months": s["months"],
            "last_at": last.isoformat(), "doctor": r.get("doctor") or "",
            "due": due.isoformat(), "late_days": (today - due).days,
            "late": late_word(due, today),
            "booked": ({"date": other["next_at"].astimezone(eng.TZ).strftime("%d.%m"),
                        "service": other.get("service") or ""} if other else None),
            "mark": mk, "tab": tab,
        })
    # без отметки — сверху, самые просроченные первыми; «nu răspunde» — вниз
    rows.sort(key=lambda x: (bool(x["mark"] and x["mark"]["result"] == "noanswer"),
                             -x["late_days"], x["name"], x["pid"]))
    return {"services": svcs,
            "rows": rows,
            "counts": {k: sum(1 for x in rows if x["tab"] == k) for k in TABS}}


def _day_start(today: date) -> datetime:
    return datetime(today.year, today.month, today.day, tzinfo=eng.TZ)


async def model(today: date) -> dict:
    """Экран «Rechemări»: услуги со сроком, строки, счётчики вкладок."""
    svcs = services()
    if not svcs:
        return {"services": [], "rows": [], "counts": {k: 0 for k in TABS}}
    done = await db.recall_done_last([s["id"] for s in svcs])
    future = await db.recall_future(_day_start(today))
    marks = await db.recall_marks()
    return compute(done, future, marks, svcs, today)


async def desk(today: date) -> dict:
    """Раздел на главной (конверт живого канала): счётчик «De sunat» и первые
    SHOW_DESK строк той же формы, что у экрана."""
    due = [x for x in (await model(today))["rows"] if x["tab"] == "due"]
    return {"n": len(due), "items": due[:SHOW_DESK]}


async def patient_lines(pid: int, today: date, can_clear: bool) -> list[dict]:
    """Строка срока в фише — по каждой услуге со сроком, где у пациента есть
    done-визит; окно и горизонт не применяются (это факт о пациенте, не
    список обзвона). `can_clear` — вправе ли вошедший снять «nu mai
    reamintim» (PERM_RECALL): строку видит любая роль."""
    svcs = services()
    if not svcs:
        return []
    by_sid = {s["id"]: s for s in svcs}
    pair_marks = _by_pair(await db.recall_marks(pid))
    out = []
    for r in await db.recall_done_last(list(by_sid), patient_id=pid):
        s = by_sid[r["service_id"]]
        last = _local_date(r.get("last_at"))
        if not last:
            continue
        due = add_months(last, s["months"])
        tab, mk = mark_state(pair_marks.get((pid, s["id"]), []), r["aid"], today)
        out.append({"service": s["ro"], "service_id": s["id"],
                    "last": _dmy(last), "next": _dmy(due),
                    "late_days": (today - due).days, "late": late_word(due, today),
                    "stop": tab == "stop", "can_clear": tab == "stop" and can_clear,
                    "mark": mk})
    out.sort(key=lambda x: x["service"])
    return out


async def cycle_of(pid: int, sid: str) -> int | None:
    """id последнего done-визита пары — цикл, к которому привязывается
    отметка; None — отмечать нечего (визита нет, пациент архивный)."""
    rows = await db.recall_done_last([sid], patient_id=pid)
    return int(rows[0]["aid"]) if rows else None
