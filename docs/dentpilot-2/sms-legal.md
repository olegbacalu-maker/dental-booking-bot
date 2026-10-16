# SMS-пакет — бумаги (черновики S1)

✅ **16.10 разделы 1, 2, 3 и 5 перенесены на страницы `docs/site/*.html` без
юриста** — слово Олега: «без юриста, я уже подписал документ на sms.md, я уже
и без юриста в ответе за данные». Дата условий и `TERMS_VERSION` — 16.10.2026,
декларация — 16.10.2026 (подписанный PDF на сервере остаётся от 02.10, пока Олег
не переподпишет). Скобки решены решениями S0 и `cloud/app/config.py`: остаток
не сгорает и остаётся при остановке; в режиме чтения SMS не уходят
(`SMS_READONLY`); своё имя платное, годом с одобрения (в черновике было «fără
plată» — это про операторов); раздел 16 сам служит договором обработки, по
просьбе клиники — отдельным актом (вопрос юристу 1 решён так до юриста).
Цены — «prețul indicat în nota de plată»: в Git их нет. Числа § 16 держит
`cloud/tests/test_contract.py`. Осталось: тексты программы (§ 4 ниже — вместе
с S5/S6, по состоянию клиники), письмо клиникам (§ 6), новая подпись
декларации, пометка «PROIECT» на бумагах 5–6 в `clinics\lege-195`.

Ниже — черновики в том виде, в каком их собрали 16.10 (до переноса). Тогда
живые страницы и тексты программы НЕ трогались намеренно:
- декларация подписана КЭП 02.10 и обещает клиникам предупреждение за 30 дней
  (п. «Modificări»);
- условия обещают то же (§ 13), а их дата «Ultima actualizare» — это
  `TERMS_VERSION` в `bot/app/core/license.py`: правка страницы — уже выпуск
  программы;
- обещать услугу, которой ещё нет, нельзя.

Порядок: юрист читает этот файл (вопросы — [sms.md](sms.md) › «Вопросы
юристу», плюс 6 ниже) → правки → Олег подписывает новую декларацию → тексты
садятся на страницы и в программу одним выпуском → письмо клиникам → через 30
дней первая SMS (S7).

Тексты — румынский, как на страницах; русские — там, где их печатает
программа. В квадратных скобках — то, что решает Олег (S0) или юрист.
Бумаги клиники (её реестр, информирование, договор об обработке, заявление
sms.md) лежат вне этого репозитория, в `clinics\lege-195` (5, 6 и
SMS-разделы 0–2). Здесь — только то, что публикует поставщик и печатает
программа.

Вопрос юристу 6 (новый, к пяти из sms.md): номер и текст **проходят** через
сервер поставщика, а он стоит у Contabo GmbH в центре данных ЕС (privacy.html
§ 5). Это передача за границу в смысле Закона 195/2024, если на сервере данные
не хранятся, а только транзитом уходят в sms.md (серверы в Молдове)? Нужна ли
строка «transfer în străinătate» в реестре клиники?

## 1. Declarația furnizorului (`docs/site/declaratie-195.html`)

Вступление, п. 1, «Copiile de rezervă» и «Modificări» — без изменений. Новая
дата — день подписи. Ниже — пункты, которые меняются, и один новый.

> **2. Furnizorul nu are acces la fișele pacienților.** Furnizorul nu are
> acces la fișele, programările, documentele și tratamentele pacienților și
> nu le prelucrează. Operator pentru datele pacienților este clinica.
> Singura excepție este Pachetul SMS (punctul 4), doar pentru clinicile care
> îl activează.
>
> **3. Ce primește furnizorul de la program.** Programul nu transmite
> furnizorului informații despre tratamente. Legăturile programului cu
> furnizorul sunt patru:
> - actualizările — *(fără schimbări)*;
> - activarea din program — *(fără schimbări)*;
> - verificarea licenței — *(fără schimbări)*;
> - memento-urile SMS — doar dacă clinica activează Pachetul SMS: pentru
>   fiecare memento programul trimite serverului furnizorului numărul de
>   telefon mobil al pacientului și textul memento-ului (denumirea clinicii,
>   ziua, data și ora vizitei și, dacă clinica alege, telefonul clinicii).
>   Textul nu conține numele pacientului, medicul, serviciul sau alte
>   informații despre tratament.
>
> Fișierul de licență conține doar denumirea clinicii, IDNO, tipul și
> termenul abonamentului.
>
> **4. Pachetul SMS.** Pentru datele de la punctul 3 care servesc
> memento-urilor SMS furnizorul este persoană împuternicită a clinicii, în
> condițiile Acordului de prelucrare a datelor pentru Pachetul SMS. Serverul
> furnizorului transmite numărul și textul operatorului SMS Rock Soft S.R.L.
> (SMS.MD), altă persoană împuternicită, și nu le păstrează: rămân doar
> identificatorul mesajului, numărul de segmente și starea livrării. SMS.MD
> păstrează mesajele pe servere din Republica Moldova timp de 3 luni și le
> șterge mai devreme la cerere. Memento-urile se trimit doar pe numere mobile
> din Republica Moldova.
>
> **5. Datele contului clinicii.** *(fostul punct 4, fără schimbări)*

