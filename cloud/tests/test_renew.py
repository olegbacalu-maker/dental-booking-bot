"""Автообновление (L13): renew в файле, /v1/license, и клиент программы против живого сервера.

Клиент программы — bot/app/core/license_renew.py, загруженный по пути (у него
нет импортов проекта): ЕГО запрос к ЭТОМУ серверу обязан получить файл, который
принимает движок, и 204, когда новее нет. Так стенд движка (tests/test_license_renew.py)
и этот прогон сходятся на одном проводе, а не на двух мнениях о нём.
"""
import email
import email.policy
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from harness import CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path

sys.path.insert(0, str(CLOUD))
from app import license as srv  # noqa: E402 — чистые части сервера
from app import db as srv_db  # noqa: E402
from app import mail  # noqa: E402

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
rn = load_by_path("license_renew", ROOT / "bot" / "app" / "core" / "license_renew.py")
lst = load_by_path("license_state", ROOT / "bot" / "app" / "core" / "license_state.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}


def _clinic(c: Client, **over) -> str:
    fields = dict(name="Clinica Renew", idno="1234567890123", contact_name="Ion",
                  email="renew@example.md", phone="")
    fields.update(over)
    return cid_from(c.post("/admin/clinics", **fields).location)


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _get(s: Server, token: str, seq: int):
    """Запрос ровно тем клиентом, что в программе."""
    return rn.fetch(s.url + srv.RENEW_PATH, token, seq, timeout=10)


def suite_renew(res: Result) -> None:
    res.ok("правило адреса — то же, что у программы: https, http только loopback",
           all(srv._RENEW_URL.match(u) is not None for u in
               ("https://cloud.dentpilot.md/v1/license", "http://127.0.0.1:8090/v1/license", "http://localhost/x"))
           and not any(srv._RENEW_URL.match(u) for u in
                       ("http://192.168.1.5:8090/v1/license", "http://cloud.dentpilot.md/v1/license",
                        "http://127.0.0.1.evil.md/", "http://localhost@evil.md/")))
    with Server() as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        r = c.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1")
        res.check("пробный файл выдан и отправлен", r.location, f"/admin/clinics/{cid}?msg=issued_mailed")
        text1 = c.get(f"/admin/clinics/{cid}/issues/1/license.json").body
        code, claim = rv.open_envelope(text1, KEYS)
        res.check("движок принимает файл с renew", code, "")
        res.ok("renew: адрес сервера из DP_BASE_URL и токен ≥ 32 знаков",
               claim is not None and claim.renew is not None
               and claim.renew["url"] == "https://cloud.dentpilot.md/v1/license"
               and len(claim.renew["token"]) >= 32, repr(claim and claim.renew))
        token = claim.renew["token"]
        res.check("токен лежит у клиники", _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0], token)
        eml = sorted(s.outbox.glob("*.eml"))
        msg = email.message_from_bytes(eml[-1].read_bytes(), policy=email.policy.default)
        res.ok("письмо говорит: активированная программа заберёт новый файл сама",
               mail.RENEW_NOTE in msg.get_body(preferencelist=("plain",)).get_content())

        # запросы программы — её клиентом
        res.check("без токена: 401 → REFUSED", _get(s, "", 0), (rn.REFUSED, ""))
        res.check("чужой токен: 401 → REFUSED", _get(s, "x" * 43, 0), (rn.REFUSED, ""))
        res.check("токен верный, seq 0: файл 1 — тот же текст, что скачивается", _get(s, token, 0), (rn.NEWER, text1))
        res.check("seq больше выданного: 204", _get(s, token, 5), (rn.SAME, ""))
        res.check("seq 1 (уже есть): 204 → SAME", _get(s, token, 1), (rn.SAME, ""))
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: программа спрашивала, файл у программы",
               "Программа спрашивала" in card and "файл у программы" in card, card[:400])
        res.ok("чужой токен следа не оставил",
               _sql(s, "SELECT count(*) FROM clinics WHERE renew_at IS NOT NULL")[0][0] == 1)

        # продление: подтверждённый платёж выдаёт seq 2, программа его забирает
        c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="")
        pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=?", cid)[0][0]
        r = c.post(f"/admin/payments/{pid}/confirm")
        res.ok("платёж подтверждён", "payment_confirmed" in r.location, r.location)
        res.ok("до запроса программы список предупреждает: у программы файл 1",
               "у программы 1" in c.get("/admin").body)
        outcome, text2 = _get(s, token, 1)
        code, claim2 = rv.open_envelope(text2, KEYS)
        res.ok("seq 1 → файл 2, тот же токен, standard, движок принимает",
               outcome == rn.NEWER and code == "" and claim2.seq == 2 and claim2.plan == "standard"
               and claim2.renew["token"] == token, f"{outcome} {code} {claim2!r}")
        res.check("файл 2 — тот же текст, что скачивается", text2,
                  c.get(f"/admin/clinics/{cid}/issues/2/license.json").body)
        mem = lst.Memory(accepted_seq=1, valid_until=claim.valid_until, grace_until=claim.grace_until)
        st, mem2 = lst.evaluate(("", claim2), datetime.now(timezone.utc), mem, True)
        res.ok("машина состояний движка принимает файл 2 поверх памяти о файле 1",
               st.state == lst.ACTIVE and mem2.accepted_seq == 2, repr(st))
        res.check("после: 204", _get(s, token, 2), (rn.SAME, ""))
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: файл у программы, журнал — строка renew",
               "файл у программы" in card and "забран программой" in card, card[-1500:])
        rows = _sql(s, "SELECT detail FROM audit WHERE what='renew' AND clinic_id=? ORDER BY id", cid)
        res.ok("журнал: две выдачи программе — файл 1 и файл 2, а 204 строк не пишет",
               len(rows) == 2 and "файл 2" in rows[1][0] and "был 1" in rows[1][0], repr(rows))
        res.ok("в списке предупреждения больше нет", "у программы 1" not in c.get("/admin").body)
        row = _sql(s, "SELECT renew_at, renew_seq FROM clinics WHERE id=?", cid)[0]
        res.ok("след последнего запроса: когда и какой seq был у программы",
               row[0] is not None and row[1] == 2, repr(row))

        # клиника до миграции: токена нет — рождается с ближайшей выдачей
        cid2 = _clinic(c, name="Fara Token")
        _sql(s, "UPDATE clinics SET renew_token='' WHERE id=?", cid2)
        c.post(f"/admin/clinics/{cid2}/issue", kind="trial")
        code, claim3 = rv.open_envelope(c.get(f"/admin/clinics/{cid2}/issues/1/license.json").body, KEYS)
        tok2 = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid2)[0][0]
        res.ok("токен родился с выдачей и попал в файл", code == "" and len(tok2) >= 32
               and claim3.renew["token"] == tok2 and tok2 != token)
        res.check("до первой выдачи: пустой токен — не ключ ко всем", _get(s, "", 0)[0], rn.REFUSED)
        res.check("схема базы: версия как у сервера (миграция renew прошла)",
                  _sql(s, "SELECT value FROM schema_meta WHERE key='version'")[0][0], str(srv_db.SCHEMA_VERSION))

    # адрес не https и не loopback: renew в файл не пишется, письмо не обещает, check предупреждает
    with Server(env={"DP_BASE_URL": "http://192.168.1.5:8090"}) as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        c.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1")
        code, claim = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/1/license.json").body, KEYS)
        res.ok("без годного адреса файл без renew — и движок его принимает", code == "" and claim.renew is None)
        msg = email.message_from_bytes(sorted(s.outbox.glob("*.eml"))[-1].read_bytes(), policy=email.policy.default)
        res.ok("письмо без обещания автообновления",
               mail.RENEW_NOTE not in msg.get_body(preferencelist=("plain",)).get_content())
        import subprocess
        out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        res.ok("check: предупреждение про renew", "поле renew" in out.stdout, out.stdout[-600:])

    # loopback по http — стенд и сервер на том же ПК: поле есть
    with Server(env={"DP_BASE_URL": "http://127.0.0.1:8090"}) as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        c.post(f"/admin/clinics/{cid}/issue", kind="trial")
        code, claim = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/1/license.json").body, KEYS)
        res.ok("loopback: renew ведёт на http://127.0.0.1:8090/v1/license",
               code == "" and claim.renew == {"url": "http://127.0.0.1:8090/v1/license", "token": claim.renew["token"]})


