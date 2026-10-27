"""Филиал = ещё одна клиника в том же кабинете (26.10.2026, Олег): «если клиника имеет филиалы
значит пускай платит … на каждый отдельная лицензия, один кабинет админ».

Что держит набор:
- один вход → несколько клиник; «Adaugă clinică» — клиника теми же правилами, тот же IDNO и ящик
  разрешены ВНУТРИ кабинета, чужой клинике — отказ; форма несёт свою клинику (?c=), форма без неё
  при нескольких клиниках не пишет ни в одну;
- клиника из «Adaugă clinică» без пробного и без одобрения (Олег 27.10): нота первого периода и
  файл на срок её оплаты, оплата в срок — период от дня заведения;
- код компьютера из кабинета — 7 цифр (поле кода программы 2.0.9 — maxlength 7): привязывает
  компьютер к своей клинике, код из письма — к той, что нашла заявка; одноразовый, свой кабинет,
  ошибки считаются verify_id;
- общая нота: строки по клиникам, заменяет их ноты, клинике в ней своя нота не выставляется,
  после оплаты каждая продлевается своим файлом, cont de plată — один со строками;
- имя отправителя SMS общее на кабинет, остаток — свой;
- админка: клиники кабинета, «Добавить клинику в кабинет», подсказка флота, переезд компьютера.
Цены прогона — не настоящие (harness: DP_PRICE_*).
"""
import email
import email.policy
import json
import re
import sqlite3
import sys

from harness import CLOUD, FIX, ROOT, Client, Result, Server, load_by_path

sys.path.insert(0, str(CLOUD))
from app import account, db, tiers  # noqa: E402
from app import payments as pay  # noqa: E402

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}
IDNO = "1003600012345"
DIRECTOR = "director@zambet.md"
MAIN = dict(name="Clinica Zambet", idno=IDNO, contact_name="Ion Rusu", phone="022123456", consent="1")
BRANCH = dict(name="Zambet Botanica", address="bd. Dacia 27, Chisinau", phone="022555010",
              contact_name="Ion Rusu", email="botanica@zambet.md", idno=IDNO, consent="1", tier="plus", months="1")
DEV1, DEV2, DEV3 = "d_0000000000a1", "d_0000000000b2", "d_0000000000c3"


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db", timeout=10)
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()                     # UPDATE из теста без commit откатился бы при close
        return rows
    finally:
        con.close()


def _letters(s: Server) -> list[tuple[str, str, str, list]]:
    out = []
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        out.append((m["To"], m["Subject"], m.get_body(preferencelist=("plain",)).get_content(),
                    [p.get_filename() for p in m.walk() if p.get_filename()]))
    return out


def _enter(s: Server, mail_to: str) -> Client:
    """Вход в кабинет кодом на e-mail — так же, как человек."""
    c = Client(s.url)
    r = c.post("/cont/login/email", email=mail_to)
    vid = re.search(r"name='verify_id' value='([^']+)'", r.body).group(1)
    code = re.search(r": (\d{6})\n", [x for x in _letters(s) if x[0] == mail_to.strip().lower()][-1][2]).group(1)
    r = c.post("/cont/login/cod", verify_id=vid, code=code, email=mail_to)
    assert r.status == 303, f"вход {mail_to}: {r.status} {r.location}"
    return c


def _register(s: Server, c: Client) -> str:
    """Главная клиника: регистрация из кабинета → id."""
    r = c.post("/cont/inregistrare", **MAIN)
    assert r.status == 303 and r.location.startswith("/cont?msg=registered"), f"регистрация: {r.status} {r.location}"
    return _sql(s, "SELECT id FROM clinics WHERE name=?", MAIN["name"])[0][0]


def _add(c: Client, main_id: str, **over) -> tuple:
    """«Adaugă clinică» из кабинета → (ответ, код с клеток страницы или '')."""
    r = c.post(f"/cont/clinica-noua?c={main_id}", **dict(BRANCH, **over))
    code = "".join(re.findall(r"<span>(\d)</span>", r.body[r.body.find("class='code'"):][:2000]))
    return r, code


def _hdr(device: str, version: str = "2.2.0") -> dict:
    return {"User-Agent": f"DentPilot/{version}", "X-DentPilot-Device": device, "X-DentPilot-Channel": "stable",
            "X-DentPilot-OS": "Windows 11", "Content-Type": "application/json"}


def _api(c: Client, path: str, body: dict, device: str = "") -> tuple[int, dict]:
    r = c._do(path, json.dumps(body).encode("utf-8"), _hdr(device) if device else {"Content-Type": "application/json"})
    try:
        return r.status, json.loads(r.body)
    except ValueError:
        return r.status, {}


def _known(c: Client, device: str, mail_to: str = DIRECTOR) -> str:
    """Программа на новом компьютере: заявка с тем же IDNO → «клиника известна» → verify_id."""
    st, d = _api(c, "/v1/trial", dict(name="Filiala", idno=IDNO, contact_name="Ion", email=mail_to,
                                      phone="", consent="1"), device)
    assert st == 409 and d.get("verify_id"), f"заявка-повтор: {st} {d}"
    return d["verify_id"]


def _token_of(s: Server, cid: str) -> str:
    return _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0]


def suite_rules(res: Result) -> None:
    """Чистые правила: формат кода кабинета, хеш без открытого кода."""
    res.ok("код кабинета — ровно 7 цифр (поле программы 2.0.9 — maxlength 7)",
           account.CODE_DIGITS == 7 and account.is_cabinet_code("0123456") and not account.is_cabinet_code("012345")
           and not account.is_cabinet_code("01234567") and not account.is_cabinet_code("01234a6"))
    res.ok("код из письма (6 цифр) кодом кабинета не считается", not account.is_cabinet_code("123456"))
    res.ok("хеш кода не равен коду и не совпадает у разных кодов",
           account._hash("1234567") != "1234567" and account._hash("1234567") != account._hash("1234568"))
    res.ok("в общей ноте — не больше GROUP_MAX клиник (cont de plată — одна страница)", pay.GROUP_MAX == 10)


