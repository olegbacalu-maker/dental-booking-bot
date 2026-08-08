"""Точка входа приложения.

Здесь осталось ровно то, что не принадлежит ни одному разделу: сборка
приложения и подключение модулей, старт (миграции, демо-наполнение, адаптер
Telegram), вход в журнал, отдача статики и эндпоинт веб-чата.

Экраны живут в `modules/`, общее для них — в `core/`. Если сюда снова начнёт
стекаться логика раздела, значит разделу пора в свой модуль.
"""
import asyncio
import hmac
import html
import logging
import os
import re
import urllib.parse
from datetime import datetime

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import brand
from . import db
from . import engine as eng
from . import paths
from . import update as upd
from .core.auth import (ADMIN_KEY, FAIL_DELAY, PERM_SETTINGS, _guard, _pin_rec,
                        _secret, _set_auth_cookie, _setup_allowed, _write_pin,
                        auth_file_fp, current_user, find_user, lock_left,
                        note_fail, note_ok, remember_auth_file, request_user,
                        require, set_request_user, set_tamper_alert, verify_pin)
from .core.layout import (LOGIN_TMPL, SETUP_TMPL, STATIC, _asset,
                          tg_configured)
from .modules.doctors import routes as doctors
from .modules.patients import routes as patients
from .modules.qr import routes as qr
from .modules.schedule import routes as schedule
from .modules.settings import routes as settings
from .modules.stats import routes as stats

app = FastAPI(title="DentPilot")
log = logging.getLogger("web")

# Модули подключаются здесь и только здесь. Модуль знает про core, db и engine,
# но ничего не знает про main.py — иначе импорт замкнулся бы в круг.
app.include_router(patients.router)
app.include_router(schedule.router)
app.include_router(doctors.router)
app.include_router(settings.router)
app.include_router(stats.router)
app.include_router(qr.router)








@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    """Отсекает гигантские POST-тела ДО того, как Starlette спулит multipart
    во временный файл (сам по себе роут-кап 25MB срабатывает уже после)."""
    if request.method == "POST":
        cl = request.headers.get("content-length", "")
        if cl.isdigit() and int(cl) > (26) * 1024 * 1024:  # 25MB файла + запас
            return Response("Payload too large", status_code=413)
    return await call_next(request)


@app.middleware("http")
async def _identify(request: Request, call_next):
    """Кто в этом запросе — один раз, для каркаса страницы.

    Сайдбар и верхний угол рисуются глубоко внутри `_shell`, куда запрос не
    приходит. Считаем здесь и кладём в контекст запроса; решение «пускать или
    нет» это НЕ подменяет — его принимает require() в самом маршруте.
    Только для /admin: статике опознание не нужно, а auth.json читается с диска.
    """
    set_request_user(current_user(request)
                     if request.url.path.startswith("/admin") else None)
    return await call_next(request)























# Логин НЕОБЯЗАТЕЛЕН: пароль у каждого свой (это стережёт pin_free), и
# заставлять регистратуру набирать ещё и id — трение десятки раз в день. Поле
# всё же есть: врачу с телефона вход по одному паролю неочевиден, а в клинике
# с одинаковыми привычками кто-нибудь однажды захочет войти именно «как я».
PIN_INPUT = ("<input type='text' name='uid' placeholder='ID (opțional)' "
             "autocomplete='username' maxlength='20' "
             "style='text-align:center;font-size:15px'>"
             "<input type='password' name='password' placeholder='PIN' autofocus required "
             "inputmode='numeric' pattern='[0-9]*' maxlength='6' "
             "style='text-align:center;font-size:28px;letter-spacing:12px'>")
PASS_INPUT = "<input type='password' name='password' placeholder='Parola' autofocus required>"
PIN_HINT = ("<div style='color:#889;font-size:12px'>PIN uitat? Închideți programul și "
            "ștergeți fișierul <b>data\\auth.json</b> — la pornire veți seta un PIN nou.</div>")










































