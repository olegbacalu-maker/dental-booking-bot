"""Модуль «SMS» админки (S4): отчёт по клиникам, карточка, выгрузка за месяц.

Слово Олега 16.10: «отдельный модуль по клиникам, чтобы я видел, кто сколько
отправил». Одна форма `report()` — на страницу `/admin/sms` и на JSON
`/admin/api/sms` (как `fleet.report`): добавлять данные сюда, обе формы
получают их разом. Сутки — по Кишинёву (sms.day_start), а не UTC.

⛔ Видно «сколько», а не «кому»: ни номеров, ни текстов здесь нет — сервер их
не хранит (sms_messages без таких колонок), показывать нечего по построению.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import config, db, license, sms, smsmd, xlsx

UTC = timezone.utc
PERIODS = ("today", "week", "month", "custom")
LEDGER_LAST = 50

_ACCOUNTS = """SELECT c.id AS cid, c.name, c.idno, s.plan, s.valid_until, s.grace_days, a.*
               FROM sms_accounts a JOIN clinics c ON c.id = a.clinic_id
               LEFT JOIN subscriptions s ON s.clinic_id = c.id
               ORDER BY c.name"""


def period(kind: str, now: datetime, frm: date | None = None, to: date | None = None
           ) -> tuple[datetime, datetime, date, date]:
    """Границы периода → (start UTC, end UTC, день с, день по) по суткам Кишинёва.
    today / week (7 дней по сегодня) / month (календарный) / custom (включительно)."""
    today = sms.local(now).date()
    if kind == "today":
        d1 = d2 = today
    elif kind == "week":
        d1, d2 = today - timedelta(days=6), today
    elif kind == "custom" and frm and to:
        d1, d2 = min(frm, to), max(frm, to)
    else:
        d1, d2 = today.replace(day=1), today
    return sms.day_start(d1), sms.day_start(d2 + timedelta(days=1)), d1, d2


def month_bounds(ym: str, now: datetime) -> tuple[datetime, datetime, date]:
    """«ГГГГ-ММ» → (start, end, первый день); кривое — текущий месяц."""
    try:
        first = datetime.strptime(ym, "%Y-%m").date()
    except (TypeError, ValueError):
        first = sms.local(now).date().replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return sms.day_start(first), sms.day_start(nxt), first


def _counts(con: sqlite3.Connection, cid: str, start: datetime, end: datetime) -> dict:
    s, e = start.strftime(db.TS), end.strftime(db.TS)
    out = {"sent": 0, "delivered": 0, "undelivered": 0, "refused": 0, "pending": 0, "billable": 0}
    for r in con.execute("SELECT state, segments FROM sms_messages WHERE clinic_id=? AND sent_at>=? AND sent_at<?",
                         (cid, s, e)).fetchall():
        out[sms.GROUP[r["state"]]] += 1
        if r["state"] not in (sms.REFUSED, sms.RETRY):
            out["sent"] += 1
        if r["state"] not in sms.REFUNDED:
            out["billable"] += int(r["segments"])     # то, что sms.md выставит в фактуре
    # потрачено = отправки минус возвраты плюс правки сегментов по сообщениям; ручной fix Олега — не расход
    out["spent"] = con.execute(f"SELECT COALESCE(-SUM(delta), 0) FROM sms_ledger WHERE clinic_id=? "
                               f"AND ({sms.SPENT_SQL}) AND at>=? AND at<?", (cid, s, e)).fetchone()[0]
    n, units = con.execute("SELECT count(*), COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=? "
                           "AND reason='pack' AND at>=? AND at<?", (cid, s, e)).fetchone()
    out["packs"], out["pack_units"] = n, units
    return out


def _failures(con: sqlite3.Connection, start: datetime, end: datetime) -> list[dict]:
    """Сбои за период по причинам: статус оператора (9, 10, 11) или код отказа sms.md."""
    s, e = start.strftime(db.TS), end.strftime(db.TS)
    marks = ",".join("?" * 6)
    bad = (sms.UNDELIVERED, sms.FAILED, sms.REJECTED, sms.REFUSED, sms.RETRY, sms.UNANSWERED)
    agg: dict[str, dict] = {}
    for r in con.execute(f"SELECT state, error, clinic_id FROM sms_messages WHERE sent_at>=? AND sent_at<? "
                         f"AND state IN ({marks})", (s, e, *bad)).fetchall():
        reason = r["state"] if r["state"] in (sms.UNDELIVERED, sms.FAILED, sms.REJECTED) else \
            f"{r['state']}: {(r['error'] or '').split(':')[0] or '—'}"
        a = agg.setdefault(reason, {"reason": reason, "count": 0, "clinics": set()})
        a["count"] += 1
        a["clinics"].add(r["clinic_id"])
    out = [{"reason": a["reason"], "count": a["count"], "clinics": len(a["clinics"])} for a in agg.values()]
    out.sort(key=lambda x: (-x["count"], x["reason"]))
    return out


def _name_from(con: sqlite3.Connection, cid: str) -> dict:
    owner = sms.name_owner(con, cid)
    if owner == cid:
        return {"name_from": "", "name_from_name": ""}
    row = con.execute("SELECT name FROM clinics WHERE id=?", (owner,)).fetchone()
    return {"name_from": owner, "name_from_name": row["name"] if row else owner}


def _item(con: sqlite3.Connection, a: sqlite3.Row, start: datetime, end: datetime, now: datetime) -> dict:
    cid = a["cid"]
    last = con.execute("SELECT MAX(sent_at) FROM sms_messages WHERE clinic_id=? AND state NOT IN (?, ?)",
                       (cid, sms.REFUSED, sms.RETRY)).fetchone()[0]
    return {"clinic_id": cid, "clinic": a["name"], "idno": a["idno"] or "", "plan": a["plan"] or "",
            "state": license.state(db.parse_ts(a["valid_until"]), a["grace_days"] or 0, now),
            "enabled": bool(a["enabled"]), "pilot": bool(a["pilot"]), "offered": sms.offered(a),
            "sender": a["sender"], "sender_state": a["sender_state"], "sender_note": a["sender_note"],
            "sender_paper": bool(a["sender_paper_at"]), "sender_paper_file": bool(a["sender_paper_id"]), "sender_until": a["sender_until"],
            "sender_prepaid": a["sender_prepaid"], "from": sms.sender_for(con, cid, now),
            # имя общее на кабинет (26.10): у филиала — главной клиники; '' — своё
            **_name_from(con, cid),
            "balance": sms.balance(con, cid), "daily_cap": a["daily_cap"],
            "used_today": sms.used_today(con, cid, now), "last_sent_at": last, **_counts(con, cid, start, end)}


def report(con: sqlite3.Connection, kind: str = "month", frm: date | None = None, to: date | None = None,
           now: datetime | None = None, with_balance: bool = True) -> dict:
    """Сводка по всем клиникам со счётом SMS за период; итоги; долг против баланса sms.md;
    очередь имён; сбои по причинам. Одна форма на страницу и на JSON."""
    now = now or datetime.now(UTC)
    kind = kind if kind in PERIODS else "month"
    start, end, d1, d2 = period(kind, now, frm, to)
    items = [_item(con, a, start, end, now) for a in con.execute(_ACCOUNTS).fetchall()]
    items.sort(key=lambda i: (-i["spent"], -i["sent"], i["clinic"]))
    keys = ("sent", "delivered", "undelivered", "refused", "pending", "billable", "spent", "packs", "pack_units", "balance")
    totals = {k: sum(i[k] for i in items) for k in keys}
    owed = sms.owed(con)
    cost = sms._cents(config.SMSMD_SEGMENT_COST) or 0
    balance, error = None, ""
    if with_balance and smsmd.enabled():
        try:
            balance = smsmd.balance()
        except (smsmd.Unanswered, smsmd.Refused) as e:
            error = str(e)
    queue = [i for i in items if i["sender_state"] in (sms.S_REQUESTED, sms.S_SUBMITTED)]
    return {"period": {"kind": kind, "from": d1.isoformat(), "to": d2.isoformat(),
                       "start": start.strftime(db.TS), "end": end.strftime(db.TS)},
            "clinics": items, "totals": totals,
            "owed": owed, "owed_mdl": f"{owed * cost / 100:.2f}", "segment_cost": config.SMSMD_SEGMENT_COST,
            "smsmd_balance": balance, "smsmd_error": error,
            "queue": queue, "failures": _failures(con, start, end),
            "configured": smsmd.enabled(), "offered_all": config.SMS_OFFERED,
            "packs": sms.packs(), "name_price": config.SMS_NAME_PRICE,
            "counts": {"clinics": len(items), "queue": len(queue), "enabled": sum(i["enabled"] for i in items)}}


def clinic_detail(con: sqlite3.Connection, cid: str, now: datetime | None = None) -> dict | None:
    """Карточка клиники › SMS: счёт, расход по дням текущего месяца, движения журнала.
    None — счёта ещё нет (программа не спрашивала, Олег не трогал)."""
    now = now or datetime.now(UTC)
    a = con.execute(_ACCOUNTS.replace("ORDER BY c.name", "") + " WHERE c.id=?" if False else
                    """SELECT c.id AS cid, c.name, c.idno, s.plan, s.valid_until, s.grace_days, a.*
                       FROM sms_accounts a JOIN clinics c ON c.id = a.clinic_id
                       LEFT JOIN subscriptions s ON s.clinic_id = c.id WHERE c.id=?""", (cid,)).fetchone()
    if a is None:
        return None
    start, end, first = month_bounds(sms.local(now).strftime("%Y-%m"), now)
    item = _item(con, a, start, end, now)
    days: dict[str, dict] = {}
    for r in con.execute("SELECT sent_at, state, segments FROM sms_messages WHERE clinic_id=? AND sent_at>=? "
                         "AND sent_at<? ORDER BY sent_at", (cid, start.strftime(db.TS), end.strftime(db.TS))).fetchall():
        d = sms.local(db.parse_ts(r["sent_at"]) or now).date().isoformat()
        row = days.setdefault(d, {"day": d, "sent": 0, "delivered": 0, "undelivered": 0, "refused": 0,
                                  "pending": 0, "segments": 0})
        if r["state"] not in (sms.REFUSED, sms.RETRY):
            row["sent"] += 1
        row[sms.GROUP[r["state"]]] += 1
        if r["state"] not in sms.REFUNDED:
            row["segments"] += int(r["segments"])
    ledger = [dict(r) for r in con.execute(
        """SELECT l.*, p.reference FROM sms_ledger l LEFT JOIN payments p ON p.id = l.payment_id
           WHERE l.clinic_id=? ORDER BY l.id DESC LIMIT ?""", (cid, LEDGER_LAST)).fetchall()]
    return {**item, "month": first.isoformat()[:7], "by_day": sorted(days.values(), key=lambda x: x["day"]),
            "ledger": ledger, "suggest": sms.suggest(a["name"]),
            # личный текст клиники (S6) — форма карточки
            "custom_ro": a["custom_ro"], "custom_ru": a["custom_ru"], "custom_on": bool(a["custom_on"])}


EXPORT_HEADER = ["Clinica", "IDNO", "Nume expeditor", "SMS trimise", "Livrate", "Nelivrate", "Refuzate",
                 "Segmente", "Segmente facturabile sms.md", "Cumparate (SMS)", "Sold la sfarsitul lunii"]
EXPORT_WIDTHS = [28, 16, 16, 12, 10, 11, 10, 11, 24, 16, 20]


def export(con: sqlite3.Connection, ym: str, now: datetime | None = None) -> tuple[str, bytes]:
    """Выгрузка за месяц по клиникам для сверки с фактурой sms.md → (имя файла, байты xlsx).
    «Segmente facturabile» — без 10/11 и отказов: то, что sms.md выставит нам."""
    now = now or datetime.now(UTC)
    start, end, first = month_bounds(ym, now)
    rows = []
    tot = [0] * 8
    for a in con.execute(_ACCOUNTS).fetchall():
        c = _counts(con, a["cid"], start, end)
        if not any(c.values()):
            continue
        bal_end = con.execute("SELECT COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=? AND at<?",
                              (a["cid"], end.strftime(db.TS))).fetchone()[0]
        vals = [c["sent"], c["delivered"], c["undelivered"], c["refused"], c["spent"], c["billable"],
                c["pack_units"], bal_end]
        tot = [t + v for t, v in zip(tot, vals)]
        rows.append([a["name"], a["idno"] or "", a["sender_live"] or "", *vals])
    rows.append(["TOTAL", "", "", *tot])
    return f"dentpilot-sms-{first:%Y-%m}.xlsx", xlsx.book(EXPORT_HEADER, rows, EXPORT_WIDTHS, sheet_name=f"SMS {first:%Y-%m}")