def suite_order(res: Result) -> None:
    """Главная кабинета детерминирована при ОДИНАКОВОЙ секунде заведения: второй ключ — порядок
    заведения (rowid), не случайный id. id подобраны НАОБОРОТ порядку заведения (главная — «c_f…»,
    филиалы — «c_0…»), метки времени равны: порядок по id дал бы филиал — красное всегда."""
    from app import cabinet, sms  # noqa: PLC0415 — нужны только этому набору
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for step in range(1, db.SCHEMA_VERSION + 1):
        for sql in db.MIGRATIONS[step]:
            con.execute(sql)
    at = "2026-10-26T10:00:00Z"
    main, b1, b2 = "c_ffffffffffff", "c_000000000001", "c_000000000000"
    for cid, name, mail_ in ((main, "Principala", "office@zambet.md"), (b1, "Filiala 1", "f1@zambet.md"),
                             (b2, "Filiala 2", "office@zambet.md")):
        con.execute("INSERT INTO clinics(id, name, email, created_at) VALUES(?,?,?,?)", (cid, name, mail_, at))
    con.execute("INSERT INTO accounts(id, provider, subject, email, clinic_id, created_at) "
                "VALUES('a_dir', 'google', 's', 'dir@zambet.md', ?, ?)", (b2, at))
    for cid in (b2, b1, main):                   # входы — в обратном порядке, тоже не в счёт
        con.execute("INSERT INTO account_clinics(account_id, clinic_id, added_at) VALUES('a_dir', ?, ?)", (cid, at))
    res.check("кабинет по порядку заведения: главная первой, хотя id у неё «наибольший»",
              [r["id"] for r in cabinet.of(con, b2)], [main, b1, b2])
    res.ok("главная одна и та же, с какой клиники ни спроси",
           all(cabinet.main_of(con, x)["id"] == main for x in (main, b1, b2)))
    res.check("клиники учётной записи — в том же порядке", [r["id"] for r in cabinet.of_account(con, "a_dir")],
              [main, b1, b2])
    res.check("имя SMS филиала — у главной", sms.name_owner(con, b1), main)
    con.execute("INSERT INTO accounts(id, provider, subject, email, created_at) "
                "VALUES('a_new', 'email', 'office@zambet.md', 'office@zambet.md', ?)", (at,))
    acc = con.execute("SELECT * FROM accounts WHERE id='a_new'").fetchone()
    account.link_by_email(con, acc, "office@zambet.md")
    res.check("вход по ящику: обе клиники с ящиком, открыта главная",
              ({r["clinic_id"] for r in con.execute("SELECT clinic_id FROM account_clinics WHERE account_id='a_new'")},
               con.execute("SELECT clinic_id FROM accounts WHERE id='a_new'").fetchone()[0]),
              ({main, b2}, main))
    con.execute("INSERT INTO payments(clinic_id, amount, method, status, reference, created_at, kind) "
                "VALUES(?, 3, 'transfer', 'pending', 'DP-2026-000001', ?, 'cabinet')", (main, at))
    for cid in (b2, main, b1):
        con.execute("INSERT INTO payment_lines(payment_id, clinic_id, tier, months, amount) VALUES(1, ?, 'plus', 1, 1)",
                    (cid,))
    res.check("строки общей ноты — в порядке клиник кабинета", [r["clinic_id"] for r in pay.lines_of(con, 1)],
              [main, b1, b2])
    con.close()


def suite_forms(res: Result) -> None:
    """«0 MDL» (кадр Олега 26.10, живой кабинет): нота SMS (months = 0) принималась за ноту
    абонемента — «Altă variantă» без отмеченного срока и сумма 0. Форма выбора: срок только из
    ряда (иначе месяц) и обязателен; сумма — сервером, без скрипта; общая нота — тоже; в кабинете
    ноты SMS — своими строками с реквизитами."""
    import re as _re  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415
    from app import views  # noqa: PLC0415 — нужны только этому набору
    now = datetime.now(timezone.utc)
    trial = {"plan": "trial", "tier": "plus", "price": 0, "grace_days": 7, "valid_until": None, "sms_until": None}
    plus = tiers.list_price("plus")
    form0 = views.tier_form(trial, "/x", False, now, months=0)
    res.ok("срок не из ряда (0 — как у ноты SMS) — отмечен месяц, сумма месяца, не 0",
           "name='months' value='1' checked required" in form0
           and f"<span class='s'>{views._mdl(plus)} MDL</span>" in form0 and "<span class='s'>0 MDL</span>" not in form0,
           form0[-900:])
    form12 = views.tier_form(trial, "/x", False, now, months=12)
    res.ok("год — отмечен год, сумма года сразу", "name='months' value='12' checked required" in form12
           and f"<span class='s'>{views._mdl(pay.amount(12, plus))} MDL</span>" in form12)
    res.check("выбор срока обязателен: у обоих вариантов required",
              len(_re.findall(r"name='months' value='(?:1|12)'[^>]*required", form0)), 2)
    rows = [({"id": "c_a", "name": "A", "address": ""}, trial, None),
            ({"id": "c_b", "name": "B", "address": ""}, dict(trial, plan="standard", tier="basic"), None)]
    g = views.group_form(rows, False)
    want = plus + tiers.list_price("basic")
    res.ok("общая нота: итог сервером (вариант клиники, месяц), без скрипта тоже верный",
           f"id='gs'>{views._mdl(want)} MDL<" in g and "id='gn'>2 clinici<" in g, g[-700:])
    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto"}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        _sql(s, "INSERT INTO payments(clinic_id, amount, method, status, reference, months, kind, sms_units, created_at) "
                "VALUES(?, 300, 'transfer', 'pending', 'DP-2026-000777', 0, 'sms', 100, '2026-10-26T10:00:00Z')", main)
        home = c.get("/cont").body
        res.ok("кабинет с ожидающей нотой SMS: она — своей строкой с реквизитами, не «нота абонемента»",
               "DP-2026-000777" in home and "pachet 100 SMS" in home and "MD00TEST" in home
               and "Altă variantă sau alt termen?" not in home and "<span class='s'>0 MDL</span>" not in home,
               home[-3500:])
        res.ok("форма абонемента рядом — с отмеченным месяцем и суммой месяца",
               "name='months' value='1' checked required" in home
               and f"<span class='s'>{views._mdl(plus)} MDL</span>" in home)


