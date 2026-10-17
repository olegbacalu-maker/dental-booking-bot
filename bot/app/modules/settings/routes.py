"""Настройки клиники: профиль, часы работы, врачи и услуги, токен Telegram,
проверка и установка обновления.

Единственный экран, который ПИШЕТ `clinic.json` — и потому единственный, где
ошибка стоит дороже обычной: битый файл клиники означает старт с чужими
демо-врачами. Запись атомарная и с резервной копией, это в `eng.save_config`.

Правило то же: `core`, `db`, `engine` — да, `main.py` — нет.
"""
from __future__ import annotations

import html
import logging
import os
import pathlib
import re
import shutil
import tempfile
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse)
from starlette.background import BackgroundTask

from ... import db
from ... import dpapi, envfile
from ... import engine as eng
from ... import update as upd
from ...core.auth import (PERM_SETTINGS, ROLE_DIRECTOR, ROLE_LABEL, _guard, _pin_rec,
                          all_users, can, delete_user, find_user,
                          n_directors, pin_free, pin_len_ok,
                          remember_auth_file, request_user, require, save_user)
from ...core.layout import (_DOW_ORDER, _ic,
                            msg_banner,
                            react_shell, shell_model, _shell, standalone,
                            tg_configured, tg_status)
from ...core import bitlocker, dbkey, demo, theme
from ...core import license as lic
from ...core import sms_loop
from ...core.storage import _data_dir
from ...core.visits import SVC_PALETTE
from . import backup as bkp
from . import crypt
from . import system
from . import lan

router = APIRouter()

# id сотрудника: он попадает в подпись куки и в журнал доступа, поэтому только
# безопасные символы — точка в нём разделила бы куку не там, где надо
_UID_RE = re.compile(r"[a-z0-9_-]{2,20}")


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


# ---------- раздел «Setări»: хаб + страницы-секции (просьба Олега 08-06) ----------
#
# Раньше всё лежало одной страницей и путалось; теперь /admin/settings — хаб из
# плиток (те же .pl-tile, что в «Pacienți»: раздел не должен выглядеть чужим),
# а каждая секция — своя страница. ⚠️ Клиника/часы/услуги по-прежнему ОДИН
# clinic.json: каждая страница шлёт только свой кусок (part=...), сервер
# сливает его с остальным конфигом. Прислать всё и тут было бы проще, но тогда
# устаревшая вкладка «Program» затирала бы услуги, сохранённые из соседней.


# Навигация раздела — ОДНА на все страницы настроек, и это не совпадение:
# она никуда не ведёт, кроме как вверх. Отсюда и форма в модели (`frame.crumbs`).
_SEC_CRUMBS = [{"href": "/admin/settings", "icon": "chev-l", "label": "Setări"},
               {"href": "/admin", "icon": "home", "label": "Panou"}]


def _sec_page(body: str, sub: str, msg: str) -> str:
    nav = "<div class='nav'>" + "".join(
        f"<a href='{c['href']}'>{_ic(c['icon'])} {c['label']}</a>"
        for c in _SEC_CRUMBS) + "</div>"
    return _shell(nav + msg_banner(msg) + body, sub, active="set")


def _sec_react(screen: str, path: str, sub: str, msg: str,
               params: dict | None = None) -> str:
    """Страница-секция настроек на React-оболочке (B1).

    ⭐ Крошка едет в модели той же структурой, из которой её печатает и
    серверная секция (`_sec_page`, сегодня — Telegram): два владельца одной
    навигации разошлись бы молча.
    """
    return react_shell(screen, path,
                       shell_model("set", sub, msg=msg, crumbs=_SEC_CRUMBS),
                       params)


# Группы узла настроек (B5, шаг 9): порядок и подписи — ОДИН список, как в
# «Параметрах» Windows; плитка знает свою группу по адресу. Группа без плиток
# (нет auth.json — нет «Securitate», облако — нет «Date și rețea») не рисуется.
HUB_GROUPS = [("general", "General"), ("programari", "Programări"),
              ("medici", "Medici"), ("date", "Date și rețea"),
              ("securitate", "Securitate"), ("ajutor", "Ajutor")]