## 2. Termeni și condiții (`docs/site/termeni.html`)

Новый раздел **добавляется последним**, а не вставляется внутрь: номера
§ 1–15 упоминаются в [contract.md](contract.md) и в письмах. Три правки в
действующих разделах — только оговорки со ссылкой на § 16.

**§ 2, первое предложение:**
> Programul rulează local, pe calculatorul clinicii, și nu depinde de
> internet în lucrul de zi cu zi; excepție face doar Pachetul SMS (§ 16),
> care are nevoie de internet și de serverul furnizorului.

**§ 9, п. 1 — дописать в конец:**
> Excepție: dacă clinica activează Pachetul SMS, pentru numerele de telefon
> și textele memento-urilor furnizorul este persoană împuternicită, în
> condițiile § 16.

**§ 10 — дописать в конец:**
> Memento-urile SMS (§ 16) pleacă doar cât programul are internet și
> serverul furnizorului răspunde; cele rămase se trimit când legătura revine,
> dacă vizita nu a început.

**§ 16. Pachetul SMS (serviciu opțional)**
> 1. Pachetul SMS trimite pacienților clinicii, în numele ei, memento-uri
>    despre vizitele programate. Serviciul este opțional și se activează
>    separat, din program (Setări › SMS) sau la cererea clinicii.
> 2. Pachetul este un număr de segmente SMS plătit în avans, la prețul din
>    oferta în vigoare la data plății; plata se face ca la abonament (§ 4).
>    Un segment este o SMS de până la 160 de caractere latine fără diacritice
>    (70 de caractere chirilice). [Termenul pachetului: nu expiră / … luni —
>    decizia S0.]
> 3. Un segment se consumă când mesajul este predat operatorului de
>    telefonie, inclusiv atunci când nu poate fi livrat (telefon închis mai
>    mult de 24 de ore, număr inactiv). Mesajele refuzate înainte de predare
>    se întorc în pachet. Restul pachetului se vede în program.
> 4. Textele memento-urilor le stabilește furnizorul. Ele conțin doar
>    denumirea clinicii, ziua, data și ora vizitei și, la alegerea clinicii,
>    telefonul clinicii — fără numele pacientului, medic, serviciu sau alte
>    informații despre tratament. Clinica alege ce memento-uri se trimit (în
>    ajun, cu 2 ore înainte). Memento-ul din ajun pleacă în ultima zi
>    lucrătoare a clinicii dinaintea vizitei; niciun mesaj nu pleacă înainte
>    de ora 08:00 sau după ora 21:00. Pachetul nu se folosește pentru
>    publicitate.
> 5. Până la aprobarea numelui propriu al clinicii, mesajele pleacă de la
>    numele „DentPilot”, cu denumirea clinicii în text. Numele propriu (până
>    la 11 caractere) îl aprobă operatorii, fără plată, în 1–2 zile
>    lucrătoare, pe baza cererii scrise a clinicii.
> 6. Memento-urile se trimit doar pe numere mobile din Republica Moldova.
>    Clinica informează pacienții și respectă refuzul lor: pacientului marcat
>    „Fără remindere SMS” în fișă programul nu îi trimite memento-uri.
> 7. Furnizorul nu garantează livrarea fiecărui mesaj: ea depinde de
>    operatorii de telefonie și de telefonul pacientului. Un mesaj poate
>    ajunge cu întârziere de până la 24 de ore; de aceea textul conține
>    întotdeauna data vizitei.
> 8. Pentru numerele de telefon și textele memento-urilor clinica este
>    operator, iar furnizorul — persoană împuternicită, în condițiile
>    Acordului de prelucrare a datelor pentru Pachetul SMS [parte a acestor
>    termeni / semnat separat — întrebarea 1 la jurist]. Furnizorul folosește
>    ca altă persoană împuternicită operatorul SMS Rock Soft S.R.L. (SMS.MD,
>    servere în Republica Moldova, păstrare 3 luni) și anunță clinica cu 30 de
>    zile înainte de a-l schimba; clinica poate atunci dezactiva pachetul.
> 9. Clinica poate opri memento-urile oricând, din program. [Segmentele
>    rămase: rămân în cont / se restituie — decizia S0.] [În regim de citire
>    (§ 6) memento-urile pentru vizitele deja programate: pleacă / nu pleacă —
>    decizia S0.]

