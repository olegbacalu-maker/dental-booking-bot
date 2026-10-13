"""Дневник визита «Consultație» (C19): `GET/POST /api/visits/{aid}` —
страница визита данными; адрес `/admin/visit/{aid}` отдаёт узел React в рамке
при любом `ui.react` (старая страница снята 13.10 — её записанные руками
ожидания, `suite_pin`, перенесены в `suite_api` значениями).

`test_visit.py` уже держит поведение записи (пустая не пишется, отменённому
не пишется, привязка позиций плана, закон 195). Здесь то, чего там нет: шапка
визита с комментарием стойки, адрес возврата (только журнал, иначе фиша),
графы и шаблоны как данные, открытые позиции без отказов и с пометкой «în
lucru», строка авторства с «actualizat», страница без формы у отменённого
и неявившегося.
"""
import json
import re
from datetime import timedelta

from harness import Client, Result, Server, clinic_today, day_model, pid_by_phone


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
    """Пациент с четырьмя визитами и планом в трёх статусах: прошлый
    подтверждённый с комментарием стойки и дневником, к которому привязана
    позиция плана; отменённый с записью, сделанной до отмены; неявившийся
    без записи; будущий без записи."""
    s = {}

    def visit(day: int, time: str, doc: str, svc: str = "consult") -> int:
        c.post_json("/api/schedule/appointments", {"date": _d(day), "time": time,
                                                  "doctor": doc, "service": svc,
                                                  "name": "Vizita Test", "phone": "069123123"})
        return _aid(c, _d(day))

    s["a_rec"] = visit(-2, "10:00", "d2")
    pid = s["pid"] = _pid(c, "069123123")
    c.post_json(f"/api/schedule/appointments/{s['a_rec']}/comment", {"comment": "de sunat înainte"})
    c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Obturație 26", "tooth": "26",
                                             "price": "500"})
    c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Detartraj", "price": "300"})
    r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Implant 36", "tooth": "36",
                                                 "price": "9000"})
    ids = sorted(it["id"] for it in _j(r)["data"]["plan"]["items"])
    s["p_done"], s["p_lucru"], s["p_refuz"] = ids
    c.post_json(f"/api/patients/{pid}/plan/{s['p_lucru']}/status", {"to": "in_lucru"})
    c.post_json(f"/api/patients/{pid}/plan/{s['p_refuz']}/status", {"to": "refuzat",
                                                                   "motiv": "nu vrea"})
    c.post_json(f"/api/visits/{s['a_rec']}", {"acuze": "Durere la rece",
                                             "diagnostic": "Pulpită 26", "tratament": "Trat",
                                             "done": [s["p_done"]]})
    s["a_canc"] = visit(-1, "11:00", "d3", "hygiene")
    c.post_json(f"/api/visits/{s['a_canc']}", {"acuze": "Igienă"})
    c.post_json(f"/api/schedule/appointments/{s['a_canc']}/status", {"to": "cancelled"})
    s["a_noshow"] = visit(-1, "12:00", "d2")
    c.post_json(f"/api/schedule/appointments/{s['a_noshow']}/status", {"to": "noshow"})
    s["a_new"] = visit(1, "12:00", "d2")
    return s


