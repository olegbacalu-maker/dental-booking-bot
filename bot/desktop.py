"""DentPilot Desktop — лаунчер .exe-издания (без Docker и VPS).

Данные КЛИНИКИ живут в отдельной папке (`data_root()` ниже), а не рядом с exe:
clinic.json (профиль, правится в Setări), dental.env (TELEGRAM_TOKEN и
ADMIN_KEY), data/dental.db (SQLite), data/dentpilot.log (лог).
⛔ Разделение намеренное: программа уезжает в `Program Files`, доступный только
на чтение. Рядом с exe остаётся лишь то, что кладёт СБОРКА (`demo.flag`,
`portable.flag`). Обычный режим — собственное окно приложения
(WebView2); закрытие окна останавливает программу.
Профиль окна (куки, кэш, localStorage) ПОСТОЯННЫЙ и свой у каждой учётки
Windows (`profile_dir()`), а вход переживает перезапуск по РЕЖИМУ установки
(`_session_policy`): постоянный профиль ≠ постоянный вход. Второй запуск
(двойной клик по ярлыку при открытой программе) выводит окно первого
экземпляра на передний план и выходит — второго окна нет (`_claim_instance`,
`_focus_existing`).
DENTART_BROWSER_MODE=1 — старый режим: консоль + системный браузер.
(env-переменные исторически с префиксом DENTART_ — не трогаем ради
совместимости с dental.env уже установленных клиник.)"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
import sys
import threading
import time
import urllib.request
import webbrowser


def exe_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):  # PyInstaller
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def bundle_dir() -> pathlib.Path:
    return pathlib.Path(getattr(sys, "_MEIPASS",
                                pathlib.Path(__file__).resolve().parent))


def _fatal_dir(path: pathlib.Path, err: Exception) -> None:
    """Папка клиники недоступна — сказать это ВСЛУХ и выйти.

    ⛔ Единственный способ сообщить здесь — окно: сборка идёт `--noconsole`
    (stdout/stderr ещё None), лога ещё нет, и до `sys.excepthook` дело не
    дойдёт — этот код исполняется на уровне модуля. Без этого окна отказ прав
    на `ProgramData` выглядит как «ярлык не работает», и чинить клиника пойдёт
    не то.
    ⚠️ Текст клинике по-румынски и с ПУТЁМ: без пути поддержка по телефону
    не сможет спросить ничего полезного.
    """
    _box(f"DentPilot nu poate folosi dosarul cu datele clinicii:\n\n{path}\n\n"
         f"{err.__class__.__name__}: {err}\n\n"
         "Verificați drepturile pe acest dosar sau porniți instalarea din nou.")
    raise SystemExit(2)


def _box(msg: str) -> None:
    """Сказать клинике вслух. ⛔ Единственный способ на этом этапе: сборка идёт
    `--noconsole`, лога может ещё не быть, а `sys.excepthook` ставится позже."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "DentPilot", 0x10)
    except Exception:                      # noqa: BLE001 — не на Windows / нет user32
        print(msg, file=sys.__stderr__ or sys.stdout)


def data_root() -> pathlib.Path:
    """Папка КЛИНИКИ. Решает ОДИН лаунчер — он один знает раскладку машины.

    ⛔ Порядок именно такой, и каждая ветка тут за своё:
      1. `$DENTART_DATA_DIR` из окружения ПРОЦЕССА — им пользуются установщик,
         будущий сайдкар Tauri и стенд. ⚠️ Из `dental.env` этот ключ НЕ берётся
         и взяться не может: сам файл лежит ВНУТРИ искомой папки, и ключ в нём
         замкнул бы круг — второй запуск разрешился бы в другое место. Поэтому
         переменная выставляется ЖЁСТКО и ДО чтения `dental.env` (ниже).
      2. `portable.flag` рядом с exe — флешка и выезд: раскладка «всё в одной
         папке», как было до переезда. Флаг БУЛЕВ и пути не несёт: путь в
         текстовом файле можно испортить, а флаг — нет.
      3. Иначе — `%ProgramData%\\DentPilot`, общая для всех учёток машины.
    ⚠️ Ветки «старая установка рядом с exe» здесь НЕТ и не будет: эта функция
    отвечает на вопрос «куда положено», и выводить ответ из положения exe
    нельзя — программа, переставленная в `Program Files`, завела бы пустую базу
    рядом с настоящей. На вопрос «а где картотека ЛЕЖИТ на самом деле»
    отвечает следующий шаг (`relocate.root_for`, P2), и отвечает не положением
    exe самим по себе, а положением, ПОДТВЕРЖДЁННЫМ маркерами данных.
    ⭐ Разница принципиальная: здесь — раскладка, там — находка.
    """
    raw = os.environ.get("DENTART_DATA_DIR", "").strip().strip("\"'")
    if raw and pathlib.Path(raw).is_absolute():
        return pathlib.Path(raw)
    if (BASE / "portable.flag").exists():
        return BASE
    return pathlib.Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "DentPilot"


