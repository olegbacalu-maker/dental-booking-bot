# -*- coding: utf-8 -*-
"""Кабинет у записи: врач ведёт по записи в каждом своём кабинете.

Главное, что стережётся: у врача с ОДНИМ кабинетом (и без кабинета вовсе) не
меняется ничего — вторая запись на занятое время по-прежнему `conflict`; у
врача с двумя — вторая проходит и ложится во второй кабинет, третья отбита.
Заметка стойки занимает врача целиком, пациент в двух кабинетах одного врача
сразу не сидит, а кабинет, занятый другим врачом, — предупреждение, не отказ.
"""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone

from harness import (TZ, Client, Result, Server, add_appt, appt_id, clinic_today,
                     day_model, new_patient, panel_live, set_rooms)


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _add(c: Client, day: str, time: str, name: str, phone: str,
         doctor: str = "d2", **fields) -> str:
    return add_appt(c, day, time, name, phone, doctor, **fields).msg


def _blocks(c: Client, day: str, dk: str = "d2") -> dict:
    """Блоки колонки врача по имени пациента."""
    col = next(x for x in day_model(c, day)["canvas"]["columns"] if x["id"] == dk)
    return {b.get("name") or b.get("text"): b for b in col["blocks"]}


def _post(c: Client, aid: int, what: str, payload: dict, day: str) -> str:
    return c.post_json(f"/api/schedule/appointments/{aid}/{what}?date={day}", payload).msg


