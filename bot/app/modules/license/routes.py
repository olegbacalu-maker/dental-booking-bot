"""Маршруты лицензии со своей вёрсткой: активация (L5), заявка и код (26.09),
«Verifică acum» (L13), переход к оплате (02.10)."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ...core import license as lic
from ...core.auth import PERM_SETTINGS, _guard, can, current_user, require
from ...core.layout import license_page, license_pay_page

router = APIRouter()


@router.get("/admin/license", response_class=HTMLResponse)
async def license_view(request: Request, msg: str = "") -> Response:
    """Страница активации (L5): состояние, импорт файла, контакты. Вход нужен,
    право директора — только на импорт: регистратура видит состояние и
    просьбу позвать директора, а не петлю no_access → стена → no_access."""
    if (deny := _guard(request)) is not None:
        return deny
    me = current_user(request)
    return HTMLResponse(license_page(msg, director=me is not None and can(me, PERM_SETTINGS),
                                     walled=lic.walled("/admin", "GET")))


@router.post("/admin/license")
async def license_install(request: Request, file: UploadFile | None = File(None),
                          text: str = Form(""), terms: str = Form("")) -> Response:
    """Файл из поля или вставленный текст → проверка → license.json → перечитать.

    Без галочки условий файл не принимается: активация и есть заключение
    договора (п. 1 условий), и летопись пишет имя того, кто её поставил.
    `required` у галочки держит браузер; этот отказ — для всего остального."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if terms != "1":
        return RedirectResponse(f"/admin/license?msg={lic.TERMS_CODE}", status_code=303)
    raw = b""
    if file is not None and file.filename:
        raw = await file.read()
    if not raw.strip():
        raw = text.encode("utf-8")
    me = current_user(request)
    code = await lic.install(raw.decode("utf-8", "replace"),
                             actor=(me or {}).get("name") or "director")
    if code:
        return RedirectResponse(f"/admin/license?msg={code}", status_code=303)
    return RedirectResponse("/admin?msg=license_ok", status_code=303)


@router.post("/admin/license/request")
async def license_request(request: Request, name: str = Form(""), idno: str = Form(""),
                          contact_name: str = Form(""), email: str = Form(""),
                          phone: str = Form(""), terms: str = Form("")) -> Response:
    """Активация без файла (26.09): заявка на пробный уходит на сервер лицензий,
    и программа активируется сама, как только файл выдан. Галочка условий — та
    же, что у импорта файла: без неё заявка не уходит, с ней летопись пишет,
    кто принял условия. Поля проверяет сервер (одни правила с формой /proba);
    его отказ страница показывает словами сервера."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if terms != "1":
        return RedirectResponse(f"/admin/license?msg={lic.TERMS_CODE}", status_code=303)
    me = current_user(request)
    code = await lic.request_trial(
        {"name": name, "idno": idno, "contact_name": contact_name, "email": email, "phone": phone},
        actor=(me or {}).get("name") or "director")
    if code == "license_ok":
        return RedirectResponse("/admin?msg=license_ok", status_code=303)
    return RedirectResponse(f"/admin/license?msg={code}", status_code=303)


@router.post("/admin/license/verify")
async def license_verify(request: Request, code: str = Form("")) -> Response:
    """Новый компьютер той же клиники (26.09): код, который сервер прислал на её
    e-mail в ответ на повтор заявки. Галочки здесь нет: код бывает только у заявки,
    а её маршрут выше без галочки не отправит — договор принят ею, и летопись
    пишет, кто активировал этот компьютер."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    me = current_user(request)
    result = await lic.verify_code(code, actor=(me or {}).get("name") or "director")
    if result == "license_ok":
        return RedirectResponse("/admin?msg=license_ok", status_code=303)
    return RedirectResponse(f"/admin/license?msg={result}", status_code=303)


@router.post("/admin/license/renew")
async def license_renew(request: Request) -> Response:
    """Кнопка «Verifică acum» (L13): тот же запрос к renew.url, что суточный, —
    только сейчас и с ответом словами. Право директора, как у импорта; в
    белом списке ворот: новый файл нужен именно в режиме чтения."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    outcome = await lic.renew_once()
    if outcome == lic.RENEWED:
        return RedirectResponse("/admin?msg=license_renewed", status_code=303)
    return RedirectResponse(f"/admin/license?msg={lic.RENEW_CODES[outcome]}", status_code=303)


@router.get("/plata/{ticket}")
async def license_pay(ticket: str) -> Response:
    """«Plătește acum» (02.10): ссылка из баннера и со страницы лицензии.

    ⭐ Приходит СИСТЕМНЫМ браузером и без куки входа: окно программы отдаёт
    target=_blank браузеру Windows, а вход у них разный. Поэтому маршрут вне
    /admin и без `_guard` — пропуском служит ключ в адресе (`lic.pay_ticket`),
    который рисуют только директору. Отсюда — запрос страницы оплаты у сервера,
    выдавшего файл, и переход туда; неудача — страница словами в том же браузере.
    ⚠️ GET меняет только частоту запроса файла, а у сервера заводит (или отдаёт
    ту же) ссылку на сутки: ни денег, ни данных клиники он не трогает."""
    if not lic.applies() or not lic.pay_ticket_ok(ticket):
        return HTMLResponse(license_pay_page("ticket"), status_code=404)
    outcome, url = await lic.pay_link()
    if outcome == lic.PAY_OK:
        return RedirectResponse(url, status_code=303)
    return HTMLResponse(license_pay_page(outcome), status_code=503)
