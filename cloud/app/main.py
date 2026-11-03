"""DentPilot Cloud — сервер лицензий и кабинет клиники (docs/dentpilot-2/cloud.md).

Отдельная программа: ни одного импорта из bot/. Общее с движком — контракт
файла лицензии и фикстуры tests/fixtures/license/.

Здесь только сборка (03.11, разнос main.py): посредники, startup, /health и
подключение роутеров. Маршруты — по разделам:
  routes_program    /v1/* — API программы клиники (Bearer-токен)
  routes_pay        /plata/<ключ>, callback maib, /pay/ok|fail
  routes_cont       /cont*, /auth/google* — кабинет клиники
  routes_admin      /, /admin* — админка, кроме платежей
  routes_admin_pay  /admin/payments*, нота и карта из карточки
  routes_public     /robots.txt, /proba, /confirma/<ключ>, /descarca
  web               общие помощники роутеров (зовутся `web.имя`)
Новый маршрут — строка в tests/test_routes.py::SNAPSHOT. ⛔ main не импортирует
никто (tests/test_routes.py): main подключает роутеры, обратный импорт замкнул бы круг.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import (auth, config, contlink, db, license, logmask, robots, smsmd, routes_admin, routes_admin_pay, routes_cont,
               routes_pay, routes_program, routes_public)

APP_VERSION = "0.1.0"
log = logging.getLogger("cloud")
# секрет уведомлений sms.md стоит в пути запроса — журнал доступа его не видит (logmask.py)
logmask.install()
app = FastAPI(title="DentPilot Cloud", docs_url=None, redoc_url=None)


@app.middleware("http")
async def _cont_program_only(request: Request, call_next):
    """Вход кнопкой программы (27.10, contlink.py) — одна клиника: разделы кабинета обо всех его
    клиниках (contlink.DENY) закрыты ему целиком, до маршрута. Вид куки читается без базы."""
    if contlink.closed(request.url.path) and auth.current_clinic_id(request):
        return RedirectResponse(f"/cont?msg={contlink.DENIED_MSG}", status_code=303)
    return await call_next(request)


# ⚠️ NoIndex — последним: Starlette первым исполняет добавленный последним, и ранний ответ
# посредника выше без него ушёл бы без заголовка
# каждый ответ облака — мимо поисковой выдачи; почему заголовком, а не robots.txt, — robots.py
app.add_middleware(robots.NoIndex)


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


# ---------- маршруты — по роутерам (03.11, разнос main.py) ----------
# порядок подключения не важен: один адрес ловит один маршрут (tests/test_routes.py)
app.include_router(routes_program.router)
app.include_router(routes_pay.router)
app.include_router(routes_cont.router)
app.include_router(routes_admin.router)
app.include_router(routes_admin_pay.router)
app.include_router(routes_public.router)
