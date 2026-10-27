"""E-mail клиники (27.10, план В): половина программы к /v1/email/* и заголовкам /v1/license.

Провод — core/license_renew.py (`email_call`, `fetch(meta=…)`), решение — core/license.py
(`mailbox`, `email_action`), напоминание — строка плитки «Licența» (settings/routes.py) и блок
страницы лицензии (layout.py), действия — POST /admin/license/email/* (modules/license/routes.py).
Сервер лицензий подменён стендом из test_license_renew: нужны ответы, которых настоящий сервер
не даёт по заказу (отказ, тишина). Что настоящий сервер и этот провод понимают друг друга —
cloud/tests/test_email.py.

⭐ Что держит набор: ящик не подтверждён — только напоминание (запись работает и так);
действия — только директору и в режиме чтения тоже (на ящик идут ноты); сервер не сказал о
ящике — ни строки, ни блока: «не знаем» не равно «не подтверждён».
"""
import json
import pathlib
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

from harness import Client, Result, Server, _rmtree_settled, shell_signal
from test_license_renew import KEY_ENV, TOKEN, Stand, _api, _events, _file, _log, _until, _wait_renew, rn
from test_paylink import _hint, _tile

CODE, CONFIRM, CHANGE = "/v1/email/code", "/v1/email/confirm", "/v1/email/change"
UNCONF = {"X-DentPilot-Email-Confirmed": "0", "X-DentPilot-Email": "clinica%40gmial.com"}


def suite_wire(res: Result) -> None:
    """`rn.email_call` и `rn.fetch(meta=…)`: исход по коду, тело — только словарь."""
    stand = Stand()
    try:
        url = stand.base + CONFIRM
        stand.answer(200, {"ok": True, "email": "a@b.md", "confirmed": True, "sent": False}, path=CONFIRM)
        out, data = rn.email_call(url, TOKEN, {"code": "123456"}, timeout=5, agent="DentPilot/test",
                                  extra={"X-DentPilot-Device": "d_0a1b2c3d4e5f"})
        res.ok("200 с ok: ACCEPTED и ящик", out == rn.ACCEPTED and data.get("confirmed") is True, repr((out, data)))
        sent = stand.posts[-1]
        res.ok("POST JSON с Bearer-токеном файла и личностью машины",
               sent["path"] == CONFIRM and sent["auth"] == f"Bearer {TOKEN}" and sent["json"] == {"code": "123456"}
               and sent["device"] == "d_0a1b2c3d4e5f", repr(sent))
        for status in (400, 409, 429, 502):
            stand.answer(status, {"ok": False, "code": "x", "text": "Codul nu este corect"}, path=CONFIRM)
            res.check(f"{status} с текстом: REJECTED словами сервера", rn.email_call(url, TOKEN, {}, timeout=5)[0],
                      rn.REJECTED)
        stand.answer(400, {"ok": False}, path=CONFIRM)
        res.check("400 без текста: OFFLINE", rn.email_call(url, TOKEN, {}, timeout=5), (rn.OFFLINE, {}))
        stand.answer(401, {"ok": False, "code": "token_unknown"}, path=CONFIRM)
        res.check("401: REFUSED", rn.email_call(url, TOKEN, {}, timeout=5), (rn.REFUSED, {}))
        stand.answer(302, None, path=CONFIRM)
        res.check("редирект не исполняется: OFFLINE", rn.email_call(url, TOKEN, {}, timeout=5), (rn.OFFLINE, {}))
        stand.serve(204)
        stand.get_headers = dict(UNCONF)
        meta: dict = {}
        res.check("204 с заголовками: SAME", rn.fetch(stand.url, TOKEN, 1, timeout=5, meta=meta)[0], rn.SAME)
        res.check("meta: ящик из заголовков", meta.get("mailbox"), {"email": "clinica@gmial.com", "confirmed": False})
        stand.get_headers = {}
        meta = {}
        rn.fetch(stand.url, TOKEN, 1, timeout=5, meta=meta)
        res.check("без заголовков — ничего (старый сервер)", meta, {})
    finally:
        stand.close()
    res.check("сервера нет: OFFLINE", rn.email_call(url, TOKEN, {}, timeout=2), (rn.OFFLINE, {}))


