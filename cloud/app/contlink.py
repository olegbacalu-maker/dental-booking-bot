"""Кабинет из программы (27.10.2026, план review/plan-cabinet-link-email-2026-10-27.md › Б):
кнопка «Deschide contul clinicii» на странице лицензии программы открывает кабинет без кода.

Тот же путь, что у «Plătește acum» (paylink.py): программа с Bearer-токеном файла
(`renew_token`) просит у сервера ссылку (`POST /v1/cont-link`) и отправляет туда системный
браузер. Отличие — ссылка ОДНОРАЗОВАЯ и короткая (TTL, 5 минут): `/cont/intra/<id>` гасит её
при первом открытии и ставит куку кабинета вида «clinic» (auth.clinic_cookie).

⛔ Вход по кнопке — ТОЛЬКО СВОЯ КЛИНИКА (рекомендация, принятая Олегом 27.10 «можешь
приступать»): кабинет с 26.10 держит несколько клиник, а программа филиала — не владелец
сети. Сессия кнопки — не учётная запись, а запись-заменитель (`session`) с provider
account.PROGRAM: `account.clinics` отдаёт ей одну клинику, поэтому `pick` не пускает к другим
по `?c=`. Чего у неё нет совсем — DENY (маршруты кабинета целиком: «Adaugă clinică», общая
нота) — их закрывает посредник `main._cont_program_only` по виду куки; смены e-mail клиники в кабинете нет ни у кого (по нему привязан вход). Каждый маршрут
`/cont…` разобран в tests/test_contlink.py: новый маршрут без решения там — красный.
Весь кабинет — прежним входом (Google или код на e-mail).

К IP вход не привязан: программа и браузер одной машины выходят в сеть по-разному (IPv4 и
IPv6), и кнопка ломалась бы «иногда». Адрес только пишется в журнал.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import Request

from . import account, auth, config, db

API_PATH = "/v1/cont-link"           # программа → ссылка (Bearer = renew_token клиники)
PATH = "/cont/intra"                 # одноразовый вход: /cont/intra/<id>
TTL = timedelta(minutes=5)
PER_HOUR = 20                        # ссылок одной клинике в час (как у оплаты)
# Маршруты кабинета, закрытые сессии кнопки целиком: все клиники кабинета и новые клиники в нём
DENY = ("/cont/clinica-noua", "/cont/nota-comuna")
DENIED_MSG = "cont_program_only"


def _hash(lid: str) -> str:
    return hashlib.sha256(lid.encode("utf-8")).hexdigest()


def url_for(lid: str) -> str:
    return config.BASE_URL.rstrip("/") + f"{PATH}/{lid}"


def create(con: sqlite3.Connection, clinic: sqlite3.Row) -> tuple[str, str] | None:
    """Новая одноразовая ссылка клиники → (id, срок) или None: PER_HOUR за час уже выдано.
    Повтор не отдаёт прежнюю: id в базе только хешем, и каждое нажатие — своя ссылка."""
    now = datetime.now(timezone.utc)
    n = con.execute("SELECT count(*) FROM cont_links WHERE clinic_id=? AND created_at > ?",
                    (clinic["id"], (now - timedelta(hours=1)).strftime(db.TS))).fetchone()[0]
    if n >= PER_HOUR:
        return None
    lid = secrets.token_urlsafe(24)
    until = (now + TTL).strftime(db.TS)
    con.execute("INSERT INTO cont_links(id_hash, clinic_id, created_at, expires_at) VALUES(?,?,?,?)",
                (_hash(lid), clinic["id"], now.strftime(db.TS), until))
    return lid, until


def use(con: sqlite3.Connection, lid: str, ip: str) -> sqlite3.Row | None:
    """Погасить ссылку → её клиника или None: неизвестна, истекла, уже открыта, клиника скрыта.
    Гасит условным UPDATE: два одновременных открытия — один вход."""
    if not lid or len(lid) > 64:
        return None
    h = _hash(lid)
    now = db.now_iso()
    cur = con.execute("UPDATE cont_links SET used_at=?, used_ip=? WHERE id_hash=? AND used_at IS NULL "
                      "AND expires_at > ?", (now, ip[:64], h, now))
    if cur.rowcount != 1:
        return None
    row = con.execute("SELECT clinic_id FROM cont_links WHERE id_hash=?", (h,)).fetchone()
    return con.execute("SELECT * FROM clinics WHERE id=? AND declined_at IS NULL", (row["clinic_id"],)).fetchone()


def session(con: sqlite3.Connection, request: Request) -> dict | None:
    """Сессия кнопки из куки кабинета → запись-заменитель учётной записи или None. Клиника
    читается из базы на каждом запросе: скрытая Олегом перестаёт пускать сразу."""
    cid = auth.current_clinic_id(request)
    if not cid:
        return None
    c = con.execute("SELECT * FROM clinics WHERE id=? AND declined_at IS NULL", (cid,)).fetchone()
    if c is None:
        return None
    # ключи — как у строки accounts: кабинет читает acc[...] по месту; email — подпись в шапке и
    # «кто» в журнале и нотах (вход не по ящику — поэтому с пометкой)
    return {"id": f"{account.PROGRAM}:{c['id']}", "provider": account.PROGRAM, "subject": "",
            "email": f"{c['email'] or c['name']} · din program", "name": "", "clinic_id": c["id"],
            "created_at": c["created_at"], "last_login_at": ""}


def closed(path: str) -> bool:
    """Закрыт ли маршрут кабинета сессии кнопки (DENY): сам адрес или под ним."""
    return any(path == p or path.startswith(p + "/") for p in DENY)
