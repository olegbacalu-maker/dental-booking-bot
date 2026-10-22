"""Договор дня «Programări» с экраном (C25.5b): запись, заметка, карточка,
перенос и «Lista zilei» — данными модели дня (`GET /api/schedule/day`).

До 13.10 здесь пинилась разметка старой страницы (нижняя форма, диалог «+»,
`CARDS`, `CS_SHOW`, таблица списка). Страницы нет; правила, ради которых пины
писались, живут в модели, и проверяются в ней — каждое расходится молча:

* **Список врачей формы — НЕ врачи дня.** Форма — активные справочника, а
  шапка дня — активные ПЛЮС выключенные, у которых есть записи этого дня.
  Возьми экран врачей из шапки — и регистратура выберет выключенного, чтобы
  получить `bad_off` на ровном месте. У разработчика такого врача обычно нет,
  и списки совпадают.
* **Часы в форме — часы ВРАЧА, и всегда на 30 минут**, независимо от
  длительности услуги. Пересчёт «по-умному» отнял бы 17:30 у получасового
  приёма — час, который сегодня законен.
* **Пустое окно врача подменяется часами клиники**: пустой выбор часа не
  отправил бы время вовсе, и вместо честного отказа вышел бы отказ разбора.
* **Комментарий в карточке ПОЛНЫЙ, в блоке канвы обрезан до 60, в списке —
  до 80.** Возьми экран текст не оттуда — и пересохранение БЕЗ единой правки
  укоротит комментарий (прайор 08-16: пересохранение обязано быть
  тождественным).
* **Перенос на СВОЁ место сервер принимает** (`ok_move` и строка в летописи).
  Значит, «бросили туда же — ничего не делать» обязано жить в браузере.
"""
import json
from datetime import timedelta

from harness import Client, Result, Server, appt_id, clinic_today, day_model, pid_by_phone


def _blocks(m: dict) -> list:
    """Блоки канвы дня (все колонки)."""
    return [b for col in m["canvas"]["columns"] for b in col["blocks"]]


def _seed(c: Client, day: str) -> list[int]:
    """Шесть записей и заметка: по одной на каждое состояние конвейера."""
    for i, (hh, name) in enumerate((("08:00", "Sta Confirmat"), ("09:00", "Sta Venit"),
                                    ("10:00", "Sta Cabinet"), ("11:00", "Sta Finalizat"),
                                    ("12:00", "Sta Neprezentat"), ("13:00", "Sta Anulat"))):
        c.post_json("/api/schedule/appointments", {"date": day, "time": hh, "doctor": "d2",
                                                  "service": "consult", "name": name,
                                                  "phone": f"06915010{i}"})
    c.post_json("/api/schedule/notes", {"date": day, "time": "16:00", "doctor": "d2",
                                       "text": "Livrare materiale"})
    ids = [r["id"] for r in day_model(c, day)["list"] if not r["is_note"]]
    for aid, to in zip(ids[1:], ("waiting", "arrived", "done", "noshow", "cancelled")):
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": to})
    return ids


# ------------------------------------------------------------- форма записи


