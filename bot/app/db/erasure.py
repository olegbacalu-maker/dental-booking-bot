"""Закон 195: что можно стереть, полное удаление и обезличивание."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from .. import db
from .conn import _execute, _fetch, _fetchval, _iso, _utcnow_iso, log
from .slots import _ACT_SQL


async def erasure_kind(pid: int) -> str:
    """'delete' — можно физически, 'anon' — только обезличивание.

    Лечением считается: запись о зубе, план, документ, визит со статусом
    done/arrived ЛИБО подтверждённый визит в прошлом (раз не отменён и не
    отмечен «не пришёл» — приём, скорее всего, состоялся, и вычеркнуть его —
    значит переписать медицинскую историю задним числом).
    ПЛАТЁЖ тоже держит фишу от физического удаления: деньги — финансовый след
    клиники, и вычеркнуть его — значит переписать кассу задним числом.
    """
    async def _n(sql: str, *a) -> int:
        return int(await _fetchval(sql, *a) or 0)

    pays = await _n("SELECT COUNT(*) FROM payments WHERE patient_id = ?", pid)
    teeth = await _n("SELECT COUNT(*) FROM teeth WHERE patient_id = ?", pid)
    plan = await _n("SELECT COUNT(*) FROM plan_items WHERE patient_id = ?", pid)
    docs = await _n("SELECT COUNT(*) FROM documents WHERE patient_id = ?", pid)
    # запись приёма — лечение по определению, даже если визит формально
    # будущий/отменённый: врач уже вписал клинический текст
    consult = await _n("SELECT COUNT(*) FROM visit_records WHERE patient_id = ?",
                       pid)
    # анамнез — медицинская запись: фиша с одним опросником обезличивается,
    # а не стирается физически
    anam = await _n("SELECT COUNT(*) FROM anamneza WHERE patient_id = ?", pid)
    # мост — протезная работа, то есть лечение: держит фишу от физического
    # стирания наравне с зубами и планом
    punti = await _n("SELECT COUNT(*) FROM bridges WHERE patient_id = ?", pid)
    # пародонтограмма — такая же медицинская запись, как зубы и дневник:
    # осмотр с измерениями держит фишу от физического стирания
    perio = await _n("SELECT COUNT(*) FROM perio_exams WHERE patient_id = ?",
                     pid)
    # прикус (26.10) — запись объективного осмотра, графа 043/e: медзапись,
    # как анамнез
    occl = await _n("SELECT COUNT(*) FROM ocluzie WHERE patient_id = ?", pid)
    now = datetime.now(timezone.utc)
    happened = await _n(
        """SELECT COUNT(*) FROM appointments WHERE patient_id = ?
           AND (status IN ('done','arrived','waiting')
                OR (status = 'confirmed' AND starts_at < ?))""",
        pid, _iso(now))
    return ("anon" if (teeth or plan or docs or happened or pays or consult
                       or anam or punti or perio or occl) else "delete")


# Таблицы, ссылающиеся на пациента, — в порядке удаления: дети раньше родителя
# (с foreign_keys=ON внешние ключи иначе откажут, без него остались бы сироты). Дневники
# приёмов стоят раньше визитов: FK на appointments. ⚠️ Состав обязан совпадать
# с export.py — обе стороны отвечают «где в базе лежит этот человек».
_PATIENT_CHILD_TABLES = ("payments", "activity", "patient_alerts", "teeth",
                         "teeth_history", "plan_items", "documents", "anamneza",
                         "ocluzie", "bridges", "bridges_removed", "recall_marks",
                         "perio_exams", "visit_records", "sms_log", "appointments")

# ⚠️ Внуки: таблицы, которые висят НЕ на пациенте, а на его записи. У
# `perio_teeth` нет patient_id вовсе, и общий шаблон «DELETE ... WHERE
# patient_id» её не касается. Каскад внешнего ключа сделал бы это сам, но
# полагаться на него нельзя: включённость `PRAGMA foreign_keys` — свойство
# СОЕДИНЕНИЯ, и на чужом (восстановление, ремонт базы, другой драйвер)
# измерения пережили бы стирание пациента молча. Удаляются ПЕРВЫМИ.
_PATIENT_GRAND_CHILDREN = (("perio_teeth", "exam_id", "perio_exams"),)


async def delete_patient_fully(pid: int) -> None:
    """Физическое удаление: строка пациента и ВСЁ, что на неё ссылается.

    Файлы документов на диске удаляет ВЫЗЫВАЮЩИЙ (маршрут): db не знает про
    раскладку файлов, и это его единственная граница.

    ⭐ АТОМАРНО (аудит 08-20). Раньше десять DELETE шли каждый со своим
    COMMIT, и обрыв посреди (питание, убитый процесс, залоченная база)
    оставлял ПОЛУпациента: платежи стёрты, фиша на месте — выглядит как
    «программа сама что-то удалила», а довершить нечем. Теперь либо целиком,
    либо ничего. У SQLite — executescript ОДНИМ вызовом: очередь aiosqlite
    исполняет его как одну операцию, чужой запрос не вклинится в середину и
    не закоммитит половину (у общего соединения commit общий). Параметров
    executescript не принимает, поэтому pid подставляется в текст — он int
    по построению, и int() рядом это закрепляет.
    """
    pid = int(pid)
    script = "BEGIN IMMEDIATE;\n" + "\n".join(
        [f"DELETE FROM {t} WHERE {key} IN "
         f"(SELECT id FROM {parent} WHERE patient_id = {pid});"
         for t, key, parent in _PATIENT_GRAND_CHILDREN]
        + [f"DELETE FROM {t} WHERE patient_id = {pid};"
           for t in _PATIENT_CHILD_TABLES]
    ) + f"\nDELETE FROM patients WHERE id = {pid};\nCOMMIT;"
    try:
        await db._CONN.executescript(script)
    except Exception:
        # обрыв посреди скрипта оставляет транзакцию открытой — вернуть
        # базу в исходное; вне транзакции rollback безвреден.
        # ⚠️ Принятый риск (ревью 08-22): между этим исключением и
        # rollback чужая операция очереди может успеть commit — общий
        # commit зафиксировал бы полу-удаление. Предусловие — сам скрипт
        # упал, а падает он только на уже-битой базе (диск, коррупция),
        # где атомарность уже не главная беда; отдельное соединение ради
        # этого окна не заводим.
        await db._CONN.rollback()
        raise
    log.warning("patient %s deleted (erasure request, no medical records)", pid)


async def anonymize_patient(pid: int) -> None:
    """Обезличивание: стереть, КТО это, оставив, ЧТО лечили.

    Стираются поля личности; клиника (зубы, план, визиты, документы-снимки)
    остаётся под номером фиши. session_key получает вид 'anon:<id>' —
    колонка UNIQUE NOT NULL, а прежний ключ содержит телефон или tg-id, то
    есть сам по себе личность. archived ставится тут же: обезличенная фиша
    не должна показываться в живых списках.

    ⚠️ Комментарии визитов и заметки стираются тоже: это свободный текст, и
    рецепция пишет туда что угодно — вплоть до «сестра Иона Попеску».
    Дневник приёма (visit_records) НЕ трогаем: acuze/diagnostic/tratament —
    та самая клиническая запись, ради которой фиша и хранится под номером.
    """
    await _execute(
        """UPDATE patients SET name = ?, phone = NULL, email = NULL,
             birth_date = NULL, birth_year = NULL, gender = NULL, idnp = NULL,
             address = NULL, insurance = NULL, notes = NULL,
             mkt_ok = NULL, mkt_at = NULL, mkt_src = NULL,
             session_key = ?, archived = 1 WHERE id = ?""",
        f"Pacient anonimizat #{pid}", f"anon:{pid}", pid)
    # платежи остаются (касса клиники под номером фиши), но заметка платежа —
    # свободный текст рецепции, то есть потенциально личность: стираем
    await _execute("UPDATE payments SET note = '' WHERE patient_id = ?", pid)
    await _execute(
        "UPDATE appointments SET comment = '' WHERE patient_id = ?", pid)
    # Будущие живые записи — отменяются (17.10, посторонний разбор): человека
    # больше нет, звонить некому, а час у врача оставался занятым, и
    # «Pacient anonimizat #N» без телефона висел в «De confirmat — sunați».
    # Прошлое не трогаем: состоявшийся приём — медицинская история под номером.
    await _execute(
        f"""UPDATE appointments SET status = 'cancelled'
            WHERE patient_id = ? AND status IN {_ACT_SQL} AND starts_at > ?""",
        pid, _utcnow_iso())
    # летопись — тот же свободный текст ЭХОМ: log_event дублирует туда заметку
    # платежа («Plată 500 MDL — transfer de la fratele …») и имя загруженного
    # файла. Строки пациента удаляются целиком, как в delete_patient_fully;
    # платёжные данные живут в payments и остаются. Событие «erase» пишет
    # вызывающий маршрут ПОСЛЕ — след стирания в летописи сохраняется.
    await _execute("DELETE FROM activity WHERE patient_id = ?", pid)
    # журнал SMS — номер телефона и день визита, то есть личность и ничего из
    # лечения: уходит целиком, как летопись (S5)
    await _execute("DELETE FROM sms_log WHERE patient_id = ?", pid)
    # имя документа дал человек («radiografie-popescu.png») — это личность;
    # сам снимок остаётся (это ЧТО лечили), скрытое имя на диске и так hex.
    # Расширение сохраняем: по нему работает белый список открытия (_OPEN_EXT)
    for d in await _fetch(
            "SELECT id, stored_path FROM documents WHERE patient_id = ?", pid):
        neutral = f"document-{d['id']}{os.path.splitext(d['stored_path'])[1]}"
        await _execute(
            "UPDATE documents SET filename = ? WHERE id = ?",
            neutral, d["id"])
    log.warning("patient %s anonymized (erasure request, has medical records)", pid)
