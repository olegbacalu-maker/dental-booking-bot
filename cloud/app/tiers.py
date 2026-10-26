"""Варианты абонемента (Олег 23.10.2026; условия 23.10.2026 § 3, 4.2, 4.5, 16):
DentPilot Basic — без модуля SMS, DentPilot Plus — с модулем SMS. Клиника выбирает
вариант при каждой оплате (/plata, кабинет); пробный месяц — всегда Plus.

⭐ Вариант живёт ТОЛЬКО на сервере. В файле лицензии второго плана нет и не будет:
программа знает `trial`/`standard` и новый план сочла бы негодным. Модуль SMS
включает и выключает ответ /v1/sms/* — код `sms_basic` (sms.blocked); ручной
тумблер карточки (`sms_off`) — другое состояние, для исключений.

Одно правило на всех (страница оплаты, кабинет, админка, ежедневная задача, confirm):
- `current(sub)` — вариант, в котором идёт подписка: пробный = Plus, иначе
  `subscriptions.tier` (подписки до шага 15 миграций — Plus);
- `price(sub, tier)` — цена месяца: ВСЕГДА прайс варианта из cloud.env, и у оплаченной
  подписки тоже (Олег 26.10: «600 везде»; до того подписка продлевалась по своей цене —
  у живых клиник это были старые 499). `subscriptions.price` — запись, по чему выставлено
  и оплачено, не источник цены. 0 = вариант не продаётся;
- `module_on(sub, now)` — работает ли модуль SMS: пробный и Plus — да; Basic — пока
  не прошёл `sms_until`, конец периода, который шёл, когда клиника перешла на Basic
  (§ 4.2: «rămâne pornit până la sfârșitul perioadei în curs»), потом нет.
⛔ Цен в репозитории нет (Олег 16.10): DP_PRICE_BASIC / DP_PRICE_PLUS в cloud.env.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import config, db

BASIC, PLUS = "basic", "plus"
TIERS = (BASIC, PLUS)
NAME = {BASIC: "DentPilot Basic", PLUS: "DentPilot Plus"}
WHAT = {BASIC: "fără modulul SMS", PLUS: "cu modulul SMS"}       # как в условиях § 4.1
WHAT_RU = {BASIC: "без модуля SMS", PLUS: "с модулем SMS"}       # админка


def list_price(tier: str) -> int:
    """Прайс месяца из cloud.env; 0 — не продаётся."""
    return int(config.PRICES.get(tier) or 0)


def current(sub: sqlite3.Row | None) -> str:
    if sub is None or sub["plan"] == "trial":
        return PLUS
    tier = sub["tier"] if "tier" in sub.keys() else PLUS
    return tier if tier in TIERS else PLUS


def price(sub: sqlite3.Row | None, tier: str) -> int:
    """Цена месяца варианта `tier`; 0 — вариант не продаётся. ⛔ Прайс cloud.env для любой
    подписки — своей цены у подписки нет (Олег 26.10: «600 везде»). `sub` остаётся в
    подписи: правило одно на всех, и вызывающим не надо знать, что подписка не участвует."""
    return list_price(tier)


def offered(sub: sqlite3.Row | None) -> list[str]:
    """Варианты, которые этой клинике можно оплатить сейчас (по порядку Basic, Plus)."""
    return [t for t in TIERS if price(sub, t) > 0]


def pick(sub: sqlite3.Row | None, asked: str = "") -> str:
    """Вариант формы: названный, если продаётся; иначе текущий, если продаётся; иначе
    первый продаваемый; ничего не продаётся — ''."""
    sold = offered(sub)
    for t in (asked, current(sub)):
        if t in sold:
            return t
    return sold[0] if sold else ""


def sms_until(sub: sqlite3.Row | None) -> datetime | None:
    if sub is None or "sms_until" not in sub.keys():
        return None
    return db.parse_ts(sub["sms_until"])


def module_on(sub: sqlite3.Row | None, now: datetime) -> bool:
    """Работает ли модуль SMS по варианту (лицензию и тумблер проверяет sms.blocked)."""
    if current(sub) == PLUS:
        return True
    until = sms_until(sub)
    return until is not None and now < until


def label(tier: str | None) -> str:
    return NAME.get(tier or "", "")