def suite_cabinet(res: Result) -> None:
    """Кабинет: несколько клиник у входа, «Adaugă clinică», форма несёт свою клинику, чужой IDNO."""
    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        home = c.get("/cont")
        res.ok("одна клиника: дашборд как прежде, строка «Adaugă clinică», списка нет",
               "Clinica are și alte sedii?" in home.body and "href='/cont/clinica-noua'" in home.body
               and "Clinicile mele" not in home.body and "action='/cont/date'" in home.body, home.body[-1500:])
        res.check("одна клиника: форма без ?c= пишет как прежде",
                  c.post("/cont/date", name="Clinica Zambet", idno=IDNO, contact_name="Ion Rusu", phone="1",
                         address="str. Stefan cel Mare 12").location, "/cont?msg=saved")
        page = c.get(f"/cont/clinica-noua?c={main}")
        res.ok("форма «Adaugă clinică»: e-mail и IDNO открытой клиники подставлены, галочка условий",
               page.status == 200 and f"value='{DIRECTOR}'" in page.body and f"value='{IDNO}'" in page.body
               and "name='consent'" in page.body and "Același IDNO este permis" in page.body, page.body[-1200:])
        r, _ = _add(c, main, address="")
        res.ok("без адреса — 400 словами, поля подставлены обратно",
               r.status == 400 and "Indicați adresa clinicii" in r.body and "value='Zambet Botanica'" in r.body)
        r, code = _add(c, main, consent="")
        res.check("без галочки условий — 400", r.status, 400)
        n_trials = len(_sql(s, "SELECT 1 FROM issues"))
        r, code = _add(c, main)
        branch = _sql(s, "SELECT id, idno, email, address, origin FROM clinics WHERE name=?", BRANCH["name"])
        res.ok("тот же IDNO внутри кабинета: клиника заведена, адрес и происхождение «cont_add»",
               r.status == 200 and len(branch) == 1 and branch[0][1:] == (IDNO, BRANCH["email"], BRANCH["address"],
                                                                         "cont_add"), repr(branch))
        bid = branch[0][0]
        res.ok("⛔ пробного у клиники из кабинета нет: сразу «standard» на срок оплаты ноты, без Олега "
               "(у главной, регистрации, пробный выдан по режиму)",
               len(_sql(s, "SELECT 1 FROM issues")) == n_trials + 1
               and _sql(s, "SELECT plan FROM subscriptions WHERE clinic_id=?", main) == [("trial",)]
               and _sql(s, "SELECT plan FROM subscriptions WHERE clinic_id=?", bid) == [("standard",)]
               and _sql(s, "SELECT reason FROM issues WHERE clinic_id=?", bid) == [(pay.ADVANCE,)])
        queue = Client(s.url).login().get("/admin").body
        res.ok("в очереди заявок админки пусто — ждать нечего (у главной файл, у новой тоже)",
               "Новых заявок на пробный период нет" in queue, queue[-1500:])
        ack = [(subj, b) for to, subj, b, _a in _letters(s) if to == BRANCH["email"]]
        res.ok("клинике — одно письмо: включена, нота первого периода с реквизитами, пробный — только у первой",
               len(ack) == 1 and "a fost adăugată în cont" in ack[0][0] and "IBAN" in ack[0][1]
               and "doar pentru prima clinică" in ack[0][1] and "cererea de probă" not in ack[0][0], repr(ack)[:800])
        res.ok("ящик новой клиники не совпал со входом кабинета — в том же письме «Confirmă adresa»: ссылка "
               "/confirma/ и код (стык с В, 27.10); ящик не подтверждён",
               len(ack) == 1 and "/confirma/" in ack[0][1] and re.search(r"codul: \d{6}\b", ack[0][1]) is not None
               and _sql(s, "SELECT email_confirmed_at IS NULL FROM clinics WHERE id=?", bid) == [(1,)], repr(ack)[:900])
        res.ok("ответ — страница кода: 7 цифр клетками, «licența ei este activă», предупреждение про код из письма "
               "для главной",
               len(code) == 7 and code.isdigit() and "Codul de activare" in r.body and "licența ei este activă" in r.body
               and "vine un cod de 6 cifre" in r.body and "Clinica Zambet" in r.body, r.body[-1800:])
        res.ok("в базе кода открытым текстом нет", not _sql(s, "SELECT 1 FROM cabinet_codes WHERE code_hash=?", code))
        res.ok("вход в новую клинику — у учётной записи, она же открыта",
               _sql(s, "SELECT count(*) FROM account_clinics")[0][0] == 2
               and _sql(s, "SELECT clinic_id FROM accounts WHERE email=?", DIRECTOR)[0][0] == bid)
        oleg = [b for to, _s, b, _a in _letters(s) if to == "oleg@example.md"]
        res.ok("Олегу письмо остаётся: новая клиника кабинета, с именем главной и нотой, включена сама",
               any("ещё одна клиника кабинета" in b and "Кабинет: Clinica Zambet" in b and "Нота: DP-" in b
                   and "включена сама" in b for b in oleg), repr(oleg)[-800:])

        home = c.get(f"/cont?c={main}")
        res.ok("две клиники: список «Clinicile mele» над дашбордом, открытая подсвечена, у другой — «Deschide»",
               "Clinicile mele" in home.body and "deschisă mai jos" in home.body and f"href='/cont?c={bid}'" in home.body
               and "Notă comună" in home.body and "2 clinici" in home.body, home.body[:4000])
        res.ok("две клиники: формы несут свою клинику (?c=)",
               f"action='/cont/date?c={main}'" in home.body and f"action='/cont/nota?c={main}'" in home.body
               and f"action='/cont/cod?c={main}'" in home.body)
        res.ok("переключение: ?c= открывает другую клинику кабинета",
               "<h1>Zambet Botanica</h1>" in c.get(f"/cont?c={bid}").body)
        res.check("чужая или несуществующая ?c= — на открытую", c.get("/cont?c=c_000000000000").location, "/cont")
        r = c.post("/cont/date", name="Подмена", idno=IDNO, contact_name="", phone="", address="x")
        res.ok("⛔ две клиники: форма без ?c= (вкладка до обновления) не пишет ни в одну",
               r.location == "/cont?msg=pick_clinic"
               and not _sql(s, "SELECT 1 FROM clinics WHERE name='Подмена'"), r.location)
        r = c.post(f"/cont/date?c={bid}", name="Zambet Botanica SRL", idno=IDNO, contact_name="Ion", phone="2",
                   address="bd. Dacia 27")
        res.ok("форма с ?c= пишет в свою клинику, тот же IDNO внутри кабинета — не «idno_taken»",
               r.location == f"/cont?c={bid}&msg=saved"
               and _sql(s, "SELECT name FROM clinics WHERE id=?", bid)[0][0] == "Zambet Botanica SRL"
               and _sql(s, "SELECT name FROM clinics WHERE id=?", main)[0][0] == "Clinica Zambet", r.location)

        r, code = _add(c, main, email=DIRECTOR, name="Zambet Balti", address="str. Independentei 5, Balti")
        res.ok("тот же ящик, что у главной, — тоже можно", r.status == 200 and len(code) == 7, r.body[-400:])
        same = [b for to, subj, b, _a in _letters(s) if to == DIRECTOR and "Zambet Balti a fost adăugată" in subj]
        res.ok("ящик = вход кабинета: подтверждён сразу, в письме новой клиники блока подтверждения нет",
               len(same) == 1 and "/confirma/" not in same[0] and "codul:" not in same[0]
               and _sql(s, "SELECT email_confirmed_at IS NOT NULL FROM clinics WHERE name='Zambet Balti'") == [(1,)],
               repr(same)[:900])
        # чужая клиника с другим IDNO — заведена программой другого человека
        other = Client(s.url)
        st, _d = _api(other, "/v1/trial", dict(name="Clinica Straina", idno="2000000000001", contact_name="X",
                                               email="straina@example.md", phone="", consent="1"))
        res.check("чужая клиника заведена", st, 200)
        r, code = _add(c, main, idno="2000000000001", email="nou@zambet.md", name="Furt")
        res.ok("IDNO чужой клиники — 409 «add_duplicate», ничего не заведено, письмо Олегу",
               r.status == 409 and "nu este în contul" in r.body and not code
               and not _sql(s, "SELECT 1 FROM clinics WHERE name='Furt'"), r.body[-600:])
        r = c.post(f"/cont/date?c={bid}", name="Zambet Botanica SRL", idno="2000000000001", contact_name="",
                   phone="", address="x")
        res.check("реквизиты: IDNO чужой клиники — idno_taken", r.location, f"/cont?c={bid}&msg=idno_taken")

        # второй человек входит ящиком клиники: вход во все клиники с ЭТИМ ящиком
        solo = _enter(s, "botanica@zambet.md").get("/cont")
        res.ok("вход ящиком филиала — только филиал (свой ящик — своя клиника)",
               "<h1>Zambet Botanica SRL</h1>" in solo.body and "Clinicile mele" not in solo.body, solo.body[:600])

        # отвязка в админке снимает вход во все клиники записи
        admin = Client(s.url).login()
        aid = _sql(s, "SELECT id FROM accounts WHERE email=?", DIRECTOR)[0][0]
        admin.post(f"/admin/accounts/{aid}/detach")
        res.ok("отвязка записи: её входы во все клиники уходят вместе с ней",
               not _sql(s, "SELECT 1 FROM account_clinics WHERE account_id=?", aid)
               and c.get("/cont").location == "/cont/login")
        # одна секунда у всех трёх — главная всё равно та, что заведена первой
        _sql(s, "UPDATE clinics SET created_at='2026-10-26T10:00:00Z' WHERE name IN "
                "('Clinica Zambet', 'Zambet Botanica SRL', 'Zambet Balti')")
        again = _enter(s, DIRECTOR.upper())
        naid = _sql(s, "SELECT id FROM accounts WHERE email=?", DIRECTOR)[0][0]
        got = {r[0] for r in _sql(s, "SELECT c.name FROM account_clinics x JOIN clinics c ON c.id=x.clinic_id "
                                     "WHERE x.account_id=?", naid)}
        res.ok("новая запись ящиком главной — вход во ВСЕ клиники с этим ящиком (главная и Bălți), не в Botanica; "
               "открыта первая",
               naid != aid and got == {"Clinica Zambet", "Zambet Balti"}
               and "<h1>Clinica Zambet</h1>" in again.get("/cont").body, repr(got))


