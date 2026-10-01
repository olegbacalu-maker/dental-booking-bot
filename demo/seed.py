"""Засев демо-клиники: живая картотека «на сегодня» для demo/gate.py.

Запускается ШЛЮЗОМ на копии шаблона перед стартом каждого слота — даты
раскладываются от текущего момента, поэтому «сегодня» в демо всегда
сегодня. Пишет напрямую в SQLite (sqlite3 из стандартной библиотеки): схему
и миграции уже сделала сама программа при сборке шаблона
(demo/gate.py › build_template), засев только наполняет таблицы.
⚠️ Поэтому он знает колонки — смена схемы значит и правку здесь; сторож —
`tests/test_demo.py::suite_seed`: засевает базу, созданную программой, и
открывает экраны.

Основа — витрины «Statistici» и «La recepție» (sandbox/proto-*/tools/seed_*.py,
28.09): ~2 месяца на 4 врача, сегодняшние статусы по часу, долги, активные
планы, звонки на завтра. Сверху — то, что показывает ФИШУ: восемь
«витринных» пациентов с полными данными, одонтограммой (поверхности, отметки,
мосты), анамнезом, предупреждениями, дневником визитов, пародонтограммой и
летописью; сегодняшние визиты отданы в первую очередь им, чтобы клик по
визиту в журнале открывал богатую карточку.

Запуск руками: `python -m demo.seed <dental.db> <clinic.json>`.
"""
from __future__ import annotations

import json
import pathlib
import random
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Chisinau")
_DOW = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# услуга → (длительность, цена, вес в случайном выборе); врачи — из clinic.json
SERVICE_META = {
    "pain": (60, 0, 6), "consult": (30, 0, 10), "hygiene": (60, 1100, 14),
    "filling": (60, 1500, 16), "extraction": (60, 1250, 7), "xray": (30, 200, 8),
    "crowns": (90, 3500, 9), "whitening": (90, 2500, 4), "implant": (30, 0, 3),
}
LOAD = {"d1": 7, "d2": 6, "d3": 6, "d4": 4}
PLAN_PROCS = [("Tratament endodontic", 1800, "d1"), ("Coroană zirconiu", 4500, "d4"),
              ("Coroană metalo-ceramică", 3200, "d4"), ("Implant dentar", 12000, "d2"),
              ("Obturație compozit", 1300, "d1"), ("Extracție molar", 900, "d2"),
              ("Igienizare profesională", 1100, "d3"), ("Albire dentară", 2500, "d3")]
TEETH_POOL = [11, 12, 14, 15, 16, 21, 24, 25, 26, 34, 35, 36, 37, 44, 45, 46, 47]
FIRST = ["Maria", "Ion", "Ana", "Vasile", "Elena", "Mihai", "Natalia", "Andrei",
         "Olga", "Sergiu", "Irina", "Victor", "Tatiana", "Dumitru", "Cristina",
         "Alexandru", "Svetlana", "Nicolae", "Ludmila", "Pavel", "Doina", "Radu",
         "Galina", "Igor", "Veronica", "Oleg", "Lilia", "Denis", "Aurelia", "Eugen"]
LAST = ["Popescu", "Rusu", "Ciobanu", "Munteanu", "Balan", "Rotaru", "Cara",
        "Donos", "Lungu", "Cebotari", "Moraru", "Turcan", "Sirbu", "Guțu",
        "Bodrug", "Ursu", "Crudu", "Cojocaru", "Plămădeală", "Zaharia", "Vieru",
        "Gheorghiță", "Negru", "Țurcanu", "Popa", "Scutaru", "Mereuță", "Olaru"]
STATE_RO = {"ok": "Sănătos", "carie": "Carie", "obturatie": "Obturație",
            "coroana": "Coroană", "implant": "Implant", "extras": "Extras", "lipsa": "Lipsă"}

