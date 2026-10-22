# -*- coding: utf-8 -*-
"""Влезает ли карточка визита в свой блок — стенд вида карточки (03.10).

    python scripts\\card_fit.py           оба вида на канве панели дня
    python scripts\\card_fit.py --pair    и две пары: копия дерева, где «время
                                         впереди» разложено сеткой, и копия без
                                         «+N» в колонках дня врача — обе обязаны
                                         краснеть

⛔ Не в CI и не в `.\\dev test`: нужен Edge (в `.venv-desktop` ничего не ставить).

Зачем. Высоту часа выбирает окно (`fitGrid`), ступень сжатия блока — замер
(`fitAppts`), и обоих не видит набор без браузера. У бейджа статуса в panel.css
написано «мерить браузером, а не арифметикой» — стенд и есть этот замер. Окно
1366×768 сажает час на пол 64px (блок 58px, три строки с 08.10): там запас кончается первым.

Утверждения на каждый вид («имя впереди», «время впереди»):
  1. документ несёт `<html data-card>` выбранного вида;
  2. визит на 60 минут — полный, и со словом статуса тоже;
  3. ни у одного блока текст не обрезан по вертикали — ни краем блока, ни
     внутри строки — и строки не наезжают друг на друга: сетка ужимала
     строки, и fitAppts не видел ничего (03.10);
  4. визит на 30 минут — сжат: полный туда не влезает;
  5. у «времени впереди» сжатая строка начинается интервалом;
  6. (13.10, вариант B) визит на 15 минут — не ниже своего получасового слота
     (пол блока — шаг сетки стартов);
  7. в сжатом виде — имя и кнопка зуба, а статус словом: значка в углу нет;
  8. визит на 45 минут при часе 64px — две строки (`slim duo`), а не одна.

День ОДНОГО врача (22.10, вариант A Олега: колонки фактов справа от имени) —
те же утверждения 1–8 на его карточках, и сверх них:
  9. колонки стоят у каждой карточки с пациентом, кроме «только имени»;
 10. внутри колонки НИЧЕГО не срезано: колонка не переполнена ни по высоте,
     ни по ширине, каждая видимая строка внутри неё и внутри блока, «+N» не
     наезжает на строку и называет ровно столько, сколько спрятано;
 11. 90-минутный визит с восемью рисками колонку переполняет — у него «+N»:
     иначе случай, ради которого утверждение 10 есть, не засеян.
⚠️ Утверждение 10 — НЕ замер блока: колонки абсолютны с overflow:hidden и
`scrollHeight` блока не растят. Макет 22.10 мерил только блок, написал «не
переполнена», а кадр показал пятую строку, срезанную снизу.

⛔ Зелёный стенд сам по себе ничего не доказывает. Доказательство — ПАРЫ
(`--pair`): та же раскладка сеткой вместо flex-переноса обязана дать красное
по утверждению 3 или 4, а колонки без «+N» (спрятанное снова видно) — по
утверждению 10; иначе стенд не видит того, ради чего написан.
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
from datetime import date, timedelta

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
# 15 минут — своя услуга: у фикстуры такой длины нет (13.10, вариант B)
SHORT = {"id": "xray", "ro": "Radiografie dentară", "ru": "Рентген", "duration": 15}
# 90 минут — день врача (22.10): пять строк колонки на полу часа, и восемь
# рисков в них не влезают
LONG90 = {"id": "impl90", "ro": "Implant dentar", "ru": "Имплант", "duration": 90}
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
    ("d3", "11:00", "xray", "Proba Scurt", "waiting"),
    ("d2", "12:00", "impl90", "Proba Riscuri", ""),
]
# День врача: d2 — первые три строки ROWS и 90-минутный визит с рисками
DOC = "d2"
RISKY = "Proba Riscuri"

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
    const mode = ['bare', 'tiny', 'duo', 'slim'].find((c) => a.classList.contains(c)) || 'full';
    const shown = (q) => { const e = a.querySelector(q); return !!e && getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0; };
    const nb = a.querySelector('b');
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
        /* (08.10) только СОСЕДНИЕ СТРОКИ: у сжатой строки в одну линию
           многоточие контейнера дорисовывается к последнему видимому боксу, и
           его прямоугольник накрывает спрятанный за ним следующий — это не
           наезд, а усечение. Наезд — разные строки с общей высотой. */
        if (w > 1 && h > 1 && Math.abs(p.top - q.top) > 2) cut.push(n1 + ' наезжает на ' + n2);
      }
    }
    const gtm = a.querySelector('.gtm'), b = a.querySelector('b');
    const gtmShown = !!gtm && getComputedStyle(gtm).display !== 'none';
    out.push({
      title: a.getAttribute('title') || '', mode, h: Math.round(r.height * 10) / 10, cut,
      odo: shown('.apact'), icon: shown('.stt'), word: shown('.gl1 .stat'),
      nameW: nb && shown('b') ? Math.round(nb.getBoundingClientRect().width) : 0,
      startsWithTime: gtmShown && !!b && gtm.getBoundingClientRect().left <= b.getBoundingClientRect().left,
    });
  }
  const gb = document.querySelector('.gridbody');
  return JSON.stringify({ card: document.documentElement.dataset.card || '',
    cell: gb ? getComputedStyle(gb).getPropertyValue('--cell').trim() : '', blocks: out });
})()"""


