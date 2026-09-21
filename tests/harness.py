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
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

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
                 dir_: pathlib.Path | None = None,
                 bot: pathlib.Path | None = None):
        """dir_ — переиспользовать папку данных ПРЕЖНЕГО сервера: так
        проверяется то, что живёт через рестарт (сигнализация auth.json,
        миграции). Чужую папку не удаляем — прибирает тот, кто её создал.

        bot — поднять сервер из КОПИИ дерева `bot\\` (тот же приём, что в
        mutate.py). Нужен там, где проверяется поведение, которое иначе не
        вызвать снаружи: исполняется ли список шага миграции, что говорит
        программа, когда отказал не CREATE, а сам подсчёт конфликтов. ⚠️ Правка
        вносится в КОПИЮ; настоящее дерево не трогается никогда."""
        self.port = free_port()
        self.bot = pathlib.Path(bot) if bot else BOT
        self._own_dir = dir_ is None
        self.dir = pathlib.Path(dir_) if dir_ else pathlib.Path(
            tempfile.mkdtemp(prefix="dp_test_"))
        self.clinic = self.dir / "clinic.json"
        if not self.clinic.exists():
            shutil.copy(FIXTURES / clinic, self.clinic)
            self._pin_legacy()
        self.extra_env = env or {}
        self.proc: subprocess.Popen | None = None

    def _pin_legacy(self) -> None:
        """Пин СТАРОЙ страницы в фикстуре, которую скопировали мы сами.

        ⛔ С 21.09 React отдаётся, когда ключа `ui.react` НЕТ: он стал
        поверхностью продукта, а не рубильником выката. Почти каждый набор при
        этом разбирает СТАРУЮ разметку как эталон — колонку времени дня, канву
        панели, — и без пина двадцать наборов упали разбором чужой страницы.
        ⭐ Пин живёт ЗДЕСЬ, а не в четырёх файлах фикстур: список файлов —
        ровно та гниющая полярность, из-за которой следующая фикстура завелась
        бы без пина МОЛЧА, и набор на ней проверял бы не тот интерфейс.
        ⚠️ Трогаем только СВОЮ копию. Профиль, положенный набором в папку до
        старта (`test_react_default` кладёт настоящий `clinic_new.json`), —
        его условие проверки, и переписывать его значило бы проверять свою
        подделку вместо продукта.
        ⭐ Набору, которому нужен React, достаточно назвать имена самому: так
        уже устроены все `suite_switch`.

        ⚠️ Пин стоит ДВАЖДЫ, и это не небрежность: ключ лежит в самих файлах
        фикстур (их копируют и руками — `test_dbcrypt` делает `shutil.copy`
        сам, и до сервера дело доходит уже с готовым профилем), а здесь —
        страховка на будущую фикстуру, которую заведут БЕЗ ключа. Одного
        механизма мало каждому: файл не покрывает новую фикстуру, харнесс не
        покрывает ручную копию.
        """
        cfg = json.loads(self.clinic.read_text(encoding="utf-8"))
        cfg.setdefault("ui", {}).setdefault("react", [])
        self.clinic.write_text(json.dumps(cfg, ensure_ascii=False, indent=1),
                               encoding="utf-8")

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
        # ⛔ Вывод сервера идёт в ФАЙЛ, а не в трубу. Труба здесь была, и её
        # никто не вычитывал: стоит серверу напечатать больше буфера окна
        # (17 КБ трейсбека хватает), как он встаёт на write НАВСЕГДА — набор
        # выглядит как «зависло на ровном месте», а причина не печатается,
        # потому что застряла в той же трубе. Нашло ревью C23 (18.09).
        self._log_path = self.dir / "server.log"
        self._log = self._log_path.open("wb")
        self.proc = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "app.main:app", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=str(self.bot), env=env,
            stdout=self._log, stderr=subprocess.STDOUT,
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

    def log_text(self) -> str:
        """Что сервер написал за свою жизнь. Файл, а не труба, — см. запуск."""
        try:
            self._log.flush()
            return self._log_path.read_bytes().decode("utf-8", "replace")
        except OSError:
            return ""

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            self._log.close()         # до удаления папки: файл лежит в ней
        except (OSError, AttributeError):
            pass
        if self._own_dir:
            _rmtree_settled(self.dir)
        else:
            _settle_db(self.dir / "dental.db")


def _rmtree_settled(path: pathlib.Path, budget: float = 5.0) -> None:
    """Убрать песочницу — ДОЖДАВШИСЬ, пока Windows отпустит базу.

    ⛔ `shutil.rmtree(..., ignore_errors=True)` сразу после TerminateProcess не
    работает и НЕ ЖАЛУЕТСЯ: убитый uvicorn ещё держит отображение `-wal`/`-shm`,
    удаление падает, флаг отказ проглатывает — и папка остаётся навсегда.
    Поймано 19.09: один полный прогон поднимает под две сотни серверов, и в
    `%TEMP%` набралось 4179 папок `dp_test_*` на 1.7 ГБ. Диск C у Олега
    переполняется регулярно, и это одна из причин.

    ⚠️ Лечится тем же ожиданием, что уже стоит у чужой папки (`_settle_db`):
    несколько попыток, пока файлы не отпустят. Последняя — молча, чтобы
    прогон не падал из-за уборки: цель — не оставить мусор, а не умереть.
    """
    deadline = time.time() + budget
    while True:
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if time.time() > deadline:
                shutil.rmtree(path, ignore_errors=True)
                return
            time.sleep(0.15)


