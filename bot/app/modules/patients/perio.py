"""Пародонтограмма: карта пародонта — шесть точек на зуб, датированным осмотром.

Слой ПОВЕРХ зубов, как мост: состояние зуба в одонтограмме не мутируется —
кариес остаётся кариесом, а карман глубиной 5 мм живёт своей строкой. Разница
с мостом одна и несущая: **единица хранения здесь — ОСМОТР, а не текущее
состояние зуба.** Пародонтология вся про сравнение во времени — «было 5 мм,
стало 3» и есть результат лечения, — а карта без вчерашнего дня не отвечает ни
на один вопрос, ради которого её ведут.

Что записывается и что считается:
- PD (adâncimea de sondare) — глубина кармана, мм, шесть точек на зуб;
- REC (recesiune) — рецессия десны, мм, те же шесть точек;
- BOP (sângerare la sondare) — кровоточивость, маска из шести нулей и единиц;
- подвижность (Miller 0–3) и фуркация (Hamp 0–3) — у зуба целиком;
- CAL = PD + REC — НЕ хранится: вычислимое не записывать.

⚠️ Точка с PD = 0 считается НЕ ИЗМЕРЕННОЙ, а не «ноль миллиметров»: здорового
кармана в 0 мм не бывает (норма 1–3), и нулём в базе обозначается пропуск.
Отсюда знаменатель BOP% и средней глубины — только измеренные точки. Иначе
половина рта, оставленная пустой, разбавляла бы оба числа вдвое, и лечение
выглядело бы успешнее, чем оно есть.
"""
from __future__ import annotations

import html

from ... import engine as eng
from ... import teeth_svg as tsvg
from ...core import theme
from ...core.layout import _ic
from .odontogram import FDI_LOWER, FDI_UPPER

# Постоянные зубы обеих дуг. Молочных в пародонтальной карте не бывает: карта
# про опору постоянного зуба, и места для временных на листе нет.
PERIO_TEETH = tuple(FDI_UPPER + FDI_LOWER)

# Пороги отчёта — те, которыми пародонтолог описывает рот вслух.
DEEP_MM = 4          # с этого начинается «карман»
SEVERE_MM = 6        # глубокий карман

MOB_RO = {1: "gr. I", 2: "gr. II", 3: "gr. III"}
FURC_RO = {1: "gr. I", 2: "gr. II", 3: "gr. III"}

# Слова итоговой строки на языке ЛИСТА: строка едет в §4 печатной 043/e, а та
# бывает русской. ⚠️ Наборы ключей обязаны совпадать — подпись ищется по ключу.
_SUM_WORDS = {
    "ro": {"head": "Parodontogramă", "teeth": "dinți", "sites": "puncte",
           "mean": "adâncime medie", "deep": "pungi", "of_which": "din care",
           "mob": "mobilitate", "furc": "furcație"},
    "ru": {"head": "Пародонтограмма", "teeth": "зубов", "sites": "точек",
           "mean": "средняя глубина", "deep": "карманы", "of_which": "из них",
           "mob": "подвижность", "furc": "фуркация"},
}


# --------------------------------------------------------------- модель

def rows_map(rows: list) -> dict:
    """Строки базы (упакованные) → {номер зуба: разобранная строка}.
    Разбор ОДИН на всех потребителей — экран, печать, 043/e, выгрузка."""
    out = {}
    for r in rows or ():
        out[int(r["tooth"])] = {
            "tooth": int(r["tooth"]),
            "pd": tsvg._perio_mm(r.get("pd")),
            "rec": tsvg._perio_mm(r.get("rec")),
            "bop": tsvg._perio_flags(r.get("bop")),
            "mob": int(r.get("mob") or 0),
            "furc": int(r.get("furc") or 0),
        }
    return out


def _norm(rows) -> list:
    """Принять И строки базы, И уже разобранные. Иначе каждый потребитель
    помнил бы, что ему досталось, и однажды забыл бы."""
    out = []
    for r in rows or ():
        out.append(r if isinstance(r.get("pd"), list)
                   else rows_map([r])[int(r["tooth"])])
    return out


