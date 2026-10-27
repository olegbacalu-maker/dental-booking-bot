"""Кабинет из программы (27.10, contlink.py): «Deschide contul clinicii» — одноразовая ссылка по
токену программы и вход в кабинет ТОЛЬКО своей клиники. План —
review/plan-cabinet-link-email-2026-10-27.md › Б; разбор — docs/dentpilot-2/cloud.md.

Что держит набор:
- ссылка: токен программы, адрес того же origin, что renew.url файла (правило программы),
  провод программы понимает сервер, в базе только хеш, каждое нажатие — новая, 20 в час;
- вход: одноразовый, 5 минут, строка журнала, кука вида «clinic», к IP не привязан;
- ⛔ сессия кнопки у филиала не видит главную: ни имени, ни списка, ни `?c=`, ни «Adaugă clinică»,
  ни общей ноты, ни имени SMS кабинета; вошедший во весь кабинет остаётся при своём входе;
- каждый маршрут /cont… разобран: новый без решения здесь — красный.
"""
import ast
import json
import re
import sys
from urllib.parse import urlsplit

from harness import CLOUD, Client, Result, Server

sys.path.insert(0, str(CLOUD))
from app import auth, contlink  # noqa: E402
from app import license as srv_license  # noqa: E402
from test_branches import (BANK_ENV, BRANCH, DIRECTOR, MAIN, _add, _approve, _enter, _register,  # noqa: E402
                           _sql, _token_of)
from test_renew import rn  # noqa: E402

HDR = {"User-Agent": "DentPilot/2.2.1", "X-DentPilot-Device": "d_00000000c0a1",
       "X-DentPilot-Channel": "stable", "X-DentPilot-OS": "Windows 11"}
ENV = {**BANK_ENV, "DP_TRIAL_MODE": "auto", "DP_SMS_OFFERED": "1", "DP_SMSMD_TOKEN": "t"}

# Каждый маршрут кабинета и что он делает с сессией кнопки программы:
#   own   — работает в пределах своей клиники (account.clinics / pick отдают одну);
#   deny  — закрыт целиком посредником (contlink.DENY → /cont?msg=cont_program_only);
#   login — вход и выход: сессии кнопки открыт, чтобы войти во весь кабинет;
#   none  — сессии кнопки не касается (регистрация: у неё клиника уже есть → /cont).
# ⛔ Новый маршрут /cont… без строки здесь — красный: реши, видит ли его вход из программы.
ROUTES = {
    ("GET", "/cont"): "own", ("GET", "/cont/login"): "login", ("POST", "/cont/login/email"): "login",
    ("POST", "/cont/login/cod"): "login", ("POST", "/cont/iesire"): "login",
    ("GET", "/cont/inregistrare"): "none", ("POST", "/cont/inregistrare"): "none",
    ("POST", "/cont/inregistrare/cod"): "none",
    ("POST", "/cont/date"): "own", ("POST", "/cont/nota"): "own", ("GET", "/cont/plati/{number}.pdf"): "own",
    ("POST", "/cont/sms/nume"): "own", ("POST", "/cont/sms/cerere.pdf"): "own", ("POST", "/cont/sms/cerere"): "own",
    ("POST", "/cont/cod"): "own",
    ("GET", "/cont/clinica-noua"): "deny", ("POST", "/cont/clinica-noua"): "deny",
    ("GET", "/cont/nota-comuna"): "deny", ("POST", "/cont/nota-comuna"): "deny",
    ("POST", "/cont/nota-comuna/anuleaza"): "deny",
    ("GET", contlink.PATH + "/{lid}"): "login",
}


def _link(c: Client, token: str):
    r = c._do(contlink.API_PATH, b"", {**HDR, "Authorization": f"Bearer {token}"})
    return r, (json.loads(r.body) if r.status == 200 else {}).get("url", "")


def _open(c: Client, url: str):
    return c.get(urlsplit(url).path)


