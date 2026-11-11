"""Флот (шаг 3, 02.10): компьютеры клиник из заголовков программы, страница и JSON.

Главное из cloud.md › «Флот»: строка на компьютер заводится и обновляется
запросами самой программы (/v1/license, /v1/trial, /v1/verify) по заголовкам
X-DentPilot-*; мусор в заголовках строки не заводит; «отстаёт» — сравнение с
последним выпуском GitHub (стенд), «молчит» — давно без связи; JSON того же
отчёта отвечает 401 без куки, а не 303 на вход.
"""
import json
import sqlite3
import sys

from harness import CLOUD, ROOT, Client, Result, Server, cid_from, load_by_path
from test_account import DIRECTOR, FakeGitHub, FakeGoogle, _google_login

sys.path.insert(0, str(CLOUD))
from app import fleet  # noqa: E402

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
DEV1, DEV2 = "d_0123456789ab", "d_fedcba987654"


def _hdr(device: str = DEV1, version: str = "1.35.2", channel: str = "stable",
         os_: str = "Windows 11 (10.0.26200)", token: str = "") -> dict:
    h = {"User-Agent": f"DentPilot/{version}", "X-DentPilot-Device": device,
         "X-DentPilot-Channel": channel, "X-DentPilot-OS": os_}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def _devices(s: Server):
    return _sql(s, "SELECT id, clinic_id, version, channel, os, last_seq FROM devices ORDER BY id")


def suite_rules(res: Result) -> None:
    """Чистые правила: заголовки → личность, сравнение версий."""
    class R:
        def __init__(self, h):
            self.headers = {k.lower(): v for k, v in h.items()}
    good = fleet.from_request(R(_hdr()))
    res.check("личность из заголовков", good, {"id": DEV1, "version": "1.35.2", "channel": "stable",
                                                  "os": "Windows 11 (10.0.26200)"})
    res.check("без X-DentPilot-Device — не программа", fleet.from_request(R({"User-Agent": "DentPilot/1.0.0"})), None)
    res.check("кривой id — не программа", fleet.from_request(R(_hdr(device="d_xyz"))), None)
    weird = fleet.from_request(R(_hdr(version="x", channel="nightly", os_="  a  b " + "c" * 100)))
    res.ok("чужая версия, чужой канал, длинная ОС — пусто, пусто, обрезано",
           weird["version"] == "" and weird["channel"] == "" and len(weird["os"]) <= fleet.OS_MAX
           and weird["os"].startswith("a b"), repr(weird))
    res.ok("отстаёт: 1.35.2 < 1.35.3, 1.35.10 > 1.35.9, пустое не отстаёт",
           fleet.behind("1.35.2", "1.35.3") and not fleet.behind("1.35.10", "1.35.9")
           and not fleet.behind("", "1.35.3") and not fleet.behind("1.35.2", "") and not fleet.behind("1.35.3", "1.35.3"))