BASE = exe_dir()

# ⛔ ПЕРВОЕ, что делает лаунчер, и раньше всего остального: привилегированный
# запуск обязан сделать ровно одно дело и выйти. Строкой ниже начинаются
# побочные действия — вычисление корня, mkdir, лог, — а процесс под
# администратором не должен ни создавать папки клиники (они достались бы
# админу, и обычный запуск потерял бы к ним доступ), ни поднимать сервер.
# ⚠️ Список того, что вообще может случиться за UAC, — `app/privileged.py`.
from app import privileged  # noqa: E402 — предзагрузочный слой, без проекта

# ⚠️ Раскладку передаём СВОЕЙ функцией: у неё три ветки ($DENTART_DATA_DIR,
# portable.flag, %ProgramData%), и второй вычислитель разошёлся бы с этим
# молча. ⛔ Окружение сюда не доезжает: повышенный процесс запускает Windows,
# а не мы, и `$DENTART_DATA_DIR`, выставленный лаунчером, в нём не виден.
if (_code := privileged.handle_argv(sys.argv[1:], data_root)) is not None:
    raise SystemExit(_code)

ROOT = data_root()

# ⭐ P2, шаги 1–3. Спрашиваем ДО всего: до mkdir, до создания профиля, до
# первого открытия базы. Позже спрашивать бессмысленно — журнал назначения уже
# создан, и всякий ответ превращается в «картотека в обоих корнях».
# ⛔ Ответ `unique` означает «работаем в СТАРОМ корне», а не «переезжаем».
# Копирования здесь нет; есть отказ завести пустой журнал рядом с настоящим —
# то самое, что случалось после одноклик-обновления, где exe подменяется на
# месте, перезапускается планировщиком и приходит в чистое окружение.
# ⚠️ Разбор веток и почему `unconfirmed`/`split` стартом не распоряжаются — в
# `app/relocate.py`. Стоимость — пара stat'ов и 16 байт заголовка.
from app import relocate  # noqa: E402 — предзагрузочный слой, без проекта

ROOT, _verdict = relocate.root_for(ROOT)
data_dir = ROOT / "data"

# ⛔ ЖЁСТКО и ЗДЕСЬ, а не `setdefault` и не ниже. Двумя причинами.
# 1. Ниже окружение пополняется ВСЕМИ ключами `dental.env` подряд, без белого
#    списка. Строка `DENTART_DATA_DIR=` в том файле (а он лежит ВНУТРИ папки,
#    которую сам же и определяет)
#    разрешилась бы у приложения в другое место, чем у лаунчера: база одна,
#    профиль другой. Замкнутый круг, который виден только со второго запуска.
#    ⚠️ Имя той функции здесь НЕ пишем: сторож `test_launcher` ищет его
#    текстом и посчитал бы этот комментарий за сам вызов.
# 2. Приложение (`paths.data_root()`) читает ровно эту переменную и обязано
#    получить ТО ЖЕ значение, которое лаунчер уже использовал для mkdir.
os.environ["DENTART_DATA_DIR"] = str(ROOT)


def profile_dir() -> pathlib.Path:
    """Папка профиля WebView2 (куки входа, кэш, localStorage) — ПОСТОЯННАЯ.

    ⭐ С 08.10.2026. До того окно шло в приватном режиме: pywebview заводил
    временный профиль на каждый запуск и не убирал его (`os._exit` минует
    уборку) — ~15 МБ мусора в %TEMP% за запуск у любой клиники, и кука входа
    лежала в этом профиле, поэтому PIN спрашивался при КАЖДОМ старте — не по
    замыслу, а побочно.
    ⛔ Своя у каждой учётки Windows (`%LOCALAPPDATA%\\DentPilot\\webview`), а не в
    папке клиники: `ProgramData` общая на всех учёток, и кука входа одного
    человека досталась бы другому. И не рядом с exe: `Program Files` только на
    чтение. `portable.flag` (флешка, выезд) — всё в одной папке: `ROOT\\webview`.
    ⚠️ Читается из окружения ПРОЦЕССА (`DENTART_PROFILE_DIR` — стенд), ДО слияния
    `dental.env`: строка в файле клиники не должна уводить профиль в другое место.
    """
    raw = os.environ.get("DENTART_PROFILE_DIR", "").strip().strip("\"'")
    if raw and pathlib.Path(raw).is_absolute():
        return pathlib.Path(raw)
    if (BASE / "portable.flag").exists():
        return ROOT / "webview"
    local = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return pathlib.Path(local) / "DentPilot" / "webview"


PROFILE_DIR = profile_dir()

