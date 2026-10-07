"""Живая проверка шлюза демо (07.10): кому слот, кому нет — на настоящем шлюзе.

Прогон (tests/run_tests.py) шлюз не поднимает: шлюзу нужен httpx, а в
окружение сборки лишнее не ставится. Там проверяется только решение
(demo/admit.py). Здесь шлюз идёт отдельным процессом — интерпретатором, в
котором есть httpx и starlette, с двумя слотами и короткими сроками, — а
запросы шлёт стандартная библиотека: робот, превью ссылки, curl, браузер с
кукой и без, браузер с запретом cookie, кнопка старта, сброс.

    <python с httpx и starlette> -X utf8 demo/check_gate.py
    у Олега: D:\\DentProject\\sandbox\\demo-venv\\Scripts\\python.exe

Программа в слотах — из `.venv-desktop` репозитория (как в README). ⛔ Только
локально: живое демо этими запросами не трогать — каждый запрос без куки к
старому шлюзу занимает там слот на час.
"""
from __future__ import annotations

import http.client
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SLOTS = 2
PENDING_S = 8          # сколько слот ждёт, придёт ли браузер за страницей
CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
SAFARI15 = ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1")
NAV = {"User-Agent": CHROME, "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
       "Sec-Fetch-Site": "same-site", "Sec-Fetch-User": "?1",
       "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
FETCH = {"User-Agent": CHROME, "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
         "Sec-Fetch-Site": "same-origin", "Accept": "*/*"}

failed: list[str] = []


def ok(label: str, cond: bool, detail: str = "") -> bool:
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or not detail else f" — {detail}"))
    if not cond:
        failed.append(label)
    return cond


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_run(n: int) -> int:
    """Начало n свободных портов подряд: слоты и шаблон шлюза."""
    for base in range(9400, 9900, n + 1):
        try:
            for p in range(base, base + n):
                with socket.socket() as s:
                    s.bind(("127.0.0.1", p))
            return base
        except OSError:
            continue
    raise RuntimeError("нет свободных портов для слотов")


class Resp:
    def __init__(self, status: int, headers, body: str) -> None:
        self.status, self.headers, self.body = status, headers, body

    def h(self, name: str) -> str:
        return self.headers.get(name, "") or ""

    @property
    def cookie(self) -> str | None:
        """Значение dp_demo из Set-Cookie; None — куку не ставили."""
        for line in self.headers.get_all("set-cookie") or []:
            m = re.match(r'dp_demo="?([^";]*)', line)
            if m:
                return m.group(1)
        return None

    def __repr__(self) -> str:
        return f"<{self.status} {self.h('location')} {self.body[:80]!r}>"


def call(method: str, path: str, headers: dict | None = None, cookie: str = "",
         body: bytes | None = None) -> Resp:
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = f"dp_demo={cookie}"
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    out = Resp(r.status, r.headers, r.read().decode("utf-8", "replace"))
    c.close()
    return out


def health() -> dict:
    return json.loads(call("GET", "/demo/health").body)


def wait_health(cond, timeout: float, what: str) -> dict:
    t0 = time.monotonic()
    h: dict = {}
    while time.monotonic() - t0 < timeout:
        try:
            h = health()
            if cond(h):
                return h
        except (OSError, ValueError, http.client.HTTPException):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"не дождались: {what}; /demo/health = {h}")


def app_version() -> str:
    src = (ROOT / "bot" / "app" / "engine.py").read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else ""


