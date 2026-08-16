# -*- coding: utf-8 -*-
"""Одонтограмма: обе дуги, оба вида, компактная карточка и детальная страница.

Модуль РИСУЮЩИЙ, без маршрутов — как `visit.py`: маршруты остаются в
`routes.py`, он же зовёт отсюда. Обратной ссылки нет и быть не может
(routes → odontogram), иначе круг.

Почему вынесено (08-16): рисунок зуба понадобился ДВУМ экранам — компактной
карточке в фише и отдельной странице «Detaliat». Копия кнопки зуба разошлась бы
первой: у неё формат подписи, сторона номера и обработчики, и «11 · Carie · MO»
на одном экране легко стало бы «11 Carie» на другом — ровно та болезнь, что
уже случалась со STATUS_LABEL и _STATUS_RO.

⚠️ Здесь ЖИВЁТ переключатель вида, и он один на оба экрана: `data-view` на
элементе `#odo`, CSS прячет `.v-frontal` или `.v-ocluzal`. На детальной
странице `#odo` — вся страница целиком, поэтому подписи поверхностей у
инспектора тоже слушаются переключателя.
"""
from __future__ import annotations

import html

from ... import engine as eng
from ... import teeth_svg as tsvg
from ...core.layout import _ic, js_json

FDI_UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
FDI_LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
# молочный прикус: те же квадранты, что и постоянный, но по пять зубов
FDI_MILK_UPPER = [55, 54, 53, 52, 51, 61, 62, 63, 64, 65]
FDI_MILK_LOWER = [85, 84, 83, 82, 81, 71, 72, 73, 74, 75]
FDI_ALL = FDI_UPPER + FDI_LOWER + FDI_MILK_UPPER + FDI_MILK_LOWER

# поверхности зуба: буква → румынское название. Порядок как в записи «MOD»,
# принятой в карте: медиальная, окклюзионная, дистальная, потом щёчная и нёбная
TOOTH_SURFACES = {"M": "mezial", "O": "ocluzal", "D": "distal",
                  "V": "vestibular", "L": "lingual"}

# Имя состояния берётся из `teeth_svg.STATE_RO` — там же, откуда его берёт
# летопись `db.set_tooth`. Своего словаря здесь нет НАМЕРЕННО.
STATES = tsvg.STATE_RO


# Подъём середины дуги в виде СВЕРХУ. Сверху челюсть — подкова, и ряд по
# линейке читается как таблица, а не как челюсть. В лицевом виде изгиба нет
# НАМЕРЕННО: там зубы стоят фронтально, и дуга ушла бы в декорацию, которая
# вдобавок разъезжается с цифрами.
ARC_PERM, ARC_MILK = 22.0, 15.0


def arc_offset(i: int, count: int, *, lower: bool, milk: bool = False) -> float:
    """Смещение зуба по вертикали, px. Середина уходит ОТ разделителя, края
    остаются на месте — так изгиб не съедает межчелюстной зазор и не упирает
    моляры в разделительную линию."""
    a = ARC_MILK if milk else ARC_PERM
    half = (count - 1) / 2
    k = (i - half) / half if half else 0.0
    return (a if lower else -a) * (1 - k * k)


# Подписи челюстей на разделителе. В виде СВЕРХУ они не украшение: корней там
# нет, и какая дуга верхняя — видно только по номерам. В лицевом виде тоже не
# лишние, а разнобой между видами был бы хуже подписи.
ARCH_MID = ("<div class='arch-mid'><b>Maxilar</b><i></i><b>Mandibular</b></div>")


def sf_text(sfmap: dict, sf: str) -> str:
    """Поверхности ОДНОЙ подписью: «Carie (M), Obturație (O)».

    ⚠️ Смесь состояний разворачивается словами: голое «MO» рядом с одним
    названием состояния было бы неправдой — так же, как в бланке 043/e и в
    выгрузке по 195-му. Однородный зуб даёт прежние буквы и прежнюю подпись.
    ⭐ Одно место на ВСЕ подписи зуба (title кнопки и плавающая подсказка):
    два текста об одном разошлись бы, и это ровно болезнь STATUS_LABEL —
    подсказка уже говорила «Carie · MO» там, где title говорил правду.
    """
    parts = tsvg.surface_summary(sfmap)
    return (", ".join(f"{STATES[k]} ({v})" for k, v in parts)
            if len(parts) > 1 else sf)


