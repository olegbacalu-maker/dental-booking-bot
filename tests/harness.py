"""Каркас тестов DentPilot: поднять сервер, поговорить с ним по HTTP.

Зависимостей нет намеренно — только стандартная библиотека. `.venv-desktop`
это окружение СБОРКИ, и всё лишнее в нём однажды окажется внутри exe; а тесты
должны запускаться и там, где ставить пакеты некому.

Сервер поднимается на свободном порту со своей временной базой, поэтому прогон
не задевает ни установленную программу (порт 8088), ни песочницы.
"""
from __future__ import annotations

import atexit
import html
import http.client
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
from datetime import date, datetime, timedelta, timezone
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
                 bot: pathlib.Path | None = None, keep_dir: bool = False,
                 clock: "Clock | None" = None):
        """dir_ — переиспользовать папку данных ПРЕЖНЕГО сервера: так
        проверяется то, что живёт через рестарт (сигнализация auth.json,
        миграции). Чужую папку не удаляем — прибирает тот, кто её создал.

        keep_dir — СВОЮ папку на выходе не сносить: её подхватит следующий
        сервер (`Server(dir_=s1.dir)`) — так стенды сеют данные первым
        сервером и смотрят вторым. Сносит её потом `s1.drop()`.
        ⛔ Раньше стенды ставили `s1._own_dir = False` и в конце звали
        `s1.__exit__()`, считая это уборкой, — а флаг так и стоял, и каждый
        прогон стенда оставлял в %TEMP% свою `dp_test_*` навсегда (26.09: 156
        папок за три дня, цепочками по шесть — ровно `.\\dev bench`).

        bot — поднять сервер из КОПИИ дерева `bot\\` (тот же приём, что в
        mutate.py). Нужен там, где проверяется поведение, которое иначе не
        вызвать снаружи: исполняется ли список шага миграции, что говорит
        программа, когда отказал не CREATE, а сам подсчёт конфликтов. ⚠️ Правка
        вносится в КОПИЮ; настоящее дерево не трогается никогда.

        clock — поддельные часы сервера (`Clock`). Не назван — сервер берёт
        часы блока `with Clock(…)`, внутри которого стартует, а вне блока
        живёт по настоящим."""
        self.port = free_port()
        self.clock = clock
        self.bot = pathlib.Path(bot) if bot else BOT
        self._made_dir = dir_ is None
        self._own_dir = self._made_dir and not keep_dir
        self.dir = pathlib.Path(dir_) if dir_ else pathlib.Path(
            tempfile.mkdtemp(prefix="dp_test_"))
        self.clinic = self.dir / "clinic.json"
        if not self.clinic.exists():
            shutil.copy(FIXTURES / clinic, self.clinic)
        self.extra_env = env or {}
        self.proc: subprocess.Popen | None = None
        # задание Windows всего дерева сервера (почему своё — _start_in_own_job)
        self._job = None
        # %TEMP% самого сервера — заводится на старте, уходит вместе с ним
        # (почему свой — в __enter__)
        self.tmp: pathlib.Path | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "Server":
        # Часы — первыми. Не заведённые (`Server(clock=Clock(…))` без `with`) —
        # отказ до старта, и песочница, которую завёл __init__, не остаётся.
        self.clock = self.clock or (_CLOCKS[-1] if _CLOCKS else None)
        if self.clock is not None and self.clock.file is None:
            self.__exit__(None, None, None)
            raise RuntimeError("часы не заведены: сервер под Clock стартует "
                               "внутри `with Clock(…)`")
        # ⭐ У сервера СВОЙ %TEMP% — рядом с песочницей, а не в ней: бэкап
        # пакует папку данных, и временное легло бы в архив. Выгрузка пациента
        # и бэкап пишут туда архив и сносят его фоновой задачей через ~20 мс
        # после отдачи, а набор гасит сервер сразу за последним запросом — и
        # `dp_export_*`/`dp_backup_*` оставались в %TEMP% (замер 26.09: 2
        # гашения из 4; при живом сервере продукт чист 20 выдач из 20). Своё
        # временное уходит вместе с сервером, а набору, которому важно, что
        # продукт прибрал за собой САМ, `self.tmp` виден, пока сервер жив.
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_srvtmp_"))
        env = dict(os.environ)
        # Часы сервера назначает Clock. FAKECLOCK_FILE, унаследованный от
        # прогона (ручная подмена до 27.09 ставилась на сам прогон), двигал бы
        # серверы молча, а clinic_today() — нет. Названный в `env=` — действует.
        env.pop("FAKECLOCK_FILE", None)
        env.update({
            "CLINIC_CONFIG": str(self.clinic),
            "DATABASE_URL": f"sqlite:///{self.dir / 'dental.db'}",
            "ADMIN_KEY": PIN,
            "DENTART_NO_RESTART": "1",       # тест-хук: не перезапускать процесс
            # тест-хук: не спрашивать обновления при старте — 300 серверов за
            # прогон выедали квоту GitHub 60 в час (03.10); набор про обновления
            # включает проверку сам, передав пустое значение в env=
            "DENTART_UPDATE_CHECK": "off",
            "TELEGRAM_TOKEN": "",            # адаптер Telegram не поднимать
            "TMPDIR": str(self.tmp), "TEMP": str(self.tmp), "TMP": str(self.tmp),
        })
        env.update(self.extra_env)
        # Часы — ПОСЛЕ extra_env: PYTHONPATH, переданный набором, дополняется
        # ими, а не затирает их
        if self.clock is not None:
            env.update(self.clock.env(env.get("PYTHONPATH", "")))
        # ⛔ Вывод сервера идёт в ФАЙЛ, а не в трубу. Труба здесь была, и её
        # никто не вычитывал: стоит серверу напечатать больше буфера окна
        # (17 КБ трейсбека хватает), как он встаёт на write НАВСЕГДА — набор
        # выглядит как «зависло на ровном месте», а причина не печатается,
        # потому что застряла в той же трубе. Нашло ревью C23 (18.09).
        self._log_path = self.dir / "server.log"
        self._log = self._log_path.open("wb")
        try:
            self.proc, self._job = _start_in_own_job(
                [str(PYTHON), "-m", "uvicorn", "app.main:app", "--port", str(self.port),
                 "--log-level", "warning"],
                cwd=str(self.bot), env=env,
                stdout=self._log, stderr=subprocess.STDOUT,
            )
        except BaseException:
            self.__exit__(None, None, None)     # `with` его после отказа не позовёт
            raise
        deadline = time.time() + 40
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise self._startup_failed("сервер упал при старте")
            if not _health(self.port, deadline):
                time.sleep(0.3)
                continue
            # ⛔ Часы, которые не встали, НЕ падают: PYTHONPATH не дошёл или
            # sitecustomize упал при импорте — `site` печатает ошибку и идёт
            # дальше, и сервер молча жил бы по настоящему времени, а набор
            # проверял бы не тот день. Отметку часы пишут в лог сами.
            if self.clock is not None and _CLOCK_MARK not in self.log_text():
                raise self._startup_failed(
                    f"сервер поднялся мимо поддельных часов — в логе нет «{_CLOCK_MARK}»: "
                    f"PYTHONPATH не дошёл или sitecustomize упал")
            return self
        raise self._startup_failed("сервер не ответил на /health за 40 секунд")

    def _startup_failed(self, why: str) -> RuntimeError:
        """Старт не удался. Исключение вылетает из __enter__, и `with` уже НЕ
        позовёт __exit__ — поэтому прибираем здесь: процесс (если ещё жив),
        его %TEMP% и свою папку. Без этого каждый несостоявшийся старт
        оставлял песочницу навсегда.
        ⚠️ Хвост server.log — в само сообщение: после уборки прочитать его
        негде. (Прежде сюда шёл `proc.stdout`, которого нет — вывод идёт в
        файл, — и «упал при старте» приходило с пустой причиной.)"""
        tail = self.log_text()[-2000:]
        self.__exit__(None, None, None)
        return RuntimeError(f"{why}:\n{tail}")

    def log_text(self) -> str:
        """Что сервер написал за свою жизнь. Файл, а не труба, — см. запуск."""
        try:
            self._log.flush()
            return self._log_path.read_bytes().decode("utf-8", "replace")
        except OSError:
            return ""

    def __exit__(self, *exc) -> None:
        # ⛔ Сперва ВСЁ дерево сервера, и только потом его папки: потомок,
        # переживший гашение, создаёт снесённый %TEMP% заново (14.10,
        # `_start_in_own_job`). Задание гасит лаунчер, сервер и их потомков
        # разом; ветка ниже — для сервера без задания (не Windows).
        if self._job is not None:
            _end_job(self._job)
            self._job = None
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
        _wait_released(getattr(self, "_log_path", None))
        if self.tmp is not None:
            _rmtree_settled(self.tmp)
            self.tmp = None
        if self._own_dir:
            _rmtree_settled(self.dir)
        else:
            _settle_db(self.dir / "dental.db")

    def drop(self) -> None:
        """Погасить (если ещё жив) и снести папку, которую завёл харнесс, — в
        том числе оставленную `keep_dir`. Чужую (`dir_=`) не трогает никогда:
        её прибирает тот, кто создал."""
        self.__exit__(None, None, None)
        if self._made_dir:
            _rmtree_settled(self.dir)


