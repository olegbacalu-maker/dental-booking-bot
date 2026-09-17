"""Карта экранов: маршрут → наборы тестов, которые его сторожат.

  python scripts/screen_map.py            пересобрать docs/dentpilot-2/screen-test-map.md
  python scripts/screen_map.py --check    только проверить, что файл свежий

Зачем: правило перехода на React — «экран не считается перенесённым, пока его
проверки не переписаны». Исполнить это нечем, если неизвестно, какие наборы
падают при переносе конкретного экрана. Таблица и есть тот критерий.

⚠️ Файл docs/dentpilot-2/screen-test-map.md ПРОИЗВОДНЫЙ. Правится генератор,
а не он: правка руками потеряется при первой же пересборке.

Зависимостей нет намеренно — только стандартная библиотека, как и у tests/.
"""
from __future__ import annotations

import ast
import collections
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # консоль бывает cp1251

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOT = ROOT / "bot" / "app"
TESTS = ROOT / "tests"
DOC = ROOT / "docs" / "dentpilot-2" / "screen-test-map.md"

HTTP = ("get", "post", "put", "delete", "patch")
# Адрес закончился: кавычка, знак запроса, решётка или пробел. Нужно, чтобы
# "/admin" не ловился внутри "/admin/week".
END = r'(?:["\'?#]|\s)'


def routes() -> list[dict]:
    """Все маршруты приложения разбором ast — не грепом: декоратор бывает
    многострочным, а имя обработчика нужно вместе с телом."""
    out = []
    for f in sorted(BOT.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in HTTP
                        and dec.args
                        and isinstance(dec.args[0], ast.Constant)):
                    continue
                body = ast.get_source_segment(src, node) or ""
                kw = {k.arg: k.value for k in dec.keywords}
                rc = kw.get("response_class")
                rc = rc.id if isinstance(rc, ast.Name) else None
                out.append({
                    "method": dec.func.attr.upper(),
                    "path": dec.args[0].value,
                    "file": str(f.relative_to(ROOT)).replace("\\", "/"),
                    "line": node.lineno,
                    "kind": _kind(body, rc),
                    "loc": len(body.splitlines()),
                })
    return out


def _kind(body: str, rc: str | None) -> str:
    if rc == "HTMLResponse" or "HTMLResponse" in body:
        return "HTML"
    if any(k in body for k in ("JSONResponse", "msg_json", "_reply(")):
        return "JSON"
    if "FileResponse" in body or "attachment" in body:
        return "FILE"
    if "status_code=303" in body or "RedirectResponse" in body:
        return "303"
    return "other"


def _patterns(path: str) -> list[re.Pattern]:
    """Адрес в тесте бывает литералом и бывает f-строкой, поэтому кандидатов
    три, и совпадения ЛЮБОГО достаточно:

      1. весь путь с границей справа — литерал `c.get("/admin/week")`;
      2. хвост после последнего `{…}` — `f"{base}/perio/new"`, где голова
         лежит в переменной и дословно в исходнике не встречается;
      3. голова до первого `{…}` — путь КОНЧАЕТСЯ плейсхолдером
         (`f"/admin/visit/{aid}"`), хвоста нет вовсе.

    ⚠️ Без третьего случая test_visit.py с его 46 проверками выглядел бы
    отсутствующим, а маршрут визита — непокрытым.
    """
    pats = []
    if "{" not in path:
        pats.append(re.escape(path) + END)
    else:
        tail = path.rsplit("}", 1)[1]
        if tail.strip("/"):
            pats.append(re.escape("/" + tail.lstrip("/")) + END)
        head = path.split("{")[0]
        if len(head) > 3:
            pats.append(re.escape(head))
    return [re.compile(p) for p in pats] or [re.compile(re.escape(path))]


def link(rs: list[dict]) -> dict[str, int]:
    src = {f.name: f.read_text(encoding="utf-8", errors="replace")
           for f in sorted(TESTS.glob("test_*.py"))}
    checks = {n: len(re.findall(r"res\.(?:ok|check)\(", s)) for n, s in src.items()}
    for r in rs:
        pats = _patterns(r["path"])
        r["suites"] = sorted(n for n, s in src.items()
                             if any(p.search(s) for p in pats))
        r["suite_checks"] = sum(checks[n] for n in r["suites"])
    return checks


MODULES = [("main.py", "Точка входа"), ("schedule", "Журнал"),
           ("patients", "Пациенты"), ("doctors", "Врачи"),
           ("settings", "Настройки"), ("stats", "Статистика"), ("qr", "QR")]
# Группы переноса — §32 спецификации DentPilot 2.0. 0 = не мигрирует.
GROUP = {"Настройки": 1, "Врачи": 1, "Статистика": 1, "QR": 1,
         "Пациенты": 2, "Журнал": 5, "Точка входа": 0, "Прочее": 0}

NOTE = {
    "/admin/update/run": "**самообновление** — спусковой крючок не проверен ничем",
    "/admin/update/check": "проверка обновлений",
    "/admin/settings/crypt": "⚠️ действия (`prepare`/`sheet`/`confirm`) проверены, "
                             "САМА СТРАНИЦА не открывается ни разу",
    "/admin/logout": "выход из журнала",
    "/admin/relink": "перепривязка врача",
    "/admin/settings/crypt/off": "выключение шифрования картотеки",
    "/admin/telegram/save": "сохранение токена бота (заморожен, но маршрут жив)",
    "/admin/lan/firewall": "правило брандмауэра, ⚠️ зовёт netsh через runas",
    "/admin/doctor-photo/{dk}": "отдача фото врача",
    "/admin/medici/add": "добавление врача",
    "/admin/medici/colors": "цвета врачей",
    "/admin/settings/backup": "страница бэкапа (экспорт проверен отдельно)",
    "/qr": "печатная страница QR",
}