def scenarios() -> None:
    h0 = wait_health(lambda h: h.get("ready") == SLOTS, 240, "все слоты готовы")
    print(f"шлюз готов: {h0}")
    ok("/demo/health называет версию программы", h0.get("version") == app_version(),
       f"{h0.get('version')!r} против {app_version()!r}")
    ok("на старте свободно всё", h0.get("busy") == 0, str(h0))

    print("\nБез куки, не браузер — слота нет")
    r = call("GET", "/robots.txt", {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"})
    ok("/robots.txt шлюза закрывает всё", r.status == 200 and "Disallow: /" in r.body, repr(r))
    ok("X-Robots-Tag на ответах шлюза", "noindex" in r.h("x-robots-tag"), r.h("x-robots-tag"))
    r = call("GET", "/admin", {"User-Agent": "curl/8.9.1", "Accept": "*/*"})
    ok("curl на журнал — страница демо с кнопкой", r.status == 200 and "Deschide demo-ul" in r.body,
       repr(r))
    ok("…и кука-проба, не слот", r.cookie == "new", str(r.cookie))
    r = call("GET", "/", {"User-Agent": "TelegramBot (like TwitterBot)"})
    ok("превью Telegram: корень → /admin", r.status == 303 and r.h("location") == "/admin", repr(r))
    r = call("GET", "/admin", {"User-Agent": "TelegramBot (like TwitterBot)"}, cookie=r.cookie or "")
    ok("превью Telegram получает og-карточку демо",
       r.status == 200 and 'property="og:title"' in r.body, repr(r))
    r = call("GET", "/admin", {**NAV, "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; "
                                                    "+http://www.google.com/bot.html)"}, cookie="new")
    ok("робот с заголовками браузера — страница демо", r.status == 200 and "Deschide" in r.body, repr(r))
    for path in ("/favicon.ico", "/static/css/panel.css", "/manifest.webmanifest", "/health"):
        r = call("GET", path, {"User-Agent": "curl/8.9.1"})
        ok(f"{path} без куки — 200 без слота и без куки", r.status == 200 and r.cookie is None,
           repr(r))
    ok("/health без куки — ответ программы", '"dentpilot"' in call("GET", "/health").body)
    r = call("GET", "/api/settings/hub", FETCH)
    ok("API без куки — 401 в конверте", r.status == 401 and json.loads(r.body).get("ok") is False,
       repr(r))
    r = call("HEAD", "/admin", NAV, cookie="new")
    ok("HEAD журнала — без слота", r.status == 200 and r.cookie == "new" and health()["busy"] == 0,
       repr(r))
    r = call("GET", "/admin", {**NAV, "Sec-Purpose": "prefetch"}, cookie="new")
    ok("предзагрузка — 503 без кеша", r.status == 503 and r.h("cache-control") == "no-store", repr(r))
    r = call("POST", "/admin/appointment/add", NAV, body=b"x=1")
    ok("форма без слота — 303 на /admin", r.status == 303 and r.h("location") == "/admin", repr(r))
    r = call("GET", "/wp-login.php", {"User-Agent": "Mozilla/5.0"})
    ok("сканер мимо журнала — 404", r.status == 404, repr(r))
    r = call("GET", "/admin/login?next=/admin/week", NAV)
    ok("экран входа программы не показывается — назад, куда шли",
       r.status == 303 and r.h("location") == "/admin/week", repr(r))
    h = health()
    ok("после всего этого слоты свободны", h["busy"] == 0, str(h))

    print("\nБраузер A: с сайта")
    r = call("GET", "/", NAV)
    probe = r.cookie
    ok("корень → /admin с кукой-пробой", r.status == 303 and probe == "new", repr(r))
    r = call("GET", "/admin", NAV, cookie=probe or "")
    a = r.cookie or ""
    ok("навигация с пробой — журнал и кука слота", r.status == 200 and "." in a, f"{r!r} {a!r}")
    ok("X-Robots-Tag и на странице программы", "noindex" in r.h("x-robots-tag"), r.h("x-robots-tag"))
    h = health()
    ok("слот выдан и ждёт страницу", h["busy"] == 1 and h["pending"] == 1, str(h))
    r = call("GET", "/admin", NAV, cookie=a)
    ok("повторная навигация — тот же слот", r.status == 200 and r.cookie is None, repr(r))
    ok("…навигация слот не подтверждает", health()["pending"] == 1)
    r = call("GET", "/api/settings/hub", FETCH, cookie=a)
    ok("API с кукой — данные слота", r.status == 200 and json.loads(r.body).get("ok") is True,
       repr(r))
    ok("…и слот подтверждён: браузер пришёл за страницей", health()["pending"] == 0, str(health()))

    print("\nБраузер B: глубокая ссылка без куки; браузер с запретом cookie")
    r = call("GET", "/admin/medici", NAV)
    ok("без куки вовсе — через /demo/start с пробой",
       r.status == 303 and r.h("location") == "/demo/start?next=%2Fadmin%2Fmedici"
       and r.cookie == "new", repr(r))
    r = call("GET", "/demo/start?next=%2Fadmin%2Fmedici", NAV)
    ok("куку не вернул — страница про cookie, не слот",
       r.status == 200 and "cookie-uri" in r.body and health()["busy"] == 1, repr(r))
    r = call("GET", "/demo/start?next=%2Fadmin%2Fmedici", NAV, cookie="new")
    b = r.cookie or ""
    ok("вернул пробу — слот и обратно на адрес",
       r.status == 303 and r.h("location") == "/admin/medici" and "." in b, repr(r))
    h = health()
    ok("занято два, один ждёт страницу", h["busy"] == 2 and h["pending"] == 1, str(h))
    r = call("GET", "/admin", NAV, cookie="new")
    ok("третий посетитель — «все заняты»", r.status == 503 and "ocupate" in r.body, repr(r))

    print(f"\nB так и не пришёл за страницей — слот отдаётся через {PENDING_S} с, не через час")
    h = wait_health(lambda h: h.get("unused", 0) >= 1 and h["busy"] == 1 and h["ready"] == SLOTS,
                    PENDING_S + 60, "невостребованный слот вернулся")
    ok("невостребованный слот сброшен и свободен", h["busy"] == 1, str(h))
    r = call("GET", "/api/settings/hub", FETCH, cookie=b)
    ok("кука B больше не действует", r.status == 401, repr(r))

    print("\nКнопка «Deschide demo-ul» (браузер без Sec-Fetch)")
    old = {"User-Agent": SAFARI15, "Accept": "text/html,*/*"}
    origin = {"Origin": f"http://127.0.0.1:{PORT}"}
    r = call("POST", "/demo/start?next=%2Fadmin", old, cookie="new")
    ok("POST без Origin — отказ", r.status == 403, repr(r))
    r = call("POST", "/demo/start?next=%2Fadmin", {**old, "Origin": "https://evil.example"},
             cookie="new")
    ok("POST с чужого сайта — отказ", r.status == 403, repr(r))
    r = call("POST", "/demo/start?next=%2Fadmin", {**old, **origin})
    ok("POST без куки — страница про cookie", r.status == 200 and "cookie-uri" in r.body, repr(r))
    r = call("POST", "/demo/start?next=%2Fadmin", {**old, **origin}, cookie="new")
    c = r.cookie or ""
    ok("кнопка с пробой — слот", r.status == 303 and r.h("location") == "/admin" and "." in c,
       repr(r))
    r = call("GET", "/admin", old, cookie=c)
    ok("старый браузер работает в своём слоте", r.status == 200 and r.cookie is None, repr(r))

    print("\n«Începe din nou» у A")
    r = call("GET", "/demo/reset", NAV, cookie=a)
    ok("сброс — на /admin с пробой вместо слота", r.status == 303 and r.cookie == "new", repr(r))
    ok("кука A больше не действует", call("GET", "/api/settings/hub", FETCH, cookie=a).status == 401)
    h = wait_health(lambda h: h["busy"] == 1 and h["ready"] == SLOTS, 60, "слот A сброшен")
    ok("слот A сброшен", True)
    ok("счётчики с запуска", h["granted"] == 3 and h["unused"] >= 1 and h["no_slot"] >= 10
       and h["full"] == 1, str(h))


def stop(gate: subprocess.Popen) -> None:
    """Шлюз со всеми слотами: на Windows — деревом (TerminateProcess не даёт
    шлюзу погасить детей), иначе — сигналом, как контейнеру."""
    if gate.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(gate.pid)], capture_output=True)
    else:
        gate.send_signal(signal.SIGINT)
    try:
        gate.wait(timeout=20)
    except subprocess.TimeoutExpired:
        gate.kill()