def _kinds(c: Client) -> list:
    """Виды куки кабинета в банке клиента — по поведению сервера (секрет подписи — его, не наш):
    «account» — вход во весь кабинет (страница входа возвращает в кабинет), «clinic» — вход
    кнопкой (страница входа открыта, кабинет пускает)."""
    have = [k for k in c.jar if k.name == auth.ACCOUNT_COOKIE]
    if not have:
        return []
    if c.get("/cont/login").status == 303:
        return ["account"]
    return ["clinic"] if c.get("/cont").status == 200 else ["?"]


def _routes() -> dict:
    """(метод, путь) каждого маршрута /cont… в main.py — из декораторов, ast-ом."""
    tree = ast.parse((CLOUD / "app" / "main.py").read_text(encoding="utf-8"))
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in fn.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post")
                    and d.args):
                continue
            a = d.args[0]
            if isinstance(a, ast.Constant):
                path = a.value
            elif (isinstance(a, ast.BinOp) and isinstance(a.left, ast.Attribute) and a.left.attr == "PATH"
                  and isinstance(a.left.value, ast.Name) and a.left.value.id == "contlink"
                  and isinstance(a.right, ast.Constant)):
                path = contlink.PATH + a.right.value
            else:
                continue
            if isinstance(path, str) and (path == "/cont" or path.startswith("/cont/")):
                out[(d.func.attr.upper(), path)] = fn.name
    return out


def suite_rules(res: Result) -> None:
    """Без сервера: срок, лимит, маршруты кабинета разобраны."""
    res.ok("ссылка живёт 5 минут, 20 в час на клинику (план Б)",
           contlink.TTL.total_seconds() == 300 and contlink.PER_HOUR == 20)
    res.ok("вид куки в подписи: «clinic» не читается как учётная запись, и наоборот",
           auth._read("account", auth.clinic_cookie("c_1")) is None
           and auth._read("clinic", auth.account_cookie("a_1")) is None
           and auth._read("clinic", auth.clinic_cookie("c_1")) == "c_1")
    got = _routes()
    res.ok("исходники нашлись: маршрутов /cont… в main.py больше десятка", len(got) > 10, repr(sorted(got)))
    res.check("⛔ каждый маршрут /cont… решён для входа из программы (ROUTES) — новый без решения красный",
              sorted(k for k in got if k not in ROUTES), [])
    res.check("в ROUTES нет маршрутов, которых больше нет (список гниёт молча)",
              sorted(k for k in ROUTES if k not in got), [])
    deny = sorted({p for (_, p), how in ROUTES.items() if how == "deny"})
    res.ok("закрытые маршруты — ровно под contlink.DENY",
           all(contlink.closed(p) for p in deny)
           and all(any(p == d or p.startswith(d + "/") for p in deny) for d in contlink.DENY)
           and not contlink.closed("/cont") and not contlink.closed("/cont/nota")
           and not contlink.closed("/cont/clinica-nouaX"), repr(deny))


