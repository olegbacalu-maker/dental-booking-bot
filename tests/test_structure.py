"""Правила раскладки кода из карты проекта — синтаксисом, а не прозой.

Единственный набор, который НЕ поднимает сервер: он читает исходники модулем
`ast`. Проверяет то, чего не видит ни один HTTP-запрос: где лежит файл, кто
кого импортирует, кто забыл позвать соседа. Такие поломки молчаливы — запрос
успешен, лог чист, а собранная у клиники программа либо не стартует, либо
показывает не то (грабли `__file__` 08-04 и `__package__` 08-05).

Каждое правило здесь уже записано прозой в CLAUDE.md и уже соблюдается. Набор
ничего не чинит: он не даёт правилу тихо отмереть при следующем переезде файла.
"""
import ast
import re

from harness import BOT, Result

# Файлы, которые `desktop.py` зовёт ДО того, как собрано приложение: импортов
# проекта в них нет и быть не может, и лежать они обязаны в корне app/.
# Переезд любого из них в подпапку ломает запуск у клиники, не тронув запуск
# из исходников — то есть ни один прогон этого не заметит.
_PRELOAD = ("app/paths.py", "app/dpapi.py", "app/envfile.py")

# Друг друга им знать можно — это один слой, живущий до сборки приложения
# (dpapi правит токен в dental.env, то есть зовёт envfile). Нельзя всё
# остальное: db, engine, core, модули — любой из них тянет за собой FastAPI.
_PRELOAD_MOD = {p.rsplit("/", 1)[-1][:-3] for p in _PRELOAD}

# `__file__` законен ровно там, где кто-то обязан знать, где лежит он сам:
# paths.py — единственный, кто знает раскладку; desktop.py — лаунчер, который
# зовут раньше paths. Везде ещё «путь рядом с собой» переживёт переезд файла
# в исходниках и умрёт внутри exe, где раскладка другая.
_FILE_OK = {"app/paths.py", "desktop.py"}

# Все, кто в итоге зовёт `_save_users`, то есть переписывает auth.json.
# verify_pin здесь не по недосмотру: при входе он молча мигрирует файл v1→v2.
# Забытый рядом remember_auth_file() = ложный «взлом» при следующем старте, а
# это хуже настоящего — клиника перестанет верить баннеру.
_AUTH_WRITERS = {"save_user", "delete_user", "_write_pin", "verify_pin"}

# Роль — НАБОР ПРАВ в таблице PERMS, а не строка, которую сравнивают по месту.
# Ловим и литерал, и константу: `role == "director"` и `role == ROLE_DIRECTOR`.
_ROLES = {"director", "receptie", "medic"}

# Законные сравнения роли: код, который ролями УПРАВЛЯЕТ, а не который решает
# по роли, что человеку можно. Экран учёток обязан знать, что такое директор,
# и через PERMS этого не выразить:
#   _users_block — какая роль выбрана в <option> по умолчанию;
#   users_save   — «последний директор снимает с себя роль» запер бы настройки
#                  навсегда: вернуть право станет некому.
# Список именной, а не по файлу: settings/routes.py длиной под тысячу строк, и
# разрешение на весь файл спрятало бы в нём будущую проверку доступа по роли.
# Переименуют функцию — набор покраснеет, и это правильно: повод посмотреть.
_ROLE_OK = {"app/modules/settings/routes.py": {"_users_block", "users_save"}}

# Владелец правила: внутри него сравнивать роли и переписывать auth.json можно,
# на то он и один на всю программу.
_AUTH_MODULE = "app/core/auth.py"

# Страница со своей вёрсткой, просящая 'Inter', обязана его и ОБЪЯВИТЬ: либо
# заполнителем __FONTS__ (его заполняет layout.standalone текстом fonts.css),
# либо своими @font-face. Правило нужно ровно потому, что нарушение невидимо:
# такая страница цела, просто нарисована системным шрифтом, — а Inter не
# установлен и у разработчика, поэтому «выглядит как всегда» и у него. Так
# экран входа полгода жил в Segoe UI, пока panel.css показывала задуманный вид.
# Знаки, которые рисует система: эмодзи, стрелки, дингбаты, геометрия и
# математика. ⭐ Блок математических операторов (U+2200..U+22FF) дописан 08-16:
# «−» U+2212 и «≈» U+2248 не эмодзи и глаз их не выделяет, но во вшитый Inter
# они не входят ровно так же, как стрелка, — то есть рисует их Windows. Правило
# берёт БЛОК, а не два знака: «всё, кроме перечисленного» живёт до первого
# нового знака и ломается молча (тот же урок, что у PLAN_ACTIVE).
_SYSGLYPH = re.compile("[🀀-🫿←-⇿∀-⋿⌀-⏿"
                       "■-➿⬀-⯿]")
