"""Шрифт заставки — @font-face программы data-адресами (05.10.2026).

Заставку окна при запуске рисует оболочка Tauri (`shell/src/main.rs`,
страница `gen/ui/splash.html`); её собирает `shell/assets.py` и берёт
начертания отсюда, чтобы заставка оболочки и экраны программы шли одним
шрифтом. Страница прежней заставки окна pywebview (`page()`) снята
22.10.2026 вместе с окном.

⛔ Сервера у заставки нет: ни /static, ни шрифта по ссылке. Поэтому шрифт —
data-адресами, и только латиница: на заставке нет ни одной русской буквы, а
кириллические файлы шрифта — лишние 60 КБ.
⚠️ Модуль зовут без приложения (сборка оболочки): импорт — только `paths`
(слой предзагрузки, держит `test_structure`).
"""
from __future__ import annotations

import base64
import re

from . import paths

_FONT_FILES = ("inter-latin-ext.woff2", "inter-latin.woff2")


def _fonts() -> str:
    """@font-face программы (static/css/fonts.css) с файлами data-адресами.
    ⚠️ Пропажа файла заставку не роняет: слово нарисуется системным шрифтом."""
    try:
        css = paths.resource("static", "css", "fonts.css").read_text(encoding="utf-8")
    except OSError:
        return ""
    out = []
    for rule in re.findall(r"@font-face\{[^}]*\}", css):
        m = re.search(r"/static/fonts/([\w.-]+\.woff2)", rule)
        if not m or m.group(1) not in _FONT_FILES:
            continue
        try:
            data = paths.resource("static", "fonts", m.group(1)).read_bytes()
        except OSError:
            continue
        uri = "data:font/woff2;base64," + base64.b64encode(data).decode()
        out.append(rule.replace(f"/static/fonts/{m.group(1)}", uri))
    return "\n".join(out)
