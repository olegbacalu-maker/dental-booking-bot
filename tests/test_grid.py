"""Контракт СЕТКИ дня (C25): одни данные — одна таблица.

`_grid` строит и «Toți medicii», и день одного врача, то есть расхождение
здесь расходится сразу по двум экранам. Поэтому контракт стоит ОТДЕЛЬНО от
пинов страниц (слово Олега 18.09) и проверяет саму функцию, без сервера:
данные подаются словарями, часы клиники подменяются на время проверки.

Что здесь закрепляется и почему именно это:

* **Ряды — непрерывный диапазон.** `day_slots` выбрасывает обеденный час
  совсем, и таблица прыгала с 12:00 на 14:00 без следа паузы, а запись,
  оказавшаяся в закрытом часу (обед или график поменяли ПОСЛЕ брони), из
  сетки исчезала целиком: час не рисовался — значит, и записи по нему никто
  не спрашивал. В списке дня визит есть, здесь его нет.
* **Закрытый час называет себя:** обед — «pauză», всё остальное — «închis».
* **Ключ записи** — стабильный `doctor_id`, а у легаси-строк без него —
  снимок имени. Врач, переименованный после визита, не должен ни исчезнуть,
  ни попасть в чужую колонку (для этого — `suite_orphan` ниже).
* **«+» врёт трижды**, если о нём не думать: под длинным визитом (там
  «ocupat»), вне часов врача (там пустая ячейка `goff`) и у выключенного
  врача, которому `/admin/add` всё равно ответит отказом.
"""
import pathlib
import re
import sys
from datetime import date, datetime, timedelta

from harness import Result

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app import engine as eng                                    # noqa: E402
from app.modules.schedule.routes import _active_map, _grid       # noqa: E402

DAY = date(2026, 9, 23)          # среда, заведомо не «сегодня»
HOURS = {"mon": [9, 18, 13, 14], "tue": [9, 18, 13, 14], "wed": [9, 18, 13, 14],
         "thu": [9, 18, 13, 14], "fri": [9, 18, 13, 14], "sat": None, "sun": None}


def _row(hour: int, minute: int = 0, **kw) -> dict:
    """Строка записи в том виде, в каком её отдаёт `db.day_appointments`."""
    r = {"id": kw.get("id", hour * 100 + minute), "patient_id": 1,
         "service": kw.get("service", "Consultație"),
         "doctor": kw.get("doctor", "Dr. Activ Doi"),
         "doctor_id": kw.get("doctor_id", "d2"),
         "service_id": "consult",
         "starts_at": datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=eng.TZ),
         "duration_min": kw.get("duration_min", 60),
         "status": kw.get("status", "confirmed"),
         "source": kw.get("source", "panel"),
         "comment": kw.get("comment", ""), "name": kw.get("name", "Ion Popa"),
         "phone": kw.get("phone", "069000000"), "birth_year": kw.get("birth_year"),
         "waiting_at": None, "arrived_at": None, "reminded_day": None,
         "has_rec": False}
    return r


def _cells(html_: str) -> list[list[str]]:
    """Строки таблицы ячейками: первая — час, дальше по врачу.

    ⚠️ Ячейка берётся ЦЕЛИКОМ, вместе с тегом: и класс `goff` (врач не
    принимает), и мишень переноса `data-dk` живут в атрибутах `<td>`, а не в
    содержимом. Разбор, теряющий тег, зеленел бы на обеих проверках по
    неверной причине — `data-dk` нашёлся бы внутри карточки записи.
    """
    out = []
    for tr in re.findall(r"<tr class='hrow[^']*'>(.*?)</tr>", html_, re.S):
        out.append(re.findall(r"(<td[^>]*>.*?</td>)", tr, re.S))
    return out


def _hour_labels(html_: str) -> list[str]:
    return [re.sub(r"<[^>]+>", " ", c).split()[0]
            for c in re.findall(r"<td class='hour[^']*'>(.*?)</td>", html_, re.S)]


def _with_hours(fn):
    """Подменить часы клиники на время проверки и вернуть как было."""
    old = eng.CONFIG.get("hours")
    eng.CONFIG["hours"] = HOURS
    try:
        return fn()
    finally:
        if old is None:
            eng.CONFIG.pop("hours", None)
        else:
            eng.CONFIG["hours"] = old


def _build(rows, items=(("d2", "Dr. Activ Doi"),), cards=None) -> str:
    return _with_hours(lambda: _grid(
        DAY, list(items), _active_map(list(rows)),
        lambda dk, h: f"/x?dk={dk}&h={h}", cards))


