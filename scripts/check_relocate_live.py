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
    <lab>\\tmp\\      TEMP программы: распаковка onefile (_MEI*)
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

# ⚠️ Консоль Windows живёт в cp1251, а отчёт печатает «⚠️» и кириллицу — и
# стенд падал UnicodeEncodeError В БЛОКЕ УБОРКИ, унося и жалобу, и удаление
# лаборатории. Тот же приём, что в `run_tests.py`: плохой символ дешевле
# потерять, чем весь отчёт. ⭐ И это ровно тот дефект, который стенд ищет в
# продукте, — кодировка вывода, взятая у машины.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    # ⛔ (09-26) TEMP — внутри лаборатории, но вне Old и Anchor: stop() гасит
    # загрузчик onefile через taskkill /F, и свою распаковку (_MEI*, 52 МБ) он
    # уже не убирает — она оставалась в %TEMP% после каждой сборки.
    tmp = old.parent / "tmp"
    tmp.mkdir(exist_ok=True)
    # ⛔ Назначение объявляем ЯВНО. Без этого лаунчер ушёл бы в
    # %ProgramData%\DentPilot — то есть проверял бы не лабораторию, а живую
    # картотеку машины, и не упал бы при этом.
    env.update({"DENTART_BROWSER_MODE": "1", "DENTART_NO_BROWSER": "1",
                "DENTART_PORT": str(port), "ADMIN_KEY": KEY,
                "DENTART_DATA_DIR": str(anchor), "TEMP": str(tmp), "TMP": str(tmp)})
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


def stop(proc) -> None:
    """Погасить ДЕРЕВО процессов, а не один pid.

    ⛔ `proc.terminate()` здесь недостаточно, и это не теория: onefile-сборка
    PyInstaller — это загрузчик, который распаковывает себя и запускает
    ДОЧЕРНИЙ процесс с тем же именем. Убив загрузчика, получаешь живого
    ребёнка: он держит порт и файл exe, `shutil.rmtree` молча не удаляет
    лабораторию (`ignore_errors`), и в темпе остаётся папка с работающей
    программой внутри. Так и вышло 21.09 — процесс прожил лишний час, и
    заметила его соседняя сессия, а не стенд.
    ⚠️ `taskkill /T` (дерево) и `/F` (без вежливых просьб): у программы нет
    окна, которое можно закрыть, а обработчик выхода здесь не нужен — данные
    лабораторные.
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


def admin_page(base: str) -> tuple[str, str]:
    """Журнал глазами вошедшего. Возвращает `(страница, чем_плохо)`.

    ⛔ Поле формы — `password`, а НЕ `key` (`main.py`, `password: str =
    Form(...)`, живёт с 30.07). С `key` маршрут отвечает 422, и стенд не
    логинился ни разу.
    ⛔ И главное: провал запроса ОБЯЗАН отличаться от честного «на странице
    этого нет». Прежняя версия ловила `urllib.error.URLError`, наследником
    которого является `HTTPError`, и возвращала строку-заглушку — утверждение
    печатало «программа открыла ЧУЖОЙ профиль» там, где на самом деле стенд
    просто не вошёл. Это прайор карты «303 не отличает успех от отказа» в новом
    платье, и он дороже обычной ошибки: стенд краснеет ПРАВДОПОДОБНО, уводя
    чинить не то.
    ⚠️ Ключ в адресе (`/admin?key=…`) и самодельная кука не принимаются
    никогда — только форма с куки-джаром, как у человека.
    """
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode({"password": KEY}).encode()
    try:
        op.open(base + "/admin/login", data=data, timeout=10).read()
    except urllib.error.HTTPError as e:
        return "", f"вход отклонён: HTTP {e.code} на /admin/login (поле формы?)"
    except OSError as e:
        return "", f"вход не состоялся: {e}"
    if not any(c.name == "admin_auth" for c in jar):
        return "", "вход прошёл без куки admin_auth — стенд не в журнале"
    try:
        with op.open(base + "/admin", timeout=10) as r:
            return r.read().decode("utf-8", "replace"), ""
    except OSError as e:
        return "", f"журнал не открылся: {e}"


def read_log(path: pathlib.Path) -> tuple[str, str]:
    """Текст лога и жалоба, если он написан НЕ в utf-8.

    ⛔ Читать один utf-8 и молчать нельзя: до правки 21.09 лаунчер открывал лог
    в ANSI машины, и стенд кириллицы не видел НИКОГДА — красное «вердикта нет»
    при вердикте, лежащем в файле. Но и принимать ANSI молча нельзя: у клиники
    ANSI это cp1250, и русская строка туда не пишется вовсе — `logging`
    выбрасывает запись целиком. Поэтому ANSI здесь не запасной вариант, а
    ОТДЕЛЬНЫЙ дефект, о котором стенд обязан сказать.
    """
    if not path.exists():
        return "", ""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), ""
    except UnicodeDecodeError:
        import locale
        ansi = locale.getpreferredencoding(False)
        return (raw.decode(ansi, "replace"),
                f"лог написан не в utf-8, а в ANSI машины ({ansi}): у клиники "
                "с румынской Windows русские строки лога пропадут целиком")


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
        page, trouble = admin_page(base)
        if trouble:
            # ⛔ Отдельная строка, а не «профиль чужой»: стенд, который не вошёл,
            # ничего не знает о профиле и обязан сказать именно это.
            bad.append(f"проверить профиль не удалось — {trouble}")
        elif CLINIC_MARK not in page:
            bad.append("на странице нет имени клиники из старого корня: "
                       "программа открыла ЧУЖОЙ профиль")

        # 2. назначение осталось пустым
        left = sorted(p.name for p in anchor.iterdir())
        if left:
            bad.append(f"в назначении появилось: {left} — ветка не сработала, "
                       "журнал заведён не там")

        # 3. вердикт записан
        log = old / "data" / "dentpilot.log"
        text, log_trouble = read_log(log)
        if "раскладка: unique" not in text:
            bad.append(f"в {log} нет строки вердикта с исходом unique")
        if log_trouble:
            bad.append(log_trouble)

        if not (old / "data" / "dental.db").exists():
            bad.append("в старом корне не появилась база — журнал открылся не там")
    finally:
        stop(proc)
        if args.keep:
            print(f"лаборатория оставлена: {lab}")
        else:
            # ⚠️ С повтором: Windows отпускает хэндлы убитого процесса не
            # мгновенно, и первая попытка сразу после taskkill проваливается на
            # ровном месте — папка остаётся в темпе, хотя держать её уже некому.
            for _ in range(5):
                shutil.rmtree(lab, ignore_errors=True)
                if not lab.exists():
                    break
                time.sleep(1)
            # ⛔ ВСЛУХ. `ignore_errors` глотает ровно тот случай, ради которого
            # проверка и нужна: файлы держит живой процесс, и папка остаётся с
            # exe внутри. Молчание здесь = мусор в темпе и занятый порт, о
            # которых узнает кто-то другой.
            if lab.exists():
                print(f"⚠️  лаборатория НЕ удалена: {lab}")
                print("    что-то держит файлы — проверьте процессы DentPilot.exe")

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
