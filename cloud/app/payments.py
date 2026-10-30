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

Карта (L12): у платежа появляется ссылка maib (`provider_id` = payId — с 30.10
это checkoutId Checkout, maib.py — и `pay_url`), reference остаётся тем же — клиника платит картой по ссылке ИЛИ
переводом с reference, долг один. Ответ maib применяет `settle` — одно правило
на callback, кнопку «Проверить» и ежедневную задачу: оплачено только то, про
что сам maib (статус checkout, maib.info) сказал OK; второй раз ничего не продлевается.
С 23.10 ссылка maib живёт минуты (maib.PAY_TTL): клинике её даёт только клик
«Plătește cu cardul» на странице оплаты (`card_plan` → `card_ask` → `card_record`), письма несут нашу
страницу; у ноты может быть несколько попыток — все в `pay_attempts`, и любая
узнаётся (`by_pay_id`), чтобы оплата во вкладке со старой ссылкой не потерялась.

Общая нота кабинета (26.10, филиалы; Олег: «Нужен и общий счёт на все клиники кабинета»):
вид CABINET — одна строка payments у ПЛАТЕЛЬЩИКА (первая клиника кабинета среди строк, её
реквизиты — покупатель в cont de plată) со строками `payment_lines` (клиника, вариант, срок,
сумма строки по правилу цены ЭТОЙ клиники). Путь денег (maib, попытки, settle, зачёт) видит
одну ноту; `confirm` продлевает каждую клинику строки своим файлом, тем же `_prolong`, что
обычную ноту. ⭐ Правило одно: у клиники не больше одного открытого долга за абонемент — своя
нота ИЛИ строка открытой общей. Общая ЗАМЕНЯЕТ открытые ноты своих клиник и прежнюю общую с
любой из них (`create_group`); клинике в открытой общей своя нота не выставляется
(`choose` — ValueError(HELD)), до отмены общей (`reject`). `debt_of` — тот долг, какой есть.