# ⛔ И вердикт — туда же, ЖЁСТКО и ОБЕИМИ ветками. Причина та же, что у строки
# выше, но здесь она острее: ниже окружение пополняется всеми ключами
# `dental.env` подряд, а сам файл лежит В КОРНЕ и правится клиникой. Строка
# `DENTART_SPLIT_SOURCE=...` в нём нарисовала бы экран раздвоения на здоровой
# машине — при чистом логе, верной раскладке и без единого признака подвоха.
# Поэтому переменная либо ставится здесь, либо СНИМАЕТСЯ здесь; «в нормальной
# ветке не трогаем» — это и есть дыра.
# ⚠️ Едет ПУТЬ источника, а не готовый рассказ о нём: файловые факты (размер,
# дата, шифрование, `-wal`) страница снимает заново в момент показа. Описание,
# записанное при старте, протухло бы молча — прайор про `layout.data_folder()`.
if _verdict["outcome"] == "split" and _verdict["source"]:
    os.environ[relocate.SPLIT_ENV] = str(_verdict["source"]["root"])
else:
    os.environ.pop(relocate.SPLIT_ENV, None)

# ⛔ Первое, что может отказать, и отказать беззвучно. Раньше здесь стоял
# `mkdir(exist_ok=True)` без parents и без перехвата: папка была своя, поэтому
# отказа не бывало. На `ProgramData` с неверными правами это «двойной клик не
# делает ничего» — ни окна, ни консоли, ни лога, потому что stderr и лог
# настраиваются ТРЕМЯ строками ниже. Поэтому: parents=True и явная жалоба.
try:
    data_dir.mkdir(parents=True, exist_ok=True)
except OSError as e:
    _fatal_dir(data_dir, e)

# noconsole-сборка: sys.stdout/stderr = None → uvicorn падает на isatty().
# Подкладываем безопасные потоки; stderr пишем в файл (видны краши).
# ⚠️ Стоит ВЫШЕ первого чтения файлов намеренно: dental.env правит сама
# клиника, и падение на его разборе иначе гибло бы молча — stderr ещё None,
# лога ещё нет, двойной клик по ярлыку «не делает ничего».
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(data_dir / "dentpilot.err.log", "a", encoding="utf-8")  # noqa: SIM115

# ⛔ `encoding="utf-8"` ОБЯЗАТЕЛЕН, и это не косметика. Без него `FileHandler`
# открывает файл в ANSI-кодировке МАШИНЫ (`locale.getpreferredencoding`), а у
# клиники Windows румынская: ANSI = cp1250, кириллицы в нём нет. Сообщение с
# русским текстом там не искажается — `logging` его ВЫБРАСЫВАЕТ целиком
# (UnicodeEncodeError → handleError), и в файл не попадает ни строки. Проверено
# опытом 21.09: лог с cp1250 принял латинскую строку и потерял русскую, след
# остался только в stderr («--- Logging error ---»).
# ⚠️ Цена промаха — все 40 русских сообщений продукта, включая диагностику
# неудавшейся миграции индексов в `db.py`: ровно то, что поддержка читает,
# когда у клиники «после обновления не открывается». На машине разработчика
# дефекта НЕ ВИДНО — здесь ANSI это cp1251, и кириллица ложится штатно.
logging.basicConfig(
    filename=str(data_dir / "dentpilot.log"), level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)

# ⚠️ Вердикт пишется ЗДЕСЬ, а не там, где получен: там ещё нет ни лога, ни
# stderr — сборка идёт `--noconsole`. Уровень WARNING намеренно: всё, кроме
# «источников нет», это состояние, о котором поддержка обязана узнать из лога,
# не выспрашивая. ⛔ Окна не показываем ни на одной ветке: `unconfirmed` —
# норма здоровой установки, а окно на каждом запуске перестают читать.
if _verdict["outcome"] != "no-origin":
    logging.warning("раскладка: %s (%s); корень запуска %s; блокировки: %s",
                    _verdict["outcome"], _verdict["why"], ROOT,
                    _verdict["blockers"] or "нет")

cfg_path = ROOT / "clinic.json"
if not cfg_path.exists():
    # Первый запуск. Два РАЗНЫХ вшитых профиля, а не один с подчистками:
    #   demo.flag есть  -> clinic.json     (показ: 4 врача, прайс, демо-записи)
    #   demo.flag нет   -> clinic_new.json (реальная клиника: пустой шаблон)
    # Выдуманные врачи в боевом журнале опаснее демо-пациентов: на «Dr. Elena
    # Rusu», которого в клинике нет, можно записать живого человека, а чужой
    # прайс бот назовёт пациенту как настоящий.
    src = "clinic.json" if (BASE / "demo.flag").exists() else "clinic_new.json"
    shutil.copy(bundle_dir() / "app" / src, cfg_path)

from app import install_info  # noqa: E402 — предзагрузочный слой, без проекта

