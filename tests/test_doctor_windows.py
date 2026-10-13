"""Окна расписания: обед впритык к краям дня и личный график врача.

Две родственные дыры одного корня (ревью 08-15): fits_clinic резал день обедом
только при строгом зазоре с обеих сторон, а «Oricare disponibil» и серверные
правила записи и переноса (`_add_appt`, `_move_appt`) проверяли занятость и
окно КЛИНИКИ, но не окно ВРАЧА (work_from/work_to) — визит садился на час,
когда врача нет.
Ответ один на всех: eng.fits_doctor поверх тех же окон, что строит free_starts.
"""
import json
import os
import subprocess
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from harness import (BOT, PYTHON, TG_ON, Bot, Client, Result, Server, appt_id, clinic_today,
                     day_model)


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _add(c: Client, day: str, time: str, doctor: str, name: str,
         phone: str, service: str = "consult") -> str:
    return c.post_json("/api/schedule/appointments", {"date": day, "time": time,
                                                     "doctor": doctor, "service": service,
                                                     "name": name, "phone": phone}).msg


def _row_of(c: Client, day: str, name: str) -> dict:
    """Строка «Lista zilei» с этим пациентом — из модели дня."""
    return next((r for r in day_model(c, day)["list"] if r["name"] == name), {})


def suite_fits(res: Result) -> None:
    """fits_clinic: обед разрезает день и когда он ПРИМЫКАЕТ к краю.

    Настройки (_val_hours) допускают f <= bf < bt <= to, а старое условие
    «bf < bt < to and f < bf» на таком дне схлопывало окно в одно целое —
    /admin/add принимал визит в перерыв, который канва штрихует.
    """
    code = r"""
import json, sys
sys.path.insert(0, r"%s")
from datetime import datetime, timedelta, date
from app import engine as eng

def fits(hours, hh, mm, dur):
    d = datetime.now(eng.TZ).date() + timedelta(days=1)   # день клиники, не машины
    eng.CONFIG["hours"] = {k: hours for k in
                           ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    return eng.fits_clinic(
        datetime(d.year, d.month, d.day, hh, mm, tzinfo=eng.TZ), dur)

out = {
 "lunch_till_close":    fits([8, 13, 11, 13], 11, 30, 30),
 "before_such_lunch":   fits([8, 13, 11, 13], 10, 0, 60),
 "lunch_from_open":     fits([8, 17, 8, 9], 8, 0, 30),
 "after_such_lunch":    fits([8, 17, 8, 9], 9, 0, 60),
 "start_at_lunch":      fits([9, 18, 13, 14], 13, 0, 30),
 "end_at_lunch_start":  fits([9, 18, 13, 14], 12, 0, 60),
 "inside_lunch_to_end": fits([9, 18, 13, 14], 13, 30, 30),
 "cross_lunch":         fits([9, 18, 13, 14], 12, 30, 60),
 "start_at_lunch_end":  fits([9, 18, 13, 14], 14, 0, 30),
 "end_at_close":        fits([9, 18, 13, 14], 17, 0, 60),
 "past_close":          fits([9, 18, 13, 14], 17, 30, 60),
 "no_lunch_noon":       fits([9, 18], 12, 0, 60),
}
print(json.dumps(out))
""" % str(BOT)
    from harness import FIXTURES
    env = dict(os.environ)
    env["CLINIC_CONFIG"] = str(FIXTURES / "clinic_test.json")
    p = subprocess.run([str(PYTHON), "-c", code], cwd=str(BOT), text=True,
                       capture_output=True, env=env)
    if p.returncode != 0:
        res.failed.append(("fits_clinic: запуск", p.stderr[-500:]))
        return
    v = json.loads(p.stdout)
    # обед [11,13] при работе [8,13] — впритык к закрытию; раньше «влезало»
    res.check("обед до самого закрытия: 11:30 НЕ проходит",
              v["lunch_till_close"], False)
    res.check("а утро того же дня проходит", v["before_such_lunch"], True)
    # обед [8,9] при работе [8,17] — с самого открытия
    res.check("обед с открытия: 8:00 НЕ проходит", v["lunch_from_open"], False)
    res.check("а 9:00 того же дня проходит", v["after_such_lunch"], True)
    # обычный обед посередине — границы впритык
    res.check("старт ровно в начало обеда — отказ", v["start_at_lunch"], False)
    res.check("конец ровно в начало обеда — проходит",
              v["end_at_lunch_start"], True)
    res.check("внутри обеда до его конца — отказ",
              v["inside_lunch_to_end"], False)
    res.check("визит поперёк обеда — отказ", v["cross_lunch"], False)
    res.check("старт ровно в конец обеда — проходит",
              v["start_at_lunch_end"], True)
    res.check("конец ровно в закрытие — проходит", v["end_at_close"], True)
    res.check("хвост за закрытием — отказ", v["past_close"], False)
    res.check("день без обеда цел", v["no_lunch_noon"], True)


