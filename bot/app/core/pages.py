"""Страницы со своей вёрсткой: вход, установка PIN, восстановление, лицензия,
обновление, перезапуск, раздвоение. Они не подключают panel.css и обязаны открыться,
даже если статика не отдалась; цвет, шрифт и логотип клиники подставляет `standalone()`.
Здесь же чтение файлов static/ и метка версии в их адресах.
"""
from __future__ import annotations

import html
import logging
import re

from .. import brand, paths
from .. import engine as eng
from . import theme


# путь считается от корня пакета, а не от расположения ЭТОГО файла: main.py
# однажды разъедется по модулям, а статика останется на месте (см. paths.py)
STATIC = paths.resource("static")


_CSS_CACHE: dict[str, str] = {}


def _asset(*parts: str) -> str:
    """Текст файла из static/. В собранной программе читается один раз, при
    запуске из исходников — каждый раз: правка стилей видна по F5, без
    перезапуска сервера. Оформление правят чаще, чем код."""
    key = "/".join(parts)
    if paths.is_frozen() and key in _CSS_CACHE:
        return _CSS_CACHE[key]
    text = (STATIC.joinpath(*parts)).read_text(encoding="utf-8")
    _CSS_CACHE[key] = text
    return text


def fonts_css() -> str:
    """Правила @font-face для страниц СО СВОЕЙ вёрсткой — ТЕМ ЖЕ файлом,
    который панель подключает ссылкой.

    Журнал получает `fonts.css` ссылкой: он кешируется, адрес несёт версию, а
    страница журнала перезагружает себя раз в 12 секунд — возить текст шрифта
    в разметке было бы расточительно. Вход, установка PIN и восстановление
    берут его СОДЕРЖИМЫМ, внутрь своего <style>: подключать таблицу стилей им
    нельзя по замыслу (они обязаны открыться, даже если статика не отдалась), а
    лишний запрос на первом экране клиники — ровно то, чего они избегают.
    Источник при этом один, поэтому объявление не задваивается.

    Внутрь страницы едут ТОЛЬКО правила: пояснения из шапки файла — три
    четверти его веса, и на первом экране клиники им делать нечего. Заодно это
    убирает из разметки слово `__FONTS__`, которое в тех пояснениях помянуто:
    иначе заполнитель «оставался» бы в готовой странице и проверка на забытую
    подстановку не значила бы ничего.

    ⚠️ Пропажа файла не имеет права уронить вход: без правил страница
    нарисуется системным шрифтом — тем же, что до 08-11. Поэтому OSError здесь
    не поднимается, а остаётся строкой в логе."""
    try:
        return re.sub(r"/\*.*?\*/", "", _asset("css", "fonts.css"),
                      flags=re.S).strip()
    except OSError:
        logging.getLogger("layout").error(
            "не читается fonts.css — страница останется на системном шрифте")
        return ""


def _asset_ver(*parts: str) -> str:
    """Метка версии в адресе файла — ею сбрасывается кеш браузера.

    У клиники это версия программы: адрес меняется ровно тогда, когда приехало
    обновление. При запуске из исходников — время правки файла, иначе работа
    над оформлением превращается в борьбу с кешем: версия-то не менялась."""
    if paths.is_frozen():
        return eng.APP_VERSION
    try:
        return str(int(STATIC.joinpath(*parts).stat().st_mtime))
    except OSError:
        return eng.APP_VERSION


_PWA_ANCHOR = '<meta charset="utf-8">'


def pwa_head() -> str:
    """Теги, которые превращают страницу в «приложение» на телефоне.

    ⚠️ Что здесь правда и что нет, чтобы не обещать лишнего в интерфейсе:
    на iPhone `apple-mobile-web-app-capable` даёт настоящий полноэкранный
    запуск с домашнего экрана и работает ПО HTTP — то есть в сети клиники уже
    сегодня. На Android полноценная установка (WebAPK) требует service worker,
    а тот живёт только в защищённом контексте (https или localhost); в сети
    клиники у нас голый http НАМЕРЕННО, поэтому там значок остаётся ярлыком —
    но с нашим именем и знаком, а не с обрезанным снимком страницы. На
    настольном браузере «установить как приложение» работает независимо от
    всего этого. ⭐ Появится https (туннель, слой 3) — Android доберёт своё
    без единой правки здесь.
    """
    name = html.escape(eng.CLINIC_NAME)
    return ('<link rel="manifest" href="/manifest.webmanifest">'
            '<link rel="apple-touch-icon" href="/icon-180.png">'
            '<meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
            f'<meta name="apple-mobile-web-app-title" content="{name}">')


