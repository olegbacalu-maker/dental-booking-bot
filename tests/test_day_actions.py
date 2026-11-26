"""Действия дня через JSON (C25.5b): запись, заметка, комментарий, статус, перенос.

Что модель дня отдаёт окнам — `test_day_forms`; что сервер делает с записью —
`test_booking`. Здесь два вопроса:

1. **Модель несёт всё, чем пользуются диалоги.** Список врачей ФОРМЫ (не
   шапки дня), их часы, услуги, концы блокировки, карточки визитов и матрица
   кнопок — и карточка с блоком канвы описывают ОДНУ запись поле в поле.
2. **Действие отвечает кодом, удача — свежим днём экрана.** Отказ называет
   себя кодом и полем (`MSG_BANNER`), и код один на все входы: окно записи
   «Programări», диалог часа на панели и фиша зовут одно правило. До 13.10
   третий вход — форма старой страницы — сверялся здесь с API отказ в отказ
   (`suite_parity`); форм нет, и сверка стала буквальной таблицей кодов.
"""
import json
from datetime import datetime, timedelta

from harness import TZ, Client, Clock, Result, Server, add_appt, appt_id, clinic_today, pid_by_phone


def _j(r) -> dict:
    return json.loads(r.body)


def _day(c: Client, date_: str, doctor: str = "") -> dict:
    q = f"?date={date_}" + (f"&doctor={doctor}" if doctor else "")
    return _j(c.get(f"/api/schedule/day{q}"))["data"]


def _day_f(c: Client, date_: str, f: str) -> dict:
    return _j(c.get(f"/api/schedule/day?date={date_}&f={f}"))["data"]


def _items(model: dict) -> list[dict]:
    """Блоки канвы дня — визиты и заметки, которые видны на экране."""
    return [b for col in model["canvas"]["columns"] for b in col["blocks"]]


# ------------------------------------------------------------ модель


