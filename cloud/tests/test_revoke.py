"""Отзыв лицензии из админки (revoke.py) и IDNO заявки пробного (trial.idno_ok) — 11.11.2026,
Олег: «Да, А + IDNO».

Главное: отзыв — обычный подписанный файл со сроком «сейчас», который программа берёт тем же
запросом и уходит в «только чтение» (проверяется её же разбором `rsa_verify` и правилом
`license_state.by_dates`); пока он стоит, ни одна дверь не выдаёт файл и не берёт денег за срок,
а IDNO, ящик и компьютер отозванной клиники нового пробного не получают.
"""
import json
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

from harness import CLOUD, FIX, ROOT, Client, Result, Server, load_by_path

sys.path.insert(0, str(CLOUD))
from app import db as cdb, revoke, trial, views  # noqa: E402
from test_branches import BANK_ENV, BRANCH, DIRECTOR, MAIN, _enter, _letters, _register, _sql  # noqa: E402
from test_jobs import _run  # noqa: E402
from test_paylink import HDR, _link  # noqa: E402
from test_tiers import _json  # noqa: E402

rv = load_by_path("rsa_verify_revoke", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
ls = load_by_path("license_state_revoke", ROOT / "bot" / "app" / "core" / "license_state.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
ENV = {**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md", "DP_SMS_OFFERED": "1",
       "DP_SMSMD_TOKEN": "t", "DP_SMSMD_BASE_URL": "http://127.0.0.1:9", "DP_SMS_PACKS": "100:50"}
# настоящие публичные IDNO (реестр плательщиков НДС, python-stdnum, банки) — контрольная 7-3-1 сходится
REAL = ("1002600000803", "1002601003214", "1020608000025", "1008600038413", "1002600003778")
BAD = ("0000000000000", "1111111111111", "100260000080", "10026000008030", "10026000O0803", "1002600000804",
       "abcdefghijklm")
PROG = dict(name="Clinica Revocare", idno=REAL[1], contact_name="Ana", email="revocare@example.md",
            phone="069000000", consent="1")
REASON = "IDNO fals, cutie de unica folosinta"


def _msg(r) -> str:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.location).query)).get("msg", "")


def _seq(s: Server, cid: str) -> int:
    return _sql(s, "SELECT COALESCE(MAX(seq), 0) FROM issues WHERE clinic_id=?", cid)[0][0]


def _program(s: Server, fields: dict = PROG, hdr: dict = HDR) -> tuple[int, dict]:
    anon = Client(s.url)
    r = anon._do(trial.API_PATH, json.dumps(fields).encode("utf-8"), {**hdr, "Content-Type": "application/json"})
    try:
        return r.status, json.loads(r.body)
    except ValueError:
        return r.status, {}


def _poll(s: Server, token: str, seq: int):
    return Client(s.url)._do(f"/v1/license?seq={seq}", None, {**HDR, "Authorization": f"Bearer {token}"})


def _revoke(admin: Client, cid: str, **over):
    return admin.post(f"/admin/clinics/{cid}/revoke", **{"reason": REASON, "confirm": "ОТОЗВАТЬ", **over})


def _claim(text: str):
    code, claim = rv.open_envelope(text, KEYS)
    return code, claim


