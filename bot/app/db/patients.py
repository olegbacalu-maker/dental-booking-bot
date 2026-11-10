"""Фиша пациента: поиск по ключу и телефону, поля, предупреждения.

`_fold`/`_digits` — та же свёртка диакритики и те же «только цифры», что
регистрирует в SQLite `schema.init` для серверного списка."""
from __future__ import annotations

import secrets

from .. import db
from .conn import _execute, _fetch, _fetchval, _utcnow_iso
from .events import log_event


async def patients_total() -> int:
    """Пуста ли картотека — вопрос лицензии (core/license.py): на пустой без
    файла стоит стена активации, на живой — отсчёт льготы.
    ⚠️ Не `patients_count`: то имя занято счётчиком ОТФИЛЬТРОВАННОГО списка
    ниже, и одноимённая функция молча перекрыла бы его (поймано 24.09)."""
    n = await _fetchval("SELECT count(*) FROM patients")
    return int(n or 0)


# ---------- пациенты и записи ----------

async def _upsert_patient(session_key: str, name: str, phone: str,
                          lang: str, birth_year: int | None) -> int:
    # Пустой телефон — NULL, и нормализация именно ЗДЕСЬ, в единственной точке
    # записи: строка '' прошла бы фильтр phone IS NOT NULL и совпала бы по
    # цифрам с любым другим безтелефонным (см. _patient_ids_by_digits)
    phone = phone or None
    await db._CONN.execute(
        """INSERT INTO patients(session_key, name, phone, lang, birth_year, created_at)
           VALUES(?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_key) DO UPDATE
             SET name = excluded.name, phone = excluded.phone, lang = excluded.lang,
                 birth_year = COALESCE(excluded.birth_year, patients.birth_year)""",
        (session_key, name, phone, lang, birth_year, _utcnow_iso()),
    )
    await db._CONN.commit()
    cur = await db._CONN.execute(
        "SELECT id FROM patients WHERE session_key = ?", (session_key,))
    row = await cur.fetchone()
    await cur.close()
    return row[0]


def manual_key(digits: str) -> str:
    """Ключ пациента, заведённого с рецепции, — ЕДИНСТВЕННОЕ место, где он
    собирается (08-20: раньше фиша и журнал собирали его каждый сам, и ветка
    «без телефона» жила только у фиши). С цифрами — склейка по номеру, как
    было всегда. Без цифр (галочка «fără telefon») склеивать не по чему — ключ
    уникальный, но того же вида: по префиксу manual: весь код узнаёт «заведён
    вручную».
    ⛔ f"manual:{digits}" с пустыми digits дал бы ОДИН ключ на всех
    безтелефонных: второй такой пациент молча склеился бы с первым, а
    _upsert_patient ещё и переписал бы имя — всплыло бы на подписываемой
    043/e с чужой одонтограммой."""
    return f"manual:{digits}" if digits else f"manual:c{secrets.token_hex(5)}"


async def _patient_ids_by_digits(digits: str) -> list[int]:
    """Пациенты, чей телефон совпадает ПО ЦИФРАМ — независимо от того, каким
    путём человек заведён (tg:… из бота, manual:… с рецепции). Телефон не
    ключ: семья делит номер, поэтому список, а решает вызывающий. Фильтр в
    Python, не в SQL: у SQLite нет regexp, а пациентов у клиники тысячи, не
    миллионы.
    ⛔ Пустые цифры — пустой ответ, и это сторож КЛАССА ошибки, а не удобство:
    пациент без телефона хранит NULL, но одна строка с phone='' (легаси, ручная
    правка базы) — и «все безтелефонные» совпали бы друг с другом по пустой
    строке: запись уехала бы первому попавшемуся."""
    if not digits:
        return []
    rows = await _fetch(
        "SELECT id, phone FROM patients WHERE phone IS NOT NULL")
    return [r["id"] for r in rows
            if "".join(ch for ch in (r["phone"] or "") if ch.isdigit()) == digits]


