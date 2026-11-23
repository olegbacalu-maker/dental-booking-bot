"""Шаблоны плана лечения клиники (`clinic.json › plan_templates`, `core/plan_tpl.py`).

Шаблон — набор позиций плана: имя, заметка, строки по порядку (процедура из
прайса по `service_id` или текстом, «нужен зуб», цена или «из прайса»). Правят
его директор и регистратура на экране «Setări › Șabloane», вкладка «Plan de
tratament» (`GET/POST /api/settings/plan-templates`, право `PERM_TEMPLATES`).
Здесь:
- правило чистыми функциями: разбор тела, правка по тронутому, терпеливое
  чтение файла, счётчик id;
- экран настроек: запись шлёт только тронутое, отказы названы, id не
  выдаётся дважды, строка следует за прайсом по id;
- ни один писатель `clinic.json` шаблоны и их счётчик не стирает — писатели
  перечислены сторожем `test_structure`, набор обязан пройти по каждому;
- права на ветке PIN-файла: директор и регистратура правят оба вида шаблонов,
  врач — нет; регистратуре хаб «Setări» открыт одной плиткой.
"""
import copy
import json
import sys

from harness import BOT, Client, Result, Server, shell_model
from test_api import NO_KEY
import test_structure

sys.path.insert(0, str(BOT))
from app import engine as appeng  # noqa: E402
from app.core import plan_tpl  # noqa: E402

API = "/api/settings/plan-templates"
CONSULT = "/api/settings/templates"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92"
       b"\xef\x00\x00\x00\x00IEND\xaeB`\x82")

IMPLANT = {"name": "Implant + coroană", "note": "pentru molari", "rows": [
    {"service_id": "consult", "tooth": False},
    {"procedure": "Implant dentar", "tooth": True},
    {"service_id": "hygiene", "tooth": False, "price": 900}]}
IMPLANT_ROWS = [
    {"procedure": "Consultație", "service_id": "consult", "tooth": False, "price": None},
    {"procedure": "Implant dentar", "service_id": "", "tooth": True, "price": None},
    {"procedure": "Igienizare", "service_id": "hygiene", "tooth": False, "price": 900}]
CANAL = {"name": "Tratament de canal + coroană", "rows": [{"procedure": "Tratament endodontic"},
                                                           {"procedure": "Coroană zirconiu", "price": "4500"}]}


def _j(r) -> dict:
    return json.loads(r.body)


def _cfg(s: Server) -> dict:
    return json.loads(s.clinic.read_text(encoding="utf-8"))


def _tpls(c: Client) -> list:
    return _j(c.get(API))["data"]["templates"]


def _fail(r) -> tuple:
    return r.status, r.msg, _j(r).get("field", "")


