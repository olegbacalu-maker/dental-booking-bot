"""API программы клиники `/v1/*` (03.11, из main.py): файл лицензии (L13), обновления,
ссылки «Plătește acum» и «Deschide contul clinicii», SMS-пакет и уведомления sms.md, заявка
пробного и код нового компьютера, подтверждение ящика, акт акцепта условий. Вход — Bearer-токен
клиники; ответы — JSON."""
from __future__ import annotations

import json
import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from . import (account, config, contlink, db, emailconf, fleet, license, maib, mail, payments, paylink, sms, smsmd,
               terms, trial, updates, views, web)
from . import login as elogin  # ⚠️ не `login`: так зовётся маршрут входа админки (routes_admin)

log = logging.getLogger("cloud")
router = APIRouter()


# ---------- автообновление файла (L13): программа клиники спрашивает сама ----------


def _bearer(request: Request) -> str:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h[:7].lower() == "bearer " else ""


@router.get(license.RENEW_PATH)
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
        mailbox = emailconf.headers(c)      # подтверждён ли ящик — рядом с файлом, не в нём (27.10)
        mailbox.update(terms.headers(con, c))   # последняя принятая версия условий (29.10, terms.py)
        if row is None or row["seq"] <= seq:
            return Response(status_code=204, headers=mailbox)
        db.audit(con, "program", "renew", c["id"], f"файл {row['seq']} забран программой (у неё был {seq})")
    return Response(license.issue_text(row), media_type="application/json", headers=mailbox)


@router.get(updates.API_PATH)
def update_api(channel: str = "stable", current: str = "") -> Response:
    """Сервер обновлений (03.10): какая версия свежая для канала программы.
    200 — выпуск новее `current` (версия, страница, файлы со ссылкой, размером и
    sha256); 204 — новее нет; 503 — сервер сам не знает, программа идёт к GitHub.
    Без входа и без токена: выпуски публичны, а программа проверяет ответ сама."""
    status, body = updates.answer(channel, current)
    if body is None:
        return Response(status_code=status)
    return JSONResponse(body, status_code=status)


@router.post(paylink.API_PATH)
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


@router.post(contlink.API_PATH)
def cont_link_api(request: Request) -> Response:
    """Программа просит вход в кабинет (27.10, «Deschide contul clinicii»): тот же Bearer, что у
    /v1/license. Ответ — одноразовая ссылка /cont/intra/<id> на contlink.TTL; каждое нажатие —
    новая; больше contlink.PER_HOUR за час — 429."""
    token = _bearer(request)
    if not token:
        return JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    with db.connect(immediate=True) as con:
        c = con.execute("SELECT * FROM clinics WHERE renew_token=? AND renew_token<>'' AND declined_at IS NULL",
                        (token,)).fetchone()
        if c is None:
            return JSONResponse({"ok": False, "code": "token_unknown"}, status_code=401)
        fleet.touch(con, c["id"], fleet.from_request(request))          # флот: компьютер вышел на связь
        made = contlink.create(con, c)
    if made is None:
        return JSONResponse({"ok": False, "code": "limited"}, status_code=429)
    return JSONResponse({"ok": True, "url": contlink.url_for(made[0]), "expires_at": made[1]})


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
    """Счёт SMS и, рядом с ним, ожидающие ноты SMS клиники (05.11, `notes`): программа держит блок
    ноты на экране, пока та ждёт оплаты. Поле добавочное — прежние ключи счёта не менялись."""
    with db.connect(immediate=True) as con:
        data = sms.view(con, cid)
        data["notes"] = web.sms_open_notes(con, web.clinic(con, cid))
        return data


@router.get("/v1/sms/account")
async def sms_account(request: Request) -> Response:
    """Что программа показывает в Setări › SMS: включено, имя и его состояние,
    от какого имени уходят SMS, остаток, пакеты, потолок, почему нельзя сейчас."""
    c, deny = await run_in_threadpool(_sms_clinic, request)
    if deny is not None:
        return deny
    return JSONResponse(await run_in_threadpool(_sms_view, c["id"]))


@router.post("/v1/sms/send")
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


@router.post("/v1/sms/status")
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