def suite_any(res: Result) -> None:
    """«Oricare disponibil» отдаёт визит врачу, который в этот час РАБОТАЕТ.

    da принимает 9–13, db — 14–18; слот 15:00 предложен free_starts из окна db.
    Старый отбор кандидатов смотрел только занятость — и отдавал визит da
    (первому в списке): он в 15:00 не занят, он в 15:00 просто не работает.
    """
    with Server(clinic="clinic_split.json", env=TG_ON) as s:
        day = _d(1)
        bot = Bot(Client(s.url), "any-window-test")
        bot.say("/start"); bot.say("lang:ro"); bot.say("book")
        bot.say("svc:consult"); bot.say("doc:any")
        _texts, buttons = bot.say(f"day:{day}")
        res.ok("слот 15:00 предложен (окно вечернего врача)",
               f"time:{day}T15:00" in buttons, f"кнопки: {buttons[:12]}")
        bot.say(f"time:{day}T15:00")
        bot.say("Ion Oricare"); bot.say("skip_year"); bot.say("069555444")
        texts, _b = bot.say("confirm")
        res.ok("визит достался вечернему врачу (db), не утреннему",
               "Zi Seara" in texts and "Dimineata" not in texts,
               f"ответ бота: {texts[:160]!r}")

        c = Client(s.url).login()
        row = _row_of(c, day, "Ion Oricare")
        res.check("и в журнале визит стоит у вечернего врача",
                  row.get("doctor"), "Dr. Zi Seara")


