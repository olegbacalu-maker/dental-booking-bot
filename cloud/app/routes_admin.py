"""Админка Олега `/admin*` (03.11, из main.py), кроме платежей: вход, клиники и карточка,
выдача файла, флот, SMS, документы клиники, журнал, ежедневная задача кнопкой."""
from __future__ import annotations

import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import (account, archive, auth, cabinet, config, contracts, db, fleet, jobs, license, payments, revoke, sms, sms_paper,
               sms_rule, smsmd, smsreport, terms, trial, views, web)

log = logging.getLogger("cloud")
router = APIRouter()


_IDNO = re.compile(r"^[0-9]{13}$")


# ---------- вход ----------


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(msg: str = "") -> Response:
    return HTMLResponse(views.login_page(msg))


@router.post("/admin/login")
def login(request: Request, user: str = Form(""), password: str = Form("")) -> Response:
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = web.ip(request)
    if auth.locked(ip):
        return RedirectResponse("/admin/login?msg=login_locked", status_code=303)
    ok = (config.ADMIN_HASH and secrets.compare_digest(user.strip(), config.ADMIN_USER)
          and auth.check_password(password, config.ADMIN_HASH))
    with db.connect(immediate=True) as con:
        db.audit(con, user.strip()[:40] or "?", "login_ok" if ok else "login_fail", None, ip)
    if not ok:
        auth.note_fail(ip)
        return RedirectResponse("/admin/login?msg=login_bad", status_code=303)
    auth.note_ok(ip)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.session_cookie(config.ADMIN_USER), max_age=auth.SESSION_TTL,
                    httponly=True, samesite="lax", secure=config.SECURE_COOKIES, path="/")
    return resp


@router.post("/admin/logout")
def logout(request: Request) -> Response:
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# ---------- клиники ----------


_CLINICS_SQL = """SELECT c.*, s.plan, s.valid_until, s.grace_days,
                         (SELECT MAX(seq) FROM issues i WHERE i.clinic_id = c.id) AS seq
                  FROM clinics c LEFT JOIN subscriptions s ON s.clinic_id = c.id
                  ORDER BY c.created_at DESC"""
# архив (archive.py): клиники вне списка, фильтров и цифр — своей вкладкой, с тем, что не даёт удалить
_ARCHIVE_SQL = _CLINICS_SQL.replace("ORDER BY c.created_at DESC", "WHERE c.archived_at IS NOT NULL ORDER BY c.archived_at DESC")
_CLINICS_SQL = _CLINICS_SQL.replace("ORDER BY c.created_at DESC", "WHERE c.archived_at IS NULL ORDER BY c.created_at DESC")


# происхождения заявок — из trial.ORIGINS, а не перечислением: «Adaugă clinică» (cont_add, 26.10) иначе
# не попала бы в очередь, а без ключа выдачи (account.start_paid) её файл ждёт Олега
_REQUESTS_SQL = (f"SELECT c.* FROM clinics c WHERE c.origin IN ({', '.join(repr(o) for o in trial.ORIGINS)}) "
                 "AND c.declined_at IS NULL AND c.archived_at IS NULL AND NOT EXISTS (SELECT 1 FROM issues i WHERE i.clinic_id = c.id) "
                 "ORDER BY c.requested_at DESC")


@router.get("/admin", response_class=HTMLResponse)
def clinics(request: Request, msg: str = "", state: str = "") -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_CLINICS_SQL).fetchall()
        requests = con.execute(_REQUESTS_SQL).fetchall()
        pending, names = web.pending_count(con), web.names_count(con)
        lives = {r["id"]: archive.live_until(con, r) for r in rows}
        archived = [(r, archive.blockers(con, r["id"]), archive.live_until(con, r))
                    for r in con.execute(_ARCHIVE_SQL).fetchall()]
    return HTMLResponse(views.clinics_page(rows, auth.current_user(request), msg, requests=requests, state=state,
                                           pending=pending, names=names, archived=archived, lives=lives))