def _settle_db(path: pathlib.Path, budget: float = 5.0) -> None:
    """Дождаться, пока базу можно открыть ПОСЛЕ гашения сервера.

    Сервер гасится TerminateProcess-ом, и его -wal/-shm остаются на диске;
    следующий, кто открывает базу, делает восстановление журнала. На Windows
    в первые мгновения после гашения это отвечает «disk I/O error»: отображение
    -shm убитого процесса ещё не отпущено, и SQLite не может его перезаписать.
    Локально это одно падение на полный прогон, на раннере GitHub — все
    восемнадцать наборов, которые читают базу stdlib-ом сразу после
    `with Server(dir_=…)` (17.09, дважды подряд). Здесь та же попытка делается
    с паузами, пока не удастся или не кончится бюджет; тогда падает набор —
    честно, а не молча.
    ⚠️ Зашифрованную картотеку stdlib не откроет вовсе («file is not a
    database») — это не наша беда, выходим молча: такие наборы читают базу
    своим драйвером."""
    if not path.exists():
        return
    deadline = time.time() + budget
    while True:
        try:
            con = sqlite3.connect(str(path))
            try:
                con.execute("PRAGMA schema_version").fetchone()
            finally:
                con.close()
            return
        except sqlite3.OperationalError as e:
            if "disk I/O error" not in str(e) or time.time() > deadline:
                raise
            time.sleep(0.15)
        except sqlite3.DatabaseError:
            return                       # шифрованная база или чужой формат


# Часовой пояс клиники — тот же, что engine.TZ (harness приложение не
# импортирует: он поднимает его подпроцессом).
TZ = ZoneInfo("Europe/Chisinau")


def clinic_today() -> date:
    """«Сегодня» КЛИНИКИ, не машины. Движок считает день по Кишинёву, а
    раннер CI живёт по UTC: между 21:00 и 24:00 UTC у них разные даты, и
    всё, что брало `date.today()`, ночью краснело — «сегодня закрытый день»,
    баннер прошедшего часа, дата завершения визита, пустой день кассы
    (18.09, четыре проверки). На ПК с местным поясом значение то же."""
    return datetime.now(TZ).date()


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

    def get(self, path: str, headers: dict | None = None) -> Reply:
        return self._do(path, headers=headers)

    def post(self, path: str, headers: dict | None = None, **fields) -> Reply:
        # doseq: список значений = ПОВТОРЯЮЩЕЕСЯ поле формы (галочки), а не
        # строка «['O', 'M']» — так браузер шлёт несколько отмеченных чекбоксов.
        # headers — именованный, не поле формы: нужен проверкам Origin (CSRF)
        return self._do(path, urllib.parse.urlencode(fields, doseq=True).encode(),
                        headers)

    def post_json(self, path: str, payload: dict,
                  headers: dict | None = None) -> Reply:
        # headers — для проверок Origin на /api/*, как у post()
        return self._do(path, json.dumps(payload).encode(),
                        {"Content-Type": "application/json", **(headers or {})})

    def post_file(self, path: str, field: str, filename: str, content: bytes,
                  *, mime: str = "application/octet-stream", **fields) -> Reply:
        """multipart/form-data — загрузка документа в фишу пациента.

        Собирается руками: в стандартной библиотеке кодировщика multipart нет,
        а тянуть requests в тесты нельзя (см. шапку файла — только stdlib).
        Имя файла НЕ экранируется намеренно: тесты подсовывают сюда `../`, и
        экранирование здесь спрятало бы ровно то, что проверяется.
        `mime` — тип файла, как его называет браузер при загрузке: по нему
        фиша решает, показывать снимок картинкой, PDF — просмотрщиком или
        отдать файл программе Windows (только keyword, чтобы не спутать с
        полем формы).
        """
        bnd = "----dp" + secrets.token_hex(8)
        parts = []
        for k, v in fields.items():
            parts.append(f"--{bnd}\r\nContent-Disposition: form-data; "
                         f'name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f"--{bnd}\r\nContent-Disposition: form-data; "
                     f'name="{field}"; filename="{filename}"\r\n'
                     f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(content + b"\r\n")
        parts.append(f"--{bnd}--\r\n".encode())
        return self._do(path, b"".join(parts),
                        {"Content-Type": f"multipart/form-data; boundary={bnd}"})

    def login(self, password: str = PIN) -> "Client":
        self.post("/admin/login", password=password, next="/admin")
        return self


class Bot:
    """Диалог бота через /chat. Возвращает (тексты, значения кнопок).

    ⚠️ Ключ сессии больше НЕ приходит от клиента: /chat выдаёт подписанный
    токен, а session_key собирает сервер (присланный `manual:<цифры>` открывал
    бы чужую фишу — находка ревью 08-15). Метка нужна только для читаемости
    теста; разные сессии дают разные токены, а не разные метки.
    """

    def __init__(self, client: Client, label: str = ""):
        self.c = client
        self.label = label
        self.token = ""

    def say(self, message: str) -> tuple[str, list[str]]:
        r = self.c.post_json("/chat", {"session": self.token, "message": message})
        data = json.loads(r.body)
        self.token = data.get("session") or self.token
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
            # Файл и строка последнего кадра: без них «набор упал:
            # OperationalError('disk I/O error')» на чужом раннере не говорит,
            # какая из двадцати баз набора не открылась (первый прогон CI 17.09)
            tb = traceback.extract_tb(e.__traceback__)
            where = f" — {pathlib.Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
            res.failed.append((f"{name}: набор упал", repr(e) + where))
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
