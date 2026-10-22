"""Дневник визита («Consultație»): запись приёма, привязка плана, закон 195.

Экран — React (`/admin/visit/{aid}`, с 13.10 без старой страницы); здесь то,
что он получает и что записывает, — через `GET/POST /api/visits/{aid}`.

Запись живёт 1:1 с визитом (visit_records) и остаётся клинической частью фиши:
обезличивание её НЕ трогает, выгрузка пациента её содержит, стирание считает
её лечением. Здесь же контраст с карточкой: из формы консультации позиция
плана финализируется НАПРЯМУЮ из Planificat (дневник фиксирует факт), хотя в
карточке это же ребро запрещено (_PLAN_EDGES).
"""
import io
import json
import re
import zipfile
from datetime import date, timedelta

from harness import (Client, Result, Server, appt_id, clinic_today, day_model, new_patient,
                     pid_by_phone)


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _pid(c: Client, phone: str) -> str:
    return str(pid_by_phone(c, phone))


def _aid(c: Client, day: str) -> str:
    """id первого по времени визита дня — из «Lista zilei» модели дня."""
    return str(appt_id(c, day))


def _visit(c: Client, aid) -> dict:
    """Страница визита данными (`GET /api/visits/{aid}`)."""
    return json.loads(c.get(f"/api/visits/{aid}").body)["data"]


def _card(c: Client, pid) -> dict:
    """Фиша данными (`GET /api/patients/{pid}`)."""
    return json.loads(c.get(f"/api/patients/{pid}").body)["data"]


def _plan_doctors(c: Client, pid, proc: str) -> tuple:
    """Врач позиции плана везде, где его читают: фиша (и кого планировали),
    лист 043/e, читаемая копия по 195-му, машинная копия (doctor, visit_doctor).
    Ячейка — по строке таблицы с этой процедурой: имя врача визита стоит на
    листе и в подписи дневника, и простое «есть на странице» ничего бы не
    сказало."""
    it = next(x for x in _card(c, pid)["plan"]["items"] if x["procedure"] == proc)
    row = re.compile(rf"<tr><td>[^<]*</td><td>{re.escape(proc)}</td><td>([^<]*)</td>")

    def cell(page: str):
        m = row.search(page)
        return m.group(1) if m else None
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
    raw = next(x for x in json.loads(z.read("date-pacient.json").decode("utf-8"))["plan_tratament"]
               if x["procedure"] == proc)
    return (it["doctor"], it["planned_doctor"],
            cell(c.get(f"/admin/patient/{pid}/fisa043").body),
            cell(z.read("fisa-pacient.html").decode("utf-8")),
            (raw["doctor"], raw["visit_doctor"]))


