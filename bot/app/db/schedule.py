"""Визиты и журнал: запись, заметки, день и дни, звонки, перенос, статус.

Всё, что занимает слот, берёт `slots._slot_lock`."""
from __future__ import annotations

from datetime import datetime, timezone

from .. import db
from .conn import _execute, _fetch, _fetchval, _iso, _utcnow_iso, log
from .events import _actor_now, log_event
from .slots import (
    _ACT_SQL, _book, _book_locked, _conflicts, _lane, _patient_busy,
    _patient_busy_at, _pick_room, _room_label, _slot_lock, ACTIVE_STATUSES,
)
from .patients import (
    _patient_ids_by_digits, _upsert_patient, manual_key, patient_id_by_key, set_birth_year,
)
from .sms import _SMS_REMINDED_SQL
from .plans import PLAN_ACTIVE


async def backfill_ids(doc_map: dict, svc_map: dict) -> None:
    """Проставляет doctor_id/service_id старым записям по ТЕКУЩЕМУ конфигу
    (имя→id, подпись ro/ru→id). Идемпотентно: трогает только NULL. Записи
    врачей, переименованных ДО этого обновления, остаются с NULL — их
    восстановить не по чему, канва показывает их отдельной колонкой."""
    for name, did in doc_map.items():
        try:
            await _execute(
                "UPDATE appointments SET doctor_id = ? WHERE doctor_id IS NULL AND doctor = ?",
                did, name,
            )
        except Exception as e:  # noqa: BLE001 — конфликт uq_doctor_slot_id на патологии
            log.warning("backfill doctor_id failed for %r: %r", name, e)
            await db._CONN.rollback()
    for label, sid_ in svc_map.items():
        try:
            await _execute(
                """UPDATE appointments SET service_id = ?
                   WHERE service_id IS NULL AND service = ? AND source != 'note'""",
                sid_, label,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("backfill service_id failed for %r: %r", label, e)
            await db._CONN.rollback()


async def relink_doctor(old_name: str, doctor_id: str) -> int:
    """Переприкрепляет сиротские строки (doctor_id IS NULL, старое имя) к врачу.
    Лечит записи, осиротевшие при переименовании ещё ДО v1.7.1 — включая
    будущие брони, невидимые для проверки занятости."""
    try:
        return await _execute(
            "UPDATE appointments SET doctor_id = ? WHERE doctor_id IS NULL AND doctor = ?",
            doctor_id, old_name,
        )
    except Exception as e:  # noqa: BLE001 — конфликт uq_doctor_slot_id (двойник часа)
        log.warning("relink %r -> %s failed: %r", old_name, doctor_id, e)
        await db._CONN.rollback()
        return -1


async def seed(rows: list | None) -> None:
    """Демо-записи (из конфига клиники) — только в пустую БД."""
    if not rows:
        return
    n = await _fetchval("SELECT count(*) FROM appointments")
    if n:
        return
    for row in rows:
        # ⛔ по именам: позиционная распаковка через границу модуля уже
        # разъехалась однажды, молча (см. engine.build_seed_rows)
        await admin_add(**row)


async def create_appointment(
    session_key: str, name: str, phone: str, lang: str,
    service: str, doctor: str, starts_at: datetime,
    source: str = "manual", birth_year: int | None = None,
    doctor_id: str | None = None, service_id: str | None = None,
    duration_min: int = 60,
    rooms: dict | None = None, room: str | None = None,
) -> int | str | None:
    """id записи; None — интервал занят у этого врача; 'dup' — у пациента
    уже есть своя запись на это время. doctor/service = снапшоты подписи,
    doctor_id/service_id = стабильные ключи; duration_min = снапшот
    длительности услуги на момент брони. `rooms` — кабинеты врача
    (`eng.room_plan`), `room` — назначенный кабинет (нет — первый свободный)."""
    async with _slot_lock():
        if await patient_id_by_key(session_key) is None:
            # ⚠️ НОВОГО человека не заводим, пока слот не подтверждён: upsert
            # до проверки оставлял при отказе «интервал занят» карточку-сироту
            # без единого визита (всплывало в аудитах 08-04, починено 08-07).
            # Для СУЩЕСТВУЮЩЕГО порядок прежний: upsert обновляет имя/телефон
            # даже при отказе — пациент сам их продиктовал. Всё под ОДНИМ
            # замком: проверка вне его снова открыла бы окно для сироты.
            if await _conflicts(doctor_id, doctor, starts_at, duration_min,
                                rooms=rooms, room=room):
                return None
        pid = await _upsert_patient(session_key, name, phone, lang, birth_year)
        return await _book_locked(pid, service, doctor, starts_at, source,
                                  doctor_id, service_id, duration_min,
                                  rooms=rooms, room=room)


async def admin_add(
    name: str, phone: str, service: str, doctor: str, starts_at: datetime,
    birth_year: int | None = None, birth_date: str | None = None,
    doctor_id: str | None = None, service_id: str | None = None,
    duration_min: int = 60, duration_set: bool = False,
    rooms: dict | None = None, room: str | None = None,
) -> int | str | None:
    """Ручная запись из журнала клиники. Пациент дедуплицируется по телефону.

    `duration_set` — длительность выбрали в окне записи руками (10.11): тогда
    у записи ставится признак, и смена процедуры её не перебьёт."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    # Пациента ищем по НОМЕРУ среди существующих, а не по ключу manual:<цифры>
    # (08-07): у пациента из Telegram ключ tg:…, и путь по ключу заводил
    # карточку-двойника — визит задним числом уезжал не тому человеку.
    # Ровно одно совпадение цифр → пишем визит по id; попутно это перестало
    # переименовывать существующего («Ion P.» из формы журнала больше не
    # затирает «Ion Popescu» в фише). Ноль совпадений → новый manual-пациент,
    # как раньше. Несколько (семейный номер) → прежняя склейка по ключу:
    # выбрать «правильного» из двоих тут не из чего.
    ids = await _patient_ids_by_digits(digits)
    key = manual_key(digits)
    existing_name, has_bd = None, False
    if len(ids) == 1:
        pid = ids[0]
        rows_p = await _fetch(
            "SELECT name, birth_date FROM patients WHERE id = ?", pid)
        if rows_p:
            existing_name = rows_p[0]["name"]
            has_bd = bool(rows_p[0]["birth_date"])
        r = await _book(pid, service, doctor, starts_at, "manual",
                        doctor_id, service_id, duration_min,
                        rooms=rooms, room=room)
    else:
        r = await create_appointment(
            key, name, phone, "ro", service, doctor, starts_at,
            source="manual", birth_year=birth_year,
            doctor_id=doctor_id, service_id=service_id, duration_min=duration_min,
            rooms=rooms, room=room,
        )
        pid = await patient_id_by_key(key)
    # дата рождения — тем же правилом, что год в upsert: новое значение, если
    # оно задано. Пишем и при dup/conflict — пациент уже существует, а дату
    # регистратура ввела про него же. В ветке по id upsert не выполнялся,
    # поэтому одиночный год (устаревшая вкладка) дописывается здесь же
    # ⛔ Дату рождения НЕ писать поверх чужой карточки (08-10, находка аудита).
    # Семейный номер — норма: ребёнка записывают на телефон родителя. Ветка
    # `len(ids) == 1` находит родителя по цифрам и пишет визит ему, а дальше
    # сюда приходила дата рождения РЕБЁНКА и затирала родительскую — без
    # истории и без предупреждения, зелёным баннером «ok». Год рождения уже
    # был осторожнее (`elif ... len(ids) == 1`), у полной даты этой оглядки не
    # было. Теперь дату принимает только карточка, у которой её ещё нет, либо
    # та, чьё имя совпало с набранным.
    same_person = (not name) or not existing_name or \
        existing_name.strip().lower() == name.strip().lower()
    if pid is not None:
        if birth_date and (same_person or not has_bd):
            await _execute(
                "UPDATE patients SET birth_date = ?, birth_year = ? WHERE id = ?",
                birth_date, birth_year, pid)
        elif birth_year and len(ids) == 1:
            await set_birth_year(pid, birth_year)
    if duration_set and isinstance(r, int):
        # Признак — отдельной строкой ПОСЛЕ брони, а не колонкой в общей
        # вставке `_book_locked` (её зовут запись из фиши и бот-наследие):
        # длительность уже легла верная, признак говорит только, кто её задал.
        await _execute("UPDATE appointments SET duration_set = 1 WHERE id = ?", r)
    return r


async def add_visit_for_patient(
    pid: int, service: str, doctor: str, starts_at: datetime,
    doctor_id: str | None = None, service_id: str | None = None,
    duration_min: int = 60,
    rooms: dict | None = None, room: str | None = None,
) -> int | str | None:
    """Запись ИЗ ФИШИ: пациент уже известен по id, дедупликация по телефону
    здесь была бы вредна. Общий путь (`manual:{цифры}`) склеивает пациентов по
    номеру, а у телеграм-пациента session_key 'tg:…' — визит из его же фиши
    уехал бы новому пациенту-двойнику или соседу с тем же семейным номером."""
    return await _book(pid, service, doctor, starts_at, "manual",
                       doctor_id, service_id, duration_min,
                       rooms=rooms, room=room)


async def add_note(doctor: str, starts_at: datetime, text: str,
                   doctor_id: str | None = None) -> int | None:
    """Заметка/блокировка слота: без пациента, но занимает слот врача."""
    async with _slot_lock():
        # заметка тоже обязана уважать интервалы (иначе ложится поверх визита)
        if await _conflicts(doctor_id, doctor, starts_at, 60, note=True):
            return None
        return await _insert_note(doctor, starts_at, text, doctor_id)


async def _insert_note(doctor: str, starts_at: datetime, text: str,
                       doctor_id: str | None) -> int | None:
    try:
        cur = await db._CONN.execute(
            """INSERT INTO appointments(patient_id, service, doctor, starts_at,
                                        source, doctor_id, created_at)
               VALUES(NULL, ?, ?, ?, 'note', ?, ?)""",
            (text, doctor, _iso(starts_at), doctor_id, _utcnow_iso()),
        )
        await db._CONN.commit()
        note_id = cur.lastrowid
        await cur.close()
        return note_id
    except db._SQ.IntegrityError:
        await db._CONN.rollback()
        return None


async def busy_lanes(doctor_key: str, doctor_name: str,
                     start: datetime, end: datetime,
                     rooms: tuple = ()) -> list[list]:
    """Занятые ИНТЕРВАЛЫ врача по кабинетам: на каждый кабинет из `rooms` свой
    список [(старт, длительность_мин)], у врача без кабинетов — один список.
    Старт свободен, пока свободен хоть один список; заметка стойки стоит в
    каждом. Матчинг и NULL-длительность (60 минут) — как у `_doctor_overlaps`."""
    rows = await _fetch(
        f"""SELECT starts_at, duration_min, room_id, source FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL}
             AND starts_at >= ? AND starts_at < ?""",
        doctor_key, doctor_name, _iso(start), _iso(end),
    )
    own = tuple(rooms or ())
    lanes: dict[str, list] = {rid: [] for rid in (own or ("",))}
    for r in rows:
        span = (r["starts_at"], int(r["duration_min"] or 60))
        if r["source"] == "note":
            for lane in lanes.values():
                lane.append(span)
        else:
            lanes[_lane(r["room_id"], own)].append(span)
    return list(lanes.values())


async def doctor_future_count(doctor_key: str, doctor_name: str,
                              now: datetime) -> int:
    """Сколько живых записей у врача впереди — замок на архивацию (v1.9.0).
    Матчинг тот же, что в booked_intervals: id, легаси-строки — по имени."""
    return await _fetchval(
        f"""SELECT COUNT(*) FROM appointments
           WHERE (doctor_id = ? OR (doctor_id IS NULL AND doctor = ?))
             AND status IN {_ACT_SQL} AND starts_at >= ?""",
        doctor_key, doctor_name, _iso(now),
    ) or 0


async def appt_patient_id(appt_id: int) -> int | None:
    """Пациент записи — по её id (окно записи узнаёт, кому досталась запись)."""
    v = await _fetchval("SELECT patient_id FROM appointments WHERE id = ?", appt_id)
    return int(v) if v is not None else None


# ---------- журнал/поиск/статусы ----------

async def day_appointments(day_start: datetime, day_end: datetime) -> list:
    # has_rec — «консультация записана»: не дата, в _DT_COLS ему не место
    # sms_sent — SMS-напоминание принято сервером или доставлено (S5): второй
    # источник колокольчика «Reminder trimis» рядом с reminded_day (флаг
    # удалённого Telegram-бота у старых визитов)
    # call_result — отметка звонка-подтверждения (`appt_calls`, 03.10): по ней
    # «programată» становится «confirmată» в повестке и списке дня. Ключ
    # первичный — строк не размножает. ⚠️ Не `AS call`: в стандарте SQL это слово занято.
    # ⛔ Тай-брейк `a.id` в ORDER BY несущий, а не косметика. Ничья по
    # (starts_at, doctor) достижима — заметка стойки и визит на одну минуту у
    # одного врача (`_conflicts` заметки не стережёт), две заметки в слоте, — и
    # она тянется ВНИЗ: канва сортирует кластеры устойчиво, то есть наследует
    # порядок базы, а порядок внутри кластера решает `col`/`of`, то есть
    # геометрию блоков. SQLite на практике стабилен, но стандарт не обещает
    # ничего. Без тай-брейка два опроса живого журнала
    # при НЕИЗМЕННОМ дне дали бы разное тело, подмена шла бы каждые 12 секунд —
    # мигание, от которого ушли 08-20, и только у той клиники, где кто-то
    # поставил заметку поверх визита.
    return await _fetch(
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id, a.service_id,
                  a.starts_at, a.duration_min, a.status, a.source,
                  a.reminded_day, a.comment, a.waiting_at, a.arrived_at,
                  a.room_id, a.room,
                  p.name, p.phone, p.birth_year,
                  (vr.id IS NOT NULL) AS has_rec, ac.result AS call_result,
                  EXISTS(SELECT 1 FROM sms_log s WHERE s.appt_id = a.id
                         AND s.state IN """ + _SMS_REMINDED_SQL + """) AS sms_sent
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
                LEFT JOIN visit_records vr ON vr.appointment_id = a.id
                LEFT JOIN appt_calls ac ON ac.appointment_id = a.id
           WHERE a.starts_at >= ? AND a.starts_at < ?
           ORDER BY a.starts_at, a.doctor, a.id""",
        _iso(day_start), _iso(day_end),
    )


