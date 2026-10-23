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
from app import auth, config, license, mail, payments, sms, sms_rule, trial  # noqa: E402

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
