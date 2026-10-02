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

from . import config

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
CARD_NOTE = "Plata cu cardul (Visa, Mastercard, Apple Pay, Google Pay), pe pagina securizată maib:"


def card_lines(pay_url: str, amount: int) -> str:
    """Ссылка на hosted-страницу maib (L12). После оплаты картой программа продлевается сама."""
    return (f"{CARD_NOTE}\n  {pay_url}\n  Suma: {amount} MDL\n"
            f"  După plata cu cardul nu trebuie să faceți nimic: noul termen ajunge singur în program "
            f"în câteva minute, iar confirmarea — pe e-mail.\n")


def ways_to_pay(reference: str, amount: int, pay_url: str | None) -> str:
    """Способы оплаты по порядку: карта (если есть ссылка), перевод (если есть
    реквизиты). Ни того ни другого — RuntimeError, как у bank_lines."""
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


def payment_letter(clinic: str, reference: str, amount: int, months: int,
                   pay_url: str | None = None) -> tuple[str, str]:
    """Письмо с нотой: ссылка на карту (L12), реквизиты перевода — что настроено."""
    ways = ways_to_pay(reference, amount, pay_url)
    subject = f"DentPilot: nota de plată {reference} pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"Pentru continuarea abonamentului DentPilot ({clinic}, {luni(months)}) "
            f"vă rugăm să achitați {amount} MDL:\n\n"
            f"{ways}\n\n"
            f"{FOOTER}")
    return subject, body


def how_to_pay(pay: dict | None, price: int) -> str:
    """Абзац «как продолжить»: ссылка на карту и/или реквизиты с reference
    (абонемент) или как оформить абонемент (пробный). Без ссылки и без
    DP_BANK_* — честная фраза, что нота придёт отдельно."""
    if pay is None:
        return (f"Pentru a continua cu un abonament ({price} MDL pe lună) răspundeți la acest e-mail "
                f"sau sunați la {config.SUPPORT_PHONE}, indicând IDNO-ul clinicii — vă trimitem nota "
                f"de plată, iar după plată termenul se prelungește automat în program.")
    try:
        ways = ways_to_pay(pay["reference"], pay["amount"], pay.get("url"))
    except RuntimeError:
        return (f"Nota de plată {pay['reference']} ({pay['amount']} MDL pentru {luni(pay['months'])}) "
                f"o primiți separat; întrebări — {config.SUPPORT_EMAIL}.")
    return (f"Pentru a continua ({luni(pay['months'])}, {pay['amount']} MDL):\n\n{ways} "
            f"Dacă ați plătit deja, ignorați acest mesaj.")


_READONLY = ("Datele pacienților se pot consulta, tipări și exporta, iar copia de rezervă rămâne "
             "disponibilă; programări noi și modificări — nu.")


def reminder_letter(kind: str, clinic: str, plan: str, valid_until: datetime, grace_until: datetime,
                    grace_days: int, pay: dict | None, price: int) -> tuple[str, str]:
    """Письмо строки таблицы cloud.md › «Напоминания» (kind — из app.jobs).
    У пробного свой текст и свой срок: «perioada de probă», дни льготы из подписки."""
    trial = plan == "trial"
    what = "perioada de probă" if trial else "abonamentul"
    what_cap = what[0].upper() + what[1:]
    for_ = "abonare" if trial else "plată"
    d, g = valid_until.strftime("%d.%m.%Y"), grace_until.strftime("%d.%m.%Y")
    if kind == "invoice":
        subject = f"DentPilot: nota de plată {pay['reference']} — abonamentul expiră la {d}"
        intro = (f"Abonamentul DentPilot pentru {clinic} expiră la {d}. După această dată programul "
                 f"funcționează complet încă {zile(grace_days)}, apoi trece în regim de citire.")
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
    return subject, f"Bună ziua,\n\n{intro}\n\n{how_to_pay(pay, price)}\n\n{FOOTER}"


# Файл лицензии клинике не показывается (решение Олега 02.10: клиник без
# интернета нет): письмо говорит про СРОК, а файл программа забирает сама по
# суточному запросу (L13) или при активации (L16/L17). В админке файл остаётся —
# инструмент поддержки.
RENEW_NOTE = ("Programul DentPilot preia singur noul termen când are acces la internet, în cel mult o zi "
              "— nu trebuie să faceți nimic.")


