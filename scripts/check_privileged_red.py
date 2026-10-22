# -*- coding: utf-8 -*-
"""Красная половина P4: каждое утверждение об исполнителе обязано КРАСНЕТЬ.

    D:\\DentProject\\app\\.venv-desktop\\Scripts\\python.exe scripts\\check_privileged_red.py

Зачем отдельно. Набор `tests\\test_privileged.py` устроен как «этого в коде
нет», и такая проверка зелена не только когда запрета не нарушили, но и когда
она сама сломана — искала не то, разбирала не так, ошиблась именем. Урок
записан как `prior-bench-false-red`.

⛔ И цена ошибки здесь выше обычной: за UAC исполняется код с правами
администратора. Сторож, молча переставший проверять, означает не «стало хуже
тестам», а «запрет исчез».

Как устроено: поломка вносится в НАСТОЯЩЕЕ дерево, набор гоняется, файл
возвращается из копии — всегда, через `finally`.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP = pathlib.Path(__file__).resolve().parents[1]
PY = APP / ".venv-desktop" / "Scripts" / "python.exe"
RUN = APP / "tests" / "run_tests.py"

PRIV = "bot/app/privileged.py"
UPD = "bot/app/update.py"
DESK = "bot/desktop.py"
QR = "bot/app/modules/qr/routes.py"
ENGINE_RS = "shell/src/engine.rs"
WATCH_RS = "shell/src/watch.rs"
OPEN = "bot/app/core/shellopen.py"

# (что сломано, файл, что заменить, чем, какая проверка обязана покраснеть)
BREAKS = [
    # ---- P4.1 ----
    ("исполнитель запускает оболочку, а не свой exe", PRIV,
     'return shell(None, "runas", sys.executable, line, None, 0) > 32',
     'return shell(None, "runas", "cmd" + ".exe", "/c " + line, None, 0) > 32',
     "запускается наш собственный файл"),

    ("имя операции не сверяется со списком", PRIV,
     "    op = OPS.get(name)\n    if op is None:",
     "    op = OPS.get(name, _set_uninstall_version)\n    if False:",
     "операции вне словаря не существует"),

    # ⚠️ Длину оставляем: полное снятие проверки роняло набор `IndexError`
    # на пустом списке, и красное приходило от падения, а не от правила.
    ("версия принимается любой строкой", PRIV,
     "    if len(args) != 1 or not VERSION_RE.match(args[0]):",
     "    if len(args) != 1:",
     "версия: отвергнуто"),

    ("приложение снова пишет в реестр само", UPD,
     "def uninstall_entry() -> dict:",
     "def _mut(k, v):\n"
     "    import winreg\n"
     "    winreg.SetValueEx(k, 'DisplayVersion', 0, winreg.REG_SZ, v)\n\n\n"
     "def uninstall_entry() -> dict:",
     "в реестр пишет только privileged.py"),

    ("лаунчер зовёт привилегированное ПОСЛЕ корня", DESK,
     [("if (_code := privileged.handle_argv(sys.argv[1:], data_root, BASE)) is not None:\n"
       "    raise SystemExit(_code)\n", ""),
      ("ROOT, _verdict = relocate.root_for(ROOT)",
       "if (_code := privileged.handle_argv(sys.argv[1:], data_root, BASE)) is not None:\n"
       "    raise SystemExit(_code)\n"
       "ROOT, _verdict = relocate.root_for(ROOT)")],
     None, "и спрашивает ДО вычисления корня", "лаунчер"),

    # ---- P4.2 (с 22.10.2026 подмены одного exe нет; путь — установщик) ----
    # ⚠️ Кусок — с телом именно `install-setup`: начало «if args: raise
    # Refused(» есть у трёх операций, и поломка без хвоста не вносилась бы
    # вовсе («ПРОМАХ»), пока сторож считался исправным (найдено 18.10, Т10).
    ("операция берёт путь аргументом", PRIV,
     '    if args:\n        raise Refused(f"операция не принимает аргументов, получено {args!r}")\n'
     "    import hashlib\n    import json\n    import pathlib\n    from . import authenticode\n",
     '    if False:\n        raise Refused(f"операция не принимает аргументов, получено {args!r}")\n'
     "    import hashlib\n    import json\n    import pathlib\n    from . import authenticode\n",
     "путь снаружи отвергнут"),

    ("скачивание снова рядом с exe", UPD,
     '    zpath = work / "DentPilot-Setup.zip"',
     '    zpath = pathlib.Path(sys.executable).resolve().parent / "DentPilot-Setup.zip"',
     "скачанный архив установщика — в папке клиники"),

    # ---- Т10: движок оболочки Tauri за UAC и путь обновления у оболочки (18.10) ----
    ("копия мастера у движка ложится в engine", PRIV,
     "    dst = prog_root / SETUP_DIR / SETUP_NAME",
     "    dst = _self_exe().parent / SETUP_DIR / SETUP_NAME",
     "копия мастера — в корне программы"),

    ("стоящую версию спрашивают у движка, а не у оболочки", PRIV,
     "    prog_root, exe, _engine = _layout(base)",
     "    prog_root, _prog, _engine = _layout(base)\n    exe = _self_exe()",
     "стоящая версия — у оболочки"),

    ("лаунчер не отдаёт исполнителю свой корень", DESK,
     "privileged.handle_argv(sys.argv[1:], data_root, BASE)",
     "privileged.handle_argv(sys.argv[1:], data_root)",
     "лаунчер передаёт исполнителю свой корень"),

    # 22.10.2026: рычаг назад на подмену exe снят — строка в dental.env не
    # должна отнимать у клиники единственный путь обновления
    ("рычаг DENTART_UPDATE_VIA=exe снова отнимает путь установщика", UPD,
     '    return bool(STATE["setup_url"]) and uninstall_entry()["found"]',
     '    if os.environ.get("DENTART_UPDATE_VIA") == "exe":\n        return False\n'
     '    return bool(STATE["setup_url"]) and uninstall_entry()["found"]',
     "путь установщика"),

    ("движок не просит оболочку закрыться", UPD,
     "    if sidecar.request_quit(reason):",
     "    if True:",
     "просьба оболочке"),

    ("сторож у оболочки ждёт движок, а не оболочку", UPD,
     "    return os.getppid()",
     "    return os.getpid()",
     "сторож ждёт выхода ОБОЛОЧКИ"),

    # ---- 18.10 (2.0.2): мастер переживает задание оболочки — стенд без UAC ----
    # Живой проход 2.0.0 → 2.0.1 встал: процесс за UAC наследует задание
    # оболочки, и по «started» Windows гасила его до запуска мастера.
    ("оболочка не разрешает выход из задания", ENGINE_RS,
     "pub const JOB_LIMITS: u32 = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;",
     "pub const JOB_LIMITS: u32 = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;",
     "мастер пережил закрытие оболочки"),

    ("мастер не просит выхода из задания", PRIV,
     "                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP\n"
     "                     | CREATE_BREAKAWAY_FROM_JOB,",
     "                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,",
     "мастер пережил закрытие оболочки"),

    # порядок 2.0.0/2.0.1 — «started», сон, запуск — при исправных задании и флаге
    ("«started» раньше запуска мастера и сон перед ним (2.0.1)", PRIV,
     "    try:\n        _spawn_setup(dst, result, work / SETUP_LOG)",
     "    done(STARTED)\n    time.sleep(3.0)\n"
     "    try:\n        _spawn_setup(dst, result, work / SETUP_LOG)",
     "мастер пережил закрытие оболочки"),

    ("мастер не запустился — «fail» при живой программе", PRIV,
     '        return done(f"установщик не запустился: {e}")',
     '        return done(f"fail\\nустановщик не запустился: {e}")',
     "отказ словами до «started»"),

    ("сторож оболочки ищет мастер не под тем именем", WATCH_RS,
     'const SETUP_NAMES: [&str; 2] = ["DentPilot-Setup.exe", "DentPilot-Setup.tmp"];',
     'const SETUP_NAMES: [&str; 2] = ["DentPilot-Setup-new.exe", "DentPilot-Setup.tmp"];',
     "сторож оболочки узнаёт мастер", "Перезапуск: у оболочки"),

    # ---- 18.10 (2.0.3): документ фиши переживает задание оболочки ----
    # Word, открытый ребёнком движка, гас вместе с DentPilot. ⚠️ Поломку
    # «путь списком» сюда не класть: explorer открывает на экране окна папок.
    ("документ открывается os.startfile — в задании оболочки", OPEN,
     "    try:\n        subprocess.Popen(line, creationflags=BREAKAWAY, **kw)\n"
     "    except PermissionError:\n        subprocess.Popen(line, **kw)\n",
     "    os.startfile(path)\n",
     "документ пережил закрытие DentPilot", "стенд задания"),

    ("задание без права выхода — документ не открывается", OPEN,
     "    except PermissionError:\n        subprocess.Popen(line, **kw)\n",
     "    except ZeroDivisionError:\n        pass\n",
     "задание без права выхода: документ открылся", "стенд задания"),

    # ---- P4.3 ----
    ("привилегированный процесс НЕ выходит", PRIV,
     "    if len(argv) < 2 or argv[0] != FLAG:\n        return None",
     "    if True:\n        return None",
     "лаунчер получает код выхода"),

    ("третий способ поднять права", QR,
     "router = APIRouter()",
     "def _mut_elevate(path):\n"
     '    import ctypes\n'
     '    return ctypes.windll.shell32.ShellExecuteW(None, "runas", path,\n'
     "                                               None, None, 1)\n\n\n"
     "router = APIRouter()",
     "повышение прав живёт в одном месте"),
]

FILTER = "P4"


def _run(flt: str = FILTER) -> tuple[int, str]:
    r = subprocess.run([str(PY), str(RUN), flt], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=str(APP))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    files = sorted({b[1] for b in BREAKS})
    orig = {rel: (APP / rel).read_text(encoding="utf-8") for rel in files}
    bad = 0
    try:
        for name, rel, old, new, want, *rest in BREAKS:
            flt = rest[0] if rest else FILTER
            src = orig[rel]
            edits = old if isinstance(old, list) else [(old, new)]
            if [o for o, _w in edits if src.count(o) != 1]:
                print(f"  ПРОМАХ {name}: кусок не найден однозначно в {rel}")
                bad += 1
                continue
            broken = src
            for o, w in edits:
                broken = broken.replace(o, w)
            (APP / rel).write_text(broken, encoding="utf-8")
            code, out = _run(flt)
            (APP / rel).write_text(src, encoding="utf-8")
            red = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("✗")]
            hit = [ln for ln in red if want in ln]
            ok = code != 0 and hit
            print(f"  {'красное' if ok else 'ЗЕЛЁНОЕ (сторож молчит)'}: {name}")
            if not ok:
                bad += 1
                print(f"        ждали про «{want}», красных строк: {len(red)}")
            for ln in red[:2]:
                print("        " + ln)
    finally:
        for rel, text in orig.items():
            (APP / rel).write_text(text, encoding="utf-8")
        print("\n  файлы возвращены из копии")

    code, out = _run()
    lcode, lout = _run("лаунчер")
    code = code or lcode
    tail = [ln for ln in (out + lout).splitlines() if "прошло" in ln]
    print(f"  контроль на исправном: {'зелёный' if not code else 'КРАСНЫЙ'}"
          f" — {' · '.join(tail)}")
    if bad or code:
        print(f"\n  неисправных сторожей: {bad}")
        return 1
    print("\n  все запреты исполнителя краснеют на сломанном коде")
    return 0


if __name__ == "__main__":
    sys.exit(main())
