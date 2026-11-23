"""Провод Google (`app/core/gauth.py`, `app/core/gapi.py`): стенд Google в процессе, сервер программы
не поднимается.

Стенд отвечает как Google по справке: `/token` сверяет PKCE, адрес возврата и клиента, `/revoke`
гасит токен, `/calendar/v3` отдаёт страницы. Экран согласия — браузер человека, его изображает
`Google.consent`: разбирает адрес согласия и отдаёт строку возврата. Переходник сверяется с ics на
одном календаре в двух видах — файлом и ответом API — как опыт сверит настоящий календарь.
"""
import base64
import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import test_ics as t
from harness import BOT, ROOT, Result, clinic_now, free_port

sys.path.insert(0, str(BOT))
from app.core import gapi, gauth, gclient, gimport, ics  # noqa: E402

GAUTH = BOT / "app" / "core" / "gauth.py"
GAPI = BOT / "app" / "core" / "gapi.py"
AUTH_IMPORTS = {"__future__", "base64", "hashlib", "hmac", "http.client", "json", "secrets",
                "urllib.error", "urllib.parse", "urllib.request", "dataclasses"}
API_IMPORTS = {"__future__", "http.client", "json", "re", "urllib.error", "urllib.parse",
               "urllib.request", "dataclasses", "datetime"}
