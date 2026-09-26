"""Автообновление файла (L13): суточный запрос к renew.url, замена только по seq выше.

Провод — core/license_renew.py, решение — core/license.py. Сервер лицензий
здесь подменён СТЕНДОМ в процессе теста (http.server на loopback — правило
renew.url это допускает), потому что нужны ответы, которых настоящий сервер
не даёт: файл старее принятого, битая подпись, 401, тишина, редирект. Что
настоящий сервер и этот клиент понимают друг друга — cloud/tests/test_renew.py:
там клиент грузится по пути и ходит в живой сервер.

Главное из cloud.md, живым сервером: сервер недоступен — программа стартует
и живёт как раньше; старый seq — файл не заменён.

⭐ Пары, на которых стенд был красным при разработке: без сравнения seq
файл seq 4 ложился поверх seq 6; без проверки подписи стенд подсовывал
битый файл; с запросом на цикле событий /health ждал ответа стенда.
"""
import ast
import http.server
import importlib.util
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

from harness import BOT, ROOT, Client, Result, Server, _rmtree_settled

FIX = ROOT / "tests" / "fixtures" / "license"
KEY_ENV = {"DENTART_LICENSE_KEYS": str(FIX / "test-key.json")}
MODULE = BOT / "app" / "core" / "license_renew.py"
ALLOWED_IMPORTS = {"__future__", "http.client", "json", "urllib.error", "urllib.request"}
TS = "%Y-%m-%dT%H:%M:%SZ"
TOKEN = "stand-token-" + "x" * 32


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rn = _load("license_renew", MODULE)
rv = _load("rsa_verify", BOT / "app" / "core" / "rsa_verify.py")
gen = _load("license_fixtures", ROOT / "scripts" / "license_fixtures.py")


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                    # клиент отвалился по таймауту — так и задумано


