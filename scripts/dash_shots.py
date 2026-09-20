# -*- coding: utf-8 -*-
"""Сцены React-панели дня в headless Edge: ЖИВОЕ ОБНОВЛЕНИЕ двумя клиентами (C26.5.2).

⛔ Не в CI и не в `.\\dev test`: нужны Edge и пакет websocket-client в
СИСТЕМНОМ Python (в .venv-desktop ничего не ставить — это окружение сборки).

Запуск из app\\:   python scripts\\dash_shots.py [--out DIR]

Зачем отдельно от прогона. Проверки клиента доказывают правило, прогон —
контракт сервера, а «живой» — это ЦЕПОЧКА целиком: канал → опрос → состояние
React → отрисовка → раскладка. Красивая панель, переставшая слушать протокол,
проходит и Vitest, и питоновский прогон: первая отрисовка у неё верна.

Сцены:
  1. панель отрисована из ОДНОГО конверта — канва, повестка, плитки,
     мини-календарь, загрузка; линия «сейчас» РОВНО ОДНА;
  2. ⭐ главная: ВТОРОЕ рабочее место добавляет запись обычным HTTP — в
     пределах одного опроса блок приезжает на экран, а геометрия соседа НЕ
     меняется;
  3. неизменный день: за полторы минуты опрос не даёт НИ ОДНОЙ мутации DOM,
     а линия «сейчас» при этом ЖИВА и сдвинулась. ⚠️ Проверки линии
     пропускаются, если стенд запущен ВНЕ рабочих часов клиники: тогда линии
     законно нет, и требовать её значило бы краснеть по неверной причине.
     Пропуск печатается вслух — молчаливый пропуск это ложное зелёное. ⚠️ Оба условия вместе:
     «ноль мутаций» в одиночку зелено и у намертво замершего экрана — самая
     частая форма ложного зелёного в этом проекте. Окно длиннее минуты
     намеренно (разбор у константы QUIET);
  4. `?ui=legacy` возвращает старую панель, и она снова живая;
  5. ⭐ ДВА БРАУЗЕРА (C26.5.3-g): A переносит визит мышью, B не делает ничего.
     Снимок A, снимок B и состояние БАЗЫ обязаны сойтись, а после команды у A
     не должно быть НИ ОДНОГО кадра с докомандным местом блока. ⚠️ Здесь
     проверяется то, чего не может jsdom: настоящая геометрия, настоящее
     наложение блоков на ячейки и настоящая цепочка команда → канал → экран.

К каждой — PNG и проверки; красная проверка даёт код возврата 1, кадры
остаются, чтобы посмотреть глазами.
"""
import argparse
import json
import os
import pathlib
import sys
import time
from datetime import timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from odo_shots import CDP, Page, login_cookie, start_edge  # noqa: E402
from harness import Client, Server, clinic_today  # noqa: E402

WIDE = (1500, 950)
# ⛔ Свой порт отладки: 9337 и 9338 заняты соседними стендами, и запуск на
# занятом молча подключился бы к ЧУЖОМУ браузеру.
PORT = 9339
# Период опроса клиента (services/live.LIVE_MS) плюс запас на ответ.
TICK = 13.0
# ⚠️ Окно тишины — больше МИНУТЫ, и это не перестраховка. Линия «сейчас»
# пересчитывается раз в 30 с, но ДВИГАЕТСЯ только когда сменилась минута:
# на окне в 39 с она законно стоит на месте, и проверка «линия жива» краснела
# бы через раз (наступил 19.09). Плюс за 95 с чужой интервал `placeNowline`
# из panel.js получает три попытки доклеить вторую линию.
QUIET = 95.0

