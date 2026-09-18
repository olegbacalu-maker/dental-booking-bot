"""Действия дня через JSON (C25.5b): запись, заметка, комментарий, статус, перенос.

Пин самих правил — `test_day_forms` (что страница отдаёт браузеру) и
`test_booking` (что сервер делает с формой). Здесь проверяется третье: JSON
говорит О ТОМ ЖЕ.

Два вопроса, на которые отвечает набор:

1. **Модель несёт всё, чем пользуются диалоги.** Список врачей ФОРМЫ (не
   колонок сетки), их часы, услуги, концы блокировки, карточки визитов и
   матрица кнопок. Карточки сверяются с литералом `CARDS` старой страницы —
   поле в поле, потому что именно там лежит полный комментарий, который в
   сетке обрезан до 60.
2. **Один ввод — один код.** Форма отвечает редиректом с `?msg=`, API —
   конвертом с тем же кодом. Разойдись они, React принимал бы визит, который
   старая страница отвергает (или наоборот), и увидела бы это клиника.

⚠️ Отказы проверяются ОБОИМИ путями на одном сервере намеренно: отказ ничего
не меняет, поэтому сравнение честное. Удачи разведены по часам и врачам.

⛔ Пустое поле в сравнении не участвует, и это не лень: ПУСТОЕ поле формы до
сервера не доезжает вовсе (Starlette отбрасывает пустые значения urlencoded),
и обязательный `Form(...)` отвечает 422 раньше нашего кода — а через JSON
пустая строка доезжает и получает честный `bad_name`. Пустым полем сравнение
проверяло бы транспорт, а не правило. Правило ловится ПРОБЕЛАМИ: их браузер
пропускает (`required` доволен), сервер обрезает, и оба пути отвечают
одинаково.
"""
import json
import re
from datetime import timedelta

from harness import Client, Result, Server, clinic_today


def _j(r) -> dict:
    return json.loads(r.body)


def _day(c: Client, date_: str, doctor: str = "") -> dict:
    q = f"?date={date_}" + (f"&doctor={doctor}" if doctor else "")
    return _j(c.get(f"/api/schedule/day{q}"))["data"]


def _ids(c: Client, date_: str) -> list[str]:
    return re.findall(r"<tr class='[a-z]+'><td>(\d+)</td>",
                      c.get(f"/admin/all?date={date_}").body)


def _items(model: dict) -> list[dict]:
    return [x for h in model["hours"] for cl in h["cells"] for x in cl["items"]]


# ------------------------------------------------------------ модель


