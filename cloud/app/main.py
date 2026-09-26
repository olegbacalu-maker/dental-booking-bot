"""DentPilot Cloud — сервер лицензий (docs/dentpilot-2/cloud.md, шаг 1).

Отдельная программа: ни одного импорта из bot/. Общее с движком — контракт
файла лицензии и фикстуры tests/fixtures/license/. Здесь: вход администратора,
клиники, выдача файла, письмо с файлом (L7), платежи переводом (L8),
ежедневная задача с напоминаниями и журнал (L9), оплата картой через maib —
ссылка, callback, проверка статуса (L12), ответ программе клиники на её
суточный запрос нового файла (L13, /v1/license), публичная форма пробного
периода /proba и заявки с неё в админке (L14).
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import auth, config, db, jobs, license, maib, mail, payments, trial, views

APP_VERSION = "0.1.0"
log = logging.getLogger("cloud")
app = FastAPI(title="DentPilot Cloud", docs_url=None, redoc_url=None)

_IDNO = re.compile(r"^[0-9]{13}$")


@app.on_event("startup")
def startup() -> None:
    db.init()
    if not config.ADMIN_HASH:
        log.warning("DP_ADMIN_HASH пуст: вход невозможен — python -m app.tools hash-password")
    try:
        k = license.key()
        if k is None:
            log.warning("DP_LICENSE_KEY пуст: файлы выдавать нечем")
        else:
            log.info("ключ выдачи kid=%s, %d бит", k.kid, k.n.bit_length())
    except (OSError, ValueError) as e:
        log.error("ключ выдачи не прочитан: %r", e)
    if not config.SMTP_HOST and not config.MAIL_OUTBOX:
        log.warning("ни DP_SMTP_HOST, ни DP_MAIL_OUTBOX: письма отправлять некуда")


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "version": APP_VERSION})


# ---------- автообновление файла (L13): программа клиники спрашивает сама ----------


def _bearer(request: Request) -> str:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h[:7].lower() == "bearer " else ""


@app.get(license.RENEW_PATH)
def license_renew(request: Request, seq: int = 0) -> Response:
    """`renew.url` из файла: последний выданный файл клинике, если он новее `seq`.

    Без куки и админки — клинику называет токен из того же файла. 401 — токен
    не признан; 204 — новее нет; 200 — файл, тот же текст, что скачивается и
    уходит письмом. Каждый запрос оставляет след в карточке (когда, какой seq у
    программы); выдача файла программе — строка в журнале."""
    token = _bearer(request)
    if not token:
        return JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    with db.connect() as con:
        c = con.execute("SELECT * FROM clinics WHERE renew_token=? AND renew_token<>''",
                        (token,)).fetchone()
        if c is None:
            return JSONResponse({"ok": False, "code": "token_unknown"}, status_code=401)
        row = con.execute("SELECT * FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1",
                          (c["id"],)).fetchone()
        con.execute("UPDATE clinics SET renew_at=?, renew_seq=? WHERE id=?",
                    (db.now_iso(), max(0, seq), c["id"]))
        if row is None or row["seq"] <= seq:
            return Response(status_code=204)
        db.audit(con, "program", "renew", c["id"], f"файл {row['seq']} забран программой (у неё был {seq})")
    return Response(license.issue_text(row), media_type="application/json")


# ---------- вход ----------


def _guard(request: Request) -> RedirectResponse | None:
    if auth.current_user(request) is None:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.get("/", response_class=HTMLResponse)
def root() -> Response:
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
def login_page(msg: str = "") -> Response:
    return HTMLResponse(views.login_page(msg))


@app.post("/admin/login")
def login(request: Request, user: str = Form(""), password: str = Form("")) -> Response:
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = _ip(request)
    if auth.locked(ip):
        return RedirectResponse("/admin/login?msg=login_locked", status_code=303)
    ok = (config.ADMIN_HASH and secrets.compare_digest(user.strip(), config.ADMIN_USER)
          and auth.check_password(password, config.ADMIN_HASH))
    with db.connect() as con:
        db.audit(con, user.strip()[:40] or "?", "login_ok" if ok else "login_fail", None, ip)
    if not ok:
        auth.note_fail(ip)
        return RedirectResponse("/admin/login?msg=login_bad", status_code=303)
    auth.note_ok(ip)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.session_cookie(config.ADMIN_USER), max_age=auth.SESSION_TTL,
                    httponly=True, samesite="lax", secure=config.SECURE_COOKIES, path="/")
    return resp


@app.post("/admin/logout")
def logout(request: Request) -> Response:
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# ---------- клиники ----------


_CLINICS_SQL = """SELECT c.*, s.plan, s.valid_until, s.grace_days,
                         (SELECT MAX(seq) FROM issues i WHERE i.clinic_id = c.id) AS seq
                  FROM clinics c LEFT JOIN subscriptions s ON s.clinic_id = c.id
                  ORDER BY c.created_at DESC"""


_REQUESTS_SQL = """SELECT c.* FROM clinics c WHERE c.origin = 'form' AND c.declined_at IS NULL
                   AND NOT EXISTS (SELECT 1 FROM issues i WHERE i.clinic_id = c.id)
                   ORDER BY c.requested_at DESC"""


@app.get("/admin", response_class=HTMLResponse)
def clinics(request: Request, msg: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_CLINICS_SQL).fetchall()
        requests = con.execute(_REQUESTS_SQL).fetchall()
    return HTMLResponse(views.clinics_page(rows, auth.current_user(request), msg, requests=requests))


# ---------- форма пробного периода (L14): публичная, без куки ----------


@app.get("/proba", response_class=HTMLResponse)
def trial_form() -> Response:
    return HTMLResponse(views.trial_page())


@app.post("/proba", response_class=HTMLResponse)
def trial_submit(request: Request, name: str = Form(""), idno: str = Form(""), contact_name: str = Form(""),
                 email: str = Form(""), phone: str = Form(""), consent: str = Form(""),
                 website: str = Form("")) -> Response:
    """Заявка: лимит с адреса, скрытое поле, чистые поля, одна клиника на IDNO/e-mail
    (trial.submit), письмо Олегу; в approve — клинике «принято», в auto — файл."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = _ip(request)
    if trial.limited(ip):
        return HTMLResponse(views.trial_page("limited"), status_code=429)
    fields = {"name": name, "idno": idno, "contact_name": contact_name, "email": email, "phone": phone,
              "consent": consent}
    f, code = trial.clean(fields)
    if code:
        return HTMLResponse(views.trial_page(code, f), status_code=400)
    trial.note(ip)
    if website.strip():
        # бот заполнил поле, которого человек не видит: ему «принято», нам — строка в лог
        log.warning("форма пробного: скрытое поле заполнено, %s, %s", ip, f["email"])
        return HTMLResponse(views.trial_done_page(trial.REQUESTED, f["email"]))
    with db.connect(immediate=True) as con:
        outcome, clinic = trial.submit(con, f, ip)
    trial.notify(clinic, outcome, ip, f)
    if outcome == trial.REQUESTED:
        trial.acknowledge(clinic)
    return HTMLResponse(views.trial_done_page(outcome, f["email"]))


