"""Письма клинике: SMTP с STARTTLS или, без DP_SMTP_HOST, сухой прогон в папку.

Сухой прогон — не заглушка «для тестов», а честный режим: письмо целиком
ложится .eml-файлом в DP_MAIL_OUTBOX, и его можно открыть почтовой программой.
Без хоста и без папки отправка отказывает словами, а не молча.

Тексты — румынские, теми же словами, что баннеры программы (layout.py):
«regim de citire», «datele se pot consulta, tipări și exporta». Русская
версия — когда появится клиника, которая попросит.
"""
from __future__ import annotations

import logging
import pathlib
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage

from . import config, tiers

log = logging.getLogger("cloud.mail")

# Тип вложения — по расширению имени: файл лицензии и PDF декларации
_MIME = {".json": ("application", "json"), ".pdf": ("application", "pdf")}


def send(to: str, subject: str, body: str, *attachments: tuple[str, bytes]) -> str:
    """Возвращает 'smtp' или путь файла в outbox. Бросает RuntimeError, когда некуда."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.MAIL_FROM, to, subject
    msg.set_content(body)
    for name, data in attachments:
        maintype, subtype = _MIME.get(pathlib.PurePath(name).suffix.lower(),
                                      ("application", "octet-stream"))
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    if config.SMTP_HOST:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
            s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(msg)
        return "smtp"
    if config.MAIL_OUTBOX:
        out = pathlib.Path(config.MAIL_OUTBOX)
        out.mkdir(parents=True, exist_ok=True)
        p = out / f"{int(time.time() * 1000)}-{to.replace('@', '_at_')}.eml"
        p.write_bytes(bytes(msg))
        return str(p)
    raise RuntimeError("ни DP_SMTP_HOST, ни DP_MAIL_OUTBOX: письмо отправить некуда")


FOOTER = f"Întrebări: {config.SUPPORT_EMAIL} · {config.SUPPORT_PHONE}\n\nDentPilot"


def luni(months: int) -> str:
    return f"{months} {'lună' if months == 1 else 'luni'}"


def ro_date(s: str | None) -> str:
    """ISO-дата сервера → как пишут в Молдове: 29.12.2026 (30.10: письмо о лицензии писало
    «până la 2026-12-29» рядом с датами ноты 29.12.2026). Один формат на письма и кабинет."""
    if not s or len(s) < 10:
        return "—"
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]}"


def zile(n: int) -> str:
    """«3 zile», но «30 de zile»: от двадцати румынский ставит «de» между числом
    и словом (и снова после ста — 120, но не 115). Пробный месяц (30) это и
    выявил: «pentru 30 zile» на странице /proba читалось бы с ошибкой."""
    if n == 1:
        return "1 zi"
    return f"{n} de zile" if n >= 20 and (n % 100 == 0 or n % 100 >= 20) else f"{n} zile"


def bank_lines(reference: str, amount: int) -> str:
    """Реквизиты перевода строками. Требует заполненных DP_BANK_* — иначе RuntimeError."""
    b = config.BANK
    if not (b["iban"] and b["beneficiary"]):
        raise RuntimeError("DP_BANK_IBAN / DP_BANK_BENEFICIARY пусты: реквизитов для письма нет")
    return (f"  Suma: {amount} MDL\n"
            f"  Beneficiar: {b['beneficiary']}\n"
            f"  IBAN: {b['iban']}\n"
            + (f"  Banca: {b['bank']}\n" if b['bank'] else "")
            + (f"  Cod fiscal: {b['code']}\n" if b['code'] else "")
            + f"  Destinația plății: {reference}\n")


_REFERENCE_NOTE = ("Important: indicați neapărat referința {reference} în destinația plății — după ea "
                   "recunoaștem plata dumneavoastră. După confirmare termenul se prelungește automat în "
                   "program; primiți confirmarea pe e-mail.")
# Карта — на НАШЕЙ странице оплаты (23.10): ссылка maib живёт минуты (maib.PAY_TTL) и
# рождается по кнопке после галочки условий (требование maib), поэтому в письме её нет.
# Значков и названий Apple Pay / Google Pay нет, пока maib их не включит (Олег 23.10).
CARD_NOTE = "Plata cu cardul — pe pagina de plată DentPilot (bifați Termenii și condițiile, apoi „Plătește cu cardul”):"


def card_lines(pay_url: str, amount: int) -> str:
    """Карта (L12): `pay_url` — страница оплаты клиники (paylink.for_mail), не ссылка maib.
    После оплаты картой программа продлевается сама."""
    return (f"{CARD_NOTE}\n  {pay_url}\n  Suma: {amount} MDL\n"
            f"  După plata cu cardul nu trebuie să faceți nimic: noul termen ajunge singur în program "
            f"în câteva minute, iar confirmarea — pe e-mail.\n")


def ways_to_pay(reference: str, amount: int, pay_url: str | None) -> str:
    """Способы оплаты по порядку: карта (если есть страница оплаты с картой), перевод (если
    есть реквизиты). Ни того ни другого — RuntimeError, как у bank_lines."""
    parts = []
    if pay_url:
        parts.append(card_lines(pay_url, amount))
    try:
        lines = bank_lines(reference, amount)
        parts.append(("Sau prin transfer bancar:\n" if pay_url else "") + lines
                     + "\n" + _REFERENCE_NOTE.format(reference=reference))
    except RuntimeError:
        if not parts:
            raise
    return "\n".join(parts)


def tier_line(tier: str | None) -> str:
    """«DentPilot Plus (cu modulul SMS)» — вариант ноты словами условий § 4.1."""
    t = tier if tier in tiers.TIERS else tiers.PLUS
    return f"{tiers.NAME[t]} ({tiers.WHAT[t]})"


def change_note(page: str | None = None) -> str:
    """Как сменить вариант или срок до оплаты (условия § 4.2: «varianta o alege clinica la
    fiecare plată»): на странице оплаты из письма (`page`), в программе или в кабинете;
    нота там заменяется, а не плодится вторая."""
    where = f"pe pagina de plată, {page}, " if page else ""
    return (f"Varianta (DentPilot Basic, fără modulul SMS, sau DentPilot Plus, cu modulul SMS) și termenul "
            f"le puteți schimba până la plată: {where}din program, butonul „Plătește acum” (Setări › Licența), "
            f"sau din contul clinicii, {CONT_URL} — nota de plată se înlocuiește cu una nouă.")


def payment_letter(clinic: str, reference: str, amount: int, months: int,
                   pay_url: str | None = None, tier: str | None = None,
                   page: str | None = None) -> tuple[str, str]:
    """Письмо с нотой: вариант и срок, карта на странице оплаты (`pay_url` — она же, когда
    карта включена), реквизиты перевода — что настроено; `page` — страница для смены варианта."""
    ways = ways_to_pay(reference, amount, pay_url)
    subject = f"DentPilot: nota de plată {reference} pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"Pentru abonamentul {tier_line(tier)} — {clinic}, {luni(months)} — "
            f"vă rugăm să achitați {amount} MDL:\n\n"
            f"{ways}\n\n"
            f"{change_note(page)}\n\n"
            f"{FOOTER}")
    return subject, body


def sms_pack_note_letter(clinic: str, reference: str, amount: int, units: int,
                         pay_url: str | None = None) -> tuple[str, str]:
    """Нота за пакет SMS (S3): та же форма, что у абонемента, другой предмет."""
    ways = ways_to_pay(reference, amount, pay_url)
    subject = f"DentPilot: nota de plată {reference} — pachet {units} SMS pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"Pentru pachetul de {units} SMS (DentPilot, {clinic}) vă rugăm să achitați {amount} MDL:\n\n"
            f"{ways}\n\n"
            f"După confirmarea plății pachetul se activează automat și soldul apare în program, "
            f"în Setări › SMS.\n\n{FOOTER}")
    return subject, body


def sms_name_note_letter(clinic: str, reference: str, amount: int, name: str,
                         pay_url: str | None = None) -> tuple[str, str]:
    """Нота за год своего имени отправителя (Олег 16.10: платно, годом)."""
    ways = ways_to_pay(reference, amount, pay_url)
    subject = f"DentPilot: nota de plată {reference} — numele de expeditor «{name}» pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"Pentru numele propriu de expeditor «{name}» (un an, DentPilot, {clinic}) vă rugăm să "
            f"achitați {amount} MDL:\n\n{ways}\n\n"
            f"Anul se numără din ziua în care operatorii aprobă numele; până atunci SMS-urile pleacă de la "
            f"«DentPilot».\n\n{FOOTER}")
    return subject, body


def sms_name_letter(clinic: str, name: str, until: str | None, reference: str) -> tuple[str, str]:
    """Клинике: год имени оплачен — с датой, если имя уже одобрено, иначе «от одобрения»."""
    subject = f"DentPilot: numele de expeditor «{name}» este plătit ({clinic})"
    when = (f"SMS-urile pleacă de la «{name}» până la {ro_date(until)}." if until else
            f"Anul începe din ziua în care operatorii aprobă numele «{name}» (1–2 zile lucrătoare după "
            f"depunerea cererii); până atunci SMS-urile pleacă de la «DentPilot».")
    body = (f"Bună ziua,\n\n"
            f"Plata pentru numele de expeditor «{name}» (nota {reference}) a fost confirmată. {when}\n\n{FOOTER}")
    return subject, body


def sms_pack_letter(clinic: str, units: int, balance: int, reference: str) -> tuple[str, str]:
    """Клинике: пакет начислен (после подтверждения платежа kind=sms)."""
    subject = f"DentPilot: pachetul de {units} SMS a fost activat ({clinic})"
    body = (f"Bună ziua,\n\n"
            f"Pachetul de {units} SMS pentru {clinic} a fost activat (nota {reference}): SMS-urile au intrat "
            f"în contul clinicii. "
            f"Soldul actual: {balance} SMS. Programul îl preia singur — îl vedeți în Setări › SMS.\n\n"
            f"{FOOTER}")
    return subject, body


def sms_low_letter(clinic: str, balance: int) -> tuple[str, str]:
    """Клинике: остаток SMS на пороге (раз за пакет, jobs)."""
    subject = f"DentPilot: au rămas {balance} SMS ({clinic})"
    body = (f"Bună ziua,\n\n"
            f"Clinica {clinic} mai are {balance} SMS. Când soldul ajunge la zero, "
            f"reminderele SMS nu se mai trimit. Un pachet nou comandați din program, Setări › SMS "
            f"(nota de plată vine pe e-mail), sau scrieți-ne.\n\n{FOOTER}")
    return subject, body


def group_letter(payer: str, reference: str, amount: int, lines: list, pay_url: str | None = None,
                 page: str | None = None) -> tuple[str, str]:
    """Письмо с общей нотой кабинета (26.10): строки — клиника, вариант, срок, сумма; одна сумма и
    один reference; реквизиты и карта — как у обычной ноты. Идёт плательщику (первой клинике)."""
    ways = ways_to_pay(reference, amount, pay_url)
    rows = "\n".join(f"  · {ln['name']} — {tier_line(ln['tier'])}, {luni(int(ln['months']))}: {ln['amount']} MDL"
                     for ln in lines)
    subject = f"DentPilot: nota comună de plată {reference} ({len(lines)} clinici)"
    body = (f"Bună ziua,\n\n"
            f"Nota comună de plată pentru abonamentele clinicilor din contul {payer}:\n\n{rows}\n\n"
            f"Total de achitat: {amount} MDL\n\n"
            f"{ways}\n\n"
            f"După confirmarea plății fiecare clinică primește termenul ei, iar programul fiecăreia îl preia "
            f"singur. Altă alegere sau anularea notei — din contul clinicii, {CONT_URL}.\n\n"
            f"{FOOTER}")
    return subject, body


def offer_line() -> str:
    """Варианты, которые продаются, с ценой месяца — для пробной клиники (прайс из cloud.env)."""
    sold = [f"{tiers.NAME[t]}, {tiers.WHAT[t]} — {tiers.list_price(t)} MDL pe lună"
            for t in tiers.TIERS if tiers.list_price(t) > 0]
    return "; ".join(sold) if sold else "prețul din oferta publicată pe dentpilot.md"


def how_to_pay(pay: dict | None) -> str:
    """Абзац «как продолжить»: карта на странице оплаты (`url`) и/или реквизиты с reference
    (абонемент, в варианте ноты) или как оформить абонемент (пробный — оба варианта
    с ценой). Без ссылки и без DP_BANK_* — честная фраза, что нота придёт отдельно."""
    if pay is None:
        # пробной клинике: сперва программа и кабинет (сама выбирает вариант и платит), потом «напишите нам»
        return (f"Pentru a continua alegeți abonamentul ({offer_line()}): din program, butonul „Plătește "
                f"acum” (Setări › Licența), sau din contul clinicii ({CONT_URL}), unde comandați nota de plată: "
                f"o plătiți prin transfer bancar cu referința din notă, iar după confirmare termenul se "
                f"prelungește automat în program. Sau răspundeți la acest e-mail / sunați la "
                f"{config.SUPPORT_PHONE}, indicând IDNO-ul clinicii și varianta — vă trimitem nota de plată noi.")
    what = f"{tier_line(pay.get('tier'))}, {luni(pay['months'])}"
    if pay.get("clinics"):
        # общая нота кабинета (26.10): одна сумма за все клиники строки
        what = f"nota comună pentru {len(pay['clinics'])} clinici ({', '.join(pay['clinics'])})"
    try:
        ways = ways_to_pay(pay["reference"], pay["amount"], pay.get("url"))
        text = (f"Pentru a continua — {what}, {pay['amount']} MDL:\n\n{ways} "
                f"Dacă ați plătit deja, ignorați acest mesaj.")
    except RuntimeError:
        text = (f"Nota de plată {pay['reference']} ({what}, {pay['amount']} MDL) "
                f"o primiți separat; întrebări — {config.SUPPORT_EMAIL}.")
    return f"{text}\n\n{change_note(pay.get('page'))}"


_READONLY = ("Datele pacienților se pot consulta, tipări și exporta, iar copia de rezervă rămâne "
             "disponibilă; programări noi și modificări — nu.")


def reminder_letter(kind: str, clinic: str, plan: str, valid_until: datetime, grace_until: datetime,
                    grace_days: int, pay: dict | None) -> tuple[str, str]:
    """Письмо строки таблицы cloud.md › «Напоминания» (kind — из app.jobs).
    У пробного свой текст и свой срок: «perioada de probă», дни льготы из подписки."""
    trial = plan == "trial"
    what = "perioada de probă" if trial else "abonamentul"
    what_cap = what[0].upper() + what[1:]
    for_ = "abonare" if trial else "plată"
    d, g = valid_until.strftime("%d.%m.%Y"), grace_until.strftime("%d.%m.%Y")
    if kind == "invoice":
        subject = f"DentPilot: nota de plată {pay['reference']} — abonamentul expiră la {d}"
        # условия § 4.5: нота за 14 дней — «în varianta în curs»; сменить — change_note в how_to_pay
        intro = (f"Abonamentul DentPilot pentru {clinic} expiră la {d}. După această dată programul "
                 f"funcționează complet încă {zile(grace_days)}, apoi trece în regim de citire. Nota de plată "
                 f"pentru perioada următoare este în varianta în curs, {tier_line(pay.get('tier'))}.")
    elif kind == "expiring":
        subject = f"DentPilot: {what} expiră în 3 zile ({clinic})"
        intro = (f"{what_cap} DentPilot pentru {clinic} expiră la {d}. După această dată programul "
                 f"funcționează complet încă {zile(grace_days)} (până la {g}), apoi trece în regim de citire.")
    elif kind == "expired":
        subject = f"DentPilot: {what} a expirat — {zile(grace_days)} pentru {for_} ({clinic})"
        intro = (f"{what_cap} DentPilot pentru {clinic} a expirat la {d}. Programul funcționează complet "
                 f"până la {g}; după această dată trece în regim de citire. {_READONLY}")
    elif kind == "last_warning":
        subject = f"DentPilot: de mâine programul trece în regim de citire ({clinic})"
        intro = (f"Mâine, {g}, programul DentPilot pentru {clinic} trece în regim de citire: {what} "
                 f"a expirat la {d}. {_READONLY}")
    elif kind == "readonly":
        subject = f"DentPilot: programul este în regim de citire ({clinic})"
        intro = (f"Din {g} programul DentPilot pentru {clinic} este în regim de citire: {what} a expirat "
                 f"la {d}, iar perioada de {zile(grace_days)} pentru {for_} s-a încheiat. {_READONLY} "
                 f"După plată programul revine singur la lucru complet.")
    else:
        raise ValueError(f"kind: {kind}")
    return subject, f"Bună ziua,\n\n{intro}\n\n{how_to_pay(pay)}\n\n{FOOTER}"


def clinic_added_letter(clinic: str, valid_until: datetime, grace_until: datetime, reference: str,
                        amount: int, months: int, tier: str | None, pay_url: str | None = None,
                        page: str | None = None) -> tuple[str, str]:
    """Клинике из «Adaugă clinică» (Олег 27.10: пробный только у главной, добавленная — сразу
    платная и включается сама): включена, до какого дня работает без оплаты, что после, и нота
    первого периода — одно письмо; напоминание «нота» за этот срок задача уже не шлёт."""
    d, g = valid_until.strftime("%d.%m.%Y"), grace_until.strftime("%d.%m.%Y")
    subject = f"DentPilot: {clinic} a fost adăugată în cont — nota de plată {reference}"
    intro = (f"Clinica {clinic} a fost adăugată în contul clinicii și licența ei este activă: programul se "
             f"activează pe calculatorul clinicii cu codul de activare din cont ({CONT_URL}, 7 cifre) și "
             f"pornește imediat. Perioada gratuită de probă este doar pentru prima clinică din cont, așa că "
             f"abonamentul acestei clinici începe de azi.\n\n"
             f"Nota de plată pentru prima perioadă este mai jos — vă rugăm s-o achitați până la {d}. Fără "
             f"plată programul funcționează complet până la {g}, apoi trece în regim de citire. {_READONLY} "
             f"Perioada plătită se numără de azi, nu de la {d}.")
    pay = {"reference": reference, "amount": int(amount), "months": int(months), "tier": tier, "url": pay_url,
           "page": page}
    return subject, f"Bună ziua,\n\n{intro}\n\n{how_to_pay(pay)}\n\n{FOOTER}"


# Файл лицензии клинике не показывается (решение Олега 02.10: клиник без
# интернета нет): письмо говорит про СРОК, а файл программа забирает сама по
# суточному запросу (L13) или при активации (L16/L17). В админке файл остаётся —
# инструмент поддержки.
RENEW_NOTE = ("Programul DentPilot preia singur noul termen când are acces la internet, în cel mult o zi "
              "— nu trebuie să faceți nimic.")


CONT_URL = config.BASE_URL.rstrip("/") + "/cont"

# cont de plată (17.10): фраза в письме об оплате, когда документ приложен (receipts.py)
RECEIPT_NOTE = ("Contul de plată nr. {number}, cu mențiunea „achitat”, este în atașament (PDF) — pentru "
                "contabilitatea clinicii; îl găsiți oricând și în contul clinicii, {cont}.")


def with_receipt(body: str, number: str, summary: str = "") -> str:
    """Письмо с фразой о приложенном cont de plată — перед подписью. `summary` — строки
    оплаты из того же снимка, что PDF (receipts.summary: № заказа, что, сумма, дата,
    поставщик и сайт — требование maib к письму после оплаты)."""
    note = (summary.rstrip() + "\n\n" if summary else "") + RECEIPT_NOTE.format(number=number, cont=CONT_URL)
    tail = "\n\n" + FOOTER
    if body.endswith(tail):
        return body[:-len(tail)] + "\n\n" + note + tail
    return body + "\n\n" + note


def trial_received(clinic: str, days: int, origin: str = "form") -> tuple[str, str]:
    """Клинике: заявка принята (режим approve). С формы — файл придёт письмом; из
    программы — программа активируется сама, письмо с файлом — запасное; из
    кабинета — файл и программа ждут в кабинете. Клинике из «Adaugă clinică» пробного
    нет (27.10) — ей clinic_added_letter."""
    subject = f"DentPilot: cererea de probă pentru {clinic} a fost primită"
    if origin == "program":
        rest = (f"Programul DentPilot se activează singur pentru {zile(days)} imediat ce aprobăm "
                f"cererea — de obicei în aceeași zi lucrătoare; nu trebuie să faceți nimic. Confirmarea "
                f"vine pe acest e-mail.")
    elif origin == "cont":
        rest = (f"Perioada de probă de {zile(days)} se activează în cel mult o zi lucrătoare — vă "
                f"confirmăm pe acest e-mail. Programul îl descărcați din contul clinicii, {CONT_URL}; la "
                f"prima pornire introduceți aceleași date și codul pe care îl trimitem pe acest e-mail.")
    else:
        rest = (f"Perioada de probă de {zile(days)} se activează în cel mult o zi lucrătoare — vă "
                f"confirmăm pe acest e-mail. Programul îl descărcați de pe {config.SITE_URL.rstrip('/')}/descarca.html; "
                f"la prima pornire introduceți aceleași date și codul pe care îl trimitem pe acest e-mail. "
                f"Instalăm împreună, la "
                f"telefon, dacă doriți.")
    body = (f"Bună ziua,\n\n"
            f"Am primit cererea de perioadă de probă DentPilot pentru {clinic}. {rest}\n\n{FOOTER}")
    return subject, body


def trial_notice(clinic, outcome: str, ip: str, fields: dict | None = None,
                 origin: str = "form") -> tuple[str, str]:
    """Олегу: заявка с формы или из программы — кто, что вышло, ссылка на карточку.
    По-русски: письмо своё. При повторе `clinic` — та, что уже есть, а `fields` —
    что написали в заявке."""
    program, cont = origin == "program", origin in ("cont", "cont_add")
    if origin == "cont_add":
        dup = ("ПОВТОР из кабинета: «Adaugă clinică» с IDNO или e-mail ЧУЖОЙ клиники (не этого кабинета) — "
               "ничего не заведено, кабинету ответили «scrieți-ne»; ответьте клинике сами")
    elif cont:
        dup = ("ПОВТОР из кабинета: клиника с этим IDNO уже есть, а вошедший Google-ящик — другой; "
               "на ящик клиники ушёл код для подключения этого аккаунта (как у программы на новом "
               "компьютере) — верный код привязывает его к клинике. Кода в журнале нет (у клиники "
               "нет e-mail или лимит) — регистрации отказано словами «scrieți-ne»: ответьте клинике "
               "сами (новый e-mail в карточке, старую запись отвязать)")
    elif program:
        dup = ("ПОВТОР из программы: клиника с этим IDNO или e-mail уже есть — на её e-mail ушёл "
               "код активации (новый компьютер?); если кода нет в журнале, ответьте клинике сами")
    else:
        dup = "ПОВТОР: клиника с этим IDNO или e-mail уже есть, форме отвечено «принято» — ответьте клинике сами"
    what = {"issued": "пробный файл выдан и отправлен клинике"
                      + (" — программа забирает его сама" if program else "")
                      + (" — файл и программа ждут в кабинете" if cont else ""),
            "issued_unmailed": "файл выдан, но письмо клинике НЕ ушло — в карточке «Отправить последний файл письмом»",
            "requested": ("файл НЕ выдан: нет ключа выдачи — клиника кабинета без пробного, нота за первый "
                          "период выставлена; выдайте «standard» до срока оплаты ноты кнопкой в карточке"
                          if origin == "cont_add" else "ждёт решения: выдать пробный кнопкой в админке"
                          + (" — программа активируется сама, как только файл выдан" if program else "")),
            "added": ("включена сама, без пробного и без вашего одобрения (Олег 27.10): файл «standard» на "
                      "срок оплаты ноты, нота за первый период — письмом клинике; делать ничего не нужно"),
            "duplicate": dup}.get(outcome, outcome)
    f = fields or {}
    source = {"program": "из программы", "cont": "из кабинета (вход через Google)",
              "cont_add": "из кабинета: ещё одна клиника кабинета (филиал)"}.get(origin, "с формы /proba")
    subject = (f"DentPilot Cloud: {'новая клиника в кабинете' if origin == 'cont_add' else 'заявка на пробный'} — "
               f"{f.get('name') or clinic['name']}")
    cab = f"  Кабинет: {f['cabinet']}\n" if f.get("cabinet") else ""
    cab += f"  Нота: {f['nota']}\n" if f.get("nota") else ""
    body = (f"Заявка {source} ({ip}):\n\n{cab}"
            f"  Клиника: {f.get('name') or clinic['name']}\n  IDNO: {f.get('idno') or clinic['idno'] or '—'}\n"
            f"  Контакт: {f.get('contact_name') or clinic['contact_name'] or '—'}\n"
            f"  E-mail: {f.get('email') or clinic['email']}\n"
            f"  Телефон: {f.get('phone') or clinic['phone'] or '—'}\n\n"
            f"Итог: {what}.\nКарточка: {config.BASE_URL.rstrip('/')}/admin/clinics/{clinic['id']}"
            f"{' (' + clinic['name'] + ', ' + (clinic['email'] or '—') + ')' if outcome == 'duplicate' else ''}\n")
    return subject, body


# Имя вложения — без диакритики: почтовые программы клиник переносят его как есть
DECLARATION_NAME = "Declaratie-furnizor-DentPilot-Legea-195.pdf"
DECLARATION_NOTE = ("Tot în atașament este Declarația furnizorului privind datele pacienților "
                    "(Legea nr. 195/2024), care confirmă acest lucru: păstrați-o în mapa "
                    "„Legea 195” a clinicii.")


def declaration() -> tuple[str, bytes] | None:
    """Подписанная декларация поставщика вложением: (имя, байты) или None.

    Читается при каждом письме, а не на старте: Олег кладёт PDF на машину,
    когда подпишет, и перезапуск сервера для этого не нужен. Не PDF (подложили
    не тот файл, обрезался при копировании) — не вложение: письмо с файлом
    лицензии уходит без декларации, а не с мусором от имени поставщика."""
    if not config.DECLARATION:
        return None
    try:
        data = pathlib.Path(config.DECLARATION).read_bytes()
    except OSError as e:
        log.warning("декларация %s не прочитана: %r", config.DECLARATION, e)
        return None
    if not data.startswith(b"%PDF-"):
        log.warning("декларация %s — не PDF, письмо уйдёт без неё", config.DECLARATION)
        return None
    return DECLARATION_NAME, data


def license_letter(clinic: str, valid_until: str, plan: str, renew: bool = False,
                   declaration: bool = False, tier: str | None = None, sms_until: str | None = None) -> tuple[str, str]:
    """Тема и текст письма о лицензии — по-румынски, как интерфейс программы.
    Файла в письме НЕТ (02.10): программа забирает его сама — `renew` (адрес
    автообновления в файле есть) добавляет RENEW_NOTE об этом. `declaration` —
    к письму приложена декларация поставщика: письмо называет её только тогда. `tier` —
    вариант подписки (у пробного не называется: он всегда Plus); `sms_until` — у Basic,
    перешедшего с Plus или пробного: до какого дня модуль SMS ещё работает (§ 4.2)."""
    trial = plan == "trial"
    what = "Perioada de probă DentPilot" if trial else f"Abonamentul {tiers.NAME.get(tier or '', 'DentPilot')}"
    valid = "este valabilă" if trial else "este valabil"
    module = (f" Modulul SMS rămâne pornit până la {ro_date(sms_until)} și se oprește apoi (DentPilot Basic); "
              f"SMS-urile rămase nu se pierd." if sms_until and not trial and tier == tiers.BASIC else "")
    site = config.SITE_URL.rstrip("/")
    subject = f"DentPilot: licența pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"{what} pentru {clinic} {valid} până la {ro_date(valid_until)}.{module}\n\n"
            + (f"{RENEW_NOTE}\n\n" if renew else "") +
            f"Programul îl descărcați de pe {site}/descarca.html sau din contul clinicii ({CONT_URL}). "
            f"Pe un calculator nou, la prima pornire, introduceți datele clinicii: primiți un cod pe "
            f"acest e-mail și programul se activează.\n\n"
            f"Licența este emisă pentru clinica dumneavoastră și nu se transmite altora. "
            f"Datele pacienților rămân pe calculatorul clinicii; noi nu avem acces la ele."
            + (f" {DECLARATION_NOTE}" if declaration else "") + "\n\n"
            + (f"{note}\n\n" if (note := documents_note()) else "")
            + f"{FOOTER}")
    return subject, body


def link_code(clinic: str, code: str, minutes: int, google_email: str, via: str = "Google") -> tuple[str, str]:
    """Клинике: код для подключения учётной записи к её кабинету (01.10). Идёт на
    ящик, записанный у клиники: кто его читает, тот и решает, пускать ли. Ящик
    просителя назван — клиника видит, кто стучится. `via` — Google или e-mail
    (вход кодом, 02.10): письмо называет, как вошёл проситель."""
    subject = f"DentPilot: codul pentru conectarea contului clinicii {clinic}"
    who = f"Contul Google {google_email}" if via == "Google" else f"Contul {google_email} (intrare prin e-mail)"
    body = (f"Bună ziua,\n\n"
            f"{who} cere acces la contul clinicii {clinic} pe {CONT_URL}. "
            f"Dacă sunteți dvs. sau o persoană din clinică, introduceți în pagina de înregistrare "
            f"codul: {code}\n\n"
            f"Codul este valabil {minutes} minute și se folosește o singură dată.\n\n"
            f"Dacă nu ați cerut acest cod, ignorați mesajul: fără el nimeni nu poate intra în contul "
            f"clinicii.\n\n{FOOTER}")
    return subject, body


def login_code(code: str, minutes: int) -> tuple[str, str]:
    """На ящик, который ввели на странице входа (02.10): код входа в кабинет без
    Google. Клиника не называется — ящик может быть ещё ничей."""
    subject = "DentPilot: codul de intrare în contul clinicii"
    body = (f"Bună ziua,\n\n"
            f"Codul pentru intrarea în contul clinicii pe {CONT_URL}: {code}\n\n"
            f"Introduceți-l în pagina de intrare. Codul este valabil {minutes} minute și se folosește o "
            f"singură dată.\n\n"
            f"Dacă nu ați cerut acest cod, ignorați mesajul: fără el nimeni nu poate intra în cont cu "
            f"adresa dvs. de e-mail.\n\n{FOOTER}")
    return subject, body


def activation_code(clinic: str, code: str, minutes: int) -> tuple[str, str]:
    """Клинике: код для активации программы на новом компьютере (26.09). Идёт на
    адрес, который у клиники уже записан, — код и есть доказательство, что
    активирует она."""
    subject = f"DentPilot: codul de activare pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"Codul pentru activarea programului DentPilot pe un calculator al clinicii {clinic}: "
            f"{code}\n\n"
            f"Introduceți-l pe pagina de activare a programului. Codul este valabil {minutes} minute "
            f"și se folosește o singură dată.\n\n"
            f"Dacă activați o clinică nouă (filială), folosiți codul din contul clinicii, {CONT_URL} — "
            f"acela leagă calculatorul de filială; acest cod îl leagă de {clinic}.\n\n"
            f"Dacă nu ați cerut acest cod, ignorați mesajul: fără el nimeni nu poate activa "
            f"programul în numele clinicii.\n\n{FOOTER}")
    return subject, body



# ---------- подтверждение ящика клиники (27.10, emailconf.py) ----------

# Зачем подтверждать — словами клиники: на этот ящик идут коды и ноты. Один текст на письмо о
# лицензии и на отдельное письмо «Retrimite» из программы.
CONFIRM_WHY = ("Pe această adresă trimitem codurile pentru un calculator nou, codul de intrare în contul "
               "clinicii, notele de plată și înștiințările despre termenul licenței.")


def confirm_lines(url: str, code: str, days: int) -> str:
    return (f"Confirmați adresa de e-mail a clinicii: deschideți linkul și apăsați „Confirmă adresa”:\n"
            f"{url}\n"
            f"sau introduceți în program, la Setări › Licența, codul: {code}\n"
            f"Linkul și codul sunt valabile {zile(days)}. {CONFIRM_WHY}")


def with_confirm(body: str, url: str, code: str, days: int) -> str:
    """Письмо о лицензии неподтверждённой клинике: просьба подтвердить ящик — сразу после первого
    абзаца (срок), до остального: письмо о пробном и есть то, которое клиника откроет первым."""
    parts = body.split("\n\n", 2)
    if len(parts) < 3:
        return body + "\n\n" + confirm_lines(url, code, days)
    return "\n\n".join([parts[0], parts[1], confirm_lines(url, code, days), parts[2]])


def confirm_letter(clinic: str, url: str, code: str, days: int) -> tuple[str, str]:
    """«Retrimite» и «Schimbă adresa» из программы: только подтверждение ящика."""
    subject = f"DentPilot: confirmați adresa de e-mail pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"Programul DentPilot pentru {clinic} a cerut confirmarea acestei adrese de e-mail.\n\n"
            f"{confirm_lines(url, code, days)}\n\n"
            f"Dacă nu lucrați cu DentPilot, ignorați mesajul: adresa nu se confirmă fără linkul sau "
            f"codul de mai sus.\n\n{FOOTER}")
    return subject, body


# ---------- документы поставщика в кабинете (29.10, contracts.py) ----------

DOCUMENTS_URL = CONT_URL + "/documente"


def documents_note() -> str:
    """Строка письма о лицензии: договор и соглашение, подписанные поставщиком, лежат в кабинете.
    '' — пока DP_CONTRACT не указывает на файл: письмо не обещает документ, которого в кабинете нет
    (Олег подписывает PDF и кладёт на сервер; проверяется при каждом письме, как декларация)."""
    if not config.CONTRACT or not pathlib.Path(config.CONTRACT).is_file():
        return ""
    return (f"Contractul de licență și Acordul de prelucrare a datelor, semnate de furnizor, le găsiți în contul "
            f"clinicii: {DOCUMENTS_URL} — de descărcat pentru contabilitatea clinicii; acolo puteți încărca și "
            f"exemplarul semnat de clinică.")

