"""Дневник визита «Consultație» (C19): старая страница записана как эталон,
`GET/POST /api/visits/{aid}` повторяют её данными, флаг `visit` отдаёт узел
React в той же рамке.

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

from harness import Client, Result, Server, clinic_today


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _dmy(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return int(c.get(f"/admin/search?q={phone}").body.split(
        "<tr id='plr", 1)[1].split("'", 1)[0])


def _aid(c: Client, day: str) -> int:
    """id последней записи дня — со страницы дня, как в test_visit."""
    return int(re.findall(r"/admin/status/(\d+)", c.get(f"/admin/all?date={day}").body)[-1])


def _seed(c: Client) -> dict:
    """Пациент с четырьмя визитами и планом в трёх статусах: прошлый
    подтверждённый с комментарием стойки и дневником, к которому привязана
    позиция плана; отменённый с записью, сделанной до отмены; неявившийся
    без записи; будущий без записи."""
    s = {}

    def visit(day: int, time: str, doc: str, svc: str = "consult") -> int:
        c.post("/admin/add", adate=_d(day), atime=time, adoctor=doc, aservice=svc,
               aname="Vizita Test", aphone="069123123", back="/admin/all")
        return _aid(c, _d(day))

    s["a_rec"] = visit(-2, "10:00", "d2")
    pid = s["pid"] = _pid(c, "069123123")
    c.post(f"/admin/comment/{s['a_rec']}", comment="de sunat înainte", back="/admin/all")
    c.post(f"/admin/patient/{pid}/plan", procedure="Obturație 26", tooth="26", price="500")
    c.post(f"/admin/patient/{pid}/plan", procedure="Detartraj", price="300")
    c.post(f"/admin/patient/{pid}/plan", procedure="Implant 36", tooth="36", price="9000")
    ids = sorted({int(x) for x in re.findall(r"/plan/(\d+)/status",
                                              c.get(f"/admin/patient/{pid}").body)})
    s["p_done"], s["p_lucru"], s["p_refuz"] = ids
    c.post(f"/admin/patient/{pid}/plan/{s['p_lucru']}/status", to="in_lucru")
    c.post(f"/admin/patient/{pid}/plan/{s['p_refuz']}/status", to="refuzat", motiv="nu vrea")
    c.post(f"/admin/visit/{s['a_rec']}", acuze="Durere la rece", diagnostic="Pulpită 26",
           tratament="Trat", done=str(s["p_done"]))
    s["a_canc"] = visit(-1, "11:00", "d3", "hygiene")
    c.post(f"/admin/visit/{s['a_canc']}", acuze="Igienă")
    c.post(f"/admin/status/{s['a_canc']}", to="cancelled", back="/admin/all")
    s["a_noshow"] = visit(-1, "12:00", "d2")
    c.post(f"/admin/status/{s['a_noshow']}", to="noshow", back="/admin/all")
    s["a_new"] = visit(1, "12:00", "d2")
    return s


def _rows(page: str) -> list[tuple[str, str]]:
    head = page.split("<div class='vwrap'>", 1)[1].split("Jurnalul", 1)[0]
    return [(k, re.sub(r"<[^>]+>", "", v).strip())
            for k, v in re.findall(r"<div class='frow'><span>([^<]*)</span><span class='v'>(.*?)</span></div>",
                                   head, re.S)]


def _labels(page: str) -> list[str]:
    return re.findall(r"<label class='dlab' for='vf_\w+'>([^<]*)</label>", page)


def _values(page: str) -> dict[str, str]:
    return dict(re.findall(r"<textarea id='vf_(\w+)'[^>]*>(.*?)</textarea>", page, re.S))


def _open(page: str) -> list[tuple[int, str]]:
    return [(int(i), re.sub(r"<[^>]+>", "", t).strip()) for i, t in
            re.findall(r"<input type='checkbox' name='done' value='(\d+)'><span>(.*?)</span>", page, re.S)]


def _linked(page: str) -> list[str]:
    return [re.sub(r"<svg.*?</svg> ", "", t) for t in re.findall(r"<div class='vdone'>(.*?)</div>", page, re.S)]


def suite_pin(res: Result) -> None:
    """Старая страница визита — эталон, записанный руками."""
    with Server() as s:
        c = Client(s.url).login()
        sd = _seed(c)
        pid, a = sd["pid"], sd["a_rec"]
        page = c.get(f"/admin/visit/{a}?back=/admin/all?date={_d(-2)}").body
        res.ok("шапка: дата, номер визита", f"· {_dmy(-2)} 10:00 · vizita #{a}</small>" in page, "шапка не та")
        res.check("шапка: пациент ссылкой, услуга, врач, статус словом, комментарий стойки",
                  _rows(page),
                  [("Pacient", "Vizita Test"), ("Serviciu", "Consultație"), ("Medic", "Dr. Activ Doi"),
                   ("Status", "confirmată"), ("Comentariu recepție", "de sunat înainte")])
        res.ok("пациент ведёт в фишу", f"<a href='/admin/patient/{pid}'>Vizita Test</a>" in page, "нет ссылки")
        res.ok("«Înapoi» — адрес из ?back, если он в журнале",
               f"<a href='/admin/all?date={_d(-2)}'>" in page, "back не принят")
        res.ok("чужой ?back — назад в фишу",
               f"<a href='/admin/patient/{pid}'>" in
               c.get(f"/admin/visit/{a}?back=http://evil.example").body.split("Înapoi", 1)[0],
               "открытый редирект")
        res.check("шаблоны: шесть кнопок по порядку",
                  re.findall(r"onclick=\"applyTpl\('(\w+)'\)\">([^<]*)</button>", page),
                  [("consult", "Consultație"), ("obturatie", "Obturație"), ("canal", "Tratament de canal"),
                   ("extractie", "Extracție"), ("detartraj", "Detartraj / igienizare"), ("control", "Control")])
        tpl = json.loads(re.search(r"const TPL = (.*?);\n", page).group(1))
        res.ok("шаблон заполняет только пустое — правило в скрипте, тексты в TPL",
               "!el.value.trim()" in page and tpl["obturatie"]["diagnostic"] == "Carie dentară, dintele __."
               and tpl["consult"]["diagnostic"] == "", "TPL не тот")
        res.check("графы дневника по порядку бланка", _labels(page),
                  ["Acuze / motivul prezentării", "Examen obiectiv", "Diagnostic",
                   "Tratament efectuat", "Recomandări"])
        res.check("значения записи в полях", _values(page),
                  {"acuze": "Durere la rece", "examen": "", "diagnostic": "Pulpită 26",
                   "tratament": "Trat", "recomandari": ""})
        res.check("выполнено на визите — привязанная позиция словами",
                  _linked(page), ["dinte 26 · Obturație 26 · 500 MDL"])
        res.check("к отметке — только активные, без отказа и без выполненной, «în lucru» помечено",
                  _open(page), [(sd["p_lucru"], "Detartraj · 300 MDL — în lucru")])
        res.ok("авторство: записано, кем", re.search(r"Înregistrat: \d\d\.\d\d\.\d{4} \d\d:\d\d · de Director", page)
               is not None and "actualizat" not in page, "нет строки авторства")
        c.post(f"/admin/visit/{a}", acuze="Durere la rece", diagnostic="Pulpită 26 acută")
        page = c.get(f"/admin/visit/{a}").body
        res.ok("после правки — «actualizat»", " · actualizat: " in page, "нет отметки правки")

        page = c.get(f"/admin/visit/{sd['a_canc']}").body
        res.ok("отменённый: без формы, с предупреждением и записью для чтения",
               "vf_acuze" not in page and "nu se completează" in page
               and "<p class='vsec'><b>Acuze / motivul prezentării:</b><br>Igienă</p>" in page
               and "Înregistrat:" in page and "Examen obiectiv:" not in page, "не то")
        page = c.get(f"/admin/visit/{sd['a_noshow']}").body
        res.ok("неявка без записи: предупреждение, ни полей, ни авторства",
               "nu se completează" in page and "vf_acuze" not in page and "Înregistrat:" not in page
               and "class='vsec'" not in page, "не то")
        page = c.get(f"/admin/visit/{sd['a_new']}").body
        res.ok("будущий без записи: пустая форма, без авторства и без «выполнено»",
               all(v == "" for v in _values(page).values()) and "Înregistrat:" not in page
               and "Efectuate la această vizită" not in page and _open(page), "не то")


def suite_api(res: Result) -> None:
    """`GET /api/visits/{aid}` повторяет страницу; POST — те же коды, что у формы."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/visits/1").status, 401)
        c = Client(s.url).login()
        res.check("чужой визит — 404", c.get("/api/visits/777").status, 404)
        sd = _seed(c)
        pid, a = sd["pid"], sd["a_rec"]
        page = c.get(f"/admin/visit/{a}?back=/admin/all?date={_d(-2)}").body
        d = _j(c.get(f"/api/visits/{a}?back=/admin/all?date={_d(-2)}"))["data"]
        res.check("состав ответа", sorted(d),
                  sorted(["appt", "record", "editable", "note", "fields", "templates", "plan", "back"]))
        ap = d["appt"]
        res.check("визит: те же значения, что в шапке",
                  [ap["patient"], ap["service"], ap["doctor"], ap["status_label"], ap["comment"]],
                  [v for _k, v in _rows(page)])
        res.check("визит: номер, дата, пациент, статус кодом",
                  (ap["id"], ap["when"], ap["patient_id"], ap["status"]),
                  (a, f"{_dmy(-2)} 10:00", pid, "confirmed"))
        res.check("запись: те же значения, что в полях",
                  {k: d["record"][k] for k in _values(page)}, _values(page))
        res.ok("запись: создана, кем, без правки",
               re.fullmatch(r"\d\d\.\d\d\.\d{4} \d\d:\d\d", d["record"]["created"])
               and d["record"]["author"] == "Director" and d["record"]["updated"] == "",
               f"{d['record']}")
        res.check("графы — те же подписи в том же порядке", [f["label"] for f in d["fields"]], _labels(page))
        res.check("графы: id, строки, подсказка", d["fields"][0],
                  {"id": "acuze", "label": "Acuze / motivul prezentării", "rows": 2,
                   "placeholder": "Ce acuză pacientul…"})
        tpl = json.loads(re.search(r"const TPL = (.*?);\n", page).group(1))
        res.check("шаблоны — те же id, подписи и тексты",
                  [(t["id"], t["label"]) for t in d["templates"]],
                  re.findall(r"onclick=\"applyTpl\('(\w+)'\)\">([^<]*)</button>", page))
        res.check("шаблоны: тексты байт в байт", {t["id"]: t["values"] for t in d["templates"]}, tpl)
        res.check("план: выполненное и открытое — как на странице",
                  ([x["text"] for x in d["plan"]["linked"]],
                   [(x["id"], x["text"], x["in_lucru"]) for x in d["plan"]["open"]]),
                  (_linked(page), [(sd["p_lucru"], "Detartraj · 300 MDL", True)]))
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
        fisa = c.get(f"/admin/patient/{pid}").body
        res.ok("в фише позиция финализирована, отказ остался отказом",
               "data-st='finalizat'" in fisa.split("Detartraj", 1)[0][-300:]
               and "<em class='pmotiv'>nu vrea</em>" in fisa, "план не тот")
        res.ok("старая страница видит запись API",
               ">Detartraj efectuat</textarea>" in c.get(f"/admin/visit/{sd['a_new']}").body, "не видит")
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
        boss.post("/admin/users/save", uid="ana", name="Ana", role="receptie", pin="2222")
        boss.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2", aservice="consult",
                  aname="Pin Vizita", aphone="069555999", back="/admin/all")
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
    """Флаг visit: узел React с номером визита и адресом возврата, ?ui=legacy
    — старая страница, старая форма при флаге живёт."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2", aservice="consult",
               aname="Flag Vizita", aphone="069888000", back="/admin/all")
        aid = _aid(c, _d(1))
        res.ok("без флага — старая страница", "vf_acuze" in c.get(f"/admin/visit/{aid}").body, "не старая")

    s = _server_with_flag()
    with s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2", aservice="consult",
               aname="Flag Vizita", aphone="069888000", back="/admin/all")
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
        res.ok("старой формы нет", "vf_acuze" not in page and "applyTpl" not in page, "две разметки")
        res.ok("?ui=legacy — старая страница", "vf_acuze" in c.get(f"/admin/visit/{aid}?ui=legacy").body, "нет")
        res.ok("?msg= — плашка сервера", "dp_toast" in c.get(f"/admin/visit/{aid}?msg=ok_visit").body, "нет")
        r = c.post(f"/admin/visit/{aid}", acuze="Control", back=f"/admin/patient/{pid}")
        res.check("старая форма при флаге работает и возвращает с плашкой",
                  (r.status, r.location), (303, f"/admin/visit/{aid}?back=/admin/patient/{pid}&msg=ok_visit"))
        res.check("чужой визит при флаге — в журнал", c.get("/admin/visit/9999").status, 303)
        res.check("без входа React-страница закрыта", Client(s.url).get(f"/admin/visit/{aid}").status, 303)
