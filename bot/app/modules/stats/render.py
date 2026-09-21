"""Разметка старой страницы аналитики — из той же модели, что уезжает в JSON.

Считает `model.py`, рисует этот файл. Разделение сделано ради C15: до него
маршрут был 291 строкой, где арифметика жила внутри f-строк, и отдать те же
цифры React-экрану значило посчитать их ВТОРОЙ раз. Цифры при этом выглядят
правдоподобно всегда — расхождение двух счётчиков не видно ни на одном экране.

⛔ Здесь нет ни одного расчёта: всё, что похоже на вычисление, — ошибка места.
"""
from __future__ import annotations

import html

from ...core.charts import donut, gauge, line_days, spark
from ...core.layout import _ic


def _trend(t: dict) -> str:
    """Сравнение с прошлым периодом. Тон берётся из `dir`, а не из знака
    числа: рост неявок — стрелка вверх и КРАСНЫЙ."""
    if not t["dir"]:
        return f"<span class='trend'>neschimbat {t['label']}</span>"
    ico = f"{_ic(t['icon'])} " if t["icon"] else ""
    return (f"<span class='trend'><span class='{t['dir']}'>{ico}{t['value']}</span>"
            f" {t['label']}{t['note']}</span>")


def _tiles(tiles: list) -> str:
    return "<div class='tiles'>" + "".join(
        f"<div class='tile sp{' bad' if t['bad'] else ''}'>"
        f"<span class='ico' style='background:{t['soft']};color:{t['tone']}'>"
        f"{_ic(t['icon'])}</span>"
        f"<div><b data-count='{t['value']}'>{t['value']}</b>"
        f"<span>{t['label']}</span>{_trend(t['trend'])}</div>"
        f"{spark(t['series'], t['tone'])}</div>"
        for t in tiles) + "</div>"


def _chart_card(ch: dict) -> str:
    return f"""<div class='fcard an-chart'>
<h3>{ch['title']} <small>{ch['sub']}</small></h3>
{line_days(ch['labels'], ch['values'], 'var(--teal)')}
<div class='an-foot'>
  <div><span>Total programări</span><b>{ch['total']}</b>{_trend(ch['total_trend'])}</div>
  <div><span>Rata de prezență</span><b>{ch['present_pct']}%</b>
    <div class='statbar'><div style='width:{ch['present_pct']}%'></div></div></div>
  <div><span>Neprezentări</span><b>{ch['noshow']}</b>
    <small>{ch['loss']}</small></div>
  <div><span>Așteptare medie</span><b data-wait>{ch['wait']['text']}</b>
    <small>{ch['wait']['sub']}</small></div>
</div></div>"""


def _src_card(src: dict) -> str:
    if not src["show"]:
        return ""       # один источник — не разбивка, а тавтология
    e = html.escape
    legend = "".join(
        f"<div class='an-src'><i style='background:{p['color']}'></i>{e(p['label'])}"
        f"<b>{p['value']}</b><small>{p['pct']}%</small></div>"
        for p in src["parts"])
    parts = [(p["label"], p["value"], p["color"]) for p in src["parts"]]
    return (f"<div class='fcard'><h3>Surse programări</h3><div class='an-donut'>"
            f"{donut(parts, 'Total')}<div class='an-legend'>{legend}</div></div></div>")


def _gauge_card(occ: dict) -> str:
    return (f"<div class='fcard an-gauge'><h3>Grad de ocupare</h3>"
            f"{gauge(occ['pct'], 'var(--teal)')}"
            f"<small>{occ['note']}</small></div>")


def _money_card(m: dict) -> str:
    note = " · ".join(
        (f"{_ic(n['icon'])} {n['t']}" if n["icon"] else n["t"]) for n in m["note"])
    link = (f"<a class='ag-all' href='{m['link']['href']}'>"
            f"{_ic(m['link']['icon'])} {m['link']['label']}</a>" if m["link"] else "")
    # суффикс « MDL» едет с каждым кадром счётчика (без data-suffix последний
    # кадр показывал голое «2550» — скрин Олега 08-07)
    return (f"<div class='fcard an-money'><h3>{m['title']} <small>{m['sub']}</small></h3>"
            f"<b data-count='{m['value']}' data-suffix='{m['suffix']}'>{m['text']}</b>"
            f"{_trend(m['trend'])}<small>{note}</small>{link}</div>")


