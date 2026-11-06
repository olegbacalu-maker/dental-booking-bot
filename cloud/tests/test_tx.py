"""Транзакции оплаты картой (30.10, ревью): разбор исходников `ast`, сервер не поднимается.

settle — только под замком записи с начала (`db.connect(immediate=True)`). Отложенная
транзакция WAL, которая уже прочитала, при записи сразу получает «database is locked»,
если соседка успела закоммитить: busy timeout устаревший снимок не ждёт. maib почти разом
шлёт callback и возвращает браузер на /pay/ok — вторая ветка падала 500 (test_maib.suite_race).
Тест гонки держит это, пока внутри транзакции есть пауза (письмо); сторож — всегда.

С 06.11 то же правило — для КАЖДОЙ транзакции, которая пишет (suite_write_lock, в конце файла):
500 «database is locked» на /v1/license в бою — та же отложенная транзакция, не про оплату.
"""
import ast
import copy
import re

from harness import CLOUD, Result

# Кто держит settle своей транзакцией — по ним видно, что обход нашёл то, что должен
# (список ВКЛЮЧАЕТ требование: переименуют — красное «найдены», а не тихий ноль)
HOLDERS = {"_maib_callback", "_returned", "payment_check", "settle_cards",
           "card_go", "payment_new", "payment_link", "payment_confirm", "payment_repeat"}
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
    res.ok("исходники нашлись: роутеры оплаты, кабинета, web.py, jobs.py, payments.py",
           {"routes_pay.py", "routes_admin_pay.py", "routes_cont.py", "web.py", "jobs.py", "payments.py"}
           <= set(trees), sorted(trees))
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

# main.py, роутеры routes_*.py и их общие помощники web.py (03.11, разнос main.py) — по имени
# файла, не списком: новый роутер мимо сторожа не пройдёт
def in_scope(fname: str) -> bool:
    """Область сторожей писем и сети maib — ВСЯ cloud/app (06.11). До того — main.py, роутеры,
    web.py, jobs.py, payments.py: транзакции sms.py и trial.py стояли мимо, и тревога Олегу из
    отправки SMS шла под замком записи незамеченной. Файл не из области молча зеленеет — поэтому
    области-списка нет."""
    return True


# Отправляющие сами по себе; `send` без модуля — mail.send, переданный параметром (jobs, sms)
SEND_BASE = {"mail.send", "mail.deliver"}

# Где письма собираются в транзакции и уходят через outbox — 7 мест оплаты решения Р4:
# callback, возврат браузера, ежедневная задача, «Проверить» (_settle_now), «Подтвердить»,
# «Зачесть повторный», кнопка карты (_card_go); и письмо с нотой (шаг 4): страница оплаты,
# кабинет, общая нота, «Выставить ноту», «Ссылка на карту», «Письмо» из админки; нота SMS из
# кабинета (05.11, cont_sms_note). С 06.11 — и все остальные письма облака: пробный из формы,
# программы и кабинета, «Adaugă clinică», нота SMS из программы, файл письмом из админки (после
# выдачи и кнопкой), тревоги Олегу из отправки SMS, уведомления о доставке и опроса.
# Список ВКЛЮЧАЕТ требование — переименуют, и «найдены» покраснеет, а не позеленеет тихо.
OUTBOX_HOLDERS = {"_maib_callback", "_returned", "settle_cards", "payment_check", "payment_confirm",
                  "payment_repeat", "card_go", "pay_link_submit", "cont_note", "cont_sms_note", "_group_submit",
                  "payment_new", "payment_link", "payment_mail",
                  "trial_submit", "_trial_program", "cont_register_submit", "cont_add_submit", "_sms_order",
                  "clinic_issue", "clinic_email", "submit", "recheck", "poll"}

