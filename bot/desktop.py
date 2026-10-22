"""DentPilot — лаунчер движка оболочки Tauri.

С 2.0.0 (18.10.2026) программа — оболочка `DentPilot.exe` (окно, меню, значок
у часов, сторож обновления) и этот движок в `engine\\DentPilot-Engine.exe`:
сервер журнала без окна. Оболочка запускает движок с `DENTART_SHELL=tauri` и
говорит с ним строками `DP1` по stdin/stdout (`docs/dentpilot-2/tauri-contract.md`
§ 2, `app/sidecar.py`). Без оболочки движок не запускается: окна у него нет
(прежнее окно pywebview снято 22.10.2026), и сервер без окна нечем закрыть.

Данные КЛИНИКИ живут в отдельной папке (`data_root()` ниже), а не рядом с exe:
clinic.json (профиль, правится в Setări), dental.env (TELEGRAM_TOKEN и
ADMIN_KEY), data/dental.db (SQLite), data/dentpilot.log (лог).
⛔ Разделение намеренное: программа уезжает в `Program Files`, доступный только
на чтение. Рядом с exe остаётся лишь то, что кладёт СБОРКА или установщик
(`demo.flag`, `install.json`).
(env-переменные исторически с префиксом DENTART_ — не трогаем ради
совместимости с dental.env уже установленных клиник.)"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import sys
import threading
import time
import urllib.request

from app import logrotate, sidecar  # предзагрузочный слой: без проекта и без побочных действий


def exe_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):  # PyInstaller
        exe = pathlib.Path(sys.executable).resolve()
        # ⭐ Движок Tauri (`engine\DentPilot-Engine.exe`, контракт § 1): корень
        # программы — папка оболочки DentPilot.exe, родитель `engine\`; там
        # лежат install.json и demo.flag. ⚠️ Узнаём по ИМЕНИ
        # собранного файла, а не по DENTART_SHELL: привилегированный запуск
        # (UAC) окружения оболочки не получает, а корень ему нужен тот же.
        if exe.name.lower() == sidecar.ENGINE_EXE.lower():
            return exe.parent.parent
        return exe.parent
    return pathlib.Path(__file__).resolve().parent


def bundle_dir() -> pathlib.Path:
    return pathlib.Path(getattr(sys, "_MEIPASS",
                                pathlib.Path(__file__).resolve().parent))


def _fatal_dir(path: pathlib.Path, err: Exception) -> None:
    """Папка клиники недоступна — сказать это ВСЛУХ и выйти.

    ⛔ Единственный способ сообщить здесь — событие `fatal` оболочке (окно
    рисует она): лога ещё нет, и до `sys.excepthook` дело не дойдёт — этот код
    исполняется на уровне модуля. Без этого отказ прав на `ProgramData`
    выглядит как «ярлык не работает», и чинить клиника пойдёт не то.
    ⚠️ Текст клинике по-румынски и с ПУТЁМ: без пути поддержка по телефону
    не сможет спросить ничего полезного.
    """
    text = (f"DentPilot nu poate folosi dosarul cu datele clinicii:\n\n{path}\n\n"
            f"{err.__class__.__name__}: {err}\n\n"
            "Verificați drepturile pe acest dosar sau porniți instalarea din nou.")
    SHELL.send("fatal", text=text, log="")      # лога ещё нет: папки нет
    raise SystemExit(sidecar.EXIT_FATAL)


def _box(msg: str) -> None:
    """Сказать клинике вслух. ⛔ У движка окон нет (контракт § 2):
    предупреждение уходит оболочке событием `warn` (окно рисует она), беда —
    событием `fatal` у того, кто её обнаружил. Окно Windows — только у
    собранного движка, запущенного БЕЗ оболочки (двойной клик по
    `DentPilot-Engine.exe`): сказать ему больше некому. Из исходников —
    stderr: модальное окно повесило бы стенд, забывший `DENTART_SHELL`."""
    if SHELL is not None:
        logging.warning("(motor Tauri: warn) %s", msg)
        SHELL.warn(msg)
        return
    if getattr(sys, "frozen", False):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "DentPilot", 0x10)
            return
        except Exception:                  # noqa: BLE001 — не на Windows / нет user32
            pass
    print(msg, file=sys.__stderr__ or sys.stdout)


def data_root() -> pathlib.Path:
    """Папка КЛИНИКИ. Решает ОДИН лаунчер — он один знает раскладку машины.

    ⛔ Порядок именно такой, и каждая ветка тут за своё:
      1. `$DENTART_DATA_DIR` из окружения ПРОЦЕССА — им пользуются установщик
         и стенды. ⚠️ Из `dental.env` этот ключ НЕ берётся
         и взяться не может: сам файл лежит ВНУТРИ искомой папки, и ключ в нём
         замкнул бы круг — второй запуск разрешился бы в другое место. Поэтому
         переменная выставляется ЖЁСТКО и ДО чтения `dental.env` (ниже).
      2. Иначе — `%ProgramData%\\DentPilot`, общая для всех учёток машины.
    ⚠️ Ветки «старая установка рядом с exe» здесь НЕТ и не будет: эта функция
    отвечает на вопрос «куда положено», и выводить ответ из положения exe
    нельзя — программа, переставленная в `Program Files`, завела бы пустую базу
    рядом с настоящей. На вопрос «а где картотека ЛЕЖИТ на самом деле»
    отвечает следующий шаг (`relocate.root_for`, P2), и отвечает не положением
    exe самим по себе, а положением, ПОДТВЕРЖДЁННЫМ маркерами данных.
    ⭐ Разница принципиальная: здесь — раскладка, там — находка.
    Режима флешки (`portable.flag`: «всё в одной папке рядом с exe») нет с
    22.10.2026: никакая сборка его не ставила, а программа-папка оболочки в
    нём не могла обновиться.
    """
    raw = os.environ.get("DENTART_DATA_DIR", "").strip().strip("\"'")
    if raw and pathlib.Path(raw).is_absolute():
        return pathlib.Path(raw)
    return pathlib.Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "DentPilot"


BASE = exe_dir()
SHELL: sidecar.Link | None = None     # труба к оболочке Tauri; ставится ниже

# ⛔ ПЕРВОЕ, что делает лаунчер, и раньше всего остального: привилегированный
# запуск обязан сделать ровно одно дело и выйти. Строкой ниже начинаются
# побочные действия — вычисление корня, mkdir, лог, — а процесс под
# администратором не должен ни создавать папки клиники (они достались бы
# админу, и обычный запуск потерял бы к ним доступ), ни поднимать сервер.
# ⚠️ Список того, что вообще может случиться за UAC, — `app/privileged.py`.
from app import privileged  # noqa: E402 — предзагрузочный слой, без проекта

# ⚠️ Раскладку передаём СВОЕЙ функцией: у неё две ветки ($DENTART_DATA_DIR,
# %ProgramData%), и второй вычислитель разошёлся бы с этим молча.
# ⛔ Окружение сюда не доезжает: повышенный процесс запускает Windows, а не
# мы, и `$DENTART_DATA_DIR`, выставленный лаунчером, в нём не виден.
# Корень программы — тоже наш (BASE): у движка Tauri это папка оболочки над
# `engine\`, туда операция кладёт копию мастера (Т10).
if (_code := privileged.handle_argv(sys.argv[1:], data_root, BASE)) is not None:
    raise SystemExit(_code)


def _internal_text() -> str:
    return ("DentPilot nu a putut porni din cauza unei erori interne.\n"
            "Detalii: data\\dentpilot.log (ultimele linii).\n"
            "Trimiteti fisierul la contact@dentpilot.md — va ajutam.")


def _port_text() -> str:
    return (f"DentPilot nu a putut porni: portul {PORT} este ocupat de alt program.\n"
            f"Inchideti programul care ocupa portul sau setati DENTART_PORT in dental.env.")


def _engine_crash(kind, value, tb) -> None:
    """Исключение, долетевшее до верха модуля у движка: трейсбек — в stderr
    (файл после подмены ниже), оболочке — `fatal`, выход с кодом 2, а не 1 —
    кодов у контракта три: 0, 2, 3."""
    import traceback
    try:
        traceback.print_exception(kind, value, tb)
        sys.stderr.flush()
        logging.error("UNCAUGHT", exc_info=(kind, value, tb))
    except Exception:  # noqa: BLE001 — сказать оболочке важнее
        pass
    SHELL.send("fatal", text=_internal_text(), log=SHELL.log)
    os._exit(sidecar.EXIT_FATAL)


# ⭐ Движок Tauri (Т5). Режим решает окружение ПРОЦЕССА и здесь — до слияния
# `dental.env`: строка `DENTART_SHELL=tauri` в файле клиники его не включит.
# После привилегированного запуска: у него свой разговор и свой выход.
# ⚠️ Трубы забираются у процесса ЗДЕСЬ, до первого `print` и до подмены
# stdout ниже (`sidecar.take`: почему ни одна чужая строка не должна попасть
# в трубу оболочки).
_SHELL_TOKEN = os.environ.get(sidecar.TOKEN_ENV, "")
if sidecar.active():
    SHELL = sidecar.take(BASE)
# ⛔ Без оболочки движок НЕ запускается (22.10.2026, окно pywebview снято):
# окна у него нет, и сервер, поднятый двойным щелчком по
# `engine\DentPilot-Engine.exe`, нечем было бы ни увидеть, ни закрыть. Отказ —
# ДО вычисления корня: такой запуск не должен ни заводить папку клиники, ни
# трогать картотеку.
if SHELL is None:
    _box("DentPilot-Engine.exe este motorul programului și nu pornește singur.\n"
         "Porniți DentPilot din meniul Start sau cu DentPilot.exe.")
    raise SystemExit(sidecar.EXIT_FATAL)
sys.excepthook = _engine_crash
# ⛔ Движок из ИСХОДНИКОВ без явной папки данных ушёл бы в
# %ProgramData%\DentPilot — в настоящую картотеку этой машины (у Олега там
# живая установка). Оболочку в разработке запускает человек, и забыть
# переменную — одно движение; стенды папку называют сами.
if not getattr(sys, "frozen", False) and not os.environ.get("DENTART_DATA_DIR", "").strip():
    SHELL.send("fatal", log="", text=(
        "Motorul DentPilot pornit din surse fără DENTART_DATA_DIR: ar folosi "
        "datele reale ale acestui calculator (%ProgramData%\\DentPilot).\n"
        "Setați DENTART_DATA_DIR spre un dosar de test."))
    raise SystemExit(sidecar.EXIT_FATAL)

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
    """Папка профиля WebView2 окна (куки входа, кэш, localStorage) — ПОСТОЯННАЯ.

    Профиль заводит и держит ОКНО — оболочка (`shell/src/paths.rs`, то же
    правило); движку путь нужен ровно для одного: профиль заставки сторожа
    перезапуска лежит РЯДОМ (`DENTART_WATCH_PROFILE` ниже).
    ⛔ Своя у каждой учётки Windows (`%LOCALAPPDATA%\\DentPilot\\webview`), а не в
    папке клиники: `ProgramData` общая на всех учёток, и кука входа одного
    человека досталась бы другому. И не рядом с exe: `Program Files` только на
    чтение.
    ⚠️ Читается из окружения ПРОЦЕССА (`DENTART_PROFILE_DIR` — стенд), ДО слияния
    `dental.env`: строка в файле клиники не должна уводить профиль в другое место.
    """
    raw = os.environ.get("DENTART_PROFILE_DIR", "").strip().strip("\"'")
    if raw and pathlib.Path(raw).is_absolute():
        return pathlib.Path(raw)
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

# stdout уже отдан оболочке (`sidecar.take` выше), stderr — в файл (видны
# краши), и дескриптором тоже (`stderr_to`): трейсбек нативного кода и
# дочерний процесс без `stderr=` не уходят в трубу, которую никто не читает.
# ⚠️ Стоит ВЫШЕ первого чтения файлов намеренно: dental.env правит сама
# клиника, и падение на его разборе иначе гибло бы молча — лога ещё нет.
_err_log = data_dir / "dentpilot.err.log"
logrotate.roll_if_big(_err_log)         # открывается раз на запуск — и сдвигается тогда же
sidecar.stderr_to(_err_log)

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
# ⭐ С 18.10 (Т5) файл ротируется: `logrotate.handler` — тот же FileHandler с
# `encoding="utf-8"`, плюс сдвиг по размеру, который не теряет записей, когда
# лог держит второй запуск программы (Windows не переименует открытый файл).
logging.basicConfig(
    handlers=[logrotate.handler(data_dir / "dentpilot.log")], level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
SHELL.log = str(data_dir / "dentpilot.log")

# ⚠️ Вердикт пишется ЗДЕСЬ, а не там, где получен: там ещё нет ни лога, ни
# stderr. Уровень WARNING намеренно: всё, кроме
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

# Профиль заставки сторожа перезапуска — РЯДОМ с профилем окна, у той же учётки
# Windows (12.10, 1.41.1). До того он жил в папке данных (`updates\watch-profile`),
# и установщик, выдающий права `icacls /T` на всю папку данных, обходил дерево в
# ту же секунду, когда WebView2 заставки в нём писал: канарейка 1.41.0 — окно
# «Nu am putut acorda drepturi». Путь знает лаунчер (profile_dir выше), приложение
# получает его готовым — второго вычисления того же места нет. Ставится ПОСЛЕ
# слияния dental.env: строка в файле клиники его не перебьёт.
os.environ["DENTART_WATCH_PROFILE"] = str(PROFILE_DIR.with_name(PROFILE_DIR.name + "-watch"))

# ⛔ Режим движка и токен оболочки (§ 4, `/shell/notices`) — ЖЁСТКО, обеими
# ветками и после слияния `dental.env`, тем же приёмом, что вердикт раздвоения
# выше: строка `DENTART_SHELL_TOKEN=…` в файле клиники открыла бы адрес
# оболочки известным токеном, которого оболочка не давала. Приложение
# спрашивает оболочку только `sidecar.linked()`; окружение здесь — для тех,
# кто читает его по старинке.
os.environ[sidecar.ENV] = sidecar.MODE
if _SHELL_TOKEN:
    os.environ[sidecar.TOKEN_ENV] = _SHELL_TOKEN
else:
    os.environ.pop(sidecar.TOKEN_ENV, None)


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


# DENTART_PORT правит сама клиника — сообщение «portul este ocupat» это прямо
# советует, — поэтому мусор в нём ожидаем. Раньше голый int() падал ЗДЕСЬ, на
# верхнем уровне модуля, до excepthook и до любого окна: двойной клик по
# ярлыку «не делал ничего», а клинику только что попросили править этот ключ.
_port_raw = os.environ.get("DENTART_PORT", "").strip()
PORT = envfile.parse_port(_port_raw) or 8088
if _port_raw and envfile.parse_port(_port_raw) is None:
    logging.error("DENTART_PORT invalid: %r - folosim 8088", _port_raw)
    _port_warn = (f'DENTART_PORT invalid: "{_port_raw}" — se folosește portul '
                  f"8088.\nCorectați valoarea în dental.env "
                  f"(un număr între 1 și 65535).")
    SHELL.warn(_port_warn)          # у движка окон нет: покажет оболочка
# Доступ с телефона (Setări → Acces de pe telefon): 0.0.0.0 ТОЛЬКО по явному
# DENTART_LAN=1 из dental.env. По умолчанию — 127.0.0.1, сетевого доступа НЕТ.
# Окно оболочки и проверка второго экземпляра ходят через loopback в обоих режимах.
HOST = "0.0.0.0" if os.environ.get("DENTART_LAN", "").strip() == "1" else "127.0.0.1"
URL = f"http://127.0.0.1:{PORT}/admin"


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
    """Переживает ли ВХОД перезапуск окна (поле `session` события `ready`;
    куки снимает окно — оболочка). `keep` — standalone, clinic_server,
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
    и ДО того, как тот поднял сервер. Не Windows — считаем первым,
    порт проверит `/health`, как раньше."""
    global _MUTEX
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        _MUTEX = k32.CreateMutexW(None, False, f"Local\\DentPilot-{PORT}")
        return k32.GetLastError() != 183          # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 — не Windows / нет kernel32
        return True


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


def _make_server(**extra):
    import uvicorn

    from app.main import app  # noqa: E402 — env уже настроен

    config = uvicorn.Config(app, host=HOST, port=PORT,
                            log_level="warning", log_config=None, **extra)
    return uvicorn.Server(config)


def _wait_ready(timeout: float = 25.0, alive=None) -> bool:
    """`alive` — жив ли ещё поток сервера: упавший сервер не ждём до срока."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if alive is not None and not alive():
            return False
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/health", timeout=1):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


