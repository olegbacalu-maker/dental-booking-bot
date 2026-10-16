"""Правило SMS (S2): сегменты и номер — по общему вектору с сервером.

Модуль `app/core/sms_rule.py` грузится по пути, как `rsa_verify` в
test_license_verify: он обязан жить без импортов проекта, и голая загрузка это
проверяет заодно. Векторы `tests/fixtures/sms/` читает и прогон сервера
(`cloud/tests/test_sms_rule.py`) против своей копии правила: программа
показывает клинике число сегментов, сервер по своему счёту списывает пакет, и
расходиться им не на чем, кроме этого файла.

⭐ Кроме случаев — покрытие: каждая причина отказа, каждый мобильный префикс,
каждый знак расширения и каждая граница 160/70 имеют свой вектор. Новая
причина в коде без вектора краснеет здесь, а не молчит.
"""
import ast
import importlib.util
import json
import sys

from harness import BOT, ROOT, Result

FIX = ROOT / "tests" / "fixtures" / "sms"
MODULE = BOT / "app" / "core" / "sms_rule.py"
ALLOWED_IMPORTS = {"__future__", "re"}


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sr = _load("sms_rule", MODULE)


def _cases(name: str) -> list:
    return json.loads((FIX / name).read_text(encoding="utf-8"))["cases"]


def _text(case: dict) -> str:
    """Строка или список кусков: строка либо [строка, сколько раз]."""
    t = case["text"]
    return t if isinstance(t, str) else "".join(p if isinstance(p, str) else p[0] * p[1] for p in t)


def suite_parts(res: Result) -> None:
    cases = _cases("parts.json")
    res.ok("вектор сегментов нашёлся и не пуст", len(cases) >= 20, f"случаев: {len(cases)}")
    for c in cases:
        res.check(f"сегменты: {c['name']}", sr.parts(_text(c)),
                  (c["encoding"], c["units"], c["segments"]))
    res.check("таблицы GSM: 127 знаков основной (без ESC) и 9 расширения",
              (len(sr.GSM_BASIC), len(sr.GSM_EXT)), (127, 9))
    res.check("в векторе обе кодировки", sorted({c["encoding"] for c in cases}), sorted([sr.GSM7, sr.UCS2]))
    in_gsm = "".join(_text(c) for c in cases if c["encoding"] == sr.GSM7)
    res.check("каждый знак расширения есть в GSM-векторе", sorted(sr.GSM_EXT - set(in_gsm)), [])
    for enc in (sr.GSM7, sr.UCS2):
        edge = {(c["units"], c["segments"]) for c in cases if c["encoding"] == enc}
        one, multi = sr.SINGLE[enc], sr.MULTI[enc]
        res.ok(f"{enc}: граница одной SMS ({one} — 1, {one + 1} — 2) есть в векторе",
               {(one, 1), (one + 1, 2)} <= edge, repr(sorted(edge)))
        res.ok(f"{enc}: граница куска ({2 * multi} — 2, {2 * multi + 1} — 3) есть в векторе",
               {(2 * multi, 2), (2 * multi + 1, 3)} <= edge, repr(sorted(edge)))


def suite_phones(res: Result) -> None:
    cases = _cases("phones.json")
    res.ok("вектор номеров нашёлся и не пуст", len(cases) >= 20, f"случаев: {len(cases)}")
    for c in cases:
        want = (c["number"], "") if "number" in c else ("", c["reason"])
        res.check(f"номер {c['raw']!r}", sr.phone(c["raw"]), want)
    reasons = {c["reason"] for c in cases if "reason" in c}
    res.check("у каждой причины отказа есть вектор, и других причин в векторе нет",
              sorted(reasons), sorted(sr.REASONS))
    prefixes = {c["number"][:2] for c in cases if "number" in c}
    res.check("у каждого мобильного префикса есть вектор", sorted(sr.MOBILE - prefixes), [])


def suite_pure(res: Result) -> None:
    """Без импортов проекта, без диска и окружения — прогон сервера зовёт его копию так же."""
    res.ok("модуль правила нашёлся", MODULE.is_file(), str(MODULE))
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    res.check("импорты — только из разрешённого списка", sorted(imported - ALLOWED_IMPORTS), [])
    res.ok("нет относительных импортов проекта",
           not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree)))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    res.ok("ни open, ни __file__, ни environ", not ({"open", "__file__"} & names or "environ" in attrs))
