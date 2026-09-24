"""Одонтограмма (C21): данные старых страниц — компактной карточки фиши и
детальной страницы — записаны как эталон; `GET /api/patients/{pid}/odontogram`
повторяет их данными, действия через JSON — теми же правилами, что формы.

`test_teeth.py` стережёт РИСУНОК (канон геометрии, поверхности, отметки,
мосты). Здесь стережётся то, что уезжает в браузер помимо рисунка: карта
зубов `TEETH` (состояние, поверхности и их состояния, отметки, врач, заметка,
дата, челюсть и сторона), история зуба `THIST`, подпись кнопки, мосты и их
роли, подъём дуги в виде сверху, легенда, раскрытие молочного ряда, выбор
зуба из адреса. Контракт — docs/dentpilot-2/clinical-chart.md.
"""
import html
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


def _seed(c: Client) -> dict:
    """Пациент с зубами в каждом состоянии: кариес с поверхностями, смесь
    состояний поверхностей, пломба, коронка, имплант, удалён, отсутствует,
    здоровый в работе (отметка), молочный с кариесом; мост 47–45 с ролями."""
    c.post("/admin/patients/new", name="Odonto Pin", phone="069300300")
    pid = _pid(c, "069300300")
    t = f"/admin/patient/{pid}/tooth"
    c.post(t, tooth="11", state="carie", note="distal <b>", doctor="Dr. Activ Doi", sf=["M", "O"])
    c.post(t, tooth="16", state="obturatie", sfst="M:carie,O:obturatie", doctor="Dr. Activ Doi")
    c.post(t, tooth="21", state="obturatie", sf=["D"])
    c.post(t, tooth="24", state="coroana")
    c.post(t, tooth="36", state="implant", doctor="Dr. Activ Trei")
    c.post(t, tooth="38", state="extras")
    c.post(t, tooth="48", state="lipsa")
    c.post(t, tooth="31", state="ok", note="în lucru", mk=["tratament"], mk0="1")
    c.post(t, tooth="55", state="carie")
    r = c.post(f"/admin/patient/{pid}/bridge", teeth="47:stalp,46:corp,45:stalp",
               material="zirconiu", doctor="Dr. Activ Doi")
    assert r.msg == "ok_punte", r.location
    return {"pid": pid}


def _blob(page: str, name: str) -> dict | list:
    m = re.search(rf"(?:const|var) {name} = (.*?);\n", page)
    assert m, f"нет {name} на странице"
    return json.loads(m.group(1))


def _titles(page: str) -> dict[int, str]:
    """Подпись каждой кнопки зуба лицевого вида (первое вхождение номера)."""
    out: dict[int, str] = {}
    for n, title in re.findall(r"<button type='button' class='tooth-btn' data-n='(\d+)'[^>]*?title=\"([^\"]*)\"", page):
        out.setdefault(int(n), html.unescape(title))
    return out


def _arcs(page: str) -> list[tuple[int, str]]:
    """(зуб, --arc) кнопок вида сверху: только там у зуба есть переменная."""
    occ = page.split("<div class='odo-view v-ocluzal'>", 1)[1]
    return [(int(n), a) for n, a in re.findall(r"data-n='(\d+)' style='--arc:(-?\d+)px'", occ)]


def _legend(page: str) -> list[str]:
    block = page.split("<div class='tleg odo-view v-frontal'>", 1)[1].split("</div>", 1)[0]
    return re.findall(r"</svg> ([^<]+)</span>", block)


