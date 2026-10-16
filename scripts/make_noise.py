# -*- coding: utf-8 -*-
"""Плитка зерна для стиля «Sticlă» — `bot/app/static/img/noise.png` (16.10).

    python scripts\\make_noise.py            сгенерировать (перезаписывает)

⛔ Не в CI и не в `.\\dev test`: нужен Edge и пакеты websocket-client, Pillow,
numpy в СИСТЕМНОМ Python (в .venv-desktop ничего не ставить — это окружение
сборки). Запускается ОДИН РАЗ: результат лежит в репозитории и едет в exe
папкой static целиком.

Зачем картинкой, а не SVG-фильтром на странице. `feTurbulence` живым
фильтром пересчитывается на каждом кадре и на каждой поверхности — на канве
дня (перерисовка каждые 12 с) это цена без выгоды. Статичная плитка 128×128
— одна текстура на весь экран, браузер её только повторяет. ⛔ SVG как файл
статики не принимается никогда (документ со скриптами, см. core/theme.py),
поэтому PNG.

Как делается. Headless Edge рисует 128×128 `feTurbulence type=fractalNoise
baseFrequency=.85 numOctaves=3 stitchTiles=stitch` (шов повторения ровный),
обесцвечивает `feColorMatrix saturate 0` и отдаёт кадр по CDP. Дальше
картинка переводится в ЗЕРНО С НУЛЕВЫМ СРЕДНИМ: серый 128 становится
прозрачным, темнее — чёрным с альфой по удалению от середины, светлее —
белым. Так плитка под `opacity: var(--noise-a)` не затемняет и не
осветляет фон в среднем — только добавляет фактуру; серая плитка под той же
прозрачностью сдвинула бы яркость всей страницы на 6%.
"""
from __future__ import annotations

import base64
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from odo_shots import CDP, start_edge  # noqa: E402

OUT = ROOT / "bot" / "app" / "static" / "img" / "noise.png"
SIZE = 128
# ⛔ Свой порт отладки: 9337–9353 заняты соседними стендами; запуск на занятом
# МОЛЧА подключается к чужому браузеру.
PORT = 9360

HTML = f"""<!doctype html><html><body style="margin:0;background:#808080">
<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" style="display:block">
<filter id="n" x="0" y="0" width="100%" height="100%">
  <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="3" stitchTiles="stitch" seed="7"/>
  <feColorMatrix type="saturate" values="0"/>
</filter>
<rect width="{SIZE}" height="{SIZE}" filter="url(#n)"/>
</svg></body></html>"""


def main() -> int:
    import numpy as np
    from PIL import Image
    import io

    profile = os.path.join(tempfile.gettempdir(), "dp-edge-noise")
    proc, ws = start_edge(profile, port=PORT)
    try:
        cdp = CDP(ws)
        cdp.cmd("Page.enable")
        cdp.cmd("Emulation.setDeviceMetricsOverride", width=SIZE, height=SIZE,
                deviceScaleFactor=1, mobile=False)
        cdp.cmd("Page.navigate", url="data:text/html;charset=utf-8," + urllib.parse.quote(HTML))
        cdp.wait_event("Page.loadEventFired", timeout=15)
        cdp.drain(0.8)
        data = cdp.cmd("Page.captureScreenshot", format="png",
                       clip={"x": 0, "y": 0, "width": SIZE, "height": SIZE, "scale": 1})["data"]
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    grey = np.asarray(Image.open(io.BytesIO(base64.b64decode(data))).convert("L"), dtype=np.int16)
    if grey.shape != (SIZE, SIZE):
        raise SystemExit(f"кадр {grey.shape}, ждали {SIZE}×{SIZE}")
    spread = int(grey.max() - grey.min())
    if spread < 40:
        raise SystemExit(f"шум не нарисовался: разброс яркости {spread}")
    # зерно с нулевым средним: знак — цвет, удаление от середины — альфа
    mid = int(np.median(grey))
    dev = grey - mid
    rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    rgba[..., :3] = np.where(dev[..., None] >= 0, 255, 0)
    # растянуть так, чтобы самое сильное отклонение дало альфу 255
    scale = 255.0 / max(1, int(np.abs(dev).max()))
    rgba[..., 3] = np.clip(np.abs(dev) * scale, 0, 255).astype(np.uint8)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(OUT, optimize=True)
    print(f"записано {OUT} ({OUT.stat().st_size} б), медиана {mid}, разброс {spread}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