def _cabinet_with_branch(s: Server) -> tuple[Client, str, str, str]:
    """Кабинет с главной и филиалом → (клиент кабинета, главная, филиал, код компьютера филиала)."""
    c = _enter(s, DIRECTOR)
    main = _register(s, c)
    _r, code = _add(c, main)
    return c, main, _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0], code


def _new_code(c: Client, cid: str) -> str:
    page = c.post(f"/cont/cod?c={cid}")
    return "".join(re.findall(r"<span>(\d)</span>", page.body))


# ⚠️ Лимиты сервера держат порядок проверок ниже: заявок с одного адреса — 5 в час (регистрация,
# «Adaugă» и каждая заявка программы), кодов из письма одной клинике — 3 в час. Отсюда три сервера.


def suite_code(res: Result) -> None:
    """Код компьютера из кабинета через провод программы: /v1/trial «известна» → /v1/verify."""
    env = {**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}
    with Server(env=env) as s:
        c, main, bid, code = _cabinet_with_branch(s)
        prog = Client(s.url)
        vid = _known(prog, DEV1)
        letter = [x for x in _letters(s) if x[0] == DIRECTOR and "codul de activare" in x[1]][-1]
        res.ok("письмо «новый компьютер» уходит главной и несёт строку про код из кабинета для филиала",
               "Dacă activați o clinică nouă (filială), folosiți codul din contul clinicii" in letter[2], letter[2])
        st, d = _api(prog, "/v1/verify", {"verify_id": vid, "code": code}, DEV1)
        res.ok("код кабинета: токен НОВОЙ клиники, не главной",
               st == 200 and d.get("token") == _token_of(s, bid) and d.get("token") != _token_of(s, main), repr(d))
        r = prog.get("/v1/license?seq=0", headers={"Authorization": f"Bearer {d.get('token', '')}"})
        _code, claim = rv.open_envelope(r.body, KEYS) if r.status == 200 else ("нет", None)
        res.ok("без одобрения Олега — по тому же токену сразу файл новой клиники (её название, «standard»)",
               claim is not None and claim.clinic == BRANCH["name"] and claim.plan == "standard",
               f"{r.status} {_code}")
        res.check("компьютер привязан к новой клинике (флот)",
                  _sql(s, "SELECT clinic_id FROM devices WHERE id=?", DEV1), [(bid,)])
        res.ok("код погашен вместе с verify_id: второй раз — 400, у кода отмечен компьютер",
               _api(prog, "/v1/verify", {"verify_id": vid, "code": code}, DEV1)[0] == 400
               and _sql(s, "SELECT used_at IS NOT NULL, device FROM cabinet_codes")[0] == (1, DEV1))
        # код из письма по-прежнему — главной
        vid2 = _known(prog, DEV2)
        mail_code = re.search(r"\b(\d{6})\b", [x for x in _letters(s) if x[0] == DIRECTOR
                                                 and "codul de activare" in x[1]][-1][2]).group(1)
        st, d = _api(prog, "/v1/verify", {"verify_id": vid2, "code": mail_code}, DEV2)
        res.ok("код из письма (6 цифр) — компьютер главной клиники, как прежде",
               st == 200 and d.get("token") == _token_of(s, main), repr(d))
        # переезд: DEV2 (у главной) активируется кодом филиала
        vid3 = _known(prog, DEV2)
        st, _d = _api(prog, "/v1/verify", {"verify_id": vid3, "code": _new_code(c, bid)}, DEV2)
        res.ok("компьютер главной, активированный кодом филиала, переехал: device_moved в журнале филиала",
               st == 200 and _sql(s, "SELECT clinic_id FROM devices WHERE id=?", DEV2) == [(bid,)]
               and _sql(s, "SELECT clinic_id FROM audit WHERE what='device_moved'") == [(bid,)])
        res.ok("«Cod de activare» без входа — на вход", Client(s.url).post(f"/cont/cod?c={bid}").location == "/cont/login")

    with Server(env=env) as s:
        c, main, bid, _code0 = _cabinet_with_branch(s)
        prog = Client(s.url)
        code2 = _new_code(c, bid)
        res.ok("«Cod de activare»: новый код той же клиники — 7 цифр", len(code2) == 7 and code2.isdigit(), code2)
        vid = _known(prog, DEV3)
        bad = "0000000" if code2 != "0000000" else "1111111"
        for _ in range(5):
            _api(prog, "/v1/verify", {"verify_id": vid, "code": bad}, DEV3)
        res.check("пять неверных кодов кабинета сжигают verify_id: и верный уже не принят",
                  _api(prog, "/v1/verify", {"verify_id": vid, "code": code2}, DEV3)[0], 400)
        res.check("без живого verify_id код кабинета не принимается",
                  _api(prog, "/v1/verify", {"verify_id": "net-takogo", "code": code2}, DEV3)[0], 400)
        vid = _known(prog, DEV3)
        code3 = _new_code(c, bid)
        res.check("новый код гасит прежний неиспользованный",
                  _api(prog, "/v1/verify", {"verify_id": vid, "code": code2}, DEV3)[0], 400)
        vid = _known(prog, DEV3)
        _sql(s, "UPDATE cabinet_codes SET expires_at='2000-01-01T00:00:00Z' WHERE used_at IS NULL")
        res.check("просроченный код кабинета — 400",
                  _api(prog, "/v1/verify", {"verify_id": vid, "code": code3}, DEV3)[0], 400)
        res.ok("ни одна из неудач не привязала компьютер", not _sql(s, "SELECT 1 FROM devices WHERE id=?", DEV3))

    with Server(env=env) as s:
        c, main, bid, _code0 = _cabinet_with_branch(s)
        other = _enter(s, "alt@other.md")
        other.post("/cont/inregistrare", name="Alta Clinica", idno="3000000000003", contact_name="A", phone="1",
                   consent="1")
        oid = _sql(s, "SELECT id FROM clinics WHERE name='Alta Clinica'")[0][0]
        foreign = _new_code(other, oid)
        prog = Client(s.url)
        vid = _known(prog, DEV3)
        res.ok("код другого кабинета к заявке этого — 400, компьютер никуда не привязан",
               len(foreign) == 7 and _api(prog, "/v1/verify", {"verify_id": vid, "code": foreign}, DEV3)[0] == 400
               and not _sql(s, "SELECT 1 FROM devices WHERE id=?", DEV3))
        res.check("код для клиники не своего кабинета из кабинета — нельзя (pick_clinic)",
                  c.post(f"/cont/cod?c={oid}").location, "/cont?msg=pick_clinic")


