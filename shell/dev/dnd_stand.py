# -*- coding: utf-8 -*-
"""Стенд: перетаскивание визита в окне Tauri НАСТОЯЩЕЙ мышью (22.10, к 2.0.4).

    .venv-desktop\\Scripts\\python.exe shell\\dev\\dnd_stand.py --exe <…\\DentPilot.exe> --mouse [--shots DIR]

⛔ Стенд берёт мышь ЧЕЛОВЕКА — `--mouse` ставится только в окно времени,
названное Олегом (22.10). Без флага он мыши не трогает: окно, язык, второй
запуск проверяются, перенос и бросок файла — нет, и итог не зелёный.

Оболочка 2.0.0–2.0.3 не давала перетащить визит от врача к врачу (в окне
pywebview это работало). Обработчик перетаскивания файлов Tauri включён по
умолчанию, и на Windows wry ставит ВМЕСТО цели броска WebView2 свою
(`RegisterDragDrop`), которая знает только файлы (CF_HDROP): `dragover` и
`drop` страницы до неё не доходят. Лечится `disable_drag_drop_handler()` на
каждом WebView (`main.rs`, `watch.rs`).

⛔ Бросок — только вводом ОС (`SendInput`): `Input.dispatchDragEvent` CDP
(как в `scripts/dash_shots.py`) вручает событие странице мимо цели броска
окна и зеленеет на сломанной сборке. CDP здесь — только глаза: координаты,
счётчики событий, открылся ли `MoveDialog`.

Окно стенда — настоящее, на экране, без `--tray`; движок — из исходников
(`DENTPILOT_DEV_APP`, как `shell/dev/run.ps1`; клиент — собранный
`bot/app/static/js/bundle.js`, в свежем worktree его нет: `npx vite build` в
`frontend`), данные и профиль — в лаборатории (TEMP). ⚠️ На полминуты стенд
берёт мышь: окно встаёт поверх всех, курсор ходит сам и возвращается на
место в конце.
⛔ И тогда мышь берётся только у машины, за которой не работают (15 с без
ввода), окно стенда — поверх всех, и под КАЖДОЙ точкой — окно процесса
стенда, по PID (22.10: шёл звонок sipgate, его окно «поверх всех», и
протяжка ушла в чужие окна). Кнопка отпускается (= бросок) только над окном
оболочки стенда — проверка ДО отпускания; чужое окно под курсором или
человек двинул мышь — Esc отменяет перетаскивание, курсор на своё окно, и
лишь там кнопка отпускается.

Проверки:
  drag     визит d2 тащится мышью в колонку d3 — открылся «Mutare programare»,
           ячейка подсветилась, после «Da, mută» визит в базе у d3
  date     поле даты рисуется по-румынски («zz.ll.aaaa»), а не по языку
           Windows; аргументы браузера — `--lang=ro` и прежние умолчания wry
  file     PDF, брошенный мышью на страницу, ничего не открывает: страница
           та же, наружу ничего не ушло (`open outside` в журнале нет)
  again    выход словом и сразу второй запуск на том же профиле — окно
           поднялось, без «cannot start» и паники (ERROR_BUSY, прайор 18.10)

⛔ Процессы — только по PID (задания стенда): `DentPilot.exe` — имя и
установленной программы Олега.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import datetime
import http.client
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from ctypes import wintypes

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import shell_check as sc  # noqa: E402
from harness import PIN, Client, _end_job, _rmtree_settled, _start_in_own_job, add_appt, \
    clinic_today, day_model, free_port  # noqa: E402

TITLE = "DentPilot — registrul clinicii"         # main.rs::TITLE
READY = 120.0                                     # движок из исходников: первый старт
FROM, TO = "d2", "d3"                             # врачи фикстуры clinic_test.json
VISIT_AT, DROP_HOUR = "10:00", 14
# словарь румынского Edge (Locales\ro.pak): «zz», «mm», «aaaa» — у Chrome «ll»
RO_DATE = "zz.mm.aaaa"
# прежние умолчания wry (webview2/mod.rs): без них вернулись бы «мини-меню»
# выделения, PDF в отдельном окне и SmartScreen на каждый адрес
WRY_DEFAULT = "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection"

u32 = ctypes.WinDLL("user32", use_last_error=True)


# ---------- лаборатория ----------

class Lab:
    """Папка стенда: копия exe, данные (своя clinic.json и dental.env),
    профиль окна. `DENTART_PROFILE_DIR` делает оболочку стендом — свой замок
    «один экземпляр» и свой `shell.json`."""

    def __init__(self, exe: pathlib.Path) -> None:
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_dnd_"))
        self.prog = self.dir / "prog"
        self.prog.mkdir()
        self.shell = self.prog / "DentPilot.exe"
        shutil.copy2(exe, self.shell)          # target стенда пересобирается — не держать его
        self.data = self.dir / "data"
        self.tmp = self.dir / "tmp"
        self.profile = self.dir / "profile" / "webview"
        for d in (self.data, self.tmp, self.profile.parent):
            d.mkdir(parents=True)
        # врачи d2/d3/d4 и часы 7–21 каждый день — без них колонке некуда бросать
        shutil.copy(ROOT / "tests" / "fixtures" / "clinic_test.json", self.data / "clinic.json")
        (self.data / "dental.env").write_text(f"TELEGRAM_TOKEN=\nADMIN_KEY={PIN}\n", encoding="utf-8")
        self.port = free_port()
        self.cdp = free_port()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def shell_log(self) -> pathlib.Path:
        return self.profile.parent / "shell.log"

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DENTART_", "DENTPILOT_", "WEBVIEW2_"))
               and k not in ("TELEGRAM_TOKEN", "ADMIN_KEY")}
        env.update({"DENTPILOT_DEV_APP": str(ROOT), "DENTART_DATA_DIR": str(self.data),
                    "DENTART_PORT": str(self.port), "DENTART_PROFILE_DIR": str(self.profile),
                    "DENTART_UPDATE_CHECK": "off", "TEMP": str(self.tmp), "TMP": str(self.tmp),
                    # глаза стенда (как у shell_check): порт отладки WebView2
                    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={self.cdp}"})
        return env

    def log_text(self) -> str:
        try:
            return self.shell_log.read_text("utf-8", "replace")
        except OSError:
            return ""

    def drop(self) -> None:
        _rmtree_settled(self.dir, budget=15.0)


class Shell:
    def __init__(self, lab: Lab) -> None:
        self.t0 = time.time()
        self.proc, self.job = _start_in_own_job([str(lab.shell)], cwd=str(lab.prog), env=lab.env())

    def wait(self, timeout: float) -> int | None:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def close(self) -> None:
        if self.job is not None:
            _end_job(self.job)
            self.job = None


def wait_ready(lab: Lab, sh: Shell) -> dict | None:
    end = time.time() + READY
    while time.time() < end:
        if b'"dentpilot"' in sc.health(lab.port):
            target = sc.page_target(lab.cdp, lab.origin + "/", 30.0)
            if target:
                return target
        if sh.proc.poll() is not None:
            return None
        time.sleep(0.3)
    return None


# ---------- CDP: команды страницы ----------

def cdp(target: dict, method: str, timeout: float = 15.0, **params):
    ws = sc._WS(target["webSocketDebuggerUrl"], timeout)
    try:
        ws.send(json.dumps({"id": 1, "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 1:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result") or {}
    finally:
        ws.close()


def js(target: dict, expr: str):
    got = cdp(target, "Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
    return (got.get("result") or {}).get("value")


def wait_js(target: dict, expr: str, timeout: float):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = js(target, expr)
        except (OSError, RuntimeError, ConnectionError):
            v = None
        if v:
            return v
        time.sleep(0.25)
    return None


def login_cookie(origin: str) -> str:
    u = urllib.parse.urlparse(origin)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
    body = urllib.parse.urlencode({"password": PIN, "next": "/admin"})
    conn.request("POST", "/admin/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    r = conn.getresponse()
    cookie = r.getheader("Set-Cookie") or ""
    r.read()
    conn.close()
    m = re.search(r"admin_auth=([^;]+)", cookie)
    if not m:
        raise SystemExit(f"вход не удался: {r.status} {cookie!r}")
    return m.group(1)


def shot(target: dict, out: pathlib.Path | None, name: str) -> None:
    if out is None:
        return
    try:
        png = cdp(target, "Page.captureScreenshot", format="png").get("data", "")
        (out / f"{name}.png").write_bytes(base64.b64decode(png))
    except (OSError, RuntimeError, ConnectionError) as e:
        print(f"   снимок {name} не снят: {e}")


# ---------- Windows: окно и настоящий ввод ----------

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _IU(ctypes.Union):
    # KEYBDINPUT/HARDWAREINPUT короче MOUSEINPUT: объединению хватает его размера
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _IU)]


MOVE, DOWN, UP, ABSOLUTE, VIRTUALDESK = 0x0001, 0x0002, 0x0004, 0x8000, 0x4000


def _mouse(flags: int, x: int = 0, y: int = 0) -> None:
    vx, vy = u32.GetSystemMetrics(76), u32.GetSystemMetrics(77)
    vw, vh = u32.GetSystemMetrics(78), u32.GetSystemMetrics(79)
    nx = round((x - vx) * 65535 / max(vw - 1, 1))
    ny = round((y - vy) * 65535 / max(vh - 1, 1))
    inp = INPUT(type=0, u=_IU(mi=MOUSEINPUT(nx, ny, 0, flags | ABSOLUTE | VIRTUALDESK, 0, 0)))
    if u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise OSError(f"SendInput: ошибка {ctypes.get_last_error()} (экран заблокирован?)")


class Foreign(Exception):
    """Ввод ушёл бы не в окно стенда — он не посылается (или обрывается)."""


IDLE = 15.0          # столько секунд без ввода человека — прежде чем взять мышь
IDLE_WAIT = 180.0


class _LII(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_s() -> float:
    lii = _LII(ctypes.sizeof(_LII), 0)
    u32.GetLastInputInfo(ctypes.byref(lii))
    return ((ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def wait_idle() -> None:
    """⛔ 22.10: Олег говорил по sipgate, и бросок стенда ушёл в чужое окно —
    мышь берётся только у машины, за которой не работают."""
    end = time.time() + IDLE_WAIT
    told = False
    while idle_s() < IDLE:
        if time.time() > end:
            raise Foreign(f"за машиной работают (ввод человека за последние {IDLE:.0f} с) — мышь не взята")
        if not told:
            print(f"   жду {IDLE:.0f} с без мыши и клавиатуры, чтобы взять мышь…", flush=True)
            told = True
        time.sleep(0.5)


def cursor() -> tuple[int, int]:
    p = wintypes.POINT()
    u32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move(x: float, y: float) -> None:
    _mouse(MOVE, round(x), round(y))
    cx, cy = cursor()
    if abs(cx - x) > 3 or abs(cy - y) > 3:
        raise Foreign(f"курсор не там, куда его поставил стенд ({cx},{cy} вместо {x:.0f},{y:.0f}): "
                      "мышью двигает человек")


def glide(a: tuple[float, float], b: tuple[float, float], steps: int = 25, pause: float = 0.03) -> None:
    for i in range(1, steps + 1):
        move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        time.sleep(pause)


def press() -> None:
    if u32.GetAsyncKeyState(0x01) & 0x8000:
        raise Foreign("левая кнопка уже нажата человеком")
    _mouse(DOWN)


def release(pids: tuple[int, ...]) -> None:
    """⛔ Отпустить кнопку — только над своим окном, и проверка — ДО отпускания:
    отпущенная кнопка и есть бросок. Чужое окно под курсором — `Foreign`, и
    вызывающий отменяет перетаскивание Esc'ом (`abort_drag`)."""
    guard(pids, cursor())
    _mouse(UP)


