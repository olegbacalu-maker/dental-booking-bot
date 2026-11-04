"""Профиль клиники и правила расписания: врачи, услуги, часы работы, рабочие
окна и свободные старты. Диалог записи бота жил здесь до 03.11.2026 (удалён
вместе с ботом; код — тег `archive/telegram-bot`)."""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import shutil
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, paths

TZ = ZoneInfo("Europe/Chisinau")

log = logging.getLogger("engine")

APP_VERSION = "2.9.0"


def _load_config() -> dict:
    """Вся клиника (врачи/услуги/часы/контакты) — из clinic.json.
    Порядок: $CLINIC_CONFIG (маунт в compose) → его .bak → копия в образе.

    Последний кандидат — ДЕМО-клиника, вшитая в exe. Раньше падение на первом
    (битый файл) молча приводило к ней: клиника стартовала с чужими врачами и
    не понимала почему. Между ними стоит .bak прошлого удачного сохранения, а
    каждое падение кандидата громко пишется в лог.

    ⛔ С 08-20 (аудит) до демо-клиники БИТЫЙ профиль больше не доезжает как
    рабочий: если clinic.json СУЩЕСТВУЕТ, но не читается, и .bak его не спас —
    ставится CONFIG_BROKEN, и main.py поднимает экран ошибки вместо журнала.
    Демо-профиль при этом всё равно возвращается, но только как каркас для
    самого экрана ошибки (standalone/theme без конфига не рисуются) — до
    записи, бота и любых страниц журнала дело не доходит.
    ⚠️ Ветка «файлов НЕТ ВОВСЕ» остаётся тихой намеренно: это законный путь
    запуска из исходников без $CLINIC_CONFIG; у клиники clinic.json кладёт
    лаунчер до старта приложения (desktop.py), и отсутствовать он не может."""
    global CONFIG_BROKEN
    candidates = []
    env_path = os.environ.get("CLINIC_CONFIG")
    if env_path:
        candidates.append(env_path)
        candidates.append(env_path + ".bak")
    broken: list[str] = []
    for i, p in enumerate(candidates):
        try:
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            if i:
                log.warning("clinic config: взят запасной кандидат %s "
                            "(предыдущие нечитаемы)", p)
            return cfg
        except FileNotFoundError:
            continue
        # UnicodeDecodeError здесь не экзотика: клиника правит clinic.json
        # Блокнотом, и «Сохранить» в ANSI с диакритикой — один клик. Без него
        # в этом except битый файл ронял бы сам импорт engine: ни .bak, ни
        # экран CONFIG_BROKEN не поднимались бы вовсе (ревью 08-22).
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning("clinic config: %s не читается (%r) — пробую дальше", p, e)
            broken.append(f"{p}: {e}")
    if broken:
        CONFIG_BROKEN = "; ".join(broken)
        log.error("clinic config: профиль клиники не читается, запасного нет — "
                  "журнал поднимется экраном ошибки, не демо-клиникой (%s)",
                  CONFIG_BROKEN)
    demo = str(paths.resource("clinic.json"))
    try:
        with open(demo, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"clinic config not found/invalid: "
                           f"{', '.join([*candidates, demo])} ({e!r})") from e