def suite_link(res: Result) -> None:
    """Ссылка по токену программы и одноразовый вход."""
    with Server(env=ENV) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        tok = _token_of(s, main)
        prog = Client(s.url)
        res.check("без токена — 401", prog._do(contlink.API_PATH, b"", HDR).status, 401)
        res.check("чужой токен — 401", _link(prog, "x" * 43)[0].status, 401)
        r, url = _link(prog, tok)
        res.ok("ссылка: /cont/intra/<id> под адресом сервера, срок назван",
               r.status == 200 and urlsplit(url).path.startswith(contlink.PATH + "/") and json.loads(r.body).get("expires_at"),
               r.body[:200])
        res.check("ссылка и renew.url файла — один адрес (программа принимает только его)",
                  urlsplit(url)[:2], urlsplit(srv_license.renew_url())[:2])
        lid = urlsplit(url).path.rsplit("/", 1)[1]
        res.ok("в базе ссылки открытым текстом нет — только хеш",
               not _sql(s, "SELECT 1 FROM cont_links WHERE id_hash=?", lid)
               and _sql(s, "SELECT count(*) FROM cont_links WHERE clinic_id=?", main)[0][0] == 1)
        r2, url2 = _link(prog, tok)
        res.ok("каждое нажатие — новая ссылка", r2.status == 200 and url2 != url)
        # ⭐ провод ПРОГРАММЫ (bot/app/core/license_renew.py) против этого сервера: тот же POST с
        # Bearer, что у «Plătește acum»
        out, data = rn.pay_link(s.url + contlink.API_PATH, tok, timeout=10, agent="DentPilot/test", extra=HDR)
        res.ok("провод программы понимает сервер: ACCEPTED, адрес /cont/intra/",
               out == rn.ACCEPTED and urlsplit(data.get("url", "")).path.startswith(contlink.PATH + "/"),
               repr((out, data)))
        res.check("провод программы: чужой токен — REFUSED",
                  rn.pay_link(s.url + contlink.API_PATH, "y" * 43, timeout=10), (rn.REFUSED, {}))
        res.ok("компьютер программы записан во флот",
               _sql(s, "SELECT clinic_id FROM devices WHERE id=?", HDR["X-DentPilot-Device"]) == [(main,)])

        b = Client(s.url)                                     # системный браузер: куки кабинета нет
        r = _open(b, url)
        res.ok("вход: 303 в кабинет, кука кабинета вида «clinic»",
               r.status == 303 and r.location == "/cont" and _kinds(b) == ["clinic"], f"{r.status} {r.location}")
        res.ok("ссылка погашена, адрес записан (к IP вход не привязан)",
               _sql(s, "SELECT used_at IS NOT NULL, used_ip FROM cont_links WHERE clinic_id=? AND used_at IS NOT NULL",
                    main) == [(1, "127.0.0.1")])
        res.ok("журнал клиники: «вход в кабинет из программы»",
               _sql(s, "SELECT who, what FROM audit WHERE clinic_id=? AND what='cont_program'", main)
               == [("program", "cont_program")])
        home = b.get("/cont")
        res.ok("кабинет открыт: своя клиника, пометка «из программы»",
               home.status == 200 and MAIN["name"] in home.body and "Ați intrat din" in home.body,
               home.body[-1200:])
        again = _open(Client(s.url), url)
        res.ok("⛔ второе открытие той же ссылки — 410 словами, без куки",
               again.status == 410 and "Linkul de intrare a expirat" in again.body)
        _sql(s, "UPDATE cont_links SET expires_at='2000-01-01T00:00:00Z' WHERE used_at IS NULL")
        late = Client(s.url)
        res.ok("⛔ истекшая (5 минут) — 410, без куки", _open(late, url2).status == 410 and _kinds(late) == [])
        res.check("выдуманная — 410", Client(s.url).get(contlink.PATH + "/nope").status, 410)
        # лимит: 20 в час на клинику (уже выдано 3)
        codes = [_link(prog, tok)[0].status for _ in range(contlink.PER_HOUR)]
        res.ok("21-я ссылка за час — 429", codes.count(200) == contlink.PER_HOUR - 3 and codes[-3:] == [429] * 3,
               repr(codes))
        # Олег скрыл клинику — ссылки нет, и вошедшая кнопкой сессия перестаёт пускать
        Client(s.url).login().post(f"/admin/clinics/{main}/decline")
        res.check("скрытая клиника: ссылки нет (токен погашен)", _link(prog, tok)[0].status, 401)
        res.check("скрытая клиника: сессия кнопки — на вход", b.get("/cont").location, "/cont/login")