async def appointment_days(start: datetime, end: datetime) -> list:
    """Записи окна ТРЕМЯ колонками — для точек мини-календаря (08.10): день,
    в который есть хоть одна живая запись. Полная выборка `day_appointments`
    на шесть недель тянула бы пациентов и визиты ради одной даты на строку.
    Что считается живой записью (без отменённых и заметок стойки), решает
    вызывающий, как и у повестки: правило одно, живёт рядом с выборкой дня."""
    # doctor_id/doctor — точки календаря в шапке дня ОДНОГО врача (22.10): его
    # записи отбирает `routes._of_doctor`, тем же правилом, что и сам день
    return await _fetch(
        """SELECT starts_at, status, source, doctor_id, doctor FROM appointments
           WHERE starts_at >= ? AND starts_at < ?""",
        _iso(start), _iso(end),
    )


async def day_patient_facts(pids: list, before: datetime) -> dict:
    """Что карточка визита дня ОДНОГО врача знает о его пациентах (22.10,
    вариант A Олега): прошлые визиты с графой «Tratament» дневника,
    предупреждения фиши, анамнез, активный план.

    ⭐ ЧЕТЫРЕ выборки на весь день по списку пациентов, а не запрос на визит:
    день врача с двенадцатью визитами стоил бы полсотни запросов на каждое
    открытие и на каждый ответ действия (`_done` отдаёт свежий день).
    Визиты — только до `before` (конец дня экрана): прошлое ЭТОГО дня, а не
    сегодняшнего, поэтому ответ зависит от данных, а не от часов.
    Отменённые и неявки визитом не считаются; заметок здесь нет (у них нет
    пациента). Активный план — перечислением (`PLAN_ACTIVE`).
    ⛔ Денег здесь нет (Олег 22.10: «не думаю что врачу эта информация
    нужна»): долг живёт в фише и у статистики, на дне врача его не видит и
    директор.
    """
    if not pids:
        return {"visits": {}, "alerts": {}, "anam": {}, "plan": {}}
    lite = ",".join("?" for _ in pids)
    act = ",".join("?" for _ in PLAN_ACTIVE)
    visits: dict[int, list] = {}
    for r in await _fetch(
            f"""SELECT a.id, a.patient_id, a.starts_at, a.service, vr.tratament
                FROM appointments a LEFT JOIN visit_records vr ON vr.appointment_id = a.id
                WHERE a.patient_id IN ({lite}) AND a.starts_at < ?
                  AND a.status NOT IN ('cancelled', 'noshow')
                ORDER BY a.starts_at, a.id""", *pids, _iso(before)):
        visits.setdefault(r["patient_id"], []).append(r)
    alerts: dict[int, list] = {}
    for r in await _fetch(
            f"SELECT patient_id, kind, text FROM patient_alerts WHERE patient_id IN ({lite}) "
            "ORDER BY id", *pids):
        alerts.setdefault(r["patient_id"], []).append(r)
    # created_at/updated_at — дата опроса для «neagă afecțiunile» дня врача
    anam = {r["patient_id"]: r for r in await _fetch(
        f"""SELECT patient_id, flags, boli, medicamente, alergii, anestezie,
                   created_at, updated_at
            FROM anamneza WHERE patient_id IN ({lite})""", *pids)}
    plan: dict[int, list] = {}
    for r in await _fetch(
            f"""SELECT patient_id, tooth, procedure, status FROM plan_items
                WHERE patient_id IN ({lite}) AND status IN ({act}) ORDER BY id""",
            *pids, *PLAN_ACTIVE):
        plan.setdefault(r["patient_id"], []).append(r)
    return {"visits": visits, "alerts": alerts, "anam": anam, "plan": plan}