_BACKDROP_JOIN = "</style></head><body>"


def _backdrop(tmpl: str, color: str) -> str:
    """Фон заставки за страницей со своей вёрсткой (05.10.2026): волны и бледный
    зуб цветом клиники, внизу — «DentPilot v…».

    ⭐ Окно программы открывается заставкой (у оболочки Tauri — `gen/ui/
    splash.html`, шрифт от `app/splash.py`) и переходит на вход в ТОМ ЖЕ окне — слово Олега «окно с PIN-кодом оставить на том же
    фоне». Фон одинаковый у заставки и у всех страниц этого класса (вход,
    установка PIN, восстановление, лицензия): иначе первый экран клиники
    выглядел бы одним, а соседний — другим.
    ⚠️ Цвет — цвет темы клиники, а не бирюза: на синей клинике бирюзовый фон
    под синей кнопкой — ровно та зашитая чужая краска, от которой нас бережёт
    тема. Заставка берёт тот же цвет, поэтому переход без вспышки.
    ⚠️ Вставка по стыку `</style></head><body>`: он есть у каждого шаблона
    этого класса, и шаблон без него останется без фона, но не сломается."""
    if _BACKDROP_JOIN not in tmpl:
        return tmpl
    css = (f"body{{--dp-c:{color};background:{brand.tint(color, .06)}!important}}"
           f"{brand.BACKDROP_CSS}"
           "body>:not(.dp-bg){position:relative;z-index:1}"
           ".dp-by{position:fixed!important;left:0;right:0;bottom:18px;display:flex;"
           "justify-content:center;align-items:center;gap:8px;font-size:12.5px;color:#6B7C85}"
           ".dp-by svg{width:30px;height:auto}")
    by = (f'<div class="dp-by">{brand.mark_svg(30, "dpby", flat=True)}'
          f"<span>DentPilot v{eng.APP_VERSION}</span></div>")
    return (tmpl.replace(_BACKDROP_JOIN, css + _BACKDROP_JOIN + brand.backdrop_svg(), 1)
                .replace("</body>", by + "</body>", 1))


def standalone(tmpl: str) -> str:
    """Подставить в страницу СО СВОЕЙ вёрсткой имя клиники, её цвет, логотип и
    объявление шрифта.

    Одна точка на все такие страницы намеренно: их много (вход, установка
    PIN, восстановление, лицензия, обновление, перезапуск, раздвоение), они
    разбросаны по модулям, и стоит завести подстановку по месту — очередной экран забудут перекрасить, а
    заметит это клиника, у которой единственная зелёная страница посреди
    синей программы. С 08-11 через ту же точку приезжает и `__FONTS__`: ровно
    так эти страницы и разошлись с журналом — шрифт объявлен в panel.css,
    которую они не подключают, и экран входа рисовался системным Segoe UI.

    ⚠️ `__FONTS__` подставляется ПОСЛЕДНИМ: это чужой текст (файл со стилями),
    и попади в него однажды `__ACCENT__`, он не должен быть истолкован."""
    th = theme.current()
    pal = theme.palette(th["primary"], th["style"])
    logo = theme.logo_url()
    # ⚠️ Теги приложения вставляются ПОСЛЕ объявления кодировки, а не в начало
    # <head>: в них едет имя клиники, а браузер обязан узнать кодировку раньше,
    # чем встретит первую не-ASCII букву. Вставка по якорю, а не заполнителем:
    # заполнитель в новом экране просто забудут — ровно то, о чём docstring.
    tmpl = tmpl.replace(_PWA_ANCHOR, _PWA_ANCHOR + pwa_head(), 1)
    tmpl = _backdrop(tmpl, pal["--teal"])
    return (tmpl.replace("__CLINIC__", html.escape(eng.CLINIC_NAME))
            .replace("__ACCENT_D__", pal["--teal-d"])
            .replace("__ACCENT__", pal["--teal"])
            .replace("__RING__", pal["--teal-ring"])
            .replace("__ON__", pal["--on-teal"])
            .replace("__BG__", theme.STYLES[th["style"]]["--bg"])
            .replace("__LOGO__",
                     f"<img class='clogo' src='{logo}' alt=''>" if logo else "")
            # выбор шрифта клиники (B5): те же семейства, что `--font` журнала.
            # ⚠️ Не `__FONT__`: он префикс `__FONTS__` и испортил бы его.
            .replace("__FAMILY__", theme.font_stack())
            .replace("__FONTS__", fonts_css()))
