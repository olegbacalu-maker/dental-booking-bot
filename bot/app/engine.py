"""Диалоговый движок демо-бота записи. Не зависит от канала:
веб-чат сегодня, Telegram — следующей итерацией (тот же handle())."""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db

TZ = ZoneInfo("Europe/Chisinau")

APP_VERSION = "1.7.0"


def _load_config() -> dict:
    """Вся клиника (врачи/услуги/часы/контакты) — из clinic.json.
    Порядок: $CLINIC_CONFIG (маунт в compose) → копия в образе."""
    candidates = []
    env_path = os.environ.get("CLINIC_CONFIG")
    if env_path:
        candidates.append(env_path)
    candidates.append(str(pathlib.Path(__file__).resolve().parent / "clinic.json"))
    for p in candidates:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
    raise RuntimeError("clinic config not found/invalid: " + ", ".join(candidates))


# все производные конфига заполняет apply_config() — hot-reload без рестарта
CONFIG: dict = {}
CLINIC_NAME = ""
CLINIC_PHONE = ""
# DOCTORS = ВСЕ врачи (в т.ч. выключенные) — чтобы история и журнал показывали
# имя; ACTIVE_DOCTORS = те, кого предлагает бот и формы записи.
DOCTORS: dict[str, str] = {}
ACTIVE_DOCTORS: dict[str, str] = {}
DOCTOR_SPEC: dict[str, str] = {}
DOCTOR_META: dict[str, dict] = {}   # color / phone / room / active
# docs = кто выполняет услугу (нет ключа = все); один врач → бот не спрашивает
SERVICES: dict[str, dict] = {}
SERVICE_PRICE: dict[str, int] = {}
SERVICE_COLOR: dict[str, str] = {}  # id услуги → цвет из конфига
URGENT_LABELS: set[str] = set()


def allowed_doc_items(svc_key: str) -> list[tuple[str, str]]:
    keys = SERVICES.get(svc_key, {}).get("docs") or list(ACTIVE_DOCTORS)
    return [(k, ACTIVE_DOCTORS[k]) for k in keys if k in ACTIVE_DOCTORS]


def _price_avg(price) -> int:
    """Средняя цена услуги в MDL из строки прайса ('1200–1800 MDL' → 1500)."""
    if isinstance(price, dict):
        price = price.get("ro", "")
    nums = [int(n) for n in re.findall(r"\d+", str(price))]
    return int(sum(nums) / len(nums)) if nums else 0



RO_DOW = ["Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du"]
RU_DOW = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

