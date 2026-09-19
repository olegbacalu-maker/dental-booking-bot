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

from datetime import date

from ... import engine as eng


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
