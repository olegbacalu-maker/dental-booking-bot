"""DentArt Desktop — лаунчер .exe-издания (без Docker и VPS).

Рядом с exe живут: clinic.json (настройки клиники, редактируются в /admin/settings),
dental.env (TELEGRAM_TOKEN и ADMIN_KEY), data/dental.db (SQLite).
Закрытие окна консоли останавливает программу."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import threading
import time
import webbrowser


def exe_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):  # PyInstaller
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def bundle_dir() -> pathlib.Path:
    return pathlib.Path(getattr(sys, "_MEIPASS",
                                pathlib.Path(__file__).resolve().parent))


BASE = exe_dir()

# первый запуск: конфиг клиники и файл секретов рядом с exe
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

PORT = int(os.environ.get("DENTART_PORT", "8088"))


def _open_browser() -> None:
    time.sleep(2.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}/admin")


def main() -> None:
    print("=" * 62)
    print("  DentArt Desktop - registrul clinicii")
    print(f"  Jurnal:  http://127.0.0.1:{PORT}/admin")
    print(f"  Setari:  clinic.json + dental.env (langa program)")
    print("  NU inchideti aceasta fereastra cat timp lucrati.")
    print("=" * 62)
    if os.environ.get("DENTART_NO_BROWSER") != "1":
        threading.Thread(target=_open_browser, daemon=True).start()
    import uvicorn

    from app.main import app  # noqa: E402 — env уже настроен

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
