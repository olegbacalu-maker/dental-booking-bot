"""SMS-пакет на сервере (S3): счёт клиники, отправка без дубля, статусы, имя отправителя.

Контракт — docs/dentpilot-2/sms.md › «Сервер (cloud/)». Программа клиники шлёт
сюда (Bearer — её токен, тот же, что у /v1/license) номер, текст, вид события
и ключ повтора; сервер решает, можно ли (счёт включён, план, имя, остаток,
потолок, тихие часы), списывает пакет ДО вызова sms.md и шлёт от имени
клиники, которое берёт из её записи — поля имени в запросе нет. Провод к
sms.md — smsmd.py; здесь правила.

⭐ Остаток не хранится — выводится: SUM(delta) журнала sms_ledger (pack +N,
send −k, refund +k, bonus/fix ±N с причиной, expire −N). Возврат — только
когда sms.md денег не взял: синхронный отказ, статусы 10 Failed и 11
Rejected. ⛔ 9 Undelivered не возвращается: SMS ушла оператору, деньги
потрачены (так и у sms.md).

⭐ Повтор без дубля — на двух уровнях, потому что своего id у sms.md нет:
1. программа → сервер: пара (клиника, ключ) уникальна; второй запрос с тем же
   ключом получает первый ответ — без второй SMS и второго списания;
2. сервер → sms.md: на молчание sms.md (таймаут, обрыв, 5xx) сообщение
   остаётся `unanswered`, и вслепую его не повторяют: следующая попытка
   программы с тем же ключом (номер и текст она присылает заново — у сервера
   их нет) сперва ищет его у sms.md по номеру, имени и времени первой
   попытки, и только не найдя — шлёт.

⛔ Номер и текст не пишутся никуда — ни в базу (колонок нет), ни в журнал, ни
в лог: они живут в памяти запроса. Ошибки называют код и поле, не значение.

⭐ Имя отправителя — ОБЩЕЕ на клиники кабинета (Олег 26.10: «Имя SMS — общее»): заявка,
заявление и оплаченный год живут у главной клиники кабинета (cabinet.main_of), филиалы шлют
от её имени — `name_owner`, `sender_for`. Остаток, пакеты, потолок, модуль (Basic / Plus) —
у каждой клиники свои. Клиника, у которой своё имя было ДО кабинета, его не теряет.
"""
from __future__ import annotations

import calendar
import logging
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone

from . import cabinet, config, db, license, mail, sms_rule, smsmd, tiers

log = logging.getLogger("cloud.sms")
UTC = timezone.utc

# ---------- время Кишинёва ----------
#
# Сутки отчёта и тихие часы считаются по Кишинёву. zoneinfo без пакета tzdata
# на Windows не знает поясов, а новая зависимость ради одного пояса лишняя:
# правило ЕС, которому Молдова следует с 2022 (tzdata 2026c: переходы в 01:00
# UTC последнего воскресенья марта и октября), — EET +2, летом EEST +3.
# Сторож — test_sms: переходы 2025–2027 против записанных из tzdata.


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() + 1) % 7)


def utc_offset(at: datetime) -> int:
    """Часов к UTC в Кишинёве в момент `at` (aware)."""
    at = at.astimezone(UTC)
    start = datetime.combine(_last_sunday(at.year, 3), time(1), tzinfo=UTC)
    end = datetime.combine(_last_sunday(at.year, 10), time(1), tzinfo=UTC)
    return 3 if start <= at < end else 2


def local(at: datetime) -> datetime:
    """Момент → стенные часы Кишинёва (без пояса)."""
    at = at.astimezone(UTC)
    return (at + timedelta(hours=utc_offset(at))).replace(tzinfo=None)


def day_start(d: date) -> datetime:
    """Полночь дня `d` по Кишинёву → момент UTC."""
    for off in (3, 2):
        cand = datetime.combine(d, time(0), tzinfo=UTC) - timedelta(hours=off)
        if utc_offset(cand) == off:
            return cand
    return datetime.combine(d, time(0), tzinfo=UTC) - timedelta(hours=2)


