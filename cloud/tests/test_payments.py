"""Платёж переводом (L8): reference, ожидание, подтверждение, отказ, продление.

Правило продления проверяется чистыми функциями на неудобных датах (31-е,
февраль, високосный год), а живым сервером — то, что нельзя увидеть иначе:
второе подтверждение не продлевает второй раз, ранняя оплата считается от
конца срока, выданный после платежа файл принимает движок.
"""
import email
import email.policy
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from harness import CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path

sys.path.insert(0, str(CLOUD))
from app import payments as pay  # noqa: E402 — чистые функции сервера
from app import config  # noqa: E402 — прайс

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
KEY = __import__("json").loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}


def _t(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _pid(s: Server, reference: str) -> int:
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute("SELECT id FROM payments WHERE reference=?", (reference,)).fetchone()[0]
    finally:
        con.close()


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _clinic(c: Client, **over) -> str:
    f = dict(name="Clinica Plată", idno="1234567890123", contact_name="Ion", email="plata@example.md", phone="")
    f.update(over)
    return cid_from(c.post("/admin/clinics", **f).location)


def _note(c: Client, s: Server, cid: str) -> int:
    """Нота переводом на месяц, без письма → id строки (последняя у клиники)."""
    c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="", method="transfer")
    return _sql(s, "SELECT id FROM payments WHERE clinic_id=? ORDER BY id DESC LIMIT 1", cid)[0][0]


def _until(s: Server, cid: str) -> str:
    return _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid)[0][0]


def suite_anchor_repeat(res: Result) -> None:
    """Живым сервером (02.10): число продления держит якорь; второй перевод по той же
    ноте зачитывается следующим периодом — только с галочкой и только у закрытой ноты."""
    with Server(env=BANK_ENV) as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        r = c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until="2027-01-31", grace_days="14")
        res.ok("срок клиники — 31.01.2027", _until(s, cid) == "2027-01-31T00:00:00Z", r.location)
        got = []
        for _ in range(3):
            c.post(f"/admin/payments/{_note(c, s, cid)}/confirm")
            got.append(_until(s, cid)[:10])
        res.check("три месяца подряд от 31-го: 28.02, 31.03, 30.04 — число не съехало",
                  got, ["2027-02-28", "2027-03-31", "2027-04-30"])
        res.check("якорь подписки — 31", _sql(s, "SELECT anchor_day FROM subscriptions WHERE clinic_id=?", cid)[0][0], 31)
        res.check("оплаченные помечены: переводом",
                  {r_[0] for r_ in _sql(s, "SELECT paid_via FROM payments WHERE clinic_id=?", cid)}, {"transfer"})

        # второй перевод по уже оплаченной ноте
        last = _sql(s, "SELECT id, reference FROM payments WHERE clinic_id=? ORDER BY id DESC LIMIT 1", cid)[0]
        page = c.get(f"/admin/clinics/{cid}").body
        res.ok("у оплаченной ноты — кнопка зачёта с обязательной галочкой",
               f"/admin/payments/{last[0]}/repeat" in page and "name='sure'" in page and "переводом" in page)
        n_issues = _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0]
        r = c.post(f"/admin/payments/{last[0]}/repeat")
        res.check("без галочки — отказ, ничего не продлено", (r.location, _until(s, cid)[:10]),
                  (f"/admin/clinics/{cid}?msg=repeat_unsure", "2027-04-30"))
        r = c.post(f"/admin/payments/{last[0]}/repeat", sure="1")
        res.check("с галочкой — зачтён, письмо ушло", r.location, f"/admin/clinics/{cid}?msg=payment_repeat_mailed")
        new = _sql(s, "SELECT reference, status, paid_via, months, amount FROM payments WHERE clinic_id=? "
                      "ORDER BY id DESC LIMIT 1", cid)[0]
        res.ok("новая строка: новый reference, оплачена переводом, тот же месяц и сумма",
               new[0] != last[1] and new[1:] == ("paid", "transfer", 1, config.PRICE_MONTH), repr(new))
        res.check("срок продлён следующим периодом по якорю", _until(s, cid)[:10], "2027-05-31")
        res.check("выдан ещё один файл", _sql(s, "SELECT count(*) FROM issues WHERE clinic_id=?", cid)[0][0],
                  n_issues + 1)
        res.ok("журнал: payment_repeat называет обе ноты",
               any(last[1] in d[0] and new[0] in d[0]
                   for d in _sql(s, "SELECT detail FROM audit WHERE what='payment_repeat'")))

        # ожидающую закрывает «Подтвердить», отклонённую — можно зачесть
        pend = _note(c, s, cid)
        res.check("ожидающая нота — не зачёт", c.post(f"/admin/payments/{pend}/repeat", sure="1").location,
                  f"/admin/clinics/{cid}?msg=payment_is_pending")
        c.post(f"/admin/payments/{pend}/reject", reason="другая сумма")
        r = c.post(f"/admin/payments/{pend}/repeat", sure="1")
        res.ok("по отклонённой ноте перевод всё же пришёл — зачтён", r.location.endswith("msg=payment_repeat_mailed")
               and _until(s, cid)[:10] == "2027-06-30", f"{r.location} {_until(s, cid)}")
        res.check("чужая строка — 404", c.post("/admin/payments/999/repeat", sure="1").status, 404)


