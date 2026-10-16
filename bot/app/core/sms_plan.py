"""Готовые тексты SMS и час отправки (S5) — чистые функции, без проекта, диска и часов.

Контракт — docs/dentpilot-2/sms.md › «События», «Шаблоны и сегменты». Модуль
не импортирует ничего из проекта (как license_renew.py и sms_rule.py): прогон
грузит его по пути и держит на нём «каждый готовый текст — один сегмент» и
пограничные правила часа, а прогон сервера сверяет с ним белый список
подстановок личного текста клиники. Время приходит аргументами.

⭐ Тексты пишем мы, клиника их не правит (Олег 16.10): одна «ă» или «—» от
регистратора удваивает цену каждой SMS, а дописанное «extracție» или имя врача
— уже данные о здоровье. Клиника выбирает вариант на событие и строку с
телефоном для отмены; свой текст — только по заявке, через админку облака
(`CUSTOM`, приезжает в /v1/sms/account).

⛔ Подстановки — только `PLACEHOLDERS`: ни врача, ни услуги, ни имени
пациента. SMS читают с экрана блокировки, и она проходит через двух
обработчиков. Держит `test_structure` («подстановки SMS — белый список»).

⚠️ Румынский — без диакритики и типографских знаков: одна «ă», «—», «„”» или
«’» переводит всю SMS в UCS-2, и она стоит вдвое. Название клиники и телефон
приходят от клиники — их приводит `fold()`. Русский — UCS-2 всегда, 70 знаков
на сегмент: один сегмент держится на названии до `NAME_MAX["ru"]` знаков.
⚠️ В тексте всегда дата, а не только «maine»: оператор пытается доставить
сутки, и SMS, дошедшая после визита, не должна вводить в заблуждение.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta

# ---------- события ----------

DAY_BEFORE, SAME_DAY = "day_before", "same_day"
EVENTS = (DAY_BEFORE, SAME_DAY)
HOURS_X = tuple(range(8, 21))       # час напоминания накануне: 08:00…20:00
LEAD_HOURS = (1, 2, 3)              # «în ziua vizitei» — за 1, 2 или 3 часа
PHONE_LINE_KEY = "phone_line"

# ---------- настройки клиники: clinic.json › sms ----------

STANDARD, SCURT, OFICIAL, CALD = "standard", "scurt", "oficial", "cald"
CUSTOM = "propriu"                  # личный текст клиники — по заявке, из админки
VARIANTS = (STANDARD, SCURT, OFICIAL, CALD)
VARIANT_LABEL = {STANDARD: "Standard", SCURT: "Scurt", OFICIAL: "Oficial", CALD: "Cald",
                 CUSTOM: "Textul clinicii"}

# Умолчания — решения Олега 16.10: накануне в 10:00 включено, в день визита
# за 2 часа выключено, строки телефона нет.
DEFAULTS = {DAY_BEFORE: {"on": True, "hour": 10, "variant": STANDARD},
            SAME_DAY: {"on": False, "hours": 2, "variant": STANDARD},
            PHONE_LINE_KEY: False}


def _int_in(value, allowed, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value in allowed else default


def settings(raw) -> dict:
    """Переключатели клиники из `clinic.json › sms` — нормализованные: чего нет
    или что кривое, берётся из DEFAULTS. Форма одна на цикл, экран и сохранение:
    {day_before: {on, hour, variant}, same_day: {on, hours, variant}, phone_line}."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for ev in EVENTS:
        d = raw.get(ev) if isinstance(raw.get(ev), dict) else {}
        base = DEFAULTS[ev]
        variant = d.get("variant")
        entry = {"on": bool(d.get("on", base["on"])),
                 "variant": variant if variant in VARIANTS or variant == CUSTOM else base["variant"]}
        if ev == DAY_BEFORE:
            entry["hour"] = _int_in(d.get("hour"), HOURS_X, base["hour"])
        else:
            entry["hours"] = _int_in(d.get("hours"), LEAD_HOURS, base["hours"])
        out[ev] = entry
    out[PHONE_LINE_KEY] = bool(raw.get(PHONE_LINE_KEY, DEFAULTS[PHONE_LINE_KEY]))
    return out


def any_on(s: dict) -> bool:
    return any(s[ev]["on"] for ev in EVENTS)


# ---------- тексты ----------

PLACEHOLDERS = ("clinica", "ziua", "data", "ora", "telefon")
# без них текст не текст: клинику пациент узнаёт только по названию в теле
# (пока отправитель — общее «DentPilot»), а дата и час — сама суть напоминания
REQUIRED = ("clinica", "data", "ora")
LANGS = ("ro", "ru")

