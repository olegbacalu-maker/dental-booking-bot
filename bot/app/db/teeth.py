"""Одонтограмма: зубы, история зубов по состояниям, мосты."""
from __future__ import annotations

from datetime import datetime, timezone

from .. import db
from .conn import _fetch, _iso, _parse_dt, _utcnow_iso, get_meta, log
from .events import log_event
from .slots import _slot_lock


# Ключ schema_meta: с какого мгновения `teeth_history` полная (ставит шаг 6).
TEETH_HIST_SINCE = "teeth_hist_since"


async def teeth_map(pid: int) -> dict:
    rows = await _fetch(
        """SELECT tooth, state, note, doctor, surfaces, surface_states, marks,
                  updated_at FROM teeth WHERE patient_id = ?""",
        pid)
    return {r["tooth"]: r for r in rows}


async def teeth_hist_since() -> datetime | None:
    """Начало истории зубов (UTC); None — метки нет, и тогда карту на дату не
    знаем НИКОГДА: «нет данных» честнее догадки."""
    v = await get_meta(TEETH_HIST_SINCE)
    try:
        return _parse_dt(v) if v else None
    except ValueError:
        log.warning("%s unreadable: %r", TEETH_HIST_SINCE, v)
        return None


async def teeth_map_at(pid: int, before: datetime) -> dict:
    """Карта зубов (вид `teeth_map`) такой, какой она была до мгновения
    `before`: последний снимок каждого зуба из `teeth_history`. Верна только
    при `before` не раньше `teeth_hist_since()` — это проверяет вызывающий.
    ⚠️ Последний — по id, а не по `at`: снимки дописываются по ходу записи, и
    id растёт вместе с ними даже там, где часы машины шагнули назад."""
    rows = await _fetch(
        """SELECT tooth, state, note, doctor, surfaces, surface_states, marks,
                  at AS updated_at FROM teeth_history
           WHERE id IN (SELECT MAX(id) FROM teeth_history
                        WHERE patient_id = ? AND at < ? GROUP BY tooth)
             AND state IS NOT NULL""", pid, _iso(before))
    return {r["tooth"]: r for r in rows}


async def teeth_history_rows(pid: int) -> list:
    """История зубов пациента целиком, по порядку записи — выгрузка по 195-му
    (состав выгрузки = состав удаления, `_PATIENT_CHILD_TABLES`). `state`
    None — строки зуба не было (здоров); `src` 'base' — снимок шага 6."""
    return await _fetch(
        """SELECT tooth, at, state, note, doctor, surfaces, surface_states, marks, src
           FROM teeth_history WHERE patient_id = ? ORDER BY id""", pid)


async def bridges_removed_rows(pid: int) -> list:
    """Снятые мосты пациента — выгрузка по 195-му, как `teeth_history_rows`."""
    return await _fetch(
        """SELECT bridge_id, teeth, material, doctor, created_at, removed_at
           FROM bridges_removed WHERE patient_id = ? ORDER BY id""", pid)


async def bridges_at(pid: int, before: datetime) -> list:
    """Мосты (вид `bridges`), стоявшие до мгновения `before`: поставленные
    раньше и ещё стоящие плюс снятые позже. Мост, снятый до начала истории,
    к такому мгновению уже не стоял — для дат после `teeth_hist_since()`
    ответ полный."""
    b = _iso(before)
    return await _fetch(
        """SELECT id, teeth, material, doctor, created_at FROM bridges
           WHERE patient_id = ? AND created_at < ?
           UNION ALL
           SELECT bridge_id AS id, teeth, material, doctor, created_at
           FROM bridges_removed
           WHERE patient_id = ? AND created_at < ? AND removed_at >= ?
           ORDER BY id""", pid, b, pid, b, b)


