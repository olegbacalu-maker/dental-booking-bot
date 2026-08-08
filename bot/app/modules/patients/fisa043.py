"""Печатная «Fișa medicală a bolnavului stomatologic» — formular nr. 043/e.

Форма из приказа МЗ РМ №828 от 31.10.2011 (первичная меддокументация, хранение
5 лет). Минздрав допускает ведение в информационной системе с распечаткой —
подпись остаётся на бумаге, поэтому у дневника колонка «Medicul (semnătura)»,
а после заполненных строк печатаются ПУСТЫЕ: продолжать можно ручкой, лист
остаётся живым документом, а не слепком.

Что берётся из фиши: паспортная часть, аллергии (alerts), одонтограмма
(числовая решётка с легендой — печатная форма традиционно буквенная, а не
цветная), план лечения, дневник приёмов (visit_records, ХРОНОЛОГИЧЕСКИ).
Чего в данных нет — печатается жёлтым пропуском на дозаполнение ручкой
(anamneza, mucoasa, ocluzia): приём тот же, что в acord.py, — на бумаге
видно, что дописать. Мы НЕ утверждаем пиксельного совпадения с типографским
бланком: заголовок называет формуляр и приказ, разделы — те же, а проверку
интересует состав записей, не вёрстка.

Страница самостоятельная (не `_shell`): лист для принтера, печать —
window.print() (паттерн acord.py/QR)."""
from __future__ import annotations

import html
from datetime import datetime

from ... import engine as eng

# буквенные коды одонтограммы; пустая клетка = sănătos / neexaminat.
# Легенда печатается НА листе — расшифровка всегда перед глазами читающего
_STATE_ABBR = {"ok": "", "carie": "C", "obturatie": "O", "tratament": "T",
               "coroana": "Cor", "implant": "Imp", "extras": "E", "lipsa": "A"}
_LEGEND = ("C — carie · O — obturație · T — în tratament · Cor — coroană · "
           "Imp — implant · E — extras · A — absent · (gol) — sănătos / "
           "neexaminat")

_FDI_UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
_FDI_LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

_PLAN_RO = {"planificat": "planificat", "in_lucru": "în lucru",
            "finalizat": "finalizat"}

_CSS = """
 *{box-sizing:border-box}
 body{font-family:Georgia,'Times New Roman',serif;max-width:780px;margin:18px auto;
      padding:0 16px;color:#111;line-height:1.45;font-size:12.5px}
 h1{font-size:16px;text-align:center;margin:8px 0 2px}
 .sub{text-align:center;color:#555;font-size:11px;margin:0 0 12px}
 h2{font-size:13px;margin:14px 0 4px;border-bottom:1px solid #999;padding-bottom:2px}
 .hdr{display:flex;justify-content:space-between;gap:16px;font-size:11px;color:#333}
 .hdr .r{text-align:right}
 .fill{background:#FFF3B0;padding:0 6px}
 .line{margin:5px 0}
 table{border-collapse:collapse;width:100%}
 .ft td,.ft th{border:1px solid #444;padding:5px 7px;vertical-align:top;
      font-size:12px;overflow-wrap:anywhere}
 .ft th{background:#f2f2f2;font-weight:600;text-align:left}
 .od td{border:1px solid #444;text-align:center;padding:3px 0;font-size:12px;
      width:6.25%}
 .od .st{height:22px;font-weight:700}
 .od .mid{border-left:2.5px solid #111}
 .od .nr{font-weight:600;background:#f7f7f7}
 .legend{font-size:10.5px;color:#444;margin:4px 0 0}
 .tnotes{font-size:11.5px;margin:4px 0 0}
 .sig{width:130px}
 .empty td{height:84px}
 .foot{margin-top:12px;font-size:10px;color:#777;text-align:center}
 .noprint{display:flex;gap:10px;justify-content:center;margin:0 0 14px}
 .noprint button{background:#0E9F8A;color:#fff;border:none;border-radius:8px;
      padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
 .noprint a{align-self:center;color:#0E9F8A;font-family:system-ui,sans-serif;font-size:14px}
 tr{page-break-inside:avoid}
 @media print{.noprint{display:none}body{margin:0 auto}}
"""


