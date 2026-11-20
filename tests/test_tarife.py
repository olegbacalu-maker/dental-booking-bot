"""Прайс «Servicii și tarife» (`core/tarife.py`, `/api/tarife*`, `/admin/tarife*`).

Прайс — те же строки `clinic.json › services`, что типы записи агенды; у строки
необязательные `where` (`agenda` | `plan`, нет ключа — оба места) и `cat` (категория
из `service_cats`). Два экрана пишут один список, поэтому главное здесь — что ни один
не стирает чужое:
- профиль 2.20.0 без новых ключей читается как раньше и пересохраняется ТОЖДЕСТВЕННО
  обоими экранами;
- пересохранение «Setări › Servicii» (вид агенды, `scope: "agenda"`) не трогает строки
  и категории прайса; пересохранение прайса не трогает длительность, врачей, цвет,
  rechemare и шаблон дневника;
- агенда не видит и не принимает строку «только plan»: окно записи журнала и фиши,
  смена процедуры, Google, услуги врача, Rechemări; план видит её;
- импорт таблицы: проверка с предпросмотром, запуск по отпечатку, ничего не удаляется;
- права на ветке PIN-файла: директор и регистратура правят, врач только смотрит.
"""
import json
import sys
from datetime import timedelta

from harness import BOT, Client, Result, Server, add_appt, clinic_today, new_patient, shell_model
from test_api import NO_KEY

sys.path.insert(0, str(BOT))
from app.core import xlsx  # noqa: E402

API = "/api/tarife"
SVC = "/api/settings/services"


def _j(r) -> dict:
    return json.loads(r.body)


def _cfg(s: Server) -> dict:
    return json.loads(s.clinic.read_text(encoding="utf-8"))


def _raw(s: Server) -> str:
    return s.clinic.read_text(encoding="utf-8")


def _day(n: int = 1) -> str:
    return (clinic_today() + timedelta(days=n)).isoformat()


def _svc(s: Server, sid: str) -> dict:
    return next(x for x in _cfg(s)["services"] if x["id"] == sid)


def _fail(r) -> tuple:
    return r.status, r.msg, _j(r).get("field", "")


def _agenda_view(c: Client) -> list:
    """Что пришлёт экран «Setări › Servicii» в виде агенды: свои строки как есть."""
    return [x for x in _j(c.get(SVC))["data"]["services"] if x["where"] != "plan"]


def _seed(c: Client) -> dict:
    """Две категории и три строки прайса «только plan»."""
    r = c.post_json(API, {"cats_new": [{"key": "a", "name": "Terapie"}, {"key": "b", "name": "Protetică"}],
                          "new": [{"ro": "Restaurare 1 suprafață", "price": "900", "cat": "a"},
                                  {"ro": "Restaurare 2 suprafețe", "ru": "Пломба 2", "price": "1 200 MDL",
                                   "cat": "a"},
                                  {"ro": "Coroană zirconiu", "price": "4500–5000", "cat": "b"}]})
    if r.msg != "ok_tarife":
        raise AssertionError(f"засев прайса: {r!r} {r.body[:300]}")
    return _j(r)["data"]


