"""Прикус («Ocluzia», 26.10.2026, волна 3 одонтограммы) — справочник и ОДНА
строка для бумаги. Отдельным модулем по той же причине, что `anamneza.py`:
подписи нужны фише (routes.py), печатной 043/e (fisa043.py) и выгрузке по
195-му (export.py); export.py импортируется самим routes.py, и обратный
импорт замкнул бы круг.

Ступень 0 разведки ортодонтии (слово Олега 25.10: «графа «Ocluzia» в листе
043/e; я думаю пока без ортодонта»): запись осмотра прикуса — класс по Энглю
по сторонам, overjet/overbite в мм, перекрёстный и открытый прикус словами,
средняя линия, заметка. ⛔ Без ортокарты, аппаратов, журнала дуг,
цефалометрии и индексов. ⛔ Никаких норм и выводов: только то, что врач
записал; пусто = «не записано», а не «норма» и не «нет».

Одна запись на пациента (upsert, как анамнез; координатор 26.10: ортокарты
и осмотров списком не будет). История — летописью: при перезаписи прежняя
строка уходит в `log_event` готовой (`line()`), разбирать её назад никто не
станет.

⚠️ Термины Angle / overjet / overbite НЕ переводятся на русском листе (память
`print_docs_i18n`: как коды одонтограммы — одинаковы на обоих листах);
переводятся подписи и единицы.
"""
from __future__ import annotations

import re

# Классы по Энглю — ровно как пишут в карте; '' = не оценивал. Белый список
# сервера: незнакомое значение — отказ с полем, а не молчаливое ''.
ANGLE = ("I", "II/1", "II/2", "III")
# Сторона смещения средней линии; '' = не записано.
SIDES = ("dreapta", "stanga")

# Потолки свободных полей (символов): зубы/стороны/область — короткие,
# заметка — как у анамнеза
TEXT_MAX = {"incrucisata": 100, "deschisa": 100, "nota": 500, "doctor": 80}

_MM = re.compile(r"^-?\d{1,2}([.,]\d{1,2})?$")


def norm_mm(value: str) -> str | None:
    """Миллиметры как прислали: «3», «3,5», «3.5», «-2» (обратное перекрытие
    бывает отрицательным) → строка с точкой; пусто → ''; иное → None (отказ).
    Числом не храним: «2.5» обязано напечататься как «2.5», а не «2.50»."""
    v = (value or "").strip().replace(",", ".")
    if not v:
        return ""
    if not _MM.match(v):
        return None
    return v


# Подписи кусков строки — на языке листа. Ключи = поля записи.
_T = {
    "ro": {
        "angle": "Angle", "dr": "dr.", "st": "stg.",
        "overjet": "overjet", "overbite": "overbite", "mm": "mm",
        "incrucisata": "încrucișată", "deschisa": "deschisă",
        "mediana": "linia mediană", "spre": "spre",
        "dreapta": "dreapta", "stanga": "stânga",
        "neevaluat": "neevaluat",
    },
    "ru": {
        "angle": "Angle", "dr": "спр.", "st": "сл.",
        "overjet": "overjet", "overbite": "overbite", "mm": "мм",
        "incrucisata": "перекрёстный", "deschisa": "открытый",
        "mediana": "средняя линия", "spre": "",
        "dreapta": "вправо", "stanga": "влево",
        "neevaluat": "не оценивал",
    },
}

# Подписи формы фиши — панель только румынская (как TEXTS анамнеза)
FORM = {
    "angle": [{"id": "", "label": "neevaluat"}] + [{"id": a, "label": a} for a in ANGLE],
    "sides": [{"id": "", "label": "—"}, {"id": "dreapta", "label": "dreapta"},
              {"id": "stanga", "label": "stânga"}],
}


# Поля СОДЕРЖАНИЯ записи — без врача, автора и дат: по ним решается «пусто»
# и собирается строка. ⚠️ Строка базы несёт и patient_id (int), и даты —
# перебирать «все ключи» нельзя.
CONTENT = ("angle_dr", "angle_st", "overjet", "overbite", "incrucisata",
           "deschisa", "mediana_mm", "mediana_spre", "nota")


def is_empty(rec: dict | None) -> bool:
    """Запись без единого заполненного поля (врач — не содержание)."""
    if not rec:
        return True
    return not any((rec.get(k) or "").strip() for k in CONTENT)


def line(rec: dict | None, lang: str = "ro") -> str:
    """Запись прикуса одной строкой: только заполненные куски через « · ».
    Одно правило на три места — 043/e, сводка в фише, выгрузка и летопись.
    Пусто целиком → '' (лист печатает прежнюю черту)."""
    if is_empty(rec):
        return ""
    t = _T.get(lang) or _T["ro"]
    r = {k: (rec.get(k) or "").strip() for k in CONTENT}
    parts = []
    a_dr, a_st = r.get("angle_dr", ""), r.get("angle_st", "")
    if a_dr or a_st:
        if a_dr == a_st:
            parts.append(f"{t['angle']} {a_dr}")
        else:
            sides = [f"{t['dr']} {a_dr}" if a_dr else "",
                     f"{t['st']} {a_st}" if a_st else ""]
            parts.append(f"{t['angle']} " + ", ".join(x for x in sides if x))
    for k in ("overjet", "overbite"):
        if r.get(k):
            parts.append(f"{t[k]} {r[k]} {t['mm']}")
    for k in ("incrucisata", "deschisa"):
        if r.get(k):
            parts.append(f"{t[k]}: {r[k]}")
    mm, spre = r.get("mediana_mm", ""), r.get("mediana_spre", "")
    if mm or spre:
        side = t.get(spre, spre) if spre else ""
        txt = " ".join(x for x in (
            f"{mm} {t['mm']}" if mm else "",
            f"{t['spre']} {side}".strip() if side else "") if x)
        parts.append(f"{t['mediana']}: {txt}")
    if r.get("nota"):
        parts.append(r["nota"])
    return " · ".join(parts)