def suite_rule(res: Result) -> None:
    """Правило шаблона чистыми функциями на подменённом профиле."""
    saved = (dict(appeng.SERVICES), appeng.CONFIG, list(appeng.PLAN_TEMPLATES))
    try:
        appeng.SERVICES.clear()
        appeng.SERVICES.update({"imp": {"ro": "Implant dentar", "ru": "Имплант"},
                                "cor": {"ro": "Coroană zirconiu", "ru": "Коронка"}})
        appeng.CONFIG = {"seq": {"doctor": 4, "service": 9}}
        appeng.PLAN_TEMPLATES.clear()
        c = plan_tpl.clean
        res.check("новый шаблон: услуга прайса — её имя и ключ, текст — без ключа, цена числом или пусто",
                  c({"name": "  Implant   +  coroană ", "rows": [
                      {"service_id": "imp", "procedure": "что угодно", "price": " 9000 "},
                      {"procedure": " Bont  protetic ", "tooth": False, "price": ""},
                      {"service_id": "zzz", "procedure": "Fostul serviciu", "price": 0}]}),
                  {"name": "Implant + coroană", "note": "", "rows": [
                      {"procedure": "Implant dentar", "service_id": "imp", "tooth": True, "price": 9000},
                      {"procedure": "Bont protetic", "service_id": "", "tooth": False, "price": None},
                      {"procedure": "Fostul serviciu", "service_id": "", "tooth": True, "price": 0}]})
        bad = []
        for field, raw in (("name", {"name": " ", "rows": [{"procedure": "x"}]}),
                           ("name", {"name": 5, "rows": [{"procedure": "x"}]}),
                           ("note", {"name": "A", "note": 7, "rows": [{"procedure": "x"}]}),
                           ("rows", {"name": "A"}), ("rows", {"name": "A", "rows": []}),
                           ("rows", {"name": "A", "rows": "x"}), ("rows", {"name": "A", "rows": ["x"]}),
                           ("rows", {"name": "A", "rows": [{"procedure": " "}]}),
                           ("rows", {"name": "A", "rows": [{"service_id": "zzz"}]}),
                           ("rows", {"name": "A", "rows": [{"procedure": "x", "tooth": "da"}]}),
                           ("rows", {"name": "A", "rows": [{"procedure": "x"}] * (plan_tpl.ROWS_MAX + 1)}),
                           ("price", {"name": "A", "rows": [{"procedure": "x", "price": "abc"}]}),
                           ("price", {"name": "A", "rows": [{"procedure": "x", "price": -1}]}),
                           ("price", {"name": "A", "rows": [{"procedure": "x", "price": 1.5}]}),
                           ("price", {"name": "A", "rows": [{"procedure": "x", "price": True}]}),
                           ("price", {"name": "A", "rows": [{"procedure": "x",
                                                             "price": plan_tpl.PRICE_MAX + 1}]}),
                           ("rows", []), ("rows", "x")):
            try:
                c(raw)
                bad.append(f"принято: {raw!r}")
            except ValueError as e:
                if str(e) != field:
                    bad.append(f"{raw!r}: поле {e} вместо {field}")
        res.ok("кривой шаблон — ValueError с именем виновного поля", not bad, "; ".join(bad))
        res.check("длина режется: имя, заметка, текст процедуры",
                  (lambda t: (len(t["name"]), len(t["note"]), len(t["rows"][0]["procedure"])))(
                      c({"name": "n" * 200, "note": "z" * 500, "rows": [{"procedure": "p" * 500}]})),
                  (plan_tpl.NAME_MAX, plan_tpl.NOTE_MAX, plan_tpl.PROC_MAX))

        prev = {"id": "pt1", "name": "Vechi", "note": "N", "rows": [{"procedure": "Ceva", "service_id": "gone",
                                                                    "tooth": True, "price": 5}], "extra": 1}
        res.check("merge: нет поля — как лежит в профиле (и чужой ключ, и строка без разбора)",
                  plan_tpl.merge(prev, {"note": ""}), {**prev, "note": ""})
        res.check("merge: строки — одно поле, приходят целиком",
                  plan_tpl.merge(prev, {"rows": [{"service_id": "cor"}]})["rows"],
                  [{"procedure": "Coroană zirconiu", "service_id": "cor", "tooth": True, "price": None}])

        appeng.CONFIG = {"seq": {"doctor": 4, "service": 9, "plan_tpl": 7}, "plan_templates": [
            {"id": "pt2", "name": "A", "note": "", "rows": [{"procedure": "x", "service_id": "", "tooth": True,
                                                              "price": None}]}]}
        appeng._read_plan_templates(appeng.CONFIG)
        out, seq, created = plan_tpl.apply({"new": [{"name": "B", "rows": [{"service_id": "imp"}]}]})
        res.check("id — от счётчика, а не от живых шаблонов; чужие счётчики целы",
                  (created, [t["id"] for t in out], seq), (["pt8"], ["pt2", "pt8"],
                                                           {"doctor": 4, "service": 9, "plan_tpl": 8}))
        res.check("без новых шаблонов счётчик не трогается, нетронутый шаблон — тот же объект",
                  (lambda r: (r[1], r[0][0] is appeng.CONFIG["plan_templates"][0]))(plan_tpl.apply({})),
                  ({"doctor": 4, "service": 9, "plan_tpl": 7}, True))
        dup = ""
        try:
            plan_tpl.apply({"new": [{"name": " a ", "rows": [{"procedure": "x"}]}]})
        except ValueError as e:
            dup = str(e)
        res.check("одинаковые имена без учёта регистра — отказ «dup»", dup, "dup")

        # файл правят и руками: кривое пропускается, старт не падает
        appeng._read_plan_templates({"plan_templates": [
            {"id": "pt1", "name": " Bun ", "note": None, "rows": [
                {"procedure": "Implant dentar", "service_id": "imp", "price": 9000},
                {"procedure": ""}, "мусор", {"procedure": "Text", "tooth": 0, "price": "100"}]},
            {"id": "pt1", "name": "Dublura", "rows": []}, {"id": "", "name": "Fără id", "rows": []},
            {"id": "pt3", "name": "", "rows": []}, {"id": "pt4", "name": "Fără rânduri"}, "мусор", None]})
        res.check("терпеливое чтение: один вид строки, кривые записи и строки пропущены",
                  appeng.PLAN_TEMPLATES,
                  [{"id": "pt1", "name": "Bun", "note": "", "rows": [
                      {"procedure": "Implant dentar", "service_id": "imp", "tooth": True, "price": 9000},
                      {"procedure": "Text", "service_id": "", "tooth": False, "price": None}]}])
        for junk in ({"plan_templates": {"pt1": {}}}, {"plan_templates": 5}, {}):
            appeng._read_plan_templates(junk)
            res.check(f"не список ({junk}) — шаблонов нет, без падения", appeng.PLAN_TEMPLATES, [])
        appeng.CONFIG = {"plan_templates": 5}
        res.check("запись поверх мусора в файле не падает", plan_tpl.apply({})[0], [])
    finally:
        appeng.SERVICES.clear()
        appeng.SERVICES.update(saved[0])
        appeng.CONFIG = saved[1]
        appeng.PLAN_TEMPLATES[:] = saved[2]