async def set_tooth(pid: int, tooth: int, state: str, note: str,
                    doctor: str = "", surfaces: str | None = None,
                    sfmap: dict | None = None, state0: str | None = None,
                    marks: list | None = None) -> None:
    """Запись одного зуба (`POST /api/patients/{pid}/teeth/{n}`). Что ляжет в
    строку и в летопись, решает `_tooth_next`; замок — тот же, что у записи
    пачкой (`set_teeth`): иначе одиночная запись вклинилась бы между её
    сверкой и записью, и пачка молча переписала бы чужое."""
    async with _slot_lock():
        rows = await _fetch(
            """SELECT state, note, doctor, surfaces, surface_states, marks FROM teeth
               WHERE patient_id = ? AND tooth = ?""", pid, tooth)
        row, txt = _tooth_next(rows[0] if rows else None, tooth, state, note, doctor,
                               surfaces, sfmap, state0, marks)
        await _put_tooth(pid, tooth, row, _utcnow_iso())
        await db._CONN.commit()
    await log_event(pid, "tooth", txt, tooth=tooth)


async def _put_tooth(pid: int, tooth: int, row: dict | None, at: str) -> None:
    """Строка зуба по решению `_tooth_next` — БЕЗ commit: его делает
    вызывающий (одна запись или вся пачка разом).

    ⭐ Здесь же — снимок в `teeth_history` («сравнить с визитом», 25.10): в той
    же транзакции и под тем же замком, что строка зуба, поэтому история и
    карта не расходятся ни на одной записи. `None` — строки зуба нет."""
    v = (row["state"], row["note"], row["doctor"], row["surfaces"],
         row["surface_states"], row["marks"]) if row else (None, "", "", "", "", "")
    await db._CONN.execute(
        """INSERT INTO teeth_history(patient_id, tooth, at, state, note, doctor,
                                     surfaces, surface_states, marks)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""", (pid, tooth, at, *v))
    if row is None:
        await db._CONN.execute("DELETE FROM teeth WHERE patient_id = ? AND tooth = ?",
                            (pid, tooth))
        return
    await db._CONN.execute(
        """INSERT INTO teeth(patient_id, tooth, state, note, doctor, surfaces,
                             surface_states, marks, updated_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(patient_id, tooth) DO UPDATE
             SET state = excluded.state, note = excluded.note,
                 doctor = excluded.doctor, surfaces = excluded.surfaces,
                 surface_states = excluded.surface_states,
                 marks = excluded.marks,
                 updated_at = excluded.updated_at""",
        (pid, tooth, row["state"], row["note"], row["doctor"], row["surfaces"],
         row["surface_states"], row["marks"], at))


async def set_teeth(pid: int, items: list[dict]) -> int | None:
    """Запись НЕСКОЛЬКИХ зубов одним действием («Salvează tot», волна 2
    одонтограммы, 25.10): None — записаны все; номер — зуб, который изменился
    с тех пор, как экран начал его править, и тогда НЕ записано НИЧЕГО.

    `items` — те же поля, что у `set_tooth` (`tooth`, `state`, `note`,
    `doctor`, `surfaces`, `sfmap`, `state0`, `marks`), плюс `base` — каким
    экран ПОКАЗАЛ зуб, когда начал правку (`state`, `sfst`, `marks`,
    `doctor`, `note`). Сверка — с той же выжимкой строки, что едет экрану
    (`teeth_svg.tooth_fields`), поэтому «не менялся» значит «выглядел бы так
    же», а не «тот же updated_at».

    Сверка и запись — под ОДНИМ `_slot_lock` (его берёт и `set_tooth`):
    иначе чужая запись встала бы между ними. Строки — одной транзакцией, один
    commit в конце, при исключении rollback.
    ⚠️ Принятый риск (тот же, что у `delete_patient_fully`): соединение
    aiosqlite общее, и чужой `_execute` между нашими await может закоммитить
    часть пачки раньше; разорвать её может только ошибка диска посреди записи.
    Откаты чужих операций в рабочем пути идут под тем же замком или после
    упавшей операции. Отдельное соединение ради этого окна не заводим.
    Летопись — как у одиночной записи: строка на зуб через `log_event` после
    commit (журнал не роняет запись)."""
    from ..teeth_svg import tooth_fields
    nums = [it["tooth"] for it in items]
    async with _slot_lock():
        rows = await _fetch(
            f"""SELECT tooth, state, note, doctor, surfaces, surface_states, marks
                FROM teeth WHERE patient_id = ? AND tooth IN ({','.join('?' * len(nums))})""",
            pid, *nums)
        prev = {r["tooth"]: r for r in rows}
        for it in items:
            if not _same_tooth(tooth_fields(prev.get(it["tooth"])), it["base"]):
                return it["tooth"]
        plan = [(it["tooth"], *_tooth_next(prev.get(it["tooth"]), it["tooth"], it["state"],
                                           it["note"], it["doctor"], it["surfaces"], it["sfmap"],
                                           it["state0"], it["marks"]))
                for it in items]
        at = _utcnow_iso()
        try:
            for tooth, row, _txt in plan:
                await _put_tooth(pid, tooth, row, at)
            await db._CONN.commit()
        except Exception:
            await db._CONN.rollback()
            raise
        for tooth, _row, txt in plan:
            await log_event(pid, "tooth", txt, tooth=tooth)
    return None