def chart_norm(parsed: list) -> list:
    """Разобранное с формы → то, что можно писать в базу.

    ⛔ Только постоянные зубы: молочные отбрасываются (см. PERIO_TEETH).
    ⛔ Зуб без единого показания не хранится вовсе: пустая строка в базе
       неотличима от «измерили, всё в норме», а это разные вещи.
    ⚠️ Упакованные строки готовятся ЗДЕСЬ, чтобы у db не было своего мнения о
       формате хранения — у неё его и не должно быть.
    """
    out = []
    for row in parsed:
        if row["tooth"] not in PERIO_TEETH:
            continue
        if not (any(row["pd"]) or any(row["rec"]) or "1" in row["bop"]
                or row["mob"] or row["furc"]):
            continue
        out.append({
            "tooth": row["tooth"],
            "pd": row["pd"], "rec": row["rec"], "bop": row["bop"],
            "mob": row["mob"], "furc": row["furc"],
            "pd_packed": tsvg.pack_perio_mm(row["pd"]),
            "rec_packed": tsvg.pack_perio_mm(row["rec"]),
        })
    return out


def summary(rows: list) -> dict:
    """Числа, которыми описывают рот: сколько зубов и точек измерено, BOP%,
    средняя глубина, карманы ≥4 и ≥6 мм, подвижные зубы и фуркации."""
    data = _norm(rows)
    sites = bleed = deep = severe = total = 0
    mob, furc = [], []
    for r in sorted(data, key=lambda x: x["tooth"]):
        for i, mm in enumerate(r["pd"]):
            if mm <= 0:
                continue
            sites += 1
            total += mm
            if r["bop"][i] == "1":
                bleed += 1
            if mm >= SEVERE_MM:
                severe += 1
                deep += 1
            elif mm >= DEEP_MM:
                deep += 1
        if r["mob"]:
            mob.append((r["tooth"], r["mob"]))
        if r["furc"]:
            furc.append((r["tooth"], r["furc"]))
    return {
        "teeth": len(data), "sites": sites,
        "bop": round(100 * bleed / sites) if sites else 0,
        "pd_mean": round(total / sites, 1) if sites else 0.0,
        "deep": deep, "severe": severe, "mob": mob, "furc": furc,
    }


def _day(value) -> str:
    return value.strftime("%d.%m.%Y") if hasattr(value, "strftime") else ""


def summary_line(exam: dict | None, rows: list, lang: str = "ro") -> str:
    """Одна строка о состоянии пародонта — для §4 печатной 043/e и выгрузки.
    Пусто, если осмотра нет: молчание честнее нулей, которых никто не мерил."""
    if not exam or not rows:
        return ""
    w = _SUM_WORDS.get(lang) or _SUM_WORDS["ro"]
    s = summary(rows)
    parts = [f"BOP {s['bop']}%", f"{w['mean']} {s['pd_mean']} mm",
             f"{w['deep']} {DEEP_MM}+ mm: {s['deep']}"]
    if s["severe"]:
        parts.append(f"{w['of_which']} {SEVERE_MM}+ mm: {s['severe']}")
    if s["mob"]:
        parts.append(f"{w['mob']}: " + ", ".join(
            f"{n} ({MOB_RO.get(g, g)})" for n, g in s["mob"]))
    if s["furc"]:
        parts.append(f"{w['furc']}: " + ", ".join(
            f"{n} ({FURC_RO.get(g, g)})" for n, g in s["furc"]))
    day = _day(exam.get("created_at"))
    head = f"{w['head']} {day}" if day else w["head"]
    return (f"{head} · {s['teeth']} {w['teeth']}, {s['sites']} {w['sites']} · "
            + ", ".join(parts))


