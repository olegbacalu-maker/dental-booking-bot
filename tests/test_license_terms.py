"""Акт акцепта условий (29.10, план § 3.2 A/C): половина программы к /v1/terms/accept, полю `terms`
заявки и кода, заголовку X-DentPilot-Terms и квитанции в папке contract.

Провод — core/license_renew.py (`terms_accept`, `terms_version`, `fetch(meta=…)`), решение —
core/license.py (`accept_terms`, `receipts`, `terms_due`, досылка в `renew_once`), баннер — сигнал
`license` оболочки (layout._terms_banner), блок страницы лицензии (layout._terms_block), действия —
POST /admin/license/terms и /api/license/terms. Сервер подменён стендом из test_license_renew: нужны
ответы по заказу (квитанция, заголовок, тишина). Что настоящий сервер понимает этот провод —
cloud/tests/test_terms.py.

⭐ Что держит набор: версия и имя уходят с заявкой; квитанция ложится в contract\\ ВНЕ базы и с id
сервера, когда он ответил; импорт файла без сервера — квитанция без id, досылается первым удачным
запросом файла; старая клиника без квитанций — баннер директору, «Accept» пишет квитанцию и шлёт акт;
слово сервера (заголовок) снимает баннер без квитанции на этом ПК; в режиме чтения баннера нет;
квитанции едут в зашифрованный экспорт.
"""
import json
import pathlib
import shutil
import tempfile

from harness import Client, Result, Server, _rmtree_settled, shell_signal
from test_backup import PW, _export
from test_license_renew import (FIX, KEY_ENV, TOKEN, Stand, _actors, _api, _file, _terms, _until,
                                _wait_renew, rn)

ACCEPT = "/v1/terms/accept"
RECEIPT_OK = {"ok": True, "id": "a_0123456789abcdef", "version": "", "at": "2026-10-29T10:00:00Z"}


def _receipt(d: pathlib.Path, version: str) -> dict:
    p = d / "contract" / f"acceptare-{version}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _terms_api(c: Client) -> dict:
    return _api(c).get("terms") or {}


def _posts(stand: Stand, path: str) -> list:
    return [p for p in stand.posts if p["path"] == path]


def suite_wire(res: Result) -> None:
    """`rn.terms_accept` и заголовок X-DentPilot-Terms в `rn.fetch(meta=…)`."""
    stand = Stand()
    try:
        url = stand.base + ACCEPT
        stand.answer(200, dict(RECEIPT_OK, version=_terms()), path=ACCEPT)
        out, data = rn.terms_accept(url, TOKEN, {"terms": _terms(), "actor": "Ana"}, timeout=5,
                                    agent="DentPilot/test", extra={"X-DentPilot-Device": "d_0a1b2c3d4e5f"})
        res.ok("200 с ok: ACCEPTED и квитанция", out == rn.ACCEPTED and data.get("id") == RECEIPT_OK["id"], repr((out, data)))
        sent = stand.posts[-1]
        res.ok("POST JSON {terms, actor} с Bearer файла и личностью машины",
               sent["path"] == ACCEPT and sent["auth"] == f"Bearer {TOKEN}"
               and sent["json"] == {"terms": _terms(), "actor": "Ana"} and sent["device"] == "d_0a1b2c3d4e5f", repr(sent))
        stand.answer(400, {"ok": False, "code": "bad_terms", "text": "Versiunea termenilor lipsește"}, path=ACCEPT)
        res.check("400 с текстом: REJECTED", rn.terms_accept(url, TOKEN, {"terms": "x"}, timeout=5)[0], rn.REJECTED)
        stand.answer(401, {"ok": False, "code": "token_unknown"}, path=ACCEPT)
        res.check("401: REFUSED", rn.terms_accept(url, TOKEN, {}, timeout=5), (rn.REFUSED, {}))
        stand.serve(204)
        stand.get_headers = {"X-DentPilot-Terms": "27.10.2026"}
        meta: dict = {}
        rn.fetch(stand.url, TOKEN, 1, timeout=5, meta=meta)
        res.check("204 с заголовком: meta.terms — версия", meta.get("terms"), "27.10.2026")
        stand.get_headers = {"X-DentPilot-Terms": "<b>x</b>"}
        meta = {}
        rn.fetch(stand.url, TOKEN, 1, timeout=5, meta=meta)
        res.check("мусор в заголовке — нет ключа", "terms" in meta, False)
        stand.get_headers = {}
        res.check("terms_version: только дата", [rn.terms_version({"X-DentPilot-Terms": x}) for x in
                                                 ("01.11.2026", "1.11.2026", "2026-11-01", "")],
                  ["01.11.2026", "", "", ""])
    finally:
        stand.close()


