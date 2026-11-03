"""Платежи в админке (03.11, из main.py): ожидающие и оплаченные, нота из карточки, карта
maib кнопкой («Проверить», «Ссылка»), «Подтвердить», «Зачесть повторный», письмо, отказ, cont de
plată. settle, confirm, credit_again — только под `db.connect(immediate=True)` (test_tx)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import auth, db, maib, payments, receipts, sms, tiers, views, web

log = logging.getLogger("cloud")
router = APIRouter()


# ---------- платежи (L8) ----------


_PENDING_SQL = """SELECT p.*, c.name AS clinic FROM payments p JOIN clinics c ON c.id = p.clinic_id
                  WHERE p.status = 'pending' ORDER BY p.id"""


_PAID_SQL = """SELECT p.*, c.name AS clinic FROM payments p JOIN clinics c ON c.id = p.clinic_id
               WHERE p.status = 'paid' ORDER BY p.paid_at DESC, p.id DESC"""
# причина отказа живёт только в журнале («REF: причина», payments.reject)
_REJECTED_SQL = """SELECT p.*, c.name AS clinic,
                          (SELECT a.detail FROM audit a WHERE a.what = 'payment_rejected' AND a.clinic_id = p.clinic_id
                           AND a.detail LIKE p.reference || ':%' ORDER BY a.id DESC LIMIT 1) AS why
                   FROM payments p JOIN clinics c ON c.id = p.clinic_id
                   WHERE p.status = 'rejected' ORDER BY p.id DESC LIMIT 100"""


@router.get("/admin/payments", response_class=HTMLResponse)
def payments_pending(request: Request, msg: str = "", month: str = "") -> Response:
    """Платежи (17.10 — вкладки): ждут подтверждения, оплачены (по месяцам, с суммой), отклонены."""
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_PENDING_SQL).fetchall()
        paid = con.execute(_PAID_SQL).fetchall()
        rejected = con.execute(_REJECTED_SQL).fetchall()
        names = web.names_count(con)
    # месяц оплаты — по Кишинёву, как сутки SMS: деньги 31-го в 23:30 — доход того месяца
    now = datetime.now(timezone.utc)
    by_month: dict[str, list] = {sms.local(now).strftime("%Y-%m"): []}
    for p in paid:
        by_month.setdefault(sms.local(db.parse_ts(p["paid_at"]) or now).strftime("%Y-%m"), []).append(p)
    months = sorted(by_month, reverse=True)
    month = month if month in by_month else months[0]
    return HTMLResponse(views.payments_page(rows, auth.current_user(request), msg, paid=by_month[month],
                                            month=month, months=months[:12], rejected=rejected, names=names))


@router.post("/admin/clinics/{cid}/payments")
def payment_new(request: Request, cid: str, months: str = Form("1"), amount: str = Form(""),
                send: str = Form(""), method: str = Form(payments.TRANSFER), tier: str = Form("")) -> Response:
    """Платёж: переводом (reference в письме) или картой (L12: плюс ссылка maib).
    Вариант — названный в форме, иначе текущий (tiers.pick); сумма пусто = по правилу
    tiers.price. Три шага, как у страницы оплаты: нота — транзакцией, письмо и maib — после
    её commit, ссылка — своей короткой. maib не ответил — нота остаётся (переводом, reference
    уже её), админ видит maib_failed и позже жмёт «Ссылка на карту» (решение Олега Р1, 30.10:
    иначе админка держала замок записи до 2 × maib.TIMEOUT, и в это время падали callback-и)."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    card = method == payments.CARD
    if card and not maib.enabled():
        return RedirectResponse(f"/admin/clinics/{cid}?msg=no_maib", status_code=303)
    plan = None
    with payments.outbox() as box, db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (cid,)).fetchone()
        t = tier if tier in tiers.TIERS else tiers.pick(sub)
        if t not in tiers.TIERS:
            return RedirectResponse(f"/admin/clinics/{cid}?msg=tier_not_sold", status_code=303)
        try:
            m = int(months)
            # срок не из ряда — отказ даёт payments.create (bad_months), не KeyError здесь
            a = (int(amount) if amount.strip()
                 else payments.amount_for(sub, t, m) if m in payments.MONTHS else 1)
        except ValueError:
            return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_amount", status_code=303)
        if a <= 0 and not amount.strip():
            # вариант без цены в cloud.env — сумму только руками
            return RedirectResponse(f"/admin/clinics/{cid}?msg=tier_not_sold", status_code=303)
        # вторая ожидающая нота не выставляется (03.10): кабинет, страница оплаты и
        # ежедневная задача её не плодят — админка тоже; письмо с прежней — по галочке
        # долг клиники — своя нота или общая нота кабинета, где она строкой (26.10)
        p = payments.debt_of(con, cid)
        if p is not None:
            if card and not p["pay_url"]:
                # карта к УЖЕ ожидающей ноте: ссылка maib к ней, reference прежний; maib молчит — maib_failed ниже
                plan = payments.card_plan(con, p, c, web.ip(request))
                code = "card_link"
            else:
                code = "note_pending"
        else:
            try:
                p = payments.create(con, c, m, a, who, tier=t)
            except ValueError as e:
                return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_{e}", status_code=303)
            code = "payment_created"
            if card:
                plan = payments.card_plan(con, p, c, web.ip(request))
                code = "card_created"
        if send == "1":
            box.add([(True, web.payment_letter(con, c, p, who))])
    if send == "1":
        code = box.code or code + "_mailed"
    if plan is not None:
        payments.card_ask(plan, fresh=True)
        with db.connect(immediate=True) as con:
            outcome, why, _ = payments.card_record(con, plan, who)
        if outcome == payments.MAIB_FAILED:
            log.error("maib: ссылка к ноте %s клиники %s не создана: %s", plan.reference, cid, why)
            code = "maib_failed"
        elif outcome != payments.LINK:
            code = "payment_not_pending"
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)


