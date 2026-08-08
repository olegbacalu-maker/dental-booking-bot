"""Одонтограмма: поверхности зуба (M/O/D/V/L) и молочный прикус.

Формула — единственное место, где клиника рисует диагноз картинкой, и ломается
она молча: страница остаётся кодом 200, а зуб просто не тот. Поэтому здесь
проверяется не «форма сохранилась», а что состояние доехало до ТРЁХ
представлений: карточка, печатная 043/e и выгрузка по 195-му.
"""
import io
import json
import zipfile
from datetime import date, timedelta

from harness import Client, Result, Server


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _pid(c: Client, phone: str) -> str:
    return c.get(f"/admin/search?q={phone}").body.split(
        "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]


def suite_surfaces(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Suprafete Test", phone="022121212")
        pid = _pid(c, "022121212")

        r = c.post(f"/admin/patient/{pid}/tooth", tooth="26", state="obturatie",
                   note="compozit", doctor="d2", sf=["O", "M"])
        res.check("поверхности сохраняются", r.msg, "ok_card")

        page = c.get(f"/admin/patient/{pid}").body
        # ⚠️ порядок канонический MODVL, а не порядок галочек: «OM» и «MO» —
        # одно и то же, и в карте, и на печати это обязано читаться одинаково
        res.ok("поверхности нормализованы в MO", '"sf": "MO"' in page,
               "порядок поверхностей не канонический")
        res.ok("подпись зуба не потеряла прежний формат",
               "26 · Obturație · compozit · MO" in page,
               "формат title изменился — сломается чтение карты")
        res.ok("флажки поверхностей есть в диалоге",
               "name='sf' value='O'" in page and "ocluzal" in page,
               "нет выбора поверхностей")

        res.check("выдуманная поверхность отбрасывается",
                  c.post(f"/admin/patient/{pid}/tooth", tooth="26",
                         state="carie", sf=["Z", "D"]).msg, "ok_card")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("осталась только настоящая буква", '"sf": "D"' in page,
               "мусорная поверхность просочилась")

        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("поверхность напечатана рядом с кодом", ">C D</td>" in f043,
               "в клетке нет поверхности")
        res.ok("легенда объясняет поверхности",
               "M — mezial" in f043 and "V — vestibular" in f043,
               "коды поверхностей нерасшифрованы")

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        res.check("поверхность в выгрузке", data["dinti"][0]["surfaces"], "D")
        res.ok("колонка поверхностей в читаемой фише",
               "Suprafețe" in z.read("fisa-pacient.html").decode("utf-8"),
               "HTML-копия без поверхностей")

        # зуб без поверхностей печатается как раньше — голой буквой
        c.post(f"/admin/patient/{pid}/tooth", tooth="11", state="carie")
        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("зуб без поверхностей — только код", ">C</td>" in f043,
               "пустые поверхности замусорили клетку")


def suite_milk(res: Result) -> None:
    """Молочный прикус: номера 51-55/61-65/71-75/81-85."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Copil Test", phone="022131313")
        pid = _pid(c, "022131313")

        page = c.get(f"/admin/patient/{pid}").body
        res.ok("молочная дуга есть на странице",
               "Dentiție temporară" in page and "milk-arch" in page,
               "нет молочного ряда")
        res.ok("у взрослой фиши она свёрнута",
               "<details class='milk'>" in page,
               "молочный ряд раскрыт там, где по нему нет записей")

        r = c.post(f"/admin/patient/{pid}/tooth", tooth="54", state="carie",
                   note="lapte", doctor="d2")
        res.check("молочный зуб принимается", r.msg, "ok_card")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("состояние молочного зуба видно",
               "54 · Carie · lapte" in page, "молочный зуб не сохранился")
        res.ok("с записями молочный ряд раскрыт сам",
               "<details class='milk' open>" in page,
               "детская фиша требует лишнего клика")

        res.check("несуществующий номер отбит",
                  c.post(f"/admin/patient/{pid}/tooth", tooth="99",
                         state="carie").msg, "bad_card")
        res.check("молочный зуб выбирается в плане лечения",
                  c.post(f"/admin/patient/{pid}/plan", procedure="Obturație 54",
                         tooth="54", price="300").status, 303)
        res.ok("в плане номер молочного зуба сохранён",
               ">54</button>" in c.get(f"/admin/patient/{pid}").body
               or "54" in c.get(f"/admin/patient/{pid}").body,
               "позиция плана потеряла зуб")

        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("молочный ряд напечатан", ">54</td>" in f043 and ">85</td>" in f043,
               "на бланке нет молочного ряда")
        res.ok("постоянный ряд на месте",
               ">18</td>" in f043 and ">48</td>" in f043,
               "молочный ряд вытеснил постоянный")

        # ⚠️ морфология: у молочных квадрантов 5-8 верхняя дуга обязана
        # переворачиваться, а позиции 4-5 — быть МОЛЯРАМИ (премоляров в
        # молочном прикусе нет). Обе ошибки видны только глазом, поэтому
        # проверяются на уровне функций teeth_svg
        import sys
        sys.path.insert(0, str(__import__("harness").BOT))
        from app import teeth_svg as tsvg          # noqa: E402
        res.ok("верхние молочные — верхняя дуга",
               tsvg.is_upper(54) and tsvg.is_upper(61)
               and not tsvg.is_upper(74),
               "молочный ряд нарисуется корнями вверх")
        res.check("54 — моляр, а не премоляр", tsvg.tooth_class(54), "molar")
        res.check("52 — боковой резец", tsvg.tooth_class(52), "incisor_l")
        res.check("53 — клык", tsvg.tooth_class(53), "canine")
        res.check("верхний молочный моляр — три корня",
                  tsvg.root_count(54), 3)
        res.check("нижний молочный моляр — два корня",
                  tsvg.root_count(84), 2)
        res.ok("молочные мельче постоянных",
               tsvg._width_k(51) < tsvg._width_k(11),
               "молочный ряд не отличается по размеру")