def suite_identity(res: Result) -> None:
    """Профиль 2.20.0 (без `where`, `cat`, `service_cats`): модель как раньше,
    пересохранение обоими экранами — файл до байта тот же."""
    with Server() as s:
        c = Client(s.url).login()
        fixture = _cfg(s)
        m = _j(c.get(API))["data"]
        res.check("все услуги в обоих местах, категорий нет",
                  ([x["where"] for x in m["services"]], m["cats"], m["uncat"]),
                  (["both"] * 5, [], 5))
        res.check("цена: сумма только у строки из одного числа",
                  [(x["id"], x["amount"]) for x in m["services"]],
                  [("consult", None), ("pain", None), ("hygiene", 1000), ("orphan", 500), ("long", 2000)])
        res.check("двуязычная цена старого профиля читается RO",
                  m["services"][0]["price"], "gratuit")
        rows = _j(c.get(SVC))["data"]["services"]
        res.check("«Setări › Servicii»: у каждой строки место и категория",
                  {(x["where"], x["cat"]) for x in rows}, {("both", "")})
        # прежнее тело, как его шлёт вкладка 2.20.0: без scope, без новых ключей.
        # Первая запись нормализует профиль, как и в 2.20.0: двуязычная цена — строкой
        # RO, подсказка `_comment` уходит, счётчики `seq` появляются
        old = [{k: v for k, v in x.items() if k not in ("where", "cat")} for x in rows]
        res.check("старое тело без scope — ok_set", c.post_json(SVC, {"services": old}).msg, "ok_set")
        want = [{**x, "price": x["price"]["ro"] if isinstance(x["price"], dict) else x["price"]}
                for x in fixture["services"]]
        res.check("…услуги — как записала бы 2.20.0, без новых ключей", _cfg(s)["services"], want)
        res.check("…ни раздела категорий, ни счётчика категорий",
                  ("service_cats" in _cfg(s), sorted(_cfg(s)["seq"])), (False, ["doctor", "service"]))
        raw = _raw(s)
        res.check("второе пересохранение старым телом — файл до байта тот же",
                  (c.post_json(SVC, {"services": old}).msg, _raw(s) == raw), ("ok_set", True))
        res.check("тело с where/cat, как вернул GET, — тоже тождественно",
                  (c.post_json(SVC, {"services": rows}).msg, _raw(s) == raw), ("ok_set", True))
        res.check("вид агенды (scope agenda) — тождественно",
                  (c.post_json(SVC, {"services": rows, "scope": "agenda"}).msg, _raw(s) == raw), ("ok_set", True))
        res.check("пустое тело прайса — ok и файл тот же",
                  (c.post_json(API, {}).msg, _raw(s) == raw), ("ok_tarife", True))
        res.check("прайс шлёт ту же цену и имя — файл тот же",
                  (c.post_json(API, {"services": {"hygiene": {"ro": "Igienizare", "price": "1000 MDL"}}}).msg,
                   _raw(s) == raw), ("ok_tarife", True))
        res.check("незнакомый scope — отказ", c.post_json(SVC, {"services": rows, "scope": "x"}).msg, "bad_set")


