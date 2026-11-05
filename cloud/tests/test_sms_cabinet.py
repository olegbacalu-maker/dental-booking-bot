"""Пакеты SMS из кабинета клиники (05.11.2026, слово Олега: «в админке клиники во вкладке SMS
добавить и там эти пакеты» — вторая дверь рядом с программой, та остаётся).

Что держит набор:
- вкладка SMS кабинета: остаток СВОЕЙ клиники, пакеты из прайса сервера, заказ за галочкой условий,
  ожидающая нота с картой и реквизитами; во вкладке оплат — строка-указатель, не вторая форма;
- путь денег — тот же, что у абонемента: нота `payments` вида `sms`, попытки карты, settle; callback
  и возврат браузера разом дают ОДНО зачисление, второй платёж по закрытой ноте — второй пакет;
- кому пакет не продаётся (Basic, без IDNO), чужая нота, филиал из кнопки программы;
- страница оплаты: нота SMS первой и под своим заголовком;
- слова: у пакета срока нет — ни письмо с нотой, ни блок реквизитов, ни страница возврата не говорят
  «termenul se prelungește».

⛔ Пакеты и цены здесь — подмена `DP_SMS_PACKS` для стенда; настоящих цен в репозитории нет.
"""
import json
import re
import sys
from datetime import datetime, timezone

from harness import CLOUD, Client, Result, Server, cid_from

sys.path.insert(0, str(CLOUD))
from app import config, mail, views  # noqa: E402
from test_branches import BANK_ENV, BRANCH, DIRECTOR, MAIN, _add, _enter, _letters, _register, _sql, _token_of  # noqa: E402
from test_contlink import _link as _cont_link, _open  # noqa: E402
from test_jobs import _run  # noqa: E402
from test_maib import FakeMaib, _together  # noqa: E402
from test_paylink import _link as _pay_link  # noqa: E402
from test_tiers import _json  # noqa: E402

PACKS = "100:50,500:200"         # стенд: «штук:лей», не прайс
ENV = {**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_SMS_OFFERED": "1", "DP_SMSMD_TOKEN": "t",
       "DP_SMSMD_BASE_URL": "http://127.0.0.1:9", "DP_SMS_PACKS": PACKS}
TERM = "termenul"                # слово, которого у пакета быть не должно: срока у него нет


class _Row(dict):
    """Строка платежа для чистых проверок разметки."""

    def keys(self):  # noqa: D102 — как у sqlite3.Row
        return super().keys()


def _pane(body: str, key: str) -> str:
    return dict(re.findall(r"<section class='pane' data-pane='(\w+)'>(.*?)</section>", body, re.S)).get(key, "")


def _count(body: str, key: str) -> str:
    nav = body[body.index("<nav class='ctabs'"):body.index("</nav>")]
    m = re.search(rf"data-tab='{key}'.*?</span>(?:<span class='n'>(\d+)</span>)?</a>", nav, re.S)
    return (m.group(1) or "") if m else "?"


def _notes(s: Server, cid: str) -> list:
    return _sql(s, "SELECT reference, status, sms_units, amount, paid_via, terms_at FROM payments "
                   "WHERE clinic_id=? AND kind='sms' ORDER BY id", cid)


def _packs_of(s: Server, cid: str) -> list:
    return _sql(s, "SELECT delta FROM sms_ledger WHERE clinic_id=? AND reason='pack' ORDER BY id", cid)


def suite_words(res: Result) -> None:
    """Слова ноты SMS — без сервера: письмо, блок реквизитов, страница возврата. Реквизиты перевода —
    стенда (в процессе прогона окружения сервера нет), на время набора."""
    was = dict(config.BANK)
    config.BANK.update(beneficiary=BANK_ENV["DP_BANK_BENEFICIARY"], iban=BANK_ENV["DP_BANK_IBAN"])
    try:
        _words(res)
    finally:
        config.BANK.clear()
        config.BANK.update(was)


