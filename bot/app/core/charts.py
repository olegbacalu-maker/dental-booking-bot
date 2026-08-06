"""Графики без единой библиотеки — инлайновый SVG.

Почему не Chart.js и не ECharts: программа ставится клинике одним exe и
работает без интернета, значит любая библиотека уехала бы ВНУТРЬ сборки. Это
плюс мегабайты к файлу, который клиника качает по мобильному интернету, и
чужой код в медицинской программе — ради четырёх фигур, каждая из которых
рисуется десятком строк. Здесь ровно эти четыре.

Живут в `core`, а не в модуле статистики: спарклайн нужен и панели дня, и
аналитике. Модуль, который импортирует соседний модуль, — начало той самой
паутины, ради ухода от которой код и раскладывали (см. `core/visits.py`).

Все размеры — в координатах viewBox, наружу отдаётся `width='100%'`: карточка
решает ширину сама, а числа внутри остаются целыми.
"""
from __future__ import annotations

import html
import math


def spark(series: list[int], tone: str, h: float = 26.0) -> str:
    """Мини-график в плитке: тренд или случайный день, без осей и подписей.

    Нормируется по СВОЕМУ максимуму — пять плиток на общей шкале (24 записи и
    2 неявки) дали бы прямую под потолком и прямую по полу, то есть ничего.
    Две недели нулей — это прямая по полу, а не пустое место: иначе плитка
    «Urgențe» в спокойной клинике вечно ниже соседних, и ряд рябит.

    Растягивается по ширине (`preserveAspectRatio='none'`), поэтому линии нужен
    non-scaling-stroke — иначе её размажет вместе с координатами.
    """
    if not series:
        return ""
    w, pad = 100.0, 3.0
    top = max(series) or 1
    step = w / max(len(series) - 1, 1)
    pts = " ".join(f"{i * step:.1f},{h - pad - (h - 2 * pad) * (v / top):.1f}"
                   for i, v in enumerate(series))
    return (f"<svg class='spark' viewBox='0 0 {w:.0f} {h:.0f}' width='100%' "
            f"height='{h:.0f}' preserveAspectRatio='none' aria-hidden='true'>"
            f"<polygon class='sp-a' points='0,{h:.0f} {pts} {w:.0f},{h:.0f}' "
            f"style='fill:{tone}'/>"
            f"<polyline class='sp-l' points='{pts}' vector-effect='non-scaling-stroke' "
            f"style='stroke:{tone}'/></svg>")