def suite_settings(res: Result) -> None:
    """Экран «Șabloane › Plan de tratament»: данные, тронутое, отказы, id, прайс."""
    with Server(keep_dir=True) as s:
        res.check("без входа — 401", (Client(s.url).get(API).status,
                                      Client(s.url).post_json(API, {}).status), (401, 401))
        c = Client(s.url).login()
        d = _j(c.get(API))["data"]
        res.check("пустой каталог, прайс по порядку с ценой строкой прайса",
                  (d["templates"], [(x["id"], x["label"], x["price"]) for x in d["services"]][:3]),
                  ([], [("consult", "Consultație", "gratuit"), ("pain", "Durere acută", "în aceeași zi"),
                        ("hygiene", "Igienizare", "1000 MDL")]))
        res.check("пределы — с сервера", d["max"], {"name": 60, "note": 120, "rows": 40,
                                                   "price": 1_000_000, "templates": 100})
        before = _cfg(s)
        r = c.post_json(API, {})
        res.check("пустая запись в профиль без шаблонов добавляет только пустой раздел",
                  (r.msg, _cfg(s)), ("ok_set", {**before, "plan_templates": []}))
        hub = {t["href"]: t for t in _j(c.get("/api/settings/hub"))["data"]["tiles"]}
        res.check("плитка хаба «Șabloane»: группа и пустой каталог словами",
                  (lambda t: (t["label"], t["group"], t["hint"]))(hub["/admin/settings/templates"]),
                  ("Șabloane", "medici", [{"t": "niciun șablon încă"}]))

        r = c.post_json(API, {"new": [IMPLANT, CANAL]})
        res.check("два новых: ok_set, id по порядку тела", (r.msg, _j(r)["data"]["created"]),
                  ("ok_set", ["pt1", "pt2"]))
        t = _tpls(c)
        res.check("первый шаблон: имя, заметка, строки в одном виде",
                  t[0], {"id": "pt1", "name": "Implant + coroană", "note": "pentru molari",
                         "rows": IMPLANT_ROWS})
        res.check("второй: цена строкой цифр — числом, «нужен зуб» по умолчанию да",
                  t[1]["rows"], [{"procedure": "Tratament endodontic", "service_id": "", "tooth": True,
                                  "price": None},
                                 {"procedure": "Coroană zirconiu", "service_id": "", "tooth": True,
                                  "price": 4500}])
        cfg = _cfg(s)
        res.check("в файле — тот же вид и счётчик id",
                  (cfg["plan_templates"][0]["rows"], cfg["seq"].get("plan_tpl")), (IMPLANT_ROWS, 2))
        res.ok("в шаблоне нет ничего о пациенте: ключи записи и строки перечислены",
               all(set(x) == {"id", "name", "note", "rows"}
                   and all(set(row) == {"procedure", "service_id", "tooth", "price"} for row in x["rows"])
                   for x in cfg["plan_templates"]), f"{cfg['plan_templates']}")
        hub = {x["href"]: x for x in _j(c.get("/api/settings/hub"))["data"]["tiles"]}
        res.check("плитка считает шаблоны плана", hub["/admin/settings/templates"]["hint"],
                  [{"t": "consultație: 0 · plan de tratament: 2"}])
        page = c.get("/admin/settings/templates")
        res.ok("страница — узел React экрана", page.status == 200
               and 'data-screen="settings_templates"' in page.body, f"код {page.status}")

        before = _cfg(s)
        r = c.post_json(API, {})
        res.check("пустое тело — ok_set, файл профиля тождественен", (r.msg, _cfg(s)), ("ok_set", before))
        r = c.post_json(API, {"templates": {"pt1": {"note": ""}}})
        res.check("правка одного поля: остальное цело (нет поля = не сообщали), сосед не тронут",
                  (r.msg, _tpls(c)[0], _cfg(s)["plan_templates"][1]),
                  ("ok_set", {"id": "pt1", "name": "Implant + coroană", "note": "", "rows": IMPLANT_ROWS},
                   before["plan_templates"][1]))
        c.post_json(API, {"templates": {"pt1": {"rows": [IMPLANT["rows"][2], IMPLANT["rows"][0]]}}})
        res.check("строки приходят целиком: порядок новый, третьей строки нет",
                  [x["procedure"] for x in _tpls(c)[0]["rows"]], ["Igienizare", "Consultație"])

        before = _cfg(s)
        row = {"procedure": "x"}
        for field, body in (("name", {"new": [{"name": "", "rows": [row]}]}),
                            ("rows", {"new": [{"name": "Gol", "rows": []}]}),
                            ("rows", {"new": [{"name": "Fără procedură", "rows": [{"tooth": True}]}]}),
                            ("price", {"new": [{"name": "Preț", "rows": [{**row, "price": "o mie"}]}]}),
                            ("price", {"templates": {"pt1": {"rows": [{**row, "price": -5}]}}}),
                            ("name", {"templates": {"pt2": {"name": " "}}}),
                            ("rows", {"templates": []}), ("rows", {"new": {}}), ("rows", {"deleted": "pt1"}),
                            ("rows", {"templates": {"pt1": "x"}})):
            res.check(f"отказ {body} — 422 bad_ptpl, поле {field}", _fail(c.post_json(API, body)),
                      (422, "bad_ptpl", field))
        for body in ({"new": [{**CANAL, "name": "implant + COROANĂ"}]},
                     {"templates": {"pt2": {"name": "Implant + coroană"}}},
                     {"new": [{"name": "Nou", "rows": [row]}, {"name": "nou", "rows": [row]}]}):
            res.check(f"одинаковое имя {list(body)} — 422 dup_ptpl", _fail(c.post_json(API, body)),
                      (422, "dup_ptpl", "name"))
        res.check("после отказов файл профиля тот же", _cfg(s), before)

        r = c.post_json(API, {"deleted": ["pt2"], "templates": {"pt2": {"name": "Stafie"}}})
        res.check("удаление: ok_set, шаблона нет, правка удалённого не воскрешает",
                  (r.msg, [x["id"] for x in _tpls(c)]), ("ok_set", ["pt1"]))
        r = c.post_json(API, {"templates": {"pt2": {"name": "Stafie"}, "pt9": {"name": "N-a fost"}}})
        res.check("правка шаблона, удалённого в другой вкладке, молча пропущена",
                  (r.msg, [x["name"] for x in _tpls(c)]), ("ok_set", ["Implant + coroană"]))
        r = c.post_json(API, {"new": [{**CANAL, "name": "Implant + coroană (copie)"}]})
        res.check("id удалённого не выдаётся заново", (_j(r)["data"]["created"], _cfg(s)["seq"]["plan_tpl"]),
                  (["pt3"], 3))

        # строка шаблона держится за услугу по id: переименование прайса она
        # видит, а услуга, убранная из прайса, остаётся прежним текстом
        rows = _j(c.get("/api/settings/services"))["data"]["services"]
        c.post_json("/api/settings/services", {"services": [
            {**x, "ro": "Igienizare profesională"} if x["id"] == "hygiene" else x for x in rows]})
        res.check("услугу переименовали в прайсе — строка шаблона под новым именем, ключ тот же",
                  (lambda x: (x["procedure"], x["service_id"]))(_tpls(c)[0]["rows"][0]),
                  ("Igienizare profesională", "hygiene"))
        c.post_json("/api/settings/services", {"services": [x for x in rows if x["id"] != "hygiene"]})
        res.check("услугу убрали из прайса — строка остаётся текстом без ключа, цена шаблона цела",
                  _tpls(c)[0]["rows"][0], {"procedure": "Igienizare", "service_id": "", "tooth": False,
                                           "price": 900})
        kept = _tpls(c)
    try:
        with Server(dir_=s.dir) as s2:
            res.check("после перезапуска шаблоны читаются из файла теми же",
                      _tpls(Client(s2.url).login()), kept)
    finally:
        s.drop()


