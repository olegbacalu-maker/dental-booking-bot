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
from datetime import datetime, time, timedelta

from harness import (TZ, Client, Clock, Result, Server, add_appt, appt_id, clinic_now,
                     clinic_today, pid_by_phone)


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _dmy(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return pid_by_phone(c, phone)


def _seed(c: Client, name: str = "Odonto Pin", phone: str = "069300300") -> dict:
    """Пациент с зубами в каждом состоянии: кариес с поверхностями, смесь
    состояний поверхностей, пломба, коронка, имплант, удалён, отсутствует,
    здоровый в работе (отметка), молочный с кариесом; мост 47–45 с ролями."""
    c.post_json("/api/patients", {"name": name, "phone": phone})
    pid = _pid(c, phone)
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
                          "modes", "plan", "visits"]))
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

        # «Adaugă în plan» с зуба (24.10): `?odo=1` — в ответе МОДЕЛЬ одонтограммы
        # с позицией (вкладка «Tratament» без перечитывания), `&card=1` — и фиша
        # рядом, как у записи зуба; без `odo` — фиша, как было; отказ — тот же
        body = {"procedure": "Inlay 36", "tooth": "36", "price": "2500", "due_date": "", "doctor": ""}
        r = c.post_json(f"{st}?odo=1", body)
        j = _j(r)
        res.check("?odo=1: ответ — модель одонтограммы с новой позицией, без фиши",
                  (r.status, j["code"], "teeth" in j["data"], "card" in j["data"],
                   [x["procedure"] for x in j["data"]["plan"]["36"]]),
                  (200, "ok_card", True, False, ["Inlay 36", "Implant 36"]))
        seen = _views(s.dir / "dental.db")
        r = c.post_json(f"{st}?odo=1&card=1&views=1", {**body, "procedure": "Onlay 36"})
        j = _j(r)
        res.check("?odo=1&card=1: модель и рядом фиша с той же позицией, без записи «Fișa deschisă»",
                  ("teeth" in j["data"], [x["procedure"] for x in j["data"]["plan"]["36"]][:2],
                   any(it["procedure"] == "Onlay 36" for it in j["data"]["card"]["plan"]["items"]),
                   _views(s.dir / "dental.db") == seen),
                  (True, ["Inlay 36", "Onlay 36"], True, True))
        r = c.post_json(st, {**body, "procedure": "Coroană 36"})
        j = _j(r)
        # ⛔ Ответ БЕЗ odo — прежний: им живёт вкладка плана фиши. Состав — тот
        # же, что у фиши, открытой GET-ом (это открытие, здесь можно), код тот же
        card = _j(c.get(f"/api/patients/{pid}"))["data"]
        res.check("без odo — прежний ответ: фиша того же состава, код ok_card, модели нет",
                  (r.status, j["code"], sorted(j["data"]), "teeth" in j["data"]),
                  (200, "ok_card", sorted(card), False))
        # запись одна и та же на обеих ветках: строки плана отличаются только
        # процедурой и номером
        rows = {it["procedure"]: it for it in card["plan"]["items"]}
        same = lambda it: {k: v for k, v in it.items() if k not in ("id", "procedure")}  # noqa: E731
        res.check("запись одна: позиция с odo и без — одинаковые строки плана",
                  same(rows["Inlay 36"]) == same(rows["Coroană 36"]), True)
        r = c.post_json(f"{st}?odo=1", {**body, "procedure": "  "})
        res.check("?odo=1 и пустая процедура — тот же отказ 422 с полем, без модели",
                  (r.status, _j(r)["code"], _j(r).get("field"), "data" in _j(r)), (422, "bad_card", "procedure", False))


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


def _tooth_acts(dbfile, pid: int) -> list:
    """Строки летописи зубов пациента по порядку: (зуб, текст)."""
    con = sqlite3.connect(str(dbfile))
    try:
        return con.execute("SELECT tooth, text FROM activity WHERE patient_id = ? AND kind = 'tooth' "
                           "ORDER BY id", (pid,)).fetchall()
    finally:
        con.close()


def _base(t: dict) -> dict:
    """`base` зуба — каким его показала модель (так шлёт экран)."""
    return {"state": t["state"], "sfst": t["sfst"], "marks": t["mk"], "doctor": t["doctor"], "note": t["note"]}


