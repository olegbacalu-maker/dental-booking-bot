"""Находки ревью волны 2 (08-15): пациенты и настройки.

Четыре дефекта одного свойства — «зелёный экран врёт молча»:
  * боковой предпросмотр фиши считал отказанные (refuzat) процедуры в сумму и
    в знаменатель прогресса — тогда как сама фиша отказ намеренно исключает
    (класс «не finalizat», чинившийся 08-11 в шести местах; peek был седьмым);
  * очистка даты рождения оставляла протухший birth_year — возраст продолжал
    показываться от удалённой даты, и убрать его было нечем;
  * «Pacient nou» искал дубликат телефона только по ключу manual:{digits} —
    пациент из бота (tg:…) с тем же номером дублировался вопреки обещанию
    формы «nu se dublează» (та же болезнь, что чинилась в /admin/add 08-07);
  * имя сотрудника вставлялось внутрь JS-литерала onsubmit="confirm('…')":
    апостроф в имени рвал строку — форма удаления уходила БЕЗ подтверждения,
    а подобранное имя исполнялось как JS; и клиентская проверка дублей услуг
    ловила только колонку RO — серверный отказ по RU-дублю перерисовывал
    форму и стирал все правки таблицы.
"""
import json
import sqlite3
from datetime import timedelta

from harness import Client, Result, Server, add_appt, clinic_today, new_patient, pid_by_phone

NO_KEY = {"ADMIN_KEY": ""}          # ветка PIN-файла: учётки живут в auth.json


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _new_pid(c: Client, **fields) -> str:
    """Создать пациента через «Pacient nou» (JSON API диалога), вернуть id."""
    return str(new_patient(c, **fields))


def _list_row(c: Client, name: str) -> dict:
    """Строка пациента в списке «Pacienți» (`GET /api/patients`) — та же
    выборка, что уезжает в книгу Excel. До 13.10 здесь читался CSV."""
    rows = json.loads(c.get("/api/patients?q=" + name.replace(" ", "+")).body)["data"]["rows"]
    return next((r for r in rows if r["name"] == name), {})


def suite_peek_plan(res: Result) -> None:
    """Предпросмотр считает план ТЕМ ЖЕ правилом, что фиша: отказ — не деньги
    и не знаменатель. ⚠️ Проверяется текст блока, а не код ответа: peek всегда
    отвечает 200, и на нём код один на оба исхода."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _new_pid(c, name="Peek Plan", phone="069111222")
        api = f"/api/patients/{pid}"
        c.post_json(f"{api}/plan", {"procedure": "Extractie 48", "price": "1000",
                                   "doctor": "Dr. Ana"})
        r = c.post_json(f"{api}/plan", {"procedure": "Obturatie 11", "price": "1000",
                                       "doctor": "Dr. Ana"})
        i1, i2 = [it["id"] for it in json.loads(r.body)["data"]["plan"]["items"]][:2]
        res.check("первая позиция уходит в отказ",
                  c.post_json(f"{api}/plan/{i1}/status", {"to": "refuzat",
                                                         "motiv": "Pacientul refuză; riscurile explicate"}).msg,
                  "ok_refuz")
        c.post_json(f"{api}/plan/{i2}/status", {"to": "in_lucru"})
        c.post_json(f"{api}/plan/{i2}/status", {"to": "finalizat"})

        plan = json.loads(c.get(api).body)["data"]["plan"]
        res.check("фиша: отказ выпал из знаменателя (1/1 finalizate)",
                  (plan["n_track"], plan["counts"].get("finalizat")), (1, 1))
        peek = json.loads(c.get(f"{api}/peek").body)["data"]["html"]
        res.ok("peek: отказ выпал из знаменателя прогресса",
               "1 / 1 finalizate" in peek,
               "peek расходится с фишей — отказ в знаменателе")
        res.ok("peek: отказанная процедура не в сумме плана",
               "1 000 MDL / 1 000 MDL" in peek,
               "peek считает цену отказанной процедуры в «X MDL / Y MDL»")
        # 14.10: «Vezi toate» вела якорем `#docs` — с вкладками (B6) он
        # открывал Rezumat, где списка документов нет
        for i in range(4):
            c.post_file(f"{api}/documents", "file", f"nota{i}.txt", b"x", category="alt")
        peek = json.loads(c.get(f"{api}/peek").body)["data"]["html"]
        res.ok("peek: «Vezi toate» ведёт на вкладку «Documente»",
               f"href='/admin/patient/{pid}?tab=docs'>Vezi toate (4)" in peek, peek[-400:])


def suite_birth_clear(res: Result) -> None:
    """Очищенная дата рождения забирает с собой и возраст — но НЕ трогает год
    пациента, у которого даты не было никогда (год из бота)."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _new_pid(c, name="Data Test", phone="069333444",
                       birth_date="1950-04-02")
        row = _list_row(c, "Data Test")
        res.ok("возраст виден, пока дата есть", row.get("age") is not None,
               f"в списке без возраста: {row!r}")

        # регистратура заметила ошибку и очистила поле даты
        res.check("сохранение с пустой датой проходит",
                  c.post_json(f"/api/patients/{pid}/profile", {"name": "Data Test",
                                                              "phone": "069333444",
                                                              "birth_date": ""}).msg, "ok_card")
        row = _list_row(c, "Data Test")
        res.ok("дата в списке пуста", row and row["birth"] == "",
               f"дата осталась: {row!r}")
        res.ok("возраст ушёл вместе с датой", row and row["age"] is None,
               f"возраст живёт от удалённой даты: {row!r}")

        # пациент «только с годом» (так пишет бот — кнопка года без даты — и
        # так писал журнал до 08-07): пустое поле даты в фише не имеет права
        # стирать его год. Состояние ставится прямо в базу: дверей, которые
        # его создают, в журнале больше нет, а у бота нужен свой сервер.
        add_appt(c, _d(1), "10:00", "An Doar", "069555666")
        an_pid = pid_by_phone(c, "069555666")
        con = sqlite3.connect(str(s.dir / "dental.db"))
        try:
            con.execute("UPDATE patients SET birth_year = 1990, birth_date = NULL "
                        "WHERE id = ?", (an_pid,))
            con.commit()
        finally:
            con.close()
        c.post_json(f"/api/patients/{an_pid}/profile", {"name": "An Doar",
                                                       "phone": "069555666", "birth_date": ""})
        row = _list_row(c, "An Doar")
        res.ok("год из бота переживает сохранение фиши без даты",
               row.get("age") is not None,
               f"пустое поле формы стёрло год: {row!r}")


