"""Каркас тестов DentPilot: поднять сервер, поговорить с ним по HTTP.

Зависимостей нет намеренно — только стандартная библиотека. `.venv-desktop`
это окружение СБОРКИ, и всё лишнее в нём однажды окажется внутри exe; а тесты
должны запускаться и там, где ставить пакеты некому.

Сервер поднимается на свободном порту со своей временной базой, поэтому прогон
не задевает ни установленную программу (порт 8088), ни песочницы.
"""
from __future__ import annotations

import atexit
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
                 bot: pathlib.Path | None = None, keep_dir: bool = False):
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
        вносится в КОПИЮ; настоящее дерево не трогается никогда."""
        self.port = free_port()
        self.bot = pathlib.Path(bot) if bot else BOT
        self._made_dir = dir_ is None
        self._own_dir = self._made_dir and not keep_dir
        self.dir = pathlib.Path(dir_) if dir_ else pathlib.Path(
            tempfile.mkdtemp(prefix="dp_test_"))
        self.clinic = self.dir / "clinic.json"
        if not self.clinic.exists():
            shutil.copy(FIXTURES / clinic, self.clinic)
            self._pin_legacy()
        self.extra_env = env or {}
        self.proc: subprocess.Popen | None = None
        # %TEMP% самого сервера — заводится на старте, уходит вместе с ним
        # (почему свой — в __enter__)
        self.tmp: pathlib.Path | None = None

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
        env.update({
            "CLINIC_CONFIG": str(self.clinic),
            "DATABASE_URL": f"sqlite:///{self.dir / 'dental.db'}",
            "ADMIN_KEY": PIN,
            "DENTART_NO_RESTART": "1",       # тест-хук: не перезапускать процесс
            "TELEGRAM_TOKEN": "",            # адаптер Telegram не поднимать
            "TMPDIR": str(self.tmp), "TEMP": str(self.tmp), "TMP": str(self.tmp),
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
                raise self._startup_failed("сервер упал при старте")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=1):
                    return self
            except Exception:  # noqa: BLE001 — ещё не поднялся
                time.sleep(0.3)
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
