# -*- coding: utf-8 -*-
"""Кадры React-одонтограммы в headless Edge с проверкой геометрии (C22).

⛔ Не в CI и не в `.\\dev test`: нужны Edge и пакет websocket-client в
СИСТЕМНОМ Python (в .venv-desktop ничего не ставить — это окружение
сборки; сервер harness поднимает из .venv-desktop сам). Пациент —
test_odontogram_api._seed, флаг odontogram — в clinic.json песочницы.

Запуск из app\\:   python scripts\\odo_shots.py [--out DIR]

Сцены: обычная карта, выбранный зуб, выбранная поверхность, изменённое
несохранённое, инспектор крупно, режим моста, узкое окно (1200 и 1000),
после записи по Enter, навигация клавиатурой, контекстное меню. К каждой
— PNG и проверки геометрии: зубы не съехали и не наложились, номер у
своего зуба, инспектор не перекрывает дугу (справа от 1366, под дугой
ниже), скобка моста по своим зубам, выбранная поверхность совпадает с
подсветкой, ничего не обрезано, ошибок в консоли нет. Красная проверка —
код возврата 1; кадры остаются, чтобы посмотреть глазами. Ввод — настоящие
события мыши и клавиатуры через CDP, не dispatchEvent из скрипта.
"""
import argparse
import base64
import http.client
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# Консоль Windows живёт в cp1251, а отчёт печатает «→» и русские слова:
# без этого прогон падал бы UnicodeEncodeError на последней строке.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

try:
    import websocket  # noqa: E402  (websocket-client, системный Python)
except ImportError:  # pragma: no cover
    sys.exit("нужен пакет websocket-client в СИСТЕМНОМ Python: pip install websocket-client")

from harness import Client, Server  # noqa: E402
from test_odontogram_api import _seed  # noqa: E402

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
DEBUG_PORT = 9337
WIDE = (1500, 1000)

