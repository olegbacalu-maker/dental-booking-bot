"""Статистика клиники: визиты, неявки, загрузка кресел, деньги за период.

⚠️ Считается здесь, а не в базе: в `db.py` нет ни одного агрегата. Цифры
собираются из дневных выборок и прайса из `clinic.json`, поэтому «выручка» —
это оценка по прайсу, а не бухгалтерия. Когда появятся настоящие деньги
(оплаты, долги), у модуля появится свой repository, и вот тогда SQL.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ... import db
from ... import engine as eng
from ...core.auth import _guard
from ...core.layout import _shell
from ...core.visits import _parse_date

router = APIRouter()


def _fmt_mdl(x: int) -> str:
    return f"{x:,}".replace(",", " ") + " MDL"


@router.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(
    request: Request,
    from_q: str = Query("", alias="from"),
    to_q: str = Query("", alias="to"),
):
    if (deny := _guard(request)) is not None:
        return deny
    today = datetime.now(eng.TZ).date()
    d1 = _parse_date(from_q) if from_q else today - timedelta(days=6)
    d2 = _parse_date(to_q) if to_q else today
    if d2 < d1:
        d1, d2 = d2, d1
    start = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    end = datetime(d2.year, d2.month, d2.day, tzinfo=eng.TZ) + timedelta(days=1)
    rows = await db.day_appointments(start, end)
    appts = [r for r in rows if r["source"] != "note"]
    act = [r for r in appts if r["status"] != "cancelled"]

    n_bot = sum(1 for r in act if r["source"] == "bot")
    n_man = len(act) - n_bot
    # «пришли» = завершённые + сидящие в кресле прямо сейчас
    n_done = sum(1 for r in act if r["status"] in ("done", "arrived"))
    n_noshow = sum(1 for r in act if r["status"] == "noshow")
    n_cancel = len(appts) - len(act)
    n_rem = sum(1 for r in appts if r["reminded_day"])
    def _price(r) -> int:
        """Цена: по стабильному service_id (не зависит от языка/переименований),
        для легаси-строк — по подписи."""
        sid = r.get("service_id")
        if sid and sid in eng.SERVICE_PRICE_BY_ID:
            return eng.SERVICE_PRICE_BY_ID[sid]
        return eng.SERVICE_PRICE.get(r["service"], 0)

    loss = sum(_price(r) for r in act if r["status"] == "noshow")
    bot_value = sum(_price(r) for r in act if r["source"] == "bot")

    def _tile(val, label: str, cls: str = "", ico: str = "") -> str:
        """Плитка периода. Структура ТА ЖЕ, что на дашборде: иначе flex кладёт
        подпись сбоку от числа, а не под ним (долг разметки с v1.5.0)."""
        icon = (f"<span class='ico' style='background:var(--teal-soft)'>{ico}</span>"
                if ico else "")
        return (f"<div class='tile {cls}'>{icon}"
                f"<div><b>{val}</b><span>{label}</span></div></div>")

    tiles = (
        "<div class='tiles'>"
        + _tile(len(act), "programări", ico="📅")
        + _tile(n_bot, "🤖 prin bot")
        + _tile(n_man, "✍️ recepție")
        + _tile(n_done, "🟦 au venit")
        + _tile(n_noshow, f"neprezentări<br>≈ {_fmt_mdl(loss)}", cls="bad")
        + _tile(n_cancel, "anulate")
        + _tile(n_rem, "🔔 remindere")
        + _tile(f"≈ {_fmt_mdl(bot_value)}", "valoare adusă de bot")
        + "</div>"
    )

    # загрузка врачей: занятые МИНУТЫ / рабочие минуты врача за период (v1.8.0 —
    # при разных длительностях считать «в штуках слотов» стало бессмысленно)
    days = [d1 + timedelta(days=i) for i in range((d2 - d1).days + 1)]
    doc_rows = []
    for dk, name in eng.DOCTORS.items():
        # по стабильному id (v1.7.1): переименование врача не обнуляет историю
        mine = [r for r in act if r.get("doctor_id") == dk
                or (not r.get("doctor_id") and r["doctor"] == name)]
        off = not eng.DOCTOR_META.get(dk, {}).get("active", True)
        if off and not mine:
            continue  # выключенный врач без записей за период — не мусорим нулями
        ns = sum(1 for r in mine if r["status"] == "noshow")
        cap_min = sum(eng.work_minutes(dk, day) for day in days)
        busy_min = sum(int(r.get("duration_min") or 60) for r in mine)
        pct = round(100 * busy_min / cap_min) if cap_min else 0
        doc_rows.append(
            f"<tr><td>{html.escape(name)}"
            f"{' <small style=\"color:var(--text3)\">· inactiv</small>' if off else ''}</td>"
            f"<td>{len(mine)}</td><td>{ns}</td>"
            f"<td style='min-width:160px'>{pct}%<div class='statbar'><div style='width:{min(pct,100)}%'></div></div></td></tr>"
        )
    doctors_tbl = ("<h2>Medici</h2><table class='list'>"
                   "<tr><th>Medic</th><th>Programări</th><th>Neprezentări</th><th>Ocupare</th></tr>"
                   + "".join(doc_rows) + "</table>")

    # группировка по service_id: RU- и RO-запись одной услуги = одна строка
    # отчёта (раньше язык пациента раздваивал услугу и делил её выручку)
    svc_count: dict[str, dict] = {}
    for r in act:
        sid = r.get("service_id")
        if sid and sid in eng.SERVICES:
            key, label = sid, eng.SERVICES[sid]["ro"]
        else:
            key, label = "lbl:" + r["service"], r["service"]
        ent = svc_count.setdefault(key, {"label": label, "cnt": 0, "val": 0})
        ent["cnt"] += 1
        ent["val"] += _price(r)
    svc_rows = "".join(
        f"<tr><td>{html.escape(ent['label'])}</td><td>{ent['cnt']}</td>"
        f"<td>≈ {_fmt_mdl(ent['val'])}</td></tr>"
        for ent in sorted(svc_count.values(), key=lambda x: -x["cnt"])[:8]
    )
    services_tbl = ("<h2>Servicii</h2><table class='list'>"
                    "<tr><th>Serviciu</th><th>Programări</th><th>≈ Valoare</th></tr>"
                    + svc_rows + "</table>")

    q7 = (today - timedelta(days=6)).isoformat()
    q30 = (today - timedelta(days=29)).isoformat()
    m1 = today.replace(day=1).isoformat()
    nav = (
        "<div class='nav'>"
        f"<b>{d1.strftime('%d.%m.%Y')} — {d2.strftime('%d.%m.%Y')}</b>"
        f"<a href='/admin/stats?from={today.isoformat()}&to={today.isoformat()}'>Azi</a>"
        f"<a href='/admin/stats?from={q7}&to={today.isoformat()}'>7 zile</a>"
        f"<a href='/admin/stats?from={m1}&to={today.isoformat()}'>Luna asta</a>"
        f"<a href='/admin/stats?from={q30}&to={today.isoformat()}'>30 zile</a>"
        f"<form class='dpickf' method='get' action='/admin/stats' style='display:inline-flex;gap:4px'>"
        f"<input class='dpick' type='date' name='from' value='{d1.isoformat()}'>"
        f"<input class='dpick' type='date' name='to' value='{d2.isoformat()}'>"
        f"<button class='searchf' style='background:var(--teal);color:#fff;border:none;"
        f"border-radius:var(--r-ctl);height:var(--h-ctl);padding:0 18px;cursor:pointer;"
        f"font-size:14px;font-weight:600'>OK</button></form>"
        f"<a href='/admin/export?from={d1.isoformat()}&to={d2.isoformat()}'>📥 Export CSV</a>"
        f"<a href='/admin'>🏠 Panou</a></div>"
    )
    hint = ("<p class='hint'>Prețurile sunt medii orientative din lista clinicii; "
            "neprezentările = venit pierdut estimat. Notițele nu se numără.</p>")
    return _shell(nav + tiles + doctors_tbl + services_tbl + hint,
                  "statistici · perioadă selectabilă", active="stat")
