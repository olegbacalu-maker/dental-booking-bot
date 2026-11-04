"""Ответ на действие: словарь MSG_BANNER и его читатели.

Коды, которыми маршруты отвечают друг другу и пользователю. Словарь общий
намеренно: как только каждый модуль заведёт свои тексты, «Programare adăugată»
начнёт звучать в трёх вариантах. ⛔ Имя MSG_BANNER вне этого файла, `banners`
и `license_pages` — нарушение (держит `test_structure`); остальным — `msg_*`.
"""
from __future__ import annotations

import html

from fastapi.responses import JSONResponse

from . import sms_loop
from .auth import PIN_MIN_LAN
from .icons import _ic


MSG_BANNER = {
    # Ворота лицензии (core/license.py, L4): один код на страницы и на JSON
    "license_readonly": ("err", "Programul este în regim de citire: abonamentul a "
                                "expirat. Datele se pot consulta, tipări și exporta; "
                                "pentru a continua lucrul, activați abonamentul."),
    "license_missing": ("err", "Programul nu are o licență activată — trimiteți cererea "
                               "pe pagina de activare."),
    "license_ok": ("ok", "Licența a fost activată"),
    "license_malformed": ("err", "Fișierul nu este un fișier de licență DentPilot "
                                 "sau este deteriorat"),
    "license_key_unknown": ("err", "Fișierul a fost emis cu o cheie pe care această "
                                   "versiune a programului nu o cunoaște — actualizați "
                                   "programul sau cereți un fișier nou"),
    "license_bad_signature": ("err", "Semnătura fișierului nu corespunde conținutului — "
                                     "fișierul a fost modificat sau este corupt"),
    "license_older": ("err", "Fișierul este mai vechi decât licența deja activată"),
    "license_terms": ("err", "Bifați acceptarea Termenilor și condițiilor și trimiteți din nou"),
    # Активация без файла (26.09): заявка на пробный со страницы активации;
    # коды — license.REQUEST_*. Отказ сервера страница дописывает его словами.
    "license_requested": ("ok", "Cererea a fost trimisă la DentPilot — programul se activează "
                                "singur imediat ce o aprobăm"),
    "license_request_refused": ("err", "DentPilot nu a primit cererea"),
    "license_request_offline": ("err", "Serverul DentPilot nu a răspuns — verificați conexiunea "
                                       "la internet și încercați din nou"),
    "license_request_declined": ("err", "Cererea de perioadă de probă nu mai este activă — "
                                        "scrieți-ne sau trimiteți o cerere nouă"),
    # Новый компьютер той же клиники: повтор заявки → код на e-mail клиники
    "license_request_code": ("ok", "Clinica este deja înregistrată la DentPilot — am trimis un cod "
                                   "de activare pe e-mailul clinicii"),
    "license_code_bad": ("err", "Codul nu este corect sau a expirat — verificați e-mailul sau "
                                "trimiteți din nou cererea pentru un cod nou"),
    # Автообновление (L13): ответ кнопки «Verifică acum» на странице лицензии;
    # коды — license.RENEW_CODES, по одному на исход запроса к серверу
    # Файл клинике не показывается (02.10): слова — про лицензию и срок
    "license_renewed": ("ok", "Licența a fost reînnoită de pe serverul DentPilot"),
    "license_renew_same": ("ok", "Nu există o licență mai nouă pe serverul DentPilot"),
    "license_renew_offline": ("err", "Serverul DentPilot nu a răspuns — verificați conexiunea "
                                     "la internet; programul încearcă din nou zilnic"),
    "license_renew_refused": ("err", "Serverul DentPilot nu a recunoscut licența acestei "
                                     "clinici — contactați DentPilot"),
    "license_renew_bad": ("err", "Răspunsul serverului DentPilot nu a putut fi verificat — "
                                 "contactați DentPilot"),
    "license_renew_none": ("err", "Licența activată nu are adresă de reînnoire — "
                                  "contactați DentPilot"),
    # E-mail клиники (27.10): ответы блока «Adresa de e-mail» на странице лицензии;
    # коды — license.EMAIL_*. Отказ сервера страница дописывает его словами.
    "license_email_sent": ("ok", "Am trimis un e-mail nou cu linkul și codul de confirmare — "
                                 "verificați și dosarul Spam"),
    "license_email_confirmed": ("ok", "Adresa de e-mail a clinicii este confirmată"),
    "license_email_changed": ("ok", "Adresa de e-mail a fost schimbată — am trimis pe ea linkul și "
                                    "codul de confirmare"),
    "license_email_refused": ("err", "DentPilot nu a acceptat cererea"),
    "license_email_offline": ("err", "Serverul DentPilot nu a răspuns — verificați conexiunea "
                                     "la internet și încercați din nou"),
    # Акт акцепта условий (29.10): ответ «Accept» баннера и страницы лицензии — license.TERMS_OK
    "license_terms_ok": ("ok", "Ați acceptat versiunea actualizată a Termenilor și condițiilor DentPilot — "
                               "actul este păstrat în folderul de date al clinicii și la DentPilot"),
    "ok": ("ok", "Programare adăugată"),
    "conflict": ("err", "Intervalul este deja ocupat la acest medic"),
    "dup": ("err", "Pacientul are deja o programare la această oră"),
    "past": ("err", "Ora aleasă a trecut deja — reîmprospătați lista orelor libere"),
    "ok_past": ("warn", "Programare adăugată — atenție: este pe o zi trecută. "
                        "Verificați data dacă nu ați vrut asta"),
    "bad": ("err", "Date invalide — verificați câmpurile"),
    "bad_name": ("err", "Lipsește numele pacientului"),
    "bad_phone": ("err", "Numărul de telefon pare incomplet — sunt necesare "
                         "minim 6 cifre (numerele străine sunt acceptate)"),
    "bad_bd": ("err", "Data nașterii nu este validă — verificați ziua, luna și "
                      "anul (nu poate fi în viitor)"),
    "bad_idnp": ("err", "IDNP trebuie să aibă exact 13 cifre — verificați "
                        "câmpul evidențiat"),
    "bad_off": ("err", "Medicul nu este activ (concediu sau arhivat) — "
                       "alegeți alt medic sau readuceți-l din concediu în Medici"),
    "bad_time": ("err", "Ora poate fi doar fixă sau la jumătate (ex. 10:00, 10:30)"),
    "ok_note": ("ok", "Notiță adăugată — ora este blocată"),
    "ok_move": ("ok", "Programare mutată"),
    # ⚠️ Оба отказа переноса говорят, ЧТО делать дальше. Перетаскивают с
    # открытого журнала, а он живёт с автообновлением: пока тянули, соседняя
    # вкладка могла и отменить визит, и завершить его.
    "mv_gone": ("err", "Programarea nu mai există — reîmprospătați pagina"),
    "mv_closed": ("err", "Se mută doar programările active — cea finalizată, "
                         "anulată sau neprezentată rămâne pe loc (redeschideți-o "
                         "dacă chiar trebuie mutată)"),
    # переход статуса, которого из текущего состояния нет (17.10): вкладка
    # смотрела на устаревшую карточку — соседняя уже отметила исход
    "bad_step": ("err", "Starea programării s-a schimbat între timp — "
                        "reîmprospătați pagina și alegeți din nou"),
    # ⚠️ Текст обязан сказать, ЧТО делать, а не только что случилось: иначе
    # регистратура прочтёт «добавлено» и пойдёт дальше, а визит останется в
    # чужой карточке.
    "ok_other": ("warn", "Programare adăugată — dar la fișa unui pacient care "
                         "există deja cu acest telefon și are alt nume. Dacă "
                         "este altă persoană (numărul familiei), deschideți "
                         "fișa și mutați programarea, sau adăugați pacientul "
                         "separat din Pacienți"),
    "ok_comment": ("ok", "Comentariu salvat"),
    # смена процедуры у стоящей записи (22.10, окно визита): отказы говорят,
    # что делать дальше, — как у переноса
    "ok_svc": ("ok", "Procedura a fost schimbată"),
    "svc_closed": ("err", "Procedura se schimbă doar la programările active — cea "
                          "finalizată, anulată sau neprezentată rămâne cum a fost "
                          "(redeschideți-o dacă chiar trebuie schimbată)"),
    "svc_doc": ("err", "Medicul acestei programări nu face procedura aleasă — "
                       "alegeți altă procedură sau mutați programarea la alt medic"),
    "ok_set": ("ok", "Setări salvate"),
    # «Rechemări» (29.10): отметка обзвона (`/api/recall/mark`) и визит с бумаги
    "ok_recall": ("ok", "Marcaj salvat"),
    "bad_recall": ("err", "Marcajul nu a putut fi salvat — verificați data și încercați din nou"),
    "recall_gone": ("err", "Pacientul nu mai este în lista de rechemări — "
                           "reîmprospătați pagina"),
    # кнопка «SMS» в строке «Rechemări» (30.10, В1 = А): отказы ДО сервера —
    # свои слова; код сервера едет его словами через `sms_denied` + text
    "ok_recall_sms": ("ok", "SMS trimis"),
    "recall_sms_dup": ("err", "SMS-ul pentru acest termen a fost deja trimis — "
                              "reîmprospătați pagina"),
    "recall_sms_off": ("err", "Butonul SMS din Rechemări este oprit — porniți-l în Setări › SMS"),
    "recall_sms_refused": ("err", "Pacientul a refuzat memento-urile SMS (bifa din fișă) — "
                                  "sunați sau scrieți"),
    "recall_sms_phone": ("err", "Numărul pacientului nu este un mobil din Moldova — sunați sau scrieți"),
    "recall_no_phone": ("err", "Completați telefonul clinicii în Setări › Clinica — "
                               "el intră în textul SMS-ului"),
    "recall_sms_quiet": ("err", f"SMS-urile se trimit între {sms_loop.plan.QUIET_END:02d}:00 și "
                                f"{sms_loop.plan.QUIET_START:02d}:00 — reveniți dimineața"),
    # галочка «Vizita a avut loc» в окне записи на прошедший день (В3 = А):
    # запись ложится сразу «finalizată» — история с бумаги, одним шагом
    "ok_past_done": ("ok", "Vizita a fost adăugată ca finalizată pe o zi trecută — "
                           "intră în istoric și în Rechemări"),
    # SMS-пакет (S6): Setări › SMS — ответы JSON API; отказ сервера едет его же
    # словами (`msg_json(text=…)`: словарь CODES облака — один на обе стороны)
    "ok_sms": ("ok", "Setări SMS salvate"),
    "bad_sms": ("err", "Setările SMS nu au putut fi citite"),
    "sms_order_ok": ("ok", "Nota de plată a fost emisă și trimisă pe e-mailul clinicii"),
    "sms_sender_ok": ("ok", "Cererea pentru numele expeditorului a fost trimisă — urmează cererea "
                            "semnată pentru operatori"),
    "sms_test_ok": ("ok", "SMS de test trimis"),
    "sms_offline": ("err", "Serverul DentPilot nu a răspuns — încercați mai târziu"),
    "sms_token": ("err", "Serverul nu a recunoscut licența programului — verificați licența"),
    "sms_denied": ("err", "Serverul a refuzat cererea"),
    "sms_unavailable": ("err", "Memento-urile SMS sunt disponibile doar în programul activat cu licență"),
    "ok_theme": ("ok", "Aspectul clinicii a fost salvat"),
    "bad_crypt": ("err", "Nu am putut pregăti criptarea — cheia nu a fost salvată. "
                         "Detalii în data\\dentpilot.log"),
    "crypt_on": ("warn", "Criptarea este deja activă. Pentru a o reface, opriți-o "
                         "mai întâi — altfel foaia tipărită nu ar mai deschide baza"),
    "ok_logo": ("ok", "Logo actualizat — apare la intrare și pe documentele tipărite"),
    "no_logo": ("ok", "Logo șters"),
    # ⚠️ Текст называет ПРИЧИНУ отказа: «logo invalid» отправило бы директора
    # искать ошибку в картинке, которая на вид открывается — а отказали ей за
    # формат (SVG) или за размер.
    "bad_logo": ("err", "Logo neacceptat — doar PNG sau JPEG, cel mult 2 MB. "
                        "SVG nu se acceptă din motive de securitate."),
    "upd_err": ("err", "Actualizarea a eșuat — vezi detalii în pagina de setări / log"),
    # второй клик по «Actualizează acum», пока первый ещё качает (17.10)
    "upd_busy": ("warn", "Actualizarea este deja în curs — așteptați: programul se "
                         "închide și repornește singur"),
    # Вход (форма и JSON-дверь смены человека, B4.4): одни слова на обе двери.
    # Блокировка подбора на входе — тем же `lock_pin`, что у смены PIN: одно
    # состояние, одно слово.
    "login_bad": ("err", "PIN greșit"),
    "auth_broken": ("err", "Fișierul de acces e deteriorat — restaurați "
                           "data\\auth.json din copia de rezervă."),
    "ok_pin": ("ok", "PIN schimbat"),
    # ⚠️ границы НЕ называются: «4–6» пережило подъём потолка до 8 (08-13), а
    # с 17.10 минимум зависит от сети (`auth.pin_min`) — словарь импортом
    # заморозил бы старое. Диапазон показывает само поле формы.
    "bad_pin": ("err", "PIN-ul vechi e greșit sau cel nou nu are numărul de "
                       "cifre cerut (vezi câmpul) ori cele două nu coincid"),
    "lock_pin": ("warn", "Prea multe încercări greșite — așteptați câteva minute"),
    # Включение сети задержано учётками (17.10): список — на самой странице
    "lan_pins": ("err", f"Accesul din rețea nu se poate porni: unele PIN-uri au "
                        f"sub {PIN_MIN_LAN} cifre — setați-le unul nou (lista e pe "
                        f"această pagină)"),
    # ⚠️ dental.env не удалось ПРОЧИТАТЬ (придержан антивирусом/OneDrive или
    # сохранён в нечитаемой кодировке) — запись отменена, файл не тронут.
    "bad_env": ("err", "Nu am putut salva: fișierul dental.env nu a putut fi "
                       "citit (poate fi blocat de alt program). Închideți "
                       "programele care îl folosesc și încercați din nou; "
                       "detalii în data\\dentpilot.log"),
    "part_note": ("ok", "Pauza a fost salvată parțial — unele ore erau deja ocupate"),
    "bad_set": ("err", "Setări invalide — verificați câmpurile (nume/telefon, ore, minim un medic și un serviciu)"),
    "outside": ("err", "Vizita nu încape în programul clinicii (închidere sau pauză)"),
    # клиника открыта, но у ЭТОГО врача график уже кончился (work_from/work_to)
    "outside_doc": ("err", "Medicul nu lucrează la ora aleasă — verificați "
                           "programul lui în pagina Medici sau alegeți alt medic"),
    # ⚠️ <input type=date> отдаёт и «0012-08-15» — промах по сегменту года
    # выглядит законной ISO-датой, а период из неё выходит в 735 000 дней.
    # Текст обязан назвать ПОЛЕ, иначе директор ищет ошибку не там.
    "bad_period": ("err", "Perioada aleasă nu este validă — verificați anul în "
                          "câmpurile de date; intervalul poate fi de cel mult "
                          "un an și nu mai vechi de anul 2000"),
    "ok_card": ("ok", "Fișa pacientului a fost actualizată"),
    "ok_punte": ("ok", "Puntea a fost salvată"),
    "ok_punte_del": ("ok", "Puntea a fost ștearsă"),
    "bad_punte": ("err", "Puntea nu este validă — dinți învecinați de pe "
                         "aceeași arcadă, cu cel puțin un stâlp"),
    "dup_punte": ("err", "Un dinte face deja parte din altă punte — "
                         "ștergeți-o întâi pe aceea"),
    # запись пачкой одонтограммы (волна 2, 25.10): зуб изменился с тех пор,
    # как экран начал его править; `{n}` — номер, подставляет маршрут
    "odo_conflict": ("err", "Dintele {n} a fost modificat între timp pe alt calculator. "
                            "Nimic nu a fost salvat — verificați dintele și salvați din nou."),
    "ok_perio": ("ok", "Parodontograma a fost salvată"),
    # ⚠️ Записано ВСЁ и ничего не потеряно — правило `covers` не даёт стереть
    # чужое. Это предупреждение, а не отказ: осмотр под записывающим успело
    # поправить второе рабочее место, и он обязан об этом узнать.
    "ok_perio_merged": ("warn", "Parodontograma a fost salvată. Atenție: "
                                "între timp examenul a fost modificat și de "
                                "pe alt calculator — măsurătorile s-au "
                                "îmbinat, verificați-le"),
    "ok_perio_new": ("ok", "Examen parodontal nou — introduceți măsurătorile"),
    "ok_perio_del": ("ok", "Examenul gol a fost șters"),
    # ⛔ Осмотр с измерениями не удаляется никем: это медицинская запись, её
    # правят, а не заставляют исчезнуть (то же правило, что у дневника визита).
    "bad_perio_del": ("err", "Examenul are măsurători și nu se șterge — "
                             "corectați valorile în el"),
    "bad_perio": ("err", "Examenul parodontal nu a fost găsit"),
    # ⚠️ Архивация УБИРАЕТ пациента из списка, и общее «фиша обновлена» об этом
    # молчит: человек возвращается в список, никого там не находит и решает,
    # что запись пропала. Сообщение обязано назвать, где искать.
    "ok_arh": ("ok", "Pacient trecut în arhivă — nu mai apare în listă. "
                     "Îl găsiți prin filtrul de status «Arhivat» sau "
                     "căutându-l după nume"),
    "ok_unarh": ("ok", "Pacient scos din arhivă — apare din nou în listă"),
    "ok_pay": ("ok", "Plata a fost înregistrată"),
    "bad_pay": ("err", "Sumă sau metodă invalidă — verificați plata"),
    "pay_del": ("ok", "Plata a fost ștearsă — urma rămâne în istoricul fișei"),
    "bad_export": ("err", "Nu am putut pregăti arhiva cu datele pacientului — "
                          "verificați spațiul pe disc; detalii în data\\dentpilot.log"),
    "ok_del": ("ok", "Fișa pacientului a fost ștearsă definitiv"),
    "ok_anon": ("ok", "Datele de identitate au fost șterse — înregistrările "
                      "medicale rămân sub numărul fișei"),
    "bad_erase": ("err", "Pentru ștergere scrieți STERG în câmpul de confirmare"),
    "bad_bkp_pass": ("err", "Parola arhivei trebuie să aibă cel puțin 10 caractere"),
    # Внешняя копия по расписанию и восстановление (17.10, core/backup_loop,
    # core/restore): один код на страницу и на JSON, как у всех
    "ok_bkp_auto": ("ok", "Folderul copiei a fost salvat — prima copie în afara "
                          "calculatorului se face în câteva minute"),
    "ok_bkp_off": ("ok", "Copia în afara calculatorului a fost oprită — rămâne "
                         "copia zilnică de pe acest calculator"),
    # выключатель «Copie zilnică automată» (17.10 вечером, слово Олега)
    "ok_bkp_on": ("ok", "Copia zilnică automată este pornită"),
    "ok_bkp_stop": ("warn", "Copia zilnică automată este oprită — rămâne doar copia "
                            "făcută la pornirea programului"),
    "bad_bkp_folder": ("err", "Folderul nu există sau nu se poate scrie în el — alegeți un "
                              "folder de pe alt disc, de pe un stick USB sau din folderul "
                              "cloud al clinicii"),
    "bad_bkp_inside": ("err", "Folderul este în interiorul folderului cu date al programului "
                              "— o copie păstrată lângă original dispare împreună cu el"),
    "bad_bkp_unset": ("err", "Alegeți întâi folderul și parola copiei în afara "
                             "calculatorului"),
    "ok_bkp_run": ("ok", "Copia de rezervă externă a fost făcută"),
    # Нет папки вне компьютера (02.11, разбор коллеги): копии лежат на том же
    # диске, что и картотека, и умирают вместе с ним — молчать об этом нельзя.
    # Строка экранов копий (`backup_loop.line` → Stare sistem, Copie de
    # rezervă), НЕ баннер каркаса (Олег 02.11). Ссылку на настройку дописывает
    # Stare sistem, поэтому точки в конце нет.
    "bkp_no_offsite": ("warn", "Copiile de rezervă sunt doar pe acest calculator — dacă "
                               "discul se defectează, se pierd odată cu evidența. Alegeți "
                               "un folder pe alt disc, un stick USB sau folderul cloud al "
                               "clinicii"),
    "bad_bkp_auto": ("err", "Copia de rezervă externă nu s-a făcut"),
    "ok_rst_staged": ("ok", "Copia a fost verificată — confirmați restaurarea"),
    "bad_rst_pass": ("err", "Parola arhivei nu este corectă"),
    "bad_rst_file": ("err", "Fișierul nu este o copie de rezervă DentPilot sau este "
                            "deteriorat"),
    "bad_rst_src": ("err", "Fișierul nu a fost găsit — verificați calea"),
    "bad_rst_newer": ("err", "Copia provine dintr-o versiune mai nouă a programului — "
                             "actualizați programul, apoi restaurați"),
    "bad_rst_none": ("err", "Nu există o copie verificată — alegeți întâi copia"),
    "ok_rst_ordered": ("ok", "Restaurarea se face la următoarea pornire a programului"),
    "ok_rst_cancel": ("ok", "Restaurarea a fost anulată"),
    "bad_bkp": ("err", "Nu am putut crea arhiva de rezervă — verificați spațiul "
                       "pe disc; detalii în data\\dentpilot.log"),
    "bad_card": ("err", "Date invalide — verificați câmpurile fișei"),
    # ⚠️ Отказ подтверждается ТЕКСТОМ, поэтому и сообщение говорит, что делать
    # дальше с бумагой: без подписи запись по ст.13(5) неполна, а регистратура
    # об этом не знает — «refuz înregistrat» она прочла бы как «готово»
    "ok_refuz": ("ok", "Refuzul a fost consemnat în fișă — tipăriți acordul "
                       "informat și dați-l la semnat pacientului și medicului"),
    "bad_refuz": ("err", "Scrieți motivul refuzului și consecințele explicate "
                         "pacientului — legea cere ca acestea să fie "
                         "consemnate, nu doar bifat refuzul"),
    # ⛔ Удаление позиции, которую уже начали, закончили или от которой пациент
    # отказался, — стирание меддокументации. Текст обязан назвать выход
    "bad_pdel": ("err", "Se poate șterge doar o poziție neîncepută. Procedura "
                        "începută, finalizată sau refuzată rămâne în fișă — "
                        "închideți-o prin statut"),
    # ⚠️ Удаляют то, чего в фише уже нет: чаще всего его сняли со второго
    # рабочего места, пока эта вкладка стояла открытой. Текст говорит, что
    # делать, как у mv_gone; фиша в ответ не едет (patients/api.py, `_GONE`).
    "alert_gone": ("err", "Atenționarea nu mai există — reîmprospătați pagina"),
    "plan_gone": ("err", "Poziția din plan nu mai există — reîmprospătați pagina"),
    "doc_gone": ("err", "Documentul nu mai există — reîmprospătați pagina"),
    "pay_gone": ("err", "Plata nu mai există — reîmprospătați pagina"),
    "new_pat": ("ok", "Pacient adăugat — completați fișa (dinți, plan, documente)"),
    # ⚠️ Сохранение НЕ отменяется — названо вслух (та же логика, что ok_other:
    # регистратуре нужна скорость, а молчаливый запрет читался бы как «программа
    # не работает»). Совет «номер второго — в notițe» опирается на то, что поиск
    # находит цифры и в заметках (_pl_match_q, 08-20).
    "ok_tel_dup": ("warn", "Fișa a fost salvată, dar acest număr de telefon "
                           "există deja la alt pacient. Dacă sunt persoane "
                           "diferite cu un telefon comun, treceți numărul în "
                           "notițele fișei, nu în câmpul Telefon"),
    "dup_pat": ("warn", "Există deja un pacient cu acest telefon — am deschis fișa lui. "
                        "Dacă este altă persoană (numărul familiei), adăugați-o cu alt "
                        "număr sau fără număr"),
    "bad_pat": ("err", "Lipsește numele pacientului"),
    # демо с сайта (core/demo.py): экран спрятан шлюзом, а не правом
    "demo_off": ("err", "În versiunea demonstrativă această secțiune nu este disponibilă"),
    "no_access": ("err", "Secțiunea este rezervată directorului clinicii. "
                         "Dacă aveți nevoie de acces, cereți-i să vă schimbe rolul "
                         "în Setări › Utilizatori"),
    # Права врача (22.10): в журнале — только свои визиты. Отказ командам к
    # чужому визиту и записи к чужому врачу (403) и подсказка-состояние
    # учётки без врача (едет в модели экранов через `msg_view`).
    "other_doctor": ("err", "Programarea este la alt medic — în registru vedeți și "
                            "modificați doar programările dvs."),
    "no_doctor_link": ("warn", "Contul nu e legat de un medic, de aceea registrul este "
                               "gol. Directorul alege medicul în Setări › Utilizatori."),
    "ok_user": ("ok", "Utilizator salvat"),
    # ⚠️ без диапазона числами: минимум зависит от сети (`auth.pin_min`), а
    # словарь — импорт; числа показывает поле формы
    "bad_user": ("err", "Date invalide — verificați numele, rolul și parola "
                        "(numărul de cifre cerut e scris în câmp)"),
    "dup_user": ("err", "Parola este deja folosită de alt utilizator — alegeți alta. "
                        "Intrarea se face doar cu parola, deci ea trebuie să fie unică"),
    "last_dir": ("err", "Trebuie să rămână cel puțin un director — altfel nimeni nu mai "
                        "poate deschide Setările și nu are cine să dea drepturi înapoi"),
    "self_user": ("err", "Nu vă puteți șterge propriul cont — cereți altui director"),
    "uid_taken": ("err", "Există deja un utilizator cu acest id — contul lui a rămas neschimbat"),
    "ok_doc": ("ok", "Document încărcat — rămâne local, pe acest calculator"),
    "bad_doc": ("err", "Fișier gol sau prea mare (max 25 MB)"),
    # сканер (01.10): лист со сканера сразу в фишу, PDF-ом
    "ok_scan": ("ok", "Document scanat și salvat în fișă"),
    "scan_none": ("err", "Niciun scaner nu a fost găsit — verificați că este pornit și conectat la acest calculator"),
    "scan_err": ("err", "Scanarea nu a reușit — verificați foaia și scanerul, apoi încercați din nou"),
    "scan_empty": ("warn", "Nicio pagină scanată — apăsați mai întâi „Scanează”"),
    "ok_med": ("ok", "Datele medicului au fost salvate"),
    "bad_med": ("err", "Date invalide — verificați câmpurile medicului"),
    "new_med": ("ok", "Medic adăugat — completați fișa lui"),
    "dup_med": ("err", "Există deja un medic cu acest nume — numele trebuie să fie unic"),
    "ok_photo": ("ok", "Fotografia a fost salvată — rămâne local, pe acest calculator"),
    "bad_photo": ("err", "Doar JPEG / PNG / WebP, până la 5 MB"),
    "ok_svc_med": ("ok", "Serviciile medicului au fost actualizate"),
    "svc_empty": ("err", "Fiecare serviciu trebuie să rămână cu cel puțin un medic "
                         "ACTIV — altfel nu mai poate fi ales la programare. Bifați alt medic "
                         "(sau readuceți unul din concediu) înainte de a-l scoate pe acesta"),
    # ⚠️ Папка НЕ «программы»: пишем мы в папку данных, и она с переезда в
    # `Program Files` другая. Совет проверить права не на той папке — это
    # директор, который час чинит исправное место, пока clinic.json не
    # сохраняется. Путь показывает «Stare sistem», туда и отсылаем.
    "save_err": ("err", "Nu am putut scrie fișierul clinicii (clinic.json) — datele NU "
                        "au fost salvate. Verificați spațiul pe disc și drepturile la "
                        "folderul cu date (Setări › Stare sistem); detalii în "
                        "data\\dentpilot.log"),
    "arch_busy": ("err", "Medicul are programări viitoare — mutați-le la alt medic sau "
                         "alegeți «în concediu» în loc de arhivare"),
    "last_med": ("err", "Trebuie să rămână cel puțin un medic activ"),
    "ok_anam": ("ok", "Anamneza a fost salvată"),
    "bad_anam": ("err", "Anamneza nu a fost salvată — bifați ce se potrivește "
                        "sau completați cel puțin un câmp"),
    "bad_anam_none": ("err", "Anamneza nu a fost salvată — «Niciuna dintre afecțiunile "
                             "de mai sus» nu se bifează împreună cu o afecțiune din listă"),
    # прикус — графа «Ocluzia» 043/e (26.10)
    "ok_occl": ("ok", "Ocluzia a fost salvată"),
    "bad_occl": ("err", "Ocluzia nu a fost salvată — completați cel puțin un câmp"),
    "bad_occl_val": ("err", "Ocluzia nu a fost salvată — verificați câmpul marcat "
                            "(clasa Angle din listă, milimetrii ca număr: 3, 2,5, -1)"),
    "ok_visit": ("ok", "Consultația a fost salvată"),
    "bad_visit": ("err", "Consultația nu a fost salvată — completați cel puțin "
                         "un câmp"),
    "bad_vst": ("err", "Vizita anulată sau neprezentată nu poate avea "
                       "consultație — schimbați mai întâi statusul vizitei"),
    # Экран раздвоения (P2). ⛔ Три остановки звучат ПО-РАЗНОМУ намеренно:
    # «PIN не ставили» и «файл повреждён» ведут человека в разные стороны,
    # и показать второе как первое — тот же тупик, что чинили в
    # восстановлении. ⚠️ Успех говорит, что данные ЕЩЁ НЕ перенесены:
    # «готово» без содержания оставило бы человека думать, что переезд
    # состоялся, — а Copy-only это следующий шаг, которого пока нет.
    "mig_ok": ("ok", "Fișa veche este confirmată. Datele NU au fost încă "
                     "mutate — transferul este pasul următor; până atunci "
                     "programul lucrează mai departe în fișa curentă"),
    "mig_kept": ("ok", "Alegerea este înregistrată: rămâneți cu fișa "
                       "curentă. Cealaltă fișă nu a fost ștearsă și nu a "
                       "fost modificată"),
    "mig_bad": ("err", "PIN greșit pentru fișa aleasă"),
    "mig_lock": ("err", "Prea multe încercări — așteptați înainte de a "
                        "reîncerca"),
    "mig_noauth": ("err", "Fișa aleasă nu are PIN — nu avem cu ce confirma "
                          "că vă aparține, deci transferul nu începe"),
    "mig_broken": ("err", "Fișierul de acces al fișei alese este deteriorat "
                          "și nu poate fi citit — transferul nu începe"),
    "mig_nousers": ("err", "În fișa aleasă nu există niciun cont — nu avem "
                           "cu ce confirma, deci transferul nu începe"),
    # lan-guard (02.11): сеть клиники
    # Вход из сети — только с выбором человека: без него PIN сверялся бы со
    # ВСЕМИ учётками (`auth.verify_pin`, `entry.try_login`)
    "login_pick": ("warn", "Alegeți-vă numele din listă și introduceți PIN-ul"),
    # Опасное действие директора из сети (`auth.LOCAL_ONLY`): отказ маршрута и
    # подсказка-состояние экрана вместо его кнопок (`msg_view`)
    "only_local": ("warn", "Această acțiune se face doar pe calculatorul principal "
                          "al clinicii — cel pe care este instalat programul"),
    # ---- заказы лаунчеру (02.11, `core/orders.py`) ----
    # Баннер директору и летопись после старта: что лаунчер исполнил или
    # отверг. Строку дополняет `orders.event_text` (что, почему, когда);
    # потолок летописи 200 знаков. Говорят, ЧТО случилось, а не про взлом:
    # штатное восстановление — не тревога.
    "ord_decrypted": ("warn", "Criptarea evidenței a fost oprită la pornirea programului"),
    "ord_restored": ("warn", "Baza de date a fost restaurată din copie la pornirea programului"),
    "ord_rejected": ("err", "O comandă nesemnată de acest cont Windows a fost respinsă "
                            "la pornire"),
    "ord_repeat": ("err", "Nimic nu a fost șters. Dacă ați cerut-o dvs., repetați "
                          "comanda din Setări"),
}


