"""Медзаписи фиши: дневник визита, анамнез, прикус, язык печатных листов."""
from __future__ import annotations

from .conn import _execute, _fetch, _fetchval, _utcnow_iso
from .events import _actor_now, log_event


# ---------- дневник визита (consultația) ----------
# Запись приёма 1:1 к визиту: acuze / examen / diagnostic / tratament /
# recomandari — графы дневника формы 043/e. Кнопки удаления НЕТ намеренно:
# медзапись правится (updated_at + author), но не исчезает; обе версии
# события остаются в летописи.

VISIT_FIELDS = ("acuze", "examen", "diagnostic", "tratament", "recomandari")


async def appointment_brief(appt_id: int) -> dict | None:
    """Один визит с именем пациента — шапка страницы консультации.
    patient_id отсюда — источник истины «чей визит»: маршруты обязаны брать
    его из этой выборки, а не из формы."""
    rows = await _fetch(
        """SELECT a.id, a.patient_id, a.service, a.doctor, a.doctor_id,
                  a.service_id, a.starts_at, a.duration_min, a.status, a.source,
                  a.comment, p.name
           FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id
           WHERE a.id = ?""", appt_id)
    return rows[0] if rows else None


async def visit_record(appt_id: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, appointment_id, patient_id, doctor, acuze, examen,
                  diagnostic, tratament, recomandari, author, created_at,
                  updated_at
           FROM visit_records WHERE appointment_id = ?""", appt_id)
    return rows[0] if rows else None


async def save_visit_record(appt_id: int, pid: int, doctor: str,
                            fields: dict) -> str:
    """Upsert записи приёма; возвращает 'created' | 'updated'.
    author — последний редактировавший; кто вписал первым, видно в летописи."""
    vals = tuple((fields.get(k) or "").strip() for k in VISIT_FIELDS)
    actor = _actor_now()
    existing = await _fetchval(
        "SELECT id FROM visit_records WHERE appointment_id = ?", appt_id)
    result = "created" if existing is None else "updated"
    # один upsert, а не SELECT+ветка: два открытых окна консультации иначе
    # вставляют наперегонки, и второе падает на UNIQUE(appointment_id).
    # created_at при обновлении не трогаем
    # (в SET его нет), гонка может лишь перепутать глагол в летописи
    await _execute(
        """INSERT INTO visit_records(appointment_id, patient_id, doctor,
             acuze, examen, diagnostic, tratament, recomandari, author,
             created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(appointment_id) DO UPDATE SET
             doctor = excluded.doctor, acuze = excluded.acuze,
             examen = excluded.examen, diagnostic = excluded.diagnostic,
             tratament = excluded.tratament,
             recomandari = excluded.recomandari,
             author = excluded.author, updated_at = ?""",
        appt_id, pid, doctor, *vals, actor, _utcnow_iso(),
                _utcnow_iso(),
    )
    # в летопись — самое информативное из заполненного: диагноз, лечение, жалобы
    snippet = next((v for v in (vals[2], vals[3], vals[0]) if v), "")
    verb = "Consultație" if result == "created" else "Consultație actualizată"
    await log_event(pid, "consult", f"{verb}: {snippet[:120] or '—'}")
    return result


# ---------- анамнез (опросник пациента) ----------
# Один на пациента, правится, не удаляется — как дневник визита. Это МЕДДАННЫЕ:
# держит фишу от физического стирания и переживает обезличивание под номером
# фиши (см. erasure_kind / anonymize_patient).

ANAMNEZA_FIELDS = ("boli", "medicamente", "alergii", "anestezie")


async def set_patient_lang(pid: int, lang: str) -> None:
    """Язык пациента — отдельным маршрутом, а НЕ через PATIENT_FIELDS:
    там пустое поле превращается в NULL, а колонка NOT NULL DEFAULT 'ro'."""
    if lang not in ("ro", "ru"):
        return
    await _execute("UPDATE patients SET lang = ? WHERE id = ?",
                   lang, pid)


async def anamneza(pid: int) -> dict | None:
    rows = await _fetch(
        """SELECT patient_id, flags, boli, medicamente, alergii, anestezie,
                  author, created_at, updated_at
           FROM anamneza WHERE patient_id = ?""", pid)
    return rows[0] if rows else None


async def save_anamneza(pid: int, flags: str, fields: dict) -> str:
    """Upsert опросника; возвращает 'created' | 'updated'."""
    vals = tuple((fields.get(k) or "").strip()[:500] for k in ANAMNEZA_FIELDS)
    actor = _actor_now()
    existed = await _fetchval(
        "SELECT 1 FROM anamneza WHERE patient_id = ?", pid)
    await _execute(
        """INSERT INTO anamneza(patient_id, flags, boli, medicamente, alergii,
             anestezie, author, created_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(patient_id) DO UPDATE SET
             flags = excluded.flags, boli = excluded.boli,
             medicamente = excluded.medicamente, alergii = excluded.alergii,
             anestezie = excluded.anestezie, author = excluded.author,
             updated_at = ?""",
        pid, flags, *vals, actor, _utcnow_iso(), _utcnow_iso(),
    )
    await log_event(pid, "anamneza",
                    "Anamneza actualizată" if existed else "Anamneza completată")
    return "updated" if existed else "created"


# Поля записи прикуса — в порядке колонок; маршрут принимает только их.
OCLUZIE_FIELDS = ("angle_dr", "angle_st", "overjet", "overbite", "incrucisata",
                  "deschisa", "mediana_mm", "mediana_spre", "nota", "doctor")


async def ocluzie(pid: int) -> dict | None:
    rows = await _fetch(
        f"""SELECT patient_id, {", ".join(OCLUZIE_FIELDS)}, author, created_at,
                   updated_at
            FROM ocluzie WHERE patient_id = ?""", pid)
    return rows[0] if rows else None


async def save_ocluzie(pid: int, fields: dict, prev_line: str = "") -> str:
    """Upsert записи прикуса; возвращает 'created' | 'updated'. `fields` —
    УЖЕ слитые с прежней записью значения всех OCLUZIE_FIELDS (правило
    «не сообщали ≠ стереть» живёт у маршрута, здесь пишется всё).
    `prev_line` — прежняя запись готовой строкой: при перезаписи она уходит
    в летопись, чтобы история прикуса не пропадала молча (летопись хранит
    готовое, разбирать её назад никто не будет)."""
    vals = tuple((fields.get(k) or "") for k in OCLUZIE_FIELDS)
    actor = _actor_now()
    existed = await _fetchval("SELECT 1 FROM ocluzie WHERE patient_id = ?", pid)
    sets = ", ".join(f"{k} = excluded.{k}" for k in OCLUZIE_FIELDS)
    await _execute(
        f"""INSERT INTO ocluzie(patient_id, {", ".join(OCLUZIE_FIELDS)}, author,
                                created_at)
            VALUES(?, {", ".join("?" * len(OCLUZIE_FIELDS))}, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET {sets},
              author = excluded.author, updated_at = ?""",
        pid, *vals, actor, _utcnow_iso(), _utcnow_iso(),
    )
    text = "Ocluzia actualizată" if existed else "Ocluzia înregistrată"
    if existed and prev_line:
        text += f" (anterior: {prev_line})"
    await log_event(pid, "ocluzie", text)
    return "updated" if existed else "created"


async def visit_records_map(pid: int) -> dict[int, dict]:
    """appointment_id → запись приёма: фиша красит историю визитов одним
    запросом, а не по одному на строку."""
    rows = await _fetch(
        """SELECT appointment_id, doctor, acuze, examen, diagnostic, tratament,
                  recomandari, author, created_at, updated_at
           FROM visit_records WHERE patient_id = ?""", pid)
    return {r["appointment_id"]: r for r in rows}


async def patient_visit_records(pid: int) -> list:
    """Записи приёмов с датой и услугой визита — для выгрузки данных пациента.

    ⚠️ `a.status` отдаётся вместе с записью и НЕ фильтруется здесь: копия по
    195-му обязана содержать всё, что клиника о пациенте хранит. Отсеивает
    отменённое и неявки печатный бланк 043/e — там строка читается как
    проведённое лечение (см. fisa043.render).
    """
    return await _fetch(
        """SELECT a.starts_at, a.service, a.status, v.doctor, v.acuze, v.examen,
                  v.diagnostic, v.tratament, v.recomandari, v.author,
                  v.created_at, v.updated_at
           FROM visit_records v JOIN appointments a ON a.id = v.appointment_id
           WHERE v.patient_id = ? ORDER BY a.starts_at DESC""", pid)
