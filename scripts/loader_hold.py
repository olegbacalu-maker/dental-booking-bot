# -*- coding: utf-8 -*-
"""Видна ли оболочка, пока экран ЖДЁТ данные — стенд B2.2, один вопрос.

    python scripts\\loader_hold.py                  все экраны на загрузчике (App.tsx › LOADS)
    python scripts\\loader_hold.py /admin/medici    только эти адреса

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. Первый `loader` роутера меняет то, КОГДА рисуется первый кадр: без
загрузчиков роутер инициализирован сразу, с загрузчиком — ждёт его. Если на
время ожидания пропадёт и оболочка, вернётся ровно то мигание, ради которого
делался B1, и на быстрой песочнице этого не видно вовсе: ответ приходит за
десятки миллисекунд. Поэтому ответ `/api/` здесь ПРИДЕРЖИВАЕТСЯ (CDP `Fetch`),
и страница снимается в тот момент, когда экран ждёт, сколько угодно долго.

Три утверждения на адрес:
  1. пока ответ придержан — сайдбар, шапка и заголовок на месте;
  2. пока ответ придержан — экран стоит в `aria-busy="true"`, а не пуст;
  3. ответ отпущен — экран вышел из ожидания.

⛔ Зелёный стенд сам по себе ничего не доказывает. Доказательство — ПАРА:
на загрузчике БЕЗ `hydrateFallbackElement` утверждение 1 обязано краснеть
(роутер рисует на месте корня `null`), иначе стенд не видит того, ради чего
написан.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import Client, Server, clinic_today  # noqa: E402
from mount_sweep import PIN, fill, pin_cookie, preconditions, seed  # noqa: E402
from odo_shots import CDP, Page, start_edge  # noqa: E402
import screen_map  # noqa: E402

WIDE = (1500, 950)
# ⛔ Свой порт отладки: 9337–9342 заняты соседними стендами, и запуск на
# занятом МОЛЧА подключается к чужому браузеру.
PORT = 9343

STATE = """(() => {
  const r = document.querySelector('.dp-react-root');
  return JSON.stringify({
    side: !!document.querySelector('aside.side'),
    top: !!document.querySelector('.main .top'),
    h1: !!document.querySelector('.content h1'),
    screen: !!r,
    busy: r ? r.getAttribute('aria-busy') : null,
    nodes: r ? r.querySelectorAll('*').length : 0,
  });
})()"""


def paused(cdp: CDP) -> list[dict]:
    """Придержанные запросы из накопленных событий; остальные события — назад."""
    out, rest = [], []
    for e in cdp.events:
        (out if e.get("method") == "Fetch.requestPaused" else rest).append(e)
    cdp.events = rest
    return [e["params"] for e in out]


def hold_one(page: Page, cdp: CDP, path: str) -> dict:
    page.go(path)                 # load не ждёт fetch: документ загружен, API придержан
    held = paused(cdp)
    time.sleep(0.7)               # дать React отрисоваться с придержанным ответом
    cdp.drain(0.2)
    held += paused(cdp)
    during = json.loads(page.js(STATE))
    for p in held:
        cdp.cmd("Fetch.continueRequest", requestId=p["requestId"])
    time.sleep(1.0)
    cdp.drain(0.3)
    for p in paused(cdp):         # запрос, ушедший уже после отпускания
        cdp.cmd("Fetch.continueRequest", requestId=p["requestId"])
    time.sleep(0.5)
    after = json.loads(page.js(STATE))
    return {"path": path, "held": [p["request"]["url"].split("/api", 1)[-1] for p in held],
            "during": during, "after": after, "errors": cdp.errors()}


def verdict(r: dict) -> list[str]:
    d, a = r["during"], r["after"]
    bad = []
    if not r["held"]:
        bad.append("ни один запрос /api/ не придержан — стенд ничего не проверил")
    if not (d["side"] and d["top"] and d["h1"]):
        bad.append(f"оболочка пропала на время ожидания: {d}")
    if not (d["screen"] and d["busy"] == "true"):
        bad.append(f"экран не в ожидании, пока ответ придержан: {d}")
    if a["busy"] == "true" or not a["screen"]:
        bad.append(f"ответ отпущен, а экран не вышел из ожидания: {a}")
    if r["errors"]:
        bad.append("ошибки консоли: " + "; ".join(r["errors"][:3]))
    return bad


def loaded_paths() -> list[str]:
    """Адреса экранов на загрузчике — из `App.tsx › LOADS` через карту FLAG.

    ⛔ Не рукописным списком: он разошёлся бы с LOADS молча, и стенд объявил бы
    проверенным то, чего не открывал. Разбор пуст — это ГРОМКО, а не «0/0».
    """
    app = (ROOT / "frontend" / "src" / "app" / "App.tsx").read_text(encoding="utf-8")
    blk = app.split("const LOADS", 1)[-1].split("\n}\n", 1)[0]
    names = set(re.findall(r"^  ([a-z_0-9]+): ", blk, re.M))
    if not names:
        raise SystemExit("в App.tsx не разобран словарь LOADS — стенд ничего бы не проверил")
    by_screen = {v: k for k, v in screen_map.FLAG.items()}
    return sorted(by_screen[n] for n in names)


def main(argv: list[str]) -> int:
    paths = [a for a in argv if a.startswith("/")] or loaded_paths()
    day = clinic_today().isoformat()
    s1 = Server()
    s1._own_dir = False
    # ⭐ Предусловия и засев — те же, что у mount_sweep: без них «Rețea» и
    # «Securitate» уводят на хаб, а одонтограмме некого открыть.
    preconditions(s1.dir)
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        ids = seed(Client(s1.url).login(PIN), day)
    # ⭐ Пин наборов СНИМАЕТСЯ (как в mount_sweep): проверяется то, что клиника
    # увидит по умолчанию, а не собственная настройка стенда.
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-loader-hold")
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    proc, results = None, []
    try:
        with s2:
            cookie = pin_cookie(s2.url)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network", "Log"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=s2.url + "/")
            cdp.cmd("Fetch.enable", patterns=[{"urlPattern": "*/api/*", "requestStage": "Request"}])
            page = Page(cdp, s2.url)
            page.size(*WIDE)
            for path in paths:
                results.append(hold_one(page, cdp, fill(path, ids)))
    finally:
        if proc:
            proc.kill()
        s1.__exit__(None, None, None)

    red = 0
    for r in results:
        bad = verdict(r)
        red += bool(bad)
        print(f"{'OK ' if not bad else 'RED'} {r['path']:<24} придержано: {', '.join(r['held']) or '—'}")
        print(f"    пока ждёт: {r['during']}")
        print(f"    отпущено:  {r['after']}")
        for b in bad:
            print(f"    ✗ {b}")
    print(f"\n{len(results) - red}/{len(results)} адресов: оболочка видна, пока экран ждёт")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
