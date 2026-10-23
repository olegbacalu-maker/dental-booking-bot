"""Платёж переводом (L8): reference, ожидание, подтверждение, отказ, продление.

cloud.md › «Оплата › Шаг 1 — transfer bancar». Reference уникален (год +
порядковый номер), печатается в письме и в админке, клиника пишет его в
назначении платежа. Подтверждение идемпотентно: второе подтверждение того же
платежа — отказ, а не второе продление. Каждое действие — строка в audit.

⭐ Правило продления: N месяцев от БОЛЬШЕЙ из дат — сегодня или конца
действующего срока. Ранняя оплата не крадёт дни, поздняя не дарит. Каждое
продление = новая выдача файла (seq+1): файл и есть истина о сроке.
⭐ Число месяца — ЯКОРЬ подписки (`subscriptions.anchor_day`, 02.10): продление
считается от числа первого оплаченного периода, а не от прошлой даты окончания.
Иначе срок, кончавшийся 31-го, после февраля навсегда съезжал бы на 28-е:
31.01 → 28.02 → 28.03 вместо 31.03 — клиника теряла бы дни, а её число менялось.
Срок, сдвинутый руками («Лицензия вручную»), якорь сбрасывает на своё число.

Повторный платёж по ОДНОЙ ноте (02.10): карта прошла после подтверждённого
перевода, бухгалтер перевёл по уже оплаченной ноте — деньги клиники у нас
дважды. Второй платёж не теряется: он зачитывается отдельной строкой с новым
reference как следующий период (`credit_again`) — картой сам, по ответу maib,
переводом — кнопкой «Зачесть повторный перевод» в админке.

Карта (L12): у платежа появляется ссылка maib (`provider_id` = payId,
`pay_url`), reference остаётся тем же — клиника платит картой по ссылке ИЛИ
переводом с reference, долг один. Ответ maib применяет `settle` — одно правило
на callback, кнопку «Проверить» и ежедневную задачу: оплачено только то, про
что сам maib (pay-info) сказал OK; второй раз ничего не продлевается.

Варианты абонемента (23.10, tiers.py): нота абонемента знает свой вариант
(`payments.tier`), клиника выбирает его при каждой оплате (`choose`); открытая нота
другого варианта или срока ЗАМЕНЯЕТСЯ (отклоняется с причиной, выставляется новая),
второго долга нет. `confirm` ставит подписке вариант и цену месяца и решает модуль
SMS: Plus — сразу, Basic — до конца периода, шедшего на момент оплаты (`sms_until`).
"""
from __future__ import annotations

import calendar
import sqlite3
from datetime import datetime, timedelta, timezone

from . import db, license, maib, mail, receipts, sms, tiers

PENDING, PAID, REJECTED = "pending", "paid", "rejected"
TRANSFER, CARD = "transfer", "card"
# Вид платежа (S3): абонемент, пополнение SMS или год своего имени отправителя.
# У пополнения `months` = 0, `sms_units` — сколько начислить при подтверждении; у
# имени `months` = 0 и `sms_units` пуст. Открытый платёж каждого вида у клиники
# один — запросы о «ожидающей ноте» всюду называют вид.
LICENSE, SMS, SMS_NAME = "license", "sms", "sms_name"
# Сроки — как на сайте: месяц или год (решение Олега 26.09; 3 и 6 месяцев нет).
# Год стоит 11 месячных — «o lună gratuită» в карточке цены сайта.
MONTHS = (1, 12)
BILLED = {1: 1, 12: 11}
# Исходы settle: подтверждён сейчас · уже не в ожидании · maib ещё ждёт · не прошёл
SETTLED_PAID, SETTLED_ALREADY, SETTLED_WAITING, SETTLED_FAILED = "paid", "already", "waiting", "failed"