def _health(port: int, deadline: float) -> bool:
    """Один опрос `/health` на старте сервера: ответил ли он.

    ⛔ Ответ читается ДО КОНЦА, и только потом сокет закрывается. 14.10
    «лог: renew=offline, без трейсбека» (`test_license_renew`, шаг 6)
    покраснел не ошибкой лицензии, а трейсбеком asyncio в логе сервера:
    `_call_connection_lost` → `shutdown` → ConnectionResetError 10054.
    Источник — этот опрос: `with urlopen(…): pass` закрывал сокет по одним
    заголовкам, uvicorn пишет тело ОТДЕЛЬНОЙ записью, и закрытие, попавшее в
    окно ~100–200 мкс вокруг неё, приходило серверу RST-ом прямо под его
    `shutdown`. Сервер здоров, asyncio лишь печатает трейсбек. Замер на живом
    сервере, одна и та же задержка клиента сразу за заголовками (40–160 мкс —
    так его растягивает нагрузка): прежний опрос — 148 трейсбеков из 9600,
    этот — 0 из 9600; без задержки прежний задел окно 2 раза из 13 200: на
    тихой машине редко, нагрузка его открывает. `Client` дочитывает ответ по
    Content-Length и в окно не попадает (0 из 4000 в том же замере).
    ⚠️ Подключение — с таймаутом в секунду: пока сервер не слушает, отказ на
    Windows приходит через 2 с повторов SYN. Но ПРИНЯТЫЙ запрос через секунду
    не бросается: брошенный с ответом в пути — тот же обрыв; ответа ждём до
    общего срока старта.
    «Ещё не поднялся» — это ТОЛЬКО сетевые ошибки (отказ соединения, обрыв,
    таймаут) и ответ 4xx/5xx. ⛔ Не `except Exception`: 13.10 у `url` пропал
    `@property`, `self.url + "/health"` падал TypeError, и каждый сервер 40
    секунд «не отвечал на /health» — ошибка кода харнесса выглядела
    зависанием программы.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.connect()
        conn.sock.settimeout(max(1.0, deadline - time.time()))
        conn.request("GET", "/health", headers={"Connection": "close"})
        r = conn.getresponse()
        r.read()
        return r.status < 400
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def _wait_released(log: pathlib.Path | None, budget: float = 10.0) -> None:
    """Дождаться, пока НАСТОЯЩИЙ процесс сервера отпустит свои файлы.

    ⛔ `Server.proc` — это ЛАУНЧЕР venv: `.venv-desktop\\Scripts\\python.exe`
    сам ничего не исполняет, а запускает базовый интерпретатор дочерним
    процессом. `terminate()` + `wait()` дожидаются ЛАУНЧЕРА; сервер Windows
    гасит следом (задание с KILL_ON_JOB_CLOSE), и ещё ~7 мс он держит базу,
    лог и свою РАБОЧУЮ папку (замер 26.09: шесть серверов из шести). В это
    окно попадала уборка `shutil.rmtree(…, ignore_errors=True)` у наборов,
    поднимающих сервер из копии `bot` (она и есть `cwd` сервера): пустая
    `bot` оставалась в %TEMP% навсегда, а флаг отказ проглатывал.
    Признак смерти — server.log: сервер унаследовал его дескриптор без права
    удаления, и переименовать файл Windows даёт, лишь когда закрыты ВСЕ
    дескрипторы. Не дождались за budget — выходим: оставшееся поймает сторож
    уборки в `run()`, это честнее, чем висеть.
    """
    if os.name != "nt" or log is None or not log.exists():
        return                   # POSIX переименует и открытый файл: признака нет
    probe = log.with_name(log.name + ".probe")
    deadline = time.time() + budget
    while True:
        try:
            os.replace(log, probe)
        except PermissionError:
            if time.time() > deadline:
                return
            time.sleep(0.02)
            continue
        except OSError:
            return
        try:
            os.replace(probe, log)   # имя вернуть: наборы читают лог и после гашения
        except OSError:
            pass
        return


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


# ---------- временное прогона: одна папка на процесс ----------
#
# ⭐ Всё, что заводит процесс харнесса, — песочницы серверов, их %TEMP%, папки
# наборов, временное дочерних процессов и стендов (профиль Edge) — живёт в
# ОДНОЙ папке `%TEMP%\dp_run_*` и уходит одним сносом на выходе. Раньше каждое
# место прибирало за собой само, и каждое по-своему не прибирало: 26.09 в
# %TEMP% лежало 387 папок `dp_*` от 24–26.09, и ни одна не выдала себя ничем,
# кроме заполняющегося диска C.

_RUN_PREFIX = "dp_run_"


def _sweep_dead_runs(base: pathlib.Path) -> None:
    """Снести временное прогонов, чей хозяин умер, не прибравшись.

    Прогон, убитый снаружи (таймаут сессии, Ctrl+C, закрытое окно), до уборки
    не доходит вовсе, и всё, что он завёл, осталось бы в %TEMP% навсегда.
    ⛔ Чистить по ВОЗРАСТУ нельзя: рядом идут прогоны других сессий, их
    песочницы живые, и «уборка» посреди прогона однажды уже заставила его
    перезапускать. Признак — не время, а замок: живой прогон держит `.lock`
    открытым без права удаления, и Windows не даст его стереть. Стёрся —
    хозяина нет, папку можно сносить.
    ⚠️ Только Windows: POSIX удаляет и открытый файл, признак там ничего не
    значит (а раннеры CI живут по одному прогону).
    ⚠️ Свежую папку (моложе минуты) не трогаем: между `mkdtemp` и открытием
    замка у только что стартовавшего прогона есть мгновение без замка.
    ⚠️ Бюджет короткий: то, что держится через минуту после смерти хозяина,
    держит осиротевший процесс, и ждать его на каждом старте незачем —
    следующий старт попробует снова.
    """
    if os.name != "nt":
        return
    for d in base.glob(_RUN_PREFIX + "*"):
        try:
            if time.time() - d.stat().st_mtime < 60:
                continue
            (d / ".lock").unlink(missing_ok=True)
        except OSError:
            continue                     # замок держит живой прогон
        _rmtree_settled(d, budget=1.0)


def _children_die_with_us():
    """Все процессы, которые заведёт прогон, — в задании Windows, гасящем их,
    когда умирает сам процесс харнесса.

    ⛔ Прогон, убитый не деревом, а ОДНИМ процессом (Stop-Process, «Снять
    задачу», таймаут, гасящий только прямого потомка), оставлял серверы
    сиротами: venv-лаунчер разрешает внукам молча выйти из своего задания, и
    uvicorn жил дальше вечно, держа песочницу от уборки (26.09, опыт: после
    Stop-Process верхнего процесса сервер жил; с заданием — 0 выживших).
    Задание с KILL_ON_JOB_CLOSE закрывается вместе с последним дескриптором,
    то есть со смертью этого процесса, как бы она ни случилась. Дети
    попадают в него сами: выход из задания оно не разрешает, и молчаливый
    выход, разрешённый лаунчером, на него не действует.
    ⚠️ Лучшее из возможного: не вышло (не Windows, запрет среды) — работаем
    как раньше; брошенное подметёт `_sweep_dead_runs`, если его не держат.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ("read", "write", "other", "read_b", "write_b", "other_b")]

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Extended(ctypes.Structure):   # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            _fields_ = [("Basic", _Basic), ("Io", _Io),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        info = _Extended()
        info.Basic.LimitFlags = 0x2000       # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not (job and k32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                                    ctypes.sizeof(info))
                and k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())):
            return None
        return job                           # дескриптор живёт, пока жив процесс
    except (OSError, AttributeError):
        return None