def _prepare(stage=lambda *a: None) -> None:
    """Что лаунчер делает с базой до старта приложения: восстановление из
    копии, перевод (шифрование) и копия. ⚠️ ПЕРЕД автобэкапом и перед стартом
    приложения: базу нельзя ни подменять, ни переводить, пока её кто-то держит
    открытой. Здесь этого не делает ещё никто.
    ⭐ Порядок: сперва восстановление (`app.core.restore.apply_pending` —
    заказ со страницы Setări › Copie de rezervă), потом ключ: заказанное
    шифрование ляжет уже на восстановленную базу; саму восстановленную базу
    под действующий ключ переводит restore. Автокопия идёт последней и
    снимает копию уже с того, с чем программа стартует."""
    try:
        from app.core import restore
        if (done := restore.apply_pending(data_dir, ROOT)):
            logging.warning("DB restore: %s", done)
    except Exception as e:  # noqa: BLE001 — восстановление не должно блокировать старт
        logging.error("DB restore FAILED: %r", e)
    try:
        from app.core import dbkey
        if (done := dbkey.apply_pending(data_dir)):
            logging.warning("DB crypt: %s", done)
    except Exception as e:  # noqa: BLE001 — переезд не должен блокировать старт
        logging.error("DB crypt FAILED: %r", e)
    stage("Se face copia de rezervă…", 38)
    _auto_backup()