def msg_banner(msg: str) -> str:
    """Ответ на действие (?msg=… из 303) — плавающей плашкой поверх окна.

    Жалоба клиники (08-14): форма записи стоит ВНИЗУ страницы, редирект
    открывает её заново с нулевой прокруткой, и баннер в потоке оставался за
    кадром — регистратура прочла «ничего не произошло» там, где журнал ответил
    «интервал занят». Плашка позиционируется фиксированно (panel.css,
    .toastbox), поэтому видна с любой прокрутки. Разметку кладёт в модель
    оболочки `shell_model` (`frame.msg`); крестик, автозакрытие успеха и
    уборку msg из адреса делает React-оболочка.

    ⭐ Единственное место, где код из MSG_BANNER становится разметкой (держит
    test_structure): модуль, собравший баннер сам, вернул бы сообщение в поток
    — и на коротких страницах разработчика это невидимо. Баннеры-СОСТОЯНИЯ
    («Zi liberă», шаблонные данные, сигнализация auth.json) остаются в потоке
    намеренно: они описывают страницу, а не отвечают на действие, и висеть
    поверх расписания весь день им нельзя.
    """
    if msg not in MSG_BANNER:
        return ""
    cls, text = MSG_BANNER[msg]
    # err — role=alert: экранный диктор объявляет отказ сразу, остальное — status
    role = "alert" if cls == "err" else "status"
    return (f"<div class='toastbox' id='dp_toast' data-kind='{cls}' role='{role}'>"
            f"<div class='banner {cls}'>{text}"
            f"<button class='t-x' type='button' aria-label='Închide'>"
            f"{_ic('close')}</button></div></div>")


