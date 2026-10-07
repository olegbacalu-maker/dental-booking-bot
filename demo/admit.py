"""Кому шлюз демо даёт слот (07.10): решение — чистая функция, без сети.

Зачем отдельно. 07.10 Олег открыл demo.dentpilot.md и увидел «Toate locurile
demo sunt ocupate» — все шесть слотов выданы. Шлюз отдавал слот на час ЛЮБОМУ
запросу без куки: роботу поисковика (куку он не хранит — каждый запрос новый
слот), превью ссылки в Telegram/Viber/Facebook, /robots.txt и /favicon.ico,
сканерам, проверке `curl …/health` из шага 9 выпуска. Шести таких запросов
хватало, чтобы закрыть демо людям на час. Слот дорогой (процесс программы на
час), поэтому решение «давать ли» живёт здесь, без httpx и starlette: его
проверяет обычный прогон (`tests/test_demo.py::suite_gate_admit`), а шлюз
только исполняет.

Правило. Слот получает НАВИГАЦИЯ ДОКУМЕНТА в браузере: GET с
`Sec-Fetch-Mode: navigate` и `Sec-Fetch-Dest: document`. Эти заголовки ставит
сам браузер (Chrome/Edge с 2019–2020, Firefox 90, Safari 16.4) и только на
переход вкладки; роботы, превью ссылок, curl и скрипты их не шлют, а fetch
страницы и подзагрузки шлют другие значения. Второй рубеж — роботы, которые
называют себя в User-Agent (`bot`, `crawl`, `spider`, библиотеки HTTP).
⚠️ «Headless» в этот список НЕ входит: кадры сайта снимаются headless-Edge
через локальный шлюз (site/README.md), а безголовый браузер, который грузит
страницу и ходит в API, ведёт себя как посетитель — отличать его по строке
нечем. Предзагрузка (`Sec-Purpose: prefetch`, prerender) слота не получает:
человек мог и не открыть страницу.

Без куки, но и без права на слот:
- статика, значок, манифест, /health — PUBLIC: они одинаковы во всех слотах и
  отдаются любым живым слотом без выдачи;
- /api/… — API: 401 в конверте программы; клиент уходит на вход ДОКУМЕНТОМ,
  а это уже навигация, которая слот получит;
- страница, но не навигация (робот, превью, браузер без Sec-Fetch, iframe) —
  PAGE: короткая страница демо с кнопкой «Deschide demo-ul». Кнопка шлёт POST,
  а его роботы не жмут: это и вход для старого браузера, и выход для
  человека, которого правило приняло за робота;
- форма (POST-навигация) без куки — HOME: на /admin, туда же, где начинает
  каждый;
- прочее — NONE (404).

Кука-проба. Навигация без куки ВОВСЕ (PROBE) идёт через `/demo/start`, а
корень `/` ставит пробу сам: слот получает только браузер, который куку
вернул. Иначе браузер с запретом cookie гонял бы круг «страница → API 401 →
вход документом → новый слот» и за секунды занимал весь пул.
"""
from __future__ import annotations

import re
from typing import Mapping

# Что делать с запросом БЕЗ действующей куки слота
SLOT = "slot"          # выдать слот сейчас
PROBE = "probe"        # навигация, но куки нет совсем: проба через /demo/start
PUBLIC = "public"      # отдать любым живым слотом, не выдавая
API = "api"            # 401 JSON
PAGE = "page"          # страница демо с кнопкой, без слота
HOME = "home"          # 303 на /admin
LATER = "later"        # предзагрузка: 503 без кеша, браузер сходит заново
NONE = "none"          # 404

# Одинаковы во всех слотах и без входа: программа отдаёт их любому
_PUBLIC_EXACT = frozenset({"/favicon.ico", "/manifest.webmanifest", "/health"})
_ICON = re.compile(r"/icon-\d{2,4}\.png")

# Роботы и библиотеки, которые называют себя сами. Подстроки, без учёта
# регистра; ⛔ без «headless» (см. докстринг модуля) и без имён браузеров:
# YaBrowser — настоящий браузер, а YandexBot ловится на «bot».
_BOT = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|meta-externalagent|preview"
    r"|curl|wget|python|java/|go-http|okhttp|libwww|httpclient|scrapy"
    r"|lighthouse|pagespeed", re.IGNORECASE)

# Путь журнала с запросом; буквы с диакритикой можно (поиск «Ștefan»),
# пробелы, управляющие и обратную косую — нет
_NEXT = re.compile(r"/admin(?:[/?][^\s\x00-\x1f\x7f\\]*)?")

ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


def _h(headers: Mapping[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def public(path: str) -> bool:
    return (path.startswith("/static/") or path in _PUBLIC_EXACT
            or _ICON.fullmatch(path) is not None)


def page(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/")


def navigation(headers: Mapping[str, str]) -> bool:
    """Переход вкладки браузера. Dest без значения — Chrome 76–79, слал Mode
    раньше Dest; `iframe`/`embed` — не вкладка: в чужом фрейме кука
    SameSite=Lax не вернётся, и каждый запрос просил бы новый слот."""
    h = _h(headers)
    return (h.get("sec-fetch-mode", "") == "navigate"
            and h.get("sec-fetch-dest", "document") in ("document", ""))


def prefetch(headers: Mapping[str, str]) -> bool:
    h = _h(headers)
    said = " ".join(h.get(k, "") for k in ("sec-purpose", "purpose", "x-purpose", "x-moz"))
    return any(w in said.lower() for w in ("prefetch", "prerender", "preview"))


def robot(user_agent: str) -> bool:
    return not user_agent.strip() or _BOT.search(user_agent) is not None


def classify(method: str, path: str, headers: Mapping[str, str], has_cookie: bool) -> str:
    """Что делать с запросом, у которого нет действующей куки слота.
    `has_cookie` — кука `dp_demo` есть с любым значением (проба, протухший
    слот): браузер куки хранит."""
    if public(path):
        return PUBLIC
    if path == "/api" or path.startswith("/api/"):
        return API
    nav = navigation(headers)
    if method == "HEAD":
        return PAGE if page(path) else NONE
    if method != "GET":
        return HOME if nav else API
    if not nav or robot(_h(headers).get("user-agent", "")):
        return PAGE if page(path) else NONE
    if prefetch(headers):
        return LATER
    if not page(path):
        return HOME
    return SLOT if has_cookie else PROBE


def safe_next(raw: str) -> str:
    """Куда вести после выдачи слота: только экран журнала. Вход и выход —
    нет (вход посетителю не нужен, выход отдал бы слот сразу), чужой хост и
    `//` — нет."""
    if (_NEXT.fullmatch(raw) and "//" not in raw and "\\" not in raw
            and not raw.startswith(("/admin/login", "/admin/logout"))):
        return raw
    return "/admin"