T_BASE = {
    "ro": {
        "menu": "Cu ce vă pot ajuta?",
        "btn_book": "📅 Programare",
        "btn_my": "🗓 Programările mele",
        "btn_prices": "💰 Prețuri",
        "btn_contacts": "☎️ Contacte",
        "choose_service": "Alegeți serviciul:",
        "choose_doctor": "La care medic doriți?",
        "any_doctor": "Oricare disponibil",
        "choose_day": "Alegeți ziua:",
        "choose_time": "Ore libere pe {day}:",
        "day_full": "În această zi nu mai sunt locuri. Alegeți altă zi:",
        "ask_name": "Cum vă numiți? (nume și prenume)",
        "ask_year": "Anul nașterii? (ex.: 1985)",
        "bad_year": "Introduceți un an valid, ex. 1985 — sau apăsați «Omite»:",
        "btn_skip": "⏭ Omite",
        "ask_phone": "Numărul dvs. de telefon? (ex.: 060 123 456)",
        "bad_phone": "Numărul nu pare corect. Introduceți un număr valid (min. 8 cifre):",
        "confirm": "Verificați programarea:\n\n🦷 {service}\n👨‍⚕️ {doctor}\n📅 {when}\n👤 {name}, {phone}\n\nConfirmați?",
        "btn_confirm": "✅ Confirm",
        "btn_change": "🔄 Alt timp",
        "booked": "Gata! V-am programat: {when}, {doctor}. Cu o zi înainte veți primi un reminder. 📩",
        "btn_demo_reminder": "⏩ Demo: arată reminderul",
        "reminder": "🔔 Reminder: {when} aveți programare la {doctor} ({service}), clinica {CLINIC}, {ADDRESS}. Confirmați prezența?",
        "reminder_soon": "🔔 În curând: astăzi la {time} aveți programare la {doctor} ({service}). Vă așteptăm — {CLINIC}, {ADDRESS}!",
        "btn_rem_ok": "✅ Voi veni",
        "btn_cancel_appt": "❌ Anulează",
        "rem_ok": "Mulțumim! Vă așteptăm. 😊",
        "slot_taken": "Ups, acest interval tocmai a fost ocupat. Alegeți altul:",
        "no_appts": "Nu aveți programări viitoare.",
        "my_header": "Programările dvs.:",
        "cancelled": "Programarea a fost anulată.",
        "cancel_gone": "Această programare nu mai este activă.",
        "own_slot": "Aveți deja o programare la această oră. Alegeți alt interval:",
        "prices": "Prețuri orientative:\n• Consultație — gratuit\n• Igienizare profesională — 1000–1200 MDL\n• Plombă compozit — 1200–1800 MDL\n• Extracție dinte — 1000–1500 MDL\n• Coroană — 2500–4500 MDL\n• Albire dentară — de la 2500 MDL\n• Consult implantologie — gratuit\n• Durere acută — vă primim în aceeași zi",
        "urgent_intro": "Ne pare rău că vă doare! Iată cele mai apropiate ore libere:",
        "urgent_call": "⚠️ Dacă durerea e insuportabilă — sunați-ne chiar acum: {PHONE}",
        "btn_otherday": "📅 Altă zi",
        "one_doctor": "Acest serviciu îl face {doctor}.",
        "contacts": "📍 str. Ștefan cel Mare 1, Cahul\n☎️ +373 60 000 000\n🕘 Lu–Vi 9:00–18:00, Sâ 9:00–14:00",
        "btn_menu": "◀️ Meniu",
        "fallback": "Nu am înțeles 🙂 Folosiți butoanele de mai jos.",
    },
    "ru": {
        "menu": "Чем могу помочь?",
        "btn_book": "📅 Записаться",
        "btn_my": "🗓 Мои записи",
        "btn_prices": "💰 Цены",
        "btn_contacts": "☎️ Контакты",
        "choose_service": "Выберите услугу:",
        "choose_doctor": "К какому врачу?",
        "any_doctor": "Любой свободный",
        "choose_day": "Выберите день:",
        "choose_time": "Свободное время на {day}:",
        "day_full": "На этот день мест нет. Выберите другой день:",
        "ask_name": "Как вас зовут? (имя и фамилия)",
        "ask_year": "Год рождения? (напр.: 1985)",
        "bad_year": "Введите корректный год, напр. 1985 — или нажмите «Пропустить»:",
        "btn_skip": "⏭ Пропустить",
        "ask_phone": "Ваш номер телефона? (напр.: 060 123 456)",
        "bad_phone": "Номер выглядит некорректно. Введите номер (мин. 8 цифр):",
        "confirm": "Проверьте запись:\n\n🦷 {service}\n👨‍⚕️ {doctor}\n📅 {when}\n👤 {name}, {phone}\n\nПодтверждаете?",
        "btn_confirm": "✅ Подтверждаю",
        "btn_change": "🔄 Другое время",
        "booked": "Готово! Вы записаны: {when}, {doctor}. За день до визита придёт напоминание. 📩",
        "btn_demo_reminder": "⏩ Демо: показать напоминание",
        "reminder": "🔔 Напоминание: {when} вы записаны к {doctor} ({service}), клиника {CLINIC}, {ADDRESS}. Подтверждаете визит?",
        "reminder_soon": "🔔 Скоро приём: сегодня в {time} вы записаны к {doctor} ({service}). Ждём вас — {CLINIC}, {ADDRESS}!",
        "btn_rem_ok": "✅ Приду",
        "btn_cancel_appt": "❌ Отменить",
        "rem_ok": "Спасибо! Ждём вас. 😊",
        "slot_taken": "Упс, это время только что заняли. Выберите другое:",
        "no_appts": "У вас нет предстоящих записей.",
        "my_header": "Ваши записи:",
        "cancelled": "Запись отменена.",
        "cancel_gone": "Эта запись уже неактивна.",
        "own_slot": "У вас уже есть запись на это время. Выберите другое:",
        "prices": "Ориентировочные цены:\n• Консультация — бесплатно\n• Проф. гигиена — 1000–1200 MDL\n• Пломба (композит) — 1200–1800 MDL\n• Удаление зуба — 1000–1500 MDL\n• Коронка — 2500–4500 MDL\n• Отбеливание — от 2500 MDL\n• Консультация по имплантации — бесплатно\n• Острая боль — примем в тот же день",
        "urgent_intro": "Сочувствуем — зубная боль не ждёт! Ближайшие свободные окна:",
        "urgent_call": "⚠️ Если боль очень сильная — позвоните нам прямо сейчас: {PHONE}",
        "btn_otherday": "📅 Другой день",
        "one_doctor": "Эту услугу выполняет {doctor}.",
        "contacts": "📍 ул. Штефан чел Маре 1, Кахул\n☎️ +373 60 000 000\n🕘 Пн–Пт 9:00–18:00, Сб 9:00–14:00",
        "btn_menu": "◀️ Меню",
        "fallback": "Не понял 🙂 Пользуйтесь кнопками ниже.",
    },
}

