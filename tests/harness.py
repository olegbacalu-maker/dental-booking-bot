"""Каркас тестов DentPilot: поднять сервер, поговорить с ним по HTTP.

Зависимостей нет намеренно — только стандартная библиотека. `.venv-desktop`
это окружение СБОРКИ, и всё лишнее в нём однажды окажется внутри exe; а тесты
должны запускаться и там, где ставить пакеты некому.

Сервер поднимается на свободном порту со своей временной базой, поэтому прогон
не задевает ни установленную программу (порт 8088), ни песочницы.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import pathlib
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]      # …\app
BOT = ROOT / "bot"
PYTHON = ROOT / ".venv-desktop" / "Scripts" / "python.exe"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
PIN = "test1234"

# Клиника, у которой бот УЖЕ настроен (grandfather). Telegram и веб-чат
# заморожены 08-08 и живут только за layout.tg_configured(), поэтому набор,
# который проверяет САМ канал (диалог бота, лендинг, /chat), обязан подниматься
# с этим окружением — иначе он стучится в дверь, которой у клиники нет.
# Флаг честный: dpapi ставит его, когда токен есть, но не расшифровывается, —
# интерфейс включён, живой адаптер Telegram при этом не стартует.
TG_ON = {"DENTART_TOKEN_UNREADABLE": "1"}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    """Свой uvicorn на свободном порту, своя пустая база, свой конфиг клиники.

    ⚠️ Windows позволяет второй bind на занятый порт, и запросы уходят СТАРОМУ
    процессу — поэтому порт берётся свободный, а не фиксированный.
    """

    def __init__(self, clinic: str = "clinic_test.json", env: dict | None = None,
                 dir_: pathlib.Path | None = None):
        """dir_ — переиспользовать папку данных ПРЕЖНЕГО сервера: так
        проверяется то, что живёт через рестарт (сигнализация auth.json,
        миграции). Чужую папку не удаляем — прибирает тот, кто её создал."""
        self.port = free_port()
        self._own_dir = dir_ is None
        self.dir = pathlib.Path(dir_) if dir_ else pathlib.Path(
            tempfile.mkdtemp(prefix="dp_test_"))
        self.clinic = self.dir / "clinic.json"
        if not self.clinic.exists():
            shutil.copy(FIXTURES / clinic, self.clinic)
        self.extra_env = env or {}
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "Server":
        env = dict(os.environ)
        env.update({
            "CLINIC_CONFIG": str(self.clinic),
            "DATABASE_URL": f"sqlite:///{self.dir / 'dental.db'}",
            "ADMIN_KEY": PIN,
            "DENTART_NO_RESTART": "1",       # тест-хук: не перезапускать процесс
            "TELEGRAM_TOKEN": "",            # адаптер Telegram не поднимать
        })
        env.update(self.extra_env)
        self.proc = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "app.main:app", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=str(BOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.time() + 40
        while time.time() < deadline:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"сервер упал при старте:\n{out[-2000:]}")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=1):
                    return self
            except Exception:  # noqa: BLE001 — ещё не поднялся
                time.sleep(0.3)
        raise RuntimeError("сервер не ответил на /health за 40 секунд")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._own_dir:
            shutil.rmtree(self.dir, ignore_errors=True)


class Reply:
    """Ответ сервера в удобном для проверок виде."""

    def __init__(self, status: int, location: str, body: str,
                 headers: dict | None = None, raw: bytes = b""):
        self.status = status
        self.location = location
        self.body = body
        # тело до декодирования: у выгрузки данных пациента ответ — zip, и
        # `body` его гарантированно портит (decode с "replace")
        self.raw = raw
        self.headers = headers or {}

    def header(self, name: str) -> str:
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return ""

    @property
    def msg(self) -> str:
        """Код баннера из редиректа (?msg=…) — язык, которым журнал отвечает."""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.location).query)
        return (q.get("msg") or [""])[0]

    def __repr__(self) -> str:
        return f"<{self.status} msg={self.msg!r} loc={self.location!r}>"


class Client:
    """HTTP-клиент с куками и БЕЗ следования редиректам: код ответа и Location —
    это и есть проверяемое поведение журнала."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect)

    def _do(self, path: str, data: bytes | None = None,
            headers: dict | None = None) -> Reply:
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers or {})
        try:
            with self.opener.open(req, timeout=30) as r:
                data = r.read()
                return Reply(r.status, r.headers.get("Location", ""),
                             data.decode("utf-8", "replace"), dict(r.headers), data)
        except urllib.error.HTTPError as e:
            data = e.read()
            return Reply(e.code, e.headers.get("Location", ""),
                         data.decode("utf-8", "replace"), dict(e.headers), data)

    def get(self, path: str) -> Reply:
        return self._do(path)

    def post(self, path: str, **fields) -> Reply:
        # doseq: список значений = ПОВТОРЯЮЩЕЕСЯ поле формы (галочки), а не
        # строка «['O', 'M']» — так браузер шлёт несколько отмеченных чекбоксов
        return self._do(path, urllib.parse.urlencode(fields, doseq=True).encode())

    def post_json(self, path: str, payload: dict) -> Reply:
        return self._do(path, json.dumps(payload).encode(),
                        {"Content-Type": "application/json"})

    def post_file(self, path: str, field: str, filename: str, content: bytes,
                  **fields) -> Reply:
        """multipart/form-data — загрузка документа в фишу пациента.

        Собирается руками: в стандартной библиотеке кодировщика multipart нет,
        а тянуть requests в тесты нельзя (см. шапку файла — только stdlib).
        Имя файла НЕ экранируется намеренно: тесты подсовывают сюда `../`, и
        экранирование здесь спрятало бы ровно то, что проверяется.
        """
        bnd = "----dp" + secrets.token_hex(8)
        parts = []
        for k, v in fields.items():
            parts.append(f"--{bnd}\r\nContent-Disposition: form-data; "
                         f'name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f"--{bnd}\r\nContent-Disposition: form-data; "
                     f'name="{field}"; filename="{filename}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode())
        parts.append(content + b"\r\n")
        parts.append(f"--{bnd}--\r\n".encode())
        return self._do(path, b"".join(parts),
                        {"Content-Type": f"multipart/form-data; boundary={bnd}"})

    def login(self, password: str = PIN) -> "Client":
        self.post("/admin/login", password=password, next="/admin")
        return self


class Bot:
    """Диалог бота через /chat. Возвращает (тексты, значения кнопок)."""

    def __init__(self, client: Client, sid: str):
        self.c = client
        self.sid = sid

    def say(self, message: str) -> tuple[str, list[str]]:
        r = self.c.post_json("/chat", {"session_id": self.sid, "message": message})
        data = json.loads(r.body)
        texts = " | ".join(m["text"] for m in data["messages"])
        buttons = [b["value"] for row in data["buttons"] for b in row]
        return texts, buttons


# ---------- сбор и запуск проверок ----------

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
    """suites = [(имя, функция(res))]. Возвращает код выхода."""
    res = Result()
    t0 = time.time()
    for name, fn in suites:
        print(f"\n=== {name} ===")
        before = len(res.passed) + len(res.failed)
        try:
            fn(res)
        except Exception as e:  # noqa: BLE001 — падение набора не должно съесть отчёт
            res.failed.append((f"{name}: набор упал", repr(e)))
        done = len(res.passed) + len(res.failed) - before
        print(f"    проверок: {done}")
    print("\n" + "=" * 60)
    for label, why in res.failed:
        print(f"  ✗ {label}: {why}")
    total = len(res.passed) + len(res.failed)
    print(f"\n{len(res.passed)}/{total} прошло за {time.time() - t0:.1f} с")
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit("Это каркас. Запускать: python tests\\run_tests.py")
