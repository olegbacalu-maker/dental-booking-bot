"""Клиент Google программы (client_id и секрет клиента «Desktop app») — откуда он берётся.

В собранном exe — только константа сборки `gclient_build.CLIENT`: её пишет scripts/embed_gclient.py
из файла вне репозитория (репозиторий публичный, а Google запрещает класть туда учётные данные клиента).
Вне exe — только JSON консоли по пути из DENTART_GOOGLE_CLIENT: прогон, `dev up`, опыт. Демо и серверный
запуск переменной не имеют — клиента нет, связь с Google там «не настроена». Как у ключа лицензии
(`license_state.keys_from`): в exe переменная не читается вовсе, её не подложить из dental.env.
"""
from __future__ import annotations

import os
import pathlib
import sys

from . import gauth

# Импорт статический: по нему PyInstaller кладёт константу в exe. Импорт по строке он не видит,
# и exe молча остался бы «не настроено» — этого не заметит ни один дымовой тест.
try:
    from . import gclient_build
except ImportError:
    gclient_build = None

ENV = "DENTART_GOOGLE_CLIENT"


def _built() -> gauth.Client | None:
    data = getattr(gclient_build, "CLIENT", None)
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
        return None
    secret = data.get("secret")
    return gauth.Client(data["id"], secret if isinstance(secret, str) else "")


def client_from(frozen: bool, env_value: str) -> gauth.Client | None:
    if frozen:
        return _built()
    path = (env_value or "").strip().strip("\"'")
    if not path:
        return None
    try:
        return gauth.client_of(pathlib.Path(path).read_bytes())
    except OSError:
        return None


def client() -> gauth.Client | None:
    """None — «не настроено»: экран прячет подключение, а не падает."""
    return client_from(bool(getattr(sys, "frozen", False)), os.environ.get(ENV, ""))
