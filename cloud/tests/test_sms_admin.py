"""Модуль «SMS» админки (S4): сводка за период, JSON, карточка, кнопки, очередь имён, Excel, тестовая SMS.

Стенд sms.md и помощники — из test_sms. Главное из sms.md › «Админка: модуль
«SMS»»: одна форма отчёта на страницу и JSON; сутки по Кишинёву; сортировка по
расходу; долг клиникам против баланса sms.md; имя не идёт в submitted без
заявления; начисление — только с причиной; Excel пишется копией xlsx движка
(те же байты); ни страница, ни JSON, ни выгрузка не несут цифр номера.
"""
import io
import json
import urllib.request
import zipfile
from datetime import date, datetime, timezone

from harness import CLOUD, ROOT, Client, Result, Server, load_by_path
from test_sms import (DIGITS, DLR_SECRET, PHONE, FakeSmsMd, Program, _bal, _clinic_with_license, _one, _sql,
                      _state, _wait)
from app import sms  # noqa: E402 — путь добавлен test_sms


def suite_admin(res: Result) -> None:
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            res.ok("шапка админки ведёт на SMS", "href='/admin/sms'>SMS</a>" in admin.get("/admin/fleet").body)
            empty = admin.get("/admin/sms").body
            res.ok("пустой модуль: страница говорит об этом, баланс sms.md показан",
                   "ещё не спрашивала про SMS" in empty and "500.00 MDL" in empty and "Сбоев нет" in empty, empty[-2000:])
            cid, token = _clinic_with_license(admin, s, "Clinica Unu", "unu@example.md")
            cid2, token2 = _clinic_with_license(admin, s, "Clinica Doi", "doi@example.md")
            _sql(s, "UPDATE clinics SET idno='2234567890123' WHERE id=?", cid2)
            card = admin.get(f"/admin/clinics/{cid}").body
            res.ok("карточка без счёта: «счёта ещё нет», кнопки пилота и заявки на имя с подсказкой",
                   "счёта ещё нет" in card and "value='pilot_on'" in card and "value='Clinica Unu'" in card, card[-3000:])
            r = admin.post(f"/admin/clinics/{cid}/sms", action="credit", reason="bonus", value="20", note="")
            res.check("начисление без причины — credit_no_note", r.location, f"/admin/clinics/{cid}?msg=credit_no_note")
            r = admin.post(f"/admin/clinics/{cid}/sms", action="credit", reason="bonus", value="20", note="demo")
            res.ok("начисление с причиной — sms_credited, остаток 20, журнал sms_credit",
                   r.location.endswith("msg=sms_credited") and _bal(s, cid) == 20
                   and "+20 (bonus): demo" in _one(s, "SELECT detail FROM audit WHERE what='sms_credit'"))
            admin.post(f"/admin/clinics/{cid2}/sms", action="credit", reason="fix", value="5", note="test")
            res.check("потолок мусором — cap_bad", admin.post(f"/admin/clinics/{cid}/sms", action="cap", value="x").location,
                      f"/admin/clinics/{cid}?msg=cap_bad")
            admin.post(f"/admin/clinics/{cid}/sms", action="cap", value="50")
            res.check("потолок 50 сохранён", _one(s, "SELECT daily_cap FROM sms_accounts WHERE clinic_id=?", cid), 50)
            # имя: заявка из карточки → без заявления в submitted не идёт → заявление → подано
            r = admin.post(f"/admin/clinics/{cid}/sms", action="request", name="Clinica Unu!")
            res.check("кривое имя — sms_name", r.location, f"/admin/clinics/{cid}?msg=sms_name")
            admin.post(f"/admin/clinics/{cid}/sms", action="request", name="Clinica Unu")
            res.check("без заявления — sender_no_paper", admin.post(f"/admin/clinics/{cid}/sms", action="submitted").location,
                      f"/admin/clinics/{cid}?msg=sender_no_paper")
            res.ok("счётчик имён в шапке: SMS (1)", "href='/admin/sms'>SMS (1)</a>" in admin.get(f"/admin/clinics/{cid}").body)
            admin.post(f"/admin/clinics/{cid}/sms", action="paper")
            res.check("заявление получено → подано", admin.post(f"/admin/clinics/{cid}/sms", action="submitted").location,
                      f"/admin/clinics/{cid}?msg=sms_saved")
            page = admin.get("/admin/sms").body
            res.ok("очередь имён на /admin/sms: подано, год не оплачен, кнопка «Сверить»",
                   "Имена на подачу (1)" in page and "подано в sms.md" in page and "год имени не оплачен" in page
                   and "Сверить имена с sms.md" in page, page[-4000:])
            fake.aliases["Clinica Unu"] = 1
            res.check("сверка кнопкой — sms_synced", admin.post("/admin/sms/sync").location, "/admin/sms?msg=sms_synced")
            res.check("имя одобрено", _one(s, "SELECT sender_state FROM sms_accounts WHERE clinic_id=?", cid), "active")
            res.check("отказ без причины — sender_no_reason",
                      admin.post(f"/admin/clinics/{cid}/sms", action="rejected", note="").location,
                      f"/admin/clinics/{cid}?msg=sender_no_reason")
            # отправки: Unu — 3 (доставлена, не доставлена, отказ оператора), Doi — 1 и отказ sms.md
            prog, prog2 = Program(s.url, token), Program(s.url, token2)
            ids = [prog.send(f"appt:{i}:day_before:x")[1]["id"] for i in range(1, 4)]
            pids = [_one(s, "SELECT provider_id FROM sms_messages WHERE id=?", i) for i in ids]
            anon = Client(s.url)
            for pid, st in zip(pids, (3, 9, 10)):
                fake.set_status(pid, st)
                anon.post_raw(f"/v1/smsmd/dlr/{DLR_SECRET}", fake.dlr(pid, st))
            res.ok("статусы применены", _wait(lambda: _state(s, ids[2]) == "failed" and _state(s, ids[1]) == "undelivered"))
            prog2.send("appt:9:day_before:x")
            fake.mode = "422"
            prog2.send("appt:10:day_before:x")
            fake.mode = "ok"
            # JSON: без куки 401; форма отчёта
            res.check("JSON без куки — 401", anon.get("/admin/api/sms").status, 401)
            data = json.loads(admin.get("/admin/api/sms?period=today").body)["data"]
            unu = next(i for i in data["clinics"] if i["clinic_id"] == cid)
            doi = next(i for i in data["clinics"] if i["clinic_id"] == cid2)
            res.ok("Unu: отправлено 3, доставлено 1, не доставлено 1, отказ 1, потрачено 2 (10 возвращено), остаток 18, "
                   "имя одобрено, но год не оплачен — от DentPilot",
                   (unu["sent"], unu["delivered"], unu["undelivered"], unu["refused"], unu["spent"], unu["balance"],
                    unu["billable"]) == (3, 1, 1, 1, 2, 18, 2) and unu["from"] == "DentPilot" and unu["sender_state"] == "active", unu)
            res.ok("Doi: отправлено 1, отказ sms.md 1 (не отправлено), потрачено 1, остаток 4",
                   (doi["sent"], doi["refused"], doi["spent"], doi["balance"]) == (1, 1, 1, 4), doi)
            res.ok("сортировка по расходу: Unu первой; итоги сходятся; долг 22 сегм. против баланса стенда",
                   [i["clinic_id"] for i in data["clinics"]] == [cid, cid2]
                   and data["totals"]["sent"] == 4 and data["totals"]["spent"] == 3 and data["totals"]["balance"] == 22
                   and data["owed"] == 22 and data["smsmd_balance"] == "500.00" and data["owed_mdl"] == "6.60", data["totals"])
            res.ok("сбои по причинам: 9, 10 и отказ sms.md по коду",
                   {(f["reason"], f["count"]) for f in data["failures"]}
                   == {("undelivered", 1), ("failed", 1), ("refused: VALIDATION_ERROR", 1)}, data["failures"])
            today = sms.local(datetime.now(timezone.utc)).date().isoformat()
            res.ok("период по Кишинёву: «сегодня» с today по today", data["period"]["from"] == data["period"]["to"] == today)
            old = json.loads(admin.get("/admin/api/sms?period=custom&from=2025-01-01&to=2025-01-31").body)["data"]
            res.ok("свой период в прошлом: отправок нет, остатки те же",
                   old["totals"]["sent"] == 0 and old["totals"]["balance"] == 22
                   and (old["period"]["kind"], old["period"]["from"], old["period"]["to"]) == ("custom", "2025-01-01", "2025-01-31"))
            page = admin.get("/admin/sms?period=week").body
            res.ok("страница: обе клиники, итоги, долг против баланса, период 7 дней подсвечен",
                   "Clinica Unu" in page and "Clinica Doi" in page and "Итого" in page and "<b>22</b> сегм." in page
                   and "class='on' href='/admin/sms?period=week'" in page, page[-3000:])
            card = admin.get(f"/admin/clinics/{cid}").body
            res.ok("карточка › SMS: остаток, имя одобрено, расход по дням, журнал с причиной",
                   "<b>18</b> сегм." in card and "одобрено" in card and "Расход по дням" in card and "demo" in card, card[-6000:])
            # выгрузка Excel: открывается, строки клиник и итог, копия xlsx = копия движка
            # сырые байты: Reply декодирует тело как текст, а zip текстом не читается
            with admin.opener.open(urllib.request.Request(f"{s.url}/admin/sms/export.xlsx?month={today[:7]}")) as rr:
                raw, disp, status = rr.read(), rr.headers.get("Content-Disposition", ""), rr.status
            res.ok("выгрузка: xlsx с именем по месяцу", status == 200 and "dentpilot-sms-" in disp, disp)
            sheet = ""
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
            except zipfile.BadZipFile:
                pass
            res.ok("xlsx читается: обе клиники, итог, facturabile",
                   "Clinica Unu" in sheet and "Clinica Doi" in sheet and "TOTAL" in sheet and "facturabile" in sheet, sheet[:300])
            res.ok("в выгрузке нет цифр номера", DIGITS not in sheet)
            res.check("журнал: sms_export", _one(s, "SELECT count(*) FROM audit WHERE what='sms_export'"), 1)
            engine_x = load_by_path("engine_xlsx", ROOT / "bot" / "app" / "core" / "xlsx.py")
            from app import xlsx as cloud_x
            hdr, rows = ["a", "b", "c"], [["x", 1, date(2026, 10, 16)], ["022447788", 2.5, None]]
            res.ok("копия xlsx облака даёт те же байты, что движок",
                   cloud_x.book(hdr, rows, [10, 5, 12], "T") == engine_x.book(hdr, rows, [10, 5, 12], "T"))
            res.ok("исходник копии совпадает с движком",
                   (CLOUD / "app" / "xlsx.py").read_text(encoding="utf-8")
                   == (ROOT / "bot" / "app" / "core" / "xlsx.py").read_text(encoding="utf-8"))
            # тестовая SMS себе: от DentPilot, мимо пакетов, номер не в журнале
            res.check("кривой номер — sms_test_phone", admin.post("/admin/sms/test", to="12345").location,
                      "/admin/sms?msg=sms_test_phone")
            n = fake.calls["send"]
            res.check("тестовая SMS — принята", admin.post("/admin/sms/test", to=PHONE).location, "/admin/sms?msg=sms_test_sent")
            res.ok("ушла от DentPilot, остатки клиник не тронуты, в журнале — без цифр",
                   fake.calls["send"] == n + 1 and fake.sent[-1]["from"] == "DentPilot" and _bal(s, cid) == 18
                   and DIGITS not in _one(s, "SELECT detail FROM audit WHERE what='sms_test'"))
            # выключатели и пилот
            admin.post(f"/admin/clinics/{cid}/sms", action="off")
            res.ok("выключено: программа получает sms_off, карточка показывает «выключено»",
                   prog.send("appt:5:day_before:x")[1]["code"] == "sms_off" and "выключено" in admin.get(f"/admin/clinics/{cid}").body)
            admin.post(f"/admin/clinics/{cid}/sms", action="on")
            admin.post(f"/admin/clinics/{cid}/sms", action="pilot_on")
            res.ok("пилот отмечен, журнал sms_toggle", _one(s, "SELECT pilot FROM sms_accounts WHERE clinic_id=?", cid) == 1
                   and _one(s, "SELECT count(*) FROM audit WHERE what='sms_toggle'") == 3)
            res.check("неизвестное действие — sms_action", admin.post(f"/admin/clinics/{cid}/sms", action="zzz").location,
                      f"/admin/clinics/{cid}?msg=sms_action")
            st, r = prog.post("/v1/sms/order", pack=100)
            card = admin.get(f"/admin/clinics/{cid}").body
            res.ok("нота за пакет в таблице нот — «SMS ×100»", st == 200 and "SMS ×100" in card)
            res.ok("страница ожидающих платежей показывает вид", "SMS ×100" in admin.get("/admin/payments").body)
            allp = admin.get("/admin/sms").body + admin.get("/admin/api/sms").body
            res.ok("ни страница, ни JSON не несут цифр номера и текста", DIGITS not in allp and "reaminteste" not in allp)
    finally:
        fake.close()