def _doctors(rows: list) -> str:
    e = html.escape
    body = "".join(
        f"<tr><td>{e(d['name'])}"
        + (" <small style='color:var(--text3)'>· inactiv</small>" if d["off"] else "")
        + f"</td><td>{d['n']}</td><td>{d['came']}</td>"
        f"<td><div class='an-bar'><span>{d['pres']}%</span>"
        f"<div class='statbar'><div style='width:{d['pres']}%'></div></div></div></td>"
        f"<td><div class='an-bar'><span>{d['pct']}%</span>"
        f"<div class='statbar'><div style='width:{min(d['pct'], 100)}%'></div></div>"
        f"</div></td></tr>" for d in rows)
    return ("<div class='fcard'><h3>Performanța medicilor</h3>"
            "<table class='list an-tbl'>"
            "<tr><th>Medic</th><th>Programări</th><th>Au venit</th>"
            "<th>Rata prezenței</th><th>Ocupare</th></tr>" + body + "</table></div>")


def _services(rows: list) -> str:
    e = html.escape
    body = "".join(
        f"<div class='an-svc'><div class='an-svc-t'><b>{e(s['label'])}</b>"
        f"<span>{s['cnt']} prog. · {s['val']}</span></div>"
        f"<div class='statbar'><div style='width:{s['pct']}%'></div></div></div>"
        for s in rows) or "<p class='hint'>— încă fără programări —</p>"
    return f"<div class='fcard'><h3>Top servicii</h3>{body}</div>"


def _activity(rows: list) -> str:
    e = html.escape
    body = "".join(
        f"<div class='an-act'><div class='an-act-b'><b>{e(a['text'])}</b>"
        + "<small>"
        + (f"<a href='/admin/patient/{a['patient_id']}'>{e(a['name'])}</a>"
           if a["patient_id"] else e(a["name"]))
        + f" · {e(a['who'])}</small></div><span>{a['at']}</span></div>"
        for a in rows)
    return ("<div class='fcard'><h3>Activitate recentă</h3>"
            + (body or "<p class='hint'>— încă nimic —</p>") + "</div>")


def _nav(d: dict) -> str:
    p = d["period"]
    links = "".join(
        f"<a href='/admin/stats?from={x['from']}&to={x['to']}'>{x['label']}</a>"
        for x in d["presets"])
    return (
        "<div class='nav'>"
        f"<b>{p['label']}</b>{links}"
        f"<form class='dpickf' method='get' action='/admin/stats' style='display:inline-flex;gap:4px'>"
        f"<input class='dpick' type='date' name='from' value='{p['from']}'>"
        f"<input class='dpick' type='date' name='to' value='{p['to']}'>"
        f"<button class='searchf' style='background:var(--teal);color:#fff;border:none;"
        f"border-radius:var(--r-ctl);height:var(--h-ctl);padding:0 18px;cursor:pointer;"
        f"font-size:14px;font-weight:600'>OK</button></form>"
        f"<a href='{d['export_url']}'>{_ic('download')} Export Excel</a>"
        f"<a href='/admin'>{_ic('home')} Panou</a></div>")


def page(d: dict) -> str:
    """Тело старой страницы целиком — без баннера и каркаса."""
    money = "".join(_money_card(m) for m in d["money"])
    return (_nav(d) + _tiles(d["tiles"])
            + "<div class='an-grid'>"
            + f"<div class='an-main'>{_chart_card(d['chart'])}{_doctors(d['doctors'])}</div>"
            + f"<div class='an-side'>{_src_card(d['sources'])}"
              f"{_gauge_card(d['occupancy'])}{money}</div>"
            + "</div>"
            + "<div class='an-grid2'>"
            + _services(d["services"]) + _activity(d["activity"])
            + "</div>"
            + f"<p class='hint'>{d['hint']}</p>")
