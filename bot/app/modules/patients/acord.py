"""Печатный «Informare și acord» для конкретного пациента (закон 195/2024).

Почему это ИНФОРМИРОВАНИЕ под подпись, а не «acord de prelucrare»: лечение и
мед.карта обрабатываются по договору мед.услуг и законной обязанности — эти
основания не отзываются, и строить их на согласии нельзя (отозванное согласие
против обязанности хранить карту — тупик, и на проверке CNPDCP это минус, а не
плюс). Настоящие согласия-галочки здесь только для необязательного: маркетинг
и фото. Логика оснований обязана совпадать с большим листом на стойке
(clinics/lege-195/1-informare-pacienti.html) — два документа, расходящиеся в
том, НА КАКОМ основании клиника лечит, хуже, чем ни одного.

Язык: ro (по умолчанию) и ru — берётся из фиши пациента, переключается ссылкой
на самой странице. Информирование, которое человек не может прочесть, не
информирует; половина пациентов Молдовы читает по-русски. ⚠️ Румынская версия
остаётся ОПОРНОЙ: она совпадает с листом на стойке и с гос.языком, поэтому
русский лист несёт об этом строку, а подписывают — тот, что распечатали.
Юридические имена (Legea 195/2024, CNPDCP, IDNO/IDNP) не переводятся.

Данные подставляются из фиши; незаполненное поле печатается жёлтым пропуском —
приём из документов lege-195: на бумаге видно, что дописать ручкой. IDNO
клиники в профиле нет — оно всегда жёлтым (вписывается один раз штампом или
ручкой; заводить поле в настройках ради одной строки не стали).

Подписанный лист сканируют и грузят в документы пациента — так факт подписи
попадает и в выгрузку по 195-му. Отметки «подписан» в базе нет намеренно:
источник истины — бумага с подписью, а не галочка, которую можно поставить
без бумаги.

Страница самостоятельная (не `_shell`): это лист для принтера, панель журнала
на нём — мусор. Паттерн тот же, что у QR-плаката: обычная навигация в том же
окне, печать — window.print() (в WebView2 работает, проверено QR-ом).
"""
from __future__ import annotations

import html
from datetime import datetime

from ... import engine as eng

_CSS = """
 *{box-sizing:border-box}
 body{font-family:Georgia,'Times New Roman',serif;max-width:760px;margin:18px auto;
      padding:0 16px;color:#111;line-height:1.5;font-size:13px}
 h1{font-size:17px;text-align:center;margin:6px 0 2px}
 .sub{text-align:center;color:#555;font-size:12px;margin:0 0 14px}
 h2{font-size:13.5px;margin:12px 0 4px}
 .fill{background:#FFF3B0;padding:0 6px;white-space:nowrap}
 ul{margin:4px 0;padding-left:20px}
 li{margin:2px 0}
 .pbox{border:1px solid #999;padding:8px 12px;margin:10px 0;font-size:13px}
 .pbox b{font-size:14px}
 .decl{margin:14px 0 4px;font-size:13px}
 .sign{margin:10px 0 0;display:flex;justify-content:space-between;font-size:13px}
 .cons{border:1px solid #999;padding:8px 12px;margin:12px 0}
 .cons .row{margin:6px 0}
 .chk{font-family:'Segoe UI Symbol',sans-serif}
 .small{font-size:11px;color:#444}
 .foot{margin-top:14px;font-size:10px;color:#777;text-align:center}
 .noprint{display:flex;gap:10px;justify-content:center;margin:0 0 14px}
 .noprint button{background:#0E9F8A;color:#fff;border:none;border-radius:8px;
      padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
 .noprint a{align-self:center;color:#0E9F8A;font-family:system-ui,sans-serif;font-size:14px}
 @media print{.noprint{display:none}body{margin:0 auto}}
"""

