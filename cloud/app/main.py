"""DentPilot Cloud — сервер лицензий (docs/dentpilot-2/cloud.md, шаг 1).

Отдельная программа: ни одного импорта из bot/. Общее с движком — контракт
файла лицензии и фикстуры tests/fixtures/license/. Здесь: вход администратора,
клиники, выдача файла, письмо с файлом (L7), платежи переводом (L8),
ежедневная задача с напоминаниями и журнал (L9), оплата картой через maib —
ссылка, callback, проверка статуса (L12), ответ программе клиники на её
суточный запрос нового файла (L13, /v1/license), публичная форма пробного
периода /proba и заявки с неё в админке (L14), кабинет клиники со входом
через Google и ссылка на скачивание программы (шаг 3, 01.10: /cont, /descarca).
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import (account, auth, cabinet, config, db, download, fleet, jobs, license, logmask, maib, mail, payments, paylink,
               receipts, robots, sms, sms_paper, sms_rule, smsmd, smsreport, tiers, trial, updates, views)
from . import login as elogin  # ⚠️ не `login`: так зовётся маршрут входа админки ниже, он затенил бы модуль

APP_VERSION = "0.1.0"
log = logging.getLogger("cloud")
# секрет уведомлений sms.md стоит в пути запроса — журнал доступа его не видит (logmask.py)
logmask.install()
app = FastAPI(title="DentPilot Cloud", docs_url=None, redoc_url=None)
# каждый ответ облака — мимо поисковой выдачи; почему заголовком, а не robots.txt, — robots.py
app.add_middleware(robots.NoIndex)

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
    if not smsmd.enabled():
        log.warning("DP_SMSMD_TOKEN пуст: SMS-пакет выключен, программы получают sms_unconfigured")


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "version": APP_VERSION})


@app.get("/robots.txt")
def robots_txt() -> Response:
    """Обход открыт намеренно: запрет индексации едет заголовком с каждым ответом,
    и поисковик обязан до него дойти (robots.py). Без этого маршрута — 404 JSON."""
    return Response(robots.TXT, media_type="text/plain; charset=utf-8")


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
        fleet.touch(con, c["id"], fleet.from_request(request), max(0, seq))   # флот (02.10)
        if row is None or row["seq"] <= seq:
            return Response(status_code=204)
        db.audit(con, "program", "renew", c["id"], f"файл {row['seq']} забран программой (у неё был {seq})")
    return Response(license.issue_text(row), media_type="application/json")


@app.get(updates.API_PATH)
def update_api(channel: str = "stable", current: str = "") -> Response:
    """Сервер обновлений (03.10): какая версия свежая для канала программы.
    200 — выпуск новее `current` (версия, страница, файлы со ссылкой, размером и
    sha256); 204 — новее нет; 503 — сервер сам не знает, программа идёт к GitHub.
    Без входа и без токена: выпуски публичны, а программа проверяет ответ сама."""
    status, body = updates.answer(channel, current)
    if body is None:
        return Response(status_code=status)
    return JSONResponse(body, status_code=status)


@app.post(paylink.API_PATH)
def pay_link_api(request: Request) -> Response:
    """Программа просит ссылку оплаты (02.10): тот же Bearer, что у /v1/license.
    Ответ — адрес страницы /plata/<id> (сутки); повтор в пределах суток — та же."""
    token = _bearer(request)
    if not token:
        return JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    with db.connect(immediate=True) as con:
        c = con.execute("SELECT * FROM clinics WHERE renew_token=? AND renew_token<>''",
                        (token,)).fetchone()
        if c is None:
            return JSONResponse({"ok": False, "code": "token_unknown"}, status_code=401)
        fleet.touch(con, c["id"], fleet.from_request(request))          # флот: компьютер вышел на связь
        link = paylink.create(con, c, "program")
    return JSONResponse({"ok": True, "url": paylink.url_for(link["id"]), "expires_at": link["expires_at"]})


# ---------- SMS-пакет (S3): программа → сервер → sms.md (docs/dentpilot-2/sms.md › «Сервер») ----------
#
# Bearer — токен клиники, тот же, что у /v1/license; имя отправителя сервер берёт
# из записи клиники, в запросе его нет. Номер и текст живут в памяти запроса:
# ни одна строка ниже не пишет их в лог или базу.

SMS_BODY_MAX = 8 * 1024


def _sms_clinic(request: Request):
    """(клиника, None) по токену программы или (None, ответ 401)."""
    token = _bearer(request)
    if not token:
        return None, JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    with db.connect() as con:
        c = con.execute("SELECT * FROM clinics WHERE renew_token=? AND renew_token<>''", (token,)).fetchone()
        if c is None:
            return None, JSONResponse({"ok": False, "code": "token_unknown"}, status_code=401)
        fleet.touch(con, c["id"], fleet.from_request(request))
    return c, None


async def _sms_body(request: Request) -> dict | None:
    try:
        body = json.loads((await request.body())[:SMS_BODY_MAX] or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _sms_answer(code: str, **extra) -> Response:
    status, data = sms.answer(code, **extra)
    return JSONResponse(data, status_code=status)


def _sms_view(cid: str) -> dict:
    with db.connect(immediate=True) as con:
        return sms.view(con, cid)


@app.get("/v1/sms/account")
async def sms_account(request: Request) -> Response:
    """Что программа показывает в Setări › SMS: включено, имя и его состояние,
    от какого имени уходят SMS, остаток, пакеты, потолок, почему нельзя сейчас."""
    c, deny = await run_in_threadpool(_sms_clinic, request)
    if deny is not None:
        return deny
    return JSONResponse(await run_in_threadpool(_sms_view, c["id"]))


@app.post("/v1/sms/send")
async def sms_send(request: Request) -> Response:
    """{to, text, kind, idem} → 200 {id, segments, state, balance} или код отказа
    (sms.CODES). Повтор с тем же idem — тот же ответ, без второй SMS и списания."""
    c, deny = await run_in_threadpool(_sms_clinic, request)
    if deny is not None:
        return deny
    body = await _sms_body(request)
    if body is None:
        return _sms_answer("bad_json")
    status, data = await run_in_threadpool(sms.submit, c["id"], body.get("to"), body.get("text"),
                                           body.get("kind"), body.get("idem"))
    return JSONResponse(data, status_code=status)


def _sms_states(cid: str, ids) -> list:
    with db.connect() as con:
        return sms.states(con, cid, ids)


@app.post("/v1/sms/status")
async def sms_status(request: Request) -> Response:
    """{ids: […]} → {items: [{id, state, error}]} — только свои сообщения."""
    c, deny = await run_in_threadpool(_sms_clinic, request)
    if deny is not None:
        return deny
    body = await _sms_body(request)
    if body is None:
        return _sms_answer("bad_json")
    return JSONResponse({"ok": True, "items": await run_in_threadpool(_sms_states, c["id"], body.get("ids"))})


def _sms_sender(cid: str, name) -> Response:
    with db.connect(immediate=True) as con:
        code = sms.request_sender(con, cid, name if isinstance(name, str) else "", "program")
        if code:
            return _sms_answer(code)
        return JSONResponse(sms.view(con, cid))


@app.post("/v1/sms/sender")
async def sms_sender(request: Request) -> Response:
    """{name} → заявка на имя отправителя (requested); подача в sms.md — руками Олега."""
    c, deny = await run_in_threadpool(_sms_clinic, request)
    if deny is not None:
        return deny
    body = await _sms_body(request)
    if body is None:
        return _sms_answer("bad_json")
    return await run_in_threadpool(_sms_sender, c["id"], body.get("name"))


def _sms_order(c, body: dict, ip: str) -> Response:
    """Нота из программы: {pack: N} — пополнение (kind=sms), {name: 1} — год своего
    имени (kind=sms_name). Одна открытая нота каждого вида на клинику; карта — при
    настроенном maib; письмо с нотой — на e-mail клиники. Цены — из cloud.env."""
    name = bool(body.get("name"))
    if name:
        if not config.SMS_NAME_PRICE:
            return _sms_answer("sms_no_name")
        units, amount = None, config.SMS_NAME_PRICE
    else:
        if not config.SMS_PACKS:
            return _sms_answer("sms_no_packs")
        try:
            units = int(body.get("pack"))
        except (TypeError, ValueError):
            units = 0
        if units not in config.SMS_PACKS:
            return _sms_answer("sms_pack", packs=sms.packs())
        amount = config.SMS_PACKS[units]
    if len(c["idno"] or "") != 13:
        return _sms_answer("sms_need_idno")
    kind = payments.SMS_NAME if name else payments.SMS
    with db.connect(immediate=True) as con:
        # выключенной клинике, без права по плану и на Basic (модуль погашен) не продаётся;
        # без имени пополнение продаётся
        acc = sms.ensure(con, c["id"])
        why = sms.blocked(con, c["id"], acc, datetime.now(timezone.utc))
        if why in ("sms_unconfigured", "sms_not_offered", "sms_off", "sms_plan", "sms_basic"):
            return _sms_answer(why)
        if name:
            # имя общее на кабинет (26.10): нота за год имени — главной клинике, на её ящик
            c = _clinic(con, sms.name_owner(con, c["id"]))
            acc = sms.ensure(con, c["id"])
        if name and acc["sender_state"] not in (sms.S_REQUESTED, sms.S_SUBMITTED, sms.S_ACTIVE):
            return _sms_answer("sms_name_none")
        p = payments.open_of(con, c["id"], kind)
        created = p is None
        if created:
            p = (payments.create_name(con, c, amount, "program") if name
                 else payments.create_pack(con, c, units, amount, "program"))
        # Карта — на нашей странице оплаты, кнопкой после галочки условий (23.10): ссылка maib
        # живёт 10 минут и рождается по клику (payments.card_link), поэтому ни программе, ни
        # письму её не даём. Программа (2.0.9) показывает `pay_url` ссылкой «Plătește cu cardul».
        page = paylink.for_mail(con, c, "program") if maib.enabled() else None
        if created and c["email"]:
            try:
                if name:
                    subject, text = mail.sms_name_note_letter(c["name"], p["reference"], int(p["amount"]),
                                                              acc["sender"], page)
                else:
                    subject, text = mail.sms_pack_note_letter(c["name"], p["reference"], int(p["amount"]),
                                                              int(p["sms_units"]), page)
                where = mail.send(c["email"], subject, text)
                db.audit(con, "program", "mail", c["id"], f"нота {kind} {p['reference']} на {c['email']} ({where})")
            except (RuntimeError, OSError) as e:
                log.error("письмо с нотой SMS %s не отправлено: %r", p["reference"], e)
    return JSONResponse({"ok": True, "kind": kind, "reference": p["reference"], "amount": int(p["amount"]),
                         "units": p["sms_units"], "pay_url": page, "created": created})


@app.post("/v1/sms/order")
async def sms_order(request: Request) -> Response:
    c, deny = await run_in_threadpool(_sms_clinic, request)
    if deny is not None:
        return deny
    body = await _sms_body(request)
    if body is None:
        return _sms_answer("bad_json")
    return await run_in_threadpool(_sms_order, c, body, _ip(request))


@app.post("/v1/smsmd/dlr/{secret}")
async def smsmd_dlr(request: Request, secret: str, tasks: BackgroundTasks) -> Response:
    """Уведомление sms.md о доставке — сигнал, не истина: 200 сразу (их повтор на
    4xx/5xx не приходит), состояние перепроверяется запросом после ответа
    (sms.recheck; дубли безвредны). Чужой или пустой секрет — 404. Тело не
    логируется: в нём пока есть phone и text."""
    if not config.SMSMD_DLR_SECRET or not secrets.compare_digest(secret, config.SMSMD_DLR_SECRET):
        return Response(status_code=404)
    parsed = smsmd.dlr((await request.body())[:SMS_BODY_MAX])
    if parsed is not None:
        tasks.add_task(sms.recheck, parsed[0], parsed[1])
    return JSONResponse({"ok": True})


@app.get(paylink.PATH + "/{pid}", response_class=HTMLResponse)
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


def _months(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        return 0


@app.post(paylink.PATH + "/{pid}", response_class=HTMLResponse)
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
    Карта — `payments.card_link`: ссылка maib рождается по клику (живёт 10 минут)."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = _ip(request)
    back = f"{paylink.PATH}/{pid}"
    if paylink.limited(ip):
        return RedirectResponse(f"{back}?msg=limited", status_code=303)
    m = _months(months)
    idno = "".join(idno.split())
    card = method == payments.CARD and maib.enabled()
    with db.connect(immediate=True) as con:
        c = paylink.lookup(con, pid)
        if c is None:
            return HTMLResponse(views.pay_link_expired_page(), status_code=410)
        if m not in payments.MONTHS:
            return RedirectResponse(f"{back}?msg=bad_months", status_code=303)
        if terms != "1":
            return RedirectResponse(f"{back}?msg=need_terms", status_code=303)
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
            return _card_go(con, note, c, "program", ip, back)
        if idno and idno != (c["idno"] or ""):
            if not trial.IDNO_RE.match(idno):
                return RedirectResponse(f"{back}?msg=bad_idno", status_code=303)
            if account.idno_taken(con, idno, c["id"]):
                return RedirectResponse(f"{back}?msg=idno_taken", status_code=303)
            con.execute("UPDATE clinics SET idno=? WHERE id=?", (idno, c["id"]))
            db.audit(con, "program", "clinic_edit", c["id"], f"IDNO {idno} (pagina de plată)")
            c = _clinic(con, c["id"])
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
            _send_payment_letter(con, c, p, "program")
        if card:
            return _card_go(con, p, c, "program", ip, back)
    code = {payments.CREATED: "note_created", payments.REPLACED: "note_replaced"}.get(outcome, "note_exists")
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


def _card_go(con, p, c, who: str, ip: str, back: str) -> Response:
    """Клик «Plătește cu cardul» → браузер на страницу maib (ссылка по клику, payments.card_link)
    или назад с card_paid, если maib уже сказал «оплачено» (тогда и письмо об оплате)."""
    try:
        outcome, url = payments.card_link(con, p, c, who, ip)
    except maib.MaibError as e:
        log.warning("ссылка maib для %s не создана: %s", p["reference"], e)
        return RedirectResponse(f"{back}{'&' if '?' in back else '?'}msg=maib_failed", status_code=303)
    sep = "&" if "?" in back else "?"
    if outcome == payments.SETTLED_PAID:
        payments.notify_paid(con, p, who)
        return RedirectResponse(f"{back}{sep}msg=card_paid", status_code=303)
    return RedirectResponse(url, status_code=303)


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


# происхождения заявок — из trial.ORIGINS, а не перечислением: «Adaugă clinică» (cont_add, 26.10) иначе
# не попала бы в очередь, а её пробный ждёт Олега всегда (trial.APPROVE_ALWAYS)
_REQUESTS_SQL = (f"SELECT c.* FROM clinics c WHERE c.origin IN ({', '.join(repr(o) for o in trial.ORIGINS)}) "
                 "AND c.declined_at IS NULL AND NOT EXISTS (SELECT 1 FROM issues i WHERE i.clinic_id = c.id) "
                 "ORDER BY c.requested_at DESC")


@app.get("/admin", response_class=HTMLResponse)
def clinics(request: Request, msg: str = "", state: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_CLINICS_SQL).fetchall()
        requests = con.execute(_REQUESTS_SQL).fetchall()
        pending, names = _pending_count(con), _names_count(con)
    return HTMLResponse(views.clinics_page(rows, auth.current_user(request), msg, requests=requests, state=state,
                                           pending=pending, names=names))


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


# ---------- заявка на пробный из программы (26.09): активация без файла ----------

TRIAL_BODY_MAX = 16 * 1024       # заявка — полкилобайта; чужой мегабайт до разбора не доходит


def _api_err(code: str, status: int) -> Response:
    """Отказ программе: код и румынский текст — программа показывает его как есть."""
    return JSONResponse({"ok": False, "code": code, "text": views.TRIAL_MSG.get(code, code)},
                        status_code=status)


def _trial_program(f: dict, ip: str, ident: dict | None = None) -> tuple[str, str, str]:
    """Заявка из программы → (исход, токен или '', verify_id или ''). В потоке: база
    и письма блокируют. На повтор — код на e-mail, который у клиники уже записан.
    `ident` — личность машины из заголовков (флот): компьютер привязывается к
    новой клинике сразу, при повторе — только после кода (чужой IDNO в заявке
    не должен приписать чужой компьютер клинике)."""
    vid = code = ""
    with db.connect(immediate=True) as con:
        outcome, clinic = trial.submit(con, f, ip, who="program", origin=trial.ORIGIN_PROGRAM)
        token = ""
        if outcome == trial.DUPLICATE:
            vid, code = trial.new_code(con, clinic, ip)
        else:
            # ⚠️ Строка клиники — ЗАНОВО: в режиме auto submit уже выдал файл, и токен
            # родился внутри выдачи. По старой строке renew_token завёл бы второй и
            # переписал первый — файл в руках программы перестал бы узнаваться (401).
            fresh = con.execute("SELECT * FROM clinics WHERE id=?", (clinic["id"],)).fetchone()
            token = license.renew_token(con, fresh)
            fleet.touch(con, clinic["id"], ident)
    if vid:
        subject, body = mail.activation_code(clinic["name"], code,
                                             int(trial.CODE_TTL.total_seconds() // 60))
        try:
            mail.send(clinic["email"], subject, body)
        except (RuntimeError, OSError, ValueError) as e:
            log.error("код активации клинике %s не отправлен: %r", clinic["id"], e)
            vid = ""                   # кода у клиники нет — и вводить нечего
    trial.notify(clinic, outcome, ip, f, trial.ORIGIN_PROGRAM)
    if outcome == trial.REQUESTED:
        trial.acknowledge(clinic)
    return outcome, token, vid


@app.post(trial.API_PATH)
async def trial_api(request: Request) -> Response:
    """Заявка на пробный со страницы активации программы: те же правила, что у
    /proba (лимит с адреса, trial.clean, одна клиника на IDNO/e-mail), ответ — JSON.

    Новой клинике — её токен сразу: по нему программа спрашивает /v1/license, пока
    файл не выдан (auto — уже выдан, approve — кнопкой в админке), и дальше живёт
    автообновлением (L13). Повтор — 409 с текстом (почему объявляется — trial.py).
    Без куки и без Origin: зовёт не браузер, а программа; токен получает только
    тот, кто завёл клинику этой заявкой."""
    ip = _ip(request)
    if not license.renew_offered():
        return _api_err("no_renew", 503)
    if trial.limited(ip):
        return _api_err("limited", 429)
    try:
        body = json.loads((await request.body())[:TRIAL_BODY_MAX] or b"{}")
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _api_err("bad_json", 400)
    f, code = trial.clean({k: str(body.get(k) or "") for k in
                           ("name", "idno", "contact_name", "email", "phone", "consent")})
    if code:
        return _api_err(code, 400)
    trial.note(ip)
    outcome, token, vid = await run_in_threadpool(_trial_program, f, ip, fleet.from_request(request))
    if outcome == trial.DUPLICATE:
        if not vid:
            return _api_err("duplicate", 409)
        return JSONResponse({"ok": False, "code": "duplicate", "verify_id": vid,
                             "text": views.TRIAL_MSG["duplicate_code"]}, status_code=409)
    return JSONResponse({"ok": True,
                         "state": "issued" if outcome in (trial.ISSUED, trial.ISSUED_UNMAILED) else "requested",
                         "url": license.renew_url(), "token": token})


def _verify_program(vid: str, code: str, ip: str, ident: dict | None = None) -> str:
    """Код → токен клиники или ''. Строка клиники — свежая: токен мог родиться только что.
    Верный код — и компьютер привязан к клинике (флот). 6 цифр — код из письма (клиника, которую
    нашла заявка); 7 цифр — код кабинета (26.10): клиника, для которой код выдан."""
    with db.connect(immediate=True) as con:
        if account.is_cabinet_code(code):
            clinic = account.use_code(con, vid, code, ip, (ident or {}).get("id", ""))
        else:
            clinic = trial.check_code(con, vid, code, ip)
        if clinic is None:
            return ""
        fleet.touch(con, clinic["id"], ident)
        return license.renew_token(con, clinic)


@app.post(trial.VERIFY_PATH)
async def trial_verify(request: Request) -> Response:
    """Новый компьютер той же клиники: код из письма → токен клиники, как у новой
    заявки. Дальше программа спрашивает /v1/license и получает последний файл.
    Код — одноразовый, CODE_TTL, CODE_ATTEMPTS ошибок; проверок с адреса —
    VERIFY_PER_HOUR (trial.py)."""
    ip = _ip(request)
    if not license.renew_offered():
        return _api_err("no_renew", 503)
    if trial.verify_limited(ip):
        return _api_err("code_limited", 429)
    try:
        body = json.loads((await request.body())[:TRIAL_BODY_MAX] or b"{}")
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _api_err("bad_json", 400)
    vid = str(body.get("verify_id") or "")[:64]
    code = "".join(str(body.get("code") or "").split())[:12]
    token = (await run_in_threadpool(_verify_program, vid, code, ip, fleet.from_request(request))
             if vid and code else "")
    if not token:
        return _api_err("bad_code", 400)
    return JSONResponse({"ok": True, "url": license.renew_url(), "token": token})


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
def clinic_card(request: Request, cid: str, msg: str = "", log: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        c = _clinic(con, cid)
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
        pending = _pending_count(con)
        accounts = account.of_clinic(con, cid)
        devices = fleet.of_clinic(con, cid)
        smsinfo = smsreport.clinic_detail(con, cid)
        names = _names_count(con)
        active = fleet.active(con)
        cab = [(r, con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (r["id"],)).fetchone(),
                con.execute("SELECT count(*) FROM devices WHERE clinic_id=?", (r["id"],)).fetchone()[0])
               for r in cabinet.of(con, cid) if r["id"] != cid]
    return HTMLResponse(views.clinic_page(c, sub, issues, audit, auth.current_user(request), msg,
                                          payments=pays, pending=pending, reminders=rems, accounts=accounts,
                                          devices=devices, smsinfo=smsinfo, names=names,
                                          log=log if codes else "", log_counts=log_counts,
                                          cabinet=cab, active=active.get(cid, 0)))


@app.post("/admin/clinics/{cid}/sibling")
def clinic_sibling(request: Request, cid: str, name: str = Form(""), address: str = Form(""),
                   phone: str = Form(""), email: str = Form(""), idno: str = Form(""),
                   contact_name: str = Form("")) -> Response:
    """«Добавить клинику в кабинет» (26.10): ещё одна клиника с теми же входами кабинета, что у
    этой; тот же IDNO и ящик разрешены, если совпавшая клиника — этого кабинета. Пробный — как у
    клиники из админки: кнопкой во вкладке «Лицензия» новой карточки."""
    if (deny := _guard(request)) is not None:
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
        c = _clinic(con, cid)
        if c is None:
            return Response(status_code=404)
        if not account.of_clinic(con, cid):
            return RedirectResponse(f"/admin/clinics/{cid}?msg=sibling_no_cabinet", status_code=303)
        outcome, new = account.add_sibling(con, c, f, auth.current_user(request))
    if outcome == trial.DUPLICATE:
        return RedirectResponse(f"/admin/clinics/{cid}?msg=sibling_duplicate", status_code=303)
    return RedirectResponse(f"/admin/clinics/{new['id']}?msg=sibling_added", status_code=303)


# ---------- флот (шаг 3, 02.10): компьютеры клиник и их версии ----------


@app.get("/admin/fleet", response_class=HTMLResponse)
def fleet_page(request: Request, msg: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        rep = fleet.report(con)
        pending = _pending_count(con)
        names = _names_count(con)
    return HTMLResponse(views.fleet_page(rep, auth.current_user(request), msg, pending, names))


@app.get("/admin/api/fleet")
def fleet_api(request: Request) -> Response:
    """Тот же отчёт JSON — для будущего интерфейса админки. Кука админа; без неё
    401 JSON, а не 303 на вход (fetch принял бы форму входа за ответ)."""
    if auth.current_user(request) is None:
        return JSONResponse({"ok": False, "code": "login"}, status_code=401)
    with db.connect() as con:
        rep = fleet.report(con)
    return JSONResponse({"ok": True, "data": rep})


def _pending_count(con) -> int:
    return con.execute("SELECT count(*) FROM payments WHERE status='pending'").fetchone()[0]


def _names_count(con) -> int:
    """Имена отправителей, ждущие Олега (заявка или подано): счётчик у раздела «SMS»."""
    return con.execute("SELECT count(*) FROM sms_accounts WHERE sender_state IN (?, ?)",
                       (sms.S_REQUESTED, sms.S_SUBMITTED)).fetchone()[0]


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


@app.get("/admin/sms", response_class=HTMLResponse)
def sms_admin(request: Request, msg: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    kind, frm, to = _period_args(request)
    with db.connect() as con:
        rep = smsreport.report(con, kind, frm, to)
        pending = _pending_count(con)
    return HTMLResponse(views.sms_page(rep, auth.current_user(request), msg, pending))


@app.get("/admin/api/sms")
def sms_api(request: Request) -> Response:
    """Тот же отчёт JSON — для будущего интерфейса админки; без куки 401 JSON, не 303."""
    if auth.current_user(request) is None:
        return JSONResponse({"ok": False, "code": "login"}, status_code=401)
    kind, frm, to = _period_args(request)
    with db.connect() as con:
        rep = smsreport.report(con, kind, frm, to)
    return JSONResponse({"ok": True, "data": rep})


@app.get("/admin/sms/export.xlsx")
def sms_export(request: Request, month: str = "") -> Response:
    """Excel за месяц по клиникам — для сверки с фактурой sms.md. Без номеров и текстов."""
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        name, data = smsreport.export(con, month)
        db.audit(con, auth.current_user(request), "sms_export", None, name)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/admin/sms/sync")
def sms_sync(request: Request) -> Response:
    """Сверить имена с sms.md сейчас — то же, что делает ежедневная задача."""
    if (deny := _guard(request)) is not None:
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


@app.post("/admin/sms/test")
def sms_test(request: Request, to: str = Form("")) -> Response:
    """Тестовая SMS себе от общего имени, мимо пакетов клиник. Номер — только в
    памяти запроса: в журнал идёт факт и исход, без цифр."""
    if (deny := _guard(request)) is not None:
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
        with db.connect() as con:
            db.audit(con, who, "sms_test", None, f"не принято: {e}")
        return RedirectResponse("/admin/sms?msg=sms_test_failed", status_code=303)
    with db.connect() as con:
        db.audit(con, who, "sms_test", None, f"принято sms.md, {got['segments']} сегм., id {got['id']}")
    return RedirectResponse("/admin/sms?msg=sms_test_sent", status_code=303)


@app.post("/admin/clinics/{cid}/sms")
def clinic_sms_action(request: Request, cid: str, action: str = Form(""), value: str = Form(""),
                      reason: str = Form(""), note: str = Form(""), name: str = Form(""),
                      custom_ro: str = Form(""), custom_ru: str = Form(""), custom_on: str = Form("")) -> Response:
    """Кнопки карточки › SMS: вкл/выкл, пилот, потолок, начисление с причиной, имя
    (заявка; заявление получено → подано → отказ). Каждое — строка в журнале."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    back = f"/admin/clinics/{cid}"
    with db.connect(immediate=True) as con:
        if _clinic(con, cid) is None:
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