def suite_devices(res: Result) -> None:
    """Запросы программы заводят и обновляют компьютеры; страница, карточка, JSON, кабинет."""
    gh, g = FakeGitHub(), FakeGoogle()
    with Server(env={**gh.env, **g.env, "DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        admin = Client(s.url).login()
        res.ok("флот пуст: страница говорит об этом", "ещё не выходил на связь" in admin.get("/admin/fleet").body)
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Flotă", idno="1234567890122",
                                  email=DIRECTOR["email"]).location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        token = _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]
        anon = Client(s.url)
        r = anon.get("/v1/license?seq=0", headers=_hdr(token=token))
        res.ok("суточный запрос с заголовками: файл выдан, компьютер заведён с версией, каналом, ОС, seq 0",
               r.status == 200 and _devices(s) == [(DEV1, cid, "1.35.2", "stable", "Windows 11 (10.0.26200)", 0)],
               f"{r.status} {_devices(s)}")
        first = _sql(s, "SELECT first_seen_at, last_seen_at FROM devices WHERE id=?", DEV1)[0]
        r = anon.get("/v1/license?seq=1", headers=_hdr(version="1.35.3", channel="beta", token=token))
        row = _devices(s)[0]
        res.ok("второй запрос того же компьютера: 204, версия и канал обновлены, seq 1, строка одна",
               r.status == 204 and row == (DEV1, cid, "1.35.3", "beta", "Windows 11 (10.0.26200)", 1)
               and len(_devices(s)) == 1, f"{r.status} {row}")
        second = _sql(s, "SELECT first_seen_at, last_seen_at FROM devices WHERE id=?", DEV1)[0]
        res.ok("первый выход на связь не переписан, последний — не раньше первого",
               second[0] == first[0] and second[1] >= first[1])
        r = anon.get("/v1/license?seq=1", headers={"Authorization": f"Bearer {token}", "User-Agent": "DentPilot/1.35.3"})
        res.ok("запрос без X-DentPilot-Device (старая программа) — 204 и строки нет",
               r.status == 204 and len(_devices(s)) == 1)
        r = anon.get("/v1/license?seq=1", headers=_hdr(device="d_not-an-id!!", token=token))
        res.ok("кривой id — 204, строки нет", r.status == 204 and len(_devices(s)) == 1)
        r = anon.get("/v1/license?seq=0", headers=_hdr(device=DEV2, version="1.35.2", token=token))
        res.ok("второй компьютер клиники: своя строка", r.status == 200 and len(_devices(s)) == 2)
        r = anon.get("/v1/license?seq=1", headers=_hdr(token="not-a-token"))
        res.ok("чужой токен: 401 и строки не трогаются", r.status == 401 and len(_devices(s)) == 2)
        # страница флота: последний выпуск от стенда GitHub (1.35.3), отстаёт только 1.35.2
        page = admin.get("/admin/fleet").body
        everyone = page[page.index("data-pane='all'"):page.index("data-pane='behind'")]
        behind = page[page.index("data-pane='behind'"):page.index("data-pane='silent'")]
        res.ok("страница «Флот»: последний выпуск, оба компьютера, отстаёт ровно один, клиника со ссылкой",
               "Последний выпуск: <b>1.35.3</b>" in page and DEV1 in everyone and DEV2 in everyone
               and everyone.count(">отстаёт<") == 1 and f"/admin/clinics/{cid}" in page
               and "компьютеров 2 у 1 клиник · отстают 1 · молчат дольше недели 0" in page, page[-2500:])
        res.ok("вкладка «Отстают от выпуска» (17.10): ровно отставший, со счётчиком у вкладки",
               DEV2 in behind and DEV1 not in behind and "Отстают от выпуска<span class='n'>1</span>" in page)
        res.ok("шапка админки ведёт на флот", "href='/admin/fleet'>Флот</a>" in admin.get("/admin").body)
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("карточка клиники: раздел «Компьютеры» с обоими", "Компьютеры" in card and DEV1 in card and DEV2 in card)
        # JSON того же отчёта
        res.check("JSON без куки — 401, не 303", anon.get("/admin/api/fleet").status, 401)
        data = json.loads(admin.get("/admin/api/fleet").body)
        res.ok("JSON: latest, оба компьютера, counts, behind и state",
               data.get("ok") is True and data["data"]["latest"] == "1.35.3"
               and {d["device"] for d in data["data"]["devices"]} == {DEV1, DEV2}
               and data["data"]["counts"] == {"devices": 2, "clinics": 1, "behind": 1, "silent": 0, "multi_clinics": 1}
               and all(d["state"] == "active" and d["clinic"] == "Clinica Flotă" for d in data["data"]["devices"])
               and [d["behind"] for d in sorted(data["data"]["devices"], key=lambda d: d["device"])] == [False, True],
               json.dumps(data)[:600])
        # молчит: последняя связь 9 дней назад
        _sql(s, "UPDATE devices SET last_seen_at='2026-09-01T00:00:00Z' WHERE id=?", DEV2)
        data = json.loads(admin.get("/admin/api/fleet").body)["data"]
        res.ok("компьютер без связи дольше недели — silent", data["counts"]["silent"] == 1
               and next(d for d in data["devices"] if d["device"] == DEV2)["silent"] is True)
        res.ok("страница: «молчит» с числом дней", ">молчит<" in admin.get("/admin/fleet").body)
        # кабинет клиники видит свои компьютеры
        c = Client(s.url)
        res.check("директор входит по ящику клиники", _google_login(c, s, g).location, "/cont")
        home = c.get("/cont").body
        res.ok("кабинет: «Calculatoare cu DentPilot», версия и метка старой версии",
               "Calculatoare cu DentPilot" in home and "DentPilot 1.35.3" in home and "DentPilot 1.35.2" in home
               and home.count("versiune veche") == 1, home[-3000:])


