"""Кабинет клиники (шаг 3, 01.10): вход через Google, регистрация, лицензия, нота, скачивание.

Google здесь — СТЕНД в процессе теста (http.server): отдаёт код на /auth и
id_token на /token теми же полями, что настоящий OpenID Connect Google (iss,
aud, sub, email, email_verified, name, nonce, exp). Прод знает одни адреса —
DP_GOOGLE_AUTH_URL/TOKEN_URL меняют только тесты. GitHub — тоже стенд:
/releases/latest с ассетами последнего выпуска.

Главное из cloud.md › «Кабинет клиники»: пароля у нас нет; клиника с тем же
подтверждённым ящиком — это она (привязка сразу); регистрация = та же заявка
на пробный, что /proba; повтор по IDNO объявляется и уходит Олегу; файл из
кабинета — байт в байт тот, что выдала админка; отвязанная запись перестаёт
пускать сразу; /descarca никогда не мёртвая.
"""
import base64
import email
import email.policy
import http.server
import json
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from harness import CLOUD, FIX, ROOT, Client, Result, Server, cid_from, load_by_path

sys.path.insert(0, str(CLOUD))
from app import account, auth, config, license, mail, trial  # noqa: E402
from app import payments as pay  # noqa: E402

rv = load_by_path("rsa_verify", ROOT / "bot" / "app" / "core" / "rsa_verify.py")
KEY = json.loads((FIX / "test-key.json").read_text(encoding="utf-8"))
KEYS = {"test": (int(KEY["n"], 16), int(KEY["e"]))}
CLIENT_ID, CLIENT_SECRET = "123-test.apps.googleusercontent.com", "GOCSPX-test-secret"
CALLBACK = "https://cloud.dentpilot.md/auth/google/callback"
BANK_ENV = {"DP_BANK_BENEFICIARY": "Oleg Bacalu", "DP_BANK_IBAN": "MD00TEST0000000000000001",
            "DP_BANK_NAME": "Banca Test", "DP_BANK_CODE": "1234567890123"}
ASSET_URL = "https://github.com/olegbacalu-maker/dental-booking-bot/releases/download/v1.35.3/DentPilot-Setup-1.35.3.zip"
DIRECTOR = dict(sub="g-director-1", email="director@clinica-test.md", name="Ana Director", email_verified=True)
CLINIC = dict(name="Clinica Cont", idno="1234567890123", contact_name="Ana", phone="069111222", consent="1")


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode("utf-8")).decode("ascii").rstrip("=")


def _jwt(claims: dict) -> str:
    """JWT без настоящей подписи: сервер её не проверяет (почему — account.py)."""
    return f"{_b64({'alg': 'RS256', 'kid': 'k1', 'typ': 'JWT'})}.{_b64(claims)}.{_b64({'sig': 'stand'})}"


class FakeGoogle:
    """Стенд Google: /auth выдаёт код и ведёт на redirect_uri, /token меняет код на id_token."""

    def __init__(self):
        self.identity = dict(DIRECTOR)
        self.override: dict = {}          # что подменить в claim'ах id_token
        self.down = False                 # /token отвечает 500
        self.codes: dict[str, tuple[dict, str, str]] = {}
        self.auths: list[dict] = []
        self.tokens: list[dict] = []
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _json(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path != "/auth":
                    return self._json(404, {})
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                fake.auths.append(q)
                code = "code-" + secrets.token_hex(6)
                fake.codes[code] = (dict(fake.identity), q.get("nonce", ""), q.get("redirect_uri", ""))
                self.send_response(302)
                self.send_header("Location", f"{q.get('redirect_uri')}?" + urllib.parse.urlencode(
                    {"code": code, "state": q.get("state", "")}))
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8")).items()}
                if self.path != "/token":
                    return self._json(404, {})
                fake.tokens.append(form)
                if fake.down:
                    return self._json(500, {"error": "server_error"})
                known = fake.codes.pop(form.get("code", ""), None)
                if (known is None or form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET
                        or form.get("grant_type") != "authorization_code" or form.get("redirect_uri") != known[2]):
                    return self._json(400, {"error": "invalid_grant"})
                ident, nonce, _ = known
                now = int(time.time())
                claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "iat": now, "exp": now + 3600,
                          "nonce": nonce, **ident, **fake.override}
                self._json(200, {"access_token": "ya29.stand", "token_type": "Bearer", "expires_in": 3599,
                                 "scope": "openid email profile", "id_token": _jwt(claims)})

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def env(self) -> dict:
        return {"DP_GOOGLE_CLIENT_ID": CLIENT_ID, "DP_GOOGLE_CLIENT_SECRET": CLIENT_SECRET,
                "DP_GOOGLE_AUTH_URL": self.url + "/auth", "DP_GOOGLE_TOKEN_URL": self.url + "/token"}

    def visit(self, url: str) -> str:
        """Как браузер: открыть адрес Google и вернуть, куда он отправил (Location)."""
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(url, timeout=10) as r:
                return r.headers.get("Location", "")
        except urllib.error.HTTPError as e:
            return e.headers.get("Location", "")


