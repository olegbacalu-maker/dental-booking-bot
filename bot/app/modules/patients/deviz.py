"""Печатный «Deviz» плана лечения — смета пациенту на руки.

Что предлагаем, на каком зубе и сколько стоит. Это НЕ согласие: юридического
текста ст. 13 Legea 263/2005 здесь нет — для этого есть `plan_acord.py`, и
один лист не заменяет другой. Внизу две подписи: пациент — что с планом и
стоимостью ознакомлен, врач — под ценой, рядом место печати «L.Ș.». Смету
уносят домой, поэтому о пациенте на ней только имя и номер фиши: IDNP, дата
рождения и телефон смете не нужны (минимизация, закон 195).

Позиции — активные, `db.PLAN_ACTIVE` перечислением, в порядке плана фиши
(`card.plan_key`); итог — та же сумма, что «Total plan activ» фиши и Total
acord. Срок цены — тот же, что у acord (`plan_acord.OFFER_DAYS` и его фраза):
у одного плана не может быть двух сроков оферты.

Бланк «Documente» (`card.FORMS`) и подписывается на экране (`card.SIGNABLE`,
`sign.py`): `sign=` — режим подписи, как у `plan_acord.render`; без него лист
печатается с линиями под ручку.

Страница самостоятельная — лист для принтера, как соседние.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta

from ... import db
from ... import engine as eng
from ...core import theme
from ...core.layout import _ic
from . import acord as pacord
from . import card as pcard
from . import plan_acord as pplan

_CSS = """
 *{box-sizing:border-box}
 body{font-family:Georgia,'Times New Roman',serif;max-width:760px;margin:18px auto;
      padding:0 16px;color:#111;line-height:1.5;font-size:13px}
 .clinic{text-align:center;font-size:12px;color:#333;margin:0 0 10px}
 .clinic b{font-size:14px;color:#111}
 h1{font-size:17px;text-align:center;margin:10px 0 12px}
 .pbox{display:flex;flex-wrap:wrap;gap:4px 24px;border:1px solid #999;
       padding:8px 12px;margin:10px 0 12px;font-size:13px}
 table{border-collapse:collapse;width:100%;font-size:12.5px;margin:4px 0}
 th,td{border:1px solid #999;padding:5px 7px;text-align:left;vertical-align:top}
 th{background:#f2f2f2;font-weight:600}
 td.t{width:70px;text-align:center}
 td.n,th.n{text-align:right;white-space:nowrap;width:110px}
 tr.tot td{font-weight:700;background:#f7f7f7}
 .small{font-size:11px;color:#444}
 .empty{border:1px dashed #999;padding:14px;text-align:center;color:#444}
 .signs{margin-top:22px;break-inside:avoid}
 .sign{margin:10px 0 0;display:flex;justify-content:space-between;gap:16px;font-size:13px}
 .ls{display:flex;justify-content:flex-end;margin-top:8px}
 .ls span{width:34mm;height:22mm;border:1px dashed #999;border-radius:50%;display:flex;
      align-items:center;justify-content:center;color:#777;font-size:11px}
 .foot{margin-top:18px;font-size:10px;color:#777;text-align:center}
 .noprint{display:flex;gap:10px;justify-content:center;margin:0 0 14px}
 .noprint button{background:__ACCENT__;color:__ON__;border:none;border-radius:8px;
      padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
 .noprint a{align-self:center;color:__ACCENT__;font-family:system-ui,sans-serif;font-size:14px}
 .clogo{display:block;max-height:16mm;max-width:45mm;object-fit:contain;margin:0 auto 3mm}
 @media print{.noprint{display:none}body{margin:0 auto}}
"""

# Двуязычные тексты, как у соседних листов. ⛔ Не переводятся MDL, IDNO и
# «L.Ș.» (место печати — румынское сокращение на бумаге, как в Registre).
# Фраза срока — из `plan_acord._T` (`offer`): одна оферта на два листа.
_T = {
    "ro": {
        "title": "Deviz",
        "print": _ic("print") + " Printează",
        "back": _ic("chev-l") + " Fișa pacientului",
        "other": "Русская версия",
        "h1": "Plan de tratament — deviz estimativ",
        "patient": "Pacient", "file": "Fișa nr.", "date": "Data eliberării",
        "p_tooth": "Dinte", "p_proc": "Procedura", "p_price": "Preț (MDL)",
        "p_total": "Total estimat", "unpriced": "de stabilit",
        "no_price": ("{n} poziții fără preț — prețul se stabilește de medic.",
                     "1 poziție fără preț — prețul se stabilește de medic."),
        "empty": "Planul este gol: nu conține poziții active.",
        "ack": "Am luat cunoștință de planul de tratament și de costul lui.",
        "sign_p": "Semnătura pacientului", "rep": "reprezentantul legal",
        "medic": "Medic curant", "sign_m": "Semnătura medicului", "data": "Data",
        "foot": "Fișa nr. {no} · deviz generat de DentPilot la {date}",
    },
    "ru": {
        "title": "Смета",
        "print": _ic("print") + " Печать",
        "back": _ic("chev-l") + " Карта пациента",
        "other": "Versiunea română",
        "h1": "План лечения — предварительная смета",
        "patient": "Пациент", "file": "Карта №", "date": "Дата выдачи",
        "p_tooth": "Зуб", "p_proc": "Процедура", "p_price": "Цена (MDL)",
        "p_total": "Итого, ориентировочно", "unpriced": "уточняется",
        "no_price": ("Позиций без цены: {n} — цену определяет врач.",
                     "1 позиция без цены — цену определяет врач."),
        "empty": "План пуст: в нём нет активных позиций.",
        "ack": "С планом лечения и его стоимостью ознакомлен(а).",
        "sign_p": "Подпись пациента", "rep": "законный представитель",
        "medic": "Лечащий врач", "sign_m": "Подпись врача", "data": "Дата",
        "foot": "Карта № {no} · смета сформирована программой DentPilot {date}",
    },
}

LANGS = pplan.LANGS


def active_items(plan: list) -> list:
    """Позиции сметы: активные (перечислением), в порядке плана фиши."""
    return sorted((it for it in plan if it["status"] in db.PLAN_ACTIVE),
                  key=pcard.plan_key)


def total_of(items: list) -> int:
    """Итог сметы — формулой «Total plan activ» фиши (`card.plan_view`)."""
    return sum(it["price_mdl"] or 0 for it in items)


def _clinic_head(lang: str) -> str:
    """Шапка клиники: вывесочное имя, юрлицо с IDNO одной строкой, адрес и
    телефон. Пустые юрлицо/IDNO просто пропускаются — жёлтый пропуск
    «вписать от руки» в шапке сметы ни к чему."""
    e = html.escape
    lines = [f"<b>{e(eng.CLINIC_NAME)}</b>"]
    legal = []
    if eng.CLINIC_LEGAL and eng.CLINIC_LEGAL != eng.CLINIC_NAME:
        legal.append(e(eng.CLINIC_LEGAL))
    if eng.CLINIC_IDNO:
        legal.append(f"IDNO {e(eng.CLINIC_IDNO)}")
    if legal:
        lines.append(" · ".join(legal))
    addr = ((eng.CONFIG or {}).get("address", {}).get(lang, "")
            or (eng.CONFIG or {}).get("address", {}).get("ro", ""))
    contact = " · ".join(e(x) for x in (addr, eng.CLINIC_PHONE) if x)
    if contact:
        lines.append(contact)
    return "<div class='clinic'>" + "<br>".join(lines) + "</div>"


def _patient_sig(t: dict, sign: dict | None) -> str:
    """Подпись пациента: линия, его подпись или — за него — подпись
    представителя с именем. Отдельной строки представителя у сметы нет, и
    подпись за ребёнка без имени читалась бы как подпись самого пациента."""
    if sign and sign.get("signer") == "reprezentant":
        return (pacord.sig_img(sign.get("patient"))
                + f" <span class='small'>({t['rep']}: "
                f"{html.escape(sign.get('name') or '')})</span>")
    return pacord.sig_patient(sign)


def render(p: dict, plan: list, lang: str = "ro", back: str = "",
           sign: dict | None = None) -> str:
    """`plan` — ВСЕ позиции пациента; на лист идут только активные.
    `sign` — режим подписи на экране (`sign.py`): картинки вместо линий, A4,
    без кнопок; `{}` — предпросмотр окна подписи. ⛔ `sign=None` — печатный
    лист, как его открывают из фиши."""
    e = html.escape
    lang = lang if lang in LANGS else "ro"
    t = _T[lang]
    other = "ru" if lang == "ro" else "ro"
    other_href, back_href = pacord.sheet_nav(p["id"], "deviz", other, back)
    file_no = (p.get("file_no") or "").strip() or str(p["id"])
    now = datetime.now(eng.TZ)
    today = now.strftime("%d.%m.%Y")
    until = (now + timedelta(days=pplan.OFFER_DAYS)).strftime("%d.%m.%Y")

    items = active_items(plan)
    medic = pplan.medic_name(plan, p)
    if items:
        rows = "".join(
            f"<tr><td class='t'>{e(str(it['tooth'] or '—'))}</td>"
            f"<td>{e(it['procedure'])}</td>"
            f"<td class='n'>{it['price_mdl'] or t['unpriced']}</td></tr>" for it in items)
        unpriced = sum(1 for it in items if not it["price_mdl"])
        # без этой строки итог читался бы как полная цена плана
        note = ""
        if unpriced:
            many, one = t["no_price"]
            note = (f"<p class='small'>"
                    f"{one if unpriced == 1 else many.format(n=unpriced)}</p>")
        body = (
            f"<table><tr><th>{t['p_tooth']}</th><th>{t['p_proc']}</th>"
            f"<th class='n'>{t['p_price']}</th></tr>{rows}"
            f"<tr class='tot'><td colspan='2'>{t['p_total']}</td>"
            f"<td class='n'>{total_of(items)}</td></tr></table>{note}"
            f"<p class='small'>"
            f"{pplan._T[lang]['offer'].format(days=pplan.OFFER_DAYS, until=until)}</p>")
    else:
        body = f"<p class='empty'>{t['empty']}</p>"

    # пустой смете подписывать нечего (на экране её и не дают: `card.can_sign`)
    signs = "" if not items else f"""<div class="signs">
<p>{t["ack"]}</p>
<div class="sign"><span>{t["data"]}: <b>{today}</b></span>
<span>{t["sign_p"]}: {_patient_sig(t, sign)}</span></div>
<div class="sign"><span>{t["medic"]}: <b>{e(medic) if medic else pacord.LINE}</b></span>
<span>{t["sign_m"]}: {pacord.sig_img((sign or {}).get("doctor"))}</span></div>
<div class="ls"><span>L.Ș.</span></div>
</div>"""
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t["title"]} — {e(p.get("name") or "pacient")}</title>
<style>{theme.paint(_CSS)}{theme.PRINT_PAGE_CSS}{pacord.SIGN_CSS if sign is not None else ""}</style></head><body>
{"" if sign is not None else f"""
<div class="noprint">
  <button onclick="window.print()">{t["print"]}</button>
  <a href="{other_href}">{t["other"]}</a>
  <a href="{back_href}">{t["back"]}</a>
</div>
"""}
{theme.print_logo()}
{_clinic_head(lang)}
<h1>{t["h1"]}</h1>
<div class="pbox">
<span>{t["patient"]}: <b>{e(p.get("name") or "")}</b></span>
<span>{t["file"]} {e(file_no)}</span>
<span>{t["date"]}: <b>{today}</b></span>
</div>
{body}
{signs}
<p class="foot">{t["foot"].format(no=e(file_no), date=today)}</p>
</body></html>"""