def suite_receipts(res: Result) -> None:
    """Заявка с версией и именем → квитанция с id сервера; импорт файла → квитанция без id, досылка."""
    stand = Stand()
    v = _terms()
    dirs = [pathlib.Path(tempfile.mkdtemp(prefix=f"dp_terms{i}_")) for i in range(2)]
    env = dict(KEY_ENV, DENTART_LICENSE_SERVER=stand.base, DENTART_LICENSE_PENDING_S="1")
    form = dict(name="Clinica Acte", idno="", contact_name="Ana", email="acte@example.md", phone="")
    try:
        d = dirs[0]
        with Server(dir_=d, env=env) as s:
            c = Client(s.url).login()
            stand.answer(200, {"ok": True, "state": "issued", "url": stand.url, "token": TOKEN,
                               "terms": {"id": "a_trial000000001", "version": v, "at": "2026-10-29T09:00:00Z"}})
            stand.serve(200, _file(1, {"url": stand.url, "token": TOKEN}))
            r = c.post("/admin/license/request", **form, terms="1")
            res.check("заявка принята, файл сразу", r.location, "/admin?msg=license_ok")
            sent = _posts(stand, "/v1/trial")[-1]["json"]
            res.ok("заявка несёт версию условий и имя директора (старые поля на месте)",
                   sent.get("terms") == v and sent.get("actor") == "Director" and sent.get("consent") == "1"
                   and sent.get("name") == "Clinica Acte", repr(sent))
            rec = _receipt(d, v)
            res.ok("квитанция в contract\\: версия, кто, клиника, адрес условий, ответ сервера (id, at)",
                   rec.get("terms") == v and rec.get("actor") == "Director" and rec.get("clinic") == "Clinica Acte"
                   and rec.get("url", "").endswith("/termeni.html") and rec.get("at")
                   and (rec.get("server") or {}).get("id") == "a_trial000000001", repr(rec))
            res.ok("квитанция — вне базы: файл в папке данных, не строка dental.db",
                   (d / "contract" / f"acceptare-{v}.json").is_file())
            t = _terms_api(c)
            res.ok("/api/license.terms: версия принята, ничего не просит, квитанция с id",
                   t == {"version": v, "accepted": v, "due": False, "receipt": True, "receipt_id": "a_trial000000001"}, repr(t))
            res.ok("баннера «s-au actualizat» нет", "s-au actualizat" not in shell_signal(c.get("/admin").body, "license")["html"])
            page = c.get("/admin/license").body
            res.ok("страница лицензии: версия принята, акт у DentPilot",
                   f"versiunea din <b>{v}</b> este acceptată · actul este la DentPilot" in page, page[-2500:])
            res.ok("досылать нечего: /v1/terms/accept не звали", not _posts(stand, ACCEPT))
            # зашифрованный экспорт несёт квитанцию файлом
            import pyzipper
            arc = _export(c, d.parent / f"{d.name}-export.zip")
            with pyzipper.AESZipFile(arc) as z:
                names = z.namelist()
            arc.unlink()
            res.ok("экспорт: contract/acceptare-<версия>.json внутри архива", f"contract/acceptare-{v}.json" in names, repr(names))

        # импорт файла (запасной путь без интернета): квитанция без сервера → досылка при первом удачном запросе
        d = dirs[1]
        stand.posts.clear()
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            stand.serve(204)
            r = c.post("/admin/license", text=_file(1, {"url": stand.url, "token": TOKEN}), terms="1")
            res.check("файл принят", r.location, "/admin?msg=license_ok")
            rec = _receipt(d, v)
            res.ok("квитанция без сервера: server null, версия и кто", rec.get("terms") == v and rec.get("server") is None
                   and rec.get("actor") == "Director", repr(rec))
            t = _terms_api(c)
            res.ok("/api/license.terms: принята локально, не просит, id нет",
                   t.get("accepted") == v and t.get("due") is False and t.get("receipt") is True and t.get("receipt_id") is None, repr(t))
            stand.answer(200, dict(RECEIPT_OK, id="a_late0000000001", version=v), path=ACCEPT)
            r = c.post("/admin/license/renew")
            res.check("«Verifică acum»: новее нет", r.location, "/admin/license?msg=license_renew_same")
            res.ok("удачный запрос файла дослал квитанцию: POST /v1/terms/accept с Bearer файла, версией и именем",
                   _until(lambda: any(p["auth"] == f"Bearer {TOKEN}" and (p["json"] or {}).get("terms") == v
                                      and (p["json"] or {}).get("actor") == "Director" for p in _posts(stand, ACCEPT)), 10),
                   repr(stand.posts[-3:]))
            res.ok("ответ сервера лёг в квитанцию",
                   _until(lambda: (_receipt(d, v).get("server") or {}).get("id") == "a_late0000000001", 10), repr(_receipt(d, v)))
            n = len(_posts(stand, ACCEPT))
            c.post("/admin/license/renew")
            res.check("второй раз не досылает", len(_posts(stand, ACCEPT)), n)
    finally:
        stand.close()
        for d in dirs:
            _rmtree_settled(d)


