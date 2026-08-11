"""Печатный «Acord informat» к плану лечения — согласие на вмешательство.

⚠️ Это ДРУГОЙ документ, чем `acord.py`. Тот — про персональные данные (закон
195/2024): «мы обрабатываем ваши данные вот на таких основаниях». Этот — про
медицинское вмешательство: «вам объяснили, что и зачем сделают, чем рискуете,
сколько стоит и какие есть альтернативы — вы согласны». Основания разные, и
подписи тоже: один лист не заменяет второй.

Норма — **ст. 13 Legea nr. 263/2005**:
  (2) для вмешательств с повышенным риском (инвазивных или хирургических)
      согласие оформляется ОБЯЗАТЕЛЬНО письменно, специальным формуляром
      медицинской документации, именуемым `acord informat`; список таких
      вмешательств и модель формуляра утверждает МЗ — Ordinul MS nr. 303 din
      06.05.2010 (модель — приложение к нему).
  (3) содержание: цель, ожидаемый эффект, методы вмешательства, потенциальный
      риск, возможные последствия — медико-социальные, психологические,
      ЭКОНОМИЧЕСКИЕ, — а также альтернативные варианты лечения.
  (5) ОТКАЗ оформляется записью в медицинской документации С УКАЗАНИЕМ
      возможных последствий и подписывается пациентом и лечащим врачом.
Отсюда состав листа: план как «методы», цены как «экономические последствия»,
разделы риска и альтернатив, и отдельный блок отказа со своей подписью.

⭐ Подписи ДВЕ и они не симметричны. Пациент подтверждает, что понял; врач —
что объяснил («Confirm că am explicat pacientului caracterul, scopul,
beneficiile și riscul procedurilor descrise» из модели). Убрать вторую —
значит оставить документ, из которого не следует, что информирование было.

Пиксельного совпадения с типографским бланком не обещаем — как и в fisa043.py:
приложение к приказу 303 в открытом доступе не публикуется, у нас на руках его
воспроизведение в операционной процедуре IMSP. Совпадает СОСТАВ и порядок
частей, а заголовок называет и закон, и приказ.

Незаполненное печатается жёлтым пропуском под ручку (приём acord.py/fisa043):
диагноз, риски и альтернативы — слова ВРАЧА про этого пациента, и подставить
их из базы не из чего. ⛔ Не заполнять их шаблоном молча: подписанный лист,
где риск описан программой, а не врачом, хуже пустой строки.

Страница самостоятельная (не `_shell`) — лист для принтера.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta

from ... import engine as eng
from ...core import theme
from ...core.layout import _ic

# сколько дней держится смета. Не настройка: 30 дней — обычный срок оферты, а
# лишний переключатель в настройках клиники стоит дороже, чем правка тут
OFFER_DAYS = 30

_CSS = """
 *{box-sizing:border-box}
 body{font-family:Georgia,'Times New Roman',serif;max-width:760px;margin:18px auto;
      padding:0 16px;color:#111;line-height:1.5;font-size:13px}
 h1{font-size:17px;text-align:center;margin:6px 0 2px}
 .sub{text-align:center;color:#555;font-size:12px;margin:0 0 14px}
 h2{font-size:13.5px;margin:12px 0 4px}
 .fill{background:#FFF3B0;padding:0 6px}
 .pbox{border:1px solid #999;padding:8px 12px;margin:10px 0;font-size:13px}
 .pbox b{font-size:14px}
 table{border-collapse:collapse;width:100%;font-size:12px;margin:4px 0}
 th,td{border:1px solid #999;padding:4px 6px;text-align:left;vertical-align:top}
 th{background:#f2f2f2;font-weight:600}
 td.n{text-align:right;white-space:nowrap}
 tr.tot td{font-weight:700;background:#f7f7f7}
 .lines{margin:2px 0 8px}
 .lines i{display:block;border-bottom:1px solid #bbb;height:15px;font-style:normal}
 .decl{margin:12px 0 4px;font-size:13px}
 .sign{margin:8px 0 0;display:flex;justify-content:space-between;font-size:13px}
 .medbox{border:1px solid #999;padding:8px 12px;margin:10px 0}
 /* блок отказа обведён жирнее остального: на подписанном листе он читается
    первым, потому что именно из-за него лист потом достают из архива */
 .refuz{border:2px solid #111;padding:8px 12px;margin:14px 0}
 .refuz table{margin-top:6px}
 .small{font-size:11px;color:#444}
 .foot{margin-top:14px;font-size:10px;color:#777;text-align:center}
 .noprint{display:flex;gap:10px;justify-content:center;margin:0 0 14px}
 .noprint button{background:__ACCENT__;color:__ON__;border:none;border-radius:8px;
      padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
 .noprint a{align-self:center;color:__ACCENT__;font-family:system-ui,sans-serif;font-size:14px}
 .clogo{display:block;max-height:16mm;max-width:45mm;object-fit:contain;margin:0 auto 3mm}
 @media print{.noprint{display:none}body{margin:0 auto}
   .refuz{break-inside:avoid}.medbox{break-inside:avoid}}
"""

# Двуязычные тексты — как в acord.py и fisa043.py: один словарь, ключи
# одинаковые. ⛔ Не переводятся: «Legea nr. 263/2005», «Ordinul MS nr. 303»,
# «acord informat» (официальное название формуляра — по нему лист опознаёт
# проверяющий), IDNP, MDL. Правишь смысл — правь ОБА языка.
_T = {
    "ro": {
        "title": "Acord informat",
        "print": _ic("print") + " Printează",
        "back": _ic("chev-l") + " Fișa pacientului",
        "other": "Русская версия",
        "h1": "ACORD INFORMAT LA INTERVENȚIA MEDICALĂ",
        "sub": ("plan de tratament stomatologic · art. 13 din Legea "
                "nr. 263/2005 cu privire la drepturile și responsabilitățile "
                "pacientului; Ordinul MS nr. 303 din 06.05.2010"),
        "name_blank": "nume, prenume: ____________________________",
        "birth": "Data nașterii", "phone": "Telefon", "file": "Fișa nr.",
        "clinic_h": "Prestatorul de servicii medicale",
        "h_diag": "1. Diagnosticul și starea actuală",
        "h_plan": "2. Intervențiile propuse și costul lor",
        "p_tooth": "Dinte", "p_proc": "Procedura (metoda intervenției)",
        "p_doc": "Medic", "p_term": "Termen", "p_price": "Preț (MDL)",
        "p_total": "Total",
        "plan_empty": "Planul de tratament nu conține poziții active.",
        "offer": ("Costul este estimativ și valabil {days} de zile, până la "
                  "{until}. Modificarea planului în urma evoluției clinice se "
                  "discută cu pacientul și se consemnează în fișă."),
        "h_scop": "3. Scopul intervenției și efectul scontat",
        "scop": ("Restabilirea funcției masticatorii, înlăturarea focarelor de "
                 "infecție și a durerii, păstrarea dinților naturali și "
                 "prevenirea complicațiilor. Rezultatul așteptat în cazul de "
                 "față:"),
        "h_risc": "4. Riscul potențial și efectele secundare",
        "risc": ("Orice intervenție stomatologică poate fi însoțită de durere "
                 "și edem postoperator, sângerare, reacție la anestezic, "
                 "infectarea plăgii, lezarea dinților vecini sau a "
                 "obturațiilor, fracturarea instrumentarului în canal, "
                 "necesitatea repetării sau schimbării tratamentului. "
                 "Riscurile specifice acestui caz:"),
        "h_alt": "5. Variantele alternative de tratament și îngrijire",
        "alt": ("Mi-au fost prezentate și alte variante posibile, inclusiv "
                "amânarea tratamentului, cu costurile și urmările fiecăreia:"),
        "h_urm": "6. Consecințele posibile în cazul neefectuării tratamentului",
        "urm": ("Evoluția afecțiunii, agravarea durerii, pierderea dintelui, "
                "răspândirea infecției. În cazul de față:"),
        "decl_h": "Declarația pacientului",
        "decl": ("Am înțeles tot ce mi-a explicat medicul și am primit răspuns "
                 "la toate întrebările mele. Benevol îmi exprim consimțământul "
                 "conștient pentru efectuarea intervențiilor descrise mai sus. "
                 "Îmi asum responsabilitatea pentru nerespectarea "
                 "recomandărilor primite. Știu că pot renunța la tratament în "
                 "orice etapă."),
        "date": "Data", "sign_p": "Semnătura pacientului",
        "minor": ("Pentru pacient minor sau pacient în privința căruia a fost "
                  "instituită o măsură de ocrotire judiciară — reprezentantul "
                  "legal: nume ______________________ "
                  "semnătura ______________"),
        "med_h": "Declarația medicului",
        "med": ("Confirm că am explicat pacientului caracterul, scopul, "
                "beneficiile, riscul intervențiilor descrise și variantele "
                "alternative, într-un limbaj accesibil, și am răspuns la "
                "întrebările sale."),
        "med_name": "Medic curant", "sign_m": "Semnătura medicului",
        "ref_h": "Refuzul pacientului la intervenția medicală",
        "ref_sub": ("art. 13 alin. (5) din Legea nr. 263/2005 — refuzul se "
                    "consemnează în documentația medicală, cu indicarea "
                    "consecințelor posibile"),
        "ref_proc": "Procedura refuzată",
        "ref_why": "Motivul și consecințele explicate pacientului",
        "ref_date": "Data refuzului",
        "ref_decl": ("Refuz efectuarea intervențiilor de mai sus. Consecințele "
                     "posibile ale refuzului mi-au fost explicate și le-am "
                     "înțeles."),
        "foot": ("Fișa nr. {no} · formular generat de DentPilot la {date} · "
                 "exemplarul semnat se păstrează la fișa pacientului "
                 "(Ordinul MS nr. 828/2011)"),
        "ref_note": "",
    },
    "ru": {
        "title": "Информированное согласие",
        "print": _ic("print") + " Печать",
        "back": _ic("chev-l") + " Карта пациента",
        "other": "Versiunea română",
        "h1": "ИНФОРМИРОВАННОЕ СОГЛАСИЕ НА МЕДИЦИНСКОЕ ВМЕШАТЕЛЬСТВО",
        "sub": ("стоматологический план лечения · ст. 13 Закона РМ "
                "№ 263/2005 о правах и обязанностях пациента (Legea "
                "nr. 263/2005); Ordinul MS nr. 303 din 06.05.2010"),
        "name_blank": "фамилия, имя: ____________________________",
        "birth": "Дата рождения", "phone": "Телефон", "file": "Карта №",
        "clinic_h": "Поставщик медицинских услуг",
        "h_diag": "1. Диагноз и текущее состояние",
        "h_plan": "2. Предлагаемые вмешательства и их стоимость",
        "p_tooth": "Зуб", "p_proc": "Процедура (метод вмешательства)",
        "p_doc": "Врач", "p_term": "Срок", "p_price": "Цена (MDL)",
        "p_total": "Итого",
        "plan_empty": "В плане лечения нет активных позиций.",
        "offer": ("Стоимость ориентировочная и действительна {days} дней, до "
                  "{until}. Изменение плана по ходу лечения обсуждается с "
                  "пациентом и вносится в карту."),
        "h_scop": "3. Цель вмешательства и ожидаемый результат",
        "scop": ("Восстановление жевательной функции, устранение очагов "
                 "инфекции и боли, сохранение собственных зубов и "
                 "предупреждение осложнений. Ожидаемый результат в данном "
                 "случае:"),
        "h_risc": "4. Возможный риск и побочные эффекты",
        "risc": ("Любое стоматологическое вмешательство может сопровождаться "
                 "болью и отёком после процедуры, кровотечением, реакцией на "
                 "анестетик, инфицированием раны, повреждением соседних зубов "
                 "или пломб, отломом инструмента в канале, необходимостью "
                 "повторить или изменить лечение. Риски в данном случае:"),
        "h_alt": "5. Альтернативные варианты лечения и ухода",
        "alt": ("Мне представлены и другие возможные варианты, включая отказ "
                "от лечения сейчас, с их стоимостью и последствиями:"),
        "h_urm": "6. Возможные последствия, если лечение не проводить",
        "urm": ("Развитие заболевания, усиление боли, потеря зуба, "
                "распространение инфекции. В данном случае:"),
        "decl_h": "Заявление пациента",
        "decl": ("Я понял(а) всё, что объяснил врач, и получил(а) ответы на "
                 "все свои вопросы. Добровольно и осознанно даю согласие на "
                 "проведение описанных выше вмешательств. Принимаю на себя "
                 "ответственность за несоблюдение полученных рекомендаций. "
                 "Знаю, что могу отказаться от лечения на любом этапе."),
        "date": "Дата", "sign_p": "Подпись пациента",
        "minor": ("Для несовершеннолетнего пациента или пациента, в отношении "
                  "которого установлена мера судебной охраны, — законный "
                  "представитель: имя ______________________ "
                  "подпись ______________"),
        "med_h": "Заявление врача",
        "med": ("Подтверждаю, что объяснил(а) пациенту характер, цель, пользу, "
                "риск описанных вмешательств и альтернативные варианты "
                "доступным языком и ответил(а) на его вопросы."),
        "med_name": "Лечащий врач", "sign_m": "Подпись врача",
        "ref_h": "Отказ пациента от медицинского вмешательства",
        "ref_sub": ("ст. 13 ч. (5) Закона № 263/2005 — отказ вносится в "
                    "медицинскую документацию с указанием возможных "
                    "последствий"),
        "ref_proc": "Процедура, от которой отказались",
        "ref_why": "Причина и разъяснённые пациенту последствия",
        "ref_date": "Дата отказа",
        "ref_decl": ("Отказываюсь от проведения указанных выше вмешательств. "
                     "Возможные последствия отказа мне разъяснены и понятны."),
        "foot": ("Карта № {no} · бланк сформирован программой DentPilot "
                 "{date} · подписанный экземпляр хранится в карте пациента "
                 "(Ordinul MS nr. 828/2011)"),
        # ⚠️ та же оговорка, что в acord.py: подписывают тот лист, который
        # распечатали, но опорным остаётся румынский — он совпадает с
        # госязыком и с названием формуляра в приказе
        "ref_note": ("Перевод для удобства пациента. Юридически опорной "
                     "является версия на румынском языке (versiunea în limba "
                     "română)."),
    },
}

LANGS = ("ro", "ru")


def _fill(value: str | None, blank: str = "________________") -> str:
    """Значение из фиши или жёлтый пропуск — на бумаге видно, что вписать."""
    v = (value or "").strip()
    return html.escape(v) if v else f"<span class='fill'>{blank}</span>"


def _lines(n: int) -> str:
    """Пустые линейки под запись от руки. Не `<textarea>` и не пропуск в
    строке: риски и альтернативы — это несколько фраз, и врачу нужно место."""
    return "<div class='lines'>" + "<i></i>" * n + "</div>"


def medic_name(plan: list, patient: dict) -> str:
    """Кто подписывает как лечащий врач.

    Позиции плана несут СНАПШОТ имени врача, и у разных позиций он может быть
    разным. Один врач на все активные позиции — печатаем его; иначе берём
    `primary_doctor` из фиши; если и его нет — жёлтый пропуск. ⛔ Не выбирать
    «первого попавшегося»: подпись под чужим именем хуже пустой строки.
    """
    names = {(it.get("doctor") or "").strip()
             for it in plan if (it.get("doctor") or "").strip()}
    if len(names) == 1:
        return names.pop()
    return (patient.get("primary_doctor") or "").strip()


def render(p: dict, plan: list, diag: str = "", lang: str = "ro") -> str:
    """`plan` — ВСЕ позиции; активные идут в согласие, отказы — в блок отказа.

    Финализированное на лист не попадает: согласие подписывают ДО, а не после;
    печатать в нём уже сделанное значило бы просить согласия задним числом.
    """
    e = html.escape
    lang = lang if lang in LANGS else "ro"
    t = _T[lang]
    other = "ru" if lang == "ro" else "ro"
    clinic = e(eng.CLINIC_NAME)
    phone = e(eng.CLINIC_PHONE)
    addr = e((eng.CONFIG or {}).get("address", {}).get(lang, "")
             or (eng.CONFIG or {}).get("address", {}).get("ro", ""))
    file_no = (p.get("file_no") or "").strip() or str(p["id"])
    now = datetime.now(eng.TZ)
    today = now.strftime("%d.%m.%Y")
    until = (now + timedelta(days=OFFER_DAYS)).strftime("%d.%m.%Y")

    active = [it for it in plan if it["status"] in ("planificat", "in_lucru")]
    refused = [it for it in plan if it["status"] == "refuzat"]

    total = sum(it["price_mdl"] or 0 for it in active)
    rows = "".join(
        f"<tr><td>{it['tooth'] or '—'}</td><td>{e(it['procedure'])}</td>"
        f"<td>{e(it['doctor'] or '—')}</td>"
        f"<td>{e(str(it.get('due_date') or '')[:10]) or '—'}</td>"
        f"<td class='n'>{it['price_mdl'] or '—'}</td></tr>" for it in active)
    if active:
        plan_html = (
            f"<table><tr><th>{t['p_tooth']}</th><th>{t['p_proc']}</th>"
            f"<th>{t['p_doc']}</th><th>{t['p_term']}</th>"
            f"<th>{t['p_price']}</th></tr>{rows}"
            f"<tr class='tot'><td colspan='4'>{t['p_total']}</td>"
            f"<td class='n'>{total}</td></tr></table>"
            f"<p class='small'>{t['offer'].format(days=OFFER_DAYS, until=until)}</p>")
    else:
        plan_html = f"<p>{t['plan_empty']}</p>"

    # блок отказа печатается ТОЛЬКО когда отказы есть: пустая рамка «отказов
    # нет» на каждом листе учит не читать этот блок вовсе
    refuz_html = ""
    if refused:
        rrows = "".join(
            f"<tr><td>{(str(it['tooth']) + ' · ') if it['tooth'] else ''}"
            f"{e(it['procedure'])}</td>"
            f"<td>{e(it.get('refuz_motiv') or '')}</td>"
            f"<td>{it['done_at'].astimezone(eng.TZ).strftime('%d.%m.%Y') if hasattr(it.get('done_at'), 'astimezone') else '—'}</td>"
            f"</tr>" for it in refused)
        refuz_html = f"""<div class="refuz">
<b>{t["ref_h"]}</b><br><span class="small">{t["ref_sub"]}</span>
<table><tr><th>{t["ref_proc"]}</th><th>{t["ref_why"]}</th>
<th>{t["ref_date"]}</th></tr>{rrows}</table>
<p class="decl">{t["ref_decl"]}</p>
<div class="sign"><span>{t["date"]}: <b>{today}</b></span>
<span>{t["sign_p"]}: ______________________</span></div>
<div class="sign"><span></span>
<span>{t["sign_m"]}: ______________________</span></div>
</div>"""

    ref_note = (f"<p class='small' style='text-align:center'>{t['ref_note']}</p>"
                if t["ref_note"] else "")
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t["title"]} — {e(p.get("name") or "pacient")}</title>
<style>{theme.paint(_CSS)}</style></head><body>

<div class="noprint">
  <button onclick="window.print()">{t["print"]}</button>
  <a href="/admin/patient/{p["id"]}/plan-acord?lang={other}">{t["other"]}</a>
  <a href="/admin/patient/{p["id"]}">{t["back"]}</a>
</div>

{theme.print_logo()}
<h1>{t["h1"]}</h1>
<p class="sub">{t["sub"]}</p>

<div class="pbox">
<b>{_fill(p.get("name"), t["name_blank"])}</b><br>
{t["birth"]}: {_fill(p.get("birth_date"))} · IDNP: {_fill(p.get("idnp"))} ·
{t["phone"]}: {_fill(p.get("phone"))} · {t["file"]} {e(file_no)}<br>
{t["clinic_h"]}: <b>{clinic}</b>{(", " + addr) if addr else ""}, {phone}
</div>

<h2>{t["h_diag"]}</h2>
<p>{_fill(diag, "_" * 60)}</p>
{_lines(1)}

<h2>{t["h_plan"]}</h2>
{plan_html}

<h2>{t["h_scop"]}</h2>
<p>{t["scop"]}</p>
{_lines(2)}

<h2>{t["h_risc"]}</h2>
<p>{t["risc"]}</p>
{_lines(2)}

<h2>{t["h_alt"]}</h2>
<p>{t["alt"]}</p>
{_lines(2)}

<h2>{t["h_urm"]}</h2>
<p>{t["urm"]}</p>
{_lines(2)}

<p class="decl"><b>{t["decl_h"]}.</b> {t["decl"]}</p>
<div class="sign">
<span>{t["date"]}: <b>{today}</b></span>
<span>{t["sign_p"]}: ______________________</span>
</div>
<p class="small" style="margin-top:8px">{t["minor"]}</p>

<div class="medbox">
<b>{t["med_h"]}.</b> {t["med"]}
<div class="sign">
<span>{t["med_name"]}: {_fill(medic_name(plan, p))}</span>
<span>{t["sign_m"]}: ______________________</span>
</div>
</div>

{refuz_html}
{ref_note}
<p class="foot">{t["foot"].format(no=e(file_no), date=today)}</p>

</body></html>"""
