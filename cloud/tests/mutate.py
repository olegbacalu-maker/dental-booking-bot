"""Мутационные пары облака: каждая ломает одно свойство и требует, чтобы его набор покраснел.

    cd cloud && python tests/mutate.py            (на ПК Олега — TEMP на D:, как у прогона)

Это НЕ набор проверок, а инструмент рядом с ними — как `tests/mutate.py` движка; в `run_tests.py`
он не входит: проверяет он не сервер, а тесты. В CI — шаг «Мутация сторожей облака» работы `cloud`.

Зачем. Проверка поведения бывает зелёной и на сломанном коде — засев не дошёл до ветки, условие
слишком широкое, проверяется не то поле (`303` у формы на оба исхода). Отличить «держит» от «молчит»
можно одним способом: сломать свойство и увидеть красной ИМЕННО ту проверку, что его держит
(`mark` — кусок её названия; красная соседняя не в счёт: её мог уронить сам слом).

Настоящее дерево не трогается: `cloud/` (без `.venv`) и то, что наборы читают из соседей
(`bot/`, `tests/fixtures/`, `docs/site/`), копируются во временную папку; слом пишется в КОПИЮ,
наборы идут из неё (`harness.ROOT` — родитель `cloud/` копии), после каждой пары файл копии
возвращается байт в байт. Сервер наборы поднимают тем же интерпретатором, что запустил скрипт.

Пары кабинета SMS (05.11) жили вне репозитория (`sandbox\\sms-cabinet\\mutate_cabinet.py`) и
гонялись руками; перенесены 07.11 вместе с парами акта акцепта кабинета (`web.cont_terms`).
⚠️ Место слома ищется ТОЧНЫМ текстом и обязано встретиться ровно один раз: правка, которая
сдвинула текст, краснеет здесь «место не найдено» — поправить строку пары, не удалять её.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TESTS = pathlib.Path(__file__).resolve().parent
CLOUD = TESTS.parent
ROOT = CLOUD.parent
# что наборы читают за пределами cloud/ (harness.FIX, load_by_path движка, страницы сайта)
NEIGHBOURS = ("bot", "tests/fixtures", "docs/site")
SKIP = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".pytest_cache")

# (что ломается, файл в cloud/, было, стало, наборы, кусок названия проверки, которая обязана покраснеть)
MUTATIONS = [
    # --- кабинет SMS (05.11) ---
    ("одно зачисление при callback + /pay/ok: settle забыл, что попытка уже зачтена",
     "app/payments.py",
     "    counted = bool(att[\"counted\"]) if att is not None else payment[\"paid_via\"] == CARD\n",
     "    counted = False\n",
     ["test_sms_cabinet.suite_cabinet"], "зачисление ОДНО"),
    ("замена ноты шлёт письмо (кабинет): письмо только у новой, не у заменённой",
     "app/routes_cont.py",
     "            if outcome != payments.EXISTS:\n                # новая нота — письмом и при карте",
     "            if outcome == payments.CREATED:\n                # новая нота — письмом и при карте",
     ["test_sms_cabinet.suite_replace"], "письмо с новой нотой ушло"),
    ("замена ноты шлёт письмо (программа): created только у новой",
     "app/routes_program.py",
     "            created = outcome != payments.EXISTS\n",
     "            created = outcome == payments.CREATED\n",
     ["test_sms_cabinet.suite_replace", "test_sms.suite_send"], "нота заменена"),
    ("нота SMS первой на /plata: карточка абонемента снова сверху",
     "app/views.py",
     "sms_notes_block(list(sms_notes), action, card_on) + card, msg=msg,",
     "card + sms_notes_block(list(sms_notes), action, card_on), msg=msg,",
     ["test_sms_cabinet.suite_plata"], "нота SMS — первой"),
    # --- акт акцепта при оплате из кабинета (07.11, web.cont_terms) ---
    ("кабинет снова не пишет акт: только terms_at",
     "app/web.py",
     "        terms_mod.record(con, cid, terms_mod.CURRENT,",
     "        (lambda *a, **k: None)(con, cid, terms_mod.CURRENT,",
     ["test_terms.suite_cabinet_act"], "акт source=pay"),
    ("акт на каждую галочку, а не один на ноту",
     "app/web.py",
     "    if not (payments.mark_terms(con, note) or fresh):\n",
     "    if not (payments.mark_terms(con, note) or True):\n",
     ["test_terms.suite_cabinet_act"], "второго акта нет"),
    ("нота админки без отметки: новизну галочки потеряли — акта нет",
     "app/routes_cont.py",
     "outcome != payments.EXISTS or not prior[\"terms_at\"]",
     "outcome != payments.EXISTS",
     ["test_terms.suite_cabinet_act"], "галочка к ноте админки"),
    ("общая нота: акт только плательщику, не каждой клинике строк",
     "app/web.py",
     "if note[\"kind\"] == payments.CABINET\n",
     "if False\n",
     ["test_terms.suite_cabinet_act"], "по акту на каждую клинику строк"),
]

RUNNER = ("import importlib, sys\n"
          "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
          "sys.path.insert(0, 'tests')\n"
          "from harness import run\n"
          "sys.exit(run([(s, getattr(importlib.import_module(s.split('.')[0]), s.split('.')[1])) "
          "for s in sys.argv[1:]]))\n")


def _copy(dst: pathlib.Path) -> pathlib.Path:
    shutil.copytree(CLOUD, dst / "cloud", ignore=SKIP)
    for rel in NEIGHBOURS:
        if (ROOT / rel).is_dir():
            shutil.copytree(ROOT / rel, dst / rel, ignore=SKIP)
    return dst / "cloud"


def _run(cloud: pathlib.Path, suites: list) -> tuple[int, str]:
    env = dict(os.environ, PYTHONUTF8="1")
    p = subprocess.run([sys.executable, "-c", RUNNER, *suites], cwd=str(cloud), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=900)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    bad = 0
    # места слома — до копии и прогонов: устаревшая пара видна сразу, а не через десять минут
    for name, rel, old, _new, _suites, _mark in MUTATIONS:
        n = (CLOUD / rel).read_text(encoding="utf-8").replace("\r\n", "\n").count(old)
        if n != 1:
            print(f"✗ {name}: место слома в {rel} встретилось {n} раз, нужно ровно 1")
            bad += 1
    if bad:
        print(f"УСТАРЕЛО ПАР: {bad}")
        return 1
    with tempfile.TemporaryDirectory(prefix="dp_cloud_mut_") as tmp:
        cloud = _copy(pathlib.Path(tmp))
        for name, rel, old, new, suites, mark in MUTATIONS:
            f = cloud / rel
            raw = f.read_bytes()
            f.write_bytes(raw.decode("utf-8").replace("\r\n", "\n").replace(old, new).encode("utf-8"))
            try:
                code, out = _run(cloud, suites)
            finally:
                f.write_bytes(raw)
            red = [ln.strip()[:120] for ln in out.splitlines() if ln.strip().startswith("✗")]
            hit = any(mark in ln for ln in red)
            ok = code != 0 and hit
            bad += 0 if ok else 1
            print(f"{'ok' if ok else '✗ '} {name}: код {code}, красных {len(red)}, "
                  f"нужная проверка {'красная' if hit else 'НЕ красная — сторож слепой'}")
            if not ok:
                print("\n".join("      " + ln for ln in (red[:5] or out.splitlines()[-15:])))
    print(f"все {len(MUTATIONS)} мутаций красные" if not bad else f"СЛЕПЫХ: {bad} из {len(MUTATIONS)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