CHECK_JS = """(() => {
  const blocks = Array.from(document.querySelectorAll('.gridbody [data-appt]'));
  const geom = {};
  for (const b of blocks) geom[b.getAttribute('data-appt')] = b.style.top + '|' + b.style.width;
  return JSON.stringify({
    cols: Array.from(document.querySelectorAll('.gridhead .dcard .nm a'))
      .map(a => a.textContent),
    appts: blocks.map(b => b.getAttribute('data-appt')
      + '@' + (b.querySelector('b') || {}).textContent),
    geom: geom,
    nowlines: document.querySelectorAll('.nowline').length,
    /* ⚠️ Линия «сейчас» есть ТОЛЬКО когда текущий час клиники попал в сетку
       дня. Стенд гоняют и ночью, и тогда её законно нет — а проверка «линия
       ровно одна» краснела бы по неверной причине (наступил 20.09, 00:24). */
    hour_in_grid: (() => {
      const tz = (document.getElementById('sf_clock') || {}).dataset;
      const hh = new Intl.DateTimeFormat('en-CA', {
        timeZone: (tz && tz.tz) || undefined, hourCycle: 'h23', hour: '2-digit',
      }).format(new Date());
      return Array.from(document.querySelectorAll('.gcol-time > div'))
        .some(d => d.textContent.slice(0, 2) === hh);
    })(),
    agenda: Array.from(document.querySelectorAll('.ag-i .ag-t')).map(t => t.textContent),
    agenda_count: (document.querySelector('.ag-h span') || {}).textContent || null,
    tiles: Array.from(document.querySelectorAll('.rk-i .rk-l')).map(t => t.textContent),
    occ: (document.querySelector('.rk-occ b') || {}).textContent || null,
    mcal: (document.querySelector('.mcal .mhead b') || {}).textContent || null,
    sparks: document.querySelectorAll('.spark').length,
    react: !!document.getElementById('root'),
    live_wrap: !!document.getElementById('live'),
    muts: window.__dpMut === undefined ? null : window.__dpMut,
    line_moves: window.__dpLine === undefined ? null : window.__dpLine,
    w: document.documentElement.clientWidth,
    h: document.body.scrollHeight,
  });
})()"""

WATCH_JS = """(() => {
  window.__dpMut = 0;
  window.__dpLine = 0;
  const isLine = (n) => n && n.nodeType === 1 && n.classList
    && n.classList.contains('nowline');
  /* ⚠️ Линию «сейчас» считаем ОТДЕЛЬНО, а не вместе со всем. Она обязана
     двигаться раз в 30 секунд — это часы, а не опрос, и смешав их, сцена
     краснела бы на правильном поведении. Зато её ноль — тоже находка:
     значит экран замер. */
  window.__dpObs = new MutationObserver(ms => {
    for (const m of ms) {
      const t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
      if (isLine(t)) { window.__dpLine++; continue; }
      const nodes = [...m.addedNodes, ...m.removedNodes];
      if (nodes.length && nodes.every(isLine)) { window.__dpLine++; continue; }
      window.__dpMut++;
    }
  });
  window.__dpObs.observe(document.querySelector('.dash'),
    {childList: true, subtree: true, attributes: true, characterData: true});
  return 1;
})()"""


def _seed(c: Client, day: str) -> None:
    """День с двумя врачами, заметкой стойки и ожидающим пациентом."""
    c.post("/admin/add", adate=day, atime="09:00", adoctor="d2", aservice="consult",
           aname="Ion Popa", aphone="069190190", back=f"/admin?date={day}")
    c.post("/admin/add", adate=day, atime="12:00", adoctor="d3", aservice="consult",
           aname="Maria Rusu", aphone="069190191", back=f"/admin?date={day}")
    c.post("/admin/note", ndate=day, ntime="15:00", ndoctor="d2",
           ntext="Livrare materiale pentru cabinetul doi", back=f"/admin?date={day}")