def suite_group(res: Result) -> None:
    """Общая нота: строки, замена нот, одна нота на клинику, оплата — свои файлы, один документ."""
    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        # своя нота у главной — до общей
        r = c.post(f"/cont/nota?c={main}", months="1", tier="plus", terms="1")
        res.ok("своя нота главной создана", r.location == f"/cont?c={main}&msg=note_created", r.location)
        own = _sql(s, "SELECT reference FROM payments WHERE clinic_id=? AND status='pending'", main)[0][0]
        page = c.get("/cont/nota-comuna")
        res.ok("страница общей ноты: обе клиники, вариант и срок у каждой, галочка условий",
               page.status == 200 and f"name='t_{main}'" in page.body and f"name='t_{bid}'" in page.body
               and f"name='m_{bid}'" in page.body and "name='terms'" in page.body, page.body[-2000:])
        r = c.post("/cont/nota-comuna", **{f"t_{main}": "plus", f"m_{main}": "1", f"t_{bid}": "basic",
                                          f"m_{bid}": "12"})
        res.check("без галочки — need_terms", r.location, "/cont/nota-comuna?msg=need_terms")
        res.check("ни одной клиники — group_empty",
                  c.post("/cont/nota-comuna", terms="1", **{f"t_{main}": "", f"t_{bid}": ""}).location,
                  "/cont/nota-comuna?msg=group_empty")
        n = len(_letters(s))
        r = c.post("/cont/nota-comuna", terms="1", **{f"t_{main}": "plus", f"m_{main}": "1", f"t_{bid}": "basic",
                                                     f"m_{bid}": "12"})
        res.check("общая нота создана и заменила ноту главной", r.location, "/cont/nota-comuna?msg=group_replaced")
        g = _sql(s, "SELECT id, reference, amount, clinic_id, kind, months FROM payments WHERE status='pending'")
        want = pay.amount(1, tiers.list_price("plus")) + pay.amount(12, tiers.list_price("basic"))
        res.ok("одна ожидающая нота — общая: у плательщика (главная), сумма строк, вид cabinet",
               len(g) == 1 and g[0][2] == want and g[0][3] == main and g[0][4] == "cabinet" and g[0][5] == 0, repr(g))
        gid, gref = g[0][0], g[0][1]
        res.check("строки: клиника, вариант, срок, сумма по прайсу варианта",
                  sorted(_sql(s, "SELECT clinic_id, tier, months, amount FROM payment_lines WHERE payment_id=?", gid)),
                  sorted([(main, "plus", 1, pay.amount(1, tiers.list_price("plus"))),
                          (bid, "basic", 12, pay.amount(12, tiers.list_price("basic")))]))
        res.ok("своя нота главной отклонена «заменена общей нотой»",
               _sql(s, "SELECT status FROM payments WHERE reference=?", own) == [("rejected",)]
               and any(gref in d for (d,) in _sql(s, "SELECT detail FROM audit WHERE what='payment_rejected'")))
        lt = [x for x in _letters(s)[n:] if x[0] == DIRECTOR]
        res.ok("письмо с общей нотой плательщику: строки по клиникам, сумма, reference, IBAN",
               len(lt) == 1 and gref in lt[0][1] and "Zambet Botanica" in lt[0][2] and str(want) in lt[0][2]
               and "IBAN" in lt[0][2], repr(lt)[:600])
        r = c.post(f"/cont/nota?c={bid}", months="1", tier="plus", terms="1")
        res.ok("⛔ клиника в общей ноте: своя нота не выставляется (in_group), долг один",
               r.location == f"/cont?c={bid}&msg=in_group"
               and _sql(s, "SELECT count(*) FROM payments WHERE status='pending'")[0][0] == 1, r.location)
        home = c.get(f"/cont?c={bid}")
        res.ok("дашборд филиала: «în nota comună», ссылка на общую ноту, формы своей ноты нет",
               f"nota comună {gref}" in home.body and "href='/cont/nota-comuna'" in home.body
               and f"action='/cont/nota?c={bid}'" not in home.body, home.body[-3000:])
        page = c.get("/cont/nota-comuna")
        res.ok("открытая общая нота на странице: строки, реквизиты, отмена",
               gref in page.body and "Anulează nota comună" in page.body and "MD00TEST" in page.body)
        # ежедневная задача: клинике в общей ноте своя нота не заводится
        _sql(s, "UPDATE subscriptions SET plan='standard', valid_until=? WHERE clinic_id=?",
             "2026-01-01T00:00:00Z", bid)
        with sqlite3.connect(s.dir / "cloud.db") as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT c.*, s.plan, s.price, s.tier, s.sms_until, s.valid_until, s.grace_days "
                              "FROM subscriptions s JOIN clinics c ON c.id=s.clinic_id WHERE c.id=?", (bid,)).fetchone()
        from app import jobs  # noqa: PLC0415 — нужен только этой проверке
        db_path = s.dir / "cloud.db"
        con = sqlite3.connect(db_path, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            con.execute("BEGIN")
            p = jobs.open_payment(con, row)
            con.execute("ROLLBACK")
        finally:
            con.close()
        res.check("задача за 14 дней: клинике в общей ноте — эта нота, своя не заводится", p["reference"], gref)
        # оплата: каждая клиника — свой файл, один документ со строками
        admin = Client(s.url).login()
        seq_m = _sql(s, "SELECT max(seq) FROM issues WHERE clinic_id=?", main)[0][0]
        seq_b = _sql(s, "SELECT max(seq) FROM issues WHERE clinic_id=?", bid)[0][0]
        n = len(_letters(s))
        r = admin.post(f"/admin/payments/{gid}/confirm")
        res.ok("подтверждение общей ноты в админке", "payment_confirmed" in r.location, r.location)
        res.ok("каждая клиника строки — своим новым файлом",
               _sql(s, "SELECT max(seq) FROM issues WHERE clinic_id=?", main)[0][0] == seq_m + 1
               and _sql(s, "SELECT max(seq) FROM issues WHERE clinic_id=?", bid)[0][0] == seq_b + 1)
        res.check("подписки: вариант строки у каждой",
                  sorted(_sql(s, "SELECT clinic_id, plan, tier FROM subscriptions")),
                  sorted([(main, "standard", "plus"), (bid, "standard", "basic")]))
        rec = _sql(s, "SELECT number, data FROM receipts WHERE payment_id=?", gid)
        data = json.loads(rec[0][1]) if rec else {}
        res.ok("cont de plată — один, номер = reference, две строки по клиникам с периодами",
               len(rec) == 1 and rec[0][0] == gref and len(data.get("items", [])) == 2
               and all("perioada" in x["detail"] for x in data["items"])
               and sum(x["amount"] for x in data["items"]) == want, repr(data)[:600])
        new = _letters(s)[n:]
        res.ok("письма: о лицензии каждой клинике на её ящик, cont de plată — вложением плательщику",
               {x[0] for x in new} >= {DIRECTOR, BRANCH["email"]}
               and any(x[0] == DIRECTOR and any((f or "").endswith(".pdf") for f in x[3]) for x in new)
               and not any(x[0] == BRANCH["email"] and any((f or "").endswith(".pdf") for f in x[3]) for x in new),
               repr([(x[0], x[1], x[3]) for x in new]))
        pdf_r = c.get(f"/cont/plati/{gref}.pdf")
        res.ok("PDF общей ноты открывается из кабинета", pdf_r.status == 200, pdf_r.status)
        res.check("чужой номер — 404", c.get("/cont/plati/DP-2000-000001.pdf").status, 404)
        # отмена
        c.post("/cont/nota-comuna", terms="1", **{f"t_{main}": "plus", f"m_{main}": "1", f"t_{bid}": "plus",
                                                 f"m_{bid}": "1"})
        gref2 = _sql(s, "SELECT reference FROM payments WHERE status='pending'")[0][0]
        r = c.post("/cont/nota-comuna/anuleaza", ref=gref2)
        res.ok("«Anulează nota comună»: нота отклонена, клиники свободны — своя нота выставляется",
               r.location == "/cont/nota-comuna?msg=group_cancelled"
               and _sql(s, "SELECT status FROM payments WHERE reference=?", gref2) == [("rejected",)]
               and c.post(f"/cont/nota?c={bid}", months="1", tier="plus", terms="1").location
               == f"/cont?c={bid}&msg=note_created", r.location)
        # зачёт повторного перевода по общей ноте — вся, с теми же строками
        r = admin.post(f"/admin/payments/{gid}/repeat", sure="1")
        rep = _sql(s, "SELECT id, kind, amount FROM payments WHERE kind='cabinet' AND status='paid' AND id<>?", gid)
        res.ok("повторный перевод по общей ноте зачитывается всей нотой, с теми же строками",
               "payment_repeat" in r.location and len(rep) == 1 and rep[0][2] == want
               and _sql(s, "SELECT count(*) FROM payment_lines WHERE payment_id=?", rep[0][0])[0][0] == 2, r.location)
        _sql(s, "UPDATE clinics SET idno='' WHERE id=?", main)
        res.check("IDNO плательщика (первой клиники строк) обязателен — need_idno_payer",
                  c.post("/cont/nota-comuna", terms="1", **{f"t_{main}": "plus", f"m_{main}": "1",
                                                           f"t_{bid}": ""}).location,
                  "/cont/nota-comuna?msg=need_idno_payer")


def suite_plata(res: Result) -> None:
    """Страница оплаты из программы (/plata) у клиники в общей ноте — общая нота, своя не выставляется."""
    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto"}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        c.post("/cont/nota-comuna", terms="1", **{f"t_{main}": "plus", f"m_{main}": "1", f"t_{bid}": "plus",
                                                 f"m_{bid}": "1"})
        gref = _sql(s, "SELECT reference FROM payments WHERE status='pending'")[0][0]
        prog = Client(s.url)
        r = prog._do("/v1/pay-link", b"", {"Authorization": f"Bearer {_token_of(s, bid)}"})
        link = json.loads(r.body).get("url", "") if r.status == 200 else ""
        path = "/" + link.split("/", 3)[-1] if link else ""
        page = prog.get(path) if path else None
        res.ok("/plata филиала: общая нота — строки обеих клиник, сумма, без формы своей ноты",
               page is not None and page.status == 200 and f"nota comună {gref}" in page.body
               and "Clinica Zambet" in page.body and "name='tier'" not in page.body,
               (page.body[-1500:] if page else f"{r.status} {r.body[:300]}"))
        r = prog.post(path, months="1", tier="plus", terms="1")
        res.ok("перевод своей нотой с /plata филиала — in_group, вторая нота не родилась",
               r.location.endswith("msg=in_group")
               and _sql(s, "SELECT count(*) FROM payments WHERE status='pending'")[0][0] == 1, r.location)