Варианты абонемента (23.10, tiers.py): нота абонемента знает свой вариант
(`payments.tier`), клиника выбирает его при каждой оплате (`choose`); открытая нота
другого варианта или срока ЗАМЕНЯЕТСЯ (отклоняется с причиной, выставляется новая),
второго долга нет. `confirm` ставит подписке вариант и цену месяца и решает модуль
SMS: Plus — сразу, Basic — до конца периода, шедшего на момент оплаты (`sms_until`).
"""
from __future__ import annotations

import calendar
import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import db, license, maib, mail, receipts, sms, tiers

PENDING, PAID, REJECTED = "pending", "paid", "rejected"
TRANSFER, CARD = "transfer", "card"
# Вид платежа (S3): абонемент, пополнение SMS или год своего имени отправителя.
# У пополнения `months` = 0, `sms_units` — сколько начислить при подтверждении; у
# имени `months` = 0 и `sms_units` пуст. Открытый платёж каждого вида у клиники
# один — запросы о «ожидающей ноте» всюду называют вид.
LICENSE, SMS, SMS_NAME = "license", "sms", "sms_name"
# Общая нота кабинета (26.10): `months` = 0 и `tier` пуст — срок и вариант у каждой строки.
CABINET = "cabinet"
GROUP_MAX = 10            # клиник в общей ноте: cont de plată со строками — одна страница A4
HELD = "held"             # ValueError: у клиники открытая общая нота — своя не выставляется
# Сроки — как на сайте: месяц или год (решение Олега 26.09; 3 и 6 месяцев нет).
# Год стоит 11 месячных — «o lună gratuită» в карточке цены сайта.
MONTHS = (1, 12)
BILLED = {1: 1, 12: 11}
# Срок на оплату первой ноты у клиники из «Adaugă clinică» (Олег 27.10: пробный только у главной,
# добавленная — сразу платная, account.start_paid): основание её первой выдачи. По нему `_prolong`
# считает первый оплаченный период от дня заведения клиники, а не от конца этого срока — иначе
# срок на оплату стал бы бесплатными днями сверх оплаченного.
ADVANCE = "clinică nouă în cont: până la plata primei note"
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
    if group_of(con, clinic["id"]) is not None:
        raise ValueError(HELD)
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


# ---------- общая нота кабинета (26.10) ----------


def lines_of(con: sqlite3.Connection, payment_id: int) -> list:
    """Строки общей ноты с названием и адресом клиники — порядок клиник кабинета."""
    return con.execute("SELECT l.*, c.name, c.address FROM payment_lines l JOIN clinics c ON c.id = l.clinic_id "
                       "WHERE l.payment_id=? ORDER BY c.created_at, c.rowid", (payment_id,)).fetchall()


def group_of(con: sqlite3.Connection, clinic_id: str) -> sqlite3.Row | None:
    """Открытая общая нота, в которой есть эта клиника."""
    return con.execute("SELECT p.* FROM payments p JOIN payment_lines l ON l.payment_id = p.id "
                       "WHERE l.clinic_id=? AND p.status=? AND p.kind=? ORDER BY p.id DESC LIMIT 1",
                       (clinic_id, PENDING, CABINET)).fetchone()


def debt_of(con: sqlite3.Connection, clinic_id: str) -> sqlite3.Row | None:
    """Открытый долг клиники за абонемент: своя нота или общая, где она есть (одно из двух)."""
    return open_of(con, clinic_id) or group_of(con, clinic_id)


def of_clinic(con: sqlite3.Connection, clinic_id: str) -> list:
    """Ноты клиники для таблицы: свои и общие, где она строкой, — новые сверху."""
    return con.execute("SELECT * FROM payments WHERE clinic_id=? OR id IN "
                       "(SELECT payment_id FROM payment_lines WHERE clinic_id=?) ORDER BY id DESC",
                       (clinic_id, clinic_id)).fetchall()


def create_group(con: sqlite3.Connection, payer: sqlite3.Row, picks: list, who: str,
                 terms: bool = True) -> tuple[sqlite3.Row, list[str]]:
    """Общая нота: `picks` — [(клиника, вариант, срок)], плательщик — `payer` (первая клиника
    среди строк) → (нота, reference заменённых нот). Сумма строки — по правилу цены её клиники
    (tiers.price), нота — их сумма. Открытые ноты этих клиник и прежние открытые общие с любой из
    них отклоняются «заменена общей нотой» (долг у клиники один). ⛔ ValueError: 'empty',
    'too_many' (GROUP_MAX), 'months', 'tier' (вариант не продаётся этой клинике)."""
    if not picks:
        raise ValueError("empty")
    if len(picks) > GROUP_MAX:
        raise ValueError("too_many")
    rows = []
    for clinic, tier, months in picks:
        if months not in MONTHS:
            raise ValueError("months")
        sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
        a = amount_for(sub, tier, months) if tier in tiers.TIERS else 0
        if a <= 0:
            raise ValueError("tier")
        rows.append((clinic, tier, months, a))
    now = datetime.now(timezone.utc)
    ref = next_reference(con, now)
    replaced = []
    olds = {}
    for clinic, *_ in rows:
        for p in (group_of(con, clinic["id"]), open_of(con, clinic["id"])):
            if p is not None:
                olds[p["id"]] = p
    for p in olds.values():
        reject(con, p, f"заменена общей нотой {ref}", who)
        replaced.append(p["reference"])
    total = sum(a for *_, a in rows)
    con.execute("""INSERT INTO payments(clinic_id, amount, currency, method, status, reference, months, kind,
                                        terms_at, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (payer["id"], total, "MDL", TRANSFER, PENDING, ref, 0, CABINET,
                 db.now_iso() if terms else None, db.now_iso()))
    p = con.execute("SELECT * FROM payments WHERE reference=?", (ref,)).fetchone()
    for clinic, tier, months, a in rows:
        con.execute("INSERT INTO payment_lines(payment_id, clinic_id, tier, months, amount) VALUES(?,?,?,?,?)",
                    (p["id"], clinic["id"], tier, months, a))
    what = "; ".join(f"{c['name']} — {tiers.NAME[t]}, {m} мес., {a} MDL" for c, t, m, a in rows)
    db.audit(con, who, "payment_new", payer["id"],
             f"{ref}: {total} MDL, общая нота ({len(rows)} клиник: {what}), перевод"
             + (", условия приняты" if terms else "") + (f"; взамен {', '.join(replaced)}" if replaced else ""))
    return p, replaced


