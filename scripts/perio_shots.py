# -*- coding: utf-8 -*-
"""Кадры React-пародонтограммы в headless Edge с проверкой геометрии (C23).

⛔ Не в CI и не в `.\\dev test`: нужны Edge и пакет websocket-client в
СИСТЕМНОМ Python (в .venv-desktop ничего не ставить — это окружение сборки).
Механика общая с одонтограммой и берётся оттуда: `odo_shots.CDP`, `Page`,
`login_cookie`, `start_edge`. Пациент — `test_perio_api._seed`, флаг `perio`
кладётся в clinic.json песочницы.

Запуск из app\\:   python scripts\\perio_shots.py [--out DIR]

Сцены: лист осмотра, диктовка (цифра уходит сама), кровоточивость клавишей
«b», глубокий карман, черновик и пересчитанный итог, отказ от черновика,
запись осмотра, новый осмотр и возврат к прошлому, узкие окна. К каждой —
PNG и проверки того, что на листе с 384 полями ломается молча: тридцать две
колонки по двенадцать точек, шесть точек кровоточивости РОВНО у глубины,
номер и рисунок внутри своей колонки, сводка не накрывает лист, страница не
едет вбок (прокрутка живёт внутри `.pscroll`, это не одно и то же), консоль
чиста. Красная проверка — код возврата 1; кадры остаются посмотреть глазами.
"""
import argparse
import json
import os
import pathlib
import shutil
import sys

# Консоль Windows живёт в cp1251, а отчёт печатает «→» и русские слова:
# без этого прогон падал бы UnicodeEncodeError на последней строке.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import Client, Server  # noqa: E402
from test_perio_api import _seed  # noqa: E402
import odo_shots as odo  # noqa: E402

WIDE = (1700, 1000)
PORT = 9338

# Проверки листа — одна функция на все сцены, возвращает JSON.
CHECK_JS = r"""
(() => {
  const R = (el) => { const r = el.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height} }
  const out = { fails: [] }
  let cols = 0, cells = 0, dots = 0, pics = 0
  for (const arch of document.querySelectorAll('.perio .parch')) {
    let prev = null
    for (const col of arch.querySelectorAll('.ptooth')) {
      cols++
      const n = col.dataset.tooth
      const rc = R(col)
      const inputs = col.querySelectorAll('.pcell input[data-k]')
      if (inputs.length !== 12) out.fails.push('puncte ' + n + ': ' + inputs.length)
      cells += inputs.length
      const d = col.querySelectorAll('.pdot')
      if (d.length !== 6) out.fails.push('sangerare ' + n + ': ' + d.length)
      if (col.querySelectorAll('.prow.rec .pdot').length) out.fails.push('sangerare la recesiune ' + n)
      dots += d.length
      const num = col.querySelector('.pnum')
      if (!num || num.textContent !== n) out.fails.push('numar ' + n)
      else { const rn = R(num); if (rn.l < rc.l - 1 || rn.r > rc.r + 1) out.fails.push('numar in afara ' + n) }
      const pic = col.querySelector('.ptpic svg')
      if (!pic) out.fails.push('dintele lipseste sub ' + n)
      else { pics++; const rp = R(pic); if (rp.l < rc.l - 1 || rp.r > rc.r + 1) out.fails.push('desenul iese din coloana ' + n) }
      // клетки колонки не наезжают друг на друга и не вылезают из неё
      for (const c of col.querySelectorAll('.pcell')) {
        const rr = R(c)
        if (rr.l < rc.l - 1 || rr.r > rc.r + 1) out.fails.push('celula in afara coloanei ' + n)
      }
      if (prev && rc.l < prev.r - 1) out.fails.push('suprapunere ' + n)
      prev = rc
    }
  }
  out.cols = cols; out.cells = cells; out.dots = dots; out.pics = pics
  // сводка справа или под листом, но не поверх
  const side = document.querySelector('.perio .pside'), grid = document.querySelector('.perio .pgrid')
  const main = grid ? grid.querySelector('.fcard') : null
  if (side && main) {
    const a = R(side), m = R(main)
    if (!(a.l >= m.r - 1 || a.r <= m.l + 1 || a.t >= m.b - 1 || a.b <= m.t + 1)) out.fails.push('rezultatul acopera foaia')
    out.side_right = a.l >= m.r - 1
    out.side_below = a.t >= m.b - 1
  }
  // страница вбок не едет; прокрутка дуги живёт ВНУТРИ .pscroll и это норма
  const de = document.documentElement
  if (de.scrollWidth > de.clientWidth + 1) out.fails.push('scroll orizontal la pagina')
  const perio = document.querySelector('.perio')
  if (perio && R(perio).r > window.innerWidth + 1) out.fails.push('.perio mai lat decat fereastra')
  out.arch_scroll = Array.from(document.querySelectorAll('.perio .pscroll'))
    .map(s => s.scrollWidth > s.clientWidth + 1)
  out.deep = Array.from(document.querySelectorAll('.perio .pcell.deep input')).map(
    i => i.dataset.n + ':' + i.dataset.k + i.dataset.i)
  out.bop = Array.from(document.querySelectorAll('.perio .pdot.on')).map(
    d => (d.closest('.ptooth') || {}).dataset.tooth + ':' + d.dataset.i)
  out.absent = Array.from(document.querySelectorAll('.perio .ptooth.absent')).map(c => c.dataset.tooth)
  out.sums = Array.from(document.querySelectorAll('.psum-i b')).map(b => b.textContent)
  out.unsaved = Boolean(document.querySelector('.dp-draft'))
  out.exam = (document.querySelector('.pexam') || {}).value || null
  out.exams = Array.from(document.querySelectorAll('.pexam option')).map(o => o.textContent)
  out.empty_btn = Boolean(Array.from(document.querySelectorAll('button')).find(
    b => b.textContent.includes('Șterge examenul gol')))
  out.start_btn = Boolean(Array.from(document.querySelectorAll('button')).find(
    b => b.textContent.includes('Începe primul examen')))
  const ae = document.activeElement
  out.focus = ae && ae.dataset && ae.dataset.k
    ? (ae.closest('.ptooth') || {}).dataset.tooth + ':' + ae.dataset.k + ae.dataset.i
    : (ae ? ae.tagName : null)
  out.value = (n, k, i) => null
  out.v16 = (() => { const el = document.querySelector('.ptooth[data-tooth="16"] input[data-k="pd"][data-i="0"]'); return el ? el.value : null })()
  out.v11 = (() => { const el = document.querySelector('.ptooth[data-tooth="11"] input[data-k="pd"][data-i="0"]'); return el ? el.value : null })()
  delete out.value
  out.toast = (document.querySelector('.toastbox') || {}).textContent || null
  out.w = window.innerWidth
  out.h = de.scrollHeight
  return JSON.stringify(out)
})()
"""

