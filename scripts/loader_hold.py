# -*- coding: utf-8 -*-
"""Видна ли оболочка, пока экран ЖДЁТ данные — стенд B2.2, один вопрос.

    python scripts\\loader_hold.py                  все экраны на загрузчике (App.tsx › LOADS)
    python scripts\\loader_hold.py /admin/medici    только эти адреса
    python scripts\\loader_hold.py --pair [адреса]  и пара утверждения 3 (ниже)

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
  3. ответ отпущен — экран вышел из ожидания, не позже потолка (`limit()`).

⛔ Зелёный стенд сам по себе ничего не доказывает. Доказательство — ПАРА:
на загрузчике БЕЗ `hydrateFallbackElement` утверждение 1 обязано краснеть
(роутер рисует на месте корня `null`), иначе стенд не видит того, ради чего
написан. Пара утверждения 3 встроена (`--pair`), обе половины — средствами
CDP, продукт не трогается: экран, до которого ответ так и не дошёл, обязан
дать красное, а шрифт, не приехавший вовсе, — нет: загрузчик ждёт его не
дольше `FONT_WAIT_MS`, и потолок это покрывает.
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

# ⭐ Утверждение 3 — ОПРОСОМ, а не паузой (03.10). С c3026f2 загрузчик отдаёт
# данные роутеру, когда для них готов шрифт, — до `FONT_WAIT_MS`
# (services/fonts.ts). Проверка стояла через 1.8 с после отпускания, а с
# шрифтом на пределе экраны выходят из ожидания за 1.06–1.30 с: на ответ
# сервера и React под нагрузкой оставалось полсекунды. Полный `.\dev bench`
# перед 1.37.4 дал «23/24» (какой адрес — бенч не показал), стенд отдельно
# сразу после — 24/24 дважды. Исправный экран выходит за доли секунды и
# опросом не задерживается; потолок тратится только на красный.
POLL_S = 0.1
MARGIN_S = 3.0
# После выхода страница наблюдается дальше: запрос, ушедший следом за
# отрисовкой, тоже отпускается, а ошибка консоли от него достаётся СВОЕМУ
# адресу. ⚠️ Не короче прежнего окна (1.8 с от отпускания): иначе поздняя
# ошибка быстрого экрана ушла бы в счёт следующего адреса — красный стенд
# назвал бы не того.
SETTLE_S = 0.5
WATCH_S = 1.8

REQUEST = {"urlPattern": "*/api/*", "requestStage": "Request"}
# Пара, «ответ не доходит»: та же стадия на ОТВЕТЕ, и он не отпускается никогда.
RESPONSE = {"urlPattern": "*/api/*", "requestStage": "Response"}
# Пара, «шрифт не приезжает»: `document.fonts.load` не отвечает вовсе, и
# загрузчик ждёт свой предел целиком на каждом экране — худшее, что продукт
# себе разрешает. Скрипт встаёт до бандла; сеть и бандл не тронуты.
NO_FONT = ("if (window.FontFaceSet) FontFaceSet.prototype.load = "
           "function () { return new Promise(function () {}) }")

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


def font_wait() -> float:
    """Предел ожидания шрифта загрузчиком, в секундах, — из `services/fonts.ts`.

    ⛔ Не копией числа: поднимут предел в продукте — рукописный потолок молча
    станет короче честного ожидания, и стенд покраснеет на исправном экране.
    Не разобрано — это ГРОМКО, как и у `loaded_paths`."""
    src = (ROOT / "frontend" / "src" / "services" / "fonts.ts").read_text(encoding="utf-8")
    m = re.search(r"^export const FONT_WAIT_MS = (\d+)\b", src, re.M)
    if not m:
        raise SystemExit("в services/fonts.ts не разобран FONT_WAIT_MS — стенду не из чего взять потолок")
    return int(m.group(1)) / 1000


def limit() -> float:
    """Потолок утверждения 3: предел шрифта и запас на ответ сервера под нагрузкой."""
    return font_wait() + MARGIN_S


def paused(cdp: CDP) -> list[dict]:
    """Придержанные ЗАПРОСЫ из накопленных событий; остальные события — назад.

    ⚠️ Придержанный ОТВЕТ (стадию Response включает только пара) не отдаётся
    никому и так и висит: это и есть «ответ не дошёл до страницы»."""
    out, rest = [], []
    for e in cdp.events:
        if e.get("method") != "Fetch.requestPaused":
            rest.append(e)
        elif "responseStatusCode" not in e["params"] and "responseErrorReason" not in e["params"]:
            out.append(e)
    cdp.events = rest
    return [e["params"] for e in out]


def api(p: dict) -> str:
    return p["request"]["url"].split("/api", 1)[-1]


def release(cdp: CDP, t0: float) -> list[str]:
    """Отпустить запросы, ушедшие уже после отпускания (второй запрос экрана),
    — иначе экран ждал бы их до следующего адреса. Что и когда — в отчёт."""
    out = []
    for p in paused(cdp):
        cdp.cmd("Fetch.continueRequest", requestId=p["requestId"])
        out.append(f"{api(p)} +{time.monotonic() - t0:.1f} с")
    return out


def left(a: dict) -> bool:
    return a["screen"] and a["busy"] != "true"


def hold_one(page: Page, cdp: CDP, path: str, ceil: float) -> dict:
    page.go(path)                 # load не ждёт fetch: документ загружен, API придержан
    held = paused(cdp)
    time.sleep(0.7)               # дать React отрисоваться с придержанным ответом
    cdp.drain(0.2)
    held += paused(cdp)
    during = json.loads(page.js(STATE))
    for p in held:
        cdp.cmd("Fetch.continueRequest", requestId=p["requestId"])
    t0, late = time.monotonic(), []
    while True:                   # утверждение 3: до выхода из ожидания или потолка
        late += release(cdp, t0)
        after = json.loads(page.js(STATE))
        waited = time.monotonic() - t0
        if left(after) or waited >= ceil:
            break
        cdp.drain(POLL_S)
    while time.monotonic() - t0 < max(waited + SETTLE_S, WATCH_S):   # и наблюдение после
        cdp.drain(POLL_S)
        late += release(cdp, t0)
    return {"path": path, "held": [api(p) for p in held], "late": late, "during": during,
            "after": after, "waited": waited, "ceil": ceil, "errors": cdp.errors()}


def verdict(r: dict) -> list[str]:
    d, a = r["during"], r["after"]
    bad = []
    if not r["held"]:
        bad.append("ни один запрос /api/ не придержан — стенд ничего не проверил")
    if not (d["side"] and d["top"] and d["h1"]):
        bad.append(f"оболочка пропала на время ожидания: {d}")
    if not (d["screen"] and d["busy"] == "true"):
        bad.append(f"экран не в ожидании, пока ответ придержан: {d}")
    if not left(a):
        bad.append(f"ответ отпущен, а экран не вышел из ожидания за {r['ceil']:.1f} с: {a}")
    if r["errors"]:
        bad.append("ошибки консоли: " + "; ".join(r["errors"][:3]))
    return bad


def report(results: list[dict]) -> int:
    """Напечатать по адресу и вернуть число красных."""
    red = 0
    for r in results:
        bad = verdict(r)
        red += bool(bad)
        print(f"{'OK ' if not bad else 'RED'} {r['path']:<24} придержано: {', '.join(r['held']) or '—'}")
        print(f"    пока ждёт: {r['during']}")
        print(f"    отпущено:  {r['after']}  {'вышел' if left(r['after']) else 'НЕ вышел'}"
              f" за {r['waited']:.2f} с")
        if r["late"]:
            print(f"    позже:     {', '.join(r['late'])}")
        for b in bad:
            print(f"    ✗ {b}")
    return red


def stuck(r: dict) -> bool:
    """Красное пары РОВНО по утверждению 3: пока держали — всё как надо, после
    отпускания экран ждёт до самого потолка. Экран, которого нет вовсе, тоже
    дал бы красное — но не то, и стенда бы не доказал."""
    d, a = r["during"], r["after"]
    return bool(r["held"]) and d["side"] and d["top"] and d["h1"] and d["busy"] == "true" \
        and a["screen"] and a["busy"] == "true" and r["waited"] >= r["ceil"]


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
    pair = "--pair" in argv
    paths = [a for a in argv if a.startswith("/")] or loaded_paths()
    ceil = limit()
    day = clinic_today().isoformat()
    s1 = Server(keep_dir=True)
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
    proc, results, no_font, no_answer = None, [], [], []
    try:
        with s2:
            cookie = pin_cookie(s2.url)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network", "Log"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=s2.url + "/")
            cdp.cmd("Fetch.enable", patterns=[REQUEST])
            page = Page(cdp, s2.url)
            page.size(*WIDE)
            urls = [fill(path, ids) for path in paths]
            results = [hold_one(page, cdp, u, ceil) for u in urls]
            if pair:
                sid = cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=NO_FONT)["identifier"]
                no_font = [hold_one(page, cdp, u, ceil) for u in urls]
                cdp.cmd("Page.removeScriptToEvaluateOnNewDocument", identifier=sid)
                # красной половине хватит трёх адресов вразброс: потолок ждётся целиком
                cdp.cmd("Fetch.enable", patterns=[REQUEST, RESPONSE])
                no_answer = [hold_one(page, cdp, u, ceil) for u in urls[::max(1, len(urls) // 3)]]
    finally:
        if proc:
            proc.kill()
        s1.drop()

    red = report(results)
    out = [r for r in results if left(r["after"])]
    slow = max(out, key=lambda r: r["waited"]) if out else None
    print(f"\n{len(results) - red}/{len(results)} адресов: оболочка видна, пока экран ждёт"
          + (f"; из ожидания — до {slow['waited']:.2f} с ({slow['path']}), потолок {ceil:.1f}"
             if slow else ""))
    if not pair:
        return 1 if red else 0

    fw = font_wait()
    print(f"\nПара, шрифт не приезжает — обязано быть ЗЕЛЁНЫМ, ожидание не короче {fw:.1f} с:")
    report(no_font)
    print("\nПара, ответ не доходит до страницы — обязано быть КРАСНЫМ по утверждению 3:")
    report(no_answer)
    fails = []
    false_red = [r["path"] for r in no_font if verdict(r)]
    if false_red:
        fails.append(f"шрифт не приехал, и исправный экран покраснел (почему — выше): {', '.join(false_red)}")
    unheld = [r["path"] for r in no_font if r["waited"] < fw]
    if unheld:
        fails.append(f"шрифт не задержан (вышел раньше {fw:.1f} с), половина ничего не доказала: "
                     + ", ".join(unheld))
    blind = [r["path"] for r in no_answer if not stuck(r)]
    if blind or not no_answer:
        fails.append(f"СТЕНД СЛЕП: ответ не дошёл, а утверждение 3 не покраснело: {', '.join(blind) or '—'}")
    for f in fails:
        print(f"    ✗ {f}")
    print(f"\nпара: ответ не дошёл — красное {len(no_answer) - len(blind)}/{len(no_answer)}; "
          f"шрифт не приехал — зелёное {len(no_font) - len(false_red)}/{len(no_font)}"
          + (" — СТЕНД НЕ ДОКАЗАН" if fails else ""))
    return 1 if red or fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