def notify_paid(con: sqlite3.Connection, payment: sqlite3.Row, who: str) -> list[tuple[bool, mail.Letter | str]]:
    """Письма после оплаты — СОБРАТЬ в транзакции оплаты (снимок cont de plată, код ящика —
    записи в базу), отправить после её commit (`send_paid`, `outbox`). По виду: пакет SMS →
    «pachetul a fost activat», абонемент → письмо о лицензии (license.letter_latest).
    Список (плательщик?, письмо или код отказа). Общая нота — письмо о лицензии КАЖДОЙ
    клинике строки на её ящик; cont de plată и строки оплаты — в письме плательщику."""
    clinic = con.execute("SELECT * FROM clinics WHERE id=?", (payment["clinic_id"],)).fetchone()
    fresh = con.execute("SELECT * FROM payments WHERE id=?", (payment["id"],)).fetchone()
    # cont de plată (17.10) — вложением в то же письмо, что говорит об оплате; строки оплаты
    # в тексте (№, что, сумма, дата, поставщик — требование maib) — из того же снимка
    receipt = receipts.attachment(con, fresh, who)
    row = receipts.get(con, fresh["id"]) if receipt else None
    summary = receipts.summary(row) if row is not None else ""
    if payment["kind"] == CABINET:
        out = []
        for ln in lines_of(con, payment["id"]):
            c = con.execute("SELECT * FROM clinics WHERE id=?", (ln["clinic_id"],)).fetchone()
            payer = c["id"] == payment["clinic_id"]
            out.append((payer, license.letter_latest(con, c, who, receipt=receipt if payer else None,
                                                     summary=summary if payer else "")))
        return out
    if payment["kind"] in (SMS, SMS_NAME):
        return [(True, (sms.letter_pack if payment["kind"] == SMS else sms.letter_name)(
            con, clinic, fresh, who, receipt=receipt, summary=summary))]
    return [(True, license.letter_latest(con, clinic, who, receipt=receipt, summary=summary))]


def send_paid(letters: list[tuple[bool, mail.Letter | str]]) -> str:
    """Отправить письма `notify_paid` — только ПОСЛЕ commit оплаты, вне транзакции: SMTP до
    30 с под замком записи валил соседние записи. Код письма плательщика для ?msg= ('' —
    ушло); отказ SMTP — лог, оплата не откатывается."""
    code = ""
    for payer, letter in letters:
        out = mail.deliver(letter) if isinstance(letter, mail.Letter) else letter
        code = out if payer else code
    return code


class Outbox:
    """Письма об оплате, собранные в транзакции; `code` — после выхода из `outbox`."""

    def __init__(self) -> None:
        self.letters: list[tuple[bool, mail.Letter | str]] = []
        self.code = ""

    def add(self, letters: list[tuple[bool, mail.Letter | str]]) -> None:
        self.letters += letters


@contextlib.contextmanager
def outbox():
    """`with payments.outbox() as box, db.connect(immediate=True) as con:` — письма, собранные
    в транзакции (`box.add(notify_paid(...))`), уходят после её commit. ⛔ Порядок важен:
    выходы идут справа налево — connect раньше outbox, иначе SMTP снова под замком. Исключение
    в транзакции — откат, и письма не уходят; `return` из блока — commit, потом письма."""
    box = Outbox()
    yield box
    box.code = send_paid(box.letters)


def subject(p: sqlite3.Row, con: sqlite3.Connection | None = None) -> str:
    """Что оплачивается — одной строкой по-румынски (описание у maib, страница возврата).
    Общая нота с `con` — с числом клиник."""
    kind = p["kind"] or LICENSE
    if kind == CABINET:
        n = len(lines_of(con, p["id"])) if con is not None else 0
        return f"abonament DentPilot, notă comună pentru {n} clinici" if n else "abonament DentPilot, notă comună"
    if kind == SMS:
        return f"pachet {p['sms_units']} SMS"
    if kind == SMS_NAME:
        return "nume de expeditor SMS, un an"
    return f"abonament {tiers.NAME.get(p['tier'], tiers.NAME[tiers.PLUS])}, {mail.luni(int(p['months'] or 1))}"


def attempt(con: sqlite3.Connection, pay_id: str | None) -> sqlite3.Row | None:
    """Попытка оплаты картой по payId (pay_attempts, миграция 15)."""
    if not pay_id:
        return None
    return con.execute("SELECT * FROM pay_attempts WHERE provider_id=?", (pay_id,)).fetchone()


