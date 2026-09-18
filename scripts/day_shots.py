# -*- coding: utf-8 -*-
"""Сцены React-дня в headless Edge: запись, карточка и НАСТОЯЩЕЕ перетаскивание (C25.5b).

⛔ Не в CI и не в `.\\dev test`: нужны Edge и пакет websocket-client в
СИСТЕМНОМ Python (в .venv-desktop ничего не ставить — это окружение сборки).

Запуск из app\\:   python scripts\\day_shots.py [--out DIR]

Зачем отдельно от прогона. Перетаскивание — единственная часть договора,
которую НЕ ПРОВЕРИТЬ ни HTTP-запросом, ни jsdom: там нет ни `DragEvent`, ни
прямоугольников элементов, и половина часа (верх ячейки — :00, низ — :30)
считается ровно по ним. Проверки клиента доказывают правило, этот стенд —
что браузер действительно его исполняет: бросок идёт через
`Input.setInterceptDrags` + `Input.dispatchDragEvent`, то есть настоящим
перетаскиванием, а не `dispatchEvent` из скрипта.

Сцены: день с записями, диалог «+», добавленная запись, карточка визита с
ПОЛНЫМ комментарием, диалог переноса после броска в нижнюю половину часа,
переехавшая запись, убранная из списка заметка стойки и отбор плитки, при
котором список сужается, а сетка остаётся целой. К каждой — PNG и проверки; красная проверка даёт код
возврата 1, кадры остаются, чтобы посмотреть глазами.
"""
import argparse
import json
import os
import pathlib
import shutil
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

LONG_CMT = ("Alergie la penicilină; de sunat cu o zi înainte; vine cu mama; "
            "preferă dimineața")

CHECK_JS = """(() => {
  const at = (e) => {
    const tr = e.closest('tr'), td = e.closest('td');
    return tr.querySelector('.hour').textContent.slice(0, 5) + '|'
      + Array.from(tr.children).indexOf(td);
  };
  const dlg = document.querySelector('dialog[open]');
  const cards = Array.from(document.querySelectorAll('.grid [data-appt]'));
  const mv = document.querySelectorAll('.mv-rows b');
  return JSON.stringify({
    rows: document.querySelectorAll('tr.hrow').length,
    cols: Array.from(document.querySelectorAll('.dh-n')).map(x => x.textContent),
    appts: cards.map(e => e.getAttribute('data-appt') + '@' + at(e)),
    drag: cards.filter(e => e.getAttribute('draggable') === 'true').length,
    dlg: dlg ? (dlg.querySelector('.dlg-head span') || {}).textContent || '' : null,
    list: Array.from(document.querySelectorAll('table.list tr')).slice(1)
      .map(r => r.className + ':' + (r.children[0] || {}).textContent),
    filter: (document.querySelector('.banner.ok') || {}).textContent || null,
    mv_from: mv[1] ? mv[1].textContent : null,
    mv_to: mv[2] ? mv[2].textContent : null,
    warn: (document.querySelector('dialog[open] .banner.err') || {}).textContent || null,
    cmt: dlg && dlg.querySelector('textarea') ? dlg.querySelector('textarea').value : null,
    toast: (document.querySelector('.toastbox') || {}).textContent || null,
    form: !!document.querySelector('form.add'),
    w: document.documentElement.clientWidth,
    h: document.body.scrollHeight,
    fails: [],
  });
})()"""

FREE = ("Array.from(document.querySelectorAll('tr.hrow'))"
        ".find(r => r.querySelector('.hour').textContent.indexOf('{hh}') === 0)"
        ".children[{col}].querySelector('.free')")
CELL = ("Array.from(document.querySelectorAll('tr.hrow'))"
        ".find(r => r.querySelector('.hour').textContent.indexOf('{hh}') === 0)"
        ".children[{col}]")
CARD = "document.querySelector('.grid [data-appt=\"{aid}\"]')"
BY_TEXT = "Array.from(document.querySelectorAll('{sel}')).find(b => b.textContent.includes('{text}'))"
# кнопка «Șterge» у строки-заметки: единственный способ убрать блокировку слота
NOTE_BTN = ("Array.from(document.querySelectorAll('table.list tr'))"
            ".map(r => r.querySelector('button.b-cancel'))"
            ".filter(Boolean).slice(-1)[0]")


