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
     [("if (_code := privileged.handle_argv(sys.argv[1:], data_root)) is not None:\n"
       "    raise SystemExit(_code)\n", ""),
      ("ROOT, _verdict = relocate.root_for(ROOT)",
       "if (_code := privileged.handle_argv(sys.argv[1:], data_root)) is not None:\n"
       "    raise SystemExit(_code)\n"
       "ROOT, _verdict = relocate.root_for(ROOT)")],
     None, "и спрашивает ДО вычисления корня", "лаунчер"),

    # ---- P4.2 ----
    ("подмена ЗАПУСКАЕТ новый файл", PRIV,
     '    old = exe.with_name(exe.stem + OLD_SUFFIX)',
     "    import subprocess\n"
     "    subprocess.Popen([str(new)])\n"
     "    old = exe.with_name(exe.stem + OLD_SUFFIX)",
     "в исполнителе нет: запуск процесса"),

    ("операция берёт путь аргументом", PRIV,
     "    if args:\n        raise Refused(",
     "    if False:\n        raise Refused(",
     "путь снаружи отвергнут"),

    ("прежняя программа удаляется", PRIV,
     "        old.unlink(missing_ok=True)\n        exe.rename(old)",
     "        old.unlink(missing_ok=True)\n        exe.unlink()",
     "прежняя программа лежит рядом"),

    ("скачивание снова рядом с exe", UPD,
     '    new_path = work_dir() / (exe.stem + ".new.exe")',
     '    new_path = exe.with_name(exe.stem + ".new.exe")',
     "скачанный файл — в папке клиники"),

    ("скрипт обновления снова рядом с exe", UPD,
     '    bat = work_dir() / "dentpilot_update.bat"',
     '    bat = exe.with_name("dentpilot_update.bat")',
     "скрипт обновления — в папке клиники"),

    ("портативной раскладке показывают UAC", UPD,
     "    if not exe_dir_writable():\n        return _install_privileged(new_path, exe)",
     "    if True:\n        return _install_privileged(new_path, exe)",
     "портативной раскладке окно UAC не показывается"),

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