@router.post("/v1/sms/sender")
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
    units = 0
    if not name:
        try:
            units = int(body.get("pack"))
        except (TypeError, ValueError):
            units = 0
    kind = payments.SMS_NAME if name else payments.SMS
    with db.connect(immediate=True) as con:
        if name:
            # год имени — та же логика, что у кабинета (web.sms_name_note): имя общее на кабинет
            # (26.10), нота — главной клинике, на её ящик
            code, c, p, created = web.sms_name_note(con, c, "program")
            if code:
                return _sms_answer(code)
            acc = sms.account(con, c["id"])
        else:
            # пакет — та же логика, что у кабинета (web.sms_pack_note): пакет из прайса, IDNO,
            # кому не продаётся, одна открытая нота; другой пакет заменяет её — `created`, с письмом
            code, p, outcome = web.sms_pack_note(con, c, units, "program")
            if code:
                return _sms_answer(code, **({"packs": sms.packs()} if code == "sms_pack" else {}))
            created = outcome != payments.EXISTS
        # Карта — на нашей странице оплаты, кнопкой после галочки условий (23.10): ссылка maib
        # живёт минуты (maib.PAY_TTL) и рождается по клику (payments.card_link), поэтому ни программе, ни
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


@router.post("/v1/sms/order")
async def sms_order(request: Request) -> Response:
    c, deny = await run_in_threadpool(_sms_clinic, request)
    if deny is not None:
        return deny
    body = await _sms_body(request)
    if body is None:
        return _sms_answer("bad_json")
    return await run_in_threadpool(_sms_order, c, body, web.ip(request))


@router.post("/v1/smsmd/dlr/{secret}")
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


# ---------- заявка на пробный из программы (26.09): активация без файла ----------

TRIAL_BODY_MAX = 16 * 1024       # заявка — полкилобайта; чужой мегабайт до разбора не доходит


def _api_err(code: str, status: int) -> Response:
    """Отказ программе: код и румынский текст — программа показывает его как есть."""
    return JSONResponse({"ok": False, "code": code, "text": views.TRIAL_MSG.get(code, code)},
                        status_code=status)


def _trial_program(f: dict, ip: str, ident: dict | None = None,
                   accept: tuple[str, str] = ("", "")) -> tuple[str, str, str, dict | None]:
    """Заявка из программы → (исход, токен или '', verify_id или '', акт или None). В потоке: база
    и письма блокируют. На повтор — код на e-mail, который у клиники уже записан.
    `ident` — личность машины из заголовков (флот): компьютер привязывается к
    новой клинике сразу, при повторе — только после кода (чужой IDNO в заявке
    не должен приписать чужой компьютер клинике). `accept` — (версия условий, кто принял) из
    тела заявки (29.10, terms.py): новой клинике — строка акта и квитанция в ответе; без версии
    (старая программа) — как раньше, с одним `consent_at`."""
    vid = code = ""
    act = None
    with db.connect(immediate=True) as con:
        outcome, clinic = trial.submit(con, f, ip, who="program", origin=trial.ORIGIN_PROGRAM, device=ident)
        token = ""
        if outcome == trial.DEVICE_TAKEN:
            # компьютер чужой клиники: ни токена, ни кода, ни письма — строка в журнале (submit)
            return outcome, "", "", None
        if outcome == trial.DUPLICATE:
            vid, code = trial.new_code(con, clinic, ip)
        else:
            if accept[0]:
                act = terms.view(terms.record(con, clinic["id"], accept[0], accept[1], terms.SRC_TRIAL, ip, ident))
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
    return outcome, token, vid, act


@router.post(trial.API_PATH)
async def trial_api(request: Request) -> Response:
    """Заявка на пробный со страницы активации программы: те же правила, что у
    /proba (лимит с адреса, trial.clean, одна клиника на IDNO/e-mail), ответ — JSON.

    Новой клинике — её токен сразу: по нему программа спрашивает /v1/license, пока
    файл не выдан (auto — уже выдан, approve — кнопкой в админке), и дальше живёт
    автообновлением (L13). Повтор — 409 с текстом (почему объявляется — trial.py).
    Без куки и без Origin: зовёт не браузер, а программа; токен получает только
    тот, кто завёл клинику этой заявкой."""
    ip = web.ip(request)
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
    outcome, token, vid, act = await run_in_threadpool(_trial_program, f, ip, fleet.from_request(request),
                                                       terms.from_body(body))
    if outcome == trial.DEVICE_TAKEN:
        return _api_err("device_taken", 409)
    if outcome == trial.DUPLICATE:
        if not vid:
            return _api_err("duplicate", 409)
        return JSONResponse({"ok": False, "code": "duplicate", "verify_id": vid,
                             "text": views.TRIAL_MSG["duplicate_code"]}, status_code=409)
    out = {"ok": True, "state": "issued" if outcome in (trial.ISSUED, trial.ISSUED_UNMAILED) else "requested",
           "url": license.renew_url(), "token": token}
    if act is not None:
        out["terms"] = act                   # квитанция акта (29.10): программа кладёт её в папку contract
    return JSONResponse(out)


