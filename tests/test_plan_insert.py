"""Шаблон плана лечения в фише: вставка в план пациента и «сохранить план как
шаблон» (`modules/patients`: `_plan_from_template`, `_plan_to_template`).

- вставка (`POST /api/patients/{pid}/plan/from-template`): отмеченные строки
  шаблона встают в план одним набором — все «planificat», с ключами услуги и
  врача по правилу обычной позиции; цена — своя цена шаблона, иначе цена
  прайса, когда она одним числом; набор только добавляется; одна строка
  летописи; отказ в любой строке не оставляет в плане ничего;
- запись набора в базе — один оператор: ошибка в середине не оставляет
  половины (проба в своём процессе, прямо по `db.add_plan_items`);
- «сохранить как шаблон» (`POST …/plan/save-template`): в шаблон идут
  процедура, «нужен зуб» и порядок, цена — по галочке; ничего о пациенте;
- права на ветке PIN-файла: вставляет любой, кто видит план, шаблоном
  сохраняют директор и регистратура, врач — нет.
"""
import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

from harness import BOT, FIXTURES, PYTHON, Client, Result, Server, clinic_today, new_patient
from test_api import NO_KEY
from test_plan_tpl import _team

SETTINGS = "/api/settings/plan-templates"
PDF = b"%PDF-1.4 " + b"x" * 64
DOC = "Dr. Activ Doi"

# строки по порядку лечения: без зуба и без цены в прайсе; из прайса одним
# числом; из прайса диапазоном; свободным текстом со своей ценой; без зуба со
# своей ценой поверх прайса
CANAL = {"name": "Canal + coroană", "note": "pentru molari", "rows": [
    {"service_id": "consult", "tooth": False},
    {"service_id": "hygiene", "tooth": True},
    {"service_id": "long", "tooth": True},
    {"procedure": "Coroană zirconiu", "tooth": True, "price": 4500},
    {"service_id": "orphan", "tooth": False, "price": 700}]}
IGIENA = {"name": "Igienizare completă", "rows": [{"service_id": "hygiene", "tooth": False}]}


def _j(r) -> dict:
    return json.loads(r.body)


def _server(**env) -> Server:
    """Прайс с диапазоном: у «Tratament lung» сумму из прайса не взять."""
    s = Server(**env)
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    for svc in cfg["services"]:
        if svc["id"] == "long":
            svc["price"] = "1200–1800 MDL"
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def _cfg(s: Server) -> dict:
    return json.loads(s.clinic.read_text(encoding="utf-8"))


def _make(c: Client, *tpls: dict) -> list[str]:
    r = c.post_json(SETTINGS, {"new": list(tpls)})
    assert r.msg == "ok_set", r.body[:300]
    return _j(r)["data"]["created"]


def _card(c: Client, pid: int) -> dict:
    r = c.get(f"/api/patients/{pid}")
    assert r.status == 200, r.body[:200]
    return _j(r)["data"]


def _plan(c: Client, pid: int) -> list[tuple]:
    return [(it["tooth"], it["procedure"], it["price"], it["service_id"], it["doctor"], it["doctor_id"],
             it["status"]) for it in _card(c, pid)["plan"]["items"]]


def _adds(c: Client, pid: int) -> list[str]:
    feed = _j(c.get(f"/api/patients/{pid}/activity?views=1"))["data"]["items"]
    return [a["text"] for a in reversed(feed) if a["kind"] == "plan_add"]


def _ins(c: Client, pid: int, body: dict) -> tuple:
    r = c.post_json(f"/api/patients/{pid}/plan/from-template", body)
    j = _j(r)
    return r.status, j.get("code"), j.get("field"), "data" in j


def _save(c: Client, pid: int, body: dict) -> tuple:
    r = c.post_json(f"/api/patients/{pid}/plan/save-template", body)
    j = _j(r)
    return r.status, j.get("code"), j.get("field"), "data" in j