async def appt_calls(ids: list) -> dict:
    """Отметки звонка-подтверждения по визитам: {appointment_id: строка}."""
    if not ids:
        return {}
    lite = ",".join("?" for _ in ids)
    rows = await _fetch(
        f"SELECT appointment_id, result, actor, at FROM appt_calls WHERE appointment_id IN ({lite})",
        *ids)
    return {r["appointment_id"]: r for r in rows}


async def set_appt_call(aid: int, result: str) -> None:
    """«ok» — дозвонились, визит подтверждён; «noanswer» — не ответил;
    пустое — снять отметку. Автор — вошедший (ACTOR_HOOK), как в летописи."""
    if not result:
        await _execute("DELETE FROM appt_calls WHERE appointment_id = ?", aid)
        return
    now = datetime.now(timezone.utc)
    await _execute(
        """INSERT INTO appt_calls(appointment_id, result, actor, at) VALUES(?, ?, ?, ?)
           ON CONFLICT(appointment_id) DO UPDATE SET result = excluded.result,
             actor = excluded.actor, at = excluded.at""",
        aid, result, _actor_now(), _iso(now))


async def set_comment(appt_id: int, text: str) -> None:
    await _execute(
        "UPDATE appointments SET comment = ? WHERE id = ?",
        text, appt_id,
    )


