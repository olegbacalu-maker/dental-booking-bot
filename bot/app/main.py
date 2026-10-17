"""Точка входа приложения.

Здесь осталось ровно то, что не принадлежит ни одному разделу: сборка
приложения и подключение модулей, посредники (шлюз режимов, опознание, потолок
тела), старт, `/health` для лаунчера и замороженная самозапись пациента
(`/` и `/chat`, живут с ботом).

Экраны живут в `modules/`, общее для них — в `core/`; вход и восстановление —
`modules/entry`, лицензия — `modules/license`, статика и значки —
`modules/assets`. Если сюда снова начнёт стекаться логика раздела, значит
разделу пора в свой модуль.
"""
import asyncio
import html
import logging
import os
import pathlib
import sys

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import db
from . import engine as eng
from . import paths
from . import update as upd
from .core import dbkey, demo
from .core import license as lic
from .core import sms_loop as sms
from .core.auth import (chat_session, current_user, host_allowed, request_user,
                        set_request_user)
from .core.layout import STATIC, msg_json, tg_configured
from .modules.assets import routes as assets
from .modules.doctors import api as doctors_api
from .modules.doctors import routes as doctors
from .modules.entry import api as entry_api
from .modules.entry import pages as entry_pages
from .modules.entry import recovery
from .modules.entry import routes as entry
from .modules.license import api as license_api
from .modules.license import routes as license_routes
from .modules.patients import api as patients_api
from .modules.patients import routes as patients
from .modules.migration import routes as migration
from .modules.qr import routes as qr
from .modules.schedule import api as schedule_api
from .modules.schedule import routes as schedule
from .modules.settings import api as settings_api
from .modules.settings import lan as settings_lan
from .modules.settings import routes as settings
from .modules.stats import api as stats_api
from .modules.stats import routes as stats

# ⛔ Без /docs, /redoc и /openapi.json (17.10): это карта всех адресов
# программы, и отдавалась она без входа — в том числе любому в сети клиники.
# Схему смотрят из исходников; в прогоне она никому не нужна.
app = FastAPI(title="DentPilot", docs_url=None, redoc_url=None, openapi_url=None)
log = logging.getLogger("web")

# Модули подключаются здесь и только здесь. Модуль знает про core, db и engine,
# но ничего не знает про main.py — иначе импорт замкнулся бы в круг.
app.include_router(patients.router)
app.include_router(migration.router)  # экран раздвоения (P2)
app.include_router(patients_api.router)   # JSON API раздела (DentPilot 2.0)
app.include_router(schedule.router)
app.include_router(schedule_api.router)  # JSON API раздела (DentPilot 2.0)
app.include_router(doctors.router)
app.include_router(doctors_api.router)    # JSON API раздела (DentPilot 2.0)
app.include_router(settings.router)
app.include_router(settings_api.router)   # JSON API раздела (DentPilot 2.0)
app.include_router(stats.router)
app.include_router(stats_api.router)      # JSON API раздела (DentPilot 2.0)
app.include_router(qr.router)
app.include_router(entry.router)          # вход, установка PIN, выход
app.include_router(entry_api.router)      # JSON-дверь: смена человека без перезагрузки
app.include_router(recovery.router)       # режим восстановления ключа
app.include_router(license_routes.router)
app.include_router(license_api.router)    # JSON API раздела (DentPilot 2.0)
app.include_router(assets.router)         # статика, значки, логотип


# ---------- посредники ----------
# ⚠️ Порядок исполнения ОБРАТЕН порядку объявления: Starlette ставит каждый
# новый посредник СНАРУЖИ прежних (`user_middleware.insert(0, …)`), поэтому
# запрос первым встречает объявленный последним. Шлюз режимов обязан быть
# внешним: в восстановлении и при битом профиле база не открыта, и отказ
# должен прозвучать раньше, чем кто-нибудь полезет в auth.json или в тело.
# Держит `test_structure` («шлюз — внешний посредник»): новый посредник —
# ВЫШЕ шлюза.

@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    """Отсекает гигантские POST-тела ДО того, как Starlette спулит multipart
    во временный файл (сам по себе роут-кап 25MB срабатывает уже после)."""
    if request.method == "POST":
        cl = request.headers.get("content-length", "")
        # в демо потолок ниже (core/demo.py): копия живёт час, место общее
        cap = demo.BODY_CAP if demo.on() else (26) * 1024 * 1024  # 25MB файла + запас
        if cl.isdigit() and int(cl) > cap:
            return Response("Payload too large", status_code=413)
    return await call_next(request)