def msg_state(msg: str) -> str:
    """Ответ на действие СТРОКОЙ СОСТОЯНИЯ — для страницы со своей вёрсткой
    (`standalone()`: раздвоение картотеки, шаг 6 снятия старого интерфейса),
    где нет стилей плавающей плашки (panel.css).
    Вид `.state.ok/.warn/.err` страница описывает в своём `<style>`.

    ⭐ Тот же словарь и то же место, что у `msg_banner` и `msg_json`: ответ на
    действие строит только layout (держит test_structure). Неизвестный код
    молчит, а не печатает себя."""
    if msg not in MSG_BANNER:
        return ""
    tone, text = MSG_BANNER[msg]
    role = "alert" if tone == "err" else "status"
    return f"<div class='state {tone}' role='{role}'>{html.escape(text)}</div>"


def msg_text(code: str) -> str:
    """Слова кода — для страницы СО СВОЕЙ вёрсткой, которая печатает их в свой
    узел (экран входа: `<div class='err'>`). Тот же словарь, что у трёх
    конвертов выше: страница, повторившая «PIN greșit» литералом, стала бы
    вторым владельцем слова — ровно то, чего держится `test_structure`.
    Неизвестный код — пустая строка, как у `msg_json`."""
    return MSG_BANNER.get(code, ("", ""))[1]


