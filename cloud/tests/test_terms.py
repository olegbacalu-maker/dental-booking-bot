"""Акт акцепта условий (29.10, terms.py; план review/plan-contract-dataflows-maib-2026-10-29.md § 3.2).

Что держит набор:
- одна версия на троих: `terms.CURRENT` сервера = `TERMS_VERSION` программы = «Ultima actualizare»
  termeni.html — сервер своей копии текста не имеет, страница оплаты принимает «текущие» условия;
- заявка и код из программы с `terms`/`actor` — строка акта с IP, компьютером, версией программы и
  квитанция в ответе; без `terms` (старая программа) — как раньше, с `consent_at` и без акта;
- `/v1/license` несёт `X-DentPilot-Terms` — старшую принятую версию; провод программы её читает;
- `/v1/terms/accept` (Bearer файла): акт source=program, квитанция; мусорная версия — bad_terms;
- галочка страницы оплаты — акт source=pay, `payments.terms_at` на месте;
- карточка клиники и кабинет показывают акты; печатная страница акта — только своей клиники;
- `sms_messages.idem` — хешем, миграция 19 хеширует старые строки и переживает повтор;
- срок хранения журнала: строки `audit` старше AUDIT_KEEP_DAYS снимает ежедневная задача;
  compose режет журнал контейнера числами из config.
"""
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from harness import CLOUD, ROOT, Client, Result, Server, cid_from, load_by_path

sys.path.insert(0, str(CLOUD))
from app import config, db, terms  # noqa: E402
from test_branches import BANK_ENV, _enter, _register, _token_of  # noqa: E402
from test_email import AUTO, GOOD, _sql  # noqa: E402
from test_renew import rn  # noqa: E402

HDR = {"X-DentPilot-Device": "d_00000000ac01", "X-DentPilot-Channel": "stable", "X-DentPilot-OS": "Windows 11"}
AGENT = "DentPilot/2.4.0"


def _program_version() -> str:
    """`TERMS_VERSION` программы — из исходника, не литералом (как tests/test_license_renew._terms)."""
    src = (ROOT / "bot" / "app" / "core" / "license.py").read_text(encoding="utf-8")
    return re.search(r'^TERMS_VERSION = "([^"]+)"', src, re.M).group(1)


def _trial(anon: Client, **over) -> dict:
    r = anon._do("/v1/trial", json.dumps(dict(GOOD, **over)).encode("utf-8"),
                 {"Content-Type": "application/json", "User-Agent": AGENT, **HDR})
    return {"status": r.status, **(json.loads(r.body) if r.body else {})}


def _acts(s: Server, cid: str) -> list:
    return _sql(s, "SELECT version, actor, source, ip, device, app_version, id, at FROM terms_acceptances "
                   "WHERE clinic_id=? ORDER BY rowid", cid)


def _header(s: Server, token: str) -> str:
    """Заголовок X-DentPilot-Terms ответа /v1/license — проводом программы (`rn.fetch(meta=…)`)."""
    meta: dict = {}
    rn.fetch(s.url + "/v1/license", token, 99, timeout=10, meta=meta)
    return meta.get("terms", "")