def suite_routes(res: Result) -> None:
    """Запись и перенос проверяют график врача НА СЕРВЕРЕ.

    Окно записи предлагает часы врача, но вкладка с журналом живёт долго, а
    график меняется на другом экране — браузеру верить нельзя (докстринг
    `_move_appt` сам называет график врача причиной перепроверки).
    """
    with Server(clinic="clinic_split.json") as s:
        c = Client(s.url).login()
        day = _d(1)

        # --- ручная запись ---
        res.check("утреннему врачу утром — ok",
                  _add(c, day, "10:00", "da", "Bun Ora", "022600100"), "ok")
        res.check("утреннему врачу в 15:00 — отказ по ЕГО графику",
                  _add(c, day, "15:00", "da", "Rau Ora", "022600200"),
                  "outside_doc")
        res.check("вечернему врачу в 8:00 — тот же отказ",
                  _add(c, day, "08:00", "db", "Rau Ora", "022600200"),
                  "outside_doc")
        res.check("вечернему врачу в 15:00 — ok",
                  _add(c, day, "15:00", "db", "Rau Ora", "022600200"), "ok")
        # длительность считается целиком: 60' с 12:30 вылезают за work_to=13
        res.check("60' ровно до конца окна врача — ok",
                  _add(c, day, "12:00", "da", "Fix Ora", "022600300"), "ok")
        res.check("60' с 12:30 вылезают за окно врача — отказ",
                  _add(c, day, "12:30", "da", "Peste Ora", "022600400"),
                  "outside_doc")

        # --- перенос ---
        day2 = _d(2)
        _add(c, day2, "15:00", "db", "Mutare Test", "022600500")
        aid = appt_id(c, day2, "Mutare Test")

        def move(to_time: str, to_doc: str) -> str:
            return c.post_json(f"/api/schedule/appointments/{aid}/move", {"date": day2,
                                                                         "time": to_time,
                                                                         "doctor": to_doc}).msg

        res.check("перенос утреннему врачу на 15:00 — отказ по его графику",
                  move("15:00", "da"), "outside_doc")
        row = _row_of(c, day2, "Mutare Test")
        res.check("отбитый визит остался у вечернего врача",
                  (row.get("doctor"), row.get("time")), ("Dr. Zi Seara", "15:00"))
        res.check("перенос утреннему врачу на его утро — ok",
                  move("11:00", "da"), "ok_move")
        # переносу хватает 30 минут в окне врача — та же поблажка, что у
        # окна клиники (визит уже существует, записан внахлёст — не наказываем)
        res.check("перенос на 12:30 (30' до конца окна) — ok",
                  move("12:30", "da"), "ok_move")

        # --- постфактум: прошлое графиком врача НЕ гейтится ---
        # ⭐ Смысл гейта — не обещать пациенту час, когда врача нет. У приёма,
        # который УЖЕ состоялся, обещать нечего: директор мог сузить график
        # после него, и тогда внести тот визит стало бы нечем — фиша прошлое
        # не берёт по замыслу, журнал остаётся единственным входом.
        res.check("вчера в часы врача — ok_past, как раньше",
                  _add(c, _d(-1), "10:00", "da", "Ieri Ora", "022600600"),
                  "ok_past")
        res.check("вчера ВНЕ часов врача — тоже принимается, задним числом",
                  _add(c, _d(-1), "15:00", "da", "Ieri Rau", "022600700"),
                  "ok_past")
        # ⚠️ Граница тут МГНОВЕННАЯ (is_past), а не дневная: «приём был сегодня
        # утром, а график сузили после обеда» — тот же постфактум, и на дневной
        # границе он остался бы невозможным. Час считается от текущего времени,
        # поэтому проверка живёт, только когда он попадает в часы клиники 8–18
        # (тот же приём, что в test_booking: ночной прогон не краснеет).
        # час берётся в поясе КЛИНИКИ (сервер строит dt в eng.TZ), а не в
        # поясе машины: на ноутбуке в другом поясе выбор был бы не тем часом
        h = datetime.now(ZoneInfo("Europe/Chisinau")).hour - 2
        if 8 <= h <= 17:
            # врач выбирается ТОТ, кто в этот час не принимает: da — 9–13,
            # db — 14–18, и час 13 не входит ни в одно окно целиком (60')
            res.check("сегодня в прошедший час вне окна врача — принимается",
                      _add(c, _d(0), f"{h:02d}:00", "db" if h < 13 else "da",
                           "Azi Trecut", "022601000"), "ok")


def suite_drop(res: Result) -> None:
    """Ячейка С ЗАПИСЬЮ — тоже мишень перетаскивания.

    Старая страница искала цель через closest('td[data-h]'), и без атрибута на
    занятой ячейке бросок на 10:30 часа, где в 10:00 уже стоит визит, молча
    умирал. У канвы (оба экрана журнала — 06.10) мишень — ячейка с
    `cells[i] = true`: признак от ГРАФИКА врача, не от занятости, и визит
    лежит поверх ячейки, а не вместо неё.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        _add(c, day, "10:00", "d2", "Drop Busy", "022600800")
        for doctor in ("", "d2"):
            canvas = day_model(c, day, doctor)["canvas"]
            hours = [h["h"] for h in canvas["hours"]]
            col = next((x for x in canvas["columns"] if x["id"] == "d2"), None)
            where = f"день {'врача' if doctor else 'всех'}"
            res.ok(f"{where}: занятый час 10:00 — мишень переноса",
                   col is not None and 10 in hours and col["cells"][hours.index(10)],
                   f"ячейка с визитом не принимает бросок: {col and col['cells']}")
            res.ok(f"{where}: визит лежит в колонке своего врача",
                   col is not None and any(b.get("name") == "Drop Busy"
                                           for b in col["blocks"]),
                   "блока визита нет в колонке d2")
    # обратная сторона: час ВНЕ приёма мишенью не стал
    with Server(clinic="clinic_hours.json") as s2:
        c2 = Client(s2.url).login()
        canvas = day_model(c2, _d(1))["canvas"]
        hours = [h["h"] for h in canvas["hours"]]
        lunch = [col["cells"][hours.index(13)] for col in canvas["columns"]
                 if not col["orphan"]] if 13 in hours else []
        res.ok("обед клиники — ряд, и его ячейки не мишени",
               bool(lunch) and not any(lunch),
               f"ряды {hours}, ячейки 13:00 {lunch}")