def suite_rule(res: Result) -> None:
    """Занятость по кабинетам — дверью клиники (окно записи, перенос, статус)."""
    with Server() as s:
        c = Client(s.url).login()

        # --- один кабинет и ни одного: как было ---
        day = _d(2)
        res.check("врач без кабинета: первая запись", _add(c, day, "10:00", "Fara Unu", "022700001", "d3"), "ok")
        res.check("врач без кабинета: вторая на тот же старт — conflict",
                  _add(c, day, "10:00", "Fara Doi", "022700002", "d3"), "conflict")
        res.check("врач без кабинета: пересечение по минутам — conflict",
                  _add(c, day, "10:30", "Fara Trei", "022700003", "d3"), "conflict")
        one = set_rooms(c, "d4", "7")
        res.check("у врача один кабинет", len(one), 1)
        res.check("один кабинет: первая запись", _add(c, day, "10:00", "Unu Unu", "022700011", "d4"), "ok")
        res.check("один кабинет: вторая на тот же старт — conflict",
                  _add(c, day, "10:00", "Unu Doi", "022700012", "d4"), "conflict")
        res.check("один кабинет: назначенный занятый кабинет — conflict",
                  _add(c, day, "10:30", "Unu Trei", "022700013", "d4", room=one[0]), "conflict")
        res.check("один кабинет: запись несёт его", _blocks(c, day, "d4")["Unu Unu"]["room_id"], one[0])

        # --- два кабинета ---
        r1, r2 = set_rooms(c, "d2", "1", "3")
        res.check("первая запись — в кабинет по умолчанию",
                  (_add(c, day, "10:00", "Doi Unu", "022700021"), _blocks(c, day)["Doi Unu"]["room_id"]),
                  ("ok", r1))
        res.check("вторая на тот же старт проходит — во второй кабинет",
                  (_add(c, day, "10:00", "Doi Doi", "022700022"), _blocks(c, day)["Doi Doi"]["room_id"]),
                  ("ok", r2))
        res.check("третья — conflict", _add(c, day, "10:00", "Doi Trei", "022700023"), "conflict")
        res.check("третья с пересечением по минутам — conflict",
                  _add(c, day, "10:30", "Doi Trei", "022700023"), "conflict")
        res.check("имя кабинета — рядом с ключом", _blocks(c, day)["Doi Doi"]["room"], "3")

        day = _d(3)
        res.check("назначенный кабинет: запись во второй",
                  (_add(c, day, "10:00", "Ales Unu", "022700031", room=r2),
                   _blocks(c, day)["Ales Unu"]["room_id"]), ("ok", r2))
        res.check("тот же кабинет, пересечение — conflict (другой не подставляется)",
                  _add(c, day, "10:30", "Ales Doi", "022700032", room=r2), "conflict")
        res.check("другой кабинет на то же время — проходит",
                  _add(c, day, "10:30", "Ales Doi", "022700032", room=r1), "ok")
        r = add_appt(c, day, "12:00", "Ales Trei", "022700033", "d2", room="r-nu-exista")
        res.check("чужой кабинет — bad_room, поле названо",
                  (r.msg, r.status, json.loads(r.body).get("field")), ("bad_room", 422, "room"))
        res.check("кабинет другого врача — тоже bad_room",
                  _add(c, day, "12:00", "Ales Trei", "022700033", room=one[0]), "bad_room")

        # --- заметка стойки занимает врача целиком ---
        day = _d(4)
        note = c.post_json("/api/schedule/notes", {"date": day, "time": "14:00", "doctor": "d2",
                                                   "text": "Lipsește"})
        res.check("заметка поставлена", note.msg, "ok_note")
        res.check("заметка блокирует кабинет по умолчанию",
                  _add(c, day, "14:00", "Nota Unu", "022700041"), "conflict")
        res.check("заметка блокирует и второй кабинет",
                  _add(c, day, "14:30", "Nota Unu", "022700041", room=r2), "conflict")
        res.check("запись стоит во втором кабинете", _add(c, day, "16:00", "Nota Doi", "022700042", room=r2), "ok")
        res.check("заметка поверх записи любого кабинета — conflict",
                  c.post_json("/api/schedule/notes", {"date": day, "time": "16:00", "doctor": "d2",
                                                      "text": "Lipsește"}).msg, "conflict")

        # --- старая запись без кабинета занимает кабинет по умолчанию ---
        day = _d(5)
        d5 = datetime.fromisoformat(day)
        at = datetime(d5.year, d5.month, d5.day, 10, 0, tzinfo=TZ).astimezone(timezone.utc)
        pid = new_patient(c, "Veche Inregistrare", "022700050")
        con = sqlite3.connect(s.dir / "dental.db")
        con.execute(
            "INSERT INTO appointments(patient_id, service, doctor, starts_at, status, source,"
            " created_at, doctor_id, duration_min) VALUES(?, 'Consultație', 'Dr. Activ Doi', ?,"
            " 'confirmed', 'manual', '2026-01-10T08:05:00+00:00', 'd2', 60)",
            (pid, at.isoformat(timespec="seconds")))
        con.commit()
        con.close()
        res.check("старая запись читается в кабинете по умолчанию",
                  _blocks(c, day)["Veche Inregistrare"]["room_id"], r1)
        res.check("в кабинет по умолчанию поверх неё — conflict",
                  _add(c, day, "10:00", "Peste Veche", "022700051", room=r1), "conflict")
        res.check("без кабинета — запись уходит во второй",
                  (_add(c, day, "10:00", "Peste Veche", "022700051"),
                   _blocks(c, day)["Peste Veche"]["room_id"]), ("ok", r2))

        # --- пациент: пересечение у одного врача — dup, у разных — как было ---
        day = _d(6)
        res.check("пациент записан", _add(c, day, "10:00", "Acelasi Om", "022700060"), "ok")
        res.check("тот же пациент, тот же врач, пересечение по минутам — dup (второй кабинет свободен)",
                  _add(c, day, "10:30", "Acelasi Om", "022700060"), "dup")
        res.check("тот же пациент к другому врачу с пересечением — проходит, как было",
                  _add(c, day, "10:30", "Acelasi Om", "022700060", "d3"), "ok")
        res.check("тот же пациент к другому врачу на тот же старт — dup, как было",
                  _add(c, day, "10:00", "Acelasi Om", "022700060", "d4"), "dup")

        # --- кабинет занят другим врачом: предупреждение, запись проходит ---
        day = _d(7)
        shared = set_rooms(c, "d3", "1")
        res.check("кабинет с тем же именем — тот же кабинет", shared[0], r1)
        res.check("другой врач занял кабинет 1", _add(c, day, "11:00", "Alt Medic", "022700070", "d3"), "ok")
        r = add_appt(c, day, "11:00", "In Comun", "022700071", "d2")
        res.check("запись в занятый другим врачом кабинет проходит с предупреждением",
                  (r.msg, r.status, json.loads(r.body)["tone"]), ("room_busy", 200, "warn"))
        res.check("и стоит в журнале", _blocks(c, day)["In Comun"]["room_id"], r1)
        res.check("в свободный от чужих кабинет — без предупреждения",
                  _add(c, day, "11:00", "In Liber", "022700072"), "ok")


