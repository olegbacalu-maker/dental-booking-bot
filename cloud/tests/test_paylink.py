"""Оплата из программы (02.10): ссылка по токену программы, публичная страница
оплаты, нота переводом, карта через стенд maib, IDNO на месте, срок жизни ссылки.
cloud.md › «Оплата из программы».
"""
import json
import sys

from harness import Client, Result, Server, cid_from

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app import config, paylink, tiers, views  # noqa: E402
from app import payments as pay  # noqa: E402
from test_account import BANK_ENV, _letters, _sql  # noqa: E402
from test_maib import FakeMaib  # noqa: E402
from test_renew import rn  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402
from app import license as srv_license  # noqa: E402

HDR = {"User-Agent": "DentPilot/1.36.1", "X-DentPilot-Device": "d_0a1b2c3d4e5f",
       "X-DentPilot-Channel": "stable", "X-DentPilot-OS": "Windows 11 (10.0.26200)"}


def _token(s: Server, cid: str) -> str:
    return _sql(s, "SELECT renew_token FROM clinics WHERE id=?", cid)[0][0] or ""


def _link(anon: Client, token: str):
    r = anon._do(paylink.API_PATH, b"", {**HDR, "Authorization": f"Bearer {token}"})
    data = json.loads(r.body) if r.status == 200 else {}
    return r, data.get("url", "")


