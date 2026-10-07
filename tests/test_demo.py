"""Демо-режим (DENTART_DEMO=1, core/demo.py): живое демо с сайта.

Что стережётся: флаг прячет ровно то, что меняет машину и учётки (список
BLOCKED) — страницы, JSON и плитки хаба одним списком — и ничего больше;
баннер демо на каждом экране; вход по ключу остаётся входом (демо не
открывает журнал без куки); потолок загрузки ниже. Без флага ничего из этого
не происходит — иначе клиника получила бы «демо» вместо программы.

Шлюз перед демо (demo/gate.py) сам в прогон не поднимается: ему нужен httpx,
а в окружение сборки лишнее не ставится. Здесь — его решение «кому слот»
(demo/admit.py, чистая функция); вживую шлюз проверяет demo/check_gate.py.
"""
import json
import pathlib
import shutil
import sys
import time
import tempfile

from harness import ROOT, Client, Result, Server

DEMO = {"DENTART_DEMO": "1"}
CLOSED_PAGES = ("/admin/settings/system", "/admin/settings/crypt",
                "/admin/settings/backup", "/admin/settings/security",
                "/admin/settings/telegram", "/admin/settings/lan", "/admin/license")
CLOSED_API = ("/api/settings/system", "/api/settings/crypt", "/api/settings/backup",
              "/api/settings/security", "/api/license")
OPEN_PAGES = ("/admin/settings", "/admin/settings/clinic", "/admin/settings/hours",
              "/admin/settings/services", "/admin/settings/theme", "/admin/settings/faq",
              "/admin/all", "/admin/search", "/admin/medici", "/admin/stats")
HUB_CLOSED = {"/admin/settings/system", "/admin/settings/crypt",
              "/admin/settings/backup", "/admin/settings/security"}
HUB_OPEN = {"/admin/settings/clinic", "/admin/settings/hours", "/admin/settings/services",
            "/admin/settings/theme", "/admin/settings/faq"}
BANNER = "Versiune demonstrativă"


def _j(r) -> dict:
    return json.loads(r.body)


def _hub(c: Client) -> set:
    return {t["href"] for t in _j(c.get("/api/settings/hub"))["data"]["tiles"]}


ABORTED = -1     # соединение оборвано, ответа нет (см. _upload)


def _upload(c: Client, size: int) -> int:
    """Код ответа на загрузку файла в `size` байт, или ABORTED. Потолок
    срабатывает ДО чтения тела, и сервер закрывает соединение, пока клиент ещё
    шлёт мегабайты: под нагрузкой это приходит не ответом 413, а обрывом
    (WinError 10053) — для ПОТОЛКА это тот же отказ (поймано полным прогоном
    01.10: один в один набор зелёный, в общем прогоне — обрыв).
    ⚠️ Обрыв — не 413 (02.10): отрицательная проверка «без флага 9 МБ НЕ
    упираются в потолок» на обрыве по любой другой причине (сосед-сервер
    прогона занял машину) краснела как «потолок демо у клиники» — 5046/5047
    при зелёном одиночном наборе. Обрыв возвращается своим кодом, и каждая
    проверка решает сама: для потолка он годится, для «проходит» — повтор."""
    try:
        return c.post_file("/api/patients/1/doc", "file", "f.pdf", b"0" * size,
                           mime="application/pdf").status
    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
        return ABORTED


def _upload_settled(c: Client, size: int, tries: int = 3) -> int:
    """Загрузка, которая ОБЯЗАНА дойти до ответа: обрыв под нагрузкой — повтор,
    не вердикт. Возвращает последний исход (ABORTED, если все попытки оборваны)."""
    got = ABORTED
    for _ in range(tries):
        got = _upload(c, size)
        if got != ABORTED:
            return got
        time.sleep(0.5)
    return got