def _start_failed() -> str:
    """Сервер не поднялся: что сказать клинике. Различаем ДВЕ разные беды:
    порт перехватили после нашей пробы ИЛИ сервер упал сам (раньше во втором
    случае врали про порт)."""
    port_taken = not _port_free_probe() and not _already_running()
    logging.error("Server did not start on port %s (port_taken=%s)", PORT, port_taken)
    return _port_text() if port_taken else _internal_text()


# Остановка движка (контракт § 2: выход не дольше 10 с после слова оболочки,
# потом она снимает задание). Запросам на лету — STOP_GRACE_S, всей остановке
# — STOP_BUDGET_S; остаток — на закрытие базы и выход.
STOP_GRACE_S = 4
STOP_BUDGET_S = 8.0


def _engine_main(link: sidecar.Link, version: str) -> None:
    """Движок оболочки Tauri: запуск под заставкой оболочки, разговор строками
    `DP1` и честная остановка по её слову. Код выхода — контракт: 0
    остановлен, 2 `fatal`, 3 `busy`."""
    try:
        code = _engine(link, version)
    except Exception:  # noqa: BLE001 — что угодно = `fatal`, а не код 1 без слова
        logging.error("motor: UNCAUGHT", exc_info=True)
        link.send("fatal", text=_internal_text(), log=link.log)
        code = sidecar.EXIT_FATAL
    logging.warning("DentPilot exit code=%s pid=%s", code, os.getpid())
    logging.shutdown()
    # ⭐ Выход ограничен по времени: к этой строке сервер остановлен, фоновые
    # циклы сняты и база закрыта (гашение в app.main). Поток, которого лаунчер
    # не знает (`to_thread` внешней копии, не-фоновый поток библиотеки), здесь
    # уже не держит процесс сверх срока контракта.
    os._exit(code)