def _btn(n: int, tmap: dict, *, lower: bool = False, milk: bool = False,
         occ: bool = False, tip: bool = True, click: str = "openTooth",
         arc: float = 0.0) -> str:
    """Кнопка одного зуба.

    `tip` — плавающая подсказка при наведении: она нужна КОМПАКТНОЙ карточке,
    где кроме рисунка ничего не видно. На детальной странице всё то же самое
    постоянно показывает инспектор справа, и вторая всплывашка поверх него
    только мешает; обработчиков там нет, поэтому и вешать их нельзя — иначе
    наведение сыпало бы ошибками в консоль.
    """
    e = html.escape
    t = tmap.get(n)
    st = t["state"] if t else "ok"
    note = t["note"] if t else ""
    sf = (t["surfaces"] if t else "") or ""
    sfmap = tsvg.surface_map(st, sf, (t["surface_states"] if t else "") or "")
    # поверхности дописываются ПОСЛЕ заметки: подпись «11 · Carie · test»
    # читают и человек, и проверка, и её формат менять незачем.
    sf_txt = sf_text(sfmap, sf)
    title = (f"{n} · {STATES.get(st, st)}"
             + (f" · {note}" if note else "")
             + (f" · {sf_txt}" if sf_txt else ""))
    num = f"<span class='num'>{n}</span>"
    if occ:
        svg = tsvg.occlusal_svg(n, st, width=38 if milk else 52,
                                interactive=True, surfaces=sfmap)
    else:
        svg = tsvg.tooth_svg(n, st, width=28 if milk else 38, interactive=True,
                             surfaces=sfmap)
    hover = (f" onmouseenter='toothTip(event,{n})' onmouseleave='toothTipOff()'"
             f" onfocus='toothTip(event,{n})' onblur='toothTipOff()'" if tip else "")
    # номер всегда со стороны КОРНЕЙ: у верхней дуги сверху, у нижней снизу —
    # так цифры не лезут в межчелюстной зазор и читаются как в макете.
    # В виде сверху корней нет, но порядок тот же: иначе при переключении
    # цифры прыгают через зуб, и глаз теряет колонку
    # ⚠️ Смещение едет ПЕРЕМЕННОЙ, а не готовым transform: наведение поднимает
    # зуб тем же свойством, и инлайновый transform перебил бы правило :hover
    # (инлайн специфичнее любого селектора) — подъём молча перестал бы работать.
    style = f" style='--arc:{arc:.0f}px'" if arc else ""
    return (f"<button type='button' class='tooth-btn' data-n='{n}'{style} "
            f"title=\"{e(title)}\" onclick='{click}({n})'{hover}>"
            f"{svg + num if lower else num + svg}</button>")


def _arch_wrap(tmap: dict, occ: bool, *, tip: bool, click: str) -> str:
    cls = " occ" if occ else ""
    n_up, n_lo = len(FDI_UPPER), len(FDI_LOWER)
    up = "".join(_btn(n, tmap, occ=occ, tip=tip, click=click,
                      arc=arc_offset(i, n_up, lower=False) if occ else 0.0)
                 for i, n in enumerate(FDI_UPPER))
    lo = "".join(_btn(n, tmap, lower=True, occ=occ, tip=tip, click=click,
                      arc=arc_offset(i, n_lo, lower=True) if occ else 0.0)
                 for i, n in enumerate(FDI_LOWER))
    return (f"<div class='arch-wrap'><div class='arch{cls}'>{up}</div>"
            f"{ARCH_MID}"
            f"<div class='arch{cls} lower'>{lo}</div></div>")


def _milk_wrap(tmap: dict, occ: bool, *, tip: bool, click: str) -> str:
    cls = " occ" if occ else ""
    n_up, n_lo = len(FDI_MILK_UPPER), len(FDI_MILK_LOWER)
    up = "".join(_btn(n, tmap, milk=True, occ=occ, tip=tip, click=click,
                      arc=arc_offset(i, n_up, lower=False, milk=True) if occ else 0.0)
                 for i, n in enumerate(FDI_MILK_UPPER))
    lo = "".join(_btn(n, tmap, lower=True, milk=True, occ=occ, tip=tip, click=click,
                      arc=arc_offset(i, n_lo, lower=True, milk=True) if occ else 0.0)
                 for i, n in enumerate(FDI_MILK_LOWER))
    return (f"<div class='arch-wrap'><div class='arch{cls} milk-arch'>{up}</div>"
            f"{ARCH_MID}"
            f"<div class='arch{cls} lower milk-arch'>{lo}</div></div>")