def _words(res: Result) -> None:
    url = "https://cloud.example/plata/abc"
    lic = mail.ways_to_pay("DP-2026-000001", 600, url)
    # способы оплаты — одни на все виды нот; от вида зависят только две концовки (mail.after_paid).
    # Умолчание — абонемент: его письмо от параметра не изменилось ни на байт
    res.ok("письмо ноты абонемента не изменилось: обе концовки — прежние фразы, байт в байт",
           mail.card_lines(url, 600).endswith(
               "  După plata cu cardul nu trebuie să faceți nimic: noul termen ajunge singur în program "
               "în câteva minute, iar confirmarea — pe e-mail.\n")
           and lic.endswith(
               "Important: indicați neapărat referința DP-2026-000001 în destinația plății — după ea "
               "recunoaștem plata dumneavoastră. După confirmare termenul se prelungește automat în "
               "program; primiți confirmarea pe e-mail.")
           and mail.card_lines(url, 600).startswith(f"{mail.CARD_NOTE}\n  {url}\n  Suma: 600 MDL\n")
           and lic == mail.ways_to_pay("DP-2026-000001", 600, url, kind="license")
           and "{" not in lic, lic)
    (card_l, bank_l), (card_s, bank_s) = mail.after_paid(), mail.after_paid("sms")
    pack = mail.ways_to_pay("DP-2026-000001", 600, url, kind="sms")
    res.ok("нота SMS отличается от ноты абонемента ТОЛЬКО двумя концовками: способы и реквизиты — те же строки",
           pack != lic and pack.replace(card_s, "<1>").replace(bank_s, "<2>")
           == lic.replace(card_l, "<1>").replace(bank_l, "<2>") and pack.count(mail.SMS_DONE["sms"]) == 2, pack)
    res.ok("неизвестный вид ноты — как абонемент (умолчание), не падение",
           mail.ways_to_pay("DP-2026-000001", 600, url, kind="cabinet") == lic)
    for kind, letter in (("sms", mail.sms_pack_note_letter("Clinica X", "DP-2026-000002", 50, 100, url)),
                         ("sms_name", mail.sms_name_note_letter("Clinica X", "DP-2026-000003", 77, "Zambet", url))):
        body = letter[1]
        res.ok(f"письмо с нотой {kind}: карта и реквизиты те же, что у абонемента, слов про срок нет",
               mail.CARD_NOTE in body and url in body and "Destinația plății: DP-2026-00000" in body
               and "indicați neapărat referința" in body and TERM not in body and "noul termen" not in body, body)
        res.check(f"письмо с нотой {kind}: что будет после оплаты — дважды, у карты и у перевода",
                  body.count(mail.SMS_DONE[kind]), 2)
    res.ok("правда о пакете — «SMS-urile se adaugă automat»",
           mail.SMS_DONE["sms"].startswith("SMS-urile se adaugă automat"))
    bare = mail.ways_to_pay("DP-2026-000004", 50, None, kind="sms")
    res.ok("блок реквизитов без карты: одни реквизиты, без «Sau prin transfer» и без срока",
           "Sau prin transfer" not in bare and "IBAN" in bare and TERM not in bare and mail.CARD_NOTE not in bare, bare)
    # страница возврата от банка
    base = dict(reference="DP-2026-000005", amount=50, currency="MDL", status="paid", paid_at="2026-11-05T10:00:00Z",
                sms_units=100, months=0, tier=None)
    pack, name = _Row(base, kind="sms"), _Row(base, kind="sms_name")
    abon = _Row(base, kind="license", months=1, tier="plus")
    for ok in (True, False):
        for label, row in (("пакет", pack), ("имя", name)):
            page = views.pay_page(ok, row)
            res.ok(f"страница возврата ({'ok' if ok else 'fail'}), {label}: без слов про срок и «Plătește acum»",
                   TERM not in page and "Plătește acum" not in page, page[-1500:])
    res.ok("страница возврата, пакет: «SMS-urile se adaugă automat», программа заберёт новый остаток",
           mail.SMS_DONE["sms"] in views.pay_page(True, pack) and "noul sold" in views.pay_page(True, pack)
           and "fila SMS" in views.pay_page(False, pack))
    res.ok("страница возврата, абонемент: как было — срок и «Plătește acum»",
           "termenul se prelungește automat" in views.pay_page(True, abon)
           and "Plătește acum" in views.pay_page(False, abon) and "termenul se prelungește" in views.pay_page(True, None))
    # карточка пакетов: что печатает по состоянию
    clinic = {"idno": "1003600012345"}
    shop = {"balance": 30, "packs": [{"units": 100, "price": 50}, {"units": 1000, "price": 450}], "closed": ""}
    card = views._cont_sms_shop(clinic, shop, [], "?c=c_1", True)
    res.ok("карточка пакетов: остаток, пакеты прайса с разрядами, галочка условий, карта и перевод, клиника в адресе",
           "Clinica are <b>30 SMS</b>" in card and "value='100' required> 100 SMS — 50 MDL" in card
           and "value='1000' required> 1 000 SMS — 450 MDL" in card and "name='terms'" in card
           and "action='/cont/sms/nota?c=c_1'" in card and "value='card'" in card and "value='transfer'" in card, card)
    res.ok("карточка пакетов без maib: только перевод",
           "value='card'" not in views._cont_sms_shop(clinic, shop, [], "", False)
           and "value='transfer'" in views._cont_sms_shop(clinic, shop, [], "", False))
    for code in ("sms_basic", "sms_off", "sms_plan"):
        closed = views._cont_sms_shop(clinic, dict(shop, closed=code), [], "", True)
        res.ok(f"карточка пакетов, {code}: слова кабинета вместо пакетов",
               views.cont_text(code)[:40] in closed.replace("&#x27;", "'") and "name='pack'" not in closed, closed)
    res.ok("карточка пакетов без IDNO: путь к реквизитам, пакетов нет",
           "href='#clinica'" in views._cont_sms_shop({"idno": ""}, shop, [], "", True)
           and "name='pack'" not in views._cont_sms_shop({"idno": ""}, shop, [], "", True))
    res.ok("карточка пакетов без прайса: «недоступны», формы нет",
           "name='pack'" not in views._cont_sms_shop(clinic, dict(shop, packs=[]), [], "", True)
           and "nu sunt disponibile" in views._cont_sms_shop(clinic, dict(shop, packs=[]), [], "", True))