def suite_model(res: Result) -> None:
    """Что GET /api/schedule/day отдаёт для формы и диалогов."""
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=day, atime="09:00", adoctor="d3",
               aservice="consult", aname="Ion Popa", aphone="069160160",
               back=f"/admin/all?date={day}")
        aid = _ids(c, day)[0]
        long_text = ("Alergie la penicilină; de sunat cu o zi înainte; "
                     "vine cu mama; preferă dimineața")
        c.post(f"/admin/comment/{aid}", comment=long_text, back=f"/admin/all?date={day}")

        m = _day(c, day)
        res.check("в модели появились форма, концы блокировки, карточки и кнопки",
                  sorted(set(m) - {"date", "doctors", "hours"}),
                  ["actions", "cards", "form", "note_ends"])

        page = c.get(f"/admin/all?date={day}").body
        res.check("КАРТОЧКИ — те же, что печатает страница, поле в поле",
                  m["cards"], json.loads(page.split("var CARDS = ", 1)[1]
                                         .split(";\n", 1)[0].rstrip(";")))
        res.check("а значит комментарий в карточке полный, в сетке — обрезанный",
                  (m["cards"][aid]["comment"],
                   next(x for x in _items(m) if x["id"] == int(aid))["comment"]),
                  (long_text, long_text[:60]))

        res.check("часы формы — те же, что в DOC_TIMES страницы",
                  m["form"]["times"],
                  json.loads(page.split("var DOC_TIMES = ", 1)[1].split(";\n", 1)[0]))
        res.check("концы блокировки — те же, что в NOTE_ENDS страницы",
                  m["note_ends"],
                  json.loads(page.split("var NOTE_ENDS = ", 1)[1].split(";\n", 1)[0]))
        res.check("услуги — те же и в том же порядке",
                  [x["id"] for x in m["form"]["services"]],
                  re.findall(r"<option value='([a-z]+)'>",
                             page.split('name="aservice"', 1)[1].split("</select>", 1)[0]))

        cs = {k: re.findall(r"'([a-z]+)'", v) for k, v in re.findall(
            r"(\w+): \[([^\]]*)\]", page.split("var CS_SHOW = ", 1)[1].split("}}", 1)[0])}
        to_of = {"waiting": "waiting", "arrived": "arrived", "done": "done",
                 "noshow": "noshow", "cancel": "cancelled", "reopen": "confirmed"}
        res.check("КНОПКИ — транспонированный CS_SHOW старой страницы",
                  {st: sorted(x["to"] for x in acts) for st, acts in m["actions"].items()},
                  {st: sorted(to_of[k] for k, v in cs.items() if st in v)
                   for st in m["actions"]})
        res.ok("возврат несёт вопрос, а остальные кнопки — нет",
               all(bool(x["confirm"]) == (x["cls"] == "b-reopen")
                   for acts in m["actions"].values() for x in acts),
               "подтверждение возврата разошлось со списком дня")

        # список ФОРМЫ — активные врачи, даже когда в сетке колонок больше
        c.post("/admin/doctor-card/d3/save", name="Dr. Activ Trei", status="concediu")
        m = _day(c, day)
        res.check("ВЫКЛЮЧЕННЫЙ ВРАЧ: колонка есть, в форме его нет",
                  ("d3" in [x["id"] for x in m["doctors"]],
                   "d3" in [x["id"] for x in m["form"]["doctors"]]),
                  (True, False))
        res.check("часы есть у каждого врача формы",
                  sorted(m["form"]["times"]),
                  sorted(x["id"] for x in m["form"]["doctors"]))

        # день врача: один врач формы, у выключенного формы нет вовсе
        res.check("день врача: в форме он один",
                  [x["id"] for x in _day(c, day, "d2")["form"]["doctors"]], ["d2"])
        res.check("у выключенного врача формы нет", _day(c, day, "d3")["form"], None)


# ------------------------------------------------------------ действия