def _legend(occ: bool) -> str:
    """Легенда показывает НАСТОЯЩИЙ зуб в каждом состоянии, а не цветной
    квадрат: так видно, чем «коронка» отличается от «пломбы», без словаря."""
    draw = ((lambda k: tsvg.occlusal_svg(36, k, width=26)) if occ
            else (lambda k: tsvg.tooth_svg(36, k, width=20)))
    return "".join(f"<span class='lg'>{draw(k)} {v}</span>"
                   for k, v in STATES.items() if k != "ok")


def view_switch() -> str:
    return ("<div class='viewsw' role='group' aria-label='Vedere'>"
            "<button type='button' data-v='frontal' class='on' aria-pressed='true'>"
            "Vedere frontală</button>"
            "<button type='button' data-v='ocluzal' aria-pressed='false'>"
            "Vedere ocluzală</button></div>")


VIEW_SCRIPT = """
// Выбор вида ПЕРЕЖИВАЕТ сохранение зуба: форма уходит POST'ом и возвращает
// страницу заново, поэтому без памяти врач, отметивший поверхность сверху,
// каждый раз возвращался бы в лицевой вид. localStorage, а не sessionStorage:
// вкладка та же, но состояние должно жить и между запусками программы.
(function () {
  var box = document.getElementById('odo');
  if (!box) return;
  var btns = box.querySelectorAll('.viewsw button');
  function set(v) {
    box.dataset.view = v;
    for (var i = 0; i < btns.length; i++) {
      var on = btns[i].dataset.v === v;
      btns[i].classList.toggle('on', on);
      btns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    try { localStorage.setItem('dp_odo_view', v); } catch (e) {}
    // инспектор рисует зуб из ВИДИМОЙ дуги, значит после переключения его
    // надо перерисовать — иначе сверху остаётся лицевой рисунок
    if (window.selTooth && window.SEL_TOOTH) selTooth(window.SEL_TOOTH);
  }
  for (var i = 0; i < btns.length; i++) {
    btns[i].addEventListener('click', function () { set(this.dataset.v); });
  }
  var saved = null;
  try { saved = localStorage.getItem('dp_odo_view'); } catch (e) {}
  if (saved === 'ocluzal') set(saved);
})();
"""


def tooth_data(tmap: dict, tooth_acts: list) -> tuple:
    """(данные зубов, история по зубам) для браузера.

    ⚠️ `jaw` и `mez` считает СЕРВЕР (`tsvg.is_upper`, `tsvg.mesial_right`).
    Правило «квадранты 1/4/5/8 лежат слева, значит их середина справа» обязано
    жить в одном месте: повтори его в JS — и подписи M/D у инспектора начнут
    расходиться с полями, залитыми на самом зубе, причём только у половины
    челюсти.
    """
    def info(n: int) -> dict:
        t = tmap.get(n)
        base = {"jaw": "sus" if tsvg.is_upper(n) else "jos",
                "mez": "right" if tsvg.mesial_right(n) else "left"}
        if not t:
            return {**base, "state": "ok", "note": "", "doctor": "", "at": "",
                    "sf": "", "sfx": "", "sfst": {}}
        sfmap = tsvg.surface_map(t["state"], t["surfaces"] or "",
                                 (t["surface_states"] or ""))
        return {**base, "state": t["state"], "note": t["note"] or "",
                "doctor": t["doctor"] or "", "sf": t["surfaces"] or "",
                "sfst": sfmap,
                # ⚠️ Готовая подпись, а не голые буквы: плавающая подсказка
                # печатает её как есть. Собирает её СЕРВЕР (`sf_text`) — порядок
                # тяжести и слова живут в одном месте, второй копии в JS нет
                "sfx": sf_text(sfmap, t["surfaces"] or ""),
                "at": t["updated_at"].astimezone(eng.TZ).strftime("%d.%m.%Y")
                      if t["updated_at"] else ""}

    hist: dict[str, list] = {}
    for a in tooth_acts:
        at = a["at"].astimezone(eng.TZ) if hasattr(a["at"], "astimezone") else None
        hist.setdefault(str(a["tooth"]), []).append(
            {"at": at.strftime("%d.%m.%Y") if at else "", "text": a["text"]})
    return js_json({str(n): info(n) for n in FDI_ALL}), js_json(hist)