_KIDS_JOB = _children_die_with_us()


def _end_children(budget: float = 5.0) -> None:
    """Погасить всех, кто ещё жив в задании процесса, и ДОЖДАТЬСЯ их смерти.

    ⛔ Задание гасит детей само, но в последний момент — когда процесс уже
    умирает, то есть ПОСЛЕ atexit. Уборка папки прогона шла раньше, при живых
    детях, и всё, что они писали в свой %TEMP% после неё, оставалось. Поймано
    03.10 (дважды за день, в полном прогоне): «Сеть: приход из сети
    записывает приложение: оставил временное: dp_run_…». Рабочий процесс
    набора (`test_netcheck`; так же устроен `test_hardening` worker-setup)
    импортирует харнесс — своя папка прогона внутри чужой, — а старт
    приложения запускает в фоне проверку BitLocker через PowerShell. Рабочий
    укладывается в секунды, atexit сносит папку, а не успевший стартовать
    PowerShell СОЗДАЁТ недостающий %TEMP% заново (Windows PowerShell делает это
    сам) и кладёт туда `__PSScriptPolicyTest_*`; задание гасит его уже потом.
    Замер под нагрузкой (рабочие по 12 и по 24 параллельно): папку оставили 17
    из 36 и 25 из 48; с этим порядком — 0 и 0.
    ⭐ Порядок — дети, потом папка: гасим то же, что задание погасило бы
    мгновением позже, только до уборки, а не после неё.
    ⚠️ Вложенная папка тут ни при чём, и убирать её не надо: она — контейнер
    всего дерева рабочего. Общая с родителем папка оставляла файлы
    PowerShell, погашенного между их созданием и удалением, уже у родителя
    (4 из 36), а рабочий без харнесса — без задания — делает PowerShell
    сиротой, который пишет в папку прогона посреди СЛЕДУЮЩИХ наборов и красит
    не тот.
    ⚠️ Номер процесса Windows раздаёт заново: ребёнок мог умереть между
    списком и OpenProcess, а номер достаться чужому. Гасим только того, кто
    В НАШЕМ задании.
    """
    if _KIDS_JOB is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _Ids(ctypes.Structure):          # JOBOBJECT_BASIC_PROCESS_ID_LIST
            _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                        ("ids", ctypes.c_size_t * 64)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.c_void_p]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                       ctypes.POINTER(wintypes.BOOL)]
        k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        me, skip = os.getpid(), set()
        deadline = time.time() + budget
        while time.time() < deadline:      # круг — ради детей, заведённых, пока гасили прежних
            ids = _Ids()
            # ERROR_MORE_DATA (234): детей больше, чем влезло в список, — он
            # неполный, но годный: гасим этих и спрашиваем снова
            if not (k32.QueryInformationJobObject(_KIDS_JOB, 3, ctypes.byref(ids),
                                                  ctypes.sizeof(ids), None)
                    or ctypes.get_last_error() == 234):
                return
            kids = [p for p in ids.ids[:ids.listed] if p != me and p not in skip]
            if not kids:
                return
            for pid in kids:
                skip.add(pid)      # каждого — один раз: неубиваемого не ждём по кругу
                # TERMINATE | QUERY_LIMITED_INFORMATION | SYNCHRONIZE
                h = k32.OpenProcess(0x0001 | 0x1000 | 0x00100000, False, pid)
                if not h:
                    continue                   # уже умер или не даётся
                try:
                    inside = wintypes.BOOL()
                    if (k32.IsProcessInJob(h, _KIDS_JOB, ctypes.byref(inside))
                            and inside):
                        k32.TerminateProcess(h, 1)
                        k32.WaitForSingleObject(
                            h, max(0, int((deadline - time.time()) * 1000)))
                finally:
                    k32.CloseHandle(h)
    except (OSError, AttributeError):
        return


