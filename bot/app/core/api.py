"""Охрана и разбор запросов JSON API (`/api/*`, DentPilot 2.0).

Отдельная пара `api_guard` / `api_require` рядом с `_guard` / `require` из
core/auth. Те отвечают редиректом 303 — правильно для страниц и губительно для
fetch: браузер сходит за редиректом сам и вернёт клиенту 200 с HTML формы
входа. Экран показал бы пустоту вместо «сессия истекла», а регистратура решила
бы, что у пациента нет записей (блокер 3 аудита миграции). Здесь отказ — JSON
с кодом состояния: 401 не вошёл, 403 нет права или чужой Origin.

⛔ Существующие `_guard` и `require` на HTML-маршрутах не трогаются: одна
правка там задела бы все модули разом. Держит test_structure: маршрут под
`/api/` зовёт api_guard/api_require и никогда — их HTML-собратьев.
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import JSONResponse

from .. import db
from .auth import _secret, auth_blocked, can, current_user, same_origin_post
from .layout import msg_json


def api_guard(request: Request) -> JSONResponse | None:
    """Вошёл ли человек. Ветки те же, что у `_guard`, ответы — JSON.

    Без секрета `_guard` ведёт на установку PIN (SQLite) или на экран «файл
    битый»; API в обоих случаях отвечает 401 — клиент отправит человека на
    /admin/login, а тот сам покажет нужное. Облачный демо-режим без ключа
    (`_guard` пускает всех) повторяется как есть: иначе у демо React-экраны
    были бы закрыты при открытых HTML-страницах.
    ⚠️ Проверка Origin на изменяющих методах — та же, что у login/setup:
    кука SameSite=Lax чужой POST и так не понесёт, но один ответ на весь класс
    дешевле, чем помнить об этом в каждом маршруте. Без Origin (curl, тесты)
    — пропуск, как и там.
    """
    if not _secret():
        if auth_blocked() or db.IS_SQLITE:
            return msg_json(False, status=401)
    elif current_user(request) is None:
        return msg_json(False, status=401)
    if request.method not in ("GET", "HEAD") and not same_origin_post(request):
        return msg_json(False, status=403)
    return None


def api_require(request: Request, perm: str) -> JSONResponse | None:
    """Сперва вход, потом право — как `require`, но JSON: 403 с кодом
    no_access, тем же словом, что видит человек на странице."""
    if (deny := api_guard(request)) is not None:
        return deny
    if can(current_user(request), perm):
        return None
    return msg_json(False, "no_access", status=403)


async def api_body(request: Request) -> dict | None:
    """Тело запроса как словарь. None — не JSON или не объект; ответ 422
    строит вызывающий: код отказа у каждого экрана свой."""
    try:
        data = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None
