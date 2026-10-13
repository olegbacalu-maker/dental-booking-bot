"""Отказ пациента от процедуры и печатный «Acord informat» к плану лечения.

Норма — ст. 13 Legea nr. 263/2005: согласие на вмешательство оформляется
письменно (ч. 2), содержит цель, методы, риск, экономические последствия и
альтернативы (ч. 3), а ОТКАЗ вносится в медицинскую документацию с указанием
возможных последствий и подписывается пациентом и врачом (ч. 5).

Отсюда два предмета проверки:
  * отказ — это СТАТУС, а не удаление: позиция остаётся в фише, в 043/e и в
    выгрузке, а кнопка «Șterge» до неё не дотягивается;
  * отказ не «активен»: он не ждёт работы, не считается в сумму плана и не
    предлагается на визите как «выполнено».
⚠️ Проверять msg, а не только код ответа: «удалось» и «нельзя» различает
код конверта (до 13.10 у форм старой фиши оба исхода были одним 303).
Фиша и визит читаются через JSON API — их рисует React.
"""
import io
import json
import sqlite3
import sys
import zipfile
from datetime import date, timedelta

from harness import BOT, Client, Result, Server, clinic_today, pid_by_phone


def _pid(c: Client, phone: str) -> str:
    return str(pid_by_phone(c, phone))


def _card(c: Client, pid) -> dict:
    """Фиша данными (`GET /api/patients/{pid}`)."""
    return json.loads(c.get(f"/api/patients/{pid}").body)["data"]


def _plan(c: Client, pid) -> dict:
    """Позиции плана фиши по имени процедуры.

    ⚠️ Имя процедуры живёт в фише ДВАЖДЫ: в плане и в ленте событий
    («Plan: - Detartraj», «Plan: … › REFUZAT (причина)»). Поэтому план берётся
    сам по себе, а лента — отдельно (`_feed`)."""
    return {it["procedure"]: it for it in _card(c, pid)["plan"]["items"]}


def _feed(c: Client, pid) -> list[str]:
    return [a["text"] for a in _card(c, pid)["activity"]["items"]]


def _iids(c: Client, pid) -> list:
    """id позиций плана в порядке плана фиши."""
    return [it["id"] for it in _card(c, pid)["plan"]["items"]]


def _setup(c: Client) -> str:
    """Пациент с планом из трёх позиций: две останутся активными, одну
    отвергнет пациент."""
    c.post("/admin/add", adate=(clinic_today() + timedelta(days=1)).isoformat(),
           atime="09:00", adoctor="d2", aservice="consult",
           aname="Refuz Test", aphone="022777888", back="/admin/all")
    pid = _pid(c, "022777888")
    c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Extracție 36", "tooth": "36",
                                             "price": "900", "doctor": "Dr. Ana"})
    c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Obturație 26", "tooth": "26",
                                             "price": "600", "doctor": "Dr. Ana"})
    c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Detartraj", "price": "500",
                                             "doctor": "Dr. Ana"})
    return pid


