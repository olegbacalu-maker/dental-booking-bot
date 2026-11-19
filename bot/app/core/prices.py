"""Цена услуги из прайса для позиции плана.

Прайс хранит цену СТРОКОЙ, как её написала клиника («900 MDL», «1200–1800 MDL»,
«de la 500»). Позиции плана нужна одна сумма, и выбрать её из диапазона может
только человек: среднее из «1200–1800» в плане лечения — цена, которой нет в
прайсе. Поэтому число отдаётся, только когда строка — ровно одна сумма, а всё
остальное возвращается подсказкой, как записано.
"""
from __future__ import annotations

import re

from .. import engine as eng

PRICE_MAX = 1_000_000

# пробел, неразрывный пробел или точка между цифрами перед ровно тремя цифрами —
# разделитель тысяч («1 200», «9.000»), а не граница двух чисел
_THOUSANDS = re.compile(r"(?<=\d)[   .](?=\d{3}(?!\d))")
# одна сумма: число и, может быть, название валюты — и больше ничего
_EXACT = re.compile(r"(\d+)\s*(?:mdl|lei|leu|l|лей|леев|лея)?\.?", re.IGNORECASE)


def parse(raw) -> tuple[int | None, str]:
    """(сумма, подсказка) из строки прайса. Сумма — только у строки из одного
    числа; иначе None и сама строка подсказкой. Пустая цена — (None, "")."""
    if isinstance(raw, dict):
        raw = raw.get("ro", "")
    text = " ".join(str(raw or "").split())
    if not text:
        return None, ""
    m = _EXACT.fullmatch(_THOUSANDS.sub("", text))
    if m and int(m.group(1)) <= PRICE_MAX:
        return int(m.group(1)), ""
    return None, text


def of_service(service_id: str) -> tuple[int | None, str]:
    """Цена услуги прайса по её ключу на сейчас; незнакомый ключ — (None, "")."""
    for svc in eng.CONFIG.get("services", []):
        if svc.get("id") == service_id:
            return parse(svc.get("price", ""))
    return None, ""


def options() -> list[dict]:
    """Услуги прайса для форм плана: ключ, имя, сумма (или None) и подсказка."""
    out = []
    for svc in eng.CONFIG.get("services", []):
        price, hint = parse(svc.get("price", ""))
        out.append({"id": svc["id"], "label": svc["ro"], "price": price, "price_hint": hint})
    return out