async def patient_name_by_phone(phone: str) -> str | None:
    """Имя ЕДИНСТВЕННОГО пациента с этим номером. None — ноль или несколько.

    Нужна журналу, чтобы предупредить регистратуру: визит ляжет в чужую
    карточку (08-10). Семейный номер — норма, ребёнка записывают на телефон
    родителя, и `admin_add` в этом случае пишет визит РОДИТЕЛЮ, молча выбрасывая
    набранное имя. Запретить нельзя — по телефону записывают десятки раз в день;
    значит надо сказать, в чью карточку легло."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    ids = await _patient_ids_by_digits(digits)
    if len(ids) != 1:
        return None
    rows = await _fetch("SELECT name FROM patients WHERE id = ?", ids[0])
    return rows[0]["name"] if rows else None


# ---------- список пациентов: поиск, фильтры, порядок и страница — в SQL ----------
#
# Экран «Pacienți» (`/api/patients`) и книга `/admin/patients.xlsx` отбирают
# ОДНОЙ выборкой: агрегаты (визиты, предупреждения, план, долг) — подзапросы,
# соединённые с patients, чтобы WHERE, ORDER BY и LIMIT считала база. Отбор
# словарём собирает модуль (`routes._pl_select`), статус строки выводит он же
# (`_pl_status`). ⭐ До 13.10 то же правило жило ещё и в Python старой страницы
# (паритет держал набор); она снята, и правило отбора теперь одно.


def _digits(s) -> str:
    """Только цифры — телефон «069-12 34» и «0691234» обязаны совпадать."""
    return "".join(ch for ch in (s or "") if ch.isdigit())


async def patient_id_by_key(session_key: str) -> int | None:
    """Есть ли уже пациент с таким ключом. Нужен до создания карточки вручную:
    `_upsert_patient` при совпадении ПЕРЕЗАПИСАЛ бы имя существующего, и
    «Ion Popescu» тихо стал бы «Ion P.» из-за общего семейного номера."""
    return await _fetchval(
        "SELECT id FROM patients WHERE session_key = ?", session_key)


async def create_patient(session_key: str, name: str, phone: str,
                         birth_year: int | None = None) -> int:
    """Карточка без визита: регистратура завела пациента заранее (звонок,
    первичный приём без времени). Остальные поля дописывает update_patient."""
    return await _upsert_patient(session_key, name, phone, "ro", birth_year)


async def set_archived(pid: int, on: bool) -> None:
    """Архивация пациента: скрывает из списков, историю не трогает."""
    await log_event(pid, "archive",
                    "Pacient arhivat" if on else "Pacient scos din arhivă")
    await _execute(
        "UPDATE patients SET archived = ? WHERE id = ?",
        int(on), pid,
    )


# Диакритика румынского: поиск «Balan» должен находить «Bălan» и наоборот.
_DIA = str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaissttAAISSTT")


def _fold(s: str) -> str:
    return (s or "").translate(_DIA).lower()


# публичное имя для модулей: таблица диакритики обязана быть ОДНА на программу,
# иначе список пациентов и поиск разойдутся в том, что считать «Bălan»
fold = _fold


async def patient_appointments(patient_id: int, limit: int = 20) -> list:
    """Визиты пациента, свежие первыми. Предел по умолчанию — 20: столько
    хватает боковому предпросмотру списка. Фише нужен ВЕСЬ список (она зовёт с
    limit=1000): на ней стоит цифра «визитов всего», и с двадцаткой она врала
    бы у давнего пациента."""
    return await _fetch(
        """SELECT id, service, doctor, starts_at, status, source, comment
           FROM appointments WHERE patient_id = ?
           ORDER BY starts_at DESC LIMIT ?""",
        patient_id, limit,
    )


# ---------- карточка пациента (v1.6.0: A2 зубы+план, A4 документы) ----------

PATIENT_FIELDS = ["name", "phone", "birth_date", "gender", "idnp", "email",
                  "address", "insurance", "primary_doctor", "file_no", "notes"]


async def get_patient(pid: int) -> dict | None:
    cols = ("id, session_key, name, phone, lang, birth_year, created_at, archived, sms_off, "
            "mkt_ok, mkt_at, mkt_src, "
            + ", ".join(PATIENT_FIELDS[2:]))
    rows = await _fetch(
        f"SELECT {cols} FROM patients WHERE id = ?", pid)
    return rows[0] if rows else None


async def update_patient(pid: int, data: dict) -> None:
    await log_event(pid, "profile", "Fișa pacientului a fost actualizată")
    """Обновление профиля: только известные поля, явным списком колонок."""
    sets_lt =", ".join(f"{f} = ?" for f in PATIENT_FIELDS)
    vals = [data.get(f) for f in PATIENT_FIELDS]
    await _execute(
        f"UPDATE patients SET {sets_lt} WHERE id = ?",
        *vals, pid,
    )


async def set_primary_doctor(pid: int, name: str | None) -> None:
    """Медик курант одним полем (шапка фиши, 14.10) — мимо `update_patient`,
    который пишет ВСЕ поля профиля и стёр бы остальные. None — снять."""
    await log_event(pid, "profile", f"Medic curant: {name}" if name else "Medic curant scos")
    await _execute("UPDATE patients SET primary_doctor = ? WHERE id = ?", name, pid)


# Согласие на маркетинг (10.11): ответ на «acorduri opționale › marketing» листа
# 195. Источников ДВА — перечислением: подпись листа на экране (`ecran`) и
# отметка регистратуры по бумажному листу (`manual`). Строка летописи — одна на
# оба места, готовой строкой.
MKT_SOURCES = ("ecran", "manual")
MKT_EVENT = {
    (True, "ecran"): "Acord marketing: DA (foaia Legea 195 semnată pe ecran)",
    (False, "ecran"): "Acord marketing: NU (foaia Legea 195 semnată pe ecran)",
    (True, "manual"): "Acord marketing: DA (marcat manual, foaie pe hârtie)",
    (False, "manual"): "Acord marketing: NU (marcat manual, foaie pe hârtie)",
}


async def set_mkt(pid: int, ok: bool, src: str) -> bool:
    """Ответ пациента о маркетинге. Летопись — вызывающий маршрут (он знает,
    откуда ответ). Ответ — изменилось ли что-то, кроме даты: тот же ответ тем
    же путём обновляет только дату (свежий лист — свежая отметка), но строки
    летописи не стоит. ⛔ «Не спрашивали» (NULL) сюда не пишется: снять ответ
    нельзя, только сменить."""
    if src not in MKT_SOURCES or not isinstance(ok, bool):
        raise ValueError("mkt")
    changed = await _execute(
        "UPDATE patients SET mkt_ok = ?, mkt_src = ? WHERE id = ? "
        "AND (mkt_ok IS NULL OR mkt_ok <> ? OR COALESCE(mkt_src, '') <> ?)",
        int(ok), src, pid, int(ok), src) > 0
    await _execute("UPDATE patients SET mkt_at = ? WHERE id = ?", _utcnow_iso(), pid)
    return changed


async def set_birth_year(pid: int, year: int | None) -> None:
    """Синк года из birth_date: возраст в поиске/сетке считается по birth_year.
    None стирает год — так очищенная дата рождения забирает с собой и возраст."""
    await _execute(
        "UPDATE patients SET birth_year = ? WHERE id = ?",
        year, pid,
    )


async def patient_alerts(pid: int) -> list:
    return await _fetch(
        "SELECT id, kind, text FROM patient_alerts WHERE patient_id = ? ORDER BY id", pid)


async def add_alert(pid: int, kind: str, text: str) -> None:
    await log_event(pid, "alert_add", f"Atenționare adăugată: {text}")
    await _execute(
        "INSERT INTO patient_alerts(patient_id, kind, text, created_at) VALUES(?, ?, ?, ?)",
        pid, kind, text, _utcnow_iso(),
    )


async def delete_alert(alert_id: int, pid: int) -> bool:
    """Снять предупреждение. След в летописи обязателен: снятая аллергия на
    пенициллин — клинически значимое событие, и «кто её снял» спросят громче,
    чем «кто записал» (до 24.09 удаление не оставляло строки вовсе). Летопись
    — ПОСЛЕ DELETE и только за реально снятую строку, как у `delete_bridge`.
    False — у пациента такого предупреждения нет (чужое, выдуманное, уже
    снятое с другого места)."""
    rows = await _fetch(
        "SELECT text FROM patient_alerts WHERE id = ? AND patient_id = ?", alert_id, pid)
    if not rows:
        return False
    n = await _execute(
        "DELETE FROM patient_alerts WHERE id = ? AND patient_id = ?", alert_id, pid)
    if n != 1:
        return False
    await log_event(pid, "alert_del", f"Atenționare ștearsă: {rows[0]['text']}")
    return True