async def move_appointment(appt_id: int, doctor_id: str, doctor: str,
                           starts_at: datetime, when: str = "",
                           rooms: dict | None = None,
                           room: str | None = None) -> str:
    """Перенос визита на другое время и/или к другому врачу (перетаскивание).

    Ответ — КОД, а не bool: у переноса четыре разных отказа, и один «False» на
    все заставил бы журнал гадать, что показать регистратуре.
    `''` — перенесено; `conflict` — интервал занят у врача; `dup` — у пациента
    уже есть запись ровно на этот час; `gone` — записи больше нет;
    `closed` — визит не активен (завершён/отменён), такие не двигаем.

    ⚠️ Проверки те же и в том же порядке, что у новой брони, и обязательно ПОД
    `_slot_lock`: уникальные индексы ловят только совпадающие старты, а
    пересечение 10:00(60′) с 10:30(60′) — нет.
    ⚠️ `when` — время НОВОГО старта в часах клиники, уже строкой: db не знает
    про часовой пояс (в базе UTC), а летопись читает человек.
    `rooms` — кабинеты врача, К КОТОРОМУ переносят; `room` — назначенный
    кабинет. Без него у того же врача запись держит свой кабинет (занят — первый
    свободный). Без `rooms` кабинет записи не трогается.
    """
    async with _slot_lock():
        rows = await _fetch(
            """SELECT patient_id, duration_min, status, service, starts_at,
                      doctor_id, room_id
               FROM appointments WHERE id = ?""", appt_id)
        if not rows:
            return "gone"
        r = rows[0]
        if r["status"] not in ACTIVE_STATUSES:
            return "closed"
        dur = int(r["duration_min"] or 60)
        own = tuple((rooms or {}).get("own") or ())
        stay = _lane(r["room_id"], own) if r["doctor_id"] == doctor_id else None
        lane = await _pick_room(doctor_id, doctor, starts_at, dur, rooms, room,
                                prefer=stay, exclude_id=appt_id)
        if lane is None:
            return "conflict"
        if r["patient_id"] and await _patient_busy(
                r["patient_id"], doctor_id, doctor, starts_at, dur,
                exclude_id=appt_id):
            return "dup"
        # ⚠️ Перенос ВРЕМЕНИ снимает отметки напоминаний. Флаг значит «пациенту
        # уже сказали про ЭТОТ час», а час стал другим: без сброса журнал рядом
        # с перенесённым визитом показывал бы «Reminder trimis» про прежний час.
        # (Флаги ставил Telegram-бот, удалён 03.11.2026; у старых визитов они
        # остались.)
        # Переезд к другому врачу в тот же час отметку не трогает: про час
        # сказано верно, а имя врача напоминание берёт актуальное.
        moved = rows[0]["starts_at"] != starts_at
        rem_lite =", reminded_day = 0, reminded_2h = 0" if moved else ""
        room_lite, room_args = "", ()
        if rooms is not None:
            room_lite = ", room_id = ?, room = ?"
            room_args = (lane or None, _room_label(rooms, lane))
        try:
            await _execute(
                f"""UPDATE appointments SET doctor = ?, doctor_id = ?,
                   starts_at = ?{rem_lite}{room_lite} WHERE id = ?""",
                doctor, doctor_id, _iso(starts_at), *room_args, appt_id,
            )
        except Exception as e:  # noqa: BLE001 — uq_doctor_slot/uq_patient_slot
            if "uq_" in str(e) or "unique" in str(e).lower():
                await db._CONN.rollback()
                return "conflict"
            raise
        if r["patient_id"]:
            await log_event(r["patient_id"], "appt_move",
                            f"Vizită mutată: {when} · {doctor} — {r['service']}")
        return ""


