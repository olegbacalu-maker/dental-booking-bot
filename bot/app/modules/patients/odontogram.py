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


def bridge_norm(teeth: list) -> list | None:
    """Зубы моста в порядке дуги; None — мостом этот набор быть не может.

    Правила от врача пилота (08-21): одна дуга (верхняя ИЛИ нижняя — между
    челюстями мостов не бывает; через среднюю линию — бывают, фронтальные);
    зубы стоят ПОДРЯД без дырок (промежуток моста — это зуб конструкции с
    ролью corp, а не пропуск в списке); молочных мостов нет; минимум два зуба
    и хотя бы одна опора (консольный мост = опора + тело).
    ⚠️ Порядок нормализуется ЗДЕСЬ, по раскладке дуги: форма может прислать
    зубы в порядке кликов, а хранение и печать читают мост слева направо."""
    got = tsvg.parse_bridge(teeth) if not isinstance(teeth, list) else teeth
    if len(got) < 2 or len({n for n, _r in got}) != len(got):
        return None
    for arch in (FDI_UPPER, FDI_LOWER):
        if all(n in arch for n, _r in got):
            ordered = sorted(got, key=lambda t: arch.index(t[0]))
            idx = [arch.index(n) for n, _r in ordered]
            if idx != list(range(idx[0], idx[0] + len(idx))):
                return None                      # дырка в ряду
            if not any(r == "stalp" for _n, r in ordered):
                return None                      # мост без единой опоры
            return ordered
    return None                                  # смесь дуг или молочные

# Имя состояния берётся из `teeth_svg.STATE_RO` — там же, откуда его берёт
# летопись `db.set_tooth`. Своего словаря здесь нет НАМЕРЕННО.
STATES = tsvg.STATE_RO
# Отметки — второй вопрос о зубе («что с ним делают»), см. teeth_svg.TOOTH_MARKS.
# Словарь тот же по той же причине: имя состояния уже расходилось дважды.
MARKS = tsvg.MARK_RO


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


def _bmap(bridges: list) -> dict:
    """{fdi: (роль, материал)} — для подписи зуба. Разбор строкой из базы —
    ТОЛЬКО через tsvg.parse_bridge: второй разбор разошёлся бы с печатью."""
    out: dict = {}
    for b in bridges or ():
        for n, r in tsvg.parse_bridge(b["teeth"]):
            out[n] = (r, b.get("material") or "")
    return out


def bridges_json(bridges: list) -> str:
    """Мосты для браузера: скобки рисует JS по кнопкам зубов (drawBridges) —
    дуга живёт в CSS-grid с переменным зазором, и серверный расчёт координат
    разъезжался бы с каждым медиа-запросом."""
    rows = []
    for b in bridges or ():
        t = tsvg.parse_bridge(b["teeth"])
        if t:
            rows.append({"id": b["id"], "teeth": t,
                         "material": b.get("material") or ""})
    return js_json(rows)


# Скобка (acoladă) моста — общий скрипт фиши и детальной страницы. Рисуется
# ПО КНОПКАМ (offsetLeft/offsetTop внутри .arch): устойчиво к зазору сетки,
# ширине окна и обоим видам; скрытый вид пропускается и дорисовывается при
# переключении (вызов из VIEW_SCRIPT) и на resize.
BRIDGE_DRAW_JS = """
function drawBridges() {
  document.querySelectorAll('.br-arc').forEach(function (x) { x.remove(); });
  /* typeof, а НЕ window.BRIDGES: на детальной странице список объявлен const,
     а top-level const свойства window не создаёт — охрана через window молча
     выключала рисование целиком (поймано при первом же показе) */
  if (typeof BRIDGES === 'undefined' || !BRIDGES.length) return;
  document.querySelectorAll('#odo .arch').forEach(function (arch) {
    if (!arch.offsetParent) return;
    var btn = {};
    arch.querySelectorAll('.tooth-btn').forEach(function (b) {
      btn[b.dataset.n] = b;
    });
    BRIDGES.forEach(function (br) {
      var bs = br.teeth.map(function (t) { return btn[String(t[0])]; });
      if (bs.some(function (b) { return !b; })) return;
      var L = Math.min.apply(null, bs.map(function (b) { return b.offsetLeft; }));
      var R = Math.max.apply(null, bs.map(function (b) {
        return b.offsetLeft + b.offsetWidth; }));
      if (R - L < 8) return;
      var lower = arch.classList.contains('lower');
      var el = document.createElement('div');
      el.className = 'br-arc' + (lower ? ' lo' : '');
      el.style.left = L + 'px';
      el.style.width = (R - L) + 'px';
      /* --arc (вид ocluzal) двигает зуб transform-ом, а transform offsetTop
         НЕ меняет — без поправки скобка ложилась бы НА поднятые зубы дуги */
      var arcOf = function (b) {
        var v = parseFloat(b.style.getPropertyValue('--arc'));
        return isNaN(v) ? 0 : v;
      };
      if (lower) {
        el.style.top = (Math.max.apply(null, bs.map(function (b) {
          return b.offsetTop + b.offsetHeight + arcOf(b); })) + 2) + 'px';
      } else {
        el.style.top = (Math.min.apply(null, bs.map(function (b) {
          return b.offsetTop + arcOf(b); })) - 14) + 'px';
      }
      var lbl = document.createElement('span');
      lbl.textContent = br.material || 'punte';
      el.appendChild(lbl);
      el.title = 'Punte ' + br.teeth[0][0] + '-'
                 + br.teeth[br.teeth.length - 1][0]
                 + (br.material ? ' (' + br.material + ')' : '');
      arch.appendChild(el);
    });
  });
}
drawBridges();
window.addEventListener('resize', drawBridges);
"""