@app.get("/admin/clinics/{cid}/sms/cerere.pdf")
def clinic_sms_paper(request: Request, cid: str) -> Response:
    """Подписанное заявление клиники на имя (загружено в кабинете, sms_paper.py) —
    файлом, для подачи в кабинете sms.md. ⚠️ Файл прислала клиника: отдаётся
    вложением с nosniff, а не в окно админки. Нет файла у текущей заявки — 404."""
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        p = sms_paper.current(con, cid, body=True)
    if p is None:
        return Response(status_code=404)
    return Response(p["body"], media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{sms_paper.filename(p["sender"])[:-4]}-semnata.pdf"',
                             "X-Content-Type-Options": "nosniff"})

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
def audit_log(request: Request, msg: str = "", kind: str = "") -> Response:
    if (deny := _guard(request)) is not None:
        return deny
    codes = views.audit_codes(kind)  # раздел журнала (?kind=pay); неизвестный — «все»
    only = f"WHERE a.what IN ({','.join('?' * len(codes))}) " if codes else ""
    with db.connect() as con:
        rows = con.execute(_AUDIT_SQL.replace("ORDER BY", only + "ORDER BY", 1), codes).fetchall()
        by_what = dict(con.execute("SELECT what, count(*) FROM audit GROUP BY what").fetchall())
        pending, names = _pending_count(con), _names_count(con)
    return HTMLResponse(views.audit_page(rows, auth.current_user(request), msg, pending,
                                         kind=kind if codes else "", by_what=by_what, names=names))


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