def _verify_program(vid: str, code: str, ip: str, ident: dict | None = None,
                    accept: tuple[str, str] = ("", "")) -> tuple[str, dict | None]:
    """Код → (токен клиники или '', акт или None). Строка клиники — свежая: токен мог родиться
    только что. Верный код — и компьютер привязан к клинике (флот). 6 цифр — код из письма (клиника,
    которую нашла заявка); 7 цифр — код кабинета (26.10): клиника, для которой код выдан.
    `accept` — (версия условий, кто принял) из тела (29.10): верный код — строка акта source=verify."""
    with db.connect(immediate=True) as con:
        if account.is_cabinet_code(code):
            clinic = account.use_code(con, vid, code, ip, (ident or {}).get("id", ""))
        else:
            clinic = trial.check_code(con, vid, code, ip)
        if clinic is None:
            return "", None
        if trial.device_kept(con, clinic, ident, ip) is not None:
            return trial.DEVICE_TAKEN, None       # не токен: маршрут отвечает 409 (код уже погашен)
        fleet.touch(con, clinic["id"], ident)
        act = (terms.view(terms.record(con, clinic["id"], accept[0], accept[1], terms.SRC_VERIFY, ip, ident))
               if accept[0] else None)
        return license.renew_token(con, clinic), act


@router.post(trial.VERIFY_PATH)
async def trial_verify(request: Request) -> Response:
    """Новый компьютер той же клиники: код из письма → токен клиники, как у новой
    заявки. Дальше программа спрашивает /v1/license и получает последний файл.
    Код — одноразовый, CODE_TTL, CODE_ATTEMPTS ошибок; проверок с адреса —
    VERIFY_PER_HOUR (trial.py)."""
    ip = web.ip(request)
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
    token, act = (await run_in_threadpool(_verify_program, vid, code, ip, fleet.from_request(request),
                                          terms.from_body(body)) if vid and code else ("", None))
    if not token:
        return _api_err("bad_code", 400)
    if token == trial.DEVICE_TAKEN:
        return _api_err("device_kept", 409)
    out = {"ok": True, "url": license.renew_url(), "token": token}
    if act is not None:
        out["terms"] = act
    return JSONResponse(out)


# ---------- подтверждение ящика клиники (27.10, план В; emailconf.py) ----------
#
# Программа (Bearer — токен файла, как у /v1/license и /v1/pay-link): «Retrimite», код, «Schimbă
# adresa». Отказы — `_api_err`: код и румынский текст, программа показывает его как есть. Письмо —
# после транзакции, как у кода активации.

EMAIL_BODY_MAX = 4 * 1024


def _email_answer(c, sent: bool = False) -> Response:
    return JSONResponse({"ok": True, **emailconf.view(c), "sent": sent})


def _email_send(token: str, ip: str, new_email: str = "") -> Response:
    """Новый код на ящик клиники; `new_email` — сперва сменить ящик («Schimbă adresa»). В потоке."""
    with db.connect(immediate=True) as con:
        c = con.execute("SELECT * FROM clinics WHERE renew_token=? AND renew_token<>''", (token,)).fetchone()
        if c is None:
            return JSONResponse({"ok": False, "code": "token_unknown"}, status_code=401)
        if not new_email and emailconf.confirmed(c):
            return _email_answer(c)
        if emailconf.limited(con, c):
            db.audit(con, "program", "code_limit", c["id"], f"подтверждение e-mail, {ip}")
            return _api_err("email_limited", 429)
        if new_email:
            code = emailconf.change(con, c, new_email, ip)
            if code:
                return _api_err(code, 409)
            c = con.execute("SELECT * FROM clinics WHERE id=?", (c["id"],)).fetchone()
        if not c["email"]:
            return _api_err("bad_email", 400)
        key, code = emailconf.issue(con, c, "program")
        db.audit(con, "program", "email_code_sent", c["id"], f"на {c['email']}, {ip}")
    subject, body = mail.confirm_letter(c["name"], emailconf.url_for(key), code, emailconf.LINK_TTL.days)
    try:
        mail.send(c["email"], subject, body)
    except (RuntimeError, OSError, ValueError) as e:
        log.error("подтверждение ящика клинике %s не отправлено: %r", c["id"], e)
        return _api_err("email_mail_failed", 502)
    return _email_answer(c, sent=True)