def quiet_window() -> tuple[int, int]:
    """(с, до) по config.SMS_QUIET «21-8»; кривое значение — умолчание 21–8."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", config.SMS_QUIET or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 23:
        return 21, 8
    return int(m.group(1)), int(m.group(2))


def quiet(now: datetime) -> bool:
    """Тихие часы 21:00–08:00 по Кишинёву — страховка поверх программы. Окно через
    полночь — две половины; равные границы — окна нет (стенд)."""
    start, end = quiet_window()
    h = local(now).hour
    if start == end:
        return False
    return start <= h < end if start < end else (h >= start or h < end)

# ---------- состояния сообщения: одно состояние — одно имя ----------

UNANSWERED = "unanswered"   # sms.md не ответил: принято ли — неизвестно; повтор сперва ищет
RETRY = "retry"             # sms.md: «не сейчас» (429, наш баланс, токен) — не принято, возвращено
REFUSED = "refused"         # sms.md: отказ по существу (422: номер, имя, текст) — не принято, возвращено
QUEUED, SENT, DELIVERED, UNKNOWN = "queued", "sent", "delivered", "unknown"
UNDELIVERED, FAILED, REJECTED = "undelivered", "failed", "rejected"
BY_STATUS = {smsmd.QUEUED: QUEUED, smsmd.SENT: SENT, smsmd.DELIVERED: DELIVERED, smsmd.UNKNOWN: UNKNOWN,
             smsmd.UNDELIVERED: UNDELIVERED, smsmd.FAILED: FAILED, smsmd.REJECTED: REJECTED}
STATES = (UNANSWERED, RETRY, REFUSED, QUEUED, SENT, DELIVERED, UNKNOWN, UNDELIVERED, FAILED, REJECTED)
FINAL = frozenset({DELIVERED, UNDELIVERED, FAILED, REJECTED, REFUSED})   # опрашивать нечего
REFUNDED = frozenset({RETRY, REFUSED, FAILED, REJECTED})                # sms.md денег не взял
# Сводка админки: «доставлено / не доставлено / отказ / в пути»
GROUP = {DELIVERED: "delivered", UNDELIVERED: "undelivered", FAILED: "refused", REJECTED: "refused",
         REFUSED: "refused", RETRY: "refused", QUEUED: "pending", SENT: "pending", UNKNOWN: "pending",
         UNANSWERED: "pending"}

POLL_FIRST = timedelta(hours=1)     # первый опрос — через час после отправки
POLL_EVERY = timedelta(hours=1)     # дальше раз в час
POLL_UNTIL = timedelta(hours=26)    # 24 ч попыток оператора плюс запас
BUSY = timedelta(seconds=60)        # первая попытка моложе — вторая ждёт её, а не ищет
FIND_BACK = timedelta(minutes=2)    # поиск у sms.md — с запасом на расхождение часов

# Вид события (sms.md › «Программа (bot/)» › «События»); свободный текст сюда
# не попадает — в базу едет только имя из списка.
KINDS = ("day_before", "same_day", "booked", "changed", "test")
IDEM_RE = re.compile(r"^[A-Za-z0-9:._+\-]{1,120}$")
MAX_SEGMENTS = 3
IDS_MAX = 200

# ---------- имя отправителя ----------

S_NONE, S_REQUESTED, S_SUBMITTED, S_ACTIVE, S_REJECTED = "none", "requested", "submitted", "active", "rejected"
SENDER_STATES = (S_NONE, S_REQUESTED, S_SUBMITTED, S_ACTIVE, S_REJECTED)
# sms.md: до 11 знаков, латиница, цифры, пробел, точка, тире; хоть одна буква —
# имя из одних цифр оператор принял бы за номер.
SENDER_RE = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9 .\-]{1,11}$")

# ---------- ответы программе: код → (HTTP, текст по-румынски) ----------

CODES = {
    # Модуль SMS выключен — два кода, две причины (23.10, те же слова, что экран SMS 2.0.9):
    # sms_basic — вариант DentPilot Basic (модуль — в Plus, условия § 4 и § 16), путь — оплата
    # Plus; sms_off — ТОЛЬКО ручной тумблер карточки (исключение Олега), путь — написать нам.
    # ⚠️ Программа ≤ 2.0.8 кода sms_basic не знает: покажет его как есть (sms.md › «Варианты»).
    "sms_unconfigured": (503, "Modulul SMS nu este disponibil încă pe server."),
    "sms_not_offered": (503, "Modulul SMS nu este disponibil acum pentru clinica dvs."),
    "sms_off": (423, "Modulul SMS este oprit. Pentru reluare, contactați-ne."),
    "sms_basic": (423, "Modulul SMS este oprit: el face parte din DentPilot Plus. Îl porniți plătind "
                       "varianta Plus („Plătește acum” în Setări › Licența) sau scriindu-ne."),
    "sms_plan": (423, "SMS-urile se trimit doar cu abonament activ."),
    "sms_sender": (423, "Numele expeditorului nu este încă aprobat de operatori."),
    "sms_quiet": (423, "SMS-urile nu se trimit între 21:00 și 08:00."),
    "sms_balance": (402, "SMS-urile plătite s-au terminat — comandați un pachet nou."),
    "sms_cap": (429, "Limita zilnică de SMS a clinicii a fost atinsă."),
    "sms_phone": (400, "Numărul nu este un mobil din Moldova."),
    "sms_text": (400, "Textul este gol sau mai lung de 3 SMS."),
    "sms_kind": (400, "Tip de mesaj necunoscut."),
    "sms_idem": (400, "Cheia mesajului lipsește sau nu este validă."),
    "sms_retry": (503, "Operatorul SMS nu a răspuns — încercăm din nou."),
    "sms_refused": (502, "Operatorul SMS a refuzat mesajul."),
    "sms_name": (400, "Numele expeditorului: până la 11 caractere latine, cifre, spațiu, punct sau cratimă."),
    "sms_name_taken": (409, "Acest nume de expeditor este deja folosit sau cerut de altă clinică — alegeți alt nume."),
    "sms_no_packs": (503, "Pachetele SMS nu sunt disponibile încă."),
    "sms_pack": (400, "Pachetul ales nu există."),
    "sms_no_name": (503, "Numele propriu de expeditor nu este disponibil încă."),
    "sms_name_none": (409, "Alegeți mai întâi numele de expeditor al clinicii."),
    "sms_need_idno": (409, "Pentru nota de plată indicați IDNO-ul clinicii (13 cifre)."),
    "bad_json": (400, "Cererea nu a putut fi citită — actualizați programul."),
}


def answer(code: str, **extra) -> tuple[int, dict]:
    http, text = CODES[code]
    return http, {"ok": False, "code": code, "text": text, **extra}


# ---------- счёт и журнал ----------


def account(con: sqlite3.Connection, clinic_id: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM sms_accounts WHERE clinic_id=?", (clinic_id,)).fetchone()


TRIAL_NOTE = "perioada de probă"


def ensure(con: sqlite3.Connection, clinic_id: str) -> sqlite3.Row:
    """Счёт клиники — заводится при первом обращении: включён, без имени, потолок по умолчанию."""
    con.execute("INSERT OR IGNORE INTO sms_accounts(clinic_id, daily_cap, updated_at) VALUES(?,?,?)",
                (clinic_id, config.SMS_DAILY_CAP, db.now_iso()))
    trial_bonus(con, clinic_id)
    return account(con, clinic_id)


def trial_bonus(con: sqlite3.Connection, clinic_id: str) -> bool:
    """Пробному периоду — SMS_TRIAL_UNITS бесплатно (Олег 16.10), один раз на клинику:
    строка bonus с отметкой TRIAL_NOTE. Проверяется при каждом обращении программы,
    потому что счёт мог завестись раньше пробного файла."""
    if not config.SMS_TRIAL_UNITS:
        return False
    sub = con.execute("SELECT plan FROM subscriptions WHERE clinic_id=?", (clinic_id,)).fetchone()
    if sub is None or sub["plan"] != "trial":
        return False
    if con.execute("SELECT 1 FROM sms_ledger WHERE clinic_id=? AND reason='bonus' AND note=?",
                   (clinic_id, TRIAL_NOTE)).fetchone():
        return False
    ledger(con, clinic_id, config.SMS_TRIAL_UNITS, "bonus", "server", note=TRIAL_NOTE)
    return True


def balance(con: sqlite3.Connection, clinic_id: str) -> int:
    return con.execute("SELECT COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=?",
                       (clinic_id,)).fetchone()[0]


LEDGER_REASONS = ("pack", "send", "refund", "bonus", "fix", "expire")
# Строки журнала, которые считаются РАСХОДОМ: отправка, возврат и правка сегментов
# по сообщению (fix с message_id). Ручная правка Олега (fix без сообщения) — нет.
SPENT_SQL = "reason IN ('send', 'refund') OR (reason='fix' AND message_id IS NOT NULL)"


def ledger(con: sqlite3.Connection, clinic_id: str, delta: int, reason: str, who: str,
           payment_id: int | None = None, message_id: int | None = None, note: str = "") -> None:
    if reason not in LEDGER_REASONS:
        raise ValueError(reason)
    con.execute("INSERT INTO sms_ledger(clinic_id, delta, reason, payment_id, message_id, at, who, note) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (clinic_id, delta, reason, payment_id, message_id, db.now_iso(), who, note[:200]))


def used_today(con: sqlite3.Connection, clinic_id: str, now: datetime) -> int:
    """Сегменты, ушедшие сегодня (сутки Кишинёва), без возвращённых — к потолку."""
    since = day_start(local(now).date()).strftime(db.TS)
    marks = ",".join("?" * len(REFUNDED))
    return con.execute(f"SELECT COALESCE(SUM(segments), 0) FROM sms_messages WHERE clinic_id=? "
                       f"AND sent_at>=? AND state NOT IN ({marks})",
                       (clinic_id, since, *sorted(REFUNDED))).fetchone()[0]


def sender_now(acc: sqlite3.Row | None, now: datetime | None = None) -> str:
    """От какого имени SMS клиники уходят сейчас: одобренное — пока оплачен год
    (sender_until), иначе общее DentPilot (Олег 16.10: без блокировки)."""
    now = now or datetime.now(UTC)
    if acc is not None and acc["sender_live"]:
        until = db.parse_ts(acc["sender_until"])
        if until is not None and until > now:
            return acc["sender_live"]
    return config.SMS_COMMON if config.SMS_COMMON_OK else ""


def name_owner(con: sqlite3.Connection, clinic_id: str) -> str:
    """Чьё имя отправителя у клиники: своё, если своё у неё уже есть (заявка, одобренное имя —
    до кабинета), иначе главной клиники кабинета (26.10). Без кабинета — она сама."""
    own = account(con, clinic_id)
    if own is not None and (own["sender_state"] != S_NONE or own["sender_live"]):
        return clinic_id
    main = cabinet.main_of(con, clinic_id)
    return main["id"] if main is not None else clinic_id


def sender_for(con: sqlite3.Connection, clinic_id: str, now: datetime | None = None) -> str:
    """От какого имени SMS ЭТОЙ клиники уходят сейчас — имя её кабинета (name_owner)."""
    return sender_now(account(con, name_owner(con, clinic_id)), now)


def offered(acc: sqlite3.Row | None) -> bool:
    """Показывать ли пакет этой клинике: токен есть и (всем — DP_SMS_OFFERED, или ей
    одной — отметка «пилот» Олега). Так S7 включается по одной клинике без релиза."""
    return smsmd.enabled() and (config.SMS_OFFERED or bool(acc is not None and acc["pilot"]))


def plan_ok(sub: sqlite3.Row | None, now: datetime) -> bool:
    """Решения S0 (config.SMS_TRIAL, SMS_READONLY): кому пакет вообще доступен."""
    if sub is None:
        return False
    if sub["plan"] == "trial" and not config.SMS_TRIAL:
        return False
    st = license.state(db.parse_ts(sub["valid_until"]), sub["grace_days"] or 0, now)
    return st in ("active", "grace") or (st == "readonly" and config.SMS_READONLY)


def blocked(con: sqlite3.Connection, clinic_id: str, acc: sqlite3.Row, now: datetime) -> str:
    """Почему клиника не может слать сейчас ('' — может). Остаток и потолок — отдельно.
    Порядок — от того, что клиника не изменит, к тому, что изменит оплатой: ручное
    выключение Олега (sms_off) говорится раньше варианта Basic (sms_basic) — оплата Plus
    его не сняла бы. Остаток при выключенном модуле не трогается (условия § 16.10)."""
    if not smsmd.enabled():
        return "sms_unconfigured"
    if not offered(acc):
        return "sms_not_offered"
    if not acc["enabled"]:
        return "sms_off"
    sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (clinic_id,)).fetchone()
    if not plan_ok(sub, now):
        return "sms_plan"
    if not tiers.module_on(sub, now):
        return "sms_basic"
    if not sender_for(con, clinic_id, now):
        return "sms_sender"
    return ""


def packs() -> list[dict]:
    return [{"units": u, "price": p} for u, p in config.SMS_PACKS.items()]


def view(con: sqlite3.Connection, clinic_id: str, now: datetime | None = None) -> dict:
    """GET /v1/sms/account — что видит программа в Setări › SMS."""
    now = now or datetime.now(UTC)
    acc = ensure(con, clinic_id)
    # имя — кабинета (name_owner): у филиала поля имени — главной клиники
    na = account(con, name_owner(con, clinic_id))
    return {"ok": True, "offered": offered(acc), "enabled": bool(acc["enabled"]),
            "sender": na["sender"] if na is not None else "",
            "sender_state": na["sender_state"] if na is not None else S_NONE,
            "sender_note": na["sender_note"] if na is not None else "",
            "sender_until": na["sender_until"] if na is not None else None,
            "sender_prepaid": na["sender_prepaid"] if na is not None else 0,
            "from": sender_now(na, now), "balance": balance(con, clinic_id), "packs": packs(),
            "name_price": config.SMS_NAME_PRICE, "name_days": config.SMS_NAME_DAYS,
            "daily_cap": acc["daily_cap"], "used_today": used_today(con, clinic_id, now),
            "blocked": blocked(con, clinic_id, acc, now), "custom": custom_texts(acc)}


# ---------- личный текст клиники (S6, «Свой текст — по заявке») ----------
#
# Клиника присылает текст Олегу, он вписывает его в карточке; программа
# получает годные тексты в /v1/sms/account и предлагает вариант «Textul
# clinicii». Проверка здесь — та же, что держит готовые тексты программы:
# подстановки из белого списка (sms_rule.custom_ok), RO — латиница без
# диакритики, один сегмент; RU — один сегмент. Образец подстановок — верхняя
# граница длины: самое длинное слово дня и «Clinica …» перед названием.

CUSTOM_SAMPLE = {"ro": {"ziua": "miercuri", "data": "17.10", "ora": "12:00", "telefon": "+373 22 123 456"},
                 "ru": {"ziua": "в воскресенье", "data": "17.10", "ora": "12:00", "telefon": "+373 22 123 456"}}


def custom_texts(acc: sqlite3.Row | None) -> dict:
    """Что программа получает: только включённые и годные тексты, по языкам."""
    if acc is None or not acc["custom_on"]:
        return {}
    return {lang: acc[f"custom_{lang}"] for lang in ("ro", "ru") if sms_rule.custom_ok(acc[f"custom_{lang}"])}


def custom_check(text: str, lang: str, clinic: str) -> str:
    """'' — годен; иначе причина: holes (подстановки), diacritics (RO не GSM-7),
    long (больше одного сегмента на образце)."""
    if not sms_rule.custom_ok(text):
        return "holes"
    label = clinic if "clinic" in clinic.lower() or "клиник" in clinic.lower() else f"Clinica {clinic}"
    sample = sms_rule.render(text, {"clinica": label, **CUSTOM_SAMPLE[lang]})
    enc, _, segs = sms_rule.parts(sample)
    if lang == "ro" and enc != sms_rule.GSM7:
        return "diacritics"
    return "" if segs == 1 else "long"


def set_custom(con: sqlite3.Connection, clinic_id: str, ro: str, ru: str, on: bool, who: str) -> str:
    """Карточка › SMS › «Личный текст клиники»: '' или код отказа (sms_custom_ro /
    sms_custom_ru — какой язык негоден; sms_custom_empty — включён без текста)."""
    texts = {lang: (t or "").replace("\r\n", "\n").strip()[:sms_rule.CUSTOM_MAX]
             for lang, t in (("ro", ro), ("ru", ru))}
    c = con.execute("SELECT name FROM clinics WHERE id=?", (clinic_id,)).fetchone()
    for lang, text in texts.items():
        if text and custom_check(text, lang, c["name"] if c else ""):
            return f"sms_custom_{lang}"
    if on and not any(texts.values()):
        return "sms_custom_empty"
    ensure(con, clinic_id)
    con.execute("UPDATE sms_accounts SET custom_ro=?, custom_ru=?, custom_on=?, updated_at=? WHERE clinic_id=?",
                (texts["ro"], texts["ru"], 1 if on else 0, db.now_iso(), clinic_id))
    db.audit(con, who, "sms_custom", clinic_id,
             f"личный текст {'включён' if on else 'выключен'}: ro {len(texts['ro'])} зн., ru {len(texts['ru'])} зн.")
    return ""


# ---------- отправка ----------


def idem_key(idem: str) -> str:
    """Ключ программы — в базе ХЕШЕМ (29.10, план § 2.4 п. 1): `appt:<id визита>:<kind>:<начало UTC>`
    нёс время приёма пациента, а условия, политика и декларация обещают «только идентификатор».
    Дедупликация и повтор сравнивают только этот столбец, поэтому хеш ей не мешает; старые строки
    захешировала миграция 19 (db._hash_idem). Сторож: cloud/tests/test_sms.py — строки `appt:` в базе нет."""
    import hashlib
    return hashlib.sha256(idem.encode("utf-8")).hexdigest()


def _row(con, clinic_id: str, idem: str):
    return con.execute("SELECT * FROM sms_messages WHERE clinic_id=? AND idem=?",
                       (clinic_id, idem_key(idem))).fetchone()


def _ok(con, row) -> tuple[int, dict]:
    return 200, {"ok": True, "id": row["id"], "segments": row["segments"], "state": row["state"],
                 "balance": balance(con, row["clinic_id"])}


def _set(con, mid: int, **cols) -> None:
    cols.setdefault("state_at", db.now_iso())
    con.execute(f"UPDATE sms_messages SET {', '.join(k + '=?' for k in cols)} WHERE id=?",
                (*cols.values(), mid))


def _refund(con, row, who: str, why: str) -> None:
    ledger(con, row["clinic_id"], int(row["segments"]), "refund", who, message_id=row["id"], note=why)


def _accepted(con, row, pid: str, segments: int, who: str) -> None:
    """sms.md принял: id запоминается; его число сегментов истинно — расхождение = строка fix."""
    _set(con, row["id"], provider_id=pid, state=QUEUED, error="")
    if segments and segments != int(row["segments"]):
        _fix_segments(con, row, segments, who)


def _fix_segments(con, row, segments: int, who: str) -> None:
    ours = int(row["segments"])
    ledger(con, row["clinic_id"], ours - segments, "fix", who, message_id=row["id"],
           note=f"sms.md насчитал {segments} сегм., сервер {ours}")
    _set(con, row["id"], segments=segments, state_at=row["state_at"])
    log.warning("сегменты разошлись: сообщение %s — sms.md %s, сервер %s", row["id"], segments, ours)
    alarm(con, "sms_segments", "DentPilot Cloud: правило сегментов разошлось с sms.md",
          f"Сообщение {row['id']} клиники {row['clinic_id']}: sms.md насчитал {segments} сегм., "
          f"сервер — {ours}. Списано по счёту sms.md (строка fix в журнале). Сверить "
          f"cloud/app/sms_rule.py и bot/app/core/sms_rule.py с правилом sms.md (S2).")


def submit(clinic_id: str, to_raw, text, kind, idem, now: datetime | None = None,
           who: str = "program") -> tuple[int, dict]:
    """POST /v1/sms/send → (HTTP, тело). Сеть — вне транзакций: строка и списание
    коммитятся ДО вызова sms.md, итог — после."""
    now = now or datetime.now(UTC)
    to, why = sms_rule.phone(to_raw if isinstance(to_raw, str) else "")
    if why:
        return answer("sms_phone", reason=why)
    text = text if isinstance(text, str) else ""
    _, _, segs = sms_rule.parts(text)
    if segs == 0 or segs > MAX_SEGMENTS:
        return answer("sms_text", segments=segs)
    if kind not in KINDS:
        return answer("sms_kind")
    if not isinstance(idem, str) or not IDEM_RE.match(idem):
        return answer("sms_idem")
    if not smsmd.enabled():
        return answer("sms_unconfigured")
    with db.connect(immediate=True) as con:
        acc = ensure(con, clinic_id)
        row = _row(con, clinic_id, idem)
        if row is not None and row["provider_id"]:
            return _ok(con, row)
        if row is not None and row["state"] == REFUSED:
            return answer("sms_refused", id=row["id"], error=row["error"])
        if row is not None and row["state"] == UNANSWERED:
            if now - (db.parse_ts(row["sent_at"]) or now) < BUSY:
                return answer("sms_retry", id=row["id"])        # первая попытка ещё идёт
            mode, sender, since = "find", row["sender"], db.parse_ts(row["sent_at"]) or now
        else:
            # новое сообщение — или повтор после «не сейчас» (деньги уже вернулись)
            why = blocked(con, clinic_id, acc, now)
            if why:
                return answer(why)
            if quiet(now):
                return answer("sms_quiet")
            have = balance(con, clinic_id)
            if have < segs:
                return answer("sms_balance", balance=have, segments=segs)
            if used_today(con, clinic_id, now) + segs > int(acc["daily_cap"]):
                return answer("sms_cap", daily_cap=acc["daily_cap"])
            sender, stamp = sender_for(con, clinic_id, now), now.strftime(db.TS)
            if row is None:
                con.execute("INSERT INTO sms_messages(clinic_id, idem, kind, sender, segments, state, "
                            "sent_at, state_at) VALUES(?,?,?,?,?,?,?,?)",
                            (clinic_id, idem_key(idem), kind, sender, segs, UNANSWERED, stamp, stamp))
                row = _row(con, clinic_id, idem)
            else:
                _set(con, row["id"], sender=sender, segments=segs, state=UNANSWERED, error="",
                     sent_at=stamp, state_at=stamp)
                row = _row(con, clinic_id, idem)
            ledger(con, clinic_id, -segs, "send", who, message_id=row["id"])
            mode, since = "send", now
    mid = row["id"]
    if mode == "find":
        try:
            found = smsmd.find(to, sender, (local(since) - FIND_BACK).strftime("%Y-%m-%d %H:%M:%S"))
        except (smsmd.Unanswered, smsmd.Refused) as e:
            log.warning("поиск сообщения %s у sms.md не удался: %s", mid, e)
            return answer("sms_retry", id=mid)
        with db.connect(immediate=True) as con:
            row = con.execute("SELECT * FROM sms_messages WHERE id=?", (mid,)).fetchone()
            if row["provider_id"]:
                return _ok(con, row)
            for pid, body in found:
                # тот же текст и ещё ничей: другое напоминание тому же пациенту — не наше
                if body == text and not con.execute("SELECT 1 FROM sms_messages WHERE provider_id=?",
                                                    (pid,)).fetchone():
                    _accepted(con, row, pid, 0, who)
                    log.info("сообщение %s найдено у sms.md после молчания", mid)
                    return _ok(con, _row(con, clinic_id, idem))
    try:
        got = smsmd.send(sender, to, text)
    except smsmd.Unanswered as e:
        log.warning("sms.md не ответил на сообщение %s: %s", mid, e)
        with db.connect() as con:
            _set(con, mid, error="no_answer")
        return answer("sms_retry", id=mid)
    except smsmd.Refused as e:
        log.warning("sms.md отказал в сообщении %s: %s", mid, e)
        temporary = e.http in (401, 402, 403, 429)
        error = e.code + ((":" + ",".join(e.fields)) if e.fields else "")
        with db.connect() as con:
            row = con.execute("SELECT * FROM sms_messages WHERE id=?", (mid,)).fetchone()
            _set(con, mid, state=RETRY if temporary else REFUSED, error=error[:80])
            _refund(con, row, who, f"sms.md: {error}"[:200])
            if e.http in (401, 402, 403):
                alarm(con, "sms_smsmd_" + str(e.http), f"DentPilot Cloud: sms.md отказывает ({e.code})",
                      f"sms.md ответил {e.http} {e.code} на отправку: "
                      + ("на нашем счёте sms.md нет денег — пополнить депозит."
                         if e.http == 402 else "токен DP_SMSMD_TOKEN не принят или без прав messages:send.")
                      + " SMS клиник не уходят, пакеты возвращаются; программа повторит сама.")
        return answer("sms_retry" if temporary else "sms_refused", id=mid, error=error)
    with db.connect(immediate=True) as con:
        row = con.execute("SELECT * FROM sms_messages WHERE id=?", (mid,)).fetchone()
        _accepted(con, row, got["id"], got["segments"], who)
        return _ok(con, con.execute("SELECT * FROM sms_messages WHERE id=?", (mid,)).fetchone())


def states(con: sqlite3.Connection, clinic_id: str, ids) -> list[dict]:
    """POST /v1/sms/status — состояние своих сообщений; чужие и неизвестные id молча пропускаются."""
    want = []
    for i in ids if isinstance(ids, list) else []:
        try:
            want.append(int(i))
        except (TypeError, ValueError):
            continue
    want = want[:IDS_MAX]
    if not want:
        return []
    rows = con.execute(f"SELECT id, state, error FROM sms_messages WHERE clinic_id=? AND id IN "
                       f"({','.join('?' * len(want))}) ORDER BY id", (clinic_id, *want)).fetchall()
    return [{"id": r["id"], "state": r["state"], "error": r["error"]} for r in rows]


# ---------- статусы: уведомление и опрос ----------


def apply(con: sqlite3.Connection, row: sqlite3.Row, status: int, segments: int, who: str) -> str:
    """Истина от sms.md (GET /messages/{id}) → состояние строки. Конечное не трогается;
    переход в 10/11 возвращает сегменты один раз (из конечного обратно не выходят)."""
    _set(con, row["id"], checked_at=db.now_iso(), state_at=row["state_at"])
    if row["state"] in FINAL:
        return row["state"]
    new = BY_STATUS.get(status)
    if segments and segments != int(row["segments"]):
        _fix_segments(con, row, segments, who)
        row = con.execute("SELECT * FROM sms_messages WHERE id=?", (row["id"],)).fetchone()
    if new is None or new == row["state"]:
        return row["state"]
    _set(con, row["id"], state=new)
    if new in REFUNDED:
        _refund(con, row, who, f"sms.md: статус {status}")
    return new


def recheck(pid: str, status_hint: int | None = None, who: str = "smsmd") -> str:
    """Уведомление о доставке — сигнал, не истина: состояние перепроверяется
    запросом. Дубль (та же пара id + status_id, что уже применена) и чужой id —
    без запроса. Возвращает итоговое состояние или ''."""
    with db.connect() as con:
        row = con.execute("SELECT * FROM sms_messages WHERE provider_id=?", (pid,)).fetchone()
    if row is None or row["state"] in FINAL:
        return row["state"] if row is not None else ""
    if status_hint is not None and BY_STATUS.get(status_hint) == row["state"]:
        return row["state"]
    try:
        truth = smsmd.message(pid)
    except (smsmd.Unanswered, smsmd.Refused) as e:
        log.warning("статус сообщения %s не получен: %s", row["id"], e)
        return row["state"]
    with db.connect(immediate=True) as con:
        fresh = con.execute("SELECT * FROM sms_messages WHERE id=?", (row["id"],)).fetchone()
        return apply(con, fresh, truth["status"], truth["segments"], who)


def poll(now: datetime | None = None, who: str = "daily") -> dict:
    """Опрос всех, у кого нет конечного состояния: через час после отправки и раз в
    час до 26 ч. Уведомление только ускоряет — истина приходит и без него."""
    now = now or datetime.now(UTC)
    out = {"checked": 0, "failed": 0}
    if not smsmd.enabled():
        return out
    marks = ",".join("?" * len(FINAL))
    with db.connect() as con:
        rows = con.execute(
            f"SELECT * FROM sms_messages WHERE provider_id IS NOT NULL AND state NOT IN ({marks}) "
            f"AND sent_at>=? AND sent_at<=? AND (checked_at IS NULL OR checked_at<=?) ORDER BY id",
            (*sorted(FINAL), (now - POLL_UNTIL).strftime(db.TS), (now - POLL_FIRST).strftime(db.TS),
             (now - POLL_EVERY).strftime(db.TS))).fetchall()
    for r in rows:
        try:
            truth = smsmd.message(r["provider_id"])
        except (smsmd.Unanswered, smsmd.Refused) as e:
            log.warning("опрос сообщения %s: %s", r["id"], e)
            out["failed"] += 1
            continue
        with db.connect(immediate=True) as con:
            fresh = con.execute("SELECT * FROM sms_messages WHERE id=?", (r["id"],)).fetchone()
            apply(con, fresh, truth["status"], truth["segments"], who)
        out["checked"] += 1
    return out


# ---------- имя отправителя ----------


def suggest(name: str) -> str:
    """Предложение имени из названия клиники: латиница без диакритики, до 11 знаков."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", name or "")
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = re.sub(r"[^A-Za-z0-9 .\-]", "", plain)
    return " ".join(plain.split())[:11].strip()


