"""JSON API настроек (DentPilot 2.0): клиника, хаб, сеть, справка, часы,
услуги, вид клиники.

Правила те же, что у соседнего routes.py: `core`, `db`, `engine` — да,
`main.py` — нет. Проверки и слияние профиля берутся ИЗ routes.py, а не
переписываются: `_val_clinic`, `_val_hours`, `_val_services`, `_val_theme`,
`_finish_cfg`, `_set_lan`, `_logo_action`, `_hub_tiles` — единственные, кто
знает правило, а старая форма и новый экран правят ОДИН файл. Второй
экземпляр этой логики разошёлся бы с первым молча.

Адреса — от сущности, не от страницы (docs/dentpilot-2/api.md), и полным
путём, без prefix у роутера: карта экранов и сторож раскладки читают адрес
из декоратора.

⚠️ Две секции отдают HTML-куски: справка (ответы с иконками) и проза страницы
сети. Это ТЕКСТ СЕРВЕРА из тех же строк, что рисует старая страница, — не
данные пользователя и не «отрисовка страницы через API»: кнопки, состояния
и форму рисует клиент, сервер отдаёт только прозу, чтобы она не жила дважды.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile

from ... import db
from ... import engine as eng
from ... import update as upd
from ...core import theme
from ...core.api import api_body, api_guard, api_require
from ...core.auth import (PERM_SETTINGS, PERM_USERS, PIN_MAX, PIN_MIN, ROLE_LABEL,
                          _pin_rec, _set_auth_cookie, all_users, change_pin,
                          current_user)
from ...core.layout import (FEEDBACK_EMAIL, HOUR_MAX, HOUR_MIN, SETUP_HINT,
                            _DOW_FULL, _DOW_ORDER, msg_json, tg_refresh_meta)
from ...core.storage import _data_dir
from ...core.visits import SVC_PALETTE
from . import backup as bkp
from . import crypt, faq, lan
from .routes import (RESTART_NOTE, _PALETTE_RO, _apply_user, _drop_user,
                     _finish_cfg, _hub_tiles, _lan_available, _last_logins,
                     _logo_action, _set_lan, _val_clinic, _val_hours,
                     _val_services, _val_theme, restart_text)

router = APIRouter()


# ---------- клиника ----------

def _clinic_data() -> dict:
    cfg = eng.CONFIG
    addr = cfg.get("address") or {}
    return {
        "name": cfg.get("name", ""),
        "phone": cfg.get("phone", ""),
        "address": {"ro": addr.get("ro", ""), "ru": addr.get("ru", "")},
        # профиль ещё шаблонный (демо-данные): экран говорит об этом тем же
        # текстом, что и баннер каркаса, — источник у фразы один
        "template": bool(cfg.get("template")),
        "hint": f"{SETUP_HINT[0]} {SETUP_HINT[1]}{SETUP_HINT[2]}",
    }


@router.get("/api/settings/clinic")
async def api_clinic_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=_clinic_data())


@router.post("/api/settings/clinic")
async def api_clinic_save(request: Request):
    """Тот же путь, что у `POST /admin/settings/save part=clinic`: проверка,
    слияние с профилем, атомарная запись, обновление профиля бота. Отличие
    одно — ответ JSON вместо 303 с ?msg=."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_set", status=422)
    addr = body.get("address") if isinstance(body.get("address"), dict) else {}
    try:
        cfg = _finish_cfg(**_val_clinic({
            "name": body.get("name", ""), "phone": body.get("phone", ""),
            "address": {"ro": addr.get("ro", ""), "ru": addr.get("ru", "")}}))
    except ValueError as e:
        # _val_clinic называет виновное поле («name» / «phone») — оно уезжает
        # клиенту, чтобы подсветить именно его; прочие ValueError без поля
        field = str(e) if str(e) in ("name", "phone") else ""
        return msg_json(False, "bad_set", status=422, field=field)
    except (KeyError, TypeError):
        return msg_json(False, "bad_set", status=422)
    if eng.save_config(cfg) is not None:
        return msg_json(False, "save_err", status=500)
    tg_refresh_meta()   # имя и телефон уезжают и в профиль бота — как у формы
    return msg_json(True, "ok_set", data=_clinic_data())


# ---------- хаб ----------

