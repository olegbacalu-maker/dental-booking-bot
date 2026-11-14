"""Печатный лист «De cumpărat» (A4, книжный): что ниже порога, по
поставщикам с телефоном; сколько купить — упаковками и единицами. Цены — только
у директора (`money`)."""
from __future__ import annotations

import html
from datetime import date

from ...core import theme
from ...core.stock import fmt_qty

_CSS = """
@page{size:A4 portrait}
body{margin:0 auto;max-width:190mm;padding:0 4mm;font:10.5pt/1.35 Georgia,'Times New Roman',serif;color:#000;background:#fff}
.noprint{display:flex;gap:8px;margin:10px 0 14px}
.noprint button,.noprint a{font:inherit;padding:6px 12px;border:1px solid #999;border-radius:6px;background:#fff;color:#000;text-decoration:none;cursor:pointer}
@media print{.noprint{display:none}}
.top{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1.5px solid #000;padding-bottom:6px}
.top h1{font-size:15pt;margin:0}
h2{font-size:11.5pt;margin:14px 0 2px}
.ph{font-size:9.5pt;color:#333;margin-bottom:4px}
table{border-collapse:collapse;width:100%;margin:4px 0 8px}
th,td{border:1px solid #000;padding:4px 6px;text-align:left;vertical-align:top}
th{font-size:9pt;background:#f2f2f2}
td.n{text-align:right;white-space:nowrap}
.empty{margin:24px 0;font-style:italic}
"""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _lei(b) -> str:
    return "" if b is None else f"{b / 100:,.2f}".replace(",", " ").replace(".", ",")


def _group(g: dict, money: bool) -> str:
    rows = []
    total = 0
    for r in g["rows"]:
        packs = r["buy_packs"]
        units = packs * r["pack_qty_milli"]
        est = r.get("est_bani")
        total += est or 0
        rows.append(
            f"<tr><td>{_e(r['name'])}</td><td class='n'>{_e(fmt_qty(r['qty_milli']))} {_e(r['unit'])}</td>"
            f"<td class='n'>{_e(fmt_qty(r['min_milli'] or 0))} {_e(r['unit'])}</td>"
            f"<td class='n'><b>{packs}</b> × {_e(r['pack_name'] or r['unit'])}</td>"
            f"<td class='n'>{_e(fmt_qty(units))} {_e(r['unit'])}</td>"
            + (f"<td class='n'>{_lei(est)}</td>" if money else "") + "</tr>")
    contact = " · ".join(x for x in (g.get("phone"), g.get("email")) if x)
    head = ("<tr><th>Material</th><th>Este</th><th>Prag</th><th>De cumpărat</th><th>În unități</th>"
            + ("<th>Estimat, lei</th>" if money else "") + "</tr>")
    foot = (f"<tr><td colspan='5'><b>Total estimat</b></td><td class='n'><b>{_lei(total)}</b></td></tr>"
            if money and total else "")
    return (f"<h2>{_e(g['supplier'])}</h2>" + (f"<div class='ph'>{_e(contact)}</div>" if contact else "")
            + f"<table><thead>{head}</thead><tbody>{''.join(rows)}{foot}</tbody></table>")


def render(d: dict, back: str) -> str:
    day = date.fromisoformat(d["today"]).strftime("%d.%m.%Y")
    body = "".join(_group(g, d["money"]) for g in d["groups"]) or \
        "<p class='empty'>Nu este nimic de cumpărat: toate materialele sunt peste prag.</p>"
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>De cumpărat — {_e(day)}</title>
<style>{_CSS}{theme.PRINT_PAGE_CSS}</style></head><body>
<div class="noprint"><button onclick="window.print()">Tipărește</button><a href="{_e(back)}">Înapoi</a></div>
<div class="top"><h1>De cumpărat</h1><div>{_e(d['clinic'])} · {_e(day)}</div></div>
{body}
</body></html>"""
