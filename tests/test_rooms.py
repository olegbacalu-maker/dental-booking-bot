# -*- coding: utf-8 -*-
"""Кабинет у записи: врач ведёт по записи в каждом своём кабинете.

Главное: у врача с ОДНИМ кабинетом (и без кабинета) не меняется ничего —
вторая запись на занятое время по-прежнему `conflict`.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone

from harness import (BOT, FIXTURES, PYTHON, TZ, Client, Result, Server, _rmtree_settled,
                     add_appt, appt_id, clinic_today, day_model, new_patient, panel_live,
                     set_rooms)


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _add(c: Client, day: str, time: str, name: str, phone: str,
         doctor: str = "d2", **fields) -> str:
    return add_appt(c, day, time, name, phone, doctor, **fields).msg


def _blocks(c: Client, day: str, dk: str = "d2") -> dict:
    col = next(x for x in day_model(c, day)["canvas"]["columns"] if x["id"] == dk)
    return {b.get("name") or b.get("text"): b for b in col["blocks"]}


def _post(c: Client, aid: int, what: str, payload: dict, day: str) -> str:
    return c.post_json(f"/api/schedule/appointments/{aid}/{what}?date={day}", payload).msg


def suite_rule(res: Result) -> None:
    """Занятость по кабинетам — дверью клиники (окно записи, перенос, статус)."""
    with Server() as s:
        c = Client(s.url).login()

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
    """Старая строка `room` читается на лету, список кабинетов заводится из фиши врача."""
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
    """Канва: у врача с несколькими кабинетами колонка — дорожки кабинетов."""
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
        # завершённая и новая запись на один час делят первый кабинет; второму это ширину не режет
        day2 = _d(2)
        _add(c, day2, "10:00", "Lat Vechi", "022730011", room=r1)
        _post(c, _blocks(c, day2)["Lat Vechi"]["id"], "status", {"to": "done"}, day2)
        _add(c, day2, "10:00", "Lat Nou", "022730012", room=r1)
        _add(c, day2, "10:15", "Lat Alaturi", "022730013", room=r2, duration=15)
        b = _blocks(c, day2)
        res.check("наложение в одном кабинете соседнюю дорожку не сужает",
                  [(b[n]["col"], b[n]["of"]) for n in ("Lat Vechi", "Lat Nou", "Lat Alaturi")],
                  [(0, 4), (1, 4), (1, 2)])

        # записи, сделанные до кабинетов, остаются в своём кабинете при смене порядка
        _add(c, day2, "12:00", "Fara Cabinet", "022730014", "d3")
        x, y = set_rooms(c, "d3", "X", "Y")
        res.check("запись без кабинета — в первом кабинете врача",
                  _blocks(c, day2, "d3")["Fara Cabinet"]["room_id"], x)
        res.check("вторая на тот же час ложится во второй",
                  (_add(c, day2, "12:00", "Cu Cabinet", "022730015", "d3"),
                   _blocks(c, day2, "d3")["Cu Cabinet"]["room_id"]), ("ok", y))
        set_rooms(c, "d3", "Y", "X")
        b = _blocks(c, day2, "d3")
        res.check("порядок кабинетов поменяли — записи остались каждая в своём",
                  [(b[n]["room_id"], b[n]["col"], b[n]["of"]) for n in ("Fara Cabinet", "Cu Cabinet")],
                  [(x, 1, 2), (y, 0, 2)])

def suite_move_overlap(res: Result) -> None:
    """Перенос и смена кабинета туда, где у этого же врача уже идёт визит: отказ по
    ПЕРЕСЕЧЕНИЮ интервалов. Уникальный индекс видит только совпавший старт —
    пересечение держит прикладная проверка."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        # запись, сделанная до кабинетов: кабинета у неё нет, читается в первом
        _add(c, day, "14:00", "Vechi Lung", "022740001", duration=60)
        r1, r2 = set_rooms(c, "d2", "1", "3")
        _add(c, day, "10:00", "Lung Unu", "022740002", room=r1, duration=60)
        _add(c, day, "10:30", "Scurt Doi", "022740003", room=r2, duration=15)
        _add(c, day, "14:20", "Scurt Trei", "022740004", room=r2, duration=10)
        a2, a3 = appt_id(c, day, "Scurt Doi"), appt_id(c, day, "Scurt Trei")
        mv = {"date": day, "doctor": "d2"}
        res.check("та же минута, занятый кабинет названа явно — conflict",
                  _post(c, a2, "move", {**mv, "time": "10:30", "room": r1}, day), "conflict")
        res.check("другое начало внутри чужого визита — conflict",
                  _post(c, a2, "move", {**mv, "time": "10:45", "room": r1}, day), "conflict")
        res.check("начало раньше, хвост заходит на чужой визит — conflict",
                  _post(c, a2, "move", {**mv, "time": "09:50", "room": r1}, day), "conflict")
        res.check("смена кабинета на занятый по интервалу — conflict",
                  _post(c, a2, "room", {"room": r1}, day), "conflict")
        res.check("запись без кабинета занимает первый: перенос в него — conflict",
                  (_post(c, a3, "move", {**mv, "time": "14:20", "room": r1}, day),
                   _post(c, a3, "room", {"room": r1}, day)), ("conflict", "conflict"))
        res.check("новая запись в занятый по интервалу кабинет — conflict",
                  _add(c, day, "14:30", "Nou Patru", "022740005", room=r1, duration=5), "conflict")
        b = _blocks(c, day)
        res.check("после отказов записи стоят где стояли",
                  [(b[n]["time"], b[n]["room_id"]) for n in ("Scurt Doi", "Scurt Trei")],
                  [("10:30", r2), ("14:20", r2)])
        res.check("впритык за визитом — можно",
                  _post(c, a2, "move", {**mv, "time": "11:00", "room": r1}, day), "ok_move")
        # порядок кабинетов поменяли: запись без кабинета осталась в своём
        set_rooms(c, "d2", "3", "1")
        res.check("после смены порядка: в кабинет старой записи — conflict, она на месте",
                  (_post(c, a3, "move", {**mv, "time": "14:30", "room": r1}, day),
                   _blocks(c, day)["Vechi Lung"]["room_id"]), ("conflict", r1))


