r"""Рутина разработки одной командой. Звать через `dev.ps1` из корня `app`.

    .\dev test [фильтр]   прогон (фильтр — кусок имени набора)
    .\dev mutate          проверка сторожей test_structure на слом
    .\dev up [порт]       песочница из исходников на своей базе (по умолчанию 8099)
    .\dev check           готов ли к релизу: дерево, пуш, версия, тег

Зачем скрипт, если команды и так известны. Инструкция «в такой ситуации запусти
это, в такой другое» — спецификация программы, а не документ для человека:
про изменённый `test_structure.py` знает git, а не память. Здесь эти правила
исполняются, а не запоминаются.

Логика в Python, а не в .ps1, намеренно: в PowerShell 5.1 stderr нативной
команды становится ошибкой (при `$ErrorActionPreference = "Stop"` —
терминирующей), нет оператора `&&`, а `$_` внутри `-Command "…"` съедается
внешней оболочкой. Каждая из трёх грабель записана в CLAUDE.md, и все три
обходятся тем, что `git` зовётся из Python.

Только стандартная библиотека — как и тесты.
"""
import os
import pathlib
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = pathlib.Path(__file__).resolve().parents[1]      # …\app
BOT = ROOT / "bot"
PYTHON = ROOT / ".venv-desktop" / "Scripts" / "python.exe"
TESTS = ROOT / "tests"
ENGINE = BOT / "app" / "engine.py"

# Песочница живёт ВНЕ репозитория: не попадает в git, не мешает `check` увидеть
# чистое дерево и переживает между запусками — накопленные данные не теряются.
SANDBOX = pathlib.Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "DentPilot-sandbox"

# Порт установленной у Олега программы. `up` гасит того, кто занял её порт, —
# и на 8088 это была бы рабочая клиника с настоящей картотекой.
INSTALLED_PORT = 8088

OK, NO = "  [ок]  ", "  [!!]  "


def say(good: bool, text: str) -> bool:
    print((OK if good else NO) + text)
    return good


def git(*args: str) -> str:
    """git без ловушек PowerShell: stderr не превращается в исключение.

    ⚠️ Срезаются ТОЛЬКО хвостовые переводы строк. `.strip()` здесь стоил бы
    дорого: у `status --porcelain` первые два символа строки — колонка статуса,
    и у модифицированного файла это « M». Общий strip съедал ведущий пробел
    первой строки, разрез `ln[3:]` уезжал на символ, и подхват мутации не
    срабатывал НИ РАЗУ — молча, потому что «сторожей не тронули» выглядит
    точно так же, как «список пуст»."""
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").rstrip("\n")


def run(cmd: list, cwd: pathlib.Path = ROOT, env: dict | None = None) -> int:
    print(f"$ {' '.join(str(c) for c in cmd)}\n")
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd),
                          env=env or os.environ.copy()).returncode


# ---------- test ----------

def cmd_test(argv: list) -> int:
    """Прогон. Если тронуты сторожа — сперва мутация: их правит не тот, кто
    помнит правило из инструкции, а тот, кто правит код."""
    touched = [ln[3:] for ln in git("status", "--porcelain").splitlines()]
    guards = [f for f in touched
              if f.replace("\\", "/").startswith("tests/")
              and pathlib.Path(f).name in ("test_structure.py", "mutate.py")]
    if guards:
        print(f"Тронуты сторожа ({', '.join(pathlib.Path(g).name for g in guards)})"
              " — сперва мутация.\n")
        if cmd_mutate([]) != 0:
            print("\nМутация не прошла: правило не ловит нарушения. "
                  "Прогон не запускаю — чинить надо сторожа.")
            return 1
        print()
    return run([PYTHON, TESTS / "run_tests.py", *argv])


def cmd_mutate(argv: list) -> int:
    return run([PYTHON, TESTS / "mutate.py", *argv])


# ---------- up ----------

def _listener_pids(port: int) -> list[str]:
    """Кто слушает порт. netstat, а не Get-NetTCPConnection: у последнего в
    `powershell -Command` съедается `$_`, и команда падает на пустом месте."""
    r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    pids = []
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" \
                and parts[1].endswith(f":{port}"):
            pids.append(parts[4])
    return sorted(set(pids))


def cmd_up(argv: list) -> int:
    """Песочница из исходников. Прошлый сервер гасится ОБЯЗАТЕЛЬНО: Windows
    разрешает второй bind на занятый порт, запросы уходят СТАРОМУ процессу, и
    это выглядит как «правка не применилась» (грабля из CLAUDE.md)."""
    port = int(argv[0]) if argv and argv[0].isdigit() else 8099
    if port == INSTALLED_PORT:
        print(f"На {INSTALLED_PORT} работает УСТАНОВЛЕННАЯ программа "
              f"(C:\\Users\\Public\\DentPilot). Песочница её не занимает и не "
              f"гасит — возьми другой порт, например `.\\dev up 8099`.")
        return 2
    for pid in _listener_pids(port):
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
        print(f"Прошлый сервер на {port} погашен (PID {pid}).")

    SANDBOX.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "CLINIC_CONFIG": str(BOT / "app" / "clinic.json"),   # демо-профиль
        "DATABASE_URL": f"sqlite:///{SANDBOX / 'dental.db'}",
        "ADMIN_KEY": "test1234",   # иначе SQLite потребует экран установки PIN
    })
    print(f"База песочницы: {SANDBOX / 'dental.db'}")
    print(f"Журнал:         http://127.0.0.1:{port}/admin   (пароль test1234)")
    print("Гасить: Ctrl+C\n")
    return run([PYTHON, "-m", "uvicorn", "app.main:app", "--port", str(port)],
               cwd=BOT, env=env)


