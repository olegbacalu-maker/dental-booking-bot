"""Публичные страницы без входа (03.11, из main.py): robots.txt, форма пробного /proba,
страница подтверждения ящика из письма (/confirma/<ключ>), скачивание программы /descarca."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import auth, db, download, emailconf, robots, trial, views, web

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
    with db.connect(immediate=True) as con:
        outcome, clinic = trial.submit(con, f, ip)
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
