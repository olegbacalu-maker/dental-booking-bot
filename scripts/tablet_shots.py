# -*- coding: utf-8 -*-
"""Базовая линия «DentPilot на планшете у кресла» (26.09, до всякой правки).

Олег 26.09: планшет врача над креслом — «вот здесь смысл локальной сети»;
поддерживать и iPad, и Android («буду спрашивать у всех, какие у них
планшеты»). Стенд снимает, как журнал выглядит и слушается пальца СЕЙЧАС.

iPad (810×1080, «настольный» Safari: UA Mac, mobile=False) и Android-планшет
(800×1280, mobile=True), по две ориентации, касания вместо мыши. Экраны:
панель, день всех врачей, фиша на вкладке Odontogramă и Vizite, детальная
одонтограмма. Замеры: переполнение по ширине, (pointer:coarse) и высота
контролов, мелкие (<40px) цели под палец по видам, касание зуба выбирает
его, долгое нажатие открывает меню зуба, падение на «Interfața nouă nu s-a
încărcat». Кадры — PNG в --out, замеры — measure.json там же.

⚠️ Это Chromium с эмуляцией касаний, а НЕ WebKit: поведение Safari на iPad
(долгое нажатие не шлёт contextmenu, backdrop-filter без префикса только с 18,
клавиатура и вьюпорт, камера в <input capture>) отсюда не проверяется —
только вёрстка, касание и медиазапросы. Первый живой iPad проверяет остальное.
⚠️ Профиль клиники — БЕЗ ключа `ui.react` (так у установки: React везде, где
есть): фикстура наборов держит `[]`, то есть старый интерфейс, и снимки
показали бы не то, что увидит врач.

⛔ Не в CI и не в `.\\dev test`: нужны Edge и websocket-client в СИСТЕМНОМ
Python (как у odo_shots.py, чьи CDP/Page/start_edge здесь и живут). Порт и
профиль Edge — свои (9483, dp-edge-tablet): чужой браузер на общем порту
не трогаем, свой гасим по имени профиля (прайор prior-cdp-port-shared).

Запуск из app\\ (PowerShell):   python scripts\\tablet_shots.py [--out DIR]
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import odo_shots as odo  # noqa: E402  (CDP, Page, login_cookie, start_edge, BTN)
from harness import Client, Server  # noqa: E402
from test_odontogram_api import _seed  # noqa: E402

PORT = 9483
PROFILE = os.path.join(os.environ["TEMP"], "dp-edge-tablet")

IPAD_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
           "(KHTML, like Gecko) Version/17.5 Safari/605.1.15")
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# (имя, ширина, высота, mobile-вьюпорт, UA). iPad 10.2" — 810×1080 CSS px.
DEVICES = [
    ("ipad_portrait", 810, 1080, False, IPAD_UA),
    ("ipad_landscape", 1080, 810, False, IPAD_UA),
    ("android_portrait", 800, 1280, True, ANDROID_UA),
    ("android_landscape", 1280, 800, True, ANDROID_UA),
]

MEASURE_JS = r"""
(() => {
  const W = innerWidth, H = innerHeight;
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
      && r.bottom > 0 && r.top < H && r.right > 0 && r.left < W; };
  const els = [...document.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab]')].filter(vis);
  const small = els.filter(e => { const r = e.getBoundingClientRect(); return r.width < 40 || r.height < 40; });
  const name = e => ((e.getAttribute('aria-label') || e.textContent || e.getAttribute('name') || e.className || e.tagName) + '')
    .replace(/\s+/g, ' ').trim().slice(0, 28);
  const sz = e => { const r = e.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height); };
  const kinds = {};
  small.forEach(e => { const k = e.classList.contains('tooth-btn') ? 'dinte' : (e.closest('nav,aside,.side,.rail') ? 'meniu' : 'alte');
    kinds[k] = (kinds[k] || 0) + 1; });
  const insp = document.querySelector('.odop-side');
  const ir = insp && insp.getBoundingClientRect();
  return JSON.stringify({
    W, H, overflowX: document.documentElement.scrollWidth - W,
    coarse: matchMedia('(pointer: coarse)').matches, hoverNone: matchMedia('(hover: none)').matches,
    touch: navigator.maxTouchPoints, ctl: getComputedStyle(document.documentElement).getPropertyValue('--h-ctl').trim(),
    targets: els.length, small: small.length, kinds,
    sample: small.filter(e => !e.classList.contains('tooth-btn')).slice(0, 6).map(e => name(e) + ' ' + sz(e)),
    menu: !!document.querySelector('.dp-cmenu'),
    sel: (document.querySelector('.odop .arch .tooth-btn.sel') || {}).dataset?.n || null,
    // инспектор зуба виден на экране без прокрутки? (главный вопрос «у кресла»)
    insp_top: ir ? Math.round(ir.top) : null, insp_visible: ir ? (ir.top < H - 80 && ir.bottom > 0) : null,
    fallback: /Interfața nouă nu s-a încărcat/.test(document.body.textContent),
  });
})()
"""


def touch(page, x, y, hold=0.0):
    """Касание пальцем: touchStart → (удержание) → touchEnd."""
    m = page.cdp.cmd
    m("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    if hold:
        page.cdp.drain(hold)
    m("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    page.cdp.drain(0.6)


def port_free(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
        return False
    except Exception:
        return True


def kill_profile():
    """Гасить СВОЙ Edge по имени профиля — не чужие браузеры других сессий."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*dp-edge-tablet*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def run(out: pathlib.Path) -> int:
    if not port_free(PORT):
        sys.exit(f"порт {PORT} занят — чужой браузер, не трогаю")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    s = Server()
    s._own_dir = False
    with s:
        pid = _seed(Client(s.url).login())["pid"]
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)              # как у установки: React везде, где он есть
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    s2 = Server(dir_=s.dir)
    proc = None
    try:
        with s2:
            origin = s2.url
            cookie = odo.login_cookie(origin)
            proc, ws_url = odo.start_edge(PROFILE, port=PORT)
            cdp = odo.CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=origin + "/")
            page = odo.Page(cdp, origin)
            for name, w, h, mobile, ua in DEVICES:
                cdp.cmd("Network.setUserAgentOverride", userAgent=ua)
                cdp.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                        deviceScaleFactor=2, mobile=mobile)
                cdp.cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
                scenes = [("panou", "/admin"), ("zi", "/admin/all"),
                          ("fisa_odonto", f"/admin/patient/{pid}?tab=odonto"),
                          ("fisa_vizite", f"/admin/patient/{pid}?tab=vizite"),
                          ("odontograma", f"/admin/patient/{pid}/odontograma")]
                for sc, path in scenes:
                    page.go(path)
                    cdp.drain(0.8)
                    m = json.loads(page.js(MEASURE_JS))
                    m["errors"] = cdp.errors()
                    page.png(out / f"{name}__{sc}.png", full=False)
                    if sc in ("fisa_odonto", "odontograma"):
                        # касание зуба 16 → выбран, и где инспектор; долгое нажатие на 21 → меню?
                        try:
                            x, y = page.center(odo.BTN.format(n=16))
                            touch(page, x, y)
                            t = json.loads(page.js(MEASURE_JS))
                            m.update(tap_sel=t["sel"], insp_top=t["insp_top"], insp_visible=t["insp_visible"])
                            page.png(out / f"{name}__{sc}_tap.png", full=False)
                            x, y = page.center(odo.BTN.format(n=21))
                            touch(page, x, y, hold=0.9)
                            m["longpress_menu"] = json.loads(page.js(MEASURE_JS))["menu"]
                        except RuntimeError as e:
                            m["tap_error"] = str(e)
                    rows.append((name, sc, m))
                    print(f"{name:18} {sc:12} W={m['W']:4} overX={m['overflowX']:4} "
                          f"coarse={m['coarse']!s:5} ctl={m['ctl'] or '-':5} "
                          f"small={m['small']:3}/{m['targets']:<3} {m['kinds']} "
                          + (f"tap={m.get('tap_sel')} panou_vizibil={m.get('insp_visible')}"
                             f"(top={m.get('insp_top')}) long={m.get('longpress_menu')} "
                             if "tap_sel" in m else "")
                          + ("FALLBACK " if m["fallback"] else "")
                          + (f"err={m['errors'][:2]}" if m["errors"] else ""))
                    if m["sample"]:
                        print(" " * 32 + "mici: " + " | ".join(m["sample"]))
    finally:
        if proc:
            proc.kill()
        kill_profile()
        time.sleep(0.5)
        shutil.rmtree(PROFILE, ignore_errors=True)
        shutil.rmtree(s.dir, ignore_errors=True)
    (out / "measure.json").write_text(json.dumps(
        [{"device": d, "scene": sc, **m} for d, sc, m in rows], ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\nкадры и measure.json → {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "tablet"), help="куда класть PNG")
    sys.exit(run(pathlib.Path(ap.parse_args().out)))