@app.get("/admin/payments", response_class=HTMLResponse)
def payments_pending(request: Request, msg: str = "", month: str = "") -> Response:
    """Платежи (17.10 — вкладки): ждут подтверждения, оплачены (по месяцам, с суммой), отклонены."""
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        rows = con.execute(_PENDING_SQL).fetchall()
        paid = con.execute(_PAID_SQL).fetchall()
        rejected = con.execute(_REJECTED_SQL).fetchall()
        names = _names_count(con)
    # месяц оплаты — по Кишинёву, как сутки SMS: деньги 31-го в 23:30 — доход того месяца
    now = datetime.now(timezone.utc)
    by_month: dict[str, list] = {sms.local(now).strftime("%Y-%m"): []}
    for p in paid:
        by_month.setdefault(sms.local(db.parse_ts(p["paid_at"]) or now).strftime("%Y-%m"), []).append(p)
    months = sorted(by_month, reverse=True)
    month = month if month in by_month else months[0]
    return HTMLResponse(views.payments_page(rows, auth.current_user(request), msg, paid=by_month[month],
                                            month=month, months=months[:12], rejected=rejected, names=names))


@app.post("/admin/clinics/{cid}/payments")
def payment_new(request: Request, cid: str, months: str = Form("1"), amount: str = Form(""),
                send: str = Form(""), method: str = Form(payments.TRANSFER), tier: str = Form("")) -> Response:
    """Платёж: переводом (reference в письме) или картой (L12: плюс ссылка maib).
    Вариант — названный в форме, иначе текущий (tiers.pick); сумма пусто = по правилу
    tiers.price. maib не ответил — строка откатывается вместе с транзакцией, reference
    не потрачен, админ видит maib_failed."""
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
                # вариант без цены в cloud.env и без своей цены подписки — сумму только руками
                return RedirectResponse(f"/admin/clinics/{cid}?msg=tier_not_sold", status_code=303)
            # вторая ожидающая нота не выставляется (03.10): кабинет, страница оплаты и
            # ежедневная задача её не плодят — админка тоже; письмо с прежней — по галочке
            # долг клиники — своя нота или общая нота кабинета, где она строкой (26.10)
            pending = payments.debt_of(con, cid)
            if pending is not None:
                if card and not pending["pay_url"]:
                    # карта к УЖЕ ожидающей ноте: ссылка maib к ней, reference прежний; maib молчит — maib_failed ниже
                    pending = payments.attach_card(con, pending, c, who, _ip(request))
                    code = "card_link"
                    if send == "1":
                        code = _send_payment_letter(con, c, pending, who) or "card_link_mailed"
                else:
                    code = "note_pending"
                    if send == "1":
                        code = _send_payment_letter(con, c, pending, who) or "note_pending_mailed"
                return RedirectResponse(f"/admin/clinics/{cid}?msg={code}", status_code=303)
            try:
                p = payments.create(con, c, m, a, who, tier=t)
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
    """Письмо с нотой абонемента: страница оплаты клиники (paylink.for_mail) — и для карты,
    и для смены варианта; ссылки maib в письме нет (живёт 10 минут, 23.10). Общая нота
    кабинета (26.10) — плательщику, со строками по клиникам."""
    if p["kind"] == payments.CABINET:
        c = _clinic(con, p["clinic_id"])
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
        payments.notify_paid(con, p, who)
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
        p = payments.by_pay_id(con, pay_id) if isinstance(pay_id, str) and pay_id else None
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
            payments.notify_paid(con, p, "maib")
    log.info("maib callback: %s → %s", p["reference"], outcome)
    return JSONResponse({"ok": True, "outcome": outcome})


