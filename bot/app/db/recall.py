"""Rechemări: выборки списка отзыва и журнал отметок."""
from __future__ import annotations

from datetime import datetime, timezone

from .conn import _execute, _fetch, _iso
from .events import _actor_now
from .slots import _ACT_SQL


# ---------- «Rechemări» (29.10): выборки для core/recall ----------
#
# Правило списка живёт в `core/recall.py` чистой функцией; здесь только
# выборки, каждая — одним запросом на всю картотеку (раздел едет в конверте
# живого канала главной, опрос постоянный).

async def recall_done_last(service_ids: list, patient_id: int | None = None) -> list:
    """Последний ЗАВЕРШЁННЫЙ визит каждой пары (пациент, услуга) по услугам со
    сроком: `aid` — его id (цикл отметок), `last_at` — его начало (псевдоним
    в _DT_COLS: иначе SQLite отдал бы строку). Только `done`: неявка, отмена и
    «programată» часы отзыва не заводят. Архивные (и обезличенные — у них
    archived=1) не участвуют.
    ⚠️ Голые колонки при MAX() SQLite берёт из строки максимума — это
    документированное поведение, на нём и держится `aid`/`doctor`."""
    if not service_ids:
        return []
    lite = ",".join("?" for _ in service_ids)
    one = " AND a.patient_id = ?" if patient_id is not None else ""
    args = [*service_ids] + ([patient_id] if patient_id is not None else [])
    return await _fetch(
        f"""SELECT a.patient_id, a.service_id, a.id AS aid, a.doctor,
                   MAX(a.starts_at) AS last_at,
                   p.name, p.phone, p.email, COALESCE(p.lang, 'ro') AS lang,
                   COALESCE(p.sms_off, 0) AS sms_off
              FROM appointments a JOIN patients p ON p.id = a.patient_id
             WHERE a.status = 'done' AND a.service_id IN ({lite})
               AND COALESCE(p.archived, 0) = 0{one}
             GROUP BY a.patient_id, a.service_id""", *args)


async def recall_future(day_start: datetime) -> list:
    """Ближайшая будущая ЖИВАЯ запись каждой пары (пациент, услуга) от начала
    дня: записанный вперёд на ту же услугу из списка уходит, на другую —
    получает пометку. Граница — начало дня, не «сейчас» (конверт живого канала
    обязан быть одинаковым весь день)."""
    return await _fetch(
        f"""SELECT patient_id, service_id, service, MIN(starts_at) AS next_at
              FROM appointments
             WHERE patient_id IS NOT NULL AND status IN {_ACT_SQL} AND starts_at >= ?
             GROUP BY patient_id, service_id""", _iso(day_start))


async def recall_marks(patient_id: int | None = None) -> list:
    """Все отметки обзвона по порядку записи (одного пациента или всей
    картотеки): действующую выбирает `core/recall` по последней строке и
    циклу, здесь ничего не интерпретируется."""
    if patient_id is None:
        return await _fetch("SELECT * FROM recall_marks ORDER BY id")
    return await _fetch("SELECT * FROM recall_marks WHERE patient_id = ? ORDER BY id",
                        patient_id)


async def recall_contacts_since(since_iso: str) -> list:
    """Отметки «sunat — revine»/«e-mail trimis»/«SMS trimis» (30.10, В7 = А) с
    момента `since_iso` (UTC ISO): пара (пациент, услуга) и её ПЕРВАЯ такая
    отметка в окне — для статистики «contactați · programați» (журнал
    читается, не интерпретируется)."""
    return await _fetch(
        """SELECT patient_id, service_id, MIN(at) AS at
             FROM recall_marks WHERE result IN ('contacted', 'emailed', 'sms') AND at >= ?
            GROUP BY patient_id, service_id""", since_iso)


async def recall_bookings_since(since_iso: str) -> list:
    """Записи (живые или завершённые), СОЗДАННЫЕ с `since_iso`, по парам
    (пациент, услуга) с ПОСЛЕДНЕЙ датой создания: «после отметки создана
    запись» ⇔ последняя созданная позже отметки (первая была бы визитом,
    который сам список и завёл). Сравнивает core/recall, не SQL."""
    return await _fetch(
        f"""SELECT patient_id, service_id, MAX(created_at) AS created_at
              FROM appointments
             WHERE patient_id IS NOT NULL AND created_at >= ?
               AND status IN ('confirmed', 'waiting', 'arrived', 'done')
             GROUP BY patient_id, service_id""", since_iso)


async def add_recall_mark(patient_id: int, service_id: str, cycle: int | None,
                          result: str, until: str = "", actor: str | None = None) -> None:
    """Дописать отметку (журнал, не состояние). Автор — вошедший
    (ACTOR_HOOK), как у отметки звонка, или названный (`sistem` у
    автоматической SMS); время — UTC программы."""
    await _execute(
        """INSERT INTO recall_marks(patient_id, service_id, cycle_appt_id, result,
                                    until_date, actor, at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        patient_id, service_id, cycle, result, until or None, actor or _actor_now(),
        _iso(datetime.now(timezone.utc)))


async def recall_auto_sent(since_iso: str, actor: str) -> int:
    """Сколько SMS отправил ЦИКЛ сам с момента `since_iso` (начало дня
    клиники, UTC ISO) — отметки `sms` с его подписью; ручные (подпись
    вошедшего) в дневной лимит не входят."""
    rows = await _fetch("SELECT COUNT(*) AS n FROM recall_marks WHERE result = 'sms' AND actor = ? AND at >= ?",
                        actor, since_iso)
    return int(rows[0]["n"]) if rows else 0
