"""Печатный лист регистра за период (10.11.2026): 257/e, 502/e, 501/e.

Колонки и их номера — как на образце бланка ANSP; лист A4 альбомом, шапка
таблицы повторяется на каждой странице (`thead`), внизу — места для подписи
ответственного и руководителя (L.Ș.) рукой. Графа «кто» — человек, выбранный в
окне; под ним мелко — учётка, внёсшая запись, и время программы
(registre-people, 10.11: «Вариант 1» Олега). Графы «Semnătura» — ПУСТЫЕ, под
руку; у 257/e графа одна («Semnătura, data»), имя и дата в ней, место для
подписи — под ними.
⚠️ Номер страницы на листе не пишется: сколько страниц выйдет, знает только
печать (константа «Pagina 1 din 1» врала бы на втором листе месяца).
Исправленная строка печатается зачёркнутой, с пометкой «corectată prin nr. N»
НЕ зачёркнутой; удалённые не печатаются. Правила бланков — `patients-print.md`.
"""
from __future__ import annotations

import html
from datetime import date, timedelta

from ... import engine as eng
from ...core import theme
from ...core import registre as reg

e = html.escape

TITLE = {
    "257": ("257/e", "Aprobat de MS al RM nr. 828 din 31.10.2011", "",
            "Registru de evidență a controlului lucrului sterilizatoarelor cu aer, cu aburi (autoclav)"),
    "502": ("502/e", "Aprobat de MS al RM nr. 630 din 08.08.2016", "3 ani",
            "Registru de evidență a efectuării curățeniei generale"),
    "501": ("501/e", "Aprobat de MS al RM nr. 630 din 08.08.2016", "3 ani",
            "Registru de evidență a utilizării lămpilor bactericide pentru dezinfecție"),
}
TEST = {"ok": "corect", "fail": "<b>incorect</b>", "": "—"}
BIO = {"ok": "negativ", "fail": "<b>pozitiv</b>", "wait": "în incubare", "": "—"}

_CSS = """
@page{size:A4 landscape}
*{box-sizing:border-box}
body{margin:0 auto;max-width:277mm;padding:0 4mm;font:9.5pt/1.3 Georgia,'Times New Roman',serif;color:#000;background:#fff}
.noprint{display:flex;gap:10px;margin:10px 0}
.noprint button,.noprint a{font:inherit;padding:6px 12px;border:1px solid #999;border-radius:6px;background:#fff;color:#000;text-decoration:none;cursor:pointer}
@media print{.noprint{display:none}}
.top{display:flex;justify-content:space-between;gap:20px;font-size:8.5pt}
.top .r{text-align:right}
h1{margin:5mm 0 1mm;text-align:center;font-size:11.5pt;text-transform:uppercase;letter-spacing:.02em}
.per{text-align:center;margin:0 0 3mm}
.norm{font-size:8.5pt;margin:0 0 3mm;white-space:pre-line}
table{width:100%;border-collapse:collapse}
th,td{border:.6pt solid #000;padding:2px 4px;vertical-align:top;overflow-wrap:break-word}
th{font-weight:600;font-size:8.5pt;text-align:center;vertical-align:middle}
tr.n th{font-weight:400;font-size:7.5pt;padding:1px}
tr{break-inside:avoid}
td.c{text-align:center;white-space:nowrap}
td.c small{white-space:normal}
td small{display:block;font-size:7.5pt;color:#333}
tr.old .x{text-decoration:line-through;color:#555}
.note{display:block;font-size:7.5pt;font-style:italic;text-decoration:none;white-space:normal;max-width:32mm;margin:0 auto}
.empty td{height:7mm}
.foot{margin-top:5mm;display:grid;grid-template-columns:1fr 1fr;gap:6mm 20mm;font-size:9pt;break-inside:avoid}
.foot .line{border-bottom:.6pt solid #000;height:7mm}
.foot small{display:block;font-size:7.5pt;color:#333}
.src{margin-top:3mm;font-size:7.5pt;color:#333;border-top:.6pt solid #999;padding-top:2mm}
.pas{margin:0 0 3mm}
.pas td,.pas th{font-size:8.5pt}
td.sg{min-width:22mm}
td.sg13 .sp{display:block;height:6mm}
"""


def _x(old: bool, v: str) -> str:
    return f'<span class="x">{v}</span>' if old else v


def _note(r: dict) -> str:
    bits = [f"nr. {r['id']}"]
    if r.get("fixed_by"):
        bits.append(f"corectată prin nr. {r['fixed_by']}")
    if r.get("fixes"):
        bits.append(f"corectează nr. {r['fixes']}: {e(r['why'])}")
    return f'<span class="note">{" · ".join(bits)}</span>'