@app.on_event("startup")
async def startup() -> None:
    if not db.IS_SQLITE and not ADMIN_KEY:
        # Postgres = серверный режим: с v1.6.0 в журнале мед-данные и файлы,
        # fail-open без ключа недопустим — падаем громко, а не открываемся тихо
        raise RuntimeError("ADMIN_KEY is required for the Postgres edition — set it in .env")
    # летопись подписывается ИМЕНЕМ вошедшего. Хук, а не импорт: db лежит ниже
    # слоя доступа, и прямой импорт замкнул бы круг db → core.auth → db
    db.ACTOR_HOOK = lambda: (request_user() or {}).get("name")
    try:
        seed_rows = eng.build_seed_rows()
    except Exception as e:  # noqa: BLE001 — демо-наполнение НЕ должно валить старт
        logging.getLogger("startup").warning("build_seed_rows failed: %r", e)
        seed_rows = []
    await db.init(seed_rows)
    await _check_auth_file()
    # v1.7.1: старым записям проставляются стабильные ключи по текущему конфигу;
    # идемпотентно (только NULL), на каждом старте — дёшево и самозалечивается
    doc_map = {name: k for k, name in eng.DOCTORS.items()}
    svc_map = {}
    for k, v in eng.SERVICES.items():
        svc_map[v["ro"]] = k
        svc_map[v["ru"]] = k
    await db.backfill_ids(doc_map, svc_map)
    upd.sync_uninstall_version()   # версия в «Программах и компонентах»
    upd.check_async()
    if db.IS_SQLITE:
        # закон 195: диск с картотекой обязан быть зашифрован — программа
        # проверяет сама, а не верит подписанному акту (core/bitlocker.py)
        from .core import bitlocker
        from .core.storage import _data_dir
        bitlocker.check_async(_data_dir())
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


_ASSET_MIME = {"css": "text/css", "js": "application/javascript"}