# все производные конфига заполняет apply_config() — hot-reload без рестарта
CONFIG: dict = {}
CLINIC_NAME = ""
CLINIC_PHONE = ""
# Юридическое лицо для подписываемых бумаг (01.10, просьба Олега): оператор
# данных в acord 195, учреждение в шапке 043/e и prestator в acord informat.
# Пусто — на листах стоит вывесочное имя и жёлтый пропуск под IDNO.
CLINIC_LEGAL = ""      # «Denumirea juridică» (SRL …); пусто = как CLINIC_NAME
CLINIC_IDNO = ""       # 13 цифр или пусто
# Профиль клиники не прочитался, и запасной .bak тоже ('' = конфиг живой).
# Ставит _load_config при старте; main.py по этому флагу НЕ открывает базу и
# поднимает экран ошибки вместо журнала — работать на вшитой демо-клинике
# поверх настоящей картотеки нельзя (чужие врачи, чужой прайс).
CONFIG_BROKEN = ""
# DOCTORS = ВСЕ врачи (в т.ч. выключенные) — чтобы история и журнал показывали
# имя; ACTIVE_DOCTORS = те, кого предлагает бот и формы записи.
DOCTORS: dict[str, str] = {}
ACTIVE_DOCTORS: dict[str, str] = {}
DOCTOR_SPEC: dict[str, str] = {}
DOCTOR_META: dict[str, dict] = {}   # color / phone / room / email / photo / status / active
# v1.9.0: галочка «активен» стала тремя состояниями. active = производное
# (только «activ» предлагается ботом и формами) — все прежние проверки живут
# на нём и не знают о новых состояниях.
#   activ    — работает;
#   concediu — временно не принимает (отпуск/болезнь), вернётся;
#   arhivat  — ушёл насовсем; архивировать можно только без будущих записей.
# Ни одно из состояний не прячет уже существующие записи: колонка врача
# держится в сетке того дня, где у него есть приёмы (урок v1.8.2 — данные
# не должны исчезать молча).
DOCTOR_STATES = ("activ", "concediu", "arhivat")
# docs = кто выполняет услугу (нет ключа = все); один врач → бот не спрашивает
SERVICES: dict[str, dict] = {}
SERVICE_PRICE: dict[str, int] = {}          # подпись (ro/ru) → средняя цена
SERVICE_PRICE_BY_ID: dict[str, int] = {}    # id услуги → средняя цена
SERVICE_COLOR: dict[str, str] = {}          # id услуги → цвет из конфига
URGENT_LABELS: set[str] = set()


def doctor_state(d: dict) -> str:
    """Состояние врача из записи конфига. Старые конфиги знают только
    active=true/false: выключенный превращается в «concediu» — обратимое
    состояние, архивацию админ выбирает осознанно."""
    st = str(d.get("status") or "").strip().lower()
    if st in DOCTOR_STATES:
        return st
    return "activ" if d.get("active", True) else "concediu"


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


def apply_config(cfg: dict) -> None:
    """Применяет конфиг клиники на лету: справочники и цены."""
    global CONFIG, CLINIC_NAME, CLINIC_PHONE, CLINIC_LEGAL, CLINIC_IDNO
    CONFIG = cfg
    CLINIC_NAME = cfg["name"]
    CLINIC_PHONE = cfg["phone"]
    CLINIC_LEGAL = str(cfg.get("legal_name") or "").strip() or CLINIC_NAME
    CLINIC_IDNO = str(cfg.get("idno") or "").strip()
    DOCTORS.clear()
    ACTIVE_DOCTORS.clear()
    DOCTOR_SPEC.clear()
    DOCTOR_META.clear()
    for d in cfg["doctors"]:
        DOCTORS[d["id"]] = d["name"]
        DOCTOR_SPEC[d["id"]] = d.get("spec", "")
        DOCTOR_META[d["id"]] = {"color": d.get("color", ""), "phone": d.get("phone", ""),
                                "room": d.get("room", ""),
                                "email": d.get("email", ""),
                                "photo": d.get("photo", ""),
                                "status": doctor_state(d),
                                "active": doctor_state(d) == "activ",
                                "work_from": d.get("work_from"),
                                "work_to": d.get("work_to")}
        if doctor_state(d) == "activ":
            ACTIVE_DOCTORS[d["id"]] = d["name"]
    SERVICES.clear()
    SERVICE_PRICE.clear()
    SERVICE_PRICE_BY_ID.clear()
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
        if svc.get("duration"):
            entry["duration"] = svc["duration"]
        # «Rechemări» (29.10): срок отзыва {months, since} — читает core/recall
        if isinstance(svc.get("recall"), dict) and svc["recall"].get("months"):
            entry["recall"] = dict(svc["recall"])
        SERVICES[svc["id"]] = entry
        avg = _price_avg(svc.get("price", ""))
        SERVICE_PRICE[svc["ro"]] = avg
        SERVICE_PRICE[svc["ru"]] = avg
        SERVICE_PRICE_BY_ID[svc["id"]] = avg


