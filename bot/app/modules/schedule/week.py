"""Недельный календарь: какие дни показаны, что в них и чем это красится.

Здесь ПРАВИЛА недели, без разметки. Их три, и все три ломаются молча:

1. **Колонок не семь.** Выходной прячется — но только если на нём нет живых
   записей: клиника меняет график, а прошлые записи в закрытом дне остаются и
   обязаны быть видны. Поэтому колонок 5, 6 или 7, и `индекс ≠ weekday()`.
   Клиент, разложивший ответ по семи позициям, поставит субботу под
   воскресенье — и это будет выглядеть совершенно правдоподобно.
2. **Счётчик — не длина списка.** Отменённые не показываются вовсе, а заметки
   стойки показываются, но в счёт «programări» не идут: это не пациенты.
3. **Цвет приезжает ПЕРЕМЕННОЙ темы, а не значением.** Клиника выбирает свой
   цвет, и зашитый хекс остался бы зелёным на синем интерфейсе (прайор 08-09).

⚠️ Записи берутся ОДНИМ запросом на всю неделю и раскладываются по дням здесь
(`by_day`): страница ходила в базу семь раз, по разу на день. Карточка врача
давно делает это одним вызовом — см. `doctors/routes._week_cells`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ... import engine as eng


def monday_of(d: date) -> date:
    """Понедельник недели, в которую попал день. Страница ключуется им, а не
    самой датой: любой день недели обязан открыть ОДНУ И ТУ ЖЕ неделю."""
    return d - timedelta(days=d.weekday())


def week_span(monday: date) -> tuple[datetime, datetime]:
    """Границы недели для одного запроса к базе, в зоне клиники."""
    start = datetime(monday.year, monday.month, monday.day, tzinfo=eng.TZ)
    return start, start + timedelta(days=7)


def by_day(rows) -> dict:
    """Записи недели по дням. ⚠️ День берётся в зоне КЛИНИКИ: в базе время
    UTC, и запись на 00:30 иначе уехала бы во вчерашнюю колонку."""
    out: dict = {}
    for r in rows or ():
        out.setdefault(r["starts_at"].astimezone(eng.TZ).date(), []).append(r)
    return out


def day_rows(rows) -> list:
    """Живые записи дня по времени: отменённые не показываются вовсе."""
    return sorted((r for r in rows or () if r["status"] != "cancelled"),
                  key=lambda r: r["starts_at"])


def is_note(r) -> bool:
    """Заметка стойки, а не пациент: считается отдельно и рисуется иначе."""
    return r["source"] == "note"


def day_count(rows) -> int:
    """Сколько ПАЦИЕНТОВ в дне — заметки стойки в «programări» не входят."""
    return sum(1 for r in rows if not is_note(r))


def shown_days(monday: date, grouped: dict, today: date, colors) -> list[dict]:
    """Колонки недели по порядку — СПИСКОМ, а не семью позициями.

    `colors` — `routes._svc_colors`: цвет живёт рядом с днём и агендой, второй
    копии правила быть не должно. Передаётся аргументом, потому что импорт из
    `routes` замкнул бы круг.
    """
    out = []
    for i in range(7):
        day = monday + timedelta(days=i)
        rows = day_rows(grouped.get(day, []))
        if not eng.hours_for(day) and not rows:
            continue
        out.append({
            # ⚠️ Дата — СТРОКОЙ одного вида на всех потребителей: разметка,
            # JSON и адрес ссылки. Смешивать `date` и ISO значит однажды
            # передать объект туда, где ждут строку, и узнать об этом от
            # клиники. `dm` — та же дата глазами человека, «18.09».
            "date": day.isoformat(),
            "dm": day.strftime("%d.%m"),
            "label": eng.day_label(eng.Session(lang="ro"), day).split(",")[0].split()[0],
            "count": day_count(rows),
            "today": day == today,
            "open": bool(eng.hours_for(day)),
            "items": [_item(r, colors) for r in rows],
        })
    return out


def _item(r, colors) -> dict:
    """Одна запись глазами недели: час, кто, что и чем красить."""
    hh = r["starts_at"].astimezone(eng.TZ).strftime("%H:%M")
    if is_note(r):
        return {"kind": "note", "time": hh, "text": r["service"][:30]}
    bg, bar = colors(r)
    return {"kind": "appt", "id": r["id"], "time": hh,
            "name": r["name"] or "—", "service": r["service"],
            "noshow": r["status"] == "noshow", "bg": bg, "bar": bar}


def model(monday: date, grouped: dict, today: date, colors) -> dict:
    """Неделя данными: колонки, итог, границы, соседние недели.

    Итог недели — сумма ПАЦИЕНТОВ показанных дней. ⚠️ Считается по тем же
    колонкам, что видны: день, скрытый как пустой выходной, в итог и не
    попадает, потому что в нём нечего считать.
    """
    days = shown_days(monday, grouped, today, colors)
    sunday = monday + timedelta(days=6)
    return {
        "monday": monday.isoformat(),
        "sunday": sunday.isoformat(),
        "prev": (monday - timedelta(days=7)).isoformat(),
        "next": (monday + timedelta(days=7)).isoformat(),
        "span": f"{monday.strftime('%d.%m')} – {sunday.strftime('%d.%m.%Y')}",
        "total": sum(d["count"] for d in days),
        "days": days,
    }
