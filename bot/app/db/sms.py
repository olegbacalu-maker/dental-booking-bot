"""SMS-пакет: очередь напоминаний `sms_log` и выключатель SMS пациента."""
from __future__ import annotations

from datetime import datetime

from .conn import _execute, _fetch, _fetchval, _iso, _utcnow_iso
from .patients import _patient_ids_by_digits, manual_key, patient_id_by_key


# ---------- SMS-пакет (S5): очередь напоминаний ----------
#
# Состояние напоминания живёт ЗДЕСЬ (`sms_log`), а не во флагах визита:
# `reminded_day`/`reminded_2h` — флаги напоминаний Telegram-бота (удалён
# 03.11.2026; у старых визитов флаг остаётся и читается колокольчиком) — SMS
# их не читает и не пишет. Решения
# «кому и когда» принимает core/sms_loop.py; здесь только выборки и записи.

SMS_QUEUED, SMS_SENT, SMS_DELIVERED = "queued", "sent", "delivered"
SMS_UNDELIVERED, SMS_FAILED, SMS_EXPIRED = "undelivered", "failed", "expired"
SMS_STATES = (SMS_QUEUED, SMS_SENT, SMS_DELIVERED, SMS_UNDELIVERED, SMS_FAILED, SMS_EXPIRED)
# «напомнили» для колокольчика журнала: SMS принята сервером или доставлена.
# Недоставленная (телефон выключен сутки) колокольчик не зажигает: пациент её
# не видел, и стойке лучше позвонить.
_SMS_REMINDED_SQL = "('sent','delivered')"


async def sms_candidates(now: datetime, horizon: datetime) -> list:
    """Визиты, которым может понадобиться SMS: programată (`confirmed` — до
    звонка и после, вид решает `status_view`), с пациентом, у которого есть
    телефон, не архивным и без «Fără remindere SMS», начало в окне. Годность
    номера (мобильный Молдовы) решает правило sms_rule у вызывающего."""
    return await _fetch(
        """SELECT a.id, a.starts_at, a.created_at, a.patient_id,
                  p.phone, p.lang, p.session_key
           FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status = 'confirmed' AND a.source <> 'note'
             AND a.starts_at > ? AND a.starts_at < ?
             AND p.phone IS NOT NULL AND p.phone <> ''
             AND COALESCE(p.archived, 0) = 0 AND COALESCE(p.sms_off, 0) = 0
           ORDER BY a.starts_at, a.id""",
        _iso(now), _iso(horizon))


async def sms_known_idems(now: datetime, horizon: datetime) -> set:
    """Ключи повтора, по которым строка уже есть, — для визитов окна."""
    rows = await _fetch(
        """SELECT s.idem FROM sms_log s JOIN appointments a ON a.id = s.appt_id
           WHERE a.starts_at > ? AND a.starts_at < ?""", _iso(now), _iso(horizon))
    return {r["idem"] for r in rows}