def abort_drag(home: tuple[float, float], pids: tuple[int, ...]) -> None:
    """Оборвать начатый бросок, не уронив его в чужое окно: Esc (OLE отменяет
    перетаскивание), курсор — на своё окно, и кнопка отпускается только там.
    Своё окно так и не встало под курсор — кнопка остаётся нажатой (её
    отпустит первый щелчок человека), но не над чужим окном."""
    class KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class KU(ctypes.Union):
        _fields_ = [("ki", KI), ("mi", MOUSEINPUT)]

    class KINPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", KU)]

    for flags in (0, 2):                              # Esc: нажать, отпустить
        k = KINPUT(type=1, u=KU(ki=KI(0x1B, 0, flags, 0, 0)))
        u32.SendInput(1, ctypes.byref(k), ctypes.sizeof(KINPUT))
        time.sleep(0.05)
    for _ in range(20):
        u32.SetCursorPos(round(home[0]), round(home[1]))
        time.sleep(0.1)
        try:
            release(pids)
            return
        except Foreign:
            pass
    print("   ⚠️  кнопка мыши осталась нажатой: под курсором чужое окно — щёлкните мышью", flush=True)


_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u32.EnumWindows.argtypes = [_ENUM, wintypes.LPARAM]
u32.EnumChildWindows.argtypes = [wintypes.HWND, _ENUM, wintypes.LPARAM]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT]
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetAncestor.restype = wintypes.HWND


