"""Вопросы, которые клиника иначе задаёт по телефону.

Программа офлайн и local-first: документации в облаке нет, ссылка «читайте на
сайте» здесь не работает. Единственное место, где директор может что-то
прочитать, — сама программа, поэтому FAQ живёт экраном в настройках
(`FaqScreen`, записи — `/api/settings/faq`) и уезжает в сборку вместе с exe. Это же решает вопрос актуальности: текст
версионируется тем же коммитом, что и поведение, о котором он рассказывает.
Меняешь поведение — правь ответ ЗДЕСЬ, в том же диффе.

Аудитория — директор (страница под PERM_SETTINGS, как весь раздел): темы
директорские — бэкап, перенос, BitLocker, закон 195. Подсказки регистратуре
сюда не писать: она этой страницы не видит, им место в самих экранах журнала.

Каждый ответ обязан называть кнопки ТЕМИ словами, что стоят в интерфейсе
(«Descarcă datele pacientului», «Stare sistem»), — FAQ, отправляющий искать
несуществующую кнопку, хуже молчания. Факты, на которые ссылается текст:
MIN_PASS и CITESTE-MA.txt — backup.py; «токен не читается на другой машине» —
dpapi.py; ступени блокировки входа — auth._LOCK_STEPS (30 с … 15 мин).
Числа правил (PIN в сети, срок входа в сети, потолок логотипа, возраст внешней
копии) — из модулей, а не литералами: правило поменяется, справка вместе с ним.

Сверка 18.10 (Олег): все ответы прошли по коду. В вопросе про вход —
«PIN», как на экране входа, а не «parola»; переезд — только через архив
(ручное копирование папки поверх новой оставляет -wal/-shm пустой базы);
Windows Home без шифрования — предупреждение во вкладке BitLocker, не на
главном экране (слово Олега); про устройство SMS-пакета здесь не пишем —
это договор, а не справка (слово Олега).
"""
from __future__ import annotations

import html

from ...core.layout import FEEDBACK_EMAIL, _ic, data_folder, tg_configured
from ...core import auth, autobackup, backup_loop, bitlocker, theme
from ...core import backup as bkp
from .system import bitlocker_state

# Что делать при каждой строке BitLocker из «Stare sistem». Сама строка — из
# `bitlocker.describe`, а не копией: поменяется текст на экране — поменяется и
# справка. ⚠️ Список ВКЛЮЧАЕТ коды: новый код в `bitlocker._CODES` без строки
# здесь справка не назовёт — держит test_settings_api.suite_faq.
BL_ADVICE = (
    (1, "gata."),
    (3, "lăsați calculatorul pornit; se termină singură."),
    (2, "pasul 2 de mai sus."),
    (8, "capcana calculatoarelor noi, mai sus."),
    (5, "apare uneori după o actualizare Windows sau BIOS. Dacă rămâne și după o "
        "repornire a calculatorului, în «Manage BitLocker» apăsați «Resume protection»."),
    (None, "priviți în «Manage BitLocker»; dacă acolo protecția e pornită, scrieți-ne."),
)


def _q(icon: str, question: str, answer: str) -> dict:
    """Одна запись справки: имя иконки (из layout._I), вопрос, ответ HTML-ом.
    JSON API отдаёт её как есть; потолок ширины карточки — правило `.dp-faq`
    клиента (`--measure`)."""
    return {"icon": icon, "question": question, "answer": answer}


def _bl_said(code: int | None, drive: str) -> str:
    """Строка «Stare sistem» для кода. У тревожных строк после « — » идёт
    совет экрана («porniți BitLocker…») — его справка говорит своими словами
    рядом, поэтому здесь только сама строка; у спокойных («activ — discul …»)
    тире — часть состояния, и строка остаётся целиком."""
    tone, txt = bitlocker.describe(code, drive)
    return txt if tone == "ok" else txt.split(" — ")[0]