def suite_form(res: Result) -> None:
    """Что окно записи предлагает выбрать — и чего не предлагает.

    ⚠️ Часы у формы СВОИ, они не выводятся из канвы: канва рисует непрерывный
    диапазон с обеденным часом внутри, а форма — только те получасовые старты,
    куда влезает 30 минут приёма.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": day, "time": "09:00",
                                                  "doctor": "d3", "service": "consult",
                                                  "name": "Pacient Trei", "phone": "069151151"})
        f = day_model(c, day)["form"]

        res.check("часы: получасовая сетка от открытия до последнего влезающего старта",
                  (f["times"]["d2"][:2], f["times"]["d2"][-1]), (["07:00", "07:30"], "20:30"))
        res.check("услуги — все из clinic.json, в его порядке",
                  [x["id"] for x in f["services"]],
                  ["consult", "pain", "hygiene", "orphan", "long"])
        res.check("врачи формы — активные справочника", [x["id"] for x in f["doctors"]],
                  ["d2", "d3", "d4"])
        res.check("дата рождения ограничена сегодняшним днём клиники",
                  f["birth_max"], clinic_today().isoformat())

        # выключенный врач: в шапке дня он есть (у него записи), в форме — нет
        c.post_json("/api/doctors/d3", {"name": "Dr. Activ Trei", "status": "concediu"})
        m = day_model(c, day)
        res.check("ВЫКЛЮЧЕННЫЙ ВРАЧ: в шапке дня остался, из формы ушёл",
                  ("d3" in [x["id"] for x in m["doctors"]],
                   "d3" in [x["id"] for x in m["form"]["doctors"]]),
                  (True, False))
        res.check("день врача: в форме он один",
                  [x["id"] for x in day_model(c, day, "d2")["form"]["doctors"]], ["d2"])
        res.check("у выключенного врача формы нет вовсе",
                  day_model(c, day, "d3")["form"], None)

    # часы ВРАЧА, а не клиники: два окна в одном дне
    with Server(clinic="clinic_split.json") as s:
        c = Client(s.url).login()
        times = day_model(c, day)["form"]["times"]
        res.check("у каждого врача формы свои часы",
                  ({"da", "db"} <= set(times), times["da"][0], times["da"][-1],
                   times["db"][0], times["db"][-1]),
                  (True, "09:00", "12:30", "14:00", "17:30"))

    # окно врача, целиком съеденное обедом: список подменяется часами клиники
    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        res.check("врач переведён на 13–14 (иначе проверка ниже пуста)",
                  c.post_json("/api/doctors/d4",
                              {"name": "Dr. Activ Patru", "spec": "Protetică",
                               "work_from": 13, "work_to": 14,
                               "status": "activ", "auto_color": True}).status, 200)
        times = day_model(c, day)["form"]["times"]
        res.check("ПУСТОЕ ОКНО подменяется часами КЛИНИКИ, а не пустым списком",
                  (bool(times["d4"]), times["d4"][0], times["d4"][-1],
                   times["d4"] == times["d2"]),
                  (True, "07:00", "20:30", False))
        res.check("а у врача с окном 9–17 список остаётся его собственным",
                  (times["d2"][0], times["d2"][-1]), ("09:00", "16:30"))
        res.ok("обеденный час из списка выброшен",
               not any(t.startswith("13:") for t in times["d2"]),
               "форма предлагает записать в обед")


# ---------------------------------------------------------- заметки стойки


def suite_slot(res: Result) -> None:
    """Заметка стойки: концы блокировки и правила самой заметки."""
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        res.check("концы блокировки — час открытых слотов плюс один",
                  day_model(c, day)["note_ends"], list(range(8, 22)))

        def note_times() -> list[str]:
            return [r["time"] for r in day_model(c, day)["list"] if r["is_note"]]

        res.check("заметка на три часа: until — ГОЛЫЙ час, граница верхняя открытая",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "15:00",
                                                     "doctor": "d2", "text": "Ședință",
                                                     "until": "18"}).msg, "ok_note")
        res.check("заблокированы 15, 16 и 17 — но не 18",
                  note_times(), ["15:00", "16:00", "17:00"])
        res.check("час занят — остальные лечь успели: part_note",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "17:00",
                                                     "doctor": "d2", "text": "Altă pauză",
                                                     "until": "19"}).msg, "part_note")
        res.check("все часы заняты — conflict",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "15:00",
                                                     "doctor": "d2", "text": "A treia",
                                                     "until": "16"}).msg, "conflict")
        res.check("конец раньше начала — bad",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "12:00",
                                                     "doctor": "d2", "text": "Invers",
                                                     "until": "11"}).msg, "bad")
        res.check("пустой текст — bad",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "12:00",
                                                     "doctor": "d3", "text": "   "}).msg, "bad")
        long_txt = "N" * 200
        c.post_json("/api/schedule/notes", {"date": day, "time": "10:00", "doctor": "d3",
                                           "text": long_txt})
        res.check("текст заметки сервер режет до 120 знаков",
                  [len(r["service"]) for r in day_model(c, day)["list"]
                   if r["is_note"] and r["time"] == "10:00"], [120])
        c.post_json("/api/doctors/d4", {"name": "Dr. Activ Patru", "status": "concediu"})
        res.check("выключенному врачу заметку не ставим — и это «bad», не «bad_off»",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "12:00",
                                                     "doctor": "d4", "text": "Concediu"}).msg, "bad")

    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        res.check("обед выпадает и из концов блокировки: 14:00 выбрать нельзя",
                  day_model(c, day)["note_ends"], list(range(8, 14)) + list(range(15, 22)))
        res.check("…ни в саму блокировку: обед перепрыгнут",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "12:00",
                                                     "doctor": "d2", "text": "Peste pauză",
                                                     "until": "15"}).msg, "ok_note")
        res.check("заметка легла на 12 и 14, обеденного часа в ней нет",
                  [r["time"] for r in day_model(c, day)["list"] if r["is_note"]],
                  ["12:00", "14:00"])


# ------------------------------------------------------- карточка визита


def suite_card(res: Result) -> None:
    """Полезная нагрузка карточки и набор кнопок по статусу."""
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        ids = _seed(c, day)
        long_text = "Alergie la penicilină; de sunat cu o zi înainte; " \
                    "vine cu mama; preferă dimineața"
        res.check("длинный комментарий длиннее блока", len(long_text) > 60, True)
        c.post_json(f"/api/schedule/appointments/{ids[0]}/comment", {"comment": long_text})
        m = day_model(c, day)
        cards = m["cards"]
        blk = next(b for b in _blocks(m) if b["id"] == ids[0])

        # call/callable (12.10) — отметка звонка и «можно ли её ставить»
        # (`core.visits.call_fields`); service_id/service_edit (22.10) — смена
        # процедуры в окне (`core.visits.service_fields`): ключ и флаг, без списка
        res.check("состав карточки", sorted(cards[str(ids[0])]),
                  sorted(["name", "phone", "service", "doctor", "time", "comment",
                          "age", "status", "pid", "rec", "call", "callable",
                          "service_id", "service_edit"]))
        res.check("КОММЕНТАРИЙ В КАРТОЧКЕ ПОЛНЫЙ, в блоке канвы обрезок рядом — до 60",
                  (cards[str(ids[0])]["comment"], blk["comment"], blk["comment_cut"]),
                  (long_text, long_text, long_text[:60]))
        res.ok("заметки стойки карточки не имеют",
               cards and all(v["service"] != "Livrare materiale" for v in cards.values()),
               "заметка попала в карточки — у неё нет ни пациента, ни исхода")
        res.ok("ОТМЕНЁННАЯ запись карточку имеет, хотя с канвы исчезла",
               cards.get(str(ids[5]), {}).get("status") == "cancelled"
               and ids[5] not in [b["id"] for b in _blocks(m)],
               "отменённую запись больше не открыть — вернуть её будет нечем")
        res.ok("карточка помнит фишу и наличие дневника",
               cards[str(ids[0])]["pid"] and cards[str(ids[0])]["rec"] is False,
               f"{cards[str(ids[0])]}")

        # кнопки карточки — матрица `actions` по состоянию из карточки
        res.check("на каждое состояние конвейера — свой набор кнопок",
                  {st: [a["to"] for a in m["actions"][cards[str(aid)]["status"]]]
                   for st, aid in zip(("confirmed", "waiting", "arrived", "done",
                                       "noshow", "cancelled"), ids)},
                  {"confirmed": ["waiting", "arrived", "done", "noshow", "cancelled"],
                   "waiting": ["arrived", "done", "cancelled"],
                   "arrived": ["done", "cancelled"],
                   "done": ["confirmed"], "noshow": ["confirmed"],
                   "cancelled": ["confirmed"]})
        res.check("возврат спрашивают подтверждением",
                  [a["confirm"] for a in m["actions"]["done"]],
                  ["Redeschideți programarea (înapoi la «programată»)?"])

        c.post_json(f"/api/schedule/appointments/{ids[1]}/comment", {"comment": "x" * 400})
        res.check("длинный комментарий обрезан сервером",
                  len(day_model(c, day)["cards"][str(ids[1])]["comment"]), 300)
        res.check("комментарий стирается пустой строкой",
                  (c.post_json(f"/api/schedule/appointments/{ids[1]}/comment",
                               {"comment": ""}).msg,
                   day_model(c, day)["cards"][str(ids[1])]["comment"]),
                  ("ok_comment", ""))

        # отказы смены статуса
        r = c.post_json(f"/api/schedule/appointments/{ids[0]}/status", {"to": "pending"})
        res.check("неизвестный статус — отказ 422, запись не тронута",
                  (r.status, r.msg, day_model(c, day)["cards"][str(ids[0])]["status"]),
                  (422, "bad", "confirmed"))
        # час отменённой записи занят другим пациентом: возврат отбивается
        res.check("час освободился и занят другим (иначе отказа ниже не будет)",
                  c.post_json("/api/schedule/appointments", {"date": day, "time": "13:00",
                                                            "doctor": "d2",
                                                            "service": "consult",
                                                            "name": "Ocupa Ora",
                                                            "phone": "069151900"}).msg, "ok")
        r = c.post_json(f"/api/schedule/appointments/{ids[5]}/status", {"to": "confirmed"})
        res.check("возврат в занятый час — отказ 409 «conflict»",
                  (r.status, r.msg), (409, "conflict"))


# ------------------------------------------------------------- перенос


def suite_move(res: Result) -> None:
    """Перенос: бросок «туда же» и поля переноса у заметки.

    Поля самой записи (`min`/`dur`/`busy`/`movable`) пинит
    `test_booking.suite_move`, мишени переноса — `test_doctor_windows.suite_drop`.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        long_name = "Alexandru-Constantin Popescu-Tăutu de la Ungheni"
        c.post_json("/api/schedule/appointments", {"date": day, "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": long_name, "phone": "069152152"})
        c.post_json("/api/schedule/notes", {"date": day, "time": "11:00", "doctor": "d2",
                                           "text": "Livrare materiale"})
        m = day_model(c, day)
        note = next(b for b in _blocks(m) if b["kind"] == "note")
        res.check("заметку тоже можно перенести: она занимает час и тащится",
                  (note["text"], note["busy"], note["movable"]),
                  ("Livrare materiale", True, True))
        aid = appt_id(c, day, long_name)
        res.check("БРОСОК НА СВОЁ МЕСТО сервер принимает как обычный перенос",
                  c.post_json(f"/api/schedule/appointments/{aid}/move",
                              {"date": day, "time": "09:00", "doctor": "d2"}).msg, "ok_move")
        pid = pid_by_phone(c, "069152152")
        feed = json.loads(c.get(f"/api/patients/{pid}").body)["data"]["activity"]["items"]
        res.ok("и пишет это в летопись пациента — значит охрана «туда же» "
               "обязана стоять в браузере",
               any("Vizită mutată" in x["text"] for x in feed),
               "перенос в себя не оставил следа — правило браузера стало "
               "необязательным, и его можно потерять незаметно")


