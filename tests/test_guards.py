"""Сторожа за сторожами — находки ревью 08-16 по кластеру `tests\\`.

`mutate.py` рядом отвечает на общий вопрос «краснеет ли каждое правило», и
отвечает честно: он ломает правило ровно там, где оно смотрит. Дефект этого
кластера другой — правило смотрит НЕ ВЕЗДЕ, где обязано, и мутация о таком
промахе сказать не может по устройству:

  * область правила о знаках кончалась на `modules/` и `core/`, а экраны живут
    и в `main.py` (вход, установка PIN, весь режим восстановления), тексты для
    человека — ещё и в `db.py` (летопись пациента);
  * требование обновить отпечаток auth.json включалось только вызовом голым
    именем, а модулем-объектом (`auth.save_user(...)`) в этом дереве ходят
    почти все — то есть сторож работал по совпадению стиля импорта;
  * `_ROLES` — список ВКЛЮЧАЮЩИЙ: четвёртая роль в PERMS выключила бы правило
    для себя молча.

Проверки устроены как в `mutate.py`: `bot\\` копируется во временную папку,
нарушение дописывается в КОПИЮ, `test_structure.BOT` перевешивается на неё.
Дописанный код никогда не исполняется — правила разбирают синтаксис.

Последний набор — про `scripts/check_release.py`: он не программа, а
единственная проверка между «нажал Publish» и «клиники качают обновление», и
его ложное «релиза нет» уводит чинить исправный релиз в веб-форму, где живут
все три задокументированные ловушки.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import pathlib
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_structure  # noqa: E402
from harness import BOT, ROOT, Result  # noqa: E402

# 🖨 — чистое эмодзи, рисует система. Живёт в исходнике \-последовательностью
# намеренно: сам этот файл правило не читает, но знак в нём сбивал бы с толку.
GLYPH = "\U0001f5a8"
# Знаки из блока математических операторов: U+2212 (минус) и U+2248
# («приблизительно»). Названы константами именно потому, что от дефиса и тильды
# их глазами не отличить, — иначе проверка ниже читалась бы как проверка ни о чём.
MINUS, APPROX = "−", "≈"


def _run(rel: str | None = None, patch=None) -> Result:
    """Прогнать `test_structure` по КОПИИ дерева с одной правкой.

    patch: строка — дописать в конец файла; пара («что было», «чем заменить») —
    заменить первое вхождение (нарушение, состоящее в изменении кода на месте).
    """
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_guard_"))
    try:
        bot = tmp / "bot"
        shutil.copytree(BOT, bot, ignore=shutil.ignore_patterns("__pycache__"))
        if rel:
            f = bot / rel
            text = f.read_text(encoding="utf-8")
            if isinstance(patch, tuple):
                was, now = patch
                if was not in text:
                    raise AssertionError(f"в {rel} нет {was!r} — проверка протухла")
                text = text.replace(was, now, 1)
            else:
                text += patch
            f.write_text(text, encoding="utf-8")
        test_structure.BOT = bot
        res = Result()
        test_structure.suite(res)
        return res
    finally:
        test_structure.BOT = BOT        # вернуть на настоящее дерево
        shutil.rmtree(tmp, ignore_errors=True)


_CLEAN: list[Result] = []


def _clean() -> Result:
    """Прогон по нетронутой копии — один на весь файл: копирование дерева
    стоит секунды, а ответ у всех наборов один и тот же."""
    if not _CLEAN:
        _CLEAN.append(_run())
    return _CLEAN[0]


def _red(res: Result, part: str) -> bool:
    return any(part in label for label, _ in res.failed)


def _why(res: Result, part: str) -> str:
    return "; ".join(why for label, why in res.failed if part in label)


def _seen(res: Result, part: str) -> bool:
    return any(part in label for label in res.passed) or _red(res, part)


def suite_glyph_scope(res: Result) -> None:
    """Правило «интерфейс не просит знаки у Windows» — по всему bot/."""
    clean = _clean()
    res.ok("живых знаков от Windows в дереве не осталось",
           not _red(clean, "знаки у Windows"),
           _why(clean, "знаки у Windows"))

    # main.py: экран восстановления (жил с ✅ во всех релизах), вход, установка
    # PIN. db.py: летопись пациента, её читает регистратура каждый день.
    for rel, what in (("app/main.py", "вход, установка PIN, восстановление"),
                      ("app/db.py", "тексты летописи пациента"),
                      ("app/update.py", "экран и лог обновления")):
        r = _run(rel, f'\n_MUT_GLYPH = "<h1>{GLYPH} Gata</h1>"\n')
        res.ok(f"знак в {rel} виден сторожу ({what})",
               _red(r, "знаки у Windows"),
               "правило не смотрит в этот файл — экран нарисует Windows")

    # Тексты бота остаются исключением: их рисует Telegram на телефоне
    # пациента. Если исключение однажды снимут, набор обязан сказать об этом.
    r = _run("app/engine.py", f'\n_MUT_TG = "{GLYPH} Programare"\n')
    res.ok("тексты бота по-прежнему исключены", not _red(r, "знаки у Windows"),
           "эмодзи в текстах Telegram стало нарушением — это не так")


def suite_glyph_math(res: Result) -> None:
    """Тот же сторож — на знаки, которые на эмодзи не похожи (08-16).

    Область правила расширили накануне, и оно прочесало весь `bot/`, — а «−»
    (U+2212) в летописи «Plan: − {procedure}» пережило и это: блока
    математических операторов в диапазонах не было. Класс риска ровно тот же,
    что у стрелки: во вшитый Inter знак не входит, значит рисует его Windows —
    своим шрифтом, своим цветом, по-разному на 10 и 11. Глазами такое не
    ловится вовсе: «−» от дефиса отличается только шириной.
    """
    for glyph, what in ((MINUS, "минус U+2212"), (APPROX, "≈ U+2248")):
        r = _run("app/db.py", f'\n_MUT_MATH = "Plan: {glyph} procedura"\n')
        res.ok(f"{what} в тексте виден сторожу", _red(r, "знаки у Windows"),
               "знак остался незамеченным — экран нарисует его системным "
               "шрифтом, а летопись уедет такой в выгрузку по 195-му")

    # Полярность: обычный дефис — законная замена, и правило обязано молчать.
    # Иначе «починка» знака гнала бы по кругу, а сторож краснел бы на текстах,
    # которых в дереве десятки.
    r = _run("app/db.py", '\n_MUT_DASH = "Plan: - procedura"\n')
    res.ok("обычный дефис нарушением не считается",
           not _red(r, "знаки у Windows"), _why(r, "знаки у Windows"))


def suite_auth_fp(res: Result) -> None:
    """Отпечаток auth.json обязателен независимо от ФОРМЫ вызова."""
    writer = ("\nasync def _mut(uid):\n"
              "    auth.save_user(uid, name='x', role='medic')\n")
    r = _run("app/modules/patients/routes.py", writer)
    res.ok("вызов через модуль включает требование отпечатка",
           _red(r, "отпечаток"),
           "auth.save_user(...) прошёл мимо сторожа — при следующем старте "
           "клиника получит ложный «взлом»")

    r = _run("app/modules/patients/routes.py",
             writer + "    await auth.remember_auth_file()\n")
    res.ok("а с remember_auth_file рядом — правило молчит",
           not _red(r, "отпечаток"), _why(r, "отпечаток"))

    # Голое имя ловилось и раньше — проверка держит обе формы разом.
    r = _run("app/modules/patients/routes.py",
             "\nasync def _mut2(uid):\n    save_user(uid, name='x', role='medic')\n")
    res.ok("голое имя ловится по-прежнему", _red(r, "отпечаток"),
           "правило перестало видеть вызов голым именем")


def suite_roles_anchor(res: Result) -> None:
    """`_ROLES` сверяется с ключами PERMS — иначе новая роль гасит правило."""
    clean = _clean()
    res.ok("якорь списка ролей существует", _seen(clean, "список ролей"),
           "проверки «список ролей совпадает с PERMS» в наборе нет")
    res.ok("и на живом дереве он зелёный", not _red(clean, "список ролей"),
           _why(clean, "список ролей"))

    r = _run("app/core/auth.py",
             ("    ROLE_MEDIC: set(),",
              "    ROLE_MEDIC: set(),\n    \"asistent\": set(),"))
    res.ok("четвёртая роль в PERMS краснеет", _red(r, "список ролей"),
           "новая роль вошла в PERMS, а _ROLES её не знает — сравнение роли "
           "по месту стало бы для неё законным, и молча")


def suite_release_arg(res: Result) -> None:
    """`check_release.py` принимает версию и с «v», и без — как release.py."""
    sys.path.insert(0, str(ROOT / "scripts"))
    # ⚠️ Импорт и вызовы под перехватом вывода намеренно: check_release при
    # загрузке переключает консоль на utf-8 (у него весь вывод русский), и
    # прогону это досталось бы кракозябрами до самого конца.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod = importlib.import_module("check_release")
        rel = {"tag_name": "v1.19.31", "html_url": "https://example/rel",
               "assets": [{"name": "dentpilot.exe", "size": 31_000_000,
                           "state": "uploaded", "digest": "sha256:0"}]}
        mod.api = lambda path: rel if path == "/latest" else [
            {"tag_name": "v1.19.31", "draft": False, "prerelease": False}]
        mod.TOKEN = "test"
        got = {}
        for arg in ("1.19.31", "v1.19.31"):
            mod.problems.clear()
            mod.notes.clear()
            got[arg] = (mod.main(arg), list(mod.problems))
    for arg, (code, problems) in got.items():
        res.ok(f"«{arg}» — исправный релиз признан исправным", code == 0,
               "; ".join(problems) or f"код возврата {code}")


def suite_version_source(res: Result) -> None:
    """Версия одна на программу: движок — источник, остальные её повторяют.

    ⚠️ Разъезд номеров не мешает НИЧЕМУ: сборка идёт, прогон зелёный, exe
    работает — просто в свойствах файла стоит не тот номер, а `package.json`
    врёт о версии клиента. Увидеть это можно, только открыв свойства в
    проводнике, поэтому проверка здесь. Поймано в первый же запуск 18.09:
    `package.json` отставал на версию.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    # ⚠️ Без перехвата вывода, в отличие от соседа: `sync_version` при импорте
    # НЕ печатает и НЕ трогает stdout — это его свойство и проверяется тем,
    # что импорт здесь голый.
    mod = importlib.import_module("sync_version")
    res.check("сегодня номера сходятся", mod.check(), [])
    v = mod.app_version()
    res.ok("версия движка — ровно три числа",
           bool(re.fullmatch(r"\d+\.\d+\.\d+", v)), f"версия {v!r}")
    res.check("клиент повторяет версию движка", mod.package_version(), v)

    # ⚠️ Сторож обязан краснеть, а не просто зеленеть: подменяем package.json
    # на копии и требуем находки. Без этого проверка выше зелена и тогда,
    # когда `check()` сломан (та же логика, что у mutate.py).
    with tempfile.TemporaryDirectory() as tmp:
        fake = pathlib.Path(tmp) / "package.json"
        fake.write_text('{\n  "name": "x",\n  "version": "0.0.1"\n}\n', encoding="utf-8")
        real = mod.PACKAGE
        mod.PACKAGE = fake
        try:
            drift = mod.check()
        finally:
            mod.PACKAGE = real
    res.ok("разъехавшийся номер клиента даёт находку",
           any("package.json" in d for d in drift),
           f"молчит: {drift}")

    # Ресурс свойств exe генерируется, а не правится руками: в нём обязана
    # стоять та же версия и имя файла, по которому обновление ищет ассет.
    info = mod.version_info(v)
    res.ok("ресурс свойств несёт версию движка и имя DentPilot.exe",
           f'"FileVersion", "{v}"' in info
           and '"OriginalFilename", "DentPilot.exe"' in info,
           "ресурс описывает не то")