def suite_idno(res: Result) -> None:
    """IDNO: контрольная 7-3-1, не все одинаковые, пустой можно — чисто и на трёх дверях пробного."""
    res.ok("пять настоящих публичных IDNO проходят", all(trial.idno_ok(x) for x in REAL),
           [x for x in REAL if not trial.idno_ok(x)])
    res.check("нули, единицы, 12 и 14 цифр, буква, чужая контрольная, буквы — отказ",
              [x for x in BAD if trial.idno_ok(x)], [])
    res.check("0000000000000: контрольная сходится — отказ даёт правило «не все одинаковые»",
              sum(int(d) * w for d, w in zip("000000000000", (7, 3, 1) * 4)) % 10, 0)
    for x in ("0000000000000", "1111111111111"):
        res.check(f"clean: {x} → bad_idno",
                  trial.clean(dict(name="Clinica X", idno=x, email="a@b.md", consent="1"))[1], "bad_idno")
    res.check("clean: пустой IDNO пробному — можно, как раньше",
              trial.clean(dict(name="Clinica X", idno="", email="a@b.md", consent="1"))[1], "")
    res.ok("текст отказа — по-румынски и называет контрольную цифру",
           "cifra de control" in views.TRIAL_MSG["bad_idno"] and "13 cifre" in views.TRIAL_MSG["bad_idno"])
    with Server(env=ENV) as s:
        before = _sql(s, "SELECT count(*) FROM clinics")[0][0]
        st, body = _program(s, {**PROG, "idno": "0000000000000"})
        res.ok("программа: 0000000000000 → 400 bad_idno, текст сервера как есть",
               st == 400 and body.get("code") == "bad_idno" and body.get("text") == views.TRIAL_MSG["bad_idno"],
               (st, body))
        r = Client(s.url).post("/proba", **{**PROG, "idno": "1111111111111", "email": "proba1@example.md"})
        res.ok("/proba: 1111111111111 — форма с отказом, клиника не заведена",
               r.status in (200, 400) and "cifra de control" in r.body, (r.status, r.body[:200]))
        c = _enter(s, DIRECTOR)
        r = c.post("/cont/inregistrare", **{**MAIN, "idno": "1003600012345"})
        res.ok("кабинет: IDNO с чужой контрольной — регистрация не прошла",
               "cifra de control" in r.body or "bad_idno" in r.location, (r.status, r.location))
        res.check("ни одна из трёх дверей не завела клинику", _sql(s, "SELECT count(*) FROM clinics")[0][0], before)
        st, body = _program(s, {**PROG, "idno": ""})
        res.ok("программа: пустой IDNO — пробный, как раньше", st == 200 and body.get("state") == "issued", (st, body))
        st, body = _program(s, {**PROG, "idno": REAL[0], "email": "real@example.md"},
                            {**HDR, "X-DentPilot-Device": "d_00000000real"})
        res.ok("программа: настоящий IDNO — пробный", st == 200 and body.get("state") == "issued", (st, body))