@app.post(maib.CALLBACK_PATH)
async def maib_callback(request: Request) -> Response:
    return await run_in_threadpool(_maib_callback, await request.body())


def _returned(pay_id: str):
    """Платёж, о котором браузер вернулся от maib, — по payId (неугадываемый id maib, любая
    попытка ноты). ⛔ По orderId (= наш reference) не искать: он порядковый
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
    with db.connect() as con:
        fresh = _payment(con, p["id"])
        if payments.settle(con, fresh, truth, "maib") == payments.SETTLED_PAID:
            payments.notify_paid(con, fresh, "maib")
        return payments.by_pay_id(con, pay_id)


@app.get(maib.OK_PATH, response_class=HTMLResponse)
def pay_ok(payId: str = "", orderId: str = "") -> Response:  # noqa: N803 — имена параметров maib
    """Куда maib возвращает браузер после оплаты. Редирект — не истина: «plătită» страница
    говорит только о ноте, которую сервер уже закрыл по ответу maib (settle); иначе —
    «în curs de confirmare». № заказа, что оплачивается, сумма и дата — требование maib."""
    return HTMLResponse(views.pay_page(True, _returned(payId)))


@app.get(maib.FAIL_PATH, response_class=HTMLResponse)
def pay_fail(payId: str = "", orderId: str = "") -> Response:  # noqa: N803
    return HTMLResponse(views.pay_page(False, _returned(payId)))


def _payment(con, pid: int):
    return con.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()


def _pdf(row) -> Response:
    """Cont de plată из снимка — в окно браузера, с именем файла для «Сохранить»."""
    return Response(receipts.render(row), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{receipts.filename(row["number"])}"'})


@app.get("/admin/payments/{pid}/cont.pdf")
def payment_receipt(request: Request, pid: int) -> Response:
    """Cont de plată оплаченного платежа (receipts.py, 17.10); не оплачен — 404.
    Оплаченный до таблицы receipts получает снимок при первом запросе."""
    if (deny := _guard(request)) is not None:
        return deny
    with db.connect() as con:
        p = _payment(con, pid)
        row = receipts.ensure(con, p, auth.current_user(request)) if p is not None else None
    if row is None:
        return Response(status_code=404)
    return _pdf(row)


def _back(request: Request, p) -> str:
    """Откуда пришли: со страницы ожидающих — туда же, иначе в карточку."""
    # путь без ?…: страница платежей бывает и /admin/payments?msg=… после прошлого действия (17.10)
    ref = request.headers.get("referer", "").split("#")[0].split("?")[0]
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
        code = "payment_confirmed" if payments.notify_paid(con, p, who) else "payment_confirmed_mailed"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@app.post("/admin/payments/{pid}/repeat")
def payment_repeat(request: Request, pid: int, sure: str = Form("")) -> Response:
    """«Зачесть повторный перевод» (02.10): по уже оплаченной или отклонённой ноте
    пришёл ещё один перевод — следующий период отдельной строкой с новым reference,
    файл и письмо как у «Подтвердить» (payments.credit_again). Галочка «перевод
    пришёл» обязательна: кнопка продлевает и выдаёт файл, случайный клик — подарок.
    Ожидающую ноту закрывает «Подтвердить», не эта кнопка."""
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
        if sure != "1":
            return RedirectResponse(f"{back}?msg=repeat_unsure", status_code=303)
        try:
            new = payments.credit_again(con, p, payments.TRANSFER, who)
        except ValueError as e:
            code = {"pending": "payment_is_pending", "idno": "bad_idno"}.get(str(e), "payment_not_pending")
            return RedirectResponse(f"{back}?msg={code}", status_code=303)
        except RuntimeError:
            return RedirectResponse(f"{back}?msg=no_key", status_code=303)
        code = "payment_repeat" if payments.notify_paid(con, new, who) else "payment_repeat_mailed"
    return RedirectResponse(f"{back}?msg={code}", status_code=303)


@app.post("/admin/payments/{pid}/mail")
def payment_mail(request: Request, pid: int) -> Response:
    """Письмо с ожидающей нотой ещё раз (03.10): та же нота, тот же reference —
    когда бухгалтер клиники потерял первое или нота выставлена без письма."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    who = auth.current_user(request)
    with db.connect() as con:
        p = con.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        if p is None:
            return Response(status_code=404)
        c = _clinic(con, p["clinic_id"])
        if p["status"] != payments.PENDING:
            code = "payment_not_pending"
        else:
            code = _send_payment_letter(con, c, p, who) or "payment_mailed"
    return RedirectResponse(f"/admin/clinics/{p['clinic_id']}?msg={code}", status_code=303)


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