async def sms_enqueue(appt_id: int, patient_id: int, kind: str, phone: str, text: str,
                      segments: int, idem: str, until_at: datetime) -> bool:
    """Поставить напоминание в очередь. Повтор ключа — молча нет: вторая копия
    программы или второй проход цикла строку не удваивают."""
    n = await _execute(
        """INSERT OR IGNORE INTO sms_log(appt_id, patient_id, kind, phone, text, segments,
                                       idem, state, until_at, created_at, state_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        appt_id, patient_id, kind, phone, text, segments, idem, SMS_QUEUED,
        _iso(until_at), _utcnow_iso(), _utcnow_iso())
    return n > 0


async def sms_queue(limit: int = 50) -> list:
    """Очередь на отправку — с визитом и пациентом, какими они стали к моменту
    отправки: отменённый визит, перенос (другое начало — другой ключ) и
    поставленная после постановки галочка отказа видны здесь, а не в момент
    постановки."""
    return await _fetch(
        """SELECT s.*, a.status AS appt_status, a.starts_at AS visit_at,
                  COALESCE(p.sms_off, 0) AS sms_off, COALESCE(p.archived, 0) AS archived
           FROM sms_log s JOIN appointments a ON a.id = s.appt_id
                JOIN patients p ON p.id = s.patient_id
           WHERE s.state = ? ORDER BY s.created_at, s.id LIMIT ?""",
        SMS_QUEUED, limit)


async def sms_set(sms_id: int, **cols) -> None:
    """Обновить строку: состояние, id сервера, ошибка. `state_at` — при смене
    состояния; остальное как передано."""
    if "state" in cols:
        cols.setdefault("state_at", _utcnow_iso())
    sets = ", ".join(f"{k} = ?" for k in cols)
    await _execute(f"UPDATE sms_log SET {sets} WHERE id = ?", *cols.values(), sms_id)


async def sms_delete(sms_id: int) -> None:
    """Снять строку, которая ещё не уходила: отменённый визит, выключенное
    событие, отказ пациента после постановки. Летописи у неё не было."""
    await _execute("DELETE FROM sms_log WHERE id = ? AND state = ?", sms_id, SMS_QUEUED)


async def sms_drop_kind(kind: str) -> int:
    """Событие выключили в настройках — его очередь снимается целиком."""
    return await _execute("DELETE FROM sms_log WHERE kind = ? AND state = ?", kind, SMS_QUEUED)


async def sms_overdue(now: datetime) -> list:
    """Строки, чьё окно отправки прошло, а SMS так и не ушла: сервер молчал,
    пакет кончился, программа была выключена. Вызывающий переводит их в
    `expired` и пишет летопись с причиной."""
    return await _fetch(
        """SELECT s.*, a.starts_at AS visit_at FROM sms_log s
           LEFT JOIN appointments a ON a.id = s.appt_id
           WHERE s.state = ? AND s.until_at <= ? ORDER BY s.id""",
        SMS_QUEUED, _iso(now))


async def sms_pending(since: datetime) -> list:
    """Принятые сервером, но без конечного состояния — кого опрашивать."""
    return await _fetch(
        """SELECT s.*, a.starts_at AS visit_at FROM sms_log s
           LEFT JOIN appointments a ON a.id = s.appt_id
           WHERE s.state = ? AND s.cloud_id IS NOT NULL AND s.created_at >= ?
           ORDER BY s.id""", SMS_SENT, _iso(since))


async def sms_rows(appt_id: int) -> list:
    """Строки SMS одного визита — карточке визита и проверкам."""
    return await _fetch(
        "SELECT * FROM sms_log WHERE appt_id = ? ORDER BY id", appt_id)


async def sms_by_idem(idem: str) -> dict | None:
    """Строка по ключу повтора — есть ли уже такая SMS (любое состояние)."""
    rows = await _fetch("SELECT * FROM sms_log WHERE idem = ?", idem)
    return rows[0] if rows else None


async def sms_log_sent(patient_id: int, kind: str, phone: str, text: str, segments: int,
                       idem: str, cloud_id: int | None) -> int | None:
    """Уже ОТПРАВЛЕННАЯ мимо очереди SMS («Rechemări», 30.10): строка сразу
    `sent`, без визита (`appt_id NULL` — колокольчик `_SMS_REMINDED_SQL`
    смотрит по визиту и её не видит), окно = момент отправки. Повтор ключа —
    None: первая запись выиграла. Доставку опрашивает штатный цикл."""
    now = _utcnow_iso()
    n = await _execute(
        """INSERT OR IGNORE INTO sms_log(appt_id, patient_id, kind, phone, text, segments,
                                       idem, cloud_id, state, until_at, created_at, state_at)
           VALUES(NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        patient_id, kind, phone, text, segments, idem, cloud_id, SMS_SENT, now, now, now)
    if n <= 0:
        return None
    rows = await _fetch("SELECT id FROM sms_log WHERE idem = ?", idem)
    return int(rows[0]["id"]) if rows else None


async def sms_states_by_kind(kind: str, patient_id: int | None = None) -> list:
    """Ключ, состояние и момент состояния всех SMS вида — `core/recall` сводит
    их со строками списка по ключу (одна выборка на картотеку)."""
    if patient_id is None:
        return await _fetch("SELECT idem, state, state_at FROM sms_log WHERE kind = ?", kind)
    return await _fetch("SELECT idem, state, state_at FROM sms_log WHERE kind = ? AND patient_id = ?",
                        kind, patient_id)


async def sms_counts(day_start: datetime) -> dict:
    """Цифры экрана Setări › SMS: в очереди; ушло и доставлено с начала дня."""
    row = await _fetch(
        """SELECT SUM(state = 'queued') AS queued,
                  SUM(state IN ('sent','delivered','undelivered') AND created_at >= ?) AS today,
                  SUM(state = 'delivered' AND created_at >= ?) AS delivered,
                  SUM(state IN ('failed','expired') AND created_at >= ?) AS failed
           FROM sms_log""", _iso(day_start), _iso(day_start), _iso(day_start))
    r = row[0] if row else {}
    return {k: int(r.get(k) or 0) for k in ("queued", "today", "delivered", "failed")}


async def sms_visits_month(start: datetime, end: datetime) -> int:
    """Сколько визитов с телефоном пациента было в окне — основа прогноза
    расхода в месяц: каждое включённое событие — по SMS на визит."""
    v = await _fetchval(
        """SELECT COUNT(*) FROM appointments a JOIN patients p ON p.id = a.patient_id
           WHERE a.status <> 'cancelled' AND a.source <> 'note'
             AND a.starts_at >= ? AND a.starts_at < ?
             AND p.phone IS NOT NULL AND p.phone <> ''
             AND COALESCE(p.archived, 0) = 0 AND COALESCE(p.sms_off, 0) = 0""",
        _iso(start), _iso(end))
    return int(v or 0)


# Строка летописи об отказе пациента от SMS — ОДНА на оба места, где его
# отмечают: фишу («Fără remindere SMS») и галочку окна записи («SMS reminder»).
SMS_OFF_EVENT = {True: "Remindere SMS oprite — la cererea pacientului",
                 False: "Remindere SMS pornite din nou"}


async def set_sms_off(pid: int, on: bool) -> bool:
    """«Fără remindere SMS» в фише. Летопись — вызывающий маршрут (он знает,
    кто поставил). Ответ — изменилось ли значение: окно записи пишет строку
    летописи только на перемене, а не на каждой записи."""
    return await _execute(
        "UPDATE patients SET sms_off = ? WHERE id = ? AND COALESCE(sms_off, 0) <> ?",
        int(bool(on)), pid, int(bool(on))) > 0


async def manual_patient_sms_off(phone: str) -> bool | None:
    """`sms_off` пациента, в чью карточку ЛЯЖЕТ ручная запись с этим номером;
    None — карточки ещё нет (запись заведёт новую).

    ⚠️ Правило выбора — то же, что у `admin_add`: ровно одно совпадение по
    цифрам — он; иначе склейка по ключу `manual:<цифры>`. Галочка окна
    показывает ЭТОГО пациента: ребёнок на номере родителя — значит родителя,
    туда же уйдёт и визит. Пишет галочку не этот ответ, а сама запись по id
    созданного визита (`appt_patient_id`), так что разойтись здесь может
    только показ."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    ids = await _patient_ids_by_digits(digits)
    pid = ids[0] if len(ids) == 1 else await patient_id_by_key(manual_key(digits))
    if pid is None:
        return None
    return bool(await _fetchval(
        "SELECT COALESCE(sms_off, 0) FROM patients WHERE id = ?", pid))
