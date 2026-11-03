"""Общие помощники маршрутов облака (03.11, разнос main.py): то, что зовут два роутера и больше.

Роутеры зовут их через модуль (`web.guard(request)`), не `from .web import …`: так их вызовы
видит разбор `tests/test_tx.py` (транзакции и письма) — по имени «модуль.функция».
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from . import auth, db, maib, mail, payments, paylink, receipts, sms

log = logging.getLogger("cloud")


def months(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        return 0


def card_go(plan: payments.Card, who: str, back: str, gone: str = "note_gone") -> Response:
    """Клик «Plătește cu cardul», шаги 2–3 (нота и снимок `plan` уже закоммичены вызывающим):
    maib — вне транзакции (payments.card_ask), запись ответа — короткой под замком записи
    (payments.card_record). → браузер на страницу maib или назад: card_paid (maib сказал
    «оплачено» — письмо об оплате после commit; или нота уже оплачена картой), `gone` (нота
    закрылась иначе, пока maib думал), maib_failed."""
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
        code = "card_paid"
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


def pdf(row) -> Response:
    """Cont de plată из снимка — в окно браузера, с именем файла для «Сохранить»."""
    return Response(receipts.render(row), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{receipts.filename(row["number"])}"'})