T: dict = {}
HELLO = ""
CHOOSE_LANG = "Alegeți limba / Выберите язык:"


def _prices_text(lang: str) -> str:
    head = "Prețuri orientative:" if lang == "ro" else "Ориентировочные цены:"
    lines = [head]
    for svc in CONFIG["services"]:
        price = svc.get("price", "")
        if isinstance(price, dict):
            price = price.get(lang, "")
        lines.append(f"• {svc[lang]} — {price}" if price else f"• {svc[lang]}")
    return "\n".join(lines)


def apply_config(cfg: dict) -> None:
    """Применяет конфиг клиники на лету: справочники, цены, тексты, приветствие."""
    global CONFIG, CLINIC_NAME, CLINIC_PHONE, HELLO
    CONFIG = cfg
    CLINIC_NAME = cfg["name"]
    CLINIC_PHONE = cfg["phone"]
    DOCTORS.clear()
    ACTIVE_DOCTORS.clear()
    DOCTOR_SPEC.clear()
    DOCTOR_META.clear()
    for d in cfg["doctors"]:
        DOCTORS[d["id"]] = d["name"]
        DOCTOR_SPEC[d["id"]] = d.get("spec", "")
        DOCTOR_META[d["id"]] = {"color": d.get("color", ""), "phone": d.get("phone", ""),
                                "room": d.get("room", ""),
                                "active": d.get("active", True)}
        if d.get("active", True):
            ACTIVE_DOCTORS[d["id"]] = d["name"]
    SERVICES.clear()
    SERVICE_PRICE.clear()
    SERVICE_COLOR.clear()
    URGENT_LABELS.clear()
    for svc in cfg["services"]:
        entry = {"ro": svc["ro"], "ru": svc["ru"]}
        if svc.get("urgent"):
            entry["urgent"] = True
            URGENT_LABELS.add(svc["ro"])
            URGENT_LABELS.add(svc["ru"])
        if svc.get("docs"):
            entry["docs"] = svc["docs"]
        if svc.get("color"):
            entry["color"] = svc["color"]
            SERVICE_COLOR[svc["id"]] = svc["color"]
        SERVICES[svc["id"]] = entry
        avg = _price_avg(svc.get("price", ""))
        SERVICE_PRICE[svc["ro"]] = avg
        SERVICE_PRICE[svc["ru"]] = avg
    T.clear()
    for lang, msgs in T_BASE.items():
        addr = cfg.get("address", {}).get(lang, "")
        T[lang] = {
            k: (v.replace("{CLINIC}", CLINIC_NAME)
                 .replace("{PHONE}", CLINIC_PHONE)
                 .replace("{ADDRESS}", addr))
            for k, v in msgs.items()
        }
        T[lang]["prices"] = _prices_text(lang)
        contacts = cfg.get("contacts", {}).get(lang)
        if contacts:
            T[lang]["contacts"] = contacts
    HELLO = f"🦷 {CLINIC_NAME} — asistent de programări / ассистент записи."