@app.post("/admin/clinics/{cid}/tier")
def clinic_tier(request: Request, cid: str, tier: str = Form(""), price: str = Form("")) -> Response:
    """Вариант абонемента вручную — для исключений (Олег 23.10): сразу, без оплаты, строкой
    в журнале (tier_set). Обычный путь — выбор клиники при оплате (payments.choose)."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    raw = price.strip()
    if raw and not raw.isdigit():
        return RedirectResponse(f"/admin/clinics/{cid}?msg=tier_price", status_code=303)
    with db.connect() as con:
        if _clinic(con, cid) is None:
            return Response(status_code=404)
        code = payments.set_tier(con, cid, tier, int(raw) if raw else None, auth.current_user(request))
    return RedirectResponse(f"/admin/clinics/{cid}?msg={code or 'tier_set'}", status_code=303)


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


@app.post("/admin/accounts/{aid}/detach")
def account_detach(request: Request, aid: str) -> Response:
    """Отвязать учётную запись кабинета от клиники (смена директора): запись
    удаляется, следующий вход этого аккаунта Google начинается с регистрации."""
    if (deny := _guard(request)) is not None:
        return deny
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        acc = account.get(con, aid)
        if acc is None:
            return Response(status_code=404)
        cid = acc["clinic_id"]
        account.detach(con, acc, auth.current_user(request))
    return RedirectResponse(f"/admin/clinics/{cid}?msg=account_detached" if cid else "/admin", status_code=303)


# ---------- кабинет клиники (шаг 3, 01.10): вход через Google, /cont ----------
#
# Публичная часть сервера по-румынски, своя кука (dp_cont), без админки.
# Поток входа — account.py; здесь только маршруты: что показать и куда вести.


def _cookie_args() -> dict:
    return {"httponly": True, "samesite": "lax", "secure": config.SECURE_COOKIES}


def _current_account(con, request: Request):
    """Учётная запись из куки кабинета — строкой из базы (отвязанная не пускает)."""
    aid = auth.current_account_id(request)
    return account.get(con, aid) if aid else None


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


@app.get("/cont", response_class=HTMLResponse)
def cont_home(request: Request, msg: str = "", c: str = "") -> Response:
    """Кабинет: дашборд открытой клиники (`?c=` — какой; без него — открытой последней), у
    записи с несколькими клиниками — список «Clinicile mele» сверху (26.10)."""
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
        sa = con.execute("SELECT * FROM sms_accounts WHERE clinic_id=?", (cl["id"],)).fetchone()
        smsinfo = None
        if sms.offered(sa):
            # имя общее на кабинет (26.10): заявка, заявление и год — у главной клиники; строка счёта
            # не заводится просмотром: без неё — «имени нет»
            owner = _clinic(con, sms.name_owner(con, cl["id"]))
            osa = con.execute("SELECT * FROM sms_accounts WHERE clinic_id=?", (owner["id"],)).fetchone()
            mine_name = owner["id"] == cl["id"]
            smsinfo = {"acc": osa, "from": sms.sender_for(con, cl["id"]), "suggest": sms.suggest(owner["name"]),
                       "paper": sms_paper.current(con, owner["id"]), "missing": sms_paper.missing(owner),
                       "clinic": owner, "shared": "" if mine_name else owner["name"],
                       "data_href": "#date" if mine_name else f"/cont?c={owner['id']}#date"}
    # последний выпуск — из памяти или одним запросом к API; вне транзакции
    return HTMLResponse(views.cont_page(acc, cl, sub, issue, pays, download.latest(), msg, devices=devices,
                                        smsinfo=smsinfo, cab=cab, group=group))


@app.get("/cont/login", response_class=HTMLResponse)
def cont_login(request: Request, msg: str = "") -> Response:
    with db.connect() as con:
        if _current_account(con, request) is not None:
            return RedirectResponse("/cont", status_code=303)
    return HTMLResponse(views.cont_login_page(msg, enabled=account.enabled()))


@app.post("/cont/login/email", response_class=HTMLResponse)
def cont_login_email(request: Request, email: str = Form("")) -> Response:
    """Вход без Google (02.10): код на введённый ящик. Ответ одинаков для любого
    годного ящика; лимиты — login.py; письмо — после транзакции."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        if _current_account(con, request) is not None:
            return RedirectResponse("/cont", status_code=303)
    email = "".join(email.split()).lower()
    on = account.enabled()
    if not elogin.email_ok(email):
        return HTMLResponse(views.cont_login_page("bad_email", enabled=on, values={"email": email}), status_code=400)
    ip = _ip(request)
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


