"""Правило SMS (S2): сколько сегментов стоит текст и годится ли номер.

Контракт — docs/dentpilot-2/sms.md › «sms.md — что известно» и «Шаблоны и
сегменты». Сервер списывает пакет по ЭТОМУ счёту до вызова sms.md; если sms.md
насчитал иначе, истинно его число (строка `fix` и письмо Олегу — S3). Номер —
мобильный Молдовы, восемь цифр без кода страны; остальное — отказ `sms_phone`.

⚠️ Вторая копия правила: первая — bot/app/core/sms_rule.py в программе (её
счётчик видит клиника в редакторе шаблона). Импортов из bot/ у сервера нет,
поэтому копии сходятся на общем векторе tests/fixtures/sms/ (его читают оба
прогона) и на сверке копий в cloud/tests/test_sms_rule.py. Правишь правило
здесь — правь там же и дописывай вектор.
"""
from __future__ import annotations

import re

# ---- сегменты ----

GSM7, UCS2 = "gsm7", "ucs2"

# GSM 03.38, основная таблица: знак — один септет. ESC (0x1B) сюда не входит:
# это префикс таблицы расширения, а не знак текста.
GSM_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
# Таблица расширения: ESC + знак, два септета. Список — тот, что назвал
# sms.md. Перевод формата (FF) стандарт тоже относит сюда, но sms.md его не
# назвал, а шаблону он не нужен: текст с ним считается как UCS-2.
GSM_EXT = frozenset("^{}[]~\\|€")

SINGLE = {GSM7: 160, UCS2: 70}      # одна SMS
MULTI = {GSM7: 153, UCS2: 67}       # кусок склеенной: остальное занимает заголовок склейки


def parts(text: str) -> tuple[str, int, int]:
    """(кодировка, единиц, сегментов) — как посчитает sms.md.

    Единица — септет GSM (знак расширения — два) или 16-битная единица UCS-2
    (знак вне BMP, то есть почти любой эмодзи, — суррогатная пара, две). Один
    знак вне GSM — «ă», «—», «„”», «’», неразрывный пробел — переводит в UCS-2
    всю SMS. Пустой текст — ноль сегментов: отправлять нечего, а отказ — дело
    проверки текста, не счёта.

    ⚠️ Знак между кусками не рвётся: ESC-пара и суррогатная пара целиком
    переезжают в следующий кусок, если в текущем осталось одно место. Поэтому
    сегменты — не `ceil(единиц / 153)`: у текста с таким знаком на границе их
    на один больше.
    """
    if all(c in GSM_BASIC or c in GSM_EXT for c in text):
        enc = GSM7
        sizes = [2 if c in GSM_EXT else 1 for c in text]
    else:
        enc = UCS2
        sizes = [2 if ord(c) > 0xFFFF else 1 for c in text]
    total = sum(sizes)
    if total == 0:
        return enc, 0, 0
    if total <= SINGLE[enc]:
        return enc, total, 1
    count, room = 1, MULTI[enc]
    for size in sizes:
        if size > room:
            count, room = count + 1, MULTI[enc]
        room -= size
    return enc, total, count


# ---- номер ----

COUNTRY = "373"
# Первые две цифры мобильного номера Молдовы — список sms.md (16.10).
# ⚠️ «80» в плане нумерации ANRCETI — блок бесплатных номеров (8XX), а sms.md
# назвал его мобильным; держим список sms.md, пока он сам не скажет иначе.
MOBILE = frozenset({"60", "61", "62", "67", "68", "69", "76", "78", "79", "80"})

# Причины отказа: одно состояние — одно имя.
EMPTY = "empty"             # номера нет
GARBAGE = "garbage"         # буквы и знаки, которых в номере не бывает
LENGTH = "length"           # цифр не столько, сколько в номере Молдовы
FOREIGN = "foreign"         # другая страна: у sms.md международное, в v1 выключено
LEFT_BANK = "left_bank"     # 77… — левобережье: у sms.md международное, в v1 не шлём
LANDLINE = "landline"       # стационарный (2…, на левобережье 5…): SMS не дойдёт
NOT_MOBILE = "not_mobile"   # прочие восьмизначные: сервисные, премиальные, свободные
REASONS = (EMPTY, GARBAGE, LENGTH, FOREIGN, LEFT_BANK, LANDLINE, NOT_MOBILE)

# Разделители, которые пишут люди: пробел любой ширины (и неразрывный из
# скопированного текста), дефис, точка, скобки.
_SEP = re.compile(r"[\s\-.()]+")
# Только ASCII-цифры: str.isdigit() пропустил бы и «٠٦٩», и полноширинные.
_DIGITS = re.compile(r"\+?[0-9]+")


def phone(raw: str | None) -> tuple[str, str]:
    """(восемь цифр, "") или ("", причина из REASONS).

    Принимает формы, которые принимает sms.md: `69123456`, `069123456`,
    `37369123456`, `+373 69 123 456`, с дефисами и скобками, а также `00373…`
    и `+373 0 69…` (ноль междугородного по привычке — однозначен).
    """
    s = _SEP.sub("", raw or "")
    if not s:
        return "", EMPTY
    if not _DIGITS.fullmatch(s):
        return "", GARBAGE
    if s.startswith("+"):
        intl = s[1:]
    elif s.startswith("00"):
        intl = s[2:]
    elif s.startswith(COUNTRY) and len(s) in (11, 12):
        intl = s
    else:
        intl = None
    if intl is not None:
        if len(intl) < 8:
            return "", LENGTH
        if not intl.startswith(COUNTRY):
            return "", FOREIGN
        nat = intl[len(COUNTRY):]
        if len(nat) == 9 and nat.startswith("0"):
            nat = nat[1:]
    elif s.startswith("0"):
        nat = s[1:]
    else:
        nat = s
    if len(nat) != 8 or nat.startswith("0"):
        return "", LENGTH
    if nat[:2] in MOBILE:
        return nat, ""
    if nat.startswith("77"):
        return "", LEFT_BANK
    if nat[0] in "25":
        return "", LANDLINE
    return "", NOT_MOBILE


# ---- личный текст клиники (S6) ----
#
# Белый список подстановок — тот же, что у готовых текстов программы
# (bot/app/core/sms_plan.py: PLACEHOLDERS, REQUIRED, CUSTOM_MAX, custom_ok,
# placeholders, render); сверяет cloud/tests/test_sms_rule.py. ⛔ Врача, услуги
# и имени пациента здесь нет и не будет: SMS читают с экрана блокировки, и
# текст проходит через двух обработчиков.
PLACEHOLDERS = ("clinica", "ziua", "data", "ora", "telefon")
REQUIRED = ("clinica", "data", "ora")
CUSTOM_MAX = 400
_PH = re.compile(r"\{([A-Za-z_]+)\}")


def placeholders(template: str) -> set[str]:
    return set(_PH.findall(template or ""))


def custom_ok(template) -> bool:
    """Годен ли личный текст: строка, подстановки из белого списка, клиника,
    дата и час на месте."""
    if not isinstance(template, str) or not template.strip() or len(template) > CUSTOM_MAX:
        return False
    ph = placeholders(template)
    return ph <= set(PLACEHOLDERS) and set(REQUIRED) <= ph


def render(template: str, values: dict) -> str:
    """Подстановка одним проходом; незнакомое имя остаётся как есть."""
    return _PH.sub(lambda m: values.get(m.group(1), m.group(0)), template)