def suite_model(res: Result) -> None:
    """Что GET /api/schedule/day отдаёт для формы и диалогов."""
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": day, "time": "09:00",
                                                  "doctor": "d3", "service": "consult",
                                                  "name": "Ion Popa", "phone": "069160160"})
        aid = str(appt_id(c, day, "Ion Popa"))
        long_text = ("Alergie la penicilină; de sunat cu o zi înainte; "
                     "vine cu mama; preferă dimineața")
        c.post_json(f"/api/schedule/appointments/{aid}/comment", {"comment": long_text})

        m = _day(c, day)
        # 06.10: `day_label` — подпись шапки дня (её строит сервер, как у
        # панели), `canvas` — канва панели, которой экран рисует день.
        # (`source_col` — колонка «Sursă» при боте — снят с ботом 03.11.2026.)
        # ⚠️ Таблицы старой страницы (`hours` с ячейками) в модели больше нет:
        # клиент её не читал с 06.10, а страница снята 13.10.
        # `remote` (02.11) — подсказка вместо «Excel» дня у открывшего из сети.
        res.check("в модели есть всё, чем живут шапка, канва, окна и список",
                  sorted(set(m) - {"date", "doctors"}),
                  ["actions", "canvas", "cards", "day_label", "day_long", "filter", "form", "list",
                   "minical", "note_actions", "note_ends", "notice", "remote"])
        # ⛔ ТРИ значения, а не два (C26.5.2). Обрезок больше не носит имени
        # полного: в блоке сетки рядом лежат `comment` (полное, источник
        # правки и участник отпечатка живого канала) и `comment_cut` (60, то,
        # что печатает ячейка). Пока имя было одно, диалог, накормленный
        # блоком, записал бы обрезок обратно, и типы не возразили бы — оба
        # `str` (разбор — live-contract › 6e).
        blk = next(x for x in _items(m) if x["id"] == int(aid))
        res.check("комментарий: в карточке полный, в блоке ПОЛНЫЙ и обрезок "
                  "рядом — под своим именем",
                  (m["cards"][aid]["comment"], blk["comment"], blk["comment_cut"]),
                  (long_text, long_text, long_text[:60]))
        # ⭐ И ВСЕ остальные поля — ПОЛЕ В ПОЛЕ (C26.5.3-a). Диалог панели
        # питается блоком, диалог дня — карточкой; разойдись две сборки, и на
        # одном экране у визита есть ссылка на фишу, а на другом нет — увидеть
        # это можно, только открыв оба. До 19.09 доказан был один `comment`.
        shared = ("name", "phone", "service", "time", "age", "status",
                  "doctor", "pid", "rec", "comment")
        card = m["cards"][aid]
        res.check("карточка и блок описывают ОДНУ запись, поле в поле",
                  {k: blk.get(k) for k in shared},
                  {k: card.get(k) for k in shared})

        res.check("часы формы — у каждого врача формы, от открытия до последнего часа",
                  {dk: (t[0], t[-1]) for dk, t in m["form"]["times"].items()},
                  {dk: ("07:00", "20:00") for dk in ("d2", "d3", "d4")})
        res.check("минуту выбирает окно: шаг сетки стартов едет в форме",
                  m["form"]["step"], 5)
        res.check("концы блокировки — открытые часы плюс один",
                  m["note_ends"], list(range(8, 22)))
        res.check("услуги — все из clinic.json, в его порядке",
                  [x["id"] for x in m["form"]["services"]],
                  ["consult", "pain", "hygiene", "orphan", "long"])
        res.check("КНОПКИ — матрица по состояниям, весь конвейер",
                  {st: sorted(x["to"] for x in acts) for st, acts in m["actions"].items()},
                  {"confirmed": ["arrived", "cancelled", "done", "noshow", "waiting"],
                   "waiting": ["arrived", "cancelled", "done"],
                   "arrived": ["cancelled", "done"],
                   "done": ["confirmed"], "noshow": ["confirmed"], "cancelled": ["confirmed"]})
        # 03.10, слово Олега: «Anulează сразу удаляет… нужно сначала спросить» —
        # вопрос несут возврат и отмена визита, шаги приёма — нет
        res.ok("возврат и отмена визита несут вопрос, а остальные кнопки — нет",
               all(bool(x["confirm"]) == (x["cls"] in ("b-reopen", "b-cancel"))
                   for acts in m["actions"].values() for x in acts),
               "подтверждение разошлось с правилом: спрашивают только возврат и отмена")
        ask_of = {x["cls"]: x["confirm"] for acts in m["actions"].values() for x in acts
                  if x["confirm"]}
        res.check("вопросы названы словами — отмена говорит, где её вернуть",
                  ask_of, {"b-cancel": "Anulați programarea? Ea dispare din grila zilei; "
                                       "o puteți redeschide din «Lista zilei».",
                           "b-reopen": "Redeschideți programarea (înapoi la «programată»)?"})

        # --- список дня (C25.5c) ---
        c.post_json("/api/schedule/notes", {"date": day, "time": "15:00", "doctor": "d2",
                                           "text": "Livrare materiale"})
        c.post_json("/api/schedule/appointments", {"date": day, "time": "11:00",
                                                  "doctor": "d2", "service": "pain",
                                                  "name": "Urgent Unu", "phone": "069160161"})
        m = _day(c, day)
        res.check("СПИСОК: строки дня по времени, вместе с заметкой",
                  [(x["time"], x["name"] or x["service"]) for x in m["list"]],
                  [("09:00", "Ion Popa"), ("11:00", "Urgent Unu"),
                   ("15:00", "Livrare materiale")])
        note = next(x for x in m["list"] if x["is_note"])
        res.check("заметка в списке: без имени и телефона, со своим словом",
                  (note["name"], note["phone"], note["source_label"],
                   note["service"]), ("", "", "notiță", "Livrare materiale"))
        res.check("срочная услуга помечена, обычная нет",
                  sorted({x["urgent"] for x in m["list"] if not x["is_note"]}),
                  [False, True])
        res.check("кнопки заметки — своя матрица, и она не пуста",
                  ({k: [b["to"] for b in v] for k, v in m["note_actions"].items()},
                   [b["confirm"] for b in m["note_actions"]["cancelled"]]),
                  ({"confirmed": ["cancelled"], "cancelled": ["confirmed"]},
                   ["Restabiliți notița?"]))

        # плитка фильтрует список и называет себя — теми же словами, что баннер
        mf = _day_f(c, day, "urg")
        res.check("ФИЛЬТР: только подходящие строки и подпись со счётом",
                  (len(mf["list"]), mf["filter"]),
                  (1, {"key": "urg", "label": "urgențe", "count": 1}))
        res.check("канва при фильтре та же", mf["canvas"], m["canvas"])
        res.check("чужой фильтр — как будто его нет",
                  _day_f(c, day, "nimic")["filter"], None)
        res.check("у дня врача фильтра нет вовсе",
                  _j(c.get(f"/api/schedule/day?date={day}&doctor=d2&f=urg"))["data"]["filter"],
                  None)

        # список ФОРМЫ — активные врачи, даже когда в сетке колонок больше
        c.post_json("/api/doctors/d3", {"name": "Dr. Activ Trei", "status": "concediu"})
        m = _day(c, day)
        res.check("ВЫКЛЮЧЕННЫЙ ВРАЧ: в шапке дня есть, в форме его нет",
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
            ({**ok, "time": "10:07"}, "bad_time", "time"),
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
        res.check("НЕБЫВАЛЫЙ статус — отказом, а не молчанием",
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
        res.check("день врача в ответе — только он и его колонка",
                  ([x["id"] for x in j["data"]["doctors"]],
                   [x["id"] for x in j["data"]["canvas"]["columns"]]), (["d3"], ["d3"]))

        # --- галочка «SMS reminder» (п.7, 22.10) — у клиники БЕЗ пакета ---
        # С пакетом и по ролям — test_sms.suite_box.
        res.check("без пакета SMS галочки нет в форме дня",
                  j["data"]["form"]["sms"], False)
        r = c.post_json(f"/api/schedule/appointments{q}",
                        {**ok, "time": "15:00", "doctor": "d3", "name": "Fara Sms",
                         "phone": "069161888", "sms": False})
        pid = next(x["pid"] for x in _items(_j(r)["data"]) if x.get("name") == "Fara Sms")
        res.check("присланная галочка без пакета — sms_off пациента не тронут",
                  (_j(r)["code"], _j(c.get(f"/api/patients/{pid}"))["data"]["profile"]["sms_off"]),
                  ("ok", False))


# ------------------------------------------------------- таблица отказов


def suite_parity(res: Result) -> None:
    """Каждый отказ называет себя СВОИМ кодом — таблицей, буквально.

    ⚠️ Берутся ОТКАЗЫ: они ничего не меняют, поэтому их можно пройти подряд на
    одном сервере. До 13.10 тот же список сверял форму старой страницы с API
    (один ввод — один код); правило, ради которого сверка жила, — код один на
    все входы, — держит теперь то, что входы зовут ОДНО правило (`routes`), а
    здесь закреплены сами коды.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": day, "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Ocupa Ora", "phone": "069162162"})
        aid = appt_id(c, day, "Ocupa Ora")

        base = {"date": day, "time": "10:00", "doctor": "d2", "service": "consult",
                "name": "N", "phone": "069162001"}
        for body, want in (({"time": "x"}, "bad"), ({"time": "10:07"}, "bad_time"),
                           ({"name": "   "}, "bad_name"), ({"phone": "12"}, "bad_phone"),
                           ({"doctor": "d1"}, "bad_off"), ({"time": "23:00"}, "outside"),
                           ({"time": "09:00"}, "conflict"),
                           ({"birth": "3000-01-01"}, "bad_bd")):
            r = c.post_json(f"/api/schedule/appointments?date={day}", {**base, **body})
            res.check(f"запись {body}: код «{want}»", _j(r)["code"], want)

        for body, want in (({"text": "  "}, "bad"), ({"until": 11}, "bad"),
                           ({"doctor": "nimeni"}, "bad")):
            r = c.post_json(f"/api/schedule/notes?date={day}",
                            {"date": day, "time": "12:00", "doctor": "d2", "text": "T",
                             "until": 13, **body})
            res.check(f"заметка {body}: код «{want}»", _j(r)["code"], want)

        for body, want in (({"time": "10:07"}, "bad_time"), ({"doctor": "d1"}, "bad_off"),
                           ({"time": "23:00"}, "outside"), ({"date": "x"}, "bad")):
            r = c.post_json(f"/api/schedule/appointments/{aid}/move?date={day}",
                            {"date": day, "time": "10:00", "doctor": "d2", **body})
            res.check(f"перенос {body}: код «{want}»", _j(r)["code"], want)


# ------------------------------------------------- перенос на другой день


def suite_move_day(res: Result) -> None:
    """Окно «Mută» меняет ДЕНЬ записи тем же маршрутом, что перетаскивание.

    Под часами (среда, 10:00): «сегодня в прошедший час» и «вчера» не зависят
    от часа прогона. Запись остаётся той же строкой: пациент, процедура,
    длительность и комментарий не трогаются.
    """
    wed, thu, fri = "2026-11-11", "2026-11-12", "2026-11-13"
    tue, mon = "2026-11-10", "2026-11-09"
    with Clock(datetime(2026, 11, 11, 10, 0, tzinfo=TZ)):
        with Server() as s:
            c = Client(s.url).login()
            res.check("запись на четверг", add_appt(c, thu, "09:00", "Muta Ziua", "069163001",
                                                    duration=45).msg, "ok")
            aid = appt_id(c, thu, "Muta Ziua")
            c.post_json(f"/api/schedule/appointments/{aid}/comment", {"comment": "alergie la latex"})
            pid = pid_by_phone(c, "069163001")

            def move(day: str, time: str, screen: str = thu, doctor: str = "d2"):
                r = c.post_json(f"/api/schedule/appointments/{aid}/move?date={screen}",
                                {"date": day, "time": time, "doctor": doctor})
                return r, _j(r)

            def block(day: str) -> dict | None:
                return next((b for b in _items(_day(c, day)) if b["id"] == aid), None)

            r, j = move(fri, "10:30")
            res.check("на другой день: принят, тон удачи, в свежем дне ЭКРАНА записи уже нет",
                      (r.status, j["code"], j["tone"], [b for b in _items(j["data"]) if b["id"] == aid]),
                      (200, "ok_move", "ok", []))
            b = block(fri) or {}
            card = _day(c, fri)["cards"][str(aid)]
            res.check("в новом дне — та же запись: час, длительность, пациент, процедура, комментарий",
                      (b.get("time"), b.get("dur"), card["name"], card["pid"], card["service_id"],
                       card["comment"]),
                      ("10:30", 45, "Muta Ziua", pid, "consult", "alergie la latex"))
            feed = [a["text"] for a in
                    _j(c.get(f"/api/patients/{pid}"))["data"]["activity"]["items"]]
            res.ok("летопись называет новый день датой, а не одним часом",
                   any(t.startswith("Vizită mutată: 13.11.2026 10:30") for t in feed), repr(feed))

            r, j = move(fri, "11:00", screen=fri)
            res.check("в том же дне летопись остаётся с одним часом",
                      (j["code"], any(t.startswith("Vizită mutată: 11:00") for t in (
                          a["text"] for a in
                          _j(c.get(f"/api/patients/{pid}"))["data"]["activity"]["items"]))),
                      ("ok_move", True))

            # прошлое: запрета нет, граница предупреждения — закрытый ДЕНЬ, и только другой
            r, j = move(wed, "09:00", screen=fri)
            res.check("на сегодня в уже прошедший час — обычный перенос, без предупреждения",
                      (r.status, j["code"], j["tone"]), (200, "ok_move", "ok"))
            r, j = move(tue, "09:00", screen=wed)
            res.check("на вчера — перенесено, но с предупреждением о прошедшем дне",
                      (r.status, j["code"], j["tone"], (block(tue) or {}).get("time")),
                      (200, "ok_move_past", "warn", "09:00"))
            res.ok("слово предупреждения есть и говорит про день",
                   "zi trecută" in j["text"], repr(j["text"]))
            r, j = move(tue, "10:00", screen=tue)
            res.check("внутри того же прошедшего дня — без предупреждения",
                      (j["code"], j["tone"]), ("ok_move", "ok"))
            r, j = move(mon, "10:00", screen=tue)
            res.check("с прошедшего дня на другой прошедший — снова предупреждение",
                      j["code"], "ok_move_past")
            r, j = move(fri, "09:00", screen=mon)
            res.check("обратно в будущее — обычный перенос", j["code"], "ok_move")

            # отказы — словами сервера, запись остаётся на месте
            add_appt(c, thu, "12:00", "Sta Pe Loc", "069163002")
            r, j = move(thu, "12:00")
            res.check("занятый час другого дня — 409 conflict со словами, запись на прежнем месте",
                      (r.status, j["code"], bool(j["text"]), (block(fri) or {}).get("time")),
                      (409, "conflict", True, "09:00"))
            r, j = move(thu, "22:00")
            res.check("час вне графика клиники в другом дне — 422 outside и поле часа",
                      (r.status, j["code"], j.get("field"), (block(fri) or {}).get("time")),
                      (422, "outside", "time", "09:00"))

            # закрытую запись окно не двигает и на другой день — как перетаскивание
            c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "cancelled"})
            r, j = move(thu, "10:00")
            res.check("отменённая на другой день не переносится — 409 mv_closed",
                      (r.status, j["code"]), (409, "mv_closed"))