def _same_tooth(cur: dict, base: dict) -> bool:
    """Выжимка строки (`tooth_fields`) против того, что экран прислал как
    `base`: отметки — набором, поверхности — без пустых значений."""
    return (cur["state"] == base["state"] and cur["note"] == base["note"]
            and cur["doctor"] == base["doctor"]
            and sorted(cur["mk"]) == sorted(base["marks"])
            and {k: v for k, v in cur["sfst"].items() if v}
            == {k: v for k, v in base["sfst"].items() if v})


async def preview_teeth(pid: int, items: list[dict]) -> dict:
    """Карта зубов (`teeth_map`) такой, какой её сделала бы запись `items`, —
    БЕЗ записи: ни строки зуба, ни летописи. Решает тот же `_tooth_next`, что
    у записи, поэтому предпросмотр экрана и записанное не расходятся."""
    tmap = await teeth_map(pid)
    now = datetime.now(timezone.utc)
    for it in items:
        n = it["tooth"]
        row, _txt = _tooth_next(tmap.get(n), n, it["state"], it["note"], it["doctor"],
                                it["surfaces"], it["sfmap"], it["state0"], it["marks"])
        if row is None:
            tmap.pop(n, None)
        else:
            tmap[n] = {"tooth": n, **row, "updated_at": now}
    return tmap


