"""Живая проверка ветки `unique` (P2, шаги 1–3 + лаунчер) на СОБРАННОМ движке.

    .venv-desktop\\Scripts\\python.exe scripts\\check_relocate_live.py
    .venv-desktop\\Scripts\\python.exe scripts\\check_relocate_live.py --exe dist\\DentPilot-Engine\\DentPilot-Engine.exe

Отвечает на вопрос, который зелёный прогон НЕ проверяет и проверить не может:
исполняет ли СОБРАННЫЙ движок ветку `unique`. Харнесс поднимает `app.main`
напрямую и `desktop.py` не исполняет ни строкой — прайор карты, — а правило
`relocate.root_for` проверено как чистая функция. Между правилом и поведением
стоят PyInstaller и файловая система, и ровно в этом промежутке 21.09 нашлись
три дефекта подряд.

Движок запускается так, как его запускает оболочка (с 22.10.2026 другого
запуска нет — окно pywebview снято): `DENTART_SHELL=tauri`, трубы `DP1`,
своё задание Windows, остановка словом `stop` — `engine_check.Engine`.

⛔ **Не «exe запустился — зелено».** Стенд отвечает «ожидался старый корень →
открылся старый корень», и зелёным считается выполнение ВСЕХ трёх утверждений:

  1. программа работает из СТАРОГО корня — журнал открылся, и на странице видно
     имя клиники из старого `clinic.json`, а не из вшитого профиля;
  2. НАЗНАЧЕНИЕ осталось пустым: ни `data\\`, ни `clinic.json`, ни `dental.env`;
  3. в `data\\dentpilot.log` старого корня лежит строка вердикта с исходом `unique`.

Раскладка лаборатории (всё во временной папке, удаляется в конце):

    <lab>\\Old\\engine\\   движок папкой + clinic.json + dental.env  ← «старая установка»
    <lab>\\Anchor\\        пусто                                     ← назначение
    <lab>\\tmp\\           TEMP движка
    $DENTART_DATA_DIR = <lab>\\Anchor

⚠️ Маркеры данных лежат в `engine\\`, а не над ним: источник `self` — папка
САМОГО процесса (`legacy.running_root`), у движка это `engine\\`. Раскладка не
про клинику, а про то, что собранный движок ИСПОЛНЯЕТ ветку `unique`.

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
import secrets
import shutil
import sys
import tempfile
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
sys.path.insert(0, str(ROOT / "scripts"))
from engine_check import READY_LIMIT, STOP_LIMIT, Engine  # noqa: E402 — тот же разговор, что у оболочки
from harness import RUN_TMP, _rmtree_settled, free_port  # noqa: E402

KEY = "lab-relocate-key"
CLINIC_MARK = "LABORATOR RADACINA VECHE"


class Lab:
    """Что нужно `engine_check.Engine`: exe, папка для stderr, корень данных
    (для хвоста лога) и окружение запуска."""

    def __init__(self, lab: pathlib.Path, exe: pathlib.Path, old: pathlib.Path,
                 anchor: pathlib.Path) -> None:
        self.dir, self.exe, self.data, self.anchor = lab, exe, old, anchor

    def env(self, port: int) -> dict:
        anchor = self.anchor
        # ⛔ (09-26) TEMP — внутри лаборатории, но вне Old и Anchor.
        tmp = self.dir / "tmp"
        tmp.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("DENTART_")}
        # ⛔ Назначение объявляем ЯВНО. Без этого движок ушёл бы в
        # %ProgramData%\DentPilot — то есть проверял бы не лабораторию, а живую
        # картотеку машины, и не упал бы при этом.
        env.update({"DENTART_SHELL": "tauri", "DENTART_SHELL_TOKEN": secrets.token_hex(16),
                    "DENTART_PORT": str(port), "ADMIN_KEY": KEY,
                    "DENTART_DATA_DIR": str(anchor), "TEMP": str(tmp), "TMP": str(tmp),
                    "DENTART_PROFILE_DIR": str(self.dir / "webview"),
                    "DENTART_UPDATE_CHECK": "off"})
        return env


def build_lab(lab: pathlib.Path, exe: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Старый корень с профилем и пустое назначение. Возвращает (exe в
    лаборатории, старый корень, назначение).

    ⭐ Базу НЕ кладём намеренно: `clinic.json` — такой же маркер данных, как и
    она, а отсутствие базы делает проверку строже. Если ветка `unique`
    сработала, программа заведёт журнал В СТАРОМ корне; если не сработала —
    заведёт его в назначении, и второе утверждение стенда покраснеет. Разница
    видна на файловой системе, а не в интерпретации.
    """
    old = lab / "Old" / "engine"
    anchor = lab / "Anchor"
    shutil.copytree(exe.parent, old)
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
    return old / exe.name, old, anchor


