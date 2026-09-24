"""Выдача файла: то, что выдал сервер, принимает движок — тем же кодом, что у клиники.

Проверяющая сторона — bot/app/core/rsa_verify.py и license_state.py, загруженные
по пути (у них нет импортов проекта). Ключ — тестовый из фикстур, общий для
обоих прогонов. И контрольная точка формата: сервер, подписав claim фикстуры
`valid.json`, обязан выдать ту же подпись байт в байт.
"""
import email
import email.policy
import json
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

from harness import (CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path,
                     unb64u)

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
lst = load_by_path("license_state", ROOT / "bot" / "app" / "core" / "license_state.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
DAY = timedelta(days=1)


def _new_clinic(c: Client, **over) -> str:
    fields = dict(name="Clinica Exemplu", idno="1234567890123", contact_name="Ion",
                  email="clinica@example.md", phone="")
    fields.update(over)
    return cid_from(c.post("/admin/clinics", **fields).location)


def suite_issue(res: Result) -> None:
    # контрольная точка формата: та же подпись, что у фикстуры
    import sys
    sys.path.insert(0, str(CLOUD))
    from app import keys as srv_keys
    from app import license as srv
    srv._key = srv_keys.load(str(FIX / "test-key.json"))   # config прочитан до нас: ключ — прямо в модуль
    fixture = json.loads((FIX / "valid.json").read_text(encoding="utf-8"))
    res.ok("подпись сервера над claim фикстуры — байт в байт как в valid.json",
           srv.sign(unb64u(fixture["payload"])) == unb64u(fixture["sig"]))

    with Server() as s:
        c = Client(s.url).login()
        cid = _new_clinic(c)
        r = c.post(f"/admin/clinics/{cid}/issue", kind="trial", reason="демонстрация")
        res.check("пробный файл выдан", r.location, f"/admin/clinics/{cid}?msg=issued")
        f = c.get(f"/admin/clinics/{cid}/issues/1/license.json")
        res.ok("файл скачивается как license.json",
               f.status == 200 and "license.json" in f.headers.get("content-disposition", ""))
        code, claim = rv.open_envelope(f.body, KEYS)
        res.check("движок принимает файл сервера", code, "")
        res.ok("claim: клиника, IDNO, план, seq 1, страна",
               claim is not None and claim.clinic_id == cid and claim.idno == "1234567890123"
               and claim.plan == "trial" and claim.seq == 1 and claim.country == "MD"
               and claim.clinic == "Clinica Exemplu", repr(claim))
        res.check("пробный: 14 дней", claim.valid_until - claim.issued_at, 14 * DAY)
        res.check("пробный: льгота 3 дня", claim.grace_until - claim.valid_until, 3 * DAY)
        st, _ = lst.evaluate(("", claim), datetime.now(timezone.utc), lst.Memory(), True)
        res.check("машина состояний движка: active", st.state, lst.ACTIVE)
        res.ok("движок отвергает файл под чужим ключом",
               rv.open_envelope(f.body, {"test": (KEYS["test"][0] + 2, 65537)})[0] == rv.BAD_SIGNATURE)

        until = (datetime.now(timezone.utc) + 60 * DAY).strftime("%Y-%m-%d")
        r = c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=until, grace_days="14",
                   reason="платёж DP-2026-000001")
        res.check("абонемент до даты выдан", r.location, f"/admin/clinics/{cid}?msg=issued")
        code, claim2 = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/2/license.json").body, KEYS)
        res.ok("второй файл: seq 2, standard, до названной даты, льгота 14",
               code == "" and claim2.seq == 2 and claim2.plan == "standard"
               and claim2.valid_until.strftime("%Y-%m-%d") == until
               and claim2.grace_until - claim2.valid_until == 14 * DAY, repr(claim2))
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: два файла, состояние «действует», основание",
               "license.json" in card and "действует" in card and "DP-2026-000001" in card)
        res.ok("список: тариф standard и срок", "standard" in c.get("/admin").body)
        res.check("неизвестный номер файла: 404", c.get(f"/admin/clinics/{cid}/issues/9/license.json").status, 404)
        r = c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until="2020-01-01")
        res.check("дата в прошлом: отказ", r.location, f"/admin/clinics/{cid}?msg=bad_date")
        r = c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until="не дата")
        res.check("не дата: отказ", r.location, f"/admin/clinics/{cid}?msg=bad_date")
        cid2 = _new_clinic(c, name="Fără IDNO", idno="")
        r = c.post(f"/admin/clinics/{cid2}/issue", kind="dates", valid_until=until)
        res.check("абонемент без IDNO: отказ", r.location, f"/admin/clinics/{cid2}?msg=bad_idno")
        r = c.post(f"/admin/clinics/{cid2}/issue", kind="trial")
        res.check("пробный без IDNO: можно", r.location, f"/admin/clinics/{cid2}?msg=issued")
        con = sqlite3.connect(s.dir / "cloud.db")
        try:
            sub = con.execute("SELECT plan, valid_until, grace_days FROM subscriptions WHERE clinic_id=?",
                              (cid,)).fetchone()
            n = con.execute("SELECT count(*) FROM issues").fetchone()[0]
        finally:
            con.close()
        res.ok("подписка приведена к последнему файлу",
               sub[0] == "standard" and sub[1].startswith(until) and sub[2] == 14, repr(sub))
        res.check("всего выдач в базе", n, 3)

    with Server(env={"DP_LICENSE_KEY": ""}) as s:
        c = Client(s.url).login()
        cid = _new_clinic(c)
        r = c.post(f"/admin/clinics/{cid}/issue", kind="trial")
        res.check("без ключа выдачи: отказ словами", r.location, f"/admin/clinics/{cid}?msg=no_key")


