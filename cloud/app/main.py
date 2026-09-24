"""DentPilot Cloud — сервер лицензий (docs/dentpilot-2/cloud.md, шаг 1).

Отдельная программа: ни одного импорта из bot/. Общее с движком — контракт
файла лицензии и фикстуры tests/fixtures/license/. Здесь: вход администратора,
клиники, выдача файла, письмо с файлом (L7). Платежи — L8, напоминания — L9.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import auth, config, db, license, mail, payments, views

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


@app.get("/admin", response_class=HTMLResponse)
def clinics(request: Request, msg: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_CLINICS_SQL).fetchall()
    return HTMLResponse(views.clinics_page(rows, auth.current_user(request), msg))


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
        pending = _pending_count(con)
    return HTMLResponse(views.clinic_page(c, sub, issues, audit, auth.current_user(request), msg,
                                          payments=pays, pending=pending))


def _pending_count(con) -> int:
    return con.execute("SELECT count(*) FROM payments WHERE status='pending'").fetchone()[0]


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
        if send == "1":
            code = _send_payment_letter(con, c, p, who) or "payment_created_mailed"
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)


def _send_payment_letter(con, c, p, who: str) -> str:
    if not c["email"]:
        return "bad_email"
    try:
        subject, body = mail.payment_letter(c["name"], p["reference"], p["amount"], p["months"])
    except RuntimeError:
        return "no_bank"
    try:
        where = mail.send(c["email"], subject, body)
    except (RuntimeError, OSError) as e:
        log.error("письмо с реквизитами %s не отправлено: %r", p["reference"], e)
        return "mail_failed"
    db.audit(con, who, "mail", c["id"], f"реквизиты {p['reference']} на {c['email']} ({where})")
    return ""


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
    """Последний выданный файл письмом; код для ?msg=."""
    row = con.execute("SELECT * FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1",
                      (c["id"],)).fetchone()
    if row is None:
        return "no_issue"
    if not c["email"]:
        return "bad_email"
    plan = con.execute("SELECT plan FROM subscriptions WHERE clinic_id=?", (c["id"],)).fetchone()
    subject, body = mail.license_letter(c["name"], row["valid_until"], plan["plan"] if plan else "standard")
    try:
        where = mail.send(c["email"], subject, body,
                          ("license.json", license.issue_text(row).encode("utf-8")))
    except (RuntimeError, OSError) as e:
        log.error("письмо клинике %s не отправлено: %r", c["id"], e)
        return "mail_failed"
    db.audit(con, who, "mail", c["id"], f"seq {row['seq']} на {c['email']} ({where})")
    return ""


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
