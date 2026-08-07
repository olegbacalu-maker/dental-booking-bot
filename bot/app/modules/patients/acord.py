"""Печатный «Informare și acord» для конкретного пациента (закон 195/2024).

Почему это ИНФОРМИРОВАНИЕ под подпись, а не «acord de prelucrare»: лечение и
мед.карта обрабатываются по договору мед.услуг и законной обязанности — эти
основания не отзываются, и строить их на согласии нельзя (отозванное согласие
против обязанности хранить карту — тупик, и на проверке CNPDCP это минус, а не
плюс). Настоящие согласия-галочки здесь только для необязательного: маркетинг
и фото. Логика оснований обязана совпадать с большим листом на стойке
(clinics/lege-195/1-informare-pacienti.html) — два документа, расходящиеся в
том, НА КАКОМ основании клиника лечит, хуже, чем ни одного.

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


def _fill(value: str | None, blank: str = "________________") -> str:
    """Значение из фиши или жёлтый пропуск — на бумаге видно, что вписать."""
    v = (value or "").strip()
    return html.escape(v) if v else f"<span class='fill'>{blank}</span>"


def render(p: dict) -> str:
    e = html.escape
    clinic = e(eng.CLINIC_NAME)
    phone = e(eng.CLINIC_PHONE)
    addr = e((eng.CONFIG or {}).get("address", {}).get("ro", ""))
    file_no = (p.get("file_no") or "").strip() or str(p["id"])
    today = datetime.now(eng.TZ).strftime("%d.%m.%Y")
    chk = "<span class='chk'>☐</span>"
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informare și acord — {e(p.get("name") or "pacient")}</title>
<style>{_CSS}</style></head><body>

<div class="noprint">
  <button onclick="window.print()">🖨 Printează</button>
  <a href="/admin/patient/{p["id"]}">← Fișa pacientului</a>
</div>

<h1>Informare privind prelucrarea datelor cu caracter personal<br>
și acordul pacientului</h1>
<p class="sub">conform Legii nr. 195/2024 a Republicii Moldova</p>

<div class="pbox">
<b>{_fill(p.get("name"), "nume, prenume: ____________________________")}</b><br>
Data nașterii: {_fill(p.get("birth_date"))} · IDNP: {_fill(p.get("idnp"))} ·
Telefon: {_fill(p.get("phone"))}<br>
Adresa: {_fill(p.get("address"), "________________________________________")}
</div>

<h2>1. Operatorul de date</h2>
<p>Clinica stomatologică <b>{clinic}</b>,
IDNO <span class="fill">«IDNO»</span>, {addr or "<span class='fill'>«adresa»</span>"},
telefon {phone}.</p>

<h2>2. Ce date prelucrăm și în ce temei</h2>
<ul>
<li><b>date de identificare și contact</b> (nume, data nașterii, IDNP, telefon,
adresă) și <b>date despre sănătate</b> — categorie specială: istoricul
tratamentelor, planul de tratament, radiografii, alergii;</li>
<li>programarea și evidența vizitelor — pentru încheierea și executarea
<b>contractului de servicii medicale</b>;</li>
<li>întocmirea și păstrarea documentației medicale — <b>obligație legală</b> a
instituției medicale;</li>
<li>remindere despre vizita programată — <b>interesul legitim</b> al clinicii;
puteți renunța oricând, la recepție.</li>
</ul>

<h2>3. Unde se păstrează și cui se pot transmite</h2>
<p>Fișele electronice se păstrează <b>local, pe calculatorul clinicii</b>
(programul DentPilot) și nu sunt transmise dezvoltatorului programului. Datele
pot fi transmise doar instituțiilor abilitate, la cererea legală a acestora,
sau altei instituții medicale, la solicitarea dvs. Documentația medicală se
păstrează pe durata prevăzută de legislație.</p>

<h2>4. Drepturile dvs.</h2>
<p>Aveți dreptul la <b>acces</b> și la o copie completă a datelor, la
<b>rectificare</b>, la <b>ștergere</b> (în măsura în care păstrarea nu este o
obligație legală), la <b>opoziție</b> față de remindere, precum și dreptul de a
depune <b>plângere</b> la CNPDCP (datepersonale.md). Adresați-vă la recepție —
răspundem în cel mult o lună.</p>

<p class="decl"><b>Declar că am primit și am înțeles informarea de mai sus.</b></p>
<div class="sign">
<span>Data: <b>{today}</b></span>
<span>Semnătura pacientului: ______________________</span>
</div>
<p class="small" style="margin-top:8px">Pentru pacient minor — reprezentantul
legal: nume ______________________ semnătura ______________</p>

<div class="cons">
<b>Acorduri opționale</b> — nu condiționează tratamentul și pot fi retrase
oricând, la recepție:
<div class="row">{chk} DA &nbsp; {chk} NU — sunt de acord să primesc mesaje
despre ofertele și noutățile clinicii (marketing);</div>
<div class="row">{chk} DA &nbsp; {chk} NU — sunt de acord ca fotografiile
tratamentului meu (înainte/după) să fie folosite în materialele clinicii,
<b>fără nume</b> și fără alte date de identificare.</div>
</div>

<p class="foot">Fișa nr. {e(file_no)} · formular generat de DentPilot
la {today} · exemplarul semnat se păstrează la clinică</p>

</body></html>"""