@router.get("/api/settings/hub")
async def api_hub(request: Request):
    """Плитки хаба со строкой состояния кусками (текст / иконка / тон /
    точка цвета) — те же данные, из которых собрана старая страница."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data={"tiles": _hub_tiles()})


# ---------- сеть клиники ----------

def _lan_data() -> dict:
    on = lan.enabled()
    ip, url = lan.address(on)
    fw = lan.firewall_rule_ok() if on else None
    return {
        "enabled": on, "ip": ip, "port": lan.port(), "url": url, "firewall": fw,
        "blocks": {
            "intro": lan.intro_html(),
            "status": lan.status_html(on, ip, url),
            "firewall": lan.firewall_html() if (on and fw is False) else "",
            "tips": lan.tips_html() if on else "",
        },
    }


@router.get("/api/settings/lan")
async def api_lan_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not _lan_available():
        return msg_json(False, status=404)
    return msg_json(True, data=_lan_data())


@router.post("/api/settings/lan")
async def api_lan_save(request: Request):
    """Переключить доступ: тот же `_set_lan`, что у формы, и тот же
    `restart_app`. Форма отвечала страницей перезапуска; здесь — JSON с тем
    же текстом, и клиент показывает его вместо страницы."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not _lan_available():
        return msg_json(False, status=404)
    body = await api_body(request)
    mode = (body or {}).get("mode")
    if mode not in ("on", "off"):
        return msg_json(False, "bad_set", status=422, field="mode")
    if (err := _set_lan(mode)) is not None:
        return msg_json(False, err, status=500)
    auto = upd.restart_app() is None
    desktop = upd.is_desktop()
    return msg_json(True, "ok_set", data={
        "enabled": mode == "on", "restart": auto,
        "text": restart_text(auto) if desktop else "",
        "note": RESTART_NOTE if desktop else "",
    })


@router.post("/api/settings/lan/firewall")
async def api_lan_firewall(request: Request):
    """Запросить правило брандмауэра (UAC на экране этого ПК). `asked` —
    запрос показан, не «правило создано»: итог видно по следующему чтению."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not _lan_available():
        return msg_json(False, status=404)
    return msg_json(True, data={"asked": lan.request_firewall_rule()})


# ---------- шифрование картотеки ----------

def _crypt_data() -> dict:
    """Состояние раздела и его проза — те же куски, что у старой страницы.

    ⛔ Адрес печатного листа едет ОТ СЕРВЕРА, а не склеивается в браузере:
    страницу обслуживает он, и клиенту нечем проверить, что она там же.
    """
    st = crypt.state(_data_dir())
    return {"state": st, "blocks": crypt.blocks(st),
            "sheet": "/admin/settings/crypt/sheet"}


@router.get("/api/settings/crypt")
async def api_crypt_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=_crypt_data())


@router.post("/api/settings/crypt/prepare")
async def api_crypt_prepare(request: Request):
    """Приготовить ключ и отправить человека на лист. Та же `crypt.prepare`,
    что у формы, и тот же отказ второму нажатию.

    ⚠️ Заказа на диске этот вызов не оставляет — его кладёт галочка на самом
    листе. Ответ несёт АДРЕС листа, а не разметку: печать остаётся серверной.
    """
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    err = crypt.prepare(_data_dir())
    if err == "crypt_on":
        return msg_json(False, err, status=409)
    if err is not None:
        return msg_json(False, err, status=500)
    return msg_json(True, data={"sheet": "/admin/settings/crypt/sheet"})


@router.post("/api/settings/crypt/off")
async def api_crypt_off(request: Request):
    """Заказать расшифровку. Форма отвечала страницей перезапуска; здесь —
    JSON с тем же словом, и клиент показывает его вместо страницы."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if (err := crypt.turn_off(_data_dir())) is not None:
        return msg_json(False, err, status=500)
    auto = upd.restart_app() is None
    desktop = upd.is_desktop()
    return msg_json(True, "ok_set", data={
        "restart": auto,
        "text": f"{crypt.OFF_DONE} — {restart_text(auto)}" if desktop else "",
        "note": RESTART_NOTE if desktop else "",
    })


# ---------- справка ----------

@router.get("/api/settings/faq")
async def api_faq(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data={"items": faq.entries(), "contact": FEEDBACK_EMAIL})


# ---------- часы работы ----------

def _hours_data() -> dict:
    hours = eng.CONFIG.get("hours", {})
    return {
        "hours": {d: (list(hours[d]) if hours.get(d) else None) for d in _DOW_ORDER},
        "range": {"min": HOUR_MIN, "max": HOUR_MAX},
        "days": [{"key": d, "label": _DOW_FULL[d]} for d in _DOW_ORDER],
    }


@router.get("/api/settings/hours")
async def api_hours_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=_hours_data())


