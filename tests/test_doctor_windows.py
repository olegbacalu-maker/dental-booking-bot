"""Окна расписания: обед впритык к краям дня и личный график врача.

Две родственные дыры одного корня (ревью 08-15): fits_clinic резал день обедом
только при строгом зазоре с обеих сторон, а «Oricare disponibil» и серверные
маршруты /admin/add и /admin/move проверяли занятость и окно КЛИНИКИ, но не
окно ВРАЧА (work_from/work_to) — визит садился на час, когда врача нет.
Ответ один на всех: eng.fits_doctor поверх тех же окон, что строит free_starts.
"""
import json
import os
import re
import subprocess
from datetime import date, timedelta

from harness import BOT, PYTHON, TG_ON, Bot, Client, Result, Server


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _add(c: Client, day: str, time: str, doctor: str, name: str,
         phone: str, service: str = "consult") -> str:
    return c.post("/admin/add", adate=day, atime=time, adoctor=doctor,
                  aservice=service, aname=name, aphone=phone,
                  back="/admin/all").msg


def _row_of(page: str, name: str) -> str:
    """Строка «Lista zilei» с этим пациентом (см. test_booking._row_of)."""
    page = page.split("Lista zilei", 1)[-1]
    for m in re.finditer(r"<tr class='[^']*'>.*?</tr>", page, re.S):
        if name in m.group(0):
            return m.group(0)
    return ""


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
    d = date.today() + timedelta(days=1)
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
        row = _row_of(c.get(f"/admin/all?date={day}").body, "Ion Oricare")
        res.ok("и в журнале визит стоит у вечернего врача",
               "Zi Seara" in row and "Dimineata" not in row,
               f"строка списка: {row[:160]!r}")


def suite_routes(res: Result) -> None:
    """/admin/add и /admin/move проверяют график врача НА СЕРВЕРЕ.

    Нижняя форма /admin/all предлагает любого врача и все получасы клиники,
    а вкладка с журналом живёт с автообновлением — браузеру верить нельзя
    (докстринг admin_move сам называет график врача причиной перепроверки).
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
        aid = _row_of(c.get(f"/admin/all?date={day2}").body,
                      "Mutare Test").split("/admin/status/", 1)[1].split("'")[0]

        def move(to_time: str, to_doc: str) -> str:
            return c.post(f"/admin/move/{aid}", mdate=day2, mtime=to_time,
                          mdoctor=to_doc, back=f"/admin/all?date={day2}").msg

        res.check("перенос утреннему врачу на 15:00 — отказ по его графику",
                  move("15:00", "da"), "outside_doc")
        row = _row_of(c.get(f"/admin/all?date={day2}").body, "Mutare Test")
        res.ok("отбитый визит остался у вечернего врача",
               "Zi Seara" in row and "15:00" in row,
               f"строка списка: {row[:160]!r}")
        res.check("перенос утреннему врачу на его утро — ok",
                  move("11:00", "da"), "ok_move")
        # переносу хватает 30 минут в окне врача — та же поблажка, что у
        # окна клиники (визит уже существует, записан внахлёст — не наказываем)
        res.check("перенос на 12:30 (30' до конца окна) — ok",
                  move("12:30", "da"), "ok_move")

        # --- постфактум: прошлые ДНИ принимаются, часы врача — правило ---
        res.check("вчера в часы врача — ok_past, как раньше",
                  _add(c, _d(-1), "10:00", "da", "Ieri Ora", "022600600"),
                  "ok_past")
        res.check("вчера ВНЕ часов врача — отказ и задним числом",
                  _add(c, _d(-1), "15:00", "da", "Ieri Rau", "022600700"),
                  "outside_doc")


def suite_drop(res: Result) -> None:
    """Ячейка С ЗАПИСЬЮ — тоже мишень перетаскивания (data-dk/data-h).

    panel.js ищет цель через closest('td[data-h]'): без атрибута на занятой
    ячейке бросок на 10:30 часа, где в 10:00 уже стоит визит, молча умирал —
    хотя комментарий в _grid прямо требует «мишень, ЗАНЯТ час или нет».
    """
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        _add(c, day, "10:00", "d2", "Drop Busy", "022600800")
        for path in (f"/admin/all?date={day}", f"/admin/doctor/d2?date={day}"):
            body = c.get(path).body
            cell = re.search(r"<td data-dk='d2' data-h='10'>(?:(?!</td>).)*"
                             r"Drop Busy", body, re.S)
            res.ok(f"{path}: занятая ячейка несёт data-dk/data-h",
                   bool(cell), "td с визитом 10:00 без drop-атрибутов")
    # обратная сторона: час ВНЕ приёма мишенью не стал
    with Server(clinic="clinic_hours.json") as s2:
        c2 = Client(s2.url).login()
        grid = c2.get(f"/admin/all?date={_d(1)}").body
        res.ok("закрытая ячейка по-прежнему не мишень",
               "<td class='goff'></td>" in grid
               and "goff' data-dk" not in grid,
               "час вне приёма принимает бросок")
