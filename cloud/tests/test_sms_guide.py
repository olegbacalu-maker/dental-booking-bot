"""Гид кабинета «Cum cereți numele clinicii în SMS» (`sms_guide.py`) и ссылка на него в карточке имени.

Что держит набор:
- страница — за входом кабинета и только там, где клинике показан раздел SMS; данных клиники в ней нет;
- цена года имени на странице — та, что в прайсе сервера; без цены страница о плате молчит; числа
  с «MDL» в исходнике гида нет;
- ссылка на гид стоит в карточке имени во всех состояниях имени у главной клиники и в виде филиала;
- слова гида в «ёлочках» — названия кнопок, полей и меток — те же, что кабинет показывает в карточке:
  каждое равно надписи элемента кабинета (кнопки, подписи поля, заголовка, метки) в одном из состояний
  или открывает её до знака препинания; иначе это слово программы или пример. Совпадения куска фразы
  мало: «Încarcă cererea» внутри «Încarcă cererea semnată» — уже другая кнопка.

Цена имени здесь — подмена `DP_SMS_NAME_PRICE` стенда; настоящих цен в репозитории нет.
"""
import html
import re
import sys

from harness import CLOUD, ROOT, Client, Result, Server

sys.path.insert(0, str(CLOUD))
from app import sms_guide  # noqa: E402
from test_branches import BRANCH, DIRECTOR, IDNO, _add, _enter, _register  # noqa: E402
from test_sms import FakeSmsMd, _clinic_with_license, _sql  # noqa: E402
from test_sms_cabinet import ENV, _pane  # noqa: E402
from test_sms_name import DATA, PDF  # noqa: E402
from test_sms_paper import _cabinet, _upload  # noqa: E402

GUIDE = "/cont/sms/ghid"
# слова гида, которых в кабинете нет: названия программы (сверяются с её исходниками) и примеры имени
PROGRAM = ("Deschide contul clinicii", "Licență")
EXAMPLES = ("DentPilot", "LuminaDent", "Lumina Dent", "Lumina-Dent")


