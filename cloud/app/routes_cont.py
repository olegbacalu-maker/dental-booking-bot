"""Кабинет клиники `/cont*` (03.11, из main.py): вход Google и кодом на e-mail, вход кнопкой
программы, регистрация, данные, нота и общая нота, SMS-имя и заявление, документы и образцы 195,
«Adaugă clinică», код компьютера, акты акцепта. Каждый маршрут /cont… разобран в
`tests/test_contlink.py::ROUTES`."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import (account, auth, cabinet, config, contlink, contracts, db, download, emailconf, fleet, jobs, maib, mail,
               modele, payments, paylink, receipts, sms, sms_paper, terms, tiers, trial, views, web)
from . import login as elogin  # ⚠️ не `login`: так зовётся маршрут входа админки (routes_admin)

log = logging.getLogger("cloud")
router = APIRouter()


# ---------- кабинет клиники (шаг 3, 01.10): вход через Google, /cont ----------
#
# Публичная часть сервера по-румынски, своя кука (dp_cont), без админки.
# Поток входа — account.py; здесь только маршруты: что показать и куда вести.


def _cookie_args() -> dict:
    return {"httponly": True, "samesite": "lax", "secure": config.SECURE_COOKIES}


def _current_account(con, request: Request):
    """Учётная запись из куки кабинета — строкой из базы (отвязанная не пускает)."""
    aid = auth.current_account_id(request)
    if aid:
        return account.get(con, aid)
    return contlink.session(con, request)          # вход кнопкой программы (27.10): одна клиника


def _full_account(con, request: Request) -> bool:
    """Вошёл ли в кабинет целиком (Google или код на e-mail), а не кнопкой программы."""
    acc = _current_account(con, request)
    return acc is not None and not account.scoped(acc)


def _cont_login_redirect() -> Response:
    return RedirectResponse("/cont/login", status_code=303)


def _cont_to(con, acc, cid: str, msg: str = "") -> str:
    """Адрес возврата в кабинет: у записи с несколькими клиниками — с открытой (?c=), у
    одной — прежний «/cont?msg=…»."""
    parts = [f"c={cid}"] if len(account.clinics(con, acc)) > 1 else []
    if msg:
        parts.append(f"msg={msg}")
    return "/cont" + ("?" + "&".join(parts) if parts else "")


def _cont_deny(acc) -> Response:
    """Формы без своей клиники: без входа — на вход; клиник несколько, а форма не назвала
    свою (вкладка до обновления) — назад, словами «reîncărcați»."""
    if acc is None:
        return _cont_login_redirect()
    return RedirectResponse("/cont?msg=pick_clinic", status_code=303)


def _cont_row(con, c) -> dict:
    """Клиника для списка «Clinicile mele»: подписка, файл, компьютеры, общая нота."""
    return {"c": c, "sub": con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (c["id"],)).fetchone(),
            "issue": con.execute("SELECT * FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1",
                                 (c["id"],)).fetchone(),
            "devices": con.execute("SELECT count(*) FROM devices WHERE clinic_id=?", (c["id"],)).fetchone()[0],
            "group": payments.group_of(con, c["id"])}


def _cont_dashboard(request: Request, msg: str, c: str, tab: str = "") -> Response:
    """Кабинет: дашборд открытой клиники по вкладкам (`?c=` — какой; без него — открытой последней),
    у записи с несколькими клиниками — чипы клиник под заголовком (26.10, 29.10). `tab` — вкладка
    по умолчанию (/cont/documente)."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        mine = account.clinics(con, acc)
        if not mine:
            return RedirectResponse("/cont/inregistrare", status_code=303)
        cl = account.pick(con, acc, c)
        if cl is None:
            return RedirectResponse("/cont", status_code=303)        # чужая или нет такой — на открытую
        if cl["id"] != acc["clinic_id"]:
            con.execute("UPDATE accounts SET clinic_id=? WHERE id=?", (cl["id"], acc["id"]))
        sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (cl["id"],)).fetchone()
        issue = con.execute("SELECT * FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1",
                            (cl["id"],)).fetchone()
        pays = payments.of_clinic(con, cl["id"])
        devices = fleet.of_clinic(con, cl["id"])
        group = payments.group_of(con, cl["id"])
        cab = [_cont_row(con, r) for r in mine] if len(mine) > 1 else []
        q = f"?c={cl['id']}" if len(mine) > 1 else ""
        sa = con.execute("SELECT * FROM sms_accounts WHERE clinic_id=?", (cl["id"],)).fetchone()
        smsinfo = None
        # пакеты SMS (05.11) — у СВОЕЙ клиники, и у филиала из кнопки программы тоже: остаток,
        # прайс, кому не продаётся (те же коды, что программе — web.SMS_CLOSED). Только чтение:
        # счёт не заводится просмотром
        smsshop = None
        if sms.offered(sa):
            why = sms.blocked(con, cl["id"], sa, datetime.now(timezone.utc))
            smsshop = {"balance": sms.balance(con, cl["id"]), "packs": sms.packs(),
                       "closed": why if why in web.SMS_CLOSED else ""}
        # вход кнопкой программы (27.10): одна клиника; в кабинете ли она с другими — только для
        # текста о коде компьютера, без их имён
        scoped = account.scoped(acc)
        branch = scoped and len(cabinet.of(con, cl["id"])) > 1
        if sms.offered(sa) and not (scoped and sms.name_owner(con, cl["id"]) != cl["id"]):
            # ⛔ имя SMS филиала — у главной клиники: сессии кнопки филиала оно не открывается
            # имя общее на кабинет (26.10): заявка, заявление и год — у главной клиники; строка счёта
            # не заводится просмотром: без неё — «имени нет»
            owner = web.clinic(con, sms.name_owner(con, cl["id"]))
            osa = con.execute("SELECT * FROM sms_accounts WHERE clinic_id=?", (owner["id"],)).fetchone()
            mine_name = owner["id"] == cl["id"]
            smsinfo = {"acc": osa, "from": sms.sender_for(con, cl["id"]), "suggest": sms.suggest(owner["name"]),
                       "paper": sms_paper.current(con, owner["id"]), "missing": sms_paper.missing(owner),
                       "clinic": owner, "shared": "" if mine_name else owner["name"],
                       "data_href": "#clinica" if mine_name else f"/cont?c={owner['id']}#clinica"}
        # вкладка «Documente» (29.10, contracts.py): экземпляры клиники и акты акцепта (terms.py)
        docs_mine = contracts.of_clinic(con, cl["id"])
        docs_fragment = contracts.terms_fragment(con, cl, q)
        modele_sms = modele.sms_on(sa)
    # последний выпуск — из памяти или одним запросом к API; вне транзакции
    return HTMLResponse(views.cont_page(acc, cl, sub, issue, pays, download.latest(), msg, devices=devices,
                                        smsinfo=smsinfo, smsshop=smsshop, cab=cab, group=group, scoped=scoped,
                                        branch=branch,
                                        docs=contracts.statuses(), docs_mine=docs_mine, docs_fragment=docs_fragment,
                                        tab=tab, modele_sms=modele_sms))