def suite_views(res: Result) -> None:
    """Два экрана одного списка: ни один не стирает чужое; места решают, кто видит."""
    with Server(keep_dir=True) as s:
        c = Client(s.url).login()
        # поля агенды у двух строк: длительность, цвет, rechemare, шаблон дневника
        rows = _j(c.get(SVC))["data"]["services"]
        for x in rows:
            if x["id"] == "hygiene":
                x.update(duration=45, color="green", recall=6)
        res.check("засев полей агенды", c.post_json(SVC, {"services": rows}).msg, "ok_set")
        c.post_json("/api/settings/templates", {"templates": {"hygiene": {"diagnostic": "Depozite."}}})
        hyg = _svc(s, "hygiene")
        d = _seed(c)
        res.check("новые строки прайса — «только plan», id от счётчика, категории — c1, c2",
                  (d["created"], [(x["where"], x["cat"]) for x in d["services"][-3:]],
                   [(x["id"], x["name"], x["n"]) for x in d["cats"]]),
                  ({"services": ["s1", "s2", "s3"], "cats": {"a": "c1", "b": "c2"}},
                   [("plan", "c1"), ("plan", "c1"), ("plan", "c2")],
                   [("c1", "Terapie", 2), ("c2", "Protetică", 1)]))
        res.check("сумма «1 200 MDL» — 1200, диапазон — подсказкой",
                  [(x["amount"], x["price_hint"]) for x in d["services"][-2:]],
                  [(1200, ""), (None, "4500–5000")])
        cfg = _cfg(s)
        res.check("счётчики в профиле, прочие целы", cfg["seq"], {**cfg["seq"], "service": 3, "service_cat": 2})

        # прайс правит свою строку агенды: цена, категория — поля агенды целы
        r = c.post_json(API, {"services": {"hygiene": {"price": "1100", "cat": "c1"}}})
        now = _svc(s, "hygiene")
        res.check("правка прайса у строки агенды: цена и категория сменились",
                  (r.msg, now["price"], now["cat"]), ("ok_tarife", "1100", "c1"))
        res.check("…длительность, цвет, врачи, rechemare, шаблон, место — как были",
                  {k: now.get(k) for k in ("duration", "color", "docs", "recall", "tpl", "where", "ru")},
                  {k: hyg.get(k) for k in ("duration", "color", "docs", "recall", "tpl", "where", "ru")})

        # пересохранение «Setări › Servicii» видом агенды прайс не трогает
        before = _cfg(s)
        view = _agenda_view(c)
        res.check("вид агенды — пять прежних строк", [x["id"] for x in view],
                  ["consult", "pain", "hygiene", "orphan", "long"])
        r = c.post_json(SVC, {"services": [{k: v for k, v in x.items() if k not in ("price", "cat")}
                                           for x in view], "scope": "agenda"})
        after = _cfg(s)
        res.check("вид агенды без цены и категории — ok_set, профиль тот же",
                  (r.msg, after), ("ok_set", before))
        # строку «оба» убрали из вида агенды — осталась в прайсе
        r = c.post_json(SVC, {"services": [x for x in view if x["id"] != "orphan"], "scope": "agenda"})
        res.check("строка «оба» ушла из вида агенды — стала «только plan», поля целы",
                  (r.msg, _svc(s, "orphan")), ("ok_set", {**before["services"][3], "where": "plan"}))
        res.check("строки прайса и категории после этого целы",
                  ([x for x in _cfg(s)["services"] if x["id"] in ("s1", "s2", "s3")],
                   _cfg(s)["service_cats"]),
                  ([x for x in before["services"] if x["id"] in ("s1", "s2", "s3")], before["service_cats"]))
        # «doar agendă» и обратно — с экрана агенды полем where
        view = _agenda_view(c)
        for x in view:
            if x["id"] == "long":
                x["where"] = "agenda"
        res.check("экран агенды ставит «doar agendă»",
                  (c.post_json(SVC, {"services": view, "scope": "agenda"}).msg, _svc(s, "long").get("where")),
                  ("ok_set", "agenda"))
        res.check("незнакомое место — отказ с полем",
                  _fail(c.post_json(SVC, {"services": [{**view[0], "where": "x"}], "scope": "agenda"})),
                  (422, "bad_set", "where"))
        res.check("агенда без единой услуги — отказ",
                  _fail(c.post_json(SVC, {"services": [{**x, "where": "plan"} for x in view]})),
                  (422, "svc_agenda_empty", "where"))
        res.check("строку «doar agendă» прайс возвращает в прайс (plan: true) — «оба»",
                  (c.post_json(API, {"services": {"long": {"plan": True}}}).msg, "where" in _svc(s, "long")),
                  ("ok_tarife", False))
        res.check("прайс снимает «plan» у строки «оба» — «doar agendă», строка жива",
                  (c.post_json(API, {"services": {"long": {"plan": False}}}).msg, _svc(s, "long")["where"]),
                  ("ok_tarife", "agenda"))
        r = c.post_json(API, {"services": {"s3": {"plan": False}}})
        res.check("снят последний «plan» у строки только прайса — удалена",
                  (r.msg, [x["id"] for x in _cfg(s)["services"] if x["id"] == "s3"]), ("ok_tarife", []))

        # кто что видит
        card = lambda pid: _j(c.get(f"/api/patients/{pid}"))["data"]  # noqa: E731
        pid = new_patient(c, "Ion Prețuri", "069111222")
        cm = card(pid)
        res.check("фиша: окно записи — только агенда (без строк прайса)",
                  [x["id"] for x in cm["appoint"]["services"]], ["consult", "pain", "hygiene", "long"])
        res.check("…услуги окна записи и врачи — одни и те же ключи",
                  sorted(cm["appoint"]["doctors"]), sorted(x["id"] for x in cm["appoint"]["services"]))
        res.check("фиша: прайс плана — по категориям, «Fără categorie» последней, без «doar agendă»",
                  [(x["id"], x["cat_name"]) for x in cm["plan_services"]],
                  [("hygiene", "Terapie"), ("s1", "Terapie"), ("s2", "Terapie"),
                   ("consult", ""), ("pain", ""), ("orphan", "")])
        res.check("одонтограмма — тот же прайс плана",
                  [x["id"] for x in _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]["services"]],
                  [x["id"] for x in cm["plan_services"]])
        res.check("шаблоны плана: прайс — строки плана",
                  [x["id"] for x in _j(c.get("/api/settings/plan-templates"))["data"]["services"]],
                  [x["id"] for x in cm["plan_services"]])
        form = _j(c.get(f"/api/schedule/day?date={_day()}"))["data"]["form"]["services"]
        res.check("журнал: окно записи без строк только прайса", [x["id"] for x in form],
                  ["consult", "pain", "hygiene", "long"])
        r = add_appt(c, _day(), "10:00", "Pacient Plan", "069222333", "d2", "s1")
        res.check("журнал: запись на строку только прайса — отказ с полем",
                  _fail(r), (422, "svc_not_agenda", "service"))
        r = c.post_json(f"/api/patients/{pid}/appoint",
                        {"date": _day(), "time": "11:00", "doctor": "d2", "service": "orphan"})
        res.check("фиша: запись на строку только прайса — отказ с полем",
                  _fail(r), (422, "svc_not_agenda", "service"))
        res.check("фиша: свободных часов у строки только прайса нет",
                  _j(c.get(f"/api/patients/{pid}/slots?date={_day()}&doctor=d2&service=s1"))["data"]["slots"], [])
        r = add_appt(c, _day(), "12:00", "Pacient Agenda", "069222444", "d2", "consult")
        res.check("журнал: запись на тип агенды — как была", r.msg, "ok")
        aid = max(int(k) for k in _j(c.get(f"/api/schedule/day?date={_day()}"))["data"]["cards"])
        res.check("смена процедуры визита: в списке только агенда (и врач визита её делает)",
                  [x["id"] for x in _j(c.get(f"/api/schedule/appointments/{aid}/service"))["data"]["options"]],
                  ["consult", "pain", "long"])
        r = c.post_json(f"/api/schedule/appointments/{aid}/service?date={_day()}", {"service_id": "s1"})
        res.check("смена процедуры на строку только прайса — отказ", r.msg, "svc_not_agenda")
        doc = _j(c.get("/api/doctors/d2"))["data"]
        names = [x["id"] for x in doc.get("services", [])]
        res.ok("карточка врача: галочки — только агенда", names and "s1" not in names
               and "orphan" not in names, f"{names}")
        res.check("услуги врача: сохранение без строк прайса их врачей не трогает",
                  (c.post_json("/api/doctors/d2/services", {"services": names}).msg,
                   _svc(s, "orphan").get("docs")), ("ok_svc_med", ["d1"]))

        # категории: правка, порядок, удаление
        r = c.post_json(API, {"cats": {"c1": {"name": "Terapie dentară"}}, "cats_order": ["c2", "c1"]})
        res.check("переименование и порядок категорий",
                  (r.msg, [(x["id"], x["name"]) for x in _j(r)["data"]["cats"]]),
                  ("ok_tarife", [("c2", "Protetică"), ("c1", "Terapie dentară")]))
        res.check("одинаковые имена категорий — отказ",
                  _fail(c.post_json(API, {"cats_new": [{"key": "z", "name": "protetică"}]})),
                  (422, "dup_tarif", "name"))
        r = c.post_json(API, {"cats_removed": ["c1"]})
        res.check("удалена категория — её строки «Fără categorie»",
                  (r.msg, [x for x in _cfg(s)["services"] if x.get("cat") == "c1"], _j(r)["data"]["uncat"]),
                  ("ok_tarife", [], 6))
        res.check("новая категория не получает id удалённой",
                  _j(c.post_json(API, {"cats_new": [{"key": "k", "name": "Chirurgie"}]}))["data"]["created"],
                  {"services": [], "cats": {"k": "c3"}})

        # отказы прайса
        res.check("пустое имя — отказ с полем", _fail(c.post_json(API, {"new": [{"ro": " "}]})),
                  (422, "bad_tarif", "ro"))
        res.check("имя длиннее предела — отказ, не обрезка",
                  _fail(c.post_json(API, {"new": [{"ro": "x" * 61}]})), (422, "bad_tarif", "ro"))
        res.check("имя занято (без регистра) — отказ",
                  _fail(c.post_json(API, {"new": [{"ro": "igienizare"}]})), (422, "dup_tarif", "ro"))
        res.check("RU совпало с чужим RO — отказ",
                  _fail(c.post_json(API, {"services": {"s1": {"ru": "Consultație"}}})), (422, "dup_tarif", "ro"))
        res.check("незнакомая категория — 409", _fail(c.post_json(API, {"services": {"s1": {"cat": "c99"}}})),
                  (409, "tarif_gone", ""))
        res.check("удалённая в другой вкладке услуга — 409",
                  _fail(c.post_json(API, {"services": {"s3": {"price": "1"}}})), (409, "tarif_gone", ""))
        res.check("plan не bool — отказ с полем",
                  _fail(c.post_json(API, {"services": {"s1": {"plan": "da"}}})), (422, "bad_tarif", "plan"))
        before = _cfg(s)
        res.check("после отказов профиль тот же", _cfg(s), before)

        # перезапуск читает то же
        kept = _j(c.get(API))["data"]
    try:
        with Server(dir_=s.dir) as s2:
            res.check("после перезапуска модель прайса та же", _j(Client(s2.url).login().get(API))["data"],
                      kept)
    finally:
        s.drop()


