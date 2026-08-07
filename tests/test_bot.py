"""Бот записи: сценарий до конца, отказы, «мои записи», отмена.

Бот и журнал делят один путь бронирования, поэтому здесь проверяется не диалог
ради диалога, а что оба входа отвечают одинаково на одну и ту же занятость.
"""
import re
from datetime import date, timedelta

from harness import Bot, Client, Result, Server


def _book(bot: Bot, day: str, hhmm: str, name: str, phone: str,
          service: str = "consult", doctor: str = "d2") -> str:
    """Проходит диалог до подтверждения. Возвращает текст последнего ответа."""
    bot.say("/start")
    bot.say("lang:ro")
    bot.say("book")
    bot.say(f"svc:{service}")
    bot.say(f"doc:{doctor}")
    bot.say(f"day:{day}")
    bot.say(f"time:{day}T{hhmm}")
    bot.say(name)
    bot.say("skip_year")
    bot.say(phone)
    texts, _ = bot.say("confirm")
    return texts


def suite(res: Result) -> None:
    with Server() as s:
        c = Client(s.url)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # --- меню и справочники ---
        bot = Bot(c, "t-menu")
        bot.say("/start")
        _, buttons = bot.say("lang:ro")
        res.ok("меню бота отвечает", "book" in buttons, f"кнопки: {buttons}")
        _, services = bot.say("book")
        res.ok("услуга без активных врачей не предлагается",
               "svc:orphan" not in services, f"услуги: {services}")
        res.ok("обычная услуга предлагается", "svc:consult" in services,
               f"услуги: {services}")
        _, doctors = bot.say("svc:consult")
        res.ok("архивный врач не предлагается", "doc:d1" not in doctors,
               f"врачи: {doctors}")

        # --- часы: свободные старты вообще есть ---
        bot.say("doc:d2")
        _, days = bot.say(f"day:{tomorrow}")
        slots = [b for b in days if b.startswith("time:")]
        res.ok("бот предлагает свободные часы", len(slots) > 0, f"кнопок: {days}")

        # --- запись до конца ---
        text = _book(Bot(c, "t-book"), tomorrow, "10:00", "Maria Bot", "069111222")
        res.ok("бот записал пациента", "10:00" in text, f"ответ: {text[:160]}")

        # --- тот же час у того же врача занят для ДРУГОГО пациента ---
        text = _book(Bot(c, "t-taken"), tomorrow, "10:00", "Alt Pacient", "069333444")
        res.ok("занятый час боту не отдаётся", "10:00" not in text,
               f"ответ: {text[:160]}")
        # отказ не должен заводить пациента-сироту: upsert шёл до проверки
        # занятости, и «час занят» оставлял карточку без визитов (08-07)
        adm = Client(s.url).login()
        res.ok("отказ бота НЕ завёл карточку-сироту",
               not re.findall(r"/admin/patient/(\d+)",
                              adm.get("/admin/search?q=069333444").body),
               "пациент без визита появился в списке")

        # --- свой же час: сообщение должно быть про ПАЦИЕНТА, не про врача ---
        # ⚠️ до 1.11.1 здесь врали: «интервалul este ocupat»
        own = Bot(c, "t-own")
        _book(own, tomorrow, "12:00", "Dubla Persoana", "069555666")
        text = _book(own, tomorrow, "12:00", "Dubla Persoana", "069555666",
                     doctor="d3")
        res.ok("свой занятый час назван своим",
               "deja o programare" in text, f"ответ: {text[:200]}")

        # --- мои записи и отмена ---
        mine = Bot(c, "t-mine")
        _book(mine, tomorrow, "13:00", "Anulare Test", "069777888")
        texts, buttons = mine.say("my")
        res.ok("«мои записи» показывают визит", "13:00" in texts,
               f"ответ: {texts[:160]}")
        cancel = [b for b in buttons if b.startswith("cancel:")]
        res.ok("есть кнопка отмены", len(cancel) > 0, f"кнопки: {buttons}")
        if cancel:
            mine.say(cancel[0])
            c2 = Client(s.url).login()
            free = c2.post("/admin/add", adate=tomorrow, atime="13:00",
                           adoctor="d2", aservice="consult", aname="Dupa Anulare",
                           aphone="022444555", back="/admin/all").msg
            res.check("после отмены час освободился", free, "ok")

        # --- срочная запись ---
        urgent = Bot(c, "t-urgent")
        urgent.say("/start")
        urgent.say("lang:ro")
        urgent.say("book")
        texts, buttons = urgent.say("svc:pain")
        res.ok("срочная услуга ведёт к ближайшим окнам",
               len(buttons) > 0, f"ответ: {texts[:160]}")
