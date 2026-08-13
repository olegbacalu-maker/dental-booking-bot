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

from ...core.layout import FEEDBACK_EMAIL, _ic
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
        _q(_ic("save"), "Cât de des fac copii de rezervă și unde le păstrez?",
           f"{p}Recomandăm o copie <b>pe săptămână</b> — sau după orice zi cu "
           f"multe modificări. Se face din <b>Setări › Copie de rezervă</b>: "
           f"alegeți o parolă (minim {bkp.MIN_PASS} caractere) și salvați "
           f"arhiva.{end}"
           f"{p}Păstrați arhiva <b>în afara acestui calculator</b> — pe un "
           f"stick USB sau pe alt calculator. O copie păstrată lângă original "
           f"dispare împreună cu el (defectarea discului, furt, viruși).{end}"
           f"{p}{_ic('sos')} Parola arhivei <b>nu se salvează nicăieri</b> — notați-o "
           f"într-un loc sigur. Fără ea, arhiva nu poate fi deschisă de "
           f"nimeni, nici de noi.{end}"
           f"{p}Arhiva este <b>de sine stătătoare</b>: chiar dacă evidența de "
           f"pe calculator este criptată, baza dinăuntru nu este — o apără "
           f"parola arhivei. Așa o restaurați oriunde, fără foaia de "
           f"recuperare. Este și motivul pentru care parola arhivei contează "
           f"mai mult decât pare: ea singură ține toată evidența clinicii."
           f"{end}"),

        _q(_ic("box"), "Cum deschid arhiva de rezervă fără DentPilot?",
           f"{p}Intenționat simplu: arhiva este un ZIP obișnuit, criptat "
           f"AES-256. Se deschide pe orice calculator cu <b>7-Zip</b> "
           f"(gratuit, www.7-zip.org) sau <b>WinRAR</b>, cu parola aleasă la "
           f"export — nu depindeți nici de DentPilot, nici de noi.{end}"
           f"{p}{_ic('sos')} Windows (Explorer) <b>nu poate</b> extrage acest tip de "
           f"arhivă și afișează o eroare — nu înseamnă că arhiva e stricată; "
           f"folosiți 7-Zip.{end}"
           f"{p}{_ic('ban')} <b>Când restaurați</b> — din arhivă sau copiind o copie "
           f"zilnică din <b>data\\backups</b> — ștergeți întâi fișierele "
           f"<b>data\\dental.db-wal</b> și <b>data\\dental.db-shm</b>, dacă "
           f"există. Ele aparțin bazei vechi și, rămase pe loc, se aplică peste "
           f"cea restaurată: evidența revine la starea dinainte, <b>fără nicio "
           f"eroare</b> — arată exact ca o arhivă goală, deși arhiva este "
           f"întreagă. Pașii din CITESTE-MA.txt includ acest pas.{end}"
           f"{p}Înăuntru găsiți <b>CITESTE-MA.txt</b> (se deschide fără "
           f"parolă) cu pașii de restaurare și <b>CONTINUT.txt</b> — lista a "
           f"tot ce conține arhiva: câți pacienți, câte programări, care "
           f"fișier este care document.{end}"),

        _q(_ic("home"), "Mutăm programul pe alt calculator sau reinstalăm Windows — "
                  "ce se întâmplă cu datele?",
           f"{p}Toate datele stau în folderul programului. Copiați folderul "
           f"<b>întreg</b> pe calculatorul nou — sau restaurați din arhiva de "
           f"rezervă (pașii sunt în CITESTE-MA.txt din arhivă). Pacienții, "
           f"programările, documentele și PIN-urile de intrare rămân.{end}"
           f"{p}{_ic('sos')} <b>Dacă evidența este criptată</b> (Setări › Criptarea "
           f"evidenței), pe calculatorul nou programul vă va cere codul de pe "
           f"<b>foaia de recuperare</b> — cea tipărită la activarea criptării. "
           f"Luați-o cu dumneavoastră odată cu folderul: cheia este legată de "
           f"contul Windows vechi și pe altul nu poate fi citită. Fără foaie, "
           f"evidența copiată nu se deschide nici de noi.{end}"
           f"{p}{_ic('sos')} Trebuie reintrodus și <b>tokenul botului Telegram</b> "
           f"(Setări › Telegram Bot), din același motiv. Aici însă nu se pierde "
           f"nimic: tokenul se ia din nou de la @BotFather.{end}"
           f"{p}Ambele sunt protecții, nu defecțiuni: un folder copiat sau "
           f"furat nu dezvăluie nici evidența, nici tokenul clinicii.{end}"),

        _q(_ic("lock"), "Ce este criptarea evidenței?",
           f"{p}<b>O opțiune, nu o obligație.</b> Pentru Legea 195 măsura "
           f"tehnică este criptarea discului (BitLocker) — programul o verifică "
           f"singur și o arată în <b>Stare sistem</b>. Criptarea evidenței este "
           f"un plus, pentru clinicile care îl doresc; fără ea sunteți la fel "
           f"de în regulă cu legea.{end}"
           f"{p}Ce face: acum fișierul <b>data\\dental.db</b> este o bază "
           f"SQLite obișnuită și, copiată de pe calculator, se deschide cu "
           f"orice program. Criptarea o face inutilizabilă în afara acestui "
           f"calculator. Are sens mai ales dacă programul stă pe un laptop "
           f"care iese din clinică. Se activează din <b>Setări › Criptarea "
           f"evidenței</b>.{end}"
           f"{p}Ce cere în schimb: activarea tipărește o <b>foaie de "
           f"recuperare</b> cu un cod, iar foaia devine responsabilitatea "
           f"clinicii. Confirmarea se află chiar pe foaia tipărită — "
           f"intenționat, pentru că ea este singurul lucru care vă salvează "
           f"evidența la schimbarea calculatorului. Păstrați-o în mapa «Legea "
           f"195», lângă actul BitLocker — adică <b>nu în calculator</b>. "
           f"Pierderea ei nu poate fi reparată de nimeni, nici de noi. Dacă "
           f"această obligație vă pare în plus, nu activați criptarea: nu "
           f"pierdeți nimic din punct de vedere legal.{end}"
           f"{p}Codul <b>nu se cere niciodată</b> în lucrul obișnuit: nici la "
           f"pornire, nici la actualizare. Programul îl cere doar după "
           f"reinstalarea Windows, la mutarea pe alt calculator, la schimbarea "
           f"contului Windows sau a discului — atunci apare un singur ecran "
           f"care îl întreabă.{end}"
           f"{p}Ce NU face criptarea: nu vă apără de cineva care stă la acest "
           f"calculator, sub acest cont Windows — programul lucrează sub el, "
           f"deci tot ce descifrează programul descifrează și acea persoană. "
           f"Împotriva asta lucrează parola de intrare și blocarea ecranului "
           f"(Win+L), nu criptarea.{end}"
           f"{p}Se poate opri oricând: <b>«Oprește criptarea»</b> pe aceeași "
           f"pagină, cu o repornire. Datele nu se pierd.{end}"),

        _q(_ic("monitor"), "Vreau registrul pe două calculatoare — la recepție "
                           "și în cabinet. Se poate?",
           f"{p}Da, și nu se plătește separat pentru al doilea calculator. "
           f"Contează însă <b>cum</b>: programul rămâne instalat pe <b>un "
           f"singur</b> calculator, iar al doilea îl deschide în browser, prin "
           f"rețeaua clinicii. Lucrați amândoi în aceeași evidență, în același "
           f"timp — programarea făcută la recepție apare singură în cabinet, "
           f"în câteva secunde.{end}"
           f"{p}{_ic('ban')} <b>Nu instalați programul de două ori.</b> A doua "
           f"instalare pornește cu evidența ei, goală și cu totul separată: ce "
           f"se scrie la recepție nu se vede în cabinet, iar ambele programe "
           f"par că funcționează corect. E cea mai ușoară greșeală de făcut și "
           f"cea mai greu de observat — uneori abia după săptămâni.{end}"
           f"{p}<b>Pașii — o singură dată, câteva minute:</b>{end}"
           f"<ol style='margin:0 0 8px;padding-left:22px'>"
           f"<li><b>Alegeți calculatorul care ține programul</b> — cel care "
           f"stă pornit toată ziua, de obicei cel de la recepție. Acolo rămân "
           f"evidența și copiile de rezervă; celălalt nu păstrează nimic.</li>"
           f"<li>Pe <b>acel</b> calculator: <b>Setări › Acces din rețea › "
           f"«Activează accesul»</b>. Programul se repornește singur — este "
           f"normal.</li>"
           f"<li>Dacă pe pagină apare butonul <b>«Creează regula de "
           f"firewall»</b>, apăsați-l și confirmați fereastra prin care "
           f"Windows cere permisiunea. Fără ea, al doilea calculator nu "
           f"intră.</li>"
           f"<li>Tot pe acea pagină scrie <b>adresa</b>, de forma "
           f"<b>http://192.168.0.15:8088/admin</b>. Notați-o.</li>"
           f"<li>Pe <b>al doilea calculator</b>: deschideți Chrome sau Edge, "
           f"scrieți adresa, intrați cu parola dumneavoastră. Salvați-o la "
           f"favorite — sau, din meniul Edge, «Instalează acest site ca "
           f"aplicație»: atunci se deschide ca un program obișnuit, cu "
           f"iconiță pe ecran.</li></ol>"
           f"{p}{_ic('sos')} Calculatorul cu programul trebuie să fie "
           f"<b>pornit</b>: cât timp doarme sau e oprit, în cabinet nu se "
           f"deschide nimic. Opriți-i modul «Sleep» din setările Windows.{end}"
           f"{p}{_ic('sos')} Dacă adresa nu se mai deschide — de obicei după o "
           f"repornire a routerului — reveniți la <b>Setări › Acces din "
           f"rețea</b>: adresa nouă scrie acolo. Ca să nu se mai schimbe, "
           f"administratorul rețelei poate fixa adresa pe router.{end}"
           f"{p}Fiecare intră cu <b>parola lui</b>: recepția vede programările, "
           f"dar nu și rapoartele de bani, iar jurnalul de acces arată cine ce "
           f"a schimbat, de pe oricare calculator. Funcționează doar în "
           f"rețeaua clinicii — de acasă nu.{end}"),

        _q(_ic("phone"), "Pot deschide registrul de pe telefon?",
           f"{p}Da, în aceeași rețea a clinicii: <b>Setări › Acces din rețea › "
           f"Activează accesul</b> (programul repornește), apoi scanați "
           f"codul QR de pe pagină cu telefonul conectat la Wi-Fi-ul "
           f"clinicii. Fiecare intră cu parola lui; din meniul browserului "
           f"alegeți «Adaugă pe ecranul principal» — registrul devine o "
           f"aplicație pe telefon.{end}"
           f"{p}Funcționează <b>doar în rețeaua clinicii</b> — de acasă nu "
           f"se deschide, iar asta e o protecție, nu un defect. Folosiți "
           f"rețeaua protejată a clinicii, nu cea pentru pacienți.{end}"
           f"{p}Dacă telefonul nu se conectează: pe pagina «Acces din "
           f"rețea» apăsați <b>«Creează regula de firewall»</b> și "
           f"confirmați în fereastra Windows; verificați și ca rețeaua "
           f"calculatorului să fie de tip «Private» în setările Windows."
           f"{end}"),

        _q(_ic("refresh"), "Actualizarea programului șterge datele?",
           f"{p}<b>Nu.</b> Actualizarea înlocuiește doar fișierele "
           f"programului; baza de date, documentele și setările rămân "
           f"neatinse. Programul verifică singur dacă există o versiune nouă "
           f"— instalarea e un click în <b>Setări › Stare sistem</b>.{end}"
           f"{p}Nu e nevoie de o copie de rezervă specială înainte de "
           f"actualizare — dar o copie recentă e oricum o idee bună.{end}"),

        _q(_ic("key"), "Am uitat parola de intrare — ce fac?",
           f"{p}Dacă în clinică există alt <b>director</b>, el poate seta o "
           f"parolă nouă pentru oricine: <b>Setări › Securitate și "
           f"utilizatori</b>.{end}"
           f"{p}Dacă parola uitată e a singurului director — scrieți-ne la "
           f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>. Există o "
           f"procedură de deblocare; datele clinicii <b>nu se pierd</b>.{end}"
           f"{p}După mai multe încercări greșite, intrarea se blochează "
           f"temporar (de la 30 de secunde la 15 minute) — e o protecție "
           f"împotriva ghicirii; așteptați și încercați din nou.{end}"
           f"{p}{_ic('sos')} A nu se confunda cu <b>foaia de recuperare</b> a criptării: "
           f"sunt lucruri diferite. Parola de intrare spune cine deschide "
           f"programul și se poate schimba; codul de pe foaie deschide baza "
           f"însăși și nu poate fi schimbat sau recuperat de nimeni.{end}"),

        _q(_ic("palette"), "Pot pune culoarea și logoul clinicii în program?",
           f"{p}Da: <b>Setări › Aspectul clinicii</b>. Alegeți unul din trei "
           f"stiluri, culoarea clinicii (șase gata alese sau a dumneavoastră) "
           f"și încărcați logoul. Culoarea se aplică butoanelor, meniului și "
           f"accentelor; logoul apare la intrare și în antetul documentelor "
           f"tipărite (043/e, acord, raport de casă).{end}"
           f"{p}Roșul urgențelor, galbenul avertismentelor și verdele "
           f"«confirmat» <b>nu se schimbă</b> — acolo culoarea înseamnă ceva, "
           f"nu decorează.{end}"
           f"{p}Logoul se acceptă doar ca <b>PNG sau JPEG</b>, cel mult 2 MB. "
           f"Fișierele SVG nu se acceptă din motive de securitate — nu sunt "
           f"imagini, ci documente care pot conține cod.{end}"),

        _q(_ic("scales"), "Ce cere Legea 195 și cu ce mă ajută programul?",
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
           f"{p}Măsura tehnică cerută de lege o acoperă <b>criptarea "
           f"discului (BitLocker)</b> — starea ei o verifică programul singur "
           f"și o arată în <b>Setări › Stare sistem</b>, ca să nu depindeți de "
           f"un act semnat. Peste ea puteți cripta și evidența propriu-zisă "
           f"(<b>Setări › Criptarea evidenței</b>): BitLocker apără discul "
           f"scos din calculator, criptarea evidenței apără fișierul copiat de "
           f"pe el.{end}"),

        _q(_ic("folder"), "Unde sunt datele clinicii și ce nu trebuie atins?",
           f"{p}Totul e în folderul programului: <b>data\\dental.db</b> — "
           f"toată evidența; <b>data\\files\\</b> — documentele pacienților; "
           f"<b>clinic.json</b> — profilul clinicii.{end}"
           f"{p}Dacă evidența este criptată, tot acolo apare "
           f"<b>data\\db.key</b> — cheia. {_ic('ban')} Acest fișier <b>nu se șterge "
           f"niciodată</b>: fără el evidența se deschide doar cu codul de pe "
           f"foaia de recuperare. Se copiază împreună cu folderul, dar pe alt "
           f"calculator nu poate fi citit — de aceea foaia.{end}"
           f"{p}{_ic('sos')} Nu ștergeți, nu redenumiți și nu «faceți curat» în aceste "
           f"fișiere din Windows — programul le leagă între ele, iar orice "
           f"ștergere se face din program. Pentru orice nelămurire: "
           f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>.{end}"),
    ]
    return (f"<h2>{_ic('help')} Întrebări frecvente</h2>"
            "<p class='hint' style='margin-top:0'>Apăsați pe o întrebare "
            "pentru răspuns. Nu găsiți răspunsul? Scrieți-ne la "
            f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>.</p>"
            + "".join(items))