def suite_request(res: Result) -> None:
    """Заявка из программы (26.09): ЕЁ провод (license_renew.request_trial) против ЭТОГО сервера.

    Адрес и путь, которые программа знает сама, — те же, что у сервера; ответ
    сервера программа понимает: токен и адрес, по которым её же fetch получает
    204 до выдачи и файл после; отказ приходит словами."""
    engine = (ROOT / "bot" / "app" / "core" / "license.py").read_text(encoding="utf-8")
    config_src = (CLOUD / "app" / "config.py").read_text(encoding="utf-8")
    m = re.search(r'^SERVER_URL = "([^"]+)"', engine, re.M)
    base = re.search(r'"DP_BASE_URL", "([^"]+)"', config_src)
    res.ok("адрес сервера в программе — умолчание DP_BASE_URL сервера",
           bool(m and base) and m.group(1) == base.group(1), f"{m and m.group(1)} / {base and base.group(1)}")
    from app import trial  # noqa: E402 — путь заявки
    path = re.search(r'^TRIAL_PATH = "([^"]+)"', engine, re.M)
    res.ok("путь заявки в программе — trial.API_PATH", bool(path) and path.group(1) == trial.API_PATH)

    s = Server()
    s.extra_env["DP_BASE_URL"] = s.url          # адрес в ответе — этот сервер (loopback)
    with s:
        fields = dict(name="Clinica Provod", idno="", contact_name="Ana", email="provod@example.md",
                      phone="", consent="1")
        outcome, data = rn.request_trial(s.url + trial.API_PATH, fields, timeout=10, agent="DentPilot/test")
        res.ok("ACCEPTED: токен и адрес, который программа согласна спрашивать",
               outcome == rn.ACCEPTED and rv.renew_url_ok(data.get("url"))
               and data.get("url") == s.url + srv.RENEW_PATH and len(data.get("token", "")) >= 32, repr(data))
        token = data.get("token", "")
        res.check("её же fetch по токену до выдачи — SAME (204)", rn.fetch(data.get("url", ""), token, 0, timeout=10),
                  (rn.SAME, ""))
        c = Client(s.url).login()
        cid = _sql(s, "SELECT id FROM clinics WHERE email=?", "provod@example.md")[0][0]
        c.post(f"/admin/clinics/{cid}/issue", kind="trial", send="1", reason="заявка из программы")
        outcome2, text = rn.fetch(data.get("url", ""), token, 0, timeout=10)
        code, claim = rv.open_envelope(text, KEYS) if outcome2 == rn.NEWER else ("нет файла", None)
        res.ok("после «Выдать» — NEWER: файл, который принимает движок, с тем же токеном",
               code == "" and claim.renew["token"] == token, f"{outcome2} {code}")
        outcome3, data3 = rn.request_trial(s.url + trial.API_PATH, fields, timeout=10)
        res.ok("повтор — REJECTED со словами сервера", outcome3 == rn.REJECTED and "înregistrată" in data3.get("text", ""),
               repr((outcome3, data3)))
        # Новый компьютер той же клиники: код на её e-mail, провод /v1/verify — токен
        vpath = re.search(r'^VERIFY_PATH = "([^"]+)"', engine, re.M)
        res.ok("путь кода в программе — trial.VERIFY_PATH", bool(vpath) and vpath.group(1) == trial.VERIFY_PATH)
        vid = data3.get("verify_id", "")
        code = ""
        for f in sorted(s.outbox.glob("*.eml")):
            m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
            if m["To"] == "provod@example.md" and "codul de activare" in m["Subject"]:
                hit = re.search(r"\b(\d{6})\b", m.get_body(preferencelist=("plain",)).get_content())
                code = hit.group(1) if hit else ""
        res.check("неверный код — REJECTED словами сервера",
                  (lambda r: (r[0], "cod" in r[1].get("text", "")))(
                      rn.verify_code(s.url + trial.VERIFY_PATH, vid, "000000" if code != "000000" else "111111", timeout=10)),
                  (rn.REJECTED, True))
        outcome5, data5 = rn.verify_code(s.url + trial.VERIFY_PATH, vid, code, timeout=10, agent="DentPilot/test")
        res.ok("код из письма — ACCEPTED: тот же токен клиники и тот же адрес",
               len(vid) >= 16 and len(code) == 6 and outcome5 == rn.ACCEPTED
               and data5.get("token") == token and data5.get("url") == data.get("url"), repr((vid, code, data5)))
        outcome6, text6 = rn.fetch(data5.get("url", ""), data5.get("token", ""), 0, timeout=10)
        code6, _claim6 = rv.open_envelope(text6, KEYS) if outcome6 == rn.NEWER else ("нет файла", None)
        res.ok("новый компьютер (seq 0) получает файл клиники, который принимает движок",
               code6 == "", f"{outcome6} {code6}")
        res.check("код одноразовый: второй раз — REJECTED",
                  rn.verify_code(s.url + trial.VERIFY_PATH, vid, code, timeout=10)[0], rn.REJECTED)
        outcome4, _ = rn.request_trial(s.url + "/v1/nu-exista", fields, timeout=10)
        res.check("чужой путь (404) — OFFLINE, не отказ", outcome4, rn.OFFLINE)