def main() -> int:
    global PORT
    PORT = free_port()
    data = pathlib.Path(tempfile.mkdtemp(prefix="dp_gate_"))
    log_path = data.parent / (data.name + ".log")
    venv = ROOT / ".venv-desktop" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = {**os.environ, "DEMO_SLOTS": str(SLOTS), "DEMO_PORT": str(PORT),
           "DEMO_HOST": "127.0.0.1", "DEMO_CHILD_PORT": str(free_run(SLOTS + 1)),
           "DEMO_DATA": str(data), "DEMO_SECURE_COOKIE": "0", "DEMO_PENDING_S": str(PENDING_S),
           "DEMO_SWEEP_S": "1", "DEMO_PYTHON": str(venv if venv.exists() else sys.executable)}
    print(f"шлюз на :{PORT}, данные {data}, журнал {log_path}")
    with open(log_path, "w", encoding="utf-8") as log:
        gate = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "demo.gate"],
                                cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            scenarios()
        except Exception as e:  # noqa: BLE001 — отчёт важнее трейса
            failed.append(f"сценарий оборвался: {e!r}")
            print(f"  ✗ сценарий оборвался: {e!r}")
        finally:
            stop(gate)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\nЖурнал шлюза — выдачи и возвраты:")
    for line in lines:
        if "выдан" in line or "не пришли" in line or "ERROR" in line or "Traceback" in line:
            print("  " + line)
    shutil.rmtree(data, ignore_errors=True)
    if failed:
        print(f"\nКРАСНОЕ: {len(failed)}; журнал шлюза оставлен: {log_path}")
        return 1
    log_path.unlink(missing_ok=True)
    print("\nВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
