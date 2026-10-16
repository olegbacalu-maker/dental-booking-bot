# -*- coding: utf-8 -*-
"""Стенд стиля «Sticlă» (16.10): кадры живых поверхностей, скорость прокрутки,
ответ на prefers-reduced-transparency.

    python scripts\\glass_shots.py [--styles clar,sticla] [--out DIR]

⛔ Не в CI и не в `.\\dev test`: нужен Edge и websocket-client в СИСТЕМНОМ
Python (в .venv-desktop ничего не ставить — это окружение сборки).

Зачем отдельно от look_sweep. Тот снимает экраны в покое: меню карточки,
окно записи, Ctrl K и тост там не открыты, а именно они у стекла получают
размытие (--surface-live). И скорость: размытие под липкой шапкой врачей
пересчитывается на каждом кадре прокрутки — look_sweep этого не меряет.

Сцены, на каждый стиль:
  Ключ --gpu поднимает Edge без --disable-gpu (растр через GPU, как у
  WebView2 клиники) — для сцены scroll это и есть честная цифра.
  dash    — панель дня в окне (не вся страница: фон окна у стекла
            `background-attachment:fixed`, и кадр «за окном» белый по
            построению, это не дефект);
  menu    — меню карточки визита (правый щелчок по блоку);
  ctrlk   — быстрый поиск;
  dialog  — окно «Programare nouă»;
  narrow  — телефон 390×844, прокрученный: таб-бар снизу над содержимым;
  scroll  — кадры прокрутки страницы под липкой шапкой: среднее / p95 /
            максимум мс между кадрами rAF. ⚠️ Headless Edge здесь без GPU
            (--disable-gpu, см. odo_shots.start_edge): размытие считается
            программно, то есть ЦИФРЫ ПЕССИМИСТИЧНЫ — у клиники WebView2 с
            GPU. Сравнивать стили между собой, а не с 16 мс буквально;
  reduce  — только у стекла: что отвечает matchMedia(prefers-reduced-
            transparency) при нынешней настройке Windows и становится ли
            стекло сплошным под эмуляцией `reduce` (CDP Emulation).

Итог печатается строками «OK/RED …» и JSON в <out>/summary.json.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import Client, Server, clinic_today  # noqa: E402
from odo_shots import CDP, Page, login_cookie, start_edge  # noqa: E402

# ⛔ Свой порт отладки: 9337–9353 и 9360 заняты соседними стендами; запуск на
# занятом МОЛЧА подключается к чужому браузеру.
PORT = 9361
WIDE = (1500, 950)
SCROLL_WIN = (1366, 700)
OUT = ROOT / "build" / "shots" / "glass"

SCROLL_JS = """new Promise((done) => {
  window.scrollTo(0, 0);
  const t = [];
  let last = performance.now(), n = 0;
  const step = () => {
    const now = performance.now(); t.push(now - last); last = now;
    window.scrollBy(0, 8);
    if (++n < 90 && window.scrollY + window.innerHeight < document.body.scrollHeight - 8) requestAnimationFrame(step);
    else {
      const s = t.slice(1).sort((a, b) => a - b);
      const q = (p) => s[Math.min(s.length - 1, Math.floor(s.length * p))];
      done(JSON.stringify({ frames: s.length, avg: +(s.reduce((a, b) => a + b, 0) / s.length).toFixed(1),
        p95: +q(.95).toFixed(1), max: +s[s.length - 1].toFixed(1), scrolled: window.scrollY }));
    }
  };
  requestAnimationFrame(step);
})"""


def settle(page: Page, timeout: float = 8.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if page.js("(() => { const r = document.querySelector('.dp-react-root');"
                   " const root = document.getElementById('root'); if (root && !r) return false;"
                   " if (r && r.getAttribute('aria-busy') === 'true') return false;"
                   " return document.readyState === 'complete' })()"):
            break
        time.sleep(0.2)
    page.cdp.drain(0.6)


def wait_for(page: Page, finder: str, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if page.js(f"!!({finder})"):
            page.cdp.drain(0.4)
            return True
        time.sleep(0.1)
    return False


def seed(c: Client, day: str) -> None:
    for i, (t, dk, name) in enumerate([("09:00", "d2", "Proba Unu"), ("10:30", "d2", "Proba Doi"),
                                        ("11:00", "d3", "Proba Trei"), ("14:00", "d4", "Proba Patru"),
                                        ("15:30", "d3", "Proba Cinci")]):
        r = c.post_json("/api/schedule/appointments", {"date": day, "time": t, "doctor": dk,
                                                       "service": "consult", "name": name,
                                                       "phone": f"0690000{i:02d}"})
        if r.status != 200:
            raise SystemExit(f"засев: HTTP {r.status} {r.body[:200]}")


def js_eval_promise(page: Page, expr: str):
    r = page.cdp.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
    if "exceptionDetails" in r:
        raise RuntimeError(r["exceptionDetails"].get("text"))
    return r["result"].get("value")


def start_edge_gpu(profile: str, port: int):
    """Как odo_shots.start_edge, но БЕЗ --disable-gpu: у клиники WebView2 рисует
    через GPU, и размытие там стоит иначе, чем в программном растеризаторе."""
    import urllib.request
    from odo_shots import EDGE_CANDIDATES
    edge = next((p for p in EDGE_CANDIDATES if os.path.exists(p)), None)
    if not edge:
        raise SystemExit("msedge.exe не найден")
    proc = subprocess.Popen([
        edge, "--headless=new", f"--remote-debugging-port={port}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "--no-first-run", "--hide-scrollbars",
        "--disable-component-update", "--enable-gpu-rasterization", "--ignore-gpu-blocklist",
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


def run(styles: list[str], out: pathlib.Path, gpu: bool = False) -> int:
    out.mkdir(parents=True, exist_ok=True)
    day = clinic_today().isoformat()
    summary: dict = {}
    red: list[str] = []
    profile = os.path.join(os.environ["TEMP"], "dp-edge-glass")
    proc = None
    with Server() as s:
        api = Client(s.url).login()
        seed(api, day)
        try:
            proc, ws_url = (start_edge_gpu if gpu else start_edge)(profile + ("-gpu" if gpu else ""), PORT)
            cdp = CDP(ws_url)
            for dom in ("Network", "Runtime", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=login_cookie(s.url), url=s.url + "/")
            page = Page(cdp, s.url)
            for style in styles:
                r = api.post_json("/api/settings/theme", {"style": style, "primary": "#0E9F8A",
                                                          "custom": "", "menu": "soft", "font": "inter"})
                if r.status != 200:
                    raise SystemExit(f"стиль {style!r}: HTTP {r.status}")
                sdir = out / style
                sdir.mkdir(exist_ok=True)
                res: dict = {}
                page.size(*WIDE)
                page.go(f"/admin?date={day}")
                settle(page)
                page.png(sdir / "dash.png", full=False)

                # меню карточки
                page.click("document.querySelector('.gridbody [data-appt]')", button="right")
                ok = wait_for(page, "document.querySelector('.dp-cmenu')")
                res["menu"] = ok
                page.png(sdir / "menu.png", full=False)
                page.key("Escape")
                page.cdp.drain(0.3)

                # Ctrl K
                page.cdp.cmd("Input.dispatchKeyEvent", type="keyDown", key="k", code="KeyK",
                             modifiers=2, windowsVirtualKeyCode=75)
                page.cdp.cmd("Input.dispatchKeyEvent", type="keyUp", key="k", code="KeyK",
                             modifiers=2, windowsVirtualKeyCode=75)
                ok = wait_for(page, "document.querySelector('.dp-qf')")
                res["ctrlk"] = ok
                page.png(sdir / "ctrlk.png", full=False)
                page.key("Escape")
                page.cdp.drain(0.3)

                # окно записи
                page.click("document.querySelector('.top .newbtn')")
                ok = wait_for(page, "document.querySelector('dialog[open]')")
                res["dialog"] = ok
                page.png(sdir / "dialog.png", full=False)
                page.key("Escape")
                page.cdp.drain(0.3)

                # узкий экран: меню — таб-бар снизу (fixed, у стекла с размытием)
                page.size(390, 844)
                page.go(f"/admin?date={day}")
                settle(page)
                page.js("window.scrollTo(0, 260)")
                page.cdp.drain(0.4)
                page.png(sdir / "narrow.png", full=False)

                # прокрутка под липкой шапкой
                page.size(*SCROLL_WIN)
                page.go(f"/admin?date={day}")
                settle(page)
                res["scroll"] = json.loads(js_eval_promise(page, SCROLL_JS))
                if style == "sticla":
                    # откуда цена: по одному слагаемому материала за раз
                    variants = {
                        "no_head_blur": ("document.querySelectorAll('.gridcard>.gridhead').forEach(h => {"
                                         " h.style.backdropFilter = 'none'; h.style.webkitBackdropFilter = 'none' })",
                                         "document.querySelectorAll('.gridcard>.gridhead').forEach(h => {"
                                         " h.style.backdropFilter = ''; h.style.webkitBackdropFilter = '' })"),
                        "no_blur_at_all": ("document.documentElement.style.setProperty('--glass-blur', 'none');"
                                           "document.documentElement.style.setProperty('--top-blur', 'none')",
                                           "document.documentElement.style.removeProperty('--glass-blur');"
                                           "document.documentElement.style.removeProperty('--top-blur')"),
                        "no_noise": ("document.documentElement.style.setProperty('--noise-a', '0')",
                                     "document.documentElement.style.removeProperty('--noise-a')"),
                        "bg_scroll_not_fixed": ("document.body.style.backgroundAttachment = 'scroll'",
                                                "document.body.style.backgroundAttachment = ''"),
                        "solid_surfaces": ("for (const k of ['--surface','--surface-live','--top-live'])"
                                           " document.documentElement.style.setProperty(k, '#fff');"
                                           "document.documentElement.style.setProperty('--side-a', '100%')",
                                           "for (const k of ['--surface','--surface-live','--top-live','--side-a'])"
                                           " document.documentElement.style.removeProperty(k)"),
                    }
                    for name, (on, off) in variants.items():
                        page.js(on)
                        page.cdp.drain(0.3)
                        res["scroll_" + name] = json.loads(js_eval_promise(page, SCROLL_JS))
                        page.js(off)
                        page.cdp.drain(0.2)

                # prefers-reduced-transparency
                if style == "sticla":
                    page.size(*WIDE)
                    page.go(f"/admin?date={day}")
                    settle(page)
                    res["reduce_now"] = page.js("matchMedia('(prefers-reduced-transparency: reduce)').matches")
                    res["surface_glass"] = page.js(
                        "getComputedStyle(document.documentElement).getPropertyValue('--surface').trim()")
                    cdp.cmd("Emulation.setEmulatedMedia",
                            features=[{"name": "prefers-reduced-transparency", "value": "reduce"}])
                    page.cdp.drain(0.6)
                    res["reduce_emulated"] = page.js("matchMedia('(prefers-reduced-transparency: reduce)').matches")
                    res["surface_reduced"] = page.js(
                        "getComputedStyle(document.documentElement).getPropertyValue('--surface').trim()")
                    res["blur_reduced"] = page.js(
                        "getComputedStyle(document.querySelector('.top')).backdropFilter")
                    page.png(sdir / "reduce.png", full=False)
                    cdp.cmd("Emulation.setEmulatedMedia", features=[])
                    page.cdp.drain(0.3)
                summary[style] = res
        finally:
            if proc:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)

    for style, res in summary.items():
        for scene in ("menu", "ctrlk", "dialog"):
            (print if res.get(scene) else red.append)(f"{'OK' if res.get(scene) else 'RED'} {style}/{scene}: "
                                                      f"{'открылось' if res.get(scene) else 'не открылось'}")
        sc = res["scroll"]
        print(f"OK {style}/scroll: {sc['frames']} кадров, среднее {sc['avg']} мс, p95 {sc['p95']} мс, "
              f"max {sc['max']} мс, прокручено {sc['scrolled']}px")
        for k, v in res.items():
            if k.startswith("scroll_"):
                print(f"   {k[7:]}: среднее {v['avg']} мс, p95 {v['p95']} мс, max {v['max']} мс")
        if "reduce_now" in res:
            solid = res["surface_reduced"].lower() in ("#ffffff", "rgb(255, 255, 255)", "var(--panel)")
            line = (f"{style}/reduce: сейчас matchMedia={res['reduce_now']}; под эмуляцией "
                    f"matchMedia={res['reduce_emulated']}, --surface {res['surface_glass'][:40]!r} → "
                    f"{res['surface_reduced']!r}, blur шапки {res['blur_reduced']!r}")
            if res["reduce_emulated"] and solid and res["blur_reduced"] == "none":
                print("OK " + line)
            else:
                red.append("RED " + line)
    for ln in red:
        print(ln)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"кадры и summary.json → {out}")
    print("ЧИСТО" if not red else f"КРАСНЫХ: {len(red)}")
    return 1 if red else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--styles", default="clar,sticla")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--gpu", action="store_true", help="Edge с GPU (как WebView2 у клиники)")
    a = ap.parse_args()
    return run([s for s in a.styles.split(",") if s], pathlib.Path(a.out), gpu=a.gpu)


if __name__ == "__main__":
    sys.exit(main())
