"""Настройки клиники: профиль, часы работы, врачи и услуги, токен Telegram,
проверка и установка обновления.

Единственный экран, который ПИШЕТ `clinic.json` — и потому единственный, где
ошибка стоит дороже обычной: битый файл клиники означает старт с чужими
демо-врачами. Запись атомарная и с резервной копией, это в `eng.save_config`.

Правило то же: `core`, `db`, `engine` — да, `main.py` — нет.
"""
from __future__ import annotations

import html
import json
import logging
import os
import pathlib
import re
import shutil
import sys
import tempfile
from datetime import datetime

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from starlette.background import BackgroundTask

from ... import db
from ... import dpapi, envfile
from ... import engine as eng
from ... import update as upd
from ...core.auth import (ADMIN_KEY, PERM_SETTINGS, PERM_USERS, PIN_MAX,
                          ROLE_DIRECTOR, ROLE_LABEL, ROLE_MEDIC, _pin_rec,
                          all_users, current_user, delete_user, find_user,
                          n_directors, pin_free, pin_len_ok,
                          remember_auth_file, require, save_user)
from ...core.layout import (FEEDBACK_EMAIL, HOUR_MAX, HOUR_MIN, js_json,
                            _DOC_STATE_RO, _DOW_FULL, _DOW_ORDER, _ic,
                            _doc_hours_text, msg_banner, _shell, standalone,
                            tg_configured, tg_refresh_meta, tg_status)
from ...core import bitlocker, dbkey, theme
from ...core.storage import _data_dir
from ...core.visits import SVC_PALETTE
from . import backup as bkp
from . import faq
from . import lan

router = APIRouter()

# id сотрудника: он попадает в подпись куки и в журнал доступа, поэтому только
# безопасные символы — точка в нём разделила бы куку не там, где надо
_UID_RE = re.compile(r"[a-z0-9_-]{2,20}")


def _set_back(msg: str) -> RedirectResponse:
    # учётки живут на странице «Securitate» — туда и возвращаем
    return RedirectResponse(f"/admin/settings/security?msg={msg}", status_code=303)


def _users_block(last_login: dict[str, str]) -> str:
    """Сотрудники клиники: кто входит и что ему можно.

    Вход идёт по ОДНОМУ паролю, без логина: регистратура набирает его десятки
    раз в день, и требовать ещё и id — трение на ровном месте. Отсюда правило,
    которое стережёт `pin_free`: пароли обязаны быть разными, иначе журнал
    доступа начнёт называть чужое имя. Id при этом есть у каждого — он нужен
    журналу и врачу на телефоне, где вход по одному паролю неочевиден.

    `last_login` (uid → «13.08.2026 14:02») — гигиена доступа: учётка, в
    которую не входили месяцами, — это либо уволенный, либо пароль, которым
    никто не пользуется; и то и другое директор должен ВИДЕТЬ, а не помнить.
    """
    e = html.escape
    doc_opts = "".join(f"<option value='{e(k)}'>{e(v)}</option>"
                       for k, v in eng.DOCTORS.items())
    rows = []
    for u in all_users():
        sel_role = "".join(
            f"<option value='{k}'{' selected' if k == u['role'] else ''}>{v}</option>"
            for k, v in ROLE_LABEL.items())
        sel_doc = "".join(
            f"<option value='{e(k)}'{' selected' if k == u['doctor_id'] else ''}>"
            f"{e(v)}</option>" for k, v in eng.DOCTORS.items())
        rows.append(
            f"<tr><td><b>{e(u['name'])}</b><br>"
            f"<small style='color:var(--text3)'>id: {e(u['id'])}</small><br>"
            f"<small style='color:var(--text3)'>ultima intrare: "
            f"{e(last_login.get(u['id'], '—'))}</small></td>"
            f"<td><form method='post' action='/admin/users/save' "
            f"style='display:flex;gap:6px;flex-wrap:wrap;align-items:center'>"
            f"<input type='hidden' name='uid' value='{e(u['id'])}'>"
            f"<input type='hidden' name='name' value=\"{e(u['name'])}\">"
            f"<select name='role'>{sel_role}</select>"
            f"<select name='doctor_id'><option value=''>— nu e medic —</option>"
            f"{sel_doc}</select>"
            f"<input type='password' name='pin' placeholder='PIN nou (opțional)' "
            f"inputmode='numeric' maxlength='{PIN_MAX}' style='width:150px'>"
            f"<button>Salvează</button></form></td>"
            # ⚠️ имя — только в HTML-атрибуте, НЕ внутри JS-литерала: браузер
            # декодирует &#x27; обратно в апостроф ДО компиляции onsubmit, и
            # «O'Brien» рвал строку confirm('…') — форма уходила БЕЗ
            # подтверждения, а подобранное имя исполнялось как JS
            f"<td><form method='post' action='/admin/users/delete' "
            f"data-msg=\"Ștergeți contul {e(u['name'])}?\" "
            f"onsubmit=\"return confirm(this.dataset.msg)\">"
            f"<input type='hidden' name='uid' value='{e(u['id'])}'>"
            f"<button class='rowdel'>Șterge</button></form></td></tr>")
    role_opts = "".join(f"<option value='{k}'"
                        f"{' selected' if k == ROLE_MEDIC else ''}>{v}</option>"
                        for k, v in ROLE_LABEL.items())
    return f"""
<h2>{_ic("users")} Utilizatori</h2>
<table class='set'><tr><th style='width:220px'>Persoana</th><th>Acces</th><th></th></tr>
{''.join(rows)}</table>
<form class='add' method='post' action='/admin/users/save'>
  <input name='name' placeholder='Nume și prenume' maxlength='60' required style='width:200px'>
  <input name='uid' placeholder='id (ex. d2, ana)' maxlength='20' required style='width:130px'>
  <select name='role'>{role_opts}</select>
  <select name='doctor_id'><option value=''>— nu e medic —</option>{doc_opts}</select>
  <input type='password' name='pin' placeholder='PIN 4–8 cifre' inputmode='numeric'
         maxlength='{PIN_MAX}' required style='width:150px'>
  <button>+ Adaugă utilizator</button>
</form>
<p class='hint'>Intrarea se face cu PIN-ul personal, fără nume de utilizator —
de aceea PIN-ul trebuie să fie unic în clinică. <b>Director</b> vede banii și
setările, <b>Recepție</b> și <b>Medic</b> — tot restul. Legătura cu un medic
face ca jurnalul să scrie numele lui la fiecare deschidere de fișă.
Pentru <b>director</b> recomandăm un PIN de 6+ cifre — el vede banii și
setările; intrările în program se văd în «Activitate recentă» (Statistici).</p>"""

_PALETTE_RO = {"green": "verde", "blue": "albastru", "amber": "portocaliu",
               "violet": "violet", "red": "roșu", "teal": "turcoaz"}


_DOW_SHORT = {"ro": {"mon": "Lu", "tue": "Ma", "wed": "Mi", "thu": "Jo",
                     "fri": "Vi", "sat": "Sâ", "sun": "Du"},
              "ru": {"mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт",
                     "fri": "Пт", "sat": "Сб", "sun": "Вс"}}


def _hours_summary(hours: dict, lang: str) -> str:
    """'Lu–Vi 9:00–18:00, Sâ 9:00–14:00' из hours-словаря."""
    names = _DOW_SHORT[lang]
    parts = []
    i = 0
    while i < 7:
        h = hours.get(_DOW_ORDER[i])
        j = i
        while j + 1 < 7 and hours.get(_DOW_ORDER[j + 1]) == h:
            j += 1
        if h:
            rng = (names[_DOW_ORDER[i]] if i == j
                   else f"{names[_DOW_ORDER[i]]}–{names[_DOW_ORDER[j]]}")
            txt = f"{rng} {h[0]}:00–{h[1]}:00"
            if len(h) >= 4:
                txt += (f" (pauză {h[2]}:00–{h[3]}:00)" if lang == "ro"
                        else f" (перерыв {h[2]}:00–{h[3]}:00)")
            parts.append(txt)
        i = j + 1
    return ", ".join(parts)


def _hour_opts(sel: int, lo: int = HOUR_MIN, hi: int = HOUR_MAX) -> str:
    return "".join(
        f"<option value='{h}'{' selected' if h == sel else ''}>{h}:00</option>"
        for h in range(lo, hi + 1)
    )


# ---------- раздел «Setări»: хаб + страницы-секции (просьба Олега 08-06) ----------
#
# Раньше всё лежало одной страницей и путалось; теперь /admin/settings — хаб из
# плиток (те же .pl-tile, что в «Pacienți»: раздел не должен выглядеть чужим),
# а каждая секция — своя страница. ⚠️ Клиника/часы/услуги по-прежнему ОДИН
# clinic.json: каждая страница шлёт только свой кусок (part=...), сервер
# сливает его с остальным конфигом. Прислать всё и тут было бы проще, но тогда
# устаревшая вкладка «Program» затирала бы услуги, сохранённые из соседней.


def _bl_row() -> str:
    """Строка BitLocker в «Stare sistem». Только desktop: у облака диск не наш."""
    if not db.IS_SQLITE:
        return ""
    tone, txt = bitlocker.describe(bitlocker.STATE["code"],
                                   bitlocker.STATE["drive"])
    ico = {"ok": _ic("check"), "warn": _ic("sos"), "alarm": _ic("ban")}.get(tone, "")
    style = (" style='color:var(--red-t);font-weight:600'" if tone == "alarm"
             else " style='color:var(--amber-t)'" if tone == "warn" else "")
    return (f"<tr><th>Criptare disc (BitLocker)</th>"
            f"<td{style}>{ico} {html.escape(txt)}</td></tr>")


