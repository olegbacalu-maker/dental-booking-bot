# -*- coding: utf-8 -*-
"""Четыре последних экрана блока C в headless Edge: C9, C10, C15, C14+.

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не
ставить — это окружение сборки).

Запуск из app\\:   python scripts\\tail_shots.py [--out DIR]

Зачем отдельно от прогона. Прайор проекта назван опытом 21.09 — «видно только
живым запуском»: статика читает ИСХОДНИК, а дефект живёт в РЕЗУЛЬТАТЕ. Vitest
доказывает правило на jsdom, питоновский прогон — контракт сервера, и обе
поверхности зелены у экрана, который в настоящем браузере не смонтировался
вовсе: узел React пуст, а серверная заглушка «Interfața nouă nu s-a încărcat»
внутри него выглядит как обычный текст страницы.

Поэтому каждая сцена проверяет ДВЕ вещи: что заглушка ушла (бандл выполнился)
и что на экране стоят данные, которых в разметке сервера нет вовсе.

Сцены:
  1. `/admin/settings/crypt` — состояние «выключено», три абзаца цены и кнопка
     подготовки; ⭐ переход на ПЕЧАТНЫЙ лист остаётся серверной страницей;
  2. `/admin/settings/system` — версия, путь к папке данных и «Verifică acum»,
     который меняет строку НА МЕСТЕ (без перезагрузки страницы);
  3. `/admin/stats` — плитки, линия, кольцо, полукруг и деньги; ⭐ счётчик
     денег обязан ЗАКОНЧИТЬ на строке сервера, а `data-count` равен значению
     всегда;
  4. `/admin/doctor-card/{dk}` — кнопки исхода в сегодняшнем списке: клик
     меняет статус строки, и меняет его СЕРВЕР (проверяется третьим лицом —
     обычным HTTP-клиентом, как соседний компьютер регистратуры).

К каждой — PNG; красная проверка даёт код возврата 1, кадры остаются.
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
# ⛔ Свой порт отладки: 9337/9338/9339 заняты соседними стендами, и запуск на
# занятом молча подключился бы к ЧУЖОМУ браузеру.
PORT = 9340

FLAGS = ["settings_crypt", "settings_system", "stats", "doctor_card"]

# Смонтировался ли React вообще. ⛔ Мало проверить, что текст на месте: его
# может печатать сервер. Заглушка внутри узла — вот признак, что бандл НЕ
# выполнился, и она обязана исчезнуть.
MOUNT_JS = """(() => {
  const root = document.getElementById('root');
  return JSON.stringify({
    root: !!root,
    stub: !!(root && root.textContent.includes('Interfața nouă nu s-a încărcat')),
    react: !!document.querySelector('.dp-react-root'),
    live_wrap: !!document.getElementById('live'),
  });
})()"""


def _seed(c: Client, day: str) -> None:
    """Два визита сегодня у d2: одному экрану нужны цифры, другому — строки."""
    for hh, name, phone in (("09:00", "Coada Unu", "069000041"),
                            ("11:00", "Coada Doi", "069000042")):
        c.post("/admin/add", adate=day, atime=hh, adoctor="d2",
               aservice="consult", aname=name, aphone=phone, back="/admin/all")


def run(out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    results = []

    def scene(page, name, fails):
        fails = list(fails) + [f"consola: {e}" for e in page.cdp.errors()]
        st = json.loads(page.js(MOUNT_JS))
        if not st["react"] or st["stub"]:
            fails.append(f"React не смонтирован: {st}")
        if st["live_wrap"]:
            # ⛔ Правило карты: узел React никогда не внутри #live, иначе
            # panel.js подменит innerHTML под смонтированным деревом.
            fails.append("узел React внутри #live")
        page.png(out / f"{name}.png")
        results.append((name, fails))
        print(("OK  " if not fails else "RED ") + name)
        for f in fails:
            print("    ", f)

    day = clinic_today().isoformat()
    s1 = Server(keep_dir=True)
    with s1:
        _seed(Client(s1.url).login(), day)
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": FLAGS}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    profile = os.path.join(os.environ["TEMP"], "dp-edge-tail-shots")
    s2 = Server(dir_=s1.dir)
    proc = None
    try:
        with s2:
            origin = s2.url
            cookie = login_cookie(origin)
            other = Client(origin).login()      # третье лицо: сосед по сети

            proc, ws_url = start_edge(profile, port=PORT)
            cdp = CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie,
                    url=origin + "/")
            page = Page(cdp, origin)
            page.size(*WIDE)

            # --- 1. шифрование картотеки ---
            page.go("/admin/settings/crypt")
            cdp.drain(1.0)
            txt = page.js("document.querySelector('.dp-react-root').innerText")
            btn = page.js("!!Array.from(document.querySelectorAll('button'))"
                          ".find(b => b.textContent.includes('Pregătește criptarea'))")
            fails = []
            for need in ("Nu este obligatorie", "Ce face", "Ce cere în schimb",
                         "Ce NU face"):
                if need not in txt:
                    fails.append(f"нет абзаца «{need}»")
            if not btn:
                fails.append("нет кнопки подготовки")
            scene(page, "01_crypt", fails)

            # ⭐ Печатный лист — серверная страница и обязан открываться без
            # бандла: без кода с этой бумаги база не откроется после смены ПК.
            other.post_json("/api/settings/crypt/prepare", {})
            page.go("/admin/settings/crypt/sheet")
            cdp.drain(0.6)
            sheet = page.js("document.body.innerText")
            fails = []
            if "Foaie de recuperare" not in sheet:
                fails.append("лист не открылся")
            if page.js("!!document.getElementById('root')"):
                fails.append("лист отдан React — он обязан быть серверным")
            page.png(out / "01b_sheet.png")
            results.append(("01b_sheet", fails))
            print(("OK  " if not fails else "RED ") + "01b_sheet")
            for f in fails:
                print("    ", f)

            # --- 2. состояние системы ---
            page.go("/admin/settings/system")
            cdp.drain(1.0)
            txt = page.js("document.querySelector('.dp-react-root').innerText")
            fails = []
            for need in ("Versiune", "Bază de date", "Verifică acum",
                         "Confidențialitate", "funcționează local"):
                if need not in txt:
                    fails.append(f"нет строки «{need}»")
            # «Verifică acum» отвечает свежей моделью и меняет строку НА МЕСТЕ:
            # перезагрузки быть не должно — метим окно и смотрим, живо ли оно.
            page.js("window.__dp_mark = 1")
            page.click("Array.from(document.querySelectorAll('button'))"
                       ".find(b => b.textContent.includes('Verifică acum'))")
            cdp.drain(2.0)
            if page.js("window.__dp_mark") != 1:
                fails.append("страница перезагрузилась — состояние не в модели")
            scene(page, "02_system", fails)

            # --- 3. аналитика ---
            page.go("/admin/stats")
            cdp.drain(1.5)
            state = json.loads(page.js("""(() => JSON.stringify({
              tiles: document.querySelectorAll('.tiles .tile').length,
              line: !!document.querySelector('svg.linechart'),
              gauge: !!document.querySelector('svg.gauge'),
              sparks: document.querySelectorAll('svg.spark').length,
              money: Array.from(document.querySelectorAll('.an-money b[data-count]'))
                .map(b => b.getAttribute('data-count') + '|' + b.textContent),
              doctors: document.querySelectorAll('.an-tbl tr').length,
            }))()"""))
            fails = []
            if state["tiles"] != 4:
                fails.append(f"плиток {state['tiles']}, ждали 4 (бот заморожен)")
            if not state["line"]:
                fails.append("нет графика по дням")
            if not state["gauge"]:
                fails.append("нет полукруга загрузки")
            if state["sparks"] != state["tiles"]:
                fails.append(f"спарклайнов {state['sparks']} на {state['tiles']} плиток")
            if len(state["money"]) != 3:
                fails.append(f"денежных карточек {len(state['money'])}, ждали 3")
            # ⛔ Счётчик — представление: он обязан ЗАКОНЧИТЬ на значении, а
            # `data-count` равен ему всегда. Разойдись они — анимация стала бы
            # источником правды.
            for pair in state["money"]:
                num, shown = pair.split("|", 1)
                digits = "".join(ch for ch in shown if ch.isdigit())
                if digits != num:
                    fails.append(f"счётчик не сошёлся: data-count={num}, на экране «{shown}»")
            scene(page, "03_stats", fails)

            # --- 4. кнопки исхода в фише врача ---
            page.go("/admin/doctor-card/d2")
            cdp.drain(1.2)
            rows = json.loads(page.js("""(() => JSON.stringify(
              Array.from(document.querySelectorAll('.fcol-c table.list tbody tr'))
                .map(tr => ({
                  cls: tr.className,
                  status: (tr.querySelector('.stat') || {}).textContent,
                  acts: Array.from(tr.querySelectorAll('td:last-child button'))
                    .map(b => b.textContent.trim()),
                }))))()"""))
            fails = []
            if len(rows) != 2:
                fails.append(f"строк {len(rows)}, ждали 2")
            if not rows or "A venit" not in (rows[0]["acts"] or []):
                fails.append(f"нет кнопок исхода: {rows[:1]}")
            page.click("Array.from(document.querySelectorAll("
                       "'.fcol-c table.list tbody tr td:last-child button'))"
                       ".find(b => b.textContent.trim() === 'A venit')")
            cdp.drain(2.0)
            after = page.js("document.querySelector('.fcol-c table.list tbody tr .stat')"
                            ".textContent")
            # ⚠️ Слово именно «a venit» (STATUS_LABEL["waiting"]), а не
            # «în așteptare»: конвейер приёма называет приход так с 08-13, и
            # проверка, ждущая другого слова, краснела бы на правильном экране.
            if "a venit" not in (after or ""):
                fails.append(f"строка не сменила статус: «{after}»")
            # ⭐ И это СЕРВЕР, а не локальный мир экрана: спрашиваем третье лицо.
            seen = [r["status"] for r in json.loads(
                other.get("/api/doctors/d2").body)["data"]["today"]]
            if "waiting" not in seen:
                fails.append(f"сервер не знает об исходе: {seen}")
            scene(page, "04_doctor_card", fails)
    finally:
        if proc:
            proc.kill()
        s1.drop()

    bad = [n for n, f in results if f]
    print(f"\n{len(results) - len(bad)}/{len(results)} сцен прошло; кадры: {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "tail"),
                    help="куда класть PNG")
    sys.exit(run(pathlib.Path(ap.parse_args().out)))
