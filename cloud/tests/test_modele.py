"""Образцы закона 195 в кабинете клиники (modele.py, 31.10.2026): «Modele pentru clinică».

Что держит набор:
- исходники нашлись: каждый образец словаря — файл в assets/modele, HTML, дата редакции на листе =
  дата в словаре; ключ образца не совпадает с ключом вкладки кабинета; в листах нет русских
  комментариев разработчика и нет снятого (бот Telegram, бумаги 3/5/6, «PROIECT»);
- основания «Informarea pacienților» те же, что у листа пациента программы (acord.py): без пакета
  SMS — «telefon sau e-mail», с ним — «telefon, e-mail sau SMS»;
- подстановка реквизитов — только через html.escape, пустое поле остаётся жёлтым «…»;
- сторож доступа: без входа — на вход; каждый образец под входом — 200, no-store, noindex;
  неизвестный — 404; филиал по `?c=` — его реквизиты; чужая `?c=` и вход кнопкой программы
  филиала к главной — на кабинет, без данных;
- вкладка «Documente» ведёт на каждый образец (с `?c=` у кабинета с филиалами), без id у карточки;
- галочка SMS отмечена только у клиники с работающим пакетом; письмо о лицензии называет образцы.
"""
import pathlib
import re
from html.parser import HTMLParser
import sys
import tempfile

from harness import CLOUD, ROOT, Client, Result, Server
from test_branches import BANK_ENV, BRANCH, DIRECTOR, MAIN, _add, _enter, _register, _sql, _token_of
from test_contlink import _link, _open

sys.path.insert(0, str(CLOUD))
from app import mail, modele, views  # noqa: E402