def suite_rules(res: Result) -> None:
    res.check("31.01 + 1 мес = 28.02", pay.add_months(_t("2026-01-31T10:00:00Z"), 1), _t("2026-02-28T10:00:00Z"))
    res.check("31.01.2028 + 1 = 29.02, високосный", pay.add_months(_t("2028-01-31T10:00:00Z"), 1),
              _t("2028-02-29T10:00:00Z"))
    res.check("30.11 + 3 = 28.02", pay.add_months(_t("2026-11-30T00:00:00Z"), 3), _t("2027-02-28T00:00:00Z"))
    res.check("+12 = тот же день через год", pay.add_months(_t("2026-09-24T12:00:00Z"), 12), _t("2027-09-24T12:00:00Z"))
    res.check("сроки — месяц и год, как на сайте", pay.MONTHS, (1, 12))
    res.check("прайс сайта: 499 в месяц, год 5 489 (11 месячных)",
              (config.PRICE_MONTH, pay.amount(1, config.PRICE_MONTH), pay.amount(12, config.PRICE_MONTH)),
              (499, 499, 5489))
    res.check("декабрь + 1 = январь", pay.add_months(_t("2026-12-15T00:00:00Z"), 1), _t("2027-01-15T00:00:00Z"))
    now = _t("2026-09-24T12:00:00Z")
    res.check("ранняя оплата: от конца срока", pay.extend_from(_t("2026-11-01T00:00:00Z"), 1, now),
              _t("2026-12-01T00:00:00Z"))
    res.check("поздняя оплата: от сегодня", pay.extend_from(_t("2026-08-01T00:00:00Z"), 1, now),
              _t("2026-10-24T12:00:00Z"))
    res.check("первая оплата: от сегодня", pay.extend_from(None, 3, now), _t("2026-12-24T12:00:00Z"))
    res.check("срок кончается ровно сейчас: от сейчас", pay.extend_from(now, 1, now), _t("2026-10-24T12:00:00Z"))

    # ⭐ Якорь (02.10, вопрос Олега про «детскую проблему»): помесячное продление держит
    # число первого периода. Без якоря цепочка шла 31.01 → 28.02 → 28.03 → 28.04: клиника
    # теряла дни, а её число менялось навсегда — каждое продление считалось от прошлого конца
    res.check("28.02 + 1 с якорем 31 = 31.03", pay.add_months(_t("2027-02-28T10:00:00Z"), 1, 31),
              _t("2027-03-31T10:00:00Z"))
    res.check("якорь 30 в феврале — 28.02", pay.add_months(_t("2027-01-30T10:00:00Z"), 1, 30),
              _t("2027-02-28T10:00:00Z"))
    v, a, out = _t("2027-01-31T10:00:00Z"), None, []
    for _ in range(4):
        a = pay.anchor_day(v, now, a)
        v = pay.extend_from(v, 1, now, a)
        out.append(v.strftime("%d.%m"))
    res.check("помесячно от 31.01: после февраля число возвращается", out, ["28.02", "31.03", "30.04", "31.05"])
    res.check("без якоря — число самого срока", pay.anchor_day(_t("2027-02-28T10:00:00Z"), now, None), 28)
    res.check("срок сдвинут руками на 15-е: якорь 31 сброшен на 15",
              pay.anchor_day(_t("2027-11-15T10:00:00Z"), now, 31), 15)
    res.check("срок кончился: отсчёт с сегодняшнего числа", pay.anchor_day(_t("2026-08-31T10:00:00Z"), now, 31), 24)
    res.check("29.02 високосного года при якоре 31 стоит на якоре",
              pay.anchor_day(_t("2028-02-29T10:00:00Z"), now, 31), 31)
    res.check("год с якорем: 28.02.2027 + 12 при якоре 29 = 29.02.2028",
              pay.extend_from(_t("2027-02-28T10:00:00Z"), 12, now, 29), _t("2028-02-29T10:00:00Z"))