def line_days(labels: list[str], values: list[int], tone: str) -> str:
    """Дневной график с осью: сколько записей в каждый день периода.

    Подписи здесь настоящий текст, поэтому картинку НЕЛЬЗЯ растягивать по одной
    оси — буквы поехали бы вместе с ней. Масштабируется целиком (meet), а густые
    периоды прореживают подписи по оси X: 30 дат в ряд всё равно нечитаемы.
    """
    if not values:
        return "<p class='hint'>— nicio programare în perioadă —</p>"
    w, h = 640.0, 210.0
    l, r, t, b = 34.0, 8.0, 16.0, 26.0
    top = max(values) or 1
    # округляем потолок вверх до «круглого», чтобы подписи оси были人-читаемы
    step_y = max(1, math.ceil(top / 4))
    top_r = step_y * 4
    iw, ih = w - l - r, h - t - b
    dx = iw / max(len(values) - 1, 1)

    def x(i: int) -> float:
        return l + i * dx

    def y(v: float) -> float:
        return t + ih - ih * (v / top_r)

    grid, yl = [], []
    for k in range(5):
        val = step_y * k
        gy = y(val)
        grid.append(f"<line x1='{l:.1f}' y1='{gy:.1f}' x2='{w - r:.1f}' y2='{gy:.1f}'/>")
        yl.append(f"<text x='{l - 8:.1f}' y='{gy + 4:.1f}' text-anchor='end'>{val}</text>")
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    dots = "".join(f"<circle cx='{x(i):.1f}' cy='{y(v):.1f}' r='4'/>"
                   for i, v in enumerate(values))
    vals = "".join(
        f"<text class='ld-v' x='{x(i):.1f}' y='{y(v) - 11:.1f}' "
        f"text-anchor='middle'>{v}</text>" for i, v in enumerate(values))
    every = max(1, len(labels) // 8)     # густой период: подписи через одну и реже
    xl = "".join(
        f"<text x='{x(i):.1f}' y='{h - 7:.1f}' text-anchor='middle'>"
        f"{html.escape(s)}</text>"
        for i, s in enumerate(labels) if i % every == 0 or i == len(labels) - 1)
    return (f"<svg class='linechart' viewBox='0 0 {w:.0f} {h:.0f}' width='100%' "
            f"role='img' aria-label='Programări pe zile'>"
            f"<g class='lc-grid'>{''.join(grid)}</g>"
            f"<g class='lc-ax'>{''.join(yl)}{xl}</g>"
            f"<polygon class='lc-a' points='{l:.1f},{y(0):.1f} {pts} "
            f"{x(len(values) - 1):.1f},{y(0):.1f}' style='fill:{tone}'/>"
            f"<polyline class='lc-l' points='{pts}' style='stroke:{tone}'/>"
            f"<g class='lc-d' style='fill:{tone}'>{dots}</g>{vals}</svg>")


def donut(parts: list[tuple[str, int, str]], total_label: str = "Total") -> str:
    """Кольцо долей. `parts` = [(подпись, количество, цвет)].

    Доли считаются от суммы ПОКАЗАННЫХ частей, поэтому подписи процентов рядом
    всегда сходятся в 100 — а не «почти», как выходит при округлении каждой
    доли отдельно от какого-то внешнего итога.
    """
    total = sum(p[1] for p in parts)
    if not total:
        return "<p class='hint'>— încă fără date —</p>"
    r, c = 54.0, 70.0
    circ = 2 * math.pi * r
    segs, off = [], 0.0
    for _lbl, val, color in parts:
        if val <= 0:
            continue
        ln = circ * val / total
        segs.append(
            f"<circle cx='{c}' cy='{c}' r='{r}' fill='none' stroke='{color}' "
            f"stroke-width='20' stroke-dasharray='{ln:.2f} {circ - ln:.2f}' "
            f"stroke-dashoffset='{-off:.2f}' transform='rotate(-90 {c} {c})'/>")
        off += ln
    return (f"<svg class='donut' viewBox='0 0 140 140' width='140' height='140' "
            f"role='img' aria-label='{html.escape(total_label)}'>"
            + "".join(segs)
            + f"<text class='dn-v' x='{c}' y='{c - 2}' text-anchor='middle'>{total}</text>"
            f"<text class='dn-l' x='{c}' y='{c + 16}' text-anchor='middle'>"
            f"{html.escape(total_label)}</text></svg>")


def gauge(pct: int, tone: str) -> str:
    """Полукруг загрузки. Дуга — один путь, доля «выкушена» пунктиром: так
    анимация появления бесплатна, CSS двигает один stroke-dashoffset.

    Зазор пунктира — ДВЕ длины дуги, не одна: анимация стартует со сдвига в
    целую дугу, и при зазоре в одну длину узор успел бы повториться — на первом
    кадре мелькал бы ХВОСТ дуги вместо пустоты. CSS-старт (196) чуть больше
    настоящей длины (π·62 ≈ 194.8) и с запасом меньше периода узора.
    """
    pct = max(0, min(100, int(pct)))
    r, cx, cy = 62.0, 75.0, 78.0
    ln = math.pi * r
    path = f"M {cx - r} {cy} A {r} {r} 0 0 1 {cx + r} {cy}"
    return (f"<svg class='gauge' viewBox='0 0 150 96' width='100%' height='96' "
            f"role='img' aria-label='Grad de ocupare {pct}%'>"
            f"<path class='gg-bg' d='{path}'/>"
            f"<path class='gg-v' d='{path}' style='stroke:{tone}' "
            f"stroke-dasharray='{ln * pct / 100:.2f} {ln * 2:.2f}'/>"
            f"<text class='gg-t' x='{cx}' y='{cy - 10}' text-anchor='middle'>{pct}%</text>"
            f"</svg>")