def _meta(d: pathlib.Path, key: str) -> str | None:
    con = sqlite3.connect(d / "dental.db")
    try:
        row = con.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _block(page: str) -> bool:
    return "E-mail neconfirmat" in page and "/admin/license/email/confirm" in page


def suite_page(res: Result) -> None:
    """Режим чтения + неподтверждённый ящик: напоминание, три действия директора, ответы словами."""
    stand = Stand()
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_mail_"))
    try:
        (d / "license.json").write_text(_file(8, {"url": stand.url, "token": TOKEN}, expired=True),
                                        encoding="utf-8")
        stand.serve(204)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _wait_renew(c)
            res.check("сервер о ящике не сказал — mailbox пуст", a.get("mailbox"), None)
            res.ok("…и ни строки на плитке, ни блока на странице",
                   "e-mail" not in _hint(_tile(c)) and not _block(c.get("/admin/license").body))

            stand.get_headers = dict(UNCONF)
            c.post("/admin/license/renew")
            a = _api(c)
            res.check("после запроса файла: ящик и «не подтверждён»", a.get("mailbox"),
                      {"email": "clinica@gmial.com", "confirmed": False, "text": ""})
            t = _tile(c)
            res.ok("плитка «Licența»: «e-mail neconfirmat» янтарным рядом со сроком",
                   "regim de citire" in _hint(t) and "e-mail neconfirmat" in _hint(t)
                   and any(p.get("tone") == "amber" and p.get("t") == "e-mail neconfirmat" for p in t["hint"]), repr(t))
            lp = c.get("/admin/license").body
            res.ok("страница: ящик назван, код, «Retrimite», «Schimbă adresa», «funcționează și fără»",
                   _block(lp) and "clinica@gmial.com" in lp and "/admin/license/email/code" in lp
                   and "/admin/license/email/change" in lp and "funcționează și fără confirmare" in lp, lp[-2500:])
            res.ok("блок e-mail — после оплаты и срока", 0 < lp.find("Plătește acum") < lp.find("E-mail neconfirmat"))

            # баннер каркаса: в сигнале license, вслед за баннером режима чтения
            sig = shell_signal(c.get("/admin").body, "license")["html"]
            res.ok("баннер директору: ящик, ссылка на лицензию, «Mai târziu» — после баннера чтения",
                   0 < sig.find("regim de citire") < sig.find("nu este confirmată")
                   and "clinica@gmial.com" in sig and "href='/admin/license'><b>Confirmați" in sig
                   and "action='/admin/license/email/later'" in sig, sig[-900:])
            r = c.post("/admin/license/email/later")
            res.check("«Mai târziu» (в режиме чтения тоже) — назад в журнал", r.location, "/admin")
            sig = shell_signal(c.get("/admin").body, "license")["html"]
            res.ok("после «Mai târziu» баннера e-mail нет, баннер чтения на месте",
                   "nu este confirmată" not in sig and "regim de citire" in sig, sig[-600:])
            later = _meta(d, "lic_mail_later")
            res.ok("«Mai târziu» — на неделю, в schema_meta (переживает перезапуск)",
                   later is not None and timedelta(days=6, hours=23) < datetime.strptime(
                       later, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
                   <= timedelta(days=7), repr(later))
            res.ok("напоминание на плитке и странице «Mai târziu» не гасит",
                   "e-mail neconfirmat" in _hint(_tile(c)) and _block(c.get("/admin/license").body))

            # «Schimbă adresa»: отказ сервера словами, потом удача
            stand.answer(409, {"ok": False, "code": "email_taken", "text": "Adresa aparține altei clinici"},
                         path=CHANGE)
            r = c.post("/admin/license/email/change", email="alta@example.md")
            res.check("отказ сервера — license_email_refused (в режиме чтения тоже)", r.location,
                      "/admin/license?msg=license_email_refused")
            res.ok("страница говорит словами сервера", "Adresa aparține altei clinici" in c.get(r.location).body)
            stand.answer(200, {"ok": True, "email": "clinica@gmail.com", "confirmed": False, "sent": True}, path=CHANGE)
            r = c.post("/admin/license/email/change", email=" clinica@gmail.com ")
            res.check("смена — license_email_changed", r.location, "/admin/license?msg=license_email_changed")
            res.ok("на сервер ушёл новый ящик без пробелов", stand.posts[-1]["json"] == {"email": "clinica@gmail.com"},
                   repr(stand.posts[-1]))
            res.ok("страница: новый ящик, всё ещё не подтверждён",
                   "E-mail neconfirmat: clinica@gmail.com" in c.get("/admin/license").body)
            # «Retrimite»
            stand.answer(200, {"ok": True, "email": "clinica@gmail.com", "confirmed": False, "sent": True}, path=CODE)
            res.check("«Retrimite» — license_email_sent", c.post("/admin/license/email/code").location,
                      "/admin/license?msg=license_email_sent")
            # код
            stand.answer(200, {"ok": True, "email": "clinica@gmail.com", "confirmed": True, "sent": False},
                         path=CONFIRM)
            r = c.post("/admin/license/email/confirm", code=" 123 456 ")
            res.check("код — license_email_confirmed", r.location, "/admin/license?msg=license_email_confirmed")
            res.check("код ушёл без пробелов", stand.posts[-1]["json"], {"code": "123456"})
            res.check("ящик подтверждён", (_api(c).get("mailbox") or {}).get("confirmed"), True)
            lp = c.get("/admin/license").body
            res.ok("страница: одна строка «confirmată», форм нет",
                   "clinica@gmail.com</b> — confirmată" in lp and not _block(lp))
            res.ok("плитка: напоминания нет", "e-mail" not in _hint(_tile(c)), repr(_tile(c)))
            ev = _events(d)
            res.ok("летопись: смена и подтверждение ящика",
                   any("a fost schimbată" in e for e in ev) and any("a fost confirmată" in e for e in ev), repr(ev))
            res.ok("лог: исходы действий", "license: email=confirm confirmed=True" in _log(s))
            stand.close()
            res.check("сервера нет — license_email_offline", c.post("/admin/license/email/code").location,
                      "/admin/license?msg=license_email_offline")
    finally:
        _rmtree_settled(d)

    # не директор: ни блока, ни действий. Отдельным сервером — первая учётка переводит вход на PIN
    stand = Stand()
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_mail2_"))
    try:
        (d / "license.json").write_text(_file(8, {"url": stand.url, "token": TOKEN}), encoding="utf-8")
        stand.serve(204)
        stand.get_headers = dict(UNCONF)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            res.ok("активная лицензия, ящик не подтверждён — запись работает (ничего не заперто)",
                   _until(lambda: (_api(c).get("mailbox") or {}).get("confirmed") is False)
                   and c.post_json("/api/patients", {"name": "Mail Test", "phone": "069000778"}).status == 200)
            sig = shell_signal(c.get("/admin").body, "license")
            res.ok("при активной лицензии сигнал license несёт только баннер e-mail",
                   sig["shown"] and "nu este confirmată" in sig["html"] and "abonament" not in sig["html"], repr(sig))
            c.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R", "role": "receptie", "pin": "3333"})
            ana = Client(s.url)
            ana.post("/admin/login", password="3333", next="/admin")
            n = len(stand.posts)
            r = ana.post("/admin/license/email/code")
            res.ok("регистратуре: блока нет, действие — no_access, на сервер ничего не ушло",
                   not _block(ana.get("/admin/license").body) and r.location == "/admin?msg=no_access"
                   and len(stand.posts) == n, repr(r))
            res.ok("регистратуре баннера нет, «Mai târziu» — no_access",
                   not shell_signal(ana.get("/admin").body, "license")["shown"]
                   and ana.post("/admin/license/email/later").location == "/admin?msg=no_access"
                   and _meta(d, "lic_mail_later") is None)
    finally:
        stand.close()
        _rmtree_settled(d)