def ledger_words(rows: list, when=None) -> str:
    """Строка летописи. ⚠️ Летопись хранит ГОТОВЫЙ текст навсегда, поэтому
    цифры разворачиваются в слова здесь и сейчас (правило db.log_event)."""
    s = summary(rows)
    day = _day(when)
    head = f"Parodontogramă (examen {day})" if day else "Parodontogramă"
    if not s["teeth"]:
        return f"{head}: examen gol"
    return (f"{head}: {s['teeth']} dinți măsurați, BOP {s['bop']}%, "
            f"adâncime medie {s['pd_mean']} mm, "
            f"pungi {DEEP_MM}+ mm: {s['deep']}")


# --------------------------------------------------------------- экран

def _cell(tooth: int, kind: str, i: int, value: int, bleed: bool) -> str:
    """Одна точка. ⚠️ Ноль показывается ПУСТЫМ полем, а не нулём: ноль в базе
    и значит «не измеряли», а написанный нолик врач прочитал бы измерением.
    Точка кровоточивости живёт только у PD — у рецессии её не бывает, и второй
    набор точек молча удваивал бы BOP при сборке формы."""
    v = str(value) if value else ""
    site = tsvg.PERIO_SITE_RO[tsvg.PERIO_SITES[i]]
    what = "adâncime" if kind == "pd" else "recesiune"
    deep = " deep" if kind == "pd" and value >= DEEP_MM else ""
    dot = (f"<button type='button' class='pdot{' on' if bleed else ''}' "
           f"data-i='{i}' title='Sângerare la sondare ({site})'></button>"
           if kind == "pd" else "")
    return (f"<div class='pcell{deep}'>"
            f"<input type='text' inputmode='numeric' maxlength='2' value='{v}' "
            f"data-k='{kind}' data-i='{i}' title='{what} · {site}' "
            f"aria-label='{tooth} {what} {site}'>{dot}</div>")


def _tooth_col(tooth: int, row: dict | None, absent: bool) -> str:
    r = row or {"pd": [0] * 6, "rec": [0] * 6, "bop": "000000",
                "mob": 0, "furc": 0}

    def cells(kind: str, sl: slice) -> str:
        return "".join(_cell(tooth, kind, i, r[kind][i], r["bop"][i] == "1")
                       for i in range(*sl.indices(6)))

    def pick(kind: str, top: int) -> str:
        cur = r[kind]
        opts = "".join(
            f"<option value='{i}'{' selected' if i == cur else ''}>"
            f"{i if i else '—'}</option>" for i in range(top + 1))
        title = "Mobilitate (Miller)" if kind == "mob" else "Furcație (Hamp)"
        return f"<select data-k='{kind}' title='{title}'>{opts}</select>"

    tip = " title='Dinte marcat absent în odontogramă'" if absent else ""
    return (f"<div class='ptooth{' absent' if absent else ''}' "
            f"data-tooth='{tooth}'{tip}>"
            f"<div class='prow'>{cells('pd', slice(0, 3))}</div>"
            f"<div class='prow rec'>{cells('rec', slice(0, 3))}</div>"
            f"<b class='pnum'>{tooth}</b>"
            f"<div class='prow rec'>{cells('rec', slice(3, 6))}</div>"
            f"<div class='prow'>{cells('pd', slice(3, 6))}</div>"
            f"<div class='pmf'>{pick('mob', tsvg.PERIO_MOB_MAX)}"
            f"{pick('furc', tsvg.PERIO_FURC_MAX)}</div></div>")


def _arch(teeth, data: dict, absent: set) -> str:
    return "<div class='parch'>" + "".join(
        _tooth_col(n, data.get(n), n in absent) for n in teeth) + "</div>"