# Экранирование значений, которые пишет ЧЕЛОВЕК, перед вставкой в innerHTML.
# Экранирование в JSON (замена "</") спасает только сам тег <script>, но не
# HTML-парсер innerHTML: заметка вида "<img src=x onerror=…>" выполнялась бы
# при наведении на зуб (нашло ревью 08-08).
TESC_JS = """
function tesc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#39;'}[c];
  });
}
"""


def _sf_btns() -> str:
    """Кнопки поверхностей для инспектора: КАЖДАЯ несёт своё состояние.

    Флажков здесь больше нет намеренно: флажок отвечает «затронута или нет», а
    вопрос теперь другой — «чем именно». Форма фиши осталась на флажках, и это
    не разнобой: там одно состояние на все отмеченные, и выбор из пяти
    выпадающих списков ради этого был бы хуже."""
    return "".join(
        f"<button type='button' class='sfbtn' data-s='{k}' aria-pressed='false'>"
        f"{k} <small>{v}</small></button>" for k, v in TOOTH_SURFACES.items())


def _sf_state_opts() -> str:
    return ("<option value=''>— fără leziune</option>"
            + "".join(f"<option value='{k}'>{STATES[k]}</option>"
                      for k in tsvg.SURFACE_STATES))


def _sf_boxes(cls: str = "") -> str:
    return "".join(
        f"<label class='{cls}'><input type='checkbox' name='sf' value='{k}'>"
        f"{k} <small>{v}</small></label>" for k, v in TOOTH_SURFACES.items())


def _state_opts() -> str:
    return "".join(f"<option value='{k}'>{v}</option>" for k, v in STATES.items())