def _tg_line(tg: dict) -> str:
    if tg["running"]:
        return f"{_ic('check')} activ — @{html.escape(tg['username'])}"
    if os.environ.get("DENTART_TOKEN_UNREADABLE") == "1":
        # шифротекст не с этой машины (см. dpapi.py). Молчаливое «fără token»
        # отправило бы клинику чинить настройки бота, которые в порядке
        return (_ic("key") + " tokenul nu poate fi citit pe acest calculator — "
                "reintroduceți-l în secțiunea Telegram")
    if os.environ.get("TELEGRAM_TOKEN", "").strip():
        return f"{_ic('sos')} {html.escape(tg.get('error') or 'pornire…')}"
    return "— fără token (secțiunea Telegram Bot)"


def _sec_page(body: str, sub: str, msg: str) -> str:
    nav = (f"<div class='nav'><a href='/admin/settings'>{_ic('chev-l')} Setări</a>"
           f"<a href='/admin'>{_ic('home')} Panou</a></div>")
    return _shell(nav + msg_banner(msg) + body, sub, active="set")


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, msg: str = ""):
    """Хаб настроек: по плитке на секцию, на каждой — живая строка состояния."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    cfg = eng.CONFIG
    e = html.escape

    def tile(href: str, ico: str, tone: str, label: str, hint: str) -> str:
        return (f"<a class='pl-tile' href='{href}'>"
                f"<span class='ico {tone}'>{ico}</span><div class='pl-tv'>"
                f"<span>{label}</span><small>{hint}</small></div></a>")

    # короткое состояние обновления — подробности на странице «Stare sistem»
    if upd.can_self_update() or upd.newer_available():
        up_short = (f"<b style='color:var(--amber-t)'>{_ic('refresh')} disponibilă "
                    f"{e(upd.STATE['latest'])}</b>")
    elif upd.STATE["checked"] and not upd.STATE["error"]:
        up_short = _ic("check") + " la zi"
    else:
        up_short = "stare necunoscută"
    tg = tg_status()
    tg_short = (f"{_ic('check')} @{e(tg['username'])}" if tg["running"] else "neconectat")
    today_h = cfg.get("hours", {}).get(_DOW_ORDER[datetime.now(eng.TZ).weekday()])
    hours_short = (f"azi {int(today_h[0])}:00–{int(today_h[1])}:00" if today_h
                   else "azi închis")
    n_docs = sum(1 for d in cfg["doctors"] if eng.doctor_state(d) == "activ")
    _th = theme.current()

    bl_tone, _bl_txt = bitlocker.describe(bitlocker.STATE["code"],
                                          bitlocker.STATE["drive"])
    bl_flag = ("" if bl_tone in ("ok", "unknown") or not db.IS_SQLITE
               else f" · <b style='color:var(--red-t)'>{_ic('ban')} disc necriptat</b>"
               if bl_tone == "alarm"
               else f" · <b style='color:var(--amber-t)'>{_ic('sos')} BitLocker</b>")
    tiles = [tile("/admin/settings/system", _ic("info"), "b", "Stare sistem",
                  f"v{eng.APP_VERSION} · {up_short}{bl_flag}"),
             tile("/admin/settings/clinic", _ic("clinic"), "g", "Clinica",
                  e(cfg["name"])),
             tile("/admin/settings/theme", _ic("palette"), "v", "Aspectul clinicii",
                  f"{e(theme.STYLE_LABEL[_th['style']][0])} · "
                  f"<span class='th-dot' style='background:{e(_th['primary'])}'></span>"
                  f"{e(_th['primary'])}"
                  + (" · logo" if theme.logo_url() else "")),
             tile("/admin/settings/hours", _ic("clock"), "v", "Program de lucru",
                  hours_short),
             tile("/admin/settings/services", _ic("tooth"), "g", "Servicii",
                  f"{len(cfg['services'])} servicii"),
             tile("/admin/medici", _ic("med"), "b", "Medici",
                  f"{n_docs} activi · se editează în secțiunea Medici")]
    if db.IS_SQLITE and os.environ.get("DENTART_ENV_FILE"):
        # Telegram заморожен (08-08): плитку видят только клиники с уже
        # настроенным токеном — grandfather, как секция в сайдбаре.
        # Прямой адрес /admin/settings/telegram жив для ручного включения.
        if tg_configured():
            tiles.append(tile("/admin/settings/telegram", _ic("bot"), "v",
                              "Telegram Bot", tg_short))
        # Подпись выключенного состояния называет ВЕЩИ, а не режим: директор
        # ищет на хабе «второй компьютер», а не «сетевой доступ» (08-13).
        lan_short = (_ic("check") + " activ în rețeaua clinicii" if lan.enabled()
                     else "al doilea calculator, telefon — oprit")
        tiles.append(tile("/admin/settings/lan", _ic("wifi"), "b",
                          "Acces din rețea", lan_short))
    if db.IS_SQLITE:
        _cs = dbkey.state()
        tiles.append(tile("/admin/settings/crypt", _ic("lock"), "g", "Criptarea evidenței",
                          {dbkey.OK: _ic("check") + " activă",
                           dbkey.UNREADABLE: "<b style='color:var(--red-t)'>" + _ic("ban") + " cheia nu "
                                             "se citește</b>"}.get(_cs, "oprită")))
    if db.IS_SQLITE and bkp.available():
        tiles.append(tile("/admin/settings/backup", _ic("save"), "b", "Copie de rezervă",
                          "arhivă criptată AES-256"))
    if _pin_rec():
        tiles.append(tile("/admin/settings/security", _ic("users"), "g",
                          "Securitate și utilizatori",
                          f"{len(all_users())} utilizatori"))
    # FAQ безусловно и последней: справка в конце списка — привычное место
    tiles.append(tile("/admin/settings/faq", _ic("help"), "v", "Întrebări frecvente",
                      "copii de rezervă, mutare, Legea 195"))

    body = (f"<div class='pl-head'><div><h2>Setări</h2>"
            f"<p>Alegeți o secțiune — modificările se aplică imediat, "
            f"fără repornire</p></div></div>"
            f"<div class='pl-tiles set-hub'>{''.join(tiles)}</div>")
    return _shell(f"<div class='nav'><a href='/admin'>{_ic('home')} Panou</a></div>"
                  + msg_banner(msg) + body,
                  "setările clinicii · pe secțiuni", active="set")


@router.get("/admin/settings/system", response_class=HTMLResponse)
async def settings_system(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    # статус спрашиваем у core, а не повторяем трюк с sys.modules: имя пакета
    # зависит от того, где лежит файл, и своя копия уже один раз соврала
    tg = tg_status()
    # Telegram заморожен (08-08): строка канала — только клинике с настроенным
    # ботом. Остальным она писала «— fără token (secțiunea Telegram Bot)» —
    # отправляла искать раздел, который заморозка как раз спрятала (08-13).
    tg_row = (f"<tr><th>Canal Telegram</th><td>{_tg_line(tg)}</td></tr>"
              if tg_configured() else "")
    if upd.can_self_update():
        up_line = (
            f"{_ic('refresh')} disponibilă {html.escape(upd.STATE['latest'])} "
            f"<form method='post' action='/admin/update/run' style='display:inline'>"
            f"<button style='background:#e8710a;color:#fff;border:none;border-radius:6px;"
            f"padding:6px 14px;cursor:pointer;font-size:14px;margin-left:8px'>"
            f"{_ic('upload')} Actualizează acum</button></form>"
        )
    elif upd.asset_pending() and upd.is_desktop():
        up_line = (f"{_ic('clock')} versiunea {html.escape(upd.STATE['latest'])} este anunțată, "
                   f"dar fișierul programului încă nu e publicat — "
                   f"reverificăm automat peste câteva minute")
    elif upd.newer_available():
        up_line = (f"<a href='{html.escape(upd.STATE['url'])}' target='_blank'>"
                   f"{_ic('refresh')} disponibilă {html.escape(upd.STATE['latest'])} — descărcați</a>")
    elif upd.STATE["checked"] and not upd.STATE["error"]:
        up_line = f"{_ic('check')} la zi"
    elif upd.STATE["error"]:
        up_line = "— necunoscut (offline?)"
    else:
        up_line = "se verifică…"
    # Канал виден в интерфейсе намеренно: на этой машине обновление приходит
    # РАНЬШЕ, чем клиникам, и перепутать её с боевой установкой нельзя.
    chan_row = ""
    ch = upd.channel()
    if ch != "stable":
        # beta — публичные пре-релизы, ключ не нужен; draft — ещё и черновики,
        # но для них нужен токен с правом записи. Названия разные намеренно:
        # риск у этих двух режимов разный, и путать их нельзя.
        name = "draft (test)" if ch == "draft" else "beta (pre-lansări)"
        note = ""
        if upd.STATE.get("draft"):
            note = " · versiunea curentă din canal este nepublicată"
        elif upd.STATE.get("prerelease"):
            note = " · versiunea curentă din canal este pre-lansare"
        chan_row = (f"<tr><th>Canal actualizări</th><td>"
                    f"<b style='color:var(--amber-t)'>{name}</b> — "
                    "acest calculator vede versiunile ÎNAINTE de clinici"
                    + note + "</td></tr>")
    up_line += ("<form method='post' action='/admin/update/check' style='display:inline'>"
                "<button style='background:none;border:1px solid var(--line);border-radius:8px;"
                "padding:4px 10px;cursor:pointer;font-size:12px;color:var(--text2);"
                f"margin-left:10px'>{_ic('refresh')} Verifică acum</button></form>")
    body = f"""