def name_key(name: str) -> str:
    """Имя для сравнения: без регистра, пробелов, точек и тире — «Zambet Dent»,
    «zambet-dent» и «ZAMBETDENT» пациент на экране читает одинаково."""
    return re.sub(r"[ .\-]", "", name or "").casefold()


def name_holder(con: sqlite3.Connection, clinic_id: str, name: str) -> str:
    """Кто ещё держит или просит это имя: id другой клиники, '*' — общее имя
    DentPilot, '' — свободно. Сверка с sms.md идёт по ИМЕНИ (sync_aliases), и
    одно имя у двух клиник после одобрения включилось бы у обеих. Держит заявка
    (requested, submitted, active) и одобренное имя в sender_live — оно работает
    и пока клиника ждёт новое; отказ (rejected) имя не держит."""
    key = name_key(name)
    if key == name_key(config.SMS_COMMON):
        return "*"
    for r in con.execute("SELECT clinic_id, sender, sender_state, sender_live FROM sms_accounts "
                         "WHERE clinic_id<>?", (clinic_id,)).fetchall():
        asked = r["sender_state"] in (S_REQUESTED, S_SUBMITTED, S_ACTIVE) and name_key(r["sender"]) == key
        if asked or (r["sender_live"] and name_key(r["sender_live"]) == key):
            return r["clinic_id"]
    return ""