def card(tmap: dict, tooth_acts: list, doc_opts: str, base: str) -> str:
    """Компактная одонтограмма в фише: обе дуги, оба вида, диалог по клику.

    ⚠️ ОБА вида уезжают в страницу сразу, переключает их CSS. Догрузка по
    запросу сэкономила бы ~58 КБ, но потребовала бы маршрута и показывала бы
    пустую дугу на первом щелчке — на 127.0.0.1 это плохой размен.
    """
    # молочный прикус раскрывается сам, если по нему уже есть записи: детская
    # фиша не должна требовать лишнего клика, взрослая — видеть лишний ряд
    milk_open = " open" if any(n in tmap for n in FDI_MILK_UPPER + FDI_MILK_LOWER) else ""
    teeth_json, thist_json = tooth_data(tmap, tooth_acts)
    return f"""<div class='fcard odo' id='odo' data-view='frontal'>
<div class='odo-head'>
  <h3>Formula dentară <small>· notație FDI · click pe dinte</small></h3>
  <div class='odo-actions'>{view_switch()}
    <a class='odo-more' href='{base}/odontograma'>{_ic('eye')} Detaliat</a></div>
</div>
<div class='odo-view v-frontal'>{_arch_wrap(tmap, False, tip=True, click='openTooth')}</div>
<div class='odo-view v-ocluzal'>{_arch_wrap(tmap, True, tip=True, click='openTooth')}
  <p class='hint occ-hint'>Suprafața vestibulară este spre exteriorul arcadei;
    cea linguală/palatinală — spre mijloc.</p>
</div>
<details class='milk'{milk_open}>
  <summary>{_ic('milk')} Dentiție temporară (dinți de lapte)</summary>
  <div class='odo-view v-frontal'>{_milk_wrap(tmap, False, tip=True, click='openTooth')}</div>
  <div class='odo-view v-ocluzal'>{_milk_wrap(tmap, True, tip=True, click='openTooth')}</div>
</details>
<div class='tleg odo-view v-frontal'>{_legend(False)}</div>
<div class='tleg odo-view v-ocluzal'>{_legend(True)}</div></div>
<div id='toothtip' class='toothtip'><b class='tt-n'></b><div class='tt-s'></div>
  <div class='tt-d'></div></div>
<dialog id='toothdlg'>
  <div class='dlg-head'><span id='t_title'>Dinte</span>
    <button type='button' onclick="document.getElementById('toothdlg').close()">{_ic('close')}</button></div>
  <form class='dlg-form' method='post' action='{base}/tooth'>
    <input type='hidden' name='tooth' id='t_num'>
    <input type='hidden' name='state0' id='t_state0'>
    <select name='state' id='t_state'>{_state_opts()}</select>
    <select name='doctor' id='t_doc'><option value=''>Medic —</option>{doc_opts}</select>
    <div class='sfrow' id='t_sf'>{_sf_boxes()}</div>
    <input name='note' id='t_note' placeholder='Notiță (opțional)' maxlength='120'>
    <button>{_ic('save')} Salvează</button>
  </form>
  <div id='t_hist' class='thist'></div>
</dialog>
<script>
const TEETH = {teeth_json};
const STATE_RO = {js_json(STATES)};
const THIST = {thist_json};
{TESC_JS}
function openTooth(n) {{
  const t = TEETH[String(n)] || {{state: 'ok', note: '', doctor: ''}};
  document.getElementById('t_title').textContent = 'Dinte ' + n;
  document.getElementById('t_num').value = n;
  document.getElementById('t_state').value = t.state;
  // ВАЖНО: чем диалог ЗАРЯЖЕН, знает только он — по этому полю сервер отличает
  // «врач сменил состояние» от «врач его не трогал». Сравнение с базой делало
  // тот же ввод то правкой, то пустышкой — по тому, чего врач не видит
  document.getElementById('t_state0').value = t.state;
  document.getElementById('t_doc').value = t.doctor || '';
  document.getElementById('t_note').value = t.note;
  const sf = (t.sf || '');
  document.querySelectorAll('#t_sf input').forEach(function (b) {{
    b.checked = sf.indexOf(b.value) >= 0;
  }});
  const h = THIST[String(n)] || [];
  document.getElementById('t_hist').innerHTML = h.length
    ? '<div class="th-t">Istoria dintelui</div>' + h.map(function (x) {{
        return '<div class="th-r"><span>' + tesc(x.at) + '</span>'
               + tesc(x.text) + '</div>';
      }}).join('')
    : '';
  document.getElementById('toothdlg').showModal();
}}
// подсказка зуба: одна плавающая карточка на всю дугу, позиционируется у зуба
const TIP = document.getElementById('toothtip');
function toothTip(ev, n) {{
  const t = TEETH[String(n)];
  if (!t || (t.state === 'ok' && !t.note && !t.doctor)) {{ TIP.style.display = 'none'; return; }}
  TIP.querySelector('.tt-n').textContent = 'Dinte ' + n;
  TIP.querySelector('.tt-s').textContent = STATE_RO[t.state] || t.state;
  TIP.querySelector('.tt-d').innerHTML =
    (t.at ? '<div>Actualizat: <b>' + tesc(t.at) + '</b></div>' : '') +
    (t.doctor ? '<div>Medic: <b>' + tesc(t.doctor) + '</b></div>' : '') +
    (t.sfx ? '<div>Suprafețe: <b>' + tesc(t.sfx) + '</b></div>' : '') +
    (t.note ? '<div class="tt-note">' + tesc(t.note) + '</div>' : '');
  const r = ev.currentTarget.getBoundingClientRect();
  TIP.style.display = 'block';
  const w = TIP.offsetWidth;
  let left = r.left + r.width / 2 - w / 2 + window.scrollX;
  left = Math.max(8, Math.min(left, document.documentElement.clientWidth - w - 8));
  TIP.style.left = left + 'px';
  TIP.style.top = (r.bottom + window.scrollY + 8) + 'px';
}}
function toothTipOff() {{ TIP.style.display = 'none'; }}
{VIEW_SCRIPT}
</script>"""