TZ = t.TZ
CLIENT = gauth.Client("123-test.apps.googleusercontent.com")


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                    # клиент отвалился по таймауту — так и задумано


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class Google:
    """Google в процессе. `token_reply` / `api_reply[путь]` — (статус, тело, заголовки) вместо ответа;
    `page` — размер страницы стенда (меньше просимого — чтобы страниц было несколько); `fail_page` —
    номер страницы событий, отвечающей 503; `loop` — `nextPageToken` по кругу; `secret` — какой
    client_secret требует обмен ("" — не требует). `write` — крючок записи (test_gwrite.Calendars):
    `(метод, путь, запрос, JSON-тело, права токена) → (статус, тело[, заголовки])`; с ним любой запрос
    под /calendar/v3/ идёт туда, тело — JSON в UTF-8."""

    def __init__(self):
        self.codes: dict[str, dict] = {}
        self.access: dict[str, frozenset] = {}
        self.refreshes: dict[str, frozenset] = {}
        self.by_refresh: dict[str, set] = {}
        self.secret = ""
        self.give_refresh = True
        self.token_reply: tuple | None = None
        self.api_reply: dict[str, tuple] = {}
        self.calendars: list[dict] = []
        self.events: dict[str, list] = {}
        self.tz = "Europe/Chisinau"
        self.page = 1000
        self.fail_page: int | None = None
        self.loop = False
        self.delay = 0.0
        self.requests: list[dict] = []
        self.write = None
        self._n = 0
        stand = self

        class H(http.server.BaseHTTPRequestHandler):
            def _reply(self, status: int, data, headers: dict | None = None) -> None:
                body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
                self.send_response(status)
                for k, v in {"Content-Type": "application/json", **(headers or {})}.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _trap(self) -> bool:
                if self.path.startswith("/redir"):
                    self.send_response(302)
                    self.send_header("Location", stand.base + "/trap")
                    self.end_headers()
                    return True
                return False

            def _write(self, method: str) -> bool:
                """Запрос к календарю мимо стенда чтения — в крючок записи."""
                url = urllib.parse.urlsplit(self.path)
                if stand.write is None or not (url.path.startswith("/calendar/v3/") or url.path.startswith("/redir")):
                    return False
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else None
                except ValueError:
                    body = ValueError
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                bearer = self.headers.get("Authorization", "")
                stand.requests.append({"method": method, "path": url.path, "query": query, "json": body,
                                       "auth": bearer, "agent": self.headers.get("User-Agent"),
                                       "type": self.headers.get("Content-Type", "")})
                if stand.delay:
                    time.sleep(stand.delay)
                if self._trap():
                    return True
                if not bearer.startswith("Bearer ") or bearer[7:] not in stand.access:
                    self._reply(401, {"error": {"code": 401, "status": "UNAUTHENTICATED",
                                                "errors": [{"reason": "authError", "domain": "global"}]}})
                    return True
                if body is ValueError:
                    self._reply(400, {"error": {"code": 400, "errors": [{"reason": "parseError"}]}})
                    return True
                reply = stand.write(method, url.path, query, body, stand.access[bearer[7:]])
                if reply is None:
                    reply = (404, {"error": {"code": 404, "errors": [{"reason": "notFound"}]}})
                if reply[0] == 204:
                    self.send_response(204)
                    self.end_headers()
                    return True
                self._reply(*reply)
                return True

            def do_POST(self):
                if self._write("POST"):
                    return
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("ascii")).items()}
                stand.requests.append({"path": self.path, "form": form, "agent": self.headers.get("User-Agent")})
                if stand.delay:
                    time.sleep(stand.delay)
                if self._trap():
                    return
                if stand.token_reply is not None:
                    self._reply(*stand.token_reply)
                    return
                if self.path == "/token":
                    self._reply(*stand._token(form))
                elif self.path == "/revoke":
                    self._reply(*stand._revoke(form.get("token", "")))
                else:
                    self._reply(404, {"error": "not_found"})

            def do_PUT(self):
                if not self._write("PUT"):
                    self._reply(405, {"error": "method"})

            def do_PATCH(self):
                if not self._write("PATCH"):
                    self._reply(405, {"error": "method"})

            def do_DELETE(self):
                if not self._write("DELETE"):
                    self._reply(405, {"error": "method"})

            def do_GET(self):
                if self._write("GET"):
                    return
                url = urllib.parse.urlsplit(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                stand.requests.append({"path": url.path, "query": query,
                                       "auth": self.headers.get("Authorization", "")})
                if self._trap():
                    return
                for prefix, reply in stand.api_reply.items():
                    if url.path.startswith(prefix):
                        self._reply(*reply)
                        return
                bearer = self.headers.get("Authorization", "")
                if not bearer.startswith("Bearer ") or bearer[7:] not in stand.access:
                    self._reply(401, {"error": {"code": 401, "status": "UNAUTHENTICATED",
                                                "errors": [{"reason": "authError", "domain": "global"}]}})
                    return
                self._reply(*stand._api(url.path, query))

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.auth_url = self.base + "/auth"
        self.token_url = self.base + "/token"
        self.revoke_url = self.base + "/revoke"
        self.api = self.base + "/calendar/v3"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()

    def _next(self, kind: str) -> str:
        self._n += 1
        return f"{kind}-{self._n}"

    def consent(self, url: str, keep: tuple | None = None) -> str:
        """Человек согласился на экране Google: строка возврата `code=…&state=…&scope=…`.
        `keep` — права, оставленные галочками (по умолчанию все просимые)."""
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
        scopes = tuple(q["scope"].split()) if keep is None else keep
        code = self._next("4/code")
        self.codes[code] = {"challenge": q["code_challenge"], "method": q["code_challenge_method"],
                            "redirect": q["redirect_uri"], "client": q["client_id"], "scopes": frozenset(scopes)}
        return urllib.parse.urlencode({"code": code, "state": q["state"], "scope": " ".join(scopes)})

    def _grant(self, scopes: frozenset, refresh: str = "") -> dict:
        access = self._next("ya29")
        self.access[access] = scopes
        out = {"access_token": access, "expires_in": 3599, "token_type": "Bearer", "scope": " ".join(sorted(scopes))}
        if refresh:
            self.by_refresh.setdefault(refresh, set()).add(access)
            out["refresh_token"] = refresh
        return out

    def _token(self, form: dict) -> tuple:
        if form.get("client_id") != CLIENT.id:
            return 401, {"error": "invalid_client", "error_description": "The OAuth client was not found."}
        if stand_secret_missing(self, form):
            return 400, {"error": "invalid_request", "error_description": "client_secret is missing."}
        if form.get("grant_type") == "authorization_code":
            got = self.codes.pop(form.get("code", ""), None)
            if got is None:
                return 400, {"error": "invalid_grant", "error_description": "Bad Request"}
            if form.get("redirect_uri") != got["redirect"]:
                return 400, {"error": "redirect_uri_mismatch", "error_description": "Bad Request"}
            verifier = form.get("code_verifier", "")
            if got["method"] != "S256" or _b64(hashlib.sha256(verifier.encode()).digest()) != got["challenge"]:
                return 400, {"error": "invalid_grant", "error_description": "Invalid code verifier."}
            refresh = self._next("1//rt") if self.give_refresh else ""
            if refresh:
                self.refreshes[refresh] = got["scopes"]
            body = self._grant(got["scopes"], refresh)
            if refresh:
                self.by_refresh[refresh] = {body["access_token"]}
            return 200, body
        if form.get("grant_type") == "refresh_token":
            refresh = form.get("refresh_token", "")
            if refresh not in self.refreshes:
                return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
            body = self._grant(self.refreshes[refresh])
            self.by_refresh.setdefault(refresh, set()).add(body["access_token"])
            return 200, body
        return 400, {"error": "unsupported_grant_type"}

    def _revoke(self, token: str) -> tuple:
        if token in self.refreshes:
            del self.refreshes[token]
            for a in self.by_refresh.pop(token, set()):
                self.access.pop(a, None)
            return 200, {}
        if token in self.access:
            del self.access[token]
            return 200, {}
        return 400, {"error": "invalid_token", "error_description": "Token expired or revoked"}

    def _paged(self, items: list, query: dict, extra: dict | None = None) -> tuple:
        size = min(int(query.get("maxResults") or 100), self.page)
        start = int((query.get("pageToken") or "p0")[1:]) if not self.loop else 0
        index = start // size if size else 0
        if self.fail_page is not None and index == self.fail_page:
            return 503, {"error": {"code": 503, "status": "UNAVAILABLE"}}
        body = {"items": items[start:start + size], **(extra or {})}
        if self.loop:
            body["nextPageToken"] = "same"
        elif start + size < len(items):
            body["nextPageToken"] = f"p{start + size}"
        return 200, body

    def _api(self, path: str, query: dict) -> tuple:
        if path == "/calendar/v3/users/me/calendarList":
            return self._paged(self.calendars, query)
        prefix, suffix = "/calendar/v3/calendars/", "/events"
        if path.startswith(prefix) and path.endswith(suffix):
            cid = urllib.parse.unquote(path[len(prefix):-len(suffix)])
            if cid not in self.events:
                return 404, {"error": {"code": 404, "errors": [{"reason": "notFound", "domain": "global"}]}}
            return self._paged(self.events[cid], query, {"timeZone": self.tz})
        return 404, {"error": {"code": 404}}


def stand_secret_missing(stand: Google, form: dict) -> bool:
    return bool(stand.secret) and form.get("client_secret") != stand.secret


def dead_port() -> int:
    """Порт, который никто не слушает: бронь харнесса не отдаст его соседней части прогона."""
    return free_port()


def _login(g: Google, client: gauth.Client = CLIENT, keep: tuple | None = None) -> gauth.Reply:
    verifier, chal = gauth.pkce()
    state, redirect = gauth.new_state(), gauth.loopback(51234, "/google/back")
    url = gauth.consent_url(client, redirect, state, chal, auth_url=g.auth_url)
    b = gauth.back(g.consent(url, keep), state)
    return gauth.exchange(client, b.auth_code, verifier, redirect, token_url=g.token_url)


# ---------- чистота ----------


def suite_pure(res: Result) -> None:
    res.ok("исходники провода нашлись", GAUTH.is_file() and GAPI.is_file(), f"{GAUTH}, {GAPI}")
    t.pure(res, GAUTH, AUTH_IMPORTS, set())
    t.pure(res, GAPI, API_IMPORTS, {"ics"})
    res.ok("права программы — только чтение", all(s.endswith(".readonly") for s in gauth.SCOPES),
           str(gauth.SCOPES))
    res.check("коды исходов перечислены без повторов",
              (len(set(gauth.CODES)), len(set(gapi.CODES))), (len(gauth.CODES), len(gapi.CODES)))


# ---------- вход ----------


def suite_auth(res: Result) -> None:
    v1, c1 = gauth.pkce()
    v2, _ = gauth.pkce()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    res.ok("PKCE: verifier 43–128 знаков из разрешённых", 43 <= len(v1) <= 128 and set(v1) <= allowed, v1)
    res.check("PKCE: challenge = base64url(sha256(verifier)) без =", c1, _b64(hashlib.sha256(v1.encode()).digest()))
    res.ok("PKCE и state каждый раз новые", v1 != v2 and gauth.new_state() != gauth.new_state())

    res.check("адрес возврата — 127.0.0.1 с портом и путём", gauth.loopback(51234, "/google/back"),
              "http://127.0.0.1:51234/google/back")
    bad = []
    for port, path in ((0, "/"), (70000, "/"), (True, "/"), (5000, "back"), (5000, "/a?b=1"), (5000, "/a#b")):
        try:
            gauth.loopback(port, path)
            bad.append((port, path))
        except ValueError:
            pass
    res.check("адрес возврата: кривой порт или путь — отказ", bad, [])

    redirect = gauth.loopback(51234, "/google/back")
    url = gauth.consent_url(CLIENT, redirect, "st-1", c1, login_hint="dr@example.com")
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(parts.query)
    res.check("согласие: адрес Google", f"{parts.scheme}://{parts.netloc}{parts.path}", gauth.AUTH_URL)
    res.check("согласие: параметры", {k: v[0] for k, v in q.items()},
              {"client_id": CLIENT.id, "redirect_uri": redirect, "response_type": "code",
               "scope": " ".join(gauth.SCOPES), "code_challenge": c1, "code_challenge_method": "S256",
               "state": "st-1", "login_hint": "dr@example.com"})
    sec = gauth.consent_url(gauth.Client(CLIENT.id, "s3cr3t"), redirect, "st", c1)
    res.ok("согласие: секрета клиента в адресе нет", "s3cr3t" not in sec and "client_secret" not in sec, sec)
    try:
        gauth.consent_url(CLIENT, redirect, "st", c1, auth_url="http://accounts.example/auth")
        res.ok("согласие: адрес не https — отказ", False)
    except ValueError:
        res.ok("согласие: адрес не https — отказ", True)

    cases = [
        ("state=st&code=4%2Fx&scope=a%20b", "st", (gauth.OK, "4/x", frozenset({"a", "b"}))),
        ("state=zz&code=4%2Fx", "st", (gauth.BAD_STATE, "", frozenset())),
        ("code=4%2Fx", "st", (gauth.BAD_STATE, "", frozenset())),
        ("state=st&code=4%2Fx", "", (gauth.BAD_STATE, "", frozenset())),
        ("state=zz&error=access_denied", "st", (gauth.BAD_STATE, "", frozenset())),
        ("state=st&error=access_denied", "st", (gauth.ACCESS_DENIED, "", frozenset())),
        ("state=st&error=server_error", "st", (gauth.FAILED, "", frozenset())),
        ("state=st", "st", (gauth.NO_CODE, "", frozenset())),
        ("state=st&code=a&code=b", "st", (gauth.NO_CODE, "", frozenset())),
        ("state=%C8%99&code=a", "st", (gauth.BAD_STATE, "", frozenset())),
    ]
    got = [(qs, (b.code, b.auth_code, b.scopes)) for qs, st, _ in cases for b in [gauth.back(qs, st)]]
    res.check("возврат из браузера: state первым, потом ошибка, потом код", got,
              [(qs, want) for qs, _, want in cases])
    res.check("снятая галочка права видна", gauth.missing(frozenset({gauth.EVENTS_READONLY})),
              (gauth.CALENDARLIST_READONLY,))

    good = json.dumps({"installed": {"client_id": CLIENT.id, "client_secret": "GOCSPX-x",
                                     "redirect_uris": ["http://localhost"]}})
    res.check("JSON консоли: Desktop-клиент читается", gauth.client_of(good), gauth.Client(CLIENT.id, "GOCSPX-x"))
    res.check("JSON консоли: без секрета — секрет пустой",
              gauth.client_of(json.dumps({"installed": {"client_id": CLIENT.id}})), CLIENT)
    res.check("JSON консоли: web-клиент, чужой id, мусор — не клиент",
              [gauth.client_of(x) for x in (json.dumps({"web": {"client_id": CLIENT.id}}),
                                            json.dumps({"installed": {"client_id": "abc"}}), b"\xff", "[]")],
              [None, None, None, None])

    g = Google()
    try:
        r = _login(g)
        res.ok("обмен: код + PKCE → токены", r.code == gauth.OK and r.grant is not None, repr(r))
        if r.grant is None:
            return
        res.check("обмен: выданы оба права, refresh-токен есть", (r.grant.scopes, bool(r.grant.refresh),
                                                                  r.grant.expires_in), (frozenset(gauth.SCOPES), True, 3599))
        form = next(x["form"] for x in g.requests if x["path"] == "/token")
        res.ok("обмен: verifier ушёл, секрета нет (у клиента его нет)",
               "code_verifier" in form and "client_secret" not in form, str(sorted(form)))
        res.check("обмен: User-Agent программы", g.requests[-1]["agent"], "DentPilot")
        rt = r.grant.refresh

        part = _login(g, keep=(gauth.EVENTS_READONLY,))
        res.check("обмен: снятая галочка — в выданных правах её нет",
                  gauth.missing(part.grant.scopes) if part.grant else None, (gauth.CALENDARLIST_READONLY,))

        verifier, chal = gauth.pkce()
        redirect = gauth.loopback(51234, "/google/back")
        url = gauth.consent_url(CLIENT, redirect, "s", chal, auth_url=g.auth_url)
        code = gauth.back(g.consent(url), "s").auth_code
        res.check("обмен: чужой verifier — invalid_grant",
                  gauth.exchange(CLIENT, code, verifier + "x", redirect, token_url=g.token_url).code,
                  gauth.INVALID_GRANT)
        res.check("обмен: код дважды — invalid_grant",
                  gauth.exchange(CLIENT, code, verifier, redirect, token_url=g.token_url).code, gauth.INVALID_GRANT)
        code = gauth.back(g.consent(url), "s").auth_code
        mis = gauth.exchange(CLIENT, code, verifier, gauth.loopback(51235, "/google/back"), token_url=g.token_url)
        res.check("обмен: другой адрес возврата — наша ошибка, не «войдите снова»",
                  (mis.code, mis.reason), (gauth.BAD_REQUEST, "redirect_uri_mismatch"))

        g.give_refresh = False
        res.check("обмен без refresh-токена — no_refresh, не ok", _login(g).code, gauth.NO_REFRESH)
        g.give_refresh = True

        g.secret = "GOCSPX-x"
        res.check("Google требует секрет, у сборки его нет — bad_request",
                  (_login(g).code, _login(g, gauth.Client(CLIENT.id, "GOCSPX-x")).code),
                  (gauth.BAD_REQUEST, gauth.OK))
        g.secret = ""
        res.check("чужой клиент — invalid_client", _login(g, gauth.Client("999-x.apps.googleusercontent.com")).code,
                  gauth.INVALID_CLIENT)

        f = gauth.refresh(CLIENT, rt, token_url=g.token_url)
        res.ok("обновление: новый access-токен, refresh-токен прежний", f.code == gauth.OK and f.grant is not None
               and f.grant.access in g.access and f.grant.refresh == "", repr(f))
        res.check("обновление: мёртвый refresh-токен — invalid_grant",
                  gauth.refresh(CLIENT, "1//nope", token_url=g.token_url).code, gauth.INVALID_GRANT)

        replies = [
            ((400, {"error": "admin_policy_enforced"}), gauth.ADMIN_POLICY),
            ((401, {}), gauth.INVALID_CLIENT),
            ((429, {"error": "rate_limit_exceeded"}), gauth.RATE_LIMITED),
            ((503, {"error": "backend_error"}), gauth.OFFLINE),
            ((400, {"error": "invalid_scope"}), gauth.BAD_REQUEST),
            ((200, b"<html>captive portal</html>"), gauth.OFFLINE),
            ((200, {"access_token": "a", "expires_in": 3599, "token_type": "MAC"}), gauth.OFFLINE),
            ((200, {"access_token": "a", "expires_in": True, "token_type": "Bearer"}), gauth.OFFLINE),
            ((200, {"access_token": "a", "expires_in": 3599, "token_type": "Bearer",
                    "pad": "x" * gauth.MAX_BODY}), gauth.OFFLINE),
        ]
        got = []
        for reply, _ in replies:
            g.token_reply = reply
            got.append(gauth.refresh(CLIENT, rt, token_url=g.token_url).code)
        g.token_reply = None
        res.check("ответ Google → код исхода", got, [want for _, want in replies])

        before = len(g.requests)
        red = gauth.refresh(CLIENT, rt, token_url=g.base + "/redir")
        res.ok("редиректу не следует: токен не уезжает на чужой адрес",
               red.code == gauth.OFFLINE and not any(x["path"] == "/trap" for x in g.requests[before:]))
        res.check("сеть недоступна — offline",
                  gauth.refresh(CLIENT, rt, token_url=f"http://127.0.0.1:{dead_port()}/token").code, gauth.OFFLINE)
        g.delay = 1.0
        t0 = time.monotonic()
        slow = gauth.refresh(CLIENT, rt, token_url=g.token_url, timeout=0.3)
        g.delay = 0.0
        res.ok("таймаут — offline и не дольше таймаута с запасом",
               slow.code == gauth.OFFLINE and time.monotonic() - t0 < 0.9, f"{slow} {time.monotonic() - t0:.2f}")

        access = gauth.refresh(CLIENT, rt, token_url=g.token_url).grant.access
        res.check("отзыв refresh-токена — ok", gauth.revoke(rt, revoke_url=g.revoke_url).code, gauth.OK)
        res.check("после отзыва: обновление — invalid_grant, API — unauthorized",
                  (gauth.refresh(CLIENT, rt, token_url=g.token_url).code,
                   gapi.calendars(access, base=g.api).code), (gauth.INVALID_GRANT, gapi.UNAUTHORIZED))
        res.check("повторный отзыв — invalid_grant (связь и так мертва)",
                  gauth.revoke(rt, revoke_url=g.revoke_url).code, gauth.INVALID_GRANT)
        sent = [x["form"] for x in g.requests if x["path"] == "/revoke"]
        res.ok("отзыв не несёт секрета клиента", all("client_secret" not in f for f in sent), str(sent))
    finally:
        g.close()


# ---------- календари и события ----------


def _event(uid: str, start: str, end: str, **kw) -> dict:
    return {"id": uid.split("@")[0], "iCalUID": uid, "status": "confirmed",
            "start": {"dateTime": start}, "end": {"dateTime": end}, **kw}


def suite_api(res: Result) -> None:
    g = Google()
    try:
        g.access["tok"] = frozenset(gauth.SCOPES)
        g.page = 2
        g.calendars = [
            {"id": "clinica@gmail.com", "summary": "Clinica", "primary": True, "accessRole": "owner",
             "timeZone": "Europe/Chisinau"},
            {"id": "c_1@group.calendar.google.com", "summary": "Dr. Rusu", "summaryOverride": "  Rusu  ",
             "accessRole": "reader"},
            {"id": "ro.md#holiday@group.v.calendar.google.com", "summary": "Sărbători", "accessRole": "reader"},
        ]
        r = gapi.calendars("tok", base=g.api)
        res.check("календари: все страницы, имя — своё у человека", [(c.id, c.name, c.primary, c.role) for c in r.items],
                  [("clinica@gmail.com", "Clinica", True, "owner"), ("c_1@group.calendar.google.com", "Rusu", False, "reader"),
                   ("ro.md#holiday@group.v.calendar.google.com", "Sărbători", False, "reader")])
        q = next(x["query"] for x in g.requests if x["path"].endswith("/calendarList"))
        res.check("календари: только читаемые, поля отобраны", (q.get("minAccessRole"), q.get("fields")),
                  ("reader", gapi.LIST_FIELDS))
        res.check("календари: Bearer access-токена", g.requests[-1]["auth"], "Bearer tok")

        cid = "ro.md#holiday@group.v.calendar.google.com"
        g.events[cid] = [_event(f"e{i}@google.com", f"2027-01-0{i}T10:00:00+02:00", f"2027-01-0{i}T10:30:00+02:00")
                         for i in range(1, 6)]
        lo = datetime(2026, 12, 31, 22, 0, tzinfo=timezone.utc)
        hi = datetime(2027, 12, 31, 10, 0, tzinfo=TZ)
        g.requests.clear()
        r = gapi.events("tok", cid, lo, hi, base=g.api)
        res.check("события: три страницы — весь набор по порядку", (r.code, [e["iCalUID"] for e in r.items], r.tz),
                  (gapi.OK, [f"e{i}@google.com" for i in range(1, 6)], "Europe/Chisinau"))
        q = g.requests[0]["query"]
        res.check("события: окно, развёрнутые серии, поля",
                  (q.get("timeMin"), q.get("timeMax"), q.get("singleEvents"), q.get("fields")),
                  ("2026-12-31T22:00:00Z", "2027-12-31T08:00:00Z", "true", gapi.EVENT_FIELDS))
        res.check("события: id календаря с # и @ — одним сегментом пути", g.requests[0]["path"],
                  "/calendar/v3/calendars/" + urllib.parse.quote(cid, safe="") + "/events")
        res.ok("события: страница за страницей по nextPageToken",
               [x["query"].get("pageToken") for x in g.requests] == [None, "p2", "p4"], str(g.requests))

        g.fail_page = 1
        r = gapi.events("tok", cid, lo, hi, base=g.api)
        res.check("сбой на второй странице — отказ всего набора, ни одного события", (r.code, r.items), (gapi.OFFLINE, ()))
        g.fail_page = None
        g.loop = True
        r = gapi.events("tok", cid, lo, hi, base=g.api)
        res.check("страница по кругу — отказ, а не вечный опрос", (r.code, r.reason, r.items), (gapi.OFFLINE, "page_loop", ()))
        g.loop = False
        r = gapi.events("tok", cid, lo, hi, base=g.api, max_events=3)
        res.check("событий больше потолка — too_many, не часть", (r.code, r.items), (gapi.TOO_MANY, ()))
        res.check("календаря нет — not_found", gapi.events("tok", "nope@x", lo, hi, base=g.api).code, gapi.NOT_FOUND)
        res.check("чужой токен — unauthorized", gapi.events("bad", cid, lo, hi, base=g.api).code, gapi.UNAUTHORIZED)

        path = "/calendar/v3/calendars/"

        def err(status, reason, domain="global", details=None):
            body = {"error": {"code": status, "errors": [{"reason": reason, "domain": domain}]}}
            if details:
                body["error"]["details"] = details
            return status, body

        replies = [
            (err(403, "insufficientPermissions", details=[{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]),
             (gapi.NO_SCOPE, "ACCESS_TOKEN_SCOPE_INSUFFICIENT", 0)),
            (err(403, "rateLimitExceeded", "usageLimits"), (gapi.RATE_LIMITED, "rateLimitExceeded", 0)),
            (err(403, "accessNotConfigured", "usageLimits"), (gapi.FORBIDDEN, "accessNotConfigured", 0)),
            (err(403, "forbidden"), (gapi.FORBIDDEN, "forbidden", 0)),
            ((*err(429, "rateLimitExceeded"), {"Retry-After": "30"}), (gapi.RATE_LIMITED, "rateLimitExceeded", 30)),
            ((*err(429, "rateLimitExceeded"), {"Retry-After": "86400"}), (gapi.RATE_LIMITED, "rateLimitExceeded", 3600)),
            (err(410, "fullSyncRequired"), (gapi.NOT_FOUND, "fullSyncRequired", 0)),
            (err(400, "badRequest"), (gapi.BAD_REQUEST, "badRequest", 0)),
            ((500, {"error": {"code": 500, "status": "INTERNAL"}}), (gapi.OFFLINE, "INTERNAL", 0)),
            ((200, b"<html>captive portal</html>"), (gapi.OFFLINE, "bad_body", 0)),
            ((200, {"items": {"not": "a list"}}), (gapi.OFFLINE, "bad_body", 0)),
            ((200, {"items": [1, 2]}), (gapi.OFFLINE, "bad_body", 0)),
        ]
        got = []
        for reply, _ in replies:
            g.api_reply = {path: reply}
            r = gapi.events("tok", cid, lo, hi, base=g.api)
            got.append((r.code, r.reason, r.retry_after))
        g.api_reply = {}
        res.check("ответ API → код исхода", got, [want for _, want in replies])

        g.requests.clear()
        r = gapi.calendars("tok", base=g.base + "/redir")
        res.ok("API: редиректу не следует — токен не уезжает", r.code == gapi.OFFLINE
               and not any(x["path"] == "/trap" for x in g.requests), str(g.requests))
        res.check("API: сеть недоступна — offline",
                  gapi.calendars("tok", base=f"http://127.0.0.1:{dead_port()}/calendar/v3").code, gapi.OFFLINE)
        bad = []
        for fn in (lambda: gapi.calendars("tok", base="http://www.googleapis.com/calendar/v3"),
                   lambda: gapi.events("tok", cid, datetime(2027, 1, 1), hi, base=g.api)):
            try:
                fn()
                bad.append(fn)
            except ValueError:
                pass
        res.check("API: адрес не https и момент без пояса — отказ вызова", bad, [])
    finally:
        g.close()


# ---------- переходник ----------


def suite_convert(res: Result) -> None:
    single = _event("u1@google.com", "2027-02-01T09:07:42+02:00", "2027-02-01T09:52:10+02:00",
                    summary="  Ion \n Popescu  ", description="Tel <b>069 123 456</b><br>control",
                    location=" Cab.  1 ", attendees=[{"email": "a@x.md", "displayName": "Ana"}, {"email": "b@x.md"}])
    o = gapi.occurrence(single)
    res.check("одиночное: ключ iCalUID, момент без секунд, минуты по исходным",
              (o.key, o.start, o.minutes, o.series, o.moved),
              ("u1@google.com", datetime(2027, 2, 1, 7, 7, tzinfo=timezone.utc), 45, False, False))
    res.check("одиночное: текст как у файла", (o.title, o.description, o.location, o.attendees, o.status),
              ("Ion Popescu", "Tel 069 123 456\ncontrol", "Cab. 1", (("Ana", "a@x.md"), ("", "b@x.md")), "CONFIRMED"))

    dst = gapi.occurrence(_event("u2@google.com", "2026-10-25T02:30:00+03:00", "2026-10-25T03:30:00+02:00"))
    res.check("ночь перевода часов: минуты через UTC", dst.minutes, 120)

    inst = {"iCalUID": "s1@google.com", "recurringEventId": "s1", "status": "confirmed",
            "start": {"dateTime": "2027-02-02T00:30:00+02:00", "timeZone": "Europe/Chisinau"},
            "end": {"dateTime": "2027-02-02T01:00:00+02:00", "timeZone": "Europe/Chisinau"},
            "originalStartTime": {"dateTime": "2027-02-01T22:30:00Z", "timeZone": "Europe/Chisinau"}}
    o = gapi.occurrence(inst)
    res.check("вхождение серии: ключ — дата по поясу серии, не по UTC", (o.key, o.series, o.moved),
              (ics.occurrence_key("s1@google.com", date(2027, 2, 2)), True, False))
    no_tz = {**inst, "start": {"dateTime": "2027-02-02T00:30:00+02:00"},
             "originalStartTime": {"dateTime": "2027-02-02T00:30:00+02:00"}}
    res.check("вхождение без пояса у события: пояс календаря", gapi.occurrence(no_tz, "UTC").key,
              ics.occurrence_key("s1@google.com", date(2027, 2, 1)))
    res.check("вхождение без пояса вовсе: дата как записана", gapi.occurrence(no_tz).key,
              ics.occurrence_key("s1@google.com", date(2027, 2, 2)))
    moved = {**inst, "start": {"dateTime": "2027-02-03T12:00:00+02:00", "timeZone": "Europe/Chisinau"},
             "end": {"dateTime": "2027-02-03T12:40:00+02:00", "timeZone": "Europe/Chisinau"}}
    o = gapi.occurrence(moved)
    res.check("перенесённое вхождение: ключ по исходной дате, пометка moved",
              (o.key, o.moved, o.minutes, o.start.astimezone(TZ).hour),
              (ics.occurrence_key("s1@google.com", date(2027, 2, 2)), True, 40, 12))

    allday = gapi.occurrence({"iCalUID": "d1@google.com", "start": {"date": "2027-02-05"}, "end": {"date": "2027-02-06"}})
    res.check("весь день: дата, без момента", (allday.key, allday.day, allday.start, allday.minutes),
              ("d1@google.com", date(2027, 2, 5), None, 0))
    now = datetime(2027, 1, 10, 9, 0, tzinfo=TZ)
    d = gimport.convert(allday, tz=TZ, now=now, doctors={})
    res.check("весь день дальше — «omis», как у файла", (d.kind, d.why), (gimport.SKIPPED, gimport.ALL_DAY))
    series_day = gapi.occurrence({"iCalUID": "d2@google.com", "recurringEventId": "d2",
                                  "start": {"date": "2027-02-08"}, "end": {"date": "2027-02-09"},
                                  "originalStartTime": {"date": "2027-02-07"}})
    res.check("вхождение серии «весь день»: ключ по исходной дате", (series_day.key, series_day.moved),
              (ics.occurrence_key("d2@google.com", date(2027, 2, 7)), True))
    gone = gapi.occurrence({**single, "status": "cancelled"})
    d = gimport.convert(gone, tz=TZ, now=now, doctors={})
    res.check("отменённое — «omis» со словом отмены, как у файла", (gone.status, d.kind, d.why),
              (ics.CANCELLED, gimport.SKIPPED, gimport.CANCELLED))

    probs = [
        ({"start": single["start"]}, ("", ics.NO_UID)),
        ({**single, "start": {"dateTime": "завтра"}}, ("u1@google.com", ics.BAD_DATE)),
        ({**single, "start": {"dateTime": "2027-02-30T10:00:00+02:00"}}, ("u1@google.com", ics.BAD_DATE)),
        ({**single, "start": {}}, ("u1@google.com", ics.NO_START)),
        ({**single, "end": {"date": "2027-02-02"}}, ("u1@google.com", ics.BAD_DATE)),
        ({**inst, "originalStartTime": {"dateTime": "2027-02-01T22:30:00Z", "timeZone": "Mars/Base"}},
         ("s1@google.com", ics.UNKNOWN_TZ)),
    ]
    res.check("не разобранное — Occurrence с кодом ics, не исключение и не пропажа",
              [(o.key, o.problem) for o in (gapi.occurrence(ev) for ev, _ in probs)], [want for _, want in probs])
    occ = gapi.occurrences([single, single, inst])
    res.check("повтор ключа — dup_key у второго", [o.problem for o in occ], ["", ics.DUP_KEY, ""])


# ---------- один календарь файлом и через API ----------


def _monday_after(day: date) -> date:
    return day + timedelta(days=7 - day.weekday())


def _google_pair(now: datetime) -> tuple[bytes, list, dict]:
    """Проверочный календарь «DentPilot test» из инструкции консоли в двух видах: выгрузка .ics, как её пишет
    Google, и ответ events.list с singleEvents=true. Серия по понедельникам 6 раз: третье вхождение
    перенесено на вторник 12:00, четвёртое удалено; одиночное и «весь день»."""
    d0 = _monday_after(now.date() + timedelta(days=7))
    days = [d0 + timedelta(weeks=i) for i in range(6)]
    single, allday = d0 + timedelta(days=2), d0 + timedelta(days=3)
    moved_to = days[2] + timedelta(days=1)
    f = "%Y%m%d"
    ics_text = "\r\n".join([
        "BEGIN:VCALENDAR", "PRODID:-//Google Inc//Google Calendar 70.9054//EN", "VERSION:2.0",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:DentPilot test", "X-WR-TIMEZONE:Europe/Chisinau",
        "BEGIN:VTIMEZONE", "TZID:Europe/Chisinau", "X-LIC-LOCATION:Europe/Chisinau",
        "BEGIN:STANDARD", "TZOFFSETFROM:+0300", "TZOFFSETTO:+0200", "TZNAME:EET", "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD", "END:VTIMEZONE",
        "BEGIN:VEVENT", f"DTSTART;TZID=Europe/Chisinau:{d0:{f}}T100000",
        f"DTEND;TZID=Europe/Chisinau:{d0:{f}}T103000", "RRULE:FREQ=WEEKLY;WKST=MO;COUNT=6;BYDAY=MO",
        f"EXDATE;TZID=Europe/Chisinau:{days[3]:{f}}T100000", "DTSTAMP:20261121T120000Z",
        "UID:serie1@google.com", "SUMMARY:Test serie", "STATUS:CONFIRMED", "END:VEVENT",
        "BEGIN:VEVENT", f"DTSTART;TZID=Europe/Chisinau:{moved_to:{f}}T120000",
        f"DTEND;TZID=Europe/Chisinau:{moved_to:{f}}T123000", "DTSTAMP:20261121T120000Z",
        "UID:serie1@google.com", f"RECURRENCE-ID;TZID=Europe/Chisinau:{days[2]:{f}}T100000",
        "SUMMARY:Test serie", "STATUS:CONFIRMED", "END:VEVENT",
        "BEGIN:VEVENT", f"DTSTART:{single:{f}}T091500Z", f"DTEND:{single:{f}}T100000Z",
        "DTSTAMP:20261121T120000Z", "UID:unic1@google.com", "SUMMARY:Test unic", "STATUS:CONFIRMED", "END:VEVENT",
        "BEGIN:VEVENT", f"DTSTART;VALUE=DATE:{allday:{f}}", f"DTEND;VALUE=DATE:{allday + timedelta(days=1):{f}}",
        "DTSTAMP:20261121T120000Z", "UID:zi1@google.com", "SUMMARY:Test zi întreagă", "END:VEVENT",
        "END:VCALENDAR", ""])

    def at(day: date, h: int, m: int = 0) -> str:
        return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ).isoformat()

    def inst(day: date, start: str, end: str) -> dict:
        return {"id": f"serie1_{day:{f}}T080000Z", "iCalUID": "serie1@google.com", "status": "confirmed",
                "summary": "Test serie", "recurringEventId": "serie1",
                "start": {"dateTime": start, "timeZone": "Europe/Chisinau"},
                "end": {"dateTime": end, "timeZone": "Europe/Chisinau"},
                "originalStartTime": {"dateTime": at(day, 10), "timeZone": "Europe/Chisinau"}}

    items = [inst(day, at(day, 10), at(day, 10, 30)) for day in days if day not in (days[2], days[3])]
    items.insert(2, inst(days[2], at(moved_to, 12), at(moved_to, 12, 30)))
    items += [{"id": "unic1", "iCalUID": "unic1@google.com", "status": "confirmed", "summary": "Test unic",
               "start": {"dateTime": f"{single.isoformat()}T09:15:00Z"}, "end": {"dateTime": f"{single.isoformat()}T10:00:00Z"}},
              {"id": "zi1", "iCalUID": "zi1@google.com", "status": "confirmed", "summary": "Test zi întreagă",
               "start": {"date": allday.isoformat()}, "end": {"date": (allday + timedelta(days=1)).isoformat()}}]
    return ics_text.encode("utf-8"), items, {"moved": ics.occurrence_key("serie1@google.com", days[2]),
                                             "deleted": ics.occurrence_key("serie1@google.com", days[3])}


def _view(o: ics.Occurrence) -> tuple:
    """Что читает дальше импорт; из статуса — только «отменено» (CONFIRMED у файла пишется не всегда)."""
    return (o.start.astimezone(timezone.utc) if o.start else None, o.minutes, o.day, o.title,
            o.series, o.moved, o.status == ics.CANCELLED, o.problem)


def suite_parity(res: Result) -> None:
    now = clinic_now()
    raw, items, marks = _google_pair(now)
    (cal,) = ics.read(raw, TZ)
    lo, hi = t.window(now, 365)
    by_file = {o.key: o for o in ics.occurrences(cal, lo, hi)}
    by_api = {o.key: o for o in gapi.occurrences(items, "Europe/Chisinau")}
    res.check("файл и API: тот же набор ключей", sorted(by_api), sorted(by_file))
    res.ok("перенесённое — под ключом исходной даты, удалённого нет ни там, ни там",
           marks["moved"] in by_api and marks["deleted"] not in by_api and marks["deleted"] not in by_file,
           str(sorted(by_api)))
    res.check("файл и API: время, длина, дата, название, пометки — одинаковы",
              {k: _view(o) for k, o in by_api.items()}, {k: _view(o) for k, o in by_file.items() if k in by_api})
    stamp = {}
    for side, got in (("file", by_file), ("api", by_api)):
        stamp[side] = {d.key: (d.kind, d.why, d.stamp) for d in
                       (gimport.convert(o, tz=TZ, now=now, doctors={}) for o in got.values())}
    res.check("файл и API: одинаковые заготовки и отпечатки — подключение не пометит «schimbat»",
              stamp["api"], stamp["file"])

    # Серия в 00:30 через перевод часов (буквальные даты; окно развёртки — аргументом): по UTC это
    # ещё вчера, и ключ обязан взять дату по поясу серии; 00:30 остаётся 00:30.
    text = "\r\n".join(["BEGIN:VCALENDAR", "X-WR-TIMEZONE:Europe/Chisinau", "BEGIN:VEVENT",
                        "DTSTART;TZID=Europe/Chisinau:20270326T003000", "DTEND;TZID=Europe/Chisinau:20270326T011500",
                        "RRULE:FREQ=DAILY;COUNT=5", "UID:dst@google.com", "SUMMARY:Control", "END:VEVENT",
                        "END:VCALENDAR", ""]).encode("utf-8")
    (cal,) = ics.read(text, TZ)
    file_dst = {o.key: _view(o) for o in ics.occurrences(cal, datetime(2027, 3, 20, tzinfo=TZ),
                                                          datetime(2027, 4, 5, tzinfo=TZ))}
    api_dst = []
    for i in range(5):
        day = date(2027, 3, 26) + timedelta(days=i)
        start = datetime(day.year, day.month, day.day, 0, 30, tzinfo=TZ)
        api_dst.append({"iCalUID": "dst@google.com", "recurringEventId": "dst", "summary": "Control",
                        "status": "confirmed",
                        "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Chisinau"},
                        "end": {"dateTime": (start + timedelta(minutes=45)).isoformat(), "timeZone": "Europe/Chisinau"},
                        "originalStartTime": {"dateTime": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                                              "timeZone": "Europe/Chisinau"}})
    res.check("перевод часов: ключи и время серии совпадают с файлом",
              {o.key: _view(o) for o in gapi.occurrences(api_dst)}, file_dst)


