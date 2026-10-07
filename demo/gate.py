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

Кому слот (07.10) — `demo/admit.py`: только навигации документа в браузере, и
только браузеру, который вернул куку-пробу. Робот, превью ссылки, curl,
предзагрузка, /robots.txt, статика без куки слота не получают: до 07.10
получали все, и шесть таких запросов закрывали демо людям на час. Слот,
выданный навигацией, ждёт PENDING, придёт ли браузер за страницей (стили,
бандл, API — уже не навигацией); не пришёл — слот на сброс, а не на час.
Строка «слот N выдан» в логе называет способ, адрес и User-Agent (адреса IP
шлюз не пишет — privacy сайта, п. 6), `/demo/health` — версию программы,
выдачи, отказы и «все заняты» с запуска.

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
import html
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
from urllib.parse import quote, urlsplit

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                                 RedirectResponse, Response)
from starlette.routing import Route

from . import admit
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
# Значение куки без слота: «браузер куки хранит» (admit.PROBE). Без точки —
# слотом не прочтётся. Имя то же, что у слота: privacy сайта называет одну куку.
PROBE_VALUE = "new"
SWEEP_S = int(_env("DEMO_SWEEP_S", "20"))   # как часто фоновый цикл смотрит на слоты
# Слот, выданный навигацией, ждёт, что браузер придёт за страницей: стили,
# бандл, первый запрос API — с той же кукой и уже НЕ навигацией. Не пришёл за
# это время (робот с заголовками браузера, закрытая вкладка) — слот на сброс,
# а не на час. Две минуты — с запасом на бандл по медленной сети.
PENDING = timedelta(seconds=int(_env("DEMO_PENDING_S", "120")))
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
        # выдан навигацией, а за страницей ещё не пришли (PENDING); None —
        # пришли или слот свободен
        self.pending_until: datetime | None = None
        self.ready = False
        self.seeded_at = _now()
        self.version = ""     # APP_VERSION процесса — из его /health
        self.lock = asyncio.Lock()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def expired(self, now: datetime) -> bool:
        return bool(self.owner) and self.until is not None and now >= self.until

    def unused(self, now: datetime) -> bool:
        """Выдан, а за страницей так и не пришли — слот отдаётся раньше часа."""
        return (bool(self.owner) and self.pending_until is not None
                and now >= self.pending_until)


slots: list[Slot] = [Slot(i) for i in range(SLOTS)]
# С запуска шлюза: выдано слотов, отдано невостребованными, ответов без слота
# (роботы, превью, API без куки…) и «все заняты» тем, кому слот положен, —
# последнее и говорит, хватает ли пула людям
stats = {"granted": 0, "unused": 0, "no_slot": 0, "full": 0}
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


