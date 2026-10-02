"""«Plătește acum» — оплата из программы (02.10): половина программы к /v1/pay-link.

Провод — core/license_renew.py (`pay_link`), решение — core/license.py, ссылка —
баннер и страница лицензии (layout.py), вход — маршрут `/plata/<ключ>` (main.py).
Сервер лицензий подменён стендом из test_license_renew: нужны ответы, которых
настоящий сервер не даёт (чужой адрес в ответе, 401, тишина). Что настоящий
сервер и этот провод понимают друг друга — cloud/tests/test_paylink.py.

⭐ Что держит набор, словами cloud.md › «Оплата из программы»:
- ссылка открывается СИСТЕМНЫМ браузером без куки входа — пропуск только ключ,
  и ключ рисуют только директору;
- браузер уходит ТОЛЬКО на страницу оплаты того сервера, что выдал файл;
- после нажатия программа сама берёт новый файл за секунды, без кнопок, —
  ради этого частый запрос (PAY_WATCH), и он гаснет вместе с оплатой.
"""
import json
import pathlib
import re
import shutil
import tempfile

from harness import Client, Result, Server, _rmtree_settled
from test_license_renew import (FIX, KEY_ENV, TOKEN, Stand, _api, _file, _log, _until,
                                _wait_renew, rn)

PAY = "/v1/pay-link"
TICKET = re.compile(r"href='/plata/([A-Za-z0-9_-]{20,})' target='_blank' rel='noopener'>Plătește acum")


def _ticket(body: str) -> str:
    m = TICKET.search(body)
    return m.group(1) if m else ""


def _hub(c: Client) -> list[dict]:
    r = c.get("/api/settings/hub")
    return json.loads(r.body).get("data", {}).get("tiles", []) if r.status == 200 else []


def _tile(c: Client) -> dict:
    return next((t for t in _hub(c) if t.get("href") == "/admin/license"), {})


def _hint(t: dict) -> str:
    return "".join(p.get("t", "") for p in t.get("hint", []))


# ---------- провод ----------


def suite_wire(res: Result) -> None:
    """`rn.pay_link`: POST с Bearer, исход по коду, тело — только словарь."""
    stand = Stand()
    try:
        url = stand.base + PAY
        page = stand.base + "/plata/abc123"
        stand.answer(200, {"ok": True, "url": page, "expires_at": "2026-10-04T10:00:00Z"}, path=PAY)
        out, data = rn.pay_link(url, TOKEN, timeout=5, agent="DentPilot/test",
                                extra={"X-DentPilot-Device": "d_0a1b2c3d4e5f"})
        res.ok("200 с ok: ACCEPTED и адрес страницы", out == rn.ACCEPTED and data.get("url") == page,
               repr((out, data)))
        sent = stand.posts[-1]
        res.ok("POST на /v1/pay-link с Bearer-токеном файла и личностью машины",
               sent["path"] == PAY and sent["auth"] == f"Bearer {TOKEN}"
               and sent["agent"] == "DentPilot/test" and sent["device"] == "d_0a1b2c3d4e5f", repr(sent))
        stand.answer(200, {"ok": False}, path=PAY)
        res.check("200 без ok: OFFLINE", rn.pay_link(url, TOKEN, timeout=5), (rn.OFFLINE, {}))
        stand.answer(401, {"ok": False, "code": "token_unknown"}, path=PAY)
        res.check("401: REFUSED", rn.pay_link(url, TOKEN, timeout=5), (rn.REFUSED, {}))
        stand.answer(500, {"text": "x"}, path=PAY)
        res.check("500: OFFLINE", rn.pay_link(url, TOKEN, timeout=5), (rn.OFFLINE, {}))
        stand.answer(302, None, path=PAY)
        res.check("редирект не исполняется: OFFLINE", rn.pay_link(url, TOKEN, timeout=5), (rn.OFFLINE, {}))
        res.check("чужой путь (404): OFFLINE", rn.pay_link(stand.base + "/v1/nu-exista", TOKEN, timeout=5),
                  (rn.OFFLINE, {}))
    finally:
        stand.close()
    res.check("сервера нет: OFFLINE", rn.pay_link(url, TOKEN, timeout=2), (rn.OFFLINE, {}))


