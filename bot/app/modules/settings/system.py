"""«Stare sistem»: что программа знает о себе — версия, база, папка с данными,
обновления, вход, шифрование диска.

⭐ Это ЕДИНСТВЕННОЕ место, где директор может свериться, куда программа пишет,
и потому якорь для двух текстов, которые иначе описывали бы раскладку словами
и протухли бы при следующем переезде: ответы FAQ про перенос и CITESTE-MA.txt
внутри вывозного архива оба отсылают СЮДА. Прайор 21.09 (хвост P1) ровно об
этом: правка, меняющая раскладку, меняет и тексты, а разошедшийся ТЕКСТ не
ловится ни импортом, ни тестом, ни ошибкой на экране. Отсюда правило этого
модуля — показывать ФАКТ (`layout.data_folder()`), а не его описание.

Куски собраны, как у `lan.py` и `crypt.py`: JSON API отдаёт их React-экрану,
который рисует кнопки сам (старая серверная страница снята 12.10).
"""
from __future__ import annotations

import html
import os

from ... import engine as eng
from ... import update as upd
from ...core import backup_loop, bitlocker
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


def bitlocker_state() -> dict:
    """Шифрование диска — то, чем закрыто требование закона 195."""
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


def backup_state() -> dict:
    """Копии картотеки — ФАКТАМИ (17.10): когда была последняя локальная,
    когда последняя внешняя и куда, что не удалось. Тон `warn` ровно при
    тексте баннера директора (`backup_loop.alert`) — одно условие на оба."""
    st = backup_loop.state()
    local = st["local_at"] or "încă nu s-a făcut"
    if not st["folder"]:
        ext = "nealeasă (Setări › Copie de rezervă)"
    elif st["ext_at"]:
        ext = f"{st['ext_at']} în {st['folder']}"
    else:
        ext = f"încă nu s-a făcut, în {st['folder']}"
    # выключатель директора (17.10 вечером): выключено — тон warn без текста
    # баннера (баннера нет намеренно), но факт на экране состояния назван
    daily = "pornită" if st["enabled"] else "oprită — rămâne copia de la pornirea programului"
    return {"tone": "warn" if (st["alert"] or not st["enabled"]) else "ok",
            "daily": daily, "local": local, "external": ext, "alert": st["alert"],
            "href": "/admin/settings/backup"}


def db_label() -> str:
    return "SQLite (local, data/dental.db)"


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
        "backup": backup_state(),
        "feedback": FEEDBACK_EMAIL,
        "privacy": privacy_html(),
        # P4.1. ⚠️ Состояние, а не действие: правка записи требует прав
        # администратора, и запрашивать их программа сама не вправе — окно UAC
        # на каждом старте перестают читать. Кнопку нажимает человек.
        "uninstall": upd.uninstall_entry(),
    }