def suite_pure(res: Result) -> None:
    """Версия — одна на троих; разбор версии и порядок; compose повторяет константы config."""
    page = (ROOT / "docs" / "site" / "termeni.html").read_text(encoding="utf-8")
    m = re.search(r"Ultima actualizare: (\d\d\.\d\d\.\d{4})", page)
    res.check("terms.CURRENT = TERMS_VERSION программы", terms.CURRENT, _program_version())
    res.check("terms.CURRENT = «Ultima actualizare» termeni.html", terms.CURRENT, m.group(1) if m else "?")
    res.check("версия — дата dd.mm.yyyy", [terms.clean_version(x) for x in ("27.10.2026", " 27.10.2026 ", "31.02.2026",
                                                                           "2026-10-27", "", None, "x")],
              ["27.10.2026", "27.10.2026", "", "", "", "", ""])
    res.ok("порядок версий — по дате, не по строке",
           terms.version_key("01.11.2026") > terms.version_key("27.10.2026") > terms.version_key("")
           and terms.version_key("02.01.2027") > terms.version_key("31.12.2026"))
    res.check("актёр — одной строкой, не длиннее ACTOR_MAX", terms.clean_actor("  Ion \n Rusu " + "x" * 80),
              ("Ion Rusu " + "x" * 80)[:terms.ACTOR_MAX])
    compose = (CLOUD / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    res.ok("compose: журнал контейнера режется числами config (LOG_MAX_SIZE × LOG_MAX_FILE)",
           f'max-size: "{config.LOG_MAX_SIZE}"' in compose and f'max-file: "{config.LOG_MAX_FILE}"' in compose
           and "logging:" in compose.split("caddy:")[0], compose[-600:])
    res.ok("срок журнала — 12 месяцев, не меньше (политика называет срок)", config.AUDIT_KEEP_DAYS == 365)
    res.ok("провод программы читает заголовок: только дата, мусор — пусто",
           rn.terms_version({"X-DentPilot-Terms": "27.10.2026"}) == "27.10.2026"
           and rn.terms_version({"X-DentPilot-Terms": "<script>"}) == "" and rn.terms_version({}) == "")


def suite_program(res: Result) -> None:
    """Заявка, код, /v1/terms/accept, заголовок — против живого сервера, проводом программы."""
    with Server(env=AUTO) as s:
        anon = Client(s.url)
        v = terms.CURRENT
        d = _trial(anon, terms=v, actor="Dr. Ana Popescu")
        token = d.get("token", "")
        cid = _sql(s, "SELECT id FROM clinics WHERE email=?", GOOD["email"])[0][0]
        res.ok("заявка с terms: принята, в ответе квитанция акта {id, version, at}",
               d["status"] == 200 and isinstance(d.get("terms"), dict) and d["terms"].get("version") == v
               and str(d["terms"].get("id", "")).startswith("a_") and d["terms"].get("at"), repr(d))
        acts = _acts(s, cid)
        res.ok("акт: версия, кто, source=trial, адрес, компьютер и версия программы из заголовков",
               len(acts) == 1 and acts[0][:6] == (v, "Dr. Ana Popescu", "trial", "127.0.0.1", HDR["X-DentPilot-Device"], "2.4.0")
               and acts[0][6] == d["terms"]["id"], repr(acts))
        res.check("consent_at записан как раньше", bool(_sql(s, "SELECT consent_at FROM clinics WHERE id=?", cid)[0][0]), True)
        res.check("журнал: terms_accept на карточке клиники",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='terms_accept' AND clinic_id=?", cid)[0][0], 1)
        res.check("/v1/license: X-DentPilot-Terms = принятая версия", _header(s, token), v)

        # старая программа: без terms — ни акта, ни заголовка, но consent на месте
        d2 = _trial(anon, name="Clinica Veche", email="veche@example.md")
        cid2 = _sql(s, "SELECT id FROM clinics WHERE email=?", "veche@example.md")[0][0]
        res.ok("без terms: принята, квитанции в ответе нет, акта нет, consent_at есть",
               d2["status"] == 200 and "terms" not in d2 and not _acts(s, cid2)
               and _sql(s, "SELECT consent_at FROM clinics WHERE id=?", cid2)[0][0], repr(d2))
        res.check("без акта заголовка нет (программа читает «не знаем»)", _header(s, d2.get("token", "")), "")
        d3 = _trial(anon, name="Clinica Mușor", email="musor@example.md", terms="2026-10-27", actor="X")
        res.ok("мусорная версия в заявке — заявка принята, акта нет", d3["status"] == 200 and "terms" not in d3
               and not _acts(s, _sql(s, "SELECT id FROM clinics WHERE email=?", "musor@example.md")[0][0]), repr(d3))

        # повторное принятие новой версии из программы — проводом программы
        url = s.url + terms.API_ACCEPT
        out, got = rn.terms_accept(url, token, {"terms": "01.11.2026", "actor": "Ion Rusu"}, timeout=10,
                                   agent=AGENT, extra=HDR)
        res.ok("/v1/terms/accept: ACCEPTED, квитанция", out == rn.ACCEPTED and got.get("version") == "01.11.2026"
               and str(got.get("id", "")).startswith("a_") and got.get("at"), repr((out, got)))
        acts = _acts(s, cid)
        res.ok("второй акт: source=program, та же клиника", len(acts) == 2 and acts[1][:3] == ("01.11.2026", "Ion Rusu", "program"))
        res.check("заголовок — старшая версия", _header(s, token), "01.11.2026")
        rn.terms_accept(url, token, {"terms": "26.10.2026", "actor": "Ion Rusu"}, timeout=10)
        res.check("акт старой версии заголовок не понижает", _header(s, token), "01.11.2026")
        res.check("мусорная версия — REJECTED bad_terms словами",
                  rn.terms_accept(url, token, {"terms": "вчера"}, timeout=10)[0], rn.REJECTED)
        res.check("чужой токен — REFUSED", rn.terms_accept(url, "x" * 43, {"terms": v}, timeout=10), (rn.REFUSED, {}))
        res.check("без токена — 401", anon.post_raw(terms.API_ACCEPT, b"{}").status, 401)
        res.check("не JSON — 400", anon._do(terms.API_ACCEPT, b"<x>", {"Authorization": f"Bearer {token}",
                                                                    "Content-Type": "application/json"}).status, 400)

        # новый компьютер той же клиники: повтор заявки → код → /v1/verify с terms
        d4 = _trial(anon, terms=v, actor="Maria")
        vid = d4.get("verify_id", "")
        res.ok("повтор — 409 с verify_id", d4["status"] == 409 and vid, repr(d4))
        letters = sorted(s.outbox.glob("*.eml"))
        code = ""
        for f in reversed(letters):
            m = re.search(r"\b(\d{6})\b", f.read_text(encoding="utf-8", errors="replace").split("Subject", 1)[-1])
            if m and GOOD["email"] in f.read_text(encoding="utf-8", errors="replace"):
                code = m.group(1)
                break
        r = anon._do("/v1/verify", json.dumps({"verify_id": vid, "code": code, "terms": v, "actor": "Maria"}).encode(),
                     {"Content-Type": "application/json", "User-Agent": "DentPilot/2.4.1", **HDR,
                      "X-DentPilot-Device": "d_00000000ac02"})
        d5 = json.loads(r.body) if r.body else {}
        res.ok("/v1/verify с terms: токен и квитанция", r.status == 200 and d5.get("token") == token
               and (d5.get("terms") or {}).get("version") == v, f"{r.status} {d5!r} code={code!r}")
        acts = _acts(s, cid)
        res.ok("акт source=verify с другим компьютером и версией программы",
               any(a[2] == "verify" and a[1] == "Maria" and a[4] == "d_00000000ac02" and a[5] == "2.4.1" for a in acts),
               repr(acts))

        # админка: акты во вкладке «Лицензия» карточки
        admin = Client(s.url).login()
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("карточка клиники: акты с версией, именем, источником, компьютером и адресом",
               "Акты акцепта условий" in card and "Dr. Ana Popescu" in card and "01.11.2026" in card
               and "заявка на пробный из программы" in card and "из программы (новая версия условий)" in card
               and HDR["X-DentPilot-Device"] in card and "127.0.0.1" in card, card[-3000:])
        res.ok("акты — внутри раздела «Лицензия»",
               card.find("data-pane='lic'") < card.find("Акты акцепта условий") < card.find("data-pane='sms'"))
        card2 = admin.get(f"/admin/clinics/{cid2}").body
        res.ok("без актов — слова, не пустая таблица", "Актов нет" in card2)
        res.ok("журнал словами: terms_accept — «условия приняты (акт)»",
               "условия приняты (акт)" in admin.get(f"/admin/clinics/{cid}?log=lic").body)


def suite_pay_and_cabinet(res: Result) -> None:
    """Страница оплаты — акт source=pay; кабинет — список и печатная страница только своей клиники."""
    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto"}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Plată", idno="1234567890123", contact_name="Vasile",
                                  email="plata@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        token = _token_of(s, cid)
        anon = Client(s.url)
        r = anon._do("/v1/pay-link", b"{}", {"Authorization": f"Bearer {token}", **HDR})
        path = "/plata/" + json.loads(r.body)["url"].rsplit("/", 1)[1]
        res.check("без галочки — need_terms, акта нет", (anon.post(path, months="1", method="transfer").location,
                                                       len(_acts(s, cid))), (f"{path}?msg=need_terms", 0))
        r = anon.post(path, months="1", method="transfer", terms="1")
        res.check("нота переводом создана", r.location, f"{path}?msg=note_created")
        acts = _acts(s, cid)
        res.ok("акт source=pay: версия CURRENT, контакт клиники, адрес браузера, без компьютера",
               len(acts) == 1 and acts[0][:5] == (terms.CURRENT, "Vasile", "pay", "127.0.0.1", ""), repr(acts))
        res.ok("payments.terms_at на месте (как было)",
               _sql(s, "SELECT terms_at FROM payments WHERE clinic_id=?", cid)[0][0])
        res.check("заголовок /v1/license после оплаты — CURRENT", _header(s, token), terms.CURRENT)

        # кабинет: список и акт своей клиники; чужой акт — 404
        other = cid_from(admin.post("/admin/clinics", name="Clinica Străină", idno="1112223334445",
                                    email="straina@example.md").location)
        with db.connect() if False else sqlite3.connect(s.dir / "cloud.db") as con:
            con.row_factory = sqlite3.Row
            con.execute("BEGIN")
            foreign = terms.record(con, other, terms.CURRENT, "Străin", terms.SRC_PAY, "10.0.0.1")
            con.execute("COMMIT")
        c = _enter(s, "plata@example.md")
        page = c.get("/cont")
        res.check("кабинет открыт на клинику оплаты", page.status, 200)
        lst = c.get(terms.PAGE)
        aid = acts[0][6]
        res.ok("/cont/acceptari: версия, кто, источник словами, ссылка на акт",
               lst.status == 200 and terms.CURRENT in lst.body and "Vasile" in lst.body and "pagina de plată" in lst.body
               and f"{terms.PAGE}/{aid}" in lst.body and "Străin" not in lst.body, lst.body[-1500:])
        act = c.get(f"{terms.PAGE}/{aid}")
        res.ok("печатная страница акта: furnizor, clinica с IDNO, versiunea, data, persoana, sursa, id, печать A4",
               act.status == 200 and "Act de acceptare a Termenilor" in act.body and "Oleg Bacalu" in act.body
               and "Clinica Plată" in act.body and "IDNO 1234567890123" in act.body and terms.CURRENT in act.body
               and "Vasile" in act.body and "pagina de plată" in act.body and aid in act.body
               and "@media print" in act.body and "size:A4" in act.body and "window.print()" in act.body, act.body[-2500:])
        res.check("чужой акт — 404", c.get(f"{terms.PAGE}/{foreign['id']}").status, 404)
        res.check("несуществующий — 404", c.get(f"{terms.PAGE}/a_nope").status, 404)
        res.check("без входа — на вход", (Client(s.url).get(terms.PAGE).status, Client(s.url).get(terms.PAGE).location),
                  (303, "/cont/login"))
        # клиника без актов: фрагмент говорит словами и советует программу
        c2 = _enter(s, "straina@example.md")
        _sql(s, "DELETE FROM terms_acceptances WHERE clinic_id=?", other)
        lst2 = c2.get(terms.PAGE)
        res.ok("без актов: «înregistrată local la activare», совет принять текущую версию из программы",
               "înregistrată local" in lst2.body and "Setări › Licența" in lst2.body and terms.CURRENT in lst2.body,
               lst2.body[-1200:])


def suite_idem_and_audit(res: Result) -> None:
    """Миграция 19 хеширует idem и переживает повтор; срок журнала — задачей."""
    with Server() as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Jurnal", idno="1234567890123",
                                  email="jurnal@example.md").location)
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=config.AUDIT_KEEP_DAYS + 1)).strftime(db.TS)
        edge = (now - timedelta(days=config.AUDIT_KEEP_DAYS - 1)).strftime(db.TS)
        _sql(s, "INSERT INTO audit(at, who, what, clinic_id, detail) VALUES(?,?,?,?,?)", old, "form", "trial_request",
             cid, "Clinica Jurnal, 203.0.113.7")
        _sql(s, "INSERT INTO audit(at, who, what, clinic_id, detail) VALUES(?,?,?,?,?)", edge, "form", "trial_request",
             cid, "Clinica Jurnal, 203.0.113.8")
        # старые строки idem — как до шага 19: сервер уже на 19, поэтому откат версии и повтор init
        raw = "appt:17:day_before:2026-11-03T08:00:00Z"
        _sql(s, "INSERT INTO sms_messages(clinic_id, idem, kind, sender, segments, state, sent_at, state_at) "
                "VALUES(?,?,?,?,?,?,?,?)", cid, raw, "day_before", "DentPilot", 1, "sent", db.now_iso(), db.now_iso())
        _sql(s, "UPDATE schema_meta SET value='18' WHERE key='version'")
        p = subprocess.run([sys.executable, "-c", "from app import db; db.init(); db.init(); print('twice')"],
                           cwd=str(CLOUD), env=s.env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        res.ok("init дважды с версии 18: шаг 19 прошёл и повторился без ошибки", p.returncode == 0 and "twice" in p.stdout,
               p.stdout + p.stderr)
        res.check("версия схемы — текущая db.SCHEMA_VERSION (19 здесь, 20 после посадки contract-sign)",
                  _sql(s, "SELECT value FROM schema_meta WHERE key='version'")[0][0], str(db.SCHEMA_VERSION))
        idem = _sql(s, "SELECT idem FROM sms_messages")[0][0]
        import hashlib
        res.check("старая строка захеширована один раз (повтор шага не хеширует хеш)", idem,
                  hashlib.sha256(raw.encode()).hexdigest())
        res.ok("в базе нет строки вида appt:", not _sql(s, "SELECT 1 FROM sms_messages WHERE idem LIKE 'appt:%'"))
        p = subprocess.run([sys.executable, "-m", "app.jobs", "daily"], cwd=str(CLOUD), env=s.env,
                           capture_output=True, text=True, encoding="utf-8", timeout=90)
        res.ok("задача: строка старше срока снята, итог словами", p.returncode == 0
               and f"снято 1 строк старше {config.AUDIT_KEEP_DAYS}" in p.stdout, p.stdout + p.stderr)
        left = _sql(s, "SELECT detail FROM audit WHERE what='trial_request' AND clinic_id=?", cid)
        res.check("строка внутри срока осталась", [d for (d,) in left], ["Clinica Jurnal, 203.0.113.8"])
        res.ok("строка daily о проходе записана", _sql(s, "SELECT 1 FROM audit WHERE what='daily'"))
        p = subprocess.run([sys.executable, "-m", "app.jobs", "daily"], cwd=str(CLOUD), env=s.env,
                           capture_output=True, text=True, encoding="utf-8", timeout=90)
        res.ok("повтор: снимать нечего — итог без слова о журнале", "снято" not in p.stdout, p.stdout[-300:])