CELL = ("document.querySelector('.ptooth[data-tooth=\"{n}\"] "
        "input[data-k=\"{k}\"][data-i=\"{i}\"]')")
BY_TEXT = "Array.from(document.querySelectorAll('{sel}')).find(b => b.textContent.includes('{text}'))"


class PerioPage(odo.Page):
    def check(self):
        return json.loads(self.js(CHECK_JS))

    def type_at(self, finder, text):
        """Настоящий ввод: клик в поле, затем клавиши по одной — как диктуют."""
        self.click(finder)
        for ch in text:
            self.key(ch)


def run(out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    results = []

    def scene(page, name, expect, clip=None, full=True):
        st = page.check()
        fails = list(st["fails"])
        for k, v in expect.items():
            if st.get(k) != v:
                fails.append(f"{k}: ожидалось {v!r}, получено {st.get(k)!r}")
        fails += [f"consola: {e}" for e in page.cdp.errors()]
        if full and not clip:
            page.size(st["w"], min(3200, st["h"] + 40))
        page.png(out / f"{name}.png", clip=clip, full=full)
        if full and not clip:
            page.size(st["w"], WIDE[1] if st["w"] == WIDE[0] else 900)
        results.append((name, fails, st))
        print(f"{'OK ' if not fails else 'RED'} {name}: cols={st['cols']} cells={st['cells']} "
              f"dots={st['dots']} deep={len(st['deep'])} bop={st['bop']} sums={st['sums']} "
              f"focus={st['focus']} unsaved={st['unsaved']}")
        for f in fails:
            print("    ", f)

    s1 = Server()
    s1._own_dir = False
    with s1:
        c = Client(s1.url).login()
        d = _seed(c)
    cfg = json.loads(s1.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["perio"]}
    s1.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    profile = os.path.join(os.environ["TEMP"], "dp-edge-perio-shots")
    s2 = Server(dir_=s1.dir)
    proc = None
    try:
        with s2:
            origin = s2.url
            cookie = odo.login_cookie(origin)
            proc, ws_url = odo.start_edge(profile, PORT)
            cdp = odo.CDP(ws_url)
            for dom in ("Network", "Runtime", "Log", "Page"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCookie", name="admin_auth", value=cookie, url=origin + "/")
            page = PerioPage(cdp, origin)
            page.size(*WIDE)
            path = f"/admin/patient/{d['pid']}/parodontograma"

            # 1. лист осмотра: обе дуги, измерения, приглушённые отсутствующие
            page.go(path)
            scene(page, "01_sheet", {"cols": 32, "cells": 384, "dots": 192, "pics": 32,
                                     "absent": ["26", "38"], "unsaved": False,
                                     "side_right": True, "v16": "3"})
            # 2. глубокий карман и кровоточивость приехали с сервера
            scene(page, "02_deep", {"deep": ["16:pd3", "16:pd5"], "bop": ["16:1", "16:4"]})
            # 3. диктовка: «3» в пустую точку уходит к следующей сама
            page.type_at(CELL.format(n=11, k="pd", i=0), "3")
            scene(page, "03_dictation", {"v11": "3", "focus": "11:pd1", "unsaved": True})
            # 4. «1» ждёт вторую цифру — бывает 12 мм
            page.type_at(CELL.format(n=11, k="pd", i=1), "1")
            scene(page, "04_wait_second", {"focus": "11:pd1"})
            page.key("2")
            scene(page, "05_two_digits", {"focus": "11:pd2"})
            # 5. «b» ставит кровоточивость с того же места
            page.click(CELL.format(n=11, k="pd", i=0))
            page.key("b")
            scene(page, "06_bleeding", {"bop": ["16:1", "16:4", "11:0"]})
            # 6. итог пересчитан до записи
            st = page.check()
            if st["sums"][3] != "3":
                results[-1][1].append(f"итог не увидел новый зуб: {st['sums']}")
            # 7. отказ от черновика возвращает осмотр
            page.click(BY_TEXT.format(sel=".pfoot button", text="Renunță"))
            scene(page, "07_discarded", {"unsaved": False, "v11": "", "bop": ["16:1", "16:4"]})
            # 8. запись осмотра: плашка сервера, черновик снят
            page.type_at(CELL.format(n=11, k="pd", i=0), "5")
            page.click(BY_TEXT.format(sel=".pfoot button", text="Salvează examenul"))
            page.cdp.drain(1.5)
            scene(page, "08_saved", {"unsaved": False, "v11": "5"})
            if not page.check()["toast"]:
                results[-1][1].append("после записи нет плашки сервера")
            # 9. новый осмотр: лист пуст, прошлый в списке, пустой можно снять
            page.click(BY_TEXT.format(sel=".odo-actions button", text="Examen nou"))
            page.cdp.drain(1.2)
            st = page.check()
            scene(page, "09_new_exam", {"cols": 32, "v16": "", "v11": "", "empty_btn": True,
                                        "unsaved": False})
            if len(st["exams"]) != 2:
                results[-1][1].append(f"в списке не два осмотра: {st['exams']}")
            # 10. возврат к прошлому осмотру по выбору из списка
            prev_id = page.js("(() => { const s = document.querySelector('.pexam');"
                              " return s.options[s.options.length - 1].value })()")
            page.js(f"(() => {{ const s = document.querySelector('.pexam');"
                    f" const set = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;"
                    f" set.call(s, '{prev_id}');"
                    f" s.dispatchEvent(new Event('change', {{bubbles: true}})); return 1 }})()")
            page.cdp.drain(1.5)
            scene(page, "10_prev_exam", {"v16": "3", "v11": "5", "empty_btn": False})
            # 11. узкие окна: сводка под листом, страница не едет вбок
            page.size(1200, 900)
            scene(page, "11_narrow_1200", {"side_below": True, "cols": 32})
            page.size(1000, 800)
            scene(page, "12_narrow_1000", {"side_below": True, "cols": 32})
            if not any(page.check()["arch_scroll"]):
                results[-1][1].append("на 1000px дуга обязана прокручиваться внутри .pscroll")
            page.size(*WIDE)
    finally:
        if proc:
            proc.kill()
        shutil.rmtree(s1.dir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)

    red = [(n, f) for n, f, _ in results if f]
    print()
    print(f"кадров: {len(results)}, красных: {len(red)} → {out}")
    return 1 if red else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "build" / "shots" / "perio"),
                    help="куда класть PNG")
    a = ap.parse_args()
    sys.exit(run(pathlib.Path(a.out)))


if __name__ == "__main__":
    main()
