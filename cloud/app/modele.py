"""Образцы документов закона 195 для клиники в кабинете (31.10.2026): «Modele pentru clinică».

Слово Олега 31.10: «да идея хорошая, про HTML страницы, давай так и сделаем». Сайт обещал прислать
образцы на e-mail в начале пробного — облако их не слало; теперь они лежат во вкладке «Documente»
кабинета и открываются страницей браузера: жёлтые поля заполняются прямо в ней, Ctrl+P — на бумагу.
План, опись и почему образцы 3, 5, 6 ушли в архив (их закрыли договор и DPA 30.10, заявление на имя
SMS кабинет печатает сам) — `review/plan-docs-195-2026-10-31.md` корня проекта.

Файлы — в репозитории (`assets/modele/`), а не на сервере, как PDF поставщика: образцы никто не
подписывает заранее, едут с кодом, версию держит git, и тест видит те же байты, что сервер.
Версия образца — дата редакции: в кабинете и на самом листе («redacția din …»), тест держит
равенство. Правка листа = новая дата здесь и в файле.

Реквизиты клиники подставляются только в поля, размеченные `data-k`, и ⛔ только через
`html.escape`: название клиники вводит человек, и `<img onerror>` в нём сработал бы на странице
кабинета. Пустое поле остаётся жёлтым заполнителем «…» — его допишут ручкой. Скрипт листа сам
считает поле без «…» заполненным. Галочка «Pachetul SMS» приходит отмеченной у клиники с работающим
пакетом; состояние нигде не хранится — как и всё, что вписано в лист.

⚠️ Основания в «Informarea pacienților» обязаны совпадать с листом пациента в программе
(`bot/app/modules/patients/acord.py`, `_T` и `_T_SMS`): правка одного без другого — два документа
клиники, по-разному объясняющие, на каком основании она лечит.
"""
from __future__ import annotations

import html
import pathlib
import re
import sqlite3

from . import sms

ASSETS = pathlib.Path(__file__).resolve().parent / "assets" / "modele"
# ⛔ ключ не равен имени вкладки кабинета (`views.CONT_TABS`) и не собирается в путь: файл берётся
# только из этого словаря
MODELE = {
    "informare": {"file": "informare-pacienti.html", "title": "Informarea pacienților",
                  "what": "se afișează la recepție; aceleași temeiuri ca formularul personal «Informare și acord» "
                          "din program",
                  "version": "31.10.2026"},
    "registru": {"file": "registru-prelucrare.html", "title": "Registrul activităților de prelucrare",
                 "what": "documentul pe care îl cere CNPDCP la un control; se actualizează când se schimbă ceva",
                 "version": "31.10.2026"},
    "bitlocker": {"file": "bitlocker.html", "title": "Criptarea calculatorului (BitLocker)",
                  "what": "instrucțiune de 10 minute și actul de confirmare, de semnat",
                  "version": "31.10.2026"},
    "verificare": {"file": "lista-verificare.html", "title": "Lista de verificare — Legea 195",
                   "what": "ce trebuie să aibă clinica: hârtiile, criptarea, copiile de rezervă; de bifat pe hârtie",
                   "version": "31.10.2026"},
}
FIELDS = ("name", "idno", "address", "phone")      # колонки clinics, которые лист знает по `data-k`
_FILL = re.compile(r'(<span class="fill" data-k="(' + "|".join(FIELDS) + r')">)«[^<]*»(</span>)')
_TOGGLE = '<input type="checkbox" id="sms-toggle">'


def source(key: str) -> str | None:
    """Текст образца как он лежит в репозитории; None — нет такого ключа или файла."""
    m = MODELE.get(key)
    if m is None:
        return None
    try:
        return (ASSETS / m["file"]).read_text(encoding="utf-8")
    except OSError:
        return None


def sms_on(acc: sqlite3.Row | None) -> bool:
    """Работает ли у клиники SMS-пакет: счёт есть, пакет предложен (`sms.offered`) и не выключен Олегом.
    Без строки `sms_accounts` — нет: `offered(None)` при DP_SMS_OFFERED отвечает «да» всем."""
    return acc is not None and sms.offered(acc) and bool(acc["enabled"])


def render(key: str, clinic, with_sms: bool = False) -> str | None:
    """Образец с реквизитами клиники: поле `data-k` → значение через html.escape (пустое — остаётся
    «…»); у клиники с SMS-пакетом галочка отмечена. None — нет такого образца."""
    page = source(key)
    if page is None:
        return None

    def fill(m: re.Match) -> str:
        value = (clinic[m.group(2)] or "").strip()
        return m.group(1) + html.escape(value, quote=True) + m.group(3) if value else m.group(0)

    page = _FILL.sub(fill, page)
    if with_sms:
        page = page.replace(_TOGGLE, '<input type="checkbox" id="sms-toggle" checked>', 1)
    return page
