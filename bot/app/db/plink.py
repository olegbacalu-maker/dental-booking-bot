"""Ответ пациента ссылкой из SMS (Premium): коды визитов и их ответы.

Код выдаёт сервер лицензий; здесь — к какому визиту и к какому НАЧАЛУ визита он
выдан (`starts_key` — та же строка начала, что в ключе повтора SMS), что ответил
пациент и закрыт ли код на сервере. Решения «выдавать, применять, закрывать» —
`core/plink_loop.py`; отметку звонка в журнале пишет `modules/schedule/plink.py`.

Таблица без шага схемы (`PLINK_DDL`, как `IMPORT_DDL`): `CREATE TABLE IF NOT
EXISTS` в `schema.init`, повтор безвреден, откат на старую версию её не замечает.
Без `REFERENCES`: строку пациента убирает стирание по `patient_id`
(`_PATIENT_CHILD_TABLES`), а код, которого больше нет в базе, закрывает цикл по
списку `schema_meta › plink_close`.
Состояния: `open` — выдан, ответа нет; `yes` / `no` — ответ пациента; `closed` —
перенос, отмена, «Fără SMS», архив (`shut_at` — сервер подтвердил закрытие).
"""
from __future__ import annotations

import re
from datetime import datetime

from .conn import _execute, _fetch, _fetchval, _iso, _utcnow_iso

PLINK_DDL = """
CREATE TABLE IF NOT EXISTS sms_links(
  code TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  appt_id INTEGER NOT NULL,
  patient_id INTEGER NOT NULL,
  starts_key TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'open',
  seq INTEGER NOT NULL DEFAULT 0,
  until_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  answer_at TEXT,
  shut_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_sms_links_appt ON sms_links(appt_id, starts_key);
"""

LINK_OPEN, LINK_YES, LINK_NO, LINK_CLOSED = "open", "yes", "no", "closed"
LINK_LIVE = (LINK_OPEN, LINK_YES, LINK_NO)
_LIVE_SQL = "('open','yes','no')"
PLINK_CLOSE_META = "plink_close"           # коды стёртых пациентов, которые ещё не закрыты на сервере
_CODE = re.compile(r"^[A-HJ-NP-Z2-9]{6}$")
# начало визита строкой ключа — та же, что `sms_plan.idem` и выборка дня `db/schedule.py`
_STARTS_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', a.starts_at)"


async def plink_codes_for(appt_ids: list[int]) -> dict:
    """Живые коды визитов при НЫНЕШНЕМ начале: {appt_id: code}. Код прежнего начала
    не возвращается — перенос получает новый код."""
    if not appt_ids:
        return {}
    lite = ",".join("?" for _ in appt_ids)
    rows = await _fetch(
        f"""SELECT l.appt_id, l.code FROM sms_links l JOIN appointments a ON a.id = l.appt_id
            WHERE l.appt_id IN ({lite}) AND l.state IN {_LIVE_SQL}
              AND l.starts_key = {_STARTS_SQL}
            ORDER BY l.created_at""", *appt_ids)
    return {r["appt_id"]: r["code"] for r in rows}


async def plink_add(code: str, kind: str, appt_id: int, patient_id: int, starts_key: str,
                    until_at: datetime) -> bool:
    n = await _execute(
        """INSERT OR IGNORE INTO sms_links(code, kind, appt_id, patient_id, starts_key, state,
                                          until_at, created_at)
           VALUES(?, ?, ?, ?, ?, 'open', ?, ?)""",
        code, kind, appt_id, patient_id, starts_key, _iso(until_at), _utcnow_iso())
    return n > 0


async def plink_get(code: str) -> dict | None:
    rows = await _fetch("SELECT * FROM sms_links WHERE code = ?", code)
    return rows[0] if rows else None


async def plink_answer(code: str, state: str, seq: int, at: datetime) -> bool:
    """Ответ сервера по коду: применяется, только если перемена новее принятой
    (`seq`), а код не закрыт. True — состояние сменилось и его надо показать журналу.
    Повторная доставка той же перемены — тихое «нет»."""
    n = await _execute(
        f"""UPDATE sms_links SET state = ?, seq = ?, answer_at = ?
            WHERE code = ? AND seq < ? AND state IN {_LIVE_SQL}""",
        state, int(seq), _iso(at), code, int(seq))
    return n > 0