def suite_commands(res: Result) -> None:
    """Смена кабинета записи, перенос, возврат статуса, длительность."""
    with Server() as s:
        c = Client(s.url).login()
        r1, r2 = set_rooms(c, "d2", "1", "3")
        day = _d(2)
        _add(c, day, "10:00", "Muta Unu", "022710001")
        _add(c, day, "10:00", "Muta Doi", "022710002")
        _add(c, day, "12:00", "Muta Trei", "022710003")
        a1, a3 = appt_id(c, day, "Muta Unu"), appt_id(c, day, "Muta Trei")

        res.check("в занятый кабинет — conflict", _post(c, a1, "room", {"room": r2}, day), "conflict")
        res.check("несуществующий кабинет — bad_room", _post(c, a1, "room", {"room": "r-zz"}, day), "bad_room")
        res.check("тот же кабинет — тихий успех", _post(c, a1, "room", {"room": r1}, day), "ok_room")
        r = c.post_json(f"/api/schedule/appointments/{a3}/room?date={day}", {"room": r2})
        col = next(x for x in json.loads(r.body)["data"]["canvas"]["columns"] if x["id"] == "d2")
        res.check("свободный кабинет — ok_room, ответ несёт свежий день",
                  (r.msg, next(b for b in col["blocks"] if b["id"] == a3)["room_id"]), ("ok_room", r2))
        res.check("панели — код без состояния",
                  "data" in json.loads(c.post_json(
                      f"/api/schedule/appointments/{a3}/room?screen=panel", {"room": r1}).body), False)
        _post(c, a3, "room", {"room": r2}, day)
        hist = json.loads(c.get(f"/api/patients/{json.loads(c.get(f'/api/schedule/day?date={day}').body)['data']['cards'][str(a3)]['pid']}").body)
        res.ok("смена кабинета — строкой в летописи пациента",
               "Cabinet schimbat: 1 › 3" in json.dumps(hist, ensure_ascii=False), "строки нет")

        # перенос: кабинет сохраняется; занят — первый свободный; оба заняты — conflict
        res.check("перенос на свободное время — кабинет тот же",
                  (_post(c, a3, "move", {"date": day, "time": "15:00", "doctor": "d2"}, day),
                   _blocks(c, day)["Muta Trei"]["room_id"]), ("ok_move", r2))
        _add(c, day, "17:00", "Ocupa Trei", "022710004", room=r2)
        res.check("перенос туда, где свой кабинет занят, — в свободный",
                  (_post(c, a3, "move", {"date": day, "time": "17:00", "doctor": "d2"}, day),
                   _blocks(c, day)["Muta Trei"]["room_id"]), ("ok_move", r1))
        res.check("перенос туда, где заняты оба, — conflict",
                  _post(c, a3, "move", {"date": day, "time": "10:00", "doctor": "d2"}, day), "conflict")
        res.check("перенос с назначенным занятым кабинетом — conflict",
                  _post(c, a3, "move", {"date": day, "time": "17:30", "doctor": "d2", "room": r2}, day),
                  "conflict")
        res.check("перенос к врачу без кабинетов — кабинет снимается",
                  (_post(c, a3, "move", {"date": day, "time": "17:00", "doctor": "d3"}, day),
                   _blocks(c, day, "d3")["Muta Trei"]["room_id"]), ("ok_move", ""))
        res.check("перенос с чужим кабинетом — bad_room",
                  _post(c, a3, "move", {"date": day, "time": "18:00", "doctor": "d3", "room": r1}, day),
                  "bad_room")

        # возврат отменённой: её кабинет заняли — возвращается в свободный
        day = _d(3)
        _add(c, day, "10:00", "Revine Unu", "022710011")
        b1 = appt_id(c, day, "Revine Unu")
        _post(c, b1, "status", {"to": "cancelled"}, day)
        _add(c, day, "10:00", "Revine Doi", "022710012")
        res.check("место отменённой занял другой (кабинет по умолчанию)",
                  _blocks(c, day)["Revine Doi"]["room_id"], r1)
        res.check("возврат отменённой проходит — во второй кабинет",
                  (_post(c, b1, "status", {"to": "confirmed"}, day),
                   _blocks(c, day)["Revine Unu"]["room_id"]), ("", r2))
        _add(c, day, "13:00", "Revine Trei", "022710013")
        b3 = appt_id(c, day, "Revine Trei")
        _post(c, b3, "status", {"to": "cancelled"}, day)
        _add(c, day, "13:00", "Revine Patru", "022710014")
        _add(c, day, "13:00", "Revine Cinci", "022710015")
        res.check("возврат, когда заняты оба кабинета, — conflict",
                  _post(c, b3, "status", {"to": "confirmed"}, day), "conflict")
        res.check("закрытой записи кабинет не меняют",
                  _post(c, b3, "room", {"room": r2}, day), "room_closed")

        # длительность: визит растёт в СВОЁМ кабинете, сосед из другого не мешает
        day = _d(4)
        _add(c, day, "10:00", "Dur Unu", "022710021", duration="30")
        _add(c, day, "10:30", "Dur Doi", "022710022", room=r2)
        _add(c, day, "11:00", "Dur Trei", "022710023", room=r1, duration="30")
        e1 = appt_id(c, day, "Dur Unu")
        res.check("удлинение до соседа в другом кабинете — проходит",
                  _post(c, e1, "duration", {"minutes": "60"}, day), "ok_dur")
        res.check("удлинение на соседа в своём кабинете — conflict",
                  _post(c, e1, "duration", {"minutes": "90"}, day), "conflict")