def _start_in_own_job(args: list, **popen) -> tuple[subprocess.Popen, object]:
    """Запустить процесс в СВОЁМ задании Windows — вложенном в задание прогона
    и без права выхода. Возвращает (процесс, задание или None).

    ⛔ `Server.__exit__` гасил ЛАУНЧЕР venv; сервер умирал вместе с заданием
    лаунчера, а потомок, которого сервер успел завести, — нет: задание
    лаунчера разрешает потомкам молча выйти (флаги 0x3000 — KILL_ON_JOB_CLOSE
    | SILENT_BREAKAWAY_OK), и потомок жил дальше в одном задании прогона, до
    `_end_children` на выходе. Так PowerShell проверки BitLocker, которую
    старт приложения пускает в фоне, переживал гашение сервера и создавал
    снесённый %TEMP% сервера ЗАНОВО (Windows PowerShell делает это сам) —
    CI 13.10: «Сторожа: уборка временного прогона: оставил временное:
    dp_srvtmp_…» (и 14.10 — «поддельные часы»). Замер 14.10, сервер гасится
    сразу за `/health`, как в сторожах: под нагрузкой PowerShell пережил
    `__exit__` 19 раз из 30 и вернул %TEMP% 4 раза; со своим заданием при той
    же нагрузке — 0 и 0 из 30 (на гашении PowerShell был жив 25 раз).
    Своё задание держит всё дерево: выход из задания лаунчера останавливается
    на нём, и `_end_job` гасит лаунчер, сервер и потомков одним вызовом.
    ⚠️ Процесс стартует ПРИОСТАНОВЛЕННЫМ и входит в задание до первой своей
    инструкции: лаунчер, успевший завести сервер до назначения, увёл бы
    сервер мимо задания. Не назначилось — процесс всё равно возобновляется
    (иначе сервер висел бы до таймаута старта), и уборка идёт по-старому:
    утечку тогда назовёт сторож прогона.
    """
    if os.name != "nt":
        return subprocess.Popen(args, **popen), None
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Extended(ctypes.Structure):       # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [("Basic", _Basic), ("Io", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _Thread(ctypes.Structure):         # THREADENTRY32
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD),
                    ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                            ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.OpenThread.restype = wintypes.HANDLE
    k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.ResumeThread.restype = wintypes.DWORD
    k32.ResumeThread.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    job = k32.CreateJobObjectW(None, None)
    info = _Extended()
    info.Basic.LimitFlags = 0x2000           # KILL_ON_JOB_CLOSE; выхода нет
    if job and not k32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                               ctypes.sizeof(info)):
        k32.CloseHandle(job)
        job = None
    if not job:
        return subprocess.Popen(args, **popen), None
    try:
        proc = subprocess.Popen(args, creationflags=0x4, **popen)   # CREATE_SUSPENDED
    except BaseException:
        k32.CloseHandle(job)
        raise
    # SET_QUOTA | TERMINATE — права, которых требует AssignProcessToJobObject.
    # Номер не уйдёт чужому: Popen держит дескриптор процесса открытым.
    h = k32.OpenProcess(0x0100 | 0x0001, False, proc.pid)
    if not (h and k32.AssignProcessToJobObject(job, h)):
        k32.CloseHandle(job)
        job = None
    if h:
        k32.CloseHandle(h)
    # Возобновить: у только что созданного процесса один поток — главный
    resumed = False
    snap = k32.CreateToolhelp32Snapshot(0x4, 0)          # TH32CS_SNAPTHREAD
    if snap and snap != ctypes.c_void_p(-1).value:       # INVALID_HANDLE_VALUE
        try:
            t = _Thread()
            t.dwSize = ctypes.sizeof(t)
            more = k32.Thread32First(snap, ctypes.byref(t))
            while more:
                if t.th32OwnerProcessID == proc.pid:
                    th = k32.OpenThread(0x0002, False, t.th32ThreadID)   # SUSPEND_RESUME
                    if th:
                        resumed = k32.ResumeThread(th) != 0xFFFFFFFF or resumed
                        k32.CloseHandle(th)
                more = k32.Thread32Next(snap, ctypes.byref(t))
        finally:
            k32.CloseHandle(snap)
    if not resumed:
        # приостановленный процесс никогда не ответит: гасим и говорим прямо
        if job is not None:
            _end_job(job)
        proc.kill()
        proc.wait()
        raise RuntimeError(f"процесс {proc.pid} не возобновился после старта в задании "
                           f"(ошибка Windows {ctypes.get_last_error()})")
    return proc, job