# Рубильники React-экранов (DentPilot 2.0): имя флага в
# clinic.json["ui"]["react"] и состояние у пилота — off / on / откат.
# Заполняется ЗДЕСЬ при включении экрана; колонки таблицы производны от него.
FLAG = {"/admin/settings/clinic": "settings_clinic",
        "/admin/medici": "doctors_list",
        "/admin/doctor-card/{dk}": "doctor_card",
        "/admin/settings": "settings_hub",
        "/admin/settings/lan": "settings_lan",
        "/admin/settings/faq": "settings_faq",
        "/admin/settings/hours": "settings_hours",
        "/admin/settings/services": "settings_services",
        "/admin/settings/theme": "settings_theme"}
PILOT = {path: "off" for path in FLAG}


def _module(path_: str) -> str:
    for key, name in MODULES:
        if key in path_:
            return name
    return "Прочее"


def render(rs: list[dict], checks: dict[str, int]) -> str:
    by = collections.defaultdict(list)
    for r in rs:
        by[_module(r["file"])].append(r)

    L = ["# Карта экранов DentPilot 2.0\n",
         "Сгенерировано разбором исходников (`ast` + сопоставление адресов с текстом\n"
         "наборов). ⚠️ Файл **производный**: правится не он, а генератор.\n"
         "Пересобрать — `python scripts/screen_map.py`.\n",
         f"\nМаршрутов **{len(rs)}** · наборов **{len(checks)}** · мест вызова "
         f"`res.ok`/`res.check` в исходниках — **{sum(checks.values())}**.\n",
         "\n⚠️ Это статические МЕСТА ВЫЗОВА, а живой прогон даёт больше: часть\n"
         "вызовов стоит в циклах. Делить одно на другое нельзя — сколько проверок\n"
         "на самом деле, говорит сам прогон (`.\\dev test`).\n",
         "\n## Маршруты без единой проверки\n",
         "\n| Маршрут | Тип | стр | Замечание |\n|---|---|---|---|"]

    for r in sorted((r for r in rs if not r["suites"]), key=lambda r: r["path"]):
        L.append(f"| `{r['method']} {r['path']}` | {r['kind']} | {r['loc']} | "
                 f"{NOTE.get(r['path'], '—')} |")

    L.append("\n⭐ Находка **не про миграцию**: дыры есть уже сейчас. "
             "`POST /admin/update/run` запускает подмену exe у клиники "
             "и не покрыт ничем.\n")

    for name in ("Настройки", "Врачи", "Статистика", "QR",
                 "Пациенты", "Журнал", "Точка входа", "Прочее"):
        items = by.get(name)
        if not items:
            continue
        g = GROUP.get(name, 0)
        L.append(f"\n## {name} — группа {g}\n" if g
                 else f"\n## {name} — не мигрирует\n")
        if not g:
            L.append("\n⛔ Аварийные и служебные маршруты: остаются серверными (§27).\n")
        L.append("\n| Маршрут | Тип | стр | Наборы | Проверок | Флаг | Пилот |"
                 "\n|---|---|---|---|---|---|---|")
        for r in sorted(items, key=lambda r: (r["path"], r["method"])):
            suites = ", ".join(x[5:-3] for x in r["suites"]) or "**—**"
            L.append(f"| `{r['method']} {r['path']}` | {r['kind']} | {r['loc']} | "
                     f"{suites} | {r['suite_checks'] or '—'} | "
                     f"{FLAG.get(r['path'], '—')} | {PILOT.get(r['path'], '—')} |")

    L += ["\n## Колонки-состояния\n",
          "\n`Флаг` — имя экрана в `clinic.json` → `ui.react` (включает "
          "React-экран; `?ui=legacy` возвращает старый на один запрос).\n"
          "`Пилот` — `off` / `on` / `откат`. `—` значит «ещё не начат».\n",
          "\n## Самые тяжёлые обработчики\n",
          "\n| стр | Маршрут | Наборов |\n|---|---|---|"]
    for r in sorted(rs, key=lambda r: -r["loc"])[:10]:
        L.append(f"| {r['loc']} | `{r['method']} {r['path']}` | {len(r['suites'])} |")
    L.append("\n⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует "
             "разделить его логически; арифметика внутри сегодня проверяется только "
             "через готовую страницу.\n")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    rs = routes()
    checks = link(rs)
    text = render(rs, checks)
    if "--check" in argv:
        old = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if old == text:
            print(f"карта экранов свежая ({len(rs)} маршрутов)")
            return 0
        print("карта экранов устарела — пересобрать: python scripts/screen_map.py")
        return 1
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(text, encoding="utf-8")
    uncovered = sum(1 for r in rs if not r["suites"])
    print(f"{DOC.relative_to(ROOT)}: маршрутов {len(rs)}, "
          f"без единой проверки {uncovered}")
    if "--json" in argv:
        print(json.dumps(rs, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
