"""Шаблоны дневника визита по услуге (10.11.2026, `core/visit_tpl.py`).

Шаблон живёт у услуги прайса (`clinic.json › services[].tpl`), правит его
клиника на экране «Setări › Șabloane consultație» (`/api/settings/templates`),
дневник визита подставляет его кнопкой «Din șablon»
(`GET /api/visits/{aid}/template?done=…`). Здесь:
- правило склейки чистой функцией (`compose`, `match_service`, `merge`);
- экран настроек: тронутое правится, нетронутое остаётся, пересохранение
  прайса без правки шаблон не трогает, кривое тело — отказ;
- визит: услуга визита + отмеченные позиции плана, `{dinte}` и `{data}`,
  повторы не склеиваются дважды, чужие и закрытые позиции не берутся,
  запрос ничего не пишет;
- права: экран — только с правом настроек, «Din șablon» — любой вошедший.
"""
import json
import sys
from datetime import timedelta

from harness import BOT, Client, Result, Server, clinic_today, day_model, pid_by_phone
from test_api import NO_KEY

sys.path.insert(0, str(BOT))
from app import engine as appeng  # noqa: E402
from app.core import visit_tpl  # noqa: E402

API = "/api/settings/templates"
FIELDS = ["acuze", "examen", "diagnostic", "tratament", "recomandari"]