def _book(rows: list) -> bytes:
    return xlsx.book(["Categoria", "Denumire", "Denumire RU", "Preț"], rows, sheet_name="Tarife")


def suite_import(res: Result) -> None:
    """Импорт таблицы: предпросмотр, запуск по отпечатку, ничего не удаляется;
    выгрузка читается импортом обратно без изменений."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json(API, {"services": {"long": {"plan": False}}})      # «doar agendă»

        def raw(path: str, blob: bytes):
            return c._do(path, blob, {"Content-Type": "application/octet-stream"})
        blob = _book([["Igienă", "Igienizare", "", "1000 MDL"],                 # то же
                      ["Igienă", "igienizare", "", "1"],                        # повтор в файле
                      ["Terapie", "Restaurare 1 suprafață", "Пломба 1", "900"],  # новая
                      ["", "Tratament lung", "", "2500"],                       # цена и «в прайс»
                      ["Terapie", "Durere acută", "", ""],                       # категория
                      ["", "", "", "100"],                                      # без имени
                      ["Terapie", "Consultație", "Острая боль", ""]])            # чужое RU
        before = _raw(s)
        r = raw("/api/tarife/import/check?name=tarife.xlsx", blob)
        d = _j(r)["data"]
        res.check("проверка: действия по строкам",
                  [(x["line"], x["act"], x["what"], x["err"]) for x in d["rows"]],
                  [(2, "changed", ["cat"], ""), (3, "bad", [], "dup"), (4, "new", [], ""),
                   (5, "changed", ["price", "plan"], ""), (6, "changed", ["cat"], ""),
                   (7, "bad", [], "name"), (8, "bad", [], "dup")])
        res.check("…счётчики и новые категории", (d["counts"], d["cats_new"]),
                  ({"new": 1, "changed": 3, "same": 0, "bad": 3}, ["Igienă", "Terapie"]))
        res.check("…прежняя цена в строке", d["rows"][3]["old_price"], "2000 MDL")
        res.check("проверка ничего не пишет", _raw(s), before)
        r = raw("/api/tarife/import/run?name=tarife.xlsx&token=x", blob)
        res.check("чужой отпечаток — 409", (r.status, r.msg), (409, "tarife_import_stale"))
        r = raw(f"/api/tarife/import/run?name=tarife.xlsx&token={d['token']}", blob)
        res.check("запуск — ok и счётчики", (r.msg, _j(r)["data"]["imported"]),
                  ("ok_tarife_import", d["counts"]))
        cfg = _cfg(s)
        res.check("новая строка — только plan, в новой категории",
                  {k: v for k, v in _svc(s, "s1").items()},
                  {"id": "s1", "ro": "Restaurare 1 suprafață", "ru": "Пломба 1", "price": "900",
                   "cat": "c2", "where": "plan"})
        res.check("строка агенды: цена из файла, снова в прайсе, длительность цела",
                  (_svc(s, "long")["price"], "where" in _svc(s, "long"), _svc(s, "long")["duration"]),
                  ("2500", False, 120))
        res.check("ничего не удалено", len(cfg["services"]), 6)
        res.check("категории — по порядку файла", [c_["name"] for c_ in cfg["service_cats"]], ["Igienă", "Terapie"])
        r = raw(f"/api/tarife/import/run?name=tarife.xlsx&token={d['token']}", blob)
        res.check("тот же отпечаток после записи — 409 (прайс сменился)", r.msg, "tarife_import_stale")

        # выгрузка → импорт: всё «без изменений»
        x = c.get("/admin/tarife.xlsx")
        res.ok("выгрузка — xlsx", x.status == 200 and x.raw[:2] == b"PK", f"{x!r}")
        d = _j(raw("/api/tarife/import/check?name=back.xlsx", x.raw))["data"]
        res.check("выгрузка, загруженная обратно, — всё без изменений",
                  d["counts"], {"new": 0, "changed": 0, "same": 6, "bad": 0})
        r = raw(f"/api/tarife/import/run?name=back.xlsx&token={d['token']}", x.raw)
        res.check("…и запуск отказывает: нечего менять", (r.status, r.msg), (422, "tarife_import_empty"))
        res.check("не таблица — отказ словами", raw("/api/tarife/import/check?name=a.pdf", b"%PDF-1.4").msg,
                  "stock_not_table")
        res.check("таблица без «Denumire» — отказ",
                  raw("/api/tarife/import/check?name=a.csv", "Nume;Pret\nA;1\n".encode()).msg,
                  "tarife_import_cols")
        csv = "Secțiune;Serviciu;Tarif\nEndo;Tratament canal 3;2400\n".encode()
        res.check("csv и синонимы заголовков", [(x["cat"], x["ro"], x["price"], x["act"]) for x in _j(
            raw("/api/tarife/import/check?name=a.csv", csv))["data"]["rows"]],
            [("Endo", "Tratament canal 3", "2400", "new")])


def _team(s: Server) -> tuple[Client, Client, Client]:
    """Директор (1111), регистратура (4444), врач d3 (2222)."""
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
    """Ветка PIN-файла: прайс правят директор и регистратура, врач только смотрит."""
    with Server(env=NO_KEY) as s:
        boss, ana, med = _team(s)
        r = ana.post_json(API, {"new": [{"ro": "Albire", "price": "3000"}]})
        res.check("регистратура правит прайс", r.msg, "ok_tarife")
        res.check("…директор видит строку", [x["ro"] for x in _j(boss.get(API))["data"]["services"]][-1], "Albire")
        res.check("can_edit: директор и регистратура — да, врач — нет",
                  [_j(x.get(API))["data"]["can_edit"] for x in (boss, ana, med)], [True, True, False])
        before = _cfg(s)
        for what, r in (("писать прайс", med.post_json(API, {"services": {"s1": {"price": "1"}}})),
                        ("проверять импорт", med._do("/api/tarife/import/check?name=a.csv", b"Denumire\nA\n",
                                                      {"Content-Type": "application/octet-stream"})),
                        ("запускать импорт", med._do("/api/tarife/import/run?name=a.csv&token=x", b"Denumire\nA\n",
                                                      {"Content-Type": "application/octet-stream"}))):
            res.check(f"врачу закрыто: {what} — 403 no_access", (r.status, r.msg), (403, "no_access"))
        res.check("после отказов врачу профиль тот же", _cfg(s), before)
        res.check("врач читает прайс", med.get(API).status, 200)
        res.check("выгрузка открыта всем вошедшим", [x.get("/admin/tarife.xlsx").status for x in (boss, ana, med)],
                  [200, 200, 200])
        res.check("регистратура прайс правит, а «Setări › Servicii» — нет",
                  (ana.post_json(SVC, {"services": _j(boss.get(SVC))["data"]["services"]}).status), 403)
        res.check("право клиенту can.prices",
                  [shell_model(x.get("/admin").body)["identity"]["can"]["prices"] for x in (boss, ana, med)],
                  [True, True, False])
        # экран прайса: страница React у всех вошедших, пункт меню — тоже у всех (врачу — только чтение)
        pages = [x.get("/admin/tarife") for x in (boss, ana, med)]
        res.check("/admin/tarife — экран React «tarife» у директора, регистратуры и врача",
                  [(p.status, 'data-screen="tarife"' in p.body) for p in pages], [(200, True)] * 3)
        res.check("пункт меню «Servicii și tarife» у всех трёх ролей, адрес /admin/tarife",
                  [[i["href"] for i in shell_model(p.body)["nav"]["items"] if i["key"] == "tarife"] for p in pages],
                  [["/admin/tarife"]] * 3)
        res.check("…и на странице прайса он выбран", shell_model(pages[2].body)["nav"]["active"], "tarife")
        anon = Client(s.url)
        res.check("без входа — 401", anon.get(API).status, 401)
        res.check("без входа страница уводит на вход", anon.get("/admin/tarife").status, 303)
