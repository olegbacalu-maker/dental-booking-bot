"""Подтверждение e-mail клиники (27.10, план В; emailconf.py): письмо о пробном со ссылкой и
кодом, страница ссылки (GET не пишет), программа — «Retrimite», код, «Schimbă adresa» проводом
ПРОГРАММЫ (bot/app/core/license_renew.py по пути), заголовки /v1/license, вход в кабинет как
подтверждение, метка и строка «Ждёт вас» в админке, переход базы на шаг 17.

⭐ Пары, на которых набор краснел при разработке, — `design/email-confirm/tools/mutate_email.py`.
"""
import json
import re
import sqlite3
import sys
import tempfile
import pathlib
from urllib.parse import urlsplit

from harness import CLOUD, Client, Result, Server, cid_from

sys.path.insert(0, str(CLOUD))
from app import emailconf  # noqa: E402
from test_account import FakeGoogle, _google_login, _letters, _sql  # noqa: E402
from test_renew import rn  # noqa: E402

AUTO = {"DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}
GOOD = dict(name="Clinica Mail", idno="", contact_name="Ana", email="clinica@gmial.com",
            phone="069000000", consent="1")
HDR = {"User-Agent": "DentPilot/2.2.1", "X-DentPilot-Device": "d_0a1b2c3d4e5f"}
LINK = re.compile(r"https?://\S+?(/confirma/[A-Za-z0-9_-]{20,})")
CODE = re.compile(r"codul: (\d{6})\n")


def _trial(anon: Client, **over) -> str:
    """Заявка, как её шлёт программа → токен клиники (режим auto: файл выдан сразу)."""
    r = anon.post_raw("/v1/trial", json.dumps(dict(GOOD, **over)).encode("utf-8"))
    return json.loads(r.body).get("token", "") if r.status == 200 else ""


def _to(s: Server, who: str) -> list:
    return [x for x in _letters(s) if x[0] == who]


def _call(s: Server, path: str, token: str, payload: dict | None = None):
    return rn.email_call(s.url + path, token, payload or {}, timeout=10, agent="DentPilot/test", extra=HDR)


def _state(s: Server, cid: str):
    return _sql(s, "SELECT email, email_confirmed_at FROM clinics WHERE id=?", cid)[0]


def _cid(s: Server, email: str) -> str:
    return _sql(s, "SELECT id FROM clinics WHERE email=?", email)[0][0]


def _box(s: Server, token: str) -> dict:
    meta: dict = {}
    rn.fetch(s.url + "/v1/license", token, 99, timeout=10, meta=meta)
    return meta.get("mailbox") or {}


def suite_letter(res: Result) -> None:
    """Письмо о пробном → ссылка → страница с кнопкой → POST. GET ничего не пишет."""
    with Server(env=AUTO) as s:
        anon = Client(s.url)
        token = _trial(anon)
        res.ok("заявка из программы принята, токен есть", len(token) >= 32)
        cid = _cid(s, GOOD["email"])
        res.check("новая клиника — ящик не подтверждён", _state(s, cid), (GOOD["email"], None))
        letters = _to(s, GOOD["email"])
        body = letters[0][2] if letters else ""
        link, code = LINK.search(body), CODE.search(body)
        res.ok("одно письмо клинике — о пробном, и в нём «Confirmă adresa», ссылка и 6 цифр",
               len(letters) == 1 and "Perioada de probă" in body and "„Confirmă adresa”" in body
               and link is not None and code is not None and "Setări › Licența" in body
               and body.index("Confirmați adresa") < body.index("Programul îl descărcați"), body[:900])
        res.ok("ссылка — под адресом сервера, тем же, что у кабинета",
               link is not None and "/confirma/" in body and "/cont" in body)
        res.check("/v1/license: заголовки — не подтверждён, ящик назван",
                  _box(s, token), {"email": GOOD["email"], "confirmed": False})
        path = link.group(1) if link else "/confirma/x"
        page = anon.get(path)
        res.ok("GET ссылки: страница с кнопкой POST, клиника и ящик названы",
               page.status == 200 and "Confirmă adresa</button>" in page.body and "method='post'" in page.body
               and GOOD["email"] in page.body and "Clinica Mail" in page.body, page.body[-800:])
        anon.get(path)
        res.check("⭐ GET дважды — ящик всё ещё не подтверждён (сканер почты не подтверждает)",
                  _state(s, cid)[1], None)
        res.check("чужой Origin — 403", anon.post(path, headers={"Origin": "http://evil.example",
                                                                 "Host": f"127.0.0.1:{s.port}"}).status, 403)
        r = anon.post(path)
        res.ok("POST — подтверждён, страница «confirmată»",
               r.status == 200 and "este confirmată" in r.body and _state(s, cid)[1], r.body[-400:])
        res.check("/v1/license: заголовки — подтверждён", _box(s, token), {"email": GOOD["email"], "confirmed": True})
        res.ok("повтор POST и GET — «deja confirmată», не ошибка",
               "deja confirmată" in anon.post(path).body and "deja confirmată" in anon.get(path).body)
        res.check("чужой ключ — 404 «nu mai este valabil»", (lambda r: (r.status, "nu mai este valabil" in r.body))(
            anon.get("/confirma/" + "x" * 32)), (404, True))
        log = _sql(s, "SELECT who, detail FROM audit WHERE what='email_confirmed' AND clinic_id=?", cid)
        res.ok("журнал: email_confirmed, путь — ссылка из письма", len(log) == 1 and "linkul" in log[0][1], repr(log))
        mails = _sql(s, "SELECT detail FROM audit WHERE what='mail' AND clinic_id=?", cid)
        res.ok("журнал письма называет подтверждение ящика", any("подтверждение ящика" in d for (d,) in mails),
               repr(mails))
        # письмо подтверждённой клинике — без просьбы
        admin = Client(s.url).login()
        n = len(_letters(s))
        admin.post(f"/admin/clinics/{cid}/email")
        last = _letters(s)[n:]
        res.ok("следующее письмо о лицензии подтверждённой — без «Confirmă adresa»",
               len(last) == 1 and "Confirmă adresa" not in last[0][2], repr(last)[:300])


def suite_program(res: Result) -> None:
    """Программа: код, «Retrimite», «Schimbă adresa» — проводом программы против этого сервера."""
    with Server(env=AUTO) as s:
        anon = Client(s.url)
        token = _trial(anon)
        cid = _cid(s, GOOD["email"])
        other = _trial(anon, name="Alta Clinica", email="alta@example.md")
        res.ok("вторая клиника заведена", len(other) >= 32)
        res.check("чужой токен — REFUSED", _call(s, emailconf.API_CODE, "x" * 43), (rn.REFUSED, {}))
        res.check("без токена — 401", anon.post_raw(emailconf.API_CODE, b"{}").status, 401)
        out, d = _call(s, emailconf.API_CONFIRM, token, {"code": "000000"})
        res.ok("неверный код — REJECTED словами сервера", out == rn.REJECTED and d.get("code") == "email_bad_code"
               and "Retrimite" in d.get("text", ""), repr((out, d)))
        # «Schimbă adresa»: лечение опечатки
        out, d = _call(s, emailconf.API_CHANGE, token, {"email": "alta@example.md"})
        res.ok("ящик другой клиники — REJECTED email_taken", out == rn.REJECTED and d.get("code") == "email_taken",
               repr((out, d)))
        out, d = _call(s, emailconf.API_CHANGE, token, {"email": "nu-e-mail"})
        res.check("кривой ящик — bad_email", (out, d.get("code")), (rn.REJECTED, "bad_email"))
        old_link = LINK.search(_to(s, GOOD["email"])[0][2]).group(1)
        out, d = _call(s, emailconf.API_CHANGE, token, {"email": "clinica@gmail.com"})
        res.ok("смена: ACCEPTED, новый ящик, не подтверждён, письмо ушло",
               out == rn.ACCEPTED and d == {"ok": True, "email": "clinica@gmail.com", "confirmed": False, "sent": True},
               repr((out, d)))
        res.check("в базе — новый ящик", _state(s, cid), ("clinica@gmail.com", None))
        new = _to(s, "clinica@gmail.com")
        res.ok("письмо подтверждения — на НОВЫЙ ящик: ссылка и код",
               len(new) == 1 and "confirmați adresa" in new[0][1].lower() and CODE.search(new[0][2])
               and LINK.search(new[0][2]), repr(new)[:400])
        res.check("⭐ ссылка, ушедшая на старый ящик, новый не подтверждает — 404",
                  anon.get(old_link).status, 404)
        out, d = _call(s, emailconf.API_CONFIRM, token, {"code": CODE.search(_to(s, GOOD["email"])[0][2]).group(1)})
        res.check("⭐ код со старого ящика — неверный", d.get("code"), "email_bad_code")
        code = CODE.search(new[0][2]).group(1)
        out, d = _call(s, emailconf.API_CONFIRM, token, {"code": code})
        res.ok("код с нового ящика — ACCEPTED, подтверждён",
               out == rn.ACCEPTED and d.get("confirmed") is True and _state(s, cid)[1], repr((out, d)))
        out, d = _call(s, emailconf.API_CHANGE, token, {"email": "inca@example.md"})
        res.ok("⛔ подтверждённый ящик программа не меняет — email_locked",
               out == rn.REJECTED and d.get("code") == "email_locked" and _state(s, cid)[0] == "clinica@gmail.com",
               repr((out, d)))
        n = len(_letters(s))
        out, d = _call(s, emailconf.API_CODE, token)
        res.ok("«Retrimite» подтверждённому — ответ без письма",
               out == rn.ACCEPTED and d.get("confirmed") is True and d.get("sent") is False
               and len(_letters(s)) == n, repr((out, d)))
        res.check("/v1/license проводом программы: подтверждён", _box(s, token),
                  {"email": "clinica@gmail.com", "confirmed": True})
        log = [w for (w,) in _sql(s, "SELECT what FROM audit WHERE clinic_id=? AND what LIKE 'email%' ORDER BY id", cid)]
        res.ok("журнал: код неверный, смена, код отправлен, подтверждён",
               log[:1] == ["email_code_bad"] and "email_change" in log and "email_code_sent" in log
               and log[-1] == "email_confirmed", repr(log))
        # «Retrimite» и лимит: 3 письма в час по просьбе программы
        sent = [_call(s, emailconf.API_CODE, other)[1].get("sent") for _ in range(3)]
        out, d = _call(s, emailconf.API_CODE, other)
        res.ok("«Retrimite»: три письма в час, четвёртый — email_limited",
               sent == [True, True, True] and out == rn.REJECTED and d.get("code") == "email_limited", repr((sent, d)))
        res.check("писем подтверждения второй клинике: 1 о пробном + 3", len(_to(s, "alta@example.md")), 4)


def suite_attempts(res: Result) -> None:
    """Ошибки кода — на все живые коды клиники; ссылка из письма от них не гаснет."""
    with Server(env=AUTO) as s:
        anon = Client(s.url)
        token = _trial(anon)
        cid = _cid(s, GOOD["email"])
        body = _to(s, GOOD["email"])[0][2]
        code, link = CODE.search(body).group(1), LINK.search(body).group(1)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(emailconf.CODE_ATTEMPTS):
            _call(s, emailconf.API_CONFIRM, token, {"code": wrong})
        out, d = _call(s, emailconf.API_CONFIRM, token, {"code": code})
        res.ok(f"после {emailconf.CODE_ATTEMPTS} ошибок верный код уже не принимается",
               out == rn.REJECTED and d.get("code") == "email_bad_code" and _state(s, cid)[1] is None, repr((out, d)))
        r = anon.post(link)
        res.ok("ссылка из того же письма — работает (её ключ не угадать)", "este confirmată" in r.body
               and _state(s, cid)[1], r.body[-300:])


def suite_login(res: Result) -> None:
    """Вход в кабинет на ящик клиники — подтверждение; регистрация из кабинета — сразу подтверждена."""
    fake = FakeGoogle()        # стенд живёт до конца процесса, как в test_account
    if True:
        with Server(env={**AUTO, **fake.env}) as s:
            anon = Client(s.url)
            token = _trial(anon, email="director@clinica-test.md")
            cid = _cid(s, "director@clinica-test.md")
            res.check("до входа — не подтверждён", _state(s, cid)[1], None)
            c = Client(s.url)
            r = _google_login(c, s, fake)
            res.ok("вход Google с ящиком клиники — в её кабинет", r.status == 303 and r.location == "/cont", repr(r)[:200])
            log = _sql(s, "SELECT detail FROM audit WHERE what='email_confirmed' AND clinic_id=?", cid)
            res.ok("⭐ вход Google на ящик клиники — подтверждение (путь «intrare în cont»)",
                   _state(s, cid)[1] is not None and len(log) == 1 and "intrare în cont" in log[0][0], repr(log))
            res.check("программа узнаёт об этом из /v1/license", _box(s, token).get("confirmed"), True)
            # регистрация из кабинета на ящик входа
            fake.identity = dict(fake.identity, sub="g-nou-2", email="nou@clinica-noua.md")
            c2 = Client(s.url)
            r = _google_login(c2, s, fake)
            res.check("новый ящик — на регистрацию", r.location, "/cont/inregistrare")
            n = len(_letters(s))
            c2.post("/cont/inregistrare", name="Clinica Nouă", idno="", contact_name="Ion", phone="", consent="1")
            cid2 = _cid(s, "nou@clinica-noua.md")
            res.ok("клиника из кабинета на ящик входа — подтверждена сразу", _state(s, cid2)[1] is not None)
            mine = [x for x in _letters(s)[n:] if x[0] == "nou@clinica-noua.md"]
            res.ok("и письмо о пробном ей — без «Confirmă adresa»",
                   mine and all("Confirmă adresa" not in b for _, _, b, _ in mine), repr(mine)[:400])


def suite_admin(res: Result) -> None:
    """Метка «e-mail neconfirmat» в списке и карточке, строка «Ждёт вас»; правка ящика в админке —
    снова не подтверждён; слово журнала."""
    with Server(env=AUTO) as s:
        anon = Client(s.url)
        _trial(anon)
        cid = _cid(s, GOOD["email"])
        admin = Client(s.url).login()
        lst = admin.get("/admin").body
        row = lst[lst.index(f"/admin/clinics/{cid}'"):][:400]
        res.ok("список клиник: метка «e-mail neconfirmat» у строки клиники", "e-mail neconfirmat" in row, row)
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: метка у ящика и строка «Ждёт вас»",
               "e-mail neconfirmat" in card and "не подтверждён" in card and "Ждёт вас" in card)
        _sql(s, "UPDATE clinics SET email_confirmed_at='2026-10-27T10:00:00Z' WHERE id=?", cid)
        res.ok("подтверждённая — без метки и без строки",
               "e-mail neconfirmat" not in admin.get("/admin").body
               and "не подтверждён" not in admin.get(f"/admin/clinics/{cid}").body)
        admin.post(f"/admin/clinics/{cid}/edit", name="Clinica Mail", idno="", contact_name="Ana",
                   email="Clinica@gmial.com", phone="", address="")
        res.ok("правка без смены ящика (регистр) — подтверждение остаётся", _state(s, cid)[1] is not None)
        admin.post(f"/admin/clinics/{cid}/edit", name="Clinica Mail", idno="", contact_name="Ana",
                   email="clinica@gmail.com", phone="", address="")
        res.check("другой ящик в админке — снова не подтверждён", _state(s, cid), ("clinica@gmail.com", None))
        log = admin.get(f"/admin/clinics/{cid}").body
        res.ok("журнал карточки словами: «e-mail сменён — снова не подтверждён»", "снова не подтверждён" in log)


