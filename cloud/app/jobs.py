"""Ежедневная задача (L9): состояние каждой подписки → что сегодня отправить.

cloud.md › «Напоминания». Запуск раз в сутки из cron (README.md) или кнопкой
в админке; в тестах и при разборе — с подставной датой:

    python -m app.jobs daily
    python -m app.jobs daily --at 2026-10-17T06:00:00Z

Строки таблицы напоминаний здесь — ОКНА дат [с, до), а не точки: если задача
не бежала несколько дней (сервер лежал), она шлёт письмо той строки, в чьём
окне сегодня, а не все пропущенные подряд. Отправленное пишется в `reminders`
с ключом (подписка, kind, period); второй запуск в тот же день — и любой
запуск до следующего окна — ничего не шлёт. Период — дата конца срока:
продление даёт новый период, и напоминания по нему идут заново.

⭐ Каждая подписка — своя транзакция: отказ почты у одной клиники не
откатывает запись об отправленном у другой, а ошибка одной не останавливает
остальных. Состояние по-прежнему не хранится: окна считаются от дат.

Карты (L12; с 23.10): письма периода несут страницу оплаты клиники
(paylink.for_mail) рядом с reference — ссылка maib живёт 10 минут и рождается
только по клику на этой странице, после галочки условий. Вторая забота задачи —
спросить maib про каждую попытку оплаты картой без окончательного ответа:
callback мог не дойти, а истина всё равно у maib.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import db, license, mail, maib, paylink, payments, sms, smsmd, tiers

log = logging.getLogger("cloud.jobs")

INVOICE, EXPIRING, EXPIRED, LAST_WARNING, READONLY = (
    "invoice", "expiring", "expired", "last_warning", "readonly")
KINDS = (INVOICE, EXPIRING, EXPIRED, LAST_WARNING, READONLY)
INVOICE_DAYS = 14      # счёт на следующий период — за 14 дней до конца срока
EXPIRING_DAYS = 3      # «expiră în 3 zile»
READONLY_DAYS = 30     # сколько дней после начала режима чтения письмо о нём ещё уместно
WHO = "daily"


def windows(valid_until: date, grace_until: date, plan: str) -> list[tuple[str, date, date]]:
    """Таблица cloud.md › «Напоминания» как окна [с, до) по датам UTC.
    Счёт — только оплаченным: пробному нечего продлевать, ему предлагают абонемент."""
    d = timedelta
    rows: list[tuple[str, date, date]] = []
    if plan != "trial":
        rows.append((INVOICE, valid_until - d(days=INVOICE_DAYS), valid_until - d(days=EXPIRING_DAYS)))
    rows += [(EXPIRING, valid_until - d(days=EXPIRING_DAYS), valid_until),
             (EXPIRED, valid_until, grace_until - d(days=1)),
             (LAST_WARNING, grace_until - d(days=1), grace_until),
             (READONLY, grace_until, grace_until + d(days=READONLY_DAYS))]
    return rows


def due(valid_until: date, grace_until: date, plan: str, today: date) -> str | None:
    """Какое письмо по расписанию сегодня: ПОСЛЕДНЯЯ строка, в чьём окне сегодня.
    При короткой льготе окна накладываются, и поздняя строка точнее: при льготе 0
    в канун срока — «de mâine regim de citire», а не «expiră în 3 zile»."""
    kind = None
    for k, start, end in windows(valid_until, grace_until, plan):
        if start <= today < end:
            kind = k
    return kind


@dataclass
class Report:
    at: str = ""
    sent: list[tuple[str, str]] = field(default_factory=list)      # (clinic_id, kind)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (clinic_id, почему)
    failed: list[tuple[str, str]] = field(default_factory=list)    # (clinic_id, ошибка)
    cards: list[tuple[str, str]] = field(default_factory=list)     # (clinic_id, reference) — maib сказал OK
    sms: str = ""                                                   # итог SMS-части (S3) словами

    def line(self) -> str:
        return (f"писем: {len(self.sent)}, пропущено: {len(self.skipped)}, ошибок: {len(self.failed)}, "
                f"картой оплачено: {len(self.cards)}" + (f"; SMS: {self.sms}" if self.sms else ""))


_SUBS = """SELECT c.*, s.plan, s.price, s.tier, s.sms_until, s.valid_until, s.grace_days
           FROM subscriptions s JOIN clinics c ON c.id = s.clinic_id
           WHERE s.valid_until IS NOT NULL AND s.cancelled_at IS NULL
           ORDER BY c.created_at, c.id"""


def open_payment(con: sqlite3.Connection, clinic: sqlite3.Row, who: str = WHO) -> sqlite3.Row:
    """Открытый платёж клиники — или новый на тот же срок, что оплачивали в последний раз,
    в варианте, в котором идёт подписка (условия § 4.5: «în varianta în curs»; сменить его
    клиника может на странице оплаты — нота заменится). Один reference на всю серию писем
    периода: второго ожидающего платежа задача не заводит. `clinic` — строка _SUBS
    (клиника и её подписка). Цены у варианта нет — ValueError('amount') от create."""
    p = payments.open_of(con, clinic["id"])
    if p is not None:
        return p
    last = con.execute("SELECT months FROM payments WHERE clinic_id=? AND status=? AND kind=? "
                       "ORDER BY id DESC LIMIT 1", (clinic["id"], payments.PAID, payments.LICENSE)).fetchone()
    months = int(last["months"]) if last and int(last["months"]) in payments.MONTHS else 1
    tier = tiers.current(clinic)
    return payments.create(con, clinic, months, payments.amount_for(clinic, tier, months), who, tier=tier)


def _one(con: sqlite3.Connection, row: sqlite3.Row, now: datetime, send, who: str, rep: Report) -> None:
    valid = db.parse_ts(row["valid_until"])
    if valid is None:
        return
    grace = valid + timedelta(days=int(row["grace_days"]))
    kind = due(valid.date(), grace.date(), row["plan"], now.date())
    if kind is None:
        return
    period = row["valid_until"]
    if con.execute("SELECT 1 FROM reminders WHERE subscription_id=? AND kind=? AND period=?",
                   (row["id"], kind, period)).fetchone():
        return
    if not row["email"]:
        log.warning("напоминание %s клинике %s не отправлено: e-mail не указан", kind, row["id"])
        rep.skipped.append((row["id"], "нет e-mail"))
        return
    pay = None
    if row["plan"] != "trial":
        p = open_payment(con, row, who)
        # карта — на странице оплаты клиники, кнопкой после галочки условий (23.10): ссылка maib
        # живёт 10 минут и рождается по клику, поэтому письмо несёт НАШУ страницу, не ссылку maib
        page = paylink.for_mail(con, row, who)
        pay = {"reference": p["reference"], "amount": int(p["amount"]), "months": int(p["months"]),
               "url": page if maib.enabled() else None, "page": page, "tier": p["tier"]}
    subject, body = mail.reminder_letter(kind, row["name"], row["plan"], valid, grace,
                                         int(row["grace_days"]), pay)
    try:
        where = send(row["email"], subject, body)
    except (RuntimeError, OSError) as e:
        log.error("напоминание %s клинике %s не отправлено: %r", kind, row["id"], e)
        rep.failed.append((row["id"], repr(e)))
        return
    con.execute("INSERT INTO reminders(subscription_id, kind, period, sent_at) VALUES(?,?,?,?)",
                (row["id"], kind, period, db.now_iso()))
    db.audit(con, who, "reminder", row["id"], f"{kind}, период до {period[:10]}, на {row['email']} ({where})")
    rep.sent.append((row["id"], kind))


ATTEMPT_DAYS = 30      # попытку без окончательного ответа maib спрашивают не дольше месяца


def settle_cards(who: str, rep: Report) -> None:
    """Каждая попытка оплаты картой без окончательного ответа maib (pay_attempts.final = 0):
    спросить pay-info и применить (payments.settle). Callback мог не дойти; истина у maib
    и без него. Окончательный ответ (OK, FAILED, TIMEOUT протухшей ссылки) закрывает
    попытку — назавтра её не спрашивают, и «card_failed» не пишется каждый день (23.10).
    Оплачено — файл письмом, как из админки. maib не ответил — в отчёт, не в
    падение задачи: письма клиникам от этого не зависят.
    ⭐ Нота могла закрыться ДРУГИМ путём (перевод подтверждён), а карта по её попытке —
    пройти потом: попытка остаётся открытой, и задача зачтёт второй платёж (credit_again)."""
    if not maib.enabled():
        return
    since = (datetime.now(timezone.utc) - timedelta(days=ATTEMPT_DAYS)).strftime(db.TS)
    with db.connect() as con:
        rows = con.execute("""SELECT a.provider_id, a.payment_id, p.reference, p.clinic_id
                              FROM pay_attempts a JOIN payments p ON p.id = a.payment_id
                              WHERE a.final=0 AND a.created_at>=? ORDER BY a.created_at""",
                           (since,)).fetchall()
    for p in rows:
        try:
            truth = maib.info(p["provider_id"])
        except maib.MaibError as e:
            log.warning("maib про %s не ответил: %s", p["reference"], e)
            rep.skipped.append((p["clinic_id"], f"maib не ответил про {p['reference']}"))
            continue
        try:
            with db.connect() as con:
                # попытка могла переехать на другую строку (зачёт повторного платежа) — платёж по ней
                fresh = payments.by_pay_id(con, p["provider_id"])
                outcome = payments.settle(con, fresh, truth, who)
                if outcome == payments.SETTLED_PAID:
                    payments.notify_paid(con, fresh, who)
                    rep.cards.append((p["clinic_id"], p["reference"]))
        except Exception as e:  # noqa: BLE001 — один платёж не останавливает остальных
            log.error("платёж картой %s: %r", p["reference"], e)
            rep.failed.append((p["clinic_id"], repr(e)))


def sms_daily(rep: Report, now: datetime, send, who: str) -> None:
    """SMS-пакет (S3, sms.md › «Ежедневная задача»): сгорание пакетов (S0), опрос
    статусов без уведомления, сверка имён с sms.md, «Au rămas N SMS» клиникам,
    баланс sms.md против проданного. Каждая часть — своя; сбой одной записывается
    и не останавливает ни остальные, ни письма о подписках."""
    parts: list[str] = []
    try:
        burned = sms.expire(now, who)
        polled = sms.poll(now, who)
        parts.append(f"статусов {polled['checked']}"
                     + (f" (не получено {polled['failed']})" if polled["failed"] else ""))
        if smsmd.enabled():
            try:
                al = sms.sync_aliases(who)
                parts.append(f"имён одобрено {al['active']}, отказано {al['rejected']}")
            except (smsmd.Unanswered, smsmd.Refused) as e:
                rep.skipped.append(("_sms", f"имена sms.md не сверены: {e}"))
        low = sms.low_letters(send, who)
        parts.append(f"писем об остатке {len(low)}")
        fc = sms.float_check(now)
        if fc["error"]:
            rep.skipped.append(("_sms", f"баланс sms.md не получен: {fc['error']}"))
        elif fc["balance"] is not None:
            parts.append(f"баланс sms.md {fc['balance']} MDL против {fc['owed']} сегм. долга"
                         + (" — тревога Олегу" if fc["alarm"] else ""))
        if burned:
            parts.append(f"сгорело {burned} сегм.")
    except Exception as e:  # noqa: BLE001 — SMS-часть не останавливает письма о подписках
        log.error("SMS-часть задачи: %r", e)
        rep.failed.append(("_sms", repr(e)))
    rep.sms = ", ".join(parts)


def daily(now: datetime | None = None, send=mail.send, who: str = WHO) -> Report:
    """Один проход по всем подпискам. `now` подставляется в тестах; письма — через `send`."""
    now = now or datetime.now(timezone.utc)
    rep = Report(at=now.strftime(db.TS))
    settle_cards(who, rep)     # сперва оплаты: продлённая подписка сегодня писем не ждёт
    sms_daily(rep, now, send, who)
    with db.connect() as con:
        subs = con.execute(_SUBS).fetchall()
    for row in subs:
        try:
            with db.connect() as con:
                _one(con, row, now, send, who, rep)
        except Exception as e:  # noqa: BLE001 — одна клиника не останавливает остальных
            log.error("напоминания клинике %s: %r", row["id"], e)
            rep.failed.append((row["id"], repr(e)))
    with db.connect() as con:
        db.audit(con, who, "daily", None, f"на {rep.at}: {rep.line()}")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily", help="напоминания по таблице cloud.md за сегодня")
    d.add_argument("--at", help="подставная дата-время YYYY-MM-DDTHH:MM:SSZ (по умолчанию сейчас, UTC)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    now = None
    if a.at:
        now = db.parse_ts(a.at)
        if now is None:
            ap.error("--at: ожидается YYYY-MM-DDTHH:MM:SSZ")
    db.init()
    rep = daily(now)
    for cid, ref in rep.cards:
        print(f"оплачено картой {ref} {cid}")
    for cid, kind in rep.sent:
        print(f"отправлено {kind} {cid}")
    for cid, why in rep.skipped:
        print(f"пропущено {cid}: {why}")
    for cid, err in rep.failed:
        print(f"ошибка {cid}: {err}")
    print(f"{rep.at}: {rep.line()}")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
