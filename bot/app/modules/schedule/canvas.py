"""Канва панели дня: правила, из которых она строится. Разметки здесь нет.

Канва — НЕ таблица `/admin/all`, и её правила живут отдельно от `day.py`
намеренно. Разведка C26.1 (`docs/dentpilot-2/admin-contract.md`) нашла три
места, где они расходятся, и первое — несущее:

1. **Ключ колонки.** Легаси-строка без `doctor_id`, но с именем ЖИВОГО врача,
   получает здесь СВОЮ колонку рядом с его собственной; таблица (`day.
   cell_rows` ищет по обоим ключам) сливает её в колонку врача. Канва — это
   единственное место в программе, где видно записи выпавшего из справочника
   врача, и единственный вход в `POST /admin/relink`. Построй её на модели
   таблицы — визит исчезнет с панели, а час будет выглядеть свободным.
2. **Время линейно.** Таблица кладёт запись В ЯЧЕЙКУ часа, канва ставит блок
   по минутам и высотой в длительность, поэтому ей нужны и `base_min`, и
   кластеры пересечений: два визита, наложившись, спрятали бы друг друга.
3. **Края дня срезаются в полоски**, а обед — нет: он в середине, и выкинутый
   средний час сдвинул бы всё, что после него.

⚠️ Общее с таблицей берётся у общих же владельцев: часы врача — у
`engine.doctor_hours`/`doctor_bounds`, статусы — у `db`/`layout`, цвет — у
`core.visits`. Свой второй источник любого из них разводил бы два экрана.
"""
from __future__ import annotations

from datetime import date, datetime

from ... import engine as eng
from ...core.layout import LIVE_STATUSES, STATUS_LABEL, _initials
from ...core.visits import _doc_hue, photo_url
from . import day as pday


def row_col(r: dict) -> str:
    """Ключ колонки: стабильный `doctor_id`, у легаси-строк — снимок имени.

    ⛔ Обе половины несущие. Переименование врача не должно двигать его
    историю, а запись без id не должна ни исчезнуть, ни прилипнуть к
    однофамильцу: `n:` и `k:` — РАЗНЫЕ колонки, даже когда имя совпадает.
    """
    did = r.get("doctor_id")
    if did and did in eng.DOCTORS:
        return f"k:{did}"
    return f"n:{r['doctor']}"


def bounds(r: dict) -> tuple[int, int]:
    """(начало, конец) визита в минутах от полуночи дня клиники."""
    st = r["starts_at"].astimezone(eng.TZ)
    s_min = st.hour * 60 + st.minute
    return s_min, s_min + int(r.get("duration_min") or 60)


def pos(r: dict, base_min: int) -> tuple[float, float]:
    """(top, height) блока В ДОЛЯХ ЧАСА: старт от base_min, высота — минуты.

    ⚠️ Пол высоты 0.4 ячейки: получасовой визит иначе становится полоской, в
    которую не помещается даже время.
    ⚠️ `base_min` — минута ПЕРВОГО ОСТАВЛЕННОГО часа, а не первого часа дня:
    после среза краёв она другая, и позиция, посчитанная от номера часа,
    уехала бы на целый час у клиники со сдвинутым графиком.
    """
    st = r["starts_at"].astimezone(eng.TZ)
    dur = int(r.get("duration_min") or 60)
    top = (st.hour * 60 + st.minute - base_min) / 60
    return top, max(dur / 60, 0.4)


def clusters(rows: list) -> list[list]:
    """Пересекающиеся визиты колонки — группами, которые поделят ширину.

    ⛔ Запись попадает в кластер, если пересекается ХОТЯ БЫ С ОДНОЙ из него, а
    не с последней: у цепочки A(09:00–11:00), B(09:30–10:00), C(10:30–11:00)
    B и C между собой не пересекаются, но обе — с A. Сравнение с последней
    откололо бы C, и она встала бы во всю ширину ПОВЕРХ A: спрятанный пациент,
    выглядящий совершенно правдоподобно.
    """
    out: list[list] = []
    for r in sorted(rows, key=bounds):
        s_min, e_min = bounds(r)
        if out and any(bounds(x)[0] < e_min and s_min < bounds(x)[1]
                       for x in out[-1]):
            out[-1].append(r)
        else:
            out.append([r])
    return out