@app.post("/admin/clinics/{cid}/decline")
def trial_decline(request: Request, cid: str) -> Response:
    """Скрыть заявку с формы: пробный не выдан, клиника остаётся (и её IDNO/e-mail —
    в правиле «второго пробного нет»)."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        if _clinic(con, cid) is None:
            return Response(status_code=404)
        con.execute("UPDATE clinics SET declined_at=? WHERE id=?", (db.now_iso(), cid))
        db.audit(con, auth.current_user(request), "trial_declined", cid, "")
    return RedirectResponse("/admin?msg=trial_declined", status_code=303)


def _clean(name: str, idno: str) -> str:
    if not name.strip() or len(name.strip()) > 120:
        return "bad_name"
    if idno.strip() and not _IDNO.match(idno.strip()):
        return "bad_idno"
    return ""


@app.post("/admin/clinics")
def clinic_new(request: Request, name: str = Form(""), idno: str = Form(""),
               contact_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
               address: str = Form("")) -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if (code := _clean(name, idno)):
        return RedirectResponse(f"/admin?msg={code}", status_code=303)
    cid = "c_" + secrets.token_hex(6)
    with db.connect() as con:
        con.execute("INSERT INTO clinics(id, name, idno, contact_name, email, phone, address, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (cid, name.strip(), idno.strip(), contact_name.strip(), email.strip(),
                     phone.strip(), address.strip(), db.now_iso()))
        db.audit(con, auth.current_user(request), "clinic_new", cid, name.strip())
    return RedirectResponse(f"/admin/clinics/{cid}?msg=clinic_ok", status_code=303)


def _clinic(con, cid: str):
    return con.execute("SELECT * FROM clinics WHERE id=?", (cid,)).fetchone()


@app.get("/admin/clinics/{cid}", response_class=HTMLResponse)
def clinic_card(request: Request, cid: str, msg: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        c = _clinic(con, cid)
        if c is None:
            return Response("нет такой клиники", status_code=404)
        sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (cid,)).fetchone()
        issues = con.execute("SELECT * FROM issues WHERE clinic_id=? ORDER BY seq DESC", (cid,)).fetchall()
        audit = con.execute("SELECT * FROM audit WHERE clinic_id=? ORDER BY id DESC LIMIT 50", (cid,)).fetchall()
        pays = con.execute("SELECT * FROM payments WHERE clinic_id=? ORDER BY id DESC", (cid,)).fetchall()
        rems = con.execute("SELECT * FROM reminders WHERE subscription_id=? ORDER BY sent_at DESC, rowid DESC",
                           (cid,)).fetchall()
        pending = _pending_count(con)
    return HTMLResponse(views.clinic_page(c, sub, issues, audit, auth.current_user(request), msg,
                                          payments=pays, pending=pending, reminders=rems))


def _pending_count(con) -> int:
    return con.execute("SELECT count(*) FROM payments WHERE status='pending'").fetchone()[0]


# ---------- ежедневная задача и журнал (L9) ----------


@app.post("/admin/jobs/daily")
def daily_job(request: Request) -> Response:
    """То же, что cron: напоминания по таблице за сегодня. Повторный запуск в тот же
    день ничего не шлёт — ключ (подписка, kind, period) в reminders."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    rep = jobs.daily(who=auth.current_user(request))
    return RedirectResponse("/admin?msg=" + ("daily_failed" if rep.failed else "daily_done"), status_code=303)


