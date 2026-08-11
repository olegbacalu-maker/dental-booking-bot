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
from ...core import theme
from ...core.layout import _ic

# буквенные коды одонтограммы; пустая клетка = sănătos / neexaminat.
# Легенда печатается НА листе — расшифровка всегда перед глазами читающего
_STATE_ABBR = {"ok": "", "carie": "C", "obturatie": "O", "tratament": "T",
               "coroana": "Cor", "implant": "Imp", "extras": "E", "lipsa": "A"}
# ⚠️ САМИ коды (C/O/T/Cor/Imp/E/A, MODVL) не переводятся — они производные
# от румынских слов и одинаковы на обоих листах; переводится расшифровка,
# иначе на русском листе легенда нечитаема ровно там, где она и нужна
_LEGEND = {
    "ro": ("C — carie · O — obturație · T — în tratament · Cor — coroană · "
           "Imp — implant · E — extras · A — absent · (gol) — sănătos / "
           "neexaminat. Suprafețe: M — mezial, O — ocluzal, D — distal, "
           "V — vestibular, L — lingual"),
    "ru": ("C — кариес · O — пломба · T — в лечении · Cor — коронка · "
           "Imp — имплант · E — удалён · A — отсутствует · (пусто) — здоров / "
           "не осмотрен. Поверхности: M — медиальная, O — окклюзионная, "
           "D — дистальная, V — вестибулярная, L — язычная"),
}

_FDI_UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
_FDI_LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

# молочный ряд печатается ВНУТРИ постоянного (как на типографском бланке):
# 10 зубов встают под позиции 4…13 шестнадцатиколоночной решётки
_FDI_MILK_UPPER = [55, 54, 53, 52, 51, 61, 62, 63, 64, 65]
_FDI_MILK_LOWER = [85, 84, 83, 82, 81, 71, 72, 73, 74, 75]

_PLAN_RO = {"planificat": "planificat", "in_lucru": "în lucru",
            "finalizat": "finalizat"}

_PLAN_RU = {"planificat": "запланировано", "in_lucru": "в работе",
            "finalizat": "выполнено"}

# Двуязычные ПОДПИСИ бланка. ⚠️ Не переводятся и в русской версии остаются
# как есть: номер формуляра (043/e), приказ МЗ, название министерства — это
# официальные наименования, по которым лист опознаёт проверяющий, и буквенные
# коды одонтограммы (C/O/T/…), потому что они производные от румынских слов.
_T = {
    "ro": {
        "title": "Fișa 043/e", "print": _ic("print") + " Printează",
        "back": _ic("chev-l") + " Fișa pacientului", "other": "Русская версия",
        "h1": "FIȘA MEDICALĂ A BOLNAVULUI STOMATOLOGIC",
        "nr": "nr.", "opened": "deschisă la",
        "s1": "1. Date generale", "name": "Nume, prenume", "sex": "Sex",
        "birth": "Data nașterii", "phone": "Telefon", "addr": "Adresa",
        "doctor": "Medic curant", "insurance": "Asigurare",
        "s2": "2. Anamneza", "allergy": "Alergii",
        "mentions": "Mențiuni (medicație, atenționări)",
        "diseases": "Bolile suportate și concomitente",
        "meds": "Medicamente administrate",
        "anesth": "Reacții la anestezice",
        "s3": "3. Formula dentară", "tnotes": "Note pe dinți",
        "s4": "4. Date obiective", "mucosa": "Starea mucoasei cavității bucale",
        "occl": "Ocluzia", "rx": "Examen radiologic",
        "rx_note": "în program: {n} radiografii atașate",
        "diag": "Diagnostic",
        "s5": "5. Planul de tratament",
        "p_tooth": "Dinte", "p_proc": "Procedură", "p_doc": "Medic",
        "p_state": "Stare", "p_price": "Preț (MDL)",
        "s6": "6. Jurnalul vizitelor",
        "j_date": "Data",
        "j_left": "Acuze, statusul obiectiv, diagnosticul",
        "j_right": "Tratamentul efectuat, recomandările",
        "j_sign": "Medicul (semnătura)",
        "d_acuze": "Acuze", "d_obiectiv": "Obiectiv", "d_diag": "Diagnostic",
        "d_trat": "Tratament", "d_rec": "Recomandări", "d_svc": "Serviciu",
        "years": "ani",
        "foot": ("Fișa nr. {no} · formular generat de DentPilot la {date} · "
                 "documentația medicală primară se păstrează 5 ani "
                 "(Ordinul MS nr. 828/2011)"),
    },
    "ru": {
        "title": "Карта 043/e", "print": _ic("print") + " Печать",
        "back": _ic("chev-l") + " Карта пациента", "other": "Versiunea română",
        "h1": "МЕДИЦИНСКАЯ КАРТА СТОМАТОЛОГИЧЕСКОГО БОЛЬНОГО",
        "nr": "№", "opened": "открыта",
        "s1": "1. Общие данные", "name": "Фамилия, имя", "sex": "Пол",
        "birth": "Дата рождения", "phone": "Телефон", "addr": "Адрес",
        "doctor": "Лечащий врач", "insurance": "Страховка",
        "s2": "2. Анамнез", "allergy": "Аллергии",
        "mentions": "Примечания (лекарства, предупреждения)",
        "diseases": "Перенесённые и сопутствующие заболевания",
        "meds": "Принимаемые лекарства",
        "anesth": "Реакции на анестетики",
        "s3": "3. Зубная формула", "tnotes": "Заметки по зубам",
        "s4": "4. Объективные данные", "mucosa": "Состояние слизистой полости рта",
        "occl": "Прикус", "rx": "Рентгенологическое исследование",
        "rx_note": "в программе: {n} снимков",
        "diag": "Диагноз",
        "s5": "5. План лечения",
        "p_tooth": "Зуб", "p_proc": "Процедура", "p_doc": "Врач",
        "p_state": "Статус", "p_price": "Цена (MDL)",
        "s6": "6. Дневник визитов",
        "j_date": "Дата",
        "j_left": "Жалобы, объективный статус, диагноз",
        "j_right": "Проведённое лечение, рекомендации",
        "j_sign": "Врач (подпись)",
        "d_acuze": "Жалобы", "d_obiectiv": "Объективно", "d_diag": "Диагноз",
        "d_trat": "Лечение", "d_rec": "Рекомендации", "d_svc": "Услуга",
        "years": "лет",
        # имя приказа НЕ переводится — по нему лист опознают, как и в шапке
        "foot": ("Карта № {no} · бланк сформирован программой DentPilot "
                 "{date} · первичная медицинская документация хранится 5 лет "
                 "(Ordinul MS nr. 828/2011)"),
    },
}