def by_pay_id(con: sqlite3.Connection, pay_id: str | None) -> sqlite3.Row | None:
    """Платёж по ЛЮБОМУ своему payId — последнему или прежней попытке (callback, страница
    возврата): клиника могла заплатить во вкладке со старой ссылкой."""
    a = attempt(con, pay_id)
    if a is not None:
        return con.execute("SELECT * FROM payments WHERE id=?", (a["payment_id"],)).fetchone()
    if not pay_id:
        return None
    return con.execute("SELECT * FROM payments WHERE provider_id=?", (pay_id,)).fetchone()


LINK_MARGIN = 60          # секунд: ссылку старше PAY_TTL − запас клинике не отдаём — не успеет заплатить
LINK = "link"             # исход card_record: адрес maib, куда вести браузер
MAIB_FAILED = "maib_failed"   # исход card_record: maib не дал ссылку (нота остаётся как была)


@dataclass
class Card:
    """Ссылка maib к ожидающей ноте в три шага (30.10, ревью транзакций): сеть — ВНЕ
    транзакции. maib думает до maib.TIMEOUT на вызов; под замком записи это время ждали все
    соседние записи (callback, /v1/license, кабинет), а дольше 10 с — «database is locked».
    `card_plan` (в транзакции: снимок ноты и последней попытки) → commit → `card_ask` (без
    базы: maib) → `card_record` (новая короткая транзакция: перечитать и записать)."""
    payment_id: int
    reference: str
    amount: int
    description: str
    email: str
    client_ip: str
    last: sqlite3.Row | None            # последняя попытка без окончательного ответа maib
    truth: dict | None = None           # ответ maib о ней (maib.info)
    reuse: str = ""                     # её ссылка — ещё жива и молода, отдать снова
    new: tuple[str, str] | None = None  # новая попытка у maib: (payId, адрес)
    error: str = ""                     # maib не дал новую ссылку


def card_plan(con: sqlite3.Connection, payment: sqlite3.Row, clinic: sqlite3.Row,
              client_ip: str = "127.0.0.1") -> Card:
    """Шаг 1, в транзакции вызывающего: всё, что maib нужно знать, — снимком.
    ⛔ Не в ожидании — ValueError('not_pending')."""
    if payment["status"] != PENDING:
        raise ValueError("not_pending")
    last = attempt(con, payment["provider_id"])
    return Card(payment["id"], payment["reference"], int(payment["amount"]),
                f"DentPilot {payment['reference']}: {subject(payment, con)} — {clinic['name']}",
                clinic["email"] or "", client_ip, last if last is not None and not last["final"] else None)


def card_ask(card: Card, fresh: bool = False) -> Card:
    """Шаг 2, вне транзакции: спросить maib. Кнопка «Plătește cu cardul»: есть живая попытка —
    сперва её статус (OK — запишет settle; ещё идёт и моложе PAY_TTL − запас — та же ссылка,
    вторая вкладка не плодит платежей у maib; maib молчит про неё — та же, если молода),
    иначе новая попытка. `fresh` — «ссылка» админки: всегда новая (взамен не прошедшей).
    Две вкладки разом могут создать у maib две попытки — card_record запишет обе."""
    last = None if fresh else card.last
    if last is not None:
        created = db.parse_ts(last["created_at"])
        young = created is not None and \
            (datetime.now(timezone.utc) - created).total_seconds() < maib.PAY_TTL - LINK_MARGIN
        try:
            card.truth = maib.info(last["provider_id"])
        except maib.MaibError:
            card.truth = None
        status = str((card.truth or {}).get("status") or "").upper()
        if status == maib.STATUS_OK:
            return card
        if young and (card.truth is None or status in maib.WAITING):
            card.reuse = last["pay_url"]
            return card
    try:
        card.new = maib.create(card.amount, card.reference, card.description, card.email, card.client_ip)
    except maib.MaibError as e:
        card.error = str(e)
    return card