async def set_appt_service(appt_id: int, service_id: str, service: str,
                           duration_min: int, rooms: dict | None = None) -> str:
    """Смена процедуры у стоящей записи (22.10): ключ услуги, СНИМОК подписи и
    СНИМОК длительности — те же три колонки, что пишет бронь.
    ⭐ Длительность, заданную руками (`duration_set`, 10.11), смена процедуры
    НЕ трогает: присланная `duration_min` тогда игнорируется.

    Ответ — КОД, как у переноса: `''` — сменено (или уже та же услуга);
    `gone` — записи нет; `closed` — визит не активен; `conflict` — выросшая
    длительность наезжает на соседа у того же врача.
    ⚠️ Состояние перечитывается ПОД `_slot_lock`, а не берётся у вызывающего:
    пока регистратура выбирала услугу, вторая вкладка могла завершить визит,
    поставить соседа вплотную или уже сменить процедуру. Наезд спрашиваем у
    ДАННЫХ (`_conflicts`) до записи — текст ошибки движка индекс не называет.
    ⚠️ Проверка наезда — только когда визит ДЛИННЕЕ прежнего: короче или
    столько же — он лежит внутри уже занятого им интервала, и отказ «занято»
    из-за чужой старой ошибки (наезд, записанный до 08-13) не дал бы даже
    сократить визит.
    ⛔ Заметку стойки (`source='note'`) здесь не тронуть: у неё в `service`
    лежит ТЕКСТ заметки, а не процедура; правило вызывающего её не пропускает,
    а условие ниже держит то же на уровне данных.
    """
    async with _slot_lock():
        rows = await _fetch(
            """SELECT patient_id, doctor, doctor_id, starts_at, duration_min,
                      duration_set, status, source, service, service_id, room_id
               FROM appointments WHERE id = ?""", appt_id)
        if not rows or rows[0]["source"] == "note":
            return "gone"
        r = rows[0]
        if r["status"] not in ACTIVE_STATUSES:
            return "closed"
        if r["service_id"] == service_id:
            return ""
        if r["duration_set"]:
            # ⭐ Длительность задана руками (10.11, `duration_set`): клиника
            # поставила её сознательно, процедура её не перебивает. Тот же
            # интервал — проверять соседа нечего (условие ниже не сработает).
            duration_min = int(r["duration_min"] or 60)
        if duration_min > int(r["duration_min"] or 60) and await _conflicts(
                r["doctor_id"], r["doctor"], r["starts_at"], duration_min,
                exclude_id=appt_id, rooms=rooms, room=_own_room(r, rooms)):
            return "conflict"
        await _execute(
            """UPDATE appointments SET service = ?, service_id = ?, duration_min = ?
               WHERE id = ? AND source != 'note'""",
            service, service_id, duration_min, appt_id)
        if r["patient_id"]:
            # «›», а не стрелка: стрелки нет во вшитом шрифте (CLAUDE.md)
            await log_event(r["patient_id"], "appt_service",
                            f"Procedura schimbată: {r['service']} › {service}")
        return ""