@router.post("/admin/clinics/{cid}/archive")
def clinic_archive(request: Request, cid: str, reason: str = Form("")) -> Response:
    """«В архив» (11.11, archive.py): метка; действующий файл не отзывается — окно предлагает «Отозвать» раньше."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        code = archive.archive(con, c, reason, auth.current_user(request))
    return RedirectResponse(f"/admin?msg={code}", status_code=303)


@router.post("/admin/clinics/{cid}/unarchive")
def clinic_unarchive(request: Request, cid: str) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        code = archive.unarchive(con, c, auth.current_user(request))
    return RedirectResponse(f"/admin?msg={code}", status_code=303)


@router.post("/admin/clinics/{cid}/delete")
def clinic_delete(request: Request, cid: str, reason: str = Form(""), confirm: str = Form("")) -> Response:
    """«Удалить навсегда» — только из архива; можно ли, решает живая база в этой транзакции (archive.blockers)."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return RedirectResponse("/admin?msg=delete_gone", status_code=303)
        code = archive.delete(con, c, reason, confirm, auth.current_user(request))
    return RedirectResponse(f"/admin?msg={code}", status_code=303)


@router.post("/admin/clinics/{cid}/decline")
def trial_decline(request: Request, cid: str) -> Response:
    """Скрыть заявку с формы: пробный не выдан, клиника остаётся (и её IDNO/e-mail —
    в правиле «второго пробного нет»)."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        if web.clinic(con, cid) is None:
            return Response(status_code=404)
        # токен — долой: программа, ждущая по этой заявке, получит 401 и скажет
        # «cererea nu mai este activă», а не будет спрашивать вечно
        con.execute("UPDATE clinics SET declined_at=?, renew_token='' WHERE id=?", (db.now_iso(), cid))
        db.audit(con, auth.current_user(request), "trial_declined", cid, "")
    return RedirectResponse("/admin?msg=trial_declined", status_code=303)


def _clean(name: str, idno: str) -> str:
    if not name.strip() or len(name.strip()) > 120:
        return "bad_name"
    if idno.strip() and not _IDNO.match(idno.strip()):
        return "bad_idno"
    return ""


@router.post("/admin/clinics")
def clinic_new(request: Request, name: str = Form(""), idno: str = Form(""),
               contact_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
               address: str = Form("")) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if (code := _clean(name, idno)):
        return RedirectResponse(f"/admin?msg={code}", status_code=303)
    cid = "c_" + secrets.token_hex(6)
    with db.connect(immediate=True) as con:
        con.execute("INSERT INTO clinics(id, name, idno, contact_name, email, phone, address, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (cid, name.strip(), idno.strip(), contact_name.strip(), email.strip(),
                     phone.strip(), address.strip(), db.now_iso()))
        db.audit(con, auth.current_user(request), "clinic_new", cid, name.strip())
    return RedirectResponse(f"/admin/clinics/{cid}?msg=clinic_ok", status_code=303)


@router.get("/admin/clinics/{cid}", response_class=HTMLResponse)
def clinic_card(request: Request, cid: str, msg: str = "", log: str = "") -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response("нет такой клиники", status_code=404)
        sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (cid,)).fetchone()
        issues = con.execute("SELECT * FROM issues WHERE clinic_id=? ORDER BY seq DESC", (cid,)).fetchall()
        # вкладка «Журнал»: фильтр по разделу (?log=pay#log), числа у фильтров — по всем событиям клиники
        codes = views.audit_codes(log)
        only = f" AND what IN ({','.join('?' * len(codes))})" if codes else ""
        audit = con.execute(f"SELECT * FROM audit WHERE clinic_id=?{only} ORDER BY id DESC LIMIT 50",
                            (cid, *codes)).fetchall()
        log_counts = dict(con.execute("SELECT what, count(*) FROM audit WHERE clinic_id=? GROUP BY what",
                                      (cid,)).fetchall())
        # ноты клиники — свои и общие ноты кабинета, где она строкой (26.10)
        pays = payments.of_clinic(con, cid)
        rems = con.execute("SELECT * FROM reminders WHERE subscription_id=? ORDER BY sent_at DESC, rowid DESC",
                           (cid,)).fetchall()
        pending = web.pending_count(con)
        accounts = account.of_clinic(con, cid)
        devices = fleet.of_clinic(con, cid)
        smsinfo = smsreport.clinic_detail(con, cid)
        names = web.names_count(con)
        active = fleet.active(con)
        cab = [(r, con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (r["id"],)).fetchone(),
                con.execute("SELECT count(*) FROM devices WHERE clinic_id=?", (r["id"],)).fetchone()[0])
               for r in cabinet.of(con, cid) if r["id"] != cid]
        acts = terms.admin_fragment(terms.of_clinic(con, cid))        # акты акцепта условий (29.10)
        docs = contracts.of_clinic(con, cid)
    return HTMLResponse(views.clinic_page(c, sub, issues, audit, auth.current_user(request), msg,
                                          payments=pays, pending=pending, reminders=rems, accounts=accounts,
                                          devices=devices, smsinfo=smsinfo, names=names,
                                          log=log if codes else "", log_counts=log_counts,
                                          cabinet=cab, active=active.get(cid, 0), terms_html=acts, docs=docs))


@router.post("/admin/clinics/{cid}/sibling")
def clinic_sibling(request: Request, cid: str, name: str = Form(""), address: str = Form(""),
                   phone: str = Form(""), email: str = Form(""), idno: str = Form(""),
                   contact_name: str = Form("")) -> Response:
    """«Добавить клинику в кабинет» (26.10): ещё одна клиника с теми же входами кабинета, что у
    этой; тот же IDNO и ящик разрешены, если совпавшая клиника — этого кабинета. Пробный — как у
    клиники из админки: кнопкой во вкладке «Лицензия» новой карточки."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if (code := _clean(name, idno)):
        return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)
    if not address.strip():
        return RedirectResponse(f"/admin/clinics/{cid}?msg=need_address", status_code=303)
    f = {"name": " ".join(name.split()), "address": " ".join(address.split()), "phone": phone.strip(),
         "email": "".join(email.split()), "idno": idno.strip(), "contact_name": " ".join(contact_name.split())}
    with db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        if not account.of_clinic(con, cid):
            return RedirectResponse(f"/admin/clinics/{cid}?msg=sibling_no_cabinet", status_code=303)
        if revoke.in_cabinet(con, cid):
            return RedirectResponse(f"/admin/clinics/{cid}?msg=revoke_add", status_code=303)
        outcome, new = account.add_sibling(con, c, f, auth.current_user(request))
    if outcome == trial.DUPLICATE:
        return RedirectResponse(f"/admin/clinics/{cid}?msg=sibling_duplicate", status_code=303)
    return RedirectResponse(f"/admin/clinics/{new['id']}?msg=sibling_added", status_code=303)