# Отправка внутри транзакции, оставленная НАМЕРЕННО, — «файл:функция → вызов», с причиной.
# Сейчас таких нет. До 06.11 их было девять (не письма об оплате: нота SMS из программы, пробный из
# формы / программы / кабинета, «Adaugă clinică», файл письмом из админки, письмо о сроке задачи):
# все вынесены за commit — письмо собирается в транзакции, уходит после неё (payments.outbox,
# mail.deliver), как письма оплаты с 30.10.
MAIL_IN_TX: dict[str, str] = {}


def _key(call: ast.Call, stem: str, mods: set) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in mods:
        return f"{f.value.id}.{f.attr}"
    if isinstance(f, ast.Name):
        return f"{stem}.{f.id}"
    return None


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _walk(node: ast.AST, w, out: list, texts: list | None = None) -> None:
    """(вызов, ближайший `with db.connect` или None), без вложенных def. Элементы `with` ПОСЛЕ
    db.connect выходят РАНЬШЕ commit — они внутри транзакции; до него — снаружи (outbox).
    `texts` — туда же строковые литералы (литерал, with): SQL записи ищет write_check."""
    if isinstance(node, _DEFS):
        return
    if isinstance(node, ast.With) and (conn := _connect(node)) is not None:
        after = False
        for item in node.items:
            _walk(item.context_expr, node if after else w, out, texts)
            after = after or item.context_expr is conn
        for stmt in node.body:
            _walk(stmt, node, out, texts)
        return
    if isinstance(node, ast.Call):
        out.append((node, w))
    if texts is not None and isinstance(node, ast.Constant) and isinstance(node.value, str):
        texts.append((node, w))
    for child in ast.iter_child_nodes(node):
        _walk(child, w, out, texts)


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
    """Нарушения «файл:функция → вызов»: вызов из `reach` внутри `with db.connect` в области (in_scope)."""
    return sorted({f"{fname}:{fn.name} → {k}" for fname, _, fn, found in funcs if in_scope(fname)
                   for _, w, k in found if w is not None and k in reach})