async def set_appt_duration(appt_id: int, minutes: int,
                            rooms: dict | None = None) -> str:
    """Длительность стоящей записи руками (10.11.2026, жалоба пилота:
    «Consultație 15′, а пациенту нужно 30′»). Коды — как у
    `set_appt_service`: `''` — сделано (или уже столько же), `gone`, `closed`,
    `conflict` — выросший визит наезжает на соседа у того же врача.

    ⭐ Ставит `duration_set`: дальше смена процедуры длительность не трогает.
    ⚠️ Тот же порядок, что у процедуры: строка перечитывается ПОД
    `_slot_lock`, сосед спрашивается у ДАННЫХ (`_conflicts`) и только когда
    визит ДЛИННЕЕ — короче он лежит внутри уже занятого интервала.
    ⚠️ Та же длительность — тихий успех БЕЗ записи: пересохранение без правки
    обязано быть тождественным (прайор 08-16), ни признака, ни летописи.
    ⛔ Заметку стойки не трогать — `gone`, и то же условие в UPDATE.
    """
    async with _slot_lock():
        rows = await _fetch(
            """SELECT patient_id, doctor, doctor_id, starts_at, duration_min,
                      status, source, service, room_id
               FROM appointments WHERE id = ?""", appt_id)
        if not rows or rows[0]["source"] == "note":
            return "gone"
        r = rows[0]
        if r["status"] not in ACTIVE_STATUSES:
            return "closed"
        was = int(r["duration_min"] or 60)
        if minutes == was:
            return ""
        if minutes > was and await _conflicts(
                r["doctor_id"], r["doctor"], r["starts_at"], minutes,
                exclude_id=appt_id, rooms=rooms, room=_own_room(r, rooms)):
            return "conflict"
        await _execute(
            """UPDATE appointments SET duration_min = ?, duration_set = 1
               WHERE id = ? AND source != 'note'""", minutes, appt_id)
        if r["patient_id"]:
            await log_event(r["patient_id"], "appt_duration",
                            f"Durata schimbată: {was} › {minutes} min — {r['service']}")
        return ""