def suite_sms_name(res: Result) -> None:
    """Имя отправителя общее на кабинет: заявка филиала — у главной, филиал шлёт от её имени."""
    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_SMS_OFFERED": "1", "DP_SMSMD_TOKEN": "t"}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        r = c.post(f"/cont/sms/nume?c={bid}", name="Zambet")
        res.ok("заявка на имя со страницы филиала ложится главной клинике",
               r.location == f"/cont?c={bid}&msg=sms_requested"
               and _sql(s, "SELECT clinic_id, sender, sender_state FROM sms_accounts WHERE sender_state<>'none'")
               == [(main, "Zambet", "requested")], r.location)
        page = c.get(f"/cont?c={bid}")
        res.ok("кабинет филиала: имя общее — у главной, формы несут открытую клинику",
               "Numele expeditorului este comun" in page.body and "Clinica Zambet" in page.body
               and f"action='/cont/sms/nume?c={bid}'" in page.body, page.body[-2500:])
        _sql(s, "UPDATE sms_accounts SET sender_state='active', sender_live='Zambet', "
                "sender_until='2099-01-01T00:00:00Z' WHERE clinic_id=?", main)
        prog = Client(s.url)
        r = prog.get("/v1/sms/account", headers={"Authorization": f"Bearer {_token_of(s, bid)}"})
        d = json.loads(r.body) if r.status == 200 else {}
        res.ok("программа филиала: имя «Zambet» (главной), остаток — свой",
               d.get("from") == "Zambet" and d.get("sender") == "Zambet" and d.get("sender_state") == "active"
               and "balance" in d, repr(d)[:400])
        r = prog._do("/v1/sms/sender", json.dumps({"name": "Alt Nume"}).encode(),
                     {"Authorization": f"Bearer {_token_of(s, bid)}", "Content-Type": "application/json"})
        res.ok("заявка на имя из программы филиала — тоже главной",
               _sql(s, "SELECT sender, sender_state FROM sms_accounts WHERE clinic_id=?", main)
               == [("Alt Nume", "requested")]
               and _sql(s, "SELECT sender_state FROM sms_accounts WHERE clinic_id=?", bid) in ([("none",)], []),
               f"{r.status} {r.body[:200]}")
        admin = Client(s.url).login()
        card = admin.get(f"/admin/clinics/{bid}").body
        res.ok("админка филиала › SMS: имя общее на кабинет, ссылка на главную",
               "общее на клиники кабинета" in card and f"/admin/clinics/{main}#sms" in card)


