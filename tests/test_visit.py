"""Дневник визита («Consultație»): запись приёма, привязка плана, закон 195.

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

from harness import Client, Result, Server


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _pid(c: Client, phone: str) -> str:
    return c.get(f"/admin/search?q={phone}").body.split(
        "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]


def _aid(c: Client, day: str) -> str:
    """id визита со страницы дня — тем же сплитом, что в test_booking."""
    return c.get(f"/admin/all?date={day}").body.split(
        "/admin/status/", 1)[1].split("'")[0].split('"')[0]


def suite(res: Result) -> None:
    """Базовый цикл: страница, сохранение, правка, видимость, охрана входа."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
               aservice="consult", aname="Consult Test", aphone="022111222",
               back="/admin/all")
        pid = _pid(c, "022111222")
        aid = _aid(c, _d(1))

        page = c.get(f"/admin/visit/{aid}").body
        res.ok("страница консультации открывается",
               "Jurnalul consultației" in page, "нет формы дневника")
        res.ok("шаблоны-заготовки на месте",
               "applyTpl" in page and "Obturație" in page, "нет шаблонов")

        res.check("пустая консультация не сохраняется",
                  c.post(f"/admin/visit/{aid}", acuze="", diagnostic="").msg,
                  "bad_visit")

        r = c.post(f"/admin/visit/{aid}", acuze="Durere la rece",
                   diagnostic="Pulpită acută, dintele 26",
                   tratament="Deschiderea camerei pulpare")
        res.check("консультация сохраняется", r.msg, "ok_visit")

        page = c.get(f"/admin/visit/{aid}").body
        res.ok("текст виден после сохранения",
               "Pulpită acută" in page and "Durere la rece" in page,
               "запись не вернулась в форму")
        res.ok("автор и время записи видны", "Înregistrat:" in page,
               "нет строки авторства")

        # ⚠️ проверять msg, а не 303: отказ и успех отвечают одинаковым кодом
        r = c.post(f"/admin/visit/{aid}", acuze="Durere la rece",
                   diagnostic="Pulpită acută, dintele 26",
                   tratament="Obturație de canal definitivă")
        res.check("правка сохраняется", r.msg, "ok_visit")
        page = c.get(f"/admin/visit/{aid}").body
        res.ok("правка видна и отмечена",
               "Obturație de canal definitivă" in page and "actualizat:" in page,
               "updated_at не показан")

        fisa = c.get(f"/admin/patient/{pid}").body
        res.ok("диагноз виден в истории визитов фиши",
               "Pulpită acută" in fisa, "таймлайн без дневника")
        res.ok("ссылка на консультацию из фиши",
               f"/admin/visit/{aid}" in fisa, "нет ссылки из таймлайна")
        res.ok("сохранение оставило след в летописи",
               "Consultație" in fisa.split("Istoric activitate", 1)[-1]
               or "consult" in fisa, "летопись молчит")

        day = c.get(f"/admin/all?date={_d(1)}").body
        res.ok("маркер дневника в списке дня", "🩺" in day,
               "журнал не показывает, что визит записан")
        res.ok("флаг дневника уехал в карточку модалки", '"rec": true' in day,
               "CARDS без rec — модалка не покажет «Vezi consultația»")
        res.ok("модалка знает адрес консультации", "c_visit" in day,
               "в модалке нет ссылки на дневник")

        anon = Client(s.url)
        res.ok("без входа страница не отдаётся",
               anon.get(f"/admin/visit/{aid}").status == 303,
               "медзапись видна без входа")
        res.ok("без входа запись не пишется",
               anon.post(f"/admin/visit/{aid}", diagnostic="x").status == 303,
               "приняло POST без входа")
        page = c.get(f"/admin/visit/{aid}").body
        res.ok("анонимный POST ничего не изменил", "diagnostic=\"x\"" not in page
               and ">x</textarea>" not in page, "анонимная правка прошла")

        res.ok("несуществующий визит уводит в журнал",
               c.get("/admin/visit/999999").status == 303,
               "должен быть редирект, не ошибка")


