"""Шлюз живого демо: своя копия демо-клиники каждому посетителю сайта (01.10).

Как устроено. Шлюз — маленький HTTP-прокси (Starlette + httpx) перед ПУЛОМ
обычных процессов программы: `uvicorn app.main:app`, издание SQLite, как у
клиники, с `DENTART_DEMO=1` (core/demo.py). Слот = процесс + своя папка
данных + свой случайный ADMIN_KEY. Посетитель получает куку `dp_demo` со
слотом и случайной меткой; шлюз сам входит в слот ключом и подставляет куку
входа программы в каждый проксируемый запрос — посетитель ключа не знает и
экрана входа не видит. Через DEMO_TTL_MIN (60) слот сбрасывается: процесс
гасится, папка заменяется копией ШАБЛОНА, засев раскладывается от «сейчас»
(demo/seed.py), процесс поднимается заново. Сброс делает фоновый цикл,
поэтому свободный слот почти всегда тёплый; когда тёплых нет, посетитель
ждёт сброс истёкшего (~5 с) или видит страницу «locurile sunt ocupate».

Шаблон (`DEMO_DATA/template`) собирается при старте шлюза: папка с
`clinic.json` и фото врачей, в которой программа запускается ОДИН раз —
создаёт схему и миграции — и гасится. Так засев всегда ложится на схему
ровно той версии, которая работает; ⚠️ `seed.py` знает колонки, и при смене
схемы ему тоже нужна правка — сторож в `tests/test_demo.py::suite_seed`.

Безопасность, коротко: программа за шлюзом слушает только 127.0.0.1; ключи
слотов случайные и живут в памяти процесса; наружу уходит только кука шлюза
(HttpOnly, SameSite=Lax, Secure за туннелем); адресов, меняющих машину и
учётки, в демо-режиме нет — это решает сама программа (core/demo.py), шлюз
их не дублирует и обслуживает только свои `/demo/…`. Тело запроса — не
больше BODY_CAP, как у программы в демо. Заголовок Host едет к программе
НЕТРОНУТЫМ: её проверка Origin на изменяющих запросах сравнивает его с
Origin браузера, и подменённый на 127.0.0.1 Host отказал бы каждому POST.

Запуск: `python -m demo.gate` из папки, где лежат `demo/` и `bot/` (репозиторий
или /srv в образе). Переменные — все с запасным значением, см. `_env` ниже.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import seed as demo_seed

HERE = pathlib.Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


APP_DIR = pathlib.Path(_env("DEMO_APP_DIR", str(HERE.parent / "bot")))   # где пакет `app`
PYTHON = _env("DEMO_PYTHON", sys.executable)
DATA = pathlib.Path(_env("DEMO_DATA", str(HERE.parent / "sandbox" / "demo-data")))
SLOTS = int(_env("DEMO_SLOTS", "6"))
TTL = timedelta(minutes=int(_env("DEMO_TTL_MIN", "60")))
PORT = int(_env("DEMO_PORT", "8090"))
HOST = _env("DEMO_HOST", "127.0.0.1")
CHILD_PORT = int(_env("DEMO_CHILD_PORT", "9101"))
SITE_URL = _env("DEMO_SITE_URL", "https://dentpilot.md")
SECURE_COOKIE = _env("DEMO_SECURE_COOKIE", "1") == "1"
BODY_CAP = 8 * 1024 * 1024
COOKIE = "dp_demo"
SWEEP_S = 20           # как часто фоновый цикл смотрит на истёкшие слоты
# Свободный слот, засеянный давно, пересевается: «сейчас» в его данных
# (кто в кабинете, кто ждёт) уехало бы от часов посетителя на полчаса
REFRESH = timedelta(minutes=30)
BOOT_TIMEOUT_S = 90    # сколько ждать /health дочернего процесса
# Переменные машины разработчика, которым нечего делать в слоте: токен бота
# запустил бы polling с демо-сервера, ключи лицензии — стену активации.
_STRIP_ENV = ("TELEGRAM_TOKEN", "DENTART_UPDATE_TOKEN", "DENTART_CHANNEL",
              "DENTART_LICENSE_KEYS", "DENTART_LICENSE_SERVER", "DENTART_ENV_FILE",
              "DENTART_LAN", "DENTART_PORT", "DENTART_TOKEN_UNREADABLE",
              "DENTART_SCAN_FAKE", "DENTART_SPLIT_SOURCE", "FAKECLOCK_FILE")
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailer", "transfer-encoding", "upgrade"}

log = logging.getLogger("demo")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Slot:
    """Один процесс программы со своей папкой данных и своим ключом."""

    def __init__(self, i: int) -> None:
        self.i = i
        self.port = CHILD_PORT + i
        self.dir = DATA / f"s{i}"
        self.proc: subprocess.Popen | None = None
        self.key = ""
        self.auth = ""        # кука входа программы — её подставляет шлюз
        self.owner = ""       # метка посетителя из куки dp_demo
        self.until: datetime | None = None
        self.ready = False
        self.seeded_at = _now()
        self.lock = asyncio.Lock()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def expired(self, now: datetime) -> bool:
        return bool(self.owner) and self.until is not None and now >= self.until


slots: list[Slot] = [Slot(i) for i in range(SLOTS)]
assign_lock = asyncio.Lock()
client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0),
                           limits=httpx.Limits(max_connections=64))


# ---------- дочерний процесс ----------

def _child_env(d: pathlib.Path, key: str) -> dict:
    env = dict(os.environ)
    for k in _STRIP_ENV:
        env.pop(k, None)
    env.update({
        "CLINIC_CONFIG": str(d / "clinic.json"),
        "DATABASE_URL": f"sqlite:///{(d / 'data' / 'dental.db').as_posix()}",
        "DENTART_DATA_DIR": str(d),
        "ADMIN_KEY": key,
        "DENTART_DEMO": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _spawn(d: pathlib.Path, port: int, key: str) -> subprocess.Popen:
    (d / "data").mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning", "--no-access-log"],
        cwd=str(APP_DIR), env=_child_env(d, key))


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


async def _wait_health(base: str, proc: subprocess.Popen) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < BOOT_TIMEOUT_S:
        if proc.poll() is not None:
            raise RuntimeError(f"процесс программы завершился с кодом {proc.returncode}")
        try:
            r = await client.get(base + "/health", timeout=3.0)
            if r.status_code == 200 and r.json().get("app") == "dentpilot":
                return
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(0.25)
    raise RuntimeError("программа не ответила на /health")


async def _login(base: str, key: str) -> str:
    """Вход ключом — как делает `tests/harness.Client.login`: без Origin
    (same_origin_post пропускает запрос не из браузера), ответ 303 с кукой."""
    r = await client.post(base + "/admin/login",
                          data={"password": key, "next": "/admin"})
    ck = r.cookies.get("admin_auth", "")
    if r.status_code != 303 or not ck:
        raise RuntimeError(f"вход в слот не удался: {r.status_code}")
    return ck


def _checkpoint(db: pathlib.Path) -> None:
    """После остановки процесса слить WAL в сам файл: копировать и засевать
    одну базу, а не базу с хвостом."""
    if not db.exists():
        return
    c = sqlite3.connect(db)
    try:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        c.close()


# ---------- шаблон ----------

def _template_dir() -> pathlib.Path:
    return DATA / "template"


async def build_template() -> None:
    """Папка-шаблон: профиль, фото врачей, база со схемой текущей версии.

    Схему создаёт САМА программа (один запуск до /health), не копия DDL в
    шлюзе: иначе шаблон отставал бы от миграций молча."""
    t = _template_dir()
    if t.exists():
        shutil.rmtree(t)
    (t / "data" / "files" / "doctors").mkdir(parents=True)
    shutil.copy(HERE / "clinic.json", t / "clinic.json")
    for p in (HERE / "photos").glob("*.jpg"):
        shutil.copy(p, t / "data" / "files" / "doctors" / p.name)
    key = secrets.token_urlsafe(16)
    port = CHILD_PORT + SLOTS          # порт вне пула — ничей
    proc = _spawn(t, port, key)
    try:
        await _wait_health(f"http://127.0.0.1:{port}", proc)
    finally:
        _stop(proc)
    _checkpoint(t / "data" / "dental.db")
    log.info("шаблон собран: %s", t)


# ---------- слоты ----------

async def reset(s: Slot) -> None:
    """Свежая копия: процесс гасится, папка — копия шаблона с засевом от
    «сейчас», новый ключ, новый процесс, новый вход."""
    async with s.lock:
        s.ready = False
        s.owner, s.until = "", None
        _stop(s.proc)
        s.proc = None
        t = _template_dir()
        await asyncio.to_thread(lambda: (shutil.rmtree(s.dir, ignore_errors=True),
                                         shutil.copytree(t, s.dir)))
        await asyncio.to_thread(demo_seed.seed, s.dir / "data" / "dental.db",
                                s.dir / "clinic.json")
        s.key = secrets.token_urlsafe(16)
        s.proc = _spawn(s.dir, s.port, s.key)
        await _wait_health(s.base, s.proc)
        s.auth = await _login(s.base, s.key)
        s.seeded_at = _now()
        s.ready = True
        log.info("слот %d готов (порт %d)", s.i, s.port)


async def _boot() -> None:
    try:
        await build_template()
    except Exception:  # noqa: BLE001 — без шаблона слотов не будет, и это надо видеть в логе
        log.exception("шаблон не собрался — демо не поднимется")
        return
    for s in slots:
        try:
            await reset(s)
        except Exception:  # noqa: BLE001
            log.exception("слот %d не поднялся", s.i)
    asyncio.create_task(_sweep())


async def _sweep() -> None:
    """Истёкшие, упавшие и залежавшиеся свободные слоты — на сброс, по
    одному за проход, чтобы не грузить машину."""
    while True:
        await asyncio.sleep(SWEEP_S)
        now = _now()
        for s in slots:
            if s.lock.locked():
                continue
            stale_free = s.ready and not s.owner and now - s.seeded_at > REFRESH
            if s.expired(now) or (s.ready and not s.alive()) or stale_free:
                try:
                    await reset(s)
                except Exception:  # noqa: BLE001
                    log.exception("сброс слота %d не удался", s.i)


def _release(s: Slot) -> None:
    """Посетитель ушёл (logout, «начать заново»): слот истекает сейчас и
    фоновый цикл его сбросит. Данные чужому не достанутся: до сброса слот
    никому не выдаётся (`owner` стоит, `until` в прошлом)."""
    if s.owner:
        s.until = _now() - timedelta(seconds=1)


async def _slot_for(request: Request) -> tuple[Slot | None, str]:
    """Слот посетителя по куке; без куки или с протухшей — свободный.
    Возвращает (слот, кука-которую-поставить или '')."""
    now = _now()
    raw = request.cookies.get(COOKIE, "")
    if raw and "." in raw:
        i, tok = raw.split(".", 1)
        if i.isdigit() and int(i) < SLOTS:
            s = slots[int(i)]
            if (s.ready and s.alive() and s.owner and not s.expired(now)
                    and secrets.compare_digest(s.owner, tok)):
                return s, ""
    async with assign_lock:
        now = _now()
        free = [s for s in slots if s.ready and s.alive() and not s.owner and not s.lock.locked()]
        if not free:
            stale = [s for s in slots if s.expired(now) and not s.lock.locked()]
            if stale:
                try:
                    await reset(stale[0])
                    free = [stale[0]]
                except Exception:  # noqa: BLE001
                    log.exception("сброс под посетителя не удался")
        if not free:
            return None, ""
        s = free[0]
        s.owner = secrets.token_urlsafe(18)
        s.until = now + TTL
        log.info("слот %d выдан до %s", s.i, s.until.isoformat(timespec="minutes"))
        return s, f"{s.i}.{s.owner}"


def _set_cookie(resp: Response, value: str) -> Response:
    resp.set_cookie(COOKIE, value, max_age=int(TTL.total_seconds()), httponly=True,
                    samesite="lax", secure=SECURE_COOKIE, path="/")
    return resp


# ---------- страницы шлюза ----------

BUSY_HTML = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="8"><title>DentPilot — demo</title>
<style>body{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f6f7;color:#20262b;
display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;
margin:0;text-align:center;padding:16px}p{max-width:520px;line-height:1.55}
a{color:#0B7F70}</style></head><body>
<h1>Toate locurile demo sunt ocupate</h1>
<p>Demo-ul oferă fiecărui vizitator o copie proprie a programului pentru o oră.
Acum toate copiile sunt în uz — pagina se reîncarcă singură; încercați peste câteva
minute.</p>
<p style="color:#5b6b72">Все демо-копии заняты, страница обновится сама.</p>
<p><a href="__SITE__">dentpilot.md</a></p></body></html>"""