def suite_grid(res: Result) -> None:
    """Контракт: диапазон часов, закрытые часы, «+», занятость, карточка."""
    # --- раскладка записей по ячейкам ---
    starts, covered = _active_map([
        _row(10), _row(10, 30, id=1030), _row(12, duration_min=120, id=12),
        _row(15, status="cancelled", id=15),
        _row(16, doctor_id=None, doctor="Dr. Plecat", id=16)])
    res.check("две записи одного часа лежат в одной ячейке",
              [r["id"] for r in starts[("d2", 10)]], [1000, 1030])
    res.check("длинный визит накрывает следующие часы",
              sorted(h for k, h in covered if k == "d2"), [11, 13])
    res.check("отменённая запись в сетку не попадает",
              ("d2", 15) in starts, False)
    res.check("легаси-строка без doctor_id ключуется именем-снимком",
              ("Dr. Plecat", 16) in starts, True)

    # --- диапазон часов и закрытые часы ---
    html_ = _build([_row(20, id=20)])                 # запись ПОСЛЕ закрытия
    labels = _hour_labels(html_)
    res.check("ряды непрерывны от первого часа клиники до часа записи",
              (labels[0], labels[-1], len(labels)), ("09:00", "20:00", 12))
    res.ok("обеденный час назван паузой, а не закрытием",
           "13:00<small>pauză</small>" in html_.replace("'", "'"),
           "обед не подписан как pauză")
    res.ok("час после закрытия назван закрытым",
           ">19:00<small>închis</small>" in html_ or "19:00<small>închis</small>" in html_,
           "закрытый час не подписан")
    res.ok("запись в закрытом часу ВИДНА, а не исчезает",
           "data-appt='20'" in html_, "визит в закрытом часу пропал из сетки")

    # --- «+», занятость, часы врача ---
    html_ = _build([_row(10, duration_min=120, id=10)])
    rows = _cells(html_)
    by_hour = dict(zip(_hour_labels(html_), [r[1] for r in rows]))
    res.ok("свободный рабочий час предлагает «+»",
           "class='free'" in by_hour["09:00"], "нет «+» в свободном часу")
    res.ok("час под длинным визитом говорит «занято», а не «+»",
           "ocupat" in by_hour["11:00"] and "class='free'" not in by_hour["11:00"],
           "под длинным визитом нарисован «+»")
    res.ok("обед у врача — пустая ячейка без «+»",
           "goff" in by_hour["13:00"], "в обед предлагается запись")
    res.ok("мишень переноса есть и у занятой ячейки",
           by_hour["10:00"].startswith("<td data-dk="),
           "в занятый час нельзя перенести")
    # закрытый час есть только там, где запись вытянула диапазон за график
    late = _build([_row(20, id=20)])
    by_late = dict(zip(_hour_labels(late), [r[1] for r in _cells(late)]))
    res.ok("у закрытого часа мишени переноса нет",
           "data-dk=" not in by_late["19:00"], "перенос в закрытый час разрешён")
    res.ok("закрытый час у врача — пустая ячейка",
           "class='goff'" in by_late["19:00"], "в закрытый час предлагается «+»")

    # --- карточка записи ---
    urgent_label = sorted(eng.URGENT_LABELS)[0]
    html_ = _build([_row(10, id=7, name="Maria <b>", service=urgent_label,
                         comment="sună înainte", birth_year=1990,
                         source="bot", status="waiting", duration_min=45)])
    card = _cells(html_)[1][1]
    res.check("имя пациента экранировано", "Maria &lt;b&gt;" in card, True)
    res.ok("на карточке час, длительность и телефон",
           "10:00 · Maria" in card and "(45′)" in card and "069000000" in card,
           "карточка потеряла содержимое")
    res.ok("статус написан СЛОВОМ, а не только цветом",
           "class='stat s-waiting'" in card, "статус только цветом")
    res.ok("срочная услуга помечена — по подписи из справочника клиники",
           "urgent" in card, f"«{urgent_label}» не считается срочной")
    res.ok("комментарий стойки виден", "sună înainte" in card, "комментарий потерян")
    res.ok("возраст пациента показан", "36 a." in card, "возраст не посчитан")

    # confirmed — базовое состояние: бейджа у него нет
    plain = _cells(_build([_row(10, id=8)]))[1][1]
    res.ok("у подтверждённой записи бейджа статуса нет",
           "class='stat s-confirmed'" not in plain, "бейдж на каждой карточке — шум")

    # заметка стойки — своим видом и без телефона
    note = _cells(_build([_row(10, id=9, source="note", service="Livrare")]))[1][1]
    res.check("заметка стойки рисуется отдельным видом",
              ("appt note" in note, "069000000" in note), (True, False))

    # --- «сегодня» подсвечивается, чужой день — нет ---
    res.ok("на чужом дне текущий час не подсвечен",
           "hrow now" not in _build([_row(10)]), "подсветка часа уехала на чужой день")
    # ⚠️ Текущий час может лежать ВНЕ графика клиники (проверка идёт и ночью),
    # и тогда строки для него просто нет. Кладём в этот час запись: диапазон
    # рядов тянется до неё, и строка существует в любое время суток.
    now = datetime.now(eng.TZ)
    today_row = dict(_row(10), id=999,
                     starts_at=now.replace(minute=0, second=0, microsecond=0))
    html_today = _with_hours(lambda: _grid(
        now.date(), [("d2", "Dr. Activ Doi")], _active_map([today_row]),
        lambda dk, h: "/x", None))
    # ⚠️ Класс ряда бывает «hrow off now»: у закрытого часа «off» идёт первым,
    # и поиск подстроки «hrow now» пропустил бы подсветку мимо графика.
    now_rows = [c for c in re.findall(r"<tr class='(hrow[^']*)'>", html_today)
                if " now" in c]
    res.check("на сегодняшнем дне подсвечен ровно один час", len(now_rows), 1)
    res.ok("подсвечен именно текущий час",
           _hour_labels(html_today)[
               [i for i, c in enumerate(re.findall(r"<tr class='(hrow[^']*)'>", html_today))
                if " now" in c][0]] == now.strftime("%H:00"),
           "подсветка стоит не на том часе")

    # --- детерминированность: одни данные — одна строка ---
    rows_in = [_row(10, id=1), _row(11, id=2, status="noshow")]
    res.ok("одни данные дают побайтово одну сетку",
           _build(rows_in) == _build(rows_in),
           "сетка меняется сама по себе — живой протокол подменял бы её каждый опрос")


