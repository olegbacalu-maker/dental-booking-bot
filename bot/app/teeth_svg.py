"""Одонтограмма DentPilot: ПАРАМЕТРИЧЕСКИЕ зубы вместо 32 картинок.

Каждый зуб собирается из базовых контуров (коронка + корни) по его классу и
челюсти, а состояние накладывается сверху отдельным слоем. Отсюда:
  · нет 32+ SVG-файлов в exe и нечему рассинхронизироваться;
  · цвет, коронка, имплант, пломба — параметры, а не новые файлы;
  · переход состояния можно анимировать: меняется слой, а не картинка.

Система координат (канон): коронка СВЕРХУ, корни ВНИЗ, viewBox 0 0 44 104.
Верхняя челюсть рисуется тем же кодом и переворачивается по вертикали, чтобы
обе дуги смотрели жевательными поверхностями друг на друга — как в кресле.

Толщина обводки 1.8px, скругления — по спецификации Олега 08-03.
"""
from __future__ import annotations

VB_W, VB_H = 44.0, 90.0
CX = VB_W / 2

# Длина корня — ОДИН параметр на всю систему. Контуры описаны в «длинной»
# сетке (шейка 42, кончик 96/100), а _ry() сжимает всё, что ниже шейки, до
# нужной длины: правится один коэффициент, а не тридцать две кривые.
NECK_Y = 42.0
ROOT_END, ROOT_END_CANINE = 82.0, 86.0
_K_ROOT = (ROOT_END - NECK_Y) / (96.0 - NECK_Y)
_K_ROOT_C = (ROOT_END_CANINE - NECK_Y) / (100.0 - NECK_Y)


def _ry(y: float, canine: bool = False) -> float:
    """Коронку не трогаем, корень сжимаем."""
    if y <= NECK_Y:
        return y
    return NECK_Y + (y - NECK_Y) * (_K_ROOT_C if canine else _K_ROOT)

# --- палитра состояний (макет «Odontogram System v1.0») ---
LINE = "#64748B"          # обводка здорового зуба
LINE_SOFT = "#94A3B8"     # внутренние детали (фиссуры, шейка)
COLORS = {
    "ok": LINE,
    "carie": "#EF4444",
    "obturatie": "#3B82F6",
    "coroana": "#F59E0B",
    "implant": "#8B5CF6",
    "tratament": "#16A34A",
    "extras": "#64748B",
    "lipsa": "#CBD5E1",
}
FILLS = {          # мягкая заливка под цвет состояния
    "carie": "#FEF2F2",
    "obturatie": "#EFF6FF",
    "coroana": "#FFF7ED",
    "implant": "#F5F3FF",
    "tratament": "#F0FDF4",
    "extras": "#E2E8F0",
}

# --- морфология по FDI ---
_INCISOR_C = {11, 21, 31, 41}
_INCISOR_L = {12, 22, 32, 42}
_CANINE = {13, 23, 33, 43}
_PREMOLAR = {14, 15, 24, 25, 34, 35, 44, 45}

# Молочный прикус — квадранты 5-8 (55-51, 61-65, 85-81, 71-75), по 5 зубов.
# ⚠️ Позиции 4 и 5 у молочных — МОЛЯРЫ, а не премоляры: премоляров в молочном
# прикусе не существует, и «отобразить 54 на 14» дало бы неверную морфологию
# ровно там, где её видно (два бугра вместо трёх).
_MILK_QUADRANTS = (5, 6, 7, 8)


def is_milk(fdi: int) -> bool:
    return fdi // 10 in _MILK_QUADRANTS


def tooth_class(fdi: int) -> str:
    if is_milk(fdi):
        pos = fdi % 10
        if pos == 1:
            return "incisor_c"
        if pos == 2:
            return "incisor_l"
        if pos == 3:
            return "canine"
        return "molar"          # 4 и 5 — молочные моляры
    if fdi in _INCISOR_C:
        return "incisor_c"
    if fdi in _INCISOR_L:
        return "incisor_l"
    if fdi in _CANINE:
        return "canine"
    if fdi in _PREMOLAR:
        return "premolar"
    return "molar"


