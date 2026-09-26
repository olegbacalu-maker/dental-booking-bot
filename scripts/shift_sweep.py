# -*- coding: utf-8 -*-
"""Сдвиги раскладки ПОСЛЕ первого кадра содержимого — на каждом экране React.

    python scripts\\shift_sweep.py [--out FILE]

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. С B4 экраны сменяются без перезагрузки, и всё, что раньше выглядело
«появлением страницы», теперь выглядит «прыжком»: второй запрос после
монтирования (одонтограмма в фише до 1.31.2 роняла всё под собой на 336 px),
картинка без зарезервированного места, замер после отрисовки. Глазами это
ловится по одному экрану в день (Олег, канарейка 25.09); здесь — все экраны
разом, метрикой `layout-shift` (PerformanceObserver), а не впечатлением.

Что считается. Для каждого адреса из карты экранов (`screen_map.FLAG`,
параметры — из засева) страница открывается документом; момент «содержимое
на месте» — первый кадр, где узел React не пуст и не `aria-busy`; сдвиги
ПОСЛЕ него (плюс один кадр на дорисовку) и без участия пользователя — это и
есть прыжок. Порог — суммарно 0.01: ниже — подпись шириной в пиксель, выше —
видно.

⛔ Пара: у экрана, который грузит часть себя вторым запросом (мутант —
`OdontogramCard` со своим запросом вместо засева), стенд обязан краснеть.
Проверено на 1.31.1 против 1.31.2: 0.046 → 0.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import screen_map  # noqa: E402
from harness import Client, Server, clinic_today  # noqa: E402
from mount_sweep import PIN, fill, pin_cookie, preconditions, seed  # noqa: E402
from odo_shots import CDP, Page, start_edge  # noqa: E402

WIDE = (1500, 950)
# ⛔ Свой порт отладки: 9337–9351 заняты соседними стендами и зондами.
PORT = 9352
LIMIT = 0.01
SETTLE = 2.5

PROBE = r"""
(() => {
  const D = { shifts: [], content: null, t0: performance.now() };
  window.__dp = D;
  const now = () => Math.round(performance.now() - D.t0);
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        D.shifts.push({ t: now(), v: +e.value.toFixed(4), input: !!e.hadRecentInput,
          src: (e.sources || []).slice(0, 3).map((s) => {
            const n = s.node, a = s.previousRect, b = s.currentRect;
            const name = n ? (n.tagName || '') + (typeof n.className === 'string' && n.className
              ? '.' + n.className.split(' ').slice(0, 2).join('.') : '') : '?';
            return `${name} ${Math.round(a.x)},${Math.round(a.y)} ${Math.round(a.width)}x${Math.round(a.height)}`
              + ` -> ${Math.round(b.x)},${Math.round(b.y)} ${Math.round(b.width)}x${Math.round(b.height)}`;
          }) });
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (e) {}
  const tick = () => {
    if (D.content === null) {
      const r = document.querySelector('.dp-react-root');
      if (r && r.children.length && r.getAttribute('aria-busy') !== 'true') D.content = now();
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})()"""


def run(out: pathlib.Path | None) -> int:
    day = clinic_today().isoformat()
    s1 = Server(keep_dir=True)
    preconditions(s1.dir)
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        c = Client(s1.url).login(PIN)
        ids = seed(c, day)
        # Чуть жизни: таблицы и списки с одной строкой сдвигов не показывают.
        for i, (n, ph) in enumerate([("Marcel Gradinaru", "017689955"), ("Laura Tudor", "0600558999"),
                                     ("Maria Sandu", "0789455666")]):
            c.post("/admin/add", adate=day, atime=f"{10 + i}:00", adoctor="d2", aservice="consult",
                   aname=n, aphone=ph, back="/admin/all")
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-shift-sweep")
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    proc, rows = None, []
    try:
        with s2:
            cookie = pin_cookie(s2.url)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network", "Log"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=s2.url + "/")
            cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=PROBE)
            page = Page(cdp, s2.url)
            page.size(*WIDE)
            for path, screen in screen_map.FLAG.items():
                url = fill(path, ids)
                page.go(url)
                time.sleep(SETTLE)
                d = json.loads(page.js("JSON.stringify(window.__dp)"))
                content = d["content"]
                late = [s for s in d["shifts"] if content is not None and s["t"] > content + 40 and not s["input"]]
                total = round(sum(s["v"] for s in late), 4)
                rows.append({"screen": screen, "url": url, "content": content, "late": late, "total": total,
                             "errors": cdp.errors()})
    finally:
        if proc:
            proc.kill()
        s1.drop()

    red = 0
    for r in rows:
        bad = r["content"] is None or r["total"] >= LIMIT or bool(r["errors"])
        red += bad
        mark = "RED" if bad else "OK "
        why = ("содержимого не дождались" if r["content"] is None else
               f"сдвиг после кадра {r['total']}" if r["total"] >= LIMIT else "")
        print(f"{mark} {r['screen']:<18} {r['url']:<44} кадр {r['content']!s:>5} мс  сдвиг {r['total']:<7} {why}")
        for s in r["late"] if bad else []:
            print(f"      t={s['t']} v={s['v']}: " + " | ".join(s["src"]))
        for e in r["errors"]:
            print(f"      консоль: {e}")
    print(f"\n{len(rows) - red}/{len(rows)} экранов без сдвигов после первого кадра содержимого")
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"подробности: {out}")
    return 1 if red else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "shots" / "shift_sweep.json")
    a = ap.parse_args()
    return run(a.out)


if __name__ == "__main__":
    sys.exit(main())