def _tooth_next(prev: dict | None, tooth: int, state: str, note: str, doctor: str,
                surfaces: str | None, sfmap: dict | None, state0: str | None,
                marks: list | None) -> tuple[dict | None, str]:
    """(строка зуба | None — строку удалить, строка летописи) — чистое решение
    записи по прежней строке `prev`. Его зовут запись (`set_tooth`,
    `set_teeth`) и предпросмотр (`preview_teeth`).

    'ok' без заметки и без врача = зуб здоров → строка удаляется (карта sparse).
    doctor — СНАПШОТ имени на момент записи, как в plan_items: переименование
    врача не должно переписывать историю зуба.
    surfaces — буквы поверхностей одной строкой («MOD»); проверяет маршрут.
    sfmap — {поверхность: состояние}, когда они РАЗНЫЕ.
    state0 — состояние в том виде, В КАКОМ ЕГО ПОКАЗАЛА ФОРМА; None = не
    сообщала (открытая вкладка со старой разметкой).
    marks — отметки ПОВЕРХ находки («tratament»), см. teeth_svg.TOOTH_MARKS;
    None = форма о них не сообщала.

    ⭐ Три колонки (`state`, `surfaces`, `surface_states`) описывают одно и то
    же, поэтому согласует их ОДНО место — это. `surfaces` и `state` при
    непустом sfmap ВЫЧИСЛЯЮТСЯ из него: иначе печатная 043/e и выгрузка по
    195-му рано или поздно показали бы «Carie», когда кариеса на зубе уже нет,
    и заметить это было бы нечем — обе читают только `state`.

    ⚠️ `None` у `surfaces` и `sfmap` значит «экран об этом НЕ СООБЩАЛ», а не
    «пусто». Запрос знает или буквы (`surfaces` списком — так до 13.10 слал
    флажки диалог старой фиши, без состояний поверхностей), или карту (так
    шлёт React и слал инспектор детальной страницы — буквы из неё
    вычисляются). Принять молчание одного за стирание — значит терять клинику
    на сохранении, в котором врач ничего не менял: так пломба уходила с
    подписываемой 043/e. Поэтому не сообщённое берётся ИЗ ЗАПИСИ, и решается
    это здесь же, где сходятся все три колонки.
    """
    # состояние в летопись — СЛОВОМ (см. log_event): «obturatie» и «lipsa» это
    # ключи одонтограммы, а строку читают регистратура и пациент в выгрузке
    from ..teeth_svg import (MARK_RO, STATE_RO, SURFACE_ORDER, SURFACE_STATES,
                            mark_list, pack_marks, pack_surfaces, surface_map,
                            surface_summary, tooth_state_of)
    if surfaces is None:
        surfaces = (prev["surfaces"] or "") if prev else ""
    # ⚠️ То же правило, что у поверхностей: «поля нет» ≠ «снято». Экран, не
    # сообщивший про отметки (`marks` = None), молчит — и молчание обязано
    # СОХРАНИТЬ отметку, а не снять её; снять все — пустой список. Иначе
    # «сохранить фишу» тихо снимало бы «в лечении» с каждого зуба. (У форм
    # старой фиши снятая галочка не слала ничего, и о факте они сообщали
    # отдельным полем `mk0`; сняты 13.10.)
    marks = mark_list(marks if marks is not None
                      else (prev["marks"] or "") if prev else "")
    if sfmap is None:
        # Буквы без карты (`surfaces` списком; до 13.10 так слали флажки
        # диалога фиши) о состояниях не сообщают. Сохранённые — держим, а
        # буква, отмеченная ВПЕРВЫЕ, получает состояние зуба: «одно состояние
        # на все отмеченные» и есть смысл флажков.
        # ⚠️ Смена состояния В ДИАЛОГЕ — это и есть сообщение: тогда прежняя
        # смесь не держится, иначе выбор врача молча пропал бы. Отличаем по
        # тому, пришло ли состояние тем же, каким диалог его и ПОКАЗАЛ, —
        # и говорит это сама форма (`state0`).
        # ⭐ Сравнение с БАЗОЙ делало один и тот же ввод то правкой, то
        # пустышкой: на зубе, где показанное совпало с сохранённым, «отметить
        # кариес на обеих поверхностях» молча не срабатывало, а на соседнем
        # срабатывало. Врач видит форму, а не колонку, поэтому «форма сообщила»
        # обязано быть фактом ФОРМЫ. Запрос без `state0` (открытая вкладка,
        # старая разметка) остаётся при прежнем сравнении — иначе у уже
        # отправляемых запросов молча сменился бы смысл.
        was = state0 if state0 is not None else (prev["state"] if prev else "")
        keep = (surface_map(prev["state"], prev["surfaces"] or "",
                            prev["surface_states"] or "")
                if prev is not None and state == was else {})
        sfmap = {k: keep.get(k, state) for k in SURFACE_ORDER if k in surfaces}
    sfmap = {k: v for k, v in sfmap.items()
             if k in SURFACE_ORDER and v in SURFACE_STATES}
    # ⭐ «Sănătos» — не утверждение о зубе, а значение списка ПО УМОЛЧАНИЮ:
    # инспектор его не поднимает, когда врач размечает поверхность, и «ok +
    # M:carie» значит «кариес мезиально», а не «зуб здоров». Коронка, имплант,
    # удаление — наоборот, сказаны про ВЕСЬ зуб и карту отменяют.
    if state not in SURFACE_STATES and state != "ok":
        # у состояний ЗУБА поверхностей нет, но буквы записи остаются как есть,
        # их печатает 043/e
        # ⭐ Форма, сообщившая карту, буквы этим и НАЗНАЧАЕТ: «какие поверхности
        # под коронкой» иначе вводилось бы только флажками фиши, а инспектор
        # принимал бы ввод, который сам же подсветил, и не сохранял.
        if sfmap:
            surfaces = "".join(k for k in SURFACE_ORDER if k in sfmap)
        sfmap = {}
    elif (state in SURFACE_STATES and not sfmap and surfaces
            and prev is not None and prev["state"] not in SURFACE_STATES):
        # Обратный переход: буквы пережили коронку/имплант/лечение, а карты под
        # ними нет и быть не могло — у состояний ЗУБА она пуста по замыслу,
        # поэтому инспектор кнопок не зажигает и прислать их не может. Считать
        # его молчание стиранием значило бы терять с подписываемой 043/e то,
        # какие поверхности поражены; новое состояние ложится на прежние буквы
        # ровно так же, как это делают флажки фиши.
        sfmap = {k: state for k in SURFACE_ORDER if k in surfaces}
    if sfmap:
        # ⚠️ ДО ветки удаления: иначе отмеченная поверхность исчезала бы вместе
        # со строкой зуба, а экран отвечал бы «сохранено» (грабля карты «303 не
        # отличает успех от отказа»)
        state = tooth_state_of(sfmap, state)
    # ⚠️ Отметка держит строку наравне с заметкой и врачом: «здоровый зуб, но
    # сейчас в работе» — законная запись, а без этого условия она удалялась бы
    # сразу после сохранения, и экран отвечал бы «сохранено» (грабля карты
    # «303 не отличает успех от отказа»).
    if state == "ok" and not note and not doctor and not marks:
        return None, f"Dinte {tooth}: {STATE_RO['ok']}"
    if state in SURFACE_STATES:
        # у поверхностного состояния буквы и карта — одно знание, поэтому буквы
        # ВЫЧИСЛЯЮТСЯ: сняли поражение с поверхности — ушла и буква
        surfaces = "".join(k for k in SURFACE_ORDER if k in sfmap)
    row = {"state": state, "note": note, "doctor": doctor, "surfaces": surfaces,
           "surface_states": pack_surfaces(sfmap), "marks": pack_marks(marks)}
    txt = f"Dinte {tooth}: {STATE_RO.get(state, state)}"
    # ⚠️ Летопись хранит ГОТОВУЮ строку, поэтому смесь разворачивается СЕЙЧАС:
    # «Carie (M), Obturație (OD)». Однородный случай даёт ровно прежний вид —
    # «Carie (MO)», и старые записи с новыми читаются одинаково
    parts = surface_summary(sfmap)
    if len(parts) > 1:
        txt = (f"Dinte {tooth}: "
               + ", ".join(f"{STATE_RO[st]} ({ls})" for st, ls in parts))
    elif surfaces:
        txt += f" ({surfaces})"
    # Отметка — отдельным словом ПОСЛЕ находки: «Carie (MO) · În tratament».
    # Так строка отвечает на оба вопроса разом, а прежние записи (у которых
    # отметок нет) выглядят ровно как выглядели.
    for m in marks:
        txt += f" · {MARK_RO[m]}"
    if doctor:
        txt += f" · {doctor}"
    if note:
        txt += f" · {note}"
    return row, txt