def suite_banner(res: Result) -> None:
    """Старая клиника без квитанций: баннер директору, «Accept» → квитанция и акт; слово сервера снимает
    баннер; в режиме чтения баннера нет."""
    stand = Stand()
    v = _terms()
    renew = {"url": stand.url, "token": TOKEN}
    dirs = [pathlib.Path(tempfile.mkdtemp(prefix=f"dp_tbanner{i}_")) for i in range(3)]
    try:
        d = dirs[0]
        (d / "license.json").write_text(_file(3, renew), encoding="utf-8")
        stand.serve(204)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            _wait_renew(c)
            sig = shell_signal(c.get("/admin").body, "license")
            res.ok("без квитанций и слова сервера — баннер warn с версией, ссылкой на текст, галочкой и «Accept»",
                   sig["shown"] and "s-au actualizat" in sig["html"] and v in sig["html"] and "banner warn" in sig["html"]
                   and "termeni.html" in sig["html"] and "action='/admin/license/terms'" in sig["html"]
                   and "name='terms'" in sig["html"] and ">Accept<" in sig["html"], sig["html"][-900:])
            t = _terms_api(c)
            res.ok("/api/license.terms: due, принятой нет", t.get("due") is True and t.get("accepted") is None, repr(t))
            res.ok("запись работает: баннер — не замок", c.post_json("/api/patients", {}).status != 423)
            page = c.get("/admin/license").body
            res.ok("страница лицензии: блок с галочкой и «Accept» назад на страницу",
                   "Termenii și condițiile s-au actualizat" in page and "name='back' value='license'" in page
                   and "Programul funcționează și fără acceptare" in page, page[-2500:])
            r = c.post("/admin/license/terms", back="license")
            res.check("без галочки — license_terms", r.msg, "license_terms")
            res.ok("квитанции нет", not _receipt(d, v))
            stand.answer(200, dict(RECEIPT_OK, id="a_accept00000001", version=v), path=ACCEPT)
            r = c.post("/admin/license/terms", terms="1", back="license")
            res.ok("«Accept» со страницы: license_terms_ok и назад на страницу лицензии",
                   r.msg == "license_terms_ok" and r.location.startswith("/admin/license?"), repr(r))
            rec = _receipt(d, v)
            res.ok("квитанция записана и акт ушёл серверу сразу (сервер файла знаком)",
                   rec.get("terms") == v and rec.get("actor") == "Director"
                   and (rec.get("server") or {}).get("id") == "a_accept00000001", repr(rec))
            sent = _posts(stand, ACCEPT)[-1]
            res.ok("POST /v1/terms/accept: Bearer файла, версия, имя", sent["auth"] == f"Bearer {TOKEN}"
                   and sent["json"] == {"terms": v, "actor": "Director"}, repr(sent))
            res.ok("баннер снят", not shell_signal(c.get("/admin").body, "license")["shown"])
            ev = _actors(d)
            res.ok("летопись: строка о принятии с версией и именем",
                   any("Acceptați Termenii și condițiile DentPilot din " + v in t_ and a == "Director" for t_, a in ev), repr(ev))
            page = c.get("/admin/license").body
            res.ok("страница: версия принята, акт у DentPilot", f"versiunea din <b>{v}</b> este acceptată · actul" in page)
            # JSON «Accept» — тот же путь
            r = c.post_json("/api/license/terms", {})
            res.check("/api/license/terms без accept — 422 license_terms", (r.status, r.msg), (422, "license_terms"))
            r = c.post_json("/api/license/terms", {"accept": True})
            body = json.loads(r.body)
            res.ok("/api/license/terms accept — ok, terms в ответе", r.status == 200 and body.get("code") == "license_terms_ok"
                   and body.get("data", {}).get("due") is False, r.body[:300])
            res.check("/api/license/terms без входа — 401", Client(s.url).post_json("/api/license/terms", {"accept": True}).status, 401)
            res.ok("повтор от того же сервера: квитанция с id не затёрта", (_receipt(d, v).get("server") or {}).get("id") == "a_accept00000001")

        # слово сервера: клиника приняла с другого ПК — баннера нет и без квитанции здесь
        d = dirs[1]
        (d / "license.json").write_text(_file(3, renew), encoding="utf-8")
        stand.get_headers = {"X-DentPilot-Terms": v}
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            _wait_renew(c)
            t = _terms_api(c)
            res.ok("заголовок = версия программы: принято, не просит, квитанции на этом ПК нет",
                   t.get("accepted") == v and t.get("due") is False and t.get("receipt") is False, repr(t))
            res.ok("баннера нет", not shell_signal(c.get("/admin").body, "license")["shown"])
            res.ok("страница: принята (без «actul» — квитанции с id здесь нет)",
                   f"versiunea din <b>{v}</b> este acceptată." in c.get("/admin/license").body)
        stand.get_headers = {"X-DentPilot-Terms": "01.01.2020"}
        (d / "license.state").unlink(missing_ok=True)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            _wait_renew(c)
            t = _terms_api(c)
            res.ok("заголовок старее версии программы — просит, принятая названа",
                   t.get("accepted") == "01.01.2020" and t.get("due") is True, repr(t))
            res.ok("баннер называет принятую версию", "versiunea acceptată de clinică: 01.01.2020" in
                   shell_signal(c.get("/admin").body, "license")["html"])
        stand.get_headers = {}

        # режим чтения: баннера условий нет (ворота не пропустили бы ответ)
        d = dirs[2]
        shutil.copy(FIX / "expired.json", d / "license.json")
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            sig = shell_signal(c.get("/admin").body, "license")["html"]
            res.ok("readonly: баннер лицензии есть, баннера условий нет", "regim de citire" in sig and "s-au actualizat" not in sig)
            res.check("/api/license.terms: не просит", _terms_api(c).get("due"), False)
    finally:
        stand.close()
        for d in dirs:
            _rmtree_settled(d)
