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
from app import config, license, mail, payments  # noqa: E402

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
    res.ok("договор и политика: у поставщика нет доступа к данным пациентов",
           "nu are acces la datele pacienților" in privacy and "nu are\n  acces la datele pacienților" in terms
           or "nu are acces la datele pacienților" in " ".join(terms.split()))
    res.ok("договор: поставщик не persoană împuternicită", "persoană\n    împuternicită" in terms
           or "persoană împuternicită" in " ".join(terms.split()))
    res.ok("страницы в стиле сайта: шрифт, шапка, футер, перекрёстные ссылки",
           all(x in terms for x in ("@font-face", 'class="top"', "<footer", "privacy.html"))
           and all(x in privacy for x in ("@font-face", 'class="top"', "<footer", "termeni.html")))
    res.ok("телефон и почта поддержки те же, что в письмах",
           config.SUPPORT_PHONE in terms and config.SUPPORT_EMAIL in terms)
    # IDNO вписан 26.09 (был плейсхолдер): один и тот же номер на обеих страницах.
    idnos = set(re.findall(r"IDNO (\d{13})", terms)) | set(re.findall(r"IDNO (\d{13})", privacy))
    res.ok("IDNO — один и тот же номер на обеих страницах, плейсхолдера нет",
           len(idnos) == 1 and terms.count("IDNO ") >= 2 and "[____]" not in terms + privacy, str(idnos))
    res.ok("contract.md: суть, таблица «обещание ↔ программа», вопросы юристу",
           all(h in contract for h in ("## Суть по пунктам", "## Обещание ↔ программа", "## Вопросы юристу"))
           and "docs/site/termeni.html" in contract)
    heads = re.findall(r"<h2>(\d+)\. ", terms)
    res.check("15 пунктов по порядку", heads, [str(i) for i in range(1, 16)])
    res.ok("contract.md описывает каждый пункт", all(f"| {i} |" in contract for i in range(1, 16)))