def request_sender(con: sqlite3.Connection, clinic_id: str, name: str, who: str) -> str:
    """Заявка на имя (клиника из программы или Олег): '' или код отказа. Прежнее
    одобренное имя работает, пока новое не станет active. Имя, которое держит или
    просит другая клиника (или общее DentPilot), — отказ sms_name_taken. Заявка филиала —
    заявка его кабинета: ложится главной клинике (name_owner, 26.10)."""
    name = " ".join((name or "").split())
    if not SENDER_RE.match(name):
        return "sms_name"
    clinic_id = name_owner(con, clinic_id)
    acc = ensure(con, clinic_id)
    if acc["sender"] == name and acc["sender_state"] in (S_REQUESTED, S_SUBMITTED, S_ACTIVE):
        return ""
    if name_holder(con, clinic_id, name):
        return "sms_name_taken"
    con.execute("UPDATE sms_accounts SET sender=?, sender_state=?, sender_note='', sender_paper_at=NULL, "
                "sender_paper_id=NULL, "
                "updated_at=? WHERE clinic_id=?", (name, S_REQUESTED, db.now_iso(), clinic_id))
    db.audit(con, who, "sms_sender", clinic_id, f"заявка на имя «{name}»")
    return ""


def sender_step(con: sqlite3.Connection, clinic_id: str, step: str, who: str, note: str = "") -> str:
    """Шаги Олега: paper («Заявление получено»), submitted («Подано в sms.md» —
    только с отметкой о заявлении), rejected («Отказ» с причиной). '' или код отказа."""
    acc = ensure(con, clinic_id)
    now = db.now_iso()
    if step == "paper":
        if acc["sender_state"] != S_REQUESTED:
            return "sender_not_requested"
        con.execute("UPDATE sms_accounts SET sender_paper_at=?, updated_at=? WHERE clinic_id=?",
                    (now, now, clinic_id))
        db.audit(con, who, "sms_sender", clinic_id, f"заявление на «{acc['sender']}» получено")
        return ""
    if step == "submitted":
        if acc["sender_state"] != S_REQUESTED:
            return "sender_not_requested"
        if not acc["sender_paper_at"]:
            return "sender_no_paper"
        con.execute("UPDATE sms_accounts SET sender_state=?, updated_at=? WHERE clinic_id=?",
                    (S_SUBMITTED, now, clinic_id))
        db.audit(con, who, "sms_sender", clinic_id, f"«{acc['sender']}» подано в sms.md")
        return ""
    if step == "rejected":
        note = " ".join((note or "").split())[:200]
        if not note:
            return "sender_no_reason"
        if acc["sender_state"] not in (S_REQUESTED, S_SUBMITTED, S_ACTIVE):
            return "sender_not_requested"
        live = "" if acc["sender_live"] == acc["sender"] else acc["sender_live"]
        con.execute("UPDATE sms_accounts SET sender_state=?, sender_note=?, sender_live=?, updated_at=? "
                    "WHERE clinic_id=?", (S_REJECTED, note, live, now, clinic_id))
        db.audit(con, who, "sms_sender", clinic_id, f"«{acc['sender']}» — отказ: {note}")
        return ""
    raise ValueError(step)