def suite_models(res: Result) -> None:
    """Контракт экрана: колонка, блок, карточка, повестка, форма, кресло,
    свободные старты, подсказка."""
    with Server() as s:
        c = Client(s.url).login()
        day = clinic_today().isoformat()
        base = day_model(c, day)
        col = next(x for x in base["canvas"]["columns"] if x["id"] == "d2")
        res.check("врач без кабинета: колонка без кабинетов, шапка пуста", (col["rooms"], col["room"]), ([], ""))
        res.check("форма записи: у врача пустой список кабинетов",
                  next(x for x in base["form"]["doctors"] if x["id"] == "d2")["rooms"], [])

        r1, r2 = set_rooms(c, "d2", "1", "3")
        want = [{"id": r1, "name": "1"}, {"id": r2, "name": "3"}]
        now = datetime.now(TZ)
        # сегодняшний час внутри графика: журнал принимает и уже прошедший
        t = f"{max(8, min(19, now.hour)):02d}:00"
        res.check("две записи на один старт", (_add(c, day, t, "Model Unu", "022720001"),
                                               _add(c, day, t, "Model Doi", "022720002")),
                  ("ok", "ok"))
        m = day_model(c, day)
        col = next(x for x in m["canvas"]["columns"] if x["id"] == "d2")
        res.check("колонка: кабинеты по порядку и строка шапки", (col["rooms"], col["room"]), (want, "1, 3"))
        blocks = {b["name"]: b for b in col["blocks"]}
        res.check("блоки: кабинет ключом и именем",
                  [(blocks[n]["room_id"], blocks[n]["room"]) for n in ("Model Unu", "Model Doi")],
                  [(r1, "1"), (r2, "3")])
        res.ok("подсказка блока называет кабинет", " · 3" in blocks["Model Doi"]["title"],
               blocks["Model Doi"]["title"])
        a2 = blocks["Model Doi"]["id"]
        res.check("карточка дня несёт тот же кабинет",
                  (m["cards"][str(a2)]["room_id"], m["cards"][str(a2)]["room"]), (r2, "3"))
        res.check("форма записи: кабинеты врача",
                  next(x for x in m["form"]["doctors"] if x["id"] == "d2")["rooms"], want)
        live = panel_live(c, day)
        res.check("канва панели и дня совпадают",
                  next(x for x in live["canvas"]["columns"] if x["id"] == "d2")["rooms"], want)
        items = {x["name"]: x for x in live["agenda"]["items"]}
        res.check("повестка: кабинет пункта", (items["Model Unu"]["room_id"], items["Model Doi"]["room_id"]),
                  (r1, r2))
        res.check("второй опрос канала без правок — 204",
                  c.get(f"/api/schedule/live?screen=panel&date={day}",
                        headers={"X-DP-Hash": c.get(
                            f"/api/schedule/live?screen=panel&date={day}").header("X-DP-Hash")}).status, 204)

        # кресло: по одному на кабинет, «не завершён» — внутри кабинета
        a1 = blocks["Model Unu"]["id"]
        for aid in (a1, a2):
            _post(c, aid, "status", {"to": "waiting"}, day)
            _post(c, aid, "status", {"to": "arrived"}, day)
        j = json.loads(c.get(f"/api/chair?doctor=d2&date={day}").body)["data"]
        res.check("два кабинета — два кресла, незавершённых нет",
                  (sorted(x["name"] for x in j["chairs"]), j["stale"]), (["Model Doi", "Model Unu"], []))
        res.ok("`chair` — один из сидящих", (j["chair"] or {}).get("name") in ("Model Unu", "Model Doi"), "")

        # врачи: список и фиша
        docs = json.loads(c.get("/api/doctors").body)["data"]["doctors"]
        d2 = next(x for x in docs if x["id"] == "d2")
        res.check("список врачей: кабинеты и имя первого", (d2["rooms"], d2["room"]), (want, "1"))
        card = json.loads(c.get("/api/doctors/d2").body)["data"]
        res.check("фиша врача: кабинеты, справочник, потолок",
                  (card["rooms"], card["rooms_all"], card["rooms_max"]), (want, want, 3))

        # свободные старты: свободен, пока свободен хоть один кабинет
        pid = new_patient(c, "Liber Start", "022720009")
        free_day = _d(3)

        def slots() -> list:
            r = c.get(f"/api/patients/{pid}/slots?date={free_day}&doctor=d2&service=consult")
            return json.loads(r.body)["data"]["slots"]

        def has(hhmm: str) -> bool:
            return hhmm in slots()

        res.ok("пустой день: 10:00 свободно", has("10:00"), f"{slots()[:3]}")
        _add(c, free_day, "10:00", "Liber Unu", "022720011")
        res.ok("один кабинет занят: 10:00 всё ещё свободно", has("10:00"), "")
        _add(c, free_day, "10:00", "Liber Doi", "022720012")
        res.ok("заняты оба: 10:00 не предлагается", not has("10:00"), "")
        res.ok("и 10:30 тоже (час занят в обоих)", not has("10:30"), "")
        res.ok("11:00 свободно", has("11:00"), "")
        c.post_json("/api/schedule/notes", {"date": free_day, "time": "15:00", "doctor": "d2", "text": "Lipsă"})
        res.ok("заметка закрывает старт во всех кабинетах", not has("15:00"), "")

        # запись из фиши идёт тем же правилом: предложенный старт принимается
        _add(c, free_day, "12:00", "Liber Trei", "022720013")
        res.ok("12:00 предложено: второй кабинет свободен", has("12:00"), "")
        r = c.post_json(f"/api/patients/{pid}/appoint",
                        {"date": free_day, "time": "12:00", "doctor": "d2", "service": "consult"})
        res.check("запись из фиши на предложенный старт проходит — во второй кабинет",
                  (r.msg, _blocks(c, free_day)["Liber Start"]["room_id"]), ("ok", r2))
        # выгрузка пациента по 195: кабинет записи едет в машинную копию
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.check("кабинет записи — в выгрузке пациента",
                  [v.get("room") for v in data["programari"]], ["3"])