# ---------- клиент Google: сборка и окружение ----------


def suite_client(res: Result) -> None:
    """Откуда программа берёт client_id: в exe — константа сборки, вне exe — файл по переменной;
    демо и сервер переменной не имеют — клиента нет."""
    spec = importlib.util.spec_from_file_location("embed_gclient", ROOT / "scripts" / "embed_gclient.py")
    eg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eg)
    good = json.dumps({"installed": {"client_id": CLIENT.id, "client_secret": "GOCSPX-test"}})
    keep_env, keep_built, keep_out = os.environ.get(gclient.ENV), gclient.gclient_build, eg.OUT
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "good.json").write_text(good, encoding="utf-8")
        (d / "web.json").write_text(json.dumps({"web": {"client_id": CLIENT.id}}), encoding="utf-8")
        try:
            os.environ.pop(gclient.ENV, None)
            res.check("демо и сервер: переменной нет — клиента нет", gclient.client(), None)
            os.environ[gclient.ENV] = ""
            res.check("переменная пустая — клиента нет", gclient.client(), None)
            os.environ[gclient.ENV] = str(d / "good.json")
            res.check("вне exe: JSON консоли по переменной", gclient.client(), gauth.Client(CLIENT.id, "GOCSPX-test"))
            res.check("вне exe: нет файла, web-клиент — клиента нет",
                      [gclient.client_from(False, str(d / x)) for x in ("nope.json", "web.json")], [None, None])
            gclient.gclient_build = None
            res.check("exe без константы — клиента нет, переменная не читается",
                      gclient.client_from(True, str(d / "good.json")), None)

            res.check("сборка: годный файл — configured", eg.embed(d / "good.json", d / "b1.py"), True)
            res.check("сборка: нет файла, web-клиент — не настроено",
                      [eg.embed(d / x, d / f"b{i}.py") for i, x in enumerate(("nope.json", "web.json"), 2)],
                      [False, False])
            raw = (d / "b1.py").read_bytes()
            built = {}
            exec(compile(raw, "gclient_build.py", "exec"), built)
            res.ok("сборка: модуль без BOM и читается Python", not raw.startswith(b"\xef\xbb\xbf") and "CLIENT" in built)
            gclient.gclient_build = types.SimpleNamespace(CLIENT=built["CLIENT"])
            res.check("exe: клиент из константы сборки", gclient.client_from(True, ""), gauth.Client(CLIENT.id, "GOCSPX-test"))
            empty = {}
            exec(compile((d / "b2.py").read_bytes(), "gclient_build.py", "exec"), empty)
            gclient.gclient_build = types.SimpleNamespace(CLIENT=empty["CLIENT"])
            res.check("exe: константа без клиента — не настроено", gclient.client_from(True, ""), None)

            out = []
            for arg in (d / "good.json", d / "nope.json"):
                eg.OUT = d / "main.py"
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = eg.main([str(arg)])
                out.append((code, buf.getvalue()))
            res.check("сборка: одна строка итога, сборка не падает", out,
                      [(0, eg.CONFIGURED + "\n"), (0, eg.MISSING + "\n")])
            res.ok("сборка: ни id клиента, ни секрета в выводе",
                   not any(CLIENT.id in s or "GOCSPX" in s for _, s in out), str(out))
        finally:
            eg.OUT, gclient.gclient_build = keep_out, keep_built
            if keep_env is None:
                os.environ.pop(gclient.ENV, None)
            else:
                os.environ[gclient.ENV] = keep_env

    rel = "bot/app/core/gclient_build.py"
    ignored = rel in _ignore((ROOT / ".gitignore").read_text(encoding="utf-8"))
    tracked = subprocess.run(["git", "ls-files", "--", rel], cwd=ROOT, capture_output=True, text=True)
    res.ok("сгенерированный модуль — в .gitignore и не отслеживается git",
           ignored and tracked.returncode == 0 and not tracked.stdout.strip(), f"{ignored} {tracked.stdout!r}")
    build = (ROOT / "Build-Engine.ps1").read_text(encoding="utf-8")
    at, pyi = build.find(r"scripts\embed_gclient.py"), build.find("-m PyInstaller")
    res.ok("Build-Engine.ps1 встраивает клиента до PyInstaller", 0 < at < pyi, f"{at} {pyi}")
    res.ok("Build-Engine.ps1 — только ASCII (PowerShell 5.1 читает файл в ANSI)", build.isascii())


def _ignore(text: str) -> set:
    return {ln.strip().lstrip("/") for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")}