def _btn(n: int, tmap: dict, *, lower: bool = False, milk: bool = False,
         occ: bool = False, tip: bool = True, click: str = "openTooth",
         arc: float = 0.0, bmap: dict | None = None) -> str:
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
    mk = tsvg.mark_list((t["marks"] if t else "") or "")
    # поверхности дописываются ПОСЛЕ заметки: подпись «11 · Carie · test»
    # читают и человек, и проверка, и её формат менять незачем.
    sf_txt = sf_text(sfmap, sf)
    # мост — в подписи зуба наравне с отметкой: скобка говорит «здесь мост»,
    # а title отвечает, КЕМ этот зуб в нём стоит (опора или тело)
    br = (bmap or {}).get(n)
    br_txt = (f" · Punte: {tsvg.BRIDGE_RO[br[0]]}"
              + (f" ({br[1]})" if br[1] else "") if br else "")
    title = (f"{n} · {STATES.get(st, st)}"
             + "".join(f" · {MARKS[m]}" for m in mk)
             + br_txt
             + (f" · {note}" if note else "")
             + (f" · {sf_txt}" if sf_txt else ""))
    num = f"<span class='num'>{n}</span>"
    if occ:
        svg = tsvg.occlusal_svg(n, st, width=38 if milk else 52,
                                interactive=True, surfaces=sfmap, marks=mk)
    else:
        svg = tsvg.tooth_svg(n, st, width=28 if milk else 38, interactive=True,
                             surfaces=sfmap, marks=mk)
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