class FakeGitHub:
    """Стенд API GitHub: последний выпуск с ассетами; режимы ok / nozip / down."""

    def __init__(self):
        self.mode = "ok"
        self.calls = 0
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                fake.calls += 1
                if fake.mode == "down":
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                assets = [{"name": "DentPilot.exe", "browser_download_url": ASSET_URL.replace(
                    "DentPilot-Setup-1.35.3.zip", "DentPilot.exe")}]
                if fake.mode == "ok":
                    assets.append({"name": "DentPilot-Setup-1.35.3.zip", "browser_download_url": ASSET_URL})
                data = json.dumps({"tag_name": "v1.35.3", "assets": assets}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/releases/latest"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def env(self) -> dict:
        return {"DP_RELEASES_API": self.url}


def _sql(s: Server, sql: str, *args):
    con = sqlite3.connect(s.dir / "cloud.db")
    try:
        rows = con.execute(sql, args).fetchall()
        con.commit()                     # UPDATE из теста без commit откатился бы при close
        return rows
    finally:
        con.close()


def _jar_cookie(c: Client, name: str):
    """Кука из банки клиента: заголовков Set-Cookie в ответе несколько, а словарь
    harness.Reply.headers хранит последний — смотреть надо в банку."""
    return next((k for k in c.jar if k.name == name), None)


def _letters(s: Server) -> list[tuple[str, str, str, bool]]:
    out = []
    for f in sorted(s.outbox.glob("*.eml")):
        m = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        out.append((m["To"], m["Subject"], m.get_body(preferencelist=("plain",)).get_content(),
                    any(p.get_filename() == "license.json" for p in m.walk())))
    return out


def _google_login(c: Client, s: Server, fake: FakeGoogle):
    """Весь вход: /auth/google → стенд Google → callback сервера. Возвращает ответ callback."""
    start = c.get("/auth/google")
    assert start.status == 302, f"/auth/google: {start.status}"
    loc = fake.visit(start.location)
    assert loc.startswith(CALLBACK + "?"), loc
    return c.get("/auth/google/callback?" + urllib.parse.urlsplit(loc).query)


def _accounts(s: Server):
    return _sql(s, "SELECT id, subject, email, name, clinic_id FROM accounts ORDER BY created_at")


def _acc_clinic(s: Server, email: str):
    """clinic_id записи по ящику: created_at с точностью до секунды, порядок двух
    записей одной секунды не определён — искать по ящику, не по индексу."""
    rows = _sql(s, "SELECT clinic_id FROM accounts WHERE email=?", email)
    return rows[0][0] if rows else "нет записи"


def suite_login(res: Result) -> None:
    """Вход: без настройки — словами; с настройкой — state, nonce, кука, отказы токена, выход."""
    with Server() as s:
        anon = Client(s.url)
        r = anon.get("/cont/login")
        res.ok("без DP_GOOGLE_*: страница входа говорит, что кабинет закрыт, без куки",
               r.status == 200 and "nu este configurată" in r.body and "set-cookie" not in r.headers
               and "/auth/google" not in r.body, r.body[-400:])
        res.check("без настройки /auth/google — 503", anon.get("/auth/google").status, 503)
        res.check("без настройки callback — 503", anon.get("/auth/google/callback?code=x&state=y").status, 503)
    g = FakeGoogle()
    with Server(env=g.env) as s:
        anon = Client(s.url)
        r = anon.get("/cont")
        res.ok("без входа /cont ведёт на страницу входа", r.status == 303 and r.location == "/cont/login")
        page = anon.get("/cont/login")
        res.ok("страница входа: кнопка Google, по-румынски, без куки, noindex",
               page.status == 200 and "Continuați cu Google" in page.body and "href='/auth/google'" in page.body
               and "set-cookie" not in page.headers and "noindex" in page.body
               and mail.zile(license.TRIAL_DAYS) in page.body, page.body[:300])
        start = anon.get("/auth/google")
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(start.location).query).items()}
        res.ok("/auth/google: 302 к Google с client_id, redirect_uri, scope, state, nonce, select_account",
               start.status == 302 and start.location.startswith(g.url + "/auth?")
               and q.get("client_id") == CLIENT_ID and q.get("redirect_uri") == CALLBACK
               and q.get("response_type") == "code" and q.get("scope") == "openid email profile"
               and len(q.get("state", "")) >= 20 and len(q.get("nonce", "")) >= 20
               and q.get("prompt") == "select_account", repr(q))
        ck = start.headers.get("set-cookie", "")
        res.ok("кука входа dp_oauth: HttpOnly, SameSite=Lax, только на /auth/google, 10 минут",
               "dp_oauth=" in ck and "httponly" in ck.lower() and "samesite=lax" in ck.lower()
               and "path=/auth/google" in ck.lower() and f"max-age={auth.OAUTH_TTL}" in ck.lower(), ck)
        # чужой state — не наш вход
        r = anon.get(f"/auth/google/callback?code=code-x&state=not-the-state")
        res.ok("callback с чужим state: обратно на вход, google_expired, без куки кабинета",
               r.status == 303 and r.location == f"/cont/login?msg={account.EXPIRED}"
               and "dp_cont" not in r.headers.get("set-cookie", ""), f"{r.status} {r.location}")
        res.ok("страница входа объясняет отказ словами",
               "a expirat" in anon.get(f"/cont/login?msg={account.EXPIRED}").body)
        res.ok("отказ пользователя у Google (error=access_denied) — словами",
               anon.get("/auth/google/callback?error=access_denied").location == f"/cont/login?msg={account.DENIED}")
        # callback вовсе без куки (другой браузер)
        bare = Client(s.url)
        r = bare.get("/auth/google/callback?code=code-x&state=whatever")
        res.check("callback без куки входа — google_expired", r.location, f"/cont/login?msg={account.EXPIRED}")
        # честный вход
        r = _google_login(anon, s, g)
        ck = _jar_cookie(anon, "dp_cont")
        res.ok("вход: клиники нет → на регистрацию; кука dp_cont HttpOnly на неделю; кука входа снята",
               r.status == 303 and r.location == "/cont/inregistrare" and ck is not None
               and "HttpOnly" in ck._rest and ck.path == "/"
               and auth.ACCOUNT_TTL - 120 < (ck.expires or 0) - time.time() <= auth.ACCOUNT_TTL
               and _jar_cookie(anon, "dp_oauth") is None,
               f"{r.status} {r.location} {ck and (ck._rest, ck.path, ck.expires)} {[k.name for k in anon.jar]}")
        rows = _accounts(s)
        res.ok("учётная запись заведена: sub, e-mail и имя от Google, клиники нет",
               len(rows) == 1 and rows[0][1] == DIRECTOR["sub"] and rows[0][2] == DIRECTOR["email"]
               and rows[0][3] == DIRECTOR["name"] and rows[0][4] is None, repr(rows))
        aid = rows[0][0]
        res.ok("стенд Google получил код, client_secret и тот же redirect_uri",
               len(g.tokens) == 1 and g.tokens[0]["client_secret"] == CLIENT_SECRET
               and g.tokens[0]["redirect_uri"] == CALLBACK, repr(g.tokens))
        res.ok("/cont без клиники ведёт на регистрацию", anon.get("/cont").location == "/cont/inregistrare")
        res.ok("страница входа при живой сессии ведёт в кабинет", anon.get("/cont/login").location == "/cont")
        res.check("журнал: account_new и account_login",
                  [r[0] for r in _sql(s, "SELECT what FROM audit WHERE what LIKE 'account_%' ORDER BY id")],
                  ["account_new", "account_login"])
        r = anon.post("/cont/iesire")
        res.ok("выход: кука снята, /cont снова на вход",
               r.status == 303 and r.location == "/cont/login?msg=logged_out"
               and 'dp_cont=""' in r.headers.get("set-cookie", "") and anon.get("/cont").status == 303, repr(r.headers))
        res.ok("выход с чужим Origin — 403",
               anon.post("/cont/iesire", headers={"Origin": "http://evil.example", "Host": f"127.0.0.1:{s.port}"}).status == 403)
        r = _google_login(anon, s, g)
        res.ok("второй вход тем же аккаунтом — та же запись, не вторая",
               r.status == 303 and len(_accounts(s)) == 1 and _accounts(s)[0][0] == aid)
        anon.post("/cont/iesire")
        # отказы по claim'ам id_token — каждый словами и без записи
        for label, over, want in (("aud чужого приложения", {"aud": "other-app"}, account.FAILED),
                                  ("токен просрочен", {"exp": int(time.time()) - 5}, account.FAILED),
                                  ("nonce не наш", {"nonce": "stale"}, account.FAILED),
                                  ("iss не Google", {"iss": "https://evil.example"}, account.FAILED),
                                  ("ящик не подтверждён", {"email_verified": False}, account.UNVERIFIED),
                                  ("без sub", {"sub": ""}, account.FAILED)):
            g.override = over
            g.identity = dict(DIRECTOR, sub="g-other-" + label[:3], email="other@example.md")
            r = _google_login(Client(s.url), s, g)
            res.ok(f"{label}: отказ словами, без куки и без записи",
                   r.location == f"/cont/login?msg={want}" and "dp_cont=" not in r.headers.get("set-cookie", "")
                   and len(_accounts(s)) == 1, f"{r.location}")
        g.override = {}
        g.down = True
        r = _google_login(Client(s.url), s, g)
        res.ok("Google не ответил на обмен кода — google_failed", r.location == f"/cont/login?msg={account.FAILED}")
        g.down = False
        res.ok("страница входа объясняет и этот отказ",
               "nu a confirmat" in anon.get(f"/cont/login?msg={account.FAILED}").body)
        # кука другого вида не пускает: подпись считается с видом
        forged = Client(s.url)
        forged.jar.set_cookie(_cookie(s, "dp_cont", auth.session_cookie("oleg")))
        res.ok("кука админа в поле кабинета не пускает", forged.get("/cont").location == "/cont/login")
        forged.jar.set_cookie(_cookie(s, "dp_admin", auth.account_cookie(aid)))
        res.ok("кука кабинета в поле админа не пускает", forged.get("/admin").location == "/admin/login")
        res.ok("лог сервера без секрета Google", CLIENT_SECRET not in s.log())