async def _wait_health(base: str, proc: subprocess.Popen) -> str:
    """Ждёт /health процесса; возвращает его версию программы."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < BOOT_TIMEOUT_S:
        if proc.poll() is not None:
            raise RuntimeError(f"процесс программы завершился с кодом {proc.returncode}")
        try:
            r = await client.get(base + "/health", timeout=3.0)
            if r.status_code == 200 and r.json().get("app") == "dentpilot":
                return str(r.json().get("version", ""))
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
        s.owner, s.until, s.pending_until = "", None, None
        _stop(s.proc)
        s.proc = None
        t = _template_dir()
        await asyncio.to_thread(lambda: (shutil.rmtree(s.dir, ignore_errors=True),
                                         shutil.copytree(t, s.dir)))
        await asyncio.to_thread(demo_seed.seed, s.dir / "data" / "dental.db",
                                s.dir / "clinic.json")
        s.key = secrets.token_urlsafe(16)
        s.proc = _spawn(s.dir, s.port, s.key)
        s.version = await _wait_health(s.base, s.proc)
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
    """Истёкшие, невостребованные, упавшие и залежавшиеся свободные слоты —
    на сброс, по одному за раз, чтобы не грузить машину."""
    while True:
        await asyncio.sleep(SWEEP_S)
        now = _now()
        for s in slots:
            if s.lock.locked():
                continue
            stale_free = s.ready and not s.owner and now - s.seeded_at > REFRESH
            if s.unused(now):
                _count_unused(s)
            if s.expired(now) or s.unused(now) or (s.ready and not s.alive()) or stale_free:
                try:
                    await reset(s)
                except Exception:  # noqa: BLE001
                    log.exception("сброс слота %d не удался", s.i)


def _count_unused(s: Slot) -> None:
    stats["unused"] += 1
    log.info("слот %d: за страницей не пришли за %d с — на сброс",
             s.i, int(PENDING.total_seconds()))


def _release(s: Slot) -> None:
    """Посетитель ушёл (logout, «начать заново»): слот истекает сейчас и
    фоновый цикл его сбросит. Данные чужому не достанутся: до сброса слот
    никому не выдаётся (`owner` стоит, `until` в прошлом)."""
    if s.owner:
        s.until = _now() - timedelta(seconds=1)


def _cookie_slot(request: Request) -> Slot | None:
    """Слот, чья метка в куке посетителя, — живой он или нет. ⚠️ Только ASCII:
    куку присылает кто угодно, а «²».isdigit() — правда при int(), падающем
    ValueError, и compare_digest на не-ASCII строке падает TypeError — оба
    раньше давали 500."""
    raw = request.cookies.get(COOKIE, "")
    i, _, tok = raw.partition(".")
    if not (raw.isascii() and i.isdigit() and tok and int(i) < SLOTS):
        return None
    s = slots[int(i)]
    return s if s.owner and secrets.compare_digest(s.owner, tok) else None


def _owned(request: Request) -> Slot | None:
    """Слот посетителя по куке — или None: куки нет, в ней проба, слот истёк
    или сброшен."""
    s = _cookie_slot(request)
    if s is not None and s.ready and s.alive() and not s.expired(_now()):
        return s
    return None


async def _assign(request: Request, how: str, target: str) -> Slot | None:
    """Свободный слот посетителю на TTL; None — все заняты. Решение, давать
    ли, принято до этого (admit.classify или кнопка /demo/start)."""
    async with assign_lock:
        now = _now()
        free = [s for s in slots if s.ready and s.alive() and not s.owner and not s.lock.locked()]
        if not free:
            stale = [s for s in slots
                     if (s.expired(now) or s.unused(now)) and not s.lock.locked()]
            if stale:
                if stale[0].unused(now):
                    _count_unused(stale[0])
                try:
                    await reset(stale[0])
                    free = [stale[0]]
                except Exception:  # noqa: BLE001
                    log.exception("сброс под посетителя не удался")
        if not free:
            return None
        now = _now()
        s = free[0]
        s.owner = secrets.token_urlsafe(18)
        s.until = now + TTL
        s.pending_until = now + PENDING
        stats["granted"] += 1
        # кто взял — чтобы следующее «все заняты» не осталось загадкой (07.10);
        # адрес IP не пишется: privacy сайта обещает, что журналов IP нет
        log.info("слот %d выдан до %s: %s %s · %s", s.i, s.until.isoformat(timespec="minutes"),
                 how, target[:120], request.headers.get("user-agent", "")[:160])
        return s


def _set_cookie(resp: Response, value: str) -> Response:
    resp.set_cookie(COOKIE, value, max_age=int(TTL.total_seconds()), httponly=True,
                    samesite="lax", secure=SECURE_COOKIE, path="/")
    return resp


def _no_store(resp: Response) -> Response:
    resp.headers["cache-control"] = "no-store"
    return resp


def _path_qs(request: Request) -> str:
    return request.url.path + (f"?{request.url.query}" if request.url.query else "")


def _same_origin(request: Request) -> bool:
    """POST кнопки пришёл со страницы самого демо. В отличие от программы,
    запрос БЕЗ Origin здесь отказ: браузер шлёт Origin на каждый POST, а слот
    просит именно браузер."""
    origin = request.headers.get("origin", "")
    host = urlsplit(origin).netloc if origin and origin != "null" else ""
    return bool(host) and host.lower() == request.headers.get("host", "").lower()


# ---------- страницы шлюза ----------

_PAGE = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">__HEAD__<title>DentPilot — demo</title>
<style>body{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f6f7;color:#20262b;
display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;
margin:0;text-align:center;padding:16px;box-sizing:border-box}p{max-width:520px;line-height:1.55}
a{color:#0B7F70}button{font:inherit;font-weight:600;color:#fff;background:#0B7F70;border:0;
border-radius:10px;padding:12px 22px;cursor:pointer}</style></head><body>
__BODY__
<p><a href="__SITE__">dentpilot.md</a></p></body></html>"""

