"""Засев «Laborator», «Stoc» и «Registre» демо-клиники — дверью клиники.

`seed.py` наполняет базу до старта программы прямым SQL (визиты, фиши, планы).
Эти три раздела сеются иначе: шлюз зовёт `seed()` ПОСЛЕ старта слота и входа
(`gate.reset`), и каждая запись идёт через JSON API программы, как её внесла
бы регистратура. Причина — у разделов своя логика записи, которую SQL обошёл
бы молча: шапка заказа лаборатории — пересчёт истории событий, срок — в
рабочих днях лаборатории; остаток склада — сумма журнала движений, «Comandat»
снимает закрытие накладной; регистры подписывает сервер. Копия этих правил в
засеве разошлась бы с программой при первой правке.

Даты — от «сегодня» самой программы (`/api/lab` › today): копия живёт 30
минут, и заказ «просрочен» в любой день, когда её открыли.

Исключение одно — прошлые дни регистров 257/e и 501/e (и уборки старше
«ieri»): программа пишет цикл, лампу и подпись только «сейчас» (момент
подписи — требование регистра), двери в прошлое у неё нет и быть не должно.
Эти строки ложатся в базу слота напрямую, колонками `db/registre._SAN_COLS`,
после того как каталог завела сама программа. Сторож колонок —
`tests/test_demo.py::suite_seed`.

Только стандартная библиотека: шлюз локально живёт в своём venv, прогон — в
окружении сборки.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Chisinau")


class SeedError(RuntimeError):
    pass


class _Api:
    def __init__(self, base: str, cookie: str) -> None:
        self.base, self.cookie = base.rstrip("/"), cookie

    def __call__(self, path: str, body: dict | None = None) -> dict:
        rq = urllib.request.Request(
            self.base + path, method="GET" if body is None else "POST",
            data=None if body is None else json.dumps(body).encode(),
            headers={"Cookie": "admin_auth=" + self.cookie, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=30) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise SeedError(f"{path}: {e.code} {e.read().decode('utf-8', 'replace')[:300]}") from None
        if not d.get("ok", True):
            raise SeedError(f"{path}: {str(d)[:300]}")
        return d.get("data") or {}


# --- Laborator -----------------------------------------------------------------
# лаборатории выдуманные; срок — рабочие дни
LABS = {
    "nord": {"name": "Laborator Ceramica Nord", "days": 7, "phone": "022 000 101"},
    "zircon": {"name": "Atelier Zircon", "days": 5, "phone": "022 000 202"},
    "plus": {"name": "Laborator Proteza Plus", "days": 10, "phone": "022 000 303"},
}

# (пациент: имя витринного или номер в остальных, лаборатория, врач, отправлен
#  дней назад, шаги [(статус, дней назад)], срочно, оттиск, позиции)
# позиция с "plan" привязывается к позиции плана пациента с этим текстом
ORDERS = [
    # просрочен: 10 рабочих дней прошли, работы нет
    ("Vasile Lungu", "plus", "d4", 18, [], True, "amprenta",
     [{"work": "Coroană", "material": "Metalo-ceramică", "shade": "A3", "teeth": [26], "price_bani": 320000,
       "plan": "Coroană metalo-ceramică"}]),
    # готов к выдаче в лаборатории
    ("Maria Popescu", "nord", "d4", 9, [("gata", 1)], False, "scanare",
     [{"work": "Coroană", "material": "Zirconiu", "shade": "A2", "teeth": [36], "price_bani": 180000,
       "plan": "Coroană zirconiu"}]),
    (3, "zircon", "d2", 7, [("gata", 2)], False, "scanare",
     [{"work": "Coroană pe implant", "material": "Zirconiu", "shade": "A3", "teeth": [46], "price_bani": 220000}]),
    # в работе, срок впереди
    ("Elena Rotaru", "nord", "d3", 2, [], False, "amprenta",
     [{"work": "Gutieră de albire", "material": "", "shade": "", "teeth": [], "price_bani": 60000,
       "plan": "Albire dentară"}]),
    (5, "zircon", "d2", 1, [], True, "scanare",
     [{"work": "Coroane provizorii", "material": "PMMA", "shade": "A2", "teeth": [14, 15], "price_bani": 80000}]),
    (8, "nord", "d3", 0, [], False, "amprenta",
     [{"work": "Gutieră de protecție", "material": "", "shade": "", "teeth": [], "price_bani": 70000}]),
    # в клинике: принят, ждёт примерки; на примерке
    (11, "zircon", "d2", 12, [("gata", 6), ("primit", 5)], False, "scanare",
     [{"work": "Bont personalizat", "material": "Titan", "shade": "", "teeth": [36], "price_bani": 150000},
      {"work": "Coroană pe implant", "material": "Zirconiu", "shade": "A3", "teeth": [36], "price_bani": 220000}]),
    (14, "plus", "d4", 24, [("gata", 10), ("primit", 9), ("proba", 7)], False, "amprenta",
     [{"work": "Proteză parțială scheletată", "material": "Crom-cobalt", "shade": "A3", "teeth": [35, 36, 37],
       "price_bani": 450000}]),
    # закрыт
    ("Sergiu Balan", "nord", "d4", 32, [("gata", 25), ("primit", 24), ("finalizat", 23)], False, "scanare",
     [{"work": "Coroane", "material": "Disilicat de litiu", "shade": "A1", "teeth": [11, 12], "price_bani": 360000}]),
]


def _plan_item(call: _Api, pid: int, text: str) -> int | None:
    for it in (call(f"/api/patients/{pid}").get("plan") or {}).get("items") or []:
        if text in (it.get("procedure") or ""):
            return it["id"]
    return None


def seed_lab(call: _Api, td: date, pid_of) -> int:
    ids = {k: call("/api/settings/lab/item", v)["id"] for k, v in LABS.items()}
    for who, lab, doc, sent, steps, urgent, imp, items in ORDERS:
        pid = pid_of(who)
        rows = []
        for it in items:
            it = dict(it)
            if "plan" in it:
                it["plan_item_id"] = _plan_item(call, pid, it.pop("plan"))
            rows.append(it)
        o = call("/api/lab/order", {"pid": pid, "lab_id": ids[lab], "doctor_id": doc,
                                    "sent_on": (td - timedelta(days=sent)).isoformat(),
                                    "urgent": urgent, "impression": imp, "items": rows})
        for to, ago in steps:
            call(f"/api/lab/order/{o['id']}/step", {"to": to, "on_date": (td - timedelta(days=ago)).isoformat()})
    return len(ORDERS)


# --- Stoc ------------------------------------------------------------------------
SUP = {"centru": "Depozit Dental Centru", "sud": "MedSupply Sud"}

# имя: (единица, категория, упаковка, в упаковке, порог — тысячные единицы, дорогой, срок, поставщик)
ITEMS = {
    "Articaină 4% 1:100 000, carpule": ("buc", "Anestezice", "cutie 50", 50000, 25000, True, True, "centru"),
    "Lidocaină spray 10%": ("ml", "Anestezice", "flacon 38 ml", 38000, 38000, False, True, "centru"),
    "Compozit nanohibrid A2": ("g", "Compozite și adezive", "seringă 4 g", 4000, 12000, True, True, "centru"),
    "Compozit nanohibrid A3": ("g", "Compozite și adezive", "seringă 4 g", 4000, 12000, True, True, "centru"),
    "Compozit fluid A2": ("g", "Compozite și adezive", "seringă 2 g", 2000, 4000, False, True, "centru"),
    "Adeziv universal": ("ml", "Compozite și adezive", "flacon 5 ml", 5000, 5000, True, True, "centru"),
    "Gel de gravare 37%": ("ml", "Compozite și adezive", "seringă 3 ml", 3000, 6000, False, True, "centru"),
    "Ciment ionomer de sticlă": ("g", "Cimenturi", "set 15 g", 15000, 15000, False, True, "sud"),
    "Ace K-file 25 mm": ("buc", "Endodonție", "blister 6", 6000, 18000, False, False, "sud"),
    "Hipoclorit de sodiu 3%": ("ml", "Endodonție", "flacon 500 ml", 500000, 250000, False, True, "sud"),
    "Conuri de gutapercă 0.04": ("buc", "Endodonție", "cutie 60", 60000, 30000, False, False, "sud"),
    "Silicon de adiție putty": ("g", "Amprentare", "set 2×300 g", 600000, 600000, True, True, "sud"),
    "Alginat cu priză rapidă": ("g", "Amprentare", "pachet 500 g", 500000, 500000, False, True, "sud"),
    "Implant dentar 4.0×10 mm": ("buc", "Implantologie", "buc", 1000, 3000, True, True, "centru"),
    "Pastă profilactică": ("g", "Profilaxie", "tub 100 g", 100000, 100000, False, True, "centru"),
    "Pulbere air-flow": ("g", "Profilaxie", "flacon 300 g", 300000, 300000, False, True, "centru"),
    "Dezinfectant suprafețe": ("ml", "Dezinfecție", "flacon 1 l", 1000000, 1000000, False, True, "sud"),
    "Mănuși nitril M": ("cutie", "Consumabile diverse", "cutie 100", 1000, 5000, False, False, "sud"),
    "Măști chirurgicale": ("cutie", "Consumabile diverse", "cutie 50", 1000, 3000, False, False, "sud"),
}

# накладные: (поставщик, №, дней назад, [(материал, упаковок, сумма MDL, лот, годен через N дней)])
# «скоро истекает» — в пределах 60 дней (`core/stock.EXP_DAYS`): здесь только адгезив
INVOICES = [
    ("centru", "DDC 4417", 27, [
        ("Articaină 4% 1:100 000, carpule", 4, 2800, "A2391", 290),
        ("Lidocaină spray 10%", 2, 640, "L0712", 140),
        ("Compozit nanohibrid A2", 6, 2700, "C8810", 200),
        ("Compozit nanohibrid A3", 4, 1800, "C8812", 200),
        ("Compozit fluid A2", 4, 1080, "F2204", 110),
        ("Adeziv universal", 2, 1500, "B5530", 24),
        ("Gel de gravare 37%", 4, 360, "G1190", 230),
        ("Implant dentar 4.0×10 mm", 6, 9000, "IM-2207", 1350),
        ("Pastă profilactică", 2, 320, "P0451", 320),
        ("Pulbere air-flow", 3, 780, "AF731", 165),
    ]),
    ("sud", "MS-10233", 10, [
        ("Ciment ionomer de sticlă", 2, 900, "GI204", 350),
        ("Ace K-file 25 mm", 4, 520, "", None),
        ("Hipoclorit de sodiu 3%", 2, 170, "H3312", 380),
        ("Conuri de gutapercă 0.04", 2, 380, "", None),
        ("Silicon de adiție putty", 1, 1450, "S7720", 77),
        ("Alginat cu priză rapidă", 3, 390, "AL559", 95),
        ("Dezinfectant suprafețe", 4, 560, "D1180", 900),
        ("Mănuși nitril M", 12, 1680, "", None),
        ("Măști chirurgicale", 6, 270, "", None),
    ]),
]

# расход: (материал, единиц, причина, пациент — имя витринного, номер остальных или None)
# итог: «Compozit nanohibrid A3» и «Silicon de adiție putty» — ниже минимума,
# путти ещё и заказан у поставщика
OUTS = [
    ("Articaină 4% 1:100 000, carpule", 42, "pacient", 2), ("Articaină 4% 1:100 000, carpule", 96, "pacient", 4),
    ("Compozit nanohibrid A3", 13, "pacient", 7), ("Compozit fluid A2", 3, "pacient", 6),
    ("Adeziv universal", 4.2, "pacient", 6), ("Gel de gravare 37%", 5, "pacient", 7),
    ("Ciment ionomer de sticlă", 18, "pacient", "Vasile Lungu"), ("Ace K-file 25 mm", 11, "pacient", "Maria Popescu"),
    ("Hipoclorit de sodiu 3%", 340, "pacient", "Maria Popescu"), ("Conuri de gutapercă 0.04", 24, "pacient", 9),
    ("Silicon de adiție putty", 310, "pacient", "Vasile Lungu"),
    ("Compozit nanohibrid A2", 9.5, "pacient", "Dumitru Moraru"), ("Articaină 4% 1:100 000, carpule", 2, "pacient", 10),
    ("Alginat cu priză rapidă", 620, "pacient", "Elena Rotaru"), ("Implant dentar 4.0×10 mm", 2, "pacient", 11),
    ("Implant dentar 4.0×10 mm", 1, "pacient", "Sergiu Balan"), ("Pastă profilactică", 92, "pacient", 12),
    ("Pulbere air-flow", 240, "pacient", "Natalia Guțu"), ("Mănuși nitril M", 7, "deschis", None),
    ("Măști chirurgicale", 3, "deschis", None), ("Lidocaină spray 10%", 22, "pacient", 13),
    ("Dezinfectant suprafețe", 1400, "deschis", None),
]


def seed_stock(call: _Api, td: date, pid_of) -> int:
    sup = {k: call("/api/stock/supplier", {"name": v, "phone": "022 000 4%02d" % i})["id"]
           for i, (k, v) in enumerate(SUP.items())}
    ids = {}
    for name, (unit, cat, pack, per, mn, costly, exp, s) in ITEMS.items():
        ids[name] = call("/api/stock/item", {"name": name, "unit": unit, "cat": cat, "pack_name": pack,
                                             "pack_qty_milli": per, "min_milli": mn, "costly": costly,
                                             "track_expiry": exp, "supplier_id": sup[s]})["id"]
    for s, nr, ago, lines in INVOICES:
        body = {"kind": "factura", "nr": nr, "doc_date": (td - timedelta(days=ago)).isoformat(),
                "supplier_id": sup[s], "lines": [
                    {"item_id": ids[n], "qty_milli": packs * ITEMS[n][3], "cost_bani": mdl * 100, "lot": lot,
                     "exp_on": (td + timedelta(days=ex)).isoformat() if ex is not None else None}
                    for n, packs, mdl, lot, ex in lines]}
        did = call("/api/stock/doc", body)["id"]
        call(f"/api/stock/doc/{did}/close", {})
    for name, qty, reason, who in OUTS:
        body = {"item_id": ids[name], "qty_milli": int(round(qty * 1000)), "reason": reason}
        if who is not None:
            body["pid"] = pid_of(who)
        call("/api/stock/out", body)
    call("/api/stock/order", {"ids": [ids["Silicon de adiție putty"]]})
    return len(ids)


# --- Registre sanitare -------------------------------------------------------------
NAT, ELE, ION = "Natalia Lungu", "Dr. Elena Rusu", "Dr. Ion Munteanu"   # врачи — из demo/clinic.json
ACN, GPN = "Autoclav clasa B nr. 23-11845", "Etuvă GP-40 nr. 0412"
SOL = "Soluție cu clor activ 0,1 % · 60 min"

CATALOG = [
    {"kind": "ster", "name": "Autoclav clasa B", "nr": "23-11845", "room": "Sala de sterilizare",
     "data": {"type": "abur", "programs": [
         {"label": "Universal 134 °C", "temp": "134", "pressure": "2,1", "min": 5},
         {"label": "Delicat 121 °C", "temp": "121", "pressure": "1,1", "min": 20}]}},
    {"kind": "ster", "name": "Etuvă GP-40", "nr": "0412", "room": "Sala de sterilizare",
     "data": {"type": "aer", "programs": [{"label": "Aer 180 °C", "temp": "180", "pressure": "", "min": 60}]}},
    {"kind": "lamp", "name": "OBN-150 ecranată", "nr": "2", "room": "Cabinet 1",
     "data": {"m3": 45, "hours": 8000, "base": 3120, "since": "2025-09-01", "screened": True}},
    {"kind": "lamp", "name": "OBN-150 ecranată", "nr": "3", "room": "Cabinet 2",
     "data": {"m3": 42, "hours": 8000, "base": 1240, "since": "2026-01-12", "screened": True}},
    # на исходе: остаток ≤ 50 ч (`core/registre.LOW_MIN`)
    {"kind": "lamp", "name": "OBN-75", "nr": "4", "room": "Sala de sterilizare",
     "data": {"m3": 18, "hours": 8000, "base": 7968, "since": "2025-03-20", "screened": False}},
    *({"kind": "room", "name": n, "data": {"every": 7}} for n in ("Cabinet 1", "Cabinet 2", "Sala de sterilizare")),
    {"kind": "room", "name": "Recepție și hol", "data": {"every": 30}},
    {"kind": "staff", "name": NAT, "data": {"func": "asistentă medicală", "sup": False}},
    {"kind": "staff", "name": ELE, "data": {"func": "medic, director", "sup": True}},
    {"kind": "staff", "name": ION, "data": {"func": "medic", "sup": True}},
    *({"kind": "solution", "name": n} for n in (SOL, "Soluție de peroxid de hidrogen 3 % · 60 min")),
]


def _arts(*x) -> str:
    return json.dumps([{"name": n, "qty": q, "pack": k} for n, q, k in x], ensure_ascii=False)


def seed_registre(call: _Api, td: date, db_path) -> dict:
    call("/api/settings/registre")          # стартовые предметы и упаковки кладёт сама программа
    for it in CATALOG:
        call("/api/settings/registre/item", it)
    cat = call("/api/settings/registre")["items"]
    ids = {(i["kind"], i["name"], i.get("nr", "")): i["id"] for k in cat.values() for i in k}
    ac, gp = ids[("ster", "Autoclav clasa B", "23-11845")], ids[("ster", "Etuvă GP-40", "0412")]
    l1, l2 = ids[("lamp", "OBN-150 ecranată", "2")], ids[("lamp", "OBN-150 ecranată", "3")]
    l3 = ids[("lamp", "OBN-75", "4")]
    room = {i["name"]: i["id"] for i in cat["room"]}

    # сегодня и вчера — дверью: уборка «ieri» с проверкой, уборка «azi» ждёт проверки
    call("/api/registre/502", {"room_id": room["Cabinet 1"], "day": "ieri", "solution": SOL, "doer": NAT})
    c1 = next(r for r in call("/api/registre")["waiting"] if r.get("room") == "Cabinet 1")
    call(f"/api/registre/502/{c1['id']}/sup", {"who": ELE})
    call("/api/registre/502", {"room_id": room["Sala de sterilizare"], "day": "azi", "solution": SOL, "doer": NAT})

    def at(days, hh, mm) -> str:
        d = td - timedelta(days=days)
        return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ).astimezone(timezone.utc).isoformat()

    def day(days) -> str:
        return (td - timedelta(days=days)).isoformat()

    con = sqlite3.connect(str(db_path), timeout=15)
    try:
        # «кто внёс» — учётка, под которой вошёл шлюз: та же, что у строк дверью выше
        actor, actor_id = con.execute("SELECT actor, actor_id FROM san_cleanings ORDER BY id LIMIT 1").fetchone()
        cycles = [  # (стерилизатор, название, программа, давл., темп., загрузка, начало, конец, хим, терм, био, био в)
            (ac, ACN, "Universal 134 °C", "2,1", "134",
             _arts(("Instrumentar stomatologic", 12, "Pungă"), ("Freze și pile", 2, "Casetă")),
             at(6, 8, 40), at(6, 9, 25), "ok", "ok", "ok", at(4, 8, 5)),
            (gp, GPN, "Aer 180 °C", "", "180", _arts(("Tăvițe și pense", 6, "Bix")),
             at(6, 13, 10), at(6, 14, 40), "ok", "ok", "", None),
            (ac, ACN, "Universal 134 °C", "2,1", "134",
             _arts(("Instrumentar stomatologic", 15, "Pungă"), ("Piese de mână", 4, "Pungă")),
             at(4, 8, 35), at(4, 9, 20), "ok", "ok", "", None),
            (ac, ACN, "Delicat 121 °C", "1,1", "121", _arts(("Material textil", 3, "Bix")),
             at(3, 9, 5), at(3, 10, 5), "ok", "ok", "", None),
            # биотест заложен вчера — результат ещё ждут
            (ac, ACN, "Universal 134 °C", "2,1", "134",
             _arts(("Instrumentar stomatologic", 18, "Pungă"), ("Freze și pile", 3, "Casetă")),
             at(1, 8, 30), at(1, 9, 15), "ok", "ok", "wait", None),
        ]
        for ster, name, prog, pr, tmp, arts, st, en, chem, term, bio, bio_at in cycles:
            con.execute("INSERT INTO san_cycles(ster_id, ster, program, pressure, temp, arts, started_at, ended_at, "
                        "chem, term, bio, actor, actor_id, end_actor, bio_actor, bio_at, doer, end_doer, created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ster, name, prog, pr, tmp, arts, st, en, chem, term, bio, actor, actor_id, actor,
                         actor if bio_at else "", bio_at, NAT, NAT, st))
        for name, ago, sup, sup_ago in (("Recepție și hol", 20, ELE, 19), ("Cabinet 2", 6, ION, 5)):
            con.execute("INSERT INTO san_cleanings(room_id, room, plan_date, done_date, solution, actor, actor_id, "
                        "doer, sup_actor, sup_id, sup_by, sup_at, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (room[name], name, day(ago), day(ago), SOL, actor, actor_id, NAT, sup, actor_id, actor,
                         at(sup_ago, 8, 20), at(ago, 19, 10)))
        for lid, lamp, rm, on, rest in ((l1, "OBN-150 ecranată nr. 2", "Cabinet 1", at(3, 7, 45), 4879),
                                        (l3, "OBN-75 nr. 4", "Sala de sterilizare", at(3, 18, 10), 31),
                                        (l1, "OBN-150 ecranată nr. 2", "Cabinet 1", at(1, 7, 50), 4878)):
            off = (datetime.fromisoformat(on) + timedelta(minutes=30)).isoformat()
            con.execute("INSERT INTO san_uv(lamp_id, lamp, room, cond, on_at, off_at, minutes, rest_hours, actor, "
                        "actor_id, off_actor, doer, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (lid, lamp, rm, "fără persoane", on, off, 30, rest, actor, actor_id, actor, NAT, on))
        con.commit()
    finally:
        con.close()

    # сейчас — дверью: идёт цикл автоклава, горит лампа в Cabinet 2
    call("/api/registre/257", {"ster_id": ac, "program": 0, "doer": NAT,
                               "arts": [{"name": "Instrumentar stomatologic", "qty": 9, "pack": "Pungă"},
                                        {"name": "Piese de mână", "qty": 2, "pack": "Pungă"}]})
    call("/api/registre/501", {"lamp_id": l2, "cond": "prezenta", "doer": NAT})
    return {"cycles": len(cycles) + 1, "cleanings": 4, "uv": 4}


def seed(base: str, cookie: str, db_path, pids: dict) -> dict:
    """Засеять три раздела живого слота. `pids` — из `seed.seed()`: `showcase`
    (имя → id) и `others` (id остальных пациентов по порядку)."""
    call = _Api(base, cookie)
    show, others = pids["showcase"], pids["others"]

    def pid_of(who) -> int:
        return show[who] if isinstance(who, str) else others[who]

    td = date.fromisoformat(call("/api/lab")["today"])
    return {"lab": seed_lab(call, td, pid_of), "stock": seed_stock(call, td, pid_of),
            "registre": seed_registre(call, td, db_path)}