def suite_migration(res: Result) -> None:
    """Шаг 17 на базе шага 16: подтверждены те, у кого журнал знает доказательство ящика."""
    from app import config, db
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_cloud_mig_"))
    keep = config.DB_PATH, db.SCHEMA_VERSION
    try:
        config.DB_PATH = tmp / "cloud.db"
        db.SCHEMA_VERSION = 16
        db.init()
        con = sqlite3.connect(config.DB_PATH)
        now = "2026-10-01T09:00:00Z"
        for cid, email in (("c_code", "a@x.md"), ("c_cont", "B@x.md"), ("c_none", "c@x.md"),
                           ("c_other", "d@x.md"), ("c_empty", "")):
            con.execute("INSERT INTO clinics(id, name, email, created_at) VALUES(?,?,?,?)", (cid, cid, email, now))
        con.execute("INSERT INTO audit(at, who, what, clinic_id) VALUES('2026-10-02T10:00:00Z','program','code_ok','c_code')")
        con.execute("INSERT INTO audit(at, who, what, clinic_id) VALUES(?,?,?,?)", (now, "program", "code_sent", "c_none"))
        con.execute("INSERT INTO accounts(id, provider, subject, email, created_at, last_login_at) "
                    "VALUES('a1','email','b@x.md','b@x.md',?, '2026-10-03T08:00:00Z')", (now,))
        con.execute("INSERT INTO account_clinics(account_id, clinic_id, added_at) VALUES('a1','c_cont',?)", (now,))
        con.execute("INSERT INTO accounts(id, provider, subject, email, created_at) "
                    "VALUES('a2','google','g2','alt@x.md',?)", (now,))
        con.execute("INSERT INTO account_clinics(account_id, clinic_id, added_at) VALUES('a2','c_other',?)", (now,))
        con.commit()
        con.close()
        db.SCHEMA_VERSION = keep[1]
        db.init()
        con = sqlite3.connect(config.DB_PATH)
        got = dict(con.execute("SELECT id, email_confirmed_at FROM clinics").fetchall())
        ver = con.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[0]
        log = con.execute("SELECT clinic_id FROM audit WHERE what='email_confirmed' ORDER BY clinic_id").fetchall()
        con.close()
        res.check("схема — последняя (шаг 17 и всё, что после)", ver, str(db.SCHEMA_VERSION))
        res.check("код второго ПК — подтверждён временем кода", got["c_code"], "2026-10-02T10:00:00Z")
        res.check("вход в кабинет с ящиком клиники (регистр не важен) — подтверждён", got["c_cont"],
                  "2026-10-03T08:00:00Z")
        res.check("код отправлен, но не введён — нет", got["c_none"], None)
        res.check("вход в кабинет ДРУГИМ ящиком — нет", got["c_other"], None)
        res.check("без ящика — нет", got["c_empty"], None)
        res.check("журнал: строка на каждую подтверждённую переходом", [r[0] for r in log], ["c_code", "c_cont"])
    finally:
        config.DB_PATH, db.SCHEMA_VERSION = keep
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