def _doc_body(card: dict, **over) -> dict:
    body = {"name": card["name"], "spec": card["spec"], "phone": card["phone"],
            "email": card["email"], "color": card["color"], "auto_color": card["auto_color"],
            "work_from": "" if card["work_from"] is None else str(card["work_from"]),
            "work_to": "" if card["work_to"] is None else str(card["work_to"]),
            "status": card["status"]}
    body.update(over)
    return body


def suite_profile(res: Result) -> None:
    """Профиль: старая строка `room` читается на лету, список кабинетов
    заводится из фиши врача."""
    # профиль читается на старте: первый сервер только даёт папку с файлом
    with Server() as s0:
        cfg = json.loads(s0.clinic.read_text(encoding="utf-8"))
        for d in cfg["doctors"]:
            if d["id"] == "d2":
                d["room"] = "Cabinet 5"
        s0.clinic.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        before = s0.clinic.read_text(encoding="utf-8")
        with Server(dir_=s0.dir) as s:
            c = Client(s.url).login()
            card = json.loads(c.get("/api/doctors/d2").body)["data"]
            res.check("старая строка — единственный кабинет врача",
                      (card["rooms"], card["room"]), ([{"id": "r-cabinet-5", "name": "Cabinet 5"}], "Cabinet 5"))
            day = _d(2)
            res.check("запись ложится в него", (_add(c, day, "10:00", "Vechi Profil", "022730001"),
                                                _blocks(c, day)["Vechi Profil"]["room_id"]),
                      ("ok", "r-cabinet-5"))
            res.check("вторая на тот же старт — conflict, как было",
                      _add(c, day, "10:00", "Vechi Doi", "022730002"), "conflict")
            res.check("чтение профиль не переписывает", s.clinic.read_text(encoding="utf-8"), before)

            # старая форма (одна строка `room`) у врача с одним кабинетом — как было
            r = c.post_json("/api/doctors/d2", _doc_body(card, room="Cabinet 6"))
            res.check("старая форма меняет единственный кабинет",
                      (r.msg, json.loads(r.body)["data"]["rooms"]),
                      ("ok_med", [{"id": "r-cabinet-6", "name": "Cabinet 6"}]))
            saved = json.loads(s.clinic.read_text(encoding="utf-8"))
            d2 = next(d for d in saved["doctors"] if d["id"] == "d2")
            res.check("в файле: справочник, список врача и строка для отката",
                      (saved["rooms"], d2["rooms"], d2["room"]),
                      ([{"id": "r-cabinet-6", "name": "Cabinet 6", "active": True}],
                       ["r-cabinet-6"], "Cabinet 6"))
            res.check("запись в убранном кабинете читается в кабинете по умолчанию",
                      _blocks(c, day)["Vechi Profil"]["room_id"], "r-cabinet-6")

            # список из фиши: существующий по ключу, новый по имени, тот же по другому написанию
            r = c.post_json("/api/doctors/d2", _doc_body(card, rooms=[
                {"id": "r-cabinet-6"}, {"name": "Chirurgie"}, {"name": "cabinet 6"}]))
            got = json.loads(r.body)["data"]
            res.check("выбрать существующий и вписать новый; повтор имени не заводит второй",
                      (r.msg, got["rooms"], got["room"]),
                      ("ok_med", [{"id": "r-cabinet-6", "name": "Cabinet 6"},
                                  {"id": "r-chirurgie", "name": "Chirurgie"}], "Cabinet 6"))
            r = c.post_json("/api/doctors/d2", _doc_body(card, room="Altul"))
            res.check("старая форма у врача с двумя кабинетами их не трогает",
                      (r.msg, [x["id"] for x in json.loads(r.body)["data"]["rooms"]]),
                      ("ok_med", ["r-cabinet-6", "r-chirurgie"]))
            r = c.post_json("/api/doctors/d2", _doc_body(card, rooms=[
                {"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]))
            res.check("больше трёх — bad_rooms, поле названо",
                      (r.msg, r.status, json.loads(r.body).get("field")), ("bad_rooms", 422, "rooms"))
            res.check("неизвестный ключ — bad_rooms",
                      c.post_json("/api/doctors/d2", _doc_body(card, rooms=[{"id": "r-nu"}])).msg, "bad_rooms")
            res.check("кабинет без имени — bad_rooms",
                      c.post_json("/api/doctors/d2", _doc_body(card, rooms=[{"name": "  "}])).msg, "bad_rooms")
            r = c.post_json("/api/doctors/d2", _doc_body(card, rooms=[]))
            saved = json.loads(s.clinic.read_text(encoding="utf-8"))
            d2 = next(d for d in saved["doctors"] if d["id"] == "d2")
            res.check("пустой список снимает кабинеты; справочник остаётся",
                      (r.msg, "rooms" in d2, "room" in d2, len(saved["rooms"])), ("ok_med", False, False, 2))
            other = json.loads(c.get("/api/doctors/d3").body)["data"]
            res.check("другой врач выбирает из справочника",
                      [x["id"] for x in other["rooms_all"]], ["r-cabinet-6", "r-chirurgie"])

def suite_lanes(res: Result) -> None:
    """Канва: у врача с несколькими кабинетами колонка — дорожки кабинетов.
    Место блока говорит, в каком он кабинете, и свободная дорожка остаётся
    открытой для щелчка; у врача с одним кабинетом раскладка прежняя."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        res.check("врач с одним кабинетом: блок во всю колонку",
                  (_add(c, day, "10:00", "Singur Unu", "022730001", "d3"),
                   [(b["col"], b["of"]) for b in _blocks(c, day, "d3").values()]), ("ok", [(0, 1)]))
        r1, r2 = set_rooms(c, "d2", "1", "3")
        _add(c, day, "10:00", "Banda Unu", "022730002", room=r2)
        b = _blocks(c, day)
        res.check("одна запись во втором кабинете стоит в своей дорожке",
                  (b["Banda Unu"]["col"], b["Banda Unu"]["of"]), (1, 2))
        _add(c, day, "10:00", "Banda Doi", "022730003")
        _add(c, day, "10:30", "Banda Trei", "022730004", room=r2, duration=30)
        b = _blocks(c, day)
        res.check("одновременные записи — рядом, по порядку кабинетов врача",
                  [(b[n]["room_id"], b[n]["col"], b[n]["of"]) for n in ("Banda Doi", "Banda Unu")],
                  [(r1, 0, 2), (r2, 1, 2)])
        col = next(x for x in day_model(c, day)["canvas"]["columns"] if x["id"] == "d2")
        first = next(h["label"] for h, open_ in zip(day_model(c, day)["canvas"]["hours"], col["cells"]) if open_)
        res.check("«Liber de la»: час, занятый в одном кабинете, свободен",
                  (_add(c, day, first, "Banda Patru", "022730005"),
                   next(x for x in day_model(c, day)["canvas"]["columns"] if x["id"] == "d2")["free"]),
                  ("ok", first))
        # короткий блок дотягивается до соседа своей дорожки, чужая не мешает
        _add(c, day, "12:00", "Scurt Unu", "022730006", room=r1, duration=5)
        _add(c, day, "12:05", "Scurt Doi", "022730007", room=r2, duration=5)
        b = _blocks(c, day)
        res.check("короткий блок: сосед из другого кабинета высоту не режет",
                  (b["Scurt Unu"]["height"], b["Scurt Doi"]["height"]), (0.25, 0.25))
        note = c.post_json(f"/api/schedule/notes?date={day}",
                           {"date": day, "time": "14:00", "doctor": "d2", "text": "Pauza"})
        nb = _blocks(c, day).get("Pauza") or {}
        res.check("заметка стойки — во всю колонку", (note.msg, nb.get("col"), nb.get("of")),
                  ("ok_note", 0, 1))