def _seed(c: Client, day: str) -> dict:
    """День с двумя записями, заметкой стойки и длинным комментарием."""
    c.post("/admin/add", adate=day, atime="09:00", adoctor="d2", aservice="consult",
           aname="Ion Popa", aphone="069170170", back=f"/admin/all?date={day}")
    c.post("/admin/add", adate=day, atime="12:00", adoctor="d3", aservice="consult",
           aname="Maria Rusu", aphone="069170171", back=f"/admin/all?date={day}")
    # заметка стойки: её удаление живёт ТОЛЬКО в списке дня — ради этой сцены
    c.post("/admin/note", ndate=day, ntime="15:00", ndoctor="d2",
           ntext="Livrare materiale", back=f"/admin/all?date={day}")
    ids = []
    body = c.get(f"/admin/all?date={day}").body
    import re
    ids = re.findall(r"<tr class='[a-z]+'><td>(\d+)</td>", body)
    c.post(f"/admin/comment/{ids[0]}", comment=LONG_CMT, back=f"/admin/all?date={day}")
    return {"ids": ids}


def point(page: Page, finder: str, frac: float):
    """Точка внутри элемента: доля его высоты (0.25 — верх, 0.75 — низ)."""
    v = page.js(f"(() => {{ const el = {finder}; if (!el) return null;"
                f" const r = el.getBoundingClientRect();"
                f" return JSON.stringify([r.left + r.width / 2, r.top + r.height * {frac}]) }})()")
    if v is None:
        raise RuntimeError(f"нет элемента: {finder}")
    return json.loads(v)


def take(cdp: CDP, name: str):
    """Вынуть событие из собранных (и убрать, чтобы не мешало следующему)."""
    for i, e in enumerate(cdp.events):
        if e.get("method") == name:
            return cdp.events.pop(i)["params"]
    return None


def drag(page: Page, src: str, dst: str, frac: float) -> str:
    """НАСТОЯЩЕЕ перетаскивание: браузер сам начинает его от нажатой кнопки, а
    события бросания шлёт CDP с тем же грузом (`Input.dragIntercepted`).

    ⚠️ Без `setInterceptDrags` headless-браузер перетаскивание НЕ доводит:
    мышиные события начинают drag, но `drop` до страницы не доходит, и сцена
    зеленела бы на пустом месте.
    """
    cdp = page.cdp
    cdp.cmd("Input.setInterceptDrags", enabled=True)
    x0, y0 = page.center(src)
    x1, y1 = point(page, dst, frac)
    cdp.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x0, y=y0)
    cdp.cmd("Input.dispatchMouseEvent", type="mousePressed", x=x0, y=y0,
            button="left", buttons=1, clickCount=1)
    data = None
    for step in (6, 18, 42, 80):
        cdp.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x0, y=y0 + step,
                button="left", buttons=1)
        cdp.drain(0.25)
        ev = take(cdp, "Input.dragIntercepted")
        if ev:
            data = ev["data"]
            break
    if data is None:
        cdp.cmd("Input.dispatchMouseEvent", type="mouseReleased", x=x0, y=y0,
                button="left", clickCount=1)
        cdp.cmd("Input.setInterceptDrags", enabled=False)
        return "браузер не начал перетаскивание (нет Input.dragIntercepted)"
    for kind in ("dragEnter", "dragOver"):
        cdp.cmd("Input.dispatchDragEvent", type=kind, x=x1, y=y1, data=data)
    cdp.drain(0.2)
    cdp.cmd("Input.dispatchDragEvent", type="drop", x=x1, y=y1, data=data)
    cdp.cmd("Input.dispatchMouseEvent", type="mouseReleased", x=x1, y=y1,
            button="left", clickCount=1)
    cdp.cmd("Input.setInterceptDrags", enabled=False)
    cdp.drain(0.6)
    return ""


def click_below(page: Page, finder: str) -> None:
    """Клик по тому, что лежит НИЖЕ СГИБА.

    ⚠️ CDP шлёт мышь в координатах ОКНА, а `getBoundingClientRect` у элемента
    за нижней границей даёт y больше высоты окна: клик уходит в пустоту, и
    сцена краснеет «ничего не произошло». Список дня как раз там — под сеткой
    и формой. Поэтому сперва подводим элемент к середине экрана.
    """
    page.js(f"(() => {{ const el = {finder};"
            f" if (el) el.scrollIntoView({{block: 'center'}}); return 1 }})()")
    page.cdp.drain(0.3)
    page.click(finder)


def type_into(page: Page, finder: str, text: str) -> None:
    page.click(finder)
    page.cdp.cmd("Input.insertText", text=text)
    page.cdp.drain(0.2)


