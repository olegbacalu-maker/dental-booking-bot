# -*- coding: utf-8 -*-
"""Снимки ВСЕХ экранов во всех стилях темы — «до/после» правки оформления.

    python scripts\\look_sweep.py --tag base                    снять эталон
    python scripts\\look_sweep.py --tag step1 --against base    снять и сравнить
    python scripts\\look_sweep.py --compare base step1          только сравнить
    ключи: --styles modern,calm  --only settings_theme,visit  --no-legacy

⛔ Не в CI и не в `.\\dev test`: нужны Edge и пакеты websocket-client, Pillow,
numpy в СИСТЕМНОМ Python (в .venv-desktop ничего не ставить — это окружение
сборки).

Зачем. Правка оформления «без видимых изменений» — перевод литералов в
переменные, наведение порядка в радиусах — недоказуема ни прогоном, ни
глазами: прогон CSS не видит, а глаз по одному экрану в день пропускает
пропавший фон и сдвиг на пиксель. Здесь берётся КАЖДЫЙ экран из карты
(`parity_audit`, тот же список, что у монтажа), в React и в старой вёрстке
(`?ui=legacy` — panel.css красит обе), в КАЖДОМ стиле темы, и снимок «после»
сверяется со снимком «до» попиксельно.

Что считается. Размер кадра разошёлся — раскладка поехала, красное сразу.
Иначе — число пикселей, где хоть один канал ушёл дальше чем на 24 из 255:
сглаживание скруглённого угла на радиус ±1px даёт единицы, пропавшая тень —
сотни, сдвиг текста на пиксель — тысячи. Порог — LIMIT на кадр; к каждому
красному рядом кладётся карта отличий (`diff/`), чтобы посмотреть глазами.

⚠️ Что нейтрализовано, потому что зависит от часов, а не от оформления:
  · маской (`visibility:hidden`, место остаётся) — часы в подвале меню
    (`#sf_clock`), «через N мин» (`.wait-min`), линия «сейчас» (`.nowline`),
    курсор ввода и ВСЕ анимации с переходами (кадр берётся в конечном
    состоянии — правило карты: без `.anim` элемент и так конечный);
  · подменой текста перед кадром — ЛЮБОЕ время вида ЧЧ:ММ в текстовых узлах
    становится нулями той же длины (`17:04` → `00:00`): метки летописи в
    «Activitate recentă» и в фише, «ultima intrare» у учёток — это время
    засева и входа, у двух прогонов оно разное. Ширина текста не меняется,
    раскладка та же; часы записей (`09:00`) тоже обнуляются, но одинаково в
    обоих кадрах, а стенд сверяет оформление, а не значения.
⚠️ Ряд текущего часа (`.now`) не нейтрализуется: два прогона внутри одного
часа его не различают, на границе часа — перезапустить.

⛔ Пара: стенд обязан краснеть на сломанном. Проверено при заведении (25.09):
`--r-card:18px` → `17px` в :root даёт 13–40 пикселей на карточку и красное на
каждом экране с карточками; `.tile{box-shadow:none}` — красное на панели.
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
from mount_sweep import PIN, fill, pin_cookie, preconditions, seed  # noqa: E402
from odo_shots import CDP, Page, start_edge  # noqa: E402
from parity_audit import audit  # noqa: E402

WIDE = (1500, 950)
# ⛔ Свой порт отладки: 9337–9352 заняты соседними стендами; запуск на занятом
# МОЛЧА подключается к чужому браузеру.
PORT = 9353
OUT = ROOT / "build" / "shots" / "look"
# Порог «отличается»: пикселей на кадр. Сглаживание ±1px радиуса — единицы,
# пропавшая тень — сотни, сдвиг — тысячи.
LIMIT = 120
CHANNEL = 24

MASK_CSS = (
    "*,*::before,*::after{animation:none!important;transition:none!important;"
    "caret-color:transparent!important}"
    "#sf_clock,.wait-min,.nowline{visibility:hidden!important}"
)
# Ставится ДО первой отрисовки каждого документа: тег стиля в <head> сразу,
# как только он появился (скрипт нового документа идёт раньше разметки).
MASK_JS = """(() => {
  const put = () => { if (!document.head) return false;
    const s = document.createElement('style'); s.id = 'dp-look-mask';
    s.textContent = %s; document.head.appendChild(s); return true; };
  // ⚠️ в момент скрипта нового документа нет ещё и <html>: наблюдать можно
  // только сам document, поддеревом
  if (!put()) new MutationObserver((_, o) => { if (put()) o.disconnect(); })
    .observe(document, { childList: true, subtree: true });
})()""" % json.dumps(MASK_CSS)

# Время ЧЧ:ММ в тексте — нулями той же длины. Только текстовые узлы: значения
# полей (даты периода статистики) и атрибуты не трогаются.
ZERO_TIME_JS = """(() => {
  const re = /\\b([01]?\\d|2[0-3]):[0-5]\\d\\b/g;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n = 0, t;
  while ((t = w.nextNode())) {
    if (re.test(t.nodeValue)) { t.nodeValue = t.nodeValue.replace(re, (m) => m.replace(/\\d/g, '0')); n++; }
    re.lastIndex = 0;
  }
  return n;
})()"""

SETTLED_JS = """(() => {
  const r = document.querySelector('.dp-react-root');
  const root = document.getElementById('root');
  if (root && !r) return false;                  // React ещё не смонтировался
  if (r && r.getAttribute('aria-busy') === 'true') return false;
  return document.readyState === 'complete';
})()"""


def settle(page: Page, timeout: float = 8.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if page.js(SETTLED_JS):
            break
        time.sleep(0.2)
    page.cdp.drain(0.6)
    page.js("window.scrollTo(0,0)")
    page.js(ZERO_TIME_JS)
    page.cdp.drain(0.2)


def shoot(tag: str, styles: list[str], only: set[str] | None, legacy: bool,
          menu: str = "brand", font: str = "inter") -> pathlib.Path:
    rows = [r for r in audit() if r["path"] and (not only or r["screen"] in only)]
    if not rows:
        raise SystemExit("нечего снимать: аудит не дал ни одного экрана с адресом")
    out = OUT / tag
    out.mkdir(parents=True, exist_ok=True)
    # час съёмки: ряд текущего часа (`.now`) в журнале не маскируется, и два
    # снимка по разные стороны границы часа разойдутся на нём законно
    (out / "meta.json").write_text(json.dumps({"hour": time.strftime("%Y-%m-%d %H")}),
                                   encoding="utf-8")

    day = clinic_today().isoformat()
    s1 = Server()
    s1._own_dir = False
    preconditions(s1.dir)
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        ids = seed(Client(s1.url).login(PIN), day)
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)          # то, что клиника видит по умолчанию (см. mount_sweep)
    cfg.pop("_ui_comment", None)
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-look-sweep")
    proc = None
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    n = 0
    t0 = time.time()
    try:
        with s2:
            origin = s2.url
            api = Client(origin).login(PIN)
            cookie = pin_cookie(origin)
            proc, ws_url = start_edge(profile, port=PORT)
            cdp = CDP(ws_url)
            for dom in ("Network", "Runtime", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=MASK_JS)
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=origin + "/")
            page = Page(cdp, origin)
            page.size(*WIDE)

            for style in styles:
                r = api.post_json("/api/settings/theme",
                                  {"style": style, "primary": "#0E9F8A", "custom": "",
                                   "logo_topbar": False, "menu": menu, "font": font})
                if r.status != 200:
                    raise SystemExit(f"стиль {style!r} не применился: HTTP {r.status} {r.body[:200]}")
                sdir = out / style
                sdir.mkdir(exist_ok=True)
                for row in rows:
                    path = fill(row["path"], ids)
                    variants = [("", path)]
                    if legacy:
                        variants.append(("-legacy", path + ("&" if "?" in path else "?") + "ui=legacy"))
                    for suffix, url in variants:
                        page.go(url)
                        settle(page)
                        page.png(sdir / f"{row['screen']}{suffix}.png")
                        n += 1
                print(f"  {style}: {n} кадров, {time.time() - t0:.0f} с")
    finally:
        if proc:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)
        s1.__exit__(None, None, None)
    print(f"снято {n} кадров → {out}")
    return out


def compare(base_tag: str, new_tag: str) -> int:
    import numpy as np
    from PIL import Image

    base, new = OUT / base_tag, OUT / new_tag
    if not base.is_dir() or not new.is_dir():
        raise SystemExit(f"нет папки снимков: {base if not base.is_dir() else new}")
    diff_dir = new / "diff"
    red, seen, missing = [], 0, []
    hours = []
    for d in (base, new):
        try:
            hours.append(json.loads((d / "meta.json").read_text(encoding="utf-8"))["hour"])
        except (OSError, ValueError, KeyError):
            hours.append("?")
    if hours[0] != hours[1]:
        print(f"⚠️ снимки из разных часов ({hours[0]} и {hours[1]}): ряд текущего часа "
              f"в журнале разойдётся законно — переснять в один час")
    for p in sorted(new.rglob("*.png")):
        if p.parent.name == "diff":
            continue
        rel = p.relative_to(new)
        q = base / rel
        if not q.exists():
            missing.append(str(rel))
            continue
        seen += 1
        a = np.asarray(Image.open(q).convert("RGB"), dtype=np.int16)
        b = np.asarray(Image.open(p).convert("RGB"), dtype=np.int16)
        if a.shape != b.shape:
            red.append((str(rel), f"размер {a.shape[1]}x{a.shape[0]} → {b.shape[1]}x{b.shape[0]}"))
            continue
        d = np.abs(a - b).max(axis=2)
        mask = d > CHANNEL
        count = int(mask.sum())
        if count > LIMIT:
            ys, xs = np.nonzero(mask)
            box = f"x{xs.min()}–{xs.max()} y{ys.min()}–{ys.max()}"
            red.append((str(rel), f"{count} px (max {int(d.max())}), {box}"))
            diff_dir.mkdir(exist_ok=True)
            heat = (a * 0.35).astype(np.uint8)
            heat[mask] = (255, 0, 0)
            Image.fromarray(heat).save(diff_dir / rel.name.replace(".png", f"-{rel.parent.name}.png"))
        elif count:
            print(f"  ~ {rel}: {count} px (в допуске)")
    print(f"\nсверено {seen} кадров: {new_tag} против {base_tag}")
    if missing:
        print(f"нет в эталоне ({len(missing)}): " + ", ".join(missing[:6]))
    for rel, why in red:
        print(f"RED {rel}: {why}")
    if red:
        print(f"карты отличий: {diff_dir}")
    print("ЧИСТО" if not red else f"КРАСНЫХ: {len(red)}")
    return 1 if red else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="имя снимка (папка build/shots/look/<tag>)")
    ap.add_argument("--against", help="эталон для сверки после съёмки")
    ap.add_argument("--compare", nargs=2, metavar=("BASE", "NEW"), help="только сверить")
    ap.add_argument("--styles", default="modern,elegant,calm")
    ap.add_argument("--menu", default="brand", help="вариант меню: brand | neutral")
    ap.add_argument("--font", default="inter", help="шрифт: inter | system")
    ap.add_argument("--only", default="", help="экраны через запятую")
    ap.add_argument("--no-legacy", action="store_true")
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)
    if not a.tag:
        ap.error("нужен --tag или --compare")
    only = {s for s in a.only.split(",") if s} or None
    shoot(a.tag, [s for s in a.styles.split(",") if s], only, not a.no_legacy,
          menu=a.menu, font=a.font)
    return compare(a.against, a.tag) if a.against else 0


if __name__ == "__main__":
    sys.exit(main())
