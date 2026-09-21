"""Аналитика директора ДАННЫМИ: все цифры раздела, без единой строки разметки.

Из `routes.py` сюда вынесено ровно то, что СЧИТАЕТ, — старая страница теперь
рисует эту же модель, а JSON API отдаёт её как есть. Второй экземпляр расчётов
разошёлся бы с первым молча: цифры выглядят правдоподобно всегда.

⚠️ Считается здесь, а не в базе: в `db.py` нет ни одного агрегата. Цифры
собираются из дневных выборок и прайса из `clinic.json`, поэтому «выручка» —
это ОЦЕНКА ПО ПРАЙСУ, а не бухгалтерия. Настоящие деньги — только `Încasări`,
их пишет регистратура.

⭐ Каждый период сравнивается С ТАКИМ ЖЕ ПО ДЛИНЕ куском сразу перед ним: у
недели это прошлая неделя, у «сегодня» — вчера. Сравнение с «прошлым месяцем»
для произвольного периода врало бы — периоды разной длины несравнимы.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ... import db
from ... import engine as eng
from ...core.layout import tg_configured

# Цвет плитки и её мягкая подложка. ⛔ Цвета СМЫСЛА теме не отдаются: красные
# отмены и зелёные записи — это значение, а не персонализация.
_SOFT = {"var(--green)": "var(--green-soft)", "var(--teal-d)": "var(--teal-soft)",
         "var(--blue)": "var(--blue-soft)", "var(--violet)": "var(--violet-soft)",
         "var(--red)": "var(--red-soft)", "var(--amber)": "var(--amber-soft)"}

# Плитки макета: ключ, подпись, значок, цвет, «рост — это плохо».
_TILES = (("total", "Programări", "cal", "var(--green)", False),
          ("bot", "Prin bot", "bot", "var(--teal-d)", False),
          ("man", "Recepție", "headset", "var(--blue)", False),
          ("done", "Au venit", "checkin", "var(--violet)", False),
          ("cancel", "Anulate", "ban", "var(--red)", True),
          ("rem", "Remindere", "bell", "var(--amber)", False))

# Границы периода. `_parse_date` проверяет только СИНТАКСИС даты, а
# `<input type=date>` отдаёт и «0012-08-15»: промах по сегменту года — законная
# ISO-дата. Без границ из неё выходил период в 735 000 дней, и вычитание такого
# срока падало OverflowError прямо в маршруте: под BaseHTTPMiddleware это не
# 500, а страница, которая не отвечает вовсе. Мягкий вариант той же дыры —
# «1900-01-01»: арифметика проходит, а график рисует 46 000 точек на спарклайн.
# ⛔ Верхняя граница считается от СЕГОДНЯ, а не по календарю: будущие записи
# смотрят вперёд, и год запаса им хватает.
FIRST_DAY = date(2000, 1, 1)
MAX_DAYS = 366                    # год — самый длинный осмысленный период


def fmt_mdl(x: int) -> str:
    """Деньги строкой для человека. ⚠️ Разделитель тысяч повторяет `panel.js`
    и клиентский `groupThousands`: счётчик переписывает текст на каждом кадре
    и спросить формат у сервера не может."""
    return f"{x:,}".replace(",", " ") + " MDL"


def period_ok(d1: date, d2: date, today: date) -> bool:
    """Годен ли период. Проверка ДО построения списка дней: список на 735 000
    дней собирается раньше, чем падает арифметика, и память он занимает уже
    настоящую."""
    return not (d1 < FIRST_DAY or d2 > today + timedelta(days=MAX_DAYS)
                or (d2 - d1).days + 1 > MAX_DAYS)


def compare_label(span: int) -> str:
    """Прошлый период — ПО ИМЕНИ, а не «perioada trecută»: безымянное сравнение
    уже дважды озадачивало Олега (загрузка 3%, «vs. perioada trecută (0)»)."""
    if span == 1:
        return "față de ziua precedentă"
    if span == 7:
        return "față de săptămâna trecută"
    if 28 <= span <= 31:
        return "față de luna trecută"
    return f"față de precedentele {span} zile"


def price(r) -> int:
    """Цена: по стабильному service_id (не зависит от языка/переименований),
    для легаси-строк — по подписи."""
    sid = r.get("service_id")
    if sid and sid in eng.SERVICE_PRICE_BY_ID:
        return eng.SERVICE_PRICE_BY_ID[sid]
    return eng.SERVICE_PRICE.get(r["service"], 0)


def agg(rows: list) -> dict:
    """Все цифры одного периода — из одной выборки, одним проходом."""
    appts = [r for r in rows if r["source"] != "note"]
    act = [r for r in appts if r["status"] != "cancelled"]
    return {
        "total": len(act),
        "bot": sum(1 for r in act if r["source"] == "bot"),
        "man": sum(1 for r in act if r["source"] == "manual"),
        "web": sum(1 for r in act if r["source"] not in ("bot", "manual")),
        # «пришли» = завершённые + в кабинете + ждущие в приёмной (waiting):
        # человек физически в клинике, для «Au venit» это уже факт
        "done": sum(1 for r in act if r["status"] in ("done", "arrived", "waiting")),
        "noshow": sum(1 for r in act if r["status"] == "noshow"),
        "cancel": len(appts) - len(act),
        "rem": sum(1 for r in appts if r["reminded_day"]),
        "value": sum(price(r) for r in act if r["status"] != "noshow"),
        "loss": sum(price(r) for r in act if r["status"] == "noshow"),
        # ⚠️ ТОТ ЖЕ фильтр, что у "value": подпись «botul a adus» печатается на
        # карточке «Venituri estimate», и неявка, оставленная в ней, объявляла
        # часть больше целого — та же 1000 MDL шла и в выручку бота, и в
        # «pierdut» соседнего блока
        "bot_value": sum(price(r) for r in act
                         if r["source"] == "bot" and r["status"] != "noshow"),
        "act": act,
    }


def trend(cur: int, prev: int, bad_up: bool, label: str) -> dict:
    """Сравнение с предыдущим периодом той же длины — КУСКАМИ.

    ⛔ `dir` — это НЕ знак числа: рост неявок и отмен плохой, и стрелка вверх
    у него красная. Вычисли цвет из знака на экране — и он позеленел бы ровно
    там, где всё плохо.
    ⚠️ От нуля процентов нет: «+∞%» — не цифра, а шум, поэтому такой случай
    показывает разницу штуками и говорит вслух, что тогда было ноль.
    """
    if cur == prev:
        return {"dir": "", "icon": "", "value": "", "label": label, "note": ""}
    if not prev:
        return {"dir": "dn" if bad_up else "up", "icon": "", "value": f"+{cur}",
                "label": label, "note": " (atunci 0)"}
    pct = (cur - prev) * 100 / prev
    up = pct > 0
    return {"dir": ("dn" if bad_up else "up") if up else ("up" if bad_up else "dn"),
            "icon": "caret-u" if up else "caret-d",
            "value": f"{abs(pct):.0f}%", "label": label, "note": ""}


def trend_money(cur: int, prev: int, label: str) -> dict:
    """Деньги сравниваем В ДЕНЬГАХ, не в процентах: директору «+2 550 MDL»
    говорит больше, чем «+100%», а нулевая прошлая неделя не ломает формулу."""
    if cur == prev:
        return {"dir": "", "icon": "", "value": "", "label": label, "note": ""}
    diff = cur - prev
    return {"dir": "up" if diff > 0 else "dn",
            "icon": "caret-u" if diff > 0 else "caret-d",
            "value": ("+" if diff > 0 else "-") + fmt_mdl(abs(diff)),
            "label": label, "note": ""}


def _dm(d: date) -> str:
    return d.strftime("%d.%m")


async def build(d1: date, d2: date, today: date) -> dict:
    """Модель раздела целиком. Одна на старую страницу и на JSON."""
    days = [d1 + timedelta(days=i) for i in range((d2 - d1).days + 1)]
    span = len(days)

    # период + такой же по длине кусок ПЕРЕД ним — одним запросом
    p1 = d1 - timedelta(days=span)
    start_all = datetime(p1.year, p1.month, p1.day, tzinfo=eng.TZ)
    end = datetime(d2.year, d2.month, d2.day, tzinfo=eng.TZ) + timedelta(days=1)
    all_rows = await db.day_appointments(start_all, end)
    split = datetime(d1.year, d1.month, d1.day, tzinfo=eng.TZ)
    cur = agg([r for r in all_rows if r["starts_at"] >= split])
    prev = agg([r for r in all_rows if r["starts_at"] < split])
    plabel = compare_label(span)

    by_day: dict[date, int] = {x: 0 for x in days}
    for r in cur["act"]:
        by_day[r["starts_at"].astimezone(eng.TZ).date()] += 1
    day_vals = [by_day[x] for x in days]

    # спарклайн каждой плитки — её же ряд по дням текущего периода
    per_day: dict[str, list[int]] = {k: [0] * span for k, *_ in _TILES}
    idx = {x: i for i, x in enumerate(days)}
    for r in cur["act"]:
        i = idx[r["starts_at"].astimezone(eng.TZ).date()]
        per_day["total"][i] += 1
        if r["source"] == "bot":
            per_day["bot"][i] += 1
        elif r["source"] == "manual":
            per_day["man"][i] += 1
        if r["status"] in ("done", "arrived", "waiting"):
            per_day["done"][i] += 1
        if r["reminded_day"]:
            per_day["rem"][i] += 1
    for r in [r for r in all_rows if r["starts_at"] >= split
              and r["source"] != "note" and r["status"] == "cancelled"]:
        per_day["cancel"][idx[r["starts_at"].astimezone(eng.TZ).date()]] += 1

    # Telegram заморожен (tg_configured): у клиники без бота нет ни канала
    # «Prin bot», ни напоминаний — плитки и донат источников прячутся.
    # per_day выше собирается по ПОЛНОМУ списку намеренно: у клиники со
    # снятым токеном исторические бот-записи не должны ронять цикл KeyError-ом
    tg_ui = tg_configured()
    tiles = [{"key": key, "label": lbl, "value": cur[key], "icon": ico,
              "tone": tone, "soft": _SOFT[tone], "bad": bad,
              "series": per_day[key],
              "trend": trend(cur[key], prev[key], bad, plabel)}
             for key, lbl, ico, tone, bad in _TILES
             if tg_ui or key not in ("bot", "rem")]

    # ---- график по дням ----
    present_pct = round(100 * cur["done"] / cur["total"]) if cur["total"] else 0
    # Время ожидания в приёмной (08-13): пары штампов waiting_at → arrived_at.
    # Считаются только визиты, где регистратура отметила ОБА шага — перескок
    # confirmed→arrived пары не даёт, и это честно: мерить там нечего.
    waits = [(r["arrived_at"] - r["waiting_at"]).total_seconds() / 60
             for r in cur["act"]
             if r.get("waiting_at") and r.get("arrived_at")
             and r["arrived_at"] >= r["waiting_at"]]
    chart = {
        "labels": [_dm(x) for x in days],
        "values": day_vals,
        "title": "Programări pe zile",
        "sub": f"· {_dm(d1)} — {d2.strftime('%d.%m.%Y')}",
        "total": cur["total"],
        "total_trend": trend(cur["total"], prev["total"], False, plabel),
        "present_pct": present_pct,
        "noshow": cur["noshow"],
        "loss": f"cca {fmt_mdl(cur['loss'])} pierdut",
        "wait": {
            "text": f"{round(sum(waits) / len(waits))} min" if waits else "—",
            "sub": (f"{len(waits)} vizite măsurate" if waits
                    else "se măsoară din «A venit» › «În cabinet»"),
        },
    }

    # ---- источники: только те, что программа ЗНАЕТ ----
    # ⛔ Google и Instagram здесь нет и не будет: программа таких источников не
    # знает, а нарисованное число директор примет за правду и решит про рекламу.
    src = [("Telegram", cur["bot"], "var(--teal)"),
           ("Recepție", cur["man"], "var(--blue)"),
           ("Web-chat", cur["web"], "var(--violet)")]
    sources = {
        # один источник — не разбивка, а тавтология
        "show": tg_ui,
        "total": cur["total"],
        "parts": [{"label": lbl, "value": val, "color": color,
                   "pct": round(100 * val / cur["total"]) if cur["total"] else 0}
                  for lbl, val, color in src],
    }

    # ---- загрузка и врачи ----
    cap_all = busy_all = 0
    doctors = []
    for dk, name in eng.DOCTORS.items():
        mine = [r for r in cur["act"] if r.get("doctor_id") == dk
                or (not r.get("doctor_id") and r["doctor"] == name)]
        off = not eng.DOCTOR_META.get(dk, {}).get("active", True)
        if off and not mine:
            continue   # выключенный врач без записей за период — не мусорим нулями
        came = sum(1 for r in mine if r["status"] in ("done", "arrived", "waiting"))
        cap = sum(eng.work_minutes(dk, day) for day in days)
        busy = sum(int(r.get("duration_min") or 60) for r in mine)
        if not off:
            cap_all += cap
            busy_all += busy
        doctors.append({"name": name, "off": off, "n": len(mine), "came": came,
                        "pres": round(100 * came / len(mine)) if mine else 0,
                        "pct": round(100 * busy / cap) if cap else 0})
    doctors.sort(key=lambda x: -x["pct"])
    # период называется ЦИФРАМИ прямо на карточке: «media pe perioadă» без дат
    # уже озадачила Олега — 3% за неделю выглядят ошибкой рядом с 86% за день
    occupancy = {
        "pct": round(100 * busy_all / cap_all) if cap_all else 0,
        "note": (f"media {_dm(d1)}–{_dm(d2)} ({span} zile) · minute ocupate din "
                 f"minutele de lucru ale medicilor activi"),
    }

    # ---- деньги ----
    # выручка ЗА СЕГОДНЯ — всегда про сегодня, какой бы период ни был выбран
    # сверху (идея Олега 08-07: пустое место под карточкой периода)
    y0 = today - timedelta(days=1)
    t_rows = await db.day_appointments(
        datetime(y0.year, y0.month, y0.day, tzinfo=eng.TZ),
        datetime(today.year, today.month, today.day, tzinfo=eng.TZ)
        + timedelta(days=1))
    t_split = datetime(today.year, today.month, today.day, tzinfo=eng.TZ)
    tv = agg([r for r in t_rows if r["starts_at"] >= t_split])["value"]
    yv = agg([r for r in t_rows if r["starts_at"] < t_split])["value"]

    # ⭐ Încasări — НАСТОЯЩИЕ деньги (модуль финансов, 08-07): оценка по прайсу
    # выше это прогноз, а здесь то, что реально записала регистратура.
    pays = await db.payments_range(start_all, end)
    inc_cur = sum(p["amount_mdl"] for p in pays if p["at"] >= split)
    inc_prev = sum(p["amount_mdl"] for p in pays if p["at"] < split)
    by_m = {m: sum(p["amount_mdl"] for p in pays
                   if p["at"] >= split and p["method"] == m)
            for m in db.PAY_METHODS}
    inc_azi = sum(p["amount_mdl"] for p in await db.payments_range(
        t_split, t_split + timedelta(days=1)))

    est_note = [{"icon": "", "t": "după lista de prețuri · nu e contabilitate"}]
    if tg_ui:
        est_note.append({"icon": "", "t": f"botul a adus cca {fmt_mdl(cur['bot_value'])}"})
    money = [
        {"key": "incasari", "title": "Încasări",
         "sub": f"· bani reali, {_dm(d1)}–{_dm(d2)}",
         "value": inc_cur, "text": fmt_mdl(inc_cur), "suffix": " MDL",
         "trend": trend_money(inc_cur, inc_prev, plabel),
         "note": [{"icon": "", "t": f"azi: {fmt_mdl(inc_azi)}"},
                  {"icon": "cash", "t": fmt_mdl(by_m["numerar"])},
                  {"icon": "card", "t": fmt_mdl(by_m["card"])},
                  {"icon": "bank", "t": fmt_mdl(by_m["transfer"])},
                  {"icon": "", "t": "plăți înregistrate la recepție"}],
         # лист для сверки ящика в конце смены; ведёт на СЕГОДНЯ, а не на конец
         # выбранного периода: касса сходится за смену, а не за произвольное окно
         "link": {"href": "/admin/casa", "label": "Raport de casă (azi) ›",
                  "icon": "print"}},
        {"key": "estimat", "title": "Venituri estimate",
         "sub": f"· {_dm(d1)}–{_dm(d2)}",
         "value": cur["value"], "text": fmt_mdl(cur["value"]), "suffix": " MDL",
         "trend": trend_money(cur["value"], prev["value"], plabel),
         "note": est_note, "link": None},
        {"key": "azi", "title": "Venituri azi", "sub": f"· {_dm(today)}",
         "value": tv, "text": fmt_mdl(tv), "suffix": " MDL",
         "trend": trend_money(tv, yv, "față de ieri"),
         "note": [{"icon": "", "t": "estimare pe ziua curentă · după lista de prețuri"}],
         "link": None},
    ]

    # ---- услуги: группировка по service_id, RU и RO — одна строка ----
    svc: dict[str, dict] = {}
    for r in cur["act"]:
        sid = r.get("service_id")
        if sid and sid in eng.SERVICES:
            key, label = sid, eng.SERVICES[sid]["ro"]
        else:
            key, label = "lbl:" + r["service"], r["service"]
        ent = svc.setdefault(key, {"label": label, "cnt": 0, "val": 0})
        ent["cnt"] += 1
        ent["val"] += price(r)
    top = sorted(svc.values(), key=lambda x: -x["cnt"])[:8]
    max_cnt = top[0]["cnt"] if top else 1
    services = [{"label": s["label"], "cnt": s["cnt"],
                 "val": f"cca {fmt_mdl(s['val'])}",
                 "pct": round(100 * s["cnt"] / max_cnt)} for s in top]

    # ---- последние события картотеки (летопись уже пишет ИМЯ вошедшего) ----
    activity = []
    for a in await db.recent_activity(10):
        at = a["at"].astimezone(eng.TZ) if a["at"] else None
        activity.append({
            "text": a["text"], "name": a["name"] or "—",
            "patient_id": a["patient_id"],
            "who": "bot" if a["actor"] == "bot" else (a["actor"] or "recepție"),
            "at": at.strftime("%d.%m %H:%M") if at else "",
        })

    # ---- периоды ----
    presets = [("azi", "Azi", today, today),
               ("d7", "7 zile", today - timedelta(days=6), today),
               ("luna", "Luna asta", today.replace(day=1), today),
               ("d30", "30 zile", today - timedelta(days=29), today)]
    return {
        "period": {"from": d1.isoformat(), "to": d2.isoformat(),
                   "label": f"{d1.strftime('%d.%m.%Y')} — {d2.strftime('%d.%m.%Y')}",
                   "short": f"{_dm(d1)}–{_dm(d2)}", "days": span},
        "presets": [{"key": k, "label": lbl, "from": a.isoformat(), "to": b.isoformat()}
                    for k, lbl, a, b in presets],
        "compare": plabel,
        "export_url": f"/admin/export.xlsx?from={d1.isoformat()}&to={d2.isoformat()}",
        "tiles": tiles,
        "chart": chart,
        "sources": sources,
        "occupancy": occupancy,
        "money": money,
        "doctors": doctors,
        "services": services,
        "activity": activity,
        "hint": ("Prețurile sunt medii orientative din lista clinicii; "
                 "neprezentările = venit pierdut estimat. Notițele nu se "
                 "numără. Secțiunea este vizibilă doar directorului."),
    }