@app.middleware("http")
async def _identify(request: Request, call_next):
    """Кто в этом запросе — один раз, для каркаса страницы.

    Сайдбар и верхний угол рисуются глубоко внутри `_shell`, куда запрос не
    приходит. Считаем здесь и кладём в контекст запроса; решение «пускать или
    нет» это НЕ подменяет — его принимает require() в самом маршруте.
    Только для /admin и /api: статике опознание не нужно, а auth.json
    читается с диска. ⚠️ /api — с 18.09 (C18): по тому же контексту летопись
    подписывает событие ИМЕНЕМ вошедшего (db.ACTOR_HOOK) и фиша решает,
    показывать ли директорские кнопки; без опознания действие через JSON
    молча записывалось бы как «recepție» — журнал доступа по 195-му врал бы
    об авторе. Держит test_patient_card.suite_actions.
    """
    journal = request.url.path.startswith(("/admin", "/api"))
    set_request_user(current_user(request) if journal else None)
    if journal:
        # запрос с ДРУГОГО устройства сети — строка «Verificarea legăturii»
        # на странице «Acces din rețea»; свой компьютер не записывается
        settings_lan.note_peer(request)
    return await call_next(request)


@app.middleware("http")
async def _own_host(request: Request, call_next):
    """Запрос пришёл по СВОЕМУ имени сервера, а не по чужому DNS (17.10).

    Закрывает DNS rebinding — страницу чужого сайта, чьё имя стало указывать
    на 127.0.0.1 и которая оттуда подбирала бы PIN или, на свежей установке,
    ставила бы первый (разбор — `auth.host_allowed`). Отказ — 421 и
    нейтральная страница с правильным адресом: до любого маршрута, куки и
    тела. Демо за шлюзом открывают по его имени — там проверки нет.
    ⚠️ Ниже шлюза режимов по правилу «шлюз — внешний посредник», и это не
    мешает: шлюз базу не трогает, а 421 на чужое имя даёт и он — сюда запрос
    доходит, если шлюз его пропустил.
    """
    if not (demo.on() or host_allowed(request)):
        return HTMLResponse(entry_pages.bad_host_page(request), status_code=421)
    return await call_next(request)


@app.middleware("http")
async def _recovery_gate(request: Request, call_next):
    """Шлюз режимов: битый профиль, восстановление, демо, лицензия.

    ⚠️ Отсекать надо ВСЕ адреса журнала, а не только главную: база не открыта
    вовсе, и любой маршрут упал бы пятисотой с невнятным следом в логе. Здесь
    же он получает внятный экран с полем для кода (`modules/entry/recovery`).
    ⚠️ `/health` намеренно НЕ трогаем: по нему лаунчер понимает, что сервер
    поднялся, — иначе окно программы не откроется и вводить код будет негде.
    Тот же шлюз держит и состояние «профиль клиники не читается»
    (eng.CONFIG_BROKEN): база в нём тоже не открыта, а вместо экрана с кодом —
    страница с объяснением, какой файл восстановить. Статика не отсекается:
    экран сам просит шрифты по /static/fonts/….
    """
    p = request.url.path
    if eng.CONFIG_BROKEN:
        if p.startswith("/admin"):
            return HTMLResponse(recovery.config_broken_page(), status_code=503)
        if p == "/" or p == "/chat":
            # каналу записи в этом состоянии отвечать нечем: конфиг (врачи,
            # услуги, часы) — это и есть то, из чего собирается диалог
            return Response(status_code=503)
    if recovery.active() and p.startswith("/admin") and not p.startswith("/admin/recover"):
        return RedirectResponse("/admin/recover", status_code=303)
    # Демо (core/demo.py): адресов, меняющих машину и учётки, нет — отказ
    # ЗДЕСЬ, до маршрута и разбора тела, одним кодом для страниц и JSON;
    # плитки хаба прячет тот же список. Пул таких процессов держит demo/gate.py.
    if demo.refuses(p):
        if p.startswith("/api/"):
            return msg_json(False, "demo_off", status=403)
        return RedirectResponse("/admin/settings?msg=demo_off", status_code=303)
    # Стена активации (L5): пустая картотека без годного файла — показывать
    # нечего, и каждый адрес журнала ведёт на страницу активации. Как у
    # восстановления выше; при льготе и режиме чтения стены нет (баннер).
    if lic.walled(p, request.method):
        return RedirectResponse("/admin/license", status_code=303)
    # Ворота лицензии (L4): пишущий запрос в состоянии readonly (или за стеной)
    # отказывает ЗДЕСЬ, до маршрутизации и разбора тела, одним кодом для
    # страниц и JSON. Чтение, печать, экспорт и бэкап остаются: замок на
    # записи, не на входе.
    if (code := lic.refuses(p, request.method)):
        if p.startswith("/api/"):
            return msg_json(False, code, status=423)
        back = "/admin/license" if code == lic.MISSING_CODE else "/admin"
        return RedirectResponse(f"{back}?msg={code}", status_code=303)
    return await call_next(request)


