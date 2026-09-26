"""Форма пробного периода (L14): публичная страница /proba на сервере лицензий.

cloud.md › «Сайт»: страница живёт здесь, а не на статике сайта — ссылка, не
форма на чужом origin. Клиника оставляет название, IDNO, контакт, e-mail и
согласие с условиями; дальше — по DP_TRIAL_MODE:

  approve  (по умолчанию)  клиника заведена как заявка, Олегу письмо, файл
                           выдаёт админка кнопкой «Выдать пробный»;
  auto                     файл выдаётся и уходит письмом сразу, Олегу копия.

⛔ Второго пробного по той же клинике нет: IDNO (если назван) и ящик e-mail
(в канонической форме: регистр, `+метка`, точки gmail) сверяются со всеми
клиниками — заявка, выданный пробный или абонемент, кроме скрытых, — и
повтор не даёт файла. ⭐ Повтор клинике не объявляется: страница та же, что
у принятой заявки, — иначе форма была бы оракулом «эта клиника уже клиент
DentPilot»; о повторе узнаёт Олег письмом и отвечает сам. Правило — в
`existing`, одно на оба режима.

Спам держат три вещи, и ни одна не требует капчи: скрытое поле, которое
человек не видит и не заполняет; лимит заявок с одного адреса (IPv6 — сети
/64) в час и общий потолок на всех; согласие галочкой. Всё, что за ними, —
в журнале с адресом.

Та же заявка приходит и из ПРОГРАММЫ (`API_PATH`, 26.09): директор заполняет
её на странице активации, и программа активируется сама, без файла. Правила
те же — `clean`, `existing`, `submit`, лимит; отличие одно: новой клинике
сразу отдаётся её токен (`license.renew_token`), и программа спрашивает по
нему `/v1/license`, пока файл не выдан. ⚠️ Здесь повтор объявляется (409):
программе нечем активироваться, а законный повтор — переустановка на новом
компьютере, и ей нужен ответ, а не вечное ожидание. Цена — ответ «эта
клиника уже зарегистрирована»; перебор держит тот же лимит с адреса и общий
потолок.

Новый компьютер той же клиники (26.09) — код на e-mail: на повтор из
программы сервер шлёт шестизначный код на адрес, который у клиники УЖЕ
записан (не на вписанный в заявку), и отдаёт программе `verify_id`. Верный
код (`VERIFY_PATH`) меняется на токен клиники — дальше как у новой. Код живёт
CODE_TTL, выдерживает CODE_ATTEMPTS ошибок и один успех, хранится хешем;
кодов клинике — не больше CODES_PER_HOUR в час, проверок с адреса — не больше
VERIFY_PER_HOUR. Чужой, вписавший IDNO клиники, получит «код отправлен», а
код — владелец ящика.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import config, db, license, mail

MODE_AUTO, MODE_APPROVE = "auto", "approve"
ORIGIN_FORM, ORIGIN_PROGRAM = "form", "program"   # clinics.origin: откуда пришла заявка
API_PATH = "/v1/trial"           # заявка из программы (JSON), ответ — токен для /v1/license
VERIFY_PATH = "/v1/verify"       # код из письма → токен клиники (новый компьютер)
CODE_TTL = timedelta(minutes=15)
CODE_ATTEMPTS = 5                # ошибок на один код; дальше код сгорает
CODES_PER_HOUR = 3               # кодов одной клинике в час: письма не станут спамом
VERIFY_PER_HOUR = 20             # проверок кода с одного адреса в час
_verify_hits: dict[str, list[float]] = {}
MAX_PER_HOUR = 5                 # заявок с одного адреса (IPv6 — с одной /64) в час
MAX_TOTAL_PER_HOUR = 60          # заявок со всех адресов в час: потолок на случай ротации адресов
_hits: dict[str, list[float]] = {}
_all: list[float] = []
HONEYPOT = "website"             # поле, которого нет для человека
ISSUED, ISSUED_UNMAILED, REQUESTED, DUPLICATE = "issued", "issued_unmailed", "requested", "duplicate"
NAME_MAX, EMAIL_MAX, CONTACT_MAX, PHONE_MAX = 120, 120, 80, 40
# Голый адрес: одна «@», без пробелов и знаков, которыми в заголовке письма
# отделяют имя от адреса или один адрес от другого.
_EMAIL = re.compile(r"^[^@\s<>\"(),;:\[\]]+@[^@\s<>\"(),;:\[\]]+\.[A-Za-z0-9-]{2,}$")
_IDNO = re.compile(r"^[0-9]{13}$")
_DOT_BLIND = ("gmail.com", "googlemail.com")   # точки в имени ящика ничего не значат


def mode() -> str:
    return MODE_AUTO if config.TRIAL_MODE.lower() == MODE_AUTO else MODE_APPROVE


# ---------- спам ----------


def bucket(ip: str) -> str:
    """Ключ лимита: IPv4 — адрес, IPv6 — сеть /64 (у любого клиента их не меньше)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return ip