def suite(res: Result) -> None:
    """Базовый цикл: страница, сохранение, правка, видимость, охрана входа."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": _d(1), "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Consult Test", "phone": "022111222"})
        pid = _pid(c, "022111222")
        aid = _aid(c, _d(1))

        r = c.get(f"/admin/visit/{aid}")
        res.ok("страница консультации открывается — экран дневника",
               r.status == 200 and 'data-screen="visit"' in r.body, f"код {r.status}")
        v = _visit(c, aid)
        res.ok("графы и шаблоны-заготовки на месте",
               [f["id"] for f in v["fields"]][:1] == ["acuze"]
               and "Obturație" in [t["label"] for t in v["templates"]], "нет шаблонов")

        res.check("пустая консультация не сохраняется",
                  c.post_json(f"/api/visits/{aid}", {"acuze": "", "diagnostic": ""}).msg,
                  "bad_visit")

        r = c.post_json(f"/api/visits/{aid}", {"acuze": "Durere la rece",
                                              "diagnostic": "Pulpită acută, dintele 26",
                                              "tratament": "Deschiderea camerei pulpare"})
        res.check("консультация сохраняется", r.msg, "ok_visit")

        rec = _visit(c, aid)["record"]
        res.check("текст виден после сохранения",
                  (rec["acuze"], rec["diagnostic"]), ("Durere la rece", "Pulpită acută, dintele 26"))
        res.ok("автор и время записи видны", rec["author"] and rec["created"],
               f"нет строки авторства: {rec}")

        # ⚠️ проверять msg, а не 303: отказ и успех отвечают одинаковым кодом
        r = c.post_json(f"/api/visits/{aid}", {"acuze": "Durere la rece",
                                              "diagnostic": "Pulpită acută, dintele 26",
                                              "tratament": "Obturație de canal definitivă"})
        res.check("правка сохраняется", r.msg, "ok_visit")
        rec = _visit(c, aid)["record"]
        res.ok("правка видна и отмечена",
               rec["tratament"] == "Obturație de canal definitivă" and rec["updated"] != "",
               f"updated_at не показан: {rec}")

        card = _card(c, pid)
        hist = card["visits"]["history"]
        res.ok("диагноз виден в истории визитов фиши",
               any("Pulpită acută" in v["diag"] for v in hist), f"таймлайн без дневника: {hist}")
        res.ok("ссылка на консультацию из фиши",
               any(v["url"].startswith(f"/admin/visit/{aid}?") for v in hist), "нет ссылки из таймлайна")
        res.ok("сохранение оставило след в летописи",
               any(a["text"].startswith("Consultație") for a in card["activity"]["items"]),
               "летопись молчит")

        # пометку рисует экран по признаку строки «Lista zilei» (`rec`)
        res.ok("маркер дневника в списке дня",
               any(r["rec"] for r in day_model(c, _d(1))["list"]),
               "журнал не показывает, что визит записан")
        # адрес консультации диалог строит сам из номера (vitest DashScreen)
        res.check("флаг дневника уехал в карточку диалога",
                  day_model(c, _d(1))["cards"].get(str(aid), {}).get("rec"), True)

        anon = Client(s.url)
        res.ok("без входа страница не отдаётся",
               anon.get(f"/admin/visit/{aid}").status == 303,
               "медзапись видна без входа")
        res.check("без входа запись не пишется (JSON API — 401)",
                  anon.post_json(f"/api/visits/{aid}", {"diagnostic": "x"}).status, 401)
        res.check("анонимный POST ничего не изменил",
                  _visit(c, aid)["record"]["diagnostic"], "Pulpită acută, dintele 26")

        res.ok("несуществующий визит уводит в журнал",
               c.get("/admin/visit/999999").status == 303,
               "должен быть редирект, не ошибка")


def suite_plan(res: Result) -> None:
    """Привязка позиций плана к визиту и запрет записи отменённым визитам."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": _d(1), "time": "10:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Plan Vizita", "phone": "022333444"})
        pid = _pid(c, "022333444")
        aid = _aid(c, _d(1))

        # запланирована ДРУГОМУ врачу, чем ведёт визит (d2 — Dr. Activ Doi)
        c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Obturație 26", "tooth": "26",
                                                 "price": "500", "doctor": "Dr. Activ Trei"})
        r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Detartraj", "price": "300"})
        items = json.loads(r.body)["data"]["plan"]["items"]
        res.check("обе позиции на месте", len(items), 2)
        iid1 = next(it["id"] for it in items if it["procedure"] == "Obturație 26")

        opened = _visit(c, aid)["plan"]["open"]
        res.ok("нефинальные позиции предлагаются к отметке",
               iid1 in [x["id"] for x in opened] and any("Detartraj" in x["text"] for x in opened),
               "плана нет в форме консультации")

        r = c.post_json(f"/api/visits/{aid}", {"tratament": "Obturație aplicată", "done": [iid1]})
        res.check("сохранение с отметкой позиции", r.msg, "ok_visit")

        # контраст с карточкой: там Planificat→Finalizat запрещён (_PLAN_EDGES),
        # из консультации — разрешён намеренно: дневник фиксирует факт
        card = _card(c, pid)
        res.check("позиция финализирована из консультации",
                  {it["id"]: it["status"] for it in card["plan"]["items"]}[iid1], "finalizat")
        res.check("долг посчитан по финализированному", card["finance"]["debt"], 500)

        plan = _visit(c, aid)["plan"]
        res.ok("привязка видна на странице визита",
               any("Obturație 26" in x["text"] for x in plan["linked"]),
               "линка позиции к визиту нет")
        res.ok("вторая позиция осталась к отметке",
               any("Detartraj" in x["text"] for x in plan["open"]),
               "непривязанное исчезло из формы")

        # ⚠️ 22.10 (пункт 3 доработок Олега): у выполненной на визите врачом
        # стоит ВРАЧ ВИЗИТА — до 2.0.4 фиша и 043/e печатали запланированного,
        # и в медзаписи значился не тот, кто лечил
        doi, trei = "Dr. Activ Doi", "Dr. Activ Trei"
        res.check("выполнена на визите — врач визита в фише, 043/e и выгрузке; "
                  "запланированный цел",
                  _plan_doctors(c, pid, "Obturație 26"),
                  (doi, trei, doi, doi, (trei, doi)))

        # Redeschide в фише = «на самом деле не сделано» → привязка снимается
        res.check("Redeschide позиции",
                  c.post_json(f"/api/patients/{pid}/plan/{iid1}/status", {"to": "in_lucru"}).msg, "")
        plan = _visit(c, aid)["plan"]
        res.ok("привязка снята вместе с done_at",
               plan["linked"] == [] and iid1 in [x["id"] for x in plan["open"]],
               "переоткрытая позиция осталась «выполненной на визите»")
        res.check("Redeschide — снова запланированный врач везде",
                  _plan_doctors(c, pid, "Obturație 26"),
                  (trei, trei, trei, trei, (trei, None)))
        # кнопка плана визита не знает: закрытая ею — у запланированного
        res.check("закрыта кнопкой плана",
                  c.post_json(f"/api/patients/{pid}/plan/{iid1}/status", {"to": "finalizat"}).msg, "")
        res.check("закрыта кнопкой — запланированный врач везде",
                  _plan_doctors(c, pid, "Obturație 26"),
                  (trei, trei, trei, trei, (trei, None)))

        # отменённый визит консультацию не принимает
        c.post_json("/api/schedule/appointments", {"date": _d(2), "time": "11:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Plan Vizita", "phone": "022333444"})
        aid2 = _aid(c, _d(2))
        c.post_json(f"/api/schedule/appointments/{aid2}/status", {"to": "cancelled"})
        res.check("отменённому визиту запись не пишется",
                  c.post_json(f"/api/visits/{aid2}", {"diagnostic": "x"}).msg, "bad_vst")
        v2 = _visit(c, aid2)
        res.ok("страница отменённого визита без формы",
               v2["editable"] is False and "nu se completează" in v2["note"],
               "форма отдаётся отменённому визиту")


