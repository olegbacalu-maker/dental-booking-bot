"""Стена активации, страница `/admin/license`, баннер и `/api/license` (L5).

Всё на живом сервере с ключом из окружения: без ключа выдачи лицензия не
применяется вовсе (`license.applies()`), и это тоже проверяется — так живут
песочница и все прочие наборы прогона. Льготное состояние подписывается
прямо здесь тем же генератором, что собрал фикстуры: фиксированных дат для
«срок прошёл, льгота идёт» в фикстурах нет и быть не может.
"""
import importlib.util
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from harness import BOT, ROOT, Client, Result, Server, _rmtree_settled

FIX = ROOT / "tests" / "fixtures" / "license"
KEY_ENV = {"DENTART_LICENSE_KEYS": str(FIX / "test-key.json")}
NO_KEY_ENV = {"DENTART_LICENSE_KEYS": ""}


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load("license_fixtures", ROOT / "scripts" / "license_fixtures.py")


def _api(c: Client) -> dict:
    r = c.get("/api/license")
    return json.loads(r.body).get("data", {}) if r.status == 200 else {"status": r.status}


def _grace_file(days_ago: int = 3, grace_days: int = 14) -> str:
    """Срок прошёл `days_ago` дней назад, льгота ещё идёт — подписано тестовым ключом."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    claim = dict(gen.CLAIMS["valid"], seq=4,
                 issued_at=(now - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 valid_until=(now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 grace_until=(now - timedelta(days=days_ago) + timedelta(days=grace_days))
                 .strftime("%Y-%m-%dT%H:%M:%SZ"))
    payload = gen.claim_bytes(claim)
    return gen.envelope(payload, gen.sign(payload, gen.load_key()))


def suite_wall(res: Result) -> None:
    """Пустая картотека без файла: стена, импорт, четыре отказа импорта."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_wall_"))
    try:
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url)
            r = c.get("/admin")
            res.ok("без входа: стена не мешает дойти до входа",
                   r.status == 303 and r.location.startswith(("/admin/license", "/admin/login")),
                   f"{r.status} {r.location!r}")
            res.check("экран входа открыт за стеной", c.get("/admin/login").status, 200)
            c.login()
            r = c.get("/admin")
            res.ok("журнал ведёт на активацию", r.status == 303 and r.location == "/admin/license",
                   f"{r.status} {r.location!r}")
            r = c.get("/admin/patients")
            res.ok("любой адрес журнала ведёт на активацию",
                   r.status == 303 and r.location == "/admin/license", f"{r.status} {r.location!r}")
            page = c.get("/admin/license")
            res.check("страница активации открывается", page.status, 200)
            res.ok("страница: заголовок, контакты, форма директору",
                   "Activarea programului" in page.body and "dentpilotpro@gmail.com" in page.body
                   and "+373 60 508 048" in page.body and 'name="file"' in page.body
                   and "@font-face{" in page.body and "__FONTS__" not in page.body,
                   page.body[:200])
            res.ok("страница: галочка условий — обязательная, со ссылкой на termeni.html",
                   "name='terms'" in page.body and "required" in page.body
                   and "https://dentpilot.md/termeni.html" in page.body, page.body[-600:])
            res.ok("за стеной ссылки «назад в журнал» нет", "Înapoi la registru" not in page.body)
            r = c.post_json("/api/patients", {})
            res.ok("за стеной запись отказывает кодом license_missing",
                   r.status == 423 and json.loads(r.body).get("code") == "license_missing",
                   f"{r.status} {r.body[:120]}")
            r = c.post("/admin/settings/save")
            res.ok("за стеной форма ведёт на активацию с кодом",
                   r.status == 303 and r.location == "/admin/license?msg=license_missing",
                   f"{r.status} {r.location!r}")
            a = _api(c)
            res.ok("/api/license: missing, стена", a.get("state") == "missing" and a.get("wall") is True
                   and a.get("applies") is True, repr(a))

            # отказы импорта — каждый своим кодом, файл не появляется
            for name, want in (("bad-sig", "license_bad_signature"),
                               ("unknown-kid", "license_key_unknown"),
                               ("tampered", "license_bad_signature")):
                r = c.post_file("/admin/license", "file", "license.json",
                                (FIX / f"{name}.json").read_bytes(), mime="application/json",
                                terms="1")
                res.ok(f"импорт {name}: {want}",
                       r.status == 303 and r.location == f"/admin/license?msg={want}",
                       f"{r.status} {r.location!r}")
            r = c.post("/admin/license", text="{ not a licence", terms="1")
            res.ok("импорт мусора текстом: license_malformed",
                   r.status == 303 and r.location == "/admin/license?msg=license_malformed",
                   f"{r.status} {r.location!r}")
            res.ok("после отказов файла на диске нет", not (d / "license.json").exists())
            page = c.get("/admin/license?msg=license_bad_signature").body
            res.ok("страница показывает причину отказа", "Semnătura fișierului" in page)

            # годный файл без галочки условий: договор не принят — файла нет
            r = c.post_file("/admin/license", "file", "license.json",
                            (FIX / "valid.json").read_bytes(), mime="application/json")
            res.ok("импорт без галочки условий: license_terms",
                   r.status == 303 and r.location == "/admin/license?msg=license_terms",
                   f"{r.status} {r.location!r}")
            res.ok("без галочки файла на диске нет", not (d / "license.json").exists())
            res.ok("страница называет причину: галочка условий",
                   "Bifați acceptarea Termenilor" in c.get("/admin/license?msg=license_terms").body)

            # импорт годного: файл на диске, стена снята, состояние active
            r = c.post_file("/admin/license", "file", "license.json",
                            (FIX / "valid.json").read_bytes(), mime="application/json", terms="1")
            res.ok("импорт valid: 303 в журнал с license_ok",
                   r.status == 303 and r.location == "/admin?msg=license_ok", f"{r.status} {r.location!r}")
            res.ok("файл записан рядом с clinic.json", (d / "license.json").exists())
            res.check("память: принят seq 3",
                      json.loads((d / "license.state").read_text(encoding="utf-8")).get("accepted_seq"), 3)
            res.check("журнал открыт", c.get("/admin").status, 200)
            a = _api(c)
            res.ok("/api/license: active, seq 3, до 2099",
                   a.get("state") == "active" and a.get("seq") == 3
                   and a.get("valid_until") == "2099-01-01T00:00:00Z", repr(a))
            page = c.get("/admin/license").body
            res.ok("страница при active: абонемент активен, ссылка назад",
                   "Abonamentul este activ" in page and "Înapoi la registru" in page)
            r = c.post_file("/admin/license", "file", "license.json",
                            (FIX / "expired.json").read_bytes(), mime="application/json", terms="1")
            res.ok("импорт файла старее принятого: license_older",
                   r.status == 303 and r.location == "/admin/license?msg=license_older",
                   f"{r.status} {r.location!r}")
            res.ok("файл на диске остался прежним",
                   json.loads((d / "license.json").read_text(encoding="utf-8"))["sig"]
                   == json.loads((FIX / "valid.json").read_text(encoding="utf-8"))["sig"])
        con = sqlite3.connect(d / "dental.db")
        try:
            rows = con.execute("SELECT text, actor FROM activity WHERE kind = 'license'").fetchall()
        finally:
            con.close()
        res.ok("летопись клиники: «Licența a fost activată … (fișier 3)»",
               any("Licența a fost activată" in r[0] and "(fișier 3)" in r[0] for r in rows), repr(rows))
        # Принятие договора — строкой летописи: версия условий и ИМЯ вошедшего
        # (у директора харнесса имени нет — вместо него подпись роли), не «sistem»
        res.ok("летопись: условия приняты — версия и кто",
               any("acceptați Termenii și condițiile din" in t and a == "Director" for t, a in rows),
               repr(rows))
    finally:
        _rmtree_settled(d)


