"""Правая колонка панели дня: правила, из которых она строится. Разметки нет.

Канва отвечает «кто когда свободен», правая колонка — «что дальше» и «как идёт
день». Переезжает она отдельно от канвы и по одному блоку: повестка, плитки с
трендами, мини-календарь. Порядок задан ЦЕНОЙ ПОЛОМКИ, а не удобством —
повестку читают весь день, и она несёт `past`, которого в модели канвы нет
вовсе.

⛔ Колокольчика и «Programări noi din bot» здесь НЕТ и не будет, пока бот
заморожен: оба блока живут за `layout.tg_configured()`, и у клиники не
рисуются. Модель для невидимого блока — это поле, которое никто не проверит
глазами, и первая же правка сломает его молча.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ... import engine as eng
from ...core.layout import STATUS_LABEL

# Класс бейджа по статусу — тот же словарь, что печатает страница.
# ⚠️ `_AG_CLS` живёт в `routes` рядом с разметкой, и второй его копии здесь
# быть не должно: он приезжает аргументом из того же места, что и цвета.


def agenda_state(d: date, starts: datetime, dur_min: int,
                 now: datetime) -> str | None:
    """Где визит относительно «сейчас»: `future` / `current` / `past`.

    ⛔ Три значения, а не CSS-класс: React обязан знать СОСТОЯНИЕ, а не
    догадываться о нём по имени класса. У канвы этой семантики нет вовсе —
    там час либо текущий, либо нет, — и собранная из канвы повестка потеряла бы
    различие «уже было» и «ещё будет» молча.
    ⚠️ `None` для ЧУЖОГО дня, и это не забывчивость: страница приглушает
    прошедшее только на сегодня («в чужом дне „прошло" не значит ничего, а
    тусклый список читался бы как отменённый»). Модель повторяет ровно это.
    ⚠️ Состояние меняется ДВАЖДЫ за визит — на старте и на конце. Оба перехода
    дискретны и потому законны для живого канала: отпечаток меняется, когда на
    экране действительно меняется слово. Непрерывное (минуты ожидания) сюда не
    попадает никогда — его считает браузер по отметке времени.
    """
    if d != now.date():
        return None
    if starts + timedelta(minutes=dur_min) <= now:
        return "past"
    return "current" if starts <= now else "future"


def agenda(d: date, rows: list, cards: dict | None, colors, ag_cls: dict,
           now: datetime) -> dict:
    """«Agenda de azi» данными: тот же день списком и по времени.

    ⚠️ Порядок — ПО ВРЕМЕНИ старта, и это не то же самое, что порядок канвы:
    там строки разложены по колонкам врачей. Список отвечает «что дальше»
    одному человеку у стойки.
    ⛔ Заметки стойки и отменённые сюда не попадают — как и на странице.
    ⛔ Слово статуса приходит ГОТОВЫМ (`STATUS_LABEL`, с заглавной): второй
    словарь статусов в браузере — это «Finalizat» в одном месте и «a venit» в
    другом, ломалось дважды (08-12, 08-16).
    ⛔ «Urgent» исчезает у ЗАВЕРШЁННОГО визита: срочность — про то, что визита
    ждут, а не про то, каким он был. Ветка живёт на `status == "confirmed"`, и
    ветка эта сегодня не исполняется ни одним пином — фикстура обязана её
    заводить.
    """
    items = sorted((r for r in rows
                    if r["status"] != "cancelled" and r["source"] != "note"),
                   key=lambda r: r["starts_at"])
    out = []
    for r in items:
        st = r["starts_at"].astimezone(eng.TZ)
        dur = int(r.get("duration_min") or 60)
        urgent = r["service"] in eng.URGENT_LABELS and r["status"] == "confirmed"
        cls, label = (("bad", "Urgent") if urgent else
                      (ag_cls.get(r["status"], "off"),
                       STATUS_LABEL.get(r["status"], r["status"]).capitalize()))
        _bg, bar = colors(r)
        out.append({
            "id": r["id"], "time": st.strftime("%H:%M"), "dur": dur,
            "name": r["name"] or "—", "service": r["service"],
            "status": r["status"], "badge": {"cls": cls, "label": label},
            "urgent": urgent, "bar": bar,
            "state": agenda_state(d, st, dur, now),
            "clickable": bool(cards is not None and r["id"] in cards),
            # ⛔ Кнопка одонтограммы — ТОЛЬКО у визита с пациентом: у записи без
            # него (легаси-строка) ссылка вела бы на `/admin/patient/None/…`.
            # ⚠️ Всплытие клика она обязана останавливать и в React: строка
            # кликабельна целиком, и без этого одно нажатие делало бы два
            # действия — открывало карточку ЗАОДНО с одонтограммой.
            "patient_id": r.get("patient_id") or None,
            # ⛔ Только ОТМЕТКА времени, никогда не строка «N min»: серверный
            # текст с минутами менял бы отпечаток живого состояния каждую
            # минуту, и подмена шла бы на каждый опрос — мигание чёрным ходом.
            "wait_since": (int(r["waiting_at"].timestamp() * 1000)
                           if r["status"] == "waiting" and r.get("waiting_at")
                           else None),
        })
    return {"count": len(out), "today": d == now.date(), "items": out}


# ---- плитки «Azi» и их тренды ----------------------------------------------

# Длина ряда мини-графика. ⚠️ Константа живёт ЗДЕСЬ, рядом с правилом, которое
# её читает: вторая копия в разметке однажды разошлась бы, и ряд под цифрой
# оказался бы не про тот период, про который подпись.
SPARK_DAYS = 14


def spark_span(d: date) -> list:
    """Две недели, ЗАКАНЧИВАЮЩИЕСЯ днём `d`: от старого к новому.

    ⚠️ Порядок несущий: перевёрнутый ряд нарисовал бы рост как падение, и
    проверка «значения те же» этого не заметила бы — множество то же.
    """
    return [d - timedelta(days=SPARK_DAYS - 1 - i) for i in range(SPARK_DAYS)]


def series_of(by_day: dict, span: list) -> list:
    """Ряды по метрикам: пять списков длиной в `span`, в том же порядке."""
    return [list(x) for x in zip(*(counts(by_day[x]) for x in span))]


def counts(rows: list) -> tuple[int, int, int, int, int]:
    """(всего, из бота, с ресепшена, срочных, неявок) за день.

    ⚠️ Знаменатели разные: первые четыре считают ЖИВЫЕ записи (без отменённых
    и без заметок стойки), а неявки — по статусу среди ВСЕХ строк. Свести к
    одному списку значило бы либо потерять неявки, либо посчитать заметку
    записью.
    """
    a = [r for r in rows if r["status"] != "cancelled" and r["source"] != "note"]
    return (len(a), sum(1 for r in a if r["source"] == "bot"),
            sum(1 for r in a if r["source"] == "manual"),
            sum(1 for r in a if r["service"] in eng.URGENT_LABELS),
            sum(1 for r in rows if r["status"] == "noshow"))


def occupancy_pct(day: date, rows: list, active_dks: list) -> int:
    """Загрузка кресел за день: занятые минуты / рабочие минуты АКТИВНЫХ врачей.

    ⚠️ Ёмкость берётся у того же `eng.work_minutes`, что считает карточку врача
    и «Statistici»: три места не имеют права назвать три разных процента про
    один и тот же день.
    ⛔ Потолок сотней: перебронированный день на этой полосе показал бы больше
    ста процентов ширины. ⚠️ У ПЛИТКИ врача потолка нет — там «130%» и есть
    ответ; здесь величина сводная и полоса общая.
    """
    cap = sum(eng.work_minutes(dk, day) for dk in active_dks)
    if not cap:
        return 0
    busy = sum(int(r.get("duration_min") or 60) for r in rows
               if r["status"] != "cancelled" and r["source"] != "note")
    return min(round(100 * busy / cap), 100)


def delta(cur: int, prev: int, bad_up: bool = False) -> dict:
    """Сравнение со вчера: `same` или `delta` с НАПРАВЛЕНИЕМ.

    ⛔ Полярность считается ЗДЕСЬ и только здесь. Для записей рост — это `up`,
    а для НЕЯВОК рост — это `dn`: «неявок стало больше» не может выглядеть
    хорошей новостью. Общая функция направления, не знающая про `bad_up`,
    однажды заберёт неявки себе, и стрелка позеленеет на росте неявок — молча,
    потому что цифра при этом верная и меняется правильно.
    ⚠️ Направление приезжает ГОТОВЫМ (`up`/`dn`), а не выводится клиентом из
    знака разницы: вывод по знаку — это и есть та самая общая функция.
    """
    diff = cur - prev
    if diff == 0:
        return {"kind": "same", "diff": 0, "dir": None, "text": "la fel ca ieri"}
    up = diff > 0
    return {"kind": "delta", "diff": diff, "text": "față de ieri",
            "dir": ("dn" if bad_up else "up") if up else ("up" if bad_up else "dn")}


# Плитки в том же порядке, что печатает карточка «Azi». ⛔ `filter` у первой
# пустой НАМЕРЕННО: «Programări» — это весь день, и ссылка ведёт в полный
# список. Раздай всем один адрес с отбором, и счётчик перестанет сходиться с
# тем, что открывается по клику.
_TILES = (
    ("total", "Programări", "cal", "green", None, "", False),
    ("bot", "Prin bot", "bot", "teal", "bot", "", False),
    ("rec", "Recepție", "headset", "blue", "rec", "", False),
    ("urg", "Urgențe", "alarm", "amber", "urg", " warn", False),
    ("noshow", "Neprezentări", "ban", "red", "noshow", " bad", True),
)
# Индекс метрики в `counts` по ключу плитки.
_TILE_AT = {"total": 0, "bot": 1, "rec": 2, "urg": 3, "noshow": 4}


def tiles(d: date, cur: tuple, prev: tuple, series: list, tg_on: bool,
          bot_new: int) -> list[dict]:
    """Плитки «Azi» СПИСКОМ, а не набором именованных полей.

    ⛔ Список, потому что плиток у клиники ЧЕТЫРЕ или пять: «Prin bot» живёт за
    `tg_configured()` и у клиники с замороженным ботом не рисуется вовсе.
    Фиксированные пять позиций дали бы React дыру на месте четвёртой, и он
    честно нарисовал бы пустую плитку там, где её нет на старом экране.
    ⚠️ У «Urgențe» тренда НЕТ — у неё своя постоянная подпись. Это ЧЕТВЁРТАЯ
    форма подписи (считая загрузку кресел), и сводить их к одной функции
    нельзя: «столько же, сколько вчера», «на столько-то больше», «вперемешку
    сегодня» и «было → стало» отвечают на разные вопросы.
    """
    day_url = f"/admin/all?date={d.isoformat()}"
    out = []
    for key, label, icon, hue, flt, cls, bad_up in _TILES:
        if key == "bot" and not tg_on:
            continue
        i = _TILE_AT[key]
        if key == "urg":
            sub = {"kind": "static", "text": "intercalate azi"}
        elif key == "bot":
            sub = ({"kind": "bot_new", "new": bot_new, "text": "azi"} if bot_new
                   else {"kind": "static", "text": "nimic nou azi"})
        else:
            sub = delta(cur[i], prev[i], bad_up)
        out.append({
            "key": key, "label": label, "value": cur[i], "icon": icon,
            "soft": f"var(--{hue}-soft)", "tone": f"var(--{hue})",
            "filter": flt, "href": day_url + (f"&f={flt}" if flt else ""),
            "cls": cls.strip(), "sub": sub, "series": list(series[i]),
        })
    return out


def occupancy(d: date, now: datetime, occ: int, occ_prev: int,
              prev_open: bool, series: list) -> dict:
    """Загрузка кресел: «было → стало», а не разница в пунктах.

    ⚠️ Две величины, а не «+16 pp»: процентные пункты пришлось объяснять даже
    Олегу, и регистратура не обязана знать эту единицу.
    ⚠️ Слова «ieri/azi» — только на СЕГОДНЯШНЕЙ странице: журнал умеет
    показывать любой день, и там честнее даты.
    ⛔ Закрытый вчера день говорит «închis», а не «0%»: ноль процентов — это
    «работали и простояли», и на выходном он читался бы как провал.
    """
    prev_day = d - timedelta(days=1)
    a_lbl, b_lbl = (("ieri", "azi") if d == now.date()
                    else (prev_day.strftime("%d.%m"), d.strftime("%d.%m")))
    return {
        "label": "Grad de ocupare", "icon": "trend",
        "soft": "var(--violet-soft)", "tone": "var(--violet)",
        "value": occ, "series": list(series),
        "from": {"label": a_lbl, "value": f"{occ_prev}%" if prev_open else "închis"},
        "to": {"label": b_lbl, "value": f"{occ}%"},
        "dir": "up" if occ > occ_prev else "dn" if occ < occ_prev else None,
    }


# ---- мини-календарь месяца --------------------------------------------------

# Дни недели в шапке. ⚠️ Тоже ДАННЫЕ: свой список в браузере — это второй
# словарь, и он разойдётся в первый же день, когда кто-то решит сократить
# «Sâmbătă» иначе.
WEEKDAYS = ("Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du")


def minical(sel: date, today: date, months, base: str = "/admin") -> dict:
    """Месяц ПОЛНЫМИ неделями Пн–Вс, с тремя метками и соседями.

    ⛔ Недели полные, и первая начинается с понедельника, даже если он из
    прошлого месяца. Обрежь её — и числа поедут по столбцам: вторник встанет
    под средой, и календарь будет врать молча, оставаясь красивым.
    ⚠️ Недель бывает ПЯТЬ или шесть, и число это не константа: сентябрь 2026
    начинается во вторник и укладывается в пять. Раскладка по шести строкам
    дала бы пустую шестую, а по пяти — потеряла бы хвост длинного месяца.
    ⚠️ Метки ТРИ и они независимы: «чужой месяц», «сегодня» и «выбранный».
    Один и тот же день бывает сразу и сегодняшним, и выбранным, и на соседний
    месяц это тоже распространяется — склей их в одно поле, и день из хвоста
    предыдущего месяца перестанет подсвечиваться как сегодняшний.
    ⚠️ `today` приходит АРГУМЕНТОМ, а не берётся из часов: иначе проверке
    пришлось бы гадать о дне, а на живом канале эта величина ещё и меняется
    раз в сутки — пусть её называет тот, кто знает момент.
    """
    first = sel.replace(day=1)
    prev_m = (first - timedelta(days=1)).replace(day=1)
    # ⚠️ +32 дня, а не +1 месяц: в феврале прибавление месяца арифметикой дат
    # промахивается мимо короткого месяца, а тридцать два дня перепрыгивают
    # любой и всегда попадают в следующий.
    next_m = (first + timedelta(days=32)).replace(day=1)
    cells: list[dict] = []
    cur = first - timedelta(days=first.weekday())
    while cur.month == sel.month or cur <= first or len(cells) % 7 != 0:
        cells.append({"date": cur.isoformat(), "day": cur.day,
                      "other": cur.month != sel.month,
                      "today": cur == today, "selected": cur == sel,
                      "href": f"{base}?date={cur.isoformat()}"})
        cur += timedelta(days=1)
    return {
        "title": f"{months[sel.month - 1]} {sel.year}",
        "weekdays": list(WEEKDAYS),
        "weeks": [cells[i:i + 7] for i in range(0, len(cells), 7)],
        # ⛔ Соседние месяцы ведут на ПЕРВОЕ ЧИСЛО, а не на тот же день-номер:
        # 31 марта минус месяц не существует, и адрес на «31 февраля» открыл бы
        # не тот месяц или отказ.
        "prev": {"date": prev_m.isoformat(), "href": f"{base}?date={prev_m.isoformat()}"},
        "next": {"date": next_m.isoformat(), "href": f"{base}?date={next_m.isoformat()}"},
    }
