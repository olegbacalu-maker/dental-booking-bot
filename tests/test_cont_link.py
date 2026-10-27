"""«Deschide contul clinicii» — кабинет своей клиники из программы без кода (27.10).

Решение — core/license.py (`cont_link`), кнопка — страница лицензии (layout.py `_cont_block`),
вход — маршрут `/cont/<ключ>` (modules/license/routes.py), сервер — cloud/app/contlink.py.
Сервер лицензий подменён стендом из test_license_renew: нужны ответы, которых настоящий сервер
не даёт (чужой адрес, страница оплаты вместо входа, 401, тишина). Что настоящий сервер и
провод программы понимают друг друга — cloud/tests/test_contlink.py.

⭐ Что держит набор, словами cloud.md › «Plătește acum» (тот же путь):
- ссылка открывается СИСТЕМНЫМ браузером без куки входа — пропуск только ключ, ключ рисуют
  только директору (⛔ маршрут без `_guard`);
- браузер уходит ТОЛЬКО на одноразовый вход `/cont/intra/<id>` того сервера, что выдал файл —
  даже его же /plata/ не годится;
- без сервера — страница словами в том же браузере.
"""
import json
import pathlib
import re
import shutil
import tempfile

from harness import Client, Result, Server, _rmtree_settled
from test_license_renew import FIX, KEY_ENV, TOKEN, Stand, _api, _file, _log, _wait_renew

CONT = "/v1/cont-link"
BUTTON = re.compile(r"href='/cont/([A-Za-z0-9_-]{20,})' target='_blank' rel='noopener'>(?:<svg.*?</svg>)? ?"
                    r"Deschide contul clinicii", re.S)


def _ticket(body: str) -> str:
    m = BUTTON.search(body)
    return m.group(1) if m else ""


def suite_cont(res: Result) -> None:
    """Директор → кнопка → браузер в кабинете сервера; отказы словами."""
    stand = Stand()
    renew = {"url": stand.url, "token": TOKEN}
    entry = stand.base + "/cont/intra/abc123"
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_cont_"))
    try:
        (d / "license.json").write_text(_file(8, renew), encoding="utf-8")
        stand.serve(204)
        stand.answer(200, {"ok": True, "url": entry, "expires_at": "2026-10-27T10:05:00Z"}, path=CONT)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _wait_renew(c)
            res.ok("активный файл с сервером", a.get("state") == "active", repr(a))
            lp = c.get("/admin/license").body
            ticket = _ticket(lp)
            res.ok("страница лицензии директору: «Deschide contul clinicii» — в новое окно с ключом",
                   bool(ticket), lp[-1800:])
            res.ok("ключ — тот же, что у «Plătește acum» (один на процесс)",
                   f"href='/plata/{ticket}'" in lp)
            res.ok("порядок: срок → Plătește acum → Deschide contul clinicii",
                   0 < lp.find("Valabil până la") < lp.find("Plătește acum") < lp.find("Deschide contul clinicii"))

            anon = Client(s.url)                     # системный браузер: без куки, только ключ
            r = anon.get(f"/cont/{ticket}")
            res.ok("по ключу без входа: 303 прямо на одноразовый вход сервера",
                   r.status == 303 and r.location == entry, repr(r))
            sent = [p for p in stand.posts if p["path"] == CONT]
            res.ok("запрос ушёл на сервер файла с его токеном",
                   len(sent) == 1 and sent[0]["auth"] == f"Bearer {TOKEN}"
                   and sent[0]["agent"].startswith("DentPilot/"), repr(sent))
            res.ok("частого запроса файла кнопка не заводит (в кабинете не платят сразу)",
                   _api(c).get("paying_until") is None)
            res.ok("в логе сервера — исход нажатия", "license: cont=ok" in _log(s))

            r = anon.get("/cont/" + "x" * 24)
            res.ok("чужой ключ: 404 словами, без перехода",
                   r.status == 404 and "Linkul a expirat" in r.body and not r.location, repr(r))
            bad = {"чужой сервер": "https://evil.example/cont/intra/abc123",
                   "тот сервер, страница оплаты": stand.base + "/plata/abc123",
                   "тот сервер, вход без id": stand.base + "/cont/intra/",
                   "тот сервер, путь глубже": stand.base + "/cont/intra/abc/../../admin",
                   "тот сервер, с запросом": entry + "?next=/admin"}
            for why, url in bad.items():
                stand.answer(200, {"ok": True, "url": url}, path=CONT)
                r = anon.get(f"/cont/{ticket}")
                res.ok(f"⛔ {why}: перехода нет, страница словами",
                       r.status == 503 and not r.location and "nu a răspuns" in r.body, f"{url} → {r.status}")
            stand.answer(429, {"ok": False, "code": "limited"}, path=CONT)
            r = anon.get(f"/cont/{ticket}")
            res.ok("лимит сервера: словами «nu a răspuns … câteva minute»",
                   r.status == 503 and "câteva minute" in r.body, repr(r))
            stand.answer(401, {"ok": False, "code": "token_unknown"}, path=CONT)
            r = anon.get(f"/cont/{ticket}")
            res.ok("токен не признан: страница словами", r.status == 503 and "nu a recunoscut licența" in r.body)
            stand.close()
            r = anon.get(f"/cont/{ticket}")
            res.ok("сервера нет (без интернета): страница словами",
                   r.status == 503 and "Serverul DentPilot nu a răspuns" in r.body
                   and "conexiunea la internet" in r.body, repr(r))
    finally:
        stand.close()
        _rmtree_settled(d)

    # не директор: ни кнопки, ни ключа. Отдельным сервером — первая учётка переводит вход на PIN
    stand = Stand()
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_cont2_"))
    try:
        (d / "license.json").write_text(_file(8, {"url": stand.url, "token": TOKEN}), encoding="utf-8")
        stand.serve(204)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            c.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "3333"})
            ana = Client(s.url)
            ana.post("/admin/login", password="3333", next="/admin")
            lp = ana.get("/admin/license").body
            res.ok("регистратуре: страница лицензии без кнопки кабинета и без ключа",
                   "Licența programului" in lp and "Deschide contul clinicii" not in lp and "/cont/" not in lp,
                   lp[-1200:])
    finally:
        stand.close()
        _rmtree_settled(d)


def suite_off(res: Result) -> None:
    """Кабинета нет — кнопки нет: файл без сервера, программа без ключей выдачи."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_cont3_"))
    try:
        shutil.copy(FIX / "expired.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            res.ok("файл без renew: кнопки нет", "Deschide contul clinicii" not in c.get("/admin/license").body)
            res.check("маршрут с чужим ключом — 404", Client(s.url).get("/cont/" + "y" * 24).status, 404)
    finally:
        _rmtree_settled(d)
    with Server() as s:
        c = Client(s.url).login()
        res.check("без ключей выдачи маршрут — 404", Client(s.url).get("/cont/" + "z" * 24).status, 404)
        lp = c.get("/admin/license").body
        res.ok("без ключей выдачи кнопки нет", "Deschide contul clinicii" not in lp)
        items = json.loads(c.get("/api/settings/faq").body)["data"]["items"]
        card = next((it["answer"] for it in items if it["question"] == "Cum plătesc abonamentul?"), "")
        res.ok("FAQ «Cum plătesc abonamentul?» называет кнопку и что видно по ней",
               "Deschide contul clinicii" in card and "doar clinica acestui program" in card, card[-600:])