def _end_job(job, budget: float = 10.0) -> None:
    """Погасить всё задание и ДОЖДАТЬСЯ, пока в нём не останется живых, —
    потом закрыть его. Мёртвый процесс не создаёт файлов: после этого
    папки дерева можно сносить. Не дождались за budget — выходим: оставшееся
    назовёт сторож уборки в `run()`, это честнее, чем висеть."""
    import ctypes
    from ctypes import wintypes

    class _Acct(ctypes.Structure):           # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        _fields_ = [("times", ctypes.c_int64 * 4),
                    ("TotalPageFaultCount", wintypes.DWORD),
                    ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD),
                    ("TotalTerminatedProcesses", wintypes.DWORD)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        k32.TerminateJobObject(job, 1)
        acct = _Acct()
        deadline = time.time() + budget
        while (k32.QueryInformationJobObject(job, 1, ctypes.byref(acct),
                                             ctypes.sizeof(acct), None)
               and acct.ActiveProcesses and time.time() < deadline):
            time.sleep(0.01)
    finally:
        k32.CloseHandle(job)


def _open_run_root() -> tuple[pathlib.Path, object]:
    """Завести папку прогона и направить в неё всё временное процесса.

    `tempfile.tempdir` — для самого процесса, TEMP/TMP/TMPDIR — для дочерних:
    сервер, подпроцесс набора, Edge стенда наследуют окружение. Замок держится
    открытым до выхода — по нему `_sweep_dead_runs` отличает живой прогон от
    убитого; внутри — кто хозяин, чтобы брошенную папку можно было узнать
    глазами."""
    base = pathlib.Path(tempfile.gettempdir())
    _sweep_dead_runs(base)
    root = pathlib.Path(tempfile.mkdtemp(prefix=_RUN_PREFIX, dir=base))
    lock = open(root / ".lock", "w", encoding="utf-8")
    lock.write(f"pid {os.getpid()}: {' '.join(sys.argv)}\n")
    lock.flush()
    tempfile.tempdir = str(root)
    for key in ("TMPDIR", "TEMP", "TMP"):
        os.environ[key] = str(root)
    return root, lock


RUN_TMP, _RUN_LOCK = _open_run_root()


@atexit.register
def _close_run_root() -> None:
    try:
        _end_children()                  # сначала дети — почему, см. там
    finally:                             # и что бы там ни случилось, уборка — всегда
        _RUN_LOCK.close()
        _rmtree_settled(RUN_TMP)


def _run_entries() -> set[str]:
    return {p.name for p in RUN_TMP.iterdir()} - {".lock"}


def _check_left(res: "Result", suite: str, before: set[str]) -> None:
    """⭐ Уборка — тоже поведение, только без падения и без красноты: утечку
    выдаёт один заполняющийся диск. Поэтому набор, оставивший что-то в папке
    прогона, краснеет СВОИМ именем, а оставленное сносится сразу, чтобы
    следующий набор не унаследовал чужое (и чтобы красное не повторялось на
    каждом следующем)."""
    left = sorted(_run_entries() - before)
    if not left:
        return
    res.failed.append((f"{suite}: оставил временное",
                       ", ".join(left[:5]) + (" …" if len(left) > 5 else "")))
    for name in left:
        path = RUN_TMP / name
        if path.is_dir():
            _rmtree_settled(path)
        else:
            try:
                path.unlink()
            except OSError:
                pass


