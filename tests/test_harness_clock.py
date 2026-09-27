"""Поддельные часы харнесса (`harness.Clock`): сами часы под проверкой.

Часы, которые не встали, не падают: сервер живёт по настоящему времени, и
набор, перенесённый «в воскресенье», проверяет будний день — зелёным. Поэтому
здесь у каждого механизма есть пара: тот же вопрос на настоящих часах (или на
сломанных) обязан получить другой ответ. Иначе проверка зеленела бы и тогда,
когда часы стоят.

⭐ Часы сервера спрашиваются ПОВЕДЕНИЕМ, а не его печатью: канва панели без
даты открывает «сегодня» сервера и подсвечивает его текущий час. Отметка
`[fakeclock]` в логе говорит только, что модуль загрузился, — ей верит один
сторож старта (п. 4).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import harness  # noqa: E402
from harness import (RUN_TMP, TZ, Client, Clock, Result, Server,  # noqa: E402
                     _rmtree_settled, clinic_now, clinic_today)


def _across_dst(now: datetime) -> datetime:
    """Ближайшая среда с ДРУГИМ смещением от UTC, чем сейчас, в часы работы.

    Другое смещение = между «сейчас» и целью переход на летнее или зимнее
    время: ровно там `now(tz) + сдвиг` ошибается на час, и проба, взятая без
    перехода, эту ошибку не отличила бы. Среда — рабочий день фикстуры
    прогона: у канвы есть часы, а значит, есть и «текущий час».
    ⚠️ Час цели отстоит от настоящего хотя бы на три: сервер, который вовсе
    не сдвинулся, иначе совпал бы с целью по часу случайно (так и было на
    пробе 12:30, взятой в 12:50, — проверка часа зеленела на неподвижном
    сервере, красной осталась одна дата).
    ⚠️ Ищется в пределах года: отменят переход времени — вернётся первая же
    среда, и о пустой пробе скажет её собственная проверка, а не зависший
    прогон."""
    hour = 9 if now.hour >= 12 else 16
    days = (now.date() + timedelta(days=i) for i in range(1, 400))
    wednesdays = [datetime.combine(d, time(hour, 30), tzinfo=TZ)
                  for d in days if d.weekday() == 2]
    return next((at for at in wednesdays if at.utcoffset() != now.utcoffset()),
                wednesdays[0])


def _server_now(s: Server) -> tuple[str, list]:
    """«Сегодня» сервера и его текущий час — так, как их видит панель."""
    data = json.loads(Client(s.url).login().get("/api/schedule/canvas").body)["data"]
    return data["date"], [h["h"] for h in data["hours"] if h["now"]]


def suite_clock(res: Result) -> None:
    """Прогон и сервер в назначенном времени — пары «часы / без часов»."""
    real = datetime.now(TZ)
    at = _across_dst(real)
    later = at + timedelta(days=2)

    with Clock(at) as clock:
        # 1. Прогон: clinic_today()/clinic_now() идут по часам блока.
        res.check("прогон: clinic_today() — день часов", clinic_today(), at.date())
        got = clinic_now()
        res.check("прогон: час через переход времени — назначенный",
                  (got.hour, got.utcoffset()), (at.hour, at.utcoffset()))
        # Пара к проверке выше: формула «пояс, потом сдвиг» на ЭТОЙ пробе
        # обязана ошибиться — иначе проба перехода не содержит, и проверка
        # часа зеленела бы на любой из двух формул.
        naive = datetime.now(TZ) + clock._shift
        res.ok("проба различает формулы: `now(tz) + сдвиг` ошибся бы на час",
               naive.hour != at.hour, f"наивная формула дала {naive:%H:%M} — перехода "
               f"между {real:%d.%m} и {at:%d.%m} нет, проба пустая")
        with Clock(at + timedelta(days=1)):
            res.check("вложенные часы: действует внутренний", clinic_today(),
                      at.date() + timedelta(days=1))
        res.check("после внутреннего — снова внешний", clinic_today(), at.date())

        # 2. Сервер, стартовавший в блоке, живёт по тем же часам — и
        #    переставляется вместе с прогоном, не погаснув.
        with Server() as s:
            day, hour = _server_now(s)
            res.check("сервер: «сегодня» — день часов", day, at.date().isoformat())
            res.check("сервер: текущий час через переход времени — назначенный",
                      hour, [at.hour])
            clock.set(later)
            res.check("часы переставляются на живом сервере", _server_now(s)[0],
                      later.date().isoformat())
            res.check("и у прогона вместе с ним", clinic_today(), later.date())
            # Чтение, попавшее на замену файла, видит пустое: сервер обязан
            # остаться в назначенном дне, а не вернуться на один запрос в
            # настоящий — такой скачок не виден ни в логе, ни в ответе.
            clock.file.write_text("", encoding="utf-8")
            res.check("пустой файл часов — сервер держит прежний сдвиг",
                      _server_now(s)[0], later.date().isoformat())
            clock.set(later)

    # 3. Пары к пп. 1–2: тот же вопрос без часов даёт настоящий день — даже
    #    когда в окружении прогона осталась ручная подмена (до 27.09 её
    #    ставили на сам прогон: PYTHONPATH + FAKECLOCK_FILE). Сервер
    #    унаследовал бы её молча, а clinic_today() — нет.
    res.check("вне блока прогон — на настоящих часах", clinic_today(),
              datetime.now(TZ).date())
    stale = RUN_TMP / "stale-clock.txt"
    stale.write_text(str(1000 * 86400), encoding="utf-8")
    saved = {k: os.environ.get(k) for k in ("PYTHONPATH", "FAKECLOCK_FILE")}
    os.environ.update(PYTHONPATH=str(harness.FAKECLOCK), FAKECLOCK_FILE=str(stale))
    try:
        with Server() as s:
            lo = clinic_today().isoformat()
            day, _ = _server_now(s)
            hi = clinic_today().isoformat()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        stale.unlink()
    res.ok("сервер без часов — настоящее «сегодня», ручная подмена прогона "
           "не наследуется", day in (lo, hi), f"сервер назвал {day}, настоящее — {lo}")

    # 4. Часы, которые не встали, останавливают старт, а не молчат: модуль
    #    часов не нашёлся — `site` это глотает, и сервер пошёл бы на настоящих.
    lab = RUN_TMP / "clock-lab"
    lab.mkdir()
    real_site, harness.FAKECLOCK = harness.FAKECLOCK, lab
    why = ""
    try:
        with Clock(at), Server():
            pass
    except RuntimeError as e:
        why = str(e)
    finally:
        harness.FAKECLOCK = real_site
        _rmtree_settled(lab)
    res.ok("сервер мимо часов не стартует — отказ с причиной",
           "мимо поддельных часов" in why, f"старт ответил {why[:200]!r}")

    # 5. Часы, не заведённые `with`, — отказ ДО старта: файла сдвига ещё нет,
    #    и песочница, которую завёл конструктор сервера, не остаётся лежать.
    idle = Server(clock=Clock(at))
    why = ""
    try:
        with idle:
            pass
    except RuntimeError as e:
        why = str(e)
    res.ok("часы без `with` — отказ до старта, песочница не остаётся",
           "не заведены" in why and not idle.dir.exists(),
           f"старт ответил {why[:120]!r}, песочница "
           f"{'осталась' if idle.dir.exists() else 'снесена'}")