def suite_scope(res: Result) -> None:
    """⛔ Сессия кнопки филиала — только филиал (план Б, решение 27.10)."""
    with Server(env=ENV) as s:
        c = _enter(s, DIRECTOR)
        main = _register(s, c)
        _add(c, main)
        bid = _sql(s, "SELECT id FROM clinics WHERE name=?", BRANCH["name"])[0][0]
        _approve(s, bid)
        c.post(f"/cont/sms/nume?c={main}", name="Zambet")          # имя SMS кабинета — у главной
        prog = Client(s.url)
        _, url = _link(prog, _token_of(s, bid))
        b = Client(s.url)
        _open(b, url)
        home = b.get("/cont")
        res.ok("кабинет кнопки филиала: филиал, «вы видите только эту клинику»",
               home.status == 200 and BRANCH["name"] in home.body and "Vedeți doar această clinică" in home.body,
               home.body[-1500:])
        res.ok("⛔ главной не видно: ни имени, ни списка «Clinicile mele», ни «Adaugă clinică», ни ссылки на неё",
               MAIN["name"] not in home.body and "Clinicile mele" not in home.body and main not in home.body
               and "clinica-noua" not in home.body and "nota-comuna" not in home.body, home.body[-2500:])
        res.ok("⛔ имя SMS кабинета (у главной) филиалу по кнопке не открыто",
               "Numele expeditorului" not in home.body)
        res.ok("код компьютера филиала — из кабинета (7 цифр), текст без имени главной",
               "action='/cont/cod'" in home.body and "Codul de 6 cifre din e-mail leagă" in home.body)
        res.check("⛔ ?c=главная — назад на свою", b.get(f"/cont?c={main}").location, "/cont")
        res.check("⛔ форма с ?c=главная не пишет в неё",
                  b.post(f"/cont/date?c={main}", name="Hack", idno="", contact_name="", phone="",
                         address="").location, "/cont?msg=pick_clinic")
        res.check("главная не переименована", _sql(s, "SELECT name FROM clinics WHERE id=?", main)[0][0], MAIN["name"])
        deny = f"/cont?msg={contlink.DENIED_MSG}"
        got = {p: (b.get(p) if m == "GET" else b.post(p, name="X")).location
               for (m, p), how in ROUTES.items() if how == "deny"}
        res.ok("⛔ «Adaugă clinică» и общая нота закрыты целиком — словами «только эта клиника»",
               set(got.values()) == {deny}, repr(got))
        r = b.get("/cont/clinica-noua")
        res.ok("отказ посредника тоже несёт noindex (NoIndex — снаружи)",
               r.headers.get("x-robots-tag", "").startswith("noindex"), repr(r.headers))
        res.check("клиник в кабинете по-прежнему две",
                  _sql(s, "SELECT count(*) FROM clinics WHERE idno=?", MAIN["idno"])[0][0], 2)
        res.ok("слово отказа на странице", "doar această clinică" in b.get(deny).body)
        res.check("⛔ заявка на имя SMS из кнопки филиала — не его (имя у главной)",
                  b.post("/cont/sms/nume", name="Altul").location, "/cont?msg=sms_not_offered")
        res.check("имя главной не тронуто",
                  _sql(s, "SELECT sender FROM sms_accounts WHERE clinic_id=?", main), [("Zambet",)])
        r = b.post("/cont/date", name="Zambet Botanica 2", idno=MAIN["idno"], contact_name="Ion", phone="1",
                   address="bd. Dacia 27")
        res.check("реквизиты своей клиники по кнопке — меняются", r.location, "/cont?msg=saved")
        res.ok("в журнале — «кто»: ящик клиники с пометкой «din program»",
               _sql(s, "SELECT who FROM audit WHERE clinic_id=? AND what='clinic_edit' ORDER BY id DESC LIMIT 1", bid)
               == [(f"{BRANCH['email']} · din program",)])
        res.ok("e-mail клиники в кабинете не правится (по нему вход) — поля нет",
               "name='email'" not in b.get("/cont").body)
        res.check("код компьютера своей клиники — выдаётся", b.post("/cont/cod").status, 200)
        # страница входа открыта сессии кнопки: войти во весь кабинет
        res.check("/cont/login сессии кнопки — страница входа, не возврат", b.get("/cont/login").status, 200)
        res.check("выход гасит куку", (b.post("/cont/iesire").location, _kinds(b)),
                  ("/cont/login?msg=logged_out", []))
        # вошедший во весь кабинет нажал кнопку в программе филиала — остаётся при своём входе
        _, url = _link(prog, _token_of(s, bid))
        r = _open(c, url)
        res.ok("вход во весь кабинет не подменяется кнопкой: 303 на филиал, кука «account»",
               r.location == f"/cont?c={bid}" and _kinds(c) == ["account"] and
               "Clinicile mele" in c.get(r.location).body, f"{r.location} {_kinds(c)}")
        res.ok("ссылка всё равно погашена", _sql(s, "SELECT count(*) FROM cont_links WHERE used_at IS NULL")[0][0] == 0)