def _save_rooms(c: Client, dk: str, *names: str):
    """Фиша врача с другим списком кабинетов — ответ как есть (отказ не роняет набор)."""
    card = json.loads(c.get(f"/api/doctors/{dk}").body)["data"]
    return c.post_json(f"/api/doctors/{dk}", _doc_body(card, rooms=[{"name": n} for n in names]))


def _lanes_of(c: Client, day: str, dk: str = "d2") -> dict:
    return {n: (b["room_id"], b["room"]) for n, b in _blocks(c, day, dk).items()}


def suite_room_removed(res: Result) -> None:
    """Кабинет убрали из фиши врача: его будущие записи не ложатся молча поверх
    записей оставшегося кабинета. До починки сохранение проходило (`ok_med`), и
    обе записи на 10:00 читались в первом кабинете."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(2)
        r1, r3 = set_rooms(c, "d2", "1", "3")
        _add(c, day, "10:00", "Rm Unu", "022760001", room=r1, duration=60)
        _add(c, day, "10:00", "Rm Trei", "022760002", room=r3, duration=60)
        r = _save_rooms(c, "d2", "1")
        body = json.loads(r.body)
        res.check("убрать кабинет, чья будущая запись легла бы внахлёст, — отказ 409, поле кабинетов",
                  (r.msg, r.status, body.get("field")), ("rooms_busy", 409, "rooms"))
        text = body.get("text", "")
        res.ok("отказ называет кабинет, число и с кем наложится",
               "„3”" in text and "o programare viitoare" in text and "Rm Trei" in text, text)
        res.check("после отказа кабинеты те же, записи каждая в своём",
                  ([x["id"] for x in json.loads(c.get("/api/doctors/d2").body)["data"]["rooms"]],
                   _lanes_of(c, day)["Rm Trei"][0]), ([r1, r3], r3))

        aid = appt_id(c, day, "Rm Trei")
        _post(c, aid, "move", {"date": day, "doctor": "d2", "time": "12:00", "room": r3}, day)
        r = _save_rooms(c, "d2", "1")
        res.check("без наложения — сохранено с предупреждением, запись перешла в оставшийся",
                  (r.msg, json.loads(r.body)["tone"], _lanes_of(c, day)["Rm Trei"]),
                  ("ok_med_moved", "warn", (r1, "1")))

        # переименование: новое имя = новый ключ, запись едет в него, а не в соседний
        ra, rb = set_rooms(c, "d3", "A", "B")
        _add(c, day, "15:00", "Rm Be", "022760003", "d3", room=rb, duration=30)
        r = _save_rooms(c, "d3", "A", "Be nou")
        res.check("переименованный кабинет: запись в нём, без лишних слов",
                  (r.msg, _lanes_of(c, day, "d3")["Rm Be"]), ("ok_med", ("r-be-nou", "Be nou")))

        # прошлое не держит: вчерашние записи внахлёст в убираемом кабинете
        rx, ry = set_rooms(c, "d4", "X", "Y")
        _add(c, _d(-1), "09:00", "Ieri X", "022760004", "d4", room=rx, duration=30)
        _add(c, _d(-1), "09:00", "Ieri Y", "022760005", "d4", room=ry, duration=30)
        res.check("прошлая запись в убираемом кабинете сохранению не мешает",
                  _save_rooms(c, "d4", "X").msg, "ok_med")

        # все кабинеты сняты: будущие записи двух кабинетов легли бы в одну колонку
        set_rooms(c, "d4", "X", "Y")
        _add(c, day, "11:00", "Gol X", "022760006", "d4", room=rx, duration=30)
        _add(c, day, "11:00", "Gol Y", "022760007", "d4", room=ry, duration=30)
        res.check("снять все кабинеты при одновременных будущих записях — отказ",
                  (_save_rooms(c, "d4").msg, len(json.loads(c.get("/api/doctors/d4").body)["data"]["rooms"])),
                  ("rooms_busy", 2))


def _worker_race(tmpdir: str) -> None:
    """Запись ждёт замка брони, пока врачу убирают кабинет. Её список кабинетов
    снят до замка и ещё помнит убранный — запись обязана прочитать новый."""
    import asyncio

    base = pathlib.Path(tmpdir)
    os.environ.update({"CLINIC_CONFIG": str(base / "clinic.json"),
                       "DATABASE_URL": f"sqlite:///{base / 'dental.db'}", "ADMIN_KEY": ""})
    sys.path.insert(0, str(BOT))
    from app import db
    from app import engine as eng
    from app.modules.doctors import routes as droutes

    async def spin() -> None:
        for _ in range(50):
            await asyncio.sleep(0)

    async def main() -> None:
        await db.init([])
        try:
            name = eng.DOCTORS["d2"]
            print("rooms", await droutes._save_doctor(
                "d2", name=name, rooms=[{"name": "1"}, {"name": "3"}]))
            r1, r3 = eng.doctor_rooms("d2")
            at = (datetime.now(eng.TZ) + timedelta(days=2)).replace(hour=10, minute=0, second=0,
                                                                    microsecond=0)
            print("first", isinstance(await db.admin_add(
                "Rc Unu", "022780001", "Consultație", name, at, doctor_id="d2",
                service_id="consult", rooms=eng.room_plan("d2"), room=r1), int))
            stale = eng.room_plan("d2")
            for n, (label, room) in enumerate((("explicit", r3), ("auto", None))):
                # замок держит проба: смена кабинетов встаёт в очередь первой,
                # запись со списком, снятым ДО неё, — второй
                async with db._slot_lock():
                    save = asyncio.ensure_future(droutes._save_doctor(
                        "d2", name=name, rooms=[{"name": "1"}]))
                    await spin()
                    book = asyncio.ensure_future(db.admin_add(
                        f"Rc {label}", f"02278001{n}", "Consultație", name, at,
                        doctor_id="d2", service_id="consult", rooms=stale, room=room))
                    await spin()
                print(f"{label}_save", await save)
                print(f"{label}_book", await book)
                print(f"{label}_rows", await db._fetchval(
                    "SELECT COUNT(*) FROM appointments WHERE doctor_id = 'd2' AND status = 'confirmed'"))
                await db._execute("UPDATE appointments SET status = 'cancelled' WHERE patient_id IN "
                                  "(SELECT id FROM patients WHERE name = ?)", f"Rc {label}")
                await droutes._save_doctor("d2", name=name, rooms=[{"name": "1"}, {"name": "3"}])
            # галочку Control снимают, пока запись в полосу ждёт замка
            await droutes._set_parallel("d2", True)
            stale = eng.room_plan("d2")
            async with db._slot_lock():
                save = asyncio.ensure_future(droutes._set_parallel("d2", False))
                await spin()
                book = asyncio.ensure_future(db.admin_add(
                    "Rc control", "022780019", "Consultație", name, at, doctor_id="d2",
                    service_id="consult", rooms=stale, room=db.CONTROL_LANE))
                await spin()
            print("control_save", (await save)[0])
            print("control_book", await book)
        finally:
            await db.close()

    asyncio.run(main())


def suite_room_race(res: Result) -> None:
    """Смена кабинетов врача и запись, ждавшая замка брони: запись не ложится в
    убранный кабинет (а значит, внахлёст в оставшемся)."""
    base = pathlib.Path(tempfile.mkdtemp(prefix="dp_rrace_"))
    try:
        shutil.copy(FIXTURES / "clinic_test.json", base / "clinic.json")
        r = subprocess.run([str(PYTHON), str(pathlib.Path(__file__).resolve()), "worker-race", str(base)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, env=dict(os.environ))
        got = dict(line.split(" ", 1) for line in (r.stdout or "").splitlines() if " " in line)
        if not res.ok("проба поднялась", r.returncode == 0 and got.get("first") == "True",
                      f"rc={r.returncode}: {got} {(r.stderr or '')[-1200:]}"):
            return
        for label in ("explicit", "auto"):
            what = "убранный кабинет назван явно" if label == "explicit" else "кабинет не выбран"
            res.check(f"{what}: кабинет убран, ждавшая запись — отказ, в базе одна запись",
                      (got.get(f"{label}_save"), got.get(f"{label}_book"), got.get(f"{label}_rows")),
                      ("ok_med", "None", "1"))
        res.check("галочку Control сняли, пока запись в полосу ждала замка, — запись не легла",
                  (got.get("control_save"), got.get("control_book")), ("ok_par_off", "None"))
    finally:
        _rmtree_settled(base)


CTL = "~control"


def _doctor_pct(c: Client, day: str, dk: str) -> int:
    d = json.loads(c.get(f"/api/stats?from={day}&to={day}").body)["data"]
    return next(x["pct"] for x in d["doctors"] if x["id"] == dk)


def _export_rows(c: Client, day: str) -> str:
    xl = c.get(f"/admin/export.xlsx?from={day}&to={day}")
    with zipfile.ZipFile(io.BytesIO(xl.raw)) as z:
        return z.read("xl/worksheets/sheet1.xml").decode("utf-8")


def suite_control_lane(res: Result) -> None:
    """Дорожка Control (галочка «Programări paralele»): запись туда — только явным
    выбором человека; свободное время, «Liber de la» и загрузка её не считают."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(2)
        res.check("без галочки дорожки нет: room=~control — bad_room",
                  _add(c, day, "10:00", "Fara Gal", "022750001", "d3", room=CTL), "bad_room")
        r = c.post_json("/api/doctors/d3/parallel", {"on": True})
        res.check("галочка включается, фиша врача её несёт",
                  (r.msg, json.loads(r.body)["data"]["parallel"]), ("ok_par_on", True))
        res.check("основная запись", _add(c, day, "10:00", "Baza Unu", "022750002", "d3", duration=60), "ok")
        res.check("без выбора на занятый час — conflict, сервер в Control сам не кладёт",
                  _add(c, day, "10:00", "Auto Doi", "022750003", "d3", duration=15), "conflict")
        res.check("явный Control на тот же час — ok",
                  _add(c, day, "10:00", "Ctl Trei", "022750004", "d3", room=CTL, duration=15), "ok")
        res.check("Control занят по минутам — conflict",
                  _add(c, day, "10:10", "Ctl Patru", "022750005", "d3", room=CTL, duration=15), "conflict")
        b = _blocks(c, day, "d3")
        res.check("канва: основная и Control — две дорожки, имя у записи «Control»",
                  [(b[n]["room_id"], b[n]["col"], b[n]["of"]) for n in ("Baza Unu", "Ctl Trei")]
                  + [b["Ctl Trei"]["room"]], [("", 0, 2), (CTL, 1, 2), "Control"])
        feed = json.loads(c.get(f"/api/patients/{b['Ctl Trei']['pid']}/activity").body)["data"]["items"]
        res.ok("летопись пациента: запись в полосе — «(Control)» после врача",
               any("Dr. Activ Trei (Control)" in x["text"] for x in feed), f"{[x['text'] for x in feed]}")
        col = next(x for x in day_model(c, day)["canvas"]["columns"] if x["id"] == "d3")
        res.check("колонка: дорожки Principal и Control",
                  [(r["id"], r["name"], r.get("control", False)) for r in col["rooms"]],
                  [("", "Principal", False), (CTL, "Control", True)])
        res.check("загрузка колонки без минут Control", col["occupancy"]["busy"], 60)
        res.check("форма записи: у врача с галочкой — дорожки и признак",
                  [(x["id"], x.get("parallel", False), len(x["rooms"]))
                   for x in day_model(c, day)["form"]["doctors"] if x["id"] in ("d2", "d3")],
                  [("d2", False, 0), ("d3", True, 2)])
        # основная 11:00–12:00 занята, Control свободен — час 11 не свободен
        _add(c, day, "11:00", "Baza Cinci", "022750006", "d3", duration=60)
        pid = new_patient(c, "Liber Sase", "022750007")
        slots = json.loads(c.get(f"/api/patients/{pid}/slots?date={day}&doctor=d3&service=consult").body)["data"]["slots"]
        res.check("свободные старты (и «Primul loc liber»): час, занятый в основной, не предлагается",
                  [t for t in slots if t.startswith(("10:", "11:"))], [])
        res.check("у другого врача без галочки Control не принимается",
                  _add(c, day, "12:00", "Alt Doi", "022750009", "d2", room=CTL), "bad_room")

        pct = _doctor_pct(c, day, "d3")
        _add(c, day, "11:15", "Ctl Sapte", "022750014", "d3", room=CTL, duration=30)
        res.check("статистика: «Grad de ocupare» врача без минут Control",
                  _doctor_pct(c, day, "d3"), pct)
        sheet = _export_rows(c, day)
        res.ok("Excel: колонка «Cabinet», у записи в полосе — «Control»",
               '<t>Cabinet</t>' in sheet and '<t xml:space="preserve">Control</t>' in sheet,
               sheet[:400])

        base = appt_id(c, day, "Baza Cinci")
        mv3 = {"date": day, "doctor": "d3"}
        res.check("перенос в Control явным выбором (бросок на полосу) — ok, запись в полосе",
                  (_post(c, base, "move", {**mv3, "time": "12:00", "room": CTL}, day),
                   _blocks(c, day, "d3")["Baza Cinci"]["room_id"]), ("ok_move", CTL))
        res.check("обратно без выбора дорожки — в основную",
                  (_post(c, base, "move", {**mv3, "time": "12:00"}, day),
                   _blocks(c, day, "d3")["Baza Cinci"]["room_id"]), ("ok_move", ""))
        aid = appt_id(c, day, "Ctl Trei")
        res.check("окно визита: из Control в основную у врача без кабинетов — занята, conflict",
                  _post(c, aid, "room", {"room": ""}, day), "conflict")
        _post(c, aid, "move", {**mv3, "time": "13:00", "room": CTL}, day)
        res.check("окно визита: из Control в основную, где свободно — ok, запись без кабинета",
                  (_post(c, aid, "room", {"room": ""}, day), _blocks(c, day, "d3")["Ctl Trei"]["room_id"]),
                  ("ok_room", ""))
        res.check("окно визита: пустой кабинет у записи в основной — bad_room",
                  _post(c, aid, "room", {"room": ""}, day), "bad_room")
        res.check("окно визита: в Control явным выбором — ok",
                  (_post(c, aid, "room", {"room": CTL}, day), _blocks(c, day, "d3")["Ctl Trei"]["room_id"]),
                  ("ok_room", CTL))

        r = c.post_json("/api/doctors/d3/parallel", {"on": False})
        body = json.loads(r.body)
        res.check("снять галочку при будущих записях в Control — par_busy 409 с числом",
                  (r.msg, r.status, body["data"]["n"]), ("par_busy", 409, 2))
        res.ok("отказ называет число словами", "2 programări viitoare" in body["text"], body["text"])
        res.check("после отказа галочка стоит",
                  json.loads(c.get("/api/doctors/d3").body)["data"]["parallel"], True)
        for n in ("Ctl Trei", "Ctl Sapte"):
            _post(c, appt_id(c, day, n), "status", {"to": "cancelled"}, day)
        res.check("без будущих записей в полосе — снимается",
                  c.post_json("/api/doctors/d3/parallel", {"on": False}).msg, "ok_par_off")

        r1, r2 = set_rooms(c, "d2", "1", "3")
        c.post_json("/api/doctors/d2/parallel", {"on": True})
        res.check("два кабинета: первые две — в кабинеты",
                  (_add(c, day, "15:00", "Cab Unu", "022750010", duration=30),
                   _add(c, day, "15:00", "Cab Doi", "022750011", duration=30)), ("ok", "ok"))
        res.check("третья без выбора — conflict (Control автовыбор не видит)",
                  _add(c, day, "15:00", "Cab Trei", "022750012", duration=15), "conflict")
        c.post_json("/api/doctors/d4/parallel", {"on": True})
        _add(c, day, "10:00", "Ctl Alt Med", "022750015", "d4", room=CTL, duration=15)
        res.check("Control у двух врачей в одно время — не «кабинет занят другим врачом»",
                  _add(c, day, "10:00", "Ctl Doi Med", "022750013", room=CTL, duration=15), "ok")
        b = _blocks(c, day)
        res.check("Control — третья дорожка", (b["Ctl Doi Med"]["col"], b["Ctl Doi Med"]["of"]), (2, 3))
        aid = appt_id(c, day, "Ctl Doi Med")
        res.check("перенос из Control без выбора дорожки — в основную (или отказ), не молча в Control",
                  (_post(c, aid, "move", {"date": day, "doctor": "d2", "time": "15:00"}, day),
                   _blocks(c, day)["Ctl Doi Med"]["room_id"]), ("conflict", CTL))
        _post(c, appt_id(c, day, "Cab Doi"), "status", {"to": "cancelled"}, day)
        res.check("убрать кабинет: записи Control не переезжают и не мешают",
                  (_save_rooms(c, "d2", "1").msg, _blocks(c, day)["Ctl Doi Med"]["room_id"]),
                  ("ok_med", CTL))


