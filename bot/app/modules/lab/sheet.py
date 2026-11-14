"""Печатный лист наряда в лабораторию (A4, книжный).

О пациенте — только имя или № фиши (выбор клиники); даты рождения, IDNP,
телефона, адреса, анамнеза и цены на листе нет: лаборатории их не нужно, а
каждое лишнее поле — лишняя передача данных третьему лицу."""
from __future__ import annotations

import html
from datetime import date

from ... import engine as eng
from ...core import theme
from ...core.labels import LAB_IMPRESSION

_CSS = """
@page{size:A4 portrait}
body{margin:0 auto;max-width:190mm;padding:0 4mm;font:10.5pt/1.35 Georgia,'Times New Roman',serif;color:#000;background:#fff}
.noprint{display:flex;gap:8px;margin:10px 0 14px}
.noprint button,.noprint a{font:inherit;padding:6px 12px;border:1px solid #999;border-radius:6px;background:#fff;color:#000;text-decoration:none;cursor:pointer}
@media print{.noprint{display:none}}
.top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1.5px solid #000;padding-bottom:6px}
.top h1{font-size:15pt;margin:0}
.top .cl{font-size:9.5pt;text-align:right}
.urg{display:inline-block;border:2.5px solid #000;font:bold 16pt/1 Arial,sans-serif;padding:4px 10px;margin:8px 0;letter-spacing:2px}
table.kv{border-collapse:collapse;width:100%;margin:8px 0}
table.kv td{padding:3px 6px;vertical-align:top}
table.kv td.k{width:34mm;color:#333}
table.w{border-collapse:collapse;width:100%;margin:8px 0}
table.w th,table.w td{border:1px solid #000;padding:4px 6px;text-align:left;vertical-align:top}
table.w th{font-size:9pt;background:#f2f2f2}
table.fdi{border-collapse:collapse;margin:6px auto}
table.fdi td{border:1px solid #888;width:8.5mm;height:7mm;text-align:center;font:9pt Arial,sans-serif;color:#888}
table.fdi td.on{border:2px solid #000;color:#000;font-weight:bold;background:#e6e6e6}
table.fdi td.mid{border:none;width:3mm}
table.fdi tr.split td{border-top:2px solid #000}
.note{border:1px solid #000;min-height:18mm;padding:5px 7px;white-space:pre-wrap}
.sign{display:flex;gap:16mm;margin-top:16mm}
.sign div{flex:1;border-top:1px solid #000;padding-top:3px;font-size:9pt}
h2{font-size:11pt;margin:12px 0 4px}
"""

_UP = (list(range(18, 10, -1)), list(range(21, 29)))
_DOWN = (list(range(48, 40, -1)), list(range(31, 39)))
_UP_K = (list(range(55, 50, -1)), list(range(61, 66)))
_DOWN_K = (list(range(85, 80, -1)), list(range(71, 76)))


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _dmy(v) -> str:
    try:
        return date.fromisoformat(str(v)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return ""


def _row(halves, marked: set, cls: str = "") -> str:
    left, right = halves
    cells = "".join(f'<td class="{"on" if t in marked else ""}">{t}</td>' for t in left)
    cells += '<td class="mid"></td>'
    cells += "".join(f'<td class="{"on" if t in marked else ""}">{t}</td>' for t in right)
    return f'<tr class="{cls}">{cells}</tr>'


def formula(marked: set) -> str:
    """Формула FDI с отмеченными зубами; молочные ряды — только если отмечен
    молочный зуб."""
    kids = any(t >= 51 for t in marked)
    rows = ([_row(_UP_K, marked)] if kids else []) + [_row(_UP, marked), _row(_DOWN, marked, "split")]
    if kids:
        rows.append(_row(_DOWN_K, marked))
    return f'<table class="fdi">{"".join(rows)}</table>'


def _lines(items: list) -> str:
    rows, seen = [], set()
    for it in items:
        g = it.get("grp")
        if g is not None:
            if g in seen:
                continue
            seen.add(g)
            grp = [x for x in items if x.get("grp") == g]
        else:
            grp = [it]
        teeth = []
        for x in grp:
            teeth += [t for t in (x.get("teeth") or "").split(",") if t]
        qty = sum(int(x.get("qty") or 1) for x in grp) if g is None else 1
        rows.append(f"<tr><td>{_e(it['work'])}</td><td>{_e(it.get('material'))}</td>"
                    f"<td>{_e(it.get('shade'))}</td><td>{_e(', '.join(teeth))}</td><td>{qty}</td></tr>")
    return ('<table class="w"><thead><tr><th>Lucrare</th><th>Material</th><th>Culoare</th><th>Dinți</th>'
            f'<th>Buc.</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')


def render(d: dict, back: str) -> str:
    o, items, p, lab = d["order"], d["items"], d["patient"], d["lab"] or {}
    marked = {int(t) for it in items for t in (it.get("teeth") or "").split(",") if t.strip().isdigit()}
    who = (f"{_e(p.get('name') or '')} <span style=\"color:#555\">(fișa nr. {_e(d['fisa'])})</span>"
           if d["who"] == "name" else f"Fișa nr. {_e(d['fisa'])}")
    legal = eng.CLINIC_LEGAL or eng.CLINIC_NAME
    idno = f"<br>IDNO {_e(eng.CLINIC_IDNO)}" if eng.CLINIC_IDNO else ""
    contact = " · ".join(x for x in (lab.get("contact"), lab.get("phone")) if x)
    impr = LAB_IMPRESSION.get(o.get("impression") or "", "")
    stage = f" · etapa {o['stage']}" if (o.get("stage") or 1) > 1 else ""
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>Comandă laborator nr {_e(o['nr'])}</title>
<style>{_CSS}{theme.PRINT_PAGE_CSS}</style></head><body>
<div class="noprint"><button onclick="window.print()">Tipărește</button><a href="{_e(back)}">Înapoi</a></div>
<div class="top"><div><h1>Comandă la laboratorul dentar nr {_e(o['nr'])}</h1>
<div>Trimisă: {_dmy(o.get('sent_on'))} · Termen: <b>{_dmy(o.get('due_on'))}</b>{stage}</div></div>
<div class="cl"><b>{_e(legal)}</b>{f' ({_e(eng.CLINIC_NAME)})' if eng.CLINIC_LEGAL and eng.CLINIC_NAME else ''}{idno}
{f'<br>{_e(eng.CLINIC_PHONE)}' if eng.CLINIC_PHONE else ''}</div></div>
{'<div class="urg">URGENT</div>' if o.get('urgent') else ''}
<table class="kv">
<tr><td class="k">Laborator</td><td><b>{_e(o['lab'])}</b>{f' · {_e(contact)}' if contact else ''}</td></tr>
<tr><td class="k">Pacient</td><td>{who}</td></tr>
<tr><td class="k">Medic</td><td>{_e(o.get('doctor')) or '—'}</td></tr>
<tr><td class="k">Amprentă</td><td>{_e(impr) or '—'}</td></tr>
</table>
<h2>Lucrări</h2>{_lines(items)}
<h2>Formula dentară</h2>{formula(marked)}
<h2>Indicații pentru tehnician</h2><div class="note">{_e(o.get('note'))}</div>
<div class="sign"><div>Medic: {_e(o.get('doctor'))}<br>semnătura</div><div>Laborator: am primit<br>data, semnătura</div></div>
</body></html>"""
