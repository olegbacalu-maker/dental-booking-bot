"""Имена `layout` — те же, что до разноса (04.11.2026).

`bot/app/core/layout.py` на две тысячи строк разнесён по соседям БЕЗ правок у
вызывающих: `from ...core.layout import X` обязано значить ровно то же, что
значило. Каждый вопрос ниже ломается молча:

- имя пропало из реэкспорта — `ImportError` у модуля, а отложенный импорт (`db`,
  `auth`, `orders`, `backup_loop`) падает только на той ветке, что его зовёт;
- реэкспорт смотрит не на тот объект, что у соседа-владельца;
- сосед импортирует layout, и круг проявляется ТОЛЬКО при определённом порядке
  импорта: поэтому каждый модуль здесь импортируется ПЕРВЫМ на чистом процессе;
- подмена `layout.X = …` до соседей не доходит: они зовут друг друга по именам;
- сосед, куда не дотянулись часы харнесса, жил бы по настоящему времени, и набор
  под `harness.Clock` проверял бы не тот день — зелёным.

`SNAPSHOT` — имена, которые снаружи берут через layout (замер на `7542c49`, разбор
ast по `bot/ tests/ scripts/ demo/`); совпадает с `layout.__all__`. Прочие имена
бывшего layout снаружи не брал никто, и реэкспорта у них нет намеренно.
⛔ `MSG_BANNER` среди них нет и не будет: читать словарь вне `messages` запрещает
`test_structure`. Новое имя снаружи — строка здесь и в `__all__`.
"""
import ast
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from harness import BOT, ROOT, Result

CORE = BOT / "app" / "core"
# Снизу вверх: порядок импорта. Каждый берёт имена только у тех, кто левее.
BELOW = ("icons", "messages", "labels", "pages", "banners", "license_pages")
FILES = (*BELOW, "layout")
# Единственное имя, которому два присваивания положены (оба при импорте,
# подстановка значка в шаблон); новое такое имя — сперва решение, потом строка здесь.
REBOUND_OK = {("license_pages", "LICENSE_TMPL")}

SNAPSHOT = frozenset((
    "_age", "ALERT_KINDS", "_asset", "data_folder", "dmy", "_doc_hours_text",
    "_DOC_STATE_RO", "_DOW_FULL", "_DOW_ORDER", "FEEDBACK_EMAIL", "fonts_css",
    "HOUR_MAX", "HOUR_MIN", "_ic", "_initials", "license_cont_page", "license_page",
    "license_pay_page", "LIVE_STATUSES", "msg_json", "msg_state", "msg_text",
    "msg_view", "react_shell", "SECTION_TITLE", "SETUP_HINT", "shell_model",
    "SOURCE_LABEL", "standalone", "STATIC", "STATUS_LABEL", "status_view",
    "SUPPORT_PHONE",
))

# Подмена имени layout из тестов и скриптов — и в коде строк для `python -c`,
# поэтому текстом, а не деревом.
_ASSIGN = re.compile(r"\blayout\.(\w+)\s*[-+]?=(?!=)")
_SETATTR = re.compile(r"\b(?:set|del)attr\(\s*layout\b")
_GUARDS = {"test_layout_names.py", "test_structure.py", "mutate.py"}

_OWNERS_CODE = """
import importlib, json, sys
from app.core import layout
names, subs = json.loads(sys.argv[1]), json.loads(sys.argv[2])
owner = {}
for sub in subs:
    mod = importlib.import_module('app.core.' + sub)
    for n in names:
        if n in vars(mod) and getattr(mod, '__name__', '') == 'app.core.' + sub:
            owner.setdefault(n, []).append(sub)
stale = []
for sub, ns in json.loads(sys.argv[3]).items():
    mod = importlib.import_module('app.core.' + sub)
    for n in ns:
        if n in vars(layout) and getattr(layout, n) is not getattr(mod, n):
            stale.append(sub + '.' + n)
print(json.dumps({'all': sorted(layout.__all__), 'missing': sorted(n for n in names if not hasattr(layout, n)),
                  'stale': stale, 'msg': hasattr(layout, 'MSG_BANNER')}))
"""

# Часы харнесса (`tests/fakeclock`) подменяют `datetime` в глобалах модулей `app.*`
# ПОСЛЕ исполнения тела: сосед, куда часы не дотянулись, жил бы по настоящему времени.
_CLOCK_CODE = """
import importlib, sys, datetime as real
for m in sys.argv[1:]:
    mod = importlib.import_module('app.core.' + m)
    if 'datetime' in vars(mod):
        print(m, mod.datetime.now(real.timezone.utc).isoformat())
from app.core import layout
print('_age', layout._age(1900))
"""

# Вход в систему снизу и сбоку: что импортируется первым у лаунчера, у `db` и у
# тех, кто берёт layout отложенно. Порядок и есть то, на чём проявляется круг.
_ENTRY = ("app.main", "app.db", "app.core.auth", "app.core.backup_loop", "app.core.orders",
          "app.modules.entry.pages", "app.core.api")


def _defined(path: pathlib.Path) -> list[str]:
    """Имена верхнего уровня файла — с повторами, если присвоено дважды."""
    out = []
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            out += [x.id for t in targets for x in ast.walk(t) if isinstance(x, ast.Name)]
    return out


def _env(**extra) -> dict:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", **extra}