@router.post("/api/settings/hours")
async def api_hours_save(request: Request):
    """То же тело, что слал скрипт старой страницы (`{hours: {день: null |
    [от, до] | [от, до, пауза от, пауза до]}}`), та же `_val_hours`."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None or not isinstance(body.get("hours"), dict):
        return msg_json(False, "bad_set", status=422)
    try:
        cfg = _finish_cfg(hours=_val_hours(body))
    except (ValueError, KeyError, TypeError):
        return msg_json(False, "bad_set", status=422)
    if eng.save_config(cfg) is not None:
        return msg_json(False, "save_err", status=500)
    tg_refresh_meta()   # часы уезжают и в профиль бота — как у формы
    return msg_json(True, "ok_set", data=_hours_data())


# ---------- услуги ----------

_DURATIONS = (15, 30, 45, 60, 90, 120)      # те же, что в <select> старой таблицы


def _services_data() -> dict:
    """Услуги так, как их показывала старая таблица: цена строкой (двуязычная
    — её RO), длительность числом (60 по умолчанию), цвет ключом палитры или
    пусто, врачи списком id (пусто = все)."""
    cfg = eng.CONFIG
    rows = []
    for s in cfg["services"]:
        price = s.get("price", "")
        if isinstance(price, dict):
            price = price.get("ro", "")
        rows.append({
            "id": s["id"], "ro": s["ro"], "ru": s.get("ru", ""),
            "price": str(price or ""),
            "duration": int(s.get("duration") or 60),
            "color": s.get("color", "") if s.get("color") in SVC_PALETTE else "",
            "urgent": bool(s.get("urgent")),
            "docs": list(s.get("docs") or []),
        })
    return {
        "services": rows,
        "palette": dict(_PALETTE_RO),
        "durations": list(_DURATIONS),
        "doctors": [{"id": d["id"], "name": d["name"]} for d in cfg["doctors"]],
    }


@router.get("/api/settings/services")
async def api_services_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=_services_data())


@router.post("/api/settings/services")
async def api_services_save(request: Request):
    """Та же `_val_services`, что у формы: она ждёт врачей строкой через
    пробел и длительность строкой — как слал скрипт старой таблицы, так что
    список id и число приводятся к тому же виду до проверки."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    rows = body.get("services") if body else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return msg_json(False, "bad_set", status=422)
    prepared = []
    for r in rows:
        docs = r.get("docs", "")
        if isinstance(docs, list):
            docs = " ".join(str(x) for x in docs)
        dur = r.get("duration")
        prepared.append({**r, "docs": docs,
                         "duration": "" if dur in (None, "") else str(dur)})
    try:
        services, seq = _val_services({"services": prepared})
        cfg = _finish_cfg(services=services, seq=seq)
    except (ValueError, KeyError, TypeError, AttributeError):
        return msg_json(False, "bad_set", status=422)
    if eng.save_config(cfg) is not None:
        return msg_json(False, "save_err", status=500)
    tg_refresh_meta()   # услуги уезжают и в меню бота — как у формы
    return msg_json(True, "ok_set", data=_services_data())


# ---------- вид клиники ----------

def _theme_data() -> dict:
    """Стиль, цвет, логотип — и всё, что нужно предпросмотру: палитры
    считает СЕРВЕР (core/theme.py) и отдаёт готовыми, как и старой странице."""
    th = theme.current()
    preset_hex = [c for c, _ in theme.PRESETS]
    return {
        "style": th["style"], "primary": th["primary"],
        "custom": th["primary"] not in preset_hex,
        "styles": [{"key": k, "label": theme.STYLE_LABEL[k][0],
                    "hint": theme.STYLE_LABEL[k][1], "vars": dict(v)}
                   for k, v in theme.STYLES.items()],
        "presets": [{"hex": h, "name": n} for h, n in theme.PRESETS],
        "palettes": {st: {c: theme.palette(c, st) for c in preset_hex}
                     for st in theme.STYLES},
        "logo": theme.logo_url(), "logo_topbar": th["logo_topbar"],
        "logo_max_mb": theme.LOGO_MAX // (1024 * 1024),
    }


@router.get("/api/settings/theme")
async def api_theme_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=_theme_data())


@router.get("/api/settings/theme/palette")
async def api_theme_palette(request: Request, c: str = "", style: str = ""):
    """Палитра своего цвета для предпросмотра — тот же расчёт, что уедет в
    CSS при сохранении; клиент его не повторяет."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    rgb = theme.parse_hex(c)
    if rgb is None:
        return msg_json(False, "bad_set", status=422, field="primary")
    st = style if style in theme.STYLES else theme.DEFAULT_STYLE
    return msg_json(True, data=theme.palette(theme.to_hex(rgb), st))


@router.post("/api/settings/theme")
async def api_theme_save(request: Request):
    """Те же поля, что у формы (`style`, `primary` или `custom` + hex,
    `logo_topbar`), та же `_val_theme`."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_set", status=422)
    try:
        cfg = _finish_cfg(theme=_val_theme({
            "style": body.get("style", ""), "primary": str(body.get("primary") or ""),
            "custom": str(body.get("custom") or ""),
            "logo_topbar": bool(body.get("logo_topbar"))}))
    except ValueError as e:
        field = str(e) if str(e) in ("style", "primary") else ""
        return msg_json(False, "bad_set", status=422, field=field)
    except (KeyError, TypeError):
        return msg_json(False, "bad_set", status=422)
    if eng.save_config(cfg) is not None:
        return msg_json(False, "save_err", status=500)
    return msg_json(True, "ok_theme", data=_theme_data())


