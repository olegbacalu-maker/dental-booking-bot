"""Ответ пациента ссылкой из SMS (Premium волна 2а): коды, страница, забор ответов, право sms_link, подарки Premium.

Без сервера: шаг схемы 25 (состав колонок — ни телефона, ни имени пациента, ни времени визита; повтор шага), алфавит
кода, поля /v1/link/new, право sms_link от множества Premium, мета-теги страницы (одни на все состояния, без клиники),
GET страницы ничего не пишет (разбор `ast`). Через живой сервер: /v1/link/new · inbox · close с отказами, страница
семи состояний RO/RU с подписью формы и Origin, перебор с адреса и роботы превью, уборка задачей, 80 SMS один раз
при первой оплате Premium, имя отправителя без оплаты года только при Premium на год.
"""
import ast
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

from harness import CLOUD, Client, Result, Server, cid_from

sys.path.insert(0, str(CLOUD))
from app import config, db, license, mail, plink, plink_page, sms, tiers  # noqa: E402
from test_account import BANK_ENV, _letters, _sql  # noqa: E402
from test_paylink import HDR, _link, _token  # noqa: E402

UTC = timezone.utc
P, PR = tiers.PLUS, tiers.PREMIUM
SMS_ENV = {"DP_SMSMD_TOKEN": "test-token", "DP_SMSMD_BASE_URL": "http://127.0.0.1:9", "DP_SMS_OFFERED": "1",
           "DP_SMS_PACKS": "100:50", "DP_SMS_NAME_PRICE": "90", "DP_LINK_HOST": "v.test.md"}
BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HUMAN = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36"
# слова, которых не должно быть в названиях колонок таблиц ссылок: данные пациента и визита
PATIENT_WORDS = ("phone", "tel", "name", "text", "patient", "appt", "visit", "doctor", "start", "slot", "idnp")


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _sub(tier: str = PR, plan: str = "standard", gdoc_until: datetime | None = None) -> dict:
    return {"plan": plan, "tier": tier, "price": 0, "grace_days": 14, "valid_until": None, "sms_until": None,
            "gdoc_until": gdoc_until.strftime(db.TS) if gdoc_until else None}


def _row(state: str = plink.OPEN, lang: str = "ro", answered: str | None = None) -> dict:
    return {"code": "K7Q2MX", "lang": lang, "state": state, "label": "Clinica Zâmbet Dent", "phone": "+373 79 123 456",
            "answered_at": answered, "until": "2099-01-01T08:00:00Z"}


def _head(page: str) -> str:
    """Мета-теги страницы: от <head> до стилей (язык тела — в <html lang>, он от переключателя)."""
    return page.split("<head>", 1)[1].split("<style>", 1)[0]


