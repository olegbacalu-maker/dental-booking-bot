# -*- coding: utf-8 -*-
"""Отрицательная половина стенда экрана раздвоения: сторож обязан КРАСНЕТЬ.

    D:\\DentProject\\app\\.venv-desktop\\Scripts\\python.exe scripts\\check_split_red.py

Зачем отдельный скрипт. `tests\\test_split.py` устроен как «всё на месте», и
такой набор зелен не только когда программа права, но и когда сам он сломан —
опечатка в имени поля, слишком широкое условие, проверка не того ответа. Урок
записан в памяти как `prior-bench-false-red`: 21.09 два утверждения из четырёх
краснели на ЛЮБОМ бинарнике, и отрицательная половина это скрывала.

Как устроено: каждая поломка вносится в НАСТОЯЩЕЕ дерево, набор гоняется,
файл возвращается из копии — всегда, через `finally`. Копии снимаются до первой
правки. ⚠️ Дерево при этом обязано быть чистым: скрипт правит рабочие файлы, и
незакоммиченная правка рядом с поломкой вернётся вместе с ней.

⭐ Мутации выбраны не «по одной на функцию», а по одной на УТВЕРЖДЕНИЕ
контракта: ни байта до ответа, отказ ничего не записывает, ответ закрывает
вопрос навсегда, исход оракула решает, форма закрыта от чужой страницы, свой
корень подтверждается своим правом, и подтверждение не объявляет копию начатой.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP = pathlib.Path(__file__).resolve().parents[1]
PY = APP / ".venv-desktop" / "Scripts" / "python.exe"
RUN = APP / "tests" / "run_tests.py"

ROUTES = "bot/app/modules/migration/routes.py"
RELOC = "bot/app/relocate.py"
STATE = "bot/app/migstate.py"

# (что сломано, файл, что заменить, чем, какая проверка обязана покраснеть,
#  каким фильтром гнать прогон — ⚠️ фильтр ОДИН аргумент, подстрокой)
DESK = "bot/desktop.py"
# Точка, ВЫШЕ которой обязан стоять вердикт: ниже неё окружение пополняется
# ключами `dental.env`, то есть файлом, который правит клиника.
MERGE = ("for k, v in envfile.read_all(env_path).items():\n"
         "    os.environ.setdefault(k, v)")
BREAKS = [
    ("экран записывает выбор уже при ПОКАЗЕ", ROUTES,
     "    dst = paths.data_root()\n    src_fp, dst_fp",
     "    dst = paths.data_root()\n"
     "    migstate.record_choice(dst, old=str(src), new=str(dst),\n"
     "                           choice=migstate.CHOICE_OLD, at='x')\n"
     "    src_fp, dst_fp",
     "до ответа migration.json не создан"),

    ("отказ всё равно записывает выбор", ROUTES,
     '    if verdict["outcome"] != SRC_OK:\n'
     '        return RedirectResponse(f"{PAGE}?msg={code}", 303)',
     '    if verdict["outcome"] != SRC_OK:\n'
     '        migstate.record_choice(dst, old=str(src), new=str(dst),\n'
     '                               choice=migstate.CHOICE_OLD, at=at)\n'
     '        return RedirectResponse(f"{PAGE}?msg={code}", 303)',
     "migration.json так и не создан"),

    ("ответ не закрывает вопрос — экран возвращается", RELOC,
     "    if migstate.settled(anchor):\n        return None",
     "    if False:\n        return None",
     "экран больше не открывается"),

    ("исход оракула не читается — подходит любой PIN", ROUTES,
     '    if verdict["outcome"] != SRC_OK:',
     '    if False:',
     "и это именно экран"),

    ("форма открыта чужой странице", ROUTES,
     "    if not same_origin_post(request):",
     "    if False and not same_origin_post(request):",
     "чужой origin отвергнут"),

    ("свой корень подтверждает кто угодно", ROUTES,
     "        if (deny := require(request, PERM_SETTINGS)) is not None:\n"
     "            return deny",
     "        if False:\n            return deny",
     "«остаюсь» без входа ничего не записывает"),

    ("подтверждение объявляет копию НАЧАТОЙ", STATE,
     '    rec = {"schema": SCHEMA, "chosen": choice, "old": old, "new": new,',
     '    rec = {"schema": SCHEMA, "chosen": choice, "authoritative": choice,\n'
     '           "old": old, "new": new,',
     "копия не объявлена начатой"),

    ("страница молчит о том, чего не показывает", ROUTES,
     "Numărul de pacienți nu este",
     "Numarul de pacienti tacut nu este",
     "страница объясняет, почему числа записей нет"),

    # ⛔ Дыра подделки: вердикт едет переменной окружения, а `dental.env`
    # правит клиника. Обе половины правила — и постановка, и снятие — обязаны
    # краснеть по отдельности.
    ("вердикт только ставится, но не снимается", DESK,
     "    os.environ.pop(relocate.SPLIT_ENV, None)",
     "    pass",
     "и СНИМАЕТСЯ во всех прочих ветках", "лаунчер"),
    ("вердикта приложению нет вовсе", DESK,
     '    os.environ[relocate.SPLIT_ENV] = str(_verdict["source"]["root"])',
     "    pass",
     "вердикт объявляется приложению", "лаунчер"),
    # ⛔ И самое неочевидное: обе правки НА МЕСТЕ, но ниже слияния — то есть
    # ровно та дыра, ради которой правило и написано. Правка двойная: унести
    # строку с её места и положить после слияния.
    ("вердикт объявляется ПОСЛЕ слияния dental.env", DESK,
     [('    os.environ[relocate.SPLIT_ENV] = str(_verdict["source"]["root"])',
       "    pass"),
      (MERGE, MERGE + "\n"
       'os.environ[relocate.SPLIT_ENV] = str(_verdict["source"]["root"])')],
     None,
     "обе правки ВЫШЕ слияния", "лаунчер"),
]


def _run(flt: str = "P2") -> tuple[int, str]:
    r = subprocess.run([str(PY), str(RUN), flt],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(APP))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    files = sorted({b[1] for b in BREAKS})
    orig = {rel: (APP / rel).read_text(encoding="utf-8") for rel in files}
    bad = 0
    try:
        for name, rel, old, new, want, *rest in BREAKS:
            flt = rest[0] if rest else "P2"
            src = orig[rel]
            # ⚠️ Поломка бывает и ДВОЙНОЙ: «строка на месте, но не там» иначе
            # одной заменой не изобразить, а именно она и есть дыра подделки.
            edits = old if isinstance(old, list) else [(old, new)]
            miss = [o for o, _w in edits if src.count(o) != 1]
            if miss:
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
            for ln in red[:3]:
                print("        " + ln)
    finally:
        for rel, text in orig.items():
            (APP / rel).write_text(text, encoding="utf-8")
        print("\n  файлы возвращены из копии")

    code, out = _run()
    lcode, lout = _run("лаунчер")
    code = code or lcode
    out += lout
    tail = [ln for ln in out.splitlines() if "прошло" in ln]
    print(f"  контрольный прогон на исправном: "
          f"{'зелёный' if code == 0 else 'КРАСНЫЙ'} — {' · '.join(tail)}")
    if bad or code:
        print(f"\n  неисправных сторожей: {bad}")
        return 1
    print("\n  все утверждения краснеют на сломанном коде")
    return 0


if __name__ == "__main__":
    sys.exit(main())