# Витринные пациенты: фиша «как у живой клиники». Поля — те, что печатают
# 043/e и acord (IDNP, адрес, дата рождения). Все данные вымышленные.
SHOWCASE = [
    {"name": "Maria Popescu", "gender": "f", "born": "1978-03-14", "phone": "069 123 456",
     "idnp": "2003078140017", "email": "maria.popescu@example.md",
     "address": "str. Ștefan cel Mare 24, ap. 7, Cahul", "insurance": "CNAM activă",
     "doc": "d1", "lang": "ro",
     "teeth": [(16, "carie", "MO", "", ""), (26, "obturatie", "O", "", ""),
               (36, "carie", "OD", "", "tratament"), (46, "obturatie", "MOD", "", ""),
               (11, "obturatie", "V", "", "")],
     "alerts": [("allergy", "Alergie la penicilină")],
     "anam": ("cardio", "Hipertensiune arterială (controlată)", "Enalapril 10 mg dimineața",
              "Penicilină", "Fără reacții la anestezie locală"),
     "perio": True,
     "plan_active": [("Tratament endodontic", 36, 1800, "d1", "in_lucru"),
                     ("Coroană zirconiu", 36, 4500, "d4", "planificat")],
     "visits": [("Durere la masticație, dintele 36", "Carie profundă ocluzo-distală 36, percuție pozitivă",
                 "Pulpită cronică 36", "Deschiderea camerei pulpare, extirpare vitală, obturație canalară provizorie",
                 "Control peste 7 zile; evitarea alimentelor dure pe partea stângă"),
                ("Control planificat", "Obturație 16 integră, gingie fără semne de inflamație",
                 "Carie 16 — tratată", "Finisarea obturației 16", "Igienizare peste 6 luni")]},
    {"name": "Andrei Cebotari", "gender": "m", "born": "1985-11-02", "phone": "068 234 567",
     "idnp": "2001085110024", "email": "", "address": "str. Mihai Eminescu 5, Cahul",
     "insurance": "", "doc": "d2", "lang": "ro",
     "teeth": [(18, "extras", "", "", ""), (28, "extras", "", "", ""),
               (46, "carie", "O", "", ""), (47, "obturatie", "MO", "", "")],
     "alerts": [], "anam": ("fumat", "", "", "", "Fără particularități"),
     "perio": False,
     "plan_active": [("Obturație compozit", 46, 1300, "d1", "planificat")],
     "visits": [("Durere acută 28, umflătură", "Molar de minte 28 parțial erupt, pericoronarită",
                 "Pericoronarită 28", "Extracția 28 sub anestezie locală, sutură",
                 "Antibiotic 5 zile, clătiri cu clorhexidină, control la 7 zile")]},
    {"name": "Elena Rotaru", "gender": "f", "born": "1992-06-21", "phone": "079 345 678",
     "idnp": "2004092062018", "email": "elena.rotaru@example.md",
     "address": "str. Independenței 12, Cahul", "insurance": "CNAM activă", "doc": "d3",
     "lang": "ro",
     "teeth": [(12, "obturatie", "D", "", ""), (22, "obturatie", "M", "", "")],
     "alerts": [("info", "Preferă programări după ora 15:00")],
     "anam": ("", "", "", "", ""), "perio": False,
     "plan_active": [("Albire dentară", None, 2500, "d3", "planificat")],
     "visits": [("Igienizare periodică", "Depuneri de tartru supragingival, sângerare ușoară la sondare",
                 "Gingivită marginală", "Detartraj ultrasonic, periaj profesional, fluorizare",
                 "Periaj de 2 ori pe zi, ață dentară; control peste 6 luni")]},
    {"name": "Vasile Lungu", "gender": "m", "born": "1961-01-30", "phone": "060 456 789",
     "idnp": "2000061013031", "email": "", "address": "s. Crihana Veche, r. Cahul",
     "insurance": "CNAM activă", "doc": "d4", "lang": "ro",
     "teeth": [(36, "lipsa", "", "", ""), (37, "lipsa", "", "", ""), (46, "lipsa", "", "", ""),
               (45, "coroana", "", "", ""), (47, "coroana", "", "", ""),
               (16, "obturatie", "MOD", "", ""), (26, "carie", "O", "", "")],
     "bridge": ("45:stalp,46:corp,47:stalp", "metalo-ceramică", "d4"),
     "alerts": [("medication", "Anticoagulant (warfarină) — consult înainte de extracții"),
                ("warning", "Diabet zaharat tip 2")],
     "anam": ("diabet,coagulare,cardio", "Diabet zaharat tip 2; cardiopatie ischemică",
              "Warfarină 5 mg; Metformin 850 mg", "", "Hipotensiune la anestezie în 2019"),
     "perio": True,
     "plan_active": [("Implant dentar", 36, 12000, "d2", "planificat"),
                     ("Coroană metalo-ceramică", 26, 3200, "d4", "planificat")],
     "visits": [("Consult pentru proteză", "Edentație 36–37, 46; punte 45–47 în stare bună",
                 "Edentație parțială mandibulară", "Amprentă de studiu, plan de tratament discutat",
                 "Analize: glicemie, INR înainte de implantare"),
                ("Durere 26 la rece", "Carie ocluzală 26, test la rece pozitiv de scurtă durată",
                 "Carie medie 26", "Preparare, obturație provizorie", "Coroană după tratament")]},
    {"name": "Natalia Guțu", "gender": "f", "born": "2001-09-09", "phone": "061 567 890",
     "idnp": "2005001090042", "email": "natalia.gutu@example.md",
     "address": "str. 31 August 3, ap. 12, Cahul", "insurance": "", "doc": "d3", "lang": "ru",
     "teeth": [(14, "obturatie", "O", "", "")],
     "alerts": [], "anam": ("", "", "", "", ""), "perio": False,
     "plan_active": [], "visits": [("Dorește albire", "Dinți fără carii active, colorație extrinsecă",
                                    "Discromie dentară", "Igienizare profesională", "Albire în ședință separată")]},
    {"name": "Dumitru Moraru", "gender": "m", "born": "1975-04-18", "phone": "067 678 901",
     "idnp": "2002075041855", "email": "", "address": "str. Alexei Mateevici 40, Cahul",
     "insurance": "", "doc": "d1", "lang": "ro",
     "teeth": [(15, "carie", "O", "", ""), (24, "carie", "MO", "", ""), (25, "carie", "D", "", ""),
               (34, "obturatie", "O", "", ""), (44, "carie", "O", "", "tratament"),
               (18, "extras", "", "", "")],
     "alerts": [("warning", "Fumător — risc parodontal")],
     "anam": ("fumat", "", "", "", ""), "perio": False,
     "plan_active": [("Obturație compozit", 24, 1300, "d1", "in_lucru"),
                     ("Obturație compozit", 15, 1300, "d1", "planificat"),
                     ("Obturație compozit", 25, 1300, "d1", "planificat")],
     "visits": [("Sensibilitate la dulce 24", "Carii multiple 15, 24, 25, 44; igienă deficitară",
                 "Carii multiple", "Obturație 44 (în două ședințe)", "Igienizare, periaj corect, renunțare la fumat")]},
    {"name": "Cristina Țurcanu", "gender": "f", "born": "1988-12-05", "phone": "078 789 012",
     "idnp": "2003088120563", "email": "cristina.turcanu@example.md",
     "address": "str. Păcii 18, Cahul", "insurance": "CNAM activă", "doc": "d1", "lang": "ro",
     "teeth": [(36, "obturatie", "MO", "", ""), (27, "carie", "O", "", "")],
     "alerts": [("warning", "Sarcină — trimestrul II; fără radiografii")],
     "anam": ("sarcina", "", "Acid folic", "", ""), "perio": False,
     "plan_active": [("Obturație compozit", 27, 1300, "d1", "planificat")],
     "visits": [("Gingii sângerânde", "Gingivită de sarcină, placă bacteriană",
                 "Gingivită", "Igienizare blândă, instruire periaj", "Control lunar pe durata sarcinii")]},
    {"name": "Sergiu Balan", "gender": "m", "born": "1969-07-23", "phone": "069 890 123",
     "idnp": "2001069072377", "email": "", "address": "str. Bogdan Petriceicu Hasdeu 7, Cahul",
     "insurance": "", "doc": "d4", "lang": "ro",
     "teeth": [(11, "coroana", "", "", ""), (12, "coroana", "", "", ""), (21, "implant", "", "", ""),
               (16, "obturatie", "O", "", ""), (46, "coroana", "", "", "")],
     "alerts": [("medication", "Antihipertensive — a lua dimineața")],
     "anam": ("cardio", "Hipertensiune arterială", "Amlodipină 5 mg", "", ""), "perio": False,
     "plan_active": [("Coroană zirconiu", 21, 4500, "d4", "in_lucru")],
     "visits": [("Control implant 21", "Implant 21 integrat, gingie sănătoasă",
                 "Stare post-implantare", "Amprentă pentru coroană definitivă", "Proba coroanei peste 10 zile")]},
]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def local(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=TZ)


