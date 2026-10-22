"""Живые стенды 5 и 6: экран раздвоения в СОБРАННОМ движке.

    .venv-desktop\\Scripts\\python.exe scripts\\check_split_live.py
    .venv-desktop\\Scripts\\python.exe scripts\\check_split_live.py --exe dist\\DentPilot-Engine\\DentPilot-Engine.exe --keep

Отвечает на вопрос, которого зелёный прогон не касается: доводит ли до
подтверждения цепочка «лаунчер → вердикт → окружение → экран → оракул», собранная
PyInstaller. Харнесс поднимает `app.main` напрямую и `desktop.py` не исполняет ни
строкой — а вердикт рождается именно там.

Движок запускается так, как его запускает оболочка (с 22.10.2026 другого
запуска нет — окно pywebview снято): `DENTART_SHELL=tauri`, трубы `DP1`,
своё задание Windows, остановка словом `stop` — `engine_check.Engine`.

⛔ **Стенд 6 НЕ проверяет миграцию.** Он проверяет ровно одно: человек доведён
до `confirmed`, и данных источника при этом никто не касался. Copy-only не
написан, и подтверждение переездом не является.

Раскладка лаборатории (временная папка, удаляется в конце):

    <lab>\\Old\\engine\\   движок папкой + профиль + data\\{dental.db, auth.json, метка}
    <lab>\\Anchor\\        профиль + data\\dental.db     ← назначение, картотека есть
    <lab>\\tmp\\           TEMP движка
    $DENTART_DATA_DIR = <lab>\\Anchor

⭐ Источник опознаётся признаком `self`: движок лежит В ПАПКЕ с маркерами
данных (`legacy.running_root` — папка самого процесса, у движка это `engine\\`),
как выглядела установка до P1. Ярлыки машины не участвуют.

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
import secrets
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core import auth  # noqa: E402
from engine_check import READY_LIMIT, STOP_LIMIT, Engine  # noqa: E402 — тот же разговор, что у оболочки
from harness import RUN_TMP, _rmtree_settled, free_port  # noqa: E402
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


def _db(p: pathlib.Path) -> None:
    """Настоящий файл SQLite, а не пустышка: у нулевого файла нет заголовка, и
    `fingerprint` объявил бы его ЗАШИФРОВАННЫМ — экран соврал бы на ровном месте."""
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE IF NOT EXISTS lab(x INTEGER)")
    con.commit()
    con.close()


def build_lab(lab: pathlib.Path, exe: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """(exe в лаборатории, источник, назначение). Движок — папкой в
    `Old\\engine\\`, и источник — она же: `self` это папка самого процесса."""
    old, anchor = lab / "Old" / "engine", lab / "Anchor"
    shutil.copytree(exe.parent, old)
    profile = json.loads((ROOT / "bot" / "app" / "clinic_new.json")
                         .read_text(encoding="utf-8"))
    for root, name in ((old, CLINIC_MARK), (anchor, "LABORATOR DESTINATIE")):
        root.mkdir(parents=True, exist_ok=True)
        profile["name"] = name
        # ⚠️ Назначение — НЕ пустая картотека: у собранной программы есть ключ
        # лицензии, и пустая картотека без файла лицензии — стена активации
        # (`license.walled`, с 02.10): экран раздвоения уезжал бы на
        # /admin/license. Демо-записи программа засеет сама при старте, до
        # снимка назначения.
        profile["seed_demo"] = root == anchor
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
    return old / exe.name, old, anchor


class Lab:
    """Что нужно `engine_check.Engine`: exe, папка для stderr, корень данных
    (для хвоста лога) и окружение запуска."""

    def __init__(self, lab: pathlib.Path, exe: pathlib.Path, anchor: pathlib.Path) -> None:
        self.dir, self.exe, self.data, self.anchor = lab, exe, anchor, anchor

    def env(self, port: int) -> dict:
        anchor = self.anchor
        # ⛔ (09-26) TEMP — внутри лаборатории, но вне Old и Anchor (их сверяют
        # снимками).
        tmp = self.dir / "tmp"
        tmp.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("DENTART_")}
        # ⛔ Назначение объявляем ЯВНО: без этого движок ушёл бы в
        # %ProgramData%, то есть в живую картотеку машины, и не упал бы.
        # ⚠️ Переменную вердикта в окружение НЕ кладём (снята вместе со всеми
        # DENTART_ выше): её обязан поставить сам лаунчер. Положили бы — стенд
        # проверял бы собственную подсказку.
        env.update({"DENTART_SHELL": "tauri", "DENTART_SHELL_TOKEN": secrets.token_hex(16),
                    "DENTART_PORT": str(port), "ADMIN_KEY": KEY,
                    "DENTART_DATA_DIR": str(anchor), "TEMP": str(tmp), "TMP": str(tmp),
                    "DENTART_PROFILE_DIR": str(self.dir / "webview"),
                    "DENTART_UPDATE_CHECK": "off"})
        return env


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
    ap.add_argument("--exe", default=str(ROOT / "dist" / "DentPilot-Engine" / "DentPilot-Engine.exe"))
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    exe = pathlib.Path(args.exe)
    if not exe.exists():
        # ⚠️ ВСЛУХ и своим кодом возврата: молчаливый пропуск — ложное зелёное.
        print(f"ПРОПУЩЕНО: {exe} не собран — проверять нечего.")
        print("Соберите: powershell -File Build-Engine.ps1")
        return 2

    # ⚠️ Лаборатория — в папке прогона харнесса (её сносит выход), а с --keep —
    # рядом, в обычном TEMP: иначе «оставлена» значило бы «снесена на выходе».
    lab = pathlib.Path(tempfile.mkdtemp(prefix="dp_splitlive_",
                                        dir=str(RUN_TMP.parent if args.keep else RUN_TMP)))
    run_exe, old, anchor = build_lab(lab, exe)
    src0 = _snapshot(old)
    e, bad5, bad6 = Engine(Lab(lab, run_exe, anchor), free_port()), [], []
    try:
        e.start()
        ev = e.wait_event({"ready", "busy", "fatal"}, READY_LIMIT)
        if ev is None or ev.get("event") != "ready":
            print(f"КРАСНО: движок не сказал ready (пришло {ev!r}).{e.tail()}")
            print(f"  лаборатория: {lab}")
            return 1
        c = Http(f"http://127.0.0.1:{e.port}")

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
        if e.proc is not None and e.proc.poll() is None:
            try:
                code, _secs = e.wait_exit(e.send_stop(), STOP_LIMIT + 5)
            except OSError:
                code = None
            if code != 0:
                bad6.append(f"движок не остановился словом stop (код {code})")
        e.close()
        if args.keep:
            print(f"лаборатория оставлена: {lab}")
        else:
            _rmtree_settled(lab)
            if lab.exists():
                print(f"⚠️  лаборатория НЕ удалена: {lab}")

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
