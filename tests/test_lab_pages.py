"""«Laborator»: страницы-оболочки — список заказов и каталог лабораторий, пункт меню, плитка, права в оболочке.

Данные и команды раздела держит `test_lab.py`; здесь только то, что отдают `modules/lab/pages.py`,
`layout.shell_model` и хаб настроек: React-экран по адресу, кому открыта страница каталога.
"""
from __future__ import annotations

import json
import re

from harness import BOT, Client, Result, Server, shell_model
from test_api import NO_KEY

PAGES = BOT / "app" / "modules" / "lab" / "pages.py"


def _screen(page: str) -> str:
    m = re.search(r'data-screen="([^"]+)"', page)
    return m.group(1) if m else ""


def _team(s: Server) -> tuple[Client, Client, Client]:
    """Директор (PIN 1111), регистратура (4444), врач (2222)."""
    boss = Client(s.url)
    boss.post("/admin/setup", pin1="1111", pin2="1111")
    for body in ({"uid": "d3", "name": "Dr. Activ Trei", "role": "medic", "doctor_id": "d3", "pin": "2222"},
                 {"uid": "ana", "name": "Ana Rusu", "role": "receptie", "pin": "4444"}):
        r = boss.post_json("/api/settings/users", body)
        if r.status != 200:
            raise AssertionError(f"учётка не заведена: {r.status} {r.body[:200]}")

    def login(pin: str) -> Client:
        x = Client(s.url)
        x.post("/admin/login", password=pin, next="/admin")
        return x
    return boss, login("4444"), login("2222")


def suite_pages(res: Result) -> None:
    """Список — всем вошедшим, каталог — стойке и директору; пункт меню у всех, `can.labs` — по праву."""
    res.ok("исходники нашлись", PAGES.exists(), str(PAGES))
    with Server(env=NO_KEY) as s:
        boss, ana, med = _team(s)
        for who, c, labs in (("директор", boss, True), ("регистратура", ana, True), ("врач", med, False)):
            page = c.get("/admin").body
            m = shell_model(page)
            keys = [i["key"] for i in m["nav"]["items"]]
            res.ok(f"{who}: пункт «Laborator» сразу после «Pacienți»", keys[keys.index("pat") + 1:keys.index("pat") + 2] == ["lab"], f"{keys}")
            res.check(f"{who}: can.labs в оболочке", m["identity"]["can"].get("labs"), labs)
            r = c.get("/admin/lab")
            res.check(f"{who}: список — React-экран «lab»", (r.status, _screen(r.body)), (200, "lab"))
            res.check(f"{who}: список — раздел «Laborator» в меню подсвечен", shell_model(r.body)["nav"]["active"], "lab")
        r = ana.get("/admin/settings/lab")
        res.check("регистратура: каталог — React-экран «settings_lab»", (r.status, _screen(r.body)), (200, "settings_lab"))
        res.check("регистратура: каталог живёт в разделе «Setări»", shell_model(r.body)["nav"]["active"], "set")
        res.ok("врач: страница каталога — отказ", med.get("/admin/settings/lab").status in (303, 403))
        res.check("без входа: список уводит на вход", Client(s.url).get("/admin/lab").status, 303)
        hub = json.loads(boss.get("/api/settings/hub").body)["data"]
        tile = [t for t in hub["tiles"] if t["href"] == "/admin/settings/lab"]
        res.check("плитка «Laboratoare» в группе «Medici»", [(t["label"], t["group"]) for t in tile], [("Laboratoare", "medici")])