def suite_taken(res: Result) -> None:
    """Одно имя — одна клиника (Олег 17.10): заявка на имя, которое другая клиника
    держит или просит, — отказ sms_name_taken. Сверка с sms.md идёт по имени, и
    дубль после одобрения включился бы у обеих. Регистр, пробел, точка и тире
    имени не меняют; общее DentPilot клинике не дают; отказ имя освобождает,
    одобренное держит, пока клиника ждёт новое."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s, "Clinica Unu", "unu@example.md")
            cid2, token2 = _clinic_with_license(admin, s, "Clinica Doi", "doi@example.md")
            prog, prog2 = Program(s.url, token), Program(s.url, token2)
            st, r = prog.post("/v1/sms/sender", name="Zambet Dent")
            res.ok("Unu просит «Zambet Dent» — заявка принята", st == 200 and r["sender_state"] == "requested", r)
            for name in ("Zambet Dent", "zambet-dent", "ZAMBETDENT", "Zambet.Dent"):
                st, r = prog2.post("/v1/sms/sender", name=name)
                res.ok(f"Doi просит «{name}» — 409 sms_name_taken с текстом для программы",
                       st == 409 and r["code"] == "sms_name_taken" and "altă clinică" in r["text"], r)
            st, acc = prog2.get("/v1/sms/account")
            res.ok("у Doi заявки нет, SMS от DentPilot", acc["sender_state"] == "none" and acc["from"] == "DentPilot", acc)
            res.check("в журнале одна заявка — от Unu",
                      _one(s, "SELECT count(*) FROM audit WHERE what='sms_sender'"), 1)
            st, r = prog.post("/v1/sms/sender", name="Zambet Dent")
            res.ok("своя повторная заявка — не дубль", st == 200 and r["sender"] == "Zambet Dent", r)
            r = admin.post(f"/admin/clinics/{cid2}/sms", action="request", name="Zambet Dent")
            res.check("из админки — тот же отказ", r.location, f"/admin/clinics/{cid2}?msg=sms_name_taken")
            res.ok("карточка говорит, почему", "другая клиника" in admin.get(r.location).body)
            st, r = prog2.post("/v1/sms/sender", name="Dent Pilot")
            res.ok("общее имя DentPilot клинике не дают", st == 409 and r["code"] == "sms_name_taken", r)
            # одобрено → Unu просит новое: прежнее работает, его по-прежнему не дают
            admin.post(f"/admin/clinics/{cid}/sms", action="paper")
            admin.post(f"/admin/clinics/{cid}/sms", action="submitted")
            fake.aliases["Zambet Dent"] = 1
            admin.post("/admin/sms/sync")
            res.check("имя Unu одобрено", _one(s, "SELECT sender_state FROM sms_accounts WHERE clinic_id=?", cid), "active")
            prog.post("/v1/sms/sender", name="Unu Nou")
            st, r = prog2.post("/v1/sms/sender", name="Zambet Dent")
            res.ok("Unu ждёт новое, одобренное прежнее держит", st == 409 and r["code"] == "sms_name_taken", r)
            st, r = prog2.post("/v1/sms/sender", name="Unu Nou")
            res.ok("новое Unu, пока заявка, тоже держит", st == 409 and r["code"] == "sms_name_taken", r)
            admin.post(f"/admin/clinics/{cid}/sms", action="rejected", note="nu este marca clinicii")
            st, r = prog2.post("/v1/sms/sender", name="Unu Nou")
            res.ok("отказ освобождает имя — заявка Doi принята",
                   st == 200 and r["sender"] == "Unu Nou" and r["sender_state"] == "requested", r)
            st, r = prog2.post("/v1/sms/sender", name="Zambet Dent")
            res.ok("одобренное Unu и после отказа нового держит", st == 409 and r["code"] == "sms_name_taken", r)
    finally:
        fake.close()


def suite_custom(res: Result) -> None:
    """Карточка › SMS › «Личный текст клиники» (S6): проверка на белый список,
    диакритику и один сегмент; включённый годный текст — в /v1/sms/account."""
    fake = FakeSmsMd()
    try:
        with Server(env=fake.env()) as s:
            admin = Client(s.url).login()
            cid, token = _clinic_with_license(admin, s, "Zambet Dent", "zd@example.md")
            prog = Program(s.url, token)
            act = f"/admin/clinics/{cid}/sms"
            card = admin.get(f"/admin/clinics/{cid}").body
            res.ok("без счёта формы нет; после обращения программы — есть",
                   "custom_ro" not in card and prog.get("/v1/sms/account")[0] == 200
                   and "name='custom_ro'" in admin.get(f"/admin/clinics/{cid}").body)
            res.check("в счёте личного текста нет", prog.get("/v1/sms/account")[1].get("custom"), {})
            ok_ro = "{clinica}: {ziua} {data} la {ora}"
            r = admin.post(act, action="custom", custom_ro="Dr {medic}: {clinica} {data} {ora}", custom_ru="", custom_on="1")
            res.check("врач в тексте — sms_custom_ro", r.location, f"/admin/clinics/{cid}?msg=sms_custom_ro")
            r = admin.post(act, action="custom", custom_ro="{clinica} vă așteaptă {ziua} {data} {ora}", custom_ru="", custom_on="1")
            res.check("диакритика в RO — sms_custom_ro", r.location, f"/admin/clinics/{cid}?msg=sms_custom_ro")
            r = admin.post(act, action="custom", custom_ro="{clinica}: " + "x" * 150 + " {data} {ora}", custom_ru="", custom_on="1")
            res.check("второй сегмент в RO — sms_custom_ro", r.location, f"/admin/clinics/{cid}?msg=sms_custom_ro")
            r = admin.post(act, action="custom", custom_ro=ok_ro, custom_ru="{clinica}: " + "ж" * 60 + " {data} {ora}", custom_on="1")
            res.check("длинный RU — sms_custom_ru", r.location, f"/admin/clinics/{cid}?msg=sms_custom_ru")
            r = admin.post(act, action="custom", custom_ro="", custom_ru="", custom_on="1")
            res.check("включён без текста — sms_custom_empty", r.location, f"/admin/clinics/{cid}?msg=sms_custom_empty")
            res.check("после отказов в счёте по-прежнему пусто", prog.get("/v1/sms/account")[1].get("custom"), {})
            r = admin.post(act, action="custom", custom_ro=ok_ro, custom_ru="{clinica}: {ziua}, {data}, {ora}", custom_on="1")
            res.check("годные тексты — sms_saved", r.location, f"/admin/clinics/{cid}?msg=sms_saved")
            res.check("программа получает оба текста", prog.get("/v1/sms/account")[1].get("custom"),
                      {"ro": ok_ro, "ru": "{clinica}: {ziua}, {data}, {ora}"})
            card = admin.get(f"/admin/clinics/{cid}").body
            res.ok("карточка показывает текст и галочку", ok_ro in card and "name='custom_on' value='1' checked" in card)
            res.ok("журнал: sms_custom без самого текста",
                   "личный текст включён" in _one(s, "SELECT detail FROM audit WHERE what='sms_custom' ORDER BY id DESC LIMIT 1"))
            r = admin.post(act, action="custom", custom_ro=ok_ro, custom_ru="", custom_on="")
            res.ok("выключили — текст остаётся в карточке, из счёта уходит",
                   r.location.endswith("msg=sms_saved") and prog.get("/v1/sms/account")[1].get("custom") == {}
                   and ok_ro in admin.get(f"/admin/clinics/{cid}").body)
    finally:
        fake.close()
