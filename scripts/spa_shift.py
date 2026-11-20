# -*- coding: utf-8 -*-
"""Сдвиги раскладки после перехода РОУТЕРОМ — экран, открытый без перезагрузки документа.

    python scripts\\spa_shift.py [--only lab] [--port N] [--out FILE]

Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. `shift_sweep` открывает каждый экран ДОКУМЕНТОМ и считает от кадра, где корень экрана не `aria-busy`.
Экран, который берёт данные сам (`useLoad`), при переходе роутером встаёт сразу — меню без счётчиков и шапка, —
а таблица, счётчики и выбор лаборатории приезжают следующим кадром: прыжок, который видит человек, а документный
проход не видит (у него пустой кадр — «ещё грузится»). Здесь отсчёт — от ПЕРВОГО кадра нового экрана.

Красное — любое из двух:
  * первый кадр нового экрана — ещё загрузка (`aria-busy`): экран встал раньше своих данных;
  * сдвиги после первого кадра — суммарно 0.01 и больше (порог `shift_sweep`).
Сеть замедлена на 150 мс, чтобы данные не успевали «до кадра» случайно: без этого гонка зеленеет через раз.

Переходы — из скрипта, не мышью: настоящий щелчок помечает сдвиги следующих 500 мс как «после ввода», и метрика
их бы не считала. Виды перехода: ссылка меню оболочки (`menu`), щелчок по пункту меню раздела (`tab`), смена
адреса как «Назад» роутера (`pop`), кнопка экрана по подписи (`click` — вкладки без адреса, у «Registre»).

Кроме разделов `TARGETS` стенд обходит сам: каждую ссылку меню оболочки (из главной и из фиши) и каждый экран
карты (`screen_map.FLAG`, адресом с главной) — новый раздел меряется без правки списка.

Окна — 1366×768 и 1440×900 (ноутбуки клиник). Все разделы `TARGETS` уже в меню оболочки: перехода нет — RED
(ссылка из меню пропала), а не пропуск.

Известные прыжки, которые решено пока не чинить, — в `KNOWN` с причиной: печатаются, итог не красят.

Пара: экран на своём `useLoad` (без строки в `LOADS`) стенд обязан красить — `/admin/lab` и `/admin/registre`
краснеют первым кадром без данных.
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

SIZES = [(1366, 768), (1440, 900)]
# Свой порт отладки: соседние стенды заняли 9337–9352.
PORT = 9353
LIMIT = 0.01
LATENCY = 150
SETTLE = 2.0
TRACE = False

SOURCES = ["/admin", "/admin/search", "/admin/patient/{pid}", "/admin/all", "/admin/settings"]
# Разделы с меню слева (`SideMenu`) и их соседи; новый такой раздел — сюда. Вид: ссылка меню оболочки или адрес
# «Назад» (у настроек раздела ссылки в меню нет). Раздел, которого в меню нет, — RED.
TARGETS = [("/admin/lab", "menu"), ("/admin/settings/lab", "pop"), ("/admin/stoc", "menu"),
           ("/admin/settings/stoc", "pop"), ("/admin/registre", "menu"), ("/admin/settings/registre", "pop"),
           ("/admin/tarife", "menu")]
# Откуда в раздел приходят чаще всего: поверх общих — соседние разделы.
TARGET_SOURCES = {"/admin/registre": ["/admin", "/admin/all", "/admin/patient/{pid}", "/admin/lab", "/admin/stoc"],
                  "/admin/settings/registre": ["/admin", "/admin/settings", "/admin/registre"]}
# Обход меню оболочки: источники, из которых жмётся каждая ссылка.
MENU_SOURCES = ["/admin", "/admin/patient/{pid}"]
# Известные прыжки, которые решено пока не чинить: печатаются с причиной и итог не красят. Перестал прыгать —
# красное «уберите из KNOWN»: список не должен прятать то, чего уже нет.
KNOWN = {
    "/admin/patient/{pid}/odontograma": "боковое меню сужается в полосу анимацией, и страница едет за ним (отложено)",
    "/admin/patient/{pid}/parodontograma": "боковое меню сужается в полосу анимацией, и страница едет за ним (отложено)",
}
# Вкладки «Registre» без адреса — по подписи кнопки, по порядку щелчков.
REGISTRE_CLICKS = ["Istoric și tipar", "Curățenie generală", "Lămpi bactericide", "Luna trecută", "Luna următoare",
                   "Sterilizare", "Azi"]
# Вкладки фиши: меню слева в режиме вкладок, тот же `SideMenu`.
CARD_TABS = ".dp-rail [role=tab]"

PROBE = r"""
(() => {
  const D = { shifts: [], first: null, ready: null, on: false };
  window.__dp = D;
  let t0 = 0, frames = [], mut = false, gen = 0;
  /* Сдвиг относится к кадру, в чей промежуток попало его время: сдвиги кадра коммита — это сам переход. */
  const frameOf = (t) => { let i = -1; while (i + 1 < frames.length && frames[i + 1] <= t) i++; return i; };
  new PerformanceObserver((list) => {
    if (!D.on) return;
    for (const e of list.getEntries()) {
      D.shifts.push({ t: Math.round(e.startTime - t0), frame: frameOf(e.startTime), v: +e.value.toFixed(4),
        input: !!e.hadRecentInput,
        src: (e.sources || []).slice(0, 3).map((s) => {
          const n = s.node, a = s.previousRect, b = s.currentRect;
          const name = n ? (n.tagName || '#text') + (typeof n.className === 'string' && n.className
            ? '.' + n.className.split(' ').slice(0, 2).join('.') : '') : '?';
          return `${name} ${Math.round(a.x)},${Math.round(a.y)} ${Math.round(a.width)}x${Math.round(a.height)}`
            + ` -> ${Math.round(b.x)},${Math.round(b.y)} ${Math.round(b.width)}x${Math.round(b.height)}`;
        }) });
    }
  }).observe({ type: 'layout-shift' });
  /* Кадр нового экрана — первый, перед которым React тронул DOM экрана: адрес меняется раньше коммита. */
  new MutationObserver((list) => {
    if (!D.on || mut) return;
    const root = (n) => n.nodeType === 1 && (n.matches('.dp-react-root') || !!n.querySelector('.dp-react-root'));
    const m = list.find((x) => (x.target.closest ? x.target : x.target.parentElement)?.closest?.('.dp-react-root')
      || [...x.addedNodes].some(root));
    if (m) { mut = true; D.mutWhat = `${Math.round(performance.now() - t0)} ${m.type} ${m.target.nodeName}.${m.target.className || ''}`
      + ` +${[...m.addedNodes].map((n) => n.nodeName + '.' + (n.className || '')).join(',')} -${[...m.removedNodes].map((n) => n.nodeName + '.' + (n.className || '')).join(',')}`; }
  }).observe(document, { subtree: true, childList: true, characterData: true });
  /* Переход: `menu` — ссылка оболочки по адресу, `tab` — n-й пункт меню раздела, `pop` — адрес как «Назад»,
     `click` — кнопка экрана по подписи (вкладки, у которых нет адреса: смена адреса не ждётся). */
  D.go = (kind, arg) => {
    let fire, picked = null;
    if (kind === 'menu') {
      const a = document.querySelector(`aside a[href="${arg}"]`);
      if (!a) return false;
      fire = () => a.click();
    } else if (kind === 'tab') {
      const b = document.querySelectorAll(%TABS%)[arg];
      if (!b || b.getAttribute('aria-selected') === 'true') return false;
      picked = b;
      fire = () => b.click();
    } else if (kind === 'click') {
      const b = [...document.querySelectorAll('.dp-react-root button')].find((x) =>
        x.getAttribute('aria-label') === arg || x.textContent.trim().startsWith(arg));
      if (!b) return false;
      fire = () => b.click();
    } else {
      fire = () => {
        const idx = ((history.state && history.state.idx) || 0) + 1;
        history.pushState({ usr: null, key: 'sweep' + idx, idx }, '', arg);
        dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
      };
    }
    const href = location.href;
    const old = document.querySelector('.dp-react-root');
    if (old) old.__dpOld = 1;
    t0 = performance.now(); frames = []; mut = false;
    Object.assign(D, { shifts: [], first: null, ready: null, on: true, trace: [] });
    const my = ++gen;
    const tick = () => {
      if (my !== gen) return;   /* петля прошлого замера на этой же странице */
      frames.push(performance.now());
      const r = document.querySelector('.dp-react-root');
      /* кадр по кадру — что видно: для разбора красного (`--trace`) */
      const sp = r && r.querySelector('.dp-split'), pn = r && r.querySelector('.dp-split-main');
      const snap = [location.pathname + location.search, sp ? sp.className : '-', pn ? Math.round(pn.getBoundingClientRect().width) + 'x'
        + Math.round(pn.getBoundingClientRect().height) : '-', r ? r.querySelectorAll('[aria-busy=true]').length + (r.getAttribute('aria-busy') === 'true' ? 'B' : '') : '-',
        r ? (r.__dpOld ? 'old' : 'new') : '-'].join(' ');
      if (!D.trace.length || D.trace[D.trace.length - 1][1] !== snap) D.trace.push([Math.round(performance.now() - t0), snap]);
      if (D.first === null && (kind === 'click' || location.href !== href) && r && (kind === 'menu' ? !r.__dpOld : kind === 'tab' ? picked.getAttribute('aria-selected') === 'true' : mut))
        D.first = frames.length - 1;
      if (D.first !== null && D.ready === null && r && r.getAttribute('aria-busy') !== 'true'
          && !r.querySelector('[aria-busy=true]')) D.ready = frames.length - 1;
      if (D.on) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    fire();
    return true;
  };
  D.ms = (i) => (i === null || i < 0 || i >= frames.length) ? null : Math.round(frames[i] - t0);
})()""".replace("%TABS%", json.dumps(CARD_TABS))


def seed_more(c: Client, day: str, pid: str) -> str:
    """Две лаборатории, заказы первого пациента и второй пациент (переход фиша → фиша). Отдаёт id второго."""
    labs = []
    for name in ("Dental Lab Nord", "Ceramica Sud"):
        r = c.post_json("/api/settings/lab/item", {"name": name})
        labs.append(json.loads(r.body)["data"]["id"])
    for i, work in enumerate(["Coroană", "Punte", "Proteză", "Coroană"]):
        r = c.post_json("/api/lab/order", {"pid": int(pid), "lab_id": labs[i % 2], "doctor_id": "d2",
                                          "items": [{"work": work, "material": "Zirconiu", "teeth": [26 - i]}]})
        if r.msg != "ok_lab_new":
            raise SystemExit(f"заказ не заведён: {r.status} {r.body[:200]}")
    c.post_json("/api/schedule/appointments", {"date": day, "time": "11:00", "doctor": "d2", "service": "consult",
                                              "name": "Laura Tudor", "phone": "0600558999"})
    rows = json.loads(c.get("/api/patients?q=Laura").body)["data"]["rows"]
    if not rows:
        raise SystemExit("второй пациент не заведён")
    return str(rows[0]["id"])


def seed_registre(c: Client) -> None:
    """Каталог «Registre» тем же маршрутом, что у директора, и по записи в каждом регистре: пустой экран не прыгает."""
    items = [
        {"kind": "ster", "name": "Melag 23 B+", "nr": "23-11845", "room": "Sala de sterilizare",
         "data": {"type": "abur", "programs": [{"label": "Universal 134 °C", "temp": "134", "pressure": "2,1", "min": 5}]}},
        {"kind": "lamp", "name": "OBN-150", "nr": "2", "room": "Cabinet 1",
         "data": {"m3": 45, "hours": 100, "base": 60, "since": "2026-01-01", "screened": False}},
        {"kind": "room", "name": "Cabinet 1", "data": {"every": 7}},
        {"kind": "solution", "name": "Septodor Forte 0,2 % · 60 min"},
        {"kind": "article", "name": "Instrumentar stomatologic"},
        {"kind": "pack", "name": "Pungă"},
    ]
    for it in items:
        r = c.post_json("/api/settings/registre/item", it)
        if r.msg != "ok_san_item":
            raise SystemExit(f"каталог Registre: {it['kind']} {r.status} {r.body[:200]}")
    cat = json.loads(c.get("/api/settings/registre").body)["data"]["items"]
    for path, body in (("/api/registre/257", {"ster_id": cat["ster"][0]["id"], "program": 0, "doer": "Maria Lungu",
                                              "arts": [{"name": "Instrumentar stomatologic", "qty": 12, "pack": "Pungă"}]}),
                       ("/api/registre/502", {"room_id": cat["room"][0]["id"], "solution": "Septodor Forte 0,2 % · 60 min",
                                              "doer": "Ion Cebotari"}),
                       ("/api/registre/501", {"lamp_id": cat["lamp"][0]["id"], "cond": "fara", "doer": "Maria Lungu"})):
        r = c.post_json(path, body)
        if not r.msg.startswith("ok_"):
            raise SystemExit(f"запись {path}: {r.status} {r.body[:200]}")


def measure(cdp: CDP, page: Page, kind: str, arg, label: str, size: str) -> dict:
    if not page.js(f"window.__dp.go({json.dumps(kind)}, {json.dumps(arg)})"):
        return {"size": size, "what": label, "skip": True}
    time.sleep(SETTLE)
    d = json.loads(page.js("(window.__dp.on = false, JSON.stringify(window.__dp))"))
    late = [s for s in d["shifts"] if d["first"] is not None and s["frame"] > d["first"] and not s["input"]]
    ms = json.loads(page.js(f"JSON.stringify([window.__dp.ms({json.dumps(d['first'])}), window.__dp.ms({json.dumps(d['ready'])})])"))
    return {"size": size, "what": label, "first": ms[0], "ready": ms[1], "busy": d["ready"] != d["first"], "late": late,
            "total": round(sum(s["v"] for s in late), 4), "errors": cdp.errors(), "trace": d["trace"], "mut": d.get("mutWhat")}


def run(out: pathlib.Path | None, only: str, port: int = PORT) -> int:
    day = clinic_today().isoformat()
    s1 = Server(keep_dir=True)
    preconditions(s1.dir)
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        c = Client(s1.url).login(PIN)
        ids = seed(c, day)
        pid2 = seed_more(c, day, ids["pid"])
        seed_registre(c)
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-spa-shift")
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    proc, rows = None, []
    try:
        with s2:
            cookie = pin_cookie(s2.url)
            proc, ws = start_edge(profile, port=port)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network", "Log"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=s2.url + "/")
            cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=PROBE)
            page = Page(cdp, s2.url)

            def slow(on: bool) -> None:
                cdp.cmd("Network.emulateNetworkConditions", offline=False, latency=LATENCY if on else 0,
                        downloadThroughput=-1, uploadThroughput=-1)

            card = fill("/admin/patient/{pid}", ids)
            for w, h in SIZES:
                size = f"{w}x{h}"
                page.size(w, h)
                for target, kind in [t for t in TARGETS if only in t[0]]:
                    for src in TARGET_SOURCES.get(target, SOURCES):
                        url = fill(src, ids)
                        slow(False)
                        page.go(url)
                        time.sleep(1.0)
                        slow(True)
                        rows.append(measure(cdp, page, kind, target, f"{url} -> {target}", size))
                if only in "card":
                    slow(False)
                    page.go(card)
                    time.sleep(1.0)
                    slow(True)
                    n = int(page.js(f"document.querySelectorAll({json.dumps(CARD_TABS)}).length"))
                    for i in list(range(1, n)) + [0]:
                        name = page.js(f"document.querySelectorAll({json.dumps(CARD_TABS)})[{i}].getAttribute('aria-label')")
                        rows.append(measure(cdp, page, "tab", i, f"fișa: tab «{name}»", size))
                    for to in (f"/admin/patient/{pid2}", card, f"/admin/patient/{pid2}?tab=plan"):
                        rows.append(measure(cdp, page, "pop", to, f"fișa -> {to}", size))
                if only in "registre":
                    slow(False)
                    page.go("/admin/registre")
                    time.sleep(1.0)
                    slow(True)
                    for label in REGISTRE_CLICKS:
                        rows.append(measure(cdp, page, "click", label, f"Registre: «{label}»", size))
                if only in "menu":
                    done_menu = {t for t, _ in TARGETS}
                    for src in MENU_SOURCES:
                        url = fill(src, ids)
                        slow(False)
                        page.go(url)
                        time.sleep(1.0)
                        links = json.loads(page.js("JSON.stringify([...new Set([...document.querySelectorAll("
                                                   "'aside nav a[href]')].map((a) => a.getAttribute('href')))])"))
                        for href in [h for h in links if h not in done_menu and h.split("?")[0] != url]:
                            page.go(url)
                            time.sleep(1.0)
                            slow(True)
                            rows.append(measure(cdp, page, "menu", href, f"meniu: {url} -> {href}", size))
                            slow(False)
                if only in "screens":
                    for path in screen_map.FLAG:
                        to = fill(path, ids)
                        if to == "/admin":
                            continue
                        slow(False)
                        page.go("/admin")
                        time.sleep(1.0)
                        slow(True)
                        row = measure(cdp, page, "pop", to, f"ecran: /admin -> {to}", size)
                        row["known"] = KNOWN.get(path, "")
                        rows.append(row)
            slow(False)
    finally:
        if proc:
            proc.kill()
        s1.drop()

    red = done = known = 0
    for r in rows:
        if r.get("skip"):
            done += 1
            red += 1
            print(f"RED {r['size']} {r['what']:<46} перехода нет: ссылки нет в меню оболочки")
            continue
        done += 1
        busy = r["first"] is not None and r["busy"]
        bad = r["first"] is None or busy or r["total"] >= LIMIT or bool(r["errors"])
        if r.get("known"):
            known += bad
            print(f"{'KNOWN' if bad else 'RED'} {r['size']} {r['what']:<46} сдвиг {r['total']:<7} "
                  + (r["known"] if bad else "больше не прыгает — уберите из KNOWN"))
            red += not bad
            continue
        red += bad
        why = ("нового экрана не дождались" if r["first"] is None else
               f"первый кадр без данных (готов через {r['ready'] - r['first'] if r['ready'] is not None else '?'} мс)" if busy else
               f"сдвиг после первого кадра {r['total']}" if r["total"] >= LIMIT else "")
        print(f"{'RED' if bad else 'OK '} {r['size']} {r['what']:<46} кадр {r['first']!s:>5} мс  "
              f"готов {r['ready']!s:>5} мс  сдвиг {r['total']:<7} {why}")
        for s in r["late"] if bad or r["total"] else []:
            print(f"      t={s['t']} v={s['v']}: " + " | ".join(s["src"]))
        for e in r["errors"]:
            print(f"      консоль: {e}")
        for t, snap in r["trace"] if TRACE and (bad or r["total"]) else []:
            print(f"      кадр t={t}: {snap}")
    print(f"\n{done - red}/{done} переходов: первый кадр нового экрана уже с данными и без сдвигов после"
          + (f" (известных прыжков: {known}, итог не красят)" if known else ""))
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"подробности: {out}")
    return 1 if red or not done else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="",
                    help="часть адреса раздела или группа: card, registre (вкладки), menu (обход меню), screens (все экраны)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "shots" / "spa_shift.json")
    ap.add_argument("--trace", action="store_true", help="у красного — кадр за кадром: адрес, меню, размер, ожидание")
    a = ap.parse_args()
    global TRACE
    TRACE = a.trace
    return run(a.out, a.only, a.port)


if __name__ == "__main__":
    sys.exit(main())