async def set_status(appt_id: int, status: str,
                     rooms: dict | None = None) -> str:
    """'' = получилось. Иначе КОД отказа, и их два разных:

    * 'conflict' — час занят У ВРАЧА (вернули визит, а слот уже отдан другому);
    * 'dup' — у ПАЦИЕНТА уже есть активная запись на этот час.

    ⚠️ Разница не косметическая. Регистратура, прочитавшая «интервал занят у
    этого медика» про час, который у медика свободен, чинить ничего не может:
    занят он у пациента, и переносить надо ЧАС. Ровно эта подмена уже записана
    в грабли для _book.
    ⚠️ Причину спрашиваем У ДАННЫХ (`_patient_busy_at`, как это делает _book), а
    не разбираем текст исключения: два бэкенда пишут его по-разному, и ветка
    сообщения отмерла бы молча.
    """
    async with _slot_lock():
        rows = await _fetch(
            """SELECT patient_id, doctor, doctor_id, starts_at, duration_min,
                      status, room_id
               FROM appointments WHERE id = ?""", appt_id)
        r = rows[0] if rows else None
        if r and status in ACTIVE_STATUSES and r["status"] not in ACTIVE_STATUSES:
            # возврат в активный статус = та же пара проверок, что при новой
            # брони: uq-индексы ловят лишь совпадающие старты
            dur = int(r["duration_min"] or 60)
            # свой кабинет за это время могли занять — тогда в первый свободный
            lane = await _pick_room(r["doctor_id"], r["doctor"], r["starts_at"],
                                    dur, rooms, prefer=_own_room(r, rooms),
                                    exclude_id=appt_id)
            if lane is None:
                return "conflict"
            if r["patient_id"] and await _patient_busy(
                    r["patient_id"], r["doctor_id"], r["doctor"],
                    r["starts_at"], dur, exclude_id=appt_id):
                return "dup"
            if rooms is not None and lane != (r["room_id"] or ""):
                await _execute(
                    "UPDATE appointments SET room_id = ?, room = ? WHERE id = ?",
                    lane or None, _room_label(rooms, lane), appt_id)
        try:
            # Штампы конвейера (08-13): «пришёл» и «зашёл в кабинет» пишутся в
            # сам визит — разница пары даёт время ожидания в приёмной.
            # ⚠️ Возврат в confirmed (reopen/промах «A venit») сбрасывает ОБА:
            # иначе мусорная пара от исправленного клика попала бы в среднее.
            if status == "waiting":
                await _execute(
                    "UPDATE appointments SET status = ?, waiting_at = ? WHERE id = ?",
                    status, _utcnow_iso(), appt_id,
                )
            elif status == "arrived":
                await _execute(
                    "UPDATE appointments SET status = ?, arrived_at = ? WHERE id = ?",
                    status, _utcnow_iso(), appt_id,
                )
            elif status == "confirmed":
                await _execute(
                    """UPDATE appointments SET status = ?,
                       waiting_at = NULL, arrived_at = NULL WHERE id = ?""",
                    status, appt_id,
                )
            else:
                await _execute(
                    "UPDATE appointments SET status = ? WHERE id = ?",
                    status, appt_id,
                )
            own = await _fetch(
                "SELECT patient_id, service FROM appointments WHERE id = ?", appt_id)
            if own and own[0]["patient_id"]:
                # статус визита зовётся ОДНИМ словом на всю программу
                # (см. log_event): свой словарь тут уже расходился с журналом —
                # кнопка ставила «nu a venit», а летопись писала «neprezentare»
                from ..core.layout import STATUS_LABEL
                await log_event(own[0]["patient_id"], "appt_status",
                                f"Vizită {STATUS_LABEL.get(status, status)}: "
                                f"{own[0]['service']}")
            return ""
        except Exception as e:  # noqa: BLE001 — uq_doctor_slot/uq_patient_slot
            if "uq_" in str(e) or "unique" in str(e).lower():
                await db._CONN.rollback()
                # ⚠️ КАКОЙ индекс сработал, движок в тексте не называет —
                # спрашиваем данные. Под УЗКОЙ страховкой (шаг 4 не доложен)
                # сюда доходит и переход между активными статусами.
                if r and r["patient_id"] and await _patient_busy_at(
                        r["patient_id"], r["starts_at"], exclude_id=appt_id):
                    return "dup"
                return "conflict"
            raise