def _cookie(s: Server, name: str, value: str):
    import http.cookiejar
    return http.cookiejar.Cookie(0, name, value, None, False, "127.0.0.1", False, False, "/", True, False,
                                 None, False, None, None, {})


def suite_cabinet(res: Result) -> None:
    """Регистрация из кабинета (auto): файл, письма, страница, файл байт в байт, реквизиты,
    нота на абонемент, продление, кабинет в админке, отвязка, вход по ящику."""
    g, gh = FakeGoogle(), FakeGitHub()
    with Server(env={**g.env, **gh.env, **BANK_ENV, "DP_TRIAL_MODE": "auto",
                     "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        c = Client(s.url)
        _google_login(c, s, g)
        page = c.get("/cont/inregistrare")
        res.ok("регистрация: форма с полями, ящик Google показан и не редактируется, имя подставлено",
               page.status == 200 and all(f"name='{n}'" in page.body for n in ("name", "idno", "contact_name", "phone", "consent"))
               and "name='email'" not in page.body and DIRECTOR["email"] in page.body
               and f"value='{DIRECTOR['name']}'" in page.body and "termeni.html" in page.body, page.body[-900:])
        r = c.post("/cont/inregistrare", **dict(CLINIC, consent=""))
        res.ok("без согласия — 400, форма с ошибкой, клиники нет",
               r.status == 400 and "acordul" in r.body and not _sql(s, "SELECT 1 FROM clinics"), f"{r.status}")
        r = c.post("/cont/inregistrare", **dict(CLINIC, name="A"))
        res.ok("название из одной буквы — 400", r.status == 400 and "Denumirea" in r.body)
        r = c.post("/cont/inregistrare", **CLINIC)
        res.ok("заявка принята: в кабинет с «файл отправлен»",
               r.status == 303 and r.location == "/cont?msg=registered_issued", f"{r.status} {r.location}")
        rows = _sql(s, "SELECT id, name, idno, email, origin, consent_at, contact_name FROM clinics")
        res.ok("клиника заведена из кабинета: ящик Google, origin cont, согласие записано",
               len(rows) == 1 and rows[0][3] == DIRECTOR["email"] and rows[0][4] == "cont" and rows[0][5]
               and rows[0][1] == "Clinica Cont" and rows[0][6] == "Ana", repr(rows))
        cid = rows[0][0]
        res.check("учётная запись привязана", _accounts(s)[0][4], cid)
        res.check("пробный файл выдан с основанием кабинета",
                  _sql(s, "SELECT seq, reason FROM issues WHERE clinic_id=?", cid), [(1, trial.REASON["cont"])])
        by_to = {t: (sub, body, att) for t, sub, body, att in _letters(s)}
        res.ok("письма: клинике файл, Олегу уведомление «из кабинета»",
               by_to[DIRECTOR["email"]][2] and "из кабинета" in by_to["oleg@example.md"][1]
               and "ждут в кабинете" in by_to["oleg@example.md"][1], repr({t: v[0] for t, v in by_to.items()}))
        home = c.get("/cont?msg=registered_issued")
        res.ok("кабинет: название, пробный до даты, файл, программа с версией из GitHub, просьба про IDNO",
               home.status == 200 and "Clinica Cont" in home.body and "Perioada de probă este valabilă" in home.body
               and "/cont/licenta.json" in home.body and "Descarcă DentPilot 1.35.3" in home.body
               and "DentPilot-Setup-1.35.3.exe" in home.body and "nu a verificat încă" in home.body
               and "completați IDNO" not in home.body and "a plecat" in home.body, home.body[-2500:])
        res.ok("кабинет не для роботов и без админских слов",
               "noindex" in home.body and "Клиники" not in home.body and "dentpilot.md/privacy.html" in home.body)
        f = c.get("/cont/licenta.json")
        admin = Client(s.url).login()
        res.ok("файл из кабинета — байт в байт тот, что в админке, и его принимает движок",
               f.status == 200 and f.body == admin.get(f"/admin/clinics/{cid}/issues/1/license.json").body
               and rv.open_envelope(f.body, KEYS)[0] == "" and "attachment" in f.headers.get("content-disposition", ""))
        res.check("журнал: скачивание файла из кабинета",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='download_license' AND clinic_id=?", cid)[0][0], 1)
        # абонемент: IDNO есть с регистрации → форма ноты
        res.ok("форма ноты: месяц и год по прайсу", "Comandă nota de plată" in home.body
               and f"{pay.amount(12, config.PRICE_MONTH)} MDL" in home.body and "name='method'" not in home.body)
        r = c.post("/cont/nota", months="6")
        res.check("срок не из ряда — bad_months", r.location, "/cont?msg=bad_months")
        n = len(_letters(s))
        r = c.post("/cont/nota", months="12")
        res.ok("нота на год создана", r.location == "/cont?msg=note_created", r.location)
        p = _sql(s, "SELECT reference, amount, months, status FROM payments WHERE clinic_id=?", cid)
        res.ok("платёж в ожидании: год по прайсу (11 месячных), reference DP-",
               len(p) == 1 and p[0][1] == pay.amount(12, config.PRICE_MONTH) and p[0][2] == 12
               and p[0][3] == "pending" and p[0][0].startswith("DP-"), repr(p))
        ref = p[0][0]
        last = _letters(s)[-1]
        res.ok("письмо с нотой клинике, с реквизитами и reference",
               len(_letters(s)) == n + 1 and last[0] == DIRECTOR["email"] and ref in last[2] and "IBAN" in last[2])
        home = c.get("/cont")
        res.ok("кабинет: нота, реквизиты и reference на странице, формы ноты больше нет",
               ref in home.body and "MD00TEST" in home.body and "Comandă nota" not in home.body
               and "în așteptare" in home.body, home.body[-2500:])
        res.check("вторая нота — note_exists", c.post("/cont/nota", months="1").location, "/cont?msg=note_exists")
        pid = _sql(s, "SELECT id FROM payments WHERE reference=?", ref)[0][0]
        admin.post(f"/admin/payments/{pid}/confirm")
        home = c.get("/cont")
        res.ok("после подтверждения: абонемент действует, платёж оплачен, новый файл",
               "Abonamentul este valabil" in home.body and "plătită" in home.body
               and rv.open_envelope(c.get("/cont/licenta.json").body, KEYS)[1].seq == 2, home.body[-2500:])
        # реквизиты
        r = c.post("/cont/date", name="Clinica Cont SRL", idno="1234567890123", contact_name="Ana P.",
                   phone="069000000", address="str. Test 1")
        res.ok("реквизиты сохранены", r.location == "/cont?msg=saved"
               and _sql(s, "SELECT name, address FROM clinics")[0] == ("Clinica Cont SRL", "str. Test 1"))
        res.check("IDNO не 13 цифр — bad_idno", c.post("/cont/date", name="X Y", idno="12").location, "/cont?msg=bad_idno")
        other = cid_from(admin.post("/admin/clinics", name="Altă Clinică", idno="9999999999999").location)
        res.check("IDNO другой клиники — idno_taken",
                  c.post("/cont/date", name="Clinica Cont SRL", idno="9999999999999").location, "/cont?msg=idno_taken")
        res.check("IDNO не изменился", _sql(s, "SELECT idno FROM clinics WHERE id=?", cid)[0][0], "1234567890123")
        res.ok("e-mail из кабинета не правится", _sql(s, "SELECT email FROM clinics WHERE id=?", cid)[0][0] == DIRECTOR["email"])
        res.ok("чужой Origin на реквизитах — 403",
               c.post("/cont/date", name="X Y", headers={"Origin": "http://evil.example", "Host": f"127.0.0.1:{s.port}"}).status == 403)
        # админка видит кабинет
        card = admin.get(f"/admin/clinics/{cid}").body
        res.ok("карточка клиники: раздел «Кабинет клиники» с ящиком Google и кнопкой «Отвязать»",
               "Кабинет клиники" in card and DIRECTOR["email"] in card and "Отвязать" in card, card[-3000:])
        aid = _accounts(s)[0][0]
        r = admin.post(f"/admin/accounts/{aid}/detach")
        res.ok("отвязка: записи нет, в карточке пусто",
               r.location == f"/admin/clinics/{cid}?msg=account_detached" and not _accounts(s)
               and "никто не входил" in admin.get(f"/admin/clinics/{cid}").body)
        res.ok("отвязанная запись не пускает сразу, кука ещё жива", c.get("/cont").location == "/cont/login")
        res.check("чужой id на отвязке — 404", admin.post("/admin/accounts/a_nope/detach").status, 404)
        # новый вход тем же Google-ящиком — клиника с таким ящиком есть → сразу в кабинет
        r = _google_login(c, s, g)
        res.ok("вход после отвязки: по ящику клиника найдена, сразу в кабинет",
               r.location == "/cont" and _accounts(s)[0][4] == cid
               and "Clinica Cont SRL" in c.get("/cont").body, r.location)
        res.check("журнал: привязка по e-mail",
                  _sql(s, "SELECT detail FROM audit WHERE what='account_link' ORDER BY id DESC LIMIT 1")[0][0],
                  f"по e-mail {DIRECTOR['email']}")
        res.ok("у чужой клиники кабинет пуст", "никто не входил" in admin.get(f"/admin/clinics/{other}").body)


def suite_link_and_duplicate(res: Result) -> None:
    """Клиника из админки + вход по её ящику; повтор по IDNO с другим ящиком; режим
    approve; скрытая клиника не привязывает; стенд GitHub для /descarca."""
    g = FakeGoogle()
    with Server(env={**g.env, "DP_TRIAL_MODE": "approve", "DP_TRIAL_NOTIFY": "oleg@example.md"}) as s:
        admin = Client(s.url).login()
        cid = cid_from(admin.post("/admin/clinics", name="Clinica Veche", idno="1111111111111",
                                  email="Director@Clinica-Test.md").location)
        c = Client(s.url)
        r = _google_login(c, s, g)
        res.ok("ящик Google = ящик клиники из админки (регистр другой): привязка сразу, в кабинет",
               r.location == "/cont" and _accounts(s)[0][4] == cid, r.location)
        home = c.get("/cont")
        res.ok("кабинет без файла: «cererea a fost primită» с датой, без ссылки на файл",
               "Clinica Veche" in home.body and "a fost primită" in home.body and "/cont/licenta.json" not in home.body)
        res.check("файл до выдачи — no_file", c.get("/cont/licenta.json").location, "/cont?msg=no_file")
        admin.post(f"/admin/clinics/{cid}/issue", kind="trial")
        res.ok("после выдачи кабинет показывает файл", "/cont/licenta.json" in c.get("/cont").body)
        # повтор по IDNO: директор входит ЛИЧНЫМ Gmail (Олег 01.10), а клиника
        # заведена с другим ящиком — код на ящик клиники, как у программы (L17)
        g.identity = dict(sub="g-second", email="second@gmail.com", name="Ion", email_verified=True)
        d = Client(s.url)
        res.check("новый ящик — регистрация", _google_login(d, s, g).location, "/cont/inregistrare")
        n = len(_letters(s))
        r = d.post("/cont/inregistrare", name="Clinica Veche", idno="1111111111111", consent="1")
        res.ok("тот же IDNO: страница кода (200), ящик клиники не назван, клиники второй нет, запись не привязана",
               r.status == 200 and "name='code'" in r.body and "name='verify_id'" in r.body
               and "clinica-test.md" not in r.body.lower() and len(_sql(s, "SELECT 1 FROM clinics")) == 1
               and _acc_clinic(s, "second@gmail.com") is None, f"{r.status} {r.body[-700:]}")
        vid = re.search(r"name='verify_id' value='([^']+)'", r.body).group(1)
        by_to = {t: (sub, body) for t, sub, body, _ in _letters(s)[n:]}
        res.ok("два письма: код на ящик клиники с Google-ящиком просителя, Олегу «ПОВТОР из кабинета» с кодом в журнале",
               len(by_to) == 2 and "conectarea contului" in by_to["Director@Clinica-Test.md"][0]
               and "second@gmail.com" in by_to["Director@Clinica-Test.md"][1]
               and "ПОВТОР из кабинета" in by_to["oleg@example.md"][1] and "second@gmail.com" in by_to["oleg@example.md"][1],
               repr({t: v[0] for t, v in by_to.items()}))
        code = re.search(r"codul: (\d{6})", by_to["Director@Clinica-Test.md"][1]).group(1)
        res.check("журнал: trial_duplicate без clinic_id",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='trial_duplicate' AND clinic_id IS NULL")[0][0], 1)
        res.check("журнал: code_sent от имени Google-ящика просителя, на карточке клиники",
                  _sql(s, "SELECT who, clinic_id FROM audit WHERE what='code_sent'"), [("second@gmail.com", cid)])
        wrong = "000000" if code != "000000" else "111111"
        r = d.post("/cont/inregistrare/cod", verify_id=vid, code=wrong)
        res.ok("неверный код — 400 словами, запись не привязана",
               r.status == 400 and "nu este corect" in r.body and _acc_clinic(s, "second@gmail.com") is None, f"{r.status}")
        r = d.post("/cont/inregistrare/cod", verify_id=vid, code=code)
        res.ok("верный код: аккаунт привязан к клинике с этим IDNO, в кабинет",
               r.status == 303 and r.location == "/cont?msg=linked" and _acc_clinic(s, "second@gmail.com") == cid,
               f"{r.status} {r.location}")
        home = d.get("/cont?msg=linked")
        res.ok("кабинет второго человека — та же клиника", "Clinica Veche" in home.body and "conectat" in home.body)
        res.ok("у клиники две записи кабинета — обе в карточке админки",
               len(_sql(s, "SELECT 1 FROM accounts WHERE clinic_id=?", cid)) == 2
               and all(e in admin.get(f"/admin/clinics/{cid}").body for e in ("Director@Clinica-Test.md", "second@gmail.com")))
        res.ok("чужой Origin на коде — 403",
               d.post("/cont/inregistrare/cod", verify_id="x", code="1",
                      headers={"Origin": "http://evil.example", "Host": f"127.0.0.1:{s.port}"}).status == 403)
        # код сгорает после CODE_ATTEMPTS ошибок — верный после них не пускает
        g.identity = dict(sub="g-burn", email="burn@gmail.com", name="B", email_verified=True)
        b = Client(s.url)
        _google_login(b, s, g)
        n = len(_letters(s))
        r = b.post("/cont/inregistrare", name="Clinica Veche", idno="1111111111111", consent="1")
        vid_b = re.search(r"name='verify_id' value='([^']+)'", r.body).group(1)
        code_b = re.search(r"codul: (\d{6})", [body for t, _, body, _ in _letters(s)[n:] if t == "Director@Clinica-Test.md"][0]).group(1)
        for _ in range(trial.CODE_ATTEMPTS):
            b.post("/cont/inregistrare/cod", verify_id=vid_b, code="999999" if code_b != "999999" else "888888")
        r = b.post("/cont/inregistrare/cod", verify_id=vid_b, code=code_b)
        res.ok("после пяти ошибок верный код сгорел: 400, не привязано",
               r.status == 400 and _acc_clinic(s, "burn@gmail.com") is None, f"{r.status}")
        # клиника без ящика: кода не отправить — 409 словами
        cid_nomail = cid_from(admin.post("/admin/clinics", name="Clinica Fără Mail", idno="2222222222222").location)
        n = len(_letters(s))
        r = b.post("/cont/inregistrare", name="Clinica Fără Mail", idno="2222222222222", consent="1")
        res.ok("IDNO клиники без e-mail: 409 «codul nu a putut fi trimis», Олегу письмо, записи нет",
               r.status == 409 and "nu a putut fi trimis" in r.body and _acc_clinic(s, "burn@gmail.com") is None
               and len(_letters(s)) == n + 1 and _letters(s)[-1][0] == "oleg@example.md", f"{r.status}")
        res.check("журнал: code_limit на карточке клиники без ящика",
                  _sql(s, "SELECT count(*) FROM audit WHERE what='code_limit' AND clinic_id=?", cid_nomail)[0][0], 1)
        # честная регистрация в режиме approve — третий ящик, своя клиника
        g.identity = dict(sub="g-stranger", email="stranger@example.md", name="Ion", email_verified=True)
        d = Client(s.url)
        res.check("третий ящик — регистрация", _google_login(d, s, g).location, "/cont/inregistrare")
        n = len(_letters(s))
        r = d.post("/cont/inregistrare", name="Clinica Străină", idno="", contact_name="Ion", consent="1")
        res.ok("approve: заявка принята, в кабинет с «cererea primită»",
               r.location == "/cont?msg=registered_requested", r.location)
        cid2 = _acc_clinic(s, "stranger@example.md")
        res.ok("клиника заведена без файла, привязана",
               cid2 not in (None, "нет записи") and not _sql(s, "SELECT 1 FROM issues WHERE clinic_id=?", cid2))
        by_to = {t: (sub, body) for t, sub, body, _ in _letters(s)[n:]}
        res.ok("письма: Олегу «ждёт решения», клинике «primită» с адресом кабинета",
               "ждёт решения" in by_to["oleg@example.md"][1] and "/cont" in by_to["stranger@example.md"][1]
               and "contul clinicii" in by_to["stranger@example.md"][1], repr(by_to))
        lst = admin.get("/admin").body
        res.ok("список клиник: заявка с меткой «кабинет»", "Заявки на пробный период" in lst and ">кабинет<" in lst)
        r = admin.post(f"/admin/clinics/{cid2}/issue", kind="trial", send="1", reason="заявка из кабинета")
        res.ok("выдача из админки — файл в кабинете, движок принимает",
               r.location == f"/admin/clinics/{cid2}?msg=issued_mailed"
               and rv.open_envelope(d.get("/cont/licenta.json").body, KEYS)[0] == "")
        # скрытая клиника: ящик свободен, вход даёт регистрацию, а не чужую клинику
        cid3 = cid_from(admin.post("/admin/clinics", name="Clinica Ascunsă", email="hidden@example.md").location)
        _sql(s, "UPDATE clinics SET declined_at='2026-09-30T00:00:00Z', origin='form' WHERE id=?", cid3)
        g.identity = dict(sub="g-hidden", email="hidden@example.md", name="H", email_verified=True)
        res.check("ящик скрытой клиники — регистрация, не её кабинет",
                  _google_login(Client(s.url), s, g).location, "/cont/inregistrare")
        # decline клиники с привязанной записью: кабинет говорит «închisă»
        _sql(s, "UPDATE clinics SET declined_at='2026-09-30T00:00:00Z' WHERE id=?", cid2)
        _sql(s, "DELETE FROM issues WHERE clinic_id=?", cid2)
        res.ok("скрытая заявка в кабинете — «închisă»", "a fost închisă" in d.get("/cont").body)


def suite_download(res: Result) -> None:
    """/descarca: ассет последнего выпуска, память, API без zip и лежащий API — страница выпусков."""
    gh = FakeGitHub()
    with Server(env=gh.env) as s:
        anon = Client(s.url)
        r = anon.get("/descarca")
        res.ok("302 на установщик последнего выпуска, без куки",
               r.status == 302 and r.location == ASSET_URL and "set-cookie" not in r.headers, f"{r.status} {r.location}")
        anon.get("/descarca")
        res.check("второй клик — из памяти, API не спрошен", gh.calls, 1)
        res.check("журнал: кто скачивал",
                  _sql(s, "SELECT count(*) FROM audit WHERE who='site' AND what='download' AND detail LIKE 'DentPilot-Setup-1.35.3.zip %'")[0][0], 2)
    gh.mode = "nozip"
    with Server(env=gh.env) as s:
        res.check("в выпуске нет zip — страница выпусков GitHub", Client(s.url).get("/descarca").location, config.RELEASES_PAGE)
    gh.mode = "down"
    with Server(env=gh.env) as s:
        r = Client(s.url).get("/descarca")
        res.ok("API лежит — страница выпусков, 302, не 500", r.status == 302 and r.location == config.RELEASES_PAGE)
    repo = re.search(r'REPO\s*=\s*"([^"]+)"', (ROOT / "bot" / "app" / "repo.py").read_text(encoding="utf-8"))
    res.ok("адрес API и страница выпусков — репозиторий программы (bot/app/repo.py)",
           repo is not None and f"/repos/{repo.group(1)}/releases/latest" in config.RELEASES_API
           and f"github.com/{repo.group(1)}/releases" in config.RELEASES_PAGE, repr(repo and repo.group(1)))


def suite_rules(res: Result) -> None:
    """Чистые правила: проверка claim'ов, реквизиты, куки разных видов."""
    now = time.time()
    good = {"iss": "accounts.google.com", "aud": config.GOOGLE_CLIENT_ID or "", "exp": now + 60, "nonce": "n1",
            "sub": "s", "email": "a@b.md", "email_verified": True, "name": "  Ana   Pop "}
    # в этом процессе DP_GOOGLE_CLIENT_ID пуст: aud '' — проверка всё равно сверяет строку
    ident, code = account.verify(good, "n1", now)
    res.ok("годный токен: личность, имя схлопнуто", code == "" and ident.name == "Ana Pop" and ident.sub == "s", f"{code} {ident}")
    for label, bad, want in (("exp строкой-мусором", dict(good, exp="x"), account.FAILED),
                             ("nonce пустой у нас", (good, ""), account.FAILED),
                             ("email_verified строкой 'true'", dict(good, email_verified="true"), account.UNVERIFIED),
                             ("без email", dict(good, email=""), account.FAILED)):
        claims, nonce = (bad if isinstance(bad, tuple) else (bad, "n1"))
        res.check(label, account.verify(claims, nonce, now)[1], want)
    res.check("JWT из двух частей — не токен", account._claims("a.b"), None)
    res.check("JWT с мусором в теле — не токен", account._claims("a.!!!.c"), None)
    f, code = account.clean_edit(dict(name=" Clinica  X ", idno="1234 5678 90123", address="a" * 201))
    res.ok("реквизиты: адрес длиннее 200 — too_long, пробелы схлопнуты", code == "too_long" and f["name"] == "Clinica X")
    res.check("реквизиты: IDNO из 12 цифр", account.clean_edit(dict(name="Xy", idno="123456789012"))[1], "bad_idno")
    res.check("реквизиты: всё чисто", account.clean_edit(dict(name="Xy", idno="1234567890123"))[1], "")
    tok = auth.account_cookie("a_1")
    res.ok("кука кабинета читается своим видом и не читается чужими",
           auth._read("account", tok) == "a_1" and auth._read("admin", tok) is None and auth._read("oauth", tok) is None)
    res.check("тело с «|» переживает подпись", auth.read_oauth_cookie(auth.oauth_cookie("st|nonce")), "st|nonce")
    body, exp_s, mac = tok.rsplit("|", 2)
    res.check("подделанный срок — не кука", auth._read("account", f"{body}|{int(exp_s) + 1}|{mac}"), None)
