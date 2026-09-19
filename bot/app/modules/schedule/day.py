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
from ...core.layout import STATUS_LABEL
from ...core.visits import _age, all_status_actions, list_rows


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


# Плитки панели дня ведут на `/admin/all?f=…` и фильтруют СПИСОК, не сетку:
# «сколько пришло из бота» — вопрос к списку, а сетка в этот момент отвечает на
# другой («что стоит в дне»), и прореживать её значило бы соврать про занятость.
# ⚠️ Отменённые в первых трёх фильтрах не считаются: «записей из бота» —
# это живые записи, а не след отменённых.
TILE_FILTERS = {
    "bot": ("prin bot",
            lambda r: r["source"] == "bot" and r["status"] != "cancelled"),
    "rec": ("recepție",
            lambda r: r["source"] == "manual" and r["status"] != "cancelled"),
    "urg": ("urgențe",
            lambda r: r["service"] in eng.URGENT_LABELS
            and r["source"] != "note" and r["status"] != "cancelled"),
    "noshow": ("neprezentări", lambda r: r["status"] == "noshow"),
}


def note_ends(d: date) -> list[int]:
    """Часы, которыми МОЖЕТ КОНЧИТЬСЯ блокировка слота: открытый час плюс один.

    ⚠️ Обеденный час выпадает из `day_slots`, а значит и отсюда: при обеде
    13–14 закончить блокировку в 14:00 нельзя, ближайшие концы — 13:00 и
    15:00. Это не оплошность: заметка блокирует ЧАСЫ ПРИЁМА, а обеденного
    часа среди них нет.
    """
    return [x.hour + 1 for x in eng.day_slots(d)]


def form_spec(d: date, items: list, sel_doctor: str = "",
              sel_time: str = "") -> dict:
    """Что предлагает форма записи: врачи, ИХ часы, услуги и предвыбор.

    ⚠️ Часы здесь СВОИ, а не из сетки. Сетка рисует непрерывный диапазон, и
    обеденный час в ней есть (со своей пометкой); форма предлагает только те
    получасовые старты, куда влезает приём.
    ⚠️ Влезает — это всегда 30 минут, а не длительность выбранной услуги:
    список ОДИН на все услуги. Пересчёт «по-умному» отнял бы 17:30 у
    получасового приёма в клинике, закрывающейся в 18:00, — час, который
    сегодня законен; а часовой визит на 17:30 всё равно отобьёт `outside`.
    ⛔ Пустое окно врача подменяется часами клиники (`or hours`). Пустой
    `<select>` не отправил бы поле `atime` вовсе, и вместо честного отказа
    «Medicul nu lucrează la ora aleasă» вышла бы ошибка разбора формы.
    ⚠️ `items` — НЕ колонки сетки: страница даёт сюда активных врачей
    справочника, потому что выключенному `/admin/add` ответит `bad_off`, а
    колонка у него в сетке остаётся, пока есть записи дня.
    """
    def _starts(fits) -> list[str]:
        out = []
        for x in eng.day_slots(d):
            for m in (0, 30):
                st = x.replace(minute=m)
                if fits(st):
                    out.append(st.strftime("%H:%M"))
        return out

    hours = _starts(lambda st: eng.fits_clinic(st, 30))
    times = {dk: _starts(lambda st, k=dk: eng.fits_doctor(k, st, 30)) or hours
             for dk, _n in items}
    cur = sel_doctor if sel_doctor in times else (items[0][0] if items else "")
    return {
        "doctors": [{"id": dk, "name": name} for dk, name in items],
        "times": times,
        # часы клиники: ими подменяется пустое окно врача, ими же живёт форма,
        # когда активных врачей нет вовсе
        "hours": hours,
        "services": [{"id": k, "label": v["ro"]} for k, v in eng.SERVICES.items()],
        "doctor": cur,
        "time": sel_time if sel_time in times.get(cur, hours) else "",
        # потолок поля «дата рождения» — тот же `date.today()`, что печатает
        # форма: у страницы и у клиента один и тот же «сегодня»
        "birth_max": date.today().isoformat(),
    }

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
        # ⛔ ДВА имени, и это не дублирование. Полное значение носит имя БЕЗ
        # суффикса — из него правят; обрезок носит имя, по которому его нельзя
        # взять по ошибке (у обоих тип `str`, и типы не возразят). Обрезает
        # по-прежнему СЕРВЕР: длина — данные, а не оформление, обрежь её в
        # браузере — и пересохранение через диалог укоротит текст в базе
        # (08-16). ⭐ Этим же ПОСТРОЕНИЕМ закрыта дыра живого канала: полное
        # значение лежит в отпечатке, поэтому правка 61-го знака приезжает
        # вторым рабочим местом, а не тонет в проекции (опыт 19.09,
        # live-contract › 6c).
        "comment": r["comment"] or "",
        "comment_cut": (r["comment"] or "")[:60],
        # ⛔ Слово статуса и возраст приезжают ГОТОВЫМИ: второй словарь статусов
        # в браузере — это «Finalizat» в одном месте и «a venit» в другом
        # (ломалось дважды, 08-12 и 08-16), а свой счёт возраста разойдётся с
        # серверным в день, когда появится месяц рождения.
        "status_label": STATUS_LABEL.get(r["status"], r["status"]),
        "age": _age(r.get("birth_year")),
        "clickable": bool(cards is not None and r["id"] in cards),
        "bg": bg, "bar": bar,
        # перетаскивание — теми же полями, что у _move_attrs
        "min": st.hour * 60 + st.minute, "busy": live,
        "movable": bool(dk) and live,
    }