def suite_activation(res: Result) -> None:
    """Заявка из программы и код: компьютер привязывается к клинике при активации."""
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        anon = Client(s.url)
        body = json.dumps({"name": "Clinica Nouă", "idno": "", "contact_name": "X", "email": "nou@example.md",
                           "phone": "", "consent": "1"}).encode()
        r = anon._do("/v1/trial", body, {"Content-Type": "application/json", **_hdr(version="1.36.0")})
        res.ok("заявка из программы с заголовками: клиника заведена, компьютер привязан к ней",
               r.status == 200 and len(_devices(s)) == 1 and _devices(s)[0][2] == "1.36.0"
               and _devices(s)[0][1] == _sql(s, "SELECT id FROM clinics")[0][0], f"{r.status} {_devices(s)}")
        cid = _devices(s)[0][1]
        # повтор с другого компьютера: до кода строки нет, после кода — есть
        r = anon._do("/v1/trial", body, {"Content-Type": "application/json", **_hdr(device=DEV2)})
        res.ok("повтор: 409 с verify_id, второй компьютер ещё не привязан",
               r.status == 409 and "verify_id" in r.body and len(_devices(s)) == 1, f"{r.status} {r.body[:200]}")
        vid = json.loads(r.body)["verify_id"]
        import email, email.policy, re
        letters = [email.message_from_bytes(f.read_bytes(), policy=email.policy.default) for f in sorted(s.outbox.glob("*.eml"))]
        code = next(re.search(r"(\d{6})", m.get_body(preferencelist=("plain",)).get_content()).group(1)
                    for m in letters if m["Subject"].startswith("DentPilot: codul de activare"))
        r = anon._do("/v1/verify", json.dumps({"verify_id": vid, "code": code}).encode(),
                     {"Content-Type": "application/json", **_hdr(device=DEV2, version="1.36.0")})
        res.ok("верный код: токен, второй компьютер привязан к той же клинике",
               r.status == 200 and [d[:2] for d in _devices(s)] == [(DEV1, cid), (DEV2, cid)], f"{r.status} {_devices(s)}")