# ---------- карта: maib (L12) ----------


def _settle_now(con, p, truth: dict, who: str, box: payments.Outbox) -> str:
    """Применить уже полученный ответ maib: код для ?msg=. Истина — статус checkout, не
    callback и не кнопка. `con` — под замком записи, `p` перечитан под ним; письмо об
    оплате — в `box`, уходит после commit."""
    outcome = payments.settle(con, p, truth, who)
    if outcome == payments.SETTLED_PAID:
        box.add(payments.notify_paid(con, p, who))
        return "card_paid"
    return {payments.SETTLED_ALREADY: "payment_not_pending", payments.SETTLED_WAITING: "card_waiting"
            }.get(outcome, "card_failed")


@router.post("/admin/payments/{pid}/check")
def payment_check(request: Request, pid: int) -> Response:
    """Кнопка «Проверить»: тот же вопрос maib, что задают callback и ежедневная задача.
    Короткое чтение → вопрос maib вне транзакции → замок записи, перечитать, settle: callback
    и возврат браузера могли закрыть ноту, пока maib отвечал."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        p = web.payment(con, pid)
    if p is None:
        return Response(status_code=404)
    back = _back(request, p)
    if not p["provider_id"]:
        return RedirectResponse(f"{back}?msg=card_none", status_code=303)
    try:
        truth = maib.info(p["provider_id"])
    except maib.MaibError as e:
        log.error("maib: статус %s не получен: %s", p["reference"], e)
        return RedirectResponse(f"{back}?msg=maib_failed", status_code=303)
    with payments.outbox() as box, db.connect(immediate=True) as con:
        code = _settle_now(con, web.payment(con, pid), truth, auth.current_user(request), box)
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@router.post("/admin/payments/{pid}/link")
def payment_link(request: Request, pid: int) -> Response:
    """Ссылка на карту к ожидающему платежу: первая (платёж заведён переводом) или
    новая взамен не прошедшей. Тот же reference; письмо — если есть e-mail. Снимок —
    чтением, maib — вне транзакции, ссылка и письмо — короткой под замком записи (нота могла
    закрыться, пока maib думал: тогда payment_not_pending, попытка записана в pay_attempts)."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if not maib.enabled():
        return RedirectResponse("/admin/payments?msg=no_maib", status_code=303)
    who = auth.current_user(request)
    with db.connect() as con:
        p = web.payment(con, pid)
        if p is None:
            return Response(status_code=404)
        back = _back(request, p)
        c = web.clinic(con, p["clinic_id"])
        try:
            plan = payments.card_plan(con, p, c, web.ip(request))
        except ValueError:
            return RedirectResponse(f"{back}?msg=payment_not_pending", status_code=303)
    payments.card_ask(plan, fresh=True)
    with payments.outbox() as box, db.connect(immediate=True) as con:
        outcome, why, p = payments.card_record(con, plan, who)
        if outcome == payments.LINK and c["email"]:
            box.add([(True, web.payment_letter(con, c, p, who))])
    if outcome == payments.MAIB_FAILED:
        log.error("maib: ссылка для платежа %s не создана: %s", pid, why)
        return RedirectResponse(f"{back}?msg=maib_failed", status_code=303)
    if outcome != payments.LINK:
        return RedirectResponse(f"{back}?msg=payment_not_pending", status_code=303)
    code = (box.code or "card_link_mailed") if c["email"] else "card_link"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@router.get("/admin/payments/{pid}/cont.pdf")