@app.get("/static/{kind}/{name}")
async def static_asset(kind: str, name: str) -> Response:
    """Оформление и поведение журнала. Кеш вечный намеренно: адрес несёт версию
    программы (?v=…), поэтому после обновления браузер запросит новый файл, а
    между обновлениями не будет тянуть их на каждую автоперезагрузку страницы —
    а она происходит раз в 12 секунд на каждом открытом экране.

    Отдаём только css и js по строгому шаблону имени: каталог статики лежит
    внутри сборки рядом с профилем клиники, и вытащить оттуда что-то ещё через
    этот адрес быть не должно."""
    mime = _ASSET_MIME.get(kind)
    if not mime or not re.fullmatch(rf"[a-z0-9_-]+\.{kind}", name):
        return Response(status_code=404)
    try:
        text = _asset(kind, name)
    except OSError:
        log.error("не читается %s/%s — страница останется без него", kind, name)
        return Response(status_code=404)
    cache = ("public, max-age=31536000, immutable" if paths.is_frozen()
             else "no-cache")
    return Response(text, media_type=mime,
                    headers={"Cache-Control": cache})


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Тот же знак во вкладке браузера. Браузер сам просит /favicon.ico, поэтому
    один роут закрывает все страницы, включая печатные."""
    return Response(brand.mark_svg(None), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


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
    if not tg_configured():
        return Response(status_code=404)
    sid = str(payload.get("session_id") or "").strip()[:64]
    if not sid:
        return {"messages": [{"text": "session_id required"}], "buttons": []}
    msg = str(payload.get("message") or "/start")[:500]
    s = eng.get_session(sid)
    texts, buttons = await eng.handle(s, sid, msg)
    return {"messages": [{"text": x} for x in texts], "buttons": buttons}


# ---------- домашняя страница журнала: сводка + карточки врачей ----------

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(next: str = "/admin", err: str = "", s: str = ""):
    if not _secret():
        return RedirectResponse("/admin", status_code=303)
    pin_mode = _pin_rec() is not None
    if err == "lock":
        # `s` — срок из редиректа сразу после неудачи; lock_left() свежее, но
        # к моменту перезагрузки страницы уже мог утечь до нуля
        left = lock_left() or (int(s) if s.isdigit() else 0)
        wait = f"{left} sec." if left < 60 else f"{(left + 59) // 60} min."
        err_html = ("<div class='err'>Prea multe încercări greșite. "
                    f"Încercați peste {wait}</div>")
    elif err:
        err_html = ("<div class='err'>PIN greșit</div>" if pin_mode
                    else "<div class='err'>Parolă greșită</div>")
    else:
        err_html = ""
    nxt = next if next.startswith("/admin") else "/admin"
    return (LOGIN_TMPL.replace("__CLINIC__", html.escape(eng.CLINIC_NAME))
            .replace("__ERR__", err_html).replace("__NEXT__", html.escape(nxt))
            .replace("__INPUT__", PIN_INPUT if pin_mode else PASS_INPUT)
            .replace("__HINT__", PIN_HINT if pin_mode else ""))


@app.post("/admin/login")
async def admin_login(password: str = Form(...), uid: str = Form(""),
                      next_url: str = Form("/admin", alias="next")):
    target = next_url if next_url.startswith("/admin") else "/admin"
    nxt = urllib.parse.quote(target, safe="")
    if (left := lock_left()) > 0:
        return RedirectResponse(
            f"/admin/login?err=lock&s={left}&next={nxt}", status_code=303)
    pw = password.strip()
    who = None
    if _pin_rec():
        # логин необязателен: пароль у каждого свой (pin_free это стережёт), и
        # заставлять регистратуру набирать ещё и id — трение на ровном месте.
        # Указан явно — сверяем только с ним: так на телефоне у врача вход
        # предсказуем, даже если однажды пароли всё-таки совпадут.
        who = verify_pin(pw, uid=uid.strip()[:32])
        ok = who is not None
    else:
        ok = bool(ADMIN_KEY) and hmac.compare_digest(pw, ADMIN_KEY)
    if ok:
        note_ok()
        if who is not None:
            # verify_pin мог молча переписать файл (миграция v1→v2, доливка
            # sid) — обновляем отпечаток, иначе следующий старт увидит «взлом»
            await remember_auth_file()
        # кука ставится ПОСЛЕ verify_pin: миграция v1→v2 меняет ключ подписи,
        # а запись пользователя — свой sid
        return _set_auth_cookie(RedirectResponse(target, status_code=303), who)
    lock = note_fail()
    # asyncio.sleep, а не time.sleep: у настольного издания один процесс на всю
    # клинику, и блокирующая пауза заморозила бы журнал остальным
    await asyncio.sleep(FAIL_DELAY)
    q = f"err=lock&s={lock}" if lock else "err=1"
    return RedirectResponse(f"/admin/login?{q}&next={nxt}", status_code=303)






async def _check_auth_file() -> None:
    """Сигнализация auth.json: файл переписали или удалили ВНЕ программы.

    Это след, а не замок (см. пояснение в core/auth.py): отпечаток файла живёт
    в базе, расхождение при старте попадает в ленту и висит баннером у
    директора, пока тот не подтвердит. Ложная тревога недопустима — поэтому
    каждый маршрут, пишущий файл сам, обязан звать remember_auth_file().
    """
    if not db.IS_SQLITE:
        return                       # у облачного издания файла PIN нет
    if (alert := await db.get_meta("auth_alert")):
        set_tamper_alert(alert)      # непогашенное предупреждение живёт и после рестарта
    now_fp = auth_file_fp()
    stored = await db.get_meta("auth_fp")
    if stored is None:
        # первый запуск с этой проверкой: судить прошлое не по чему
        await db.set_meta("auth_fp", now_fp)
        return
    if stored == now_fp:
        return
    when = datetime.now(eng.TZ).strftime("%d.%m.%Y %H:%M")
    what = ("șters" if not now_fp else "modificat")
    text = (f"Fișierul de acces (auth.json) a fost {what} în afara programului "
            f"— sesizat la pornirea din {when}")
    await db.log_clinic_event("auth_tamper", text)
    await db.set_meta("auth_alert", text)
    await db.set_meta("auth_fp", now_fp)   # один сигнал на одно вмешательство
    set_tamper_alert(text)
    logging.getLogger("auth").warning("auth.json tampered: %s", what)


@app.post("/admin/security/ack")
async def security_ack(request: Request):
    """Погасить предупреждение. Только директор: остальные не могут ни оценить
    «это был техник», ни сменить PIN-ы — им баннер и не показывается."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    await db.del_meta("auth_alert")
    set_tamper_alert("")
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/logout")
async def admin_logout():
    """Выход. Кука снимается у браузера; серверных сессий у нас нет, поэтому
    больше ничего гасить не нужно."""
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie("admin_auth")
    return resp