@router.post("/api/settings/theme/logo")
async def api_theme_logo(request: Request, file: UploadFile = File(...)):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    data = await file.read(theme.LOGO_MAX + 1)
    await file.close()
    code = _logo_action(data)
    ok = code == "ok_logo"
    return msg_json(ok, code, data=_theme_data() if ok else None,
                    status=200 if ok else (500 if code == "save_err" else 422))


@router.post("/api/settings/theme/logo/delete")
async def api_theme_logo_delete(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    code = _logo_action(None)
    ok = code == "no_logo"
    return msg_json(ok, code, data=_theme_data() if ok else None,
                    status=200 if ok else 500)


# ---------- безопасность: учётки и свой PIN ----------

# Отказ проверки — 422; спор с состоянием клиники (чужой PIN, последний
# директор, своя учётка, блокировка) — 409.
_USER_HTTP = {"bad_user": 422, "bad_pin": 422, "dup_user": 409, "last_dir": 409,
              "self_user": 409, "lock_pin": 409}


async def _security_data(me_id: str) -> dict:
    last = await _last_logins()
    return {
        "users": [{"id": u["id"], "name": u["name"], "role": u["role"],
                   "doctor_id": u.get("doctor_id", ""),
                   "last_login": last.get(u["id"], "")} for u in all_users()],
        "roles": dict(ROLE_LABEL),
        "doctors": [{"id": k, "name": v} for k, v in eng.DOCTORS.items()],
        "me": me_id,
        "pin": {"min": PIN_MIN, "max": PIN_MAX},
    }


def _me(request: Request) -> str:
    return str((current_user(request) or {}).get("id") or "")


@router.get("/api/settings/security")
async def api_security(request: Request):
    """Раздел есть только у клиники с PIN-файлом (в облаке людей нет)."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not _pin_rec():
        return msg_json(False, status=404)
    return msg_json(True, data=await _security_data(_me(request)))


@router.post("/api/settings/users")
async def api_user_save(request: Request):
    """Завести или поправить сотрудника — те же правила, что у формы
    (`_apply_user`): уникальный PIN, последний директор, длина PIN."""
    if (deny := api_require(request, PERM_USERS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_user", status=422)
    s = lambda k: str(body.get(k) or "")  # noqa: E731 — три вызова, не функция
    code = await _apply_user(s("uid"), name=s("name"), role=s("role"),
                             doctor_id=s("doctor_id"), pin=s("pin"))
    if code != "ok_user":
        return msg_json(False, code, status=_USER_HTTP.get(code, 422))
    return msg_json(True, code, data=await _security_data(_me(request)))


@router.post("/api/settings/users/{uid}/delete")
async def api_user_delete(request: Request, uid: str):
    if (deny := api_require(request, PERM_USERS)) is not None:
        return deny
    code = await _drop_user(_me(request), uid)
    if code != "ok_user":
        return msg_json(False, code, status=_USER_HTTP.get(code, 422))
    return msg_json(True, code, data=await _security_data(_me(request)))


@router.post("/api/settings/pin")
async def api_pin_change(request: Request):
    """Смена СВОЕГО PIN — та же `change_pin`, что у формы. Удача вращает ключ
    подписи, поэтому ответ несёт свежую куку: иначе следующий запрос этой же
    вкладки выкинул бы на вход."""
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_pin", status=422)
    s = lambda k: str(body.get(k) or "")  # noqa: E731
    code, who = await change_pin(s("old_pin"), s("new1"), s("new2"))
    if code != "ok_pin":
        return msg_json(False, code, status=_USER_HTTP.get(code, 422))
    return _set_auth_cookie(msg_json(True, code), who)


# ---------- копия ----------

@router.get("/api/settings/backup")
async def api_backup(request: Request):
    """Порог пароля и имя архива. Сама выгрузка остаётся за
    `POST /admin/backup/export`: файл идёт обычной формой, браузер скачивает
    ответ потоком, а отказ возвращается на страницу с ?msg=."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not (db.IS_SQLITE and bkp.available()):
        return msg_json(False, status=404)
    return msg_json(True, data={"min_pass": bkp.MIN_PASS, "filename": bkp.archive_name()})