def limited(ip: str) -> bool:
    """Больше MAX_PER_HOUR заявок с адреса за час, или больше MAX_TOTAL_PER_HOUR со
    всех, — отказ, тем же приёмом, что лимит входа. Считаются и принятые, и
    отказанные после проверки полей: перебор адресов тоже заявки."""
    now = time.time()
    key = bucket(ip)
    stamps = [t for t in _hits.get(key, []) if now - t < 3600]
    if stamps:
        _hits[key] = stamps
    else:
        _hits.pop(key, None)
    _all[:] = [t for t in _all if now - t < 3600]
    return len(stamps) >= MAX_PER_HOUR or len(_all) >= MAX_TOTAL_PER_HOUR


def note(ip: str) -> None:
    now = time.time()
    _hits.setdefault(bucket(ip), []).append(now)
    _all.append(now)


# ---------- поля ----------


def clean(fields: dict) -> tuple[dict, str]:
    """(чистые поля, код ошибки или ''). Коды — ключи views.TRIAL_MSG.
    Пробелы и переводы строк внутри полей схлопываются в один пробел: поле
    уходит в заголовок письма, а перевод строки там — второй заголовок."""
    f = {k: " ".join((fields.get(k) or "").split()) for k in ("name", "idno", "contact_name", "email", "phone")}
    f["idno"] = f["idno"].replace(" ", "")
    f["email"] = f["email"].replace(" ", "")
    if not 2 <= len(f["name"]) <= NAME_MAX:
        return f, "bad_name"
    if f["idno"] and not _IDNO.match(f["idno"]):
        return f, "bad_idno"
    if not f["email"] or len(f["email"]) > EMAIL_MAX or not _EMAIL.match(f["email"]):
        return f, "bad_email"
    if len(f["contact_name"]) > CONTACT_MAX or len(f["phone"]) > PHONE_MAX:
        return f, "too_long"
    if (fields.get("consent") or "") != "1":
        return f, "no_consent"
    return f, ""


def canonical(email: str) -> str:
    """Один ящик — одна форма: регистр не важен, `+метка` в имени ящика отбрасывается,
    у gmail точки в имени ничего не значат. Хранится и в письмо идёт адрес, как
    его написали; сравнивается — эта форма."""
    local, _, domain = email.lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in _DOT_BLIND:
        local = local.replace(".", "")
    return f"{local}@{domain}"


def existing(con: sqlite3.Connection, idno: str, email: str) -> sqlite3.Row | None:
    """Клиника с тем же IDNO или тем же ящиком — заявка, пробный или абонемент.
    Скрытая заявка не считается: «Скрыть» освобождает IDNO и e-mail."""
    want = canonical(email)
    domain = want.partition("@")[2]
    rows = con.execute("SELECT * FROM clinics WHERE declined_at IS NULL AND ((? <> '' AND idno = ?) "
                       "OR lower(email) LIKE ?) ORDER BY created_at", (idno, idno, "%@" + domain)).fetchall()
    for r in rows:
        if (idno and r["idno"] == idno) or canonical(r["email"]) == want:
            return r
    return None


# ---------- заявка ----------