# Где стоит блок: `style.top` как его печатает React (доли ячейки в calc()).
# ⚠️ Сравнивается СТРОКА стиля, а не пиксели: пиксель ячейки ставит замер в
# браузере, и на другом размере окна он законно другой — а вот множитель в
# `calc()` обязан быть тем же у обоих клиентов.
WHERE_JS = """(() => {
  const b = document.querySelector('.gridbody [data-appt="%s"]');
  return JSON.stringify({top: b ? b.style.top : null,
                         col: b ? (b.closest('.gcol') || {}).dataset.dk : null});
})()"""


def _second_browser(origin: str, cookie: str) -> tuple:
    """Второе рабочее место — ОТДЕЛЬНЫЙ БРАУЗЕР, а не вторая вкладка.

    ⛔ И это не придирка к чистоте: живой опрос НЕ ИДЁТ у невидимой вкладки —
    так у React (`useLive`: `if (stopped || document.hidden) return`), так и у
    легаси (`panel.js`), и это правильно: фоновая вкладка не обязана дёргать
    движок. Открой второго клиента вкладкой в том же окне — и ПЕРВЫЙ станет
    скрытым, перестанет опрашивать и замрёт. Сцена 20.09 так и покраснела:
    команда прошла, база и второй экран сошлись, а первый стоял на
    докомандном месте. Два рабочих места — это два ОКНА.
    ⚠️ Свой профиль и свой порт отладки: общий профиль два headless-процесса
    не делят.
    """
    proc2, ws2 = start_edge(os.path.join(os.environ["TEMP"], "dp-edge-dash-b"),
                            port=PORT + 1)
    cdp2 = CDP(ws2)
    for dom in ("Network", "Runtime", "Log", "Page"):
        cdp2.cmd(f"{dom}.enable")
    cdp2.cmd("Network.setCookie", name="admin_auth", value=cookie,
             url=origin + "/")
    return proc2, cdp2, Page(cdp2, origin)


def _drag(page: Page, appt: int, col_i: int, hour: int, half: bool) -> str:
    """Перетащить визит в ячейку `hour` (нижняя половина — получас).

    ⛔ Координата берётся у НАСТОЯЩЕГО прямоугольника ячейки: ровно то, чего
    не проверить в jsdom, где геометрии нет вовсе и её приходится подставлять.
    ⚠️ Сначала пробуем НАСТОЯЩЕЕ перетаскивание браузера (`Input.setInterceptDrags`
    + `Input.dispatchDragEvent`). Если Edge не перехватил бросок за отведённое
    время, событие собирается в самой странице — тоже настоящим `DragEvent` с
    настоящими координатами, но мимо машинерии браузера. О подмене печатается
    ВСЛУХ: молчаливый откат — это ложное зелёное.
    """
    xy = json.loads(page.js(
        "(() => { const c = document.querySelectorAll('.gridbody .gcol')[%d]"
        ".querySelector('.gcell[data-h=\"%d\"]'); const r = c.getBoundingClientRect();"
        " return JSON.stringify([r.left + r.width / 2, r.top + r.height * %s]) })()"
        % (col_i, hour, "0.75" if half else "0.25")))
    src = json.loads(page.js(
        "(() => { const b = document.querySelector('.gridbody [data-appt=\"%d\"]');"
        " const r = b.getBoundingClientRect();"
        " return JSON.stringify([r.left + r.width / 2, r.top + 6]) })()" % appt))
    tx, ty = xy
    sx, sy = src
    m = page.cdp.cmd
    try:
        m("Input.setInterceptDrags", enabled=True)
        m("Input.dispatchMouseEvent", type="mouseMoved", x=sx, y=sy)
        m("Input.dispatchMouseEvent", type="mousePressed", x=sx, y=sy,
          button="left", clickCount=1)
        m("Input.dispatchMouseEvent", type="mouseMoved", x=sx, y=sy + 12,
          button="left", buttons=1)
        m("Input.dispatchMouseEvent", type="mouseMoved", x=tx, y=ty,
          button="left", buttons=1)
        data = None
        for e in list(page.cdp.events):
            if e.get("method") == "Input.dragIntercepted":
                data = e["params"]["data"]
        if data is None and page.cdp.wait_event("Input.dragIntercepted", timeout=2.0):
            for e in list(page.cdp.events):
                if e.get("method") == "Input.dragIntercepted":
                    data = e["params"]["data"]
        if data is not None:
            for t in ("dragEnter", "dragOver", "drop"):
                m("Input.dispatchDragEvent", type=t, x=tx, y=ty, data=data)
            m("Input.dispatchMouseEvent", type="mouseReleased", x=tx, y=ty,
              button="left", clickCount=1)
            m("Input.setInterceptDrags", enabled=False)
            page.cdp.drain(0.5)
            return "браузерный"
        m("Input.dispatchMouseEvent", type="mouseReleased", x=tx, y=ty,
          button="left", clickCount=1)
        m("Input.setInterceptDrags", enabled=False)
    except RuntimeError as e:
        print(f"    ⚠️  Input.dispatchDragEvent недоступен ({e}); собираем событие в странице")
    page.js(
        "(() => { const b = document.querySelector('.gridbody [data-appt=\"%d\"]');"
        " const col = document.querySelectorAll('.gridbody .gcol')[%d];"
        " const dt = new DataTransfer();"
        " const mk = (t, y) => new DragEvent(t, {bubbles: true, cancelable: true,"
        "   clientX: %f, clientY: y, dataTransfer: dt});"
        " b.dispatchEvent(mk('dragstart', %f));"
        " col.dispatchEvent(mk('dragover', %f));"
        " col.dispatchEvent(mk('drop', %f));"
        " b.dispatchEvent(mk('dragend', %f)); return 1 })()"
        % (appt, col_i, tx, sy, ty, ty, ty))
    page.cdp.drain(0.4)
    return "страничный"