def suite_doctors(res: Result) -> None:
    """Измерение врача: порядок, несколько колонок, чужие записи, пустота."""
    items = [("d2", "Dr. Activ Doi"), ("d3", "Dr. Activ Trei")]
    html_ = _build([_row(10, id=1), _row(11, id=2, doctor_id="d3",
                                         doctor="Dr. Activ Trei")], items)
    heads = re.findall(r"<a class='dh-n'[^>]*>([^<]+)</a>", html_)
    res.check("колонки идут в порядке, который дали", heads,
              ["Dr. Activ Doi", "Dr. Activ Trei"])
    res.ok("шапка колонки ведёт в день этого врача",
           f"/admin/doctor/d2?date={DAY.isoformat()}" in html_, "нет ссылки на день врача")
    rows = _cells(html_)
    res.check("в каждой строке ячеек по числу врачей плюс час",
              {len(r) for r in rows}, {3})
    ten = dict(zip(_hour_labels(html_), rows))["10:00"]
    res.check("запись стоит у СВОЕГО врача, у соседа в этот час свободно",
              ("data-appt='1'" in ten[1], "class='free'" in ten[2]), (True, True))

    res.ok("день без записей — сетка есть, записей нет",
           "<table class='grid'" in _build([], items) and "data-appt" not in _build([], items),
           "пустой день ломает сетку")

    # ⚠️ Запись врача, которого НЕТ в колонках, не попадает в чужую ячейку.
    html_ = _build([_row(10, id=5, doctor_id="d9", doctor="Dr. Nimeni")], items)
    res.ok("запись чужого врача не показывается под своим",
           "data-appt='5'" not in html_, "визит уехал в чужую колонку")


def suite_orphan(res: Result) -> None:
    """Легаси-имя без `doctor_id`: не исчезает и не попадает к другому врачу.

    ⚠️ Так выглядят записи, созданные до v1.7.1, и записи врача, которого
    переименовали: `doctor_id` пуст, а в строке лежит СНИМОК имени. Сетка
    ищет по обоим ключам (`starts.get((dk, h)) or starts.get((dname, h))`),
    и обе половины этого «или» несущие.
    """
    items = [("d2", "Dr. Activ Doi"), ("d3", "Dr. Activ Trei")]
    orphan = _row(10, id=77, doctor_id=None, doctor="Dr. Activ Doi")
    html_ = _build([orphan], items)
    rows = dict(zip(_hour_labels(html_), _cells(html_)))
    res.ok("легаси-запись находится по снимку имени",
           "data-appt='77'" in rows["10:00"][1],
           "запись без doctor_id исчезла из сетки")
    res.ok("и не дублируется у соседнего врача",
           "data-appt='77'" not in rows["10:00"][2], "запись видна дважды")

    # имя, которого в справочнике уже нет вовсе: колонки под него нет, и
    # запись не должна прилипнуть к первому попавшемуся врачу
    gone = _row(11, id=78, doctor_id=None, doctor="Dr. Plecat Demult")
    html_ = _build([gone], items)
    res.ok("имя, которого нет в справочнике, не попадает в чужую колонку",
           "data-appt='78'" not in html_,
           "запись ушедшего врача показана под действующим")

    # ⚠️ Ключ важнее подписи: у записи с ЖИВЫМ doctor_id снимок имени может
    # быть старым, и колонка выбирается по id, а не по строке.
    renamed = _row(12, id=79, doctor_id="d3", doctor="Старое Имя")
    html_ = _build([renamed], items)
    rows = dict(zip(_hour_labels(html_), _cells(html_)))
    res.ok("переименованный врач: запись у своей колонки по id",
           "data-appt='79'" in rows["12:00"][2] and "data-appt='79'" not in rows["12:00"][1],
           "запись ушла не к тому врачу после переименования")
