"""Вкладка «Google Calendar»: выборки и запись; правила — `modules/schedule/gcal.py`.

Строку события не удалять, а обнулять: ключ нужен повторной загрузке."""
from __future__ import annotations

import re

from .. import db
from .conn import _execute, _fetch, _fetchval, _utcnow_iso
from .pimport import _APPT_CHILDREN, _APPT_SIG
from .slots import _ACT_SQL

GCAL_NEW, GCAL_MOVED, GCAL_SKIPPED, GCAL_UNPARSED = "nou", "mutat", "omis", "nerecunoscut"
# Событие стёртого пациента: строка без текста держит ключ, чтобы файл не вернул человека.
GCAL_ERASED = "sters"
GCAL_STATES = (GCAL_NEW, GCAL_MOVED, GCAL_SKIPPED, GCAL_UNPARSED, GCAL_ERASED)

_GCAL_COLS = ("source_id", "ext_key", "starts_at", "minutes", "title", "body", "series",
              "gstatus", "state", "why", "by_hand", "stamp", "stamp_moved", "seen_at",
              "created_at", "auto_why", "ack")

# `shell_model` не корутина: ответ для меню лежит здесь, обновляет его каждая запись модуля.
_GCAL_MENU = {"on": False, "todo": 0}


def gcal_menu() -> dict:
    return dict(_GCAL_MENU)


async def gcal_menu_refresh() -> None:
    on = await _fetchval("SELECT COUNT(*) FROM gcal_sources WHERE loaded_at IS NOT NULL")
    todo = await _fetchval(
        "SELECT COUNT(*) FROM gcal_events WHERE state = ? AND starts_at > ?",
        GCAL_NEW, _utcnow_iso())
    _GCAL_MENU["on"] = bool(on)
    _GCAL_MENU["todo"] = int(todo or 0)


async def gcal_sources() -> list:
    return await _fetch(
        "SELECT * FROM gcal_sources WHERE loaded_at IS NOT NULL ORDER BY loaded_at DESC, id DESC")


async def gcal_source_put(kind: str, name: str, actor: str, ext_id: str = "") -> int:
    """Источник файла узнаётся по имени календаря, источник аккаунта — по id календаря Google:
    календарь в Google переименовывают, а id у него один."""
    now = _utcnow_iso()
    if ext_id:
        sid = await _fetchval(
            "SELECT id FROM gcal_sources WHERE kind = ? AND ext_id = ? ORDER BY id LIMIT 1", kind, ext_id)
    else:
        sid = await _fetchval(
            "SELECT id FROM gcal_sources WHERE kind = ? AND name = ? ORDER BY id LIMIT 1", kind, name)
    if sid is None:
        cur = await db._CONN.execute(
            """INSERT INTO gcal_sources(kind, name, ext_id, loaded_at, loaded_by, created_at)
               VALUES(?, ?, ?, ?, ?, ?)""", (kind, name, ext_id, now, actor, now))
        await db._CONN.commit()
        sid = cur.lastrowid
        await cur.close()
    else:
        await _execute("UPDATE gcal_sources SET name = ?, loaded_at = ?, loaded_by = ? WHERE id = ?",
                       name, now, actor, sid)
    await gcal_menu_refresh()
    return int(sid)


async def gcal_source_settings(sid: int, settings: str) -> None:
    await _execute("UPDATE gcal_sources SET settings = ? WHERE id = ?", settings, sid)


async def gcal_sources_prune(keep: int = 0) -> None:
    """Источник без событий остаётся после переименования календаря. `keep` — источник, который
    только что загружен: пустой календарь Google тоже источник, иначе вкладка теряла бы его настройки."""
    await _execute(
        "DELETE FROM gcal_sources WHERE id != ? AND id NOT IN (SELECT DISTINCT source_id FROM gcal_events)",
        keep)
    await gcal_menu_refresh()


async def gcal_source_merge(old: int, new: int) -> None:
    await _execute("UPDATE gcal_events SET source_id = ? WHERE source_id = ?", new, old)
    await _execute("DELETE FROM gcal_sources WHERE id = ?", old)


async def gcal_events_by_keys(keys: list) -> dict:
    """{ключ: строка}; кусками — у SQLite потолок числа параметров."""
    out: dict = {}
    for i in range(0, len(keys), 400):
        part = keys[i:i + 400]
        marks = ",".join("?" for _ in part)
        for r in await _fetch(f"SELECT * FROM gcal_events WHERE ext_key IN ({marks})", *part):
            out[r["ext_key"]] = r
    return out


async def gcal_source_future(sid: int) -> list:
    """Будущие строки источника — среди них ищутся пропавшие из календаря."""
    return await _fetch(
        "SELECT * FROM gcal_events WHERE source_id = ? AND starts_at > ? AND state != ?",
        sid, _utcnow_iso(), GCAL_ERASED)


