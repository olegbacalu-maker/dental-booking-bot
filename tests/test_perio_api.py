"""Пародонтограмма (C23): `/api/…/perio` — лист данными, действия через JSON.

`test_perio.py` стережёт КЛИНИКУ: что измерения доехали до четырёх
представлений (экран, печатный лист, §4 печатной 043/e, выгрузка по 195-му) и
что арифметика итога сходится. Здесь стережётся то, что уезжает в браузер
помимо чисел: список осмотров с датами и счётом, порядок шести точек в
колонке зуба, точка кровоточивости ТОЛЬКО у глубины, приглушённый
отсутствующий зуб, подпись точки словами, справочники и пороги, снимок врача
в выпадающем списке — и что запись стирает ровно то, о чём сообщила, не трогая
работу второго рабочего места.

До 13.10 эталоном служила старая страница листа (`suite_pin`); она снята, и
её записанные руками ожидания живут в `suite_api` значениями.

Контракт — docs/dentpilot-2/clinical-chart.md.
"""
import json
import pathlib
import re
from datetime import datetime, timezone

from harness import Client, Result, Server, pid_by_phone

PERM = ([18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
        + [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38])


def _j(r) -> dict:
    return json.loads(r.body)


def _pid(c: Client, phone: str) -> int:
    return pid_by_phone(c, phone)


def _new_exam(c: Client, pid: int) -> int:
    """Новый осмотр (`POST …/perio/exams`) и его id."""
    return _j(c.post_json(f"/api/patients/{pid}/perio/exams", {}))["data"]["exam"]["id"]


def _seed(c: Client) -> dict:
    """Пациент с осмотром: измеренные 16 и 46, отсутствующий 26 и удалённый 38
    в одонтограмме (карта обязана приглушить оба), врач и заметка осмотра."""
    c.post_json("/api/patients", {"name": "Perio Pin", "phone": "069400400"})
    pid = _pid(c, "069400400")
    t = f"/api/patients/{pid}/teeth"
    c.post_json(f"{t}/26", {"state": "lipsa", "surfaces": []})
    c.post_json(f"{t}/38", {"state": "extras", "surfaces": []})
    base = f"/admin/patient/{pid}"
    eid = _new_exam(c, pid)
    # 16 — карманы 4 и 5 мм, две кровоточащие точки, подвижность I и фуркация
    # II; 46 — ровные двойки
    r = c.post_json(f"/api/patients/{pid}/perio/{eid}", {
        "teeth": {"16": _row(pd=[3, 2, 3, 4, 2, 5], rec=[1, 0, 0, 0, 0, 2], bop="010010",
                             mob=1, furc=2),
                  "46": _row(pd=[2] * 6)},
        "covers": PERM, "doctor": "Dr. Activ Doi", "note": "reevaluare"})
    assert r.msg == "ok_perio", r.body[:200]
    return {"pid": pid, "eid": eid, "base": base}


def _row(pd=None, rec=None, bop="000000", mob=0, furc=0) -> dict:
    """Строка зуба ЦЕЛИКОМ — так её шлёт экран и только так принимает API."""
    return {"pd": pd or [0] * 6, "rec": rec or [0] * 6,
            "bop": bop, "mob": mob, "furc": furc}


def _strip_hits(svg: str) -> str:
    return re.sub(r"<g class='sfz'[^>]*>.*?</g>", "", svg)


def suite_api(res: Result) -> None:
    """`GET /api/patients/{pid}/perio` — лист данными; запись через JSON —
    белыми списками разбора (`teeth_svg`), правилом `covers` и кодами
    MSG_BANNER."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/patients/1/perio").status, 401)
        c = Client(s.url).login()
        res.check("чужая фиша — 404", c.get("/api/patients/777/perio").status, 404)
        d = _seed(c)
        pid, eid = d["pid"], d["eid"]
        j = _j(c.get(f"/api/patients/{pid}/perio"))["data"]
        res.check("состав", sorted(j),
                  sorted(["patient", "exams", "exam", "rev", "rows", "teeth",
                          "arches", "sites", "summary", "limits", "grades",
                          "doctors", "colors"]))
        res.check("цвета полосы кармана для 3D над листом — по ключам порогов",
                  sorted(j["colors"]), ["deep", "severe"])
        res.check("осмотр выбран свежий, с датой, врачом, заметкой и счётом зубов",
                  ({k: v for k, v in j["exam"].items() if k != "at"},
                   bool(re.fullmatch(r"\d\d\.\d\d\.\d{4}", j["exam"]["at"])), len(j["exams"]),
                   j["exams"][0] == j["exam"]),
                  ({"id": eid, "doctor": "Dr. Activ Doi", "note": "reevaluare", "teeth": 2},
                   True, 1, True))
        res.ok("отпечаток осмотра едет на экран — с ним запись и вернётся",
               len(j["rev"]) == 12, f"rev {j['rev']!r}")
        res.check("измерения: шесть точек глубины и рецессии, маска кровоточивости, степени",
                  j["rows"]["16"],
                  {"tooth": 16, "pd": [3, 2, 3, 4, 2, 5], "rec": [1, 0, 0, 0, 0, 2],
                   "bop": "010010", "mob": 1, "furc": 2, "cal": [4, 2, 3, 4, 2, 7]})
        res.check("в карте только измеренные зубы — «не измеряли» и «ноль» не одно и то же",
                  sorted(j["rows"]), ["16", "46"])
        res.check("CAL считает сервер, и только там, где измерена глубина",
                  _j(c.post_json(f"/api/patients/{pid}/perio/{eid}",
                                 {"teeth": {"17": _row(pd=[0, 3, 0, 0, 0, 0],
                                                       rec=[2, 2, 0, 0, 0, 0])}}))["data"]["rows"]["17"]["cal"],
                  [0, 5, 0, 0, 0, 0])
        r = c.post_json(f"/api/patients/{pid}/perio/{eid}",
                        {"teeth": {"16": {"pd": [3, 3, 3, 3, 3, 3]}}, "covers": [16]})
        res.check("строка зуба без остальных полей — отказ, а не тихое обнуление",
                  (r.status, _j(r)["code"], _j(r).get("field")), (422, "bad_perio", "teeth"))
        res.check("после отказа измерения зуба целы",
                  _j(c.get(f"/api/patients/{pid}/perio"))["data"]["rows"]["16"]["rec"],
                  [1, 0, 0, 0, 0, 2])

        j = _j(c.get(f"/api/patients/{pid}/perio"))["data"]
        # 16 + 46 + одна точка 17: 13 измеренных, 2 кровоточат → 15%;
        # 34 мм / 13 = 2.6; карманы 4 и 5 мм; три зуба
        res.check("сводка: BOP от измеренных точек, средняя глубина, карманы, зубы",
                  [j["summary"][k] for k in ("bop", "pd_mean", "deep", "teeth")],
                  [15, 2.6, 2, 3])
        res.check("сводка целиком: тяжёлые карманы, подвижные зубы, фуркации, средний CAL",
                  {k: j["summary"][k] for k in ("sites", "severe", "mob", "furc", "cal_mean")},
                  {"sites": 13, "severe": 0, "mob": [[16, 1]], "furc": [[16, 2]], "cal_mean": 3.0})
        res.check("порядок точек — канон, с полным словом на каждую",
                  [(x["key"], x["label"]) for x in j["sites"]],
                  [("MV", "mezio-vestibular"), ("V", "vestibular"), ("DV", "disto-vestibular"),
                   ("ML", "mezio-lingual"), ("L", "lingual / palatinal"), ("DL", "disto-lingual")])
        res.check("дуги: только постоянные зубы, тем же порядком, что на листе",
                  j["arches"]["upper"] + j["arches"]["lower"], PERM)
        res.check("пороги и потолки ввода — серверные",
                  j["limits"], {"mm_max": 15, "mob_max": 3, "furc_max": 3, "deep": 4, "severe": 6})
        res.check("степени словами", (j["grades"]["mob"]["2"], j["grades"]["furc"]["3"]),
                  ("gr. II", "gr. III"))
        res.check("отсутствующие зубы помечены сервером, остальные — нет",
                  sorted(n for n, t in j["teeth"].items() if t["absent"]), ["26", "38"])
        res.check("зуб знает своё состояние и подпись",
                  (j["teeth"]["26"]["state"], j["teeth"]["26"]["title"], j["teeth"]["11"]["state"]),
                  ("lipsa", "26 · Lipsă", "ok"))
        res.check("на листе все 32 постоянных зуба и ни одного молочного",
                  (len(j["teeth"]), [n for n in j["teeth"] if int(n) > 50]), (32, []))
        odo = _j(c.get(f"/api/patients/{pid}/odontogram"))["data"]
        res.check("рисунок зуба — та же геометрия, что у одонтограммы, без целей поверхностей",
                  {n: j["teeth"][n]["svg"]["frontal"] for n in ("16", "26", "38")},
                  {n: _strip_hits(odo["teeth"][n]["svg"]["frontal"]) for n in ("16", "26", "38")})
        res.check("пациент и справочник врачей",
                  (j["patient"], j["doctors"][1]), ({"id": pid, "name": "Perio Pin"}, "Dr. Activ Doi"))

        # ---- запись осмотра через JSON ----
        r = c.post_json(f"/api/patients/{pid}/perio/{eid}",
                        {"teeth": {"16": {"pd": [5, 5, 5, 5, 5, 5], "rec": [0] * 6,
                                          "bop": [1, 0, 0, 0, 0, 0], "mob": 2, "furc": 0}},
                         "covers": [16]})
        j = _j(r)["data"]
        res.check("измерения записаны, кровоточивость списком тоже понята",
                  (r.status, _j(r)["code"], j["rows"]["16"]["pd"], j["rows"]["16"]["bop"],
                   j["rows"]["16"]["mob"]),
                  (200, "ok_perio", [5, 5, 5, 5, 5, 5], "100000", 2))
        res.check("показывали только 16 — остальные зубы осмотра целы",
                  (sorted(j["rows"]), j["rows"]["46"]["pd"]), (["16", "17", "46"], [2] * 6))
        before = j["rows"]["16"]
        j2 = _j(c.post_json(f"/api/patients/{pid}/perio/{eid}",
                            {"teeth": {"16": {"pd": [5, 5, 5, 5, 5, 5], "rec": [0] * 6,
                                              "bop": "100000", "mob": 2, "furc": 0}},
                             "covers": [16]}))["data"]
        res.check("пересохранение без единой правки тождественно", j2["rows"]["16"], before)
        j3 = _j(c.post_json(f"/api/patients/{pid}/perio/{eid}", {"teeth": {}}))["data"]
        res.check("без поля covers не стирается ничего — «не сообщали» ≠ «стереть»",
                  sorted(j3["rows"]), ["16", "17", "46"])
        j4 = _j(c.post_json(f"/api/patients/{pid}/perio/{eid}",
                            {"teeth": {}, "covers": [17]}))["data"]
        res.check("сообщили про 17 и не прислали измерений — стёрт только он",
                  sorted(j4["rows"]), ["16", "46"])
        res.check("врач и заметка без полей не тронуты",
                  (j4["exam"]["doctor"], j4["exam"]["note"]), ("Dr. Activ Doi", "reevaluare"))
        j5 = _j(c.post_json(f"/api/patients/{pid}/perio/{eid}",
                            {"teeth": {}, "doctor": "Dr. Nimeni", "note": "  a doua  "}))["data"]
        res.check("чужой врач — пусто, а не отказ; заметка обрезана по краям",
                  (j5["exam"]["doctor"], j5["exam"]["note"]), ("", "a doua"))
        c.post_json(f"/api/patients/{pid}/perio/{eid}",
                    {"teeth": {}, "doctor": "Dr. Activ Doi"})
        r = c.post_json("/api/doctors/d2", {"name": "Dr. Activ Doi Popescu"})
        # ⚠️ Переименование обязано СОСТОЯТЬСЯ: проверка, которая бьёт мимо
        # маршрута, зеленела бы всегда — прежнее имя так и осталось бы в
        # справочнике, и стирать подпись было бы нечему.
        res.check("врач переименован (иначе проверка ниже бессмысленна)",
                  (r.msg, "Dr. Activ Doi Popescu" in
                   _j(c.get(f"/api/patients/{pid}/perio"))["data"]["doctors"]),
                  ("ok_med", True))
        j7 = _j(c.post_json(f"/api/patients/{pid}/perio/{eid}",
                            {"teeth": {"16": _row(pd=[3] * 6)}, "covers": [16],
                             "doctor": "Dr. Activ Doi"}))["data"]
        res.check("врача переименовали — прежняя подпись осмотра не стирается",
                  j7["exam"]["doctor"], "Dr. Activ Doi")
        j8 = _j(c.post_json(f"/api/patients/{pid}/perio/{eid}",
                            {"teeth": {}, "doctor": "Dr. Nimeni"}))["data"]
        res.check("а чужое имя по-прежнему не принимается", j8["exam"]["doctor"], "")
        j6 = _j(c.post_json(f"/api/patients/{pid}/perio/{eid}",
                            {"teeth": {"16": {"pd": [99, -1, "3", None, 2, 3], "rec": [1],
                                              "bop": "zz1", "mob": 9, "furc": "2"}},
                             "covers": [16]}))["data"]
        res.check("мусор отброшен белыми списками разбора: длина шести точек цела",
                  j6["rows"]["16"],
                  {"tooth": 16, "pd": [0, 0, 3, 0, 2, 3], "rec": [1, 0, 0, 0, 0, 0],
                   "bop": "001000", "mob": 0, "furc": 2, "cal": [0, 0, 3, 0, 2, 3]})
        r = c.post_json(f"/api/patients/{pid}/perio/{eid}",
                        {"teeth": {"55": _row(pd=[3] * 6), "99": _row(pd=[3] * 6)},
                         "covers": [55, 99]})
        res.check("молочный и несуществующий зуб на лист не попадают",
                  sorted(_j(r)["data"]["rows"]), ["16", "46"])

        # ---- осмотры: новый, выбор, снятие ----
        r = c.post_json(f"/api/patients/{pid}/perio/exams", {})
        j = _j(r)["data"]
        new_id = j["exam"]["id"]
        res.check("новый осмотр выбран сразу и пуст, прошлый на месте",
                  (r.status, _j(r)["code"], j["exam"]["teeth"], j["rows"],
                   [x["id"] for x in j["exams"]]),
                  (200, "ok_perio_new", 0, {}, [new_id, eid]))
        res.check("прошлый осмотр открывается по ?exam=",
                  _j(c.get(f"/api/patients/{pid}/perio?exam={eid}"))["data"]["exam"]["id"], eid)
        res.check("чужой ?exam= — свежий осмотр, а не чужая карта",
                  _j(c.get(f"/api/patients/{pid}/perio?exam=999999"))["data"]["exam"]["id"], new_id)
        r = c.post_json(f"/api/patients/{pid}/perio/{new_id}/delete", {})
        res.check("пустой осмотр снят, выбран прошлый",
                  (r.status, _j(r)["code"], _j(r)["data"]["exam"]["id"]), (200, "ok_perio_del", eid))
        r = c.post_json(f"/api/patients/{pid}/perio/{eid}/delete", {})
        res.check("осмотр с измерениями не снимается — 409 с объяснением",
                  (r.status, _j(r)["code"], "măsurători" in _j(r)["text"]),
                  (409, "bad_perio_del", True))
        r = c.post_json(f"/api/patients/{pid}/perio/999999", {"teeth": {}})
        res.check("чужой осмотр — 404 bad_perio", (r.status, _j(r)["code"]), (404, "bad_perio"))
        res.check("не JSON — 422",
                  c.post(f"/api/patients/{pid}/perio/{eid}", chart="16:3,3,3,3,3,3").status, 422)
        res.check("чужой Origin — 403",
                  c.post_json(f"/api/patients/{pid}/perio/exams", {},
                              headers={"Origin": "http://evil.example"}).status, 403)

        # ---- границы и мусор: отказ конвертом, а не пятисотой и не удалением
        huge = 2 ** 63          # в колонку SQLite INTEGER уже не влезает
        r = c.post_json(f"/api/patients/{pid}/perio/{huge}", {"teeth": {}})
        res.check("номер осмотра за пределом целого — 404 конвертом, а не 500",
                  (r.status, _j(r)["code"]), (404, "bad_perio"))
        res.check("он же при снятии осмотра",
                  c.post_json(f"/api/patients/{pid}/perio/{huge}/delete", {}).status, 404)
        res.check("и у самого большого допустимого — честный отказ",
                  c.post_json(f"/api/patients/{pid}/perio/{2 ** 63 - 1}",
                              {"teeth": {}}).status, 404)
        res.ok("сервер после этого жив",
               c.get(f"/api/patients/{pid}/perio").status == 200, "не отвечает")
        r = c.post_json(f"/api/patients/{pid}/perio/{eid}",
                        {"teeth": {"46": _row(pd=[3.5] * 6)}, "covers": [46]})
        res.check("дробные миллиметры — отказ, а не тихое удаление зуба",
                  (r.status, _j(r)["code"], _j(r).get("field")), (422, "bad_perio", "teeth"))
        res.check("зуб 46 на месте",
                  _j(c.get(f"/api/patients/{pid}/perio"))["data"]["rows"]["46"]["pd"], [2] * 6)
        r = c.post_json(f"/api/patients/{pid}/perio/{eid}", {"teeth": {}, "covers": ["46"]})
        res.check("номер зуба строкой понят так же, как числом: зуб стёрт",
                  ("46" in _j(r)["data"]["rows"], _j(r)["code"]), (False, "ok_perio"))


def _server_with_flag() -> Server:
    s = Server()
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["perio"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return s


def suite_switch(res: Result) -> None:
    """Пародонтограмма — React при любом `ui.react` (старая страница снята
    13.10): узел в рамке с узким сайдбаром, осмотр из адреса параметром,
    `?ui=legacy` отдаёт тот же React, печать — серверная."""
    with Server() as s:
        c = Client(s.url).login()
        d = _seed(c)
        res.ok("без флага — тоже React (старой страницы нет)",
               '<div id="root" data-screen="perio"' in c.get(f"{d['base']}/parodontograma").body,
               "узла нет")
        c.post_json("/api/patients", {"name": "Perio Gol", "phone": "069400401"})
        res.check("пациент без осмотров: экран «начните» (осмотра в модели нет)",
                  _j(c.get(f"/api/patients/{_pid(c, '069400401')}/perio"))["data"]["exam"], None)

    s = _server_with_flag()
    with s:
        c = Client(s.url).login()
        d = _seed(c)
        pid, base, eid = d["pid"], d["base"], d["eid"]
        page = c.get(f"{base}/parodontograma?exam={eid}").body
        res.ok("узел React в рамке пародонтограммы, сайдбар узкий",
               '<div id="root" data-screen="perio"' in page
               and "/static/js/bundle.js?v=" in page, "узла нет")
        # ⭐ B1: узкий сайдбар больше не строка серверной разметки, а поле
        # модели — сайдбар рисует React. Проверяем ЗНАЧЕНИЕ, а не литерал.
        shell = json.loads(page.split('data-shell="', 1)[1].split('"', 1)[0]
                           .replace("&quot;", '"'))
        res.ok("узкий сайдбар — в модели оболочки", shell["frame"]["rail"] is True,
               f"{shell['frame']['rail']!r}")
        res.ok("серверного каркаса нет", "<aside" not in page, "две оболочки разом")
        params = json.loads(page.split('data-params="', 1)[1].split('"', 1)[0].replace("&quot;", '"'))
        res.check("параметры: фиша и выбранный осмотр", params,
                  {"pid": str(pid), "exam": str(eid)})
        res.ok("без ?exam= узел едет без осмотра — свежий выберет сервер",
               json.loads(c.get(f"{base}/parodontograma").body.split(
                   'data-params="', 1)[1].split('"', 1)[0].replace("&quot;", '"')) == {"pid": str(pid)},
               "лишний параметр")
        res.ok("старой разметки нет",
               "class='pcell" not in page and "PERIO_DEEP" not in page, "две разметки")
        res.ok("?ui=legacy — тот же React",
               'data-screen="perio"' in c.get(f"{base}/parodontograma?ui=legacy").body,
               "старая страница вернулась")
        res.ok("?msg= — плашка сервера",
               "dp_toast" in c.get(f"{base}/parodontograma?msg=ok_perio").body, "нет")
        res.ok("печатный лист остаётся серверным",
               "Parodontogramă" in c.get(f"{base}/parodontograma/print").body
               and "id=\"root\"" not in c.get(f"{base}/parodontograma/print").body,
               "печать уехала в React")
        res.check("чужая фиша — на список",
                  c.get("/admin/patient/9999/parodontograma").status, 303)
        res.check("без входа закрыта",
                  Client(s.url).get(f"{base}/parodontograma").status, 303)


def suite_day(res: Result) -> None:
    """Дата осмотра: в базе UTC, на листе — день клиники. Сервер не поднимается,
    модуль зовётся напрямую: подменить час записи через HTTP нечем, а ошибка
    видна только у осмотров, сделанных поздним вечером."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))
    from app.modules.patients import perio as pp
    from app import engine as eng

    late = datetime(2026, 9, 1, 22, 0, tzinfo=timezone.utc)   # 01:00 02.09 в Кишинёве
    day = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    res.check("вечерний осмотр записан завтрашним днём клиники, а не вчерашним UTC",
              (pp._day(late), pp._day(day)), ("02.09.2026", "01.09.2026"))
    naive = datetime(2026, 9, 1, 22, 0)
    res.check("наивное значение не двигается второй раз",
              pp._day(naive), "01.09.2026")
    res.check("не дата — пусто", (pp._day(None), pp._day("2026-09-01")), ("", ""))
    res.ok("зона берётся у движка, а не вшита",
           str(eng.TZ).endswith("Chisinau") or "Chisinau" in str(eng.TZ),
           f"зона движка: {eng.TZ}")


def suite_two_seats(res: Result) -> None:
    """Два рабочих места в одном осмотре: ни одно не отнимает работу другого.

    ⛔ Здесь стояла закреплённая НАМЕРЕННО дыра (ревью C23, 18.09): правило
    стирания «показывали, но не прислали» сносило зуб, который только что
    измерило соседнее место, — а `shown` у листа всегда все 32, и намерения он
    не описывал никак. Правило заменено на «сообщаем о ТРОНУТОМ» (`covers`), и
    набор переписан под него, а НЕ удалён: возврат к старому обязан краснеть.
    ⚠️ До 13.10 то же правило проверялось и на старой форме листа (её JS
    собирал `covers` слепком); форма снята, правило держит один интерфейс.
    ⭐ Отпечаток `rev` — слово, а не замок: запись проходит всегда, но человек
    узнаёт, что лист под ним успело поправить второе место.
    """
    with Server() as s:
        a = Client(s.url).login()
        b = Client(s.url).login()
        d = _seed(a)
        pid, eid, base = d["pid"], d["eid"], d["base"]
        ma = _j(a.get(f"/api/patients/{pid}/perio"))["data"]
        mb = _j(b.get(f"/api/patients/{pid}/perio"))["data"]
        res.check("оба места видят один осмотр и один его отпечаток",
                  (sorted(ma["rows"]), sorted(mb["rows"]), ma["rev"] == mb["rev"]),
                  (["16", "46"], ["16", "46"], True))

        # A дописывает зуб 26 и правит глубину у 16 — сообщает о двух зубах
        first = _j(a.post_json(f"/api/patients/{pid}/perio/{eid}", {
            "teeth": {"26": _row(pd=[5] * 6), "16": _row(pd=[4] * 6)},
            "covers": [16, 26], "rev": ma["rev"]}))["data"]
        res.check("первое место добавило зуб и поправило свой",
                  (sorted(first["rows"]), first["rows"]["16"]["pd"]),
                  (["16", "26", "46"], [4] * 6))
        res.ok("отпечаток осмотра сменился вместе с данными",
               first["rev"] not in ("", ma["rev"]), f"отпечаток {first['rev']!r}")

        # B сохраняет СВОЮ работу: он правил только 46 и про остальных молчит
        r = b.post_json(f"/api/patients/{pid}/perio/{eid}", {
            "teeth": {"46": _row(pd=[3] * 6)}, "covers": [46], "rev": mb["rev"]})
        second = _j(r)["data"]
        res.check("зуб соседнего места пережил чужую запись",
                  sorted(second["rows"]), ["16", "26", "46"])
        res.check("и чужая правка тоже: 16 остался таким, каким его сделал сосед",
                  second["rows"]["16"]["pd"], [4] * 6)
        res.check("своё второе место записало", second["rows"]["46"]["pd"], [3] * 6)
        res.check("осмотр правили под записывающим — ответ говорит об этом",
                  (r.status, _j(r)["code"], _j(r)["tone"]),
                  (200, "ok_perio_merged", "warn"))
        res.ok("и говорит словами, а не кодом",
               "alt calculator" in _j(r)["text"], f"текст {_j(r)['text']!r}")

        # ⚠️ Ложной тревоги быть не должно: со свежим отпечатком ответ обычный
        r2 = b.post_json(f"/api/patients/{pid}/perio/{eid}", {
            "teeth": {"46": _row(pd=[3, 3, 3, 3, 3, 4])}, "covers": [46],
            "rev": second["rev"]})
        res.check("свежий отпечаток — обычная запись, без тревоги",
                  _j(r2)["code"], "ok_perio")

        # стирание живо: зуб назван в covers и не прислан
        j3 = _j(b.post_json(f"/api/patients/{pid}/perio/{eid}",
                            {"teeth": {}, "covers": [46]}))["data"]
        res.check("зуб, у которого убрали измерения, стирается",
                  sorted(j3["rows"]), ["16", "26"])

        # --- сообщать нечего — не делается ничего, включая летопись ---
        def perio_lines() -> int:
            items = _j(a.get(f"/api/patients/{pid}/activity"))["data"]["items"]
            return sum("Parodontogramă" in x["text"] for x in items)

        was = perio_lines()
        r0 = a.post_json(f"/api/patients/{pid}/perio/{eid}", {"teeth": {}, "covers": []})
        res.check("пустое сообщение принимается и летописи не пишет",
                  (_j(r0)["code"], perio_lines()), ("ok_perio", was))
