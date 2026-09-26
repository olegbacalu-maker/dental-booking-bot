# -*- coding: utf-8 -*-
"""Доступ из сети: что Windows ДЕЙСТВИТЕЛЬНО пустит и кто уже дошёл (26.09).

Поймано на машине Олега после переезда в `Program Files`: страница «Acces din
rețea» спрашивала правило брандмауэра по ИМЕНИ, и правило «dentpilot» на
СТАРЫЙ путь exe засчитывалось новому — у клиники со старой раскладкой это
«всё в порядке» при закрытом входе и без кнопки починки. Запрет, который
Windows ставит, пока её окно ждёт ответа, не был виден вовсе.

⚠️ Настоящий UAC и настоящий телефон прогон не предъявит. Здесь проверяется:
вердикт по правилам (чистая функция на образцах), что правило с НАШИМ именем
на ЧУЖОЙ путь не засчитывается (живой вызов PowerShell на Windows), и что
приход из сети действительно записывается приложением (ASGI с адресом
клиента из сети — uvicorn в прогоне слушает только 127.0.0.1).
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app.modules.settings import netcheck  # noqa: E402
from harness import BOT, FIXTURES, PYTHON, Result  # noqa: E402

ON = [True, True, True]
OPEN = [False, False, False]


def _st(rules, category="Public", on=ON, shut=OPEN) -> dict:
    return {"rules": rules, "category": category, "network": "Clinica",
            "on": list(on), "shut": list(shut)}


def _r(action, profiles, proto=6, enabled=True) -> dict:
    return {"a": action, "p": profiles, "t": proto, "e": enabled}


A, B = netcheck.ALLOW, netcheck.BLOCK
PUB, PRIV, DOM, ALL = 4, 2, 1, 2147483647


def suite_verdict(res: Result) -> None:
    """Вердикт по правилам ЭТОГО exe и типу сети адреса для телефона."""
    v = netcheck.verdict
    res.check("правил нет — не пустят", v(_st([])), "missing")
    res.check("разрешение в публичной сети, сеть публичная", v(_st([_r(A, PUB)])), "ok")
    # ровно то, что прежняя кнопка ставила (profile=private) на Wi-Fi, который
    # Windows по умолчанию называет «Public»
    res.check("разрешение только частной сети, сеть публичная",
              v(_st([_r(A, PRIV)])), "missing")
    res.check("разрешение только UDP не пускает HTTP",
              v(_st([_r(A, ALL, proto=17)], "Private")), "missing")
    res.check("любой протокол во всех профилях", v(_st([_r(A, ALL, proto=256)], "Private")), "ok")
    res.check("выключенное разрешение не считается", v(_st([_r(A, PUB, enabled=False)])), "missing")
    # окно Windows: запрет, пока ждёт ответа, и после «Отмена»
    res.check("запрет сильнее разрешения", v(_st([_r(B, PUB), _r(A, PUB)])), "blocked")
    res.check("запрет ДРУГОЙ сети не мешает",
              v(_st([_r(B, PRIV), _r(A, PUB)])), "ok")
    res.check("брандмауэр этой сети выключен — пускают без правил",
              v(_st([], on=[True, True, False])), "ok")
    res.check("«блокировать все входящие» — не правило, кнопкой не лечится",
              v(_st([_r(A, PUB)], shut=[False, False, True])), "shut")
    res.check("тип сети неизвестен — разрешение засчитывается",
              v(_st([_r(A, PRIV)], category="")), "ok")
    res.check("тип сети неизвестен — запрет тоже", v(_st([_r(B, PRIV)], category="")), "blocked")
    res.check("доменная сеть", v(_st([_r(A, DOM)], "DomainAuthenticated")), "ok")


def suite_profiles(res: Result) -> None:
    """Профили нашего правила: публичная — только когда сеть клиники такая."""
    res.ok("публичная сеть клиники — разрешаем и публичную",
           "public" in netcheck.profiles_for("Public").split(","),
           netcheck.profiles_for("Public"))
    res.ok("частная сеть — публичную не открываем",
           "public" not in netcheck.profiles_for("Private").split(","),
           netcheck.profiles_for("Private"))
    res.ok("тип неизвестен — публичную не открываем",
           "public" not in netcheck.profiles_for("").split(","), netcheck.profiles_for(""))
    for cat in ("Public", "Private", ""):
        got = set(netcheck.profiles_for(cat).split(","))
        res.ok(f"частная и доменная всегда ({cat or 'неизвестно'})",
               {"private", "domain"} <= got, str(got))


def suite_peers(res: Result) -> None:
    """Кто пришёл из сети: свой компьютер не записывается, свежие сверху."""
    peers: dict = {}
    for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "", "testclient"):
        netcheck.note(peers, host, "Mozilla/5.0 (Linux; Android 13)", now=100.0)
    res.check("петля, пустой и не-адрес не записываются", peers, {})
    # браузер на САМОМ сервере по адресу для телефона: не петля, но брандмауэр
    # такое не фильтрует — засчитать его значило бы соврать про второе устройство
    netcheck.note(peers, "192.168.0.14", "Edg/128", now=100.0, own={"192.168.0.14"})
    res.check("свой адрес в сети не записывается", peers, {})
    netcheck.note(peers, "192.168.0.23", "Mozilla/5.0 (Linux; Android 13; SM-X200) "
                  "AppleWebKit/537.36 Chrome/128 Safari/537.36", now=100.0)
    netcheck.note(peers, "192.168.0.31", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5)", now=150.0)
    res.check("два устройства", len(peers), 2)
    got = netcheck.lines(peers, now=160.0)
    res.check("свежие сверху, со словом устройства и давностью", got,
              ["192.168.0.31 — iPhone, acum 10 s",
               "192.168.0.23 — tabletă Android, acum 1 min"])
    netcheck.note(peers, "192.168.0.23", "Mozilla/5.0 (Linux; Android 13)", now=170.0)
    res.check("повторный приход обновляет строку, не множит", len(peers), 2)
    for i in range(40):
        netcheck.note(peers, f"10.0.0.{i}", "", now=200.0 + i)
    res.check("держим ограниченное число адресов", len(peers), netcheck._KEEP)
    res.ok("вытесняются самые старые", "10.0.0.39" in peers and "192.168.0.23" not in peers,
           str(sorted(peers)))

    d = netcheck.device_of
    res.check("телефон Android", d("Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari"),
              "telefon Android")
    res.check("планшет Android", d("Mozilla/5.0 (Linux; Android 13; SM-X200) Safari"),
              "tabletă Android")
    res.check("iPad", d("Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)"), "iPad")
    res.check("Windows", d("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/128"),
              "calculator Windows")
    res.check("Mac (iPad в режиме компьютера так же)",
              d("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"), "Mac sau iPad")
    res.check("давность в часах", netcheck.ago(7300), "acum 2 h")


def suite_probe(res: Result) -> None:
    """Живой PowerShell: правила ищутся по ПУТИ, а не по имени."""
    if os.name != "nt":
        res.ok("не Windows — брандмауэр не спрашивается (probe → None)",
               netcheck.probe(r"C:\x\DentPilot.exe") is None, "")
        return
    # Контроль: есть ли на машине правило с НАШИМ именем. Если есть, прежняя
    # проверка по имени ответила бы здесь «всё в порядке» — ради этого случая
    # набор и написан. Без него утверждение ниже верно и по старой логике,
    # поэтому говорим ВСЛУХ, какой случай проверен.
    named = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule",
                            "name=DentPilot"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    st = netcheck.probe(r"C:\DentPilot-nu-exista\DentPilot.exe")
    if not res.ok("PowerShell ответил", st is not None, "probe вернул None на Windows"):
        return
    res.check("у несуществующего exe правил нет", st["rules"], [])
    label = ("правило с именем DentPilot на этой машине ЕСТЬ, и оно не засчитано"
             if named.returncode == 0 else
             "правила с именем DentPilot на этой машине нет (контроль слабее)")
    res.check(label, netcheck.verdict(st), "missing")
    res.ok("три профиля в ответе", len(st["on"]) == 3 and len(st["shut"]) == 3,
           f"on={st['on']} shut={st['shut']}")


# ---------- приход из сети записывает само приложение ----------

def _worker_peers(tmpdir: str) -> None:
    """Живое приложение как ASGI: адрес клиента задаём сами."""
    import asyncio

    base = pathlib.Path(tmpdir)
    os.environ.update({
        "CLINIC_CONFIG": str(base / "clinic.json"),
        "DATABASE_URL": f"sqlite:///{base / 'dental.db'}",
        "ADMIN_KEY": "",
        "DENTART_NO_RESTART": "1",
        "TELEGRAM_TOKEN": "",
    })
    sys.path.insert(0, str(BOT))
    from app import db
    from app.main import app
    from app.modules.settings import lan

    # адреса «устройств» — из TEST-NET-2 (198.51.100.0/24): их нет ни у одной
    # настоящей машины, и прогон не спутает «планшет» со своим адресом в сети
    async def call(path: str, client_ip: str, ua: str) -> int:
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "GET", "scheme": "http", "path": path,
                 "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"192.168.0.14:8088"),
                             (b"user-agent", ua.encode())],
                 "client": (client_ip, 40000), "server": ("192.168.0.14", 8088)}
        got = {}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                got["status"] = msg["status"]

        await app(scope, receive, send)
        return got.get("status", 0)

    async def main() -> None:
        async with app.router.lifespan_context(app):
            try:
                print("local", await call("/admin/login", "127.0.0.1", "Edge"))
                print("after_local", len(lan._PEERS))
                print("lan", await call("/admin/login", "198.51.100.23",
                                        "Mozilla/5.0 (Linux; Android 13; SM-X200)"))
                print("static", await call("/health", "198.51.100.31", "curl"))
                print("peers", ";".join(sorted(lan._PEERS)) or "-")
                seen = netcheck.lines(lan._PEERS)
                print("line", seen[0].split(",")[0] if seen else "-")
            finally:
                if db._CONN is not None:
                    await db._CONN.close()

    asyncio.run(main())


def suite_peers_live(res: Result) -> None:
    """Проводка: запрос с устройства сети становится строкой страницы. Без неё
    «Verificarea legăturii» навсегда говорила бы «ничего не дошло» и слала
    клинику искать поломку в исправной сети — хуже, чем не говорить ничего."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_peers_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", base / "clinic.json")
        r = subprocess.run([str(PYTHON), str(pathlib.Path(__file__).resolve()),
                            "worker-peers", str(base)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120,
                           # строка страницы румынская (ă), а консоль — cp1251
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        got = dict(line.split(" ", 1) for line in (r.stdout or "").splitlines() if " " in line)
        if not res.ok("проба поднялась", r.returncode == 0,
                      f"rc={r.returncode}: {(r.stderr or '')[-1500:]}"):
            return
        # без PIN вход уводит на установку (303) — важно, что ответ есть,
        # а не какой: записывает приход промежуточный слой, до маршрута
        res.ok("запрос с этого компьютера отвечен", got.get("local") in ("200", "303"),
               f"код {got.get('local')!r}")
        res.check("и НЕ записан", got.get("after_local"), "0")
        res.ok("запрос из сети отвечен", got.get("lan") in ("200", "303"),
               f"код {got.get('lan')!r}")
        res.check("записан только журнальный запрос из сети", got.get("peers"),
                  "198.51.100.23")
        res.check("строка страницы называет устройство", got.get("line"),
                  "198.51.100.23 — tabletă Android")
    finally:
        shutil.rmtree(base, ignore_errors=True)


_WORKERS = {"worker-peers": _worker_peers}

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in _WORKERS:
        _WORKERS[sys.argv[1]](sys.argv[2])
    else:
        print("Это файл наборов. Запускать: python tests\\run_tests.py сеть")
        sys.exit(2)