def _bitlocker(p: str, end: str) -> str:
    """Ответ «BitLocker»: первой строкой — состояние ЭТОГО компьютера теми же
    словами, что в «Stare sistem» (`system.bitlocker_state`), в конце — что
    делать при каждой строке, которую программа может показать."""
    st = bitlocker_state()
    now = (f"{_ic(st['icon'])} " if st["icon"] else "") + html.escape(st["text"])
    drive = bitlocker.STATE["drive"] or "C:"
    rows = "".join(f"<li><b>{html.escape(_bl_said(code, drive))}</b> — "
                   f"{html.escape(tip)}</li>" for code, tip in BL_ADVICE)
    ol = "<ol style='margin:0 0 8px;padding-left:22px'>"
    ul = "<ul style='margin:0 0 8px;padding-left:22px'>"
    return (
        f"{p}<b>Pe acest calculator, acum:</b> {now}. Programul verifică starea la "
        f"fiecare pornire; același rând îl vedeți în <b>Setări › Stare sistem</b>.{end}"
        f"{p}<b>De ce.</b> Fișele pacienților stau pe discul acestui calculator. Dacă un "
        f"calculator sau doar discul lui este furat, fără criptare datele se citesc "
        f"conectând discul la alt calculator — PIN-ul DentPilot și parola Windows nu le "
        f"apără. BitLocker criptează tot discul: furat, el rămâne ilizibil. Aceasta este "
        f"măsura tehnică pe care o cere Legea 195.{end}"
        f"{p}<b>Pasul 1 — ediția Windows.</b> Apăsați <b>Win+Pause</b> (sau Setări › "
        f"Sistem › Despre) și citiți rândul «Ediție». Windows 10 sau 11 <b>Pro</b> (ori "
        f"Enterprise) are BitLocker. Pe <b>Home</b> nu există — vedeți mai jos.{end}"
        f"{p}<b>Pasul 2 — porniți BitLocker</b> (Pro, cu un cont de administrator):{end}"
        f"{ol}"
        f"<li>Meniul Start, scrieți <b>BitLocker</b> și deschideți «Manage BitLocker».</li>"
        f"<li>La discul <b>{html.escape(drive)}</b> apăsați «Turn on BitLocker».</li>"
        f"<li>Când Windows întreabă unde salvați <b>cheia de recuperare</b>, alegeți "
        f"«Print the recovery key» (tipărire). Puteți păstra în plus un fișier pe un "
        f"stick USB («Save to a file») — dar nu pe acest calculator.</li>"
        f"<li>Pe un calculator nou alegeți «Encrypt used disk space only». Pe unul pe "
        f"care s-a lucrat deja — «Encrypt entire drive»: durează mai mult, dar "
        f"criptează și urmele fișierelor șterse.</li>"
        f"<li>Alegeți «New encryption mode», apoi «Start encrypting». Criptarea merge în "
        f"fundal; puteți lucra normal, și în DentPilot.</li></ol>"
        f"{p}<b>Capcana calculatoarelor noi.</b> Dacă programul scrie că discul <b>pare "
        f"criptat, dar protecția este OPRITĂ</b>, discul a fost criptat din fabrică, iar "
        f"cheia stă deschisă lângă date: un disc furat se deschide singur. În «Manage "
        f"BitLocker» scrie de obicei «Waiting for activation» (în rusă «Ожидает "
        f"активации»). Apăsați «Turn on BitLocker» și salvați cheia: durează un minut "
        f"și nu criptează nimic din nou.{end}"
        f"{p}<b>Pe Windows Home</b> BitLocker nu există. Unele calculatoare Home au în "
        f"schimb <b>Criptarea dispozitivului</b> (Setări › Confidențialitate și "
        f"securitate) — dacă o aveți, porniți-o; cheia ei se păstrează în contul "
        f"Microsoft cu care intrați în Windows. Dacă nu o aveți, programul lucrează la "
        f"fel. {_ic('sos')} Rețineți doar că discul rămâne <b>necriptat</b>: de pe un "
        f"calculator furat fișele pot fi citite. Trecerea la Windows Pro rezolvă asta "
        f"oricând.{end}"
        f"{p}<b>Cheia de recuperare — unde o păstrați.</b> Windows o cere rar: după "
        f"schimbarea plăcii de bază sau a discului, uneori după o actualizare BIOS. "
        f"Fără ea, discul nu se mai deschide niciodată — nici de noi, nici de "
        f"Microsoft. Tipăriți-o, scrieți pe foaie numele calculatorului și păstrați-o "
        f"în mapa «Legea 195» a clinicii, nu lângă calculator. Nu o lipiți de monitor "
        f"și nu o salvați pe același disc.{end}"
        f"{p}Sunt trei lucruri diferite: <b>cheia BitLocker</b> deschide discul, "
        f"<b>foaia de recuperare</b> a criptării evidenței deschide baza DentPilot, iar "
        f"<b>PIN-ul</b> spune cine intră în program.{end}"
        f"{p}<b>Pasul 3 — verificați.</b> Închideți DentPilot și porniți-l din nou: "
        f"starea se verifică la pornire. Ce poate scrie în Stare sistem, la «Criptare "
        f"disc (BitLocker)»:{end}"
        f"{ul}{rows}</ul>"
        f"{p}<b>BitLocker nu înlocuiește copia de rezervă:</b> un disc defect sau un "
        f"calculator furat rămân fără date, chiar dacă nimeni nu le poate citi. Le "
        f"păstrează copia din afara calculatorului (<b>Setări › Copie de rezervă</b>)."
        f"{end}")


