"""Подтверждение e-mail клиники (27.10, план В; слово Олега: подтверждать ПОСЛЕ включения,
неподтверждённому — только напоминание, метка в админке).

Регистрация из программы включает её сразу, а ящик никто не проверял: опечатка
`clinica@gmial.com` проходила молча, и потом в пустоту уходили код второго компьютера,
код входа в кабинет, ноты и письма о сроке. Теперь `clinics.email_confirmed_at`:

- в письме о лицензии неподтверждённой клинике — ссылка «Confirmă adresa» и 6 цифр
  (`for_letter`, одно письмо, не два). Ссылка ведёт на страницу с кнопкой (POST): почтовые
  сканеры открывают ссылки сами, и голый GET подтверждал бы ящик без человека. Живёт LINK_TTL —
  письмо о пробном читают не сразу;
- программа (Bearer `renew_token`): `/v1/email/code` — «Retrimite», `/v1/email/confirm` — код,
  `/v1/email/change` — «Schimbă adresa», ⛔ только пока ящик НЕ подтверждён (иначе любой за
  ПК регистратуры уводил бы кабинет и письма об оплате). Узнаёт состояние и из суточного
  `/v1/license` — заголовками рядом с файлом (`headers`), не в подписанном файле;
- вход в кабинет кодом на этот ящик или Google с ним же — тоже подтверждение (`by_mailbox`);
  клиника, заведённая из кабинета на ящик вошедшего, подтверждена сразу (`on_new_clinic`).

⛔ Запирать нечего: неподтверждённый ящик программу не останавливает (решение 21.09: программа не
запирает данные), это только напоминание директору и метка Олегу.

Код и ссылка привязаны к АДРЕСУ, на который ушли (`email`): после смены ящика старые не
подтверждают новый. Ссылка хранится хешем (`id`), код — хешем с id строки. Кодов на клинику —
CODES_PER_HOUR в час (как у входа кодом, login.py), письмо о лицензии в лимит не входит: его
шлёт сам сервер. Ошибка кода засчитывается всем живым кодам клиники — CODE_ATTEMPTS на всех,
ссылка из письма от этого не гаснет (её 32 байта не угадать).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import cabinet, config, db, trial

PAGE = "/confirma"               # /confirma/<ключ>: страница с кнопкой, POST — подтверждение
API_CODE = "/v1/email/code"      # «Retrimite»: новый код на ящик клиники
API_CONFIRM = "/v1/email/confirm"
API_CHANGE = "/v1/email/change"  # «Schimbă adresa»: только пока не подтверждён
LINK_TTL = timedelta(days=7)
CODE_ATTEMPTS = 5                # ошибок на все живые коды клиники; дальше они гаснут
CODES_PER_HOUR = 3               # писем с кодом по просьбе программы в час
# Заголовки ответа /v1/license — «рядом с файлом»: подтверждён ли ящик и какой (адрес —
# в %-кодировке: заголовок латиница, а имя ящика может быть не ASCII)
H_CONFIRMED, H_EMAIL = "X-DentPilot-Email-Confirmed", "X-DentPilot-Email"
# clinics.email_confirmed_at: каким путём — словами журнала (views.AUDIT_RU › email_confirmed)
VIA_LINK, VIA_CODE, VIA_LOGIN, VIA_CABINET = "linkul din e-mail", "codul din program", "intrare în cont", \
    "înregistrare din cont"


def confirmed(clinic: sqlite3.Row) -> bool:
    return bool(clinic["email_confirmed_at"])


def view(clinic: sqlite3.Row) -> dict:
    """Что программа знает о ящике: тот же ответ у всех трёх маршрутов."""
    return {"email": clinic["email"], "confirmed": confirmed(clinic)}


def headers(clinic: sqlite3.Row) -> dict:
    """Заголовки ответа /v1/license (200 и 204): у клиники без ящика — ничего."""
    if not clinic["email"]:
        return {}
    return {H_CONFIRMED: "1" if confirmed(clinic) else "0",
            H_EMAIL: urllib.parse.quote(clinic["email"], safe="@+.-_")}


def _id(token: str) -> str:
    return hashlib.sha256(f"confirm:{token}".encode("utf-8")).hexdigest()


def _code_hash(rid: str, code: str) -> str:
    return hashlib.sha256(f"email:{rid}:{code}".encode("utf-8")).hexdigest()


def url_for(token: str) -> str:
    return config.BASE_URL.rstrip("/") + f"{PAGE}/{token}"


def issue(con: sqlite3.Connection, clinic: sqlite3.Row, who: str) -> tuple[str, str]:
    """Ссылка и код на нынешний ящик клиники → (ключ ссылки, код). Письмо шлёт вызывающий."""
    token = secrets.token_urlsafe(24)
    rid = _id(token)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    now = datetime.now(timezone.utc)
    con.execute("INSERT INTO email_confirms(id, clinic_id, email, code_hash, created_at, expires_at, who) "
                "VALUES(?,?,?,?,?,?,?)", (rid, clinic["id"], clinic["email"], _code_hash(rid, code),
                                          now.strftime(db.TS), (now + LINK_TTL).strftime(db.TS), who[:120]))
    return token, code


def for_letter(con: sqlite3.Connection, clinic: sqlite3.Row, who: str) -> tuple[str, str] | None:
    """Письму о лицензии неподтверждённой клиники — (адрес ссылки, код); подтверждённой — None."""
    fresh = con.execute("SELECT * FROM clinics WHERE id=?", (clinic["id"],)).fetchone()
    if fresh is None or confirmed(fresh) or not fresh["email"]:
        return None
    # не 'program': письмо о лицензии шлёт сам сервер, в лимит просьб программы оно не входит
    token, code = issue(con, fresh, f"letter ({who})")
    return url_for(token), code


def limited(con: sqlite3.Connection, clinic: sqlite3.Row) -> bool:
    """Лимит писем с кодом по просьбе программы: CODES_PER_HOUR в час на клинику."""
    hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(db.TS)
    n = con.execute("SELECT count(*) FROM email_confirms WHERE clinic_id=? AND created_at > ? AND who='program'",
                    (clinic["id"], hour_ago)).fetchone()[0]
    return n >= CODES_PER_HOUR


def mark(con: sqlite3.Connection, clinic_id: str, via: str, who: str) -> bool:
    """Отметить ящик подтверждённым; True — отметка поставлена сейчас (не была)."""
    cur = con.execute("UPDATE clinics SET email_confirmed_at=? WHERE id=? AND email_confirmed_at IS NULL "
                      "AND email<>''", (db.now_iso(), clinic_id))
    if cur.rowcount:
        email = con.execute("SELECT email FROM clinics WHERE id=?", (clinic_id,)).fetchone()[0]
        db.audit(con, who, "email_confirmed", clinic_id, f"{email} — {via}")
        con.execute("UPDATE email_confirms SET used_at=? WHERE clinic_id=? AND used_at IS NULL",
                    (db.now_iso(), clinic_id))
    return bool(cur.rowcount)


def _live(con: sqlite3.Connection, clinic: sqlite3.Row) -> list:
    """Живые коды клиники на её НЫНЕШНИЙ ящик."""
    return con.execute("SELECT * FROM email_confirms WHERE clinic_id=? AND email=? AND used_at IS NULL "
                       "AND expires_at > ?", (clinic["id"], clinic["email"], db.now_iso())).fetchall()


def by_link(con: sqlite3.Connection, token: str) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
    """Ключ ссылки → (строка кода, клиника) или (None, None): нет, истёк, использован или ящик
    клиники с тех пор сменился. Подтверждённая клиника — (строка, клиника): страница скажет
    «уже подтверждён», а не «ссылка недействительна»."""
    if not token or len(token) > 64:
        return None, None
    row = con.execute("SELECT * FROM email_confirms WHERE id=?", (_id(token),)).fetchone()
    if row is None:
        return None, None
    c = con.execute("SELECT * FROM clinics WHERE id=?", (row["clinic_id"],)).fetchone()
    if c is None or c["email"] != row["email"]:
        return None, None
    if confirmed(c):
        return row, c
    if row["used_at"] or row["expires_at"] <= db.now_iso():
        return None, None
    return row, c


def check_code(con: sqlite3.Connection, clinic: sqlite3.Row, code: str, ip: str) -> bool:
    """Верный живой код → ящик подтверждён; ошибка засчитана всем живым кодам клиники."""
    live = [r for r in _live(con, clinic) if r["attempts"] < CODE_ATTEMPTS]
    if not live or not code:
        return False
    if any(hmac.compare_digest(r["code_hash"], _code_hash(r["id"], code)) for r in live):
        mark(con, clinic["id"], VIA_CODE, "program")
        return True
    con.execute("UPDATE email_confirms SET attempts = attempts + 1 WHERE clinic_id=? AND used_at IS NULL",
                (clinic["id"],))
    db.audit(con, "program", "email_code_bad", clinic["id"], ip)
    return False


def taken(con: sqlite3.Connection, clinic: sqlite3.Row, email: str) -> bool:
    """Ящик уже у другой живой клиники — не своего кабинета (у филиала он бывает тот же)."""
    own = cabinet.ids(con, clinic["id"]) | {clinic["id"]}
    return trial.existing(con, "", email, own) is not None


def change(con: sqlite3.Connection, clinic: sqlite3.Row, email: str, ip: str) -> str:
    """«Schimbă adresa» из программы: '' — сменён (ящик снова не подтверждён); иначе код отказа —
    ключ views.TRIAL_MSG. ⛔ Подтверждённый ящик программа не меняет."""
    if confirmed(clinic):
        return "email_locked"
    if trial.canonical(email) == trial.canonical(clinic["email"] or "-@-"):
        return "email_same"
    if taken(con, clinic, email):
        return "email_taken"
    con.execute("UPDATE clinics SET email=?, email_confirmed_at=NULL WHERE id=?", (email, clinic["id"]))
    db.audit(con, "program", "email_change", clinic["id"], f"{clinic['email']} → {email}, {ip}")
    return ""


def by_mailbox(con: sqlite3.Connection, email: str, who: str) -> None:
    """Вход в кабинет кодом на ящик или Google с ним же: ящик доказан — подтверждены все живые
    клиники с этим ящиком (сравнение — trial.canonical, как у привязки по ящику)."""
    want = trial.canonical(email)
    domain = want.partition("@")[2]
    for r in con.execute("SELECT id, email FROM clinics WHERE declined_at IS NULL AND email_confirmed_at IS NULL "
                         "AND lower(email) LIKE ?", ("%@" + domain,)).fetchall():
        if r["email"] and trial.canonical(r["email"]) == want:
            mark(con, r["id"], VIA_LOGIN, who)


def on_new_clinic(con: sqlite3.Connection, clinic_id: str, who: str) -> None:
    """Клиника, заведённая из кабинета (регистрация, «Adaugă clinică»): `who` — ящик вошедшей
    учётной записи. Совпал с ящиком клиники — он доказан входом, отметка сразу, и письмо о
    пробном не просит подтверждать. Форма сайта и программа (`who` — 'form'/'program') мимо."""
    if "@" not in who:
        return
    c = con.execute("SELECT email FROM clinics WHERE id=?", (clinic_id,)).fetchone()
    if c is None or not c["email"] or trial.canonical(c["email"]) != trial.canonical(who):
        return
    known = con.execute("SELECT 1 FROM accounts WHERE lower(email)=?", (who.lower(),)).fetchone()
    if known:
        mark(con, clinic_id, VIA_CABINET, who)