def sync_aliases(who: str = "daily") -> dict:
    """Сверка имён с sms.md (GET /v3/sender-aliases): поданное и одобренное
    операторами — active (SMS уходят от него), заблокированное — rejected.
    Заявки без «Подано» не трогаются: в submitted имя идёт только с заявлением.
    Кнопка «Активно» Олегу не нужна — состояние читает сервер."""
    out = {"active": 0, "rejected": 0}
    names = smsmd.aliases()          # бросает — пусть видит вызвавший
    with db.connect(immediate=True) as con:
        for acc in con.execute("SELECT * FROM sms_accounts WHERE sender_state IN (?, ?) OR sender_live<>''",
                               (S_SUBMITTED, S_ACTIVE)).fetchall():
            st = names.get(acc["sender"])
            now_dt = datetime.now(UTC)
            now = now_dt.strftime(db.TS)
            if acc["sender_state"] == S_SUBMITTED and st == smsmd.ALIAS_ACTIVE:
                # оплаченные вперёд годы начинаются с одобрения (Олег 16.10: отсчёт — с одобрения)
                until = acc["sender_until"]
                if acc["sender_prepaid"]:
                    base = db.parse_ts(until)
                    base = base if base is not None and base > now_dt else now_dt
                    until = (base + timedelta(days=config.SMS_NAME_DAYS * int(acc["sender_prepaid"]))).strftime(db.TS)
                con.execute("UPDATE sms_accounts SET sender_state=?, sender_live=?, sender_note='', sender_until=?, "
                            "sender_prepaid=0, updated_at=? WHERE clinic_id=?",
                            (S_ACTIVE, acc["sender"], until, now, acc["clinic_id"]))
                db.audit(con, who, "sms_sender", acc["clinic_id"],
                         f"«{acc['sender']}» одобрено (sms.md)" + (f", имя оплачено до {until[:10]}" if until else ""))
                out["active"] += 1
            elif acc["sender_state"] in (S_SUBMITTED, S_ACTIVE) and st in smsmd.ALIAS_DEAD:
                live = "" if acc["sender_live"] == acc["sender"] else acc["sender_live"]
                con.execute("UPDATE sms_accounts SET sender_state=?, sender_note=?, sender_live=?, updated_at=? "
                            "WHERE clinic_id=?", (S_REJECTED, f"sms.md: статус {st}", live, now, acc["clinic_id"]))
                db.audit(con, who, "sms_sender", acc["clinic_id"], f"«{acc['sender']}» — sms.md: статус {st}")
                out["rejected"] += 1
            if acc["sender_live"] and acc["sender_live"] != acc["sender"] and names.get(acc["sender_live"]) in smsmd.ALIAS_DEAD:
                # прежнее имя заблокировано, пока новое ещё ждёт: молчать, а не слать от мёртвого
                con.execute("UPDATE sms_accounts SET sender_live='', updated_at=? WHERE clinic_id=?",
                            (now, acc["clinic_id"]))
                db.audit(con, who, "sms_sender", acc["clinic_id"], f"прежнее «{acc['sender_live']}» заблокировано у sms.md")
    return out