@app.get("/admin/setup", response_class=HTMLResponse)
async def admin_setup_page(err: str = ""):
    if not _setup_allowed():
        return RedirectResponse("/admin", status_code=303)
    err_html = "<div class='err'>PIN-urile nu coincid sau nu au 4–6 cifre</div>" if err else ""
    return (SETUP_TMPL.replace("__CLINIC__", html.escape(eng.CLINIC_NAME))
            .replace("__ERR__", err_html))




@app.post("/admin/setup")
async def admin_setup(pin1: str = Form(...), pin2: str = Form(...)):
    if not _setup_allowed():
        return RedirectResponse("/admin", status_code=303)
    p1, p2 = pin1.strip(), pin2.strip()
    if p1 != p2 or not p1.isdigit() or not (4 <= len(p1) <= 6):
        return RedirectResponse("/admin/setup?err=1", status_code=303)
    _write_pin(p1)
    await remember_auth_file()
    return _set_auth_cookie(RedirectResponse("/admin", status_code=303),
                            find_user("clinic"))


@app.post("/admin/pin/change")
async def admin_pin_change(request: Request, old_pin: str = Form(...),
                           new1: str = Form(...), new2: str = Form(...)):
    if (deny := _guard(request)) is not None:
        return deny
    if not _pin_rec():
        return RedirectResponse("/admin/settings/security?msg=bad_pin", status_code=303)
    # своё сообщение, а не bad_pin: «старый PIN неверен» при блокировке — ровно
    # тот случай, когда экран врёт, и человек начинает перебирать верный PIN
    if lock_left() > 0:
        return RedirectResponse("/admin/settings/security?msg=lock_pin", status_code=303)
    # форма смены — второй оракул для того же PIN, поэтому считает те же неудачи
    if (who := verify_pin(old_pin.strip())) is None:
        note_fail()
        await asyncio.sleep(FAIL_DELAY)
        return RedirectResponse("/admin/settings/security?msg=bad_pin", status_code=303)
    note_ok()
    n1, n2 = new1.strip(), new2.strip()
    if n1 != n2 or not n1.isdigit() or not (4 <= len(n1) <= 6):
        return RedirectResponse("/admin/settings/security?msg=bad_pin", status_code=303)
    # роль и id берутся у вошедшего: смена своего PIN не должна никого повышать
    _write_pin(n1, role=who.get("role", "director"), uid=who.get("id", "clinic"))
    await remember_auth_file()
    return _set_auth_cookie(
        RedirectResponse("/admin/settings/security?msg=ok_pin", status_code=303),
        find_user(who.get("id", "clinic")))


























# ---------- настройки клиники ----------





















# ---------- статистика ----------





# ---------- экспорт CSV ----------



# ---------- поиск пациента ----------



















































# ---------- общая сетка: все врачи ----------





# ---------- страница одного врача ----------



# ---------- раздел «Medici»: карточка врача (v1.9.0) ----------
#
# Каталог врачей живёт в clinic.json (Setări + hot-reload), в БД — только
# doctor_id и снапшот имени (решение PLAN_DB_V17). Этот раздел = единственное
# место правки врачей: таблица из Setări убрана, чтобы не было двух источников.















































# ---------- действия ----------











# ---------- печатный QR для пациентов ----------



# ---------- QR для демо ----------