@router.get("/cont", response_class=HTMLResponse)
def cont_home(request: Request, msg: str = "", c: str = "") -> Response:
    return _cont_dashboard(request, msg, c)


@router.get(contlink.PATH + "/{lid}", response_class=HTMLResponse)
def cont_from_program_page(lid: str) -> Response:
    """Вход из программы, шаг 1: страница с кнопкой «Intră în contul clinicii» (POST сюда же).
    ⛔ GET ничего не гасит (канарейка 2.3.0, 27.10): окно программы открывало адрес само, прежде
    чем отдать его браузеру Windows, — и тот получал 410. Мёртвая или истёкшая — 410 словами."""
    with db.connect() as con:
        c = contlink.peek(con, lid)
    if c is None:
        return HTMLResponse(views.cont_link_expired_page(), status_code=410)
    return HTMLResponse(views.cont_link_enter_page(c["name"], f"{contlink.PATH}/{lid}"))


@router.post(contlink.PATH + "/{lid}", response_class=HTMLResponse)
def cont_from_program(request: Request, lid: str) -> Response:
    """Одноразовый вход из программы, шаг 2 (27.10, contlink.py): ссылка жива и не открыта — гаснет,
    кука кабинета «только эта клиника» → /cont. Уже вошедший во весь кабинет с этой клиникой —
    остаётся при своём входе (ссылка всё равно гаснет). Иначе — 410 словами: нажать кнопку снова.
    В журнал — адрес и браузер (User-Agent): кто вошёл, разбирается без гаданий."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = web.ip(request)
    ua = " ".join((request.headers.get("user-agent") or "?").split())[:160]
    with db.connect(immediate=True) as con:
        c = contlink.use(con, lid, ip)
        if c is None:
            return HTMLResponse(views.cont_link_expired_page(), status_code=410)
        db.audit(con, "program", "cont_program", c["id"], f"вход кнопкой программы, {ip}, {ua}")
        acc = _current_account(con, request)
        keep = acc is not None and not account.scoped(acc) and any(
            r["id"] == c["id"] for r in account.clinics(con, acc))
    if keep:
        return RedirectResponse(f"/cont?c={c['id']}", status_code=303)
    resp = RedirectResponse("/cont", status_code=303)
    resp.set_cookie(auth.ACCOUNT_COOKIE, auth.clinic_cookie(c["id"]), max_age=auth.ACCOUNT_TTL, path="/",
                    **_cookie_args())
    return resp


@router.get("/cont/login", response_class=HTMLResponse)
def cont_login(request: Request, msg: str = "") -> Response:
    with db.connect() as con:
        # вошедший кнопкой программы (одна клиника) может войти во весь кабинет — страница входа ему открыта
        if _full_account(con, request):
            return RedirectResponse("/cont", status_code=303)
    return HTMLResponse(views.cont_login_page(msg, enabled=account.enabled()))


@router.post("/cont/login/email", response_class=HTMLResponse)
def cont_login_email(request: Request, email: str = Form("")) -> Response:
    """Вход без Google (02.10): код на введённый ящик. Ответ одинаков для любого
    годного ящика; лимиты — login.py; письмо — после транзакции."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        if _full_account(con, request):
            return RedirectResponse("/cont", status_code=303)
    email = "".join(email.split()).lower()
    on = account.enabled()
    if not elogin.email_ok(email):
        return HTMLResponse(views.cont_login_page("bad_email", enabled=on, values={"email": email}), status_code=400)
    ip = web.ip(request)
    if elogin.request_limited(ip):
        return HTMLResponse(views.cont_login_page("login_limited", enabled=on, values={"email": email}),
                            status_code=429)
    with db.connect(immediate=True) as con:
        vid, code = elogin.new_code(con, email, ip)
    if not vid:
        return HTMLResponse(views.cont_login_page("login_limited", enabled=on, values={"email": email}),
                            status_code=429)
    subject, body = mail.login_code(code, int(elogin.CODE_TTL.total_seconds() // 60))
    try:
        mail.send(email, subject, body)
    except (RuntimeError, OSError, ValueError) as e:
        log.error("код входа на %s не отправлен: %r", email, e)
        return HTMLResponse(views.cont_login_page("mail_failed", enabled=on, values={"email": email}),
                            status_code=502)
    return HTMLResponse(views.cont_email_code_page(vid, email))


@router.post("/cont/login/cod", response_class=HTMLResponse)
def cont_login_code(request: Request, verify_id: str = Form(""), code: str = Form(""),
                    email: str = Form("")) -> Response:
    """Код из письма → учётная запись e-mail и кука кабинета; клиника с этим
    ящиком есть → кабинет, нет → регистрация. Одноразовый, CODE_TTL,
    CODE_ATTEMPTS ошибок на код, VERIFY_PER_HOUR проверок с адреса."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = web.ip(request)
    vid = verify_id.strip()[:64]
    code = "".join(code.split())[:12]
    email = "".join(email.split())[:trial.EMAIL_MAX].lower()
    if trial.verify_limited(ip):
        return HTMLResponse(views.cont_email_code_page(vid, email, "code_limited"), status_code=429)
    acc = None
    with db.connect(immediate=True) as con:
        found = elogin.check_code(con, vid, code, ip) if vid and code else None
        if found:
            acc = account.login_email(con, found, ip)
    if acc is None:
        return HTMLResponse(views.cont_email_code_page(vid, email, "bad_code"), status_code=400)
    resp = RedirectResponse("/cont" if acc["clinic_id"] else "/cont/inregistrare", status_code=303)
    resp.set_cookie(auth.ACCOUNT_COOKIE, auth.account_cookie(acc["id"]), max_age=auth.ACCOUNT_TTL, path="/",
                    **_cookie_args())
    return resp


@router.get("/auth/google")
def google_start(request: Request) -> Response:
    """К Google: state и nonce — в подписанной куке на время входа."""
    if not account.enabled():
        return HTMLResponse(views.cont_login_page(account.OFF, enabled=False), status_code=503)
    url, cookie = account.begin()
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(auth.OAUTH_COOKIE, cookie, max_age=auth.OAUTH_TTL, path="/auth/google", **_cookie_args())
    return resp


def _google_login(ident: account.Identity, ip: str):
    with db.connect(immediate=True) as con:
        return account.login(con, ident, ip)


@router.get(account.CALLBACK_PATH)
async def google_callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
    """От Google: state против куки, код → id_token (в потоке: сеть), проверка
    claim'ов, учётная запись. Клиника по ящику уже есть → кабинет; нет → регистрация."""
    if not account.enabled():
        return HTMLResponse(views.cont_login_page(account.OFF, enabled=False), status_code=503)
    if error:
        return RedirectResponse(f"/cont/login?msg={account.DENIED}", status_code=303)
    ident, why = await run_in_threadpool(account.finish, code, state,
                                         request.cookies.get(auth.OAUTH_COOKIE, ""))
    if ident is None:
        resp = RedirectResponse(f"/cont/login?msg={why}", status_code=303)
        resp.delete_cookie(auth.OAUTH_COOKIE, path="/auth/google")
        return resp
    acc = await run_in_threadpool(_google_login, ident, web.ip(request))
    resp = RedirectResponse("/cont" if acc["clinic_id"] else "/cont/inregistrare", status_code=303)
    resp.set_cookie(auth.ACCOUNT_COOKIE, auth.account_cookie(acc["id"]), max_age=auth.ACCOUNT_TTL, path="/",
                    **_cookie_args())
    resp.delete_cookie(auth.OAUTH_COOKIE, path="/auth/google")
    return resp


@router.post("/cont/iesire")
def cont_logout(request: Request) -> Response:
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    resp = RedirectResponse("/cont/login?msg=logged_out", status_code=303)
    resp.delete_cookie(auth.ACCOUNT_COOKIE, path="/")
    return resp


@router.get("/cont/inregistrare", response_class=HTMLResponse)
def cont_register(request: Request, msg: str = "") -> Response:
    with db.connect() as con:
        acc = _current_account(con, request)
    if acc is None:
        return _cont_login_redirect()
    if acc["clinic_id"]:
        return RedirectResponse("/cont", status_code=303)
    return HTMLResponse(views.cont_register_page(acc, msg))


@router.post("/cont/inregistrare", response_class=HTMLResponse)
def cont_register_submit(request: Request, name: str = Form(""), idno: str = Form(""),
                         contact_name: str = Form(""), phone: str = Form(""), consent: str = Form("")) -> Response:
    """Регистрация = заявка на пробный теми же правилами, что /proba (лимит с адреса,
    trial.clean, одна клиника на IDNO/e-mail); e-mail — ящик Google. Повтор по IDNO
    (директор входит личным Gmail, а клиника заведена с другим ящиком) — код на
    ящик клиники, как у программы на новом компьютере: страница кода, письмо
    Олегу. Ящика у клиники нет или лимит — 409 словами."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        acc = _current_account(con, request)
    if acc is None:
        return _cont_login_redirect()
    if acc["clinic_id"]:
        return RedirectResponse("/cont", status_code=303)
    ip = web.ip(request)
    if trial.limited(ip):
        return HTMLResponse(views.cont_register_page(acc, "limited"), status_code=429)
    f, code = trial.clean({"name": name, "idno": idno, "contact_name": contact_name, "email": acc["email"],
                           "phone": phone, "consent": consent})
    if code:
        return HTMLResponse(views.cont_register_page(acc, code, f), status_code=400)
    trial.note(ip)
    vid = link_code = ""
    with db.connect(immediate=True) as con:
        outcome, clinic = account.register(con, acc, f, ip)
        if outcome == trial.DUPLICATE:
            vid, link_code = account.request_link(con, acc, clinic, ip)
    if vid:
        subject, body = mail.link_code(clinic["name"], link_code, int(trial.CODE_TTL.total_seconds() // 60),
                                       acc["email"], via="Google" if acc["provider"] == "google" else "e-mail")
        try:
            mail.send(clinic["email"], subject, body)
        except (RuntimeError, OSError, ValueError) as e:
            log.error("код подключения клинике %s не отправлен: %r", clinic["id"], e)
            vid = ""                   # кода у клиники нет — и вводить нечего
    trial.notify(clinic, outcome, ip, f, trial.ORIGIN_CONT)
    if outcome == trial.DUPLICATE:
        if vid:
            return HTMLResponse(views.cont_code_page(acc, vid))
        return HTMLResponse(views.cont_register_page(acc, "duplicate", f), status_code=409)
    if outcome == trial.REQUESTED:
        trial.acknowledge(clinic)
    issued = outcome in (trial.ISSUED, trial.ISSUED_UNMAILED)
    return RedirectResponse(f"/cont?msg={'registered_issued' if issued else 'registered_requested'}",
                            status_code=303)


@router.post("/cont/inregistrare/cod", response_class=HTMLResponse)
def cont_register_code(request: Request, verify_id: str = Form(""), code: str = Form("")) -> Response:
    """Код с ящика клиники → Google-аккаунт привязан к клинике с этим IDNO. Тот же
    activation_codes, что у программы на новом компьютере: одноразовый, CODE_TTL,
    CODE_ATTEMPTS ошибок на код, VERIFY_PER_HOUR проверок с адреса."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        acc = _current_account(con, request)
    if acc is None:
        return _cont_login_redirect()
    if acc["clinic_id"]:
        return RedirectResponse("/cont", status_code=303)
    ip = web.ip(request)
    vid = verify_id.strip()[:64]
    code = "".join(code.split())[:12]
    if trial.verify_limited(ip):
        return HTMLResponse(views.cont_code_page(acc, vid, "code_limited"), status_code=429)
    with db.connect(immediate=True) as con:
        clinic = account.confirm_link(con, acc, vid, code, ip) if vid and code else None
    if clinic is None:
        return HTMLResponse(views.cont_code_page(acc, vid, "bad_code"), status_code=400)
    return RedirectResponse("/cont?msg=linked", status_code=303)


def _cont_clinic(request: Request, con, c: str = "", post: bool = True):
    """(учётная запись, клиника) запроса кабинета. Клиника — названная формой (`?c=`) и своя;
    форма без неё — только у записи с ОДНОЙ клиникой (account.pick). (None, None) — без входа;
    (запись, None) — клиника не своя или форма её не назвала."""
    acc = _current_account(con, request)
    if acc is None:
        return None, None
    return acc, account.pick(con, acc, c, post=post)


@router.post("/cont/date")
def cont_edit(request: Request, name: str = Form(""), idno: str = Form(""), contact_name: str = Form(""),
              phone: str = Form(""), address: str = Form(""), c: str = "") -> Response:
    """Реквизиты клиники из кабинета. E-mail здесь не правится: по нему привязан
    вход. IDNO другой живой клиники не присвоить (своего кабинета — можно)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    f, code = account.clean_edit({"name": name, "idno": idno, "contact_name": contact_name, "phone": phone,
                                  "address": address})
    with db.connect() as con:
        acc, cl = _cont_clinic(request, con, c)
        if cl is None:
            return _cont_deny(acc)
        if code:
            return RedirectResponse(_cont_to(con, acc, cl["id"], code), status_code=303)
        if account.idno_taken(con, f["idno"], cl["id"]):
            return RedirectResponse(_cont_to(con, acc, cl["id"], "idno_taken"), status_code=303)
        con.execute("UPDATE clinics SET name=?, idno=?, contact_name=?, phone=?, address=? WHERE id=?",
                    (f["name"], f["idno"], f["contact_name"], f["phone"], f["address"], cl["id"]))
        db.audit(con, acc["email"], "clinic_edit", cl["id"], f"{f['name']} (din cont)")
        back = _cont_to(con, acc, cl["id"], "saved")
    return RedirectResponse(back, status_code=303)


@router.post("/cont/nota")
def cont_note(request: Request, months: str = Form("1"), method: str = Form(payments.TRANSFER),
              tier: str = Form(""), terms: str = Form(""), c: str = "") -> Response:
    """Нота на абонемент из кабинета: тот же выбор, что на странице оплаты
    (payments.choose — вариант и срок, другой заменяет открытую ноту, долг один); карта —
    только при настроенном maib; ⛔ без галочки условий — нет (требование maib). Письмо с
    нотой — как из админки, после commit ноты; maib — вне транзакции (`web.card_go`)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    m = web.months(months)
    card = method == payments.CARD and maib.enabled()
    plan = None
    with payments.outbox() as box, db.connect(immediate=True) as con:
        acc, cl = _cont_clinic(request, con, c)
        if cl is None:
            return _cont_deny(acc)
        if m not in payments.MONTHS:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "bad_months"), status_code=303)
        if terms != "1":
            return RedirectResponse(_cont_to(con, acc, cl["id"], "need_terms"), status_code=303)
        if len(cl["idno"] or "") != 13:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "need_idno"), status_code=303)
        sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (cl["id"],)).fetchone()
        try:
            p, outcome = payments.choose(con, cl, tier or tiers.pick(sub), m, acc["email"])
        except ValueError as e:
            # клиника в открытой общей ноте кабинета (26.10) — своя нота не выставляется
            why = "in_group" if str(e) == payments.HELD else "tier_not_sold"
            return RedirectResponse(_cont_to(con, acc, cl["id"], why), status_code=303)
        if outcome != payments.EXISTS:
            box.add([(True, web.payment_letter(con, cl, p, acc["email"]))])
        if card:
            plan = payments.card_plan(con, p, cl, web.ip(request))
            back = _cont_to(con, acc, cl["id"])
        elif outcome == payments.EXISTS:
            back = _cont_to(con, acc, cl["id"], "note_exists")
        else:
            back = _cont_to(con, acc, cl["id"], "note_replaced" if outcome == payments.REPLACED else "note_created")
    if plan is not None:
        return web.card_go(plan, acc["email"], back)
    return RedirectResponse(back, status_code=303)


