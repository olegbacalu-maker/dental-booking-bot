"""Путь «своё имя отправителя SMS» целиком: заявка → заявление → оплата года → одобрение → конец года.

Что держит набор:
- оплата года — шаг списка кабинета, баннер после загрузки заявления называет её; оплаченный до
  одобрения год виден и второй раз не продаётся ни кабинетом, ни программой;
- без реквизитов клиники кабинет сначала называет, чего нет, а шагов и поля загрузки не даёт;
- поставщику уходит письмо о заявке (кабинет и программа) и о загруженном заявлении; клинике — об
  одобрении (с оплаченным годом и без него) и об отказе с причиной;
- одобренное имя без оплаченного года и имя, чей год кончился, названы словами в кабинете и в
  админке; за две недели до конца года и в день конца клинике уходит по одному письму;
- отказ sms.md клиника читает по-румынски; подтверждение ноты имени в админке говорит про имя;
- филиал видит имя кабинета без кнопок заявки и оплаты.

⛔ Цена имени здесь — подмена `DP_SMS_NAME_PRICE` стенда; настоящих цен в репозитории нет.
"""
import sys
from datetime import datetime, timedelta, timezone

from harness import CLOUD, Client, Result, Server

sys.path.insert(0, str(CLOUD))
from app import db, sms  # noqa: E402
from test_branches import BRANCH, DIRECTOR, MAIN, _add, _enter, _register  # noqa: E402
from test_sms import FakeSmsMd, Program, _clinic_with_license, _letters, _one, _run_daily, _sql  # noqa: E402
from test_sms_cabinet import ENV, _count, _pane  # noqa: E402
from test_sms_paper import _cabinet, _msg, _upload  # noqa: E402

OLEG = "oleg@example.md"          # FakeSmsMd.env: DP_TRIAL_NOTIFY
PDF = b"%PDF-1.7\n% semnat\n%%EOF\n"
DATA = dict(idno="1234567890122", contact_name="Ion Popescu", phone="+373 299 12 345",
            address="or. Cahul, str. Stefan cel Mare 12")


def _to(s: Server, who: str) -> list:
    return [x for x in _letters(s) if x[0] == who]


def _until(s: Server, cid: str, days: float) -> None:
    at = (datetime.now(timezone.utc) + timedelta(days=days)).strftime(db.TS)
    _sql(s, "UPDATE sms_accounts SET sender_until=? WHERE clinic_id=?", at, cid)


