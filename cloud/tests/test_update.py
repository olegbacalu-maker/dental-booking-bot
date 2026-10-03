"""Сервер обновлений (03.10): /v1/update отвечает программам, какая версия свежая для канала.

GitHub подменён стендом в процессе теста: нужны ответы, которых настоящий не даёт
по заказу (пре-релиз впереди, файл без sha256, чужая ссылка, GitHub лежит).
Провод программы (`bot/app/update_server.py`) грузится по пути и ходит в ЭТОТ
сервер — так держится договор двух сторон, как у `license_renew` (test_renew.py).
"""
import hashlib
import http.server
import json
import threading
import urllib.parse

from harness import ROOT, Client, Result, Server, load_by_path

us = load_by_path("update_server", ROOT / "bot" / "app" / "update_server.py")
REPO = "olegbacalu-maker/dental-booking-bot"
DL = f"https://github.com/{REPO}/releases/download/"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _release(tag: str, *, pre: bool = False, exe: bool = True, setup: bool = True,
             digest: bool = True, foreign: bool = False, state: str = "uploaded") -> dict:
    v = tag[1:]
    assets = []
    if exe:
        assets.append({"name": "DentPilot.exe", "state": state, "size": 35_336_416,
                       "digest": f"sha256:{_sha(tag + 'exe')}" if digest else None,
                       "browser_download_url": ("https://evil.example/DentPilot.exe" if foreign
                                                else f"{DL}{tag}/DentPilot.exe")})
    if setup:
        assets.append({"name": f"DentPilot-Setup-{v}.zip", "state": "uploaded", "size": 38_027_517,
                       "digest": f"sha256:{_sha(tag + 'setup')}",
                       "browser_download_url": f"{DL}{tag}/DentPilot-Setup-{v}.zip"})
    return {"tag_name": tag, "prerelease": pre, "draft": False,
            "html_url": f"https://github.com/{REPO}/releases/tag/{tag}", "assets": assets}