@router.get("/cont/plati/{number}.pdf")
def cont_receipt(request: Request, number: str) -> Response:
    """Cont de plată из кабинета — только документ СВОИХ клиник (своя нота или общая, где
    своя клиника строкой); чужой номер или неоплаченная нота — 404, без входа — на вход."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        own = {r["id"] for r in account.clinics(con, acc)}
        p = con.execute("SELECT * FROM payments WHERE reference=?", (number,)).fetchone()
        if p is not None and p["clinic_id"] not in own and (account.scoped(acc) or not any(
                ln["clinic_id"] in own for ln in payments.lines_of(con, p["id"]))):
            p = None                  # общая нота называет все клиники кабинета: кнопке программы — нет
        row = receipts.ensure(con, p, acc["email"]) if p is not None else None
    if row is None:
        return Response(status_code=404)
    return web.pdf(row)


# ---------- кабинет › SMS: пакеты и оплата нот SMS (05.11) ----------
#
# Слово Олега 05.11: «в админке клиники во вкладке SMS добавить и там эти пакеты» — покупка пакета
# из кабинета, вторая дверь рядом с программой (Setări › SMS, она остаётся). Логика заказа одна
# (web.sms_pack_note), путь денег — тот же, что у абонемента (payments, maib, receipts): своего
# провода нет. Остаток и пакет — у СВОЕЙ клиники (у филиала свои); имя отправителя — у главной.


@router.post("/cont/sms/nota")
def cont_sms_note(request: Request, pack: str = Form(""), ref: str = Form(""),
                  method: str = Form(payments.TRANSFER), terms: str = Form(""), c: str = "") -> Response:
    """Нота SMS из кабинета. `pack` — заказ пакета: нота (или уже открытая — у клиники она одна),
    письмо с ней; картой — сразу на страницу банка. `ref` — карта к ОЖИДАЮЩЕЙ ноте SMS этой
    клиники (пакет, год имени), как на странице оплаты. ⛔ Без галочки условий — нет (требование
    maib); цена — из прайса сервера, не из формы. Письмо с нотой — после commit, maib — вне
    транзакции (`web.card_go`)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    card = method == payments.CARD and maib.enabled()
    plan = None
    with payments.outbox() as box, db.connect(immediate=True) as con:
        acc, cl = _cont_clinic(request, con, c)
        if cl is None:
            return _cont_deny(acc)
        if terms != "1":
            return RedirectResponse(_cont_to(con, acc, cl["id"], "need_terms"), status_code=303)
        if ref:
            note = con.execute("SELECT * FROM payments WHERE reference=? AND clinic_id=? AND status=? AND kind IN (?,?)",
                               (ref, cl["id"], payments.PENDING, payments.SMS, payments.SMS_NAME)).fetchone()
            if note is None:
                return RedirectResponse(_cont_to(con, acc, cl["id"], "note_gone"), status_code=303)
            if not card:
                return RedirectResponse(_cont_to(con, acc, cl["id"], "no_card"), status_code=303)
            said = ""
        else:
            code, note, created = web.sms_pack_note(con, cl, web.months(pack), acc["email"], terms=True)
            if code:
                return RedirectResponse(_cont_to(con, acc, cl["id"], code), status_code=303)
            if created:
                # новая нота — письмом и при карте: не дойдёт клиника до оплаты — реквизиты у неё есть
                box.add([(True, web.sms_note_letter(con, cl, note, acc["email"]))])
            said = "sms_note_created" if created else "sms_note_exists"
        payments.mark_terms(con, note)
        if card:
            plan = payments.card_plan(con, note, cl, web.ip(request))
        back = _cont_to(con, acc, cl["id"], "" if card else said)
    if plan is not None:
        return web.card_go(plan, acc["email"], back, paid="sms_card_paid")
    return RedirectResponse(back, status_code=303)


