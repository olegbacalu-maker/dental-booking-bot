"""Фиша пациента (C18): JSON API `/api/patients/{pid}` — цифры, порядок и
слова фиши, записанные руками на пациенте, у которого есть каждая ветка.

Что стережётся. Вся арифметика фиши (сумма активного плана, прогресс без
отказов, долг, «следующий» и «последний» визит, пилюли шапки, цифры KPI,
риски анамнеза) до 18.09 жила внутри f-строк старой страницы и проверялась
только через готовую разметку. С C18 она в `card.py`, а эталон — ожидания,
записанные руками: до 13.10 их держала старая страница (`suite_pin`), а
`suite_api` сверял с ней ответ API строка в строку; со снятием старой фиши
те же ожидания перенесены в `suite_api` буквально, без пересчёта по формуле.
`suite_actions` гоняет действия фиши через JSON: отказ проверки 422 с полем,
спор с состоянием 409, удача — свежая фиша.
"""
import json
import re
import sqlite3
from datetime import timedelta

from harness import (Client, Result, Server, clinic_today, day_model, new_patient,
                     pid_by_phone)

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
PDF = b"%PDF-1.4 " + b"x" * 64


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _dmy(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return pid_by_phone(c, phone)


def _aid(c: Client, day: str) -> int:
    """id последней по времени записи дня — из «Lista zilei» модели дня."""
    return int([r["id"] for r in day_model(c, day)["list"] if not r["is_note"]][-1])


def _seed(c: Client) -> dict:
    """Пациент с каждой веткой фиши: четыре визита (прошлый завершённый с
    дневником, отменённый, прошлый подтверждённый без дневника, будущий),
    план из пяти позиций во всех четырёх статусах с просроченным сроком и
    позицией без цены, платёж и возврат, четыре предупреждения (в шапку
    попадают три), анамнез с галочками и свободным текстом, три документа
    трёх видов (картинка, PDF, чужая программа), два зуба, один из них
    имплант."""
    def visit(day: int, time: str, doc: str, svc: str = "consult") -> int:
        c.post_json("/api/schedule/appointments", {"date": _d(day), "time": time,
                                                  "doctor": doc, "service": svc,
                                                  "name": "Pin Test", "phone": "069000111"})
        return _aid(c, _d(day))

    s = {}
    s["v_done"] = visit(-10, "10:00", "d2")
    c.post_json(f"/api/schedule/appointments/{s['v_done']}/status", {"to": "done"})
    c.post_json(f"/api/visits/{s['v_done']}", {"acuze": "Durere", "diagnostic": "Pulpită 26",
                                              "tratament": "Trat"})
    s["v_canc"] = visit(-3, "11:00", "d3", "hygiene")
    c.post_json(f"/api/schedule/appointments/{s['v_canc']}/status", {"to": "cancelled"})
    s["v_last"] = visit(-1, "12:00", "d2")
    s["v_next"] = visit(2, "09:30", "d2")
    pid = s["pid"] = _pid(c, "069000111")
    c.post_json(f"/api/patients/{pid}/profile", {"name": "Pin Test", "phone": "069000111",
                                                "birth_date": "1985-03-07", "gender": "f",
                                                "idnp": "2000000000001",
                                                "email": "pin@example.com",
                                                "address": "str. Pin 1",
                                                "insurance": "CNAM activă",
                                                "primary_doctor": "Dr. Activ Doi",
                                                "file_no": "D-5", "notes": "nota internă"})
    c.post_json(f"/api/patients/{pid}/teeth/11", {"state": "carie", "note": "distal",
                                                 "doctor": "Dr. Activ Doi", "surfaces": []})
    c.post_json(f"/api/patients/{pid}/teeth/36", {"state": "implant",
                                                 "doctor": "Dr. Activ Doi", "surfaces": []})
    for proc, tooth, price, due in (("Coroană 11", "11", "1200", ""),
                                    ("Detartraj", "", "500", ""),
                                    ("Extracție 48", "48", "700", "2020-01-01"),
                                    ("Consult gratuit", "", "", ""),
                                    ("Implant 36", "36", "9000", "")):
        c.post_json(f"/api/patients/{pid}/plan", {"procedure": proc, "tooth": tooth,
                                                 "price": price, "due_date": due,
                                                 "doctor": "Dr. Activ Doi" if proc == "Coroană 11" else ""})
    # id позиций — в порядке заведения (фиша отдаёт их в порядке плана)
    ids = sorted(it["id"] for it in _card(c, pid)["plan"]["items"])
    s["p_lucru"], s["p_fin"], s["p_due"], s["p_free"], s["p_refuz"] = ids
    c.post_json(f"/api/patients/{pid}/plan/{s['p_lucru']}/status", {"to": "in_lucru"})
    c.post_json(f"/api/patients/{pid}/plan/{s['p_fin']}/status", {"to": "in_lucru"})
    c.post_json(f"/api/patients/{pid}/plan/{s['p_fin']}/status", {"to": "finalizat"})
    c.post_json(f"/api/patients/{pid}/plan/{s['p_refuz']}/status", {"to": "refuzat",
                                                                   "motiv": "refuză implantul"})
    c.post_json(f"/api/patients/{pid}/payments", {"amount": "300", "method": "numerar",
                                                 "note": "avans"})
    c.post_json(f"/api/patients/{pid}/payments", {"amount": "-100", "method": "card",
                                                 "note": "restituire"})
    for kind, text in (("allergy", "Penicilină"), ("medication", "Anticoagulante"),
                       ("warning", "Leșină"), ("info", "Vorbește rusă")):
        c.post_json(f"/api/patients/{pid}/alerts", {"kind": kind, "text": text})
    c.post_json(f"/api/patients/{pid}/anamneza", {"flags": ["diabet", "cardio"],
                                                 "alergii": "latex"})
    c.post_file(f"/api/patients/{pid}/documents", "file", "rx.png", PNG, mime="image/png", category="radiografie")
    c.post_file(f"/api/patients/{pid}/documents", "file", "acord.pdf", PDF, mime="application/pdf", category="acord")
    c.post_file(f"/api/patients/{pid}/documents", "file", "trimitere.docx", b"PK" + b"x" * 64, category="trimitere")
    return s


def _card(c: Client, pid: int, views: bool = False) -> dict:
    r = c.get(f"/api/patients/{pid}" + ("?views=1" if views else ""))
    assert r.status == 200, r.body[:200]
    return _j(r)["data"]


def _feed(c: Client, pid: int) -> list[dict]:
    """Летопись вместе с журналом доступа — лентой отдельно (`/activity`): она
    сама просмотра не пишет, чтение не меняет считаемое."""
    return _j(c.get(f"/api/patients/{pid}/activity?views=1"))["data"]["items"]


def _opens(c: Client, pid: int) -> int:
    """Строк «Fișa deschisă» в журнале доступа."""
    return sum(a["kind"] == "view" for a in _feed(c, pid))


def suite_api(res: Result) -> None:
    """`GET /api/patients/{pid}` на засеянном пациенте: пилюли, KPI, план,
    сальдо, документы, визиты, летопись, анамнез, профиль — значениями,
    записанными руками (до 13.10 — эталоном старой страницы, `suite_pin`)."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/patients/1").status, 401)
        c = Client(s.url).login()
        res.check("чужая фиша — 404", c.get("/api/patients/777").status, 404)
        sd = _seed(c)
        pid = sd["pid"]
        d = _card(c, pid)
        res.check("состав ответа", sorted(d),
                  sorted(["id", "name", "initials", "archived", "erasure", "profile", "hero",
                          "kpi", "alerts", "anamneza", "plan", "finance", "documents",
                          "forms", "visits", "activity", "appoint", "options"]))
        res.check("пилюли: активен, ТРИ первых предупреждения, страховка, долг, импланты",
                  [(pl["tone"], pl["text"]) for pl in d["hero"]["pills"]],
                  [("green", "Pacient activ"), ("orange", "Penicilină"),
                   ("orange", "Anticoagulante"), ("red", "Leșină"), ("green", "CNAM activă"),
                   ("red", "De achitat: 300 MDL"), ("purple", "1 implant")])
        res.ok("пилюли несут имена значков", all(pl["icon"] for pl in d["hero"]["pills"]),
               f"{d['hero']['pills']}")
        res.check("KPI: визиты без отменённого, активные, готово, отменённые, давность, "
                  "следующий, последний",
                  (d["kpi"]["visits"], d["kpi"]["active"], d["kpi"]["done"], d["kpi"]["canc"],
                   d["hero"]["days_ago"], d["hero"]["next"]["date"][:5], d["hero"]["next"]["time"],
                   d["hero"]["last"]["date"], d["hero"]["last"]["service"]),
                  (3, 3, 1, 1, 1, _dmy(2)[:5], "09:30", _dmy(-1), "Consultație"))
        pl = d["plan"]
        hidden = pl["items"] and [it["status"] not in d["options"]["tab_states"][pl["default_tab"]]
                                  for it in pl["items"]]
        res.check("порядок плана: в работе, планируемое по сроку, готовое, отказ; закрытые "
                  "спрятаны вкладкой по умолчанию",
                  [(it["status"], it["procedure"], h) for it, h in zip(pl["items"], hidden)],
                  [("in_lucru", "Coroană 11", False), ("planificat", "Extracție 48", False),
                   ("planificat", "Consult gratuit", False), ("finalizat", "Detartraj", True),
                   ("refuzat", "Implant 36", True)])
        res.check("план: суммы, прогресс, счёт, вкладка",
                  (pl["total"], pl["total_done"], pl["n_track"], pl["pct_done"], pl["counts"],
                   pl["default_tab"], pl["n_act"]),
                  (1900, 500, 4, 25, {"planificat": 2, "in_lucru": 1, "finalizat": 1, "refuzat": 1},
                   "act", 3))
        by = {it["procedure"]: it for it in pl["items"]}
        res.check("план: кнопки по статусу — переходы по рёбрам плана",
                  [(it["status"], it["next"], it["refusable"], it["deletable"]) for it in pl["items"]],
                  [("in_lucru", "finalizat", True, False), ("planificat", "in_lucru", True, True),
                   ("planificat", "in_lucru", True, True), ("finalizat", "in_lucru", False, False),
                   ("refuzat", "planificat", False, False)])
        res.check("план: срок просрочен, дата закрытия, причина отказа, подписи",
                  (by["Extracție 48"]["due"], by["Extracție 48"]["overdue"],
                   by["Detartraj"]["done"], by["Implant 36"]["motiv"], by["Coroană 11"]["label"],
                   by["Consult gratuit"]["price"], by["Coroană 11"]["tooth"]),
                  ("01.01.2020", True, _dmy(0), "refuză implantul", "În lucru", None, 11))
        # без визита врач позиции — запланированный, и Detartraj, закрытый
        # кнопкой плана, тоже; выполненная на визите — test_visit.suite_plan
        res.check("план: врач позиции и кого планировали",
                  [(it["procedure"], it["doctor"], it["planned_doctor"]) for it in pl["items"]],
                  [("Coroană 11", "Dr. Activ Doi", "Dr. Activ Doi"), ("Extracție 48", "", ""),
                   ("Consult gratuit", "", ""), ("Detartraj", "", ""), ("Implant 36", "", "")])
        fin = d["finance"]
        res.check("сальдо: начислено, оплачено, долг, плашка",
                  (fin["charged"], fin["paid"], fin["debt"], fin["sold"], fin["can_delete"]),
                  (500, 200, 300, {"kind": "bad", "amount": 300}, True))
        res.check("платежи: свежие первыми, возврат с минусом, кто принял",
                  [(p_["neg"], p_["amount"], p_["method"], p_["note"], p_["taken_by"])
                   for p_ in fin["payments"]],
                  [(True, 100, "card", "restituire", "Director"),
                   (False, 300, "numerar", "avans", "Director")])
        res.check("документы: порядок, дата, размер, чем открывать",
                  [(x["filename"], x["when"], x["size"], x["view"], x["category"])
                   for x in d["documents"]],
                  [("trimitere.docx", _dmy(0), "0 KB", "ext", "trimitere"),
                   ("acord.pdf", _dmy(0), "0 KB", "pdf", "acord"),
                   ("rx.png", _dmy(0), "0 KB", "img", "radiografie")])
        hist = d["visits"]["history"]
        res.check("визиты: строки истории — свежие первыми, отменённый со своим словом",
                  [(f"{v['when']} · {v['status_label']}", v["service"]) for v in hist],
                  [(f"{_dmy(2)} 09:30 · programată", "Consultație"),
                   (f"{_dmy(-1)} 12:00 · programată", "Consultație"),
                   (f"{_dmy(-3)} 11:00 · anulată", "Igienizare"),
                   (f"{_dmy(-10)} 10:00 · finalizată", "Consultație")])
        res.check("визиты: следующий, дневник и приглашение, диагноз, ссылка с возвратом",
                  [(v["is_next"], v["consult"], v["diag"]) for v in hist],
                  [(True, "", ""), (False, "invite", ""), (False, "", ""),
                   (False, "rec", "Pulpită 26")])
        res.check("визиты: адрес дневника — с возвратом в фишу (и у приглашения)",
                  (hist[3]["url"], hist[1]["url"]),
                  (f"/admin/visit/{sd['v_done']}?back=/admin/patient/{pid}",
                   f"/admin/visit/{sd['v_last']}?back=/admin/patient/{pid}"))
        res.check("визиты: живые для списка за цифрой, всего",
                  (len(d["visits"]["live"]), d["visits"]["n_total"]), (3, 4))
        act = d["activity"]
        res.check("летопись: 29 событий без просмотров, свежие первыми",
                  (len(act["items"]), act["items"][0]["text"], act["items"][-1]["text"],
                   any(a["kind"] == "view" for a in act["items"])),
                  (29, "Document încărcat: trimitere.docx",
                   f"Programare: Consultație · Dr. Activ Doi · {_dmy(-10)} 10:00", False))
        res.check("летопись: показ 10, без просмотров, автор и час",
                  (act["shown"], act["views"], act["items"][0]["who"],
                   len(act["items"][0]["hhmm"]), act["items"][0]["icon"]),
                  (10, False, "Director", 5, "clip"))
        an = d["anamneza"]
        res.check("анамнез: риски, галочки по порядку словаря, свободный текст, автор",
                  (an["state"], an["n_risk"], an["flags"], an["marked"], an["free"],
                   an["when"], an["author"], an["texts"]["alergii"]),
                  ("risk", 3, ["cardio", "diabet"],
                   ["Boli cardiovasculare / hipertensiune", "Diabet zaharat"],
                   [{"label": "Alergii (medicamente, materiale)", "text": "latex",
                     "short": "Alergii"}],
                   _dmy(0), "Director", "latex"))
        res.check("предупреждения: все четыре, по порядку, словом вида",
                  [(a["kind"], a["label"], a["text"]) for a in d["alerts"]],
                  [("allergy", "Alergie", "Penicilină"), ("medication", "Medicație", "Anticoagulante"),
                   ("warning", "Atenție", "Leșină"), ("info", "Info", "Vorbește rusă")])
        pr = d["profile"]
        res.check("профиль: значения, дата рождения и пол по-человечески",
                  [pr["phone"], pr["birth"], pr["gender_label"], pr["idnp"], pr["email"],
                   pr["address"], pr["insurance"], pr["primary_doctor"], pr["created"]],
                  ["069000111", "07.03.1985", "F", "2000000000001", "pin@example.com",
                   "str. Pin 1", "CNAM activă", "Dr. Activ Doi", _dmy(0)])
        res.check("профиль: пол сырым значением для формы", pr["gender"], "f")
        res.check("профиль: возраст, канал, дело, заметка, язык, год",
                  (pr["age"], pr["channel"], pr["file_no"], pr["notes"], pr["lang"], pr["year"]),
                  (41, "recepție", "D-5", "nota internă", "ro", _dmy(0)[-4:]))
        res.check("шапка: имя, инициалы, архив, ветка стирания",
                  (d["name"], d["initials"], d["archived"], d["erasure"]),
                  ("Pin Test", "PT", False, "anon"))
        res.check("окно записи: врачи по услуге, медик курант выбран",
                  (d["appoint"]["doctors"], d["appoint"]["primary"],
                   [x["id"] for x in d["appoint"]["services"]], d["appoint"]["today"]),
                  ({"consult": ["d2", "d3", "d4"], "pain": ["d2"], "hygiene": ["d3"],
                    "orphan": [], "long": ["d2"]}, "d2",
                   ["consult", "pain", "hygiene", "orphan", "long"], _d(0)))
        op = d["options"]
        res.check("справочники форм: виды, вопросы, категории, оплата, зубы",
                  (len(op["alert_kinds"]), len(op["anamneza_flags"]), len(op["anamneza_texts"]),
                   [x["id"] for x in op["doc_categories"]], [x["id"] for x in op["pay_methods"]],
                   op["teeth"][:3], op["milk"][:2], op["max_doc_mb"], op["doctors"]),
                  (4, 12, 4, ["radiografie", "acord195", "acord_plan", "chestionar", "fisa043",
                              "acord", "trimitere", "alt"],
                   ["numerar", "card", "transfer"], [18, 17, 16], [55, 54], 25,
                   ["Dr. Arhivat Unu", "Dr. Activ Doi", "Dr. Activ Trei", "Dr. Activ Patru"]))

        # журнал доступа (закон 195): каждое открытие фиши пишется
        n_before = len(_card(c, pid, views=True)["activity"]["items"])
        res.ok("?views=1 — в ленте просмотры", any(
            a["kind"] == "view" for a in _card(c, pid, views=True)["activity"]["items"]),
               "просмотров нет")
        res.ok("каждое открытие фиши записано (второй просмотр добавил строку)",
               len(_card(c, pid, views=True)["activity"]["items"]) > n_before, "не пишется")
        r = c.get(f"/api/patients/{pid}/activity?views=1")
        res.ok("лента отдельно — те же строки, без новой записи о просмотре",
               r.status == 200 and _j(r)["data"]["views"] is True
               and len(_j(r)["data"]["items"]) == len(_card(c, pid, views=True)["activity"]["items"]) - 1,
               r.body[:200])

        # одонтограмма — своей моделью (C21): засеянные зубы, остальные здоровы
        odo = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]
        res.check("модель одонтограммы: кариес 11 и имплант 36, остальные здоровы",
                  {k: v["state"] for k, v in odo["teeth"].items() if v["state"] != "ok"},
                  {"11": "carie", "36": "implant"})

        # пустая фиша — те же пустые состояния
        c.post_json("/api/patients", {"name": "Gol Fără"})
        bare = _pid(c, "Gol")
        d = _card(c, bare)
        res.check("пустая фиша: пилюля одна, KPI нули, план и сальдо пусты, анамнез не собран",
                  ([(pl["tone"], pl["text"]) for pl in d["hero"]["pills"]], d["kpi"],
                   d["hero"]["last"], d["hero"]["next"], d["hero"]["days_ago"],
                   d["plan"]["items"], d["plan"]["default_tab"], d["finance"]["sold"],
                   d["anamneza"]["state"], d["alerts"], d["documents"], d["visits"]["history"],
                   d["profile"]["phone"], d["erasure"]),
                  ([("green", "Pacient activ")],
                   {"visits": 0, "active": 0, "done": 0, "canc": 0}, None, None, None,
                   [], "act", None, "none", [], [], [], "", "delete"))

        # сальдо, архив и план из одних отказов — ветки, которые до 13.10 держал
        # эталон старой фиши (`suite_pin`)
        iid = _act(c, bare, "/plan", {"procedure": "Sigilare", "price": "200"})[1]["data"]["plan"]["items"][0]["id"]
        _act(c, bare, f"/plan/{iid}/status", {"to": "in_lucru"})
        _act(c, bare, f"/plan/{iid}/status", {"to": "finalizat"})
        d = _act(c, bare, "/payments", {"amount": "200", "method": "card"})[1]["data"]
        res.check("оплачено ровно — «achitat integral», без пилюли долга и аванса",
                  (d["finance"]["sold"], [pl["text"] for pl in d["hero"]["pills"]
                                         if pl["text"].startswith(("De achitat", "Avans"))]),
                  ({"kind": "ok", "amount": 0}, []))
        d = _act(c, bare, "/payments", {"amount": "50", "method": "card"})[1]["data"]
        res.check("переплата — аванс в сальдо и в шапке",
                  (d["finance"]["sold"],
                   ("green", "Avans: 50 MDL") in [(pl["tone"], pl["text"]) for pl in d["hero"]["pills"]]),
                  ({"kind": "plus", "amount": 50}, True))
        d = _act(c, bare, "/archive", {"on": True})[1]["data"]
        pills = [(pl["tone"], pl["text"]) for pl in d["hero"]["pills"]]
        res.check("архив: серая пилюля вместо «активен»",
                  (d["archived"], ("grey", "Arhivat") in pills, ("green", "Pacient activ") in pills),
                  (True, True, False))
        rf = new_patient(c, "Doar Refuz")
        iid = _act(c, rf, "/plan", {"procedure": "Implant", "price": "100"})[1]["data"]["plan"]["items"][0]["id"]
        pl = _act(c, rf, f"/plan/{iid}/status", {"to": "refuzat", "motiv": "nu vrea"})[1]["data"]["plan"]
        res.check("план из одних отказов открывает вкладку Refuzate, прогресс 0/0, план 0 MDL",
                  (pl["default_tab"], pl["n_track"], pl["counts"].get("refuzat"), pl["total"]),
                  ("refuzat", 0, 1, 0))


def _act(c: Client, pid: int, path: str, payload: dict | None = None) -> tuple:
    """(код HTTP, конверт) действия фиши."""
    r = c.post_json(f"/api/patients/{pid}{path}", payload or {})
    return r.status, _j(r)


def _gone(c: Client, pid: int, api: str) -> tuple:
    """Удаление того, чего в фише нет: (HTTP, код, есть ли текст, есть ли
    данные). Фиша в ответе на такое — чтение мимо журнала доступа: удаление
    не состоялось и строки в летописи не оставило. (До 13.10 рядом сверялась
    плашка старой формы — тот же код.)"""
    r = c.post_json(f"/api/patients/{pid}{api}", {})
    j = _j(r)
    return r.status, j["code"], bool(j["text"]), "data" in j


def suite_actions(res: Result) -> None:
    """Действия фиши через JSON: коды MSG_BANNER, отказ проверки 422 с полем,
    спор с состоянием 409, удача — свежая фиша."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Act Test", "phone": "069555000"})
        pid = _pid(c, "069555000")
        c.post_json("/api/patients", {"name": "Alt Om", "phone": "069555111"})

        # ---- профиль ----
        st, j = _act(c, pid, "/profile", {"name": " ", "phone": "069555000"})
        res.check("профиль без имени — 422, поле name", (st, j["code"], j.get("field")),
                  (422, "bad_card", "name"))
        st, j = _act(c, pid, "/profile", {"name": "Act Test", "birth_date": "2222-01-01"})
        res.check("дата в будущем — 422 bad_bd, поле", (st, j["code"], j.get("field")),
                  (422, "bad_bd", "birth_date"))
        st, j = _act(c, pid, "/profile", {"name": "Act Test", "idnp": "12"})
        res.check("кривой IDNP — 422 bad_idnp", (st, j["code"], j.get("field")), (422, "bad_idnp", "idnp"))
        st, j = _act(c, pid, "/profile", {"name": "Act Test Nou", "phone": "069555000",
                                          "birth_date": "1990-05-06", "lang": "ru",
                                          "notes": "n", "insurance": "CNAM"})
        # ⚠️ Возраст — от «сегодня» клиники, а не числом: число 36 покраснело бы
        # само 06.05.2027 без единой правки кода (посторонний разбор 17.10)
        today = clinic_today()
        age = today.year - 1990 - ((today.month, today.day) < (5, 6))
        res.check("профиль сохранён — ok_card и свежая фиша",
                  (st, j["code"], j["data"]["name"], j["data"]["profile"]["birth"],
                   j["data"]["profile"]["lang"], j["data"]["profile"]["age"],
                   [(pl["tone"], pl["text"]) for pl in j["data"]["hero"]["pills"]]),
                  (200, "ok_card", "Act Test Nou", "06.05.1990", "ru", age,
                   [("green", "Pacient activ"), ("green", "CNAM")]))
        res.check("правка видна и при новом открытии фиши", _card(c, pid)["name"], "Act Test Nou")
        st, j = _act(c, pid, "/profile", {"name": "Act Test Nou", "phone": "069 555 111"})
        res.check("чужой номер — сохранено, но названо вслух (warn)",
                  (st, j["code"], j["tone"]), (200, "ok_tel_dup", "warn"))
        res.check("повторное сохранение того же — тождественно",
                  _act(c, pid, "/profile", {"name": "Act Test Nou", "phone": "069 555 111"})[1]["code"],
                  "ok_tel_dup")

        # ---- медик курант из шапки фиши (14.10, слово Олега: выбор на месте) ----
        # ⛔ Своим маршрутом: /profile пишет ВСЕ поля, и поле, которого нет в
        # теле, стирается — врач одним полем через него снёс бы профиль
        _act(c, pid, "/profile", {"name": "Act Test Nou", "phone": "069555000",
                                  "birth_date": "1990-05-06", "insurance": "CNAM",
                                  "notes": "n", "lang": "ru"})
        keep = ("name", "phone", "birth", "insurance", "notes", "lang")
        before = {k: _card(c, pid)["profile"][k] for k in keep}
        doc = _card(c, pid)["options"]["doctors"][1]
        st, j = _act(c, pid, "/doctor", {"doctor": "Dr. Nimeni"})
        res.check("врач не из клиники — 422 bad_card, поле primary_doctor, без фиши",
                  (st, j["code"], j.get("field"), "data" in j), (422, "bad_card", "primary_doctor", False))
        st, j = _act(c, pid, "/doctor", {"doctor": doc})
        res.check("врач сохранён одним полем — ok_card, остальной профиль цел",
                  (st, j["code"], j["data"]["profile"]["primary_doctor"],
                   {k: j["data"]["profile"][k] for k in keep}),
                  (200, "ok_card", doc, before))
        res.check("смена врача — строка летописи со своим текстом",
                  [a["text"] for a in j["data"]["activity"]["items"] if a["kind"] == "profile"][:1],
                  [f"Medic curant: {doc}"])
        st, j = _act(c, pid, "/doctor", {"doctor": ""})
        res.check("пусто — врач снят, остальное цело",
                  (st, j["data"]["profile"]["primary_doctor"], {k: j["data"]["profile"][k] for k in keep}),
                  (200, "", before))
        # врача, которого клиника уже убрала из списка, фиша хранит; повторный
        # выбор того же имени (стоит в шапке первым) не отбивается
        con = sqlite3.connect(str(s.dir / "dental.db"))
        try:
            con.execute("UPDATE patients SET primary_doctor = 'Dr. Plecat' WHERE id = ?", (pid,))
            con.commit()
        finally:
            con.close()
        st, j = _act(c, pid, "/doctor", {"doctor": "Dr. Plecat"})
        res.check("прежний врач не из списка — пересохранение тождественно",
                  (st, j["data"]["profile"]["primary_doctor"]), (200, "Dr. Plecat"))

        # ---- архив ----
        st, j = _act(c, pid, "/archive", {"on": True})
        res.check("в архив — ok_arh, archived", (st, j["code"], j["data"]["archived"]), (200, "ok_arh", True))
        st, j = _act(c, pid, "/archive", {"on": False})
        res.check("из архива — ok_unarh", (st, j["code"], j["data"]["archived"]), (200, "ok_unarh", False))

        # ---- предупреждения ----
        st, j = _act(c, pid, "/alerts", {"kind": "zzz", "text": "x"})
        res.check("чужой вид — 422", (st, j["code"], j.get("field")), (422, "bad_card", "text"))
        st, j = _act(c, pid, "/alerts", {"kind": "allergy", "text": "  Latex  "})
        res.check("предупреждение добавлено, в шапке пилюля",
                  (st, j["code"], [(a["kind"], a["text"]) for a in j["data"]["alerts"]],
                   ("orange", "Latex") in [(pl["tone"], pl["text"]) for pl in j["data"]["hero"]["pills"]]),
                  (200, "ok_card", [("allergy", "Latex")], True))
        aid = j["data"]["alerts"][0]["id"]
        st, j = _act(c, pid, f"/alerts/{aid}/delete")
        res.check("удалено — тихий успех, список пуст", (st, j["code"], j["data"]["alerts"]), (200, "", []))
        # ⚠️ До 24.09 снятие предупреждения не оставляло в летописи НИЧЕГО
        # (закон 195: кто снял аллергию), а удаление по чужому id отвечало
        # фишей целиком — чтением мимо журнала доступа
        res.check("снятие — одна строка летописи: текст, имя вошедшего, значок",
                  [(a["text"], a["who"], a["icon"]) for a in j["data"]["activity"]["items"]
                   if a["kind"] == "alert_del"],
                  [("Atenționare ștearsă: Latex", "Director", "trash")])
        feed = _feed(c, pid)
        res.check("уже снятое (вторая вкладка) — 404 alert_gone без фиши",
                  _gone(c, pid, f"/alerts/{aid}/delete"),
                  (404, "alert_gone", True, False))
        c.post_json("/api/patients", {"name": "Alt Alerta", "phone": "069555777"})
        pid_alt = _pid(c, "069555777")
        oid = _act(c, pid_alt, "/alerts", {"kind": "info", "text": "Străin"})[1]["data"]["alerts"][0]["id"]
        res.check("чужое предупреждение через свою фишу — отказ, у владельца осталось",
                  (_gone(c, pid, f"/alerts/{oid}/delete"),
                   [a["text"] for a in _card(c, pid_alt)["alerts"]]),
                  ((404, "alert_gone", True, False), ["Străin"]))
        res.check("отказы не тронули ни летописи, ни журнала доступа", _feed(c, pid), feed)
        st, j = _act(c, pid, "/alerts", {"kind": "allergy", "text": "Iod"})
        aid = j["data"]["alerts"][0]["id"]
        res.check("второе снятие — тоже строкой в летописи, свежие первыми",
                  (c.post_json(f"/api/patients/{pid}/alerts/{aid}/delete", {}).msg,
                   [a["text"] for a in _feed(c, pid) if a["kind"] == "alert_del"]),
                  ("", ["Atenționare ștearsă: Iod", "Atenționare ștearsă: Latex"]))

        # ---- анамнез ----
        st, j = _act(c, pid, "/anamneza", {"flags": [], "boli": "  "})
        res.check("пустой опросник на пустом — 422 bad_anam", (st, j["code"]), (422, "bad_anam"))
        st, j = _act(c, pid, "/anamneza", {"flags": ["hiv", "zzz"], "anestezie": "lipotimie"})
        res.check("анамнез сохранён: чужой флаг отброшен, риски посчитаны",
                  (st, j["code"], j["data"]["anamneza"]["flags"], j["data"]["anamneza"]["n_risk"],
                   j["data"]["anamneza"]["state"]), (200, "ok_anam", ["hiv"], 2, "risk"))
        st, j = _act(c, pid, "/anamneza", {"flags": []})
        res.check("пустое пересохранение существующего — законное снятие, ok_anam",
                  (st, j["code"], j["data"]["anamneza"]["state"]), (200, "ok_anam", "ok"))

        # ---- план ----
        st, j = _act(c, pid, "/plan", {"procedure": "  "})
        res.check("позиция без процедуры — 422, поле", (st, j["code"], j.get("field")),
                  (422, "bad_card", "procedure"))
        st, j = _act(c, pid, "/plan", {"procedure": "Plombă", "tooth": "99", "price": "5000000",
                                       "due_date": "cândva"})
        it = j["data"]["plan"]["items"][0]
        res.check("позиция добавлена: чужой зуб и кривой срок обнулены, цена срезана",
                  (st, j["code"], it["procedure"], it["tooth"], it["price"], it["due"],
                   it["status"], it["next"], it["deletable"], j["data"]["kpi"]["active"]),
                  (200, "ok_card", "Plombă", None, 1000000, "", "planificat", "in_lucru", True, 1))
        iid = it["id"]
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "finalizat"})
        res.check("запрещённое ребро — 409 bad_card", (st, j["code"]), (409, "bad_card"))
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "in_lucru"})
        res.check("Începe — тихий успех, статус и кнопки обновились",
                  (st, j["code"], j["data"]["plan"]["items"][0]["status"],
                   j["data"]["plan"]["items"][0]["next"]), (200, "", "in_lucru", "finalizat"))
        st, j = _act(c, pid, f"/plan/{iid}/delete")
        res.check("удалить начатую — 409 bad_pdel", (st, j["code"]), (409, "bad_pdel"))
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "refuzat", "motiv": "  "})
        res.check("отказ без причины — 422 bad_refuz, поле motiv", (st, j["code"], j.get("field")),
                  (422, "bad_refuz", "motiv"))
        st, j = _act(c, pid, f"/plan/{iid}/status", {"to": "refuzat", "motiv": "nu vrea"})
        res.check("отказ с причиной — ok_refuz, вкладка отказов, прогресс 0/0",
                  (st, j["code"], j["data"]["plan"]["items"][0]["motiv"],
                   j["data"]["plan"]["default_tab"], j["data"]["plan"]["n_track"]),
                  (200, "ok_refuz", "nu vrea", "refuzat", 0))
        st, j = _act(c, pid, "/plan", {"procedure": "Coroană", "price": "700"})
        iid2 = j["data"]["plan"]["items"][0]["id"]
        st, j = _act(c, pid, f"/plan/{iid2}/delete")
        res.check("удалить нетронутую — можно, тихо", (st, j["code"], len(j["data"]["plan"]["items"])),
                  (200, "", 1))
        res.check("уже удалённая позиция — 404 plan_gone без фиши; строка одна",
                  (*_gone(c, pid, f"/plan/{iid2}/delete"),
                   sum(a["text"] == "Plan: - Coroană" for a in _feed(c, pid))),
                  (404, "plan_gone", True, False, 1))
        res.check("чужая позиция — 409", _act(c, pid, "/plan/9999/status", {"to": "in_lucru"})[0], 409)

        # ---- платежи ----
        st, j = _act(c, pid, "/payments", {"amount": "abc"})
        res.check("сумма не числом — 422, поле amount", (st, j["code"], j.get("field")),
                  (422, "bad_pay", "amount"))
        res.check("нулевая — 422", _act(c, pid, "/payments", {"amount": "0"})[1]["code"], "bad_pay")
        res.check("чужой метод — 422",
                  _act(c, pid, "/payments", {"amount": "10", "method": "crypto"})[1]["code"], "bad_pay")
        st, j = _act(c, pid, "/payments", {"amount": "250", "method": "card", "note": "avans"})
        res.check("платёж записан — ok_pay, аванс в сальдо и в шапке",
                  (st, j["code"], j["data"]["finance"]["sold"], j["data"]["finance"]["debt"],
                   j["data"]["finance"]["payments"][0]["amount"],
                   ("green", "Avans: 250 MDL") in [(pl["tone"], pl["text"]) for pl in j["data"]["hero"]["pills"]]),
                  (200, "ok_pay", {"kind": "plus", "amount": 250}, -250, 250, True))
        pay_id = j["data"]["finance"]["payments"][0]["id"]
        st, j = _act(c, pid, f"/payments/{pay_id}/delete")
        res.check("директор удаляет платёж — pay_del, след в летописи",
                  (st, j["code"], j["data"]["finance"]["payments"],
                   any("ștearsă" in a["text"] for a in j["data"]["activity"]["items"])),
                  (200, "pay_del", [], True))
        res.check("уже удалённый платёж — 404 pay_gone, а не «Plata a fost ștearsă»; строка одна",
                  (*_gone(c, pid, f"/payments/{pay_id}/delete"),
                   sum(a["kind"] == "pay_del" for a in _feed(c, pid))),
                  (404, "pay_gone", True, False, 1))

        # ---- документы ----
        r = c.post_file(f"/api/patients/{pid}/documents", "file", "rx.png", PNG, mime="image/png",
                        category="radiografie")
        j = _j(r)
        res.check("документ загружен — ok_doc, картинка у себя",
                  (r.status, j["code"], [(x["filename"], x["view"], x["category"]) for x in j["data"]["documents"]]),
                  (200, "ok_doc", [("rx.png", "img", "radiografie")]))
        doc_id = j["data"]["documents"][0]["id"]
        res.ok("файл отдаётся старым маршрутом", c.get(f"/admin/doc/{doc_id}").status == 200, "нет")
        r = c.post_file(f"/api/patients/{pid}/documents", "file", "gol.txt", b"", category="alt")
        res.check("пустой файл — 422 bad_doc", (r.status, _j(r)["code"], _j(r).get("field")),
                  (422, "bad_doc", "file"))
        r = c.post_file(f"/api/patients/{pid}/documents", "file", "virus.exe", b"MZ" + b"x" * 10)
        exe_id = _j(r)["data"]["documents"][0]["id"]
        j = _j(c.post_json(f"/api/documents/{exe_id}/open", {}))
        res.check("открыть .exe программой нельзя — opened false, причина ext",
                  (j["ok"], j["data"]), (True, {"opened": False, "reason": "ext"}))
        j = _j(c.post_json("/api/documents/9999/open", {}))
        res.check("чужой документ — opened false, missing", j["data"]["reason"], "missing")
        st, j = _act(c, pid, f"/documents/{exe_id}/delete")
        res.check("документ удалён — тихо, остался один", (st, [x["id"] for x in j["data"]["documents"]]),
                  (200, [doc_id]))

        # ---- бланки со статусом (01.10): tipărit — из летописи, semnat — скан своей категории ----
        forms = {f["key"]: f for f in j["data"]["forms"]}
        res.check("четыре бланка, ни один не печатался и не подписан",
                  (sorted(forms), [f["printed"] for f in forms.values()],
                   [f["signed"] for f in forms.values()]),
                  (["acord195", "acord_plan", "chestionar", "fisa043"], [""] * 4, [None] * 4))
        c.get(f"/admin/patient/{pid}/plan-acord")
        forms = {f["key"]: f for f in _j(c.get(f"/api/patients/{pid}"))["data"]["forms"]}
        res.ok("после печати acord informat — дата печати, остальные пусты",
               forms["acord_plan"]["printed"] and not forms["acord195"]["printed"],
               f"{forms['acord_plan']} / {forms['acord195']}")
        r = c.post_file(f"/api/patients/{pid}/documents", "file", "acord-semnat.png", PNG,
                        mime="image/png", category="acord_plan")
        j = _j(r)
        forms = {f["key"]: f for f in j["data"]["forms"]}
        signed_id = j["data"]["documents"][0]["id"]
        res.check("скан категории acord_plan = подписан; план после подписи не менялся",
                  (forms["acord_plan"]["signed"]["doc_id"], forms["acord_plan"]["stale"],
                   j["data"]["documents"][0]["category_label"]),
                  (signed_id, False, "Acord informat la plan — semnat"))
        st, j = _act(c, pid, "/plan", {"tooth": "26", "procedure": "Obturație 26", "price": "900"})
        forms = {f["key"]: f for f in j["data"]["forms"]}
        res.check("позиция, добавленная ПОСЛЕ подписи, — план изменён после подписи",
                  (st, forms["acord_plan"]["stale"], forms["acord_plan"]["n_active"]),
                  (200, True, 1))
        res.ok("опросник: статус — когда введён в фишу (выше в наборе), скана нет",
               forms["chestionar"]["filled"] != "" and forms["chestionar"]["signed"] is None
               and forms["chestionar"]["printed"] == "",
               f"{forms['chestionar']}")
        res.check("уже удалённый документ — 404 doc_gone без фиши; строка одна",
                  (*_gone(c, pid, f"/documents/{exe_id}/delete"),
                   sum(a["text"] == "Document șters: virus.exe" for a in _feed(c, pid))),
                  (404, "doc_gone", True, False, 1))

        # ---- запись ----
        j = _j(c.get(f"/api/patients/{pid}/slots?date={_d(3)}&doctor=d2&service=consult"))
        res.ok("часы врача на дату — список HH:MM", j["ok"] and len(j["data"]["slots"]) > 5
               and re.fullmatch(r"\d\d:\d\d", j["data"]["slots"][0]), f"{j}")
        res.check("врач не по услуге — пусто",
                  _j(c.get(f"/api/patients/{pid}/slots?date={_d(3)}&doctor=d3&service=long"))["data"]["slots"], [])
        st, j = _act(c, pid, "/appoint", {"date": "x", "time": "09:00", "doctor": "d2", "service": "consult"})
        res.check("кривая дата — 422 bad", (st, j["code"], j.get("field")), (422, "bad", "time"))
        st, j = _act(c, pid, "/appoint", {"date": _d(-1), "time": "09:00", "doctor": "d2", "service": "consult"})
        res.check("прошедший час — 409 past", (st, j["code"]), (409, "past"))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "09:00", "doctor": "d1", "service": "consult"})
        res.check("архивный врач — 409 bad_off", (st, j["code"]), (409, "bad_off"))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "23:00", "doctor": "d2", "service": "consult"})
        res.check("вне часов клиники — 422 outside", (st, j["code"]), (422, "outside"))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "09:00", "doctor": "d2", "service": "consult"})
        res.check("запись из фиши — ok, визит в истории и в KPI",
                  (st, j["code"], j["data"]["visits"]["n_total"], j["data"]["kpi"]["visits"],
                   j["data"]["hero"]["next"]["time"], j["data"]["visits"]["history"][0]["is_next"]),
                  (200, "ok", 1, 1, "09:00", True))
        st, j = _act(c, pid, "/appoint", {"date": _d(3), "time": "09:00", "doctor": "d3", "service": "consult"})
        res.check("тот же час у пациента — 409 dup", (st, j["code"]), (409, "dup"))
        res.ok("визит виден в журнале дня",
               "Act Test Nou" in [r["name"] for r in day_model(c, _d(3))["list"]], "нет")

        # ---- зуб из фиши и журнал доступа ----
        # ⚠️ После записи зуба фиша перечитывала себя GET-ом фиши, а он —
        # ОТКРЫТИЕ: каждое сохранение зуба добавляло в журнал доступа (закон
        # 195) ложное «Fișa deschisă». Свежая фиша едет в ответе самой записи.
        c.post_json("/api/patients", {"name": "Dinte Jurnal", "phone": "069555444"})
        pt = _pid(c, "069555444")
        _card(c, pt)
        res.check("фиша открыта один раз — одна строка журнала доступа", _opens(c, pt), 1)
        implant = {"state": "implant", "state0": "ok", "note": "", "doctor": "",
                   "surfaces": {}, "marks": []}
        r = c.post_json(f"/api/patients/{pt}/teeth/36?card=1", implant)
        j = _j(r)
        res.check("зуб из фиши: модель и свежая фиша в одном ответе (пилюля, летопись)",
                  (r.status, j["code"], j["data"]["teeth"]["36"]["state"],
                   [pl["text"] for pl in j["data"].get("card", {}).get("hero", {}).get("pills", [])],
                   j["data"].get("card", {}).get("activity", {}).get("items", [{}])[0].get("text"),
                   j["data"].get("card", {}).get("activity", {}).get("views")),
                  (200, "ok_card", "implant", ["Pacient activ", "1 implant"],
                   "Dinte 36: Implant", False))
        res.check("запись зуба из фиши журнал доступа не тронула", _opens(c, pt), 1)
        j = _j(c.post_json(f"/api/patients/{pt}/teeth/36?card=1&views=1",
                           {**implant, "state0": "implant"}))
        acts = j["data"].get("card", {}).get("activity", {})
        res.check("фиша в ответе — в режиме ленты запроса (?views=1: с просмотрами)",
                  (acts.get("views"), sum(a["kind"] == "view" for a in acts.get("items", [])),
                   _opens(c, pt)), (True, 1, 1))
        j = _j(c.post_json(f"/api/patients/{pt}/teeth/36", {**implant, "state0": "implant"}))
        res.check("без ?card=1 (детальная страница) — только модель, фиши в ответе нет",
                  (j["code"], "card" in j["data"]), ("ok_card", False))
        r = c.post_json(f"/api/patients/{pt}/teeth/99?card=1", implant)
        res.check("отказ записи — 422 без данных, журнал не тронут",
                  (r.status, "data" in _j(r), _opens(c, pt)), (422, False, 1))
        _card(c, pt)
        res.check("настоящее открытие фиши пишется, как прежде", _opens(c, pt), 2)

        # ---- стирание ----
        st, j = _act(c, pid, "/erase", {"confirm": "nu"})
        res.check("без слова — 422 bad_erase, поле confirm", (st, j["code"], j.get("field")),
                  (422, "bad_erase", "confirm"))
        st, j = _act(c, pid, "/erase", {"confirm": "sterg"})
        res.check("фиша с лечением — обезличена, ok_anon",
                  (st, j["code"], j["data"]["profile"]["phone"], j["data"]["profile"]["idnp"]),
                  (200, "ok_anon", "", ""))
        # 17.10 (посторонний разбор): будущая запись обезличенного висела в
        # «De confirmat — sunați» без телефона и держала час врача
        row = next(r for r in day_model(c, _d(3))["list"]
                   if r["time"] == "09:00" and not r["is_note"])
        res.check("будущая запись обезличенного отменена: час свободен, звонить некому",
                  (row["status"], j["data"]["visits"]["live"], j["data"]["hero"]["next"]),
                  ("cancelled", [], None))
        c.post_json("/api/patients", {"name": "Doar Contact", "phone": "069555222"})
        pid2 = _pid(c, "069555222")
        st, j = _act(c, pid2, "/erase", {"confirm": "STERG"})
        res.check("контакт без лечения — удалён, адрес списка",
                  (st, j["code"], j["data"]), (200, "ok_del", {"url": "/admin/search?msg=ok_del"}))
        res.check("фиши больше нет — 404", c.get(f"/api/patients/{pid2}").status, 404)

        # ---- охрана ----
        anon = Client(s.url)
        res.check("без входа действие — 401", anon.post_json(f"/api/patients/{pid}/alerts", {}).status, 401)
        res.check("чужой Origin — 403",
                  c.post_json(f"/api/patients/{pid}/alerts", {"kind": "info", "text": "x"},
                              headers={"Origin": "http://evil.example"}).status, 403)
        res.check("не JSON — 422", c.post(f"/api/patients/{pid}/profile", name="X").status, 422)

    # право удалять платёж — только у директора (ветка PIN-файла, как у клиники)
    s = Server(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana", "role": "receptie", "pin": "2222"})
        boss.post_json("/api/patients", {"name": "Bani Test", "phone": "069555333"})
        pid = _pid(boss, "069555333")
        rec = Client(s.url)
        rec.post("/admin/login", password="2222", next="/admin")
        st, j = _act(rec, pid, "/payments", {"amount": "100", "method": "numerar"})
        res.check("регистратура записывает платёж", (st, j["code"], j["data"]["finance"]["can_delete"]),
                  (200, "ok_pay", False))
        # ⚠️ автор события — ИМЯ вошедшего и через JSON: движок опознаёт
        # человека на /api так же, как на /admin (main._identify); иначе
        # летопись подписывала бы действия API «recepție», и журнал по 195-му
        # называл бы не того, кто принял деньги
        res.check("летопись подписана именем вошедшего, а не «recepție»",
                  (j["data"]["activity"]["items"][0]["who"],
                   j["data"]["finance"]["payments"][0]["taken_by"]), ("Ana", "Ana"))
        pay_id = j["data"]["finance"]["payments"][0]["id"]
        st, j = _act(rec, pid, f"/payments/{pay_id}/delete")
        res.check("регистратура не удаляет — 403 no_access", (st, j["code"]), (403, "no_access"))
        st, j = _act(boss, pid, f"/payments/{pay_id}/delete")
        res.check("директор удаляет — pay_del", (st, j["code"], j["data"]["finance"]["can_delete"]),
                  (200, "pay_del", True))
        st, j = _act(rec, pid, "/alerts", {"kind": "allergy", "text": "Penicilină"})
        st, j = _act(rec, pid, f"/alerts/{j['data']['alerts'][0]['id']}/delete")
        res.check("снятие предупреждения подписано именем снявшего (ветка PIN, как у клиники)",
                  [(a["text"], a["who"]) for a in j["data"]["activity"]["items"] if a["kind"] == "alert_del"],
                  [("Atenționare ștearsă: Penicilină", "Ana")])
        res.ok("регистратуре фиша открыта", _card(rec, pid)["name"] == "Bani Test", "закрыта")


def suite_switch(res: Result) -> None:
    """Фиша — узел React (старая страница снята 13.10): номер фиши и режим
    ленты в той же рамке, плашка сервера по `?msg=`, право стоит и на
    странице."""
    with Server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Flag Card", "069777000")
        res.ok("без флага — тоже React (старой фиши нет)",
               '<div id="root" data-screen="patient_card"' in c.get(f"/admin/patient/{pid}").body,
               "узла нет")

    s = Server()
    with s:
        c = Client(s.url).login()
        pid = new_patient(c, "Flag Card", "069777000")
        page = c.get(f"/admin/patient/{pid}").body
        # подпись раздела печатает сам экран (08.10, крошки) — сервер отдаёт пустую
        res.ok("узел React в рамке фиши",
               '<div id="root" data-screen="patient_card"' in page
               and f"fișa pacientului · #{pid}" not in page and "/static/js/bundle.js?v=" in page,
               "узла нет")
        params = json.loads(page.split("data-params=\"", 1)[1].split("\"", 1)[0]
                            .replace("&quot;", '"'))
        res.check("номер фиши — параметром узла, без режима ленты", params, {"pid": str(pid)})
        page_v = c.get(f"/admin/patient/{pid}?views=1").body
        params = json.loads(page_v.split("data-params=\"", 1)[1].split("\"", 1)[0]
                            .replace("&quot;", '"'))
        res.check("?views=1 — режим ленты параметром", params, {"pid": str(pid), "views": "1"})
        res.ok("старой разметки нет", "class='hero'" not in page and "id='plan'" not in page
               and "apptdlg" not in page, "две разметки")
        res.ok("не внутри #live", 'id="live"' not in page, "живой кусок")
        res.ok("?msg= на React-странице — плашка сервера",
               "dp_toast" in c.get(f"/admin/patient/{pid}?msg=ok_card").body, "плашки нет")
        res.check("чужая фиша — на список", c.get("/admin/patient/9999").status, 303)
        r = c.post_json(f"/api/patients/{pid}/teeth/11", {"state": "carie", "doctor": "Dr. Activ Doi",
                                                         "surfaces": []})
        res.ok("запись зуба через API доехала до модели одонтограммы",
               r.status == 200
               and _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]["teeth"]["11"]["state"] == "carie",
               f"{r!r}")
        res.check("профиль правится через API",
                  _act(c, pid, "/profile", {"name": "Flag Card", "phone": "069777000"})[0], 200)
        res.check("без входа React-страница закрыта", Client(s.url).get(f"/admin/patient/{pid}").status, 303)

    s = Server(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana", "role": "receptie", "pin": "2222"})
        pid = new_patient(boss, "Flag Pin", "069777111")
        rec = Client(s.url)
        rec.post("/admin/login", password="2222", next="/admin")
        res.ok("регистратуре фиша открыта и по PIN",
               'data-screen="patient_card"' in rec.get(f"/admin/patient/{pid}").body, "закрыта")


def suite_doc_outlives_shell(res: Result) -> None:
    """Стенд без оболочки (18.10, 2.0.3): документ, открытый из фиши, переживает
    закрытие DentPilot.

    Оболочка Tauri держит движок в «задании» Windows с KILL_ON_JOB_CLOSE, и
    прежний `os.startfile` рождал Word ребёнком движка в задании: закрыл
    DentPilot — Windows погасила Word с несохранённой правкой. Здесь то же без
    оболочки (`jobstand`): задание с пределами из `engine.rs`, «движок» в нём
    открывает документ НАСТОЯЩИМ `core.shellopen.open_file` из исходников,
    задание закрывается — и обработчик обязан стучать дальше. Обработчик —
    `.vbs` (wscript.exe, классическая программа, как Word). Имя с запятой и без
    пробелов — ловушка explorer (`shellopen`: путь только в кавычках).

    Три прохода: пределы оболочки; задание без права выхода (оболочка до
    2.0.2, задание харнесса) — флаг отвергнут, explorer без него; и контроль —
    прежний `os.startfile` в том же задании обязан ПОГИБНУТЬ: иначе стенд
    болезни не видит, и зелёное двух первых ничего не значит."""
    import os
    import sys
    import tempfile
    import time
    from pathlib import Path

    import jobstand
    from harness import _rmtree_settled

    if sys.platform != "win32":
        res.ok("не Windows — задания оболочки нет", True, "")
        return
    if (why := jobstand.doc_stand_missing()):
        # ⚠️ ВСЛУХ: зелёная строка без стенда читалась бы как «проверено»
        res.ok(f"ПРОПУЩЕНО: стенд документа — {why}", True, "")
        return
    root = Path(__file__).resolve().parents[1]
    try:
        limits = jobstand.shell_limits(root / "shell" / "src" / "engine.rs")
    except (OSError, ValueError) as e:
        res.ok("пределы задания оболочки читаются из engine.rs", False, str(e))
        return
    breakaway = jobstand.LIMITS["JOB_OBJECT_LIMIT_BREAKAWAY_OK"]
    python = getattr(sys, "_base_executable", sys.executable)
    passes = (
        ("пределы оболочки", limits, "shellopen", True),
        ("задание без права выхода", limits & ~breakaway, "shellopen", True),
        ("контроль: прежний os.startfile", limits, "startfile", False),
    )
    td = Path(tempfile.mkdtemp(prefix="dp_docjob_"))
    try:
        engine_py = td / "engine.py"
        engine_py.write_text(jobstand.OPEN_ENGINE, encoding="utf-8")
        for i, (name, flags, how, survives) in enumerate(passes):
            lab = td / str(i)
            lab.mkdir()
            doc = lab / "Radiografie,12.10.vbs"
            doc.write_text(jobstand.DOC_VBS.format(dir=lab), encoding="utf-16")
            said = lab / "said.txt"
            job = jobstand.Job(flags)
            engine = None
            try:
                engine = jobstand.start([python, str(engine_py), str(root / "bot"), how,
                                         str(doc), str(said)], suspended=True)
                job.add(engine)            # в задании до первой инструкции, как у `Engine::start`
                engine.resume()
                end = time.monotonic() + 20
                while not jobstand.beats(lab) and time.monotonic() < end:
                    time.sleep(0.05)
                text = said.read_text(encoding="utf-8") if said.exists() else "—"
                if not res.ok(f"{name}: документ открылся", jobstand.beats(lab) > 0,
                              f"обработчик не стучит 20 с; движок: {text}"):
                    continue
                if how != "startfile":
                    res.check(f"{name}: открытие без ошибки", text, "opened")
                job.close()                # оболочка закрылась
                res.ok(f"{name}: движок погашен вместе с заданием", engine.wait(5),
                       "задание не гасит — стенд ничего не доказал")
                time.sleep(0.6)
                before = jobstand.beats(lab)
                time.sleep(1.0)
                alive = jobstand.beats(lab) > before
                if survives:
                    res.ok(f"{name}: документ пережил закрытие DentPilot", alive,
                           "обработчик замолчал вместе с заданием — Word погиб бы "
                           "с несохранённой правкой")
                else:
                    res.ok("контроль: os.startfile гибнет вместе с заданием — стенд видит болезнь",
                           not alive, "обработчик os.startfile пережил задание: стенд "
                           "не отличает исправное от сломанного")
            finally:
                job.close()
                if engine is not None:
                    engine.kill()
                    engine.close()
                (lab / "stop").write_text("", encoding="ascii")
                # выживший уходит сам по `stop`; его папку не снести, пока он жив
                end = time.monotonic() + 5
                while jobstand.beats(lab) and not (lab / "done").exists() and time.monotonic() < end:
                    time.sleep(0.05)
    finally:
        _rmtree_settled(td, budget=10.0)
