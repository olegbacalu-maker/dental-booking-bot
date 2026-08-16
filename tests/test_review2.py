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
from datetime import date, timedelta

from harness import Client, Result, Server

NO_KEY = {"ADMIN_KEY": ""}          # ветка PIN-файла: учётки живут в auth.json


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _new_pid(c: Client, **fields) -> str:
    """Создать пациента через «Pacient nou», вернуть id из редиректа."""
    r = c.post("/admin/patients/new", **fields)
    return r.location.split("/admin/patient/", 1)[1].split("?")[0]


def _csv_row(c: Client, name: str) -> list:
    for line in c.get("/admin/patients.csv").body.splitlines():
        if name in line:
            return line.split(";")
    return []


def suite_peek_plan(res: Result) -> None:
    """Предпросмотр считает план ТЕМ ЖЕ правилом, что фиша: отказ — не деньги
    и не знаменатель. ⚠️ Проверяется текст блока, а не код ответа: peek всегда
    отвечает 200, и на нём код один на оба исхода."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _new_pid(c, name="Peek Plan", phone="069111222")
        base = f"/admin/patient/{pid}"
        c.post(f"{base}/plan", procedure="Extractie 48", price="1000",
               doctor="Dr. Ana")
        c.post(f"{base}/plan", procedure="Obturatie 11", price="1000",
               doctor="Dr. Ana")
        page = c.get(base).body
        iids = []
        for part in page.split("/plan/")[1:]:
            iid = part.split("/", 1)[0]
            if iid.isdigit() and iid not in iids:
                iids.append(iid)
        i1, i2 = iids[:2]
        res.check("первая позиция уходит в отказ",
                  c.post(f"{base}/plan/{i1}/status", to="refuzat",
                         motiv="Pacientul refuză; riscurile explicate").msg,
                  "ok_refuz")
        c.post(f"{base}/plan/{i2}/status", to="in_lucru")
        c.post(f"{base}/plan/{i2}/status", to="finalizat")

        fisha = c.get(base).body
        res.ok("фиша: отказ выпал из знаменателя", "1/1 finalizate" in fisha,
               "в фише прогресс считает отказ")
        peek = c.get(f"{base}/peek").body
        res.ok("peek: отказ выпал из знаменателя прогресса",
               "1 / 1 finalizate" in peek,
               "peek расходится с фишей — отказ в знаменателе")
        res.ok("peek: отказанная процедура не в сумме плана",
               "1 000 MDL / 1 000 MDL" in peek,
               "peek считает цену отказанной процедуры в «X MDL / Y MDL»")


def suite_birth_clear(res: Result) -> None:
    """Очищенная дата рождения забирает с собой и возраст — но НЕ трогает год
    пациента, у которого даты не было никогда (год из бота)."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _new_pid(c, name="Data Test", phone="069333444",
                       birth_date="1950-04-02")
        row = _csv_row(c, "Data Test")
        res.ok("возраст виден, пока дата есть", row and row[4].strip() != "",
               f"CSV без возраста: {row!r}")

        # регистратура заметила ошибку и очистила поле даты
        res.check("сохранение с пустой датой проходит",
                  c.post(f"/admin/patient/{pid}/save", name="Data Test",
                         phone="069333444", birth_date="").msg, "ok_card")
        row = _csv_row(c, "Data Test")
        res.ok("дата в CSV пуста", row and row[3].strip() == "",
               f"дата осталась: {row!r}")
        res.ok("возраст ушёл вместе с датой", row and row[4].strip() == "",
               f"возраст живёт от удалённой даты: {row!r}")

        # пациент «только с годом» (запись из журнала со старой вкладки):
        # пустое поле даты в фише не имеет права стирать его год
        c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d2",
               aservice="consult", aname="An Doar", aphone="069555666",
               ayear="1990", back="/admin/all")
        an_pid = c.get("/admin/search?q=069555666").body.split(
            "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]
        c.post(f"/admin/patient/{an_pid}/save", name="An Doar",
               phone="069555666", birth_date="")
        row = _csv_row(c, "An Doar")
        res.ok("год из бота переживает сохранение фиши без даты",
               row and row[4].strip() != "",
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
        c.post(f"/admin/patient/{pid}/save", name="Tg Pacient",
               phone="069123456")

        r = c.post("/admin/patients/new", name="Dublura", phone="069 123 456")
        res.check("совпадение цифр открывает существующую фишу", r.msg,
                  "dup_pat")
        res.ok("и это ТА ЖЕ фиша, а не двойник",
               f"/admin/patient/{pid}?" in r.location,
               f"открыта другая фиша: {r.location!r}")

        # прежний путь (ключ manual:{digits}) продолжает склеивать как раньше
        pid2 = _new_pid(c, name="Manual Unu", phone="069777888")
        r = c.post("/admin/patients/new", name="Manual Doi", phone="069777888")
        res.check("manual-совпадение склеивает как раньше", r.msg, "dup_pat")
        res.ok("к той же manual-фише", f"/admin/patient/{pid2}?" in r.location,
               f"открыта другая фиша: {r.location!r}")


def suite_settings_ui(res: Result) -> None:
    """Имя сотрудника не попадает в JS-код подтверждения удаления, а
    клиентская проверка дублей услуг знает те же правила, что сервер."""
    with Server(env=NO_KEY) as s:
        boss = Client(s.url)
        boss.post("/admin/setup", pin1="1111", pin2="1111")
        res.check("сотрудник с апострофом заводится",
                  boss.post("/admin/users/save", uid="ob", name="O'Brien",
                            role="receptie", pin="7777").msg, "ok_user")
        body = boss.get("/admin/settings/security").body
        # ⚠️ html.escape НЕ спасает внутри onsubmit: браузер декодирует
        # &#x27; обратно в апостроф ДО компиляции обработчика, литерал рвётся,
        # и форма удаления уходит БЕЗ confirm
        res.ok("имя не вставляется в JS-литерал confirm",
               "confirm('Ștergeți contul" not in body,
               "имя внутри confirm('…') — апостроф ломает подтверждение")
        res.ok("подтверждение живо и несёт имя данными, не кодом",
               "confirm(this.dataset.msg)" in body
               and "Ștergeți contul O&#x27;Brien?" in body,
               "нет confirm(this.dataset.msg) с именем в data-атрибуте")

        # услуги: клиентская проверка обязана резать то же, что сервер
        # (_val_services) — RU-дубли и перекрёстные ro/ru, включая «пустой RU
        # наследует RO»; иначе payload проходит браузер, сервер отвечает
        # bad_set и перерисовка формы стирает все правки таблицы
        svc_page = boss.get("/admin/settings/services").body
        script = svc_page.split("function collectServices", 1)[1]
        res.ok("клиентская проверка дублей знает колонку RU",
               "seen[ru]" in script and "seen[ro]" in script,
               "collectServices дедуплицирует только RO")
        # сервер (правила, которые клиент зеркалит) — на месте
        payload = json.dumps({"services": [
            {"id": "", "ro": "Alfa", "ru": "Ceva"},
            {"id": "", "ro": "Beta", "ru": "ceva"},
        ]})
        res.check("сервер режет RU-дубль",
                  boss.post("/admin/settings/save", part="services",
                            payload=payload).msg, "bad_set")
        payload = json.dumps({"services": [
            {"id": "", "ro": "Gamma", "ru": ""},          # пустой RU ← RO
            {"id": "", "ro": "Delta", "ru": "gamma"},
        ]})
        res.check("сервер режет перекрёстный ro/ru-дубль",
                  boss.post("/admin/settings/save", part="services",
                            payload=payload).msg, "bad_set")