def _writer_acts(c: Client) -> dict:
    """Писатель `clinic.json` → действия, которые его зовут: (ответ, ждём код).
    Ключи — как в сторожe `test_structure._CFG_WRITERS`."""
    def get(path: str) -> dict:
        return _j(c.get(path))["data"]

    def theme() -> dict:
        d = get("/api/settings/theme")
        return {"style": d["style"], "primary": d["primary"], "menu": d["menu"], "font": d["font"],
                "card": d["card"], "logo_topbar": True, "odo_btn": False}

    def services(change) -> dict:
        return {"services": change(get("/api/settings/services")["services"])}

    doc = {"name": "Dr. Doi Nou", "spec": "Chirurgie", "phone": "101", "email": "doi@x.md",
           "color": "#123456", "auto_color": False, "work_from": 9, "work_to": 15, "status": "activ"}
    S, D = "app/modules/settings/", "app/modules/doctors/routes.py:"
    return {
        S + "api.py:api_clinic_save": [
            lambda: (c.post_json("/api/settings/clinic", {"name": "Clinica Nouă", "phone": "022000111",
                                                          "address": {"ro": "str. A", "ru": "ул. А"}}),
                     "ok_set")],
        S + "api.py:api_hours_save": [
            lambda: (c.post_json("/api/settings/hours", {"hours": {
                **get("/api/settings/hours")["hours"], "sun": None}}), "ok_set")],
        S + "api.py:api_services_save": [
            lambda: (c.post_json("/api/settings/services", services(lambda rows: rows)), "ok_set"),
            lambda: (c.post_json("/api/settings/services", services(
                lambda rows: [*rows, {"ro": "Serviciu nou", "ru": "", "price": "500"}])), "ok_set")],
        S + "api.py:api_templates_save": [
            lambda: (c.post_json(CONSULT, {"templates": {"hygiene": {"diagnostic": "Depozite."}}}), "ok_set")],
        "app/core/plan_tpl.py:store": [lambda: (c.post_json(API, {}), "ok_set")],
        "app/core/tarife.py:store": [
            lambda: (c.post_json("/api/tarife", {"cats_new": [{"key": "a", "name": "Terapie"}],
                                                 "new": [{"ro": "Restaurare", "price": "900", "cat": "a"}]}),
                     "ok_tarife"),
            lambda: (c.post_json("/api/tarife", {"services": {"hygiene": {"plan": False}}}), "ok_tarife")],
        S + "api.py:api_theme_save": [lambda: (c.post_json("/api/settings/theme", theme()), "ok_theme")],
        S + "routes.py:_logo_action": [
            lambda: (c.post_file("/api/settings/theme/logo", "file", "logo.png", PNG), "ok_logo"),
            lambda: (c.post_json("/api/settings/theme/logo/delete", {}), "no_logo")],
        S + "api.py:api_backup_auto": [
            lambda: (c.post_json("/api/settings/backup/auto", {"enabled": False}), "ok_bkp_stop")],
        S + "api.py:api_sms_save": [
            lambda: (c.post_json("/api/settings/sms", {"day_before": {"on": False}}), "ok_sms")],
        D + "_save_cfg": [
            lambda: (c.post_json("/api/doctors", {"name": "Dr. Cinci", "spec": "Orto"}), "new_med"),
            lambda: (c.post_json("/api/doctors/colors", {}), "ok_med"),
            lambda: (c.post_json("/api/doctors/d2/services", {"services": [
                x["id"] for x in get("/api/settings/services")["services"]]}), "ok_svc_med"),
            lambda: (c.post_file("/api/doctors/d1/photo", "file", "foto.png", PNG), "ok_photo"),
            lambda: (c.post_json("/api/doctors/d1/photo/delete", {}), "ok_med"),
            lambda: (c.post_json("/api/doctors/d1/parallel", {"on": True}), "ok_par_on")],
        D + "_save_doctor": [
            lambda: (c.post_json("/api/doctors/d2", {**doc, "rooms": [{"name": "Cabinet 1"},
                                                                   {"name": "Cabinet 2"}]}), "ok_med"),
            lambda: (c.post_json("/api/doctors/d2", {**doc, "rooms": [{"name": "Cabinet 1"}]}), "ok_med")],
    }