# ---------- пакет, начисление, письма ----------


def credit_pack(con: sqlite3.Connection, payment: sqlite3.Row, who: str) -> None:
    """Оплаченный платёж kind=sms → +N сегментов (из payments.confirm, один раз на платёж)."""
    units = int(payment["sms_units"] or 0)
    ensure(con, payment["clinic_id"])
    ledger(con, payment["clinic_id"], units, "pack", who, payment_id=payment["id"],
           note=f"пакет {units} по {payment['reference']}")
    db.audit(con, who, "sms_pack", payment["clinic_id"], f"{payment['reference']}: +{units} SMS")


def credit_name(con: sqlite3.Connection, payment: sqlite3.Row, who: str) -> str | None:
    """Оплаченный год имени (kind=sms_name): имя уже одобрено — год от большей из дат
    (сегодня, конец оплаченного); ещё нет — год ждёт одобрения (sender_prepaid).
    Возвращает дату конца или None (ещё не началось)."""
    acc = ensure(con, payment["clinic_id"])
    now = datetime.now(UTC)
    if acc["sender_state"] == S_ACTIVE and acc["sender_live"] == acc["sender"]:
        base = db.parse_ts(acc["sender_until"])
        base = base if base is not None and base > now else now
        until = (base + timedelta(days=config.SMS_NAME_DAYS)).strftime(db.TS)
        con.execute("UPDATE sms_accounts SET sender_until=?, updated_at=? WHERE clinic_id=?",
                    (until, db.now_iso(), payment["clinic_id"]))
        db.audit(con, who, "sms_name", payment["clinic_id"],
                 f"{payment['reference']}: имя «{acc['sender']}» оплачено до {until[:10]}")
        return until
    con.execute("UPDATE sms_accounts SET sender_prepaid=sender_prepaid+1, updated_at=? WHERE clinic_id=?",
                (db.now_iso(), payment["clinic_id"]))
    db.audit(con, who, "sms_name", payment["clinic_id"],
             f"{payment['reference']}: год имени «{acc['sender']}» оплачен — начнётся с одобрения")
    return None


