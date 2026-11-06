# -*- coding: utf-8 -*-
"""Движение на панели дня: есть там, где задумано, и нет там, где его быть не должно (06.11.2026).

    python scripts\\motion_check.py                 шесть сценариев на дереве
    python scripts\\motion_check.py --pair          и пары: копии дерева со сломанным правилом
                                                   обязаны краснеть — каждая своим сценарием
    python scripts\\motion_check.py --styles clar,sticla,fluent,modern,elegant,calm
                                                   окно, статус, меню и ответ — в каждом стиле
    ключи: --polls N (сколько опросов ждать в покое, по умолчанию 3), --only idle,dialog

⛔ Не в CI и не в `.\\dev test`: нужны Edge и websocket-client в системном Python
(в `.venv-desktop` ничего не ставить).

Зачем. Плавность не видит ни один другой стенд: `look_sweep` гасит переходы перед
кадром, `shift_sweep` смотрит только сдвиги раскладки, vitest не считает стилей.
А ломается она молча и в обе стороны: правило появления пропало — окно снова
«хлопает»; правило без охраны — анимация играет на каждом опросе живого канала
или у того, кто попросил систему убрать движение.

Сценарии (каждый — на свежей странице главной, окно 1366×768):
  idle    покой живого канала: N опросов подряд — все 204, ни одного запуска
          анимации или перехода, ни одного изменившегося узла (кроме часов меню
          и линии «сейчас»);
  dialog  окно визита: прозрачность по кадрам растёт от нуля до единицы, переход
          длится ступень `--dur-fast`, высота окна не меняется с приходом
          карандаша, сдвигов раскладки нет, окно кликабельно сразу;
  status  смена статуса при процессоре ×4: кнопки шага выключены на время
          команды, а их вид не меняется ни на одном кадре (не мигают);
  menu    меню правой кнопки проявляется;
  toast   плавающий ответ въезжает и ПОСЛЕ снятия класса `anim` (он снимается
          первым же изменением дня и до перезагрузки документа не возвращается);
  reduce  `prefers-reduced-motion`: после окна, меню, вкладки, смены статуса и
          сворачивания меню — ни одного НОВОГО перехода или анимации с
          длительностью (список «новое» — NEW ниже; задержанная ступенька вида
          выключенной кнопки длительности не имеет и движением не считается).

⚠️ Покой меряется ВНЕ границы получаса: на ней сервер законно меняет конверт (час
«сейчас», прошедшее начало записи). Перед сценарием стенд ждёт, если до границы
меньше, чем длится замер. Засев — записи не ближе двух часов от «сейчас»: у них
нет минутных порогов (опоздание 5 и 15 минут, счётчик ожидания).

⛔ Зелёный стенд сам по себе ничего не доказывает — доказательство пары (`--pair`,
проверено при заведении 06.11.2026, каждая покраснела своим сценарием):
  idle    · в конверт канала дописано «сейчас» (`core/api.live_envelope`) → опросы
            отвечают 200 вместо 204;
          · в panel.css дописан бесконечный пульс цифры вкладки → запуски в покое;
  dialog  · `dialog[open]{transition:none !important}` → перехода у окна нет;
  status  · у кнопок шага снята задержка вида (`transition:none !important`) →
            вид кнопок меняется на кадрах команды;
  menu    · `.dp-cmenu{transition:none !important}` → меню встаёт сразу;
  toast   · въезд ответа возвращён под `.anim` → после первого изменения дня
            ответ стоит без движения;
  reduce  · правило появления окна дописано БЕЗ `@media (prefers-reduced-motion)`
            → переход у окна при выключенном движении.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import BOT, TZ, Client, Server  # noqa: E402
from odo_shots import CDP, Page, login_cookie, start_edge  # noqa: E402

# ⛔ Свой порт отладки: 9337–9347, 9349, 9352/9353, 9355, 9360/9361 заняты
# соседними стендами, и запуск на занятом МОЛЧА подключается к чужому браузеру.
PORT = 9348
SIZE = (1366, 768)
LIVE_S = 12            # период опроса живого канала (services/live.ts › LIVE_MS)
SCENARIOS = ("idle", "dialog", "status", "menu", "toast", "reduce")
STYLE_SCENARIOS = ("dialog", "status", "menu", "toast")

# Замеры в странице: кадры, изменения узлов, сеть, сдвиги раскладки, запуски
# анимаций и переходов. Код программы не трогается — всё вводится по CDP.
INSTR = r"""(() => {
  if (window.__mc) return 1;
  const M = window.__mc = { frames: [], samples: [], muts: [], res: [], shifts: [], runs: [], on: false, sample: null };
  const sel = (n) => {
    if (!n) return 'null';
    if (n.nodeType === 3) return '#text<' + (n.parentElement ? sel(n.parentElement) : '') + '>';
    if (n.nodeType !== 1) return n.nodeName;
    let s = n.tagName.toLowerCase();
    if (n.id) s += '#' + n.id;
    const c = (typeof n.className === 'string' ? n.className : '').trim();
    if (c) s += '.' + c.split(/\s+/).join('.');
    return s.slice(0, 80);
  };
  M.reset = () => { M.frames = []; M.samples = []; M.muts = []; M.res = []; M.shifts = []; M.runs = []; M.on = true; };
  const dur = (e) => {
    try {
      const all = e.target.getAnimations({ subtree: false }).concat(
        e.pseudoElement ? document.getAnimations().filter((a) => a.effect && a.effect.target === e.target
          && a.effect.pseudoElement === e.pseudoElement) : []);
      const mine = all.filter((a) => (a.animationName || a.transitionProperty) === (e.animationName || e.propertyName));
      return mine.length ? Math.max(...mine.map((a) => Number(a.effect.getComputedTiming().duration) || 0)) : -1;
    } catch (x) { return -1; }
  };
  const run = (kind) => (e) => { if (M.on) M.runs.push({ kind, name: e.animationName || e.propertyName,
    target: sel(e.target), pseudo: e.pseudoElement || '', dur: dur(e), off: !!e.target.disabled }); };
  document.addEventListener('animationstart', run('animation'), true);
  document.addEventListener('animationiteration', run('iteration'), true);
  document.addEventListener('transitionrun', run('transition'), true);
  const watch = () => new MutationObserver((recs) => {
    if (!M.on) return;
    for (const r of recs) {
      const now = r.type === 'attributes' ? String(r.target.getAttribute(r.attributeName)) : '';
      // перемер ступеней блоков раз в минуту переписывает класс тем же значением — не изменение
      if (r.type === 'attributes' && String(r.oldValue) === now) continue;
      M.muts.push(sel(r.target) + (r.attributeName ? ' @' + r.attributeName : ''));
    }
  }).observe(document.documentElement, { subtree: true, childList: true, attributes: true,
    characterData: true, attributeOldValue: true });
  if (document.documentElement) watch(); else document.addEventListener('readystatechange', watch, { once: true });
  const loop = () => {
    if (M.on) {
      M.frames.push(performance.now());
      if (M.sample) { try { M.samples.push(M.sample()); } catch (e) { /* узла ещё нет */ } }
    }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  new PerformanceObserver((l) => { if (!M.on) return; for (const e of l.getEntries())
    M.res.push({ name: e.name.replace(location.origin, ''), status: e.responseStatus });
  }).observe({ type: 'resource', buffered: false });
  try { new PerformanceObserver((l) => { if (!M.on) return; for (const e of l.getEntries())
    M.shifts.push(Math.round(e.value * 10000) / 10000);
  }).observe({ type: 'layout-shift', buffered: false }); } catch (e) { /* движок без layout-shift */ }
  return 1;
})()"""

# ⚠️ Блок — НЕ завершённый: сценарии статуса доводят записи до «Finalizat», а у
# закрытого визита карандаша смены процедуры нет (режим --styles ходит по кругу).
BLOCK = "document.querySelector('.gappt:not(.gnote):not(.done)')"
STEP = "document.querySelector('.ag-l .ag-i .ag-next')"
DLG = ("() => { const d = document.querySelector('dialog[open]'); if (!d) return null;"
       " return [Number(getComputedStyle(d).opacity), d.offsetHeight, !!d.querySelector('button.dp-card-pen')]; }")

# Что считается НОВЫМ движением первой волны (сценарий reduce): цель и свойство.
# Наведение и фокус старых правил сюда не входят — их гасит прежний блок под `.anim`.
NEW = (
    ("dialog", ("opacity", "transform")),
    (".dp-cmenu", ("opacity", "transform")),
    (".fl-list", ("opacity",)), (".fl-empty", ("opacity",)),
    (".banner", ("dp-toast",)),
    (".side", ("width", "flex-basis")),
    ("", ("dp-moved", "dp-moved-g")),
    (".stat", ("background-color", "color")), (".pl-badge", ("background-color", "color")),
    (".gappt", ("background-color", "opacity")),
    (".ag-i", ("border-left-color", "border-top-color", "opacity")),
    ("b", ("color",)),
)


def is_new(r: dict) -> bool:
    if r["dur"] == 0:
        return False            # ступенька без длительности — не движение
    tag, *classes = r["target"].split("#")[0].split(".")
    for who, props in NEW:
        hit = not who or (who[1:] in classes if who.startswith(".") else who == tag)
        if hit and r["name"] in props:
            return True
    return r["off"] and r["name"] == "opacity"     # затухание выключенной кнопки


class Run:
    """Одна страница главной на одном сервере; собирает утверждения."""

    def __init__(self, cdp: CDP, url: str, label: str):
        self.cdp, self.url, self.label = cdp, url, label
        self.page = Page(cdp, url)
        self.bad: list[str] = []
        self.n = 0

    def ok(self, cond: bool, text: str) -> None:
        self.n += 1
        if not cond:
            self.bad.append(text)
        print(f"  {'OK ' if cond else 'RED'} {text}")

    def js(self, expr: str):
        return self.page.js(expr)

    def home(self) -> None:
        self.cdp.cmd("Network.setCookie", name="admin_auth", value=login_cookie(self.url), url=self.url + "/")
        self.page.size(*SIZE)
        self.page.go("/admin")
        time.sleep(1.2)

    def tap(self, finder: str, wait: float, sample: str = "", button: str = "left") -> dict:
        """Настоящий щелчок по центру элемента; всё, что случилось за `wait` секунд."""
        self.js(f"(() => {{ const el = {finder}; if (el) el.scrollIntoView({{block: 'center'}}); }})()")
        time.sleep(0.3)
        x, y = self.page.center(finder)
        m = self.cdp.cmd
        m("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        time.sleep(0.35)                 # наведение доиграло свои переходы
        self.js(f"__mc.sample = {sample or 'null'}; __mc.reset(); 1")
        m("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=1)
        m("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=1)
        self.cdp.drain(wait)
        return self.take()

    def take(self) -> dict:
        return json.loads(self.js("(() => { __mc.on = false; return JSON.stringify({samples: __mc.samples,"
                                  " muts: __mc.muts, res: __mc.res, shifts: __mc.shifts, runs: __mc.runs,"
                                  " frames: __mc.frames.length}) })()"))

    def esc(self) -> None:
        self.page.key("Escape")

    # ---------- сценарии ----------

    def idle(self, polls: int) -> None:
        span = polls * LIVE_S + 3
        now = datetime.now(TZ)
        left = (30 - now.minute % 30) * 60 - now.second
        if left < span + 5:
            print(f"  … до границы получаса {left} с — жду её: на ней сервер законно меняет конверт")
            time.sleep(left + 3)
            self.home()
        self.js("__mc.sample = null; __mc.reset(); 1")
        self.cdp.drain(span)
        d = self.take()
        live = [r["status"] for r in d["res"] if "/schedule/live" in r["name"]]
        self.ok(len(live) >= polls and all(s == 204 for s in live),
                f"покой: опросов {len(live)}, все 204 «не менялось»: {live}")
        self.ok(not d["runs"], f"покой: запусков анимаций и переходов {len(d['runs'])}"
                + (f" — {[r['name'] + ' ' + r['target'] for r in d['runs'][:4]]}" if d["runs"] else ""))
        noise = [m for m in d["muts"] if "sf_clock" not in m and "nowline" not in m]
        self.ok(not noise, f"покой: изменившихся узлов {len(noise)}" + (f" — {noise[:4]}" if noise else ""))

    def dialog(self) -> None:
        step = self.js("getComputedStyle(document.documentElement).getPropertyValue('--dur-fast').trim()")
        want = float(step.rstrip("s")) * (1 if step.endswith("ms") else 1000) if step else -1
        d = self.tap(BLOCK, 0.9, DLG)
        seen = [s for s in d["samples"] if s]
        ops = [s[0] for s in seen]
        self.ok(bool(ops) and ops[0] < 0.2 and ops[-1] == 1 and ops == sorted(ops),
                f"окно: прозрачность по кадрам растёт от нуля до единицы ({ops[:1]} … {ops[-1:]}, кадров {len(ops)})")
        mine = [r for r in d["runs"] if r["target"].startswith("dialog") and r["name"] == "opacity" and not r["pseudo"]]
        self.ok(len(mine) == 1 and abs(mine[0]["dur"] - want) < 1,
                f"окно: переход прозрачности один и длится ступень --dur-fast ({step}): {[r['dur'] for r in mine]} мс")
        back = [r for r in d["runs"] if r["target"].startswith("dialog") and r["pseudo"] == "::backdrop"]
        self.ok(bool(back), "окно: затемнение темнеет переходом вместе с окном")
        self.ok(len({s[1] for s in seen}) == 1 and any(s[2] for s in seen),
                f"окно: карандаш пришёл и высоту окна не изменил ({sorted({s[1] for s in seen})})")
        self.ok(not d["shifts"], f"окно: сдвигов раскладки после открытия нет ({d['shifts']})")
        self.ok(self.js("(() => { const d = document.querySelector('dialog[open]'); const r = d.getBoundingClientRect();"
                        " return d.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); })()"),
                "окно: под курсором — само окно, а не слой поверх (кликабельно)")
        self.esc()
        time.sleep(0.3)

    def status(self) -> None:
        look = ("() => { const bs = Array.from(document.querySelectorAll('.ag-next, .dk-btn, .dp-free-btn'));"
                " return [Math.min(...bs.map((b) => Number(getComputedStyle(b).opacity))),"
                " bs.filter((b) => b.disabled).length, bs.length]; }")
        self.cdp.cmd("Emulation.setCPUThrottlingRate", rate=4)
        time.sleep(0.3)
        try:
            before = self.js(f"({look})()[0]")
            d = self.tap(STEP, 1.8, look)
        finally:
            self.cdp.cmd("Emulation.setCPUThrottlingRate", rate=1)
        posts = [r for r in d["res"] if "/status" in r["name"]]
        self.ok(len(posts) == 1 and posts[0]["status"] == 200, f"статус: одна команда, ответ 200 ({[r['status'] for r in posts]})")
        self.ok(any(s[1] == s[2] and s[2] > 1 for s in d["samples"]),
                "статус: на время команды кнопки шага выключены все (защита от второго щелчка цела)")
        lows = sorted({s[0] for s in d["samples"]})
        self.ok(lows == [before], f"статус: вид кнопок не менялся ни на одном кадре (прозрачность {lows}, до щелчка {before})")
        time.sleep(1.6)                  # пометка сменившегося статуса доиграла

    def menu(self) -> None:
        d = self.tap(BLOCK, 0.6, "() => { const m = document.querySelector('.dp-cmenu');"
                     " return m ? Number(getComputedStyle(m).opacity) : null; }", button="right")
        ops = [s for s in d["samples"] if s is not None]
        self.ok(bool(ops) and ops[0] < 0.3 and ops[-1] == 1 and ops == sorted(ops),
                f"меню: проявляется по кадрам ({ops[:1]} … {ops[-1:]}, кадров {len(ops)})")
        self.esc()
        time.sleep(0.3)

    def toast(self) -> None:
        if self.js("document.documentElement.classList.contains('anim')"):
            self.tap(STEP, 1.8)          # первое изменение дня снимает `anim` — как у стойки
            time.sleep(1.6)
        self.ok(not self.js("document.documentElement.classList.contains('anim')"),
                "ответ: класс anim к этому времени снят (первым изменением дня)")
        self.tap(BLOCK, 0.9)
        self.js("(() => { const t = document.querySelector('dialog[open] textarea');"
                " Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, 'de sunat înapoi ' + Date.now());"
                " t.dispatchEvent(new Event('input', { bubbles: true })); return 1 })()")
        time.sleep(0.3)
        d = self.tap("Array.from(document.querySelectorAll('dialog[open] button')).find((b) => b.textContent.includes('Salvează'))",
                     1.2, "() => { const b = document.querySelector('.toastbox .banner');"
                          " return b ? [Number(getComputedStyle(b).opacity), Math.round(b.getBoundingClientRect().top)] : null; }")
        seen = [s for s in d["samples"] if s]
        self.ok(bool(seen) and seen[0][0] < 0.5 and seen[-1][0] == 1 and seen[0][1] > seen[-1][1],
                "ответ: плашка въезжает — прозрачность и место меняются по кадрам "
                + (f"({seen[0]} → {seen[-1]})" if seen else "(плашки нет)"))
        if self.js("!!document.querySelector('.toastbox .t-x')"):
            self.js("document.querySelector('.toastbox .t-x').click()")

    def reduce(self) -> None:
        if self.js("document.documentElement.classList.contains('anim')"):
            self.tap(STEP, 1.8)          # дальше — как у стойки: `anim` снят, прежний выключатель не работает
            time.sleep(1.6)
        self.cdp.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
        runs: list[dict] = []
        try:
            d = self.tap(BLOCK, 0.6, DLG)
            first = next((s for s in d["samples"] if s), None)
            self.ok(first is not None and first[0] == 1, f"без движения: окно стоит целиком с первого кадра ({first})")
            runs += d["runs"]
            self.esc()
            time.sleep(0.2)
            d = self.tap(BLOCK, 0.5, "() => { const m = document.querySelector('.dp-cmenu');"
                         " return m ? Number(getComputedStyle(m).opacity) : null; }", button="right")
            first = next((s for s in d["samples"] if s is not None), None)
            self.ok(first == 1, f"без движения: меню стоит целиком с первого кадра ({first})")
            runs += d["runs"]
            self.esc()
            time.sleep(0.2)
            runs += self.tap("document.querySelectorAll('.fl-tab')[1]", 0.4)["runs"]
            runs += self.tap("document.querySelectorAll('.fl-tab')[0]", 0.4)["runs"]
            d = self.tap(STEP, 2.0, "() => Array.from(document.querySelectorAll('.moved')).filter((el) =>"
                         " / 0px 0px 0px 3px/.test(' ' + getComputedStyle(el).boxShadow)).length")
            runs += d["runs"]
            self.ok(max(d["samples"] or [0]) >= 2,
                    f"без движения: запись со сменившимся статусом помечена кольцом без анимации ({max(d['samples'] or [0])} узла)")
            if self.js("!!document.querySelector('.side .side-fold')"):
                runs += self.tap("document.querySelector('.side .side-fold')", 0.5)["runs"]
                runs += self.tap("document.querySelector('.side .side-fold')", 0.5)["runs"]
        finally:
            self.cdp.cmd("Emulation.setEmulatedMedia", features=[])
        new = [r for r in runs if is_new(r)]
        if os.environ.get("MC_VERBOSE"):       # что именно запускалось — глазами, при разборе
            for line in sorted({f"{r['kind']} {r['name']} {r['target'][:40]} {r['pseudo']} {r['dur']}" for r in runs}):
                print("      ·", line)
        self.ok(not new, f"без движения: новых переходов и анимаций с длительностью {len(new)} из {len(runs)} запусков"
                + (f" — {[(r['name'], r['target'][:30], r['pseudo'], r['dur']) for r in new[:4]]}" if new else ""))

    def scenario(self, name: str, polls: int) -> None:
        print(f"[{self.label}] {name}")
        self.home()
        self.idle(polls) if name == "idle" else getattr(self, name)()


def seed(c: Client) -> None:
    """Девять записей на сегодня, не ближе двух часов от «сейчас»: в покое у них
    нет ни минутных порогов, ни прошедшего на глазах начала."""
    now = datetime.now(TZ)
    h0 = now.hour - 4 if now.hour >= 11 else max(7, now.hour + 2)
    day = now.date().isoformat()
    n = 0
    for dh in range(3):
        for dk in ("d2", "d3", "d4"):
            n += 1
            r = c.post_json("/api/schedule/appointments", {
                "date": day, "time": f"{h0 + dh:02d}:00", "doctor": dk, "service": "pain",
                "name": f"Proba Miscare {n}", "phone": f"06977{n:04d}"})
            if r.status != 200:
                raise SystemExit(f"засев не удался ({h0 + dh:02d}:00 {dk}): {r.status} {r.body[:120]}")


def broken_tree(css: str = "", patch: tuple[str, str, str] | None = None, swap: tuple[str, str] | None = None) -> pathlib.Path:
    """Копия `bot/` со сломанным правилом: дописка в конец panel.css, замена в
    panel.css (`swap`) или замена в файле движка (`patch`: путь, было, стало).
    ⛔ Правится КОПИЯ; чего ломать уже нет — стенд устарел вместе с кодом."""
    dst = pathlib.Path(tempfile.mkdtemp(prefix="dp_motion_")) / "bot"
    shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
    sheet = dst / "app" / "static" / "css" / "panel.css"
    if swap:
        text = sheet.read_text(encoding="utf-8")
        if swap[0] not in text:
            raise SystemExit(f"пара: в panel.css нет {swap[0]!r} — стенд устарел вместе с CSS")
        sheet.write_text(text.replace(swap[0], swap[1], 1), encoding="utf-8", newline="")
    if css:
        with open(sheet, "ab") as f:
            f.write(("\n" + css + "\n").encode("utf-8"))
    if patch:
        p = dst / patch[0]
        text = p.read_text(encoding="utf-8")
        if patch[1] not in text:
            raise SystemExit(f"пара: в {patch[0]} нет {patch[1]!r} — стенд устарел вместе с кодом")
        p.write_text(text.replace(patch[1], patch[2], 1), encoding="utf-8", newline="")
    return dst


# (сценарий, чем сломано, как сломать) — каждая обязана покраснеть СВОИМ сценарием
PAIRS = [
    ("idle", "«сейчас» в конверте канала", {"patch": (
        "app/core/api.py", 'out = {"screen": screen, "date": d.isoformat(), "live": state is not None}',
        'out = {"screen": screen, "date": d.isoformat(), "live": state is not None, "now": __import__("time").time()}')}),
    ("idle", "бесконечный пульс цифры вкладки", {"css": "@keyframes mc-pulse{50%{opacity:.6}}.fl-tab b{animation:mc-pulse 1s infinite}"}),
    ("dialog", "окно без перехода", {"css": "dialog[open]{transition:none !important}"}),
    ("status", "вид выключенной кнопки без задержки", {"css": ".savebtn.ag-next:disabled,.dk-btn:disabled,.dp-free-btn:disabled{transition:none !important}"}),
    ("menu", "меню без перехода", {"css": ".dp-cmenu{transition:none !important}"}),
    ("toast", "въезд ответа снова под .anim", {"swap": (" .toastbox .banner{animation:dp-toast .3s ease both}",
                                                         " .anim .toastbox .banner{animation:dp-toast .3s ease both}")}),
    ("reduce", "появление окна без охраны reduced-motion", {"css": "dialog[open]{transition:opacity var(--dur-fast) ease !important}"
                                                               "@starting-style{dialog[open]{opacity:0}}"}),
]


def run_tree(cdp: CDP, bot: pathlib.Path | None, label: str, names, polls: int, styles=()) -> tuple[int, list[str]]:
    s1 = Server(keep_dir=True, **({"bot": bot} if bot else {}))
    try:
        with s1:
            c = Client(s1.url).login()
            seed(c)
            run = Run(cdp, s1.url, label)
            cdp.cmd("Page.addScriptToEvaluateOnNewDocument", source=INSTR)
            if styles:
                for style in styles:
                    r = c.post_json("/api/settings/theme", {"style": style, "primary": "#0E9F8A", "custom": "", "menu": "soft"})
                    if r.msg != "ok_theme":
                        raise SystemExit(f"стиль {style} не сохранился: {r.msg}")
                    run.label = f"{label} · {style}"
                    for name in STYLE_SCENARIOS:
                        run.scenario(name, polls)
            else:
                for name in names:
                    run.scenario(name, polls)
            errs = cdp.errors()
            run.ok(not errs, f"ошибок консоли нет ({errs[:3]})")
            return run.n, run.bad
    finally:
        s1.drop()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", action="store_true")
    ap.add_argument("--styles", default="")
    ap.add_argument("--polls", type=int, default=3)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    names = [n for n in SCENARIOS if not a.only or n in a.only.split(",")]
    styles = [s for s in a.styles.split(",") if s]
    profile = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "dp-edge-motion-check")
    shutil.rmtree(profile, ignore_errors=True)
    proc, ws = start_edge(profile, port=PORT)
    blind: list[str] = []
    try:
        cdp = CDP(ws)
        for dom in ("Page", "Runtime", "Network"):
            cdp.cmd(f"{dom}.enable")
        cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
        total, bad = run_tree(cdp, None, "дерево", names, a.polls, styles)
        print(f"\n{'OK ' if not bad else 'RED'} дерево: {total - len(bad)}/{total}" + ("" if not bad else " — " + "; ".join(bad[:6])))
        if a.pair:
            for name, what, how in PAIRS:
                if a.only and name not in a.only.split(","):
                    continue
                copy = broken_tree(**how)
                try:
                    _n, red = run_tree(cdp, copy, f"пара · {what}", [name], min(a.polls, 2))
                finally:
                    shutil.rmtree(copy.parent, ignore_errors=True)
                seen = bool(red)
                print(f"пара {name}: {what} — {'видна (красное: ' + red[0][:90] + ')' if seen else 'НЕ ВИДНА — стенд слеп'}\n")
                if not seen:
                    blind.append(f"{name}: {what}")
    finally:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    okay = not bad and not blind
    tail = f"движение: {total - len(bad)}/{total} утверждений" + (f", стилей {len(styles)}" if styles else "")
    if a.pair:
        tail += f", пар {len(PAIRS) - len(blind)}/{len(PAIRS)} краснеют"
    print(("OK  " if okay else "RED ") + tail + ("" if okay else " — " + "; ".join((bad + ["слепая пара " + b for b in blind])[:4])))
    return 0 if okay else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
