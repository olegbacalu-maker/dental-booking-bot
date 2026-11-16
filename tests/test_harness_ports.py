"""Порт сервера прогона — один на машину (`harness.free_port`).

Части `.\\dev test` идут разом, и каждая поднимает свои серверы. Windows
пускает второго слушателя на занятый порт, и запросы уходят тому, чей адрес
точнее: две части с одним номером говорили бы с чужим сервером и чужой базой,
не краснея. Здесь — что номер не достаётся двоим ни при какой гонке, что
занятый кем-то порт не выдаётся, и что сервер, на чей порт ответил чужак,
не стартует молча.
"""
from __future__ import annotations

import http.server
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import harness  # noqa: E402
from harness import PYTHON, Result, Server, _rmtree_settled  # noqa: E402

TESTS = pathlib.Path(__file__).resolve().parent

# Рабочий: ждёт общего сигнала и берёт `n` портов, НАЧИНАЯ С ОДНОГО И ТОГО ЖЕ
# номера, что и все остальные, — так гонка за номер идёт на каждом шаге.
_TAKER = r"""
import os, pathlib, sys, time
sys.path.insert(0, sys.argv[1])
import harness
go, start, n = pathlib.Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
while not go.exists():
    time.sleep(0.005)
harness._port_next = start - harness.PORT_LO
print(" ".join(str(harness.free_port()) for _ in range(n)), flush=True)
sys.stdin.read()              # держать брони, пока родитель не сверит
"""

# Рабочий: бронирует ровно `port` и держит, пока не закроют stdin.
_HOLDER = r"""
import sys
sys.path.insert(0, sys.argv[1])
import harness
print("ok" if harness._lease(int(sys.argv[2])) else "busy", flush=True)
sys.stdin.read()
"""


def _start(code: str, *args) -> subprocess.Popen:
    return subprocess.Popen([str(PYTHON), "-c", code, str(TESTS), *map(str, args)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def _end(p: subprocess.Popen) -> None:
    try:
        p.stdin.close()
        p.wait(timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        p.kill()
        p.wait()


def _from(port: int) -> int:
    """Следующий `free_port()` этого процесса начнёт обход с `port`."""
    harness._port_next = port - harness.PORT_LO
    return port


def _quiet_port() -> int:
    """Номер в диапазоне, который сейчас никем не занят и не забронирован, —
    для проверок, которые сами его займут. Бронь сразу снимается."""
    p = harness.free_port()
    harness.release_port(p)
    return p


def suite_ports(res: Result) -> None:
    if os.name != "nt":
        res.ok("не Windows — порты проверяются только там", True, "")
        return
    res.ok("диапазон ниже динамических портов Windows",
           harness.PORT_HI <= 49152 and harness.PORT_LO >= 1024,
           f"{harness.PORT_LO}–{harness.PORT_HI}")

    # 1. Гонка: 8 процессов разом, все с одного номера, по 25 портов — ни
    # одного номера дважды. Без брони каждый взял бы тот же первый порт.
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_ports_"))
    go = tmp / "go"
    start = _quiet_port()
    takers = [_start(_TAKER, go, start, 25) for _ in range(8)]
    try:
        time.sleep(1.5)                     # все импортировали харнесс и ждут
        go.write_text("go", encoding="utf-8")
        got = [list(map(int, t.stdout.readline().split())) for t in takers]
        flat = [p for g in got for p in g]
        res.check("гонка: каждый рабочий получил 25 портов", [len(g) for g in got], [25] * 8)
        res.check("гонка: ни один номер не достался двоим", len(flat), len(set(flat)))
        res.ok("гонка: все номера в своём диапазоне",
               all(harness.PORT_LO <= p < harness.PORT_HI for p in flat), str(flat[:5]))
        # пока рабочие держат брони, этот процесс их номеров не получит
        _from(start)
        mine = [harness.free_port() for _ in range(5)]
        res.ok("чужие брони обходятся и третьим процессом",
               not set(mine) & set(flat), f"{sorted(set(mine) & set(flat))}")
        for p in mine:
            harness.release_port(p)
    finally:
        for t in takers:
            _end(t)
        _rmtree_settled(tmp)

    # 2. Бронь живёт, пока жив владелец, и снимается его смертью.
    port = _quiet_port()
    holder = _start(_HOLDER, port)
    try:
        res.check("бронь другого процесса взята", holder.stdout.readline().strip(), "ok")
        _from(port)
        p = harness.free_port()
        harness.release_port(p)
        res.ok("порт под чужой бронью не выдаётся, хотя сокетом свободен", p != port,
               f"выдан {p}")
    finally:
        _end(holder)
    _from(port)
    p = harness.free_port()
    harness.release_port(p)
    res.check("умер владелец — бронь снята сама", p, port)

    # 3. Порт, занятый не харнессом: обычный слушатель на 127.0.0.1 (как
    # uvicorn) и исключительный на 0.0.0.0 — оба не выдаются.
    for what, addr, excl in (("127.0.0.1, как uvicorn", "127.0.0.1", False),
                             ("0.0.0.0 исключительно", "0.0.0.0", True)):
        port = _quiet_port()
        s = socket.socket()
        try:
            if excl:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind((addr, port))
            s.listen()
            _from(port)
            p = harness.free_port()
            harness.release_port(p)
            res.ok(f"занятый слушателем на {what} не выдаётся", p != port, f"выдан {p}")
        finally:
            s.close()

    # 4. Сервер, на чей порт отвечает чужак, не стартует молча. Чужак — как
    # соседняя часть со своим сервером на том же номере: слушает 127.0.0.1 и
    # на /health отвечает 200. Наш uvicorn на этот номер не сядет, а опрос
    # старта получил бы «здоров» от чужого.
    class _Impostor(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status":"ok","app":"dentpilot"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    class _Plain(http.server.ThreadingHTTPServer):
        allow_reuse_address = False         # как uvicorn на Windows: без SO_REUSEADDR

    port = _quiet_port()
    imp = _Plain(("127.0.0.1", port), _Impostor)
    th = threading.Thread(target=imp.serve_forever, daemon=True)
    th.start()
    srv = Server()
    harness.release_port(srv.port)
    srv.port = port                         # то, что прежде выдал бы bind на 0
    try:
        why = ""
        try:
            with srv:
                pass
        except RuntimeError as e:
            why = str(e)
        res.ok("сервер на порту чужака не стартует", bool(why), "стартовал молча")
        res.ok("и называет причину: чужой слушатель или упал на bind",
               "чужой процесс" in why or "упал при старте" in why, why[:300])
    finally:
        imp.shutdown()
        imp.server_close()

    # 5. Свой сервер — свой: проверка «чей порт» не краснеет на нашем.
    with Server() as s:
        res.check("у живого сервера набора чужих слушателей нет",
                  harness._foreign_listeners(s.port, s._job), set())
        other = socket.socket()
        try:
            op = _quiet_port()
            other.bind(("127.0.0.1", op))
            other.listen()
            res.check("слушатель вне задания сервера — чужой",
                      harness._foreign_listeners(op, s._job), {os.getpid()})
        finally:
            other.close()