# Двуязычные тексты листа — по образцу engine.T_BASE: один словарь, ключи
# одинаковые в обоих языках. Правишь смысл — правь ОБА, иначе лист начнёт
# обещать разное разным людям.
_T = {
    "ro": {
        "title": "Informare și acord",
        "print": "🖨 Printează",
        "back": "← Fișa pacientului",
        "other": "Русская версия",
        "h1": ("Informare privind prelucrarea datelor cu caracter personal<br>"
               "și acordul pacientului"),
        "sub": "conform Legii nr. 195/2024 a Republicii Moldova",
        "name_blank": "nume, prenume: ____________________________",
        "birth": "Data nașterii", "phone": "Telefon", "addr": "Adresa",
        "h_op": "1. Operatorul de date",
        "op": "Clinica stomatologică",
        "op_tel": "telefon",
        "h_data": "2. Ce date prelucrăm și în ce temei",
        "li1": ("<b>date de identificare și contact</b> (nume, data nașterii, "
                "IDNP, telefon, adresă) și <b>date despre sănătate</b> — "
                "categorie specială: istoricul tratamentelor, planul de "
                "tratament, radiografii, alergii;"),
        "li2": ("programarea și evidența vizitelor — pentru încheierea și "
                "executarea <b>contractului de servicii medicale</b>;"),
        "li3": ("întocmirea și păstrarea documentației medicale — "
                "<b>obligație legală</b> a instituției medicale;"),
        "li4": ("remindere despre vizita programată — <b>interesul legitim</b> "
                "al clinicii; puteți renunța oricând, la recepție."),
        "h_store": "3. Unde se păstrează și cui se pot transmite",
        "store": ("Fișele electronice se păstrează <b>local, pe calculatorul "
                  "clinicii</b> (programul DentPilot) și nu sunt transmise "
                  "dezvoltatorului programului. Datele pot fi transmise doar "
                  "instituțiilor abilitate, la cererea legală a acestora, sau "
                  "altei instituții medicale, la solicitarea dvs. Documentația "
                  "medicală se păstrează pe durata prevăzută de legislație."),
        "h_rights": "4. Drepturile dvs.",
        "rights": ("Aveți dreptul la <b>acces</b> și la o copie completă a "
                   "datelor, la <b>rectificare</b>, la <b>ștergere</b> (în "
                   "măsura în care păstrarea nu este o obligație legală), la "
                   "<b>opoziție</b> față de remindere, precum și dreptul de a "
                   "depune <b>plângere</b> la CNPDCP (datepersonale.md). "
                   "Adresați-vă la recepție — răspundem în cel mult o lună."),
        "decl": "Declar că am primit și am înțeles informarea de mai sus.",
        "date": "Data", "sign": "Semnătura pacientului",
        "minor": ("Pentru pacient minor — reprezentantul legal: nume "
                  "______________________ semnătura ______________"),
        "opt_h": "Acorduri opționale",
        "opt_sub": ("nu condiționează tratamentul și pot fi retrase oricând, "
                    "la recepție:"),
        "opt_mkt": ("sunt de acord să primesc mesaje despre ofertele și "
                    "noutățile clinicii (marketing);"),
        "opt_photo": ("sunt de acord ca fotografiile tratamentului meu "
                      "(înainte/după) să fie folosite în materialele clinicii, "
                      "<b>fără nume</b> și fără alte date de identificare."),
        "foot": ("Fișa nr. {no} · formular generat de DentPilot la {date} · "
                 "exemplarul semnat se păstrează la clinică"),
        "ref": "",
    },
    "ru": {
        "title": "Информирование и согласие",
        "print": "🖨 Печать",
        "back": "← Карта пациента",
        "other": "Versiunea română",
        "h1": ("Информирование об обработке персональных данных<br>"
               "и согласие пациента"),
        "sub": "согласно Закону РМ № 195/2024 (Legea nr. 195/2024)",
        "name_blank": "фамилия, имя: ____________________________",
        "birth": "Дата рождения", "phone": "Телефон", "addr": "Адрес",
        "h_op": "1. Оператор данных",
        "op": "Стоматологическая клиника",
        "op_tel": "телефон",
        "h_data": "2. Какие данные обрабатываем и на каком основании",
        "li1": ("<b>данные для идентификации и связи</b> (имя, дата рождения, "
                "IDNP, телефон, адрес) и <b>данные о здоровье</b> — особая "
                "категория: история лечения, план лечения, рентгеновские "
                "снимки, аллергии;"),
        "li2": ("запись на приём и учёт визитов — для заключения и исполнения "
                "<b>договора об оказании медицинских услуг</b>;"),
        "li3": ("ведение и хранение медицинской документации — "
                "<b>обязанность по закону</b> для медицинского учреждения;"),
        "li4": ("напоминания о назначенном визите — <b>законный интерес</b> "
                "клиники; вы можете отказаться в любой момент на стойке."),
        "h_store": "3. Где хранятся и кому могут быть переданы",
        "store": ("Электронные карты хранятся <b>локально, на компьютере "
                  "клиники</b> (программа DentPilot) и не передаются "
                  "разработчику программы. Данные могут быть переданы только "
                  "уполномоченным органам по их законному запросу либо другому "
                  "медицинскому учреждению по вашей просьбе. Медицинская "
                  "документация хранится в течение срока, установленного "
                  "законодательством."),
        "h_rights": "4. Ваши права",
        "rights": ("Вы имеете право на <b>доступ</b> и полную копию данных, на "
                   "<b>исправление</b>, на <b>удаление</b> (в той мере, в "
                   "какой хранение не является обязанностью по закону), на "
                   "<b>возражение</b> против напоминаний, а также право подать "
                   "<b>жалобу</b> в CNPDCP (datepersonale.md). Обратитесь на "
                   "стойку — отвечаем не позднее одного месяца."),
        "decl": "Заявляю, что получил(а) и понял(а) изложенное выше.",
        "date": "Дата", "sign": "Подпись пациента",
        "minor": ("Для несовершеннолетнего пациента — законный представитель: "
                  "имя ______________________ подпись ______________"),
        "opt_h": "Необязательные согласия",
        "opt_sub": ("не влияют на лечение и могут быть отозваны в любой "
                    "момент на стойке:"),
        "opt_mkt": ("согласен(на) получать сообщения о предложениях и новостях "
                    "клиники (маркетинг);"),
        "opt_photo": ("согласен(на), чтобы фотографии моего лечения (до/после) "
                      "использовались в материалах клиники <b>без имени</b> и "
                      "без иных данных, позволяющих меня опознать."),
        "foot": ("Карта № {no} · бланк сформирован программой DentPilot "
                 "{date} · подписанный экземпляр хранится в клинике"),
        # ⚠️ опорной остаётся румынская версия: она совпадает с листом на
        # стойке и с гос.языком. Убрать эту строку — значит выдать перевод за
        # оригинал
        "ref": ("Перевод для удобства пациента. Юридически опорной является "
                "версия на румынском языке (versiunea în limba română)."),
    },
}

