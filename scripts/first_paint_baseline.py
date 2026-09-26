# -*- coding: utf-8 -*-
"""Базовая линия первого кадра ДО B1 — один замер, не система проверок.

⛔ Не в CI и не в `.\\dev test`: нужен Edge. Запуск из app\\:

    python scripts\\first_paint_baseline.py [--out FILE]

⭐ Зачем именно СЕЙЧАС. «До» существует ровно до первого коммита B1: как только
оболочка переедет в React, восстановить сегодняшнюю последовательность кадров
будет нечем. Это единственный скоропортящийся артефакт этапа.

Что доказывается (а не просто записывается): сегодняшний код действительно
показывает ту причинную цепочку, которую B1 обязан устранить —

    загрузка документа → каркас с ПУСТЫМ #root и заглушкой → монтирование React
    → данные из /api → изменение высоты содержимого → сдвиг раскладки

⚠️ Замер снимается ДО `load`, а не после: сэмплер вставляется через
`Page.addScriptToEvaluateOnNewDocument`, то есть исполняется раньше любого
скрипта страницы. Замер после `loadEventFired` (как в соседних сценах) первый
кадр не видит вовсе и показал бы ровное «всё уже на месте» — ложное зелёное.
"""
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

from odo_shots import CDP, Page, login_cookie, start_edge  # noqa: E402
from harness import Client, Server, clinic_today  # noqa: E402

WIDE = (1500, 950)
# ⛔ Свой порт отладки: 9337-9340 заняты соседними стендами, и запуск на занятом
# молча подключился бы к ЧУЖОМУ браузеру.
PORT = 9341

# Сэмплер. Ставится ДО скриптов страницы и пишет два ряда:
#   marks   — когда впервые появился каждый узел цепочки;
#   samples — геометрия документа, только когда она ИЗМЕНИЛАСЬ.
# ⚠️ Правый край шапки берётся у `.who` (чип вошедшего) — это самый правый
# элемент верхней панели, и именно он уезжает на 15 px, когда появляется полоса
# прокрутки. Если чипа нет (облако без учёток), берётся сама `.top`.
PROBE = """
(() => {
  const D = { marks: [], samples: [], seen: {} };
  window.__dp = D;
  const now = () => Math.round(performance.now());
  const mark = (n) => { if (!D.seen[n]) { D.seen[n] = 1; D.marks.push([n, now()]); } };

  document.addEventListener('DOMContentLoaded', () => mark('dom_ready'));
  window.addEventListener('load', () => mark('load'));

  const look = () => {
    if (document.querySelector('aside.side')) mark('shell');
    const root = document.getElementById('root');
    if (root) {
      mark('root_node');
      if (root.querySelector('.hint')) mark('stub_visible');
      if (root.children.length === 0) mark('stub_cleared');
    }
    if (document.querySelector('.dp-react-root')) mark('react_mount');
    if (document.querySelector('.dp-react-root [aria-busy="false"], .fcard, .tiles, table.list'))
      mark('screen_content');
  };
  const anchor = () => document.querySelector('.who') || document.querySelector('.top');
  const frame = () => {
    const de = document.documentElement;
    if (!de) { requestAnimationFrame(frame); return; }
    look();
    const a = anchor();
    const s = { t: now(), h: de.scrollHeight, vw: de.clientWidth,
                x: a ? Math.round(a.getBoundingClientRect().right) : null };
    const p = D.samples[D.samples.length - 1];
    if (!p || p.h !== s.h || p.x !== s.x || p.vw !== s.vw) D.samples.push(s);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);

  /* ⚠️ Наблюдатель — ПОСЛЕ сэмплера и в try. Скрипт исполняется раньше разбора
     документа, и `document.documentElement` тогда ещё null: `observe` на нём
     бросает, а брошенное исключение убивало весь замер — оставались только две
     метки от слушателей, зарегистрированных выше. Цель — `document`. */
  try {
    new MutationObserver(look).observe(document, { childList: true, subtree: true });
  } catch (e) { D.marks.push(['observer_failed', 0]); }
  look();
})()
"""

COLLECT = """(() => {
  const D = window.__dp || { marks: [], samples: [] };
  const paint = {};
  for (const e of performance.getEntriesByType('paint')) paint[e.name] = Math.round(e.startTime);
  const res = {};
  for (const e of performance.getEntriesByType('resource')) {
    const m = /\\/static\\/(js|css)\\/(bundle|panel)\\.(js|css)/.exec(e.name);
    if (m) res[m[2] + '.' + m[3]] = { start: Math.round(e.startTime),
                                      end: Math.round(e.responseEnd),
                                      kb: Math.round((e.transferSize || 0) / 1024) };
  }
  const nav = performance.getEntriesByType('navigation')[0] || {};
  return JSON.stringify({
    marks: D.marks, samples: D.samples, paint, res,
    nav: { dom: Math.round(nav.domContentLoadedEventEnd || 0),
           load: Math.round(nav.loadEventEnd || 0) },
  });
})()"""


def _seed(c: Client, day: str) -> None:
    for hh, name, phone in (("09:00", "Baza Unu", "069000051"),
                            ("10:00", "Baza Doi", "069000052"),
                            ("11:00", "Baza Trei", "069000053")):
        c.post("/admin/add", adate=day, atime=hh, adoctor="d2",
               aservice="consult", aname=name, aphone=phone, back="/admin/all")


def measure(page: Page, cdp: CDP, path: str, settle: float = 6.0) -> dict:
    """Один адрес: перейти и дать странице отстояться, потом собрать ряды."""
    page.go(path)
    time.sleep(settle)
    cdp.drain(0.3)
    data = json.loads(page.js(COLLECT))
    data["path"] = path
    return data


