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
                   "recunoaștem plata dumneavoastră. După confirmare primiți prin e-mail fișierul de "
                   "licență cu noul termen.")
CARD_NOTE = "Plata cu cardul (Visa, Mastercard, Apple Pay, Google Pay), pe pagina securizată maib:"


def card_lines(pay_url: str, amount: int) -> str:
    """Ссылка на hosted-страницу maib (L12). После оплаты картой файл приходит сам."""
    return (f"{CARD_NOTE}\n  {pay_url}\n  Suma: {amount} MDL\n"
            f"  După plata cu cardul nu trebuie să faceți nimic: fișierul de licență cu noul "
            f"termen vine pe e-mail în câteva minute.\n")


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
                f"de plată, iar după plată noul fișier de licență.")
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
                 f"După activarea noului fișier de licență programul revine la lucru complet.")
    else:
        raise ValueError(f"kind: {kind}")
    return subject, f"Bună ziua,\n\n{intro}\n\n{how_to_pay(pay, price)}\n\n{FOOTER}"


RENEW_NOTE = ("Dacă programul este deja activat și are acces la internet, preia singur "
              "fișierul nou în cel mult o zi — nu trebuie să faceți nimic.")


def trial_received(clinic: str, days: int) -> tuple[str, str]:
    """Клинике: заявка с формы принята (режим approve), файл придёт отдельным письмом."""
    subject = f"DentPilot: cererea de probă pentru {clinic} a fost primită"
    body = (f"Bună ziua,\n\n"
            f"Am primit cererea de perioadă de probă DentPilot pentru {clinic}. Fișierul de licență "
            f"pentru {zile(days)} vine pe acest e-mail în cel mult o zi lucrătoare, împreună cu pașii de "
            f"activare; programul îl instalăm împreună, la telefon.\n\n{FOOTER}")
    return subject, body


def trial_notice(clinic, outcome: str, ip: str, fields: dict | None = None) -> tuple[str, str]:
    """Олегу: заявка с формы — кто, что вышло, ссылка на карточку. По-русски: письмо
    своё. При повторе `clinic` — та, что уже есть, а `fields` — что написали в форме."""
    what = {"issued": "пробный файл выдан и отправлен клинике",
            "issued_unmailed": "файл выдан, но письмо клинике НЕ ушло — в карточке «Отправить последний файл письмом»",
            "requested": "ждёт решения: выдать пробный кнопкой в админке",
            "duplicate": "ПОВТОР: клиника с этим IDNO или e-mail уже есть, форме отвечено «принято» — "
                         "ответьте клинике сами"}.get(outcome, outcome)
    f = fields or {}
    subject = f"DentPilot Cloud: заявка на пробный — {f.get('name') or clinic['name']}"
    body = (f"Заявка с формы /proba ({ip}):\n\n"
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
    """Тема и текст письма с файлом — по-румынски, как интерфейс программы.
    `renew` — в файле есть адрес автообновления (L13): письмо говорит, что
    активированной программе делать ничего не нужно. `declaration` — к письму
    приложена декларация поставщика: письмо называет её только тогда."""
    what = "perioada de probă" if plan == "trial" else "abonamentul"
    subject = f"DentPilot: fișierul de licență pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"În atașament este fișierul de licență DentPilot pentru {clinic} — {what} "
            f"este valabil până la {valid_until[:10]}.\n\n"
            f"Cum se activează:\n"
            f"1. Salvați fișierul license.json pe calculatorul clinicii.\n"
            f"2. În DentPilot deschideți pagina Licență (meniul Setări sau adresa "
            f"/admin/license din program).\n"
            f"3. Alegeți fișierul, bifați acceptarea Termenilor și condițiilor și apăsați "
            f"«Activează licența».\n\n"
            + (f"{RENEW_NOTE}\n\n" if renew else "") +
            f"Fișierul este emis pentru clinica dumneavoastră și nu se transmite altora. "
            f"Datele pacienților rămân pe calculatorul clinicii; noi nu avem acces la ele."
            + (f" {DECLARATION_NOTE}" if declaration else "") + "\n\n"
            f"{FOOTER}")
    return subject, body