# Часовой пояс клиники — тот же, что engine.TZ (harness приложение не
# импортирует: он поднимает его подпроцессом).
TZ = ZoneInfo("Europe/Chisinau")


def clinic_today() -> date:
    """«Сегодня» КЛИНИКИ, не машины. Движок считает день по Кишинёву, а
    раннер CI живёт по UTC: между 21:00 и 24:00 UTC у них разные даты, и
    всё, что брало `date.today()`, ночью краснело — «сегодня закрытый день»,
    баннер прошедшего часа, дата завершения визита, пустой день кассы
    (18.09, четыре проверки). На ПК с местным поясом значение то же.
    Внутри `with Clock(…)` — день поддельных часов."""
    return clinic_now().date()


def clinic_now() -> datetime:
    """«Сейчас» клиники — по поддельным часам, если идёт блок `with Clock(…)`."""
    return _CLOCKS[-1].now() if _CLOCKS else datetime.now(TZ)


# ---------- поддельные часы: прогон и сервер в назначенном времени ----------

FAKECLOCK = pathlib.Path(__file__).resolve().parent / "fakeclock"
_CLOCK_MARK = "[fakeclock]"         # отметка sitecustomize в логе сервера
_CLOCKS: list["Clock"] = []         # действующие блоки, внутренний — последним


def _retry(fn, budget: float = 2.0):
    """Файл часов в это мгновение может читать сервер, а Windows не даёт
    заменить или стереть файл, открытый чужим процессом. Чтение — микросекунды,
    поэтому хватает короткого ожидания."""
    deadline = time.time() + budget
    while True:
        try:
            return fn()
        except PermissionError:
            if time.time() > deadline:
                raise
            time.sleep(0.01)


class Clock:
    """Поддельные часы: прогон и серверы живут в назначенном времени.

        with Clock(datetime(2026, 10, 4, 10, 0, tzinfo=TZ)) as clock:
            clinic_today()             # 04.10 — у прогона
            with Server() as s:        # и у сервера: 04.10, 10:00, часы идут
                clock.set(…)           # переставить обоих, сервер не гасится

    Внутри блока `clinic_today()`/`clinic_now()` и КАЖДЫЙ `Server()`,
    стартовавший в нём, идут по этим часам. Так существующий набор целиком
    переезжает в воскресенье или в полночь одной строкой, без правки самого
    набора (`test_react_default.suite_fresh_day_off`). `Server(clock=…)`
    называет часы явно; из вложенных блоков действует внутренний. Наивное
    время — стенные часы КЛИНИКИ.

    Устройство: сдвиг от настоящего времени, секундами, в файле папки
    прогона. Сервер перечитывает его на каждом now() —
    `tests/fakeclock/sitecustomize.py` через PYTHONPATH, там же разобрано,
    чего он не достаёт; прогон считает здесь той же формулой.
    ⭐ Дважды подмену собирали руками вне репозитория — 24.09 (полночь живого
    /admin) и 27.09 (воскресная краснота `suite_fresh`); отсюда харнесс.
    ⚠️ В процессе ПРОГОНА двигаются только `clinic_today()`/`clinic_now()`:
    `datetime.now(TZ)`, написанный в наборе прямо, и `app.*`, исполняемый в
    самом прогоне, живут по настоящим часам. Набор, который пойдёт под часы,
    берёт время у харнесса.
    """

    def __init__(self, at: datetime):
        self._at = at
        self._shift = timedelta(0)
        self.file: pathlib.Path | None = None

    def __enter__(self) -> "Clock":
        fd, name = tempfile.mkstemp(prefix="dp_clock_", suffix=".txt", dir=RUN_TMP)
        os.close(fd)
        self.file = pathlib.Path(name)
        try:
            self.set(self._at)
        except BaseException:
            self.__exit__(None, None, None)   # `with` его после отказа не позовёт
            raise
        _CLOCKS.append(self)
        return self

    def __exit__(self, *exc) -> None:
        if self in _CLOCKS:
            _CLOCKS.remove(self)
        if self.file is None:
            return
        for path in (self.file, self._next()):
            try:
                _retry(lambda p=path: p.unlink(missing_ok=True))
            except OSError:
                pass                     # останется — назовёт сторож уборки
        self.file = None

    def _next(self) -> pathlib.Path:
        return self.file.with_name(self.file.name + ".new")

    def set(self, at: datetime) -> None:
        """Переставить часы — у прогона и у живых серверов разом.

        ⚠️ Файл ЗАМЕНЯЕТСЯ целиком, а не переписывается на месте: чтение
        между усечением и записью дало бы серверу пустой файл. Сервер,
        прочитавший пустое или битое, держит прежний сдвиг."""
        if self.file is None:
            raise RuntimeError("часы не заведены: Clock работает внутри `with`")
        if at.tzinfo is None:
            at = at.replace(tzinfo=TZ)
        text = repr((at - datetime.now(timezone.utc)).total_seconds())
        nxt = self._next()
        nxt.write_text(text, encoding="utf-8")
        _retry(lambda: os.replace(nxt, self.file))
        self._shift = timedelta(seconds=float(text))

    def now(self, tz=TZ) -> datetime:
        """⭐ Сдвиг — к UTC, пояс — потом, как у сервера: у aware-даты сложение
        идёт по стенным часам, и `now(tz) + сдвиг` через переход на зимнее
        время ошибся бы на час."""
        return (datetime.now(timezone.utc) + self._shift).astimezone(tz)

    def env(self, pythonpath: str = "") -> dict:
        """Окружение сервера под этими часами; прежний PYTHONPATH сохраняется."""
        if self.file is None:
            raise RuntimeError("часы не заведены: сервер под Clock стартует "
                               "внутри `with Clock(…)`")
        return {"PYTHONPATH": os.pathsep.join(p for p in (str(FAKECLOCK), pythonpath) if p),
                "FAKECLOCK_FILE": str(self.file)}


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
        """Код ответа — язык, которым журнал отвечает: у формы — из редиректа
        (?msg=…), у JSON API — поле `code` конверта (`layout.msg_json`).
        Словарь у них один (`MSG_BANNER`), поэтому и проверка одна, кто бы ни
        ответил: перевод набора со старой формы на API (снятие старого
        интерфейса, 12.10) меняет вызов, а не проверку."""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.location).query)
        code = (q.get("msg") or [""])[0]
        if code or self.location:
            return code
        if not self.header("content-type").startswith("application/json"):
            return ""
        try:
            doc = json.loads(self.body)
        except ValueError:
            return ""
        return str(doc.get("code") or "") if isinstance(doc, dict) else ""

    def __repr__(self) -> str:
        return f"<{self.status} msg={self.msg!r} loc={self.location!r}>"