def suite_revoke(res: Result) -> None:
    """Отзыв: подтверждение, файл со сроком «сейчас», программа — в чтение, SMS, оплата, кабинет, письма."""
    with Server(env=ENV) as s:
        c = _enter(s, DIRECTOR)
        cid = _register(s, c)
        tok = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]
        anon = Client(s.url)
        first = _poll(s, tok, 0)
        res.ok("до отзыва: программа забрала пробный № 1", first.status == 200 and _seq(s, cid) == 1, first.status)
        _, pay_url = _link(anon, tok)
        admin = Client(s.url).login()
        r = admin.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="", method="transfer", tier="")
        note = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending' AND kind='license'", cid)
        res.ok("до отзыва: нота абонемента выставлена (заплатят позже по ней)", bool(note), _msg(r))
        card = admin.get(f"/admin/clinics/{cid}").body
        form = card[card.find(f"action='/admin/clinics/{cid}/revoke'"):]
        form = form[:form.find("</form>")]
        res.ok("карточка: кнопка «Отозвать лицензию», слово, причина, письмо снято по умолчанию",
               bool(form) and "name='confirm'" in form and "name='reason'" in form and " required" in form
               and "name='send' value='1'>" in form and "checked" not in form, form[:300])
        mails = len([x for x in _letters(s) if x[0] == DIRECTOR])

        res.check("без причины — отказ", _msg(_revoke(admin, cid, reason="  ")), revoke.NEED_REASON)
        res.check("без слова ОТОЗВАТЬ — отказ", _msg(_revoke(admin, cid, confirm="да")), revoke.NEED_WORD)
        res.check("отказы файла не выдали", _seq(s, cid), 1)
        r = _revoke(admin, cid, confirm="отозвать")
        res.check("слово в любом регистре — отозвана", _msg(r), revoke.REVOKED)
        row = _sql(s, "SELECT revoked_at IS NOT NULL, revoked_reason, revoked_seq, revoked_by FROM clinics WHERE id=?", cid)[0]
        res.check("строка клиники: когда, почему, файл № 2, кто", (row[0], row[1], row[2], row[3]), (1, REASON, 2, "oleg"))
        res.check("журнал: issue и revoke с причиной",
                  [w for (w,) in _sql(s, "SELECT what FROM audit WHERE clinic_id=? AND what IN ('issue','revoke') "
                                         "ORDER BY id DESC LIMIT 2", cid)], ["revoke", "issue"])
        res.check("письма клинике нет — галочка снята", len([x for x in _letters(s) if x[0] == DIRECTOR]), mails)

        got = _poll(s, tok, 1)
        code, claim = _claim(got.body) if got.status == 200 else ("no", None)
        res.ok("программа забирает файл № 2 и он годен её же проверкой", got.status == 200 and code == "" and
               claim is not None and claim.seq == 2, (got.status, code))
        if claim is not None:
            res.ok("срок файла — через 2 с после выдачи, льготы нет (issued < valid == grace)",
                   claim.valid_until - claim.issued_at == timedelta(seconds=revoke.REVOKE_SECONDS)
                   and claim.grace_until == claim.valid_until)
            res.check("правило программы: через 3 с после выдачи — «только чтение»",
                      ls.by_dates(claim.issued_at + timedelta(seconds=3), claim.valid_until, claim.grace_until),
                      ls.READONLY)
            res.check("план прежний (пробный)", claim.plan, "trial")

        res.check("второй отзыв — «уже отозвана», файла нет", (_msg(_revoke(admin, cid)), _seq(s, cid)),
                  (revoke.ALREADY, 2))
        r = admin.post(f"/admin/clinics/{cid}/issue", kind="trial", valid_until="", grace_days="3", reason="x")
        res.check("«Выдать вручную» поверх отзыва — отказ, файла нет", (_msg(r), _seq(s, cid)), ("revoke_issue", 2))
        r = admin.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="", method="transfer", tier="")
        res.check("нота абонемента из админки — отказ", _msg(r), "revoke_pay")
        r, _ = _link(anon, tok)
        res.ok("«Plătește acum» программы — 403 revoked (программа: REFUSED)",
               r.status == 403 and json.loads(r.body).get("code") == "revoked", (r.status, r.body[:120]))
        if pay_url:
            res.check("старая страница оплаты — «ссылка не действует» (410)",
                      anon.get("/plata/" + pay_url.rsplit("/", 1)[1]).status, 410)
        acc = anon._do("/v1/sms/account", None, {**HDR, "Authorization": f"Bearer {tok}"})
        a = json.loads(acc.body) if acc.status == 200 else {}
        res.ok("SMS: сразу sms_off на сервере, тумблер не тронут, 30 пробных SMS на счёте",
               a.get("blocked") == "sms_off" and a.get("enabled") is True and a.get("balance") == 30, a)
        st, sent = _json(anon, "/v1/sms/send", tok, {"to": "069123456", "text": "Test", "kind": "day_before", "idem": "r1"})
        res.ok("SMS: отправка — отказ sms_off, ничего не списано", st != 200 and sent.get("code") == "sms_off"
               and _sql(s, "SELECT COALESCE(SUM(delta),0) FROM sms_ledger WHERE clinic_id=?", cid)[0][0] == 30,
               (st, sent))

        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: плашка «Лицензия отозвана», причина, «Вернуть», без «Выдать вручную»",
               "Лицензия отозвана" in card and REASON in card and f"/admin/clinics/{cid}/restore" in card
               and f"/admin/clinics/{cid}/issue'" not in card and f"/admin/clinics/{cid}/revoke'" not in card)
        res.ok("список клиник: метка «отозвана» и фильтр", "отозвана" in admin.get("/admin").body
               and cid in admin.get("/admin?state=revoked").body)

        page = c.get("/cont").body
        res.ok("кабинет: «a fost retrasă», без оплаты и «Adaugă clinică»",
               "a fost retrasă" in page and "Treci la abonament" not in page and "/cont/clinica-noua" not in page
               and "action='/cont/nota" not in page)
        res.check("кабинет: нота абонемента — отказ revoked",
                  _msg(c.post("/cont/nota", months="1", tier="plus", terms="1", method="transfer")), "revoked")
        clinics = _sql(s, "SELECT count(*) FROM clinics")[0][0]
        r = c.post("/cont/clinica-noua", **{**BRANCH, "idno": MAIN["idno"]})
        res.ok("кабинет: «Adaugă clinică» — 409, новая клиника не заведена",
               r.status == 409 and "retrasă" in r.body and _sql(s, "SELECT count(*) FROM clinics")[0][0] == clinics,
               r.status)

        r = admin.post(f"/admin/payments/{note[0][0]}/confirm")
        paid = _sql(s, "SELECT status FROM payments WHERE id=?", note[0][0])[0][0]
        res.ok("перевод по старой ноте подтверждён: деньги записаны, срок не продлён, файла нет",
               paid == "paid" and _seq(s, cid) == 2
               and _sql(s, "SELECT count(*) FROM audit WHERE clinic_id=? AND what='payment_revoked'", cid)[0][0] == 1,
               (paid, _seq(s, cid)))
        res.ok("«Ждёт вас»: оплата пришла при отозванной — вернуть деньги или «Вернуть»",
               "пришла при отозванной лицензии" in admin.get(f"/admin/clinics/{cid}").body)

        before = [x for x in _letters(s) if x[0] == DIRECTOR]
        rc, out = _run(s, datetime.now(timezone.utc).date())
        after = [x for x in _letters(s) if x[0] == DIRECTOR]
        res.ok("ежедневная задача: отозванной ни письма о сроке, ни ноты", rc == 0 and len(after) == len(before),
               (rc, [x[1] for x in after[len(before):]], out[-300:]))