# ------------------------------------------------------- список дня


def suite_list(res: Result) -> None:
    """«Lista zilei»: что в строке, какие кнопки и как её режет отбор.

    ⚠️ Список — НЕ канва. Он показывает и отменённые записи (на канве их нет),
    и заметки стойки, и это единственное место, где заметку можно убрать и
    вернуть: в карточку визита заметки не попадают по замыслу.
    ⛔ Один и тот же комментарий живёт на экране в ТРЁХ длинах: полный в
    карточке, 80 знаков в списке, 60 в блоке канвы. Возьми экран не ту — и
    пересохранение укоротит текст без единой правки (прайор 08-16).
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        long_cmt = "B" * 100
        c.post_json("/api/schedule/appointments", {"date": day, "time": "09:00",
                                                  "doctor": "d2", "service": "pain",
                                                  "name": "Ion Popa", "phone": "069190190"})
        c.post_json("/api/schedule/appointments", {"date": day, "time": "10:00",
                                                  "doctor": "d3", "service": "consult",
                                                  "name": "Maria Rusu", "phone": "069190191"})
        c.post_json("/api/schedule/notes", {"date": day, "time": "15:00", "doctor": "d2",
                                           "text": "Livrare materiale"})
        ids = [r["id"] for r in day_model(c, day)["list"]]
        c.post_json(f"/api/schedule/appointments/{ids[0]}/comment", {"comment": long_cmt})
        c.post_json(f"/api/schedule/appointments/{ids[1]}/status", {"to": "cancelled"})
        m = day_model(c, day)
        rows = m["list"]

        res.check("в списке ВСЕ записи дня, включая отменённую и заметку",
                  [r["id"] for r in rows], ids)
        res.ok("а на канве отменённой нет",
               ids[1] not in [b["id"] for b in _blocks(m)],
               "отменённая запись осталась на канве")
        res.check("состояние строки — состояние записи",
                  [r["status"] for r in rows], ["confirmed", "cancelled", "confirmed"])

        first = rows[0]
        res.check("строка: час, имя, телефон, услуга, врач, срочность",
                  (first["time"], first["name"], first["phone"], first["service"],
                   first["doctor"], first["urgent"]),
                  ("09:00", "Ion Popa", "069190190", "Durere acută", "Dr. Activ Doi", True))
        res.check("источник назван словом",
                  (first["source_label"], rows[2]["source_label"]), ("manual", "notiță"))
        blk = next(b for b in _blocks(m) if b["id"] == ids[0])
        res.check("КОММЕНТАРИЙ В СПИСКЕ обрезан до 80, в блоке канвы — до 60",
                  (first["comment_cut"], first["comment"], blk["comment_cut"]),
                  (long_cmt[:80], long_cmt, long_cmt[:60]))

        note = rows[2]
        res.check("у заметки нет ни имени, ни телефона, а текст стоит услугой",
                  (note["is_note"], note["name"], note["phone"], note["service"]),
                  (True, "", "", "Livrare materiale"))
        res.check("заметку можно убрать, и это её единственная кнопка",
                  [a["to"] for a in m["note_actions"][note["status"]]], ["cancelled"])
        c.post_json(f"/api/schedule/appointments/{ids[2]}/status", {"to": "cancelled"})
        m2 = day_model(c, day)
        gone = m2["list"][2]
        res.check("убранная заметка предлагает вернуть — и спрашивает СВОИМ вопросом",
                  [(a["to"], a["confirm"]) for a in m2["note_actions"][gone["status"]]],
                  [("confirmed", "Restabiliți notița?")])

        # дневник визита помечает строку
        res.ok("визит записан в дневник (иначе метка ниже недостижима)",
               c.post_json(f"/api/visits/{ids[0]}", {"acuze": "Durere la rece",
                                                    "diagnostic": "K02.1"}).msg.startswith("ok"),
               "дневник не сохранён")
        res.check("строка помечена «дневник заполнен»",
                  day_model(c, day)["list"][0]["rec"], True)

        # отбор режет СПИСОК, но не канву
        plain = day_model(c, day)
        f = day_model(c, day, f="urg")
        res.check("отбор: только подходящие строки и подпись со счётом",
                  ([r["id"] for r in f["list"]], f["filter"]),
                  ([ids[0]], {"key": "urg", "label": "urgențe", "count": 1}))
        res.check("канва при отборе не редеет", f["canvas"], plain["canvas"])

        doc = day_model(c, day, "d2")
        res.check("день врача: список только его записей",
                  sorted({r["doctor"] for r in doc["list"]}), ["Dr. Activ Doi"])
        res.check("у дня врача отбора нет вовсе",
                  day_model(c, day, "d2", f="urg")["filter"], None)
