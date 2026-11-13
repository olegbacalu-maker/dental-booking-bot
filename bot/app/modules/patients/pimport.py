"""Импорт пациентов из таблицы. Один разбор отвечает и проверке, и каждой
порции записи, поэтому между запросами ничего не хранится."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re

from ... import db
from ...core import tabfile
from . import profile_rules as prules

BATCH = 200
GROUP_CAP = 300
PREVIEW_ROWS = 8
HEADER_SCAN = 25

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
    ("doctor", "Medic curant"),
    ("file_no", "Nr. dosar"),
    ("notes", "Notițe"),
    ("appt", "Data programării (în notițe)"),
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
             "дата записи", "запись", "appointment"],
    "birth": ["data nasterii", "data nast", "nasterii", "nascut", "data de nastere",
              "anul nasterii", "дата рождения", "рождения", "д р", "др", "родился",
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
    "doctor": ["medic", "medicul", "medic curant", "doctor", "врач", "лечащий врач"],
    "file_no": ["nr fisa", "nr fisei", "nr dosar", "numar fisa", "fisa", "номер карты", "карта",
                "file no"],
    "notes": ["note", "notite", "observatii", "obs", "comentariu", "comentarii", "mentiuni",
              "примечание", "примечания", "заметки", "комментарий", "notes", "comment"],
}
# узнаются, чтобы не импортировать: счётчики и то, что программа считает сама
_SKIP = {"id", "nr", "nr crt", "n", "no", "п п", "n п п", "varsta", "возраст", "age", "sold",
         "sold mdl", "status", "canal", "vizite", "ultima vizita", "urmatoarea vizita",
         "inregistrat"}

# экран печатает эти слова как есть, своего словаря у него нет
REASONS = {
    "no_name": "lipsește numele",
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
}
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
           "fill": False, "force": []}
    try:
        out["sheet"] = int(o.get("sheet") or 0)
        if o.get("header") is not None:
            out["header"] = int(o["header"])
        if o.get("cols") is not None:
            out["cols"] = {int(k): str(v) for k, v in dict(o["cols"]).items() if v}
        out["force"] = sorted({int(x) for x in (o.get("force") or [])})
    except (TypeError, ValueError):
        return None
    if out["sheet"] < 0 or (out["header"] or 0) < 0:
        return None
    if out["cols"] is not None and (set(out["cols"].values()) - FIELD_IDS
                                    or any(k < 0 for k in out["cols"])):
        return None
    out["enc"] = o.get("enc") if o.get("enc") in tabfile.ENCODINGS else ""
    out["delim"] = o.get("delim") if o.get("delim") in tabfile.DELIMITERS else ""
    out["fill"] = o.get("fill") is True
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
            "force": opts["force"]}


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
    if isinstance(v, _dt.date):
        return v.strftime("%d.%m.%Y")
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _name(parts: list) -> tuple[str, bool]:
    s = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip(" ,.;")
    recased = False
    if s and (s.isupper() or s.islower()):
        s = re.sub(r"[^\W\d_]+", lambda m: m.group().capitalize(), s)
        recased = True
    return s[:120], recased


def phones(values: list) -> tuple[list[str], list[tuple]]:
    """Номера в виде клиники (`069123456`); два столбца с одним номером — один номер."""
    out, notes, seen = [], [], set()
    for raw in values:
        for part in re.split(r"[;,/\n]|\s{2,}|(?<=\d)\s+(?=\+|0\d{2}\D?\d)", str(raw)):
            d = db._digits(part)
            if not d:
                continue
            key = db.phone_key(d)
            if len(key) == 9 and key[0] == "0":
                num = key
                if len(d) == 8:
                    notes.append(("tel_zero", ""))
            elif 6 <= len(d) <= 15:
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


_GENDER = {"m": "m", "f": "f", "м": "m", "ж": "f", "b": "m", "masculin": "m", "feminin": "f",
           "barbat": "m", "femeie": "f", "муж": "m", "жен": "f", "мужской": "m",
           "женский": "f", "male": "m", "female": "f"}


def _record(line: int, raw: dict, doctors: dict) -> dict | None:
    """Строка файла как будущая фиша. None — в назначенных колонках пусто."""
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

    rec["primary_doctor"] = ""
    if raw.get("doctor"):
        src = one("doctor")
        hit = doctors.get(fold(src))
        if hit:
            rec["primary_doctor"] = hit
        else:
            w.append(("doc_unknown", src[:60]))
            extra.append(f"Medic: {src}")

    for _t, v in raw.get("appt", []):
        d, _y, _n = parse_date(v)
        extra.append(f"Programare în fișier: {d.strftime('%d.%m.%Y') if d else _text(v)}")
    many = len(raw.get("notes", [])) > 1
    for title, v in raw.get("notes", []):
        extra.append(f"{title}: {_text(v)}" if many and title else _text(v))
    notes_s = "; ".join(x for x in extra if x)
    if len(notes_s) > 500:
        notes_s = notes_s[:500]
        w.append(("notes_cut", ""))
    rec["notes"] = notes_s
    return rec


def build(table: tabfile.Table, res: dict, doctors: list) -> tuple[list, list]:
    """Строка без значений в назначенных колонках не считается: итоги, подписи."""
    rows = table.sheets[res["sheet"]].rows
    head = next((ln for rno, ln in rows if rno == res["header"]), [])
    cols = res["cols"]
    by_fold = {fold(d): d for d in doctors}
    recs, preview = [], []
    for rno, line in rows:
        if rno <= res["header"]:
            continue
        if len(preview) < PREVIEW_ROWS:
            preview.append({"line": rno, "cells": [_text(c) for c in line]})
        raw: dict = {}
        for i, f in cols.items():
            if i < len(line) and line[i] is not None:
                title = _text(head[i]) if i < len(head) else ""
                raw.setdefault(f, []).append((title, line[i]))
        rec = _record(rno, raw, by_fold)
        if rec is not None:
            recs.append(rec)
    return recs, preview


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
            rec.update(act="bad", reason=why(rec["err"]))
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
                       forceable=hit[0] == "birth")
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


def report_rows(recs: list) -> list:
    """Строки книги «что не вошло»: всё, кроме вошедшего без единой пометки."""
    out = []
    for rec in recs:
        g = group_of(rec)
        if rec["act"] == "exists" and rec["mine"]:
            g = "noted" if rec["notes_w"] else "new"
        if g == "new":
            continue
        v = row_view(rec)
        out.append([v["line"], v["name"], v["phone"], v["birth"], v["idnp"], RESULT[g],
                    "; ".join(([v["reason"]] if v["reason"] and g != "noted" else [])
                              + v["notes"])])
    return out


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