def suite_actions(res: Result) -> None:
    """Пять действий: удача несёт свежий день, отказ — код и поле."""
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        q = f"?date={day}"

        res.check("без входа — 401",
                  Client(s.url).post_json(f"/api/schedule/appointments{q}", {}).status, 401)
        res.check("чужой Origin — 403",
                  c.post_json(f"/api/schedule/appointments{q}", {},
                              headers={"Origin": "http://evil.example"}).status, 403)
        res.check("не JSON — 422",
                  c.post(f"/api/schedule/appointments{q}", name="X").status, 422)

        # --- запись ---
        ok = {"date": day, "time": "09:00", "doctor": "d2", "service": "consult",
              "name": "Ion Popa", "phone": "069161161"}
        r = c.post_json(f"/api/schedule/appointments{q}", ok)
        j = _j(r)
        res.check("запись принята и ответ несёт СВЕЖИЙ день",
                  (r.status, j["code"], [x["name"] for x in _items(j["data"])]),
                  (200, "ok", ["Ion Popa"]))
        res.ok("и текст плашки приезжает с сервера",
               j["text"] and j["tone"] == "ok", f"{j.get('text')!r}")
        aid = _items(j["data"])[0]["id"]

        res.check("тот же час у того же врача — 409 conflict",
                  [(r.status, _j(r)["code"]) for r in
                   [c.post_json(f"/api/schedule/appointments{q}",
                                {**ok, "name": "Alt Pacient", "phone": "069161999"})]],
                  [(409, "conflict")])
        res.check("тот же пациент на тот же час к другому врачу — 409 dup",
                  [(r.status, _j(r)["code"]) for r in
                   [c.post_json(f"/api/schedule/appointments{q}", {**ok, "doctor": "d3"})]],
                  [(409, "dup")])

        for body, want, field in (
            ({**ok, "date": "not-a-date"}, "bad", "time"),
            ({**ok, "time": "10:15"}, "bad_time", "time"),
            ({**ok, "name": "  "}, "bad_name", "name"),
            ({**ok, "phone": "12"}, "bad_phone", "phone"),
            ({**ok, "doctor": "d1"}, "bad_off", ""),
            ({**ok, "doctor": "nimeni"}, "bad", "time"),
            ({**ok, "service": "nimic"}, "bad", "time"),
            ({**ok, "time": "23:00"}, "outside", "time"),
            ({**ok, "birth": "2200-01-01", "time": "10:00"}, "bad_bd", "birth"),
        ):
            r = c.post_json(f"/api/schedule/appointments{q}", body)
            j = _j(r)
            res.check(f"отказ «{want}»: код, состояние и поле",
                      (j["code"], r.status, j.get("field", "")),
                      (want, 409 if want == "bad_off" else 422, field))

        res.check("галочка «без телефона» принимается вместо номера",
                  _j(c.post_json(f"/api/schedule/appointments{q}",
                                 {**ok, "time": "10:00", "phone": "",
                                  "nophone": True, "name": "Fara Telefon"}))["code"], "ok")

        # --- заметка ---
        r = c.post_json(f"/api/schedule/notes{q}",
                        {"date": day, "time": "15:00", "doctor": "d2",
                         "text": "Ședință", "until": 18})
        j = _j(r)
        res.check("заметка на три часа: код и три блока в свежем дне",
                  (r.status, j["code"],
                   sorted(x["time"] for x in _items(j["data"]) if x["kind"] == "note")),
                  (200, "ok_note", ["15:00", "16:00", "17:00"]))
        res.check("час занят, остальные легли — part_note",
                  _j(c.post_json(f"/api/schedule/notes{q}",
                                 {"date": day, "time": "17:00", "doctor": "d2",
                                  "text": "Altă", "until": 19}))["code"], "part_note")
        r = c.post_json(f"/api/schedule/notes{q}",
                        {"date": day, "time": "12:00", "doctor": "d2", "text": " ",
                         "until": 13})
        res.check("пустой текст — 422 и поле текста",
                  (r.status, _j(r)["code"], _j(r).get("field")), (422, "bad", "text"))

        # --- комментарий ---
        r = c.post_json(f"/api/schedule/appointments/{aid}/comment{q}",
                        {"comment": "x" * 400})
        j = _j(r)
        res.check("комментарий сохранён, обрезан сервером и виден в карточке",
                  (r.status, j["code"], len(j["data"]["cards"][str(aid)]["comment"])),
                  (200, "ok_comment", 300))

        # --- статус ---
        r = c.post_json(f"/api/schedule/appointments/{aid}/status{q}", {"to": "done"})
        j = _j(r)
        res.check("статус сменился, свежий день это показывает",
                  (r.status, j["code"],
                   next(x["status"] for x in _items(j["data"]) if x["id"] == aid)),
                  (200, "", "done"))
        r = c.post_json(f"/api/schedule/appointments/{aid}/status{q}", {"to": "pending"})
        res.check("НЕБЫВАЛЫЙ статус: страница молчит, API отвечает отказом",
                  (r.status, _j(r)["code"]), (422, "bad"))

        # --- перенос ---
        r = c.post_json(f"/api/schedule/appointments/{aid}/move{q}",
                        {"date": day, "time": "11:00", "doctor": "d2"})
        res.check("завершённый визит не переносится — 409 mv_closed",
                  (r.status, _j(r)["code"]), (409, "mv_closed"))
        c.post_json(f"/api/schedule/appointments/{aid}/status{q}", {"to": "confirmed"})
        r = c.post_json(f"/api/schedule/appointments/{aid}/move{q}",
                        {"date": day, "time": "11:30", "doctor": "d3"})
        j = _j(r)
        res.check("перенос принят, свежий день кладёт визит на новое место",
                  (r.status, j["code"],
                   next(x["time"] for x in _items(j["data"]) if x["id"] == aid)),
                  (200, "ok_move", "11:30"))
        r = c.post_json(f"/api/schedule/appointments/999999/move{q}",
                        {"date": day, "time": "12:00", "doctor": "d2"})
        res.check("несуществующая запись — 409 mv_gone",
                  (r.status, _j(r)["code"]), (409, "mv_gone"))

        # свежий день приходит для ЭКРАНА, а не для даты визита
        j = _j(c.post_json(f"/api/schedule/appointments{q}&doctor=d3",
                           {**ok, "time": "14:00", "doctor": "d3",
                            "name": "Doar La Trei", "phone": "069161777"}))
        res.check("день врача в ответе — только его колонка",
                  [x["id"] for x in j["data"]["doctors"]], ["d3"])