def card_record(con: sqlite3.Connection, card: Card, who: str) -> tuple[str, str, sqlite3.Row]:
    """Шаг 3, под замком записи (`db.connect(immediate=True)`): перечитать ноту и записать, что
    сказал maib. → (исход, адрес, платёж): (LINK, адрес maib) — вести браузер; (SETTLED_PAID, '')
    — maib сказал «оплачено» (письмо — вызывающему, по возвращённому платежу); (SETTLED_ALREADY,
    '') — нота закрылась, пока maib думал (callback, другая вкладка, админ); (MAIB_FAILED, текст).

    Ответ о прежней попытке — через settle, единственный путь к `paid`. Новая попытка — в
    pay_attempts всегда (⛔ payId вслепую не заменяется: прежние остаются узнаваемыми,
    by_pay_id), в строку ноты (последняя) и журнал `card_link` — только пока нота ждёт."""
    p = con.execute("SELECT * FROM payments WHERE id=?", (card.payment_id,)).fetchone()
    if card.truth is not None and card.last is not None:
        # попытка могла переехать на другую строку (зачёт повторного платежа) — платёж по ней
        target = by_pay_id(con, card.last["provider_id"]) or p
        outcome = settle(con, target, card.truth, who)
        if outcome == SETTLED_PAID:
            return SETTLED_PAID, "", target
        p = con.execute("SELECT * FROM payments WHERE id=?", (card.payment_id,)).fetchone()
    if card.new is not None:
        pay_id, pay_url = card.new
        con.execute("INSERT INTO pay_attempts(provider_id, payment_id, pay_url, created_at) VALUES(?,?,?,?)",
                    (pay_id, card.payment_id, pay_url, db.now_iso()))
        if p["status"] == PENDING:
            con.execute("UPDATE payments SET method=?, provider_id=?, pay_url=?, provider_status='' WHERE id=?",
                        (CARD, pay_id, pay_url, p["id"]))
            db.audit(con, who, "card_link", p["clinic_id"], f"{p['reference']}: maib {pay_id}")
            return LINK, pay_url, con.execute("SELECT * FROM payments WHERE id=?", (p["id"],)).fetchone()
    if p["status"] != PENDING:
        return SETTLED_ALREADY, "", p
    if card.reuse:
        return LINK, card.reuse, p
    return MAIB_FAILED, card.error, p


EXPIRED = "TIMEOUT"       # ссылка maib прожила PAY_TTL без оплаты: это не «карта не прошла»


def settle(con: sqlite3.Connection, payment: sqlite3.Row, result: dict, who: str) -> str:
    """Применить ответ maib о платеже (maib.info — статус checkout в наших словах): SETTLED_*.

    ⛔ Единственное место, где статус maib становится нашим `paid`, — и только
    статус OK. Всё, что не OK и не ожидание, — «не прошёл»: строка остаётся в
    ожидании (долг стоит, перевод по reference по-прежнему возможен), а слова
    maib ложатся в provider_status и журнал (`card_failed`; протухшая ссылка —
    TIMEOUT — без строки: её не открывали). Не в ожидании — ничего: второе
    подтверждение не продлевает (инвариант 3).
    `result.payId` — любая попытка ЭТОГО платежа (pay_attempts), не только последняя;
    окончательный ответ закрывает попытку (`final`): ежедневная задача её больше не спрашивает."""
    pay_id = result.get("payId")
    att = attempt(con, pay_id)
    if pay_id != payment["provider_id"] and (att is None or att["payment_id"] != payment["id"]):
        raise ValueError("foreign")
    status = str(result.get("status") or "").upper()
    detail = " ".join(str(result.get(k) or "") for k in ("status", "statusCode", "statusMessage")).strip()
    if pay_id == payment["provider_id"]:
        con.execute("UPDATE payments SET provider_status=? WHERE id=?", (detail[:120], payment["id"]))
    if att is not None:
        con.execute("UPDATE pay_attempts SET status=?, final=? WHERE provider_id=?",
                    (detail[:120], 0 if status in maib.WAITING else 1, pay_id))
    counted = bool(att["counted"]) if att is not None else payment["paid_via"] == CARD
    if payment["status"] != PENDING:
        # ⭐ Нота уже закрыта ДРУГИМ путём (перевод подтверждён, нота отклонена, другая
        # попытка картой), а maib говорит, что ЭТА карта прошла: деньги клиники у нас
        # дважды — зачесть как следующий период, а не промолчать. Деньги этой попытки уже
        # зачтены — ничего (инвариант 3).
        if status == maib.STATUS_OK and not counted:
            credit_again(con, payment, CARD, who, pay_id=pay_id)
            return SETTLED_PAID
        return SETTLED_ALREADY
    if status == maib.STATUS_OK:
        confirm(con, payment, who, via=CARD)
        con.execute("UPDATE payments SET method=? WHERE id=?", (CARD, payment["id"]))
        con.execute("UPDATE pay_attempts SET counted=1 WHERE provider_id=?", (pay_id,))
        return SETTLED_PAID
    if status in maib.WAITING:
        return SETTLED_WAITING
    if status != EXPIRED:
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
    con.execute("UPDATE payments SET status=?, paid_at=?, confirmed_by=?, paid_via=? WHERE id=? AND status=?",
                (PAID, db.now_iso(), who, via, payment["id"], PENDING))
    if payment["kind"] == CABINET:
        # общая нота (26.10): каждая клиника строки — своим продлением и своим файлом
        first, items = None, []
        for ln in lines_of(con, payment["id"]):
            c = con.execute("SELECT * FROM clinics WHERE id=?", (ln["clinic_id"],)).fetchone()
            issued, period = _prolong(con, c, ln, payment, who, note=" (общая нота)")
            first = first or issued
            items.append(receipts.line_item(c, ln, period))
        receipts.create(con, payment["id"], who, items=items)
        return first or (0, "")
    issued, period = _prolong(con, clinic, payment, payment, who)
    # cont de plată (17.10): снимок оплаты с оплаченным сроком — от начала периода до нового конца
    receipts.create(con, payment["id"], who, period=period)
    return issued