env_path = ROOT / "dental.env"
if not env_path.exists():
    # ⭐ Канал обновления берётся ЗДЕСЬ и только здесь — при ПЕРВОМ создании
    # файла. Намерение записал установщик в install.json; дальше файлом владеет
    # клиника, и сверять канал на каждом старте НЕЛЬЗЯ: это отняло бы у неё
    # возможность переключиться руками, а у нас — единственного писателя.
    # ⚠️ Зачем вообще: флаг канарейки жил только в dental.env, а чистая
    # установка создавала файл заново — машина молча возвращалась на stable.
    # Случалось дважды и выглядело как «обновление не пришло».
    try:
        _info = install_info.read(BASE)
    except install_info.InstallInfoError as e:
        # ⛔ Молча подставить stable нельзя: это ровно та беда. Но и держать
        # клинику взаперти из-за испорченного файла в папке программы
        # несоразмерно — канал работать не мешает. Поэтому громко и дальше.
        logging.error("install.json не читается: %s", e)
        _box(f"install.json:\n{e}\n\nProgramul pornește pe canalul obișnuit.")
        _info = None
    env_path.write_text(
        "# Token botului Telegram (de la @BotFather):\nTELEGRAM_TOKEN=\n"
        "# Parola jurnalului /admin (gol = deschis):\nADMIN_KEY=\n"
        + install_info.channel_line(_info),
        encoding="utf-8",
    )
from app import dpapi, envfile  # noqa: E402 — путь к env вычислен строкой выше

for k, v in envfile.read_all(env_path).items():
    os.environ.setdefault(k, v)

# Токен бота лежит в dental.env зашифрованным средствами Windows: файл,
# унесённый с этой машины, бесполезен. Расшифровать надо ЗДЕСЬ, до старта
# приложения — дальше TELEGRAM_TOKEN читается из окружения как обычная строка.
dpapi.unlock_env_token(env_path)

os.environ.setdefault("CLINIC_CONFIG", str(cfg_path))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{data_dir / 'dental.db'}")

# путь к env-файлу — для страницы настроек (правка токена из UI)
os.environ["DENTART_ENV_FILE"] = str(env_path)


def _auto_backup() -> None:
    """Копия базы при каждом старте. Сама логика (шифрованные копии, ротация,
    временное имя против битых файлов-обманок) — в `app.core.autobackup`:
    тело desktop.py тестами неимпортируемо, а упавший на середине бэкап уже
    однажды оставлял мусор, который ротация считала новейшей копией.
    ⚠️ Импорт `app.core.autobackup` тут возможен ровно потому, что тот не
    тянет `storage`/`db`: лаунчер работает до сборки приложения.
    """
    try:
        from app.core import autobackup
        done = autobackup.make_backup(data_dir)
        if done is not None:
            logging.warning("Auto-backup: %s", done.name)
    except Exception as e:  # noqa: BLE001 — бэкап не должен блокировать старт
        logging.warning("Auto-backup FAILED: %r", e)


# DENTART_PORT правит сама клиника — диалог «портул e ocupat» это прямо
# советует, — поэтому мусор в нём ожидаем. Раньше голый int() падал ЗДЕСЬ, на
# верхнем уровне модуля, до excepthook и до любого MessageBox: двойной клик по
# ярлыку «не делал ничего», а клинику только что попросили править этот ключ.
_port_raw = os.environ.get("DENTART_PORT", "").strip()
PORT = envfile.parse_port(_port_raw) or 8088
if _port_raw and envfile.parse_port(_port_raw) is None:
    logging.error("DENTART_PORT invalid: %r - folosim 8088", _port_raw)
    _port_warn = (f'DENTART_PORT invalid: "{_port_raw}" — se folosește portul '
                  f"8088.\nCorectați valoarea în dental.env "
                  f"(un număr între 1 și 65535).")
    if os.environ.get("DENTART_BROWSER_MODE") == "1":
        print(_port_warn)
    else:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, _port_warn, "DentPilot", 0x30)
        except Exception:  # noqa: BLE001 — не-Windows/без user32
            pass
# Доступ с телефона (Setări → Acces de pe telefon): 0.0.0.0 ТОЛЬКО по явному
# DENTART_LAN=1 из dental.env. По умолчанию — 127.0.0.1, сетевого доступа НЕТ.
# Окно программы и single-instance guard ходят через loopback в обоих режимах.
HOST = "0.0.0.0" if os.environ.get("DENTART_LAN", "").strip() == "1" else "127.0.0.1"
URL = f"http://127.0.0.1:{PORT}/admin"
# Заголовок окна — по нему второй запуск находит первое окно; у нестандартного
# порта (DENTART_PORT, стенд) — с портом, иначе две программы на одной машине
# (клиника и стенд) путали бы окна друг друга
TITLE = "DentPilot — registrul clinicii" + (f" · :{PORT}" if PORT != 8088 else "")


def _install_mode() -> str:
    """Режим установки (deployment-modes.md): `install.json` рядом с программой;
    без файла (исходники, стенд) — `DENTART_MODE`, и только у несобранной."""
    try:
        info = install_info.read(BASE)
    except install_info.InstallInfoError:
        info = None
    if info:
        return info["mode"]
    if not getattr(sys, "frozen", False):
        m = os.environ.get("DENTART_MODE", "").strip()
        if m in install_info.MODES:
            return m
    return install_info.MODE_DEFAULT


