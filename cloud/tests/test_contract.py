"""Договор и сайт (L11): страницы docs/site/ говорят то же, что сервер и письма.

Числа и фразы берутся из кода сервера, не из теста: поменяется льгота или
текст письма — страница обязана поменяться вместе с ними, и заметит это
прогон, а не клиника. Половина про программу (баннер, NO_FILE_GRACE) —
в tests/test_structure.py движка.
"""
import re
import sys
from urllib.parse import urlsplit

from harness import CLOUD, ROOT, Result

sys.path.insert(0, str(CLOUD))
from app import auth, config, license, mail, payments, receipts, sms, sms_rule, trial  # noqa: E402

SITE = ROOT / "docs" / "site"


def suite(res: Result) -> None:
    terms = (SITE / "termeni.html").read_text(encoding="utf-8")
    privacy = (SITE / "privacy.html").read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "dentpilot-2" / "contract.md").read_text(encoding="utf-8")

    def num(pattern: str):
        m = re.search(pattern, terms)
        return int(m.group(1)) if m else None

    res.check("пробный период — TRIAL_DAYS", num(r"perioadă de probă de (\d+) (?:de )?zile"), license.TRIAL_DAYS)
    res.check("после пробного — TRIAL_GRACE_DAYS", num(r"încă (\d+) zile \(perioada pentru abonare\)"),
              license.TRIAL_GRACE_DAYS)
    res.check("после абонемента — GRACE_DAYS", num(r"încă (\d+)\s+zile \(perioada de plată\)"), license.GRACE_DAYS)
    res.ok("режим чтения теми же словами, что письма", " ".join(mail._READONLY.split()) in " ".join(terms.split()),
           mail._READONLY)
    res.ok("правило продления: от большей из дат", "oricare este mai târzie" in terms)
    # Сроки — месяц или год, как в карточке цены сайта (26.09). Фраза договора
    # привязана к ряду MONTHS: вернут 3 и 6 месяцев — прогон потребует слов.
    res.ok("сроки абонемента — ряд MONTHS: месяц или год",
           payments.MONTHS == (1, 12) and "pe o lună sau pe un an (12 luni)" in " ".join(terms.split()),
           str(payments.MONTHS))
    res.ok("нота за 14 дней и уведомление за 3 — как окна задачи",
           "Cu 14 zile înainte de expirare" in terms and "cu 3 zile înainte" in terms)
    host = urlsplit(config.BASE_URL).hostname
    res.ok("политика: сервер лицензий назван адресом из DP_BASE_URL", host in privacy, host)
    res.ok("политика: данные учётной записи — состав, срок, без данных пациентов",
           "Datele contului clinicii" in privacy and "IDNO" in privacy and "durata contractului" in privacy
           and "nicio informație despre pacienți" in privacy)
    # С § 16 (SMS, 16.10) политика и декларация говорят «fișele»: номер и время
    # визита у клиники с пакетом через сервер проходят, карты — нет
    res.ok("договор и политика: у поставщика нет доступа к данным (политика — к картам) пациентов",
           "nu are acces la fișele pacienților" in privacy
           and "nu are acces la datele pacienților" in " ".join(terms.split()))
    res.ok("договор: поставщик не persoană împuternicită", "persoană\n    împuternicită" in terms
           or "persoană împuternicită" in " ".join(terms.split()))
    res.ok("страницы в стиле сайта: шрифт, шапка, футер, перекрёстные ссылки",
           all(x in terms for x in ("@font-face", 'class="top"', "<footer", "privacy.html"))
           and all(x in privacy for x in ("@font-face", 'class="top"', "<footer", "termeni.html")))
    res.ok("телефон и почта поддержки те же, что в письмах",
           config.SUPPORT_PHONE in terms and config.SUPPORT_EMAIL in terms)
    # Текст о законе 195 перед кнопкой «Descarcă» (L15), обе версии: контакты
    # и форма пробного — те же, что у сервера. Надписи программы на нём
    # сторожит tests/test_structure.py движка.
    for name in ("descarca.html", "descarca-ru.html"):
        page = (SITE / name).read_text(encoding="utf-8")
        res.ok(f"{name}: телефон, почта и форма пробного — как у сервера",
               config.SUPPORT_PHONE in page and config.SUPPORT_EMAIL in page
               and f"https://{host}/proba" in page)
        res.ok(f"{name}: в стиле сайта, со ссылками на условия и политику",
               all(x in page for x in ("@font-face", 'class="top"', "<footer", "termeni.html", "privacy.html")))
    # Декларация поставщика (закон 195): её подписанный PDF едет в каждое письмо о
    # лицензии (DP_DECLARATION). Говорит ровно то, что п. 9 условий и § 5 политики:
    # подписанная бумага, разошедшаяся с договором, хуже, чем никакой.
    decl = " ".join((SITE / "declaratie-195.html").read_text(encoding="utf-8").split())
    flat_terms, flat_privacy = " ".join(terms.split()), " ".join(privacy.split())
    res.ok("декларация: нет доступа к картам пациентов, как § 4 политики; не persoană împuternicită — как п. 9 условий",
           "nu are acces la fișele pacienților" in decl and "nu are acces la fișele pacienților" in flat_privacy
           and "persoană împuternicită" in decl and "persoană împuternicită" in flat_terms)
    lic_file = "fișierul de licență conține doar denumirea clinicii, idno, tipul și termenul abonamentului"
    res.ok("декларация: состав файла лицензии — словами политики § 5",
           lic_file in decl.lower() and lic_file in flat_privacy.lower())
    res.ok("декларация: предупреждение об изменениях за 30 дней — как п. 13 условий",
           "cu cel puțin 30 de zile înainte" in decl and "cu cel puțin 30 de zile înainte" in flat_terms)
    res.ok("декларация: IDNO, телефон и почта — те же, что в условиях",
           set(re.findall(r"IDNO (\d{13})", decl)) == set(re.findall(r"IDNO (\d{13})", terms))
           and config.SUPPORT_PHONE in decl and config.SUPPORT_EMAIL in decl)
    # Код на e-mail (новый компьютер той же клиники): срок в политике и в письме — CODE_TTL
    minutes = int(trial.CODE_TTL.total_seconds() // 60)
    res.ok("политика § 5 и декларация: код активации — со сроком, как у сервера",
           "codul de activare" in flat_privacy.lower() and f"valabil {minutes} minute" in flat_privacy
           and "codul primit pe e-mailul clinicii" in decl
           and f"valabil {minutes} minute" in mail.activation_code("C", "123456", minutes)[1])
    res.ok("условия п. 7: другой компьютер — кодом на e-mail (файла у клиники нет с 02.10)",
           "codul de activare trimis pe e-mailul clinicii" in flat_terms)
    # письма пробной клинике ведут в кабинет (02.10): тот же адрес, что на страницах
    res.ok("письмо «как продолжить» без ноты ведёт в кабинет и называет ноту",
           mail.CONT_URL in mail.how_to_pay(None) and "nota de plată" in mail.how_to_pay(None))
    res.ok("декларация: письмо называет её тем же именем, что страница",
           "Declarația furnizorului" in decl and "Declarația furnizorului" in mail.DECLARATION_NOTE)
    # IDNO вписан 26.09 (был плейсхолдер): один и тот же номер на обеих страницах.
    idnos = set(re.findall(r"IDNO (\d{13})", terms)) | set(re.findall(r"IDNO (\d{13})", privacy))
    res.ok("IDNO — один и тот же номер на обеих страницах, плейсхолдера нет",
           len(idnos) == 1 and terms.count("IDNO ") >= 2 and "[____]" not in terms + privacy, str(idnos))
    res.ok("contract.md: суть, таблица «обещание ↔ программа», вопросы юристу",
           all(h in contract for h in ("## Суть по пунктам", "## Обещание ↔ программа", "## Вопросы юристу"))
           and "docs/site/termeni.html" in contract)
    heads = re.findall(r"<h2>(\d+)\. ", terms)
    res.check("16 пунктов по порядку", heads, [str(i) for i in range(1, 17)])
    res.ok("contract.md описывает каждый пункт", all(f"| {i} |" in contract for i in range(1, 17)))
    # Модуль SMS и пакеты SMS — § 16 (16.10, слово Олега «без юриста»; с 23.10 —
    # модуль входит в тариф с SMS, пакеты отдельно). Числа раздела — из
    # config и правила сегментов сервера, не из теста; поменяли константу —
    # прогон требует слов. Цен на страницах нет (Олег 16.10: «в Git про цены
    # писать не надо») — раздел отсылает к ноте.
    s16 = flat_terms.split("<h2>16. ", 1)[1] if "<h2>16. " in flat_terms else ""
    res.ok("§ 16 — Modulul SMS", s16.startswith("Modulul SMS"), s16[:60])
    res.ok("§ 16: сегмент — как sms_rule.SINGLE (латиница / кириллица)",
           f"până la {sms_rule.SINGLE[sms_rule.GSM7]} de caractere latine" in s16
           and f"până la {sms_rule.SINGLE[sms_rule.UCS2]} de caractere chirilice" in s16)
    res.ok("§ 16: остаток не сгорает — SMS_PACK_DAYS = 0",
           config.SMS_PACK_DAYS == 0 and "SMS-urile rămase nu expiră" in s16, str(config.SMS_PACK_DAYS))
    res.ok("§ 16: пробному — SMS_TRIAL_UNITS бесплатно, один раз",
           config.SMS_TRIAL and f"o singură dată, {config.SMS_TRIAL_UNITS} de SMS gratuit" in s16)
    res.ok("§ 16: письмо об остатке — на пороге SMS_LOW", f"rămân {config.SMS_LOW} de SMS" in s16)
    quiet_from, quiet_to = sms.quiet_window()
    res.ok("§ 16: тихие часы — quiet_window сервера",
           f"înainte de ora {quiet_to:02d}:00 sau după ora {quiet_from:02d}:00" in s16,
           f"{quiet_from}-{quiet_to}")
    res.ok("§ 16: до одобрения — общее имя SMS_COMMON; своё — годом (SMS_NAME_DAYS)",
           config.SMS_COMMON_OK and f"„{config.SMS_COMMON}”" in s16
           and config.SMS_NAME_DAYS == 365 and "se plătește pe un an" in s16)
    res.ok("§ 16: в режиме чтения не уходят — SMS_READONLY",
           not config.SMS_READONLY and "În regim de citire (secțiunea 6) memento-urile nu se trimit" in s16)
    keep = "rămân doar identificatorul mesajului, numărul de segmente și starea livrării"
    res.ok("§ 16 и декларация: на сервере остаются id, сегменты и статус — одними словами",
           keep in s16 and keep in decl)
    res.ok("§ 16, политика и декларация называют субобработчика одинаково",
           all("Rock Soft S.R.L. (SMS.MD" in x for x in (s16, flat_privacy, decl)))
    res.ok("§ 16: цены нет — отсылка к ноте",
           s16.count("prețul indicat în nota de plată") == 2
           and not re.search(r"\d\s*(?:lei|MDL|bani)\b", s16, re.I))
    # Кабинет клиники (шаг 3, 01.10): политика называет вход Google и оба cookie
    # со сроками из auth.py; страницы скачивания ведут на /descarca и /cont сервера.
    res.ok("политика § 5: суточная проверка называет версию, канал, Windows и идентификатор компьютера (флот, 02.10)",
           all(x in flat_privacy for x in ("versiunea programului", "canalul de actualizare",
                                           "identificator tehnic al calculatorului", "fără date ale pacienților")))
    # Декларация — подпись Олега под теми же фактами: суточная проверка перечисляет
    # то же, что § 5, иначе подписанная бумага расходится с политикой (02.10: флот
    # попал в политику, а в декларацию — нет, и PDF чуть не ушёл на подпись устаревшим).
    res.ok("декларация п. 3: суточная проверка — теми же словами, что политика § 5 (флот)",
           all(x in decl for x in ("versiunea programului", "canalul de actualizare",
                                   "identificator tehnic al calculatorului", "fără date ale pacienților")))
    # вход кодом на e-mail (02.10): политика называет его рядом с Google, срок кода — тот же CODE_TTL
    res.ok("политика § 5: вход в кабинет — Google или код на e-mail, срок кода как у сервера",
           "cod de 6 cifre" in flat_privacy and "cont Google" in flat_privacy
           and f"valabil {minutes} minute" in flat_privacy)
    res.ok("политика § 5: кабинет — вход Google, cookie dp_oauth и dp_cont со сроками auth.py",
           "cont Google" in privacy and "dp_oauth" in privacy and "dp_cont" in privacy
           and f"({auth.OAUTH_TTL // 60} minute)" in flat_privacy and f"({auth.ACCOUNT_TTL // 86400} zile" in flat_privacy
           and f"https://{host}/cont" in privacy and f"{host}/descarca" in privacy
           and "Parola nu ajunge la noi" in flat_privacy)
    for name in ("descarca.html", "descarca-ru.html"):
        page = (SITE / name).read_text(encoding="utf-8")
        res.ok(f"{name}: кнопка ведёт на /descarca сервера, кабинет назван, плейсхолдера нет",
               f'href="https://{host}/descarca"' in page and f"https://{host}/cont" in page
               and "[LINK-DESCARCARE]" not in page)
    # Договор при активации (29.10): docs/dentpilot-2/contract/ — ОБЩИЕ документы,
    # подписанные поставщиком (как декларация): contract.html (Anexa 1 — условия
    # в версии акта акцепта, Anexa 2 — потоки, Anexa 3 — DPA). Сторож держит: ни
    # одного плейсхолдера (клиника — через акт), одна версия-дата у всех трёх,
    # числа и фразы — те же, что у условий и кода, DPA не называет медданные
    # предметом, субобработчик — как в § 16, политика и декларация называют
    # каждый канал, что код шлёт. Интервалы программы (6 ч, 10 мин) держит
    # tests/test_structure.py движка — у облака нет его исходников.
    folder = ROOT / "docs" / "dentpilot-2" / "contract"
    docs = {name: " ".join((folder / name).read_text(encoding="utf-8").split())
            if (folder / name).exists() else ""
            for name in ("contract.html", "dpa.html", "anexa-2.html")}
    c, dpa, flows = docs["contract.html"], docs["dpa.html"], docs["anexa-2.html"]
    readme = (folder / "README.md").read_text(encoding="utf-8") if (folder / "README.md").exists() else ""
    res.ok("договор: папка на месте — три документа и README", all(docs.values()) and bool(readme))
    res.ok("договор: документы общие — ни одного плейсхолдера {{…}}", not any("{{" in t for t in docs.values()))
    versions = {(m.group(1) if (m := re.search(r"Versiunea documentului: (\d\d\.\d\d\.\d{4})", t)) else None)
                for t in docs.values()}
    res.ok("договор: у всех трёх документов одна «Versiunea documentului»",
           len(versions) == 1 and None not in versions, str(versions))
    res.ok("договор и DPA: клиника — через акт акцепта, её подпись необязательна",
           "actul de acceptare" in c and "actul de acceptare" in dpa and "semnătura ei este opțională" in c)
    res.ok("договор: цена — из оферты на дату платежа, сумм нет",
           "oferta în vigoare la data plății" in c and not re.search(r"\d\s*(?:lei|MDL|bani)\b", c, re.I))
    res.ok("договор: пробный, оформление, период оплаты — числами сервера",
           f"perioadă de probă de {license.TRIAL_DAYS} de zile" in c
           and f"încă {license.TRIAL_GRACE_DAYS} zile (perioada pentru abonare)" in c
           and f"încă {license.GRACE_DAYS} zile (perioada de plată)" in c)
    res.ok("договор: режим чтения — словами условий § 6, «anumite funcții» нет",
           "regim de citire" in c and "nu se pierd și nu se blochează" in c
           and "nu se pierd și nu se blochează" in flat_terms and "anumite funcții" not in c)
    limits = ("ultimele 12 luni", "preaviz de 30 de zile", "fără penalități și fără preaviz")
    res.ok("договор: предел ответственности и расторжение — как § 11–12 условий",
           all(x in c for x in limits) and all(x in flat_terms for x in limits))
    res.ok("договор: документ оплаты — cont de plată «achitat», без factura fiscală, форма продавца как у receipts",
           "nu emite factură fiscală" in c and receipts.SELLER_FORM in c
           and "contul de plată cu mențiunea „achitat”" in c)
    res.ok("договор и DPA: удалённая помощь — Asistență rapidă, представитель присутствует, без копирования",
           all("Asistență rapidă" in t for t in (c, dpa)) and "prezent la calculator" in c
           and "nu copiază" in c and "nu copiază" in dpa)
    res.ok("договор: Anexa 1 — условия по адресу страницы; Anexa 2 и 3 названы",
           "https://dentpilot.md/termeni.html" in c and "Anexa 2" in c and "Anexa 3" in c)
    res.ok("DPA: предмет — номер и текст SMS и сеанс помощи, «două și numai două»; медданных в категориях нет",
           "numărul de telefon mobil" in dpa and "textul memento-ului" in dpa
           and "două și numai două" in dpa and "anamnez" not in dpa.lower())
    res.ok("DPA, § 16, политика, декларация: субобработчик, «что остаётся» и 3 luni — одними словами",
           "Rock Soft S.R.L. (SMS.MD" in dpa and keep in dpa and "3 luni" in dpa and "3 luni" in s16)
    res.ok("DPA: зарубежные провайдеры — только данные учётной записи, поставщик там оператор",
           all(x in dpa for x in ("Contabo GmbH", "GitHub, Inc.", "maib", "Gmail"))
           and "operator în nume propriu" in dpa)
    res.ok("Anexa 2: тихие часы SMS — quiet_window; SMS.MD 3 luni; maib и GitHub; что остаётся на ПК",
           f"între {quiet_to:02d}:00 și {quiet_from:02d}:00" in flows and "3 luni" in flows
           and "GitHub, Inc." in flows and "maib" in flows and "Rock Soft S.R.L. (SMS.MD)" in flows
           and "Ce rămâne pe calculatorul clinicii" in flows)
    res.ok("Anexa 2: код активации — со сроком сервера", f"expiră în {minutes} minute" in flows)
    # SMS из «Rechemări» (30.10): reamintirea controlului periodic названа в § 16,
    # DPA (предмет, субъекты, текст, инструкция — кнопка), Anexa 2, декларации и
    # политике одними словами; текст — только название и телефон клиники
    res.ok("§ 16, DPA, Anexa 2, декларация, политика: reamintirea controlului periodic из Rechemări — везде",
           all("reamintirea controlului periodic" in x and "Rechemări" in x for x in (s16, dpa, flows, decl, flat_privacy))
           and "butonului „SMS” din lista Rechemări" in s16 and "butonului „SMS” din lista Rechemări" in dpa
           and "doar denumirea și telefonul clinicii" in s16 and "doar denumirea și telefonul clinicii" in dpa)
    # автоматическая отправка по галочке (утро 30.10, В1 → В): названа в § 16, DPA (инструкция),
    # Anexa 2, декларации и политике; число в день — константа программы, в текстах его нет
    res.ok("§ 16, DPA, Anexa 2, декларация, политика: trimiterea automată по настройке клиники; числа в день в тексте нет",
           all("trimiterea automată" in x or "trimiterii automate" in x for x in (s16, dpa, flows, decl, flat_privacy))
           and "un număr limitat pe zi" in s16 and not re.search(r"cel mult \d+", s16))
    res.ok("политика § 5: обновления на GitHub, кнопки оплаты/кабинета, опрос SMS, maib, внутренние уведомления",
           all(x in flat_privacy for x in ("Verificarea actualizărilor", "GitHub, Inc.", "Deschide contul clinicii",
                                           "soldul de SMS", "maib", "notificările interne ale furnizorului")))
    res.ok("декларация п. 2–3: обновления на GitHub, кнопки, опрос SMS, удалённая помощь",
           all(x in decl for x in ("GitHub, Inc.", "Deschide contul clinicii", "soldului de SMS", "Asistență rapidă")))
    res.ok("README папки договора: три файла, условия, версия = дата, DP_CONTRACT",
           all(x in readme for x in ("contract.html", "dpa.html", "anexa-2.html", "termeni.html",
                                     "DP_CONTRACT", "Versiunea documentului")))
    # Условия 29.10 (terms-250): то, что договор уже обещал, названо и в них — договор
    # и акт в кабинете (§ 1), cont de plată без factura fiscală (§ 4), обновления на
    # сервере и GitHub (§ 8), техданные ПК в данных учётной записи (§ 9), Asistență
    # rapidă словами договора кл. 7 (§ 10), адрес поставщика как в договоре (§ 15),
    # счёт SMS и «что остаётся» (§ 16). Пересказа договора нет — отсылка в кабинет.
    addr = re.compile(r"MD-\d{4}, or\. [^,<]+, str\. [^,<]+? \d+")
    res.ok("условия § 1 и § 10: договор, акт и условия помощи — в кабинете клиники, раздел «Documente» как у акта",
           "secțiunea „Documente”" in flat_terms and "act de acceptare" in flat_terms
           and "contractul semnat de furnizor, în contul clinicii (clauza 7)" in flat_terms
           and "secțiunea «Documente»" in " ".join((CLOUD / "app" / "terms.py").read_text(encoding="utf-8").split()))
    res.ok("условия § 4: cont de plată «achitat», без factura fiscală и TVA — как договор 2.5",
           "nu emite factură fiscală" in flat_terms and "nu este plătitor de TVA" in flat_terms
           and "contul de plată cu mențiunea „achitat”" in flat_terms)
    res.ok("условия § 8: проверка на сервере поставщика, файлы с GitHub, Inc., IP, подпись файла",
           all(x in flat_terms for x in ("la pornire și apoi la fiecare", "GitHub (GitHub, Inc.)", "adresa IP a clinicii",
                                         "semnătura digitală a furnizorului")))
    res.ok("условия § 9.2: техданные ПК в данных учётной записи — словами политики (без данных пациентов)",
           all(x in flat_terms for x in ("datele tehnice ale calculatoarelor", "versiunea programului", "canalul de actualizare",
                                         "identificator tehnic al calculatorului", "fără date ale pacienților")))
    res.ok("условия § 10: Asistență rapidă — по просьбе, код вводит клиника, представитель присутствует, без копирования",
           all(x in flat_terms for x in ("Asistență rapidă", "codul sesiunii îl introduce clinica", "prezent la calculator",
                                         "nu copiază", "niciun mijloc de acces de la distanță")))
    res.ok("условия § 15 и договор: адрес поставщика один", bool(addr.search(flat_terms)) and bool(addr.search(c))
           and addr.search(flat_terms).group(0) == addr.search(c).group(0), repr((addr.search(flat_terms), addr.search(c))))
    res.ok("условия § 16: счёт SMS читается с сервера; идентификатор — amprentă без пациента и визита",
           "soldul de SMS al clinicii de pe serverul furnizorului" in s16 and "amprentă tehnică" in s16
           and "nu se pot afla pacientul, numărul de telefon sau vizita" in s16)