## 3. Politica de confidențialitate (`docs/site/privacy.html`)

**§ 4 — заменить абзац:**
> Programul DentPilot rulează local, pe computerul clinicii. Furnizorul
> **nu are acces la fișele pacienților**; operator de date pentru pacienți
> este clinica. Excepție: dacă clinica activează Pachetul SMS, serverul
> furnizorului primește, pentru fiecare memento, numărul de telefon mobil al
> pacientului și textul memento-ului (denumirea clinicii, ziua, data și ora
> vizitei), le transmite operatorului SMS Rock Soft S.R.L. (SMS.MD, servere în
> Republica Moldova) și nu le păstrează. Pentru aceste date furnizorul este
> persoană împuternicită a clinicii (Termeni și condiții, § 16). Prin acest
> site nu se prelucrează date ale pacienților.

**§ 5, «Ce nu conține» — первое предложение:**
> Date ale pacienților — cu excepția memento-urilor SMS de la § 4, care
> tranzitează serverul și nu rămân pe el.

**§ 5, «Cine le vede» — дописать:**
> … și, pentru clinicile cu Pachetul SMS, a operatorului SMS Rock Soft S.R.L.
> (SMS.MD), căruia furnizorul îi transmite cererea clinicii pentru numele
> expeditorului (denumirea, IDNO, datele reprezentantului).

## 4. Тексты программы

Все печатаются **по состоянию клиники**: включён пакет — вариант «SMS»,
выключен — прежний текст как есть. Состояние одно — то же, что решает отправку
(`sms_account().enabled` из S5), иначе бумага разойдётся с программой.

**`modules/patients/acord.py` › `store`** (лист на стойке; ⚠️ основания
обязаны совпадать с `clinics\lege-195\1-informare-pacienti.html` — правило
`patients.md`):
> RO: Fișele electronice se păstrează **local, pe calculatorul clinicii**
> (programul DentPilot) și nu sunt transmise dezvoltatorului programului.
> Pentru memento-urile SMS se transmit doar numărul de telefon și data și ora
> vizitei, prin serverul dezvoltatorului (care nu le păstrează), operatorului
> SMS.MD (Rock Soft S.R.L.), care le păstrează 3 luni. Datele pot fi
> transmise doar … *(дальше без изменений)*
>
> RU: Электронные карты хранятся **локально, на компьютере клиники**
> (программа DentPilot) и не передаются разработчику программы. Для
> SMS-напоминаний передаются только номер телефона, дата и время визита —
> через сервер разработчика (он их не хранит) оператору SMS.MD (Rock Soft
> S.R.L.), который хранит их 3 месяца. Данные могут быть переданы только …
> *(дальше без изменений)*

**`acord.py` › `li4`:**
> RO: remindere despre vizita programată (prin SMS) — **interesul legitim**
> al clinicii; puteți renunța oricând, la recepție.
>
> RU: напоминания о назначенном визите (по SMS) — **законный интерес**
> клиники; вы можете отказаться в любой момент на стойке.

**`modules/settings/system.py` › `privacy_html`, первый абзац:**
> RO: **Programul funcționează local.** Fișele pacienților nu sunt transmise
> dezvoltatorului și nu sunt stocate pe serverele acestuia. Pentru
> memento-urile SMS programul trimite doar numărul de telefon și data și ora
> vizitei, care trec prin serverul dezvoltatorului spre operatorul SMS și nu
> rămân pe el. Actualizările descarcă doar fișierele programului. …
>
> RU: Программа работает локально. Карты пациентов не передаются
> разработчику и не хранятся на его серверах. Для SMS-напоминаний программа
> передаёт только номер телефона, дату и время визита — они проходят через
> сервер разработчика к оператору SMS и не остаются на нём. …