def _j(r) -> dict:
    return json.loads(r.body)


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _dmy(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _tpls(c: Client) -> dict:
    return {s["id"]: s["tpl"] for s in _j(c.get(API))["data"]["services"]}


def _visit(c: Client, day: int, time: str, svc: str, name: str, phone: str,
           doc: str = "d3") -> int:
    c.post_json("/api/schedule/appointments", {"date": _d(day), "time": time, "doctor": doc,
                                              "service": svc, "name": name, "phone": phone})
    return int([r["id"] for r in day_model(c, _d(day))["list"]
                if not r["is_note"] and r["time"] == time][-1])


def suite_rule(res: Result) -> None:
    """Правило «Din șablon» чистой функцией на подменённом каталоге услуг."""
    saved = dict(appeng.SERVICES)
    try:
        appeng.SERVICES.clear()
        appeng.SERVICES.update({
            "obt": {"ro": "Obturație", "ru": "Пломба",
                    "tpl": {"diagnostic": "Carie, dintele {dinte}.",
                            "recomandari": "Fără masticație 2 ore.\nControl."}},
            "obtc": {"ro": "Obturație compozit", "ru": "Пломба композит",
                     "tpl": {"diagnostic": "Compozit {dinte}"}},
            "igi": {"ro": "Igienizare", "ru": "Гигиена",
                    "tpl": {"tratament": "Igienizare {data}.", "recomandari": "Control."}},
            "nul": {"ro": "Consultație", "ru": "Консультация"},
        })
        m = visit_tpl.match_service
        res.check("позиция плана → услуга: целиком, началом, по-русски, без регистра, самая длинная",
                  [m("Obturație"), m("obturație 26"), m("Пломба 16"), m("Obturație compozit 26"),
                   m("Obturațieee"), m("Implant 36"), m("")],
                  ["obt", "obt", "obt", "obtc", "", "", ""])
        c = visit_tpl.compose
        res.check("одна услуга визита, без позиций: {dinte} — «__», {data} — дата",
                  c("obt", [], "10.11.2026")["diagnostic"], "Carie, dintele __.")
        v = c("igi", [{"procedure": "Obturație 26", "tooth": 26},
                      {"procedure": "obturație", "tooth": 16},
                      {"procedure": "Obturație 26", "tooth": 26},
                      {"procedure": "Implant 36", "tooth": 36}], "10.11.2026")
        res.check("визит + позиции: склейка по графам, зубы услуги через запятую, повтор строки — один раз",
                  v, {"acuze": "", "examen": "", "diagnostic": "Carie, dintele 26, 16.",
                      "tratament": "Igienizare 10.11.2026.",
                      "recomandari": "Control.\nFără masticație 2 ore."})
        res.check("услуга без шаблона и неизвестная — пусто",
                  (c("nul", [], "x"), c("zzz", [], "x")), ({k: "" for k in FIELDS},) * 2)
        res.check("merge: нет графы — прежняя, пустая — стёрта, пробелы срезаны",
                  visit_tpl.merge({"diagnostic": "D", "tratament": "T"},
                                  {"tratament": "  ", "recomandari": " R \r\n2 "}),
                  {"diagnostic": "D", "recomandari": "R \n2"})
        bad = []
        for raw in ([], "x", {"diagnostic": 5}, {"diagnostic": None}):
            try:
                visit_tpl.merge({}, raw)
                bad.append(repr(raw))
            except ValueError:
                pass
        res.ok("кривой шаблон — ValueError, а не молчаливое «пусто»", not bad, f"{bad}")
        res.check("merge: чужие ключи не хранятся, длина режется",
                  visit_tpl.merge({}, {"foo": "x", "examen": "e" * 2500}), {"examen": "e" * 2000})
    finally:
        appeng.SERVICES.clear()
        appeng.SERVICES.update(saved)


def suite_settings(res: Result) -> None:
    """Экран шаблонов: данные, правка тронутого, тождественность, плитка хаба."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get(API).status, 401)
        c = Client(s.url).login()
        d = _j(c.get(API))["data"]
        res.check("услуги прайса по порядку, у всех пусто",
                  [(x["id"], x["label"], x["tpl"]) for x in d["services"]],
                  [(sid, lab, {k: "" for k in FIELDS}) for sid, lab in
                   [("consult", "Consultație"), ("pain", "Durere acută"), ("hygiene", "Igienizare"),
                    ("orphan", "Serviciu fără medic"), ("long", "Tratament lung")]])
        res.check("графы, метки, предел", ([f["id"] for f in d["fields"]], d["marks"], d["max"]),
                  (FIELDS, {"tooth": "{dinte}", "date": "{data}"}, 2000))
        ex = d["example"]
        res.ok("заглушка: каждая непустая графа помечена «Exemplu, editați»",
               all(v.startswith("Exemplu, editați") for v in ex.values() if v) and any(ex.values()),
               f"{ex}")
        body = json.dumps(d, ensure_ascii=False).casefold()
        res.ok("ни слова о протоколах", "protocol" not in body and "протокол" not in body, "есть")
        page = c.get("/admin/settings/templates")
        res.ok("страница — узел React экрана", page.status == 200
               and 'data-screen="settings_templates"' in page.body, f"код {page.status}")
        hub = {t["href"]: t for t in _j(c.get("/api/settings/hub"))["data"]["tiles"]}
        tile = hub.get("/admin/settings/templates") or {}
        res.check("плитка хаба: группа «Medici», пустой каталог словами",
                  (tile.get("group"), tile.get("hint")), ("medici", [{"t": "niciun șablon încă"}]))

        r = c.post_json(API, {"templates": {"hygiene": {"diagnostic": "Depozite {dinte}",
                                                        "tratament": "Igienizare {data}"},
                                            "ghost": {"diagnostic": "x"}}})
        res.check("запись: ok_set; услуга, которой нет, молча пропущена", r.msg, "ok_set")
        t = _tpls(c)
        res.check("записано у своей услуги, соседи пусты",
                  (t["hygiene"]["diagnostic"], t["hygiene"]["tratament"], t["consult"]["diagnostic"]),
                  ("Depozite {dinte}", "Igienizare {data}", ""))
        hub = {x["href"]: x for x in _j(c.get("/api/settings/hub"))["data"]["tiles"]}
        res.check("плитка: одна услуга с шаблоном", hub["/admin/settings/templates"]["hint"],
                  [{"t": "1 serviciu cu șablon"}])

        c.post_json(API, {"templates": {"hygiene": {"recomandari": "Control"}}})
        res.check("правка одной графы: остальные целы (нет поля = не сообщали)",
                  {k: v for k, v in _tpls(c)["hygiene"].items() if v},
                  {"diagnostic": "Depozite {dinte}", "tratament": "Igienizare {data}",
                   "recomandari": "Control"})
        c.post_json(API, {"templates": {"hygiene": {"tratament": ""}}})
        res.check("присланная пустой — стёрта", _tpls(c)["hygiene"]["tratament"], "")

        before = _tpls(c)
        rows = _j(c.get("/api/settings/services"))["data"]["services"]
        r = c.post_json("/api/settings/services", {"services": rows})
        res.check("пересохранение прайса без правки: ok_set", r.msg, "ok_set")
        res.check("…и шаблоны тождественны", _tpls(c), before)
        rows = [{**x, "price": "777"} if x["id"] == "hygiene" else x for x in rows]
        c.post_json("/api/settings/services", {"services": rows})
        res.check("правка цены услуги шаблон не трогает", _tpls(c), before)
        r = c.post_json(API, {"templates": {}})
        res.check("пустое тело шаблонов — ok и тождественно", (r.msg, _tpls(c)), ("ok_set", before))

        for bad in ({"templates": []}, {"templates": {"hygiene": "x"}},
                    {"templates": {"hygiene": {"diagnostic": 7}}}, {}):
            r = c.post_json(API, bad)
            res.check(f"кривое тело {bad} — 422 bad_set", (r.status, r.msg), (422, "bad_set"))
        res.check("после отказов — ничего не изменилось", _tpls(c), before)


def suite_visit(res: Result) -> None:
    """«Din șablon» на визите: услуга визита + отмеченные позиции плана."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json(API, {"templates": {
            "hygiene": {"diagnostic": "Depozite dentare.", "tratament": "Igienizare {data}.",
                        "recomandari": "Control peste 6 luni."},
            "consult": {"diagnostic": "Examinat dintele {dinte}.",
                        "recomandari": "Control peste 6 luni."}}})
        aid = _visit(c, -1, "10:00", "hygiene", "Sablon Test", "069555111")
        pid = pid_by_phone(c, "069555111")
        for body in ({"procedure": "Consultație 26", "tooth": "26"},
                     {"procedure": "consultație", "tooth": "11"},
                     {"procedure": "Consultație"},
                     {"procedure": "Implant 36", "tooth": "36"},
                     {"procedure": "Consultație 47", "tooth": "47"}):
            r = c.post_json(f"/api/patients/{pid}/plan", body)
        ids = sorted(it["id"] for it in _j(r)["data"]["plan"]["items"])
        p26, p11, p0, pimp, p47 = ids
        c.post_json(f"/api/patients/{pid}/plan/{p47}/status", {"to": "refuzat", "motiv": "nu vrea"})

        d = _j(c.get(f"/api/visits/{aid}"))["data"]
        res.check("визит: у услуги шаблон есть", d["appt"]["tpl"], True)
        res.check("позиции: шаблон по услуге подписи (отказ — не в списке)",
                  [(x["id"], x["tpl"]) for x in d["plan"]["open"]],
                  [(p26, True), (p11, True), (p0, True), (pimp, False)])

        def tpl(done: list) -> dict:
            r = c.get(f"/api/visits/{aid}/template?done={','.join(str(x) for x in done)}")
            return _j(r)["data"]["values"]

        res.check("ничего не отмечено — только услуга визита, дата подставлена",
                  tpl([]), {"acuze": "", "examen": "", "diagnostic": "Depozite dentare.",
                            "tratament": f"Igienizare {_dmy(-1)}.",
                            "recomandari": "Control peste 6 luni."})
        res.check("отмечены 26, 11 и имплант: склейка, зубы услуги, повтор рекомендации — один раз",
                  tpl([p26, p11, pimp]),
                  {"acuze": "", "examen": "",
                   "diagnostic": "Depozite dentare.\nExaminat dintele 26, 11.",
                   "tratament": f"Igienizare {_dmy(-1)}.", "recomandari": "Control peste 6 luni."})
        res.check("позиция без зуба — «__»", tpl([p0])["diagnostic"],
                  "Depozite dentare.\nExaminat dintele __.")
        res.check("отказ, чужой и мусорный id — не берутся", tpl([p47, 99999, "x"])["diagnostic"],
                  "Depozite dentare.")
        res.check("запрос ничего не пишет: записи дневника нет",
                  _j(c.get(f"/api/visits/{aid}"))["data"]["record"], None)

        a2 = _visit(c, -1, "12:00", "pain", "Sablon Doi", "069555222", doc="d2")
        d2 = _j(c.get(f"/api/visits/{a2}"))["data"]
        res.check("услуга без шаблона: флаг нет, тексты пусты",
                  (d2["appt"]["tpl"], _j(c.get(f"/api/visits/{a2}/template"))["data"]["values"]),
                  (False, {k: "" for k in FIELDS}))
        res.check("чужой визит — 404", c.get("/api/visits/99999/template").status, 404)
        res.check("без входа — 401", Client(s.url).get(f"/api/visits/{aid}/template").status, 401)


