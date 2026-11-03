"""Оплата клиники (03.11, из main.py): страница /plata/<ключ> (вне /admin и без входа —
cloud.md › «Plătește acum»), callback maib Checkout и возврат браузера /pay/ok|fail."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import account, auth, db, maib, payments, paylink, tiers, trial, views, web
from . import terms as terms_mod  # `terms` здесь — поле формы (галочка условий)

log = logging.getLogger("cloud")
router = APIRouter()


@router.get(paylink.PATH + "/{pid}", response_class=HTMLResponse)
def pay_link_page(pid: str, msg: str = "") -> Response:
    with db.connect() as con:
        c = paylink.lookup(con, pid)
        if c is None:
            return HTMLResponse(views.pay_link_expired_page(), status_code=410)
        sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (c["id"],)).fetchone()
        # долг клиники за абонемент: своя нота или общая нота кабинета, где она строкой (26.10)
        pending = payments.debt_of(con, c["id"])
        lines = payments.lines_of(con, pending["id"]) if pending is not None and pending["kind"] == payments.CABINET else []
        extra = [x for x in (payments.open_of(con, c["id"], payments.SMS),
                             payments.open_of(con, c["id"], payments.SMS_NAME)) if x is not None]
    return HTMLResponse(views.pay_link_page(c, sub, pending, pid, msg, card_on=maib.enabled(), sms_notes=extra,
                                            lines=lines))


@router.post(paylink.PATH + "/{pid}", response_class=HTMLResponse)
def pay_link_submit(request: Request, pid: str, months: str = Form("1"), method: str = Form(payments.TRANSFER),
                    idno: str = Form(""), tier: str = Form(""), terms: str = Form(""),
                    ref: str = Form("")) -> Response:
    """Со страницы оплаты: нота на выбранные вариант и срок (та же, что из админки и
    кабинета, одна ожидающая на клинику; другой вариант или срок — нота ЗАМЕНЯЕТСЯ,
    payments.choose) — картой сразу на страницу maib, переводом — нота с реквизитами
    здесь и письмом. ⛔ Без галочки условий (`terms`) — ни карты, ни ноты: требование
    maib, «Am citit și accept Termenii» перед оплатой. IDNO без него абонемента не
    бывает — заполняется тут же. Вариант не назван (старая страница) — текущий.
    `ref` — ожидающая нота SMS (пакет, имя) этой клиники: её карта, тем же путём.
    Карта — `web.card_go`: ссылка maib рождается по клику (живёт минуты, maib.PAY_TTL).
    Три шага: нота и снимок для maib — транзакцией; письмо с нотой и maib — после её commit,
    вне замка записи; ответ maib — своей короткой (`web.card_go`)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = web.ip(request)
    back = f"{paylink.PATH}/{pid}"
    if paylink.limited(ip):
        return RedirectResponse(f"{back}?msg=limited", status_code=303)
    m = web.months(months)
    idno = "".join(idno.split())
    card = method == payments.CARD and maib.enabled()
    plan = None
    with payments.outbox() as box, db.connect(immediate=True) as con:
        c = paylink.lookup(con, pid)
        if c is None:
            return HTMLResponse(views.pay_link_expired_page(), status_code=410)
        if m not in payments.MONTHS:
            return RedirectResponse(f"{back}?msg=bad_months", status_code=303)
        if terms != "1":
            return RedirectResponse(f"{back}?msg=need_terms", status_code=303)
        # акт акцепта (29.10, terms.py): галочка страницы оплаты — строка с версией CURRENT; кто —
        # контакт клиники (страница имени не спрашивает); `payments.terms_at` остаётся как был
        terms_mod.record(con, c["id"], terms_mod.CURRENT, c["contact_name"] or "", terms_mod.SRC_PAY, ip)
        if ref:
            note = con.execute("SELECT * FROM payments WHERE reference=? AND clinic_id=? AND status=? AND kind IN (?,?)",
                               (ref, c["id"], payments.PENDING, payments.SMS, payments.SMS_NAME)).fetchone()
            group = payments.group_of(con, c["id"])
            if note is None and group is not None and group["reference"] == ref:
                note = group                       # общая нота кабинета, где эта клиника (26.10)
            if note is None:
                return RedirectResponse(f"{back}?msg=note_gone", status_code=303)
            if not card:
                return RedirectResponse(f"{back}?msg=no_card", status_code=303)
            plan = payments.card_plan(con, note, c, ip)
        else:
            if idno and idno != (c["idno"] or ""):
                # ссылку оплаты открывает любой, у кого она есть: IDNO здесь только ЗАПОЛНЯЕТСЯ;
                # записанный меняет кабинет клиники (cont_edit) — за входом
                if c["idno"]:
                    return RedirectResponse(f"{back}?msg=idno_locked", status_code=303)
                if not trial.IDNO_RE.match(idno):
                    return RedirectResponse(f"{back}?msg=bad_idno", status_code=303)
                if account.idno_taken(con, idno, c["id"]):
                    return RedirectResponse(f"{back}?msg=idno_taken", status_code=303)
                con.execute("UPDATE clinics SET idno=? WHERE id=?", (idno, c["id"]))
                db.audit(con, "program", "clinic_edit", c["id"], f"IDNO {idno} (pagina de plată)")
                c = web.clinic(con, c["id"])
            if len(c["idno"] or "") != 13:
                return RedirectResponse(f"{back}?msg=pay_need_idno", status_code=303)
            sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (c["id"],)).fetchone()
            try:
                p, outcome = payments.choose(con, c, tier or tiers.pick(sub), m, "program")
            except ValueError as e:
                return RedirectResponse(f"{back}?msg={'in_group' if str(e) == payments.HELD else 'tier_not_sold'}",
                                        status_code=303)
            if outcome != payments.EXISTS:
                # новая нота — письмом и при карте: не дойдёт клиника до оплаты — реквизиты у неё есть
                box.add([(True, web.payment_letter(con, c, p, "program"))])
            if card:
                plan = payments.card_plan(con, p, c, ip)
    if plan is not None:
        return web.card_go(plan, "program", back)
    code = {payments.CREATED: "note_created", payments.REPLACED: "note_replaced"}.get(outcome, "note_exists")
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


