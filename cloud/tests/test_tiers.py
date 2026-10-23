"""Варианты абонемента DentPilot Basic / Plus (23.10.2026, tiers.py).

Правило без сервера: вариант, цена месяца (своя у подписки — прайс у другого
варианта), модуль SMS после оплаты (Plus — сразу, Basic — до конца текущего
периода), тексты писем и кодов. Через живой сервер: выбор на /plata с галочкой
условий, замена ноты вместо второго долга, confirm ставит вариант, цену и модуль,
коды sms_basic / sms_off, ручная смена варианта, нота за 14 дней в текущем
варианте, страница возврата maib с № заказа, вариант без цены, миграция данных до
шага 15. Цены прогона — заметно не настоящие (harness: DP_PRICE_*).
"""
import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from harness import CLOUD, ROOT, Client, Result, Server, cid_from

sys.path.insert(0, str(CLOUD))
from app import config, db, mail, receipts, sms, tiers, views  # noqa: E402
from app import payments as pay  # noqa: E402
from test_account import BANK_ENV, _letters, _sql  # noqa: E402
from test_jobs import _run  # noqa: E402
from test_paylink import HDR, _link, _token  # noqa: E402

UTC = timezone.utc
B, P = tiers.BASIC, tiers.PLUS
SMS_ENV = {"DP_SMSMD_TOKEN": "test-token", "DP_SMSMD_BASE_URL": "http://127.0.0.1:9", "DP_SMS_OFFERED": "1",
           "DP_SMS_PACKS": "100:50"}


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _sub(plan: str = "standard", tier: str = P, price: int = 0, valid: datetime | None = None,
         sms_until: datetime | None = None) -> dict:
    return {"plan": plan, "tier": tier, "price": price, "grace_days": 14,
            "valid_until": valid.strftime(db.TS) if valid else None,
            "sms_until": sms_until.strftime(db.TS) if sms_until else None}


def _note(tier: str | None = B, months: int = 1, amount: int = 0) -> dict:
    return {"tier": tier, "months": months, "amount": amount or tiers.list_price(tier or P)}


