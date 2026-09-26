"""Живые стенды 5 и 6: экран раздвоения в СОБРАННОЙ программе.

    python scripts/check_split_live.py
    python scripts/check_split_live.py --exe dist\\DentPilot.exe --keep

Отвечает на вопрос, которого зелёный прогон не касается: доводит ли до
подтверждения цепочка «лаунчер → вердикт → окружение → экран → оракул», собранная
PyInstaller. Харнесс поднимает `app.main` напрямую и `desktop.py` не исполняет ни
строкой — а вердикт рождается именно там.

⛔ **Стенд 6 НЕ проверяет миграцию.** Он проверяет ровно одно: человек доведён
до `confirmed`, и данных источника при этом никто не касался. Copy-only не
написан, и подтверждение переездом не является.

Раскладка лаборатории (временная папка, удаляется в конце):

    <lab>\\Old\\      DentPilot.exe + профиль + data\\{dental.db, auth.json, метка}
    <lab>\\Anchor\\   профиль + data\\dental.db          ← назначение, картотека есть
    <lab>\\tmp\\      TEMP программы: распаковка onefile (_MEI*)
    $DENTART_DATA_DIR = <lab>\\Anchor

⭐ Источник опознаётся признаком `self`: exe лежит В ПАПКЕ с маркерами данных,
то есть ровно так, как выглядит установка до P1. Ярлыки машины не участвуют.

⛔ **Настоящая `%ProgramData%\\DentPilot` не участвует ни одной стороной** —
инвариант всех стендов, держит `test_launcher`.

⭐ **Список разрешённых изменений в назначении назван поимённо и он короткий.**
Требовать «в назначении не изменилось ничего» нельзя: программа работает, пишет
лог, а отказ обязан записать счётчик попыток. Стенд, краснеющий на исправном
коде, читается как поломка правила и отключается вместе с ней.
"""
import argparse
import http.cookiejar
import json
import os
import pathlib
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "tests"))

from app.core import auth  # noqa: E402
from test_srcpin import _diff, _snapshot  # noqa: E402

KEY = "lab-split-key"
PIN_GOOD = "4321"
PIN_BAD = "0000"
CLINIC_MARK = "LABORATOR SURSA VECHE"
SRC_MARK = "marker-sursa.txt"

# Что назначению МОЖНО изменить, пока идёт подтверждение. Всё остальное в
# разнице — красное.
ALLOWED = {
    "file:data\\srcpin_fail.json",   # счётчик попыток: ему тут и место
    "file:data\\dental.db-wal",      # работающая база трогает журнал
    "file:data\\dental.db-shm",
    "file:data\\dentpilot.log",      # программа пишет лог, она живая
}
ALLOWED_OK = ALLOWED | {"file:migration.json"}   # запись ответа — только на удаче


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _db(p: pathlib.Path) -> None:
    """Настоящий файл SQLite, а не пустышка: у нулевого файла нет заголовка, и
    `fingerprint` объявил бы его ЗАШИФРОВАННЫМ — экран соврал бы на ровном месте."""
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE IF NOT EXISTS lab(x INTEGER)")
    con.commit()
    con.close()