# ---------- старт ----------

@app.on_event("startup")
async def startup() -> None:
    """Старт по шагам. Порядок значим: два ранних выхода (битый профиль,
    нечитаемый ключ) оставляют базу НЕОТКРЫТОЙ, и всё, что ниже них, без базы
    не живёт."""
    # летопись подписывается ИМЕНЕМ вошедшего. Хук, а не импорт: db лежит ниже
    # слоя доступа, и прямой импорт замкнул бы круг db → core.auth → db
    db.ACTOR_HOOK = lambda: (request_user() or {}).get("name")
    # ⛔ Профиль клиники не читается (и .bak тоже): поднимаемся ЭКРАНОМ ОШИБКИ,
    # как в режиме восстановления, — база не открывается (ни миграций, ни
    # сида), Telegram не стартует, все адреса ведут на объяснение. Работать на
    # вшитой демо-клинике поверх настоящей картотеки нельзя: на «Dr. Elena
    # Rusu», которой в клинике нет, запишут живого человека, а чужой прайс
    # уйдёт пациенту как настоящий. Падать тоже нельзя (прайор 08-16): у
    # клиники это «программа не открывается», и рассказать, что чинить, некому.
    if eng.CONFIG_BROKEN:
        logging.getLogger("startup").error(
            "clinic.json не читается, запасного нет — экран ошибки: %s",
            eng.CONFIG_BROKEN)
        return
    seed_rows = _seed_rows()
    # ⭐ Ключ картотеки не читается (новый ПК, переустановка Windows, другая
    # учётка). Падать нельзя: у клиники не осталось бы НИ ОДНОГО экрана, чтобы
    # ввести код с листа восстановления, — программа просто не открывалась бы.
    # Поэтому поднимаемся в режиме восстановления: база не тронута, работает
    # ровно один экран, и все прочие адреса ведут на него.
    if dbkey.state() == dbkey.UNREADABLE:
        recovery.enter()
        logging.getLogger("startup").error(
            "ключ базы не читается на этой учётке Windows — режим восстановления")
        return
    await db.init(seed_rows)
    await entry.check_auth_file()
    # Лицензия (L3): файл, память, состояние — до первого запроса к воротам
    # (L4) и баннеру (L5). Облако и демо без ключа: внутри no-op.
    await lic.startup()
    # Автообновление файла (L13): суточный запрос к renew.url в фоне — как
    # upd.check_async ниже: старт не ждёт, отказ молчит, без файла с renew — no-op.
    lic.renew_async()
    # SMS-пакет (S5): очередь напоминаний — тот же приём, тик 60 с. Без файла
    # лицензии с `renew` (исходники, демо) — no-op; счёт из прошлого запуска
    # читается до первого тика, чтобы страницы знали, есть ли пакет.
    await sms.startup()
    sms.sms_async()
    await _backfill_ids()
    if paths.is_frozen():
        _sweep_previous_version()
    # Демо (core/demo.py) живёт в контейнере без GitHub и без реестра: ни
    # сверки версии, ни запроса релизов — обновление не его дело.
    if not demo.on():
        _watch_releases()
    _check_disk_encryption()
    _start_telegram()


def _seed_rows() -> list:
    try:
        return eng.build_seed_rows()
    except Exception as e:  # noqa: BLE001 — демо-наполнение НЕ должно валить старт
        logging.getLogger("startup").warning("build_seed_rows failed: %r", e)
        return []


async def _backfill_ids() -> None:
    """v1.7.1: старым записям проставляются стабильные ключи по текущему конфигу;
    идемпотентно (только NULL), на каждом старте — дёшево и самозалечивается."""
    doc_map = {name: k for k, name in eng.DOCTORS.items()}
    svc_map = {}
    for k, v in eng.SERVICES.items():
        svc_map[v["ro"]] = k
        svc_map[v["ru"]] = k
    await db.backfill_ids(doc_map, svc_map)