_BOT_TEXTS = ("app/engine.py", "app/telegram.py")

_INTER = re.compile(r"font-family\s*:\s*['\"]?Inter")
_DECLARED = ("__FONTS__", "@font-face")


def _ui_texts(tree: ast.Module) -> list[tuple[int, str]]:
    """Строковые литералы модуля БЕЗ docstring'ов, каждый одним куском.

    Пояснения в проекте написаны со знаками ⚠/⭐/⛔ по стилю, и до экрана они
    не доезжают — запрещать их незачем, а с ними правило краснело бы всегда.
    Отсев по САМОМУ узлу, а не по номеру строки: у многострочного литерала
    номер зависит от версии Python, и сверка номеров тихо перестала бы ловить."""
    inner = {id(x) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)
             for x in ast.walk(n) if x is not n}
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)) and n.body:
            first = n.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docs.add(id(first.value))
    out = []
    for n in ast.walk(tree):
        if id(n) in inner or id(n) in docs:
            continue
        if isinstance(n, ast.JoinedStr):
            out.append((n.lineno, "".join(v.value for v in ast.walk(n)
                                          if isinstance(v, ast.Constant)
                                          and isinstance(v.value, str))))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append((n.lineno, n.value))
    return out


def _sources() -> list[tuple[str, ast.Module]]:
    """Все модули программы: (путь от bot/ через `/`, разобранное дерево)."""
    out = []
    for p in sorted(BOT.rglob("*.py")):
        rel = p.relative_to(BOT).as_posix()
        out.append((rel, ast.parse(p.read_text(encoding="utf-8"), filename=rel)))
    return out


def _calls(node: ast.AST) -> set[str]:
    """Имена функций, вызванных внутри узла. `await f()` тоже считается: Await
    оборачивает Call, а walk доходит до него.

    ⚠️ Последнее имя берётся и у вызова ЧЕРЕЗ МОДУЛЬ (`auth.save_user(...)` —
    это ast.Attribute, у него нет `.id`). Правило про отпечаток auth.json
    включающее: не увидев вызова, оно молчит, а не краснеет, — то есть чужой
    стиль импорта выключал бы его целиком. А модулем-объектом здесь ходят
    почти все (`from ...core import theme`), и сегодня правило работает лишь
    потому, что писателей auth.json импортируют поимённо."""
    return {n.func.id if isinstance(n.func, ast.Name) else n.func.attr
            for n in ast.walk(node) if isinstance(n, ast.Call)
            and isinstance(n.func, (ast.Name, ast.Attribute))}


def _enclosing(tree: ast.Module, lineno: int) -> set[str]:
    """Имена всех функций, внутри которых лежит строка (вложенные — тоже)."""
    return {fn.name for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and fn.lineno <= lineno <= (fn.end_lineno or fn.lineno)}


def _templates(tree: ast.Module) -> list[tuple[int, str]]:
    """Строковые литералы модуля — каждый ОДНИМ куском: (строка, текст).

    f-строка разобрана на части, и заполнитель вполне может лежать в другой
    части, чем `font-family` (`<style>__FONTS__ … {color}` — уже две). Поэтому
    части одного литерала склеиваются, а вложенные в него узлы вторым разом не
    разбираются: иначе один шаблон дал бы десяток «нарушителей»."""
    inner = {id(x) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)
             for x in ast.walk(n) if x is not n}
    out = []
    for n in ast.walk(tree):
        if id(n) in inner:
            continue
        if isinstance(n, ast.JoinedStr):
            text = "".join(v.value for v in ast.walk(n)
                           if isinstance(v, ast.Constant)
                           and isinstance(v.value, str))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            text = n.value
        else:
            continue
        out.append((n.lineno, text))
    return out


def _imported(node: ast.AST) -> list[str]:
    """Что импортирует один узел import/from-import — модуль и имена вместе."""
    if isinstance(node, ast.ImportFrom):
        return [node.module or ""] + [a.name for a in node.names]
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    return []


