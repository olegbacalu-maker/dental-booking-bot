"""Печатный отчёт кассы за день — «Raport de casă».

Кто и зачем: в конце смены регистратура сверяет наличные в ящике с тем, что
проведено в программе, и подписывает лист. Поэтому здесь именно ПЕЧАТЬ, а не
экран: подпись ставится ручкой, лист уходит в папку.

Почему в `stats`, а не в `patients`: отчёт про день клиники, а не про пациента,
и живёт он за `PERM_MONEY` — той же дверью, что «Încasări» в аналитике.
Раскладка страницы повторяет `patients/acord.py`: тот же скелет, та же кнопка
печати, тот же `@media print`.

⛔ Только румынский, в отличие от `acord.py` и `fisa043.py`. Те читает ПАЦИЕНТ,
и язык берётся из его фиши; этот лист внутренний — его читает клиника, а у
клиники язык один. Заводить `_T` здесь значило бы обещать перевод там, где
некому его спросить.
"""
from __future__ import annotations

import html
from datetime import date, datetime

from ... import engine as eng
from ...core import theme

# Порядок фиксированный, а не по данным: пустая строка «Card — 0 MDL» это тоже
# сведение кассы. «Сегодня картой не платили» и «строку забыли» — разные вещи,
# и на подписываемом листе они обязаны выглядеть по-разному.
METHODS = (("numerar", "Numerar"), ("card", "Card"), ("transfer", "Transfer"))

_CSS = """
 *{box-sizing:border-box}
 body{font-family:Georgia,'Times New Roman',serif;max-width:760px;margin:18px auto;
      padding:0 16px;color:#111;line-height:1.5;font-size:13px}
 h1{font-size:17px;text-align:center;margin:6px 0 2px}
 .sub{text-align:center;color:#555;font-size:12px;margin:0 0 14px}
 table{width:100%;border-collapse:collapse;margin:10px 0;font-size:12.5px}
 th,td{border:1px solid #999;padding:5px 8px;text-align:left}
 th{background:#F0F0F0;font-size:12px}
 td.n,th.n{text-align:right;white-space:nowrap}
 tr.tot td{font-weight:700;background:#F7F7F7}
 .empty{border:1px solid #999;padding:14px;text-align:center;color:#555}
 .sums{width:auto;margin-left:auto}
 .sign{margin:18px 0 0;display:flex;justify-content:space-between;font-size:13px}
 .foot{margin-top:14px;font-size:10px;color:#777;text-align:center}
 .noprint{display:flex;gap:10px;justify-content:center;margin:0 0 14px}
 .noprint button{background:__ACCENT__;color:__ON__;border:none;border-radius:8px;
      padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
 .noprint a{align-self:center;color:__ACCENT__;font-family:system-ui,sans-serif;font-size:14px}
 .clogo{display:block;max-height:16mm;max-width:45mm;object-fit:contain;margin-bottom:2mm}
 .clogo.c{margin:0 auto 3mm}
 @media print{.noprint{display:none}body{margin:0 auto}}
"""


def _mdl(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def render(day: date, rows: list) -> str:
    """`rows` — то, что вернул `db.payments_day`, без обработки.

    ⚠️ `at` приходит в UTC, как все даты из `_fetch`. Перевод в `eng.TZ` живёт
    ЗДЕСЬ и только здесь: платёж, принятый в 09:00, иначе встал бы в отчёт как
    06:00 — дата верна, формат верен, час чужой, и по такому листу касса не
    сойдётся с ящиком.
    """
    e = html.escape
    clinic = e(eng.CLINIC_NAME)
    d_s = day.strftime("%d.%m.%Y")

    trs, by_method, total = [], {k: 0 for k, _ in METHODS}, 0
    for r in rows:
        amount = int(r["amount_mdl"] or 0)
        total += amount
        # неизвестный способ не теряем в сумме: он попадает в total и в
        # таблицу, просто не имеет своей строки в сводке
        if r["method"] in by_method:
            by_method[r["method"]] += amount
        label = dict(METHODS).get(r["method"], r["method"] or "—")
        trs.append(
            f"<tr><td>{r['at'].astimezone(eng.TZ).strftime('%H:%M')}</td>"
            f"<td>{e(r['patient'] or '—')}</td>"
            f"<td>{e(label)}</td>"
            f"<td class='n'>{_mdl(amount)}</td>"
            f"<td>{e(r['taken_by'] or '—')}</td>"
            f"<td>{e(r['note'] or '')}</td></tr>")

    if trs:
        table = (f"<table><thead><tr><th>Ora</th><th>Pacient</th><th>Metoda</th>"
                 f"<th class='n'>Suma, MDL</th><th>Încasat de</th><th>Notă</th>"
                 f"</tr></thead><tbody>{''.join(trs)}</tbody></table>")
    else:
        table = ("<div class='empty'>În această zi nu au fost înregistrate "
                 "încasări.</div>")

    sums = "".join(f"<tr><td>{lbl}</td><td class='n'>{_mdl(by_method[k])}</td></tr>"
                   for k, lbl in METHODS)
    sums = (f"<table class='sums'><tbody>{sums}"
            f"<tr class='tot'><td>Total încasat</td>"
            f"<td class='n'>{_mdl(total)} MDL</td></tr></tbody></table>")

    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raport de casă — {d_s}</title>
<style>{theme.paint(_CSS)}</style></head><body>

<div class="noprint">
  <button onclick="window.print()">🖨 Printează</button>
  <a href="/admin/stats">← Statistici</a>
</div>

{theme.print_logo("clogo c")}
<h1>Raport de casă</h1>
<p class="sub">{clinic} · ziua de {d_s}</p>

{table}

<h2 style="font-size:13.5px;margin:14px 0 4px">Total pe metode de plată</h2>
{sums}

<div class="sign">
<span>Casier: ______________________</span>
<span>Semnătura: ______________________</span>
</div>

<p class="foot">Documentul reflectă plățile înregistrate în program la data
indicată. Tipărit: {datetime.now(eng.TZ).strftime('%d.%m.%Y %H:%M')}.</p>
</body></html>"""
