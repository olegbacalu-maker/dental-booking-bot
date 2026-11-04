"""Слова и форматы, общие для экранов: имена статусов, виды предупреждений, дни
недели, дата человеку, контакты программы, диапазон часов.

⭐ Одно состояние — одно имя, в ОДНОМ словаре. `db` лежит НИЖЕ этого файла и берёт
STATUS_LABEL отложенным импортом внутри функции: на уровне модуля был бы круг.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .. import db
from .. import engine as eng


# Адрес на домене сайта (06.10, слово Олега): Cloudflare пересылает его в
# рабочий ящик, и сменить ящик можно, не трогая ни одной установленной копии.
FEEDBACK_EMAIL = "contact@dentpilot.md"
SUPPORT_PHONE = "+373 60 508 048"     # страница активации лицензии; менять вместе с сайтом
SITE_URL = "https://dentpilot.md"     # знак в уголке ведёт сюда — в системном браузере

# Единый диапазон часов для ВСЕХ выпадающих списков: часы клиники, обед,
# личное окно врача. Раньше их было три разных (0-23 / 6-21 / 7-23) — клиника
# видела в соседних полях разные наборы без всякой причины.
# 07:00 — самая ранняя разумная смена; потолок 21:00 намеренно выше вечерних
# 19-20, чтобы кабинет с поздним приёмом мог себя настроить.
HOUR_MIN, HOUR_MAX = 7, 21


def _initials(name: str) -> str:
    words = [w for w in re.split(r"[\s.]+", name) if w and w.lower() not in ("dr", "dr.")]
    return "".join(w[0].upper() for w in words[:2]) or "?"


# ⭐ Плашка обязана называть статус ТЕМ ЖЕ словом, что и кнопка, которая его
# ставит. До 08-12 «Finalizat» переводил запись в «a venit» — это словарь
# СТАТИСТИКИ, где «Au venit» = пришли и считаются done ВМЕСТЕ с arrived. В
# журнале он отвечал не на тот вопрос: рядом с нажатой кнопкой «Finalizat»
# стояло «a venit», в повестке та же запись звалась «Finalizat», а в летописи
# пациента (db._STATUS_RO) — «finalizată». Одно состояние, три имени.
# ⭐ 08-16 своего словаря у db не осталось вовсе: он расходился и дальше —
# кнопка ставила «nu a venit», а летопись писала «neprezentare». Теперь
# `db.set_status` берёт слово ОТСЮДА отложенным импортом (на уровне модуля был
# бы круг: layout импортирует db). Новый статус называется здесь и нигде более.
# ⚠️ Отсюда же берёт текст повестка дня (_AG_CLS в schedule/routes.py): новый
# статус называется ЗДЕСЬ и нигде больше.
STATUS_LABEL = {
    # 03.10, слово Олега: «надпись confirmat появляется после того как
    # нажимаешь галочку» в «De confirmat». Запись до звонка — «programată»;
    # «confirmată» даёт только звонок (`status_view` ниже). Код в базе прежний:
    # меняется слово, а не данные. Летопись хранит ГОТОВЫЕ строки, и старые
    # «confirmată» в ней не переписываются — это история, а не оформление.
    "confirmed": "programată",
    # 08-13, вопрос Олега: «a sosit» ставили в момент ПРИХОДА, а называлось
    # это «în cabinet» — статус десять минут утверждал то, чего ещё нет.
    # Теперь конвейер честный: пришёл (waiting) → в кабинете (arrived).
    # ⚠️ «a venit» и «nu a venit» — соседи-близнецы: слово нигде не выводится
    # без цвета/иконки (waiting — фиолетовый, noshow — красный).
    "waiting": "a venit",
    "arrived": "în cabinet",
    "done": "finalizată",
    "noshow": "nu a venit",
    "cancelled": "anulată",
}

# Звонок-подтверждение поверх «programată» (03.10): отметка из «De confirmat»
# (`appt_calls`, в строку дня приезжает колонкой `call_result`). Статус в базе
# звонок не меняет — меняется то, как запись ВЫГЛЯДИТ: ключ вида (класс `.stat
# s-*` и плашки повестки) и слово. У прочих статусов звонок не значит ничего:
# пришедшему «nu răspunde» не нужно.
CALL_LABEL = {"ok": "confirmată", "noanswer": "nu răspunde"}
_CALL_VIEW = {"ok": "called", "noanswer": "noanswer"}


def status_view(status: str, call: str | None = "") -> tuple[str, str]:
    """(ключ вида, слово) статуса записи с учётом звонка-подтверждения.

    ⛔ Одно место на все экраны — повестку обеих оболочек и «Lista zilei»:
    второй расчёт «confirmată или programată» разошёлся бы с первым ровно так,
    как расходились словари статусов (08-12, 08-16)."""
    if status == "confirmed" and call in _CALL_VIEW:
        return _CALL_VIEW[call], CALL_LABEL[call]
    return status, STATUS_LABEL.get(status, status)


# статусы, при которых слот занят — единый источник правды в db/slots.py
LIVE_STATUSES = db.ACTIVE_STATUSES


# Тот же приём, что у STATUS_LABEL, для остальных кодов, которые видит человек.
# Оба словаря переехали сюда из modules/patients/routes.py, когда выгрузке по
# 195-му понадобились те же слова: копия данных обязана быть «в понятной
# форме», а импортировать routes.py она не может — routes.py импортирует её.
# ⚠️ Новый вид предупреждения или новый источник записи называется ЗДЕСЬ.
ALERT_KINDS = {"allergy": "Alergie", "medication": "Medicație",
               "warning": "Atenție", "info": "Info"}
# источник визита: рецепция завела руками или пациент записался сам
SOURCE_LABEL = {"manual": "recepție", "bot": "online", "note": "notă"}


def dmy(value) -> str:
    """Дата человеку — dd.mm.yyyy, а не сырой ISO из базы.

    ⚠️ Переводится в пояс клиники только значение С поясом: `birth_date` и
    `due_date` лежат ГОЛЫМИ датами (текст «1990-05-06»), и astimezone на
    наивном значении подставил бы пояс машины и сдвинул ДЕНЬ.
    Пустое остаётся пустым: печатные листы рисуют на этом месте жёлтый
    пропуск под ручку, а таблицы — прочерк, и решают это они, не эта функция.
    """
    if not value:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(eng.TZ)
        return value.strftime("%d.%m.%Y")
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def _age(birth_year) -> int | None:
    if not birth_year:
        return None
    return datetime.now(eng.TZ).year - int(birth_year)


_DOW_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


_DOW_FULL = {"mon": "Luni", "tue": "Marți", "wed": "Miercuri", "thu": "Joi",
             "fri": "Vineri", "sat": "Sâmbătă", "sun": "Duminică"}


_DOC_STATE_RO = {"activ": "Activ", "concediu": "În concediu", "arhivat": "Arhivat"}


def _doc_hours_text(dk: str) -> str:
    meta = eng.DOCTOR_META.get(dk, {})
    wf, wt = meta.get("work_from"), meta.get("work_to")
    if wf is None and wt is None:
        return "ca clinica"
    a = f"{int(wf):02d}:00" if wf is not None else "deschidere"
    b = f"{int(wt):02d}:00" if wt is not None else "închidere"
    return f"{a}–{b}"
