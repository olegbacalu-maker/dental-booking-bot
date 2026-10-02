"""Оплата из программы (02.10): ссылка по токену программы, публичная страница
оплаты, нота переводом, карта через стенд maib, IDNO на месте, срок жизни ссылки.
cloud.md › «Оплата из программы».
"""
import json
import sys

from harness import Client, Result, Server, cid_from

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from app import config, paylink  # noqa: E402
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
        res.ok("страница: клиника, цены, срок, выбор месяца/года, перевод; без maib карты нет, IDNO не спрашивает",
               page.status == 200 and "Clinica Plată Program" in page.body
               and f"{pay.amount(12, config.PRICE_MONTH)} MDL" in page.body and "name='months'" in page.body
               and "Transfer bancar" in page.body and "Plătește cu cardul" not in page.body
               and "name='idno'" not in page.body and "Perioada de probă este valabilă" in page.body
               and "noindex" in page.body, page.body[-1200:])
        res.check("чужой Origin — 403", anon.post(path, months="12", method="transfer",
                                                 headers={"Origin": "http://evil.example",
                                                          "Host": f"127.0.0.1:{s.port}"}).status, 403)
        res.check("срок не из ряда — bad_months", anon.post(path, months="6", method="transfer").location,
                  f"{path}?msg=bad_months")
        n0 = len(_letters(s))
        r = anon.post(path, months="12", method="transfer")
        res.check("нота переводом создана", r.location, f"{path}?msg=note_created")
        p = _sql(s, "SELECT reference, amount, months, status, method FROM payments WHERE clinic_id=?", cid)
        res.ok("платёж: год по прайсу, ожидает, перевод",
               len(p) == 1 and p[0][1] == pay.amount(12, config.PRICE_MONTH) and p[0][2] == 12
               and p[0][3] == "pending" and p[0][4] == "transfer", repr(p))
        ref = p[0][0]
        letters = _letters(s)
        res.ok("письмо с нотой ушло клинике, с reference",
               len(letters) == n0 + 1 and letters[-1][0] == "plata@example.md" and ref in letters[-1][2])
        page = anon.get(path + "?msg=note_created")
        res.ok("страница показывает ноту: reference, IBAN, 12 luni; выбора срока больше нет",
               ref in page.body and "MD00TEST" in page.body and "12 luni" in page.body
               and "name='months'" not in page.body and "Nota de plată a fost creată" in page.body, page.body[-1500:])
        res.check("вторая нота не плодится — note_exists", anon.post(path, months="1", method="transfer").location,
                  f"{path}?msg=note_exists")
        res.check("платёж по-прежнему один", _sql(s, "SELECT count(*) FROM payments WHERE clinic_id=?", cid)[0][0], 1)
        pid_db = _sql(s, "SELECT id FROM payments WHERE reference=?", ref)[0][0]
        admin.post(f"/admin/payments/{pid_db}/confirm")
        page = anon.get(path)
        res.ok("после подтверждения: абонемент действует, ноты нет, снова выбор срока",
               "Abonamentul este valabil" in page.body and ref not in page.body and "name='months'" in page.body,
               page.body[-1500:])
        # клиника без IDNO: абонемента без него не бывает — просим на месте
        cid2 = cid_from(admin.post("/admin/clinics", name="Fără IDNO", idno="", email="fara@example.md").location)
        admin.post(f"/admin/clinics/{cid2}/issue", kind="trial")
        url2 = _link(anon, _token(s, cid2))[1]
        path2 = "/plata/" + url2.rsplit("/", 1)[1]
        res.ok("без IDNO страница просит IDNO", "name='idno'" in anon.get(path2).body)
        res.check("без IDNO нота не создаётся — pay_need_idno",
                  anon.post(path2, months="1", method="transfer").location, f"{path2}?msg=pay_need_idno")
        res.check("IDNO другой клиники — idno_taken",
                  anon.post(path2, months="1", method="transfer", idno="1234567890123").location,
                  f"{path2}?msg=idno_taken")
        res.check("кривой IDNO — bad_idno", anon.post(path2, months="1", method="transfer", idno="12").location,
                  f"{path2}?msg=bad_idno")
        r = anon.post(path2, months="1", method="transfer", idno="7777 777 777 777")
        res.ok("IDNO сохранён (пробелы сняты) и нота создана",
               r.location == f"{path2}?msg=note_created"
               and _sql(s, "SELECT idno FROM clinics WHERE id=?", cid2) == [("7777777777777",)], r.location)
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
            r = anon.post(path, months="1", method="card")
            p = _sql(s, "SELECT provider_id, pay_url, method, status FROM payments WHERE clinic_id=?", cid)
            res.ok("карта: 303 прямо на страницу maib, платёж с payId, ссылкой и методом card",
                   r.status == 303 and len(p) == 1 and r.location == p[0][1] and p[0][0] in fake.pays
                   and p[0][2] == "card" and p[0][3] == "pending", f"{r.status} {r.location} {p}")
            res.ok("страница с ожидающей нотой ведёт на ту же ссылку maib и показывает перевод",
                   p[0][1] in anon.get(path).body and "MD00TEST" in anon.get(path).body)
    finally:
        fake.close()