def suite_flow(res: Result) -> None:
    with Server(env=BANK_ENV) as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        year = datetime.now(timezone.utc).year
        ref1 = f"DP-{year}-000001"

        r = c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="1")
        res.check("платёж создан, письмо с реквизитами ушло", r.location,
                  f"/admin/clinics/{cid}?msg=payment_created_mailed")
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: reference, сумма по тарифу, ожидает",
               ref1 in card and f"{config.PRICE_MONTH} MDL" in card and "ожидает" in card, "нет в карточке")
        res.ok("шапка считает ожидающие", "Платежи (1)" in card)
        res.ok("страница ожидающих показывает платёж и клинику",
               ref1 in c.get("/admin/payments").body and "Clinica Plată" in c.get("/admin/payments").body)
        eml = sorted(s.outbox.glob("*.eml"))
        res.check("письмо с реквизитами — одно", len(eml), 1)
        msg = email.message_from_bytes(eml[0].read_bytes(), policy=email.policy.default)
        body = msg.get_body(preferencelist=("plain",)).get_content()
        res.ok("письмо: reference в теме и в назначении, IBAN, сумма",
               ref1 in msg["Subject"] and f"Destinația plății: {ref1}" in body
               and "MD00TEST0000000000000001" in body and f"{config.PRICE_MONTH} MDL" in body, body[:300])

        pid = _pid(s, ref1)
        r = c.post(f"/admin/payments/{pid}/confirm")
        res.check("подтверждение: продлено, файл выдан и отправлен", r.location,
                  f"/admin/clinics/{cid}?msg=payment_confirmed_mailed")
        code, claim = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/1/license.json").body, KEYS)
        res.ok("файл после платежа принимает движок: standard, seq 1",
               code == "" and claim.plan == "standard" and claim.seq == 1, f"{code} {claim!r}")
        res.ok("первая оплата: месяц от сегодня",
               abs((claim.valid_until - pay.add_months(claim.issued_at, 1)).total_seconds()) <= 2,
               f"{claim.issued_at} -> {claim.valid_until}")
        res.check("льгота 14 дней", claim.grace_until - claim.valid_until, timedelta(days=14))
        res.ok("основание файла — reference платежа", ref1 in c.get(f"/admin/clinics/{cid}").body)
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: оплачен, действует", "оплачен" in card and "действует" in card)
        res.ok("ожидающих больше нет", "Ожидающих платежей нет" in c.get("/admin/payments").body)
        res.check("письмо с файлом ушло — писем два", len(list(s.outbox.glob("*.eml"))), 2)

        r = c.post(f"/admin/payments/{pid}/confirm")
        res.check("второе подтверждение: отказ", r.location, f"/admin/clinics/{cid}?msg=payment_not_pending")
        res.check("выдач по-прежнему одна", _sql(s, "SELECT count(*) FROM issues")[0][0], 1)
        res.check("срок не сдвинут", _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid)[0][0],
                  claim.valid_until.strftime("%Y-%m-%dT%H:%M:%SZ"))

        # ранняя оплата: от конца действующего срока, не от сегодня
        r = c.post(f"/admin/clinics/{cid}/payments", months="12", amount="1000", send="")
        ref2 = f"DP-{year}-000002"
        res.check("второй платёж: следующий номер, без письма", r.location, f"/admin/clinics/{cid}?msg=payment_created")
        res.ok("сумма своя", "1000 MDL" in c.get(f"/admin/clinics/{cid}").body)
        r = c.post(f"/admin/payments/{_pid(s, ref2)}/confirm")
        res.ok("ранняя оплата подтверждена", "payment_confirmed" in r.location, r.location)
        code, claim2 = rv.open_envelope(c.get(f"/admin/clinics/{cid}/issues/2/license.json").body, KEYS)
        res.check("ранняя оплата не крадёт дни: год от прежнего конца срока",
                  claim2.valid_until, pay.add_months(claim.valid_until, 12))
        res.check("файл seq 2", claim2.seq, 2)

        # отказ
        r = c.post(f"/admin/clinics/{cid}/payments", months="12", amount="", send="")
        ref3 = f"DP-{year}-000003"
        pid3 = _pid(s, ref3)
        res.check("год по тарифу — 11 месячных, как на сайте",
                  _sql(s, "SELECT months, amount FROM payments WHERE id=?", pid3)[0],
                  (12, 11 * config.PRICE_MONTH))
        r = c.post(f"/admin/payments/{pid3}/reject", reason="поступления нет")
        res.check("отказ", r.location, f"/admin/clinics/{cid}?msg=payment_rejected")
        res.check("в базе: rejected", _sql(s, "SELECT status FROM payments WHERE id=?", pid3)[0][0], "rejected")
        r = c.post(f"/admin/payments/{pid3}/confirm")
        res.check("подтвердить отклонённый нельзя", r.location, f"/admin/clinics/{cid}?msg=payment_not_pending")
        res.check("выдач по-прежнему две", _sql(s, "SELECT count(*) FROM issues")[0][0], 2)
        res.ok("причина в журнале", any("поступления нет" in d[0] for d in
                                        _sql(s, "SELECT detail FROM audit WHERE what='payment_rejected'")))

        # со страницы ожидающих — обратно на неё
        c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="")
        pid4 = _pid(s, f"DP-{year}-000004")
        r = c.post(f"/admin/payments/{pid4}/confirm", headers={"Referer": s.url + "/admin/payments"})
        res.ok("подтверждение со страницы ожидающих ведёт обратно туда",
               r.location.startswith("/admin/payments?msg=payment_confirmed"), r.location)

        # вторая ожидающая нота не выставляется (03.10)
        c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="")
        ref5 = f"DP-{year}-000005"
        pid5 = _pid(s, ref5)
        n_pay = _sql(s, "SELECT count(*) FROM payments")[0][0]
        n_eml = len(list(s.outbox.glob("*.eml")))
        r = c.post(f"/admin/clinics/{cid}/payments", months="12", amount="", send="1")
        res.check("нота при ожидающей: вторая не выставлена, письмо с прежней ушло — note_pending_mailed",
                  r.location, f"/admin/clinics/{cid}?msg=note_pending_mailed")
        res.check("платежей не прибавилось", _sql(s, "SELECT count(*) FROM payments")[0][0], n_pay)
        eml = sorted(s.outbox.glob("*.eml"))
        res.ok("письмо одно и с прежним reference",
               len(eml) == n_eml + 1 and ref5 in email.message_from_bytes(eml[-1].read_bytes(), policy=email.policy.default)["Subject"])
        res.check("без галочки — note_pending, письма нет",
                  (c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="").location,
                   len(list(s.outbox.glob("*.eml")))),
                  (f"/admin/clinics/{cid}?msg=note_pending", n_eml + 1))
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("у ожидающей ноты кнопка «Письмо»", f"/admin/payments/{pid5}/mail" in card and ">Письмо<" in card)
        res.check("«Письмо» — письмо ещё раз", c.post(f"/admin/payments/{pid5}/mail").location,
                  f"/admin/clinics/{cid}?msg=payment_mailed")
        res.check("писем стало на одно больше", len(list(s.outbox.glob("*.eml"))), n_eml + 2)
        c.post(f"/admin/payments/{pid5}/reject", reason="проверка")
        res.check("«Письмо» для отклонённой — not_pending", c.post(f"/admin/payments/{pid5}/mail").location,
                  f"/admin/clinics/{cid}?msg=payment_not_pending")

        # проверки формы
        res.check("2 месяца — не из ряда", c.post(f"/admin/clinics/{cid}/payments", months="2").location,
                  f"/admin/clinics/{cid}?msg=bad_months")
        res.check("3 месяца — больше не из ряда (26.09: только месяц и год)",
                  c.post(f"/admin/clinics/{cid}/payments", months="3").location,
                  f"/admin/clinics/{cid}?msg=bad_months")
        res.check("сумма буквами", c.post(f"/admin/clinics/{cid}/payments", months="1", amount="abc").location,
                  f"/admin/clinics/{cid}?msg=bad_amount")
        res.check("сумма ноль", c.post(f"/admin/clinics/{cid}/payments", months="1", amount="0").location,
                  f"/admin/clinics/{cid}?msg=bad_amount")
        res.check("чужой платёж: 404", c.post("/admin/payments/999/confirm").status, 404)
        kinds = [k[0] for k in _sql(s, "SELECT what FROM audit WHERE clinic_id=? ORDER BY id", cid)]
        res.check("журнал: каждое действие своей строкой",
                  kinds[:9], ["clinic_new", "payment_new", "mail", "payment_paid", "issue", "mail",
                              "payment_new", "payment_paid", "issue"])

    with Server() as s:
        res.check("ожидающие без входа: на вход", Client(s.url).get("/admin/payments").status, 303)
        c = Client(s.url).login()
        cid = _clinic(c)
        r = c.post(f"/admin/clinics/{cid}/payments", months="1", amount="", send="1")
        res.check("без реквизитов: платёж создан, письмо отказано словами",
                  r.location, f"/admin/clinics/{cid}?msg=no_bank")
        res.check("платёж при этом в ожидании", _sql(s, "SELECT status FROM payments")[0][0], "pending")