async def gcal_write(inserts: list, updates: list, deletes: list) -> None:
    """Итог загрузки одной транзакцией; имена колонок идут в SQL текстом — только из `_GCAL_COLS`."""
    conn = db._CONN
    try:
        for row in inserts:
            cols = [c for c in _GCAL_COLS if c in row]
            await conn.execute(
                f"INSERT INTO gcal_events({', '.join(cols)}) "
                f"VALUES({', '.join('?' for _ in cols)})", [row[c] for c in cols])
        for rid, row in updates:
            cols = [c for c in _GCAL_COLS if c in row]
            if cols:
                await conn.execute(
                    f"UPDATE gcal_events SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                    [row[c] for c in cols] + [rid])
        for rid in deletes:
            await conn.execute("DELETE FROM gcal_events WHERE id = ?", (rid,))
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    await gcal_menu_refresh()


async def gcal_rows() -> list:
    """Строки вкладки: будущие события и не разобранные без даты, пока у них есть текст."""
    return await _fetch(
        """SELECT e.*, a.starts_at AS appt_when, a.doctor AS appt_doctor,
                  a.doctor_id AS appt_doctor_id, a.status AS appt_status,
                  a.duration_min AS appt_minutes, a.patient_id AS appt_pid,
                  p.name AS appt_patient
           FROM gcal_events e LEFT JOIN appointments a ON a.id = e.appt_id
                LEFT JOIN patients p ON p.id = a.patient_id
           WHERE e.state != ?
             AND (e.starts_at > ? OR (e.starts_at IS NULL AND e.title != ''))
           ORDER BY e.starts_at IS NULL, e.starts_at, e.id""",
        GCAL_ERASED, _utcnow_iso())


async def gcal_event(eid: int) -> dict | None:
    rows = await _fetch("SELECT * FROM gcal_events WHERE id = ?", eid)
    return rows[0] if rows else None


async def gcal_set_state(eid: int, state: str, was: tuple) -> bool:
    """Решение человека о строке; прежнее состояние — условием в UPDATE: второй щелчок меняет ноль строк."""
    marks = ",".join("?" for _ in was)
    n = await _execute(
        f"UPDATE gcal_events SET state = ?, by_hand = 1 WHERE id = ? AND state IN ({marks})",
        state, eid, *was)
    await gcal_menu_refresh()
    return n > 0


async def gcal_mark_moved(eid: int, appt_id: int, actor: str, *, how: str = "", key: str = "",
                          new_pid: int | None = None, sms_skip: bool | None = None) -> bool:
    """Событие связано с записью, его текст стёрт; уже перенесённое не перевязывается.
    `sms_skip` — метка «без SMS» у записи пачки и автопереноса; отпечаток записи для отмены
    снимается здесь же, после комментария, который ей поставил перенос."""
    if sms_skip is not None:
        await _execute("UPDATE appointments SET sms_skip = ? WHERE id = ?", int(sms_skip), appt_id)
    n = await _execute(
        f"""UPDATE gcal_events SET state = ?, appt_id = ?, title = '', body = '',
                  stamp_moved = stamp, gstatus = '', ack = '', auto_why = '', moved_at = ?,
                  moved_by = ?, moved_how = ?, move_key = ?, move_pid = ?,
                  appt_sig = COALESCE((SELECT {_APPT_SIG} FROM appointments WHERE id = ?), '')
           WHERE id = ? AND state NOT IN (?, ?)""",
        GCAL_MOVED, appt_id, _utcnow_iso(), actor, how, key, new_pid, appt_id, eid,
        GCAL_MOVED, GCAL_ERASED)
    await gcal_menu_refresh()
    return n > 0


async def gcal_unmove(eid: int, appt_id: int) -> bool:
    """Отмена переноса пачкой или автоматом: запись снимается, только если её никто не трогал
    (отпечаток тот же) и на ней ничего не висит, — тогда событие возвращается в «De mutat» решением
    человека, и автоперенос его больше не берёт. Своё событие ребёнком записи не считается.
    Одним скриптом: общее соединение не даст чужому запросу вклиниться между сверкой и удалением.
    Ответ — снята ли запись."""
    eid, aid = int(eid), int(appt_id)
    free = " AND ".join(f"NOT EXISTS (SELECT 1 FROM {t} WHERE {c} = {aid})"
                        for t, c in _APPT_CHILDREN if t != "gcal_events")
    script = f"""BEGIN IMMEDIATE;
UPDATE gcal_events SET state = '{GCAL_NEW}', by_hand = 1, appt_id = NULL, stamp_moved = '', moved_at = NULL,
       moved_by = '', moved_how = '', move_key = '', move_pid = NULL, appt_sig = '', ack = '', auto_why = ''
 WHERE id = {eid} AND appt_id = {aid} AND state = '{GCAL_MOVED}' AND move_key != ''
   AND appt_sig = (SELECT {_APPT_SIG} FROM appointments WHERE id = {aid})
   AND NOT EXISTS (SELECT 1 FROM gcal_events WHERE appt_id = {aid} AND id != {eid})
   AND {free};
DELETE FROM appointments WHERE id = {aid} AND NOT EXISTS (SELECT 1 FROM gcal_events WHERE appt_id = {aid});
COMMIT;"""
    try:
        await db._CONN.executescript(script)
    except Exception:
        await db._CONN.rollback()
        raise
    await gcal_menu_refresh()
    return not await _fetchval("SELECT COUNT(*) FROM appointments WHERE id = ?", aid)


async def gcal_linked(appt_id: int) -> bool:
    return bool(await _fetchval(
        "SELECT COUNT(*) FROM gcal_events WHERE appt_id = ?", appt_id))


async def gcal_expire(before: str) -> int:
    """Стирает текст событий раньше `before`; у события без даты счёт — от последней загрузки."""
    n = await _execute(
        """UPDATE gcal_events SET title = '', body = '', appt_sig = ''
           WHERE (title != '' OR body != '' OR appt_sig != '')
             AND ((starts_at IS NOT NULL AND starts_at < ?)
                  OR (starts_at IS NULL AND seen_at < ?))""", before, before)
    await gcal_menu_refresh()
    return n


async def gcal_clear() -> int:
    """«Șterge tot din Google»; ключи перенесённых и стёртых остаются — иначе загрузка задвоила бы журнал."""
    n = int(await _fetchval(
        "SELECT COUNT(*) FROM gcal_events WHERE state NOT IN (?, ?)",
        GCAL_MOVED, GCAL_ERASED) or 0)
    script = f"""BEGIN IMMEDIATE;
DELETE FROM gcal_events WHERE state NOT IN ('{GCAL_MOVED}', '{GCAL_ERASED}');
UPDATE gcal_events SET title = '', body = '', appt_sig = '';
UPDATE gcal_sources SET loaded_at = NULL, loaded_by = '', name = '', settings = '';
DELETE FROM gcal_sources WHERE id NOT IN (SELECT DISTINCT source_id FROM gcal_events);
COMMIT;"""
    try:
        await db._CONN.executescript(script)
    except Exception:
        await db._CONN.rollback()
        raise
    await gcal_menu_refresh()
    return n


async def gcal_journal(start: str, end: str) -> list:
    """Живые записи журнала в окне: по ним вкладка узнаёт событие, уже внесённое руками."""
    return await _fetch(
        f"""SELECT a.id, a.patient_id, a.starts_at, a.doctor, a.doctor_id, p.name
            FROM appointments a JOIN patients p ON p.id = a.patient_id
            WHERE a.starts_at >= ? AND a.starts_at <= ? AND a.status IN {_ACT_SQL}""",
        start, end)


async def gcal_patients() -> list:
    """Фиши для подсказки «кто это»; архивные не предлагаются."""
    return await _fetch("SELECT id, name, phone FROM patients WHERE archived = 0")


def gcal_phone_keys(phone: str) -> set:
    """Номер фиши в видах, в каких его отдаёт разбор текста: молдавский — восемь цифр, чужой — с плюсом."""
    from ..core import gimport          # db лежит ниже core: импорт отложен
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    keys = set(gimport.phones(phone or ""))
    if len(digits) >= 6:
        keys.add(digits)
    return keys


def _gcal_text_has(text: str, keys: set) -> bool:
    """Сверх разбора — цифры подряд без разделителей: стирание обязано найти
    и номер, записанный как попало; лишняя стёртая строка дешевле уцелевшей."""
    from ..core import gimport
    if keys & set(gimport.phones(text)):
        return True
    squashed = re.sub(r"\D", "", text)
    return any(k.isdigit() and k in squashed for k in keys)


async def gcal_ids_with_phone(phone: str) -> list:
    keys = gcal_phone_keys(phone)
    if not keys:
        return []
    rows = await _fetch(
        "SELECT id, title, body FROM gcal_events WHERE title != '' OR body != ''")
    return [int(r["id"]) for r in rows if _gcal_text_has(r["title"] + "\n" + r["body"], keys)]


def _gcal_erase_sql(where: str) -> str:
    """События → пустые строки-ключи. Текстом: его исполняет и скрипт полного
    стирания, которому параметры недоступны; `where` — только из чисел."""
    return (f"UPDATE gcal_events SET state = '{GCAL_ERASED}', title = '', body = '', "
            f"stamp = '', stamp_moved = '', gstatus = '', why = '', appt_id = NULL, "
            f"moved_by = '', move_pid = NULL, appt_sig = '' WHERE {where}")


async def gcal_erase(ids: list) -> None:
    if ids:
        await _execute(_gcal_erase_sql("id IN (" + ",".join(str(int(i)) for i in ids) + ")"))
        await gcal_menu_refresh()