class Stand:
    """Стенд сервера лицензий: отвечает тем, что положили в `reply`, помнит запросы."""

    def __init__(self):
        self.reply = {"status": 204, "body": "", "delay": 0.0}
        self.requests: list[dict] = []
        self.post_replies: dict[str, dict] = {}          # путь → ответ: /v1/trial, /v1/verify (26.09)
        self.posts: list[dict] = []
        stand = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                stand.requests.append({"path": self.path,
                                       "auth": self.headers.get("Authorization", ""),
                                       "agent": self.headers.get("User-Agent", "")})
                r = dict(stand.reply)
                if r["delay"]:
                    time.sleep(r["delay"])
                body = r["body"].encode("utf-8")
                self.send_response(r["status"])
                if r["status"] in (301, 302):
                    self.send_header("Location", stand.base + "/trap")
                self.send_header("Content-Type", "application/json")
                if r["status"] != 204:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if r["status"] != 204:
                    self.wfile.write(body)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    sent = json.loads(raw.decode("utf-8"))
                except ValueError:
                    sent = None
                stand.posts.append({"path": self.path, "json": sent,
                                    "type": self.headers.get("Content-Type", "")})
                r = stand.post_replies.get(self.path, {"status": 404, "body": ""})
                body = r["body"].encode("utf-8")
                self.send_response(r["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.url = self.base + "/v1/license"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def serve(self, status: int, body: str = "", delay: float = 0.0) -> None:
        self.reply = {"status": status, "body": body, "delay": delay}

    def answer(self, status: int, data: dict | None = None, path: str = "/v1/trial") -> None:
        """Ответ на POST: заявка на пробный (/v1/trial) или код из письма (/v1/verify)."""
        self.post_replies[path] = {"status": status, "body": json.dumps(data) if data is not None else ""}

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def _file(seq: int, renew: dict | None, *, expired: bool = False) -> str:
    """Файл с подписью тестового ключа: действует ещё 400 дней или уже в readonly."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    d = timedelta(days=1)
    claim = dict(gen.CLAIMS["valid"], seq=seq, issued_at=(now - 40 * d).strftime(TS),
                 valid_until=((now - 20 * d) if expired else (now + 400 * d)).strftime(TS),
                 grace_until=((now - 6 * d) if expired else (now + 414 * d)).strftime(TS))
    if renew is not None:
        claim["renew"] = renew
    payload = gen.claim_bytes(claim)
    return gen.envelope(payload, gen.sign(payload, gen.load_key()))


def _sig(text: str) -> str:
    return json.loads(text)["sig"]


def _tampered(text: str) -> str:
    env = json.loads(text)
    env["sig"] = env["sig"][:-1] + ("A" if env["sig"][-1] != "A" else "B")
    return json.dumps(env)


def _api(c: Client) -> dict:
    r = c.get("/api/license")
    return json.loads(r.body).get("data", {}) if r.status == 200 else {"status": r.status}


def _renew(a: dict) -> dict:
    """Поле renew ответа; None (файла с renew на диске нет) — как пустое, чтобы
    набор краснел проверкой, а не падал на None."""
    return a.get("renew") or {}


def _wait_renew(c: Client, timeout: float = 20.0) -> dict:
    """Дождаться первой попытки автообновления этого процесса."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        a = _api(c)
        if _renew(a).get("at"):
            return a
        time.sleep(0.2)
    return _api(c)


def _events(d: pathlib.Path) -> list[str]:
    con = sqlite3.connect(d / "dental.db")
    try:
        return [r[0] for r in con.execute("SELECT text FROM activity WHERE kind = 'license'")]
    finally:
        con.close()


def _mem(d: pathlib.Path) -> dict:
    return json.loads((d / "license.state").read_text(encoding="utf-8"))


def _log(s: Server) -> str:
    return s._log_path.read_text(encoding="utf-8", errors="replace")


# ---------- провод ----------


def suite_client(res: Result) -> None:
    """license_renew.fetch: исход по коду ответа, заголовки, без редиректов, таймаут."""
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    res.check("модуль чистый: импорты только из разрешённого списка", sorted(imported - ALLOWED_IMPORTS), [])
    res.ok("нет относительных импортов проекта",
           not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree)))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    res.ok("ни open, ни __file__, ни environ", not ({"open", "__file__"} & names or "environ" in attrs))
    res.ok("подписи модуль не проверяет — это license.py", "open_envelope" not in names | attrs)
    res.check("адрес с seq", rn.request_url("https://x/v1/license", 7), "https://x/v1/license?seq=7")
    res.check("адрес с seq при своём query", rn.request_url("https://x/l?a=1", 2), "https://x/l?a=1&seq=2")

    stand = Stand()
    try:
        body = _file(5, {"url": stand.url, "token": TOKEN})
        stand.serve(200, body)
        res.check("200 — NEWER и текст файла", rn.fetch(stand.url, TOKEN, 4, timeout=5), (rn.NEWER, body))
        req = stand.requests[-1]
        res.check("запрос: путь с seq", req["path"], "/v1/license?seq=4")
        res.check("запрос: Authorization Bearer", req["auth"], f"Bearer {TOKEN}")
        res.ok("запрос: User-Agent тот, что передан", rn.fetch(stand.url, TOKEN, 4, timeout=5, agent="DentPilot/9.9")
               and stand.requests[-1]["agent"] == "DentPilot/9.9", stand.requests[-1]["agent"])
        stand.serve(204)
        res.check("204 — SAME", rn.fetch(stand.url, TOKEN, 5, timeout=5), (rn.SAME, ""))
        stand.serve(401, '{"ok": false}')
        res.check("401 — REFUSED", rn.fetch(stand.url, TOKEN, 5, timeout=5), (rn.REFUSED, ""))
        stand.serve(403, "")
        res.check("403 — REFUSED", rn.fetch(stand.url, TOKEN, 5, timeout=5), (rn.REFUSED, ""))
        stand.serve(500, "oops")
        res.check("500 — OFFLINE", rn.fetch(stand.url, TOKEN, 5, timeout=5), (rn.OFFLINE, ""))
        stand.serve(404, "")
        res.check("404 — OFFLINE", rn.fetch(stand.url, TOKEN, 5, timeout=5), (rn.OFFLINE, ""))
        stand.serve(302, "")
        n = len(stand.requests)
        res.check("редирект — OFFLINE", rn.fetch(stand.url, TOKEN, 5, timeout=5), (rn.OFFLINE, ""))
        res.ok("за редиректом клиент не идёт: токен не уезжает на чужой адрес",
               len(stand.requests) == n + 1 and not any(r["path"].endswith("/trap") for r in stand.requests))
        stand.serve(200, "x" * (rn.MAX_BODY + 10))
        res.check("тело больше потолка — OFFLINE", rn.fetch(stand.url, TOKEN, 5, timeout=5), (rn.OFFLINE, ""))
        stand.serve(200, body, delay=3.0)
        t0 = time.time()
        got = rn.fetch(stand.url, TOKEN, 4, timeout=1.0)
        res.ok("таймаут — OFFLINE, и раньше, чем ответил бы сервер",
               got == (rn.OFFLINE, "") and time.time() - t0 < 2.5, f"{got} за {time.time() - t0:.1f} с")
    finally:
        stand.close()
    res.check("порт закрыт — OFFLINE", rn.fetch(stand.url, TOKEN, 4, timeout=5), (rn.OFFLINE, ""))
    res.check("адрес не разбирается — OFFLINE", rn.fetch("https://[::/", TOKEN, 4, timeout=5), (rn.OFFLINE, ""))