def suite_paylink(res: Result) -> None:
    with Server(env={**BANK_ENV}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Plată Program", idno="1234567890123",
                                  email="plata@example.md").location)
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        tok = _token(s, cid)
        res.ok("после выдачи у клиники есть токен программы", len(tok) >= 32)
        anon = Client(s.url)
        res.check("ссылка без токена — 401", anon._do(paylink.API_PATH, b"", HDR).status, 401)
        res.check("чужой токен — 401", _link(anon, "not-a-token")[0].status, 401)
        r, url = _link(anon, tok)
        res.ok("ссылка выдана: /plata/<id> под адресом сервера, срок жизни назван",
               r.status == 200 and url.startswith(config.BASE_URL.rstrip("/") + "/plata/")
               and json.loads(r.body).get("expires_at"), r.body[:200])
        res.check("повторный запрос программы — та же ссылка", _link(anon, tok)[1], url)
        # ⭐ Провод ПРОГРАММЫ (bot/app/core/license_renew.py, грузится по пути) против
        # ЭТОГО сервера — «Plătește acum» в 1.36.1. И её правило: браузер уходит только
        # на страницу оплаты того же адреса, что renew.url в файле, — значит оба
        # адреса сервер обязан строить от одного BASE_URL, иначе программа отвергала
        # бы каждую ссылку («Serverul DentPilot nu a răspuns») молча для сервера.
        out, data = rn.pay_link(s.url + paylink.API_PATH, tok, timeout=10, agent="DentPilot/test", extra=HDR)
        res.ok("провод программы понимает сервер: ACCEPTED и та же ссылка",
               out == rn.ACCEPTED and data.get("url") == url, repr((out, data)))
        res.check("провод программы: чужой токен — REFUSED",
                  rn.pay_link(s.url + paylink.API_PATH, "x" * 43, timeout=10), (rn.REFUSED, {}))
        res.check("страница оплаты и renew.url файла — один адрес (правило программы)",
                  urlsplit(url)[:2], urlsplit(srv_license.renew_url())[:2])
        res.ok("компьютер программы записан во флот", _sql(s, "SELECT clinic_id FROM devices WHERE id='d_0a1b2c3d4e5f'") == [(cid,)])
        path = "/plata/" + url.rsplit("/", 1)[1]
        page = anon.get(path)
        res.ok("страница: клиника, оба варианта с ценой месяца и года, выбор срока, галочка условий, перевод; "
               "без maib карты нет, IDNO не спрашивает",
               page.status == 200 and "Clinica Plată Program" in page.body
               and all(f"{views._mdl(pay.amount(m, tiers.list_price(t)))} MDL" in page.body
                       for t in tiers.TIERS for m in pay.MONTHS)
               and "DentPilot Basic" in page.body and "DentPilot Plus" in page.body
               and "name='months'" in page.body and "name='tier'" in page.body
               and "name='terms' value='1' required" in page.body and "dentpilot.md/termeni.html" in page.body
               and "Transfer bancar" in page.body and "Plătește cu cardul" not in page.body
               and "name='idno'" not in page.body and "Perioada de probă este valabilă" in page.body
               and "noindex" in page.body, page.body[-1200:])
        res.check("чужой Origin — 403", anon.post(path, months="12", method="transfer",
                                                 headers={"Origin": "http://evil.example",
                                                          "Host": f"127.0.0.1:{s.port}"}).status, 403)
        res.check("срок не из ряда — bad_months", anon.post(path, months="6", method="transfer").location,
                  f"{path}?msg=bad_months")
        res.ok("пробный — по умолчанию Plus (условия § 3)", "value='plus' checked" in page.body
               and "value='basic' checked" not in page.body)
        n0 = len(_letters(s))
        res.check("без галочки условий ни ноты, ни карты — need_terms (требование maib)",
                  anon.post(path, months="12", method="transfer").location, f"{path}?msg=need_terms")
        res.check("без галочки нота не создана", _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=?", cid)[0][0], 0)
        r = anon.post(path, months="12", method="transfer", terms="1")
        res.check("нота переводом создана", r.location, f"{path}?msg=note_created")
        p = _sql(s, "SELECT reference, amount, months, status, method FROM payments WHERE clinic_id=?", cid)
        res.ok("платёж: год по прайсу, ожидает, перевод",
               len(p) == 1 and p[0][1] == pay.amount(12, tiers.list_price(tiers.PLUS)) and p[0][2] == 12
               and p[0][3] == "pending" and p[0][4] == "transfer", repr(p))
        ref = p[0][0]
        letters = _letters(s)
        res.ok("письмо с нотой ушло клинике, с reference",
               len(letters) == n0 + 1 and letters[-1][0] == "plata@example.md" and ref in letters[-1][2])
        page = anon.get(path + "?msg=note_created")
        res.ok("страница показывает ноту: reference, вариант, IBAN, 12 luni; смена — за «Altă variantă»",
               ref in page.body and "MD00TEST" in page.body and "12 luni" in page.body
               and "<b>DentPilot Plus</b>" in page.body and "Altă variantă sau alt termen?" in page.body
               and "Nota de plată a fost creată" in page.body, page.body[-1500:])
        res.check("тот же выбор — нота та же, note_exists",
                  anon.post(path, months="12", tier="plus", method="transfer", terms="1").location,
                  f"{path}?msg=note_exists")
        res.check("платёж по-прежнему один", _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=?", cid)[0][0], 1)
        pid_db = _sql(s, "SELECT id FROM payments WHERE reference=?", ref)[0][0]
        admin.post(f"/admin/payments/{pid_db}/confirm")
        page = anon.get(path)
        res.ok("после подтверждения: абонемент действует, ноты нет, снова выбор срока",
               "Abonamentul DentPilot Plus este valabil" in page.body and ref not in page.body
               and "name='months'" in page.body,
               page.body[-1500:])
        # клиника без IDNO: абонемента без него не бывает — просим на месте
        cid2 = cid_from(admin.post("/admin/clinics", name="Fără IDNO", idno="", email="fara@example.md").location)
        admin.post(f"/admin/clinics/{cid2}/issue", kind="trial")
        url2 = _link(anon, _token(s, cid2))[1]
        path2 = "/plata/" + url2.rsplit("/", 1)[1]
        res.ok("без IDNO страница просит IDNO", "name='idno'" in anon.get(path2).body)
        res.check("без IDNO нота не создаётся — pay_need_idno",
                  anon.post(path2, months="1", method="transfer", terms="1").location, f"{path2}?msg=pay_need_idno")
        res.check("IDNO другой клиники — idno_taken",
                  anon.post(path2, months="1", method="transfer", idno="1234567890123", terms="1").location,
                  f"{path2}?msg=idno_taken")
        res.check("кривой IDNO — bad_idno", anon.post(path2, months="1", method="transfer", idno="12",
                                                     terms="1").location,
                  f"{path2}?msg=bad_idno")
        r = anon.post(path2, months="1", method="transfer", idno="7777 777 777 777", terms="1")
        res.ok("IDNO сохранён (пробелы сняты) и нота создана",
               r.location == f"{path2}?msg=note_created"
               and _sql(s, "SELECT idno FROM clinics WHERE id=?", cid2) == [("7777777777777",)], r.location)
        # ссылку открывает любой, у кого она есть: записанный IDNO отсюда не меняется (30.10)
        res.check("другой IDNO при записанном — idno_locked",
                  anon.post(path2, months="1", method="transfer", idno="7777777777778", terms="1").location,
                  f"{path2}?msg=idno_locked")
        res.ok("IDNO прежний, строки clinic_edit не прибавилось",
               _sql(s, "SELECT idno FROM clinics WHERE id=?", cid2) == [("7777777777777",)]
               and _sql(s, "SELECT count(*) FROM audit WHERE who='program' AND what='clinic_edit'")[0][0] == 1)
        res.ok("idno_locked — словами: изменить можно в кабинете клиники",
               "contul clinicii" in anon.get(f"{path2}?msg=idno_locked").body)
        res.check("тот же IDNO при записанном — как без поля: нота есть",
                  anon.post(path2, months="1", method="transfer", idno="7777777777777", terms="1").location,
                  f"{path2}?msg=note_exists")
        # срок жизни
        _sql(s, "UPDATE pay_links SET expires_at='2020-01-01T00:00:00Z' WHERE clinic_id=?", cid2)
        r = anon.get(path2)
        res.ok("просроченная ссылка — 410 словами", r.status == 410 and "a expirat" in r.body)
        res.check("неизвестная ссылка — 410", anon.get("/plata/nu-exista").status, 410)
        res.ok("просроченной ссылке и форма отказывает — 410", anon.post(path2, months="1", method="transfer").status == 410)
        r, url3 = _link(anon, _token(s, cid2))
        res.ok("после истечения программа получает новую ссылку", r.status == 200 and url3 and url3 != url2)
        whats = {w for (w,) in _sql(s, "SELECT what FROM audit")}
        res.ok("журнал: paylink_new, нота и IDNO от «program»",
               "paylink_new" in whats
               and _sql(s, "SELECT count(*) FROM audit WHERE who='program' AND what='payment_new'")[0][0] >= 1
               and _sql(s, "SELECT count(*) FROM audit WHERE who='program' AND what='clinic_edit'")[0][0] == 1)
    # карта: стенд maib
    fake = FakeMaib()
    try:
        with Server(env={**BANK_ENV, **fake.env}) as s:
            admin = Client(s.url).login()
            cid = cid_from(admin.post("/admin/clinics", name="Clinica Card", idno="2222222222222",
                                      email="card@example.md").location)
            admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
            anon = Client(s.url)
            url = _link(anon, _token(s, cid))[1]
            path = "/plata/" + url.rsplit("/", 1)[1]
            res.ok("с maib страница предлагает и карту, и перевод",
                   "Plătește cu cardul" in anon.get(path).body and "Transfer bancar" in anon.get(path).body)
            res.check("карта без галочки — need_terms", anon.post(path, months="1", method="card").location,
                      f"{path}?msg=need_terms")
            r = anon.post(path, months="1", method="card", terms="1")
            p = _sql(s, "SELECT provider_id, pay_url, method, status FROM payments WHERE clinic_id=?", cid)
            res.ok("карта: 303 прямо на страницу maib, платёж с payId, ссылкой и методом card",
                   r.status == 303 and len(p) == 1 and r.location == p[0][1] and p[0][0] in fake.pays
                   and p[0][2] == "card" and p[0][3] == "pending", f"{r.status} {r.location} {p}")
            page = anon.get(path).body
            res.ok("страница с ожидающей нотой: карта — кнопкой за галочкой (прямой ссылки maib нет), перевод виден",
                   p[0][1] not in page and "Plătește cu cardul" in page and "name='terms'" in page
                   and "MD00TEST" in page)
            r = anon.post(path, months="1", tier="plus", method="card", terms="1")
            res.ok("кнопка карты у ожидающей ноты — на ту же ссылку maib, второй платёж у maib не создан",
                   r.status == 303 and r.location == p[0][1] and len(fake.pays) == 1, f"{r.location} {fake.pays}")
    finally:
        fake.close()


def suite_hits_sweep(res: Result) -> None:
    """Лимиты в памяти (Р3, 30.10): ключ адреса, который больше не приходит, выметается,
    когда его последняя отметка старше часа; живой ключ и сам лимит в час — как были."""
    import time
    from app import login
    for mod, fn, cap in ((paylink, paylink.limited, paylink.POSTS_PER_HOUR),
                         (login, login.request_limited, login.REQUESTS_PER_HOUR)):
        name = mod.__name__.rsplit(".", 1)[1]
        saved = dict(mod._hits), list(mod._swept)
        try:
            now = time.time()
            mod._hits.clear()
            mod._hits.update({f"10.0.0.{i}": [now - 7200, now - 3700] for i in range(500)})
            mod._hits["10.9.9.9"] = [now - 4000, now - 600]           # живой: последняя отметка 10 мин назад
            mod._swept[0] = now                                          # только что выметали — ждём минуту
            fn("192.0.2.1")
            res.check(f"{name}: раньше минуты после уборки ключи не трогаются", len(mod._hits), 502)
            mod._swept[0] = now - 61
            fn("192.0.2.1")
            res.check(f"{name}: уборка — остались живой и спрашивающий", sorted(mod._hits),
                      ["10.9.9.9", "192.0.2.1"])
            res.check(f"{name}: отметки живого ключа целы", len(mod._hits["10.9.9.9"]), 2)
            mod._hits.clear()
            got = [fn("192.0.2.7") for _ in range(cap + 1)]
            res.check(f"{name}: лимит в час прежний — {cap} проходят, следующий нет",
                      got, [False] * cap + [True])
        finally:
            mod._hits.clear()
            mod._hits.update(saved[0])
            mod._swept[:] = saved[1]
