"""Публичные страницы без входа (03.11, из main.py): robots.txt, форма пробного /proba,
страница подтверждения ящика из письма (/confirma/<ключ>), скачивание программы /descarca,
страница ответа пациента по ссылке из SMS (/r/<код>, короткий хост v.dentpilot.md — plink_page.py)."""
from __future__ import annotations

import logging
import pathlib
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import auth, db, download, emailconf, payments, plink, plink_page, robots, trial, views, web

log = logging.getLogger("cloud")
router = APIRouter()


@router.get("/robots.txt")
def robots_txt() -> Response:
    """Обход открыт намеренно: запрет индексации едет заголовком с каждым ответом,
    и поисковик обязан до него дойти (robots.py). Без этого маршрута — 404 JSON."""
    return Response(robots.TXT, media_type="text/plain; charset=utf-8")


# ---------- форма пробного периода (L14): публичная, без куки ----------


@router.get("/proba", response_class=HTMLResponse)
def trial_form() -> Response:
    return HTMLResponse(views.trial_page())


@router.post("/proba", response_class=HTMLResponse)
def trial_submit(request: Request, name: str = Form(""), idno: str = Form(""), contact_name: str = Form(""),
                 email: str = Form(""), phone: str = Form(""), consent: str = Form(""),
                 website: str = Form("")) -> Response:
    """Заявка: лимит с адреса, скрытое поле, чистые поля, одна клиника на IDNO/e-mail
    (trial.submit), письмо Олегу; в approve — клинике «принято», в auto — файл."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    ip = web.ip(request)
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
    with payments.outbox() as box, db.connect(immediate=True) as con:      # письмо — после commit
        outcome, clinic = trial.submit(con, f, ip)
        box.add(trial.letter(con, outcome, clinic, "form"))
    outcome = trial.mailed(outcome, clinic, box.code, "form")
    trial.notify(clinic, outcome, ip, f)
    if outcome == trial.REQUESTED:
        trial.acknowledge(clinic)
    return HTMLResponse(views.trial_done_page(outcome, f["email"]))


@router.get(emailconf.PAGE + "/{key}", response_class=HTMLResponse)
def email_confirm_page(key: str) -> Response:
    """Ссылка из письма: страница с кнопкой. ⛔ GET ничего не пишет — почтовые сканеры открывают
    ссылки сами, и подтверждал бы сканер, а не человек."""
    with db.connect() as con:
        _, c = emailconf.by_link(con, key)
    if c is None:
        return HTMLResponse(views.confirm_page("dead"), status_code=404)
    if emailconf.confirmed(c):
        return HTMLResponse(views.confirm_page("already"))
    return HTMLResponse(views.confirm_page("ask", c["name"], c["email"], key))


@router.post(emailconf.PAGE + "/{key}", response_class=HTMLResponse)
def email_confirm_submit(request: Request, key: str) -> Response:
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    with db.connect(immediate=True) as con:
        _, c = emailconf.by_link(con, key)
        if c is None:
            return HTMLResponse(views.confirm_page("dead"), status_code=404)
        if not emailconf.mark(con, c["id"], emailconf.VIA_LINK, c["email"]):
            return HTMLResponse(views.confirm_page("already"))
    return HTMLResponse(views.confirm_page("done"))

# ---------- скачивание с сайта (L15): /descarca ----------


@router.get("/descarca")
def descarca(request: Request) -> Response:
    """302 на подписанный установщик последнего выпуска (GitHub Releases); API
    молчит — на страницу выпусков. Кто скачивал — строкой в журнале."""
    url, rel = download.target()
    with db.connect(immediate=True) as con:
        db.audit(con, "site", "download", None, f"{rel.asset if rel else 'pagina GitHub'} {web.ip(request)}")
    return RedirectResponse(url, status_code=302)


# ---------- ответ пациента по ссылке из SMS (Premium волна 2а): /r/<код> ----------

OG_IMAGE = pathlib.Path(__file__).resolve().parent / "assets" / "og-confirm.png"


def _page(body: str, status: int = 200) -> Response:
    return HTMLResponse(body, status_code=status, headers=plink_page.HEADERS)


def _dead(request: Request, lang: str) -> Response:
    """Кода нет (промах): безликая 404, сверх предела промахов с адреса — 429."""
    ip, ua = web.ip(request), request.headers.get("user-agent", "")
    if plink_page.miss_limited(ip, ua):
        return _page(plink_page.dead(lang, limited=True), 429)
    plink_page.note_miss(ip, ua)
    return _page(plink_page.dead(lang), 404)


@router.get(plink_page.PATH + "/{code}", response_class=HTMLResponse)
def link_page(request: Request, code: str, l: str = "") -> Response:  # noqa: E741 — имя параметра в адресе
    """Страница по ссылке из SMS. ⛔ Ничего не пишет — ни «открыто», ни счётчика в базе: её открывают роботы
    превью раньше человека. Ответ — только POST ниже."""
    now = datetime.now(timezone.utc)
    with db.connect() as con:
        row = plink.lookup(con, plink.norm(code))
    if row is None:
        return _dead(request, l)
    lang = plink_page.lang_of(l, row)
    if not plink.alive(row, now):
        return _page(plink_page.dead(lang), 404)
    return _page(plink_page.render(row, lang, now))


@router.post(plink_page.PATH + "/{code}", response_class=HTMLResponse)
def link_answer(request: Request, code: str, a: str = Form(""), t: str = Form(""), l: str = Form("")) -> Response:  # noqa: E741
    """Нажатие «Vin» / «Nu pot veni» (и смена ответа строкой ниже). Чужой Origin — 403 без записи; подпись формы
    не та (слепой POST, страница старше суток) — 403 и та же страница с новой подписью, ответ не записан."""
    if not auth.same_origin_post(request):
        return Response(status_code=403)
    if plink_page.post_limited(web.ip(request)):
        return _page(plink_page.dead(l, limited=True), 429)
    now = datetime.now(timezone.utc)
    code = plink.norm(code)
    with db.connect() as con:
        row = plink.lookup(con, code)
    if row is None:
        return _dead(request, l)
    lang = plink_page.lang_of(l, row)
    if not plink.alive(row, now):
        return _page(plink_page.dead(lang), 404)
    if not plink_page.mark_ok(code, t, now):
        return _page(plink_page.render(row, lang, now), 403)
    with db.connect(immediate=True) as con:
        row, _ = plink.respond(con, code, a, now)
    if row is None:                              # стёрт между чтением и записью (уборка задачей)
        return _page(plink_page.dead(lang), 404)
    return _page(plink_page.render(row, lang, now, just=row["state"] == a))


@router.get(plink_page.OG_PATH)
def link_og() -> Response:
    """Картинка карточки превью: одна на все ссылки и оба языка, вне пути кода, без cookie."""
    return Response(OG_IMAGE.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})
