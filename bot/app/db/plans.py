"""План лечения: позиции и их статусы."""
from __future__ import annotations

from .conn import _execute, _fetch, _fetchval, _utcnow_iso
from .events import log_event


# ---------- рабочие списки регистратуры на главной (01.10, schedule/desk) ----------

async def plan_open_summary() -> list:
    """Активный план по пациенту: сколько позиций, на какую сумму и с какого
    дня висит — список «Plan fără programare». ⚠️ Псевдоним даты —
    `created_at` (он в `_DT_COLS`): иначе в SQLite MIN() остался бы строкой
    (прайор 08-06). Активное — перечислением, как везде."""
    sql = ("SELECT patient_id, COUNT(*) AS n, COALESCE(SUM(price_mdl), 0) AS total, "
           "MIN(created_at) AS created_at FROM plan_items "
           "WHERE status IN ('planificat', 'in_lucru') GROUP BY patient_id")
    return await _fetch(sql)


# ⭐ «Активная» позиция плана — это planificat|in_lucru, а НЕ «всё, что не
# finalizat». Пока статусов было три, две формулировки совпадали; с появлением
# ОТКАЗА (refuzat, ст.13(5) Legea 263/2005) вторая стала враньём: отказанная
# процедура навсегда осталась бы «в лечении» — в KPI фиши, в колонке списка и
# в сумме активного плана. Считать активность только через этот кортеж.
PLAN_ACTIVE = ("planificat", "in_lucru")
# закрытые: у них проставлен done_at и они не ждут работы
PLAN_CLOSED = ("finalizat", "refuzat")


async def plan_items(pid: int) -> list:
    # created_at — когда позиция появилась в плане: по нему статус «acord
    # informat» говорит «план изменён после подписи» (01.10)
    # visit_doctor — врач визита, на котором позицию выполнили (22.10): кто
    # ЗАПЛАНИРОВАН, лежит в `doctor` и не переписывается — «Redeschide»
    # обязан вернуть его. Кого печатать — fisa043.plan_doctor. Подзапрос, а
    # не JOIN: doctor/status/id/created_at есть в обеих таблицах.
    return await _fetch(
        """SELECT id, tooth, procedure, doctor, status, price_mdl, due_date,
                  done_at, appointment_id, refuz_motiv, created_at,
                  (SELECT a.doctor FROM appointments a
                    WHERE a.id = plan_items.appointment_id) AS visit_doctor
           FROM plan_items WHERE patient_id = ? ORDER BY id""", pid)


async def last_events(pid: int, kinds: tuple) -> dict:
    """Когда в последний раз случалось событие каждого вида — статусы бланков
    фиши («tipărit DD.MM»). Лента фиши для этого не годится: она режется
    шестьюдесятью строками, и печать месячной давности из неё выпадает.
    ⚠️ Псевдоним `at` — в `_DT_COLS`: иначе в SQLite MAX() остался бы строкой."""
    if not kinds:
        return {}
    lite = ",".join("?" for _ in kinds)
    rows = await _fetch(
        f"""SELECT kind, MAX(at) AS at FROM activity
            WHERE patient_id = ? AND kind IN ({lite}) GROUP BY kind""",
        pid, *kinds)
    return {r["kind"]: r["at"] for r in rows}


async def plan_item_status(item_id: int, pid: int) -> str | None:
    """Текущий статус позиции — для проверки, что переход допустим. Стрелки
    статусов НАПРАВЛЕННЫЕ (см. _PLAN_EDGES в модуле пациентов), и охрана
    обязана смотреть на «откуда», а не только на «куда»."""
    return await _fetchval(
        "SELECT status FROM plan_items WHERE id = ? AND patient_id = ?",
        item_id, pid)


async def add_plan_item(pid: int, tooth: int | None, procedure: str,
                        doctor: str, price_mdl: int | None,
                        due_date: str = "") -> None:
    await _execute(
        """INSERT INTO plan_items(patient_id, tooth, procedure, doctor, price_mdl,
                                  due_date, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        pid, tooth, procedure, doctor, price_mdl, due_date or None,
                _utcnow_iso(),
    )
    await log_event(pid, "plan_add",
                    f"Plan: + {procedure}" + (f" (dinte {tooth})" if tooth else ""),
                    tooth=tooth)


async def set_plan_status(item_id: int, pid: int, status: str,
                          appt_id: int | None = None, motiv: str = "") -> None:
    """appt_id — визит, НА котором позицию выполнили (страница консультации).
    Привязка живёт только у финализированной позиции: «Redeschide» означает
    «на самом деле не сделано», и ссылка на визит снимается вместе с done_at.

    ⚠️ `done_at` — дата ЗАКРЫТИЯ позиции, а не «выполнения»: её получает и
    отказ (refuzat). Иначе пришлось бы завести пятую колонку-дату ради того же
    смысла, а лист согласия и 043/e спрашивают у отказа ровно дату и причину.
    Возврат в работу (Redeschide / Reia) чистит и дату, и причину: позиция
    снова ждёт работы, и старая причина отказа врала бы о ней.
    """
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
                        item_id, pid)
    if rows:
        # причина отказа уходит в летопись ВМЕСТЕ с переходом: лента —
        # единственное место, где видно, кто и когда отказ оформил
        tail = f" ({motiv})" if status == "refuzat" and motiv else ""
        # статус позиции — СЛОВОМ (см. log_event): тем же словарём, каким его
        # называют бумажный бланк 043/e и выгрузка по 195-му
        from ..modules.patients.fisa043 import PLAN_RO
        await log_event(pid, "plan_status",
                        f"Plan: {rows[0]['procedure']} › "
                        f"{PLAN_RO.get(status, status)}{tail}",
                        tooth=rows[0]["tooth"])
    if status in PLAN_CLOSED:
        # к визиту привязывается только ВЫПОЛНЕННОЕ: отказ ни на каком приёме
        # не «сделан», и appointment_id у него обязан остаться пустым
        appt = appt_id if status == "finalizat" else None
        why = motiv if status == "refuzat" else ""
        await _execute(
            """UPDATE plan_items SET status = ?, done_at = ?,
                  appointment_id = ?, refuz_motiv = ?
                WHERE id = ? AND patient_id = ?""",
            status, _utcnow_iso(), appt, why, item_id, pid,
        )
    else:
        await _execute(
            """UPDATE plan_items SET status = ?, done_at = NULL,
                  appointment_id = NULL, refuz_motiv = ''
                WHERE id = ? AND patient_id = ?""",
            status, item_id, pid,
        )


async def delete_plan_item(item_id: int, pid: int) -> bool:
    """Летопись — ПОСЛЕ DELETE и только за реально снятую строку (как у
    `delete_bridge`). False — позиции у пациента нет."""
    rows = await _fetch("SELECT procedure, tooth FROM plan_items WHERE id = ? AND patient_id = ?",
                        item_id, pid)
    if not rows:
        return False
    n = await _execute(
        "DELETE FROM plan_items WHERE id = ? AND patient_id = ?", item_id, pid)
    if n != 1:
        return False
    await log_event(pid, "plan_del", f"Plan: - {rows[0]['procedure']}",
                    tooth=rows[0]["tooth"])
    return True