def _arch_wrap(tmap: dict, occ: bool, *, tip: bool, click: str,
               bmap: dict | None = None) -> str:
    cls = " occ" if occ else ""
    n_up, n_lo = len(FDI_UPPER), len(FDI_LOWER)
    up = "".join(_btn(n, tmap, occ=occ, tip=tip, click=click, bmap=bmap,
                      arc=arc_offset(i, n_up, lower=False) if occ else 0.0)
                 for i, n in enumerate(FDI_UPPER))
    lo = "".join(_btn(n, tmap, lower=True, occ=occ, tip=tip, click=click,
                      bmap=bmap,
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
    квадрат: так видно, чем «коронка» отличается от «пломбы», без словаря.

    ⚠️ Отметки идут ТЕМ ЖЕ рядом, но на здоровом зубе: иначе «в лечении»
    выглядело бы восьмым состоянием — ровно тем недоразумением, из-за которого
    кариес и лечение вытесняли друг друга (08-17). Разделитель показывает, что
    это другой вопрос о зубе."""
    draw = ((lambda k, m=(): tsvg.occlusal_svg(36, k, width=26, marks=m)) if occ
            else (lambda k, m=(): tsvg.tooth_svg(36, k, width=20, marks=m)))
    return ("".join(f"<span class='lg'>{draw(k)} {v}</span>"
                    for k, v in STATES.items() if k != "ok")
            + "<span class='lg-sep'></span>"
            + "".join(f"<span class='lg'>{draw('ok', (k,))} {v}</span>"
                      for k, v in MARKS.items()))


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
    // надо перерисовать — иначе сверху остаётся лицевой рисунок.
    // !BR_MODE: в режиме «Punte nouă» selTooth перехвачен в brToggle, и
    // переключение вида молча вбрасывало бы SEL_TOOTH в состав моста
    if (window.selTooth && window.SEL_TOOTH && !window.BR_MODE)
      selTooth(window.SEL_TOOTH);
    // скобки мостов меряются по кнопкам ВИДИМОЙ дуги — перерисовать
    if (window.drawBridges) drawBridges();
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
                    "sf": "", "sfx": "", "sfst": {}, "mk": [], "mkx": ""}
        sfmap = tsvg.surface_map(t["state"], t["surfaces"] or "",
                                 (t["surface_states"] or ""))
        mk = tsvg.mark_list(t["marks"] or "")
        return {**base, "state": t["state"], "note": t["note"] or "",
                "doctor": t["doctor"] or "", "sf": t["surfaces"] or "",
                "sfst": sfmap, "mk": mk,
                # готовая подпись отметок — по той же причине, что и `sfx`:
                # слова живут в MARK_RO, второй копии в JS быть не должно
                "mkx": ", ".join(MARKS[m] for m in mk),
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


def _mk_boxes() -> str:
    """Отметки зуба — флажками РЯДОМ со списком состояния, а не в нём.

    ⚠️ Скрытое `mk0` обязательно: снятый флажок не шлёт ничего, и без него
    сервер не отличил бы «сняли отметку» от «форма о ней не знает» (открытая
    вкладка со старой разметкой). Ровно та же болезнь, что у поверхностей,
    и лечится тем же — форма сообщает о САМОМ ФАКТЕ, что она в курсе."""
    return ("<input type='hidden' name='mk0' value='1'>"
            + "".join(f"<label class='mkbox'><input type='checkbox' name='mk' "
                      f"value='{k}'>{v}</label>" for k, v in MARKS.items()))


def card(tmap: dict, tooth_acts: list, doc_opts: str, base: str,
         bridges: list | None = None) -> str:
    """Компактная одонтограмма в фише: обе дуги, оба вида, диалог по клику.

    ⚠️ ОБА вида уезжают в страницу сразу, переключает их CSS. Догрузка по
    запросу сэкономила бы ~58 КБ, но потребовала бы маршрута и показывала бы
    пустую дугу на первом щелчке — на 127.0.0.1 это плохой размен.
    """
    # молочный прикус раскрывается сам, если по нему уже есть записи: детская
    # фиша не должна требовать лишнего клика, взрослая — видеть лишний ряд
    milk_open = " open" if any(n in tmap for n in FDI_MILK_UPPER + FDI_MILK_LOWER) else ""
    teeth_json, thist_json = tooth_data(tmap, tooth_acts)
    bmap = _bmap(bridges or [])
    return f"""<div class='fcard odo' id='odo' data-view='frontal'>
<div class='odo-head'>
  <h3>Formula dentară <small>· notație FDI · click pe dinte</small></h3>
  <div class='odo-actions'>{view_switch()}
    <a class='odo-more' href='{base}/odontograma'>{_ic('eye')} Detaliat</a></div>
</div>
<div class='odo-view v-frontal'>{_arch_wrap(tmap, False, tip=True, click='openTooth', bmap=bmap)}</div>
<div class='odo-view v-ocluzal'>{_arch_wrap(tmap, True, tip=True, click='openTooth', bmap=bmap)}
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
    <div class='mkrow' id='t_mk'>{_mk_boxes()}</div>
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
  const mk = (t.mk || []);
  document.querySelectorAll('#t_mk input[type=checkbox]').forEach(function (b) {{
    b.checked = mk.indexOf(b.value) >= 0;
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
  // ВАЖНО: отметка держит подсказку наравне с заметкой — здоровый зуб В РАБОТЕ
  // это законная запись, и без неё в условии подсказка молча не показывалась бы
  if (!t || (t.state === 'ok' && !t.note && !t.doctor && !(t.mk || []).length)) {{
    TIP.style.display = 'none'; return;
  }}
  TIP.querySelector('.tt-n').textContent = 'Dinte ' + n;
  TIP.querySelector('.tt-s').textContent = STATE_RO[t.state] || t.state;
  TIP.querySelector('.tt-d').innerHTML =
    (t.mkx ? '<div class="tt-mk">' + tesc(t.mkx) + '</div>' : '') +
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
var BRIDGES = {bridges_json(bridges or [])};
{BRIDGE_DRAW_JS}
{VIEW_SCRIPT}
</script>"""


def page(patient: dict, tmap: dict, tooth_acts: list, doc_opts: str,
         base: str, sel: int | None, bridges: list | None = None) -> str:
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
    bmap = _bmap(bridges or [])
    name = e(patient["name"])
    sel_js = str(sel) if sel in FDI_ALL else "0"
    return f"""<div class='odop odo' id='odo' data-view='frontal'>
<div class='odop-top'>
  <a class='odop-back' href='{base}'>{_ic('pat')} {name}</a>
  <h2>Odontogramă <small>· notație FDI</small></h2>
  <div class='odo-actions'>{view_switch()}
    <button type='button' class='odo-more' id='br_new'>{_ic('plus')} Punte nouă</button>
    <button type='button' class='odo-more' onclick='window.print()'>{_ic('print')} Printează</button>
  </div>
</div>
<div id='br_bar' class='br-bar' hidden>
  <b>Punte nouă:</b> click pe dinții punții (învecinați, aceeași arcadă)
  <span id='br_n'>—</span>
  <button type='button' class='pl-btn' id='br_cancel'>Anulează</button>
  <button type='button' class='pl-btn primary' id='br_go' disabled>Continuă</button>
</div>
<div class='odop-grid'>
  <div class='odop-main'>
    <div class='fcard'>
      <div class='odo-view v-frontal'>{_arch_wrap(tmap, False, tip=False, click='selTooth', bmap=bmap)}</div>
      <div class='odo-view v-ocluzal'>{_arch_wrap(tmap, True, tip=False, click='selTooth', bmap=bmap)}
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
      <div id='i_bridge' class='i-bridge' hidden>
        <span id='i_br_t'></span>
        <form method='post' id='i_br_del'
              onsubmit="return confirm('Ștergeți puntea?')">
          <button class='pl-btn'>Șterge puntea</button>
        </form>
      </div>
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
        <div class='mkrow' id='i_mk'>{_mk_boxes()}</div>
        <select name='doctor' id='i_doc'><option value=''>Medic —</option>{doc_opts}</select>
        <input name='note' id='i_note' placeholder='Notiță (opțional)' maxlength='120'>
        <button id='i_save' disabled>{_ic('save')} Salvează</button>
      </form>
      <div id='i_hist' class='thist'></div>
    </div>
  </aside>
</div></div>
<dialog id='brdlg'>
  <div class='dlg-head'><span>Punte nouă</span>
    <button type='button' onclick="document.getElementById('brdlg').close()">{_ic('close')}</button></div>
  <form class='dlg-form' method='post' action='{base}/bridge' id='br_form'>
    <input type='hidden' name='teeth' id='br_teeth'>
    <p class='hint' style='margin:0'>Click pe un dinte pentru a schimba rolul:
      stâlp (Co) sau corp de punte (D).</p>
    <div class='br-chips' id='br_chips'></div>
    <select name='doctor' id='br_doc'><option value=''>Medic —</option>{doc_opts}</select>
    <select name='material' id='br_mat'>
      <option value='metalo-ceramică'>Metalo-ceramică</option>
      <option value='zirconiu'>Zirconiu</option>
      <option value='ceramică'>Ceramică</option>
      <option value='metal'>Metal</option>
      <option value='acrilat'>Acrilat</option>
      <option value='alt'>Alt material…</option>
    </select>
    <input name='material_alt' id='br_alt' placeholder='Materialul punții'
           maxlength='40' style='display:none'>
    <button>{_ic('save')} Salvează puntea</button>
  </form>
</dialog>
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
  if (BR_MODE) {{ brToggle(n); return; }}
  const t = TEETH[String(n)];
  if (!t) return;
  window.SEL_TOOTH = n;
  // зуб в мосту: инспектор называет конструкцию и даёт её снять; клик по
  // зубу вне моста блок прячет
  const ib = document.getElementById('i_bridge');
  const inBr = BRIDGES.filter(function (br) {{
    return br.teeth.some(function (x) {{ return x[0] === n; }});
  }})[0];
  if (inBr) {{
    const role = inBr.teeth.filter(function (x) {{ return x[0] === n; }})[0][1];
    document.getElementById('i_br_t').textContent =
      'Punte ' + inBr.teeth[0][0] + '-' + inBr.teeth[inBr.teeth.length - 1][0]
      + (inBr.material ? ' (' + inBr.material + ')' : '')
      + ' - rol: ' + (BRIDGE_RO[role] || role);
    document.getElementById('i_br_del').action =
      BR_BASE + '/bridge/' + inBr.id + '/del';
    ib.hidden = false;
  }} else {{
    ib.hidden = true;
  }}
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
  const mk = (t.mk || []);
  document.querySelectorAll('#i_mk input[type=checkbox]').forEach(function (b) {{
    b.checked = mk.indexOf(b.value) >= 0;
  }});
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
// ---------- мост (punte): режим выбора зубов и диалог ролей ----------
// Жест — ровно как показал врач пилота (08-21): «selectezi 47-44 și meniu în
// care alegi punte». Пока режим включён, клик по зубу НЕ открывает инспектор
// (перехват в selTooth), а отмечает зуб; порядок и правила дуги проверяет
// сервер (bridge_norm) — здесь только удобство.
const BRIDGES = {bridges_json(bridges or [])};
const BRIDGE_RO = {js_json(tsvg.BRIDGE_RO)};
const BR_BASE = '{base}';
const ARCH_UP = {js_json(FDI_UPPER)}, ARCH_LO = {js_json(FDI_LOWER)};
// BR_MODE — на window: его читает ЧУЖОЙ скрипт (VIEW_SCRIPT, охрана
// переключения вида), а top-level let, как и const, свойства window
// не создаёт — та же ловушка, что у BRIDGES выше
window.BR_MODE = false;
let BR_SEL = [], BR_ROLES = {{}};
function brIdx(n) {{
  let i = ARCH_UP.indexOf(n);
  return i >= 0 ? i : 100 + ARCH_LO.indexOf(n);
}}
function brPaint() {{
  document.querySelectorAll('.tooth-btn').forEach(function (b) {{
    b.classList.toggle('br-pick',
                       BR_SEL.indexOf(parseInt(b.dataset.n, 10)) >= 0);
  }});
  const ord = BR_SEL.slice().sort(function (a, b) {{ return brIdx(a) - brIdx(b); }});
  document.getElementById('br_n').textContent = ord.length ? ord.join(', ') : '';
  document.getElementById('br_go').disabled = BR_SEL.length < 2;
}}
function brToggle(n) {{
  if (n > 50) return;               // молочных мостов не бывает (врач, 08-21)
  const i = BR_SEL.indexOf(n);
  if (i >= 0) BR_SEL.splice(i, 1); else BR_SEL.push(n);
  brPaint();
}}
function brStop() {{
  BR_MODE = false; BR_SEL = [];
  document.getElementById('br_bar').hidden = true;
  brPaint();
}}
document.getElementById('br_new').addEventListener('click', function () {{
  BR_MODE = true; BR_SEL = [];
  document.getElementById('br_bar').hidden = false;
  brPaint();
}});
document.getElementById('br_cancel').addEventListener('click', brStop);
document.getElementById('br_go').addEventListener('click', function () {{
  const ord = BR_SEL.slice().sort(function (a, b) {{ return brIdx(a) - brIdx(b); }});
  BR_ROLES = {{}};
  ord.forEach(function (n, i) {{
    // крайние — опоры по умолчанию; средний опорой делает клик по фишке
    // (пример врача: 47-45-43 опоры при теле 46/44)
    BR_ROLES[n] = (i === 0 || i === ord.length - 1) ? 'stalp' : 'corp';
  }});
  const box = document.getElementById('br_chips');
  box.innerHTML = '';
  ord.forEach(function (n) {{
    const b = document.createElement('button');
    b.type = 'button'; b.dataset.n = n;
    box.appendChild(b);
  }});
  brChips();
  document.getElementById('brdlg').showModal();
}});
function brChips() {{
  document.querySelectorAll('#br_chips button').forEach(function (b) {{
    const n = parseInt(b.dataset.n, 10);
    b.className = 'br-chip' + (BR_ROLES[n] === 'stalp' ? ' stalp' : '');
    b.textContent = n + ' - ' + (BRIDGE_RO[BR_ROLES[n]] || '');
  }});
}}
document.addEventListener('click', function (ev) {{
  const b = ev.target.closest ? ev.target.closest('#br_chips button') : null;
  if (!b) return;
  const n = parseInt(b.dataset.n, 10);
  BR_ROLES[n] = BR_ROLES[n] === 'stalp' ? 'corp' : 'stalp';
  brChips();
}});
document.getElementById('br_mat').addEventListener('change', function () {{
  document.getElementById('br_alt').style.display =
    this.value === 'alt' ? 'block' : 'none';
}});
document.getElementById('br_form').addEventListener('submit', function () {{
  const ord = BR_SEL.slice().sort(function (a, b) {{ return brIdx(a) - brIdx(b); }});
  document.getElementById('br_teeth').value = ord.map(function (n) {{
    return n + ':' + (BR_ROLES[n] || 'corp');
  }}).join(',');
}});
{VIEW_SCRIPT}
{BRIDGE_DRAW_JS}
// зуб из адреса: после сохранения маршрут возвращает сюда с ?t=<номер>,
// и выбор переживает перезагрузку страницы
if ({sel_js}) selTooth({sel_js});
</script>"""
