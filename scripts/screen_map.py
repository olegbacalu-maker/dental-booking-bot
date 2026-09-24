"""Карта экранов: маршрут → наборы тестов, которые его сторожат.

  python scripts/screen_map.py            пересобрать docs/dentpilot-2/screen-test-map.md
  python scripts/screen_map.py --check    только проверить, что файл свежий

Зачем: правило перехода на React — «экран не считается перенесённым, пока его
проверки не переписаны». Исполнить это нечем, если неизвестно, какие наборы
падают при переносе конкретного экрана. Таблица и есть тот критерий.

⚠️ Файл docs/dentpilot-2/screen-test-map.md ПРОИЗВОДНЫЙ. Правится генератор,
а не он: правка руками потеряется при первой же пересборке. Так же производны
route-map.md и таблица маршрутов клиента frontend/src/app/routes.ts (B2).

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
ROUTE_DOC = ROOT / "docs" / "dentpilot-2" / "route-map.md"
ROUTES_TS = ROOT / "frontend" / "src" / "app" / "routes.ts"

HTTP = ("get", "post", "put", "delete", "patch")
# Адрес закончился: кавычка, знак запроса, решётка или пробел. Нужно, чтобы
# "/admin" не ловился внутри "/admin/week".
END = r'(?:["\'?#]|\s)'


def _consts(tree: ast.Module) -> dict:
    """Строковые константы уровня модуля: `PAGE = "/admin/migration"`.

    ⚠️ Нужны потому, что адрес маршрута не обязан быть литералом. Модуль,
    объявивший его константой, раньше пропадал из карты ЦЕЛИКОМ и молча — а
    карта при этом выглядела полной: то же число маршрутов, ни одной жалобы.
    Так из неё выпал экран раздвоения (21.09).
    """
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            out[node.targets[0].id] = node.value.value
    return out


def _route_path(node: ast.AST, consts: dict) -> str | None:
    """Адрес из аргумента декоратора, или None — если разобрать не смогли.

    ⛔ None обязан быть ГРОМКИМ у вызывающего. Тихий пропуск здесь и есть
    ошибка класса «правило нашло ноль нарушителей и позеленело».
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _route_path(node.left, consts)
        right = _route_path(node.right, consts)
        return None if left is None or right is None else left + right
    return None


