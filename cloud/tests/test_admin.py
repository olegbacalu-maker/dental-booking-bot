"""Вход администратора: охрана, кука, выход, Origin, лимит попыток."""
import sqlite3

from harness import ADMIN_PASS, ADMIN_USER, Client, Result, Server, read_json


def suite_login(res: Result) -> None:
    with Server() as s:
        c = Client(s.url)
        h = c.get("/health")
        res.ok("/health отвечает", h.status == 200 and read_json(h).get("ok") is True)
        res.ok("без входа: журнал ведёт на вход",
               c.get("/admin").status == 303 and c.get("/admin").location == "/admin/login")
        res.check("без входа: карточка тоже", c.get("/admin/clinics/c_000000000000").status, 303)
        res.check("без входа: POST тоже ведёт на вход", c.post("/admin/clinics", name="x").status, 303)
        r = c.post("/admin/login", user=ADMIN_USER, password="wrong")
        res.ok("неверный пароль: обратно на вход с кодом",
               r.status == 303 and r.location == "/admin/login?msg=login_bad", f"{r.status} {r.location!r}")
        res.ok("страница входа показывает отказ",
               "Неверный логин" in c.get("/admin/login?msg=login_bad").body)
        r = c.post("/admin/login", user=ADMIN_USER, password=ADMIN_PASS,
                   headers={"Origin": "http://evil.example", "Host": f"127.0.0.1:{s.port}"})
        res.check("чужой Origin на входе: 403", r.status, 403)
        r = c.post("/admin/login", user=ADMIN_USER, password=ADMIN_PASS)
        res.ok("верный пароль: в журнал", r.status == 303 and r.location == "/admin", f"{r.status} {r.location!r}")
        res.ok("кука выдана HttpOnly", "httponly" in r.headers.get("set-cookie", "").lower())
        res.check("после входа журнал открыт", c.get("/admin").status, 200)
        r = c.post("/admin/logout")
        res.ok("выход: на вход", r.status == 303 and r.location == "/admin/login")
        res.check("после выхода журнал закрыт", c.get("/admin").status, 303)
        db_path = s.dir / "cloud.db"
        con = sqlite3.connect(db_path)
        try:
            kinds = [r[0] for r in con.execute("SELECT what FROM audit ORDER BY id")]
        finally:
            con.close()
        res.ok("журнал: неудача и удача входа записаны",
               "login_fail" in kinds and "login_ok" in kinds, repr(kinds))


def suite_lock(res: Result) -> None:
    with Server() as s:
        c = Client(s.url)
        for _ in range(5):
            c.post("/admin/login", user=ADMIN_USER, password="wrong")
        r = c.post("/admin/login", user=ADMIN_USER, password=ADMIN_PASS)
        res.ok("шестая попытка, даже верная: заперто на минуту",
               r.status == 303 and r.location == "/admin/login?msg=login_locked", f"{r.location!r}")
        res.check("заперто: журнал по-прежнему закрыт", c.get("/admin").status, 303)
