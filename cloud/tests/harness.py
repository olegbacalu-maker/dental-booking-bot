"""Каркас тестов сервера лицензий — тот же приём, что tests/harness.py движка.

Сервер поднимается на свободном порту со своей временной базой, тестовым
ключом из tests/fixtures/license/ (тем же, что знают тесты движка), сухим
прогоном почты в папку и коротким pbkdf2 у администратора. Стандартная
библиотека плюс `app.auth` самого сервера для хеша — второй формулы хеша
здесь нет намеренно.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLOUD = ROOT / "cloud"
FIX = ROOT / "tests" / "fixtures" / "license"
ADMIN_USER, ADMIN_PASS = "oleg", "test-parola-123"

sys.path.insert(0, str(CLOUD))
from app.auth import make_hash  # noqa: E402

ADMIN_HASH = make_hash(ADMIN_PASS, iters=1000)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    def __init__(self, env: dict | None = None):
        self.port = free_port()
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="dp_cloud_"))
        self.outbox = self.dir / "outbox"
        self.extra_env = env or {}
        self.env: dict = {}
        self.proc = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "Server":
        env = dict(os.environ)
        env.update({"DP_CLOUD_DB": str(self.dir / "cloud.db"),
                    "DP_LICENSE_KEY": str(FIX / "test-key.json"),
                    "DP_ADMIN_USER": ADMIN_USER, "DP_ADMIN_HASH": ADMIN_HASH,
                    "DP_SECRET": "test-secret", "DP_MAIL_OUTBOX": str(self.outbox),
                    "DP_SMTP_HOST": ""})
        # Как run-windows.ps1: на Windows без UTF-8 режима вывод в трубу и лог
        # идёт в cp1251 — румынские ă/ț роняют печать, а кириллица приходит
        # тесту не в той кодировке (25.09: 11 красных только на ПК).
        env["PYTHONUTF8"] = "1"
        env.update(self.extra_env)
        self.env = env      # то же окружение — для запуска задач как из cron
        self._log = (self.dir / "server.log").open("wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=str(CLOUD), env=env, stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.time() + 40
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("сервер упал при старте:\n" + self.log()[-2000:])
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=1):
                    return self
            except Exception:  # noqa: BLE001 — ещё не поднялся
                time.sleep(0.2)
        raise RuntimeError("сервер не ответил на /health за 40 секунд")

    def log(self) -> str:
        try:
            self._log.flush()
            return (self.dir / "server.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._log.close()
        for _ in range(10):
            try:
                shutil.rmtree(self.dir)
                break
            except OSError:
                time.sleep(0.3)


def _lower(headers) -> dict:
    """uvicorn шлёт имена заголовков строчными; тестам всё равно, в каком регистре."""
    return {k.lower(): v for k, v in headers.items()}


class Reply:
    def __init__(self, status: int, location: str, body: str, headers: dict):
        self.status, self.location, self.body, self.headers = status, location, body, headers


class Client:
    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect)

    def _do(self, path: str, data: bytes | None = None, headers: dict | None = None) -> Reply:
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with self.opener.open(req, timeout=30) as r:
                return Reply(r.status, r.headers.get("Location", ""),
                             r.read().decode("utf-8", "replace"), _lower(r.headers))
        except urllib.error.HTTPError as e:
            return Reply(e.code, e.headers.get("Location", ""),
                         e.read().decode("utf-8", "replace"), _lower(e.headers))

    def get(self, path: str, headers: dict | None = None) -> Reply:
        return self._do(path, headers=headers)

    def post(self, path: str, headers: dict | None = None, **fields) -> Reply:
        return self._do(path, urllib.parse.urlencode(fields, doseq=True).encode(), headers)

    def post_raw(self, path: str, data: bytes, content_type: str = "application/json") -> Reply:
        """Тело как есть — так стучится провайдер (callback maib), не форма админки."""
        return self._do(path, data, {"Content-Type": content_type})

    def login(self, user: str = ADMIN_USER, password: str = ADMIN_PASS) -> "Client":
        self.post("/admin/login", user=user, password=password)
        return self


class Result:
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def check(self, label: str, got, want) -> bool:
        if got == want:
            self.passed.append(label)
            return True
        self.failed.append((label, f"получено {got!r}, ожидалось {want!r}"))
        return False

    def ok(self, label: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed.append(label)
            return True
        self.failed.append((label, detail or "условие не выполнено"))
        return False


def run(suites: list) -> int:
    res = Result()
    t0 = time.time()
    for name, fn in suites:
        print(f"\n=== {name} ===")
        before = len(res.passed) + len(res.failed)
        try:
            fn(res)
        except Exception as e:  # noqa: BLE001 — падение набора не должно съесть отчёт
            tb = traceback.extract_tb(e.__traceback__)
            where = f" — {pathlib.Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
            res.failed.append((f"{name}: набор упал", repr(e) + where))
        print(f"    проверок: {len(res.passed) + len(res.failed) - before}")
    print("\n" + "=" * 60)
    for label, why in res.failed:
        print(f"  ✗ {label}: {why}")
    total = len(res.passed) + len(res.failed)
    print(f"\n{len(res.passed)}/{total} прошло за {time.time() - t0:.1f} с")
    return 1 if res.failed else 0


def unb64u(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def load_by_path(name: str, path: pathlib.Path):
    """Модуль движка без импортов проекта — как tests/test_license_verify.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def cid_from(location: str) -> str:
    return location.split("/admin/clinics/", 1)[1].split("?", 1)[0]


def read_json(reply: Reply) -> dict:
    return json.loads(reply.body)