def _text(page: str) -> str:
    """Страница словами: без разметки и стилей, пробелы схлопнуты."""
    page = re.sub(r"<(style|script)\b.*?</\1>", "", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", page)).split())


def _quoted(page: str) -> list[str]:
    return sorted({w.rstrip("…") for w in re.findall(r"«([^«»]+)»", _text(page))})


def _labels(page: str) -> set:
    """Надписи элементов страницы: кнопки, подписи полей, заголовки, метки, ссылки, выделенное."""
    page = re.sub(r"<(style|script|svg)\b.*?</\1>", "", page, flags=re.S)
    return {_text(m.group(2)) for m in re.finditer(r"<(button|label|summary|h2|b|span|a)\b[^>]*>(.*?)</\1>", page, re.S)}


def _named(word: str, labels: set) -> bool:
    """Слово гида — надпись целиком или её начало до знака препинания («Pentru cerere lipsesc…: adresa»)."""
    return any(x == word or (x.startswith(word) and x[len(word):len(word) + 1] in tuple(".:,;")) for x in labels)


def _link(pane: str) -> bool:
    card = pane[pane.find("SMS · numele expeditorului"):]
    return f"href='{GUIDE}'" in card and sms_guide.LINK in card


def suite_page(res: Result) -> None:
    """Вход, цена с сервера, клиника без раздела SMS, филиал."""
    res.check("адрес гида в модуле — тот же, что у маршрута", sms_guide.PATH, GUIDE)
    src = (CLOUD / "app" / "sms_guide.py").read_text(encoding="utf-8")
    res.check("в исходнике гида нет цены числом", re.findall(r"\d[\d ]*\s*(?:MDL|lei)\b", src), [])
    with Server(env={**ENV, "DP_SMS_NAME_PRICE": "77"}) as s:
        r = Client(s.url).get(GUIDE)
        res.check("без входа гид ведёт на вход кабинета", (r.status, r.location), (303, "/cont/login"))
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        r = c.get(GUIDE)
        res.ok("гид открыт вошедшему: заголовок, каркас кабинета, ссылка назад во вкладку SMS",
               r.status == 200 and f"<h1>{sms_guide.TITLE}</h1>" in r.body and "Contul clinicii" in r.body
               and "action='/cont/iesire'" in r.body and "href='/cont#sms'" in r.body, f"{r.status} {r.body[:400]}")
        res.ok("цена года имени на странице — из прайса сервера",
               "Numele propriu se plătește pe un an: 77 MDL." in _text(r.body) and "Plătiți anul numelui" in r.body)
        res.ok("на странице нет данных клиники", IDNO not in r.body and "Ion Rusu" not in r.body)
        res.ok("ссылка на гид — в карточке имени, пока имени нет", _link(_pane(c.get("/cont").body, "sms")))
        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        pane = _pane(c.get(f"/cont?c={bid}").body, "sms")
        card = pane[pane.find("SMS · numele expeditorului"):]
        res.ok("вид филиала: ссылка на гид есть и несёт открытую клинику",
               f"href='{GUIDE}?c={bid}'" in card and "/cont/sms/nume" not in card, card[-1500:])
        r = c.get(f"{GUIDE}?c={bid}")
        res.ok("гид с клиникой кабинета: ссылки ведут в её вкладки",
               r.status == 200 and f"href='/cont?c={bid}#sms'" in r.body, f"{r.status}")
        r = c.get(f"{GUIDE}?c=c_strain")
        res.check("гид с чужой клиникой в адресе — на кабинет", (r.status, r.location), (303, "/cont"))
    with Server(env={**ENV, "DP_SMS_NAME_PRICE": "91"}) as s:
        c = _enter(s, DIRECTOR)
        _register(s, c)
        text = _text(c.get(GUIDE).body)
        res.ok("другой прайс сервера — другая цена на странице, прежней нет",
               "pe un an: 91 MDL." in text and "77" not in text, text[:300])
    with Server(env=ENV) as s:
        c = _enter(s, DIRECTOR)
        _register(s, c)
        text = _text(c.get(GUIDE).body)
        res.ok("без цены в прайсе гид о плате молчит, как карточка: ни суммы, ни шага оплаты",
               "MDL" not in text and "Plătiți anul numelui" not in text and "Descărcați cererea completată" in text,
               text[:300])
    with Server(env={k: v for k, v in ENV.items() if k != "DP_SMS_OFFERED"}) as s:
        c = _enter(s, DIRECTOR)
        _register(s, c)
        r = c.get(GUIDE)
        res.check("клинике без раздела SMS гид не показан — на кабинет", (r.status, r.location), (303, "/cont"))
        res.ok("у неё и ссылки на гид нет", GUIDE not in c.get("/cont").body)


def suite_words(res: Result) -> None:
    """Имя от заявки до одобрения: ссылка на гид в каждом состоянии; слова гида — слова кабинета."""
    fake = FakeSmsMd()
    seen = set()
    try:
        with Server(env={**fake.env(), "DP_SMS_NAME_PRICE": "77", "DP_MAIB_BASE_URL": "http://127.0.0.1:9",
                         "DP_MAIB_CLIENT_ID": "c", "DP_MAIB_CLIENT_SECRET": "s", "DP_MAIB_SIGNATURE_KEY": "k"}) as s:
            admin = Client(s.url).login()
            cid, _token = _clinic_with_license(admin, s, "Zambet Dent", "zd@example.md")
            cab = _cabinet(s, "zd@example.md")

            def look(what: str) -> str:
                page = cab.get("/cont").body
                seen.update(_labels(page))
                res.ok(f"ссылка на гид в карточке имени: {what}", _link(_pane(page, "sms")))
                return page

            look("имени нет")
            cab.post("/cont/sms/nume", name="Zambet Dent")
            look("заявка без реквизитов клиники")
            cab.post("/cont/date", name="Zambet Dent", **DATA)
            page = look("заявка, шаги")
            res.ok("кнопка карты в форме оплаты есть (стенд с maib)", "Plătește cu cardul" in page)
            _upload(cab, PDF)
            cab.post("/cont/sms/nota", name="1", method="transfer", terms="1")
            look("заявление загружено, нота ждёт")
            pid = _sql(s, "SELECT id FROM payments WHERE kind='sms_name'")[0][0]
            admin.post(f"/admin/payments/{pid}/confirm")
            look("год оплачен до одобрения")
            admin.post(f"/admin/clinics/{cid}/sms", action="submitted")
            look("подано операторам")
            fake.aliases["Zambet Dent"] = 1
            admin.post("/admin/sms/sync")
            look("одобрено и оплачено")
            fake.aliases["Zambet Dent"] = 3
            admin.post("/admin/sms/sync")
            look("отказано")

            guide = cab.get(GUIDE).body
            words = _quoted(guide)
            res.ok("в гиде названы кнопки и шаги (слов в «ёлочках» не меньше десяти)", len(words) >= 10, repr(words))
            program = "".join(f.read_text(encoding="utf-8", errors="replace")
                              for f in sorted((ROOT / "bot" / "app").rglob("*.py")))
            res.ok("исходники программы нашлись", len(program) > 100_000)
            res.check("⛔ слова гида в «ёлочках» — те же, что в кабинете (или слово программы, пример)",
                      [w for w in words if not _named(w, seen) and w not in EXAMPLES
                       and not (w in PROGRAM and w in program)], [])
            res.check("список слов программы не гниёт: каждое названо в гиде", [w for w in PROGRAM if w not in words], [])
            order = [guide.find(f"<li><b>{t}</b>") for t in
                     ("Descărcați cererea completată", "Semnați-o", "Încărcați cererea semnată",
                      "Plătiți anul numelui", "O depunem la SMS.MD")]
            res.ok("пять шагов гида — заголовками карточки и в её порядке", -1 not in order and order == sorted(order),
                   repr(order))
    finally:
        fake.close()


def _webp_size(data: bytes) -> tuple:
    """(ширина, высота) из заголовка WebP с потерями (VP8); иное — (0, 0)."""
    if data[:4] != b"RIFF" or data[8:16] != b"WEBPVP8 ":
        return 0, 0
    return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF


def _raw(c: Client, url: str) -> tuple:
    """(код, байты, заголовки): `Client.get` читает тело текстом, картинке нужны байты."""
    with c.opener.open(url, timeout=30) as r:
        return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}