# Колонки фактов дня врача (утверждение 10): переполнение мерится У КОЛОНКИ —
# по высоте и по ширине, — а каждая видимая строка сверяется с краем колонки
# и блока. Спрятанное в «+N» (`vf-cut`, display:none) не мерится, а считается.
FACTS = r"""(() => {
  const out = [];
  for (const a of document.querySelectorAll('.gappt.has-vf')) {
    const r = a.getBoundingClientRect();
    const mode = ['bare', 'tiny', 'duo', 'slim'].find((c) => a.classList.contains(c)) || 'full';
    const vf = a.querySelector('.vf');
    const shown = !!vf && getComputedStyle(vf).display !== 'none';
    const cut = [];
    let more = 0;
    if (shown) {
      const vr = vf.getBoundingClientRect();
      if (vr.bottom > r.bottom + 0.5 || vr.top < r.top - 0.5) cut.push('колонки за краем блока');
      for (const col of vf.querySelectorAll('.vf-col')) {
        const nm = col.getAttribute('aria-label') || 'колонка';
        const cs = getComputedStyle(col);
        const cr = col.getBoundingClientRect();
        const right = cr.right - parseFloat(cs.paddingRight) + 0.5;
        if (col.scrollHeight > col.clientHeight + 0.5) cut.push(nm + ': переполнена по высоте');
        if (col.scrollWidth > col.clientWidth + 0.5) cut.push(nm + ': переполнена по ширине');
        const m = col.querySelector(':scope > .vf-more');
        const on = !!m && getComputedStyle(m).display !== 'none';
        const mr = on ? m.getBoundingClientRect() : null;
        let hid = 0;
        for (const k of col.children) {
          if (k === m) continue;
          if (getComputedStyle(k).display === 'none') { hid += k.classList.contains('vf-cut') ? 1 : 0; continue; }
          const q = k.getBoundingClientRect();
          const t = (k.textContent || '').trim().slice(0, 28);
          if (q.bottom > Math.min(cr.bottom, vr.bottom, r.bottom) + 0.5 || q.top < Math.max(cr.top, r.top) - 0.5)
            cut.push(nm + ': строка «' + t + '» срезана краем');
          if (q.right > right + 1) cut.push(nm + ': строка «' + t + '» шире колонки');
          if (mr && q.bottom > mr.top + 1 && q.top < mr.bottom - 1 && q.right > mr.left + 0.5)
            cut.push(nm + ': «+N» наезжает на «' + t + '»');
        }
        if (on) {
          more += 1;
          if ((m.textContent || '') !== '+' + hid) cut.push(nm + ': «' + m.textContent + '» при спрятанных ' + hid);
          if (mr.bottom > cr.bottom + 0.5) cut.push(nm + ': «+N» срезан краем');
        } else if (hid) cut.push(nm + ': спрятано ' + hid + ', а «+N» нет');
      }
    }
    out.push({ title: a.getAttribute('title') || '', mode, shown, cut, more });
  }
  return JSON.stringify(out);
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
    cfg["services"].append(SHORT)
    cfg["services"].append(LONG90)
    cfg.pop("ui", None)
    cfg.pop("_ui_comment", None)
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def seed(c: Client, day: str) -> None:
    for i, (dk, at, svc, name, _) in enumerate(ROWS):
        c.post_json("/api/schedule/appointments", {"date": day, "time": at, "doctor": dk,
                                                  "service": svc, "name": name,
                                                  "phone": f"069{i:06d}"})
    canvas = json.loads(c.get(f"/api/schedule/canvas?date={day}").body)["data"]
    ids = {b["name"]: b["id"] for col in canvas["columns"] for b in col["blocks"]
           if b["kind"] == "appt"}
    missing = [r[3] for r in ROWS if r[3] not in ids]
    if missing:
        raise SystemExit(f"засев не удался, нет блоков: {missing}")
    for _, _, _, name, status in ROWS:
        if status:
            c.post_json(f"/api/schedule/appointments/{ids[name]}/status", {"to": status})
    seed_facts(c, day, canvas)


def seed_facts(c: Client, day: str, canvas: dict) -> None:
    """Факты 90-минутного визита дня врача: восемь рисков (atenționări и
    анамнез без пересечений — сервер их не сведёт), четыре процедуры плана
    и прошлый визит. Пять строк колонки на полу часа — им не влезть.
    Денег на карточке нет (Олег 22.10), засев их и не кладёт."""
    pid = next(b["pid"] for col in canvas["columns"] for b in col["blocks"]
               if b["kind"] == "appt" and b["name"] == RISKY)
    for kind, text in (("allergy", "Alergie: penicilină"), ("medication", "Anticoagulant: Xarelto"),
                       ("warning", "Sarcină, trimestrul II")):
        c.post_json(f"/api/patients/{pid}/alerts", {"kind": kind, "text": text})
    c.post_json(f"/api/patients/{pid}/anamneza",
                {"flags": ["diabet", "astm", "epilepsie", "tiroida"], "alergii": "latex"})
    for tooth, proc in (("46", "Implant Osstem"), ("45", "Obturație compozit"),
                        ("11", "Coroană ceramică"), ("36", "Tratament endodontic")):
        c.post_json(f"/api/patients/{pid}/plan", {"tooth": tooth, "procedure": proc,
                                                 "doctor": "", "price": "900", "due_date": ""})
    # прошлый визит — тем же телефоном, то есть тем же пациентом
    phone = f"069{[r[3] for r in ROWS].index(RISKY):06d}"
    prev = (date.fromisoformat(day) - timedelta(days=40)).isoformat()
    c.post_json("/api/schedule/appointments", {"date": prev, "time": "09:00", "doctor": DOC,
                                              "service": "pain", "name": RISKY, "phone": phone})


def measure(page: Page, c: Client, view: str, day: str, doctor: str = "") -> dict:
    r = c.post_json("/api/settings/theme", {"style": "fluent", "primary": "#0E9F8A",
                                            "custom": "", "card": view})
    if r.msg != "ok_theme":
        raise SystemExit(f"вид {view} не сохранился: {r.msg}")
    page.go(f"/admin/doctor/{doctor}?date={day}" if doctor else f"/admin?date={day}")
    time.sleep(1.0)
    m = json.loads(page.js(MEASURE))
    m["facts"] = json.loads(page.js(FACTS)) if doctor else []
    return m


def dur_of(block: dict) -> int:
    return int(re.search(r"(\d+)′", block["title"]).group(1))


def verdict(view: str, m: dict, rows: list = ROWS) -> list[str]:
    bad = []
    if m["card"] != view:
        bad.append(f"документ несёт data-card={m['card']!r}, а выбран {view!r}")
    if m["cell"] != "64px":
        bad.append(f"час не на полу: --cell={m['cell']} — запас 58px не проверен")
    if len(m["blocks"]) != len(rows):
        bad.append(f"блоков {len(m['blocks'])}, засеяно {len(rows)} — стенд мерил не то")
    for b in m["blocks"]:
        dur = dur_of(b)
        who = b["title"].split(" · ")[3] if b["title"].count(" · ") >= 3 else b["title"]
        if b["cut"]:
            bad.append(f"{who} ({dur}′, {b['mode']}): текст обрезан — {', '.join(b['cut'])}")
        if dur >= 60 and b["mode"] != "full":
            bad.append(f"{who} ({dur}′): сжат в {b['mode']} — полный вид не влез в блок {b['h']}px")
        if dur <= 30 and b["mode"] == "full":
            bad.append(f"{who} ({dur}′): «полный» в блоке {b['h']}px — сжатие не сработало")
        if view == "time" and b["mode"] in ("slim", "duo") and not b["startsWithTime"]:
            bad.append(f"{who} ({dur}′): сжатая строка «времени впереди» не начинается интервалом")
        # 13.10, вариант B: короткий визит читается — имя, зуб, статус словом
        half = int(m["cell"].rstrip("px") or 0) / 2 - 6
        if dur < 30 and b["h"] < half - 0.5:
            bad.append(f"{who} ({dur}′): блок {b['h']}px ниже своего слота ({half}px) — пол не держится")
        if b["mode"] in ("slim", "duo"):
            if not b["odo"]:
                bad.append(f"{who} ({dur}′, {b['mode']}): нет кнопки зуба")
            if b["nameW"] < 20:
                bad.append(f"{who} ({dur}′, {b['mode']}): имени не видно ({b['nameW']}px)")
            if b["icon"]:
                bad.append(f"{who} ({dur}′, {b['mode']}): значок статуса в углу вместо слова")
        if dur == 45 and m["cell"] == "64px" and b["mode"] != "duo":
            bad.append(f"{who} (45′): при часе 64px — {b['mode']}, а не две строки")
    return bad


def verdict_facts(m: dict) -> list[str]:
    """Утверждения 9–11: колонки фактов дня врача."""
    bad = []
    mine = [r for r in ROWS if r[0] == DOC]
    if len(m["facts"]) != len(mine):
        bad.append(f"колонки у {len(m['facts'])} карточек из {len(mine)} — факты не приехали")
    for f in m["facts"]:
        dur = dur_of(f)
        who = f["title"].split(" · ")[3] if f["title"].count(" · ") >= 3 else f["title"]
        if not f["shown"] and f["mode"] not in ("tiny", "bare"):
            bad.append(f"{who} ({dur}′, {f['mode']}): колонок не видно")
        for x in f["cut"]:
            bad.append(f"{who} ({dur}′, {f['mode']}): {x}")
        if who == RISKY and not f["more"]:
            bad.append(f"{who} ({dur}′): восемь рисков влезли без «+N» — переполнение не засеяно")
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
                for doctor in ("", DOC):
                    m = measure(page, c, view, day, doctor)
                    bad = (verdict(view, m, [r for r in ROWS if r[0] == DOC]) + verdict_facts(m)
                           if doctor else verdict(view, m))
                    where = f"день {doctor}" if doctor else "главная"
                    modes = "  ".join(f"{dur_of(b)}′={b['mode']}" for b in m["blocks"])
                    more = f"  «+N»={sum(f['more'] for f in m['facts'])}" if doctor else ""
                    print(f"{'OK ' if not bad else 'RED'} {label}: {view:<4} {where:<8} "
                          f"--cell={m['cell']}  {modes}{more}")
                    for b in bad:
                        print(f"    ✗ {b}")
                    problems += [f"{view} {where}: {b}" for b in bad]
    finally:
        if proc:
            proc.kill()
        s1.drop()
    return problems


# Сломанная пара: три строки блока (08.10: .gl1, имя, услуга) разложены
# сеткой, которая УЖИМАЕТ ряды под высоту блока (minmax(0,1fr)) — та самая
# беда 03.10: строки режутся и наезжают, а fitAppts (scrollHeight) ничего не
# видит. Дописывается В КОНЕЦ таблицы копии и перебивает рабочие правила
# порядком — той же специфичностью.
_GRID = """
@media (min-width:641px){
 [data-card="time"] .gappt:not(.slim):not(.tiny):not(.bare):not(.gnote):has(> .gl1){display:grid;
   grid-template-rows:repeat(3,minmax(0,1fr));align-content:stretch}
 [data-card="time"] .gappt:not(.slim):not(.tiny):not(.bare):not(.gnote)>*{min-height:0}
}
"""


# Вторая пара (22.10): колонки дня врача без «+N» — спрятанное снова видно,
# метки нет. Так стояло на макете: строки режутся краем колонки, а блок «не
# переполнен». Утверждение 10 обязано это увидеть.
_NO_MORE = """
.vf-col > .vf-cut{display:block !important}
.vf-more.on{display:none !important}
"""


def broken_tree(tail: str = _GRID, marker: bytes = b'[data-card="time"] .gappt') -> pathlib.Path:
    """Копия `bot/` с правилом поломки в конце panel.css: сетка «времени
    впереди» (первая версия 03.10) или колонки без «+N» (макет 22.10).
    Правка вносится в КОПИЮ; настоящее дерево не трогается. `marker` — правило,
    которое ломается: нет его в стилях — стенд устарел вместе с CSS."""
    dst = pathlib.Path(tempfile.mkdtemp(prefix="dp_cardfit_")) / "bot"
    shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
    css = dst / "app" / "static" / "css"
    if not any(marker in (css / n).read_bytes() for n in ("panel.css", "bundle.css")
               if (css / n).exists()):
        raise SystemExit(f"пара: правила {marker.decode()} нет — стенд устарел вместе с CSS")
    with open(css / "panel.css", "ab") as f:
        f.write(tail.encode("utf-8"))
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
    copy = broken_tree(_NO_MORE, b".vf-more")
    try:
        cols = run(copy, "без +N")
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)
    # красное — именно утверждением 10, а не случайным соседом
    seen_cols = any("срезана краем" in p or "переполнена" in p for p in cols)
    print(f"пара: колонки без «+N» {'видны (красное)' if seen_cols else 'НЕ ВИДНЫ — стенд слеп'}")
    return 1 if problems or not seen or not seen_cols else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