@app.post("/cont/login/cod", response_class=HTMLResponse)
def cont_login_code(request: Request, verify_id: str = Form(""), code: str = Form(""),
                    email: str = Form("")) -> Response:
    """Код из письма → учётная запись e-mail и кука кабинета; клиника с этим
    ящиком есть → кабинет, нет → регистрация. Одноразовый, CODE_TTL,
    CODE_ATTEMPTS ошибок на код, VERIFY_PER_HOUR проверок с адреса."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = _ip(request)
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


@app.get("/auth/google")
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


@app.get(account.CALLBACK_PATH)
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
    acc = await run_in_threadpool(_google_login, ident, _ip(request))
    resp = RedirectResponse("/cont" if acc["clinic_id"] else "/cont/inregistrare", status_code=303)
    resp.set_cookie(auth.ACCOUNT_COOKIE, auth.account_cookie(acc["id"]), max_age=auth.ACCOUNT_TTL, path="/",
                    **_cookie_args())
    resp.delete_cookie(auth.OAUTH_COOKIE, path="/auth/google")
    return resp


@app.post("/cont/iesire")
def cont_logout(request: Request) -> Response:
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    resp = RedirectResponse("/cont/login?msg=logged_out", status_code=303)
    resp.delete_cookie(auth.ACCOUNT_COOKIE, path="/")
    return resp


@app.get("/cont/inregistrare", response_class=HTMLResponse)
def cont_register(request: Request, msg: str = "") -> Response:
    with db.connect() as con:
        acc = _current_account(con, request)
    if acc is None:
        return _cont_login_redirect()
    if acc["clinic_id"]:
        return RedirectResponse("/cont", status_code=303)
    return HTMLResponse(views.cont_register_page(acc, msg))


@app.post("/cont/inregistrare", response_class=HTMLResponse)
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
    ip = _ip(request)
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


@app.post("/cont/inregistrare/cod", response_class=HTMLResponse)
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
    ip = _ip(request)
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


@app.post("/cont/date")
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


@app.post("/cont/nota")
def cont_note(request: Request, months: str = Form("1"), method: str = Form(payments.TRANSFER),
              tier: str = Form(""), terms: str = Form(""), c: str = "") -> Response:
    """Нота на абонемент из кабинета: тот же выбор, что на странице оплаты
    (payments.choose — вариант и срок, другой заменяет открытую ноту, долг один); карта —
    только при настроенном maib; ⛔ без галочки условий — нет (требование maib). Письмо с
    нотой — как из админки."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    m = _months(months)
    card = method == payments.CARD and maib.enabled()
    try:
        with db.connect(immediate=True) as con:
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
                _send_payment_letter(con, cl, p, acc["email"])
            if card:
                return _card_go(con, p, cl, acc["email"], _ip(request), _cont_to(con, acc, cl["id"]))
            if outcome == payments.EXISTS:
                return RedirectResponse(_cont_to(con, acc, cl["id"], "note_exists"), status_code=303)
            back = _cont_to(con, acc, cl["id"], "note_replaced" if outcome == payments.REPLACED else "note_created")
    except maib.MaibError as e:
        log.error("maib: нота из кабинета не создана: %s", e)
        return RedirectResponse("/cont?msg=maib_failed", status_code=303)
    return RedirectResponse(back, status_code=303)


