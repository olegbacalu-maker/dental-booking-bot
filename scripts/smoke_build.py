"""Дымовой тест СОБРАННОГО exe сразу после сборки: программа реально открывается.

    .venv-desktop\\Scripts\\python.exe scripts\\smoke_build.py
    .venv-desktop\\Scripts\\python.exe scripts\\smoke_build.py --exe dist\\DentPilot.exe

⛔ **Зачем отдельный шаг, если сборка и так печатает `OK`.** Печатала она ровно
одно: файл существует и весит столько-то. 21.09 этого оказалось мало трижды за
день — правка лаунчера, которая в исходниках верна, а в бинарнике не исполняется,
видна ТОЛЬКО запуском: между правилом и поведением стоят PyInstaller, планировщик
и файловая система. `Build-Installer.ps1` этот шаг имел с самого начала, а
`Build-Desktop.ps1` — нет, и именно им собирают, когда проверяют поведение.
⚠️ Проверять `/health` недостаточно: он отвечает БЕЗ единого файла на диске,
поэтому потерянный `--add-data` (static, clinic.json) им не ловится. Страницы
открывает `tests/smoke_exe.py`, а этот файл даёт ему изолированную программу.

Лаборатория — временная папка, удаляется в конце:

    <lab>\\DentPilot.exe   копия собранного
    <lab>\\dental.env      grandfather-состояние (см. ниже)
    $DENTART_DATA_DIR = <lab>

⛔ **Корень данных объявляется ЯВНО и до старта.** С P1 лаунчер больше не
считает папку данных от места exe: не найдя переменной, он уходит в
`%ProgramData%\\DentPilot` — то есть стенд молча проверял бы не свою копию и
писал бы в НАСТОЯЩУЮ картотеку машины. Не падение, а подмена предмета проверки.
Двусторонний сторож `test_launcher.suite_port` держит это правило для всех
стендов и требует, чтобы новый был назван в его списке.

⚠️ **`dental.env` с нерасшифровываемым токеном — не причуда, а grandfather.**
Самозапись (визитка `/` и `/chat`) заморожена 08-08 и живёт за
`tg_configured()`. Без токена дымовой тест проверял бы отсутствующий канал, и
потерянный из сборки `index.html` остался бы незамеченным. Переменная
`DENTART_TOKEN_UNREADABLE` здесь НЕ работает: лаунчер зовёт
`dpapi.unlock_env_token`, и тот СНИМАЕТ флаг, когда токен прочитан (пустой токен
= прочитан успешно). Поэтому даём честное состояние: токен есть, расшифровать
нельзя — флаг выставит сам dpapi, а адаптер Telegram не стартует, значит сети во
время сборки не будет.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

# Консоль Windows у Олега и раннера CI живёт в cp1251/cp1252, а отчёт румынский
# и русский. Без этого печать падает UnicodeEncodeError ПОСРЕДИ шага, и сборка
# краснеет на выводе, а не на предмете проверки. Та же мера, что в run_tests.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEY = "smoke1234"


def free_port() -> int:
    """Порт у ОС, а не из головы.

    ⛔ 8088 — порт установленной программы с настоящей картотекой; второй bind
    на занятый порт Windows разрешает, и запросы уходят СТАРОМУ процессу.
    Эфемерный диапазон туда не попадает, но проверка стоит одной строки.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    if port == 8088:
        return free_port()
    return port


def src_version() -> str:
    """APP_VERSION из исходников — текстом, без импорта приложения.

    Импорт `app.engine` притащил бы fastapi и всё дерево зависимостей в шаг,
    который обязан работать и тогда, когда приложение сломано.
    """
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"',
                  (ROOT / "bot" / "app" / "engine.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def start(lab: pathlib.Path, port: int):
    env = dict(os.environ)
    env.update({"DENTART_BROWSER_MODE": "1", "DENTART_NO_BROWSER": "1",
                "DENTART_PORT": str(port), "ADMIN_KEY": KEY,
                "DENTART_DATA_DIR": str(lab)})
    proc = subprocess.Popen([str(lab / "DentPilot.exe")], cwd=str(lab), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            return proc, base, None
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as r:
                return proc, base, json.loads(r.read())
        except Exception:  # noqa: BLE001 — сервер ещё не поднялся
            time.sleep(1)
    return proc, base, None


def stop(proc) -> None:
    """Погасить ДЕРЕВО процессов, а не один pid.

    ⛔ onefile-сборка PyInstaller — это загрузчик, который распаковывает себя и
    запускает ДОЧЕРНИЙ процесс с тем же именем. Убив загрузчика, получаешь
    живого ребёнка: он держит порт и файл exe, лаборатория не удаляется, и в
    темпе остаётся работающая программа. Так и вышло 21.09 у соседнего стенда.
    """
    if proc is None or proc.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def cleanup(lab: pathlib.Path) -> None:
    """⚠️ Windows отпускает файлы убитого процесса С ЗАДЕРЖКОЙ.

    Первый `rmtree` сразу после `taskkill` падает, когда папку уже никто не
    держит. Поэтому повтор — и ВСЛУХ, если не помогло: молчание здесь означает
    мусор в темпе и занятый порт, о которых узнает кто-то другой.
    """
    for _ in range(6):
        shutil.rmtree(lab, ignore_errors=True)
        if not lab.exists():
            return
        time.sleep(0.5)
    print(f"⚠️  лаборатория НЕ удалена: {lab}")
    print("    что-то держит файлы — проверьте процессы DentPilot.exe")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(ROOT / "dist" / "DentPilot.exe"))
    args = ap.parse_args()

    exe = pathlib.Path(args.exe)
    if not exe.exists():
        # ⚠️ ВСЛУХ и отдельным кодом возврата. Молчаливый пропуск — это ложное
        # зелёное: сборка приняла бы «нечего проверять» за «проверено».
        print(f"ПРОПУЩЕНО: {exe} не собран — проверять нечего.")
        return 2

    lab = pathlib.Path(tempfile.mkdtemp(prefix="dp_smoke_"))
    proc = None
    bad = []
    try:
        shutil.copy(exe, lab / "DentPilot.exe")
        (lab / "dental.env").write_text(
            "# smoke: токен есть, но не расшифровывается -> grandfather\n"
            "TELEGRAM_TOKEN=dpapi:smoke-nu-rasshifruesh\n"
            f"ADMIN_KEY={KEY}\n", encoding="utf-8")

        proc, base, health = start(lab, free_port())
        if not health:
            print("КРАСНО: собранный exe не отвечает на /health — он не "
                  "запускается (проверьте hidden-imports).")
            return 1
        got, want = str(health.get("version", "")), src_version()
        print(f"   exe отвечает и представляется как {got}")
        if want and got != want:
            bad.append(f"exe сообщает {got}, а в engine.py {want} — "
                       "в dist\\ остался СТАРЫЙ бинарник")

        out = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "smoke_exe.py"), base, KEY],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((out.stdout or "").rstrip())
        if (out.stderr or "").strip():
            print((out.stderr or "").rstrip())
        if out.returncode != 0:
            bad.append("страницы собранной программы не открываются — см. выше "
                       "(потерян --add-data? сбит путь к static?)")
    finally:
        stop(proc)
        cleanup(lab)

    if bad:
        print("КРАСНО:")
        for b in bad:
            print(f"  · {b}")
        return 1
    print("ЗЕЛЕНО: собранная программа запускается и открывает страницы.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