def suite_195(res: Result) -> None:
    """Закон 195: дневник — медзапись. Стирание видит её, обезличивание
    сохраняет клинический текст, выгрузка содержит раздел Consultații."""
    with Server() as s:
        c = Client(s.url).login()
        # будущий подтверждённый визит БЕЗ других медданных: до дневника такая
        # фиша удалялась бы физически — с записью обязана обезличиваться
        c.post_json("/api/schedule/appointments", {"date": _d(3), "time": "09:30",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Erase Consult", "phone": "022555666"})
        pid = _pid(c, "022555666")
        aid = _aid(c, _d(3))

        res.check("без дневника фиша удаляется физически", _card(c, pid)["erasure"], "delete")

        c.post_json(f"/api/visits/{aid}", {"acuze": "Control profilactic",
                                          "diagnostic": "Gingivită catarală"})
        # ⚠️ главная проверка набора: erasure_kind обязан считать дневник
        # лечением, иначе right-to-erasure сотрёт медзапись физически
        res.check("с дневником — только обезличивание", _card(c, pid)["erasure"], "anon")

        # выгрузка: раздел есть и в JSON, и в читаемой фише
        r = c.get(f"/admin/patient/{pid}/export")
        res.check("выгрузка отдаётся", r.status, 200)
        z = zipfile.ZipFile(io.BytesIO(r.raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.check("consultatii в JSON-выгрузке", len(data["consultatii"]), 1)
        res.check("диагноз в выгрузке",
                  data["consultatii"][0]["diagnostic"], "Gingivită catarală")
        html_page = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("раздел Consultații в читаемой фише",
               "Consultații (1)" in html_page and "Gingivită" in html_page,
               "HTML-копия без дневника")
        want = (clinic_today() + timedelta(days=3)).strftime("%d.%m.%Y") + " 09:30"
        res.ok("время визита в поясе клиники", want in html_page,
               f"нет строки {want!r} — час UTC утёк в документ")

        r = c.post_json(f"/api/patients/{pid}/erase", {"confirm": "STERG"})
        res.check("обезличивание проходит", r.msg, "ok_anon")
        v = _visit(c, aid)
        res.ok("личность стёрта, клиника осталась",
               v["appt"]["patient"].startswith("Pacient anonimizat")
               and v["record"]["diagnostic"] == "Gingivită catarală",
               f"обезличивание тронуло медзапись или оставило имя: {v['appt']['patient']!r}")


def suite_043(res: Result) -> None:
    """Печатная «Fișa 043/e»: титул, одонтограмма, план, дневник, следы."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": _d(1), "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Fisa Print", "phone": "022777888"})
        pid = _pid(c, "022777888")
        aid = _aid(c, _d(1))
        c.post_json(f"/api/patients/{pid}/profile", {"name": "Fisa Print",
                                                    "phone": "022777888",
                                                    "idnp": "2001100223344",
                                                    "birth_date": "1990-05-05",
                                                    "address": "str. Formularului 43"})
        c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie",
                                                     "note": "carie distală", "doctor": "d2",
                                                     "surfaces": []})
        c.post_json(f"/api/patients/{pid}/alerts", {"kind": "allergy",
                                                   "text": "Alergie la lidocaină"})
        c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Ob<script>alert(1)</script>",
                                                 "tooth": "26", "price": "700"})
        c.post_json(f"/api/visits/{aid}", {"acuze": "Durere la 26",
                                          "diagnostic": "Carie profundă 26",
                                          "tratament": "Obturație fotopolimerizabilă"})
        c.post_file(f"/api/patients/{pid}/documents", "file", "rx.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64, category="radiografie")

        anon = Client(s.url)
        res.ok("без входа форма не отдаётся",
               anon.get(f"/admin/patient/{pid}/fisa043").status == 303,
               "медформа ушла без входа")

        r = c.get(f"/admin/patient/{pid}/fisa043")
        res.check("форма отдаётся", r.status, 200)
        page = r.body
        res.ok("это 043/e с шапкой приказа",
               "FIȘA MEDICALĂ A BOLNAVULUI STOMATOLOGIC" in page
               and "043/e" in page and "828 din 31.10.2011" in page,
               "нет заголовка формуляра")
        res.ok("паспортная часть заполнена",
               "Fisa Print" in page and "2001100223344" in page
               and "05.05.1990" in page, "титул без данных фиши")
        res.ok("одонтограмма: решётка и буква статуса",
               ">18</td>" in page and ">48</td>" in page
               and ">C</td>" in page, "решётки или кода C нет")
        res.ok("легенда напечатана на листе",
               "Cor — coroană" in page and "neexaminat" in page,
               "легенды нет — коды нечитаемы")
        res.ok("заметка зуба в списке", "carie distală" in page,
               "note зуба не печатаются")
        res.ok("аллергия в анамнезе", "Alergie la lidocaină" in page,
               "аллергии нет на титуле")
        res.ok("диагноз дневника поднят на титул",
               page.count("Carie profundă 26") >= 2,
               "титульный «Diagnostic» пуст при заполненном дневнике")
        # ⚠️ время в базе UTC: дневник обязан печатать час клиники
        want = _d(1).split("-")
        want = f"{want[2]}.{want[1]}.{want[0]} 09:00"
        res.ok("час дневника — местный, не UTC", want in page,
               f"нет строки {want!r}")
        res.ok("подпись — имя врача и место под роспись",
               "Medicul (semnătura)" in page, "нет колонки подписи")
        res.ok("пустые строки под ручку", page.count("class='empty'") == 3,
               "лист не продолжается ручкой")
        res.ok("рентген-счётчик упомянут", "radiografii atașate" in page,
               "нет отметки о снимках в программе")
        res.ok("жёлтые пропуски для рукописного", "class='fill'" in page
               and "Bolile suportate" in page, "нет дозаполняемых полей")
        res.ok("XSS в процедуре плана экранирован",
               "<script>alert" not in page, "сырой скрипт в печатной форме")

        res.ok("генерация оставила след в летописи",
               any("Fișa 043/e generată" in a["text"] for a in _card(c, pid)["activity"]["items"]),
               "летопись молчит про выдачу формы")

        # ⚠️ Запись, чей визит отменён или отмечен «неявка», в дневник не
        # идёт: сама программа такую консультацию заполнять отказывается
        # (visit.NO_FORM_STATUSES), а 043/e — первичная меддокументация со
        # сроком хранения 5 лет, и строка в ней читается как проведённое
        # лечение с подписью врача. Бумага не имеет права спорить с журналом.
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "noshow"})
        page = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("запись отменённого визита ушла из дневника",
               "Durere la 26" not in page,
               "043/e печатает приём, которого не было")
        res.ok("и её диагноз не поднят на титул",
               "Carie profundă 26" not in page,
               "диагноз неявки уехал в титульную часть карты")
        # …но из ВЫГРУЗКИ по 195-му она никуда не делась: это данные о
        # пациенте, которые клиника о нём хранит
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        res.ok("в копии по 195-му запись осталась",
               "Durere la 26" in z.read("date-pacient.json").decode("utf-8"),
               "выгрузка потеряла запись вместе с бланком")

        # пустая фиша: форма печатается и без единой записи
        pid2 = new_patient(c, "Gol Fisa")
        r = c.get(f"/admin/patient/{pid2}/fisa043")
        res.ok("пустая фиша тоже печатается",
               r.status == 200 and "class='empty'" in r.body,
               f"код {r.status} на фише без данных")