def run(out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    results = []

    def scene(page, name, expect, extra=""):
        st = json.loads(page.js(CHECK_JS))
        fails = []
        for k, v in expect.items():
            if st.get(k) != v:
                fails.append(f"{k}: ожидалось {v!r}, получено {st.get(k)!r}")
        fails += [f"consola: {e}" for e in page.cdp.errors()]
        if extra:
            fails.append(extra)
        page.size(st["w"], min(3200, st["h"] + 40))
        page.png(out / f"{name}.png")
        page.size(*WIDE)
        results.append((name, fails))
        print(("OK  " if not fails else "RED ") + f"{name}: appts={st['appts']} "
              f"nowlines={st['nowlines']} muts={st['muts']} "
              f"line={st['line_moves']}")
        for f in fails:
            print("    ", f)
        return st

    # ⚠️ День именно СЕГОДНЯШНИЙ: линия «сейчас» рисуется только на сегодня, а
    # без неё сцены 1 и 3 проверяли бы не свой предмет.
    day = clinic_today().isoformat()
    s1 = Server()
    s1._own_dir = False
    with s1:
        _seed(Client(s1.url).login(), day)
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["schedule_dash"]}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-dash-shots")
    s2 = Server(dir_=s1.dir)
    proc = proc_b = None
    try:
        with s2:
            origin = s2.url
            cookie = login_cookie(origin)
            # ⭐ ВТОРОЕ рабочее место: обычный HTTP-клиент, как соседний
            # компьютер регистратуры. Он и есть предмет главной сцены.
            other = Client(origin).login()

            proc, ws_url = start_edge(profile, port=PORT)
            cdp = CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=origin + "/")
            page = Page(cdp, origin)
            page.size(*WIDE)

            # --- 1. панель из одного конверта ---
            page.go(f"/admin?date={day}")
            cdp.drain(1.5)
            probe = json.loads(page.js(CHECK_JS))
            in_hours = bool(probe["hour_in_grid"])
            if not in_hours:
                print("⚠️  час вне графика клиники: проверки линии «сейчас» "
                      "пропущены (стенд запущен не в рабочее время)")
            line_n = 1 if in_hours else 0
            st = scene(page, "01_panel", {
                "react": True, "live_wrap": False, "nowlines": line_n,
                "agenda_count": "2 programări",
                "tiles": ["Programări", "Recepție", "Urgențe", "Neprezentări"],
            })
            base_geom = st["geom"]
            before = set(st["appts"])

            # --- 2. ⭐ второе рабочее место добавляет запись ---
            page.js(WATCH_JS)
            other.post("/admin/add", adate=day, atime="10:00", adoctor="d2",
                       aservice="consult", aname="Vasile Nou", aphone="069190192",
                       back=f"/admin?date={day}")
            t0 = time.time()
            while time.time() - t0 < TICK:
                cdp.drain(1.0)
                cur = json.loads(page.js(CHECK_JS))
                if len(cur["appts"]) > len(before):
                    break
            st = json.loads(page.js(CHECK_JS))
            fresh = [a for a in st["appts"] if a not in before]
            bad = ""
            if len(fresh) != 1 or "Vasile Nou" not in fresh[0]:
                bad = f"приехало не то: {fresh!r} (ждали одну «Vasile Nou»)"
            # ⛔ Геометрия СОСЕДЕЙ обязана остаться прежней: живое обновление —
            # это приезд записи, а не пересборка дня.
            moved = [k for k, v in base_geom.items()
                     if k in st["geom"] and st["geom"][k] != v]
            if moved:
                bad += f" · поехали соседи: {moved!r}"
            scene(page, "02_live_new", {"nowlines": line_n,
                                        "agenda_count": "3 programări"}, bad)

            # --- 3. неизменный день: ни одной мутации ---
            page.js("(() => { window.__dpMut = 0; window.__dpLine = 0; return 1 })()")
            was_quiet = json.loads(page.js(CHECK_JS))
            cdp.drain(QUIET)
            st = json.loads(page.js(CHECK_JS))
            quiet = ""
            if st["muts"]:
                # ⭐ Не «сколько», а ЧТО: за 95 секунд день меняется и
                # ЗАКОННО — сменился час клиники, пациент перешёл в прошлое.
                # Без этой строки сцена краснела бы «мигание вернулось» на
                # правильном поведении, и разбирать пришлось бы догадками
                # (наступило 20.09).
                diff = [k for k in ("appts", "geom", "agenda", "agenda_count",
                                    "tiles", "occ", "cols")
                        if was_quiet.get(k) != st.get(k)]
                quiet = (f"на неизменном дне {st['muts']} мутаций DOM — экран "
                         "подменяется на каждый опрос, мигание вернулось"
                         f" · изменилось: {diff or 'ничего из наблюдаемого'}")
            # ⭐ И обратная сторона: линия обязана ДВИГАТЬСЯ. Ноль здесь значит,
            # что экран замер, а «ноль мутаций» стало бы зелёным по неверной
            # причине — самая частая форма ложного зелёного в этом проекте.
            if in_hours and not st["line_moves"]:
                quiet += (" · линия «сейчас» не сдвинулась ни разу за "
                          f"{QUIET:.0f} с — экран замер")
            scene(page, "03_quiet", {"nowlines": line_n}, quiet)

            # --- 5. ⭐ ДВА БРАУЗЕРА: перенос у A приезжает к B (C26.5.3-g) ---
            # ⛔ Главная проверка ступени и единственная, которая смотрит на
            # ЦЕПОЧКУ целиком: команда → мутация → канал → второй экран. Ни
            # Vitest, ни питоновский прогон её не заменяют: первый не знает
            # геометрии, второй не знает браузера.
            proc_b, cdp_b, page_b = _second_browser(origin, cookie)
            page_b.size(*WIDE)
            page_b.go(f"/admin?date={day}")
            cdp_b.drain(1.0)
            aid = int(json.loads(page.js(
                "(() => { const b = [...document.querySelectorAll('.gridbody [data-appt]')]"
                ".find(x => (x.querySelector('b') || {}).textContent.includes('Ion Popa'));"
                " return JSON.stringify(b.getAttribute('data-appt')) })()")))
            was_a = json.loads(page.js(WHERE_JS % aid))
            was_b = json.loads(page_b.js(WHERE_JS % aid))
            how = _drag(page, aid, 0, 11, half=True)
            # ⛔ Диалог переноса обязателен: перетащить мышью легко случайно, а
            # визит — это человек, которому уже назвали время. Не открылся —
            # сцена КРАСНАЯ, а не падение стенда на исключении.
            has_dlg = page.js("!!document.querySelector('dialog .mv-act')")
            if has_dlg:
                page.click("document.querySelectorAll('dialog .mv-act button')[1]")
            # ⛔ Кадры СНИМАЮТСЯ подряд: запрещён не «неверный итог», а любой
            # кадр, в котором блок вернулся на докомандное место ПОСЛЕ того,
            # как он уже переехал. Ровно это ловит порядковый номер тика.
            frames, moved_at = [], None
            t0 = time.time()
            while time.time() - t0 < TICK + 4:
                cur = json.loads(page.js(WHERE_JS % aid))["top"]
                frames.append(cur)
                if moved_at is None and cur != was_a["top"]:
                    moved_at = time.time() - t0
                time.sleep(0.25)
            now_a = json.loads(page.js(WHERE_JS % aid))
            # B ничего не делал — он обязан УЗНАТЬ сам, в пределах одного опроса
            t0 = time.time()
            while time.time() - t0 < TICK:
                cdp_b.drain(1.0)
                now_b = json.loads(page_b.js(WHERE_JS % aid))
                if now_b["top"] != was_b["top"]:
                    break
            now_b = json.loads(page_b.js(WHERE_JS % aid))
            # ...и правда — у БАЗЫ
            row = next((r for r in json.loads(
                other.get(f"/api/schedule/day?date={day}").body)["data"]["list"]
                if r["id"] == aid), None)
            bad = f"перенос {how}"
            if not has_dlg:
                bad += " · диалог переноса НЕ открылся"
            if moved_at is None:
                bad += " · блок НЕ переехал у A вовсе"
            if now_a != now_b:
                bad += f" · A и B разошлись: {now_a!r} против {now_b!r}"
            if row is None or row["time"] != "11:30":
                bad += f" · база говорит другое: {row and row['time']!r}"
            # запрещённый кадр: старое место ПОСЛЕ нового
            after = frames[frames.index(now_a["top"]):] if now_a["top"] in frames else []
            if any(f == was_a["top"] for f in after):
                bad += " · был кадр с ДОКОМАНДНЫМ местом после переезда"
            cdp_b.drain(0.2)
            bad += "".join(f" · консоль B: {e}" for e in cdp_b.errors())
            scene(page, "05_two_clients", {"nowlines": line_n}, bad
                  if bad != f"перенос {how}" else "")
            print(f"    перенос {how}; A увидел новое место через "
                  f"{moved_at if moved_at is None else round(moved_at, 2)} с; "
                  f"кадров снято {len(frames)}")
            page_b.png(out / "05_two_clients_B.png")

            # --- 4. мгновенный откат ---
            page.go(f"/admin?date={day}&ui=legacy")
            cdp.drain(1.0)
            scene(page, "04_legacy", {"react": False, "live_wrap": True})
    finally:
        for p in (proc, proc_b):
            if p is not None:
                p.terminate()
        s1.__exit__(None, None, None)

    red = [n for n, f in results if f]
    print("\n" + "=" * 60)
    print(f"{len(results) - len(red)}/{len(results)} сцен зелёные · кадры в {out}")
    if red:
        print("красные: " + ", ".join(red))
    return 1 if red else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "dash"),
                    help="куда класть PNG")
    sys.exit(run(pathlib.Path(ap.parse_args().out)))
