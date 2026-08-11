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
⚠️ Проверять msg, а не код: у карточки оба исхода — 303 (см. прайор в
CLAUDE.md про _card_redirect).
"""
import io
import re
import zipfile
from datetime import date, timedelta

from harness import Client, Result, Server


def _pid(c: Client, phone: str) -> str:
    return c.get(f"/admin/search?q={phone}").body.split(
        "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]


def _plan_block(page: str) -> str:
    """Только карточка плана.

    ⚠️ Имя процедуры живёт на странице ДВАЖДЫ: в плане и в ленте событий
    («Plan: − Detartraj», «Plan: … → refuzat (причина)»). Проверка по всей
    странице зеленела бы на удалённой позиции и краснела бы на очищенной
    причине — то есть врала бы в обе стороны.
    """
    return page.split("id='plan'", 1)[1].split("class='fcard'", 1)[0]


def _iids(page: str) -> list:
    """id позиций плана в порядке появления на странице."""
    seen = []
    for m in re.findall(r"/plan/(\d+)/status", page):
        if m not in seen:
            seen.append(m)
    return seen


def _setup(c: Client) -> str:
    """Пациент с планом из трёх позиций: две останутся активными, одну
    отвергнет пациент."""
    c.post("/admin/add", adate=(date.today() + timedelta(days=1)).isoformat(),
           atime="09:00", adoctor="d2", aservice="consult",
           aname="Refuz Test", aphone="022777888", back="/admin/all")
    pid = _pid(c, "022777888")
    c.post(f"/admin/patient/{pid}/plan", procedure="Extracție 36", tooth="36",
           price="900", doctor="Dr. Ana")
    c.post(f"/admin/patient/{pid}/plan", procedure="Obturație 26", tooth="26",
           price="600", doctor="Dr. Ana")
    c.post(f"/admin/patient/{pid}/plan", procedure="Detartraj", price="500",
           doctor="Dr. Ana")
    return pid


def suite_refuz(res: Result) -> None:
    """Статус «Refuzat»: рёбра, обязательная причина, запрет удаления."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        page = c.get(f"/admin/patient/{pid}").body
        i1, i2, i3 = _iids(page)[:3]

        def flip(iid: str, to: str, **kw) -> str:
            return c.post(f"/admin/patient/{pid}/plan/{iid}/status",
                          to=to, **kw).msg

        res.ok("кнопка отказа есть у запланированного",
               f"data-id='{i1}'" in page and "openRefuz" in page,
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

        page = c.get(f"/admin/patient/{pid}").body
        res.ok("позиция осталась в фише", "Extracție 36" in _plan_block(page),
               "отказ стёр позицию из плана")
        res.ok("причина видна прямо в строке",
               "i s-au explicat riscurile" in _plan_block(page),
               "причина не показана")
        res.ok("бейдж отказа на месте", "data-st='refuzat'" in page,
               "статус не отрисован")
        res.ok("вкладка отказов появилась", "data-f='refuzat'" in page,
               "нет вкладки Refuzate")

        # ⛔ Удалять можно только НЕТРОНУТОЕ: иначе кнопка «Șterge» стирала бы
        # ровно то, что закон велит хранить
        refuz_row = page.split("data-st='refuzat'", 1)[1][:900]
        res.ok("у отказа нет кнопки удаления", "/del'" not in refuz_row,
               "отказ можно стереть кнопкой")
        res.check("и удалить его запросом нельзя",
                  c.post(f"/admin/patient/{pid}/plan/{i1}/del").msg, "bad_pdel")
        res.ok("позиция пережила попытку удаления",
               "Extracție 36" in _plan_block(c.get(f"/admin/patient/{pid}").body),
               "запрос всё-таки стёр запись")

        # начатую тоже не стереть — она уже клинический факт
        res.check("начатую в работу — можно", flip(i2, "in_lucru"), "")
        res.check("начатую удалить нельзя",
                  c.post(f"/admin/patient/{pid}/plan/{i2}/del").msg, "bad_pdel")
        res.check("нетронутую удалить можно",
                  c.post(f"/admin/patient/{pid}/plan/{i3}/del").msg, "")
        res.ok("нетронутая исчезла",
               "Detartraj" not in _plan_block(c.get(f"/admin/patient/{pid}").body),
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

        page = c.get(f"/admin/patient/{pid}").body
        res.ok("возврат в план стёр прежнюю причину",
               "amână tratamentul" not in _plan_block(page),
               "старая причина отказа осталась на выполненной позиции")
        # ⭐ …но из ЛЕНТЫ она никуда не делась: отказ был, и запись о нём —
        # часть журнала доступа по 195-му, а не черновик
        res.ok("в летописи отказ остался с причиной",
               "amână tratamentul" in page, "событие отказа исчезло из ленты")


def suite_refuz_not_active(res: Result) -> None:
    """Отказ НЕ активен: ни в KPI, ни в сумме плана, ни в списке, ни в
    галочках визита. ⭐ Прежде «активным» считалось всё, что не finalizat, —
    и отказ застрял бы в лечении навсегда."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        i1 = _iids(c.get(f"/admin/patient/{pid}").body)[0]

        page = c.get(f"/admin/patient/{pid}").body
        res.ok("до отказа в плане три активных", "Active (3)" in page,
               "не та отправная точка")
        res.ok("и сумма плана — 2 000", "2 000 MDL" in page,
               "сумма активного плана посчитана иначе")

        c.post(f"/admin/patient/{pid}/plan/{i1}/status", to="refuzat",
               motiv="refuz documentat")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("активных стало два", "Active (2)" in page,
               "отказ остался среди активных")
        # 900 отказано → в «plan activ» обязано остаться 1 100
        res.ok("цена отказа ушла из суммы плана",
               "1 100 MDL" in page and "2 000 MDL" not in page,
               "отказанная процедура всё ещё в счёте")
        res.ok("прогресс не считает отказ в знаменателе",
               "0/2 finalizate" in page and "1 refuzate" in page,
               "отказ застрял в прогрессе")

        # список пациентов: «в лечении» считается по активным позициям
        lst = c.get("/admin/search?q=022777888").body
        res.ok("в списке пациент числится с 2 позициями",
               "2" in lst and "Refuz Test" in lst, "список не открылся")

        # визит не предлагает отметить отказанное как выполненное
        aid = c.get(f"/admin/all?date="
                    f"{(date.today() + timedelta(days=1)).isoformat()}"
                    ).body.split("/admin/status/", 1)[1].split("'")[0]
        vis = c.get(f"/admin/visit/{aid}").body
        res.ok("в консультации нет галочки на отказанное",
               "Obturație 26" in vis and "Extracție 36" not in vis,
               "отказ предложен как «выполнено на визите»")
        # ⚠️ и запросом мимо страницы тоже: устаревшая вкладка прислала бы id
        c.post(f"/admin/visit/{aid}", acuze="test", done=i1)
        res.ok("отказ не финализируется чужим запросом",
               "data-st='refuzat'" in c.get(f"/admin/patient/{pid}").body,
               "отказ молча стал выполненным")


def suite_acord(res: Result) -> None:
    """Печатный лист согласия: состав по ст.13(3) и обе подписи по ст.13(2)."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        i1 = _iids(c.get(f"/admin/patient/{pid}").body)[0]
        c.post(f"/admin/patient/{pid}/plan/{i1}/status", to="refuzat",
               motiv="teama de intervenție; consecințe explicate")

        r = c.get(f"/admin/patient/{pid}/plan-acord")
        res.ok("лист открывается", r.status == 200, f"код {r.status}")
        b = r.body
        res.ok("лист называет закон и приказ",
               "Legea nr. 263/2005" in b and "303" in b,
               "нет ссылки на норму — по ней лист опознают на проверке")
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
               "Acord informat" in c.get(f"/admin/patient/{pid}").body,
               "нет записи в ленте фиши")


def suite_refuz_docs(res: Result) -> None:
    """Отказ доезжает до 043/e и до выгрузки по 195-му: и то и другое —
    места, где запись обязана быть, чтобы считаться сделанной."""
    with Server() as s:
        c = Client(s.url).login()
        pid = _setup(c)
        i1 = _iids(c.get(f"/admin/patient/{pid}").body)[0]
        c.post(f"/admin/patient/{pid}/plan/{i1}/status", to="refuzat",
               motiv="motiv consemnat pentru 043")

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
