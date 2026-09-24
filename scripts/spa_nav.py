# -*- coding: utf-8 -*-
"""Переход между экранами без перезагрузки: оболочка остаётся на месте — стенд B4.

    python scripts\\spa_nav.py

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. С B1 оболочку рисует бандл, и полная загрузка документа на каждом
переходе гасит ВСЁ окно — то, что Олег назвал «нет плавности» на канарейке
1.30.0. B4 переводит ссылки между экранами на роутер: документ не
перезагружается, сайдбар и шапка остаются теми же узлами, а модель оболочки
нового адреса приезжает из документа этого адреса (`services/doc.ts`).

Что доказывается настоящим щелчком мыши (Input.dispatchMouseEvent, не
`el.click()`):
  1. панель → «Săptămâna»: адрес и экран недели, документ НЕ перезагружен
     (свидетель — переменная окна, поставленная до щелчка), сайдбар и шапка —
     те же узлы DOM, подпись раздела — от документа нового адреса, и этот
     документ был запрошен fetch-ем;
  2. неделя → «Zi»: то же в обратную сторону;
  3. прокрутка: новый путь открывается сверху, «Назад» возвращает прежнюю
     позицию (окно 500 px высотой, чтобы было куда прокручивать; если
     страница не выше окна — SKIP с причиной, а не тихая зелень);
  4. F5 на адресе, куда привёл переход, даёт тот же экран (то, что и стенд
     url_state_f5, но на этом адресе).

⛔ Пара (без неё стенд ничего не доказывает): та же ссылка, лишённая роутера
(узел подменён клоном без обработчиков React), обязана перезагрузить документ
— свидетель ОБЯЗАН пропасть. Если он уцелел, стенд слеп к перезагрузке.
"""
from __future__ import annotations

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

from harness import Client, Server, clinic_today  # noqa: E402
from mount_sweep import PIN, pin_cookie, preconditions, seed  # noqa: E402
from odo_shots import CDP, Page, start_edge  # noqa: E402

# Окно НИЗКОЕ намеренно: прокрутку иначе не проверить — экраны в 950 px
# помещаются целиком.
SIZE = (1500, 500)
# ⛔ Свой порт отладки: 9337–9345 заняты соседними стендами, и запуск на
# занятом МОЛЧА подключается к чужому браузеру.
PORT = 9346

NAV_LINK = "[...document.querySelectorAll('.dp-react-root .nav a')].find(a => a.textContent.trim() === %s)"

MARK = """(() => {
  window.__dpTok = 'tok' + Math.random();
  const a = document.querySelector('aside.side'); if (a) a.__dpMark = 1;
  const t = document.querySelector('.main .top'); if (t) t.__dpMark = 1;
  return window.__dpTok;
})()"""

STATE = """(() => {
  const r = document.querySelector('.dp-react-root');
  const docs = performance.getEntriesByType('resource')
    .filter(e => e.initiatorType === 'fetch' && !new URL(e.name).pathname.startsWith('/api/'))
    .map(e => { const u = new URL(e.name); return u.pathname + u.search; });
  return JSON.stringify({
    href: location.pathname + location.search,
    tok: window.__dpTok || '',
    aside: !!(document.querySelector('aside.side') || {}).__dpMark,
    top: !!(document.querySelector('.main .top') || {}).__dpMark,
    sub: (document.querySelector('.content .sub') || {}).textContent || '',
    active: (document.querySelector('aside nav a.on') || {getAttribute(){return ''}}).getAttribute('title'),
    busy: r ? r.getAttribute('aria-busy') : 'none',
    week: !!document.querySelector('.dp-react-root .week'),
    dash: !!document.querySelector('.dp-react-root .dash'),
    docs: docs,
    y: window.scrollY,
    tall: document.documentElement.scrollHeight - window.innerHeight,
  });
})()"""


def state(page: Page) -> dict:
    return json.loads(page.js(STATE))