ENV = {**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_SMS_OFFERED": "1", "DP_SMSMD_TOKEN": "t"}
EVIL_NAME = "<img src=x onerror=alert(1)>"
EVIL_ADDR = "\"'><script>alert(2)</script>"
ACORD = ROOT / "bot" / "app" / "modules" / "patients" / "acord.py"


class _Visible(HTMLParser):
    """Текст листа БЕЗ SMS-разделов (`sms-only`) и галочки (`smstoggle`) — то, что печатает клиника без
    пакета. Глубина считается по стеку открытых тегов: SMS-раздел — и <span>, и <li>, и <div>."""
    VOID = {"input", "br", "meta", "img", "hr", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.text = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        cls = dict(attrs).get("class") or ""
        hide = any(c in ("sms-only", "smstoggle") for c in cls.split())
        self.stack.append(hide or (bool(self.stack) and self.stack[-1]))

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if not (self.stack and self.stack[-1]):
            self.text.append(data)


def _without_sms(page: str) -> str:
    p = _Visible()
    p.feed(re.sub(r"<(script|style)>.*?</>", "", page, flags=re.S))
    return " ".join(" ".join(p.text).split())


def _scripts(page: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", page, re.S)


def suite_rules(res: Result) -> None:
    """Без сервера: файлы, версии, тексты, подстановка, письмо."""
    keys = list(modele.MODELE)
    res.check("четыре образца по порядку кабинета", keys, ["informare", "registru", "bitlocker", "verificare"])
    pages = {k: modele.source(k) for k in keys}
    res.ok("исходники нашлись: каждый образец — HTML-файл в assets/modele",
           all(p is not None and p.startswith("<!doctype html>") and p.rstrip().endswith("</html>")
               for p in pages.values()), repr({k: (p or "")[:40] for k, p in pages.items()}))
    for k, p in pages.items():
        ver = re.findall(r"redacția din (\d{2}\.\d{2}\.\d{4})", p or "")
        res.check(f"«{k}»: дата редакции на листе = дата в словаре", ver, [modele.MODELE[k]["version"]])
    tabs = {t for t, _, _ in views.CONT_TABS}
    res.ok("⛔ ключ образца не равен ключу вкладки кабинета", not tabs & set(keys))
    res.check("файлы — ровно образцы словаря (лишний лист в папке никто не откроет)",
              sorted(f.name for f in modele.ASSETS.glob("*.html")), sorted(m["file"] for m in modele.MODELE.values()))
    allp = "\n".join(pages.values())
    res.ok("нет русских комментариев разработчика (клиника видит «Просмотр кода»)",
           not re.search(r"[А-Яа-яЁё]", allp.replace("BitLocker ожидает\nактивации", "")),
           re.findall(r".{20}[А-Яа-яЁё]+.{20}", allp)[:3])
    res.ok("снятое не вернулось: бот Telegram, «PROIECT», бумаги 3/5/6 как документы клиники",
           "Telegram" not in allp and "PROIECT" not in allp and "documentul 5" not in allp
           and "documentele 5–6" not in allp and "două exemplare" not in allp and "qr-print" not in allp, "")
    # Олег 31.10 (вопрос 2): про доступ поставщика вне SMS лист молчит — ни строки об удалённой помощи,
    # ни обратных абсолютных утверждений, которые спорили бы с DPA 30.10 (§ 1.1, 2.3)
    gone = ("Alte transmiteri nu au loc", "NU are acces", "nu se transmit terților", "nu părăsesc calculatorul",
            "pot fi transmise doar", "Asistență rapidă", "asistență la distanță")
    res.ok("о доступе поставщика вне SMS образцы молчат: ни «nu are acces»/«alte transmiteri nu au loc», "
           "ни удалённой помощи", not [g for g in gone if g in allp], repr([g for g in gone if g in allp]))
    fill = {k: _scripts(p)[0] for k, p in pages.items()}
    res.ok("скрипт жёлтых полей — один на все листы (ES5, ничего не запоминает)",
           len(set(fill.values())) == 1 and "localStorage" not in allp and "contentEditable" in fill["informare"])
    res.ok("реквизиты размечены: название клиники — у каждого листа",
           all('data-k="name"' in p for p in pages.values())
           and all(f'data-k="{f}"' in pages["informare"] for f in modele.FIELDS))
    res.ok("галочка «Pachetul SMS» — у информирования, реестра и списка проверки, не у BitLocker",
           all('id="sms-toggle"' in pages[k] for k in ("informare", "registru", "verificare"))
           and 'id="sms-toggle"' not in pages["bitlocker"])

    # основания — как у листа пациента в программе (patients.md: «основания обязаны совпадать»)
    acord = ACORD.read_text(encoding="utf-8")
    inf = pages["informare"]
    res.ok("исходники нашлись: acord.py программы", "_T_SMS" in acord and '"li4"' in acord)
    res.ok("без SMS: «telefon sau e-mail» — как acord.py li4; с SMS: «telefon, e-mail sau SMS» — как _T_SMS",
           "periodic (telefon sau e-mail)" in acord and "periodic (telefon, e-mail sau SMS)" in acord
           and 'periodic (telefon<span class="no-sms"> sau e-mail</span><span class="sms-only">, e-mail sau '
               'SMS</span>)' in inf, inf[inf.find("periodic (telefon"):][:160])
    plain = _without_sms(inf)
    res.ok("лист без пакета SMS не называет SMS (а с пакетом — называет), как лист пациента программы",
           "SMS" not in plain and "telefon sau e-mail" in plain and "Cine prelucrează datele" in plain
           and "SMS.MD" in inf, plain[plain.find("periodic"):][:200])

    clinic = {"name": EVIL_NAME, "idno": "1003600012345", "address": EVIL_ADDR, "phone": "  "}
    page = modele.render("informare", clinic)
    res.ok("⛔ реквизиты — через html.escape: ни сырого <img>, ни <script> сверх своих",
           "<img" not in page and page.count("<script>") == pages["informare"].count("<script>")
           and "&lt;img src=x onerror=alert(1)&gt;" in page and "&quot;&#x27;&gt;&lt;script&gt;" in page)
    res.ok("IDNO подставлен, пустой телефон — жёлтый заполнитель «telefon»",
           '<span class="fill" data-k="idno">1003600012345</span>' in page
           and '<span class="fill" data-k="phone">«telefon»</span>' in page)
    res.ok("подстановка не трогает поля без data-k (их дописывают ручкой)",
           "«e-mail / telefon responsabil»" in page and "«zz.ll.aaaa»" in page)
    res.ok("галочка SMS: без пакета снята, с пакетом отмечена",
           'id="sms-toggle">' in page and 'id="sms-toggle" checked>' in modele.render("informare", clinic, True)
           and 'id="sms-toggle" checked' not in modele.render("bitlocker", clinic, True))
    res.ok("неизвестный образец и путь вместо ключа — None",
           modele.render("nu-exista", clinic) is None and modele.render("../main", clinic) is None
           and modele.source("informare-pacienti.html") is None)
    res.ok("sms_on: без строки счёта — нет (offered(None) при DP_SMS_OFFERED сказал бы «да»)",
           modele.sms_on(None) is False)

    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "contract-2026-10-30.pdf"
        f.write_bytes(b"%PDF-1.4\n")
        keep = mail.config.CONTRACT
        try:
            mail.config.CONTRACT = str(f)
            letter = mail.license_letter("C", "2026-12-01", "standard")[1]
        finally:
            mail.config.CONTRACT = keep
    res.ok("письмо о лицензии: образцы 195 — в том же разделе «Documente»",
           "modelele de documente pentru Legea 195" in letter and mail.DOCUMENTS_URL in letter
           and letter.index(mail.DOCUMENTS_URL) < letter.index("modelele de documente"))


def suite_cabinet(res: Result) -> None:
    """Сторож доступа, реквизиты своей клиники, вкладка, SMS, филиал, вход кнопкой программы."""
    with Server(env=ENV) as s:
        anon = Client(s.url)
        for k in modele.MODELE:
            r = anon.get(f"/cont/modele/{k}")
            res.check(f"без входа «{k}» — на вход", (r.status, r.location), (303, "/cont/login"))
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        _sql(s, "UPDATE clinics SET name=?, address=? WHERE id=?", EVIL_NAME, EVIL_ADDR, main)

        for k in modele.MODELE:
            r = c.get(f"/cont/modele/{k}")
            res.ok(f"«{k}» под входом: 200, HTML, no-store, noindex, реквизиты экранированы",
                   r.status == 200 and r.headers.get("content-type", "").startswith("text/html")
                   and r.headers.get("cache-control") == "no-store"
                   and r.headers.get("x-robots-tag", "").startswith("noindex")
                   and "&lt;img src=x onerror=alert(1)&gt;" in r.body and "<img" not in r.body
                   and "<script>alert" not in r.body, f"{r.status} {r.headers}")
        inf = c.get("/cont/modele/informare").body
        res.ok("IDNO и телефон клиники подставлены",
               f'data-k="idno">{MAIN["idno"]}<' in inf and f'data-k="phone">{MAIN["phone"]}<' in inf)
        res.ok("SMS: счёта нет — галочка снята", 'id="sms-toggle" checked' not in inf)
        res.check("неизвестный образец — 404", c.get("/cont/modele/nu-exista").status, 404)
        res.check("путь вместо ключа — 404", c.get("/cont/modele/..%2F..%2Fmain.py").status, 404)
        res.check("⛔ чужая или несуществующая ?c= — на кабинет, без данных",
                  (c.get("/cont/modele/informare?c=c_0000000000").status,
                   c.get("/cont/modele/informare?c=c_0000000000").location), (303, "/cont"))

        docs = c.get("/cont/documente").body
        pane = docs[docs.index("data-pane='documente'"):]
        res.ok("вкладка «Documente»: «Modele pentru clinică» — ссылка на каждый образец, в новой вкладке",
               "Modele pentru clinică" in pane
               and all(f"href='/cont/modele/{k}' target='_blank' rel='noopener'" in pane for k in modele.MODELE)
               and all(m["title"] in pane and f"modelul din {m['version']}" in pane for m in modele.MODELE.values()),
               pane[:3000])
        res.ok("карточка — после документов поставщика, до актов акцепта",
               pane.index("Documentele furnizorului") < pane.index("Modele pentru clinică")
               < pane.index("Acceptarea termenilor"))
        res.ok("без пакета SMS — строки про SMS-разделы нет", "secțiunile despre memento-uri" not in pane)

        _sql(s, "INSERT INTO sms_accounts(clinic_id, daily_cap, updated_at) VALUES(?, 50, '2026-10-31T10:00:00Z')", main)
        res.ok("SMS: пакет работает — галочка отмечена, во вкладке строка про SMS-разделы",
               'id="sms-toggle" checked' in c.get("/cont/modele/informare").body
               and "secțiunile despre memento-uri" in c.get("/cont/documente").body)
        _sql(s, "UPDATE sms_accounts SET enabled=0 WHERE clinic_id=?", main)
        res.ok("SMS выключен Олегом — галочка снята",
               'id="sms-toggle" checked' not in c.get("/cont/modele/informare").body)

        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        br = c.get(f"/cont/modele/informare?c={bid}").body
        res.ok("филиал по ?c=: его название и адрес, не главной",
               f'data-k="name">{BRANCH["name"]}<' in br and f'data-k="address">{BRANCH["address"]}<' in br
               and "onerror" not in br, br[br.find("1. Cine"):][:400])
        pane = c.get(f"/cont/documente?c={bid}").body
        res.ok("кабинет с филиалами: ссылки на образцы несут ?c= открытой клиники",
               all(f"href='/cont/modele/{k}?c={bid}'" in pane for k in modele.MODELE))

        prog = Client(s.url)
        _, url = _link(prog, _token_of(s, bid))
        b = Client(s.url)
        _open(b, url)
        res.ok("вход кнопкой программы филиала: образец открывается с реквизитами филиала",
               f'data-k="name">{BRANCH["name"]}<' in b.get("/cont/modele/registru").body)
        r = b.get(f"/cont/modele/registru?c={main}")
        res.check("⛔ вход кнопкой филиала: ?c=главная — на кабинет, без данных главной",
                  (r.status, r.location), (303, "/cont"))
