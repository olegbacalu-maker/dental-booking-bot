"""DentArt Desktop — лаунчер .exe-издания (без Docker и VPS).

Рядом с exe живут: clinic.json (профиль клиники, правится в Setări),
dental.env (TELEGRAM_TOKEN и ADMIN_KEY), data/dental.db (SQLite),
data/dentart.log (лог). Обычный режим — собственное окно приложения
(WebView2); закрытие окна останавливает программу.
DENTART_BROWSER_MODE=1 — старый режим: консоль + системный браузер."""
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
    sys.stderr = open(data_dir / "dentart.err.log", "a", encoding="utf-8")  # noqa: SIM115

logging.basicConfig(
    filename=str(data_dir / "dentart.log"), level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

PORT = int(os.environ.get("DENTART_PORT", "8088"))
URL = f"http://127.0.0.1:{PORT}/admin"


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
    print("  DentArt Desktop - registrul clinicii")
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
    logging.warning("DentArt start v%s port=%s mode=%s pid=%s", APP_VERSION, PORT,
                    "browser" if os.environ.get("DENTART_BROWSER_MODE") == "1" else "window",
                    os.getpid())
    atexit.register(lambda: logging.warning("DentArt clean exit pid=%s", os.getpid()))
    sys.excepthook = lambda *a: logging.error("UNCAUGHT", exc_info=a)
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
    _wait_ready()
    webview.create_window(
        "DentArt — registrul clinicii", URL,
        width=1280, height=860, min_size=(960, 640),
    )
    webview.start()
    os._exit(0)  # окно закрыто = программа остановлена


if __name__ == "__main__":
    main()