def _drafts(teeth: dict) -> list:
    """Черновики пяти зубов — каждый на своё правило записи: имплант поверх
    смеси поверхностей (карта стирается, буквы держатся), новая смесь,
    «Sănătos» с кариесом на поверхности (состояние ВЫЧИСЛЯЕТСЯ), отметка и
    заметка на коронке, зуб в работе становится здоровым (строка удаляется)."""
    def d(n: int, **kw) -> dict:
        t = teeth[str(n)]
        return {"n": n, "state": t["state"], "state0": t["state"], "note": t["note"], "doctor": t["doctor"],
                "surfaces": t["sfst"], "marks": t["mk"], **kw}
    return [d(16, state="implant"),
            d(11, surfaces={"M": "carie", "O": "obturatie", "D": "carie"}),
            d(22, state="ok", surfaces={"O": "carie"}),
            d(24, marks=["devital"], note="refăcută"),
            d(31, marks=[], note="")]


def suite_batch(res: Result) -> None:
    """«Salvează tot» и предпросмотр черновика (волна 2, 25.10).

    Предпросмотр ничего не пишет (ни строки зуба, ни летописи, ни «Fișa
    deschisă») и рисует РОВНО то, что потом запишется: предпросмотр каждого
    зуба совпадает с его записью поле в поле (рисунки, подписи, данные).
    Запись пачкой — то же, что те же черновики по одному у пациента-двойника:
    те же зубы и те же строки летописи. Конфликт (зуб изменился с тех пор,
    как экран начал правку) и негодный зуб — отказ, НЕ записано ничего."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _seed(c)["pid"]
        twin = _seed(c, "Odonto Geaman", "069300303")["pid"]
        dbf = s.dir / "dental.db"
        odo = f"/api/patients/{pid}/odontogram"
        teeth0 = _j(c.get(odo))["data"]["teeth"]
        drafts = _drafts(teeth0)
        nums = [d["n"] for d in drafts]

        acts0, views0 = _tooth_acts(dbf, pid), _views(dbf)
        r = c.post_json(f"{odo}/preview", {"teeth": drafts})
        res.check("предпросмотр: 200", r.status, 200)
        pv = _j(r)["data"]["teeth"]
        res.check("предпросмотр — только присланные зубы", sorted(pv), sorted(str(n) for n in nums))
        res.check("предпросмотр не пишет летопись", _tooth_acts(dbf, pid), acts0)
        res.check("предпросмотр не пишет «Fișa deschisă»", _views(dbf), views0)
        res.ok("предпросмотр не трогает зубы", _j(c.get(odo))["data"]["teeth"] == teeth0, "модель сменилась")
        res.check("предпросмотр: «Sănătos» + кариес на O → состояние вычислено, как у записи",
                  (pv["22"]["state"], pv["22"]["sfst"]), ("carie", {"O": "carie"}))
        res.check("предпросмотр: имплант стирает карту поверхностей", pv["16"]["sfst"], {})
        res.ok("предпросмотр: рисунок черновика, не сохранённый",
               pv["16"]["svg"]["frontal"] != teeth0["16"]["svg"]["frontal"], "рисунок прежний")

        items = [{**d, "base": _base(teeth0[str(d["n"])])} for d in drafts]
        r = c.post_json(f"/api/patients/{pid}/teeth", {"teeth": items})
        res.check("запись пачкой: ok_card", (r.status, r.msg), (200, "ok_card"))
        m1 = _j(r)["data"]
        res.ok("ответ — модель, без фиши (её не просили)", "teeth" in m1 and "card" not in m1, "не то")
        res.ok("зубы вне пачки не тронуты",
               all(m1["teeth"][k] == teeth0[k] for k in teeth0 if int(k) not in nums), "чужой зуб сменился")
        for n in nums:
            res.check(f"зуб {n}: предпросмотр = записанное поле в поле", pv[str(n)], m1["teeth"][str(n)])
        acts1 = _tooth_acts(dbf, pid)[len(acts0):]
        res.check("летопись: строка на каждый зуб, в порядке пачки", [t for t, _x in acts1], nums)

        tw = f"/api/patients/{twin}/teeth"
        for d in drafts:
            r = c.post_json(f"{tw}/{d['n']}", {k: v for k, v in d.items() if k != "n"})
            assert r.msg == "ok_card", r.body[:200]
        mt = _j(c.get(f"/api/patients/{twin}/odontogram"))["data"]
        res.ok("пачка = те же черновики по одному: зубы", mt["teeth"] == m1["teeth"], "разошлись")
        res.check("пачка = те же черновики по одному: строки летописи",
                  [x for _t, x in acts1], [x for _t, x in _tooth_acts(dbf, twin)[-len(drafts):]])

        # фиша рядом — тем же хвостом, что у записи зуба; открытием она не пишется
        t21 = m1["teeth"]["21"]
        views1 = _views(dbf)
        r = c.post_json(f"/api/patients/{pid}/teeth?card=1&views=1",
                        {"teeth": [{"n": 21, "state": "coroana", "state0": t21["state"], "note": "", "doctor": "",
                                    "surfaces": t21["sfst"], "marks": t21["mk"], "base": _base(t21)}]})
        d = _j(r)["data"]
        res.ok("?card=1 — свежая фиша рядом с моделью", r.msg == "ok_card" and "card" in d
               and d["teeth"]["21"]["state"] == "coroana", r.body[:200])
        res.check("фиша в ответе — не открытие", _views(dbf), views1)

        # конфликт: 36 изменили «на другом компьютере», пока экран правил 21 и 36
        m2 = _j(c.get(odo))["data"]["teeth"]
        stale = [{"n": 21, "state": "implant", "state0": m2["21"]["state"], "note": "", "doctor": "",
                  "surfaces": {}, "marks": [], "base": _base(m2["21"])},
                 {"n": 36, "state": "extras", "state0": m2["36"]["state"], "note": "", "doctor": "",
                  "surfaces": {}, "marks": [], "base": _base(m2["36"])}]
        r = c.post_json(f"/api/patients/{pid}/teeth/36", {"state": "implant", "note": "alt calculator",
                                                         "doctor": m2["36"]["doctor"], "surfaces": {}, "marks": []})
        assert r.msg == "ok_card", r.body[:200]
        before, acts2 = _j(c.get(odo))["data"]["teeth"], _tooth_acts(dbf, pid)
        r = c.post_json(f"/api/patients/{pid}/teeth", {"teeth": stale})
        body = _j(r)
        res.check("конфликт: 409 odo_conflict, поле — номер зуба", (r.status, body.get("code"), body.get("field")),
                  (409, "odo_conflict", "36"))
        res.ok("конфликт: текст называет зуб и говорит, что не сохранено ничего",
               "Dintele 36" in body.get("text", "") and "Nimic nu a fost salvat" in body.get("text", ""),
               body.get("text", ""))
        res.ok("конфликт: НЕ записано ничего — и годный 21 тоже", _j(c.get(odo))["data"]["teeth"] == before,
               "часть пачки записалась")
        res.check("конфликт: летопись не тронута", _tooth_acts(dbf, pid), acts2)
        res.check("конфликт: удалённая строка — тоже изменение (31 был в работе, стал здоров)",
                  c.post_json(f"/api/patients/{pid}/teeth", {"teeth": [
                      {"n": 31, "state": "ok", "state0": "ok", "note": "", "doctor": "", "surfaces": {},
                       "marks": ["tratament"], "base": _base(teeth0["31"])}]}).status, 409)

        # негодная пачка — 422, и тоже ничего
        ok21 = {"n": 21, "state": "implant", "state0": "", "note": "", "doctor": "", "surfaces": {}, "marks": [],
                "base": _base(before["21"])}
        for why, payload, field in (
                ("чужое состояние", [ok21, {**ok21, "n": 22, "state": "tratament", "base": _base(before["22"])}], "22"),
                ("без base", [{k: v for k, v in ok21.items() if k != "base"}], "21"),
                ("чужой номер", [{**ok21, "n": 99}], "99"),
                ("номер строкой", [{**ok21, "n": "21"}], "teeth"),
                ("повтор зуба", [ok21, ok21], "teeth"),
                ("пустая пачка", [], "teeth")):
            r = c.post_json(f"/api/patients/{pid}/teeth", {"teeth": payload})
            res.check(f"негодная пачка ({why}): 422 bad_card, поле {field}",
                      (r.status, r.msg, _j(r).get("field")), (422, "bad_card", field))
        res.ok("негодные пачки ничего не записали", _j(c.get(odo))["data"]["teeth"] == before
               and _tooth_acts(dbf, pid) == acts2, "запись прошла")
        res.check("предпросмотр негодного зуба — 422",
                  c.post_json(f"{odo}/preview", {"teeth": [{**ok21, "state": "tratament"}]}).status, 422)

        out = Client(s.url)
        res.check("без входа: запись пачкой закрыта (JSON 401)",
                  out.post_json(f"/api/patients/{pid}/teeth", {"teeth": [ok21]}).status, 401)
        res.check("без входа: предпросмотр закрыт (JSON 401)",
                  out.post_json(f"{odo}/preview", {"teeth": [ok21]}).status, 401)
        res.check("чужая фиша — 404", c.post_json("/api/patients/9999/teeth", {"teeth": [ok21]}).status, 404)


def _hist_rows(dbfile, pid: int) -> list:
    """Снимки истории зубов пациента по порядку: (зуб, at, state, src)."""
    con = sqlite3.connect(str(dbfile))
    try:
        return con.execute("SELECT tooth, at, state, src FROM teeth_history WHERE patient_id = ? "
                           "ORDER BY id", (pid,)).fetchall()
    finally:
        con.close()


def _count(dbfile, table: str, pid: int) -> int:
    con = sqlite3.connect(str(dbfile))
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table} WHERE patient_id = ?", (pid,)).fetchone()[0]
    finally:
        con.close()


def suite_compare(res: Result) -> None:
    """«Сравнить с визитом» (волна 2, 25.10): история зубов СОСТОЯНИЯМИ.

    Засев идёт по поддельным часам: метка начала истории (шаг 6 на старте),
    потом три дня записей — день визита 1, день визита 2 и «сегодня». Карта
    «на визит» — конец ДНЯ визита: что записано в тот день после приёма,
    принадлежит ему. Ожидания записаны руками: какие зубы изменились и
    какими словами, мост, снятый после визита, на карте визита стоит; визит
    раньше метки — «нет данных». Рисунок «было» сверяется с моделью, которую
    экран отдавал В ТОТ день: второго рисовальщика нет. Список визитов — без
    отменённых, неявок, сегодняшних и будущих; GET сравнения ничего не пишет."""
    day0 = clinic_today()

    def at(days: int, hh: int = 14) -> datetime:
        return datetime.combine(day0 + timedelta(days=days), time(hh, 0), tzinfo=TZ)

    def dd(days: int) -> str:
        return (day0 + timedelta(days=days)).isoformat()

    def dmy(days: int) -> str:
        return (day0 + timedelta(days=days)).strftime("%d.%m.%Y")

    name, phone = "Odonto Compar", "069300404"
    # ⚠️ часы стартуют с НАСТОЯЩЕГО «сейчас» и дальше только прыгают вперёд
    # (харнесс: копии лаунчера иначе выходят «из будущего»)
    with Clock(clinic_now()) as clock, Server() as s:
        c = Client(s.url).login()
        dbf = s.dir / "dental.db"
        c.post_json("/api/patients", {"name": name, "phone": phone})
        pid = _pid(c, phone)
        t = f"/api/patients/{pid}/teeth"
        odo = f"/api/patients/{pid}/odontogram"
        res.check("визит до начала истории записан", add_appt(c, dd(-5), "10:00", name, phone).msg, "ok_past")

        # день визита 1: зубы и мост записаны днём, визит — утром того же дня
        clock.set(at(1))
        c.post_json(f"{t}/16", {"state": "carie", "surfaces": {"M": "carie"}})
        c.post_json(f"{t}/36", {"state": "obturatie", "surfaces": {"O": "obturatie"}})
        c.post_json(f"{t}/26", {"state": "ok", "marks": ["devital"], "surfaces": {}})
        r = c.post_json(f"/api/patients/{pid}/bridges", {"teeth": [[46, "stalp"], [45, "corp"], [44, "stalp"]],
                                                        "material": "zirconiu", "doctor": "Dr. Activ Doi"})
        res.check("мост поставлен", r.msg, "ok_punte")
        bid = _j(r)["data"]["bridges"][0]["id"]
        m1 = _j(c.get(odo))["data"]
        clock.set(at(1, 16))
        # утро того же дня — «ok», не «ok_past»: предупреждение о прошлом дневное
        res.check("визит 1 (тот же день, утром) записан", add_appt(c, dd(1), "09:00", name, phone).msg, "ok")

        # день визита 2: пломба вместо кариеса, 36 здоров, пачкой — коронка 21 и
        # врач без находки на 11, мост снят; всё ПОСЛЕ приёма
        clock.set(at(10))
        res.check("визит 2 записан", add_appt(c, dd(10), "09:00", name, phone).msg, "ok")
        clock.set(at(10, 15))
        n0 = len(_hist_rows(dbf, pid))
        c.post_json(f"{t}/16", {"state": "obturatie", "surfaces": {"M": "obturatie", "O": "obturatie"}})
        c.post_json(f"{t}/36", {"state": "ok", "surfaces": {}, "marks": []})
        res.check("снимок на каждую запись зуба (+2, второй — «строки нет»)",
                  [(n, st) for n, _a, st, _s in _hist_rows(dbf, pid)[n0:]], [(16, "obturatie"), (36, None)])
        cur = _j(c.get(odo))["data"]["teeth"]
        r = c.post_json(t, {"teeth": [
            {"n": 21, "state": "coroana", "state0": "ok", "note": "", "doctor": "", "surfaces": {}, "marks": [],
             "base": _base(cur["21"])},
            {"n": 11, "state": "ok", "state0": "ok", "note": "", "doctor": "Dr. Activ Doi", "surfaces": {},
             "marks": [], "base": _base(cur["11"])}]})
        res.check("пачка записана", r.msg, "ok_card")
        rows = _hist_rows(dbf, pid)[n0 + 2:]
        res.check("пачка — снимок на каждый зуб, одним мгновением",
                  ([(n, st) for n, _a, st, _s in rows], len({a for _n, a, _st, _s in rows})),
                  ([(21, "coroana"), (11, "ok")], 1))
        res.check("снятие моста — ok", c.post_json(f"/api/patients/{pid}/bridges/{bid}/delete", {}).msg,
                  "ok_punte_del")
        m2 = _j(c.get(odo))["data"]

        # «сегодня» (день 15): кариес на 11; визиты, которых в списке быть не должно
        clock.set(at(15))
        c.post_json(f"{t}/11", {"state": "carie", "doctor": "Dr. Activ Doi", "surfaces": {"D": "carie"}})
        for day, to in ((12, "cancelled"), (13, "noshow")):
            add_appt(c, dd(day), "10:00", name, phone)
            c.post_json(f"/api/schedule/appointments/{appt_id(c, dd(day), name)}/status", {"to": to})
        add_appt(c, dd(15), "09:00", name, phone)
        add_appt(c, dd(17), "10:00", name, phone)
        other = _seed(c, "Odonto Strain", "069300405")["pid"]
        add_appt(c, dd(11), "10:00", "Odonto Strain", "069300405")

        d = _j(c.get(odo))["data"]
        vis = d["visits"]
        ids = {v["date"]: v["id"] for v in vis}
        res.check("список визитов: свежие первыми, без отменённого, неявки, сегодняшнего, будущего и чужого",
                  [(v["date"], v["known"]) for v in vis], [(dmy(10), True), (dmy(1), True), (dmy(-5), False)])
        res.check("подпись визита — дата · услуга · врач",
                  (vis[0]["label"].startswith(dmy(10) + " · "), vis[0]["label"].count(" · ")), (True, 2))

        views0, acts0, hist0 = _views(dbf), _tooth_acts(dbf, pid), _hist_rows(dbf, pid)
        cmp = f"{odo}/compare?visit="
        r1 = _j(c.get(cmp + str(ids[dmy(1)])))["data"]
        res.check("визит 1: данные есть", (r1["known"], r1["visit"]["date"]), (True, dmy(1)))
        res.check("визит 1: изменившиеся зубы в порядке экрана, было → стало",
                  [(x["n"], x["was"], x["now"]) for x in r1["changes"]],
                  [(16, "Carie (M)", "Obturație (MO)"),
                   (11, "Sănătos", "Carie (D)"),
                   (21, "Sănătos", "Coroană"),
                   (46, "Sănătos · Punte: Stâlp", "Sănătos"),
                   (45, "Sănătos · Punte: Corp de punte", "Sănătos"),
                   (44, "Sănătos · Punte: Stâlp", "Sănătos"),
                   (36, "Obturație (O)", "Sănătos")])
        res.check("визит 1: «было» — только изменившиеся зубы", sorted(r1["teeth"], key=int),
                  ["11", "16", "21", "36", "44", "45", "46"])
        res.ok("визит 1: рисунок «было» = модель экрана В ТОТ день (поле в поле, с подписью и мостом)",
               all(r1["teeth"][k] == m1["teeth"][k] for k in r1["teeth"]),
               ", ".join(k for k in r1["teeth"] if r1["teeth"][k] != m1["teeth"][k]))
        res.check("визит 1: мост, снятый после визита, на карте визита стоит", r1["bridges"], m1["bridges"])
        res.check("зуб без изменений (26, отметка) в разнице не назван", "26" in r1["teeth"], False)

        r2 = _j(c.get(cmp + str(ids[dmy(10)])))["data"]
        res.check("визит 2: записанное в день визита после приёма — его работа; изменился только 11",
                  [(x["n"], x["was"], x["now"]) for x in r2["changes"]],
                  [(11, "Sănătos", "Carie (D)")])
        res.check("визит 2: врач без находки — «Sănătos», и рисунок тот, что экран показывал",
                  r2["teeth"]["11"], m2["teeth"]["11"])
        res.check("визит 2: мост уже снят", r2["bridges"], [])

        r0 = _j(c.get(cmp + str(ids[dmy(-5)])))["data"]
        res.check("визит до начала истории — «нет данных», без разницы и без рисунка",
                  (r0["known"], r0["changes"], r0["teeth"], r0["bridges"]), (False, [], {}, []))
        res.check("начало истории названо датой", r0["since"], dmy(0))

        res.check("GET сравнения не пишет «Fișa deschisă» (закон 195)", _views(dbf), views0)
        res.check("GET сравнения не пишет летопись", _tooth_acts(dbf, pid), acts0)
        res.check("GET сравнения не пишет историю", _hist_rows(dbf, pid), hist0)
        res.ok("GET сравнения не трогает модель", _j(c.get(odo))["data"]["teeth"] == d["teeth"], "модель сменилась")

        bad = {"отменённый": appt_id(c, dd(12), name), "неявка": appt_id(c, dd(13), name),
               "сегодняшний": appt_id(c, dd(15), name), "будущий": appt_id(c, dd(17), name),
               "чужой": appt_id(c, dd(11), "Odonto Strain"), "несуществующий": 99999}
        for why, aid in bad.items():
            res.check(f"визит {why} — 404", c.get(cmp + str(aid)).status, 404)
        for why, q in (("без визита", f"{odo}/compare"), ("визит словом", cmp + "abc"), ("минус", cmp + "-1")):
            res.check(f"{why} — 404", c.get(q).status, 404)
        res.check("чужая фиша — 404", c.get(f"/api/patients/{other + 1000}/odontogram/compare?visit=1").status, 404)
        res.check("без входа — JSON 401", Client(s.url).get(cmp + str(ids[dmy(1)])).status, 401)

        # стирание: контакт без лечения, у которого зуб был записан и снят, уходит
        # целиком — вместе с историей зубов и снятыми мостами
        c.post_json("/api/patients", {"name": "Odonto Sters", "phone": "069300406"})
        gone = _pid(c, "069300406")
        c.post_json(f"/api/patients/{gone}/teeth/12", {"state": "carie", "surfaces": {"M": "carie"}})
        c.post_json(f"/api/patients/{gone}/teeth/12", {"state": "ok", "surfaces": {}, "marks": []})
        r = c.post_json(f"/api/patients/{gone}/bridges", {"teeth": [[14, "stalp"], [15, "stalp"]]})
        c.post_json(f"/api/patients/{gone}/bridges/{_j(r)['data']['bridges'][0]['id']}/delete", {})
        res.check("до стирания: история и снятый мост есть",
                  (_count(dbf, "teeth_history", gone), _count(dbf, "bridges_removed", gone)), (2, 1))
        res.check("стирание — физическое", c.post_json(f"/api/patients/{gone}/erase", {"confirm": "STERG"}).msg,
                  "ok_del")
        res.check("после стирания — ни истории, ни снятого моста",
                  (_count(dbf, "teeth_history", gone), _count(dbf, "bridges_removed", gone)), (0, 0))