# `{clinica}` — подпись клиники: «Clinica X», а если название уже содержит
# слово (Clinica Test, Clinică Dr. Pop, Dental Clinic) — как есть, иначе
# «Clinica Clinica Test» (`clinic_label`).
TEXTS = {
    "ro": {
        # образец Олега (15–16.10) — умолчание
        STANDARD: ("Buna ziua! {clinica} va reaminteste ca {ziua}, {data}, "
                   "la ora {ora} aveti o programare la noi. O zi buna!"),
        SCURT: "{clinica}: programare {ziua}, {data}, la ora {ora}.",
        OFICIAL: ("Buna ziua. {clinica} va informeaza: aveti programare "
                  "{ziua}, {data}, ora {ora}."),
        CALD: ("Buna ziua! Va asteptam {ziua}, {data}, la ora {ora}, la {clinica}. "
               "Va dorim o zi frumoasa!"),
    },
    "ru": {
        STANDARD: "{clinica}: ждём вас {ziua}, {data}, в {ora}.",
        SCURT: "{clinica}: запись {ziua}, {data}, в {ora}.",
        OFICIAL: "{clinica} напоминает: запись {ziua}, {data}, в {ora}.",
        CALD: "Ждём вас {ziua}, {data}, в {ora}. {clinica}",
    },
}
CLINIC_WORD = {"ro": "Clinica", "ru": "Клиника"}
# строка «телефон для отмены» — галочкой клиники, у готовых вариантов
PHONE_LINE = {"ro": "\nAnulare: {telefon}", "ru": "\nОтмена: {telefon}"}

TODAY = {"ro": "astazi", "ru": "сегодня"}
TOMORROW = {"ro": "maine", "ru": "завтра"}
# ⚠️ Свой формат дня, а не `eng.day_label`: тот даёт «Sâ» с диакритикой
WEEKDAY = {"ro": ("luni", "marti", "miercuri", "joi", "vineri", "sambata", "duminica"),
           "ru": ("в понедельник", "во вторник", "в среду", "в четверг", "в пятницу",
                  "в субботу", "в воскресенье")}

# Пределы, на которых прогон держит «один сегмент» (test_sms): румынский — на
# названии до 30 знаков, с самым длинным днём и строкой телефона; русский — на
# названии до 12 знаков без строки телефона. Длиннее — предпросмотр в Setări
# называет число сегментов словами, а не молча.
NAME_MAX = {"ro": 30, "ru": 12}
CUSTOM_MAX = 400                    # личный текст длиннее — не текст, а ошибка

_PH = re.compile(r"\{([A-Za-z_]+)\}")
# Знаки, которые люди пишут в названии и телефоне, а GSM-7 не знает
_FOLD = str.maketrans({"ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
                       "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ş": "S", "Ț": "T", "Ţ": "T",
                       "„": '"', "”": '"', "“": '"', "«": '"', "»": '"', "’": "'", "‘": "'",
                       "—": "-", "–": "-", "‐": "-", " ": " ", "…": "..."})


def fold(s: str) -> str:
    """Латиница без диакритики и без типографских знаков — для румынского текста.
    Кириллица и прочее остаются как есть: их честно покажет счёт сегментов."""
    out = []
    for c in (s or "").translate(_FOLD):
        d = unicodedata.normalize("NFKD", c)
        out.append(d[0] if len(d) > 1 and d[0].isascii()
                   and all(unicodedata.combining(x) for x in d[1:]) else c)
    return " ".join("".join(out).split())


def clinic_label(name: str, lang: str) -> str:
    """«Clinica X» для текста; название, в котором слово уже есть («Clinica
    Test», «Clinică Dr. Pop», «Dental Clinic»), — как есть."""
    name = " ".join((name or "").split())
    if not name or "clinic" in fold(name).lower() or "клиник" in name.lower():
        return name
    return f"{CLINIC_WORD.get(lang, CLINIC_WORD['ro'])} {name}"


def placeholders(template: str) -> set[str]:
    return set(_PH.findall(template or ""))


def custom_ok(template) -> bool:
    """Годен ли личный текст клиники: строка, подстановки из белого списка,
    клиника, дата и час на месте. Иначе — готовый вариант (сервер текст
    проверяет до программы, это вторая страховка)."""
    if not isinstance(template, str) or not template.strip() or len(template) > CUSTOM_MAX:
        return False
    ph = placeholders(template)
    return ph <= set(PLACEHOLDERS) and set(REQUIRED) <= ph


def render(template: str, values: dict) -> str:
    """Подстановка ОДНИМ проходом: значение (название клиники) со скобками внутри
    второй раз не разбирается; незнакомое имя остаётся как есть."""
    return _PH.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def day_word(lang: str, visit_day: date, on_day: date) -> str:
    """«astazi» / «maine» / день недели — от дня ОТПРАВКИ: визит в понедельник
    при напоминании в пятницу — «luni», а не «maine»."""
    delta = (visit_day - on_day).days
    if delta == 0:
        return TODAY[lang]
    if delta == 1:
        return TOMORROW[lang]
    return WEEKDAY[lang][visit_day.weekday()]