def suite_cabinet(res: Result) -> None:
    """Покупка пакета из кабинета: перевод и карта, одно зачисление, второй платёж, отказы, филиал."""
    fake = FakeMaib()
    try:
        with Server(env={**ENV, **fake.env}) as s:
            c = _enter(s, DIRECTOR)
            main = _register(s, c)
            home = c.get("/cont")
            sms = _pane(home.body, "sms")
            res.ok("вкладка SMS: остаток, пакеты стенда, форма заказа — выше имени отправителя",
                   "SMS · sold și pachete" in sms and "Clinica are <b>0 SMS</b>" in sms
                   and "100 SMS — 50 MDL" in sms and "500 SMS — 200 MDL" in sms and "action='/cont/sms/nota'" in sms
                   and sms.index("sold și pachete") < sms.index("numele expeditorului"), sms[:2500])
            res.check("счётчик вкладки SMS пуст", _count(home.body, "sms"), "")
            res.check("без галочки условий — need_terms", c.post("/cont/sms/nota", pack="100").location,
                      "/cont?msg=need_terms")
            res.check("пакета не из прайса нет — sms_pack", c.post("/cont/sms/nota", pack="250", terms="1").location,
                      "/cont?msg=sms_pack")
            res.check("цена из формы не читается: лишнее поле не заводит ноту вне прайса",
                      c.post("/cont/sms/nota", pack="7", amount="1", terms="1").location, "/cont?msg=sms_pack")
            res.check("отказы ноты не завели", _notes(s, main), [])

            # перевод: нота, письмо, страница
            n0 = len(_letters(s))
            r = c.post("/cont/sms/nota", pack="100", method="transfer", terms="1")
            res.check("заказ переводом — sms_note_created", r.location, "/cont?msg=sms_note_created")
            notes = _notes(s, main)
            res.ok("нота вида sms: 100 штук, сумма из прайса стенда, ждёт, условия отмечены",
                   len(notes) == 1 and notes[0][1:4] == ("pending", 100, 50) and notes[0][5], repr(notes))
            ref = notes[0][0]
            letters = _letters(s)
            res.ok("письмо с нотой: одно, на ящик клиники, пакет и референция, страница оплаты, без слов про срок",
                   len(letters) == n0 + 1 and letters[-1][0] == DIRECTOR and ref in letters[-1][1]
                   and "100 SMS" in letters[-1][1] and "/plata/" in letters[-1][2] and mail.CARD_NOTE in letters[-1][2]
                   and mail.SMS_DONE["sms"] in letters[-1][2] and TERM not in letters[-1][2], letters[-1][:3])
            res.check("журнал: письмо с нотой sms", _sql(s, "SELECT count(*) FROM audit WHERE what='mail' AND "
                                                            "detail LIKE ?", f"нота sms {ref}%")[0][0], 1)
            home = c.get("/cont?msg=sms_note_created")
            sms, plati = _pane(home.body, "sms"), _pane(home.body, "plati")
            res.ok("вкладка SMS: ожидающая нота — карта за галочкой (ref) и реквизиты; другой пакет — за «Alt pachet?»",
                   ref in sms and f"name='ref' value='{ref}'" in sms and "name='terms'" in sms
                   and "MD00TEST0000000000000001" in sms and mail.SMS_DONE["sms"] in sms and TERM not in sms
                   and "<span class='lbl'>Pachet nou</span>" not in sms and "<summary>Alt pachet?</summary>" in sms
                   and f"Nota {ref} se anulează" in sms and "Înlocuiește nota de plată" in sms, sms[:3000])
            res.ok("вкладка оплат: нота SMS — строкой со ссылкой на вкладку SMS, без второй формы",
                   ref in plati and "href='#sms'" in plati and "name='ref'" not in plati, plati[-2500:])
            res.check("счётчик «ждёт вас» у SMS — 1", _count(home.body, "sms"), "1")
            res.ok("слово «нота создана» на странице", "pachetul SMS a fost creată" in home.body)
            res.check("второй заказ при открытой ноте — та же нота (sms_note_exists)",
                      c.post("/cont/sms/nota", pack="100", terms="1").location, "/cont?msg=sms_note_exists")
            res.check("нота одна, письмо второй раз не уходит", (len(_notes(s, main)), len(_letters(s))), (1, n0 + 1))
            # программа видит ту же ноту — одна логика на две двери
            st, data = _json(Client(s.url), "/v1/sms/order", _token_of(s, main), {"pack": 100})
            res.ok("заказ из программы при ноте кабинета: та же нота, не вторая",
                   st == 200 and data.get("reference") == ref and data.get("created") is False, repr((st, data)))

            # карта по ожидающей ноте: галочка, ссылка банка, callback и возврат браузера разом
            res.check("карта без галочки — need_terms", c.post("/cont/sms/nota", ref=ref, method="card").location,
                      "/cont?msg=need_terms")
            res.check("перевод по ref — нечего делать: no_card",
                      c.post("/cont/sms/nota", ref=ref, method="transfer", terms="1").location, "/cont?msg=no_card")
            r = c.post("/cont/sms/nota", ref=ref, method="card", terms="1")
            pid, url = _sql(s, "SELECT provider_id, pay_url FROM payments WHERE reference=?", ref)[0]
            res.ok("«Plătește cu cardul»: ссылка банка родилась сейчас, браузер на неё",
                   r.status == 303 and r.location == url and pid in fake.pays, f"{r.status} {r.location}")
            res.ok("банку ушли сумма ноты и её предмет",
                   fake.pays[pid]["body"]["amount"] == 50
                   and "100 SMS" in (fake.pays[pid]["body"].get("orderInfo") or {}).get("description", ""),
                   repr(fake.pays[pid]["body"]))
            fake.set_status(pid, "Completed")
            n1 = len(_letters(s))
            bank, browser = Client(s.url), Client(s.url)
            cb, ok = _together(lambda: fake.post(bank, pid),
                               lambda: browser.get(f"/pay/ok?checkoutId={pid}&checkoutStatus=Completed&orderId={ref}"))
            res.ok("callback и /pay/ok разом: оба 200, исход paid или already",
                   getattr(cb, "status", None) == 200 and json.loads(cb.body).get("outcome") in ("paid", "already")
                   and getattr(ok, "status", None) == 200, f"{cb!r} {ok!r}")
            res.ok("страница возврата: «plătită», пакет, «SMS-urile se adaugă automat», без слов про срок",
                   "plătită" in ok.body and "Pachet 100 SMS" in ok.body and mail.SMS_DONE["sms"] in ok.body
                   and TERM not in ok.body, ok.body[-1500:])
            res.check("зачисление ОДНО: одна строка pack на 100", _packs_of(s, main), [(100,)])
            res.check("нота одна и оплачена картой", [(x[1], x[4]) for x in _notes(s, main)], [("paid", "card")])
            res.check("cont de plată — одна строка", _sql(s, "SELECT count(*) FROM receipts r JOIN payments p ON "
                                                            "p.id = r.payment_id WHERE p.reference=?", ref)[0][0], 1)
            res.check("журнал: один payment_paid и один sms_pack",
                      _sql(s, "SELECT what, count(*) FROM audit WHERE clinic_id=? AND what IN ('payment_paid', "
                              "'sms_pack') GROUP BY what ORDER BY what", main), [("payment_paid", 1), ("sms_pack", 1)])
            letters = _letters(s)
            res.ok("письмо после оплаты: одно, «a fost activat», cont de plată вложением",
                   len(letters) == n1 + 1 and "pachetul de 100 SMS a fost activat" in letters[-1][1]
                   and any((f or "").endswith(".pdf") for f in letters[-1][3]), repr([x[1] for x in letters[n1:]]))
            res.ok("повторный callback — already, второй строки pack нет",
                   json.loads(fake.post(bank, pid).body).get("outcome") == "already" and _packs_of(s, main) == [(100,)])
            home = c.get("/cont")
            sms = _pane(home.body, "sms")
            res.ok("вкладка SMS после оплаты: остаток вырос (30 пробных + 100), пакеты снова в продаже, счётчик пуст",
                   "Clinica are <b>130 SMS</b>" in sms and "name='pack'" in sms and "name='ref'" not in sms
                   and _count(home.body, "sms") == "", sms[:1500])
            res.ok("в таблице нот оплаченная нота SMS — с документом и своим предметом, не «0 luni»",
                   f"/cont/plati/{ref}.pdf" in _pane(home.body, "plati") and "<td>pachet 100 SMS</td>" in
                   _pane(home.body, "plati") and "0 luni" not in home.body)
            res.check("в логе сервера ни «database is locked», ни трейсбека",
                      [x for x in ("database is locked", "Traceback") if x in s.log()], [])

            # заказ сразу картой: нота, письмо с ней и страница банка — одним кликом
            n2 = len(_letters(s))
            r = c.post("/cont/sms/nota", pack="500", method="card", terms="1")
            ref2, pid2, url2 = _sql(s, "SELECT reference, provider_id, pay_url FROM payments WHERE clinic_id=? AND "
                                       "kind='sms' AND status='pending'", main)[0]
            res.ok("заказ картой: нота на 500, письмо с нотой ушло, браузер на страницу банка",
                   r.status == 303 and r.location == url2 and len(_letters(s)) == n2 + 1
                   and ref2 in _letters(s)[-1][1] and fake.pays[pid2]["body"]["amount"] == 200, f"{r.location}")
            # второй платёж по закрытой ноте: перевод подтверждён, потом прошла карта — второй пакет
            admin = Client(s.url).login()
            nid = _sql(s, "SELECT id FROM payments WHERE reference=?", ref2)[0][0]
            admin.post(f"/admin/payments/{nid}/confirm")
            res.check("нота закрыта переводом: +500", _packs_of(s, main), [(100,), (500,)])
            fake.set_status(pid2, "Completed")
            r = fake.post(bank, pid2)
            res.ok("карта по закрытой ноте: зачтена вторым пакетом (paid), новой строкой с новым номером",
                   json.loads(r.body).get("outcome") == "paid" and _packs_of(s, main) == [(100,), (500,), (500,)]
                   and [x[1] for x in _notes(s, main)] == ["paid", "paid", "paid"]
                   and len({x[0] for x in _notes(s, main)}) == 3, f"{r.body} {_notes(s, main)}")
            res.check("журнал: payment_repeat один", _sql(s, "SELECT count(*) FROM audit WHERE what='payment_repeat' "
                                                              "AND clinic_id=?", main)[0][0], 1)
            res.ok("тот же callback ещё раз — already, третьего пакета на 500 нет",
                   json.loads(fake.post(bank, pid2).body).get("outcome") == "already"
                   and _packs_of(s, main) == [(100,), (500,), (500,)])

            # callback не дошёл и браузер не вернулся — ноту SMS подбирает задача
            r = c.post("/cont/sms/nota", pack="100", method="card", terms="1")
            pid3 = _sql(s, "SELECT provider_id FROM payments WHERE clinic_id=? AND kind='sms' AND status='pending'",
                        main)[0][0]
            fake.set_status(pid3, "Completed")
            code, out = _run(s, datetime.now(timezone.utc).date())
            res.ok("задача спросила банк и зачла пакет: +100, один раз",
                   code == 0 and _packs_of(s, main) == [(100,), (500,), (500,), (100,)], out[-600:])
            _run(s, datetime.now(timezone.utc).date())
            res.check("второй проход задачи ничего не прибавляет", len(_packs_of(s, main)), 4)

            # банк уже сказал «оплачено», а клиника жмёт карту ещё раз — слова без срока
            r = c.post("/cont/sms/nota", pack="100", method="card", terms="1")
            ref4, pid4 = _sql(s, "SELECT reference, provider_id FROM payments WHERE clinic_id=? AND kind='sms' AND "
                                 "status='pending'", main)[0]
            fake.set_status(pid4, "Completed")
            r = c.post("/cont/sms/nota", ref=ref4, method="card", terms="1")
            res.check("клик по уже оплаченной у банка ноте — sms_card_paid", r.location, "/cont?msg=sms_card_paid")
            said = c.get(r.location).body
            res.ok("слово кабинета: SMS прибавляются, про срок ни слова",
                   "SMS-urile se adaugă automat" in said and "termenul se prelungește" not in
                   said[said.index("class='banner"):said.index("class='banner") + 400], said[:200])
            res.check("и зачтена она один раз", len(_packs_of(s, main)), 5)

            # филиал: свой остаток, свой пакет; чужая нота из формы главной не оплачивается
            _add(c, main)
            bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
            sms_b = _pane(c.get(f"/cont?c={bid}").body, "sms")
            res.ok("филиал во вкладке SMS: свой остаток (0), форма несёт клинику (?c=)",
                   "Clinica are <b>0 SMS</b>" in sms_b and f"action='/cont/sms/nota?c={bid}'" in sms_b, sms_b[:1500])
            res.check("форма без ?c= у кабинета с двумя клиниками — pick_clinic, ноты нет",
                      (c.post("/cont/sms/nota", pack="100", terms="1").location, _notes(s, bid)),
                      ("/cont?msg=pick_clinic", []))
            r = c.post(f"/cont/sms/nota?c={bid}", pack="100", terms="1")
            res.check("пакет филиалу — его нота", (r.location, len(_notes(s, bid))),
                      (f"/cont?c={bid}&msg=sms_note_created", 1))
            ref_b = _notes(s, bid)[0][0]
            res.check("⛔ нота филиала из формы главной — note_gone, у банка платежа нет",
                      (c.post(f"/cont/sms/nota?c={main}", ref=ref_b, method="card", terms="1").location,
                       _sql(s, "SELECT provider_id FROM payments WHERE reference=?", ref_b)[0][0]),
                      (f"/cont?c={main}&msg=note_gone", None))
            # вход кнопкой программы филиала: вкладка SMS с пакетами есть, имени кабинета нет
            _, link = _cont_link(Client(s.url), _token_of(s, bid))
            b = Client(s.url)
            _open(b, link)
            home_b = b.get("/cont")
            sms_b = _pane(home_b.body, "sms")
            res.ok("кнопка программы филиала: во вкладке SMS пакеты и своя нота, имени отправителя кабинета нет",
                   "SMS · sold și pachete" in sms_b and ref_b in sms_b and f"name='ref' value='{ref_b}'" in sms_b
                   and "numele expeditorului" not in sms_b and MAIN["name"] not in home_b.body, sms_b[:2000])
            r = b.post("/cont/sms/nota", ref=ref_b, method="card", terms="1")
            res.ok("кнопка программы: карта своей ноты — на страницу банка",
                   r.status == 303 and r.location.startswith("https://") and "msg=" not in r.location, r.location)
            res.check("⛔ кнопка программы: ?c=главная — pick_clinic",
                      b.post(f"/cont/sms/nota?c={main}", pack="100", terms="1").location, "/cont?msg=pick_clinic")

            # кому не продаётся: Basic (модуль погашен) и клиника без IDNO
            before = len(_notes(s, bid))
            _sql(s, "UPDATE subscriptions SET plan='standard', tier='basic', sms_until=NULL WHERE clinic_id=?", bid)
            sms_b = _pane(c.get(f"/cont?c={bid}").body, "sms")
            res.ok("Basic при открытой ноте: нота остаётся с оплатой (остаток не пропадёт), пакетов нет",
                   f"name='ref' value='{ref_b}'" in sms_b and "name='pack'" not in sms_b, sms_b[:2000])
            _sql(s, "UPDATE payments SET status='rejected' WHERE reference=?", ref_b)
            sms_b = _pane(c.get(f"/cont?c={bid}").body, "sms")
            res.ok("Basic: вместо пакетов — путь к Plus",
                   "face parte din DentPilot Plus" in sms_b and "name='pack'" not in sms_b and ref_b not in sms_b,
                   sms_b[:2000])
            res.check("Basic: заказ — sms_basic, ноты нет",
                      (c.post(f"/cont/sms/nota?c={bid}", pack="100", terms="1").location, len(_notes(s, bid))),
                      (f"/cont?c={bid}&msg=sms_basic", before))
            _sql(s, "UPDATE subscriptions SET tier='plus' WHERE clinic_id=?", bid)
            _sql(s, "UPDATE clinics SET idno='' WHERE id=?", bid)
            sms_b = _pane(c.get(f"/cont?c={bid}").body, "sms")
            res.ok("без IDNO: путь к реквизитам, пакетов нет", "href='#clinica'" in sms_b and "name='pack'" not in sms_b)
            res.check("без IDNO: заказ — sms_need_idno",
                      c.post(f"/cont/sms/nota?c={bid}", pack="100", terms="1").location, f"/cont?c={bid}&msg=sms_need_idno")
            res.check("без входа — на вход", Client(s.url).post("/cont/sms/nota", pack="100", terms="1").location,
                      "/cont/login")
    finally:
        fake.close()

    # без maib: карты нет нигде, перевод работает
    with Server(env=ENV) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        sms = _pane(c.get("/cont").body, "sms")
        res.ok("без maib: в форме пакетов только перевод", "value='card'" not in sms and "value='transfer'" in sms)
        r = c.post("/cont/sms/nota", pack="100", method="card", terms="1")
        res.check("без maib «карта» из формы — обычная нота переводом", r.location, "/cont?msg=sms_note_created")
        sms = _pane(c.get("/cont").body, "sms")
        res.ok("без maib: у ноты реквизиты, кнопки карты нет; в письме страницы оплаты нет",
               "MD00TEST0000000000000001" in sms and "name='ref'" not in sms and "/plata/" not in _letters(s)[-1][2])