# ---------- кабинет › SMS: имя отправителя и заявление (17.10, sms_paper.py) ----------
#
# Раздел виден, только когда пакет предложен клинике (sms.offered): клиника без
# пакета про SMS в кабинете не видит ничего, как и в программе.


def _cont_sms(request: Request, con):
    """(учётная запись, открытая клиника, хозяйка имени, её счёт SMS) кабинета; счёт None —
    пакет открытой клинике не предложен. Имя общее на кабинет (26.10): заявка, заявление и год —
    у главной клиники (sms.name_owner). Клиника — из адреса формы (?c=)."""
    acc, cl = _cont_clinic(request, con, request.query_params.get("c", ""))
    if cl is None:
        return acc, None, None, None
    sa = con.execute("SELECT * FROM sms_accounts WHERE clinic_id=?", (cl["id"],)).fetchone()
    if not sms.offered(sa):
        return acc, cl, cl, None
    if account.scoped(acc) and sms.name_owner(con, cl["id"]) != cl["id"]:
        return acc, cl, cl, None          # вход кнопкой программы филиала: имя кабинета не его (27.10)
    owner = web.clinic(con, sms.name_owner(con, cl["id"]))
    return acc, cl, owner, sms.ensure(con, owner["id"])


@router.post("/cont/sms/nume")
def cont_sms_name(request: Request, name: str = Form("")) -> Response:
    """Заявка на имя из кабинета — та же sms.request_sender, что у программы и
    админки (с отказом на чужое имя); имя — кабинета (главной клиники)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        acc, cl, owner, sa = _cont_sms(request, con)
        if cl is None:
            return _cont_deny(acc)
        if sa is None:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "sms_not_offered"), status_code=303)
        code = sms.request_sender(con, owner["id"], name, acc["email"])
        back = _cont_to(con, acc, cl["id"], code or "sms_requested")
    return RedirectResponse(back, status_code=303)


@router.post("/cont/sms/cerere.pdf")
def cont_sms_form(request: Request, rep: str = Form("")) -> Response:
    """Заявление на имя, уже заполненное (PDF): реквизиты клиники-хозяйки имени, имя заявки,
    представитель с формы. Без заявки или без реквизитов — назад с причиной."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        acc, cl, c, sa = _cont_sms(request, con)
        if cl is None:
            return _cont_deny(acc)
        if sa is None:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "sms_not_offered"), status_code=303)
        if sa["sender_state"] != sms.S_REQUESTED or not sa["sender"]:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "sms_paper_state"), status_code=303)
        if sms_paper.missing(c):
            return RedirectResponse(_cont_to(con, acc, cl["id"], "sms_paper_data"), status_code=303)
        who = sms_paper.clean_rep(rep)
        if not who:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "sms_paper_rep"), status_code=303)
        body = sms_paper.render(c, sa["sender"], who)
    return Response(body, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{sms_paper.filename(sa["sender"])}"'})


def _cont_known(request: Request) -> bool:
    """Вошла ли клиника в кабинет и назвала ли форма свою клинику (только чтение)."""
    with db.connect() as con:
        return _cont_clinic(request, con, request.query_params.get("c", ""))[1] is not None


def _cont_paper_back(request: Request, code: str) -> str:
    with db.connect() as con:
        acc, cl = _cont_clinic(request, con, request.query_params.get("c", ""))
        return _cont_to(con, acc, cl["id"], code) if cl is not None else "/cont/login"


def _cont_paper_save(request: Request, body: bytes, name: str) -> str:
    with db.connect(immediate=True) as con:
        acc, cl, owner, sa = _cont_sms(request, con)
        if cl is None:
            return "login"
        if sa is None:
            return "sms_not_offered"
        return sms_paper.attach(con, owner["id"], body, name, acc["email"]) or "sms_paper_ok"


@router.post("/cont/sms/cerere")
async def cont_sms_upload(request: Request) -> Response:
    """Подписанное заявление (PDF) в базу; ставит «Заявление получено».
    ⛔ Тело читается здесь, с потолком, а не штатным разбором формы: тот кладёт
    файл на диск целиком, и потолок после него ничего не сберёг бы. Лишнее сверх
    потолка дочитывается вхолостую (до DRAIN), чтобы браузер получил ответ «файл
    велик», а не обрыв: ранний ответ при непрочитанном теле Windows рвёт RST."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    # вход — ДО чтения тела: без него аноним заставлял бы сервер читать до 32 МБ
    if not await run_in_threadpool(_cont_known, request):
        return _cont_login_redirect()

    async def back(code: str) -> Response:
        return RedirectResponse(await run_in_threadpool(_cont_paper_back, request, code), status_code=303)
    limit, drain = sms_paper.MAX_BYTES + 64 * 1024, 32 * 1024 * 1024
    try:
        declared = int(request.headers.get("content-length") or "0")
    except ValueError:
        declared = 0
    if declared > drain:
        return await back("sms_paper_big")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > drain:
            break
        if size <= limit:
            chunks.append(chunk)
    if size > limit:
        return await back("sms_paper_big")
    raw = b"".join(chunks)

    async def replay() -> dict:
        return {"type": "http.request", "body": raw, "more_body": False}

    try:
        form = await Request(request.scope, replay).form(max_files=1, max_fields=4)
    except Exception:                         # кривой multipart: тот же ответ, что пустой файл
        return await back("sms_paper_empty")
    up = form.get("file")
    if up is None or not hasattr(up, "read"):
        return await back("sms_paper_empty")
    body = await up.read(sms_paper.MAX_BYTES + 1)
    code = await run_in_threadpool(_cont_paper_save, request, body, getattr(up, "filename", "") or "")
    if code == "login":
        return _cont_login_redirect()
    return await back(code)


# ---------- кабинет › документы (29.10, contracts.py): подписанные поставщиком PDF, экземпляр клиники ----------
#
# Документы поставщика общие: нужен только вход; экземпляр клиники — только СВОИХ клиник (как cont de
# plată). Сессии кнопки программы (contlink) раздел открыт в пределах её клиники.


async def _read_upload(request: Request, limit: int) -> tuple[str, bytes, dict]:
    """Файл формы multipart с потолком — тем же приёмом, что cont_sms_upload: тело читает сам маршрут,
    лишнее сверх потолка дочитывается вхолостую (до DRAIN), чтобы браузер получил ответ, а не RST.
    → ('', байты файла, остальные поля формы) или ('big' | 'empty', b'', {})."""
    drain = 32 * 1024 * 1024
    try:
        declared = int(request.headers.get("content-length") or "0")
    except ValueError:
        declared = 0
    if declared > drain:
        return "big", b"", {}
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > drain:
            break
        if size <= limit + 64 * 1024:
            chunks.append(chunk)
    if size > limit + 64 * 1024:
        return "big", b"", {}
    raw = b"".join(chunks)

    async def replay() -> dict:
        return {"type": "http.request", "body": raw, "more_body": False}

    try:
        form = await Request(request.scope, replay).form(max_files=1, max_fields=8)
    except Exception:                         # кривой multipart: тот же ответ, что пустой файл
        return "empty", b"", {}
    up = form.get("file")
    if up is None or not hasattr(up, "read"):
        return "empty", b"", {}
    body = await up.read(limit + 1)
    return "", body, {k: v for k, v in form.multi_items() if isinstance(v, str)}


def _cont_docs_back(request: Request, code: str) -> str:
    c = request.query_params.get("c", "")
    return f"/cont/documente?msg={code}" + (f"&c={c}" if c else "")


@router.get("/cont/documente", response_class=HTMLResponse)
def cont_documents(request: Request, msg: str = "", c: str = "") -> Response:
    """Раздел «Documente» — кабинет, открытый на этой вкладке (29.10): адрес живёт в письмах и в акте."""
    return _cont_dashboard(request, msg, c, tab="documente")


@router.get("/cont/documente/{doc}.pdf")
def cont_document_pdf(request: Request, doc: str) -> Response:
    """Подписанный поставщиком PDF — в окно браузера; документ общий, нужен только вход в кабинет."""
    with db.connect() as con:
        if _current_account(con, request) is None:
            return _cont_login_redirect()
    data = contracts.provider_pdf(doc) if doc in contracts.DOCS else None
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{contracts.filename(doc)}"'})


@router.get("/cont/modele/{key}", response_class=HTMLResponse)
def cont_model(request: Request, key: str, c: str = "") -> Response:
    """Образец закона 195 с реквизитами клиники (31.10, modele.py) — страницей, для печати. Только своя
    клиника (`?c=` филиала; чужая или неизвестная — на кабинет, без данных); неизвестный образец — 404.
    `no-store`: в странице реквизиты клиники."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        cl = account.pick(con, acc, c)
        if cl is None:
            return RedirectResponse("/cont", status_code=303)
        sa = con.execute("SELECT * FROM sms_accounts WHERE clinic_id=?", (cl["id"],)).fetchone()
    page = modele.render(key, cl, modele.sms_on(sa))
    if page is None:
        return Response(status_code=404)
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/cont/documente/{rid}/clinica.pdf")
def cont_document_mine(request: Request, rid: int) -> Response:
    """Экземпляр клиники — только своих клиник; чужой или без файла — 404, без входа — на вход."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        own = {r["id"] for r in account.clinics(con, acc)}
        r = contracts.get(con, rid)
        if r is None or r["clinic_id"] not in own:
            return Response(status_code=404)
        cl = web.clinic(con, r["clinic_id"])
    data = contracts.read_file(r)
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{contracts.clinic_filename(cl, r)}"',
                             "X-Content-Type-Options": "nosniff"})


def _cont_docs_save(request: Request, doc: str, body: bytes) -> str:
    with db.connect(immediate=True) as con:
        acc, cl = _cont_clinic(request, con, request.query_params.get("c", ""))
        if acc is None:
            return "login"
        if cl is None:
            return "pick_clinic"
        return contracts.attach(con, cl["id"], doc, body, acc["email"]) or "doc_ok"


@router.post("/cont/documente/incarca")
async def cont_document_upload(request: Request) -> Response:
    """Экземпляр, подписанный клиникой (PDF) → файл и строка. Вход — ДО чтения тела (как у заявления SMS)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if not await run_in_threadpool(_cont_known, request):
        return _cont_login_redirect()
    kind, body, fields = await _read_upload(request, contracts.MAX_BYTES)
    if kind:
        code = "doc_" + kind
    else:
        code = await run_in_threadpool(_cont_docs_save, request, fields.get("doc", ""), body)
    if code == "login":
        return _cont_login_redirect()
    if code == "pick_clinic":
        return RedirectResponse("/cont?msg=pick_clinic", status_code=303)
    return RedirectResponse(await run_in_threadpool(_cont_docs_back, request, code), status_code=303)


# ---------- кабинет › клиники кабинета (26.10): «Adaugă clinică», код компьютера, общая нота ----------
#
# Филиал = ещё одна клиника в том же кабинете (Олег 26.10, cabinet.py): своя лицензия, пробный,
# подписка и база; общие — вход, общая нота и имя отправителя SMS.


@router.get("/cont/clinica-noua", response_class=HTMLResponse)
def cont_add_form(request: Request, c: str = "", msg: str = "") -> Response:
    with db.connect() as con:
        acc, cl = _cont_clinic(request, con, c, post=False)
        if acc is None:
            return _cont_login_redirect()
        if cl is None:
            return RedirectResponse("/cont/inregistrare" if not account.clinics(con, acc) else "/cont",
                                    status_code=303)
        msg = msg or _add_unpaid(con, cl)      # сразу на форме: не заполнять её зря
    return HTMLResponse(views.cont_add_page(acc, cl, msg))


@router.post("/cont/clinica-noua", response_class=HTMLResponse)
def cont_add_submit(request: Request, c: str = "", name: str = Form(""), address: str = Form(""),
                    phone: str = Form(""), contact_name: str = Form(""), email: str = Form(""),
                    idno: str = Form(""), consent: str = Form(""), tier: str = Form(""),
                    months: str = Form("")) -> Response:
    """Ещё одна клиника кабинета теми же правилами и лимитом, что регистрация, но без пробного и
    без одобрения Олега (Олег 27.10, trial.NO_TRIAL): сразу на абонементе выбранного варианта и
    срока — нота за первый период и файл на срок её оплаты (account.start_paid); нота — письмом
    на ящик новой клиники. Тот же IDNO и ящик разрешены внутри кабинета, чужой клинике —
    «add_duplicate» и письмо Олегу. Ответ — страница с кодом компьютера новой клиники (виден один
    раз; программа активируется им и сразу получает файл), вход в неё — у всех записей кабинета;
    она же открыта."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        acc, cl = _cont_clinic(request, con, c)
    if cl is None:
        return _cont_deny(acc)
    ip = web.ip(request)
    f, code = account.clean_new({"name": name, "address": address, "phone": phone, "contact_name": contact_name,
                                 "email": email, "idno": idno, "consent": consent})
    f.update(tier=tier, months=months)          # выбор возвращается в форму вместе с полями
    if code:
        return HTMLResponse(views.cont_add_page(acc, cl, code, f), status_code=400)
    if months not in ("1", "12") or tiers.list_price(tier) <= 0:
        return HTMLResponse(views.cont_add_page(acc, cl, "tier_not_sold" if tiers.list_price(tier) <= 0 else "bad_months",
                                                f), status_code=400)
    with db.connect() as con:
        if (late := _add_unpaid(con, cl)):
            return HTMLResponse(views.cont_add_page(acc, cl, late, f), status_code=409)
    if trial.limited(ip):
        return HTMLResponse(views.cont_add_page(acc, cl, "limited", f), status_code=429)
    trial.note(ip)
    act = until = ""
    main = nota = None
    with db.connect(immediate=True) as con:
        if len(account.clinics(con, acc)) >= account.CLINICS_MAX:
            return HTMLResponse(views.cont_add_page(acc, cl, "clinics_max", f), status_code=409)
        outcome, new = account.add_clinic(con, cl, f, ip, acc["email"], tier, int(months))
        if outcome != trial.DUPLICATE:
            con.execute("UPDATE accounts SET clinic_id=? WHERE id=?", (new["id"], acc["id"]))
            act, until = account.new_code(con, new, acc["email"])
            main = cabinet.main_of(con, new["id"])
            nota = payments.debt_of(con, new["id"])
            if outcome == trial.ADDED:
                _send_added_letter(con, new, nota, acc["email"])
    trial.notify(new, outcome, ip, dict(f, cabinet=f"{cl['name']} ({cl['id']})",
                                        nota=f"{nota['reference']}, {nota['amount']} MDL" if nota else ""),
                 trial.ORIGIN_CONT_ADD)
    if outcome == trial.DUPLICATE:
        return HTMLResponse(views.cont_add_page(acc, cl, "add_duplicate", f), status_code=409)
    return HTMLResponse(views.cont_activation_page(acc, new, act, until, main, download.latest(),
                                                   "clinic_added" if outcome == trial.ADDED else "clinic_added_wait"))


def _add_unpaid(con, cl) -> str:
    """Текст отказа «Adaugă clinică», пока у клиники кабинета просрочена первая нота
    (account.overdue_first), или ''. Заявкой не считается: лимит заявок не тратит."""
    late = account.overdue_first(con, cl["id"])
    if late is None:
        return ""
    clinic, nota = late
    return views.cont_text("add_unpaid").format(name=clinic["name"], ref=nota["reference"] if nota else "—")


def _send_added_letter(con, c, p, who: str) -> None:
    """Клинике из «Adaugă clinică» — одно письмо: включена, срок на оплату, нота первого периода с
    реквизитами. Ушло — напоминание «нота» за этот срок задача уже не шлёт (jobs.INVOICE: у срока
    на оплату его окно открыто с первого дня); не ушло — пришлёт задача. Ящик не подтверждён (не
    совпал со входом кабинета, emailconf.on_new_clinic) — в том же письме «Confirmă adresa» и
    код, как в письме о лицензии (license.mail_latest): одно письмо, не два."""
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (c["id"],)).fetchone()
    if p is None or sub is None or not c["email"]:
        return
    page = paylink.for_mail(con, c, who)
    valid = db.parse_ts(sub["valid_until"])
    try:
        subject, body = mail.clinic_added_letter(c["name"], valid, valid + timedelta(days=int(sub["grace_days"])),
                                                 p["reference"], p["amount"], p["months"], p["tier"],
                                                 pay_url=page if maib.enabled() else None, page=page)
        confirm = emailconf.for_letter(con, c, who)
        if confirm:
            body = mail.with_confirm(body, *confirm, emailconf.LINK_TTL.days)
        where = mail.send(c["email"], subject, body)
    except (RuntimeError, OSError, ValueError) as e:
        log.error("письмо новой клинике кабинета %s не отправлено: %r", c["id"], e)
        return
    con.execute("INSERT OR IGNORE INTO reminders(subscription_id, kind, period, sent_at) VALUES(?,?,?,?)",
                (c["id"], jobs.INVOICE, sub["valid_until"], db.now_iso()))
    db.audit(con, who, "mail", c["id"], f"клиника добавлена, нота {p['reference']} на {c['email']} ({where})")


@router.post("/cont/cod", response_class=HTMLResponse)
def cont_code_new(request: Request, c: str = "") -> Response:
    """Код компьютера клиники кабинета (7 цифр, 7 дней, один раз): прежний неиспользованный
    гаснет. Страница с кодом — ответ формы, код виден один раз."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        acc, cl = _cont_clinic(request, con, c)
        if cl is None:
            return _cont_deny(acc)
        if cl["declined_at"]:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "closed"), status_code=303)
        code, until = account.new_code(con, cl, acc["email"])
        if not code:
            return RedirectResponse(_cont_to(con, acc, cl["id"], "code_limit"), status_code=303)
        main = cabinet.main_of(con, cl["id"])
    return HTMLResponse(views.cont_activation_page(acc, cl, code, until, main, download.latest()))