def _fill(value, blank: str = "________________") -> str:
    v = ("" if value is None else str(value)).strip()
    return html.escape(v) if v else f"<span class='fill'>{blank}</span>"


def _dt(value) -> str:
    if getattr(value, "tzinfo", None) is not None:
        value = value.astimezone(eng.TZ)
    return value.strftime("%d.%m.%Y %H:%M")


def _od_rows(teeth: dict) -> str:
    """Четыре ряда решётки: статусы верхних, номера верхних, номера нижних,
    статусы нижних. Средняя линия — утолщённая граница на 9-й клетке."""
    def cells(nums, kind):
        out = []
        for i, n in enumerate(nums):
            mid = " mid" if i == 8 else ""
            if kind == "nr":
                out.append(f"<td class='nr{mid}'>{n}</td>")
            else:
                st = (teeth.get(n) or {}).get("state", "ok")
                out.append(f"<td class='st{mid}'>"
                           f"{html.escape(_STATE_ABBR.get(st, ''))}</td>")
        return "".join(out)

    return (f"<tr>{cells(_FDI_UPPER, 'st')}</tr>"
            f"<tr>{cells(_FDI_UPPER, 'nr')}</tr>"
            f"<tr>{cells(_FDI_LOWER, 'nr')}</tr>"
            f"<tr>{cells(_FDI_LOWER, 'st')}</tr>")


def _diary_cell(r: dict) -> tuple[str, str]:
    """Две ячейки дневника: (acuze+obiectiv+diagnostic, tratament+recomandări)."""
    e = html.escape

    def part(label, key):
        v = (r.get(key) or "").strip()
        return f"<b>{label}:</b> {e(v)}" if v else ""

    left = "<br>".join(x for x in (part("Acuze", "acuze"),
                                   part("Obiectiv", "examen"),
                                   part("Diagnostic", "diagnostic")) if x)
    right = "<br>".join(x for x in (part("Tratament", "tratament"),
                                    part("Recomandări", "recomandari")) if x)
    svc = (r.get("service") or "").strip()
    if svc:
        right = (right + "<br>" if right else "") + \
            f"<small style='color:#555'>Serviciu: {e(svc)}</small>"
    return left or "—", right or "—"


def render(p: dict, alerts: list, teeth: dict, plan: list, recs: list,
           rx_count: int, age: int | None) -> str:
    """`recs` — записи приёмов ХРОНОЛОГИЧЕСКИ (дневник читается сверху вниз)."""
    e = html.escape
    clinic = e(eng.CLINIC_NAME)
    addr = e((eng.CONFIG or {}).get("address", {}).get("ro", ""))
    phone = e(eng.CLINIC_PHONE)
    file_no = (p.get("file_no") or "").strip() or str(p["id"])
    today = datetime.now(eng.TZ).strftime("%d.%m.%Y")

    allergy = "; ".join(a["text"] for a in alerts if a["kind"] == "allergy")
    mentions = "; ".join(a["text"] for a in alerts
                         if a["kind"] in ("medication", "warning"))
    gender = {"m": "M", "f": "F"}.get(p.get("gender") or "", "")
    birth = (p.get("birth_date") or "").strip()
    if birth:
        try:
            birth = datetime.fromisoformat(birth).strftime("%d.%m.%Y")
        except ValueError:
            pass
    elif p.get("birth_year"):
        birth = str(p["birth_year"])
    if birth and age is not None:
        birth += f" ({age} ani)"

    # диагноз титульной части — последний непустой из дневника
    diag = next((r["diagnostic"].strip() for r in reversed(recs)
                 if (r.get("diagnostic") or "").strip()), "")

    tooth_notes = "; ".join(
        f"{t} — {e((row.get('note') or '').strip())}"
        for t, row in sorted(teeth.items()) if (row.get("note") or "").strip())

    plan_rows = "".join(
        f"<tr><td>{it['tooth'] or '—'}</td><td>{e(it['procedure'])}</td>"
        f"<td>{e(it['doctor']) or '—'}</td>"
        f"<td>{_PLAN_RO.get(it['status'], it['status'])}</td>"
        f"<td>{it['price_mdl'] or '—'}</td></tr>"
        for it in plan)
    plan_html = (f"<table class='ft'><tr><th>Dinte</th><th>Procedură</th>"
                 f"<th>Medic</th><th>Stare</th><th>Preț (MDL)</th></tr>"
                 f"{plan_rows}</table>" if plan
                 else f"<p class='line'>{_fill('', '_' * 60)}</p>")

    diary_rows = []
    for r in recs:
        left, right = _diary_cell(r)
        diary_rows.append(
            f"<tr><td style='white-space:nowrap'>{_dt(r['starts_at'])}</td>"
            f"<td>{left}</td><td>{right}</td>"
            f"<td class='sig'>{e(r.get('doctor') or '')}<br><br></td></tr>")
    # пустые строки: лист продолжает жить ручкой и после печати
    diary_rows += ["<tr class='empty'><td></td><td></td><td></td>"
                   "<td class='sig'></td></tr>"] * 3

    rx_note = (f" <small>(în program: {rx_count} radiografii atașate)</small>"
               if rx_count else "")

    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fișa 043/e — {e(p.get("name") or "pacient")}</title>
