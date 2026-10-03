"""Сервер обновлений как первый источник (03.10): провод, решение `update._check`, живой сервер.

Провод — `bot/app/update_server.py`: ответу сервера он не верит на слово, и это
главное, что здесь держится. Сервер может назвать один из настоящих выпусков, но
не подсунуть чужой файл (ссылка только на выпуск нашего репозитория с тем же
тегом), не откатить программу (версия только новее) и не протащить обрубок
(sha256 и размер). Что настоящий сервер и этот провод понимают друг друга —
cloud/tests/test_update.py: там провод грузится по пути и ходит в живой сервер.

Решение (`update._check`) проверяется в отдельном процессе с подменами: сеть и
GitHub там не нужны, а подмены не переживают проверку. Живой сервер программы —
со стендом вместо cloud.dentpilot.md: спрашивает при старте, показывает версию,
и НЕ спрашивает, пока харнесс держит `DENTART_UPDATE_CHECK=off`.
"""
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

from harness import BOT, PYTHON, Client, Result, Server

_spec = importlib.util.spec_from_file_location("update_server", BOT / "app" / "update_server.py")
us = importlib.util.module_from_spec(_spec)
sys.modules["update_server"] = us
_spec.loader.exec_module(us)

REPO = "olegbacalu-maker/dental-booking-bot"
DL = f"https://github.com/{REPO}/releases/download/"
SHA = "a" * 64