def suite_control_refusal(res: Result) -> None:
    """Отказ «врач занят» у врача с Control называет, кто занимает, до какого часа и
    ближайшее свободное время основной колонки; у врача без Control — прежний."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(2)
        c.post_json("/api/doctors/d3/parallel", {"on": True})
        _add(c, day, "10:00", "Pr Baza", "022770001", "d3", duration=90)
        r = add_appt(c, day, "10:30", "Pr Nou", "022770002", "d3", duration=30)
        body = json.loads(r.body)
        res.check("отказ у врача с Control: кто и до какого часа, ближайшее свободное",
                  (r.msg, r.status, body["data"]["who"], body["data"]["from"], body["data"]["to"],
                   body["data"]["next"]), ("conflict", 409, "Pr Baza", "10:00", "11:30", "11:30"))
        res.ok("слово отказа называет занятого", "Pr Baza" in body["text"] and "10:00–11:30" in body["text"],
               body["text"])
        res.check("в Control отказ сам не кладёт: записей у врача одна",
                  [n for n in _blocks(c, day, "d3")], ["Pr Baza"])
        _add(c, day, "10:00", "Pr Alt0", "022770004", "d4", duration=60)
        res.check("у врача без Control отказ прежний, без данных",
                  "data" in json.loads(add_appt(c, day, "10:00", "Pr Alt", "022770003", "d4",
                                                duration=30).body), False)
        res.check("длительность в Control любая",
                  _add(c, day, "12:00", "Pr Lung", "022770005", "d3", room=CTL, duration=90), "ok")


def suite_control_gcal(res: Result) -> None:
    """Вкладка «Google Calendar» в полосу Control сама не кладёт; явный выбор «Control» в
    окне переноса принимается в обеих ветках шва (`gcal._journal_add`)."""
    from test_gcal import base_events, cal, loaded, move_body, row
    with Server() as s:
        c = Client(s.url).login()
        loaded(res, c, cal(base_events()), "загрузка")
        c.post_json("/api/doctors/d2/parallel", {"on": True})
        a1 = row(c, "Popescu Ion")
        day = _d(3)
        _add(c, day, "09:00", "Ocupat Gcal", "022790001", duration=60)
        r = c.post_json(f"/api/gcal/events/{a1['id']}/move", move_body(3, "09:00", "Ion Popescu", "069123456"))
        res.check("на занятый час без кабинета — conflict, не в Control", r.msg, "conflict")
        res.check("в журнале одна запись", list(_blocks(c, day)), ["Ocupat Gcal"])
        # окно переноса — то же окно записи: «Control» в нём выбирает человек
        pid = new_patient(c, "Ion Popescu", "069123456")
        r = c.post_json(f"/api/gcal/events/{a1['id']}/move",
                        move_body(3, "09:00", "Ion Popescu", "069123456", room=CTL, pid=pid))
        res.check("явный выбор Control в окне переноса (фиша выбрана) — ok, запись в полосе",
                  (r.msg, _blocks(c, day)["Ion Popescu"]["room_id"]), ("ok", CTL))


_WORKERS = {"worker-race": _worker_race}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in _WORKERS:
        _WORKERS[sys.argv[1]](sys.argv[2])
    else:
        print("Это файл наборов. Запускать: python tests\\run_tests.py rooms")
        sys.exit(2)