def suite_banner(res: Result) -> None:
    """Баннер: льгота, режим чтения, отсутствие при active; /api/license."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_banner_"))
    try:
        (d / "license.json").write_text(_grace_file(), encoding="utf-8")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            page = c.get("/admin")
            res.check("льгота: журнал открыт", page.status, 200)
            res.ok("льгота: баннер warn со ссылкой на лицензию",
                   "Abonamentul a expirat la" in page.body and "banner warn" in page.body
                   and "href='/admin/license'" in page.body, "баннера нет")
            res.ok("льгота: запись работает", c.post_json("/api/patients", {}).status != 423)
            a = _api(c)
            res.ok("/api/license: grace, seq 4", a.get("state") == "grace" and a.get("seq") == 4, repr(a))
            page = c.get("/admin/license").body
            res.ok("страница при льготе: срок и дата режима чтения",
                   "Abonamentul a expirat" in page and "regim de citire" in page)
        # файл подменён на более старый (seq 2 < принятого 4), память стёрта —
        # зеркало в базе помнит принятый: состояние по его датам, с кодом
        shutil.copy(FIX / "expired.json", d / "license.json")
        (d / "license.state").unlink()
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            page = c.get("/admin").body
            res.ok("файл старее принятого: льгота по памяти, баннер о файле",
                   "banner warn" in page and "Fișierul de licență" in page, "баннера нет")
            a = _api(c)
            res.ok("/api/license: grace с кодом license_older",
                   a.get("state") == "grace" and a.get("code") == "license_older", repr(a))
    finally:
        _rmtree_settled(d)

    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_banner2_"))
    try:
        shutil.copy(FIX / "expired.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            page = c.get("/admin").body
            res.ok("режим чтения: баннер err всем", "banner err" in page and "regim de citire" in page)
            res.ok("режим чтения: страница без стены", c.get("/admin/license").status == 200)
        shutil.copy(FIX / "valid.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            page = c.get("/admin").body
            res.ok("active: баннера лицензии нет", "/admin/license" not in page)
            res.check("/api/license без входа: 401", Client(s.url).get("/api/license").status, 401)
    finally:
        _rmtree_settled(d)


def suite_no_keys(res: Result) -> None:
    """Без ключа выдачи лицензия не применяется: ни стены, ни баннера, ни отказов."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_nokey_"))
    try:
        with Server(dir_=d, env=NO_KEY_ENV) as s:
            c = Client(s.url).login()
            res.check("без ключей: журнал открыт", c.get("/admin").status, 200)
            res.ok("без ключей: запись не отказывает лицензией",
                   c.post_json("/api/patients", {}).status != 423)
            res.check("/api/license: applies false", _api(c), {"applies": False})
            page = c.get("/admin/license").body
            res.ok("страница без ключей объясняет, что проверки нет",
                   "nu verifică licența" in page, page[:200])
            res.ok("без ключей баннера нет", "/admin/license" not in c.get("/admin").body)
    finally:
        _rmtree_settled(d)