def save_config(cfg: dict) -> str | None:
    """Пишет конфиг в файл и применяет на лету. Возвращает текст ошибки или None."""
    path = os.environ.get("CLINIC_CONFIG") or str(
        pathlib.Path(__file__).resolve().parent / "clinic.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return f"nu pot scrie {path}: {e}"
    apply_config(cfg)
    return None


apply_config(_load_config())


@dataclass
class Session:
    lang: str = "ro"
    state: str = "lang"
    data: dict = field(default_factory=dict)


SESSIONS: dict[str, Session] = {}


def get_session(sid: str) -> Session:
    return SESSIONS.setdefault(sid, Session())


def t(s: Session, key: str) -> str:
    return T[s.lang][key]


def btn(label: str, value: str) -> dict:
    return {"label": label, "value": value}


def chunk(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def menu_buttons(s: Session) -> list[list[dict]]:
    return [
        [btn(t(s, "btn_book"), "book")],
        [btn(t(s, "btn_my"), "my")],
        [btn(t(s, "btn_prices"), "prices"), btn(t(s, "btn_contacts"), "contacts")],
    ]


def day_label(s: Session, d: date) -> str:
    dow = (RO_DOW if s.lang == "ro" else RU_DOW)[d.weekday()]
    return f"{dow} {d.strftime('%d.%m')}"


_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def hours_for(d: date) -> tuple | None:
    """Рабочие часы дня из конфига; None = выходной.
    Формат: [от, до] или [от, до, пауза_от, пауза_до] (обед)."""
    h = CONFIG.get("hours", {}).get(_DOW[d.weekday()])
    return tuple(int(x) for x in h) if h else None


def next_days() -> list[date]:
    out: list[date] = []
    d = datetime.now(TZ).date() + timedelta(days=1)
    scanned = 0
    while len(out) < 7 and scanned < 14:
        if hours_for(d):
            out.append(d)
        d += timedelta(days=1)
        scanned += 1
    return out


def day_slots(d: date) -> list[datetime]:
    h = hours_for(d)
    if not h:
        return []
    hours = list(range(h[0], h[1]))
    if len(h) >= 4:  # обеденный перерыв выпадает из сетки
        hours = [x for x in hours if not (h[2] <= x < h[3])]
    return [datetime(d.year, d.month, d.day, hour, 0, tzinfo=TZ) for hour in hours]


def day_rows(s: Session) -> list[list[dict]]:
    rows = chunk([btn(day_label(s, d), "day:" + d.isoformat()) for d in next_days()], 3)
    rows.append([btn(t(s, "btn_menu"), "menu")])
    return rows


def service_rows(s: Session) -> list[list[dict]]:
    rows = []
    for k, v in SERVICES.items():
        label = ("🆘 " + v[s.lang]) if v.get("urgent") else v[s.lang]
        rows.append([btn(label, f"svc:{k}")])
    return rows


def doctor_rows(s: Session) -> list[list[dict]]:
    items = allowed_doc_items(s.data.get("svc", ""))
    rows = [[btn(name, f"doc:{k}")] for k, name in items]
    if len(items) > 1:
        rows.append([btn(t(s, "any_doctor"), "doc:any")])
    return rows


def svc_allowed_names(s: Session) -> list[str]:
    return [name for _, name in allowed_doc_items(s.data.get("svc", ""))]


async def time_rows(s: Session, d: date) -> list[list[dict]] | None:
    slots = await free_slots(s.data["doc"], d, svc_allowed_names(s))
    if not slots:
        return None
    rows = chunk(
        [btn(x.strftime("%H:%M"), "time:" + x.strftime("%Y-%m-%dT%H:%M")) for x in slots], 4
    )
    rows.append([btn(t(s, "btn_menu"), "menu")])
    return rows


async def free_slots(
    doc_key: str, d: date, allowed_names: list[str] | None = None
) -> list[datetime]:
    start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=TZ)
    end = start + timedelta(days=1)
    now = datetime.now(TZ)
    slots = day_slots(d)
    if doc_key == "any":
        names = allowed_names or list(ACTIVE_DOCTORS.values())
        free: set[datetime] = set()
        for name in names:
            b = await db.booked(name, start, end)
            free.update(x for x in slots if x not in b)
        return sorted(x for x in free if x > now)
    b = await db.booked(DOCTORS[doc_key], start, end)
    return [x for x in slots if x not in b and x > now]


async def urgent_slots(
    limit: int = 8, allowed_names: list[str] | None = None
) -> list[datetime]:
    """Ближайшие свободные окна у допущенных врачей, начиная с СЕГОДНЯ."""
    out: list[datetime] = []
    d = datetime.now(TZ).date()
    for _ in range(4):
        if hours_for(d):
            out += await free_slots("any", d, allowed_names)
        if len(out) >= limit:
            break
        d += timedelta(days=1)
    return out[:limit]


def build_seed_rows() -> list[tuple]:
    """Демо-наполнение журнала на первый рабочий день (только при пустой БД)."""
    if not CONFIG.get("seed_demo"):
        return []
    d = datetime.now(TZ).date() + timedelta(days=1)
    for _ in range(7):
        if hours_for(d):
            break
        d += timedelta(days=1)
    usable = day_slots(d)[1:]  # с 2-го слота дня, перерыв уже исключён
    demo_people = [
        ("Maria Exemplu", "060 111 222", 1978), ("Ion Popescu", "069 222 333", 1991),
        ("Ana Balan", "061 333 444", 2001), ("Vasile Rotaru", "068 444 555", 1969),
        ("Elena Cara", "062 555 666", 1985), ("Mihai Donos", "067 666 777", 1996),
    ]
    rows = []
    for i, (key, svc) in enumerate(SERVICES.items()):
        if i >= len(demo_people) or i >= len(usable):
            break
        doctor = allowed_doc_items(key)[0][1]
        name, phone, year = demo_people[i]
        rows.append((name, phone, svc["ro"], doctor, usable[i], year))
    return rows


def is_urgent(s: Session) -> bool:
    return bool(SERVICES.get(s.data.get("svc", ""), {}).get("urgent"))


async def render_urgent(s: Session, prefix: str | None = None):
    """Экран «ближайшие окна» для острой боли — вход и ВСЕ возвраты в него.
    Телефон клиники показывается всегда, даже если окон нет."""
    slots = await urgent_slots(allowed_names=svc_allowed_names(s))
    if slots:
        texts = ([prefix] if prefix else [t(s, "urgent_intro")]) + [t(s, "urgent_call")]
        s.data["day"] = slots[0].date().isoformat()
        s.state = "time"
        rows = chunk(
            [btn(f"{day_label(s, x.date())} {x.strftime('%H:%M')}",
                 "time:" + x.strftime("%Y-%m-%dT%H:%M")) for x in slots], 2
        )
        rows.append([btn(t(s, "btn_otherday"), "otherday")])
        rows.append([btn(t(s, "btn_menu"), "menu")])
        return texts, rows
    texts = ([prefix] if prefix else []) + [t(s, "urgent_call"), t(s, "choose_day")]
    s.state = "day"
    return texts, day_rows(s)


def confirm_text(s: Session) -> str:
    dt = datetime.fromisoformat(s.data["time"])
    when = f"{day_label(s, dt.date())} {dt.strftime('%H:%M')}"
    doc = t(s, "any_doctor") if s.data.get("doc") == "any" else DOCTORS[s.data["doc"]]
    who = s.data["name"]
    if s.data.get("year"):
        who += f" ({s.data['year']})"
    return t(s, "confirm").format(
        service=SERVICES[s.data["svc"]][s.lang], doctor=doc, when=when,
        name=who, phone=s.data["phone"],
    )


async def fallback(s: Session):
    """Непонятый ввод НЕ выбрасывает из флоу — перерисовывает текущий шаг."""
    if s.state == "lang":
        return [HELLO, CHOOSE_LANG], [[btn("Română", "lang:ro"), btn("Русский", "lang:ru")]]
    if s.state == "svc":
        return [t(s, "fallback"), t(s, "choose_service")], service_rows(s)
    if s.state == "doc" and "svc" in s.data:
        return [t(s, "fallback"), t(s, "choose_doctor")], doctor_rows(s)
    if s.state == "day" and "doc" in s.data:
        return [t(s, "fallback"), t(s, "choose_day")], day_rows(s)
    if s.state == "time" and s.data.get("day") and s.data.get("doc"):
        if is_urgent(s):
            return await render_urgent(s, t(s, "fallback"))
        d = date.fromisoformat(s.data["day"])
        rows = await time_rows(s, d)
        if rows is not None:
            return [t(s, "fallback"), t(s, "choose_time").format(day=day_label(s, d))], rows
        s.state = "day"
        return [t(s, "day_full")], day_rows(s)
    if s.state == "name":
        return [t(s, "ask_name")], []
    if s.state == "year":
        return [t(s, "bad_year")], [[btn(t(s, "btn_skip"), "skip_year")]]
    if s.state == "phone":
        return [t(s, "bad_phone")], []
    if s.state == "confirm" and all(k in s.data for k in ("svc", "doc", "time", "name", "phone")):
        return [t(s, "fallback"), confirm_text(s)], [
            [btn(t(s, "btn_confirm"), "confirm"), btn(t(s, "btn_change"), "change")]
        ]
    return [t(s, "fallback")], menu_buttons(s)


async def do_book(s: Session, sid: str):
    dt = datetime.fromisoformat(s.data["time"])
    # слот мог пройти, пока вводили имя/телефон (актуально для окон «сегодня»)
    if dt <= datetime.now(TZ):
        if is_urgent(s):
            return await render_urgent(s, t(s, "slot_taken"))
        s.state = "day"
        return [t(s, "slot_taken")], day_rows(s)
    doc_key = s.data.get("doc", "any")
    if doc_key == "any":
        candidates = []
        for name in svc_allowed_names(s):
            b = await db.booked(name, dt, dt + timedelta(hours=1))
            if dt not in b:
                candidates.append(name)
    else:
        candidates = [DOCTORS[doc_key]]
    service = SERVICES[s.data["svc"]][s.lang]
    appt_id = None
    doctor = None
    # при гонке за слот пробуем всех свободных врачей, прежде чем сдаться
    for cand in candidates:
        r = await db.create_appointment(
            sid, s.data["name"], s.data["phone"], s.lang, service, cand, dt,
            birth_year=s.data.get("year"),
        )
        if r == "dup":
            if is_urgent(s):
                return await render_urgent(s, t(s, "own_slot"))
            s.state = "day"
            return [t(s, "own_slot")], day_rows(s)
        if r is not None:
            appt_id, doctor = r, cand
            break
    if appt_id is None:
        if is_urgent(s):
            return await render_urgent(s, t(s, "slot_taken"))
        s.state = "day"
        return [t(s, "slot_taken")], day_rows(s)
    s.data["last_appt"] = appt_id
    s.state = "menu"
    when = f"{day_label(s, dt.date())} {dt.strftime('%H:%M')}"
    return [t(s, "booked").format(when=when, doctor=doctor)], [
        [btn(t(s, "btn_demo_reminder"), "demo_reminder")],
        [btn(t(s, "btn_menu"), "menu")],
    ]


async def handle(s: Session, sid: str, msg: str):
    msg = (msg or "").strip()

    if msg in ("/start", "start"):
        s.state = "lang"
        s.data = {}
        return [HELLO, CHOOSE_LANG], [[btn("Română", "lang:ro"), btn("Русский", "lang:ru")]]

    if msg.startswith("lang:"):
        s.lang = "ru" if msg == "lang:ru" else "ro"
        s.state = "menu"
        return [t(s, "menu")], menu_buttons(s)

    if msg == "menu":
        s.state = "menu"
        return [t(s, "menu")], menu_buttons(s)

    if msg == "book":
        s.state = "svc"
        s.data = {}
        return [t(s, "choose_service")], service_rows(s)

    if msg.startswith("svc:"):
        key = msg[4:]
        if key not in SERVICES:
            return await fallback(s)
        s.data["svc"] = key
        if SERVICES[key].get("urgent"):
            # острая боль: без выбора врача, сразу ближайшие окна (включая сегодня)
            s.data["doc"] = "any"
            return await render_urgent(s)
        allowed = allowed_doc_items(key)
        if len(allowed) == 1:
            # услугу делает один врач — не задаём лишний вопрос
            s.data["doc"] = allowed[0][0]
            s.state = "day"
            return [t(s, "one_doctor").format(doctor=allowed[0][1]),
                    t(s, "choose_day")], day_rows(s)
        s.state = "doc"
        return [t(s, "choose_doctor")], doctor_rows(s)

    if msg.startswith("doc:"):
        key = msg[4:]
        if "svc" not in s.data:
            return await fallback(s)
        allowed_keys = {k for k, _ in allowed_doc_items(s.data["svc"])}
        if key != "any" and key not in allowed_keys:
            return await fallback(s)
        s.data["doc"] = key
        s.state = "day"
        return [t(s, "choose_day")], day_rows(s)

    if msg.startswith("day:"):
        if "svc" not in s.data or "doc" not in s.data:
            return await fallback(s)
        try:
            d = date.fromisoformat(msg[4:])
        except ValueError:
            return await fallback(s)
        rows = await time_rows(s, d)
        if rows is None:
            return [t(s, "day_full")], day_rows(s)
        s.data["day"] = d.isoformat()
        s.state = "time"
        return [t(s, "choose_time").format(day=day_label(s, d))], rows

    if msg.startswith("time:"):
        if "svc" not in s.data or "doc" not in s.data:
            return await fallback(s)
        try:
            dt = datetime.fromisoformat(msg[5:])
        except ValueError:
            return await fallback(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        # только валидные слоты сетки и только будущее
        if dt not in day_slots(dt.date()) or dt <= datetime.now(TZ):
            return await fallback(s)
        s.data["time"] = dt.isoformat()
        if s.data.get("name") and s.data.get("phone"):
            s.state = "confirm"
            return [confirm_text(s)], [
                [btn(t(s, "btn_confirm"), "confirm"), btn(t(s, "btn_change"), "change")]
            ]
        s.state = "name"
        return [t(s, "ask_name")], []

    if msg in ("change", "otherday"):
        if "svc" not in s.data or "doc" not in s.data:
            return await fallback(s)
        # «другое время» при острой боли = снова ближайшие окна (сегодня не теряем);
        # «другой день» — осознанный уход в обычный календарь
        if msg == "change" and is_urgent(s):
            return await render_urgent(s)
        s.state = "day"
        return [t(s, "choose_day")], day_rows(s)

    if msg == "confirm" and s.state == "confirm":
        return await do_book(s, sid)

    # «да» текстом на шаге подтверждения = подтверждение
    if s.state == "confirm" and msg.lower().strip(" !.") in {
        "da", "да", "yes", "ok", "ок", "confirm", "подтверждаю", "confirm"
    }:
        return await do_book(s, sid)

    if msg == "my":
        rows = await db.my_appointments(sid, datetime.now(TZ))
        if not rows:
            return [t(s, "no_appts")], menu_buttons(s)
        lines = [t(s, "my_header")]
        brows = []
        for r in rows:
            dt = r["starts_at"].astimezone(TZ)
            lines.append(
                f"• #{r['id']} {r['service']} — {day_label(s, dt.date())} "
                f"{dt.strftime('%H:%M')} ({r['doctor']})"
            )
            # «в кабинете» (arrived) из бота не отменяется — кнопку не рисуем,
            # иначе тап давал бы ложное «запись уже неактивна»
            if r.get("status", "confirmed") == "confirmed":
                brows.append([btn(f"{t(s, 'btn_cancel_appt')} #{r['id']}",
                                  f"cancel:{r['id']}")])
        brows.append([btn(t(s, "btn_menu"), "menu")])
        return ["\n".join(lines)], brows

    if msg.startswith("cancel:"):
        try:
            appt_id = int(msg[7:])
        except ValueError:
            return await fallback(s)
        n = await db.cancel_appointment(sid, appt_id)
        s.state = "menu"
        if not n:
            return [t(s, "cancel_gone")], menu_buttons(s)
        return [t(s, "cancelled")], menu_buttons(s)

    if msg == "demo_reminder":
        rows = await db.my_appointments(sid, datetime.now(TZ))
        if not rows:
            return [t(s, "no_appts")], menu_buttons(s)
        last = s.data.get("last_appt")
        row = next((r for r in rows if r["id"] == last), rows[0])
        dt = row["starts_at"].astimezone(TZ)
        text = t(s, "reminder").format(
            when=f"{day_label(s, dt.date())} {dt.strftime('%H:%M')}",
            doctor=row["doctor"], service=row["service"],
        )
        return [text], [
            [btn(t(s, "btn_rem_ok"), "rem_ok")],
            [btn(f"{t(s, 'btn_cancel_appt')} #{row['id']}", f"cancel:{row['id']}")],
        ]

    if msg == "rem_ok":
        s.state = "menu"
        return [t(s, "rem_ok")], menu_buttons(s)

    if msg == "prices":
        return [t(s, "prices")], [[btn(t(s, "btn_menu"), "menu")]]

    if msg == "contacts":
        return [t(s, "contacts")], [[btn(t(s, "btn_menu"), "menu")]]

    if msg == "skip_year" and s.state == "year":
        s.state = "phone"
        return [t(s, "ask_phone")], []

    # свободный текст: имя, год рождения, телефон
    if s.state == "name" and msg:
        s.data["name"] = msg[:80]
        s.state = "year"
        return [t(s, "ask_year")], [[btn(t(s, "btn_skip"), "skip_year")]]

    if s.state == "year" and msg:
        yr = msg.strip()
        if yr.isdigit() and 1900 <= int(yr) <= datetime.now(TZ).year:
            s.data["year"] = int(yr)
            s.state = "phone"
            return [t(s, "ask_phone")], []
        return [t(s, "bad_year")], [[btn(t(s, "btn_skip"), "skip_year")]]

    if s.state == "phone" and msg:
        digits = re.sub(r"\D", "", msg)
        if not (8 <= len(digits) <= 15) or not re.fullmatch(r"[+0-9 ()\-.]{6,25}", msg):
            # след для форензики: без самого номера (PII), только форма ввода
            logging.getLogger("engine").warning(
                "bad_phone rejected: len=%d digits=%d channel=%s",
                len(msg), len(digits),
                sid.split(":", 1)[0] if ":" in sid else "web")
            return [t(s, "bad_phone")], []
        s.data["phone"] = msg
        s.state = "confirm"
        return [confirm_text(s)], [
            [btn(t(s, "btn_confirm"), "confirm"), btn(t(s, "btn_change"), "change")]
        ]

    return await fallback(s)