def suite_refuz(res: Result) -> None:
    """Статус «Refuzat»: рёбра, обязательная причина, запрет удаления."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        i1, i2, i3 = _iids(c, pid)[:3]

        def flip(iid, to: str, **kw) -> str:
            return c.post_json(f"/api/patients/{pid}/plan/{iid}/status", {"to": to, **kw}).msg

        res.ok("отказ предлагается у запланированного",
               {it["id"]: it["refusable"] for it in _card(c, pid)["plan"]["items"]}[i1],
               "нет входа в отказ")

        # ⭐ Без причины отказ не принимается СЕРВЕРОМ: required в форме
        # обходится любым запросом мимо страницы, а запись по ч.(5) без
        # объяснённых последствий — не запись
        res.check("отказ без причины не принимается", flip(i1, "refuzat"),
                  "bad_refuz")
        res.check("отказ с причиной принимается",
                  flip(i1, "refuzat", motiv="Pacientul refuză extracția; "
                                            "i s-au explicat riscurile"),
                  "ok_refuz")

        card = _card(c, pid)
        plan = {it["procedure"]: it for it in card["plan"]["items"]}
        res.ok("позиция осталась в фише", "Extracție 36" in plan,
               "отказ стёр позицию из плана")
        res.ok("причина видна прямо в строке",
               "i s-au explicat riscurile" in plan.get("Extracție 36", {}).get("motiv", ""),
               "причина не показана")
        res.check("статус отказа на месте", plan["Extracție 36"]["status"], "refuzat")
        res.check("вкладка отказов появилась (счёт отказов)",
                  card["plan"]["counts"].get("refuzat"), 1)

        # ⛔ Удалять можно только НЕТРОНУТОЕ: иначе кнопка «Șterge» стирала бы
        # ровно то, что закон велит хранить
        res.check("у отказа нет удаления", plan["Extracție 36"]["deletable"], False)
        res.check("и удалить его запросом нельзя",
                  c.post_json(f"/api/patients/{pid}/plan/{i1}/delete", {}).msg, "bad_pdel")
        res.ok("позиция пережила попытку удаления", "Extracție 36" in _plan(c, pid),
               "запрос всё-таки стёр запись")

        # начатую тоже не стереть — она уже клинический факт
        res.check("начатую в работу — можно", flip(i2, "in_lucru"), "")
        res.check("начатую удалить нельзя",
                  c.post_json(f"/api/patients/{pid}/plan/{i2}/delete", {}).msg, "bad_pdel")
        res.check("нетронутую удалить можно",
                  c.post_json(f"/api/patients/{pid}/plan/{i3}/delete", {}).msg, "")
        res.ok("нетронутая исчезла", "Detartraj" not in _plan(c, pid),
               "опечатку стереть не дали")

        # рёбра: отказаться от сделанного нельзя, вернуться можно только в план
        res.check("из работы в отказ — можно",
                  flip(i2, "refuzat", motiv="amână tratamentul"), "ok_refuz")
        res.check("из отказа сразу в работу нельзя",
                  flip(i2, "in_lucru", motiv="x"), "bad_card")
        res.check("Reia: из отказа в план — можно", flip(i2, "planificat"), "")
        res.check("довели до финала", flip(i2, "in_lucru"), "")
        res.check("и финализировали", flip(i2, "finalizat"), "")
        res.check("отказаться от сделанного нельзя",
                  flip(i2, "refuzat", motiv="prea târziu"), "bad_card")

        # ⚠️ Смотрится сама запись в базе: фиша показывает причину только у
        # отказа, и по ней «стёрлась ли» не проверить — она молчала бы в обоих случаях
        con = sqlite3.connect(str(s.dir / "dental.db"))
        try:
            motiv = con.execute("SELECT refuz_motiv FROM plan_items WHERE id = ?", (i2,)).fetchone()[0]
        finally:
            con.close()
        res.check("возврат в план стёр прежнюю причину", motiv or "", "")
        # ⭐ …но из ЛЕНТЫ она никуда не делась: отказ был, и запись о нём —
        # часть журнала доступа по 195-му, а не черновик
        res.ok("в летописи отказ остался с причиной",
               any("amână tratamentul" in t for t in _feed(c, pid)), "событие отказа исчезло из ленты")


def suite_refuz_not_active(res: Result) -> None:
    """Отказ НЕ активен: ни в KPI, ни в сумме плана, ни в списке, ни в
    галочках визита. ⭐ Прежде «активным» считалось всё, что не finalizat, —
    и отказ застрял бы в лечении навсегда."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        i1 = _iids(c, pid)[0]

        plan = _card(c, pid)["plan"]
        res.check("до отказа в плане три активных", plan["n_act"], 3)
        res.check("и сумма плана — 2 000", plan["total"], 2000)

        c.post_json(f"/api/patients/{pid}/plan/{i1}/status", {"to": "refuzat",
                                                             "motiv": "refuz documentat"})
        plan = _card(c, pid)["plan"]
        res.check("активных стало два", plan["n_act"], 2)
        # 900 отказано → в «plan activ» обязано остаться 1 100
        res.check("цена отказа ушла из суммы плана", plan["total"], 1100)
        res.check("прогресс не считает отказ в знаменателе (0/2, 1 отказ)",
                  (plan["total_done"], plan["n_track"], plan["counts"].get("refuzat")), (0, 2, 1))

        # список пациентов: «в лечении» считается по активным позициям
        rows = json.loads(c.get("/api/patients?q=022777888").body)["data"]["rows"]
        res.check("в списке пациент числится в лечении (по активным позициям)",
                  [(r["name"], r["status"]) for r in rows], [("Refuz Test", "tratament")])

        # визит не предлагает отметить отказанное как выполненное
        aid = c.get(f"/admin/all?date="
                    f"{(clinic_today() + timedelta(days=1)).isoformat()}"
                    ).body.split("/admin/status/", 1)[1].split("'")[0]
        opened = [x["text"] for x in json.loads(c.get(f"/api/visits/{aid}").body)["data"]["plan"]["open"]]
        res.ok("в консультации нет галочки на отказанное",
               any("Obturație 26" in t for t in opened) and not any("Extracție 36" in t for t in opened),
               f"отказ предложен как «выполнено на визите»: {opened}")
        # ⚠️ и запросом мимо страницы тоже: устаревшая вкладка прислала бы id
        c.post_json(f"/api/visits/{aid}", {"acuze": "test", "done": [i1]})
        res.check("отказ не финализируется чужим запросом",
                  _plan(c, pid)["Extracție 36"]["status"], "refuzat")