# Проверки геометрии — одна функция на все сцены, возвращает JSON.
CHECK_JS = r"""
(() => {
  const R = (el) => { const r = el.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height} }
  const out = { fails: [] }
  let teeth = 0
  for (const row of document.querySelectorAll('.odop .odo-view .arch')) {
    const rr = R(row)
    if (rr.w === 0) continue
    let prev = null
    for (const b of row.querySelectorAll('.tooth-btn')) {
      teeth++
      const n = b.dataset.n
      const num = b.querySelector('.num')
      const rb = R(b)
      if (!num || num.textContent !== n) out.fails.push('numar ' + n)
      else { const rn = R(num); if (rn.l < rb.l - 1 || rn.r > rb.r + 1 || rn.t < rb.t - 1 || rn.b > rb.b + 1) out.fails.push('numar in afara ' + n) }
      if (prev && rb.l < prev.r - 1) out.fails.push('suprapunere ' + n)
      if (rb.l < rr.l - 1 || rb.r > rr.r + 1) out.fails.push('taiat ' + n)
      prev = rb
    }
  }
  out.teeth = teeth
  const side = document.querySelector('.odop-side'), main = document.querySelector('.odop-main')
  if (side && main) {
    const a = R(side), m = R(main)
    if (!(a.l >= m.r - 1 || a.r <= m.l + 1 || a.t >= m.b - 1 || a.b <= m.t + 1)) out.fails.push('inspectorul acopera arcada')
    out.side_right = a.l >= m.r - 1
    out.side_below = a.t >= m.b - 1
  }
  out.brackets = 0
  for (const br of document.querySelectorAll('.br-arc')) {
    const m = /Punte (\d+)-(\d+)/.exec(br.title)
    const row = br.closest('.arch')
    if (!m || !row) { out.fails.push('acolada fara dinti'); continue }
    const b1 = row.querySelector(`.tooth-btn[data-n="${m[1]}"]`), b2 = row.querySelector(`.tooth-btn[data-n="${m[2]}"]`)
    if (!b1 || !b2) { out.fails.push('acolada: dintii lipsesc'); continue }
    const rb = R(br), r1 = R(b1), r2 = R(b2), rr = R(row)
    if (Math.abs(rb.l - Math.min(r1.l, r2.l)) > 3 || Math.abs(rb.r - Math.max(r1.r, r2.r)) > 3) out.fails.push('acolada nu acopera ' + br.title)
    if (rb.t < rr.t - 24 || rb.b > rr.b + 24) out.fails.push('acolada in afara randului ' + br.title)
    out.brackets++
  }
  const de = document.documentElement
  if (de.scrollWidth > de.clientWidth + 1) out.fails.push('scroll orizontal')
  const odop = document.querySelector('.odop')
  if (odop && R(odop).r > window.innerWidth + 1) out.fails.push('.odop mai lat decat fereastra')
  const sel = document.querySelector('.odop .arch .tooth-btn.sel')
  out.sel = sel ? sel.dataset.n : null
  const sf = document.querySelector('.insp .sfbtn.sel')
  out.sf = sf ? sf.dataset.s : null
  out.sf_state = sf ? ((Array.from(sf.classList).find(c => c.startsWith('sf-')) || '').slice(3)) : null
  const lab = document.querySelector('.insp .sfstate label b')
  out.sf_label = lab ? lab.textContent : null
  out.dirty = Array.from(document.querySelectorAll('.odop .arch .tooth-btn.dirty')).map(b => b.dataset.n)
  out.unsaved = Boolean(document.querySelector('.dp-draft'))
  const menu = document.querySelector('.dp-cmenu')
  out.menu = Boolean(menu)
  if (menu) { const r = R(menu); if (r.l < 0 || r.t < 0 || r.r > window.innerWidth || r.b > window.innerHeight) out.fails.push('meniul iese din fereastra') }
  out.br_mode = Boolean(document.querySelector('.br-bar'))
  out.picked = Array.from(document.querySelectorAll('.tooth-btn.br-pick')).map(b => b.dataset.n)
  const ae = document.activeElement
  out.focus = ae && ae.dataset && ae.dataset.n ? ae.dataset.n : (ae ? ae.tagName : null)
  const c = document.querySelector('.odop .arch .tooth-svg .sfz circle')
  out.hit_r = c ? getComputedStyle(c).r : null
  out.toast = (document.querySelector('.toastbox') || {}).textContent || null
  out.hist = document.querySelectorAll('.insp .th-r').length
  out.w = window.innerWidth
  out.h = de.scrollHeight
  return JSON.stringify(out)
})()
"""


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.n = 0
        self.events = []

    def cmd(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def drain(self, seconds):
        """Собрать события (ошибки консоли, исключения) за паузу."""
        end = time.time() + seconds
        self.ws.settimeout(0.2)
        try:
            while time.time() < end:
                try:
                    msg = json.loads(self.ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if "method" in msg:
                    self.events.append(msg)
        finally:
            self.ws.settimeout(30)

    def wait_event(self, name, timeout=15):
        end = time.time() + timeout
        self.ws.settimeout(max(0.5, timeout))
        try:
            while time.time() < end:
                msg = json.loads(self.ws.recv())
                if msg.get("method") == name:
                    return True
                if "method" in msg:
                    self.events.append(msg)
        except websocket.WebSocketTimeoutException:
            pass
        finally:
            self.ws.settimeout(30)
        return False

    def errors(self):
        out = []
        for e in self.events:
            if e["method"] == "Runtime.exceptionThrown":
                out.append(e["params"]["exceptionDetails"].get("text", "exception"))
            elif e["method"] == "Runtime.consoleAPICalled" and e["params"]["type"] == "error":
                out.append(" ".join(str(a.get("value", "")) for a in e["params"]["args"])[:200])
        self.events = []
        return out


class Page:
    """Страница под управлением: настоящий ввод через Input.*, проверки через Runtime."""

    KEYS = {"Enter": ("Enter", 13), "Escape": ("Escape", 27), "ArrowLeft": ("ArrowLeft", 37),
            "ArrowUp": ("ArrowUp", 38), "ArrowRight": ("ArrowRight", 39), "ArrowDown": ("ArrowDown", 40)}

    def __init__(self, cdp, origin):
        self.cdp = cdp
        self.origin = origin

    def go(self, path):
        self.cdp.cmd("Page.navigate", url=self.origin + path)
        self.cdp.wait_event("Page.loadEventFired", timeout=15)
        self.cdp.drain(1.5)

    def js(self, expr):
        r = self.cdp.cmd("Runtime.evaluate", returnByValue=True, expression=expr)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("text"))
        return r["result"].get("value")

    def check(self):
        return json.loads(self.js(CHECK_JS))

    def center(self, finder):
        """finder — JS-выражение, дающее элемент; центр его прямоугольника."""
        v = self.js(f"(() => {{ const el = {finder}; if (!el) return null; const r = el.getBoundingClientRect();"
                    f" return JSON.stringify([r.left + r.width / 2, r.top + r.height / 2]) }})()")
        if v is None:
            raise RuntimeError(f"нет элемента: {finder}")
        return json.loads(v)

    def click(self, finder, button="left"):
        x, y = self.center(finder)
        m = self.cdp.cmd
        m("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        m("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=1)
        m("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=1)
        self.cdp.drain(0.3)

    def key(self, name):
        if name in self.KEYS:
            key, vk = self.KEYS[name]
            self.cdp.cmd("Input.dispatchKeyEvent", type="keyDown", key=key, code=key, windowsVirtualKeyCode=vk)
            self.cdp.cmd("Input.dispatchKeyEvent", type="keyUp", key=key, code=key, windowsVirtualKeyCode=vk)
        else:
            code = "Key" + name.upper()
            self.cdp.cmd("Input.dispatchKeyEvent", type="keyDown", key=name, code=code, text=name,
                         windowsVirtualKeyCode=ord(name.upper()))
            self.cdp.cmd("Input.dispatchKeyEvent", type="keyUp", key=name, code=code, windowsVirtualKeyCode=ord(name.upper()))
        self.cdp.drain(0.3)

    def size(self, w, h):
        self.cdp.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
        self.cdp.drain(0.4)

    def png(self, path, clip=None, full=True):
        args = {"format": "png"}
        if clip:
            x, y, w, h = clip
            args["clip"] = {"x": x, "y": y, "width": w, "height": h, "scale": 1}
        elif full:
            args["captureBeyondViewport"] = True
        data = self.cdp.cmd("Page.captureScreenshot", **args)["data"]
        pathlib.Path(path).write_bytes(base64.b64decode(data))


def login_cookie(origin):
    host, port = origin.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    body = urllib.parse.urlencode({"password": "test1234", "next": "/admin"})
    conn.request("POST", "/admin/login", body, {"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    set_cookie = resp.getheader("Set-Cookie") or ""
    resp.read()
    conn.close()
    m = re.search(r"admin_auth=([^;]+)", set_cookie)
    if not m:
        raise SystemExit(f"нет куки в ответе {resp.status}: {set_cookie!r}")
    return m.group(1)


def start_edge(profile, port=DEBUG_PORT):
    edge = next((p for p in EDGE_CANDIDATES if os.path.exists(p)), None)
    if not edge:
        raise SystemExit("msedge.exe не найден")
    proc = subprocess.Popen([
        edge, "--headless=new", f"--remote-debugging-port={port}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "--no-first-run", "--disable-gpu", "--hide-scrollbars",
        # ⛔ (09-24) без флага Edge качает в профиль свои компоненты: профиль, проживший
        # ~30 мин, дорастает до ~440 МБ — двенадцать брошенных съели 5 ГБ в TEMP
        "--disable-component-update",
        f"--window-size={WIDE[0]},{WIDE[1]}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    target = None
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                pages = [t for t in json.load(r) if t.get("type") == "page"]
            if pages:
                target = pages[0]
                break
        except Exception:
            pass
        time.sleep(0.3)
    if not target:
        proc.kill()
        raise SystemExit("Edge не поднял страницу")
    return proc, target["webSocketDebuggerUrl"]


BTN = "document.querySelector('.odop .arch .tooth-btn[data-n=\"{n}\"]')"
PIC = "document.querySelector('.insp-pic [data-s=\"{s}\"]')"
BY_TEXT = "Array.from(document.querySelectorAll('{sel}')).find(b => b.textContent.includes('{text}'))"


def run(out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    results = []

    def scene(page, name, expect, clip=None, full=True):
        st = page.check()
        fails = list(st["fails"])
        for k, v in expect.items():
            if st.get(k) != v:
                fails.append(f"{k}: ожидалось {v!r}, получено {st.get(k)!r}")
        errs = page.cdp.errors()
        fails += [f"consola: {e}" for e in errs]
        if full and not clip:
            page.size(st["w"], min(3200, st["h"] + 40))
        page.png(out / f"{name}.png", clip=clip, full=full)
        if full and not clip:
            page.size(st["w"], WIDE[1] if st["w"] == WIDE[0] else 900)
        results.append((name, fails, st))
        mark = "OK " if not fails else "RED"
        print(f"{mark} {name}: sel={st['sel']} sf={st['sf']}/{st['sf_state'] or '-'} dirty={st['dirty']} "
              f"teeth={st['teeth']} brackets={st['brackets']} side={'right' if st.get('side_right') else 'below' if st.get('side_below') else '-'}")
        for f in fails:
            print("    ", f)

    s1 = Server(keep_dir=True)
    with s1:
        c = Client(s1.url).login()
        pid = _seed(c)["pid"]
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["odontogram", "patient_card"]}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    profile = os.path.join(os.environ["TEMP"], "dp-edge-odo-shots")
    s2 = Server(dir_=s1.dir)
    proc = None
    try:
        with s2:
            origin = s2.url
            cookie = login_cookie(origin)
            proc, ws_url = start_edge(profile)
            cdp = CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=origin + "/")
            page = Page(cdp, origin)
            page.size(*WIDE)
            path = f"/admin/patient/{pid}/odontograma"

            # 1. обычная карта
            page.go(path)
            scene(page, "01_chart", {"sel": None, "unsaved": False, "menu": False})
            # 2. выбранный зуб из адреса — в фокусе, инспектор справа
            page.go(path + "?t=16")
            scene(page, "02_selected", {"sel": "16", "focus": "16", "side_right": True, "sf": "M"})
            # 3. выбранная поверхность: клик по D на рисунке инспектора — только выбор
            page.click(PIC.format(s="D"))
            scene(page, "03_surface", {"sel": "16", "sf": "D", "sf_label": "D", "sf_state": "", "unsaved": False, "dirty": []})
            # 4. повторный клик — быстрый цикл, черновик явный
            page.click(PIC.format(s="D"))
            scene(page, "04_dirty", {"sel": "16", "sf": "D", "sf_state": "carie", "unsaved": True, "dirty": ["16"]})
            # 5. инспектор крупно (кадр по его прямоугольнику)
            rect = json.loads(page.js("(() => { const r = document.querySelector('.odop-side').getBoundingClientRect();"
                                      " return JSON.stringify([r.left, r.top + window.scrollY, r.width, r.height]) })()"))
            scene(page, "05_inspector", {"unsaved": True}, clip=rect)
            # 6. режим моста: Esc снимает черновик, «Punte nouă», три зуба
            page.key("Escape")
            page.click(BY_TEXT.format(sel=".odo-actions button", text="Punte nouă"))
            for n in (24, 25, 26):
                page.click(BTN.format(n=n))
            scene(page, "06_bridge", {"br_mode": True, "picked": ["24", "25", "26"], "unsaved": False, "dirty": []})
            page.key("Escape")
            # 7. узкое окно: 1200 — инспектор под дугой; 1000 — цели поверхностей крупнее
            page.click(BTN.format(n=16))
            page.size(1200, 900)
            scene(page, "07_narrow_1200", {"sel": "16", "side_below": True, "br_mode": False})
            page.size(1000, 800)
            scene(page, "08_narrow_1000", {"sel": "16", "side_below": True, "hit_r": "7.5px"})
            page.size(*WIDE)
            # 8. после записи по Enter: D → carie, фокус на зубе внутри карты
            page.go(path + "?t=16")
            hist0 = page.check()["hist"]
            page.click(PIC.format(s="D"))
            page.click(PIC.format(s="D"))
            page.key("Enter")
            page.cdp.drain(1.2)
            st = page.check()
            scene(page, "09_saved", {"sel": "16", "sf": "D", "sf_state": "carie", "unsaved": False, "dirty": [], "hist": hist0 + 1})
            if not st["toast"]:
                results[-1][1].append("после записи нет плашки сервера")
            # 9. навигация клавиатурой: 16 → 14 → 44, буква v
            page.key("ArrowRight")
            page.key("ArrowRight")
            page.key("ArrowDown")
            page.key("v")
            scene(page, "10_keyboard", {"sel": "44", "focus": "44", "sf": "V"})
            # 10. контекстное меню правой кнопкой по 21, затем «Coroană» — в черновик
            page.click(BTN.format(n=21), button="right")
            scene(page, "11_menu", {"menu": True, "sel": "44"}, full=False)
            page.click(BY_TEXT.format(sel=".dp-cmenu button", text="Coroană"))
            scene(page, "12_menu_applied", {"menu": False, "sel": "21", "dirty": ["21"], "unsaved": True})
    finally:
        if proc:
            proc.kill()
        s1.drop()
        shutil.rmtree(profile, ignore_errors=True)

    red = [(n, f) for n, f, _ in results if f]
    print()
    print(f"кадров: {len(results)}, красных: {len(red)} → {out}")
    return 1 if red else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "odo"), help="куда класть PNG")
    args = ap.parse_args()
    sys.exit(run(pathlib.Path(args.out)))


if __name__ == "__main__":
    main()