class _OneWrite(http.client.HTTPConnection):
    """Соединение клиента прогона: небольшой запрос уходит в сокет ОДНОЙ
    записью — строка запроса, заголовки и тело вместе.

    ⛔ Штатный http.client пишет заголовки и тело ДВУМЯ `sendall`, а urllib
    всегда просит `Connection: close`. Маршрут, которому тело не нужно,
    отвечает по одним заголовкам — ворота лицензии (423 в шлюзе до разбора
    тела), отказ прав, 404, — и uvicorn по `close` сразу закрывает сокет.
    Застрянь клиент между двумя записями (замер 12.10: первая `sendall`
    возвращалась через 3–27 мс, когда сервер уже ответил и закрыл), тело
    приходит в закрытый сокет, сервер отвечает RST, и Windows выбрасывает
    УЖЕ ПРИШЕДШИЙ ответ: чтение падает `ConnectionAbortedError` 10053 вместо
    423. «Ворота в readonly» падали так раз в 3–15 прогонов, каждый раз на
    другом JSON-POST: тело приходило позже начала ответа на 6–19 запросах из
    42 в КАЖДОМ прогоне, а падал тот, где закрытие успевало раньше тела.
    Признак класса — «набор упал: ConnectionAbortedError … socket.py», а не
    красная проверка; повтор «лечил», потому что окно узкое.
    ⭐ Чинится клиент, а не ворота: браузер (WebView2) держит соединение
    (keep-alive), и uvicorn после раннего ответа сам дочитывает тело и
    отвечает на следующий запрос в том же сокете (проверено сырыми сокетами
    12.10). Ранний отказ без чтения тела — законный HTTP; ломалась только
    пара «close + две записи», которой у браузера нет.
    ⚠️ Одной записью — только запрос до `MERGE_MAX` (обычные JSON и формы):
    он приходит серверу одним куском, заголовков без тела у того не бывает. Крупнее — штатно, двумя записями: одним куском он не придёт
    всё равно, а раннему отказу на мегабайтах одна запись ВРЕДИТ (замер
    12.10, 9 МБ на 404 до чтения тела: штатно ответ 10/10, одной записью
    обрыв 10/10; 1 МБ — обрыв 2/10 против 6/10). Мегабайты на маршрут,
    отвечающий до тела, обрываются и штатно — см. `test_demo._upload`.
    """

    # С запасом меньше и сегмента петли (~64 КБ), и одного чтения сервера
    # (буфер proactor — 64 КБ): запрос не дробится ни там, ни там.
    MERGE_MAX = 32 * 1024

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending = b""

    def send(self, data):
        # Подключение — сразу, как у http.client: отказ соединения остаётся
        # внутри request(), и urllib по-прежнему заворачивает его в URLError.
        if self.sock is None:
            self.connect()
        data = bytes(data)
        if len(self._pending) + len(data) <= self.MERGE_MAX:
            self._pending += data
            return
        self._flush()            # крупное — как у http.client: сразу, по отдельности
        super().send(data)

    def _flush(self):
        data, self._pending = self._pending, b""
        if data:
            super().send(data)

    def getresponse(self):
        self._flush()
        return super().getresponse()


class _OneWriteHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_OneWrite, req)