def suite_doors(res: Result) -> None:
    """IDNO, ящик и компьютер отозванной клиники остаются заняты: новый пробный ни одной дверью."""
    with Server(env=ENV) as s:
        st, body = _program(s)
        cid = _sql(s, "SELECT id FROM clinics WHERE email=?", PROG["email"])[0][0]
        admin = Client(s.url).login()
        res.check("отозвана", _msg(_revoke(admin, cid)), revoke.REVOKED)
        n = _sql(s, "SELECT count(*) FROM clinics")[0][0]
        st, body = _program(s, {**PROG, "email": "other@example.md"}, {**HDR, "X-DentPilot-Device": "d_000000000002"})
        res.ok("тот же IDNO, другой ящик и ПК — повтор (409), не новый пробный", st == 409 and body.get("code") == "duplicate",
               (st, body))
        st, body = _program(s, {**PROG, "idno": REAL[2]}, {**HDR, "X-DentPilot-Device": "d_000000000003"})
        res.ok("тот же ящик, другой IDNO и ПК — повтор (409)", st == 409 and body.get("code") == "duplicate", (st, body))
        st, body = _program(s, {**PROG, "idno": REAL[3], "email": "third@example.md"})
        res.ok("тот же компьютер, новые IDNO и ящик — 409 device_taken", st == 409 and body.get("code") == "device_taken",
               (st, body))
        r = Client(s.url).post("/proba", **{**PROG, "email": "fourth@example.md"})
        res.ok("/proba: тот же IDNO — без новой клиники", r.status in (200, 303, 409), r.status)
        res.check("клиник не прибавилось", _sql(s, "SELECT count(*) FROM clinics")[0][0], n)


