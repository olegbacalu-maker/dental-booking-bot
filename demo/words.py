"""Срок копии демо словами (07.10): «o oră», «30 de minute» и «час», «30 минут».

Срок держит шлюз (`DEMO_TTL_MIN`), а называют его три места: страницы шлюза
(RO и RU), полоса демо в программе — RO, шлюз передаёт её готовой строкой в
`DENTART_DEMO_TTL`, сама программа срок не считает, — и сайт: там руками
(`site/index.html` и `ru.html`, раздел демо) — при смене срока править и их.
Число словами — только здесь: «30 de minute» в одном месте и «30 minute» в
другом были бы двумя правилами одного срока.
"""
from __future__ import annotations


def _de(n: int) -> str:
    """Румынское «de» после числа: 20 de minute, 101 minute, 120 de minute."""
    r = n % 100
    return " de" if r == 0 or r >= 20 else ""


def ttl_ro(minutes: int) -> str:
    """Для «pentru …» и «după …»: «o oră», «două ore», «30 de minute»."""
    if minutes % 60 == 0:
        h = minutes // 60
        return "o oră" if h == 1 else "două ore" if h == 2 else f"{h}{_de(h)} ore"
    if minutes == 1:
        return "un minut"
    if minutes == 2:
        return "două minute"
    return f"{minutes}{_de(minutes)} minute"


def _ru(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def ttl_ru(minutes: int) -> str:
    """Для «на …»: «час», «2 часа», «30 минут», «21 минуту»."""
    if minutes % 60 == 0:
        h = minutes // 60
        return "час" if h == 1 else f"{h} {_ru(h, 'час', 'часа', 'часов')}"
    return f"{minutes} {_ru(minutes, 'минуту', 'минуты', 'минут')}"