def suite_demo(res: Result) -> None:
    with Server(env=DEMO) as s:
        r = Client(s.url).get("/admin")
        res.ok("без куки демо не пускает — вход по ключу остаётся входом",
               r.status == 303 and r.location.startswith("/admin/login"), repr(r))
        c = Client(s.url).login()
        r = c.get("/admin")
        res.check("после входа журнал открыт", r.status, 200)
        res.ok("баннер демо на журнале", BANNER in r.body, "полосы демо нет")
        res.ok("баннер ведёт в шлюз: /demo/reset", "href='/demo/reset'" in r.body,
               "ссылки сброса нет")
        res.ok("баннер демо и на списке пациентов", BANNER in c.get("/admin/search").body,
               "полоса есть только на главной")
        # закрытые адреса — страницы и формы, одним кодом
        for path in CLOSED_PAGES:
            r = c.get(path)
            res.ok(f"{path}: в демо нет", r.status == 303 and r.msg == "demo_off", repr(r))
        for path, fields in (("/admin/update/check", {}), ("/admin/backup/export", {}),
                             ("/admin/users/save", {"name": "x"}), ("/admin/pin/change", {}),
                             ("/admin/telegram/save", {"token": "1:x"}),
                             ("/admin/settings/crypt/prepare", {})):
            r = c.post(path, **fields)
            res.ok(f"POST {path}: в демо нет", r.status == 303 and r.msg == "demo_off", repr(r))
        # отказ стоит ДО маршрута: адрес под закрытым префиксом, которого нет,
        # получает тот же отказ, а не 404 — и ничего под ним не разбирается
        r = c.get("/admin/settings/crypt/oricare")
        res.ok("закрытый префикс закрывает и адрес под ним", r.status == 303 and r.msg == "demo_off",
               repr(r))
        # закрытые адреса — JSON: 403 тем же кодом, не 303 на вход
        for path in CLOSED_API:
            r = c.get(path)
            res.ok(f"{path}: 403 demo_off", r.status == 403 and _j(r).get("code") == "demo_off",
                   repr(r)[:120])
        r = c.post_json("/api/settings/users", {"name": "x"})
        res.ok("POST /api/settings/users: 403 demo_off",
               r.status == 403 and _j(r).get("code") == "demo_off", repr(r)[:120])
        # код отказа — слово для человека, не голый код
        res.ok("demo_off переводится в текст", _j(c.get("/api/license")).get("text", "").startswith("În versiunea"),
               _j(c.get("/api/license")).get("text", ""))
        # открытые разделы — как у клиники
        for path in OPEN_PAGES:
            res.check(f"{path}: открыт", c.get(path).status, 200)
        hrefs = _hub(c)
        res.ok("плитки закрытых разделов спрятаны", not (hrefs & HUB_CLOSED),
               str(sorted(hrefs & HUB_CLOSED)))
        res.ok("плитки клиники, часов, услуг, вида и FAQ на месте", HUB_OPEN <= hrefs,
               str(sorted(HUB_OPEN - hrefs)))
        # потолок загрузки ниже: 9 МБ — 413 ещё до маршрута, 1 МБ проходит
        big = _upload(c, 9 * 1024 * 1024)
        res.ok("загрузка 9 МБ в демо — 413 (или обрыв до чтения тела)", big in (413, ABORTED), str(big))
        small = _upload_settled(c, 1024 * 1024)
        res.ok("1 МБ проходит потолок демо", small not in (413, ABORTED), str(small))
    with Server() as s:
        c = Client(s.url).login()
        res.ok("без флага полосы демо нет", BANNER not in c.get("/admin").body,
               "полоса демо у клиники")
        res.check("без флага «Stare sistem» открыт", c.get("/admin/settings/system").status, 200)
        res.ok("без флага плитка системы на месте", "/admin/settings/system" in _hub(c),
               "плитка пропала без демо")
        big = _upload_settled(c, 9 * 1024 * 1024)
        res.ok("без флага 9 МБ не упираются в потолок демо", big not in (413, ABORTED), str(big))