def mail_check(trees: dict[str, ast.Module]) -> tuple[set, dict, list]:
    """(отправляющие функции «модуль.имя», {функция: [строки with, где outbox раньше
    db.connect]}, нарушения «файл:функция → вызов» в области). Отправляющая — та, что зовёт
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


def _where(trees: dict, func: str) -> str:
    """Файл, где определена функция: маршруты и помощники живут по роутерам (03.11)."""
    return next(f for f, tree in trees.items() for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func)


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
    """Письма — после commit: ни mail.send, ни отправляющей функции внутри `with db.connect`
    нигде в cloud/app (с 06.11 — все письма облака, не только оплата), кроме названных исключений
    (их нет); и пары."""
    trees = _trees()
    need = {"routes_pay.py", "routes_admin_pay.py", "routes_cont.py", "web.py", "routes_program.py", "routes_admin.py",
            "jobs.py", "payments.py", "license.py", "sms.py", "mail.py"}
    res.ok("исходники нашлись: роутеры, web.py, jobs.py, payments.py, license.py, sms.py, mail.py",
           need <= set(trees), sorted(need - set(trees)))
    senders, boxed, bad = mail_check(trees)
    want = {"mail.send", "mail.deliver", "payments.send_paid", "payments.outbox", "sms.low_letters",
            "sms.float_check", "jobs.daily"}
    res.ok("отправляющие найдены: mail.send/deliver, send_paid, outbox, письма задачи (low_letters, "
           "float_check, daily)", want <= senders, sorted(want - senders))
    builders = {"payments.notify_paid", "license.letter_latest", "sms.letter_pack", "sms.letter_name",
                "web.payment_letter", "routes_admin_pay._settle_now", "payments.card_plan", "payments.card_record",
                "trial.submit", "trial.letter", "account.register", "account.add_clinic", "routes_cont._added_letter",
                "web.sms_note_letter", "sms.alarm_letter", "sms._accepted", "sms._fix_segments", "sms.apply",
                "jobs._one"}
    res.ok("сборка писем ничего не отправляет: notify_paid, letter_*, payment_letter, _settle_now, card_*, "
           "заявка и клиника кабинета (submit, register, add_clinic), _added_letter, sms_note_letter, "
           "тревога SMS (alarm_letter и кто её зовёт), письмо о сроке (_one)",
           not (builders & senders), sorted(builders & senders))
    res.ok("outbox раньше db.connect у 7 мест оплаты, 7 мест письма с нотой и 10 мест остальных писем",
           OUTBOX_HOLDERS <= set(boxed), sorted(OUTBOX_HOLDERS - set(boxed)))
    res.check("отправка внутри with db.connect — только названные исключения",
              [b for b in bad if b not in MAIL_IN_TX], [])
    res.check("исключения живые (нет устаревших строк)", sorted(set(MAIL_IN_TX) - set(bad)), [])
    # пары: каждая поломка краснеет
    _, _, m = mail_check(_inject(trees, "routes_pay.py", "_maib_callback", "mail.send('a', 'b', 'c')"))
    res.ok("пара: mail.send в транзакции callback — красный", "routes_pay.py:_maib_callback → mail.send" in m, repr(m))
    _, _, m = mail_check(_inject(trees, "jobs.py", "settle_cards", "payments.send_paid([])"))
    res.ok("пара: send_paid в транзакции ежедневной задачи — красный",
           "jobs.py:settle_cards → payments.send_paid" in m, repr(m))
    _, _, m = mail_check(_swap(trees, "routes_admin_pay.py", "payment_confirm"))
    res.ok("пара: connect раньше outbox («Подтвердить») — красный",
           "routes_admin_pay.py:payment_confirm → payments.outbox" in m, repr(m))
    _, _, m = mail_check(_prepend(trees, "payments.py", "notify_paid", "mail.deliver(None)"))
    hit = {"routes_pay.py:_maib_callback → payments.notify_paid", "routes_pay.py:_returned → payments.notify_paid",
           "jobs.py:settle_cards → payments.notify_paid", "routes_admin_pay.py:payment_confirm → payments.notify_paid",
           "routes_admin_pay.py:payment_repeat → payments.notify_paid",
           "routes_admin_pay.py:payment_check → routes_admin_pay._settle_now",
           "web.py:card_go → payments.notify_paid"}
    res.ok("пара: notify_paid начал отправлять — красные все места оплаты", hit <= set(m), sorted(hit - set(m)))
    _, _, m = mail_check(_prepend(trees, "web.py", "payment_letter", "mail.send('a', 'b', 'c')"))
    hit = {f"{_where(trees, h)}:{h} → web.payment_letter" for h in ("pay_link_submit", "cont_note", "_group_submit",
                                                            "payment_new", "payment_link", "payment_mail")}
    res.ok("пара: сборка письма с нотой начала отправлять — красные все шесть мест ноты",
           hit <= set(m), sorted(hit - set(m)))
    # пары 06.11: письма вне оплаты — заявка, кабинет, задача, SMS
    _, _, m = mail_check(_inject(trees, "sms.py", "submit", "mail.send('a', 'b', 'c')"))
    res.ok("пара: mail.send в транзакции отправки SMS (sms.py — в области) — красный",
           "sms.py:submit → mail.send" in m, repr(m))
    _, _, m = mail_check(_inject(trees, "jobs.py", "daily", "mail.deliver(letter)"))
    res.ok("пара: mail.deliver в транзакции ежедневной задачи — красный", "jobs.py:daily → mail.deliver" in m, repr(m))
    _, _, m = mail_check(_inject(trees, "routes_program.py", "_sms_order", "mail.send(c['email'], 'a', 'b')"))
    res.ok("пара: mail.send в транзакции ноты SMS из программы (как до 06.11) — красный",
           "routes_program.py:_sms_order → mail.send" in m, repr(m))
    _, _, m = mail_check(_swap(trees, "routes_public.py", "trial_submit"))
    res.ok("пара: connect раньше outbox у формы пробного — красный",
           "routes_public.py:trial_submit → payments.outbox" in m, repr(m))
    _, _, m = mail_check(_prepend(trees, "trial.py", "submit", "mail.send('a', 'b', 'c')"))
    hit = {"routes_public.py:trial_submit → trial.submit", "routes_program.py:_trial_program → trial.submit",
           "routes_cont.py:cont_register_submit → account.register", "routes_cont.py:cont_add_submit → account.add_clinic"}
    res.ok("пара: trial.submit снова отправляет — красные форма, программа, регистрация кабинета, «Adaugă clinică»",
           hit <= set(m), sorted(hit - set(m)))
    _, _, m = mail_check(_prepend(trees, "license.py", "letter_latest", "mail.deliver(None)"))
    hit = {"routes_admin.py:clinic_issue → license.letter_latest", "routes_admin.py:clinic_email → license.letter_latest",
           "routes_public.py:trial_submit → trial.letter", "routes_program.py:_trial_program → trial.letter",
           "routes_cont.py:cont_register_submit → trial.letter"}
    res.ok("пара: сборка письма о лицензии начала отправлять — красные выдача и кнопка админки, три двери пробного",
           hit <= set(m), sorted(hit - set(m)))
    _, _, m = mail_check(_prepend(trees, "sms.py", "alarm_letter", "mail.send('a', 'b', 'c')"))
    hit = {"sms.py:submit → sms.alarm_letter", "sms.py:submit → sms._accepted", "sms.py:recheck → sms.apply",
           "sms.py:poll → sms.apply", "sms.py:float_check → sms.alarm_letter"}
    res.ok("пара: тревога Олегу снова отправляет сама — красные отправка SMS, уведомление, опрос, баланс",
           hit <= set(m), sorted(hit - set(m)))
    _, _, m = mail_check(_prepend(trees, "jobs.py", "_one", "send('a', 'b', 'c')"))
    res.ok("пара: письмо о сроке снова уходит из _one (send параметром) — красный",
           "jobs.py:daily → jobs._one" in m, repr(m))
    _, _, m = mail_check(_prepend(trees, "routes_cont.py", "_added_letter", "mail.send('a', 'b', 'c')"))
    res.ok("пара: письмо новой клинике кабинета снова отправляет само — красный",
           "routes_cont.py:cont_add_submit → routes_cont._added_letter" in m, repr(m))
    _, _, m = mail_check(_prepend(trees, "web.py", "sms_note_letter", "mail.send('a', 'b', 'c')"))
    hit = {"routes_program.py:_sms_order → web.sms_note_letter", "routes_cont.py:cont_sms_note → web.sms_note_letter"}
    res.ok("пара: сборка письма с нотой SMS начала отправлять — красные программа и кабинет",
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
    """(функции «модуль.имя», которые ходят в maib — сами или по цепочке, нарушения в области).
    Основа — функции maib.py, где есть urlopen (`_call`); дальше — все, кто их зовёт."""
    _, funcs = _funcs(trees)
    base = {f"maib.{fn.name}" for fname, _, fn, _ in funcs if fname == "maib.py"
            and any(isinstance(n, ast.Attribute) and n.attr == "urlopen" for n in ast.walk(fn))}
    reach = _closure(funcs, base)
    return reach, _inside(funcs, reach)


def suite_net_outside_tx(res: Result) -> None:
    """maib — вне транзакции: ни maib.* с сетью, ни функции, что их зовёт (по цепочке), внутри
    `with db.connect` нигде в cloud/app, кроме названных исключений (их нет); и пары."""
    trees = _trees()
    need = {"maib.py", "routes_pay.py", "routes_admin_pay.py", "routes_cont.py", "web.py", "jobs.py", "payments.py"}
    res.ok("исходники нашлись: maib.py, роутеры оплаты, кабинета, web.py, jobs.py, payments.py", need <= set(trees),
           sorted(need - set(trees)))
    reach, bad = net_check(trees)
    want = {"maib._call", "maib.token", "maib.create", "maib.info", "payments.card_ask", "web.card_go"}
    res.ok("сеть maib найдена: _call, token, create, info и по цепочке card_ask, _card_go",
           want <= reach, sorted(want - reach))
    quiet = {"maib.enabled", "maib.verify", "maib.ours", "payments.card_plan", "payments.card_record",
             "payments.settle", "payments.notify_paid", "routes_admin_pay._settle_now", "web.payment_letter"}
    res.ok("без сети: enabled, verify, ours, снимок и запись ответа (card_plan, card_record, settle)",
           not (quiet & reach), sorted(quiet & reach))
    res.check("maib внутри with db.connect — только названные исключения",
              [b for b in bad if b not in NET_IN_TX], [])
    res.check("исключения живые (нет устаревших строк)", sorted(set(NET_IN_TX) - set(bad)), [])
    # пары: каждая поломка краснеет
    _, m = net_check(_inject(trees, "routes_pay.py", "_maib_callback", "maib.info('x')"))
    res.ok("пара: maib.info в транзакции callback — красный", "routes_pay.py:_maib_callback → maib.info" in m, repr(m))
    _, m = net_check(_inject(trees, "jobs.py", "settle_cards", "maib.info('x')"))
    res.ok("пара: maib.info в транзакции ежедневной задачи — красный",
           "jobs.py:settle_cards → maib.info" in m, repr(m))
    _, m = net_check(_inject(trees, "web.py", "card_go", "payments.card_ask(plan)"))
    res.ok("пара: card_ask в транзакции кнопки карты — красный", "web.py:card_go → payments.card_ask" in m, repr(m))
    _, m = net_check(_inject(trees, "routes_pay.py", "pay_link_submit", "web.card_go(plan, 'program', back)"))
    res.ok("пара: кнопка карты целиком внутри транзакции страницы оплаты (как до шага 4) — красный",
           "routes_pay.py:pay_link_submit → web.card_go" in m, repr(m))
    _, m = net_check(_prepend(trees, "payments.py", "card_record", "maib.create(1, 'r', 'd')"))
    hit = {f"{_where(trees, h)}:{h} → payments.card_record" for h in ("card_go", "payment_new", "payment_link")}
    res.ok("пара: запись ответа начала звать maib — красные кнопка карты, нота и ссылка из админки",
           hit <= set(m), sorted(hit - set(m)))


# ---------- транзакция, которая пишет, — под замком записи с начала (06.11) ----------
# Бой, 06.11: 500 на GET /v1/license — «database is locked». Программа на старте шлёт три запроса
# разом; license_renew шёл отложенной транзакцией: прочёл клинику, потом писал след запроса. SQLite
# у транзакции, которая УЖЕ читает, замок записи не ждёт (busy timeout — только до первого чтения):
# сосед держит замок или успел закоммитить — отказ сразу. Отсюда правило: `with db.connect`, в
# котором есть запись, открыт с immediate=True. Запись — SQL-литерал INSERT / UPDATE / DELETE /
# REPLACE или вызов функции, которая пишет на чужом `con` (сама или по цепочке). Транзакции, где
# запись стоит первой, отложенными были безопасны (замок берётся с ожиданием) — правило одно на
# всех: «сперва запись» молча кончается с первой добавленной выше строкой чтения.
# Живой тест — tests/test_lock.py (сосед держит замок, запрос обязан ждать).
# ⚠️ Чего сторож не видит: SQL, собранный не литералом (переменная модуля, строка, начатая
# не-литералом), и вызов функции, пришедшей параметром (`send`).

WRITE_SQL = re.compile(r"^\s*(INSERT\s+(OR\s+\w+\s+)?INTO|UPDATE\s+(OR\s+\w+\s+)?\w+\s+SET|DELETE\s+FROM"
                       r"|REPLACE\s+INTO)\b", re.I)
SQL = "SQL"          # метка записи литералом — в нарушении «файл:функция → SQL»

# Кто пишет на чужом `con` — по ним видно, что обход нашёл то, что должен (список ВКЛЮЧАЕТ
# требование: переименуют — красное «найдены», а не тихий ноль)
WRITE_NAMES = {"db.audit", "fleet.touch", "terms.record", "paylink.create", "contlink.create", "sms.ensure",
               "sms.view", "sms.ledger", "license.issue", "license.renew_token", "payments.settle",
               "payments.create", "receipts.ensure", "trial.submit", "emailconf.issue", "account.detach"}
# Кто только читает: цепочка не должна разрастись до «пишут все»
READ_NAMES = {"web.clinic", "web.payment", "sms.account", "sms.balance", "sms.states", "sms.blocked",
              "terms.headers", "fleet.of_clinic", "payments.of_clinic", "payments.debt_of", "account.clinics"}
# Чьи транзакции переведены на замок с начала 06.11 — у каждой пара «без immediate — красный»
WRITE_HOLDERS = {"license_renew", "_sms_clinic", "submit", "descarca", "_cont_dashboard", "cont_edit",
                 "cont_receipt", "cont_sms_form", "login", "trial_decline", "clinic_new", "sms_export",
                 "sms_test", "clinic_edit", "clinic_issue", "clinic_tier", "account_detach", "payment_receipt",
                 "payment_reject", "daily", "clinic_email"}
# Чьи транзакции только читают и остаются отложенными: правило — не «immediate везде»
READ_HOLDERS = {"clinics", "clinic_card", "audit_log", "issue_file", "email_confirm_page"}

# Пишущая транзакция, оставленная отложенной НАМЕРЕННО, — «файл:функция → первая запись», с причиной.
# Сейчас таких нет. До 06.11 их было четыре (письмо о сроке задачи, «Au rămas N SMS», тревога о
# балансе sms.md, «отправить файл письмом» админки): письмо уходило ВНУТРИ транзакции ДО первой
# записи, и замок с начала держал бы запись всего сервера на время SMTP. Письма вынесены за commit
# (mail.deliver после транзакции: отправить → отметить) — причина исчезла, транзакции под замком.
DEFERRED_WRITE: dict[str, str] = {}


def _aliases(tree: ast.Module, mods: set) -> dict:
    """Имя в файле → модуль облака: `from . import login as elogin` зовёт login под другим именем."""
    out = {m: m for m in mods}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and not node.module:
            for a in node.names:
                if a.name in mods:
                    out[a.asname or a.name] = a.name
    return out


def _wkey(call: ast.Call, stem: str, names: dict) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in names:
        return f"{names[f.value.id]}.{f.attr}"
    if isinstance(f, ast.Name):
        return f"{stem}.{f.id}"
    return None


def write_check(trees: dict[str, ast.Module]) -> tuple[set, dict, list]:
    """(пишущие «модуль.имя», {функция: [(файл, строка, immediate)]} — её `with db.connect` с
    записью, нарушения «файл:функция → первая запись» — такие with без immediate=True).
    Пишущая — функция, у которой запись (SQL-литерал или вызов пишущей) стоит ВНЕ своего
    `with db.connect`, то есть на чужом `con`; дальше — все, кто так зовёт её, по цепочке."""
    mods = {f[:-3] for f in trees}
    funcs = []
    for fname, tree in trees.items():
        stem, names = fname[:-3], _aliases(tree, mods)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls: list = []
                texts: list = []
                for stmt in node.body:
                    _walk(stmt, None, calls, texts)
                marks = [(c.lineno, c.col_offset, _wkey(c, stem, names), w) for c, w in calls]
                marks += [(t.lineno, t.col_offset, SQL, w) for t, w in texts if WRITE_SQL.match(t.value)]
                funcs.append((fname, stem, node, sorted(marks, key=lambda m: m[:2])))
    writers = {SQL}
    while True:
        more = {f"{stem}.{fn.name}" for _, stem, fn, marks in funcs
                if any(w is None and k in writers for _, _, k, w in marks)}
        if more <= writers:
            break
        writers |= more
    held: dict = {}
    bad = []
    for fname, _, fn, marks in funcs:
        seen = set()
        for _, _, k, w in marks:
            if w is None or k not in writers or id(w) in seen:
                continue
            seen.add(id(w))
            imm = _immediate(_connect(w))
            held.setdefault(fn.name, []).append((fname, w.lineno, imm))
            if not imm:
                bad.append(f"{fname}:{fn.name} → {k}")
    return writers - {SQL}, held, sorted(bad)


def _deferred(trees: dict[str, ast.Module]) -> set:
    """Функции, у которых есть `with db.connect` без immediate (читающие и исключения)."""
    return {node.name for tree in trees.values() for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for w in ast.walk(node) if isinstance(w, ast.With) and (c := _connect(w)) is not None
            and not _immediate(c)}


def suite_write_lock(res: Result) -> None:
    """Каждый `with db.connect`, в котором есть запись, — immediate=True, кроме названных
    исключений; и пары: снятый immediate, запись в читающей транзакции, читатель стал писателем."""
    trees = _trees()
    need = {"routes_program.py", "routes_pay.py", "routes_cont.py", "routes_admin.py", "routes_admin_pay.py",
            "routes_public.py", "web.py", "jobs.py", "sms.py", "payments.py", "fleet.py", "db.py"}
    res.ok("исходники нашлись: роутеры, web.py, jobs.py, sms.py, payments.py, fleet.py, db.py",
           need <= set(trees), sorted(need - set(trees)))
    writers, held, bad = write_check(trees)
    res.ok("пишущие найдены: audit, touch, record, create ссылок, ensure, issue, settle и остальные",
           WRITE_NAMES <= writers, sorted(WRITE_NAMES - writers))
    res.ok("читающие не записаны в пишущие: clinic, payment, balance, states, headers…",
           not (READ_NAMES & writers), sorted(READ_NAMES & writers))
    res.ok("пишущие транзакции найдены у /v1/license, /v1/sms/*, кабинета, админки, задачи",
           WRITE_HOLDERS <= set(held), sorted(WRITE_HOLDERS - set(held)))
    res.ok("читающие транзакции остались отложенными (правило — не «immediate везде»): список клиник, "
           "карточка, журнал, файл выдачи, страница подтверждения ящика",
           READ_HOLDERS <= _deferred(trees) and not (READ_HOLDERS & set(held)),
           f"{sorted(READ_HOLDERS - _deferred(trees))} {sorted(READ_HOLDERS & set(held))}")
    res.check("with db.connect с записью без immediate=True — только названные исключения",
              [b for b in bad if b not in DEFERRED_WRITE], [])
    res.check("исключения живые (нет устаревших строк)", sorted(set(DEFERRED_WRITE) - set(bad)), [])
    # пары: каждая поломка краснеет
    for func in sorted(WRITE_HOLDERS):
        _, _, m = write_check(_strip(trees, func))
        res.ok(f"пара: без immediate у {func} — сторож красный",
               any(f":{func} → " in b for b in m if b not in DEFERRED_WRITE), repr(m))
    _, _, m = write_check(_inject(trees, "routes_admin.py", "clinics", "db.audit(con, 'a', 'b')"))
    res.ok("пара: запись в читающей транзакции списка клиник — красный",
           "routes_admin.py:clinics → db.audit" in m, repr(m))
    _, _, m = write_check(_inject(trees, "routes_admin.py", "clinics",
                                  "con.execute('UPDATE clinics SET name=name')"))
    res.ok("пара: UPDATE литералом в читающей транзакции — красный", "routes_admin.py:clinics → SQL" in m, repr(m))
    _, _, m = write_check(_prepend(trees, "web.py", "clinic", "con.execute('DELETE FROM audit')"))
    hit = {"routes_admin.py:clinic_card → web.clinic", "routes_admin.py:clinic_document_file → web.clinic"}
    res.ok("пара: читатель web.clinic начал писать — красные читающие транзакции, что его зовут",
           hit <= set(m), sorted(hit - set(m)))