def is_upper(fdi: int) -> bool:
    """Верхняя дуга: постоянные 1-2 и молочные 5-6. Без молочных квадрантов
    верхний молочный ряд рисовался бы корнями вверх."""
    return fdi // 10 in (1, 2, 5, 6)


def root_count(fdi: int) -> int:
    """Корней: верхние моляры 3, нижние 2, верхний первый премоляр 2, прочие 1."""
    cls = tooth_class(fdi)
    if cls == "molar":
        return 3 if is_upper(fdi) else 2
    if fdi in (14, 24):
        return 2
    return 1


def _sx(x: float, k: float) -> float:
    """Сжатие по ширине относительно центра — так один контур даёт и
    центральный резец, и боковой, и третий моляр."""
    return CX + (x - CX) * k


def _p(*pts: float) -> str:
    return " ".join(f"{v:.1f}" for v in pts)


# ---------------------------------------------------------------- коронки

def crown_path(fdi: int) -> str:
    """Замкнутый контур коронки. Низ контура = шейка зуба."""
    cls = tooth_class(fdi)
    k = _width_k(fdi)
    s = lambda x: _sx(x, k)  # noqa: E731

    if cls in ("incisor_c", "incisor_l"):
        # режущий край почти прямой, шейка уже края
        return (f"M {_p(s(12), 46)} C {_p(s(11), 30, s(10), 15, s(13.5), 9)} "
                f"Q {_p(s(22), 5.5, s(30.5), 9)} "
                f"C {_p(s(34), 15, s(33), 30, s(32), 46)} Z")
    if cls == "canine":
        # один острый бугор по центру
        return (f"M {_p(s(11), 48)} C {_p(s(10), 32, s(12), 17, s(17), 8)} "
                f"Q {_p(s(22), 3.5, s(27), 8)} "
                f"C {_p(s(32), 17, s(34), 32, s(33), 48)} Z")
    if cls == "premolar":
        # два бугра (щёчный + язычный) с ложбинкой между ними
        return (f"M {_p(s(10), 46)} C {_p(s(9), 30, s(9), 18, s(12), 11)} "
                f"Q {_p(s(15.5), 6.5, s(18.5), 11.5)} Q {_p(s(22), 15, s(25.5), 11.5)} "
                f"Q {_p(s(28.5), 6.5, s(32), 11)} "
                f"C {_p(s(35), 18, s(35), 30, s(34), 46)} Z")
    # моляр: широкая коронка с тремя буграми
    return (f"M {_p(s(6), 44)} C {_p(s(5), 28, s(6), 15, s(10), 10)} "
            f"Q {_p(s(13), 6.5, s(16), 11)} Q {_p(s(19), 15, s(22), 15)} "
            f"Q {_p(s(25), 15, s(28), 11)} Q {_p(s(31), 6.5, s(34), 10)} "
            f"C {_p(s(38), 15, s(39), 28, s(38), 44)} Z")


def _width_k(fdi: int) -> float:
    """Коэффициент ширины: боковой резец уже центрального, третий моляр —
    мельче первого. Одна геометрия, разные пропорции."""
    cls = tooth_class(fdi)
    pos = fdi % 10
    if is_milk(fdi):
        # молочные мельче постоянных; первый молочный моляр уже второго
        return {1: 0.72, 2: 0.66, 3: 0.72, 4: 0.86, 5: 0.92}.get(pos, 0.8)
    if cls == "incisor_l":
        return 0.82
    if cls == "premolar":
        return 0.94 if pos == 4 else 0.90
    if cls == "molar":
        return {6: 1.0, 7: 0.95, 8: 0.88}.get(pos, 1.0)
    return 1.0


# ---------------------------------------------------------------- корни