def _session_policy(mode: str) -> str:
    """Переживает ли ВХОД перезапуск окна. `keep` — standalone, clinic_server,
    clinic_client: открыл DentPilot — сразу работаешь. `clear` — shared_pc (одна
    учётка Windows на нескольких людей): куки входа снимаются при каждом старте и
    при закрытии окна, следующий запуск — экран входа; профиль (кэш, настройки
    интерфейса) при этом постоянный. ⭐ Постоянный профиль ≠ постоянный вход.
    Клиника может решить сама: `DENTART_SESSION=keep|clear` в dental.env."""
    raw = os.environ.get("DENTART_SESSION", "").strip().lower()
    if raw in ("keep", "clear"):
        return raw
    return "clear" if mode == "shared_pc" else "keep"


_MUTEX = None


def _claim_instance() -> bool:
    """Первый ли это экземпляр на этом порту: именованный мьютекс Windows, живёт
    ровно столько, сколько процесс. Второй запуск узнаёт о первом за миллисекунду
    и ДО того, как тот поднял сервер (заставка). Не Windows — считаем первым,
    порт проверит `/health`, как раньше."""
    global _MUTEX
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        _MUTEX = k32.CreateMutexW(None, False, f"Local\\DentPilot-{PORT}")
        return k32.GetLastError() != 183          # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 — не Windows / нет kernel32
        return True


def _focus_existing(timeout: float = 8.0) -> bool:
    """Вывести окно ПЕРВОГО экземпляра на передний план: верхнее видимое окно
    другого процесса с заголовком программы (`TITLE`, ровно таким); свёрнутое — развернуть. Первый
    может ещё подниматься (заставка) — ждём до `timeout`.
    ⚠️ Windows отдаёт передний план не всякому: процесс, не получавший ввода,
    может лишь мигнуть кнопкой в панели задач. Присоединение к очереди ввода
    переднего окна (`AttachThreadInput`) снимает замок без побочных нажатий;
    не вышло — мигаем кнопкой в панели задач (`FlashWindowEx`)."""
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
    except Exception:  # noqa: BLE001 — не Windows
        return False
    me = os.getpid()
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def find() -> int:
        found: list = []

        def cb(hwnd, _):
            if not u32.IsWindowVisible(hwnd):
                return True
            n = u32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value == TITLE:
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value != me:
                    found.append(hwnd)
            return True
        u32.EnumWindows(proto(cb), 0)
        return found[0] if found else 0

    deadline = time.time() + timeout
    while time.time() < deadline:
        if (hwnd := find()):
            if u32.IsIconic(hwnd):
                u32.ShowWindow(hwnd, 9)                      # SW_RESTORE
            k32 = ctypes.windll.kernel32
            fg = u32.GetForegroundWindow()
            tid_fg = u32.GetWindowThreadProcessId(fg, None) if fg else 0
            tid_me = k32.GetCurrentThreadId()
            joined = bool(tid_fg) and tid_fg != tid_me and bool(u32.AttachThreadInput(tid_fg, tid_me, True))
            u32.BringWindowToTop(hwnd)
            ok = bool(u32.SetForegroundWindow(hwnd))
            if joined:
                u32.AttachThreadInput(tid_fg, tid_me, False)
            if not ok:
                class FLASH(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                                ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                                ("dwTimeout", wintypes.DWORD)]
                f = FLASH(ctypes.sizeof(FLASH), hwnd, 3, 5, 0)   # FLASHW_ALL
                u32.FlashWindowEx(ctypes.byref(f))
            return True
        time.sleep(0.3)
    return False


def _already_running() -> bool:
    """Первый экземпляр уже слушает наш порт? (двойной клик по ярлыку —
    норма в клинике; раньше второй экземпляр падал на bind и показывал
    зомби-окно, подключённое к чужому серверу)."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/health", timeout=1.5) as r:
            return b'"dentpilot"' in r.read(200)  # отпечаток, не общий {"ok":true}
    except Exception:  # noqa: BLE001 — порт свободен или занят не нами
        return False


def _port_free_probe() -> bool:
    """Порт реально свободен? EXCLUSIVE-бинд пробой: uvicorn на Windows ставит
    SO_REUSEADDR и «успешно» биндится ПОВЕРХ чужого reuse-сервера — коннекты
    продолжают идти чужому (split-brain без единой ошибки, проверено тестом)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _run_server() -> None:
    import uvicorn

    from app.main import app  # noqa: E402 — env уже настроен

    config = uvicorn.Config(app, host=HOST, port=PORT,
                            log_level="warning", log_config=None)
    uvicorn.Server(config).run()