def suite_acord_medic(res: Result) -> None:
    """Кто подписывает лист как лечащий врач (ст. 13(2) Legea 263/2005).

    Позиции несут СНАПШОТ имени врача, и у закрытых позиций он свой. Согласие
    же дают на АКТИВНЫЕ вмешательства — значит и «Confirm că am explicat»
    подписывает тот, кто их выполняет. Сервера здесь не нужно: вопрос целиком
    в одной функции, а спор про имена решается кортежем db.PLAN_ACTIVE.
    """
    sys.path.insert(0, str(BOT))
    from app.modules.patients import plan_acord

    res.check("врач закрытой позиции не подписывает согласие",
              plan_acord.medic_name(
                  [{"doctor": "Dr. Vechi", "status": "finalizat"},
                   {"doctor": "", "status": "planificat"}],
                  {"primary_doctor": "Dr. Curent"}), "Dr. Curent")
    res.check("отказ тоже не даёт имени подписи",
              plan_acord.medic_name(
                  [{"doctor": "Dr. Vechi", "status": "refuzat"},
                   {"doctor": "", "status": "planificat"}],
                  {"primary_doctor": "Dr. Curent"}), "Dr. Curent")
    # зеркальный случай: имён по всему плану два, по активным — одно, и при
    # пустом primary_doctor старая формула стирала имя с листа вовсе
    res.check("подписывает врач согласуемой позиции",
              plan_acord.medic_name(
                  [{"doctor": "Dr. A", "status": "finalizat"},
                   {"doctor": "Dr. B", "status": "planificat"}], {}), "Dr. B")