def suite(res: Result) -> None:
    # Якорь: пустой обход сделал бы все проверки ниже зелёными разом.
    absent = [f for f in FILES if not (CORE / f"{f}.py").is_file()]
    res.ok("исходники layout и соседей нашлись", not absent, f"нет файлов: {absent} в {CORE}")
    if absent:
        return

    defined = {f: _defined(CORE / f"{f}.py") for f in FILES}
    owners: dict[str, list[str]] = {}
    for f, ns in defined.items():
        for n in set(ns) - {"__all__"}:
            owners.setdefault(n, []).append(f)
    twice = sorted(f"{n}: {', '.join(o)}" for n, o in owners.items() if len(o) > 1)
    res.ok("у имени layout один файл-владелец", not twice, "; ".join(twice))

    lost = sorted(SNAPSHOT - set(owners))
    res.ok("каждое имя снимка определено в layout или соседе", not lost,
           "имя пропало: " + ", ".join(lost))

    probe = subprocess.run(
        [sys.executable, "-c", _OWNERS_CODE, json.dumps(sorted(SNAPSHOT)), json.dumps(list(BELOW)),
         json.dumps({f: defined[f] for f in BELOW})],
        cwd=BOT, env=_env(), capture_output=True, text=True, encoding="utf-8", timeout=120)
    if not res.ok("снимок layout читается", probe.returncode == 0,
                  f"код {probe.returncode}: {probe.stderr[-400:]}"):
        return
    got = json.loads(probe.stdout.strip().splitlines()[-1])
    res.ok("каждое имя снимка есть в layout", not got["missing"],
           "пропали (ImportError у вызывающего): " + ", ".join(got["missing"]))
    res.check("__all__ у layout — это снимок", set(got["all"]), set(SNAPSHOT))
    res.ok("layout.X — тот же объект, что у соседа-владельца", not got["stale"],
           "реэкспорт смотрит не туда: " + ", ".join(got["stale"]))
    res.ok("MSG_BANNER через layout не торчит", not got["msg"],
           "словарь читают только его допущенные файлы (test_structure)")

    # Каждый модуль — первым на чистом процессе. Импорт соседа после `app.main`
    # ничего не доказывает: круг проявляется только при неудачном порядке.
    broken = []
    entries = [f"app.core.{f}" for f in FILES] + list(_ENTRY)
    for mod in entries:
        p = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=BOT, env=_env(),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if p.returncode:
            broken.append(f"{mod}: {p.stderr.strip().splitlines()[-1][:200] if p.stderr.strip() else p.returncode}")
    res.ok(f"импорт первым на чистом процессе: {len(entries)} входов", not broken, "; ".join(broken))

    # Отложенные импорты снизу — те самые, которых нельзя поднять на уровень модуля.
    lazy = subprocess.run(
        [sys.executable, "-c",
         "from app import db\n"
         "from app.core.layout import STATUS_LABEL\n"
         "from app.core import auth, backup_loop, orders\n"
         "from app.core import layout\n"
         "assert layout.msg_text('bkp_no_offsite'), 'нет текста'\n"
         "print(STATUS_LABEL['done'])"],
        cwd=BOT, env=_env(), capture_output=True, text=True, encoding="utf-8", timeout=120)
    res.ok("отложенный импорт снизу находит слова",
           lazy.returncode == 0 and "finalizat" in lazy.stdout, lazy.stderr[-300:])

    scanned, swapped = 0, []
    for top in ("tests", "scripts", "demo"):
        for f in sorted((ROOT / top).rglob("*.py")):
            if f.name in _GUARDS:
                continue
            scanned += 1
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if _ASSIGN.search(line) or _SETATTR.search(line):
                    swapped.append(f"{f.relative_to(ROOT).as_posix()}:{i}")
    res.ok("тесты и скрипты не подменяют имена layout", scanned > 50 and not swapped,
           f"просмотрено файлов {scanned}; подмена через layout до соседей не дойдёт — "
           "подменять у владельца: " + ", ".join(swapped))

    # ⛔ Изменяемое состояние модуля — через модуль: у этих файлов его нет. Новое
    # переприсваивание сделало бы `from .x import ИМЯ` у соседа молчаливой копией.
    rebound = sorted({(f, n) for f, ns in defined.items() for n in ns if ns.count(n) > 1} - REBOUND_OK)
    with_global = [f for f in FILES
                   for n in ast.walk(ast.parse((CORE / f"{f}.py").read_text(encoding="utf-8")))
                   if isinstance(n, ast.Global)]
    res.ok("у layout и соседей нет переприсваиваемого состояния", not rebound and not with_global,
           f"присвоено дважды: {rebound}; global: {with_global}")
    res.ok("прощённое присваивание ещё существует",
           all(defined[f].count(n) == 2 for f, n in REBOUND_OK), f"{REBOUND_OK}")

    shift = tempfile.NamedTemporaryFile("w", suffix=".shift", delete=False)
    shift.write(str(400 * 86400))                        # +400 суток
    shift.close()
    try:
        env = _env(PYTHONPATH=str(ROOT / "tests" / "fakeclock"), FAKECLOCK_FILE=shift.name)
        p = subprocess.run([sys.executable, "-c", _CLOCK_CODE, *FILES], cwd=BOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        pathlib.Path(shift.name).unlink(missing_ok=True)
    rows = dict(ln.split(" ", 1) for ln in p.stdout.splitlines()
                if ln and not ln.startswith("[fakeclock]"))
    age = rows.pop("_age", "")
    soon = datetime.now(timezone.utc) + timedelta(days=300)
    stuck = sorted(m for m, at in rows.items() if datetime.fromisoformat(at) < soon)
    now_age = datetime.now(timezone.utc).year - 1900
    res.ok("часы харнесса двигают layout и соседей",
           p.returncode == 0 and len(rows) >= 2 and not stuck and age.strip().isdigit()
           and int(age) >= now_age + 1,
           f"код {p.returncode}; соседи с datetime: {sorted(rows)}; мимо часов: {stuck}; "
           f"_age(1900) = {age!r}; {p.stderr[-300:]}")