LANGS = ("ro", "ru")

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
 .od tr.mk td{font-size:10.5px;color:#333}
 .od tr.mk .nr{background:#fafafa}
 .legend{font-size:10.5px;color:#444;margin:4px 0 0}
 .tnotes{font-size:11.5px;margin:4px 0 0}
 .sig{width:130px}
 .empty td{height:84px}
 .foot{margin-top:12px;font-size:10px;color:#777;text-align:center}
 .noprint{display:flex;gap:10px;justify-content:center;margin:0 0 14px}
 .noprint button{background:__ACCENT__;color:__ON__;border:none;border-radius:8px;
      padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
 .noprint a{align-self:center;color:__ACCENT__;font-family:system-ui,sans-serif;font-size:14px}
 tr{page-break-inside:avoid}
 .clogo{display:block;max-height:16mm;max-width:45mm;object-fit:contain;margin-bottom:2mm}
 .clogo.c{margin:0 auto 3mm}
 @media print{.noprint{display:none}body{margin:0 auto}}
"""


def _fill(value, blank: str = "________________") -> str:
    v = ("" if value is None else str(value)).strip()
    return html.escape(v) if v else f"<span class='fill'>{blank}</span>"


def _dt(value) -> str:
    if getattr(value, "tzinfo", None) is not None:
        value = value.astimezone(eng.TZ)
    return value.strftime("%d.%m.%Y %H:%M")


def _od_rows(teeth: dict, milk: bool = False) -> str:
    """Ряды решётки: статусы верхних, номера верхних, [молочные], номера
    нижних, статусы нижних. Средняя линия — утолщённая граница на 9-й клетке.
    Клетка статуса — буква состояния и, если отмечены, поверхности («C MO»)."""
    def cells(nums, kind, pad=0):
        out = ["<td></td>"] * pad
        for i, n in enumerate(nums):
            mid = " mid" if i == len(nums) // 2 else ""
            if kind == "nr":
                out.append(f"<td class='nr{mid}'>{n}</td>")
            else:
                t = teeth.get(n) or {}
                txt = _STATE_ABBR.get(t.get("state", "ok"), "")
                sf = (t.get("surfaces") or "").strip()
                if sf:                       # и при «ok»: данные есть — печатаем
                    txt = f"{txt} {sf}".strip()
                out.append(f"<td class='st{mid}'>{html.escape(txt)}</td>")
        out += ["<td></td>"] * pad
        return "".join(out)

    rows = (f"<tr>{cells(_FDI_UPPER, 'st')}</tr>"
            f"<tr>{cells(_FDI_UPPER, 'nr')}</tr>")
    if milk:
        # 10 клеток по центру 16-колоночной решётки: по три пустых с краёв
        rows += (f"<tr class='mk'>{cells(_FDI_MILK_UPPER, 'nr', pad=3)}</tr>"
                 f"<tr class='mk'>{cells(_FDI_MILK_UPPER, 'st', pad=3)}</tr>"
                 f"<tr class='mk'>{cells(_FDI_MILK_LOWER, 'st', pad=3)}</tr>"
                 f"<tr class='mk'>{cells(_FDI_MILK_LOWER, 'nr', pad=3)}</tr>")
    rows += (f"<tr>{cells(_FDI_LOWER, 'nr')}</tr>"
             f"<tr>{cells(_FDI_LOWER, 'st')}</tr>")
    return rows


def _diary_cell(r: dict, t: dict) -> tuple[str, str]:
    """Две ячейки дневника: (acuze+obiectiv+diagnostic, tratament+recomandări)."""
    e = html.escape

    def part(label, key):
        v = (r.get(key) or "").strip()
        return f"<b>{label}:</b> {e(v)}" if v else ""

    left = "<br>".join(x for x in (part(t["d_acuze"], "acuze"),
                                   part(t["d_obiectiv"], "examen"),
                                   part(t["d_diag"], "diagnostic")) if x)
    right = "<br>".join(x for x in (part(t["d_trat"], "tratament"),
                                    part(t["d_rec"], "recomandari")) if x)
    svc = (r.get("service") or "").strip()
    if svc:
        right = (right + "<br>" if right else "") + \
            f"<small style='color:#555'>{t['d_svc']}: {e(svc)}</small>"
    return left or "—", right or "—"


def render(p: dict, alerts: list, teeth: dict, plan: list, recs: list,
           rx_count: int, age: int | None, anam: dict | None = None,
           flag_labels: dict | None = None, lang: str = "ro") -> str:
    """`recs` — записи приёмов ХРОНОЛОГИЧЕСКИ (дневник читается сверху вниз).
    `anam` — опросник анамнеза, `flag_labels` — подписи его отметок."""
    e = html.escape
    lang = lang if lang in LANGS else "ro"
    t = _T[lang]
    other = "ru" if lang == "ro" else "ro"
    plan_ro = _PLAN_RO if lang == "ro" else _PLAN_RU
    clinic = e(eng.CLINIC_NAME)
    addr = e((eng.CONFIG or {}).get("address", {}).get(lang, "")
             or (eng.CONFIG or {}).get("address", {}).get("ro", ""))
    phone = e(eng.CLINIC_PHONE)
    file_no = (p.get("file_no") or "").strip() or str(p["id"])
    today = datetime.now(eng.TZ).strftime("%d.%m.%Y")

    an = anam or {}
    # аллергии на бланке — из обоих источников: опросник (собран заранее) и
    # предупреждения фиши (их ставят по ходу лечения)
    allergy = "; ".join(x for x in [
        (an.get("alergii") or "").strip(),
        "; ".join(a["text"] for a in alerts if a["kind"] == "allergy"),
    ] if x)
    mentions = "; ".join(a["text"] for a in alerts
                         if a["kind"] in ("medication", "warning"))
    marked = [lab for k, lab in (flag_labels or {}).items()
              if k in set((an.get("flags") or "").split(","))]
    # раздел «Bolile suportate»: сперва отмеченное в опроснике, затем дописанное
    boli = "; ".join(x for x in [", ".join(marked),
                                 (an.get("boli") or "").strip()] if x)
    medicamente = (an.get("medicamente") or "").strip()
    anestezie = (an.get("anestezie") or "").strip()
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
        birth += f" ({age} {t['years']})"

    # диагноз титульной части — последний непустой из дневника
    diag = next((r["diagnostic"].strip() for r in reversed(recs)
                 if (r.get("diagnostic") or "").strip()), "")

    tooth_notes = "; ".join(
        f"{num} — {e((row.get('note') or '').strip())}"
        for num, row in sorted(teeth.items()) if (row.get("note") or "").strip())
    # молочный ряд печатается только там, где он осмыслен: есть записи по
    # молочным зубам либо пациенту меньше 14 лет
    has_milk = (any(50 < t < 90 for t in teeth)
                or (age is not None and age < 14))

    plan_rows = "".join(
        f"<tr><td>{it['tooth'] or '—'}</td><td>{e(it['procedure'])}</td>"
        f"<td>{e(it['doctor']) or '—'}</td>"
        f"<td>{plan_ro.get(it['status'], it['status'])}</td>"
        f"<td>{it['price_mdl'] or '—'}</td></tr>"
        for it in plan)
    plan_html = (f"<table class='ft'><tr><th>{t['p_tooth']}</th>"
                 f"<th>{t['p_proc']}</th><th>{t['p_doc']}</th>"
                 f"<th>{t['p_state']}</th><th>{t['p_price']}</th></tr>"
                 f"{plan_rows}</table>" if plan
                 else f"<p class='line'>{_fill('', '_' * 60)}</p>")

    diary_rows = []
    for r in recs:
        left, right = _diary_cell(r, t)
        diary_rows.append(
            f"<tr><td style='white-space:nowrap'>{_dt(r['starts_at'])}</td>"
            f"<td>{left}</td><td>{right}</td>"
            f"<td class='sig'>{e(r.get('doctor') or '')}<br><br></td></tr>")
    # пустые строки: лист продолжает жить ручкой и после печати
    diary_rows += ["<tr class='empty'><td></td><td></td><td></td>"
                   "<td class='sig'></td></tr>"] * 3

    rx_note = (f" <small>({t['rx_note'].format(n=rx_count)})</small>"
               if rx_count else "")

    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t["title"]} — {e(p.get("name") or "pacient")}</title>
<style>{theme.paint(_CSS)}</style></head><body>

<div class="noprint">
  <button onclick="window.print()">{t["print"]}</button>
  <a href="/admin/patient/{p["id"]}/fisa043?lang={other}">{t["other"]}</a>
  <a href="/admin/patient/{p["id"]}">{t["back"]}</a>
</div>

<div class="hdr">
  <div>{theme.print_logo()}Ministerul Sănătății al Republicii Moldova<br>
  <b>{clinic}</b> · IDNO <span class="fill">«IDNO»</span><br>
  {addr or "<span class='fill'>«adresa»</span>"} · tel. {phone}</div>
  <div class="r">Formularul nr. <b>043/e</b><br>
  aprobat prin Ordinul MS RM<br>nr. 828 din 31.10.2011</div>
</div>

<h1>{t["h1"]}</h1>
<p class="sub">{t["nr"]} <b>{e(file_no)}</b> · {t["opened"]}
{_fill(p.get("created_at") and _dt(p["created_at"]).split(" ")[0], "__.__.____")}</p>

<h2>{t["s1"]}</h2>
<p class="line">{t["name"]}: <b>{_fill(p.get("name"),
"____________________________")}</b> · {t["sex"]}: {_fill(gender, "___")}</p>
<p class="line">{t["birth"]}: {_fill(birth)} · IDNP: {_fill(p.get("idnp"))} ·
{t["phone"]}: {_fill(p.get("phone"))}</p>
<p class="line">{t["addr"]}: {_fill(p.get("address"), "_" * 50)}</p>
<p class="line">{t["doctor"]}: {_fill(p.get("primary_doctor"))} ·
{t["insurance"]}: {_fill(p.get("insurance"))}</p>

<h2>{t["s2"]}</h2>
<p class="line">{t["allergy"]}: {_fill(allergy, "_" * 50)}</p>
{f"<p class='line'>{t['mentions']}: {e(mentions)}</p>" if mentions else ""}
<p class="line">{t["diseases"]}: {_fill(boli, "_" * 44)}</p>
<p class="line">{t["meds"]}: {_fill(medicamente, "_" * 48)}</p>
<p class="line">{t["anesth"]}: {_fill(anestezie, "_" * 50)}</p>

<h2>{t["s3"]}</h2>
<table class="od">{_od_rows(teeth, has_milk)}</table>
<p class="legend">{_LEGEND[lang]}</p>
{f"<p class='tnotes'><b>{t['tnotes']}:</b> {tooth_notes}</p>" if tooth_notes else ""}

<h2>{t["s4"]}</h2>
<p class="line">{t["mucosa"]}: {_fill("", "_" * 40)}</p>
<p class="line">{t["occl"]}: {_fill("", "_" * 30)} ·
{t["rx"]}:{rx_note} {_fill("", "_" * 20)}</p>
<p class="line">{t["diag"]}: {_fill(diag, "_" * 56)}</p>

<h2>{t["s5"]}</h2>
{plan_html}

<h2>{t["s6"]}</h2>
<table class="ft">
<tr><th>{t["j_date"]}</th><th>{t["j_left"]}</th>
<th>{t["j_right"]}</th>
<th class="sig">{t["j_sign"]}</th></tr>
{"".join(diary_rows)}
</table>

<p class="foot">{t["foot"].format(no=e(file_no), date=today)}</p>

</body></html>"""