# ------------------------------------------------------- паритет кодов


def suite_parity(res: Result) -> None:
    """Один ввод — один код: форма и API отвечают одинаково.

    ⚠️ Берутся ОТКАЗЫ: они ничего не меняют, поэтому оба пути можно пройти
    подряд на одном сервере и сравнить честно. Удачи разведены по часам в
    `suite_actions` — там сравнивать нечего, код виден сразу.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    back = f"/admin/all?date={day}"
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=day, atime="09:00", adoctor="d2",
               aservice="consult", aname="Ocupa Ora", aphone="069162162", back=back)
        aid = _ids(c, day)[0]

        rows = [
            {"date": day, "time": "x", "doctor": "d2", "service": "consult",
             "name": "N", "phone": "069162001"},
            {"date": day, "time": "10:15", "doctor": "d2", "service": "consult",
             "name": "N", "phone": "069162002"},
            {"date": day, "time": "10:00", "doctor": "d2", "service": "consult",
             "name": "   ", "phone": "069162003"},
            {"date": day, "time": "10:00", "doctor": "d2", "service": "consult",
             "name": "N", "phone": "12"},
            {"date": day, "time": "10:00", "doctor": "d1", "service": "consult",
             "name": "N", "phone": "069162004"},
            {"date": day, "time": "23:00", "doctor": "d2", "service": "consult",
             "name": "N", "phone": "069162005"},
            {"date": day, "time": "09:00", "doctor": "d2", "service": "consult",
             "name": "N", "phone": "069162006"},
            {"date": day, "time": "10:00", "doctor": "d2", "service": "consult",
             "name": "N", "phone": "069162007", "birth": "3000-01-01"},
        ]
        for i, b in enumerate(rows):
            form = c.post("/admin/add", adate=b["date"], atime=b["time"],
                          adoctor=b["doctor"], aservice=b["service"],
                          aname=b["name"], aphone=b["phone"],
                          abirth=b.get("birth", ""), back=back).msg
            api = _j(c.post_json(f"/api/schedule/appointments?date={day}", b))["code"]
            res.check(f"запись, отказ {i + 1}: форма и API говорят одно",
                      api, form)

        notes = [
            {"date": day, "time": "12:00", "doctor": "d2", "text": "  ", "until": 13},
            {"date": day, "time": "12:00", "doctor": "d2", "text": "T", "until": 11},
            {"date": day, "time": "12:00", "doctor": "nimeni", "text": "T", "until": 13},
        ]
        for i, b in enumerate(notes):
            form = c.post("/admin/note", ndate=b["date"], ntime=b["time"],
                          ndoctor=b["doctor"], ntext=b["text"],
                          nuntil=str(b["until"]), back=back).msg
            api = _j(c.post_json(f"/api/schedule/notes?date={day}", b))["code"]
            res.check(f"заметка, отказ {i + 1}: форма и API говорят одно", api, form)

        moves = [
            {"date": day, "time": "10:15", "doctor": "d2"},
            {"date": day, "time": "10:00", "doctor": "d1"},
            {"date": day, "time": "23:00", "doctor": "d2"},
            {"date": "x", "time": "10:00", "doctor": "d2"},
        ]
        for i, b in enumerate(moves):
            form = c.post(f"/admin/move/{aid}", mdate=b["date"], mtime=b["time"],
                          mdoctor=b["doctor"], back=back).msg
            api = _j(c.post_json(f"/api/schedule/appointments/{aid}/move?date={day}",
                                 b))["code"]
            res.check(f"перенос, отказ {i + 1}: форма и API говорят одно", api, form)