# ---------- живой сервер ----------


def suite_live(res: Result) -> None:
    """Файл с renew на диске, стенд отвечает по-разному; каждый старт — один запрос."""
    stand = Stand()
    renew = {"url": stand.url, "token": TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_renew_"))
    try:
        (d / "license.json").write_text(_file(5, renew), encoding="utf-8")

        # 1. стенд держит новый файл (seq 6) три секунды: старт не ждёт, потом замена
        newer = _file(6, renew)
        stand.serve(200, newer, delay=3.0)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            t0 = time.time()
            a = _api(c)
            res.ok("старт не ждёт сервер лицензий: /api/license отвечает по старому файлу, "
                   "пока стенд молчит",
                   a.get("state") == "active" and a.get("seq") == 5 and _renew(a).get("at") is None
                   and time.time() - t0 < 2.5, repr(a))
            a = _wait_renew(c)
            res.ok("стенд ответил новым файлом: принят, seq 6, без перезапуска",
                   _renew(a).get("outcome") == "renewed" and a.get("seq") == 6
                   and a.get("state") == "active", repr(a))
            res.check("файл на диске — тот, что прислал стенд", _sig((d / "license.json").read_text(encoding="utf-8")),
                      _sig(newer))
            res.check("память: принят seq 6", _mem(d).get("accepted_seq"), 6)
            req = stand.requests[-1]
            res.ok("запрос программы: seq принятого, Bearer из файла, DentPilot в User-Agent",
                   req["path"] == "/v1/license?seq=5" and req["auth"] == f"Bearer {TOKEN}"
                   and req["agent"].startswith("DentPilot/"), repr(req))
            res.ok("лог: renew=renewed", "license: renew=renewed seq=6 had=5" in _log(s), _log(s)[-400:])
            page = c.get("/admin/license").body
            res.ok("страница лицензии: строка автообновления, последняя проверка, кнопка директору",
                   "verifică zilnic" in page and "ultima verificare" in page and "fișier nou primit" in page
                   and "action='/admin/license/renew'" in page, page[-1500:])
        res.ok("летопись клиники: «reînnoită automat … (fișier 6)»",
               any("reînnoită automat" in t and "(fișier 6)" in t for t in _events(d)), repr(_events(d)))
        n = len(stand.requests)

        # 2. стенд прислал файл СТАРЕЕ принятого: диск не тронут
        older = _file(4, renew)
        stand.serve(200, older)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _wait_renew(c)
            res.ok("старый seq — same, файл не заменён",
                   _renew(a).get("outcome") == "same" and a.get("seq") == 6, repr(a))
            res.check("на диске по-прежнему seq 6", _sig((d / "license.json").read_text(encoding="utf-8")), _sig(newer))
            res.ok("лог: «новее нет» — рутина, не предупреждение", "license: renew=" not in _log(s), _log(s)[-400:])
        res.check("каждый старт — ровно один запрос", len(stand.requests), n + 1)

        # 3. тот же seq — тоже не замена (иначе летопись писала бы «активирована» на пустом месте)
        stand.serve(200, newer)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            res.check("тот же seq — same", _renew(_wait_renew(c)).get("outcome"), "same")
        res.check("летопись не пополнилась", len([t for t in _events(d) if "reînnoită" in t]), 1)

        # 4. файл с битой подписью: bad, диск не тронут
        stand.serve(200, _tampered(_file(7, renew)))
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _wait_renew(c)
            res.ok("битая подпись — bad, seq прежний", _renew(a).get("outcome") == "bad"
                   and a.get("seq") == 6, repr(a))
            res.check("на диске seq 6", _sig((d / "license.json").read_text(encoding="utf-8")), _sig(newer))

        # 5. 204, 401, 500 — три исхода, ни один не трогает состояние
        for status, want in ((204, "same"), (401, "refused"), (500, "offline")):
            stand.serve(status, "")
            with Server(dir_=d, env=KEY_ENV) as s:
                c = Client(s.url).login()
                a = _wait_renew(c)
                res.ok(f"стенд {status} — {want}, состояние прежнее",
                       _renew(a).get("outcome") == want and a.get("seq") == 6
                       and a.get("state") == "active", repr(a))

        # 6. сервера нет вовсе: программа стартует и живёт как раньше
        stand.close()
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _wait_renew(c)
            res.ok("порт закрыт — offline, active по файлу с диска",
                   _renew(a).get("outcome") == "offline" and a.get("state") == "active"
                   and a.get("seq") == 6, repr(a))
            res.check("журнал открывается", c.get("/admin").status, 200)
            r = c.post_json("/api/patients", {"name": "Offline Test", "phone": "069000777"})
            res.check("запись работает", r.status, 200)
            res.ok("лог: renew=offline, без трейсбека", "license: renew=offline" in _log(s)
                   and "Traceback" not in _log(s), _log(s)[-400:])
            res.ok("страница лицензии называет исход словами", "serverul nu a răspuns" in c.get("/admin/license").body)
    finally:
        _rmtree_settled(d)

    # 7. файл без renew: спрашивать некого — ни запроса, ни строки на странице
    stand2 = Stand()
    d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_renew2_"))
    try:
        shutil.copy(FIX / "valid.json", d2 / "license.json")
        with Server(dir_=d2, env=KEY_ENV) as s:
            c = Client(s.url).login()
            time.sleep(1.0)
            a = _api(c)
            res.ok("без renew в файле: /api/license отдаёт renew: null", a.get("renew", "?") is None, repr(a))
            res.ok("страница без строки автообновления", "verifică zilnic" not in c.get("/admin/license").body)
            res.ok("лог без renew", "license: renew=" not in _log(s))
        res.check("стенд запросов не видел", stand2.requests, [])
    finally:
        stand2.close()
        _rmtree_settled(d2)


def suite_button(res: Result) -> None:
    """Кнопка «Verifică acum»: тот же запрос сейчас; в readonly проходит ворота; только директору."""
    stand = Stand()
    renew = {"url": stand.url, "token": TOKEN}
    d = pathlib.Path(tempfile.mkdtemp(prefix="dp_renew3_"))
    try:
        # просроченный файл с renew на диске: readonly; стенд пока молчит (204)
        (d / "license.json").write_text(_file(8, renew, expired=True), encoding="utf-8")
        stand.serve(204)
        with Server(dir_=d, env=KEY_ENV) as s:
            c = Client(s.url).login()
            a = _wait_renew(c)
            res.ok("просроченный файл: readonly, стенд без нового — same",
                   a.get("state") == "readonly" and _renew(a).get("outcome") == "same", repr(a))
            r = c.post_json("/api/patients", {"name": "Ro Test", "phone": "069000888"})
            res.check("запись отказывает", r.status, 423)
            r = c.post("/admin/license/renew")
            res.ok("кнопка в readonly проходит ворота: 303 на страницу с исходом same",
                   r.status == 303 and r.location == "/admin/license?msg=license_renew_same", repr(r))
            res.ok("страница показывает исход словами",
                   "Nu există un fișier de licență mai nou" in c.get("/admin/license?msg=license_renew_same").body)
            fresh = _file(9, renew)
            stand.serve(200, fresh)
            r = c.post("/admin/license/renew")
            res.ok("стенд выдал новый файл: 303 в журнал с license_renewed",
                   r.status == 303 and r.location == "/admin?msg=license_renewed", repr(r))
            a = _api(c)
            res.ok("после кнопки: active, seq 9, без перезапуска",
                   a.get("state") == "active" and a.get("seq") == 9, repr(a))
            r = c.post_json("/api/patients", {"name": "Ok Test", "phone": "069000999"})
            res.check("запись снова работает", r.status, 200)
            res.ok("журнал показывает баннер", "reînnoit de pe serverul DentPilot" in c.get("/admin?msg=license_renewed").body)
            r = c.post("/admin/license/renew")
            res.check("второй раз: same", r.location, "/admin/license?msg=license_renew_same")
            stand.serve(200, _tampered(_file(10, renew)))
            r = c.post("/admin/license/renew")
            res.check("битый файл со стенда: license_renew_bad", r.location, "/admin/license?msg=license_renew_bad")
            stand.serve(401)
            r = c.post("/admin/license/renew")
            res.check("токен не признан: license_renew_refused", r.location, "/admin/license?msg=license_renew_refused")
            res.check("seq не сдвинулся", _api(c).get("seq"), 9)
            stand.close()
            r = c.post("/admin/license/renew")
            res.check("сервера нет: license_renew_offline", r.location, "/admin/license?msg=license_renew_offline")
            # не директор: право то же, что у импорта
            c.post("/admin/users/save", uid="ana", name="Ana R", role="receptie", pin="3333")
            ana = Client(s.url)
            ana.post("/admin/login", password="3333", next="/admin")
            r = ana.post("/admin/license/renew")
            res.ok("регистратуре кнопка закрыта: no_access", r.status == 303 and r.msg == "no_access", repr(r))
            res.ok("регистратура видит строку, но не кнопку",
                   "verifică zilnic" in ana.get("/admin/license").body
                   and "action='/admin/license/renew'" not in ana.get("/admin/license").body)
    finally:
        _rmtree_settled(d)

    # файл без renew: кнопке нечего спрашивать — код none, не 500 и не отказ ворот
    d2 = pathlib.Path(tempfile.mkdtemp(prefix="dp_renew4_"))
    try:
        shutil.copy(FIX / "expired.json", d2 / "license.json")
        with Server(dir_=d2, env=KEY_ENV) as s:
            c = Client(s.url).login()
            r = c.post("/admin/license/renew")
            res.check("без renew в файле: license_renew_none", r.location, "/admin/license?msg=license_renew_none")
    finally:
        _rmtree_settled(d2)


# ---------- активация без файла: заявка на пробный (26.09) ----------


def _actors(d: pathlib.Path) -> list[tuple[str, str]]:
    con = sqlite3.connect(d / "dental.db")
    try:
        return [(r[0], r[1]) for r in con.execute("SELECT text, actor FROM activity WHERE kind = 'license'")]
    finally:
        con.close()


def _until(cond, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


def suite_request(res: Result) -> None:
    """Заявка со страницы активации: токен в license.pending, файл сам, без кнопки.

    Стенд сервера — тот же, что у автообновления; ждать минуту незачем:
    DENTART_LICENSE_PENDING_S=1 — цикл спрашивает раз в секунду."""
    stand = Stand()
    dirs = [pathlib.Path(tempfile.mkdtemp(prefix=f"dp_req{i}_")) for i in range(3)]
    env = dict(KEY_ENV, DENTART_LICENSE_SERVER=stand.base, DENTART_LICENSE_PENDING_S="1")
    ok = {"ok": True, "state": "requested", "url": stand.url, "token": TOKEN}
    form = dict(name="Clinica Cerere", idno="", contact_name="Ana", email="cerere@example.md", phone="")
    try:
        d = dirs[0]
        with Server(dir_=d, env=env) as s:
            c = Client(s.url)
            c.login()
            page = c.get("/admin/license").body
            res.ok("стена: главный путь — заявка (поля, условия и политика), файл — запасной",
                   "action='/admin/license/request'" in page and "name='email'" in page
                   and "privacy.html" in page and "Aveți deja fișierul de licență" in page
                   and 'name="file"' in page, page[-2500:])
            r = c.post("/admin/license/request", **form)
            res.ok("без галочки: license_terms, на сервер ничего не ушло",
                   r.status == 303 and r.location == "/admin/license?msg=license_terms" and not stand.posts,
                   f"{r.status} {r.location!r} {len(stand.posts)}")

            stand.answer(400, {"ok": False, "code": "bad_email",
                               "text": "Indicați o adresă de e-mail valabilă."})
            r = c.post("/admin/license/request", **dict(form, email="nu-e"), terms="1")
            res.check("отказ сервера: license_request_refused", r.location,
                      "/admin/license?msg=license_request_refused")
            sent = stand.posts[-1] if stand.posts else {}
            res.ok("заявка ушла JSON-ом на /v1/trial, с согласием",
                   sent.get("path") == "/v1/trial" and "application/json" in sent.get("type", "")
                   and (sent.get("json") or {}).get("consent") == "1"
                   and (sent.get("json") or {}).get("name") == "Clinica Cerere", repr(sent))
            page = c.get("/admin/license?msg=license_request_refused").body
            res.ok("страница: слова сервера и вписанные поля на месте",
                   "Indicați o adresă de e-mail valabilă." in page and "value='Clinica Cerere'" in page)
            res.ok("после отказа ожидания нет", not (d / "license.pending").exists())

            stand.answer(500)
            r = c.post("/admin/license/request", **form, terms="1")
            res.check("сервер не ответил как надо: license_request_offline", r.location,
                      "/admin/license?msg=license_request_offline")

            stand.answer(200, ok)
            stand.serve(204)
            asked = len(stand.requests)
            r = c.post("/admin/license/request", **form, terms="1")
            res.check("принято, файл ещё не выдан: license_requested", r.location,
                      "/admin/license?msg=license_requested")
            pend = json.loads((d / "license.pending").read_text(encoding="utf-8")) \
                if (d / "license.pending").exists() else {}
            res.ok("license.pending: токен и адрес сервера, кто принял условия и какую версию",
                   pend.get("token") == TOKEN and pend.get("url") == stand.url
                   and pend.get("actor") == "Director" and pend.get("terms") == "26.09.2026", repr(pend))
            res.ok("первый запрос по токену заявки — сразу",
                   any(q["auth"] == f"Bearer {TOKEN}" for q in stand.requests[asked:]))
            page = c.get("/admin/license").body
            res.ok("ожидание: что отправлено, самообновление страницы, кнопка проверки",
                   "Cererea de perioadă de probă a fost trimisă" in page and "Clinica Cerere" in page
                   and "http-equiv='refresh'" in page and "cererea a fost aprobată" in page, page[-2000:])
            res.check("стена держится, пока файла нет", c.get("/admin").location, "/admin/license")
            res.ok("цикл спрашивает часто, пока заявка ждёт",
                   _until(lambda: len(stand.requests) >= asked + 3, 10), str(len(stand.requests) - asked))

            stand.serve(200, _file(1, {"url": stand.url, "token": TOKEN}))
            res.ok("сервер выдал файл — программа забрала его сама, без кнопки",
                   _until(lambda: (d / "license.json").exists() and not (d / "license.pending").exists()))
            res.check("состояние active", _api(c).get("state"), "active")
            res.check("стены нет", c.get("/admin").status, 200)
            ev = _actors(d)
            res.ok("летопись: заявка отправлена и активация — с версией условий и именем директора",
                   any("Cerere de perioadă de probă trimisă" in t and a == "Director" for t, a in ev)
                   and any("Licența a fost activată" in t and "acceptați Termenii și condițiile din 26.09.2026"
                           in t and a == "Director" for t, a in ev), repr(ev))

        d = dirs[1]
        with Server(dir_=d, env=env) as s:
            c = Client(s.url)
            c.login()
            stand.answer(200, dict(ok, state="issued"))
            stand.serve(200, _file(1, {"url": stand.url, "token": TOKEN}))
            r = c.post("/admin/license/request", **form, terms="1")
            res.check("auto: файл выдан сразу — активация в том же запросе", r.location, "/admin?msg=license_ok")
            res.ok("auto: license.json на месте, заявки нет",
                   (d / "license.json").exists() and not (d / "license.pending").exists())

        d = dirs[2]
        with Server(dir_=d, env=env) as s:
            c = Client(s.url)
            c.login()
            stand.answer(200, ok)
            stand.serve(204)
            c.post("/admin/license/request", **form, terms="1")
            stand.serve(401, '{"ok": false, "code": "token_unknown"}')
            res.ok("заявку скрыли в админке (401): ожидание снято само",
                   _until(lambda: not (d / "license.pending").exists()))
            page = c.get("/admin/license").body
            res.ok("страница: заявка больше не активна — и снова форма заявки",
                   "nu mai este activă" in page and "action='/admin/license/request'" in page, page[-1500:])
            res.ok("файла нет, стена на месте", not (d / "license.json").exists()
                   and c.get("/admin").location == "/admin/license")
    finally:
        stand.close()
        for d in dirs:
            _rmtree_settled(d)


def suite_code(res: Result) -> None:
    """Новый компьютер клиники, которая уже есть у DentPilot: повтор заявки → код на
    e-mail клиники → код на странице → токен клиники → её файл, без файла из письма."""
    stand = Stand()
    dirs = [pathlib.Path(tempfile.mkdtemp(prefix=f"dp_code{i}_")) for i in range(2)]
    env = dict(KEY_ENV, DENTART_LICENSE_SERVER=stand.base, DENTART_LICENSE_PENDING_S="1")
    vid = "V" * 24
    form = dict(name="Clinica Veche", idno="1003600012345", contact_name="Ana",
                email="veche@example.md", phone="", terms="1")
    try:
        d = dirs[0]
        with Server(dir_=d, env=env) as s:
            c = Client(s.url)
            c.login()
            res.ok("форма заявки подсказывает путь второго компьютера",
                   "trimitem un cod de activare" in c.get("/admin/license").body)
            stand.answer(409, {"ok": False, "code": "duplicate", "verify_id": vid,
                               "text": "Clinica este deja înregistrată la DentPilot. Am trimis un cod "
                                       "de activare pe adresa de e-mail a clinicii."})
            r = c.post("/admin/license/request", **form)
            res.check("повтор с verify_id: license_request_code", r.location,
                      "/admin/license?msg=license_request_code")
            page = c.get("/admin/license?msg=license_request_code").body
            res.ok("страница: слова сервера, поле кода; заявка — под «Nu a venit codul», файл — запасной",
                   "Am trimis un cod" in page and "action='/admin/license/verify'" in page
                   and "name='code'" in page and "autocomplete='one-time-code'" in page
                   and "Nu a venit codul" in page and "Aveți deja fișierul de licență" in page, page[-3000:])
            res.ok("ожидания нет: токена у программы ещё нет", not (d / "license.pending").exists())

            stand.answer(400, {"ok": False, "code": "bad_code",
                               "text": "Codul nu este corect sau a expirat."}, path="/v1/verify")
            r = c.post("/admin/license/verify", code=" 123 456 ")
            res.check("неверный код: license_code_bad", r.location, "/admin/license?msg=license_code_bad")
            sent = stand.posts[-1] if stand.posts else {}
            res.ok("код ушёл JSON-ом на /v1/verify: verify_id заявки, цифры без пробелов",
                   sent.get("path") == "/v1/verify" and sent.get("json") == {"verify_id": vid, "code": "123456"},
                   repr(sent))
            page = c.get("/admin/license?msg=license_code_bad").body
            res.ok("страница: слова сервера, поле кода на месте",
                   "Codul nu este corect sau a expirat." in page and "name='code'" in page, page[-2000:])

            stand.answer(200, {"ok": True, "url": stand.url, "token": TOKEN}, path="/v1/verify")
            stand.serve(200, _file(3, {"url": stand.url, "token": TOKEN}))
            r = c.post("/admin/license/verify", code="654321")
            res.check("верный код: файл клиники — активация в том же запросе", r.location, "/admin?msg=license_ok")
            res.ok("license.json на месте, заявки нет",
                   (d / "license.json").exists() and not (d / "license.pending").exists())
            res.check("состояние active", _api(c).get("state"), "active")
            res.ok("по токену клиники, с seq 0: новый компьютер получает последний файл",
                   any(q["auth"] == f"Bearer {TOKEN}" and "seq=0" in q["path"] for q in stand.requests))
            ev = _actors(d)
            res.ok("летопись: активация кодом и принятие условий — директором",
                   any("codul trimis pe e-mailul clinicii" in t and a == "Director" for t, a in ev)
                   and any("Licența a fost activată" in t and "acceptați Termenii și condițiile din 26.09.2026"
                           in t and a == "Director" for t, a in ev), repr(ev))

        d = dirs[1]
        with Server(dir_=d, env=env) as s:
            c = Client(s.url)
            c.login()
            posted = len(stand.posts)
            r = c.post("/admin/license/verify", code="654321")
            res.ok("код без заявки в этом запуске: license_code_bad, на сервер ничего",
                   r.location == "/admin/license?msg=license_code_bad" and len(stand.posts) == posted,
                   f"{r.location!r} {len(stand.posts) - posted}")
            page = c.get("/admin/license?msg=license_code_bad").body
            res.ok("страница: «trimiteți din nou cererea» и снова форма заявки",
                   "trimiteți din nou cererea" in page and "action='/admin/license/request'" in page, page[-2000:])
    finally:
        stand.close()
        for d in dirs:
            _rmtree_settled(d)

