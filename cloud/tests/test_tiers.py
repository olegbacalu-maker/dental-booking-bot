"""Варианты абонемента DentPilot Basic / Plus / Premium (tiers.py).

Правило без сервера: вариант, цена месяца (своя у подписки — прайс у другого
варианта), модуль SMS и календари врачей после оплаты (вариант с ними — сразу, уход
с них — до конца текущего периода), тексты писем и кодов. Через живой сервер: выбор
на /plata с галочкой условий, замена ноты вместо второго долга, confirm ставит
вариант, цену и модуль, коды sms_basic / sms_off, ручная смена варианта, нота за 14
дней в текущем варианте, страница возврата maib с № заказа, вариант без цены,
миграция данных до шага 15, Premium без прайса вручную и с прайсом оплатой. Сторож
`suite_sets` — что даёт вариант, решают множества tiers, не сравнение с одним
вариантом. Цены прогона — заметно не настоящие (harness: DP_PRICE_*).
"""
import ast
import base64
import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from harness import CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path, unb64u

sys.path.insert(0, str(CLOUD))
from app import config, db, license, mail, receipts, sms, tiers, views  # noqa: E402
from app import payments as pay  # noqa: E402
from test_account import BANK_ENV, _letters, _sql  # noqa: E402
from test_jobs import _run  # noqa: E402
from test_paylink import HDR, _link, _token  # noqa: E402

