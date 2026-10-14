"""Статика, знак, значки, манифест и логотип клиники."""
from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter
from fastapi.responses import Response

from ... import brand
from ... import engine as eng
from ... import paths
from ...core import theme
from ...core.layout import STATIC, _asset

router = APIRouter()
log = logging.getLogger("web")

_ASSET_MIME = {"css": "text/css", "js": "application/javascript",
               # ⚠️ woff2 читается БАЙТАМИ, а не текстом (см. ветку ниже):
               # _asset() декодирует utf-8 и на шрифте падает
               "fonts": "font/woff2"}


@router.get("/static/{kind}/{name}")
async def static_asset(kind: str, name: str) -> Response:
    """Оформление и поведение журнала. Кеш вечный намеренно: адрес несёт версию
    программы (?v=…), поэтому после обновления браузер запросит новый файл, а
    между обновлениями не будет тянуть их на каждую автоперезагрузку страницы —
    а она происходит раз в 12 секунд на каждом открытом экране.

    Отдаём только css и js по строгому шаблону имени: каталог статики лежит
    внутри сборки рядом с профилем клиники, и вытащить оттуда что-то ещё через
    этот адрес быть не должно."""
    mime = _ASSET_MIME.get(kind)
    # шрифты лежат в fonts/ и называются .woff2, остальное — имя.<папка>
    ext = "woff2" if kind == "fonts" else kind
    if not mime or not re.fullmatch(rf"[a-z0-9_-]+\.{ext}", name):
        return Response(status_code=404)
    try:
        # ⚠️ Шрифт — ДВОИЧНЫЙ файл. _asset() отдаёт текст (utf-8) и на woff2
        # падает с UnicodeDecodeError, поэтому читаем байтами и мимо кеша
        # текстов: класть 500 КБ шрифта в _CSS_CACHE незачем, его и так
        # закеширует браузер на год.
        text = (STATIC / kind / name).read_bytes() if kind == "fonts" \
            else _asset(kind, name)
    except OSError:
        log.error("не читается %s/%s — страница останется без него", kind, name)
        return Response(status_code=404)
    cache = ("public, max-age=31536000, immutable" if paths.is_frozen()
             else "no-cache")
    return Response(text, media_type=mime,
                    headers={"Cache-Control": cache})


@router.get("/favicon.ico")
async def favicon() -> Response:
    """Тот же знак во вкладке браузера. Браузер сам просит /favicon.ico, поэтому
    один роут закрывает все страницы, включая печатные."""
    return Response(brand.mark_svg(None), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


ICON_PX = (180, 192, 512)  # apple-touch-icon; манифест просит 192 и 512


@router.get("/icon-{px}.png")
async def app_icon(px: int) -> Response:
    """Знак значком приложения. Размеры перечислены намеренно: адрес открыт без
    входа, а `brand.png` РИСУЕТ картинку — свободный размер дал бы любому в сети
    клиники дешёвый способ занять процессор запросами вида /icon-9000.png."""
    if px not in ICON_PX:
        return Response(status_code=404)
    # 180 — тот, что забирает iPhone (apple-touch-icon), и ему нужен знак БЕЗ
    # прозрачности: см. brand.png. Остальные два берёт манифест, там прозрачные
    # углы — норма, значок ложится на подложку системы.
    return Response(brand.png(px, opaque=px == 180), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/manifest.webmanifest")
async def manifest() -> Response:
    """Паспорт «приложения» для телефона: имя, значок, цвет, стартовый адрес.

    Собирается на лету, а не лежит файлом, по двум причинам, и обе тихие:
    ⛔ цвет и имя принадлежат КЛИНИКЕ (`theme.current`, `clinic.json`) — файл
    в сборке заморозил бы зелёный DentPilot на синем интерфейсе;
    ⛔ адреса внутри обязаны быть ОТНОСИТЕЛЬНЫМИ: одна и та же программа
    открывается как 127.0.0.1, как 192.168.x.y из сети клиники и через будущий
    туннель — записанный хост сделал бы значок нерабочим на всех адресах, кроме
    одного.

    `start_url` — журнал, а не «/»: «/» это витрина записи для пациента, и
    установленное приложение обязано открываться там, где работают.
    """
    th = theme.current()
    bg = theme.STYLES[th["style"]]["--bg"]  # тот же цвет, что <meta theme-color>
    body = json.dumps({
        "id": "/admin",
        "name": f"{eng.CLINIC_NAME} — registru",
        "short_name": eng.CLINIC_NAME,
        "lang": "ro",
        "start_url": "/admin",
        "scope": "/",
        "display": "standalone",
        "background_color": bg,
        "theme_color": bg,
        "icons": [{"src": f"/icon-{px}.png", "sizes": f"{px}x{px}",
                   "type": "image/png"} for px in (192, 512)],
    }, ensure_ascii=False)
    return Response(body, media_type="application/manifest+json",
                    headers={"Cache-Control": "no-cache"})


@router.get("/clinic-logo")
async def clinic_logo() -> Response:
    """Логотип клиники. Отдаётся БЕЗ входа намеренно: он нужен экрану входа,
    а сам по себе это та же картинка, что висит у клиники на двери и печатается
    на бланке, — скрывать в нём нечего.

    ⭐ Имя файла не приходит из запроса ВООБЩЕ: путь собирает theme из двух
    разрешённых имён. Поэтому здесь нет ни разбора имени, ни проверки на «..» —
    подставить сюда чужой путь нечем."""
    p = theme.logo_path()
    if p is None:
        return Response(status_code=404)
    try:
        data = p.read_bytes()
    except OSError:
        log.warning("логотип клиники не читается: %s", p)
        return Response(status_code=404)
    # адрес несёт отпечаток времени правки (theme.logo_url), поэтому кеш можно
    # держать долго: замена логотипа меняет адрес и доезжает сразу
    return Response(data, media_type=theme.logo_mime(p.name),
                    headers={"Cache-Control": "public, max-age=86400"})