async def health(request: Request) -> Response:
    ready = [s for s in slots if s.ready and s.alive()]
    return JSONResponse({"ok": bool(ready), "slots": SLOTS, "ready": len(ready),
                         "busy": sum(1 for s in ready if s.owner),
                         "ttl_min": int(TTL.total_seconds() // 60)},
                        status_code=200 if ready else 503)


async def demo_reset(request: Request) -> Response:
    """«Începe din nou»: нынешний слот — на сброс, посетителю — другой."""
    raw = request.cookies.get(COOKIE, "")
    if raw and "." in raw and raw.split(".", 1)[0].isdigit():
        i = int(raw.split(".", 1)[0])
        if i < SLOTS and secrets.compare_digest(slots[i].owner, raw.split(".", 1)[1]):
            _release(slots[i])
    resp = RedirectResponse("/admin", status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


async def logout(request: Request) -> Response:
    """Выход из демо — обратно на сайт; копия уходит на сброс."""
    raw = request.cookies.get(COOKIE, "")
    if raw and "." in raw and raw.split(".", 1)[0].isdigit():
        i = int(raw.split(".", 1)[0])
        if i < SLOTS and secrets.compare_digest(slots[i].owner, raw.split(".", 1)[1]):
            _release(slots[i])
    resp = RedirectResponse(SITE_URL, status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


async def root(request: Request) -> Response:
    return RedirectResponse("/admin", status_code=303)


# ---------- прокси ----------

async def _forward(request: Request, s: Slot, body: bytes) -> httpx.Response:
    url = s.base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _HOP and k.lower() not in ("cookie", "content-length",
                                                               "accept-encoding")}
    headers["cookie"] = f"admin_auth={s.auth}"
    return await client.request(request.method, url, headers=headers, content=body)


async def proxy(request: Request) -> Response:
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > BODY_CAP:
        return Response("Payload too large", status_code=413)
    s, fresh = await _slot_for(request)
    if s is None:
        return HTMLResponse(BUSY_HTML.replace("__SITE__", SITE_URL), status_code=503)
    body = await request.body()
    try:
        r = await _forward(request, s, body)
        if (r.status_code in (301, 302, 303, 307, 308)
                and r.headers.get("location", "").startswith("/admin/login")):
            # кука входа протухла (программа сменила ключ подписи) — войти
            # заново и повторить один раз; экран входа посетителю не показывать
            s.auth = await _login(s.base, s.key)
            r = await _forward(request, s, body)
            if r.headers.get("location", "").startswith("/admin/login"):
                return _set_cookie(RedirectResponse("/admin", status_code=303), fresh) \
                    if fresh else RedirectResponse("/admin", status_code=303)
    except httpx.HTTPError as e:
        log.warning("слот %d не ответил: %r", s.i, e)
        return HTMLResponse(BUSY_HTML.replace("__SITE__", SITE_URL), status_code=503)
    headers = {k: v for k, v in r.headers.multi_items()
               if k.lower() not in _HOP and k.lower() not in ("set-cookie", "content-length",
                                                               "content-encoding")}
    if request.url.path.startswith("/static/"):
        # адрес статики несёт версию (?v=…): кеш на час безопасен и бережёт
        # туннель — у программы без заморозки стоит no-cache
        headers["cache-control"] = "public, max-age=3600"
    resp = Response(content=r.content, status_code=r.status_code, headers=headers)
    return _set_cookie(resp, fresh) if fresh else resp


@asynccontextmanager
async def lifespan(_app: Starlette):
    """Старт: шаблон и слоты собираются В ФОНЕ — шлюз отвечает на /demo/health
    сразу (503, пока нет ни одного слота). Остановка: все дочерние процессы."""
    DATA.mkdir(parents=True, exist_ok=True)
    boot = asyncio.create_task(_boot())
    try:
        yield
    finally:
        boot.cancel()
        for s in slots:
            _stop(s.proc)
        await client.aclose()


app = Starlette(
    routes=[
        Route("/", root),
        Route("/demo/health", health),
        Route("/demo/reset", demo_reset),
        Route("/admin/logout", logout),
        Route("/{rest:path}", proxy, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
    ],
    lifespan=lifespan)


def main() -> None:
    import uvicorn
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log.info("демо: %d слотов по %d мин., программа из %s, данные в %s",
             SLOTS, int(TTL.total_seconds() // 60), APP_DIR, DATA)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