_AUDIT_SQL = """SELECT a.*, c.name AS clinic FROM audit a LEFT JOIN clinics c ON c.id = a.clinic_id
                ORDER BY a.id DESC LIMIT 200"""


@app.get("/admin/audit", response_class=HTMLResponse)
def audit_log(request: Request, msg: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_AUDIT_SQL).fetchall()
        pending = _pending_count(con)
    return HTMLResponse(views.audit_page(rows, auth.current_user(request), msg, pending))


# ---------- платежи (L8) ----------


_PENDING_SQL = """SELECT p.*, c.name AS clinic FROM payments p JOIN clinics c ON c.id = p.clinic_id
                  WHERE p.status = 'pending' ORDER BY p.id"""


@app.get("/admin/payments", response_class=HTMLResponse)
def payments_pending(request: Request, msg: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_PENDING_SQL).fetchall()
    return HTMLResponse(views.payments_page(rows, auth.current_user(request), msg))


@app.post("/admin/clinics/{cid}/payments")
def payment_new(request: Request, cid: str, months: str = Form("1"), amount: str = Form(""),
                send: str = Form(""), method: str = Form(payments.TRANSFER)) -> Response:
    """Платёж: переводом (reference в письме) или картой (L12: плюс ссылка maib).
    maib не ответил — строка откатывается вместе с транзакцией, reference не
    потрачен, админ видит maib_failed."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    card = method == payments.CARD
    if card and not maib.enabled():
        return RedirectResponse(f"/admin/clinics/{cid}?msg=no_maib", status_code=303)
    try:
        with db.connect() as con:
            c = _clinic(con, cid)
            if c is None:
                return Response(status_code=404)
            sub = con.execute("SELECT price FROM subscriptions WHERE clinic_id=?", (cid,)).fetchone()
            price = sub["price"] if sub else 399
            try:
                m = int(months)
                a = int(amount) if amount.strip() else m * price
            except ValueError:
                return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_amount", status_code=303)
            try:
                p = payments.create(con, c, m, a, who)
            except ValueError as e:
                return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_{e}", status_code=303)
            code = "payment_created"
            if card:
                p = payments.attach_card(con, p, c, who, _ip(request))
                code = "card_created"
            if send == "1":
                code = _send_payment_letter(con, c, p, who) or code + "_mailed"
    except maib.MaibError as e:
        log.error("maib: платёж клинике %s не создан: %s", cid, e)
        return RedirectResponse(f"/admin/clinics/{cid}?msg=maib_failed", status_code=303)
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)


def _send_payment_letter(con, c, p, who: str) -> str:
    if not c["email"]:
        return "bad_email"
    try:
        subject, body = mail.payment_letter(c["name"], p["reference"], p["amount"], p["months"],
                                            pay_url=p["pay_url"])
    except RuntimeError:
        return "no_bank"
    try:
        where = mail.send(c["email"], subject, body)
    except (RuntimeError, OSError) as e:
        log.error("письмо с нотой %s не отправлено: %r", p["reference"], e)
        return "mail_failed"
    db.audit(con, who, "mail", c["id"], f"нота {p['reference']} на {c['email']} ({where})")
    return ""


# ---------- карта: maib (L12) ----------


def _settle_now(con, p, who: str) -> str:
    """Спросить maib и применить: код для ?msg=. Истина — pay-info, не callback и не кнопка."""
    truth = maib.info(p["provider_id"])
    outcome = payments.settle(con, p, truth, who)
    if outcome == payments.SETTLED_PAID:
        license.mail_latest(con, _clinic(con, p["clinic_id"]), who)
        return "card_paid"
    return {payments.SETTLED_ALREADY: "payment_not_pending", payments.SETTLED_WAITING: "card_waiting"
            }.get(outcome, "card_failed")


@app.post("/admin/payments/{pid}/check")
def payment_check(request: Request, pid: int) -> Response:
    """Кнопка «Проверить»: тот же вопрос maib, что задают callback и ежедневная задача."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        p = _payment(con, pid)
        if p is None:
            return Response(status_code=404)
        back = _back(request, p)
        if not p["provider_id"]:
            return RedirectResponse(f"{back}?msg=card_none", status_code=303)
        try:
            code = _settle_now(con, p, auth.current_user(request))
        except maib.MaibError as e:
            log.error("maib: статус %s не получен: %s", p["reference"], e)
            code = "maib_failed"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@app.post("/admin/payments/{pid}/link")
