"""Ответ пациента ссылкой из SMS (Premium волна 2а): коды ссылок, ответы, забор ответов программой.

Программа клиники Premium перед напоминанием «Cu o zi înainte» берёт у сервера коды (`/v1/link/new`) и кладёт в
SMS строку `v.dentpilot.md/КОД`; пациент открывает страницу (plink_page.py) и нажимает «Vin» или «Nu pot veni»;
программа забирает ответы (`/v1/link/inbox`) и кладёт их в окно визита; перенос, отмена, архив — `/v1/link/close`.

⛔ Через сервер идут только коды, ответы и время ответа, подпись и телефон КЛИНИКИ — ни телефона, ни имени
пациента, ни времени визита (`until` — граница ответа, начало визита; сервер её не печатает). Код ↔ визит знает
только программа. Состав колонок держит test_plink.suite_schema.

⛔ Открыть ссылку ≠ ответить: Google Messages и мессенджеры открывают её сами ради карточки превью. Ответ — только
POST формы с подписью (`form_mark`), GET ничего не пишет (держит test_plink.suite_page разбором `ast`).

Код выдаёт сервер (`secrets.choice`, алфавит без I O 0 1, 6 знаков: 32⁶ ≈ 1,07 млрд), уникален среди всех строк
таблицы. Состояния: open → yes | no (сменить можно до `until`) → closed (программа закрыла: визит перенесён или
отменён). Строка стирается через `config.LINK_KEEP_DAYS` после `until` (jobs.daily → `purge`).

Право — `features.sms_link` файла лицензии (tiers.link_until, Premium); сервер отвечает тем же правилом:
`link_plan` без права, `link_off` при выключенном модуле SMS (sms.blocked). `kind` — шов волны 2б
(«освободилось место»), сегодня только `confirm`.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config, db, license, sms, tiers

UTC = timezone.utc
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 6
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{6}$")    # двойник в программе: bot/app/core/plink.py (test_plink.suite_wire_twin)
CONFIRM = "confirm"
KINDS = (CONFIRM,)
OPEN, YES, NO, CLOSED = "open", "yes", "no", "closed"
STATES = (OPEN, YES, NO, CLOSED)
ANSWERS = (YES, NO)
LANGS = ("ro", "ru")
BATCH_MAX = 200          # кодов в одном /v1/link/new
CLOSE_MAX = 200          # кодов в одном /v1/link/close
INBOX_MAX = 500          # перемен в одном ответе /v1/link/inbox (дальше — `more`)
UNTIL_MAX = timedelta(days=45)   # граница ответа не дальше: напоминание уходит накануне, не за месяцы
LABEL_MAX = 60
PHONE_MAX = 32
_PHONE_RE = re.compile(r"^[0-9+()\- ]*$")
CLINIC_COLUMNS = ("clinic_id", "label", "phone", "seq", "updated_at")
LINK_COLUMNS = ("code", "clinic_id", "kind", "lang", "state", "seq", "until", "created_at", "answered_at")

CODES = {
    "link_plan": (423, "Răspunsul pacientului prin link face parte din DentPilot Premium."),
    "link_off": (423, "Modulul SMS este oprit — linkurile de răspuns nu se emit."),
    "link_limit": (429, "Prea multe linkuri de răspuns azi — încercăm din nou mai târziu."),
    "link_bad": (400, "Cererea de linkuri nu este completă — actualizați programul."),
    "bad_json": (400, "Cererea nu a putut fi citită — actualizați programul."),
}


def answer(code: str, **extra) -> tuple[int, dict]:
    http, text = CODES[code]
    return http, {"ok": False, "code": code, "text": text, **extra}


def norm(code) -> str:
    """Код из адреса или запроса: строчные принимаются (пациент мог перепечатать ссылку)."""
    return code.strip().upper() if isinstance(code, str) else ""


# ---------- право ----------


def right(con: sqlite3.Connection, clinic_id: str, now: datetime) -> datetime | None:
    """До какого момента у клиники право sms_link — тем же правилом, что в её файле: срок и льгота подписки,
    вариант (tiers.link_until). Нет подписки, срок и льгота прошли, пробный, не Premium — None."""
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic_id,)).fetchone()
    if sub is None:
        return None
    valid = db.parse_ts(sub["valid_until"])
    if license.state(valid, sub["grace_days"] or 0, now) not in ("active", "grace"):
        return None
    return tiers.link_until(sub, valid + timedelta(days=sub["grace_days"] or 0), now)


def refused(con: sqlite3.Connection, clinic_id: str, now: datetime) -> str:
    """Почему новых кодов нет ('' — можно): без права — link_plan; модуль SMS выключен (тумблер, отзыв, токена
    sms.md нет, пакет не предложен) — link_off: SMS со ссылкой всё равно не ушла бы."""
    if right(con, clinic_id, now) is None:
        return "link_plan"
    if sms.blocked(con, clinic_id, sms.account(con, clinic_id), now) in sms.CLOSED:
        return "link_off"
    return ""


# ---------- выдача ----------


def _label(raw) -> str:
    return " ".join(raw.split())[:LABEL_MAX] if isinstance(raw, str) else ""


def clean_new(body: dict, now: datetime) -> dict | None:
    """Поля `/v1/link/new` → {kind, until, langs, label, phone} или None (link_bad). `until` — UTC с «Z», в
    будущем и не дальше UNTIL_MAX; языки — только ro/ru, от 1 до BATCH_MAX; подпись — 1..LABEL_MAX знаков;
    телефон клиники — цифры, пробел, «+», скобки, дефис."""
    kind = body.get("kind", CONFIRM)
    until = db.parse_ts(body.get("until")) if isinstance(body.get("until"), str) else None
    langs = body.get("langs")
    label = _label(body.get("label"))
    phone = body.get("phone", "")
    if kind not in KINDS or until is None or not now < until <= now + UNTIL_MAX:
        return None
    if not isinstance(langs, list) or not 1 <= len(langs) <= BATCH_MAX or any(x not in LANGS for x in langs):
        return None
    if not label or not isinstance(phone, str) or len(phone.strip()) > PHONE_MAX or not _PHONE_RE.match(phone):
        return None
    return {"kind": kind, "until": until, "langs": langs, "label": label, "phone": " ".join(phone.split())}


def _fresh(con: sqlite3.Connection) -> str:
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        if con.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone() is None:
            return code


def issue(con: sqlite3.Connection, clinic_id: str, f: dict, now: datetime) -> tuple[str, list[str]]:
    """Коды на напоминания (в транзакции immediate вызывающего): ('', коды по порядку языков) или
    ('link_limit', []). Подпись и телефон клиники — последние присланные: страница называет клинику так же,
    как SMS."""
    day_ago = (now - timedelta(days=1)).strftime(db.TS)
    made = con.execute("SELECT count(*) FROM links WHERE clinic_id=? AND created_at>?", (clinic_id, day_ago)).fetchone()[0]
    if made + len(f["langs"]) > config.LINK_DAILY:
        return "link_limit", []
    at = now.strftime(db.TS)
    con.execute("INSERT INTO link_clinics(clinic_id, label, phone, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(clinic_id) DO UPDATE SET label=excluded.label, phone=excluded.phone, "
                "updated_at=excluded.updated_at", (clinic_id, f["label"], f["phone"], at))
    codes = []
    for lang in f["langs"]:
        code = _fresh(con)
        con.execute("INSERT INTO links(code, clinic_id, kind, lang, until, created_at) VALUES(?,?,?,?,?,?)",
                    (code, clinic_id, f["kind"], lang, f["until"].strftime(db.TS), at))
        codes.append(code)
    return "", codes


# ---------- забор ответов и закрытие ----------


def inbox(con: sqlite3.Connection, clinic_id: str, after: int) -> dict:
    """Перемены клиники после `after`: последний ответ каждого кода (yes / no) с номером перемены и временем.
    `seq` — до какого номера программа может считать себя дочитавшей; `more` — есть ещё (взять с `after=seq`).
    Повторная доставка безвредна: ответ кода — состояние, не событие."""
    rows = con.execute("SELECT code, seq, state, answered_at FROM links WHERE clinic_id=? AND seq>? "
                       "AND state IN (?, ?) ORDER BY seq LIMIT ?",
                       (clinic_id, max(0, after), YES, NO, INBOX_MAX + 1)).fetchall()
    more = len(rows) > INBOX_MAX
    rows = rows[:INBOX_MAX]
    if more:
        top = rows[-1]["seq"]
    else:
        lc = con.execute("SELECT seq FROM link_clinics WHERE clinic_id=?", (clinic_id,)).fetchone()
        top = max(after, lc["seq"] if lc is not None else 0)
    return {"ok": True, "seq": top, "more": more,
            "items": [{"code": r["code"], "seq": r["seq"], "state": r["state"], "at": r["answered_at"]} for r in rows]}


def clean_codes(raw) -> list[str] | None:
    if not isinstance(raw, list) or len(raw) > CLOSE_MAX:
        return None
    codes = [norm(x) for x in raw]
    return codes if all(CODE_RE.match(x) for x in codes) else None


def close(con: sqlite3.Connection, clinic_id: str, codes: list[str]) -> int:
    """Программа закрыла коды (перенос, отмена, «Fără SMS», стирание пациента): страница скажет «изменено».
    Только свои коды; уже закрытые не считаются."""
    if not codes:
        return 0
    marks = ",".join("?" * len(codes))
    return con.execute(f"UPDATE links SET state=? WHERE clinic_id=? AND state<>? AND code IN ({marks})",
                       (CLOSED, clinic_id, CLOSED, *codes)).rowcount


# ---------- страница пациента ----------


def lookup(con: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    """Код с подписью и телефоном клиники — для страницы. Только чтение."""
    if not CODE_RE.match(code):
        return None
    return con.execute("SELECT l.*, COALESCE(lc.label, c.name) AS label, COALESCE(lc.phone, '') AS phone "
                       "FROM links l JOIN clinics c ON c.id = l.clinic_id "
                       "LEFT JOIN link_clinics lc ON lc.clinic_id = l.clinic_id WHERE l.code=?", (code,)).fetchone()


def alive(row: sqlite3.Row | None, now: datetime) -> bool:
    """Код отвечает: есть и визит ещё не начался. Закрытый — тоже «жив» (страница «изменено» с телефоном)."""
    until = db.parse_ts(row["until"]) if row is not None else None
    return until is not None and now < until


def respond(con: sqlite3.Connection, code: str, what: str, now: datetime) -> tuple[sqlite3.Row | None, bool]:
    """Ответ пациента (в транзакции immediate вызывающего): (строка после ответа, сменился ли ответ). Тот же
    ответ ещё раз — тихий успех без новой перемены; закрытый или прошедший код ответа не принимает."""
    row = lookup(con, code)
    if what not in ANSWERS or not alive(row, now) or row["state"] == CLOSED:
        return row, False
    if row["state"] == what:
        return row, False
    con.execute("INSERT INTO link_clinics(clinic_id, label, phone, updated_at) VALUES(?, ?, '', ?) "
                "ON CONFLICT(clinic_id) DO NOTHING", (row["clinic_id"], row["label"], now.strftime(db.TS)))
    con.execute("UPDATE link_clinics SET seq=seq+1 WHERE clinic_id=?", (row["clinic_id"],))
    seq = con.execute("SELECT seq FROM link_clinics WHERE clinic_id=?", (row["clinic_id"],)).fetchone()[0]
    con.execute("UPDATE links SET state=?, seq=?, answered_at=? WHERE code=? AND state=?",
                (what, seq, now.strftime(db.TS), code, row["state"]))
    return lookup(con, code), True


# ---------- уборка ----------


def purge(con: sqlite3.Connection, now: datetime) -> int:
    """Ежедневная задача (в транзакции immediate вызывающего): стереть коды, чей визит начался больше
    LINK_KEEP_DAYS назад, — с ответами. → сколько стёрто."""
    edge = (now - timedelta(days=config.LINK_KEEP_DAYS)).strftime(db.TS)
    return con.execute("DELETE FROM links WHERE until<?", (edge,)).rowcount
