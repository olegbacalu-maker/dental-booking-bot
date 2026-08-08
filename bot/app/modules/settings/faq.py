"""Вопросы, которые клиника иначе задаёт по телефону.

Программа офлайн и local-first: документации в облаке нет, ссылка «читайте на
сайте» здесь не работает. Единственное место, где директор может что-то
прочитать, — сама программа, поэтому FAQ живёт страницей в настройках и
уезжает в сборку вместе с exe. Это же решает вопрос актуальности: текст
версионируется тем же коммитом, что и поведение, о котором он рассказывает.
Меняешь поведение — правь ответ ЗДЕСЬ, в том же диффе.

Аудитория — директор (страница под PERM_SETTINGS, как весь раздел): темы
директорские — бэкап, перенос, закон 195. Подсказки регистратуре сюда не
писать: она этой страницы не видит, им место в самих экранах журнала.

Каждый ответ обязан называть кнопки ТЕМИ словами, что стоят в интерфейсе
(«Descarcă datele pacientului», «Stare sistem»), — FAQ, отправляющий искать
несуществующую кнопку, хуже молчания. Факты, на которые ссылается текст:
MIN_PASS и CITESTE-MA.txt — backup.py; «токен не читается на другой машине» —
dpapi.py; ступени блокировки входа — auth._LOCK_STEPS (30 с … 15 мин).

Никакого JS: <details>/<summary> раскрываются браузером, и страница остаётся
живой даже там, где скрипты не загрузились.
"""
from __future__ import annotations

from ...core.layout import FEEDBACK_EMAIL
from . import backup as bkp

_CARD = ("style='border:1px solid var(--line);border-radius:var(--r-card);"
         "background:var(--panel);padding:12px 16px;margin:10px 0'")
_SUM = "style='cursor:pointer;font-weight:600;font-size:14px;color:var(--text)'"
_BODY = ("style='margin-top:10px;font-size:13px;line-height:1.6;"
         "color:var(--text2);max-width:720px'")


def _q(icon: str, question: str, answer: str) -> str:
    return (f"<details class='faq' {_CARD}><summary {_SUM}>{icon} {question}"
            f"</summary><div {_BODY}>{answer}</div></details>")


