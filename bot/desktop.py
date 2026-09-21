"""DentPilot Desktop — лаунчер .exe-издания (без Docker и VPS).

Данные КЛИНИКИ живут в отдельной папке (`data_root()` ниже), а не рядом с exe:
clinic.json (профиль, правится в Setări), dental.env (TELEGRAM_TOKEN и
ADMIN_KEY), data/dental.db (SQLite), data/dentpilot.log (лог).
⛔ Разделение намеренное: программа уезжает в `Program Files`, доступный только
на чтение. Рядом с exe остаётся лишь то, что кладёт СБОРКА (`demo.flag`,
`portable.flag`). Обычный режим — собственное окно приложения
(WebView2); закрытие окна останавливает программу.
DENTART_BROWSER_MODE=1 — старый режим: консоль + системный браузер.
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


def main() -> None:
    import atexit

    from app.engine import APP_VERSION
    logging.warning("DentPilot start v%s port=%s mode=%s pid=%s", APP_VERSION, PORT,
                    "browser" if os.environ.get("DENTART_BROWSER_MODE") == "1" else "window",
                    os.getpid())
    atexit.register(lambda: logging.warning("DentPilot clean exit pid=%s", os.getpid()))
    sys.excepthook = lambda *a: logging.error("UNCAUGHT", exc_info=a)

    if _already_running():
        # второй запуск: свой сервер не поднимаем, просто ещё одно окно к первому
        logging.warning("Already running on port %s - opening extra window only", PORT)
        if os.environ.get("DENTART_BROWSER_MODE") == "1":
            print("DentPilot este deja pornit - deschid jurnalul in browser.")
            if os.environ.get("DENTART_NO_BROWSER") != "1":
                webbrowser.open(URL)
            return
        try:
            import webview
            webview.settings["ALLOW_DOWNLOADS"] = True   # см. комментарий ниже
            # БЕЗ confirm_close: закрытие доп-окна не гасит сервер первого
            # экземпляра, переспрашивать здесь — ложная тревога
            webview.create_window("DentPilot — registrul clinicii", URL,
                                  width=1280, height=860, min_size=(960, 640))
            webview.start()
        except Exception:  # noqa: BLE001
            if os.environ.get("DENTART_NO_BROWSER") != "1":
                webbrowser.open(URL)
        return

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

    # ⚠️ ПЕРЕД автобэкапом и перед стартом приложения: базу нельзя переводить,
    # пока её кто-то держит открытой. Здесь этого не делает ещё никто.
    try:
        from app.core import dbkey
        if (done := dbkey.apply_pending(data_dir)):
            logging.warning("DB crypt: %s", done)
    except Exception as e:  # noqa: BLE001 — переезд не должен блокировать старт
        logging.error("DB crypt FAILED: %r", e)
    _auto_backup()
    if os.environ.get("DENTART_BROWSER_MODE") == "1":
        _browser_mode()
        return
    try:
        import webview  # pywebview: собственное окно приложения
    except Exception:  # noqa: BLE001 — нет WebView2? откат на браузер
        logging.warning("pywebview indisponibil - browser mode")
        _browser_mode()
        return

    threading.Thread(target=_run_server, daemon=True).start()
    if not _wait_ready() or not _already_running():
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
                    "Trimiteti fisierul la dentpilotpro@gmail.com — va ajutam.")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, warn, "DentPilot", 0x10)
        except Exception:  # noqa: BLE001 — не-Windows/без user32
            pass
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
    # ⭐ Сервер к этому моменту уже поднят и отвечает, то есть программа
    # работает целиком — не хватает только окна. Поэтому отказ окна переводит
    # в браузер, а не гасит: клиника работает сегодня, а WebView2 ставится
    # потом. Модальное окно Windows тут и присутствие обозначает, и даёт
    # единственный способ остановить программу — своей кнопкой (иначе процесс
    # без окна нечем закрыть, кроме диспетчера задач).
    try:
        webview.create_window(
            "DentPilot — registrul clinicii", URL,
            width=1280, height=860, min_size=(960, 640),
            confirm_close=True,
            localization={
                "global.quitConfirmation":
                    "Închideți DentPilot? Programul se oprește complet până la "
                    "următoarea pornire.",
            },
        )
        webview.start()
    except Exception as e:  # noqa: BLE001 — что угодно вместо окна = браузер
        logging.error("Окно не открылось (%r) — переходим в браузер", e)
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