def suite_rules(res: Result) -> None:
    now = _now()
    pb, pp = tiers.list_price(B), tiers.list_price(P)
    res.ok("прайс прогона: оба варианта продаются, Basic дешевле", 0 < pb < pp, str(config.PRICES))
    res.check("вариант: нет подписки и пробный — Plus (условия § 3), иначе — свой",
              [tiers.current(None), tiers.current(_sub("trial", B)), tiers.current(_sub(tier=B)),
               tiers.current(_sub(tier="gold"))], [P, P, B, P])
    res.check("цена: свой вариант — своя цена подписки, другой и пробный — прайс",
              [tiers.price(_sub(tier=P, price=444), P), tiers.price(_sub(tier=P, price=444), B),
               tiers.price(_sub("trial", P, 444), P), tiers.price(None, B)], [444, pb, pp, pb])
    res.check("сумма ноты: год — 11 месячных своей цены", pay.amount_for(_sub(tier=P, price=444), P, 12), 11 * 444)
    res.check("выбор по умолчанию: названный, иначе текущий", [tiers.pick(_sub("trial", B)), tiers.pick(_sub(tier=B)),
                                                                tiers.pick(_sub(tier=B), P), tiers.pick(None, "x")],
              [P, B, P, P])
    res.check("модуль SMS: Plus и пробный — да; Basic — пока не прошёл sms_until",
              [tiers.module_on(_sub(tier=P), now), tiers.module_on(_sub("trial", B), now),
               tiers.module_on(_sub(tier=B), now), tiers.module_on(_sub(tier=B, sms_until=now + timedelta(days=3)), now),
               tiers.module_on(_sub(tier=B, sms_until=now - timedelta(seconds=1)), now)],
              [True, True, False, True, False])
    # tier_after — что confirm делает с подпиской (§ 4.2)
    trial_end = now + timedelta(days=20)
    t, price, until, why = pay.tier_after(_sub("trial", P, pp, trial_end), _note(B), now)
    res.ok("пробный → Basic: модуль до конца пробного, цена — прайс Basic, строка журнала",
           (t, price, until) == (B, pb, trial_end.strftime(db.TS)) and "пробный → DentPilot Basic" in why
           and trial_end.strftime("%Y-%m-%d") in why, repr((t, price, until, why)))
    end = now + timedelta(days=5)
    res.check("Plus → Basic с действующим сроком: модуль до конца оплаченного Plus",
              pay.tier_after(_sub(tier=P, price=444, valid=end), _note(B), now)[:3], (B, pb, end.strftime(db.TS)))
    t, _, until, why = pay.tier_after(_sub(tier=P, valid=now - timedelta(days=2)), _note(B), now)
    res.ok("Plus → Basic после конца срока (льгота): модуль гаснет сразу",
           (t, until) == (B, None) and "выключен сразу" in why, repr((t, until, why)))
    keep = now + timedelta(days=9)
    res.check("Basic → Basic: прежний конец модуля, своя цена",
              pay.tier_after(_sub(tier=B, price=300, valid=end, sms_until=keep), _note(B, amount=300), now)[:3],
              (B, 300, keep.strftime(db.TS)))
    t, price, until, why = pay.tier_after(_sub(tier=B, price=300, valid=end), _note(P), now)
    res.ok("Basic → Plus: модуль сразу, цена — прайс Plus",
           (t, price, until) == (P, pp, None) and "модуль SMS сразу" in why, repr((t, price, until, why)))
    res.check("Plus → Plus: цена существующей подписки не меняется",
              pay.tier_after(_sub(tier=P, price=444, valid=end), _note(P, amount=444), now), (P, 444, None, ""))
    res.check("нота без варианта (до шага 15) — Plus", pay.tier_after(_sub(tier=P, price=444), _note(None), now)[0], P)
    saved = dict(config.PRICES)
    try:
        config.PRICES[B] = 0
        res.check("вариант сняли с продажи после ноты — цена из суммы ноты",
                  pay.tier_after(_sub(tier=P, valid=end), _note(B, 12, 11 * 321), now)[1], 321)
        res.check("вариант без цены не предлагается", tiers.offered(None), [P])
    finally:
        config.PRICES.update(saved)
    # тексты
    _, body = mail.payment_letter("Clinica T", "DP-2026-000001", pb, 1, pay_url="https://maib.example/p/1", tier=B)
    res.ok("нота письмом: вариант словами условий и как сменить его до оплаты",
           "DentPilot Basic (fără modulul SMS)" in body and "Plătește acum" in body and mail.CONT_URL in body, body)
    _, body = mail.reminder_letter("invoice", "Clinica T", "standard", end, end + timedelta(days=14), 14,
                                   {"reference": "DP-2026-000002", "amount": pb, "months": 1, "url": None, "tier": B})
    res.ok("нота за 14 дней: «în varianta în curs» (§ 4.5) и смена на странице оплаты",
           "în varianta în curs, DentPilot Basic (fără modulul SMS)" in body and "se înlocuiește" in body, body)
    trial_how = mail.how_to_pay(None)
    res.ok("пробной: оба варианта с ценой месяца из окружения",
           f"DentPilot Basic, fără modulul SMS — {pb} MDL pe lună" in trial_how
           and f"DentPilot Plus, cu modulul SMS — {pp} MDL pe lună" in trial_how, trial_how)
    res.ok("коды: sms_basic — 423 и путь к Plus; sms_off — нейтрально, без «la cererea clinicii»",
           sms.CODES["sms_basic"][0] == 423 and "DentPilot Plus" in sms.CODES["sms_basic"][1]
           and sms.CODES["sms_off"][0] == 423 and "cererea" not in sms.CODES["sms_off"][1])
    res.ok("ни один ответ программе не называет услугу «Pachetul SMS»",
           not [c for c, (_, t) in sms.CODES.items() if "Pachetul SMS" in t])
    res.check("cont de plată: предмет с вариантом",
              receipts.item_for(None, {"kind": "license", "months": 12, "tier": B})["title"],
              "Abonament DentPilot Basic (fără modulul SMS)")
    # «DentPilot™ Basic» в условиях = «DentPilot Basic» сервера: знак ставит сайт, имя варианта то же
    terms = " ".join((ROOT / "docs" / "site" / "termeni.html").read_text(encoding="utf-8")
                     .replace("™", "").split())
    res.ok("условия называют варианты так же, как сервер, и обещают то, что делает confirm",
           all(tiers.NAME[t] in terms for t in tiers.TIERS)
           and "modulul SMS rămâne pornit până la sfârșitul perioadei în curs" in terms
           and "în varianta în curs" in terms and "Varianta o alege clinica la fiecare plată" in terms)
    # срок перевода — словами § 4.6: его подтверждает Олег, когда деньги дошли; своего срока нет
    when = "după ce banii ajung în contul furnizorului"
    res.ok("шаги оплаты: перевод — словами условий § 4.6, без «în aceeași zi lucrătoare»",
           when in terms and all(when in views._steps(on) and "aceeași zi" not in views._steps(on)
                                 for on in (True, False)), views._steps(True))


