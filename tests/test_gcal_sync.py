"""Сверка журнала с календарями врачей (`app/modules/doctors/gcal_sync.py`) на стенде Google.

Маршрутов у сверки нет, поэтому набор гоняет её отдельным интерпретатором на своей папке клиники (как
`test_gdoc`): в общем процессе `app.db` уже открыт с чужим `DATABASE_URL`. Стенд — `test_gapi.Google` с
`test_gwrite.Calendars`; подключение врача набор делает сам, как сделает экран, через `gdoc.store`.
Записи ставятся путём журнала (`db.admin_add`, `set_status`, `move_appointment`), стирание — путём 195.
Право — подписанный файл лицензии тестовым ключом.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote

from harness import BOT, FIXTURES, PYTHON, Result, _rmtree_settled

SRC = BOT / "app" / "modules" / "doctors" / "gcal_sync.py"
SECRETS = re.compile(r"ya29-[\w-]+|1//rt-[\w-]+|4/code-\d+")


def _worker(tmpdir: str) -> None:
    import asyncio
    import time
    from datetime import datetime, time as dtime, timedelta, timezone

    base = pathlib.Path(tmpdir)
    (base / "clinic.json").write_text((FIXTURES / "clinic_test.json").read_text(encoding="utf-8"), encoding="utf-8")
    os.environ.update({"CLINIC_CONFIG": str(base / "clinic.json"),
                       "DATABASE_URL": f"sqlite:///{base / 'dental.db'}", "ADMIN_KEY": "",
                       "DENTART_LICENSE_KEYS": str(FIXTURES / "license" / "test-key.json")})
    os.environ.pop("DENTART_DEMO", None)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    sys.path.insert(0, str(BOT))
    import test_gapi as tg
    import test_gwrite as tw

    g = tg.Google()
    cals = tw.Calendars(g)
    (base / "google-client.json").write_text(json.dumps({"installed": {"client_id": tg.CLIENT.id}}),
                                             encoding="utf-8")
    os.environ["DENTART_GOOGLE_CLIENT"] = str(base / "google-client.json")
    os.environ["DENTART_GOOGLE_STAND"] = g.base

    from app import db
    from app import engine as eng
    from app.core import gdoc, gwrite
    from app.core import license as lic
    from app.modules.doctors import gcal_sync as gs

    gs.PAUSE_S = 0
    checks: list = []
    seq = {"n": 5, "phone": 100}
    link = base / gdoc.FILE_NAME
    today = datetime.now(eng.TZ).date()

    def chk(label, got, want):
        # снимок сейчас: список запросов стенда растёт и дальше
        checks.append([label, json.loads(json.dumps(got, ensure_ascii=False, default=str)), want])

    def at(days, hh, mm=0):
        return datetime.combine(today + timedelta(days=days), dtime(hh, mm), tzinfo=eng.TZ)

    def utc(moment):
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def entry(dk):
        return json.loads(link.read_text(encoding="utf-8"))["doctors"].get(dk) if link.exists() else None

    def calls(kind=""):
        return [f"{r.get('method', 'POST')} {r['path'].rsplit('/', 1)[-1] if '/events/' in r['path'] else r['path']}"
                for r in g.requests if kind in r["path"]]

    def events_calls():
        return [r.get("method", "POST") for r in g.requests if "/events" in r["path"]]

    def posted():
        return [int(r["json"]["extendedProperties"]["private"]["dp_appt"]) for r in g.requests
                if r.get("method") == "POST" and r["path"].endswith("/events") and isinstance(r.get("json"), dict)]

    def by_appt(cal):
        return {int(e["extendedProperties"]["private"]["dp_appt"]): e for e in cals.live(cal).values()}

    async def rows(dk):
        return {r["appt_id"]: r for r in await db.gdoc_sent_rows(dk)}

    async def license(features, readonly=False):
        seq["n"] += 1
        tw.put_license(base, seq["n"], features, readonly=readonly)
        await lic.refresh()

    async def connect(dk, owner=tw.OWNER):
        cals.owner = owner
        grant = tw.doctor_grant(g, gdoc.agent())
        mark = gdoc.new_mark()
        r = gwrite.calendar_insert(grant.access, gwrite.calendar_summary(eng.CLINIC_NAME, eng.DOCTORS.get(dk, dk)),
                                   gwrite.calendar_description(mark, gs.DESC_ON), base=g.api, agent=gdoc.agent())
        await gdoc.store(dk, refresh=grant.refresh, account=r.data["dataOwner"], cal_id=r.data["id"],
                         cal_name=r.data["summary"], mark=mark, actor="Ana", reused=False,
                         access_token=grant.access, expires_in=grant.expires_in)
        return r.data["id"]

    async def book(dk, when, name, minutes=30, service="Consultație"):
        seq["phone"] += 1
        got = await db.admin_add(name, f"069{seq['phone']:06d}", service, eng.DOCTORS[dk], when.astimezone(timezone.utc),
                                 doctor_id=dk, duration_min=minutes)
        assert isinstance(got, int), got
        return got

    async def main() -> None:
        await db.init([])
        await license({"gcal": 30, "gcal_doctor": 30})
        try:
            await scenario()
        finally:
            if gs._task is not None:
                gs._task.cancel()
                await asyncio.gather(gs._task, return_exceptions=True)
            await db.close()
            g.close()
        disk = (link.read_text(encoding="utf-8") if link.exists() else "") + "".join(
            p.read_bytes().decode("latin-1") for p in base.glob("dental.db*"))
        chk("токены не легли открытым текстом ни в файл связи, ни в картотеку", SECRETS.findall(disk), [])
        print(json.dumps({"checks": checks}, ensure_ascii=False, default=str))

    async def scenario() -> None:
        chk("никто не подключён — проход пуст, к Google ни одного запроса", [await gs.tick(), g.requests],
            [gs.R_OK, []])

        # ---- первая сверка врача ----
        cal2 = await connect("d2")
        a1 = await book("d2", at(1, 9), "Ion Rusu")
        await db._execute("UPDATE appointments SET room = 'Cab. 2' WHERE id = ?", a1)
        a2 = await book("d2", at(10, 10), "Ana Popa")
        await db.set_status(a2, "waiting")
        a3 = await book("d2", at(-1, 11), "Vasile Lungu", service="Detartraj")
        await db.set_status(a3, "done")
        await db._execute("UPDATE patients SET file_no = '0420' WHERE id = ?", await db.appt_patient_id(a3))
        a4 = await book("d2", at(1, 12), "Maria Rotaru")
        await db.set_status(a4, "cancelled")
        await db.add_note(eng.DOCTORS["d2"], at(1, 13).astimezone(timezone.utc), "pauză", doctor_id="d2")
        a6 = await book("d2", at(-40, 9), "Vechi Demult")
        await db.set_status(a6, "done")
        await book("d2", at(100, 9), "Departe Mult")
        a8 = await book("d2", at(2, 9), "Legat Nume")
        await db._execute("UPDATE appointments SET doctor_id = NULL WHERE id = ?", a8)
        await book("d3", at(1, 9), "Alt Medic")
        a10 = await book("d2", at(3, 9), "Nu Venit")
        await db.set_status(a10, "noshow")
        g.requests.clear()
        code = await gs.run_doctor("d2")
        got = by_appt(cal2)
        chk("первая сверка: живые и проведённые записи окна, легаси-строка по имени; отмена, неявка, заметка, "
            "старше и дальше окна, чужой врач — нет", [code, sorted(got)], [gs.R_OK, sorted([a1, a2, a3, a8])])
        e1 = got[a1]
        chk("событие: время и длина записи, «doar ora» с кабинетом, без напоминаний, частное",
            [e1["summary"], e1["start"]["dateTime"], e1["end"]["dateTime"], e1["description"], e1["visibility"],
             e1["reminders"], e1["status"]],
            ["Programare · Cab. 2", utc(at(1, 9)), utc(at(1, 9, 30)), gs.NOTE, "private", {"useDefault": False},
             "confirmed"])
        stored = json.dumps(cals.events, ensure_ascii=False)
        chk("«doar ora»: ни имени, ни фиши, ни телефона, ни услуги у Google",
            [w in stored for w in ("Rusu", "Lungu", "0420", "069", "Detartraj")], [False] * 5)
        sent = await rows("d2")
        chk("отправленное: строка на каждое событие, id из эпохи, записи и поколения",
            [sorted(sent), sent[a1]["event_id"], sent[a1]["gen"], bool(sent[a1]["stamp"])],
            [sorted([a1, a2, a3, a8]), gwrite.event_id(gwrite.clinic_tag(lic.current().claim.clinic_id), 1, a1, 0),
             0, True])
        chk("проход писал — счётчик проходов +1 в файле и в картотеке",
            [(entry("d2") or {}).get("seq"), await db.get_meta(gdoc.META_SEQ + "d2")], [1, "1"])
        desc = cals.cals[cal2]["description"]
        chk("описание календаря — слова программы и метка связи последней строкой",
            [desc.startswith(gs.DESC_ON), "Ultima verificare: " in desc,
             gwrite.mark_of(desc) == (entry("d2") or {}).get("mark")], [True, True, True])

        # ---- ничего не менялось — ни одного запроса ----
        g.requests.clear()
        code = await gs.run_doctor("d2")
        chk("ничего не менялось — ни одного запроса к Google, счётчик стоит",
            [code, g.requests, (entry("d2") or {}).get("seq")], [gs.R_OK, [], 1])
        for st in ("waiting", "arrived"):
            await db.set_status(a1, st)
        await db.set_status(a1, "confirmed")
        await gs.run_doctor("d2")
        chk("«A venit», «În cabinet», назад — ни одного запроса", g.requests, [])

        # ---- перенос, отмена, возврат, другой врач ----
        await db.move_appointment(a1, "d2", eng.DOCTORS["d2"], at(1, 10, 30).astimezone(timezone.utc))
        await gs.run_doctor("d2")
        chk("перенос — одно обновление тем же id, новое время",
            [events_calls(), by_appt(cal2)[a1]["start"]["dateTime"], by_appt(cal2)[a1]["id"]],
            [["PUT"], utc(at(1, 10, 30)), sent[a1]["event_id"]])
        g.requests.clear()
        await db.set_status(a2, "cancelled")
        await gs.run_doctor("d2")
        off = (await rows("d2"))[a2]
        chk("отмена — событие удалено, строка помнит поколение",
            [events_calls(), a2 in by_appt(cal2), off["stamp"], off["gen"]], [["DELETE"], False, "", 1])
        g.requests.clear()
        await db.set_status(a2, "confirmed")
        await gs.run_doctor("d2")
        chk("отмену вернули — вставка новым поколением, не «надгробием»",
            [events_calls(), by_appt(cal2)[a2]["id"].endswith("g1")], [["POST"], True])
        g.requests.clear()
        await db.move_appointment(a1, "d3", eng.DOCTORS["d3"], at(1, 10, 30).astimezone(timezone.utc))
        await gs.run_doctor("d2")
        chk("перенос к другому врачу — у прежнего события нет", [events_calls(), a1 in by_appt(cal2)],
            [["DELETE"], False])

        # ---- стирание и обезличивание по 195, уровни подробности ----
        a12 = await book("d2", at(4, 9), "Șters Complet")
        await gs.run_doctor("d2")
        await db.delete_patient_fully(await db.appt_patient_id(a12))
        g.requests.clear()
        await gs.run_doctor("d2")
        chk("пациента стёрли — его событие у Google удалено по строке отправленного",
            [events_calls(), a12 in by_appt(cal2), (await rows("d2"))[a12]["stamp"]], [["DELETE"], False, ""])
        live = len(by_appt(cal2))
        g.requests.clear()
        chk("уровень «nume și serviciu»", await gdoc.set_level("name", "Director"), gdoc.LV_SET)
        await gs.run_doctor("d2")
        chk("смена уровня — переписаны все события, имя и услуга в заголовке",
            [events_calls(), by_appt(cal2)[a3]["summary"]], [["PUT"] * live, "Vasile Lungu · Detartraj"])
        await gdoc.set_level("initials", "Director")
        await gs.run_doctor("d2")
        chk("уровень «inițiale» — буквы и номер фиши", by_appt(cal2)[a3]["summary"], "V.L. · Fișa 0420")
        await gdoc.set_level("name", "Director")
        await gs.run_doctor("d2")
        g.requests.clear()
        await db.anonymize_patient(await db.appt_patient_id(a3))
        await gs.run_doctor("d2")
        chk("обезличили — прошлое событие переписано без имени",
            [events_calls(), "Lungu" in by_appt(cal2)[a3]["summary"]], [["PUT"], False])
        await gdoc.set_level("time", "Director")
        await gs.run_doctor("d2")
        chk("назад к «doar ora» — имён у Google нет",
            [w in json.dumps(by_appt(cal2), ensure_ascii=False) for w in ("Popa", "Legat", "anonimizat")],
            [False] * 3)

        # ---- окно: старше месяца убирается, вернулось — тот же id занят «надгробием» ----
        acts0 = await db._fetchval("SELECT COUNT(*) FROM activity WHERE kind = 'gdoc'")
        a13 = await book("d2", at(-25, 9), "Recent Trecut")
        await db.set_status(a13, "done")
        await gs.run_doctor("d2")
        gs.BACK = timedelta(days=20)
        g.requests.clear()
        await gs.run_doctor("d2")
        chk("вышло из окна — удалено у Google, строка без события старше окна забыта",
            [events_calls(), a13 in by_appt(cal2), a13 in await rows("d2")], [["DELETE"], False, False])
        gs.BACK = timedelta(days=30)
        g.requests.clear()
        await gs.run_doctor("d2")
        chk("снова в окне: id занят «надгробием» (409) — то же тело поверх, событие живо",
            [events_calls(), a13 in by_appt(cal2)], [["POST", "PUT"], True])
        chk("проходы сверки летопись не пишут",
            await db._fetchval("SELECT COUNT(*) FROM activity WHERE kind = 'gdoc'"), acts0)

        # ---- темп: BURST за проход, порядок, хвост ----
        cal4 = await connect("d4")
        plan = {1: None, 2: None, 5: None, 30: None, 60: None, -2: None, -10: None}
        for d in plan:
            plan[d] = await book("d4", at(d, 9), f"Pacient {d + 100}")
        gs.BURST = 3
        g.requests.clear()
        codes = [await gs.run_doctor("d4")]
        pending = gs.stats("d4")["pending"]
        codes += [await gs.run_doctor("d4"), await gs.run_doctor("d4")]
        gs.BURST = 100
        chk("не больше BURST записей за проход; хвост — «more», догоняет следующий",
            [codes, pending, gs.stats("d4")["pending"]], [[gs.R_MORE, gs.R_MORE, gs.R_OK], 4, 0])
        chk("порядок: ближнее будущее, дальнее, прошлое от недавнего",
            posted(), [plan[d] for d in (1, 2, 5, 30, 60, -2, -10)])

        # ---- предел Google, истёкший токен, потерянный ответ, «надгробие», исчезнувшее событие, 400 ----
        b1 = await book("d4", at(6, 9), "Limita Google")
        cals.fail("POST", "/events", 403, {"error": {"code": 403, "errors": [
            {"reason": "rateLimitExceeded", "domain": "usageLimits"}]}}, headers={"Retry-After": "7"})
        code = await gs.run_doctor("d4")
        quiet = gs._state["d4"]["quiet_until"] - time.monotonic()
        g.requests.clear()
        again = await gs.run_doctor("d4")
        chk("предел Google — стоп врача, тишина Retry-After, повтор без запросов",
            [code, gs.stats("d4")["error"], 5 < quiet <= 7.5, again, g.requests], [gdoc.A_RATE, gdoc.A_RATE, True,
                                                                                    gdoc.A_RATE, []])
        gs.wake("d4")
        chk("«Sincronizează acum» снимает тишину — запись доехала",
            [await gs.run_doctor("d4"), b1 in by_appt(cal4), gs.stats("d4")["error"]], [gs.R_OK, True, ""])
        b2 = await book("d4", at(7, 9), "Token Expirat")
        a = await gdoc.access("d4")
        g.access.pop(a.token, None)
        g.requests.clear()
        code = await gs.run_doctor("d4")
        chk("access-токен истёк посреди прохода — новый по refresh и один повтор",
            [code, "POST /token" in calls(), b2 in by_appt(cal4)], [gs.R_OK, True, True])
        tag, epoch = a.tag, a.epoch
        b3 = await book("d4", at(8, 9), "Raspuns Pierdut")
        eid = gwrite.event_id(tag, epoch, b3, 0)
        cals.events[cal4][eid] = {"id": eid, "status": "confirmed", "summary": "x",
                                  "extendedProperties": {"private": {"dp": tag, "dp_appt": str(b3)}}}
        g.requests.clear()
        await gs.run_doctor("d4")
        chk("ответ на вставку потерялся (409 на свой id) — то же тело поверх, строка записана",
            [events_calls(), by_appt(cal4)[b3]["summary"], bool((await rows("d4"))[b3]["stamp"])],
            [["POST", "PUT"], "Programare", True])
        b4 = await book("d4", at(9, 9), "Mormant Vechi")
        eid = gwrite.event_id(tag, epoch, b4, 0)
        cals.events[cal4][eid] = {"id": eid, "status": "cancelled"}
        cals.fail("PUT", eid, 404, {"error": {"code": 404, "errors": [{"reason": "notFound"}]}})
        g.requests.clear()
        await gs.run_doctor("d4")
        chk("«надгробие» не воскресло — следующее поколение, новый id",
            [events_calls(), by_appt(cal4)[b4]["id"].endswith("g1")], [["POST", "PUT", "POST"], True])
        row = (await rows("d4"))[b1]
        cals.purge(cal4, row["event_id"])
        await db.move_appointment(b1, "d4", eng.DOCTORS["d4"], at(6, 11).astimezone(timezone.utc))
        g.requests.clear()
        await gs.run_doctor("d4")
        chk("событие исчезло у Google совсем — обновление 404, вставка следующим поколением",
            [events_calls(), by_appt(cal4)[b1]["id"].endswith("g1"), by_appt(cal4)[b1]["start"]["dateTime"]],
            [["PUT", "POST"], True, utc(at(6, 11))])
        c1 = await book("d4", at(11, 9), "Corp Gresit")
        c2 = await book("d4", at(12, 9), "Corp Bun")
        cals.fail("POST", "/events", 400, {"error": {"code": 400, "errors": [{"reason": "invalid"}]}})
        code = await gs.run_doctor("d4")
        st = gs.stats("d4")
        chk("Google не принял тело — запись пропущена, остальные едут, ошибка видна",
            [code, c1 in by_appt(cal4), c2 in by_appt(cal4), st["error"], st["pending"]],
            [gs.R_OK, False, True, gs.E_BAD, 1])
        await gs.run_doctor("d4")
        chk("следующий проход довёз пропущенную", [c1 in by_appt(cal4), gs.stats("d4")["error"]], [True, ""])

        # ---- имя и описание календаря — раз в час ----
        cals.cals[cal4]["summary"] = "Calendarul meu"
        cals.cals[cal4]["description"] = ""
        g.requests.clear()
        await gs.run_doctor("d4")
        chk("до часа — календарь не трогается", calls("/calendars/"), [])
        gs._state["d4"]["described"] = time.monotonic() - gs.DESCRIBE_EVERY - 1
        await gs.run_doctor("d4")
        want = gwrite.calendar_summary(eng.CLINIC_NAME, eng.DOCTORS["d4"])
        chk("через час: свежая сверка метки, имя и описание с меткой возвращены, имя — и в файле",
            [[c for c in calls() if "/events" not in c][-2:][0].startswith("GET"), cals.cals[cal4]["summary"],
             gwrite.mark_of(cals.cals[cal4]["description"]) == (entry("d4") or {}).get("mark"),
             (entry("d4") or {}).get("calendar", {}).get("name")],
            [True, want, True, want])

        # ---- пересборка: картотеку восстановили из копии ----
        orphan = gwrite.event_id(tag, epoch, 999999, 0)
        cals.events[cal4][orphan] = {"id": orphan, "status": "confirmed",
                                     "extendedProperties": {"private": {"dp": tag, "dp_appt": "999999"}}}
        before = len(by_appt(cal4))
        await db.set_meta(gdoc.META_SEQ + "d4", "0")
        g.requests.clear()
        code = await gs.run_doctor("d4")
        chk("копия картотеки старше календаря — все наши события удалены, отправленное забыто, новая эпоха",
            [code, cals.live(cal4), await rows("d4"), (entry("d4") or {}).get("epoch"),
             events_calls().count("DELETE")], [gs.R_MORE, {}, {}, 2, before])
        await gs.run_doctor("d4")
        chk("после пересборки — всё снова в календаре, id новой эпохи",
            [len(by_appt(cal4)), all(f"e2a{k}g" in v["id"] for k, v in by_appt(cal4).items())],
            [before - 1, True])

        # ---- переподключение: новый календарь, прежние строки забыты ----
        chk("«Deconectează» — календарь удалён", await gdoc.leave("d4", "disconnect", "Ana"), gdoc.L_DELETED)
        cal4b = await connect("d4")
        g.requests.clear()
        await gs.run_doctor("d4")
        sent4 = await rows("d4")
        chk("подключили заново — всё вставлено в новый календарь, к прежнему ни одного запроса",
            [len(by_appt(cal4b)), [r for r in g.requests if quote(cal4, safe="") in r["path"]],
             {r["cal_id"] for r in sent4.values()}, {r["epoch"] for r in sent4.values()}],
            [before - 1, [], {cal4b}, {1}])

        # ---- права нет: из календаря уходит всё, связь хранится; право вернулось ----
        await gdoc.set_level("name", "Director")
        await gs.run_doctor("d4")
        window = sorted(by_appt(cal4b))
        now_s = utc(datetime.now(timezone.utc))
        future = sorted(k for k, v in by_appt(cal4b).items() if v["start"]["dateTime"] >= now_s)
        past = sorted(k for k in window if k not in future)
        erased, anon = future[0], past[0]
        anon_name = by_appt(cal4b)[anon]["summary"].split(" · ")[0]
        pid_erased, pid_anon = await db.appt_patient_id(erased), await db.appt_patient_id(anon)
        epoch0 = (entry("d4") or {}).get("epoch")
        stray = gwrite.event_id(tag, epoch0, 888888, 0)
        cals.events[cal4b][stray] = {"id": stray, "status": "confirmed",
                                     "extendedProperties": {"private": {"dp": tag, "dp_appt": "888888"}}}
        await license({"gcal": 30})
        cals.fail("DELETE", "/calendars/" + quote(cal4b, safe="") + "/events/", 503, {"error": {"code": 503}})
        await gs.tick()
        chk("Premium кончился, Google не ответил — уход оборван: события на месте, метки паузы нет, связь хранится",
            [len(cals.live(cal4b)), await db.get_meta(gs.META_PAUSED + "d4"), gdoc.linked()["d4"]["state"]],
            [len(window) + 1, None, gdoc.S_ON])
        gs.BURST = 2
        ticks = 0
        while ticks < 30 and await db.get_meta(gs.META_PAUSED + "d4") is None:
            await gs.tick()
            ticks += 1
        gs.BURST = 100
        chk("оборванный уход доделан следующими проходами: ушло всё — прошлое, будущее и неизвестное таблице",
            [ticks > 1, cals.live(cal4b), await rows("d4"), cals.cals[cal4b]["description"].startswith(gs.DESC_OFF),
             (entry("d4") or {}).get("epoch") > epoch0, gdoc.linked()["d4"]["state"], cal4b in cals.cals],
            [True, {}, {}, True, True, gdoc.S_ON, True])
        g.requests.clear()
        await gs.tick()
        chk("права всё ещё нет — повторно к Google не ходит", g.requests, [])
        await db.delete_patient_fully(pid_erased)
        await db.anonymize_patient(pid_anon)
        await license({"gcal": 30, "gcal_doctor": 30})
        g.requests.clear()
        await gs.tick()
        got = by_appt(cal4b)
        ep = (entry("d4") or {}).get("epoch")
        chk("право вернулось — окно вставлено заново новой эпохой, без 409; стёртого в паузе нет, обезличенный без "
            "имени; описание прежнее, метки паузы нет",
            [sorted(got), all(f"e{ep}a" in v["id"] for v in got.values()), "PUT" in events_calls(),
             anon_name in got[anon]["summary"], cals.cals[cal4b]["description"].startswith(gs.DESC_ON),
             await db.get_meta(gs.META_PAUSED + "d4")],
            [[k for k in window if k != erased], True, False, False, True, None])
        await license({"gcal": 30, "gcal_doctor": 30}, readonly=True)
        await gs.tick()
        chk("режим чтения — то же, что без права: календарь пуст", cals.live(cal4b), {})
        await license({"gcal": 30, "gcal_doctor": 30})
        await gs.tick()
        chk("лицензия продлена — окно вернулось", sorted(by_appt(cal4b)), [k for k in window if k != erased])
        await gdoc.set_level("time", "Director")
        await gs.run_doctor("d4")

        # ---- отпуск, архив, врача нет в списке ----
        cfg = json.loads(json.dumps(eng.CONFIG))
        for d in cfg["doctors"]:
            if d["id"] == "d4":
                d["status"] = "concediu"
        eng.apply_config(cfg)
        b9 = await book("d4", at(13, 9), "In Concediu")
        await gs.tick()
        chk("врач в отпуске — сверка идёт", b9 in by_appt(cal4b), True)
        cal1 = await connect("d1")
        await db.gdoc_sent_put("d1", 1, "x", 1, 0, "s", cal1, datetime.now(timezone.utc))
        cals.fail("DELETE", "/calendars/" + quote(cal1, safe=""), 503, {"error": {"code": 503}})
        await gs.tick()
        chk("врач в архиве, Google не ответил — ключ хранится, календарь у Google, повтор следующим проходом",
            [entry("d1") is not None, cal1 in cals.cals], [True, True])
        await gs.tick()
        chk("архив: календарь удалён, ключ и отправленное забыты",
            [entry("d1"), cal1 in cals.cals, await rows("d1")], [None, False, {}])
        cal9 = await connect("d9")
        saved = dict(eng.DOCTORS)
        eng.DOCTORS.clear()
        await gs.tick()
        chk("справочник врачей пуст — не повод удалять календари", [entry("d9") is not None, cal9 in cals.cals],
            [True, True])
        eng.DOCTORS.update(saved)
        await gs.tick()
        chk("врача нет в списке — календарь удалён", [entry("d9"), cal9 in cals.cals], [None, False])
        texts = [r["text"] for r in await db._fetch("SELECT text FROM activity WHERE kind = 'gdoc' ORDER BY id")]
        chk("летопись ухода: архив и «нет в списке»",
            [any(t.endswith("medicul a fost arhivat") for t in texts),
             any(t.endswith("medicul nu mai este în listă") for t in texts)], [True, True])

        # ---- календарь удалили в телефоне ----
        a14 = await book("d2", at(5, 9), "Fara Calendar")
        cals.cals.pop(cal2)
        code = await gs.run_doctor("d2")
        chk("врач удалил календарь — стоп, связь «переподключить», заново не создаётся",
            [code, gdoc.linked()["d2"]["state"], gdoc.linked()["d2"]["why"], len(cals.cals), a14 > 0],
            [gdoc.A_DEAD, gdoc.S_RECONNECT, gdoc.DEAD_GONE, 1, True])

        # ---- крючки двери: сверка зарегистрирована и будится ----
        os.environ[gs.TICK_ENV] = "3600"
        gs.poll_async()
        chk("сверка зарегистрирована в двери: счётчики те же", gdoc.sync_stats("d4"), gs.stats("d4"))
        b10 = await book("d4", at(14, 9), "Trezit Acum")
        chk("«Sincronizează acum» — проход врача через дверь", await gdoc.sync_run("d4", 20.0), gs.R_OK)
        b11 = await book("d4", at(15, 9), "Trezit Bucla")
        gdoc.sync_wake("d4")
        for _ in range(100):
            if b11 in by_appt(cal4b):
                break
            await asyncio.sleep(0.05)
        chk("разбудили цикл — запись доехала без ожидания тика", [b10 in by_appt(cal4b), b11 in by_appt(cal4b)],
            [True, True])

        sent = json.dumps(g.requests, ensure_ascii=False, default=str)
        chk("Google не получает ни id машины, ни id лицензии", [lic.device_id() in sent,
                                                                lic.current().claim.clinic_id in sent], [False, False])

    asyncio.run(main())


def suite(res: Result) -> None:
    """Сверка: окно, разница по всей таблице, темп, отказы Google, пересборка, уход без права, архив."""
    if not res.ok("исходники нашлись", SRC.exists(), str(SRC)):
        return
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_gsync_"))
    try:
        r = subprocess.run([str(PYTHON), str(pathlib.Path(__file__).resolve()), "worker", str(base)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("{")]
        if not res.ok("проба поднялась", r.returncode == 0 and len(lines) == 1,
                      f"rc={r.returncode}: {(r.stdout or '')[-600:]} {(r.stderr or '')[-2500:]}"):
            return
        got = json.loads(lines[0])
    finally:
        _rmtree_settled(base)
    for label, have, want in got["checks"]:
        res.check(label, have, want)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        _worker(sys.argv[2])
