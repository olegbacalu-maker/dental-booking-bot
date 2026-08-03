"""Фирменный знак DentPilot — одна геометрия для иконки и для интерфейса.

Иконка на рабочем столе и знак в шапке программы должны быть ОДНИМ знаком.
Нарисованные по отдельности, они разойдутся при первой же правке — поэтому
фигуры описаны здесь числами, а PIL (сборка .ico) и SVG (интерфейс) остаются
лишь двумя способами их нарисовать.

Система координат 256x256 — родная для .ico. Модуль намеренно без зависимостей:
его импортирует и приложение, и скрипт сборки.
"""
from __future__ import annotations

VB = 256
TEAL = (7, 94, 84)
WHITE = (250, 250, 250)

# Знак: коронка и два корня с выемкой между ними, на скруглённом квадрате.
# (вид, x0, y0, x1, y1, радиус скругления, цвет)
SHAPES = (
    ("rect", 0, 0, 256, 256, 52, TEAL),       # фон
    ("rect", 64, 52, 192, 150, 46, WHITE),    # коронка
    ("rect", 78, 110, 120, 204, 20, WHITE),   # левый корень
    ("rect", 136, 110, 178, 204, 20, WHITE),  # правый корень
    ("ellipse", 112, 150, 144, 214, 0, TEAL),  # выемка между корнями
)


def hexc(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb


def mark_svg(px: int | None = 34, cls: str = "", label: str = "DentPilot") -> str:
    """Знак как встроенный SVG. px=None — тянется по контейнеру (для favicon).

    Внутри картинки нет ни ссылок, ни шрифтов: она одинаково работает в окне
    программы, в браузере и в data-URI.
    """
    size = "" if px is None else f' width="{px}" height="{px}"'
    parts = []
    for kind, x0, y0, x1, y1, r, rgb in SHAPES:
        fill = hexc(rgb)
        if kind == "rect":
            parts.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" '
                         f'height="{y1 - y0}" rx="{r}" fill="{fill}"/>')
        else:
            parts.append(f'<ellipse cx="{(x0 + x1) / 2:g}" cy="{(y0 + y1) / 2:g}" '
                         f'rx="{(x1 - x0) / 2:g}" ry="{(y1 - y0) / 2:g}" fill="{fill}"/>')
    klass = f' class="{cls}"' if cls else ""
    return (f'<svg{klass} viewBox="0 0 {VB} {VB}"{size} xmlns="http://www.w3.org/2000/svg" '
            f'role="img" aria-label="{label}">{"".join(parts)}</svg>')


def draw_pil(size: int):
    """Тот же знак средствами PIL — для .ico. PIL здесь, а не наверху модуля:
    приложению он не нужен, а тащить его в exe ради иконки незачем."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / float(VB)
    for kind, x0, y0, x1, y1, r, rgb in SHAPES:
        # координаты PIL — это индексы пикселей (включительно), у SVG — грани.
        # Разница видна только у фигуры во весь холст, поэтому и клампим.
        box = [round(x0 * s), round(y0 * s),
               min(round(x1 * s), size - 1), min(round(y1 * s), size - 1)]
        if kind == "rect":
            d.rounded_rectangle(box, radius=round(r * s), fill=rgb + (255,))
        else:
            d.ellipse(box, fill=rgb + (255,))
    return img