def suite_seed(res: Result) -> None:
    """Засев демо (demo/seed.py) ложится на схему ПРОГРАММЫ: базу создаёт
    первый сервер, засев её наполняет, второй сервер открывает экраны. Это
    единственный сторож колонок, которые засев знает сам: смена схемы без
    правки засева краснеет здесь, а не у посетителя сайта."""
    sys.path.insert(0, str(ROOT))
    from demo import seed as dseed  # noqa: E402 — пакет демо лежит в корне репозитория
    work = pathlib.Path(tempfile.mkdtemp(prefix="dp_demo_"))
    try:
        shutil.copy(ROOT / "demo" / "clinic.json", work / "clinic.json")
        with Server(env=DEMO, dir_=work):
            pass                                   # схема и миграции — от программы
        counts = dseed.seed(work / "dental.db", work / "clinic.json")
        res.ok("засев: пациенты, визиты, план, оплаты",
               counts["patients"] > 200 and counts["appointments"] > 400
               and counts["plan_items"] > 100 and counts["payments"] > 100, str(counts))
        res.ok("засев: сегодня есть визиты", sum(counts["today"].values()) > 0, str(counts["today"]))
        with Server(env=DEMO, dir_=work) as s:
            c = Client(s.url).login()
            res.check("журнал открывается на засеве", c.get("/admin").status, 200)
            live = _j(c.get("/api/schedule/live"))["data"]
            desk = live.get("desk") or {}
            res.ok("«La recepție» не пуста: подтверждения и план без записи",
                   bool(desk.get("confirm")) and bool(desk.get("unscheduled")),
                   str({k: len(v) if isinstance(v, list) else v for k, v in desk.items()}))
            pats = _j(c.get("/api/patients?q=Popescu"))["data"]
            rows = pats.get("rows") or pats.get("patients") or pats.get("items") or []
            pid = next((r["id"] for r in rows if r.get("name") == "Maria Popescu"), None)
            res.ok("витринный пациент находится поиском", pid is not None, str(pats)[:200])
            if pid is not None:
                card = _j(c.get(f"/api/patients/{pid}"))
                res.ok("фиша витринного пациента отдаётся", card.get("ok") is True
                       and "Maria Popescu" in json.dumps(card, ensure_ascii=False), str(card)[:200])
                odo = _j(c.get(f"/api/patients/{pid}/odontogram"))
                res.ok("одонтограмма с состояниями", odo.get("ok") is True
                       and "carie" in json.dumps(odo), str(odo)[:200])
                perio = _j(c.get(f"/api/patients/{pid}/perio"))
                res.ok("пародонтограмма с осмотром", perio.get("ok") is True
                       and "Examen parodontal" in json.dumps(perio, ensure_ascii=False), str(perio)[:200])
                page = c.get(f"/admin/patient/{pid}/fisa043").body
                res.ok("043/e печатается с данными", "Maria Popescu" in page and "2003078140017" in page,
                       "в 043/e нет пациента или IDNP")
                res.ok("acord печатается с юрлицом демо", "Clinica Demo SRL" in c.get(f"/admin/patient/{pid}/acord").body,
                       "acord без юрлица")
                res.ok("карточка пациента (старая страница) открывается",
                       c.get(f"/admin/patient/{pid}?ui=legacy").status == 200, "")
            for path in ("/admin/all", "/admin/week", "/admin/medici", "/admin/stats",
                         "/admin/search", "/admin/settings"):
                res.check(f"{path} на засеве", c.get(path).status, 200)
            st = _j(c.get("/api/stats"))
            res.ok("аналитика считается на засеве", st.get("ok") is True, str(st)[:200])
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Заголовки и User-Agent — как их шлют на самом деле (Chrome 141, Firefox 143,
# Safari 17 и 15, браузеры мессенджеров, роботы и превью ссылок)
_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
_UA = {
    "Chrome": _CHROME,
    "Edge": _CHROME + " Edg/141.0.0.0",
    "Firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Safari 17": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/17.6 Safari/605.1.15"),
    "Safari 15 (iOS)": ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 "
                        "Mobile/15E148 Safari/604.1"),
    "Yandex Browser": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/138.0.0.0 YaBrowser/25.8.0.0 Safari/537.36"),
    "браузер Telegram": ("Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, "
                         "like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36 "
                         "Telegram-Android/12.0.1 (Samsung SM-A546B; Android 14; SDK 34; AVERAGE)"),
    "браузер Facebook": ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                         "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/22A3354 "
                         "[FBAN/FBIOS;FBAV/480.0.0.40.103;FBDV/iPhone15,2;FBSN/iOS;FBLC/ro_RO]"),
    "headless Edge": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) HeadlessChrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"),
    "Googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Googlebot Smartphone": ("Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.7390.54 "
                             "Mobile Safari/537.36 (compatible; Googlebot/2.1; "
                             "+http://www.google.com/bot.html)"),
    "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "YandexBot": "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "TelegramBot": "TelegramBot (like TwitterBot)",
    "Facebook": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "WhatsApp": "WhatsApp/2.23.20.0 A",
    "Skype": "Mozilla/5.0 (Windows NT 6.1; WOW64) SkypeUriPreview Preview/0.5",
    "Slack": "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
    "Discord": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
    "curl": "curl/8.9.1",
    "python-requests": "python-requests/2.32.3",
    "Go": "Go-http-client/2.0",
    "пустой": "",
}
_NAV = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Site": "same-site", "Sec-Fetch-User": "?1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_FETCH = {"Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
          "Sec-Fetch-Site": "same-origin", "Accept": "*/*"}