def suite_insert(res: Result) -> None:
    """Вставка шаблона в план: что встаёт в план и что отвечает отказ."""
    with _server() as s:
        c = Client(s.url).login()
        tid, hyg = _make(c, CANAL, IGIENA)
        pid = new_patient(c, "Sablon Unu", "069777001")

        cat = _j(c.get(f"/api/patients/{pid}/plan/templates"))
        res.check("окно получает шаблоны клиники строками и врача по умолчанию (медика куранта нет — пусто)",
                  ([(t["id"], t["name"], [(r["procedure"], r["service_id"], r["tooth"], r["price"])
                                          for r in t["rows"]]) for t in cat["data"]["templates"]],
                   cat["data"]["doctor"]),
                  ([(tid, "Canal + coroană", [("Consultație", "consult", False, None),
                                              ("Igienizare", "hygiene", True, None),
                                              ("Tratament lung", "long", True, None),
                                              ("Coroană zirconiu", "", True, 4500),
                                              ("Serviciu fără medic", "orphan", False, 700)]),
                    (hyg, "Igienizare completă", [("Igienizare", "hygiene", False, None)])], ""))
        c.post_json(f"/api/patients/{pid}/doctor", {"doctor": DOC})
        res.check("врач по умолчанию — медик курант пациента",
                  _j(c.get(f"/api/patients/{pid}/plan/templates"))["data"]["doctor"], DOC)

        st, j = (lambda r: (r.status, _j(r)))(c.post_json(
            f"/api/patients/{pid}/plan", {"procedure": "Radiografie", "tooth": "11", "price": "150"}))
        assert j["code"] == "ok_card", j
        manual = (11, "Radiografie", 150, None, "", None, "planificat")

        res.check("весь шаблон на зуб 36: удача со свежей фишей",
                  _ins(c, pid, {"template_id": tid, "tooth": "36", "doctor": DOC}),
                  (200, "ok_ptpl_ins", None, True))
        whole = [(None, "Consultație", None, "consult", DOC, "d2", "planificat"),
                 (36, "Igienizare", 1000, "hygiene", DOC, "d2", "planificat"),
                 (36, "Tratament lung", None, "long", DOC, "d2", "planificat"),
                 (36, "Coroană zirconiu", 4500, None, DOC, "d2", "planificat"),
                 (None, "Serviciu fără medic", 700, "orphan", DOC, "d2", "planificat")]
        res.check("в плане — прежняя позиция и строки шаблона по порядку: зуб только у строк «с зубом», цена "
                  "прайса одним числом, диапазон — без цены, своя цена шаблона — как записана; ключи услуги и врача",
                  _plan(c, pid), [manual, *whole])
        res.check("летопись: одна строка на весь набор",
                  _adds(c, pid), ["Plan: + Radiografie (dinte 11)",
                                  "Plan: adăugat din șablonul „Canal + coroană”: 5 proceduri"])
        res.ok("вставленная позиция правится, как любая «planificat»",
               all(it["editable"] and it["deletable"] for it in _card(c, pid)["plan"]["items"]), "не правится")
        last = _card(c, pid)["plan"]["items"][-1]["id"]
        r = c.post_json(f"/api/patients/{pid}/plan/{last}/edit", {"price": "650"})
        res.check("«Editează» у вставленной позиции: цена меняется", (r.msg, _plan(c, pid)[-1][2]), ("ok_pedit", 650))

        # отмеченные строки: порядок запроса не важен, зуб и цена строки сильнее общих
        res.check("часть строк со своим зубом и ценой — удача",
                  _ins(c, pid, {"template_id": tid, "tooth": "46", "doctor": "", "rows": [
                      {"i": 3, "procedure": "Coroană zirconiu", "tooth": "47", "price": "5000"},
                      {"i": 0, "procedure": "Consultație", "tooth": "46", "price": "300"},
                      {"i": 2, "procedure": "Tratament lung", "price": "1500"},
                      {"i": 1, "tooth": "", "price": ""}]}),
                  (200, "ok_ptpl_ins", None, True))
        res.check("вставка добавляет: прежние позиции целы; строки — в порядке шаблона; строка «без зуба» зуба "
                  "не получила; пустая строка стирает зуб и цену; без врача — без ключа врача",
                  _plan(c, pid)[6:], [(None, "Consultație", 300, "consult", "", None, "planificat"),
                                      (None, "Igienizare", None, "hygiene", "", None, "planificat"),
                                      (46, "Tratament lung", 1500, "long", "", None, "planificat"),
                                      (47, "Coroană zirconiu", 5000, None, "", None, "planificat")])
        res.check("прежние шесть позиций не тронуты", _plan(c, pid)[:5], [manual, *whole[:4]])
        res.check("вторая вставка — вторая строка летописи, число процедур своё",
                  _adds(c, pid)[2:], ["Plan: adăugat din șablonul „Canal + coroană”: 4 proceduri"])
        _ins(c, pid, {"template_id": hyg, "tooth": "16", "doctor": DOC})
        res.check("одна процедура — «1 procedură»; у шаблона без строк «с зубом» общий зуб не ставится",
                  (_adds(c, pid)[-1], _plan(c, pid)[-1][0]),
                  ("Plan: adăugat din șablonul „Igienizare completă”: 1 procedură", None))

        before, feed = _plan(c, pid), _adds(c, pid)
        for what, body, want in (
                ("чужой номер зуба у строки в середине", {"template_id": tid, "tooth": "36", "rows": [
                    {"i": 0}, {"i": 1, "tooth": "99"}, {"i": 2}]}, (422, "bad_card", "tooth", False)),
                ("цена не числом у последней строки", {"template_id": tid, "rows": [
                    {"i": 0}, {"i": 1}, {"i": 4, "price": "mult"}]}, (422, "bad_card", "price", False)),
                ("чужой общий зуб", {"template_id": tid, "tooth": "9"}, (422, "bad_card", "tooth", False)),
                ("ни одной строки", {"template_id": tid, "rows": []}, (422, "bad_card", "rows", False)),
                ("строки не списком", {"template_id": tid, "rows": {"i": 0}}, (422, "bad_card", "rows", False)),
                ("шаблона нет", {"template_id": "pt999", "tooth": "36"}, (404, "tpl_gone", None, False)),
                ("шаблон не назван", {"tooth": "36"}, (404, "tpl_gone", None, False)),
                ("строка шаблона уже другая процедура", {"template_id": tid, "rows": [
                    {"i": 0}, {"i": 1, "procedure": "Detartraj"}]}, (409, "tpl_changed", None, False)),
                ("строки с таким номером в шаблоне нет", {"template_id": tid, "rows": [{"i": 0}, {"i": 5}]},
                 (409, "tpl_changed", None, False)),
                ("одна строка дважды", {"template_id": tid, "rows": [{"i": 1}, {"i": 1}]},
                 (409, "tpl_changed", None, False))):
            res.check(f"отказ: {what}", _ins(c, pid, body), want)
        res.check("после всех отказов план тот же — ни одной строки из отказанного набора", _plan(c, pid), before)
        res.check("…и летопись та же", _adds(c, pid), feed)
        res.check("пациента нет — 404", _ins(c, 999999, {"template_id": tid})[0], 404)

        # шаблон правят в настройках, пока окно вставки открыто
        c.post_json(SETTINGS, {"templates": {hyg: {"rows": [{"service_id": "consult", "tooth": False}]}}})
        res.check("строку шаблона заменили — окно со старой строкой получает отказ, а не другую процедуру",
                  _ins(c, pid, {"template_id": hyg, "rows": [{"i": 0, "procedure": "Igienizare"}]}),
                  (409, "tpl_changed", None, False))
        c.post_json(SETTINGS, {"deleted": [hyg]})
        res.check("шаблон удалили — 404 tpl_gone", _ins(c, pid, {"template_id": hyg}), (404, "tpl_gone", None, False))
        res.check("…и план по-прежнему тот же", _plan(c, pid), before)

        # подписанное согласие покрывает план до вставки и не покрывает после
        sp = new_patient(c, "Sablon Semnat", "069777002")
        c.post_json(f"/api/patients/{sp}/plan", {"procedure": "Coroană 26", "tooth": "26", "price": "3000"})
        time.sleep(1.1)
        c.post_file(f"/api/patients/{sp}/documents", "file", "acord-semnat.pdf", PDF,
                    mime="application/pdf", category="acord_plan")

        def acord() -> tuple:
            f = next(x for x in _card(c, sp)["forms"] if x["key"] == "acord_plan")
            return bool(f["signed"]), f["stale"], f["n_active"]

        res.check("подписанное согласие покрывает план", acord(), (True, False, 1))
        time.sleep(1.1)
        _ins(c, sp, {"template_id": tid, "tooth": "26", "rows": [{"i": 1}, {"i": 3}]})
        res.check("после вставки шаблона: план изменён после подписи", acord(), (True, True, 3))

        # склад: у вставленной позиции ключ услуги — техкарта услуги срабатывает
        item = _j(c.post_json("/api/stock/item", {"name": "Mănuși nitril M", "unit": "buc"}))["data"]["id"]
        r = c.post_json("/api/stock/tehcard/hygiene", {"lines": [{"item_id": item, "qty_milli": 2000}]})
        assert r.msg == "ok_stock_tc", r.body[:200]
        hid = next(it["id"] for it in _card(c, sp)["plan"]["items"] if it["procedure"] == "Igienizare")
        c.post_json(f"/api/patients/{sp}/plan/{hid}/status", {"to": "in_lucru"})
        res.check("«Finalizează» у вставленной позиции с техкартой: склад предлагает материалы",
                  c.post_json(f"/api/patients/{sp}/plan/{hid}/status", {"to": "finalizat"}).msg,
                  "ok_stock_tc_pending")
        res.check("…её материалы — из техкарты услуги",
                  [x["item"] for x in _j(c.get(f"/api/stock/plan/{hid}"))["data"]["lines"]], ["Mănuși nitril M"])