UTC = timezone.utc
B, P, PR = tiers.BASIC, tiers.PLUS, tiers.PREMIUM
rv = load_by_path("rsa_verify_tiers", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
SMS_ENV = {"DP_SMSMD_TOKEN": "test-token", "DP_SMSMD_BASE_URL": "http://127.0.0.1:9", "DP_SMS_OFFERED": "1",
           "DP_SMS_PACKS": "100:50"}


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _sub(plan: str = "standard", tier: str = P, price: int = 0, valid: datetime | None = None,
         sms_until: datetime | None = None, gdoc_until: datetime | None = None) -> dict:
    return {"plan": plan, "tier": tier, "price": price, "grace_days": 14,
            "valid_until": valid.strftime(db.TS) if valid else None,
            "sms_until": sms_until.strftime(db.TS) if sms_until else None,
            "gdoc_until": gdoc_until.strftime(db.TS) if gdoc_until else None}


def _note(tier: str | None = B, months: int = 1, amount: int = 0) -> dict:
    return {"tier": tier, "months": months, "amount": amount or tiers.list_price(tier or P)}


def suite_rules(res: Result) -> None:
    now = _now()
    pb, pp = tiers.list_price(B), tiers.list_price(P)
    res.ok("прайс прогона: оба варианта продаются, Basic дешевле", 0 < pb < pp, str(config.PRICES))
    res.check("вариант: нет подписки и пробный — Plus (условия § 3), иначе — свой",
              [tiers.current(None), tiers.current(_sub("trial", B)), tiers.current(_sub(tier=B)),
               tiers.current(_sub(tier="gold"))], [P, P, B, P])
    res.check("⛔ цена варианта — всегда прайс: и у оплаченной подписки по 444, и у пробного (Олег 26.10: "
              "«600 везде»)",
              [tiers.price(_sub(tier=P, price=444), P), tiers.price(_sub(tier=P, price=444), B),
               tiers.price(_sub("trial", P, 444), P), tiers.price(None, B)], [pp, pb, pp, pb])
    res.check("сумма ноты: год — 11 месячных прайса, не цены подписки", pay.amount_for(_sub(tier=P, price=444), P, 12),
              11 * pp)
    res.check("выбор по умолчанию: названный, иначе текущий", [tiers.pick(_sub("trial", B)), tiers.pick(_sub(tier=B)),
                                                                tiers.pick(_sub(tier=B), P), tiers.pick(None, "x")],
              [P, B, P, P])
    res.check("модуль SMS: Plus и пробный — да; Basic — пока не прошёл sms_until",
              [tiers.module_on(_sub(tier=P), now), tiers.module_on(_sub("trial", B), now),
               tiers.module_on(_sub(tier=B), now), tiers.module_on(_sub(tier=B, sms_until=now + timedelta(days=3)), now),
               tiers.module_on(_sub(tier=B, sms_until=now - timedelta(seconds=1)), now)],
              [True, True, False, True, False])
    g_end = now + timedelta(days=40)
    res.check("право gcal: пробный и Plus — до конца файла; Basic — до sms_until, но не дальше; прошло — нет",
              [tiers.gcal_until(_sub("trial", B), g_end, now), tiers.gcal_until(_sub(tier=P), g_end, now),
               tiers.gcal_until(None, g_end, now), tiers.gcal_until(_sub(tier=B), g_end, now),
               tiers.gcal_until(_sub(tier=B, sms_until=now + timedelta(days=3)), g_end, now),
               tiers.gcal_until(_sub(tier=B, sms_until=g_end + timedelta(days=9)), g_end, now),
               tiers.gcal_until(_sub(tier=B, sms_until=now - timedelta(seconds=1)), g_end, now),
               tiers.gcal_until(_sub(tier=P), now, now)],
              [g_end, g_end, g_end, None, now + timedelta(days=3), g_end, None, None])
    samples = [_sub(tier=P), _sub("trial", B), _sub(tier=B), _sub(tier=B, sms_until=now + timedelta(days=3)),
               _sub(tier=B, sms_until=now - timedelta(seconds=1)), _sub(tier="gold")]
    res.check("право gcal есть ровно там, где работает модуль SMS (срок файла впереди)",
              [tiers.gcal_until(x, g_end, now) is not None for x in samples], [tiers.module_on(x, now) for x in samples])
    # tier_after — что confirm делает с подпиской (§ 4.2)
    trial_end = now + timedelta(days=20)
    t, price, until, _, why = pay.tier_after(_sub("trial", P, pp, trial_end), _note(B), now)
    res.ok("пробный → Basic: модуль до конца пробного, цена — прайс Basic, строка журнала",
           (t, price, until) == (B, pb, trial_end.strftime(db.TS)) and "пробный → DentPilot Basic" in why
           and trial_end.strftime("%Y-%m-%d") in why, repr((t, price, until, why)))
    end = now + timedelta(days=5)
    res.check("Plus → Basic с действующим сроком: модуль до конца оплаченного Plus",
              pay.tier_after(_sub(tier=P, price=444, valid=end), _note(B), now)[:3], (B, pb, end.strftime(db.TS)))
    t, _, until, _, why = pay.tier_after(_sub(tier=P, valid=now - timedelta(days=2)), _note(B), now)
    res.ok("Plus → Basic после конца срока (льгота): модуль гаснет сразу",
           (t, until) == (B, None) and "выключен сразу" in why, repr((t, until, why)))
    keep = now + timedelta(days=9)
    res.check("Basic → Basic: прежний конец модуля, цена — прайс Basic",
              pay.tier_after(_sub(tier=B, price=300, valid=end, sms_until=keep), _note(B, amount=300), now)[:3],
              (B, pb, keep.strftime(db.TS)))
    t, price, until, _, why = pay.tier_after(_sub(tier=B, price=300, valid=end), _note(P), now)
    res.ok("Basic → Plus: модуль сразу, цена — прайс Plus",
           (t, price, until) == (P, pp, None) and "модуль SMS сразу" in why, repr((t, price, until, why)))
    res.check("Plus → Plus по 444: в подписку записан прайс, не 444",
              pay.tier_after(_sub(tier=P, price=444, valid=end), _note(P, amount=444), now), (P, pp, None, None, ""))
    res.check("нота без варианта (до шага 15) — Plus", pay.tier_after(_sub(tier=P, price=444), _note(None), now)[0], P)
    saved = dict(config.PRICES)
    try:
        config.PRICES[B] = 0
        res.check("вариант сняли с продажи после ноты — цена из суммы ноты",
                  pay.tier_after(_sub(tier=P, valid=end), _note(B, 12, 11 * 321), now)[1], 321)
        res.check("вариант без цены не предлагается", tiers.offered(None), [P, PR])
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


def suite_premium_rules(res: Result) -> None:
    """Premium без сервера: контракт линии (ключ, имя, формулы), множества, права файла, три пути
    перехода, тексты страницы оплаты, админки и письма, шаг схемы 24."""
    now = _now()
    end = now + timedelta(days=5)
    g_end = now + timedelta(days=40)
    pp, ppr = tiers.list_price(P), tiers.list_price(PR)
    ts = (lambda d: d.strftime(db.TS))
    res.ok("прайс прогона: Premium продаётся и дороже Plus", 0 < pp < ppr, str(config.PRICES))
    res.check("Premium: ключ, имя и что даёт — контракт между сессиями линии",
              (tiers.TIERS, tiers.NAME[PR], tiers.WHAT[PR], tiers.WHAT_RU[PR]),
              ((B, P, PR), "DentPilot Premium", "cu modulul SMS și calendarele medicilor în Google",
               "с модулем SMS и календарями врачей в Google"))
    res.check("формулы Basic и Plus не тронуты", (tiers.WHAT[B], tiers.WHAT[P], tiers.WHAT_RU[B], tiers.WHAT_RU[P]),
              ("fără modulul SMS", "cu modulul SMS", "без модуля SMS", "с модулем SMS"))
    res.check("множества: модуль SMS и связь с Google — Plus и Premium, календари врачей — только Premium",
              (sorted(tiers.SMS_TIERS), sorted(tiers.GCAL_TIERS), sorted(tiers.GDOC_TIERS)), ([P, PR], [P, PR], [PR]))
    res.check("пробный остаётся Plus, и при tier=premium в строке", tiers.current(_sub("trial", PR)), P)
    res.check("модуль SMS у Premium работает без sms_until", tiers.module_on(_sub(tier=PR), now), True)
    res.check("право gcal у Premium — до конца файла (Premium ⊃ Plus)", tiers.gcal_until(_sub(tier=PR), g_end, now), g_end)
    gd = (lambda x: tiers.gdoc_until(x, g_end, now))
    res.check("право gcal_doctor: Premium — до конца файла; Plus, Basic, пробный, без подписки — нет; после ухода — "
              "до gdoc_until, но не дальше файла; прошло — нет",
              [gd(_sub(tier=PR)), gd(_sub(tier=P)), gd(_sub(tier=B)), gd(_sub("trial", PR)), gd(None),
               gd(_sub(tier=P, gdoc_until=now + timedelta(days=3))), gd(_sub(tier=B, gdoc_until=g_end + timedelta(days=9))),
               gd(_sub(tier=P, gdoc_until=now - timedelta(seconds=1)))],
              [g_end, None, None, None, None, now + timedelta(days=3), g_end, None])
    res.check("права файла Premium: gcal и gcal_doctor одной датой", license.features(_sub(tier=PR), g_end, now),
              {"gcal": ts(g_end), "gcal_doctor": ts(g_end)})
    res.check("права файла Plus и пробного — только gcal",
              [license.features(_sub(tier=P), g_end, now), license.features(_sub("trial", PR), g_end, now)],
              [{"gcal": ts(g_end)}, {"gcal": ts(g_end)}])
    res.check("права файла Basic без остатков — пусто (поля features нет)", license.features(_sub(tier=B), g_end, now), {})
    res.check("слова прав для журнала и reissue",
              [license.rights({}), license.rights({"gcal": "X"}), license.rights({"gcal": "X", "gcal_doctor": "Y"})],
              ["без gcal", "gcal до X", "gcal до X, gcal_doctor до Y"])
    # три пути перехода (§ 4.2 правилом модуля SMS)
    t, price, su, gu, why = pay.tier_after(_sub(tier=P, valid=end), _note(PR), now)
    res.ok("Plus → Premium: календари сразу, модуль SMS как был, цена — прайс Premium",
           (t, price, su, gu) == (PR, ppr, None, None) and "календари врачей сразу" in why and "модуль SMS" not in why,
           repr((t, price, su, gu, why)))
    t, _, su, gu, why = pay.tier_after(_sub(tier=B, valid=end, sms_until=now - timedelta(days=1)), _note(PR), now)
    res.ok("Basic → Premium: и модуль SMS, и календари — сразу",
           (t, su, gu) == (PR, None, None) and "модуль SMS сразу" in why and "календари врачей сразу" in why,
           repr((t, su, gu, why)))
    t, _, su, gu, why = pay.tier_after(_sub(tier=PR, valid=end), _note(P), now)
    res.ok("⛔ Premium → Plus: модуль SMS работает (без sms_until), календари — до конца оплаченного периода",
           (t, su, gu) == (P, None, ts(end)) and f"календари врачей до {ts(end)[:10]}" in why and "модуль SMS" not in why,
           repr((t, su, gu, why)))
    t, _, su, gu, why = pay.tier_after(_sub(tier=PR, valid=end), _note(B), now)
    res.ok("Premium → Basic: и модуль SMS, и календари — до конца оплаченного периода",
           (t, su, gu) == (B, ts(end), ts(end)) and f"модуль SMS до {ts(end)[:10]}" in why
           and f"календари врачей до {ts(end)[:10]}" in why, repr((t, su, gu, why)))
    t, _, su, gu, why = pay.tier_after(_sub(tier=PR, valid=now - timedelta(days=2)), _note(P), now)
    res.ok("Premium → Plus после конца срока (льгота): календари гаснут сразу",
           (t, gu) == (P, None) and "календари врачей выключены сразу" in why, repr((t, gu, why)))
    keep = now + timedelta(days=9)
    res.check("Plus → Basic после ухода с Premium: остаток календарей прежний, модуль SMS — до конца периода",
              pay.tier_after(_sub(tier=P, valid=end, gdoc_until=keep), _note(B), now)[2:4], (ts(end), ts(keep)))
    res.check("Plus → Plus после ухода с Premium: остаток календарей прежний",
              pay.tier_after(_sub(tier=P, valid=end, gdoc_until=keep), _note(P), now)[3], ts(keep))
    res.check("Premium → Premium: ничего не сменилось", pay.tier_after(_sub(tier=PR, valid=end), _note(PR), now),
              (PR, ppr, None, None, ""))
    res.check("пробный → Premium: календари сразу, модуль SMS был и есть",
              pay.tier_after(_sub("trial", P, pp, end), _note(PR), now)[4],
              "переход пробный → DentPilot Premium: календари врачей сразу")
    # тексты
    _, body = mail.license_letter("Clinica T", ts(end), "standard", tier=P, gdoc_until=ts(end))
    _, body2 = mail.license_letter("Clinica T", ts(end), "standard", tier=PR)
    res.ok("письмо о лицензии ушедшей с Premium: до какого дня календари и что потом; у Premium — без этой фразы",
           f"Calendarele medicilor în Google se actualizează până la {mail.ro_date(ts(end))}" in body
           and "programările viitoare" in body and "Modulul SMS rămâne" not in body
           and "Calendarele medicilor" not in body2 and "Abonamentul DentPilot Premium" in body2, body[:600])
    res.check("формула вариантов в письме: с прайсом Premium — три, Basic/Plus — прежними словами", mail.variants(),
              "DentPilot Basic, fără modulul SMS, DentPilot Plus, cu modulul SMS, sau DentPilot Premium, cu modulul SMS și "
              "calendarele medicilor în Google")
    saved = dict(config.PRICES)
    try:
        config.PRICES[PR] = 0
        res.check("без прайса Premium — прежняя формула двух вариантов", mail.variants(),
                  "DentPilot Basic, fără modulul SMS, sau DentPilot Plus, cu modulul SMS")
        res.check("без прайса Premium не предлагается (кабинет, /plata)", tiers.offered(None), [B, P])
        res.ok("без прайса Premium «что будет при выборе» его не называет",
               "Premium" not in views._module_note(_sub(tier=P, valid=end), now))
    finally:
        config.PRICES.update(saved)
    res.ok("«что даёт вариант» — строка на каждый вариант (без неё /plata — 500 в день появления прайса)",
           set(views._TIER_PERKS) == set(tiers.TIERS), str(sorted(views._TIER_PERKS)))
    note = views._module_note(_sub(tier=PR, valid=end), now)
    res.ok("«что будет при выборе» у Premium: календари до конца периода с Basic или Plus, модуль SMS — с Basic",
           "Cu DentPilot Basic modulul SMS rămâne pornit până la sfârșitul perioadei în curs" in note
           and "Cu DentPilot Basic sau DentPilot Plus calendarele medicilor în Google se actualizează până la sfârșitul "
               "perioadei în curs" in note, note)
    note = views._module_note(_sub(tier=P, valid=end), now)
    res.ok("у Plus — Premium включает календари сразу, о выключении календарей ни слова",
           "DentPilot Premium pornește calendarele medicilor în Google imediat" in note
           and "se actualizează până la" not in note, note)
    res.check("плитка админки: Premium — модуль SMS и календари работают", views._module_word(_sub(tier=PR), now),
              "по варианту модуль SMS работает; календари врачей работают")
    res.ok("плитка админки у Plus после ухода с Premium — до какого дня календари",
           "календари врачей до" in views._module_word(_sub(tier=P, gdoc_until=keep), now)
           and "календари" not in views._module_word(_sub(tier=P), now))
    res.ok("код tier_bad называет каждый вариант", all(tiers.NAME[t] in views.MSG["tier_bad"][1] for t in tiers.TIERS),
           views.MSG["tier_bad"][1])
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for step in range(1, db.SCHEMA_VERSION + 1):
            db.apply_step(con, step)
        try:
            db.apply_step(con, 24)
            again = ""
        except sqlite3.OperationalError as e:
            again = str(e)
        cols = {r[1] for r in con.execute("PRAGMA table_info(subscriptions)")}
        res.ok("шаг 24: subscriptions.gdoc_until; повтор шага без ошибки",
               "gdoc_until" in cols and not again and db.SCHEMA_VERSION >= 24, again)
    finally:
        con.close()


_ONE = {"BASIC", "PLUS", "PREMIUM"}


def _one_tier(x: ast.AST) -> bool:
    """`tiers.PLUS` (и BASIC, PREMIUM) или строка варианта — один вариант, а не множество."""
    if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name):
        return x.value.id == "tiers" and x.attr in _ONE
    return isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value in tiers.TIERS