HUB_GROUP_OF = {"/admin/settings/system": "general", "/admin/license": "general",
                "/admin/settings/clinic": "general",
                "/admin/settings/theme": "general", "/admin/settings/hours": "programari",
                "/admin/settings/services": "programari",
                "/admin/settings/telegram": "programari", "/admin/settings/sms": "programari",
                "/admin/medici": "medici",
                "/admin/settings/lan": "date", "/admin/settings/crypt": "date",
                "/admin/settings/backup": "date", "/admin/settings/security": "securitate",
                "/admin/settings/faq": "ajutor"}


def _lic_hint(s) -> list[dict]:
    """Строка плитки «Licența» (02.10): срок словами страницы лицензии; при
    льготе и чтении — тоном смысла, как баннер. Считает сервер, как у всех плиток."""
    def d(x) -> str:
        return x.astimezone(eng.TZ).strftime("%d.%m.%Y")
    if s.claim is None:
        return [{"t": "neactivată"}]
    if s.state == lic.st.ACTIVE:
        what = "perioadă de probă" if s.claim.plan == "trial" else "activă"
        return [{"icon": "check", "t": f"{what} până la {d(s.valid_until)}"}]
    if s.state == lic.st.GRACE:
        return [{"icon": "sos", "t": f"expirată · funcționează până la {d(s.grace_until)}",
                 "tone": "amber"}]
    return [{"icon": "ban", "t": "regim de citire — Plătește acum", "tone": "red"}]


def _lan_available() -> bool:
    """Секция сети — только под лаунчером: слушающий адрес он выбирает по
    dental.env, а без файла (прогон, песочница, демо) переключать нечего."""
    return bool(os.environ.get("DENTART_ENV_FILE"))