def suite_route_map(res: Result) -> None:
    """Карта маршрутов B2 не отстаёт от кода.

    ⛔ Полярность у `screen_map.FLAG` ВКЛЮЧАЮЩАЯ: он перечисляет то, что есть,
    и забытая строка не делает его неверным — она делает его неполным. Карта
    при этом выглядит целой: столько же столбцов, ни одной жалобы. Так к 19.09
    он отстал на пять имён (perio и все три экрана журнала), и карта экранов
    молча показывала «—» у переехавших. Мутация такой список не спасает: она
    ломает сторожа тем же устаревшим именем.

    ⭐ Отсюда якорь: три источника обязаны совпадать ЗНАК В ЗНАК —
    `layout.REACT_SCREENS` (что сервер умеет отдать React), `FLAG` (по какому
    адресу), `App.tsx` (кто это нарисует). Разойдётся любой — здесь красное.
    ⚠️ Проверяется в обе стороны. «Все имена FLAG есть в REACT_SCREENS» одной
    половиной зеленело бы на пустом FLAG.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import screen_map

    src = (ROOT / "bot" / "app" / "core" / "layout.py").read_text(encoding="utf-8")
    blk = src.split("REACT_SCREENS = frozenset({", 1)[1].split("})", 1)[0]
    screens = set(re.findall(r'"([a-z_0-9]+)"', blk))
    res.ok("имена экранов вычитаны", len(screens) > 15,
           f"разобрано {len(screens)} — разбор сломан, проверки ниже пусты")

    flag = set(screen_map.FLAG.values())
    res.ok("у каждого React-экрана есть адрес в карте",
           not (screens - flag),
           "экран умеет ехать в React, но карта не знает откуда: "
           + ", ".join(sorted(screens - flag)))
    res.ok("в карте нет адреса под несуществующий экран",
           not (flag - screens),
           "карта называет экран, которого сервер не отдаст: "
           + ", ".join(sorted(flag - screens)))
    res.ok("адреса в карте не повторяются",
           len(screen_map.FLAG) == len(set(screen_map.FLAG.values())),
           "два адреса на один экран — маршрут станет неоднозначным")

    app = (ROOT / "frontend" / "src" / "app" / "App.tsx").read_text(encoding="utf-8")
    drawn = set(re.findall(r"screen === '([a-z_0-9]+)'", app))
    res.ok("клиент разбирает разбор экрана", len(drawn) > 15,
           f"разобрано {len(drawn)} — форма развилки в App.tsx изменилась, "
           "и эта проверка перестала что-либо значить")
    res.ok("каждый экран карты умеет рисоваться клиентом",
           not (screens - drawn),
           "сервер отдаст узел, а клиент покажет «экран не существует»: "
           + ", ".join(sorted(screens - drawn)))

    # ⛔ И строка B2 на КАЖДЫЙ адрес: без неё карта маршрутов печатает «?» в
    # колонках параметров и загрузчика, то есть выглядит заполненной.
    no_b2 = sorted(set(screen_map.FLAG) - set(screen_map.B2))
    res.ok("у каждого адреса есть параметры и загрузчик", not no_b2,
           "карта маршрутов напечатает «?»: " + ", ".join(no_b2))
    extra_b2 = sorted(set(screen_map.B2) - set(screen_map.FLAG))
    res.ok("нет строки B2 под адрес, которого нет в карте", not extra_b2,
           "строка описывает несуществующий маршрут: " + ", ".join(extra_b2))

    # ⚠️ И перевод адреса: правило «новых адресов не заводим» держится тем, что
    # маршрут React ВЫЧИСЛЯЕТСЯ. Проверяется на адресе с параметром пути —
    # на бесπараметрном перевод тождествен и доказывал бы только равенство себе.
    res.ok("адрес с параметром пути переводится, а не переписывается",
           screen_map.react_path("/admin/patient/{pid}") == "/admin/patient/:pid",
           f"получено {screen_map.react_path('/admin/patient/{pid}')}")

def suite_screen_map(res: Result) -> None:
    """Карта экранов видит ВСЕ маршруты — иначе parity доказывают по неполной.

    ⛔ Полярность у карты опасная: она устроена как «вот что есть», и маршрут,
    которого сборщик не понял, делает её ЛОЖНО ПОЛНОЙ — то же число строк, ни
    одной жалобы. Так 21.09 из неё выпал весь модуль экрана раздвоения: адрес
    был объявлен константой, а сборщик брал только литерал.

    ⚠️ Полный diff файла здесь НЕ сверяется намеренно. В карте есть счётчики
    проверок, и они меняются от каждого нового набора — гейт «файл совпадает»
    краснел бы на любом коммите с тестом и был бы отключён в первую неделю.
    Сверяется устойчивое: что каждый найденный маршрут в карте назван.
    ⭐ Свежесть целиком — отдельной командой, когда она нужна:
    `python scripts/screen_map.py --check`.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import screen_map

    rs, unresolved = screen_map.routes()
    res.ok("сборщик нашёл маршруты", len(rs) > 100,
           f"найдено {len(rs)} — обход дерева сломан, проверки ниже пусты")
    res.ok("адрес разобран у ВСЕХ маршрутов", not unresolved,
           "карта недосчитывает и молчит: " + ", ".join(unresolved))

    doc = screen_map.DOC
    if not res.ok("карта на месте", doc.exists(), f"нет {doc}"):
        return
    text = doc.read_text(encoding="utf-8")
    missing = sorted({r["path"] for r in rs if f"`{r['method']} {r['path']}`"
                      not in text})
    res.ok("каждый маршрут назван в карте", not missing,
           "карта устарела — `python scripts/screen_map.py`; нет: "
           + ", ".join(missing[:8]))

    # ⛔ И проверка на саму проверку: если разбор однажды перестанет находить
    # константы, этот маршрут исчезнет первым — он объявлен именно так.
    res.ok("маршрут, объявленный константой, найден",
           any(r["path"] == "/admin/migration" for r in rs),
           "сборщик снова берёт только литералы — модуль выпадет из карты молча")