def _wait_ready(timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/health", timeout=1):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


def _browser_mode() -> None:
    print("=" * 62)
    print("  DentPilot Desktop - registrul clinicii")
    print(f"  Jurnal:  {URL}")
    print("  NU inchideti aceasta fereastra cat timp lucrati.")
    print("=" * 62)
    if os.environ.get("DENTART_NO_BROWSER") != "1":
        threading.Thread(
            target=lambda: (time.sleep(2.5), webbrowser.open(URL)),
            daemon=True).start()
    _run_server()


def _prepare(stage=lambda *a: None) -> None:
    """Что лаунчер делает с базой до старта приложения: перевод (шифрование) и
    копия. ⚠️ ПЕРЕД автобэкапом и перед стартом приложения: базу нельзя
    переводить, пока её кто-то держит открытой. Здесь этого не делает ещё никто."""
    try:
        from app.core import dbkey
        if (done := dbkey.apply_pending(data_dir)):
            logging.warning("DB crypt: %s", done)
    except Exception as e:  # noqa: BLE001 — переезд не должен блокировать старт
        logging.error("DB crypt FAILED: %r", e)
    stage("Se face copia de rezervă…", 38)
    _auto_backup()


SPLASH_MIN_S = 0.9               # заставка видна не меньше — иначе это вспышка


class _Boot:
    """Запуск под заставкой: перевод базы, копия, сервер — ровно ОДИН раз.

    ⭐ С 05.10.2026 окно открывается СРАЗУ, с заставкой (`app/splash.py`), а
    этот запуск идёт в потоке pywebview (`webview.start(func)`) и двигает её
    полоску по настоящим этапам; готов журнал — окно уходит на его адрес, и
    экран входа встаёт на том же фоне. Раньше окно появлялось только после
    подъёма сервера: несколько секунд после двойного клика не было видно ничего.
    ⭐ Запуск идёт ПАРАЛЛЕЛЬНО открытию окна, а не после: WebView2 сам
    поднимается секунды три-четыре (лог 05.10: «DentPilot start» → начало
    запуска 3.9 с), и в очередь эти две паузы складывались бы. Этапы, пришедшие
    до готовности страницы, не теряются: последний ждёт в `_last` и уходит в
    заставку, как только та загрузилась (`in_window`).
    ⚠️ Замок — потому что запуск может понадобиться и без окна: WebView2 нет,
    `webview.start` упал — тогда тот же запуск зовёт основной поток, и если
    фон уже начал его, run() дождётся первого: второго сервера не будет.
    """

    def __init__(self, policy: str = "keep") -> None:
        self._lock = threading.Lock()
        self._ok: bool | None = None
        self._window = None
        self.policy = policy
        self._last: tuple = ("Se pornește DentPilot…", 6, 0)
        self._t0 = time.monotonic()

    def stage(self, text: str, pct: int, upto: int = 0) -> None:
        """Этап запуска — в заставку, если она уже готова, иначе — до готовности."""
        self._last = (text, pct, upto)
        if self._window is not None:
            self._push()

    def _push(self) -> None:
        text, pct, upto = self._last
        try:
            self._window.evaluate_js(f"dpStage({json.dumps(text)},{pct},{upto})")
        except Exception:  # noqa: BLE001 — заставка украшает, запуск важнее
            pass

    def start(self) -> None:
        """Запуск в фоне — сразу, не дожидаясь окна."""
        threading.Thread(target=self.run, args=(self.stage,), daemon=True).start()

    def run(self, stage=None) -> bool:
        with self._lock:
            if self._ok is None:
                self._ok = self._go(stage or (lambda *a: None))
            return self._ok

    def _go(self, stage) -> bool:
        t0 = time.monotonic()
        stage("Se pregătește baza de date…", 16)
        _prepare(stage)
        t1 = time.monotonic()
        stage("Se pornește registrul…", 55, 92)
        threading.Thread(target=_run_server, daemon=True).start()
        if _wait_ready() and _already_running():
            # сколько клиника смотрит на заставку — и из чего это складывается
            logging.warning("запуск: журнал готов за %.1f с (база и копия %.1f, сервер %.1f)",
                            time.monotonic() - t0, t1 - t0, time.monotonic() - t1)
            return True
        # различаем ДВЕ разные беды: порт перехватили после нашей пробы ИЛИ
        # сервер упал сам (раньше во втором случае врали про порт)
        port_taken = not _port_free_probe() and not _already_running()
        logging.error("Server did not start on port %s (port_taken=%s)", PORT, port_taken)
        if port_taken:
            warn = (f"DentPilot nu a putut porni: portul {PORT} este ocupat de alt program.\n"
                    f"Inchideti programul care ocupa portul sau setati DENTART_PORT in dental.env.")
        else:
            warn = ("DentPilot nu a putut porni din cauza unei erori interne.\n"
                    "Detalii: data\\dentpilot.log (ultimele linii).\n"
                    "Trimiteti fisierul la contact@dentpilot.md — va ajutam.")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, warn, "DentPilot", 0x10)
        except Exception:  # noqa: BLE001 — не-Windows/без user32
            pass
        return False

    def in_window(self, window) -> None:
        """Поток pywebview: заставка готова — догнать её этапом и дождаться
        запуска, потом — журнал в том же окне."""
        self._window = window
        shown = time.monotonic()
        logging.warning("заставка на экране через %.1f с", shown - self._t0)
        self._push()                    # этап, пришедший раньше страницы
        if not self.run():              # дождаться фонового запуска
            window.destroy()            # сообщение уже показано — окно закрываем
            return
        # ⚠️ Запуск нередко готов РАНЬШЕ, чем WebView2 покажет страницу (05.10:
        # журнал за 3.8 с, окно — за 3.9): заставка тогда мелькнула бы долей
        # секунды, и это читалось бы сбоем. Минимум показа — только в этом
        # случае; на медленной машине он ничего не добавляет.
        time.sleep(max(0.0, SPLASH_MIN_S - (time.monotonic() - shown)))
        try:
            window.evaluate_js("dpDone()")
            time.sleep(0.45)            # полоска дошла и погасла — без рывка
        except Exception:  # noqa: BLE001
            pass
        if self.policy == "clear":
            self.forget_session()       # общий ПК: каждый запуск — с экрана входа
        window.load_url(URL)

    def forget_session(self) -> None:
        """Снять куки входа из постоянного профиля (режим `clear`): кэш и
        настройки интерфейса остаются, учётка — нет."""
        try:
            if self._window is not None:
                self._window.clear_cookies()
        except Exception as e:  # noqa: BLE001 — профиль важнее, чем уборка в нём
            logging.warning("cookie-urile nu s-au sters: %r", e)


