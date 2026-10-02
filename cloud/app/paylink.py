"""Оплата из программы (02.10, слово Олега: «кнопку Plătește acum и оттуда сразу
на страницу maib с моими данными»).

Программа не несёт ни секретов мерчанта, ни куки кабинета. По кнопке она
просит у сервера одноразовую ссылку (`POST /v1/pay-link`, тот же Bearer-токен,
что у суточного запроса файла `/v1/license`) и открывает её в браузере.
Страница `/plata/<id>` публична по неугадываемому id (token_urlsafe(18)),
живёт TTL (сутки) и показывает одно: как заплатить за абонемент ЭТОЙ клиники —
нота с реквизитами перевода и, при настроенном maib, кнопка на страницу
оплаты картой. Нота — та же строка `payments`, что у админки и кабинета (одна
ожидающая на клинику); после оплаты срок продлевается и файл выдаётся как
обычно, программа подхватывает его суточным запросом или «Verifică acum».

⛔ Ссылка — не вход в кабинет: по ней нельзя ни увидеть, ни изменить ничего,
кроме оплаты (и IDNO, без которого абонемента не бывает). Повторный запрос
программы в пределах TTL возвращает ту же ссылку — строки не плодятся.
"""
from __future__ import annotations

import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import config, db, trial

PATH = "/plata"                  # страница оплаты: /plata/<id>
API_PATH = "/v1/pay-link"        # программа → ссылка (Bearer = renew_token клиники)
TTL = timedelta(hours=24)
POSTS_PER_HOUR = 20              # отправок формы с одного адреса в час
_hits: dict[str, list[float]] = {}


def url_for(pid: str) -> str:
    return config.BASE_URL.rstrip("/") + f"{PATH}/{pid}"


def create(con: sqlite3.Connection, clinic: sqlite3.Row, who: str) -> sqlite3.Row:
    """Живая ссылка клиники — прежняя, если ещё не истекла, иначе новая."""
    now = datetime.now(timezone.utc)
    live = con.execute("SELECT * FROM pay_links WHERE clinic_id=? AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
                       (clinic["id"], now.strftime(db.TS))).fetchone()
    if live is not None:
        return live
    pid = secrets.token_urlsafe(18)
    con.execute("INSERT INTO pay_links(id, clinic_id, created_at, expires_at) VALUES(?,?,?,?)",
                (pid, clinic["id"], now.strftime(db.TS), (now + TTL).strftime(db.TS)))
    db.audit(con, who, "paylink_new", clinic["id"], f"ссылка оплаты до {(now + TTL).strftime(db.TS)}")
    return con.execute("SELECT * FROM pay_links WHERE id=?", (pid,)).fetchone()


def lookup(con: sqlite3.Connection, pid: str) -> sqlite3.Row | None:
    """Клиника живой ссылки или None: неизвестна, истекла, клиника скрыта."""
    if not pid or len(pid) > 64:
        return None
    row = con.execute("SELECT * FROM pay_links WHERE id=?", (pid,)).fetchone()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    if (db.parse_ts(row["expires_at"]) or now) <= now:
        return None
    return con.execute("SELECT * FROM clinics WHERE id=? AND declined_at IS NULL", (row["clinic_id"],)).fetchone()


def limited(ip: str) -> bool:
    """Больше POSTS_PER_HOUR отправок формы с адреса за час — отказ."""
    now = time.time()
    key = trial.bucket(ip)
    stamps = [t for t in _hits.get(key, []) if now - t < 3600]
    _hits[key] = stamps + [now]
    return len(stamps) >= POSTS_PER_HOUR