def suite_rights(res: Result) -> None:
    """Экран шаблонов — право настроек; «Din șablon» — любой вошедший."""
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        boss.post_json("/api/settings/users", {"uid": "d3", "name": "Dr. Activ Trei", "role": "medic",
                                               "doctor_id": "d3", "pin": "2222"})
        boss.post_json("/api/settings/users", {"uid": "ana", "name": "Ana R", "role": "receptie",
                                               "pin": "4444"})
        boss.post_json(API, {"templates": {"hygiene": {"diagnostic": "Depozite."}}})
        aid = _visit(boss, -1, "10:00", "hygiene", "Drept Sablon", "069555333")

        def login(pin):
            x = Client(s.url)
            x.post("/admin/login", password=pin, next="/admin")
            return x
        med, rec = login("2222"), login("4444")
        res.check("врач и стойка: экран шаблонов — 403",
                  (med.get(API).status, rec.get(API).status,
                   med.post_json(API, {"templates": {"hygiene": {"diagnostic": "x"}}}).status),
                  (403, 403, 403))
        res.check("шаблон после отказа цел", _tpls(boss)["hygiene"]["diagnostic"], "Depozite.")
        res.check("врач своего визита: «Din șablon» отвечает",
                  _j(med.get(f"/api/visits/{aid}/template"))["data"]["values"]["diagnostic"],
                  "Depozite.")