def config_path() -> pathlib.Path:
    """Где лежит профиль клиники — и, значит, вся её «личная» папка.

    ⚠️ ПИШЕМ в папку клиники, а не в resource(): у собранной программы вшитые
    файлы лежат во временной распаковке, и сохранённые настройки исчезли бы
    вместе с ней при закрытии.

    ⛔ И не «рядом с exe»: с переезда в `Program Files` та папка только для
    чтения. Запасная ветка идёт в `paths.data_root()`, а если и его нет —
    ПАДАЕТ с именем недостающей переменной. Это не строгость ради строгости:
    прежний запасной путь вёл в папку программы, и у клиники это был бы отказ
    доступа без единого слова на экране, а у разработчика — молча работающая
    запись в дерево исходников.
    ⚠️ Все четыре живых контекста задают `$CLINIC_CONFIG` сами (лаунчер,
    песочница `dev up`, харнесс прогона, compose облака), так что до ветки
    дело не доходит ни в одном из них.

    ⭐ Функция ОДНА на всех намеренно: рядом с этим файлом лежит логотип
    клиники (core/theme.py), и разойдись два вычисления пути — логотип уехал бы
    в папку, которую программа при следующем запуске не смотрит.
    """
    if env_path := os.environ.get("CLINIC_CONFIG"):
        return pathlib.Path(env_path)
    if (root := paths.data_root()) is not None:
        return root / "clinic.json"
    raise RuntimeError(
        "Не задано, где лежит профиль клиники: нет ни $CLINIC_CONFIG, "
        "ни $DENTART_DATA_DIR. Их выставляет лаунчер (bot/desktop.py); "
        "прогон и песочница задают $CLINIC_CONFIG сами.")


def save_config(cfg: dict) -> str | None:
    """Пишет конфиг в файл и применяет на лету. Возвращает текст ошибки или None.

    ⚠️ Запись АТОМАРНАЯ (tmp + os.replace) и с резервной копией. Прямая запись
    в clinic.json открывала его на "w" (обрезание) ДО сериализации: диск полон,
    антивирус, выдернутая вилка — и на диске оставался обрубок. Такой файл не
    парсится, а _load_config() молча берёт следующего кандидата — копию ДЕМО-
    клиники в самом exe, и клиника стартует с чужими врачами."""
    p = config_path()
    path = str(p)
    tmp = p.with_name(p.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())     # без этого замена может опередить данные
        # ⚠️ бэкап — ТОЛЬКО попытка: копия унаследовала read-only от главного
        # файла и потом навсегда блокировала сохранение (поймано тестом v1.9.1).
        # Страховка не имеет права мешать основной операции.
        if p.exists():
            try:
                shutil.copy2(p, p.with_name(p.name + ".bak"))
            except OSError as e:
                log.warning("clinic config: копия .bak не сделана (%r)", e)
        os.replace(tmp, p)           # атомарно: старый файл живёт до последнего
    except OSError as e:
        pathlib.Path(tmp).unlink(missing_ok=True)
        return f"nu pot scrie {path}: {e}"
    apply_config(cfg)
    return None


apply_config(_load_config())


def day_label(d: date) -> str:
    dow = RO_DOW[d.weekday()]
    return f"{dow} {d.strftime('%d.%m')}"


_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def hours_for(d: date) -> tuple | None:
    """Рабочие часы дня из конфига; None = выходной.
    Формат: [от, до] или [от, до, пауза_от, пауза_до] (обед)."""
    h = CONFIG.get("hours", {}).get(_DOW[d.weekday()])
    return tuple(int(x) for x in h) if h else None


def day_slots(d: date) -> list[datetime]:
    h = hours_for(d)
    if not h:
        return []
    hours = list(range(h[0], h[1]))
    if len(h) >= 4:  # обеденный перерыв выпадает из сетки
        hours = [x for x in hours if not (h[2] <= x < h[3])]
    return [datetime(d.year, d.month, d.day, hour, 0, tzinfo=TZ) for hour in hours]


# ---------- длительности и интервалы (v1.8.0) ----------

GRID_STEP = 30  # шаг сетки стартов, минут


def svc_duration(svc_key: str) -> int:
    """Длительность услуги в минутах (из конфига, дефолт 60)."""
    try:
        return max(15, min(240, int(SERVICES.get(svc_key, {}).get("duration", 60))))
    except (TypeError, ValueError):
        return 60


