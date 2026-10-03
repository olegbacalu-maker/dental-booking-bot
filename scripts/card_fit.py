# -*- coding: utf-8 -*-
"""Влезает ли карточка визита в свой блок — стенд вида карточки (03.10).

    python scripts\\card_fit.py           оба вида на канве панели дня
    python scripts\\card_fit.py --pair    и пара: копия дерева, где «время
                                         впереди» разложено сеткой, обязана краснеть

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. Высоту часа выбирает окно (`fitGrid`), ступень сжатия блока — замер
(`fitAppts`), и обоих не видит набор без браузера. У бейджа статуса в panel.css
написано «мерить браузером, а не арифметикой» — стенд и есть этот замер. Окно
1366×768 сажает час на пол 66px (блок 60px): там запас кончается первым.

Утверждения на каждый вид («имя впереди», «время впереди»):
  1. документ несёт `<html data-card>` выбранного вида;
  2. визит на 60 минут — полный, и со словом статуса тоже;
  3. ни у одного блока текст не обрезан по вертикали — ни краем блока, ни
     внутри строки — и строки не наезжают друг на друга: сетка ужимала
     строки, и fitAppts не видел ничего (03.10);
  4. визит на 30 минут — сжат: полный туда не влезает;
  5. у «времени впереди» сжатая строка начинается интервалом.

⛔ Зелёный стенд сам по себе ничего не доказывает. Доказательство — ПАРА
(`--pair`): та же раскладка сеткой вместо flex-переноса обязана дать красное
по утверждению 3 или 4, иначе стенд не видит того, ради чего написан.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
from datetime import timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from harness import BOT, Client, Server, clinic_today  # noqa: E402
from odo_shots import CDP, Page, login_cookie, start_edge  # noqa: E402

# ⛔ Свой порт отладки: 9337–9346 и 9352/9353 заняты соседними стендами, и
# запуск на занятом МОЛЧА подключается к чужому браузеру.
PORT = 9347
SIZE = (1366, 768)
VIEWS = ("name", "time")

# Длительности услуг стенда: короткая, средняя, длинная. 60 — у остальных.
DUR = {"consult": 30, "hygiene": 45, "long": 120}
# (врач, час, услуга, имя, статус): у 60-минутных — каждое слово статуса,
# которое печатается на блоке, и одно длинное имя.
ROWS = [
    ("d2", "08:00", "consult", "Proba Treizeci", ""),
    ("d2", "09:00", "pain", "Proba Asteapta", "waiting"),
    ("d2", "10:00", "hygiene", "Proba Patruzeci", "arrived"),
    ("d3", "08:00", "pain", "Proba Simplu", ""),
    ("d3", "09:00", "pain", "Proba Finalizata", "done"),
    ("d3", "10:00", "consult", "Proba Nu Venit", "noshow"),
    ("d4", "08:00", "long", "Proba Lung Popescu-Vasilescu", ""),
    ("d4", "10:00", "pain", "Proba In Cabinet", "arrived"),
]

# Обрезанный по вертикали текст: за краем блока или внутри своей строки.
# ⚠️ У строчных (`display:inline`, сжатая строка) своей высоты нет — у них
# смотрится только край блока.
# ⛔ Третья беда — строки НАЕЗЖАЮТ друг на друга: сетка ужимает строку, а
# элемент сохраняет свою высоту и вылезает в соседнюю. Каждая строка внутри
# себя цела, край блока не пересечён — первая версия замера этого не видела
# (пара 03.10 позеленела). Поэтому прямоугольники строк сверяются попарно.
# Пропускается только не отрисованное (внутри скрытой строки) и пустое.
MEASURE = r"""(() => {
  const out = [];
  for (const a of document.querySelectorAll('.gappt:not(.gnote)')) {
    const r = a.getBoundingClientRect();
    const mode = ['bare', 'tiny', 'slim'].find((c) => a.classList.contains(c)) || 'full';
    const cut = [], rows = [];
    for (const k of a.querySelectorAll('b, small, .gtm, .stat')) {
      const s = getComputedStyle(k);
      if (s.display === 'none' || !k.getClientRects().length || !(k.textContent || '').trim()) continue;
      const q = k.getBoundingClientRect();
      const nm = k.className || k.tagName.toLowerCase();
      if (s.display !== 'inline' && k.scrollHeight > k.clientHeight + 1) cut.push(nm + ': внутри строки');
      else if (q.bottom > r.bottom + 0.5 || q.top < r.top - 0.5) cut.push(nm + ': за краем блока');
      if (!k.classList.contains('stat')) rows.push([nm, q]);
    }
    for (let i = 0; i < rows.length; i++) {
      for (let j = i + 1; j < rows.length; j++) {
        const [n1, p] = rows[i], [n2, q] = rows[j];
        const w = Math.min(p.right, q.right) - Math.max(p.left, q.left);
        const h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
        if (w > 1 && h > 1) cut.push(n1 + ' наезжает на ' + n2);
      }
    }
    const gtm = a.querySelector('.gtm'), b = a.querySelector('b');
    const gtmShown = !!gtm && getComputedStyle(gtm).display !== 'none';
    out.push({
      title: a.getAttribute('title') || '', mode, h: Math.round(r.height * 10) / 10, cut,
      startsWithTime: gtmShown && !!b && gtm.getBoundingClientRect().left <= b.getBoundingClientRect().left,
    });
  }
  const gb = document.querySelector('.gridbody');
  return JSON.stringify({ card: document.documentElement.dataset.card || '',
    cell: gb ? getComputedStyle(gb).getPropertyValue('--cell').trim() : '', blocks: out });
})()"""


def prepare(dir_: pathlib.Path) -> None:
    """Профиль стенда: длительности услуг и React по умолчанию.

    ⭐ Пин наборов (`ui.react: []`) СНИМАЕТСЯ, как в mount_sweep: проверяется
    то, что клиника увидит по умолчанию, а не старая страница."""
    p = dir_ / "clinic.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    for s in cfg.get("services", []):
        if s.get("id") in DUR:
            s["duration"] = DUR[s["id"]]
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def seed(c: Client, day: str) -> None:
    for i, (dk, at, svc, name, _) in enumerate(ROWS):
        c.post("/admin/add", adate=day, atime=at, adoctor=dk, aservice=svc, aname=name,
               aphone=f"069{i:06d}", back="/admin")
    canvas = json.loads(c.get(f"/api/schedule/canvas?date={day}").body)["data"]
    ids = {b["name"]: b["id"] for col in canvas["columns"] for b in col["blocks"]
           if b["kind"] == "appt"}
    missing = [r[3] for r in ROWS if r[3] not in ids]
    if missing:
        raise SystemExit(f"засев не удался, нет блоков: {missing}")
    for _, _, _, name, status in ROWS:
        if status:
            c.post(f"/admin/status/{ids[name]}", to=status, back="/admin")


def measure(page: Page, c: Client, view: str, day: str) -> dict:
    r = c.post("/admin/settings/save", part="theme", style="fluent", primary="#0E9F8A",
               custom="", card=view)
    if r.msg != "ok_theme":
        raise SystemExit(f"вид {view} не сохранился: {r.msg}")
    page.go(f"/admin?date={day}")
    time.sleep(1.0)
    return json.loads(page.js(MEASURE))


def dur_of(block: dict) -> int:
    return int(re.search(r"(\d+)′", block["title"]).group(1))


def verdict(view: str, m: dict) -> list[str]:
    bad = []
    if m["card"] != view:
        bad.append(f"документ несёт data-card={m['card']!r}, а выбран {view!r}")
    if m["cell"] != "66px":
        bad.append(f"час не на полу: --cell={m['cell']} — запас 60px не проверен")
    if len(m["blocks"]) != len(ROWS):
        bad.append(f"блоков {len(m['blocks'])}, засеяно {len(ROWS)} — стенд мерил не то")
    for b in m["blocks"]:
        dur = dur_of(b)
        who = b["title"].split(" · ")[3] if b["title"].count(" · ") >= 3 else b["title"]
        if b["cut"]:
            bad.append(f"{who} ({dur}′, {b['mode']}): текст обрезан — {', '.join(b['cut'])}")
        if dur >= 60 and b["mode"] != "full":
            bad.append(f"{who} ({dur}′): сжат в {b['mode']} — полный вид не влез в блок {b['h']}px")
        if dur <= 30 and b["mode"] == "full":
            bad.append(f"{who} ({dur}′): «полный» в блоке {b['h']}px — сжатие не сработало")
        if view == "time" and b["mode"] == "slim" and not b["startsWithTime"]:
            bad.append(f"{who} ({dur}′): сжатая строка «времени впереди» не начинается интервалом")
    return bad


def run(bot: pathlib.Path | None, label: str) -> list[str]:
    """Один проход: свой сервер (из дерева `bot` или настоящего), оба вида."""
    day = (clinic_today() - timedelta(days=1)).isoformat()
    s1 = Server(keep_dir=True, **({"bot": bot} if bot else {}))
    prepare(s1.dir)
    profile = os.path.join(os.environ["TEMP"], "dp-edge-card-fit")
    proc, problems = None, []
    try:
        with s1:
            c = Client(s1.url).login()
            seed(c, day)
            proc, ws = start_edge(profile, port=PORT)
            cdp = CDP(ws)
            for dom in ("Page", "Runtime", "Network"):
                cdp.cmd(f"{dom}.enable")
            cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
            cdp.cmd("Network.setCookie", name="admin_auth", value=login_cookie(s1.url), url=s1.url + "/")
            page = Page(cdp, s1.url)
            page.size(*SIZE)
            for view in VIEWS:
                m = measure(page, c, view, day)
                bad = verdict(view, m)
                modes = "  ".join(f"{dur_of(b)}′={b['mode']}" for b in m["blocks"])
                print(f"{'OK ' if not bad else 'RED'} {label}: {view:<4}  --cell={m['cell']}  {modes}")
                for b in bad:
                    print(f"    ✗ {b}")
                problems += [f"{view}: {b}" for b in bad]
    finally:
        if proc:
            proc.kill()
        s1.drop()
    return problems


# Первая версия «времени впереди» (03.10): слово статуса во второй колонке
# сетки. Дописывается В КОНЕЦ таблицы копии и перебивает рабочие правила
# порядком — той же специфичностью.
_GRID = """
@media (min-width:641px){
 [data-card="time"] .gappt:not(.slim):not(.tiny):not(.bare):not(.gnote):has(> .gtm){display:grid;
   grid-template-columns:auto minmax(0,1fr);align-content:start}
 [data-card="time"] .gappt:not(.slim):not(.tiny):not(.bare):not(.gnote) .gtm{grid-area:1/1}
 [data-card="time"] .gappt:not(.slim):not(.tiny):not(.bare):not(.gnote) .stw{grid-area:1/2}
 [data-card="time"] .gappt:not(.slim):not(.tiny):not(.bare):not(.gnote) b,
 [data-card="time"] .gappt:not(.slim):not(.tiny):not(.bare):not(.gnote) small:not(.stw){grid-column:1/-1}
}
"""


def broken_tree() -> pathlib.Path:
    """Копия `bot/`, где «время впереди» разложено сеткой — та самая первая
    версия 03.10. Правка вносится в КОПИЮ; настоящее дерево не трогается."""
    dst = pathlib.Path(tempfile.mkdtemp(prefix="dp_cardfit_")) / "bot"
    shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
    css = dst / "app" / "static" / "css" / "panel.css"
    if b'[data-card="time"] .gappt' not in css.read_bytes():
        raise SystemExit("пара: правил «времени впереди» нет — стенд устарел вместе с CSS")
    with open(css, "ab") as f:
        f.write(_GRID.encode("utf-8"))
    return dst


def main(argv: list[str]) -> int:
    problems = run(None, "дерево")
    print(f"\n{'0 расхождений' if not problems else f'{len(problems)} расхождений'}: "
          f"карточка влезает в блок в обоих видах" + ("" if not problems else " — НЕТ"))
    if "--pair" not in argv:
        return 1 if problems else 0
    copy = broken_tree()
    try:
        broken = run(copy, "сетка")
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)
    seen = bool(broken)
    print(f"пара: раскладка сеткой {'видна (красное)' if seen else 'НЕ ВИДНА — стенд слеп'}")
    return 1 if problems or not seen else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