def suite_new_dup(res: Result) -> None:
    """«Pacient nou» не дублирует фишу, чей телефон совпадает по ЦИФРАМ — даже
    когда ключ пациента не manual:{digits} (пациент из бота, фиша без номера,
    дописанного позже)."""
    with Server() as s:
        c = Client(s.url).login()
        # фиша с ключом НЕ manual:{digits}: заведена без номера (manual:c…),
        # телефон дописан сохранением — ровно как у пациента из tg:…
        pid = _new_pid(c, name="Tg Pacient")
        c.post_json(f"/api/patients/{pid}/profile", {"name": "Tg Pacient", "phone": "069123456"})

        r = c.post_json("/api/patients", {"name": "Dublura", "phone": "069 123 456"})
        res.check("совпадение цифр открывает существующую фишу", r.msg,
                  "dup_pat")
        res.check("и это ТА ЖЕ фиша, а не двойник", json.loads(r.body)["data"]["id"], int(pid))

        # прежний путь (ключ manual:{digits}) продолжает склеивать как раньше
        pid2 = _new_pid(c, name="Manual Unu", phone="069777888")
        r = c.post_json("/api/patients", {"name": "Manual Doi", "phone": "069777888"})
        res.check("manual-совпадение склеивает как раньше", r.msg, "dup_pat")
        res.check("к той же manual-фише", json.loads(r.body)["data"]["id"], int(pid2))


def suite_settings_ui(res: Result) -> None:
    """Сотрудник с апострофом в имени заводится, а сервер режет RU-дубли и
    перекрёстные ro/ru-дубли услуг."""
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        res.check("сотрудник с апострофом заводится",
                  boss.post_json("/api/settings/users", {"uid": "ob", "name": "O'Brien",
                                                        "role": "receptie", "pin": "7777"}).msg, "ok_user")
        # Старые страницы учёток и услуг (их JS: confirm с именем, collectServices)
        # сняты 12.10 — экраны рисует React. Дубли подписей React-экран не
        # повторяет: их режет только сервер (_val_services), а правки при отказе
        # живут в состоянии экрана. Пустой RU наследует RO.
        res.check("сервер режет RU-дубль",
                  boss.post_json("/api/settings/services", {"services": [
                      {"id": "", "ro": "Alfa", "ru": "Ceva"},
                      {"id": "", "ro": "Beta", "ru": "ceva"}]}).msg, "bad_set")
        res.check("сервер режет перекрёстный ro/ru-дубль",
                  boss.post_json("/api/settings/services", {"services": [
                      {"id": "", "ro": "Gamma", "ru": ""},          # пустой RU ← RO
                      {"id": "", "ro": "Delta", "ru": "gamma"}]}).msg, "bad_set")
