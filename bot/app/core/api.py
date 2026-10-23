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
from .auth import _secret, can, current_user, same_origin_post
from .layout import msg_json
from .visits import mine, my_scope


# ---- живой канал ДАННЫМИ (C27.1) -------------------------------------------
# ⭐ Живой журнал держится ОДНИМ свойством: сервер отвечает «не менялось», пока
# состояние то же. У старого канала (опрос страницы, снят 13.10) это держалось
# построением — `data-hash` у обёртки и `X-DP-Hash` фрагмента считались от
# ОДНОЙ строки разметки. Канал данных обязан держать ровно это, иначе первый
# же опрос на неизменном дне вернёт «изменение», и React станет перерисовывать
# панель каждые 12 секунд на пустом месте — увидеть это можно, только простояв
# на странице полминуты.
LIVE_TAG = "x-dp-hash"


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
    ⛔ Кто рисует экран, здесь НЕ спрашивается: всё, что попадёт в `data`,
    попадёт и в отпечаток, а состояние меняется от дня, а не от профиля.
    """
    out = {"screen": screen, "date": d.isoformat(), "live": state is not None}
    if state is not None:
        out.update(state)
    return out


def live_reply(request: Request, data) -> Response:
    """Ответ живого канала: 204 «состояние прежнее» или 200 с состоянием.

    ⚠️ Сравнение идёт СВОИМ заголовком, а не ETag/304 — как у старого канала и
    по той же причине: у WebView2 и у туннеля свои кеши, и стандартную пару они
    вправе трактовать сами. Отсюда же `no-store`.
    ⚠️ `X-DP-V` несёт версию программы: после тихого обновления exe клиент
    видит чужую версию и перезагружается целиком, вместо того чтобы вклеивать
    новые данные в старый экран со старым кодом. ⭐ Заголовок едет и на 204:
    вкладка узнаёт об обновлении даже в тихий день, когда тела нет вовсе.
    """
    h = live_hash(data)
    headers = {"X-DP-Hash": h, "X-DP-V": eng.APP_VERSION,
               "Cache-Control": "no-store"}
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

    Без секрета `_guard` ведёт на установку PIN или на экран «файл битый»;
    API в обоих случаях отвечает 401 — клиент отправит человека на
    /admin/login, а тот сам покажет нужное.
    ⚠️ Проверка Origin на изменяющих методах — та же, что у login/setup:
    кука SameSite=Lax чужой POST и так не понесёт, но один ответ на весь класс
    дешевле, чем помнить об этом в каждом маршруте. Без Origin (curl, тесты)
    — пропуск, как и там.
    """
    if not _secret():
        return msg_json(False, status=401)
    if current_user(request) is None:
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


# ---- журнал врача: только свои визиты (22.10, права врача) -------------------
# Две двери одного правила (`auth.schedule_scope` через `visits.my_scope`):
# команда К СТОЯЩЕМУ визиту спрашивает, чей он, по строке из базы; запись,
# заметка и перенос спрашивают, К КОМУ. Отказ — 403 `other_doctor`, тем же
# конвертом, что `no_access`. ⛔ Это последняя линия: клиент чужих визитов
# не получает вовсе (модели режутся по `mine`), но адрес набирается руками,
# а вкладка живёт долго. Правило `test_structure` «команда к визиту журнала
# спрашивает, чей он» требует `api_own_appt` у каждого маршрута команды.


def api_own_doctor(doctor: str) -> JSONResponse | None:
    """Запись, заметка или перенос к врачу `doctor`: 403 `other_doctor`, если
    журнал вошедшего не включает его (у врача — чужой, у учётки без врача —
    любой). None — можно, или врача такого нет и правило само ответит `bad`:
    кривой ввод остаётся кривым вводом, а не чужим врачом."""
    scope = my_scope()
    if scope is None or (scope and (doctor == scope or doctor not in eng.DOCTORS)):
        return None
    return msg_json(False, "other_doctor", status=403)


async def api_own_appt(appt_id: int) -> JSONResponse | None:
    """Команда к стоящему визиту (исход, комментарий, процедура, перенос,
    отметка звонка): 403 `other_doctor`, если визит не из журнала вошедшего.
    None — свой, полное право, или визита нет: «нет такого» (`mv_gone`)
    говорит правило, как и раньше.
    ⛔ Спрашивается ДО правила и по строке из базы, а не по телу запроса: тело
    переноса называет, КУДА двигать, а не чей визит."""
    scope = my_scope()
    if scope is None:
        return None
    cur = await db.appointment_brief(appt_id)
    if cur is None or mine(cur, scope):
        return None
    return msg_json(False, "other_doctor", status=403)