def _sweep_previous_version() -> None:
    """⭐ Прошлая версия убирается ЗДЕСЬ, а не батником обновления (08-10,
    находка аудита). Батник стирал `.old.exe`, как только новый файл ПОЯВЛЯЛСЯ
    на диске, — а появиться и запуститься разное: битая докачка, прошедшая
    проверку; антивирус, съевший exe после подмены; несовместимый бинарник. На
    диске не оставалось ни одной рабочей копии, и клиника получала мёртвые
    ярлыки в начале смены. Теперь удаление — доказательство работоспособности:
    сюда доходят, только когда модули загрузились и база ОТКРЫЛАСЬ.
    ⚠️ Именно в startup приложения, а не в лаунчере: у лаунчера две ветки
    (окно и браузерный режим), и уборка в одной из них не работала во второй —
    поймано проверкой на собранном exe, тесты исходников эту ветку не видят
    вовсе (`frozen` там ложь)."""
    try:
        for old in pathlib.Path(sys.executable).resolve().parent.glob("*.old.exe"):
            old.unlink(missing_ok=True)
            log.warning("прошлая версия убрана: %s", old.name)
    except OSError as e:  # noqa: BLE001 — уборка не имеет права ронять старт
        log.warning("прошлая версия не убрана (%r)", e)
    # копия exe, из которой шёл сторож перезапуска (11.10): убирается тем же
    # доказательством работоспособности; ещё жив (окно гаснет через секунду
    # после нашего старта) — не вышло, уберём при следующем старте
    try:
        watch = upd.work_dir() / upd._WATCH_EXE
        if watch.exists():
            watch.unlink()
            log.warning("копия сторожа перезапуска убрана: %s", watch.name)
    except OSError:
        pass


def _watch_releases() -> None:
    upd.sync_uninstall_version()   # версия в «Программах и компонентах»
    # ⚠️ `DENTART_UPDATE_CHECK=off` — тест-хук харнесса (03.10): три сотни
    # тестовых серверов за прогон спрашивали GitHub при каждом старте и
    # выедали анонимную квоту 60 в час — у канарейки на той же машине
    # проверка обновлений потом шла запасным путём (02.10: 0 из 60).
    if os.environ.get("DENTART_UPDATE_CHECK", "").strip().lower() != "off":
        upd.check_async()


def _check_disk_encryption() -> None:
    # закон 195: диск с картотекой обязан быть зашифрован — программа
    # проверяет сама, а не верит подписанному акту (core/bitlocker.py)
    from .core import bitlocker
    from .core.storage import _data_dir
    bitlocker.check_async(_data_dir())


def _start_telegram() -> None:
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if token:
        from . import telegram as tg

        async def _tg_guard() -> None:
            try:
                await tg.run(token)
            except Exception as e:  # noqa: BLE001 — веб-чат должен жить при любой ошибке TG
                print(f"Telegram adapter FAILED: {e!r} — web chat keeps running")

        asyncio.create_task(_tg_guard())
        print("Telegram adapter: starting (token present)")
    else:
        print("TELEGRAM_TOKEN not set — Telegram adapter disabled (web chat only)")


@app.get("/health")
async def health() -> dict:
    # "app" = отпечаток для single-instance guard в desktop.py:
    # чужой сервис с {"ok":true} на нашем порту не должен сойти за нас
    return {"ok": True, "app": "dentpilot", "version": eng.APP_VERSION}


# ---------- самозапись пациента (лендинг + веб-чат) ----------
# ЗАМОРОЖЕНА вместе с Telegram (08-08): это тот же канал «пациент записывает
# себя сам», от которого клиники отказались. Живёт ровно у тех, у кого настроен
# бот (tg_configured) — интерфейс журнала и так весь под этим выключателем.
# 404, а не заглушка: канала у этой клиники нет, и страница-извинение только
# сбивала бы с толку того, кто открыл старую ссылку.

@app.get("/", response_class=HTMLResponse)
async def index() -> Response:
    if not tg_configured():
        return Response(status_code=404)
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace("{{CLINIC_NAME}}",
                                     html.escape(eng.CLINIC_NAME)))


@app.post("/chat")
async def chat(payload: dict):
    """⛔ Ключ сессии НЕ приходит от клиента (см. core.auth.chat_session): для
    движка session_key — это удостоверение пациента, и присланный `manual:…`
    открывал бы чужие записи. Сервер выдаёт свой, подписанный; клиент только
    возвращает его следующим запросом."""
    if not tg_configured():
        return Response(status_code=404)
    sid, token = chat_session(str(payload.get("session") or ""))
    msg = str(payload.get("message") or "/start")[:500]
    s = eng.get_session(sid)
    texts, buttons = await eng.handle(s, sid, msg)
    return {"messages": [{"text": x} for x in texts], "buttons": buttons,
            "session": token}