def payment_link(request: Request, pid: int) -> Response:
    """Ссылка на карту к ожидающему платежу: первая (платёж заведён переводом) или
    новая взамен не прошедшей. Тот же reference; письмо — если есть e-mail."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if not maib.enabled():
        return RedirectResponse("/admin/payments?msg=no_maib", status_code=303)
    who = auth.current_user(request)
    try:
        with db.connect() as con:
            p = _payment(con, pid)
            if p is None:
                return Response(status_code=404)
            back = _back(request, p)
            c = _clinic(con, p["clinic_id"])
            try:
                p = payments.attach_card(con, p, c, who, _ip(request))
            except ValueError:
                return RedirectResponse(f"{back}?msg=payment_not_pending", status_code=303)
            code = "card_link"
            if c["email"]:
                code = _send_payment_letter(con, c, p, who) or "card_link_mailed"
    except maib.MaibError as e:
        log.error("maib: ссылка для платежа %s не создана: %s", pid, e)
        return RedirectResponse(f"/admin/payments?msg=maib_failed", status_code=303)
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


def _maib_callback(raw: bytes) -> Response:
    """Сигнал от maib после оплаты. Подпись — фильтр от чужих; истина — pay-info
    (инвариант 2); второй callback того же платежа ничего не делает (3).
    Ответы: 400 битый или подпись не сошлась, 404 платёж не наш, 503 maib не
    ответил про статус (пусть повторит), 200 — принято, с исходом."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"ok": False, "code": "bad_json"}, status_code=400)
    result = maib.signed(payload)
    if result is None:
        log.warning("maib callback: подпись не сошлась или тело не по форме")
        return JSONResponse({"ok": False, "code": "bad_signature"}, status_code=400)
    pay_id = result.get("payId")
    with db.connect() as con:
        p = (con.execute("SELECT * FROM payments WHERE provider_id=?", (pay_id,)).fetchone()
             if isinstance(pay_id, str) and pay_id else None)
    if p is None:
        log.warning("maib callback: платёж %r не наш", pay_id)
        return JSONResponse({"ok": False, "code": "unknown_payment"}, status_code=404)
    try:
        truth = maib.info(pay_id)
    except maib.MaibError as e:
        log.error("maib callback: статус %s не получен: %s", p["reference"], e)
        return JSONResponse({"ok": False, "code": "maib_unavailable"}, status_code=503)
    with db.connect() as con:
        p = _payment(con, p["id"])
        outcome = payments.settle(con, p, truth, "maib")
        if outcome == payments.SETTLED_PAID:
            license.mail_latest(con, _clinic(con, p["clinic_id"]), "maib")
    log.info("maib callback: %s → %s", p["reference"], outcome)
    return JSONResponse({"ok": True, "outcome": outcome})


@app.post(maib.CALLBACK_PATH)
async def maib_callback(request: Request) -> Response:
    return await run_in_threadpool(_maib_callback, await request.body())


@app.get(maib.OK_PATH, response_class=HTMLResponse)
def pay_ok() -> Response:
    """Куда maib возвращает браузер после оплаты. Редирект — не истина: страница
    не говорит «оплачено», а что подтверждение и файл придут письмом."""
    return HTMLResponse(views.pay_page(True))


