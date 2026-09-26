"""Форма пробного периода (L14): /proba, одна клиника на IDNO/e-mail, два режима, спам.

Главное из cloud.md: второй запрос с тем же IDNO не выдаёт второй файл — и
с тем же e-mail тоже, и после скрытой заявки тоже. Режимы: approve — заявка
ждёт кнопки в админке, auto — файл сразу. Всё публичное — без куки, а всё,
что отказано, — без строки в базе.
"""
import email
import email.policy
import json
import re
import sqlite3
import subprocess
import sys

from harness import CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
sys.path.insert(0, str(CLOUD))
from app import license, mail  # noqa: E402 — срок пробного и его слова
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
GOOD = dict(name="Clinica Probă", idno="1234567890123", contact_name="Ana", email="proba@example.md",
            phone="069000000", consent="1")


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _letters(s: Server) -> list[tuple[str, str, str, bool]]:
    """(кому, тема, текст, есть ли license.json) по порядку."""
    out = []
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        out.append((m["To"], m["Subject"], m.get_body(preferencelist=("plain",)).get_content(),
                    any(p.get_filename() == "license.json" for p in m.walk())))
    return out


def _clinics(s: Server):
    return _sql(s, "SELECT id, name, idno, email, origin, requested_at, consent_at, declined_at FROM clinics ORDER BY created_at")