def _sum_html(s: dict) -> str:
    def box(label: str, value, sub: str = "") -> str:
        return (f"<div class='psum-i'><span>{html.escape(label)}</span>"
                f"<b>{value}</b>"
                + (f"<small>{html.escape(sub)}</small>" if sub else "")
                + "</div>")
    return ("<div class='psum'>"
            + box("BOP", f"{s['bop']}%", "sângerare la sondare")
            + box("Adâncime medie", f"{s['pd_mean']} mm", "puncte măsurate")
            + box(f"Pungi {DEEP_MM}+ mm", s["deep"],
                  f"din care {SEVERE_MM}+ mm: {s['severe']}")
            + box("Dinți măsurați", s["teeth"], f"{s['sites']} puncte")
            + "</div>")


def page(patient: dict, exam: dict, exams: list, rows: list, absent: set,
         doc_opts: str, base: str) -> str:
    """Лист пародонтограммы: две дуги, шесть точек на зуб, счёт справа.

    ⚠️ Ввод рассчитан на ДИКТОВКУ: врач называет числа, ассистент печатает.
    Поэтому поле само уходит к следующей точке, как только число не может
    вырасти («3» — уже готовое значение, «1» ждёт вторую цифру), а
    кровоточивость ставится клавишей «b» с того же места. Без этого карту из
    192 чисел не заполняют — её просто не ведут.
    """
    e = html.escape
    data = rows_map(rows)
    s = summary(list(data.values()))
    opts = "".join(
        f"<option value='{x['id']}'{' selected' if x['id'] == exam['id'] else ''}>"
        f"{_day(x['created_at'])} · {x['teeth']} dinți</option>" for x in exams)
    note = e(exam.get("note") or "")
    cur_doc = (exam.get("doctor") or "").strip()
    docs = doc_opts.replace(f">{e(cur_doc)}<",
                            f" selected>{e(cur_doc)}<") if cur_doc else doc_opts
    shown = ",".join(str(n) for n in PERIO_TEETH)
    return f"""<div class='perio' id='perio'>
<div class='odop-top'>
  <a class='odop-back' href='{e(base)}'>{_ic('pat')} {e(patient['name'])}</a>
  <h2>Parodontogramă <small>· 6 puncte pe dinte</small></h2>
  <div class='odo-actions'>
    <form method='get' class='pinline'>
      <select name='exam' onchange='this.form.submit()'
              title='Examen'>{opts}</select>
    </form>
    <form method='post' action='{e(base)}/perio/new' class='pinline'>
      <button class='odo-more'>{_ic('plus')} Examen nou</button>
    </form>
    <a class='odo-more' href='{e(base)}/parodontograma/print'
       target='_blank'>{_ic('print')} Printează</a>
  </div>
</div>
<form method='post' action='{e(base)}/perio' id='pform'>
  <input type='hidden' name='exam' value='{exam['id']}'>
  <input type='hidden' name='chart' id='pchart'>
  <input type='hidden' name='shown' value='{shown}'>
  <div class='pgrid'>
    <div class='fcard'>
      <p class='hint'>Rânduri: adâncimea de sondare și recesiunea, dinspre
        vestibular spre oral. Punctul roșu = sângerare (tasta <b>b</b>).
        Cifra trece singură la punctul următor.</p>
      <div class='pscroll'>{_arch(FDI_UPPER, data, absent)}</div>
      <div class='pmid'><span>Maxilar</span><i></i><span>Mandibular</span></div>
      <div class='pscroll'>{_arch(FDI_LOWER, data, absent)}</div>
      <div class='pfoot'>
        <label>Medic <select name='doctor'><option value=''>—</option>{docs}</select></label>
        <label class='pnote'>Notă <input type='text' name='note' value='{note}'
          maxlength='200' placeholder='ex. reevaluare după detartraj'></label>
        <button class='pl-btn primary'>{_ic('save')} Salvează examenul</button>
      </div>
    </div>
    <aside class='fcard pside'>
      <h3>Rezultatul examenului</h3>
      {_sum_html(s)}
      <p class='hint'>Nivelul de atașament (CAL) = adâncime + recesiune: se
        calculează, nu se introduce.</p>
    </aside>
  </div>
</form>
<script>
var PERIO_DEEP = {DEEP_MM};
var PERIO_SEVERE = {SEVERE_MM};
var PERIO_MM_MAX = {tsvg.PERIO_MM_MAX};
{CHART_JS}
</script>
</div>"""