def suite_frames(res: Result) -> None:
    """Кадры гида: файлы репозитория по ключу словаря, за входом, с верным типом."""
    res.ok("кадров три-четыре", 3 <= len(sms_guide.FRAMES) <= 4, repr(list(sms_guide.FRAMES)))
    files = sorted(f.name for f in sms_guide.ASSETS.iterdir())
    res.check("в папке кадров — ровно файлы словаря",
              files, sorted(f[0] for f in sms_guide.FRAMES.values()))
    big = {k: len(sms_guide.frame(k) or b"") for k in sms_guide.FRAMES}
    res.ok("каждый кадр — не пустой и не тяжелее 150 КБ", all(0 < n <= 150_000 for n in big.values()), repr(big))
    res.check("размеры в словаре — размеры файлов (страница не прыгает при загрузке)",
              {k: _webp_size(sms_guide.frame(k) or b"") for k in sms_guide.FRAMES},
              {k: (f[1], f[2]) for k, f in sms_guide.FRAMES.items()})
    with Server(env={**ENV, "DP_SMS_NAME_PRICE": "77"}) as s:
        one = next(iter(sms_guide.FRAMES))
        r = Client(s.url).get(f"{GUIDE}/cadru/{one}")
        res.check("без входа кадр не отдаётся — на вход кабинета", (r.status, r.location), (303, "/cont/login"))
        c = _enter(s, DIRECTOR)
        _register(s, c)
        page = c.get(GUIDE).body
        res.check("страница показывает каждый кадр словаря",
                  sorted(re.findall(rf"<img src='{GUIDE}/cadru/([^']+)'", page)), sorted(sms_guide.FRAMES))
        for key in sms_guide.FRAMES:
            status, data, hdr = _raw(c, s.url + f"{GUIDE}/cadru/{key}")
            res.ok(f"кадр «{key}»: те же байты, что в репозитории, image/webp, nosniff, кэш браузера",
                   status == 200 and data == sms_guide.frame(key) and hdr.get("content-type") == "image/webp"
                   and hdr.get("x-content-type-options") == "nosniff"
                   and hdr.get("cache-control") == "private, max-age=86400", f"{status} {hdr}")
        got = [c.get(f"{GUIDE}/cadru/{k}").status for k in
               ("nimic", "pasi.webp", "..%2Fmodele%2Fbitlocker.html", "%2E%2E%2F%2E%2E%2Fsms.py")]
        res.check("⛔ кадр — только по ключу словаря: неизвестный ключ, имя файла и путь — 404", got, [404] * 4)


SUITES = [
    ("Гид имени SMS в кабинете: кадры — по ключу словаря, за входом, WebP до 150 КБ", suite_frames),
    ("Гид имени SMS в кабинете: вход, цена прайса сервера, клиника без SMS, филиал", suite_page),
    ("Гид имени SMS в кабинете: ссылка в каждом состоянии имени, слова гида — слова карточки", suite_words),
]

if __name__ == "__main__":
    from harness import run
    sys.exit(run(SUITES))