def suite_mail(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        cid = _new_clinic(c)
        r = c.post(f"/admin/clinics/{cid}/email")
        res.check("письмо до выдачи: нечего слать", r.location, f"/admin/clinics/{cid}?msg=no_issue")
        r = c.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1")
        res.check("выдать и отправить", r.location, f"/admin/clinics/{cid}?msg=issued_mailed")
        files = sorted(s.outbox.glob("*.eml"))
        res.check("в outbox одно письмо", len(files), 1)
        msg = email.message_from_bytes(files[0].read_bytes(), policy=email.policy.default)
        res.ok("тема и адресат", msg["To"] == "clinica@example.md" and "Clinica Exemplu" in msg["Subject"],
               f"{msg['To']} / {msg['Subject']}")
        parts = [p for p in msg.walk() if p.get_filename() == "license.json"]
        res.check("вложение license.json одно", len(parts), 1)
        attached = parts[0].get_payload(decode=True).decode("utf-8")
        served = c.get(f"/admin/clinics/{cid}/issues/1/license.json").body
        res.check("вложение — тот же файл, что скачивается", attached, served)
        code, claim = rv.open_envelope(attached, KEYS)
        res.check("вложение принимает движок", code, "")
        body = msg.get_body(preferencelist=("plain",)).get_content()
        res.ok("текст письма: как активировать и контакты",
               "Activează licența" in body and "+373 60 508 048" in body and "perioada de probă" in body)
        r = c.post(f"/admin/clinics/{cid}/email")
        res.check("повторная отправка последнего файла", r.location, f"/admin/clinics/{cid}?msg=mailed")
        res.check("в outbox два письма", len(list(s.outbox.glob("*.eml"))), 2)
        cid2 = _new_clinic(c, name="Fara Email", email="")
        r = c.post(f"/admin/clinics/{cid2}/issue", kind="trial", send="1")
        res.check("клиника без e-mail: файл выдан, письмо отказано словами",
                  r.location, f"/admin/clinics/{cid2}?msg=bad_email")
        res.check("файл при этом выдан", c.get(f"/admin/clinics/{cid2}/issues/1/license.json").status, 200)
        con = sqlite3.connect(s.dir / "cloud.db")
        try:
            kinds = [r[0] for r in con.execute("SELECT what FROM audit WHERE clinic_id=? ORDER BY id", (cid,))]
        finally:
            con.close()
        res.check("журнал: заведена, выдан, письмо, письмо", kinds, ["clinic_new", "issue", "mail", "mail"])
