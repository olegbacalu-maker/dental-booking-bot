"""Календари врачей в Google: что программа туда отправила (`gdoc_sent`) и что должна отправить.

Правила сверки — `modules/doctors/gcal_sync.py`. Строка `gdoc_sent` живёт дольше записи: стирание
пациента удаляет запись, а событие у Google убирает следующая сверка по этой строке. `stamp = ''` —
событие у Google удалено, строка помнит поколение: тот же id Google второй раз не примет."""
from __future__ import annotations

from datetime import datetime

from .conn import _execute, _fetch, _iso, _utcnow_iso
from .slots import ACTIVE_STATUSES

# Что врач видит в своём календаре: живые записи и проведённые; отмена и неявка — нет.
GDOC_STATUSES = (*ACTIVE_STATUSES, "done")


async def gdoc_desired(dk: str, name: str | None, since: datetime, until: datetime) -> list[dict]:
    """Записи врача в окне, по правилу `visits.of_doctor`: по `doctor_id`, у легаси-строки без него —
    по снимку имени. Заметки стойки не уходят."""
    marks = ",".join("?" * len(GDOC_STATUSES))
    return await _fetch(
        f"""SELECT a.id, a.starts_at, a.duration_min, a.room, a.service,
                   COALESCE(p.name, '') AS patient, COALESCE(p.file_no, '') AS file_no
              FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
             WHERE (a.doctor_id = ? OR (COALESCE(a.doctor_id, '') = '' AND a.doctor = ?))
               AND a.status IN ({marks}) AND a.source != 'note'
               AND a.starts_at >= ? AND a.starts_at < ?
             ORDER BY a.starts_at, a.id""",
        dk, name, *GDOC_STATUSES, _iso(since), _iso(until))


async def gdoc_sent_rows(dk: str) -> list[dict]:
    """Всё отправленное врачу, не окно: стёртая или ушедшая из окна запись находится только так."""
    return await _fetch(
        "SELECT appt_id, event_id, epoch, gen, stamp, cal_id, starts_at FROM gdoc_sent WHERE doctor_id = ?", dk)


async def gdoc_sent_put(dk: str, appt_id: int, event_id: str, epoch: int, gen: int, stamp: str, cal_id: str,
                        starts_at: datetime) -> None:
    await _execute(
        """INSERT INTO gdoc_sent(doctor_id, appt_id, event_id, epoch, gen, stamp, cal_id, starts_at, sent_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(doctor_id, appt_id) DO UPDATE SET event_id = excluded.event_id,
               epoch = excluded.epoch, gen = excluded.gen, stamp = excluded.stamp, cal_id = excluded.cal_id,
               starts_at = excluded.starts_at, sent_at = excluded.sent_at""",
        dk, appt_id, event_id, epoch, gen, stamp, cal_id, _iso(starts_at), _utcnow_iso())


async def gdoc_sent_off(dk: str, appt_id: int) -> None:
    """Событие удалено у Google: следующая вставка — новым поколением."""
    await _execute(
        "UPDATE gdoc_sent SET stamp = '', gen = gen + 1, sent_at = ? WHERE doctor_id = ? AND appt_id = ?",
        _utcnow_iso(), dk, appt_id)


async def gdoc_sent_stale(dk: str, epoch: int, cal_id: str) -> int:
    """Строки прежнего календаря врача: у Google их не трогать, а забыть. Календарь — и по id, не только
    по эпохе: после «Deconectează» новая связь снова начинает с первой эпохи."""
    return await _execute("DELETE FROM gdoc_sent WHERE doctor_id = ? AND (epoch != ? OR cal_id != ?)",
                          dk, epoch, cal_id)


async def gdoc_sent_prune(dk: str, before: datetime) -> int:
    """Удалённые у Google события старше окна: их поколение больше не понадобится."""
    return await _execute(
        "DELETE FROM gdoc_sent WHERE doctor_id = ? AND stamp = '' AND starts_at < ?", dk, _iso(before))


async def gdoc_sent_forget(dk: str) -> int:
    """Календаря больше нет или он пересобран: отправленного врачу нет."""
    return await _execute("DELETE FROM gdoc_sent WHERE doctor_id = ?", dk)