def _maib_callback(raw: bytes, signature: str, timestamp: str) -> Response:
    """Сигнал от maib после оплаты. Подпись (заголовки X-Signature и
    X-Signature-Timestamp над СЫРЫМ телом) — фильтр от чужих; истина — статус
    checkout у maib (инвариант 2); второй callback того же платежа ничего не делает (3).
    Ответы: 400 подпись не сошлась или тело не по форме, 404 платёж не наш, 503 maib
    не ответил про статус (пусть повторит), 200 — принято, с исходом."""
    if not maib.verify(raw, signature, timestamp):
        log.warning("maib callback: подпись не сошлась или метка не свежая")
        return JSONResponse({"ok": False, "code": "bad_signature"}, status_code=400)
    try:
        result = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"ok": False, "code": "bad_json"}, status_code=400)
    if not isinstance(result, dict):
        return JSONResponse({"ok": False, "code": "bad_json"}, status_code=400)
    pay_id = result.get("checkoutId")
    with db.connect() as con:
        p = payments.by_pay_id(con, pay_id) if isinstance(pay_id, str) and pay_id else None
    if p is None:
        log.warning("maib callback: платёж %r не наш", pay_id)
        return JSONResponse({"ok": False, "code": "unknown_payment"}, status_code=404)
    try:
        truth = maib.info(pay_id)
    except maib.MaibError as e:
        log.error("maib callback: статус %s не получен: %s", p["reference"], e)
        return JSONResponse({"ok": False, "code": "maib_unavailable"}, status_code=503)
    # замок записи с начала: возврат браузера (/pay/ok) приходит почти тем же мигом, и
    # отложенная транзакция, прочитавшая до его коммита, при записи сразу «database is locked»
    with payments.outbox() as box, db.connect(immediate=True) as con:     # письмо — после commit
        p = web.payment(con, p["id"])
        outcome = payments.settle(con, p, truth, "maib")
        if outcome == payments.SETTLED_PAID:
            box.add(payments.notify_paid(con, p, "maib"))
    log.info("maib callback: %s → %s", p["reference"], outcome)
    return JSONResponse({"ok": True, "outcome": outcome})


@router.post(maib.CALLBACK_PATH)
async def maib_callback(request: Request) -> Response:
    return await run_in_threadpool(_maib_callback, await request.body(),
                                   request.headers.get("x-signature", ""),
                                   request.headers.get("x-signature-timestamp", ""))


def _returned(pay_id: str):
    """Платёж, о котором браузер вернулся от maib, — по checkoutId (неугадываемый id maib,
    любая попытка ноты). ⛔ По orderId (= наш reference) не искать: он порядковый
    (DP-2026-000123), и страница по нему показывала бы чужие ноты; а после зачёта
    повторного платежа он и не совпадает с reference строки. Нота ещё ждёт, а maib
    настроен — сразу спросить maib о ЭТОЙ попытке и применить ответ (settle: та же
    истина, что у callback), чтобы страница могла сказать «plătită» по факту."""
    if not pay_id or len(pay_id) > 64:
        return None
    with db.connect() as con:
        p = payments.by_pay_id(con, pay_id)
    if p is None or p["status"] != payments.PENDING or not maib.enabled():
        return p
    try:
        truth = maib.info(pay_id)
    except maib.MaibError as e:
        log.warning("maib о возврате %s не ответил: %s", p["reference"], e)
        return p
    # callback того же платежа — в тот же миг; письмо — после commit
    with payments.outbox() as box, db.connect(immediate=True) as con:
        fresh = web.payment(con, p["id"])
        if payments.settle(con, fresh, truth, "maib") == payments.SETTLED_PAID:
            box.add(payments.notify_paid(con, fresh, "maib"))
        return payments.by_pay_id(con, pay_id)


@router.get(maib.OK_PATH, response_class=HTMLResponse)
def pay_ok(checkoutId: str = "", checkoutStatus: str = "", orderId: str = "") -> Response:  # noqa: N803 — имена maib
    """Куда maib возвращает браузер после оплаты (Checkout дописывает checkoutId,
    checkoutStatus — Completed или Failed — и orderId). Редирект — не истина, и
    checkoutStatus тоже: «plătită» страница говорит только о ноте, которую сервер уже
    закрыл по ответу maib (settle); иначе — «în curs de confirmare». № заказа, что
    оплачивается, сумма и дата — требование maib."""
    return HTMLResponse(views.pay_page(True, _returned(checkoutId)))


@router.get(maib.FAIL_PATH, response_class=HTMLResponse)
def pay_fail(checkoutId: str = "", checkoutStatus: str = "", orderId: str = "") -> Response:  # noqa: N803
    return HTMLResponse(views.pay_page(False, _returned(checkoutId)))