# ---------- флот (шаг 3, 02.10): компьютеры клиник и их версии ----------


@router.get("/admin/fleet", response_class=HTMLResponse)
def fleet_page(request: Request, msg: str = "") -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        rep = fleet.report(con)
        pending = web.pending_count(con)
        names = web.names_count(con)
    return HTMLResponse(views.fleet_page(rep, auth.current_user(request), msg, pending, names))


@router.get("/admin/api/fleet")
def fleet_api(request: Request) -> Response:
    """Тот же отчёт JSON — для будущего интерфейса админки. Кука админа; без неё
    401 JSON, а не 303 на вход (fetch принял бы форму входа за ответ)."""
    if auth.current_user(request) is None:
        return JSONResponse({"ok": False, "code": "login"}, status_code=401)
    with db.connect() as con:
        rep = fleet.report(con)
    return JSONResponse({"ok": True, "data": rep})


# ---------- модуль «SMS» (S4): кто сколько отправил, имена, деньги ----------


def _period_args(request: Request) -> tuple[str, date | None, date | None]:
    q = request.query_params
    kind = q.get("period") or "month"

    def _d(s):
        try:
            return date.fromisoformat((s or "").strip()) if s else None
        except ValueError:
            return None
    return kind, _d(q.get("from")), _d(q.get("to"))


@router.get("/admin/sms", response_class=HTMLResponse)
def sms_admin(request: Request, msg: str = "") -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    kind, frm, to = _period_args(request)
    with db.connect() as con:
        rep = smsreport.report(con, kind, frm, to)
        pending = web.pending_count(con)
    return HTMLResponse(views.sms_page(rep, auth.current_user(request), msg, pending))


@router.get("/admin/api/sms")
def sms_api(request: Request) -> Response:
    """Тот же отчёт JSON — для будущего интерфейса админки; без куки 401 JSON, не 303."""
    if auth.current_user(request) is None:
        return JSONResponse({"ok": False, "code": "login"}, status_code=401)
    kind, frm, to = _period_args(request)
    with db.connect() as con:
        rep = smsreport.report(con, kind, frm, to)
    return JSONResponse({"ok": True, "data": rep})


