"""Импорт из Google Calendar: готовое событие -> заготовка строки журнала.

Модуль чистый: из проекта знает только ics.py. Заготовка — не запись: врач,
телефон и имя здесь только подсказки, которые утверждает человек."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import ics

STEP = 5
MAX_MINUTES = 240

OK = "ok"
SKIPPED = "skipped"
UNPARSED = "unparsed"
KINDS = (OK, SKIPPED, UNPARSED)

# ---- почему пропущено ----

PAST = "past"
ALL_DAY = "all_day"
CANCELLED = "cancelled"
BEYOND = "beyond"
SKIPS = (PAST, ALL_DAY, CANCELLED, BEYOND)

# ---- длительность, которую должен посмотреть человек ----

CHECK_LONG = "long"
CHECK_NONE = "no_duration"
CHECKS = (CHECK_LONG, CHECK_NONE)

NEW, SAME, CHANGED = "new", "same", "changed"

key = ics.occurrence_key


@dataclass(frozen=True)
class Draft:
    key: str
    kind: str
    why: str = ""
    detail: str = ""
    start: datetime | None = None
    minutes: int = 0
    src_start: datetime | None = None
    src_minutes: int = 0
    rounded: bool = False
    check: str = ""
    title: str = ""
    description: str = ""
    location: str = ""
    attendees: tuple = ()
    series: bool = False
    moved: bool = False
    note: str = ""
    phones: tuple = ()
    doctor: str = ""
    doctor_hits: tuple = ()
    patient: str = ""
    stamp: str = ""


def round_slot(start: datetime, minutes: int) -> tuple[datetime, int]:
    """Начало — к ближайшим пяти минутам, длина — как в календаре; длина, не кратная
    пяти, — вверх. Счёт в UTC: перевод часов сдвинул бы стенные минуты."""
    begin = start.astimezone(timezone.utc).replace(second=0, microsecond=0)
    off = begin.minute % STEP
    begin += timedelta(minutes=STEP - off if off * 2 > STEP else -off)
    return begin, max(STEP, minutes + -minutes % STEP)


def stamp(start: datetime, minutes: int, title: str) -> str:
    """Отпечаток — от значений ФАЙЛА, не от округлённых: иначе событие 9:07 каждый
    раз выглядело бы изменившимся. Название — хешем: в таблице имён быть не должно."""
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return f"{start.astimezone(timezone.utc):%Y%m%dT%H%MZ}|{minutes}|{digest}"


# Дата — с точкой или дробью (день.месяц.год) либо год-месяц-день. Через дефис
# «12-34-56» пишут номер, не дату; и кусок номера «069.12.03.85» — не дата.
_DATEISH = re.compile(r"(?<![\d./-])(?:[0-3]?\d[./][01]?\d[./](?:\d{4}|\d{2})|\d{4}-[01]\d-[0-3]\d)(?!\d)")
_RUN = re.compile(r"\+?\d[\d \-().]*\d")
COUNTRY = "373"


def _national(digits: str) -> str:
    if len(digits) == 9 and digits[0] == "0":
        digits = digits[1:]
    return digits if len(digits) == 8 and digits[0] != "0" else ""


def _normal(groups: list[str], plus: bool) -> str:
    d = "".join(groups)
    if plus or d.startswith("00"):
        intl = d if plus else d[2:]
        if intl.startswith(COUNTRY):
            return _national(intl[len(COUNTRY):])
        # Чужая страна принимается только с явным плюсом: без него длинный ряд
        # цифр — скорее номер полиса или сумма.
        return "+" + intl if plus and 9 <= len(intl) <= 15 else ""
    if d.startswith(COUNTRY) and len(d) in (11, 12):
        return _national(d[len(COUNTRY):])
    if len(d) == 9 and d[0] == "0":
        return _national(d)
    # Восемь цифр без нуля и кода — только мобильные, и не четыре пары: так
    # в названии пишут номера зубов («64 65 74 75»).
    if len(d) == 8 and d[0] in "67" and [len(g) for g in groups] != [2, 2, 2, 2]:
        return d
    return ""


def phones(text: str) -> tuple[str, ...]:
    """Телефоны из текста, только узнаваемые формы: дата рождения, сумма и IDNP номером не становятся."""
    out: list[str] = []
    for run in _RUN.finditer(_DATEISH.sub(" | ", text or "")):
        groups = re.findall(r"\d+", run.group())
        i = 0
        while i < len(groups):
            # Самый длинный годный кусок: после номера через пробел часто
            # стоит сумма или время, и ряд цифр целиком номером не является.
            for j in range(min(len(groups), i + 8), i, -1):
                found = _normal(groups[i:j], run.group().startswith("+") and i == 0)
                if found:
                    if found not in out:
                        out.append(found)
                    i = j - 1
                    break
            i += 1
    return tuple(out)


_WORD = re.compile(r"[^\W\d_]+")
_NAME = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_MARKS = frozenset({"dr", "doctor", "doctorul", "medic", "medicul", "др", "доктор", "врач"})
_NOISE = frozenset({"tel", "telefon", "mob", "nr", "тел", "телефон", "моб"})
NAME_WORDS = 4


def fold(text: str) -> str:
    """Без регистра и диакритики: «Țurcanu», «Ţurcanu» и «turcanu» — одно."""
    s = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _doctor_words(name: str) -> list[str]:
    return [w for w in _WORD.findall(fold(name)) if w not in _MARKS]


def doctor_hint(title: str, doctors: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    """(врач или "", все совпавшие). Сравнивается только фамилия и инициалы первым
    словом: имя врача слишком часто оказывается именем пациента. Совпали двое —
    выбирает человек, кроме случая, когда ровно один назван со словом «dr»."""
    raw = _WORD.findall(title or "")
    words = [fold(w) for w in raw]
    hits, marked = [], []
    for doc, name in doctors.items():
        parts = _doctor_words(name)
        if not parts:
            continue
        at = [i for i, w in enumerate(words) if w == parts[-1]] if len(parts[-1]) >= 3 else []
        if at:
            hits.append(doc)
            for i in at:
                # «Dr. Elena Rusu»: между словом «dr» и фамилией стоит имя врача.
                while i > 0 and words[i - 1] in parts:
                    i -= 1
                if i > 0 and words[i - 1] in _MARKS:
                    marked.append(doc)
                    break
        elif len(parts) >= 2 and raw and raw[0].isupper() and len(raw[0]) == len(parts):
            initials = "".join(p[0] for p in parts)
            if words[0] in (initials, initials[::-1]):
                hits.append(doc)
    pick = marked if len(marked) == 1 else hits
    return (pick[0] if len(pick) == 1 else ""), tuple(hits)


def _within(word: str, parts: list[str]) -> bool:
    return all(p in parts for p in word.split("-"))


def _initials_of(raw: list[str], words: list[str], parts: list[str]) -> bool:
    initials = "".join(p[0] for p in parts)
    return (len(parts) >= 2 and bool(raw) and raw[0].isupper() and len(raw[0]) == len(parts)
            and words[0] in (initials, initials[::-1]))


def _split(title: str, doctors: dict[str, str]) -> tuple[list[str], list[str], bool]:
    """(имя целиком, имя без слов узнанного врача, однофамилец ли).

    Слова имени делятся на группы: группу рвёт всё, кроме пробела, — запятая, тире, номер, скобка,
    слово «dr». Врач отделён, если его фамилия стоит после «dr», врач узнан по инициалам или у
    фамилии своя группа только из слов его имени («…, 069… — Grecu»): тогда эта группа из имени
    уходит. Однофамилец — когда так сказать нельзя: фамилия врача есть только внутри имени
    («Ana Marin 069…»), или без «dr» имени, кроме имени врача, не осталось («Marin 069…»)."""
    found = list(_NAME.finditer(title or ""))
    raw = [m.group() for m in found]
    words = [fold(w) for w in raw]
    names = [_doctor_words(n) for n in doctors.values()]
    drop: set[int] = set()
    after_mark: set[int] = set()
    for i, w in enumerate(words):
        if w in _NOISE:
            drop.add(i)
        elif w in _MARKS:
            drop.add(i)
            for parts in names:
                j = i + 1
                while j < len(words) and _within(words[j], parts):
                    drop.add(j)
                    after_mark.add(j)
                    j += 1
    if any(_initials_of(raw, words, parts) for parts in names):
        drop.add(0)
    groups: list[list[int]] = []
    gap = True
    for i, m in enumerate(found):
        if i in drop:
            gap = True
            continue
        if gap or not title[found[i - 1].end():m.start()].isspace():
            groups.append([])
        groups[-1].append(i)
        gap = False
    full = [raw[i] for g in groups for i in g]
    dk, _hits = doctor_hint(title, doctors)
    if not dk:
        return full, full, False
    parts = _doctor_words(doctors[dk])
    sur = parts[-1]
    strong = any(sur in words[i].split("-") for i in after_mark) or _initials_of(raw, words, parts)
    alone = [g for g in groups if all(_within(words[i], parts) for i in g)
             and any(sur in words[i].split("-") for i in g)]
    rest = [g for g in groups if g not in alone]
    if strong and not rest:
        # «Elena Rusu 069… — Dr. Rusu»: врач назван с «dr», а имя врача без него — имя пациента
        alone, rest = [], alone
    inside = any(sur in words[i].split("-") for g in rest for i in g)
    namesake = not strong and (not alone and inside or bool(alone) and not rest)
    # второе прочтение однофамильца: фамилия внутри имени — это врач
    short = [raw[i] for g in rest for i in g if not (namesake and words[i] == sur)]
    return full, short, namesake


def patient_guess(title: str, doctors: dict[str, str], *, cut: bool = False) -> str:
    """Заготовка имени пациента; слова услуги прилипают — без человека не утверждать. Слова, по
    которым узнан врач, из имени уходят; у однофамильца (`namesake`) имя остаётся целым, а `cut`
    отдаёт второе прочтение — без слов врача."""
    full, short, unclear = _split(title, doctors)
    keep = short if cut or not unclear else full
    return " ".join(keep[:NAME_WORDS])


def namesake(title: str, doctors: dict[str, str]) -> bool:
    """Нельзя сказать, где в названии врач, а где пациент: без человека не переносить."""
    return _split(title, doctors)[2]


def convert(occ: ics.Occurrence, *, tz, now: datetime, doctors: dict[str, str],
            until: datetime | None = None) -> Draft:
    """`until` — конец выбранного периода: позже него — «пропущено», не потеря."""
    base = dict(key=occ.key, title=occ.title, description=occ.description,
                location=occ.location, attendees=tuple(occ.attendees),
                series=occ.series, moved=occ.moved, note=occ.note)
    src = occ.start.astimezone(tz).replace(second=0, microsecond=0) if occ.start else None
    if occ.problem:
        return Draft(kind=UNPARSED, why=occ.problem, detail=occ.detail, src_start=src, **base)
    why = ""
    if (occ.status or "").upper() == ics.CANCELLED:
        why = CANCELLED
    elif src is None:
        why = ALL_DAY if occ.day is not None else ""
        if not why:
            return Draft(kind=UNPARSED, why=ics.NO_START, **base)
    elif src <= now:
        why = PAST
    elif until is not None and src > until:
        why = BEYOND
    if why:
        return Draft(kind=SKIPPED, why=why, src_start=src, src_minutes=occ.minutes, **base)
    begin, minutes = round_slot(src, occ.minutes)
    start = begin.astimezone(tz)
    check = CHECK_NONE if occ.minutes <= 0 else CHECK_LONG if minutes > MAX_MINUTES else ""
    doctor, hits = doctor_hint(occ.title, doctors)
    return Draft(kind=OK, start=start, minutes=minutes, src_start=src, src_minutes=occ.minutes,
                 rounded=start != src or (occ.minutes > 0 and minutes != occ.minutes),
                 check=check, phones=phones(occ.title + "\n" + occ.description),
                 doctor=doctor, doctor_hits=hits, patient=patient_guess(occ.title, doctors),
                 stamp=stamp(src, occ.minutes, occ.title), **base)


def convert_all(occs, *, tz, now: datetime, doctors: dict[str, str],
                until: datetime | None = None) -> list[Draft]:
    """Заготовки по времени; без времени — в конце, в порядке файла."""
    drafts = [convert(o, tz=tz, now=now, doctors=doctors, until=until) for o in occs]
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(drafts, key=lambda d: (d.start or d.src_start or far, d.key))


def overlaps(rows) -> list[tuple[str, str]]:
    """rows — (ключ, группа, старт, минуты): пары ключей одной группы с пересечением интервалов."""
    by_group: dict = {}
    for k, group, start, minutes in rows:
        if group and start is not None:
            begin = start.astimezone(timezone.utc)
            by_group.setdefault(group, []).append((begin, begin + timedelta(minutes=minutes), k))
    out = []
    for items in by_group.values():
        items.sort(key=lambda it: (it[0], it[2]))
        for i, (_, end, k) in enumerate(items):
            for begin2, _, k2 in items[i + 1:]:
                if begin2 >= end:
                    break
                out.append((k, k2))
    return out


def compare(drafts, stored: dict[str, str]) -> dict[str, str]:
    """{ключ: новая / та же / изменилась} для годных заготовок; `stored` — отпечатки прошлого импорта."""
    return {d.key: NEW if d.key not in stored else SAME if stored[d.key] == d.stamp else CHANGED
            for d in drafts if d.kind == OK}