def suite_save(res: Result) -> None:
    """«Salvează ca șablon»: что переезжает из плана в шаблон клиники и что нет."""
    with _server() as s:
        c = Client(s.url).login()
        pid = new_patient(c, "Zaharia Pacientescu", "069777010")
        due = (clinic_today().replace(day=1)).isoformat()

        def add(body: dict) -> int:
            r = c.post_json(f"/api/patients/{pid}/plan", body)
            assert r.msg == "ok_card", r.body[:200]
            return max(it["id"] for it in _j(r)["data"]["plan"]["items"])

        hyg = add({"procedure": "Igienizare", "service_id": "hygiene", "tooth": "16", "doctor": DOC,
                   "price": "1200", "due_date": due})
        crown = add({"procedure": "Coroană zirconiu", "tooth": "26", "doctor": "Dr. Activ Patru", "price": "4500"})
        cons = add({"procedure": "Consultație"})                    # текст услуги, ключа нет
        own = add({"procedure": "Igienizare + fluor", "service_id": "hygiene", "price": "300"})
        refused = add({"procedure": "Tratament lung", "service_id": "long", "tooth": "36"})
        c.post_json(f"/api/patients/{pid}/plan/{refused}/status",
                    {"to": "refuzat", "motiv": "Pacientul Zaharia refuză tratamentul"})
        c.post_json(f"/api/patients/{pid}/plan/{hyg}/status", {"to": "in_lucru"})
        clean = _cfg(s)

        res.check("отмеченные позиции — новым шаблоном: удача, фиша в ответе",
                  _save(c, pid, {"name": "  Din  planul bun ", "item_ids": [refused, cons, hyg, crown, own]}),
                  (200, "ok_ptpl_new", None, True))
        cfg = _cfg(s)
        tpl = cfg["plan_templates"][0]
        res.check("шаблон: имя, пустая заметка, строки в порядке плана; «нужен зуб» — по позиции; услуга — по "
                  "ключу, а у позиции без ключа — по точному имени; дописанный текст остаётся текстом; цены не взяты",
                  tpl, {"id": "pt1", "name": "Din planul bun", "note": "", "rows": [
                      {"procedure": "Igienizare", "service_id": "hygiene", "tooth": True, "price": None},
                      {"procedure": "Coroană zirconiu", "service_id": "", "tooth": True, "price": None},
                      {"procedure": "Consultație", "service_id": "consult", "tooth": False, "price": None},
                      {"procedure": "Igienizare + fluor", "service_id": "", "tooth": False, "price": None},
                      {"procedure": "Tratament lung", "service_id": "long", "tooth": True, "price": None}]})
        res.check("запись шаблона остальной профиль не тронула",
                  {k: v for k, v in cfg.items() if k not in ("plan_templates", "seq")},
                  {k: v for k, v in clean.items() if k not in ("plan_templates", "seq")})

        res.check("«Păstrează prețurile»: цены позиций переезжают, пустая остаётся пустой",
                  (_save(c, pid, {"name": "Cu prețuri", "item_ids": [hyg, crown, cons], "keep_prices": True})[1],
                   [r["price"] for r in _cfg(s)["plan_templates"][1]["rows"]]),
                  ("ok_ptpl_new", [1200, 4500, None]))

        stored = _cfg(s)["plan_templates"]
        text = json.dumps(stored, ensure_ascii=False)
        res.check("в записи шаблона — только свои ключи", ({frozenset(t) for t in stored},
                                                          {frozenset(r) for t in stored for r in t["rows"]}),
                  ({frozenset(("id", "name", "note", "rows"))},
                   {frozenset(("procedure", "service_id", "tooth", "price"))}))
        res.ok("«нужен зуб» — да или нет, номера зуба в шаблоне нет",
               all(type(r["tooth"]) is bool for t in stored for r in t["rows"]), text)
        leaked = [w for w in ("Zaharia", "Pacientescu", "069777010", DOC, "Dr. Activ Patru", "refuză", due,
                              '"16"', '"26"', '"36"', "in_lucru", "refuzat", "planificat")
                  if w in text]
        res.check("ничего о пациенте в профиле клиники: ни имени, ни телефона, ни зубов, ни врача, ни срока, "
                  "ни причины отказа, ни статусов", leaked, [])
        res.ok("…и ни одного числа зуба среди значений строк",
               not any(v in (16, 26, 36) for t in stored for r in t["rows"] for v in r.values()), text)

        before = _cfg(s)
        other = new_patient(c, "Alt Pacient", "069777011")
        foreign = _j(c.post_json(f"/api/patients/{other}/plan", {"procedure": "Detartraj"}))["data"]["plan"]["items"][0]["id"]
        for what, body, want in (
                ("имя занято (без учёта регистра)", {"name": "din planul BUN", "item_ids": [hyg]},
                 (422, "dup_ptpl", "name", False)),
                ("имени нет", {"name": "  ", "item_ids": [hyg]}, (422, "bad_ptpl", "name", False)),
                ("ни одной позиции", {"name": "Gol", "item_ids": []}, (422, "bad_ptpl", "rows", False)),
                ("позиции не списком чисел", {"name": "Gol", "item_ids": ["1"]}, (422, "bad_ptpl", "rows", False)),
                ("позиция чужого пациента", {"name": "Străin", "item_ids": [hyg, foreign]},
                 (404, "plan_gone", None, False)),
                ("позиции нет", {"name": "Lipsă", "item_ids": [999999]}, (404, "plan_gone", None, False))):
            res.check(f"отказ: {what}", _save(c, pid, body), want)
        res.check("после отказов профиль клиники тот же", _cfg(s), before)

        res.check("сохранённый шаблон вставляется другому пациенту — круг замкнут",
                  (_ins(c, other, {"template_id": "pt2", "tooth": "44", "doctor": DOC})[1], _plan(c, other)[1:]),
                  ("ok_ptpl_ins", [(44, "Igienizare", 1200, "hygiene", DOC, "d2", "planificat"),
                                   (44, "Coroană zirconiu", 4500, None, DOC, "d2", "planificat"),
                                   (None, "Consultație", None, "consult", DOC, "d2", "planificat")]))
        res.check("сохранение шаблона план пациента не изменило и строки в летопись не дало",
                  (len(_plan(c, pid)), len(_adds(c, pid))), (5, 5))


