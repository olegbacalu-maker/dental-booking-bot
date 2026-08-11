"""Аналитика клиники: KPI со сравнением периодов, график по дням, источники,
загрузка, врачи, услуги, последние события. Раздел директора (PERM_MONEY).

⚠️ Считается здесь, а не в базе: в `db.py` нет ни одного агрегата. Цифры
собираются из дневных выборок и прайса из `clinic.json`, поэтому «выручка» —
это оценка по прайсу, а не бухгалтерия. Когда появятся настоящие деньги
(оплаты, долги), у модуля появится свой repository, и вот тогда SQL.

Пересобран 08-06 по макету Олега. Чего из макета тут НЕТ и почему:
- «Surse: Google / Instagram» — программа не знает таких источников; пациент
  приходит из Telegram, от регистратуры или через веб-чат. Рисовать Google —
  показать директору выдуманное число, по которому он решит про рекламу.
- «Ocuparea cabinetelor» — кабинетов в модели нет, `room` у врача — подпись.
- «Bună ziua, Liviu!» — приветствие живёт в топбаре (чип вошедшего), а не в
  заголовке раздела.

Каждый период сравнивается С ТАКИМ ЖЕ ПО ДЛИНЕ куском сразу перед ним: у
недели это прошлая неделя, у «сегодня» — вчера. Сравнение с «прошлым месяцем»
для произвольного периода врало бы — периоды разной длины несравнимы.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ... import db
from ... import engine as eng
from ...core.auth import PERM_MONEY, require
from ...core.charts import donut, gauge, line_days, spark
from ...core.layout import _ic, _shell, tg_configured
from ...core.visits import _parse_date
from . import casa

router = APIRouter()


def _fmt_mdl(x: int) -> str:
    return f"{x:,}".replace(",", " ") + " MDL"


def _price(r) -> int:
    """Цена: по стабильному service_id (не зависит от языка/переименований),
    для легаси-строк — по подписи."""
    sid = r.get("service_id")
    if sid and sid in eng.SERVICE_PRICE_BY_ID:
        return eng.SERVICE_PRICE_BY_ID[sid]
    return eng.SERVICE_PRICE.get(r["service"], 0)


def _agg(rows: list) -> dict:
    """Все цифры одного периода — из одной выборки, одним проходом."""
    appts = [r for r in rows if r["source"] != "note"]
    act = [r for r in appts if r["status"] != "cancelled"]
    return {
        "total": len(act),
        "bot": sum(1 for r in act if r["source"] == "bot"),
        "man": sum(1 for r in act if r["source"] == "manual"),
        "web": sum(1 for r in act if r["source"] not in ("bot", "manual")),
        # «пришли» = завершённые + сидящие в кресле прямо сейчас
        "done": sum(1 for r in act if r["status"] in ("done", "arrived")),
        "noshow": sum(1 for r in act if r["status"] == "noshow"),
        "cancel": len(appts) - len(act),
        "rem": sum(1 for r in appts if r["reminded_day"]),
        "value": sum(_price(r) for r in act if r["status"] != "noshow"),
        "loss": sum(_price(r) for r in act if r["status"] == "noshow"),
        "bot_value": sum(_price(r) for r in act if r["source"] == "bot"),
        "act": act,
    }


def _period_label(span: int) -> str:
    """Прошлый период — ПО ИМЕНИ, а не «perioada trecută»: безымянное сравнение
    уже дважды озадачивало Олега (загрузка 3%, «vs. perioada trecută (0)»)."""
    if span == 1:
        return "față de ziua precedentă"
    if span == 7:
        return "față de săptămâna trecută"
    if 28 <= span <= 31:
        return "față de luna trecută"
    return f"față de precedentele {span} zile"


def _trend(cur: int, prev: int, bad_up: bool = False,
           label: str = "față de perioada trecută") -> str:
    """Сравнение с предыдущим периодом той же длины. От нуля процентов нет:
    «+∞%» — не цифра, а шум."""
    if cur == prev:
        return f"<span class='trend'>neschimbat {label}</span>"
    if not prev:
        cls = "dn" if bad_up else "up"
        return (f"<span class='trend'><span class='{cls}'>+{cur}</span>"
                f" {label} (atunci 0)</span>")
    pct = (cur - prev) * 100 / prev
    cls = ("dn" if bad_up else "up") if pct > 0 else ("up" if bad_up else "dn")
    arrow = _ic("caret-u") if pct > 0 else _ic("caret-d")
    return (f"<span class='trend'><span class='{cls}'>{arrow} {abs(pct):.0f}%</span>"
            f" {label}</span>")


def _trend_money(cur: int, prev: int, label: str) -> str:
    """Деньги сравниваем В ДЕНЬГАХ, не в процентах: директору «+2 550 MDL»
    говорит больше, чем «+100%», а нулевая прошлая неделя не ломает формулу."""
    if cur == prev:
        return f"<span class='trend'>neschimbat {label}</span>"
    diff = cur - prev
    cls, arrow = ("up", _ic("caret-u")) if diff > 0 else ("dn", _ic("caret-d"))
    sign = "+" if diff > 0 else "−"
    return (f"<span class='trend'><span class='{cls}'>{arrow} {sign}"
            f"{_fmt_mdl(abs(diff))}</span> {label}</span>")


@router.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(
    request: Request,
    from_q: str = Query("", alias="from"),
    to_q: str = Query("", alias="to"),
):
    # деньги — единственное, что закрыто от врача и регистратуры (решение
    # Олега 08-06); проверка ЗДЕСЬ, а не только в меню: адрес набирается руками
    if (deny := require(request, PERM_MONEY)) is not None:
        return deny
    e = html.escape
    today = datetime.now(eng.TZ).date()
    d1 = _parse_date(from_q) if from_q else today - timedelta(days=6)
    d2 = _parse_date(to_q) if to_q else today
    if d2 < d1:
        d1, d2 = d2, d1
    days = [d1 + timedelta(days=i) for i in range((d2 - d1).days + 1)]
    span = len(days)

    # период + такой же по длине кусок ПЕРЕД ним — одним запросом
    p1 = d1 - timedelta(days=span)
    start_all = datetime(p1.year, p1.month, p1.day, tzinfo=eng.TZ)
    end = datetime(d2.year, d2.month, d2.day, tzinfo=eng.TZ) + timedelta(days=1)
    all_rows = await db.day_appointments(start_all, end)
    split = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    cur = _agg([r for r in all_rows if r["starts_at"] >= split])
    prev = _agg([r for r in all_rows if r["starts_at"] < split])
    plabel = _period_label(span)

    by_day: dict[date, int] = {x: 0 for x in days}
    for r in cur["act"]:
        by_day[r["starts_at"].astimezone(eng.TZ).date()] += 1
    day_vals = [by_day[x] for x in days]

    # ---- шесть KPI макета + деньги (label, cur, prev, ico, tone, bad_up) ----
    kpis = [
        ("Programări", cur["total"], prev["total"], _ic("cal"), "var(--green)", False),
        ("Prin bot", cur["bot"], prev["bot"], _ic("bot"), "var(--teal-d)", False),
        ("Recepție", cur["man"], prev["man"], _ic("headset"), "var(--blue)", False),
        ("Au venit", cur["done"], prev["done"], _ic("checkin"), "var(--violet)", False),
        ("Anulate", cur["cancel"], prev["cancel"], _ic("ban"), "var(--red)", True),
        ("Remindere", cur["rem"], prev["rem"], _ic("bell"), "var(--amber)", False),
    ]
    # спарклайн каждой плитки — её же ряд по дням текущего периода
    per_day: dict[str, list[int]] = {k: [0] * span for k, *_ in kpis}
    idx = {x: i for i, x in enumerate(days)}
    for r in cur["act"]:
        i = idx[r["starts_at"].astimezone(eng.TZ).date()]
        per_day["Programări"][i] += 1
        if r["source"] == "bot":
            per_day["Prin bot"][i] += 1
        elif r["source"] == "manual":
            per_day["Recepție"][i] += 1
        if r["status"] in ("done", "arrived"):
            per_day["Au venit"][i] += 1
        if r["reminded_day"]:
            per_day["Remindere"][i] += 1
    canc = [r for r in all_rows if r["starts_at"] >= split
            and r["source"] != "note" and r["status"] == "cancelled"]
    for r in canc:
        per_day["Anulate"][idx[r["starts_at"].astimezone(eng.TZ).date()]] += 1

    # Telegram заморожен (tg_configured): у клиники без бота нет ни канала
    # «Prin bot», ни напоминаний — плитки и донат источников прячутся.
    # per_day выше собирается по ПОЛНОМУ списку намеренно: у клиники со
    # снятым токеном исторические бот-записи не должны ронять цикл KeyError-ом
    tg_ui = tg_configured()
    if not tg_ui:
        kpis = [k for k in kpis if k[0] not in ("Prin bot", "Remindere")]

    soft = {"var(--green)": "var(--green-soft)", "var(--teal-d)": "var(--teal-soft)",
            "var(--blue)": "var(--blue-soft)", "var(--violet)": "var(--violet-soft)",
            "var(--red)": "var(--red-soft)", "var(--amber)": "var(--amber-soft)"}
    tiles = "<div class='tiles'>" + "".join(
        f"<div class='tile sp{' bad' if lbl == 'Anulate' else ''}'>"
        f"<span class='ico' style='background:{soft[tone]};color:{tone}'>{ico}</span>"
        f"<div><b data-count='{val}'>{val}</b><span>{lbl}</span>"
        f"{_trend(val, pv, bad, plabel)}</div>{spark(per_day[lbl], tone)}</div>"
        for lbl, val, pv, ico, tone, bad in kpis) + "</div>"

    # ---- график по дням ----
    lbl_days = [x.strftime("%d.%m") for x in days]
    present_pct = round(100 * cur["done"] / cur["total"]) if cur["total"] else 0
    chart_card = f"""<div class='fcard an-chart'>