def mail_name(con: sqlite3.Connection, clinic: sqlite3.Row, payment: sqlite3.Row, who: str,
              receipt: tuple[str, bytes] | None = None, summary: str = "") -> str:
    """Письмо об оплаченном имени; код для ?msg= ('' — ушло). `receipt` — cont de
    plată (имя, PDF) вложением, как у письма о лицензии; `summary` — строки оплаты."""
    if not clinic["email"]:
        return "bad_email"
    acc = account(con, clinic["id"])
    until = acc["sender_until"] if acc is not None and acc["sender_state"] == S_ACTIVE else None
    subject, body = mail.sms_name_letter(clinic["name"], acc["sender"] if acc else "", until, payment["reference"])
    if receipt:
        body = mail.with_receipt(body, payment["reference"], summary)
    try:
        where = mail.send(clinic["email"], subject, body, *([receipt] if receipt else []))
    except (RuntimeError, OSError) as e:
        log.error("письмо об имени %s не отправлено: %r", payment["reference"], e)
        return "mail_failed"
    db.audit(con, who, "mail", clinic["id"], f"имя SMS {payment['reference']} на {clinic['email']} ({where})")
    return ""


def credit(con: sqlite3.Connection, clinic_id: str, delta: int, reason: str, note: str, who: str) -> str:
    """«Начислить» Олега: bonus или fix, ±N, причина обязательна. '' или код отказа."""
    note = " ".join((note or "").split())[:200]
    if reason not in ("bonus", "fix"):
        return "credit_reason"
    if not note:
        return "credit_no_note"
    if delta == 0 or abs(delta) > 100000:
        return "credit_amount"
    ensure(con, clinic_id)
    ledger(con, clinic_id, delta, reason, who, note=note)
    db.audit(con, who, "sms_credit", clinic_id, f"{delta:+d} ({reason}): {note}")
    return ""


def set_pilot(con: sqlite3.Connection, clinic_id: str, on: bool, who: str) -> None:
    """«Пилот»: пакет предложен этой клинике, пока DP_SMS_OFFERED пуст."""
    ensure(con, clinic_id)
    con.execute("UPDATE sms_accounts SET pilot=?, updated_at=? WHERE clinic_id=?",
                (1 if on else 0, db.now_iso(), clinic_id))
    db.audit(con, who, "sms_toggle", clinic_id, "пилот: предложено" if on else "пилот снят")


def set_enabled(con: sqlite3.Connection, clinic_id: str, on: bool, who: str) -> None:
    ensure(con, clinic_id)
    con.execute("UPDATE sms_accounts SET enabled=?, updated_at=? WHERE clinic_id=?",
                (1 if on else 0, db.now_iso(), clinic_id))
    db.audit(con, who, "sms_toggle", clinic_id, "включено" if on else "выключено")


def set_cap(con: sqlite3.Connection, clinic_id: str, cap: int, who: str) -> str:
    if cap < 0 or cap > 100000:
        return "cap_bad"
    ensure(con, clinic_id)
    con.execute("UPDATE sms_accounts SET daily_cap=?, updated_at=? WHERE clinic_id=?",
                (cap, db.now_iso(), clinic_id))
    db.audit(con, who, "sms_cap", clinic_id, f"потолок {cap} сегм. в сутки")
    return ""


def mail_pack(con: sqlite3.Connection, clinic: sqlite3.Row, payment: sqlite3.Row, who: str,
              receipt: tuple[str, bytes] | None = None, summary: str = "") -> str:
    """Письмо «pachetul de N SMS a fost activat»; код для ?msg= ('' — ушло). `receipt` —
    cont de plată вложением, `summary` — строки оплаты."""
    if not clinic["email"]:
        return "bad_email"
    subject, body = mail.sms_pack_letter(clinic["name"], int(payment["sms_units"] or 0),
                                         balance(con, clinic["id"]), payment["reference"])
    if receipt:
        body = mail.with_receipt(body, payment["reference"], summary)
    try:
        where = mail.send(clinic["email"], subject, body, *([receipt] if receipt else []))
    except (RuntimeError, OSError) as e:
        log.error("письмо о пакете SMS %s не отправлено: %r", payment["reference"], e)
        return "mail_failed"
    db.audit(con, who, "mail", clinic["id"], f"пакет SMS {payment['reference']} на {clinic['email']} ({where})")
    return ""


ALARM_TO = "_sms"       # строка reminders для писем Олегу: раз в сутки на вид


