"""Поисковики: облако не попадает в выдачу (12.10.2026, письмо Search Console).

Запрет — заголовком `X-Robots-Tag: noindex` на каждом ответе; robots.txt обход
НЕ закрывает — иначе поисковик не увидит запрета, а адреса облака, на которые
ссылается сайт, проиндексирует голыми (разбор — app/robots.py).
"""
from __future__ import annotations

import re

from harness import Client, Result, Server, cid_from
from test_account import FakeGitHub, _letters


def _tagged(r) -> bool:
    return "noindex" in r.headers.get("x-robots-tag", "")


def suite(res: Result) -> None:
    gh = FakeGitHub()
    with Server(env=gh.env) as s:
        c = Client(s.url)
        r = c.get("/robots.txt")
        res.ok("robots.txt отвечает 200 текстом", r.status == 200
               and r.headers.get("content-type", "").startswith("text/plain"), f"{r.status} {r.headers.get('content-type')}")
        res.ok("robots.txt — для всех роботов", "User-agent: *" in r.body, r.body)
        # ⛔ «починить» его до Disallow: / — значит спрятать от поисковика сам запрет
        # индексации: адрес /cont, на который ссылается сайт, ушёл бы в выдачу голым
        res.ok("robots.txt не закрывает обход целиком (запрет — заголовком)",
               not re.search(r"(?mi)^\s*Disallow:\s*/\s*$", r.body), r.body)

        # те адреса, на которые ссылается сайт (dentpilot.md), и те, куда они ведут
        site = {
            "/cont (ссылка «Logare / Înregistrare»)": ("/cont", 303),
            "/cont/login": ("/cont/login", 200),
            "/proba (форма пробного)": ("/proba", 200),
            "/descarca (кнопка скачивания)": ("/descarca", 302),
            "/ (корень)": ("/", 303),
        }
        for label, (path, want) in site.items():
            r = c.get(path)
            res.ok(f"{label}: ответ прежний ({want}) и с noindex", r.status == want and _tagged(r),
                   f"{r.status} {r.headers.get('x-robots-tag')!r}")
        # и всё остальное: вход админки, JSON программы, 404, отказ
        others = {
            "/admin/login": c.get("/admin/login"),
            "/health (JSON)": c.get("/health"),
            "/robots.txt сам": c.get("/robots.txt"),
            "неизвестный адрес — 404": c.get("/nu-exista"),
            "/v1/update без канала (JSON программы)": c.get("/v1/update"),
            "POST входа с чужим Origin — 403": c.post("/admin/login", user="x", password="y",
                                                      headers={"Origin": "http://evil.example", "Host": f"127.0.0.1:{s.port}"}),
        }
        for label, r in others.items():
            res.ok(f"{label}: noindex", _tagged(r), f"{r.status} {r.headers.get('x-robots-tag')!r}")
        res.check("значение заголовка — одно и полное", c.get("/health").headers.get("x-robots-tag"), "noindex, nofollow")
        res.check("неизвестный адрес — по-прежнему 404", c.get("/nu-exista").status, 404)


def suite_root(res: Result) -> None:
    """Корень облака — кабинет клиники, не админка (09.11): первая посторонняя клиника открыла
    cloud.dentpilot.md/ и вписала свой e-mail во вход администратора. Гость с корня — ко входу
    кабинета, вошедший — в свой кабинет; /admin — только прямым адресом, публичные страницы на
    него не ссылаются."""
    with Server(env={"DP_TRIAL_MODE": "auto"}) as s:
        anon = Client(s.url)
        r = anon.get("/")
        res.check("корень → кабинет клиники (303 /cont), не /admin", (r.status, r.location), (303, "/cont"))
        r = anon.get("/cont")
        res.check("гость с корня дальше — ко входу кабинета", (r.status, r.location), (303, "/cont/login"))
        res.check("/admin по прямому адресу — как раньше, вход администратора",
                  (lambda x: (x.status, x.location))(anon.get("/admin")), (303, "/admin/login"))
        public = {"/cont/login": anon.get("/cont/login"), "/proba": anon.get("/proba")}
        # вошедший в кабинет (код на ящик клиники, заведённой в админке): корень → его кабинет
        admin = Client(s.url).login()
        cid_from(admin.post("/admin/clinics", name="Clinica Radacina", idno="7007007007007",
                            email="radacina@example.md").location)
        c = Client(s.url)
        r = c.post("/cont/login/email", email="radacina@example.md")
        vid = re.search(r"name='verify_id' value='([^']+)'", r.body)
        code = re.search(r": (\d{6})\n", _letters(s)[-1][2])
        r = c.post("/cont/login/cod", verify_id=vid.group(1) if vid else "", code=code.group(1) if code else "",
                   email="radacina@example.md")
        res.check("вход кодом прошёл — в кабинет", (r.status, r.location), (303, "/cont"))
        r = c.get("/")
        res.check("вошедший: корень → /cont", (r.status, r.location), (303, "/cont"))
        home = c.get("/cont")
        res.ok("вошедший: /cont — его кабинет", home.status == 200 and "Clinica Radacina" in home.body, repr(home)[:200])
        public["/cont (кабинет)"] = home
        for label, page in public.items():
            res.ok(f"{label}: 200 и ни одной ссылки на админку", page.status == 200 and "/admin" not in page.body,
                   f"{page.status} {page.body[max(0, page.body.find('/admin') - 120):][:240]!r}")
