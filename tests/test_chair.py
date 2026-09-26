# -*- coding: utf-8 -*-
"""Экран «у кресла» (контракт docs/dentpilot-2/chair-mode.md): правило «кто в
кресле» и его API.

Главное, что стережётся: сервер решает, КТО сидит в кресле, одним правилом, и
это правило переживает то, что бывает в клинике каждый день, — забытое
«Finalizează» у прошлого пациента (два `arrived` у одного врача), приёмную из
нескольких человек, чужого врача и заметку стойки в том же дне.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bot"))

from app.modules.schedule import chair  # noqa: E402
from harness import Client, Result, Server, clinic_today  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)   # 09:00 по Кишинёву


def _row(i, status, start_h, arrived_min=None):
    return {"id": i, "status": status, "starts_at": T0 + timedelta(hours=start_h),
            "arrived_at": (T0 + timedelta(minutes=arrived_min)
                           if arrived_min is not None else None)}


def _item(i, status, wait_ms=None):
    return {"id": i, "status": status, "wait_since": wait_ms, "name": f"P{i}"}


def _ids(xs):
    return [x["id"] for x in xs]


def suite_rule(res: Result) -> None:
    """Правило на образцах — без сервера и без базы."""
    m = chair.model
    rows = [_row(1, "confirmed", 0), _row(2, "confirmed", 1)]
    got = m(rows, [_item(1, "confirmed"), _item(2, "confirmed")])
    res.check("никого в кабинете — кресло пусто", got["chair"], None)
    res.check("очередь по времени приёма", _ids(got["queue"]), [1, 2])

    rows = [_row(1, "arrived", 0, arrived_min=5), _row(2, "confirmed", 1)]
    got = m(rows, [_item(1, "arrived"), _item(2, "confirmed")])
    res.check("в кабинете — в кресле", got["chair"]["id"], 1)
    res.check("в кресле — не в очереди", _ids(got["queue"]), [2])

    # забытое «Finalizează»: 1 завели в 09:05, 2 — в 10:10; сидит второй
    rows = [_row(1, "arrived", 0, arrived_min=5), _row(2, "arrived", 1, arrived_min=70)]
    got = m(rows, [_item(1, "arrived"), _item(2, "arrived")])
    res.check("два в кабинете — в кресле последний заведённый", got["chair"]["id"], 2)
    res.check("прошлый — «не завершён», а не пропал", _ids(got["stale"]), [1])
    # тот же случай, но позже по времени приёма — РАНЬШЕ заведён: решает штамп
    rows = [_row(1, "arrived", 2, arrived_min=5), _row(2, "arrived", 1, arrived_min=70)]
    got = m(rows, [_item(2, "arrived"), _item(1, "arrived")])
    res.check("решает штамп «în cabinet», не время приёма", got["chair"]["id"], 2)
    # строка без штампа (до 08-13) старше любой со штампом
    rows = [_row(1, "arrived", 3), _row(2, "arrived", 0, arrived_min=1)]
    got = m(rows, [_item(2, "arrived"), _item(1, "arrived")])
    res.check("строка без штампа старше строки со штампом", got["chair"]["id"], 2)
    rows = [_row(1, "arrived", 0), _row(2, "arrived", 1)]
    got = m(rows, [_item(1, "arrived"), _item(2, "arrived")])
    res.check("обе без штампа — по времени приёма", got["chair"]["id"], 2)

    rows = [_row(1, "confirmed", 0), _row(2, "waiting", 1), _row(3, "waiting", 2),
            _row(4, "done", 0), _row(5, "noshow", 0)]
    items = [_item(1, "confirmed"), _item(2, "waiting", 2000), _item(3, "waiting", 1000),
             _item(4, "done"), _item(5, "noshow")]
    got = m(rows, items)
    res.check("приёмная — кто раньше пришёл, потом записанные", _ids(got["queue"]), [3, 2, 1])
    res.check("завершённые и неявки — не в очереди и не в кресле",
              (got["chair"], _ids(got["stale"])), (None, []))
    # строка, которой нет в повестке (заметка стойки, отменённая), не садится
    got = m([_row(9, "arrived", 0, arrived_min=1)], [])
    res.check("не из повестки — не в кресле", got["chair"], None)

    rd = chair.resolve_doctor
    known = {"d2": "Dr. Doi", "d3": "Dr. Trei"}
    res.check("адрес решает", rd("d2", {"doctor_id": "d3"}, known), "d2")
    res.check("без адреса — врач учётки", rd("", {"doctor_id": "d3"}, known), "d3")
    res.check("неизвестный в адресе — врач учётки", rd("zz", {"doctor_id": "d3"}, known), "d3")
    res.check("учётка без врача — выбор", rd("", {"role": "director"}, known), "")
    res.check("врач учётки удалён из справочника — выбор", rd("", {"doctor_id": "d9"}, known), "")
    res.check("вход без учётки (облачный ключ)", rd("", None, known), "")

    # ⛔ перечисление обязано лежать внутри активных статусов базы: иначе
    # кресло ждало бы статус, которого конвейер не ставит
    src = (pathlib.Path(__file__).resolve().parents[1] / "bot" / "app" / "db.py").read_text(encoding="utf-8")
    active = next(ast.literal_eval(n.value) for n in ast.parse(src).body
                  if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ACTIVE_STATUSES")
    res.ok("кресло и очередь — внутри db.ACTIVE_STATUSES",
           {chair.CHAIR, *chair.QUEUE} <= set(active), f"{active}")


def _monday() -> str:
    """Рабочий понедельник через неделю: не «сегодня» (правило не должно
    зависеть от часа прогона) и не выходной (журнал бы его не принял)."""
    t = clinic_today()
    return (t + timedelta(days=7 - t.weekday() + 7)).isoformat()


def suite_api(res: Result) -> None:
    """GET /api/chair: врач, кресло, «не завершён», очередь, кнопки исхода."""
    with Server() as s:
        res.check("без входа — 401", Client(s.url).get("/api/chair").status, 401)
        c = Client(s.url).login()
        j = json.loads(c.get("/api/chair").body)["data"]
        res.ok("директор без привязки — выбор врача, кресло пусто",
               j["doctor"] is None and j["chair"] is None and j["queue"] == []
               and {"dk", "name"} <= set(j["doctors"][0]), f"{j}")
        res.ok("архивный врач в выборе не предлагается",
               "d1" not in [x["dk"] for x in j["doctors"]], f"{j['doctors']}")

        day = _monday()
        for hh, nm, ph, dk in (("09:00", "Ana Unu", "069400401", "d2"),
                               ("10:00", "Bogdan Doi", "069400402", "d2"),
                               ("11:00", "Cezar Trei", "069400403", "d2"),
                               ("09:30", "Dina Alta", "069400404", "d3")):
            c.post("/admin/add", adate=day, atime=hh, adoctor=dk,
                   aservice="consult", aname=nm, aphone=ph)
        c.post("/admin/note", ndate=day, ntime="12:00", ndoctor="d2",
               ntext="Livrare materiale")

        def get(q=f"?doctor=d2&date={day}"):
            return json.loads(c.get("/api/chair" + q).body)["data"]

        j = get()
        names = {x["name"]: x["id"] for x in j["queue"]}
        res.check("свой врач, по времени, без чужого и без заметки",
                  [x["name"] for x in j["queue"]], ["Ana Unu", "Bogdan Doi", "Cezar Trei"])
        res.check("врач назван", j["doctor"], {"dk": "d2", "name": "Dr. Activ Doi"})
        res.ok("кнопки исхода — матрицей сервера", "arrived" in j["actions"]
               and "confirmed" in j["actions"], f"{list(j['actions'])}")
        res.check("кресло пусто, пока никого не завели", j["chair"], None)

        def to(name, st):
            r = c.post_json(f"/api/schedule/appointments/{names[name]}/status", {"to": st})
            return r.status

        # ⚠️ Штампы конвейера — с точностью до СЕКУНДЫ (`db._iso`): два
        # перехода в одну секунду — ничья, и её решило бы время приёма. Поэтому
        # пауза, и тот, кто должен победить по штампу, записан на БОЛЕЕ ПОЗДНИЙ
        # (приёмная) или БОЛЕЕ РАННИЙ (кресло) час — иначе проверка зеленела бы
        # и без правила (так и было в первой редакции этого набора).
        res.check("пришёл Cezar (11:00)", to("Cezar Trei", "waiting"), 200)
        time.sleep(1.1)
        res.check("пришёл Bogdan (10:00)", to("Bogdan Doi", "waiting"), 200)
        j = get()
        res.check("приёмная по времени прихода, затем записанные",
                  [x["name"] for x in j["queue"]], ["Cezar Trei", "Bogdan Doi", "Ana Unu"])

        to("Cezar Trei", "arrived")
        j = get()
        res.check("в кресле тот, кого завели", (j["chair"] or {}).get("name"), "Cezar Trei")
        res.ok("у пациента в кресле есть фиша",
               bool((j["chair"] or {}).get("patient_id")), f"{j['chair']}")
        res.check("в кресле — не в очереди", [x["name"] for x in j["queue"]],
                  ["Bogdan Doi", "Ana Unu"])
        time.sleep(1.1)
        to("Ana Unu", "arrived")          # 09:00 — раньше по времени приёма
        j = get()
        res.check("завели второго, не завершив первого — в кресле последний заведённый",
                  (j["chair"] or {}).get("name"), "Ana Unu")
        res.check("первый — «не завершён»", [x["name"] for x in j["stale"]], ["Cezar Trei"])
        res.check("в очереди только приёмная", [x["name"] for x in j["queue"]], ["Bogdan Doi"])

        to("Ana Unu", "done")
        j = get()
        res.check("завершили — в кресле снова незавершённый",
                  (j["chair"] or {}).get("name"), "Cezar Trei")
        res.check("завершённый ушёл отовсюду", j["stale"], [])
        to("Bogdan Doi", "cancelled")
        j = get()
        res.check("отменённый ушёл из очереди", j["queue"], [])

        # дневник визита, открытый из кресла, возвращает В КРЕСЛО: сервер эхом
        # отдаёт `back` (`_visit_back` пропускает только /admin…) — сузь его до
        # белого списка без кресла, и возврат сломается молча
        v = json.loads(c.get(f"/api/visits/{names['Ana Unu']}"
                             f"?back=%2Fadmin%2Fcabinet%3Fdoctor%3Dd2").body)
        res.check("дневник из кресла возвращает в кресло",
                  (v.get("data") or {}).get("back"), "/admin/cabinet?doctor=d2")

        j = get(f"?doctor=zz&date={day}")
        res.check("неизвестный врач без привязки — выбор", j["doctor"], None)
        j = get(f"?doctor=d3&date={day}")
        res.check("кресло другого врача — его записи",
                  [x["name"] for x in j["queue"]], ["Dina Alta"])


def suite_page(res: Result) -> None:
    """Адрес экрана: у клиники — оболочка React с врачом в узле; без React
    (аварийный выключатель) — день врача, старой страницы у кресла нет."""
    s = Server()
    cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
    cfg["ui"] = {"react": ["chair"]}
    s.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    with s:
        r = Client(s.url).get("/admin/cabinet")
        res.ok("без входа — на вход", r.status == 303 and "/admin/login" in r.location,
               f"{r.status} {r.location!r}")
        c = Client(s.url).login()
        page = c.get("/admin/cabinet?doctor=d2")
        res.ok("узел React экрана кресла", page.status == 200
               and 'data-screen="chair"' in page.body, f"код {page.status}")
        res.ok("врач из адреса — в параметрах узла", "&quot;doctor&quot;: &quot;d2&quot;" in page.body,
               "нет data-params с врачом")
        page = c.get("/admin/cabinet")
        res.ok("без врача — узел без параметров (экран предложит выбор)",
               'data-screen="chair"' in page.body and "data-params" not in page.body.split('data-screen="chair"')[1][:200],
               "параметры есть")
    with Server() as s2:                    # фикстура: ui.react = [] — старое везде
        c = Client(s2.url).login()
        r = c.get("/admin/cabinet?doctor=d2")
        res.ok("без React — день врача", r.status == 303 and r.location.endswith("/admin/doctor/d2"),
               f"{r.status} {r.location!r}")
        r = c.get("/admin/cabinet")
        res.ok("без React и без врача — панель", r.status == 303 and r.location.endswith("/admin"),
               f"{r.status} {r.location!r}")
