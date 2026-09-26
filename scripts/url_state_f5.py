# -*- coding: utf-8 -*-
"""F5 на адресе, который написал роутер, даёт тот же экран — стенд B2.3.

    python scripts\\url_state_f5.py

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. Переход внутри экрана (соседняя неделя, другой день, период, осмотр,
лента фиши) меняет адрес РОУТЕРОМ, и загрузчик читает уже новый адрес. Если
перезагрузка на этом адресе не воспроизводит то же состояние, маршрутизация
получилась только видимой: адрес говорит одно, экран показывает другое, а
закладка и F5 открывают третье. Клиентские проверки открывают свежий роутер
на том же адресе, но страницу СЕРВЕРА не видят; здесь — настоящий документ.

Один сценарий на все экраны: открыть адрес → переход внутри экрана → снять
(адрес, запрос API, ключевой текст) → F5 → снять ещё раз → сравнить.

⛔ Зелёный стенд сам по себе ничего не доказывает. Пара: при адресе, записанном
мимо роутера (`history.replaceState`), загрузчик не перечитывает данные, и
ключ после F5 обязан разойтись — иначе стенд этого не видит.
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
from mount_sweep import PIN, fill, pin_cookie, preconditions, seed  # noqa: E402
from odo_shots import CDP, Page, start_edge  # noqa: E402

WIDE = (1500, 950)
# ⛔ Свой порт отладки: 9337–9343 заняты соседними стендами.
PORT = 9344

ROOT_A = "[...document.querySelectorAll('.dp-react-root .nav a')]"
NAV_B = "(document.querySelector('.dp-react-root .nav b')||{}).textContent||''"

# (имя, адрес, что нажать (JS → элемент) или None, ключ (JS → строка),
#  образец запроса API, сравнивать ли запрос)
CASES = [
    ("неделя", "/admin/week", f"{ROOT_A}.find(a => a.textContent.includes('săpt.'))",
     NAV_B, "/api/schedule/week", True),
    ("день клиники", "/admin/all", f"{ROOT_A}[0]", NAV_B, "/api/schedule/day", True),
    ("день врача", "/admin/doctor/{dk}", f"{ROOT_A}[0]", NAV_B, "/api/schedule/day", True),
    ("статистика", "/admin/stats", f"{ROOT_A}[0]", NAV_B, "/api/stats", True),
    ("пародонтограма", "/admin/patient/{pid}/parodontograma",
     "[...document.querySelectorAll('.dp-react-root button')]"
     ".find(b => /Examen nou|Începe primul examen/.test(b.textContent))",
     "(document.querySelector('.pexam')||{}).value||''", "/perio", True),
    # ⚠️ Лента фиши — без сравнения запроса: переключатель НАМЕРЕННО не
    # перезапускает загрузчик (иначе журнал доступа получал бы лишнее «открыл
    # фишу»), а F5 грузит фишу сразу с лентой. Сравнивается адрес и режим.
    ("фиша: лента доступа", "/admin/patient/{pid}", "document.querySelector('.dp-views')",
     "(document.querySelector('.dp-views')||{}).textContent||''", "/api/patients/", False),
    # Поиск: смена отбора дочитывает только список (сводка — раз на открытие),
    # загрузчик её не видит; F5 обязан собрать тот же список по адресу.
    ("поиск: сортировка", "/admin/search",
     "[...document.querySelectorAll('.pl-card thead th a')].find(a => a.textContent.trim() === 'Pacient')",
     "([...document.querySelectorAll('.pl-card thead th a')].find(a => a.querySelector('svg'))||{}).textContent||''",
     "/api/patients?", True),
    ("визит", "/admin/visit/{appt_id}?back=%2Fadmin%2Fall", None,
     "([...document.querySelectorAll('.dp-react-root a')].find(a => a.textContent.includes('Înapoi'))"
     "||{getAttribute(){return ''}}).getAttribute('href')", "/api/visits/", True),
]

SNAP = """(() => {
  const r = document.querySelector('.dp-react-root');
  const api = performance.getEntriesByType('resource').map(e => e.name)
    .filter(n => n.includes(%s)).map(n => { const u = new URL(n); return u.pathname + u.search; });
  return JSON.stringify({
    href: location.pathname + location.search,
    busy: r ? r.getAttribute('aria-busy') : 'none',
    api: api.length ? api[api.length - 1] : '',
    key: String(%s).trim(),
  });
})()"""


def snap(page: Page, api_rx: str, key_js: str) -> dict:
    return json.loads(page.js(SNAP % (json.dumps(api_rx), key_js)))


def settle(page: Page, api_rx: str, key_js: str, want_href_change: str | None = None) -> dict:
    """Ждать, пока экран выйдет из ожидания (и адрес сменится, если ждём)."""
    end = time.time() + 10
    s = snap(page, api_rx, key_js)
    while time.time() < end:
        s = snap(page, api_rx, key_js)
        if s["busy"] != "true" and s["key"] and (want_href_change is None or s["href"] != want_href_change):
            break
        time.sleep(0.2)
    time.sleep(0.8)
    return snap(page, api_rx, key_js)


def run_case(page: Page, cdp: CDP, case, ids) -> dict:
    name, path, click_js, key_js, api_rx, cmp_api = case
    url = fill(path, ids)
    page.go(url)
    start = settle(page, api_rx, key_js)
    if click_js:
        ok = page.js(f"(() => {{ const el = {click_js}; if (!el) return false; el.click(); return true }})()")
        if not ok:
            return {"name": name, "bad": [f"нечего нажать: {click_js}"]}
        before = settle(page, api_rx, key_js, want_href_change=start["href"])
    else:
        before = start
    cdp.cmd("Page.reload", ignoreCache=True)
    cdp.wait_event("Page.loadEventFired", timeout=15)
    after = settle(page, api_rx, key_js)
    bad = []
    if click_js and before["href"] == start["href"]:
        bad.append(f"переход не сменил адрес: {start['href']}")
    if after["href"] != before["href"]:
        bad.append(f"адрес после F5 другой: {before['href']} → {after['href']}")
    if after["key"] != before["key"]:
        bad.append(f"экран после F5 другой: «{before['key']}» → «{after['key']}»")
    if cmp_api and after["api"] != before["api"]:
        bad.append(f"запрос после F5 другой: {before['api']} → {after['api']}")
    if not before["key"]:
        bad.append("ключ пуст — стенд ничего не сравнил")
    errs = cdp.errors()
    if errs:
        bad.append("ошибки консоли: " + "; ".join(errs[:3]))
    return {"name": name, "start": start, "before": before, "after": after, "bad": bad}


def main() -> int:
    day = clinic_today().isoformat()
    s1 = Server(keep_dir=True)
    preconditions(s1.dir)
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        ids = seed(Client(s1.url).login(PIN), day)
    # ⭐ Пин наборов снимается: проверяется то, что клиника увидит по умолчанию.
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-url-f5")
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    proc, results = None, []
    try:
        with s2:
            cookie = pin_cookie(s2.url)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network", "Log"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=s2.url + "/")
            page = Page(cdp, s2.url)
            page.size(*WIDE)
            for case in CASES:
                cdp.events.clear()
                results.append(run_case(page, cdp, case, ids))
    finally:
        if proc:
            proc.kill()
        s1.drop()

    red = 0
    for r in results:
        red += bool(r["bad"])
        print(f"{'OK ' if not r['bad'] else 'RED'} {r['name']}")
        if "before" in r:
            print(f"    до F5:    {r['before']['href']}  «{r['before']['key'][:60]}»  {r['before']['api']}")
            print(f"    после F5: {r['after']['href']}  «{r['after']['key'][:60]}»  {r['after']['api']}")
        for b in r["bad"]:
            print(f"    ✗ {b}")
    print(f"\n{len(results) - red}/{len(results)}: F5 на адресе роутера даёт тот же экран")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