def _who(r: dict, name: str, by: str, at: str) -> str:
    """Человек и мелко — кто внёс и когда. Строка до шага 10 (`legacy`):
    человек неизвестен, в графе — учётка, помеченная как учётка."""
    if r.get("legacy") and name == r["actor"]:
        return f"{e(name)}<small>cont (înreg. veche), {e(at)}</small>"
    return f"{e(name)}<small>înreg. {e(by)}, {e(at)}</small>"


def _t257(rows: list) -> str:
    head = ("<thead><tr><th rowspan=2>Data</th><th rowspan=2>Marca. Nr sterilizatorului cu aer, cu abur "
            "(autoclavă)</th><th colspan=3>Articole sterilizate</th><th colspan=2>Timpul de sterilizare</th>"
            "<th colspan=2>Regimul</th><th colspan=3>Test-control</th><th rowspan=2>Semnătura, data</th></tr>"
            "<tr><th>Denumirea</th><th>Cantitatea</th><th>Ambalaj</th><th>Începutul</th><th>Sfârșitul</th>"
            "<th>Presiunea, bar</th><th>Temperatura, °C</th><th>Biologic</th><th>Termic</th><th>Chimic</th></tr>"
            "<tr class=n>" + "".join(f"<th>{i}</th>" for i in range(1, 14)) + "</tr></thead>")
    body = []
    for r in rows:
        o = bool(r.get("fixed_by"))
        arts = r.get("arts") or []
        bio = BIO.get(r["bio"], "—") + (f"<small>{e(r['bio_at'])}</small>" if r.get("bio_at") else "")
        end = e(r["end"]) if not r["open"] else "în curs"
        sig = _who(r, r["doer"], r["actor"], r["at"])
        if r.get("end_doer") and r["end_doer"] != r["doer"]:
            sig += f"<small>încheiat: {e(r['end_doer'])}</small>"
        if r.get("bio_actor"):
            sig += f"<small>biologic: înreg. {e(r['bio_actor'])}</small>"
        sig += '<span class="sp"></span>'
        body.append(
            f'<tr class="{"old" if o else ""}"><td class=c>{_x(o, e(r["date"]))}{_note(r)}</td>'
            f"<td>{_x(o, e(r['ster']))}<small>{_x(o, e(r['program']))}</small></td>"
            f"<td>{_x(o, '<br>'.join(e(a['name']) for a in arts))}</td>"
            f"<td class=c>{_x(o, '<br>'.join(str(a['qty']) for a in arts))}</td>"
            f"<td>{_x(o, '<br>'.join(e(a.get('pack') or '') for a in arts))}</td>"
            f"<td class=c>{_x(o, e(r['start']))}</td><td class=c>{_x(o, end)}</td>"
            f"<td class=c>{_x(o, e(r['pressure']) or '—')}</td><td class=c>{_x(o, e(r['temp']) or '—')}</td>"
            f"<td class=c>{_x(o, bio)}</td><td class=c>{_x(o, TEST.get(r['term'], '—'))}</td>"
            f"<td class=c>{_x(o, TEST.get(r['chem'], '—'))}</td><td class=sg13>{_x(o, sig)}</td></tr>")
    return f"<table>{head}<tbody>{''.join(body)}{_blank(13, 3)}</tbody></table>"


def _t502(rows: list) -> str:
    head = ("<thead><tr><th rowspan=2>Număr de ordine</th><th rowspan=2>Încăperea</th>"
            "<th rowspan=2>Data planificării</th><th rowspan=2>Data efectuării</th>"
            "<th rowspan=2>Soluția dezinfectantă utilizată (denumirea, concentrația și expoziția)</th>"
            "<th colspan=2>A efectuat</th><th colspan=2>A supervizat</th></tr>"
            "<tr><th>numele, prenumele</th><th>Semnătura</th><th>numele, prenumele</th><th>Semnătura</th></tr>"
            "<tr class=n>" + "".join(f"<th>{i}</th>" for i in range(1, 10)) + "</tr></thead>")
    body = []
    for r in rows:
        o = bool(r.get("fixed_by"))
        # проверка до шага 10 (`sup_by` пуст) подписана учёткой — так и названа
        sup = "<td></td><td class=sg></td>"
        if r.get("sup_actor"):
            how = (f"înreg. {e(r['sup_by'])}" if r.get("sup_by") else "cont (înreg. veche)") + f", {e(r['sup_at'])}"
            sup = f"<td>{_x(o, e(r['sup_actor']) + f'<small>{how}</small>')}</td><td class=sg></td>"
        body.append(
            f'<tr class="{"old" if o else ""}"><td class=c>{r["id"]}{_note(r) if (r.get("fixes") or o) else ""}</td>'
            f"<td>{_x(o, e(r['room']))}</td><td class=c>{_x(o, e(r['plan']))}</td>"
            f"<td class=c>{_x(o, e(r['done']))}</td><td>{_x(o, e(r['solution']))}</td>"
            f"<td>{_x(o, _who(r, r['doer'], r['actor'], r['at']))}</td><td class=sg></td>"
            f"{sup}</tr>")
    return f"<table>{head}<tbody>{''.join(body)}{_blank(9, 3)}</tbody></table>"