def suite_sets(res: Result) -> None:
    """⛔ Что даёт вариант — множествами tiers (SMS_TIERS, GCAL_TIERS, GDOC_TIERS), не сравнением с одним
    вариантом: «Plus или иначе Basic» у третьего варианта молча выключало SMS и связь с Google. Разбор `ast`
    всей cloud/app, кроме tiers.py: == / != / is с вариантом и in (…) с литералом из вариантов."""
    app = CLOUD / "app"
    files = [p for p in sorted(app.rglob("*.py")) if p != app / "tiers.py"]
    res.ok("исходники облака нашлись", len(files) >= 30, str(len(files)))
    bad = []
    for p in files:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Compare):
                continue
            sides = [node.left, *node.comparators]
            for op, a, b in zip(node.ops, sides, sides[1:]):
                one = isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)) and (_one_tier(a) or _one_tier(b))
                lit = (isinstance(op, (ast.In, ast.NotIn)) and isinstance(b, (ast.Tuple, ast.List, ast.Set))
                       and any(_one_tier(e) for e in b.elts))
                if one or lit:
                    bad.append(f"{p.relative_to(CLOUD).as_posix()}:{node.lineno}")
    res.check("нет сравнения с одним вариантом (== / != tiers.PLUS|BASIC|PREMIUM, in (tiers.X, …)) вне tiers.py",
              bad, [])


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
               and f"Modulul SMS rămâne pornit până la {mail.ro_date(trial_end)}" in body, body[:600])
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
        res.check("Plus вручную: цена — прайс; цена из формы (старой) не принимается", _subrow(s, cid)[1:3],
                  ("plus", pp))
        res.ok("у «Вариант вручную» нет поля цены", "placeholder='цена / мес." not in admin.get(f"/admin/clinics/{cid}").body)
        res.check("продление — по прайсу", views._mdl(pp) + " MDL <small>/ lună</small>" in anon.get(path).body, True)
        cid2 = cid_from(admin.post("/admin/clinics", name="Clinica Proba", idno="4444444444444").location)
        admin.post(f"/admin/clinics/{cid2}/issue", kind="trial")
        res.check("пробный вручную не меняется — tier_trial",
                  admin.post(f"/admin/clinics/{cid2}/tier", tier="basic").location, f"/admin/clinics/{cid2}?msg=tier_trial")
        res.check("и у оплатившей клиники без галочки нота не создаётся — need_terms",
                  anon.post(path, tier="plus", months="1", method="transfer").location, f"{path}?msg=need_terms")
        # страница возврата maib: по checkoutId, не по reference
        ref = _sql(s, "SELECT reference FROM payments WHERE id=?", pid)[0][0]
        _sql(s, "UPDATE payments SET provider_id='pay-ok-test-uuid' WHERE id=?", pid)
        ok = Client(s.url).get(f"/pay/ok?checkoutId=pay-ok-test-uuid&orderId={ref}")
        res.ok("/pay/ok: № заказа, что оплачено, сумма, «plătită» только раз сервер закрыл ноту, поставщик",
               ok.status == 200 and ref in ok.body and "Abonament DentPilot Plus, 1 lună" in ok.body
               and f"{views._mdl(pp)} MDL" in ok.body and "plătită" in ok.body and "Oleg Bacalu" in ok.body
               and "Mulțumim" in ok.body, ok.body[-1500:])
        res.ok("/pay/ok по одному reference (порядковому) ничего не показывает",
               ref not in Client(s.url).get(f"/pay/ok?orderId={ref}").body)
        res.ok("/pay/ok с неизвестным checkoutId — без подробностей",
               ref not in Client(s.url).get(f"/pay/ok?checkoutId=nu-exista&orderId={ref}").body)
        anon.post(path, tier="plus", months="12", method="transfer", terms="1")
        pend = _sql(s, "SELECT id, reference FROM payments WHERE clinic_id=? AND status='pending'", cid)[0]
        _sql(s, "UPDATE payments SET provider_id='pay-wait-uuid' WHERE id=?", pend[0])
        ok = Client(s.url).get(f"/pay/ok?checkoutId=pay-wait-uuid&orderId={pend[1]}")
        res.ok("/pay/ok до ответа maib — «în curs de confirmare», не «plătită»",
               pend[1] in ok.body and "în curs de confirmare" in ok.body and "plătită" not in ok.body, ok.body[-1200:])
        fail = Client(s.url).get(f"/pay/fail?checkoutId=pay-wait-uuid&orderId={pend[1]}")
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


