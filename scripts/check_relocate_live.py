"""Живая проверка ветки `unique` (P2, шаги 1–3 + лаунчер).

    python scripts/check_relocate_live.py
    python scripts/check_relocate_live.py --exe dist\\DentPilot.exe

Отвечает на вопрос, который зелёный прогон НЕ проверяет и проверить не может:
исполняет ли СОБРАННЫЙ лаунчер ветку `unique`. Харнесс поднимает `app.main`
напрямую и `desktop.py` не исполняет ни строкой — прайор карты, — а правило
`relocate.root_for` проверено как чистая функция. Между правилом и поведением
стоят PyInstaller, планировщик и файловая система, и ровно в этом промежутке
21.09 нашлись три дефекта подряд.

⛔ **Не «exe запустился — зелено».** Стенд отвечает «ожидался старый корень →
открылся старый корень», и зелёным считается выполнение ВСЕХ трёх утверждений:

  1. программа работает из СТАРОГО корня — журнал открылся, и на странице видно
     имя клиники из `Old\\clinic.json`, а не из вшитого профиля;
  2. НАЗНАЧЕНИЕ осталось пустым: ни `data\\`, ни `clinic.json`, ни `dental.env`;
  3. в `Old\\data\\dentpilot.log` лежит строка вердикта с исходом `unique`.

Раскладка лаборатории (всё во временной папке, удаляется в конце):

    <lab>\\Old\\      DentPilot.exe + clinic.json + dental.env  ← «старая установка»
    <lab>\\Anchor\\   пусто                                      ← назначение
    $DENTART_DATA_DIR = <lab>\\Anchor

⛔ **Настоящая `%ProgramData%\\DentPilot` не участвует ни одной стороной.**
Это инвариант стендов: всякий, кто запускает собранный exe, обязан получить
изолированный `DENTART_DATA_DIR` ДО старта, иначе он не падает, а молча
проверяет не тот экземпляр и пишет в живую картотеку машины. Держит
`test_launcher` — двусторонним списком, поэтому и этот файл в нём назван.

⚠️ Почему `unique` нельзя проверить на машине разработчика как она есть: там
назначение ЗАНЯТО (в `ProgramData` лежит база), и живой ответ будет `split`.
Чтобы получить `unique`, пришлось бы опустошить `ProgramData` — то есть
переставить рабочую среду человека. Лаборатория даёт ветку, не трогая ничего.
"""
import argparse
import http.cookiejar
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEY = "lab-relocate-key"
CLINIC_MARK = "LABORATOR RADACINA VECHE"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_lab(lab: pathlib.Path, exe: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Старый корень с профилем и пустое назначение.

    ⭐ Базу НЕ кладём намеренно: `clinic.json` — такой же маркер данных, как и
    она, а отсутствие базы делает проверку строже. Если ветка `unique`
    сработала, программа заведёт журнал В СТАРОМ корне; если не сработала —
    заведёт его в назначении, и второе утверждение стенда покраснеет. Разница
    видна на файловой системе, а не в интерпретации.
    """
    old = lab / "Old"
    anchor = lab / "Anchor"
    old.mkdir(parents=True)
    anchor.mkdir(parents=True)

    profile = json.loads((ROOT / "bot" / "app" / "clinic_new.json")
                         .read_text(encoding="utf-8"))
    profile["name"] = CLINIC_MARK
    (old / "clinic.json").write_text(json.dumps(profile, ensure_ascii=False,
                                                indent=2), encoding="utf-8")
    # ⚠️ Файл пишем сами, чтобы лаунчер не создавал его и не засевал канал:
    # засев — предмет другого стенда, и лишняя ветка здесь только мешала бы.
    (old / "dental.env").write_text("TELEGRAM_TOKEN=\nADMIN_KEY=\n",
                                    encoding="utf-8")
    shutil.copy(exe, old / "DentPilot.exe")
    return old, anchor


def run_lab(old: pathlib.Path, anchor: pathlib.Path, port: int, seconds: int = 90):
    env = dict(os.environ)
    # ⛔ Назначение объявляем ЯВНО. Без этого лаунчер ушёл бы в
    # %ProgramData%\DentPilot — то есть проверял бы не лабораторию, а живую
    # картотеку машины, и не упал бы при этом.
    env.update({"DENTART_BROWSER_MODE": "1", "DENTART_NO_BROWSER": "1",
                "DENTART_PORT": str(port), "ADMIN_KEY": KEY,
                "DENTART_DATA_DIR": str(anchor)})
    proc = subprocess.Popen([str(old / "DentPilot.exe")], cwd=str(old), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return proc, base, False
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as r:
                if json.loads(r.read()).get("app") == "dentpilot":
                    return proc, base, True
        except Exception:  # noqa: BLE001 — сервер ещё не поднялся
            time.sleep(1)
    return proc, base, False


def admin_page(base: str) -> str:
    """Журнал глазами вошедшего.

    ⚠️ Ключ в адресе и самодельная кука не принимаются никогда: такой запрос
    уезжает редиректом на форму входа, и проверка «имя клиники видно» молча
    отвечала бы «нет» на любой сборке.
    """
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode({"key": KEY}).encode()
    try:
        op.open(base + "/admin/login", data=data, timeout=10).read()
        with op.open(base + "/admin", timeout=10) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return f"<!-- запрос не удался: {e} -->"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(ROOT / "dist" / "DentPilot.exe"))
    ap.add_argument("--keep", action="store_true",
                    help="не удалять лабораторию (разбор после красноты)")
    args = ap.parse_args()

    exe = pathlib.Path(args.exe)
    if not exe.exists():
        # ⚠️ ВСЛУХ и отдельным кодом возврата. Молчаливый пропуск — это ложное
        # зелёное: обёртка приняла бы «нечего проверять» за «проверено».
        print(f"ПРОПУЩЕНО: {exe} не собран — проверять нечего.")
        print("Соберите: powershell -File Build-Desktop.ps1")
        return 2

    lab = pathlib.Path(tempfile.mkdtemp(prefix="dp_relocate_"))
    old, anchor = build_lab(lab, exe)
    port = free_port()
    proc = None
    bad = []
    try:
        proc, base, alive = run_lab(old, anchor, port)
        if not alive:
            print("КРАСНО: программа не поднялась за отведённое время.")
            print(f"  лаборатория: {lab}")
            return 1

        # 1. работаем из СТАРОГО корня — это видно по профилю на странице
        page = admin_page(base)
        if CLINIC_MARK not in page:
            bad.append("на странице нет имени клиники из старого корня: "
                       "программа открыла ЧУЖОЙ профиль")

        # 2. назначение осталось пустым
        left = sorted(p.name for p in anchor.iterdir())
        if left:
            bad.append(f"в назначении появилось: {left} — ветка не сработала, "
                       "журнал заведён не там")

        # 3. вердикт записан
        log = old / "data" / "dentpilot.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        if "раскладка: unique" not in text:
            bad.append(f"в {log} нет строки вердикта с исходом unique")

        if not (old / "data" / "dental.db").exists():
            bad.append("в старом корне не появилась база — журнал открылся не там")
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if args.keep:
            print(f"лаборатория оставлена: {lab}")
        else:
            shutil.rmtree(lab, ignore_errors=True)

    if bad:
        print("КРАСНО:")
        for b in bad:
            print(f"  · {b}")
        return 1
    print("ЗЕЛЕНО: ветка unique исполнена собранным лаунчером.")
    print("  · журнал открыт в СТАРОМ корне (имя клиники оттуда)")
    print("  · назначение осталось пустым")
    print("  · вердикт unique записан в лог")
    return 0


if __name__ == "__main__":
    sys.exit(main())