def _passport(lamps: list) -> str:
    if not lamps:
        return ""
    rows = []
    for lp in lamps:
        d = lp.get("data") or {}
        changes = ", ".join(reg.dmy(c.get("date")) for c in d.get("changes") or []) or "—"
        rows.append(f"<tr><td>{e(lp.get('room') or '')}{', ' + str(d.get('m3')) + ' m³' if d.get('m3') else ''}</td>"
                    f"<td>{e(reg.label(lp))}</td><td class=c>{e(reg.dmy(d.get('since')))}</td>"
                    f"<td class=c>{d.get('hours') or ''}</td><td class=c>{lp.get('rest', '')}</td>"
                    f"<td class=c>{e(changes)}</td></tr>")
    return ("<table class=pas><thead><tr><th>Denumirea și cubatura încăperii</th><th>Marca, numărul lămpii</th>"
            "<th>Data începerii exploatării lămpii</th><th>Rezerva orelor de lucru (conform instrucțiunii "
            "producătorului)</th><th>Ore rămase la data tipăririi</th><th>Data schimbării lămpii de facto</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>")


def _t501(rows: list) -> str:
    head = ("<thead><tr><th rowspan=2>Data</th><th rowspan=2>Încăperea iradiată</th>"
            "<th rowspan=2>Condițiile de dezinfecție (în prezența sau lipsa persoanelor)</th>"
            "<th colspan=2>Ora</th><th rowspan=2>Durata iradierii</th><th rowspan=2>Ore de valabilitate</th>"
            "<th rowspan=2>Persoana responsabilă (nume, prenume)</th><th rowspan=2>Semnătura</th></tr>"
            "<tr><th>Conectării</th><th>Deconectării</th></tr>"
            "<tr class=n>" + "".join(f"<th>{i}</th>" for i in range(1, 10)) + "</tr></thead>")
    body = []
    for r in rows:
        o = bool(r.get("fixed_by"))
        dur = f"{r['minutes']} min" if r.get("minutes") else "—"
        who = _who(r, r["doer"], r["actor"], r["at"]) + (
            f"<small>oprit: înreg. {e(r['off_actor'])}</small>" if r.get("off_actor") and r["off_actor"] != r["actor"] else "")
        body.append(
            f'<tr class="{"old" if o else ""}"><td class=c>{_x(o, e(r["date"]))}{_note(r)}</td>'
            f"<td>{_x(o, e(r['room']))}<small>{_x(o, e(r['lamp']))}</small></td><td>{_x(o, e(r['cond']))}</td>"
            f"<td class=c>{_x(o, e(r['on']))}</td><td class=c>{_x(o, e(r['off']) if not r['open'] else 'în curs')}</td>"
            f"<td class=c>{_x(o, dur)}</td><td class=c>{_x(o, '' if r.get('rest') is None else str(r['rest']))}</td>"
            f"<td>{_x(o, who)}</td><td class=sg></td></tr>")
    return f"<table>{head}<tbody>{''.join(body)}{_blank(9, 3)}</tbody></table>"


def _blank(cols: int, n: int) -> str:
    """Пустые строки под ручку: лист живёт и после печати (как 043/e)."""
    return "".join("<tr class=empty>" + "<td></td>" * cols + "</tr>" for _ in range(n))