def routes() -> tuple[list[dict], list[str]]:
    """Все маршруты приложения разбором ast — не грепом: декоратор бывает
    многострочным, а имя обработчика нужно вместе с телом.

    Возвращает `(маршруты, неразобранные)`. Второй список почти всегда пуст, и
    именно поэтому его нельзя выбрасывать: непустым он станет ровно тогда,
    когда карта начнёт врать.
    """
    out, unresolved = [], []
    for f in sorted(BOT.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        consts = _consts(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in HTTP
                        and dec.args):
                    continue
                rel = str(f.relative_to(ROOT)).replace("\\", "/")
                path_ = _route_path(dec.args[0], consts)
                if path_ is None:
                    unresolved.append(f"{rel}:{node.lineno} {node.name}")
                    continue
                body = ast.get_source_segment(src, node) or ""
                kw = {k.arg: k.value for k in dec.keywords}
                rc = kw.get("response_class")
                rc = rc.id if isinstance(rc, ast.Name) else None
                out.append({
                    "method": dec.func.attr.upper(),
                    "path": path_,
                    "file": rel,
                    "line": node.lineno,
                    "kind": _kind(body, rc),
                    "loc": len(body.splitlines()),
                })
    return out, unresolved


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
# ⚠️ Список ведётся РУКАМИ и тестом не покрыт: к 19.09 он отстал на пять
# имён (perio и все три экрана журнала), и карта экранов молча показывала
# «—» у переехавших. Правило простое: завёл имя в REACT_SCREENS — впиши
# сюда его адрес.
FLAG = {"/admin/settings/clinic": "settings_clinic",
        "/admin/medici": "doctors_list",
        "/admin/doctor-card/{dk}": "doctor_card",
        "/admin/settings": "settings_hub",
        "/admin/settings/lan": "settings_lan",
        "/admin/settings/faq": "settings_faq",
        "/admin/settings/hours": "settings_hours",
        "/admin/settings/services": "settings_services",
        "/admin/settings/theme": "settings_theme",
        "/admin/settings/security": "settings_security",
        "/admin/settings/backup": "settings_backup",
        "/admin/settings/crypt": "settings_crypt",
        "/admin/settings/system": "settings_system",
        "/admin/stats": "stats",
        "/admin/search": "patients_search",
        "/admin/patient/{pid}": "patient_card",
        "/admin/visit/{appt_id}": "visit",
        "/admin/patient/{pid}/odontograma": "odontogram",
        "/admin/patient/{pid}/parodontograma": "perio",
        "/admin/week": "schedule_week",
        "/admin/all": "schedule_all",
        "/admin/doctor/{dk}": "schedule_doctor",
        "/admin": "schedule_dash"}
# Что нужно маршруту сверх имени экрана: параметры узла и загрузчик (B2).
# ⭐ Лежит РЯДОМ с FLAG намеренно. Два словаря в разных файлах разъезжаются
# поодиночке; здесь пропуск виден глазом, а `test_guards` требует строку на
# КАЖДЫЙ ключ FLAG — список с включающей полярностью без этого гниёт молча.
# ⚠️ «?» у ключа значит «бывает и не быть»: сервер кладёт его только когда
# значение непустое (`params or None`).
# ⚠️ Загрузчик — то, что экран просит ПРИ МОНТИРОВАНИИ. В data-router это и
# станет `loader` маршрута; «—» значит, что просить нечего и данные уже в
# параметрах узла.
B2 = {
    "/admin": ("—", "GET /api/schedule/live",
               "живой КАНАЛ, а не разовая загрузка: 204 «не менялось», отпечаток; "
               "день — из АДРЕСА (пусто — сегодня сервера), шапка — эхо канала"),
    "/admin/week": ("date", "GET /api/schedule/week", ""),
    "/admin/all": ("date, f?", "GET /api/schedule/day", "экран DayScreen, общий с днём врача"),
    "/admin/doctor/{dk}": ("date, dk", "GET /api/schedule/day", "тот же DayScreen, отличается dk"),
    "/admin/search": ("q?, med?, st?, ch?, dat?, sort?, page?, per?",
                      "GET /api/patients/summary + GET /api/patients",
                      "ДВА запроса разом (Promise.all) — loader обязан ждать оба"),
    "/admin/patient/{pid}": ("pid, views?", "GET /api/patients/{pid}", ""),
    "/admin/visit/{appt_id}": ("aid, back", "GET /api/visits/{aid}",
                               "⚠️ ключ узла `aid`, а параметр пути `appt_id` — имена РАЗНЫЕ"),
    "/admin/patient/{pid}/odontograma": ("pid, t?", "GET /api/patients/{pid}/odontogram", ""),
    "/admin/patient/{pid}/parodontograma": ("pid, exam?", "GET /api/patients/{pid}/perio", ""),
    "/admin/medici": ("—", "GET /api/doctors", ""),
    "/admin/doctor-card/{dk}": ("dk", "GET /api/doctors/{dk}",
                                "⛔ НЕ путать с /admin/doctor/{dk} — это день врача в журнале"),
    "/admin/settings": ("—", "GET /api/settings/hub", ""),
    "/admin/settings/clinic": ("—", "GET /api/settings/clinic",
                               "⚠️ единственный экран НЕ на useLoad: свой useEffect"),
    "/admin/settings/lan": ("—", "GET /api/settings/lan", ""),
    "/admin/settings/faq": ("—", "GET /api/settings/faq", ""),
    "/admin/settings/hours": ("—", "GET /api/settings/hours", ""),
    "/admin/settings/services": ("—", "GET /api/settings/services", ""),
    "/admin/settings/theme": ("—", "GET /api/settings/theme", ""),
    "/admin/settings/security": ("—", "GET /api/settings/security", ""),
    "/admin/settings/backup": ("—", "GET /api/settings/backup", ""),
    "/admin/settings/crypt": ("—", "GET /api/settings/crypt", ""),
    "/admin/settings/system": ("—", "GET /api/settings/system", ""),
    "/admin/stats": ("from, to", "GET /api/stats", ""),
}


def react_path(path_: str) -> str:
    """Адрес FastAPI как маршрут React: `{pid}` → `:pid`, остальное БЕЗ правок.

    ⛔ Новых адресов не заводим. `/dashboard`, `/pacienti` и прочее на сервере
    не существует, и перезагрузка такой страницы дала бы 404 — правило решения
    B: бэкенд не переписывается ради роутера.
    """
    return re.sub(r"\{([a-z_]+)\}", lambda m: ":" + m.group(1), path_)


# ⛔ Колонка «Пилот» убрана 21.09 вместе с самим выкатом: живых профилей нет,
# сохранять нечего, и React стал поверхностью продукта по умолчанию. FLAG
# остался как «где у экрана есть React-имя», а не как рубильник включения.


def _module(path_: str) -> str:
    for key, name in MODULES:
        if key in path_:
            return name
    return "Прочее"


def render(rs: list[dict], checks: dict[str, int],
           unresolved: list[str] | None = None) -> str:
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
         "\n⛔ Адресов, которые сборщик не смог разобрать: "
         f"**{len(unresolved or [])}**"
         + (" — " + ", ".join(unresolved) if unresolved else
            " — маршрут, объявленный через константу, раньше выпадал из карты\n"
            "ЦЕЛИКОМ и молча: число маршрутов не менялось, жалобы не было.")
         + "\n",
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
        L.append("\n| Маршрут | Тип | стр | Наборы | Проверок | Экран React |"
                 "\n|---|---|---|---|---|---|")
        for r in sorted(items, key=lambda r: (r["path"], r["method"])):
            suites = ", ".join(x[5:-3] for x in r["suites"]) or "**—**"
            L.append(f"| `{r['method']} {r['path']}` | {r['kind']} | {r['loc']} | "
                     f"{suites} | {r['suite_checks'] or '—'} | "
                     f"{FLAG.get(r['path'], '—')} |")

    L += ["\n## Колонки-состояния\n",
          "\n`Экран React` — имя РЕАЛИЗОВАННОЙ поверхности. С 21.09 она "
          "отдаётся ПО УМОЛЧАНИЮ: `ui.react` в профиле стал аварийным "
          "выключателем, а не рубильником выката (`?ui=legacy` по-прежнему "
          "возвращает старую страницу на один запрос). `—` значит «страница "
          "серверная по замыслу» — печать и аварийные экраны.\n",
          "\n## Самые тяжёлые обработчики\n",
          "\n| стр | Маршрут | Наборов |\n|---|---|---|"]
    for r in sorted(rs, key=lambda r: -r["loc"])[:10]:
        L.append(f"| {r['loc']} | `{r['method']} {r['path']}` | {len(r['suites'])} |")
    L.append("\n⛔ `GET /admin/patient/{pid}` — 909 строк одной функцией. §18 требует "
             "разделить его логически; арифметика внутри сегодня проверяется только "
             "через готовую страницу.\n")
    return "\n".join(L)


def render_routes() -> str:
    """Карта маршрутов B2: адрес FastAPI → маршрут React → экран → параметры → загрузчик.

    ⛔ Новых адресов НЕТ и быть не может: маршрут React — тот же путь, только
    `{pid}` записан как `:pid`. Это и есть правило решения B, записанное кодом,
    а не обещанием: колонка вычисляется из адреса сервера, а не набирается.
    """
    rows = sorted(FLAG.items(), key=lambda kv: (kv[0].count("/"), kv[0]))
    L = ["# Карта маршрутов B2\n",
         "Адрес FastAPI → маршрут React → экран → параметры узла → загрузчик.\n",
         "\n⚠️ Файл **производный**: правится не он, а `scripts/screen_map.py`\n"
         "(словари `FLAG` и `B2` лежат там рядом). Пересобрать —\n"
         "`python scripts/screen_map.py`.\n",
         "\n⛔ Колонка «маршрут React» ВЫЧИСЛЯЕТСЯ из адреса сервера, а не\n"
         "набирается: новых адресов вроде `/dashboard` или `/pacienti` на сервере\n"
         "нет, и перезагрузка такой страницы дала бы 404. Бэкенд не переписывается\n"
         "ради роутера.\n",
         f"\nПоверхностей **{len(rows)}**.\n",
         "\n| адрес FastAPI | маршрут React | экран | параметры узла | загрузчик |",
         "|---|---|---|---|---|"]
    notes = []
    for path_, screen in rows:
        params, loader, note = B2.get(path_, ("?", "?", ""))
        L.append(f"| `{path_}` | `{react_path(path_)}` | `{screen}` | {params} | {loader} |")
        if note:
            notes.append(f"- `{path_}` — {note}")
    if notes:
        L += ["\n## Что нельзя потерять при переносе\n"] + notes
    L += ["\n## Чего в этой карте намеренно нет\n",
          "Крошка раздела (`frame.crumbs`) — она в модели ОБОЛОЧКИ, а не в\n"
          "параметрах экрана, и одна на все десять страниц настроек. В\n"
          "конфигурацию маршрута её тянуть незачем: она уже приезжает готовой.\n",
          "\nПрава. Страница зовёт `require(PERM_…)`, её загрузчик — `api_require`.\n"
          "Свести их в одно место — это B3, и до выбора режима роутера трогать\n"
          "нечего. ⚠️ Расхождение прав между страницей и её загрузчиком обязано\n"
          "быть проверено ДО B3, иначе проверка переедет в загрузчик вместе с\n"
          "ошибкой.\n",
          "\n---\nСвязано: [spa-transition.md](spa-transition.md),\n"
          "[screen-test-map.md](screen-test-map.md).\n"]
    return "\n".join(L)


def render_routes_ts() -> str:
    """Таблица маршрутов клиента (B2) — ИЗ FLAG, тем же приёмом, что icons.ts.

    ⛔ Рукописная таблица в клиенте была бы второй картой адресов рядом с
    серверной, и разошлись бы они молча: перезагрузка на адресе, которого
    клиент не знает, показывает «такого экрана нет», а не ошибку сборки.
    Свежесть держит `test_guards.suite_route_map`.
    """
    rows = sorted(FLAG.items(), key=lambda kv: (kv[0].count("/"), kv[0]))
    L = ["// Сгенерировано scripts/screen_map.py из словаря FLAG.",
         "// НЕ ПРАВИТЬ РУКАМИ: правится FLAG, потом `python scripts/screen_map.py`.",
         "// Маршрут — адрес FastAPI, где `{pid}` записан как `:pid`. Новых адресов нет:",
         "// перезагрузка на адресе, которого не знает сервер, дала бы 404.",
         "export const ROUTES = ["]
    for path_, screen in rows:
        L.append(f"  {{ path: {json.dumps(react_path(path_))}, "
                 f"screen: {json.dumps(screen)} }},")
    L += ["] as const", "",
          "export type ScreenName = (typeof ROUTES)[number]['screen']", ""]
    return "\n".join(L)


def main(argv: list[str]) -> int:
    rs, unresolved = routes()
    checks = link(rs)
    text = render(rs, checks, unresolved)
    rtext = render_routes()
    ts = render_routes_ts()
    if "--check" in argv:
        old = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        rold = ROUTE_DOC.read_text(encoding="utf-8") if ROUTE_DOC.exists() else ""
        tsold = ROUTES_TS.read_text(encoding="utf-8") if ROUTES_TS.exists() else ""
        if old == text and rold == rtext and tsold == ts:
            print(f"карты свежие ({len(rs)} маршрутов, {len(FLAG)} поверхностей)")
            return 0
        stale = ", ".join(n for n, ok in (("экранов", old == text),
                                         ("маршрутов", rold == rtext),
                                         ("routes.ts", tsold == ts)) if not ok)
        print(f"устарело: {stale} — пересобрать: python scripts/screen_map.py")
        return 1
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(text, encoding="utf-8")
    ROUTE_DOC.write_text(rtext, encoding="utf-8")
    ROUTES_TS.write_text(ts, encoding="utf-8", newline="\n")  # LF, как icons.ts
    print(f"{ROUTE_DOC.relative_to(ROOT)}: поверхностей {len(FLAG)}")
    print(f"{ROUTES_TS.relative_to(ROOT)}: маршрутов клиента {len(FLAG)}")
    uncovered = sum(1 for r in rs if not r["suites"])
    print(f"{DOC.relative_to(ROOT)}: маршрутов {len(rs)}, "
          f"без единой проверки {uncovered}")
    if unresolved:
        # ⛔ ВСЛУХ: недосчитанный маршрут делает карту ЛОЖНО ПОЛНОЙ, а это
        # хуже пустой — по ней принимают решение о готовности.
        print(f"⛔ адрес не разобран у {len(unresolved)} маршрутов — карта "
              f"НЕДОСЧИТЫВАЕТ: {', '.join(unresolved)}")
    if "--json" in argv:
        print(json.dumps(rs, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