def suite_path(res: Result) -> None:
    """Одна клиника от заявки до конца года и отказа sms.md."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s, "Zambet Dent", "zd@example.md")
            cab = _cabinet(s, "zd@example.md")

            # заявка без реквизитов: чего нет — первым, шагов и загрузки нет; письмо поставщику
            res.check("заявка без адреса и телефона — слова про данные клиники",
                      _msg(cab.post("/cont/sms/nume", name="Zambet Dent")), "sms_requested_data")
            got = _to(s, OLEG)
            res.ok("поставщику — письмо о заявке: имя, клиника, год не оплачен, ссылка на карточку",
                   len(got) == 1 and "заявка на имя SMS «Zambet Dent»" in got[0][1] and "Zambet Dent" in got[0][2]
                   and "НЕ оплачен" in got[0][2] and f"/admin/clinics/{cid}#sms" in got[0][2], repr(got))
            pane = _pane(cab.get("/cont").body, "sms")
            res.ok("нет реквизитов: названо, чего нет, со ссылкой на «Clinica»; ни шагов, ни поля загрузки",
                   "Pentru cerere lipsesc datele clinicii: adresa, telefonul." in pane
                   and "<a href='#clinica'>Clinica</a>" in pane and "multipart/form-data" not in pane
                   and "Descarcă cererea" not in pane and "<ol class='steps'>" not in pane, pane[-3000:])
            res.check("повтор той же заявки письма поставщику не шлёт",
                      (_msg(cab.post("/cont/sms/nume", name="Zambet Dent")), len(_to(s, OLEG))),
                      ("sms_requested_data", 1))

            # реквизиты есть: пять шагов, оплата — четвёртым
            cab.post("/cont/date", name="Zambet Dent", **DATA)
            pane = _pane(cab.get("/cont").body, "sms")
            order = [pane.find(x) for x in ("Descărcați cererea completată", "Semnați-o", "Încărcați cererea semnată",
                                            "<b>Plătiți anul numelui</b>", "<b>O depunem la SMS.MD</b>")]
            res.ok("шаги: скачать, подписать, загрузить, оплатить год, подача — в этом порядке",
                   -1 not in order and order == sorted(order) and pane.count("<li>") >= 5
                   and "Fără plată, numele aprobat nu se folosește" in pane, f"{order} {pane[-3000:]}")

            # заявление загружено, год не оплачен: баннер называет оплату; письмо поставщику
            r = _upload(cab, PDF)
            res.check("загрузка при неоплаченном годе — sms_paper_pay", _msg(r), "sms_paper_pay")
            res.ok("баннер после загрузки называет оплату года",
                   "Mai rămâne plata anului numelui" in cab.get(r.location).body)
            got = _to(s, OLEG)
            res.ok("поставщику — письмо о загруженном заявлении",
                   len(got) == 2 and "заявление на имя SMS загружено «Zambet Dent»" in got[1][1]
                   and "Заявление клиники (PDF)" in got[1][2], repr(got[1:]))
            res.ok("очередь имён и карточка: год имени не оплачен — заметной меткой, до «Подано»",
                   "<span class='tag bad'>год имени не оплачен</span>" in admin.get("/admin/sms").body
                   and "<span class='tag bad'>год имени не оплачен</span>" in admin.get(f"/admin/clinics/{cid}").body
                   and "одобренное без оплаты имя не работает" in admin.get(f"/admin/clinics/{cid}").body)

            # заказ года переводом; подтверждение в админке — своими словами
            res.check("заказ года имени", _msg(cab.post("/cont/sms/nota", name="1", method="transfer", terms="1")),
                      "sms_name_note_created")
            ref, pid = _sql(s, "SELECT reference, id FROM payments WHERE kind='sms_name'")[0]
            res.ok("шаг оплаты называет ожидающую ноту",
                   f"nota de plată {ref} este în așteptare" in _pane(cab.get("/cont").body, "sms"))
            r = admin.post(f"/admin/payments/{pid}/confirm")
            page = admin.get(r.location).body
            res.ok("подтверждение ноты имени: слова про год имени, не про срок и файл",
                   r.location.endswith("msg=payment_confirmed_name_mailed") and "год имени отправителя оплачен" in page
                   and "срок продлён" not in page, f"{r.location}")

            # оплачено до одобрения: видно, формы нет, второй ноты не выставить
            home = cab.get("/cont")
            pane = _pane(home.body, "sms")
            res.ok("год оплачен до одобрения: сказано в шаге и под шагами, формы оплаты нет",
                   pane.count("Anul este plătit; se numără din ziua aprobării.") == 2
                   and "name='name' value='1'" not in pane and "pe un an:" not in pane, pane[-3000:])
            res.check("кабинет: второй заказ года — sms_name_paid",
                      (_msg(cab.post("/cont/sms/nota", name="1", method="transfer", terms="1")),
                       _one(s, "SELECT count(*) FROM payments WHERE kind='sms_name'")), ("sms_name_paid", 1))
            st, data = Program(s.url, token).post("/v1/sms/order", name=1)
            res.check("программа: второй заказ года — 409 sms_name_paid словами",
                      (st, data.get("code"), data.get("text")),
                      (409, "sms_name_paid", sms.CODES["sms_name_paid"][1]))
            res.check("повторная загрузка при оплаченном годе — sms_paper_ok", _msg(_upload(cab, PDF)), "sms_paper_ok")
            res.ok("очередь имён: оплачено лет: 1", "оплачено лет: 1" in admin.get("/admin/sms").body)

            # одобрение: письмо клинике с датой, форма продления — за кнопкой
            admin.post(f"/admin/clinics/{cid}/sms", action="submitted")
            fake.aliases["Zambet Dent"] = 1
            n = len(_to(s, "zd@example.md"))
            admin.post("/admin/sms/sync")
            mine = _to(s, "zd@example.md")
            until = _one(s, "SELECT sender_until FROM sms_accounts WHERE clinic_id=?", cid)
            ro = f"{until[8:10]}.{until[5:7]}.{until[:4]}"
            res.ok("клинике — письмо об одобрении: имя и до какого дня оплачен год",
                   len(mine) == n + 1 and "«Zambet Dent» a fost aprobat" in mine[-1][1]
                   and f"valabil până la {ro}" in mine[-1][2] and "pleacă de la «Zambet Dent»" in mine[-1][2],
                   repr(mine[-1:]))
            pane = _pane(cab.get("/cont").body, "sms")
            res.ok("одобрено и оплачено: «aprobat, achitat până la», продление — за кнопкой",
                   f"achitat până la {ro}" in pane and "<summary>Prelungește numele cu încă un an</summary>" in pane
                   and "acum SMS-urile pleacă de la «Zambet Dent»" in pane, pane[-3000:])
            admin.post("/admin/sms/sync")
            res.check("повторная сверка второго письма не шлёт", len(_to(s, "zd@example.md")), n + 1)

            # за две недели до конца: одно письмо, повтор задачи молчит
            _until(s, cid, 10)
            n = len(_to(s, "zd@example.md"))
            code, out = _run_daily(s)
            mine = _to(s, "zd@example.md")
            res.ok("за 10 дней до конца года — письмо «se încheie la»",
                   code == 0 and len(mine) == n + 1 and "se încheie la" in mine[-1][1]
                   and "pleacă de la «DentPilot»" in mine[-1][2] and "писем о годе имени 1" in out, out[-600:])
            _run_daily(s)
            res.check("второй проход того же дня — без письма; отметка одна",
                      (len(_to(s, "zd@example.md")),
                       _one(s, "SELECT count(*) FROM reminders WHERE subscription_id=? AND kind='sms_name_soon'", cid)),
                      (n + 1, 1))

            # год кончился: письмо, кабинет и админка говорят это словами
            _until(s, cid, -1)
            code, out = _run_daily(s)
            mine = _to(s, "zd@example.md")
            res.ok("год кончился — письмо «s-a încheiat», один раз",
                   len(mine) == n + 2 and "s-a încheiat" in mine[-1][1] and "Numele rămâne aprobat" in mine[-1][2],
                   out[-600:])
            _run_daily(s)
            res.check("повтор — без письма", len(_to(s, "zd@example.md")), n + 2)
            pane = _pane(cab.get("/cont").body, "sms")
            res.ok("кабинет: «anul s-a încheiat» вместо зелёного «aprobat, achitat până la», продление открыто",
                   "<span class='tag warn'>anul s-a încheiat</span>" in pane and "achitat până la" not in pane
                   and "SMS-urile pleacă de la «DentPilot»" in pane and "Prelungiți numele cu un an: 77 MDL." in pane
                   and "name='name' value='1'" in pane and "<summary>Prelungește" not in pane, pane[-3000:])
            card = admin.get(f"/admin/clinics/{cid}").body
            names = admin.get("/admin/sms").body
            res.ok("админка: год имени кончился — в карточке, в «Ждёт вас» и списком во вкладке имён",
                   "год имени кончился" in card and "SMS идут от «DentPilot»" in card
                   and "Одобрено, но не работает (1)" in names, card[-3000:])

            # отказ sms.md: причина по-румынски, «respinsă», письмо клинике
            fake.aliases["Zambet Dent"] = 3
            admin.post("/admin/sms/sync")
            note = _one(s, "SELECT sender_note FROM sms_accounts WHERE clinic_id=?", cid)
            pane = _pane(cab.get("/cont").body, "sms")
            res.ok("отказ sms.md: причина по-румынски, «Cererea … respinsă»",
                   note == "numele a fost blocat de operatori (SMS.MD, starea 3)" and "статус" not in pane
                   and "Cererea pentru <b>Zambet Dent</b> <span class='tag bad'>respinsă</span>: " + note in pane,
                   f"{note} {pane[-2000:]}")
            mine = _to(s, "zd@example.md")
            res.ok("клинике — письмо об отказе с причиной",
                   len(mine) == n + 3 and "a fost respinsă" in mine[-1][1] and f"Motivul: {note}" in mine[-1][2],
                   repr(mine[-1:]))
    finally:
        fake.close()


def suite_unpaid(res: Result) -> None:
    """Одобрено без оплаченного года; заявка из программы; отказ Олега с причиной."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s, "Clinica Doi", "doi@example.md")
            _sql(s, "UPDATE clinics SET address='str. Unu 1', phone='022000111' WHERE id=?", cid)
            st, _ = Program(s.url, token).post("/v1/sms/sender", name="Doi Dent")
            got = _to(s, OLEG)
            res.ok("заявка из программы — тоже письмом поставщику",
                   st == 200 and len(got) == 1 and "заявка на имя SMS «Doi Dent»" in got[0][1], f"{st} {got}")
            admin.post(f"/admin/clinics/{cid}/sms", action="request", name="Doi Dent 2")
            res.check("заявка, вписанная в админке, письма поставщику не шлёт", len(_to(s, OLEG)), 1)
            admin.post(f"/admin/clinics/{cid}/sms", action="paper")
            admin.post(f"/admin/clinics/{cid}/sms", action="submitted")
            cab = _cabinet(s, "doi@example.md")
            res.ok("подано без оплаты: кабинет напоминает про год",
                   "Anul numelui nu este încă plătit — plătiți-l mai jos" in _pane(cab.get("/cont").body, "sms"))
            fake.aliases["Doi Dent 2"] = 1
            n = len(_to(s, "doi@example.md"))
            admin.post("/admin/sms/sync")
            mine = _to(s, "doi@example.md")
            res.ok("одобрено без оплаты: письмо говорит, что год не оплачен и SMS идут от DentPilot",
                   len(mine) == n + 1 and "a fost aprobat" in mine[-1][1] and "nu este încă plătit" in mine[-1][2]
                   and "în continuare de la «DentPilot»" in mine[-1][2], repr(mine[-1:]))
            home = cab.get("/cont")
            pane = _pane(home.body, "sms")
            res.ok("кабинет: «aprobat, anul neplătit», SMS от DentPilot, форма оплаты открыта",
                   "<span class='tag warn'>aprobat, anul neplătit</span>" in pane
                   and "anul numelui nu este plătit — SMS-urile pleacă de la «DentPilot»" in pane
                   and "name='name' value='1'" in pane and "<span class='tag ok'>aprobat</span>" not in pane, pane[-3000:])
            card = admin.get(f"/admin/clinics/{cid}").body
            res.ok("админка: одобрено, год не оплачен — в карточке и списком во вкладке имён",
                   "год имени не оплачен" in card and "одобрено, но год имени не оплачен" in card
                   and "Одобрено, но не работает (1)" in admin.get("/admin/sms").body, card[-3000:])
            code, _out = _run_daily(s)
            res.check("неоплаченному имени писем о конце года нет",
                      (code, _one(s, "SELECT count(*) FROM reminders WHERE kind LIKE 'sms_name_%'")), (0, 0))
            # отказ Олега: причина дословно в письме клинике
            admin.post(f"/admin/clinics/{cid}/sms", action="rejected", note="Denumirea nu coincide cu marca clinicii")
            mine = _to(s, "doi@example.md")
            res.ok("отказ Олега — письмо клинике с причиной и путём к новой заявке",
                   len(mine) == n + 2 and "«Doi Dent 2» a fost respinsă" in mine[-1][1]
                   and "Motivul: Denumirea nu coincide cu marca clinicii" in mine[-1][2]
                   and "Puteți cere alt nume" in mine[-1][2], repr(mine[-1:]))
    finally:
        fake.close()


