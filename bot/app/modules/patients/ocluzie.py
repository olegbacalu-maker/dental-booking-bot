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

# ряды дуги — те же, что у модели одонтограммы (одно место правды); модуль
# одонтограммы про прикус не знает, круга нет
from .odontogram import FDI_LOWER, FDI_MILK_LOWER, FDI_MILK_UPPER, FDI_UPPER

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


# ---------- зубы из свободного текста (07.11, прикус в 3D, этап 2) ----------

# Пары рядов «верх — низ»: зуб и его антагонист стоят под ОДНИМ индексом
# (13 ↔ 43, 26 ↔ 36, 53 ↔ 83). Постоянный и молочный ряды не смешиваются.
_ROWS = ((FDI_UPPER, FDI_LOWER), (FDI_MILK_UPPER, FDI_MILK_LOWER))
_WHERE = {n: (pair, side, i) for pair in _ROWS for side, row in enumerate(pair)
          for i, n in enumerate(row)}
# номер — ровно две цифры (не кусок «123» и не «3» из «3 mm»); диапазон —
# дефис, короткое или длинное тире, пробелы вокруг допустимы
_CHUNK = re.compile(r"(?<!\d)(\d{2})(?!\d)(?:\s*[-–—]\s*(\d{2})(?!\d))?")


def _span(row: list[int], i: int, j: int) -> list[int]:
    lo, hi = (i, j) if i <= j else (j, i)
    return row[lo:hi + 1]


def teeth_of(text: str | None) -> list[int]:
    """Зубы, названные в графе «încrucișată» / «deschisă», — ОДНО правило для
    сцены (клиент своего разбора не заводит). Текст свободный: врач писал его
    для бумаги, поэтому незнакомые куски молча пропускаются, а не отказ.

    - «16, 46» — перечисление;
    - «13–23», «34-36», «12—22» — диапазон ПО ДУГЕ (ряды модели
      одонтограммы), а не по числам: 13–23 идёт через 11/21;
    - диапазон через обе челюсти («13–43», «16–33») — участок прикуса: на
      каждой челюсти тот же отрезок от зуба до антагониста другого конца
      (13–43 → 13 и 43; 13–33 → 13…23 и 43…33);
    - номер не из FDI, молочный с постоянным в одном диапазоне — пропуск
      куска целиком (полдиапазона хуже, чем ничего).
    Порядок — как названо, повторы убраны."""
    out: list[int] = []
    for m in _CHUNK.finditer(text or ""):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else None
        if a not in _WHERE or (b is not None and b not in _WHERE):
            continue
        pa, sa, ia = _WHERE[a]
        if b is None:
            got = [a]
        else:
            pb, sb, ib = _WHERE[b]
            if pa is not pb:
                continue
            if sa == sb:
                got = _span(pa[sa], ia, ib)
            else:
                got = _span(pa[sa], ia, ib) + _span(pa[sb], ia, ib)
        out += [n for n in got if n not in out]
    return out
