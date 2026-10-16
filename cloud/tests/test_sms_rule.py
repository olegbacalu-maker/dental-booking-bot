"""Правило SMS (S2): копия сервера против общего вектора и против копии программы.

Сервер списывает пакет по СВОЕМУ счёту сегментов (`app/sms_rule.py`), а
клиника видит счёт программы (`bot/app/core/sms_rule.py`). Импортов из bot/ у
сервера нет, поэтому правило живёт дважды и сходится в двух местах:
- общий вектор `tests/fixtures/sms/` — его же читает прогон движка
  (`tests/test_sms_rule.py`);
- сверка копий: модуль программы чистый и грузится по пути (как
  `license_renew` в test_renew), и обе копии обязаны ответить одинаково на
  тысячи текстов и номеров, которых в векторе нет.
"""
import json
import random
import sys

from harness import CLOUD, ROOT, Result, load_by_path

sys.path.insert(0, str(CLOUD))
from app import sms_rule as sr  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sms"
bot = load_by_path("sms_rule_bot", ROOT / "bot" / "app" / "core" / "sms_rule.py")


def _cases(name: str) -> list:
    return json.loads((FIX / name).read_text(encoding="utf-8"))["cases"]


def _text(case: dict) -> str:
    """Строка или список кусков: строка либо [строка, сколько раз]."""
    t = case["text"]
    return t if isinstance(t, str) else "".join(p if isinstance(p, str) else p[0] * p[1] for p in t)


def suite_vectors(res: Result) -> None:
    parts, phones = _cases("parts.json"), _cases("phones.json")
    res.ok("векторы сегментов и номеров нашлись и не пусты", len(parts) >= 20 and len(phones) >= 20,
           f"сегментов: {len(parts)}, номеров: {len(phones)}")
    for c in parts:
        res.check(f"сегменты: {c['name']}", sr.parts(_text(c)), (c["encoding"], c["units"], c["segments"]))
    for c in phones:
        want = (c["number"], "") if "number" in c else ("", c["reason"])
        res.check(f"номер {c['raw']!r}", sr.phone(c["raw"]), want)
    res.check("у каждой причины отказа есть вектор, и других причин в векторе нет",
              sorted({c["reason"] for c in phones if "reason" in c}), sorted(sr.REASONS))
    res.check("у каждого мобильного префикса есть вектор",
              sorted(sr.MOBILE - {c["number"][:2] for c in phones if "number" in c}), [])


def suite_twins(res: Result) -> None:
    names = ("GSM7", "UCS2", "GSM_BASIC", "GSM_EXT", "SINGLE", "MULTI", "COUNTRY", "MOBILE", "REASONS")
    res.check("постоянные копий совпадают", [n for n in names if getattr(sr, n) != getattr(bot, n)], [])

    rnd = random.Random(16_10_2026)
    letters = sorted(sr.GSM_BASIC | sr.GSM_EXT) + list(
        "ăâîșțşţĂÂÎȘȚжёЖЁ—–„”’… \t`‍️\f\x1b") + ["\U0001F600", "\U0001F44D"]
    texts = []
    for _ in range(3000):
        n = rnd.choice((rnd.randint(0, 12), rnd.randint(150, 165), rnd.randint(300, 470), rnd.randint(60, 210)))
        pool = letters if rnd.random() < 0.3 else sorted(sr.GSM_BASIC | sr.GSM_EXT)
        texts.append("".join(rnd.choice(pool) for _ in range(n)))
    diff = [t for t in texts if sr.parts(t) != bot.parts(t)]
    res.ok("сегменты: копии согласны на 3000 случайных текстов", not diff,
           f"{len(diff)} расхождений, первое: {diff[:1]!r}")

    # Начало национального номера — из каждого класса: мобильный, левобережье,
    # стационарный, прочий, лишний ноль; дальше случайные цифры около восьми.
    starts = ("69", "60", "80", "77", "22", "53", "90", "63", "0", "")
    raws = [c["raw"] for c in _cases("phones.json")]
    for _ in range(4000):
        head = rnd.choice(("", "0", "+373", "373", "00373", "+373 0", "+", "00", "+40", "+7"))
        body = rnd.choice(starts) + "".join(rnd.choice("0123456789") for _ in range(rnd.randint(0, 9)))
        noise = "".join(rnd.choice(" -.() \t/+a") for _ in range(rnd.randint(0, 2)))
        cut = rnd.randint(0, len(body))
        raws.append(head + body[:cut] + noise + body[cut:])
    diff = [r for r in raws if sr.phone(r) != bot.phone(r)]
    res.ok("номера: копии согласны на 4000 случайных строк", not diff,
           f"{len(diff)} расхождений, первое: {diff[:1]!r}")
    res.ok("случайные номера задели и приём, и все причины отказа",
           {sr.phone(r)[1] for r in raws} >= set(sr.REASONS) | {""},
           repr(sorted({sr.phone(r)[1] for r in raws})))