# ---------- check ----------

def cmd_check(argv: list) -> int:
    """Предполётная проверка релизной лестницы. Отвечает «чего не хватает»
    ДО сборки, а не на третьем её шаге."""
    print("Готовность к релизу\n")
    ok = True

    dirty = git("status", "--porcelain")
    ok &= say(not dirty, "дерево чистое" if not dirty else
              f"дерево грязное — Build-Installer откажет:\n"
              + "\n".join("          " + l for l in dirty.splitlines()))

    ahead = git("rev-list", "--count", "origin/main..main").strip()
    ok &= say(ahead == "0", "всё запушено" if ahead == "0" else
              f"не запушено коммитов: {ahead} — тег повиснет на origin/main "
              f"и опишет НЕ ТОТ код")

    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', ENGINE.read_text(encoding="utf-8"))
    ver = m.group(1) if m else ""
    three = bool(re.fullmatch(r"\d+\.\d+\.\d+", ver))
    ok &= say(three, f"APP_VERSION = {ver}" if three else
              f"APP_VERSION = {ver!r} — нужны ровно три числа")

    # ⚠️ Тег ПОЗАДИ HEAD — нормальное состояние между релизами, а не поломка:
    # выпустили версию, работа пошла дальше. Красить это в [!!] значит завести
    # баннер, который горит каждый день, — его перестанут читать ровно к тому
    # разу, когда он прав (та же грабля, что с жёлтым `ok_past`). Красное здесь
    # только на настоящем расхождении: тег на ветке, которой в HEAD нет.
    bump = False
    if three:
        tag = f"v{ver}"
        at = git("rev-list", "-n", "1", tag).strip()
        head = git("rev-parse", "HEAD").strip()
        if not at:
            say(True, f"тега {tag} ещё нет — создать после сборки, "
                      f"на тот коммит, из которого собрано")
        elif at == head:
            say(True, f"тег {tag} на HEAD — собрано будет ровно это")
        elif git("rev-list", "--count", f"HEAD..{tag}").strip() == "0":
            n = git("rev-list", "--count", f"{tag}..HEAD").strip()
            bump = True
            say(True, f"{ver} уже выпущена, сверху коммитов: {n}")
        else:
            ok &= say(False, f"тег {tag} стоит на {at[:7]}, и этого коммита нет "
                             f"в HEAD {head[:7]} — тег описывает другую ветку")

    # Есть ли что выпускать. В exe едет ТОЛЬКО bot/: тесты, scripts, dev.ps1,
    # README и скриншоты не пакуются, и релиз с одними ими повёз бы клинике
    # 30 МБ ради новой строки версии.
    # ⚠️ Информационно, не [!!]: сразу после релиза «в bot/ пусто» — норма, и
    # красная строка тут горела бы постоянно (та же ловушка, что с тегом выше).
    base = git("describe", "--tags", "--abbrev=0").strip()
    empty = False
    if base:
        stat = [l for l in git("diff", "--numstat", f"{base}..HEAD",
                               "--", "bot/").splitlines() if l.strip()]
        # подъём версии — одна строка в engine.py: сам по себе он не содержание
        only_bump = (len(stat) == 1 and stat[0].endswith("engine.py")
                     and stat[0].split("\t")[:2] == ["1", "1"])
        empty = not stat or only_bump
        say(True, f"в bot/ с {base} изменений нет" if not stat else
                  f"в bot/ с {base} только подъём версии" if only_bump else
                  f"в bot/ с {base} изменено файлов: {len(stat)}")

    print()
    if not ok:
        print("Сначала закрыть отмеченное [!!] — иначе лестница сломается "
              "на середине.")
    elif empty:
        print(f"⛔ Выпускать нечего: программа не менялась с {base}. Такой релиз "
              f"повёз бы\n   клинике 30 МБ ради новой строки версии, канарейке "
              f"нечего было бы\n   проверять руками, а откатить нельзя — релизы "
              f"только вперёд.")
    elif bump:
        print(f"К работе готов. Перед РЕЛИЗОМ поднять APP_VERSION: {ver} уже "
              f"выпущена, и сборка из этого кода назвалась бы её именем.")
    else:
        print("Можно собирать:  powershell -File Build-Installer.ps1")
        print("Прогон перед этим:  .\\dev test")
    return 0 if ok else 1


# ---------- точка входа ----------

COMMANDS = {"test": cmd_test, "mutate": cmd_mutate, "up": cmd_up,
            "check": cmd_check}


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.split("Зачем скрипт")[0].rstrip())
        return 0 if argv else 2
    cmd = COMMANDS.get(argv[0])
    if cmd is None:
        print(f"Нет команды {argv[0]!r}. Есть: {', '.join(COMMANDS)}")
        return 2
    return cmd(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