def suite_device_taken(res: Result) -> None:
    """02.11: компьютер, уже записанный за клиникой, не получает второй пробный на новый ящик —
    409 со словами, которые программа покажет как есть (провод bot/app/core/license_renew.py,
    без правки клиента); свою клинику он находит кодом, как раньше; скрытая заявка компьютер
    не держит. Заявок здесь ровно пять — лимит с адреса (trial.MAX_PER_HOUR)."""
    from app import views  # noqa: E402 — текст отказа
    rn = load_by_path("license_renew", ROOT / "bot" / "app" / "core" / "license_renew.py")
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        anon = Client(s.url)

        def trial(email_: str, name: str = "Clinica Nouă", idno: str = "") -> tuple[int, dict]:
            body = json.dumps({"name": name, "idno": idno, "contact_name": "X", "email": email_,
                               "phone": "", "consent": "1"}).encode()
            r = anon._do("/v1/trial", body, {"Content-Type": "application/json", **_hdr()})
            return r.status, json.loads(r.body or "{}")

        st, d = trial("nou@example.md")
        cid = _sql(s, "SELECT id FROM clinics")[0][0]
        res.ok("первая заявка: клиника заведена, компьютер у неё", st == 200 and _devices(s)[0][:2] == (DEV1, cid),
               f"{st} {d}")
        n_letters = len(list(s.outbox.glob("*.eml")))
        st, d = trial("alta@example.md", name="Clinica Alta")
        res.ok("тот же компьютер, новый ящик: 409 device_taken со словами, без verify_id и токена",
               st == 409 and d.get("code") == "device_taken" and d.get("text") == views.TRIAL_MSG["device_taken"]
               and "verify_id" not in d and "token" not in d, f"{st} {d}")
        res.ok("…новой клиники нет, компьютер остался у первой, писем не ушло",
               _sql(s, "SELECT count(*) FROM clinics")[0][0] == 1 and _devices(s)[0][:2] == (DEV1, cid)
               and len(list(s.outbox.glob("*.eml"))) == n_letters)
        res.ok("…в журнале — повторная заявка с причиной reason=device, компьютером и владельцем (без clinic_id)",
               any(why.startswith("reason=device") and DEV1 in why and cid in why for why, in
                   _sql(s, "SELECT detail FROM audit WHERE what='trial_duplicate' AND clinic_id IS NULL")))
        res.ok("текст отказа чужую клинику не называет", "Clinica Nouă" not in views.TRIAL_MSG["device_taken"]
               and "nou@" not in d.get("text", ""))
        st, d = trial("nou@example.md")
        res.ok("свою клинику тот же компьютер находит как раньше: 409 с verify_id (код на её e-mail)",
               st == 409 and d.get("code") == "duplicate" and d.get("verify_id"), f"{st} {d}")
        outcome, data = rn.request_trial(s.url + "/v1/trial", {"name": "Clinica Alta", "idno": "", "contact_name": "X",
                                                               "email": "alta2@example.md", "phone": "", "consent": "1"},
                                         extra={k: v for k, v in _hdr().items() if k != "User-Agent"},
                                         agent="DentPilot/2.7.0")
        res.ok("провод программы читает отказ как REJECTED со словами сервера и без verify_id (REQUEST_REFUSED)",
               outcome == rn.REJECTED and data.get("text") == views.TRIAL_MSG["device_taken"]
               and "verify_id" not in data, f"{outcome} {data}")
        _sql(s, "UPDATE clinics SET declined_at='2026-11-02T10:00:00Z' WHERE id=?", cid)
        st, d = trial("alta3@example.md", name="Clinica Alta")
        res.ok("скрытая заявка компьютер не держит: новая клиника заведена, компьютер переехал",
               st == 200 and d.get("token") and _devices(s)[0][1] != cid, f"{st} {d}")


def _code_to(s: Server, to: str) -> str:
    """Шестизначный код из последнего письма «codul de activare» на адрес `to`."""
    import email
    import email.policy
    import re
    for f in sorted(s.outbox.glob("*.eml"), reverse=True):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        if to in str(m["To"]) and m["Subject"].startswith("DentPilot: codul de activare"):
            hit = re.search(r"\b(\d{6})\b", m.get_body(preferencelist=("plain",)).get_content())
            return hit.group(1) if hit else ""
    return ""