<h2>{_ic("info")} Stare sistem</h2>
<table class='set'>
<tr><th style='width:180px'>Versiune</th><td>v{eng.APP_VERSION}</td></tr>
<tr><th>Bază de date</th><td>{"SQLite (local, data/dental.db)" if db.IS_SQLITE else "PostgreSQL"}</td></tr>
{tg_row}
<tr><th>Actualizări</th><td>{up_line}</td></tr>
{chan_row}
<tr><th>Acces jurnal</th><td>{_ic('lock')} {"PIN setat" if _pin_rec() else ("parolă (ADMIN_KEY)" if ADMIN_KEY else "deschis")}</td></tr>
{_bl_row()}
<tr><th>Feedback / suport</th><td><a href='mailto:{FEEDBACK_EMAIL}'>{FEEDBACK_EMAIL}</a></td></tr>
</table>

<h2>{_ic("shield")} Confidențialitate</h2>
<div class='pcard' style='max-width:760px'>
<p style='margin:0 0 8px;font-size:13px;line-height:1.55;color:var(--text2)'>
<b style='color:var(--text)'>Programul funcționează local.</b> Datele personale ale pacienților
nu sunt transmise dezvoltatorului și nu sunt stocate pe serverele acestuia.
Actualizările descarcă doar fișierele programului. Baza de date, jurnalele și
copiile de rezervă rămân pe acest calculator, în folderul programului.</p>
<p style='margin:0;font-size:12.5px;line-height:1.55;color:var(--text3)'>
Программа работает локально. Персональные данные пациентов не передаются
разработчику и не хранятся на его серверах. Обновления загружают только файлы
программы. База данных, журналы и резервные копии остаются на этом компьютере.</p>
</div>"""
    return _sec_page(body, "setări · stare sistem", msg)


@router.get("/admin/settings/telegram", response_class=HTMLResponse)
async def settings_telegram(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not (db.IS_SQLITE and os.environ.get("DENTART_ENV_FILE")):
        return RedirectResponse("/admin/settings", status_code=303)
    tok_set = bool(os.environ.get("TELEGRAM_TOKEN", "").strip())
    ph = ("••• token setat — introduceți altul pentru schimbare" if tok_set
          else "token de la @BotFather (ex. 123456789:AA...)")
    body = f"""
<h2>{_ic("bot")} Telegram — token bot</h2>
<p class='hint' style='margin-top:0'>Stare: {_tg_line(tg_status())}</p>
<form class='add' method='post' action='/admin/telegram/save'
      onsubmit="return confirm('Programul se va reporni pentru aplicare. Continuați?')">
  <input type='password' name='token' placeholder="{ph}" style='width:430px'>
  <button>{_ic('save')} Salvează</button>
</form>
<p class='hint'>Creați botul clinicii la @BotFather (2 minute) și lipiți tokenul aici.
Câmp gol + salvare = dezactivează canalul Telegram.</p>"""
    return _sec_page(body, "setări · Telegram Bot", msg)


@router.get("/admin/settings/lan", response_class=HTMLResponse)
async def settings_lan(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not (db.IS_SQLITE and os.environ.get("DENTART_ENV_FILE")):
        return RedirectResponse("/admin/settings", status_code=303)
    return _sec_page(lan.render(), "setări · acces din rețea", msg)


@router.post("/admin/lan/save", response_class=HTMLResponse)
async def admin_lan_save(request: Request, mode: str = Form("")):
    """Переключить доступ из сети клиники. Слушающий адрес выбирает ЛАУНЧЕР
    при старте (bot/desktop.py), поэтому применение = перезапуск программы —
    тот же путь, что смена токена бота."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    env_file = os.environ.get("DENTART_ENV_FILE", "")
    if not (db.IS_SQLITE and env_file):
        return RedirectResponse("/admin/settings", status_code=303)
    val = "1" if mode == "on" else ""
    try:
        envfile.set_value(pathlib.Path(env_file), "DENTART_LAN", val)
    except OSError as ex:
        # dental.env не читается/не пишется (придержан, чужая кодировка) —
        # set_value отказывается, а не переписывает файл; говорим честно
        logging.getLogger("settings").warning("env write: %r", ex)
        return RedirectResponse("/admin/settings/lan?msg=bad_env", status_code=303)
    os.environ["DENTART_LAN"] = val
    logging.getLogger("settings").warning(
        "LAN access %s", "ENABLED" if val else "disabled")
    if upd.restart_app() is not None:
        # dev-режим/тест-хук: перезапуск не случился — просто баннер
        return RedirectResponse("/admin/settings/lan?msg=ok_set", status_code=303)
    return _restart_page("Setare salvată", "/admin/settings/lan")


@router.post("/admin/lan/firewall")
async def admin_lan_firewall(request: Request):
    """Кнопка «создай правило firewall»: UAC-запрос на ЭКРАНЕ ПК клиники —
    доступ включают с этого компьютера, так что директор его и видит."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not (db.IS_SQLITE and os.environ.get("DENTART_ENV_FILE")):
        return RedirectResponse("/admin/settings", status_code=303)
    lan.request_firewall_rule()
    return RedirectResponse("/admin/settings/lan", status_code=303)


@router.get("/admin/settings/backup", response_class=HTMLResponse)
async def settings_backup(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not (db.IS_SQLITE and bkp.available()):
        return RedirectResponse("/admin/settings", status_code=303)
    body = f"""
<h2>{_ic("save")} Copie de rezervă criptată</h2>
<form class='add' method='post' action='/admin/backup/export'>
  <input type='password' name='parola' placeholder='parolă (min. {bkp.MIN_PASS} caractere)'
         minlength='{bkp.MIN_PASS}' required style='width:280px' autocomplete='new-password'>
  <button>{_ic('download')} Exportă arhiva</button>
</form>
<p class='hint'>Arhivă ZIP criptată (AES-256) cu baza de date, profilul clinicii și
documentele pacienților — pentru stick USB sau alt calculator. Se deschide cu 7-Zip
prin parola aleasă. <b>Parola nu se salvează nicăieri</b> — fără ea arhiva nu poate
fi citită de nimeni, nici de noi.</p>"""
    return _sec_page(body, "setări · copie de rezervă", msg)


@router.get("/admin/settings/security", response_class=HTMLResponse)
async def settings_security(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not _pin_rec():
        return RedirectResponse("/admin/settings", status_code=303)
    # последний вход каждого — из meta (пишет /admin/login), НЕ из auth.json:
    # файл под сигнализацией отпечатка, и запись «когда входил» при каждом
    # входе дёргала бы её на ровном месте
    last = {}
    for u in all_users():
        v = await db.get_meta(f"last_login:{u['id']}")
        if v:
            try:
                last[u["id"]] = (datetime.fromisoformat(v).astimezone(eng.TZ)
                                 .strftime("%d.%m.%Y %H:%M"))
            except ValueError:
                pass
    body = f"""
<h2>{_ic("key")} Schimbă PIN</h2>
<form class='add' method='post' action='/admin/pin/change'>
  <input type='password' name='old_pin' placeholder='PIN actual' inputmode='numeric' maxlength='{PIN_MAX}' required style='width:140px'>
  <input type='password' name='new1' placeholder='PIN nou' inputmode='numeric' maxlength='{PIN_MAX}' required style='width:140px'>
  <input type='password' name='new2' placeholder='repetați' inputmode='numeric' maxlength='{PIN_MAX}' required style='width:140px'>
  <button>Schimbă</button>
</form>""" + _users_block(last)
    return _sec_page(body, "setări · securitate și utilizatori", msg)


@router.get("/admin/settings/faq", response_class=HTMLResponse)
async def settings_faq(request: Request, msg: str = ""):
    # под PERM_SETTINGS, как весь раздел: темы директорские (бэкап, перенос,
    # закон 195). Подсказки регистратуре — в самих экранах, не здесь.
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    return _sec_page(faq.render(), "setări · întrebări frecvente", msg)


@router.get("/admin/settings/clinic", response_class=HTMLResponse)
async def settings_clinic(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    cfg = eng.CONFIG
    e = html.escape
    body = f"""
