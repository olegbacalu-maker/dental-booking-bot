"""Справочник вопросов анамнеза — отдельным модулем, потому что подписи нужны
ТРЁМ потребителям: фише (routes.py), печатной 043/e (fisa043.py) и выгрузке
по 195-му (export.py). Держать их в routes.py нельзя: export.py импортируется
самим routes.py, и обратный импорт замкнул бы круг.

Опросник — то, что меняет ТАКТИКУ приёма (анестезия, кровотечение,
инфекционный контроль), а не медицинская карта целиком: её клиника не ведёт.
Ключ хранится в базе строкой, подписи живут здесь — добавить вопрос значит
дописать по строке в оба языка, миграция не нужна.

⚠️ Наборы ключей ro и ru обязаны совпадать: подпись ищется по ключу, и
пропущенный перевод молча напечатает ключ вместо вопроса.
"""
from __future__ import annotations

from ...core import theme

FLAGS = {
    "ro": {
        "cardio": "Boli cardiovasculare / hipertensiune",
        "diabet": "Diabet zaharat",
        "coagulare": "Tulburări de coagulare / anticoagulante",
        "hepatita": "Hepatită",
        "hiv": "HIV / SIDA",
        "tuberculoza": "Tuberculoză",
        "epilepsie": "Epilepsie",
        "astm": "Astm bronșic",
        "renale": "Boli renale",
        "tiroida": "Afecțiuni tiroidiene",
        "sarcina": "Sarcină / alăptare",
        "fumat": "Fumător",
    },
    "ru": {
        "cardio": "Сердечно-сосудистые заболевания / гипертония",
        "diabet": "Сахарный диабет",
        "coagulare": "Нарушения свёртываемости / антикоагулянты",
        "hepatita": "Гепатит",
        "hiv": "ВИЧ / СПИД",
        "tuberculoza": "Туберкулёз",
        "epilepsie": "Эпилепсия",
        "astm": "Бронхиальная астма",
        "renale": "Заболевания почек",
        "tiroida": "Заболевания щитовидной железы",
        "sarcina": "Беременность / кормление",
        "fumat": "Курит",
    },
}

# (ключ поля, подпись в фише, подсказка-плейсхолдер) — панель только румынская
TEXTS = (
    ("boli", "Alte boli suportate / concomitente", "ex. ulcer gastric operat 2019"),
    ("medicamente", "Medicamente administrate curent", "denumire, doză"),
    ("alergii", "Alergii (medicamente, materiale)", "ex. penicilină, latex"),
    ("anestezie", "Reacții la anestezice", "ex. lipotimie la lidocaină"),
)

# подписи свободных полей на печатном листе — по-русски тоже
TEXT_LABELS = {
    "ro": {"boli": "Alte boli", "medicamente": "Medicamente",
           "alergii": "Alergii", "anestezie": "Reacții la anestezice"},
    "ru": {"boli": "Другие заболевания", "medicamente": "Лекарства",
           "alergii": "Аллергии", "anestezie": "Реакции на анестетики"},
}


# --- печатный бланк для пациента ---
# Спрашивать двенадцать пунктов голосом через стойку неудобно и небыстро:
# пациент заполняет лист, пока ждёт, а рецепция переносит ответы в программу.
# Бланк НЕ хранится как документ: источник истины — то, что введено в фишу
# (иначе появилось бы два расходящихся анамнеза). Подписанный лист клиника
# при желании сканирует в документы пациента, как и лист информирования.
_FORM_T = {
    "ro": {
        "title": "Chestionar medical",
        "h1": "CHESTIONAR MEDICAL AL PACIENTULUI",
        "lead": ("Vă rugăm să completați acest chestionar înainte de "
                 "tratament. Informația este necesară pentru siguranța "
                 "dumneavoastră: unele afecțiuni și medicamente schimbă "
                 "anestezia și tratamentul."),
        "pat": "Pacient", "birth": "Data nașterii",
        "q_head": "Suferiți sau ați suferit de:",
        "yes": "DA", "no": "NU",
        "free_head": "Completați, dacă este cazul:",
        "date": "Data", "sign": "Semnătura pacientului",
        "minor": ("Pentru pacient minor — semnătura reprezentantului legal: "
                  "______________________"),
        "foot": ("Datele se prelucrează conform Legii nr. 195/2024 · "
                 "formular generat de DentPilot la {date}"),
    },
    "ru": {
        "title": "Медицинская анкета",
        "h1": "МЕДИЦИНСКАЯ АНКЕТА ПАЦИЕНТА",
        "lead": ("Пожалуйста, заполните анкету до начала лечения. Эти "
                 "сведения нужны для вашей безопасности: некоторые "
                 "заболевания и лекарства меняют анестезию и лечение."),
        "pat": "Пациент", "birth": "Дата рождения",
        "q_head": "Есть ли у вас (или были) следующие состояния:",
        "yes": "ДА", "no": "НЕТ",
        "free_head": "Заполните, если относится к вам:",
        "date": "Дата", "sign": "Подпись пациента",
        "minor": ("Для несовершеннолетнего — подпись законного "
                  "представителя: ______________________"),
        "foot": ("Данные обрабатываются согласно Закону № 195/2024 "
                 "(Legea nr. 195/2024) · бланк сформирован программой "
                 "DentPilot {date}"),
    },
}

