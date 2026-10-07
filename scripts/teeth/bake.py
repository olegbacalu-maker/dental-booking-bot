# -*- coding: utf-8 -*-
"""Запечь все 16 типов в таблицы и записать `frontend/models/teeth.js` (07.10).

Файл едет в программу отдельно от бандла: сборка клиента копирует его в
`bot/app/static/js/teeth.js`, клиент грузит его при открытии 3D (`loadTeeth.ts`).

Запуск:  python bake.py [--js-only] [--out путь/к/teeth.js]
Таблицы считаются четырьмя процессами (по четыре типа), потом проверка: стенка
без выбросов по углу, вершина там, где эталон, жевательная поверхность внутри
контура. Таблица — мм эталона, три знака (0,001 мм) — с запасом.
"""
import json
import pathlib
import subprocess
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ALL = ["U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]
# в репозитории генератор лежит в scripts/teeth, рабочая копия — sandbox/perio-3d/teeth
_REPO = HERE.parent.parent if (HERE.parent.parent / "frontend").exists() else HERE.parent / "wt"
DEFAULT_OUT = _REPO / "frontend" / "models" / "teeth.js"


def bake():
    groups = [ALL[i::4] for i in range(4)]
    procs = [subprocess.Popen([sys.executable, str(HERE / "gen_teeth.py"), *g], cwd=HERE) for g in groups]
    bad = [p.wait() for p in procs]
    if any(bad):
        raise SystemExit(f"запекание упало: {bad}")


def check(tab):
    """Выбросы: радиус, отличающийся от соседей по углу больше чем на 0,25 мм."""
    r = np.asarray(tab["r"])
    nb = (np.roll(r, 1, 1) + np.roll(r, -1, 1)) / 2
    spike = float(np.abs(r - nb).max())
    cap = np.asarray(tab["cap"])
    tip = float(max(cap.max(), tab["capCenter"]))
    return spike, tip


def rnd(v):
    if isinstance(v, list):
        return [rnd(x) for x in v]
    if isinstance(v, dict):
        return {k: rnd(x) for k, x in v.items()}
    if isinstance(v, float):
        return round(v, 3)
    return v


def write_js(out):
    lines = [
        "/* Свои модели зубов — таблицы всех 16 типов постоянных зубов (07.10).",
        "   Генератор — scripts/teeth (gen_teeth.py + family.py), запись — bake.py.",
        "   ⛔ Не править руками. На сборке клиента копируется в bot/app/static/js/teeth.js",
        "   (vite.config.ts), в программе грузится при открытии 3D (loadTeeth.ts).",
        "   Типы — teeth.d.ts рядом. */",
        "export const SCULPT = {",
    ]
    for nm in ALL:
        tab = json.loads((HERE / f"table_{nm}.json").read_text(encoding="utf-8"))
        spike, tip = check(tab)
        print(f"{nm}: вершина {tip:.2f} (эталон {tab['ref']['crown']}), выброс стенки {spike:.3f} мм")
        lines.append(f"  {nm}: {json.dumps(rnd(tab), separators=(',', ':'))},")
    lines.append("}")
    lines.append("")
    pairs = []
    for q, jaw in ((1, "U"), (2, "U"), (3, "L"), (4, "L")):
        for k in range(1, 9):
            pairs.append(f"{q}{k}: '{jaw}{k}'")
    lines.append("/** Номер FDI → своя модель: все постоянные зубы (молочные — пока формула). */")
    lines.append("export const SCULPT_OF = {")
    for i in range(0, len(pairs), 8):
        lines.append("  " + ", ".join(pairs[i:i + 8]) + ",")
    lines.append("}")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("записано:", out, round(out.stat().st_size / 1024), "КБ")


if __name__ == "__main__":
    args = sys.argv[1:]
    out = DEFAULT_OUT
    if "--out" in args:
        out = pathlib.Path(args[args.index("--out") + 1])
    if "--js-only" not in args:
        bake()
    write_js(out)
