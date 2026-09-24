"""Ежедневная задача (L9): окна напоминаний, письма, повтор в тот же день, новый период.

Окна проверяются чистой функцией с подставной датой на каждую строку таблицы
cloud.md › «Напоминания». Живым сервером — то, что видно только целиком: задача
запускается как из cron (отдельным процессом с окружением сервера и --at),
письма ложатся в outbox, отправленное — в reminders, второй запуск в тот же
день ничего не шлёт, продление открывает новый период.
"""
import email
import email.policy
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

from harness import CLOUD, Client, Result, Server, cid_from

sys.path.insert(0, str(CLOUD))
from app import jobs  # noqa: E402 — чистые функции сервера
from app import payments as pay  # noqa: E402

BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}
D = timedelta(days=1)


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _clinic(c: Client, **over) -> str:
    f = dict(name="Clinica Zilnic", idno="1234567890123", contact_name="Ion", email="zilnic@example.md", phone="")
    f.update(over)
    return cid_from(c.post("/admin/clinics", **f).location)


def _run(s: Server, at: date) -> tuple[int, str]:
    """Задача как из cron: отдельный процесс, окружение сервера, подставная дата."""
    p = subprocess.run([sys.executable, "-m", "app.jobs", "daily", "--at", f"{at:%Y-%m-%d}T06:00:00Z"],
                       cwd=str(CLOUD), env=s.env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return p.returncode, p.stdout + p.stderr


def _letters(s: Server) -> list[tuple[str, str, str]]:
    """(тема, текст, кому) по порядку отправки."""
    out = []
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        out.append((m["Subject"], m.get_body(preferencelist=("plain",)).get_content(), m["To"]))
    return out


def _kinds(s: Server, cid: str) -> list[tuple[str, str]]:
    return [(r[0], r[1][:10]) for r in _sql(s, "SELECT kind, period FROM reminders WHERE subscription_id=? "
                                                   "ORDER BY sent_at, rowid", cid)]


def suite_windows(res: Result) -> None:
    v, g = date(2026, 10, 31), date(2026, 11, 14)      # абонемент, льгота 14
    table = [(-20, None), (-15, None), (-14, "invoice"), (-13, "invoice"), (-4, "invoice"),
             (-3, "expiring"), (-1, "expiring"), (0, "expired"), (12, "expired"), (13, "last_warning"),
             (14, "readonly"), (43, "readonly"), (44, None)]
    for off, want in table:
        res.check(f"абонемент, льгота 14: день {off:+d} → {want}", jobs.due(v, g, "standard", v + off * D), want)
    t, tg = date(2026, 10, 8), date(2026, 10, 11)       # пробный 14 + 3
    for off, want in [(-14, None), (-4, None), (-3, "expiring"), (0, "expired"), (1, "expired"),
                      (2, "last_warning"), (3, "readonly"), (32, "readonly"), (33, None)]:
        res.check(f"пробный, льгота 3: день {off:+d} → {want}", jobs.due(t, tg, "trial", t + off * D), want)
    for off, want in [(-3, "expiring"), (-1, "last_warning"), (0, "readonly")]:
        res.check(f"льгота 0: день {off:+d} → {want}", jobs.due(v, v, "standard", v + off * D), want)
    res.check("льгота 1: в день срока — завтра только чтение", jobs.due(v, v + D, "standard", v), "last_warning")
    res.check("порядок строк — как в таблице", [k for k, _, _ in jobs.windows(v, g, "standard")], list(jobs.KINDS))
    res.check("пробному — без строки счёта", [k for k, _, _ in jobs.windows(t, tg, "trial")], list(jobs.KINDS[1:]))
    res.ok("окна одного тарифа не пересекаются при льготе ≥ 2",
           all(e1 <= s2 for (_, _, e1), (_, s2, _) in zip(jobs.windows(v, g, "standard"),
                                                          jobs.windows(v, g, "standard")[1:])))


def suite_daily(res: Result) -> None:
    with Server(env=BANK_ENV) as s:
        c = Client(s.url).login()
        cid = _clinic(c)
        today = datetime.now(timezone.utc).date()
        v = today + 60 * D
        r = c.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}", grace_days="14")
        res.check("абонемент до даты выдан", r.location, f"/admin/clinics/{cid}?msg=issued")
        year = datetime.now(timezone.utc).year
        ref1 = f"DP-{year}-000001"

        rc, out = _run(s, v - 20 * D)
        res.ok("за 20 дней: ничего, код 0", rc == 0 and "писем: 0" in out and not _letters(s), out[-300:])
        rc, out = _run(s, v - 14 * D)
        res.ok("за 14 дней: одно письмо, код 0", rc == 0 and "писем: 1" in out and len(_letters(s)) == 1, out[-300:])
        subj, body, to = _letters(s)[0]
        res.ok("счёт: reference в теме, дата срока, реквизиты, назначение платежа",
               f"nota de plată {ref1}" in subj and f"{v:%d.%m.%Y}" in subj and "MD00TEST0000000000000001" in body
               and f"Destinația plății: {ref1}" in body and to == "zilnic@example.md", subj + body[:200])
        res.check("платёж создан задачей: ожидает, 1 мес., по тарифу",
                  _sql(s, "SELECT status, months, amount FROM payments WHERE clinic_id=?", cid),
                  [("pending", 1, 399)])
        res.check("reminders: счёт за период", _kinds(s, cid), [("invoice", f"{v:%Y-%m-%d}")])
        rc, out = _run(s, v - 14 * D)
        res.ok("второй запуск в тот же день — ни одного письма", "писем: 0" in out and len(_letters(s)) == 1, out[-200:])
        rc, out = _run(s, v - 13 * D)
        res.ok("на следующий день в том же окне — тоже ничего", "писем: 0" in out and len(_letters(s)) == 1)

        _run(s, v - 3 * D)
        res.check("за 3 дня: второе письмо", len(_letters(s)), 2)
        subj, body, _ = _letters(s)[1]
        res.ok("«expiră în 3 zile», тот же reference, без второго платежа",
               "abonamentul expiră în 3 zile" in subj and ref1 in body
               and _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=?", cid)[0][0] == 1, subj)
        _run(s, v)
        subj, body, _ = _letters(s)[2]
        g = v + 14 * D
        res.ok("в день срока: «a expirat — 14 zile pentru plată», дата конца льготы",
               "abonamentul a expirat — 14 zile pentru plată" in subj and f"{g:%d.%m.%Y}" in body
               and "regim de citire" in body, subj)
        _run(s, v + 5 * D)
        res.check("в середине льготы — ничего нового", len(_letters(s)), 3)
        _run(s, v + 13 * D)
        subj, body, _ = _letters(s)[3]
        res.ok("накануне: «de mâine … regim de citire»", "de mâine programul trece în regim de citire" in subj, subj)
        _run(s, v + 14 * D)
        subj, body, _ = _letters(s)[4]
        res.ok("в день льготы: «este în regim de citire», что остаётся доступным",
               "programul este în regim de citire" in subj and "se pot consulta, tipări și exporta" in body, subj)
        _run(s, v + 15 * D)
        _run(s, v + 44 * D)
        res.check("после — ничего: писем пять", len(_letters(s)), 5)
        res.check("reminders: пять строк одного периода", _kinds(s, cid),
                  [(k, f"{v:%Y-%m-%d}") for k in jobs.KINDS])
        res.check("журнал: reminder на каждое письмо",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='reminder' AND clinic_id=?", cid)[0][0], 5)
        res.check("журнал: строка daily на каждый из 11 запусков",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='daily'")[0][0], 11)

        # оплата открывает новый период — напоминания идут заново, с новым reference
        pid = _sql(s, "SELECT id FROM payments WHERE reference=?", ref1)[0][0]
        r = c.post(f"/admin/payments/{pid}/confirm")
        res.ok("платёж подтверждён — новый файл", "payment_confirmed" in r.location, r.location)
        v2 = pay.add_months(datetime(v.year, v.month, v.day, tzinfo=timezone.utc), 1).date()
        res.check("срок — месяц от прежнего конца", _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?",
                                                        cid)[0][0][:10], f"{v2:%Y-%m-%d}")
        n = len(_letters(s))
        _run(s, v2 - 14 * D)
        res.check("новый период: счёт снова", len(_letters(s)), n + 1)
        subj, body, _ = _letters(s)[-1]
        res.ok("новый reference в счёте", f"DP-{year}-000002" in subj and f"{v2:%d.%m.%Y}" in subj, subj)
        res.check("reminders: старый период остался, новый начат",
                  _kinds(s, cid)[-2:], [("readonly", f"{v:%Y-%m-%d}"), ("invoice", f"{v2:%Y-%m-%d}")])
        card = c.get(f"/admin/clinics/{cid}").body
        res.ok("карточка: таблица напоминаний с русскими названиями",
               "Напоминания" in card and "счёт за 14 дней" in card and "режим только чтения" in card)


def suite_edges(res: Result) -> None:
    with Server() as s:      # без реквизитов банка
        res.check("задача без входа: на вход", Client(s.url).post("/admin/jobs/daily").status, 303)
        res.check("журнал без входа: на вход", Client(s.url).get("/admin/audit").status, 303)
        c = Client(s.url).login()
        today = datetime.now(timezone.utc).date()

        # пробный: свой текст, свой срок, платёж не заводится
        ct = _clinic(c, name="Clinica Probă", idno="", email="proba@example.md")
        c.post(f"/admin/clinics/{ct}/issue", kind="trial")
        t = today + 14 * D
        rc, out = _run(s, today)
        res.ok("пробному счёт не шлётся", "писем: 0" in out and not _letters(s), out[-200:])
        _run(s, t)
        subj, body, _ = _letters(s)[0]
        res.ok("пробный истёк: «perioada de probă … 3 zile pentru abonare», как оформить, без IBAN",
               "perioada de probă a expirat — 3 zile pentru abonare" in subj and "399 MDL pe lună" in body
               and "IDNO" in body and "IBAN" not in body, subj + body[:200])
        res.check("платежей у пробного нет", _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=?", ct)[0][0], 0)
        _run(s, t + 3 * D)
        subj, body, _ = _letters(s)[1]
        res.ok("пробный в режиме чтения", "programul este în regim de citire" in subj and "perioada de probă" in body, subj)

        # без e-mail — пропуск словами, без записи; без реквизитов — счёт «придёт отдельно»
        v = today + 60 * D
        cn = _clinic(c, name="Fără Email", email="")
        c.post(f"/admin/clinics/{cn}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}")
        cb = _clinic(c, name="Fără Bancă", email="banca@example.md")
        c.post(f"/admin/clinics/{cb}/issue", kind="dates", valid_until=f"{v:%Y-%m-%d}")
        rc, out = _run(s, v - 14 * D)
        res.ok("без e-mail: пропущено словами, код 0", rc == 0 and f"пропущено {cn}: нет e-mail" in out, out[-300:])
        res.check("без e-mail: в reminders ничего", _kinds(s, cn), [])
        subj, body, to = _letters(s)[2]
        res.ok("без реквизитов: счёт с reference, «o primiți separat», без IBAN",
               "nota de plată DP-" in subj and "o primiți separat" in body and "IBAN" not in body
               and to == "banca@example.md", subj + body[:200])
        res.check("платёж при этом создан", _sql(s, "SELECT status FROM payments WHERE clinic_id=?", cb), [("pending",)])
        res.check("писем всего три", len(_letters(s)), 3)
        rc, out = _run(s, v - 14 * D)
        res.ok("повтор: ничего", "писем: 0" in out and "пропущено" in out and len(_letters(s)) == 3)

        p = subprocess.run([sys.executable, "-m", "app.jobs", "daily", "--at", "вчера"], cwd=str(CLOUD),
                           env=s.env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        res.check("--at не дата: отказ", p.returncode, 2)

        # кнопка в админке — тот же проход, что cron; сводка состояний и журнал
        r = c.post("/admin/jobs/daily")
        res.check("кнопка: выполнено", r.location, "/admin?msg=daily_done")
        rows = _sql(s, "SELECT who, detail FROM audit WHERE what='daily' ORDER BY id DESC LIMIT 1")
        res.ok("журнал: строка daily от администратора с итогом",
               rows and rows[0][0] == "oleg" and "писем: 0" in rows[0][1], repr(rows))
        page = c.get("/admin?msg=daily_done").body
        res.ok("список: сводка состояний и кнопка",
               "Состояния:" in page and "действует 3" in page and "нет файла 0" in page
               and "Запустить ежедневную задачу" in page and "Ежедневная задача выполнена" in page)
        log = c.get("/admin/audit").body
        res.ok("страница журнала: daily, reminder, ссылка на клинику",
               "daily" in log and "reminder" in log and f"/admin/clinics/{cb}" in log and "Fără Bancă" in log)
        res.check("страница журнала — 200", c.get("/admin/audit").status, 200)