def submit(con: sqlite3.Connection, f: dict, ip: str, who: str = "form",
           origin: str = ORIGIN_FORM) -> tuple[str, sqlite3.Row]:
    """Заявка → (исход, клиника). Исход: DUPLICATE — уже есть, ничего не сделано;
    REQUESTED — заведена, ждёт админа; ISSUED — пробный выдан и отправлен.
    `origin` — форма сайта или программа: заявки из обеих ждут в одном списке."""
    old = existing(con, f["idno"], f["email"])
    if old is not None:
        # без clinic_id: чужой текст не должен ложиться в карточку клиники
        db.audit(con, who, "trial_duplicate", None,
                 f"{f['name']}, IDNO {f['idno'] or '—'}, {f['email']}, {ip} — уже есть {old['id']} ({old['name']})")
        return DUPLICATE, old
    cid = "c_" + secrets.token_hex(6)
    now = db.now_iso()
    con.execute("INSERT INTO clinics(id, name, idno, contact_name, email, phone, address, created_at, "
                "origin, requested_at, consent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (cid, f["name"], f["idno"], f["contact_name"], f["email"], f["phone"], "", now, origin, now, now))
    db.audit(con, who, "trial_request", cid, f"{f['name']}, IDNO {f['idno'] or '—'}, {f['email']}, {ip}")
    clinic = con.execute("SELECT * FROM clinics WHERE id=?", (cid,)).fetchone()
    if mode() != MODE_AUTO:
        return REQUESTED, clinic
    valid, grace = license.trial_dates()
    try:
        license.issue(con, clinic, "trial", valid, grace,
                      "cerere din program" if origin == ORIGIN_PROGRAM else "formular de probă", who)
    except RuntimeError as e:
        # ключа выдачи нет: заявка остаётся заявкой, а не откатывается пятисотой
        db.audit(con, who, "trial_no_key", cid, str(e)[:200])
        return REQUESTED, clinic
    code = license.mail_latest(con, clinic, who)
    if code:
        db.audit(con, who, "mail_failed", cid, f"пробный из формы не ушёл: {code}")
        return ISSUED_UNMAILED, clinic
    return ISSUED, clinic


def notify(clinic: sqlite3.Row, outcome: str, ip: str, fields: dict | None = None,
           origin: str = ORIGIN_FORM) -> str:
    """Письмо Олегу о заявке — как вышло; отказ почты не ломает заявку."""
    subject, body = mail.trial_notice(clinic, outcome, ip, fields, origin)
    try:
        return mail.send(config.TRIAL_NOTIFY, subject, body)
    except (RuntimeError, OSError, ValueError):
        return ""


def acknowledge(clinic: sqlite3.Row) -> str:
    """Клинике в режиме approve: заявка принята, файл придёт (из программы — программа
    активируется сама). Отказ почты — молча."""
    subject, body = mail.trial_received(clinic["name"], license.TRIAL_DAYS,
                                        from_program=clinic["origin"] == ORIGIN_PROGRAM)
    try:
        return mail.send(clinic["email"], subject, body)
    except (RuntimeError, OSError, ValueError):
        return ""


# ---------- код на e-mail: новый компьютер той же клиники (26.09) ----------


def _code_hash(vid: str, code: str) -> str:
    return hashlib.sha256(f"{vid}:{code}".encode("utf-8")).hexdigest()


def new_code(con: sqlite3.Connection, clinic: sqlite3.Row, ip: str) -> tuple[str, str]:
    """Код для клиники → (verify_id, код) или ('', ''): у клиники нет ящика или
    лимит кодов за час исчерпан. Письмо шлёт вызывающий — после транзакции."""
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).strftime(db.TS)
    recent = con.execute("SELECT count(*) FROM activation_codes WHERE clinic_id=? AND created_at > ?",
                         (clinic["id"], hour_ago)).fetchone()[0]
    if not clinic["email"] or recent >= CODES_PER_HOUR:
        db.audit(con, "program", "code_limit", clinic["id"], ip)
        return "", ""
    vid = secrets.token_urlsafe(18)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    con.execute("INSERT INTO activation_codes(id, clinic_id, code_hash, created_at, expires_at) "
                "VALUES(?,?,?,?,?)", (vid, clinic["id"], _code_hash(vid, code), now.strftime(db.TS),
                                      (now + CODE_TTL).strftime(db.TS)))
    db.audit(con, "program", "code_sent", clinic["id"], f"на {clinic['email']}, {ip}")
    return vid, code


def verify_limited(ip: str) -> bool:
    """Больше VERIFY_PER_HOUR проверок кода с адреса за час — отказ (перебор кодов)."""
    now = time.time()
    key = bucket(ip)
    stamps = [t for t in _verify_hits.get(key, []) if now - t < 3600]
    _verify_hits[key] = stamps + [now]
    return len(stamps) >= VERIFY_PER_HOUR


def check_code(con: sqlite3.Connection, vid: str, code: str, ip: str) -> sqlite3.Row | None:
    """Верный живой код → клиника (код погашен); иначе None, и ошибка засчитана коду."""
    row = con.execute("SELECT * FROM activation_codes WHERE id=?", (vid,)).fetchone()
    now = datetime.now(timezone.utc)
    if (row is None or row["used_at"] or row["attempts"] >= CODE_ATTEMPTS
            or (db.parse_ts(row["expires_at"]) or now) <= now):
        return None
    if not hmac.compare_digest(row["code_hash"], _code_hash(vid, code)):
        con.execute("UPDATE activation_codes SET attempts = attempts + 1 WHERE id=?", (vid,))
        db.audit(con, "program", "code_bad", row["clinic_id"], ip)
        return None
    con.execute("UPDATE activation_codes SET used_at=? WHERE id=?", (now.strftime(db.TS), vid))
    db.audit(con, "program", "code_ok", row["clinic_id"], ip)
    # заявку скрыли, пока код шёл: токена скрытой клинике не будет (её IDNO и ящик свободны)
    return con.execute("SELECT * FROM clinics WHERE id=? AND declined_at IS NULL",
                       (row["clinic_id"],)).fetchone()