def msg_view(code: str) -> dict:
    """Код словами и тоном — подсказка-СОСТОЯНИЕ внутри модели экрана
    (`notice` дня, панели, недели и кресла: «contul nu e legat de un medic»,
    22.10). Тот же словарь, что у `msg_json` и `msg_text`: клиент печатает
    `text` и красит по `tone`, переводить код сам не имеет права."""
    tone, text = MSG_BANNER.get(code, ("", ""))
    return {"code": code, "tone": tone, "text": text}


def msg_json(ok: bool, code: str = "", *, data=None, field: str = "",
             status: int = 200, text: str = "") -> JSONResponse:
    """Конверт ответа JSON API (`/api/*`, DentPilot 2.0).

    Тот же код из MSG_BANNER, что уезжает страницам в `?msg=`, — и ЗДЕСЬ же он
    становится текстом для человека: клиент показывает `text` и красит по
    `tone`, а переводить код сам не имеет права (второй словарь = один статус
    тремя словами, это уже случалось дважды). `code` остаётся для проверок и
    лога, `field` называет поле формы при 422.

    ⚠️ Код, которого в словаре нет, уезжает с ПУСТЫМ текстом, а не с самим
    кодом: иначе на экране появилось бы «bad_set». Клиент на пустой текст
    показывает свою общую фразу про недоступный движок.
    """
    # `text` — слова ДРУГОГО словаря, не второй перевод кода: отказ сервера
    # лицензий (cloud sms.CODES) приходит по-румынски, и переписывать его
    # здесь значило бы завести второй словарь тех же состояний (S6)
    tone, word = MSG_BANNER.get(code, ("ok" if ok else "err", ""))
    body: dict = {"ok": ok, "code": code, "tone": tone, "text": text or word}
    if field:
        body["field"] = field
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=status)
