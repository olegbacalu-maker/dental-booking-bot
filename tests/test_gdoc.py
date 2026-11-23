"""Дверь к Google врачей (`app/core/gdoc.py`): файл связи, токены, замок врача, уход без отзыва.

Маршрутов у двери нет, поэтому набор гоняет её отдельным интерпретатором на своей папке клиники (как
`test_book`): в общем процессе `app.db` уже открыт с чужим `DATABASE_URL`. Стенд Google — в том же
интерпретаторе (`test_gapi.Google` с `test_gwrite.Calendars`); вход врача и создание календаря делает
набор сам, как сделает подключение врача, и кладёт запись через `gdoc.store`. Право — подписанный файл
лицензии тестовым ключом, сменой файла и `license.refresh()`.
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

SRC = BOT / "app" / "core" / "gdoc.py"
# Так стенд называет выданные токены и коды: ни один не должен лечь открытым текстом на диск.
SECRETS = re.compile(r"ya29-[\w-]+|1//rt-[\w-]+|4/code-\d+")


def _worker(tmpdir: str) -> None:
    import asyncio
    import time

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

    from app import db, dpapi, version
    from app.core import gdoc, gwrite
    from app.core import license as lic

    checks: list = []
    seq = {"n": 5}
    link = base / gdoc.FILE_NAME

    def chk(label, got, want):
        checks.append([label, got, want])

    def entry(dk):
        return json.loads(link.read_text(encoding="utf-8"))["doctors"].get(dk) if link.exists() else None

    def calls(kind=""):
        return [f"{r.get('method', 'POST')} {r['path']}" for r in g.requests if kind in r["path"]]

    async def license(features, readonly=False):
        seq["n"] += 1
        tw.put_license(base, seq["n"], features, readonly=readonly)
        await lic.refresh()

    async def connect(dk, doctor, owner=tw.OWNER):
        cals.owner = owner
        grant = tw.doctor_grant(g, gdoc.agent())
        mark = gdoc.new_mark()
        r = gwrite.calendar_insert(grant.access, gwrite.calendar_summary("Clinica Test", doctor),
                                   gwrite.calendar_description(mark, "Programările — doar în DentPilot"),
                                   base=g.api, agent=gdoc.agent())
        ok = await gdoc.store(dk, refresh=grant.refresh, account=r.data["dataOwner"], cal_id=r.data["id"],
                              cal_name=r.data["summary"], mark=mark, actor="Ana", reused=False,
                              access_token=grant.access, expires_in=grant.expires_in)
        return ok, r.data["id"], grant

    async def main() -> None:
        await db.init([])
        await license({"gcal": 30, "gcal_doctor": 30})
        try:
            chk("клиент Google есть: исходники, DPAPI, лицензия применяется", gdoc.client() == tg.CLIENT, True)
            chk("врач не подключён — none, файла нет", [(await gdoc.access("d1")).code, link.exists(), gdoc.linked()],
                [gdoc.A_NONE, False, {}])

            # ---- подключение и первый вход в дверь ----
            ok, cal1, grant1 = await connect("d1", "Dr. Ion Rusu")
            e = entry("d1") or {}
            chk("запись врача легла", ok, True)
            chk("запись: токен под DPAPI этой машины, аккаунт — dataOwner, календарь, эпоха 1, счётчик 0",
                [e.get("token", "").startswith(dpapi.PREFIX), e.get("device") == lic.device_id(), e.get("account"),
                 e.get("calendar", {}).get("id") == cal1, e.get("epoch"), e.get("seq"), e.get("connected_by"),
                 e.get("dead"), e.get("foreign"), len(e.get("mark", ""))],
                [True, True, tw.OWNER, True, 1, 0, "Ana", "", False, 8])
            chk("refresh-токен расшифровывается здесь", dpapi.unprotect(e.get("token", "")), grant1.refresh)
            chk("копия id календаря и счётчика — в картотеке",
                [await db.get_meta(gdoc.META_CAL + "d1") == cal1, await db.get_meta(gdoc.META_SEQ + "d1")], [True, "0"])
            g.requests.clear()
            a = await gdoc.access("d1")
            chk("дверь: ok, токен входа из памяти — ни одного запроса к Google",
                [a.code, a.token == grant1.access, a.cal_id == cal1, a.epoch, a.seq, a.rebuild, calls()],
                [gdoc.A_OK, True, True, 1, 0, False, []])
            claim = lic.current().claim
            chk("дверь: метка клиники от id лицензии, адрес — стенд, подпись — версия программы",
                [a.tag, a.api, a.agent, a.mark == e.get("mark")],
                [gwrite.clinic_tag(claim.clinic_id), g.api, f"DentPilot/{version.APP_VERSION}", True])
            a = await gdoc.access("d1", force=True)
            chk("force: новый access-токен и свежая сверка метки",
                [a.code, a.token != grant1.access, calls()],
                [gdoc.A_OK, True, ["POST /token", f"GET /calendar/v3/calendars/{quote(cal1, safe='')}"]])
            body = gwrite.event_body("time", tw.appt(), tag=a.tag, event_id=gwrite.event_id(a.tag, a.epoch, 17, 0),
                                     note="n")
            chk("ключом двери пишется в календарь врача",
                gwrite.event_insert(a.token, a.cal_id, body, base=a.api, agent=a.agent).code, gwrite.OK)

            # ---- метка календаря — не чаще раза в час ----
            g.requests.clear()
            await gdoc.access("d1")
            await gdoc.access("d1")
            chk("метку сверяют не на каждом входе", calls("/calendars/"), [])
            gdoc._checked["d1"] = time.monotonic() - gdoc.MARK_EVERY - 1
            await gdoc.access("d1")
            chk("прошёл час — сверка метки снова", calls("/calendars/"),
                [f"GET /calendar/v3/calendars/{quote(cal1, safe='')}"])

            # ---- счётчик проходов и пересборка ----
            chk("проход писал — счётчик +1 в файле и в картотеке",
                [await gdoc.done("d1", 0), (entry("d1") or {}).get("seq"), await db.get_meta(gdoc.META_SEQ + "d1"),
                 bool((entry("d1") or {}).get("last_ok"))], [1, 1, "1", True])
            chk("счётчики совпали — пересборки нет", (await gdoc.access("d1")).rebuild, False)
            await db.set_meta(gdoc.META_SEQ + "d1", "0")
            chk("картотеку восстановили из копии — пересборка", (await gdoc.access("d1")).rebuild, True)
            await db.del_meta(gdoc.META_SEQ + "d1")
            chk("копия старше подключения (отметки нет, проходы писали) — пересборка",
                (await gdoc.access("d1")).rebuild, True)
            chk("после пересборки — новая эпоха, счётчик файла в картотеку",
                [await gdoc.bump_epoch("d1"), await db.get_meta(gdoc.META_SEQ + "d1")], [2, "1"])
            a = await gdoc.access("d1")
            chk("после пересборки — пересборки нет, эпоха 2", [a.rebuild, a.epoch], [False, 2])
            chk("проход без записи — счётчик тот же, отметка удачи есть",
                [await gdoc.done("d1", 1, wrote=False), (entry("d1") or {}).get("seq"),
                 await db.get_meta(gdoc.META_SEQ + "d1")], [1, 1, "1"])

            # ---- истёкший access-токен и смена refresh-токена ----
            a = await gdoc.access("d1")
            g.access.pop(a.token, None)
            r = gwrite.event_update(a.token, a.cal_id, body["id"], body, base=a.api, agent=a.agent)
            await gdoc.report("d1", r.code)
            b = await gdoc.access("d1")
            chk("access-токен истёк: unauthorized → report → новый токен по refresh",
                [r.code, b.code, b.token != a.token,
                 gwrite.event_update(b.token, b.cal_id, body["id"], body, base=b.api, agent=b.agent).code],
                [gwrite.UNAUTHORIZED, gdoc.A_OK, True, gwrite.OK])
            scopes = frozenset(gauth_scopes())
            g.access["ya29-rot"] = scopes
            g.refreshes["1//rt-rot"] = scopes
            g.token_reply = (200, {"access_token": "ya29-rot", "expires_in": 3599, "token_type": "Bearer",
                                   "refresh_token": "1//rt-rot", "scope": " ".join(sorted(scopes))})
            a = await gdoc.access("d1", force=True)
            g.token_reply = None
            chk("Google выдал новый refresh-токен — он в файле под DPAPI",
                [a.token, dpapi.unprotect((entry("d1") or {}).get("token", ""))], ["ya29-rot", "1//rt-rot"])
            chk("и по нему дверь живёт дальше", (await gdoc.access("d1", force=True)).code, gdoc.A_OK)

            # ---- описание без метки — календарь наш; чужая метка — другая установка ----
            cals.cals[cal1]["description"] = ""
            chk("врач стёр описание календаря — связь жива", (await gdoc.access("d1", force=True)).code, gdoc.A_OK)
            ok, cal2, _ = await connect("d2", "Dr. Ana Popa", owner="ana@gmail.com")
            cals.cals[cal2]["description"] = gwrite.calendar_description("00000000")
            a = await gdoc.access("d2", force=True)
            g.requests.clear()
            again = await gdoc.access("d2", force=True)
            chk("чужая метка — foreign, в файле; повтор — без сети",
                [a.code, (entry("d2") or {}).get("foreign"), again.code, calls()],
                [gdoc.A_FOREIGN, True, gdoc.A_FOREIGN, []])
            chk("экран видит foreign", gdoc.linked()["d2"]["state"], gdoc.S_FOREIGN)
            chk("уход от чужого календаря — забыть ключ, календарь не трогать",
                [await gdoc.leave("d2", "disconnect", "Ana"), entry("d2"), cal2 in cals.cals],
                [gdoc.L_LOCAL, None, True])

            # ---- другой компьютер / другая учётка Windows ----
            ok, cal3, _ = await connect("d3", "Dr. Trei")
            raw = json.loads(link.read_text(encoding="utf-8"))
            raw["doctors"]["d3"]["device"] = "d_000000000000"
            link.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            before = link.read_bytes()
            chk("запись не с этого компьютера — elsewhere, файл не тронут",
                [(await gdoc.access("d3")).code, link.read_bytes() == before], [gdoc.A_ELSEWHERE, True])
            chk("экран: переподключить, причина elsewhere",
                [gdoc.linked()["d3"]["state"], gdoc.linked()["d3"]["why"]], [gdoc.S_RECONNECT, "elsewhere"])
            chk("архив отсюда: удалить нельзя, но может позже — ключ остаётся",
                [await gdoc.leave("d3", "archived", must_delete=True), entry("d3") is not None], [gdoc.L_KEPT, True])
            raw = json.loads(link.read_text(encoding="utf-8"))
            raw["doctors"]["d3"].update(device=lic.device_id(), token="1//rt-plain")
            link.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            chk("открытый токен в файле — чужая запись, не наша", (await gdoc.access("d3")).code, gdoc.A_ELSEWHERE)
            chk("«Deconectează» отсюда — ключ забыт, календарь остался",
                [await gdoc.leave("d3", "disconnect", "Ana"), entry("d3"), cal3 in cals.cals],
                [gdoc.L_LOCAL, None, True])

            # ---- мёртвый refresh-токен, удалённый календарь, исходы сверки ----
            ok, cal4, grant4 = await connect("d4", "Dr. Patru")
            g.refreshes.pop(grant4.refresh, None)
            a = await gdoc.access("d4", force=True)
            g.requests.clear()
            chk("refresh-токен мёртв — dead invalid_grant, в файле; повтор — без сети",
                [a.code, a.reason, (entry("d4") or {}).get("dead"), (await gdoc.access("d4")).code, calls()],
                [gdoc.A_DEAD, gdoc.DEAD_GRANT, gdoc.DEAD_GRANT, gdoc.A_DEAD, []])
            ok, cal5, _ = await connect("d5", "Dr. Cinci")
            cals.cals.pop(cal5)
            a = await gdoc.access("d5", force=True)
            chk("врач удалил календарь в телефоне — dead gone", [a.code, a.reason], [gdoc.A_DEAD, gdoc.DEAD_GONE])
            chk("уход от удалённого календаря — как удаление, копия id стёрта",
                [await gdoc.leave("d5", "disconnect", "Ana"), await db.get_meta(gdoc.META_CAL + "d5")],
                [gdoc.L_DELETED, None])
            await connect("d6", "Dr. Sase")
            await gdoc.report("d6", gwrite.OFFLINE)
            await gdoc.report("d6", gwrite.RATE_LIMITED)
            chk("сбой сети и предел — связь жива", (await gdoc.access("d6")).code, gdoc.A_OK)
            await gdoc.report("d6", gwrite.NO_SCOPE)
            await connect("d7", "Dr. Sapte")
            await gdoc.report("d7", gwrite.NOT_FOUND)
            chk("сверка сообщила: право снято / календаря нет",
                [((await gdoc.access("d6")).code, (await gdoc.access("d6")).reason),
                 ((await gdoc.access("d7")).code, (await gdoc.access("d7")).reason)],
                [(gdoc.A_DEAD, gdoc.DEAD_SCOPE), (gdoc.A_DEAD, gdoc.DEAD_GONE)])

            # ---- уход: календарь удаляется, доступ у Google не отзывается ----
            ok, cal8, grant8 = await connect("d8", "Dr. Opt")
            a = await gdoc.access("d8")
            for i in (1, 2, 3):
                gwrite.event_insert(a.token, a.cal_id, gwrite.event_body(
                    "time", tw.appt(id=i), tag=a.tag, event_id=gwrite.event_id(a.tag, a.epoch, i, 0), note=""), base=a.api, agent=a.agent)
            await gdoc.done("d8", 0)
            chk("«Deconectează»: календарь удалён, ключ забыт, копии в картотеке стёрты",
                [await gdoc.leave("d8", "disconnect", "Ana"), cal8 in cals.cals, entry("d8"),
                 await db.get_meta(gdoc.META_CAL + "d8"), await db.get_meta(gdoc.META_SEQ + "d8")],
                [gdoc.L_DELETED, False, None, None, None])
            chk("доступ у Google не отозван: refresh-токен врача жив, к /revoke ни одного запроса",
                [grant8.refresh in g.refreshes, [r["path"] for r in g.requests if r["path"].endswith("/revoke")]],
                [True, []])
            chk("уйти без связи — none; незнакомая причина — ошибка программиста",
                [await gdoc.leave("d8", "disconnect", "Ana"), await raises(gdoc.leave("d1", "bye", "Ana"))],
                [gdoc.L_NONE, True])
            ok, cal10, _ = await connect("d10", "Dr. Zece")
            cals.fail("DELETE", "/calendars/", 503, {"error": {"code": 503}})
            chk("архив без сети — ключ остаётся до следующего прохода",
                [await gdoc.leave("d10", "archived", must_delete=True), entry("d10") is not None, cal10 in cals.cals],
                [gdoc.L_KEPT, True, True])
            chk("следующий проход — календарь удалён",
                [await gdoc.leave("d10", "archived"), cal10 in cals.cals], [gdoc.L_DELETED, False])
            ok, cal11, _ = await connect("d11", "Dr. Unspe")
            cals.fail("DELETE", "/calendars/", 503, {"error": {"code": 503}})
            chk("«Deconectează» без сети — ключ забыт, календарь остался у Google",
                [await gdoc.leave("d11", "disconnect", "Ana"), entry("d11"), cal11 in cals.cals],
                [gdoc.L_LOCAL, None, True])

            # ---- право gcal_doctor ----
            ok, cal9, _ = await connect("d9", "Dr. Noua")
            await license({"gcal": 30})
            g.requests.clear()
            chk("права нет — gate без сети, связь хранится",
                [(await gdoc.access("d1")).code, calls(), gdoc.linked()["d1"]["state"]],
                [gdoc.A_GATE, [], gdoc.S_ON])
            chk("уход права не спрашивает", (await gdoc.access("d1", leave=True)).code, gdoc.A_OK)
            chk("уборка после конца права: календарь удаляется",
                [await gdoc.leave("d9", "archived", must_delete=True), cal9 in cals.cals], [gdoc.L_DELETED, False])
            await license({"gcal": 30, "gcal_doctor": 30}, readonly=True)
            chk("режим чтения — gate", (await gdoc.access("d1")).code, gdoc.A_GATE)
            await license({"gcal": 30, "gcal_doctor": 30})
            chk("право вернулось — дверь открыта без нового входа", (await gdoc.access("d1")).code, gdoc.A_OK)
            keep = os.environ.pop("DENTART_GOOGLE_CLIENT")
            chk("сборка без клиента Google — no_client", (await gdoc.access("d1")).code, gdoc.A_NO_CLIENT)
            os.environ["DENTART_GOOGLE_CLIENT"] = keep
            os.environ["DENTART_DEMO"] = "1"
            chk("демо — no_client", (await gdoc.access("d1")).code, gdoc.A_NO_CLIENT)
            os.environ.pop("DENTART_DEMO")

            # ---- замок врача ----
            async with gdoc.lock("d1"), asyncio.timeout(5):
                inner = await gdoc.access("d1")
                named = await gdoc.calendar_named("d1", "DentPilot · Clinica Test · Dr. Rusu")
            chk("замок повторно входим той же задачей: проход держит его и зовёт дверь",
                [inner.code, named, (entry("d1") or {}).get("calendar", {}).get("name")],
                [gdoc.A_OK, None, "DentPilot · Clinica Test · Dr. Rusu"])
            held = asyncio.Event()
            release = asyncio.Event()

            async def holder():
                async with gdoc.lock("d1"):
                    held.set()
                    await release.wait()
            task = asyncio.create_task(holder())
            await held.wait()
            try:
                async with asyncio.timeout(0.3):
                    await gdoc.done("d1", 1)
                waited = False
            except TimeoutError:
                waited = True
            async with asyncio.timeout(5):
                other = await gdoc.access("d6")
            release.set()
            await task
            chk("другая задача ждёт замка врача; чужой врач — не ждёт", [waited, other.code], [True, gdoc.A_DEAD])
            await connect("d12", "Dr. Doisprezece")
            s1 = (entry("d1") or {}).get("seq")
            await asyncio.gather(gdoc.done("d1", s1), gdoc.done("d12", 0), gdoc.calendar_named("d6", "X"),
                                 gdoc.report("d7", gwrite.NO_SCOPE))
            chk("проходы двух врачей разом не теряют записей друг друга",
                [(entry("d1") or {}).get("seq"), (entry("d12") or {}).get("seq"),
                 (entry("d6") or {}).get("calendar", {}).get("name")], [s1 + 1, 1, "X"])

            # ---- крючки сверки: подключение будит и ждёт, не зная модуля сверки ----
            t0 = time.monotonic()
            gdoc.sync_wake("d1")
            gdoc.sync_wake()
            chk("без сверки: разбудить — ничего, прогнать — None сразу, счётчики — {}",
                [await gdoc.sync_run("d1", 2.0), time.monotonic() - t0 < 0.5, gdoc.sync_stats("d1")], [None, True, {}])
            woke, ran, done_ = [], [], []
            delay = {"s": 0.05}

            async def run(dk):
                ran.append(dk)
                await asyncio.sleep(delay["s"])
                if dk == "boom":
                    raise RuntimeError("pass failed")
                done_.append(dk)
                return f"ok:{dk}"

            stats = {"last_ok": "2026-12-01T09:00:00Z", "error": "", "error_at": "", "pending": 3}
            gdoc.attach_sync(wake=woke.append, run=run, stats=lambda dk: {**stats, "dk": dk})
            gdoc.sync_wake("d1")
            gdoc.sync_wake()
            chk("сверка подключена: будят с врачом и без", list(woke), ["d1", None])
            chk("прогнать врача: тот врач, ответ прохода", [await gdoc.sync_run("d12", 2.0), list(ran)], ["ok:d12", ["d12"]])
            delay["s"] = 0.8
            t0 = time.monotonic()
            late = await gdoc.sync_run("d13", 0.2)
            waited = time.monotonic() - t0
            await asyncio.sleep(1.0)
            chk("не успела — None не дольше ожидания, а проход доходит до конца",
                [late, waited < 0.6, list(done_)], [None, True, ["d12", "d13"]])
            delay["s"] = 0.01
            chk("проход упал — None, не исключение", await gdoc.sync_run("boom", 2.0), None)
            chk("счётчики сверки — как есть", gdoc.sync_stats("d14"), {**stats, "dk": "d14"})
            other = []
            gdoc.attach_sync(wake=other.append, run=run, stats=lambda dk: {})
            gdoc.sync_wake("d2")
            chk("повторное подключение заменяет крючки", [list(woke), list(other), gdoc.sync_stats("d1")],
                [["d1", None], ["d2"], {}])
            gdoc.attach_sync(wake=None, run=None, stats=None)
            chk("None — сверки снова нет", [await gdoc.sync_run("d1", 1.0), gdoc.sync_stats("d1")], [None, {}])

            # ---- уровень, тот же аккаунт ----
            chk("уровень по умолчанию — doar ora", await gdoc.level(), "time")
            chk("уровень: смена, повтор, незнакомый",
                [await gdoc.set_level("name", "Director"), await gdoc.level(), await gdoc.set_level("name", "Director"),
                 await gdoc.set_level("full", "Director"), await gdoc.level()],
                [gdoc.LV_SET, "name", gdoc.LV_SAME, gdoc.LV_BAD, "name"])
            await connect("d13", "Dr. Treisprezece", owner="Clinica@Gmail.com")
            await connect("d14", "Dr. Paisprezece", owner="clinica@gmail.com")
            chk("врачи на аккаунте клиники — для предупреждения «Deconectează»",
                [gdoc.same_account(" clinica@gmail.com "), gdoc.same_account("")], [["d13", "d14"], []])
            v = gdoc.linked()["d13"]
            chk("экран: состояние, аккаунт, календарь, кто подключил",
                [v["state"], v["why"], v["account"], bool(v["calendar"]["id"]), v["calendar"]["name"], v["connected_by"]],
                [gdoc.S_ON, "", "Clinica@Gmail.com", True, "DentPilot · Clinica Test · Dr. Treisprezece", "Ana"])

            rows = await db._fetch("SELECT actor, text FROM activity WHERE kind = 'gdoc' ORDER BY id")
            texts = [f"{r['actor']}: {r['text']}" for r in rows]
            chk("летопись: подключение, уход с причиной, уровень",
                [texts[0], "Ana: Calendarele medicilor: „DentPilot · Clinica Test · Dr. Opt” — deconectat" in texts,
                 "sistem: Calendarele medicilor: „DentPilot · Clinica Test · Dr. Noua” — medicul a fost arhivat" in texts,
                 "Director: Calendarele medicilor: nivelul „nume și serviciu”" in texts],
                ["Ana: Calendarele medicilor: „DentPilot · Clinica Test · Dr. Ion Rusu” — conectat", True, True, True])

            sent = json.dumps(g.requests, ensure_ascii=False, default=str)
            chk("Google не получает ни id машины, ни id лицензии (Anexa 2)",
                [lic.device_id() in sent, claim.clinic_id in sent,
                 sorted({r.get("agent") for r in g.requests if r.get("agent")})],
                [False, False, [f"DentPilot/{version.APP_VERSION}"]])
        finally:
            await db.close()
            g.close()
        disk = link.read_text(encoding="utf-8") + "".join(
            p.read_bytes().decode("latin-1") for p in base.glob("dental.db*"))
        chk("токены не легли открытым текстом ни в файл связи, ни в картотеку", SECRETS.findall(disk), [])
        print(json.dumps({"checks": checks}, ensure_ascii=False, default=str))

    async def raises(coro) -> bool:
        try:
            await coro
        except ValueError:
            return True
        return False

    def gauth_scopes():
        from app.core import gauth
        return gauth.DOCTOR_SCOPES

    asyncio.run(main())


def suite(res: Result) -> None:
    """Дверь: вход по праву, токены и метка, счётчик и пересборка, уход без отзыва, замок врача."""
    if not res.ok("исходники нашлись", SRC.exists(), str(SRC)):
        return
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_gdoc_"))
    try:
        r = subprocess.run([str(PYTHON), str(pathlib.Path(__file__).resolve()), "worker", str(base)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=180, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
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