def page(patient: dict, tmap: dict, tooth_acts: list, doc_opts: str,
         base: str, sel: int | None) -> str:
    """Детальная одонтограмма: дуга крупно + постоянный инспектор справа.

    Модалки здесь нет НАМЕРЕННО: она закрывает собой дугу, а весь смысл этого
    экрана — видеть зуб и соседей одновременно. Клик выбирает, инспектор
    показывает; рисунок в инспекторе — КЛОН уже нарисованного зуба из видимой
    дуги, поэтому второй набор SVG (52 зуба) в страницу не едет и не может
    разойтись с первым.

    ⚠️ Форма уходит в ТОТ ЖЕ маршрут, что и диалог фиши, теми же полями —
    отдельной проверки поверхностей и состояния здесь нет и заводить её нельзя.
    Отличие одно: скрытое поле `back`, по которому маршрут возвращает сюда, а
    не в фишу.
    """
    e = html.escape
    milk_open = " open" if any(n in tmap for n in FDI_MILK_UPPER + FDI_MILK_LOWER) else ""
    teeth_json, thist_json = tooth_data(tmap, tooth_acts)
    name = e(patient["name"])
    sel_js = str(sel) if sel in FDI_ALL else "0"
    return f"""<div class='odop odo' id='odo' data-view='frontal'>
<div class='odop-top'>
  <a class='odop-back' href='{base}'>{_ic('pat')} {name}</a>
  <h2>Odontogramă <small>· notație FDI</small></h2>
  <div class='odo-actions'>{view_switch()}
    <button type='button' class='odo-more' onclick='window.print()'>{_ic('print')} Printează</button>
  </div>
</div>
<div class='odop-grid'>
  <div class='odop-main'>
    <div class='fcard'>
      <div class='odo-view v-frontal'>{_arch_wrap(tmap, False, tip=False, click='selTooth')}</div>
      <div class='odo-view v-ocluzal'>{_arch_wrap(tmap, True, tip=False, click='selTooth')}
        <p class='hint occ-hint'>Suprafața vestibulară este spre exteriorul arcadei;
          cea linguală/palatinală — spre mijloc.</p>
      </div>
      <details class='milk'{milk_open}>
        <summary>{_ic('milk')} Dentiție temporară (dinți de lapte)</summary>
        <div class='odo-view v-frontal'>{_milk_wrap(tmap, False, tip=False, click='selTooth')}</div>
        <div class='odo-view v-ocluzal'>{_milk_wrap(tmap, True, tip=False, click='selTooth')}</div>
      </details>
      <div class='tleg odo-view v-frontal'>{_legend(False)}</div>
      <div class='tleg odo-view v-ocluzal'>{_legend(True)}</div>
    </div>
  </div>
  <aside class='odop-side'>
    <div class='fcard insp'>
      <div class='insp-t'>Dinte selectat</div>
      <div class='insp-n'><b id='i_num'>—</b><span id='i_jaw'></span></div>
      <div class='insp-pic' id='i_pic'>
        <span class='lb lb-v'>V</span><span class='lb lb-l'>L</span>
        <span class='lb lb-m'>M</span><span class='lb lb-d'>D</span>
      </div>
      <form class='dlg-form insp-f' method='post' action='{base}/tooth'>
        <input type='hidden' name='tooth' id='i_tooth'>
        <input type='hidden' name='back' value='odontograma'>
        <input type='hidden' name='sfst' id='i_sfst'>
        <div class='insp-t'>Suprafețe</div>
        <div class='sfbtns' id='i_sf'>{_sf_btns()}</div>
        <div class='sfstate' id='i_sfrow'>
          <label for='i_sfstate'>Starea suprafeței <b id='i_sflab'>—</b></label>
          <select id='i_sfstate'>{_sf_state_opts()}</select>
        </div>
        <div class='insp-t'>Starea dintelui</div>
        <select name='state' id='i_state'>{_state_opts()}</select>
        <select name='doctor' id='i_doc'><option value=''>Medic —</option>{doc_opts}</select>
        <input name='note' id='i_note' placeholder='Notiță (opțional)' maxlength='120'>
        <button id='i_save' disabled>{_ic('save')} Salvează</button>
      </form>
      <div id='i_hist' class='thist'></div>
    </div>
  </aside>
</div></div>
<script>
const TEETH = {teeth_json};
const STATE_RO = {js_json(STATES)};
const THIST = {thist_json};
const JAW_RO = {{sus: 'Maxilar', jos: 'Mandibular'}};
window.SEL_TOOTH = 0;
// SF — состояния поверхностей ВЫБРАННОГО зуба, SF_SEL — какая сейчас правится.
// Скрытое поле собирается из SF перед отправкой: сервер разбирает ту же строку,
// что кладёт в базу (`M:carie,O:obturatie`), и второго формата не появляется.
let SF = {{}}, SF_SEL = null;
const SF_ORDER = {js_json(list(TOOTH_SURFACES))};
{TESC_JS}
function paintSurfaces() {{
  var parts = [];
  SF_ORDER.forEach(function (k) {{ if (SF[k]) parts.push(k + ':' + SF[k]); }});
  document.getElementById('i_sfst').value = parts.join(',');
  document.querySelectorAll('#i_sf .sfbtn').forEach(function (b) {{
    var k = b.dataset.s, st = SF[k] || '';
    b.className = 'sfbtn' + (st ? ' on sf-' + st : '') + (k === SF_SEL ? ' sel' : '');
    b.setAttribute('aria-pressed', st ? 'true' : 'false');
  }});
  var row = document.getElementById('i_sfrow');
  row.style.display = SF_SEL ? 'block' : 'none';
  if (SF_SEL) {{
    document.getElementById('i_sflab').textContent = SF_SEL;
    document.getElementById('i_sfstate').value = SF[SF_SEL] || '';
  }}
}}
document.addEventListener('click', function (ev) {{
  var b = ev.target.closest ? ev.target.closest('#i_sf .sfbtn') : null;
  if (!b) return;
  SF_SEL = b.dataset.s;
  paintSurfaces();
}});
document.addEventListener('change', function (ev) {{
  if (ev.target.id !== 'i_sfstate' || !SF_SEL) return;
  if (ev.target.value) SF[SF_SEL] = ev.target.value; else delete SF[SF_SEL];
  paintSurfaces();
}});
function selTooth(n) {{
  const t = TEETH[String(n)];
  if (!t) return;
  window.SEL_TOOTH = n;
  const box = document.getElementById('odo');
  const view = box.dataset.view === 'ocluzal' ? '.v-ocluzal' : '.v-frontal';
  box.querySelectorAll('.tooth-btn.sel').forEach(function (b) {{
    b.classList.remove('sel');
  }});
  box.querySelectorAll('.tooth-btn[data-n="' + n + '"]').forEach(function (b) {{
    b.classList.add('sel');
  }});
  document.getElementById('i_num').textContent = n;
  document.getElementById('i_jaw').textContent = JAW_RO[t.jaw] || '';
  // рисунок — клон уже отрисованного зуба из ВИДИМОЙ дуги; ссылки на
  // градиент и обтравку остаются рабочими, они ищутся по всему документу
  const pic = document.getElementById('i_pic');
  pic.querySelectorAll('svg').forEach(function (s) {{ s.remove(); }});
  const src = box.querySelector(view + ' .tooth-btn[data-n="' + n + '"] svg');
  if (src) pic.appendChild(src.cloneNode(true));
  pic.dataset.jaw = t.jaw;
  pic.dataset.mez = t.mez;
  document.getElementById('i_tooth').value = n;
  document.getElementById('i_state').value = t.state;
  document.getElementById('i_doc').value = t.doctor || '';
  document.getElementById('i_note').value = t.note;
  document.getElementById('i_save').disabled = false;
  SF = {{}};
  for (var k in (t.sfst || {{}})) SF[k] = t.sfst[k];
  // ВАЖНО: поверхность выбирается СРАЗУ, иначе список её состояния скрыт до
  // первого клика по букве — а догадаться, что по букве надо кликать, неоткуда:
  // рядом стоит список состояния ЗУБА, и панель выглядит законченной
  SF_SEL = SF_ORDER.filter(function (k) {{ return SF[k]; }})[0] || 'O';
  paintSurfaces();
  const h = THIST[String(n)] || [];
  document.getElementById('i_hist').innerHTML = h.length
    ? '<div class="th-t">Istoric</div>' + h.map(function (x) {{
        return '<div class="th-r"><span>' + tesc(x.at) + '</span>'
               + tesc(x.text) + '</div>';
      }}).join('')
    : '<p class="hint" style="margin:0">— fără înregistrări —</p>';
}}
{VIEW_SCRIPT}
// зуб из адреса: после сохранения маршрут возвращает сюда с ?t=<номер>,
// и выбор переживает перезагрузку страницы
if ({sel_js}) selTooth({sel_js});
</script>"""