def payment_receipt(request: Request, pid: int) -> Response:
    """Cont de plată оплаченного платежа (receipts.py, 17.10); не оплачен — 404.
    Оплаченный до таблицы receipts получает снимок при первом запросе."""
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        p = web.payment(con, pid)
        row = receipts.ensure(con, p, auth.current_user(request)) if p is not None else None
    if row is None:
        return Response(status_code=404)
    return web.pdf(row)


def _back(request: Request, p) -> str:
    """Откуда пришли: со страницы ожидающих — туда же, иначе в карточку."""
    # путь без ?…: страница платежей бывает и /admin/payments?msg=… после прошлого действия (17.10)
    ref = request.headers.get("referer", "").split("#")[0].split("?")[0]
    return "/admin/payments" if ref.endswith("/admin/payments") else f"/admin/clinics/{p['clinic_id']}"


@router.post("/admin/payments/{pid}/confirm")
def payment_confirm(request: Request, pid: int) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    # замок записи с начала, как у settle: callback по той же ноте, закоммиченный между нашим
    # чтением и записью, сделал бы отложенную транзакцию «database is locked» — админу 500
    with payments.outbox() as box, db.connect(immediate=True) as con:     # письмо — после commit
        p = web.payment(con, pid)
        if p is None:
            return Response(status_code=404)
        back = _back(request, p)
        try:
            payments.confirm(con, p, who)
        except ValueError:
            return RedirectResponse(f"{back}?msg=payment_not_pending", status_code=303)
        except RuntimeError:
            return RedirectResponse(f"{back}?msg=no_key", status_code=303)
        box.add(payments.notify_paid(con, p, who))
    code = "payment_confirmed" if box.code else "payment_confirmed_mailed"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@router.post("/admin/payments/{pid}/repeat")
def payment_repeat(request: Request, pid: int, sure: str = Form("")) -> Response:
    """«Зачесть повторный перевод» (02.10): по уже оплаченной или отклонённой ноте
    пришёл ещё один перевод — следующий период отдельной строкой с новым reference,
    файл и письмо как у «Подтвердить» (payments.credit_again). Галочка «перевод
    пришёл» обязательна: кнопка продлевает и выдаёт файл, случайный клик — подарок.
    Ожидающую ноту закрывает «Подтвердить», не эта кнопка."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    # замок записи с начала, как у settle: callback по той же ноте, закоммиченный между нашим
    # чтением и записью, сделал бы отложенную транзакцию «database is locked» — админу 500
    with payments.outbox() as box, db.connect(immediate=True) as con:     # письмо — после commit
        p = web.payment(con, pid)
        if p is None:
            return Response(status_code=404)
        back = _back(request, p)
        if sure != "1":
            return RedirectResponse(f"{back}?msg=repeat_unsure", status_code=303)
        try:
            new = payments.credit_again(con, p, payments.TRANSFER, who)
        except ValueError as e:
            code = {"pending": "payment_is_pending", "idno": "bad_idno"}.get(str(e), "payment_not_pending")
            return RedirectResponse(f"{back}?msg={code}", status_code=303)
        except RuntimeError:
            return RedirectResponse(f"{back}?msg=no_key", status_code=303)
        box.add(payments.notify_paid(con, new, who))
    code = "payment_repeat" if box.code else "payment_repeat_mailed"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@router.post("/admin/payments/{pid}/mail")
def payment_mail(request: Request, pid: int) -> Response:
    """Письмо с ожидающей нотой ещё раз (03.10): та же нота, тот же reference —
    когда бухгалтер клиники потерял первое или нота выставлена без письма."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    code = ""
    with payments.outbox() as box, db.connect(immediate=True) as con:
        p = con.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        if p is None:
            return Response(status_code=404)
        c = web.clinic(con, p["clinic_id"])
        if p["status"] != payments.PENDING:
            code = "payment_not_pending"
        else:
            box.add([(True, web.payment_letter(con, c, p, who))])
    code = code or box.code or "payment_mailed"
    return RedirectResponse(f"/admin/clinics/{p['clinic_id']}?msg={code}", status_code=303)


@router.post("/admin/payments/{pid}/reject")
def payment_reject(request: Request, pid: int, reason: str = Form("")) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        p = web.payment(con, pid)
        if p is None:
            return Response(status_code=404)
        back = _back(request, p)
        try:
            payments.reject(con, p, reason.strip()[:200], auth.current_user(request))
        except ValueError:
            return RedirectResponse(f"{back}?msg=payment_not_pending", status_code=303)
    return RedirectResponse(f"{back}?msg=payment_rejected", status_code=303)
