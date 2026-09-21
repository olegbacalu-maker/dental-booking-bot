# -*- coding: utf-8 -*-
"""Живой монтаж ВСЕХ React-экранов в headless Edge — один проход, один вопрос.

    python scripts\\mount_sweep.py [--out DIR] [--only settings_faq,visit]

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить
— это окружение сборки).

Зачем, если есть 411 проверок клиента и 23/23 серверных набора. Потому что все
они читают ИСХОДНИК, а дефект живёт в РЕЗУЛЬТАТЕ: экран, который в настоящем
браузере не смонтировался вовсе, оставляет зелёными и Vitest, и питоновский
прогон — узел React пуст, а серверная заглушка внутри него читается как обычный
текст страницы. Прайор проекта назван опытом 21.09, три дефекта подряд.

⭐ **Это НЕ 23 полноценных E2E-теста, и расширять до них не надо.** Поведение
каждого экрана уже доказано своим слоем; здесь закрывается ровно остаточный
класс: «экран открылся у человека». Семь утверждений на экран, все общие:

  1. маршрут отвечает — ни один запрос страницы не пришёл с 4xx/5xx;
  2. сервер выбрал React — узел `#root` несёт `data-screen` этого экрана;
  3. бандл ВЫПОЛНИЛСЯ — есть `.dp-react-root`, серверной заглушки нет;
  4. данные пришли — экран не остался в `aria-busy` и не пуст;
  5. ни одного исключения JS и ни одной ошибки консоли;
  6. ни одного ответа `/api/` с 4xx/5xx — отказ, спрятанный за версткой;
  7. экран не свалился в legacy и не показал «такого экрана нет».

⛔ Список экранов НЕ пишется здесь руками — он берётся из `parity_audit`.
Рукописный разошёлся бы с `REACT_SCREENS` молча, и проход объявил бы полным то,
чего не открывал.
⭐ Подстановка параметров — по ИМЕНИ параметра (`{pid}`, `{dk}`, `{appt_id}`),
а не по экрану: имён три, и они не растут от новых экранов.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core import auth  # noqa: E402
from harness import Client, Server, clinic_today  # noqa: E402
from odo_shots import CDP, Page, start_edge  # noqa: E402
from parity_audit import audit  # noqa: E402

WIDE = (1500, 950)
# PIN лаборатории. ⚠️ Как только рядом появляется `auth.json`, вход по
# `ADMIN_KEY` перестаёт работать: подпись сессии берётся из файла. Значит и
# заходить надо им.
PIN = "43219876"
# ⛔ Свой порт отладки: 9337–9341 заняты соседними стендами, и запуск на занятом
# МОЛЧА подключается к чужому браузеру.
PORT = 9342

STUB = "Interfața nouă nu s-a încărcat"
UNKNOWN = "nu există în interfața nouă"
OFFLINE = "Programul nu răspunde"

STATE_JS = """(() => {
  const root = document.getElementById('root');
  const react = document.querySelector('.dp-react-root');
  const txt = react ? react.innerText : '';
  return JSON.stringify({
    root: !!root,
    screen: root ? (root.dataset.screen || '') : '',
    stub: !!(root && root.textContent.includes(%s)),
    react: !!react,
    busy: react ? react.getAttribute('aria-busy') : null,
    nodes: react ? react.querySelectorAll('*').length : 0,
    len: txt.trim().length,
    unknown: txt.includes(%s),
    offline: txt.includes(%s),
    live_wrap: !!document.getElementById('live'),
  });
})()""" % (json.dumps(STUB), json.dumps(UNKNOWN), json.dumps(OFFLINE))


def preconditions(dir_: pathlib.Path) -> None:
    """Чего экраны ТРЕБУЮТ, чтобы вообще открыться.

    ⛔ Два экрана уводят на хаб редиректом, и это не дефект, а предусловие:
    «Acces din rețea» живёт только у настольного издания (`DENTART_ENV_FILE`
    ставит лаунчер), а «Securitate» — только там, где заведён `auth.json`.
    ⭐ Удовлетворяем их, а НЕ выбрасываем экраны из списка: выброшенный экран
    тихо не проверяется, и проход всё равно объявляет себя полным.
    ⚠️ Файл кладётся ДО первого старта: иначе первый запуск запомнит отпечаток
    без него, второй увидит расхождение и поднимет ложную тревогу подмены.
    """
    (dir_ / "dental.env").write_text("TELEGRAM_TOKEN=\nADMIN_KEY=\n",
                                     encoding="utf-8")
    users = [{"id": "dir", "role": auth.ROLE_DIRECTOR, "name": "Director",
              **auth._secret_fields(PIN)}]
    (dir_ / "auth.json").write_text(
        json.dumps({"v": 2, "cookie_key": "sweep" * 12, "users": users}, indent=1),
        encoding="utf-8")


def pin_cookie(origin: str) -> str:
    """Кука входа ПИНом. `odo_shots.login_cookie` заходит по `ADMIN_KEY`, а он
    здесь уже не действует."""
    import http.client
    import re as _re
    import urllib.parse as _up
    host, port = origin.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    conn.request("POST", "/admin/login", _up.urlencode({"password": PIN}),
                 {"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    got = resp.getheader("Set-Cookie") or ""
    resp.read()
    conn.close()
    m = _re.search(r"admin_auth=([^;]+)", got)
    if not m:
        raise SystemExit(f"вход ПИНом не удался: HTTP {resp.status}, {got!r}")
    return m.group(1)


def seed(c: Client, day: str) -> dict:
    """Минимум, без которого параметрические адреса некуда направить."""
    c.post("/admin/add", adate=day, atime="09:00", adoctor="d2",
           aservice="consult", aname="Proba Mount", aphone="069000099",
           back="/admin/all")
    rows = json.loads(c.get("/api/patients?q=Proba").body)["data"]["rows"]
    today = json.loads(c.get("/api/doctors/d2").body)["data"]["today"]
    if not rows or not today:
        raise SystemExit(f"засев не удался: пациентов {len(rows)}, визитов {len(today)}")
    return {"pid": str(rows[0]["id"]), "dk": "d2", "appt_id": str(today[0]["id"])}


def fill(path: str, ids: dict) -> str:
    """`/admin/patient/{pid}` → реальный адрес. Незнакомый параметр — ошибка
    ГРОМКАЯ: молча подставленная пустая строка дала бы 404, и проход обвинил бы
    экран в том, чего тот не делал."""
    def sub(m):
        name = m.group(1)
        if name not in ids:
            raise SystemExit(f"{path}: параметр {{{name}}} нечем заполнить — "
                             f"допишите его в seed(); известны {sorted(ids)}")
        return ids[name]
    return re.sub(r"\{(\w+)\}", sub, path)


def http_failures(events: list) -> list[str]:
    """Ответы 4xx/5xx у страницы и её запросов. ⭐ Отдельно от консоли: отказ,
    который экран проглотил и нарисовал пустоту, в консоль не попадает."""
    bad = []
    for e in events:
        if e.get("method") != "Network.responseReceived":
            continue
        r = e["params"]["response"]
        if r.get("status", 0) >= 400:
            url = r.get("url", "")
            if "/admin" in url or "/api/" in url or "/static/" in url:
                bad.append(f"{r['status']} {url.split('?')[0]}")
    return bad


def run(out: pathlib.Path, only: set[str] | None) -> int:
    rows = [r for r in audit() if r["path"] and (not only or r["screen"] in only)]
    if not rows:
        raise SystemExit("нечего открывать: аудит не дал ни одного экрана с адресом")
    out.mkdir(parents=True, exist_ok=True)
    flags = [r["screen"] for r in rows]

    day = clinic_today().isoformat()
    s1 = Server()
    s1._own_dir = False
    preconditions(s1.dir)
    s1.extra_env["DENTART_ENV_FILE"] = str(s1.dir / "dental.env")
    with s1:
        ids = seed(Client(s1.url).login(PIN), day)
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    # ⚠️ Все флаги разом. Это НЕ выкат: профиль лаборатории живёт в темпе и
    # никакой клиники не касается. Вопрос прохода — «открывается ли», а он
    # задаётся только при включённом флаге.
    cfg["ui"] = {"react": flags}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-mount-sweep")
    results, proc = [], None
    s2 = Server(dir_=s1.dir, env={"DENTART_ENV_FILE": str(s1.dir / "dental.env")})
    try:
        with s2:
            origin = s2.url
            cookie = pin_cookie(origin)
            proc, ws_url = start_edge(profile, port=PORT)
            cdp = CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie,
                    url=origin + "/")
            page = Page(cdp, origin)
            page.size(*WIDE)

            for r in rows:
                name, path = r["screen"], fill(r["path"], ids)
                cdp.events.clear()          # своя история на каждый экран
                fails = []
                page.go(path)
                cdp.drain(1.2)
                net = http_failures(cdp.events)
                st = json.loads(page.js(STATE_JS))
                errs = cdp.errors()

                if net:
                    fails.append("HTTP: " + "; ".join(sorted(set(net))[:4]))
                if not st["root"]:
                    fails.append("узла #root нет — сервер отдал старую страницу")
                elif st["screen"] != name:
                    fails.append(f"сервер выбрал не тот экран: {st['screen']!r}")
                if st["stub"]:
                    fails.append("бандл не выполнился: внутри узла заглушка")
                if not st["react"]:
                    fails.append("нет .dp-react-root — экран не смонтировался")
                if st["unknown"]:
                    fails.append("App.tsx не знает этого имени — UnknownScreen")
                if st["offline"]:
                    fails.append("экран показывает отказ загрузки")
                if st["busy"] == "true":
                    fails.append("данные так и не пришли: остался aria-busy")
                if st["react"] and (st["len"] < 20 or st["nodes"] < 3):
                    fails.append(f"экран пуст: {st['len']} симв., {st['nodes']} узлов")
                if st["live_wrap"] and st["react"]:
                    # ⛔ Правило карты: узел React никогда не внутри #live.
                    fails.append("живая обёртка вокруг смонтированного узла")
                fails += [f"консоль: {e}" for e in errs]

                page.png(out / f"{name}.png")
                results.append((name, path, fails))
                print(("OK  " if not fails else "RED ") + f"{name:<18} {path}")
                for f in fails:
                    print("     ·", f)
    finally:
        if proc:
            proc.kill()
        s1.__exit__(None, None, None)

    bad = [n for n, _p, f in results if f]
    print(f"\n{len(results) - len(bad)}/{len(results)} экранов смонтировались; "
          f"кадры: {out}")
    if bad:
        print("красные: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "mount"))
    ap.add_argument("--only", default="", help="через запятую, для разбора красного")
    a = ap.parse_args()
    sys.exit(run(pathlib.Path(a.out),
                 {s.strip() for s in a.only.split(",") if s.strip()} or None))