def guard(pids: tuple[int, ...], *points: tuple[float, float]) -> None:
    """⛔ Под КАЖДОЙ точкой ввода — окно процесса стенда (PID владельца
    корневого окна под точкой: у страницы это окно оболочки, хотя сами окна
    отрисовки — процесса msedgewebview2), иначе ни нажатия, ни броска:
    поверх могут лежать чужие окна «поверх всех» (звонок sipgate 22.10)."""
    for x, y in points:
        h = u32.WindowFromPoint(wintypes.POINT(round(x), round(y)))
        root = u32.GetAncestor(h, 2) if h else 0                  # GA_ROOT
        pid = wintypes.DWORD()
        if root:
            u32.GetWindowThreadProcessId(root, ctypes.byref(pid))
        if pid.value not in pids:
            t = ctypes.create_unicode_buffer(128)
            if root:
                u32.GetWindowTextW(root, t, 128)
            raise Foreign(f"под ({x:.0f},{y:.0f}) чужое окно «{t.value}» (pid {pid.value}) — ввод не послан")


def path(a: tuple[float, float], b: tuple[float, float], n: int = 12) -> list[tuple[float, float]]:
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def windows_of(pid: int) -> list[tuple[int, str]]:
    found = []

    def each(hwnd, _lp):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u32.IsWindowVisible(hwnd):
            t = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, t, 256)
            found.append((hwnd, t.value))
        return True

    u32.EnumWindows(_ENUM(each), 0)
    return found


def rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def page_rect(main: int) -> tuple[int, int, int, int] | None:
    """Экран страницы программы: самый большой `Chrome_RenderWidgetHostHWND`
    окна (у полосы меню он в 32 px высотой)."""
    best: list = []

    def each(hwnd, _lp):
        c = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(hwnd, c, 64)
        if c.value == "Chrome_RenderWidgetHostHWND" and u32.IsWindowVisible(hwnd):
            l, t, r, b = rect(hwnd)
            best.append(((r - l) * (b - t), (l, t, r, b)))
        return True

    u32.EnumChildWindows(main, _ENUM(each), 0)
    return max(best)[1] if best else None


def on_top(hwnd: int, top: bool) -> None:
    # поверх всех без прав переднего плана; нажатие мыши само сделает окно активным
    u32.SetWindowPos(hwnd, -1 if top else -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)


def main_window(pid: int, timeout: float = 20.0) -> int:
    end = time.time() + timeout
    while time.time() < end:
        for hwnd, title in windows_of(pid):
            if title.startswith(TITLE):
                return hwnd
        time.sleep(0.2)
    return 0


# ---------- страница: что видно глазами CDP ----------

SPY_JS = """(() => {
  if (window.__dnd) return 1;
  const s = window.__dnd = {dragstart: 0, dragenter: 0, dragover: 0, drop: 0, dragend: 0,
                            move: 0, last: null, lit: false};
  for (const t of ['dragstart', 'dragenter', 'dragover', 'drop', 'dragend'])
    document.addEventListener(t, () => { s[t]++ }, true);
  document.addEventListener('mousemove', (e) => { s.move++; s.last = [e.clientX, e.clientY] }, true);
  new MutationObserver(() => { if (document.querySelector('.gcell.dropzone')) s.lit = true })
    .observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class']});
  return 1;
})()"""

GEOM_JS = """(() => {
  const b = document.querySelector('.gridbody [data-appt="%d"]');
  const col = document.querySelector('.gridbody .gcol[data-dk="%s"]');
  const c = col && col.querySelector('.gcell[data-h="%d"]');
  if (!b || !c) return null;
  const rb = b.getBoundingClientRect(), rc = c.getBoundingClientRect();
  return JSON.stringify({dpr: devicePixelRatio, src: [rb.left + rb.width / 2, rb.top + 8],
                         dst: [rc.left + rc.width / 2, rc.top + rc.height * 0.3],
                         vw: innerWidth, vh: innerHeight});
})()"""

