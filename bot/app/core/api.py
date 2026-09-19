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

import hashlib
import json

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from .. import db
from .. import engine as eng
from .auth import _secret, auth_blocked, can, current_user, same_origin_post
from .layout import msg_json


# ---- живой канал ДАННЫМИ (C27.1) -------------------------------------------
# ⭐ Живой журнал держится ОДНИМ свойством: сервер отвечает «не менялось», пока
# состояние то же. У старого канала это держалось построением — `data-hash` у
# обёртки и `X-DP-Hash` фрагмента считались от ОДНОЙ строки разметки, второго
# рендера «для опроса» не существовало. Канал данных обязан унаследовать ровно
# это, иначе первый же опрос на неизменном дне вернёт «изменение», и React
# станет перерисовывать панель каждые 12 секунд на пустом месте — увидеть это
# можно, только простояв на странице полминуты.
# ⚠️ Имя запросного заголовка здесь БОЛЬШЕ НЕ ОБЪЯВЛЯЕТСЯ. `LIVE_HEADER =
# "x-dp-live"` стоял рядом и не читался ни одной строкой: константа с
# включающей полярностью, которая молча пережила бы переименование заголовка
# (правило «у списков-исключений есть полярность», CLAUDE.md). Живой опрос
# старой страницы разбирает свой заголовок там, где он ему нужен, —
# `schedule/routes._live_fragment` и `_live_stale`.
LIVE_TAG = "x-dp-hash"

# Какую поверхность сервер отдаёт по адресу экрана. ⛔ Ответ едет ЗАГОЛОВКОМ, а
# не полем `data`, и причина та же, что у `X-DP-V`: всё, что попадает в `data`,
# попадает в отпечаток. Положи поверхность туда — и включение флага у директора
# перерисовало бы панель, хотя в дне не изменилось ничего; а `?ui=legacy`,
# дописанный к адресу ОПРОСА, давал бы другой отпечаток того же дня.
# ⭐ Заголовок едет и на 204: вкладка узнаёт об откате даже в тихий день, когда
# тела нет вовсе. Поле в `data` на 204 не приехало бы никогда.
LIVE_SURFACE = "X-DP-Surface"


def live_canon(data) -> str:
    """Канонические байты состояния — ЕДИНСТВЕННЫЙ вид, от которого считается
    отпечаток и который уезжает клиенту.

    ⛔ `sort_keys` обязателен: порядок ключей словаря в Python — это порядок
    вставки, и перестановка двух строк в сборке модели поменяла бы отпечаток,
    не тронув ни одного значения. ⛔ `separators` без пробелов и
    `ensure_ascii=False` — чтобы «тот же текст» давал те же байты независимо от
    настроек дампа в другом месте.
    """
    return json.dumps(data, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def live_hash(data) -> str:
    """Отпечаток состояния. ⛔ Считается ОТ ТОГО ЖЕ, что отправляется."""
    return hashlib.md5(live_canon(data).encode("utf-8")).hexdigest()


def live_envelope(screen: str, d, state: dict | None) -> dict:
    """Конверт живого состояния — ЕДИНСТВЕННОЕ место, где он собирается.

    ⛔ `live` — не отдельное утверждение, а ИМЯ ТОГО ЖЕ ФАКТА, что и состав:
    состояние либо есть целиком, либо его нет вовсе. Две независимые строки
    («поставить флаг» и «долить состояние») однажды разойдутся, и клиент
    получит `live:true` с пустотой — успешный ответ, по которому нечего
    нарисовать и непонятно, что делать. Так и было до 19.09.
    ⛔ Кто рисует экран, здесь НЕ спрашивается. Поверхность едет заголовком
    `X-DP-Surface` (разбор — рядом с константой): всё, что попадёт в `data`,
    попадёт и в отпечаток, а поверхность меняется не от дня, а от профиля.
    """
    out = {"screen": screen, "date": d.isoformat(), "live": state is not None}
    if state is not None:
        out.update(state)
    return out


def live_reply(request: Request, data, surface: str | None = None) -> Response:
    """Ответ живого канала: 204 «состояние прежнее» или 200 с состоянием.

    ⚠️ Сравнение идёт СВОИМ заголовком, а не ETag/304 — как у старого канала и
    по той же причине: у WebView2 и у туннеля свои кеши, и стандартную пару они
    вправе трактовать сами. Отсюда же `no-store`.
    ⚠️ `X-DP-V` несёт версию программы: после тихого обновления exe клиент
    видит чужую версию и перезагружается целиком, вместо того чтобы вклеивать
    новые данные в старый экран со старым кодом.
    ⚠️ `X-DP-Surface` — вторая половина отката, ровно по той же схеме: клиент
    видит, что по адресу теперь живёт не его поверхность, и перезагружается.
    Первая половина (205 старой вкладке на включение флага) живёт в
    `schedule/routes._live_stale` и сделана в C26.5.1.
    """
    h = live_hash(data)
    headers = {"X-DP-Hash": h, "X-DP-V": eng.APP_VERSION,
               "Cache-Control": "no-store"}
    if surface is not None:
        headers[LIVE_SURFACE] = surface
    if request.headers.get(LIVE_TAG) == h:
        return Response(status_code=204, headers=headers)
    # ⛔ Конверт — тот же `msg_json`, а не собранный по месту словарь: свой
    # второй конверт развёл бы разбор ответов у клиента ровно так же, как
    # второй словарь статусов разводит слова на экране.
    out = msg_json(True, data=data)
    out.headers.update(headers)
    return out


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