ISO_DAY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def suite_dates(res: Result) -> None:
    """Даты для человека — dd.mm.yyyy в письмах и в кабинете (30.10: письмо о лицензии писало
    «până la 2026-12-29», а нота рядом — 29.12.2026). Сервер хранит ISO; клиника его не видит."""
    from datetime import datetime, timezone
    from app import mail, tiers, views
    res.check("ro_date: ISO-отметка сервера → 29.12.2026", mail.ro_date("2026-12-29T21:00:00Z"), "29.12.2026")
    res.check("ro_date: пусто → «—»", (mail.ro_date(None), mail.ro_date("")), ("—", "—"))
    res.check("кабинет и письма — один формат", views._ro("2026-12-29"), mail.ro_date("2026-12-29"))
    vu, gu = datetime(2026, 12, 29, tzinfo=timezone.utc), datetime(2027, 1, 12, tzinfo=timezone.utc)
    letters = {
        "license_letter, пробный": mail.license_letter("C", "2026-12-29T21:00:00Z", "trial", renew=True),
        "license_letter, Basic с модулем SMS": mail.license_letter("C", "2026-12-29T21:00:00Z", "standard",
                                                                   tier=tiers.BASIC, sms_until="2026-11-15T10:00:00Z"),
        "sms_name_letter": mail.sms_name_letter("C", "CLINICA", "2027-10-30T08:00:00Z", "DP-1"),
        "reminder_letter": mail.reminder_letter("expiring", "C", "trial", vu, gu, 14, None),
        "clinic_added_letter": mail.clinic_added_letter("C", vu, gu, "DP-2", 600, 1, tiers.PLUS),
    }
    for name, (subject, body) in letters.items():
        res.check(f"{name}: ни одной ISO-даты в теме и тексте", ISO_DAY.findall(subject + body), [])
    res.ok("license_letter: «până la 29.12.2026», модуль SMS — «până la 15.11.2026»",
           "până la 29.12.2026." in letters["license_letter, Basic с модулем SMS"][1]
           and "până la 15.11.2026 și" in letters["license_letter, Basic с модулем SMS"][1],
           letters["license_letter, Basic с модулем SMS"][1])
    res.ok("sms_name_letter: «până la 30.10.2027»", "până la 30.10.2027." in letters["sms_name_letter"][1])
    dev = views._cont_devices([{"os": "Windows 11", "version": "2.6.0", "last_seen_at": "2026-10-30T08:12:05Z"}],
                              "2.6.0")
    res.ok("кабинет, «Calculatoare»: ultima verificare 30.10.2026 08:12 UTC",
           "ultima verificare 30.10.2026 08:12 UTC" in dev and not ISO_DAY.search(dev), dev)


