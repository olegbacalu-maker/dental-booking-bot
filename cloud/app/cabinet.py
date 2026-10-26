"""Клиники одного кабинета (26.10.2026): филиал = ещё одна клиника в том же кабинете.

Слово Олега 26.10: «если клиника имеет филиалы значит пускай платит … на каждый отдельная
лицензия, один кабинет админ» → «филиал просто добавляет из админки новую клинику и все».
Отдельной сущности «сеть» нет: кабинет — это учётные записи входа (`account_clinics`) и
клиники, к которым у них вход. У каждой клиники кабинета всё своё — лицензия, пробный,
подписка, ноты, компьютеры, остаток SMS; общие только вход, общая нота (payments.CABINET)
и имя отправителя SMS (sms.name_owner — у главной клиники).

`of(con, clinic_id)` — клиники, с которыми эта делит хотя бы один вход, включая её саму, по
дате заведения (в одну секунду — по порядку заведения, rowid); первая — ГЛАВНАЯ клиника
кабинета. ⛔ Второй ключ — rowid, не id: id случаен, и при равной секунде (метка — до секунды)
главной стала бы случайная клиника (26.10: так покраснел прогон на main). rowid таблицы с
текстовым ключом — порядок вставки; VACUUM, VACUUM INTO и копия backup API его сохраняют
(проверено 26.10, SQLite 3.45). Один шаг по связям, а не замыкание: у второго человека кабинета (администратор с
входом только в главную) главная та же.
⚠️ Олег отвязал единственный вход — кабинета больше нет: каждая клиника сама по себе, филиал
шлёт SMS от общего имени DentPilot, пока вход не привяжут снова (разбор — cloud.md).

Здесь только чтение базы: модуль зовут и кабинет (account), и SMS (sms), и оплата —
импорт любого из них отсюда замкнул бы круг.
"""
from __future__ import annotations

import sqlite3

_OF = """SELECT DISTINCT c.* FROM clinics c
         WHERE c.id = ? OR c.id IN (SELECT b.clinic_id FROM account_clinics a
                                    JOIN account_clinics b ON b.account_id = a.account_id
                                    WHERE a.clinic_id = ?)
         ORDER BY c.created_at, c.rowid"""


def of(con: sqlite3.Connection, clinic_id: str) -> list:
    """Клиники кабинета этой клиники (она сама — тоже), главная первой."""
    return con.execute(_OF, (clinic_id, clinic_id)).fetchall()


def ids(con: sqlite3.Connection, clinic_id: str) -> set[str]:
    return {r["id"] for r in of(con, clinic_id)}


def main_of(con: sqlite3.Connection, clinic_id: str) -> sqlite3.Row | None:
    """Главная клиника кабинета: заведённая первой. Без кабинета — она сама."""
    rows = of(con, clinic_id)
    return rows[0] if rows else None


def of_account(con: sqlite3.Connection, account_id: str) -> list:
    """Клиники, к которым у учётной записи вход, по дате заведения."""
    return con.execute("SELECT c.* FROM account_clinics a JOIN clinics c ON c.id = a.clinic_id "
                       "WHERE a.account_id=? ORDER BY c.created_at, c.rowid", (account_id,)).fetchall()


def accounts_of(con: sqlite3.Connection, clinic_id: str) -> list:
    """Учётные записи с входом в клинику, по дате заведения."""
    return con.execute("SELECT a.* FROM account_clinics x JOIN accounts a ON a.id = x.account_id "
                       "WHERE x.clinic_id=? ORDER BY a.created_at", (clinic_id,)).fetchall()