def _prolong(con: sqlite3.Connection, clinic: sqlite3.Row, line: sqlite3.Row, payment: sqlite3.Row, who: str,
             note: str = "") -> tuple[tuple[int, str], tuple[datetime, datetime]]:
    """Продление клиники по оплаченной строке (`line` — своя нота или строка общей: вариант,
    срок, сумма): срок от большей из дат с якорем, файл, вариант и цена подписки, модуль SMS.
    → (выдача, (начало периода, новый конец)) — период для cont de plată."""
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic["id"],)).fetchone()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    current = db.parse_ts(sub["valid_until"]) if sub else None
    first = advance_start(con, clinic["id"])
    if first is not None and current is not None and current >= now:
        # первая нота клиники из кабинета оплачена в срок: период — от дня заведения (ADVANCE);
        # опоздала (срок на оплату прошёл) — как любая поздняя оплата, от сегодня
        day = first.day
        valid = add_months(first, int(line["months"]), day)
    else:
        day = anchor_day(current, now, sub["anchor_day"] if sub else None)
        valid = extend_from(current, int(line["months"]), now, day)
    grace = valid + timedelta(days=license.GRACE_DAYS)
    tier, price, sms_until, switch = tier_after(sub, line, now)
    db.audit(con, who, "payment_paid", clinic["id"],
             f"{payment['reference']}{note}: {line['amount']} MDL, {tiers.NAME[tier]}, срок до {valid.strftime(db.TS)}"
             + (f"; {switch}" if switch else ""))
    issued = license.issue(con, clinic, "standard", valid, grace,
                           f"платёж {payment['reference']}", who)
    # якорь и вариант — после выдачи: она заводит строку подписки, если её ещё не было
    con.execute("UPDATE subscriptions SET anchor_day=?, tier=?, price=?, sms_until=? WHERE clinic_id=?",
                (day, tier, price, sms_until, clinic["id"]))
    start = first if first is not None and current is not None and current >= now else (
        now if current is None or current < now else current)
    return issued, (start, valid)


def advance_start(con: sqlite3.Connection, clinic_id: str) -> datetime | None:
    """Начало срока на оплату первой ноты (ADVANCE) — пока он последняя выдача клиники; иначе None."""
    row = con.execute("SELECT reason, issued_at FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1",
                      (clinic_id,)).fetchone()
    return db.parse_ts(row["issued_at"]) if row is not None and row["reason"] == ADVANCE else None


