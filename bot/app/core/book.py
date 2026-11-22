"""Поставить визит фише, которая уже известна по номеру.

Одно правило для всех, кто ставит визит не из окна записи журнала: перенос события Google в выбранную
фишу (`schedule/gcal`) и импорт пациентов с записями (`patients/pimport`). Лежит в `core`, потому что
зовут его два модуля, а модуль соседа не импортирует. Окно журнала принимает имя и телефон, а не номер фиши, поэтому его
правило — `routes._book_appt`; порядок проверок здесь тот же, и новая проверка там обязана появиться и
здесь. Третьей копии быть не должно: визит фише по номеру ставит только `book_visit`
(`test_structure`, писатели `db.add_visit_for_patient`).

Ответ — код из `MSG_BANNER` (слова печатает показывающий) и номер записи. Удача бывает с
предупреждением: `ok_past`, `ok_past_done`, `room_busy` — запись создана."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from .. import db
from .. import engine as eng
from . import gimport

OK_CODES = frozenset({"ok", "ok_past", "ok_past_done", "room_busy"})


@dataclass(frozen=True)
class Booked:
    code: str
    appt_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.appt_id is not None


def default_service(sid: str = "") -> str:
    """Процедура визита без своей: выбор человека, иначе консультация, иначе первая не срочная услуга
    агенды. Срочная («Durere acută») умолчанием не годится: у клиники она часто первая в списке, а визит
    из старой программы или из календаря — не острая боль."""
    if sid and eng.in_agenda(sid):
        return sid
    first = [(x, s["ro"]) for x, s in eng.SERVICES.items() if eng.in_agenda(x)]
    consult = [x for x, name in first if gimport.fold(name).startswith("consult") or x == "consult"]
    calm = [x for x, _n in first if not eng.SERVICES[x].get("urgent")]
    return (consult or calm or [x for x, _n in first] or [""])[0]


def wall(d: date, t: time) -> datetime:
    """Стенное время клиники: в базу момент уходит в UTC сам (`db._iso`), перевод часов учтён поясом."""
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=eng.TZ)


def history(start: datetime | None, done: bool) -> bool:
    """Визит прошедшего ДНЯ, который ложится сразу «finalizată»: перенос истории из файла."""
    return done and start is not None and eng.is_past_day(start.date())


def refusal(doctor_id: str, start: datetime | None, service_id: str,
            minutes: int | None = None, room: str = "", done: bool = False) -> tuple[str, int]:
    """Проверки без базы, в порядке окна записи: (код отказа или "", длительность визита).

    `minutes` None — длительность услуги; число — выбранная длительность, правило `eng.dur_ok`.
    Часы врача проверяются только для будущего, часы клиники и сетка 5 минут — всегда
    (`eng.place_refusal`). Кроме истории (`history`: прошедший день и `done`): визит уже был,
    график клиники и состав врачей с тех пор могли смениться — часы клиники и «врач выключен» не
    проверяются; сетка, услуга, длительность, кабинет и занятость — как у всех."""
    doctor, svc = eng.DOCTORS.get(doctor_id), eng.SERVICES.get(service_id)
    if start is None or not doctor or not svc:
        return "bad", 0
    if not eng.in_agenda(service_id):
        return "svc_not_agenda", 0
    dur = eng.svc_duration(service_id)
    if minutes is not None:
        if not eng.dur_ok(minutes):
            return "bad_dur", 0
        dur = minutes
    if history(start, done):
        if not eng.start_ok(start):
            return "bad_time", 0
    elif code := eng.place_refusal(doctor_id, start, dur):
        return code, 0
    if room and not eng.room_allowed(doctor_id, room):
        return "bad_room", 0
    return "", dur


async def probe(pid: int | None, doctor_id: str, start: datetime | None, service_id: str, *,
                minutes: int | None = None, room: str = "", done: bool = False) -> str:
    """Тот же ответ, что дал бы `book_visit`, но на сухую: без замка и без записи (предпросмотр).

    Правду говорит `book_visit` в момент записи — между пробой и записью час могут занять.
    `ok_past_done` проба не различает: это `ok_past` с отметкой статуса."""
    code, dur = refusal(doctor_id, start, service_id, minutes, room, done)
    if code:
        return code
    plan = eng.room_plan(doctor_id)
    got = await db.slot_probe(doctor_id, eng.DOCTORS[doctor_id], start, dur, plan,
                              room or None, pid=pid)
    if got["dup"]:
        return "dup"
    if not got["free"]:
        return "conflict"
    if eng.is_past_day(start.date()):
        return "ok_past"
    return "room_busy" if got["room_busy"] else "ok"


async def book_visit(pid: int, doctor_id: str, start: datetime | None, service_id: str, *,
                     minutes: int | None = None, room: str = "", done: bool = False,
                     comment: str = "") -> Booked:
    """Визит фише `pid` (фиша обязана существовать — её находит или заводит зовущий).

    `start` — стенное время клиники с поясом (`wall`); `minutes` — длительность, выбранная не
    услугой (признак `duration_set`: смена процедуры её не перебьёт); `room` — кабинет, пусто —
    первый свободный; `done` — визит на прошедший ДЕНЬ ложится сразу «finalizată», как галочка «Vizita a avut loc»
    окна записи (сегодняшний остаётся «programată»: его закрывают из карточки); `comment` —
    комментарий записи. Занятость врача, кабинета и пациента решается под `_slot_lock`
    (`db._book`). Согласие пациента на SMS не трогается: галочку окна записи пишет зовущий после
    удачи (`schedule/routes._apply_sms`), импорт её не шлёт."""
    code, dur = refusal(doctor_id, start, service_id, minutes, room, done)
    if code:
        return Booked(code)
    plan = eng.room_plan(doctor_id)
    r = await db.add_visit_for_patient(pid, eng.SERVICES[service_id]["ro"], eng.DOCTORS[doctor_id],
                                       start, doctor_id=doctor_id, service_id=service_id,
                                       duration_min=dur, duration_set=minutes is not None,
                                       rooms=plan, room=room or None)
    if not isinstance(r, int):
        return Booked("dup" if r == "dup" else "conflict")
    if comment:
        await db.set_comment(r, comment)
    if eng.is_past_day(start.date()):
        if done and not await db.set_status(r, "done"):
            return Booked("ok_past_done", r)
        return Booked("ok_past", r)
    return Booked("room_busy" if await db.appt_room_busy(r, plan) else "ok", r)
