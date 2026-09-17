"""JSON API настроек (DentPilot 2.0): клиника, хаб, сеть, справка, часы.

Правила те же, что у соседнего routes.py: `core`, `db`, `engine` — да,
`main.py` — нет. Проверки и слияние профиля берутся ИЗ routes.py, а не
переписываются: `_val_clinic`, `_val_hours`, `_finish_cfg`, `_set_lan`,
`_hub_tiles` — единственные, кто знает правило, а старая форма и новый экран
правят ОДИН файл. Второй экземпляр этой логики разошёлся бы с первым молча.

Адреса — от сущности, не от страницы (docs/dentpilot-2/api.md), и полным
путём, без prefix у роутера: карта экранов и сторож раскладки читают адрес
из декоратора.

⚠️ Две секции отдают HTML-куски: справка (ответы с иконками) и проза страницы
сети. Это ТЕКСТ СЕРВЕРА из тех же строк, что рисует старая страница, — не
данные пользователя и не «отрисовка страницы через API»: кнопки, состояния
и форму рисует клиент, сервер отдаёт только прозу, чтобы она не жила дважды.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import engine as eng
from ... import update as upd
from ...core.api import api_body, api_require
from ...core.auth import PERM_SETTINGS
from ...core.layout import (FEEDBACK_EMAIL, HOUR_MAX, HOUR_MIN, SETUP_HINT,
                            _DOW_FULL, _DOW_ORDER, msg_json, tg_refresh_meta)
from . import faq, lan
from .routes import (RESTART_NOTE, _finish_cfg, _hub_tiles, _lan_available,
                     _set_lan, _val_clinic, _val_hours, restart_text)

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