def _files(s: Server, cid: str) -> list[tuple]:
    """Выдачи клиники по порядку: (seq, claim как подписан, valid_until, grace_until, основание)."""
    return [(seq, json.loads(unb64u(p)), v, g, why) for seq, p, v, g, why in
            _sql(s, "SELECT seq, payload, valid_until, grace_until, reason FROM issues WHERE clinic_id=? ORDER BY seq", cid)]


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _gcal(claim: dict) -> str | None:
    return (claim.get("features") or {}).get("gcal")


def _tools(s: Server, *args: str) -> str:
    p = subprocess.run([sys.executable, "-m", "app.tools", "reissue", *args], cwd=str(CLOUD), env=s.env,
                       capture_output=True, text=True, encoding="utf-8")
    return p.stdout + p.stderr


def suite_gcal(res: Result) -> None:
    """Право gcal в файле (`features`) — правилом модуля SMS: пробный, оплата Basic и Plus, «Вариант
    вручную» новым файлом, нота без подписки, срок на оплату первой ноты, перевыдача командой."""
    pb = tiers.list_price(B)
    with Server(env={**BANK_ENV, **SMS_ENV}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Google", idno="7777777777771",
                                  email="google@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        seq, claim, trial_end, grace, _ = _files(s, cid)[-1]
        res.check("пробный: право gcal до конца файла с льготой", _gcal(claim), grace)
        code, pc = rv.open_envelope(admin.get(f"/admin/clinics/{cid}/issues/{seq}/license.json").body, KEYS)
        res.ok("проверка программы принимает файл с правом и видит ту же дату",
               code == "" and pc is not None and pc.features.get("gcal") is not None
               and pc.features["gcal"].strftime(db.TS) == grace, (code, pc))
        res.ok("журнал выдачи называет право", any(f"gcal до {grace}" in d for (d,) in
                                                 _sql(s, "SELECT detail FROM audit WHERE what='issue' AND clinic_id=?", cid)))

        tok = _token(s, cid)
        anon = Client(s.url)
        path = "/plata/" + _link(anon, tok)[1].rsplit("/", 1)[1]

        def paid(tier: str) -> None:
            anon.post(path, tier=tier, months="1", method="transfer", terms="1")
            pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending'", cid)[0][0]
            admin.post(f"/admin/payments/{pid}/confirm")

        paid("basic")
        seq2, claim, _, grace2, _ = _files(s, cid)[-1]
        res.ok("пробный → Basic: право до конца пробного (как модуль SMS), не до нового срока",
               seq2 == seq + 1 and _gcal(claim) == trial_end and grace2 > trial_end, (seq2, _gcal(claim), trial_end))
        paid("plus")
        seq3, claim, valid3, grace3, _ = _files(s, cid)[-1]
        res.check("Basic → Plus: право до конца нового файла", (seq3, _gcal(claim)), (seq2 + 1, grace3))
        r = admin.post(f"/admin/clinics/{cid}/tier", tier="basic")
        seq4, claim, valid4, grace4, why = _files(s, cid)[-1]
        res.ok("«Вариант вручную» Basic: новый файл с тем же сроком и без права",
               r.location.endswith("msg=tier_set") and seq4 == seq3 + 1 and (valid4, grace4) == (valid3, grace3)
               and "features" not in claim and why == "вариант вручную", (r.location, seq4, claim))
        res.ok("журнал «Вариант вручную» называет файл", any(f"файл {seq4} с тем же сроком" in d for (d,) in
                                                           _sql(s, "SELECT detail FROM audit WHERE what='tier_set'")))
        admin.post(f"/admin/clinics/{cid}/tier", tier="plus")
        seq5, claim, valid5, grace5, _ = _files(s, cid)[-1]
        res.ok("«Вариант вручную» Plus: новый файл с тем же сроком и правом до его конца",
               seq5 == seq4 + 1 and (valid5, grace5) == (valid3, grace3) and _gcal(claim) == grace3, (seq5, claim))

        # нота без подписки: строку подписки заводит выдача — уже с оплаченным вариантом
        cid_b = cid_from(admin.post("/admin/clinics", name="Clinica Fara Fisier", idno="7777777777772",
                                    email="fara@example.md").location)
        admin.post(f"/admin/clinics/{cid_b}/payments", months="1", amount="", send="", method="transfer", tier="basic")
        pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending'", cid_b)[0][0]
        admin.post(f"/admin/payments/{pid}/confirm")
        files = _files(s, cid_b)
        res.ok("нота Basic без подписки: подписка заведена с Basic и его ценой, файл без права",
               _subrow(s, cid_b)[:4] == ("standard", "basic", pb, None) and len(files) == 1
               and "features" not in files[0][1], (_subrow(s, cid_b), files[-1][1] if files else None))

        # срок на оплату первой ноты («Adaugă clinică») узнаётся по основанию последней выдачи
        cid_a = cid_from(admin.post("/admin/clinics", name="Clinica Filiala", idno="7777777777773",
                                    email="filiala@example.md").location)
        today = datetime.now(UTC).date()
        admin.post(f"/admin/clinics/{cid_a}/issue", kind="dates", valid_until=f"{today + timedelta(days=14):%Y-%m-%d}",
                   grace_days="14")
        _sql(s, "UPDATE issues SET reason=? WHERE clinic_id=?", pay.ADVANCE, cid_a)
        admin.post(f"/admin/clinics/{cid_a}/tier", tier="basic")
        res.check("перевыдача у клиники со сроком на оплату первой ноты оставляет его основание",
                  [why for *_, why in _files(s, cid_a)], [pay.ADVANCE, pay.ADVANCE])

        # команда перевыдачи: файл «до выкатки» без права у Plus, вариант сменён мимо выдачи, отзыв, прошедший срок
        old = dict(_files(s, cid)[-1][1])
        old.pop("features", None)
        _sql(s, "UPDATE issues SET payload=? WHERE clinic_id=? AND seq=?",
             _b64u(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()), cid, seq5)
        cid_d = cid_from(admin.post("/admin/clinics", name="Clinica Dates", idno="7777777777774",
                                    email="dates@example.md").location)
        admin.post(f"/admin/clinics/{cid_d}/issue", kind="dates", valid_until=f"{today + timedelta(days=20):%Y-%m-%d}",
                   grace_days="14")
        _sql(s, "UPDATE subscriptions SET tier='basic' WHERE clinic_id=?", cid_d)
        cid_r = cid_from(admin.post("/admin/clinics", name="Clinica Retrasa", idno="7777777777775",
                                    email="retrasa@example.md").location)
        admin.post(f"/admin/clinics/{cid_r}/issue", kind="dates", valid_until=f"{today + timedelta(days=20):%Y-%m-%d}",
                   grace_days="14")
        _sql(s, "UPDATE subscriptions SET tier='basic' WHERE clinic_id=?", cid_r)
        admin.post(f"/admin/clinics/{cid_r}/revoke", reason="test", confirm="ОТОЗВАТЬ")
        # у файла с прошедшей льготой право в claim ещё записано, а выдача сейчас его бы не дала
        cid_x = cid_from(admin.post("/admin/clinics", name="Clinica Expirata", idno="7777777777776",
                                    email="expirata@example.md").location)
        admin.post(f"/admin/clinics/{cid_x}/issue", kind="dates", valid_until=f"{today + timedelta(days=20):%Y-%m-%d}",
                   grace_days="14")
        past = (datetime.now(UTC) - timedelta(days=1)).strftime(db.TS)
        _sql(s, "UPDATE issues SET valid_until=?, grace_until=? WHERE clinic_id=?", past, past, cid_x)
        seqs = {c: _files(s, c)[-1][0] for c in (cid, cid_d, cid_r, cid_x, cid_b, cid_a)}
        out = _tools(s)
        res.ok("reissue без --apply: две клиники с иными правами, файлов нет; отзыв и прошедший срок мимо",
               f"{cid} Clinica Google: без gcal → gcal до {grace3}" in out
               and f"{cid_d} Clinica Dates: gcal до" in out and "→ без gcal" in out
               and cid_r not in out and cid_x not in out and cid_b not in out and cid_a not in out
               and "к перевыдаче: 2" in out and {c: _files(s, c)[-1][0] for c in seqs} == seqs, out)
        out = _tools(s, "--apply")
        got = {c: _files(s, c)[-1] for c in seqs}
        res.ok("reissue --apply: seq+1 с тем же сроком и правом по варианту, у остальных ничего",
               got[cid][0] == seqs[cid] + 1 and _gcal(got[cid][1]) == grace3 and (got[cid][2], got[cid][3]) == (valid3, grace3)
               and got[cid_d][0] == seqs[cid_d] + 1 and "features" not in got[cid_d][1]
               and got[cid][4] == "перевыдача: права в файле"
               and all(got[c][0] == seqs[c] for c in (cid_r, cid_x, cid_b, cid_a)) and "выдано: 2" in out, out)
        code, pc = rv.open_envelope(admin.get(f"/admin/clinics/{cid}/issues/{got[cid][0]}/license.json").body, KEYS)
        res.ok("перевыданный файл принимает проверка программы", code == "" and pc is not None
               and pc.seq == seqs[cid] + 1 and pc.features["gcal"].strftime(db.TS) == grace3, (code, pc))
        res.ok("повтор команды ничего не находит", "к перевыдаче: 0" in _tools(s), _tools(s))


def suite_premium(res: Result) -> None:
    """Premium через живой сервер. Без прайса: страница оплаты его не предлагает, «Вариант вручную» ставит (проверка
    до продажи) — файл с обоими правами; назад на Plus вручную — календари сразу. С прайсом: оплата из пробного,
    Premium → Plus оплатой — календари до конца периода, письмо, плитка; перевыдача видит gcal_doctor и не ходит по
    кругу."""
    today = datetime.now(UTC).date()
    with Server(env={**BANK_ENV, **SMS_ENV, "DP_PRICE_PREMIUM": ""}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Canar", idno="7777777777781",
                                  email="canar@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{today + timedelta(days=20):%Y-%m-%d}",
                   grace_days="14")
        seq, *_ = _files(s, cid)[-1]
        tok = _token(s, cid)
        anon = Client(s.url)
        path = "/plata/" + _link(anon, tok)[1].rsplit("/", 1)[1]
        page = anon.get(path).body
        res.ok("без прайса Premium: на странице оплаты его нет", "value='premium'" not in page
               and "value='plus'" in page and "DentPilot Premium" not in page, page[-2500:])
        res.check("без прайса Premium не оплатить — tier_not_sold",
                  anon.post(path, tier="premium", months="1", method="transfer", terms="1").location,
                  f"{path}?msg=tier_not_sold")
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("админка: в «Выставить ноту» Premium недоступен, в «Вариант вручную» есть с пометкой «без прайса»",
               "value='premium' disabled>DentPilot Premium — не продаётся" in card
               and "<option value='premium'>DentPilot Premium (без прайса)</option>" in card, card[-4000:])
        r = admin.post(f"/admin/clinics/{cid}/tier", tier="premium")
        res.check("⛔ вручную Premium без прайса — tier_set (канарейка до продажи)", r.location,
                  f"/admin/clinics/{cid}?msg=tier_set")
        seq2, claim, valid2, grace2, why = _files(s, cid)[-1]
        res.ok("файл: тот же срок, права gcal и gcal_doctor до его конца",
               seq2 == seq + 1 and claim.get("features") == {"gcal": grace2, "gcal_doctor": grace2}
               and why == "вариант вручную", (seq2, claim))
        code, pc = rv.open_envelope(admin.get(f"/admin/clinics/{cid}/issues/{seq2}/license.json").body, KEYS)
        res.ok("проверка программы принимает файл и видит gcal_doctor", code == "" and pc is not None
               and pc.features.get("gcal_doctor") is not None and pc.features["gcal_doctor"].strftime(db.TS) == grace2,
               (code, pc))
        res.check("подписка: Premium, цена записью 0", _subrow(s, cid)[1:3], ("premium", 0))
        res.ok("журнал: прайса нет, модуль SMS и календари работают",
               any("DentPilot Plus → DentPilot Premium" in d and "прайса нет" in d and "модуль SMS работает" in d
                   and "календари врачей работают" in d
                   for (d,) in _sql(s, "SELECT detail FROM audit WHERE what='tier_set' AND clinic_id=?", cid)))
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("плитка «Вариант»: прайса нет, календари работают",
               "прайса нет — не продаётся" in card and "календари врачей работают" in card, card[:4000])
        res.check("модуль SMS у Premium работает", _account(anon, tok).get("blocked"), "")
        page = anon.get(path).body
        res.ok("страница оплаты клиники на Premium без прайса: Premium не предложен, сказано, что календари уйдут в конце периода",
               "value='premium'" not in page and " checked " in page
               and "calendarele medicilor în Google se actualizează până la sfârșitul perioadei în curs" in page, page[-2500:])
        out = subprocess.run([sys.executable, "-m", "app.tools", "check"], cwd=str(CLOUD), env=s.env,
                             capture_output=True, text=True, encoding="utf-8").stdout
        res.ok("tools check называет пустой прайс Premium", "DP_PRICE_PREMIUM пуст" in out, out[-800:])
        admin.post(f"/admin/clinics/{cid}/tier", tier="plus")
        seq3, claim, _, grace3, _ = _files(s, cid)[-1]
        res.ok("вручную Premium → Plus: календари гаснут сразу — в файле только gcal",
               seq3 == seq2 + 1 and claim.get("features") == {"gcal": grace3}
               and any("календари врачей выключены сразу" in d for (d,) in
                       _sql(s, "SELECT detail FROM audit WHERE what='tier_set' AND clinic_id=?", cid)), claim)

    with Server(env={**BANK_ENV, **SMS_ENV}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Premium", idno="7777777777782",
                                  email="premium@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        tok = _token(s, cid)
        anon = Client(s.url)
        path = "/plata/" + _link(anon, tok)[1].rsplit("/", 1)[1]
        page = anon.get(path).body
        res.ok("с прайсом: три карточки, у Premium — имя и что даёт словами условий",
               all(f"value='{t}'" in page for t in tiers.TIERS) and "DentPilot Premium" in page
               and tiers.WHAT[PR] in page and "DentPilot Premium pornește calendarele medicilor în Google" in page,
               page[-3000:])

        def paid(tier: str) -> None:
            anon.post(path, tier=tier, months="1", method="transfer", terms="1")
            pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending'", cid)[0][0]
            admin.post(f"/admin/payments/{pid}/confirm")

        n = len(_letters(s))
        anon.post(path, tier="premium", months="1", method="transfer", terms="1")
        res.ok("письмо с нотой Premium — вариант словами условий",
               len(_letters(s)) == n + 1 and f"DentPilot Premium ({tiers.WHAT[PR]})" in _letters(s)[-1][2])
        pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending'", cid)[0][0]
        admin.post(f"/admin/payments/{pid}/confirm")
        _, claim, valid1, grace1, _ = _files(s, cid)[-1]
        res.ok("пробный → Premium оплатой: оба права до конца нового файла, подписка Premium по прайсу",
               claim.get("features") == {"gcal": grace1, "gcal_doctor": grace1}
               and _subrow(s, cid)[1:4] == ("premium", tiers.list_price(PR), None), (claim, _subrow(s, cid)))
        res.ok("журнал оплаты: переход и «календари врачей сразу»",
               any("переход пробный → DentPilot Premium: календари врачей сразу" in d for (d,) in
                   _sql(s, "SELECT detail FROM audit WHERE what='payment_paid' AND clinic_id=?", cid)))
        n = len(_letters(s))
        paid("plus")
        _, claim, valid2, grace2, _ = _files(s, cid)[-1]
        res.ok("⛔ Premium → Plus оплатой: gcal — до конца нового файла, gcal_doctor — до конца оплаченного Premium",
               claim.get("features") == {"gcal": grace2, "gcal_doctor": valid1}
               and _sql(s, "SELECT tier, sms_until, gdoc_until FROM subscriptions WHERE clinic_id=?", cid)
               == [("plus", None, valid1)], claim)
        res.check("модуль SMS после Premium → Plus работает", _account(anon, tok).get("blocked"), "")
        body = _letters(s)[-1][2] if len(_letters(s)) > n else ""
        res.ok("письмо после оплаты: до какого дня обновляются календари врачей",
               f"Calendarele medicilor în Google se actualizează până la {mail.ro_date(valid1)}" in body, body[:900])
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("плитка «Вариант»: Plus, календари врачей до конца оплаченного Premium",
               f"календари врачей до {valid1[:10]}" in card, card[:4000])
        res.ok("reissue: файл с обоими правами — не к перевыдаче (одна сборка прав с выдачей)", "к перевыдаче: 0" in
               _tools(s), _tools(s))
        last = _files(s, cid)[-1]
        old = dict(last[1])
        old["features"] = {"gcal": old["features"]["gcal"]}
        _sql(s, "UPDATE issues SET payload=? WHERE clinic_id=? AND seq=?",
             _b64u(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()), cid, last[0])
        out = _tools(s)
        res.ok("reissue: файл без gcal_doctor у клиники с остатком календарей — к перевыдаче, словами обоих прав",
               f"{cid} Clinica Premium: gcal до {grace2} → gcal до {grace2}, gcal_doctor до {valid1}" in out
               and "к перевыдаче: 1" in out, out)
        admin.post(f"/admin/clinics/{cid}/tier", tier="plus")
        res.ok("«Вариант вручную» Plus после ухода с Premium: остаток календарей снят, в файле только gcal",
               _files(s, cid)[-1][1].get("features") == {"gcal": grace2}
               and _sql(s, "SELECT gdoc_until FROM subscriptions WHERE clinic_id=?", cid) == [(None,)],
               _files(s, cid)[-1][1])


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
        res.check("шаг 24: остатка календарей врачей у старой подписки нет",
                  _sql(s, "SELECT gdoc_until FROM subscriptions"), [(None,)])
        res.check("версия схемы", _sql(s, "SELECT value FROM schema_meta WHERE key='version'"), [(str(db.SCHEMA_VERSION),)])
        anon = Client(s.url)
        url = "/plata/" + _link(anon, tok)[1].rsplit("/", 1)[1]
        page = anon.get(url).body
        res.ok("страница: и Plus оплаченной по 444 подписки, и Basic — по прайсу (Олег 26.10: «600 везде»)",
               f"{views._mdl(tiers.list_price(P))} MDL <small>/ lună</small>" in page
               and f"{views._mdl(tiers.list_price(B))} MDL <small>/ lună</small>" in page
               and f"{views._mdl(444)} MDL" not in page and "value='plus' checked" in page, page[-2500:])
        anon.post(url, tier="plus", months="12", method="transfer", terms="1")
        res.check("оплаченная подписка по 444 — следующая нота (год) по прайсу: 11 × прайс Plus",
                  _sql(s, "SELECT tier, amount FROM payments WHERE status='pending'"), [("plus", 11 * tiers.list_price(P))])


def suite_card(res: Result) -> None:
    """Карта по клику (23.10): ссылка maib живёт 10 минут (maib.PAY_TTL) — письмо несёт нашу
    страницу, ссылка рождается кнопкой за галочкой; у ноты может быть несколько попыток, и
    оплата во вкладке со старой ссылкой узнаётся; задача не пишет card_failed каждый день."""
    from test_maib import FakeMaib, _payment
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
                   and "/plata/" in body and "checkout.maib.md" not in body and mail.CARD_NOTE in body, body[:800])
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
            fake.set_status(old_pid, "Completed")
            r = fake.post(anon, old_pid)
            res.ok("callback по прежней попытке — наш, нота оплачена (не 404)",
                   r.status == 200 and json.loads(r.body).get("outcome") == "paid"
                   and _payment(s, cid)["status"] == "paid", f"{r.status} {r.body}")
            res.check("вариант после оплаты прежней попыткой — Basic", _subrow(s, cid)[1], "basic")
            res.ok("повторный callback той же попытки — already",
                   json.loads(fake.post(anon, old_pid).body).get("outcome") == "already")
            # задача: протухшая попытка — один окончательный ответ, без card_failed, назавтра не спрашивает
            fake.set_status(p2["provider_id"], "Expired")
            info0 = fake.calls["info"]
            rc, out = _run(s, datetime.now(UTC).date())
            rc2, out2 = _run(s, datetime.now(UTC).date())
            res.ok("Expired (TIMEOUT) протухшей ссылки: maib спрошен один раз, card_failed не пишется",
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
            fake.set_status(sp[0], "Completed")
            ok = Client(s.url).get(f"/pay/ok?checkoutId={sp[0]}&orderId={sms_ref}")
            res.ok("/pay/ok: спросил maib о попытке, нота SMS оплачена, «plătită»",
                   "plătită" in ok.body and sms_ref in ok.body
                   and _sql(s, "SELECT status FROM payments WHERE reference=?", sms_ref) == [("paid",)], ok.body[-1200:])
            acc = _account(anon, _token(s, cid))
            # пробных 30 здесь нет: счёт SMS завёлся уже после оплаты (бонус — при первом обращении в пробном)
            res.ok("пакет начислен: +100", acc.get("balance") == 100, repr(acc))
    finally:
        fake.close()