@app.get("/cont/plati/{number}.pdf")
def cont_receipt(request: Request, number: str) -> Response:
    """Cont de plată из кабинета — только документ СВОИХ клиник (своя нота или общая, где
    своя клиника строкой); чужой номер или неоплаченная нота — 404, без входа — на вход."""
    with db.connect() as con:
        acc = _current_account(con, request)
        if acc is None:
            return _cont_login_redirect()
        own = {r["id"] for r in account.clinics(con, acc)}
        p = con.execute("SELECT * FROM payments WHERE reference=?", (number,)).fetchone()
        if p is not None and p["clinic_id"] not in own and not any(
                ln["clinic_id"] in own for ln in payments.lines_of(con, p["id"])):
            p = None
        row = receipts.ensure(con, p, acc["email"]) if p is not None else None
    if row is None:
        return Response(status_code=404)
    return _pdf(row)



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
    owner = _clinic(con, sms.name_owner(con, cl["id"]))
    return acc, cl, owner, sms.ensure(con, owner["id"])


@app.post("/cont/sms/nume")
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


@app.post("/cont/sms/cerere.pdf")
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


@app.post("/cont/sms/cerere")
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


# ---------- кабинет › клиники кабинета (26.10): «Adaugă clinică», код компьютера, общая нота ----------
#
# Филиал = ещё одна клиника в том же кабинете (Олег 26.10, cabinet.py): своя лицензия, пробный,
# подписка и база; общие — вход, общая нота и имя отправителя SMS.