CHART_JS = """
(function () {
  var form = document.getElementById('pform');
  if (!form) return;
  var cells = Array.prototype.slice.call(
    form.querySelectorAll(".pcell input[type='text']"));

  /* Итоги пересчитываются В БРАУЗЕРЕ тем же счётом, что на сервере: врач
     видит BOP% сразу, не сохраняя. Сервер считает заново при отрисовке,
     поэтому расхождение живёт максимум до перезагрузки страницы. */
  function recalc() {
    var sites = 0, bleed = 0, deep = 0, severe = 0, mm = 0, teeth = {};
    form.querySelectorAll('.ptooth').forEach(function (col) {
      col.querySelectorAll('.pcell').forEach(function (cell) {
        var inp = cell.querySelector('input');
        if (!inp || inp.dataset.k !== 'pd') return;
        var v = parseInt(inp.value, 10);
        if (!(v > 0)) return;
        sites++; mm += v; teeth[col.dataset.tooth] = 1;
        if (v >= PERIO_SEVERE) { severe++; deep++; }
        else if (v >= PERIO_DEEP) { deep++; }
        var dot = cell.querySelector('.pdot');
        if (dot && dot.classList.contains('on')) bleed++;
      });
    });
    var vals = form.querySelectorAll('.psum b');
    if (vals.length < 4) return;
    vals[0].textContent = (sites ? Math.round(100 * bleed / sites) : 0) + '%';
    vals[1].textContent = (sites ? (Math.round(10 * mm / sites) / 10) : 0) + ' mm';
    vals[2].textContent = deep;
    vals[3].textContent = Object.keys(teeth).length;
  }

  /* Диктовка: значение уходит к следующей точке, как только не может вырасти.
     «1» ждёт вторую цифру (бывает 12 мм), «3» — уже готовое число. Без этого
     правила ассистент жмёт Tab сто девяносто два раза. */
  form.addEventListener('input', function (ev) {
    var inp = ev.target;
    if (inp.tagName !== 'INPUT' || !inp.dataset || !inp.dataset.k) return;
    inp.value = inp.value.replace(/[^0-9]/g, '').slice(0, 2);
    var v = parseInt(inp.value, 10);
    if (v > PERIO_MM_MAX) { inp.value = inp.value.slice(0, 1); v = parseInt(inp.value, 10); }
    if (inp.dataset.k === 'pd') {
      inp.parentNode.classList.toggle('deep', v >= PERIO_DEEP);
    }
    recalc();
    if (inp.value.length === 2 || (v >= 2 && v <= 9)) next(inp);
  });

  form.addEventListener('keydown', function (ev) {
    var inp = ev.target;
    if (inp.tagName !== 'INPUT' || !inp.dataset || !inp.dataset.k) return;
    if (ev.key === 'b' || ev.key === 'B') {
      ev.preventDefault();
      var dot = inp.parentNode.querySelector('.pdot');
      if (dot) { dot.classList.toggle('on'); recalc(); }
    } else if (ev.key === 'Enter') {
      ev.preventDefault(); next(inp);
    }
  });

  form.addEventListener('click', function (ev) {
    var d = ev.target.closest ? ev.target.closest('.pdot') : null;
    if (!d) return;
    d.classList.toggle('on');
    recalc();
  });

  function next(inp) {
    var i = cells.indexOf(inp);
    if (i >= 0 && i + 1 < cells.length) { cells[i + 1].focus(); cells[i + 1].select(); }
  }

  /* Сборка проволочной строки ПЕРЕД отправкой: одно скрытое поле вместо
     двухсот, как мост уезжает строкой «47:stalp,46:corp».
     ВАЖНО: зуб без единого показания в строку НЕ попадает — сервер обязан
     отличать «не измеряли» от «измерили, и там ноль». */
  form.addEventListener('submit', function () {
    var out = [];
    form.querySelectorAll('.ptooth').forEach(function (col) {
      var r = {pd: [0,0,0,0,0,0], rec: [0,0,0,0,0,0], bop: [0,0,0,0,0,0],
               mob: 0, furc: 0};
      col.querySelectorAll('.pcell').forEach(function (cell) {
        var inp = cell.querySelector('input');
        if (!inp) return;
        var i = parseInt(inp.dataset.i, 10);
        r[inp.dataset.k][i] = parseInt(inp.value, 10) || 0;
        var dot = cell.querySelector('.pdot');
        if (dot && dot.classList.contains('on')) r.bop[i] = 1;
      });
      col.querySelectorAll('select').forEach(function (s) {
        r[s.dataset.k] = parseInt(s.value, 10) || 0;
      });
      var any = r.pd.concat(r.rec, r.bop).some(function (x) { return x > 0; });
      if (!any && !r.mob && !r.furc) return;
      out.push(col.dataset.tooth + ':' + r.pd.join(',') + '/' + r.rec.join(',')
               + '/' + r.bop.join('') + '/' + r.mob + '/' + r.furc);
    });
    document.getElementById('pchart').value = out.join(';');
  });

  recalc();
})();
"""


