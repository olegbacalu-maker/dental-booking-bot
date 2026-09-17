"""icons.ts для React-клиента — ИЗ layout._I, а не руками.

  python scripts/gen_icons.py          пересобрать frontend/src/components/icons.ts
  python scripts/gen_icons.py --check  только проверить, что файл свежий

У иконок один владелец — `core/layout._I` (правило карты: ничего графического
от Windows, значок = иконка currentColor, и она сама берёт цвет клиники).
Второй список в TypeScript разошёлся бы с первым при первой же правке, поэтому
файл ПРОИЗВОДНЫЙ: правится источник, потом пересборка. Свежесть держит
test_structure (разбором ast, без Node), мутация — в mutate.py.

Зависимостей нет намеренно — только стандартная библиотека, как у tests/.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # консоль бывает cp1251

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "bot" / "app" / "core" / "layout.py"
OUT = ROOT / "frontend" / "src" / "components" / "icons.ts"


def icons_from_tree(tree: ast.Module) -> dict[str, str] | None:
    """{имя: внутренняя разметка svg} из литерала `_I = {...}`; None — словаря
    нет (якорь правила пропал)."""
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "_I" and isinstance(n.value, ast.Dict)):
            out = {}
            for k, v in zip(n.value.keys, n.value.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)):
                    out[k.value] = v.value
            return out
    return None


def render(icons: dict[str, str]) -> str:
    lines = [
        "// Сгенерировано scripts/gen_icons.py из bot/app/core/layout.py (_I).",
        "// НЕ ПРАВИТЬ РУКАМИ: правится источник, потом `python scripts/gen_icons.py`.",
        "// Внутренняя разметка <svg> — те же path'ы, что рисует серверный _ic().",
        "export const ICONS = {",
    ]
    for name in icons:      # порядок источника, чтобы диффы читались
        lines.append(f"  {json.dumps(name)}: {json.dumps(icons[name], ensure_ascii=False)},")
    lines += ["} as const", "", "export type IconName = keyof typeof ICONS", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    icons = icons_from_tree(ast.parse(LAYOUT.read_text(encoding="utf-8")))
    if not icons:
        print(f"в {LAYOUT} нет словаря _I")
        return 1
    text = render(icons)
    if "--check" in argv:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if old == text:
            print(f"icons.ts свежий ({len(icons)} иконок)")
            return 0
        print("icons.ts устарел — пересобрать: python scripts/gen_icons.py")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"{OUT.relative_to(ROOT)}: {len(icons)} иконок")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
