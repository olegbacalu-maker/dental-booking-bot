"""Кабинет клиники (шаг 3 плана, 01.10): вход через Google, учётная запись, привязка к клинике.

cloud.md › «Кабинет клиники». Клиника входит на cloud.dentpilot.md/cont своим
аккаунтом Google (OpenID Connect: код авторизации, обмен кода на id_token
делает СЕРВЕР, с client_secret). Пароля у нас нет и не будет — его держит
Google; нам приходят только идентификатор аккаунта (`sub`), e-mail и имя.
С 02.10 есть и второй вход — кодом на e-mail (`login.py`, слово Олега «надо
тоже сделать возможность»): учётная запись `provider='email'`, `subject` —
ящик в канонической форме; пароля по-прежнему нет. Дальше обе записи живут
одинаково: привязка к клинике по ящику, регистрация, код по IDNO.
Учётная запись (`accounts`) — это «кто вошёл»; клиника — отдельная строка,
к которой запись привязана (`clinic_id`), и у одной клиники записей может
быть несколько (директор и администратор).

С 26.10 у учётной записи может быть НЕСКОЛЬКО клиник (филиал = ещё одна клиника в том же
кабинете, cabinet.py): вход — `account_clinics`, `accounts.clinic_id` — клиника, открытая
последней. «Adaugă clinică» (`add_clinic`) — заявка на пробный теми же правилами, что
регистрация, но тот же IDNO и тот же ящик разрешены, если совпавшая клиника — своя.
Компьютер новой клиники активируется кодом из кабинета (`new_code` / `use_code`): 7 цифр —
поле кода программы 2.0.9 принимает не больше 7 знаков.

Входит обычно ДИРЕКТОР своим личным Google-аккаунтом (слово Олега 01.10:
«у клиник своего аккаунта нет»), поэтому ящик Google и ящик клиники — чаще
всего разные. Привязка: клиника с тем же подтверждённым ящиком (в
канонической форме, как у формы /proba — trial.canonical) уже есть → это
она, кабинет открывается сразу; нет → страница регистрации: та же заявка
на пробный, что у /proba и у программы (trial.submit, те же правила и
лимиты), только e-mail берётся из Google и не редактируется. Повтор по
IDNO при другом ящике — КОД на ящик, записанный у клиники (тот же
activation_codes, что у программы на новом компьютере, L17): кто читает
почту клиники, тот и решает, пускать ли этот Google-аккаунт; верный код
привязывает запись. Так же подключается второй человек клиники. Ящика у
клиники нет или лимит кодов — отказ словами и письмо Олегу. Смена
директора без кода: Олег вписывает клинике новый e-mail и отвязывает
старую запись.

⛔ Подпись id_token здесь не проверяется — намеренно. Токен приходит не от
браузера, а прямым HTTPS-запросом сервера к Google с client_secret, и Google
в документации говорит ровно это: токен, полученный так, можно не проверять
по подписи. Проверяются iss, aud, exp, nonce и email_verified — то, что
отличает «этот человек в этом входе» от чужого токена. Второй разбор JWT с
JWKS — слой, который однажды разошёлся бы с первым.

Адреса Google (config.GOOGLE_AUTH_URL / GOOGLE_TOKEN_URL) меняют только
тесты: стенд Google живёт в процессе теста, прод знает одни адреса.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import auth, cabinet, config, db, trial
from . import emailconf  # подтверждение ящика входом (27.10)

log = logging.getLogger("cloud.account")

CALLBACK_PATH = "/auth/google/callback"
SCOPE = "openid email profile"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
TIMEOUT = 10                     # обмен кода на токен: Google отвечает за доли секунды
ADDRESS_MAX = 200
# Коды отказа входа — ключи views.CONT_MSG
DENIED, EXPIRED, FAILED, UNVERIFIED, OFF = "google_denied", "google_expired", "google_failed", "google_unverified", "google_off"


@dataclass
class Identity:
    sub: str
    email: str
    name: str


def enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def callback_url() -> str:
    """Тот же адрес, что вписан в консоли Google как Authorized redirect URI."""
    return config.BASE_URL.rstrip("/") + CALLBACK_PATH


# ---------- шаг 1: к Google ----------


def begin() -> tuple[str, str]:
    """(адрес Google, значение куки dp_oauth). Кука несёт state и nonce: state
    сверяется с ответом Google (чужой callback не пройдёт), nonce — с id_token."""
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {"client_id": config.GOOGLE_CLIENT_ID, "redirect_uri": callback_url(),
              "response_type": "code", "scope": SCOPE, "state": state, "nonce": nonce,
              "prompt": "select_account", "access_type": "online"}
    return config.GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params), auth.oauth_cookie(f"{state}|{nonce}")


# ---------- шаг 2: от Google ----------


def _claims(id_token: str) -> dict | None:
    """Полезная нагрузка JWT без проверки подписи (почему — в шапке модуля)."""
    parts = id_token.split(".")
    if len(parts) != 3:
        return None
    try:
        raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return claims if isinstance(claims, dict) else None


def exchange(code: str) -> dict | None:
    """Код → ответ Google (id_token внутри). None — Google не ответил или отказал."""
    body = urllib.parse.urlencode({"code": code, "client_id": config.GOOGLE_CLIENT_ID,
                                   "client_secret": config.GOOGLE_CLIENT_SECRET,
                                   "redirect_uri": callback_url(),
                                   "grant_type": "authorization_code"}).encode("ascii")
    req = urllib.request.Request(config.GOOGLE_TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read(64 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        log.warning("google token: %s %s", e.code, e.read(500)[:500])
        return None
    except (OSError, ValueError) as e:
        log.warning("google token: %r", e)
        return None
    return data if isinstance(data, dict) else None


def verify(claims: dict, nonce: str, now: float | None = None) -> tuple[Identity | None, str]:
    """Проверка claim'ов id_token → (личность, '') или (None, код отказа)."""
    now = now or time.time()
    try:
        exp = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        exp = 0
    if (claims.get("iss") not in ISSUERS or claims.get("aud") != config.GOOGLE_CLIENT_ID
            or exp <= now or not nonce or claims.get("nonce") != nonce):
        return None, FAILED
    sub, email = str(claims.get("sub") or ""), str(claims.get("email") or "").strip()
    if not sub or not email:
        return None, FAILED
    if claims.get("email_verified") is not True:
        return None, UNVERIFIED
    name = " ".join(str(claims.get("name") or "").split())[:trial.CONTACT_MAX]
    return Identity(sub, email[:trial.EMAIL_MAX], name), ""