def render() -> str:
    p = "<p style='margin:0 0 8px'>"
    end = "</p>"
    items = [
        _q("💾", "Cât de des fac copii de rezervă și unde le păstrez?",
           f"{p}Recomandăm o copie <b>pe săptămână</b> — sau după orice zi cu "
           f"multe modificări. Se face din <b>Setări → Copie de rezervă</b>: "
           f"alegeți o parolă (minim {bkp.MIN_PASS} caractere) și salvați "
           f"arhiva.{end}"
           f"{p}Păstrați arhiva <b>în afara acestui calculator</b> — pe un "
           f"stick USB sau pe alt calculator. O copie păstrată lângă original "
           f"dispare împreună cu el (defectarea discului, furt, viruși).{end}"
           f"{p}⚠️ Parola arhivei <b>nu se salvează nicăieri</b> — notați-o "
           f"într-un loc sigur. Fără ea, arhiva nu poate fi deschisă de "
           f"nimeni, nici de noi.{end}"),

        _q("📦", "Cum deschid arhiva de rezervă fără DentPilot?",
           f"{p}Intenționat simplu: arhiva este un ZIP obișnuit, criptat "
           f"AES-256. Se deschide pe orice calculator cu <b>7-Zip</b> "
           f"(gratuit, www.7-zip.org) sau <b>WinRAR</b>, cu parola aleasă la "
           f"export — nu depindeți nici de DentPilot, nici de noi.{end}"
           f"{p}⚠️ Windows (Explorer) <b>nu poate</b> extrage acest tip de "
           f"arhivă și afișează o eroare — nu înseamnă că arhiva e stricată; "
           f"folosiți 7-Zip.{end}"
           f"{p}Înăuntru găsiți <b>CITESTE-MA.txt</b> (se deschide fără "
           f"parolă) cu pașii de restaurare și <b>CONTINUT.txt</b> — lista a "
           f"tot ce conține arhiva: câți pacienți, câte programări, care "
           f"fișier este care document.{end}"),

        _q("🖥️", "Mutăm programul pe alt calculator sau reinstalăm Windows — "
                  "ce se întâmplă cu datele?",
           f"{p}Toate datele stau în folderul programului. Copiați folderul "
           f"<b>întreg</b> pe calculatorul nou — sau restaurați din arhiva de "
           f"rezervă (pașii sunt în CITESTE-MA.txt din arhivă). Pacienții, "
           f"programările, documentele și PIN-urile de intrare rămân.{end}"
           f"{p}⚠️ Singurul lucru care trebuie reintrodus: <b>tokenul botului "
           f"Telegram</b> (Setări → Telegram Bot). Tokenul e criptat cu cheia "
           f"Windows a calculatorului vechi și pe altul nu poate fi citit. "
           f"Asta e o protecție, nu o defecțiune: un fișier copiat sau furat "
           f"nu dezvăluie tokenul clinicii.{end}"),

        _q("📶", "Pot deschide registrul de pe telefon?",
           f"{p}Da, în rețeaua clinicii: <b>Setări → Acces de pe telefon → "
           f"Activează accesul</b> (programul repornește), apoi scanați "
           f"codul QR de pe pagină cu telefonul conectat la Wi-Fi-ul "
           f"clinicii. Fiecare intră cu parola lui; din meniul browserului "
           f"alegeți «Adaugă pe ecranul principal» — registrul devine o "
           f"aplicație pe telefon.{end}"
           f"{p}Funcționează <b>doar în rețeaua clinicii</b> — de acasă nu "
           f"se deschide, iar asta e o protecție, nu un defect. Folosiți "
           f"rețeaua protejată a clinicii, nu cea pentru pacienți.{end}"
           f"{p}Dacă telefonul nu se conectează: pe pagina «Acces de pe "
           f"telefon» apăsați <b>«Creează regula de firewall»</b> și "
           f"confirmați în fereastra Windows; verificați și ca rețeaua "
           f"calculatorului să fie de tip «Private» în setările Windows."
           f"{end}"),

        _q("🔄", "Actualizarea programului șterge datele?",
           f"{p}<b>Nu.</b> Actualizarea înlocuiește doar fișierele "
           f"programului; baza de date, documentele și setările rămân "
           f"neatinse. Programul verifică singur dacă există o versiune nouă "
           f"— instalarea e un click în <b>Setări → Stare sistem</b>.{end}"
           f"{p}Nu e nevoie de o copie de rezervă specială înainte de "
           f"actualizare — dar o copie recentă e oricum o idee bună.{end}"),

        _q("🔑", "Am uitat parola de intrare — ce fac?",
           f"{p}Dacă în clinică există alt <b>director</b>, el poate seta o "
           f"parolă nouă pentru oricine: <b>Setări → Securitate și "
           f"utilizatori</b>.{end}"
           f"{p}Dacă parola uitată e a singurului director — scrieți-ne la "
           f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>. Există o "
           f"procedură de deblocare; datele clinicii <b>nu se pierd</b>.{end}"
           f"{p}După mai multe încercări greșite, intrarea se blochează "
           f"temporar (de la 30 de secunde la 15 minute) — e o protecție "
           f"împotriva ghicirii; așteptați și încercați din nou.{end}"),

        _q("⚖️", "Ce cere Legea 195 și cu ce mă ajută programul?",
           f"{p}Legea 195/2024 (protecția datelor personale) dă pacientului "
           f"dreptul la o copie a datelor lui și dreptul la ștergere. "
           f"Ambele sunt în fișa pacientului: <b>«Descarcă datele "
           f"pacientului»</b> — arhivă cu tot ce știe programul despre el; "
           f"<b>«Șterge datele personale»</b> — ștergerea la cerere.{end}"
           f"{p}Formularul personal de informare (cu datele pacientului "
           f"completate automat) se tipărește din fișă: <b>«Informare / acord "
           f"— tipărire»</b>. Exemplarul semnat îl scanați sau fotografiați "
           f"și îl încărcați la documentele pacientului — așa dovada "
           f"semnăturii rămâne în program.{end}"
           f"{p}Datele stau <b>doar pe acest calculator</b> — nimic nu pleacă "
           f"pe servere străine. Documentele generale (informarea de la "
           f"recepție, registrul de evidență) le primiți de la furnizor.{end}"
           f"{p}Recomandat: criptarea discului (BitLocker) — starea ei se "
           f"vede în <b>Setări → Stare sistem</b>.{end}"),

        _q("📁", "Unde sunt datele clinicii și ce nu trebuie atins?",
           f"{p}Totul e în folderul programului: <b>data\\dental.db</b> — "
           f"toată evidența; <b>data\\files\\</b> — documentele pacienților; "
           f"<b>clinic.json</b> — profilul clinicii.{end}"
           f"{p}⚠️ Nu ștergeți, nu redenumiți și nu «faceți curat» în aceste "
           f"fișiere din Windows — programul le leagă între ele, iar orice "
           f"ștergere se face din program. Pentru orice nelămurire: "
           f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>.{end}"),
    ]
    return ("<h2>❓ Întrebări frecvente</h2>"
            "<p class='hint' style='margin-top:0'>Apăsați pe o întrebare "
            "pentru răspuns. Nu găsiți răspunsul? Scrieți-ne la "
            f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>.</p>"
            + "".join(items))