def _group_state(con, acc):
    """(клиники записи для выбора, открытая общая нота, её строки)."""
    mine = [r for r in account.clinics(con, acc) if r["declined_at"] is None]
    rows = [(r, con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (r["id"],)).fetchone(), None)
            for r in mine]
    pending = next((g for g in (payments.group_of(con, r["id"]) for r in mine) if g is not None), None)
    return rows, pending, (payments.lines_of(con, pending["id"]) if pending is not None else [])


@router.get("/cont/nota-comuna", response_class=HTMLResponse)
def cont_group(request: Request, msg: str = "") -> Response:
    """Общая нота на клиники кабинета (Олег 26.10: «Нужен и общий счёт на все клиники кабинета»)."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        if not account.clinics(con, acc):
            return RedirectResponse("/cont/inregistrare", status_code=303)
        rows, pending, lines = _group_state(con, acc)
    return HTMLResponse(views.cont_group_page(acc, rows, pending, lines, msg, card_on=maib.enabled()))


def _group_submit(request: Request, form: dict, ip: str) -> Response:
    back = "/cont/nota-comuna"
    card = form.get("method") == payments.CARD and maib.enabled()
    plan = None
    with payments.outbox() as box, db.connect(immediate=True) as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        rows, pending, _ = _group_state(con, acc)
        if form.get("terms") != "1":
            return RedirectResponse(f"{back}?msg=need_terms", status_code=303)
        ref = form.get("ref") or ""
        if ref:
            # карта к открытой общей ноте — за галочкой условий, ссылка maib по клику
            if pending is None or pending["reference"] != ref:
                return RedirectResponse(f"{back}?msg=group_gone", status_code=303)
            if not card:
                return RedirectResponse(f"{back}?msg=no_card", status_code=303)
            plan = payments.card_plan(con, pending, web.clinic(con, pending["clinic_id"]), ip)
        else:
            picks = []
            for r, _, _ in rows:
                t = form.get(f"t_{r['id']}") or ""
                if t:
                    picks.append((r, t, web.months(form.get(f"m_{r['id']}") or "1")))
            if not picks:
                return RedirectResponse(f"{back}?msg=group_empty", status_code=303)
            payer = picks[0][0]
            if len(payer["idno"] or "") != 13:
                return RedirectResponse(f"{back}?msg=need_idno_payer", status_code=303)
            try:
                p, replaced = payments.create_group(con, payer, picks, acc["email"])
            except ValueError as e:
                why = {"too_many": "group_too_many", "months": "bad_months"}.get(str(e), "tier_not_sold")
                return RedirectResponse(f"{back}?msg={why}", status_code=303)
            box.add([(True, web.payment_letter(con, payer, p, acc["email"]))])
            if card:
                plan = payments.card_plan(con, p, payer, ip)
    if plan is not None:
        return web.card_go(plan, acc["email"], back, gone="group_gone")
    return RedirectResponse(f"{back}?msg={'group_replaced' if replaced else 'group_created'}", status_code=303)


@router.post("/cont/nota-comuna")
async def cont_group_submit(request: Request) -> Response:
    """Общая нота: у каждой клиники вариант (`t_<id>`, пусто — не входит) и срок (`m_<id>`),
    одна галочка условий; заменяет открытые ноты своих клиник и прежнюю общую (payments.
    create_group); переводом — нота здесь и письмом плательщику, картой — сразу к maib. `ref` —
    карта к открытой общей ноте."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    form = await request.form(max_fields=2 * (account.CLINICS_MAX + 4))
    data = {k: str(v) for k, v in form.items() if isinstance(v, str)}
    return await run_in_threadpool(_group_submit, request, data, web.ip(request))