def tier_after(sub: sqlite3.Row | None, payment: sqlite3.Row, now: datetime) -> tuple[str, int, str | None, str]:
    """Подписка после оплаты ноты абонемента: (вариант, цена месяца, sms_until, строка для журнала).

    Цена — прайс варианта (tiers.price; Олег 26.10: «600 везде»), записью в подписку; прайса
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


def set_tier(con: sqlite3.Connection, clinic_id: str, tier: str, who: str) -> str:
    """Карточка › «Вариант вручную» — для исключений (Олег 23.10): вариант сразу, без оплаты.
    Plus — модуль SMS сразу; Basic — модуль гаснет сразу (переход «с конца периода» даёт
    только оплата). Цена — прайс варианта: своей цены у подписки нет (Олег 26.10: «600
    везде»), разовая скидка — суммой ноты в «Выставить ноту». '' или код отказа: tier_bad,
    tier_trial (пробный — всегда Plus, вариант выбирают при оплате), tier_no_sub (подписки
    нет), tier_price (у варианта нет прайса в cloud.env — не продаётся)."""
    if tier not in tiers.TIERS:
        return "tier_bad"
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic_id,)).fetchone()
    if sub is None:
        return "tier_no_sub"
    if sub["plan"] == "trial":
        return "tier_trial"
    p = tiers.price(sub, tier)
    if p <= 0:
        return "tier_price"
    before = tiers.current(sub)
    con.execute("UPDATE subscriptions SET tier=?, price=?, sms_until=NULL, updated_at=? WHERE clinic_id=?",
                (tier, p, db.now_iso(), clinic_id))
    db.audit(con, who, "tier_set", clinic_id,
             f"вручную: {tiers.NAME[before]} → {tiers.NAME[tier]}, {p} MDL / мес.; модуль SMS "
             + ("работает" if tier == tiers.PLUS else "выключен сразу"))
    return ""


def credit_again(con: sqlite3.Connection, payment: sqlite3.Row, via: str, who: str,
                 pay_id: str | None = None) -> sqlite3.Row:
    """Второй платёж по уже закрытой ноте — следующий период отдельной строкой.

    Новая строка: новый reference, те же сумма и срок, `via` — чем пришли деньги.
    Карта: payId `pay_id` (по умолчанию — последний у ноты) и его ссылка переезжают
    со старой строки на новую, попытка — тоже: следующий callback того же платежа
    найдёт её уже оплаченной этой картой и ничего не продлит (инвариант 3); старая
    строка остаётся в истории без этой ссылки.
    ⛔ Ожидающую ноту так не закрыть — для неё «Подтвердить» (ValueError('pending'))."""
    if payment["status"] == PENDING:
        raise ValueError("pending")
    now = datetime.now(timezone.utc)
    ref = next_reference(con, now)
    provider_id = (pay_id or payment["provider_id"]) if via == CARD else None
    att = attempt(con, provider_id)
    pay_url = (att["pay_url"] if att is not None else payment["pay_url"]) if via == CARD else None
    if provider_id and provider_id == payment["provider_id"]:
        con.execute("UPDATE payments SET provider_id=NULL WHERE id=?", (payment["id"],))
    con.execute("""INSERT INTO payments(clinic_id, amount, currency, method, status, reference, months,
                                        provider_id, pay_url, created_at, kind, sms_units, tier)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (payment["clinic_id"], payment["amount"], payment["currency"], via, PENDING, ref,
                 payment["months"], provider_id, pay_url, db.now_iso(), payment["kind"], payment["sms_units"],
                 payment["tier"]))
    new = con.execute("SELECT * FROM payments WHERE reference=?", (ref,)).fetchone()
    # общая нота зачитывается вся, с теми же строками
    con.execute("INSERT INTO payment_lines(payment_id, clinic_id, tier, months, amount) "
                "SELECT ?, clinic_id, tier, months, amount FROM payment_lines WHERE payment_id=?",
                (new["id"], payment["id"]))
    if att is not None:
        con.execute("UPDATE pay_attempts SET payment_id=? WHERE provider_id=?", (new["id"], provider_id))
    db.audit(con, who, "payment_repeat", payment["clinic_id"],
             f"{payment['reference']} ({payment['status']}): второй платёж "
             f"{'картой' if via == CARD else 'переводом'} зачтён как {ref}")
    confirm(con, new, who, via=via)
    if att is not None:
        con.execute("UPDATE pay_attempts SET counted=1, final=1 WHERE provider_id=?", (provider_id,))
    return con.execute("SELECT * FROM payments WHERE id=?", (new["id"],)).fetchone()


def reject(con: sqlite3.Connection, payment: sqlite3.Row, reason: str, who: str) -> None:
    if payment["status"] != PENDING:
        raise ValueError("not_pending")
    con.execute("UPDATE payments SET status=?, confirmed_by=? WHERE id=? AND status=?",
                (REJECTED, who, payment["id"], PENDING))
    db.audit(con, who, "payment_rejected", payment["clinic_id"],
             f"{payment['reference']}: {reason or 'без причины'}")
