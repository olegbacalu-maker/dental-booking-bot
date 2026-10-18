"""Цикл SMS-напоминаний (S5): кому, когда и через что — рядом с автообновлением лицензии.

Контракт — docs/dentpilot-2/sms.md › «Программа (bot/)». ⭐ SMS уходят, только
пока программа запущена: расписание знает только она, и событие рождается
здесь, а не в cron на сервере. Тик — 60 с, как у `telegram._reminder_loop`;
старт программы цикла не ждёт, сеть — в потоке, отказ — строкой в лог.

Три чистых соседа делают всё, что можно проверить без сервера:
  sms_plan  — тексты, подстановки, окно отправки, тихие часы, настройки;
  sms_rule  — сегменты и годность номера (общий вектор с облаком, S2);
  sms       — провод к /v1/sms/* (как license_renew).
Здесь — связка с базой, лицензией и часами клиники:

1. Счёт (`/v1/sms/account`) перечитывается раз в ACCOUNT_EVERY и по кнопке;
   последний принятый хранится в schema_meta (`sms_account`), чтобы после
   старта без сети программа знала, предлагается ли ей пакет вообще. Нет
   счёта — нет очереди: клиника без пакета не получает ни строки в летописи.
2. Очередь — `sms_log` (db.py): визит попадает в неё, когда наступило окно
   события (`sms_plan.window`), по ключу повтора `appt:{id}:{kind}:{starts_at}`.
   Перенос — новый ключ; отмена, отказ пациента и выключенное событие
   снимают строку до отправки.
3. Отправка — по очереди, в часы бодрствования 08:00–21:00 по часам клиники;
   ответ сервера решает состояние строки. Отказ уровня клиники (нет остатка,
   потолок, пакет выключен, сервер молчит) останавливает проход — следующий
   тик попробует снова, а окно, прошедшее впустую, даёт `expired` с причиной.
4. Состояние доставки опрашивается у сервера (`/v1/sms/status`) раз в
   STATUS_EVERY, до STATUS_UNTIL после отправки.

⛔ Флаги Telegram `reminded_day`/`reminded_2h` здесь не читаются и не пишутся.
⛔ Номер и текст в лог не попадают: строки лога называют id и код.
⚠️ Летопись хранит ГОТОВУЮ строку (db.log_event): слово состояния
разворачивается здесь и сейчас, записанное не переписывается.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from .. import db
from .. import engine as eng
from . import license as lic
from . import rsa_verify
from . import sms as wire
from . import sms_plan as plan
from . import sms_rule as rule

log = logging.getLogger("sms")

TICK = 60.0                                  # секунд между проходами
TICK_ENV = "DENTART_SMS_TICK_S"              # стенд: секунды вместо минуты
ACCOUNT_EVERY = timedelta(minutes=10)        # счёт перечитывается не чаще
STATUS_EVERY = timedelta(minutes=5)          # опрос доставки
STATUS_UNTIL = timedelta(hours=30)           # 24 ч попыток оператора плюс запас и сутки сервера
HORIZON = timedelta(days=plan.SEND_DAY_BACK + 1)   # визиты, у которых окно может быть сегодня
QUEUE_BATCH = 50                             # строк очереди за проход
META_ACCOUNT = "sms_account"                 # schema_meta: последний принятый счёт (JSON)
FORECAST_DAYS = 30                           # прогноз расхода — по визитам последних 30 дней
# «Мало SMS» — по ШТУКАМ (Олег 18.10, контракт Tauri § 4): платный остаток 30
# и меньше, в пробном периоде 10 и меньше (пробных всего 30 — порог платного
# сработал бы с первой SMS). Читает их ТОЛЬКО `low_limit`; прежний порог по
# дням расхода снят — два порога одного состояния расходятся молча.
LOW_PAID = 30
LOW_TRIAL = 10
META_LOW = "sms_low"                         # schema_meta: с какого времени остаток у порога

# Отказы сервера, после которых строка больше не уйдёт никогда (своя вина:
# номер, текст, ключ) — `failed`. Остальные коды — уровня клиники или сервера:
# строка ждёт следующего тика, пока не истечёт окно.
ROW_FINAL = frozenset({"sms_phone", "sms_text", "sms_kind", "sms_idem", "sms_refused", "bad_json"})
# Коды, после которых счёт перечитывается сразу: остаток или состояние
# клиники на сервере изменились, и экран должен это показать.
RECHECK = frozenset({"sms_balance", "sms_off", "sms_not_offered", "sms_plan", "sms_sender",
                     "sms_unconfigured", "sms_cap"})

# Причина для летописи и экрана — по-румынски, коротко; код сервера без строки
# здесь печатается как есть (новый код сервера виден, а не спрятан).
WHY = {
    "offline": "serverul nu a răspuns",
    "refused": "licența nu a fost recunoscută de server",
    "sms_balance": "pachetul SMS s-a terminat",
    "sms_cap": "limita zilnică de SMS a fost atinsă",
    # «Выключить» в карточке клиники облака = клиника отказалась (слово Олега 17.10);
    # экран показывает к этому контакты для возобновления (SmsSettingsScreen, blocked).
    "sms_off": "pachetul SMS este oprit la cererea clinicii",
    "sms_not_offered": "pachetul SMS nu este disponibil",
    "sms_unconfigured": "pachetul SMS nu este disponibil pe server",
    "sms_plan": "abonamentul nu este activ",
    "sms_sender": "numele expeditorului nu este aprobat",
    "sms_retry": "operatorul SMS nu a răspuns",
    "sms_refused": "operatorul SMS a refuzat mesajul",
    "sms_phone": "numărul nu este un mobil din Moldova",
    "sms_text": "textul nu a fost acceptat",
    "sms_quiet": "ore de liniște",
    "program_off": "programul era oprit",
}

# Летопись по состоянию строки: вид события (значок — card.ACT_ICON) и слово.
EVENT = {db.SMS_SENT: ("sms", "SMS trimis"), db.SMS_DELIVERED: ("sms_ok", "SMS livrat"),
         db.SMS_UNDELIVERED: ("sms_fail", "SMS nelivrat"), db.SMS_FAILED: ("sms_fail", "SMS eșuat"),
         db.SMS_EXPIRED: ("sms_fail", "SMS netrimis")}
# состояние сервера (cloud/app/sms.py) → наше; прочие («в пути») ждут опроса
CLOUD_FINAL = {"delivered": db.SMS_DELIVERED, "undelivered": db.SMS_UNDELIVERED,
               "failed": db.SMS_FAILED, "rejected": db.SMS_FAILED, "refused": db.SMS_FAILED}
KIND_LABEL = {plan.DAY_BEFORE: "cu o zi înainte", plan.SAME_DAY: "în ziua vizitei"}

_task: asyncio.Task | None = None
_wake: asyncio.Event | None = None
_lock: asyncio.Lock | None = None
_account: dict | None = None                 # последний ПРИНЯТЫЙ счёт сервера
_account_at: datetime | None = None
_status_at: datetime | None = None
_forecast: dict = {"visits": 0, "month": 0, "daily": 0.0}
_counts: dict = {"queued": 0, "today": 0, "delivered": 0, "failed": 0}   # цифры экрана, с тика
# последний проход: когда, чем кончился, последний отказ (код) — экрану и логу
_last: dict = {"at": None, "outcome": "", "error": "", "sent": 0}
# Эпизод «мало SMS»: когда остаток впервые опустился до порога ('' — выше).
# Ключ уведомления у часов (`core/notices`): после пополнения сбрасывается,
# и следующее падение до порога — новое уведомление, а не забытое старое.
_low_since: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agent() -> str:
    return f"DentPilot/{eng.APP_VERSION}"


# ---------- куда и чем ----------


def target() -> tuple[str, str] | None:
    """(база /v1/sms/, токен) из принятого файла лицензии — или None: файла с
    `renew` нет (исходники, exe без ключей, демо), и SMS взять неоткуда."""
    if not lic.applies():
        return None
    t = lic.renew_target()
    if t is None:
        return None
    base = wire.base_of(t[0])
    return (base, t[1]) if base and rsa_verify.renew_url_ok(base) else None


def available() -> bool:
    return target() is not None


def settings() -> dict:
    return plan.settings((eng.CONFIG or {}).get("sms"))


def account() -> dict | None:
    """Счёт, как его видел сервер в последний раз (копия)."""
    return dict(_account) if _account is not None else None


def offered() -> bool:
    """Показывать ли пакет: решает сервер (`offered`), программа лишь помнит ответ."""
    return bool(_account and _account.get("offered"))


def enabled() -> bool:
    """Сервер пустит отправку: предлагается, включён, не заблокирован планом или именем."""
    return offered() and bool(_account.get("enabled")) and not _account.get("blocked")


def active() -> bool:
    """Пакет РАБОТАЕТ у этой клиники: сервер пускает и хоть одно событие
    включено. Это же состояние решает текст листа на стойке (acord.py):
    бумага обязана совпадать с тем, что делает программа."""
    return enabled() and plan.any_on(settings())


def custom_texts() -> dict:
    """Личный текст клиники по языкам — из счёта сервера, годный по белому списку."""
    raw = (_account or {}).get("custom") or {}
    return {k: v for k, v in raw.items() if k in plan.LANGS and plan.custom_ok(v)} \
        if isinstance(raw, dict) else {}


def forecast() -> dict:
    """Прогноз расхода: визитов за месяц, SMS в месяц при текущих событиях, в день."""
    return dict(_forecast)


def trial() -> bool:
    """Пробный период — по плану принятой лицензии: ровно при нём облако
    начисляет пробные SMS (cloud/app/sms.py › trial_bonus). Счёт сервера
    пробного остатка от платного не отличает."""
    s = lic.current()
    return bool(s is not None and s.claim is not None and s.claim.plan == "trial")


def low_limit(balance: int, is_trial: bool) -> int:
    """⛔ ЕДИНСТВЕННОЕ сравнение «мало SMS»: порог, до которого опустился
    остаток, или 0 — остаток выше. Держит `test_structure` (пороги читает
    только она)."""
    limit = LOW_TRIAL if is_trial else LOW_PAID
    return limit if balance <= limit else 0


LOW_TITLE = "Pachetul SMS se termină"


def low_text(left: int, is_trial: bool) -> str:
    """Что сказать человеку — одни слова на подсказку меню, экран Setări › SMS
    и уведомление у часов. ⚠️ Без «дней»: порог — штуки, и прогноз расхода
    здесь не обещается."""
    if left <= 0:
        return ("Pachetul SMS s-a terminat — memento-urile nu mai pleacă. "
                "Comandați un pachet nou în Setări › SMS.")
    what = "din perioada de probă" if is_trial else "în pachet"
    return (f"Au rămas {left} SMS {what}; când se termină, memento-urile nu mai "
            f"pleacă. Comandați un pachet nou în Setări › SMS.")


def low() -> dict | None:
    """«Мало SMS» — ОДНО состояние на три места: подсказка у пункта меню
    (`layout._sms_alert`), баннер экрана Setări › SMS (`screen`) и уведомление
    у часов (`core/notices`). None — пакет не работает или остатка хватает.
    `since` — ключ эпизода (пусто, пока цикл его не записал)."""
    if not active():
        return None
    is_trial = trial()
    left = int(_account.get("balance") or 0)
    limit = low_limit(left, is_trial)
    if not limit:
        return None
    return {"left": max(0, left), "limit": limit, "trial": is_trial, "since": _low_since,
            "title": LOW_TITLE, "text": low_text(left, is_trial)}


def _track_low() -> bool:
    """Отметить начало или конец эпизода «мало SMS» по принятому счёту. True —
    отметка сменилась (её надо записать). Пакет не пускает — эпизод не
    трогаем: остаток 0 у отказа «не предлагается» — не падение."""
    global _low_since
    if not enabled():
        return False
    hit = low_limit(int(_account.get("balance") or 0), trial())
    if hit and not _low_since:
        _low_since = _now().strftime("%Y%m%dT%H%M%SZ")
        return True
    if not hit and _low_since:
        _low_since = ""                      # пополнили: следующее падение — новый эпизод
        return True
    return False


async def _save_low() -> None:
    if not _track_low():
        return
    try:
        await db.set_meta(META_LOW, _low_since)
    except Exception as e:  # noqa: BLE001 — память эпизода не роняет цикл
        log.warning("sms: low mark not saved: %r", e)


def last() -> dict:
    return dict(_last)


def wake() -> None:
    """Разбудить цикл: настройки сохранены, кнопка нажата — не ждать минуту."""
    if _wake is not None:
        _wake.set()


# ---------- счёт ----------


async def startup() -> None:
    """До первого тика: счёт из прошлого запуска, чтобы страницы знали, есть
    ли пакет, пока сервер ещё не отвечал (или не ответит вовсе)."""
    global _account, _low_since
    raw = await db.get_meta(META_ACCOUNT)
    if raw:
        try:
            data = json.loads(raw)
            _account = data if isinstance(data, dict) else None
        except ValueError:
            _account = None
    _low_since = (await db.get_meta(META_LOW) or "")[:20]


async def _remember(acc: dict | None) -> None:
    global _account, _account_at
    _account, _account_at = acc, _now()
    try:
        await db.set_meta(META_ACCOUNT, json.dumps(acc, ensure_ascii=False) if acc else "")
    except Exception as e:  # noqa: BLE001 — память счёта не роняет цикл
        log.warning("sms: account not saved: %r", e)
    await _save_low()


async def refresh_account(force: bool = False) -> str:
    """Перечитать счёт у сервера. Исход — wire.*; OFFLINE/REFUSED оставляют
    прежний счёт (программа живёт по тому, что знала)."""
    t = target()
    if t is None:
        return wire.OFFLINE
    if not force and _account_at is not None and _now() - _account_at < ACCOUNT_EVERY:
        return wire.OK
    outcome, body = await asyncio.to_thread(wire.account, t[0], t[1], wire.TIMEOUT, _agent(),
                                            lic.identity())
    if outcome == wire.OK:
        await _remember({k: body.get(k) for k in (
            "offered", "enabled", "sender", "sender_state", "sender_note", "sender_until",
            "from", "balance", "packs", "name_price", "name_days", "daily_cap", "used_today",
            "blocked", "custom")})
    elif outcome == wire.DENIED:
        code = body.get("code") or ""
        if code in ("sms_not_offered", "sms_unconfigured"):
            # сервер знает клинику, но пакета ей нет: плитка молчит, очереди нет
            await _remember({"offered": False, "enabled": False, "blocked": code, "balance": 0})
        _last["error"] = code
    else:
        _last["error"] = outcome
    return outcome


# ---------- очередь ----------


def _tg_patient(session_key: str | None) -> bool:
    """Пациент бота при живом боте: напоминает Telegram, SMS не дублирует (S0)."""
    from .layout import tg_configured   # отложенно: layout тянет оболочку целиком
    return bool(session_key and session_key.startswith("tg:") and tg_configured())


async def _enqueue_due(now: datetime, s: dict) -> int:
    """Визиты окна → строки очереди для событий, чьё окно наступило."""
    horizon = now + HORIZON
    rows = await db.sms_candidates(now, horizon)
    if not rows:
        return 0
    known = await db.sms_known_idems(now, horizon)
    local_now = now.astimezone(eng.TZ)
    custom = custom_texts()
    added = 0
    for r in rows:
        number, why = rule.phone(r["phone"])
        if why or _tg_patient(r.get("session_key")):
            continue
        starts = r["starts_at"].astimezone(eng.TZ)
        created = r["created_at"].astimezone(eng.TZ)
        starts_utc = r["starts_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for ev in plan.EVENTS:
            if not s[ev]["on"]:
                continue
            key = plan.idem(r["id"], ev, starts_utc)
            if key in known:
                continue
            win = plan.window(ev, starts, created, hour=s[ev].get("hour", 10),
                              hours=s[ev].get("hours", 2), is_open=lambda d: bool(eng.hours_for(d)))
            if win is None or not (win[0] <= local_now < win[1]):
                continue
            text = plan.text(r["lang"] or "ro", s[ev]["variant"], clinic=eng.CLINIC_NAME,
                             phone=eng.CLINIC_PHONE, phone_line=s[plan.PHONE_LINE_KEY],
                             starts=starts, on_day=local_now.date(), custom=custom)
            _, _, segs = rule.parts(text)
            if await db.sms_enqueue(r["id"], r["patient_id"], ev, number, text, segs, key, win[1]):
                known.add(key)
                added += 1
    return added


async def _log(row: dict, state: str, code: str = "") -> None:
    kind, word = EVENT[state]
    visit = row.get("visit_at")
    when = visit.astimezone(eng.TZ).strftime("%d.%m.%Y %H:%M") if visit else ""
    text = f"{word} ({KIND_LABEL.get(row['kind'], row['kind'])})" + (f" — vizita {when}" if when else "")
    if code:
        text += f": {WHY.get(code, code)}"
    await db.log_event(row["patient_id"], kind, text, actor="sistem")


async def _expire(now: datetime) -> int:
    n = 0
    for r in await db.sms_overdue(now):
        await db.sms_set(r["id"], state=db.SMS_EXPIRED)
        await _log(r, db.SMS_EXPIRED, r.get("error") or "program_off")
        n += 1
    return n


async def _send_queued(base: str, token: str, now: datetime) -> int:
    """Проход по очереди. Возвращает число принятых сервером. Отказ уровня
    клиники или тишина сервера прерывают проход: следующий тик попробует снова."""
    sent = 0
    for r in await db.sms_queue(QUEUE_BATCH):
        if r["until_at"] <= now:
            continue                        # истечёт следующим проходом _expire
        if r["appt_status"] != "confirmed" or r["sms_off"] or r["archived"]:
            await db.sms_delete(r["id"])    # визит отменён или пациент отказался — тихо
            continue
        outcome, body = await asyncio.to_thread(wire.send, base, token, r["phone"], r["text"],
                                                r["kind"], r["idem"], wire.TIMEOUT, _agent(),
                                                lic.identity())
        if outcome == wire.OK:
            await db.sms_set(r["id"], state=db.SMS_SENT, cloud_id=int(body.get("id") or 0) or None,
                             error="", segments=int(body.get("segments") or r["segments"]))
            if _account is not None and isinstance(body.get("balance"), int):
                _account["balance"] = body["balance"]
            await _log(r, db.SMS_SENT)
            log.info("sms: sent row=%s cloud=%s", r["id"], body.get("id"))
            sent += 1
            continue
        if outcome == wire.DENIED:
            code = str(body.get("code") or "sms_refused")
            if code in ROW_FINAL:
                await db.sms_set(r["id"], state=db.SMS_FAILED, error=code[:80])
                await _log(r, db.SMS_FAILED, code)
                log.warning("sms: row=%s failed: %s", r["id"], code)
                continue
            await db.sms_set(r["id"], error=code[:80])
            _last["error"] = code
            log.warning("sms: paused: %s", code)
            if code in RECHECK:
                await refresh_account(force=True)
            break
        for_rest = outcome                  # REFUSED / OFFLINE: ждём, сервера нет
        await db.sms_set(r["id"], error=for_rest)
        _last["error"] = for_rest
        log.warning("sms: paused: %s", for_rest)
        break
    return sent


async def _poll_status(base: str, token: str, now: datetime) -> None:
    global _status_at
    if _status_at is not None and now - _status_at < STATUS_EVERY:
        return
    rows = await db.sms_pending(now - STATUS_UNTIL)
    _status_at = now
    if not rows:
        return
    outcome, body = await asyncio.to_thread(wire.status, base, token, [r["cloud_id"] for r in rows],
                                            wire.TIMEOUT, _agent(), lic.identity())
    if outcome != wire.OK:
        return
    by_id = {it.get("id"): it for it in body.get("items") or [] if isinstance(it, dict)}
    for r in rows:
        it = by_id.get(r["cloud_id"])
        new = CLOUD_FINAL.get((it or {}).get("state"))
        if new is None:
            continue
        await db.sms_set(r["id"], state=new, error=str(it.get("error") or "")[:80])
        await _log(r, new, "" if new == db.SMS_DELIVERED else str(it.get("error") or ""))


async def _refresh_forecast(now: datetime, s: dict) -> None:
    visits = await db.sms_visits_month(now - timedelta(days=FORECAST_DAYS), now)
    per_visit = sum(1 for ev in plan.EVENTS if s[ev]["on"])
    _forecast.update(visits=visits, month=visits * per_visit,
                     daily=visits * per_visit / FORECAST_DAYS)
    local = now.astimezone(eng.TZ)
    _counts.update(await db.sms_counts(local.replace(hour=0, minute=0, second=0, microsecond=0)))


# ---------- проход ----------


async def tick() -> str:
    """Один проход: счёт, снятие выключенных событий, истёкшие, постановка,
    отправка, опрос. Исход — слово для лога и экрана."""
    global _lock
    now = _now()
    t = target()
    if t is None:
        _last.update(at=now, outcome="none")
        return "none"
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        base, token = t
        s = settings()
        await refresh_account()
        await _save_low()                    # план лицензии мог смениться без нового счёта
        for ev in plan.EVENTS:
            if not s[ev]["on"]:
                await db.sms_drop_kind(ev)
        await _refresh_forecast(now, s)
        expired = await _expire(now)
        added = sent = 0
        if enabled():
            added = await _enqueue_due(now, s)
            if plan.awake(now.astimezone(eng.TZ)):
                _last["error"] = ""
                sent = await _send_queued(base, token, now)
            await _poll_status(base, token, now)
        outcome = "sent" if sent else ("queued" if added else ("idle" if offered() else "off"))
        _last.update(at=now, outcome=outcome, sent=sent)
        if added or sent or expired:
            # ⚠️ ASCII: строку читает тест в логе сервера на Windows
            log.warning("sms: tick added=%d sent=%d expired=%d", added, sent, expired)
        return outcome


def _tick_seconds() -> float:
    try:
        s = float(os.environ.get(TICK_ENV, "") or 0)
    except ValueError:
        s = 0
    return s if s > 0 else TICK


async def _loop() -> None:
    global _wake
    _wake = asyncio.Event()
    while True:
        try:
            await tick()
        except Exception as e:  # noqa: BLE001 — фон не имеет права умереть
            log.warning("sms: tick failed: %r", e)
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=_tick_seconds())
        except asyncio.TimeoutError:
            pass


def sms_async() -> None:
    """Из хука старта main.py, после `startup()`: цикл в фоне — тот же приём,
    что `lic.renew_async`: старт не ждёт, таймаут есть, отказ молчит в лог."""
    global _task
    if _task is not None:
        return
    _task = asyncio.get_running_loop().create_task(_loop())


# ---------- команды экрана ----------


async def _command(fn, *args) -> tuple[str, dict]:
    t = target()
    if t is None:
        return wire.OFFLINE, {}
    outcome, body = await asyncio.to_thread(fn, t[0], t[1], *args, wire.TIMEOUT, _agent(),
                                            lic.identity())
    if outcome == wire.OK:
        await refresh_account(force=True)
    return outcome, body


async def request_sender(name: str) -> tuple[str, dict]:
    return await _command(wire.sender, name)


async def order(pack: int = 0, name: bool = False) -> tuple[str, dict]:
    return await _command(wire.order, pack, name)


async def send_test(phone: str) -> tuple[str, dict]:
    """Тестовая SMS на номер директора — мимо очереди, из пакета клиники."""
    number, why = rule.phone(phone)
    if why:
        return wire.DENIED, {"code": "sms_phone", "reason": why}
    now = datetime.now(eng.TZ)
    text = plan.text("ro", plan.STANDARD, clinic=eng.CLINIC_NAME, phone=eng.CLINIC_PHONE,
                     phone_line=False, starts=now, on_day=now.date())
    return await _command(wire.send, number, text, "test", f"test:{now.strftime('%Y%m%dT%H%M%S')}")


def _previews(s: dict) -> dict:
    """Предпросмотры: событие → вариант → язык → {text, segments} с названием
    и телефоном клиники; накануне — «maine», в день визита — «astazi»."""
    now = datetime.now(eng.TZ)
    custom = custom_texts()
    variants = list(plan.VARIANTS) + ([plan.CUSTOM] if custom else [])
    out = {}
    for ev in plan.EVENTS:
        starts = (now + timedelta(days=1 if ev == plan.DAY_BEFORE else 0)).replace(hour=12, minute=0)
        out[ev] = {}
        for v in variants:
            out[ev][v] = {}
            for lang in plan.LANGS:
                if v == plan.CUSTOM and lang not in custom:
                    continue
                text = plan.text(lang, v, clinic=eng.CLINIC_NAME, phone=eng.CLINIC_PHONE,
                                 phone_line=s[plan.PHONE_LINE_KEY], starts=starts, on_day=now.date(),
                                 custom=custom)
                out[ev][v][lang] = {"text": text, "segments": rule.parts(text)[2]}
    return out


def _low_view() -> dict | None:
    """`low()` для экрана и проверок: без ключа эпизода — он нужен только часам."""
    lo = low()
    return {k: lo[k] for k in ("left", "limit", "trial", "title", "text")} if lo else None


def screen() -> dict:
    """Данные экрана Setări › SMS (modules/settings/api.py добавляет `can_order`)."""
    s = settings()
    acc = account()
    fc = forecast()
    custom = custom_texts()
    blocked = (acc or {}).get("blocked") or ""
    why = WHY.get(blocked, blocked) if blocked else (WHY.get(_last["error"], _last["error"])
                                                     if _last["error"] in ("offline", "refused") else "")
    daily = fc["daily"]
    return {
        "available": available(), "offered": offered(), "enabled": enabled(), "active": active(),
        "why": "" if not available() else why,
        # код сервера — экран различает «выключено по желанию клиники» и прочие отказы
        "blocked": blocked if available() else "",
        "account": ({k: acc.get(k) for k in ("balance", "from", "sender", "sender_state", "sender_note",
                                            "sender_until", "packs", "name_price", "name_days", "daily_cap",
                                            "used_today")} if acc and offered() else None),
        "settings": s,
        "options": {"hours": list(plan.HOURS_X), "leads": list(plan.LEAD_HOURS),
                    "variants": [{"key": v, "label": plan.VARIANT_LABEL[v]} for v in plan.VARIANTS]
                    + ([{"key": plan.CUSTOM, "label": plan.VARIANT_LABEL[plan.CUSTOM]}] if custom else [])},
        "previews": _previews(s) if available() else {},
        "forecast": {**fc, "days_left": (int(int((acc or {}).get("balance") or 0) // daily)
                                         if acc and daily > 0 else None)},
        # «мало SMS» — то же состояние, что у пункта меню и у часов (`low`)
        "low": _low_view(), "counts": _counts, "last": status()["last"],
        "clinic": {"name": eng.CLINIC_NAME, "phone": eng.CLINIC_PHONE},
    }


def status() -> dict:
    """Состояние для экрана Setări › SMS и проверок (без номеров и текстов)."""
    return {"available": available(), "offered": offered(), "enabled": enabled(),
            "active": active(), "account": account(), "settings": settings(),
            "forecast": forecast(), "low": _low_view(), "last": {
                "at": _last["at"].strftime("%Y-%m-%dT%H:%M:%SZ") if _last["at"] else None,
                "outcome": _last["outcome"], "error": _last["error"],
                "error_text": WHY.get(_last["error"], _last["error"])}}
