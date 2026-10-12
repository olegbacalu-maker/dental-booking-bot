"""Поисковики: облако не попадает в выдачу (12.10.2026, письмо Search Console).

Запрет — заголовком `X-Robots-Tag: noindex` на каждом ответе; robots.txt обход
НЕ закрывает — иначе поисковик не увидит запрета, а адреса облака, на которые
ссылается сайт, проиндексирует голыми (разбор — app/robots.py).
"""
from __future__ import annotations

import re

from harness import Client, Result, Server
from test_account import FakeGitHub


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