def suite(res: Result) -> None:
    src = _sources()
    by_path = dict(src)

    # Сторож за сторожами. Все проверки ниже устроены как «нарушителей не
    # нашлось», и пустой список файлов делает их все зелёными разом. Если
    # раскладка репозитория однажды переедет, упасть должно здесь, а не
    # притвориться успехом.
    res.ok("исходники нашлись", len(src) > 20,
           f"под {BOT} разобрано файлов: {len(src)}")

    bad = [f"{rel}:{n.lineno}" for rel, tree in src if rel not in _FILE_OK
           for n in ast.walk(tree)
           if isinstance(n, ast.Name) and n.id == "__file__"]
    res.ok("__file__ только в paths.py и desktop.py", not bad,
           "путь «рядом с собой» вне разрешённых мест: " + ", ".join(bad))

    # Правильно — `(__package__ or "app").split(".")[0]`. Голый __package__ в
    # имени модуля после переезда файла в подпапку начинает означать другое, и
    # никакой ошибки при этом не всплывает: статус живого бота показывался
    # выключенным при чистом логе и успешном запросе.
    bad = []
    for rel, tree in src:
        safe = set()
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "split"):
                safe.update(id(x) for x in ast.walk(n)
                            if isinstance(x, ast.Name) and x.id == "__package__")
        bad += [f"{rel}:{n.lineno}" for n in ast.walk(tree)
                if isinstance(n, ast.Name) and n.id == "__package__"
                and id(n) not in safe]
    res.ok("__package__ только через .split('.')[0]", not bad,
           "имя модуля считается от __package__ целиком: " + ", ".join(bad))

    bad = []
    for rel, tree in src:
        if rel == _AUTH_MODULE:
            continue
        allowed = _ROLE_OK.get(rel, set())
        for n in ast.walk(tree):
            if not isinstance(n, ast.Compare):
                continue
            if not all(isinstance(o, (ast.Eq, ast.NotEq)) for o in n.ops):
                continue        # `in ("director", …)` — это проверка ввода
            for side in [n.left, *n.comparators]:
                lit = isinstance(side, ast.Constant) and side.value in _ROLES
                const = isinstance(side, ast.Name) and side.id.startswith("ROLE_")
                # белый список спрашиваем ПОСЛЕ совпадения: _enclosing обходит
                # дерево целиком, и на каждое сравнение подряд это секунды
                if (lit or const) and not allowed & _enclosing(tree, n.lineno):
                    bad.append(f"{rel}:{n.lineno}")
                    break
    res.ok("роль не сравнивается по месту", not bad,
           "доступ решается сравнением роли, а не PERMS: " + ", ".join(bad))

    # Якорь к правилу выше. `_ROLES` — список ВКЛЮЧАЮЩИЙ: четвёртая роль в
    # PERMS выключила бы правило для себя молча, потому что её литерала в
    # списке нет (ветка `ROLE_*` спасает только тех, кто пишет сравнение
    # константой). Источник истины один — ключи PERMS; расхождение в ЛЮБУЮ
    # сторону красное: лишнее имя тут так же слепо, как недостающее.
    auth_mod = by_path.get(_AUTH_MODULE) or ast.Module(body=[], type_ignores=[])
    role_const = {n.targets[0].id: n.value.value for n in ast.walk(auth_mod)
                  if isinstance(n, ast.Assign) and len(n.targets) == 1
                  and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id.startswith("ROLE_")
                  and isinstance(n.value, ast.Constant)}
    perms_keys = None
    for n in ast.walk(auth_mod):
        if (isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "PERMS"
                        for t in n.targets)
                and isinstance(n.value, ast.Dict)):
            perms_keys = {k.value if isinstance(k, ast.Constant)
                          else role_const.get(k.id) if isinstance(k, ast.Name)
                          else None for k in n.value.keys}
    res.ok("список ролей совпадает с PERMS", perms_keys == _ROLES,
           f"_ROLES={sorted(_ROLES)}, ключи PERMS="
           f"{sorted(map(str, perms_keys)) if perms_keys is not None else None}"
           f" — правило ловит сравнение по месту только для перечисленных имён")

    # Полярность правила ниже опасная: `_AUTH_WRITERS` — список имён, которые
    # ВКЛЮЧАЮТ требование. Переименуют `save_user` — правило станет искать
    # несуществующее имя, найдёт ноль нарушителей и позеленеет НАВСЕГДА. Мутация
    # этого не ловит: она ломает сторожа тем же устаревшим именем. Поэтому имена
    # сверяются с определениями в самом auth.py. (Остальные списки — обратной
    # полярности и краснеют сами: пропал `paths.py` — не нашёлся файл; переехал
    # `users_save` — сравнение роли в нём перестало быть разрешённым.)
    defined = {fn.name for fn in ast.walk(by_path.get(_AUTH_MODULE) or ast.Module(
        body=[], type_ignores=[]))
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
    gone = sorted(_AUTH_WRITERS - defined)
    res.ok("список пишущих auth.json не протух", not gone,
           f"нет в {_AUTH_MODULE}: {', '.join(gone)} — правило ищет то, чего "
           f"больше нет, и молчит")

    # Внутри auth.py пломбу ставить не надо: модуль владеет файлом, и там
    # writers свободно зовут друг друга (verify_pin → _write_pin → _save_users).
    # Обязанность возникает у ЧУЖОГО кода, который тронул auth.json.
    bad = []
    for rel, tree in src:
        if rel == _AUTH_MODULE:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = _calls(fn)
            if called & _AUTH_WRITERS and "remember_auth_file" not in called:
                who = ", ".join(sorted(called & _AUTH_WRITERS))
                bad.append(f"{rel}:{fn.lineno} {fn.name}() зовёт {who}")
    res.ok("кто пишет auth.json — обновляет отпечаток", not bad,
           "забыт remember_auth_file(): " + "; ".join(bad))

    bad = []
    for rel in _PRELOAD:
        if rel not in by_path:
            bad.append(f"{rel} — нет по этому пути")
            continue
        for n in ast.walk(by_path[rel]):
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            targets = [m for m in _imported(n) if m]
            own = getattr(n, "level", 0) or any(
                m.split(".")[0] == "app" for m in targets)
            if not own:
                continue                    # стандартная библиотека — можно
            outside = [m for m in targets
                       if m.split(".")[-1] not in _PRELOAD_MOD]
            if outside:
                bad.append(f"{rel}:{n.lineno} → {', '.join(outside)}")
    res.ok("paths/dpapi/envfile в корне app/ и без импортов проекта", not bad,
           "лаунчер зовёт их до сборки приложения: " + "; ".join(bad))

    # main.py подключает роутеры модулей; обратный импорт замкнул бы круг.
    # Сегодня это упало бы и так, громко, — правило стоит здесь ради того, чтобы
    # его нельзя было «починить» отложенным импортом внутри функции.
    bad = [f"{rel}:{n.lineno}" for rel, tree in src
           if rel.startswith(("app/modules/", "app/core/"))
           for n in ast.walk(tree)
           if any(m.split(".")[-1] == "main" for m in _imported(n) if m)]
    res.ok("модуль не импортирует main", not bad,
           "модуль знает про main.py: " + ", ".join(bad))

    bad = [f"{rel}:{ln}" for rel, tree in src for ln, text in _templates(tree)
           if _INTER.search(text) and not any(d in text for d in _DECLARED)]
    res.ok("страница со своей вёрсткой объявляет шрифт", not bad,
           "просит 'Inter', не объявив его (__FONTS__ в <style>): "
           + ", ".join(bad))


    # ---- ничего графического от Windows (08-11) ----
    # Эмодзи, стрелки, галочки и геометрию рисует ОПЕРАЦИОННАЯ СИСТЕМА своим
    # шрифтом: по-разному на 10 и 11, всегда цветными посреди сдержанного
    # экрана и мимо выбранного клиникой цвета. Вшитый Inter покрывает четыре
    # подмножества, и ни в одно из них не входят U+2192, U+25B2..U+25C0,
    # U+2714/U+2715, U+23F3 — то есть «не эмодзи» тут ничего не значит.
    # ⭐ Правило смотрит в СТРОКОВЫЕ ЛИТЕРАЛЫ, а не в файл: комментарии и
    # docstring'и до экрана не доезжают, и запрещать их незачем.
    # ⛔ Тексты бота (engine.py, telegram.py) исключены намеренно: их рисует
    # Telegram на телефоне пациента, а не Windows на машине клиники.
    # ⚠️ Область — ВЕСЬ bot/, а не только modules/ и core/: экраны живут и в
    # main.py (вход, установка PIN, весь режим восстановления), а тексты для
    # человека — ещё и в db.py (летопись пациента). Префиксный фильтр держался
    # тут не по решению, и под ним пережили все релизы ✅ на экране
    # восстановления и две стрелки → в текстах db.py. Заодно в область попадают
    # строки лога: знак в них безвреден, но и не нужен, а исключение по «это
    # лог» пришлось бы угадывать по имени функции.
    bad = []
    for rel, tree in src:
        if rel in _BOT_TEXTS:
            continue
        for ln, text in _ui_texts(tree):
            found = "".join(dict.fromkeys(_SYSGLYPH.findall(text)))
            if found:
                bad.append(f"{rel}:{ln} {found}")
    res.ok("интерфейс не просит знаки у Windows", not bad,
           "рисует системным шрифтом (нужна иконка из layout._I): "
           + "; ".join(bad[:8]))

    # ⚠️ Забытый импорт `_ic` не виден ни глазами, ни этим набором иначе:
    # вызов в ветке `if meta.get("room")` на демо-профиле просто не исполняется,
    # страница открывается, а у клиники с заполненным кабинетом падает. Ровно
    # так и случилось 08-11 со списком врачей.
    bad = []
    for rel, tree in src:
        text = (BOT / rel).read_text(encoding="utf-8")
        if not re.search(r"(?<![A-Za-z_])_ic\(", text) or "def _ic(" in text:
            continue
        names = {a.asname or a.name for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) for a in n.names}
        if "_ic" not in names:
            bad.append(rel)
    res.ok("кто зовёт _ic — тот его импортирует", not bad,
           "вызывает _ic без импорта: " + ", ".join(bad))

    # ⚠️ Тот же вызов, забытый f-префиксом, не падает ВООБЩЕ: строка уезжает на
    # экран как есть, и заголовок раздела читается «{_ic('wifi')} Acces din
    # rețea». Ни ошибки, ни пустого места, ни следа в логе — глазами это
    # переживает и ревью, и релиз: так `settings/lan.py` прожил от 1.15.0 до
    # 1.19.23 (нашлось 08-13, когда страницу открыли по другому поводу).
    # Ловится только текстом литерала: f-строка разбирается парсером, и
    # заполнитель в её частях не остаётся, — значит `{_ic(` уцелел ровно там,
    # где префикс забыли.
    bad = [f"{rel}:{ln}" for rel, tree in src for ln, text in _ui_texts(tree)
           if "{_ic(" in text]
    res.ok("вызов _ic не остаётся текстом", not bad,
           "строка без f-префикса — знак уедет на экран как есть: "
           + ", ".join(bad))

    # ---- ответ на действие строит только layout (08-14) ----
    # msg_banner в layout — единственное место, где код из ?msg= становится
    # разметкой: плашка ПЛАВАЕТ поверх окна, потому что форма записи стоит
    # внизу страницы, а 303 открывает её с нулевой прокруткой — баннер в потоке
    # клиника не увидела («сказали ок, а что случилось — не поняли»). Модуль,
    # собравший баннер из словаря сам, вернул бы сообщение в поток, и на
    # коротких страницах разработчика это невидимо.
    # ⚠️ Полярность опасная: правило ищет ИМЯ, и после переименования словаря
    # оно позеленело бы навсегда — поэтому сперва якорь «словарь ещё есть».
    layout_tree = by_path.get("app/core/layout.py")
    has_dict = layout_tree is not None and any(
        isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "MSG_BANNER" for t in n.targets)
        for n in ast.walk(layout_tree))
    bad = [] if has_dict else ["app/core/layout.py: словарь MSG_BANNER не найден"]
    bad += [f"{rel}:{n.lineno}" for rel, tree in src
            if rel != "app/core/layout.py"
            for n in ast.walk(tree)
            if (isinstance(n, ast.Name) and n.id == "MSG_BANNER")
            or (isinstance(n, ast.ImportFrom)
                and any(a.name == "MSG_BANNER" for a in n.names))]
    res.ok("ответ на действие строит только layout", not bad,
           "MSG_BANNER вне layout.msg_banner — сообщение вернётся строкой в "
           "поток, и внизу страницы его опять не видно: " + ", ".join(bad))

    # ---- миграции db: версия схемы и schema_meta (08-15) ----
    # Шаг, добавленный в словари миграций без поднятия SCHEMA_VERSION, — мёртвый
    # код: цикл _migrate идёт range(have+1, SCHEMA_VERSION+1) и до него не
    # доходит, а страж «missing migration step» ловит только отсутствующие
    # шаги, не лишние. Ровно так шаг 4 ('waiting' в предикатах uq-индексов) не
    # исполнялся ни у одной клиники с 08-13 — молча: база «домигрирована»,
    # лог чист, страховки от двойной брони на waiting-визите нет.
    # ⚠️ Полярность опасная: правило ищет ИМЕНА. Переименуют SCHEMA_VERSION или
    # словарь — искать станет нечего, поэтому «не нашлось» здесь тоже красное.
    db_tree = by_path.get("app/db.py")
    consts, dictkeys = {}, {}
    for n in ast.walk(db_tree or ast.Module(body=[], type_ignores=[])):
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)):
            continue
        name = n.targets[0].id
        if isinstance(n.value, ast.Constant):
            consts[name] = n.value.value
        elif isinstance(n.value, ast.Dict):
            dictkeys[name] = [k.value for k in n.value.keys
                              if isinstance(k, ast.Constant)]
    ver = consts.get("SCHEMA_VERSION")
    pg = dictkeys.get("MIGRATIONS_PG")
    lite = dictkeys.get("MIGRATIONS_LITE")
    res.ok("версия схемы равна последнему шагу миграций",
           isinstance(ver, int) and bool(pg) and bool(lite)
           and max(pg) == max(lite) == ver,
           f"SCHEMA_VERSION={ver!r}, max(MIGRATIONS_PG)="
           f"{max(pg) if pg else None}, max(MIGRATIONS_LITE)="
           f"{max(lite) if lite else None} — лишний шаг не исполнится ни у "
           f"одной клиники, недостающий уронит _migrate")

    # В schema_meta безусловно пишут _set_schema_version, set_meta и backfill —
    # таблица обязана создаваться В ОБЕИХ схемах. Из PG_SCHEMA её однажды
    # удалили случайно (434513c), и облако переставало стартовать на свежем
    # Postgres; прогон этого не видит — все наборы гоняют SQLite-ветку.
    # ---- границы PIN в текстах — из констант (08-15) ----
    # PIN_MIN/PIN_MAX живут в core/auth.py и уже поднимались (4–6 → 4–8,
    # 08-13). Текст, назвавший диапазон числами, при этом отстаёт МОЛЧА:
    # баннер «nu are 4–6 cifre» отговаривал от разрешённых 7–8 цифр, а экран
    # первой установки противоречил сам себе. Правило: строковый литерал с
    # «N–M cifre» обязан называть ровно PIN_MIN–PIN_MAX (докстринги и
    # комментарии до экрана не доезжают — их правило пропускает).
    # ⚠️ Полярность опасная в обе стороны: константы обязаны НАЙТИСЬ (иначе
    # сверять не с чем), и хотя бы один текст с диапазоном обязан существовать
    # (плейсхолдер «PIN 4–8 cifre») — иначе правило сторожит пустоту.
    auth_tree = by_path.get("app/core/auth.py")
    pin_rng = None
    for n in ast.walk(auth_tree or ast.Module(body=[], type_ignores=[])):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Tuple)
                and [getattr(t, "id", None) for t in n.targets[0].elts]
                == ["PIN_MIN", "PIN_MAX"]
                and isinstance(n.value, ast.Tuple)):
            vals = [v.value for v in n.value.elts if isinstance(v, ast.Constant)]
            if len(vals) == 2:
                pin_rng = tuple(vals)
    rng_re = re.compile(r"(\d+)\s*[–—-]\s*(\d+)\s+cifre")
    bad = [] if pin_rng else ["app/core/auth.py: PIN_MIN/PIN_MAX не найдены"]
    hits = 0
    if pin_rng:
        for rel, tree in src:
            for ln, text in _ui_texts(tree):
                for m in rng_re.finditer(text):
                    hits += 1
                    if (int(m.group(1)), int(m.group(2))) != pin_rng:
                        bad.append(f"{rel}:{ln} «{m.group(0)}»")
        if not hits:
            bad.append("ни один текст не называет диапазон — якорь правила "
                       "пропал (плейсхолдер «PIN 4–8 cifre»)")
    res.ok("тексты называют диапазон PIN из констант", not bad,
           f"текст расходится с PIN_MIN/PIN_MAX={pin_rng}: " + "; ".join(bad))

    need = "CREATE TABLE IF NOT EXISTS schema_meta("
    bad = [what for what, ok in (
        ("PG_SCHEMA", need in str(consts.get("PG_SCHEMA", ""))),
        ("SQLITE_SCHEMA/SQLITE_CARD_SCHEMA",
         any(need in str(consts.get(v, ""))
             for v in ("SQLITE_SCHEMA", "SQLITE_CARD_SCHEMA"))),
    ) if not ok]
    res.ok("schema_meta создаётся в обеих схемах", not bad,
           "нет CREATE TABLE schema_meta в: " + ", ".join(bad)
           + " — издание на этой схеме не стартует на пустой базе")