_FORM_CSS = """
 *{box-sizing:border-box}
 body{font-family:Georgia,'Times New Roman',serif;max-width:760px;margin:18px auto;
      padding:0 16px;color:#111;line-height:1.5;font-size:13px}
 h1{font-size:17px;text-align:center;margin:6px 0 10px}
 .lead{font-size:12px;color:#444;margin:0 0 12px}
 .pbox{border:1px solid #999;padding:8px 12px;margin:0 0 12px}
 h2{font-size:13.5px;margin:14px 0 6px}
 table.q{border-collapse:collapse;width:100%}
 table.q td{padding:6px 4px;border-bottom:1px dotted #bbb;font-size:13px}
 table.q td.a{width:130px;white-space:nowrap;text-align:right;
      font-family:'Segoe UI Symbol',sans-serif}
 .fl{margin:10px 0 0;font-size:13px}
 .fl b{display:block;margin-bottom:2px;font-weight:600}
 .fl .ln{border-bottom:1px solid #999;height:19px}
 .sign{margin:16px 0 0;display:flex;justify-content:space-between;font-size:13px}
 .small{font-size:11px;color:#444;margin-top:8px}
 .foot{margin-top:14px;font-size:10px;color:#777;text-align:center}
 .noprint{display:flex;gap:10px;justify-content:center;margin:0 0 14px}
 .noprint button{background:__ACCENT__;color:__ON__;border:none;border-radius:8px;
      padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
 .noprint a{align-self:center;color:__ACCENT__;font-family:system-ui,sans-serif;font-size:14px}
 .clogo{display:block;max-height:16mm;max-width:45mm;object-fit:contain;margin-bottom:2mm}
 .clogo.c{margin:0 auto 3mm}
 @media print{.noprint{display:none}body{margin:0 auto}}
"""


def render_form(p: dict, lang: str = "ro") -> str:
    """Пустой бланк опросника с шапкой пациента — на принтер."""
    import html
    from datetime import datetime

    from ... import engine as eng

    lang = lang if lang in FLAGS else "ro"
    t = _FORM_T[lang]
    other = "ru" if lang == "ro" else "ro"
    e = html.escape
    today = datetime.now(eng.TZ).strftime("%d.%m.%Y")
    chk = "<span style='font-family:Segoe UI Symbol,sans-serif'>☐</span>"
    rows = "".join(
        f"<tr><td>{e(v)}</td>"
        f"<td class='a'>{chk} {t['yes']} &nbsp;&nbsp; {chk} {t['no']}</td></tr>"
        for v in FLAGS[lang].values())
    free = "".join(
        f"<div class='fl'><b>{e(TEXT_LABELS[lang][k])}:</b>"
        f"<div class='ln'></div><div class='ln'></div></div>"
        for k, _lab, _ph in TEXTS)
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t["title"]} — {e(p.get("name") or "")}</title>
<style>{theme.paint(_FORM_CSS)}</style></head><body>

<div class="noprint">
  <button onclick="window.print()">🖨 {t["title"]}</button>
  <a href="/admin/patient/{p["id"]}/anamneza/print?lang={other}">
    {"Русская версия" if lang == "ro" else "Versiunea română"}</a>
  <a href="/admin/patient/{p["id"]}">← {e(eng.CLINIC_NAME)}</a>
</div>

{theme.print_logo("clogo c")}
<h1>{t["h1"]}</h1>
<p class="lead">{t["lead"]}</p>

<div class="pbox">
{t["pat"]}: <b>{e(p.get("name") or "") or "____________________________"}</b><br>
{t["birth"]}: {e(p.get("birth_date") or "") or "____________"} ·
{e(eng.CLINIC_NAME)}
</div>

<h2>{t["q_head"]}</h2>
<table class="q">{rows}</table>

<h2>{t["free_head"]}</h2>
{free}

<div class="sign">
<span>{t["date"]}: ______________</span>
<span>{t["sign"]}: ______________________</span>
</div>
<p class="small">{t["minor"]}</p>

<p class="foot">{t["foot"].format(date=today)}</p>

</body></html>"""


def labels(lang: str = "ro") -> dict:
    return FLAGS.get(lang) or FLAGS["ro"]


def marked(flags: str, lang: str = "ro") -> list[str]:
    """Подписи отмеченного, в порядке справочника (а не в порядке галочек)."""
    have = {x for x in (flags or "").split(",") if x}
    lab = labels(lang)
    return [v for k, v in lab.items() if k in have]