def template_for(lang: str, variant: str, phone_line: bool, custom: dict | None = None) -> str:
    """Шаблон: личный текст клиники, если выбран и годен на этом языке, иначе
    готовый вариант (неизвестный — стандартный). Строка телефона — только у
    готовых: личный текст решает сам, есть ли в нём {telefon}."""
    lang = lang if lang in LANGS else "ro"
    own = (custom or {}).get(lang) if variant == CUSTOM else None
    if custom_ok(own):
        return own
    tpl = TEXTS[lang].get(variant) or TEXTS[lang][STANDARD]
    return tpl + PHONE_LINE[lang] if phone_line else tpl


def text(lang: str, variant: str, *, clinic: str, phone: str, phone_line: bool,
         starts: datetime, on_day: date, custom: dict | None = None) -> str:
    """Готовая SMS. `starts` — начало визита по часам клиники, `on_day` — день
    отправки. Без телефона клиники строки отмены нет."""
    lang = lang if lang in LANGS else "ro"
    tpl = template_for(lang, variant, phone_line and bool((phone or "").strip()), custom)
    name, tel = clinic_label(clinic, lang), (phone or "").strip()
    if lang == "ro":
        name, tel = fold(name), fold(tel)
    return render(tpl, {"clinica": name, "ziua": day_word(lang, starts.date(), on_day),
                        "data": starts.strftime("%d.%m"), "ora": starts.strftime("%H:%M"),
                        "telefon": tel})


def idem(appt_id: int, kind: str, starts_utc: str) -> str:
    """Ключ повтора: `appt:{id}:{kind}:{starts_at}`. Перенос — другое начало и
    другой ключ: новое напоминание без дубля прежнего; вторая копия программы
    той же клиники (старый ПК) даёт тот же ключ — сервер второй SMS не пошлёт."""
    return f"appt:{int(appt_id)}:{kind}:{starts_utc}"


# ---------- час отправки ----------

QUIET_START, QUIET_END = 21, 8      # шлём только 08:00–21:00 по часам клиники
SAME_DAY_FLOOR = timedelta(hours=1)  # «за N часов» в тихие часы → в 08:00, если до визита ≥ 1 ч
SAME_DAY_LATE = timedelta(minutes=30)  # позже, чем за полчаса до начала, — уже не напоминание
SEND_DAY_BACK = 14                  # дальше рабочий день не ищем: клиника в отпуске


def awake(now: datetime) -> bool:
    """Не тихие часы: 08:00 ≤ час < 21:00 (часы клиники)."""
    return QUIET_END <= now.hour < QUIET_START


def send_day(visit_day: date, is_open) -> date:
    """Последний рабочий день клиники перед визитом (`is_open(день)` — часы из
    clinic.json): визит в понедельник — пятница, а не воскресенье, когда
    клиника закрыта и программа выключена."""
    d = visit_day - timedelta(days=1)
    for _ in range(SEND_DAY_BACK):
        if is_open(d):
            return d
        d -= timedelta(days=1)
    return visit_day - timedelta(days=1)


def window(event: str, starts: datetime, created: datetime, *, hour: int = 10,
           hours: int = 2, is_open=lambda d: True) -> tuple[datetime, datetime] | None:
    """Окно отправки [с, до) или None — «не слать». Все моменты — по часам
    клиники (aware). Тихие часы внутри окна ждёт цикл (`awake`).

    Накануне: в последний рабочий день перед визитом, с часа X. Запись сделана
    позже — сразу при записи, если до 21:00 того же дня; записан в день визита
    — накануне не бывает. Окно кончается в 21:00: утром следующего дня «maine»
    было бы уже неправдой.

    В день визита: за N часов. Попадает до 08:00 — в 08:00, если до визита ещё
    ≥ 1 ч, иначе не слать; запись меньше чем за N часов до визита — не слать;
    позже, чем за полчаса до начала, — тоже нет."""
    tz = starts.tzinfo
    visit_day = starts.date()
    if event == DAY_BEFORE:
        start = datetime.combine(send_day(visit_day, is_open), time(hour), tzinfo=tz)
        if created > start:
            start = created
        if start.date() >= visit_day:
            return None
        end = datetime.combine(start.date(), time(QUIET_START), tzinfo=tz)
        return (start, end) if start < end else None
    if event == SAME_DAY:
        due = starts - timedelta(hours=hours)
        if created > due:
            return None
        first = datetime.combine(visit_day, time(QUIET_END), tzinfo=tz)
        if due < first:
            if starts - first < SAME_DAY_FLOOR:
                return None
            due = first
        end = min(starts - SAME_DAY_LATE, datetime.combine(visit_day, time(QUIET_START), tzinfo=tz))
        return (due, end) if due < end else None
    return None