def doctor_bounds(dk: str, d: date) -> tuple[int, int, int, int] | None:
    """Рабочее окно врача в часах: часы клиники, суженные его work_from/work_to.
    None = день закрыт (для клиники или для врача окно пустое)."""
    h = hours_for(d)
    if not h:
        return None
    f, to = int(h[0]), int(h[1])
    bf, bt = (int(h[2]), int(h[3])) if len(h) >= 4 else (to, to)
    meta = DOCTOR_META.get(dk, {})
    wf, wt = meta.get("work_from"), meta.get("work_to")
    if wf is not None:
        f = max(f, int(wf))
    if wt is not None:
        to = min(to, int(wt))
    if f >= to:
        return None
    return f, to, bf, bt


def doctor_hours(dk: str, d: date) -> set[int]:
    """Часы, в которые врач ПРИНИМАЕТ в этот день: окно клиники, суженное его
    work_from/work_to, минус обед. Выключенный врач не принимает вовсе.

    ⭐ Один ответ на вопрос «свободен ли этот час у этого врача» — канва обоих
    экранов дня спрашивает ЗДЕСЬ. Пока формула стояла двумя копиями (08-12),
    страницы разошлись: канва штриховала часы вне окна врача и не давала по
    ним кликнуть, а таблица старой «Programări» предлагала в них «+» — одна
    страница запрещала то, что другая разрешала, про одного и того же врача.
    ⚠️ Выключенный (`active: false`) сюда добавлен не для красоты: запись
    отвечает ему `bad_off`, поэтому «+» у него — тупик без объяснения.
    Проверку держит `doctor_bounds` отдельно: там она означала бы, что
    выключенный врач исчез и из ЁМКОСТИ (`work_minutes`), а его прошлые визиты
    ещё стоят в статистике.
    """
    if not DOCTOR_META.get(dk, {}).get("active", True):
        return set()
    b = doctor_bounds(dk, d)
    if not b:
        return set()
    f, to, bf, bt = b
    return {h for h in range(f, to) if not (bf <= h < bt)}


def _windows(dk: str, d: date) -> list[tuple[datetime, datetime]]:
    """Непрерывные рабочие интервалы врача за день (обед разрезает)."""
    b = doctor_bounds(dk, d)
    if not b:
        return []
    f, to, bf, bt = b

    def _dt(hour: int) -> datetime:
        return datetime(d.year, d.month, d.day, hour, 0, tzinfo=TZ)

    if bf < bt and f < bt and bf < to:  # обед пересекает окно врача
        out = []
        if f < bf:
            out.append((_dt(f), _dt(min(bf, to))))
        if max(bt, f) < to:
            out.append((_dt(max(bt, f)), _dt(to)))
        return out
    return [(_dt(f), _dt(to))]


def _overlaps(start: datetime, dur: int,
              busy: list[tuple[datetime, int]]) -> bool:
    end = start + timedelta(minutes=dur)
    for b_start, b_dur in busy:
        if b_start < end and start < b_start + timedelta(minutes=b_dur):
            return True
    return False


def fits_clinic(start: datetime, duration: int) -> bool:
    """Интервал целиком внутри рабочего окна КЛИНИКИ (обед разрезает)."""
    h = hours_for(start.date())
    if not h:
        return False
    d0 = start.date()
    f, to = int(h[0]), int(h[1])
    bf, bt = (int(h[2]), int(h[3])) if len(h) >= 4 else (to, to)

    def _dt(hour: int) -> datetime:
        return datetime(d0.year, d0.month, d0.day, hour, 0, tzinfo=TZ)

    # ⚠️ разрез тем же условием, что в _windows: настройки допускают обед
    # ВПРИТЫК к открытию или закрытию (f == bf или bt == to), и строгое
    # «bf < bt < to and f < bf» на таком дне схлопывало окно в одно целое —
    # запись в перерыв принималась, хотя канва и free_starts его исключают
    if bf < bt and f < bt and bf < to:
        wins = []
        if f < bf:
            wins.append((_dt(f), _dt(min(bf, to))))
        if max(bt, f) < to:
            wins.append((_dt(max(bt, f)), _dt(to)))
    else:
        wins = [(_dt(f), _dt(to))]
    end = start + timedelta(minutes=duration)
    return any(w_s <= start and end <= w_e for w_s, w_e in wins)