def suite_acord(res: Result) -> None:
    """Печатный лист согласия: состав по ст.13(3) и обе подписи по ст.13(2)."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        c.post_json(f"/api/patients/{pid}/profile", {"name": "Refuz Test",
                                                    "phone": "022777888",
                                                    "birth_date": "1990-05-06"})
        i1 = _iids(c, pid)[0]
        c.post_json(f"/api/patients/{pid}/plan/{i1}/status", {"to": "refuzat",
                                                             "motiv": "teama de intervenție; consecințe explicate"})

        r = c.get(f"/admin/patient/{pid}/plan-acord")
        res.ok("лист открывается", r.status == 200, f"код {r.status}")
        b = r.body
        res.ok("лист называет закон и приказ",
               "Legea nr. 263/2005" in b and "303" in b,
               "нет ссылки на норму — по ней лист опознают на проверке")
        # ⚠️ на подписываемом листе даты одного формата: ниже стоит «Data:
        # dd.mm.yyyy», и сырой ISO из базы рядом с ней читается как чужая
        # запись, а на экране регистратуры та же дата показана dd.mm.yyyy
        res.ok("дата рождения — dd.mm.yyyy, как остальные даты листа",
               "06.05.1990" in b and "1990-05-06" not in b,
               "в шапке согласия сырой ISO из базы")
        # ⭐ состав по ч.(3): цель, методы, риск, экономика, альтернативы
        for needle, what in (("Diagnosticul", "диагноз"),
                             ("Obturație 26", "методы = позиции плана"),
                             ("efectul scontat", "цель и ожидаемый эффект"),
                             ("Riscul potențial", "риск"),
                             ("alternative", "альтернативы")):
            res.ok(f"на листе есть {what}", needle in b, f"нет {needle!r}")
        res.ok("итог по деньгам — экономические последствия",
               "1 100" in b or "1100" in b, "нет суммы плана на листе")

        # ⛔ выполненного и отказанного в согласии быть не должно: согласие
        # подписывают ДО, а отказ живёт в своём блоке
        res.ok("отказанное не стоит среди согласуемого",
               b.split("Refuzul pacientului")[0].count("Extracție 36") == 0,
               "отказ попал в список того, на что дают согласие")
        res.ok("блок отказа на месте", "Refuzul pacientului" in b
               and "teama de intervenție" in b, "нет блока отказа")

        # ⚠️ подписи ДВЕ и они не симметричны: пациент понял, врач объяснил
        res.ok("подпись пациента", "Semnătura pacientului" in b, "нет подписи")
        res.ok("подпись врача", "Semnătura medicului" in b, "нет подписи врача")
        res.ok("врач подтверждает, что объяснил",
               "am explicat pacientului" in b,
               "лист не фиксирует сам факт информирования")
        res.ok("врач подставлен из плана", "Dr. Ana" in b,
               "medic curant не подставлен")
        res.ok("есть строка законного представителя",
               "reprezentantul legal" in b, "нет строки для несовершеннолетнего")

        ru = c.get(f"/admin/patient/{pid}/plan-acord?lang=ru").body
        res.ok("русская версия открывается", "Подпись пациента" in ru,
               "нет русского листа")
        res.ok("русская версия оговаривает опорный язык",
               "румынском" in ru, "перевод выдан за оригинал")
        res.ok("название закона не переведено", "Legea nr. 263/2005" in ru,
               "юридическое имя ушло в перевод")

        # генерация листа — событие обработки, как acord и 043/e
        res.ok("выдача листа попала в летопись",
               any("Acord informat" in t for t in _feed(c, pid)),
               "нет записи в ленте фиши")


def suite_refuz_docs(res: Result) -> None:
    """Отказ доезжает до 043/e и до выгрузки по 195-му: и то и другое —
    места, где запись обязана быть, чтобы считаться сделанной."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        i1 = _iids(c, pid)[0]
        c.post_json(f"/api/patients/{pid}/plan/{i1}/status", {"to": "refuzat",
                                                             "motiv": "motiv consemnat pentru 043"})

        f = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("043/e показывает статус отказа", "REFUZAT" in f,
               "в разделе 5 отказ неотличим от плана")
        res.ok("043/e печатает причину", "motiv consemnat pentru 043" in f,
               "причина не попала в медкарту")
        fru = c.get(f"/admin/patient/{pid}/fisa043?lang=ru").body
        res.ok("русская 043/e тоже называет отказ", "ОТКАЗ" in fru,
               "русский бланк молчит про отказ")

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        html = next(n for n in z.namelist() if n.endswith(".html"))
        text = z.read(html).decode("utf-8")
        res.ok("причина отказа есть в копии по 195-му",
               "motiv consemnat pentru 043" in text,
               "пациент не увидит, как записан его отказ")
