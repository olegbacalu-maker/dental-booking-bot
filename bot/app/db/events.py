"""Летопись: события пациента и клиники, кто за журналом.

Подпись события — имя вошедшего (`db.ACTOR_HOOK`, ставит `main.py` при
старте); хук читается через пакет, а не по значению."""
from __future__ import annotations

from datetime import datetime

from .. import db
from .conn import _execute, _fetch, _fetchval, _iso, _utcnow_iso, log


def _actor_now(default: str = "recepție") -> str:
    """Имя вошедшего для летописи. Любая осечка молча даёт прежнюю подпись:
    журнал не имеет права уронить саму операцию."""
    try:
        return (db.ACTOR_HOOK() if db.ACTOR_HOOK else None) or default
    except Exception:                                   # noqa: BLE001
        return default


# ПОТОЛОК текста события. ⚠️ Обрезка ЖЁСТКАЯ и посреди слова, а строка хранится
# навсегда — переписать её нечем. ⛔ Поднимать это число «чтобы влезло» нельзя:
# в колонке уже лежат строки, обрезанные прежним потолком, и новый к ним не
# относится — картотека станет разноформатной, а обрезанное не вернётся. Строку
# сокращают, а не потолок поднимают (08-16, `uq_event_text`).
EVENT_TEXT_MAX = 200


