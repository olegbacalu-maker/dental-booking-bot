"""Письма клинике: SMTP с STARTTLS или, без DP_SMTP_HOST, сухой прогон в папку.

Сухой прогон — не заглушка «для тестов», а честный режим: письмо целиком
ложится .eml-файлом в DP_MAIL_OUTBOX, и его можно открыть почтовой программой.
Без хоста и без папки отправка отказывает словами, а не молча.

Тексты — румынские, теми же словами, что баннеры программы (layout.py):
«regim de citire», «datele se pot consulta, tipări și exporta». Русская
версия — когда появится клиника, которая попросит.
"""
from __future__ import annotations

import pathlib
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage

from . import config


def send(to: str, subject: str, body: str,
         attachment: tuple[str, bytes] | None = None) -> str:
    """Возвращает 'smtp' или путь файла в outbox. Бросает RuntimeError, когда некуда."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.MAIL_FROM, to, subject
    msg.set_content(body)
    if attachment:
        name, data = attachment
        msg.add_attachment(data, maintype="application", subtype="json", filename=name)
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
                 f"funcționează complet încă {grace_days} zile, apoi trece în regim de citire.")
    elif kind == "expiring":
        subject = f"DentPilot: {what} expiră în 3 zile ({clinic})"
        intro = (f"{what_cap} DentPilot pentru {clinic} expiră la {d}. După această dată programul "
                 f"funcționează complet încă {grace_days} zile (până la {g}), apoi trece în regim de citire.")
    elif kind == "expired":
        subject = f"DentPilot: {what} a expirat — {grace_days} zile pentru {for_} ({clinic})"
        intro = (f"{what_cap} DentPilot pentru {clinic} a expirat la {d}. Programul funcționează complet "
                 f"până la {g}; după această dată trece în regim de citire. {_READONLY}")
    elif kind == "last_warning":
        subject = f"DentPilot: de mâine programul trece în regim de citire ({clinic})"
        intro = (f"Mâine, {g}, programul DentPilot pentru {clinic} trece în regim de citire: {what} "
                 f"a expirat la {d}. {_READONLY}")
    elif kind == "readonly":
        subject = f"DentPilot: programul este în regim de citire ({clinic})"
        intro = (f"Din {g} programul DentPilot pentru {clinic} este în regim de citire: {what} a expirat "
                 f"la {d}, iar perioada de {grace_days} zile pentru {for_} s-a încheiat. {_READONLY} "
                 f"După activarea noului fișier de licență programul revine la lucru complet.")
    else:
        raise ValueError(f"kind: {kind}")
    return subject, f"Bună ziua,\n\n{intro}\n\n{how_to_pay(pay, price)}\n\n{FOOTER}"


RENEW_NOTE = ("Dacă programul este deja activat și are acces la internet, preia singur "
              "fișierul nou în cel mult o zi — nu trebuie să faceți nimic.")


def license_letter(clinic: str, valid_until: str, plan: str, renew: bool = False) -> tuple[str, str]:
    """Тема и текст письма с файлом — по-румынски, как интерфейс программы.
    `renew` — в файле есть адрес автообновления (L13): письмо говорит, что
    активированной программе делать ничего не нужно."""
    what = "perioada de probă" if plan == "trial" else "abonamentul"
    subject = f"DentPilot: fișierul de licență pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"În atașament este fișierul de licență DentPilot pentru {clinic} — {what} "
            f"este valabil până la {valid_until[:10]}.\n\n"
            f"Cum se activează:\n"
            f"1. Salvați fișierul license.json pe calculatorul clinicii.\n"
            f"2. În DentPilot deschideți pagina Licență (meniul Setări sau adresa "
            f"/admin/license din program).\n"
            f"3. Alegeți fișierul și apăsați «Activează licența».\n\n"
            + (f"{RENEW_NOTE}\n\n" if renew else "") +
            f"Fișierul este emis pentru clinica dumneavoastră și nu se transmite altora. "
            f"Datele pacienților rămân pe calculatorul clinicii; noi nu avem acces la ele.\n\n"
            f"{FOOTER}")
    return subject, body