CONT_URL = config.BASE_URL.rstrip("/") + "/cont"


def trial_received(clinic: str, days: int, origin: str = "form") -> tuple[str, str]:
    """Клинике: заявка принята (режим approve). С формы — файл придёт письмом; из
    программы — программа активируется сама, письмо с файлом — запасное; из
    кабинета — файл и программа ждут в кабинете."""
    subject = f"DentPilot: cererea de probă pentru {clinic} a fost primită"
    if origin == "program":
        rest = (f"Programul DentPilot se activează singur pentru {zile(days)} imediat ce aprobăm "
                f"cererea — de obicei în aceeași zi lucrătoare; nu trebuie să faceți nimic. Confirmarea "
                f"vine pe acest e-mail.")
    elif origin == "cont":
        rest = (f"Perioada de probă de {zile(days)} se activează în cel mult o zi lucrătoare — vă "
                f"confirmăm pe acest e-mail. Programul îl descărcați din contul clinicii, {CONT_URL}; la "
                f"prima pornire introduceți aceleași date și se activează singur.")
    else:
        rest = (f"Perioada de probă de {zile(days)} se activează în cel mult o zi lucrătoare — vă "
                f"confirmăm pe acest e-mail. Programul îl descărcați de pe {config.SITE_URL.rstrip('/')}/descarca.html; "
                f"la prima pornire introduceți aceleași date și se activează singur. Instalăm împreună, la "
                f"telefon, dacă doriți.")
    body = (f"Bună ziua,\n\n"
            f"Am primit cererea de perioadă de probă DentPilot pentru {clinic}. {rest}\n\n{FOOTER}")
    return subject, body


def trial_notice(clinic, outcome: str, ip: str, fields: dict | None = None,
                 origin: str = "form") -> tuple[str, str]:
    """Олегу: заявка с формы или из программы — кто, что вышло, ссылка на карточку.
    По-русски: письмо своё. При повторе `clinic` — та, что уже есть, а `fields` —
    что написали в заявке."""
    program, cont = origin == "program", origin == "cont"
    if cont:
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
            "requested": "ждёт решения: выдать пробный кнопкой в админке"
                         + (" — программа активируется сама, как только файл выдан" if program else ""),
            "duplicate": dup}.get(outcome, outcome)
    f = fields or {}
    source = {"program": "из программы", "cont": "из кабинета (вход через Google)"}.get(origin, "с формы /proba")
    subject = f"DentPilot Cloud: заявка на пробный — {f.get('name') or clinic['name']}"
    body = (f"Заявка {source} ({ip}):\n\n"
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
                   declaration: bool = False) -> tuple[str, str]:
    """Тема и текст письма о лицензии — по-румынски, как интерфейс программы.
    Файла в письме НЕТ (02.10): программа забирает его сама — `renew` (адрес
    автообновления в файле есть) добавляет RENEW_NOTE об этом. `declaration` —
    к письму приложена декларация поставщика: письмо называет её только тогда."""
    what = "Perioada de probă" if plan == "trial" else "Abonamentul"
    valid = "este valabilă" if plan == "trial" else "este valabil"
    site = config.SITE_URL.rstrip("/")
    subject = f"DentPilot: licența pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"{what} DentPilot pentru {clinic} {valid} până la {valid_until[:10]}.\n\n"
            + (f"{RENEW_NOTE}\n\n" if renew else "") +
            f"Programul îl descărcați de pe {site}/descarca.html sau din contul clinicii ({CONT_URL}). "
            f"Pe un calculator nou, la prima pornire, introduceți datele clinicii: primiți un cod pe "
            f"acest e-mail și programul se activează.\n\n"
            f"Licența este emisă pentru clinica dumneavoastră și nu se transmite altora. "
            f"Datele pacienților rămân pe calculatorul clinicii; noi nu avem acces la ele."
            + (f" {DECLARATION_NOTE}" if declaration else "") + "\n\n"
            f"{FOOTER}")
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
            f"Dacă nu ați cerut acest cod, ignorați mesajul: fără el nimeni nu poate activa "
            f"programul în numele clinicii.\n\n{FOOTER}")
    return subject, body

