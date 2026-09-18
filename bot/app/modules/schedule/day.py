"""Сетка дня: правила, из которых строятся «Toți medicii» и день врача.

Здесь нет ни одной строки разметки. Всё, что знает эта таблица про время,
врачей и занятость, живёт функциями — их же возьмёт JSON API, когда экран
поедет в React. Контракт самих правил закреплён в `tests/test_grid.py`.

Три правила, которые ломаются молча, и потому вынесены поимённо:

1. **Ряды — непрерывный диапазон.** `day_slots` выбрасывает обеденный час
   совсем, и таблица прыгала бы с 12:00 на 14:00 без следа паузы. Хуже
   второе: запись, оказавшаяся в ЗАКРЫТОМ часу (обед или график поменяли
   после брони), исчезала бы из сетки целиком — час не нарисован, значит и
   записи по нему никто не спросил. В списке дня визит есть, в сетке нет.
2. **Ключ записи — стабильный `doctor_id`**, а у строк без него — СНИМОК
   имени. Обе половины несущие: переименование врача не должно двигать его
   историю, а запись без id не должна исчезнуть или прилипнуть к соседу.
3. **«Занято» и «не принимает» — разные вещи.** Под длинным визитом «+» врал
   бы («час свободен»), вне часов врача — врал бы иначе («можно записать»),
   и `/admin/add` ответил бы отказом. Поэтому у ячейки четыре исхода, а не
   два.
"""
from __future__ import annotations

from datetime import date, datetime

from ... import db
from ... import engine as eng