def _engine(link: sidecar.Link, version: str) -> int:
    from app import brand
    try:
        from app.core import theme
        primary = theme.current()["primary"]
    except Exception as e:  # noqa: BLE001 — тема украшает, запуск важнее
        logging.warning("тема для заставки не прочиталась: %r", e)
        primary = brand.hexc(brand.TEAL)
    link.send("hello", version=version, color=primary, pid=os.getpid())

    # Слово оболочки слушаем СРАЗУ: окно закрыли под заставкой — сервер не
    # поднимаем вовсе. ⛔ Но подготовку базы (восстановление, перевод ключа,
    # копия) не обрываем: её прерывать нельзя, проверка — после неё.
    stop = threading.Event()
    why = {"v": ""}

    def on_stop(reason: str) -> None:
        why["v"] = reason
        stop.set()
    link.listen(on_stop)

    # Второй экземпляр (вторая учётка Windows, стенд): первой отвечает
    # оболочка, мьютекс — страховка (§ 2 «Второй запуск»). Своего сервера нет —
    # `busy` с адресом первого, оболочка покажет его.
    first = _claim_instance()
    if not first or _already_running():
        if _already_running() or (_wait_ready(10.0) and _already_running()):
            logging.warning("Already running on port %s - busy for the shell", PORT)
            link.send("busy", url=URL)
            return sidecar.EXIT_BUSY
        logging.warning("instance mutex held but no server - starting anyway")
    if not _port_free_probe():
        logging.error("Port %s is occupied by a foreign program - not starting", PORT)
        link.send("fatal", text=_port_text(), log=link.log)
        return sidecar.EXIT_FATAL

    def stage(text: str, pct: int, upto: int = 0) -> None:
        link.send("stage", text=text, pct=pct, upto=upto)

    t0 = time.monotonic()
    stage("Se pornește DentPilot…", 6)        # этапы — на заставку оболочки
    stage("Se pregătește baza de date…", 16)
    _prepare(stage)
    t1 = time.monotonic()
    if stop.is_set():
        logging.warning("остановка до старта сервера (%s)", why["v"])
        return sidecar.EXIT_STOP
    stage("Se pornește registrul…", 55, 92)
    server = _make_server(timeout_graceful_shutdown=STOP_GRACE_S)
    # ⚠️ Не фоновый поток и не основной: остановка — `should_exit` из этого
    # потока, и потом его честно дождаться; сигналов uvicorn вне основного
    # потока не ставит.
    th = threading.Thread(target=server.run, name="uvicorn")
    th.start()
    if not (_wait_ready(alive=th.is_alive) and _already_running()):
        link.send("fatal", text=_start_failed(), log=link.log)
        server.should_exit = True
        th.join(STOP_BUDGET_S)
        return sidecar.EXIT_FATAL
    logging.warning("запуск: журнал готов за %.1f с (база и копия %.1f, сервер %.1f)",
                    time.monotonic() - t0, t1 - t0, time.monotonic() - t1)
    mode = _install_mode()
    link.send("ready", url=URL, port=PORT, session=_session_policy(mode),
              data=str(ROOT), lan=HOST == "0.0.0.0")

    while th.is_alive() and not stop.wait(0.5):
        pass
    if not stop.is_set():
        logging.error("сервер остановился сам, без слова оболочки")
        link.send("fatal", text=_internal_text(), log=link.log)
        return sidecar.EXIT_FATAL
    t2 = time.monotonic()
    logging.warning("остановка по слову оболочки (%s)", why["v"])
    server.should_exit = True
    th.join(STOP_BUDGET_S)
    if th.is_alive():
        logging.error("сервер не остановился за %.0f с — выходим", STOP_BUDGET_S)
    else:
        logging.warning("сервер остановлен за %.1f с", time.monotonic() - t2)
    return sidecar.EXIT_STOP


def main() -> None:
    from app.engine import APP_VERSION
    logging.warning("DentPilot start v%s port=%s mode=tauri pid=%s", APP_VERSION, PORT,
                    os.getpid())
    _engine_main(SHELL, APP_VERSION)    # выходит сам, с кодом контракта


if __name__ == "__main__":
    main()