# ---------- мосты (punte, 08-21, просьба пилота) ----------
# Мост — конструкция ПОВЕРХ зубов: состояние зуба (teeth.state) не мутируется,
# кариес под опорой и «lipsă» под промежутком остаются правдой самого зуба.
# Роль у КАЖДОГО зуба (опора бывает и в середине — пример врача: 47-43 с
# опорами 47/45/43); печать и рисование читают строку teeth через
# teeth_svg.parse_bridge — второго разбора не заводить.

async def bridges(pid: int) -> list:
    return await _fetch(
        """SELECT id, teeth, material, doctor, created_at
           FROM bridges WHERE patient_id = ? ORDER BY id""", pid)


def _bridge_words(teeth: list, material: str) -> str:
    """Мост словами для летописи: «Punte dentară 47–43 din zirconiu; stâlpi:
    47, 45, 43; intermediari: 46, 44». Летопись хранит ГОТОВУЮ строку навсегда
    (см. log_event), поэтому роли разворачиваются в слова здесь и сейчас."""
    span = f"{teeth[0][0]}–{teeth[-1][0]}"
    stalpi = ", ".join(str(n) for n, r in teeth if r == "stalp")
    corp = ", ".join(str(n) for n, r in teeth if r == "corp")
    out = f"Punte dentară {span}"
    if material:
        out += f" din {material}"
    out += f"; stâlpi: {stalpi}"
    if corp:
        out += f"; intermediari: {corp}"
    return out