def suite_parts(res: Result) -> None:
    """Чистые части: заголовки ответа и их разбор проводом программы, текст письма."""
    from app import mail
    h = emailconf.headers({"email": "ăna+x@exemplu.md", "email_confirmed_at": None})
    res.ok("заголовки латиницей: имя ящика в %-кодировке", all(v.isascii() for v in h.values()), repr(h))
    res.check("провод программы разбирает их обратно", rn.mailbox(h), {"email": "ăna+x@exemplu.md", "confirmed": False})
    res.check("клиника без ящика — заголовков нет", emailconf.headers({"email": "", "email_confirmed_at": None}), {})
    res.check("чужие заголовки — None", rn.mailbox({"X-DentPilot-Email-Confirmed": "yes",
                                                   "X-DentPilot-Email": "a@b.md"}), None)
    body = mail.with_confirm("Bună ziua,\n\nPerioada este valabilă.\n\nRest.\n\nDentPilot", "https://u/confirma/k",
                             "123456", 7)
    res.ok("просьба — после первого абзаца, «7 zile»",
           body.split("\n\n")[2].startswith("Confirmați adresa") and "7 zile" in body, body)
    res.ok("ссылка письма — под BASE_URL, путь /confirma/",
           urlsplit(emailconf.url_for("k")).path == "/confirma/k")
    # текст — тоже поведение: политика § 5 называет срок и состав ссылки подтверждения
    pol = " ".join((CLOUD.parent / "docs" / "site" / "privacy.html").read_text(encoding="utf-8").split())
    res.ok("privacy.html: подтверждение ящика — link și cod de 6 cifre, срок emailconf.LINK_TTL",
           "Confirmarea adresei de e-mail:" in pol and "un cod de 6 cifre" in pol
           and f"(valabile {emailconf.LINK_TTL.days} zile, o singură dată)" in pol, pol[:0])
