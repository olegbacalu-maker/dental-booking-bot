"""Форма пробного периода (L14): /proba, одна клиника на IDNO/e-mail, два режима, спам.

Главное из cloud.md: второй запрос с тем же IDNO не выдаёт второй файл — и
с тем же e-mail тоже, и после скрытой заявки тоже. Режимы: approve — заявка
ждёт кнопки в админке, auto — файл сразу. Всё публичное — без куки, а всё,
что отказано, — без строки в базе.
"""
import email
import email.policy
import json
import sqlite3
import subprocess
import sys

from harness import CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
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
               and "termeni.html" in page.body and "privacy.html" in page.body and "14 zile" in page.body,
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

        # повтор по IDNO с другим e-mail
        r = anon.post("/proba", **dict(GOOD, email="alt@example.md", name="Altă Denumire"))
        res.ok("тот же IDNO: «уже зарегистрирована», без второго файла",
               r.status == 200 and "deja înregistrată" in r.body and "alt@example.md" not in r.body, r.body[-400:])
        # повтор по e-mail без IDNO, регистр другой
        r = anon.post("/proba", **dict(GOOD, idno="", email="PROBA@example.md"))
        res.ok("тот же e-mail (регистр другой), без IDNO: «уже зарегистрирована»", "deja înregistrată" in r.body)
        res.ok("клиника одна, выдача одна, писем по-прежнему два",
               len(_clinics(s)) == 1 and _sql(s, "SELECT count(*) FROM issues")[0][0] == 1 and len(_letters(s)) == 2)
        res.check("журнал: два trial_duplicate на ту же клинику",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='trial_duplicate' AND clinic_id=?", cid)[0][0], 2)

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
        # скрытое поле — боту «принято», в базе пусто
        r = anon.post("/proba", **dict(GOOD, idno="", email="bot@example.md", website="http://spam"))
        res.ok("скрытое поле заполнено: страница «принято», ничего не создано",
               r.status == 200 and "primită" in r.body and len(_clinics(s)) == 1 and len(_letters(s)) == 2)
        res.ok("лог сервера видел бота", "скрытое поле" in s.log())
        # лимит с адреса: заявок уже 3 засчитанных (принята, дубли, бот считаются) — добираем до пяти
        n0 = len(_clinics(s))
        codes = [anon.post("/proba", **dict(GOOD, idno="", email=f"l{i}@example.md")).status for i in range(4)]
        res.ok("шестой запрос с адреса за час — 429, до него заявки шли",
               codes[:-1].count(200) >= 1 and codes[-1] == 429, repr(codes))
        r = anon.post("/proba", **dict(GOOD, idno="", email="l9@example.md"))
        res.ok("и дальше 429 со словами", r.status == 429 and "Prea multe cereri" in r.body)
        res.ok("лимит не создал лишних клиник сверх принятых", len(_clinics(s)) == n0 + codes[:-1].count(200))
        card = c.get("/admin").body
        res.ok("список клиник: заявок на пробный нет (файл уже выдан)", "Заявки на пробный период" not in card)


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
        res.ok("повтор по IDNO, пока заявка ждёт: «уже зарегистрирована»", "deja înregistrată" in r.body
               and len(_clinics(s)) == 1)
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
        res.ok("повтор скрытой заявки по IDNO: «уже зарегистрирована», третьей клиники нет",
               "deja înregistrată" in r.body and len(_clinics(s)) == 2)
        res.check("журнал: trial_declined", _sql(s, "SELECT count(*) FROM audit WHERE what='trial_declined'")[0][0], 1)
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
    # auto без ключа выдачи: файла не будет — заявка остаётся заявкой, не пятисотой
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_LICENSE_KEY": ""}) as s:
        r = Client(s.url).post("/proba", **GOOD)
        res.ok("auto без ключа: «принято», клиника ждёт в заявках, журнал trial_no_key",
               r.status == 200 and "Cererea a fost primită" in r.body and len(_clinics(s)) == 1
               and _sql(s, "SELECT count(*) FROM issues")[0][0] == 0
               and _sql(s, "SELECT count(*) FROM audit WHERE what='trial_no_key'")[0][0] == 1
               and "Заявки на пробный период (1)" in Client(s.url).login().get("/admin").body, f"{r.status}")