async def add_bridge(pid: int, teeth: list, material: str,
                     doctor: str = "") -> int | str | None:
    """id — записан; 'dup' — какой-то зуб уже в другом мосту (два моста на
    одном зубе — вздор, и молча перекрывать чужую конструкцию нельзя).
    `teeth` приходит УЖЕ нормализованным (odontogram.bridge_norm) — db
    порядка дуги не знает. Проверка и INSERT — под _slot_lock: инвариант
    «зуб в одном мосту» держится только check-then-insert'ом (у таблицы нет
    уникального индекса — зубы лежат упакованной строкой), и без замка два
    конкурентных сохранения оба видят «свободно» (ревью 08-22)."""
    from ..teeth_svg import pack_bridge, parse_bridge
    mine = {n for n, _r in teeth}
    async with _slot_lock():
        for row in await bridges(pid):
            if mine & {n for n, _r in parse_bridge(row["teeth"])}:
                return "dup"
        packed = pack_bridge(teeth)
        cur = await db._CONN.execute(
            """INSERT INTO bridges(patient_id, teeth, material, doctor,
                                   created_at) VALUES(?, ?, ?, ?, ?)""",
            (pid, packed, material, doctor, _utcnow_iso()))
        await db._CONN.commit()
        new_id = cur.lastrowid
        await cur.close()
    txt = _bridge_words(teeth, material)
    if doctor:
        txt += f" · {doctor}"
    await log_event(pid, "bridge", txt)
    return new_id


async def delete_bridge(bid: int, pid: int) -> bool:
    """Снять мост. След в летописи остаётся: конструкцию ставили и снимали —
    это события лечения, а не оформление. Летопись пишется ПОСЛЕ удаления и
    только если DELETE реально снял строку: log_event коммитится собственной
    транзакцией, и записанное ДО было бы враньём навсегда при отказе DELETE
    или втором конкурентном удалении (ревью 08-22). Замок — тот же, что у
    add_bridge: SELECT и DELETE иначе гоняются с ним."""
    from ..teeth_svg import parse_bridge
    async with _slot_lock():
        rows = await _fetch(
            "SELECT teeth, material, doctor, created_at FROM bridges "
            "WHERE id = ? AND patient_id = ?", bid, pid)
        if not rows:
            return False
        # снятый мост уходит в bridges_removed той же транзакцией («сравнить с
        # визитом», 25.10): карта на дату, когда он стоял, обязана его рисовать
        b = rows[0]
        try:
            await db._CONN.execute(
                """INSERT INTO bridges_removed(bridge_id, patient_id, teeth, material,
                                               doctor, created_at, removed_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (bid, pid, b["teeth"], b["material"], b["doctor"], _iso(b["created_at"]),
                 _utcnow_iso()))
            cur = await db._CONN.execute(
                "DELETE FROM bridges WHERE id = ? AND patient_id = ?", (bid, pid))
            n = cur.rowcount
            await cur.close()
            if n != 1:
                await db._CONN.rollback()
                return False
            await db._CONN.commit()
        except Exception:
            await db._CONN.rollback()
            raise
    t = parse_bridge(rows[0]["teeth"])
    span = f"{t[0][0]}–{t[-1][0]}" if t else "?"
    await log_event(pid, "bridge", f"Punte dentară {span} ștearsă")
    return True