def root_paths(fdi: int) -> list[str]:
    """Контуры корней. Начинаются ВЫШЕ шейки — коронка накрывает стык."""
    n = root_count(fdi)
    cls = tooth_class(fdi)
    k = _width_k(fdi)
    can = cls == "canine"
    s = lambda x: _sx(x, k)          # noqa: E731
    y = lambda v: _ry(v, can)        # noqa: E731
    tip = 100.0 if can else 96.0

    if n == 1:
        neck_l, neck_r = (11, 33) if can else (12.5, 31.5)
        return [f"M {_p(s(neck_l), y(42))} "
                f"C {_p(s(neck_l + 1), y(64), s(neck_l + 4), y(84), s(20), y(tip - 4))} "
                f"Q {_p(s(22), y(tip), s(24), y(tip - 4))} "
                f"C {_p(s(neck_r - 4), y(84), s(neck_r - 1), y(64), s(neck_r), y(42))}"]
    if n == 2:
        # два расходящихся корня (нижние моляры, верхний первый премоляр)
        left = (f"M {_p(s(8), y(42))} C {_p(s(8), y(62), s(9), y(78), s(11), y(90))} "
                f"Q {_p(s(13), y(95), s(15), y(90))} "
                f"C {_p(s(17), y(76), s(18), y(60), s(18), y(42))}")
        right = (f"M {_p(s(26), y(42))} C {_p(s(26), y(60), s(27), y(76), s(29), y(90))} "
                 f"Q {_p(s(31), y(95), s(33), y(90))} "
                 f"C {_p(s(35), y(78), s(36), y(62), s(36), y(42))}")
        if cls == "premolar":       # у премоляра корни ближе друг к другу
            left = (f"M {_p(s(12), y(42))} C {_p(s(12), y(62), s(13), y(80), s(15), y(91))} "
                    f"Q {_p(s(17), y(96), s(18.5), y(91))} "
                    f"C {_p(s(20), y(76), s(20.5), y(60), s(20.5), y(42))}")
            right = (f"M {_p(s(23.5), y(42))} C {_p(s(23.5), y(60), s(24), y(76), s(25.5), y(91))} "
                     f"Q {_p(s(27), y(96), s(29), y(91))} "
                     f"C {_p(s(31), y(80), s(32), y(62), s(32), y(42))}")
        return [left, right]
    # три корня (верхние моляры): два щёчных + один нёбный по центру
    return [
        f"M {_p(s(7), y(42))} C {_p(s(7), y(60), s(8), y(74), s(10), y(86))} "
        f"Q {_p(s(12), y(91), s(14), y(86))} "
        f"C {_p(s(15.5), y(72), s(16), y(58), s(16), y(42))}",
        f"M {_p(s(18), y(42))} C {_p(s(18), y(62), s(19), y(80), s(20.5), y(92))} "
        f"Q {_p(s(22), y(97), s(23.5), y(92))} "
        f"C {_p(s(25), y(80), s(26), y(62), s(26), y(42))}",
        f"M {_p(s(28), y(42))} C {_p(s(28), y(58), s(28.5), y(72), s(30), y(86))} "
        f"Q {_p(s(32), y(91), s(34), y(86))} "
        f"C {_p(s(36), y(74), s(37), y(60), s(37), y(42))}",
    ]


def _canal_lines(fdi: int) -> list[str]:
    """Осевые линии корневых каналов — для состояния «эндодонтия»."""
    n = root_count(fdi)
    k = _width_k(fdi)
    can = tooth_class(fdi) == "canine"
    s = lambda x: _sx(x, k)          # noqa: E731
    y = lambda v: _ry(v, can)        # noqa: E731
    tip = 99.0 if can else 96.0
    if n == 1:
        return [f"M {_p(s(22), 34)} L {_p(s(22), y(tip - 5))}"]
    if n == 2:
        if tooth_class(fdi) == "premolar":
            return [f"M {_p(s(20), 34)} L {_p(s(16.5), y(tip - 6))}",
                    f"M {_p(s(24), 34)} L {_p(s(27.5), y(tip - 6))}"]
        return [f"M {_p(s(19), 34)} L {_p(s(13), y(tip - 8))}",
                f"M {_p(s(25), 34)} L {_p(s(31), y(tip - 8))}"]
    return [f"M {_p(s(18), 34)} L {_p(s(12), y(tip - 12))}",
            f"M {_p(s(22), 34)} L {_p(s(22), y(tip - 3))}",
            f"M {_p(s(26), 34)} L {_p(s(32), y(tip - 12))}"]