def _profile(clinic_json: pathlib.Path) -> tuple[dict, dict, dict]:
    """(врачи id→имя, услуги id→(подпись, [врачи]), часы)."""
    cfg = json.loads(pathlib.Path(clinic_json).read_text(encoding="utf-8"))
    docs = {d["id"]: d["name"] for d in cfg["doctors"]}
    svcs = {s["id"]: (s["ro"], list(s.get("docs") or docs)) for s in cfg["services"]
            if s["id"] in SERVICE_META}
    return docs, svcs, cfg.get("hours", {})


def seed(db_path, clinic_json, now: datetime | None = None) -> dict:
    """Засеять базу (схема уже создана программой). Возвращает счётчики."""
    rnd = random.Random(20261001)
    now = now or datetime.now(TZ)
    today = now.date()
    start, end = today - timedelta(days=70), today + timedelta(days=6)
    docs, svcs, hours = _profile(pathlib.Path(clinic_json))
    c = sqlite3.connect(str(db_path))
    c.execute("PRAGMA foreign_keys=OFF")
    tables = ("appt_calls", "perio_teeth", "perio_exams", "bridges", "teeth", "visit_records",
              "documents", "payments", "plan_items", "activity", "patient_alerts", "anamneza",
              "appointments", "patients")
    for t in tables:
        c.execute(f"DELETE FROM {t}")
    c.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)" % ",".join("?" * len(tables)), tables)

    def act(pid, kind, text, at, actor="recepție", tooth=None):
        c.execute("INSERT INTO activity(patient_id, at, actor, kind, tooth, text) VALUES(?,?,?,?,?,?)",
                  (pid, iso(at), actor, kind, tooth, text))

    # --- пациенты: витринные первыми (их id малы, поиск их видит сразу) ---
    show_ids = []
    for i, sp in enumerate(SHOWCASE):
        created = local(start - timedelta(days=rnd.randint(30, 400)), 10)
        cur = c.execute(
            "INSERT INTO patients(session_key, name, phone, lang, birth_year, created_at, birth_date, "
            "gender, idnp, email, address, insurance, primary_doctor) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"demo:s{i}", sp["name"], sp["phone"], sp["lang"], int(sp["born"][:4]), iso(created),
             sp["born"], sp["gender"], sp["idnp"], sp["email"], sp["address"], sp["insurance"],
             docs[sp["doc"]]))
        show_ids.append(cur.lastrowid)
    pats = list(show_ids)
    for i in range(232):
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        phone = (f"0{rnd.choice([60, 61, 62, 67, 68, 69, 78, 79])} "
                 f"{rnd.randint(100, 999)} {rnd.randint(100, 999)}")
        created = local(start - timedelta(days=rnd.randint(0, 400)), 10)
        cur = c.execute(
            "INSERT INTO patients(session_key, name, phone, lang, birth_year, created_at, gender) "
            "VALUES(?,?,?,?,?,?,?)",
            (f"demo:{i}", name, phone, rnd.choice(["ro", "ro", "ro", "ru"]),
             rnd.randint(1950, 2012), iso(created), rnd.choice(["m", "f"])))
        pats.append(cur.lastrowid)

    # --- визиты: 70 дней назад … 6 дней вперёд ---
    svc_by_doc = {dk: [k for k, (_l, ds) in svcs.items() if dk in ds] for dk in docs}
    n_appt = n_pay = n_plan = 0
    done_by_show: dict[int, list] = {pid: [] for pid in show_ids}
    show_today = list(show_ids)
    rnd.shuffle(show_today)
    d = start
    while d <= end:
        h = hours.get(_DOW[d.weekday()])
        if not h:
            d += timedelta(days=1)
            continue
        open_h, close_h = max(int(h[0]), 8), int(h[1])
        for dk, dname in docs.items():
            base = LOAD.get(dk, 5) if d.weekday() < 5 else max(1, LOAD.get(dk, 5) // 2)
            n = max(0, int(rnd.gauss(base, 1.4)))
            t = local(d, open_h)
            end_t = local(d, close_h)
            for _ in range(n):
                keys = svc_by_doc[dk]
                sid = rnd.choices(keys, weights=[SERVICE_META[k][2] for k in keys])[0]
                label = svcs[sid][0]
                dur, price, _w = SERVICE_META[sid]
                t += timedelta(minutes=rnd.choice([0, 0, 0, 30]))
                if t + timedelta(minutes=dur) > end_t:
                    break
                # сегодняшние визиты — сперва витринным: клик по журналу
                # обязан открывать богатую фишу
                pid = show_today.pop() if (d == today and show_today) else rnd.choice(pats)
                waiting = arrived = None
                if d < today or (d == today and t + timedelta(minutes=dur) <= now):
                    r = rnd.random()
                    status = "cancelled" if r < 0.085 else "noshow" if r < 0.145 else "done"
                    if status == "done" and rnd.random() < 0.7:
                        waiting = t - timedelta(minutes=rnd.randint(0, 12))
                        arrived = waiting + timedelta(minutes=rnd.randint(2, 22))
                elif d == today and t <= now:
                    status = "arrived"
                    waiting = t - timedelta(minutes=8)
                    arrived = t + timedelta(minutes=3)
                elif d == today and t <= now + timedelta(minutes=40):
                    status = rnd.choice(["waiting", "confirmed"])
                    if status == "waiting":
                        waiting = now - timedelta(minutes=rnd.randint(3, 15))
                else:
                    status = "confirmed"
                created = t - timedelta(days=rnd.randint(1, 16), hours=rnd.randint(0, 8))
                comment = rnd.choice(["", "", "", "", "control", "durere", "după radiografie",
                                      "pacient nou", ""])
                try:
                    cur = c.execute(
                        "INSERT INTO appointments(patient_id, service, doctor, starts_at, status, "
                        "source, reminded_day, reminded_2h, comment, created_at, doctor_id, "
                        "service_id, duration_min, waiting_at, arrived_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, label, dname, iso(t), status, "manual", 0, 0, comment, iso(created),
                         dk, sid, dur, iso(waiting) if waiting else None,
                         iso(arrived) if arrived else None))
                except sqlite3.IntegrityError:
                    t += timedelta(minutes=dur)
                    continue
                aid = cur.lastrowid
                n_appt += 1
                if d >= today - timedelta(days=14):
                    act(pid, "appt_new", f"Programare: {label} · {dname} · {t.strftime('%d.%m.%Y %H:%M')}",
                        created)
                if status == "done" and pid in done_by_show:
                    done_by_show[pid].append((aid, t, dname, sid))
                if status == "done" and price:
                    amount = int(round(price * rnd.uniform(0.85, 1.15) / 50.0)) * 50
                    done_at = t + timedelta(minutes=dur)
                    c.execute(
                        "INSERT INTO plan_items(patient_id, tooth, procedure, doctor, status, "
                        "price_mdl, created_at, done_at, appointment_id) VALUES(?,?,?,?,?,?,?,?,?)",
                        (pid, rnd.choice(TEETH_POOL) if sid in ("filling", "extraction", "crowns") else None,
                         label, dname, "finalizat", amount, iso(t - timedelta(days=2)), iso(done_at), aid))
                    n_plan += 1
                    # сегодняшние платят реже: «на выходе» ещё не дошли до кассы
                    if rnd.random() < (0.55 if d == today else 0.9):
                        method = rnd.choices(["numerar", "card", "transfer"], weights=[50, 40, 10])[0]
                        c.execute("INSERT INTO payments(patient_id, amount_mdl, method, note, taken_by, at) "
                                  "VALUES(?,?,?,?,?,?)",
                                  (pid, amount, method, "", "Recepție",
                                   iso(done_at + timedelta(minutes=rnd.randint(1, 10)))))
                        n_pay += 1
                t += timedelta(minutes=dur)
        d += timedelta(days=1)

    # --- активный план у ~40 обычных пациентов ---
    for pid in rnd.sample(pats[len(show_ids):], 40):
        for _ in range(rnd.choice([1, 1, 2, 2, 3])):
            proc, price, dk = rnd.choice(PLAN_PROCS)
            created = now - timedelta(days=rnd.randint(3, 75))
            tooth = rnd.choice(TEETH_POOL)
            c.execute(
                "INSERT INTO plan_items(patient_id, tooth, procedure, doctor, status, price_mdl, "
                "created_at) VALUES(?,?,?,?,?,?,?)",
                (pid, tooth, proc, docs[dk], rnd.choice(["planificat", "planificat", "in_lucru"]),
                 price, iso(created)))
            act(pid, "plan_add", f"Plan: + {proc} (dinte {tooth})", created, docs[dk], tooth)
            n_plan += 1

    # --- витринные: одонтограмма, мосты, анамнез, предупреждения, визиты, пародонт ---
    for pid, sp in zip(show_ids, SHOWCASE):
        dname = docs[sp["doc"]]
        for k, (tooth, state, surfaces, note, marks) in enumerate(sp["teeth"]):
            at = now - timedelta(days=rnd.randint(2, 60), hours=k)
            c.execute("INSERT INTO teeth(patient_id, tooth, state, note, updated_at, doctor, surfaces, "
                      "surface_states, marks) VALUES(?,?,?,?,?,?,?,?,?)",
                      (pid, tooth, state, note, iso(at), dname, surfaces, "", marks))
            txt = f"Dinte {tooth}: {STATE_RO[state]}" + (f" ({surfaces})" if surfaces else "")
            if marks:
                txt += " · În tratament"
            act(pid, "tooth", f"{txt} · {dname}", at, dname, tooth)
        if sp.get("bridge"):
            teeth, material, dk = sp["bridge"]
            c.execute("INSERT INTO bridges(patient_id, teeth, material, doctor, created_at) VALUES(?,?,?,?,?)",
                      (pid, teeth, material, docs[dk], iso(now - timedelta(days=rnd.randint(100, 400)))))
        for kind, text in sp["alerts"]:
            at = now - timedelta(days=rnd.randint(5, 90))
            c.execute("INSERT INTO patient_alerts(patient_id, kind, text, created_at) VALUES(?,?,?,?)",
                      (pid, kind, text, iso(at)))
            act(pid, "alert_add", f"Atenționare adăugată: {text}", at, dname)
        flags, boli, meds, alergii, anest = sp["anam"]
        if any(sp["anam"]) or sp["visits"]:
            at = now - timedelta(days=rnd.randint(10, 120))
            c.execute("INSERT INTO anamneza(patient_id, flags, boli, medicamente, alergii, anestezie, "
                      "author, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (pid, flags, boli, meds, alergii, anest, dname, iso(at), iso(at)))
        for (aid, t, vdoc, _sid), rec in zip(sorted(done_by_show[pid], key=lambda x: x[1], reverse=True),
                                             sp["visits"]):
            acuze, examen, diag, trat, rec_ = rec
            at = t + timedelta(minutes=35)
            c.execute("INSERT INTO visit_records(appointment_id, patient_id, doctor, acuze, examen, "
                      "diagnostic, tratament, recomandari, author, created_at, updated_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (aid, pid, vdoc, acuze, examen, diag, trat, rec_, vdoc, iso(at), iso(at)))
            act(pid, "consult", f"Consultație: {diag[:120]}", at, vdoc)
        for proc, tooth, price, dk, status in sp["plan_active"]:
            created = now - timedelta(days=rnd.randint(3, 40))
            c.execute("INSERT INTO plan_items(patient_id, tooth, procedure, doctor, status, price_mdl, "
                      "created_at) VALUES(?,?,?,?,?,?,?)",
                      (pid, tooth, proc, docs[dk], status, price, iso(created)))
            act(pid, "plan_add", f"Plan: + {proc}" + (f" (dinte {tooth})" if tooth else ""),
                created, docs[dk], tooth)
            n_plan += 1
        if sp["perio"]:
            at = now - timedelta(days=rnd.randint(7, 45))
            cur = c.execute("INSERT INTO perio_exams(patient_id, doctor, note, created_at) VALUES(?,?,?,?)",
                            (pid, docs["d3"], "Examen parodontal inițial", iso(at)))
            exam = cur.lastrowid
            for tooth in (16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26,
                          36, 35, 34, 33, 32, 31, 41, 42, 43, 44, 45, 46):
                deep = tooth in (16, 26, 36, 46)
                pd = [rnd.choice([2, 3, 3, 4, 5] if deep else [1, 2, 2, 3]) for _ in range(6)]
                rec = [rnd.choice([0, 0, 1, 2] if deep else [0, 0, 0, 1]) for _ in range(6)]
                bop = "".join("1" if rnd.random() < (0.45 if deep else 0.15) else "0" for _ in range(6))
                c.execute("INSERT INTO perio_teeth(exam_id, tooth, pd, rec, bop, mob, furc) VALUES(?,?,?,?,?,?,?)",
                          (exam, tooth, ",".join(map(str, pd)), ",".join(map(str, rec)), bop,
                           1 if deep and rnd.random() < 0.3 else 0, 0))

    # --- звонки-подтверждения на следующий рабочий день ---
    nd = today + timedelta(days=1)
    while not hours.get(_DOW[nd.weekday()]):
        nd += timedelta(days=1)
    rows = c.execute(
        "SELECT id, patient_id FROM appointments WHERE status='confirmed' AND starts_at >= ? AND starts_at < ? "
        "ORDER BY starts_at LIMIT 3", (iso(local(nd, 0)), iso(local(nd + timedelta(days=1), 0)))).fetchall()
    for (aid, pid), res in zip(rows, ["ok", "ok", "noanswer"]):
        at = now - timedelta(minutes=rnd.randint(5, 50))
        c.execute("INSERT INTO appt_calls(appointment_id, result, actor, at) VALUES(?,?,?,?)",
                  (aid, res, "Recepție", iso(at)))
        act(pid, "call", f"Confirmare telefonică ({at.strftime('%d.%m %H:%M')}): "
                         f"{'confirmat' if res == 'ok' else 'nu răspunde'}", at)
    c.commit()
    counts = {"patients": len(pats), "appointments": n_appt, "payments": n_pay, "plan_items": n_plan,
              "today": dict(c.execute("SELECT status, COUNT(*) FROM appointments WHERE starts_at >= ? "
                                      "AND starts_at < ? GROUP BY 1",
                                      (iso(local(today, 0)), iso(local(today + timedelta(days=1), 0)))).fetchall())}
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("python -m demo.seed <dental.db> <clinic.json>")
        return 2
    print(seed(argv[0], argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