_SCRIPT = {"Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "script",
           "Sec-Fetch-Site": "same-origin"}
_OLD = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _hd(base: dict, ua: str, **extra) -> dict:
    return {**base, "User-Agent": _UA[ua], **extra}


def suite_gate_admit(res: Result) -> None:
    """Шлюз демо даёт слот только навигации браузера (demo/admit.py, 07.10).

    До 07.10 слот на час получал любой запрос без куки — робот, превью
    ссылки, /robots.txt, `curl …/health`, — и шести таких хватало, чтобы
    Олег увидел «Toate locurile demo sunt ocupate». Здесь — таблица
    решений, которую исполняет шлюз, на заголовках настоящих браузеров и
    роботов, в обе стороны: слот получают люди (иначе демо закрыто уже
    ПРАВИЛОМ) и не получают остальные."""
    sys.path.insert(0, str(ROOT))
    from demo import admit  # noqa: E402 — пакет демо лежит в корне репозитория
    res.ok("решение шлюза берётся из репозитория",
           pathlib.Path(admit.__file__).resolve() == (ROOT / "demo" / "admit.py").resolve(),
           admit.__file__)

    cases = []
    # люди: навигация вкладки — слот; без куки вовсе — сперва проба
    for ua in ("Chrome", "Edge", "Firefox", "Safari 17", "Yandex Browser",
               "браузер Telegram", "браузер Facebook"):
        cases.append((f"{ua}: переход на журнал — слот", "GET", "/admin", _hd(_NAV, ua), True,
                      admit.SLOT))
    cases += [
        ("Chrome без куки вовсе — проба, не слот", "GET", "/admin", _hd(_NAV, "Chrome"), False,
         admit.PROBE),
        ("Chrome: глубокая ссылка журнала — слот", "GET", "/admin/patient/5",
         _hd(_NAV, "Chrome"), True, admit.SLOT),
        # безголовый браузер — как посетитель: кадры сайта снимаются так
        ("headless Edge (кадры сайта) — слот", "GET", "/admin", _hd(_NAV, "headless Edge"), True,
         admit.SLOT),
        ("браузер без Sec-Fetch (Safari 15) — страница с кнопкой", "GET", "/admin",
         _hd(_OLD, "Safari 15 (iOS)"), True, admit.PAGE),
        ("переход внутри iframe — не слот", "GET", "/admin",
         _hd(_NAV, "Chrome", **{"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site"}),
         True, admit.PAGE),
        ("предзагрузка — не слот", "GET", "/admin",
         _hd(_NAV, "Chrome", **{"Sec-Purpose": "prefetch"}), True, admit.LATER),
        ("prerender — не слот", "GET", "/admin",
         _hd(_NAV, "Chrome", **{"Sec-Purpose": "prefetch;prerender"}), True, admit.LATER),
        ("робот, назвавшийся в UA, с заголовками навигации — не слот", "GET", "/admin",
         _hd(_NAV, "Googlebot Smartphone"), True, admit.PAGE),
        ("пустой User-Agent с заголовками навигации — не слот", "GET", "/admin",
         _hd(_NAV, "пустой"), True, admit.PAGE),
        # клиент без куки: fetch страницы (переход B4), API, формы
        ("fetch страницы (переход без перезагрузки) — не слот", "GET", "/admin/week",
         _hd(_FETCH, "Chrome"), True, admit.PAGE),
        ("GET /api/… — 401, не слот", "GET", "/api/schedule/live", _hd(_FETCH, "Chrome"), True,
         admit.API),
        ("POST /api/… — 401, не слот", "POST", "/api/patients", _hd(_FETCH, "Chrome"), True,
         admit.API),
        ("навигация на /api — 401, не слот", "GET", "/api", _hd(_NAV, "Chrome"), True, admit.API),
        ("форма без слота — на /admin", "POST", "/admin/appointment/add", _hd(_NAV, "Chrome"),
         True, admit.HOME),
        ("DELETE fetch без слота — 401", "DELETE", "/admin/x", _hd(_FETCH, "Chrome"), True,
         admit.API),
        ("HEAD журнала — не слот", "HEAD", "/admin", _hd(_NAV, "Chrome"), True, admit.PAGE),
        ("HEAD мимо журнала — 404", "HEAD", "/wp-login.php", _hd(_OLD, "curl"), False, admit.NONE),
        ("неизвестный адрес навигацией — на /admin", "GET", "/oricare", _hd(_NAV, "Chrome"), True,
         admit.HOME),
        ("сканер на /wp-login.php — 404", "GET", "/wp-login.php", _hd(_OLD, "curl"), False,
         admit.NONE),
        ("сканер на /.env — 404", "GET", "/.env", _hd(_OLD, "python-requests"), False, admit.NONE),
    ]
    for path, headers in (("/static/js/bundle.js", _hd(_SCRIPT, "Chrome")),
                          ("/static/css/panel.css", _hd(_OLD, "Googlebot")),
                          ("/favicon.ico", _hd(_OLD, "Googlebot")),
                          ("/manifest.webmanifest", _hd(_FETCH, "Chrome")),
                          ("/icon-180.png", _hd(_OLD, "Safari 15 (iOS)")),
                          ("/health", _hd(_OLD, "curl"))):
        cases.append((f"{path} без куки — отдаётся без слота", "GET", path, headers, False,
                      admit.PUBLIC))
    # роботы, превью ссылок, скрипты: без заголовков навигации — страница демо
    for ua in ("Googlebot", "bingbot", "YandexBot", "TelegramBot", "Facebook", "WhatsApp",
               "Skype", "Slack", "Discord", "curl", "python-requests", "Go"):
        cases.append((f"{ua} на журнал — страница демо, не слот", "GET", "/admin",
                      _hd(_OLD, ua), True, admit.PAGE))
    res.ok("таблица решений не пуста", len(cases) > 40, str(len(cases)))
    for label, method, path, headers, has_cookie, want in cases:
        res.check(label, admit.classify(method, path, headers, has_cookie), want)

    # второй рубеж — строка UA: роботы ловятся, браузеры нет (YaBrowser рядом
    # с YandexBot, браузеры внутри мессенджеров, безголовый Edge)
    for ua in ("Googlebot", "bingbot", "YandexBot", "TelegramBot", "Facebook", "Skype",
               "Slack", "Discord", "curl", "python-requests", "Go", "пустой"):
        res.ok(f"робот по UA: {ua}", admit.robot(_UA[ua]), _UA[ua])
    for ua in ("Chrome", "Edge", "Firefox", "Safari 17", "Safari 15 (iOS)", "Yandex Browser",
               "браузер Telegram", "браузер Facebook", "headless Edge"):
        res.ok(f"браузер не робот: {ua}", not admit.robot(_UA[ua]), _UA[ua])

    res.ok("robots.txt закрывает всё", "Disallow: /\n" in admit.ROBOTS_TXT
           and "User-agent: *" in admit.ROBOTS_TXT, admit.ROBOTS_TXT)

    # куда вести после выдачи: только журнал, не вход/выход и не чужой хост
    for raw, want in (("/admin", "/admin"),
                      ("/admin/patient/5?tab=odo", "/admin/patient/5?tab=odo"),
                      ("/admin?d=2026-10-07", "/admin?d=2026-10-07"),
                      ("/admin/search?q=Ștefan", "/admin/search?q=Ștefan"),
                      ("", "/admin"), ("/administrator", "/admin"),
                      ("//evil.example/admin", "/admin"), ("https://evil.example/admin", "/admin"),
                      ("/admin//evil.example", "/admin"), ("/admin/\\evil.example", "/admin"),
                      ("/admin/login?next=/admin/week", "/admin"), ("/admin/logout", "/admin"),
                      ("/demo/reset", "/admin"), ("/admin/x\r\nSet-Cookie: a=b", "/admin")):
        res.check(f"next {raw!r}", admit.safe_next(raw), want)