# ---------- живой сценарий ----------


def suite_pay(res: Result) -> None:
    """Режим чтения → «Plătește acum» → браузер на странице оплаты → файл пришёл сам."""
    stand = Stand()
    renew = {"url": stand.url, "token": TOKEN}
    page = stand.base + "/plata/abc123"
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_pay_"))
    try:
        (d / "license.json").write_text(_file(8, renew, expired=True), encoding="utf-8")
        stand.serve(204)
        stand.answer(200, {"ok": True, "url": page, "expires_at": "2026-10-04T10:00:00Z"}, path=PAY)
        # частый запрос — раз в секунду вместо минуты, как у заявки
        with Server(dir_=d, env={**KEY_ENV, "DENTART_LICENSE_PENDING_S": "1"}) as s:
            c = Client(s.url).login()
            a = _wait_renew(c)
            res.ok("просроченный файл с сервером: readonly, оплата доступна, частого запроса нет",
                   a.get("state") == "readonly" and a.get("pay") is True and a.get("paying_until") is None,
                   repr(a))

            lp = c.get("/admin/license").body
            ticket = _ticket(lp)
            res.ok("страница лицензии: «Plătește acum» — ссылка в новое окно с ключом", bool(ticket), lp[-1500:])
            res.ok("в режиме чтения оплата стоит ПЕРВОЙ, раньше срока и «Verifică acum»",
                   0 < lp.find("Plătește acum") < lp.find("Valabil până la") < lp.find("/admin/license/renew"))
            journal = c.get("/admin?ui=legacy").body
            res.ok("баннер журнала: та же ссылка и «achitați abonamentul»",
                   f"href='/plata/{ticket}'" in journal and "achitați abonamentul" in journal)
            res.ok("ключ один на процесс: вторая отрисовка — тот же", _ticket(c.get("/admin/license").body) == ticket)
            t = _tile(c)
            res.ok("плитка «Licența» в настройках: режим чтения красным",
                   t.get("label") == "Licența" and "regim de citire" in _hint(t)
                   and any(p.get("tone") == "red" for p in t.get("hint", [])), repr(t))

            # системный браузер: без куки, только ключ
            anon = Client(s.url)
            r = anon.get(f"/plata/{ticket}")
            res.ok("по ключу без входа: 303 прямо на страницу оплаты сервера",
                   r.status == 303 and r.location == page, repr(r))
            sent = [p for p in stand.posts if p["path"] == PAY]
            res.ok("запрос ушёл на сервер файла с его токеном",
                   len(sent) == 1 and sent[0]["auth"] == f"Bearer {TOKEN}"
                   and sent[0]["agent"].startswith("DentPilot/"), repr(sent))
            a = _api(c)
            res.ok("после нажатия объявлен частый запрос", bool(a.get("paying_until")), repr(a))
            lp = c.get("/admin/license").body
            res.ok("страница говорит, что проверяет каждую минуту, и обновляется сама",
                   "verifică plata la fiecare minut" in lp and "http-equiv='refresh'" in lp)
            res.ok("в логе сервера — исход нажатия", "license: pay=ok" in _log(s))

            # оплата дошла: новый файл — без единой кнопки
            stand.serve(200, _file(9, renew))
            res.ok("оплата дошла: программа сама взяла новый срок за секунды",
                   _until(lambda: _api(c).get("seq") == 9, 20.0), repr(_api(c)))
            a = _api(c)
            res.ok("active, частый запрос погас вместе с оплатой",
                   a.get("state") == "active" and a.get("paying_until") is None, repr(a))
            r = c.post_json("/api/patients", {"name": "Pay Test", "phone": "069000777"})
            res.check("запись снова работает", r.status, 200)
            res.ok("плитка: «activă până la»", "activă până la" in _hint(_tile(c)), repr(_tile(c)))
            lp = c.get("/admin/license").body
            res.ok("при активной оплата — после срока и «Verifică acum» (продление заранее)",
                   0 < lp.find("/admin/license/renew") < lp.find("Plătește acum")
                   and "http-equiv='refresh'" not in lp)

            # отказы — словами, в том же браузере, без перехода
            r = anon.get("/plata/" + "x" * 24)
            res.ok("чужой ключ: 404 словами, без перехода",
                   r.status == 404 and "Linkul de plată a expirat" in r.body and not r.location, repr(r))
            ticket = _ticket(lp)
            n = len(stand.posts)
            stand.answer(200, {"ok": True, "url": "https://evil.example/plata/abc123"}, path=PAY)
            r = anon.get(f"/plata/{ticket}")
            res.ok("адрес в ответе не того сервера: перехода нет",
                   r.status == 503 and not r.location and "nu a răspuns" in r.body
                   and len(stand.posts) == n + 1, repr(r))
            stand.answer(200, {"ok": True, "url": stand.base + "/admin/x"}, path=PAY)
            r = anon.get(f"/plata/{ticket}")
            res.ok("тот сервер, но не страница оплаты: перехода нет", r.status == 503 and not r.location, repr(r))
            stand.answer(401, {"ok": False, "code": "token_unknown"}, path=PAY)
            r = anon.get(f"/plata/{ticket}")
            res.ok("токен не признан: страница словами",
                   r.status == 503 and "nu a recunoscut licența" in r.body, repr(r))
            stand.close()
            r = anon.get(f"/plata/{ticket}")
            res.ok("сервера нет: страница словами", r.status == 503 and "nu a răspuns" in r.body, repr(r))
            res.ok("неудачи частого запроса не заводят",
                   _api(c).get("paying_until") is None)
    finally:
        _rmtree_settled(d)

    # не директор: ни ссылки, ни ключа. Отдельным сервером — первая учётка
    # переводит вход на PIN, и сессия директора по ADMIN_KEY гаснет
    stand = Stand()
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_pay3_"))
    try:
        (d / "license.json").write_text(_file(8, {"url": stand.url, "token": TOKEN}, expired=True),
                                        encoding="utf-8")
        stand.serve(204)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            c.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
            ana = Client(s.url)
            ana.post("/admin/login", password="3333", next="/admin")
            banner = ana.get("/admin?ui=legacy").body
            res.ok("регистратуре в режиме чтения: баннер без ссылки оплаты, страница без кнопки",
                   "regim de citire" in banner and "activați abonamentul" in banner
                   and "/plata/" not in banner and "/plata/" not in ana.get("/admin/license").body,
                   banner[-1200:])
    finally:
        stand.close()
        _rmtree_settled(d)