def settle(page: Page, ready, timeout: float = 10.0) -> dict:
    """Ждать, пока `ready(state)` не станет истинным; вернуть последнее состояние."""
    end = time.time() + timeout
    s = state(page)
    while time.time() < end and not ready(s):
        time.sleep(0.05)
        s = state(page)
    return s


def click(page: Page, text: str) -> None:
    """Настоящий щелчок мышью по ссылке шапки экрана.

    ⚠️ Сначала ссылка ставится в середину окна: `Input.dispatchMouseEvent`
    бьёт по координатам ОКНА, а верхняя панель липкая — на прокрученной
    странице щелчок по центру спрятанной под ней ссылки уходил в «+ Programare
    nouă» и уводил документом на `/admin/all#addform` (окно 260 px, шаг 3)."""
    el = NAV_LINK % json.dumps(text)
    page.js(f"(() => {{ const el = {el}; if (el) el.scrollIntoView({{ block: 'center' }}) }})()")
    time.sleep(0.2)
    page.click(el)


def main() -> int:
    day = clinic_today().isoformat()
    s1 = Server()
    s1._own_dir = False
    preconditions(s1.dir)
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        seed(Client(s1.url).login(PIN), day)
    # ⭐ Пин наборов снимается: проверяется то, что клиника увидит по умолчанию.
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-spa-nav")
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    proc, bad, skipped = None, [], []
    try:
        with s2:
            cookie = pin_cookie(s2.url)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network", "Log"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=s2.url + "/")
            page = Page(cdp, s2.url)
            page.size(*SIZE)

            # 1. панель → неделя
            page.go("/admin")
            a = settle(page, lambda s: s["dash"])
            tok = page.js(MARK)
            t0 = time.time()
            click(page, "Săptămâna")
            b = settle(page, lambda s: s["href"].startswith("/admin/week") and s["week"] and s["busy"] != "true")
            ms_spa = int((time.time() - t0) * 1000)
            print(f"панель → неделя: {a['href']} → {b['href']}  «{b['sub'][:40]}»  {ms_spa} ms")
            if not b["href"].startswith("/admin/week?date="):
                bad.append(f"щелчок не привёл на неделю: {b['href']}")
            if b["tok"] != tok:
                bad.append("документ ПЕРЕЗАГРУЖЕН: свидетель окна пропал")
            if not (b["aside"] and b["top"]):
                bad.append("сайдбар или шапка пересозданы — оболочка мигнула")
            if "calendar săptămânal" not in b["sub"]:
                bad.append(f"подпись раздела не от документа недели: «{b['sub']}»")
            if not any(d.startswith("/admin/week") for d in b["docs"]):
                bad.append(f"документ нового адреса не запрашивался: {b['docs']}")
            if not b["week"]:
                bad.append("экран недели не нарисован")

            # 2. неделя → панель
            tok = page.js(MARK)
            click(page, "Zi")
            c = settle(page, lambda s: s["href"].startswith("/admin?") and s["dash"])
            print(f"неделя → панель: {b['href']} → {c['href']}  «{c['sub'][:40]}»")
            if c["tok"] != tok:
                bad.append("обратно: документ ПЕРЕЗАГРУЖЕН")
            if not (c["aside"] and c["top"]):
                bad.append("обратно: сайдбар или шапка пересозданы")
            if "panou principal" not in c["sub"]:
                bad.append(f"обратно: подпись не от документа панели: «{c['sub']}»")
            if c["active"] != "Dashboard":
                bad.append(f"активный пункт меню: «{c['active']}», ждали «Dashboard»")

            # 3. прокрутка: новый путь — сверху, «Назад» — где были. Окно на
            # время шага ещё ниже: неделя с засевом умещается и в 500 px.
            page.size(SIZE[0], 260)
            click(page, "Săptămâna")
            d = settle(page, lambda s: s["week"] and s["busy"] != "true")
            if d["tall"] < 120:
                skipped.append(f"прокрутка: неделя не выше окна ({d['tall']} px запаса) — нечего проверять")
            else:
                page.js("window.scrollTo(0, 120)")
                time.sleep(0.3)
                # `click` подводит ссылку под окно, поэтому позиция снимается ПОСЛЕ
                # этого — и именно её обязан вернуть «Назад».
                page.js(f"(() => {{ const el = {NAV_LINK % '"Zi"'}; el.scrollIntoView({{ block: 'center' }}) }})()")
                time.sleep(0.2)
                y0 = state(page)["y"]
                click(page, "Zi")
                e = settle(page, lambda s: s["dash"] and s["busy"] != "true")
                time.sleep(0.3)
                e = state(page)
                if not e["dash"]:
                    bad.append(f"прокрутка: щелчок «Zi» не привёл на панель: {e['href']}")
                elif e["y"] != 0:
                    bad.append(f"новый путь открылся не сверху: scrollY={e['y']}")
                page.js("history.back()")
                f = settle(page, lambda s: s["href"].startswith("/admin/week") and s["week"] and s["busy"] != "true")
                time.sleep(0.5)
                f = state(page)
                print(f"прокрутка: неделя@{y0} → панель y={e['y']} → назад y={f['y']}")
                if y0 == 0:
                    skipped.append("прокрутка «Назад»: ссылка «Zi» видна без прокрутки — возврат позиции не отличим от верха")
                elif abs(f["y"] - y0) > 4:
                    bad.append(f"«Назад» не вернул прокрутку: y={f['y']}, ждали {y0}")
            page.size(*SIZE)

            # 4. F5 на адресе, куда привёл переход
            g = state(page)
            cdp.cmd("Page.reload", ignoreCache=True)
            cdp.wait_event("Page.loadEventFired", timeout=15)
            h = settle(page, lambda s: s["week"] and s["busy"] != "true")
            print(f"F5: {g['href']} → {h['href']}  «{h['sub'][:40]}»")
            if h["href"] != g["href"] or "calendar săptămânal" not in h["sub"] or not h["week"]:
                bad.append(f"F5 на адресе перехода дал другой экран: {h['href']} «{h['sub'][:40]}»")

            # для сравнения — документом, как было до B4
            t0 = time.time()
            page.go(b["href"])
            settle(page, lambda s: s["week"] and s["busy"] != "true")
            ms_doc = int((time.time() - t0) * 1000)
            print(f"для сравнения: тот же адрес документом — {ms_doc} ms (переходом — {ms_spa} ms; "
                  f"грубо, шаг опроса 50 ms + дренаж CDP)")

            errs = cdp.errors()
            if errs:
                bad.append("ошибки консоли: " + "; ".join(errs[:3]))

            # ⛔ Пара: обычная ссылка перезагружает документ — свидетель пропадает
            page.go("/admin")
            settle(page, lambda s: s["dash"])
            tok = page.js(MARK)
            page.js("(() => { const a = %s; a.replaceWith(a.cloneNode(true)); })()" % (NAV_LINK % '"Săptămâna"'))
            click(page, "Săptămâna")
            cdp.wait_event("Page.loadEventFired", timeout=15)
            p = settle(page, lambda s: s["week"] and s["busy"] != "true")
            print(f"пара (обычная ссылка): {p['href']}  свидетель {'ПРОПАЛ' if p['tok'] != tok else 'уцелел'}")
            if p["tok"] == tok:
                bad.append("пара: обычная ссылка НЕ перезагрузила документ — стенд слеп к перезагрузке")
    finally:
        if proc:
            proc.kill()
        s1.__exit__(None, None, None)

    for s in skipped:
        print(f"    SKIP {s}")
    for b in bad:
        print(f"    ✗ {b}")
    print("\nOK: переход без перезагрузки, оболочка на месте, пара красная"
          if not bad else "\nRED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
