"""Заказы в зуботехническую лабораторию: правила и модели экранов.

Заказ — письменное назначение изделия на заказ (Legea 102/2017): не удаляется,
только отменяется (`anulat`), номер сквозной. Статус шапки — не отдельная
правда, а пересчёт истории (`replay`): отмена шага пишет событие `anulare_pas`
и ничего не стирает. Цена лаборатории видна и пишется только с `PERM_MONEY`;
имени пациента в заказе нет — его берут из фиши в момент ответа или печати.
Запись — `db/lab.py`.
⚠️ Ошибка ввода — `LabError(code, field, status)`: код уходит в `msg_json`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from .. import db
from .. import engine as eng
from .auth import PERM_LABS, PERM_MONEY, PERM_SETTINGS, can
from .labels import LAB_CAUSE, LAB_EVENT_LABEL, LAB_IMPRESSION, LAB_PAYER, LAB_STATUS_LABEL

# Подсказки окна (те же, что в макете); поля свободные.
WORKS = ("Coroană", "Coroană pe implant", "Punte", "Fațetă", "Inlay / onlay", "Proteză parțială",
         "Proteză scheletată", "Proteză totală", "Alignere / gutiere", "Gutieră de protecție",
         "Lucrare provizorie", "Model de studiu / wax-up", "Altă lucrare")
MATERIALS = ("Zirconiu", "Metalo-ceramică", "E.max (disilicat de litiu)", "Ceramică feldspatică",
             "Compozit", "PMMA (provizoriu)", "Acrilat", "CoCr (scheletat)", "Polimer termoformat",
             "Alt material")
SHADES = ("A1", "A2", "A3", "A3.5", "A4", "B1", "B2", "B3", "C1", "C2", "D2", "D3", "BL1", "BL2")

FILTERS = ("lucru", "intarziate", "ridicat", "primite", "vizita", "finalizate", "anulate", "toate")
WHO = ("name", "fisa")

TEXT_MAX, NOTE_MAX, WHY_MAX, DATA_MAX = 120, 1000, 300, 120
ITEMS_MAX, QTY_MAX, PRICE_MAX, DAYS_MAX = 20, 99, 10_000_000, 90
_TEETH = {q * 10 + n for q in (1, 2, 3, 4) for n in range(1, 9)} | \
         {q * 10 + n for q in (5, 6, 7, 8) for n in range(1, 6)}

# Шаги, которые меняют статус. `trimis`, `etapa`, `refacere` — работа уехала
# к технику (новый срок); `etapa` прибавляет этап, переделка — нет.
_SEND = ("trimis", "etapa", "refacere")
_STATUS_KINDS = _SEND + ("gata", "primit", "proba", "finalizat", "anulat")

# Переходы: что можно сделать из статуса; первая — главная кнопка.
_NEXT = {
    "trimis": ("gata", "primit"),
    "gata": ("primit",),
    "primit": ("proba", "finalizat", "refacere"),
    "proba": ("finalizat", "etapa", "refacere"),
}
STEP_LABEL = {"gata": "E gata", "primit": "Primit", "proba": "Probă", "finalizat": "Finalizează",
              "etapa": "Etapa următoare", "refacere": "Refacere", "undo": "Anulează ultimul pas",
              "cancel": "Anulează comanda"}

_META_WHO, _META_LATE = "lab_who", "lab_late_gata"


class LabError(ValueError):
    def __init__(self, code: str, field: str = "", status: int = 422):
        super().__init__(code)
        self.code, self.field, self.status = code, field, status


# ---------- время и сроки ----------

def today() -> date:
    return datetime.now(eng.TZ).date()


def _day_start_utc(d: date) -> str:
    return datetime.combine(d, time(0), tzinfo=eng.TZ).astimezone(timezone.utc).isoformat(timespec="seconds")


def add_workdays(start: date, n: int, workdays: str) -> date:
    """Срок лаборатории: `n` её рабочих дней после отправки (пн=1 … вс=7).
    Праздников нет. Пустой набор дней — календарные."""
    days = {int(c) for c in (workdays or "") if c in "1234567"} or set(range(1, 8))
    d, left = start, max(0, int(n))
    while left:
        d += timedelta(days=1)
        if d.isoweekday() in days:
            left -= 1
    return d


def _d(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _date_in(body: dict, key: str, field: str = "") -> date | None:
    v = body.get(key)
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise LabError("lab_bad", field or key) from None


# ---------- история → шапка ----------

def replay(events: list) -> tuple[dict, set, int | None]:
    """Шапка из истории: (статус и даты, id отменённых шагов, какой шаг
    отменит «Anulează ultimul pas»). Единственное место, где из событий
    выводится статус: шапка в базе — только его копия для быстрых списков."""
    undone = {int(e["data"]["undoes"]) for e in events
              if e["kind"] == "anulare_pas" and (e.get("data") or {}).get("undoes")}
    head = {"status": "trimis", "stage": 1, "sent_on": None, "due_on": None,
            "received_on": None, "done_on": None}
    eff = []
    for e in events:
        k = e["kind"]
        if k in _STATUS_KINDS:
            if e["id"] in undone:
                continue
            eff.append(e)
        if k in _SEND:
            head.update(status="trimis", sent_on=e.get("on_date"), due_on=e.get("due_on"),
                        received_on=None, done_on=None)
            if k == "etapa":
                head["stage"] += 1
        elif k == "termen":
            head["due_on"] = e.get("due_on")
        elif k == "primit":
            head.update(status="primit", received_on=e.get("on_date"))
        elif k == "finalizat":
            head.update(status="finalizat", done_on=e.get("on_date"))
        elif k in ("gata", "proba", "anulat"):
            head["status"] = k
    return head, undone, (eff[-1]["id"] if len(eff) > 1 else None)


def steps(status: str, undoable: bool) -> list:
    out = [{"act": a, "label": STEP_LABEL[a], "main": i == 0} for i, a in enumerate(_NEXT.get(status, ()))]
    if undoable:
        out.append({"act": "undo", "label": STEP_LABEL["undo"], "main": False})
    if status in db.LAB_OPEN:
        out.append({"act": "cancel", "label": STEP_LABEL["cancel"], "main": False})
    return out


# ---------- кто ----------

def _who(me: dict | None) -> tuple[str, str]:
    me = me or {}
    return (me.get("name") or "director"), str(me.get("id") or "")


def can_map(me: dict | None) -> dict:
    return {"money": can(me, PERM_MONEY), "labs": can(me, PERM_LABS), "settings": can(me, PERM_SETTINGS)}


def _money(me) -> bool:
    return can(me, PERM_MONEY)


# ---------- настройки клиники ----------

async def prefs() -> dict:
    who = await db.get_meta(_META_WHO)
    return {"who": who if who in WHO else "name", "late_gata": (await db.get_meta(_META_LATE)) == "1"}


async def save_prefs(body: dict) -> None:
    if "who" in body:
        if body["who"] not in WHO:
            raise LabError("lab_bad", "who")
        await db.set_meta(_META_WHO, body["who"])
    if "late_gata" in body:
        await db.set_meta(_META_LATE, "1" if body["late_gata"] else "0")


# ---------- каталог ----------

def _text(body: dict, key: str, mx: int = TEXT_MAX, field: str = "") -> str:
    v = body.get(key)
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise LabError("lab_bad", field or key)
    s = " ".join(str(v).split()) if mx <= TEXT_MAX else str(v).strip()
    if len(s) > mx:
        raise LabError("lab_bad", field or key)
    return s


def _int(v, lo: int, hi: int, field: str) -> int:
    if isinstance(v, bool):
        raise LabError("lab_bad", field)
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise LabError("lab_bad", field) from None
    if n != v and not (isinstance(v, str) and v.strip().lstrip("-").isdigit()):
        raise LabError("lab_bad", field)
    if not lo <= n <= hi:
        raise LabError("lab_bad", field)
    return n


async def clean_lab(body: dict) -> dict:
    """Лаборатория из формы каталога. Двойника по имени не заводит."""
    name = _text(body, "name")
    if not name:
        raise LabError("lab_bad", "name")
    lid = body.get("id")
    old = None
    if lid:
        old = await db.lab_get(_int(lid, 1, 10**9, "id"))
        if not old:
            raise LabError("lab_lab_gone", status=404)
    twin = await db.lab_by_name(name)
    if twin and (not old or twin["id"] != old["id"]):
        raise LabError("lab_dup", "name")
    email = _text(body, "email")
    if email and "@" not in email:
        raise LabError("lab_bad", "email")
    wd = str(body.get("workdays") if body.get("workdays") is not None else (old or {}).get("workdays", "12345"))
    if not wd or any(c not in "1234567" for c in wd) or len(set(wd)) != len(wd):
        raise LabError("lab_bad", "workdays")
    data_in = body.get("data") if isinstance(body.get("data"), dict) else {}
    data = dict((old or {}).get("data") or {})
    for k in ("idno", "legal", "address", "note"):
        if k in data_in:
            data[k] = _text(data_in, k, field=k)
    if data.get("idno"):
        data["idno"] = data["idno"].replace(" ", "")
        if not (data["idno"].isdigit() and len(data["idno"]) == 13):
            raise LabError("lab_bad", "idno")
    if "own" in data_in:
        data["own"] = bool(data_in["own"])
    days = body.get("days", (old or {}).get("days", 7))
    return {
        "id": old["id"] if old else None, "name": name,
        "phone": _text(body, "phone"), "email": email, "contact": _text(body, "contact"),
        "days": _int(days, 0, DAYS_MAX, "days"), "workdays": "".join(sorted(wd)),
        "active": 1 if body.get("active", True) else 0,
        "sort": _int(body.get("sort", (old or {}).get("sort", 0)) or 0, -9999, 9999, "sort"),
        "data": data,
    }


def lab_out(r: dict, full: bool = False) -> dict:
    out = {"id": r["id"], "name": r["name"], "days": r["days"], "workdays": r["workdays"],
           "active": bool(r["active"])}
    if full:
        out.update(phone=r["phone"], email=r["email"], contact=r["contact"], sort=r["sort"],
                   data=r.get("data") or {}, orders=int(r.get("orders") or 0), open=int(r.get("open") or 0))
    return out


async def settings_model(me) -> dict:
    return {"labs": [lab_out(r, True) for r in await db.labs_all()], "prefs": await prefs(),
            "can": can_map(me)}


async def due_for(lab_id: int, sent: date | None) -> date:
    lab = await db.lab_get(lab_id)
    if not lab:
        raise LabError("lab_lab_gone", status=404)
    return add_workdays(sent or today(), lab["days"], lab["workdays"])


# ---------- строки модели ----------

def _teeth_list(s: str) -> list[int]:
    return [int(t) for t in (s or "").split(",") if t.strip().isdigit()]


def _fisa(r: dict) -> str:
    return (r.get("file_no") or "").strip() or str(r["patient_id"])


def work_summary(items: list) -> str:
    """Сводка строк одной строкой: группа (мост) — одним изделием, одинаковые
    работы — одной с числом («Fațetă ×2»)."""
    counts: dict[str, list] = {}
    seen: set = set()
    for it in items:
        if it.get("grp") is not None:
            if it["grp"] in seen:
                continue
            seen.add(it["grp"])
        key = it["work"].strip().lower()
        cur = counts.setdefault(key, [it["work"], 0])
        cur[1] += 1 if it.get("grp") is not None else (it.get("qty") or 1)
    return " · ".join(w + (f" ×{n}" if n > 1 else "") for w, n in counts.values())


def _appt_out(a: dict | None, td: date) -> dict | None:
    if not a:
        return None
    st = a["starts_at"]
    if isinstance(st, str):
        st = datetime.fromisoformat(st)
    if st.tzinfo is None:
        st = st.replace(tzinfo=timezone.utc)
    loc = st.astimezone(eng.TZ)
    d = loc.date()
    day = "azi" if d == td else "maine" if d == td + timedelta(days=1) else None
    return {"id": a["id"], "starts_at": loc.isoformat(timespec="minutes"), "date": d.isoformat(),
            "time": loc.strftime("%H:%M"), "doctor": a.get("doctor") or "", "day": day}


def order_row(o: dict, items: list, appt: dict | None, td: date, late_gata: bool, money: bool) -> dict:
    st = o["status"]
    due = _d(o.get("due_on"))
    waits = st == "trimis" or (st == "gata" and late_gata)
    late = bool(waits and due and due < td)
    teeth = sorted({t for it in items for t in _teeth_list(it.get("teeth", ""))})
    nxt = _appt_out(appt, td)
    row = {
        "id": o["id"], "nr": o["nr"], "pid": o["patient_id"], "patient": o.get("patient") or "",
        "fisa": _fisa(o), "doctor_id": o["doctor_id"], "doctor": o["doctor"],
        "lab_id": o["lab_id"], "lab": o["lab"], "status": st, "status_label": LAB_STATUS_LABEL.get(st, st),
        "stage": o["stage"], "sent_on": o["sent_on"], "due_on": o["due_on"],
        "received_on": o["received_on"], "done_on": o["done_on"],
        "urgent": bool(o["urgent"]), "impression": o["impression"],
        "work": work_summary(items), "teeth": teeth,
        "late": late, "days_late": (td - due).days if late else None,
        "due_in": (due - td).days if (due and st in ("trimis", "gata")) else None,
        "ready": st == "gata",
        "next_appt": nxt,
        "visit_wait": bool(nxt and nxt["day"] and st in ("trimis", "gata")),
    }
    if money:
        row["total_bani"] = sum(int(it["price_bani"]) for it in items if it.get("price_bani") is not None)
    return row


def item_out(it: dict, money: bool) -> dict:
    plan = None
    if it.get("plan_item_id") and it.get("plan_procedure") is not None:
        plan = {"id": it["plan_item_id"], "procedure": it["plan_procedure"], "tooth": it["plan_tooth"],
                "status": it["plan_status"]}
    out = {"id": it["id"], "plan_item_id": it.get("plan_item_id"), "plan": plan,
           "service_id": it.get("service_id"), "work": it["work"], "material": it["material"],
           "shade": it["shade"], "teeth": _teeth_list(it["teeth"]), "qty": it["qty"], "grp": it["grp"]}
    if money:
        out["price_bani"] = it.get("price_bani")
    return out


def event_out(e: dict, undone: set) -> dict:
    return {"id": e["id"], "kind": e["kind"], "kind_label": LAB_EVENT_LABEL.get(e["kind"], e["kind"]),
            "on_date": e.get("on_date"), "due_on": e.get("due_on"),
            "cause": e.get("cause") or None, "cause_label": LAB_CAUSE.get(e.get("cause") or "", ""),
            "payer": e.get("payer") or None, "payer_label": LAB_PAYER.get(e.get("payer") or "", ""),
            "note": e.get("note") or "", "actor": e.get("actor") or "", "doer": e.get("doer") or "",
            "at": e["at"].isoformat() if isinstance(e["at"], datetime) else e["at"],
            "undone": e["id"] in undone}


async def _rows(orders: list, me, td: date | None = None) -> list:
    """Строки списка: кнопки шагов едут в каждой — экран своей таблицы
    переходов не держит, а «можно ли отменить шаг» знает только история."""
    td = td or today()
    ids = [o["id"] for o in orders]
    items = await db.lab_items(ids)
    events = await db.lab_events(ids)
    appts = await db.lab_next_appts(sorted({o["patient_id"] for o in orders}), _day_start_utc(td))
    late_gata = (await prefs())["late_gata"]
    money = _money(me)
    out = []
    for o in orders:
        row = order_row(o, items.get(o["id"], []), appts.get(o["patient_id"]), td, late_gata, money)
        row["steps"] = steps(o["status"], replay(events.get(o["id"], []))[2] is not None)
        out.append(row)
    return out


def _match(r: dict, f: str) -> bool:
    st = r["status"]
    return {"lucru": st in db.LAB_OPEN, "intarziate": r["late"], "ridicat": r["ready"],
            "primite": st in ("primit", "proba"), "vizita": r["visit_wait"],
            "finalizate": st == "finalizat", "anulate": st == "anulat", "toate": True}[f]


def _order_key(r: dict):
    opened = r["status"] in db.LAB_OPEN
    return (0 if r["late"] else 1, -(r["days_late"] or 0), 0 if opened else 1,
            (r["due_on"] or "9999-12-31") if opened else "", -r["nr"])


async def list_model(me, f: str = "", q: str = "", lab: str = "") -> dict:
    f = f if f in FILTERS else "lucru"
    rows = await _rows(await db.lab_orders_rows(), me)
    counts = {k: sum(1 for r in rows if _match(r, k)) for k in FILTERS}
    shown = [r for r in rows if _match(r, f)]
    if lab and str(lab).isdigit():
        shown = [r for r in shown if r["lab_id"] == int(lab)]
    if q.strip():
        needle = db.fold(q.strip())
        shown = [r for r in shown
                 if needle in db.fold(" ".join((r["patient"], r["fisa"], str(r["nr"]), r["work"], r["lab"])))]
    shown.sort(key=_order_key)
    return {"today": today().isoformat(), "f": f, "counts": counts, "orders": shown,
            "labs": [lab_out(x) for x in await db.labs_all()], "can": can_map(me)}


def _badges(rows: list, items: dict) -> dict:
    out: dict[str, dict] = {}
    for r in rows:                       # новые сверху: первый встретившийся — последний заказ
        if r["status"] == "anulat":
            continue
        for it in items.get(r["id"], []):
            key = str(it.get("plan_item_id") or "")
            if key and key not in out:
                out[key] = {"order_id": r["id"], "nr": r["nr"], "status": r["status"],
                            "status_label": r["status_label"], "due_on": r["due_on"],
                            "late": r["late"], "ready": r["ready"]}
    return out


async def patient_model(me, pid: int) -> dict:
    if not await db.get_patient(pid):
        raise LabError("lab_patient_gone", status=404)
    orders = await db.lab_orders_rows(pid)
    rows = await _rows(orders, me)
    items = await db.lab_items([o["id"] for o in orders])
    td = today()
    nxt = (await db.lab_next_appts([pid], _day_start_utc(td))).get(pid)
    return {"today": td.isoformat(), "pid": pid, "orders": rows, "plan": _badges(rows, items),
            "next_appt": _appt_out(nxt, td), "can": can_map(me)}


def _active_doctors() -> list:
    return [{"id": k, "name": v} for k, v in eng.DOCTORS.items()
            if eng.DOCTOR_META.get(k, {}).get("active", True)]


def _doctor_of_plan(p: dict) -> str:
    dk = str(p.get("doctor_id") or "")
    if dk in eng.DOCTORS:
        return dk
    for k, v in eng.DOCTORS.items():
        if p.get("doctor") and v == p["doctor"]:
            return k
    return ""


async def form_model(me, pid: int | None, plan_item: int | None) -> dict:
    patient, plan, dk = None, [], ""
    if pid:
        p = await db.get_patient(pid)
        if not p:
            raise LabError("lab_patient_gone", status=404)
        patient = {"pid": pid, "name": p.get("name") or "",
                   "fisa": (p.get("file_no") or "").strip() or str(pid)}
        orders = await db.lab_orders_rows(pid)
        rows = await _rows(orders, me)
        badges = _badges(rows, await db.lab_items([o["id"] for o in orders]))
        for it in await db.plan_items(pid):
            if it["status"] not in db.PLAN_ACTIVE:
                continue
            full = await db.lab_plan_item(it["id"], pid) or {}
            k = _doctor_of_plan(full)
            plan.append({"id": it["id"], "tooth": it["tooth"], "procedure": it["procedure"],
                         "doctor": it["doctor"], "doctor_id": k or None, "status": it["status"],
                         "ordered": badges.get(str(it["id"]))})
            if plan_item and it["id"] == plan_item:
                dk = k
    if not dk:
        own = str((me or {}).get("doctor_id") or "")
        dk = own if own in eng.DOCTORS else ""
    out = {
        "today": today().isoformat(), "patient": patient, "plan": plan,
        "labs": [lab_out(x) for x in await db.labs_all() if x["active"]],
        "doctors": _active_doctors(), "doctor_id": dk,
        "words": {"status": LAB_STATUS_LABEL, "kind": LAB_EVENT_LABEL, "cause": LAB_CAUSE,
                  "payer": LAB_PAYER, "impression": LAB_IMPRESSION},
        "works": list(WORKS), "materials": list(MATERIALS), "shades": list(SHADES),
        "who": (await prefs())["who"], "can": can_map(me),
    }
    if _money(me):
        seen, last = set(), []
        for r in await db.lab_last_prices():
            key = (r["lab_id"], r["work"].strip().lower())
            if key not in seen:
                seen.add(key)
                last.append({"lab_id": r["lab_id"], "work": r["work"], "price_bani": r["price_bani"],
                             "nr": r["nr"], "on": r["sent_on"]})
        out["last_prices"] = last
    return out


async def _order_full(oid: int):
    o = await db.lab_order_head(oid)
    if not o:
        raise LabError("lab_gone", status=404)
    rows = await db.lab_orders_rows(o["patient_id"])
    o = next(r for r in rows if r["id"] == oid)
    evs = (await db.lab_events([oid])).get(oid, [])
    its = (await db.lab_items([oid])).get(oid, [])
    return o, its, evs


async def order_model(me, oid: int) -> dict:
    o, its, evs = await _order_full(oid)
    row = (await _rows([o], me))[0]
    _, undone, target = replay(evs)
    money = _money(me)
    row.update(appointment_id=o["appointment_id"], note=o["note"],
               data={k: o["data"][k] for k in ("tech", "invoice") if k in (o.get("data") or {})},
               items=[item_out(it, money) for it in its],
               events=[event_out(e, undone) for e in evs])
    return {"order": row, "steps": steps(o["status"], target is not None), "can": can_map(me)}


async def dash_model(me, td: date, scope: str | None = None) -> dict:
    """Плашка главной — едет в конверте живого канала панели (`_panel_live`).
    ⛔ Только от дня `td`, ни одного «сейчас»: отпечаток канала обязан стоять
    весь день при неизменных данных. `scope` — журнал вошедшего, как у
    остальной панели: врачу — заказы своего врача, учётке без врача — ничего."""
    if scope == "":
        orders = []
    else:
        orders = [o for o in await db.lab_orders_rows() if o["status"] in db.LAB_OPEN
                  and (scope is None or o["doctor_id"] == scope)]
    rows = await _rows(orders, me, td)

    def brief(r):
        return {"id": r["id"], "nr": r["nr"], "pid": r["pid"], "patient": r["patient"], "work": r["work"],
                "lab": r["lab"], "due_on": r["due_on"], "days_late": r["days_late"],
                "next_appt": r["next_appt"]}

    late = sorted((r for r in rows if r["late"]), key=lambda r: (-(r["days_late"] or 0), r["nr"]))
    ready = sorted((r for r in rows if r["ready"]), key=lambda r: (r["due_on"] or "", r["nr"]))
    visit = sorted((r for r in rows if r["visit_wait"]), key=lambda r: (r["next_appt"]["starts_at"], r["nr"]))
    return {"late": [brief(r) for r in late], "ready": [brief(r) for r in ready],
            "visit": [brief(r) for r in visit],
            "counts": {"late": len(late), "ready": len(ready), "visit": len(visit)}}


# ---------- заказ из формы ----------

def _teeth_in(v, field: str) -> str:
    if v in (None, ""):
        return ""
    if not isinstance(v, list):
        raise LabError("lab_bad", field)
    out: list[int] = []
    for t in v:
        if isinstance(t, bool) or not isinstance(t, int) or t not in _TEETH:
            raise LabError("lab_bad", field)
        if t not in out:
            out.append(t)
    return ",".join(str(t) for t in out)


async def _items_in(raw, pid: int, money: bool, old: dict[int, dict]) -> list:
    if not isinstance(raw, list) or not raw:
        raise LabError("lab_bad", "items")
    if len(raw) > ITEMS_MAX:
        raise LabError("lab_bad", "items")
    out, plans = [], set()
    for i, it in enumerate(raw):
        f = f"items.{i}"
        if not isinstance(it, dict):
            raise LabError("lab_bad", f)
        iid = it.get("id")
        if iid is not None:
            iid = _int(iid, 1, 10**9, f)
            if iid not in old:
                raise LabError("lab_bad", f)
        work = _text(it, "work", field=f"{f}.work")
        if not work:
            raise LabError("lab_bad", f"{f}.work")
        row = {"id": iid, "work": work, "material": _text(it, "material", field=f"{f}.material"),
               "shade": _text(it, "shade", field=f"{f}.shade"),
               "teeth": _teeth_in(it.get("teeth"), f"{f}.teeth"),
               "qty": _int(it.get("qty", 1) or 1, 1, QTY_MAX, f"{f}.qty"),
               "grp": None if it.get("grp") in (None, "") else _int(it["grp"], 0, 999, f"{f}.grp"),
               "plan_item_id": None, "service_id": None}
        pi = it.get("plan_item_id")
        if pi not in (None, ""):
            pi = _int(pi, 1, 10**9, f"{f}.plan")
            if pi in plans:
                raise LabError("lab_bad", f"{f}.plan")
            plan = await db.lab_plan_item(pi, pid)
            if not plan:
                raise LabError("lab_bad", f"{f}.plan")
            plans.add(pi)
            row["plan_item_id"] = pi
            row["service_id"] = plan.get("service_id") or None
        if money and "price_bani" in it:
            pb = it["price_bani"]
            row["price_bani"] = None if pb in (None, "") else _int(pb, 0, PRICE_MAX, f"{f}.price")
        else:
            row["price_bani"] = old[iid]["price_bani"] if iid else None
        out.append(row)
    return out


async def _lab_in(body: dict, me, *, required: bool) -> tuple[dict | None, str]:
    """(лаборатория из каталога | None, имя новой). Новую заводит вызывающий
    ПОСЛЕ всех проверок заказа — иначе отказ по сроку оставил бы её в каталоге."""
    lid = body.get("lab_id")
    if lid not in (None, ""):
        lab = await db.lab_get(_int(lid, 1, 10**9, "lab"))
        if not lab:
            raise LabError("lab_lab_gone", "lab", 404)
        return lab, ""
    name = _text(body, "lab_name", field="lab")
    if not name:
        if required:
            raise LabError("lab_need_lab", "lab")
        return None, ""
    twin = await db.lab_by_name(name)
    if twin:
        return twin, ""
    if not can(me, PERM_LABS):
        raise LabError("no_access", "lab", 403)
    return None, name


def _doctor_in(body: dict) -> str:
    dk = str(body.get("doctor_id") or "")
    if dk and dk not in eng.DOCTORS:
        raise LabError("lab_bad", "doctor")
    return dk


def _data_in(body: dict, old: dict) -> dict:
    d = dict(old or {})
    raw = body.get("data") if isinstance(body.get("data"), dict) else {}
    for k in ("tech", "invoice"):
        if k in raw:
            d[k] = _text(raw, k, DATA_MAX, k)
    return d


async def _appt_in(body: dict, pid: int):
    a = body.get("appointment_id")
    if a in (None, ""):
        return None
    a = _int(a, 1, 10**12, "appointment")
    if await db.lab_appt_patient(a) != pid:
        raise LabError("lab_bad", "appointment")
    return a


def _impr(body: dict) -> str:
    v = str(body.get("impression") or "")
    if v and v not in LAB_IMPRESSION:
        raise LabError("lab_bad", "impression")
    return v


async def _new_lab(name: str) -> dict:
    lid = await db.lab_save({"name": name, "phone": "", "email": "", "contact": "", "days": 7,
                             "workdays": "12345", "active": 1, "sort": 0, "data": {}})
    return await db.lab_get(lid)


def _short(s: str, n: int = 70) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


async def create(me, body: dict) -> tuple[int, int]:
    pid = body.get("pid")
    pid = _int(pid, 1, 10**12, "pid") if pid not in (None, "") else None
    if not pid or not await db.get_patient(pid):
        raise LabError("lab_bad", "pid")
    lab, new_name = await _lab_in(body, me, required=True)
    dk = _doctor_in(body)
    td = today()
    sent = _date_in(body, "sent_on") or td
    if sent > td:
        raise LabError("lab_bad", "sent_on")
    due = _date_in(body, "due_on")
    items = await _items_in(body.get("items"), pid, _money(me), {})
    note = _text(body, "note", NOTE_MAX)
    appt = await _appt_in(body, pid)
    impr = _impr(body)
    data = _data_in(body, {})
    if due is None:
        due = add_workdays(sent, lab["days"] if lab else 7, lab["workdays"] if lab else "12345")
    if due < sent:
        raise LabError("lab_bad", "due_on")
    if new_name:
        lab = await _new_lab(new_name)
    actor, aid = _who(me)
    head = {"patient_id": pid, "doctor_id": dk, "doctor": eng.DOCTORS.get(dk, "") if dk else "",
            "lab_id": lab["id"], "lab": lab["name"], "appointment_id": appt,
            "urgent": 1 if body.get("urgent") else 0, "impression": impr, "note": note,
            "status": "trimis", "stage": 1, "sent_on": sent.isoformat(), "due_on": due.isoformat(),
            "received_on": None, "done_on": None, "data": data, "actor": actor, "actor_id": aid}
    first = {"kind": "trimis", "on_date": sent.isoformat(), "due_on": due.isoformat(),
             "actor": actor, "actor_id": aid}
    oid, nr = await db.lab_order_create(head, items, first)
    await db.log_event(pid, "lab", _short(f"Laborator: comanda nr {nr} — {work_summary(items)} — "
                                          f"trimisă la {lab['name']}", 190), actor=actor)
    return oid, nr


async def _load(oid: int):
    o = await db.lab_order_head(oid)
    if not o:
        raise LabError("lab_gone", status=404)
    evs = (await db.lab_events([oid])).get(oid, [])
    return o, evs


async def _commit(o: dict, evs: list, new: list, *, head: dict | None = None,
                  items: list | None = None) -> dict:
    """Дописать события и переложить копию истории в шапку одной записью."""
    for i, e in enumerate(new):
        e.setdefault("id", -(i + 1))
    h, _, _ = replay(evs + new)
    for e in new:
        e.pop("id", None)
    await db.lab_order_write(o["id"], head={**(head or {}), **h}, items=items, events=new)
    return h


def _fmt(d) -> str:
    dd = _d(d)
    return dd.strftime("%d.%m.%Y") if dd else "—"


def _lei(b: int) -> str:
    return f"{b / 100:.2f}".rstrip("0").rstrip(".") + " lei"


async def edit(me, oid: int, body: dict) -> None:
    o, evs = await _load(oid)
    if o["status"] in db.LAB_CLOSED:
        raise LabError("lab_closed", status=409)
    pid = o["patient_id"]
    actor, aid = _who(me)
    money = _money(me)
    head, new, plain = {}, [], False
    ev = {"actor": actor, "actor_id": aid, "on_date": today().isoformat()}

    lab, new_name = await _lab_in(body, me, required=False)
    if "doctor_id" in body:
        dk = _doctor_in(body)
        if dk != o["doctor_id"]:
            head.update(doctor_id=dk, doctor=eng.DOCTORS.get(dk, "") if dk else "")
            plain = True
    due = _date_in(body, "due_on")
    if due is not None:
        sent = _d(o["sent_on"])
        if sent and due < sent:
            raise LabError("lab_bad", "due_on")
    if "urgent" in body and (1 if body["urgent"] else 0) != o["urgent"]:
        head["urgent"] = 1 if body["urgent"] else 0
        plain = True
    if "impression" in body and _impr(body) != o["impression"]:
        head["impression"] = _impr(body)
        plain = True
    if "note" in body and _text(body, "note", NOTE_MAX) != o["note"]:
        head["note"] = _text(body, "note", NOTE_MAX)
        plain = True
    if "appointment_id" in body and (a := await _appt_in(body, pid)) != o["appointment_id"]:
        head["appointment_id"] = a
        plain = True
    if "data" in body:
        d = _data_in(body, o.get("data") or {})
        if d != (o.get("data") or {}):
            head["data"] = d
            plain = True
    items = None
    if "items" in body:
        cur = (await db.lab_items([oid])).get(oid, [])
        old = {it["id"]: it for it in cur}
        items = await _items_in(body["items"], pid, money, old)
        was = [(it["id"], it["work"], it["material"], it["shade"], it["teeth"], it["qty"], it["grp"],
                it["plan_item_id"]) for it in cur]
        now_ = [(it["id"], it["work"], it["material"], it["shade"], it["teeth"], it["qty"], it["grp"],
                 it["plan_item_id"]) for it in items]
        old_p = {it["id"]: it["price_bani"] for it in cur}
        kept = {it["id"] for it in items if it["id"]}
        priced = money and (any(it["price_bani"] != old_p[it["id"]] for it in items if it["id"])
                            or any(it["price_bani"] is not None for it in items if not it["id"])
                            or any(p is not None for i, p in old_p.items() if i not in kept))
        if was != now_:
            plain = True
        if priced:
            sums = (sum(it["price_bani"] or 0 for it in cur), sum(it["price_bani"] or 0 for it in items))
            new.append({**ev, "kind": "pret", "note": f"{_lei(sums[0])} › {_lei(sums[1])}"})
        if was == now_ and not priced:
            items = None
    if new_name:
        lab = await _new_lab(new_name)
    if lab and lab["id"] != o["lab_id"]:
        head.update(lab_id=lab["id"], lab=lab["name"])
        new.append({**ev, "kind": "laborator", "note": _short(f"{o['lab']} › {lab['name']}", 200)})
    if due is not None and due.isoformat() != o["due_on"]:
        new.append({**ev, "kind": "termen", "due_on": due.isoformat(),
                    "note": f"{_fmt(o['due_on'])} › {_fmt(due)}"})
    if plain:
        new.append({**ev, "kind": "editat"})
    if not new and items is None:
        return
    await _commit(o, evs, new, head=head, items=items)


def _on_date(body: dict, o: dict) -> date:
    d = _date_in(body, "on_date") or today()
    sent = _d(o["sent_on"])
    if d > today() or (sent and d < sent):
        raise LabError("lab_bad", "on_date")
    return d


async def _log_step(o: dict, word: str, actor: str) -> None:
    await db.log_event(o["patient_id"], "lab",
                       _short(f"Laborator: comanda nr {o['nr']} › {word}", 190), actor=actor)


async def step(me, oid: int, body: dict) -> None:
    o, evs = await _load(oid)
    to = str(body.get("to") or "")
    if to not in ("gata", "primit", "proba", "finalizat") or to not in _NEXT.get(o["status"], ()):
        raise LabError("lab_step", status=409)
    actor, aid = _who(me)
    on = _on_date(body, o)
    await _commit(o, evs, [{"kind": to, "on_date": on.isoformat(), "note": _text(body, "note", WHY_MAX),
                            "actor": actor, "actor_id": aid}])
    await _log_step(o, LAB_STATUS_LABEL[to], actor)


async def _resend(me, oid: int, body: dict, kind: str) -> None:
    o, evs = await _load(oid)
    if kind not in _NEXT.get(o["status"], ()):
        raise LabError("lab_step", status=409)
    ev: dict = {"kind": kind}
    if kind == "refacere":
        cause = str(body.get("cause") or "")
        if cause not in LAB_CAUSE:
            raise LabError("lab_bad", "cause")
        payer = str(body.get("payer") or "")
        if payer not in LAB_PAYER:
            raise LabError("lab_bad", "payer")
        ev.update(cause=cause, payer=payer)
    note = _text(body, "note", WHY_MAX)
    if kind == "refacere" and ev["cause"] == "alta" and not note:
        raise LabError("lab_bad", "note")
    td = today()
    sent = _date_in(body, "sent_on") or td
    if sent > td or (_d(o["sent_on"]) and sent < _d(o["sent_on"])):
        raise LabError("lab_bad", "sent_on")
    due = _date_in(body, "due_on")
    if due is None:
        lab = await db.lab_get(o["lab_id"]) if o["lab_id"] else None
        due = add_workdays(sent, lab["days"] if lab else 7, lab["workdays"] if lab else "12345")
    if due < sent:
        raise LabError("lab_bad", "due_on")
    actor, aid = _who(me)
    ev.update(on_date=sent.isoformat(), due_on=due.isoformat(), note=note, actor=actor, actor_id=aid)
    await _commit(o, evs, [ev])
    word = LAB_EVENT_LABEL[kind] + (f" ({LAB_CAUSE[ev['cause']].lower()})" if kind == "refacere" else "")
    await _log_step(o, word, actor)


async def etapa(me, oid: int, body: dict) -> None:
    await _resend(me, oid, body, "etapa")


async def refacere(me, oid: int, body: dict) -> None:
    await _resend(me, oid, body, "refacere")


async def undo(me, oid: int) -> None:
    o, evs = await _load(oid)
    _, _, target = replay(evs)
    if target is None:
        raise LabError("lab_no_undo", status=409)
    gone = next(e for e in evs if e["id"] == target)
    actor, aid = _who(me)
    await _commit(o, evs, [{"kind": "anulare_pas", "on_date": today().isoformat(),
                            "note": LAB_EVENT_LABEL.get(gone["kind"], gone["kind"]),
                            "data": {"undoes": target}, "actor": actor, "actor_id": aid}])
    await _log_step(o, f"pas anulat ({LAB_EVENT_LABEL.get(gone['kind'], gone['kind']).lower()})", actor)


async def cancel(me, oid: int, body: dict) -> None:
    o, evs = await _load(oid)
    if o["status"] not in db.LAB_OPEN:
        raise LabError("lab_step", status=409)
    why = _text(body, "why", WHY_MAX)
    if not why:
        raise LabError("lab_bad", "why")
    actor, aid = _who(me)
    await _commit(o, evs, [{"kind": "anulat", "on_date": today().isoformat(), "note": why,
                            "actor": actor, "actor_id": aid}])
    await _log_step(o, "anulată", actor)


# ---------- лист наряда ----------

async def sheet_data(me, oid: int) -> dict:
    """Всё для листа наряда + событие `tiparit`: открытие листа — передача
    данных пациента лаборатории, след нужен и в истории заказа, и в фише."""
    o, its, evs = await _order_full(oid)
    p = await db.get_patient(o["patient_id"]) or {}
    who = (await prefs())["who"]
    lab = await db.lab_get(o["lab_id"]) if o["lab_id"] else None
    actor, aid = _who(me)
    shown = "nume" if who == "name" else "nr. fișă"
    await db.lab_order_write(oid, events=[{"kind": "tiparit", "on_date": today().isoformat(),
                                           "note": _short(f"{o['lab']} · pacient: {shown}", 200),
                                           "data": {"who": who, "lab_id": o["lab_id"]},
                                           "actor": actor, "actor_id": aid}])
    await db.log_event(o["patient_id"], "lab_print",
                       _short(f"Laborator: fișa comenzii nr {o['nr']} tipărită pentru {o['lab']}", 190),
                       actor=actor)
    return {"order": o, "items": its, "patient": p, "who": who, "lab": lab,
            "fisa": (p.get("file_no") or "").strip() or str(o["patient_id"])}


# ---------- закон 195: копия данных пациента ----------

async def export_rows(pid: int) -> list:
    """Заказы пациента словами — для выгрузки по 195-му (та же таблица, что
    держит фишу от стирания)."""
    orders = await db.lab_orders_rows(pid)
    ids = [o["id"] for o in orders]
    items, events = await db.lab_items(ids), await db.lab_events(ids)
    out = []
    for o in reversed(orders):
        evs = events.get(o["id"], [])
        _, undone, _ = replay(evs)
        out.append({
            "nr": o["nr"], "laborator": o["lab"], "medic": o["doctor"],
            "stare": LAB_STATUS_LABEL.get(o["status"], o["status"]), "etapa": o["stage"],
            "trimis": o["sent_on"], "termen": o["due_on"], "primit": o["received_on"],
            "finalizat": o["done_on"], "urgent": bool(o["urgent"]),
            "amprenta": LAB_IMPRESSION.get(o["impression"], ""), "indicatii": o["note"],
            "lucrari": [{"lucrare": it["work"], "material": it["material"], "culoare": it["shade"],
                         "dinti": _teeth_list(it["teeth"]), "cantitate": it["qty"]}
                        for it in items.get(o["id"], [])],
            "istoric": [{"pas": LAB_EVENT_LABEL.get(e["kind"], e["kind"]), "data": e.get("on_date"),
                         "termen": e.get("due_on"), "cauza": LAB_CAUSE.get(e.get("cause") or "", ""),
                         "plateste": LAB_PAYER.get(e.get("payer") or "", ""), "nota": e.get("note") or "",
                         "cine": e.get("actor") or "", "anulat": e["id"] in undone,
                         "la": e["at"].isoformat() if isinstance(e["at"], datetime) else e["at"]}
                        for e in evs],
        })
    return out