def suite_auto(res: Result) -> None:
    """Режим auto: файл сразу; повтор по IDNO и по e-mail — «уже есть», без второго файла."""
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        anon = Client(s.url)
        page = anon.get("/proba")
        res.ok("страница открыта всем, без куки, по-румынски, с полями и ссылками на условия",
               page.status == 200 and "set-cookie" not in page.headers and "Perioadă de probă" in page.body
               and all(f"name='{n}'" in page.body for n in ("name", "idno", "email", "consent", "website"))
               and "termeni.html" in page.body and "privacy.html" in page.body and mail.zile(license.TRIAL_DAYS) in page.body,
               page.body[:300])
        r = anon.post("/proba", **GOOD)
        res.ok("заявка принята: файл отправлен, страница называет адрес",
               r.status == 200 and "Fișierul a fost trimis" in r.body and "proba@example.md" in r.body, r.body[-600:])
        rows = _clinics(s)
        res.ok("клиника заведена с формы, согласие записано",
               len(rows) == 1 and rows[0][4] == "form" and rows[0][5] and rows[0][6] and rows[0][3] == "proba@example.md",
               repr(rows))
        cid = rows[0][0]
        res.check("пробный файл выдан: seq 1", _sql(s, "SELECT seq, reason FROM issues WHERE clinic_id=?", cid),
                  [(1, "formular de probă")])
        by_to = {t: (sub, body, att) for t, sub, body, att in _letters(s)}
        res.ok("два письма: клинике с файлом, Олегу уведомление",
               len(by_to) == 2 and by_to["proba@example.md"][2] and "заявка на пробный" in by_to["oleg@example.md"][0]
               and "выдан и отправлен" in by_to["oleg@example.md"][1]
               and f"/admin/clinics/{cid}" in by_to["oleg@example.md"][1], repr({t: v[0] for t, v in by_to.items()}))
        c = Client(s.url).login()
        code, claim = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/1/license.json").body, KEYS)
        res.ok("файл принимает движок: trial, клиника и IDNO из формы, renew есть",
               code == "" and claim.plan == "trial" and claim.clinic == "Clinica Probă"
               and claim.idno == "1234567890123" and claim.renew is not None, f"{code} {claim!r}")
        res.check("журнал: trial_request с адресом",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='trial_request' AND clinic_id=?", cid)[0][0], 1)

        # повтор по IDNO с другим e-mail: клинике то же «принято», Олегу — «ПОВТОР», файла нет
        n = len(_letters(s))
        r = anon.post("/proba", **dict(GOOD, email="alt@example.md", name="Altă Denumire"))
        res.ok("тот же IDNO: страница как у принятой заявки — форма не оракул",
               r.status == 200 and "Cererea a fost primită" in r.body and "înregistrată" not in r.body, r.body[-400:])
        last = _letters(s)[-1]
        res.ok("Олегу письмо о повторе с тем, что написали, и с той клиникой, что уже есть",
               len(_letters(s)) == n + 1 and last[0] == "oleg@example.md" and "ПОВТОР" in last[2]
               and "alt@example.md" in last[2] and "Altă Denumire" in last[1] and cid in last[2], last[2][-300:])
        # повтор по ящику: регистр, +метка, точки gmail, адрес в угловых скобках — один ящик
        for label, em in (("регистр другой", "PROBA@Example.MD"), ("+метка", "proba+dp@example.md")):
            r = anon.post("/proba", **dict(GOOD, idno="", email=em))
            res.ok(f"тот же ящик ({label}), без IDNO: второго файла нет",
                   "Cererea a fost primită" in r.body and len(_clinics(s)) == 1, r.body[-200:])
        r = anon.post("/proba", **dict(GOOD, idno="", email="<proba@example.md>"))
        res.ok("адрес в угловых скобках — не адрес: 400", r.status == 400 and "e-mail" in r.body, f"{r.status}")
        res.ok("клиника одна, выдача одна",
               len(_clinics(s)) == 1 and _sql(s, "SELECT count(*) FROM issues")[0][0] == 1)
        res.check("журнал: три trial_duplicate, ни один не на карточке клиники",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='trial_duplicate' AND clinic_id IS NULL")[0][0], 3)
        res.check("на карточке клиники повторов нет",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='trial_duplicate' AND clinic_id=?", cid)[0][0], 0)

        # ошибки полей — ничего не создаётся
        for label, bad, word in (("IDNO из 12 цифр", dict(GOOD, idno="123456789012", email="x1@example.md"), "13 cifre"),
                                 ("без e-mail", dict(GOOD, idno="", email=""), "e-mail"),
                                 ("e-mail без @", dict(GOOD, idno="", email="nu-e-mail"), "e-mail"),
                                 ("название из одной буквы", dict(GOOD, name="A", idno="", email="x2@example.md"), "Denumirea"),
                                 ("без согласия", dict(GOOD, idno="", email="x3@example.md", consent=""), "acordul")):
            r = anon.post("/proba", **bad)
            res.ok(f"{label}: 400, форма с ошибкой", r.status == 400 and word in r.body and "name='name'" in r.body,
                   f"{r.status} {r.body[-300:]}")
        res.check("клиника по-прежнему одна", len(_clinics(s)), 1)
        # скрытое поле — боту «принято», в базе пусто; это пятая засчитанная заявка с адреса
        n_l = len(_letters(s))
        r = anon.post("/proba", **dict(GOOD, idno="", email="bot@example.md", website="http://spam"))
        res.ok("скрытое поле заполнено: страница «принято», ничего не создано",
               r.status == 200 and "primită" in r.body and len(_clinics(s)) == 1 and len(_letters(s)) == n_l)
        res.ok("лог сервера видел бота", "скрытое поле" in s.log())
        # лимит с адреса: пять засчитанных (принята, повтор IDNO, два повтора ящика, бот — ошибки полей не считаются)
        r = anon.post("/proba", **dict(GOOD, idno="", email="l9@example.md"))
        res.ok("шестой запрос с адреса за час — 429 со словами, без строки",
               r.status == 429 and "Prea multe cereri" in r.body and len(_clinics(s)) == 1, f"{r.status}")
        card = c.get("/admin").body
        res.ok("список клиник: заявок на пробный нет (файл уже выдан)", "Заявки на пробный период" not in card)


def suite_rules(res: Result) -> None:
    """Чистые правила формы: канонический ящик, поля, лимит по адресу и общий."""
    from app import trial
    res.check("канонический ящик: регистр, +метка, точки gmail",
              [trial.canonical(e) for e in ("A.B+x@Gmail.COM", "ab@gmail.com", "a.b@example.md", "a.b+t@example.md")],
              ["ab@gmail.com", "ab@gmail.com", "a.b@example.md", "a.b@example.md"])
    f, code = trial.clean(dict(name="  Clinica\n  X ", idno="1234 5678 90123", email=" a@b.md ", consent="1"))
    res.ok("clean: пробелы схлопнуты, IDNO без пробелов, e-mail без пробелов",
           code == "" and f["name"] == "Clinica X" and f["idno"] == "1234567890123" and f["email"] == "a@b.md", repr(f))
    for label, fields, want in (("имя с запятой", dict(name="Xy", email="a,b@c.md", consent="1"), "bad_email"),
                                ("два @", dict(name="Xy", email="a@b@c.md", consent="1"), "bad_email"),
                                ("домен без точки", dict(name="Xy", email="a@b", consent="1"), "bad_email"),
                                ("контакт длиннее 80", dict(name="Xy", email="a@b.md", contact_name="и" * 81, consent="1"), "too_long"),
                                ("согласие не 1", dict(name="Xy", email="a@b.md", consent="yes"), "no_consent")):
        res.check(f"clean: {label} → {want}", trial.clean(fields)[1], want)
    res.check("ключ лимита: IPv4 — адрес, IPv6 — сеть /64, мусор — как есть",
              [trial.bucket(ip) for ip in ("10.0.0.1", "2001:db8:1:2:3:4:5:6", "2001:db8:1:2:ffff::1", "nope")],
              ["10.0.0.1", "2001:db8:1:2::/64", "2001:db8:1:2::/64", "nope"])
    trial._hits.clear(); trial._all.clear()
    for _ in range(trial.MAX_PER_HOUR):
        trial.note("2001:db8:1:2:3:4:5:6")
    res.ok("IPv6: другой адрес той же /64 упирается в тот же лимит",
           trial.limited("2001:db8:1:2:ffff::1") and not trial.limited("2001:db8:1:3::1"))
    trial._hits.clear(); trial._all.clear()
    for i in range(trial.MAX_TOTAL_PER_HOUR):
        trial.note(f"10.1.{i // 250}.{i % 250 + 1}")
    res.ok("общий потолок: свежий адрес получает отказ, когда заявок со всех слишком много",
           trial.limited("192.0.2.1"))
    trial._hits.clear(); trial._all.clear()


def suite_approve(res: Result) -> None:
    """Режим approve (по умолчанию): заявка ждёт кнопки; выдать, скрыть; check."""
    with Server(env={"DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        anon = Client(s.url)
        r = anon.post("/proba", **GOOD)
        res.ok("заявка принята: «cererea a fost primită»", r.status == 200 and "Cererea a fost primită" in r.body,
               r.body[-400:])
        rows = _clinics(s)
        cid = rows[0][0]
        res.ok("клиника есть, файла нет", len(rows) == 1 and _sql(s, "SELECT count(*) FROM issues")[0][0] == 0)
        by_to = {t: (sub, body, att) for t, sub, body, att in _letters(s)}
        res.ok("письма: клинике «принято» без файла, Олегу — ждёт решения",
               len(by_to) == 2 and "a fost primită" in by_to["proba@example.md"][0]
               and not by_to["proba@example.md"][2] and "ждёт решения" in by_to["oleg@example.md"][1],
               repr({t: v[0] for t, v in by_to.items()}))
        c = Client(s.url).login()
        page = c.get("/admin").body
        res.ok("список клиник: заявка на пробный с кнопками",
               "Заявки на пробный период (1)" in page and "Clinica Probă" in page
               and "Выдать пробный и отправить" in page and f"/admin/clinics/{cid}/decline" in page)
        r = anon.post("/proba", **dict(GOOD, email="alt@example.md"))
        res.ok("повтор по IDNO, пока заявка ждёт: «принято», второй клиники нет",
               "Cererea a fost primită" in r.body and len(_clinics(s)) == 1)
        r = c.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1", reason="заявка с формы")
        res.check("кнопка: пробный выдан и отправлен", r.location, f"/admin/clinics/{cid}?msg=issued_mailed")
        res.ok("файл ушёл клинике, заявка исчезла из списка",
               _letters(s)[-1][0] == "proba@example.md" and _letters(s)[-1][3]
               and "Заявки на пробный период" not in c.get("/admin").body)
        code, claim = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/1/license.json").body, KEYS)
        res.ok("файл принимает движок", code == "" and claim.plan == "trial")

        # вторая заявка — скрыть; после скрытия повтор всё равно «уже есть»
        r = anon.post("/proba", **dict(GOOD, name="A Doua", idno="9876543210987", email="doua@example.md"))
        res.ok("вторая клиника — заявка", "Cererea a fost primită" in r.body and len(_clinics(s)) == 2)
        cid2 = _clinics(s)[1][0]
        r = c.post(f"/admin/clinics/{cid2}/decline")
        res.check("скрыть: 303 с trial_declined", r.location, "/admin?msg=trial_declined")
        res.ok("заявок в списке нет, клиника осталась, declined_at записан",
               "Заявки на пробный период" not in c.get("/admin").body and _clinics(s)[1][7])
        r = anon.post("/proba", **dict(GOOD, name="A Doua", idno="9876543210987", email="doua2@example.md"))
        res.ok("«Скрыть» освобождает IDNO: новая заявка заведена третьей клиникой",
               "Cererea a fost primită" in r.body and len(_clinics(s)) == 3 and _clinics(s)[2][2] == "9876543210987")
        res.check("журнал: trial_declined", _sql(s, "SELECT count(*) FROM audit WHERE what='trial_declined'")[0][0], 1)
        # перевод строки в названии — не второй заголовок письма, а пробел
        r = anon.post("/proba", **dict(GOOD, name="Clinica\r\nBcc: evil@example.md", idno="", email="crlf@example.md"))
        res.ok("CRLF в названии: принято одной строкой, без 500",
               r.status == 200 and _clinics(s)[-1][1] == "Clinica Bcc: evil@example.md", f"{r.status} {_clinics(s)[-1][1]!r}")
        res.ok("в письме Олегу тема одной строкой",
               any("Clinica Bcc: evil@example.md" in sub for _, sub, _, _ in _letters(s)[-2:]))
        res.check("скрыть несуществующую: 404", c.post("/admin/clinics/c_nope/decline").status, 404)
        res.check("скрыть без входа: на вход", Client(s.url).post(f"/admin/clinics/{cid}/decline").status, 303)
        out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                             capture_output=True, text=True, encoding="utf-8")
        res.ok("check: форма пробного, режим approve, ящик уведомлений",
               "форма пробного" in out.stdout and "режим approve" in out.stdout and "oleg@example.md" in out.stdout,
               out.stdout[-400:])
        # без ящика писем заявка всё равно принимается
    with Server(env={"DP_MAIL_OUTBOX": "", "DP_SMTP_HOST": ""}) as s:
        r = Client(s.url).post("/proba", **GOOD)
        res.ok("почта не настроена: заявка принята, клиника заведена, без падения",
               r.status == 200 and "Cererea a fost primită" in r.body and len(_clinics(s)) == 1, f"{r.status}")
    # auto, почта не настроена: файл выдан, письмо не ушло — клинике «принято», Олегу правда
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_MAIL_OUTBOX": "", "DP_SMTP_HOST": ""}) as s:
        r = Client(s.url).post("/proba", **GOOD)
        res.ok("auto без почты: файл выдан, страница «принято», а не «отправлено»",
               r.status == 200 and "Cererea a fost primită" in r.body and "a plecat" not in r.body
               and _sql(s, "SELECT count(*) FROM issues")[0][0] == 1
               and _sql(s, "SELECT count(*) FROM audit WHERE what='mail_failed'")[0][0] == 1, f"{r.status}")
    # auto без ключа выдачи: файла не будет — заявка остаётся заявкой, не пятисотой
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_LICENSE_KEY": ""}) as s:
        r = Client(s.url).post("/proba", **GOOD)
        res.ok("auto без ключа: «принято», клиника ждёт в заявках, журнал trial_no_key",
               r.status == 200 and "Cererea a fost primită" in r.body and len(_clinics(s)) == 1
               and _sql(s, "SELECT count(*) FROM issues")[0][0] == 0
               and _sql(s, "SELECT count(*) FROM audit WHERE what='trial_no_key'")[0][0] == 1
               and "Заявки на пробный период (1)" in Client(s.url).login().get("/admin").body, f"{r.status}")


# ---------- заявка из программы (26.09): активация без файла ----------

API = "/v1/trial"


def _api(c: Client, fields: dict) -> tuple[int, dict]:
    """Заявка так, как её шлёт программа: JSON, без куки и без Origin."""
    r = c.post_raw(API, json.dumps(fields).encode("utf-8"))
    try:
        return r.status, json.loads(r.body)
    except ValueError:
        return r.status, {}


def _poll(c: Client, token: str, seq: int = 0):
    return c.get(f"/v1/license?seq={seq}", headers={"Authorization": f"Bearer {token}"})


def suite_program(res: Result) -> None:
    """Заявка из программы: токен сразу, файл по нему после выдачи; повтор — 409; скрыть — 401."""
    with Server(env={"DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:          # approve
        anon = Client(s.url)
        mine = dict(GOOD, idno="", name="Clinica Program", email="prog@example.md")
        st, d = _api(anon, mine)
        res.ok("approve: принято — state requested, токен ≥ 32 знаков и адрес /v1/license",
               st == 200 and d.get("ok") is True and d.get("state") == "requested"
               and len(d.get("token", "")) >= 32 and d.get("url", "").endswith("/v1/license"), repr(d))
        token = d.get("token", "")
        res.check("по токену до выдачи — 204, файла ещё нет", _poll(anon, token).status, 204)
        rows = _clinics(s)
        cid = rows[-1][0]
        res.ok("клиника заведена заявкой из программы: origin program, согласие записано",
               rows[-1][4] == "program" and rows[-1][6], repr(rows[-1]))
        by_to = {t: (sub, body, att) for t, sub, body, att in _letters(s)}
        res.ok("письма: клинике «программа активируется сама», Олегу «из программы»",
               "se activează singur" in by_to.get("prog@example.md", ("", "", 0))[1]
               and "из программы" in by_to.get("oleg@example.md", ("", "", 0))[1],
               repr({t: v[1][:120] for t, v in by_to.items()}))
        c = Client(s.url).login()
        page = c.get("/admin").body
        res.ok("заявка из программы — в списке заявок с меткой",
               "Заявки на пробный период (1)" in page and "Clinica Program" in page and "программа" in page)
        r = c.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1", reason="заявка из программы")
        res.check("кнопка «Выдать»", r.location, f"/admin/clinics/{cid}?msg=issued_mailed")
        r = _poll(anon, token)
        code, claim = rv.open_envelope(r.body, KEYS) if r.status == 200 else ("нет файла", None)
        res.ok("по тому же токену — файл: движок принимает, внутри тот же токен",
               code == "" and claim.plan == "trial" and claim.renew["token"] == token, f"{r.status} {code}")

        st, d = _api(anon, dict(mine, name="Alta Clinica"))
        res.ok("повтор по e-mail: 409 duplicate с текстом, без токена, вторая клиника не заведена",
               st == 409 and d.get("code") == "duplicate" and "token" not in d
               and "înregistrată" in d.get("text", "") and len(_clinics(s)) == 1, repr(d))
        st, d = _api(anon, dict(GOOD, email="nu-e-email"))
        res.ok("поле: 400 bad_email со словами формы", st == 400 and d.get("code") == "bad_email"
               and "e-mail" in d.get("text", ""), repr(d))
        st, d = _api(anon, dict(GOOD, consent=""))
        res.check("без согласия: 400 no_consent", (st, d.get("code")), (400, "no_consent"))
        r = anon.post_raw(API, b"<html>nu e json</html>")
        res.check("не JSON: 400 bad_json", (r.status, json.loads(r.body).get("code")), (400, "bad_json"))
        res.check("отказы полей клиник не заводят", len(_clinics(s)), 1)

        st, d = _api(anon, dict(GOOD, name="De Ascuns", idno="1112223334445", email="skip@example.md"))
        token2 = d.get("token", "")
        cid2 = _clinics(s)[-1][0]
        c.post(f"/admin/clinics/{cid2}/decline")
        res.check("скрытая заявка: токен отозван — 401", _poll(anon, token2).status, 401)

        codes = [_api(anon, dict(GOOD, name=f"Limita {i}", idno="", email=f"l{i}@example.md"))[1].get("code")
                 for i in range(4)]
        res.ok("лимит с адреса — тот же, что у формы: 429 limited",
               "limited" in codes and codes.index("limited") <= 2, repr(codes))

    with Server(env={"DP_TRIAL_MODE": "auto"}) as s:
        anon = Client(s.url)
        st, d = _api(anon, dict(GOOD, email="auto@example.md"))
        res.ok("auto: state issued", st == 200 and d.get("state") == "issued", repr(d))
        r = _poll(anon, d.get("token", ""))
        code, claim = rv.open_envelope(r.body, KEYS) if r.status == 200 else ("нет файла", None)
        res.ok("auto: файл сразу, и токен внутри файла — тот, что отдан программе",
               code == "" and claim.renew["token"] == d.get("token"), f"{r.status} {code}")
        res.ok("auto: письмо с файлом ушло клинике — запасной путь",
               any(t == "auto@example.md" and att for t, _s, _b, att in _letters(s)))


# ---------- новый компьютер той же клиники: код на e-mail (26.09) ----------


def _code_from(s: Server, to: str) -> str:
    """Шестизначный код из последнего письма «codul de activare» на адрес `to`."""
    for addr, subject, body, _att in reversed(_letters(s)):
        if addr == to and "codul de activare" in subject:
            m = re.search(r"\b(\d{6})\b", body)
            return m.group(1) if m else ""
    return ""


def _verify(c: Client, vid: str, code: str) -> tuple[int, dict]:
    r = c.post_raw("/v1/verify", json.dumps({"verify_id": vid, "code": code}).encode("utf-8"))
    try:
        return r.status, json.loads(r.body)
    except ValueError:
        return r.status, {}


def _write(s: Server, sql: str, *args) -> None:
    con = sqlite3.connect(s.dir / "cloud.db", timeout=10)
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def suite_code(res: Result) -> None:
    """Повтор из программы: код на записанный e-mail клиники, код → её токен → её файл."""
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        anon = Client(s.url)
        first = dict(GOOD, name="Clinica Veche", email="veche@example.md")
        st, d = _api(anon, first)
        token = d.get("token", "")
        res.ok("первый компьютер: заявка, файл сразу (auto)", st == 200 and d.get("state") == "issued", repr(d))

        st, d = _api(anon, dict(first, email="alt@example.md"))       # тот же IDNO, другой ящик
        vid = d.get("verify_id", "")
        res.ok("повтор из программы: 409 с verify_id и словами «cod de activare»",
               st == 409 and d.get("code") == "duplicate" and len(vid) >= 16
               and "cod de activare" in d.get("text", ""), repr(d))
        code = _code_from(s, "veche@example.md")
        res.ok("код ушёл на ящик, записанный у клиники, а не на вписанный в заявку",
               len(code) == 6 and not _code_from(s, "alt@example.md"), code)
        res.ok("в базе кода открытым текстом нет",
               not _sql(s, "SELECT 1 FROM activation_codes WHERE code_hash=? OR id=?", code, code))
        wrong = "000000" if code != "000000" else "111111"
        res.check("неверный код: 400 bad_code", (lambda r: (r[0], r[1].get("code")))(_verify(anon, vid, wrong)),
                  (400, "bad_code"))
        st, d = _verify(anon, vid, code)
        res.ok("верный код: токен этой клиники и адрес /v1/license",
               st == 200 and d.get("token") == token and d.get("url", "").endswith("/v1/license"), repr(d))
        r = _poll(anon, d.get("token", ""))
        code_, claim = rv.open_envelope(r.body, KEYS) if r.status == 200 else ("нет файла", None)
        res.ok("по нему — файл этой клиники", code_ == "" and claim.clinic == "Clinica Veche", f"{r.status} {code_}")
        res.check("код одноразовый: второй раз — 400", _verify(anon, vid, code)[0], 400)

        _st, d = _api(anon, first)
        vid2, code2 = d.get("verify_id", ""), _code_from(s, "veche@example.md")
        bad = "999999" if code2 != "999999" else "888888"
        for _ in range(5):
            _verify(anon, vid2, bad)
        res.check("пять ошибок сжигают код: и верный уже не принят", _verify(anon, vid2, code2)[0], 400)

        _st, d = _api(anon, first)
        vid3, code3 = d.get("verify_id", ""), _code_from(s, "veche@example.md")
        _write(s, "UPDATE activation_codes SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", vid3)
        res.check("просроченный код — 400", _verify(anon, vid3, code3)[0], 400)

        st, d = _api(anon, first)
        res.ok("четвёртый код за час не шлётся: 409 без verify_id", st == 409 and "verify_id" not in d, repr(d))
        notes = [b for t2, _s, b, _a in _letters(s) if t2 == "oleg@example.md"]
        res.ok("Олегу: повтор из программы — код ушёл клинике", any("код активации" in b for b in notes))

    # свой сервер: лимит заявок с адреса (5 в час) выше уже выбран
    with Server(env={"DP_TRIAL_MODE": "auto"}) as s:
        anon = Client(s.url)
        hidden = dict(GOOD, name="Clinica Ascunsa", idno="", email="ascunsa@example.md")
        _api(anon, hidden)
        _st, d = _api(anon, hidden)
        vid4, code4 = d.get("verify_id", ""), _code_from(s, "ascunsa@example.md")
        _write(s, "UPDATE clinics SET declined_at='2026-09-26T10:00:00Z' WHERE email=?", "ascunsa@example.md")
        res.ok("заявку скрыли, пока код шёл: верный код токена не даёт (400)",
               len(code4) == 6 and _verify(anon, vid4, code4)[0] == 400, f"{vid4!r} {code4!r}")