def suite_schema(res: Result) -> None:
    """⛔ В таблицах ссылок — только код, ответ, время ответа, подпись и телефон КЛИНИКИ (сторож 13 разведки)."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for step in range(1, db.SCHEMA_VERSION + 1):
            db.apply_step(con, step)
        try:
            db.apply_step(con, 25)
            again = ""
        except sqlite3.OperationalError as e:
            again = str(e)
        res.ok("шаг 25: повтор шага без ошибки", db.SCHEMA_VERSION >= 25 and not again, again)
        links = [r[1] for r in con.execute("PRAGMA table_info(links)")]
        clinics = [r[1] for r in con.execute("PRAGMA table_info(link_clinics)")]
        res.check("links: состав колонок перечислен — код, клиника, вид, язык, ответ, перемена, граница, время",
                  links, list(plink.LINK_COLUMNS))
        res.check("link_clinics: подпись и телефон клиники, счётчик перемен — и только", clinics, list(plink.CLINIC_COLUMNS))
        bad = [c for c in links if any(w in c for w in PATIENT_WORDS)]
        res.check("links: ни телефона, ни имени, ни текста, ни времени визита", bad, [])
        res.ok("subscriptions.name_free_until — конец годового Premium (подарок имени)",
               "name_free_until" in {r[1] for r in con.execute("PRAGMA table_info(subscriptions)")})
        fks = {t: {r[2] for r in con.execute(f"PRAGMA foreign_key_list({t})")} for t in ("links", "link_clinics")}
        res.check("обе таблицы ссылаются только на clinics", fks, {"links": {"clinics"}, "link_clinics": {"clinics"}})
    finally:
        con.close()


def suite_rules(res: Result) -> None:
    now = _now()
    end = now + timedelta(days=40)
    res.check("алфавит кода: 32 знака без I O 0 1", (len(plink.ALPHABET), set("IO01") & set(plink.ALPHABET)), (32, set()))
    res.ok("CODE_RE: 6 знаков алфавита, строчные — после norm",
           bool(plink.CODE_RE.match("K7Q2MX")) and not plink.CODE_RE.match("K7Q2M0") and not plink.CODE_RE.match("K7Q2M")
           and bool(plink.CODE_RE.match(plink.norm(" k7q2mx "))))
    res.check("право: LINK_TIERS — только Premium", sorted(tiers.LINK_TIERS), [PR])
    lu = (lambda x: tiers.link_until(x, end, now))
    res.check("sms_link: Premium — до конца файла; Plus, пробный — нет; ушедшая с Premium — до gdoc_until, не дальше",
              [lu(_sub(PR)), lu(_sub(P)), lu(_sub(PR, "trial")), lu(None), lu(_sub(P, gdoc_until=now + timedelta(days=3))),
               lu(_sub(P, gdoc_until=end + timedelta(days=9))), lu(_sub(P, gdoc_until=now - timedelta(seconds=1)))],
              [end, None, None, None, now + timedelta(days=3), end, None])
    ts = end.strftime(db.TS)
    res.check("права файла Premium: gcal, gcal_doctor и sms_link одной датой; у Plus sms_link нет",
              [license.features(_sub(PR), end, now), license.features(_sub(P), end, now)],
              [{"gcal": ts, "gcal_doctor": ts, "sms_link": ts}, {"gcal": ts}])
    res.check("слова прав: три права по порядку", license.rights({"gcal": "A", "gcal_doctor": "B", "sms_link": "C"}),
              "gcal до A, gcal_doctor до B, sms_link до C")
    until = (now + timedelta(days=1)).strftime(db.TS)
    ok = {"kind": "confirm", "until": until, "langs": ["ro", "ru"], "label": " Clinica  Zambet ", "phone": "022 123 456"}
    f = plink.clean_new(ok, now)
    res.ok("поля /v1/link/new: годные — подпись без лишних пробелов, языки по порядку",
           f is not None and f["label"] == "Clinica Zambet" and f["langs"] == ["ro", "ru"], repr(f))
    bad = [{**ok, "kind": "offer"}, {**ok, "until": now.strftime(db.TS)}, {**ok, "until": "2026-11-28 07:00"},
           {**ok, "until": (now + plink.UNTIL_MAX + timedelta(hours=1)).strftime(db.TS)}, {**ok, "langs": []},
           {**ok, "langs": ["de"]}, {**ok, "langs": ["ro"] * (plink.BATCH_MAX + 1)}, {**ok, "label": "  "},
           {**ok, "phone": "<script>"}, {**ok, "phone": 22}]
    res.check("поля /v1/link/new: вид не confirm, граница в прошлом или далеко, языки, подпись, телефон — link_bad",
              [plink.clean_new(b, now) for b in bad], [None] * len(bad))
    res.check("закрытие: только список кодов алфавита, не больше CLOSE_MAX",
              [plink.clean_codes(["k7q2mx"]), plink.clean_codes(["K7Q2M0"]), plink.clean_codes("K7Q2MX"),
               plink.clean_codes(["K7Q2MX"] * (plink.CLOSE_MAX + 1))], [["K7Q2MX"], None, None, None])
    # мета-теги: одни на все состояния живого кода, язык — кода, без клиники; у мёртвой страницы og:* нет
    rows = [_row(), _row(plink.YES, answered="2026-11-27T08:04:00Z"), _row(plink.NO, answered="2026-11-27T08:04:00Z"),
            _row(plink.CLOSED)]
    heads = {_head(plink_page.render(r, lang, now, just)) for r in rows for lang in ("ro", "ru") for just in (False, True)}
    res.check("мета-теги одни на все состояния и оба языка страницы (язык — кода)", len(heads), 1)
    head = heads.pop()
    res.ok("мета-теги V1 (w2-look § 4): заголовок, описание, картинка, locale, noindex; без og:url и og:site_name",
           "<title>Confirmați programarea</title>" in head
           and "content='Apăsați pentru a răspunde: Vin sau Nu pot veni'" in head
           and f"content='https://{config.LINK_HOST}/og/confirm.png'" in head and "og:locale' content='ro_RO'" in head
           and "noindex, nofollow" in head and "og:url" not in head and "og:site_name" not in head, head)
    res.ok("мета-теги: ни клиники, ни кода, ни телефона", all(x not in head for x in ("Zâmbet", "Clinica", "K7Q2MX", "123")))
    ru = _head(plink_page.render(_row(lang="ru"), "ro", now))
    res.ok("код русского пациента: «Подтвердите запись», ru_RU", "<title>Подтвердите запись</title>" in ru
           and "ru_RU" in ru and "Нажмите, чтобы ответить: приду или не смогу прийти" in ru, ru)
    dead = plink_page.dead("ro")
    res.ok("безликая страница: без og:*, без клиники", "og:" not in dead and "Zâmbet" not in dead
           and "Linkul nu mai este valabil" in dead and "<title>Programare</title>" in dead)
    yes = plink_page.render(_row(plink.YES, answered="2026-11-27T08:04:00Z"), "ro", now, just=True)
    res.ok("«Vin»: анимация CSS, при «уменьшить движение» — готовой; без JavaScript",
           "class='anim'" in yes and "prefers-reduced-motion:reduce" in yes and "<script" not in yes.lower()
           and "Mulțumim! Vă așteptăm." in yes)
    again = plink_page.render(_row(plink.NO, answered="2026-11-27T08:04:00Z"), "ru", now)
    res.ok("«уже не придёт» по-русски: время ответа по Кишинёву, звонок клинике tel:, «Всё-таки приду»",
           "Вы сообщили, что не придёте" in again and "Ваш ответ: Не смогу прийти · 27.11, 10:04" in again
           and "href='tel:+37379123456'" in again and "Всё-таки приду" in again, again[-1500:])
    res.ok("подпись формы: эти и прошлые сутки — да, позавчера и чужой код — нет",
           plink_page.mark_ok("K7Q2MX", plink_page.mark("K7Q2MX", now - timedelta(days=1)), now)
           and not plink_page.mark_ok("K7Q2MX", plink_page.mark("K7Q2MX", now - timedelta(days=2)), now)
           and not plink_page.mark_ok("K7Q2MX", plink_page.mark("ABCDEF", now), now)
           and not plink_page.mark_ok("K7Q2MX", "", now))
    res.ok("роботы превью узнаются по User-Agent", plink_page.is_bot(BOT) and plink_page.is_bot("WhatsApp/2.23")
           and plink_page.is_bot("facebookexternalhit/1.1") and not plink_page.is_bot(HUMAN))
    # подарки Premium без сервера
    free = now + timedelta(days=100)
    acc = {"sender_live": "Zambet", "sender_until": None, "sender_prepaid": 0, "sender_state": sms.S_ACTIVE}
    res.check("имя при годовом Premium: от своего имени без оплаты года; после — от общего",
              [sms.sender_now(acc, now, free), sms.sender_now(acc, now, None), sms.sender_now(acc, now, now)],
              ["Zambet", config.SMS_COMMON, config.SMS_COMMON])
    res.check("год имени: годовой Premium — free, иначе прежние состояния",
              [sms.name_year(acc, now, free), sms.name_year(acc, now), sms.name_year(None, now, free)],
              [sms.Y_FREE, sms.Y_UNPAID, sms.Y_FREE])
    res.check("подарок 80 — константа рядом с пробными 30", (config.SMS_PREMIUM_UNITS, config.SMS_TRIAL_UNITS), (80, 30))
    s1, b1 = mail.sms_name_year_letter("free_soon", "Clinica T", "Zambet", free.strftime(db.TS))
    _, b2 = mail.sms_name_year_letter("free_over", "Clinica T", "Zambet", free.strftime(db.TS))
    res.ok("письма о конце годового Premium: имя включено до даты / больше не включено, путь оплаты года",
           f"inclus în Premium anual până la {mail.ro_date(free.strftime(db.TS))}" in s1
           and "plătiți din nou DentPilot Premium pe un an" in b1 and "nu mai este inclus" in b2
           and "Setări › SMS" in b1 and "Setări › SMS" in b2, b1 + b2)


def _defs(path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


_WRITES = re.compile(r"\b(UPDATE|INSERT|DELETE|REPLACE)\b", re.I)


def _writes(fn: ast.FunctionDef) -> list[str]:
    """Что в теле функции похоже на запись в базу: immediate=True, SQL записи, запись ответа и журнала."""
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.keyword) and n.arg == "immediate":
            out.append(f"{fn.name}: immediate")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and _WRITES.search(n.value):
            out.append(f"{fn.name}: SQL записи")
        if isinstance(n, ast.Attribute) and n.attr in ("respond", "issue", "close", "audit", "purge", "ledger"):
            out.append(f"{fn.name}: {n.attr}")
    return out


def suite_get_readonly(res: Result) -> None:
    """⛔ GET страницы ничего не пишет: превью Google Messages открывает ссылку раньше человека (сторож 11)."""
    pub = _defs(CLOUD / "app" / "routes_public.py")
    pl = _defs(CLOUD / "app" / "plink.py")
    page = _defs(CLOUD / "app" / "plink_page.py")
    names = ("link_page", "_dead", "_page", "link_og")
    res.ok("исходники нашлись: обработчики страницы и её помощники",
           all(n in pub for n in names) and {"lookup", "alive", "norm"} <= set(pl) and {"render", "dead"} <= set(page))
    bad = [w for n in names for w in _writes(pub[n])]
    bad += [w for n in ("lookup", "alive", "norm") for w in _writes(pl[n])]
    bad += [w for n in page.values() for w in _writes(n)]
    res.check("GET страницы: ни immediate, ни SQL записи, ни записи ответа — в обработчике и во всём, что он зовёт", bad, [])
    res.ok("POST записывает ответ — сторож видит запись там, где она есть", bool(_writes(pub["link_answer"])))


def _api(c: Client, method: str, path: str, tok: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    hdr = {**HDR, "Authorization": f"Bearer {tok}"}
    if data is not None:
        hdr["Content-Type"] = "application/json"
    r = c._do(path, data, hdr) if method == "POST" else c.get(path, headers=hdr)
    return r.status, (json.loads(r.body) if r.body.startswith("{") else {})


def _premium(s: Server, admin: Client, name: str, idno: str) -> tuple[str, str]:
    today = datetime.now(UTC).date()
    cid = cid_from(admin.post("/admin/clinics", name=name, idno=idno, email=f"{idno}@example.md").location)
    admin.post(f"/admin/clinics/{cid}/issue", kind="dates", valid_until=f"{today + timedelta(days=30):%Y-%m-%d}",
               grace_days="14")
    admin.post(f"/admin/clinics/{cid}/tier", tier="premium")
    return cid, _token(s, cid)


def _until(hours: int = 24) -> str:
    return (_now() + timedelta(hours=hours)).strftime(db.TS)


def _t(page: str, a: str) -> str:
    """Подпись формы с кнопкой `a` со страницы (её отдаёт только GET)."""
    m = re.search(r"name='t' value='([0-9a-f]+)'><input type='hidden' name='l' value='\w+'><input type='hidden' "
                  rf"name='a' value='{a}'>", page)
    return m.group(1) if m else ""


def _state(s: Server, code: str):
    return _sql(s, "SELECT state, seq FROM links WHERE code=?", code)[0]


def suite_api(res: Result) -> None:
    with Server(env={**BANK_ENV, **SMS_ENV}) as s:
        admin = Client(s.url).login()
        cid, tok = _premium(s, admin, "Clinica Zâmbet Dent", "7777777777791")
        anon = Client(s.url)
        claim = json.loads(__import__("harness").unb64u(_sql(s, "SELECT payload FROM issues WHERE clinic_id=? "
                                                                "ORDER BY seq DESC LIMIT 1", cid)[0][0]))
        res.ok("файл Premium несёт право sms_link (перевыдача при «Вариант вручную»)",
               (claim.get("features") or {}).get("sms_link") == claim["grace_until"], claim.get("features"))
        new = {"kind": "confirm", "until": _until(), "langs": ["ro", "ru", "ro"], "label": "Clinica Zâmbet Dent",
               "phone": "+373 79 123 456"}
        st, data = _api(anon, "POST", "/v1/link/new", tok, new)
        codes = data.get("codes") or []
        res.ok("/v1/link/new: хост из DP_LINK_HOST, три кода алфавита, разные",
               st == 200 and data.get("host") == "v.test.md" and len(set(codes)) == 3
               and all(plink.CODE_RE.match(x) for x in codes), (st, data))
        res.check("языки кодов — по порядку запроса", [_sql(s, "SELECT lang FROM links WHERE code=?", x)[0][0] for x in codes],
                  ["ro", "ru", "ro"])
        res.check("link_clinics: подпись и телефон клиники", _sql(s, "SELECT label, phone, seq FROM link_clinics WHERE "
                                                                     "clinic_id=?", cid), [("Clinica Zâmbet Dent", "+373 79 123 456", 0)])
        res.check("без токена — 401", anon._do("/v1/link/new", b"{}", {"Content-Type": "application/json"}).status, 401)
        res.check("кривой JSON — bad_json", anon._do("/v1/link/new", b"{", {**HDR, "Authorization": f"Bearer {tok}"}).status,
                  400)
        st, data = _api(anon, "POST", "/v1/link/new", tok, {**new, "until": "вчера"})
        res.check("кривые поля — 400 link_bad с текстом", (st, data.get("code"), bool(data.get("text"))), (400, "link_bad", True))
        st, data = _api(anon, "GET", "/v1/link/inbox?after=0", tok)
        res.check("inbox пуст: seq 0", (st, data.get("seq"), data.get("items"), data.get("more")), (200, 0, [], False))

        # страница: GET не пишет
        code, ru_code = codes[0], codes[1]
        before = _sql(s, "SELECT * FROM links ORDER BY code")
        r = anon.get(f"/r/{code}", headers={"User-Agent": BOT})
        res.ok("страница кода: клиника, вопрос, обе кнопки, мета V1; без cookie; no-store и CSP",
               r.status == 200 and "Clinica Zâmbet Dent" in r.body and "Veniți la programare?" in r.body
               and "value='yes'" in r.body and "value='no'" in r.body and "<title>Confirmați programarea</title>" in r.body
               and "set-cookie" not in r.headers and r.headers.get("cache-control") == "no-store"
               and "default-src 'none'" in r.headers.get("content-security-policy", "")
               and "form-action 'self'" in r.headers.get("content-security-policy", ""), (r.status, r.headers))
        anon.get(f"/r/{code.lower()}?l=ru")
        res.check("⛔ GET (робот превью, строчные, ?l=ru) ничего не записал", _sql(s, "SELECT * FROM links ORDER BY code"), before)
        res.check("time-of-visit на странице нет: ни даты, ни часа", re.findall(r"\b\d{1,2}:\d{2}\b", r.body), [])
        t_yes = _t(r.body, "yes")
        res.ok("подпись формы есть у обеих кнопок", bool(t_yes) and bool(_t(r.body, "no")))
        # POST: Origin и подпись
        res.check("POST с чужим Origin — 403, ответ не записан",
                  (anon.post(f"/r/{code}", headers={"Origin": "https://evil.example"}, a="yes", t=t_yes).status,
                   _state(s, code)), (403, ("open", 0)))
        r = anon.post(f"/r/{code}", a="yes", t="")
        res.check("⛔ POST без подписи формы — 403, ответ не записан, страница с вопросом",
                  (r.status, _state(s, code), "Veniți la programare?" in r.body), (403, ("open", 0), True))
        r = anon.post(f"/r/{code}", a="yes", t=_t(anon.get(f"/r/{ru_code}").body, "yes"))
        res.check("подпись чужого кода — 403", (r.status, _state(s, code)), (403, ("open", 0)))
        r = anon.post(f"/r/{code}", headers={"Origin": s.url}, a="yes", t=t_yes)
        res.ok("«Vin» (свой Origin): галочка с анимацией, ответ записан переменой 1",
               r.status == 200 and "Mulțumim! Vă așteptăm." in r.body and "class='anim'" in r.body
               and _state(s, code) == ("yes", 1), (r.status, _state(s, code)))
        anon.post(f"/r/{code}", a="yes", t=t_yes)
        res.check("то же нажатие ещё раз — тихий успех без новой перемены", _state(s, code), ("yes", 1))
        st, data = _api(anon, "GET", "/v1/link/inbox?after=0", tok)
        items = data.get("items") or []
        res.ok("inbox: код, перемена 1, yes, время ответа; seq 1",
               data.get("seq") == 1 and len(items) == 1 and items[0]["code"] == code and items[0]["state"] == "yes"
               and items[0]["seq"] == 1 and bool(db.parse_ts(items[0]["at"])), data)
        r = anon.get(f"/r/{code}")
        res.ok("открыл снова: «Ați confirmat deja», время ответа, без анимации, «Nu mai pot veni»",
               "Ați confirmat deja" in r.body and "Răspunsul dvs.: Vin · " in r.body and "class='anim'" not in r.body
               and "Nu mai pot veni" in r.body)
        r = anon.post(f"/r/{code}", a="no", t=_t(r.body, "no"))
        res.ok("передумал → «Nu pot veni»: «Am anunțat clinica», звонок клинике, «Totuși vin»; перемена 2",
               "Am anunțat clinica" in r.body and "href='tel:+37379123456'" in r.body and "Totuși vin" in r.body
               and _state(s, code) == ("no", 2), _state(s, code))
        st, data = _api(anon, "GET", "/v1/link/inbox?after=1", tok)
        res.check("inbox after=1: только последнее слово кода — no", [(i["code"], i["state"], i["seq"]) for i in data["items"]],
                  [(code, "no", 2)])
        r = anon.get(f"/r/{ru_code}")
        res.ok("код русского пациента: страница и мета по-русски", "Вы придёте на приём?" in r.body
               and "<title>Подтвердите запись</title>" in r.body and "Приду" in r.body)
        r = anon.get(f"/r/{ru_code}?l=ro")
        res.ok("переключатель RO: тело по-румынски, мета — языка кода", "Veniți la programare?" in r.body
               and "<title>Подтвердите запись</title>" in r.body)
        r = anon.post(f"/r/{ru_code}", a="yes", l="ro", t=_t(r.body, "yes"))
        res.ok("ответ со страницы RO русского кода: язык формы держится", "Mulțumim! Vă așteptăm." in r.body
               and _state(s, ru_code) == ("yes", 3), _state(s, ru_code))
        # другая клиника не видит и не закрывает чужих кодов
        cid2, tok2 = _premium(s, admin, "Clinica Alta", "7777777777792")
        res.check("чужая клиника: inbox пуст, close — 0", (_api(anon, "GET", "/v1/link/inbox?after=0", tok2)[1]["items"],
                                                          _api(anon, "POST", "/v1/link/close", tok2, {"codes": [code]})[1]["closed"]),
                  ([], 0))
        res.check("close: кривой список — link_bad", _api(anon, "POST", "/v1/link/close", tok, {"codes": ["X"]})[1].get("code"),
                  "link_bad")
        res.check("close своих: 1; повтор — 0", [_api(anon, "POST", "/v1/link/close", tok, {"codes": [code.lower()]})[1]["closed"],
                                                _api(anon, "POST", "/v1/link/close", tok, {"codes": [code]})[1]["closed"]], [1, 0])
        r = anon.get(f"/r/{code}")
        res.ok("закрытый: «Linkul nu mai este valabil» + «modificată sau anulată de clinică», клиника и звонок",
               r.status == 200 and "modificată sau anulată de clinică" in r.body and "Clinica Zâmbet Dent" in r.body
               and "tel:+37379123456" in r.body and "value='yes'" not in r.body)
        res.check("закрытому коду ответ не принимается", (anon.post(f"/r/{code}", a="yes", t=t_yes).status, _state(s, code)),
                  (200, ("closed", 2)))
        # срок прошёл = кода нет
        _sql(s, "UPDATE links SET until=? WHERE code=?", (_now() - timedelta(minutes=1)).strftime(db.TS), codes[2])
        gone, nope = anon.get(f"/r/{codes[2]}"), anon.get("/r/ZZZZZZ")
        res.ok("визит начался: 404, безликая страница без клиники и og:*; «нет такого» — то же самое",
               gone.status == 404 and nope.status == 404 and gone.body == nope.body and "Zâmbet" not in gone.body
               and "og:" not in gone.body and "Programarea a trecut" in gone.body)
        res.check("прошедшему коду ответ не принимается", anon.post(f"/r/{codes[2]}", a="yes", t=t_yes).status, 404)
        og = anon.get("/og/confirm.png")
        res.ok("картинка превью: PNG, кэш на сутки, без cookie", og.status == 200
               and og.headers.get("content-type") == "image/png" and "max-age=86400" in og.headers.get("cache-control", "")
               and "set-cookie" not in og.headers, og.headers)
        # право и модуль
        cid3 = cid_from(admin.post("/admin/clinics", name="Clinica Plus", idno="7777777777793",
                                   email="plus@example.md").location)
        admin.post(f"/admin/clinics/{cid3}/issue", kind="dates",
                   valid_until=f"{date.today() + timedelta(days=30):%Y-%m-%d}", grace_days="14")
        st, data = _api(anon, "POST", "/v1/link/new", _token(s, cid3), new)
        res.check("Plus — 423 link_plan, кодов нет", (st, data.get("code"), _sql(s, "SELECT count(*) FROM links WHERE "
                                                                                   "clinic_id=?", cid3)[0][0]),
                  (423, "link_plan", 0))
        _account(anon, tok)                  # счёт SMS заводится первым обращением программы
        _sql(s, "UPDATE sms_accounts SET enabled=0 WHERE clinic_id=?", cid)
        st, data = _api(anon, "POST", "/v1/link/new", tok, new)
        res.check("модуль SMS выключен тумблером — 423 link_off", (st, data.get("code")), (423, "link_off"))
        _sql(s, "UPDATE sms_accounts SET enabled=1 WHERE clinic_id=?", cid)
        admin.post(f"/admin/clinics/{cid}/tier", tier="plus")
        res.check("вручную Premium → Plus: право снято сразу — link_plan", _api(anon, "POST", "/v1/link/new", tok, new)[1].get("code"),
                  "link_plan")
        res.check("ответы после ухода с Premium программа по-прежнему забирает", len(_api(anon, "GET", "/v1/link/inbox?after=0",
                                                                                         tok)[1]["items"]), 1)
        admin.post(f"/admin/clinics/{cid}/tier", tier="premium")
        now = _now().strftime(db.TS)
        con = sqlite3.connect(s.dir / "cloud.db")
        try:
            con.executemany("INSERT INTO links(code, clinic_id, kind, lang, until, created_at) VALUES(?,?,?,?,?,?)",
                            [(f"Q{i:05d}", cid2, "confirm", "ro", _until(), now) for i in range(config.LINK_DAILY - 1)])
            con.commit()
        finally:
            con.close()
        st, data = _api(anon, "POST", "/v1/link/new", tok2, {**new, "langs": ["ro", "ro"]})
        res.check("потолок кодов за сутки — 429 link_limit, ни одного кода сверх", (st, data.get("code")), (429, "link_limit"))
        res.check("до потолка — выдаётся", _api(anon, "POST", "/v1/link/new", tok2, {**new, "langs": ["ro"]})[0], 200)


def suite_limit(res: Result) -> None:
    """Перебор: 11-й промах с адреса — 429; живой код с того же адреса отвечает; робот превью промахов не копит
    (сторож 18 разведки + находка w2-look)."""
    with Server(env={**BANK_ENV, **SMS_ENV}) as s:
        admin = Client(s.url).login()
        _, tok = _premium(s, admin, "Clinica Limit", "7777777777794")
        c = Client(s.url)
        code = _api(c, "POST", "/v1/link/new", tok, {"kind": "confirm", "until": _until(), "langs": ["ro"],
                                                     "label": "Clinica Limit", "phone": ""})[1]["codes"][0]
        bots = [c.get(f"/r/AAAA{plink.ALPHABET[i]}A", headers={"User-Agent": BOT}).status
                for i in range(15)]
        res.check("робот превью: 15 промахов — все 404, не 429", set(bots), {404})
        people = [c.get(f"/r/BBBB{chr(65 + i)}C", headers={"User-Agent": HUMAN}).status
                  for i in range(10)]                # предел — 10 в час (разведка § 2.4), числом, не константой
        res.check("человек: 10 промахов — 404", set(people), {404})
        r = c.get("/r/CCCCCD", headers={"User-Agent": HUMAN})
        res.ok("11-й промах с адреса — 429, безликая страница «Prea multe încercări»", r.status == 429
               and "Prea multe încercări" in r.body and "og:" not in r.body, (r.status, r.body[-300:]))
        r = c.get(f"/r/{code}", headers={"User-Agent": HUMAN})
        res.ok("живой код с того же адреса отвечает", r.status == 200 and "Veniți la programare?" in r.body
               and "Nu pot veni" in r.body and "Clinica Limit" in r.body, r.status)
        res.check("без кнопки звонка, когда телефона клиники нет", "tel:" in r.body, False)


def suite_jobs(res: Result) -> None:
    """Уборка: код стирается через LINK_KEEP_DAYS после начала визита; удаление клиники стирает её коды."""
    with Server(env={**BANK_ENV, **SMS_ENV}) as s:
        admin = Client(s.url).login()
        cid, tok = _premium(s, admin, "Clinica Jobs", "7777777777795")
        anon = Client(s.url)
        codes = _api(anon, "POST", "/v1/link/new", tok, {"kind": "confirm", "until": _until(), "langs": ["ro", "ro"],
                                                         "label": "Clinica Jobs", "phone": ""})[1]["codes"]
        now = _now()
        _sql(s, "UPDATE links SET until=? WHERE code=?",
             (now - timedelta(days=config.LINK_KEEP_DAYS, hours=1)).strftime(db.TS), codes[0])
        _sql(s, "UPDATE links SET until=? WHERE code=?",
             (now - timedelta(days=config.LINK_KEEP_DAYS) + timedelta(hours=2)).strftime(db.TS), codes[1])
        p = subprocess.run([sys.executable, "-m", "app.jobs", "daily"], cwd=str(CLOUD), env=s.env, capture_output=True,
                           text=True, encoding="utf-8", timeout=120)
        res.check("ежедневная задача: старше срока — стёрт, моложе — остался",
                  (p.returncode, [x for (x,) in _sql(s, "SELECT code FROM links ORDER BY code")]), (0, [codes[1]]))
        res.ok("журнал задачи называет стёртые ссылки", any("ссылки ответа: стёрто 1" in d for (d,) in
                                                            _sql(s, "SELECT detail FROM audit WHERE what='daily'")), p.stdout[-500:])


def _pay(s: Server, admin: Client, anon: Client, path: str, cid: str, tier: str, months: int) -> None:
    anon.post(path, tier=tier, months=str(months), method="transfer", terms="1")
    pid = _sql(s, "SELECT id FROM payments WHERE clinic_id=? AND status='pending' AND kind='license'", cid)[0][0]
    admin.post(f"/admin/payments/{pid}/confirm")


def _account(anon: Client, tok: str) -> dict:
    return _api(anon, "GET", "/v1/sms/account", tok)[1]


def suite_gifts(res: Result) -> None:
    """Подарки Premium (Олег 27.11): 80 SMS один раз при первой оплате Premium; своё имя без оплаты года — только при
    Premium, оплаченном на год, до конца этого года (и после ухода с Premium — до него же); год имени тогда не
    продаётся (409 sms_name_free)."""
    with Server(env={**BANK_ENV, **SMS_ENV}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Cadou", idno="7777777777796",
                                  email="cadou@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        tok = _token(s, cid)
        anon = Client(s.url)
        path = "/plata/" + _link(anon, tok)[1].rsplit("/", 1)[1]
        acc = _account(anon, tok)
        res.ok("пробный: 30 SMS, подарка Premium нет; поля gifts и name_year добавочные",
               acc.get("balance") == config.SMS_TRIAL_UNITS and acc.get("gifts") == {
                   "bonus_units": 80, "bonus_at": None, "name_free_until": None} and acc.get("name_year") == sms.Y_UNPAID,
               acc)
        _pay(s, admin, anon, path, cid, "plus", 1)
        res.check("оплата Plus — подарка нет", _account(anon, tok)["balance"], config.SMS_TRIAL_UNITS)
        _pay(s, admin, anon, path, cid, "premium", 1)
        acc = _account(anon, tok)
        res.ok("первая оплата Premium: +80 одной строкой bonus «cadou DentPilot Premium», дата в gifts",
               acc["balance"] == config.SMS_TRIAL_UNITS + 80 and bool(acc["gifts"]["bonus_at"])
               and _sql(s, "SELECT delta, note FROM sms_ledger WHERE clinic_id=? AND reason='bonus' ORDER BY id", cid)
               == [(30, sms.TRIAL_NOTE), (80, sms.PREMIUM_NOTE)], acc)
        res.ok("помесячный Premium: имя не бесплатно", acc["gifts"]["name_free_until"] is None and acc["name_year"] != sms.Y_FREE)
        _sql(s, "UPDATE sms_accounts SET sender='Cadou', sender_state='requested' WHERE clinic_id=?", cid)
        st, data = _api(anon, "POST", "/v1/sms/order", tok, {"name": 1})
        res.ok("помесячный Premium: год имени платный, как у Plus — нота", st == 200 and data.get("kind") == "sms_name", data)
        _sql(s, "UPDATE payments SET status='rejected' WHERE clinic_id=? AND kind='sms_name'", cid)
        _pay(s, admin, anon, path, cid, "plus", 1)
        _pay(s, admin, anon, path, cid, "premium", 12)
        valid = _sql(s, "SELECT valid_until FROM subscriptions WHERE clinic_id=?", cid)[0][0]
        acc = _account(anon, tok)
        res.ok("уход и возврат на Premium: подарок 80 не повторяется", acc["balance"] == config.SMS_TRIAL_UNITS + 80
               and _sql(s, "SELECT count(*) FROM sms_ledger WHERE clinic_id=? AND note=?", cid, sms.PREMIUM_NOTE)[0][0] == 1, acc)
        res.ok("Premium на год: имя включено до конца оплаченного года (name_free_until = срок), name_year free",
               acc["gifts"]["name_free_until"] == valid and acc["name_year"] == sms.Y_FREE
               and _sql(s, "SELECT name_free_until FROM subscriptions WHERE clinic_id=?", cid)[0][0] == valid, (acc, valid))
        st, data = _api(anon, "POST", "/v1/sms/order", tok, {"name": 1})
        res.check("⛔ год имени при годовом Premium не продаётся — 409 sms_name_free", (st, data.get("code")), (409, "sms_name_free"))
        _sql(s, "UPDATE sms_accounts SET sender_live='Cadou', sender_state='active' WHERE clinic_id=?", cid)
        res.check("одобренное имя без оплаченного года работает: SMS от «Cadou»", _account(anon, tok)["from"], "Cadou")
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("админка: метка «входит в Premium на год до …»", f"входит в Premium на год до {valid[:10]}" in card)
        _pay(s, admin, anon, path, cid, "plus", 1)
        acc = _account(anon, tok)
        res.ok("ушла с Premium на Plus: имя работает до конца оплаченного года Premium", acc["from"] == "Cadou"
               and acc["gifts"]["name_free_until"] == valid, acc)
        # письмо заранее: за NAME_SOON_DAYS до конца годового Premium
        at = db.parse_ts(valid) - timedelta(days=sms.NAME_SOON_DAYS - 2)
        before = len(_letters(s))
        p = subprocess.run([sys.executable, "-m", "app.jobs", "daily", "--at", at.strftime(db.TS)], cwd=str(CLOUD),
                           env=s.env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        mails = _letters(s)[before:]
        res.ok("письмо заранее: имя включено в Premium на год до даты, путь оплаты года",
               p.returncode == 0 and any("inclus în Premium anual" in subj for _, subj, _, _ in mails)
               and _sql(s, "SELECT count(*) FROM reminders WHERE subscription_id=? AND kind='sms_name_free_soon'", cid)[0][0] == 1,
               (p.stdout[-400:], [m[1] for m in mails]))
        _sql(s, "UPDATE subscriptions SET name_free_until=? WHERE clinic_id=?",
             (_now() - timedelta(minutes=1)).strftime(db.TS), cid)
        acc = _account(anon, tok)
        res.check("год Premium кончился: SMS от общего имени, год имени снова платный",
                  (acc["from"], acc["name_year"], acc["gifts"]["name_free_until"]), (config.SMS_COMMON, sms.Y_UNPAID, None))


def suite_caddy(res: Result) -> None:
    """Второй хост Caddy: только страница кода (переписана на /r/<код>) и картинка превью, прочее — 404; та же
    Referrer-Policy, что у основного (no-referrer = Origin: null в форме → 403 на «Vin»)."""
    caddy = (CLOUD / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    m = re.search(r"^" + re.escape(config.LINK_HOST) + r" \{\n(.*?)^\}", caddy, re.M | re.S)
    res.ok("Caddyfile: блок короткого хоста — тот же, что умолчание DP_LINK_HOST", m is not None, config.LINK_HOST)
    block = m.group(1) if m else ""
    res.ok("короткий хост: код из 6 знаков переписывается на /r/<код> приложения, ?l= не трогается",
           "path_regexp code ^/([A-Za-z0-9]{6})$" in block and f"rewrite * {plink_page.PATH}/{{re.code.1}}" in block, block)
    res.ok("короткий хост: картинка превью — тем же адресом, что в мета-тегах", f"handle {plink_page.OG_PATH} {{" in block)
    res.ok("короткий хост: всё прочее — 404 (кабинет, админка и API только на cloud.)",
           re.search(r"^\thandle \{\n\t\trespond 404\n\t\}", block, re.M) is not None, block)
    sites = re.findall(r"^\S+ \{$", caddy, re.M)
    policies = re.findall(r"^\s*Referrer-Policy\s+(\S+)", caddy, re.M)
    res.ok("Referrer-Policy в каждом блоке хоста и нигде не no-referrer",
           len(policies) == len(sites) >= 2 and "no-referrer" not in policies, f"{sites} {policies}")


SUITES = [
    ("Ссылки ответа: шаг 25 — в таблицах ни телефона, ни имени, ни времени визита; повтор шага", suite_schema),
    ("Ссылки ответа: код, поля, право sms_link, мета-теги страницы, подарки Premium — без сервера", suite_rules),
    ("Ссылки ответа: GET страницы ничего не пишет (разбор ast)", suite_get_readonly),
    ("Ссылки ответа: /v1/link/new · inbox · close, страница RO/RU, подпись формы и Origin, право, потолок", suite_api),
    ("Ссылки ответа: перебор с адреса — 429, живой код отвечает, робот превью не копит промахов", suite_limit),
    ("Ссылки ответа: уборка ежедневной задачей", suite_jobs),
    ("Ссылки ответа: второй хост в Caddyfile — страница кода и картинка, прочее 404", suite_caddy),
    ("Подарки Premium: 80 SMS один раз при первой оплате, имя без оплаты года только при Premium на год", suite_gifts),
]