# ---------------------------------------------------------------- детали

def _fissures(fdi: int) -> list[str]:
    """Фиссуры на жевательной поверхности — то, что делает зуб зубом,
    а не силуэтом. У резцов и клыка — одна вертикальная борозда."""
    cls = tooth_class(fdi)
    k = _width_k(fdi)
    s = lambda x: _sx(x, k)  # noqa: E731
    if cls in ("incisor_c", "incisor_l"):
        return [f"M {_p(s(22), 12)} L {_p(s(22), 26)}"]
    if cls == "canine":
        return [f"M {_p(s(22), 9)} L {_p(s(22), 26)}"]
    if cls == "premolar":
        return [f"M {_p(s(13), 15)} Q {_p(s(22), 20, s(31), 15)}"]
    return [f"M {_p(s(9), 16)} Q {_p(s(22), 23, s(35), 16)}",
            f"M {_p(s(22), 20)} L {_p(s(22), 34)}"]


def _implant_screw(fdi: int) -> str:
    """Резьбовой имплант вместо корня: ствол + витки."""
    k = _width_k(fdi)
    s = lambda x: _sx(x, k)  # noqa: E731
    body = (f"M {_p(s(16), 40)} L {_p(s(18.5), _ry(88))} Q {_p(s(22), _ry(95), s(25.5), _ry(88))} "
            f"L {_p(s(28), 40)} Z")
    threads = []
    for i in range(6):
        yy = _ry(46 + i * 8)
        half = 5.8 - i * 0.5
        threads.append(f"M {_p(s(22 - half), yy)} L {_p(s(22 + half), yy + 1.8)}")
    return body, threads


# ---------------------------------------------------------------- сборка

# ⚠️ Имена состояний зуба — ОДИН словарь на программу (08-16): отсюда их берут
# и карточка пациента (`routes.TOOTH_STATES` — это он и есть), и летопись
# фиши (`db.set_tooth` отложенным импортом). Модуль для этого годится тем, что
# импортов проекта в нём нет вовсе: тянуть его может кто угодно, включая db.
STATE_RO = {
    "ok": "Sănătos", "carie": "Carie", "obturatie": "Obturație",
    "coroana": "Coroană", "implant": "Implant", "tratament": "În tratament",
    "extras": "Extras", "lipsa": "Lipsă",
}


