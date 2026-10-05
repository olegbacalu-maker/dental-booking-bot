"""Фирменный знак DentPilot — одна геометрия для иконки и для интерфейса.

Иконка на рабочем столе и знак в шапке программы должны быть ОДНИМ знаком.
Нарисованные по отдельности, они разойдутся при первой же правке — поэтому
фигуры описаны здесь числами, а PIL (сборка .ico) и SVG (интерфейс) остаются
лишь двумя способами их нарисовать.

⭐ С 05.10.2026 — знак v2 (логотип Олега, перерисованный в вектор): тот же
контурный зуб, что на сайте (путь `TOOTH` — дословно путь из шапки
site\\index.html), и лента со стрелкой-«пилотом», прорезающая его у шейки.
Слово: «Dent» — синим Safir, «Pilot» — бирюзой. Песочница с вариантами —
D:\\DentProject\\sandbox\\brand-v2 (там же отвергнутые оттенки и почему).
Меняется путь зуба — меняется и на сайте, иначе знаки снова разъедутся.

Две системы координат: знак — 284x220 (шире высоты: стрелка уходит вправо),
иконка — 256x256, родная для .ico. Модуль намеренно без зависимостей: его
импортирует и приложение, и лаунчер до сборки приложения, и скрипт сборки.
"""
from __future__ import annotations

import math
import re

VB = 256
TEAL = (14, 159, 138)          # #0E9F8A — фирменный цвет сайта
WHITE = (255, 255, 255)
PLATE_R = 68                   # скругление квадрата иконки: 9px на 34px, как на сайте
# подложка иконки — бирюза сверху-слева в глубокую бирюзу снизу-справа
PLATE_TOP, PLATE_BOTTOM = (20, 184, 163), (10, 124, 128)
SAFIR = "#1E3A8A"              # «Dent». ⛔ НЕ #2563EB: это синий «информации» и тема «Albastru»
TEAL_LIGHT, TEAL_MID, TEAL_DEEP = "#2ED3BF", "#0E9F8A", "#0A7480"

# Зуб в системе 24x24 (как у иконок сайта): коронка и два корня одним контуром.
TOOTH = ("M8.2 3.8C5.9 3.8 4 5.7 4 8.2c0 1.9.8 3.2 1.4 4.7.7 1.7 1 4.4 1.8 6.6.3.9 "
         "1.5.9 1.8 0 .6-1.9.8-4 1.6-5.2.6-.9 1.7-.9 2.3 0 .8 1.2 1 3.3 1.6 5.2.3.9 "
         "1.5.9 1.8 0 .8-2.2 1.1-4.9 1.8-6.6.6-1.5 1.4-2.8 1.4-4.7 0-2.5-1.9-4.4-4.2-4.4"
         "-1.1 0-1.9.5-3.1.5s-2-.5-3.2-.5z")

# ---- знак v2 (284x220) -------------------------------------------------------
MARK_W, MARK_H = 284, 220
TOOTH_K, TOOTH_TX, TOOTH_TY = 9.6, 4.0, 6.0     # зуб: x 42..196, y 42..202
TOOTH_SW = 2.25                                  # толщина ленты зуба, в сетке 24
# Лента по пропорциям макета: хвост левее зуба на ~четверть его ширины, проходит
# над выемкой между корнями и выходит у коронки справа (кубическая кривая).
SW_A, SW_C1, SW_C2, SW_B = (4, 160), (80, 152), (172, 118), (240, 64)
SW_MAX = 15.0                                    # ширина ленты у стрелки; к хвосту — 0
GAP = 7.0                                        # просвет в зубе вокруг ленты

# ---- иконка (256x256) --------------------------------------------------------
ICON_MARK_W = 196        # знак в иконке, ширина; толщина зуба там больше (2.6)
ICON_TOOTH_SW = 2.6
# ≤32 px (вкладка браузера, панель задач, заголовок окна): стрелка там — штрих,
# поэтому ТОЛЬКО зуб, крупнее и толще. Сравнение рядом — в песочнице brand-v2.
SMALL = (8.6, 2.4)       # масштаб 24-сетки, толщина
SMALL_MAX = 32