@router.post("/cont/nota-comuna/anuleaza")
def cont_group_cancel(request: Request, ref: str = Form("")) -> Response:
    """Отменить открытую общую ноту: клиники свободны — своя нота или новая общая. Деньги,
    пришедшие по отменённой, не теряются (зачёт повторного платежа)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        _, pending, _ = _group_state(con, acc)
        if pending is None or pending["reference"] != ref:
            return RedirectResponse("/cont/nota-comuna?msg=group_gone", status_code=303)
        payments.reject(con, pending, "отменена в кабинете", acc["email"])
    return RedirectResponse("/cont/nota-comuna?msg=group_cancelled", status_code=303)


@router.get("/cont/acceptari", response_class=HTMLResponse)     # = terms.PAGE; литерал — его читает test_contlink.ROUTES
def cont_terms_list(request: Request, msg: str = "", c: str = "") -> Response:
    """Кабинет: акты акцепта открытой клиники (`?c=` — какой). Сессии кнопки программы — своя."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        cl = account.pick(con, acc, c)
        if cl is None:
            return RedirectResponse("/cont", status_code=303)
        multi = len(account.clinics(con, acc)) > 1
        return HTMLResponse(terms.cont_list_page(acc, cl, con, msg, multi=multi))


@router.get("/cont/acceptari/{aid}", response_class=HTMLResponse)
def cont_terms_act(request: Request, aid: str, c: str = "") -> Response:
    """Печатная страница акта — только СВОЕЙ клиники: чужой id — 404 словами, без разницы с несуществующим."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        cl = account.pick(con, acc, c)
        if cl is None:
            return RedirectResponse("/cont", status_code=303)
        row = terms.get(con, cl["id"], aid)
        if row is None:
            return HTMLResponse(views._cont_shell("Actul nu există", "<div class='card'><p>Actul cerut nu există "
                                                  "sau nu aparține acestei clinici.</p></div>", acc,
                                                  lead=f"<a href='{terms.PAGE}'>Toate actele</a>"), status_code=404)
        multi = len(account.clinics(con, acc)) > 1
        return HTMLResponse(terms.cont_act_page(acc, cl, row, multi=multi))