def alarm(con: sqlite3.Connection, kind: str, subject: str, body: str) -> bool:
    """Письмо Олегу (ящик уведомлений, DP_TRIAL_NOTIFY) — не чаще раза в сутки на вид."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    if con.execute("SELECT 1 FROM reminders WHERE subscription_id=? AND kind=? AND period=?",
                   (ALARM_TO, kind, day)).fetchone():
        return False
    try:
        mail.send(config.TRIAL_NOTIFY, subject, body)
    except (RuntimeError, OSError) as e:
        log.error("тревога %s не отправлена: %r", kind, e)
        return False
    con.execute("INSERT INTO reminders(subscription_id, kind, period, sent_at) VALUES(?,?,?,?)",
                (ALARM_TO, kind, day, db.now_iso()))
    return True


def low_letters(send=None, who: str = "daily") -> list[str]:
    """«Au rămas N SMS» — клинике, чей остаток опустился до порога, раз за пакет
    (период письма — последний пакет: новый пакет даёт новое письмо)."""
    send = send or mail.send
    sent: list[str] = []
    with db.connect() as con:
        rows = con.execute(
            """SELECT c.*, (SELECT COALESCE(SUM(delta), 0) FROM sms_ledger l WHERE l.clinic_id=c.id) AS bal,
                      (SELECT MAX(id) FROM sms_ledger l WHERE l.clinic_id=c.id AND l.reason='pack') AS pack
               FROM clinics c JOIN sms_accounts a ON a.clinic_id=c.id WHERE a.enabled=1""").fetchall()
    now = datetime.now(UTC)
    for r in rows:
        if r["pack"] is None or r["bal"] > config.SMS_LOW or not r["email"]:
            continue
        with db.connect() as con:
            # модуль погашен вариантом Basic — «пополните» не к месту: остаток ждёт возврата на Plus
            sub = con.execute("SELECT * FROM subscriptions WHERE clinic_id=?", (r["id"],)).fetchone()
            if not tiers.module_on(sub, now):
                continue
            if con.execute("SELECT 1 FROM reminders WHERE subscription_id=? AND kind='sms_low' AND period=?",
                           (r["id"], str(r["pack"]))).fetchone():
                continue
            subject, body = mail.sms_low_letter(r["name"], max(0, r["bal"]))
            try:
                where = send(r["email"], subject, body)
            except (RuntimeError, OSError) as e:
                log.error("письмо об остатке SMS клинике %s не отправлено: %r", r["id"], e)
                continue
            con.execute("INSERT INTO reminders(subscription_id, kind, period, sent_at) VALUES(?,?,?,?)",
                        (r["id"], "sms_low", str(r["pack"]), db.now_iso()))
            db.audit(con, who, "mail", r["id"], f"остаток SMS {r['bal']} на {r['email']} ({where})")
            sent.append(r["id"])
    return sent


def _cents(s: str) -> int | None:
    """«123.45» → 12345 (копейки целым — без float)."""
    m = re.fullmatch(r"\s*(-?)(\d+)(?:[.,](\d{1,2}))?\s*", s or "")
    if not m:
        return None
    v = int(m.group(2)) * 100 + int((m.group(3) or "0").ljust(2, "0"))
    return -v if m.group(1) else v


def owed(con: sqlite3.Connection) -> int:
    """Продано и не потрачено — сумма положительных остатков клиник, сегментов."""
    return con.execute("SELECT COALESCE(SUM(b), 0) FROM (SELECT SUM(delta) AS b FROM sms_ledger "
                       "GROUP BY clinic_id HAVING b > 0)").fetchone()[0]


def float_check(now: datetime | None = None) -> dict:
    """Баланс sms.md против проданного остатка и недели расхода (в леях по
    себестоимости). Не хватает — письмо Олегу, раз в сутки."""
    now = now or datetime.now(UTC)
    out = {"balance": None, "owed": 0, "week": 0, "alarm": False, "error": ""}
    cost = _cents(config.SMSMD_SEGMENT_COST) or 0
    with db.connect() as con:
        out["owed"] = owed(con)
        out["week"] = con.execute(f"SELECT COALESCE(-SUM(delta), 0) FROM sms_ledger WHERE ({SPENT_SQL}) AND at>=?",
                                  ((now - timedelta(days=7)).strftime(db.TS),)).fetchone()[0]
    if not smsmd.enabled():
        return out
    try:
        out["balance"] = smsmd.balance()
    except (smsmd.Unanswered, smsmd.Refused) as e:
        out["error"] = str(e)
        return out
    have = _cents(out["balance"])
    need = max(out["owed"], out["week"]) * cost
    if have is not None and have < need:
        with db.connect() as con:
            out["alarm"] = alarm(con, "sms_float", "DentPilot Cloud: на счёте sms.md меньше, чем продано",
                                 f"Баланс sms.md: {out['balance']} MDL. Продано клиникам и не потрачено: "
                                 f"{out['owed']} сегм. (≈ {out['owed'] * cost / 100:.2f} MDL по "
                                 f"{config.SMSMD_SEGMENT_COST}); расход за 7 дней: {out['week']} сегм. "
                                 f"Пополнить депозит sms.md переводом с бизнес-счёта.")
    return out


def expire(now: datetime | None = None, who: str = "daily") -> int:
    """Сгорание пакетов — решение S0 (config.SMS_PACK_DAYS; 0 = не сгорает). Пакет,
    которому исполнилось N дней, сгорает на свой неистраченный остаток: тратится
    старое первым, поэтому от пакета остаётся остаток клиники минус всё
    начисленное после него (не больше самого пакета). Строка `expire` — одна на пакет."""
    days = config.SMS_PACK_DAYS
    if not days:
        return 0
    now = now or datetime.now(UTC)
    burned = 0
    with db.connect(immediate=True) as con:
        packs_due = con.execute(
            "SELECT * FROM sms_ledger p WHERE reason='pack' AND at<=? AND NOT EXISTS "
            "(SELECT 1 FROM sms_ledger e WHERE e.reason='expire' AND e.payment_id=p.payment_id) ORDER BY id",
            ((now - timedelta(days=days)).strftime(db.TS),)).fetchall()
        for p in packs_due:
            left = expired_part(balance(con, p["clinic_id"]), con.execute(
                "SELECT COALESCE(SUM(delta), 0) FROM sms_ledger WHERE clinic_id=? AND id>? AND reason IN ('pack', 'bonus') "
                "AND delta>0", (p["clinic_id"], p["id"])).fetchone()[0], int(p["delta"]))
            ledger(con, p["clinic_id"], -left, "expire", who, payment_id=p["payment_id"],
                   note=f"пакет от {p['at'][:10]} — {days} дн.")
            burned += left
    return burned


def expired_part(balance_now: int, credited_after: int, pack: int) -> int:
    """Сколько сгорает от пакета: остаток минус начисленное после него, в пределах [0, пакет]."""
    return max(0, min(pack, balance_now - credited_after))