def _run_daily(s: Server) -> str:
    """Ежедневная задача как из cron, на сегодня (UTC), окружением сервера."""
    import subprocess  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415
    p = subprocess.run([sys.executable, "-m", "app.jobs", "daily", "--at",
                        f"{datetime.now(timezone.utc):%Y-%m-%d}T06:00:00Z"], cwd=str(CLOUD), env=s.env,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    return p.stdout + p.stderr


def suite_paid(res: Result) -> None:
    """Клиника из «Adaugă clinică» — сразу платная и включается сама (Олег 27.10: «оставим бесплатный
    месяц только главной клинике, а добавление я бы сделал сразу платным»; «меня может не быть на
    месте, а им надо работать»): вариант и срок — в форме, нота первого периода и файл на срок её
    оплаты при ЛЮБОМ режиме пробного; оплата в срок — период от дня заведения, поздняя — от сегодня;
    без ключа выдачи — нота есть, клиника ждёт Олега."""
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    env = {**BANK_ENV, "DP_TRIAL_MODE": "approve", "DP_TRIAL_NOTIFY": "oleg@example.md"}
    with Server(env=env) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        page = c.get(f"/cont/clinica-noua?c={main}").body
        res.ok("форма: вариант (Basic, Plus) и срок — как у ноты, IDNO обязателен, пробного не обещает",
               "name='tier' value='basic'" in page and "name='tier' value='plus'" in page
               and "name='months' value='12'" in page and "inputmode='numeric' required" in page
               and "doar pentru prima clinică" in page and "O lună de probă" not in page
               and "aprobăm" not in page, page[-3000:])
        r, _ = _add(c, main, idno="")
        res.ok("без IDNO — 400 словами (файл абонемента без IDNO не выдаётся), ничего не заведено",
               r.status == 400 and "Indicați IDNO-ul clinicii noi" in r.body
               and not _sql(s, "SELECT 1 FROM clinics WHERE name=?", BRANCH["name"]), r.body[-600:])
        r, _ = _add(c, main, months="3")
        res.ok("срок не из ряда — 400, выбор подставлен обратно", r.status == 400 and "Alegeți o lună sau un an" in r.body)
        r, _ = _add(c, main, tier="gold")
        res.ok("вариант, которого нет, — 400 «nu se poate plăti»",
               r.status == 400 and "Varianta aleasă nu se poate plăti" in r.body, r.body[-600:])
        r, code = _add(c, main, tier="basic", months="12")
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        iss = _sql(s, "SELECT reason, issued_at, valid_until, grace_until FROM issues WHERE clinic_id=?", bid)
        ok_dates = False
        if len(iss) == 1:
            at, vu, gu = (db.parse_ts(x) for x in iss[0][1:])
            ok_dates = vu - at == timedelta(days=14) and gu - vu == timedelta(days=14)
        res.ok("⛔ DP_TRIAL_MODE=approve: главная ждёт Олега, а новая клиника кабинета включена сама — файл на "
               "14 дней оплаты (jobs.INVOICE_DAYS) и льгота 14 (license.GRACE_DAYS)",
               r.status == 200 and len(code) == 7 and not _sql(s, "SELECT 1 FROM issues WHERE clinic_id=?", main)
               and len(iss) == 1 and iss[0][0] == pay.ADVANCE and ok_dates, repr(iss))
        res.check("подписка: «standard» в выбранном варианте",
                  _sql(s, "SELECT plan, tier, price FROM subscriptions WHERE clinic_id=?", bid),
                  [("standard", "basic", tiers.list_price("basic"))])
        nota = _sql(s, "SELECT id, reference, tier, months, amount, kind FROM payments WHERE clinic_id=? "
                       "AND status='pending'", bid)
        res.ok("нота первого периода: выбранный вариант и срок, сумма по прайсу",
               len(nota) == 1 and nota[0][2:] == ("basic", 12, pay.amount(12, tiers.list_price("basic")), "license"),
               repr(nota))
        mine = [x for x in _letters(s) if x[0] == BRANCH["email"]]
        res.ok("письмо клинике — одно, с нотой и сроком оплаты", len(mine) == 1 and nota[0][1] in mine[0][1]
               and iss[0][2][8:10] + "." + iss[0][2][5:7] in mine[0][2], repr(mine)[:600])
        out = _run_daily(s)
        again = [x for x in _letters(s) if x[0] == BRANCH["email"]]
        res.ok("ежедневная задача в тот же день второй ноты не шлёт (напоминание «нота» за этот срок отмечено)",
               len(again) == 1 and _sql(s, "SELECT kind FROM reminders WHERE subscription_id=?", bid) == [("invoice",)],
               out[-600:] + repr([x[1] for x in again]))
        home = c.get(f"/cont?c={bid}").body
        res.ok("кабинет новой клиники: абонемент Basic и нота в ожидании, не «perioada de probă»",
               nota[0][1] in home and "DentPilot Basic" in home and "perioada de probă ·" not in home, home[-3000:])
        res.ok("срок на оплату — не «valabil până la»: «achitați nota de plată până la», янтарная «nota de plată» "
               "(блок «Licența» и строка «Clinicile mele»)",
               "achitați nota de plată până la" in home and "Activă — achitați nota până la" in home
               and "<span class='tag warn'>nota de plată</span>" in home
               and "Abonamentul DentPilot Basic este valabil până la" not in home, home[:6000])
        # оплата в срок: период — от дня заведения, а не от конца срока на оплату
        admin = Client(s.url).login()
        r = admin.post(f"/admin/payments/{nota[0][0]}/confirm")
        start = db.parse_ts(iss[0][1])
        got = _sql(s, "SELECT valid_until, reason FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1", bid)
        res.ok("оплата в срок: год — от дня заведения (не + 14 дней сверх оплаченного)",
               "payment_confirmed" in r.location and got[0][0] == pay.add_months(start, 12).strftime(db.TS)
               and got[0][1] != pay.ADVANCE, f"{r.location} {got} от {iss[0][1]}")
        res.check("якорь подписки — число дня заведения",
                  _sql(s, "SELECT anchor_day FROM subscriptions WHERE clinic_id=?", bid), [(start.day,)])
        home = c.get(f"/cont?c={bid}").body
        res.ok("после оплаты — обычное «valabil până la», зелёная «activă»",
               "Abonamentul DentPilot Basic este valabil până la" in home and "achitați nota de plată până la" not in home,
               home[:6000])
        # поздняя оплата: срок на оплату прошёл — как любая поздняя, от сегодня
        _add(c, main, name="Zambet Balti", address="str. Independentei 5, Balti", email="balti@zambet.md")
        bal = _sql(s, "SELECT id FROM clinics WHERE name='Zambet Balti'")[0][0]
        # заведена 20 дней назад, срок на оплату кончился 6 дней назад (идёт льгота)
        _sql(s, "UPDATE issues SET issued_at=? WHERE clinic_id=?",
             (datetime.now(timezone.utc) - timedelta(days=20)).strftime(db.TS), bal)
        _sql(s, "UPDATE subscriptions SET valid_until=? WHERE clinic_id=?",
             (datetime.now(timezone.utc) - timedelta(days=6)).strftime(db.TS), bal)
        pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending'", bal)[0][0]
        admin.post(f"/admin/payments/{pid}/confirm")
        late = db.parse_ts(_sql(s, "SELECT valid_until FROM issues WHERE clinic_id=? ORDER BY seq DESC LIMIT 1", bal)[0][0])
        want = pay.add_months(datetime.now(timezone.utc), 1)
        res.ok("поздняя оплата: месяц — от сегодня", late is not None and abs((late - want).total_seconds()) < 120,
               f"{late} ~ {want}")
        # сторож «бесконечных 28 дней» (координатор 27.10): пока первая нота клиники кабинета просрочена — не добавлять
        r1, _ = _add(c, main, name="Zambet Ciocana", address="str. Ciocana 1", email="ciocana@zambet.md")
        r2, _ = _add(c, main, name="Zambet Riscani", address="str. Riscani 2", email="riscani@zambet.md")
        res.ok("две клиники подряд, пока сроки на оплату идут, — можно", r1.status == 200 and r2.status == 200,
               f"{r1.status} {r2.status}")
        cio = _sql(s, "SELECT id FROM clinics WHERE name='Zambet Ciocana'")[0][0]
        cref = _sql(s, "SELECT reference FROM payments WHERE clinic_id=? AND status='pending'", cio)[0][0]
        _sql(s, "UPDATE subscriptions SET valid_until=? WHERE clinic_id=?",
             (datetime.now(timezone.utc) - timedelta(days=1)).strftime(db.TS), cio)
        want_txt = f"Achitați mai întâi nota clinicii Zambet Ciocana ({cref}), apoi puteți adăuga o clinică nouă."
        form = c.get(f"/cont/clinica-noua?c={main}").body
        res.ok("форма: срок первой ноты прошёл — сразу словами, какую ноту оплатить", want_txt in form, form[:3000])
        r, code = _add(c, main, name="Zambet Durlesti", address="str. Durlesti 3", email="durlesti@zambet.md")
        res.ok("⛔ «Adaugă clinică» при просроченной первой ноте — 409 словами, ничего не заведено",
               r.status == 409 and want_txt in r.body and not code
               and not _sql(s, "SELECT 1 FROM clinics WHERE name='Zambet Durlesti'"), r.body[:3000])
        admin.post(f"/admin/payments/{_sql(s, 'SELECT id FROM payments WHERE reference=?', cref)[0][0]}/confirm")
        res.ok("нота оплачена — форма снова открыта", "Achitați mai întâi" not in c.get(f"/cont/clinica-noua?c={main}").body)

    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_LICENSE_KEY": ""}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        r, code = _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        res.ok("без ключа выдачи: клиника заведена, код есть, нота выставлена, файла нет — «licența o activăm noi»",
               r.status == 200 and len(code) == 7 and "Licența o activăm noi" in r.body
               and not _sql(s, "SELECT 1 FROM issues WHERE clinic_id=?", bid)
               and _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=? AND status='pending'", bid) == [(1,)]
               and _sql(s, "SELECT count(*) FROM audit WHERE what='add_no_key' AND clinic_id=?", bid) == [(1,)],
               r.body[-1500:])
        queue = Client(s.url).login().get("/admin").body
        res.ok("…и ждёт Олега в очереди заявок", "Zambet Botanica" in queue and "кабинет +" in queue)


