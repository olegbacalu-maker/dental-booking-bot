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
from datetime import date, datetime, timedelta, timezone

from .. import db
from .. import engine as eng
from . import sms_loop
from . import sms_plan as splan
from . import sms_rule

LEAD = 14          # В2 = А: строка появляется за 14 дней до срока
SNOOZE = 14        # «Sunat — revine» / «E-mail trimis» / «SMS trimis» прячут строку на 14 дней
SHOW_DESK = 3      # строк раздела на главной; остальное — «încă N · toată lista»
# белый список сроков (месяцев) — один на валидатор настроек и на экран
MONTHS = (3, 4, 6, 9, 12, 24)
# `sms` (30.10) ставит только `POST /api/recall/sms` после ответа сервера —
# руками через /mark не ставится (`MANUAL`): отметка без SMS врала бы
RESULTS = ("contacted", "emailed", "sms", "noanswer", "later", "stop", "clear")
MANUAL = tuple(r for r in RESULTS if r != "sms")
TABS = ("due", "snoozed", "stop")
# слово отметки — одно на строку списка, главную, фишу и летопись
WORD = {"contacted": "sunat — revine", "emailed": "e-mail trimis", "sms": "SMS trimis",
        "noanswer": "nu răspunde", "later": "amânat", "stop": "nu mai reamintim",
        "clear": "marcaj anulat"}
# недоставленная SMS возвращает строку в «De sunat» сразу (В4 = А, Олег 30.10):
# пациент её не видел, и стойке лучше позвонить
SMS_BACK = frozenset({db.SMS_UNDELIVERED, db.SMS_FAILED})


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