@router.get("/admin/sms/export.xlsx")
def sms_export(request: Request, month: str = "") -> Response:
    """Excel за месяц по клиникам — для сверки с фактурой sms.md. Без номеров и текстов."""
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect(immediate=True) as con:
        name, data = smsreport.export(con, month)
        db.audit(con, auth.current_user(request), "sms_export", None, name)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/admin/sms/sync")
def sms_sync(request: Request) -> Response:
    """Сверить имена с sms.md сейчас — то же, что делает ежедневная задача."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if not smsmd.enabled():
        return RedirectResponse("/admin/sms?msg=sms_unconfigured", status_code=303)
    try:
        sms.sync_aliases(auth.current_user(request))
    except (smsmd.Unanswered, smsmd.Refused) as e:
        log.error("сверка имён с sms.md: %s", e)
        return RedirectResponse("/admin/sms?msg=sms_sync_failed", status_code=303)
    return RedirectResponse("/admin/sms?msg=sms_synced", status_code=303)


@router.post("/admin/sms/test")
def sms_test(request: Request, to: str = Form("")) -> Response:
    """Тестовая SMS себе от общего имени, мимо пакетов клиник. Номер — только в
    памяти запроса: в журнал идёт факт и исход, без цифр."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if not smsmd.enabled():
        return RedirectResponse("/admin/sms?msg=sms_unconfigured", status_code=303)
    digits, why = sms_rule.phone(to)
    if why:
        return RedirectResponse("/admin/sms?msg=sms_test_phone", status_code=303)
    who = auth.current_user(request)
    try:
        got = smsmd.send(config.SMS_COMMON, digits, "DentPilot: SMS de test. O zi buna!")
    except (smsmd.Unanswered, smsmd.Refused) as e:
        with db.connect(immediate=True) as con:
            db.audit(con, who, "sms_test", None, f"не принято: {e}")
        return RedirectResponse("/admin/sms?msg=sms_test_failed", status_code=303)
    with db.connect(immediate=True) as con:
        db.audit(con, who, "sms_test", None, f"принято sms.md, {got['segments']} сегм., id {got['id']}")
    return RedirectResponse("/admin/sms?msg=sms_test_sent", status_code=303)


@router.post("/admin/clinics/{cid}/sms")
def clinic_sms_action(request: Request, cid: str, action: str = Form(""), value: str = Form(""),
                      reason: str = Form(""), note: str = Form(""), name: str = Form(""),
                      custom_ro: str = Form(""), custom_ru: str = Form(""), custom_on: str = Form("")) -> Response:
    """Кнопки карточки › SMS: вкл/выкл, пилот, потолок, начисление с причиной, имя
    (заявка; заявление получено → подано → отказ). Каждое — строка в журнале."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    back = f"/admin/clinics/{cid}"
    with db.connect(immediate=True) as con:
        if web.clinic(con, cid) is None:
            return Response(status_code=404)
        code = "sms_saved"
        if action in ("on", "off"):
            sms.set_enabled(con, cid, action == "on", who)
        elif action in ("pilot_on", "pilot_off"):
            sms.set_pilot(con, cid, action == "pilot_on", who)
        elif action == "cap":
            try:
                code = sms.set_cap(con, cid, int(value), who) or code
            except ValueError:
                code = "cap_bad"
        elif action == "credit":
            try:
                delta = int(value)
            except ValueError:
                return RedirectResponse(f"{back}?msg=credit_amount", status_code=303)
            code = sms.credit(con, cid, delta, reason, note, who) or "sms_credited"
        elif action in ("paper", "submitted", "rejected"):
            # имя общее на кабинет (26.10): шаги — у его хозяйки (главной клиники)
            code = sms.sender_step(con, sms.name_owner(con, cid), action, who, note) or code
        elif action == "request":
            code = sms.request_sender(con, cid, name, who) or code
        elif action == "custom":
            code = sms.set_custom(con, cid, custom_ro, custom_ru, custom_on == "1", who) or code
        else:
            code = "sms_action"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)



@router.get("/admin/clinics/{cid}/sms/cerere.pdf")
def clinic_sms_paper(request: Request, cid: str) -> Response:
    """Подписанное заявление клиники на имя (загружено в кабинете, sms_paper.py) —
    файлом, для подачи в кабинете sms.md. ⚠️ Файл прислала клиника: отдаётся
    вложением с nosniff, а не в окно админки. Нет файла у текущей заявки — 404."""
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        p = sms_paper.current(con, cid, body=True)
    if p is None:
        return Response(status_code=404)
    return Response(p["body"], media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{sms_paper.filename(p["sender"])[:-4]}-semnata.pdf"',
                             "X-Content-Type-Options": "nosniff"})

# ---------- документы (29.10, contracts.py): экземпляр, подписанный клиникой — файлом ----------


@router.get("/admin/clinics/{cid}/documente/{rid}.pdf")
def clinic_document_file(request: Request, cid: str, rid: int) -> Response:
    """⚠️ Файл прислала клиника: вложением с nosniff, не в окно админки. Нет строки или файла — 404."""
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        r = contracts.get(con, rid)
        c = web.clinic(con, cid)
    if r is None or c is None or r["clinic_id"] != cid:
        return Response(status_code=404)
    data = contracts.read_file(r)
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{contracts.clinic_filename(c, r)}"',
                             "X-Content-Type-Options": "nosniff"})


# ---------- ежедневная задача и журнал (L9) ----------


@router.post("/admin/jobs/daily")
def daily_job(request: Request) -> Response:
    """То же, что cron: напоминания по таблице за сегодня. Повторный запуск в тот же
    день ничего не шлёт — ключ (подписка, kind, period) в reminders."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    rep = jobs.daily(who=auth.current_user(request))
    return RedirectResponse("/admin?msg=" + ("daily_failed" if rep.failed else "daily_done"), status_code=303)