def add_months(dt: datetime, n: int, day: int | None = None) -> datetime:
    """Календарные месяцы: 31.01 + 1 = 28/29.02, время суток сохраняется. `day` —
    число-якорь вместо числа `dt`: 28.02 + 1 с якорем 31 = 31.03."""
    month0 = dt.month - 1 + n
    year, month = dt.year + month0 // 12, month0 % 12 + 1
    day = min(day or dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def amount(months: int, price: int) -> int:
    """Сумма по прайсу за срок из MONTHS: год — 11 месячных."""
    return BILLED[months] * price


def anchor_day(valid_until: datetime | None, now: datetime, anchor: int | None) -> int:
    """Число, от которого считается продление. Срок кончился (или его нет) — новый
    отсчёт с сегодняшнего числа. Срок действует — якорь подписки, если срок стоит
    НА нём (число якоря, обрезанное концом месяца: 28.02 при якоре 31); иначе срок
    двигали руками, и якорь — его собственное число."""
    if valid_until is None or valid_until < now:
        return now.day
    last = calendar.monthrange(valid_until.year, valid_until.month)[1]
    return anchor if anchor and valid_until.day == min(anchor, last) else valid_until.day


def extend_from(valid_until: datetime | None, months: int, now: datetime,
                anchor: int | None = None) -> datetime:
    base = now if valid_until is None or valid_until < now else valid_until
    return add_months(base, months, anchor_day(valid_until, now, anchor))


def next_reference(con: sqlite3.Connection, now: datetime) -> str:
    year = now.year
    row = con.execute("SELECT reference FROM payments WHERE reference LIKE ? ORDER BY reference DESC LIMIT 1",
                      (f"DP-{year}-%",)).fetchone()
    last = int(row[0].rsplit("-", 1)[1]) if row else 0
    return f"DP-{year}-{last + 1:06d}"


def create(con: sqlite3.Connection, clinic: sqlite3.Row, months: int, amount: int, who: str,
           tier: str = tiers.PLUS, terms: bool = False, note: str = "") -> sqlite3.Row:
    """Нота абонемента варианта `tier`. `terms` — клиника отметила условия перед этой
    оплатой (страница оплаты, кабинет): время ложится в terms_at. `note` — хвост строки журнала."""
    if months not in MONTHS:
        raise ValueError("months")
    if tier not in tiers.TIERS:
        raise ValueError("tier")
    if amount <= 0:
        raise ValueError("amount")
    now = datetime.now(timezone.utc)
    ref = next_reference(con, now)
    con.execute("""INSERT INTO payments(clinic_id, amount, currency, method, status, reference, months, tier,
                                        terms_at, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (clinic["id"], amount, "MDL", TRANSFER, PENDING, ref, months, tier,
                 db.now_iso() if terms else None, db.now_iso()))
    db.audit(con, who, "payment_new", clinic["id"],
             f"{ref}: {amount} MDL за {months} мес., {tiers.NAME[tier]}, перевод"
             + (", условия приняты" if terms else "") + (f"; {note}" if note else ""))
    return con.execute("SELECT * FROM payments WHERE reference=?", (ref,)).fetchone()


def amount_for(sub: sqlite3.Row | None, tier: str, months: int) -> int:
    """Сумма ноты варианта за срок по правилу tiers.price; 0 — вариант не продаётся."""
    return amount(months, tiers.price(sub, tier)) if months in MONTHS else 0


CREATED, EXISTS, REPLACED = "created", "exists", "replaced"


def choose(con: sqlite3.Connection, clinic: sqlite3.Row, tier: str, months: int, who: str,
           terms: bool = True) -> tuple[sqlite3.Row, str]:
    """Выбор клиники на странице оплаты или в кабинете → (нота, CREATED | EXISTS | REPLACED).

    Открытая нота того же варианта и срока — она же (сумма прежняя: её мог выставить
    админ со скидкой). Другого — отклоняется с причиной «заменена» и выставляется новая:
    долг у клиники один, а прежний reference, если по нему всё же заплатят, зачитывается
    повторным платежом (credit_again), деньги не теряются.
    ⛔ Вариант не продаётся (цены нет) — ValueError('tier'), срок не из ряда — ValueError('months')."""
    if months not in MONTHS:
        raise ValueError("months")
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    a = amount_for(sub, tier, months) if tier in tiers.TIERS else 0
    if a <= 0:
        raise ValueError("tier")
    old = open_of(con, clinic["id"])
    if old is not None and (old["tier"] or tiers.PLUS) == tier and int(old["months"]) == months:
        if terms and not old["terms_at"]:
            con.execute("UPDATE payments SET terms_at=? WHERE id=?", (db.now_iso(), old["id"]))
        return con.execute("SELECT * FROM payments WHERE id=?", (old["id"],)).fetchone(), EXISTS
    if old is not None:
        reject(con, old, f"заменена: клиника выбрала {tiers.NAME[tier]}, {months} мес.", who)
    p = create(con, clinic, months, a, who, tier=tier, terms=terms,
               note=f"взамен {old['reference']}" if old is not None else "")
    return p, (REPLACED if old is not None else CREATED)


def create_pack(con: sqlite3.Connection, clinic: sqlite3.Row, units: int, amount: int, who: str) -> sqlite3.Row:
    """Нота за пакет SMS (kind=sms): тот же reference, тот же путь оплаты; при
    подтверждении начисляется пакет, а не срок (confirm)."""
    if units <= 0 or amount <= 0:
        raise ValueError("amount")
    ref = next_reference(con, datetime.now(timezone.utc))
    con.execute("""INSERT INTO payments(clinic_id, amount, currency, method, status, reference, months, kind,
                                        sms_units, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (clinic["id"], amount, "MDL", TRANSFER, PENDING, ref, 0, SMS, units, db.now_iso()))
    db.audit(con, who, "payment_new", clinic["id"], f"{ref}: {amount} MDL за пакет {units} SMS, перевод")
    return con.execute("SELECT * FROM payments WHERE reference=?", (ref,)).fetchone()


def create_name(con: sqlite3.Connection, clinic: sqlite3.Row, amount: int, who: str) -> sqlite3.Row:
    """Нота за год своего имени отправителя (kind=sms_name, Олег 16.10)."""
    if amount <= 0:
        raise ValueError("amount")
    ref = next_reference(con, datetime.now(timezone.utc))
    con.execute("""INSERT INTO payments(clinic_id, amount, currency, method, status, reference, months, kind, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (clinic["id"], amount, "MDL", TRANSFER, PENDING, ref, 0, SMS_NAME, db.now_iso()))
    db.audit(con, who, "payment_new", clinic["id"], f"{ref}: {amount} MDL за год имени отправителя, перевод")
    return con.execute("SELECT * FROM payments WHERE reference=?", (ref,)).fetchone()


def open_of(con: sqlite3.Connection, clinic_id: str, kind: str = LICENSE) -> sqlite3.Row | None:
    """Ожидающая нота клиники этого вида — одна на вид."""
    return con.execute("SELECT * FROM payments WHERE clinic_id=? AND status=? AND kind=? ORDER BY id DESC LIMIT 1",
                       (clinic_id, PENDING, kind)).fetchone()


def notify_paid(con: sqlite3.Connection, payment: sqlite3.Row, who: str) -> str:
    """Письмо после оплаты — по виду: пакет SMS → «pachetul a fost activat»,
    абонемент → письмо о лицензии (license.mail_latest). Код для ?msg= или ''."""
    clinic = con.execute("SELECT * FROM clinics WHERE id=?", (payment["clinic_id"],)).fetchone()
    fresh = con.execute("SELECT * FROM payments WHERE id=?", (payment["id"],)).fetchone()
    # cont de plată (17.10) — вложением в то же письмо, что говорит об оплате; строки оплаты
    # в тексте (№, что, сумма, дата, поставщик — требование maib) — из того же снимка
    receipt = receipts.attachment(con, fresh, who)
    row = receipts.get(con, fresh["id"]) if receipt else None
    summary = receipts.summary(row) if row is not None else ""
    if payment["kind"] in (SMS, SMS_NAME):
        return (sms.mail_pack if payment["kind"] == SMS else sms.mail_name)(con, clinic, fresh, who,
                                                                            receipt=receipt, summary=summary)
    return license.mail_latest(con, clinic, who, receipt=receipt, summary=summary)


def subject(p: sqlite3.Row) -> str:
    """Что оплачивается — одной строкой по-румынски (описание у maib, страница возврата)."""
    kind = p["kind"] or LICENSE
    if kind == SMS:
        return f"pachet {p['sms_units']} SMS"
    if kind == SMS_NAME:
        return "nume de expeditor SMS, un an"
    return f"abonament {tiers.NAME.get(p['tier'], tiers.NAME[tiers.PLUS])}, {mail.luni(int(p['months'] or 1))}"


def attach_card(con: sqlite3.Connection, payment: sqlite3.Row, clinic: sqlite3.Row, who: str,
                client_ip: str = "127.0.0.1") -> sqlite3.Row:
    """Ссылка maib к ожидающему платежу (L12): новый платёж у maib, payId и адрес
    страницы — в строку; reference не меняется. Повторный вызов — новая ссылка
    взамен неудавшейся. Бросает maib.MaibError, если maib не ответил."""
    if payment["status"] != PENDING:
        raise ValueError("not_pending")
    pay_id, pay_url = maib.create(int(payment["amount"]), payment["reference"],
                                  f"DentPilot {payment['reference']}: {subject(payment)} — {clinic['name']}",
                                  clinic["email"] or "", client_ip)
    con.execute("UPDATE payments SET method=?, provider_id=?, pay_url=?, provider_status='' WHERE id=?",
                (CARD, pay_id, pay_url, payment["id"]))
    db.audit(con, who, "card_link", clinic["id"], f"{payment['reference']}: maib {pay_id}")
    return con.execute("SELECT * FROM payments WHERE id=?", (payment["id"],)).fetchone()


def settle(con: sqlite3.Connection, payment: sqlite3.Row, result: dict, who: str) -> str:
    """Применить ответ maib о платеже (pay-info): SETTLED_*.

    ⛔ Единственное место, где статус maib становится нашим `paid`, — и только
    статус OK. Всё, что не OK и не ожидание, — «не прошёл»: строка остаётся в
    ожидании (долг стоит, перевод по reference по-прежнему возможен), а слова
    maib ложатся в provider_status и журнал. Не в ожидании — ничего: второе
    подтверждение не продлевает (инвариант 3)."""
    if result.get("payId") != payment["provider_id"]:
        raise ValueError("foreign")
    status = str(result.get("status") or "").upper()
    detail = " ".join(str(result.get(k) or "") for k in ("status", "statusCode", "statusMessage")).strip()
    con.execute("UPDATE payments SET provider_status=? WHERE id=?", (detail[:120], payment["id"]))
    if payment["status"] != PENDING:
        # ⭐ Нота уже закрыта ДРУГИМ путём (перевод подтверждён, нота отклонена), а maib
        # говорит, что ЭТА карта прошла: деньги клиники у нас дважды — зачесть как
        # следующий период, а не промолчать. Закрыта этой же картой — ничего (инвариант 3).
        if status == maib.STATUS_OK and payment["paid_via"] != CARD:
            credit_again(con, payment, CARD, who)
            return SETTLED_PAID
        return SETTLED_ALREADY
    if status == maib.STATUS_OK:
        confirm(con, payment, who, via=CARD)
        con.execute("UPDATE payments SET method=? WHERE id=?", (CARD, payment["id"]))
        return SETTLED_PAID
    if status in maib.WAITING:
        return SETTLED_WAITING
    db.audit(con, who, "card_failed", payment["clinic_id"], f"{payment['reference']}: {detail}")
    return SETTLED_FAILED


def confirm(con: sqlite3.Connection, payment: sqlite3.Row, who: str,
            via: str = TRANSFER) -> tuple[int, str]:
    """Подтвердить поступление: продлить и выдать файл. Возвращает (seq, текст файла).
    `via` — чем пришли деньги (перевод — кнопкой админа, карта — по ответу maib).
    ⛔ Не в ожидании — ValueError('not_pending'): продление не повторяется."""
    if payment["status"] != PENDING:
        raise ValueError("not_pending")
    clinic = con.execute("SELECT * FROM clinics WHERE id=?", (payment["clinic_id"],)).fetchone()
    if payment["kind"] in (SMS, SMS_NAME):
        # SMS (S3): начисление или год имени вместо продления и файла; один раз — по тому же AND status
        con.execute("UPDATE payments SET status=?, paid_at=?, confirmed_by=?, paid_via=? WHERE id=? AND status=?",
                    (PAID, db.now_iso(), who, via, payment["id"], PENDING))
        what = f"пакет {payment['sms_units']} SMS" if payment["kind"] == SMS else "год имени отправителя"
        db.audit(con, who, "payment_paid", clinic["id"], f"{payment['reference']}: {payment['amount']} MDL, {what}")
        (sms.credit_pack if payment["kind"] == SMS else sms.credit_name)(con, payment, who)
        receipts.create(con, payment["id"], who)
        return 0, ""
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    current = db.parse_ts(sub["valid_until"]) if sub else None
    day = anchor_day(current, now, sub["anchor_day"] if sub else None)
    valid = extend_from(current, int(payment["months"]), now, day)
    grace = valid + timedelta(days=license.GRACE_DAYS)
    tier, price, sms_until, switch = tier_after(sub, payment, now)
    con.execute("UPDATE payments SET status=?, paid_at=?, confirmed_by=?, paid_via=? WHERE id=? AND status=?",
                (PAID, db.now_iso(), who, via, payment["id"], PENDING))
    db.audit(con, who, "payment_paid", clinic["id"],
             f"{payment['reference']}: {payment['amount']} MDL, {tiers.NAME[tier]}, срок до {valid.strftime(db.TS)}"
             + (f"; {switch}" if switch else ""))
    issued = license.issue(con, clinic, "standard", valid, grace,
                           f"платёж {payment['reference']}", who)
    # якорь и вариант — после выдачи: она заводит строку подписки, если её ещё не было
    con.execute("UPDATE subscriptions SET anchor_day=?, tier=?, price=?, sms_until=? WHERE clinic_id=?",
                (day, tier, price, sms_until, clinic["id"]))
    # cont de plată (17.10): снимок оплаты с оплаченным сроком — от начала периода до нового конца
    start = now if current is None or current < now else current
    receipts.create(con, payment["id"], who, period=(start, valid))
    return issued


def tier_after(sub: sqlite3.Row | None, payment: sqlite3.Row, now: datetime) -> tuple[str, int, str | None, str]:
    """Подписка после оплаты ноты абонемента: (вариант, цена месяца, sms_until, строка для журнала).

    Цена — по правилу tiers.price (свой вариант — своя цена, другой — прайс); прайса
    нет (вариант сняли с продажи после ноты) — цена из суммы ноты. Модуль SMS (§ 4.2):
    Plus — работает сразу (`sms_until` пуст); переход на Basic с Plus или пробного —
    работает до конца периода, который идёт сейчас, и гаснет; Basic → Basic — как было."""
    tier = payment["tier"] if payment["tier"] in tiers.TIERS else tiers.PLUS
    months = int(payment["months"] or 1)
    price = tiers.price(sub, tier) or int(payment["amount"]) // BILLED.get(months, months)
    before = tiers.current(sub)
    if tier == tiers.PLUS:
        return tier, price, None, (f"переход {tiers.NAME[before]} → {tiers.NAME[tier]}, модуль SMS сразу"
                                   if sub is not None and sub["plan"] != "trial" and before != tier else "")
    if before == tiers.BASIC:
        return tier, price, sub["sms_until"] if sub is not None else None, ""
    current = db.parse_ts(sub["valid_until"]) if sub is not None else None
    until = current.strftime(db.TS) if current is not None and current > now else None
    what = "пробный" if sub is not None and sub["plan"] == "trial" else tiers.NAME[before]
    return tier, price, until, (f"переход {what} → {tiers.NAME[tier]}: модуль SMS до {until[:10]}" if until
                                else f"переход {what} → {tiers.NAME[tier]}: модуль SMS выключен сразу")


def set_tier(con: sqlite3.Connection, clinic_id: str, tier: str, price: int | None, who: str) -> str:
    """Карточка › «Вариант вручную» — для исключений (Олег 23.10): вариант сразу, без оплаты.
    Plus — модуль SMS сразу; Basic — модуль гаснет сразу (переход «с конца периода» даёт
    только оплата). Цена месяца — названная, иначе по правилу tiers.price. '' или код
    отказа: tier_bad, tier_trial (пробный — всегда Plus, вариант выбирают при оплате),
    tier_no_sub (подписки нет), tier_price (цены нет ни в форме, ни в прайсе)."""
    if tier not in tiers.TIERS:
        return "tier_bad"
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic_id,)).fetchone()
    if sub is None:
        return "tier_no_sub"
    if sub["plan"] == "trial":
        return "tier_trial"
    p = price if price and price > 0 else tiers.price(sub, tier)
    if p <= 0:
        return "tier_price"
    before = tiers.current(sub)
    con.execute("UPDATE subscriptions SET tier=?, price=?, sms_until=NULL, updated_at=? WHERE clinic_id=?",
                (tier, p, db.now_iso(), clinic_id))
    db.audit(con, who, "tier_set", clinic_id,
             f"вручную: {tiers.NAME[before]} → {tiers.NAME[tier]}, {p} MDL / мес.; модуль SMS "
             + ("работает" if tier == tiers.PLUS else "выключен сразу"))
    return ""


def credit_again(con: sqlite3.Connection, payment: sqlite3.Row, via: str, who: str) -> sqlite3.Row:
    """Второй платёж по уже закрытой ноте — следующий период отдельной строкой.

    Новая строка: новый reference, те же сумма и срок, `via` — чем пришли деньги.
    Карта: payId (и ссылка) переезжает со старой строки на новую — следующий
    callback того же платежа найдёт её уже оплаченной этой картой и ничего не
    продлит (инвариант 3); старая строка остаётся в истории без ссылки.
    ⛔ Ожидающую ноту так не закрыть — для неё «Подтвердить» (ValueError('pending'))."""
    if payment["status"] == PENDING:
        raise ValueError("pending")
    now = datetime.now(timezone.utc)
    ref = next_reference(con, now)
    provider_id = payment["provider_id"] if via == CARD else None
    pay_url = payment["pay_url"] if via == CARD else None
    if provider_id:
        con.execute("UPDATE payments SET provider_id=NULL WHERE id=?", (payment["id"],))
    con.execute("""INSERT INTO payments(clinic_id, amount, currency, method, status, reference, months,
                                        provider_id, pay_url, created_at, kind, sms_units, tier)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (payment["clinic_id"], payment["amount"], payment["currency"], via, PENDING, ref,
                 payment["months"], provider_id, pay_url, db.now_iso(), payment["kind"], payment["sms_units"],
                 payment["tier"]))
    new = con.execute("SELECT * FROM payments WHERE reference=?", (ref,)).fetchone()
    db.audit(con, who, "payment_repeat", payment["clinic_id"],
             f"{payment['reference']} ({payment['status']}): второй платёж "
             f"{'картой' if via == CARD else 'переводом'} зачтён как {ref}")
    confirm(con, new, who, via=via)
    return con.execute("SELECT * FROM payments WHERE id=?", (new["id"],)).fetchone()


def reject(con: sqlite3.Connection, payment: sqlite3.Row, reason: str, who: str) -> None:
    if payment["status"] != PENDING:
        raise ValueError("not_pending")
    con.execute("UPDATE payments SET status=?, confirmed_by=? WHERE id=? AND status=?",
                (REJECTED, who, payment["id"], PENDING))
    db.audit(con, who, "payment_rejected", payment["clinic_id"],
             f"{payment['reference']}: {reason or 'без причины'}")