def suite_plan(res: Result) -> None:
    """Привязка позиций плана к визиту и запрет записи отменённым визитам."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d2",
               aservice="consult", aname="Plan Vizita", aphone="022333444",
               back="/admin/all")
        pid = _pid(c, "022333444")
        aid = _aid(c, _d(1))

        c.post(f"/admin/patient/{pid}/plan", procedure="Obturație 26",
               tooth="26", price="500")
        c.post(f"/admin/patient/{pid}/plan", procedure="Detartraj", price="300")
        fisa = c.get(f"/admin/patient/{pid}").body
        iids = re.findall(r"/plan/(\d+)/status", fisa)
        res.check("обе позиции на месте", len(iids), 2)
        iid1 = iids[0]

        page = c.get(f"/admin/visit/{aid}").body
        res.ok("нефинальные позиции предлагаются чекбоксами",
               f"name='done' value='{iid1}'" in page and "Detartraj" in page,
               "плана нет в форме консультации")

        r = c.post(f"/admin/visit/{aid}", tratament="Obturație aplicată",
                   done=iid1)
        res.check("сохранение с отметкой позиции", r.msg, "ok_visit")

        # контраст с карточкой: там Planificat→Finalizat запрещён (_PLAN_EDGES),
        # из консультации — разрешён намеренно: дневник фиксирует факт
        fisa = c.get(f"/admin/patient/{pid}").body
        res.ok("позиция финализирована из консультации",
               "data-st='finalizat'" in fisa, "статус не изменился")
        res.ok("долг посчитан по финализированному",
               "De achitat" in fisa and "500 MDL" in fisa,
               "финансы не увидели финализацию")

        page = c.get(f"/admin/visit/{aid}").body
        res.ok("привязка видна на странице визита",
               "Efectuate la această vizită" in page and "Obturație 26" in page,
               "линка позиции к визиту нет")
        res.ok("вторая позиция осталась чекбоксом",
               "name='done'" in page and "Detartraj" in page,
               "непривязанное исчезло из формы")

        # Redeschide в фише = «на самом деле не сделано» → привязка снимается
        res.check("Redeschide позиции",
                  c.post(f"/admin/patient/{pid}/plan/{iid1}/status",
                         to="in_lucru").msg, "")
        page = c.get(f"/admin/visit/{aid}").body
        res.ok("привязка снята вместе с done_at",
               "Efectuate la această vizită" not in page
               and f"name='done' value='{iid1}'" in page,
               "переоткрытая позиция осталась «выполненной на визите»")

        # отменённый визит консультацию не принимает
        c.post("/admin/add", adate=_d(2), atime="11:00", adoctor="d2",
               aservice="consult", aname="Plan Vizita", aphone="022333444",
               back="/admin/all")
        aid2 = _aid(c, _d(2))
        c.post(f"/admin/status/{aid2}", to="cancelled", back="/admin/all")
        res.check("отменённому визиту запись не пишется",
                  c.post(f"/admin/visit/{aid2}", diagnostic="x").msg, "bad_vst")
        page = c.get(f"/admin/visit/{aid2}").body
        res.ok("страница отменённого визита без формы",
               "nu se completează" in page and "vf_diagnostic" not in page,
               "форма отдаётся отменённому визиту")


def suite_195(res: Result) -> None:
    """Закон 195: дневник — медзапись. Стирание видит её, обезличивание
    сохраняет клинический текст, выгрузка содержит раздел Consultații."""
    with Server() as s:
        c = Client(s.url).login()
        # будущий подтверждённый визит БЕЗ других медданных: до дневника такая
        # фиша удалялась бы физически — с записью обязана обезличиваться
        c.post("/admin/add", adate=_d(3), atime="09:30", adoctor="d2",
               aservice="consult", aname="Erase Consult", aphone="022555666",
               back="/admin/all")
        pid = _pid(c, "022555666")
        aid = _aid(c, _d(3))

        fisa = c.get(f"/admin/patient/{pid}").body
        res.ok("без дневника фиша удаляется физически",
               "Șterge definitiv" in fisa, "ветка стирания уже не delete")

        c.post(f"/admin/visit/{aid}", acuze="Control profilactic",
               diagnostic="Gingivită catarală")
        fisa = c.get(f"/admin/patient/{pid}").body
        # ⚠️ главная проверка набора: erasure_kind обязан считать дневник
        # лечением, иначе right-to-erasure сотрёт медзапись физически
        res.ok("с дневником — только обезличивание",
               "Șterge datele personale" in fisa
               and "Șterge definitiv" not in fisa,
               "запись приёма не удержала фишу от физического удаления")

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
        want = (date.today() + timedelta(days=3)).strftime("%d.%m.%Y") + " 09:30"
        res.ok("время визита в поясе клиники", want in html_page,
               f"нет строки {want!r} — час UTC утёк в документ")

        r = c.post(f"/admin/patient/{pid}/erase", confirm="STERG")
        res.check("обезличивание проходит", r.msg, "ok_anon")
        page = c.get(f"/admin/visit/{aid}").body
        res.ok("личность стёрта, клиника осталась",
               "Pacient anonimizat" in page and "Gingivită catarală" in page,
               "обезличивание тронуло медзапись или оставило имя")
