"""«Stare sistem»: что программа знает о себе — версия, база, папка с данными,
обновления, вход, шифрование диска.

⭐ Это ЕДИНСТВЕННОЕ место, где директор может свериться, куда программа пишет,
и потому якорь для двух текстов, которые иначе описывали бы раскладку словами
и протухли бы при следующем переезде: ответы FAQ про перенос и CITESTE-MA.txt
внутри вывозного архива оба отсылают СЮДА. Прайор 21.09 (хвост P1) ровно об
этом: правка, меняющая раскладку, меняет и тексты, а разошедшийся ТЕКСТ не
ловится ни импортом, ни тестом, ни ошибкой на экране. Отсюда правило этого
модуля — показывать ФАКТ (`layout.data_folder()`), а не его описание.

Куски собраны, как у `lan.py` и `crypt.py`: старая страница склеивает их со
своими формами, JSON API отдаёт те же куски React-экрану, который рисует
кнопки сам.
"""
from __future__ import annotations

import html
import os

from ... import db
from ... import engine as eng
from ... import update as upd
from ...core import bitlocker
from ...core.auth import ADMIN_KEY, _pin_rec
from ...core.layout import (FEEDBACK_EMAIL, _ic, data_folder, tg_configured,
                            tg_status)

# Строка «Folderul cu date». ⚠️ Путь, а не «да/нет»: его сверяют глазами с
# адресной строкой Проводника, и сокращение вроде «%ProgramData%» сверить
# нельзя.
FOLDER_HINT = ("aici stau evidența, documentele și copiile de rezervă — nu în "
               "folderul în care este instalat programul")

CHANNEL_WARN = "acest calculator vede versiunile ÎNAINTE de clinici"


def tg_line(tg: dict) -> str:
    """Строка канала бота. Её читает и раздел Telegram, поэтому она здесь, а
    не внутри сборки страницы."""
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


def bitlocker_state() -> dict | None:
    """Шифрование диска — то, чем закрыто требование закона 195.

    None вне настольного издания: у облака диск не наш, и говорить о нём
    нечего.
    """
    if not db.IS_SQLITE:
        return None
    tone, txt = bitlocker.describe(bitlocker.STATE["code"],
                                   bitlocker.STATE["drive"])
    return {"tone": tone, "text": txt,
            "icon": {"ok": "check", "warn": "sos", "alarm": "ban"}.get(tone, "")}


def update_state() -> dict:
    """Что программа знает про обновление — ОДНО состояние на страницу и JSON.

    ⚠️ Слово принадлежит серверу: в нём едут номер версии и причина, по которой
    файла ещё нет. `url` непуст только там, где качать надо руками.
    """
    latest = upd.STATE["latest"]
    if upd.can_self_update():
        return {"state": "self", "icon": "refresh", "latest": latest,
                "url": "", "text": f"disponibilă {latest}"}
    if upd.asset_pending() and upd.is_desktop():
        return {"state": "pending", "icon": "clock", "latest": latest, "url": "",
                "text": (f"versiunea {latest} este anunțată, dar fișierul "
                         f"programului încă nu e publicat — reverificăm "
                         f"automat peste câteva minute")}
    if upd.newer_available():
        return {"state": "link", "icon": "refresh", "latest": latest,
                "url": upd.STATE["url"], "text": f"disponibilă {latest} — descărcați"}
    if upd.STATE["checked"] and not upd.STATE["error"]:
        return {"state": "fresh", "icon": "check", "latest": latest, "url": "",
                "text": "la zi"}
    if upd.STATE["error"]:
        return {"state": "unknown", "icon": "", "latest": latest, "url": "",
                "text": "— necunoscut (offline?)"}
    return {"state": "checking", "icon": "", "latest": latest, "url": "",
            "text": "se verifică…"}


def channel_state() -> dict | None:
    """Канал обновлений — только когда он НЕ stable.

    ⭐ Виден в интерфейсе намеренно: на этой машине обновление приходит РАНЬШЕ,
    чем клиникам, и перепутать её с боевой установкой нельзя.
    ⚠️ Названия разные намеренно: риск у `beta` и `draft` разный (первый —
    публичные пре-релизы без ключа, второй — ещё и черновики), и путать их
    нельзя.
    """
    ch = upd.channel()
    if ch == "stable":
        return None
    note = ""
    if upd.STATE.get("draft"):
        note = " · versiunea curentă din canal este nepublicată"
    elif upd.STATE.get("prerelease"):
        note = " · versiunea curentă din canal este pre-lansare"
    return {"name": "draft (test)" if ch == "draft" else "beta (pre-lansări)",
            "warn": CHANNEL_WARN, "note": note}


def access_state() -> dict:
    if _pin_rec():
        return {"icon": "lock", "text": "PIN setat"}
    return {"icon": "lock", "text": "parolă (ADMIN_KEY)" if ADMIN_KEY else "deschis"}


def db_label() -> str:
    return "SQLite (local, data/dental.db)" if db.IS_SQLITE else "PostgreSQL"