def _hub_tiles() -> list[dict]:
    """Плитки хаба: адрес, иконка, тон, подпись и строка состояния КУСКАМИ —
    текст / иконка с текстом (и тоном) / точка цвета. Отдаёт их JSON API;
    состояние считает только сервер."""
    cfg = eng.CONFIG
    # короткое состояние обновления — подробности на странице «Stare sistem»
    if upd.can_self_update() or upd.newer_available():
        up_short = [{"icon": "refresh", "t": f"disponibilă {upd.STATE['latest']}",
                     "tone": "amber"}]
    elif upd.STATE["checked"] and not upd.STATE["error"]:
        up_short = [{"icon": "check", "t": "la zi"}]
    else:
        up_short = [{"t": "stare necunoscută"}]
    today_h = cfg.get("hours", {}).get(_DOW_ORDER[datetime.now(eng.TZ).weekday()])
    hours_short = (f"azi {int(today_h[0])}:00–{int(today_h[1])}:00" if today_h
                   else "azi închis")
    n_docs = sum(1 for d in cfg["doctors"] if eng.doctor_state(d) == "activ")
    _th = theme.current()

    bl_tone, _bl_txt = bitlocker.describe(bitlocker.STATE["code"],
                                          bitlocker.STATE["drive"])
    bl_flag = ([] if bl_tone in ("ok", "unknown")
               else [{"t": " · "}, {"icon": "ban", "t": "disc necriptat", "tone": "red"}]
               if bl_tone == "alarm"
               else [{"t": " · "}, {"icon": "sos", "t": "BitLocker", "tone": "amber"}])

    def tile(href: str, icon: str, tone: str, label: str, hint: list) -> dict:
        # группа — по адресу, из ОДНОГО словаря: плитка без группы уронит
        # сборку хаба KeyError — громко, а не молча без строки
        return {"href": href, "icon": icon, "tone": tone, "label": label, "hint": hint,
                "group": HUB_GROUP_OF[href]}

    tiles = [tile("/admin/settings/system", "info", "b", "Stare sistem",
                  [{"t": f"v{eng.APP_VERSION} · "}, *up_short, *bl_flag]),
             tile("/admin/settings/clinic", "clinic", "g", "Clinica",
                  [{"t": cfg["name"]}]),
             tile("/admin/settings/theme", "palette", "v", "Aspectul clinicii",
                  [{"t": f"{theme.STYLE_LABEL[_th['style']][0]} · "},
                   {"dot": _th["primary"]}, {"t": _th["primary"]}]
                  + ([{"t": " · logo"}] if theme.logo_url() else [])),
             tile("/admin/settings/hours", "clock", "v", "Program de lucru",
                  [{"t": hours_short}]),
             tile("/admin/settings/services", "tooth", "g", "Servicii",
                  [{"t": f"{len(cfg['services'])} servicii"}]),
             tile("/admin/medici", "med", "b", "Medici",
                  [{"t": f"{n_docs} activi · se editează în secțiunea Medici"}])]
    # Licența (02.10): срок и «Plătește acum» — на странице лицензии, плитка ведёт
    # туда. Только где лицензия применяется (`lic.applies`): у песочницы, демо и
    # облака срока нет, и плитка обещала бы пустую страницу.
    if (ls := lic.current()) is not None and lic.applies():
        tiles.insert(1, tile("/admin/license", "key", "g", "Licența", _lic_hint(ls)))
    if _lan_available():
        # Telegram заморожен (08-08): плитку видят только клиники с уже
        # настроенным токеном — grandfather, как секция в сайдбаре.
        # Прямой адрес /admin/settings/telegram жив для ручного включения.
        if tg_configured():
            tg = tg_status()
            tiles.append(tile("/admin/settings/telegram", "bot", "v", "Telegram Bot",
                              [{"icon": "check", "t": f"@{tg['username']}"}]
                              if tg["running"] else [{"t": "neconectat"}]))
        # Подпись выключенного состояния называет ВЕЩИ, а не режим: директор
        # ищет на хабе «второй компьютер», а не «сетевой доступ» (08-13).
        tiles.append(tile("/admin/settings/lan", "wifi", "b", "Acces din rețea",
                          [{"icon": "check", "t": "activ în rețeaua clinicii"}]
                          if lan.enabled()
                          else [{"t": "al doilea calculator, telefon — oprit"}]))
    # SMS-пакет (S6): плитка — только когда сервер предлагает пакет этой
    # клинике (S0 › 7: выключатель на сервере, не выпуск программы)
    if sms_loop.offered():
        acc = sms_loop.account() or {}
        tiles.append(tile("/admin/settings/sms", "chat", "v", "SMS pentru pacienți",
                          [{"icon": "check", "t": f"{int(acc.get('balance') or 0)} SMS rămase"}]
                          if sms_loop.active() else [{"icon": "ban", "t": "oprit", "tone": "amber"}]))
    _cs = dbkey.state()
    tiles.append(tile("/admin/settings/crypt", "lock", "g", "Criptarea evidenței",
                      {dbkey.OK: [{"icon": "check", "t": "activă"}],
                       dbkey.UNREADABLE: [{"icon": "ban", "t": "cheia nu se citește",
                                           "tone": "red"}]}.get(_cs, [{"t": "oprită"}])))
    if bkp.available():
        tiles.append(tile("/admin/settings/backup", "save", "b", "Copie de rezervă",
                          [{"t": "arhivă criptată AES-256"}]))
    if _pin_rec():
        tiles.append(tile("/admin/settings/security", "users", "g",
                          "Securitate și utilizatori",
                          [{"t": f"{len(all_users())} utilizatori"}]))
    # FAQ безусловно и последней: справка в конце списка — привычное место
    tiles.append(tile("/admin/settings/faq", "help", "v", "Întrebări frecvente",
                      [{"t": "copii de rezervă, mutare, Legea 195"}]))
    # Демо с сайта (core/demo.py): плитка раздела, который шлюз отклонит,
    # обещала бы экран, которого нет. Тот же список, что у отказа в main.py, —
    # не второй.
    return [t for t in tiles if not demo.refuses(t["href"])]


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, msg: str = ""):
    """Хаб настроек: по плитке на секцию, на каждой — живая строка состояния."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    # ⭐ B1: оболочку рисует React, сервер печатает голову и модель.
    return react_shell("settings_hub", request.url.path,
                       shell_model("set", "setările clinicii · pe secțiuni", msg=msg))


@router.get("/admin/settings/sms", response_class=HTMLResponse)
async def settings_sms(request: Request, msg: str = ""):
    """Setări › SMS (S6). Видит и регистратура (слово Олега 16.10): вход —
    `_guard`, не `require(PERM_SETTINGS)`; что только директору («Comandă»,
    тестовая SMS), решает JSON API. Крошка «Setări» — тому, кому она открыта."""
    if (deny := _guard(request)) is not None:
        return deny
    me = request_user()
    crumbs = (_SEC_CRUMBS if me is None or can(me, PERM_SETTINGS)
              else [{"href": "/admin", "icon": "home", "label": "Panou"}])
    return react_shell("settings_sms", request.url.path,
                       shell_model("sms" if sms_loop.offered() else "set",
                                   "memento-uri SMS pentru pacienți", msg=msg, crumbs=crumbs))


@router.get("/admin/settings/system", response_class=HTMLResponse)
async def settings_system(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    return _sec_react("settings_system", request.url.path,
                       "setări · stare sistem", msg)


@router.get("/admin/settings/telegram", response_class=HTMLResponse)
async def settings_telegram(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not os.environ.get("DENTART_ENV_FILE"):
        return RedirectResponse("/admin/settings", status_code=303)
    tok_set = bool(os.environ.get("TELEGRAM_TOKEN", "").strip())
    ph = ("••• token setat — introduceți altul pentru schimbare" if tok_set
          else "token de la @BotFather (ex. 123456789:AA...)")
    body = f"""