async def log_event(patient_id: int | None, kind: str, text: str, *,
                    actor: str = "", tooth: int | None = None) -> None:
    """Событие карты пациента. Никогда не роняет основную операцию: журнал —
    это летопись, а не транзакция; потерянная строка хуже, чем упавшая запись
    к врачу, только в одном случае — если из-за неё не состоялась сама запись.

    ⚠️ Хранится ГОТОВАЯ строка, и переписывать её потом нельзя: летопись
    отвечает на вопрос «кто что сделал», а не «как это выглядит сегодня».
    Отсюда правило для вызывающих: внутренний код (`in_lucru`, `noshow`,
    `obturatie`) разворачивается в СЛОВО здесь и сейчас — ту же строку читает
    и лента фиши, и выгрузка по 195-му, где она обязана быть «в понятной
    форме». Словари слов лежат по месту их смысла (`core.layout.STATUS_LABEL`,
    `fisa043.PLAN_RO`, `teeth_svg.STATE_RO`) и берутся ОТЛОЖЕННЫМ импортом:
    db лежит ниже слоя интерфейса, и на уровне модуля это замкнуло бы круг.
    """
    if patient_id is None:
        return
    # подпись по умолчанию — ИМЯ вошедшего, а не канал: закон 195 спрашивает
    # «кто именно открыл фишу», и «recepție» на этот вопрос не отвечает
    actor = actor or _actor_now()
    try:
        await _execute(
            """INSERT INTO activity(patient_id, at, actor, kind, tooth, text)
               VALUES(?, ?, ?, ?, ?, ?)""",
            patient_id, _utcnow_iso(), actor, kind, tooth,
               text[:EVENT_TEXT_MAX],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("activity %s/%s failed: %r", patient_id, kind, e)


async def log_clinic_event(kind: str, text: str, actor: str = "sistem") -> None:
    """Событие УРОВНЯ КЛИНИКИ — patient_id NULL. Попадает в ленту «Activitate
    recentă» (её LEFT JOIN такие строки переживает), но ни в одну фишу:
    фишам чужие события не принадлежат."""
    try:
        await _execute(
            """INSERT INTO activity(patient_id, at, actor, kind, text)
               VALUES(NULL, ?, ?, ?, ?)""",
            _utcnow_iso(), actor, kind, text[:EVENT_TEXT_MAX],
        )
    except Exception as e:  # noqa: BLE001 — летопись не роняет операцию
        log.warning("clinic event %s failed: %r", kind, e)


async def _log_booking(pid: int, service: str, doctor: str,
                       starts_at: datetime, source: str) -> None:
    """Событие «записался» — одно на все пути брони, поэтому вынесено."""
    await log_event(pid, "appt_new",
                    f"Programare: {service} · {doctor} · "
                    f"{starts_at.strftime('%d.%m.%Y %H:%M')}",
                    actor="bot" if source == "bot" else "recepție")


async def patient_activity(pid: int, limit: int = 50, *,
                           include_views: bool = False) -> list:
    """История фиши. По умолчанию БЕЗ просмотров: журнал доступа (кто открывал
    карточку — требование закона 195) пишется в ту же таблицу, но в ленте фиши
    ему не место — рецепция открывает карточку по многу раз на дню, и лента из
    «Fișa deschisă» перестала бы читаться. Выгрузка данных пациента зовёт с
    include_views=True: в КОПИИ обязаны быть и просмотры — это тоже обработка."""
    if include_views:
        return await _fetch(
            """SELECT id, at, actor, kind, tooth, text FROM activity
               WHERE patient_id = ? ORDER BY at DESC, id DESC LIMIT ?""",
            pid, limit)
    return await _fetch(
        """SELECT id, at, actor, kind, tooth, text FROM activity
           WHERE patient_id = ? AND kind NOT IN ('view','doc_view')
           ORDER BY at DESC, id DESC LIMIT ?""", pid, limit)


async def recent_activity(limit: int = 10) -> list:
    """Последние события ПО ВСЕЙ клинике — лента «Activitate recentă» в
    аналитике. Просмотры отфильтрованы по той же причине, что в ленте фиши:
    рецепция открывает карточки десятки раз на дню, и лента из «Fișa deschisă»
    перестала бы читаться (журнал доступа живёт своей страницей)."""
    return await _fetch(
        """SELECT a.id, a.at, a.actor, a.kind, a.text, a.patient_id, p.name
           FROM activity a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.kind NOT IN ('view','doc_view')
           ORDER BY a.at DESC, a.id DESC LIMIT ?""", limit)


async def tooth_activity(pid: int) -> list:
    """События по зубам — для истории конкретного зуба в диалоге."""
    return await _fetch(
        """SELECT at, actor, tooth, text FROM activity
           WHERE patient_id = ? AND tooth IS NOT NULL ORDER BY at DESC, id DESC""", pid)


async def tooth_records_since(pid: int, since: datetime) -> list:
    """Строки летописи по зубам и мостам С мгновения `since`, свежие первыми, —
    «сравнить с визитом» для даты раньше начала истории зубов (25.10): там
    состояния на ту дату нет, и экран показывает ДОСЛОВНО, что записывали
    после, а не догадку о том, каким зуб был. Мосты в летописи без номера
    зуба (`kind` 'bridge'), поэтому идут отдельным условием."""
    return await _fetch(
        """SELECT at, tooth, text FROM activity
           WHERE patient_id = ? AND (tooth IS NOT NULL OR kind = 'bridge') AND at >= ?
           ORDER BY at DESC, id DESC""", pid, _iso(since))


async def _backfill_activity() -> None:
    """Разовый перенос уже существующих визитов в журнал: иначе у клиники,
    которая работает полгода, таймлайн стартует с пустого места, хотя история
    визитов у нас есть. Идемпотентно — отмечается флагом в schema_meta."""
    done = await _fetchval("SELECT value FROM schema_meta WHERE key = 'act_backfill'")
    if done:
        return
    rows = await _fetch(
        """SELECT id, patient_id, service, doctor, starts_at, created_at, source
           FROM appointments WHERE patient_id IS NOT NULL ORDER BY created_at""")
    # Летопись читает человек: час обязан быть часом КЛИНИКИ, как в живом пути
    # (_log_booking печатает дату, построенную в eng.TZ), а _fetch отдаёт
    # starts_at в UTC — без перевода перенесённый визит на 09:00 записался бы
    # «06:00» навсегда, текст события строка и не пересчитывается.
    # Импорт отложенный: engine импортирует db, на уровне модуля был бы круг.
    from .. import engine as eng
    n = 0
    for r in rows:
        when = r["starts_at"]
        txt = f"Programare: {r['service']} · {r['doctor']}"
        if hasattr(when, "strftime"):
            if getattr(when, "tzinfo", None) is not None:
                # переводить только значения С поясом: astimezone на наивном
                # подставил бы пояс машины и мог сдвинуть день
                when = when.astimezone(eng.TZ)
            txt += " · " + when.strftime("%d.%m.%Y %H:%M")
        await _execute(
            """INSERT INTO activity(patient_id, at, actor, kind, text)
               VALUES(?, ?, ?, ?, ?)""",
            r["patient_id"], _iso(r["created_at"]) if hasattr(r["created_at"], "strftime")
               else str(r["created_at"]),
               "bot" if r["source"] == "bot" else "recepție", "appt_new", txt[:200],
        )
        n += 1
    await _execute(
        """INSERT INTO schema_meta(key, value) VALUES('act_backfill', ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""", str(n))
    if n:
        log.warning("activity backfill: %s programări перенесены в журнал", n)