def suite_api(res: Result) -> None:
    """`GET /api/visits/{aid}` на засеянных визитах — значениями, записанными
    руками; POST — коды MSG_BANNER."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/visits/1").status, 401)
        c = Client(s.url).login()
        res.check("чужой визит — 404", c.get("/api/visits/777").status, 404)
        sd = _seed(c)
        pid, a = sd["pid"], sd["a_rec"]
        d = _j(c.get(f"/api/visits/{a}?back=/admin/all?date={_d(-2)}"))["data"]
        res.check("состав ответа", sorted(d),
                  sorted(["appt", "record", "editable", "note", "fields", "templates", "plan", "back"]))
        ap = d["appt"]
        res.check("шапка: пациент, услуга, врач, статус словом, комментарий стойки",
                  [ap["patient"], ap["service"], ap["doctor"], ap["status_label"], ap["comment"]],
                  ["Vizita Test", "Consultație", "Dr. Activ Doi", "programată", "de sunat înainte"])
        res.check("визит: номер, дата, пациент, статус кодом",
                  (ap["id"], ap["when"], ap["patient_id"], ap["status"]),
                  (a, f"{_dmy(-2)} 10:00", pid, "confirmed"))
        res.check("запись: значения граф",
                  {k: d["record"][k] for k in ("acuze", "examen", "diagnostic", "tratament",
                                               "recomandari")},
                  {"acuze": "Durere la rece", "examen": "", "diagnostic": "Pulpită 26",
                   "tratament": "Trat", "recomandari": ""})
        res.ok("запись: создана, кем, без правки",
               re.fullmatch(r"\d\d\.\d\d\.\d{4} \d\d:\d\d", d["record"]["created"])
               and d["record"]["author"] == "Director" and d["record"]["updated"] == "",
               f"{d['record']}")
        res.check("графы дневника по порядку бланка", [f["label"] for f in d["fields"]],
                  ["Acuze / motivul prezentării", "Examen obiectiv", "Diagnostic",
                   "Tratament efectuat", "Recomandări"])
        res.check("графы: id, строки, подсказка", d["fields"][0],
                  {"id": "acuze", "label": "Acuze / motivul prezentării", "rows": 2,
                   "placeholder": "Ce acuză pacientul…"})
        res.check("шаблоны: шесть, по порядку, с подписями",
                  [(t["id"], t["label"]) for t in d["templates"]],
                  [("consult", "Consultație"), ("obturatie", "Obturație"),
                   ("canal", "Tratament de canal"), ("extractie", "Extracție"),
                   ("detartraj", "Detartraj / igienizare"), ("control", "Control")])
        tpl = {t["id"]: t["values"] for t in d["templates"]}
        res.check("шаблоны: тексты по графам, пустая графа — пусто (заполняется только пустое)",
                  (tpl["obturatie"]["diagnostic"], tpl["consult"]["diagnostic"], sorted(tpl["canal"])),
                  ("Carie dentară, dintele __.", "",
                   sorted(["acuze", "examen", "diagnostic", "tratament", "recomandari"])))
        res.check("план: выполненное на визите словами; к отметке — только активные, «în lucru» помечено",
                  ([x["text"] for x in d["plan"]["linked"]],
                   [(x["id"], x["text"], x["in_lucru"]) for x in d["plan"]["open"]]),
                  (["dinte 26 · Obturație 26 · 500 MDL"], [(sd["p_lucru"], "Detartraj · 300 MDL", True)]))
        res.check("можно писать, предупреждения нет, адрес возврата принят",
                  (d["editable"], d["note"], d["back"]), (True, "", f"/admin/all?date={_d(-2)}"))
        res.check("чужой адрес возврата — фиша",
                  _j(c.get(f"/api/visits/{a}?back=http://evil.example"))["data"]["back"],
                  f"/admin/patient/{pid}")
        dc = _j(c.get(f"/api/visits/{sd['a_canc']}"))["data"]
        res.check("отменённый: писать нельзя, предупреждение словами страницы, запись есть",
                  (dc["editable"], "nu se completează" in dc["note"], dc["record"]["acuze"],
                   dc["appt"]["status_label"]), (False, True, "Igienă", "anulată"))
        dn = _j(c.get(f"/api/visits/{sd['a_noshow']}"))["data"]
        res.check("неявка: без записи, писать нельзя", (dn["record"], dn["editable"]), (None, False))
        dw = _j(c.get(f"/api/visits/{sd['a_new']}"))["data"]
        res.check("будущий: без записи, можно писать, план открыт",
                  (dw["record"], dw["editable"], len(dw["plan"]["open"]), dw["plan"]["linked"]),
                  (None, True, 1, []))

        # ---- запись через JSON ----
        r = c.post_json(f"/api/visits/{sd['a_new']}", {"acuze": "  ", "examen": ""})
        res.check("пустая запись — 422 bad_visit", (r.status, _j(r)["code"]), (422, "bad_visit"))
        r = c.post_json(f"/api/visits/{sd['a_canc']}", {"acuze": "x"})
        res.check("отменённому — 409 bad_vst", (r.status, _j(r)["code"]), (409, "bad_vst"))
        r = c.post_json(f"/api/visits/{sd['a_new']}",
                        {"acuze": "Control", "tratament": "Detartraj efectuat",
                         "done": [sd["p_lucru"], sd["p_refuz"], "zzz"], "back": f"/admin/all?date={_d(1)}"})
        d = _j(r)
        res.check("запись сохранена — ok_visit, свежая страница, адрес возврата",
                  (r.status, d["code"], d["data"]["record"]["tratament"], d["data"]["back"],
                   d["data"]["record"]["author"]),
                  (200, "ok_visit", "Detartraj efectuat", f"/admin/all?date={_d(1)}", "Director"))
        res.check("отмеченная активная позиция выполнена на визите; отказ и мусор пропущены",
                  ([x["text"] for x in d["data"]["plan"]["linked"]], d["data"]["plan"]["open"]),
                  (["Detartraj · 300 MDL"], []))
        plan = {it["procedure"]: it for it in _j(c.get(f"/api/patients/{pid}"))["data"]["plan"]["items"]}
        res.check("в фише позиция финализирована, отказ остался отказом",
                  (plan["Detartraj"]["status"], plan["Implant 36"]["status"], plan["Implant 36"]["motiv"]),
                  ("finalizat", "refuzat", "nu vrea"))
        res.check("правка видна при новом открытии страницы",
                  _j(c.get(f"/api/visits/{sd['a_new']}"))["data"]["record"]["tratament"],
                  "Detartraj efectuat")
        r = c.post_json(f"/api/visits/{sd['a_new']}", {"acuze": "Control", "tratament": "Detartraj efectuat"})
        res.ok("повторная запись — «actualizat», тот же текст",
               _j(r)["data"]["record"]["updated"] != "" and _j(r)["data"]["record"]["tratament"] == "Detartraj efectuat",
               r.body[:200])
        res.check("длина режется до 2000, как у формы",
                  len(_j(c.post_json(f"/api/visits/{sd['a_new']}", {"acuze": "x" * 2500}))["data"]["record"]["acuze"]),
                  2000)
        res.check("не JSON — 422", c.post(f"/api/visits/{sd['a_new']}", acuze="X").status, 422)
        res.check("чужой Origin — 403",
                  c.post_json(f"/api/visits/{sd['a_new']}", {"acuze": "x"},
                              headers={"Origin": "http://evil.example"}).status, 403)
        res.check("чужой визит — 404", c.post_json("/api/visits/777", {"acuze": "x"}).status, 404)

    # ветка PIN-файла: дневник открыт любой вошедшей роли, как страница
    s = Server(env={"ADMIN_KEY": ""})
    with s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana", "role": "receptie", "pin": "2222"})
        boss.post_json("/api/schedule/appointments", {"date": _d(1), "time": "09:00",
                                                     "doctor": "d2", "service": "consult",
                                                     "name": "Pin Vizita", "phone": "069555999"})
        aid = _aid(boss, _d(1))
        rec = Client(s.url)
        rec.post("/admin/login", password="2222", next="/admin")
        r = rec.post_json(f"/api/visits/{aid}", {"acuze": "Control"})
        res.check("регистратура пишет дневник, автор — её имя",
                  (r.status, _j(r)["code"], _j(r)["data"]["record"]["author"]), (200, "ok_visit", "Ana"))


def _server_with_flag(env: dict | None = None) -> Server:
    s = Server(env=env)
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["visit"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_switch(res: Result) -> None:
    """Дневник визита — React при любом `ui.react` (старая страница снята
    13.10): узел с номером визита и адресом возврата, `?ui=legacy` отдаёт тот
    же React."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": _d(1), "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Flag Vizita", "phone": "069888000"})
        aid = _aid(c, _d(1))
        res.ok("без флага — тоже React (старой страницы нет)",
               '<div id="root" data-screen="visit"' in c.get(f"/admin/visit/{aid}").body, "узла нет")

    s = _server_with_flag()
    with s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": _d(1), "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Flag Vizita", "phone": "069888000"})
        aid = _aid(c, _d(1))
        pid = _pid(c, "069888000")
        page = c.get(f"/admin/visit/{aid}?back=/admin/all?date={_d(1)}").body
        res.ok("узел React в рамке визита",
               '<div id="root" data-screen="visit"' in page and f"consultație · vizita #{aid}" in page
               and "/static/js/bundle.js?v=" in page, "узла нет")
        params = json.loads(page.split("data-params=\"", 1)[1].split("\"", 1)[0].replace("&quot;", '"'))
        res.check("номер визита и адрес возврата — параметрами узла",
                  params, {"aid": str(aid), "back": f"/admin/all?date={_d(1)}"})
        params = json.loads(c.get(f"/admin/visit/{aid}").body.split("data-params=\"", 1)[1]
                            .split("\"", 1)[0].replace("&quot;", '"'))
        res.check("без ?back — возврат в фишу", params["back"], f"/admin/patient/{pid}")
        params = json.loads(c.get(f"/admin/visit/{aid}?back=http://evil.example").body
                            .split("data-params=\"", 1)[1].split("\"", 1)[0].replace("&quot;", '"'))
        res.check("чужой ?back — назад в фишу, а не наружу", params["back"], f"/admin/patient/{pid}")
        res.ok("старой формы нет", "vf_acuze" not in page and "applyTpl" not in page, "две разметки")
        res.ok("?ui=legacy — тот же React",
               'data-screen="visit"' in c.get(f"/admin/visit/{aid}?ui=legacy").body,
               "старая страница вернулась")
        res.ok("?msg= — плашка сервера", "dp_toast" in c.get(f"/admin/visit/{aid}?msg=ok_visit").body, "нет")
        res.check("чужой визит — в журнал", c.get("/admin/visit/9999").status, 303)
        res.check("без входа React-страница закрыта", Client(s.url).get(f"/admin/visit/{aid}").status, 303)