def suite_pin(res: Result) -> None:
    """Старые страницы — эталон: карточка фиши и детальная одонтограмма несут
    одни данные зубов, подписи и мосты."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _seed(c)["pid"]
        card = c.get(f"/admin/patient/{pid}").body
        page = c.get(f"/admin/patient/{pid}/odontograma?t=16").body
        teeth = _blob(page, "TEETH")
        res.check("данные зубов одни на карточку и детальную страницу", _blob(card, "TEETH"), teeth)
        res.check("карта зубов: все 52 номера, у нетронутого — здоров и пусто",
                  (len(teeth), teeth["12"]),
                  (52, {"jaw": "sus", "mez": "right", "state": "ok", "note": "", "doctor": "",
                        "at": "", "sf": "", "sfx": "", "sfst": {}, "mk": [], "mkx": ""}))
        res.check("кариес с поверхностями: буквы, карта, подпись буквами, заметка сырая, дата",
                  teeth["11"],
                  {"jaw": "sus", "mez": "right", "state": "carie", "note": "distal <b>",
                   "doctor": "Dr. Activ Doi", "sf": "MO", "sfst": {"M": "carie", "O": "carie"},
                   "mk": [], "mkx": "", "sfx": "MO", "at": _dmy(0)})
        res.check("смесь состояний поверхностей: состояние зуба — тяжелейшее, подпись словами",
                  (teeth["16"]["state"], teeth["16"]["sf"], teeth["16"]["sfst"], teeth["16"]["sfx"]),
                  ("carie", "MO", {"M": "carie", "O": "obturatie"}, "Carie (M), Obturație (O)"))
        res.check("отметка поверх здорового зуба: список и подпись",
                  (teeth["31"]["state"], teeth["31"]["mk"], teeth["31"]["mkx"], teeth["31"]["note"]),
                  ("ok", ["tratament"], "În tratament", "în lucru"))
        res.check("остальные состояния и челюсти",
                  {n: (teeth[n]["state"], teeth[n]["jaw"], teeth[n]["mez"])
                   for n in ("21", "24", "36", "38", "48", "55")},
                  {"21": ("obturatie", "sus", "left"), "24": ("coroana", "sus", "left"),
                   "36": ("implant", "jos", "left"), "38": ("extras", "jos", "left"),
                   "48": ("lipsa", "jos", "right"), "55": ("carie", "sus", "right")})
        hist = _blob(page, "THIST")
        res.check("история зуба: строка летописи с датой",
                  (sorted(hist), hist["11"][0]["at"], hist["11"][0]["text"]),
                  (["11", "16", "21", "24", "31", "36", "38", "48", "55"], _dmy(0),
                   "Dinte 11: Carie (MO) · Dr. Activ Doi · distal <b>"))
        titles = _titles(page)
        res.check("подписи кнопок: состояние, отметка, мост с ролью и материалом, заметка, поверхности",
                  (titles[11], titles[16], titles[31], titles[47], titles[46], titles[12]),
                  ("11 · Carie · distal <b> · MO", "16 · Carie · Carie (M), Obturație (O)",
                   "31 · Sănătos · În tratament · în lucru",
                   "47 · Sănătos · Punte: Stâlp (zirconiu)",
                   "46 · Sănătos · Punte: Corp de punte (zirconiu)", "12 · Sănătos"))
        br = _blob(page, "BRIDGES")
        res.check("мост: зубы в порядке дуги с ролями и материал",
                  [(b["teeth"], b["material"]) for b in br],
                  [([[47, "stalp"], [46, "corp"], [45, "stalp"]], "zirconiu")])
        res.check("мосты карточки — те же", _blob(card, "BRIDGES"), br)
        arcs = _arcs(page)
        res.check("подъём дуги сверху: края на месте, середина выше; нижняя — вниз",
                  ([a for n, a in arcs if n in (17, 16, 11, 21, 27)],
                   [a for n, a in arcs if n in (47, 41, 31)], len(arcs)),
                  (["-5", "-10", "-22", "-22", "-5"], ["5", "22", "22"], 28 + 16))
        res.check("легенда: состояния без «здоров», потом отметки",
                  _legend(page), ["Carie", "Obturație", "Coroană", "Implant", "Extras", "Lipsă", "În tratament"])
        res.ok("молочный ряд раскрыт, когда по нему есть записи",
               "<details class='milk' open>" in page and "<details class='milk' open>" in card, "свёрнут")
        res.ok("выбор зуба из адреса", "selTooth(16)" in page, "нет")
        res.ok("сторона зеркала и челюсть считает сервер: правые квадранты — mez right",
               teeth["18"]["mez"] == "right" and teeth["28"]["mez"] == "left"
               and teeth["48"]["mez"] == "right" and teeth["38"]["mez"] == "left", "не то")
        res.ok("у старых страниц целей поверхностей нет", "sfz" not in page and "sfz" not in card,
               "hit уехал на старую страницу")
        c.post("/admin/patients/new", name="Odonto Gol", phone="069300301")
        bare = _pid(c, "069300301")
        page = c.get(f"/admin/patient/{bare}/odontograma").body
        res.ok("пустая карта: молочный ряд свёрнут, мостов нет, все здоровы",
               "<details class='milk'>" in page and _blob(page, "BRIDGES") == []
               and all(t["state"] == "ok" for t in _blob(page, "TEETH").values()), "не то")


def _strip_hits(svg: str) -> str:
    return re.sub(r"<g class='sfz'[^>]*>.*?</g>", "", svg)


def _btn_svgs(page: str, occ: bool) -> dict[int, str]:
    """SVG каждой кнопки зуба одного вида старой страницы. Блоков вида
    несколько (постоянные и молочные), берутся все нужного вида."""
    want = "v-ocluzal" if occ else "v-frontal"
    parts = re.split(r"(<div class='odo-view v-(?:frontal|ocluzal)'>)", page)
    out: dict[int, str] = {}
    for marker, seg in zip(parts[1::2], parts[2::2]):
        if want not in marker:
            continue
        for n, svg in re.findall(r"<button type='button' class='tooth-btn' data-n='(\d+)'[^>]*>(?:<span class='num'>\d+</span>)?(<svg.*?</svg>)", seg, re.S):
            out.setdefault(int(n), svg)
    return out


def suite_api(res: Result) -> None:
    """`GET /api/patients/{pid}/odontogram` повторяет старые страницы данными;
    рисунок зуба — тот же SVG плюс цели поверхностей; действия — теми же
    правилами и кодами."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/patients/1/odontogram").status, 401)
        c = Client(s.url).login()
        res.check("чужая фиша — 404", c.get("/api/patients/777/odontogram").status, 404)
        pid = _seed(c)["pid"]
        page = c.get(f"/admin/patient/{pid}/odontograma").body
        d = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]
        res.check("состав", sorted(d),
                  sorted(["teeth", "history", "arches", "arc", "milk_open", "bridges", "legend",
                          "states", "marks", "surfaces", "surface_states", "bridge_roles",
                          "materials", "patient", "doctors", "perio"]))
        res.check("без пародонтального осмотра замеров нет — нулей не выдумываем",
                  d["perio"], {})
        teeth_old = _blob(page, "TEETH")
        res.check("зубы: те же данные, что TEETH старой страницы",
                  {k: {f: v[f] for f in teeth_old[k]} for k, v in d["teeth"].items()}, teeth_old)
        res.check("подписи зубов — те же, что title кнопок",
                  {n: d["teeth"][str(n)]["title"] for n in (11, 16, 31, 47, 46, 12)},
                  {n: t for n, t in _titles(page).items() if n in (11, 16, 31, 47, 46, 12)})
        res.check("история — та же", d["history"], _blob(page, "THIST"))
        res.check("мосты: зубы, роли, материал, врач",
                  [(b["teeth"], b["material"], b["doctor"]) for b in d["bridges"]],
                  [([[47, "stalp"], [46, "corp"], [45, "stalp"]], "zirconiu", "Dr. Activ Doi")])
        res.check("зуб знает свой мост", (d["teeth"]["47"]["bridge"], d["teeth"]["46"]["bridge"], d["teeth"]["11"]["bridge"]),
                  ({"role": "stalp", "material": "zirconiu"}, {"role": "corp", "material": "zirconiu"}, None))
        res.check("дуги и подъём вида сверху — как на странице",
                  (d["arches"]["upper"][:3], d["arches"]["milk_lower"][-2:],
                   [str(a) for a in d["arc"]["upper"]][:4], d["arc"]["lower"][7], d["arc"]["milk_upper"]),
                  ([18, 17, 16], [74, 75], ["0", "-5", "-10", "-14"], 22, [0, -6, -10, -13, -15, -15, -13, -10, -6, 0]))
        res.check("подъём: те же значения, что --arc кнопок",
                  [str(a) for a in d["arc"]["upper"][1:15] + d["arc"]["lower"][1:15]
                   + d["arc"]["milk_upper"][1:9] + d["arc"]["milk_lower"][1:9]],
                  [a for _n, a in _arcs(page)])
        res.check("легенда — те же подписи и порядок",
                  [x["label"] for x in d["legend"]["frontal"]], _legend(page))
        res.ok("легенда: рисунок зуба на каждый пункт", all("<svg" in x["svg"] for x in d["legend"]["occlusal"]), "нет")
        res.check("молочный ряд раскрыт", d["milk_open"], True)
        res.check("словари: состояния, отметки, поверхности, роли, материалы, врачи",
                  (list(d["states"]), list(d["marks"]), list(d["surfaces"]), d["surface_states"],
                   d["bridge_roles"], [m["id"] for m in d["materials"]], d["doctors"][1]),
                  (["ok", "carie", "obturatie", "coroana", "implant", "extras", "lipsa"], ["tratament"],
                   ["M", "O", "D", "V", "L"], ["carie", "obturatie"], {"stalp": "Stâlp", "corp": "Corp de punte"},
                   ["metalo-ceramică", "zirconiu", "ceramică", "metal", "acrilat", "alt"], "Dr. Activ Doi"))
        res.check("пациент", d["patient"], {"id": pid, "name": "Odonto Pin", "primary_doctor": ""})
        # рисунок: тот же SVG, что у кнопки старой страницы, плюс цели поверхностей
        old_f, old_o = _btn_svgs(page, False), _btn_svgs(page, True)
        res.check("лицевой рисунок без целей — байт в байт как на странице",
                  {n: _strip_hits(d["teeth"][str(n)]["svg"]["frontal"]) for n in (11, 16, 36, 48, 55)},
                  {n: old_f[n] for n in (11, 16, 36, 48, 55)})
        res.check("вид сверху без целей — байт в байт",
                  {n: _strip_hits(d["teeth"][str(n)]["svg"]["occlusal"]) for n in (11, 16, 36, 48, 55)},
                  {n: old_o[n] for n in (11, 16, 36, 48, 55)})
        hits = {v: sorted(re.findall(r"data-s='(\w)'", d["teeth"]["16"]["svg"][v])) for v in ("frontal", "occlusal")}
        res.check("цели поверхностей: пять на зуб в обоих видах, и на отсутствующем тоже",
                  (hits, len(re.findall(r"data-s=", d["teeth"]["48"]["svg"]["occlusal"]))),
                  ({"frontal": ["D", "L", "M", "O", "V"], "occlusal": ["D", "L", "M", "O", "V"]}, 5))
        res.ok("цели внутри зеркалящей обёртки (после рисунка, до </g>)",
               d["teeth"]["11"]["svg"]["frontal"].index("class='sfz'") <
               d["teeth"]["11"]["svg"]["frontal"].rindex("</g>"), "цели снаружи обёртки")

        # ---- запись зуба через JSON: те же правила, явное намерение ----
        r = c.post_json(f"/api/patients/{pid}/teeth/99", {"state": "carie"})
        res.check("чужой номер — 422 bad_card", (r.status, _j(r)["code"], _j(r).get("field")), (422, "bad_card", "state"))
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "zzz"})
        res.check("чужое состояние — 422", (r.status, _j(r)["code"]), (422, "bad_card"))
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie", "state0": "ok", "note": "  test  ",
                                                          "doctor": "Dr. Activ Doi", "surfaces": ["O", "M", "X"],
                                                          "marks": []})
        j = _j(r)
        t26 = j["data"]["teeth"]["26"]
        res.check("зуб записан: буквы отфильтрованы и в каноне, заметка обрезана, врач из справочника",
                  (r.status, j["code"], t26["state"], t26["sf"], t26["sfst"], t26["note"], t26["doctor"]),
                  (200, "ok_card", "carie", "MO", {"M": "carie", "O": "carie"}, "test", "Dr. Activ Doi"))
        res.ok("старая страница видит зуб API", "26 · Carie · test · MO" in html.unescape(
            c.get(f"/admin/patient/{pid}/odontograma").body), "не видит")
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie", "state0": "carie", "note": "test",
                                                          "doctor": "Dr. Activ Doi", "surfaces": {"M": "carie", "O": "obturatie", "Q": "carie", "D": "zzz"}})
        t26 = _j(r)["data"]["teeth"]["26"]
        res.check("карта поверхностей: чужие буквы и состояния отброшены, состояние зуба — тяжелейшее",
                  (t26["sfst"], t26["state"], t26["sfx"]), ({"M": "carie", "O": "obturatie"}, "carie", "Carie (M), Obturație (O)"))
        before = t26
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie", "state0": "carie", "note": "test",
                                                          "doctor": "Dr. Activ Doi"})
        res.check("без полей поверхностей и отметок — ничего не стёрто (форма не сообщала)",
                  _j(r)["data"]["teeth"]["26"], before)
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie", "state0": "carie", "note": "test",
                                                          "doctor": "Dr. Activ Doi", "marks": ["tratament", "zzz"]})
        t26 = _j(r)["data"]["teeth"]["26"]
        res.check("отметка добавлена, чужая отброшена, поверхности целы",
                  (t26["mk"], t26["mkx"], t26["sfst"]), (["tratament"], "În tratament", {"M": "carie", "O": "obturatie"}))
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie", "state0": "carie", "note": "test",
                                                          "doctor": "Dr. Activ Doi", "marks": []})
        res.check("пустой список отметок — снята", _j(r)["data"]["teeth"]["26"]["mk"], [])
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "ok", "state0": "carie", "note": "", "doctor": ""})
        res.check("здоров без заметки — строка ушла, зуб пуст",
                  (_j(r)["data"]["teeth"]["26"]["state"], _j(r)["data"]["teeth"]["26"]["sfst"]), ("ok", {}))
        res.ok("история зуба пополнилась", len(_j(r)["data"]["history"]["26"]) >= 3, "нет")

        # ---- мосты ----
        r = c.post_json(f"/api/patients/{pid}/bridges", {"teeth": [[16, "stalp"], [14, "stalp"]], "material": "metal"})
        res.check("дырка в ряду — 422 bad_punte", (r.status, _j(r)["code"], _j(r).get("field")), (422, "bad_punte", "teeth"))
        r = c.post_json(f"/api/patients/{pid}/bridges", {"teeth": [[46, "corp"], [45, "stalp"]], "material": "metal"})
        res.check("зуб уже в мосту — 409 dup_punte", (r.status, _j(r)["code"]), (409, "dup_punte"))
        r = c.post_json(f"/api/patients/{pid}/bridges", {"teeth": [[14, "stalp"], [15, "corp"], [16, "stalp"]],
                                                         "material": "alt", "material_alt": "  aur  ", "doctor": "Dr. Activ Trei"})
        j = _j(r)
        res.check("мост записан: порядок дуги, свободный материал, врач; зубы знают роль",
                  (r.status, j["code"], [(b["teeth"], b["material"], b["doctor"]) for b in j["data"]["bridges"]][1],
                   j["data"]["teeth"]["15"]["bridge"], "Punte: Corp de punte (aur)" in j["data"]["teeth"]["15"]["title"]),
                  (200, "ok_punte", ([[16, "stalp"], [15, "corp"], [14, "stalp"]], "aur", "Dr. Activ Trei"),
                   {"role": "corp", "material": "aur"}, True))
        bid = j["data"]["bridges"][1]["id"]
        res.ok("старая страница видит мост API", f'"id": {bid}' in c.get(f"/admin/patient/{pid}/odontograma").body, "нет")
        r = c.post_json(f"/api/patients/{pid}/bridges/{bid}/delete", {})
        res.check("мост снят — ok_punte_del, остался один", (r.status, _j(r)["code"], len(_j(r)["data"]["bridges"])),
                  (200, "ok_punte_del", 1))
        res.check("снять чужой — 404", c.post_json(f"/api/patients/{pid}/bridges/{bid}/delete", {}).status, 404)
        res.check("не JSON — 422", c.post(f"/api/patients/{pid}/teeth/26", state="carie").status, 422)
        res.check("чужой Origin — 403",
                  c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie"},
                              headers={"Origin": "http://evil.example"}).status, 403)

        # ---- замер пародонта у того же зуба (контракт: зуб один на оба
        # инструмента). Осмотр заводится СТАРОЙ формой: так проверяется и то,
        # что инспектор читает те же данные, что печатает 043/e.
        loc = c.post(f"/admin/patient/{pid}/perio/new").location or ""
        eid = int(re.search(r"exam=(\d+)", loc).group(1))
        perm = ",".join(str(n) for n in (
            [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
            + [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]))
        c.post(f"/admin/patient/{pid}/perio", exam=str(eid), shown=perm,
               chart=("16:3,2,3,4,2,5/1,0,0,0,0,2/010010/1/2;"
                      "46:2,2,2,2,2,2/0,0,0,0,0,0/000000/0/0"))
        per = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]["perio"]
        res.check("замер зуба — готовой фразой сервера, с рецессией и степенями",
                  per["16"]["text"],
                  "PD 3 2 3 / 4 2 5 · recesiune 1 · · / · · 2 · sângerare 2/6 "
                  "· mobilitate gr. I · furcație gr. II")
        res.check("у зуба без рецессии и степеней — только глубины",
                  per["46"]["text"], "PD 2 2 2 / 2 2 2")
        res.check("неизмеренный зуб строки не получает и осмотр назван номером",
                  (sorted(per), per["16"]["exam"], per["16"]["at"] == _dmy(0)),
                  (["16", "46"], eid, True))