def row_hours(live: list) -> set:
    """Часы, занятые записями, — и по началу, И ПО КОНЦУ визита.

    ⚠️ Без конца хвост двухчасового визита уходил бы за нижний край сетки.
    """
    hs: set = set()
    for r in live:
        st = r["starts_at"].astimezone(eng.TZ)
        end_min = st.hour * 60 + st.minute + int(r.get("duration_min") or 60)
        hs.add(st.hour)
        hs.add(max(st.hour, (end_min - 1) // 60))
    return hs


def hours_of(d: date, live: list) -> list[int]:
    """Ряды канвы: непрерывный диапазон от первого известного часа до
    последнего. Обед остаётся рядом (он в середине), потому что время на канве
    линейно и выкинутый час сдвинул бы всё, что ниже."""
    known = sorted({x.hour for x in eng.day_slots(d)} | row_hours(live))
    return list(range(known[0], known[-1] + 1)) if known else []


def open_hours(d: date, shown: list) -> set:
    """Часы, открытые ХОТЯ БЫ У ОДНОЙ показанной колонки.

    ⚠️ Спрашивается у `doctor_bounds` — ровно там же, где `_cells` берёт свою
    штриховку: свой второй признак «закрыто» развёл бы полоску и штриховку.
    """
    out: set = set()
    for dk, _name in shown:
        b = eng.doctor_bounds(dk, d)
        if b:
            f_h, to_h, bf_h, bt_h = b
            out |= {h for h in range(f_h, to_h) if not (bf_h <= h < bt_h)}
    return out


def trim_edges(hours: list[int], keep: set) -> tuple[list[int], list[int], list[int]]:
    """Срезать КРАЙНИЕ полностью закрытые часы: (ряды, слева, справа).

    ⚠️ Только края. Закрытый час в СЕРЕДИНЕ — это обед, и он обязан остаться
    рядом. ⚠️ Час, в котором есть запись, не срезается никогда: визит вне
    графика — как раз то, что сетка обязана показывать. Хотя бы один ряд
    остаётся всегда, иначе день без графика и без записей отдал бы пустоту.
    """
    lead, tail = 0, len(hours)
    while lead < tail - 1 and hours[lead] not in keep:
        lead += 1
    while tail - 1 > lead and hours[tail - 1] not in keep:
        tail -= 1
    return hours[lead:tail], hours[:lead], hours[tail:]


def free_hour(dk: str, d: date, taken: list) -> int | None:
    """Первый рабочий час врача без ПЕРЕСЕЧЕНИЙ с его занятыми интервалами.

    ⛔ Не «первый час без записи»: визит на 09:00 длиной два часа занимает и
    10:00, хотя записи в десять нет. Ошибка здесь предлагает регистратуре час,
    в который сервер откажет.
    """
    b = eng.doctor_bounds(dk, d)
    if not b:
        return None
    f_h, to_h, bf_h, bt_h = b
    spans = [bounds(r) for r in taken]
    for h in range(f_h, to_h):
        if bf_h <= h < bt_h:
            continue
        if not any(s < (h + 1) * 60 and h * 60 < e for s, e in spans):
            return h
    return None


def shown_doctors(by_col: dict) -> list[tuple[str, str]]:
    """Колонки справочника: активные плюс выключенные, у которых есть записи
    этого дня, — иначе их визиты стало бы негде смотреть."""
    return [(dk, name) for dk, name in eng.DOCTORS.items()
            if eng.DOCTOR_META.get(dk, {}).get("active", True)
            or by_col.get(f"k:{dk}")]


def orphan_cols(by_col: dict) -> list[str]:
    """Ключи колонок-сирот: всё, что не принадлежит живому справочнику."""
    return sorted(set(by_col) - {f"k:{dk}" for dk in eng.DOCTORS})


# Серый колонки-сироты. ⚠️ Он НЕ фирменный и теме не отдаётся намеренно: это
# цвет смысла «этого врача в справочнике больше нет», ровно как `--red` у
# ошибки. Фирменным он сказал бы обратное — что колонка своя.
_ORPHAN_HUE = "#94A3B8"


def _tip(r: dict) -> str:
    """Подсказка блока. ⚠️ Она не украшение: у короткой записи браузер сжимает
    текст в строку с многоточием, а у совсем короткой убирает совсем — и тогда
    подсказка единственное, что отвечает «кто это», не открывая карточку.
    Поэтому её собирает СЕРВЕР: слово статуса приходит из `STATUS_LABEL`, и
    второй его словарь в браузере — это «Finalizat» в одном месте и «a venit»
    в другом (ломалось дважды, 08-12 и 08-16)."""
    st = r["starts_at"].astimezone(eng.TZ)
    dur = int(r.get("duration_min") or 60)
    word = (STATUS_LABEL.get(r["status"], r["status"])
            if r["status"] != "confirmed" else "")
    return (f"{st.strftime('%H:%M')} · {dur}′ · {r['service']}"
            f" · {r['name'] or '—'}" + (f" · {word}" if word else ""))


def blocks(rows: list, col_dk: str, base_min: int, cards, colors) -> list[dict]:
    """Блоки одной колонки: вид записи плюс ГЕОМЕТРИЯ.

    ⚠️ Сам вид берётся у `day.appt_view` — те же поля переноса (`min`, `dur`,
    `busy`, `movable`), что печатает `_move_attrs`, и то же готовое слово
    статуса. Канва дописывает только место в кластере (`col` из `of`) и долю
    высоты. Свой второй вид записи развёл бы два дневных экрана.
    ⚠️ Порядок внутри кластера — тот же, что на странице: неактивные раньше
    активных, чтобы живая запись легла ПОВЕРХ отменённой пары.
    """
    out: list[dict] = []
    for cluster in clusters(rows):
        n = len(cluster)
        for j, r in enumerate(sorted(cluster,
                                     key=lambda x: x["status"] in LIVE_STATUSES)):
            top, height = pos(r, base_min)
            v = pday.appt_view(r, col_dk, cards, colors)
            v.update({"top": round(top, 3), "height": round(height, 3),
                      "col": j, "of": n})
            if v["kind"] == "note":
                # ⛔ Один и тот же текст живёт на экране в ДВУХ длинах: 80 в
                # подсказке и 40 в самом блоке. Обе — данные, а не оформление:
                # обрежь их в браузере по своей мерке, и пересохранение через
                # диалог укоротит текст в базе (прайор 08-16).
                v["title"] = r["service"][:80]
                v["label"] = r["service"][:40]
            else:
                v["title"] = _tip(r)
                # «сколько ждёт в приёмной»: сервер отдаёт только ОТМЕТКУ, а
                # минуты считает браузер — серверная строка с минутами меняла
                # бы отпечаток живого тела каждую минуту, и опрос подменял бы
                # сетку без единой правки данных (мигание, 08-20).
                v["wait_since"] = (
                    int(r["waiting_at"].timestamp() * 1000)
                    if r["status"] == "waiting" and r.get("waiting_at") else None)
            out.append(v)
    return out


def _band(hs: list[int]) -> dict | None:
    """Срезанный край одной полоской: с какого часа по какой закрыто."""
    return {"from": f"{hs[0]:02d}:00", "to": f"{hs[-1] + 1:02d}:00"} if hs else None


def _column(d: date, dk: str, name: str, by_col: dict, live: list,
            hours: list[int], base_min: int, cards, colors) -> dict:
    """Колонка живого врача: шапка, приёмные часы и блоки."""
    key = f"k:{dk}"
    meta = eng.DOCTOR_META.get(dk, {})
    mine = [r for r in live if row_col(r) == key and r["source"] != "note"]
    free_h = free_hour(dk, d, by_col.get(key, []))
    # Загрузка кресла: занятые минуты / рабочие минуты врача В ЭТОТ ДЕНЬ.
    # Ёмкость берётся у того же `eng.work_minutes`, что считает «Statistici»,
    # иначе дашборд и статистика показывали бы разный процент про одного врача.
    cap = eng.work_minutes(dk, d)
    busy = sum(int(r.get("duration_min") or 60) for r in mine)
    work = eng.doctor_hours(dk, d)
    return {
        "key": key, "id": dk, "name": name, "orphan": False,
        "spec": eng.DOCTOR_SPEC.get(dk, "") or "",
        "off": not meta.get("active", True),
        # ⛔ Цвет врача считает ОДИН `_doc_hue` — он же красит аватар,
        # карточку врача и `/api/doctors`. Своя формула «по месту среди
        # ПОКАЗАННЫХ в этот день колонок» жила здесь и на странице до 19.09:
        # цвет колонки расходился с аватаром того же врача и вдобавок менялся
        # ото дня ко дню от того, у кого есть записи.
        "hue": _doc_hue(dk),
        "photo": photo_url(dk), "initials": _initials(name),
        # ⚠️ Кабинет и телефон — ОТДЕЛЬНЫМИ полями, а не только внутри
        # подсказки: регистратура наводится на карточку именно ради номера
        # кабинета. Ветка `if meta.get("room")` пуста на демо-профиле, поэтому
        # у разработчика всё выглядит целым и без них.
        "room": meta.get("room", "") or "", "phone": meta.get("phone", "") or "",
        # ⛔ Считает ПАЦИЕНТОВ: заметка стойки занимает час, но «N prog.» её не
        # видит. Свести к одному списку — и число разойдётся с «Lista zilei»
        # на том же экране.
        "count": len(mine),
        # ⛔ А ЭТО смотрит на занятость — и заметка занимает час наравне с
        # визитом (`by_col` собран из всех живых строк). Два числа в одной
        # строке шапки питаются разными списками намеренно.
        "free": f"{free_h:02d}:00" if free_h is not None else None,
        # ⚠️ Процент НЕ обрезан сотней: перебронированный день показывает
        # «130%», и это единственный признак, по которому директор его увидит.
        # Обрезается только ШИРИНА полосы — это дело рисовальщика.
        "occupancy": ({"busy": busy, "cap": cap, "pct": round(100 * busy / cap)}
                      if cap else None),
        "title": " · ".join(x for x in [name, meta.get("room", ""),
                                        meta.get("phone", "")] if x),
        # ⛔ Час принимает клик и перетащенный визит по ОДНОМУ признаку —
        # приёмному часу этого врача (`eng.doctor_hours`, её же спрашивает
        # таблица «Programări»). Заведи второй — два экрана разойдутся в том,
        # куда можно писать.
        "cells": [h in work for h in hours],
        "blocks": blocks(by_col.get(key, []), dk, base_min, cards, colors),
        "relink": None,
    }


def _orphan_column(key: str, by_col: dict, live: list, hours: list[int],
                   base_min: int, cards, colors) -> dict:
    """Колонка выпавшего из справочника врача — и единственный вход в relink.

    ⛔ Ни клика, ни переноса: врача с таким именем в списке уже нет, писать
    ему некуда, и адреса у переноса нет тоже (`col_dk` пустой).
    """
    name = key[2:]
    mine = [r for r in live if row_col(r) == key and r["source"] != "note"]
    return {
        "key": key, "id": None, "name": name, "orphan": True,
        "spec": "", "off": True, "hue": _ORPHAN_HUE,
        "photo": "", "initials": _initials(name),
        "count": len(mine), "free": None, "occupancy": None, "title": "",
        "cells": [False] * len(hours),
        "blocks": blocks(by_col.get(key, []), "", base_min, cards, colors),
        "relink": {"name": name,
                   "options": [{"id": k, "name": n}
                               for k, n in eng.DOCTORS.items()]},
    }


def model(d: date, rows: list, cards: dict | None, colors) -> dict:
    """Канва дня данными: ряды часов, колонки и блоки с их геометрией.

    ⛔ Это НЕ `day.model` другими словами, и подменять одну другой нельзя.
    Ключ колонки здесь свой (`row_col`): легаси-строка без `doctor_id`, но с
    именем живого врача, получает СВОЮ колонку, тогда как таблица сливает её
    в колонку этого врача. Собери React по модели таблицы — визит выпавшего из
    справочника врача исчезнет с панели, час будет выглядеть свободным, а
    `test_schedule_api.suite_day_orphan` останется зелёной: она про таблицу и
    фиксирует как раз слияние. Разбор — `docs/dentpilot-2/admin-contract.md`.

    ⚠️ `colors` приходит аргументом по той же причине, что и у `day.model`:
    `_svc_colors` живёт в `routes`, и импорт оттуда замкнул бы круг.
    ⚠️ Чего здесь НЕТ намеренно: линии «сейчас» (её ставит `panel.js` по
    минутам — серверная строка меняла бы отпечаток живого тела каждый опрос)
    и ступеней сжатия блока (`slim`/`tiny`/`bare` ставятся ПО ЗАМЕРУ в
    браузере: высоту ряда решает окно, и порог числом соврал бы на одном из
    двух мониторов). Подсветка текущего ЧАСА, наоборот, серверная: она
    меняется раз в час, и её смена — честное изменение страницы.
    """
    live = [r for r in rows if r["status"] != "cancelled"]
    rh = row_hours(live)
    hours = hours_of(d, live)
    if not hours:
        # «Zi liberă» — ни графика, ни записей: сетки нет вовсе
        return {"date": d.isoformat(), "empty": True, "base_min": None,
                "tight": False, "hours": [], "columns": [],
                "bands": {"top": None, "bottom": None}}
    by_col: dict = {}
    for r in live:
        by_col.setdefault(row_col(r), []).append(r)
    shown = shown_doctors(by_col)
    hours, band_l, band_r = trim_edges(hours, open_hours(d, shown) | rh)
    base_min = hours[0] * 60
    now = datetime.now(eng.TZ)
    nh = now.hour if d == now.date() else None
    cols = [_column(d, dk, name, by_col, live, hours, base_min, cards, colors)
            for dk, name in shown]
    cols += [_orphan_column(key, by_col, live, hours, base_min, cards, colors)
             for key in orphan_cols(by_col)]
    return {
        "date": d.isoformat(), "empty": False, "base_min": base_min,
        # ⚠️ Больше четырёх колонок — карточка врача ужимается (у клиники на
        # шесть врачей полноразмерная режет имена). Считается ПОСЛЕ сирот:
        # они такие же колонки и тоже отнимают ширину.
        "tight": len(cols) > 4,
        "hours": [{"h": h, "label": f"{h:02d}:00", "now": h == nh} for h in hours],
        "bands": {"top": _band(band_l), "bottom": _band(band_r)},
        "columns": cols,
    }
