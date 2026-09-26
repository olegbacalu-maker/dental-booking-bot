"""Обновившаяся клиника (L6): картотека с пациентами, файла лицензии нет.

Путь клиники, которая работала до лицензии: пациенты уже есть, файла ещё
нет. Стены нет — показывать есть что; 14 дней от первого запуска этой версии
программа работает в льготе с баннером, потом переходит в режим чтения;
импорт файла возвращает всё. Пустая картотека рядом — для контраста: там
стена. Пациенты заводятся в запуске БЕЗ ключей выдачи (лицензия не
применяется — так их завела бы прежняя версия), а версия с ключами приходит
вторым стартом на ту же папку.

⭐ «15 дней спустя» — память подвинута назад руками: `first_start` в файле
памяти уезжает на 15 дней, зеркало в базе помнит сегодняшний, и слияние берёт
самый ранний. Это ровно то, что сделала бы жизнь, только без ожидания.
"""
import json
import pathlib
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

from harness import ROOT, Client, Result, Server, _rmtree_settled

FIX = ROOT / "tests" / "fixtures" / "license"
KEY_ENV = {"DENTART_LICENSE_KEYS": str(FIX / "test-key.json")}
NO_KEY_ENV = {"DENTART_LICENSE_KEYS": ""}
TS = "%Y-%m-%dT%H:%M:%SZ"


def _api(c: Client) -> dict:
    r = c.get("/api/license")
    return json.loads(r.body).get("data", {}) if r.status == 200 else {"status": r.status}


def _patients(d: pathlib.Path) -> int:
    con = sqlite3.connect(d / "dental.db")
    try:
        return con.execute("SELECT count(*) FROM patients").fetchone()[0]
    finally:
        con.close()


def _refused(r) -> bool:
    if r.status == 423:
        return True
    return r.status == 303 and "msg=license_" in r.location


def suite_existing(res: Result) -> None:
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_exist_"))
    try:
        # 1. прежняя версия (без ключей выдачи): картотека наполняется
        with Server(dir_=d, env=NO_KEY_ENV) as s:
            c = Client(s.url).login()
            for name, phone in (("Ion Test", "069000111"), ("Ana Test", "069000222")):
                r = c.post_json("/api/patients", {"name": name, "phone": phone})
                res.check(f"прежняя версия: пациент {name} заведён", r.status, 200)
        res.check("в картотеке два пациента", _patients(d), 2)

        # 2. версия с лицензией пришла, файла нет: льгота, не стена
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            page = c.get("/admin")
            res.check("картотека открывается: стены нет", page.status, 200)
            res.ok("баннер льготы: файл лишний раз не пугает, а называет срок и ссылку",
                   "banner warn" in page.body and "Fișierul de licență lipsește" in page.body
                   and "href='/admin/license'" in page.body, "баннера нет")
            mem = json.loads((d / "license.state").read_text(encoding="utf-8"))
            a = _api(c)
            res.ok("/api/license: grace, без стены, без кода, отсчёт от первого запуска",
                   a.get("state") == "grace" and a.get("wall") is False and a.get("code") == ""
                   and a.get("valid_until") == mem["first_start"], repr(a))
            first = datetime.strptime(mem["first_start"], TS).replace(tzinfo=timezone.utc)
            res.check("льгота — 14 дней от первого запуска",
                      a.get("grace_until"), (first + timedelta(days=14)).strftime(TS))
            r = c.post_json("/api/patients", {"name": "Nou Test", "phone": "069000333"})
            res.check("в льготе запись работает", r.status, 200)
            lic_page = c.get("/admin/license").body
            res.ok("страница активации: срок льготы, ссылка назад",
                   "funcționează încă până la" in lic_page and "Înapoi la registru" in lic_page)
            res.ok("лог: grace без файла и без принятого seq",
                   "license: state=grace code=- seq=0" in
                   s._log_path.read_text(encoding="utf-8", errors="replace"))

        # 3. рестарт: отсчёт не начинается заново
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            res.check("после рестарта отсчёт от той же даты",
                      _api(c).get("valid_until"), mem["first_start"])

        # 4. пятнадцать дней спустя: режим чтения, картотека открыта
        now = datetime.now(timezone.utc)
        mem["first_start"] = (now - timedelta(days=15)).strftime(TS)
        mem["last_seen"] = (now - timedelta(days=1)).strftime(TS)
        (d / "license.state").write_text(json.dumps(mem), encoding="utf-8")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _api(c)
            res.check("через 15 дней: readonly", a.get("state"), "readonly")
            page = c.get("/admin")
            res.check("картотека по-прежнему открывается", page.status, 200)
            res.ok("баннер режима чтения называет файл",
                   "banner err" in page.body and "Fișierul de licență lipsește" in page.body
                   and "regim de citire" in page.body, "баннера нет")
            r = c.post_json("/api/patients", {"name": "Tarziu Test", "phone": "069000555"})
            res.ok("запись отказывает license_readonly",
                   r.status == 423 and json.loads(r.body).get("code") == "license_readonly",
                   f"{r.status} {r.body[:100]}")
            res.check("фиша читается", c.get("/api/patients/1").status, 200)
            res.ok("бэкап разрешён и в режиме чтения",
                   not _refused(c.post("/admin/backup/export", parola="test-parola-1")))
            res.check("пациентов по-прежнему три", _patients(d), 3)

            # 5. импорт файла возвращает работу
            r = c.post_file("/admin/license", "file", "license.json",
                            (FIX / "valid.json").read_bytes(), mime="application/json", terms="1")
            res.ok("импорт файла: 303 в журнал с license_ok",
                   r.status == 303 and r.location == "/admin?msg=license_ok", f"{r.status} {r.location!r}")
            res.check("после импорта: active", _api(c).get("state"), "active")
            r = c.post_json("/api/patients", {"name": "Dupa Test", "phone": "069000666"})
            res.check("после импорта запись работает", r.status, 200)
            res.ok("баннера больше нет", "/admin/license" not in c.get("/admin").body)
    finally:
        _rmtree_settled(d)

    # 6. контраст: пустая картотека без файла — стена, не льгота
    d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_exist2_"))
    try:
        with Server(dir_=d2, env=KEY_ENV) as s:
            c = Client(s.url).login()
            r = c.get("/admin")
            res.ok("пустая картотека без файла: стена, а не 14 дней",
                   r.status == 303 and r.location == "/admin/license", f"{r.status} {r.location!r}")
            res.check("/api/license: missing со стеной", _api(c).get("wall"), True)
    finally:
        _rmtree_settled(d2)