<h3>Programări pe zile <small>· {d1.strftime('%d.%m')} — {d2.strftime('%d.%m.%Y')}</small></h3>
{line_days(lbl_days, day_vals, 'var(--teal)')}
<div class='an-foot'>
  <div><span>Total programări</span><b>{cur['total']}</b>{_trend(cur['total'], prev['total'], label=plabel)}</div>
  <div><span>Rata de prezență</span><b>{present_pct}%</b>
    <div class='statbar'><div style='width:{present_pct}%'></div></div></div>
  <div><span>Neprezentări</span><b>{cur['noshow']}</b>
    <small>≈ {_fmt_mdl(cur['loss'])} pierdut</small></div>
</div></div>"""

    # ---- источники: только те, что программа ЗНАЕТ ----
    src_parts = [("Telegram", cur["bot"], "var(--teal)"),
                 ("Recepție", cur["man"], "var(--blue)"),
                 ("Web-chat", cur["web"], "var(--violet)")]
    legend = "".join(
        f"<div class='an-src'><i style='background:{color}'></i>{e(lbl)}"
        f"<b>{val}</b><small>{round(100 * val / cur['total']) if cur['total'] else 0}%</small></div>"
        for lbl, val, color in src_parts)
    src_card = ((f"<div class='fcard'><h3>Surse programări</h3><div class='an-donut'>"
                 f"{donut([(l, v, c) for l, v, c in src_parts], 'Total')}"
                 f"<div class='an-legend'>{legend}</div></div></div>")
                if tg_ui else "")  # один источник — не разбивка, а тавтология

    # ---- средняя загрузка + деньги ----
    cap_all = busy_all = 0
    doc_rows = []
    for dk, name in eng.DOCTORS.items():
        mine = [r for r in cur["act"] if r.get("doctor_id") == dk
                or (not r.get("doctor_id") and r["doctor"] == name)]
        off = not eng.DOCTOR_META.get(dk, {}).get("active", True)
        if off and not mine:
            continue   # выключенный врач без записей за период — не мусорим нулями
        ns = sum(1 for r in mine if r["status"] == "noshow")
        came = sum(1 for r in mine if r["status"] in ("done", "arrived"))
        cap = sum(eng.work_minutes(dk, day) for day in days)
        busy = sum(int(r.get("duration_min") or 60) for r in mine)
        pct = round(100 * busy / cap) if cap else 0
        if not off:
            cap_all += cap
            busy_all += busy
        pres = round(100 * came / len(mine)) if mine else 0
        doc_rows.append((name, off, len(mine), came, pres, pct))
    avg_pct = round(100 * busy_all / cap_all) if cap_all else 0
    # период называется ЦИФРАМИ прямо на карточке: «media pe perioadă» без дат
    # уже озадачила Олега — 3% за неделю выглядят ошибкой рядом с 86% за день
    gauge_card = (f"<div class='fcard an-gauge'><h3>Grad de ocupare</h3>"
                  f"{gauge(avg_pct, 'var(--teal)')}"
                  f"<small>media {d1.strftime('%d.%m')}–{d2.strftime('%d.%m')} "
                  f"({len(days)} zile) · minute ocupate din minutele de lucru "
                  f"ale medicilor activi</small></div>")
    # деньги: период в заголовке, суффикс « MDL» едет с каждым кадром счётчика
    # (без data-suffix последний кадр показывал голое «2550» — скрин Олега 08-07)
    money_card = (f"<div class='fcard an-money'>"
                  f"<h3>Venituri estimate <small>· {d1.strftime('%d.%m')}–"
                  f"{d2.strftime('%d.%m')}</small></h3>"
                  f"<b data-count='{cur['value']}' data-suffix=' MDL'>"
                  f"{_fmt_mdl(cur['value'])}</b>"
                  f"{_trend_money(cur['value'], prev['value'], plabel)}"
                  f"<small>după lista de prețuri · nu e contabilitate"
                  + (f" · botul a adus ≈ {_fmt_mdl(cur['bot_value'])}"
                     if tg_ui else "")
                  + "</small></div>")
    # выручка ЗА СЕГОДНЯ — всегда про сегодня, какой бы период ни был выбран
    # сверху (идея Олега 08-07: пустое место под карточкой периода)
    y0 = today - timedelta(days=1)
    t_rows = await db.day_appointments(
        datetime(y0.year, y0.month, y0.day, tzinfo=eng.TZ),
        datetime(today.year, today.month, today.day, tzinfo=eng.TZ)
        + timedelta(days=1))
    t_split = datetime(today.year, today.month, today.day, tzinfo=eng.TZ)
    tv = _agg([r for r in t_rows if r["starts_at"] >= t_split])["value"]
    yv = _agg([r for r in t_rows if r["starts_at"] < t_split])["value"]
    azi_card = (f"<div class='fcard an-money'>"
                f"<h3>Venituri azi <small>· {today.strftime('%d.%m')}</small></h3>"
                f"<b data-count='{tv}' data-suffix=' MDL'>{_fmt_mdl(tv)}</b>"
                f"{_trend_money(tv, yv, 'față de ieri')}"
                f"<small>estimare pe ziua curentă · după lista de prețuri</small>"
                f"</div>")
    # ---- Încasări: НАСТОЯЩИЕ деньги (модуль финансов, 08-07) ----
    # оценка по прайсу выше — прогноз; здесь — что реально записала рецепция
    pays_period = await db.payments_range(start_all, end)
    inc_cur = sum(p["amount_mdl"] for p in pays_period if p["at"] >= split)
    inc_prev = sum(p["amount_mdl"] for p in pays_period if p["at"] < split)
    by_m = {m: sum(p["amount_mdl"] for p in pays_period
                   if p["at"] >= split and p["method"] == m)
            for m in db.PAY_METHODS}
    inc_azi = sum(p["amount_mdl"] for p in await db.payments_range(
        t_split, t_split + timedelta(days=1)))
    incasari_card = (
        f"<div class='fcard an-money'><h3>Încasări "
        f"<small>· bani reali, {d1.strftime('%d.%m')}–{d2.strftime('%d.%m')}"
        f"</small></h3>"
        f"<b data-count='{inc_cur}' data-suffix=' MDL'>{_fmt_mdl(inc_cur)}</b>"
        f"{_trend_money(inc_cur, inc_prev, plabel)}"
        f"<small>azi: {_fmt_mdl(inc_azi)} · {_ic('cash')} {_fmt_mdl(by_m['numerar'])} · "
        f"{_ic('card')} {_fmt_mdl(by_m['card'])} · {_ic('bank')} {_fmt_mdl(by_m['transfer'])} · "
        f"plăți înregistrate la recepție</small>"
        # лист для сверки ящика в конце смены; ведёт на СЕГОДНЯ, а не на конец
        # выбранного периода: касса сходится за смену, а не за произвольное окно
        f"<a class='ag-all' href='/admin/casa'>{_ic('print')} Raport de casă (azi) ›</a>"
        f"</div>")

    # ---- врачи ----
    rows_html = "".join(
        f"<tr><td>{e(name)}"
        + (" <small style='color:var(--text3)'>· inactiv</small>" if off else "")
        + f"</td><td>{n}</td><td>{came}</td>"
        f"<td><div class='an-bar'><span>{pres}%</span>"
        f"<div class='statbar'><div style='width:{pres}%'></div></div></div></td>"
        f"<td><div class='an-bar'><span>{pct}%</span>"
        f"<div class='statbar'><div style='width:{min(pct, 100)}%'></div></div></div></td></tr>"
        for name, off, n, came, pres, pct in
        sorted(doc_rows, key=lambda x: -x[5]))
    doctors_tbl = ("<div class='fcard'><h3>Performanța medicilor</h3>"
                   "<table class='list an-tbl'>"
                   "<tr><th>Medic</th><th>Programări</th><th>Au venit</th>"
                   "<th>Rata prezenței</th><th>Ocupare</th></tr>"
                   + rows_html + "</table></div>")

    # ---- услуги: группировка по service_id, RU и RO — одна строка ----
    svc_count: dict[str, dict] = {}
    for r in cur["act"]:
        sid = r.get("service_id")
        if sid and sid in eng.SERVICES:
            key, label = sid, eng.SERVICES[sid]["ro"]
        else:
            key, label = "lbl:" + r["service"], r["service"]
        ent = svc_count.setdefault(key, {"label": label, "cnt": 0, "val": 0})
        ent["cnt"] += 1
        ent["val"] += _price(r)
    top_svc = sorted(svc_count.values(), key=lambda x: -x["cnt"])[:8]
    max_cnt = top_svc[0]["cnt"] if top_svc else 1
    svc_rows = "".join(
        f"<div class='an-svc'><div class='an-svc-t'><b>{e(s['label'])}</b>"
        f"<span>{s['cnt']} prog. · ≈ {_fmt_mdl(s['val'])}</span></div>"
        f"<div class='statbar'><div style='width:{round(100 * s['cnt'] / max_cnt)}%'></div></div></div>"
        for s in top_svc) or "<p class='hint'>— încă fără programări —</p>"
    services_card = f"<div class='fcard'><h3>Top servicii</h3>{svc_rows}</div>"

    # ---- последние события картотеки (журнал уже пишет ИМЯ вошедшего) ----
    acts = await db.recent_activity(10)
    act_rows = []
    for a in acts:
        at = a["at"].astimezone(eng.TZ) if a["at"] else None
        who = "bot" if a["actor"] == "bot" else f"{e(a['actor'] or 'recepție')}"
        link = (f"<a href='/admin/patient/{a['patient_id']}'>{e(a['name'] or '—')}</a>"
                if a["patient_id"] else e(a["name"] or "—"))
        act_rows.append(
            f"<div class='an-act'><div class='an-act-b'><b>{e(a['text'])}</b>"
            f"<small>{link} · {who}</small></div>"
            f"<span>{at.strftime('%d.%m %H:%M') if at else ''}</span></div>")
    activity_card = ("<div class='fcard'><h3>Activitate recentă</h3>"
                     + ("".join(act_rows) or "<p class='hint'>— încă nimic —</p>")
                     + "</div>")

    # ---- периоды ----
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
        f"<a href='/admin/export?from={d1.isoformat()}&to={d2.isoformat()}'>{_ic('download')} Export CSV</a>"
        f"<a href='/admin'>{_ic('home')} Panou</a></div>"
    )
    hint = ("<p class='hint'>Prețurile sunt medii orientative din lista clinicii; "
            "neprezentările = venit pierdut estimat. Notițele nu se numără. "
            "Secțiunea este vizibilă doar directorului.</p>")
    body = (nav + tiles
            + "<div class='an-grid'>"
            + f"<div class='an-main'>{chart_card}{doctors_tbl}</div>"
            + f"<div class='an-side'>{src_card}{gauge_card}{incasari_card}"
              f"{money_card}{azi_card}</div>"
            + "</div>"
            + "<div class='an-grid2'>"
            + services_card + activity_card
            + "</div>"
            + hint)
    return _shell(body, "statistici · perioadă selectabilă · doar director",
                  active="stat")


@router.get("/admin/casa", response_class=HTMLResponse)
async def admin_casa(request: Request, d: str = ""):
    """Печатный отчёт кассы за день. `?d=YYYY-MM-DD`, по умолчанию сегодня.

    За `PERM_MONEY`, как и вся страница статистики: это выручка клиники, а не
    долг конкретного пациента (тот виден любой роли — и в фише, и в списке).
    Проверка здесь, а не только в ссылке: адрес набирается руками.
    """
    if (deny := require(request, PERM_MONEY)) is not None:
        return deny
    day = _parse_date(d) if d else datetime.now(eng.TZ).date()
    start = datetime(day.year, day.month, day.day, tzinfo=eng.TZ)
    rows = await db.payments_day(start, start + timedelta(days=1))
    return HTMLResponse(casa.render(day, rows))
