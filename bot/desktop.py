"""DentPilot Desktop — лаунчер .exe-издания (без Docker и VPS).

Рядом с exe живут: clinic.json (профиль клиники, правится в Setări),
dental.env (TELEGRAM_TOKEN и ADMIN_KEY), data/dental.db (SQLite),
data/dentpilot.log (лог). Обычный режим — собственное окно приложения
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


BASE = exe_dir()

cfg_path = BASE / "clinic.json"
if not cfg_path.exists():
    shutil.copy(bundle_dir() / "app" / "clinic.json", cfg_path)

env_path = BASE / "dental.env"
if not env_path.exists():
    env_path.write_text(
        "# Token botului Telegram (de la @BotFather):\nTELEGRAM_TOKEN=\n"
        "# Parola jurnalului /admin (gol = deschis):\nADMIN_KEY=\n",
        encoding="utf-8",
    )
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

data_dir = BASE / "data"
data_dir.mkdir(exist_ok=True)
os.environ.setdefault("CLINIC_CONFIG", str(cfg_path))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{data_dir / 'dental.db'}")

# noconsole-сборка: sys.stdout/stderr = None → uvicorn падает на isatty().
# Подкладываем безопасные потоки; stderr пишем в файл (видны краши).
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(data_dir / "dentpilot.err.log", "a", encoding="utf-8")  # noqa: SIM115

logging.basicConfig(
    filename=str(data_dir / "dentpilot.log"), level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# путь к env-файлу — для страницы настроек (правка токена из UI)
os.environ["DENTART_ENV_FILE"] = str(env_path)


def _auto_backup() -> None:
    """Копия базы при каждом старте (через SQLite backup API — консистентно
    даже после краха с WAL), храним последние 14 в data/backups."""
    src = data_dir / "dental.db"
    if not src.exists():
        return
    try:
        import sqlite3
        bdir = data_dir / "backups"
        bdir.mkdir(exist_ok=True)
        # PID в имени: два одновременных старта не пишут в один файл бэкапа
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dst_path = bdir / f"dental_{stamp}_{os.getpid()}.db"
        src_c = sqlite3.connect(str(src))
        dst_c = sqlite3.connect(str(dst_path))
        with dst_c:
            src_c.backup(dst_c)
        src_c.close()
        dst_c.close()
        for f in sorted(bdir.glob("dental_*.db"))[:-14]:
            f.unlink(missing_ok=True)
        logging.warning("Auto-backup: %s", dst_path.name)
    except Exception as e:  # noqa: BLE001 — бэкап не должен блокировать старт
        logging.warning("Auto-backup FAILED: %r", e)


PORT = int(os.environ.get("DENTART_PORT", "8088"))
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

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT,
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
        # порт занят чужой программой: bind умер в daemon-потоке —
        # без этой проверки окно молча показало бы ЧУЖОЙ сервер
        logging.error("Server failed to start on port %s (occupied by another app?)", PORT)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f"DentPilot nu a putut porni: portul {PORT} este ocupat de alt program.\n"
                f"Închideți programul care ocupă portul sau setați DENTART_PORT în dental.env.",
                "DentPilot", 0x10)
        except Exception:  # noqa: BLE001 — не-Windows/без user32
            pass
        return
    webview.create_window(
        "DentPilot — registrul clinicii", URL,
        width=1280, height=860, min_size=(960, 640),
    )
    webview.start()
    os._exit(0)  # окно закрыто = программа остановлена


if __name__ == "__main__":
    main()
