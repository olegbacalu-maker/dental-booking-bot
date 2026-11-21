"""Импорт пациентов из таблицы. Один разбор отвечает и проверке, и каждой
порции записи, поэтому между запросами ничего не хранится."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re

from ... import db
from ... import engine as eng
from ...core import book, tabfile
from . import profile_rules as prules

BATCH = 200
GROUP_CAP = 300
PREVIEW_ROWS = 8
HEADER_SCAN = 25
DOCS_CAP = 500

FIELDS = [
    ("", "Nu importa"),
    ("full", "Nume și prenume"),
    ("last", "Nume (familie)"),
    ("first", "Prenume"),
    ("patr", "Patronimic"),
    ("phone", "Telefon"),
    ("phone2", "Telefon 2"),
    ("birth", "Data nașterii"),
    ("idnp", "IDNP"),
    ("gender", "Gen"),
    ("email", "E-mail"),
    ("address", "Adresă"),
    ("insurance", "Asigurare"),
    ("doctor", "Medic (curant și al programării)"),
    ("file_no", "Nr. dosar"),
    ("notes", "Notițe"),
    ("appt", "Data programării"),
    ("appt_time", "Ora programării"),
    ("appt_dur", "Durata programării (min)"),
    ("appt_svc", "Procedură / Serviciu"),
    ("appt_note", "Comentariu la programare"),
]
FIELD_IDS = {f for f, _l in FIELDS}
_MULTI = {"notes", "phone", "phone2"}

# порядок полей — приоритет при равной длине слова
_WORDS = {
    "full": ["nume prenume", "nume si prenume", "numele prenumele", "numele si prenumele",
             "nume complet", "pacient", "pacientul", "client", "фио", "ф и о", "пациент",
             "фамилия имя", "фамилия имя отчество", "клиент", "full name", "name", "patient"],
    "last": ["nume", "numele", "nume de familie", "familia", "фамилия", "last name", "surname"],
    "first": ["prenume", "prenumele", "имя", "first name", "given name"],
    "patr": ["patronimic", "отчество", "middle name"],
    "appt": ["data programarii", "programare", "programarea", "programarii", "data vizitei",
             "ziua", "data si ora", "data ora", "data programare", "дата записи", "запись",
             "дата визита", "дата приема", "appointment", "appointment date"],
    "appt_time": ["ora", "ora programarii", "orele", "ora vizitei", "время", "время записи",
                  "время приема", "час", "time", "hour"],
    "appt_dur": ["durata", "durata programarii", "durata vizitei", "min", "minute", "длительность",
                 "продолжительность", "мин", "минут", "duration"],
    "appt_svc": ["procedura", "procedura programarii", "serviciu", "serviciul", "manopera", "услуга",
                 "процедура", "service", "procedure"],
    "appt_note": ["comentariu programare", "comentariu la programare", "nota programare",
                  "примечание к записи", "комментарий к записи"],
    "birth": ["data nasterii", "data nast", "data nas", "data nasc", "data n", "d n", "nasterii",
              "nascut", "data de nastere", "anul nasterii", "anul nast", "дата рожд", "д рожд",
              "год рожд", "г р", "дата рождения", "рождения", "д р", "др", "родился",
              "год рождения", "birth date", "date of birth", "birth", "dob", "birthday"],
    "idnp": ["idnp", "cod personal", "codul personal", "cnp", "личный код",
             "идентификационный номер"],
    "email": ["e mail", "email", "mail", "posta", "почта", "эл почта", "электронная почта"],
    "phone": ["telefon", "telefonul", "tel", "nr telefon", "nr tel", "numar telefon",
              "numar de telefon", "mobil", "gsm", "contact", "телефон", "тел", "моб",
              "мобильный", "номер телефона", "phone", "mobile", "phone number"],
    "gender": ["gen", "sex", "sexul", "пол", "gender"],
    "address": ["adresa", "adresa de domiciliu", "domiciliu", "localitate", "oras", "адрес",
                "город", "address"],
    "insurance": ["asigurare", "polita", "cnam", "полис", "страховка", "insurance"],
    "doctor": ["medic", "medicul", "medic curant", "doctor", "doctorul", "dr", "medic stomatolog",
               "stomatolog", "врач", "лечащий врач", "доктор", "стоматолог"],
    "file_no": ["nr fisa", "nr fisei", "nr dosar", "numar fisa", "fisa", "номер карты", "карта",
                "file no"],
    "notes": ["nota", "note", "notite", "observatii", "obs", "comentariu", "comentarii", "mentiuni",
              "примечание", "примечания", "заметки", "комментарий", "notes", "comment"],
}
# узнаются, чтобы не импортировать: счётчики и то, что программа считает сама
_SKIP = {"id", "nr", "nr crt", "n", "no", "п п", "n п п", "varsta", "возраст", "age", "sold",
         "sold mdl", "status", "canal", "vizite", "ultima vizita", "urmatoarea vizita",
         "inregistrat", "loc nastere", "locul nasterii", "locul de nastere", "место рождения"}

# экран печатает эти слова как есть, своего словаря у него нет
REASONS = {
    "no_name": "lipsește numele",
    "title": "pare un titlu, nu un pacient („{}”)",
    "name_case": "numele a fost rescris cu majuscule doar la inițiale",
    "tel_zero": "zero adăugat la începutul telefonului",
    "tel_foreign": "număr străin, păstrat cum este în fișier",
    "tel_bad": "telefon necitit („{}”), trecut în notițe",
    "tel_more": "al doilea telefon trecut în notițe",
    "bd_bad": "data nașterii necitită („{}”)",
    "bd_year": "doar anul nașterii",
    "bd_serial": "data nașterii citită dintr-un număr Excel, verificați",
    "idnp_zero": "zero adăugat la începutul IDNP",
    "idnp_len": "IDNP nu are 13 cifre („{}”), lăsat gol",
    "idnp_check": "cifra de control a IDNP nu corespunde, verificați",
    "gender_bad": "genul necitit („{}”)",
    "doc_unknown": "medicul „{}” nu este în lista clinicii, trecut în notițe",
    "dur_bad": "durata necitită („{}”), se pune durata procedurii",
    "svc_other": "procedura „{}” nu este în lista clinicii — programare cu procedura aleasă",
    "notes_cut": "notițe scurtate la 500 de caractere",
    "family": "același telefon ca la: {}",
    "archived": "pacientul este în arhivă",
    "ex_idnp": "există deja (același IDNP): {}",
    "ex_phone": "există deja (același telefon și nume): {}",
    "ex_birth": "posibil există deja (același nume și dată a nașterii): {}",
    "ex_bare": "există deja (același nume, fără alte date): {}",
    "dup_idnp": "dublu al rândului {} (același IDNP)",
    "dup_phone": "dublu al rândului {} (același telefon și nume)",
    "dup_birth": "posibil dublu al rândului {} (același nume și dată a nașterii)",
    "dup_bare": "dublu al rândului {} (același nume, fără alte date)",
    # programarea din rând: de ce nu se pune în agendă
    "v_no_date": "ora fără dată",
    "v_bad_date": "data programării necitită („{}”)",
    "v_no_time": "programare fără oră — data trecută în notițe",
    "v_bad_time": "ora necitită („{}”) — data trecută în notițe",
    "v_bad_range": "intervalul orei nu se citește („{}”) — data trecută în notițe",
    "v_no_doc": "fără medic — data trecută în notițe",
    "v_doc_unknown": "medic necunoscut („{}”) — data și medicul trecute în notițe",
    "v_doc_skip": "medicul ales: „Nu programa” — data trecută în notițe",
    "v_past_off": "vizită trecută — neimportată (bifa „Importă și vizitele trecute”)",
    "v_row_bad": "rândul nu intră",
    "v_busy_file": "ocupat — rândul {} are programare la același medic în acest timp",
    "v_dup_file": "pacientul are deja o programare în acest timp (rândul {})",
    "v_conflict": "ocupat — medicul are altă programare în acest timp",
    "v_dup": "pacientul are deja o programare în acest timp",
    "v_exists": "există deja (aceeași programare la pacient)",
    "v_outside": "în afara programului clinicii",
    "v_outside_doc": "în afara programului medicului",
    "v_bad_off": "medic inactiv în clinică",
    "v_bad_dur": "durata nu se potrivește (5–240 de minute, din 5 în 5)",
    "v_bad": "programarea nu se poate pune",
    "v_room": "cabinetul medicului este ocupat de alt medic — programarea se pune",
    "v_to_row": "programarea se adaugă la fișa din rândul {}",
    "v_to_card": "programarea se adaugă la fișa existentă: {}",
    "v_rounded": "ora din fișier rotunjită la grila de 5 minute: {}",
}
# Код ответа `book.book_visit` / `book.probe` → слово строки предпросмотра и отчёта.
_BOOK_WHY = {"conflict": "v_conflict", "dup": "v_dup", "exists": "v_exists", "outside": "v_outside",
             "outside_doc": "v_outside_doc", "bad_off": "v_bad_off", "bad_dur": "v_bad_dur"}
VISIT_GROUPS = [("v_new", "Programări noi"), ("v_past", "Vizite trecute (istoric)"),
                ("v_no", "Nu se programează")]
VISIT_RESULT = {"v_new": "programată", "v_past": "în istoric (finalizată)", "v_no": "nu s-a programat"}
GROUPS = [("new", "Fișe noi"), ("noted", "Cu observații"), ("exists", "Există deja"),
          ("dup", "Dubluri în fișier"), ("bad", "Nu intră")]
RESULT = {"new": "fișă nouă", "noted": "fișă nouă, cu observații", "exists": "există deja",
          "dup": "dublu în fișier", "bad": "nu a intrat"}
FILL_LABEL = {"birth_date": "data nașterii", "gender": "gen", "idnp": "IDNP", "email": "e-mail",
              "address": "adresă", "insurance": "asigurare", "file_no": "nr. dosar"}


def why(code: str, arg="") -> str:
    return REASONS[code].format(arg)


_DIA = str.maketrans("ăâîșşțţё", "aaisstte")


def fold(s) -> str:
    s = (str(s) if s is not None else "").lower().translate(_DIA)
    return re.sub(r"[^a-zа-я0-9]+", " ", s).strip()


def _head_key(title) -> str:
    """Шапка без скобок: «IDNP (demo)» узнаётся как «IDNP»."""
    return fold(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", str(title or "")))


def _field_of(key: str) -> str:
    best, score = "", 0
    for f, words in _WORDS.items():
        for w in words:
            if key == w:
                s = 1000 + len(w)
            elif f" {w} " in f" {key} ":
                s = len(w)
            else:
                continue
            if s > score:
                best, score = f, s
    return best


def guess_columns(header: list) -> dict[int, str]:
    keys = [_head_key(h) for h in header]
    found = [("" if (not k or k in _SKIP) else _field_of(k)) for k in keys]
    has_first = "first" in found
    out: dict[int, str] = {}
    used: set[str] = set()
    for i, f in enumerate(found):
        if f == "last" and not has_first:
            f = "full"                     # одиночное «Nume» — имя целиком
        elif f == "full" and has_first and keys[i] in ("name", "nume"):
            f = "last"
        if f == "phone" and "phone" in used:
            f = "phone2"
        if not f or (f in used and f not in _MULTI):
            continue
        out[i] = f
        used.add(f)
    return out


def find_header(rows: list) -> tuple[int, dict[int, str]]:
    """Первая строка, где узнано имя и ещё хоть что-то; (0, {}) — шапки нет."""
    best = (0, {})
    for rno, line in rows[:HEADER_SCAN]:
        g = guess_columns(line)
        if not {"full", "last", "first"} & set(g.values()):
            continue
        if len(g) >= 2:
            return rno, g
        if len(g) > len(best[1]):
            best = (rno, g)
    return best


def parse_opts(raw: str) -> dict | None:
    """None — не разобрать; чего в выборе нет, то угадывает программа."""
    try:
        o = json.loads(raw) if raw else {}
    except ValueError:
        return None
    if not isinstance(o, dict):
        return None
    out = {"sheet": 0, "header": None, "cols": None, "enc": "", "delim": "",
           "fill": False, "force": [], "docs": {}, "past": True, "sms": False, "svc": ""}
    try:
        out["sheet"] = int(o.get("sheet") or 0)
        if o.get("header") is not None:
            out["header"] = int(o["header"])
        if o.get("cols") is not None:
            out["cols"] = {int(k): str(v) for k, v in dict(o["cols"]).items() if v}
        out["force"] = sorted({int(x) for x in (o.get("force") or [])})
        out["docs"] = {str(k)[:120]: str(v)[:40] for k, v in dict(o.get("docs") or {}).items() if v}
    except (TypeError, ValueError):
        return None
    if len(out["docs"]) > DOCS_CAP:
        return None
    if out["sheet"] < 0 or (out["header"] or 0) < 0:
        return None
    if out["cols"] is not None and (set(out["cols"].values()) - FIELD_IDS
                                    or any(k < 0 for k in out["cols"])):
        return None
    out["enc"] = o.get("enc") if o.get("enc") in tabfile.ENCODINGS else ""
    out["delim"] = o.get("delim") if o.get("delim") in tabfile.DELIMITERS else ""
    out["fill"] = o.get("fill") is True
    # Визиты из файла: прошлые — в историю (вкл. по умолчанию), SMS по будущим — выключены, пока
    # человек не включит сам; процедура для строк без своей — ключ услуги агенды.
    out["past"] = o.get("past") is not False
    out["sms"] = o.get("sms") is True
    out["svc"] = str(o.get("svc") or "")[:40]
    return out


def resolve(table: tabfile.Table, opts: dict) -> dict | None:
    """Выбор, доведённый до конкретного; None — листа с таким номером нет."""
    if opts["sheet"] >= len(table.sheets):
        return None
    rows = table.sheets[opts["sheet"]].rows
    header, cols = opts["header"], opts["cols"]
    if header is None:
        header, guessed = find_header(rows)
    else:
        line = next((ln for rno, ln in rows if rno == header), [])
        guessed = guess_columns(line) if header else {}
    if cols is None:
        cols = guessed
    return {"sheet": opts["sheet"], "header": header, "cols": dict(sorted(cols.items())),
            "enc": table.enc, "delim": table.delim, "fill": opts["fill"],
            "force": opts["force"], "docs": dict(sorted((opts.get("docs") or {}).items())),
            "past": opts.get("past", True), "sms": opts.get("sms", False),
            "svc": default_service(opts.get("svc", ""))}


def agenda_services() -> list[tuple[str, str]]:
    """Услуги, которые можно поставить визитом (окно записи журнала), в порядке профиля."""
    return [(sid, s["ro"]) for sid, s in eng.SERVICES.items() if eng.in_agenda(sid)]


def default_service(sid: str) -> str:
    """Процедура визита для строк без своей: выбор человека, иначе консультация, иначе первая не
    срочная услуга агенды. Срочная («Durere acută») умолчанием не годится: у клиники она часто
    первая в списке, а визит из старой программы — не острая боль."""
    if sid and eng.in_agenda(sid):
        return sid
    first = agenda_services()
    consult = [x for x, name in first if fold(name).startswith("consult") or x == "consult"]
    calm = [x for x, _n in first if not eng.SERVICES[x].get("urgent")]
    return (consult or calm or [x for x, _n in first] or [""])[0]


def has_visits(res: dict) -> bool:
    """Колонка даты записи назначена: строки файла становятся визитами."""
    return bool({"appt", "appt_time"} & set(res["cols"].values()))


def token(blob: bytes, res: dict) -> str:
    """Импортируется ровно то, что человек видел на шаге проверки."""
    canon = json.dumps({**res, "cols": {str(k): v for k, v in res["cols"].items()}},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    h = hashlib.sha256(blob)
    h.update(b"|" + canon.encode("utf-8"))
    return h.hexdigest()[:32]


def ready(res: dict) -> bool:
    return bool({"full", "last", "first"} & set(res["cols"].values()))


def _text(v) -> str:
    if isinstance(v, _dt.datetime):
        return v.strftime("%d.%m.%Y %H:%M") if v.time() != _dt.time(0, 0) else v.strftime("%d.%m.%Y")
    if isinstance(v, _dt.date):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, _dt.time):
        return v.strftime("%H:%M")
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _name(parts: list) -> tuple[str, bool]:
    s = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip(" ,.;")
    recased = False
    if s and (s.isupper() or s.islower()):
        s = re.sub(r"[^\W\d_]+", lambda m: m.group().capitalize(), s)
        recased = True
    return s[:120], recased


def _local(s) -> bool:
    k = db.phone_key(s)
    return len(k) == 9 and k[0] == "0"


def _numbers(chunk: str) -> list[str]:
    """Группы через пробел или дефис — один номер, если вместе он полный:
    «060 000 205» не делится, хотя вторая группа и похожа на начало номера.
    Делится только то, где каждая часть — полный номер сама."""
    out = []
    for part in re.split(r"(?<=\d)[\s\-–.]*(?=\+)", chunk):
        if _local(part):
            out.append(part)
            continue
        acc, cut = [], []
        for g in re.split(r"[\s\-–]+", part.strip()):
            acc.append(g)
            if _local(" ".join(acc)):
                cut.append(" ".join(acc))
                acc = []
        rest = db._digits(" ".join(acc))
        if cut and (len(cut) > 1 or rest) and (not rest or 10 <= len(rest) <= 15):
            out.extend(cut + ([" ".join(acc)] if rest else []))
        else:
            out.append(part)
    return out


def phones(values: list) -> tuple[list[str], list[tuple]]:
    """Номера в виде клиники (`069123456`); два столбца с одним номером — один номер."""
    out, notes, seen = [], [], set()
    for raw in values:
        parts = [p for chunk in re.split(r"[;,/\n]", str(raw)) for p in _numbers(chunk)]
        for part in parts:
            d = db._digits(part)
            if not d:
                continue
            key = db.phone_key(d)
            if len(key) == 9 and key[0] == "0":
                num = key
                if len(d) == 8:
                    notes.append(("tel_zero", ""))
            elif 6 <= len(d) <= 15 and not (d[0] == "0" and d[1:2] != "0"):
                # с одного нуля пишут только наши номера: не той длины — не прочитан
                plus = part.strip().startswith("+") or d.startswith("00")
                num = ("+" if plus else "") + (d[2:] if d.startswith("00") else d)
                notes.append(("tel_foreign", ""))
            else:
                notes.append(("tel_bad", part.strip()[:40]))
                continue
            if key not in seen:
                seen.add(key)
                out.append(num)
    return out, notes


_MONTHS = {m: i for i, names in enumerate([
    ("ian", "янв", "jan"), ("feb", "фев"), ("mar", "мар"), ("apr", "апр"),
    ("mai", "май", "мая", "may"), ("iun", "июн", "jun"), ("iul", "июл", "jul"),
    ("aug", "авг"), ("sep", "сен"), ("oct", "окт"), ("noi", "ноя", "nov"),
    ("dec", "дек")], start=1) for m in names}


def parse_date(raw) -> tuple[_dt.date | None, int | None, str]:
    """(дата, одиночный год, пометка). День первым: «1/2/03» — первое февраля."""
    if isinstance(raw, _dt.datetime):
        return raw.date(), None, ""         # `tabfile.read(times=True)`: час дню рождения не нужен
    if isinstance(raw, _dt.date):
        return raw, None, ""
    s = str(raw).strip().lower().rstrip(".г ").strip()
    today = _dt.date.today()
    if re.fullmatch(r"(18|19|20)\d\d", s):
        return None, int(s), "bd_year"
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t].*)?", s)
    if m:
        y, mo, da = map(int, m.groups())
    elif (m := re.fullmatch(r"(\d{1,2})[./\-\s](\d{1,2})[./\-\s](\d{2}|\d{4})", s)):
        da, mo, y = map(int, m.groups())
        if y < 100:
            y += 1900 if y > today.year % 100 else 2000
    elif (m := re.fullmatch(r"(\d{1,2})\s+([a-zа-яă]+)\.?\s+(\d{4})", s)) and m.group(2)[:3] in _MONTHS:
        da, mo, y = int(m.group(1)), _MONTHS[m.group(2)[:3]], int(m.group(3))
    elif re.fullmatch(r"\d{4,5}", s):
        # дата Excel, потерявшая формат ячейки: число дней
        return _dt.date(1899, 12, 30) + _dt.timedelta(days=int(s)), None, "bd_serial"
    else:
        return None, None, "bd_bad"
    try:
        return _dt.date(y, mo, da), None, ""
    except ValueError:
        return None, None, "bd_bad"


_CYR = dict(zip("абвгдезийклмнопрстуфхцыэ", "abvgdeziiklmnoprstufhtie"))
_CYR.update({"ё": "e", "ж": "j", "ч": "c", "ш": "s", "щ": "s", "ю": "iu", "я": "ia", "ъ": "",
             "ь": "", "і": "i"})
# одно звучание — одна запись: «Чобану» и «Ciobanu», «Цуркану» и «Țurcanu», «Георге» и «Gheorghe»
_SOUND = [("sh", "s"), ("ch", "c"), ("zh", "j"), ("ts", "t"), ("gh", "g"), ("kh", "h"), ("dj", "g"),
          ("k", "c"), ("y", "i"), ("w", "v"), ("q", "c"), ("x", "cs")]
_TITLES = {"dr", "doctor", "doctorul", "doctora", "medic", "medicul", "med", "stomatolog", "dna",
           "dl", "dnul", "vrac"}


def _sound(word: str) -> str:
    w = "".join(_CYR.get(ch, ch) for ch in word)
    for a, b in _SOUND:
        w = w.replace(a, b)
    w = re.sub(r"([cg])i(?=[aou])", r"\1", w)      # «Cio-», «Giu-» звучат как «Чо-», «Джу-»
    return re.sub(r"(.)\1+", r"\1", w)


def doc_words(name) -> list[str]:
    """Слова имени врача без званий; кириллица и латиница сводятся к одному
    звучанию, буква с точкой («E.») остаётся инициалом."""
    s = re.sub(r"(?i)\bд\s*[-.]\s*р\b\.?", " dr ", str(name or ""))
    return [w for w in (_sound(x) for x in fold(s).split()) if w and w not in _TITLES]


def _doc_score(said: list[str], doc: list[str]) -> int:
    """0 — не он. Каждое полное слово — слово врача, каждый инициал — первая
    буква другого слова; одни инициалы — только все сразу («E. R.»)."""
    full = [w for w in said if len(w) > 1]
    left = list(doc)
    for w in full:
        if w not in left:
            return 0
        left.remove(w)
    for ch in (w for w in said if len(w) == 1):
        hit = next((x for x in left if x[0] == ch), None)
        if hit is None:
            return 0
        left.remove(hit)
    if not said or (not full and (len(said) < 2 or left)):
        return 0
    # «Rusu Elena» ближе к «Rusu Elena», чем к «Rusu Elena Maria»
    return 100 * (len(full) + len(said)) - len(left)


NO_DOCTOR = "-"


class Doctors:
    """Врачи клиники для импорта и решение человека по каждому написанию."""

    def __init__(self, names: dict | None = None, choice: dict | None = None):
        self.names = dict(names or {})
        self.choice = dict(choice or {})
        self._words = {d: doc_words(n) for d, n in self.names.items()}
        self._auto: dict = {}

    def auto(self, key: str, src: str) -> tuple[str, list]:
        """(врач или "", все, кто подошёл одинаково хорошо)."""
        if key not in self._auto:
            said = doc_words(src)
            scores = {d: _doc_score(said, w) for d, w in self._words.items()}
            best = max(scores.values(), default=0)
            cands = sorted(d for d, s in scores.items() if s and s == best)
            self._auto[key] = (cands[0] if len(cands) == 1 else "", cands)
        return self._auto[key]

    def pick(self, key: str, src: str) -> str:
        """Врач, `NO_DOCTOR` или "" — не узнан и не выбран."""
        c = self.choice.get(key, "")
        if c == NO_DOCTOR or c in self.names:
            return c
        return self.auto(key, src)[0]


def doc_key(src) -> str:
    """Одно решение на одно написание: регистр, точки, звание, порядок слов и
    алфавит не важны — «dr. Rusu E.» и «Е. Русу» решаются один раз."""
    return (" ".join(sorted(doc_words(src))) or fold(src))[:120]


_GENDER = {"m": "m", "f": "f", "м": "m", "ж": "f", "b": "m", "masculin": "m", "feminin": "f",
           "barbat": "m", "femeie": "f", "муж": "m", "жен": "f", "мужской": "m",
           "женский": "f", "male": "m", "female": "f"}


def _record(line: int, raw: dict, doctors: Doctors, ctx: dict | None = None) -> dict | None:
    """Строка файла как будущая фиша. None — в назначенных колонках пусто. `ctx` — визит строки:
    `today` (день клиники), `past` (ставить прошлые), `svc` (процедура по умолчанию)."""
    if not raw:
        return None
    rec = {"line": line, "notes_w": [], "err": "", "birth_year": None}
    w = rec["notes_w"]

    def one(f: str) -> str:
        return _text(raw[f][0][1]) if raw.get(f) else ""

    if raw.get("last") or raw.get("first"):
        name, recased = _name([one("last"), one("first"), one("patr")])
    else:
        name, recased = _name([one("full")])
    rec["name"] = name
    if not name or not re.search(r"[^\W\d_]", name):
        rec["err"] = "no_name"
    elif re.search(r"\d", name) and set(raw) <= {"full", "last", "first", "patr"}:
        # «Total: 48», «Ianuarie 2024» в колонке имени: в имени человека цифр нет
        rec["err"] = "title"
    elif recased:
        w.append(("name_case", ""))

    extra: list[str] = []
    nums, notes = phones([v for f in ("phone", "phone2") for _t, v in raw.get(f, [])])
    rec["phone"] = nums[0] if nums else ""
    w.extend(dict.fromkeys(n for n in notes if n[0] != "tel_bad"))
    for code, arg in notes:
        if code == "tel_bad":
            w.append((code, arg))
            extra.append(f"Telefon în fișier: {arg}")
    if nums[1:]:
        w.append(("tel_more", ""))
        extra += [f"Tel. {i}: {n}" for i, n in enumerate(nums[1:], start=2)]

    rec["birth_date"] = ""
    if raw.get("birth"):
        src = raw["birth"][0][1]
        d, year, note = parse_date(src)
        if d is not None:
            ok = prules.birth_date(d.isoformat())
            d, note = (ok, note) if ok else (None, "bd_bad")
        elif year is not None and not 1900 <= year <= _dt.date.today().year:
            year, note = None, "bd_bad"
        rec["birth_date"] = d.isoformat() if d else ""
        rec["birth_year"] = d.year if d else year
        if note:
            w.append((note, _text(src)[:30] if note == "bd_bad" else ""))

    rec["idnp"] = ""
    if raw.get("idnp"):
        src = one("idnp")
        idn = db._digits(src)
        if len(idn) == 12:
            idn = "0" + idn
            w.append(("idnp_zero", ""))
        if len(idn) != 13:
            w.append(("idnp_len", src[:30]))
        else:
            rec["idnp"] = idn
            if not prules.idnp_check_digit(idn):
                w.append(("idnp_check", ""))

    rec["gender"] = ""
    if raw.get("gender"):
        g = fold(one("gender"))
        rec["gender"] = _GENDER.get(g, _GENDER.get(g[:3], ""))
        if not rec["gender"]:
            w.append(("gender_bad", one("gender")[:20]))

    for f in ("email", "address", "insurance", "file_no"):
        rec[f] = one(f)[:200]

    rec["primary_doctor"] = rec["doc_key"] = rec["doc_src"] = ""
    src = one("doctor")
    hit = ""
    if src:
        key = rec["doc_key"] = doc_key(src)
        rec["doc_src"] = src
        hit = doctors.pick(key, src)
        if hit in doctors.names:
            rec["primary_doctor"] = doctors.names[hit]
        elif hit != NO_DOCTOR:
            w.append(("doc_unknown", src[:60]))
            extra.append(f"Medic: {src}")

    rec["visit"] = _visit(raw, hit, src, doctors, ctx or {})
    many = len(raw.get("notes", [])) > 1
    tail = [f"{title}: {_text(v)}" if many and title else _text(v) for title, v in raw.get("notes", [])]
    rec["notes_parts"] = (extra, tail)
    v = rec["visit"]
    rec["notes"], cut = compose_notes(rec, bool(v and v["problem"]))
    if cut:
        w.append(("notes_cut", ""))
    return rec


def compose_notes(rec: dict, with_visit: bool) -> tuple[str, bool]:
    """Заметки фиши: телефоны и врач, которых не прочитали, запись из файла (только если визит не
    встал), колонки заметок. (текст, обрезан ли до 500)."""
    extra, tail = rec["notes_parts"]
    v = rec.get("visit")
    parts = list(extra) + ([v["note"]] if with_visit and v else []) + list(tail)
    s = "; ".join(x for x in parts if x)
    return (s[:500], True) if len(s) > 500 else (s, False)


def _minutes(v) -> int | None:
    """Длительность из колонки: минуты числом или текстом («30», «30 min», «1h30», «1:30»), время
    Excel (`[h]:mm` 1:30 — 90 минут), доля суток числа без формата. К 5 минутам вверх; None — не
    прочитано или вне 5–240."""
    if isinstance(v, _dt.time):
        m = v.hour * 60 + v.minute
    else:
        raw = str(v).strip()
        k = fold(raw).replace(" ", "")
        if re.fullmatch(r"0?\.\d{3,}", raw):
            m = round(float(raw) * 1440)
        elif mt := re.fullmatch(r"(\d{1,2})[:.](\d{2})", raw):
            m = int(mt.group(1)) * 60 + int(mt.group(2))
        elif mt := re.fullmatch(r"(\d+)(?:min|m|minute|minut|мин|минут|минуты)?", k):
            m = int(mt.group(1))
        elif mt := re.fullmatch(r"(\d+)(?:h|ore|ora|ч|час|часа)(\d+)?(?:min|m|мин)?", k):
            m = int(mt.group(1)) * 60 + int(mt.group(2) or 0)
        elif re.fullmatch(r"0?\.\d+", raw):
            m = round(float(raw) * 1440)
        else:
            return None
    m = -(-m // 5) * 5
    return m if eng.dur_ok(m) else None


def svc_match(text: str) -> str:
    """Услуга агенды по названию из файла: то же написание без регистра и диакритики (ro, ru или
    ключ), иначе единственная, чьё название содержит написанное (от 4 знаков). "" — не узнана."""
    k = fold(text)
    if not k:
        return ""
    names = {sid: {fold(s.get("ro")), fold(s.get("ru")), fold(sid)}
             for sid, s in eng.SERVICES.items() if eng.in_agenda(sid)}
    exact = [sid for sid, ns in names.items() if k in ns]
    if exact:
        return exact[0]
    if len(k) < 4:
        return ""
    near = [sid for sid, ns in names.items() if any(k in n for n in ns if n)]
    return near[0] if len(near) == 1 else ""


_WHEN_WHY = {tabfile.NO_DATE: "v_no_date", tabfile.BAD_DATE: "v_bad_date",
             tabfile.NO_TIME: "v_no_time", tabfile.BAD_TIME: "v_bad_time",
             tabfile.BAD_RANGE: "v_bad_range"}


def _visit(raw: dict, hit: str, src: str, doctors: Doctors, ctx: dict) -> dict | None:
    """Визит из строки: когда, к кому, какая процедура, сколько. `problem` — почему не ставится
    (код `REASONS`); тогда дата уходит в заметки фиши. Час не выдумывается, врач не подставляется."""
    if not (raw.get("appt") or raw.get("appt_time")):
        return None

    def cell(f: str):
        return raw[f][0][1] if raw.get(f) else None

    day, hour = cell("appt"), cell("appt_time")
    w = tabfile.when(day, hour)
    svc_txt = _text(cell("appt_svc"))[:80]
    shown = w.day.strftime("%d.%m.%Y") if w.day else _text(day)
    if w.source or hour is not None:
        shown += " " + (w.source or _text(hour))
    shown = shown.strip()
    v = {"problem": "", "arg": "", "start": None, "minutes": None, "doctor": "",
         "svc": ctx.get("svc", ""), "comment": "", "when": shown, "doc_src": src[:60],
         "svc_src": svc_txt, "past": False, "notes_w": [],
         "note": "Programare în fișier: " + shown + (f", {svc_txt}" if svc_txt else "")}
    if w.problem:
        v["problem"] = _WHEN_WHY[w.problem]
        if w.problem == tabfile.BAD_DATE:
            v["arg"] = _text(day)[:30]
        elif w.problem in (tabfile.BAD_TIME, tabfile.BAD_RANGE):
            v["arg"] = _text(hour if hour is not None else day)[:30]
        return v
    if not src:
        v["problem"] = "v_no_doc"
    elif hit == NO_DOCTOR:
        v["problem"] = "v_doc_skip"
    elif hit not in doctors.names:
        v["problem"], v["arg"] = "v_doc_unknown", src[:40]
    if v["problem"]:
        return v
    v["doctor"] = hit
    start, span = w.slot(eng.TZ)
    v["start"] = start
    v["when"] = start.strftime("%d.%m.%Y %H:%M")
    moved = w.rounded(eng.TZ)
    if moved and start.time() != w.start:
        v["notes_w"].append(("v_rounded", f"{w.source} › {start.strftime('%H:%M')}"))
    minutes = span
    if raw.get("appt_dur"):
        got = _minutes(cell("appt_dur"))
        if got is None:
            v["notes_w"].append(("dur_bad", _text(cell("appt_dur"))[:20]))
        else:
            minutes = got
    v["minutes"] = minutes
    comment = [_text(cell("appt_note"))[:200]]
    if moved:
        comment.append(f"Fișier: {w.source}")
    if svc_txt:
        sid = svc_match(svc_txt)
        if sid:
            v["svc"] = sid
        else:
            v["notes_w"].append(("svc_other", svc_txt[:40]))
            comment.append(f"Procedură în fișier: {svc_txt}")
    v["comment"] = "; ".join(x for x in comment if x)[:300]
    v["past"] = start.date() < ctx.get("today", _dt.date.today())
    if v["past"] and not ctx.get("past", True):
        v["problem"] = "v_past_off"
    return v


def build(table: tabfile.Table, res: dict, doctors: dict) -> tuple[list, list]:
    """Строка без значений в назначенных колонках не считается: итоги, подписи;
    строка-раздел (одна ячейка на всю ширину) — тоже. `doctors` — id → имя."""
    sheet = table.sheets[res["sheet"]]
    rows = sheet.rows
    head = next((ln for rno, ln in rows if rno == res["header"]), [])
    cols = res["cols"]
    docs = Doctors(doctors, res.get("docs"))
    ctx = {"today": _dt.datetime.now(eng.TZ).date(), "past": res.get("past", True),
           "svc": res.get("svc", "")}
    recs, preview = [], []
    for rno, line in rows:
        if rno <= res["header"]:
            continue
        if len(preview) < PREVIEW_ROWS:
            preview.append({"line": rno, "cells": [_text(c) for c in line]})
        if rno in sheet.bands:
            continue
        raw: dict = {}
        for i, f in cols.items():
            if i < len(line) and line[i] is not None:
                title = _text(head[i]) if i < len(head) else ""
                raw.setdefault(f, []).append((title, line[i]))
        rec = _record(rno, raw, docs, ctx)
        if rec is not None:
            recs.append(rec)
    return recs, preview


def doctor_list(recs: list, doctors: dict, choice: dict | None = None) -> list:
    """Шаг «Medici»: каждое написание врача в файле — один раз, с тем, кого
    узнала программа, и с выбором человека. Строки без имени не в счёт."""
    docs = Doctors(doctors, choice)
    out: dict = {}
    for rec in recs:
        key = rec["doc_key"]
        if not key or rec["err"]:
            continue
        if key not in out:
            auto, cands = docs.auto(key, rec["doc_src"])
            c = docs.choice.get(key, "")
            out[key] = {"key": key, "value": rec["doc_src"][:80], "rows": 0, "auto": auto,
                        "cands": cands if not auto else [],
                        "choice": c if c == NO_DOCTOR or c in docs.names else ""}
        out[key]["rows"] += 1
    return sorted(out.values(), key=lambda x: (bool(x["auto"]), -x["rows"], x["key"]))


def name_key(name) -> str:
    """Имя для сравнения: без регистра и диакритики, порядок слов не важен."""
    return " ".join(sorted(fold(name).split()))


class _Index:
    """«Тот же человек»: IDNP, телефон и имя, имя и дата рождения, одно имя
    при пустых прочих данных с обеих сторон."""

    def __init__(self):
        self.idnp: dict = {}
        self.phone: dict = {}
        self.birth: dict = {}
        self.bare: dict = {}

    def add(self, who, name: str, phone, birth, idnp) -> None:
        nk, pk, bd = name_key(name), db.phone_key(phone), str(birth or "")[:10]
        if idnp:
            self.idnp.setdefault(idnp, who)
        if pk:
            self.phone.setdefault(pk, []).append((nk, who))
        if bd and nk:
            self.birth.setdefault((nk, bd), who)
        if nk and not (pk or bd or idnp):
            self.bare.setdefault(nk, who)

    def match(self, rec: dict):
        nk, pk = name_key(rec["name"]), db.phone_key(rec["phone"])
        if rec["idnp"] and rec["idnp"] in self.idnp:
            return "idnp", self.idnp[rec["idnp"]]
        for other, who in self.phone.get(pk, []) if pk else []:
            if other == nk:
                return "phone", who
        if rec["birth_date"] and (nk, rec["birth_date"]) in self.birth:
            return "birth", self.birth[(nk, rec["birth_date"])]
        if not (pk or rec["birth_date"] or rec["idnp"]) and nk in self.bare:
            return "bare", self.bare[nk]
        return None

    def family(self, rec: dict):
        pk = db.phone_key(rec["phone"])
        return self.phone[pk][0][1] if pk and self.phone.get(pk) else None


def analyse(recs: list, patients: list, force: list, iid: int = 0) -> None:
    """`iid` — импорт, чьи фиши отчёт называет новыми, а не «există deja»."""
    base, seen = _Index(), _Index()
    for p in patients:
        base.add(p, p["name"] or "", p["phone"], p["birth_date"], p["idnp"])
    forced = set(force)
    for rec in recs:
        rec.update(act="new", reason="", match=None, forceable=False, fill=[], mine=False)
        if rec["err"]:
            rec.update(act="bad", reason=why(rec["err"], rec["name"][:40]))
            continue
        hit = base.match(rec)
        if hit:
            by, p = hit
            # та же фиша до последнего признака — уже заведена этим же файлом
            same = (db.phone_key(p["phone"]) == db.phone_key(rec["phone"])
                    and (p["idnp"] or "") == rec["idnp"])
            if not (by == "birth" and rec["line"] in forced and not same):
                rec.update(act="exists", reason=why("ex_" + by, p["name"]),
                           match={"id": p["id"], "name": p["name"]},
                           forceable=by == "birth" and not same,
                           mine=bool(iid) and p.get("import_id") == iid)
                if p.get("archived"):
                    rec["notes_w"].append(("archived", ""))
                if by != "bare":
                    rec["fill"] = [f for f in db.IMPORT_FILL if rec.get(f) and not p.get(f)]
                continue
        hit = seen.match(rec)
        if hit and not (hit[0] == "birth" and rec["line"] in forced):
            rec.update(act="dup", reason=why("dup_" + hit[0], hit[1]),
                       forceable=hit[0] == "birth", root=hit[1])
            continue
        kin = base.family(rec)
        if kin is not None or (kin_line := seen.family(rec)) is not None:
            rec["notes_w"].append(
                ("family", kin["name"] if kin is not None else f"rândul {kin_line}"))
        seen.add(rec["line"], rec["name"], rec["phone"], rec["birth_date"], rec["idnp"])


def group_of(rec: dict) -> str:
    if rec["act"] == "new" and rec["notes_w"]:
        return "noted"
    return rec["act"]


def row_view(rec: dict) -> dict:
    birth = (_dt.date.fromisoformat(rec["birth_date"]).strftime("%d.%m.%Y")
             if rec["birth_date"] else str(rec["birth_year"] or ""))
    return {"line": rec["line"], "name": rec["name"], "phone": rec["phone"], "birth": birth,
            "idnp": rec["idnp"], "reason": rec["reason"],
            "notes": [why(c, a) for c, a in rec["notes_w"]],
            "match": rec["match"], "forceable": rec["forceable"],
            "fill": [FILL_LABEL[f] for f in rec["fill"]]}


def summary(recs: list) -> tuple[dict, list]:
    counts = {g: 0 for g, _l in GROUPS}
    rows = {g: [] for g, _l in GROUPS}
    for rec in recs:
        g = group_of(rec)
        counts[g] += 1
        if len(rows[g]) < GROUP_CAP:
            rows[g].append(row_view(rec))
    counts.update(rows=len(recs), create=counts["new"] + counts["noted"],
                  fill=sum(1 for r in recs if r["act"] == "exists" and r["fill"]),
                  family=sum(1 for r in recs if r["act"] == "new"
                             and any(c == "family" for c, _a in r["notes_w"])))
    groups = [{"id": g, "label": label, "count": counts[g], "rows": rows[g],
               "more": counts[g] - len(rows[g])} for g, label in GROUPS]
    return counts, groups


def report_rows(recs: list, visits: bool = False) -> list:
    """Строки книги «что не вошло»: всё, кроме вошедшего без единой пометки; с визитами — и строка,
    чей визит не встал или встал с пометкой. `visits` — колонка «Programare» в конце."""
    out = []
    for rec in recs:
        g = group_of(rec)
        if rec["act"] == "exists" and rec["mine"]:
            g = "noted" if rec["notes_w"] else "new"
        vs = rec.get("vstate", "")
        v_noted = vs == "v_no" or bool(rec.get("vwhy")) or bool(rec.get("visit") and rec["visit"]["notes_w"])
        if g == "new" and not (visits and v_noted):
            continue
        v = row_view(rec)
        row = [v["line"], v["name"], v["phone"], v["birth"], v["idnp"], RESULT[g],
               "; ".join(([v["reason"]] if v["reason"] and g != "noted" else []) + v["notes"])]
        if visits:
            vv = visit_view(rec) if vs else None
            row.append("; ".join([visit_result(rec)] + (vv["notes"] if vv else [])) if vs else "")
        out.append(row)
    return out


def _who(rec: dict):
    """Чья фиша получит визит строки: заведённая строкой (`("l", строка)`) или найденная (`("p", id)`).
    Дубль строки файла — фиша той строки, которую он повторяет."""
    if rec["act"] == "exists":
        return ("p", rec["match"]["id"])
    if rec["act"] == "dup":
        return ("l", rec.get("root"))
    return ("l", rec["line"])


def _end(v: dict):
    return v["start"] + _dt.timedelta(minutes=v["minutes"] or eng.svc_duration(v["svc"]))


def _set_visit(rec: dict, state: str, code: str = "", arg="") -> None:
    rec["vstate"], rec["vwhy"] = state, (why(code, arg) if code else "")


def visit_outcome(rec: dict, code: str) -> None:
    """Ответ `book.probe` / `book.book_visit` → группа и слово строки."""
    v = rec["visit"]
    if code in book.OK_CODES:
        _set_visit(rec, "v_past" if v["past"] else "v_new", "v_room" if code == "room_busy" else "")
    else:
        _set_visit(rec, "v_no", _BOOK_WHY.get(code, "v_bad"))


def visit_ready(rec: dict) -> bool:
    """Строку можно ставить визитом: фиша войдёт или найдена, дата, час, врач и процедура есть."""
    v = rec.get("visit")
    return bool(v) and not v["problem"] and rec["act"] != "bad" and bool(v["svc"])


async def plan_visits(recs: list, booked: list | None = None) -> None:
    """Предпросмотр визитов: что встанет, что нет и почему. Занятость в базе — `book.probe` (на
    сухую, правду говорит запись); пересечения строк файла между собой — здесь, в памяти: раньше в
    файле — первым, как и при записи. `booked` — визиты этого импорта (отчёт после записи):
    такой визит — «поставлен», а не «у пациента уже есть запись»."""
    mine = {(r["patient_id"], r["starts_at"].timestamp()) for r in booked or []}
    by_doc: dict = {}
    by_who: dict = {}
    for rec in recs:
        v = rec.get("visit")
        rec["vstate"], rec["vwhy"] = ("", "")
        if not v:
            continue
        if rec["act"] == "bad":
            _set_visit(rec, "v_no", "v_row_bad")
            continue
        if v["problem"]:
            _set_visit(rec, "v_no", v["problem"], v["arg"])
            continue
        if not v["svc"]:
            _set_visit(rec, "v_no", "v_bad")
            continue
        start, end = v["start"], _end(v)
        who = _who(rec)
        pid = who[1] if who[0] == "p" else None
        if pid is not None and (pid, start.timestamp()) in mine:
            _set_visit(rec, "v_past" if v["past"] else "v_new")
        else:
            await _plan_one(rec, v, who, pid, start, end, by_doc, by_who)
            if rec["vstate"] == "v_no":
                continue
        by_doc.setdefault(v["doctor"], []).append((start, end, rec["line"]))
        by_who.setdefault(who, []).append((start, end, v["doctor"], rec["line"]))


async def _plan_one(rec: dict, v: dict, who, pid, start, end, by_doc: dict, by_who: dict) -> None:
    """Одна строка предпросмотра: сперва пересечения строк файла, потом база (`book.probe`)."""
    clash = next((ln for s0, e0, doc, ln in by_who.get(who, [])
                  if s0 == start or (doc == v["doctor"] and s0 < end and start < e0)), None)
    if clash is not None:
        _set_visit(rec, "v_no", "v_dup_file", clash)
        return
    busy = [ln for s0, e0, ln in by_doc.get(v["doctor"], []) if s0 < end and start < e0]
    if len(busy) >= max(1, len(eng.doctor_rooms(v["doctor"]))):
        _set_visit(rec, "v_no", "v_busy_file", busy[0])
        return
    if pid is not None and await db.import_visit_exists(pid, start):
        _set_visit(rec, "v_no", "v_exists")
        return
    visit_outcome(rec, await book.probe(pid, v["doctor"], start, v["svc"], minutes=v["minutes"],
                                        done=v["past"]))


def visit_view(rec: dict) -> dict:
    v = rec["visit"]
    notes = [why(c, a) for c, a in v["notes_w"]]
    if rec["act"] == "dup" and rec["vstate"] != "v_no":
        notes.insert(0, why("v_to_row", rec.get("root")))
    elif rec["act"] == "exists" and rec["vstate"] != "v_no" and not rec.get("mine"):
        notes.insert(0, why("v_to_card", rec["match"]["name"]))
    doctor = eng.DOCTORS.get(v["doctor"], "") if v["doctor"] else v["doc_src"]
    service = eng.SERVICES.get(v["svc"], {}).get("ro", "") if v["doctor"] else v["svc_src"]
    return {"line": rec["line"], "name": rec["name"], "when": v["when"], "doctor": doctor,
            "service": service, "reason": rec["vwhy"], "notes": notes,
            "patient": rec["match"]["id"] if rec["act"] == "exists" else None}


def visit_summary(recs: list) -> tuple[dict, list]:
    counts = {g: 0 for g, _l in VISIT_GROUPS}
    rows = {g: [] for g, _l in VISIT_GROUPS}
    for rec in recs:
        g = rec.get("vstate")
        if not g:
            continue
        counts[g] += 1
        if len(rows[g]) < GROUP_CAP:
            rows[g].append(visit_view(rec))
    counts["rows"] = sum(counts[g] for g, _l in VISIT_GROUPS)
    groups = [{"id": g, "label": label, "count": counts[g], "rows": rows[g],
               "more": counts[g] - len(rows[g])} for g, label in VISIT_GROUPS]
    return counts, groups


def visit_result(rec: dict) -> str:
    """Колонка «Programare» книги-отчёта: что стало с визитом строки."""
    g = rec.get("vstate")
    if not g:
        return ""
    v = rec["visit"]
    head = f"{VISIT_RESULT[g]}: {v['when']}"
    if g != "v_no" and v["doctor"]:
        head += f", {eng.DOCTORS.get(v['doctor'], '')}"
    return head + (f" — {rec['vwhy']}" if rec["vwhy"] else "")


async def create(rec: dict, iid: int, file_name: str) -> int:
    """Путём «Pacient nou». Занятый ключ телефона — семейный номер: фиша
    получает свой ключ, иначе переписала бы чужую."""
    digits = db._digits(rec["phone"])
    key = db.manual_key(digits)
    if digits and await db.patient_id_by_key(key) is not None:
        key = db.manual_key("")
    pid = await db.create_patient(key, rec["name"], rec["phone"], rec["birth_year"],
                                  origin="import", origin_arg=file_name[:80])
    data = {f: rec.get(f) or None for f in db.PATIENT_FIELDS}
    await db.update_patient(pid, data, log=False)
    await db.import_mark(pid, iid)
    return pid


async def fill(rec: dict) -> bool:
    """Строка летописи называет, какие поля дописаны."""
    done = await db.fill_patient_blanks(rec["match"]["id"], rec)
    if done:
        await db.log_event(rec["match"]["id"], "import_fill",
                           "Fișă completată prin import: "
                           + ", ".join(FILL_LABEL[f] for f in done))
    return bool(done)