def privacy_html() -> str:
    """Два абзаца о том, что программа работает локально — румынский для
    клиники и русский для Олега. ⚠️ Оба ссылаются на «folderul cu date выше»,
    то есть на ФАКТ из этой же таблицы, а не на описание раскладки."""
    return (
        "<p style='margin:0 0 8px;font-size:13px;line-height:1.55;color:var(--text2)'>"
        "<b style='color:var(--text)'>Programul funcționează local.</b> Datele "
        "personale ale pacienților nu sunt transmise dezvoltatorului și nu sunt "
        "stocate pe serverele acestuia. Actualizările descarcă doar fișierele "
        "programului. Baza de date, jurnalele și copiile de rezervă rămân pe "
        "acest calculator, în folderul cu date de mai sus.</p>"
        "<p style='margin:0;font-size:12.5px;line-height:1.55;color:var(--text3)'>"
        "Программа работает локально. Персональные данные пациентов не "
        "передаются разработчику и не хранятся на его серверах. Обновления "
        "загружают только файлы программы. База данных, журналы и резервные "
        "копии остаются на этом компьютере.</p>")


def data() -> dict:
    """Модель экрана. Telegram заморожен (08-08): строка канала — только
    клинике с настроенным ботом. Остальным она писала «— fără token (secțiunea
    Telegram Bot)» и отправляла искать раздел, который заморозка спрятала
    (08-13)."""
    return {
        "version": eng.APP_VERSION,
        "db": db_label(),
        "folder": {"path": data_folder() or "", "hint": FOLDER_HINT},
        "telegram": tg_line(tg_status()) if tg_configured() else "",
        "update": update_state(),
        "channel": channel_state(),
        "access": access_state(),
        "bitlocker": bitlocker_state(),
        "feedback": FEEDBACK_EMAIL,
        "privacy": privacy_html(),
        # P4.1. ⚠️ Состояние, а не действие: правка записи требует прав
        # администратора, и запрашивать их программа сама не вправе — окно UAC
        # на каждом старте перестают читать. Кнопку нажимает человек.
        "uninstall": upd.uninstall_entry(),
    }


# ---- разметка старой страницы, из тех же кусков ----

_CHECK_FORM = ("<form method='post' action='/admin/update/check' style='display:inline'>"
               "<button style='background:none;border:1px solid var(--line);"
               "border-radius:8px;padding:4px 10px;cursor:pointer;font-size:12px;"
               f"color:var(--text2);margin-left:10px'>{_ic('refresh')} "
               "Verifică acum</button></form>")

_RUN_FORM = ("<form method='post' action='/admin/update/run' style='display:inline'>"
             "<button style='background:#e8710a;color:#fff;border:none;"
             "border-radius:6px;padding:6px 14px;cursor:pointer;font-size:14px;"
             f"margin-left:8px'>{_ic('upload')} Actualizează acum</button></form>")


def _row(label: str, value: str, width: str = "") -> str:
    style = f" style='width:{width}'" if width else ""
    return f"<tr><th{style}>{label}</th><td>{value}</td></tr>"


def render() -> str:
    d = data()
    up = d["update"]
    ico = f"{_ic(up['icon'])} " if up["icon"] else ""
    if up["state"] == "link":
        line = f"<a href='{html.escape(up['url'])}' target='_blank'>{ico}{up['text']}</a>"
    else:
        line = f"{ico}{up['text']}"
    if up["state"] == "self":
        line += _RUN_FORM
    line += _CHECK_FORM

    rows = [_row("Versiune", f"v{d['version']}", "180px"),
            _row("Bază de date", d["db"])]
    if d["folder"]["path"]:
        rows.append(_row("Folderul cu date",
                         f"<code>{html.escape(d['folder']['path'])}</code><br>"
                         f"<span style='color:var(--text3);font-size:12px'>"
                         f"{d['folder']['hint']}</span>"))
    if d["telegram"]:
        rows.append(_row("Canal Telegram", d["telegram"]))
    rows.append(_row("Actualizări", line))
    if d["channel"]:
        rows.append(_row("Canal actualizări",
                         f"<b style='color:var(--amber-t)'>{d['channel']['name']}</b> — "
                         f"{d['channel']['warn']}{d['channel']['note']}"))
    rows.append(_row("Acces jurnal",
                     f"{_ic(d['access']['icon'])} {d['access']['text']}"))
    if d["bitlocker"]:
        bl = d["bitlocker"]
        style = (" style='color:var(--red-t);font-weight:600'" if bl["tone"] == "alarm"
                 else " style='color:var(--amber-t)'" if bl["tone"] == "warn" else "")
        icon = f"{_ic(bl['icon'])} " if bl["icon"] else ""
        rows.append(f"<tr><th>Criptare disc (BitLocker)</th>"
                    f"<td{style}>{icon}{html.escape(bl['text'])}</td></tr>")
    rows.append(_row("Feedback / suport",
                     f"<a href='mailto:{d['feedback']}'>{d['feedback']}</a>"))

    return (f"<h2>{_ic('info')} Stare sistem</h2>"
            f"<table class='set'>{''.join(rows)}</table>"
            f"<h2>{_ic('shield')} Confidențialitate</h2>"
            f"<div class='pcard' style='max-width:var(--measure)'>"
            f"{d['privacy']}</div>")
