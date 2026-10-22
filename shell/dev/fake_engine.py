"""Подставной движок для опыта с оболочкой (только разработка).

Говорит с оболочкой по контракту § 2 (строки `DP1 …` в stdout, `stop` и
закрытый stdin), пока настоящий движок (`bot/desktop.py` в режиме
`DENTART_SHELL=tauri`) не научился сам. Подключается так:

    DENTPILOT_DEV_APP=<app>  DENTPILOT_DEV_ENGINE=<app>\\shell\\dev\\fake_engine.py

Режим — `DP_FAKE`:
  demo    (по умолчанию) свой маленький сервер: страница с выгрузками
          (attachment), печатью, `beforeunload`, `dpMenu/dpRun/dpCtx` как у
          слоя команд, кука входа, `/shell/notices` с токеном оболочки
  bridge  НАСТОЯЩИЙ движок программы ребёнком: `bot/desktop.py` в режиме
          `DENTART_SHELL=tauri`; его строки DP1 — оболочке как есть (и в свой
          журнал), слово оболочки — ему (экраны React, вход, «Exportă», копия
          базы — всё настоящее)
  fatal   этапы, затем `fatal` и выход 2
  busy    `busy` на адрес порта и выход 3 (порт должен обслуживать DentPilot)
  quit    как demo, через DP_FAKE_AFTER секунд — `quit` (как перед установщиком)
  crash   как demo, через DP_FAKE_AFTER секунд — выход 1 без слова
  hang    как demo, но `stop` не слушает (оболочка обязана снять задание)

Порт — `DENTART_PORT` (по умолчанию 8094; ⛔ 8088 — живая установка Олега),
папка данных — `DENTART_DATA_DIR`; `DP_FAKE_SESSION` = keep|clear,
`DP_FAKE_LAN` = 1, `DP_FAKE_COLOR` = #RRGGBB, `DP_FAKE_WARN` = текст слова `warn`. Свой журнал —
`<данные>\\fake-engine.log`.
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import subprocess
import sys
import threading
import time

MODE = os.environ.get("DP_FAKE", "demo")
PORT = int(os.environ.get("DENTART_PORT", "8094") or 8094)
if PORT == 8088:
    sys.exit("8088 - instalarea vie; alegeți alt port")
DATA = pathlib.Path(os.environ.get("DENTART_DATA_DIR") or
                    pathlib.Path(os.environ.get("TEMP", ".")) / "dentpilot-fake")
DATA.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ.get("DENTART_SHELL_TOKEN", "")
COLOR = os.environ.get("DP_FAKE_COLOR", "#0E9F8A")
AFTER = float(os.environ.get("DP_FAKE_AFTER", "8"))
LOG = DATA / "fake-engine.log"
T0 = time.monotonic()


def log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} +{time.monotonic() - T0:.2f}s pid={os.getpid()} {msg}\n")


def say(event: str, **kw) -> None:
    sys.stdout.write("DP1 " + json.dumps({"v": 1, "event": event, **kw}) + "\n")
    sys.stdout.flush()
    log(f"say {event} {kw}")


stopping = threading.Event()


def watch_stdin() -> None:
    """`stop` или закрытый stdin — честная остановка (у hang — мимо ушей)."""
    for line in sys.stdin:
        log(f"stdin: {line.strip()}")
        try:
            if json.loads(line).get("cmd") == "stop":
                break
        except ValueError:
            continue
    log("stdin: stop / EOF")
    if MODE != "hang":
        stopping.set()


PAGE = """<!doctype html><html lang="ro"><head><meta charset="utf-8"><title>DentPilot demo</title>
<style>:root{--teal:%(color)s}body{font:15px Segoe UI,sans-serif;margin:24px;color:#13201e}
a,button{margin:4px 6px 4px 0}code{background:#eef}</style></head><body>
<h2>Motor de probă (%(mode)s)</h2>
<p>Cookie: <code id="ck"></code> &middot; dpShell: <code id="sh"></code></p>
<p><a href="/files/raport.csv">Exportă (CSV)</a>
<a href="/files/copie.zip">Copie de rezervă (ZIP)</a>
<a href="/files/document.pdf">Document pacient (PDF)</a></p>
<p><button onclick="window.print()">Tipărește</button>
<button onclick="dpShell.send('win/zoomin')">Mărește</button>
<button onclick="dpShell.send('win/zoom0')">100%%</button>
<button onclick="dpShell.send('win/datafolder')">Dosarul cu date</button>
<a href="https://dentpilot.md" target="_blank" rel="noopener">Site (alt browser)</a>
<a href="http://127.0.0.1:%(other)d/">alt port 127.0.0.1</a></p>
<p><label><input id="dirty" type="checkbox"> formular nesalvat (beforeunload)</label>
<input placeholder="câmp pentru clic dreapta"></p>
<p id="log"></p>
<script>
document.getElementById('ck').textContent=document.cookie||'(nimic)';
document.getElementById('sh').textContent=window.dpShell?JSON.stringify(window.dpShell):'nu';
window.addEventListener('beforeunload',function(e){
  if(!document.getElementById('dirty').checked)return;
  fetch('/beforeunload',{method:'POST',keepalive:true});e.preventDefault();e.returnValue='';});
var L=function(t){document.getElementById('log').textContent+=' '+t;fetch('/ran?'+encodeURIComponent(t))};
window.dpMenu=function(id){var m={
  file:[{id:'act:newAppt',label:'Programare nouă…',accel:'Ctrl+N',enabled:true},{sep:true},
        {id:'act:print',label:'Tipărește…',accel:'Ctrl+P',enabled:true},
        {id:'act:export',label:'Exportă…',enabled:false},{sep:true},
        {id:'win:datafolder',label:'Deschide dosarul cu datele',enabled:true},
        {id:'win:quit',label:'Închide DentPilot complet…',enabled:true}],
  edit:[{id:'key:c',label:'Copiază',accel:'Ctrl+C',enabled:true},{id:'key:v',label:'Lipește',accel:'Ctrl+V',enabled:true}],
  view:[{id:'win:zoomin',label:'Mărește',accel:'Ctrl+=',enabled:true},{id:'win:fullscreen',label:'Ecran complet',accel:'F11',enabled:true}],
  go:[{id:'go:/admin?go=1',label:'Programări & azi',accel:'Ctrl+2',enabled:true}],
  help:[{id:'win:mail',label:'Scrie-ne o problemă',enabled:true},{id:'act:about',label:'Despre DentPilot',enabled:true}]};
  fetch('/ran?menu:'+id);return {v:1,items:m[id]||[]}};
window.dpRun=function(id){L(id);if(id.indexOf('go:')===0)location.assign(id.slice(3));if(id==='act:print')window.print()};
window.dpCtx=function(){return {v:1,color:'%(color)s',logged:true,title:'demo'}};
</script></body></html>"""


class Demo(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):  # noqa: D401 — журнал свой
        log("http " + (fmt % a))

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        log(f"POST {self.path}")
        self._send(204, b"", "text/plain")

    def do_GET(self):  # noqa: N802
        p = self.path
        if p == "/health":
            return self._send(200, json.dumps({"ok": True, "app": "dentpilot", "version": "0.0.0-fake"}).encode(),
                              "application/json")
        if p.startswith("/ran"):
            log(f"page ran {p}")
            return self._send(204, b"", "text/plain")
        if p == "/shell/notices":
            got = self.headers.get("X-DentPilot-Shell", "")
            if not TOKEN or got != TOKEN:
                log(f"notices refused (token {'ok' if got == TOKEN else 'wrong'})")
                return self._send(404, b"not found", "text/plain")
            items = [
                {"id": "update:9.9.9", "title": "DentPilot 9.9.9 este gata",
                 "body": "Actualizați în Setări › Sistem.", "open": "/admin?from=update"},
                {"id": "sms:30:ep1", "title": "Au rămas 30 de SMS",
                 "body": "Cumpărați un pachet nou în Setări › SMS.", "open": "/admin?from=sms"},
            ]
            log("notices served")
            return self._send(200, json.dumps({"v": 1, "items": items}).encode(), "application/json")
        if p.startswith("/files/"):
            name = p.rsplit("/", 1)[1]
            ctype = {"csv": "text/csv", "zip": "application/zip", "pdf": "application/pdf"}[name.rsplit(".", 1)[1]]
            body = (f"fisier de proba {name}\n" * 20).encode()
            return self._send(200, body, ctype, {"Content-Disposition": f'attachment; filename="{name}"'})
        if p.startswith("/admin") or p == "/":
            log(f"page {p} cookie={'yes' if 'dp_session' in (self.headers.get('Cookie') or '') else 'no'}")
            page = PAGE % {"color": COLOR, "mode": MODE, "other": PORT + 1}
            return self._send(200, page.encode(), "text/html; charset=utf-8",
                              {"Set-Cookie": "dp_session=demo; Path=/; HttpOnly; SameSite=Lax"
                               if "Cookie" not in self.headers else "X-Ok: 1"})
        self._send(404, b"not found", "text/plain")


def serve() -> http.server.ThreadingHTTPServer:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Demo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def stages() -> None:
    say("hello", version="0.0.0-fake", color=COLOR, pid=os.getpid())
    if os.environ.get("DP_FAKE_WARN"):
        say("warn", text=os.environ["DP_FAKE_WARN"])
    for text, pct, upto, pause in (("Se pregătește baza de date…", 16, 0, .6),
                                   ("Se face copia de rezervă…", 38, 0, .6),
                                   ("Se pornește registrul…", 55, 92, .8)):
        say("stage", text=text, pct=pct, upto=upto)
        time.sleep(pause)


def ready() -> None:
    say("ready", url=f"http://127.0.0.1:{PORT}/admin", port=PORT,
        session=os.environ.get("DP_FAKE_SESSION", "keep"), data=str(DATA),
        lan=os.environ.get("DP_FAKE_LAN") == "1")


def main() -> int:
    log(f"start mode={MODE} port={PORT} token={'yes' if TOKEN else 'no'} shell={os.environ.get('DENTART_SHELL')}")
    threading.Thread(target=watch_stdin, daemon=True).start()
    if MODE == "busy":
        say("busy", url=f"http://127.0.0.1:{PORT}/admin")
        return 3
    if MODE == "fatal":
        stages()
        say("fatal", text=f"DentPilot nu a putut porni: portul {PORT} este ocupat de alt program.",
            log=str(DATA / "data" / "dentpilot.log"))
        return 2
    if MODE == "bridge":
        return bridge()
    stages()
    srv = serve()
    ready()
    deadline = time.monotonic() + AFTER
    while not stopping.wait(0.2):
        if MODE in ("quit", "crash") and time.monotonic() > deadline:
            if MODE == "quit":
                say("quit", reason="update")
                stopping.wait(5)
                break
            log("crash: exit 1")
            os._exit(1)
    srv.shutdown()
    log("stopped: exit 0")
    return 0


def bridge() -> int:
    """Настоящий движок программы ребёнком: его DP1 — оболочке, её `stop` — ему.
    До 22.10.2026 ребёнок шёл браузерным режимом окна pywebview, и слова DP1
    говорил этот файл за него; браузерного режима больше нет."""
    app = pathlib.Path(__file__).resolve().parents[2]
    env = dict(os.environ, DENTART_SHELL="tauri", DENTART_DATA_DIR=str(DATA),
               DENTART_PORT=str(PORT), PYTHONUTF8="1")
    # ⚠️ демо-профиль клиники — копией, как у `.\\dev up`: лаунчер копирует
    # профиль, только если файла нет
    cfg = DATA / "clinic.json"
    if not cfg.exists():
        cfg.write_bytes((app / "bot" / "app" / "clinic.json").read_bytes())
    child = subprocess.Popen([sys.executable, str(app / "bot" / "desktop.py")], cwd=str(app / "bot"),
                             env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=open(DATA / "bridge-server.log", "a", encoding="utf-8"),  # noqa: SIM115
                             text=True, encoding="utf-8",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def relay() -> None:
        for line in child.stdout:
            line = line.rstrip("\n")
            if line.startswith("DP1 "):
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
                log(f"bridge: {line[:200]}")

    threading.Thread(target=relay, daemon=True).start()
    while not stopping.wait(0.3):
        if child.poll() is not None:
            log(f"bridge: engine exited {child.returncode}")
            return child.returncode
    try:
        child.stdin.write('{"v":1,"cmd":"stop"}\n')
        child.stdin.flush()
    except OSError:
        pass
    try:
        code = child.wait(10)
    except subprocess.TimeoutExpired:
        child.kill()
        code = 1
    log(f"bridge stopped: engine exit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