def suite_admin(res: Result) -> None:
    """Админка: клиники того же кабинета, «Добавить клинику в кабинет», подсказка флота, миграция."""
    with Server(env={**BANK_ENV, "DP_TRIAL_MODE": "auto"}) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        admin = Client(s.url).login()
        card = admin.get(f"/admin/clinics/{main}").body
        res.ok("карточка главной: «Клиники того же кабинета» со ссылкой на филиал и формой добавления",
               "Клиники того же кабинета" in card and f"href='/admin/clinics/{bid}'" in card
               and f"action='/admin/clinics/{main}/sibling'" in card and "клиник в кабинете: 2" in card)
        r = admin.post(f"/admin/clinics/{main}/sibling", name="Zambet Ciocana", address="str. Ciocana 1",
                       email="ciocana@zambet.md", idno=IDNO, contact_name="", phone="")
        new = _sql(s, "SELECT id, origin FROM clinics WHERE name='Zambet Ciocana'")
        res.ok("Олег добавил клинику в кабинет: заведена (как из админки — без пробного), входы кабинета те же",
               len(new) == 1 and r.location == f"/admin/clinics/{new[0][0]}?msg=sibling_added"
               and new[0][1] == "admin" and not _sql(s, "SELECT 1 FROM issues WHERE clinic_id=?", new[0][0])
               and _sql(s, "SELECT count(*) FROM account_clinics WHERE clinic_id=?", new[0][0])[0][0] == 1, r.location)
        res.ok("журнал: «клиника добавлена в кабинет» словами",
               "клиника добавлена в кабинет" in admin.get(f"/admin/clinics/{new[0][0]}").body)
        _sql(s, "INSERT INTO clinics(id, name, idno, created_at) VALUES('c_strain00001', 'Straina', "
                "'9999999999999', '2026-01-01T00:00:00Z')")
        res.check("чужой IDNO в «Добавить клинику» — sibling_duplicate",
                  admin.post(f"/admin/clinics/{main}/sibling", name="X", address="y", email="",
                             idno="9999999999999", contact_name="", phone="").location,
                  f"/admin/clinics/{main}?msg=sibling_duplicate")
        other = Client(s.url)
        _api(other, "/v1/trial", dict(name="Clinica Straina", idno="2000000000001", contact_name="X",
                                      email="straina@example.md", phone="", consent="1"))
        r, code = _add(c, main, email="straina@example.md", name="Furt2")
        res.ok("«Adaugă clinică» с ящиком чужой клиники — 409, ничего не заведено",
               r.status == 409 and not code and not _sql(s, "SELECT 1 FROM clinics WHERE name='Furt2'"), r.status)
        lone = "c_lone00000001"
        _sql(s, "INSERT INTO clinics(id, name, created_at) VALUES(?, 'Singura', '2026-01-01T00:00:00Z')", lone)
        res.check("клиника без входа в кабинет — добавлять некуда",
                  admin.post(f"/admin/clinics/{lone}/sibling", name="X", address="y", email="", idno="",
                             contact_name="", phone="").location, f"/admin/clinics/{lone}?msg=sibling_no_cabinet")
        # подсказка флота: два активных компьютера у клиники
        for dev in (DEV1, DEV2):
            _sql(s, "INSERT INTO devices(id, clinic_id, version, channel, os, first_seen_at, last_seen_at) "
                    "VALUES(?,?,?,?,?,?,?)", dev, main, "2.2.0", "stable", "Windows 11", db.now_iso(), db.now_iso())
        fleet = admin.get("/admin/fleet").body
        res.ok("флот: «клиник с 2+ активными за 30 дн.: 1», вкладка «Несколько компьютеров», значок у клиники",
               "клиник с 2+ активными за 30 дн.: 1" in fleet and "data-pane='multi'" in fleet
               and "2 активных за 30 дн." in fleet, fleet[-2000:])
        res.ok("карточка: значок в плитке «Программа»", "2 активных за 30 дн." in admin.get(f"/admin/clinics/{main}").body)
        _sql(s, "UPDATE devices SET last_seen_at='2026-01-01T00:00:00Z' WHERE id=?", DEV2)
        res.ok("компьютер молчит дольше 30 дней — подсказки нет",
               "2 активных за 30 дн." not in admin.get(f"/admin/clinics/{main}").body)


def suite_migration(res: Result) -> None:
    """Шаг 16 на данных шага 15: каждая прежняя учётная запись — вход в её нынешнюю клинику.
    База шага 15 кладётся туда, где сервер её откроет, ДО старта: миграцию делает его старт."""
    s = Server()
    path = s.dir / "cloud.db"
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for step in range(1, 16):
            con.execute("BEGIN")
            for sql in db.MIGRATIONS[step]:
                con.execute(sql)
            con.execute("COMMIT")
        con.execute("INSERT INTO schema_meta(key, value) VALUES('version', '15')")
        con.execute("INSERT INTO clinics(id, name, created_at) VALUES('c_old000000001', 'Veche', '2026-01-01T00:00:00Z')")
        con.execute("INSERT INTO accounts(id, provider, subject, email, clinic_id, created_at) "
                    "VALUES('a_old1', 'google', 's1', 'a@b.md', 'c_old000000001', '2026-01-02T00:00:00Z')")
        con.execute("INSERT INTO accounts(id, provider, subject, email, clinic_id, created_at) "
                    "VALUES('a_new1', 'email', 'x@y.md', 'x@y.md', NULL, '2026-01-03T00:00:00Z')")
    finally:
        con.close()
    with s:
        links = _sql(s, "SELECT account_id, clinic_id FROM account_clinics")
        ver = _sql(s, "SELECT value FROM schema_meta WHERE key='version'")[0][0]
        res.check("версия схемы — последняя", ver, str(db.SCHEMA_VERSION))
        res.check("прежняя запись с клиникой — вход в неё; без клиники — ничего", links,
                  [("a_old1", "c_old000000001")])
