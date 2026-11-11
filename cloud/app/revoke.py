"""Отзыв лицензии из админки (11.11.2026, Олег: «нужно сделать из админки возможность для отзыва
лицензии» → «Да, А + IDNO»).

⭐ Отзыв — НЕ новое состояние программы, а обычный подписанный файл: `license.issue` выдаёт seq+1
со сроком «сейчас + REVOKE_SECONDS» и без льготы. Программа (любая с 1.36.0) берёт его тем же
суточным запросом, стартом или «Verifică acum» и уходит в «только чтение», как при неуплате:
картотека видна, печать, экспорт и бэкап открыты (закон 195, 043/e хранится 5 лет). Выпуск
программы не нужен. ⛔ Снять токен (как «Скрыть заявку») — не отзыв: программа с принятым файлом
на 401 живёт до конца его срока и льготы.
⛔ Программа требует `issued_at < valid_until <= grace_until` (rsa_verify.parse_claim): срок «ровно
сейчас» она отвергла бы как битый файл и жила бы по прежнему.

Строка клиники помнит отзыв (`revoked_*`, шаг схемы 22). Пока он стоит, закрыто всё, что выдало бы
файл или взяло деньги за срок: ручная «Выдать», нота абонемента (админка, кабинет, страница оплаты,
ссылка из программы, общая нота), продление оплатой, пришедшей по старой ссылке (деньги
записываются, срок — нет), «Adaugă clinică» кабинета, письма ежедневной задачи. SMS — `sms_off`
сразу на сервере. IDNO, ящик и компьютер отозванной клиники остаются заняты (`trial.existing`,
`trial.device_owner` смотрят только `declined_at`) — нового пробного на них нет.

«Вернуть» — файл seq+2 с прежним сроком (последний файл ДО отзыва). Срок уже кончился — только
снять отметку: программа и так была бы в «только чтение», дальше — обычная оплата или «Выдать».
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import cabinet, config, db, license, mail

CONFIRM_WORD = "ОТОЗВАТЬ"               # вписать в форму — подтверждение (Олег 11.11)
REVOKE_SECONDS = 2                      # срок файла отзыва: строго позже выдачи, и сразу прошёл
REASON_MAX = 300
REVOKE_TAG, RESTORE_TAG = "отзыв", "возврат"

# исходы для ?msg= админки (views.MSG)
REVOKED, RESTORED, RESTORED_EXPIRED = "revoked", "restored", "restored_expired"
NEED_REASON, NEED_WORD, NO_FILE, ALREADY, NOT_REVOKED = (
    "revoke_reason", "revoke_word", "revoke_no_file", "revoke_already", "revoke_not")


def is_revoked(row: sqlite3.Row | None) -> bool:
    """Отозвана ли клиника — по строке `clinics` (или выборке с её столбцами)."""
    return row is not None and "revoked_at" in row.keys() and bool(row["revoked_at"])


def in_cabinet(con: sqlite3.Connection, clinic_id: str) -> bool:
    """Есть ли отозванная клиника среди клиник кабинета `clinic_id` (она сама — тоже): «Adaugă clinică»
    такого кабинета дала бы новую клинику с файлом на срок оплаты первой ноты — в обход отзыва."""
    ids = cabinet.ids(con, clinic_id) | {clinic_id}
    marks = ",".join("?" * len(ids))
    return con.execute(f"SELECT 1 FROM clinics WHERE id IN ({marks}) AND revoked_at IS NOT NULL LIMIT 1",
                       tuple(ids)).fetchone() is not None


def _clean(reason: str) -> str:
    return " ".join((reason or "").split())[:REASON_MAX]


def revoke(con: sqlite3.Connection, clinic: sqlite3.Row, reason: str, word: str, who: str) -> str:
    """Отозвать: файл отзыва и отметка в строке клиники; '' — сделано, иначе код отказа."""
    reason = _clean(reason)
    if is_revoked(clinic):
        return ALREADY
    if not reason:
        return NEED_REASON
    if (word or "").strip().upper() != CONFIRM_WORD:
        return NEED_WORD
    if con.execute("SELECT 1 FROM issues WHERE clinic_id=? LIMIT 1", (clinic["id"],)).fetchone() is None:
        return NO_FILE              # программе нечего отзывать: заявку без файла «Скрыть»
    sub = con.execute("SELECT plan FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    plan = sub["plan"] if sub is not None and sub["plan"] in license.PLANS else "trial"
    end = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=REVOKE_SECONDS)
    seq, _ = license.issue(con, clinic, plan, end, end, f"{REVOKE_TAG}: {reason}", who)
    con.execute("UPDATE clinics SET revoked_at=?, revoked_by=?, revoked_reason=?, revoked_seq=? WHERE id=?",
                (db.now_iso(), who, reason, seq, clinic["id"]))
    db.audit(con, who, "revoke", clinic["id"], f"файл {seq}, срок кончился сразу: {reason}")
    return ""


def restore(con: sqlite3.Connection, clinic: sqlite3.Row, reason: str, who: str) -> str:
    """Вернуть: отметку долой и файл с прежним сроком (последний файл до отзыва). → исход для ?msg=."""
    if not is_revoked(clinic):
        return NOT_REVOKED
    reason = _clean(reason) or "без причины"
    prior = con.execute("SELECT * FROM issues WHERE clinic_id=? AND seq<? ORDER BY seq DESC LIMIT 1",
                        (clinic["id"], clinic["revoked_seq"] or 0)).fetchone()
    con.execute("UPDATE clinics SET revoked_at=NULL, revoked_by='', revoked_reason='', revoked_seq=NULL WHERE id=?",
                (clinic["id"],))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    valid = db.parse_ts(prior["valid_until"]) if prior is not None else None
    grace = db.parse_ts(prior["grace_until"]) if prior is not None else None
    soon = now + timedelta(seconds=REVOKE_SECONDS)
    if valid is None or grace is None or grace <= soon:
        db.audit(con, who, "restore", clinic["id"],
                 f"срок до отзыва ({(prior['grace_until'] if prior is not None else '—')[:10]}) уже прошёл — "
                 f"файл не выдан: {reason}")
        return RESTORED_EXPIRED
    sub = con.execute("SELECT plan FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    plan = sub["plan"] if sub is not None and sub["plan"] in license.PLANS else "trial"
    # срок кончился, льгота идёт — новый файл обязан быть позже выдачи: срок «сейчас + 2 с», льгота прежняя
    seq, _ = license.issue(con, clinic, plan, max(valid, soon), grace, f"{RESTORE_TAG}: {reason}", who)
    db.audit(con, who, "restore", clinic["id"], f"файл {seq}, срок до {prior['valid_until'][:10]}, "
                                                 f"льгота до {prior['grace_until'][:10]}: {reason}")
    return RESTORED


def letter(clinic: sqlite3.Row, who: str) -> mail.Letter | str:
    """Письмо клинике об отзыве — только галочкой формы (по умолчанию снята, Олег 11.11). Собрать в
    транзакции, отправить после commit (payments.outbox). Код отказа — `bad_email`."""
    if not clinic["email"]:
        return "bad_email"
    subject = f"DentPilot: licența clinicii {clinic['name']} a fost retrasă"
    body = (f"Bună ziua,\n\n"
            f"Licența DentPilot a clinicii {clinic['name']} a fost retrasă. La următoarea verificare a licenței "
            f"(la pornire, o dată pe zi sau cu «Verifică acum») programul trece în regim de citire: datele "
            f"pacienților se pot consulta, tipări și exporta, iar copia de rezervă rămâne disponibilă; "
            f"programări noi și modificări — nu. Mesajele SMS nu se mai trimit.\n\n"
            f"Pentru detalii scrieți-ne la {config.SUPPORT_EMAIL}.\n\n{mail.FOOTER}")
    return mail.Letter(clinic["email"], subject, body, clinic["id"], who, "письмо об отзыве лицензии",
                       f"письмо об отзыве клинике {clinic['id']}")