@app.get(maib.FAIL_PATH, response_class=HTMLResponse)
def pay_fail() -> Response:
    return HTMLResponse(views.pay_page(False))


def _payment(con, pid: int):
    return con.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()


def _back(request: Request, p) -> str:
    """Откуда пришли: со страницы ожидающих — туда же, иначе в карточку."""
    ref = request.headers.get("referer", "")
    return "/admin/payments" if ref.endswith("/admin/payments") else f"/admin/clinics/{p['clinic_id']}"


@app.post("/admin/payments/{pid}/confirm")
def payment_confirm(request: Request, pid: int) -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    with db.connect() as con:
        p = _payment(con, pid)
        if p is None:
            return Response(status_code=404)
        back = _back(request, p)
        try:
            payments.confirm(con, p, who)
        except ValueError:
            return RedirectResponse(f"{back}?msg=payment_not_pending", status_code=303)
        except RuntimeError:
            return RedirectResponse(f"{back}?msg=no_key", status_code=303)
        c = _clinic(con, p["clinic_id"])
        code = "payment_confirmed" if _send_latest(con, c, who) else "payment_confirmed_mailed"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@app.post("/admin/payments/{pid}/reject")
def payment_reject(request: Request, pid: int, reason: str = Form("")) -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        p = _payment(con, pid)
        if p is None:
            return Response(status_code=404)
        back = _back(request, p)
        try:
            payments.reject(con, p, reason.strip()[:200], auth.current_user(request))
        except ValueError:
            return RedirectResponse(f"{back}?msg=payment_not_pending", status_code=303)
    return RedirectResponse(f"{back}?msg=payment_rejected", status_code=303)


@app.post("/admin/clinics/{cid}/edit")
def clinic_edit(request: Request, cid: str, name: str = Form(""), idno: str = Form(""),
                contact_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
                address: str = Form("")) -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if (code := _clean(name, idno)):
        return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)
    with db.connect() as con:
        if _clinic(con, cid) is None:
            return Response(status_code=404)
        con.execute("UPDATE clinics SET name=?, idno=?, contact_name=?, email=?, phone=?, address=? WHERE id=?",
                    (name.strip(), idno.strip(), contact_name.strip(), email.strip(), phone.strip(),
                     address.strip(), cid))
        db.audit(con, auth.current_user(request), "clinic_edit", cid, name.strip())
    return RedirectResponse(f"/admin/clinics/{cid}?msg=saved", status_code=303)


# ---------- выдача файла ----------


def _send_latest(con, c, who: str) -> str:
    """Последний выданный файл письмом; код для ?msg=. Одна функция на админку,
    callback maib и ежедневную задачу — license.mail_latest."""
    return license.mail_latest(con, c, who)


@app.post("/admin/clinics/{cid}/issue")
def clinic_issue(request: Request, cid: str, kind: str = Form("trial"), valid_until: str = Form(""),
                 grace_days: str = Form(str(license.GRACE_DAYS)), reason: str = Form(""),
                 send: str = Form("")) -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    with db.connect() as con:
        c = _clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        if kind == "trial":
            plan, (valid, grace) = "trial", license.trial_dates()
        else:
            plan = "standard"
            try:
                valid = datetime.strptime(valid_until.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days = max(0, min(60, int(grace_days or license.GRACE_DAYS)))
            except ValueError:
                return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_date", status_code=303)
            if valid <= datetime.now(timezone.utc):
                return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_date", status_code=303)
            grace = valid + timedelta(days=days)
        try:
            license.issue(con, c, plan, valid, grace, reason.strip() or kind, who)
        except ValueError as e:
            return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_{e}", status_code=303)
        except RuntimeError:
            return RedirectResponse(f"/admin/clinics/{cid}?msg=no_key", status_code=303)
        code = "issued"
        if send == "1":
            code = _send_latest(con, c, who) or "issued_mailed"
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)


@app.get("/admin/clinics/{cid}/issues/{seq}/license.json")
def issue_file(request: Request, cid: str, seq: int) -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        row = con.execute("SELECT * FROM issues WHERE clinic_id=? AND seq=?", (cid, seq)).fetchone()
    if row is None:
        return Response(status_code=404)
    return Response(license.issue_text(row), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="license.json"'})


@app.post("/admin/clinics/{cid}/email")
def clinic_email(request: Request, cid: str) -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        c = _clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        code = _send_latest(con, c, auth.current_user(request)) or "mailed"
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)