def suite_off(res: Result) -> None:
    """Платить некому — ссылки нет: файл без сервера, программа без ключей выдачи."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_pay2_"))
    try:
        shutil.copy(FIX / "expired.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _api(c)
            res.ok("файл без renew: оплата недоступна", a.get("pay") is False, repr(a))
            res.ok("ни на странице, ни в баннере ссылки нет",
                   "/plata/" not in c.get("/admin/license").body
                   and "/plata/" not in c.get("/admin?ui=legacy").body)
            res.ok("плитка «Licența» есть и без сервера", _tile(c).get("label") == "Licența")
            res.check("маршрут без ключа — 404", Client(s.url).get("/plata/" + "y" * 24).status, 404)
    finally:
        _rmtree_settled(d)

    with Server() as s:
        c = Client(s.url).login()
        res.ok("без ключей выдачи плитки «Licența» нет",
               not _tile(c) and any(t.get("href") == "/admin/settings/faq" for t in _hub(c)))
        res.check("маршрут — 404", Client(s.url).get("/plata/" + "z" * 24).status, 404)
        faq = c.get("/admin/settings/faq?ui=legacy").body
        res.ok("FAQ отвечает, как платить, словами кнопок",
               "Cum plătesc abonamentul?" in faq and "Plătește acum" in faq
               and "Setări › Licența" in faq and "Verifică acum dacă există un termen nou" in faq)