def model(d, items: list, active: tuple, cards: dict | None, colors,
          form_items: list | None = None, rows: list | None = None,
          f: str = "") -> dict:
    """Сетка дня данными: колонки, ряды часов, ячейки с их исходом — и всё,
    чем живут диалоги: форма, концы блокировки, карточки, кнопки исхода.

    ⚠️ Колонки — СПИСОК, и ячейка ссылается на него позицией. Врачей может не
    быть вовсе (никого активного и ни одной записи), может быть один (день
    врача) или все; раскладка по фиксированным позициям сломалась бы на
    первом же выключенном враче.
    ⛔ `form_items` — врачи ФОРМЫ, и это НЕ `items`. В сетке остаётся колонка
    выключенного врача, пока у него есть записи дня, а записать в него
    `/admin/add` не даст (`bad_off`). Возьми клиент врачей из колонок —
    регистратура выбрала бы выключенного и получила отказ на ровном месте, а
    у разработчика оба списка совпадают. `None` — формы нет вовсе (так
    выглядит страница выключенного врача).
    ⚠️ Карточки приезжают ЦЕЛИКОМ, включая отменённые, которых в сетке нет:
    отменённую запись открывают, чтобы вернуть. И комментарий в них ПОЛНЫЙ, а
    в карточке сетки обрезан до 60 — диалог обязан править полный, иначе
    пересохранение без единой правки укоротит текст (прайор 08-16).
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
    return {
        "date": d.isoformat(), "doctors": cols, "hours": hours,
        "form": form_spec(d, form_items) if form_items is not None else None,
        "note_ends": note_ends(d),
        # ключи строками: так их печатает `js_json(cards)` на странице, и так
        # они приезжают из JSON — иначе клиент искал бы карточку числом, а
        # получал бы объект со строковыми ключами
        "cards": {str(k): v for k, v in (cards or {}).items()},
        "actions": all_status_actions(),
        "note_actions": all_status_actions(is_note=True),
        **_list_part(rows or [], f),
    }


def _list_part(rows: list, f: str) -> dict:
    """«Lista zilei» и плитка-фильтр. Фильтр режет ТОЛЬКО список: сетка в этот
    момент отвечает на другой вопрос — что стоит в дне, — и прореживать её
    значило бы соврать про занятость."""
    flt = TILE_FILTERS.get(f)
    if not flt:
        return {"list": list_rows(rows), "filter": None}
    label, pred = flt
    hits = [r for r in rows if pred(r)]
    return {"list": list_rows(hits),
            "filter": {"key": f, "label": label, "count": len(hits)}}