def suite_device_kept(res: Result) -> None:
    """02.11 (Олег: «Да, закрыть»): компьютер пробной клиники не получает второй пробный обходом —
    новый ящик через /proba (сайт, без компьютера) и код в программе (/v1/verify). Отказ 409 словами,
    которые программа показывает на экране кода (провод bot/app/core/license_renew.py); своя клиника и
    платная — как раньше. Заявок здесь пять — лимит с адреса (trial.MAX_PER_HOUR)."""
    from app import views  # noqa: E402 — текст отказа
    rn = load_by_path("license_renew", ROOT / "bot" / "app" / "core" / "license_renew.py")
    extra = {k: v for k, v in _hdr().items() if k != "User-Agent"}
    with Server(env={"DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        anon = Client(s.url)

        def trial(email_: str, name: str) -> dict:
            out, data = rn.request_trial(s.url + "/v1/trial", {"name": name, "idno": "", "contact_name": "X",
                                                               "email": email_, "phone": "", "consent": "1"},
                                         extra=extra, agent="DentPilot/2.7.0")
            return data

        def verify(vid: str, to: str) -> tuple[str, dict]:
            return rn.verify_code(s.url + "/v1/verify", vid, _code_to(s, to), extra=extra, agent="DentPilot/2.7.0")

        trial("a@example.md", "Clinica A")
        a = _sql(s, "SELECT id FROM clinics WHERE email='a@example.md'")[0][0]
        res.ok("компьютер у пробной клиники A", _devices(s)[0][:2] == (DEV1, a), _devices(s))
        r = anon.post("/proba", name="Clinica B", idno="", contact_name="X", email="b@example.md", phone="",
                      consent="1")
        b = _sql(s, "SELECT id FROM clinics WHERE email='b@example.md'")
        res.ok("сайт: новый пробный B на новый ящик (без компьютера)", r.status == 200 and len(b) == 1, r.status)
        b = b[0][0] if b else ""
        vid = trial("b@example.md", "Clinica B").get("verify_id", "")
        out, data = verify(vid, "b@example.md")
        res.ok("код B на компьютере A: REJECTED словами device_kept (экран кода, не «нет связи»), без токена",
               out == rn.REJECTED and data.get("text") == views.TRIAL_MSG["device_kept"] and "token" not in data,
               f"{out} {data}")
        res.ok("…компьютер остался у A, в журнале reason=device с обеими клиниками",
               _devices(s)[0][:2] == (DEV1, a)
               and any(why.startswith("reason=device") and a in why and b in why for why, in
                       _sql(s, "SELECT detail FROM audit WHERE what='trial_duplicate' AND clinic_id IS NULL")))
        res.ok("текст на экране кода не зовёт вводить IDNO и даёт контакт",
               "IDNO" not in views.TRIAL_MSG["device_kept"] and "@" in views.TRIAL_MSG["device_kept"])
        vid = trial("a@example.md", "Clinica A").get("verify_id", "")
        out, data = verify(vid, "a@example.md")
        res.ok("своя клиника: код A на компьютере A — токен, как раньше", out == rn.ACCEPTED and data.get("token"),
               f"{out} {data}")
        _sql(s, "UPDATE subscriptions SET plan='standard' WHERE clinic_id=?", b)
        vid = trial("b@example.md", "Clinica B").get("verify_id", "")
        out, data = verify(vid, "b@example.md")
        res.ok("платная клиника B: код на компьютере A — токен, компьютер переехал (device_moved), как раньше",
               out == rn.ACCEPTED and data.get("token") and _devices(s)[0][:2] == (DEV1, b), f"{out} {data}")
        # «ни одной оплаты» — своей нотой или строкой общей ноты кабинета (чистая функция, без commit)
        from app import trial  # noqa: E402
        con = sqlite3.connect(s.dir / "cloud.db")
        con.row_factory = sqlite3.Row
        try:
            now = "2026-11-02T10:00:00Z"
            con.execute("INSERT INTO payments(clinic_id, amount, method, status, reference, created_at) "
                        "VALUES(?, 400, 'transfer', 'pending', 'T-1', ?)", (a, now))
            pending = trial.unpaid_trial(con, a)
            pid = con.execute("INSERT INTO payments(clinic_id, amount, method, status, reference, created_at) "
                              "VALUES(?, 800, 'transfer', 'paid', 'T-2', ?)", (b, now)).lastrowid
            con.execute("INSERT INTO payment_lines(payment_id, clinic_id, tier, months, amount) "
                        "VALUES(?, ?, 'plus', 1, 400)", (pid, a))
            res.ok("unpaid_trial: ожидающая нота — ещё не оплата; строка оплаченной общей ноты — оплата",
                   pending is True and trial.unpaid_trial(con, a) is False)
        finally:
            con.close()