async def _email_json(request: Request) -> dict | None:
    try:
        body = json.loads((await request.body())[:EMAIL_BODY_MAX] or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


@router.post(emailconf.API_CODE)
async def email_code_api(request: Request) -> Response:
    """«Retrimite»: письмо со ссылкой и кодом на ящик клиники. Подтверждённому — ответ без письма.
    Лимиты: запросов с адреса — как у входа кодом, писем клинике — emailconf.CODES_PER_HOUR."""
    token, ip = _bearer(request), web.ip(request)
    if not token:
        return JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    if elogin.request_limited(ip):
        return _api_err("limited", 429)
    return await run_in_threadpool(_email_send, token, ip)


@router.post(emailconf.API_CHANGE)
async def email_change_api(request: Request) -> Response:
    """«Schimbă adresa»: лечение опечатки — новый ящик и код на него. ⛔ Только пока ящик не
    подтверждён (emailconf.change): подтверждённый меняет кабинет или Олег."""
    token, ip = _bearer(request), web.ip(request)
    if not token:
        return JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    if elogin.request_limited(ip):
        return _api_err("limited", 429)
    body = await _email_json(request)
    if body is None:
        return _api_err("bad_json", 400)
    email = "".join(str(body.get("email") or "").split())
    if not elogin.email_ok(email):
        return _api_err("bad_email", 400)
    return await run_in_threadpool(_email_send, token, ip, email)


def _email_check(token: str, code: str, ip: str) -> Response:
    with db.connect(immediate=True) as con:
        c = con.execute("SELECT * FROM clinics WHERE renew_token=? AND renew_token<>''", (token,)).fetchone()
        if c is None:
            return JSONResponse({"ok": False, "code": "token_unknown"}, status_code=401)
        if not emailconf.confirmed(c) and not emailconf.check_code(con, c, code, ip):
            return _api_err("email_bad_code", 400)
        return _email_answer(con.execute("SELECT * FROM clinics WHERE id=?", (c["id"],)).fetchone())


@router.post(emailconf.API_CONFIRM)
async def email_confirm_api(request: Request) -> Response:
    """Код из письма, введённый в программе → ящик подтверждён. Проверок с адреса — как у кода
    активации (trial.VERIFY_PER_HOUR), ошибок на коды клиники — emailconf.CODE_ATTEMPTS."""
    token, ip = _bearer(request), web.ip(request)
    if not token:
        return JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    if trial.verify_limited(ip):
        return _api_err("code_limited", 429)
    body = await _email_json(request)
    if body is None:
        return _api_err("bad_json", 400)
    code = "".join(str(body.get("code") or "").split())[:12]
    return await run_in_threadpool(_email_check, token, code, ip)


# ---------- акт акцепта условий (29.10, terms.py) ----------
#
# Программа (Bearer — токен файла, как у /v1/license): повторное принятие новой версии условий —
# баннер «Termenii și condițiile s-au actualizat» в программе. Кабинет: список актов своей клиники
# и печатная страница акта (экземпляр клиники к общему договору). Разбор — terms.py.


def _terms_accept(token: str, ip: str, body: dict, ident: dict | None) -> Response:
    with db.connect(immediate=True) as con:
        c = con.execute("SELECT * FROM clinics WHERE renew_token=? AND renew_token<>'' AND declined_at IS NULL",
                        (token,)).fetchone()
        if c is None:
            return JSONResponse({"ok": False, "code": "token_unknown"}, status_code=401)
        version, actor = terms.from_body(body)
        if not version:
            return _api_err("bad_terms", 400)
        fleet.touch(con, c["id"], ident)
        act = terms.view(terms.record(con, c["id"], version, actor, terms.SRC_PROGRAM, ip, ident))
    return JSONResponse({"ok": True, **act})


@router.post(terms.API_ACCEPT)
async def terms_accept_api(request: Request) -> Response:
    """{terms, actor} → строка акта source=program, ответ — квитанция {id, version, at}.
    Версия — дата dd.mm.yyyy (bad_terms иначе); актов одной версии может быть несколько
    (второй компьютер, повтор после сбоя записи квитанции) — это история, не состояние."""
    token, ip = _bearer(request), web.ip(request)
    if not token:
        return JSONResponse({"ok": False, "code": "token_missing"}, status_code=401)
    if elogin.request_limited(ip):
        return _api_err("limited", 429)
    body = await _email_json(request)
    if body is None:
        return _api_err("bad_json", 400)
    return await run_in_threadpool(_terms_accept, token, ip, body, fleet.from_request(request))