def _body(tag: str = "v9.9.9", **over) -> dict:
    v = tag[1:]
    b = {"ok": True, "tag": tag, "version": v, "prerelease": False,
         "page": f"https://github.com/{REPO}/releases/tag/{tag}",
         "exe": {"name": "DentPilot.exe", "url": f"{DL}{tag}/DentPilot.exe", "size": 35_000_000, "sha256": SHA},
         "setup": {"name": f"DentPilot-Setup-{v}.zip", "url": f"{DL}{tag}/DentPilot-Setup-{v}.zip",
                   "size": 38_000_000, "sha256": "b" * 64}}
    b.update(over)
    return b


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class Stand:
    """Стенд сервера обновлений: отвечает тем, что положили в `reply`, помнит вопросы."""

    def __init__(self):
        self.reply = {"status": 200, "body": _body()}
        self.asked: list[dict] = []
        stand = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                stand.asked.append({"path": u.path, "q": dict(urllib.parse.parse_qsl(u.query)),
                                    "agent": self.headers.get("User-Agent", ""),
                                    "device": self.headers.get("X-DentPilot-Device", "")})
                r = stand.reply
                if u.path != "/v1/update":
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if r["status"] in (301, 302):
                    self.send_response(r["status"])
                    self.send_header("Location", "https://evil.example/v1/update")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = b"" if r["status"] == 204 else (r["body"] if isinstance(r["body"], bytes)
                                                       else json.dumps(r["body"]).encode())
                self.send_response(r["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if data:
                    self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


# ---------- провод ----------


def suite_wire(res: Result) -> None:
    """`update_server.check` отбраковывает всё, кроме выпуска нашего репозитория новее стоящего."""
    ok = us.check(_body(), REPO, "1.36.2")
    res.ok("годный ответ: тег, версия, оба файла, страница",
           ok and ok["version"] == "9.9.9" and ok["exe"]["sha256"] == SHA and ok["setup"] is not None, repr(ok))
    bad = {
        "ok не true": _body(ok=False),
        "версия не новее стоящей": _body("v1.36.2", version="1.36.2"),
        "версия старее стоящей (откат)": _body("v1.0.0"),
        "тег без «v»": dict(_body(), tag="9.9.9"),
        "ни одного годного файла": _body(exe=None, setup=None),
    }
    for name, b in bad.items():
        res.check(f"отброшено: {name}", us.check(b, REPO, "1.36.2"), None)
    exe = dict(_body()["exe"])
    files = {
        "ссылка на чужой хост": dict(exe, url="https://evil.example/DentPilot.exe"),
        "ссылка на чужой репозиторий": dict(exe, url=f"https://github.com/x/y/releases/download/v9.9.9/DentPilot.exe"),
        "ссылка на другой тег": dict(exe, url=f"{DL}v1.0.0/DentPilot.exe"),
        "другое имя файла": dict(exe, name="DentPilot-Setup-9.9.9.exe"),
        "sha256 не 64 знака": dict(exe, sha256="abc"),
        "размер обрубка": dict(exe, size=1000),
        "размер строкой": dict(exe, size="35000000"),
        "размер логическим": dict(exe, size=True),
    }
    for name, a in files.items():
        got = us.check(_body(exe=a), REPO, "1.36.2")
        res.ok(f"файл отброшен: {name}", got is not None and got["exe"] is None, repr(got))
    got = us.check(_body(page="https://evil.example/"), REPO, "1.36.2")
    res.check("страница не нашего репозитория — подставлена своя",
              got["page"], f"https://github.com/{REPO}/releases/tag/v9.9.9")

    stand = Stand()
    try:
        out, rel = us.ask(stand.base, "beta", "1.36.2", REPO, timeout=5, agent="DentPilot/1.36.2",
                          extra={"X-DentPilot-Device": "d_0a1b2c3d4e5f"})
        res.ok("ask: NEWER и проверенный выпуск", out == us.NEWER and rel["version"] == "9.9.9", repr((out, rel)))
        q = stand.asked[-1]
        res.ok("вопрос: канал, стоящая версия, программа называет себя",
               q["path"] == "/v1/update" and q["q"] == {"channel": "beta", "current": "1.36.2"}
               and q["agent"] == "DentPilot/1.36.2" and q["device"] == "d_0a1b2c3d4e5f", repr(q))
        for status, body, want, name in ((204, None, us.SAME, "204 — SAME"),
                                         (503, {"ok": False}, us.OFFLINE, "503 — OFFLINE"),
                                         (302, None, us.OFFLINE, "редирект не исполняется — OFFLINE"),
                                         (200, b"{oops", us.OFFLINE, "не JSON — OFFLINE"),
                                         (200, b"x" * (us.MAX_BODY + 10), us.OFFLINE, "тело сверх потолка — OFFLINE"),
                                         (200, _body(exe=None, setup=None), us.OFFLINE,
                                          "ответ не прошёл проверку — OFFLINE, как будто сервера нет")):
            stand.reply = {"status": status, "body": body}
            res.check(f"ask: {name}", us.ask(stand.base, "stable", "1.36.2", REPO, timeout=5)[0], want)
        n = len(stand.asked)
        stand.reply = {"status": 302, "body": None}
        us.ask(stand.base, "stable", "1.36.2", REPO, timeout=5)
        res.check("за редиректом не ходили (вопрос один)", len(stand.asked), n + 1)
    finally:
        stand.close()
    res.check("сервера нет — OFFLINE", us.ask(stand.base, "stable", "1.36.2", REPO, timeout=2)[0], us.OFFLINE)


# ---------- решение update._check ----------

_CODE = r'''
import json, os, sys
sys.path.insert(0, r"%s")
os.environ.pop("DENTART_FAKE_UPDATE_URL", None)
os.environ.pop("DENTART_UPDATE_TOKEN", None)
os.environ.pop("DENTART_CHANNEL", None)
from app import engine as eng
from app import update as upd
from app import update_server as us
import threading

class _NoTimer:
    def __init__(self, *a, **kw): pass
    def start(self): pass
    def cancel(self): pass
threading.Timer = _NoTimer
out = {}
asked, api = [], []
reply = {"v": None}
def fake_ask(server, ch, current, repo, **kw):
    asked.append({"ch": ch, "current": current, "repo": repo, "agent": kw.get("agent", ""),
                  "device": (kw.get("extra") or {}).get("X-DentPilot-Device", "")})
    r = reply["v"]
    if isinstance(r, Exception):
        raise r
    return r
def fake_api(path):
    api.append(path)
    if path == "/releases/latest":
        return {"tag_name": "v8.8.8", "html_url": "u", "assets": [
            {"name": "DentPilot.exe", "browser_download_url": "https://github.com/x/e", "size": 33000000,
             "state": "uploaded", "digest": "sha256:" + "c" * 64}]}
    if path.startswith("/releases?"):
        return []
    raise AssertionError(path)
us.ask = fake_ask
upd._api = fake_api
upd._web_fallback = lambda ch: None
upd._newest_tag_atom = lambda: ""
upd._releases_graphql = lambda: []
rel = {"tag": "v9.9.9", "version": "9.9.9", "prerelease": True, "page": "https://github.com/p",
       "exe": {"name": "DentPilot.exe", "url": "https://github.com/e", "size": 35000000, "sha256": "a" * 64},
       "setup": None}

def run(name):
    del asked[:], api[:]
    upd.STATE.update(latest="", asset_url="", asset_size=0, asset_digest="", error="")
    upd._check()
    out[name] = {"latest": upd.STATE["latest"], "asset_url": upd.STATE["asset_url"],
                 "size": upd.STATE["asset_size"], "digest": upd.STATE["asset_digest"],
                 "pre": upd.STATE["prerelease"], "channel": upd.STATE["channel"],
                 "newer": upd.newer_available(), "asked": list(asked), "api": list(api)}

reply["v"] = (us.NEWER, rel); run("newer")
reply["v"] = (us.SAME, {}); run("same")
reply["v"] = (us.OFFLINE, {}); run("offline")
reply["v"] = RuntimeError("boom"); run("raised")
upd._beta = lambda: True
reply["v"] = (us.NEWER, rel); run("beta")
upd._beta = lambda: False
upd._token = lambda: "tok"
run("draft")
out["app_version"] = eng.APP_VERSION
print(json.dumps(out))
''' % str(BOT)


def suite_decision(res: Result) -> None:
    """Сервер — первым; его молчание — прежний путь к GitHub; черновики — мимо сервера."""
    with tempfile.TemporaryDirectory(prefix="dp_upds_") as work:
        p = subprocess.run([str(PYTHON), "-c", _CODE], cwd=str(BOT), text=True, capture_output=True,
                           env={**os.environ, "CLINIC_CONFIG": os.path.join(work, "clinic.json"),
                                "DENTART_LICENSE_SERVER": "http://127.0.0.1:9"})
    if p.returncode != 0:
        res.failed.append(("update._check: запуск", p.stderr[-800:]))
        return
    o = json.loads(p.stdout.strip().splitlines()[-1])
    v = o["app_version"]
    n = o["newer"]
    res.ok("сервер назвал новее: версия, ссылка, размер, sha256 — без единого вопроса GitHub",
           n["latest"] == "v9.9.9" and n["asset_url"] == "https://github.com/e" and n["size"] == 35000000
           and n["digest"] == "sha256:" + "a" * 64 and n["pre"] is True and n["newer"] and n["api"] == [], repr(n))
    a = n["asked"][0] if n["asked"] else {}
    res.ok("спросили: канал stable, стоящая версия, наш репозиторий, программа назвала себя",
           a.get("ch") == "stable" and a.get("current") == v and a.get("repo") == REPO
           and a.get("agent") == f"DentPilot/{v}" and a.get("device", "").startswith("d_"), repr(a))
    s = o["same"]
    res.ok("сервер: новее нет — «la zi», GitHub не спрашивали",
           s["latest"] == f"v{v}" and not s["newer"] and s["asset_url"] == "" and s["api"] == [], repr(s))
    f = o["offline"]
    res.ok("сервер молчит — прежний путь к GitHub", f["api"] == ["/releases/latest"] and f["latest"] == "v8.8.8",
           repr(f))
    r_ = o["raised"]
    res.ok("сервер упал исключением — проверка не падает, идёт к GitHub",
           r_["api"] == ["/releases/latest"] and r_["latest"] == "v8.8.8", repr(r_))
    b = o["beta"]
    res.ok("канарейка спрашивает канал beta", b["asked"] and b["asked"][0]["ch"] == "beta"
           and b["latest"] == "v9.9.9", repr(b))
    d = o["draft"]
    res.ok("черновики (токен разработчика) — мимо сервера: его не спрашивали",
           d["asked"] == [] and d["channel"] == "draft", repr(d))


# ---------- живой сервер программы ----------


def _hub_hint(c: Client) -> str:
    r = c.get("/api/settings/hub")
    tiles = json.loads(r.body).get("data", {}).get("tiles", []) if r.status == 200 else []
    sys_tile = next((t for t in tiles if t.get("href") == "/admin/settings/system"), {})
    return "".join(p.get("t", "") for p in sys_tile.get("hint", []))


def suite_live(res: Result) -> None:
    stand = Stand()
    try:
        with Server(env={"DENTART_UPDATE_CHECK": "", "DENTART_LICENSE_SERVER": stand.base}) as s:
            deadline = time.time() + 15
            while time.time() < deadline and not stand.asked:
                time.sleep(0.2)
            q = stand.asked[0] if stand.asked else {}
            res.ok("программа при старте спросила сервер обновлений: stable, своя версия, назвала себя",
                   q.get("path") == "/v1/update" and q.get("q", {}).get("channel") == "stable"
                   and q.get("agent", "").startswith("DentPilot/") and q.get("device", "").startswith("d_"),
                   repr(q))
            c = Client(s.url).login()
            res.ok("настройки показывают версию от сервера", "disponibilă v9.9.9" in _hub_hint(c), _hub_hint(c))
        n = len(stand.asked)
        with Server(env={"DENTART_LICENSE_SERVER": stand.base}) as s:
            Client(s.url).login().get("/admin")
            time.sleep(2)
            res.check("харнесс по умолчанию проверку выключает — сервер не спрошен", len(stand.asked), n)
    finally:
        stand.close()