def suite_rights(res: Result) -> None:
    """Вставляет любой, кто видит план; шаблоном сохраняют директор и
    регистратура, врач — нет (ветка PIN-файла клиники)."""
    with _server(env=NO_KEY) as s:
        boss, ana, med = _team(s)
        tid, = _make(boss, CANAL)
        pid = new_patient(boss, "Sablon Roluri", "069777020")
        anon = Client(s.url)
        res.check("без входа: окно шаблонов, вставка и сохранение — 401",
                  [anon.get(f"/api/patients/{pid}/plan/templates").status,
                   _ins(anon, pid, {"template_id": tid})[0],
                   _save(anon, pid, {"name": "X", "item_ids": [1]})[0]], [401, 401, 401])
        res.check("шаблоны клиники в окне вставки видят все трое",
                  [[t["id"] for t in _j(x.get(f"/api/patients/{pid}/plan/templates"))["data"]["templates"]]
                   for x in (boss, ana, med)], [[tid]] * 3)
        res.check("врач по умолчанию у пациента без медика куранта: врачу — он сам, остальным — пусто",
                  [_j(x.get(f"/api/patients/{pid}/plan/templates"))["data"]["doctor"] for x in (boss, ana, med)],
                  ["", "", "Dr. Activ Trei"])
        res.check("вставляют все трое",
                  [_ins(x, pid, {"template_id": tid, "tooth": "36", "rows": [{"i": 1}]})[:2]
                   for x in (boss, ana, med)], [(200, "ok_ptpl_ins")] * 3)
        res.check("…и в плане три позиции", len(_plan(boss, pid)), 3)
        feed = _j(boss.get(f"/api/patients/{pid}/activity"))["data"]["items"]
        res.check("летопись называет, кто вставил", [a["who"] for a in feed if a["kind"] == "plan_add"][::-1],
                  ["Director", "Ana Rusu", "Dr. Activ Trei"])
        ids = [it["id"] for it in _card(boss, pid)["plan"]["items"]]
        res.check("шаблоном сохраняют директор и регистратура",
                  [_save(x, pid, {"name": n, "item_ids": ids})[:2] for x, n in ((boss, "De la director"),
                                                                             (ana, "De la recepție"))],
                  [(200, "ok_ptpl_new")] * 2)
        before = _cfg(s)
        r = med.post_json(f"/api/patients/{pid}/plan/save-template", {"name": "De la medic", "item_ids": ids})
        res.check("врачу сохранение шаблоном закрыто — 403 no_access", (r.status, r.msg), (403, "no_access"))
        res.check("…и профиль клиники после отказа тот же", _cfg(s), before)
        res.check("в профиле — три шаблона: исходный и два сохранённых",
                  [t["name"] for t in _cfg(s)["plan_templates"]],
                  ["Canal + coroană", "De la director", "De la recepție"])


