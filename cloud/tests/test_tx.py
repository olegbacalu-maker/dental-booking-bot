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
HOLDERS = {"_maib_callback", "_returned", "payment_check", "settle_cards",
           "_card_go", "payment_new", "payment_link", "payment_confirm", "payment_repeat"}
# Кто делает ноту `paid`: settle (карта) и confirm / credit_again («Подтвердить», «Зачесть
# повторный» админки) — у всех одна гонка с callback, и замок нужен один
PAID_WRITERS = {"settle", "confirm", "credit_again"}


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
    """(обёртки, {функция: [(файл, строка, immediate)]} — её `with db.connect`, в которых
    зовётся пишущий paid (PAID_WRITERS) или обёртка, нарушения «файл:строка функция»).
    Обёртка — функция, которая зовёт пишущего (или обёртку) ВНЕ своего `with db.connect`, то
    есть на чужом `con`: card_record, _settle_now. Её вызовы требуют того же замка."""
    funcs = []
    for fname, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found: list = []
                _calls(node, None, found)
                funcs.append((fname, node, found))
    wrappers = set(PAID_WRITERS)
    while True:
        more = {fn.name for _, fn, found in funcs
                if fn.name not in PAID_WRITERS and any(w is None and _name(c) in wrappers for c, w in found)}
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
    return wrappers - PAID_WRITERS, held, bad


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
    """settle, confirm, credit_again — только под db.connect(immediate=True), и пара: снятый
    immediate краснеет."""
    trees = _trees()
    res.ok("исходники нашлись: main.py, jobs.py, payments.py",
           {"main.py", "jobs.py", "payments.py"} <= set(trees), sorted(trees))
    wrappers, held, bad = check(trees)
    res.ok("обёртки settle найдены: card_record, _settle_now",
           {"card_record", "_settle_now"} <= wrappers, sorted(wrappers))
    res.ok("транзакции с settle / confirm / credit_again найдены у callback, возврата, «Проверить», "
           "ежедневной задачи, кнопки карты, ноты и ссылки из админки, «Подтвердить», «Зачесть повторный»",
           HOLDERS <= set(held), sorted(held))
    res.check("каждый with db.connect, где зовётся settle / confirm / credit_again (или обёртка), — "
              "immediate=True", bad, [])
    for func in sorted(HOLDERS):
        _, _, mbad = check(_strip(trees, func))
        res.ok(f"пара: без immediate у {func} — сторож красный",
               any(b.endswith(" " + func) for b in mbad), repr(mbad))


# ---------- письма — после commit (шаг 3) ----------
# SMTP держит до 30 с (mail.send, timeout=30); внутри транзакции это время замка записи, и
# соседние записи (callback, лицензия) падают через 10 с ожидания. Отправка — только вне
# `with db.connect`: письмо собирается в транзакции (payments.notify_paid, license.letter_latest,
# sms.letter_*), уходит после commit (payments.outbox → send_paid → mail.deliver).

SCOPE = ("main.py", "jobs.py", "payments.py")
# Отправляющие сами по себе; `send` без модуля — mail.send, переданный параметром (jobs, sms)
SEND_BASE = {"mail.send", "mail.deliver"}

# Где письма собираются в транзакции и уходят через outbox — 7 мест оплаты решения Р4:
# callback, возврат браузера, ежедневная задача, «Проверить» (_settle_now), «Подтвердить»,
# «Зачесть повторный», кнопка карты (_card_go); и письмо с нотой (шаг 4): страница оплаты,
# кабинет, общая нота, «Выставить ноту», «Ссылка на карту», «Письмо» из админки.
# Список ВКЛЮЧАЕТ требование — переименуют, и «найдены» покраснеет, а не позеленеет тихо.
OUTBOX_HOLDERS = {"_maib_callback", "_returned", "settle_cards", "payment_check", "payment_confirm",
                  "payment_repeat", "_card_go", "pay_link_submit", "cont_note", "_group_submit",
                  "payment_new", "payment_link", "payment_mail"}

