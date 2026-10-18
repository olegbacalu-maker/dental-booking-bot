"""JSON API настроек (DentPilot 2.0): клиника, хаб, сеть, справка, часы,
услуги, вид клиники.

Правила те же, что у соседнего routes.py: `core`, `db`, `engine` — да,
`main.py` — нет. Проверки и слияние профиля берутся ИЗ routes.py, а не
переписываются: `_val_clinic`, `_val_hours`, `_val_services`, `_val_theme`,
`_finish_cfg`, `_set_lan`, `_logo_action`, `_hub_tiles` — единственные, кто
знает правило. Второй экземпляр этой логики разошёлся бы с первым молча.

Адреса — от сущности, не от страницы (docs/dentpilot-2/api.md), и полным
путём, без prefix у роутера: карта экранов и сторож раскладки читают адрес
из декоратора.

⚠️ Некоторые секции отдают HTML-куски: справка (ответы с иконками), проза
сети, шифрования и «Stare sistem». Это ТЕКСТ СЕРВЕРА — не данные пользователя
и не «отрисовка страницы через API»: кнопки, состояния и форму рисует клиент,
сервер отдаёт только прозу, чтобы она не жила дважды.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from ... import db, paths
from ... import engine as eng
from ... import privileged
from ... import update as upd
from ...core import backup_loop, dbkey, notices, restore, sms_loop, theme
from ...core import sms_plan as splan
from ...core.api import api_body, api_guard, api_require
from ...core.auth import (PERM_SETTINGS, PERM_USERS, PIN_MAX, PIN_MIN_LAN, ROLE_LABEL,
                          _pin_rec, _set_auth_cookie, all_users, can, change_pin,
                          client_peer, current_user, pin_min, pin_readiness,
                          request_user)
from ...core.layout import (FEEDBACK_EMAIL, HOUR_MAX, HOUR_MIN, SETUP_HINT, SUPPORT_PHONE,
                            _DOW_FULL, _DOW_ORDER, msg_json, msg_text, tg_refresh_meta)
from ...core.storage import _data_dir
from ...core.visits import SVC_PALETTE
from ...core import backup as bkp
from . import autostart, crypt, faq, lan, system
from .routes import (RESTART_NOTE, _PALETTE_RO, _apply_user, _drop_user,
                     _finish_cfg, _hub_tiles, HUB_GROUPS, _lan_available, _last_logins,
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
        # юрлицо и IDNO — только для подписываемых бумаг; пусто = как было
        "legal_name": cfg.get("legal_name") or "",
        "idno": cfg.get("idno") or "",
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
    """Проверка, слияние с профилем, атомарная запись, обновление профиля
    бота; ответ — JSON."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_set", status=422)
    addr = body.get("address") if isinstance(body.get("address"), dict) else {}
    try:
        cfg = _finish_cfg(**_val_clinic({
            "name": body.get("name", ""), "phone": body.get("phone", ""),
            "address": {"ro": addr.get("ro", ""), "ru": addr.get("ru", "")},
            "legal_name": body.get("legal_name", ""),
            "idno": body.get("idno", "")}))
    except ValueError as e:
        # _val_clinic называет виновное поле («name» / «phone» / «idno») — оно
        # уезжает клиенту, чтобы подсветить именно его; прочие ValueError без поля
        field = str(e) if str(e) in ("name", "phone", "idno") else ""
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
    точка цвета)."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    # группы — порядок и подписи одним списком (`HUB_GROUPS`)
    return msg_json(True, data={"tiles": _hub_tiles(),
                                "groups": [{"key": k, "label": v} for k, v in HUB_GROUPS]})


# ---------- сеть клиники ----------