LANGS = ("ro", "ru")


def _fill(value: str | None, blank: str = "________________") -> str:
    """Значение из фиши или жёлтый пропуск — на бумаге видно, что вписать."""
    v = (value or "").strip()
    return html.escape(v) if v else f"<span class='fill'>{blank}</span>"


def render(p: dict, lang: str = "ro") -> str:
    e = html.escape
    lang = lang if lang in LANGS else "ro"
    t = _T[lang]
    other = "ru" if lang == "ro" else "ro"
    clinic = e(eng.CLINIC_NAME)
    phone = e(eng.CLINIC_PHONE)
    addr = e((eng.CONFIG or {}).get("address", {}).get(lang, "")
             or (eng.CONFIG or {}).get("address", {}).get("ro", ""))
    file_no = (p.get("file_no") or "").strip() or str(p["id"])
    today = datetime.now(eng.TZ).strftime("%d.%m.%Y")
    chk = "<span class='chk'>☐</span>"
    ref = f"<p class='small' style='text-align:center'>{t['ref']}</p>" if t["ref"] else ""
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t["title"]} — {e(p.get("name") or "pacient")}</title>
<style>{_CSS}</style></head><body>

<div class="noprint">
  <button onclick="window.print()">{t["print"]}</button>
  <a href="/admin/patient/{p["id"]}/acord?lang={other}">{t["other"]}</a>
  <a href="/admin/patient/{p["id"]}">{t["back"]}</a>
</div>

<h1>{t["h1"]}</h1>
<p class="sub">{t["sub"]}</p>

<div class="pbox">
<b>{_fill(p.get("name"), t["name_blank"])}</b><br>
{t["birth"]}: {_fill(p.get("birth_date"))} · IDNP: {_fill(p.get("idnp"))} ·
{t["phone"]}: {_fill(p.get("phone"))}<br>
{t["addr"]}: {_fill(p.get("address"), "________________________________________")}
</div>

<h2>{t["h_op"]}</h2>
<p>{t["op"]} <b>{clinic}</b>,
IDNO <span class="fill">«IDNO»</span>, {addr or "<span class='fill'>«adresa»</span>"},
{t["op_tel"]} {phone}.</p>

<h2>{t["h_data"]}</h2>
<ul>
<li>{t["li1"]}</li>
<li>{t["li2"]}</li>
<li>{t["li3"]}</li>
<li>{t["li4"]}</li>
</ul>

<h2>{t["h_store"]}</h2>
<p>{t["store"]}</p>

<h2>{t["h_rights"]}</h2>
<p>{t["rights"]}</p>

<p class="decl"><b>{t["decl"]}</b></p>
<div class="sign">
<span>{t["date"]}: <b>{today}</b></span>
<span>{t["sign"]}: ______________________</span>
</div>
<p class="small" style="margin-top:8px">{t["minor"]}</p>

<div class="cons">
<b>{t["opt_h"]}</b> — {t["opt_sub"]}
<div class="row">{chk} DA &nbsp; {chk} NU — {t["opt_mkt"]}</div>
<div class="row">{chk} DA &nbsp; {chk} NU — {t["opt_photo"]}</div>
</div>
{ref}
<p class="foot">{t["foot"].format(no=e(file_no), date=today)}</p>

</body></html>"""
