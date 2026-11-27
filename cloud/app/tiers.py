"""Варианты абонемента: DentPilot Basic — без модуля SMS, DentPilot Plus — с модулем SMS,
DentPilot Premium — Plus и календари врачей в Google (условия § 3, 4.2, 4.5, 16). Клиника
выбирает вариант при каждой оплате (/plata, кабинет); пробный месяц — всегда Plus.

⭐ Вариант живёт ТОЛЬКО на сервере. В файле лицензии второго плана нет и не будет:
программа знает `trial`/`standard` и новый план сочла бы негодным. Модуль SMS
включает и выключает ответ /v1/sms/* — код `sms_basic` (sms.blocked); ручной
тумблер карточки (`sms_off`) — другое состояние, для исключений. Связь с Google и
календари врачей программа узнаёт датами прав в файле (`features`), не вариантом.

Что даёт вариант — только множествами ниже (`SMS_TIERS`, `GCAL_TIERS`, `GDOC_TIERS`), не
сравнением с одним вариантом: «Plus или иначе Basic» у третьего варианта молча выключает то,
что он включает. Сравнение `== / != tiers.PLUS|BASIC|PREMIUM` вне этого файла держит
`test_tiers.suite_sets`.

Одно правило на всех (страница оплаты, кабинет, админка, ежедневная задача, confirm):
- `current(sub)` — вариант, в котором идёт подписка: пробный = Plus, иначе
  `subscriptions.tier` (подписки до шага 15 миграций — Plus);
- `price(sub, tier)` — цена месяца: ВСЕГДА прайс варианта из cloud.env, и у оплаченной
  подписки тоже: `subscriptions.price` — запись, по чему выставлено и оплачено, не
  источник цены. 0 = вариант не продаётся;
- `module_on(sub, now)` — работает ли модуль SMS: пробный и варианты с SMS — да; без SMS —
  пока не прошёл `sms_until`, конец периода, который шёл при уходе с варианта с SMS
  (§ 4.2: «rămâne pornit până la sfârșitul perioadei în curs»), потом нет;
- `gcal_until(sub, end, now)` — связь с аккаунтом Google (право `gcal`) тем же правилом,
  что модуль SMS, но датой в файле лицензии: программа держит связь, пока дата не прошла;
- `gdoc_until(sub, end, now)` — календари врачей в Google (право `gcal_doctor`): у Premium —
  до конца файла; после ухода с Premium — до `gdoc_until` подписки, конца периода, шедшего
  при уходе; потом программа убирает будущие приёмы из календарей.
Цен в репозитории нет: DP_PRICE_BASIC / DP_PRICE_PLUS / DP_PRICE_PREMIUM в cloud.env.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import config, db

BASIC, PLUS, PREMIUM = "basic", "plus", "premium"
TIERS = (BASIC, PLUS, PREMIUM)
NAME = {BASIC: "DentPilot Basic", PLUS: "DentPilot Plus", PREMIUM: "DentPilot Premium"}
WHAT = {BASIC: "fără modulul SMS", PLUS: "cu modulul SMS",                       # как в условиях § 4.1
        PREMIUM: "cu modulul SMS, calendarele medicilor în Google și răspunsul pacientului prin link"}
WHAT_RU = {BASIC: "без модуля SMS", PLUS: "с модулем SMS",                       # админка
           PREMIUM: "с модулем SMS, календарями врачей в Google и ответом пациента по ссылке"}
SMS_TIERS = frozenset({PLUS, PREMIUM})       # модуль SMS
GCAL_TIERS = frozenset({PLUS, PREMIUM})      # связь с аккаунтом Google клиники (право gcal)
GDOC_TIERS = frozenset({PREMIUM})            # календари врачей в Google (право gcal_doctor)


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
    подписки — своей цены у подписки нет. `sub` остаётся в подписи: правило одно на всех, и
    вызывающим не надо знать, что подписка не участвует."""
    return list_price(tier)


def offered(sub: sqlite3.Row | None) -> list[str]:
    """Варианты, которые этой клинике можно оплатить сейчас (по порядку TIERS)."""
    return [t for t in TIERS if price(sub, t) > 0]


def pick(sub: sqlite3.Row | None, asked: str = "") -> str:
    """Вариант формы: названный, если продаётся; иначе текущий, если продаётся; иначе ближайший
    продаваемый ниже текущего — клиника на Premium без прайса видит отмеченным Plus, а не Basic, и не
    теряет модуль SMS ошибкой одного клика; иначе первый продаваемый; ничего не продаётся — ''."""
    sold = offered(sub)
    cur = current(sub)
    for t in (asked, cur):
        if t in sold:
            return t
    below = [t for t in sold if TIERS.index(t) < TIERS.index(cur)]
    return below[-1] if below else (sold[0] if sold else "")


def _column(sub: sqlite3.Row | None, name: str) -> datetime | None:
    if sub is None or name not in sub.keys():
        return None
    return db.parse_ts(sub[name])


def sms_until(sub: sqlite3.Row | None) -> datetime | None:
    """До какого момента модуль SMS работает после ухода с варианта с SMS (колонка подписки)."""
    return _column(sub, "sms_until")


def gdoc_left(sub: sqlite3.Row | None) -> datetime | None:
    """До какого момента календари врачей работают после ухода с Premium (колонка подписки)."""
    return _column(sub, "gdoc_until")


def module_on(sub: sqlite3.Row | None, now: datetime) -> bool:
    """Работает ли модуль SMS по варианту (лицензию и тумблер проверяет sms.blocked)."""
    if current(sub) in SMS_TIERS:
        return True
    until = sms_until(sub)
    return until is not None and now < until


def _right(own: bool, left: datetime | None, end: datetime, now: datetime) -> datetime | None:
    """Дата права для файла до `end`: вариант даёт право — `end`; иначе остаток после ухода,
    но не дальше `end`; прошло или нет — None."""
    until = end if own else left
    if until is None:
        return None
    until = min(until, end)
    return until if until > now else None


def gcal_until(sub: sqlite3.Row | None, end: datetime, now: datetime) -> datetime | None:
    """Дата права gcal для файла, действующего до `end` (льгота включительно): пробный, Plus и
    Premium — `end`; Basic — `sms_until`, но не дальше `end`; права нет — None. `sub` — подписка
    с планом выдаваемого файла: пробный всегда Plus (`current`)."""
    return _right(current(sub) in GCAL_TIERS, sms_until(sub), end, now)


def gdoc_until(sub: sqlite3.Row | None, end: datetime, now: datetime) -> datetime | None:
    """Дата права gcal_doctor для файла до `end`: Premium — `end`; ушедшая с Premium — `gdoc_until`
    подписки, но не дальше `end`; пробный (он Plus) и остальные — None."""
    return _right(current(sub) in GDOC_TIERS, gdoc_left(sub), end, now)


def label(tier: str | None) -> str:
    return NAME.get(tier or "", "")
