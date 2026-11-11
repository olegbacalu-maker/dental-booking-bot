"""Архив клиник и удаление из архива (archive.py) — 11.11.2026, Олег: «Да, с умолчаниями».

Главное: архив — метка (вне списка, фильтров, флота и писем ежедневной задачи; файл программы не отзывается; IDNO,
ящик и ПК остаются заняты). Удалить навсегда — только из архива, со словом и причиной, одной транзакцией; IDNO,
ящик и ПК освобождаются. ⛔ Деньги, отправленные SMS и подписанные бумаги запрещают удаление — каждый запрет своей
проверкой, по живой базе в момент POST (страница могла быть открыта раньше).
"""
import json
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

from harness import CLOUD, Client, Result, Server

sys.path.insert(0, str(CLOUD))
from app import archive, db as cdb, trial  # noqa: E402
from test_branches import BANK_ENV, MAIN, _enter, _letters, _register  # noqa: E402
from test_jobs import _run  # noqa: E402
from test_paylink import HDR  # noqa: E402

ENV = {**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md", "DP_SMS_OFFERED": "1",
       "DP_SMSMD_TOKEN": "t", "DP_SMSMD_BASE_URL": "http://127.0.0.1:9", "DP_SMS_PACKS": "100:50"}
PROG = dict(name="Clinica Arhiva", idno="1002601003214", contact_name="Ana", email="arhiva@example.md",
            phone="069000000", consent="1")
NOW = "2026-11-11T10:00:00Z"
# что запрещает удаление (Олег 11.11, «Да, с умолчаниями»): деньги, отправленные SMS, подписанные бумаги
BLOCKED = (("payments", "ноты и платежи"), ("payment_lines", "строки общей ноты"), ("receipts", "cont de plată"),
           ("pay_attempts", "попытки оплаты картой"), ("sms_messages", "отправленные SMS"),
           ("sms_ledger", "списания и пакеты SMS"), ("clinic_contracts", "подписанные клиникой документы"),
           ("sms_papers", "подписанные заявления на имя SMS"))


def _msg(r) -> str:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.location).query)).get("msg", "")


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db", timeout=10)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        rows = con.execute(sql, args).fetchall()
        con.commit()                     # UPDATE/INSERT из теста без commit откатился бы при close
        return rows
    finally:
        con.close()


def _program(s: Server, fields: dict = PROG, device: str = HDR["X-DentPilot-Device"]) -> tuple[int, dict]:
    r = Client(s.url)._do(trial.API_PATH, json.dumps(fields).encode("utf-8"),
                          {**HDR, "X-DentPilot-Device": device, "Content-Type": "application/json"})
    try:
        return r.status, json.loads(r.body)
    except ValueError:
        return r.status, {}


def _pane(body: str, key: str) -> str:
    i = body.find(f"<section class='pane' data-pane='{key}'>")
    return body[i:body.find("</section>", i)] if i >= 0 else ""


def _admin_clinic(admin: Client, name: str, idno: str = "", email: str = "") -> str:
    r = admin.post("/admin/clinics", name=name, idno=idno, contact_name="—", email=email, phone="", address="")
    cid = r.location.split("/admin/clinics/")[1].split("?")[0]
    admin.post(f"/admin/clinics/{cid}/issue", kind="trial", valid_until="", grace_days="3", reason="probă")
    return cid


def _delete(admin: Client, cid: str, **over):
    return admin.post(f"/admin/clinics/{cid}/delete", **{"reason": "clinică demo", "confirm": "УДАЛИТЬ", **over})