def suite_replace(res: Result) -> None:
    """Другой пакет при открытой ноте — замена, как у абонемента (payments.choose): долг один, письмо
    с новой нотой уходит, а оплата по прежней странице банка не теряется — зачитывается её пакетом."""
    fake = FakeMaib()
    try:
        with Server(env={**ENV, **fake.env}) as s:
            c = _enter(s, DIRECTOR)
            main = _register(s, c)

            def rows() -> list:
                return _sql(s, "SELECT reference, status, sms_units FROM payments WHERE clinic_id=? AND kind='sms' "
                               "ORDER BY id", main)

            c.post("/cont/sms/nota", pack="100", method="card", terms="1")
            ref_a, pid_a = _sql(s, "SELECT reference, provider_id FROM payments WHERE clinic_id=? AND kind='sms'", main)[0]
            n = len(_letters(s))
            r = c.post("/cont/sms/nota", pack="500", method="transfer", terms="1")
            res.check("другой пакет при открытой ноте — sms_note_replaced", r.location, "/cont?msg=sms_note_replaced")
            got = rows()
            res.ok("прежняя нота отклонена, новая на 500 ждёт — долг один",
                   len(got) == 2 and got[0] == (ref_a, "rejected", 100) and got[1][1:] == ("pending", 500), repr(got))
            ref_b = got[1][0]
            letters = _letters(s)
            res.ok("письмо с новой нотой ушло: её номер и пакет",
                   len(letters) == n + 1 and ref_b in letters[-1][1] and "500 SMS" in letters[-1][1], letters[-1][1])
            res.ok("журнал: прежняя нота — «заменена», кем и на какой пакет",
                   _sql(s, "SELECT who, detail FROM audit WHERE what='payment_rejected' AND clinic_id=?", main)
                   == [(DIRECTOR, f"{ref_a}: заменена: клиника выбрала пакет 500 SMS")])
            home = c.get(r.location)
            sms = _pane(home.body, "sms")
            res.ok("вкладка SMS: платится новая нота, прежней среди ожидающих нет, слово «заменена» на странице",
                   f"name='ref' value='{ref_b}'" in sms and ref_a not in sms and "a fost înlocuită" in home.body
                   and _count(home.body, "sms") == "1", sms[:2500])
            res.check("тот же пакет ещё раз — та же нота, письма нет",
                      (c.post("/cont/sms/nota", pack="500", terms="1").location, len(rows()), len(_letters(s))),
                      ("/cont?msg=sms_note_exists", 2, n + 1))
            # из программы — то же правило: другой пакет заменяет, письмо уходит, программа получает новую ноту
            st, data = _json(Client(s.url), "/v1/sms/order", _token_of(s, main), {"pack": 100})
            ref_c = data.get("reference", "")
            res.ok("заказ другого пакета из программы: новая нота (created), прежняя отклонена, письмо ушло",
                   st == 200 and data.get("created") is True and data.get("units") == 100 and ref_c not in (ref_a, ref_b)
                   and [x[1] for x in rows()] == ["rejected", "rejected", "pending"] and len(_letters(s)) == n + 2,
                   repr((st, data, rows())))
            # клиника всё же заплатила на ПРЕЖНЕЙ странице банка (открытая вкладка): деньги не теряются
            fake.set_status(pid_a, "Completed")
            r = fake.post(Client(s.url), pid_a)
            got = rows()
            res.ok("оплата по прежней ноте после замены: зачтена её пакетом новой строкой, новая нота ждёт дальше",
                   json.loads(r.body).get("outcome") == "paid" and _packs_of(s, main) == [(100,)]
                   and [x[1] for x in got] == ["rejected", "rejected", "pending", "paid"] and got[2][0] == ref_c,
                   f"{r.body} {got}")
            res.ok("повтор того же callback — already, второго пакета нет",
                   json.loads(fake.post(Client(s.url), pid_a).body).get("outcome") == "already"
                   and _packs_of(s, main) == [(100,)])
    finally:
        fake.close()