def admin_page(base: str) -> tuple[str, str]:
    """Журнал глазами вошедшего. Возвращает `(страница, чем_плохо)`.

    ⛔ Поле формы — `password`, а НЕ `key` (`modules/entry/routes.py`,
    `password: str = Form(...)`, живёт с 30.07). С `key` маршрут отвечает 422,
    и стенд не логинился ни разу.
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
    ap.add_argument("--exe", default=str(ROOT / "dist" / "DentPilot-Engine" / "DentPilot-Engine.exe"))
    ap.add_argument("--keep", action="store_true",
                    help="не удалять лабораторию (разбор после красноты)")
    args = ap.parse_args()

    exe = pathlib.Path(args.exe)
    if not exe.exists():
        # ⚠️ ВСЛУХ и отдельным кодом возврата. Молчаливый пропуск — это ложное
        # зелёное: обёртка приняла бы «нечего проверять» за «проверено».
        print(f"ПРОПУЩЕНО: {exe} не собран — проверять нечего.")
        print("Соберите: powershell -File Build-Engine.ps1")
        return 2

    # ⚠️ Лаборатория — в папке прогона харнесса (её сносит выход), а с --keep —
    # рядом, в обычном TEMP: иначе «оставлена» значило бы «снесена на выходе».
    lab = pathlib.Path(tempfile.mkdtemp(prefix="dp_relocate_",
                                        dir=str(RUN_TMP.parent if args.keep else RUN_TMP)))
    run_exe, old, anchor = build_lab(lab, exe)
    e = Engine(Lab(lab, run_exe, old, anchor), free_port())
    bad = []
    try:
        e.start()
        ev = e.wait_event({"ready", "busy", "fatal"}, READY_LIMIT)
        if ev is None or ev.get("event") != "ready":
            print(f"КРАСНО: движок не сказал ready (пришло {ev!r}).{e.tail()}")
            print(f"  лаборатория: {lab}")
            return 1
        base = f"http://127.0.0.1:{e.port}"

        # 1. работаем из СТАРОГО корня — это видно по профилю на странице
        page, trouble = admin_page(base)
        if trouble:
            # ⛔ Отдельная строка, а не «профиль чужой»: стенд, который не вошёл,
            # ничего не знает о профиле и обязан сказать именно это.
            bad.append(f"проверить профиль не удалось — {trouble}")
        elif CLINIC_MARK not in page:
            bad.append("на странице нет имени клиники из старого корня: "
                       "программа открыла ЧУЖОЙ профиль")
        if pathlib.Path(ev.get("data") or ".").resolve() != old.resolve():
            bad.append(f"движок назвал оболочке папку данных {ev.get('data')!r}, а не {old}")

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
        if e.proc is not None and e.proc.poll() is None:
            try:
                code, _secs = e.wait_exit(e.send_stop(), STOP_LIMIT + 5)
            except OSError:
                code = None
            if code != 0:
                bad.append(f"движок не остановился словом stop (код {code})")
        e.close()
        if args.keep:
            print(f"лаборатория оставлена: {lab}")
        else:
            # ⛔ ВСЛУХ. Файлы может держать недобитый процесс — молчание здесь =
            # мусор в темпе и занятый порт, о которых узнает кто-то другой.
            _rmtree_settled(lab)
            if lab.exists():
                print(f"⚠️  лаборатория НЕ удалена: {lab}")

    if bad:
        print("КРАСНО:")
        for b in bad:
            print(f"  · {b}")
        return 1
    print("ЗЕЛЕНО: ветка unique исполнена собранным движком.")
    print("  · журнал открыт в СТАРОМ корне (имя клиники оттуда)")
    print("  · назначение осталось пустым")
    print("  · вердикт unique записан в лог")
    return 0


if __name__ == "__main__":
    sys.exit(main())