# --------------------------------------------------------------- печать

# ⚠️ Заполнителей у theme.paint РОВНО ДВА: __ACCENT__ и __ON__. Любой другой
# («__ACCENT_D__», «__ACCENT_SOFT__») останется в стилях СТРОКОЙ — правило
# просто не применится, и увидеть это можно только распечатав лист. Фон плашки
# поэтому нейтрально-серый: он обязан быть спокойным при ЛЮБОМ цвете клиники.
_CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{font:12px/1.45 Inter,system-ui,sans-serif;color:#111;margin:24px;background:#fff}
h1{font-size:19px;margin:6px 0 2px}
h2{font-size:13px;margin:16px 0 6px;color:__ACCENT__}
.ph{display:flex;justify-content:space-between;align-items:flex-start;
    border-bottom:1.5px solid __ACCENT__;padding-bottom:8px}
.ph .pr{text-align:right}
.pmeta{color:#555;margin:0 0 4px}
.ptab{border-collapse:collapse;width:100%;font-size:10.5px;table-layout:fixed}
.ptab th{text-align:left;color:#555;font-weight:600;width:96px;
         padding:3px 6px 3px 0;white-space:nowrap}
.ptab td{border:1px solid #C9D6D2;padding:3px 2px;text-align:center;
         letter-spacing:.5px}
.ptab tr:first-child td{border:0;font-size:11px;padding-bottom:4px}
.pres{margin-top:14px;padding:8px 10px;border:1px solid __ACCENT__;
      border-radius:6px;background:#FAFAFA}
.pleg{color:#555;font-size:10px;margin-top:10px}
.psign{display:flex;gap:40px;margin-top:26px;color:#333}
.bd{display:inline-block;width:6px;height:6px;border-radius:50%;
  background:#B91C1C;vertical-align:middle}
.noprint{display:flex;gap:10px;margin:0 0 14px}
.noprint button{background:__ACCENT__;color:__ON__;border:none;border-radius:8px;
  padding:9px 20px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif}
.noprint a{align-self:center;color:__ACCENT__;font-family:system-ui,sans-serif;
  font-size:14px}
tr{page-break-inside:avoid}
.clogo{display:block;max-height:16mm;max-width:45mm;object-fit:contain;
  margin-bottom:2mm}
@media print{.noprint{display:none}body{margin:0}}
"""


def _print_arch(teeth, data: dict) -> str:
    def cell(row, key, sl, dots=False):
        if not row:
            return ""
        if dots:
            return " ".join("<i class='bd'></i>" if f == "1" else "·"
                            for f in row["bop"][sl])
        return " ".join(str(v) if v else "·" for v in row[key][sl])

    def line(label, fn) -> str:
        return (f"<tr><th>{label}</th>"
                + "".join(f"<td>{fn(data.get(n))}</td>" for n in teeth)
                + "</tr>")

    head = "".join(f"<td><b>{n}</b></td>" for n in teeth)
    v, o = slice(0, 3), slice(3, 6)
    return (f"<table class='ptab'><tr><th></th>{head}</tr>"
            + line("PD vestibular", lambda r: cell(r, "pd", v))
            + line("PD oral", lambda r: cell(r, "pd", o))
            + line("Recesiune V", lambda r: cell(r, "rec", v))
            + line("Recesiune O", lambda r: cell(r, "rec", o))
            + line("Sângerare V", lambda r: cell(r, "bop", v, True))
            + line("Sângerare O", lambda r: cell(r, "bop", o, True))
            + line("Mobilitate",
                   lambda r: MOB_RO.get(r["mob"], "") if r else "")
            + line("Furcație",
                   lambda r: FURC_RO.get(r["furc"], "") if r else "")
            + "</table>")


def print_sheet(patient: dict, exam: dict, rows: list) -> str:
    """Печатный лист пародонтограммы.

    ⛔ Отдельным листом, а НЕ внутри 043/e: структура 043/e задана приказом
    828/2011, и вставлять в неё свою таблицу нельзя. В саму 043/e едет ОДНА
    строка итога, в §4 «Date obiective», — там ей и место.
    ⚠️ Лист только румынский: это документ ВРАЧА, а не пациента (в отличие от
    анкеты анамнеза и информирования, которые печатаются на языке пациента).
    """
    e = html.escape
    data = rows_map(rows)
    s = summary(list(data.values()))
    day = _day(exam.get("created_at"))
    doctor = e(exam.get("doctor") or "")
    note = e(exam.get("note") or "")
    addr = e((eng.CONFIG or {}).get("address", {}).get("ro", ""))
    file_no = e((patient.get("file_no") or "").strip() or str(patient["id"]))
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Parodontogramă — {e(patient.get('name') or 'pacient')}</title>
<style>{theme.paint(_CSS)}</style></head><body>
<div class="noprint">
  <button onclick="window.print()">Printează</button>
  <a href="/admin/patient/{patient['id']}/parodontograma">Înapoi</a>
</div>
<div class="ph">
  <div>{theme.print_logo()}<b>{e(eng.CLINIC_NAME)}</b><br>
    <small>{addr}{(' · tel. ' + e(eng.CLINIC_PHONE)) if eng.CLINIC_PHONE else ''}</small></div>
  <div class="pr">Parodontogramă<br><small>{day}</small></div>
</div>
<h1>{e(patient.get('name') or '')}</h1>
<p class="pmeta">Fișa nr. {file_no}{(' · medic: ' + doctor) if doctor else ''}
  {(' · ' + note) if note else ''}</p>
<h2>Maxilar</h2>{_print_arch(FDI_UPPER, data)}
<h2>Mandibular</h2>{_print_arch(FDI_LOWER, data)}
<div class="pres"><b>Rezultat:</b> {s['teeth']} dinți, {s['sites']} puncte
  măsurate · BOP {s['bop']}% · adâncime medie {s['pd_mean']} mm ·
  pungi {DEEP_MM}+ mm: {s['deep']} (din care {SEVERE_MM}+ mm: {s['severe']})</div>
<p class="pleg">PD — adâncimea de sondare (mm); recesiune — retracția gingivală
  (mm); nivelul de atașament CAL = PD + recesiune. Puncte, în ordine:
  mezio-vestibular, vestibular, disto-vestibular / mezio-lingual, lingual,
  disto-lingual. «·» — punct nemăsurat. Mobilitate — Miller; furcație — Hamp.</p>
<div class="psign"><span>Medic ____________________</span>
  <span>Semnătura ____________________</span></div>
</body></html>"""