_BUSY = ("<h1>Toate locurile demo sunt ocupate</h1>\n"
         "<p>Demo-ul oferă fiecărui vizitator o copie proprie a programului pentru o oră.\n"
         "Acum toate copiile sunt în uz — pagina se reîncarcă singură; încercați peste câteva\n"
         "minute.</p>\n"
         "<p style=\"color:#5b6b72\">Все демо-копии заняты, страница обновится сама.</p>")

# Страница демо без слота: её видят робот, превью ссылки (отсюда og-теги —
# карточка ссылки в Viber/Telegram/999 вместо пустоты) и браузер, которому
# слот не выдан навигацией. Кнопка — POST: роботы форм не жмут.
_START = ("<h1>DentPilot — demo online</h1>\n"
          "<p>Programul adevărat, cu o clinică fictivă: fiecare vizitator primește o copie\n"
          "proprie pentru o oră.</p>\n"
          "<form method=\"post\" action=\"__ACTION__\"><button type=\"submit\">Deschide demo-ul</button></form>\n"
          "<p style=\"color:#5b6b72\">Настоящая программа с вымышленной клиникой: каждому\n"
          "посетителю — своя копия на час.</p>")
_START_HEAD = (
    "\n<meta name=\"description\" content=\"__DESC__\">"
    "\n<meta property=\"og:title\" content=\"DentPilot — demo online\">"
    "\n<meta property=\"og:description\" content=\"__DESC__\">"
    # картинка — карточка самого сайта: своей у демо нет
    "\n<meta property=\"og:image\" content=\"__SITE__/shots/og.png\">")
_START_DESC = ("Programul DentPilot cu o clinică fictivă: o copie proprie pentru o oră, "
               "direct în browser.")

_COOKIES = ("<h1>Demo-ul are nevoie de cookie-uri</h1>\n"
            "<p>Browserul nu a păstrat cookie-ul tehnic al demo-ului, iar fără el copia\n"
            "dvs. nu poate funcționa. Permiteți cookie-urile pentru acest site și încercați\n"
            "din nou.</p>\n"
            "<form method=\"post\" action=\"__ACTION__\"><button type=\"submit\">Încearcă din nou</button></form>\n"
            "<p style=\"color:#5b6b72\">Браузер не сохранил техническую куку демо, а без неё\n"
            "своя копия не работает. Разрешите cookie для этого сайта и попробуйте снова.</p>")


def _html(body: str, head: str = "") -> str:
    return (_PAGE.replace("__HEAD__", head).replace("__BODY__", body)
            .replace("__SITE__", html.escape(SITE_URL.rstrip("/"))))


def _action(nxt: str) -> str:
    return html.escape("/demo/start?next=" + quote(nxt, safe=""))


def _busy() -> Response:
    page = _html(_BUSY, '\n<meta http-equiv="refresh" content="8">')
    return _no_store(HTMLResponse(page, status_code=503))


def _start_page(nxt: str) -> Response:
    """Страница демо без слота; кука-проба — чтобы кнопка пришла с ней."""
    head = _START_HEAD.replace("__DESC__", _START_DESC)
    page = _html(_START.replace("__ACTION__", _action(nxt)), head)
    return _set_cookie(_no_store(HTMLResponse(page)), PROBE_VALUE)


def _cookies_page(nxt: str) -> Response:
    page = _html(_COOKIES.replace("__ACTION__", _action(nxt)))
    return _set_cookie(_no_store(HTMLResponse(page)), PROBE_VALUE)


