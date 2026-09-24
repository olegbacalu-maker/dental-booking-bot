# -*- coding: utf-8 -*-
"""Отказ в праве ПОСРЕДИ сеанса — экран не монтируется, уход как у сервера (B3).

    python scripts\\perm_gate.py

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. При открытии документа право проверяет страница сервера, ДО React
(`core/auth.require` → 303 `/admin?msg=no_access`), и загрузчик без права не
запускается вовсе. Отказ приходит загрузчику в одном живом случае: право
отняли, пока вкладка открыта (роль читается из файла на каждом запросе). Здесь
это и делается: директор открывает статистику, роль в `auth.json` меняется на
регистратуру, щелчок по периоду.

Утверждения:
  1. разрешено: статистика открыта, период на экране;
  2. запрещено: после щелчка — `/admin?msg=no_access`, как у страницы сервера;
  3. ни кадра «отказа внутри раздела»: плашки `role=alert` в экране не было.

⛔ Пара: у маршрута без признака `guarded` вкладка остаётся в разделе с
плашкой отказа — стенд обязан это видеть (красное).
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

from harness import Server  # noqa: E402
from mount_sweep import pin_cookie, preconditions  # noqa: E402
from odo_shots import CDP, Page, start_edge  # noqa: E402

WIDE = (1500, 950)
# ⛔ Свой порт отладки: 9337–9344 заняты соседними стендами.
PORT = 9345

# Сэмплер ставится ДО скриптов страницы: ловит плашку отказа, даже мелькнувшую.
# ⚠️ След — в sessionStorage, а не в переменной страницы: плашка могла мелькнуть
# МЕЖДУ щелчком и уходом документа, и переменная ушла бы вместе со страницей.
PROBE = """(() => {
  const look = () => {
    if (document.querySelector('.dp-react-root [role=alert]')) {
      try { sessionStorage.setItem('dpg_alerted', '1') } catch (e) {}
    }
    requestAnimationFrame(look);
  };
  requestAnimationFrame(look);
})()"""

STATE = """JSON.stringify({
  href: location.pathname + location.search,
  stats: location.pathname === '/admin/stats' && !!document.querySelector('.dp-react-root .nav b'),
  alerted: (() => { try { return sessionStorage.getItem('dpg_alerted') === '1' } catch (e) { return false } })(),
  alertNow: !!document.querySelector('.dp-react-root [role=alert]'),
  banner: (document.querySelector('.content .banner, .content .msg') || {}).textContent || '',
})"""


def state(page: Page) -> dict:
    return json.loads(page.js(STATE))


def main() -> int:
    s1 = Server()
    s1._own_dir = False
    preconditions(s1.dir)            # auth.json: директор с ПИНом
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        pass
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-perm-gate")
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    proc, bad = None, []
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

            page.go("/admin/stats")
            time.sleep(1.0)
            a = state(page)
            print(f"разрешено:  {a}")
            if not (a["href"] == "/admin/stats" and a["stats"] and not a["alertNow"]):
                bad.append(f"директор не видит статистику: {a}")

            # ⭐ Понижение на лету: роль читается из файла на КАЖДОМ запросе.
            auth = s1.dir / "auth.json"
            rec = json.loads(auth.read_text(encoding="utf-8"))
            for u in rec["users"]:
                u["role"] = "receptie"
            auth.write_text(json.dumps(rec, indent=1), encoding="utf-8")

            page.js("[...document.querySelectorAll('.dp-react-root .nav a')][0].click()")
            cdp.wait_event("Page.loadEventFired", timeout=8)
            time.sleep(1.2)
            b = state(page)
            print(f"запрещено:  {b}")
            if b["href"] != "/admin?msg=no_access":
                bad.append(f"вкладка не ушла туда, куда страница сервера: {b['href']}")
            if b["alerted"] or b["alertNow"]:
                bad.append("в разделе мелькнула плашка отказа — экран монтировался")
            errs = cdp.errors()
            if errs:
                bad.append("ошибки консоли: " + "; ".join(errs[:3]))
    finally:
        if proc:
            proc.kill()
        s1.__exit__(None, None, None)

    for b in bad:
        print(f"    ✗ {b}")
    print("\nOK: без права экран не монтируется, уход как у сервера" if not bad else "\nRED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