def fits_doctor(dk: str, start: datetime, duration: int) -> bool:
    """Интервал целиком внутри рабочего окна ВРАЧА — те самые окна (_windows),
    из которых free_starts предлагает слоты: часы клиники, суженные его
    work_from/work_to, обед разрезает. Занятость сюда не входит — её атомарно
    перепроверяет db при вставке."""
    end = start + timedelta(minutes=duration)
    return any(w_s <= start and end <= w_e
               for w_s, w_e in _windows(dk, start.date()))


def work_minutes(dk: str, d: date) -> int:
    """Рабочие минуты врача за день (для ёмкости в статистике)."""
    return sum(int((e - s).total_seconds()) // 60 for s, e in _windows(dk, d))


def is_past(dt: datetime) -> bool:
    """Старт уже прошёл. Одна граница на всех: free_starts предлагает только
    t > now, и всё, что принимает выбранный час, обязано отказывать по тому же
    правилу — иначе форма показывает будущее, а POST принимает прошлое."""
    return dt <= datetime.now(TZ)


def is_past_day(d: date) -> bool:
    """День закрыт. ⚠️ Для ЗАПРЕТА берётся is_past (мгновенная граница), а для
    предупреждения — эта, дневная. Разница не косметическая: пациента без
    записи регистратура вносит в идущий час, и на мгновенной границе такой
    визит — «в прошлом». Жёлтый баннер по нескольку раз в день на нормальной
    работе приучает не читать баннеры вовсе, и настоящая опечатка в дате
    проходит незамеченной."""
    return d < datetime.now(TZ).date()


async def free_starts(
    doc_key: str, d: date, duration: int,
    allowed_keys: list[str] | None = None,
) -> list[datetime]:
    """Свободные СТАРТЫ для услуги данной длительности: 30-мин сетка внутри
    рабочих окон врача, интервал влезает в окно и не пересекает занятые."""
    now = datetime.now(TZ)
    day_start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=TZ)
    day_end = day_start + timedelta(days=1)
    keys = ([doc_key] if doc_key != "any"
            else (allowed_keys or list(ACTIVE_DOCTORS)))
    free: set[datetime] = set()
    for k in keys:
        busy = await db.booked_intervals(k, DOCTORS.get(k, ""), day_start, day_end)
        for w_start, w_end in _windows(k, d):
            t_cur = w_start
            while t_cur + timedelta(minutes=duration) <= w_end:
                if t_cur > now and not _overlaps(t_cur, duration, busy):
                    free.add(t_cur)
                t_cur += timedelta(minutes=GRID_STEP)
    return sorted(free)


async def free_slots(
    doc_key: str, d: date, allowed_keys: list[str] | None = None
) -> list[datetime]:
    """Свободные часовые окна (для дашборда «liber de la»)."""
    return await free_starts(doc_key, d, 60, allowed_keys)


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
    if not usable:
        return rows
    # сид раскладывается последовательно с учётом длительности услуги,
    # чтобы 90-минутные демо-записи не пересекались со следующими
    cursor = usable[0]
    day_end = usable[-1] + timedelta(hours=1)
    i = 0
    for key, svc in SERVICES.items():
        if i >= len(demo_people):
            break
        dur = svc_duration(key)
        if cursor + timedelta(minutes=dur) > day_end:
            break
        items = allowed_doc_items(key)
        if not items:
            continue  # услугу некому выполнять (врач выключен) — не падаем
        dk, doctor = items[0]
        name, phone, year = demo_people[i]
        i += 1
        # ⛔ СЛОВАРЁМ, а не кортежем (08-10, находка аудита). Раньше здесь был
        # кортеж из девяти значений, который `db.seed` распаковывал позиционно
        # через `admin_add(*row)`. 08-07 в `admin_add` добавили `birth_date`
        # седьмым параметром — и всё правое поехало на одну позицию: ключ врача
        # уехал в дату рождения, ключ услуги в id врача, длительность в id
        # услуги. Ни одна проверка не покраснела, потому что типов у SQLite
        # нет, а демо-визиты просто вставали «вне списка» с нулевой загрузкой
        # кресел. Именованные аргументы ломаются ГРОМКО при следующей вставке.
        rows.append({"name": name, "phone": phone, "service": svc["ro"],
                     "doctor": doctor, "starts_at": cursor, "birth_year": year,
                     "doctor_id": dk, "service_id": key, "duration_min": dur})
        step = ((dur + 59) // 60) * 60  # следующий сид с чистого часа
        cursor += timedelta(minutes=step)
    return rows