def _worker_tx(tmpdir: str) -> None:
    """Набор со строкой, которую база не принимает, — по `db.add_plan_items`
    напрямую: правило фиши такую строку до базы не допускает."""
    base = pathlib.Path(tmpdir)
    os.environ.update({"CLINIC_CONFIG": str(base / "clinic.json"),
                       "DATABASE_URL": f"sqlite:///{base / 'dental.db'}", "ADMIN_KEY": ""})
    sys.path.insert(0, str(BOT))
    from app import db

    def row(proc) -> dict:
        return {"tooth": 36, "procedure": proc, "doctor": "", "price_mdl": 100,
                "service_id": None, "doctor_id": None}

    async def count(pid: int) -> tuple:
        return (await db._fetchval("SELECT COUNT(*) FROM plan_items WHERE patient_id = ?", pid),
                await db._fetchval("SELECT COUNT(*) FROM activity WHERE patient_id = ? AND kind = 'plan_add'",
                                   pid))

    async def main() -> None:
        await db.init([])
        try:
            pid = await db.create_patient(db.manual_key("069777030"), "Tx Unu", "069777030")
            print("good", await db.add_plan_items(pid, [row("A"), row("B")], "Plan: set", tooth=36))
            print("after_good", await count(pid))
            try:
                await db.add_plan_items(pid, [row("C"), row(None), row("D")], "Plan: rupt")
                print("bad", "accepted")
            except Exception as e:                                      # noqa: BLE001
                print("bad", type(e).__name__)
                await db._CONN.rollback()
            print("after_bad", await count(pid))
            print("empty", await db.add_plan_items(pid, [], "Plan: gol"))
            print("after_empty", await count(pid))
            print("order", await db._fetch("SELECT procedure FROM plan_items WHERE patient_id = ? ORDER BY id",
                                           pid))
        finally:
            await db.close()

    asyncio.run(main())