def report(m: dict) -> list:
    """Читаемая сводка и — главное — вывод, видна ли причинная цепочка."""
    out = []
    marks = dict(m["marks"])
    order = ["shell", "stub_visible", "root_node", "stub_cleared", "react_mount",
             "screen_content", "dom_ready", "load"]
    out.append(f"  цепочка: " + " → ".join(
        f"{k} {marks[k]}мс" for k in order if k in marks))
    fp = m["paint"].get("first-contentful-paint")
    if fp is not None:
        out.append(f"  первый содержательный кадр: {fp} мс")
    b = m["res"].get("bundle.js")
    if b:
        out.append(f"  bundle.js: запрошен на {b['start']} мс, получен на "
                   f"{b['end']} мс, {b['kb']} КБ по сети")
    s = m["samples"]
    if s:
        hs = [x["h"] for x in s]
        xs = [x["x"] for x in s if x["x"] is not None]
        out.append(f"  высота документа: {hs[0]} → {hs[-1]} px, "
                   f"изменений {len(set(hs))}")
        if xs:
            out.append(f"  правый край шапки: {xs[0]} → {xs[-1]} px, "
                       f"сдвиг {xs[-1] - xs[0]:+d} px, изменений {len(set(xs))}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "baseline.json"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    day = clinic_today().isoformat()
    s1 = Server(keep_dir=True)
    with s1:
        _seed(Client(s1.url).login(), day)
    # ⛔ Харнесс пинит `ui.react = []` во ВСЕХ фикстурах (harness._pin_legacy):
    # почти каждый набор разбирает старую разметку как эталон. Без явного
    # включения замер снял бы ЛЕГАСИ-страницы — без узла #root вовсе, то есть
    # доказывал бы отсутствие дефекта, которого на той поверхности и нет.
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    # ⚠️ Список обязан покрывать ВСЕ замеряемые адреса. Пропущенный
    # `doctors_list` отдавал `/admin/medici` старой страницей, и замер честно
    # показывал серверный каркас на 59 мс без единого узла React — выглядело
    # как дефект стенда, а было дефектом списка.
    cfg["ui"] = {"react": ["schedule_dash", "patients_search", "stats",
                           "doctors_list", "settings_hub", "doctor_card",
                           "schedule_week", "schedule_all", "schedule_doctor"]}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-baseline")
    s2 = Server(dir_=s1.dir)
    proc = None
    runs = []
    try:
        with s2:
            cookie = login_cookie(s2.url)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network"):
                cdp.cmd(f"{dom}.enable")
            # ⛔ Кеш ВЫКЛЮЧЕН, и это не мелочь. Без этого второй и следующие
            # адреса берут bundle.js из памяти браузера, React монтируется до
            # первого кадра сэмплера, и метки `root_node` / `stub_visible`
            # пропадают вовсе — страница выглядит здоровой, потому что замер
            # опоздал. Поймано на `/admin/medici`: тёплый прогон дал «каркас на
            # 58 мс», холодный — честные 205. Пара «до/после» без этого
            # сравнивает не код, а прогретость профиля.
            cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie,
                    url=s2.url + "/")
            # ⛔ Сэмплер обязан стоять ДО скриптов страницы, иначе первый кадр
            # уже прошёл и замер покажет ровное «всё на месте».
            cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=PROBE)
            page = Page(cdp, s2.url)
            page.size(*WIDE)

            # ⚠️ `/admin/medici` добавлен ПОСЛЕ снятия базовой линии: его «до»
            # потеряно, потому что первую вертикаль B1 я включил именно на нём,
            # а в набор адресов его не внёс. Прайор на будущее: замерять надо
            # ТОТ адрес, который собираешься тронуть первым.
            # ⭐ Правило Олега 24.09: адрес сначала попадает в набор замера,
            # и только ПОТОМ его оболочка переносится. `/admin/medici` этому
            # правилу не подчинился и своё «до» потерял — второй раз не надо.
            for path in ("/admin", "/admin/search", "/admin/stats",
                         "/admin/medici", "/admin/settings",
                         "/admin/doctor-card/d2",
                         "/admin/week", "/admin/all", "/admin/doctor/d2"):
                m = measure(page, cdp, path)
                runs.append(m)
                print(f"\n{path}")
                for line in report(m):
                    print(line)
    finally:
        if proc:
            proc.kill()
        s1.drop()

    out.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nряды сохранены: {out}")

    # ⭐ Главное утверждение стенда: цепочка видна, а не просто числа записаны.
    bad = []
    grew = []
    for m in runs:
        mk = dict(m["marks"])
        for need in ("shell", "root_node", "stub_visible", "stub_cleared", "react_mount"):
            if need not in mk:
                bad.append(f"{m['path']}: нет метки {need}")
        if "react_mount" in mk and "shell" in mk and mk["react_mount"] < mk["shell"]:
            bad.append(f"{m['path']}: React смонтирован РАНЬШЕ каркаса — замер врёт")
        hs = [x["h"] for x in m["samples"]]
        if len(set(hs)) > 1:
            grew.append(f"{m['path']} ({hs[0]}→{hs[-1]})")
    # ⚠️ Рост документа требуется НЕ от каждого экрана: список пациентов в
    # песочнице умещается в окно, и требовать роста от него значило бы красить
    # стенд на правильном поведении. Дефект доказан, если он виден ХОТЬ ГДЕ-ТО.
    if not grew:
        bad.append("ни на одном адресе документ не вырос — дефект не пойман")
    print()
    for b in bad:
        print("  ✗ " + b)
    if grew:
        print("  документ вырастает после прихода данных: " + ", ".join(grew))
    print("цепочка видна на всех адресах" if not bad
          else f"не доказано на {len(bad)} утверждениях")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