def suite_name(res: Result) -> None:
    """Год своего имени отправителя — той же дверью кабинета, что пакет: имя общее на кабинет, нота —
    главной клинике; филиалу из кнопки программы имя не открыто."""
    fake = FakeMaib()
    try:
        with Server(env={**ENV, **fake.env, "DP_SMS_NAME_PRICE": "77"}) as s:
            c = _enter(s, DIRECTOR)
            main = _register(s, c)

            def names() -> list:
                return _sql(s, "SELECT reference, clinic_id, status, amount, terms_at FROM payments "
                               "WHERE kind='sms_name' ORDER BY id")

            sms = _pane(c.get("/cont").body, "sms")
            res.ok("имени ещё нет: года имени не предлагают, подсказка называет обе двери",
                   "pe un an" not in sms and "name='name' value='1'" not in sms and "aici sau din program" in sms, sms[-2500:])
            res.check("год имени без заявки на имя — sms_name_none",
                      c.post("/cont/sms/nota", name="1", terms="1").location, "/cont?msg=sms_name_none")
            c.post("/cont/sms/nume", name="Zambet")
            home = c.get("/cont")
            sms = _pane(home.body, "sms")
            res.ok("имя запрошено: год имени — цена прайса стенда, галочка условий, карта и перевод",
                   "Numele propriu se plătește pe un an: 77 MDL." in sms and "name='name' value='1'" in sms
                   and sms.index("numele expeditorului") < sms.index("name='name' value='1'")
                   and sms.count("name='terms'") == 2, sms[-3000:])
            res.check("счётчик SMS: заявление не загружено — 1", _count(home.body, "sms"), "1")
            res.check("без галочки — need_terms", c.post("/cont/sms/nota", name="1").location, "/cont?msg=need_terms")
            n = len(_letters(s))
            r = c.post("/cont/sms/nota", name="1", method="transfer", terms="1")
            res.check("заказ года имени — sms_name_note_created", r.location, "/cont?msg=sms_name_note_created")
            got = names()
            res.ok("нота вида sms_name у главной: цена прайса, ждёт, условия отмечены",
                   len(got) == 1 and got[0][1:4] == (main, "pending", 77) and got[0][4], repr(got))
            ref = got[0][0]
            letters = _letters(s)
            res.ok("письмо с нотой за имя: номер, имя, страница оплаты, без слов про срок",
                   len(letters) == n + 1 and ref in letters[-1][1] and "Zambet" in letters[-1][1]
                   and "/plata/" in letters[-1][2] and mail.SMS_DONE["sms_name"] in letters[-1][2]
                   and TERM not in letters[-1][2], letters[-1][:3])
            home = c.get(r.location)
            sms = _pane(home.body, "sms")
            res.ok("карточка имени: ожидающая нота с картой за галочкой и реквизитами; слово о ноте на странице",
                   f"name='ref' value='{ref}'" in sms and "nume de expeditor SMS, un an" in sms
                   and "MD00TEST0000000000000001" in sms and "name='name' value='1'" not in sms
                   and "numele de expeditor a fost creată" in home.body, sms[-3000:])
            res.check("счётчик SMS: заявление и нота — 2", _count(home.body, "sms"), "2")
            res.check("второй заказ — та же нота (sms_name_note_exists)",
                      (c.post("/cont/sms/nota", name="1", terms="1").location, len(names()), len(_letters(s))),
                      ("/cont?msg=sms_name_note_exists", 1, n + 1))
            st, data = _json(Client(s.url), "/v1/sms/order", _token_of(s, main), {"name": 1})
            res.ok("заказ из программы при ноте кабинета: та же нота",
                   st == 200 and data.get("reference") == ref and data.get("created") is False
                   and data.get("kind") == "sms_name", repr((st, data)))

            # филиал: имя общее — заказ и оплата из его вида идут главной клинике
            _add(c, main)
            bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
            sms_b = _pane(c.get(f"/cont?c={bid}").body, "sms")
            res.ok("вид филиала: нота имени главной клиники — с оплатой, форма несёт филиал (?c=)",
                   f"name='ref' value='{ref}'" in sms_b and f"action='/cont/sms/nota?c={bid}'" in sms_b
                   and MAIN["name"] in sms_b, sms_b[-3000:])
            r = c.post(f"/cont/sms/nota?c={bid}", ref=ref, method="card", terms="1")
            pid = _sql(s, "SELECT provider_id FROM payments WHERE reference=?", ref)[0][0]
            res.ok("карта ноты имени из вида филиала: на страницу банка, плательщик — главная",
                   r.status == 303 and pid in fake.pays
                   and MAIN["name"] in (fake.pays[pid]["body"].get("orderInfo") or {}).get("description", ""),
                   f"{r.status} {r.location}")
            # кнопка программы филиала: имени нет ни в карточке, ни в маршруте
            _, link = _cont_link(Client(s.url), _token_of(s, bid))
            b = Client(s.url)
            _open(b, link)
            res.ok("⛔ кнопка программы филиала: ни карточки имени, ни ноты имени главной",
                   ref not in b.get("/cont").body and "numele expeditorului" not in _pane(b.get("/cont").body, "sms"))
            res.check("⛔ кнопка программы филиала: заказ года имени — sms_not_offered",
                      (b.post("/cont/sms/nota", name="1", terms="1").location, len(names())),
                      ("/cont?msg=sms_not_offered", 1))
            res.check("⛔ кнопка программы филиала: карта ноты имени главной — note_gone",
                      b.post("/cont/sms/nota", ref=ref, method="card", terms="1").location, "/cont?msg=note_gone")

            # оплата: имя ещё не одобрено — год ждёт одобрения; письмо, документ, страница возврата
            fake.set_status(pid, "Completed")
            n = len(_letters(s))
            r = fake.post(Client(s.url), pid)
            res.ok("callback: нота имени оплачена, год ждёт одобрения (prepaid), документ один",
                   json.loads(r.body).get("outcome") == "paid" and names()[0][2] == "paid"
                   and _sql(s, "SELECT sender_prepaid FROM sms_accounts WHERE clinic_id=?", main) == [(1,)]
                   and _sql(s, "SELECT count(*) FROM receipts r JOIN payments p ON p.id = r.payment_id "
                               "WHERE p.reference=?", ref)[0][0] == 1, f"{r.body} {names()}")
            res.ok("письмо «este plătit» ушло главной клинике",
                   len(_letters(s)) == n + 1 and "este plătit" in _letters(s)[-1][1] and _letters(s)[-1][0] == DIRECTOR)
            ok = Client(s.url).get(f"/pay/ok?checkoutId={pid}&checkoutStatus=Completed&orderId={ref}")
            res.ok("страница возврата: «plătită», имя на год, без слов про срок",
                   "plătită" in ok.body and "Nume de expeditor SMS, un an" in ok.body and TERM not in ok.body,
                   ok.body[-1200:])
            home = c.get("/cont")
            res.ok("после оплаты: год имени снова можно заказать (следующий), счётчик — одно заявление",
                   "name='name' value='1'" in _pane(home.body, "sms") and _count(home.body, "sms") == "1")
    finally:
        fake.close()

    # цены имени нет — года имени в кабинете нет
    with Server(env=ENV) as s:
        c = _enter(s, DIRECTOR)
        _register(s, c)
        c.post("/cont/sms/nume", name="Zambet")
        res.ok("без DP_SMS_NAME_PRICE блока года имени нет", "pe un an" not in _pane(c.get("/cont").body, "sms"))
        res.check("и заказ — sms_no_name", c.post("/cont/sms/nota", name="1", terms="1").location,
                  "/cont?msg=sms_no_name")