def render(form: str, rows: list, d1: date, d2: date, printed: str, norms: str = "",
           lamps: list | None = None, back: str = "/admin/registre") -> str:
    code, order, keep, title = TITLE[form]
    clinic = e(eng.CLINIC_LEGAL or eng.CLINIC_NAME)
    idno = f" · IDNO {e(eng.CLINIC_IDNO)}" if getattr(eng, "CLINIC_IDNO", "") else ""
    last = d2 - timedelta(days=1)
    nrs = [r["id"] for r in rows]
    per = f"Perioada: {reg.dmy(d1)} – {reg.dmy(last)}"
    per += f" · înregistrările nr. {min(nrs)}–{max(nrs)}" if nrs else " · fără înregistrări"
    top_extra = ""
    if form == "257":
        top_extra = (f'<p class="norm"><b>Documentația normativă (DN) privind controlul lucrului '
                     f'sterilizatoarelor:</b> {e(norms) if norms else "_" * 60}</p>')
    table = _t257(rows) if form == "257" else _t502(rows) if form == "502" else _passport(lamps or []) + _t501(rows)
    keep_line = f"<br>Termen de păstrare — {keep}" if keep else ""
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{code} — {e(reg.dmy(d1))}–{e(reg.dmy(last))}</title>
<style>{_CSS}{theme.PRINT_PAGE_CSS}</style></head><body>
<div class="noprint"><button onclick="window.print()">Tipărește</button><a href="{e(back)}">Înapoi</a></div>
<div class="top"><div>{theme.print_logo()}<b>{clinic}</b>{idno}<br>denumirea instituției</div>
<div class="r">Formular nr. {code}<br>{order}{keep_line}</div></div>
<h1>{title}</h1><p class="per">{per}</p>{top_extra}
{table}
<div class="foot">
<div>Responsabil de registru<div class="line"></div><small>numele, prenumele · semnătura</small></div>
<div>Conducător<div class="line"></div><small>semnătura · L.Ș.</small></div>
</div>
<p class="src">Extras din registrul electronic DentPilot, tipărit {e(printed)}. Numele — persoana care a efectuat
sau a verificat, aleasă la înregistrare; dedesubt — contul din program care a făcut înregistrarea și ora programului.
Semnăturile se pun de mână pe acest extras. Corectările sunt înregistrări noi, cele corectate rămân tăiate;
înregistrările șterse nu se tipăresc.</p>
</body></html>"""


def excel_rows(form: str, rows: list) -> tuple[list, list, list]:
    """(шапка, строки, ширины) для `core/xlsx.book` — те же колонки, что у бланка."""
    def acct(r):
        # учётка, внёсшая строку; у строк до шага 10 она же была исполнителем
        return "cont (înreg. veche)" if r.get("legacy") else r["actor"]

    def mark(r):
        return ("corectată prin nr. %s" % r["fixed_by"]) if r.get("fixed_by") else (
            "corectează nr. %s: %s" % (r["fixes"], r["why"]) if r.get("fixes") else "")
    if form == "257":
        head = ["Nr.", "Data", "Sterilizator", "Program", "Articole", "Cantitatea", "Ambalaj", "Începutul",
                "Sfârșitul", "Presiunea, bar", "Temperatura, °C", "Biologic", "Termic", "Chimic", "Responsabil",
                "Încheiat de", "Înregistrat de", "Ora înregistrării", "Corectare"]
        out = [[r["id"], r["date"], r["ster"], r["program"],
                "; ".join(a["name"] for a in r["arts"]), "; ".join(str(a["qty"]) for a in r["arts"]),
                "; ".join(a.get("pack") or "" for a in r["arts"]), r["start"], r["end"], r["pressure"], r["temp"],
                {"ok": "negativ", "fail": "pozitiv", "wait": "în incubare"}.get(r["bio"], ""),
                {"ok": "corect", "fail": "incorect"}.get(r["term"], ""),
                {"ok": "corect", "fail": "incorect"}.get(r["chem"], ""), r["doer"], r.get("end_doer") or "",
                acct(r), r["at"], mark(r)] for r in rows]
        return head, out, [6, 11, 24, 18, 34, 10, 16, 9, 9, 9, 9, 11, 10, 10, 20, 20, 20, 16, 30]
    if form == "502":
        head = ["Nr.", "Încăperea", "Data planificării", "Data efectuării", "Soluția dezinfectantă",
                "A efectuat", "Înregistrat de", "Ora înregistrării", "A supervizat", "Verificare înregistrată de",
                "Ora verificării", "Corectare"]
        out = [[r["id"], r["room"], r["plan"], r["done"], r["solution"], r["doer"], acct(r), r["at"],
                r["sup_actor"], r.get("sup_by") or (r["sup_actor"] and "cont (înreg. veche)"), r["sup_at"], mark(r)]
               for r in rows]
        return head, out, [6, 22, 13, 13, 34, 20, 20, 16, 20, 20, 16, 30]
    head = ["Nr.", "Data", "Încăperea", "Lampa", "Condițiile", "Conectare", "Deconectare", "Durata, min",
            "Ore rămase", "Persoana responsabilă", "Înregistrat de", "Ora înregistrării", "Corectare"]
    out = [[r["id"], r["date"], r["room"], r["lamp"], r["cond"], r["on"], r["off"], r.get("minutes") or "",
            "" if r.get("rest") is None else r["rest"], r["doer"], acct(r), r["at"], mark(r)] for r in rows]
    return head, out, [6, 11, 20, 26, 22, 10, 11, 10, 10, 22, 20, 16, 30]