_AUDIT_SQL = """SELECT a.*, c.name AS clinic FROM audit a LEFT JOIN clinics c ON c.id = a.clinic_id
                ORDER BY a.id DESC LIMIT 200"""


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_log(request: Request, msg: str = "", kind: str = "") -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    codes = views.audit_codes(kind)  # раздел журнала (?kind=pay); неизвестный — «все»
    only = f"WHERE a.what IN ({','.join('?' * len(codes))}) " if codes else ""
    with db.connect() as con:
        rows = con.execute(_AUDIT_SQL.replace("ORDER BY", only + "ORDER BY", 1), codes).fetchall()
        by_what = dict(con.execute("SELECT what, count(*) FROM audit GROUP BY what").fetchall())
        pending, names = web.pending_count(con), web.names_count(con)
    return HTMLResponse(views.audit_page(rows, auth.current_user(request), msg, pending,
                                         kind=kind if codes else "", by_what=by_what, names=names))


@router.post("/admin/clinics/{cid}/edit")
def clinic_edit(request: Request, cid: str, name: str = Form(""), idno: str = Form(""),
                contact_name: str = Form(""), email: str = Form(""), phone: str = Form(""),
                address: str = Form("")) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if (code := _clean(name, idno)):
        return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)
    with db.connect(immediate=True) as con:
        if (old := web.clinic(con, cid)) is None:
            return Response(status_code=404)
        con.execute("UPDATE clinics SET name=?, idno=?, contact_name=?, email=?, phone=?, address=? WHERE id=?",
                    (name.strip(), idno.strip(), contact_name.strip(), email.strip(), phone.strip(),
                     address.strip(), cid))
        db.audit(con, auth.current_user(request), "clinic_edit", cid, name.strip())
        # другой ящик — снова не подтверждён (27.10): доказан был прежний
        if trial.canonical(email.strip() or "-@-") != trial.canonical(old["email"] or "-@-"):
            con.execute("UPDATE clinics SET email_confirmed_at=NULL WHERE id=?", (cid,))
            if old["email_confirmed_at"]:
                db.audit(con, auth.current_user(request), "email_reset", cid,
                         f"{old['email']} → {email.strip() or '—'}")
    return RedirectResponse(f"/admin/clinics/{cid}?msg=saved", status_code=303)


# ---------- выдача файла ----------