def suite_plata(res: Result) -> None:
    """Страница оплаты: ожидающая нота SMS — первой и под своим заголовком."""
    fake = FakeMaib()
    try:
        with Server(env={**ENV, **fake.env}) as s:
            admin = Client(s.url).login()
            cid = cid_from(admin.post("/admin/clinics", name="Clinica Pachet", idno="7777777777777",
                                      email="pachet@example.md").location)
            admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
            anon = Client(s.url)
            tok = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]
            path = "/plata/" + _pay_link(anon, tok)[1].rsplit("/", 1)[1]
            page = anon.get(path).body
            res.ok("без ноты SMS страница — как была: «Plata abonamentului», одна карточка",
                   "<h1>Plata abonamentului</h1>" in page and "name='ref'" not in page)
            st, data = _json(anon, "/v1/sms/order", tok, {"pack": 100})
            ref = data.get("reference", "")
            page = anon.get(path).body
            res.ok("нота SMS — первой: её карточка выше карточки абонемента, заголовок страницы общий",
                   st == 200 and "<h1>Plata online</h1>" in page and "Plata abonamentului" not in page
                   and 0 < page.index("Pachet 100 SMS") < page.index("abonament DentPilot")
                   and page.index(f"name='ref' value='{ref}'") < page.index("name='tier'"), page[-3000:])
            head = page[page.index("Pachet 100 SMS") - 200:page.index("Pachet 100 SMS") + 200]
            res.ok("свой заголовок карточки: что оплачивается — заголовком, номер ноты — подписью",
                   "<h2>Pachet 100 SMS</h2>" in head and f"nota de plată {ref}" in head, head)
            sms_card = page[page.index("Pachet 100 SMS"):page.index("abonament DentPilot")]
            res.ok("блок реквизитов ноты SMS: без слов про срок, «SMS-urile se adaugă automat»",
                   TERM not in sms_card and mail.SMS_DONE["sms"] in sms_card, sms_card[-1200:])
            res.check("нота из программы заведена без галочки: terms_at пуст",
                      _sql(s, "SELECT terms_at FROM payments WHERE reference=?", ref)[0][0], None)
            r = anon.post(path, ref=ref, method="card", terms="1")
            pid, at = _sql(s, "SELECT provider_id, terms_at FROM payments WHERE reference=?", ref)[0]
            res.ok("карта ноты SMS со страницы оплаты — как раньше, на страницу банка", r.status == 303 and pid in fake.pays)
            res.ok("галочка перед оплатой ноты SMS: время — в её terms_at, акт source=pay — рядом",
                   bool(at) and _sql(s, "SELECT count(*) FROM terms_acceptances WHERE clinic_id=? AND source='pay'",
                                     cid)[0][0] == 1, repr(at))
            anon.post(path, ref=ref, method="card", terms="1")
            res.check("второй клик отмеченное время не переписывает",
                      _sql(s, "SELECT terms_at FROM payments WHERE reference=?", ref)[0][0], at)
            fake.set_status(pid, "Completed")
            res.check("банк уже сказал «оплачено», клик ещё раз — sms_card_paid",
                      anon.post(path, ref=ref, method="card", terms="1").location, f"{path}?msg=sms_card_paid")
            page = anon.get(f"{path}?msg=sms_card_paid").body
            res.ok("после оплаты нота SMS со страницы ушла, страница снова про абонемент",
                   "<h1>Plata abonamentului</h1>" in page and "Pachet 100 SMS" not in page
                   and "SMS-urile se adaugă automat" in page)
    finally:
        fake.close()
