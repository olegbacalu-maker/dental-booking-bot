# -*- coding: utf-8 -*-
"""Аудит parity: что ДОКАЗАНО по каждому React-экрану — фактами из дерева.

    python scripts/parity_audit.py            таблица для человека
    python scripts/parity_audit.py --json     машине (список берёт сцена)

Четыре уровня доказательства, и они отвечают на РАЗНЫЕ вопросы:

| Уровень | Что доказывает | Чего НЕ доказывает |
|---|---|---|
| серверные наборы | маршрут отвечает и данные верны | что экран нарисовался |
| ветка флага | сервер отдаёт ту поверхность, что просили | что бандл выполнился |
| тест клиента | правило экрана на jsdom | что экран смонтировался в браузере |
| живой монтаж | экран открылся у человека — `mount_sweep.py`, все 23 | что он делает дальше |
| сцена поведения | что экран УМЕЕТ в браузере | экраны, у которых уметь нечего |

⭐ Смысл таблицы в последней колонке. Первые три зелены и у экрана, который в
настоящем браузере не смонтировался вовсе: узел React пуст, а серверная
заглушка внутри него читается как обычный текст страницы. Прайор проекта
назван опытом 21.09 — «видно только живым запуском».

⛔ Список экранов НЕ ведётся здесь руками: он собирается из `REACT_SCREENS`
разбором `layout.py`, адреса — из `FLAG` генератора карты. Рукописный список
разошёлся бы с кодом молча, и аудит объявил бы полным то, чего не видел (ровно
это уже случилось с картой экранов 21.09).
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import screen_map  # noqa: E402


def react_screens() -> set[str]:
    """Имена экранов из `layout.REACT_SCREENS` — разбором, без импорта
    приложения: у него в этот момент нет ни конфига, ни базы."""
    tree = ast.parse((ROOT / "bot" / "app" / "core" / "layout.py")
                     .read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "REACT_SCREENS"
                        for t in n.targets)):
            return {c.value for c in ast.walk(n.value)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return set()


def components() -> dict:
    """Экран → компонент, из `App.tsx`: он и есть реестр поверхностей."""
    src = (ROOT / "frontend" / "src" / "app" / "App.tsx").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"screen === '([a-z_]+)'", src):
        c = re.search(r"<(\w+Screen)", src[m.end():m.end() + 260])
        if c:
            out[m.group(1)] = c.group(1)
    return out


def _scene_urls(src: str) -> list[str]:
    """Адреса, по которым сцена реально ХОДИТ.

    ⛔ Подстрокой сравнивать нельзя, и ошибается она в ОБЕ стороны: `/admin`
    встречается в каждом файле сцен, поэтому панель набирала пять чужих сцен;
    а `/admin/patient/{pid}/parodontograma` не встречается нигде дословно —
    адрес собирается f-строкой, — и экран с живой сценой показывался без неё.
    Ложная дыра дороже пропущенной: инструмент, кричащий на ровном месте,
    перестают читать целиком.

    Берём литералы и f-строки, начинающиеся с `/admin`; у f-строки заполнитель
    заменяем на `{}` — дальше его сопоставит шаблон маршрута.
    """
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if n.value.startswith("/admin"):
                out.append(n.value)
        elif isinstance(n, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}"
                           for v in n.values)
            if text.startswith("/admin"):
                out.append(text)
    return out


def _matches(route: str, urls: list[str]) -> bool:
    """Шаблон маршрута против адресов сцены: `{pid}` — это один сегмент."""
    pat = re.compile("^" + re.sub(r"\\{[^}]*\\}", "[^/]+",
                                  re.escape(route)) + "$")
    return any(pat.match(u.split("?")[0]) for u in urls)


def audit() -> list[dict]:
    path_of = {flag: path for path, flag in screen_map.FLAG.items()}
    rs, unresolved = screen_map.routes()
    screen_map.link(rs)
    suites_of: dict[str, set] = {}
    for r in rs:
        if r["method"] == "GET":
            suites_of.setdefault(r["path"], set()).update(r["suites"])

    tests = {f.name: f.read_text(encoding="utf-8", errors="replace")
             for f in (ROOT / "tests").glob("test_*.py")}
    shots = {f.name: _scene_urls(f.read_text(encoding="utf-8", errors="replace"))
             for f in (ROOT / "scripts").glob("*_shots.py")}
    comp_of = components()
    client = {f.name.replace(".test.tsx", "")
              for f in (ROOT / "frontend" / "src").rglob("*.test.tsx")}

    out = []
    for s in sorted(react_screens()):
        path = path_of.get(s, "")
        comp = comp_of.get(s, "")
        out.append({
            "screen": s,
            "path": path,
            "server_suites": sorted(suites_of.get(path, set())),
            # Ветка флага пишется набором, который НАЗЫВАЕТ имя экрана:
            # так устроены все `suite_switch`.
            "flag_suites": sorted(n[5:-3] for n, t in tests.items()
                                  if f'"{s}"' in t or f"'{s}'" in t),
            "component": comp,
            "client_test": bool(comp) and comp in client,
            "scenes": sorted(n[:-9] for n, urls in shots.items()
                             if path and _matches(path, urls)),
            "unresolved_routes": unresolved,
        })
    return out


def holes(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        h = []
        if not r["path"]:
            h.append("адреса нет в FLAG генератора карты")
        if not r["server_suites"]:
            h.append("серверных наборов на маршруте НЕТ")
        if not r["flag_suites"]:
            h.append("ветка флага не проверяется")
        if not r["component"]:
            h.append("экран не зарегистрирован в App.tsx")
        elif not r["client_test"]:
            h.append(f"нет теста клиента у {r['component']}")
        if not r["scenes"]:
            # ⚠️ Формулировка точная намеренно. МОНТАЖ у всех закрыт проходом
            # `mount_sweep.py` — он берёт список отсюда же и открывает каждый
            # экран в настоящем браузере. Здесь речь о сцене ПОВЕДЕНИЯ, и
            # писать «живого ничего нет» было бы ложной дырой: инструмент,
            # кричащий на ровном месте, перестают читать целиком.
            h.append("поведенческой сцены нет (монтаж — mount_sweep.py)")
        if h:
            out.append(f"{r['screen']}: " + "; ".join(h))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = audit()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    lvl = {k: sum(1 for r in rows if r[k]) for k in
           ("server_suites", "flag_suites", "client_test", "scenes")}
    n = len(rows)
    print(f"React-экранов: {n}\n")
    print("| Экран | Адрес | Сервер | Флаг | Клиент | Сцена |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(f"| `{r['screen']}` | `{r['path'] or '—'}` | "
              f"{len(r['server_suites'])} | {len(r['flag_suites'])} | "
              f"{'да' if r['client_test'] else '⛔ НЕТ'} | "
              f"{', '.join(r['scenes']) or '—'} |")
    print(f"\nСервер {lvl['server_suites']}/{n} · флаг {lvl['flag_suites']}/{n} · "
          f"клиент {lvl['client_test']}/{n} · живая сцена {lvl['scenes']}/{n}")
    # ⚠️ Отсутствие сцены названо дырой намеренно, хотя первые три колонки
    # зелены: это ровно тот остаток риска, который другие уровни закрыть не
    # могут — они читают исходник, а дефект живёт в результате.
    bad = holes(rows)
    print("\n## Дыры" if bad else "\nДыр нет.")
    for line in bad:
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