def suite_schema(res: Result) -> None:
    """Шаг 23 переживает повтор; каждая таблица со ссылкой на clinics(id) названа в archive.py."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for step in range(1, cdb.SCHEMA_VERSION + 1):
            cdb.apply_step(con, step)
        cdb.apply_step(con, 23)
        cols = {r[1] for r in con.execute("PRAGMA table_info(clinics)")}
        res.ok("шаг 23: archived_at, archived_by, archived_reason; повтор без ошибки",
               {"archived_at", "archived_by", "archived_reason"} <= cols and cdb.SCHEMA_VERSION >= 23)
        refs = sorted(t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                      if any(f[2] == "clinics" for f in con.execute(f"PRAGMA foreign_key_list({t})")))
        known = set(archive.CLEARED) | {t for t, _, _ in archive.BLOCKERS} | set(archive.DETACHED)
        res.ok("таблицы со ссылкой на clinics нашлись", len(refs) >= 15, refs)
        res.check("каждая ссылка на clinics(id) — в CLEARED, BLOCKERS или DETACHED", sorted(set(refs) - known), [])
    finally:
        con.close()


def suite_archive(res: Result) -> None:
    """Архив: вне списка, фильтров, заявок, флота и писем; файл не отозван; IDNO, ящик и ПК заняты; «Вернуть»."""
    with Server(env=ENV) as s:
        st, body = _program(s)
        tok = body.get("token", "")
        cid = _sql(s, "SELECT id FROM clinics WHERE email=?", PROG["email"])[0][0]
        other = _admin_clinic((admin := Client(s.url).login()), "Clinica Rămâne", "1002600000803", "ramane@example.md")
        Client(s.url)._do(f"/v1/license?seq=0", None, {**HDR, "Authorization": f"Bearer {tok}"})
        page = admin.get("/admin").body
        form = page[page.find(f"action='/admin/clinics/{cid}/archive'"):]
        form = form[:form.find("</form>")]
        res.ok("строка списка: «В архив», у действующей — предупреждение и «Сначала отозвать»",
               "Лицензия действует" in form and f"/admin/clinics/{cid}#lic" in form and "Всё равно в архив" in form, form[:200])
        seq = _sql(s, "SELECT MAX(seq) FROM issues WHERE clinic_id=?", cid)[0][0]
        res.check("в архив", _msg(admin.post(f"/admin/clinics/{cid}/archive", reason="clinică demo")), archive.ARCHIVED)
        res.check("повторно — уже в архиве", _msg(admin.post(f"/admin/clinics/{cid}/archive")), archive.ALREADY)
        page = admin.get("/admin").body
        lst, arc = _pane(page, "list"), _pane(page, "archive")
        res.ok("список: архивной нет, «Все» её не считает; вкладка «Архив 1» — она с причиной",
               cid not in lst and other in lst and "Все 1" in lst and cid in arc and "clinică demo" in arc
               and "Архив <span class='c'>1</span>" in page, (cid in lst, "Все 1" in lst))
        res.ok("фильтр состояния её не показывает", cid not in _pane(admin.get("/admin?state=active").body, "list"))
        fleet = json.loads(admin.get("/admin/api/fleet").body)["data"]
        res.ok("флот: компьютеров архивной нет", all(d["clinic_id"] != cid for d in fleet["devices"]), fleet["counts"])
        res.check("архив не отзывает: файлов столько же, отметки отзыва нет",
                  _sql(s, "SELECT MAX(seq), revoked_at FROM issues JOIN clinics c ON c.id=issues.clinic_id "
                          "WHERE clinic_id=?", cid)[0], (seq, None))
        r = Client(s.url)._do(f"/v1/license?seq={seq}", None, {**HDR, "Authorization": f"Bearer {tok}"})
        res.check("программа архивной спрашивает как раньше (204 — новее нет)", r.status, 204)
        res.ok("карточка: «в архиве», причина, «Вернуть из архива»",
               "в архиве" in (card := admin.get(f"/admin/clinics/{cid}").body) and f"/admin/clinics/{cid}/unarchive" in card)
        n = _sql(s, "SELECT count(*) FROM clinics")[0][0]
        st, body = _program(s, {**PROG, "email": "alt@example.md"}, "d_000000000002")
        res.ok("тот же IDNO — повтор (409), не новый пробный", st == 409 and body.get("code") == "duplicate", (st, body))
        st, body = _program(s, {**PROG, "idno": "1020608000025"}, "d_000000000003")
        res.ok("тот же ящик — повтор (409)", st == 409 and body.get("code") == "duplicate", (st, body))
        st, body = _program(s, {**PROG, "idno": "1008600038413", "email": "nou@example.md"})
        res.ok("тот же компьютер — 409 device_taken", st == 409 and body.get("code") == "device_taken", (st, body))
        res.check("клиник не прибавилось", _sql(s, "SELECT count(*) FROM clinics")[0][0], n)
        # срок архивной прошёл: задача молчит (окно «режим чтения»), у соседки с тем же сроком — письмо
        past = (datetime.now(timezone.utc) - timedelta(days=5)).strftime(cdb.TS)
        _sql(s, "UPDATE subscriptions SET valid_until=?, grace_days=0 WHERE clinic_id IN (?, ?)", past, cid, other)
        before = _letters(s)
        rc, out = _run(s, datetime.now(timezone.utc).date())
        new = [x[0] for x in _letters(s)[len(before):]]
        res.ok("ежедневная задача: архивной ни письма, соседке — письмо", rc == 0 and PROG["email"] not in new
               and "ramane@example.md" in new, (rc, new, out[-200:]))
        res.check("вернуть из архива", _msg(admin.post(f"/admin/clinics/{cid}/unarchive")), archive.UNARCHIVED)
        res.ok("снова в списке", cid in _pane(admin.get("/admin").body, "list"))
        res.check("вернуть невозвращаемое — archive_not", _msg(admin.post(f"/admin/clinics/{cid}/unarchive")),
                  archive.NOT_ARCHIVED)


def suite_delete(res: Result) -> None:
    """Удалить: только из архива, причина и слово; стёрто всё, что держалось; IDNO, ящик и ПК свободны; журнал."""
    with Server(env=ENV) as s:
        c = _enter(s, "director@arhiva.md")
        cid = _register(s, c)
        tok = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]
        anon = Client(s.url)
        anon._do("/v1/license?seq=0", None, {**HDR, "Authorization": f"Bearer {tok}"})
        anon._do("/v1/sms/account", None, {**HDR, "Authorization": f"Bearer {tok}"})        # счёт SMS и пробный бонус
        _sql(s, "INSERT INTO terms_acceptances(id, clinic_id, version, actor, source, at) VALUES('t1', ?, '05.11.2026', "
                "'Ion', 'trial', ?)", cid, NOW) if not _sql(s, "SELECT 1 FROM terms_acceptances WHERE clinic_id=?", cid) else None
        admin = Client(s.url).login()
        held = {t: _sql(s, f"SELECT count(*) FROM {t} WHERE clinic_id=?", cid)[0][0] for t in archive.CLEARED}
        res.ok("засев: файл, ПК, привязка кабинета, SMS-счёт с бонусом, акт",
               all(held[t] for t in ("issues", "devices", "account_clinics", "sms_accounts", "sms_ledger",
                                      "terms_acceptances", "subscriptions")), held)
        res.check("не в архиве — удалить нельзя", (_msg(_delete(admin, cid)), _sql(s, "SELECT count(*) FROM clinics WHERE id=?", cid)[0][0]),
                  (archive.NOT_ARCHIVED, 1))
        admin.post(f"/admin/clinics/{cid}/archive", reason="demo")
        arc = _pane(admin.get("/admin").body, "archive")
        res.ok("вкладка «Архив»: «Удалить навсегда», слово, причина, предупреждение о действующем файле",
               f"action='/admin/clinics/{cid}/delete'" in arc and "name='confirm'" in arc and "required" in arc
               and "отозвать её уже нельзя" in arc and "доработает до срока + льготы" in arc, arc[:300])
        res.check("без причины — отказ", _msg(_delete(admin, cid, reason=" ")), archive.NEED_REASON)
        res.check("без слова УДАЛИТЬ — отказ", _msg(_delete(admin, cid, confirm="da")), archive.NEED_WORD)
        res.check("отказы ничего не стёрли", _sql(s, "SELECT count(*) FROM clinics WHERE id=?", cid)[0][0], 1)
        acc = _sql(s, "SELECT id FROM accounts WHERE clinic_id=?", cid)[0][0]
        res.check("удалить (слово в любом регистре)", _msg(_delete(admin, cid, confirm="удалить")), archive.DELETED)
        left = {t: _sql(s, f"SELECT count(*) FROM {t} WHERE clinic_id=?", cid)[0][0] for t in archive.CLEARED}
        res.ok("стёрто: клиника и всё, что на ней держалось",
               not any(left.values()) and not _sql(s, "SELECT 1 FROM clinics WHERE id=?", cid)
               and not _sql(s, "SELECT 1 FROM reminders WHERE subscription_id=?", cid), left)
        res.check("учётная запись кабинета осталась, без открытой клиники",
                  _sql(s, "SELECT count(*), MAX(clinic_id) FROM accounts WHERE id=?", acc)[0], (1, None))
        row = _sql(s, "SELECT who, detail FROM audit WHERE what='clinic_deleted' AND clinic_id=?", cid)
        res.ok("журнал: «удалена» — кто, имя, IDNO, причина, что программа доработает",
               len(row) == 1 and row[0][0] == "oleg" and MAIN["name"] in row[0][1] and MAIN["idno"] in row[0][1]
               and "clinică demo" in row[0][1] and "доработает" in row[0][1], row)
        res.ok("прежние строки журнала клиники остались",
               _sql(s, "SELECT count(*) FROM audit WHERE clinic_id=? AND what<>'clinic_deleted'", cid)[0][0] > 3)
        st, body = _program(s, {**PROG, "idno": MAIN["idno"], "email": "director@arhiva.md"})
        res.ok("IDNO, ящик и компьютер свободны: новый пробный выдан", st == 200 and body.get("state") == "issued", (st, body))
        r = admin.post(f"/admin/clinics/{cid}/delete", reason="x", confirm="УДАЛИТЬ")
        res.check("второй раз — «такой клиники уже нет»", _msg(r), "delete_gone")


def _block(s: Server, label: str, cid: str, payer: str) -> None:
    """Строка, которая держит клинику, — минимальной вставкой."""
    if label == "payments":
        _sql(s, "INSERT INTO payments(clinic_id, amount, method, status, reference, created_at) "
                "VALUES(?, 100, 'transfer', 'rejected', 'DP-T-1', ?)", cid, NOW)
    elif label == "payment_lines":
        _sql(s, "INSERT INTO payments(clinic_id, amount, method, status, reference, created_at, kind) "
                "VALUES(?, 100, 'transfer', 'pending', 'DP-T-2', ?, 'cabinet')", payer, NOW)
        pid = _sql(s, "SELECT id FROM payments WHERE reference='DP-T-2'")[0][0]
        _sql(s, "INSERT INTO payment_lines(payment_id, clinic_id, tier, months, amount) VALUES(?, ?, 'plus', 1, 100)",
             pid, cid)
    elif label == "receipts":
        _sql(s, "INSERT INTO receipts(clinic_id, number, issued_at, data) VALUES(?, 'DP-T-3', ?, '{}')", cid, NOW)
    elif label == "pay_attempts":
        _sql(s, "INSERT INTO payments(clinic_id, amount, method, status, reference, created_at) "
                "VALUES(?, 100, 'card', 'pending', 'DP-T-4', ?)", cid, NOW)
        pid = _sql(s, "SELECT id FROM payments WHERE reference='DP-T-4'")[0][0]
        _sql(s, "INSERT INTO pay_attempts(provider_id, payment_id, created_at) VALUES('pay-t-4', ?, ?)", pid, NOW)
    elif label == "sms_messages":
        _sql(s, "INSERT INTO sms_messages(clinic_id, idem, kind, sender, segments, state, sent_at, state_at) "
                "VALUES(?, 'i1', 'day_before', 'DentPilot', 1, 'delivered', ?, ?)", cid, NOW, NOW)
    elif label == "sms_ledger":
        _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who) VALUES(?, -1, 'send', ?, 'program')", cid, NOW)
    elif label == "clinic_contracts":
        _sql(s, "INSERT INTO clinic_contracts(clinic_id, doc, file, sha256, uploaded_at, who) "
                "VALUES(?, 'contract', 'x.pdf', 'ab', ?, 'Ion')", cid, NOW)
    elif label == "sms_papers":
        _sql(s, "INSERT INTO sms_papers(clinic_id, sender, body, size, sha256, uploaded_at, who) "
                "VALUES(?, 'Zambet', X'25504446', 4, 'ab', ?, 'Ion')", cid, NOW)


def suite_blockers(res: Result) -> None:
    """Каждый запрет: страница открыта, когда держать было нечего; строка появилась; POST — отказ, клиника цела,
    вкладка «Архив» называет причину словами."""
    with Server(env=ENV) as s:
        admin = Client(s.url).login()
        payer = _admin_clinic(admin, "Clinica Plătitor", "1002600003778", "plat@example.md")
        idnos = iter(["1003600012344", "1003600099994", "1003600088882", "1003600011118", "1003600022220",
                      "1003600033332", "1003600055556", "1234567890122"])
        res.check("запреты удаления — ровно эти (решение Олега 11.11)", [(t, lab) for t, lab, _ in archive.BLOCKERS],
                  list(BLOCKED))
        for table, label in BLOCKED:      # свой список, не archive.BLOCKERS: выкинутый запрет обязан покраснеть здесь
            cid = _admin_clinic(admin, f"Clinica {table}", next(idnos), f"{table}@example.md")
            admin.post(f"/admin/clinics/{cid}/archive", reason="demo")
            stale = _pane(admin.get("/admin").body, "archive")
            res.ok(f"{table}: до строки — форма удаления на странице", f"action='/admin/clinics/{cid}/delete'" in stale)
            _block(s, table, cid, payer)
            r = _delete(admin, cid)
            res.check(f"{table}: удаление по старой странице — отказ, клиника цела",
                      (_msg(r), _sql(s, "SELECT count(*) FROM clinics WHERE id=?", cid)[0][0]), (archive.BLOCKED, 1))
            arc = _pane(admin.get("/admin").body, "archive")
            row = arc[arc.find(f"/admin/clinics/{cid}'"):]
            row = row[:row.find("</tr>")]
            res.ok(f"{table}: «Архив» называет «{label}», формы удаления нет",
                   f"{label}: " in row and f"action='/admin/clinics/{cid}/delete'" not in row, row[:200])
        res.ok("журнал: отказы записаны (delete_refused)",
               _sql(s, "SELECT count(*) FROM audit WHERE what='delete_refused'")[0][0] == len(BLOCKED))
        cid = _admin_clinic(admin, "Clinica Bonus", "1020608000025", "bonus@example.md")
        admin.post(f"/admin/clinics/{cid}/archive")
        _sql(s, "INSERT INTO sms_ledger(clinic_id, delta, reason, at, who, note) VALUES(?, 30, 'bonus', ?, 'server', "
                "'perioada de probă')", cid, NOW)
        res.check("пробный бонус SMS (не деньги и не отправка) удалению не мешает", _msg(_delete(admin, cid)), archive.DELETED)


if __name__ == "__main__":
    from harness import run
    sys.exit(run([("schema", suite_schema), ("archive", suite_archive), ("delete", suite_delete),
                  ("blockers", suite_blockers)]))