def active_map(rows: list) -> tuple[dict, set]:
    """({(врач, час): [записи]}, {(врач, час) под длинным визитом}).

    ⚠️ Ключ — `doctor_id`, пока он известен справочнику; иначе имя-снимок.
    Отменённые записи в сетку не попадают вовсе.
    """
    starts: dict = {}
    covered: set = set()
    for r in rows:
        if r["status"] == "cancelled":
            continue
        did = r.get("doctor_id")
        key = did if did and did in eng.DOCTORS else r["doctor"]
        st = r["starts_at"].astimezone(eng.TZ)
        starts.setdefault((key, st.hour), []).append(r)
        dur = int(r.get("duration_min") or 60)
        end_min = st.hour * 60 + st.minute + dur
        for h in range(st.hour + 1, (end_min + 59) // 60):
            covered.add((key, h))
    return starts, covered


def hours_range(d: date, starts: dict, covered: set) -> list[int]:
    """Часы рядов: рабочие плюс те, где что-то стоит, без дыр между ними."""
    open_h = {x.hour for x in eng.day_slots(d)}
    known = sorted(open_h | {h for _k, h in starts} | {h for _k, h in covered})
    return list(range(known[0], known[-1] + 1)) if known else []


def open_hours(d: date) -> set:
    """Часы, когда клиника открыта (обед уже выброшен)."""
    return {x.hour for x in eng.day_slots(d)}


def closed_kind(d: date, h: int) -> str:
    """Чем закрыт час: «pauza» (обед клиники), «inchis» (вне графика), «»."""
    if h in open_hours(d):
        return ""
    hf = eng.hours_for(d)
    br_f, br_t = (int(hf[2]), int(hf[3])) if hf and len(hf) >= 4 else (0, 0)
    return "pauza" if br_f <= h < br_t else "inchis"


def now_hour(d: date) -> int | None:
    """Текущий час — ТОЛЬКО на сегодняшнем дне, иначе None."""
    now = datetime.now(eng.TZ)
    return now.hour if now.date() == d else None


def column_spec(dk: str) -> str:
    """Подпись колонки под именем врача; выключенный помечается прямо здесь."""
    spec = eng.DOCTOR_SPEC.get(dk, "")
    if not eng.DOCTOR_META.get(dk, {}).get("active", True):
        spec = (spec + " · inactiv").strip(" ·")
    return spec


def work_hours(d: date, items: list) -> dict:
    """{врач: часы приёма} — один ответ на вопрос «принимает ли он в этот час»
    для обеих дневных страниц (`eng.doctor_hours`). Он же закрывает разом обед
    клиники, суженные часы врача из его фиши и выключенного врача."""
    return {dk: eng.doctor_hours(dk, d) for dk, _n in items}


def cell_kind(dk: str, dname: str, h: int, starts: dict, covered: set,
              work: dict) -> str:
    """Исход ячейки: «appts» (в ней записи), «busy» (под длинным визитом),
    «off» (врач не принимает) или «free» («+»)."""
    if starts.get((dk, h)) or starts.get((dname, h)):
        return "appts"
    if (dk, h) in covered or (dname, h) in covered:
        return "busy"
    if h not in work.get(dk, set()):
        return "off"
    return "free"


def cell_rows(dk: str, dname: str, h: int, starts: dict) -> list:
    """Записи ячейки. ⚠️ Ищутся по ОБОИМ ключам: id и снимку имени."""
    return starts.get((dk, h)) or starts.get((dname, h)) or []


def can_drop(dk: str, h: int, work: dict) -> bool:
    """Мишень переноса: приёмный час врача, ЗАНЯТ он или нет — в 10:00 стоит
    визит, а 10:30 у того же часа свободно."""
    return h in work.get(dk, set())

# --------------------------------------------------------------- модель 2.0
# ⚠️ Здесь НЕ появляется ни одного нового правила: всё, что ниже, собирает уже
# вынесенные функции в один ответ. Если модель и разметка однажды разойдутся,
# виновата будет сборка, а не правило — искать станет где.

def appt_view(r, dk: str, cards: dict | None, colors) -> dict:
    """Одна запись глазами сетки: то же, что печатает карточка.

    `colors` и `cards` передаются аргументами по той же причине, что и у
    недели: они живут в `routes`/`core.visits`, а импорт оттуда замкнул бы
    круг. ⛔ Перетаскивание описывается ТЕМИ ЖЕ полями, что `_move_attrs`:
    минуты от полуночи, длительность, подпись и признак «занимает интервал».
    Разойдись они — перенос на новом экране молча перестал бы работать, а
    поймать это можно только руками.
    """
    st = r["starts_at"].astimezone(eng.TZ)
    dur = int(r.get("duration_min") or 60)
    live = r["status"] in db.ACTIVE_STATUSES
    if r["source"] == "note":
        return {"kind": "note", "id": r["id"], "time": st.strftime("%H:%M"),
                "text": r["service"], "min": st.hour * 60 + st.minute,
                "dur": dur, "busy": live, "movable": bool(dk) and live}
    bg, bar = colors(r)
    return {
        "kind": "appt", "id": r["id"], "time": st.strftime("%H:%M"),
        "name": r["name"] or "—", "service": r["service"],
        "phone": r["phone"] or "", "status": r["status"],
        "urgent": r["service"] in eng.URGENT_LABELS,
        "source": r["source"], "dur": dur,
        "comment": (r["comment"] or "")[:60],
        "birth_year": r.get("birth_year"),
        "clickable": bool(cards is not None and r["id"] in cards),
        "bg": bg, "bar": bar,
        # перетаскивание — теми же полями, что у _move_attrs
        "min": st.hour * 60 + st.minute, "busy": live,
        "movable": bool(dk) and live,
    }


def model(d, items: list, active: tuple, cards: dict | None, colors) -> dict:
    """Сетка дня данными: колонки, ряды часов, ячейки с их исходом.

    ⚠️ Колонки — СПИСОК, и ячейка ссылается на него позицией. Врачей может не
    быть вовсе (никого активного и ни одной записи), может быть один (день
    врача) или все; раскладка по фиксированным позициям сломалась бы на
    первом же выключенном враче.
    """
    starts, covered = active
    work = work_hours(d, items)
    nh = now_hour(d)
    cols = [{"id": dk, "name": name, "spec": column_spec(dk)} for dk, name in items]
    hours = []
    for h in hours_range(d, starts, covered):
        kind = closed_kind(d, h)
        cells = []
        for dk, dname in items:
            ck = cell_kind(dk, dname, h, starts, covered, work)
            cells.append({
                "kind": ck,
                "drop": can_drop(dk, h, work),
                "items": [appt_view(r, dk, cards, colors)
                          for r in cell_rows(dk, dname, h, starts)],
            })
        hours.append({"h": h, "label": f"{h:02d}:00", "closed": kind,
                      "now": h == nh, "cells": cells})
    return {"date": d.isoformat(), "doctors": cols, "hours": hours}
