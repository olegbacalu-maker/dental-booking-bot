"""Проверки полей профиля — одни на правку фиши, «Pacient nou» и импорт:
правило, записанное в двух местах, расходится молча."""
from __future__ import annotations

import re
from datetime import date

IDNP_RE = re.compile(r"[0-9]{13}")


def birth_date(text: str) -> date | None:
    """Дата рождения из ISO-строки; None — не дата, раньше 1900 или в будущем."""
    try:
        d = date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None
    return d if 1900 <= d.year and d <= date.today() else None


def idnp_shape(text: str) -> bool:
    return bool(IDNP_RE.fullmatch(text or ""))


def idnp_check_digit(text: str) -> bool:
    """Контрольная цифра по весам 7-3-1. Правило не подтверждено на настоящих
    номерах, поэтому по нему только помечают, не отказывают."""
    if not idnp_shape(text):
        return False
    return sum(int(c) * (7, 3, 1)[i % 3] for i, c in enumerate(text[:12])) % 10 == int(text[12])