async def health(request: Request) -> Response:
    """Состояние пула — шлюз отвечает сам и слота не берёт. `version` —
    программа в слотах (шаг 9 выпуска, app/RELEASE.md), `pending` — выданы, но
    за страницей ещё не пришли; счётчики — с запуска шлюза."""
    ready = [s for s in slots if s.ready and s.alive()]
    return JSONResponse({"ok": bool(ready), "slots": SLOTS, "ready": len(ready),
                         "busy": sum(1 for s in ready if s.owner),
                         "pending": sum(1 for s in ready if s.owner and s.pending_until),
                         "ttl_min": int(TTL.total_seconds() // 60),
                         "version": ", ".join(sorted({s.version for s in ready if s.version})),
                         **stats},
                        status_code=200 if ready else 503)


async def robots(request: Request) -> Response:
    """Роботам демо закрыто целиком: копия на час — не страница для поиска.
    Слот робот и так не получит (admit), это — чтобы не ходил вовсе."""
    return PlainTextResponse(admit.ROBOTS_TXT)


async def demo_start(request: Request) -> Response:
    """Выдача слота через пробу куки. GET — второй шаг admit.PROBE: браузер
    получил пробу и вернулся с ней (не вернулся — куки запрещены, страница о
    них вместо круга новых слотов). POST — кнопка со страницы демо: вход для
    браузера без Sec-Fetch и для человека, которого правило приняло за
    робота; роботы форм не жмут, поэтому User-Agent здесь не спрашивается."""
    nxt = admit.safe_next(request.query_params.get("next", ""))
    if _owned(request) is not None:
        return RedirectResponse(nxt, status_code=303)
    has_cookie = COOKIE in request.cookies
    if request.method == "POST":
        if not _same_origin(request):
            return PlainTextResponse("Forbidden", status_code=403)
        how = "кнопка"
    else:
        kind = admit.classify(request.method, nxt, request.headers, has_cookie)
        if kind not in (admit.SLOT, admit.PROBE):
            stats["no_slot"] += 1
            return _refuse(kind, nxt)
        how = "навигация"
    if not has_cookie:
        stats["no_slot"] += 1
        return _cookies_page(nxt)
    s = await _assign(request, how, nxt)
    if s is None:
        stats["full"] += 1
        return _busy()
    return _set_cookie(RedirectResponse(nxt, status_code=303), f"{s.i}.{s.owner}")


async def demo_reset(request: Request) -> Response:
    """«Începe din nou»: нынешний слот — на сброс, посетителю — другой. Вместо
    слота кука-проба: браузер её хранит, и новый слот выдаст сама навигация."""
    s = _cookie_slot(request)
    if s is not None:
        _release(s)
    return _set_cookie(RedirectResponse("/admin", status_code=303), PROBE_VALUE)


async def logout(request: Request) -> Response:
    """Выход из демо — обратно на сайт; копия уходит на сброс."""
    s = _cookie_slot(request)
    if s is not None:
        _release(s)
    resp = RedirectResponse(SITE_URL, status_code=303)
    resp.delete_cookie(COOKIE, path="/")
    return resp


async def login_page(request: Request) -> Response:
    """Экран входа программы посетителю не показывается никогда: входит шлюз.
    Клиент уходит сюда сам, получив 401 (слот истёк, у API нет куки), —
    обратно туда, куда он шёл; без слота это навигация, она его и получит."""
    return RedirectResponse(admit.safe_next(request.query_params.get("next", "")),
                            status_code=303)


async def root(request: Request) -> Response:
    """Вход с сайта. Кука-проба ставится здесь же: следующий шаг, /admin,
    придёт с ней — и навигация получит слот без лишнего перехода."""
    resp = RedirectResponse("/admin", status_code=303)
    return resp if COOKIE in request.cookies else _set_cookie(resp, PROBE_VALUE)


# ---------- прокси ----------

def _refuse(kind: str, target: str) -> Response:
    """Ответ без слота (admit.classify)."""
    if kind == admit.PROBE:
        return _set_cookie(RedirectResponse("/demo/start?next=" + quote(target, safe=""),
                                            status_code=303), PROBE_VALUE)
    if kind == admit.API:
        # конверт программы (core/api.py → msg_json): клиент на 401 уходит на
        # вход документом, вход ведёт обратно (login_page) — это навигация
        return JSONResponse({"ok": False, "code": "", "tone": "err", "text": ""},
                            status_code=401)
    if kind == admit.PAGE:
        return _start_page(admit.safe_next(target))
    if kind == admit.HOME:
        return RedirectResponse("/admin", status_code=303)
    if kind == admit.LATER:
        # предзагрузку браузер выбросит и на настоящем переходе спросит снова
        return _no_store(Response(status_code=503))
    return PlainTextResponse("Not found", status_code=404)


async def _forward(request: Request, s: Slot, body: bytes, *, auth: bool = True) -> httpx.Response:
    url = s.base + _path_qs(request)
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _HOP and k.lower() not in ("cookie", "content-length",
                                                               "accept-encoding")}
    if auth:
        headers["cookie"] = f"admin_auth={s.auth}"
    return await client.request(request.method, url, headers=headers, content=body)