def mark_state(events: list[dict], cycle: int | None, today: date,
               sms_states: dict | None = None) -> tuple[str, dict | None]:
    """(вкладка, действующая отметка) пары по её журналу.

    Действует последняя строка: `stop` — всегда, через циклы; остальные —
    только пока `cycle_appt_id` равен текущему последнему done-визиту (пришёл
    на новую гигиену — старые «nu răspunde» и «amânat» перестают действовать
    сами). `clear` снимает строку перед собой. `later` прячет до даты
    (голая дата, пояс не применяется); `contacted`/`emailed`/`sms` — на SNOOZE
    дней от местной даты отметки; `noanswer` оставляет строку и считает
    попытки. `sms_states` — состояния SMS по ключу (`db.sms_states_by_kind`):
    у отметки `sms` в `mk["sms"]` слово доставки, а `undelivered`/`failed`
    возвращают строку в `due` сразу (SMS_BACK).
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
    if last["result"] == "sms":
        st = (sms_states or {}).get(splan.recall_idem(last["patient_id"], last["service_id"],
                                                      last.get("cycle_appt_id") or 0))
        state = str((st or {}).get("state") or "")
        mk["sms"] = {"state": state, "word": sms_loop.EVENT.get(state, ("", ""))[1]}
        if state in SMS_BACK:
            return "due", mk
    if last["result"] == "later":
        try:
            u = date.fromisoformat(str(last.get("until_date") or ""))
        except ValueError:
            return "due", mk
        mk["until"] = u.isoformat()
        return ("snoozed" if u > today else "due"), mk
    if last["result"] in ("contacted", "emailed", "sms") and at and (today - at).days < SNOOZE:
        mk["until"] = (at + timedelta(days=SNOOZE)).isoformat()
        return "snoozed", mk
    return "due", mk


def _by_pair(marks: list[dict]) -> dict[tuple[int, str], list[dict]]:
    out: dict[tuple[int, str], list[dict]] = {}
    for m in marks:
        out.setdefault((m["patient_id"], m["service_id"]), []).append(m)
    return out


def _sms_states(rows: list[dict]) -> dict:
    """`db.sms_states_by_kind(recall)` → {idem: строка}."""
    return {r["idem"]: r for r in rows}


def sms_button(r: dict, aid: int, sid: str, ctx: dict | None, states: dict) -> dict | None:
    """Блок кнопки «SMS» строки — данные, без часа: None — пакет не пускает
    (`ctx` пуст) или SMS этого цикла уже ушла (её состояние — в отметке);
    иначе {can, why}: `sms_off` — отказ пациента, `phone` — не мобильный РМ,
    `no_clinic_phone` — тексту нечего обещать. Тихие часы решает экран по
    `sms.quiet` конверта: они зависят от часа, а строка — нет."""
    if not ctx or not ctx.get("on"):
        return None
    if splan.recall_idem(r["patient_id"], sid, aid) in states:
        return None
    why = ""
    if r.get("sms_off"):
        why = "sms_off"
    elif not ctx.get("clinic_phone"):
        why = "no_clinic_phone"
    elif sms_rule.phone(r.get("phone") or "")[1]:
        why = "phone"
    return {"can": not why, "why": why}


def compute(done: list[dict], future: list[dict], marks: list[dict],
            svcs: list[dict], today: date, sms_rows: list[dict] | None = None,
            sms_ctx: dict | None = None) -> dict:
    """Список по правилу § 1 — чистая функция от выборок (проверяется без
    сервера). `done` — `db.recall_done_last`, `future` — `db.recall_future`,
    `marks` — `db.recall_marks`, `svcs` — `services()`; `sms_rows` —
    `db.sms_states_by_kind(recall)`, `sms_ctx` — {on, clinic_phone} (30.10)."""
    states = _sms_states(sms_rows or [])
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
        tab, mk = mark_state(pair_marks.get((r["patient_id"], s["id"]), []), r["aid"], today, states)
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
            "sms": sms_button(r, r["aid"], s["id"], sms_ctx, states) if tab != "stop" else None,
        })
    # без отметки — сверху, самые просроченные первыми; «nu răspunde» — вниз
    rows.sort(key=lambda x: (bool(x["mark"] and x["mark"]["result"] == "noanswer"),
                             -x["late_days"], x["name"], x["pid"]))
    return {"services": svcs,
            "rows": rows,
            "counts": {k: sum(1 for x in rows if x["tab"] == k) for k in TABS}}


def _day_start(today: date) -> datetime:
    return datetime(today.year, today.month, today.day, tzinfo=eng.TZ)


def sms_ctx() -> dict | None:
    """Контекст кнопки «SMS» (30.10): None — гейт `sms_loop.recall_on()` закрыт
    (Basic, выключено в облаке, без лицензии, галочка снята) — и экран не
    говорит об SMS ни слова."""
    if not sms_loop.recall_on():
        return None
    return {"on": True, "clinic_phone": bool((eng.CLINIC_PHONE or "").strip())}


def sms_head() -> dict | None:
    """Блок `sms` конверта экрана: остаток и тихие часы (единственное в
    конверте, что зависит от часа — поэтому только у экрана, не у главной)."""
    if sms_ctx() is None:
        return None
    acc = sms_loop.account() or {}
    return {"on": True, "balance": int(acc.get("balance") or 0),
            "quiet": not splan.awake(datetime.now(eng.TZ))}


async def model(today: date) -> dict:
    """Экран «Rechemări»: услуги со сроком, строки, счётчики вкладок."""
    svcs = services()
    if not svcs:
        return {"services": [], "rows": [], "counts": {k: 0 for k in TABS}}
    done = await db.recall_done_last([s["id"] for s in svcs])
    future = await db.recall_future(_day_start(today))
    marks = await db.recall_marks()
    sms_rows = await db.sms_states_by_kind(splan.RECALL)
    return compute(done, future, marks, svcs, today, sms_rows, sms_ctx())


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
    states = _sms_states(await db.sms_states_by_kind(splan.RECALL, pid))
    out = []
    for r in await db.recall_done_last(list(by_sid), patient_id=pid):
        s = by_sid[r["service_id"]]
        last = _local_date(r.get("last_at"))
        if not last:
            continue
        due = add_months(last, s["months"])
        tab, mk = mark_state(pair_marks.get((pid, s["id"]), []), r["aid"], today, states)
        out.append({"service": s["ro"], "service_id": s["id"],
                    "last": _dmy(last), "next": _dmy(due),
                    "late_days": (today - due).days, "late": late_word(due, today),
                    "stop": tab == "stop", "can_clear": tab == "stop" and can_clear,
                    "mark": mk})
    out.sort(key=lambda x: x["service"])
    return out


def month_start(d: date, back: int = 0) -> date:
    """Первое число месяца `d` минус `back` месяцев."""
    y, m = divmod(d.month - 1 - back, 12)
    return date(d.year + y, m + 1, 1)


def count_stats(contacts: list[dict], bookings: list[dict], start: date, end: date) -> dict:
    """«Contactați N · programați M» за [start, end) по дню клиники: N —
    пациенты с отметкой contacted/emailed в периоде (пациент, не пара), M — из
    них те, у кого ПОСЛЕ отметки создана запись на ту же услугу (живая или
    done). Чистая функция; `at`/`created_at` — datetime из `_DT_COLS`."""
    booked_at: dict[tuple[int, str], datetime] = {
        (b["patient_id"], b["service_id"]): b["created_at"] for b in bookings
        if isinstance(b.get("created_at"), datetime)}
    contacted: set[int] = set()
    booked: set[int] = set()
    for c in contacts:
        at = c.get("at")
        if not isinstance(at, datetime):
            continue
        local = at.astimezone(eng.TZ).date()
        if not start <= local < end:
            continue
        contacted.add(c["patient_id"])
        b = booked_at.get((c["patient_id"], c["service_id"]))
        # строго ПОСЛЕ: визит, заведённый задним числом в ту же секунду, что
        # отметка, записью «после звонка» не является
        if b is not None and b > at:
            booked.add(c["patient_id"])
    return {"contacted": len(contacted), "booked": len(booked)}


async def stats(today: date) -> dict | None:
    """Статистика одной строкой (Олег 29.10, В4 → Б): текущий и прошлый
    календарный месяц. Окно выборки — с начала прошлого месяца; бакеты
    считает Python по дню клиники. ⛔ Без единой отметки «sunat»/«e-mail» за
    оба месяца — None, строки нет (Олег: у новой клиники экран был бы в
    нулях); пустой ОДИН месяц рядом с живым — нули."""
    prev0, cur0, next0 = month_start(today, 1), month_start(today), add_months(month_start(today), 1)
    since = _day_start(prev0).astimezone(timezone.utc).isoformat(timespec="seconds")
    contacts = await db.recall_contacts_since(since)
    bookings = await db.recall_bookings_since(since)
    out = {"month": count_stats(contacts, bookings, cur0, next0),
           "prev": count_stats(contacts, bookings, prev0, cur0)}
    if not out["month"]["contacted"] and not out["prev"]["contacted"]:
        return None
    return out


async def pair(pid: int, sid: str) -> dict | None:
    """Последний done-визит пары с пациентом (телефон, язык, `sms_off`) — для
    кнопки «SMS»; None — визита нет или пациент архивный."""
    rows = await db.recall_done_last([sid], patient_id=pid)
    return rows[0] if rows else None


async def cycle_of(pid: int, sid: str) -> int | None:
    """id последнего done-визита пары — цикл, к которому привязывается
    отметка; None — отмечать нечего (визита нет, пациент архивный)."""
    row = await pair(pid, sid)
    return int(row["aid"]) if row else None