def _lan_data(st: dict | None) -> dict:
    """`st` — `lan.firewall_state()`, посчитанный вызывающим в потоке.
    `fw` — вердикт словами (ok / missing / blocked / shut) и сеть, в которой
    он получен; `firewall` — прежнее «да / нет / проверить нечем»."""
    on = lan.enabled()
    ip, url = lan.address(on)
    st = st if on else None
    short, unknown = pin_readiness()
    return {
        "enabled": on, "ip": ip, "port": lan.port(), "url": url,
        "firewall": lan.firewall_ok(st),
        "fw": ({"verdict": st["verdict"], "category": st["category"],
                "network": st["network"]} if st is not None else None),
        # учётки, с которыми сеть не включится (17.10): имена для клиента,
        # `blocked` — кнопка включения закрыта (сервер отказал бы `lan_pins`);
        # держат ТОЛЬКО короткие, неизвестная длина — подсказка (`auth.pin_readiness`)
        "pins": {"min": PIN_MIN_LAN,
                 "short": [u["name"] for u in short],
                 "unknown": [u["name"] for u in unknown],
                 "blocked": not on and bool(short)},
        "blocks": {
            "intro": lan.intro_html(),
            "status": lan.status_html(on, ip, url, st),
            "pins": lan.pins_html(short, unknown, on),
            "firewall": lan.firewall_html(st) if lan.firewall_fixable(st) else "",
            "tips": lan.tips_html(st) if on else "",
        },
    }


@router.get("/api/settings/lan")
async def api_lan_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not _lan_available():
        return msg_json(False, status=404)
    # PowerShell (секунда-две) — в потоке: иначе на это время замер бы журнал
    st = await asyncio.to_thread(lan.firewall_state) if lan.enabled() else None
    return msg_json(True, data=_lan_data(st))


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
        # lan_pins — спор с состоянием учёток (409), bad_env — сбой файла (500)
        return msg_json(False, err, status=409 if err == "lan_pins" else 500)
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
    st = await asyncio.to_thread(lan.firewall_state)
    return msg_json(True, data={"asked": lan.request_firewall_rule(st)})


# ---------- состояние системы ----------

