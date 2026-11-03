"""Пародонтограмма: осмотры и точки."""
from __future__ import annotations

from .. import db
from .conn import _execute, _fetch, _fetchval, _utcnow_iso
from .events import log_event
from .slots import _slot_lock


# ---------- пародонтограмма (perio) ----------

async def perio_exams(pid: int) -> list:
    """Осмотры пациента, свежие сверху, с числом измеренных зубов.
    ⚠️ `teeth` — СЧЁТЧИК, а не строка зубов: имя короткое, потому что колонка
    так и называется на экране («28 dinți»)."""
    return await _fetch(
        """SELECT e.id, e.doctor, e.note, e.created_at,
                  COUNT(t.tooth) AS teeth
           FROM perio_exams e LEFT JOIN perio_teeth t ON t.exam_id = e.id
           WHERE e.patient_id = ?
           GROUP BY e.id, e.doctor, e.note, e.created_at
           ORDER BY e.created_at DESC, e.id DESC""", pid)


async def perio_exam(pid: int, eid: int) -> dict | None:
    """Шапка осмотра. ⚠️ Всегда И по пациенту: id осмотра приходит из формы, и
    без второго условия чужой осмотр открывался бы по прямому адресу."""
    rows = await _fetch(
        """SELECT id, patient_id, doctor, note, created_at
           FROM perio_exams WHERE id = ? AND patient_id = ?""", eid, pid)
    return rows[0] if rows else None


async def perio_rows(eid: int) -> list:
    """Измерения одного осмотра, по порядку номеров зуба."""
    return await _fetch(
        """SELECT tooth, pd, rec, bop, mob, furc FROM perio_teeth
           WHERE exam_id = ? ORDER BY tooth""", eid)


async def perio_new(pid: int, doctor: str = "", note: str = "") -> int:
    """Новый (пустой) осмотр. Летопись пишется при СОХРАНЕНИИ измерений, а не
    здесь: пустой осмотр — это ещё не находка, а открытый лист."""
    cur = await db._CONN.execute(
        """INSERT INTO perio_exams(patient_id, doctor, note, created_at)
           VALUES(?, ?, ?, ?)""",
        (pid, doctor, note, _utcnow_iso()))
    await db._CONN.commit()
    new_id = cur.lastrowid
    await cur.close()
    return int(new_id)


async def perio_save(pid: int, eid: int, rows: list, covers: set,
                     doctor: str | None = None,
                     note: str | None = None) -> int:
    """Записать измерения в осмотр. Возвращает число сохранённых зубов.

    ⛔ `covers` — зубы, О КОТОРЫХ это сохранение СООБЩАЕТ: экран прислал их
    измерения или сказал, что измерений у них больше нет. Стирается
    `covers − keep`, и только оно. Зуб вне `covers` не пишется и НЕ СТИРАЕТСЯ:
    про него не сказано ничего, а «не сообщали» никогда не значит «стереть»
    (08-16, две потери данных ровно на этом различии).
    ⭐ Отсюда два рабочих места правят ОДИН осмотр, не отнимая работу друг у
    друга (18.09). Прежнее правило стирало «показанные, но не присланные», а
    показывал лист всегда все 32 зуба: место, загрузившее осмотр раньше,
    сносило чужой зуб целиком и возвращало чужие числа к тем, что видело само
    — ответ 200, в летописи обычная вторая строка.
    ⚠️ Врач и заметка — только если ПРИСЛАНЫ (None ≠ пустая строка): форма
    печати их не шлёт, и None не должен затирать подпись осмотра.
    ⚠️ Сообщать нечего — не делается НИЧЕГО, включая строку летописи: пустое
    сохранение это не находка осмотра, а промах по кнопке.
    """
    from ..modules.patients.perio import ledger_words
    if not rows and not covers and doctor is None and note is None:
        return 0
    keep = {int(r["tooth"]) for r in rows}
    async with _slot_lock():
        for tooth in sorted(covers - keep):
            await _execute(
                "DELETE FROM perio_teeth WHERE exam_id = ? AND tooth = ?",
                eid, int(tooth))
        for r in rows:
            await _execute(
                """INSERT INTO perio_teeth(exam_id, tooth, pd, rec, bop, mob, furc)
                   VALUES(?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(exam_id, tooth) DO UPDATE SET
                     pd = excluded.pd, rec = excluded.rec, bop = excluded.bop,
                     mob = excluded.mob, furc = excluded.furc""",
                eid, int(r["tooth"]), r["pd_packed"], r["rec_packed"],
                r["bop"], int(r["mob"]), int(r["furc"]))
        if doctor is not None or note is not None:
            await _execute(
                """UPDATE perio_exams SET doctor = COALESCE(?, doctor),
                          note = COALESCE(?, note)
                   WHERE id = ? AND patient_id = ?""",
                doctor, note, eid, pid)
    exam = await perio_exam(pid, eid)
    when = exam["created_at"] if exam else None
    await log_event(pid, "perio", ledger_words(await perio_rows(eid), when))
    return len(rows)


async def perio_drop(pid: int, eid: int) -> bool:
    """Снять ПУСТОЙ осмотр (двойной клик по «Examen nou»).
    ⛔ Осмотр с измерениями не удаляется никем: это медицинская запись, её
    правят, а не заставляют исчезнуть — то же правило, что у дневника визита.
    """
    if await _fetchval("SELECT COUNT(*) FROM perio_teeth WHERE exam_id = ?",
                       eid):
        return False
    n = await _execute(
        "DELETE FROM perio_exams WHERE id = ? AND patient_id = ?", eid, pid)
    return n == 1


async def perio_last(pid: int) -> tuple:
    """Последний осмотр С ИЗМЕРЕНИЯМИ и его строки — для 043/e и выгрузки-195.
    ⚠️ Именно с измерениями: пустой лист, открытый и не заполненный, не должен
    подменять собой прошлую настоящую карту на подписываемой бумаге."""
    for e in await perio_exams(pid):
        if e["teeth"]:
            return e, await perio_rows(e["id"])
    return None, []