def tooth_svg(fdi: int, state: str = "ok", *, width: int = 44,
              interactive: bool = False, extra_class: str = "") -> str:
    """Готовый <svg> одного зуба. Всё рисование — в канонической ориентации,
    верхняя челюсть переворачивается обёрткой."""
    state = state if state in STATE_RO else "ok"
    col = COLORS.get(state, LINE)
    fill = FILLS.get(state, "#FFFFFF")
    h = int(width * VB_H / VB_W)
    body: list[str] = []

    crown = crown_path(fdi)
    roots = root_paths(fdi)

    if state == "lipsa":
        # «отсутствует» — только призрак контура, пунктиром
        body.append(f"<path d='{crown}' fill='none' stroke='{COLORS['lipsa']}' "
                    f"stroke-width='1.6' stroke-dasharray='3 3'/>")
        for r in roots:
            body.append(f"<path d='{r}' fill='none' stroke='{COLORS['lipsa']}' "
                        f"stroke-width='1.6' stroke-dasharray='3 3'/>")
    elif state == "implant":
        screw, threads = _implant_screw(fdi)
        body.append(f"<path d='{screw}' fill='{fill}' stroke='{col}' stroke-width='1.8'/>")
        for t in threads:
            body.append(f"<path d='{t}' fill='none' stroke='{col}' stroke-width='1.4' "
                        f"opacity='.75'/>")
        body.append(f"<path d='{crown}' fill='#FFFFFF' stroke='{col}' stroke-width='1.8'/>")
        for f in _fissures(fdi):
            body.append(f"<path d='{f}' fill='none' stroke='{col}' stroke-width='1.2' opacity='.5'/>")
    else:
        root_col = col if state in ("tratament", "extras") else LINE
        for r in roots:
            body.append(f"<path d='{r}' fill='{fill if state == 'extras' else '#FFFFFF'}' "
                        f"stroke='{root_col}' stroke-width='1.8'/>")
        crown_fill = "#FFFFFF"
        crown_col = LINE
        if state == "coroana":
            crown_fill, crown_col = COLORS["coroana"], "#D97706"
        elif state == "extras":
            crown_fill, crown_col = FILLS["extras"], col
        elif state in ("carie", "obturatie", "tratament"):
            crown_col = col
        body.append(f"<path d='{crown}' fill='{crown_fill}' stroke='{crown_col}' "
                    f"stroke-width='1.8'/>")

        if state != "coroana":
            det = crown_col if state in ("carie", "obturatie", "tratament") else LINE_SOFT
            for f in _fissures(fdi):
                body.append(f"<path d='{f}' fill='none' stroke='{det}' stroke-width='1.2' "
                            f"opacity='.55'/>")
        if state == "carie":
            k = _width_k(fdi)
            body.append(f"<path d='M {_p(_sx(18, k), 16)} Q {_p(_sx(22, k), 10, _sx(26, k), 16)} "
                        f"Q {_p(_sx(28, k), 22, _sx(22, k), 25)} "
                        f"Q {_p(_sx(16, k), 22, _sx(18, k), 16)} Z' fill='{col}'/>")
        elif state == "obturatie":
            k = _width_k(fdi)
            body.append(f"<path d='M {_p(_sx(16.5, k), 15)} Q {_p(_sx(22, k), 11, _sx(27.5, k), 15)} "
                        f"Q {_p(_sx(29, k), 21, _sx(22, k), 23.5)} "
                        f"Q {_p(_sx(15, k), 21, _sx(16.5, k), 15)} Z' fill='{col}'/>")
        elif state == "tratament":
            for c in _canal_lines(fdi):
                body.append(f"<path d='{c}' fill='none' stroke='{col}' stroke-width='2' "
                            f"stroke-linecap='round' opacity='.9'/>")
        elif state == "extras":
            # крест «удалён» — по ширине КОНКРЕТНОГО зуба: у молочного бокового
            # резца (k=0.66) фиксированные 12…32 вылезали за коронку.
            # k считается ЗДЕСЬ: соседние ветки заводят его каждая себе, и
            # в этой его не было — страница фиши падала на легенде состояний
            k = _width_k(fdi)
            body.append(f"<path d='M {_p(_sx(12, k), 30)} L {_p(_sx(32, k), 66)} "
                        f"M {_p(_sx(32, k), 30)} L {_p(_sx(12, k), 66)}' "
                        f"stroke='{col}' stroke-width='3' stroke-linecap='round'/>")

    inner = "".join(body)
    if is_upper(fdi):                       # верхняя дуга смотрит вниз
        inner = f"<g transform='translate(0,{VB_H}) scale(1,-1)'>{inner}</g>"

    cls = ("tooth-svg" + (" tooth-int" if interactive else "")
           + (f" {extra_class}" if extra_class else ""))
    return (f"<svg class='{cls}' viewBox='0 0 {VB_W:.0f} {VB_H:.0f}' width='{width}' "
            f"height='{h}' fill='none' stroke-linecap='round' stroke-linejoin='round' "
            f"aria-label='{fdi}'>{inner}</svg>")


# ⚠️ Здесь лежала ODONTO_CSS — копия блока одонтограммы, дословно повторявшая
# static/css/panel.css. Её никто не импортировал с переезда оформления в файл
# (08-04), и копия успела разойтись с оригиналом: при переводе теней на
# двухслойные (08-06) в ней осталась старая однослойная. Мёртвый стиль опаснее
# отсутствующего — он выглядит действующим, и правку внесут в него.
# Оформление зубов живёт ТОЛЬКО в panel.css.