@router.get("/api/settings/system")
async def api_system_get(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    return msg_json(True, data=system.data())


@router.post("/api/settings/system/check")
def api_system_check(request: Request):
    """Проверить обновления прямо сейчас — не ждать следующего цикла.

    ⚠️ Синхронный `def` › threadpool: сетевой запрос не должен блокировать
    сервер.
    ⭐ Ответ — СВЕЖАЯ модель целиком, а не «проверено»: старая страница
    отвечала редиректом на себя же, то есть человек видел результат на
    перезагруженной странице. Второй запрос за состоянием был бы тем же самым
    ответом, только позже.
    """
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    upd.check_now()
    return msg_json(True, data=system.data())


@router.post("/api/settings/system/uninstall-sync")
def api_uninstall_sync(request: Request):
    """Попросить Windows поправить запись «Программ и компонентов» (P4.1).

    ⭐ Ответ — СВЕЖАЯ модель, а не «сделано»: итог UAC серверу не виден, и
    сказать «готово» он не вправе. Человек подтверждает окно, экран перечитывает
    состояние и видит результат фактом, а не обещанием.
    ⚠️ Синхронный `def` › threadpool: `ShellExecuteW` блокирует до показа окна.
    """
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    st = upd.uninstall_entry()
    if not st["found"] or not st["stale"]:
        # Нечего чинить — и окно UAC ради этого не показываем.
        return msg_json(True, data=system.data())
    try:
        privileged.request("uninstall-version", eng.APP_VERSION)
    except privileged.Refused:
        # ⛔ Отказ ДО окна: версия движка не из трёх чисел. Это дефект сборки,
        # а не действие человека, и молчать о нём нельзя.
        return msg_json(False, "bad_set", data=system.data())
    return msg_json(True, data=system.data())


@router.post("/api/settings/autostart")
async def api_autostart(request: Request):
    """Галочка «Pornește odată cu Windows» (Tauri, контракт § 2): значение Run
    в HKCU учётки, под которой работает движок. Ответ — СВЕЖАЯ модель экрана:
    галочка показывает то, что записано в реестре, а не то, что нажали.
    Строки нет (окно pywebview, браузер, исходники) — маршрута тоже нет."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if autostart.state() is None:
        return msg_json(False, status=404)
    body = await api_body(request)
    on = (body or {}).get("on")
    if not isinstance(on, bool):
        return msg_json(False, "bad_set", status=422, field="on")
    if not await asyncio.to_thread(autostart.apply, on):
        return msg_json(False, "autostart_fail", text=autostart.FAIL, status=500,
                        data=system.data())
    return msg_json(True, "ok_set", data=system.data())


# ---------- уведомления у часов (Tauri, контракт § 4) ----------

@router.get("/shell/notices")
async def shell_notices(request: Request):
    """Что сказать у часов — оболочке ЭТОГО ПК, не человеку: без сессии и без
    данных пациентов (`core/notices`). Не `/api/`: охрана здесь не кука, а
    токен запуска оболочки. Чужому — 404 тем же телом, что у несуществующего
    адреса."""
    if not notices.shell_request_ok(request):
        raise HTTPException(status_code=404)
    return JSONResponse(notices.items(), headers={"Cache-Control": "no-store"})


# ---------- шифрование картотеки ----------

def _crypt_data() -> dict:
    """Состояние раздела и его проза кусками.

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
    """Тело `{hours: {день: null | [от, до] | [от, до, пауза от, пауза до]}}`,
    проверка — `_val_hours`."""
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
    """Услуги для экрана: цена строкой (двуязычная
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
    считает СЕРВЕР (core/theme.py) и отдаёт готовыми."""
    th = theme.current()
    preset_hex = [c for c, _ in theme.PRESETS]
    return {
        "style": th["style"], "primary": th["primary"],
        "custom": th["primary"] not in preset_hex,
        "menu": th["menu"], "font": th["font"], "card": th["card"],
        "styles": [{"key": k, "label": theme.STYLE_LABEL[k][0],
                    "hint": theme.STYLE_LABEL[k][1], "vars": dict(v)}
                   for k, v in theme.STYLES.items()],
        # меню и шрифт (B5): переменные и набор семейств — для предпросмотра
        "menus": [{"key": k, "label": theme.MENU_LABEL[k][0],
                   "hint": theme.MENU_LABEL[k][1], "vars": dict(v)}
                  for k, v in theme.MENUS.items()],
        "fonts": [{"key": k, "label": theme.FONT_LABEL[k][0],
                   "hint": theme.FONT_LABEL[k][1], "stack": s}
                  for k, s in theme.FONTS.items()],
        # вид карточки визита (03.10): образец рисует клиент, сервер — подписи
        "cards": [{"key": k, "label": v[0], "hint": v[1]}
                  for k, v in theme.CARD_LABEL.items()],
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
    """Поля `style`, `primary` или `custom` + hex, `menu`, `font`, `card`,
    `logo_topbar`; проверка — `_val_theme`."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_set", status=422)
    try:
        cfg = _finish_cfg(theme=_val_theme({
            "style": body.get("style", ""), "primary": str(body.get("primary") or ""),
            "custom": str(body.get("custom") or ""),
            "menu": str(body.get("menu") or ""), "font": str(body.get("font") or ""),
            "card": str(body.get("card") or ""),
            "logo_topbar": bool(body.get("logo_topbar"))}))
    except ValueError as e:
        field = str(e) if str(e) in ("style", "primary", "menu", "font", "card") else ""
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
        # минимум — по состоянию сети (6 при включённом доступе), функцией
        "pin": {"min": pin_min(), "max": PIN_MAX},
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
    code, who = await change_pin(s("old_pin"), s("new1"), s("new2"),
                                 client_peer(request))
    if code != "ok_pin":
        return msg_json(False, code, status=_USER_HTTP.get(code, 422))
    return _set_auth_cookie(msg_json(True, code), who)


# ---------- копия ----------
#
# Три части одного экрана (17.10): ручной экспорт (как был), внешняя копия по
# расписанию (`core/backup_loop`) и восстановление (`core/restore`). Каждый
# ответ несёт ОДНУ модель `_backup_data()` — экран рисует её целиком, второго
# состояния в клиенте нет.

ARCHIVES_SHOWN = 30


def _archives_in(folder: str) -> list[dict]:
    """Архивы в папке назначения, новейшими вперёд: свои (`dentpilot-auto-*`)
    и ручные экспорты, положенные туда рукой."""
    out = []
    if not folder:
        return out
    try:
        d = pathlib.Path(folder)
        files = [p for p in d.glob("*.zip") if p.is_file()] if d.is_dir() else []
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[:ARCHIVES_SHOWN]:
            stt = p.stat()
            made = datetime.fromtimestamp(stt.st_mtime, eng.TZ).strftime("%d.%m.%Y %H:%M")
            out.append({"name": p.name, "size": stt.st_size, "made": made, "day": made[:10]})
    except OSError:
        return out
    return out


def _backup_data() -> dict:
    d = _data_dir()
    st = backup_loop.state()
    return {"min_pass": bkp.MIN_PASS, "filename": bkp.archive_name(),
            "auto": st,
            "restore": {"local": restore.local_copies(d) if d else [],
                        "archives": _archives_in(st["folder"]),
                        "staged": restore.summary(d) if d else None,
                        "pending": bool(d and restore.pending(d)),
                        "schema": db.SCHEMA_VERSION}}


@router.get("/api/settings/backup")
async def api_backup(request: Request):
    """Модель экрана: порог пароля и имя архива (сама выгрузка остаётся за
    `POST /admin/backup/export`: файл идёт обычной формой, браузер скачивает
    ответ потоком), состояние внешней копии, кандидаты на восстановление."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not bkp.available():
        return msg_json(False, status=404)
    return msg_json(True, data=_backup_data())


def _folder_check(folder: str) -> str | None:
    """Папка назначения: абсолютная, существует, пишется, НЕ внутри папки
    данных (копия на том же месте, что и база, — не копия). Код отказа или None."""
    try:
        p = pathlib.Path(folder)
        if not p.is_absolute() or not p.is_dir():
            return "bad_bkp_folder"
        d = _data_dir()
        for inside in (d, paths.data_root()):
            if inside is not None and (p.resolve() == inside.resolve()
                                       or inside.resolve() in p.resolve().parents):
                return "bad_bkp_inside"
        probe = p / f".dentpilot-write-test-{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        return "bad_bkp_folder"
    return None


@router.post("/api/settings/backup/auto")
async def api_backup_auto(request: Request):
    """{enabled?, folder?, password?} — экран шлёт то, что тронул (17.10
    вечером: выключатель и форма папки — два разных жеста). ⭐ Отсутствие
    ключа = «не сообщали», не «стереть» (прайор 08-16): выключатель без
    `folder` папку не трогает. `folder: ""` — выключить внешнюю копию;
    пустой пароль — оставить сохранённый. Папка и выключатель — в
    clinic.json › backup, пароль — в dental.env под DPAPI (как токен бота).
    Коды: выключатель — ok_bkp_on / ok_bkp_stop, папка — ok_bkp_auto /
    ok_bkp_off."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_set", status=422)
    enabled = bool(body["enabled"]) if "enabled" in body else backup_loop.enabled()
    touched_folder = "folder" in body
    folder = (str(body.get("folder") or "").strip().strip("\"'") if touched_folder
              else backup_loop.folder())
    pw = str(body.get("password") or "")
    if touched_folder and folder and (err := _folder_check(folder)) is not None:
        return msg_json(False, err, status=422, field="folder")
    if pw and len(pw) < bkp.MIN_PASS:
        return msg_json(False, "bad_bkp_pass", status=422, field="password")
    if touched_folder and folder and not pw and not backup_loop.password():
        return msg_json(False, "bad_bkp_pass", status=422, field="password")
    try:
        cfg = _finish_cfg(backup={"folder": folder, "enabled": enabled})
    except (ValueError, KeyError, TypeError):
        return msg_json(False, "bad_set", status=422)
    if pw:
        try:
            backup_loop.set_password(pw)
        except OSError as ex:
            logging.getLogger("settings").warning("backup pass: %r", ex)
            return msg_json(False, "bad_env", status=500)
    if eng.save_config(cfg) is not None:
        return msg_json(False, "save_err", status=500)
    backup_loop.wake()
    if touched_folder:
        code = "ok_bkp_auto" if folder else "ok_bkp_off"
    else:
        code = "ok_bkp_on" if enabled else "ok_bkp_stop"
    logging.getLogger("settings").warning("backup settings: daily %s, folder %r",
                                          "on" if enabled else "OFF", folder)
    return msg_json(True, code, data=_backup_data())


@router.post("/api/settings/backup/auto/run")
async def api_backup_auto_run(request: Request):
    """«Fă o copie acum»: внешняя копия сейчас, ответ — свежая модель; отказ
    приходит словами цикла (тот же текст, что в ленте и баннере)."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    if not backup_loop.folder():
        return msg_json(False, "bad_bkp_unset", status=409)
    err = await backup_loop.run_external()
    if err:
        return msg_json(False, "bad_bkp_auto", status=500, data=_backup_data(),
                        text=f"{msg_text('bad_bkp_auto')}: {err}")
    return msg_json(True, "ok_bkp_run", data=_backup_data())


@router.post("/api/settings/backup/restore/stage")
async def api_restore_stage(request: Request):
    """Принять копию и показать, что внутри, ДО подтверждения.
    {kind: local|archive|path, name|path, password}. `local` — копия из
    data\\backups (под ключом картотеки), `archive` — архив из папки
    назначения по имени, `path` — архив по полному пути (флешка)."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    body = await api_body(request)
    if body is None or d is None:
        return msg_json(False, "bad_rst_src", status=422)
    kind = str(body.get("kind") or "")
    pw = str(body.get("password") or "")
    try:
        if kind == "local":
            key = dbkey.load() if dbkey.enabled() else None
            if dbkey.enabled() and key is None:
                raise restore.RestoreError("bad_rst_file", "cheia bazei nu poate fi citită")
            s = await asyncio.to_thread(restore.stage_local, d, str(body.get("name") or ""), key)
        elif kind in ("archive", "path"):
            if kind == "archive":
                name = str(body.get("name") or "")
                if not backup_loop.folder() or "/" in name or "\\" in name or not name:
                    raise restore.RestoreError("bad_rst_src", f"nume nepermis: {name!r}")
                src = pathlib.Path(backup_loop.folder()) / name
            else:
                src = pathlib.Path(str(body.get("path") or "").strip().strip("\"'"))
                if not src.is_absolute():
                    raise restore.RestoreError("bad_rst_src", f"cale relativă: {src}")
            s = await asyncio.to_thread(restore.stage_archive, d, src, pw)
        else:
            raise restore.RestoreError("bad_rst_src", f"kind={kind!r}")
    except restore.RestoreError as ex:
        logging.getLogger("settings").warning("restore stage: %s (%s)", ex.code, ex.detail)
        return msg_json(False, ex.code, status=422, data=_backup_data())
    except OSError as ex:
        logging.getLogger("settings").warning("restore stage: %r", ex)
        return msg_json(False, "bad_rst_file", status=500, data=_backup_data())
    if int(s.get("schema") or 0) > db.SCHEMA_VERSION:
        restore.cancel(d)
        return msg_json(False, "bad_rst_newer", status=409, data=_backup_data())
    return msg_json(True, "ok_rst_staged", data=_backup_data())


@router.post("/api/settings/backup/restore/confirm")
async def api_restore_confirm(request: Request):
    """Заказать восстановление принятой копии лаунчеру и перезапустить
    программу — как выключение шифрования (`api_crypt_off`): подмену базы
    делает только лаунчер до старта приложения."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    if d is None or not restore.request(d):
        return msg_json(False, "bad_rst_none", status=409, data=_backup_data())
    logging.getLogger("settings").warning("restore ordered: %s", restore.summary(d))
    auto = upd.restart_app() is None
    desktop = upd.is_desktop()
    return msg_json(True, "ok_rst_ordered", data={
        **_backup_data(), "restart": auto,
        "text": f"{msg_text('ok_rst_ordered')} — {restart_text(auto)}" if desktop else "",
        "note": RESTART_NOTE if desktop else "",
    })


@router.post("/api/settings/backup/restore/cancel")
async def api_restore_cancel(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    if d is not None:
        restore.cancel(d)
    return msg_json(True, "ok_rst_cancel", data=_backup_data())


# ---------- SMS-пакет (S6): Setări › SMS ----------
#
# Видит и регистратура (Олег 16.10): чтение и переключатели — `api_guard`;
# «Comandă» (пополнение, своё имя) и тестовая SMS — `api_require(PERM_SETTINGS)`.
# Данные экрана собирает цикл (`sms_loop.screen`): счёт сервера, настройки
# из clinic.json, предпросмотры с названием клиники, прогноз, остаток на дни.
# Отказ сервера лицензий уезжает его словами (`text=`), код — `sms_denied`.

_SMS_OUTCOME = {sms_loop.wire.OFFLINE: ("sms_offline", 503), sms_loop.wire.REFUSED: ("sms_token", 503)}


def _sms_data() -> dict:
    me = request_user()
    return {**sms_loop.screen(), "can_order": me is None or can(me, PERM_SETTINGS),
            "support": {"phone": SUPPORT_PHONE, "email": FEEDBACK_EMAIL}}


def _sms_fail(outcome: str, body: dict, *, field: str = ""):
    if outcome == sms_loop.wire.DENIED:
        return msg_json(False, "sms_denied", status=409, field=field,
                        text=str(body.get("text") or ""), data={"reason": body.get("code") or ""})
    code, status = _SMS_OUTCOME.get(outcome, ("sms_offline", 503))
    return msg_json(False, code, status=status)


@router.get("/api/settings/sms")
async def api_sms_get(request: Request):
    if (deny := api_guard(request)) is not None:
        return deny
    return msg_json(True, data=_sms_data())


@router.post("/api/settings/sms")
async def api_sms_save(request: Request):
    """Переключатели целиком ({day_before, same_day, phone_line}): кривое —
    умолчание (`sms_plan.settings`); цикл будится сразу — включённое событие
    может быть «уже пора»."""
    if (deny := api_guard(request)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_sms", status=422)
    try:
        cfg = _finish_cfg(sms=splan.settings(body))
    except (ValueError, KeyError, TypeError):
        return msg_json(False, "bad_sms", status=422)
    if eng.save_config(cfg) is not None:
        return msg_json(False, "save_err", status=500)
    sms_loop.wake()
    return msg_json(True, "ok_sms", data=_sms_data())


@router.post("/api/settings/sms/refresh")
async def api_sms_refresh(request: Request):
    """«Verifică acum»: счёт перечитывается у сервера, очередь — следующим тиком."""
    if (deny := api_guard(request)) is not None:
        return deny
    if not sms_loop.available():
        return msg_json(False, "sms_unavailable", status=409)
    outcome = await sms_loop.refresh_account(force=True)
    sms_loop.wake()
    if outcome in (sms_loop.wire.OK, sms_loop.wire.DENIED):
        return msg_json(True, data=_sms_data())
    return _sms_fail(outcome, {})


@router.post("/api/settings/sms/order")
async def api_sms_order(request: Request):
    """{pack: N} — пополнение, {name: 1} — год своего имени; директору. Нота
    и ссылка maib — ответом сервера, письмо — на e-mail клиники."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_sms", status=422)
    if not sms_loop.available():
        return msg_json(False, "sms_unavailable", status=409)
    try:
        pack = int(body.get("pack") or 0)
    except (TypeError, ValueError):
        pack = 0
    outcome, data = await sms_loop.order(pack=pack, name=bool(body.get("name")))
    if outcome != sms_loop.wire.OK:
        return _sms_fail(outcome, data)
    return msg_json(True, "sms_order_ok",
                    data={k: data.get(k) for k in ("kind", "reference", "amount", "units", "pay_url", "created")})


@router.post("/api/settings/sms/sender")
async def api_sms_sender(request: Request):
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_sms", status=422)
    if not sms_loop.available():
        return msg_json(False, "sms_unavailable", status=409)
    outcome, data = await sms_loop.request_sender(str(body.get("name") or ""))
    if outcome != sms_loop.wire.OK:
        return _sms_fail(outcome, data, field="name")
    return msg_json(True, "sms_sender_ok", data=_sms_data())


@router.post("/api/settings/sms/test")
async def api_sms_test(request: Request):
    """Тестовая SMS на номер директора — из пакета клиники, мимо очереди."""
    if (deny := api_require(request, PERM_SETTINGS)) is not None:
        return deny
    body = await api_body(request)
    if body is None:
        return msg_json(False, "bad_sms", status=422)
    if not sms_loop.available():
        return msg_json(False, "sms_unavailable", status=409)
    outcome, data = await sms_loop.send_test(str(body.get("phone") or ""))
    if outcome != sms_loop.wire.OK:
        return _sms_fail(outcome, data, field="phone")
    return msg_json(True, "sms_test_ok", data=_sms_data())