<style>{_CSS}</style></head><body>

<div class="noprint">
  <button onclick="window.print()">🖨 Printează</button>
  <a href="/admin/patient/{p["id"]}">← Fișa pacientului</a>
</div>

<div class="hdr">
  <div>Ministerul Sănătății al Republicii Moldova<br>
  <b>{clinic}</b> · IDNO <span class="fill">«IDNO»</span><br>
  {addr or "<span class='fill'>«adresa»</span>"} · tel. {phone}</div>
  <div class="r">Formularul nr. <b>043/e</b><br>
  aprobat prin Ordinul MS RM<br>nr. 828 din 31.10.2011</div>
</div>

<h1>FIȘA MEDICALĂ A BOLNAVULUI STOMATOLOGIC</h1>
<p class="sub">nr. <b>{e(file_no)}</b> · deschisă la
{_fill(p.get("created_at") and _dt(p["created_at"]).split(" ")[0], "__.__.____")}</p>

<h2>1. Date generale</h2>
<p class="line">Nume, prenume: <b>{_fill(p.get("name"),
"____________________________")}</b> · Sex: {_fill(gender, "___")}</p>
<p class="line">Data nașterii: {_fill(birth)} · IDNP: {_fill(p.get("idnp"))} ·
Telefon: {_fill(p.get("phone"))}</p>
<p class="line">Adresa: {_fill(p.get("address"), "_" * 50)}</p>
<p class="line">Medic curant: {_fill(p.get("primary_doctor"))} ·
Asigurare: {_fill(p.get("insurance"))}</p>

<h2>2. Anamneza</h2>
<p class="line">Alergii: {_fill(allergy, "_" * 50)}</p>
{f"<p class='line'>Mențiuni (medicație, atenționări): {e(mentions)}</p>" if mentions else ""}
<p class="line">Bolile suportate și concomitente: {_fill("", "_" * 44)}</p>
<p class="line">{_fill("", "_" * 76)}</p>

<h2>3. Formula dentară</h2>
<table class="od">{_od_rows(teeth)}</table>
<p class="legend">{_LEGEND}</p>
{f"<p class='tnotes'><b>Note pe dinți:</b> {tooth_notes}</p>" if tooth_notes else ""}

<h2>4. Date obiective</h2>
<p class="line">Starea mucoasei cavității bucale: {_fill("", "_" * 40)}</p>
<p class="line">Ocluzia: {_fill("", "_" * 30)} ·
Examen radiologic:{rx_note} {_fill("", "_" * 20)}</p>
<p class="line">Diagnostic: {_fill(diag, "_" * 56)}</p>

<h2>5. Planul de tratament</h2>
{plan_html}

<h2>6. Jurnalul vizitelor</h2>
<table class="ft">
<tr><th>Data</th><th>Acuze, statusul obiectiv, diagnosticul</th>
<th>Tratamentul efectuat, recomandările</th>
<th class="sig">Medicul (semnătura)</th></tr>
{"".join(diary_rows)}
</table>

<p class="foot">Fișa nr. {e(file_no)} · formular generat de DentPilot la {today}
· documentația medicală primară se păstrează 5 ani (Ordinul MS nr. 828/2011)</p>

</body></html>"""