def suite_branch(res: Result) -> None:
    """Филиал: имя общее — заявка и оплата у главной клиники, в его виде кнопок нет."""
    with Server(env={**ENV, "DP_SMS_NAME_PRICE": "77"}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        c.post("/cont/sms/nume", name="Zambet")
        c.post("/cont/sms/nota", name="1", method="transfer", terms="1")
        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        home = c.get(f"/cont?c={bid}")
        pane = _pane(home.body, "sms")
        card = pane[pane.find("SMS · numele expeditorului"):]
        res.ok("вид филиала: имя общее, заявка и оплата — у главной, со ссылкой на её вкладку SMS",
               "cererea și plata se fac la clinica principală" in card and f"href='/cont?c={main}#sms'" in card
               and MAIN["name"] in card and "Zambet" in card, card[-2000:])
        res.ok("вид филиала: ни заявки, ни заказа года, ни оплаты ноты имени",
               "/cont/sms/nume" not in card and "name='name' value='1'" not in card and "name='ref'" not in card
               and "multipart/form-data" not in card and "name='terms'" not in card, card[-2000:])
        res.check("счётчик SMS филиала ноту имени главной не считает", _count(home.body, "sms"), "")
        own = _pane(c.get(f"/cont?c={main}").body, "sms")
        res.ok("вид главной: заявка и нота на месте",
               "/cont/sms/nume" in own and "nume de expeditor SMS, un an" in own and "în așteptare" in own, own[-2000:])


SUITES = [
    ("Имя SMS: путь от заявки до конца года — шаг оплаты, письма, отказ по-румынски", suite_path),
    ("Имя SMS: одобрено без оплаты, заявка из программы, отказ с причиной", suite_unpaid),
    ("Имя SMS: филиал — без кнопок заявки и оплаты", suite_branch),
]

if __name__ == "__main__":
    from harness import run
    sys.exit(run(SUITES))
