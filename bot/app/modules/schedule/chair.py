"""Экран «у кресла»: кто у врача в кресле и кто следующий. Разметки нет.

Контракт — `docs/dentpilot-2/chair-mode.md`. Олег 26.09: планшет врача над
креслом — «он включил программу и быстро записал данные по одонтограмме».
Экран не ищет пациента: сервер отвечает, КТО в кресле, одним правилом здесь,
а экран только рисует ответ (тот же прайор, что правила правой колонки
панели в `panel.py`).

⛔ Статусы — ПЕРЕЧИСЛЕНИЕМ, не «всё, кроме done»: правило «всё, кроме X» живёт
ровно до второго X (грабля `PLAN_ACTIVE`, CLAUDE.md). Оба набора обязаны
лежать внутри `db.ACTIVE_STATUSES` — держит `tests/test_chair.py`.
⚠️ Модуль без импортов проекта: правило разбирает прогон без сервера.
"""
from __future__ import annotations

# «în cabinet» (`layout.STATUS_LABEL`): регистратура переводит правой кнопкой
# на панели (v1.31.0), врач — с экрана кресла.
CHAIR = "arrived"
# Очередь: сперва уже пришедшие («a venit», в приёмной), затем записанные.
QUEUE = ("waiting", "confirmed")


def resolve_doctor(asked: str, user: dict | None, known) -> str:
    """Чей экран: `?doctor=` из адреса, если такой врач есть; иначе врач,
    к которому привязана учётка вошедшего (`doctor_id`, 08-06); иначе пусто —
    экран предложит выбрать. Директору и регистратуре кресло любого врача
    открывается адресом, врачу — своё без единого касания."""
    if asked and asked in known:
        return asked
    mine = str((user or {}).get("doctor_id") or "")
    return mine if mine in known else ""


def model(rows: list, items: list) -> dict:
    """`rows` — строки дня ЭТОГО врача (`db.day_appointments`), `items` — они
    же повесткой (`panel.agenda(...)["items"]`): форма строки одна на панель и
    кресло, второй сборки слова статуса нет.

    ⭐ В кресле — тот, кого ПОСЛЕДНИМ завели в кабинет (`arrived_at`, штамп
    конвейера 08-13). Несколько `arrived` у одного врача — это забытое
    «Finalizează» у прошлого пациента, а не два человека в одном кресле:
    последний щелчок «În cabinet» и есть тот, кто сидит. Остальные `arrived`
    идут в `stale` — видны строкой «не завершён», а не прячутся. Строка без
    штампа (старше 08-13) — по времени приёма, и она всегда старше любой
    строки со штампом.
    Очередь: `waiting` — кто раньше пришёл (`wait_since`), затем `confirmed` —
    по времени приёма (порядок повестки).
    ⚠️ Штампы — с точностью до секунды (`db._iso`): ничья в одну секунду
    решается временем приёма, затем id — порядок детерминирован.
    """
    by_id = {it["id"]: it for it in items}

    def when(r: dict):
        at = r.get("arrived_at")
        # (есть штамп, штамп или время приёма, время приёма, id): кортеж не
        # сравнивает None с датой, а тай-брейк id — чтобы порядок не зависел
        # от того, в каком порядке база отдала ничью
        return (at is not None, at or r["starts_at"], r["starts_at"], r["id"])

    arrived = sorted((r for r in rows if r["status"] == CHAIR and r["id"] in by_id),
                     key=when)
    chair = by_id[arrived[-1]["id"]] if arrived else None
    stale = [by_id[r["id"]] for r in arrived[:-1]]
    waiting = sorted((it for it in items if it["status"] == QUEUE[0]),
                     key=lambda it: (it.get("wait_since") is None,
                                     it.get("wait_since") or 0))
    later = [it for it in items if it["status"] == QUEUE[1]]
    return {"chair": chair, "stale": stale, "queue": waiting + later}