def suite_restore(res: Result) -> None:
    """«Вернуть»: файл № 3 с прежним сроком; срок прошёл — только снять отметку; письмо отзыва галочкой."""
    with Server(env=ENV) as s:
        st, body = _program(s)
        tok = body.get("token", "")
        cid = _sql(s, "SELECT id FROM clinics WHERE email=?", PROG["email"])[0][0]
        was = _sql(s, "SELECT valid_until, grace_until FROM issues WHERE clinic_id=? AND seq=1", cid)[0]
        admin = Client(s.url).login()
        mails = len(_letters(s))
        res.check("отзыв с галочкой письма", _msg(_revoke(admin, cid, send="1")), "revoked_mailed")
        new = _letters(s)[mails:]
        res.ok("письмо клинике: «a fost retrasă», регим чтения назван",
               len(new) == 1 and new[0][0] == PROG["email"] and "retrasă" in new[0][1] and "regim de citire" in new[0][2],
               [x[:2] for x in new])
        r = admin.post(f"/admin/clinics/{cid}/restore", reason="verificat")
        res.check("вернуть — restored", _msg(r), revoke.RESTORED)
        got = _poll(s, tok, 2)
        code, claim = _claim(got.body) if got.status == 200 else ("no", None)
        res.ok("программа забирает файл № 3 с прежним сроком и льготой",
               code == "" and claim is not None and claim.seq == 3
               and (ls.fmt(claim.valid_until), ls.fmt(claim.grace_until)) == tuple(was), (code, was))
        res.check("отметка снята", _sql(s, "SELECT revoked_at, revoked_seq FROM clinics WHERE id=?", cid)[0], (None, None))
        res.check("«Выдать вручную» снова работает", _msg(admin.post(f"/admin/clinics/{cid}/issue", kind="trial",
                                                                    valid_until="", grace_days="3", reason="x")), "issued")
        res.check("вернуть невозвращаемое — revoke_not", _msg(admin.post(f"/admin/clinics/{cid}/restore")), revoke.NOT_REVOKED)
        res.check("журнал: revoke и restore словами",
                  (views.AUDIT_RU["revoke"][1], views.AUDIT_RU["restore"][1]), ("lic", "lic"))
        # срок до отзыва уже прошёл: только снять отметку, файла не выдать (он был бы в прошлом — программа отвергла бы)
        _revoke(admin, cid)
        seq = _seq(s, cid)
        past = (datetime.now(timezone.utc) - timedelta(days=2)).strftime(cdb.TS)
        _sql(s, "UPDATE issues SET valid_until=?, grace_until=? WHERE clinic_id=? AND seq<?", past, past, cid, seq)
        r = admin.post(f"/admin/clinics/{cid}/restore", reason="x")
        res.check("срок прошёл — restored_expired, файла нет, отметка снята",
                  (_msg(r), _seq(s, cid), _sql(s, "SELECT revoked_at FROM clinics WHERE id=?", cid)[0][0]),
                  (revoke.RESTORED_EXPIRED, seq, None))


def suite_schema(res: Result) -> None:
    """Шаг 22 переживает повтор и даёт четыре столбца."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for step in range(1, cdb.SCHEMA_VERSION + 1):
            cdb.apply_step(con, step)
        cdb.apply_step(con, 22)
        cols = {r[1] for r in con.execute("PRAGMA table_info(clinics)")}
        res.ok("шаг 22: revoked_at, revoked_by, revoked_reason, revoked_seq; повтор без ошибки",
               {"revoked_at", "revoked_by", "revoked_reason", "revoked_seq"} <= cols and cdb.SCHEMA_VERSION >= 22)
    finally:
        con.close()


if __name__ == "__main__":
    from harness import run
    sys.exit(run([("idno", suite_idno), ("revoke", suite_revoke), ("doors", suite_doors),
                  ("restore", suite_restore), ("schema", suite_schema)]))