def hexc(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb


def tint(hex_color: str, a: float) -> str:
    """Цвет, разбавленный белым: a=0.06 — еле заметный оттенок фона."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return hexc(tuple(round(255 - (255 - v) * a) for v in (r, g, b)))


def _bez(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _swoosh(n: int = 90) -> list[tuple[float, float]]:
    """Лента от хвоста к голове залитым контуром (координаты знака)."""
    top, bot = [], []
    for i in range(n + 1):
        t = i / n
        x, y = _bez(SW_A, SW_C1, SW_C2, SW_B, t)
        x2, y2 = _bez(SW_A, SW_C1, SW_C2, SW_B, min(1, t + 1e-3))
        x1, y1 = _bez(SW_A, SW_C1, SW_C2, SW_B, max(0, t - 1e-3))
        ln = math.hypot(x2 - x1, y2 - y1) or 1
        nx, ny = -(y2 - y1) / ln, (x2 - x1) / ln
        w = SW_MAX * (t ** 0.75) / 2
        top.append((x + nx * w, y + ny * w))
        bot.append((x - nx * w, y - ny * w))
    return top + bot[::-1]


def _arrow() -> tuple[tuple[float, float], ...]:
    """Бумажный самолётик по касательной к концу ленты: остриё, крылья, выемка."""
    ux, uy = SW_B[0] - SW_C2[0], SW_B[1] - SW_C2[1]
    ln = math.hypot(ux, uy)
    ux, uy = ux / ln, uy / ln
    vx, vy = -uy, ux
    tip = (SW_B[0] + ux * 42, SW_B[1] + uy * 42)
    base = (tip[0] - ux * 58, tip[1] - uy * 58)
    left = (base[0] - vx * 27, base[1] - vy * 27)
    right = (base[0] + vx * 27, base[1] + vy * 27)
    return tip, left, right, SW_B


SWOOSH = _swoosh()
ARROW = _arrow()


def _d(points) -> str:
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points) + "Z"


def _mark_body(uid: str, ink: str | None, sw: float = TOOTH_SW) -> str:
    """Внутренность знака в координатах 284x220. ink=None — в цвете
    (градиенты), иначе одним цветом (`currentColor` или хекс). Просвет ленты —
    маской, по-настоящему прозрачный: знак ложится на любой фон."""
    sp = _d(SWOOSH)
    tip, left, right, notch = ARROW
    defs = (f'<mask id="{uid}k" maskUnits="userSpaceOnUse" x="0" y="0" '
            f'width="{MARK_W}" height="{MARK_H}"><rect width="{MARK_W}" height="{MARK_H}" '
            f'fill="#fff"/><path d="{sp}" fill="#000" stroke="#000" '
            f'stroke-width="{GAP * 2}" stroke-linejoin="round"/></mask>')
    if ink is None:
        defs += (f'<linearGradient id="{uid}t" x1="0" y1="0" x2="1" y2="1">'
                 f'<stop offset="0" stop-color="{TEAL_LIGHT}"/><stop offset=".55" '
                 f'stop-color="{TEAL_MID}"/><stop offset="1" stop-color="{TEAL_DEEP}"/>'
                 f'</linearGradient><linearGradient id="{uid}s" gradientUnits="userSpaceOnUse" '
                 f'x1="{SW_A[0]}" y1="{SW_A[1]}" x2="{tip[0]:.1f}" y2="{tip[1]:.1f}">'
                 f'<stop offset="0" stop-color="{TEAL_DEEP}"/><stop offset=".6" '
                 f'stop-color="{TEAL_MID}"/><stop offset="1" stop-color="{TEAL_LIGHT}"/>'
                 f'</linearGradient>')
        t_ink, s_ink = f"url(#{uid}t)", f"url(#{uid}s)"
        head = (f'<path d="{_d((left, tip, notch))}" fill="{TEAL_LIGHT}"/>'
                f'<path d="{_d((notch, tip, right))}" fill="{TEAL_DEEP}"/>')
    else:
        t_ink = s_ink = ink
        head = f'<path d="{_d((left, tip, right, notch))}" fill="{ink}"/>'
    tooth = (f'<path d="{TOOTH}" transform="translate({TOOTH_TX} {TOOTH_TY}) '
             f'scale({TOOTH_K})" fill="none" stroke="{t_ink}" stroke-width="{sw}" '
             f'stroke-linecap="round" stroke-linejoin="round"/>')
    return (f'<defs>{defs}</defs><g mask="url(#{uid}k)">{tooth}</g>'
            f'<path d="{sp}" fill="{s_ink}"/>{head}')


# Центровка знака в иконке (05.10, Олег: «на ярлыке значок не по центру, а
# смещён вниз и в сторону»). Рамка знака 284x220 рисунком занята НЕ по центру:
# над стрелкой и под зубом поля разные, и вписанная рамка сажала рисунок на
# 11 единиц ниже (на ярлыке 48 px — 15 px поля сверху против 10 снизу).
# Поэтому центрируется сам рисунок, по его краям (`_content_box`).
# ⚠️ Не по центру масс: масса — зуб, он левее середины, и центровка по ней
# уводила всю картинку вправо (поля 46/32 на 256) — то самое «в сторону».
# Сравнение трёх вариантов — sandbox\brand-v2 (05.10).


def _content_box(sw: float) -> tuple[float, float, float, float]:
    """Края рисунка знака (лево, верх, право, низ) в координатах 284x220:
    контур зуба с половиной толщины линии, лента и стрелка."""
    half = sw * TOOTH_K / 2
    pts = [(TOOTH_TX + x * TOOTH_K, TOOTH_TY + y * TOOTH_K) for x, y in _points(TOOTH)]
    left = min(x for x, _ in pts) - half
    right = max(x for x, _ in pts) + half
    top = min(y for _, y in pts) - half
    bottom = max(y for _, y in pts) + half
    for x, y in list(SWOOSH) + list(ARROW):
        left, right = min(left, x), max(right, x)
        top, bottom = min(top, y), max(bottom, y)
    return left, top, right, bottom


def _icon_place() -> tuple[float, float, float]:
    """Масштаб и сдвиг знака в иконке 256: (масштаб, x, y) для translate/scale."""
    m = ICON_MARK_W / MARK_W
    left, top, right, bottom = _content_box(ICON_TOOTH_SW)
    return m, VB / 2 - (left + right) / 2 * m, VB / 2 - (top + bottom) / 2 * m


def _icon_body(uid: str, small: bool) -> str:
    """Иконка 256x256: бирюзовый квадрат и белый знак (≤32 px — только зуб)."""
    plate = (f'<defs><linearGradient id="{uid}p" x1="0" y1="0" x2="1" y2="1">'
             f'<stop offset="0" stop-color="{hexc(PLATE_TOP)}"/><stop offset="1" '
             f'stop-color="{hexc(PLATE_BOTTOM)}"/></linearGradient></defs>'
             f'<rect width="{VB}" height="{VB}" rx="{PLATE_R}" fill="url(#{uid}p)"/>')
    if small:
        k, sw = SMALL
        off = (VB - 24 * k) / 2
        return (plate + f'<path d="{TOOTH}" transform="translate({off:.1f} {off:.1f}) '
                f'scale({k})" fill="none" stroke="#FFFFFF" stroke-width="{sw}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    s, x, y = _icon_place()
    return (plate + f'<g transform="translate({x:.1f} {y:.1f}) scale({s:.4f})">'
            f'{_mark_body(uid, "#FFFFFF", ICON_TOOTH_SW)}</g>')


def mark_svg(px: int | None = 34, cls: str = "", label: str = "DentPilot",
             flat: bool = False) -> str:
    """Знак как встроенный SVG.

    Без `flat` — ИКОНКА (квадрат с белым знаком), px — её сторона; px=None
    тянется по контейнеру (favicon). Мелкая (px ≤ 32 и favicon) — только зуб.

    ⭐ `flat=True` — знак БЕЗ собственной подложки, одним цветом
    `currentColor`, px — ширина. Нужен там, где знак лежит НА фирменном цвете
    клиники: своя бирюзовая подложка — тот самый зашитый хекс, который тема не
    перекрашивает, и на синей шапке она стала бы пятном.

    Внутри картинки нет ни ссылок, ни шрифтов: она одинаково работает в окне
    программы, в браузере и в data-URI. ⚠️ id внутри (маски, градиенты) берут
    приставку от `cls`: два знака на одной странице не должны делить маску.
    """
    klass = f' class="{cls}"' if cls else ""
    uid = "dp" + re.sub(r"[^a-z0-9]", "", (cls or "mark").lower())
    head = f'<svg{klass} xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}"'
    if flat:
        size = "" if px is None else f' width="{px}" height="{round(px * MARK_H / MARK_W)}"'
        return (f'{head} viewBox="0 0 {MARK_W} {MARK_H}"{size}>'
                f'{_mark_body(uid, "currentColor")}</svg>')
    size = "" if px is None else f' width="{px}" height="{px}"'
    small = px is None or px <= SMALL_MAX
    return f'{head} viewBox="0 0 {VB} {VB}"{size}>{_icon_body(uid, small)}</svg>'


def color_mark_svg(px: int | None = None, uid: str = "dpc") -> str:
    """Знак в цвете (градиенты) — заставка, экран входа, сайт, баннеры."""
    size = "" if px is None else f' width="{px}" height="{round(px * MARK_H / MARK_W)}"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MARK_W} {MARK_H}"{size} '
            f'role="img" aria-label="DentPilot">{_mark_body(uid, None)}</svg>')


# ---- знак + слово (заставка) ---------------------------------------------------
LOCKUP_CSS = (
    ".dp-lockup{display:flex;flex-direction:column;align-items:center;gap:10px}"
    ".dp-lockup svg{width:290px;height:auto}"
    # шрифт — страницы (заставка объявляет Inter сама): фрагмент шрифтов не просит
    ".dp-wm{font-family:inherit;font-weight:800;letter-spacing:-.035em;"
    "line-height:1;font-size:70px}"
    f".dp-wm .d{{color:{SAFIR}}}"
    ".dp-wm .p{background:linear-gradient(100deg,#12B3A0 0%,#0E9F8A 45%,#0A7C88 100%);"
    "-webkit-background-clip:text;background-clip:text;color:transparent}")


def lockup_html() -> str:
    """Знак над словом «DentPilot». ⚠️ Слово набрано шрифтом Inter — страница
    обязана его объявить (layout.fonts_css или встроенный, как в заставке)."""
    return (f'<div class="dp-lockup">{color_mark_svg(uid="dplk")}'
            '<div class="dp-wm"><span class="d">Dent</span><span class="p">Pilot</span></div></div>')


# ---- фон заставки и экранов входа ----------------------------------------------
# Волны и бледный зуб — цветом `--dp-c` (цвет темы клиники): на бирюзовой теме
# фон совпадает с заставкой, на синей становится синим. Рисуется кодом, а не
# картинкой: резко на любом мониторе и не весит ничего.
# ⚠️ Цвет — через style, а не атрибутом: var() в атрибуте SVG не разбирается.
BACKDROP_CSS = (
    ".dp-bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}"
    ".dp-bg svg{width:100%;height:100%}")


def backdrop_svg() -> str:
    c = "stop-color:var(--dp-c)"
    return (
        '<div class="dp-bg" aria-hidden="true"><svg viewBox="0 0 1280 824" '
        'preserveAspectRatio="xMidYMid slice"><defs>'
        f'<linearGradient id="dpw1" x1="0" y1="0" x2="1" y2="1"><stop offset="0" style="{c};stop-opacity:.30"/>'
        f'<stop offset="1" style="{c};stop-opacity:0"/></linearGradient>'
        f'<linearGradient id="dpw2" x1="0" y1="1" x2="1" y2="0"><stop offset="0" style="{c};stop-opacity:.34"/>'
        f'<stop offset=".7" style="{c};stop-opacity:.04"/></linearGradient>'
        f'<linearGradient id="dpw3" x1="1" y1="1" x2="0" y2="0"><stop offset="0" style="{c};stop-opacity:.28"/>'
        f'<stop offset="1" style="{c};stop-opacity:0"/></linearGradient>'
        '<filter id="dpsoft"><feGaussianBlur stdDeviation="18"/></filter></defs>'
        '<path d="M0 0H430C330 120 230 260 0 330Z" fill="url(#dpw1)" filter="url(#dpsoft)"/>'
        '<path d="M0 520C210 470 420 600 560 824H0Z" fill="url(#dpw2)" filter="url(#dpsoft)"/>'
        '<path d="M0 610C260 560 470 690 640 824" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="2"/>'
        '<path d="M1280 610C1060 640 880 740 760 824H1280Z" fill="url(#dpw3)" filter="url(#dpsoft)"/>'
        '<path d="M1280 650C1080 680 920 760 820 824" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="2"/>'
        '<path d="M0 250C140 200 300 90 380 0" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="2"/>'
        f'<path d="{TOOTH}" transform="translate(905 150) scale(22)" fill="#fff" fill-opacity=".35" '
        'style="stroke:var(--dp-c);stroke-opacity:.10" stroke-width="1.4" stroke-linejoin="round"/>'
        '</svg></div>')


# ---- PNG и .ico (PIL) -------------------------------------------------------------
_PNG: dict[tuple[int, bool], bytes] = {}


def png(size: int, opaque: bool = False) -> bytes:
    """Тот же знак в PNG — для значка на домашнем экране телефона.

    ⛔ SVG тут не годится, хотя во вкладке браузера работает: `apple-touch-icon`
    его не понимает вовсе, а в манифесте PNG — единственный формат, который
    берут все. Поэтому знак рисуется дважды из ОДНИХ чисел, а не сохраняется
    картинкой рядом: сохранённая разошлась бы с интерфейсом при первой же
    правке фигуры.

    ⚠️ `opaque=True` — для iOS. Значок со скруглёнными углами имеет ПРОЗРАЧНЫЕ
    углы, а iOS в `apple-touch-icon` прозрачность не поддерживает и заливает её
    ЧЁРНЫМ — фирменный знак приезжает на домашний экран в чёрной рамке, и
    заметно это только на самом айфоне. Поэтому там подложка — сплошной
    квадрат без скругления: скруглять углы iOS будет сам.

    Кеш — потому что рисование стоит дороже отдачи, а результат за жизнь
    процесса не меняется: фигура зашита, размеров три."""
    key = (size, opaque)
    if key not in _PNG:
        import io

        img = draw_pil(size, rounded=not opaque)
        if opaque:
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        _PNG[key] = buf.getvalue()
    return _PNG[key]


_NUM = re.compile(r"[MmLlHhVvCcSsZz]|-?(?:\d+\.?\d*|\.\d+)")


def _points(d: str, steps: int = 14) -> list[tuple[float, float]]:
    """Контур пути в ломаную (24-сетка). Понимает M L H V C S Z в обоих
    регистрах — ровно то, из чего состоят пути иконок сайта; кривые Безье
    режутся на `steps` отрезков: на 1024 px излом не виден."""
    tok = _NUM.findall(d)
    pts: list[tuple[float, float]] = []
    x = y = 0.0
    sx = sy = 0.0
    cx2 = cy2 = None            # вторая опорная прошлой кривой — для S
    cmd = ""
    i = 0

    def num() -> float:
        nonlocal i
        i += 1
        return float(tok[i - 1])

    def cubic(x1, y1, x2, y2, x3, y3):
        for n in range(1, steps + 1):
            t = n / steps
            a, b, c, e = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
            pts.append((a * x + b * x1 + c * x2 + e * x3, a * y + b * y1 + c * y2 + e * y3))

    while i < len(tok):
        if tok[i].isalpha():
            cmd = tok[i]
            i += 1
            if cmd in "Zz":
                pts.append((sx, sy))
                x, y, cx2 = sx, sy, None
                continue
        rel = cmd.islower()
        bx, by = (x, y) if rel else (0.0, 0.0)
        c = cmd.upper()
        if c == "M":
            x, y = bx + num(), by + num()
            sx, sy, cx2 = x, y, None
            pts.append((x, y))
            cmd = "l" if rel else "L"       # дальше пары чисел — линии
        elif c == "L":
            x, y, cx2 = bx + num(), by + num(), None
            pts.append((x, y))
        elif c == "H":
            x, cx2 = bx + num(), None
            pts.append((x, y))
        elif c == "V":
            y, cx2 = by + num(), None
            pts.append((x, y))
        elif c == "C":
            x1, y1, x2, y2 = bx + num(), by + num(), bx + num(), by + num()
            x3, y3 = bx + num(), by + num()
            cubic(x1, y1, x2, y2, x3, y3)
            x, y, cx2, cy2 = x3, y3, x2, y2
        elif c == "S":
            x1, y1 = (2 * x - cx2, 2 * y - cy2) if cx2 is not None else (x, y)
            x2, y2, x3, y3 = bx + num(), by + num(), bx + num(), by + num()
            cubic(x1, y1, x2, y2, x3, y3)
            x, y, cx2, cy2 = x3, y3, x2, y2
        else:
            raise ValueError(f"brand: команда пути {cmd!r} не поддержана")
    return pts


def _stroke(d, pts, width: float, fill: int) -> None:
    """Толстая линия по ломаной со скруглёнными стыками. Кружок в каждой
    вершине обязателен: joint="curve" у PIL оставляет между отрезками
    толстой линии волосяные щели цвета фона."""
    d.line(pts, fill=fill, width=max(1, round(width)))
    r = width / 2
    for x, y in pts:
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def draw_pil(size: int, small: bool | None = None, rounded: bool = True):
    """Иконка средствами PIL — для .ico при сборке и для png() в работе.

    PIL не сглаживает края, поэтому знак рисуется вчетверо крупнее и
    уменьшается: иначе контур на 48 px шёл бы лесенкой. `small` — только зуб;
    по умолчанию для size ≤ 32. `rounded=False` — квадрат без скругления (iOS).

    Импорт PIL внутри функции: модуль зовёт и скрипт сборки, которому не нужно
    приложение, и брать зависимость на весь модуль ради двух функций незачем.
    ⚠️ В exe PIL всё равно едет (его же просит загрузка снимков в фише), так
    что png() в собранной программе работает — и это проверяет smoke_exe."""
    from PIL import Image, ImageDraw

    ss = 4
    big = size * ss
    s = big / float(VB)
    # подложка: диагональный градиент — 2x2 растянутые сглаживанием
    mid = tuple((a + b) // 2 for a, b in zip(PLATE_TOP, PLATE_BOTTOM))
    grad = Image.new("RGB", (2, 2))
    grad.putdata([PLATE_TOP, mid, mid, PLATE_BOTTOM])
    plate = grad.resize((big, big), Image.BILINEAR).convert("RGBA")
    shape = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shape).rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=round(PLATE_R * s) if rounded else 0, fill=255)
    plate.putalpha(shape)

    ink = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(ink)
    if small if small is not None else size <= SMALL_MAX:
        k, sw = SMALL
        off = (VB - 24 * k) / 2
        _stroke(d, [((off + px * k) * s, (off + py * k) * s) for px, py in _points(TOOTH)],
                sw * k * s, 255)
    else:
        m, ox, oy = _icon_place()

        def at(px, py):                       # координаты знака -> пиксели холста
            return ((ox + px * m) * s, (oy + py * m) * s)

        tooth = [at(TOOTH_TX + px * TOOTH_K, TOOTH_TY + py * TOOTH_K)
                 for px, py in _points(TOOTH)]
        _stroke(d, tooth, ICON_TOOTH_SW * TOOTH_K * m * s, 255)
        sw_pts = [at(*p) for p in SWOOSH]
        # просвет: лента, раздутая на GAP, стирает зуб под собой
        d.polygon(sw_pts, fill=0)
        _stroke(d, sw_pts + sw_pts[:1], GAP * 2 * m * s, 0)
        d.polygon(sw_pts, fill=255)
        tip, left, right, notch = ARROW
        d.polygon([at(*left), at(*tip), at(*right), at(*notch)], fill=255)
    white = Image.new("RGBA", (big, big), WHITE + (255,))
    plate.paste(white, (0, 0), ink)
    return plate.resize((size, size), Image.LANCZOS)