# Отправка внутри транзакции, оставленная НАМЕРЕННО: не письмо об оплате (решение Олега Р4 —
# в эту ветку не берём, список в отчёт). Ключ — «файл:функция → вызов».
MAIL_IN_TX = {
    # не оплата (Р4): в эту ветку не берём, список — в отчёт
    "main.py:_sms_order → mail.send": "нота SMS из программы (main.py ~327)",
    "main.py:_trial_program → trial.submit": "пробный из программы: выдача и письмо (trial.py:218)",
    "main.py:trial_submit → trial.submit": "пробный с /proba: выдача и письмо (trial.py:218)",
    "main.py:cont_register_submit → account.register": "регистрация кабинета → trial.submit (trial.py:218)",
    "main.py:cont_add_submit → account.add_clinic": "«Adaugă clinică» → trial.submit (trial.py:218)",
    "main.py:cont_add_submit → main._send_added_letter": "письмо новой клинике кабинета (нота + ящик)",
    "main.py:clinic_issue → main._send_latest": "файл письмом из админки после выдачи (main.py ~1650)",
    "main.py:clinic_email → main._send_latest": "файл письмом из админки, кнопка «отправить»",
    "jobs.py:daily → jobs._one": "напоминания о сроке ежедневной задачи (send параметром)",
}


def _key(call: ast.Call, stem: str, mods: set) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in mods:
        return f"{f.value.id}.{f.attr}"
    if isinstance(f, ast.Name):
        return f"{stem}.{f.id}"
    return None


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _walk(node: ast.AST, w, out: list) -> None:
    """(вызов, ближайший `with db.connect` или None), без вложенных def. Элементы `with` ПОСЛЕ
    db.connect выходят РАНЬШЕ commit — они внутри транзакции; до него — снаружи (outbox)."""
    if isinstance(node, _DEFS):
        return
    if isinstance(node, ast.With) and (conn := _connect(node)) is not None:
        after = False
        for item in node.items:
            _walk(item.context_expr, node if after else w, out)
            after = after or item.context_expr is conn
        for stmt in node.body:
            _walk(stmt, node, out)
        return
    if isinstance(node, ast.Call):
        out.append((node, w))
    for child in ast.iter_child_nodes(node):
        _walk(child, w, out)


def _funcs(trees: dict[str, ast.Module]) -> tuple[set, list]:
    """(модули, [(файл, модуль, def, [(вызов, with db.connect или None, «модуль.имя»)])])."""
    mods = {f[:-3] for f in trees}
    funcs = []
    for fname, tree in trees.items():
        stem = fname[:-3]
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found: list = []
                for stmt in node.body:
                    _walk(stmt, None, found)
                funcs.append((fname, stem, node, [(c, w, _key(c, stem, mods)) for c, w in found]))
    return mods, funcs


def _closure(funcs: list, base: set) -> set:
    """`base` и каждая функция, что зовёт кого-то из них где угодно — по цепочке."""
    out = set(base)
    while True:
        more = {f"{stem}.{fn.name}" for _, stem, fn, found in funcs if any(k in out for _, _, k in found)}
        if more <= out:
            return out
        out |= more


def _inside(funcs: list, reach: set) -> list:
    """Нарушения «файл:функция → вызов»: вызов из `reach` внутри `with db.connect` в SCOPE."""
    return sorted({f"{fname}:{fn.name} → {k}" for fname, _, fn, found in funcs if fname in SCOPE
                   for _, w, k in found if w is not None and k in reach})


def mail_check(trees: dict[str, ast.Module]) -> tuple[set, dict, list]:
    """(отправляющие функции «модуль.имя», {функция: [строки with, где outbox раньше
    db.connect]}, нарушения «файл:функция → вызов» в SCOPE). Отправляющая — та, что зовёт
    отправляющую где угодно (в своей транзакции или после неё): её вызов внутри чужой
    транзакции — SMTP под замком."""
    mods, funcs = _funcs(trees)
    senders = _closure(funcs, SEND_BASE | {f"{m}.send" for m in mods})
    boxed: dict = {}
    for fname, stem, fn, found in funcs:
        for node in ast.walk(fn):
            if isinstance(node, ast.With) and (conn := _connect(node)) is not None:
                first = node.items[0].context_expr
                if first is not conn and isinstance(first, ast.Call) and _key(first, stem, mods) == "payments.outbox":
                    boxed.setdefault(fn.name, []).append(node.lineno)
    return senders, boxed, _inside(funcs, senders)