DIAG_JS = """JSON.stringify({href: location.href, title: document.title,
  cols: Array.from(document.querySelectorAll('.gridbody .gcol')).map((c) => c.dataset.dk || ''),
  appts: Array.from(document.querySelectorAll('.gridbody [data-appt]')).map((b) => b.dataset.appt),
  hours: Array.from(document.querySelectorAll('.gridbody .gcol .gcell[data-h]')).slice(0, 20)
    .map((c) => c.dataset.h), text: document.body.innerText.slice(0, 300)})"""

DIALOG_JS = """(() => {
  const d = Array.from(document.querySelectorAll('dialog[open]'))
    .find((x) => x.textContent.includes('Mutare programare'));
  return JSON.stringify({open: !!d, text: d ? d.innerText.replace(/\\s+/g, ' ').slice(0, 300) : '',
                         spy: window.__dnd || null});
})()"""

YES_JS = """(() => {
  const d = Array.from(document.querySelectorAll('dialog[open]'))
    .find((x) => x.textContent.includes('Mutare programare'));
  const b = d && Array.from(d.querySelectorAll('button')).find((x) => x.textContent.trim() === 'Da, mută');
  if (!b) return 0;
  b.click();
  return 1;
})()"""


def to_screen(view: tuple[int, int, int, int], g: dict, p: list[float]) -> tuple[float, float]:
    return view[0] + p[0] * g["dpr"], view[1] + p[1] * g["dpr"]


def date_hint(target: dict) -> str:
    """Подсказка пустого поля даты так, как её рисует браузер: поля и
    разделители из теневого дерева браузера (`DOM.getDocument` с `pierce`)."""
    js(target, "(() => { let i = document.getElementById('__dp_date');"
               " if (!i) { i = document.createElement('input'); i.type = 'date'; i.id = '__dp_date';"
               " document.body.appendChild(i) } return 1 })()")
    root = cdp(target, "DOM.getDocument", depth=-1, pierce=True)["root"]

    def find(n: dict):
        a = n.get("attributes") or []
        if "id" in a[::2] and a[a.index("id") + 1] == "__dp_date":
            return n
        for k in (n.get("children") or []) + (n.get("shadowRoots") or []) + \
                ([n["contentDocument"]] if n.get("contentDocument") else []):
            got = find(k)
            if got:
                return got
        return None

    def text(n: dict) -> str:
        if n.get("nodeType") == 3:
            return n.get("nodeValue", "")
        return "".join(text(k) for k in (n.get("children") or []) + (n.get("shadowRoots") or []))

    def edit(n: dict):
        a = n.get("attributes") or []
        if "pseudo" in a[::2] and a[a.index("pseudo") + 1] == "-webkit-datetime-edit":
            return n
        for k in (n.get("children") or []) + (n.get("shadowRoots") or []):
            got = edit(k)
            if got:
                return got
        return None

    node = find(root)
    e = edit(node) if node else None
    return text(e).strip() if e else ""


