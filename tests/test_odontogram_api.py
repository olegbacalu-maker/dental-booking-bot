"""Одонтограмма (C21): `GET /api/patients/{pid}/odontogram` — карта зубов
данными, действия через JSON.

`test_teeth.py` стережёт РИСУНОК (канон геометрии, поверхности, отметки,
мосты). Здесь стережётся то, что уезжает в браузер помимо рисунка: данные
зуба (состояние, поверхности и их состояния, отметки, врач, заметка, дата,
челюсть и сторона), история зуба, подпись, мосты и их роли, подъём дуги в
виде сверху, легенда, раскрытие молочного ряда, выбор зуба из адреса.
До 13.10 эталоном служили старые страницы (карточка фиши и детальная
одонтограмма, `suite_pin`); они сняты, и записанные руками ожидания живут в
`suite_api` значениями. Контракт — docs/dentpilot-2/clinical-chart.md.
"""
import json
import re
import sqlite3
from datetime import timedelta

from harness import Client, Result, Server, clinic_today, pid_by_phone


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _dmy(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return pid_by_phone(c, phone)


def _seed(c: Client) -> dict:
    """Пациент с зубами в каждом состоянии: кариес с поверхностями, смесь
    состояний поверхностей, пломба, коронка, имплант, удалён, отсутствует,
    здоровый в работе (отметка), молочный с кариесом; мост 47–45 с ролями."""
    c.post_json("/api/patients", {"name": "Odonto Pin", "phone": "069300300"})
    pid = _pid(c, "069300300")
    t = f"/api/patients/{pid}/teeth"
    c.post_json(f"{t}/11", {"state": "carie", "note": "distal <b>", "doctor": "Dr. Activ Doi",
                           "surfaces": ["M", "O"]})
    c.post_json(f"{t}/16", {"state": "obturatie", "doctor": "Dr. Activ Doi",
                           "surfaces": {"M": "carie", "O": "obturatie"}})
    c.post_json(f"{t}/21", {"state": "obturatie", "surfaces": ["D"]})
    c.post_json(f"{t}/24", {"state": "coroana", "surfaces": []})
    c.post_json(f"{t}/36", {"state": "implant", "doctor": "Dr. Activ Trei", "surfaces": []})
    c.post_json(f"{t}/38", {"state": "extras", "surfaces": []})
    c.post_json(f"{t}/48", {"state": "lipsa", "surfaces": []})
    c.post_json(f"{t}/31", {"state": "ok", "note": "în lucru", "surfaces": [],
                           "marks": ["tratament"]})
    c.post_json(f"{t}/55", {"state": "carie", "surfaces": []})
    r = c.post_json(f"/api/patients/{pid}/bridges", {"teeth": [[47, "stalp"], [46, "corp"], [45, "stalp"]],
                                                    "material": "zirconiu",
                                                    "doctor": "Dr. Activ Doi"})
    assert r.msg == "ok_punte", r.body[:200]
    return {"pid": pid}


def _strip_hits(svg: str) -> str:
    return re.sub(r"<g class='sfz'[^>]*>.*?</g>", "", svg)


def suite_api(res: Result) -> None:
    """`GET /api/patients/{pid}/odontogram` на засеянном пациенте: данные
    зубов, подписи, история, мосты, дуги, легенда — значениями, записанными
    руками; рисунок несёт цели поверхностей; запись — белыми списками и
    кодами MSG_BANNER."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/patients/1/odontogram").status, 401)
        c = Client(s.url).login()
        res.check("чужая фиша — 404", c.get("/api/patients/777/odontogram").status, 404)
        pid = _seed(c)["pid"]
        d = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]
        res.check("состав", sorted(d),
                  sorted(["teeth", "history", "arches", "arc", "milk_open", "bridges", "legend",
                          "states", "marks", "surfaces", "surface_states", "bridge_roles",
                          "materials", "patient", "doctors", "perio", "perio_layer", "palette",
                          "tooth_states",
                          "modes", "plan"]))
        res.check("план зуба: у пациента без плана — пустой словарь", d["plan"], {})
        # кисть (11.10): кариес и пломба ставятся только по поверхностям, сетка
        # состояний зуба получает СПИСОК СЕРВЕРА — второго словаря у клиента нет
        res.check("tooth_states: состояния про весь зуб — словарь состояний без поверхностных, тем же порядком",
                  list(d["tooth_states"]), [k for k in d["states"] if k not in d["surface_states"]])
        # B7 ступень 1: размеры и цвета для объёмного вида едут с сервера
        # с 02.10 за состояниями идут отметки: 3D красит кольца тем же цветом, что ореол/каналы в 2D
        res.check("палитра: цвет на каждое состояние и отметку, тем же порядком",
                  list(d["palette"]), list(d["states"]) + list(d["marks"]))
        res.check("размеры для 3D у всех зубов, 16 — 10,5 мм и три корня",
                  (all(set(v["geom"]) == {"md", "bl", "crown", "root", "roots", "cls", "upper"} for v in d["teeth"].values()),
                   d["teeth"]["16"]["geom"]["md"], d["teeth"]["16"]["geom"]["roots"], d["teeth"]["55"]["geom"]["cls"]),
                  (True, 10.5, 3, "molar"))
        res.check("без пародонтального осмотра замеров нет — нулей не выдумываем",
                  d["perio"], {})
        res.check("и слоя пародонта для 3D нет — None, а не пустой слой",
                  d["perio_layer"], None)
        teeth = d["teeth"]
        info = ("jaw", "mez", "state", "note", "doctor", "at", "sf", "sfx", "sfst", "mk", "mkx")
        res.check("карта зубов: все 52 номера, у нетронутого — здоров и пусто",
                  (len(teeth), {f: teeth["12"][f] for f in info}),
                  (52, {"jaw": "sus", "mez": "right", "state": "ok", "note": "", "doctor": "",
                        "at": "", "sf": "", "sfx": "", "sfst": {}, "mk": [], "mkx": ""}))
        res.check("кариес с поверхностями: буквы, карта, подпись буквами, заметка сырая, дата",
                  {f: teeth["11"][f] for f in info},
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
        res.ok("сторону зеркала и челюсть считает сервер: правые квадранты — mez right",
               teeth["18"]["mez"] == "right" and teeth["28"]["mez"] == "left"
               and teeth["48"]["mez"] == "right" and teeth["38"]["mez"] == "left", "не то")
        res.check("подписи: состояние, отметка, мост с ролью и материалом, заметка, поверхности",
                  {n: teeth[str(n)]["title"] for n in (11, 16, 31, 47, 46, 12)},
                  {11: "11 · Carie · distal <b> · MO", 16: "16 · Carie · Carie (M), Obturație (O)",
                   31: "31 · Sănătos · În tratament · în lucru",
                   47: "47 · Sănătos · Punte: Stâlp (zirconiu)",
                   46: "46 · Sănătos · Punte: Corp de punte (zirconiu)", 12: "12 · Sănătos"})
        # подпись панели зуба (08.10): название по позиции и сторона пациента —
        # слова сервера, у клиента словаря зубов нет
        res.check("название зуба и сторона — с сервера",
                  {n: (d["teeth"][str(n)]["name"], d["teeth"][str(n)]["side"])
                   for n in (11, 13, 24, 36, 48, 55, 85)},
                  {11: ("Incisiv central", "dreapta"), 13: ("Canin", "dreapta"),
                   24: ("Premolar I", "stânga"), 36: ("Molar I", "stânga"),
                   48: ("Molar III", "dreapta"), 55: ("Molar II", "dreapta"),
                   85: ("Molar II", "dreapta")})
        hist = d["history"]
        res.check("история зуба: строка летописи с датой",
                  (sorted(hist), hist["11"][0]["at"], hist["11"][0]["text"]),
                  (["11", "16", "21", "24", "31", "36", "38", "48", "55"], _dmy(0),
                   "Dinte 11: Carie (MO) · Dr. Activ Doi · distal <b>"))
        res.check("мосты: зубы, роли, материал, врач",
                  [(b["teeth"], b["material"], b["doctor"]) for b in d["bridges"]],
                  [([[47, "stalp"], [46, "corp"], [45, "stalp"]], "zirconiu", "Dr. Activ Doi")])
        res.check("зуб знает свой мост", (d["teeth"]["47"]["bridge"], d["teeth"]["46"]["bridge"], d["teeth"]["11"]["bridge"]),
                  ({"role": "stalp", "material": "zirconiu"}, {"role": "corp", "material": "zirconiu"}, None))
        res.check("дуги и подъём вида сверху",
                  (d["arches"]["upper"][:3], d["arches"]["milk_lower"][-2:],
                   [str(a) for a in d["arc"]["upper"]][:4], d["arc"]["lower"][7], d["arc"]["milk_upper"]),
                  ([18, 17, 16], [74, 75], ["0", "-5", "-10", "-14"], 22, [0, -6, -10, -13, -15, -15, -13, -10, -6, 0]))
        up, lo = d["arches"]["upper"], d["arches"]["lower"]
        res.check("подъём сверху: края на месте, середина выше; нижняя — вниз",
                  ([d["arc"]["upper"][up.index(n)] for n in (17, 16, 11, 21, 27)],
                   [d["arc"]["lower"][lo.index(n)] for n in (47, 41, 31)]),
                  ([-5, -10, -22, -22, -5], [5, 22, 22]))
        res.check("легенда: состояния без «здоров», потом отметки",
                  [x["label"] for x in d["legend"]["frontal"]],
                  ["Carie", "Obturație", "Coroană", "Implant", "Extras", "Lipsă",
                   "În tratament", "Nerv extras"])
        res.ok("легенда: рисунок зуба на каждый пункт", all("<svg" in x["svg"] for x in d["legend"]["occlusal"]), "нет")
        res.check("молочный ряд раскрыт", d["milk_open"], True)
        res.check("словари: состояния, отметки, поверхности, роли, материалы, врачи",
                  (list(d["states"]), list(d["marks"]), list(d["surfaces"]), d["surface_states"],
                   d["bridge_roles"], [m["id"] for m in d["materials"]], d["doctors"][1]),
                  (["ok", "carie", "obturatie", "coroana", "implant", "extras", "lipsa"], ["tratament", "devital"],
                   ["M", "O", "D", "V", "L"], ["carie", "obturatie"], {"stalp": "Stâlp", "corp": "Corp de punte"},
                   ["metalo-ceramică", "zirconiu", "ceramică", "metal", "acrilat", "alt"], "Dr. Activ Doi"))
        res.check("пациент", d["patient"], {"id": pid, "name": "Odonto Pin", "primary_doctor": ""})
        # рисунок: цели поверхностей поверх рисунка зуба. (До 13.10 здесь ещё
        # сверялся рисунок без целей с кнопкой старой страницы байт в байт —
        # второго рисовальщика больше нет, канон геометрии держит test_teeth.)
        res.ok("у каждого зуба оба вида рисунка, без целей — это всё ещё зуб",
               all("<svg" in _strip_hits(t["svg"][v]) for t in teeth.values()
                   for v in ("frontal", "occlusal")), "рисунка нет")
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
        res.check("подпись зуба собрана из записанного", t26["title"], "26 · Carie · test · MO")
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

        # ---- пересохранение БЕЗ единой правки тождественно на ОБОИХ словарях (11.10) ----
        # API принимает поверхности двумя словарями: картой (её шлёт панель
        # React, с кистью — только её) и буквами (так слал диалог старой фиши,
        # снятой 13.10; путь остаётся в контракте API). Четыре вида записей,
        # которые живут у клиник: кариес буквами без карты (старше 08-16),
        # смесь состояний по карте, «C на весь зуб» без поверхностей, коронка с
        # буквами под ней. Прайор 08-16: так пломба уходила с подписываемой 043/e.
        t = f"/api/patients/{pid}/teeth"
        c.post_json(f"{t}/27", {"state": "carie", "doctor": "Dr. Activ Doi", "surfaces": []})        # «C» без поверхностей
        c.post_json(f"{t}/25", {"state": "coroana", "surfaces": ["M", "O", "D"]})          # коронка с буквами под ней
        con = sqlite3.connect(str(s.dir / "dental.db"))                     # запись старше 08-16: карты нет
        con.execute("UPDATE teeth SET surface_states = '' WHERE patient_id = ? AND tooth = 11", (pid,))
        con.commit()
        con.close()

        def info(n: int) -> dict:
            x = dict(_j(c.get(f"/api/patients/{pid}/odontogram"))["data"]["teeth"][str(n)])
            x.pop("at", None)                                               # дата записи меняется по праву
            return x

        for n in (11, 16, 27, 25):
            before = info(n)
            what = f"{n} ({before['state']}, {before['sf'] or 'fără suprafețe'}, карта {before['sfst'] or '—'})"
            body = {"state": before["state"], "state0": before["state"], "note": before["note"],
                    "doctor": before["doctor"], "surfaces": before["sfst"], "marks": before["mk"]}
            r = c.post_json(f"/api/patients/{pid}/teeth/{n}", body)
            res.check(f"панель React: пересохранение {what} тождественно", (r.status, info(n)), (200, before))
            r = c.post_json(f"{t}/{str(n)}", {"state": before["state"],
                                             "state0": before["state"], "note": before["note"],
                                             "doctor": before["doctor"],
                                             "surfaces": list(before["sf"]),
                                             "marks": before["mk"]})
            res.check(f"буквами (словарь старой формы): пересохранение {what} тождественно",
                      (r.msg, info(n)), ("ok_card", before))

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
        r = c.post_json(f"/api/patients/{pid}/bridges/{bid}/delete", {})
        res.check("мост снят — ok_punte_del, остался один", (r.status, _j(r)["code"], len(_j(r)["data"]["bridges"])),
                  (200, "ok_punte_del", 1))
        res.check("снять чужой — 404", c.post_json(f"/api/patients/{pid}/bridges/{bid}/delete", {}).status, 404)
        res.check("не JSON — 422", c.post(f"/api/patients/{pid}/teeth/26", state="carie").status, 422)
        res.check("чужой Origin — 403",
                  c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie"},
                              headers={"Origin": "http://evil.example"}).status, 403)

        # ---- замер пародонта у того же зуба (контракт: зуб один на оба
        # инструмента): инспектор читает тот же осмотр, что печатает 043/e
        eid = _j(c.post_json(f"/api/patients/{pid}/perio/exams", {}))["data"]["exam"]["id"]
        c.post_json(f"/api/patients/{pid}/perio/{eid}", {"teeth": {
            "16": {"pd": [3, 2, 3, 4, 2, 5], "rec": [1, 0, 0, 0, 0, 2], "bop": "010010",
                   "mob": 1, "furc": 2},
            "46": {"pd": [2] * 6, "rec": [0] * 6, "bop": "000000", "mob": 0, "furc": 0}}})
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
        # 06.10: тот же осмотр ЧИСЛАМИ — слой пародонта в 3D; CAL считает сервер
        lay = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]["perio_layer"]
        res.check("слой пародонта: тот же осмотр, только измеренные зубы",
                  (lay["exam"]["id"], lay["exam"]["at"] == _dmy(0), sorted(lay["rows"])),
                  (eid, True, ["16", "46"]))
        r16 = lay["rows"]["16"]
        res.check("числа зуба как есть + CAL = PD + рецессия только у измеренных точек",
                  (r16["pd"], r16["rec"], r16["bop"], r16["mob"], r16["furc"], r16["cal"]),
                  ([3, 2, 3, 4, 2, 5], [1, 0, 0, 0, 0, 2], "010010", 1, 2, [4, 2, 3, 4, 2, 7]))
        res.check("пороги и цвета полосы — с сервера, ключи совпадают",
                  (lay["limits"], sorted(lay["colors"]), [x["key"] for x in lay["sites"]]),
                  ({"deep": 4, "severe": 6}, ["deep", "severe"], ["MV", "V", "DV", "ML", "L", "DL"]))


_PLAN_FIELDS = ["active", "doctor", "done", "due", "id", "label", "motiv", "overdue",
                "price", "procedure", "status"]


def _views(dbfile) -> int:
    """Сколько раз фишу ОТКРЫВАЛИ — строки «Fișa deschisă» журнала доступа."""
    con = sqlite3.connect(str(dbfile))
    try:
        return con.execute("SELECT COUNT(*) FROM activity WHERE kind = 'view'").fetchone()[0]
    finally:
        con.close()


def suite_plan(res: Result) -> None:
    """План ЗУБА в модели одонтограммы (24.10, вкладка «Tratament» панели):
    позиции раскладываются по номеру в порядке плана фиши, строка — та же, что
    у фиши (одна сериализация на два места), активная — перечислением сервера;
    позиция без зуба в зуб не попадает. GET одонтограммы — не открытие фиши:
    в журнал доступа он не пишет, а план читается без него."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Odonto Plan", "phone": "069300302"})
        pid = _pid(c, "069300302")
        add = {}
        for proc, tooth, price, due, doc in (("Obturație 16 MO", "16", "800", _d(-3), "Dr. Activ Doi"),
                                             ("Endodonție 16", "16", "1500", "", ""),
                                             ("Coroană 16", "16", "", _d(30), ""),
                                             ("Implant 36", "36", "9000", "", "Dr. Activ Trei"),
                                             ("Detartraj", "", "500", "", ""),
                                             ("Extracție 55", "55", "200", "", "")):
            r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": proc, "tooth": tooth, "price": price,
                                                          "due_date": due, "doctor": doc})
            assert r.msg == "ok_card", r.body[:200]
            add[proc] = max(it["id"] for it in _j(r)["data"]["plan"]["items"])
        st = f"/api/patients/{pid}/plan"
        c.post_json(f"{st}/{add['Endodonție 16']}/status", {"to": "in_lucru"})
        c.post_json(f"{st}/{add['Coroană 16']}/status", {"to": "in_lucru"})
        c.post_json(f"{st}/{add['Coroană 16']}/status", {"to": "finalizat"})
        r = c.post_json(f"{st}/{add['Implant 36']}/status", {"to": "refuzat", "motiv": "refuză implantul"})
        assert r.msg == "ok_refuz", r.body[:200]

        seen = _views(s.dir / "dental.db")
        d = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]
        res.check("GET одонтограммы не пишет «Fișa deschisă» — план читается без открытия фиши",
                  _views(s.dir / "dental.db"), seen)
        plan = d["plan"]
        res.check("план разложен по зубам: позиция без зуба («Detartraj») — ни в один",
                  sorted(plan), ["16", "36", "55"])
        res.check("поля строки — чтение, без кнопок переходов фиши",
                  sorted(plan["16"][0]), _PLAN_FIELDS)
        res.check("порядок фиши: в работе, запланированное, законченное; подписи статусов сервера",
                  [(x["procedure"], x["status"], x["label"], x["active"]) for x in plan["16"]],
                  [("Endodonție 16", "in_lucru", "În lucru", True),
                   ("Obturație 16 MO", "planificat", "Planificat", True),
                   ("Coroană 16", "finalizat", "Finalizat", False)])
        by = {x["procedure"]: x for x in plan["16"] + plan["36"]}
        res.check("срок и просрочка, цена, врач, дата закрытия — значениями фиши",
                  ((by["Obturație 16 MO"]["due"], by["Obturație 16 MO"]["overdue"], by["Obturație 16 MO"]["price"],
                    by["Obturație 16 MO"]["doctor"]),
                   (by["Coroană 16"]["due"], by["Coroană 16"]["overdue"], by["Coroană 16"]["price"],
                    by["Coroană 16"]["done"])),
                  ((_dmy(-3), True, 800, "Dr. Activ Doi"), (_dmy(30), False, None, _dmy(0))))
        res.check("отказ: не активен, причина рядом",
                  (by["Implant 36"]["label"], by["Implant 36"]["active"], by["Implant 36"]["motiv"]),
                  ("Refuzat", False, "refuză implantul"))
        res.check("молочный зуб — тем же путём", [x["procedure"] for x in plan["55"]], ["Extracție 55"])

        # ⭐ одна строка на два места: всё, что едет в зуб, — ровно то, что фиша
        # говорит о той же позиции (её читает GET фиши, это открытие — здесь можно)
        card = {it["id"]: it for it in _j(c.get(f"/api/patients/{pid}"))["data"]["plan"]["items"]}
        mine = [x for rows in plan.values() for x in rows]
        res.check("каждая позиция зуба — та же строка, что у плана фиши",
                  [{k: v for k, v in x.items() if k != "active"} for x in mine],
                  [{k: card[x["id"]][k] for k in _PLAN_FIELDS if k != "active"} for x in mine])

        # запись плана меняет модель одонтограммы: следующая модель её знает
        r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Sigilare 16", "tooth": "16", "price": "",
                                                      "due_date": "", "doctor": ""})
        assert r.msg == "ok_card", r.body[:200]
        d = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]
        res.check("новая позиция — в модели зуба сразу, на своём месте порядка",
                  [x["procedure"] for x in d["plan"]["16"]],
                  ["Endodonție 16", "Obturație 16 MO", "Sigilare 16", "Coroană 16"])
        c.post_json(f"{st}/{add['Obturație 16 MO']}/delete", {})
        d = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]
        res.check("удалённая позиция из зуба ушла",
                  [x["procedure"] for x in d["plan"]["16"]], ["Endodonție 16", "Sigilare 16", "Coroană 16"])