<h2>{_ic("clinic")} Clinica</h2>
<form method='post' action='/admin/settings/save'>
<input type='hidden' name='part' value='clinic'>
<table class='set'>
<tr><th style='width:180px'>Nume</th><td><input type='text' name='name' value='{e(cfg["name"])}'></td></tr>
<tr><th>Telefon</th><td><input type='text' name='phone' value='{e(cfg["phone"])}'></td></tr>
<tr><th>Adresa (RO)</th><td><input type='text' name='addr_ro' value='{e(cfg.get("address", {}).get("ro", ""))}'></td></tr>
<tr><th>Adresa (RU)</th><td><input type='text' name='addr_ru' value='{e(cfg.get("address", {}).get("ru", ""))}'></td></tr>
</table>
<p class='hint'>Numele, telefonul și adresa apar în bot ({_ic('phone')} contacte), în bara laterală
a registrului și pe documentele tipărite (043/e, acord, raport de casă).
Restul secțiunilor nu sunt atinse la salvare.</p>
<button class='savebtn'>{_ic('save')} Salvează</button>
</form>"""
    return _sec_page(body, "setări · clinica", msg)


@router.get("/admin/settings/crypt", response_class=HTMLResponse)
async def settings_crypt(request: Request, msg: str = ""):
    """Шифрование картотеки: состояние и включение.

    ⭐ Включение идёт в ДВА шага через отдельную страницу с листом, и это не
    вежливость. Лист восстановления — единственное, что стоит между клиникой и
    полной потерей данных при смене ПК, а единственный момент, когда его точно
    прочитают, — сейчас. Кнопки «включить» одним нажатием здесь нет намеренно.
    """
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not db.IS_SQLITE:
        return _sec_page("<p class='hint'>Ediția cloud folosește PostgreSQL — "
                         "criptarea fișierului nu se aplică.</p>",
                         "setări · criptare", msg)
    d = _data_dir()
    st = dbkey.state()
    pending = bool(d and (d / dbkey.PENDING_FILE).exists())

    if pending:
        body = (f"<h2>{_ic('lock')} Criptarea evidenței</h2>"
                "<div class='banner warn'>Criptarea este pregătită și se aplică "
                "la următoarea pornire a programului.</div>"
                "<div class='nav'><a class='primary' href='/admin/settings/crypt/sheet'>"
                f"{_ic('print')} Deschide foaia de recuperare</a></div>")
    elif st == dbkey.OK:
        body = f"""
<h2>{_ic('lock')} Criptarea evidenței</h2>
<div class='banner ok'>Evidența este criptată. Fișierul <b>dental.db</b> nu poate
fi citit pe alt calculator sau de pe alt cont Windows.</div>
<p class='hint'>Copiile zilnice din <code>data\\backups</code> sunt și ele
criptate. Arhiva de rezervă (Setări › Copie de rezervă) rămâne independentă:
înăuntru baza este necriptată, protejată de parola arhivei — ca să nu depindă
de aceeași cheie.</p>
<div class='nav'><a href='/admin/settings/crypt/sheet'>{_ic('print')} Foaia de recuperare</a></div>
<form method='post' action='/admin/settings/crypt/off'
      onsubmit="return confirm('Evidența va fi decriptată la următoarea pornire. Continuați?')">
  <button class='rowdel'>Oprește criptarea</button>
</form>"""
    else:
        # ⚠️ Тон здесь — РЕШЕНИЕ Олега (08-09): шифрование это ОПЦИЯ, а не
        # рекомендация. Требование закона 195 закрывает BitLocker, и программа
        # его проверяет сама; клинике, которая включит шифрование, достаётся
        # обязанность хранить лист восстановления. Уговаривать её взять эту
        # обязанность не за что — экран обязан честно назвать и то, что оно
        # даёт, и то, чего стоит, а выбор оставить директору.
        body = f"""
<h2>{_ic('lock')} Criptarea evidenței</h2>
<div class='banner ok'>Nu este obligatorie. Cerința Legii 195 este acoperită de
criptarea discului (BitLocker) — starea ei o verifică programul singur, în
<b>Stare sistem</b>. Aceasta este o măsură în plus, pentru cine o dorește.</div>
<p class='hint'><b>Ce face.</b> Acum <b>data\\dental.db</b> este o bază SQLite
obișnuită: copiată de pe calculator, se deschide cu orice program. Criptarea o
face inutilizabilă în afara acestui calculator. Are sens mai ales dacă
programul stă pe un laptop care iese din clinică.</p>
<p class='hint'><b>Ce cere în schimb.</b> Cheia este legată de contul Windows de
pe acest calculator. După reinstalarea Windows sau la schimbarea calculatorului
evidența se deschide <b>numai</b> cu codul de pe foaia de recuperare — foaia
devine responsabilitatea clinicii, iar pierderea ei nu poate fi reparată de
nimeni, nici de noi. De aceea pasul următor este tipărirea ei.</p>
<p class='hint'><b>Ce NU face.</b> Nu vă apără de cineva care lucrează la acest
calculator sub acest cont Windows. Acolo lucrează parola de intrare și blocarea
ecranului (Win+L).</p>
<form method='post' action='/admin/settings/crypt/prepare'>
  <button class='savebtn'>Pregătește criptarea ›</button>