async def plink_live_count(now: datetime) -> int:
    """Сколько кодов ещё ждут ответа или могут его сменить (срок не прошёл)."""
    return int(await _fetchval(
        f"SELECT COUNT(*) FROM sms_links WHERE state IN {_LIVE_SQL} AND until_at > ?", _iso(now)) or 0)


async def plink_last_no(since: datetime) -> int:
    """Номер последней перемены «Nu pot veni» после `since` (0 — нет): уведомлению у часов."""
    return int(await _fetchval(
        "SELECT COALESCE(MAX(seq), 0) FROM sms_links WHERE state = 'no' AND answer_at > ?",
        _iso(since)) or 0)


async def plink_stale() -> list[str]:
    """Живые коды, чей визит перенесён, отменён, удалён, у пациента «Fără SMS» или он в
    архиве: их надо закрыть, иначе пациент ответил бы на то, чего больше нет."""
    rows = await _fetch(
        f"""SELECT l.code FROM sms_links l
                 LEFT JOIN appointments a ON a.id = l.appt_id
                 LEFT JOIN patients p ON p.id = l.patient_id
            WHERE l.state IN {_LIVE_SQL}
              AND (a.id IS NULL OR a.status = 'cancelled' OR l.starts_key <> {_STARTS_SQL}
                   OR p.id IS NULL OR COALESCE(p.sms_off, 0) = 1 OR COALESCE(p.archived, 0) = 1)
            ORDER BY l.created_at""")
    return [r["code"] for r in rows]


async def plink_mark_closed(codes: list[str]) -> None:
    """Закрыть у себя — сервер узнает следующим проходом (`plink_unshut`)."""
    for code in codes:
        await _execute(f"UPDATE sms_links SET state = 'closed' WHERE code = ? AND state IN {_LIVE_SQL}", code)


async def plink_unshut(limit: int = 200) -> list[str]:
    rows = await _fetch(
        "SELECT code FROM sms_links WHERE state = 'closed' AND shut_at IS NULL ORDER BY created_at LIMIT ?",
        limit)
    return [r["code"] for r in rows]


async def plink_shut(codes: list[str]) -> None:
    now = _utcnow_iso()
    for code in codes:
        await _execute("UPDATE sms_links SET shut_at = ? WHERE code = ? AND state = 'closed'", now, code)


async def plink_patient_rows(pid: int) -> list:
    """Коды пациента — его выгрузке по 195-му (ответ пациента — его данные)."""
    return await _fetch(
        """SELECT code, kind, appt_id, starts_key, state, until_at, created_at, answer_at
           FROM sms_links WHERE patient_id = ? ORDER BY created_at""", pid)


def _plink_forget_sql(codes: list[str]) -> str:
    """Оператор «эти коды закрыть на сервере» для скрипта стирания: строки пациента уйдут
    из таблицы, а код на сервере должен умереть сразу, не через срок. Коды подставляются
    текстом (executescript параметров не берёт) — только по правилу кода."""
    good = [c for c in codes if _CODE.match(c)]
    if not good:
        return ""
    val = ",".join(good)
    return (f"INSERT INTO schema_meta(key, value) VALUES('{PLINK_CLOSE_META}', '{val}') "
            "ON CONFLICT(key) DO UPDATE SET value = CASE WHEN value = '' THEN excluded.value "
            "ELSE value || ',' || excluded.value END;")


async def plink_codes_of(pid: int) -> list[str]:
    """Коды пациента, которые сервер ещё может открыть (не подтверждённые закрытием)."""
    rows = await _fetch(
        "SELECT code FROM sms_links WHERE patient_id = ? AND shut_at IS NULL", pid)
    return [r["code"] for r in rows]


async def plink_forget(pid: int) -> None:
    """Обезличивание: строки кодов уходят, коды — в список закрытия (тот же оператор,
    что у полного удаления, отдельной транзакцией: обезличивание пошаговое)."""
    sql = _plink_forget_sql(await plink_codes_of(pid))
    if sql:
        await _execute(sql)
    await _execute("DELETE FROM sms_links WHERE patient_id = ?", pid)