def run(out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    results = []

    def scene(page, name, expect, note=""):
        st = json.loads(page.js(CHECK_JS))
        fails = list(st["fails"])
        for k, v in expect.items():
            if st.get(k) != v:
                fails.append(f"{k}: ожидалось {v!r}, получено {st.get(k)!r}")
        fails += [f"consola: {e}" for e in page.cdp.errors()]
        if note:
            fails.append(note)
        page.size(st["w"], min(3200, st["h"] + 40))
        page.png(out / f"{name}.png")
        page.size(*WIDE)
        results.append((name, fails))
        print(("OK  " if not fails else "RED ") + f"{name}: appts={st['appts']} "
              f"drag={st['drag']} dlg={st['dlg']!r}")
        for f in fails:
            print("    ", f)

    day = (clinic_today() + timedelta(days=3)).isoformat()
    s1 = Server()
    s1._own_dir = False
    with s1:
        ids = _seed(Client(s1.url).login(), day)["ids"]
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["schedule_all", "schedule_doctor"]}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    profile = os.path.join(os.environ["TEMP"], "dp-edge-day-shots")
    s2 = Server(dir_=s1.dir)
    proc = None
    try:
        with s2:
            origin = s2.url
            cookie = login_cookie(origin)
            proc, ws_url = start_edge(profile)
            cdp = CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=origin + "/")
            page = Page(cdp, origin)
            page.size(*WIDE)
            path = f"/admin/all?date={day}"

            # 1. день целиком: сетка, форма, две записи, обе тащатся
            page.go(path)
            # заметка стойки тоже тащится (её блок живёт в сетке), поэтому
            # перетаскиваемых три, а не две
            scene(page, "01_day", {"form": True, "drag": 3,
                                   "appts": [f"{ids[0]}@09:00|1", f"{ids[1]}@12:00|2",
                                             f"{ids[2]}@15:00|1"]})

            # 2. «+» открывает диалог на своей ячейке
            page.click(FREE.format(hh="10:00", col=1))
            scene(page, "02_slot", {"dlg": "Dr. Activ Doi — 10:00"})

            # 3. запись из диалога: настоящие клики и настоящий ввод
            type_into(page, "document.querySelector('dialog[open] input[placeholder=\"Nume pacient\"]')",
                      "Vasile Lupu")
            type_into(page, "document.querySelector('dialog[open] input[placeholder=\"Telefon\"]')",
                      "069112233")
            page.click(BY_TEXT.format(sel="dialog[open] .dlg-form button", text="Adaugă programarea"))
            cdp.drain(1.0)
            st = json.loads(page.js(CHECK_JS))
            scene(page, "03_added", {"dlg": None},
                  note="" if any("@10:00|1" in a for a in st["appts"])
                  else f"новой записи в 10:00 нет: {st['appts']}")
            if not st["toast"]:
                results[-1][1].append("после записи нет плашки сервера")

            # 4. карточка визита: комментарий ПОЛНЫЙ, а не обрезанный сеткой
            page.click(CARD.format(aid=ids[0]))
            scene(page, "04_card", {"cmt": LONG_CMT})
            page.click("document.querySelector('dialog[open] .dlg-head button')")
            cdp.drain(0.3)

            # 5. НАСТОЯЩЕЕ перетаскивание в НИЖНЮЮ половину часа → 11:30
            why = drag(page, CARD.format(aid=ids[0]), CELL.format(hh="11:00", col=1), 0.75)
            scene(page, "05_move_dialog",
                  {"mv_from": "Dr. Activ Doi · 09:00", "mv_to": "Dr. Activ Doi · 11:30",
                   "warn": None}, note=why)

            # 6. подтверждение: запись стоит на новом месте
            page.click(BY_TEXT.format(sel="dialog[open] .mv-act button", text="Da, mută"))
            cdp.drain(1.2)
            st = json.loads(page.js(CHECK_JS))
            scene(page, "06_moved", {"dlg": None},
                  note="" if any(a.startswith(f"{ids[0]}@11:00") for a in st["appts"])
                  else f"запись не переехала: {st['appts']}")

            # 7. СПИСОК ДНЯ (C25.5c): заметку убирают отсюда — больше ниоткуда,
            # карточки визита у неё нет по замыслу
            click_below(page, NOTE_BTN)
            cdp.drain(1.2)
            st = json.loads(page.js(CHECK_JS))
            scene(page, "07_note_removed", {"dlg": None},
                  note="" if any(x.startswith("cancelled:") for x in st["list"])
                  else f"заметка не убрана: {st['list']}")

            # 8. плитка панели дня: список сужается, сетка остаётся целой
            grid_before = len(st["appts"])
            page.go(f"/admin/all?date={day}&f=urg")
            st = json.loads(page.js(CHECK_JS))
            scene(page, "08_filtered", {},
                  note="" if (st["filter"] and "urgențe" in st["filter"]
                              and len(st["appts"]) == grid_before)
                  else f"фильтр: {st['filter']!r}, записей в сетке "
                       f"{len(st['appts'])} против {grid_before}")
    finally:
        if proc:
            proc.kill()
        time.sleep(0.5)
        shutil.rmtree(s1.dir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)

    red = [(n, f) for n, f in results if f]
    print()
    print(f"сцен: {len(results)}, красных: {len(red)} → {out}")
    return 1 if red else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "day"), help="куда класть PNG")
    args = ap.parse_args()
    sys.exit(run(pathlib.Path(args.out)))


if __name__ == "__main__":
    main()