class Client:
    """HTTP-клиент с куками и БЕЗ следования редиректам: код ответа и Location —
    это и есть проверяемое поведение журнала. Небольшой запрос уходит одной
    записью (`_OneWrite`) — иначе ранний отказ сервера обрывался 10053."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect, _OneWriteHandler)

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


# ---- фиша пациента через JSON API (экраны фиши — только React с 13.10) ----
# До снятия старого интерфейса наборы заводили фишу формой «Pacient nou» и
# искали её id разбором старой страницы списка (`<tr id='plr…'>`). Тот же
# путь, которым это делает клиника, теперь — JSON API экрана.

def new_patient(c: Client, name: str, phone: str = "", **fields) -> int:
    """Новая фиша (`POST /api/patients`, диалог «Pacient nou») — её id.
    ⚠️ Совпавший телефон, как и в продукте, ОТКРЫВАЕТ существующую фишу
    (`dup_pat`): id тогда чужой — набору, которому важна именно новая, код
    ответа проверять самому."""
    r = c.post_json("/api/patients", {"name": name, "phone": phone, **fields})
    doc = json.loads(r.body)
    if not doc.get("ok"):
        raise AssertionError(f"фиша не заведена: {r.status} {r.body[:200]}")
    return int(doc["data"]["id"])


def shell_model(page: str) -> dict:
    """Модель оболочки React со страницы — так её читает клиент: JSON в
    атрибуте `data-shell="…"`, экранированный как HTML (`layout.react_shell`).
    Баннеры каркаса (демо, лицензия, …) у React-экрана живут здесь сигналами,
    а не разметкой. Узла нет (старая страница) — пустой словарь."""
    if 'data-shell="' not in page:
        return {}
    return json.loads(html.unescape(page.split('data-shell="', 1)[1].split('"', 1)[0]))


def shell_signal(page: str, name: str) -> dict:
    """Сигнал `name` оболочки React — `{"shown", "html"}`, баннер каркаса так,
    как его рисует клиент. Проза баннера (`<b>`, `href='…'`) читается здесь
    сырой: в странице она экранирована внутри атрибута.
    ⛔ Модели на странице нет — AssertionError, а не пустой сигнал: проверка
    «баннера нет» по странице без модели зеленела бы молча (журнал стал
    оболочкой React 13.10, и проверки, читавшие разметку `/admin`, ослепли)."""
    model = shell_model(page)
    if not model:
        raise AssertionError(f"на странице нет модели оболочки (data-shell): {page[:200]!r}")
    return model["signals"][name]


def pid_by_phone(c: Client, query: str) -> int:
    """id первой фиши, которую находит поиск списка (`GET /api/patients?q=`):
    телефон, имя, номер дела — как ищет стойка. Порядок — экрана (последний
    визит); архивные находятся, раз их спросили поиском."""
    r = c.get("/api/patients?q=" + urllib.parse.quote(query))
    rows = json.loads(r.body)["data"]["rows"] if r.status == 200 else []
    if not rows:
        raise AssertionError(f"поиск {query!r} никого не нашёл: {r.status} {r.body[:200]}")
    return int(rows[0]["id"])


# ---- журнал через JSON API (экраны журнала — только React с 13.10) ----
# До снятия старого интерфейса наборы записывали визит формой `/admin/add` и
# искали его номер разбором старой страницы дня (`/admin/status/<id>` в
# «Lista zilei»). Тот же путь, которым это делает клиника, теперь — окно
# «Programare nouă» и модель дня экрана «Programări».

def add_appt(c: Client, day: str, time: str, name: str, phone: str = "",
             doctor: str = "d2", service: str = "consult", **fields) -> Reply:
    """Ручная запись (`POST /api/schedule/appointments`). Код — `reply.msg`
    (`ok`, `ok_past`, `ok_other` — удача; остальное — отказ, как у окна)."""
    return c.post_json("/api/schedule/appointments",
                       {"date": day, "time": time, "doctor": doctor,
                        "service": service, "name": name, "phone": phone, **fields})


def day_model(c: Client, day: str = "", doctor: str = "", f: str = "") -> dict:
    """День экрана «Programări» данными (`GET /api/schedule/day`): канва,
    «Lista zilei», карточки, форма. Пустой `day` — сегодня сервера."""
    q = urllib.parse.urlencode({k: v for k, v in (("date", day), ("doctor", doctor),
                                                   ("f", f)) if v})
    r = c.get("/api/schedule/day" + (f"?{q}" if q else ""))
    if r.status != 200:
        raise AssertionError(f"день {day!r} не отдан: {r.status} {r.body[:200]}")
    return json.loads(r.body)["data"]


def panel_live(c: Client, day: str = "") -> dict:
    """Живое состояние «Panoul principal» (`GET /api/schedule/live?screen=panel`):
    канва, повестка, мини-календарь, «La recepție». Пустой `day` — сегодня."""
    r = c.get("/api/schedule/live?screen=panel" + (f"&date={day}" if day else ""))
    if r.status != 200:
        raise AssertionError(f"канал панели не ответил: {r.status} {r.body[:200]}")
    return json.loads(r.body)["data"]


def appt_id(c: Client, day: str, name: str = "") -> int:
    """Номер визита дня — строка «Lista zilei» с этим именем пациента; без
    имени — ПЕРВЫЙ визит дня по времени (так его находил разбор старого
    списка). Заметки стойки не считаются: у них нет имени."""
    rows = [r for r in day_model(c, day)["list"] if not r["is_note"]
            and (not name or r["name"] == name)]
    if not rows:
        raise AssertionError(f"визита {name!r} на {day} нет в списке дня")
    return int(rows[0]["id"])


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
        tmp_before = _run_entries()
        try:
            fn(res)
        except Exception as e:  # noqa: BLE001 — падение набора не должно съесть отчёт
            # Файл и строка последнего кадра: без них «набор упал:
            # OperationalError('disk I/O error')» на чужом раннере не говорит,
            # какая из двадцати баз набора не открылась (первый прогон CI 17.09)
            tb = traceback.extract_tb(e.__traceback__)
            where = f" — {pathlib.Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
            res.failed.append((f"{name}: набор упал", repr(e) + where))
        _check_left(res, name, tmp_before)
        done = len(res.passed) + len(res.failed) - before
        print(f"    проверок: {done}")
    # ⚠️ Сторож уборки выше слеп, если временное пишется МИМО папки прогона:
    # чистая папка тогда значит «сюда не писали», а не «прибрали».
    print("\n=== Уборка: временное прогона ===")
    res.ok("всё временное прогона живёт в его папке",
           tempfile.gettempdir() == str(RUN_TMP) == os.environ.get("TEMP"),
           f"tempfile → {tempfile.gettempdir()}, TEMP → {os.environ.get('TEMP')}, "
           f"а папка прогона {RUN_TMP}")
    print("    проверок: 1")
    print("\n" + "=" * 60)
    for label, why in res.failed:
        print(f"  ✗ {label}: {why}")
    total = len(res.passed) + len(res.failed)
    print(f"\n{len(res.passed)}/{total} прошло за {time.time() - t0:.1f} с")
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit("Это каркас. Запускать: python tests\\run_tests.py")
