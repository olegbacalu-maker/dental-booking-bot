"""Общие помощники маршрутов облака (03.11, разнос main.py): то, что зовут два роутера и больше.

Роутеры зовут их через модуль (`web.guard(request)`), не `from .web import …`: так их вызовы
видит разбор `tests/test_tx.py` (транзакции и письма) — по имени «модуль.функция».
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from . import auth, config, db, maib, mail, payments, paylink, receipts, sms
from . import terms as terms_mod  # `terms` здесь — параметр-галочка (sms_pack_note, sms_name_note)

log = logging.getLogger("cloud")


def months(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        return 0


def card_go(plan: payments.Card, who: str, back: str, gone: str = "note_gone", paid: str = "card_paid") -> Response:
    """Клик «Plătește cu cardul», шаги 2–3 (нота и снимок `plan` уже закоммичены вызывающим):
    maib — вне транзакции (payments.card_ask), запись ответа — короткой под замком записи
    (payments.card_record). → браузер на страницу maib или назад: `paid` (maib сказал
    «оплачено» — письмо об оплате после commit; или нота уже оплачена картой; у ноты SMS свой
    код — её слова не про срок), `gone` (нота закрылась иначе, пока maib думал), maib_failed."""
    payments.card_ask(plan)
    with payments.outbox() as box, db.connect(immediate=True) as con:
        outcome, url, p = payments.card_record(con, plan, who)
        if outcome == payments.SETTLED_PAID:
            box.add(payments.notify_paid(con, p, who))
    if outcome == payments.LINK:
        return RedirectResponse(url, status_code=303)
    if outcome == payments.MAIB_FAILED:
        log.warning("ссылка maib для %s не создана: %s", plan.reference, url)
        code = "maib_failed"
    elif outcome == payments.SETTLED_PAID or (p["status"] == payments.PAID and p["paid_via"] == payments.CARD):
        code = paid
    else:
        code = gone
    return RedirectResponse(f"{back}{'&' if '?' in back else '?'}msg={code}", status_code=303)


def guard(request: Request) -> RedirectResponse | None:
    if auth.current_user(request) is None:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def clinic(con, cid: str):
    return con.execute("SELECT * FROM clinics WHERE id=?", (cid,)).fetchone()


def cont_terms(con, note, fresh: bool, who: str, addr: str) -> int:
    """Галочка условий в кабинете перед нотой (07.11, Олег: «Да, писать акт»): отметка в
    `payments.terms_at` ноты и акт акцепта — тем же `terms.record`, что у страницы оплаты (версия
    CURRENT, source=pay, кто — контакт клиники, адрес браузера; `who` — учётная запись кабинета, в
    журнал), в транзакции записи вызывающего (`immediate=True`). ⛔ Один акт на ноту: акт пишется,
    только когда галочка у ЭТОЙ ноты новая — нота заведена сейчас (`fresh`, её terms_at поставил
    create) или её terms_at был пуст (нота админки или программы); повторный клик к той же ноте акта
    не пишет, а возврат со страницы банка и callback галочки не видят вовсе. Клиника акта — клиника
    ноты; у общей ноты — каждая клиника её строк. → сколько актов записано."""
    if not (payments.mark_terms(con, note) or fresh):
        return 0
    ids = ([ln["clinic_id"] for ln in payments.lines_of(con, note["id"])] if note["kind"] == payments.CABINET
           else [note["clinic_id"]])
    for cid in dict.fromkeys(ids):
        c = clinic(con, cid)
        terms_mod.record(con, cid, terms_mod.CURRENT, c["contact_name"] or "", terms_mod.SRC_PAY, addr, who=who)
    return len(dict.fromkeys(ids))


def pending_count(con) -> int:
    return con.execute("SELECT count(*) FROM payments WHERE status='pending'").fetchone()[0]


def names_count(con) -> int:
    """Имена отправителей, ждущие Олега (заявка или подано): счётчик у раздела «SMS»."""
    return con.execute("SELECT count(*) FROM sms_accounts WHERE sender_state IN (?, ?)",
                       (sms.S_REQUESTED, sms.S_SUBMITTED)).fetchone()[0]


def payment_letter(con, c, p, who: str) -> mail.Letter | str:
    """Письмо с нотой абонемента — СОБРАТЬ в транзакции (paylink.for_mail заводит ссылку
    страницы оплаты — запись в базу), отправить после её commit (`payments.outbox`): SMTP до
    30 с под замком записи валил соседние записи. Страница оплаты клиники — и для карты, и
    для смены варианта; ссылки maib в письме нет (живёт минуты, maib.PAY_TTL). Общая нота
    кабинета (26.10) — плательщику, со строками по клиникам. Код отказа: bad_email, no_bank."""
    if p["kind"] == payments.CABINET:
        c = clinic(con, p["clinic_id"])
    if not c["email"]:
        return "bad_email"
    page = paylink.for_mail(con, c, who)
    try:
        if p["kind"] == payments.CABINET:
            subject, body = mail.group_letter(c["name"], p["reference"], p["amount"], payments.lines_of(con, p["id"]),
                                              pay_url=page if maib.enabled() else None, page=page)
        else:
            subject, body = mail.payment_letter(c["name"], p["reference"], p["amount"], p["months"],
                                                pay_url=page if maib.enabled() else None, tier=p["tier"],
                                                page=page)
    except RuntimeError:
        return "no_bank"
    return mail.Letter(c["email"], subject, body, c["id"], who, f"нота {p['reference']}",
                       f"письмо с нотой {p['reference']}")


def payment(con, pid: int):
    return con.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()


# Кому пакет SMS не продаётся (sms.blocked): выключенной клинике, без права по плану и на Basic
# (модуль погашен). Без одобренного имени пополнение продаётся — SMS уходят от общего имени.
SMS_CLOSED = ("sms_unconfigured", "sms_not_offered", "sms_off", "sms_plan", "sms_basic")


def sms_pack_note(con, c, units: int, who: str, terms: bool = False) -> tuple[str, object, str]:
    """Нота за пакет SMS — ОДНА логика на две двери: программа (`/v1/sms/order`) и кабинет
    (`/cont/sms/nota`). → (код отказа sms.CODES или '', нота, payments.CREATED | EXISTS | REPLACED).
    Пакет — только из `config.SMS_PACKS` (цена оттуда же, не из формы); IDNO обязателен; открытая
    нота вида `sms` у клиники одна. Тот же пакет — она же (сумма прежняя); ДРУГОЙ — она отклоняется
    с причиной «заменена» и выставляется новая, как у абонемента (payments.choose): долг один, а
    оплата по прежней ноте, если всё же придёт, зачтётся её пакетом (credit_again), деньги не
    теряются. В транзакции записи вызывающего (`immediate=True`)."""
    if not config.SMS_PACKS:
        return "sms_no_packs", None, ""
    if units not in config.SMS_PACKS:
        return "sms_pack", None, ""
    if len(c["idno"] or "") != 13:
        return "sms_need_idno", None, ""
    acc = sms.ensure(con, c["id"])
    why = sms.blocked(con, c["id"], acc, datetime.now(timezone.utc))
    if why in SMS_CLOSED:
        return why, None, ""
    old = payments.open_of(con, c["id"], payments.SMS)
    if old is not None and int(old["sms_units"] or 0) == units:
        return "", old, payments.EXISTS
    if old is not None:
        payments.reject(con, old, f"заменена: клиника выбрала пакет {units} SMS", who)
    p = payments.create_pack(con, c, units, config.SMS_PACKS[units], who, terms=terms)
    return "", p, (payments.REPLACED if old is not None else payments.CREATED)


def sms_name_note(con, c, who: str, terms: bool = False) -> tuple[str, object, object, bool]:
    """Нота за год своего имени отправителя — та же одна логика на программу и кабинет.
    → (код отказа sms.CODES или '', клиника-хозяйка имени, нота, создана ли сейчас). Имя общее на
    кабинет (26.10): нота — ГЛАВНОЙ клинике, на её ящик, кто бы из клиник кабинета ни заказал;
    заказать можно, когда имя запрошено, подано или одобрено; открытая нота вида одна."""
    if not config.SMS_NAME_PRICE:
        return "sms_no_name", None, None, False
    if len(c["idno"] or "") != 13:
        return "sms_need_idno", None, None, False
    acc = sms.ensure(con, c["id"])
    why = sms.blocked(con, c["id"], acc, datetime.now(timezone.utc))
    if why in SMS_CLOSED:
        return why, None, None, False
    owner = clinic(con, sms.name_owner(con, c["id"]))
    acc = sms.ensure(con, owner["id"])
    if acc["sender_state"] not in (sms.S_REQUESTED, sms.S_SUBMITTED, sms.S_ACTIVE):
        return "sms_name_none", None, None, False
    p = payments.open_of(con, owner["id"], payments.SMS_NAME)
    if p is not None:
        return "", owner, p, False
    return "", owner, payments.create_name(con, owner, config.SMS_NAME_PRICE, who, terms=terms), True


def sms_open_notes(con, c, who: str = "program") -> list[dict]:
    """Ожидающие ноты SMS клиники — программе, вместе со счётом (`/v1/sms/account`, 05.11): экран
    Setări › SMS держит блок ноты, пока она ждёт оплаты, а не одну строку до ухода с экрана. Пакет —
    нота самой клиники, год имени — нота хозяйки имени кабинета (sms.name_owner). Поля — те же, что
    в ответе заказа (`/v1/sms/order`); `pay_url` — наша страница оплаты, только при настроенном maib
    (ссылки банка нет: она живёт минуты). ⚠️ Поле новое: программа ≤ 2.9.1 его не читает."""
    out = []
    owner = clinic(con, sms.name_owner(con, c["id"]))
    for kind, buyer in ((payments.SMS, c), (payments.SMS_NAME, owner)):
        p = payments.open_of(con, buyer["id"], kind)
        if p is None:
            continue
        out.append({"kind": kind, "reference": p["reference"], "amount": int(p["amount"]), "units": p["sms_units"],
                    "pay_url": paylink.for_mail(con, buyer, who) if maib.enabled() else None})
    return out


def sms_note_letter(con, c, p, who: str) -> mail.Letter | str:
    """Письмо с нотой SMS (пакет, год имени) — СОБРАТЬ в транзакции (paylink.for_mail заводит
    ссылку страницы оплаты), отправить после её commit (`payments.outbox`), как письмо с нотой
    абонемента. Карта — строкой со страницей оплаты, когда maib настроен. Код отказа: bad_email,
    no_bank."""
    if not c["email"]:
        return "bad_email"
    page = paylink.for_mail(con, c, who) if maib.enabled() else None
    try:
        if p["kind"] == payments.SMS_NAME:
            acc = sms.account(con, c["id"])
            subject, body = mail.sms_name_note_letter(c["name"], p["reference"], int(p["amount"]),
                                                      acc["sender"] if acc is not None else "", page)
        else:
            subject, body = mail.sms_pack_note_letter(c["name"], p["reference"], int(p["amount"]),
                                                      int(p["sms_units"]), page)
    except RuntimeError:
        return "no_bank"
    return mail.Letter(c["email"], subject, body, c["id"], who, f"нота {p['kind']} {p['reference']}",
                       f"письмо с нотой SMS {p['reference']}")


def pdf(row) -> Response:
    """Cont de plată из снимка — в окно браузера, с именем файла для «Сохранить»."""
    return Response(receipts.render(row), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{receipts.filename(row["number"])}"'})