<h2>{_ic("bot")} Telegram — token bot</h2>
<p class='hint' style='margin-top:0'>Stare: {system.tg_line(tg_status())}</p>
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
    if not _lan_available():
        return RedirectResponse("/admin/settings", status_code=303)
    return _sec_react("settings_lan", request.url.path,
                       "setări · acces din rețea", msg)


def _set_lan(mode: str) -> str | None:
    """Переключить доступ из сети в dental.env. Код отказа (`bad_env`) или
    None; зовёт JSON API (`api.py`). Применение — перезапуск программы."""
    env_file = os.environ.get("DENTART_ENV_FILE", "")
    val = "1" if mode == "on" else ""
    try:
        envfile.set_value(pathlib.Path(env_file), "DENTART_LAN", val)
    except OSError as ex:
        # dental.env не читается/не пишется (придержан, чужая кодировка) —
        # set_value отказывается, а не переписывает файл; говорим честно
        logging.getLogger("settings").warning("env write: %r", ex)
        return "bad_env"
    os.environ["DENTART_LAN"] = val
    logging.getLogger("settings").warning(
        "LAN access %s", "ENABLED" if val else "disabled")
    return None


@router.get("/admin/settings/backup", response_class=HTMLResponse)
async def settings_backup(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not bkp.available():
        return RedirectResponse("/admin/settings", status_code=303)
    return _sec_react("settings_backup", request.url.path,
                       "setări · copie de rezervă", msg)


async def _last_logins() -> dict[str, str]:
    """Последний вход каждого — из meta (пишет /admin/login), НЕ из auth.json:
    файл под сигнализацией отпечатка, и запись «когда входил» при каждом входе
    дёргала бы её на ровном месте. uid → «13.08.2026 14:02» в часах клиники."""
    last: dict[str, str] = {}
    for u in all_users():
        v = await db.get_meta(f"last_login:{u['id']}")
        if v:
            try:
                last[u["id"]] = (datetime.fromisoformat(v).astimezone(eng.TZ)
                                 .strftime("%d.%m.%Y %H:%M"))
            except ValueError:
                pass
    return last


@router.get("/admin/settings/security", response_class=HTMLResponse)
async def settings_security(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if not _pin_rec():
        return RedirectResponse("/admin/settings", status_code=303)
    return _sec_react("settings_security", request.url.path,
                       "setări · securitate și utilizatori", msg)


@router.get("/admin/settings/faq", response_class=HTMLResponse)
async def settings_faq(request: Request, msg: str = ""):
    # под PERM_SETTINGS, как весь раздел: темы директорские (бэкап, перенос,
    # закон 195). Подсказки регистратуре — в самих экранах, не здесь.
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    return _sec_react("settings_faq", request.url.path,
                       "setări · întrebări frecvente", msg)


@router.get("/admin/settings/clinic", response_class=HTMLResponse)
async def settings_clinic(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    # Та же рамка и та же плашка ответа, а вместо формы — узел для бандла.
    return _sec_react("settings_clinic", request.url.path,
                       "setări · clinica", msg)


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
    return _sec_react("settings_crypt", request.url.path,
                       "setări · criptare", msg)


@router.get("/admin/settings/crypt/sheet", response_class=HTMLResponse)
async def settings_crypt_sheet(request: Request):
    """Печатный лист восстановления. Вид намеренно как у листа BitLocker:
    клиника этот ритуал уже прошла и знает, что такую бумагу кладут в папку.

    ⛔ Остаётся СЕРВЕРНЫМ и при включённом React-флаге: это печатный документ,
    и он обязан открываться, когда бандл не загрузился, — иначе код, без
    которого база не откроется никогда после смены ПК, показать нечем.
    """
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    key, pending = crypt.key_for_sheet(_data_dir())
    if key is None:
        return RedirectResponse("/admin/settings/crypt?msg=bad_crypt", status_code=303)
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
    приложения: базу нельзя подменять под открытым соединением."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    if ack != "1":
        return RedirectResponse("/admin/settings/crypt/sheet", status_code=303)
    if (err := crypt.confirm(_data_dir())) is not None:
        return RedirectResponse(f"/admin/settings/crypt?msg={err}", status_code=303)
    return _restart_now(crypt.ON_DONE, "/admin/settings/crypt")


# Образцы карточки визита для выбора вида — те же, что рисует React-экран
# (ThemeSettingsScreen › CardSample).
_CARD_SAMPLE = {
    "name": "<span class='cv'><b>Ana Popescu</b><small>09:00 · 60′ · Control</small></span>",
    "time": "<span class='cv'><em>09:00–10:00</em><b>Ana Popescu</b><small>Control</small></span>",
}


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
    return _sec_react("settings_theme", request.url.path,
                       "setări · aspectul clinicii", msg)


def _logo_action(data: bytes | None) -> str:
    """Логотип клиники: `data` — новый файл, None — убрать. Код ответа:
    ok_logo / no_logo / bad_logo / save_err. Зовёт JSON API (`api.py`)."""
    th = theme.current()
    if data is None:
        theme.clear_logo()
        name, msg = None, "no_logo"
    else:
        try:
            name = theme.save_logo(data)
        except (ValueError, OSError):
            return "bad_logo"
        msg = "ok_logo"
    # ⚠️ Стиль, цвет И галочку шапки переносим ЯВНО: _finish_cfg заменяет
    # секцию целиком, и сохранение логотипа сбросило бы выбранный цвет на
    # фирменный зелёный (а забытая галочка молча снимала бы логотип с шапки
    # при каждой замене файла — тот же класс, что и потеря логотипа при
    # смене цвета).
    cfg = _finish_cfg(theme={"style": th["style"], "primary": th["primary"],
                             "logo": name, "logo_topbar": th["logo_topbar"]})
    if eng.save_config(cfg) is not None:
        return "save_err"
    return msg


@router.get("/admin/settings/hours", response_class=HTMLResponse)
async def settings_hours(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    return _sec_react("settings_hours", request.url.path,
                       "setări · program de lucru", msg)


@router.get("/admin/settings/services", response_class=HTMLResponse)
async def settings_services(request: Request, msg: str = ""):
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    return _sec_react("settings_services", request.url.path,
                       "setări · servicii", msg)


# Валидаторы по секциям: каждая страница присылает свой кусок, и проверяется
# ровно он. Слияние с остальным конфигом делает _finish_cfg — нетронутые
# секции переезжают КАК ЕСТЬ, без повторного разбора: прогон услуг через
# разбор формы превратил бы двуязычную цену {"ro","ru"} из демо-профиля в
# строку-огрызок.

def _val_clinic(data: dict) -> dict:
    name = str(data.get("name", "")).strip()[:80]
    phone = str(data.get("phone", "")).strip()[:30]
    # текст ошибки — ИМЯ виновного поля: JSON API подсвечивает его на экране;
    # форме всё равно, она ловит ValueError целиком
    if not name:
        raise ValueError("name")
    if not phone:
        raise ValueError("phone")
    addr_ro = str(data.get("address", {}).get("ro", "")).strip()[:120]
    addr_ru = str(data.get("address", {}).get("ru", "")).strip()[:120]
    # юрлицо и IDNO — для подписываемых бумаг; оба необязательны (пустое =
    # вывесочное имя и жёлтый пропуск на листе), но набранный IDNO обязан
    # быть 13 цифрами: ошибка в нём уехала бы на acord и 043/e молча
    legal = str(data.get("legal_name", "")).strip()[:120]
    idno = re.sub(r"[\s.-]", "", str(data.get("idno", "")))
    if idno and not re.fullmatch(r"\d{13}", idno):
        raise ValueError("idno")
    return {"name": name, "phone": phone,
            "address": {"ro": addr_ro, "ru": addr_ru},
            "legal_name": legal, "idno": idno}


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
    cur = eng.CONFIG.get("theme") or {}
    keep = cur.get("logo")
    # Меню и шрифт (B5): нет поля — «не сообщали», прежний выбор остаётся
    # (клиент без этих групп не имеет права их сбросить — прайор 08-16);
    # есть, но незнакомое — отказ, как у стиля.
    menu = data.get("menu") or cur.get("menu") or theme.DEFAULT_MENU
    if menu not in theme.MENUS:
        raise ValueError("menu")
    font = data.get("font") or cur.get("font") or theme.DEFAULT_FONT
    if font not in theme.FONTS:
        raise ValueError("font")
    # вид карточки визита (03.10) — по тому же правилу, что меню и шрифт
    card = data.get("card") or cur.get("card") or theme.DEFAULT_CARD
    if card not in theme.CARD_LABEL:
        raise ValueError("card")
    # галочка «логотип в шапке» приходит ИЗ ФОРМЫ каждый раз (флажок на
    # странице всегда нарисован, когда есть логотип): нет поля = снята
    return {"style": style, "primary": theme.to_hex(rgb),
            "menu": menu, "font": font, "card": card,
            "logo": keep if keep in theme.LOGO_NAMES.values() else None,
            "logo_topbar": bool(data.get("logo_topbar"))}


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


@router.post("/admin/update/run", response_class=HTMLResponse)
def admin_update_run(request: Request):
    """Одним кликом: скачать новый exe, подменить себя, перезапуститься.
    Синхронный def — FastAPI выполняет в threadpool (скачивание блокирует)."""
    if (deny := require(request, PERM_SETTINGS)) is not None:
        return deny
    err = upd.self_update()
    if err == upd.BUSY:
        # второй клик, пока первый качает: не вторая закачка и не второе окно
        # UAC, а слово «уже идёт» (17.10, канарейка 1.44.0)
        return RedirectResponse("/admin/settings/system?msg=upd_busy", status_code=303)
    if err:
        return RedirectResponse("/admin/settings/system?msg=upd_err", status_code=303)
    # ⚠️ Цвет текста — ТЁМНЫЙ фирменный, не __ON__: `standalone()` кладёт под
    # страницу фон заставки (`_backdrop`, светлая подложка цвета клиники с
    # !important), и белый «on-teal» на нём был почти невидим — Олег увидел это
    # на канарейке 1.44.0. Шрифт и фон — как у остальных страниц этого класса.
    return standalone(f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="18;url=/admin/settings/system">
<title>Actualizare…</title><style>__FONTS__
 body{{font-family:'Inter','Segoe UI',system-ui,sans-serif;display:flex;flex-direction:column;
      align-items:center;justify-content:center;height:100vh;margin:0;background:__BG__;
      color:__ACCENT_D__;text-align:center;padding:16px;box-sizing:border-box}}
 h1{{color:__ACCENT_D__;font-size:26px;margin:14px 0 8px}}
 p{{color:#3b4a55;line-height:1.55;max-width:520px}}
 .sp{{font-size:44px;color:__ACCENT__;animation:r 1.2s linear infinite;display:inline-block}}
 .sp svg{{width:44px;height:44px}}
 @keyframes r{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div class="sp">{_ic('refresh')}</div>
<h1>Se actualizează la {html.escape(upd.STATE['latest'])}…</h1>
<p>Programul se închide și repornește singur.<br>
Această pagină se va reîncărca automat în ~18 secunde.</p>
</body></html>""")


async def _apply_user(uid: str, *, name: str, role: str, doctor_id: str,
                      pin: str) -> str:
    """Правила учётки (зовёт JSON API, `api.py`). Код ответа:
    bad_user / dup_user / last_dir / ok_user."""
    uid, name, pin = uid.strip().lower()[:20], name.strip()[:60], pin.strip()
    if not _UID_RE.fullmatch(uid) or role not in ROLE_LABEL:
        return "bad_user"
    existing = find_user(uid)
    if not existing and not pin:
        return "bad_user"                       # новому нужен пароль
    if pin and not pin_len_ok(pin):
        return "bad_user"
    # ⚠️ проверка ДО записи: вход идёт по одному лишь паролю, и два одинаковых
    # означают, что журнал доступа однажды назовёт не того человека
    if pin and not pin_free(pin, except_uid=uid):
        return "dup_user"
    # директор, снимающий с себя роль последним, запирает настройки НАВСЕГДА:
    # вернуть право станет некому
    if (existing and (existing.get("role") or ROLE_DIRECTOR) == ROLE_DIRECTOR
            and role != ROLE_DIRECTOR and n_directors(excluding=uid) == 0):
        return "last_dir"
    save_user(uid, name=name or (existing or {}).get("name") or uid, role=role,
              doctor_id=doctor_id if doctor_id in eng.DOCTORS else "",
              pin=pin or None)
    await remember_auth_file()      # своя запись — не «взлом» при след. старте
    return "ok_user"


async def _drop_user(me_id: str, uid: str) -> str:
    """Удаление учётки (зовёт JSON API, `api.py`). Код ответа:
    self_user / last_dir / ok_user."""
    if me_id and me_id == uid:
        return "self_user"
    if n_directors(excluding=uid) == 0:
        return "last_dir"
    delete_user(uid)
    await remember_auth_file()
    return "ok_user"


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
    if not env_file:
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
    return _restart_now("Token salvat", "/admin/settings/telegram", "ok_tok")


# Что сказать человеку, когда настройка применится только после перезапуска.
# Пара (жирная часть, хвост): страница выделяет первую <b>, JSON API отдаёт
# сплошным текстом; фраза одна, чтобы React не завёл свою.
RESTART_AUTO = ("Programul se închide acum și pornește din nou",
                " — setarea se aplică la pornire.")
RESTART_MANUAL = ("Închideți programul și porniți-l din nou",
                  " — setarea se aplică la pornire.")
RESTART_NOTE = ("Dacă fereastra nu revine în câteva secunde, deschideți DentPilot "
                "de pe scurtătura de pe desktop. Datele clinicii nu sunt afectate: "
                "oprirea programului nu șterge nimic.")


def restart_text(auto: bool) -> str:
    return "".join(RESTART_AUTO if auto else RESTART_MANUAL)


def _restart_now(done: str, back_url: str,
                 fallback: str = "") -> HTMLResponse | RedirectResponse:
    """Сохранили настройку, которую читает лаунчер, — перезапускаем программу.

    ⛔ ЕДИНСТВЕННАЯ точка запуска. Раньше маршрут звал `restart_app()` сам, а
    потом отдавал `_restart_page()`, который звал его ВТОРОЙ раз: задача
    планировщика заводилась дважды подряд, и спасал только `/f` в `/create`.
    Теперь запуск ровно один, а страница только рассказывает, чем он кончился.

    ⚠️ Отказ планировщика (политика домена, урезанные права, отключённая
    служба) — НЕ то же самое, что издание без перезапуска. В первом случае
    настройка сохранена, но не применится, пока программу не закроют и не
    откроют руками, — и это ровно то, что говорит страница при `auto=False`.
    Отдельного баннера для этого не заводим: тот же факт вторым текстом во
    втором месте разошёлся бы с этим при первой же правке (так уже было со
    STATUS_LABEL). `fallback` — для второго случая: запуск из исходников и
    облако, где закрывать и открывать нечего, а сообщить «сохранено» надо.
    """
    err = upd.restart_app()
    if err is not None and fallback and not upd.is_desktop():
        return RedirectResponse(f"{back_url}?msg={fallback}", status_code=303)
    return HTMLResponse(_restart_page(done, back_url, auto=err is None))


def _restart_page(done: str, back_url: str, auto: bool) -> str:
    """Экран «настройка применится при следующем запуске».

    Для настроек, которые читает ЛАУНЧЕР до старта приложения: токен бота,
    сетевой доступ, шифрование картотеки.

    ⭐ Перезапуск НАСТОЯЩИЙ (08-10). Экран раньше обещал его и не делал:
    механизм всё это время лежал готовым в `update.py` — `restart_app()`,
    написанный «для применения токена и т.п.», — и просто не был подключён.
    Второй такой писать не стали, взяли этот.
    {_ic('sos')} Формулировка обязана оставаться правдой и тогда, когда перезапуск не
    состоялся: планировщик Windows может не отработать, а в серверном запуске
    его нет вовсе. Поэтому текст говорит «закрываемся сейчас» и сразу даёт
    запасной ход — открыть с ярлыка. Обещать «окно вернётся само» без оговорки
    и было прошлой ошибкой.
    {_ic('sos')} `restart_app()` гасит процесс через ~1.2 с (`_exit_soon`), поэтому
    страницу отдаём ПЕРВОЙ, а гасимся уже после ответа. Сам запуск сюда НЕ
    входит — он в `_restart_now`, иначе страница заводила бы вторую задачу
    планировщика поверх той, что уже запустил маршрут.
    """
    return standalone(f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>Repornire…</title><style>
 body{{font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;
      justify-content:center;height:100vh;margin:0;background:__ACCENT__;color:__ON__;text-align:center}}
 p{{max-width:520px;line-height:1.55;font-size:15px}}
 a{{color:__ON__;font-weight:600;font-size:14px;margin-top:18px;display:inline-block}}
</style></head><body>
<h1>{_ic('check')} {done}</h1>
<p><b>{(RESTART_AUTO if auto else RESTART_MANUAL)[0]}</b>{(RESTART_AUTO if auto else RESTART_MANUAL)[1]}</p>
<p style="opacity:.85;font-size:13.5px">{RESTART_NOTE}</p>
<a href="{back_url}">{_ic('chev-l')} Înapoi în setări</a>
</body></html>""")