def _relay(request: Request, r: httpx.Response) -> Response:
    headers = {k: v for k, v in r.headers.multi_items()
               if k.lower() not in _HOP and k.lower() not in ("set-cookie", "content-length",
                                                               "content-encoding")}
    if request.url.path.startswith("/static/"):
        # адрес статики несёт версию (?v=…): кеш на час безопасен и бережёт
        # туннель — у программы без заморозки стоит no-cache
        headers["cache-control"] = "public, max-age=3600"
    return Response(content=r.content, status_code=r.status_code, headers=headers)


async def _public(request: Request) -> Response:
    """Статика, значок, манифест, /health без куки — без слота: они одинаковы
    во всех слотах, и программа отдаёт их без входа. Отвечает любой живой
    слот, кука входа не едет."""
    s = next((x for x in slots if x.ready and x.alive()), None)
    if s is None:
        return _no_store(PlainTextResponse("Demo is starting", status_code=503))
    try:
        r = await _forward(request, s, b"", auth=False)
    except httpx.HTTPError as e:
        log.warning("слот %d не ответил: %r", s.i, e)
        return _no_store(PlainTextResponse("Demo is unavailable", status_code=503))
    return _relay(request, r)


async def proxy(request: Request) -> Response:
    cl = request.headers.get("content-length", "")
    if cl.isdigit() and int(cl) > BODY_CAP:
        return Response("Payload too large", status_code=413)
    fresh = ""
    s = _owned(request)
    if s is not None:
        if s.pending_until is not None and not admit.navigation(request.headers):
            s.pending_until = None    # браузер пришёл за страницей: слот его на час
    else:
        kind = admit.classify(request.method, request.url.path, request.headers,
                              COOKIE in request.cookies)
        if kind == admit.PUBLIC:
            return await _public(request)
        if kind != admit.SLOT:
            if kind != admit.PROBE:
                stats["no_slot"] += 1
            return _refuse(kind, _path_qs(request))
        s = await _assign(request, "навигация", _path_qs(request))
        if s is None:
            stats["full"] += 1
            return _busy()
        fresh = f"{s.i}.{s.owner}"
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
        return _busy()
    resp = _relay(request, r)
    return _set_cookie(resp, fresh) if fresh else resp


class _NoIndex:
    """`X-Robots-Tag` на КАЖДЫЙ ответ шлюза, включая ответы программы: копия
    демо на час не должна попасть в поиск ни одной страницей."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_tagged(message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []),
                                      (b"x-robots-tag", b"noindex, nofollow")]
            await send(message)

        await self.app(scope, receive, send_tagged)


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
        Route("/robots.txt", robots),
        Route("/demo/health", health),
        Route("/demo/reset", demo_reset),
        Route("/demo/start", demo_start, methods=["GET", "POST"]),
        # только GET: POST входа идёт в прокси, как шёл
        Route("/admin/login", login_page),
        Route("/admin/logout", logout),
        Route("/{rest:path}", proxy, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
    ],
    middleware=[Middleware(_NoIndex)],
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
