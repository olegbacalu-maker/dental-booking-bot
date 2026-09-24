"""Письма клинике: SMTP с STARTTLS или, без DP_SMTP_HOST, сухой прогон в папку.

Сухой прогон — не заглушка «для тестов», а честный режим: письмо целиком
ложится .eml-файлом в DP_MAIL_OUTBOX, и его можно открыть почтовой программой.
Без хоста и без папки отправка отказывает словами, а не молча.
"""
from __future__ import annotations

import pathlib
import smtplib
import time
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


def payment_letter(clinic: str, reference: str, amount: int, months: int) -> tuple[str, str]:
    """Письмо с реквизитами перевода. Требует заполненных DP_BANK_* — иначе RuntimeError."""
    b = config.BANK
    if not (b["iban"] and b["beneficiary"]):
        raise RuntimeError("DP_BANK_IBAN / DP_BANK_BENEFICIARY пусты: реквизитов для письма нет")
    subject = f"DentPilot: nota de plată {reference} pentru {clinic}"
    body = (f"Bună ziua,\n\n"
            f"Pentru continuarea abonamentului DentPilot ({clinic}, {months} "
            f"{'lună' if months == 1 else 'luni'}) vă rugăm să efectuați un transfer bancar:\n\n"
            f"  Suma: {amount} MDL\n"
            f"  Beneficiar: {b['beneficiary']}\n"
            f"  IBAN: {b['iban']}\n"
            + (f"  Banca: {b['bank']}\n" if b['bank'] else "")
            + (f"  Cod fiscal: {b['code']}\n" if b['code'] else "")
            + f"  Destinația plății: {reference}\n\n"
            f"Important: indicați neapărat referința {reference} în destinația plății — după ea "
            f"recunoaștem plata dumneavoastră. După confirmare primiți prin e-mail fișierul de "
            f"licență cu noul termen.\n\n"
            f"Întrebări: {config.SUPPORT_EMAIL} · {config.SUPPORT_PHONE}\n\n"
            f"DentPilot")
    return subject, body


def license_letter(clinic: str, valid_until: str, plan: str) -> tuple[str, str]:
    """Тема и текст письма с файлом — по-румынски, как интерфейс программы."""
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
            f"Fișierul este emis pentru clinica dumneavoastră și nu se transmite altora. "
            f"Datele pacienților rămân pe calculatorul clinicii; noi nu avem acces la ele.\n\n"
            f"Întrebări: {config.SUPPORT_EMAIL} · {config.SUPPORT_PHONE}\n\n"
            f"DentPilot")
    return subject, body