@router.post("/admin/clinics/{cid}/issue")
def clinic_issue(request: Request, cid: str, kind: str = Form("trial"), valid_until: str = Form(""),
                 grace_days: str = Form(str(license.GRACE_DAYS)), reason: str = Form(""),
                 send: str = Form("")) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    # письмо о выдаче собирается в транзакции, уходит после её commit (06.11: SMTP шёл под её замком)
    with payments.outbox() as box, db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        if revoke.is_revoked(c):
            # поверх отзыва — только «Вернуть»: ручная выдача молча сняла бы отзыв, оставив отметку
            return RedirectResponse(f"/admin/clinics/{cid}?msg=revoke_issue", status_code=303)
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
        if send == "1":
            box.add([(True, license.letter_latest(con, c, who))])
    code = (box.code or "issued_mailed") if send == "1" else "issued"
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)


@router.post("/admin/clinics/{cid}/revoke")
def clinic_revoke(request: Request, cid: str, reason: str = Form(""), confirm: str = Form(""),
                  send: str = Form("")) -> Response:
    """«Отозвать лицензию» (11.11, revoke.py): причина обязательна, подтверждение — вписанное слово
    «ОТОЗВАТЬ»; письмо клинике — только галочкой (по умолчанию снята), после commit."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    with payments.outbox() as box, db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        try:
            code = revoke.revoke(con, c, reason, confirm, who)
        except RuntimeError:
            return RedirectResponse(f"/admin/clinics/{cid}?msg=no_key", status_code=303)
        except ValueError as e:
            return RedirectResponse(f"/admin/clinics/{cid}?msg=bad_{e}", status_code=303)
        if code:
            return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)
        if send == "1":
            box.add([(True, revoke.letter(c, who))])
    msg = (box.code or "revoked_mailed") if send == "1" else revoke.REVOKED
    return RedirectResponse(f"/admin/clinics/{cid}?msg={msg}", status_code=303)


@router.post("/admin/clinics/{cid}/restore")
def clinic_restore(request: Request, cid: str, reason: str = Form("")) -> Response:
    """«Вернуть лицензию»: файл с прежним сроком (revoke.restore); письма нет."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        try:
            code = revoke.restore(con, c, reason, auth.current_user(request))
        except RuntimeError:
            return RedirectResponse(f"/admin/clinics/{cid}?msg=no_key", status_code=303)
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)


@router.post("/admin/clinics/{cid}/tier")
def clinic_tier(request: Request, cid: str, tier: str = Form("")) -> Response:
    """Вариант абонемента вручную — для исключений (Олег 23.10): сразу, без оплаты, строкой
    в журнале (tier_set). Обычный путь — выбор клиники при оплате (payments.choose). Цены
    здесь нет: цена варианта — всегда прайс (Олег 26.10: «600 везде»)."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        if web.clinic(con, cid) is None:
            return Response(status_code=404)
        code = payments.set_tier(con, cid, tier, auth.current_user(request))
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code or 'tier_set'}", status_code=303)


@router.get("/admin/clinics/{cid}/issues/{seq}/license.json")
def issue_file(request: Request, cid: str, seq: int) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    with db.connect() as con:
        row = con.execute("SELECT * FROM issues WHERE clinic_id=? AND seq=?", (cid, seq)).fetchone()
    if row is None:
        return Response(status_code=404)
    return Response(license.issue_text(row), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="license.json"'})


@router.post("/admin/clinics/{cid}/email")
def clinic_email(request: Request, cid: str) -> Response:
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    # письмо собирается в транзакции (код подтверждения ящика — запись), уходит после её commit
    with payments.outbox() as box, db.connect(immediate=True) as con:
        c = web.clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        box.add([(True, license.letter_latest(con, c, auth.current_user(request)))])
    return RedirectResponse(f"/admin/clinics/{cid}?msg={box.code or 'mailed'}", status_code=303)


@router.post("/admin/accounts/{aid}/detach")
def account_detach(request: Request, aid: str) -> Response:
    """Отвязать учётную запись кабинета от клиники (смена директора): запись
    удаляется, следующий вход этого аккаунта Google начинается с регистрации."""
    if (deny := web.guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        acc = account.get(con, aid)
        if acc is None:
            return Response(status_code=404)
        cid = acc["clinic_id"]
        account.detach(con, acc, auth.current_user(request))
    return RedirectResponse(f"/admin/clinics/{cid}?msg=account_detached" if cid else "/admin", status_code=303)