@app.get("/cont/clinica-noua", response_class=HTMLResponse)
def cont_add_form(request: Request, c: str = "", msg: str = "") -> Response:
    with db.connect() as con:
        acc, cl = _cont_clinic(request, con, c, post=False)
        if acc is None:
            return _cont_login_redirect()
        if cl is None:
            return RedirectResponse("/cont/inregistrare" if not account.clinics(con, acc) else "/cont",
                                    status_code=303)
    return HTMLResponse(views.cont_add_page(acc, cl, msg))


@app.post("/cont/clinica-noua", response_class=HTMLResponse)
def cont_add_submit(request: Request, c: str = "", name: str = Form(""), address: str = Form(""),
                    phone: str = Form(""), contact_name: str = Form(""), email: str = Form(""),
                    idno: str = Form(""), consent: str = Form("")) -> Response:
    """Ещё одна клиника кабинета: заявка на пробный теми же правилами и лимитом, что регистрация,
    но ⛔ всегда ждёт одобрения Олега, при любом DP_TRIAL_MODE (trial.APPROVE_ALWAYS); тот же IDNO
    и ящик разрешены внутри кабинета, чужой клинике — «add_duplicate» и письмо Олегу. Ответ —
    страница с кодом компьютера новой клиники (виден один раз; программа активируется им сразу,
    файл придёт после одобрения), вход в неё — у всех записей кабинета; она же открыта."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect() as con:
        acc, cl = _cont_clinic(request, con, c)
    if cl is None:
        return _cont_deny(acc)
    ip = _ip(request)
    f, code = account.clean_new({"name": name, "address": address, "phone": phone, "contact_name": contact_name,
                                 "email": email, "idno": idno, "consent": consent})
    if code:
        return HTMLResponse(views.cont_add_page(acc, cl, code, f), status_code=400)
    if trial.limited(ip):
        return HTMLResponse(views.cont_add_page(acc, cl, "limited", f), status_code=429)
    trial.note(ip)
    act = until = ""
    main = None
    with db.connect(immediate=True) as con:
        if len(account.clinics(con, acc)) >= account.CLINICS_MAX:
            return HTMLResponse(views.cont_add_page(acc, cl, "clinics_max", f), status_code=409)
        outcome, new = account.add_clinic(con, cl, f, ip, acc["email"])
        if outcome != trial.DUPLICATE:
            con.execute("UPDATE accounts SET clinic_id=? WHERE id=?", (new["id"], acc["id"]))
            act, until = account.new_code(con, new, acc["email"])
            main = cabinet.main_of(con, new["id"])
    trial.notify(new, outcome, ip, dict(f, cabinet=f"{cl['name']} ({cl['id']})"), trial.ORIGIN_CONT_ADD)
    if outcome == trial.DUPLICATE:
        return HTMLResponse(views.cont_add_page(acc, cl, "add_duplicate", f), status_code=409)
    trial.acknowledge(new)
    return HTMLResponse(views.cont_activation_page(acc, new, act, until, main, download.latest(),
                                                   "clinic_added_requested"))


@app.post("/cont/cod", response_class=HTMLResponse)
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


@app.get("/cont/nota-comuna", response_class=HTMLResponse)
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
    try:
        with db.connect(immediate=True) as con:
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
                return _card_go(con, pending, _clinic(con, pending["clinic_id"]), acc["email"], ip, back)
            picks = []
            for r, _, _ in rows:
                t = form.get(f"t_{r['id']}") or ""
                if t:
                    picks.append((r, t, _months(form.get(f"m_{r['id']}") or "1")))
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
            _send_payment_letter(con, payer, p, acc["email"])
            if card:
                return _card_go(con, p, payer, acc["email"], ip, back)
    except maib.MaibError as e:
        log.error("maib: общая нота из кабинета не создана: %s", e)
        return RedirectResponse(f"{back}?msg=maib_failed", status_code=303)
    return RedirectResponse(f"{back}?msg={'group_replaced' if replaced else 'group_created'}", status_code=303)


@app.post("/cont/nota-comuna")
async def cont_group_submit(request: Request) -> Response:
    """Общая нота: у каждой клиники вариант (`t_<id>`, пусто — не входит) и срок (`m_<id>`),
    одна галочка условий; заменяет открытые ноты своих клиник и прежнюю общую (payments.
    create_group); переводом — нота здесь и письмом плательщику, картой — сразу к maib. `ref` —
    карта к открытой общей ноте."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    form = await request.form(max_fields=2 * (account.CLINICS_MAX + 4))
    data = {k: str(v) for k, v in form.items() if isinstance(v, str)}
    return await run_in_threadpool(_group_submit, request, data, _ip(request))


@app.post("/cont/nota-comuna/anuleaza")
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

# ---------- скачивание с сайта (L15): /descarca ----------


@app.get("/descarca")
def descarca(request: Request) -> Response:
    """302 на подписанный установщик последнего выпуска (GitHub Releases); API
    молчит — на страницу выпусков. Кто скачивал — строкой в журнале."""
    url, rel = download.target()
    with db.connect() as con:
        db.audit(con, "site", "download", None, f"{rel.asset if rel else 'pagina GitHub'} {_ip(request)}")
    return RedirectResponse(url, status_code=302)