def entries() -> list[dict]:
    """Все записи справки в порядке страницы."""
    p = "<p style='margin:0 0 8px'>"
    end = "</p>"
    # ⭐ Путь НАСТОЯЩИЙ, а не пересказ раскладки (`layout.data_folder`): папку
    # выбирает лаунчер, и пересказ устареет на следующем переезде (так ушла
    # портативная раскладка `portable.flag`, 22.10.2026). Строку, которую
    # директор сверяет с адресной строкой Проводника, устареть нельзя. Пусто
    # бывает только вне настольного издания (облако, запуск из исходников) —
    # тогда называем обычную раскладку: спрашивать о ней не у кого.
    _folder = data_folder()
    loc = (f"<b>{html.escape(_folder)}</b>" if _folder else
           "<b>C:\\ProgramData\\DentPilot</b>")
    pin_lan = auth.PIN_MIN_LAN
    lan_hours = auth.COOKIE_TTL_LAN // 3600
    # Telegram заморожен (08-08): абзац про токен — только клинике, у которой
    # бот настроен (grandfather). Остальным он рассказывал бы про раздел,
    # которого у них нет (08-13). Следующий абзац меняет число вместе с ним:
    # «Ambele» опирается на два предмета — лист восстановления И токен.
    if tg_configured():
        tok = (f"{p}{_ic('sos')} Trebuie reintrodus și <b>tokenul botului "
               f"Telegram</b> (Setări › Telegram Bot), din același motiv. Aici "
               f"însă nu se pierde nimic: tokenul se ia din nou de la "
               f"@BotFather.{end}"
               f"{p}Ambele sunt protecții, nu defecțiuni: un folder copiat sau "
               f"furat nu dezvăluie nici evidența, nici tokenul clinicii.{end}")
    else:
        tok = (f"{p}Este o protecție, nu o defecțiune: un folder copiat sau "
               f"furat nu dezvăluie evidența clinicii.{end}")
    items = [
        _q("save", "Cât de des fac copii de rezervă și unde le păstrez?",
           f"{p}Cu <b>Setări › Copie de rezervă › Copie zilnică automată</b> "
           f"pornită, programul face singur, <b>o dată pe zi</b>, cât timp este "
           f"pornit, o copie pe acest calculator și — dacă ați ales un folder — o "
           f"arhivă criptată <b>în afara calculatorului</b>: un folder de pe alt "
           f"disc, un stick USB lăsat în calculator sau folderul cloud al "
           f"clinicii, cu o parolă de minim {bkp.MIN_PASS} caractere. Pe ecran "
           f"vedeți <b>Ultima copie</b> (când și unde) și copiile făcute, pe zile; "
           f"dacă o copie nu s-a făcut sau cea din folder are "
           f"{backup_loop.STALE_DAYS} zile ori mai mult, directorul vede un "
           f"avertisment pe fiecare ecran.{end}"
           f"{p}Întrerupătorul îl decide directorul. <b>Oprit</b>, programul face "
           f"doar copia de la pornire, pe acest calculator, și nu mai avertizează "
           f"nimic — folderul și parola rămân salvate pentru când îl porniți din "
           f"nou.{end}"
           f"{p}O copie păstrată lângă original dispare împreună cu el "
           f"(defectarea discului, furt, viruși) — de aceea contează cea din "
           f"afara calculatorului. Înainte de o mutare sau după o zi cu multe "
           f"modificări puteți face oricând și o arhivă manuală: <b>Copie manuală "
           f"pe stick USB › Exportă arhiva</b>.{end}"
           f"{p}{_ic('sos')} Parola arhivei manuale <b>nu se salvează nicăieri</b>; "
           f"parola copiei din folder este păstrată pe acest calculator (criptată), "
           f"dar arhivele se deschid pe orice calculator cu parola aleasă — "
           f"notați-o într-un loc sigur. Fără ea, arhiva nu poate fi deschisă de "
           f"nimeni, nici de noi.{end}"
           f"{p}Pentru cine vrea detaliile: copiile de pe acest calculator stau în "
           f"<b>data\\backups</b> (se păstrează ultimele {autobackup.KEEP}, criptate "
           f"ca și evidența), arhivele din folder se numesc "
           f"<b>{backup_loop.AUTO_PREFIX}…zip</b> (se păstrează ultimele "
           f"{backup_loop.KEEP_EXT}; arhivele exportate manual în același folder "
           f"nu sunt șterse).{end}"
           f"{p}Arhiva este <b>de sine stătătoare</b>: chiar dacă evidența de "
           f"pe calculator este criptată, baza dinăuntru nu este — o apără "
           f"parola arhivei. Așa o restaurați oriunde, fără foaia de "
           f"recuperare. Este și motivul pentru care parola arhivei contează "
           f"mai mult decât pare: ea singură ține toată evidența clinicii."
           f"{end}"),

        # ⚠️ На новом компьютере пустая картотека без файла лицензии — стена
        # активации (`license.walled`): до кнопки восстановления не дойти, пока
        # не поставлен PIN и не активирована программа. После восстановления
        # auth.json едет из архива — вход старыми PIN.
        _q("refresh", "Cum restaurez evidența dintr-o copie?",
           f"{p}Din program, în <b>Setări › Copie de rezervă › Restaurare din "
           f"copie</b> (secțiunea pliată de jos): alegeți după dată o copie de pe "
           f"acest calculator sau din folderul ales, ori scrieți calea unei "
           f"arhive de pe stick (cu parola ei), și apăsați <b>Verifică copia</b>. "
           f"Programul vă arată mai întâi <b>câți pacienți, programări și "
           f"documente</b> conține copia — abia apoi apăsați <b>Restaurează la "
           f"următoarea pornire</b>, închideți programul și porniți-l din nou.{end}"
           f"{p}Înlocuirea se face <b>la pornire</b>, de către program "
           f"însuși, niciodată cu evidența deschisă. Baza de acum <b>nu se "
           f"șterge</b>: rămâne în folderul cu date sub numele "
           f"<b>dental.before-restore-&lt;data&gt;.db</b>, iar în Activitate "
           f"recentă (Statistici) apare ce copie a fost restaurată. Dacă evidența "
           f"este criptată, copia este trecută automat sub cheia acestui "
           f"calculator — nu trebuie șters nimic.{end}"
           f"{p}Pe un calculator nou: instalați DentPilot și porniți-l. Programul "
           f"cere întâi un PIN — puneți unul provizoriu — și activarea (pagina "
           f"<b>Licența</b> se deschide singură; codul vine pe e-mailul "
           f"clinicii). Abia apoi se deschid setările și restaurați arhiva de pe "
           f"stick cu același buton. După repornire intrați cu PIN-urile vechi, "
           f"cele din copie. Dacă programul nu poate fi instalat deloc, vedeți "
           f"întrebarea următoare.{end}"),

        _q("box", "Cum deschid arhiva de rezervă fără DentPilot?",
           f"{p}Intenționat simplu: arhiva este un ZIP obișnuit, criptat "
           f"AES-256. Se deschide pe orice calculator cu <b>7-Zip</b> "
           f"(gratuit, www.7-zip.org) sau <b>WinRAR</b>, cu parola aleasă la "
           f"export — nu depindeți nici de DentPilot, nici de noi.{end}"
           f"{p}{_ic('sos')} Windows (Explorer) <b>nu poate</b> extrage acest tip de "
           f"arhivă și afișează o eroare — nu înseamnă că arhiva e stricată; "
           f"folosiți 7-Zip.{end}"
           f"{p}Programul pune în fiecare arhivă, lângă date, un fișier text care "
           f"se deschide fără parolă — <b>CITESTE-MA.txt</b> — cu pașii de "
           f"restaurare manuală, pentru cazul în care programul nu poate fi "
           f"instalat; altfel folosiți butonul <b>Restaurare din copie</b> "
           f"(întrebarea de mai sus). Alături, <b>CONTINUT.txt</b> — lista a tot "
           f"ce conține arhiva: câți pacienți, câte programări, care fișier este "
           f"care document.{end}"
           f"{p}{_ic('ban')} La restaurarea <b>manuală</b> (dezarhivare peste "
           f"folderul cu date, cu programul închis) ștergeți întâi "
           f"<b>data\\dental.db-wal</b> și <b>data\\dental.db-shm</b> — rămase pe "
           f"loc, se aplică peste baza restaurată și evidența revine la starea "
           f"dinainte fără nicio eroare — iar dacă pe calculator este activată "
           f"criptarea evidenței, și <b>data\\db.key</b>: baza din arhivă nu "
           f"este criptată, iar cu cheia rămasă pe loc programul ar da eroare "
           f"la pornire (după restaurare criptarea se activează din nou din "
           f"Setări). Butonul <b>Restaurare din copie</b> face toate acestea "
           f"singur și păstrează legăturile către documentele pacienților — de "
           f"aceea este calea recomandată.{end}"),

        # Переезд — ТОЛЬКО через архив (сверка 18.10): совет «скопируйте папку
        # поверх новой» оставлял -wal/-shm пустой базы первого запуска, и журнал
        # выглядел пустым без ошибки. dental.env в архив не едет (белый список
        # backup.write_encrypted) — пароль внешней копии и сеть заводятся заново.
        _q("home", "Mutăm programul pe alt calculator sau reinstalăm Windows — "
                  "ce se întâmplă cu datele?",
           f"{p}Datele clinicii stau <b>separat de program</b>, în folderul "
           f"lor: {loc}. Ca să le mutați, faceți pe calculatorul vechi o arhivă "
           f"— <b>Setări › Copie de rezervă › Copie manuală pe stick USB</b> — "
           f"sau folosiți ultima copie din folderul ales. Pe calculatorul nou "
           f"instalați DentPilot și restaurați arhiva cu <b>Restaurare din "
           f"copie</b> (pașii — la întrebarea despre restaurare). Pacienții, "
           f"programările, documentele, profilul clinicii și PIN-urile de "
           f"intrare rămân.{end}"
           f"{p}{_ic('folder')} <b>Nu copiați fișierele de mână</b> peste folderul "
           f"nou: o copiere pe jumătate lasă evidența goală, fără nicio eroare, "
           f"iar arhiva pune la loc și legăturile către documentele pacienților. "
           f"Programul în sine nu ține date și se reinstalează oricând. Calea "
           f"folderului pe calculatorul nou o arată programul, în <b>Setări › "
           f"Stare sistem</b>, rândul <b>Folderul cu date</b>.{end}"
           f"{p}Pe calculatorul nou se pornesc din nou <b>parola copiei din "
           f"folder</b> (Setări › Copie de rezervă) și, dacă îl folosiți, "
           f"<b>accesul din rețea</b> (Setări › Acces din rețea): ele țin de "
           f"calculator, nu de evidență, și nu trec prin arhivă.{end}"
           f"{p}{_ic('sos')} <b>Dacă evidența este criptată</b> (Setări › Criptarea "
           f"evidenței), arhiva se restaurează fără foaia de recuperare — o apără "
           f"parola arhivei; după mutare porniți criptarea din nou și tipăriți "
           f"foaia nouă. Codul de pe <b>foaia de recuperare</b> îl cere programul "
           f"doar când găsește folderul vechi sub alt cont Windows — de exemplu, "
           f"discul vechi pus în calculatorul nou: cheia este legată de contul "
           f"Windows vechi și pe altul nu poate fi citită. Fără foaie, o astfel "
           f"de evidență nu se deschide nici de noi.{end}"
           + tok),

        _q("shield", "Cum pornesc BitLocker — criptarea discului?",
           _bitlocker(p, end)),

        _q("lock", "Ce este criptarea evidenței?",
           f"{p}<b>O opțiune, nu o obligație.</b> Pentru Legea 195 măsura "
           f"tehnică este criptarea discului (BitLocker) — programul o verifică "
           f"singur și o arată în <b>Stare sistem</b>. Criptarea evidenței este "
           f"un plus, pentru clinicile care îl doresc; fără ea sunteți la fel "
           f"de în regulă cu legea. Cum se pornește BitLocker — în întrebarea "
           f"de mai sus.{end}"
           f"{p}Ce face: acum fișierul <b>data\\dental.db</b> este o bază "
           f"SQLite obișnuită și, copiată de pe calculator, se deschide cu "
           f"orice program. Criptarea o face inutilizabilă în afara acestui "
           f"calculator. Are sens mai ales dacă programul stă pe un laptop "
           f"care iese din clinică. Se activează din <b>Setări › Criptarea "
           f"evidenței</b>.{end}"
           # dbkey шифрует базу и её копии, data\files — нет (сверка 18.10)
           f"{p}Ce acoperă: baza cu fișele (<b>data\\dental.db</b>) și copiile "
           f"zilnice. Documentele încărcate la pacienți — scanări, fotografii, "
           f"din <b>data\\files</b> — programul nu le criptează; pe ele le apără "
           f"BitLocker.{end}"
           f"{p}Ce cere în schimb: activarea tipărește o <b>foaie de "
           f"recuperare</b> cu un cod, iar foaia devine responsabilitatea "
           f"clinicii. Confirmarea se află chiar pe foaia tipărită — "
           f"intenționat, pentru că ea este singurul lucru care vă salvează "
           f"evidența la schimbarea calculatorului. Păstrați-o în mapa «Legea "
           f"195» a clinicii, lângă cheia de recuperare BitLocker — adică <b>nu "
           f"în calculator</b>. Pierderea ei nu poate fi reparată de nimeni, "
           f"nici de noi. Dacă această obligație vă pare în plus, nu activați "
           f"criptarea: nu pierdeți nimic din punct de vedere legal.{end}"
           f"{p}Codul <b>nu se cere niciodată</b> în lucrul obișnuit: nici la "
           f"pornire, nici la actualizare. Programul îl cere doar după "
           f"reinstalarea Windows, la mutarea pe alt calculator, la schimbarea "
           f"contului Windows sau a discului — atunci apare un singur ecran "
           f"care îl întreabă.{end}"
           f"{p}Ce NU face criptarea: nu vă apără de cineva care stă la acest "
           f"calculator, sub acest cont Windows — programul lucrează sub el, "
           f"deci tot ce descifrează programul descifrează și acea persoană. "
           f"Împotriva asta lucrează PIN-ul de intrare și blocarea ecranului "
           f"(Win+L), nu criptarea.{end}"
           f"{p}Se poate opri oricând: <b>«Oprește criptarea»</b> pe aceeași "
           f"pagină, cu o repornire. Datele nu se pierd.{end}"),

        # ⚠️ Кнопка «Activează accesul» закрыта, пока у кого-то PIN короче
        # PIN_MIN_LAN (`auth.pin_readiness`), а вход в сети живёт COOKIE_TTL_LAN —
        # без этих двух фраз директор видит серую кнопку и «программа опять
        # просит PIN» как поломки.
        _q("monitor", "Vreau registrul pe două calculatoare — la recepție "
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
           f"normal. Butonul se deschide doar când fiecare utilizator are un PIN "
           f"de cel puțin {pin_lan} cifre: în rețea PIN-ul poate fi încercat de "
           f"pe orice telefon din Wi-Fi. Dacă butonul e închis, pagina arată "
           f"cui; setați-i un PIN nou în <b>Setări › Securitate și "
           f"utilizatori</b>.</li>"
           f"<li>Dacă pe pagină apare butonul <b>«Creează regula de "
           f"firewall»</b>, apăsați-l și confirmați fereastra prin care "
           f"Windows cere permisiunea. Fără ea, al doilea calculator nu "
           f"intră.</li>"
           f"<li>Tot pe acea pagină scrie <b>adresa</b>, de forma "
           f"<b>http://192.168.0.15:8088/admin</b>. Notați-o.</li>"
           f"<li>Pe <b>al doilea calculator</b>: deschideți Chrome sau Edge, "
           f"scrieți adresa, intrați cu PIN-ul dumneavoastră. Salvați-o la "
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
           f"{p}Fiecare intră cu <b>PIN-ul lui</b>: recepția vede programările, "
           f"dar nu și rapoartele de bani, medicul — doar programările lui "
           f"(pacienții îi vede pe toți), iar jurnalul de acces arată cine ce "
           f"a schimbat, de pe oricare calculator. Cât timp accesul din rețea e "
           f"pornit, programul cere PIN-ul din nou după {lan_hours} ore — o dată "
           f"pe tură, pe fiecare calculator și telefon. Funcționează doar în "
           f"rețeaua clinicii — de acasă nu.{end}"),

        _q("phone", "Pot deschide registrul de pe telefon?",
           f"{p}Da, în aceeași rețea a clinicii: <b>Setări › Acces din rețea › "
           f"Activează accesul</b> (programul repornește), apoi scanați "
           f"codul QR de pe pagină cu telefonul conectat la Wi-Fi-ul "
           f"clinicii. Fiecare intră cu PIN-ul lui (în rețea — de cel puțin "
           f"{pin_lan} cifre); din meniul browserului alegeți «Adaugă pe "
           f"ecranul principal».{end}"
           f"{p}Pe <b>iPhone</b> registrul se deschide după aceea ca o "
           f"aplicație adevărată — pe tot ecranul, cu iconița programului. Pe "
           f"<b>Android</b> rămâne deocamdată o scurtătură care se deschide în "
           f"browser: pentru mai mult ar fi nevoie de o legătură criptată, iar "
           f"în rețeaua locală ea nu există. Diferența e de sistem, nu de "
           f"telefon — pe amândouă se lucrează la fel.{end}"
           f"{p}Funcționează <b>doar în rețeaua clinicii</b> — de acasă nu "
           f"se deschide, iar asta e o protecție, nu un defect. Folosiți "
           f"rețeaua protejată a clinicii, nu cea pentru pacienți.{end}"
           f"{p}Dacă telefonul nu se conectează, deschideți pagina «Acces "
           f"din rețea» pe calculatorul cu programul: ea verifică singură "
           f"permisiunea Windows (și oferă butonul <b>«Creează regula de "
           f"firewall»</b>, dacă lipsește), iar la «Verificarea legăturii» "
           f"arată ce dispozitive au ajuns până la calculator.{end}"),

        # С переезда в Program Files обновление ставит подписанный установщик
        # за UAC (`update._update_by_setup`) и перезапускается само.
        _q("refresh", "Cum funcționează «Rechemări»?",
           f"{p}«Rechemări» este lista recepției cu pacienții cărora le-a venit "
           f"timpul pentru o procedură repetată (de regulă igienizarea). Termenul "
           f"se alege <b>la serviciu</b>: în <b>Setări › Servicii</b>, coloana "
           f"<b>Rechemare</b> — de exemplu Igienizare, 6 luni. Serviciile fără "
           f"termen nu intră în listă.{end}"
           f"{p}Lista se calculează singură din <b>vizitele finalizate</b>: "
           f"pacientul apare cu 14 zile înainte de termen și rămâne până când "
           f"este programat din nou la același serviciu sau până la un marcaj "
           f"al recepției (<b>Sunat — revine</b>, <b>Nu răspunde</b>, "
           f"<b>Amânat până la</b>, <b>Nu mai reaminti</b>). Programarea la "
           f"alt serviciu nu îl scoate din listă — rândul spune «vine pe …», ca "
           f"să vorbiți cu el la recepție. Rândul din fișa pacientului arată "
           f"ultima vizită și termenul următor.{end}"
           f"{p}Istoricul de pe hârtie se introduce din <b>Programare nouă</b> "
           f"pe data vizitei trecute, cu bifa <b>Vizita a avut loc</b>: vizita "
           f"intră direct ca finalizată și pornește termenul. Butonul "
           f"<b>E-mail</b> deschide programul de e-mail al calculatorului cu un "
           f"text pregătit (fără prețuri sau oferte); dacă nu se deschide nimic, "
           f"folosiți <b>Copiază adresa</b> și <b>Copiază textul</b>. DentPilot "
           f"nu trimite mesaje prin internet și nu transmite nimănui datele "
           f"pacienților. Medicii nu văd lista — doar rândul din fișă.{end}"
           f"{p}Cu modulul SMS (DentPilot Plus și luna de probă) rândul are și "
           f"butonul <b>SMS</b>: trimite pacientului o singură reamintire a "
           f"controlului periodic pentru termenul curent — textul conține doar "
           f"denumirea și telefonul clinicii, fără serviciu sau prețuri — și "
           f"consumă un SMS din pachet. Dacă SMS-ul nu ajunge, pacientul revine "
           f"în «De sunat». Butonul se pornește și se oprește în "
           f"<b>Setări › SMS</b>.{end}"),

        _q("refresh", "Actualizarea programului șterge datele?",
           f"{p}<b>Nu.</b> Actualizarea înlocuiește doar fișierele "
           f"programului; baza de date, documentele și setările rămân "
           f"neatinse. Programul verifică singur dacă există o versiune nouă; "
           f"o instalați din <b>Setări › Stare sistem › Actualizează acum</b>.{end}"
           f"{p}Windows cere confirmarea drepturilor de administrator — apăsați "
           f"<b>Da</b>. Programul se închide pentru circa un minut și pornește "
           f"singur cu versiunea nouă; pe al doilea calculator și pe telefoane "
           f"reîncărcați pagina. Alegeți un moment în care nu se lucrează în "
           f"registru.{end}"
           f"{p}Nu e nevoie de o copie de rezervă specială înainte de "
           f"actualizare — dar o copie recentă e oricum o idee bună.{end}"),

        # ⚠️ Слова кнопок — те, что на экранах: «Plătește acum» (баннер, страница
        # лицензии), плитка «Licența», «Verifică acum dacă există un termen nou»;
        # подписи страницы оплаты — cloud/app/views.py (pay_link_page). Карта
        # появляется на той странице только с договором maib — отсюда «dacă».
        # Cont de plată «achitat» — cloud/app/receipts.py (письмо и кабинет).
        # «Deschide contul clinicii» (27.10) — та же страница лицензии, только директору; кабинет
        # по ней — только эта клиника (cloud/app/contlink.py).
        # Варианты Basic / Plus и когда включается модуль SMS — условия § 4.1–4.2.
        _q("card", "Cum plătesc abonamentul?",
           f"{p}Din program: <b>Setări › Licența</b> și butonul <b>Plătește acum</b> — "
           f"același buton apare și în bannerul de sus când abonamentul a expirat. Pagina "
           f"de plată se deschide în browser, cu datele clinicii deja completate: alegeți "
           f"varianta (<b>DentPilot Basic</b> fără modulul SMS sau <b>DentPilot Plus</b> "
           f"cu modulul SMS), perioada (o lună sau un an) și modul de plată.{end}"
           f"{p}Modulul SMS pornește imediat după plata variantei Plus; la trecerea la "
           f"Basic rămâne pornit până la sfârșitul perioadei în curs. SMS-urile nu intră "
           f"în abonament: pachetele se comandă separat, în <b>Setări › SMS</b>.{end}"
           f"{p}<b>Transfer bancar</b> — primiți nota de plată pe e-mail, cu referința ei "
           f"(DP-…), pe care o treceți în ordinul de plată. Dacă pagina afișează "
           f"<b>Plătește cu cardul</b>, puteți achita imediat cu cardul.{end}"
           f"{p}Termenul nou ajunge în program singur: după «Plătește acum» programul "
           f"verifică plata la fiecare minut timp de două ore, apoi o dată pe zi. Plata "
           f"prin transfer se confirmă când banii ajung în contul DentPilot; ca să "
           f"verificați imediat, apăsați <b>Verifică acum dacă există un termen nou</b> "
           f"pe pagina licenței.{end}"
           f"{p}După plată primiți pe e-mail <b>contul de plată</b> cu mențiunea "
           f"«achitat» (PDF), pentru contabilitatea clinicii; îl puteți descărca "
           f"oricând și din contul clinicii DentPilot.{end}"
           f"{p}Contul clinicii se deschide și din program, fără cod: pe aceeași pagină "
           f"a licenței, butonul <b>Deschide contul clinicii</b> (doar pentru director). "
           f"Așa vedeți doar clinica acestui program; celelalte clinici ale contului — "
           f"după intrarea cu Google sau cu codul pe e-mail.{end}"
           f"{p}Dacă abonamentul a expirat, programul lucrează în continuare până la data "
           f"din banner, apoi trece în regim de citire: datele se pot consulta, tipări și "
           f"exporta, iar copia de rezervă funcționează; programări și înregistrări noi se "
           f"pot face din nou imediat după plată. Întrebări: "
           f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>.{end}"),

        # Подтверждение ящика (27.10): слова — блока страницы лицензии (layout._email_block) и
        # письма облака (cloud/app/mail.py, confirm_lines); ссылка живёт 7 дней (emailconf.LINK_TTL).
        # Подтверждённый ящик программа не меняет — только кабинет или DentPilot.
        _q("mail", "Ce înseamnă «E-mail neconfirmat» la Licența?",
           f"{p}Adresa de e-mail a clinicii, înregistrată la DentPilot, încă nu a fost confirmată. Pe ea "
           f"vin codul pentru un calculator nou, intrarea în contul clinicii și notele de plată — de "
           f"aceea o greșeală de tastare se vede abia când codul nu mai ajunge. Programul "
           f"<b>funcționează și fără confirmare</b>; nimic nu se blochează.{end}"
           f"{p}Confirmați din e-mailul de la DentPilot: butonul <b>Confirmă adresa</b> (linkul este "
           f"valabil 7 zile) sau codul din 6 cifre, introdus în <b>Setări › Licența</b>. Intrarea în "
           f"contul clinicii cu aceeași adresă confirmă și ea adresa. Nu găsiți e-mailul? Verificați "
           f"dosarul Spam sau apăsați <b>Retrimite e-mailul</b>.{end}"
           f"{p}Adresa este greșită? Tot acolo, <b>Schimbă adresa</b>: codul pleacă pe adresa nouă. "
           f"După confirmare adresa se schimbă doar din contul clinicii sau scriindu-ne.{end}"),

        # «PIN», как на экране входа («Ați uitat PIN-ul?»). Сброс при пропавшем
        # auth.json — только с подтверждением администратора Windows
        # (`privileged._auth_reset`), учётки заводятся заново; счётчик неудач —
        # на устройство (`auth.client_peer`).
        _q("key", "Am uitat PIN-ul de intrare — ce fac?",
           f"{p}Dacă în clinică există alt <b>director</b>, el poate seta un "
           f"PIN nou pentru oricine: <b>Setări › Securitate și "
           f"utilizatori</b>.{end}"
           f"{p}Dacă PIN-ul uitat e al singurului director — scrieți-ne la "
           f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>. Există o "
           f"procedură de deblocare: ea cere confirmarea unui administrator "
           f"Windows la calculatorul cu programul, iar utilizatorii clinicii se "
           f"adaugă din nou după ea; datele clinicii <b>nu se pierd</b>.{end}"
           f"{p}După mai multe încercări greșite, intrarea se blochează "
           f"temporar (de la 30 de secunde la 15 minute) — doar pe calculatorul "
           f"sau telefonul de pe care s-a greșit. E o protecție împotriva "
           f"ghicirii; așteptați și încercați din nou.{end}"
           f"{p}{_ic('sos')} A nu se confunda cu <b>foaia de recuperare</b> a criptării: "
           f"sunt lucruri diferite. PIN-ul spune cine deschide programul și se "
           f"poate schimba; codul de pe foaie deschide baza însăși și nu poate "
           f"fi schimbat sau recuperat de nimeni.{end}"),

        # Стилей, меню, шрифтов — по нескольку, и их число растёт: числом в
        # тексте не называем («трёх стилей» пережило три новых стиля).
        _q("palette", "Pot pune culoarea și logoul clinicii în program?",
           f"{p}Da: <b>Setări › Aspectul clinicii</b>. Alegeți stilul "
           f"programului, culoarea clinicii (una gata aleasă sau a "
           f"dumneavoastră), meniul, fontul și cum arată programările pe grilă, "
           f"apoi încărcați logoul. Culoarea se aplică butoanelor, meniului și "
           f"accentelor; logoul apare la intrare, în antetul documentelor "
           f"tipărite (043/e, acord, raport de casă) și, dacă bifați, în bara "
           f"de sus a registrului.{end}"
           f"{p}Roșul urgențelor, galbenul avertismentelor și verdele "
           f"«confirmat» <b>nu se schimbă</b> — acolo culoarea înseamnă ceva, "
           f"nu decorează.{end}"
           f"{p}Logoul se acceptă doar ca <b>PNG sau JPEG</b>, cel mult "
           f"{theme.LOGO_MAX // (1024 * 1024)} MB. Fișierele SVG nu se acceptă din "
           f"motive de securitate — nu sunt imagini, ci documente care pot "
           f"conține cod.{end}"),

        # Декларация поставщика (закон 195) едет вложением в каждое письмо о
        # лицензии (cloud/app/mail.declaration); образцы общих документов —
        # по просьбе (слово Олега 18.10).
        _q("scales", "Ce cere Legea 195 și cu ce mă ajută programul?",
           f"{p}Legea 195/2024 (protecția datelor personale) dă pacientului "
           f"dreptul la o copie a datelor lui și dreptul la ștergere. "
           f"Ambele sunt în fișa pacientului: <b>«Descarcă datele "
           f"pacientului»</b> — arhivă cu tot ce știe programul despre el; "
           f"secțiunea <b>«Ștergerea datelor (Legea 195)»</b> — ștergerea la "
           f"cerere. Dacă pacientul are înregistrări medicale, se șterg doar "
           f"datele de identitate (nume, telefon, IDNP, adresă), iar tratamentul "
           f"rămâne sub numărul fișei: clinica e obligată să-l păstreze.{end}"
           f"{p}Formularul personal de informare (cu datele pacientului "
           f"completate automat) se tipărește din fișă: <b>«Informare / acord "
           f"— tipărire»</b>. Exemplarul semnat îl scanați sau fotografiați "
           f"și îl încărcați la documentele pacientului — așa dovada "
           f"semnăturii rămâne în program.{end}"
           f"{p}Evidența stă <b>pe acest calculator</b>: fișele pacienților nu "
           f"ajung pe serverele noastre. Copia din folderul ales — de exemplu un "
           f"folder cloud — pleacă doar criptată, cu parola clinicii. "
           f"<b>Declarația furnizorului</b> (Legea 195), semnată, o primiți pe "
           f"e-mail odată cu licența; dacă o vreți și pe altă adresă sau aveți "
           f"nevoie de modelele informării de la recepție și ale registrului de "
           f"evidență, scrieți-ne.{end}"
           f"{p}Măsura tehnică cerută de lege o acoperă <b>criptarea "
           f"discului (BitLocker)</b> — starea ei o verifică programul singur "
           f"și o arată în <b>Setări › Stare sistem</b>, ca să nu depindeți de "
           f"un act semnat. Peste ea puteți cripta și evidența propriu-zisă "
           f"(<b>Setări › Criptarea evidenței</b>): BitLocker apără discul "
           f"scos din calculator, criptarea evidenței apără fișierul copiat de "
           f"pe el. Cum se pornește BitLocker — în întrebarea despre BitLocker."
           f"{end}"),

        _q("folder", "Unde sunt datele clinicii și ce nu trebuie atins?",
           f"{p}Datele au un folder al lor, separat de folderul în care "
           f"este instalat programul: {loc} — îl arată și <b>Setări › Stare "
           f"sistem</b>, rândul <b>Folderul cu date</b>. Înăuntru: "
           f"<b>data\\dental.db</b> — toată evidența; <b>data\\files\\</b> — "
           f"documentele pacienților; <b>clinic.json</b> — profilul "
           f"clinicii.{end}"
           f"{p}Dacă evidența este criptată, tot acolo apare "
           f"<b>data\\db.key</b> — cheia. {_ic('ban')} Acest fișier <b>nu se șterge "
           f"niciodată</b>: fără el evidența se deschide doar cu codul de pe "
           f"foaia de recuperare. Se copiază împreună cu folderul, dar pe alt "
           f"calculator nu poate fi citit — de aceea foaia. Singura excepție: "
           f"restaurarea unei <b>arhive de rezervă</b> — vezi întrebarea "
           f"despre arhivă.{end}"
           f"{p}{_ic('sos')} Nu ștergeți, nu redenumiți și nu «faceți curat» în aceste "
           f"fișiere din Windows — programul le leagă între ele, iar orice "
           f"ștergere se face din program. Pentru orice nelămurire: "
           f"<a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a>.{end}"),
    ]
    return items
