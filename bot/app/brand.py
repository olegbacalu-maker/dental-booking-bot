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


def _shape(kind: str, x0: int, y0: int, x1: int, y1: int, r: int, fill: str) -> str:
    if kind == "rect":
        return (f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" '
                f'height="{y1 - y0}" rx="{r}" fill="{fill}"/>')
    return (f'<ellipse cx="{(x0 + x1) / 2:g}" cy="{(y0 + y1) / 2:g}" '
            f'rx="{(x1 - x0) / 2:g}" ry="{(y1 - y0) / 2:g}" fill="{fill}"/>')


def mark_svg(px: int | None = 34, cls: str = "", label: str = "DentPilot",
             flat: bool = False) -> str:
    """Знак как встроенный SVG. px=None — тянется по контейнеру (для favicon).

    Внутри картинки нет ни ссылок, ни шрифтов: она одинаково работает в окне
    программы, в браузере и в data-URI.

    ⭐ `flat=True` — знак БЕЗ собственной подложки: фигуры рисуются
    `currentColor`, а выемка между корнями остаётся по-настоящему прозрачной
    (маска, а не заливка цветом фона — иначе выемку пришлось бы красить в цвет
    подложки, и она разъехалась бы с темой). Нужен там, где знак лежит НА
    фирменном цвете клиники: своя тёмно-зелёная подложка — тот самый зашитый
    хекс, который тема не перекрашивает, и на синей шапке она стала бы пятном.
    """
    size = "" if px is None else f' width="{px}" height="{px}"'
    klass = f' class="{cls}"' if cls else ""
    head = (f'<svg{klass} viewBox="0 0 {VB} {VB}"{size} '
            f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">')
    if not flat:
        return head + "".join(_shape(*s[:6], hexc(s[6])) for s in SHAPES) + "</svg>"
    # В маске белое видно, чёрное прозрачно: фигуры знака — белым, выемка —
    # чёрным. Подложка (первая фигура) не рисуется вовсе.
    mid = "dpm" + (cls or "mark")
    cut = "".join(_shape(*s[:6], "#FFF" if s[6] == WHITE else "#000")
                  for s in SHAPES[1:])
    return (f'{head}<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" '
            f'width="{VB}" height="{VB}"><rect width="{VB}" height="{VB}" fill="#000"/>'
            f'{cut}</mask><rect width="{VB}" height="{VB}" fill="currentColor" '
            f'mask="url(#{mid})"/></svg>')


_PNG: dict[tuple[int, bool], bytes] = {}


def png(size: int, opaque: bool = False) -> bytes:
    """Тот же знак в PNG — для значка на домашнем экране телефона.

    ⛔ SVG тут не годится, хотя во вкладке браузера работает: `apple-touch-icon`
    его не понимает вовсе, а в манифесте PNG — единственный формат, который
    берут все. Поэтому знак рисуется дважды из ОДНИХ чисел (SHAPES), а не
    сохраняется картинкой рядом: сохранённая разошлась бы с интерфейсом при
    первой же правке фигуры.

    ⚠️ `opaque=True` — для iOS. Значок со скруглёнными углами имеет ПРОЗРАЧНЫЕ
    углы, а iOS в `apple-touch-icon` прозрачность не поддерживает и заливает её
    ЧЁРНЫМ — фирменный знак приезжает на домашний экран в чёрной рамке, и
    заметно это только на самом айфоне. Поэтому там знак кладётся на сплошной
    квадрат своего же цвета: скруглять углы iOS будет сам.

    Кеш — потому что рисование стоит дороже отдачи, а результат за жизнь
    процесса не меняется: фигура зашита, размеров три."""
    key = (size, opaque)
    if key not in _PNG:
        import io

        from PIL import Image

        img = draw_pil(size)
        if opaque:
            plate = Image.new("RGB", (size, size), TEAL)
            plate.paste(img, (0, 0), img)   # альфа знака — маской
            img = plate
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        _PNG[key] = buf.getvalue()
    return _PNG[key]


def draw_pil(size: int):
    """Тот же знак средствами PIL — для .ico при сборке и для png() в работе.

    Импорт PIL внутри функции: модуль зовёт и скрипт сборки, которому не нужно
    приложение, и брать зависимость на весь модуль ради двух функций незачем.
    ⚠️ В exe PIL всё равно едет (его же просит загрузка снимков в фише), так
    что png() в собранной программе работает — и это проверяет smoke_exe."""
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