**`modules/settings/faq.py` (ответ про закон 195):**
> Fișele stau **doar pe acest calculator** — nimic din ele nu pleacă pe
> servere străine. Memento-urile SMS trimit doar numărul de telefon și data
> și ora vizitei, prin operatorul SMS.MD. Documentele generale (informarea de
> la recepție, registrul de evidență) le primiți de la furnizor.

## 5. Сайт — страницы «Descarcă» (`docs/site/descarca*.html`)

Это общие страницы, не по клинике, поэтому — оговорка вместо условия.

**RO, «Operatorul datelor este clinica» — второе и третье предложения
первого абзаца:**
> … De aceea, în sensul Legii nr. 195/2024, operator pentru datele
> pacienților este clinica. Furnizorul programului nu prelucrează fișele
> pacienților; doar dacă clinica activează Pachetul SMS, el transmite, ca
> persoană împuternicită, numărul de telefon și ora vizitei pentru
> memento-uri. …

**RO, второй абзац — последнее предложение:**
> Despre fișele pacienților programul nu trimite nimic; Pachetul SMS, dacă
> este activat, trimite doar numărul de telefon și data și ora vizitei.

**RU, те же места:**
> … Поставщик программы не обрабатывает карты пациентов; только если клиника
> включает SMS-пакет, он как уполномоченное лицо передаёт номер телефона и
> время визита для напоминаний. …
>
> О картах пациентов программа не передаёт ничего; SMS-пакет, если он
> включён, передаёт только номер телефона, дату и время визита.

## 6. Письмо клиникам за 30 дней (S1 → S7)

Всем клиникам с действующим абонементом и пробным периодом — по декларации
(«Modificări») и по условиям (§ 13). Отправка из админки облака одним
письмом.

> **Subiect:** DentPilot — Pachetul SMS și declarația actualizată privind
> datele pacienților
>
> Bună ziua,
>
> De la «data S7» DentPilot oferă, opțional, **Pachetul SMS**: memento-uri
> despre vizite trimise pacienților în numele clinicii. Pentru clinicile care
> nu îl activează nu se schimbă nimic.
>
> Pentru clinicile care îl activează, programul va trimite serverului
> DentPilot numărul de telefon al pacientului și textul memento-ului
> (denumirea clinicii, data și ora vizitei — fără nume, medic sau tratament);
> serverul le transmite operatorului SMS.MD și nu le păstrează. Pentru aceste
> date DentPilot devine persoană împuternicită a clinicii.
>
> De aceea am actualizat Declarația furnizorului, Termenii și condițiile
> (§ 16, nou) și Politica de confidențialitate. Versiunile noi intră în
> vigoare la «data S7»; le găsiți la dentpilot.md, iar declarația semnată —
> atașată.
>
> Întrebări — la acest e-mail sau la +373 60 508 048.
>
> Cu respect,
> Oleg Bacalu, DentPilot

## 7. `contract.md` — что добавить при S7

В таблицу «обещание ↔ программа» (не раньше, чем есть код: строки называют
константы, и `test_contract` их сверяет):

| Обещание | Программа / сервер | Где |
|---|---|---|
| в тексте нет имени, врача, услуги | белый список подстановок, сторож `test_structure` | `bot/app/core/sms*.py` |
| номер и текст на сервере не остаются | колонок нет; сторож «цифр номера нет в базе и в логе» | `cloud/app/sms.py`, `cloud/app/db.py` |
| только номера Молдовы | `sms_rule.phone` — `77…` и зарубежные отказ | `bot/app/core/sms_rule.py`, `cloud/app/sms_rule.py` |
| не раньше 08:00 и не позже 21:00 | тихие часы в программе и на сервере | `core/sms.py`, `cloud/app/sms.py` |
| сегмент — 160/70 знаков, отказ до оператора возвращается | `sms_rule.parts`, строка `refund` на 10/11 | `cloud/app/sms.py` |
| отказ пациента соблюдается | `patients.sms_off` мимо цикла | `bot/app/db.py` |

П. 9 таблицы «Суть по пунктам» получает оговорку о § 16.