def _func(tree: ast.Module, func: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return node
    raise AssertionError(f"нет функции {func}")


def _inject(trees: dict, fname: str, func: str, src: str) -> dict:
    """Копия деревьев: `src` первой строкой в первый `with db.connect` функции — мутация."""
    out = copy.deepcopy(trees)
    for w in ast.walk(_func(out[fname], func)):
        if isinstance(w, ast.With) and _connect(w) is not None:
            w.body.insert(0, ast.parse(src).body[0])
            return out
    raise AssertionError(f"{fname}:{func} без with db.connect")


def _swap(trees: dict, fname: str, func: str) -> dict:
    """Копия: `with payments.outbox(), db.connect()` функции наоборот — письма ушли бы до commit."""
    out = copy.deepcopy(trees)
    for w in ast.walk(_func(out[fname], func)):
        if isinstance(w, ast.With) and _connect(w) is not None and len(w.items) == 2:
            w.items.reverse()
    return out


def _prepend(trees: dict, fname: str, func: str, src: str) -> dict:
    """Копия: `src` первой строкой тела функции (сборка письма начала отправлять)."""
    out = copy.deepcopy(trees)
    _func(out[fname], func).body.insert(0, ast.parse(src).body[0])
    return out


def suite_mail_after_commit(res: Result) -> None:
    """Письма об оплате — после commit: ни mail.send, ни отправляющей функции внутри
    `with db.connect` в main.py, jobs.py, payments.py, кроме названных исключений; и пары."""
    trees = _trees()
    need = {"main.py", "jobs.py", "payments.py", "license.py", "sms.py", "mail.py"}
    res.ok("исходники нашлись: main.py, jobs.py, payments.py, license.py, sms.py, mail.py",
           need <= set(trees), sorted(need - set(trees)))
    senders, boxed, bad = mail_check(trees)
    want = {"mail.send", "mail.deliver", "payments.send_paid", "payments.outbox", "license.mail_latest"}
    res.ok("отправляющие найдены: mail.send/deliver, send_paid, outbox, обёртка mail_latest",
           want <= senders, sorted(want - senders))
    builders = {"payments.notify_paid", "license.letter_latest", "sms.letter_pack", "sms.letter_name",
                "main._payment_letter", "main._settle_now", "payments.card_plan", "payments.card_record"}
    res.ok("сборка писем ничего не отправляет: notify_paid, letter_*, _payment_letter, _settle_now, card_*",
           not (builders & senders), sorted(builders & senders))
    res.ok("outbox раньше db.connect у 7 мест оплаты и 6 мест письма с нотой",
           OUTBOX_HOLDERS <= set(boxed), sorted(OUTBOX_HOLDERS - set(boxed)))
    res.check("отправка внутри with db.connect — только названные исключения",
              [b for b in bad if b not in MAIL_IN_TX], [])
    res.check("исключения живые (нет устаревших строк)", sorted(set(MAIL_IN_TX) - set(bad)), [])
    # пары: каждая поломка краснеет
    _, _, m = mail_check(_inject(trees, "main.py", "_maib_callback", "mail.send('a', 'b', 'c')"))
    res.ok("пара: mail.send в транзакции callback — красный", "main.py:_maib_callback → mail.send" in m, repr(m))
    _, _, m = mail_check(_inject(trees, "jobs.py", "settle_cards", "payments.send_paid([])"))
    res.ok("пара: send_paid в транзакции ежедневной задачи — красный",
           "jobs.py:settle_cards → payments.send_paid" in m, repr(m))
    _, _, m = mail_check(_swap(trees, "main.py", "payment_confirm"))
    res.ok("пара: connect раньше outbox («Подтвердить») — красный",
           "main.py:payment_confirm → payments.outbox" in m, repr(m))
    _, _, m = mail_check(_prepend(trees, "payments.py", "notify_paid", "mail.deliver(None)"))
    hit = {"main.py:_maib_callback → payments.notify_paid", "main.py:_returned → payments.notify_paid",
           "jobs.py:settle_cards → payments.notify_paid", "main.py:payment_confirm → payments.notify_paid",
           "main.py:payment_repeat → payments.notify_paid", "main.py:payment_check → main._settle_now",
           "main.py:_card_go → payments.notify_paid"}
    res.ok("пара: notify_paid начал отправлять — красные все места оплаты", hit <= set(m), sorted(hit - set(m)))
    _, _, m = mail_check(_prepend(trees, "main.py", "_payment_letter", "mail.send('a', 'b', 'c')"))
    hit = {f"main.py:{h} → main._payment_letter" for h in ("pay_link_submit", "cont_note", "_group_submit",
                                                            "payment_new", "payment_link", "payment_mail")}
    res.ok("пара: сборка письма с нотой начала отправлять — красные все шесть мест ноты",
           hit <= set(m), sorted(hit - set(m)))


# ---------- сеть maib — вне транзакции (шаг 4) ----------
# maib думает до maib.TIMEOUT (15 с) на вызов; клик «Plătește cu cardul» и нота картой из
# админки держали его под замком записи, и соседние записи (callback, /v1/license, кабинет)
# ждали с ними, а дольше 10 с — «database is locked» (test_maib.suite_slow). Сеть — только
# вне `with db.connect`: снимок (payments.card_plan) → commit → maib (card_ask) → короткая
# транзакция ответа (card_record, settle).

# Вызов maib внутри транзакции, оставленный НАМЕРЕННО, — с причиной. Сейчас таких нет.
NET_IN_TX: dict[str, str] = {}


def net_check(trees: dict[str, ast.Module]) -> tuple[set, list]:
    """(функции «модуль.имя», которые ходят в maib — сами или по цепочке, нарушения в SCOPE).
    Основа — функции maib.py, где есть urlopen (`_call`); дальше — все, кто их зовёт."""
    _, funcs = _funcs(trees)
    base = {f"maib.{fn.name}" for fname, _, fn, _ in funcs if fname == "maib.py"
            and any(isinstance(n, ast.Attribute) and n.attr == "urlopen" for n in ast.walk(fn))}
    reach = _closure(funcs, base)
    return reach, _inside(funcs, reach)


def suite_net_outside_tx(res: Result) -> None:
    """maib — вне транзакции: ни maib.* с сетью, ни функции, что их зовёт (по цепочке), внутри
    `with db.connect` в main.py, jobs.py, payments.py, кроме названных исключений; и пары."""
    trees = _trees()
    need = {"maib.py", "main.py", "jobs.py", "payments.py"}
    res.ok("исходники нашлись: maib.py, main.py, jobs.py, payments.py", need <= set(trees),
           sorted(need - set(trees)))
    reach, bad = net_check(trees)
    want = {"maib._call", "maib.token", "maib.create", "maib.info", "payments.card_ask", "main._card_go"}
    res.ok("сеть maib найдена: _call, token, create, info и по цепочке card_ask, _card_go",
           want <= reach, sorted(want - reach))
    quiet = {"maib.enabled", "maib.verify", "maib.ours", "payments.card_plan", "payments.card_record",
             "payments.settle", "payments.notify_paid", "main._settle_now", "main._payment_letter"}
    res.ok("без сети: enabled, verify, ours, снимок и запись ответа (card_plan, card_record, settle)",
           not (quiet & reach), sorted(quiet & reach))
    res.check("maib внутри with db.connect — только названные исключения",
              [b for b in bad if b not in NET_IN_TX], [])
    res.check("исключения живые (нет устаревших строк)", sorted(set(NET_IN_TX) - set(bad)), [])
    # пары: каждая поломка краснеет
    _, m = net_check(_inject(trees, "main.py", "_maib_callback", "maib.info('x')"))
    res.ok("пара: maib.info в транзакции callback — красный", "main.py:_maib_callback → maib.info" in m, repr(m))
    _, m = net_check(_inject(trees, "jobs.py", "settle_cards", "maib.info('x')"))
    res.ok("пара: maib.info в транзакции ежедневной задачи — красный",
           "jobs.py:settle_cards → maib.info" in m, repr(m))
    _, m = net_check(_inject(trees, "main.py", "_card_go", "payments.card_ask(plan)"))
    res.ok("пара: card_ask в транзакции кнопки карты — красный", "main.py:_card_go → payments.card_ask" in m, repr(m))
    _, m = net_check(_inject(trees, "main.py", "pay_link_submit", "_card_go(plan, 'program', back)"))
    res.ok("пара: кнопка карты целиком внутри транзакции страницы оплаты (как до шага 4) — красный",
           "main.py:pay_link_submit → main._card_go" in m, repr(m))
    _, m = net_check(_prepend(trees, "payments.py", "card_record", "maib.create(1, 'r', 'd')"))
    hit = {f"main.py:{h} → payments.card_record" for h in ("_card_go", "payment_new", "payment_link")}
    res.ok("пара: запись ответа начала звать maib — красные кнопка карты, нота и ссылка из админки",
           hit <= set(m), sorted(hit - set(m)))
