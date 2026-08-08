"""Справочник вопросов анамнеза — отдельным модулем, потому что подписи нужны
ТРЁМ потребителям: фише (routes.py), печатной 043/e (fisa043.py) и выгрузке
по 195-му (export.py). Держать их в routes.py нельзя: export.py импортируется
самим routes.py, и обратный импорт замкнул бы круг.

Опросник — то, что меняет ТАКТИКУ приёма (анестезия, кровотечение,
инфекционный контроль), а не медицинская карта целиком: её клиника не ведёт.
Ключ хранится в базе строкой, подписи живут здесь — добавить вопрос значит
дописать по строке в оба языка, миграция не нужна.

⚠️ Наборы ключей ro и ru обязаны совпадать: подпись ищется по ключу, и
пропущенный перевод молча напечатает ключ вместо вопроса.
"""
from __future__ import annotations

FLAGS = {
    "ro": {
        "cardio": "Boli cardiovasculare / hipertensiune",
        "diabet": "Diabet zaharat",
        "coagulare": "Tulburări de coagulare / anticoagulante",
        "hepatita": "Hepatită",
        "hiv": "HIV / SIDA",
        "tuberculoza": "Tuberculoză",
        "epilepsie": "Epilepsie",
        "astm": "Astm bronșic",
        "renale": "Boli renale",
        "tiroida": "Afecțiuni tiroidiene",
        "sarcina": "Sarcină / alăptare",
        "fumat": "Fumător",
    },
    "ru": {
        "cardio": "Сердечно-сосудистые заболевания / гипертония",
        "diabet": "Сахарный диабет",
        "coagulare": "Нарушения свёртываемости / антикоагулянты",
        "hepatita": "Гепатит",
        "hiv": "ВИЧ / СПИД",
        "tuberculoza": "Туберкулёз",
        "epilepsie": "Эпилепсия",
        "astm": "Бронхиальная астма",
        "renale": "Заболевания почек",
        "tiroida": "Заболевания щитовидной железы",
        "sarcina": "Беременность / кормление",
        "fumat": "Курит",
    },
}

# (ключ поля, подпись в фише, подсказка-плейсхолдер) — панель только румынская
TEXTS = (
    ("boli", "Alte boli suportate / concomitente", "ex. ulcer gastric operat 2019"),
    ("medicamente", "Medicamente administrate curent", "denumire, doză"),
    ("alergii", "Alergii (medicamente, materiale)", "ex. penicilină, latex"),
    ("anestezie", "Reacții la anestezice", "ex. lipotimie la lidocaină"),
)

# подписи свободных полей на печатном листе — по-русски тоже
TEXT_LABELS = {
    "ro": {"boli": "Alte boli", "medicamente": "Medicamente",
           "alergii": "Alergii", "anestezie": "Reacții la anestezice"},
    "ru": {"boli": "Другие заболевания", "medicamente": "Лекарства",
           "alergii": "Аллергии", "anestezie": "Реакции на анестетики"},
}


def labels(lang: str = "ro") -> dict:
    return FLAGS.get(lang) or FLAGS["ro"]


def marked(flags: str, lang: str = "ro") -> list[str]:
    """Подписи отмеченного, в порядке справочника (а не в порядке галочек)."""
    have = {x for x in (flags or "").split(",") if x}
    lab = labels(lang)
    return [v for k, v in lab.items() if k in have]