def suite_switch(res: Result) -> None:
    """Одонтограмма — узел React (старая страница снята 13.10): рамка с узким
    сайдбаром, номер зуба из адреса параметром."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _seed(c)["pid"]
        res.ok("без флага — тоже React (старой страницы нет)",
               '<div id="root" data-screen="odontogram"' in
               c.get(f"/admin/patient/{pid}/odontograma").body, "узла нет")
        c.post_json("/api/patients", {"name": "Odonto Gol", "phone": "069300301"})
        bare = _j(c.get(f"/api/patients/{_pid(c, '069300301')}/odontogram"))["data"]
        res.ok("пустая карта: молочный ряд свёрнут, мостов нет, все здоровы",
               bare["milk_open"] is False and bare["bridges"] == []
               and all(t["state"] == "ok" for t in bare["teeth"].values()), "не то")

    s = Server()
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
        res.ok("чужой номер зуба в адресе параметром не едет",
               '&quot;t&quot;' not in c.get(f"/admin/patient/{pid}/odontograma?t=99").body,
               "зуб 99 уехал в узел")
        res.ok("старой разметки нет", "insp-pic" not in page and "selTooth" not in page, "две разметки")
        res.ok("?msg= — плашка сервера", "dp_toast" in c.get(f"/admin/patient/{pid}/odontograma?msg=ok_punte").body, "нет")
        res.check("чужая фиша — на список", c.get("/admin/patient/9999/odontograma").status, 303)
        res.check("без входа закрыта", Client(s.url).get(f"/admin/patient/{pid}/odontograma").status, 303)
