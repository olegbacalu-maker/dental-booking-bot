"""Транзакции оплаты картой (30.10, ревью): разбор исходников `ast`, сервер не поднимается.

settle — только под замком записи с начала (`db.connect(immediate=True)`). Отложенная
транзакция WAL, которая уже прочитала, при записи сразу получает «database is locked»,
если соседка успела закоммитить: busy timeout устаревший снимок не ждёт. maib почти разом
шлёт callback и возвращает браузер на /pay/ok — вторая ветка падала 500 (test_maib.suite_race).
Тест гонки держит это, пока внутри транзакции есть пауза (письмо); сторож — всегда.
"""
import ast
import copy

from harness import CLOUD, Result

# Кто держит settle своей транзакцией — по ним видно, что обход нашёл то, что должен
# (список ВКЛЮЧАЕТ требование: переименуют — красное «найдены», а не тихий ноль)
HOLDERS = {"_maib_callback", "_returned", "payment_check", "settle_cards"}


def _name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _connect(w: ast.With) -> ast.Call | None:
    """`db.connect(...)` среди элементов `with`, иначе None."""
    for item in w.items:
        e = item.context_expr
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "connect" \
                and isinstance(e.func.value, ast.Name) and e.func.value.id == "db":
            return e
    return None


def _immediate(call: ast.Call) -> bool:
    return any(k.arg == "immediate" and isinstance(k.value, ast.Constant) and k.value.value is True
               for k in call.keywords)


def _calls(node: ast.AST, inside_with: bool, out: list) -> None:
    """(вызов, ближайший `with db.connect` или None) — без вложенных def: у них свой учёт."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        w = inside_with
        if isinstance(child, ast.With) and _connect(child) is not None:
            w = child
        if isinstance(child, ast.Call):
            out.append((child, w))
        _calls(child, w, out)


def check(trees: dict[str, ast.Module]) -> tuple[set, dict, list]:
    """(обёртки settle, {функция: [(файл, строка, immediate)]} — её `with db.connect`, в
    которых зовётся settle или обёртка, нарушения «файл:строка функция»).
    Обёртка — функция, которая зовёт settle (или обёртку) ВНЕ своего `with db.connect`, то
    есть на чужом `con`: card_link, _settle_now, _card_go. Её вызовы требуют того же замка."""
    funcs = []
    for fname, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found: list = []
                _calls(node, None, found)
                funcs.append((fname, node, found))
    wrappers = {"settle"}
    while True:
        more = {fn.name for _, fn, found in funcs
                if fn.name != "settle" and any(w is None and _name(c) in wrappers for c, w in found)}
        if more <= wrappers:
            break
        wrappers |= more
    held: dict = {}
    bad = []
    for fname, fn, found in funcs:
        seen = set()
        for c, w in found:
            if w is None or _name(c) not in wrappers or id(w) in seen:
                continue
            seen.add(id(w))
            imm = _immediate(_connect(w))
            held.setdefault(fn.name, []).append((fname, w.lineno, imm))
            if not imm:
                bad.append(f"{fname}:{w.lineno} {fn.name}")
    return wrappers - {"settle"}, held, bad


def _trees() -> dict[str, ast.Module]:
    return {f.name: ast.parse(f.read_text(encoding="utf-8")) for f in sorted((CLOUD / "app").glob("*.py"))}


def _strip(trees: dict, func: str) -> dict:
    """Копия деревьев, где у `with db.connect` функции `func` снят immediate — мутация."""
    out = copy.deepcopy(trees)
    for tree in out.values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
                for w in ast.walk(node):
                    if isinstance(w, ast.With) and (call := _connect(w)) is not None:
                        call.keywords = [k for k in call.keywords if k.arg != "immediate"]
    return out


def suite_settle_lock(res: Result) -> None:
    """settle — только под db.connect(immediate=True), и пара: снятый immediate краснеет."""
    trees = _trees()
    res.ok("исходники нашлись: main.py, jobs.py, payments.py",
           {"main.py", "jobs.py", "payments.py"} <= set(trees), sorted(trees))
    wrappers, held, bad = check(trees)
    res.ok("обёртки settle найдены: card_link, _settle_now, _card_go",
           {"card_link", "_settle_now", "_card_go"} <= wrappers, sorted(wrappers))
    res.ok("транзакции с settle найдены у callback, возврата, «Проверить», ежедневной задачи",
           HOLDERS <= set(held), sorted(held))
    res.check("каждый with db.connect, где зовётся settle (или обёртка), — immediate=True", bad, [])
    for func in sorted(HOLDERS):
        _, _, mbad = check(_strip(trees, func))
        res.ok(f"пара: без immediate у {func} — сторож красный",
               any(b.endswith(" " + func) for b in mbad), repr(mbad))