def build_lab(lab: pathlib.Path, exe: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    old, anchor = lab / "Old", lab / "Anchor"
    profile = json.loads((ROOT / "bot" / "app" / "clinic_new.json")
                         .read_text(encoding="utf-8"))
    for root, name in ((old, CLINIC_MARK), (anchor, "LABORATOR DESTINATIE")):
        root.mkdir(parents=True)
        profile["name"] = name
        (root / "clinic.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "dental.env").write_text("TELEGRAM_TOKEN=\nADMIN_KEY=\n",
                                         encoding="utf-8")
        _db(root / "data" / "dental.db")

    # PIN источника — теми же полями, что пишет сама программа: своя формула в
    # лаборатории означала бы, что стенд проверяет не тот файл, который лежит
    # у клиники.
    users = [{"id": "dir", "role": auth.ROLE_DIRECTOR, "name": "Director",
              **auth._secret_fields(PIN_GOOD)}]
    (old / "data" / "auth.json").write_text(
        json.dumps({"v": 2, "cookie_key": "lab" * 20, "users": users}, indent=1),
        encoding="utf-8")
    # ⭐ Именная метка: если что-нибудь СКОПИРУЕТ источник в назначение, она
    # приедет вместе со всем остальным и будет видна поимённо.
    (old / "data" / SRC_MARK).write_text("sursa", encoding="utf-8")

    shutil.copy(exe, old / "DentPilot.exe")
    return old, anchor


def run_lab(old: pathlib.Path, anchor: pathlib.Path, port: int, seconds: int = 90):
    env = dict(os.environ)
    # ⛔ (09-26) TEMP — внутри лаборатории, но вне Old и Anchor (их сверяют
    # снимками): stop() гасит загрузчик onefile через taskkill /F, и свою
    # распаковку (_MEI*, 52 МБ) он уже не убирает — она оставалась в %TEMP%.
    tmp = old.parent / "tmp"
    tmp.mkdir(exist_ok=True)
    # ⛔ Назначение объявляем ЯВНО: без этого лаунчер ушёл бы в
    # %ProgramData%\DentPilot, то есть в живую картотеку машины, и не упал бы.
    env.update({"DENTART_BROWSER_MODE": "1", "DENTART_NO_BROWSER": "1",
                "DENTART_PORT": str(port), "ADMIN_KEY": KEY,
                "DENTART_DATA_DIR": str(anchor), "TEMP": str(tmp), "TMP": str(tmp)})
    # ⚠️ Переменную вердикта в окружение НЕ кладём: её обязан поставить сам
    # лаунчер. Положили бы — стенд проверял бы собственную подсказку.
    env.pop("DENTART_SPLIT_SOURCE", None)
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
    """Погасить ДЕРЕВО: onefile-сборка это загрузчик плюс дочерний процесс, и
    убитый загрузчик оставляет живого ребёнка с портом и файлом exe в руках."""
    if proc is None or proc.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


class Http:
    """Клиент с кукой и БЕЗ следования редиректам: Location и есть поведение."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect)

    def _do(self, path: str, data: bytes | None = None):
        req = urllib.request.Request(self.base + path, data=data)
        try:
            with self.op.open(req, timeout=20) as r:
                return r.status, r.headers.get("Location", ""), r.read().decode(
                    "utf-8", "replace")
        except urllib.error.HTTPError as e:
            # ⛔ HTTPError ловим ОТДЕЛЬНО и ДО OSError: он его наследник, и
            # общий except превратил бы честный 403 в «запрос не состоялся» —
            # стенд краснел бы правдоподобно, уводя чинить не то.
            return e.code, e.headers.get("Location", ""), e.read().decode(
                "utf-8", "replace")
        except OSError as e:
            return 0, "", f"ЗАПРОС НЕ СОСТОЯЛСЯ: {e}"

    def get(self, path: str):
        return self._do(path)

    def post(self, path: str, **fields):
        return self._do(path, urllib.parse.urlencode(fields).encode())

    def login(self) -> bool:
        self._do("/admin/login", urllib.parse.urlencode({"password": KEY}).encode())
        return any(c.name == "admin_auth" for c in self.jar)


def changed(before: dict, after: dict) -> set:
    return ({k for k in set(before) ^ set(after)}
            | {k for k in set(before) & set(after) if before[k] != after[k]})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(ROOT / "dist" / "DentPilot.exe"))
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    exe = pathlib.Path(args.exe)
    if not exe.exists():
        # ⚠️ ВСЛУХ и своим кодом возврата: молчаливый пропуск — ложное зелёное.
        print(f"ПРОПУЩЕНО: {exe} не собран — проверять нечего.")
        print("Соберите: powershell -File Build-Desktop.ps1")
        return 2

    lab = pathlib.Path(tempfile.mkdtemp(prefix="dp_splitlive_"))
    old, anchor = build_lab(lab, exe)
    src0 = _snapshot(old)
    port, proc, bad5, bad6 = free_port(), None, [], []
    try:
        proc, base, alive = run_lab(old, anchor, port)
        if not alive:
            print(f"КРАСНО: программа не поднялась.\n  лаборатория: {lab}")
            return 1
        c = Http(base)

        # --- предусловие: раздвоение НАЙДЕНО собранным лаунчером -----------
        st, _loc, page = c.get("/admin/migration")
        if st != 200:
            bad5.append(f"экран раздвоения не открылся: HTTP {st} "
                        "(лаунчер не объявил вердикт приложению?)")
        else:
            for want, why in ((str(old), "источник"), (str(anchor), "назначение")):
                if want not in page:
                    bad5.append(f"на экране не назван {why}: {want}")
            if "Numărul de pacienți nu este" not in page:
                bad5.append("экран молчит о том, что числа записей не показывает")
        if not c.login():
            bad5.append("вход по ADMIN_KEY не состоялся — баннер не проверить")
        elif "/admin/migration" not in c.get("/admin")[2]:
            bad5.append("директор НЕ видит сигнал: баннера раздвоения нет в журнале")

        dst0 = _snapshot(anchor)

        # --- СТЕНД 5: неправильный PIN -------------------------------------
        st, loc, _b = c.post("/admin/migration/confirm", choice="old", pin=PIN_BAD)
        if st != 303 or not loc.startswith("/admin/migration"):
            bad5.append(f"отказ не вернул на экран: HTTP {st}, Location {loc!r}")
        if "msg=mig_bad" not in loc:
            bad5.append(f"отказ не назван кодом mig_bad: {loc!r}")
        if (d := changed(src0, _snapshot(old))):
            bad5.append(f"ИСТОЧНИК ИЗМЕНЁН при отказе: {_diff(src0, _snapshot(old))}")
            del d
        dst1 = _snapshot(anchor)
        if (extra := changed(dst0, dst1) - ALLOWED):
            bad5.append(f"в назначении изменилось лишнее: {sorted(extra)}")
        if "file:data\\srcpin_fail.json" not in changed(dst0, dst1):
            bad5.append("счётчик попыток не записан — перебор ничем не ограничен")
        if (anchor / "migration.json").exists():
            bad5.append("отказ записал выбор в migration.json")

        # --- СТЕНД 6: правильный PIN ---------------------------------------
        st, loc, _b = c.post("/admin/migration/confirm", choice="old", pin=PIN_GOOD)
        if st != 303 or "msg=mig_ok" not in loc:
            bad6.append(f"подтверждение не принято: HTTP {st}, Location {loc!r}")
        if changed(src0, _snapshot(old)):
            bad6.append("ИСТОЧНИК ИЗМЕНЁН ПОСЛЕ УДАЧИ: "
                        + _diff(src0, _snapshot(old)))
        if (extra := changed(dst1, _snapshot(anchor)) - ALLOWED_OK):
            bad6.append(f"в назначении изменилось лишнее: {sorted(extra)}")
        mig = anchor / "migration.json"
        if not mig.exists():
            bad6.append("ответ человека не записан: migration.json нет")
        else:
            rec = json.loads(mig.read_text(encoding="utf-8"))
            if rec.get("chosen") != "old":
                bad6.append(f"записан не тот ответ: {rec!r}")
            if rec.get("old") != str(old) or rec.get("new") != str(anchor):
                bad6.append(f"в записи названы не те корни: {rec!r}")
            if rec.get("authoritative"):
                bad6.append("подтверждение объявило копию НАЧАТОЙ — а её нет")
        # ⛔ Никакого Copy/Move: именная метка источника не могла приехать.
        if list(anchor.rglob(SRC_MARK)):
            bad6.append(f"файл источника {SRC_MARK} оказался в назначении — "
                        "подтверждение что-то скопировало")
        if _snapshot(old) != src0:
            bad6.append("источник разошёлся со снимком до запуска")
        st, _loc, _b = c.get("/admin/migration")
        if st != 303:
            bad6.append(f"вопрос не закрыт: экран снова открылся (HTTP {st})")
        log = (anchor / "data" / "dentpilot.log")
        text = log.read_bytes().decode("utf-8", "replace") if log.exists() else ""
        if "раскладка: split" not in text:
            bad6.append(f"в {log} нет строки вердикта с исходом split")
    finally:
        stop(proc)
        if args.keep:
            print(f"лаборатория оставлена: {lab}")
        else:
            for _ in range(5):
                shutil.rmtree(lab, ignore_errors=True)
                if not lab.exists():
                    break
                time.sleep(1)
            if lab.exists():
                print(f"⚠️  лаборатория НЕ удалена: {lab}")
                print("    что-то держит файлы — проверьте процессы DentPilot.exe")

    for name, bad, good in (("СТЕНД 5 (неверный PIN)", bad5,
                             ["отказ показан, источник побайтно тот же",
                              "в назначении только счётчик попыток",
                              "migration.json не создан"]),
                            ("СТЕНД 6 (верный PIN)", bad6,
                             ["подтверждение получено, источник побайтно тот же",
                              "ни копирования, ни записи в базу источника",
                              "ответ записан, копия НЕ объявлена начатой",
                              "вопрос закрыт: экран больше не возвращается"])):
        print(f"\n{name}: {'КРАСНО' if bad else 'ЗЕЛЕНО'}")
        for line in (bad or good):
            print(f"  {'·' if bad else '✓'} {line}")
    return 1 if (bad5 or bad6) else 0


if __name__ == "__main__":
    sys.exit(main())