def _account(anon: Client, tok: str) -> dict:
    r = anon.get("/v1/sms/account", headers={**HDR, "Authorization": f"Bearer {tok}"})
    return json.loads(r.body) if r.status == 200 else {"status": r.status}


def _json(anon: Client, path: str, tok: str, body: dict):
    req = json.dumps(body).encode()
    r = anon._do(path, req, {**HDR, "Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return r.status, (json.loads(r.body) if r.body.startswith("{") else {})


def _subrow(s: Server, cid: str):
    return _sql(s, "SELECT plan, tier, price, sms_until, valid_until FROM subscriptions WHERE clinic_id=?", cid)[0]


def suite_flow(res: Result) -> None:
    pb, pp = tiers.list_price(B), tiers.list_price(P)
    with Server(env={**BANK_ENV, **SMS_ENV}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Variante", idno="3333333333333",
                                  email="variante@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        tok = _token(s, cid)
        anon = Client(s.url)
        path = "/plata/" + _link(anon, tok)[1].rsplit("/", 1)[1]
        trial_end = _subrow(s, cid)[4]
        # выбор Basic в пробном
        n = len(_letters(s))
        r = anon.post(path, tier="basic", months="1", method="transfer", terms="1")
        res.check("пробный выбирает Basic — нота создана", r.location, f"{path}?msg=note_created")
        p1 = _sql(s, "SELECT reference, tier, amount, months, terms_at, status FROM payments WHERE clinic_id=?", cid)
        res.ok("нота: вариант Basic, сумма по прайсу Basic, отметка условий",
               len(p1) == 1 and p1[0][1:4] == ("basic", pb, 1) and p1[0][4] and p1[0][5] == "pending", repr(p1))
        res.ok("журнал ноты: вариант и «условия приняты»",
               any("DentPilot Basic" in d and "условия приняты" in d for (d,) in
                   _sql(s, "SELECT detail FROM audit WHERE what='payment_new' AND clinic_id=?", cid)))
        res.ok("письмо с нотой — с вариантом", len(_letters(s)) == n + 1
               and "DentPilot Basic (fără modulul SMS)" in _letters(s)[-1][2])
        # другой выбор — замена, а не второй долг
        r = anon.post(path, tier="plus", months="12", method="transfer", terms="1")
        res.check("другой вариант и срок — нота заменена", r.location, f"{path}?msg=note_replaced")
        rows = _sql(s, "SELECT reference, tier, months, amount, status FROM payments WHERE clinic_id=? ORDER BY id", cid)
        res.ok("старая отклонена, новая Plus на год по прайсу; ожидающая одна",
               len(rows) == 2 and rows[0][4] == "rejected" and rows[1][1:] == ("plus", 12, 11 * pp, "pending")
               and sum(1 for r_ in rows if r_[4] == "pending") == 1, repr(rows))
        res.ok("журнал: причина замены и «взамен»",
               any("заменена" in d for (d,) in _sql(s, "SELECT detail FROM audit WHERE what='payment_rejected'"))
               and any(f"взамен {rows[0][0]}" in d for (d,) in _sql(s, "SELECT detail FROM audit WHERE what='payment_new'")))
        res.ok("письмо с новой нотой ушло", len(_letters(s)) == n + 2 and rows[1][0] in _letters(s)[-1][2])
        page = anon.get(path).body
        res.ok("страница: нота Plus на 12 luni, замена за «Altă variantă»",
               rows[1][0] in page and "<b>DentPilot Plus</b>, 12 luni" in page and "Înlocuiește nota de plată" in page)
        anon.post(path, tier="basic", months="1", method="transfer", terms="1")
        ref = _sql(s, "SELECT reference FROM payments WHERE clinic_id=? AND status='pending'", cid)[0][0]
        pid = _sql(s, "SELECT id FROM payments WHERE reference=?", ref)[0][0]
        acc = _account(anon, tok)
        res.ok("пробный: модуль работает, 30 SMS бонуса", acc.get("blocked") == "" and acc.get("balance") == 30, repr(acc))
        n = len(_letters(s))
        admin.post(f"/admin/payments/{pid}/confirm")
        plan, tier, price, until, _ = _subrow(s, cid)
        res.check("оплачен Basic из пробного: вариант, цена Basic, модуль до конца пробного",
                  (plan, tier, price, until), ("standard", "basic", pb, trial_end))
        res.ok("журнал оплаты: вариант и переход с датой модуля",
               any("DentPilot Basic" in d and f"модуль SMS до {trial_end[:10]}" in d for (d,) in
                   _sql(s, "SELECT detail FROM audit WHERE what='payment_paid' AND clinic_id=?", cid)))
        body = _letters(s)[-1][2] if len(_letters(s)) > n else ""
        res.ok("письмо после оплаты — поля maib: № заказа, что и период, сумма, валюта, дата, поставщик и сайт",
               f"Comanda nr.: {ref}" in body and "Abonament DentPilot Basic (fără modulul SMS), 1 lună, perioada" in body
               and f"Suma: {receipts.money(pb)} MDL" in body and "Data plății:" in body
               and "Furnizor: Oleg Bacalu, antreprenor independent" in body and "dentpilot.md" in body, body[:1500])
        res.ok("письмо о лицензии: вариант и до какого дня работает модуль SMS",
               "Abonamentul DentPilot Basic pentru Clinica Variante" in body
               and f"Modulul SMS rămâne pornit până la {trial_end[:10]}" in body, body[:600])
        acc = _account(anon, tok)
        res.ok("Basic до конца пробного: модуль ещё работает", acc.get("blocked") == "", repr(acc))
        _sql(s, "UPDATE subscriptions SET sms_until='2020-01-01T00:00:00Z' WHERE clinic_id=?", cid)
        acc = _account(anon, tok)
        res.ok("конец пробного прошёл: blocked = sms_basic, экран виден, остаток цел (§ 16.10)",
               acc.get("blocked") == "sms_basic" and acc.get("offered") is True and acc.get("balance") == 30, repr(acc))
        st, data = _json(anon, "/v1/sms/send", tok, {"to": "069123456", "text": "Test", "kind": "test", "idem": "t:1"})
        res.ok("отправка на Basic — 423 sms_basic, текст ведёт к Plus",
               st == 423 and data.get("code") == "sms_basic" and "DentPilot Plus" in data.get("text", ""), repr((st, data)))
        st, data = _json(anon, "/v1/sms/order", tok, {"pack": 100})
        res.ok("пакет SMS на Basic не продаётся — sms_basic, ноты нет",
               st == 423 and data.get("code") == "sms_basic"
               and _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=? AND kind='sms'", cid)[0][0] == 0, repr((st, data)))
        admin.post(f"/admin/clinics/{cid}/sms", action="off")
        res.check("ручной тумблер говорится раньше варианта — sms_off", _account(anon, tok).get("blocked"), "sms_off")
        admin.post(f"/admin/clinics/{cid}/sms", action="on")
        # Plus — сразу
        anon.post(path, tier="plus", months="1", method="transfer", terms="1")
        pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending'", cid)[0][0]
        admin.post(f"/admin/payments/{pid}/confirm")
        res.check("Basic → Plus: вариант, прайс Plus, модуль без конца", _subrow(s, cid)[1:4], ("plus", pp, None))
        res.check("модуль включён сразу после оплаты Plus", _account(anon, tok).get("blocked"), "")
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: плитка варианта, выбор варианта в ноте, «Вариант вручную»",
               "Вариант" in card and "name='tier'" in card and "Вариант вручную" in card
               and "standard · DentPilot Plus" in card, card[-3000:])
        # ручная смена — исключение
        r = admin.post(f"/admin/clinics/{cid}/tier", tier="basic", price="")
        res.check("вручную на Basic — tier_set", r.location, f"/admin/clinics/{cid}?msg=tier_set")
        res.check("Basic вручную: прайс Basic, модуль гаснет сразу", (_subrow(s, cid)[1:4], _account(anon, tok).get("blocked")),
                  (("basic", pb, None), "sms_basic"))
        res.ok("журнал: tier_set с прежним и новым вариантом",
               any("DentPilot Plus → DentPilot Basic" in d for (d,) in
                   _sql(s, "SELECT detail FROM audit WHERE what='tier_set' AND clinic_id=?", cid)))
        admin.post(f"/admin/clinics/{cid}/tier", tier="plus", price="123")
        res.check("Plus вручную со своей ценой", _subrow(s, cid)[1:3], ("plus", 123))
        res.check("кривая цена — tier_price", admin.post(f"/admin/clinics/{cid}/tier", tier="plus", price="12a").location,
                  f"/admin/clinics/{cid}?msg=tier_price")
        res.check("продление в своём варианте — по своей цене",
                  views._mdl(123) + " MDL <small>/ lună</small>" in anon.get(path).body, True)
        cid2 = cid_from(admin.post("/admin/clinics", name="Clinica Proba", idno="4444444444444").location)
        admin.post(f"/admin/clinics/{cid2}/issue", kind="trial")
        res.check("пробный вручную не меняется — tier_trial",
                  admin.post(f"/admin/clinics/{cid2}/tier", tier="basic").location, f"/admin/clinics/{cid2}?msg=tier_trial")
        res.check("и у оплатившей клиники без галочки нота не создаётся — need_terms",
                  anon.post(path, tier="plus", months="1", method="transfer").location, f"{path}?msg=need_terms")
        # страница возврата maib: по payId, не по reference
        ref = _sql(s, "SELECT reference FROM payments WHERE id=?", pid)[0][0]
        _sql(s, "UPDATE payments SET provider_id='pay-ok-test-uuid' WHERE id=?", pid)
        ok = Client(s.url).get(f"/pay/ok?payId=pay-ok-test-uuid&orderId={ref}")
        res.ok("/pay/ok: № заказа, что оплачено, сумма, «plătită» только раз сервер закрыл ноту, поставщик",
               ok.status == 200 and ref in ok.body and "Abonament DentPilot Plus, 1 lună" in ok.body
               and f"{views._mdl(pp)} MDL" in ok.body and "plătită" in ok.body and "Oleg Bacalu" in ok.body
               and "Mulțumim" in ok.body, ok.body[-1500:])
        res.ok("/pay/ok по одному reference (порядковому) ничего не показывает",
               ref not in Client(s.url).get(f"/pay/ok?orderId={ref}").body)
        res.ok("/pay/ok с неизвестным payId — без подробностей",
               ref not in Client(s.url).get(f"/pay/ok?payId=nu-exista&orderId={ref}").body)
        anon.post(path, tier="plus", months="12", method="transfer", terms="1")
        pend = _sql(s, "SELECT id, reference FROM payments WHERE clinic_id=? AND status='pending'", cid)[0]
        _sql(s, "UPDATE payments SET provider_id='pay-wait-uuid' WHERE id=?", pend[0])
        ok = Client(s.url).get(f"/pay/ok?payId=pay-wait-uuid&orderId={pend[1]}")
        res.ok("/pay/ok до ответа maib — «în curs de confirmare», не «plătită»",
               pend[1] in ok.body and "în curs de confirmare" in ok.body and "plătită" not in ok.body, ok.body[-1200:])
        fail = Client(s.url).get(f"/pay/fail?payId=pay-wait-uuid&orderId={pend[1]}")
        res.ok("/pay/fail: № заказа и как ещё оплатить", "nu a reușit" in fail.body and pend[1] in fail.body
               and "transfer bancar" in fail.body)


def suite_not_sold(res: Result) -> None:
    with Server(env={**BANK_ENV, "DP_PRICE_BASIC": ""}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Doar Plus", idno="5555555555555",
                                  email="plus@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        anon = Client(s.url)
        path = "/plata/" + _link(anon, _token(s, cid))[1].rsplit("/", 1)[1]
        page = anon.get(path).body
        res.ok("Basic без цены — на странице только Plus", "value='plus'" in page and "value='basic'" not in page)
        res.check("Basic без цены не оплатить — tier_not_sold",
                  anon.post(path, tier="basic", months="1", method="transfer", terms="1").location,
                  f"{path}?msg=tier_not_sold")
        res.check("ноты нет", _sql(s, "SELECT count(*) FROM payments")[0][0], 0)
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("админка: Basic в ноте недоступен и назван «не продаётся»", "не продаётся" in card and "disabled" in card)
        out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                             capture_output=True, text=True, encoding="utf-8").stdout
        res.ok("tools check называет пустой прайс", "DP_PRICE_BASIC пуст" in out and "DentPilot Plus:" in out, out[-800:])


def suite_jobs(res: Result) -> None:
    with Server(env={**BANK_ENV}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Nota", idno="6666666666666",
                                  email="nota@example.md").location)
        today = datetime.now(UTC).date()
        admin.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{today + timedelta(days=10):%Y-%m-%d}",
                   grace_days="14")
        admin.post(f"/admin/clinics/{cid}/tier", tier="basic", price="")
        rc, out = _run(s, today)
        rows = _sql(s, "SELECT tier, amount, months, status FROM payments WHERE clinic_id=?", cid)
        res.check("нота за 14 дней — в текущем варианте и по его цене", rows,
                  [("basic", tiers.list_price(B), 1, "pending")])
        body = _letters(s)[-1][2]
        res.ok("письмо: «în varianta în curs» и как сменить вариант до оплаты",
               "în varianta în curs, DentPilot Basic (fără modulul SMS)" in body and "Plătește acum" in body
               and mail.CONT_URL in body, body[:1200])


def suite_migration(res: Result) -> None:
    """База до шага 15: подписки и ноты — Plus, цена подписки не меняется."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_tiers_"))
    path = tmp / "cloud.db"
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for step in range(1, 15):
        for q in db.MIGRATIONS[step]:
            con.execute(q)
    con.execute("INSERT INTO schema_meta VALUES('version', '14')")
    now = _now()
    tok = "t" * 43
    con.execute("INSERT INTO clinics(id, name, idno, email, created_at, renew_token) VALUES(?,?,?,?,?,?)",
                ("c_old", "Clinica Veche", "7777777777777", "veche@example.md", now.strftime(db.TS), tok))
    con.execute("INSERT INTO subscriptions(clinic_id, plan, price, valid_until, updated_at) VALUES(?,?,?,?,?)",
                ("c_old", "standard", 444, (now + timedelta(days=40)).strftime(db.TS), now.strftime(db.TS)))
    con.execute("INSERT INTO payments(clinic_id, amount, method, status, reference, months, created_at, paid_at) "
                "VALUES(?,?,?,?,?,?,?,?)", ("c_old", 444, "transfer", "paid", "DP-2026-000001", 1,
                                            now.strftime(db.TS), now.strftime(db.TS)))
    con.close()
    try:
        _migrated(res, path, tok)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _migrated(res: Result, path: pathlib.Path, tok: str) -> None:
    def _sql(_s, sql: str, *args):     # база — своя, не папки харнесса (test_account._sql читает ту)
        con = sqlite3.connect(path)
        try:
            rows = con.execute(sql, args).fetchall()
            con.commit()
            return rows
        finally:
            con.close()
    with Server(env={**BANK_ENV, "DP_CLOUD_DB": str(path)}) as s:
        res.check("шаг 15: подписка — Plus, цена прежняя, модуль без конца",
                  _sql(s, "SELECT tier, price, sms_until FROM subscriptions"), [("plus", 444, None)])
        res.check("шаг 15: нота абонемента — Plus", _sql(s, "SELECT tier, terms_at FROM payments"), [("plus", None)])
        res.check("версия схемы", _sql(s, "SELECT value FROM schema_meta WHERE key='version'"), [(str(db.SCHEMA_VERSION),)])
        anon = Client(s.url)
        url = "/plata/" + _link(anon, tok)[1].rsplit("/", 1)[1]
        page = anon.get(url).body
        res.ok("страница: Plus по своей цене подписки, Basic — по прайсу",
               f"{views._mdl(444)} MDL <small>/ lună</small>" in page
               and f"{views._mdl(tiers.list_price(B))} MDL <small>/ lună</small>" in page
               and "value='plus' checked" in page, page[-2500:])
        anon.post(url, tier="plus", months="12", method="transfer", terms="1")
        res.check("продление Plus на год — 11 × своя цена",
                  _sql(s, "SELECT tier, amount FROM payments WHERE status='pending'"), [("plus", 11 * 444)])


def suite_card(res: Result) -> None:
    """Карта по клику (23.10): ссылка maib живёт 10 минут (maib.PAY_TTL) — письмо несёт нашу
    страницу, ссылка рождается кнопкой за галочкой; у ноты может быть несколько попыток, и
    оплата во вкладке со старой ссылкой узнаётся; задача не пишет card_failed каждый день."""
    from test_maib import CALLBACK, FakeMaib, _payment
    fake = FakeMaib()
    try:
        with Server(env={**BANK_ENV, **SMS_ENV, **fake.env}) as s:
            admin = Client(s.url).login()
            cid = cid_from(admin.post("/admin/clinics", name="Clinica Card Clic", idno="8888888888888",
                                      email="clic@example.md").location)
            admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
            anon = Client(s.url)
            path = "/plata/" + _link(anon, _token(s, cid))[1].rsplit("/", 1)[1]
            r = anon.post(path, tier="basic", months="1", method="transfer", terms="1")
            p = _payment(s, cid)
            body = _letters(s)[-1][2]
            res.ok("нота переводом: ссылки maib нет ни в строке, ни в письме; письмо ведёт на страницу оплаты",
                   r.location.endswith("msg=note_created") and not p["provider_id"] and fake.calls["pay"] == 0
                   and "/plata/" in body and "maib.ecommerce.md" not in body and mail.CARD_NOTE in body, body[:800])
            r = anon.post(path, tier="basic", months="1", method="card", terms="1")
            p1 = _payment(s, cid)
            res.ok("клик «Plătește cu cardul»: ссылка рождается сейчас, браузер на неё",
                   r.status == 303 and r.location == p1["pay_url"] and fake.calls["pay"] == 1, r.location)
            r = anon.post(path, tier="basic", months="1", method="card", terms="1")
            res.ok("второй клик, пока ссылка молода и maib ждёт: та же ссылка, у maib второго платежа нет",
                   r.location == p1["pay_url"] and fake.calls["pay"] == 1 and fake.calls["info"] == 1,
                   f"{r.location} {fake.calls}")
            old_pid = p1["provider_id"]
            _sql(s, "UPDATE pay_attempts SET created_at='2020-01-01T00:00:00Z' WHERE provider_id=?", old_pid)
            r = anon.post(path, tier="basic", months="1", method="card", terms="1")
            p2 = _payment(s, cid)
            res.ok("ссылка старше PAY_TTL: новая попытка, reference прежний",
                   p2["provider_id"] != old_pid and r.location == p2["pay_url"] and p2["reference"] == p1["reference"]
                   and fake.calls["pay"] == 2, f"{dict(p2)}")
            res.check("обе попытки записаны", _sql(s, "SELECT count(*) FROM pay_attempts WHERE payment_id=?", p2["id"]),
                      [(2,)])
            # клиника заплатила во вкладке со СТАРОЙ ссылкой — callback по старому payId
            fake.set_status(old_pid, "OK")
            r = anon.post_raw(CALLBACK, fake.callback(old_pid))
            res.ok("callback по прежней попытке — наш, нота оплачена (не 404)",
                   r.status == 200 and json.loads(r.body).get("outcome") == "paid"
                   and _payment(s, cid)["status"] == "paid", f"{r.status} {r.body}")
            res.check("вариант после оплаты прежней попыткой — Basic", _subrow(s, cid)[1], "basic")
            res.ok("повторный callback той же попытки — already",
                   json.loads(anon.post_raw(CALLBACK, fake.callback(old_pid)).body).get("outcome") == "already")
            # задача: протухшая попытка — один окончательный ответ, без card_failed, назавтра не спрашивает
            fake.set_status(p2["provider_id"], "TIMEOUT")
            info0 = fake.calls["info"]
            rc, out = _run(s, datetime.now(UTC).date())
            rc2, out2 = _run(s, datetime.now(UTC).date())
            res.ok("TIMEOUT протухшей ссылки: maib спрошен один раз, card_failed не пишется",
                   fake.calls["info"] == info0 + 1
                   and _sql(s, "SELECT count(*) FROM audit WHERE what='card_failed'")[0][0] == 0
                   and _sql(s, "SELECT final FROM pay_attempts WHERE provider_id=?", p2["provider_id"]) == [(1,)],
                   f"{fake.calls} {out[-300:]}")
            # нота SMS: программа получает страницу оплаты, карта — там же, за галочкой
            st, data = _json(anon, "/v1/sms/order", _token(s, cid), {"pack": 100})
            res.ok("нота SMS из программы: pay_url — страница оплаты, не ссылка maib; у maib платежа нет",
                   st == 200 and (data.get("pay_url") or "").startswith(config.BASE_URL.rstrip("/") + "/plata/")
                   and fake.calls["pay"] == 2, repr((st, data)))
            page = anon.get(path).body
            sms_ref = data.get("reference", "")
            res.ok("страница оплаты показывает ноту SMS с картой за галочкой",
                   sms_ref in page and "Pachet 100 SMS" in page and f"name='ref' value='{sms_ref}'" in page, page[-1500:])
            res.check("карта ноты SMS без галочки — need_terms",
                      anon.post(path, ref=sms_ref, method="card").location, f"{path}?msg=need_terms")
            r = anon.post(path, ref=sms_ref, method="card", terms="1")
            sp = _sql(s, "SELECT provider_id, pay_url FROM payments WHERE reference=?", sms_ref)[0]
            res.ok("клик на ноте SMS: ссылка maib родилась сейчас", r.status == 303 and r.location == sp[1]
                   and sp[0] in fake.pays, f"{r.location} {sp}")
            # страница возврата: maib уже сказал OK — сервер применяет сразу и говорит «plătită»
            fake.set_status(sp[0], "OK")
            ok = Client(s.url).get(f"/pay/ok?payId={sp[0]}&orderId={sms_ref}")
            res.ok("/pay/ok: спросил maib о попытке, нота SMS оплачена, «plătită»",
                   "plătită" in ok.body and sms_ref in ok.body
                   and _sql(s, "SELECT status FROM payments WHERE reference=?", sms_ref) == [("paid",)], ok.body[-1200:])
            acc = _account(anon, _token(s, cid))
            # пробных 30 здесь нет: счёт SMS завёлся уже после оплаты (бонус — при первом обращении в пробном)
            res.ok("пакет начислен: +100", acc.get("balance") == 100, repr(acc))
    finally:
        fake.close()