def _server_with_flag(env: dict | None = None) -> Server:
    s = Server(env=env)
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["odontogram"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_switch(res: Result) -> None:
    """Флаг odontogram: узел React в рамке с узким сайдбаром, номер зуба из
    адреса параметром, ?ui=legacy — старая страница, старая форма зуба при
    флаге живёт и возвращает сюда."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _seed(c)["pid"]
        res.ok("без флага — старая страница", "insp-pic" in c.get(f"/admin/patient/{pid}/odontograma").body, "не старая")

    s = _server_with_flag()
    with s:
        c = Client(s.url).login()
        pid = _seed(c)["pid"]
        page = c.get(f"/admin/patient/{pid}/odontograma?t=16").body
        res.ok("узел React в рамке одонтограммы, сайдбар узкий",
               '<div id="root" data-screen="odontogram"' in page
               and "/static/js/bundle.js?v=" in page, "узла нет")
        # ⭐ B1: узкий сайдбар больше не строка серверной разметки, а поле
        # модели — сайдбар рисует React. Проверяем ЗНАЧЕНИЕ, а не литерал.
        shell = json.loads(page.split('data-shell="', 1)[1].split('"', 1)[0]
                           .replace("&quot;", '"'))
        res.ok("узкий сайдбар — в модели оболочки", shell["frame"]["rail"] is True,
               f"{shell['frame']['rail']!r}")
        res.ok("серверного каркаса нет", "<aside" not in page, "две оболочки разом")
        params = json.loads(page.split("data-params=\"", 1)[1].split("\"", 1)[0].replace("&quot;", '"'))
        res.check("параметры: фиша и выбранный зуб", params, {"pid": str(pid), "t": "16"})
        res.ok("старой разметки нет", "insp-pic" not in page and "selTooth" not in page, "две разметки")
        res.ok("?ui=legacy — старая страница", "insp-pic" in c.get(f"/admin/patient/{pid}/odontograma?ui=legacy").body, "нет")
        res.ok("?msg= — плашка сервера", "dp_toast" in c.get(f"/admin/patient/{pid}/odontograma?msg=ok_punte").body, "нет")
        r = c.post(f"/admin/patient/{pid}/tooth", tooth="26", state="carie", back="odontograma", sf=["O"])
        res.check("старая форма зуба при флаге работает и возвращает сюда",
                  (r.status, r.location), (303, f"/admin/patient/{pid}/odontograma?t=26&msg=ok_card"))
        res.check("чужая фиша при флаге — на список", c.get("/admin/patient/9999/odontograma").status, 303)
        res.check("без входа закрыта", Client(s.url).get(f"/admin/patient/{pid}/odontograma").status, 303)