</form>"""
    return _sec_page(body, "setări · criptare", msg)


# Ключ, показанный на листе, но ещё НЕ заказанный. Заказ (pending-файл на
# диске) появляется только на галочке «Am tipărit foaia»: докстринг dbkey
# обещает, что включение ТРЕБУЕТ подтверждения листа, а раньше pending клал
# уже /crypt/prepare — директор закрывал страницу листа, не печатая, и
# следующий старт молча шифровал картотеку. Без листа на бумаге это потеря
# базы при первой же смене ПК. Память процесса — правильное место ровно
# потому, что перезапуск её стирает: не подтверждено = не заказано.
_SHEET_KEY: bytes | None = None


@router.post("/admin/settings/crypt/prepare")
async def settings_crypt_prepare(request: Request):
    global _SHEET_KEY
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    if not d:
        return RedirectResponse("/admin/settings/crypt?msg=bad_crypt", status_code=303)
    # ⛔ Второе нажатие НЕ создаёт новый ключ (найдено враждебным ревью 08-09).
    # Раньше оно перезаписывало ожидающий ключ, и напечатанный лист переставал
    # подходить; а нажатие при УЖЕ включённом шифровании было хуже вдвойне:
    # заказ на переезд не мог выполниться никогда (база под старым ключом),
    # экран навсегда застревал на «криптование подготовлено», а лист печатался
    # с ключом, который не открывает ничего. Прежний ключ при этом становился
    # недоступен для печати. Открытая в соседней вкладке страница — обычное
    # дело в регистратуре, так что это не теоретический случай.
    if dbkey.enabled(d):
        return RedirectResponse("/admin/settings/crypt?msg=crypt_on", status_code=303)
    if dbkey.load_pending(d) is None and _SHEET_KEY is None:
        _SHEET_KEY = dbkey.generate()
    return RedirectResponse("/admin/settings/crypt/sheet", status_code=303)


@router.get("/admin/settings/crypt/sheet", response_class=HTMLResponse)
async def settings_crypt_sheet(request: Request):
    """Печатный лист восстановления. Вид намеренно как у листа BitLocker:
    клиника этот ритуал уже прошла и знает, что такую бумагу кладут в папку."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    key = None
    if d and (d / dbkey.PENDING_FILE).exists():
        key = dbkey.load_pending(d)
    if key is None and not dbkey.enabled(d):
        key = _SHEET_KEY                 # показан, но ещё не подтверждён
    if key is None:
        key = dbkey.load()
    if key is None:
        return RedirectResponse("/admin/settings/crypt?msg=bad_crypt", status_code=303)
    # подтверждение нужно и ожидающему заказу, и ещё не заказанному листу
    pending = bool(d and ((d / dbkey.PENDING_FILE).exists()
                          or (_SHEET_KEY is not None and not dbkey.enabled(d))))
    e = html.escape
    confirm = ("""
<form class='noprint' method='post' action='/admin/settings/crypt/confirm'>
  <label class='ack'><input type='checkbox' name='ack' value='1' required>
  Am tipărit foaia și am pus-o în mapa clinicii</label>
  <button class='savebtn'>Activează criptarea</button>
</form>""" if pending else "")
    return HTMLResponse(f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>{e(eng.CLINIC_NAME)} — foaie de recuperare</title><style>
 body{{font-family:'Segoe UI',system-ui,sans-serif;color:#111;max-width:170mm;
      margin:0 auto;padding:12mm}}
 h1{{font-size:19pt;margin:0 0 2mm}}
 .sub{{color:#555;font-size:10pt;margin-bottom:6mm}}
 .code{{font-family:ui-monospace,Consolas,monospace;font-size:15pt;line-height:1.9;
       letter-spacing:.06em;border:2px solid #111;border-radius:3mm;padding:6mm;
       word-break:break-all;text-align:center;margin-bottom:6mm}}
 .box{{border:1px solid #999;border-radius:2mm;padding:5mm;font-size:10.5pt;
      line-height:1.6;margin-bottom:5mm}}
 .warn{{border-color:#B45309;background:#FFFBEB}}
 .sign{{margin-top:10mm;display:flex;justify-content:space-between;font-size:10pt}}
 .noprint{{margin:8mm 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
 .ack{{display:flex;gap:8px;align-items:center;font-size:11pt}}
 button{{background:#0E9F8A;color:#fff;border:none;border-radius:8px;
        padding:10px 22px;font-size:14px;cursor:pointer;font-family:inherit}}
 @media print{{.noprint{{display:none}}body{{padding:0}}}}
</style></head><body>
<div class="noprint"><button onclick="window.print()">{_ic('print')} Tipărește</button>
<a href="/admin/settings/crypt">{_ic('chev-l')} Înapoi</a></div>
<h1>Foaie de recuperare — evidența clinicii</h1>
<div class="sub">{e(eng.CLINIC_NAME)} · DentPilot · generată {datetime.now(eng.TZ).strftime('%d.%m.%Y')}</div>
<div class="code">{e(dbkey.format_recovery(key))}</div>
<div class="box warn"><b>Fără acest cod evidența nu poate fi deschisă de nimeni —
nici de furnizorul programului.</b> Nu există copie de rezervă a lui: codul
există doar pe această foaie.</div>
<div class="box">
<b>Când este nevoie de el:</b> după reinstalarea Windows, la mutarea programului
pe alt calculator, la schimbarea contului Windows sau a discului.<br>
<b>Când NU este nevoie:</b> niciodată în lucrul obișnuit — nici la pornire, nici
la actualizare. Programul îl cere doar în situațiile de mai sus.<br><br>
<b>Unde se păstrează:</b> în mapa „Legea 195”, lângă actul BitLocker — adică nu
în calculator. O copie poate fi ținută în alt loc (seif, altă adresă).
</div>
<div class="box">Litera „O” din cod este întotdeauna literă: cifrele 0, 1, 8 și 9
nu apar în el. Codul poate fi introdus cu litere mici și cu spații.</div>
<div class="sign"><span>Predat: ____________________</span>
<span>Data: ____________</span></div>
{confirm}
</body></html>""")


@router.post("/admin/settings/crypt/confirm")
async def settings_crypt_confirm(request: Request, ack: str = Form("")):
    """Подтверждение и перезапуск. Сам переезд делает ЛАУНЧЕР до старта
    приложения: базу нельзя подменять под открытым соединением.

    ⭐ Заказ (pending-файл) кладётся ИМЕННО ЗДЕСЬ, на галочке «лист напечатан»,
    а не в /prepare: закрытая без подтверждения страница листа не должна
    оставлять на диске ничего, что следующий старт исполнит как приказ
    шифровать. Ключ заказа — ровно тот, что напечатан на листе (_SHEET_KEY)."""
    global _SHEET_KEY
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if ack != "1":
        return RedirectResponse("/admin/settings/crypt/sheet", status_code=303)
    d = _data_dir()
    if not d:
        return RedirectResponse("/admin/settings/crypt?msg=bad_crypt", status_code=303)
    if not dbkey.enabled(d) and dbkey.load_pending(d) is None:
        if _SHEET_KEY is None or not dbkey.request_encrypt(d, _SHEET_KEY):
            return RedirectResponse("/admin/settings/crypt?msg=bad_crypt",
                                    status_code=303)
    _SHEET_KEY = None
    return HTMLResponse(_restart_page("Criptarea a fost activată",
                                      "/admin/settings/crypt"))


@router.post("/admin/settings/crypt/off")
async def settings_crypt_off(request: Request):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    if not d:
        return RedirectResponse("/admin/settings/crypt?msg=bad_crypt", status_code=303)
    dbkey.request_decrypt(d)
    return HTMLResponse(_restart_page("Criptarea va fi oprită",
                                      "/admin/settings/crypt"))


@router.get("/admin/settings/theme", response_class=HTMLResponse)
async def settings_theme(request: Request, msg: str = ""):
    """Как клиника выглядит: стиль, фирменный цвет, логотип.

    ⭐ Выбор здесь НАРОЧНО короткий — три стиля и шесть цветов плюс свой. Полсотни
    ползунков превратили бы программу в конструктор CSS: каждая клиника собрала
    бы себе нечитаемое, а поддержка получила бы столько же разных экранов,
    сколько установок. Стиль и цвет — ровно те две вещи, по которым люди узнают
    «своё», всё остальное держит дизайн-система.
    """
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    th = theme.current()
    e = html.escape
    preset_hex = [c for c, _ in theme.PRESETS]
    custom = th["primary"] not in preset_hex

    # ⭐ Палитры считает СЕРВЕР и отдаёт готовыми. Живому предпросмотру нельзя
    # повторять арифметику из core/theme.py: два расчёта неизбежно разойдутся, и
    # клиника увидит при выборе один цвет, а после сохранения другой. Своего
    # цвета в наборе нет — за ним предпросмотр сходит на /theme/palette.
    pal_js = js_json({st: {c: theme.palette(c, st) for c in preset_hex}
                     for st in theme.STYLES})
    sty_js = js_json(theme.STYLES)

    styles = "".join(
        f"<label class='th-style'>"
        f"<input type='radio' name='style' value='{e(key)}'"
        f"{' checked' if key == th['style'] else ''}>"
        f"<span class='th-card' style=\"border-radius:{v['--r-card']};"
        f"background:{v['--bg']};border-color:{v['--line']};box-shadow:{v['--sh']}\">"
        f"<i style=\"border-radius:{v['--r-ctl']}\"></i><u></u><u class='sh'></u></span>"
        f"<b>{e(theme.STYLE_LABEL[key][0])}</b>"
        f"<small>{e(theme.STYLE_LABEL[key][1])}</small></label>"
        for key, v in theme.STYLES.items())

    colors = "".join(
        f"<label class='th-c' title='{e(name)}'>"
        f"<input type='radio' name='primary' value='{e(hexv)}'"
        f"{' checked' if hexv == th['primary'] else ''}>"
        f"<span style='background:{e(hexv)}'></span></label>"
        for hexv, name in theme.PRESETS)

    logo = theme.logo_url()
    logo_box = (f"<img class='th-logo' src='{e(logo)}' alt='logo'>" if logo
                else "<div class='th-logo none'>fără logo</div>")
    logo_del = (f"<button name='act' value='del' class='pl-btn'>{_ic('trash')} Șterge</button>"
                if logo else "")

    body = f"""
<h2>{_ic("palette")} Aspectul clinicii</h2>
<form method='post' action='/admin/settings/save' id='thf'>
<input type='hidden' name='part' value='theme'>

<h3 class='th-h'>Stil interfață</h3>
<div class='th-styles'>{styles}</div>

<h3 class='th-h'>Culoare principală</h3>
<div class='th-colors'>{colors}
  <label class='th-c th-custom' title='Culoare personalizată'>
    <input type='radio' name='primary' value='custom'{' checked' if custom else ''}>
    <span class='pick'>{_ic('palette')}</span>
  </label>
  <input type='color' name='custom' id='thcustom' value='{e(th["primary"])}'>
</div>
<p class='hint'>Culoarea se aplică butoanelor, meniului și accentelor.
Roșu pentru urgențe, galben pentru avertismente și verde pentru „confirmat”
rămân neschimbate — acolo culoarea înseamnă ceva, nu decorează.</p>
<button class='savebtn'>{_ic('save')} Salvează</button>
</form>

<h3 class='th-h'>Logo</h3>
<div class='th-logowrap'>
  {logo_box}
  <form method='post' action='/admin/settings/theme/logo'
        enctype='multipart/form-data' class='th-logof'>
    <div class='filepick'>
      <input type='file' name='file' id='thlogo' accept='image/png,image/jpeg'>
      <label for='thlogo'>{_ic('clip')} Alege fișier…</label>
    </div>
    <button class='pl-btn primary'>Încarcă</button>
    {logo_del}
  </form>
</div>
<p class='hint'>PNG sau JPEG, cel mult 2 MB. Apare pe ecranul de intrare și în
antetul documentelor tipărite (043/e, acord, raport de casă). Logoul rămâne la
actualizarea programului — se păstrează lângă profilul clinicii.</p>

<script>
(function(){{
  var PAL = {pal_js}, STY = {sty_js};
  var f = document.getElementById('thf'), root = document.documentElement;
  function put(o){{ for (var k in o) root.style.setProperty(k, o[k]); }}
  function style(){{ var r = f.querySelector('input[name=style]:checked');
                     return r ? r.value : 'modern'; }}
  function color(){{ var r = f.querySelector('input[name=primary]:checked');
                     if (!r) return null;
                     return r.value === 'custom'
                       ? document.getElementById('thcustom').value : r.value; }}
  function apply(){{
    var st = style(), c = color();
    put(STY[st] || {{}});
    if (!c) return;
    if (PAL[st] && PAL[st][c.toUpperCase()]) {{ put(PAL[st][c.toUpperCase()]); return; }}
    /* своего цвета в наборе нет — палитру считает сервер, здесь её не выводят */
    fetch('/admin/settings/theme/palette?c=' + encodeURIComponent(c)
          + '&style=' + encodeURIComponent(st))
      .then(function(r){{ return r.ok ? r.json() : null; }})
      .then(function(p){{ if (p) put(p); }})
      .catch(function(){{}});
  }}
  f.addEventListener('change', function(ev){{
    if (ev.target.name === 'custom') {{
      f.querySelector('input[name=primary][value=custom]').checked = true;
    }}
    apply();
  }});
  document.getElementById('thcustom').addEventListener('input', apply);
}})();
</script>"""
    return _sec_page(body, "setări · aspectul clinicii", msg)


@router.get("/admin/settings/theme/palette")
async def settings_theme_palette(request: Request, c: str = "", style: str = ""):
    """Палитра для своего цвета — единственный способ показать предпросмотр,
    не переписывая расчёт на JavaScript. Отдаёт то же, что уедет в CSS при
    сохранении, поэтому «увидел одно, получил другое» здесь невозможно."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    rgb = theme.parse_hex(c)
    if rgb is None:
        return JSONResponse({}, status_code=400)
    st = style if style in theme.STYLES else theme.DEFAULT_STYLE
    return JSONResponse(theme.palette(theme.to_hex(rgb), st))


@router.post("/admin/settings/theme/logo")
async def settings_theme_logo(request: Request, file: UploadFile = File(None),
                              act: str = Form("")):
    """Логотип клиники. Отдельным маршрутом, а не полем общей формы: файл идёт
    multipart, и сваливать его в тот же обработчик, что правит профиль, значит
    гонять картинку через разбор настроек на каждое сохранение цвета."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    back = "/admin/settings/theme"
    th = theme.current()
    if act == "del":
        theme.clear_logo()
        name = None
        msg = "no_logo"
    else:
        data = await file.read(theme.LOGO_MAX + 1) if file is not None else b""
        if file is not None:
            await file.close()
        try:
            name = theme.save_logo(data)
        except (ValueError, OSError):
            return RedirectResponse(f"{back}?msg=bad_logo", status_code=303)
        msg = "ok_logo"
    # ⚠️ Стиль и цвет переносим ЯВНО: _finish_cfg заменяет секцию целиком, и
    # сохранение логотипа сбросило бы выбранный цвет на фирменный зелёный.
    cfg = _finish_cfg(theme={"style": th["style"], "primary": th["primary"],
                             "logo": name})
    if eng.save_config(cfg) is not None:
        return RedirectResponse(f"{back}?msg=save_err", status_code=303)
    return RedirectResponse(f"{back}?msg={msg}", status_code=303)


@router.get("/admin/settings/hours", response_class=HTMLResponse)
async def settings_hours(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    cfg = eng.CONFIG

    def _break_opts(sel) -> str:
        out = [f"<option value=''{' selected' if sel is None else ''}>—</option>"]
        for x in range(HOUR_MIN, HOUR_MAX + 1):
            out.append(f"<option value='{x}'{' selected' if sel == x else ''}>{x}:00</option>")
        return "".join(out)

    hours_rows = []
    for day in _DOW_ORDER:
        h = cfg.get("hours", {}).get(day)
        closed = h is None
        hv = list(h) if h else [9, 18]
        f, t = int(hv[0]), int(hv[1])
        bf = int(hv[2]) if len(hv) >= 4 else None
        bt = int(hv[3]) if len(hv) >= 4 else None
        hours_rows.append(
            f"<tr><td>{_DOW_FULL[day]}</td>"
            f"<td><input type='checkbox' id='hc_{day}'{' checked' if closed else ''}> închis</td>"
            f"<td><select id='hf_{day}'>{_hour_opts(f)}</select></td>"
            f"<td><select id='ht_{day}'>{_hour_opts(t, HOUR_MIN + 1, HOUR_MAX)}</select></td>"
            f"<td><select id='hb_{day}'>{_break_opts(bf)}</select></td>"
            f"<td><select id='he_{day}'>{_break_opts(bt)}</select></td></tr>"
        )
    body = f"""
<h2>{_ic("clock")} Program de lucru</h2>
<form method='post' action='/admin/settings/save' onsubmit='return collectHours()'>
<input type='hidden' name='part' value='hours'>
<input type='hidden' name='payload' id='payload'>
<table class='set'>
<tr><th>Ziua</th><th>Închis</th><th>De la</th><th>Până la</th>
<th>Pauză de la</th><th>Pauză până la</th></tr>
{''.join(hours_rows)}
</table>
<p class='hint'>Pauza (ex. prânz 13:00–14:00) dispare din calendarul zilei și din registru.
«—» = fără pauză. Medicul își poate îngusta orele în fișa lui, dar nu le poate lărgi
peste programul clinicii.</p>
<button class='savebtn'>{_ic('save')} Salvează programul</button>
</form>
<script>
function collectHours() {{
  const days = ['mon','tue','wed','thu','fri','sat','sun'];
  const hours = {{}};
  for (const d of days) {{
    if (document.getElementById('hc_' + d).checked) {{ hours[d] = null; continue; }}
    const f = parseInt(document.getElementById('hf_' + d).value);
    const t = parseInt(document.getElementById('ht_' + d).value);
    const bf = document.getElementById('hb_' + d).value;
    const bt = document.getElementById('he_' + d).value;
    if (bf !== '' && bt !== '') hours[d] = [f, t, parseInt(bf), parseInt(bt)];
    else hours[d] = [f, t];
  }}
  document.getElementById('payload').value = JSON.stringify({{hours: hours}});
  return true;
}}
</script>"""
    return _sec_page(body, "setări · program de lucru", msg)


@router.get("/admin/settings/services", response_class=HTMLResponse)
async def settings_services(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    cfg = eng.CONFIG
    e = html.escape

    def _color_opts(sel: str) -> str:
        out = [f"<option value=''{' selected' if not sel else ''}>auto</option>"]
        for k, ro in _PALETTE_RO.items():
            out.append(f"<option value='{k}'{' selected' if sel == k else ''}>{ro}</option>")
        return "".join(out)

    def _dur_opts(sel) -> str:
        cur = int(sel) if sel else 60
        return "".join(f"<option value='{x}'{' selected' if cur == x else ''}>{x} min</option>"
                       for x in (15, 30, 45, 60, 90, 120))

    svc_rows = "".join(
        f"<tr><td><input type='hidden' class='s_id' value='{e(s['id'])}'>"
        f"<input type='text' class='s_ro' value='{e(s['ro'])}'></td>"
        f"<td><input type='text' class='s_ru' value='{e(s['ru'])}'></td>"
        f"<td><input type='text' class='s_price' value='{e(str(s.get('price', '')) if not isinstance(s.get('price'), dict) else s['price'].get('ro', ''))}'></td>"
        f"<td><select class='s_dur'>{_dur_opts(s.get('duration'))}</select></td>"
        f"<td><select class='s_color'>{_color_opts(s.get('color', ''))}</select></td>"
        f"<td style='text-align:center'><input type='checkbox' class='s_urg'{' checked' if s.get('urgent') else ''}></td>"
        f"<td><input type='text' class='s_docs' value='{e(' '.join(s.get('docs', [])))}' placeholder='gol = toți'></td>"
        f"<td><button type='button' class='rowdel' onclick='this.closest(\"tr\").remove()'>{_ic('close')}</button></td></tr>"
        for s in cfg["services"]
    )
    doc_ids_hint = ", ".join(f"{d['id']}={e(d['name'])}" for d in cfg["doctors"])
    body = f"""
<h2>{_ic("tooth")} Servicii</h2>
<form method='post' action='/admin/settings/save' onsubmit='return collectServices()'>
<input type='hidden' name='part' value='services'>
<input type='hidden' name='payload' id='payload'>
<table class='set' id='svc_t'>
<tr><th>Denumire (RO)</th><th>Denumire (RU)</th><th style='width:120px'>Preț</th>
<th style='width:90px'>Durată</th><th style='width:100px'>Culoare</th>
<th style='width:40px'>{_ic('sos')}</th><th style='width:140px'>Medici (id)</th><th></th></tr>
<tbody id='svc_tb'>{svc_rows}</tbody>
</table>
<button type='button' class='addrow' onclick='addSvc()'>+ Adaugă serviciu</button>
<p class='hint'>Coloana «Medici»: id-uri separate prin spațiu ({doc_ids_hint}); gol = toți medicii.
{_ic('sos')} = flux urgent (fără alegerea medicului, sloturi din ziua curentă).</p>
<button class='savebtn'>{_ic('save')} Salvează serviciile</button>
</form>

<script>
const SVC_COLORS = {js_json(_PALETTE_RO)};
function addSvc() {{
  const tb = document.getElementById('svc_tb');
  const tr = document.createElement('tr');
  let opts = "<option value=''>auto</option>";
  for (const k in SVC_COLORS) opts += "<option value='" + k + "'>" + SVC_COLORS[k] + "</option>";
  let dopts = "";
  for (const x of [15, 30, 45, 60, 90, 120])
    dopts += "<option value='" + x + "'" + (x === 60 ? " selected" : "") + ">" + x + " min</option>";
  tr.innerHTML = "<td><input type='hidden' class='s_id' value=''>" +
    "<input type='text' class='s_ro' placeholder='Serviciu'></td>" +
    "<td><input type='text' class='s_ru' placeholder='Услуга'></td>" +
    "<td><input type='text' class='s_price' placeholder='500 MDL'></td>" +
    "<td><select class='s_dur'>" + dopts + "</select></td>" +
    "<td><select class='s_color'>" + opts + "</select></td>" +
    "<td style='text-align:center'><input type='checkbox' class='s_urg'></td>" +
    "<td><input type='text' class='s_docs' placeholder='gol = toți'></td>" +
    "<td><button type='button' class='rowdel' onclick='this.closest(\\"tr\\").remove()'>{_ic('close')}</button></td>";
  tb.appendChild(tr);
}}
function collectServices() {{
  const services = [];
  document.querySelectorAll('#svc_tb tr').forEach(tr => {{
    services.push({{ id: tr.querySelector('.s_id').value,
                    ro: tr.querySelector('.s_ro').value,
                    ru: tr.querySelector('.s_ru').value,
                    price: tr.querySelector('.s_price').value,
                    duration: tr.querySelector('.s_dur').value,
                    color: tr.querySelector('.s_color').value,
                    urgent: tr.querySelector('.s_urg').checked,
                    docs: tr.querySelector('.s_docs').value }});
  }});
  // валидация ДО отправки: при серверной ошибке форма перерисуется из
  // сохранённого конфига и все правки админа пропадут — не доводим до этого.
  // Правила — ТЕ ЖЕ, что у сервера (_val_services): дубликат по RO, по RU и
  // перекрёстный ro/ru, причём пустой RU наследует RO; иначе payload проходил
  // клиента, бился об сервер — и правки таблицы всё равно терялись
  const seen = {{}};
  for (const s of services) {{
    const roRaw = s.ro.trim().slice(0, 60);
    if (!roRaw) continue;
    const ruRaw = s.ru.trim().slice(0, 60) || roRaw;
    const ro = roRaw.toLowerCase(), ru = ruRaw.toLowerCase();
    const clash = seen[ro] === true ? roRaw
                : (ru !== ro && seen[ru] === true) ? ruRaw : null;
    if (clash !== null) {{
      alert('Două rânduri au aceeași denumire de serviciu (RO sau RU): «' +
            clash + '». Redenumiți unul dintre ele.');
      return false;
    }}
    seen[ro] = true;
    seen[ru] = true;
  }}
  document.getElementById('payload').value = JSON.stringify({{services: services}});
  return true;
}}
</script>"""
    return _sec_page(body, "setări · servicii", msg)


# Валидаторы по секциям: каждая страница присылает свой кусок, и проверяется
# ровно он. Слияние с остальным конфигом делает _finish_cfg — нетронутые
# секции переезжают КАК ЕСТЬ, без повторного разбора: прогон услуг через
# разбор формы превратил бы двуязычную цену {"ro","ru"} из демо-профиля в
# строку-огрызок.

def _val_clinic(data: dict) -> dict:
    name = str(data.get("name", "")).strip()[:80]
    phone = str(data.get("phone", "")).strip()[:30]
    if not name or not phone:
        raise ValueError("name/phone")
    addr_ro = str(data.get("address", {}).get("ro", "")).strip()[:120]
    addr_ru = str(data.get("address", {}).get("ru", "")).strip()[:120]
    return {"name": name, "phone": phone,
            "address": {"ro": addr_ro, "ru": addr_ru}}


def _val_theme(data: dict) -> dict:
    """Стиль и фирменный цвет. Логотип сюда не приходит — он меняется своим
    маршрутом, но обязан ПЕРЕЖИТЬ сохранение цвета, поэтому переносится из
    текущего профиля: `_finish_cfg` кладёт секцию целиком, и забытое поле
    означало бы «поменял цвет — пропал логотип»."""
    style = data.get("style")
    if style not in theme.STYLES:
        raise ValueError("style")
    choice = str(data.get("primary", ""))
    rgb = theme.parse_hex(str(data.get("custom", "")) if choice == "custom"
                          else choice)
    if rgb is None:
        raise ValueError("primary")
    keep = (eng.CONFIG.get("theme") or {}).get("logo")
    return {"style": style, "primary": theme.to_hex(rgb),
            "logo": keep if keep in theme.LOGO_NAMES.values() else None}


def _val_hours(data: dict) -> dict:
    hours = {}
    for day in _DOW_ORDER:
        h = data.get("hours", {}).get(day)
        if h is None:
            hours[day] = None
            continue
        vals = [int(x) for x in h]
        if len(vals) == 2:
            f, t = vals
            if not (0 <= f < t <= 24):
                raise ValueError("hours")
            hours[day] = [f, t]
        elif len(vals) == 4:
            f, t, bf, bt = vals
            if not (0 <= f < t <= 24 and f <= bf < bt <= t):
                raise ValueError("break")
            if bf <= f and bt >= t:
                raise ValueError("break=whole day")
            hours[day] = [f, t, bf, bt]
        else:
            raise ValueError("hours format")
    if all(v is None for v in hours.values()):
        raise ValueError("all closed")
    return hours


def _val_services(data: dict) -> tuple[list, dict]:
    # ⭐ Счётчики id ПЕРСИСТЕНТНЫ (cfg["seq"]) и только растут. Раньше id искался
    # как первый свободный d{n} среди текущего списка: удалили d2, добавили врача —
    # он получал d2 и наследовал историю уволенного. Теперь id не переиспользуется.
    seq = dict(eng.CONFIG.get("seq") or {})
    seq_d = int(seq.get("doctor", 0))
    seq_s = int(seq.get("service", 0))
    for d in eng.CONFIG.get("doctors", []):
        mnum = re.fullmatch(r"d(\d+)", str(d.get("id", "")))
        if mnum:
            seq_d = max(seq_d, int(mnum.group(1)))
    for s in eng.CONFIG.get("services", []):
        mnum = re.fullmatch(r"s(\d+)", str(s.get("id", "")))
        if mnum:
            seq_s = max(seq_s, int(mnum.group(1)))

    doc_ids = {d["id"] for d in eng.CONFIG.get("doctors", [])}
    # одинаковые подписи услуг ломали бы бэкфилл service_id и отчёты
    labels_seen: set[str] = set()

    services = []
    sused: set[str] = set()
    for s in data.get("services", []):
        ro = str(s.get("ro", "")).strip()[:60]
        ru = str(s.get("ru", "")).strip()[:60] or ro
        if not ro:
            continue
        if ro.casefold() in labels_seen or (ru.casefold() != ro.casefold()
                                            and ru.casefold() in labels_seen):
            raise ValueError("duplicate service label")
        labels_seen.add(ro.casefold())
        labels_seen.add(ru.casefold())
        sid = str(s.get("id", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]{1,20}", sid) or sid in sused:
            seq_s += 1
            sid = f"s{seq_s}"
        sused.add(sid)
        entry: dict = {"id": sid, "ro": ro, "ru": ru}
        price = str(s.get("price", "")).strip()[:60]
        if price:
            entry["price"] = price
        dur_raw = str(s.get("duration", "") or "").strip()
        if dur_raw.isdecimal() and int(dur_raw) in (15, 30, 45, 60, 90, 120):
            if int(dur_raw) != 60:
                entry["duration"] = int(dur_raw)  # 60 = дефолт, не пишем
        color_s = str(s.get("color", "")).strip()
        if color_s in SVC_PALETTE:
            entry["color"] = color_s
        if s.get("urgent"):
            entry["urgent"] = True
        docs = [tok for tok in re.split(r"[,\s]+", str(s.get("docs", "")))
                if tok in doc_ids]
        if docs:
            entry["docs"] = docs
        services.append(entry)
    if not services:
        raise ValueError("services")
    return services, {"doctor": seq_d, "service": seq_s}


def _finish_cfg(**updates) -> dict:
    """Слить проверенный кусок с текущим конфигом и доснарядить производное.

    Врачи всегда переезжают как есть: их каталог правится только в «Medici»
    (фото/e-mail/статус не должны теряться из-за сохранения настроек).
    `contacts` пересобирается из ИТОГОВЫХ значений — бот показывает адрес и
    часы одной строкой, и она обязана отражать любой сохранённый кусок.
    """
    cfg = dict(eng.CONFIG)
    cfg.pop("template", None)      # клинику заполнили — подсказка больше не нужна
    cfg.pop("_comment", None)
    cfg.update(updates)
    if not cfg.get("doctors"):
        raise ValueError("doctors")
    phone, hours = cfg["phone"], cfg["hours"]
    addr_ro = cfg.get("address", {}).get("ro", "")
    addr_ru = cfg.get("address", {}).get("ru", "")
    cfg["contacts"] = {
        "ro": (f"{_ic('pin')} {addr_ro}\n" if addr_ro else "")
              + f"{_ic('phone')} {phone}\n{_ic('clock')} {_hours_summary(hours, 'ro')}",
        "ru": (f"{_ic('pin')} {addr_ru}\n" if addr_ru else "")
              + f"{_ic('phone')} {phone}\n{_ic('clock')} {_hours_summary(hours, 'ru')}",
    }
    return cfg


def _build_config(data: dict) -> dict:
    """Полный payload одним куском — путь старой цельной формы. Живёт как
    рабочий: на нём тесты горячей перезагрузки, и им же может пользоваться
    что-то внешнее, собирающее конфиг целиком."""
    services, seq = _val_services(data)
    return _finish_cfg(**_val_clinic(data), hours=_val_hours(data),
                       services=services, seq=seq)


@router.post("/admin/update/check")
def admin_update_check(request: Request):
    """Проверить обновления прямо сейчас — не ждать следующего цикла.
    Синхронный def › threadpool, сетевой запрос не блокирует сервер."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    upd.check_now()
    return RedirectResponse("/admin/settings/system", status_code=303)


@router.post("/admin/update/run", response_class=HTMLResponse)
def admin_update_run(request: Request):
    """Одним кликом: скачать новый exe, подменить себя, перезапуститься.
    Синхронный def — FastAPI выполняет в threadpool (скачивание блокирует)."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    err = upd.self_update()
    if err:
        return RedirectResponse("/admin/settings/system?msg=upd_err", status_code=303)
    return standalone(f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="18;url=/admin/settings/system">
<title>Actualizare…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:__ACCENT__;color:__ON__;text-align:center}}
 .sp{{font-size:44px;animation:r 1.2s linear infinite;display:inline-block}}
 @keyframes r{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="sp">{_ic('refresh')}</div>
<h1>Se actualizează la {html.escape(upd.STATE['latest'])}…</h1>
<p>Programul se închide și repornește singur.<br>
Această pagină se va reîncărca automat în ~18 secunde.</p>
</body></html>""")


@router.post("/admin/users/save")
async def users_save(request: Request, uid: str = Form(...), name: str = Form(""),
                     role: str = Form(ROLE_MEDIC), doctor_id: str = Form(""),
                     pin: str = Form("")):
    """Завести сотрудника или поправить его доступ."""
    if (deny := require(request, PERM_USERS)) is not None:
        return deny
    uid, name, pin = uid.strip().lower()[:20], name.strip()[:60], pin.strip()
    if not _UID_RE.fullmatch(uid) or role not in ROLE_LABEL:
        return _set_back("bad_user")
    existing = find_user(uid)
    if not existing and not pin:
        return _set_back("bad_user")           # новому нужен пароль
    if pin and not pin_len_ok(pin):
        return _set_back("bad_user")
    # ⚠️ проверка ДО записи: вход идёт по одному лишь паролю, и два одинаковых
    # означают, что журнал доступа однажды назовёт не того человека
    if pin and not pin_free(pin, except_uid=uid):
        return _set_back("dup_user")
    # директор, снимающий с себя роль последним, запирает настройки НАВСЕГДА:
    # вернуть право станет некому
    if (existing and (existing.get("role") or ROLE_DIRECTOR) == ROLE_DIRECTOR
            and role != ROLE_DIRECTOR and n_directors(excluding=uid) == 0):
        return _set_back("last_dir")
    save_user(uid, name=name or (existing or {}).get("name") or uid, role=role,
              doctor_id=doctor_id if doctor_id in eng.DOCTORS else "",
              pin=pin or None)
    await remember_auth_file()      # своя запись — не «взлом» при след. старте
    return _set_back("ok_user")


@router.post("/admin/users/delete")
async def users_delete(request: Request, uid: str = Form(...)):
    if (deny := require(request, PERM_USERS)) is not None:
        return deny
    me = current_user(request)
    if me and me.get("id") == uid:
        return _set_back("self_user")
    if n_directors(excluding=uid) == 0:
        return _set_back("last_dir")
    delete_user(uid)
    await remember_auth_file()
    return _set_back("ok_user")


@router.post("/admin/backup/export")
async def admin_backup_export(request: Request, parola: str = Form(...)):
    """Зашифрованный архив клиники — целиком, для флешки или переезда.

    Пишется во временную папку и отдаётся файлом; временное подчищает фоновая
    задача после отдачи (как у выгрузки данных пациента). minlength в форме —
    вежливость, настоящая проверка тут: форму можно послать и без браузера.
    """
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    d = _data_dir()
    if d is None or not bkp.available():
        return RedirectResponse("/admin/settings", status_code=303)
    if len(parola) < bkp.MIN_PASS:
        return RedirectResponse("/admin/settings/backup?msg=bad_bkp_pass",
                                status_code=303)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_backup_"))
    dest = tmp / "backup.zip"
    clinic = os.environ.get("CLINIC_CONFIG", "")
    # ⚠️ Не только OSError: _db_snapshot нарочно бросает RuntimeError (ключ
    # шифрования не читается), а у драйвера базы свои классы (залоченная база,
    # сбой sqlcipher_export) — ловить их через db._SQ, второй бэкенд пишет
    # иначе. Раньше всё это уходило голым 500, а во временной папке навсегда
    # оставался НЕЗАШИФРОВАННЫЙ снимок картотеки — подчистка стояла только в
    # ветке OSError. Теперь прибирает finally: любой исход без готового архива
    # не оставляет в %TEMP% ничего.
    ok = False
    try:
        n = bkp.write_encrypted(d, pathlib.Path(clinic) if clinic else None,
                                parola, dest)
        ok = True
    except (OSError, RuntimeError, db._SQ.Error if db._SQ else ()) as ex:
        logging.getLogger("settings").warning("backup export: %r", ex)
        return RedirectResponse("/admin/settings/backup?msg=bad_bkp", status_code=303)
    finally:
        if not ok:
            shutil.rmtree(tmp, ignore_errors=True)
    logging.getLogger("settings").warning("encrypted backup exported (%d files)", n)
    return FileResponse(
        dest, filename=bkp.archive_name(), media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@router.post("/admin/telegram/save", response_class=HTMLResponse)
async def admin_telegram_save(request: Request, token: str = Form("")):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    env_file = os.environ.get("DENTART_ENV_FILE", "")
    if not (db.IS_SQLITE and env_file):
        return RedirectResponse("/admin/settings", status_code=303)
    tok = token.strip()
    if tok and not re.fullmatch(r"\d{6,12}:[\w-]{30,120}", tok):
        return RedirectResponse("/admin/settings/telegram?msg=bad_tok",
                                status_code=303)
    # в файл — шифротекст (dpapi), в окружение — открытый токен: им дальше
    # пользуются и бот, и статус на этой же странице. Если DPAPI недоступен
    # (запуск из исходников не под Windows), пишем как раньше — иначе правка
    # токена перестала бы работать у разработчика вовсе.
    try:
        envfile.set_value(pathlib.Path(env_file), "TELEGRAM_TOKEN",
                          (dpapi.protect(tok) or tok) if tok else "")
    except OSError as ex:
        # dental.env не читается — set_value отказывается, а не переписывает
        # файл одной строкой; окружение тоже не трогаем: файл и env едины
        logging.getLogger("settings").warning("env write: %r", ex)
        return RedirectResponse("/admin/settings/telegram?msg=bad_env",
                                status_code=303)
    os.environ["TELEGRAM_TOKEN"] = tok
    os.environ.pop("DENTART_TOKEN_UNREADABLE", None)
    if upd.restart_app() is not None:
        # dev-режим/тест-хук: перезапуск не случился — просто баннер
        return RedirectResponse("/admin/settings/telegram?msg=ok_tok",
                                status_code=303)
    return _restart_page("Token salvat", "/admin/settings/telegram")


def _restart_page(done: str, back_url: str) -> str:
    """Экран «настройка применится при следующем запуске».

    Для настроек, которые читает ЛАУНЧЕР до старта приложения: токен бота,
    сетевой доступ, шифрование картотеки.

    ⭐ Перезапуск НАСТОЯЩИЙ (08-10). Экран раньше обещал его и не делал:
    механизм всё это время лежал готовым в `update.py` — `restart_app()`,
    написанный «для применения токена и т.п.», — и просто не был подключён.
    Второй такой писать не стали, взяли этот.
    {_ic('sos')} Формулировка обязана оставаться правдой и тогда, когда перезапуск не
    состоялся: планировщик Windows может не отработать, а в облачном издании
    его нет вовсе. Поэтому текст говорит «закрываемся сейчас» и сразу даёт
    запасной ход — открыть с ярлыка. Обещать «окно вернётся само» без оговорки
    и было прошлой ошибкой.
    {_ic('sos')} `restart_app()` гасит процесс через ~1.2 с (`_exit_soon`), поэтому
    страницу отдаём ПЕРВОЙ, а гасимся уже после ответа.
    """
    auto = upd.restart_app() is None
    return standalone(f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>Repornire…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:__ACCENT__;color:__ON__;text-align:center}}
 p{{max-width:520px;line-height:1.55;font-size:15px}}
 a{{color:__ON__;font-weight:600;font-size:14px;margin-top:18px;display:inline-block}}
</style></head><body>
<h1>{_ic('check')} {done}</h1>
<p>{"<b>Programul se închide acum și pornește din nou</b> — setarea se aplică la pornire."
   if auto else
   "<b>Închideți programul și porniți-l din nou</b> — setarea se aplică la pornire."}</p>
<p style="opacity:.85;font-size:13.5px">Dacă fereastra nu revine în câteva
secunde, deschideți DentPilot de pe scurtătura de pe desktop. Datele clinicii nu
sunt afectate: oprirea programului nu șterge nimic.</p>
<a href="{back_url}">{_ic('chev-l')} Înapoi în setări</a>
</body></html>""")


@router.post("/admin/settings/save")
async def admin_settings_save(request: Request, payload: str = Form(""),
                              part: str = Form("")):
    """Сохранение настроек. `part` говорит, КАКОЙ кусок пришёл; без него —
    старый цельный payload. Ошибка возвращает на ТУ ЖЕ страницу-секцию:
    человек правил часы — там и должен увидеть, что не так."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    back = {"clinic": "/admin/settings/clinic", "hours": "/admin/settings/hours",
            "services": "/admin/settings/services",
            "theme": "/admin/settings/theme"}.get(part, "/admin/settings")
    try:
        if part == "theme":
            form = await request.form()
            cfg = _finish_cfg(theme=_val_theme({
                "style": form.get("style", ""),
                "primary": form.get("primary", ""),
                "custom": form.get("custom", "")}))
        elif part == "clinic":
            form = await request.form()
            cfg = _finish_cfg(**_val_clinic({
                "name": form.get("name", ""), "phone": form.get("phone", ""),
                "address": {"ro": form.get("addr_ro", ""),
                            "ru": form.get("addr_ru", "")}}))
        elif part == "hours":
            cfg = _finish_cfg(hours=_val_hours(json.loads(payload)))
        elif part == "services":
            services, seq = _val_services(json.loads(payload))
            cfg = _finish_cfg(services=services, seq=seq)
        else:
            cfg = _build_config(json.loads(payload))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return RedirectResponse(f"{back}?msg=bad_set", status_code=303)
    if eng.save_config(cfg) is not None:
        return RedirectResponse(f"{back}?msg=save_err", status_code=303)
    tg_refresh_meta()   # имя/телефон/орар уезжают и в профиль бота
    ok = "ok_theme" if part == "theme" else "ok_set"
    return RedirectResponse(f"{back}?msg={ok}", status_code=303)