def suite_writers(res: Result) -> None:
    """Каждый писатель `clinic.json` оставляет шаблоны плана и их счётчик как
    были: профиль пишется целиком, и забытый раздел стирался бы молча."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json(API, {"new": [IMPLANT, CANAL]})
        c.post_json(API, {"deleted": ["pt2"]})
        acts = _writer_acts(c)
        res.check("действие есть на каждого писателя из сторожа — и ни одного лишнего",
                  sorted(acts), sorted(test_structure._CFG_WRITERS))
        keep = copy.deepcopy((_cfg(s)["plan_templates"], _cfg(s)["seq"]["plan_tpl"]))
        res.check("засев: один шаблон, счётчик помнит удалённый", (len(keep[0]), keep[1]), (1, 2))
        for who, steps in acts.items():
            for i, step in enumerate(steps, 1):
                r, want = step()
                cfg = _cfg(s)
                res.check(f"{who} #{i}: действие удалось ({want}), шаблоны плана и счётчик целы",
                          (r.msg, cfg.get("plan_templates"), (cfg.get("seq") or {}).get("plan_tpl")),
                          (want, *keep))
        res.check("после всех писателей новый шаблон получает следующий id, не занятый прежде",
                  _j(c.post_json(API, {"new": [CANAL]}))["data"]["created"], ["pt3"])


def _team(s: Server) -> tuple[Client, Client, Client]:
    """Директор (1111), регистратура «Ana Rusu» (4444), врач d3 (2222)."""
    boss = Client(s.url)
    boss.post("/admin/setup", pin1="1111", pin2="1111")
    for body in ({"uid": "d3", "name": "Dr. Activ Trei", "role": "medic", "doctor_id": "d3", "pin": "2222"},
                 {"uid": "ana", "name": "Ana Rusu", "role": "receptie", "pin": "4444"}):
        r = boss.post_json("/api/settings/users", body)
        if r.status != 200:
            raise AssertionError(f"учётка не заведена: {r.status} {r.body[:200]}")

    def login(pin):
        x = Client(s.url)
        x.post("/admin/login", password=pin, next="/admin")
        return x
    return boss, login("4444"), login("2222")


def suite_rights(res: Result) -> None:
    """Шаблоны — директор и регистратура, врачу нет; хаб «Setări» открыт тому,
    у кого есть хоть одна плитка, и показывает только разрешённые."""
    with Server(env=NO_KEY) as s:
        boss, ana, med = _team(s)

        def nav(c: Client) -> list:
            return [i["href"] for i in shell_model(c.get("/admin").body)["nav"]["items"]]

        def can(c: Client) -> tuple:
            m = shell_model(c.get("/admin").body)["identity"]["can"]
            return m["settings"], m["templates"]

        res.check("регистратура читает оба вида шаблонов", (ana.get(API).status, ana.get(CONSULT).status),
                  (200, 200))
        res.check("регистратура пишет шаблон плана", ana.post_json(API, {"new": [IMPLANT]}).msg, "ok_set")
        res.check("…и шаблон консультации",
                  ana.post_json(CONSULT, {"templates": {"hygiene": {"diagnostic": "Depozite."}}}).msg, "ok_set")
        res.check("директор видит оба, записанные регистратурой",
                  ([x["name"] for x in _tpls(boss)],
                   next(x["tpl"]["diagnostic"] for x in _j(boss.get(CONSULT))["data"]["services"]
                        if x["id"] == "hygiene")), (["Implant + coroană"], "Depozite."))
        res.check("директор правит шаблон плана", boss.post_json(API, {"templates": {"pt1": {"note": "x"}}}).msg,
                  "ok_set")

        before = _cfg(s)
        for what, r in (("читать шаблоны плана", med.get(API)), ("читать шаблоны консультации", med.get(CONSULT)),
                        ("писать шаблон плана", med.post_json(API, {"deleted": ["pt1"]})),
                        ("писать шаблон консультации",
                         med.post_json(CONSULT, {"templates": {"hygiene": {"diagnostic": "x"}}})),
                        ("читать хаб", med.get("/api/settings/hub"))):
            res.check(f"врачу закрыто: {what} — 403 no_access", (r.status, r.msg), (403, "no_access"))
        for path in ("/admin/settings", "/admin/settings/templates"):
            r = med.get(path)
            res.ok(f"врачу закрыта страница {path}", r.status == 303 and r.msg == "no_access", f"{r!r}")
        res.check("после отказов врачу профиль тот же", _cfg(s), before)

        page = ana.get("/admin/settings")
        res.ok("регистратуре хаб открыт — узел React", page.status == 200
               and 'data-screen="settings_hub"' in page.body, f"{page!r}")
        res.check("…и в нём «Șabloane» и вход во вкладку «Google Calendar»",
                  sorted((t["href"], t["label"]) for t in _j(ana.get("/api/settings/hub"))["data"]["tiles"]),
                  [("/admin/google", "Google Calendar"), ("/admin/settings/templates", "Șabloane")])
        res.ok("страница шаблонов регистратуре открыта, крошка ведёт в хаб",
               (lambda p: p.status == 200 and "/admin/settings" in
                [x["href"] for x in shell_model(p.body)["frame"]["crumbs"]])(ana.get("/admin/settings/templates")),
               "закрыта или без крошки")
        boss_tiles = [t["href"] for t in _j(boss.get("/api/settings/hub"))["data"]["tiles"]]
        res.ok("директор видит все плитки, шаблоны среди них",
               {"/admin/settings/templates", "/admin/settings/system", "/admin/settings/clinic",
                "/admin/settings/services", "/admin/settings/security"} <= set(boss_tiles), f"{boss_tiles}")
        # остальные настройки для регистратуры закрыты, как были: отказ — в
        # маршруте, по адресу, набранному руками
        for path in ("/admin/settings/system", "/admin/settings/clinic", "/admin/settings/theme",
                     "/admin/settings/hours", "/admin/settings/services", "/admin/settings/security",
                     "/admin/settings/backup", "/admin/settings/crypt", "/admin/settings/faq"):
            r = ana.get(path)
            res.ok(f"регистратуре закрыта страница {path}", r.status == 303 and r.msg == "no_access", f"{r!r}")
        for path in ("/api/settings/system", "/api/settings/clinic", "/api/settings/theme",
                     "/api/settings/hours", "/api/settings/services", "/api/settings/security",
                     "/api/settings/backup", "/api/settings/crypt", "/api/settings/faq"):
            r = ana.get(path)
            res.check(f"регистратуре закрыт {path} — 403 no_access", (r.status, r.msg), (403, "no_access"))
        r = ana.post_json("/api/settings/services", {"services": []})
        res.check("регистратура не пишет прайс — 403 no_access", (r.status, r.msg), (403, "no_access"))

        res.check("пункт меню «Setări»: у директора и регистратуры есть, у врача нет",
                  ["/admin/settings" in nav(x) for x in (boss, ana, med)], [True, True, False])
        res.check("права клиенту: настройки — только директор, шаблоны — директор и регистратура",
                  [can(x) for x in (boss, ana, med)], [(True, True), (False, True), (False, False)])
