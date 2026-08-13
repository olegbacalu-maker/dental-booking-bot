"""Проверка сторожей на слом: каждое правило `test_structure` обязано краснеть.

    D:\\DentProject\\app\\.venv-desktop\\Scripts\\python.exe tests\\mutate.py

Это НЕ набор проверок, а инструмент рядом с ними — как `smoke_exe.py`. В
`run_tests.py` он не входит: проверяет он не программу, а тесты, и меняется
только вместе с ними.

Зачем. Проверки в `test_structure` устроены как «нарушителей не нашлось», и
такая проверка зелена не только когда всё хорошо, но и когда она сломана —
опечатка в имени узла, неверный путь, слишком узкое условие. Отличить одно от
другого можно единственным способом: нарушить правило и убедиться, что стало
красным. Ровно та же логика, что у `r.status == 303` — код один на оба исхода,
поэтому смотреть надо не на него.

Настоящее дерево не трогается: `bot\\` копируется во временную папку, нарушение
дописывается в КОПИЮ, а `test_structure.BOT` перевешивается на неё. Дописанный
код никогда не исполняется — проверки разбирают синтаксис, не запускают его,
поэтому мутация может звать функции, которые в том файле не импортированы.

Добавил правило в `test_structure` — добавь сюда строку. Если забудешь, скрипт
скажет об этом сам: он сверяет список мутаций со списком проверок в обе стороны.
"""
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_structure  # noqa: E402
from harness import BOT, Result  # noqa: E402

# По одной строке на каждую проверку в suite, в том же порядке:
#   (кусок названия проверки, куда править, что сделать)
# Файл — путь от bot/. None вместо файла означает особый случай: пустое дерево.
# Что сделать: строка — ДОПИСАТЬ в конец; пара («что было», «чем заменить») —
# ЗАМЕНИТЬ первое вхождение. Замена нужна там, где нарушение состоит в
# исчезновении кода: дописыванием переименование не изобразить.
MUTATIONS = [
    # Канарейка. Проверяется не правилом, а отсутствием исходников: если обход
    # однажды перестанет находить файлы, все остальные правила станут зелёными
    # разом, и упасть должно ровно здесь.
    ("исходники нашлись", None, None),
    ("__file__", "app/db.py",
     "\n_mut = __file__\n"),
    ("__package__", "app/engine.py",
     "\n_mut = __package__ + '.telegram'\n"),
    ("роль не сравнивается", "app/modules/stats/routes.py",
     "\ndef _mut(u):\n    return u.get('role') == 'director'\n"),
    # Переименование того, за чем правило следит. Единственная мутация-замена:
    # приписать сюда нечего, нарушение — в ИСЧЕЗНОВЕНИИ имени `save_user`.
    ("не протух", "app/core/auth.py",
     ("def save_user(", "def store_user(")),
    ("отпечаток", "app/modules/schedule/routes.py",
     "\nasync def _mut(uid):\n    save_user(uid, name='x', role='medic')\n"),
    ("paths/dpapi/envfile", "app/paths.py",
     "\nfrom . import db  # noqa\n"),
    ("не импортирует main", "app/core/visits.py",
     "\nfrom app import main  # noqa\n"),
    # Очередная страница со своей вёрсткой, забывшая заполнитель шрифта. Ровно
    # так и выглядела бы поломка: страница на месте, разметка цела, шрифт не
    # тот — и никакой запрос этого не отличит.
    ("объявляет шрифт", "app/modules/qr/routes.py",
     "\n_MUT = \"\"\"<style>body{font-family:'Inter',sans-serif}</style>\"\"\"\n"),
    # Очередной экран, попросивший знак у Windows. Ломается ИМЕННО строкой
    # интерфейса, а не комментарием: комментарии и docstring'и правило
    # пропускает намеренно, и мутация комментарием позеленела бы, ничего
    # не проверив.
    ("не просит знаки у Windows", "app/modules/qr/routes.py",
     "\n_MUT_GLYPH = \"<button>\\U0001f5a8 Printeaza</button>\"\n"),
    # Вызов _ic без импорта. Ловится только так: на демо-профиле такой вызов
    # часто стоит в ветке, которая не исполняется (`if meta.get('room')`),
    # страница открывается, и ни один запрос ошибки не видит — а у клиники
    # с заполненным полем падает. Ровно это случилось 08-11 со списком врачей.
    # ⚠️ Ломается УДАЛЕНИЕМ импорта, а не добавлением вызова: почти каждый
    # модуль интерфейса `_ic` уже импортирует, и дописанный вызов нарушением
    # не был бы — мутация позеленела бы, ничего не проверив.
    ("_ic — тот его импортирует", "app/core/visits.py",
     ("_age, _ic, _initials", "_age, _initials")),
    # Заголовок раздела, собранный обычной строкой вместо f-строки. Ломается
    # ДОБАВЛЕНИЕМ (в отличие от соседа): нарушение — это сам литерал, а не
    # отсутствие импорта, и в чистом дереве такого литерала нет ни одного.
    ("_ic не остаётся текстом", "app/modules/qr/routes.py",
     "\n_MUT_RAW = \"<h2>{_ic('wifi')} Titlu</h2>\"\n"),
]


def _run(bot: pathlib.Path) -> Result:
    """Прогнать набор по указанному дереву исходников."""
    test_structure.BOT = bot
    res = Result()
    test_structure.suite(res)
    return res


def _copy(dst: pathlib.Path) -> pathlib.Path:
    shutil.copytree(BOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def main() -> int:
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_mut_"))
    bad: list[str] = []
    try:
        # 1. Исходное дерево обязано быть зелёным — иначе сравнивать не с чем.
        clean = _run(_copy(base / "clean"))
        live = [label for label, _ in clean.failed]
        print(f"{'дерево без правок':<34} {live or 'зелено'}")
        if live:
            bad.append("набор красный ДО мутаций — сначала почини правило")

        # 2. Список мутаций и список проверок обязаны совпадать. Проверка без
        #    мутации — сторож, которого не проверяли; мутация без проверки —
        #    хвост от переименованного правила.
        labels = clean.passed
        for label in labels:
            if not any(exp in label for exp, _, _ in MUTATIONS):
                bad.append(f"нет мутации для проверки «{label}»")
        for exp, _, _ in MUTATIONS:
            if not any(exp in label for label in labels):
                bad.append(f"мутация «{exp}» не совпала ни с одной проверкой")

        # 3. Каждое правило ломаем и ждём красного.
        for i, (expect, rel, patch) in enumerate(MUTATIONS):
            work = base / f"m{i}"
            if rel is None:
                work.mkdir()                    # особый случай: пустое дерево
            else:
                f = _copy(work) / rel
                text = f.read_text(encoding="utf-8")
                if isinstance(patch, tuple):
                    was, now = patch
                    if was not in text:
                        # мутация описывает код, которого уже нет: сама протухла
                        bad.append(f"мутация «{expect}»: в {rel} нет {was!r}")
                    text = text.replace(was, now, 1)
                else:
                    text += patch
                f.write_text(text, encoding="utf-8")
            got = [label for label, _ in _run(work).failed]
            hit = [g for g in got if expect in g]
            print(f"{'  сломано: ' + expect:<34} "
                  f"{'красное — ' + hit[0] if hit else 'ЗЕЛЁНОЕ (сторож молчит)'}")
            if not hit:
                bad.append(f"правило «{expect}» не заметило нарушения")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        test_structure.BOT = BOT                # вернуть на настоящее дерево

    print()
    for line in bad:
        print(f"  ✗ {line}")
    print("все сторожа краснеют" if not bad else
          f"неисправных сторожей: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