def main() -> None:
    import atexit

    from app.engine import APP_VERSION
    logging.warning("DentPilot start v%s port=%s mode=%s pid=%s", APP_VERSION, PORT,
                    "browser" if os.environ.get("DENTART_BROWSER_MODE") == "1" else "window",
                    os.getpid())
    atexit.register(lambda: logging.warning("DentPilot clean exit pid=%s", os.getpid()))
    sys.excepthook = lambda *a: logging.error("UNCAUGHT", exc_info=a)

    first = _claim_instance()
    if not first or _already_running():
        # ⭐ Второй запуск (08.10): свой сервер не поднимаем и ВТОРОГО ОКНА НЕ
        # открываем — выводим окно первого экземпляра на передний план и выходим.
        # До того второе окно шло во временном профиле (снова PIN), а закрытие
        # первого гасило сервер под вторым — окно-зомби.
        logging.warning("Already running on port %s - focusing the first window", PORT)
        if os.environ.get("DENTART_BROWSER_MODE") != "1" and _focus_existing():
            return
        if _already_running():
            # окна нет (браузерный режим, окно не открылось) — вкладка, как раньше
            if os.environ.get("DENTART_BROWSER_MODE") == "1":
                print("DentPilot este deja pornit - deschid jurnalul in browser.")
            if os.environ.get("DENTART_NO_BROWSER") != "1":
                webbrowser.open(URL)
            return
        # мьютекс чей-то есть, а ни окна, ни сервера нет: первый ещё не поднялся
        # или застрял — ждём сервер ещё раз, иначе идём обычным путём (порт
        # проверит _port_free_probe)
        if _wait_ready(10.0) and _already_running():
            if _focus_existing(2.0):
                return
            if os.environ.get("DENTART_NO_BROWSER") != "1":
                webbrowser.open(URL)
            return
        logging.warning("instance mutex held but no window and no server - starting anyway")

    if not _port_free_probe():
        # порт занят, но /health не наш → чужая программа, честно говорим и выходим
        logging.error("Port %s is occupied by a foreign program - not starting", PORT)
        warn = (f"DentPilot nu a putut porni: portul {PORT} este ocupat de alt program.\n"
                f"Inchideti programul care ocupa portul sau setati DENTART_PORT in dental.env.")
        if os.environ.get("DENTART_BROWSER_MODE") == "1":
            print(warn)
        else:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, warn, "DentPilot", 0x10)
            except Exception:  # noqa: BLE001 — не-Windows/без user32
                pass
        return

    if os.environ.get("DENTART_BROWSER_MODE") == "1":
        _prepare()
        _browser_mode()
        return
    try:
        import webview  # pywebview: собственное окно приложения
    except Exception:  # noqa: BLE001 — нет WebView2? откат на браузер
        logging.warning("pywebview indisponibil - browser mode")
        _prepare()
        _browser_mode()
        return

    # pywebview по умолчанию ставит ALLOW_DOWNLOADS=False и ОТМЕНЯЕТ любое
    # скачивание молча: ни диалога сохранения, ни ошибки, ни следа в окне.
    # Из-за этого «Salvează pe disc» в фише и «📥 Export CSV» в журнале были
    # мёртвыми кнопками — в браузерном режиме работали, в окне программы нет.
    webview.settings["ALLOW_DOWNLOADS"] = True
    # Закрытие ЭТОГО окна гасит всю программу (os._exit ниже) — вместе с
    # доступом с телефона и с ботом у тех, у кого он настроен. Привычное
    # «закрыть все окна в конце смены» делало это молча, поэтому окно
    # переспрашивает. Текст НЕЙТРАЛЬНЫЙ намеренно: Telegram заморожен 08-08
    # (фидбек клиник) и в текстах продукта не упоминается. Кнопки диалога
    # рисует сама Windows на языке системы, наш только текст.
    # ⛔ Окно может не открыться ВООВСЕ: WebView2 Runtime есть не на каждой
    # Windows 10 (обновления выключены, LTSC, свежая машина без Edge). Раньше
    # исключение отсюда улетало в никуда: сборка --noconsole, значит ни окна,
    # ни консоли, ни сообщения — клиника кликала по ярлыку, и НЕ ПРОИСХОДИЛО
    # НИЧЕГО. Неотличимо от «программа сломана», и позвонить с этим нельзя.
    # ⭐ Сервер к этому моменту поднят (или поднимается под заставкой — тогда
    # его дожидается `boot.run()`), то есть программа работает целиком — не
    # хватает только окна. Поэтому отказ окна переводит в браузер, а не гасит: клиника работает сегодня, а WebView2 ставится
    # потом. Модальное окно Windows тут и присутствие обозначает, и даёт
    # единственный способ остановить программу — своей кнопкой (иначе процесс
    # без окна нечем закрыть, кроме диспетчера задач).
    # Цвет фона заставки — цвет темы клиники: экран входа после неё окрашен им
    # же (layout.standalone), и на синей клинике иначе мелькнула бы бирюза.
    # ⚠️ Тема не прочиталась — не повод не открыть окно: остаётся бирюза.
    from app import brand, splash
    try:
        from app.core import theme
        primary = theme.current()["primary"]
    except Exception as e:  # noqa: BLE001
        logging.warning("тема для заставки не прочиталась: %r", e)
        primary = brand.hexc(brand.TEAL)
    mode = _install_mode()
    policy = _session_policy(mode)
    logging.warning("fereastra: profil %s, mod %s, sesiune %s", PROFILE_DIR, mode, policy)
    # ⛔ Профиль создаётся ЗДЕСЬ: WebView2 не создаёт родителей, и без папки окно
    # не открылось бы вовсе — программа ушла бы в браузер при здоровой машине.
    storage: str | None = str(PROFILE_DIR)
    try:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logging.error("profilul ferestrei nu se poate crea (%r) - profil temporar", e)
        storage = None
    boot = _Boot(policy)
    try:
        window = webview.create_window(
            TITLE, html=splash.page(APP_VERSION, primary),
            width=1280, height=860, min_size=(960, 640),
            background_color=brand.tint(primary, .06),
            confirm_close=True,
            localization={
                "global.quitConfirmation":
                    "Închideți DentPilot? Programul se oprește complet până la "
                    "următoarea pornire.",
            },
        )
        if policy == "clear":
            # общий ПК: закрыл окно — вышел из учётки, даже если следующий
            # запуск не наш (куки снимаются и на старте, см. in_window)
            window.events.closing += boot.forget_session
        boot.start()                    # параллельно окну, а не после него
        # ⭐ private_mode=False + storage_path: один профиль на все запуски —
        # ни мусора в TEMP, ни PIN при каждом старте (profile_dir выше)
        webview.start(boot.in_window, window, private_mode=storage is None,
                      storage_path=storage)
    except Exception as e:  # noqa: BLE001 — что угодно вместо окна = браузер
        logging.error("Окно не открылось (%r) — переходим в браузер", e)
        # окно могло упасть раньше, чем запуск успел начаться под заставкой:
        # тогда он делается здесь, без неё; не поднялся сервер — сказано вслух
        if not boot.run():
            os._exit(0)
        try:
            webbrowser.open(URL)
        except Exception:  # noqa: BLE001
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "DentPilot funcționează, dar fereastra programului nu a putut "
                "fi deschisă pe acest calculator.\n\n"
                f"Registrul s-a deschis în browser: {URL}\n"
                "Dacă nu s-a deschis, copiați adresa în Chrome sau Edge.\n\n"
                "NU închideți această fereastră cât timp lucrați — programul "
                "se oprește odată cu ea.\n\n"
                "Pentru fereastra proprie instalați «Microsoft Edge WebView2 "
                "Runtime» (gratuit, de la Microsoft) și porniți din nou.",
                "DentPilot", 0x40)
        except Exception:  # noqa: BLE001 — не-Windows/без user32
            pass
    os._exit(0)  # окно закрыто = программа остановлена


if __name__ == "__main__":
    main()