def _own_room(r, rooms: dict | None) -> str | None:
    """Кабинет, где запись стоит сейчас; None — у врача кабинетов нет."""
    return _lane(r["room_id"], tuple((rooms or {}).get("own") or ())) or None


async def set_appt_room(appt_id: int, room: str, rooms: dict | None) -> str:
    """Перевод стоящей записи в другой кабинет её врача. Коды — как у
    длительности: `''` — сделано (или запись уже там, тогда без записи и без
    летописи), `gone` (и для заметки стойки), `closed`, `bad_room`,
    `conflict` — в этом кабинете у врача на это время уже стоит запись."""
    async with _slot_lock():
        rows = await _fetch(
            """SELECT patient_id, doctor, doctor_id, starts_at, duration_min,
                      status, source, service, room_id
               FROM appointments WHERE id = ?""", appt_id)
        if not rows or rows[0]["source"] == "note":
            return "gone"
        r = rows[0]
        if r["status"] not in ACTIVE_STATUSES:
            return "closed"
        own = tuple((rooms or {}).get("own") or ())
        if not room or room not in own:
            return "bad_room"
        was = _lane(r["room_id"], own)
        if was == room:
            return ""
        if await _conflicts(r["doctor_id"], r["doctor"], r["starts_at"],
                            int(r["duration_min"] or 60), exclude_id=appt_id,
                            rooms=rooms, room=room):
            return "conflict"
        await _execute(
            """UPDATE appointments SET room_id = ?, room = ?
               WHERE id = ? AND source != 'note'""",
            room, _room_label(rooms, room), appt_id)
        if r["patient_id"]:
            await log_event(
                r["patient_id"], "appt_room",
                f"Cabinet schimbat: {_room_label(rooms, was)} › "
                f"{_room_label(rooms, room)} — {r['service']}")
        return ""