class _Quiet(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class FakeGitHub:
    """Стенд GitHub: /releases/latest, /releases/tags/{tag} и атом-фид, счётчик вопросов."""

    def __init__(self):
        self.latest = _release("v1.36.2")
        self.tags: dict[str, dict] = {"v1.36.2": self.latest}
        self.atom = ["v1.36.2", "v1.36.1"]
        self.down = False
        self.calls = 0
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.calls += 1
                if fake.down:
                    return self._send(503, b"")
                if self.path == "/releases/latest":
                    return self._send(200, json.dumps(fake.latest).encode())
                if self.path.startswith("/releases/tags/"):
                    tag = urllib.parse.unquote(self.path.rsplit("/", 1)[1])
                    rel = fake.tags.get(tag)
                    return self._send(200 if rel else 404, json.dumps(rel or {"message": "Not Found"}).encode())
                if self.path == "/releases.atom":
                    xml = "".join(f"<entry><link href='https://github.com/{REPO}/releases/tag/{t}'/></entry>"
                                  for t in fake.atom)
                    return self._send(200, f"<feed>{xml}</feed>".encode(), "application/atom+xml")
                self._send(404, b"{}")

            def log_message(self, *a):
                pass

        self.srv = _Quiet(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def env(self, ttl: int = 0) -> dict:
        return {"DP_RELEASES_API": self.base + "/releases/latest",
                "DP_RELEASES_TAG_API": self.base + "/releases/tags/{tag}",
                "DP_RELEASES_ATOM": self.base + "/releases.atom", "DP_UPDATE_CACHE_S": str(ttl)}

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def _ask(c: Client, channel: str, current: str):
    r = c.get(f"/v1/update?channel={channel}&current={current}")
    return r.status, (json.loads(r.body) if r.status == 200 and r.body else None)


def suite_update(res: Result) -> None:
    fake = FakeGitHub()
    try:
        with Server(env=fake.env()) as s:
            c = Client(s.url)
            st, body = _ask(c, "stable", "1.36.1")
            res.ok("stable, стоит 1.36.1: 200 — v1.36.2 с обоими файлами, ссылками на наш репозиторий и sha256",
                   st == 200 and body["version"] == "1.36.2" and body["prerelease"] is False
                   and body["exe"]["url"] == f"{DL}v1.36.2/DentPilot.exe"
                   and body["exe"]["sha256"] == _sha("v1.36.2exe") and body["exe"]["size"] == 35_336_416
                   and body["setup"]["url"] == f"{DL}v1.36.2/DentPilot-Setup-1.36.2.zip", repr(body))
            res.check("стоит та же версия — 204", _ask(c, "stable", "1.36.2")[0], 204)
            res.check("стоит новее — 204", _ask(c, "stable", "1.37.0")[0], 204)

            # пре-релиз впереди: видит только beta (и draft разработчика), stable — нет
            fake.tags["v1.37.0"] = _release("v1.37.0", pre=True)
            fake.atom.insert(0, "v1.37.0")
            st, body = _ask(c, "beta", "1.36.2")
            res.ok("beta: пре-релиз v1.37.0 из атом-фида и выпуска по тегу",
                   st == 200 and body["version"] == "1.37.0" and body["prerelease"] is True
                   and body["channel"] == "beta", repr(body))
            res.check("draft отвечает как beta", (_ask(c, "draft", "1.36.2")[1] or {}).get("version"), "1.37.0")
            res.check("stable пре-релиза не видит", _ask(c, "stable", "1.36.2")[0], 204)
            res.check("канал-мусор — как stable", _ask(c, "nonsense", "1.36.2")[0], 204)
            res.check("версия-мусор — как будто ничего не стоит: 200",
                      (_ask(c, "stable", "abc")[1] or {}).get("version"), "1.36.2")

            # файлы без sha256, чужая ссылка, недолитый — сервер их не пересказывает
            fake.latest = _release("v1.36.3", digest=False)
            res.check("файл без sha256 — exe отброшен, установщик остался",
                      ((b := _ask(c, "stable", "1.36.2")[1]) or {}).get("exe"), None)
            res.ok("…и установщик при этом на месте", b and b["setup"] is not None, repr(b))
            fake.latest = _release("v1.36.3", foreign=True)
            res.check("чужая ссылка — exe отброшен", (_ask(c, "stable", "1.36.2")[1] or {}).get("exe"), None)
            fake.latest = _release("v1.36.3", state="new")
            res.check("недолитый файл — exe отброшен", (_ask(c, "stable", "1.36.2")[1] or {}).get("exe"), None)

            # GitHub лёг: прежний ответ лучше молчания
            fake.latest = _release("v1.36.2")
            _ask(c, "stable", "1.36.1")
            fake.down = True
            st, body = _ask(c, "stable", "1.36.1")
            res.ok("GitHub лёг после удачи — отдаётся прежний ответ", st == 200 and body["version"] == "1.36.2",
                   repr((st, body)))
        with Server(env=fake.env()) as s:
            res.check("GitHub лежит с самого старта — 503, программа пойдёт к GitHub сама",
                      _ask(Client(s.url), "stable", "1.36.1")[0], 503)
        fake.down = False
        fake.latest = dict(_release("v1.36.3"), tag_name="1.36.3")
        with Server(env=fake.env()) as s:
            res.check("тег без «v» — выпуск не признан (ловушка веб-формы 08-06), 503",
                      _ask(Client(s.url), "stable", "1.36.1")[0], 503)
        fake.latest = _release("v1.36.2")

        # кэш: один вопрос к GitHub на канал за UPDATE_CACHE_S
        fake.down = False
        with Server(env=fake.env(ttl=300)) as s:
            c = Client(s.url)
            n = fake.calls
            for _ in range(5):
                _ask(c, "stable", "1.36.1")
            res.check("пять вопросов программ — один вопрос к GitHub", fake.calls - n, 1)

            # ⭐ договор: провод ПРОГРАММЫ против этого сервера
            out, rel = us.ask(s.url, "stable", "1.36.1", REPO, timeout=10, agent="DentPilot/1.36.1",
                              extra={"X-DentPilot-Device": "d_0a1b2c3d4e5f"})
            res.ok("провод программы: NEWER, проверенный выпуск с обоими файлами",
                   out == us.NEWER and rel["version"] == "1.36.2" and rel["exe"]["sha256"] == _sha("v1.36.2exe")
                   and rel["setup"]["name"] == "DentPilot-Setup-1.36.2.zip", repr((out, rel)))
            res.check("провод программы: та же версия — SAME", us.ask(s.url, "stable", "1.36.2", REPO, timeout=10),
                      (us.SAME, {}))
            res.check("провод программы с чужим репозиторием — ответ отброшен (ссылки не на его выпуски)",
                      us.ask(s.url, "stable", "1.36.1", "someone/else", timeout=10), (us.OFFLINE, {}))
    finally:
        fake.close()
    res.check("сервера нет — OFFLINE", us.ask("http://127.0.0.1:9", "stable", "1.36.1", REPO, timeout=2),
              (us.OFFLINE, {}))
