"""JSON-дверь журнала: вход и выход без перезагрузки (B4.4, 16.10.2026).

Смена человека у стойки («Ieșire din cont» → PIN коллеги) до 16.10 шла
документами: выход на страницу входа, форма, редирект на `/admin` — и окно
программы гасло целиком три раза подряд (пустой лист, пустой каркас, панель),
ровно то мигание, которое B4 убрал у остальных переходов. Здесь те же два
действия отвечают конвертом, а экран PIN рисует клиент (`features/entry`).

⛔ Проверку PIN, счётчик неудач, паузу и запись в ленту делает `try_login`
из `routes.py` — ОДИН оракул на форму и на JSON. Второй, со своими ветками,
разошёлся бы с первым в том, кого пускать (поэтому и файл в `_LOGIN_OK`
теста раскладки — поимённо, как `routes.py`).
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ...core.api import api_body, api_guard
from ...core.auth import _as_user, client_peer, same_origin_post, _set_auth_cookie
from ...core.layout import msg_json
from .routes import LOGIN_BROKEN, LOGIN_OK, try_login

router = APIRouter()


@router.post("/api/auth/login")
async def api_login(request: Request):
    """Вход: `{"pin": …, "uid": …}` → кука вошедшего. Это сама дверь, куки
    ещё нет — поэтому единственный маршрут под `/api/` БЕЗ `api_guard`
    (`test_structure`, `_API_OPEN`). ⛔ Сверка Origin остаётся: чужой сайт в
    браузере клиники иначе перебирал бы PIN-ы и накручивал счётчик до
    блокировки — та же причина, что у формы (`same_origin_post`).

    Коды — те же слова, что видит форма входа: `login_bad` (422), `lock_pin`
    (423, `data.left` — секунды), `auth_broken` (409). ⚠️ 401 здесь не
    бывает намеренно: клиент на 401 уходит на страницу входа документом, а
    экран PIN обязан показать отказ на месте.
    """
    if not same_origin_post(request):
        return msg_json(False, status=403)
    body = await api_body(request) or {}
    outcome, who, lock = await try_login(str(body.get("pin") or "")[:64],
                                         str(body.get("uid") or "")[:32],
                                         client_peer(request))
    if outcome == LOGIN_BROKEN:
        return msg_json(False, "auth_broken", status=409)
    if outcome != LOGIN_OK:
        if lock:
            return msg_json(False, "lock_pin", data={"left": lock}, status=423)
        return msg_json(False, "login_bad", field="pin", status=422)
    # кука — ПОСЛЕ try_login (миграция v1→v2 меняет ключ подписи); в ответе
    # имя вошедшего ради проверок, оболочку клиент перечитает документом
    me = _as_user(who) if who else {"id": "admin", "name": ""}
    return _set_auth_cookie(msg_json(True, data={"uid": me["id"], "name": me["name"]}),
                            who)


@router.post("/api/auth/logout")
async def api_logout(request: Request):
    """Выход: кука снимается у браузера, как у `GET /admin/logout`; серверных
    сессий нет, гасить больше нечего. Под `api_guard`, как весь `/api/`: на
    истёкшую куку — 401, и клиент запирает экран так же, он и так снаружи."""
    if (deny := api_guard(request)) is not None:
        return deny
    resp = msg_json(True)
    resp.delete_cookie("admin_auth")
    return resp