def finish(code: str, state: str, cookie: str) -> tuple[Identity | None, str]:
    """Callback Google: state против куки, обмен кода, проверка токена."""
    saved = auth.read_oauth_cookie(cookie)
    if saved is None:
        return None, EXPIRED
    want_state, _, nonce = saved.partition("|")
    if not code or not state or not secrets.compare_digest(state, want_state):
        return None, EXPIRED
    data = exchange(code)
    if not data or not isinstance(data.get("id_token"), str):
        return None, FAILED
    claims = _claims(data["id_token"])
    if claims is None:
        return None, FAILED
    return verify(claims, nonce)


# ---------- учётные записи ----------


def find(con: sqlite3.Connection, sub: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM accounts WHERE provider='google' AND subject=?", (sub,)).fetchone()


def get(con: sqlite3.Connection, aid: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()


def login(con: sqlite3.Connection, ident: Identity, ip: str) -> sqlite3.Row:
    """Вошедший Google-аккаунт → строка accounts (новая или прежняя). Запись без
    клиники тут же привязывается к клинике с тем же подтверждённым ящиком, если
    такая есть и не скрыта."""
    now = db.now_iso()
    acc = find(con, ident.sub)
    if acc is None:
        aid = "a_" + secrets.token_hex(6)
        con.execute("INSERT INTO accounts(id, provider, subject, email, name, created_at, last_login_at) "
                    "VALUES(?,?,?,?,?,?,?)", (aid, "google", ident.sub, ident.email, ident.name, now, now))
        db.audit(con, ident.email, "account_new", None, f"Google, {ip}")
    else:
        aid = acc["id"]
        con.execute("UPDATE accounts SET email=?, name=?, last_login_at=? WHERE id=?",
                    (ident.email, ident.name, now, aid))
    acc = get(con, aid)
    if not clinics(con, acc):
        link_by_email(con, acc, ident.email)
        acc = get(con, aid)
    emailconf.by_mailbox(con, ident.email, ident.email)   # Google подтвердил ящик (email_verified)
    db.audit(con, ident.email, "account_login", acc["clinic_id"], ip)
    return acc


def login_email(con: sqlite3.Connection, email: str, ip: str) -> sqlite3.Row:
    """Вход кодом на e-mail (02.10): запись provider='email' (новая или прежняя),
    subject — ящик в канонической форме, e-mail — как ввели (строчными). Без
    клиники — привязка к клинике с тем же ящиком, как у Google-входа."""
    now = db.now_iso()
    email = email.strip().lower()
    canon = trial.canonical(email)
    acc = con.execute("SELECT * FROM accounts WHERE provider='email' AND subject=?", (canon,)).fetchone()
    if acc is None:
        aid = "a_" + secrets.token_hex(6)
        con.execute("INSERT INTO accounts(id, provider, subject, email, name, created_at, last_login_at) "
                    "VALUES(?,?,?,?,?,?,?)", (aid, "email", canon, email, "", now, now))
        db.audit(con, email, "account_new", None, f"e-mail, {ip}")
    else:
        aid = acc["id"]
        con.execute("UPDATE accounts SET last_login_at=? WHERE id=?", (now, aid))
    acc = get(con, aid)
    if not clinics(con, acc):
        link_by_email(con, acc, email)
        acc = get(con, aid)
    emailconf.by_mailbox(con, email, email)               # код пришёл на этот ящик
    db.audit(con, email, "account_login", acc["clinic_id"], f"e-mail, {ip}")
    return acc


def link(con: sqlite3.Connection, acc: sqlite3.Row, clinic_id: str, how: str) -> None:
    """Вход учётной записи в клинику; она же становится открытой (accounts.clinic_id)."""
    con.execute("INSERT OR IGNORE INTO account_clinics(account_id, clinic_id, added_at, how) VALUES(?,?,?,?)",
                (acc["id"], clinic_id, db.now_iso(), how[:200]))
    con.execute("UPDATE accounts SET clinic_id=? WHERE id=?", (clinic_id, acc["id"]))
    db.audit(con, acc["email"], "account_link", clinic_id, how)


def link_by_email(con: sqlite3.Connection, acc: sqlite3.Row, email: str) -> None:
    """Запись без клиник — вход во ВСЕ живые клиники с этим ящиком (у филиала он бывает тот же,
    что у главной); открыта — ГЛАВНАЯ, первая по дате, а в одну секунду — по порядку заведения
    (rowid: id случаен, и при равной секунде «первая по id» — случайная клиника). Открытая
    ставится явно, а не «какая привязалась последней». Сравнение ящиков — trial.canonical."""
    want = trial.canonical(email)
    domain = want.partition("@")[2]
    rows = [r for r in con.execute("SELECT * FROM clinics WHERE declined_at IS NULL AND lower(email) LIKE ? "
                                   "ORDER BY created_at, rowid", ("%@" + domain,)).fetchall()
            if r["email"] and trial.canonical(r["email"]) == want]
    for r in rows:
        link(con, acc, r["id"], f"по e-mail {email}")
    if rows:
        con.execute("UPDATE accounts SET clinic_id=? WHERE id=?", (rows[0]["id"], acc["id"]))


def detach(con: sqlite3.Connection, acc: sqlite3.Row, who: str) -> None:
    """Отвязать и удалить запись: следующий вход этого аккаунта — как первый. Вход во все её
    клиники уходит вместе с ней."""
    con.execute("DELETE FROM account_clinics WHERE account_id=?", (acc["id"],))
    con.execute("DELETE FROM accounts WHERE id=?", (acc["id"],))
    db.audit(con, who, "account_detach", acc["clinic_id"], f"{acc['email']} ({acc['id']})")


def of_clinic(con: sqlite3.Connection, clinic_id: str) -> list:
    return cabinet.accounts_of(con, clinic_id)


def clinics(con: sqlite3.Connection, acc: sqlite3.Row) -> list:
    """Клиники учётной записи по дате заведения (главная первой). Сессия кнопки программы
    (contlink.py) — только своя клиника."""
    if scoped(acc):
        return con.execute("SELECT * FROM clinics WHERE id=?", (acc["clinic_id"],)).fetchall()
    return cabinet.of_account(con, acc["id"])


PROGRAM = "program"       # provider сессии кнопки «Deschide contul clinicii» (27.10, contlink.py)


def scoped(acc) -> bool:
    """Вошли ли кнопкой программы: такой сессии — одна клиника, без кабинета вокруг."""
    return acc is not None and acc["provider"] == PROGRAM


def pick(con: sqlite3.Connection, acc: sqlite3.Row, c: str, post: bool = False) -> sqlite3.Row | None:
    """Какая клиника у этого запроса кабинета. Названа (`?c=`) — только своя. Не названа:
    страница — открытая последней (иначе первая); ⛔ форма — только если клиника у записи
    ОДНА: вкладка, открытая на одной клинике, не должна записать в другую (намерение — из
    формы, а не из того, что открыто сейчас). None — нет такой или не своя."""
    mine = clinics(con, acc)
    if c:
        return next((r for r in mine if r["id"] == c), None)
    if post:
        return mine[0] if len(mine) == 1 else None
    return next((r for r in mine if r["id"] == acc["clinic_id"]), mine[0] if mine else None)


def register(con: sqlite3.Connection, acc: sqlite3.Row, f: dict, ip: str) -> tuple[str, sqlite3.Row]:
    """Регистрация клиники из кабинета: заявка на пробный теми же правилами, что
    /proba (trial.submit), e-mail — ящик Google. Не повтор → запись привязана."""
    outcome, clinic = trial.submit(con, dict(f, email=acc["email"]), ip, who=acc["email"],
                                   origin=trial.ORIGIN_CONT)
    if outcome != trial.DUPLICATE:
        link(con, acc, clinic["id"], "регистрация в кабинете")
    return outcome, clinic


def request_link(con: sqlite3.Connection, acc: sqlite3.Row, clinic: sqlite3.Row, ip: str) -> tuple[str, str]:
    """Повтор по IDNO: код на ящик клиники → (verify_id, код) или ('', ''): ящика
    нет или лимит кодов за час. Письмо шлёт вызывающий — после транзакции."""
    return trial.new_code(con, clinic, ip, who=acc["email"])


def confirm_link(con: sqlite3.Connection, acc: sqlite3.Row, vid: str, code: str, ip: str) -> sqlite3.Row | None:
    """Верный код → запись привязана к клинике кода и к остальным клиникам её кабинета (кто
    читает почту клиники, тот и решает — 26.10); None — код не подошёл."""
    clinic = trial.check_code(con, vid, code, ip, who=acc["email"])
    if clinic is None:
        return None
    for r in reversed(cabinet.of(con, clinic["id"])):
        if r["id"] != clinic["id"] and r["declined_at"] is None:
            link(con, acc, r["id"], f"clinica din același cont cu {clinic['name']}")
    link(con, acc, clinic["id"], f"cod pe e-mailul clinicii, Google {acc['email']}")
    return clinic


def clean_edit(fields: dict) -> tuple[dict, str]:
    """Реквизиты из кабинета: те же границы, что у заявки; IDNO — 13 цифр или пусто."""
    f = {k: " ".join((fields.get(k) or "").split()) for k in ("name", "idno", "contact_name", "phone", "address")}
    f["idno"] = f["idno"].replace(" ", "")
    if not 2 <= len(f["name"]) <= trial.NAME_MAX:
        return f, "bad_name"
    if f["idno"] and not trial.IDNO_RE.match(f["idno"]):
        return f, "bad_idno"
    if (len(f["contact_name"]) > trial.CONTACT_MAX or len(f["phone"]) > trial.PHONE_MAX
            or len(f["address"]) > ADDRESS_MAX):
        return f, "too_long"
    return f, ""


def idno_taken(con: sqlite3.Connection, idno: str, clinic_id: str) -> bool:
    """Тот же IDNO у другой живой клиники — кабинету его не присвоить. Клиники своего
    кабинета не в счёт: у филиалов IDNO общий (26.10)."""
    if not idno:
        return False
    own = cabinet.ids(con, clinic_id)
    return any(r["id"] not in own for r in
               con.execute("SELECT id FROM clinics WHERE idno=? AND id<>? AND declined_at IS NULL",
                           (idno, clinic_id)).fetchall())


# ---------- клиника в кабинет: «Adaugă clinică» (26.10) ----------

CLINICS_MAX = 20          # клиник у одной записи: потолок от ошибки и спама, не тариф


def clean_new(fields: dict) -> tuple[dict, str]:
    """Новая клиника кабинета: поля и правила заявки на пробный (trial.clean) плюс адрес — по
    нему филиалы различают в списке, поэтому обязателен."""
    f, code = trial.clean(fields)
    f["address"] = " ".join((fields.get("address") or "").split())
    if code:
        return f, code
    if not f["address"]:
        return f, "need_address"
    if len(f["address"]) > ADDRESS_MAX:
        return f, "too_long"
    return f, ""


def add_clinic(con: sqlite3.Connection, current: sqlite3.Row, f: dict, ip: str, who: str,
               origin: str = trial.ORIGIN_CONT_ADD) -> tuple[str, sqlite3.Row]:
    """Ещё одна клиника кабинета `current` → (исход trial.submit, клиника). Заявка на пробный
    теми же правилами, что у любой новой клиники, но ждёт одобрения Олега при любом режиме
    (trial.APPROVE_ALWAYS); тот же IDNO или ящик разрешены, если совпавшая клиника — этого
    кабинета, чужая — DUPLICATE, ничего не заведено. Вход в новую — у всех записей кабинета
    `current`: директор и администратор видят одно и то же."""
    own = cabinet.ids(con, current["id"])
    outcome, clinic = trial.submit(con, f, ip, who=who, origin=origin, allow=own)
    if outcome == trial.DUPLICATE:
        return outcome, clinic
    marks = ",".join("?" * len(own))
    con.execute(f"INSERT OR IGNORE INTO account_clinics(account_id, clinic_id, added_at, how) "
                f"SELECT DISTINCT account_id, ?, ?, ? FROM account_clinics WHERE clinic_id IN ({marks})",
                (clinic["id"], db.now_iso(), f"adăugată lângă {current['name']}"[:200], *sorted(own)))
    db.audit(con, who, "clinic_added", clinic["id"], f"{clinic['name']} — в кабинет {current['name']} ({current['id']})")
    return outcome, con.execute("SELECT * FROM clinics WHERE id=?", (clinic["id"],)).fetchone()


def add_sibling(con: sqlite3.Connection, current: sqlite3.Row, f: dict, who: str) -> tuple[str, sqlite3.Row]:
    """Админка › «Добавить клинику в кабинет» (Олег 26.10: «и владелец и я в админке»): клиника
    как из админки (без заявки и пробного — его выдаёт кнопка карточки), входы кабинета `current`.
    → ('created', клиника) или (trial.DUPLICATE, чужая клиника с этим IDNO или ящиком)."""
    own = cabinet.ids(con, current["id"])
    if f["idno"] or f["email"]:
        # ящика нет — сверка только по IDNO: пустой ящик совпал бы с любой клиникой без ящика
        old = trial.existing(con, f["idno"], f["email"] or "-@-", own)
        if old is not None:
            return trial.DUPLICATE, old
    cid = "c_" + secrets.token_hex(6)
    con.execute("INSERT INTO clinics(id, name, idno, contact_name, email, phone, address, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)", (cid, f["name"], f["idno"], f["contact_name"], f["email"], f["phone"],
                                            f["address"], db.now_iso()))
    marks = ",".join("?" * len(own))
    con.execute(f"INSERT OR IGNORE INTO account_clinics(account_id, clinic_id, added_at, how) "
                f"SELECT DISTINCT account_id, ?, ?, ? FROM account_clinics WHERE clinic_id IN ({marks})",
                (cid, db.now_iso(), f"adăugată de DentPilot lângă {current['name']}"[:200], *sorted(own)))
    db.audit(con, who, "clinic_added", cid, f"{f['name']} — в кабинет {current['name']} ({current['id']}), из админки")
    return "created", con.execute("SELECT * FROM clinics WHERE id=?", (cid,)).fetchone()


# ---------- код активации из кабинета (26.10) ----------
#
# Компьютер клиники кабинета активируется обычным путём программы: заявка с тем же IDNO →
# «клиника известна» → поле кода. Код из письма (6 цифр) привязывает компьютер к клинике,
# которую нашла заявка (главной: она старше); код кабинета (7 цифр) — к той, для которой его
# выдали. ⛔ 7, не больше и не буквы: поле кода программы 2.0.9 — maxlength 7, inputmode numeric
# (bot/app/core/layout.py, _CODE_FORM). Перебор держат: живой verify_id обязателен (его даёт
# только заявка, кодов на клинику — trial.CODES_PER_HOUR), ошибки считаются этому verify_id
# (trial.CODE_ATTEMPTS), проверок с адреса — trial.VERIFY_PER_HOUR; живые коды не совпадают.

CODE_DIGITS = 7
CODE_TTL = timedelta(days=7)
CODES_PER_HOUR = 10       # кодов одной клинике из кабинета в час


def is_cabinet_code(code: str) -> bool:
    return len(code) == CODE_DIGITS and code.isdigit()


def _hash(code: str) -> str:
    return hashlib.sha256(f"cabinet:{code}".encode("ascii")).hexdigest()


def new_code(con: sqlite3.Connection, clinic: sqlite3.Row, who: str) -> tuple[str, str]:
    """Код для компьютера клиники → (код, срок ISO) или ('', '') — лимит в час. Прежний
    неиспользованный код этой клиники гаснет: живой у клиники один."""
    now = datetime.now(timezone.utc)
    stamp = now.strftime(db.TS)
    hour_ago = (now - timedelta(hours=1)).strftime(db.TS)
    if con.execute("SELECT count(*) FROM cabinet_codes WHERE clinic_id=? AND created_at>?",
                   (clinic["id"], hour_ago)).fetchone()[0] >= CODES_PER_HOUR:
        db.audit(con, who, "code_limit", clinic["id"], "код кабинета")
        return "", ""
    con.execute("UPDATE cabinet_codes SET expires_at=? WHERE clinic_id=? AND used_at IS NULL AND expires_at>?",
                (stamp, clinic["id"], stamp))
    while True:                                  # живые коды разных клиник не совпадают
        code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
        if not con.execute("SELECT 1 FROM cabinet_codes WHERE code_hash=? AND used_at IS NULL AND expires_at>?",
                           (_hash(code), stamp)).fetchone():
            break
    until = (now + CODE_TTL).strftime(db.TS)
    con.execute("INSERT INTO cabinet_codes(clinic_id, code_hash, created_at, expires_at, who) VALUES(?,?,?,?,?)",
                (clinic["id"], _hash(code), stamp, until, who))
    db.audit(con, who, "cont_code", clinic["id"], f"код компьютера из кабинета, до {until[:10]}")
    return code, until


def use_code(con: sqlite3.Connection, vid: str, code: str, ip: str, device: str = "") -> sqlite3.Row | None:
    """Код кабинета с verify_id программы → клиника кода (код и verify_id погашены) или None:
    verify_id не живой, кода нет или он чужого кабинета — тогда ошибка засчитана verify_id, как
    неверный код из письма."""
    row = con.execute("SELECT * FROM activation_codes WHERE id=?", (vid,)).fetchone()
    now = datetime.now(timezone.utc)
    stamp = now.strftime(db.TS)
    if (row is None or row["used_at"] or row["attempts"] >= trial.CODE_ATTEMPTS
            or (db.parse_ts(row["expires_at"]) or now) <= now):
        return None
    own = cabinet.ids(con, row["clinic_id"])
    hit = next((x for x in con.execute("SELECT * FROM cabinet_codes WHERE code_hash=? AND used_at IS NULL "
                                       "AND expires_at>?", (_hash(code), stamp)).fetchall()
                if x["clinic_id"] in own), None)
    if hit is None:
        con.execute("UPDATE activation_codes SET attempts = attempts + 1 WHERE id=?", (vid,))
        db.audit(con, "program", "code_bad", row["clinic_id"], f"код кабинета, {ip}")
        return None
    con.execute("UPDATE cabinet_codes SET used_at=?, device=? WHERE id=?", (stamp, device[:40], hit["id"]))
    con.execute("UPDATE activation_codes SET used_at=? WHERE id=?", (stamp, vid))
    db.audit(con, "program", "cont_code_ok", hit["clinic_id"],
             f"компьютер {device or '—'} активирован кодом кабинета, {ip}")
    return con.execute("SELECT * FROM clinics WHERE id=? AND declined_at IS NULL", (hit["clinic_id"],)).fetchone()