def browser_args(profile: pathlib.Path) -> str:
    """Командная строка главного процесса WebView2 этого профиля."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" | "
          "Select-Object -ExpandProperty CommandLine")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout
    want = str(profile).lower()
    for line in out.splitlines():
        low = line.lower()
        if want in low and "--type=" not in low:
            return line.strip()
    return ""


# ---------- бросок файла: источник — окно WinForms, мышь — SendInput ----------

DROP_PS1 = r"""param([string]$Path, [string]$Mark)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$f = New-Object System.Windows.Forms.Form
$f.FormBorderStyle = 'None'; $f.TopMost = $true; $f.ShowInTaskbar = $false
$f.StartPosition = 'Manual'; $f.Location = New-Object System.Drawing.Point(40, 40)
$f.Size = New-Object System.Drawing.Size(180, 110); $f.BackColor = [System.Drawing.Color]::Gold
$f.Text = 'dp-drop-source'
$f.Add_MouseDown({
  $d = New-Object System.Windows.Forms.DataObject
  $c = New-Object System.Collections.Specialized.StringCollection
  [void]$c.Add($Path); $d.SetFileDropList($c)
  $r = $f.DoDragDrop($d, [System.Windows.Forms.DragDropEffects]'Copy, Move, Link')
  [IO.File]::WriteAllText($Mark + '.done', [string]$r)
  $f.Close()
})
$f.Add_Shown({ [IO.File]::WriteAllText($Mark, 'shown') })
[System.Windows.Forms.Application]::Run($f)
"""

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
       b"trailer<</Root 1 0 R>>\n%%EOF\n")


def drop_file(lab: Lab, pid: int, view: tuple[int, int, int, int]) -> dict:
    """PDF из «Проводника» (окно WinForms с CF_HDROP) — мышью на страницу.
    Окно-источник кладётся ПОВЕРХ страницы стенда: весь путь мыши — по своим
    окнам, чужое не получит даже наведения с файлом."""
    pdf = lab.dir / "fisa-aruncata.pdf"
    pdf.write_bytes(PDF)
    script = lab.dir / "drop_source.ps1"
    script.write_text(DROP_PS1, encoding="utf-8")
    mark = lab.dir / "drop.mark"
    proc, job = _start_in_own_job(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                                   "-File", str(script), "-Path", str(pdf), "-Mark", str(mark)],
                                  cwd=str(lab.dir))
    rep: dict = {}
    try:
        end = time.time() + 20
        while not mark.exists() and time.time() < end:
            time.sleep(0.1)
        src = next((h for h, t in windows_of(proc.pid) if t == "dp-drop-source"), 0)
        if not src:
            rep["error"] = "окно-источник не появилось"
            return rep
        l, t, r, b = rect(src)
        u32.SetWindowPos(src, -1, view[0] + 40, view[1] + 40, r - l, b - t, 0x0010 | 0x0040)
        time.sleep(0.3)
        l, t, r, b = rect(src)
        a = ((l + r) / 2, (t + b) / 2)
        dst = ((view[0] + view[2]) / 2, (view[1] + view[3]) / 2)
        wait_idle()
        guard((proc.pid,), a)
        guard((proc.pid, pid), *path(a, dst))
        guard((pid,), dst)
        move(*a)
        time.sleep(0.2)
        guard((proc.pid,), a)
        press()
        try:
            time.sleep(0.15)
            glide(a, (a[0] + 12, a[1] + 12), steps=4)
            time.sleep(0.3)                       # DoDragDrop источника
            glide((a[0] + 12, a[1] + 12), dst, steps=30)
            for i in range(6):
                move(dst[0] + (2 if i % 2 else -2), dst[1])
                time.sleep(0.08)
            release((pid,))                       # ⛔ бросок — только в окно оболочки стенда
        except BaseException:
            abort_drag(a, (proc.pid, pid))
            raise
        end = time.time() + 10
        while not (lab.dir / "drop.mark.done").exists() and time.time() < end:
            time.sleep(0.1)
        done = lab.dir / "drop.mark.done"
        rep["effect"] = done.read_text("utf-8").strip() if done.exists() else "?"
    finally:
        _end_job(job)
    return rep


# ---------- сценарий ----------

def drag_visit(target: dict, pid: int, view: tuple[int, int, int, int], g: dict) -> dict:
    """Визит d2 → колонка d3, 14:00: нажать, протянуть, отпустить — мышью ОС."""
    src, dst = to_screen(view, g, g["src"]), to_screen(view, g, g["dst"])
    mid = to_screen(view, g, [g["vw"] / 2, g["vh"] / 2])
    start = (src[0], src[1] + 14)
    pids = (pid,)
    wait_idle()
    guard(pids, mid, *path(src, start, 2), *path(start, dst))
    # сверка координат: курсор над серединой страницы — страница видит то же место
    move(mid[0] - 3, mid[1])
    time.sleep(0.1)
    move(*mid)
    time.sleep(0.3)
    seen = json.loads(js(target, "JSON.stringify(window.__dnd.last)") or "null")
    want = [round(g["vw"] / 2), round(g["vh"] / 2)]
    if not seen or abs(seen[0] - want[0]) > 2 or abs(seen[1] - want[1]) > 2:
        raise Foreign(f"страница не видит курсор стенда (видит {seen}, ждали {want}) — ввод не послан")
    move(*src)
    time.sleep(0.25)
    guard(pids, src, dst)
    press()
    try:
        time.sleep(0.12)
        glide(src, start, steps=5)
        time.sleep(0.35)                       # старт перетаскивания браузера
        glide(start, dst, steps=30)
        for i in range(6):
            move(dst[0] + (2 if i % 2 else -2), dst[1])
            time.sleep(0.08)
        lit = json.loads(js(target, DIALOG_JS))["spy"]["lit"]
        release(pids)
    except BaseException:
        abort_drag(src, pids)
        raise
    time.sleep(1.0)
    st = json.loads(js(target, DIALOG_JS))
    return {"calibration": seen, "dialog": st["open"], "text": st["text"], "spy": st["spy"],
            "lit_while_over": lit}


def quit_shell(lab: Lab, sh: Shell, target: dict | None) -> int | None:
    if target is None:
        return None
    sent = sc.page_eval(target, lab.origin, "window.dpShell ? (dpShell.send('win/quit'), 1) : 0")
    asked = sc.answer_dialog(sh.proc.pid, sc.QUIT_TEXT, 10.0) if sent == 1 else ""
    return sh.wait(sc.QUIT_LIMIT) if asked else None


def run(exe: pathlib.Path, shots: pathlib.Path | None, mouse: bool) -> dict:
    lab = Lab(exe)
    rep: dict = {"exe": str(exe)}
    sh = sh2 = None
    back = cursor()
    hwnd = 0
    try:
        sh = Shell(lab)
        target = wait_ready(lab, sh)
        rep["ready"] = target is not None
        if target is None:
            rep["log"] = lab.log_text()[-1500:]
            return rep
        rep["args"] = browser_args(lab.profile)

        # засев: визит у d2 на завтра (ни «прошлое», ни выходной: часы 7–21 всегда)
        day = (clinic_today() + datetime.timedelta(days=1)).isoformat()
        c = Client(lab.origin).login()
        r = add_appt(c, day, VISIT_AT, "Ion Popa", "069190190", doctor=FROM)
        rep["seed"] = r.msg
        visit = next(b["id"] for col in day_model(c, day)["canvas"]["columns"]
                     for b in col["blocks"] if b.get("kind") == "appt")
        cdp(target, "Network.setCookie", name="admin_auth", value=login_cookie(lab.origin),
            url=lab.origin + "/")
        cdp(target, "Page.navigate", url=f"{lab.origin}/admin/all?date={day}")
        geom = wait_js(target, GEOM_JS % (visit, TO, DROP_HOUR), 30.0)
        if not geom:
            rep["error"] = "сетка дня не отрисовалась"
            rep["page"] = js(target, DIAG_JS)
            return rep
        g = json.loads(geom)
        js(target, SPY_JS)

        hwnd = main_window(sh.proc.pid)
        view = page_rect(hwnd) if hwnd else None
        if not view:
            rep["error"] = "окно оболочки не найдено"
            return rep
        if not mouse:
            rep["refused"] = "без --mouse мышь не берётся: перенос и бросок файла не проверены"
        else:
            on_top(hwnd, True)
            time.sleep(0.5)
            try:
                rep["drag"] = drag_visit(target, sh.proc.pid, view, g)
            except Foreign as e:
                rep["refused"] = str(e)
        shot(target, shots, "drag-dialog")
        moved = None
        if (rep.get("drag") or {}).get("dialog") and js(target, YES_JS) == 1:
            end = time.time() + 10
            while time.time() < end and moved is None:
                for col in day_model(c, day)["canvas"]["columns"]:
                    if col.get("id") == TO and any(b["id"] == visit for b in col["blocks"]):
                        moved = True
                time.sleep(0.4)
        if rep.get("drag"):
            rep["drag"]["moved_to"] = TO if moved else None

        # ---- date: подсказка пустого поля даты ----
        rep["date"] = date_hint(target)
        js(target, "(() => { const i = document.getElementById('__dp_date');"
                   " i.style.cssText = 'position:fixed;top:80px;left:80px;z-index:99999;"
                   "font-size:18px;padding:6px'; return 1 })()")
        time.sleep(0.3)
        shot(target, shots, "date-field")
        js(target, "(() => { const i = document.getElementById('__dp_date'); if (i) i.remove(); return 1 })()")

        # ---- file: PDF мышью на страницу ----
        js(target, "window.__dpMark = 'same-page'")
        href = js(target, "location.href")
        log0 = len(lab.log_text())
        try:
            rep["file"] = drop_file(lab, sh.proc.pid, view) if "refused" not in rep else {}
        except Foreign as e:
            rep["refused"], rep["file"] = str(e), {}
        time.sleep(2.0)
        try:
            now_mark = js(target, "window.__dpMark || ''")
            now_href = js(target, "location.href")
        except (OSError, RuntimeError, ConnectionError):
            now_mark, now_href = "", ""
        tail = lab.log_text()[log0:]
        rep["file"].update({"same_page": now_mark == "same-page" and now_href == href,
                            "href": now_href, "log": [ln for ln in tail.splitlines()
                                                      if "file" in ln or "outside" in ln
                                                      or "download" in ln][:6]})
        on_top(hwnd, False)

        # ---- again: выход словом и сразу второй запуск ----
        rep["quit_code"] = quit_shell(lab, sh, target)
        sh.close()
        sh = None
        # ⚠️ порт свободен только между запусками: соседний прогон мог взять его
        if not sc.port_free(lab.port):
            lab.port = free_port()
        sh2 = Shell(lab)
        t2 = wait_ready(lab, sh2)
        log2 = lab.log_text()
        rep["again"] = {"ready": t2 is not None, "alive": sh2.proc.poll() is None,
                        "retries": len(re.findall(r"WebView2 \w+: not created \(try \d+\)", log2)),
                        "cannot_start": "cannot start: " in log2,
                        "panic": re.findall(r"PANIC .*", log2)}
        rep["again"]["quit_code"] = quit_shell(lab, sh2, t2)
    finally:
        try:
            if hwnd:
                on_top(hwnd, False)
            u32.SetCursorPos(*back)
        except OSError:
            pass
        for s in (sh, sh2):
            if s is not None:
                s.close()
        lab.drop()
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, help="собранный DentPilot.exe (cargo build)")
    ap.add_argument("--shots", help="папка для снимков (диалог переноса, поле даты)")
    ap.add_argument("--mouse", action="store_true",
                    help="взять мышь человека: ТОЛЬКО в окно, названное Олегом (без флага — "
                         "перенос и бросок файла не проверяются)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # ⚠️ координаты окна и курсора — в настоящих пикселях: иначе Windows
    # отдаёт масштабированные, и мышь промахнулась бы на экране 125%
    u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    shots = pathlib.Path(a.shots).resolve() if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    rep = run(pathlib.Path(a.exe).resolve(), shots, a.mouse)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    d = rep.get("drag") or {}
    f = rep.get("file") or {}
    ag = rep.get("again") or {}
    args = rep.get("args", "")
    want = {
        "окно поднялось с движком": rep.get("ready"),
        # ⛔ мышь не взята (за машиной работают, окно закрыто чужим) — не зелёное
        "ввод мыши шёл только в окна стенда": rep.get("ready") and "refused" not in rep,
        "drag: «Mutare programare» открылся от броска мышью": d.get("dialog"),
        "drag: ячейка подсветилась под курсором": d.get("lit_while_over") or (d.get("spy") or {}).get("lit"),
        f"drag: визит в базе у {TO}": d.get("moved_to") == TO,
        f"date: поле даты по-румынски ({RO_DATE})": rep.get("date") == RO_DATE,
        "date: браузер с --lang=ro": "--lang=ro" in args,
        "date: умолчания wry на месте": WRY_DEFAULT in args,
        "file: брошенный PDF ничего не открыл": bool(f.get("effect")) and f.get("same_page") and not any(
            "open outside" in ln for ln in f.get("log", [])),
        # ⚠️ иначе «ничего не открыл» зеленеет и там, где бросок не дошёл вовсе
        # (у обработчика Tauri файл съедается им самим)
        "file: бросок дошёл до WebView2 и отклонён молча": any(
            "dropped file not opened" in ln for ln in f.get("log", [])),
        "again: выход словом — код 0": rep.get("quit_code") == 0,
        "again: второй запуск подряд поднялся": ag.get("ready") and ag.get("alive"),
        "again: без cannot start и паники": ag and not ag.get("cannot_start") and not ag.get("panic"),
    }
    for k, v in want.items():
        print(f"   {'OK ' if v else 'RED'}  {k}")
    return 0 if all(want.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