def suite_tx(res: Result) -> None:
    """Набор позиций в базе — всё или ничего, и одна строка летописи на набор."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_ptx_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", base / "clinic.json")
        r = subprocess.run([str(PYTHON), str(pathlib.Path(__file__).resolve()), "worker-tx", str(base)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, env=dict(os.environ))
        got = dict(line.split(" ", 1) for line in (r.stdout or "").splitlines() if " " in line)
        if not res.ok("проба поднялась", r.returncode == 0 and got.get("good") == "2",
                      f"rc={r.returncode}: {got} {(r.stderr or '')[-1200:]}"):
            return
        res.check("набор из двух строк: две позиции и ОДНА строка летописи", got.get("after_good"), "(2, 1)")
        res.check("строка в середине набора не принята базой — исключение, а не тихий пропуск",
                  got.get("bad"), "IntegrityError")
        res.check("…и от набора в плане нет ни строки до неё, ни строки после, летопись та же",
                  got.get("after_bad"), "(2, 1)")
        res.check("пустой набор ничего не пишет", (got.get("empty"), got.get("after_empty")), ("0", "(2, 1)"))
        res.check("порядок позиций — порядок строк набора", got.get("order"),
                  "[{'procedure': 'A'}, {'procedure': 'B'}]")
    finally:
        shutil.rmtree(base, ignore_errors=True)


_WORKERS = {"worker-tx": _worker_tx}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in _WORKERS:
        _WORKERS[sys.argv[1]](sys.argv[2])
    else:
        print("Это файл наборов. Запускать: python tests\\run_tests.py plan_insert")
        sys.exit(2)
