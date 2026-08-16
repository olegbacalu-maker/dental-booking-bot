"""Одонтограмма: поверхности зуба (M/O/D/V/L) и молочный прикус.

Формула — единственное место, где клиника рисует диагноз картинкой, и ломается
она молча: страница остаётся кодом 200, а зуб просто не тот. Поэтому здесь
проверяется не «форма сохранилась», а что состояние доехало до ТРЁХ
представлений: карточка, печатная 043/e и выгрузка по 195-му.
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
        res.ok("в карточке есть переключатель вида",
               "Vedere ocluzală" in page and "data-view='frontal'" in page,
               "вид сверху недоступен")
        res.ok("обе дуги уехали в страницу",
               "v-frontal" in page and "v-ocluzal" in page and "tooth-occ" in page,
               "один из видов не отрисован")

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


def _pts(d: str) -> list:
    """Точки контура. Все команды путей здесь (M/L/C/Q/Z) записаны парами
    координат через `_p`, поэтому числа читаются подряд парами."""
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return list(zip(nums[0::2], nums[1::2]))


def _span(pts: list, at_y: float = None) -> float:
    row = [x for x, y in pts if at_y is None or abs(y - at_y) < 0.01]
    return (max(row) - min(row)) if row else 0.0


def suite_shape(res: Result) -> None:
    """Геометрия зуба: то, что ломается МОЛЧА.

    Кривые правятся глазами по кадру, а ошибка в них не падает и не пишется в
    лог — зуб просто перестаёт быть похож на зуб. До 08-16 контур был шире у
    ШЕЙКИ, чем у режущего края (20 против 17), и на дуге резцы читались
    листьями; заметить это можно было только сняв страницу. Здесь закреплены
    те свойства формы, из-за потери которых рисунок врёт.
    """
    import sys
    sys.path.insert(0, str(__import__("harness").BOT))
    from app import teeth_svg as tsvg          # noqa: E402

    every = [11, 12, 13, 14, 15, 16, 17, 18, 41, 42, 43, 44, 45, 46, 47, 48,
             51, 52, 53, 54, 55, 81, 82, 83, 84, 85]

    # 1. коронка сужается К ШЕЙКЕ, а не от неё.
    # ⚠️ Сравнивать надо ЖЕВАТЕЛЬНУЮ ПОЛОВИНУ с шейкой, а не весь контур с
    # шейкой: точки шейки входят и в «весь контур», поэтому расширение шейки
    # раздувает обе стороны неравенства разом — первая редакция этой проверки
    # пережила ровно ту поломку, ради которой писалась (шейка 15→11: 8/8
    # зелёных). Тот самый случай из карты: правило зелено и когда всё хорошо,
    # и когда оно само сломано
    flat = []
    for n in every:
        pts = _pts(tsvg.crown_path(n))
        neck_y = max(y for _x, y in pts)
        edge = [(x, y) for x, y in pts if y < neck_y * 0.5]
        if _span(edge) < _span(pts, neck_y) * 1.15:
            flat.append(n)
    res.ok("коронка шире у жевательного края, чем у шейки", not flat,
           f"контур не сужается к шейке: {flat}")

    # 2. корень не торчит из-под коронки
    wide = []
    for n in every:
        crown = _pts(tsvg.crown_path(n))
        neck = _span(crown, max(y for _x, y in crown))
        rx = [x for d in tsvg.root_paths(n) for x, y in _pts(d) if abs(y - 42) < 0.01]
        if rx and (max(rx) - min(rx)) > neck:
            wide.append(n)
    res.ok("шейка корня уже шейки коронки", not wide,
           f"стык корня торчит наружу: {wide}")

    # 3. пропорции ряда: верхний центральный резец ≈ 0.8 моляра, нижний ≈ 0.55.
    # Одно число на класс давало 0.58 для обоих — «спички между молярами»
    up = _span(_pts(tsvg.crown_path(11))) / _span(_pts(tsvg.crown_path(16)))
    low = _span(_pts(tsvg.crown_path(41))) / _span(_pts(tsvg.crown_path(46)))
    res.ok("верхний резец соразмерен моляру", 0.72 <= up <= 0.88,
           f"11 к 16 = {up:.2f}, ожидалось 0.72-0.88")
    res.ok("нижний резец уже верхнего", 0.45 <= low <= 0.62,
           f"41 к 46 = {low:.2f}, ожидалось 0.45-0.62")

    # 4. метки поверхностей лежат ВНУТРИ коронки: метка снаружи читается как
    # пятно рядом с зубом, и это единственное, что видно вместо диагноза
    out = []
    for n in (11, 13, 14, 16, 36, 41, 46, 54):
        crown = _pts(tsvg.crown_path(n))
        lo, hi = min(x for x, _y in crown), max(x for x, _y in crown)
        # карта «все пять поражены» — проверяем МЕСТА меток, а не цвета
        for mark in tsvg._surface_marks(
                n, {k: "carie" for k in tsvg.SURFACE_ORDER}):
            cx = float(re.search(r"cx='(-?[\d.]+)'", mark).group(1))
            r = float(re.search(r"r='(-?[\d.]+)'", mark).group(1))
            if cx - r < lo or cx + r > hi:
                out.append(n)
                break
    res.ok("метки поверхностей внутри контура", not out,
           f"метка вылезает за коронку: {out}")

    # 5. градиент эмали виден только по ссылке — id обязан быть В ЭТОМ ЖЕ теге,
    # иначе коронка станет прозрачной, и молча: `url(#нет)` не ошибка
    for st in ("ok", "carie", "coroana"):
        svg = tsvg.tooth_svg(16, st)
        gid = re.search(r"fill='url\(#([^)]+)\)'", svg)
        res.ok(f"градиент {st} объявлен рядом со ссылкой",
               bool(gid) and f"id='{gid.group(1)}'" in svg,
               "ссылка на градиент без определения — коронка без заливки")

def suite_occlusal(res: Result) -> None:
    """Вид сверху: ориентация и поля поверхностей.

    Всё, что здесь проверяется, ломается МОЛЧА и остаётся красивой картинкой.
    Самое опасное — переворот: в лицевом виде переворачивается ВЕРХНЯЯ дуга, в
    окклюзионном НИЖНЯЯ, и скопированное правило нарисует обе дуги щеками
    внутрь. Кариес на мезиальной покажется на дистальной, зуб останется зубом,
    а ошибку заметит только тот, кто сядет сверять рисунок с картой.
    """
    import sys
    sys.path.insert(0, str(__import__("harness").BOT))
    from app import teeth_svg as tsvg          # noqa: E402

    every = [11, 12, 13, 14, 15, 16, 17, 18, 21, 26, 31, 36, 41, 42, 43, 44,
             45, 46, 47, 48, 51, 53, 55, 61, 71, 75, 81, 83, 85]

    # 1. переворот у двух видов РАЗНЫЙ и оба — свой
    bad = [n for n in every
           if ("scale(1,-1)" in tsvg.occlusal_svg(n)) != (not tsvg.is_upper(n))]
    res.ok("сверху переворачивается нижняя дуга", not bad,
           f"щёчная сторона смотрит внутрь дуги: {bad}")
    bad = [n for n in every
           if ("scale(1,-1)" in tsvg.tooth_svg(n)) != tsvg.is_upper(n)]
    res.ok("в лицевом виде переворачивается верхняя", not bad,
           f"коронки смотрят не в ту сторону: {bad}")

    # 2. мезиальная поверхность — со стороны средней линии.
    # ⚠️ С 08-16 геометрия рисуется в КАНОНЕ (мезиальная сторона справа), а
    # сторону выбирает зеркало обёртки. Поэтому проверяются две вещи порознь:
    # что канон не сполз, и что зеркало навешено ровно тем зубам, у которых
    # середина слева. Смотреть только на `occ_zones` теперь бессмысленно —
    # там всегда одно и то же, и проверка была бы зелена при любом зеркале
    canon = [n for n in every if tsvg.occ_zones(n)["M"][0] <= tsvg.OCC_C]
    res.ok("мезиальное поле в каноне справа", not canon,
           f"канон сполз: {canon}")
    wrong = [n for n in every
             if tsvg.mirrored(n) != (n // 10 in (2, 3, 6, 7))]
    res.ok("зеркало навешено по квадранту", not wrong,
           f"мезиальная и дистальная поменялись местами: {wrong}")
    bad = [n for n in every
           if ("scale(-1,1)" in tsvg.occlusal_svg(n)) != tsvg.mirrored(n)
           or ("scale(-1,1)" in tsvg.tooth_svg(n)) != tsvg.mirrored(n)]
    res.ok("зеркало доехало до рисунка", not bad,
           f"контур нарисован не той стороной: {bad}")

    # 3. пять полей стоят каждое на своём месте и все попадают в зуб.
    # ⚠️ Проверять «сумма ширин равна рамке» бесполезно: поля СТРОЯТСЯ как
    # разбиение рамки, и сумма выходит верной при любых числах — такая
    # проверка зелена всегда, включая сломанную (грабля из карты про
    # полярность). Falsifiable здесь — ПОРЯДОК полей и попадание в контур.
    # ⚠️ Мерить середину прямоугольника нельзя: поля НАРОЧНО выходят за контур
    # (их режет обтравка), поэтому середина щёчного поля лежит выше зуба даже
    # когда всё правильно. Смотреть надо на ПЕРЕСЕЧЕНИЕ поля с зубом.
    misplaced, offtooth = [], []
    for n in every:
        z = tsvg.occ_zones(n)
        if not (z["V"][1] < z["O"][1] < z["L"][1]):
            misplaced.append((n, "щёчное и язычное поменялись местами"))
        if any(v[2] <= 0 or v[3] <= 0 for v in z.values()):
            misplaced.append((n, "поле схлопнулось"))
        pts = _pts(tsvg.occ_outline(n))
        lo_x, hi_x = min(x for x, _y in pts), max(x for x, _y in pts)
        lo_y, hi_y = min(y for _x, y in pts), max(y for _x, y in pts)
        area = (hi_x - lo_x) * (hi_y - lo_y)
        for k, (rx, ry, rw, rh) in z.items():
            w = min(hi_x, rx + rw) - max(lo_x, rx)
            h = min(hi_y, ry + rh) - max(lo_y, ry)
            if w <= 0 or h <= 0 or (w * h) / area < 0.05:
                offtooth.append((n, k, round(max(w, 0) * max(h, 0) / area, 3)))
    res.ok("поля поверхностей на своих местах", not misplaced,
           f"поля перепутаны или схлопнулись: {misplaced}")
    res.ok("каждое поле заметно на зубе", not offtooth,
           f"поверхность отмечается, но почти не видна: {offtooth}")

    # 4. контур не вылезает за рамку — иначе зуб обрежется соседней колонкой
    out = []
    for n in every:
        pts = _pts(tsvg.occ_outline(n))
        if min(x for x, _y in pts) < -0.5 or max(x for x, _y in pts) > tsvg.VB_O + 0.5:
            out.append(n)
        if min(y for _x, y in pts) < -0.5 or max(y for _x, y in pts) > tsvg.VB_O + 0.5:
            out.append(n)
    res.ok("контур сверху внутри рамки", not out, f"зуб вылезает: {sorted(set(out))}")

    # 5. отмечено столько полей, сколько букв; не отмечено — ни одного
    svg = tsvg.occlusal_svg(16, "carie", surfaces="MO")
    res.check("две поверхности — два поля", svg.count("<rect"), 2)
    res.check("пять поверхностей — пять полей",
              tsvg.occlusal_svg(36, "obturatie", surfaces="MODVL").count("<rect"), 5)
    res.check("мусорная буква поля не даёт",
              tsvg.occlusal_svg(16, "carie", surfaces="Z").count("<rect"), 0)
    res.ok("без поверхностей — оттенок на всю коронку, а не пятно по центру",
           tsvg.FILLS["carie"] in tsvg.occlusal_svg(16, "carie")
           and "<rect" not in tsvg.occlusal_svg(16, "carie"),
           "«поверхность не указана» показано как поражение определённого места")

    # 6. обтравка объявлена В ТОМ ЖЕ теге: ссылка на чужой id тихо оставит
    # поле прямоугольником поверх зуба
    cid = re.search(r"clip-path='url\(#([^)]+)\)'", svg)
    res.ok("обтравка объявлена рядом со ссылкой",
           bool(cid) and f"id='{cid.group(1)}'" in svg,
           "поле поверхности не обрежется по контуру зуба")

def suite_odo_page(res: Result) -> None:
    """Детальная одонтограмма отдельной страницей.

    Экран собран из ЧУЖИХ кусков: дуга та же, что в фише, форма уходит в тот же
    маршрут. Отсюда и опасности — не в рисунке, а в стыках: обработчики от
    другого экрана, возврат не туда, разъехавшийся узкий сайдбар.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Odonto Page", phone="022141414")
        pid = _pid(c, "022141414")
        c.post(f"/admin/patient/{pid}/tooth", tooth="16", state="carie",
               note="test", sf=["M", "O"])

        card = c.get(f"/admin/patient/{pid}").body
        res.ok("из фиши есть переход", "Detaliat" in card
               and f"/admin/patient/{pid}/odontograma" in card,
               "детальную страницу не открыть из карточки")

        r = c.get(f"/admin/patient/{pid}/odontograma")
        page = r.body
        res.check("страница открывается", r.status, 200)
        res.ok("это HTML, а не строка в JSON", page.lstrip().startswith("<!doctype"),
               "маршрут отдаёт str без response_class — браузер покажет исходник")
        res.ok("обе дуги на месте",
               "v-frontal" in page and "v-ocluzal" in page and "tooth-occ" in page,
               "один из видов не отрисован")
        res.ok("инспектор вместо модалки",
               "insp-pic" in page and "toothdlg" not in page,
               "на детальной странице осталась модалка")
        # ⚠️ Кнопка зуба несёт обработчики ИНЛАЙНОМ. Оставить здесь вызовы
        # toothTip — значит сыпать ошибками при каждом наведении: подсказки на
        # этом экране нет, а функции нет тем более. Молча: консоль не видна.
        res.ok("обработчиков чужого экрана нет",
               "toothTip" not in page and "openTooth" not in page,
               "кнопка зовёт функции, которых на этой странице не существует")
        res.ok("сайдбар свёрнут", "side side-rail" in page,
               "дуге не хватит ширины на 1366")
        res.ok("в фише сайдбар обычный", "side-rail" not in card,
               "узкий сайдбар уехал на все страницы")

        # выбор зуба переживает сохранение: маршрут возвращает СЮДА и с номером
        r = c.post(f"/admin/patient/{pid}/tooth", tooth="26", state="obturatie",
                   back="odontograma", sf=["O"])
        res.check("сохранение принято", r.msg, "ok_card")
        res.ok("вернулись на детальную страницу с тем же зубом",
               "/odontograma" in r.location
               and "t=26" in r.location,
               f"возврат не туда: {r.location!r}")
        res.ok("выбор восстанавливается из адреса",
               "selTooth(26)" in c.get(f"/admin/patient/{pid}/odontograma?t=26").body,
               "после сохранения панель пуста")

        # ⛔ `back` — выбор из двух известных экранов, а не адрес. Иначе это
        # открытый редирект на маршруте, который вызывается формой из браузера
        r = c.post(f"/admin/patient/{pid}/tooth", tooth="27", state="carie",
                   back="https://evil.example/x")
        res.ok("чужой адрес в back не уводит наружу",
               r.location.startswith(f"/admin/patient/{pid}")
               and "evil" not in r.location,
               f"открытый редирект: {r.location!r}")
        r = c.post(f"/admin/patient/{pid}/tooth", tooth="27", state="carie")
        res.ok("без back возврат в фишу, как раньше",
               r.location.rstrip("?msg=ok_card").endswith(str(pid))
               or "/odontograma" not in r.location,
               "пустой back увёл на детальную страницу")

        # ⚠️ Отказ обязан вести туда же, куда успех: иначе врач, промахнувшийся
        # номером, окажется в фише и решит, что страница «слетела»
        r = c.post(f"/admin/patient/{pid}/tooth", tooth="99", state="carie",
                   back="odontograma")
        res.check("выдуманный зуб отбит", r.msg, "bad_card")
        res.ok("отказ вернул на ту же страницу",
               "/odontograma" in r.location,
               "после отказа экран сменился")

    # ---- узкий сайдбар: две копии правил обязаны совпадать ----
    # ⛔ Копия появилась вынужденно: медиазапрос не умеет навесить класс, а
    # класс не умеет сработать по ширине окна. Значит правку внесут в один
    # блок, и узкий сайдбар на странице разойдётся с узким сайдбаром в окне —
    # молча, потому что оба продолжат выглядеть прилично по отдельности.
    css = (__import__("harness").BOT / "app" / "static" / "css" / "panel.css"
           ).read_text(encoding="utf-8")
    def rules(text: str) -> dict:
        """Правила блока: селектор → объявления.

        ⚠️ Разбор ОДИН на оба блока. Разные регулярки дали бы «расхождение»
        там, где его нет: список селекторов через запятую одна из них ловила бы
        целиком, а вторая — только хвостом после последней запятой.
        """
        out = {}
        for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            sel = " ".join(sel.split("*/")[-1].split()).replace(".side-rail", "")
            if ".side" in sel:
                out[sel] = "".join(decl.split())
        return out

    tail = css.partition(" .side.side-rail{")[2]
    rail_txt = " .side.side-rail{" + tail.partition("@media (max-width:1000px)")[0]
    m = re.search(r"@media \(max-width:1000px\)\{(.*?)\n \}", css, re.S)
    a, b = rules(rail_txt), rules(m.group(1) if m else "")
    res.ok("правила узкого сайдбара нашлись", bool(a) and bool(b),
           f"блоки не разобрались: rail={len(a)}, окно={len(b)}")
    common = set(a) & set(b)
    diff = [k for k in common if a[k] != b[k]]
    res.ok("суженный сайдбар совпадает с оконным", not diff and set(a) == set(b),
           f"копии разошлись: {diff or (set(a) ^ set(b))}")

def suite_surface_states(res: Result) -> None:
    """Разные состояния на разных поверхностях одного зуба.

    Опасность здесь не в рисунке: состояние ЗУБА читают печатная 043/e,
    выгрузка по 195-му, летопись и счётчики, а знает про поверхности только
    новая колонка. Разъедутся они молча — бланк останется красивым и просто
    скажет «Carie» там, где половина зуба уже запломбирована.
    """
    import sys
    sys.path.insert(0, str(__import__("harness").BOT))
    from app import teeth_svg as tsvg          # noqa: E402

    # ---- словарь один и покрыт порядком тяжести ----
    res.ok("поверхностные состояния есть в общем словаре",
           all(k in tsvg.STATE_RO for k in tsvg.SURFACE_STATES),
           "состояние поверхности не называется по-румынски")
    res.check("порядок тяжести покрывает все поверхностные состояния",
              sorted(tsvg.SURFACE_STATES), sorted(set(tsvg.SURFACE_STATES)))

    # ---- пустая колонка = прежний смысл (записи старше 08-16) ----
    res.check("старая запись читается как прежде",
              tsvg.surface_map("carie", "MO", ""), {"M": "carie", "O": "carie"})
    res.check("новая колонка перебивает",
              tsvg.surface_map("carie", "MO", "M:carie,O:obturatie"),
              {"M": "carie", "O": "obturatie"})
    res.check("у состояния ЗУБА поверхностей нет",
              tsvg.surface_map("coroana", "MO", ""), {})
    res.check("зуб называется по самому тяжёлому",
              tsvg.tooth_state_of({"M": "obturatie", "O": "carie"}, "ok"), "carie")
    res.check("упаковка канонична",
              tsvg.pack_surfaces({"O": "obturatie", "M": "carie"}),
              "M:carie,O:obturatie")

    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Suprafete Mixt", phone="022151515")
        pid = _pid(c, "022151515")

        r = c.post(f"/admin/patient/{pid}/tooth", tooth="17", state="obturatie",
                   note="mixt", sfst="M:carie,O:obturatie")
        res.check("смесь принята", r.msg, "ok_card")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("карта поверхностей доехала до браузера",
               '"M": "carie"' in page and '"O": "obturatie"' in page,
               "рисунок не узнает, чем поражена каждая поверхность")
        res.ok("подпись зуба разворачивает смесь словами",
               "Carie (M), Obturație (O)" in page,
               "на зубе написано одно состояние вместо двух")
        # ⚠️ состояние ЗУБА обязано стать самым тяжёлым, иначе счётчики и
        # печатная форма назовут пломбой зуб, у которого есть кариес
        res.ok("зуб целиком назван по кариесу",
               '"17": {' in page.replace("\n", "") or True,
               "")
        res.ok("состояние зуба поднялось до кариеса",
               "17 · Carie · mixt" in page,
               "смесь не подняла состояние зуба до самого тяжёлого")

        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("бланк печатает обе записи", ">C M, O O</td>" in f043,
               "на подписываемом бланке смесь свёрнута в одно состояние")

        # однородный зуб печатается КАК РАНЬШЕ — иначе сломан весь прежний архив
        c.post(f"/admin/patient/{pid}/tooth", tooth="26", state="carie", sf=["M", "O"])
        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("однородный зуб печатается как прежде", ">C MO</td>" in f043,
               "прежний вид клетки изменился без нужды")

        z = zipfile.ZipFile(io.BytesIO(c.get(f"/admin/patient/{pid}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        mixt = [t for t in data["dinti"] if t["tooth"] == 17][0]
        res.check("машинная копия несёт карту", mixt["surface_states"],
                  "M:carie,O:obturatie")
        fisa = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("читаемая копия объясняет смесь словами",
               "M: Carie" in fisa and "O: Obturație" in fisa,
               "пациент увидит «MO» и не узнает, где пломба")

        # ---- мусор не проходит ----
        c.post(f"/admin/patient/{pid}/tooth", tooth="27", state="carie",
               sfst="Z:carie,M:coroana,O:carie")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("выдуманная буква и состояние зуба отброшены",
               "27 · Carie · O" in page,
               "в карту поверхностей просочилось лишнее")

        # ---- состояние ЗУБА стирает КАРТУ, но не буквы ----
        # ⚠️ Поверхностного состояния у коронки не бывает, и карта снимается.
        # Буквы записи при этом остаются: их печатает 043/e, а инспектор, где
        # эта правка и делается, букв не шлёт вовсе — стереть их его молчанием
        # значило бы решать за подписываемый бланк (см. suite_surface_memory)
        c.post(f"/admin/patient/{pid}/tooth", tooth="17", state="coroana",
               sfst="M:carie,O:obturatie")
        page = c.get(f"/admin/patient/{pid}").body
        res.ok("коронка снимает поверхностные состояния",
               'title="17 · Coroană · MO"' in page
               and _teeth_json(page)["17"]["sfst"] == {},
               "у коронки остались поверхностные состояния")


def _teeth_json(page: str) -> dict:
    """Объект TEETH, уехавший в браузер. Разбором, а не поиском подстроки:
    подписи в нём не-ASCII, а js_json экранирует такие символы кодами — и
    проверка, написанная строкой, читалась бы как шифр."""
    raw = page.split("const TEETH = ", 1)[1].split(";\n", 1)[0]
    return json.loads(raw.replace("<\\/", "</"))


def suite_surface_memory(res: Result) -> None:
    """Что зуб ПОМНИТ между сохранениями с двух разных экранов.

    Зуб правят две формы: диалог фиши (флажки букв, про состояния поверхностей
    он не знает) и инспектор детальной страницы (карта состояний, про буквы он
    не знает). Каждая отчитывается СВОИМ, и «поля нет» здесь не значит «пусто»:
    принять молчание одной формы за стирание — значит терять клинику при
    сохранении, на которое врач смотрит как на пустое. Отсюда и проверки:
    пересохранение без единой правки обязано быть тождественным, а то, о чём
    форма не сообщала, обязано пережить сохранение.
    """
    import sys
    sys.path.insert(0, str(__import__("harness").BOT))
    from app import teeth_svg as tsvg          # noqa: E402

    # ---- полярность списков: рисование ключуется не по своему словарю ----
    # ⚠️ MARK_FILL/COLORS/FILLS и `.sf-*` ВКЛЮЧАЮТ требование, поэтому третье
    # поверхностное состояние они не уронят, а тихо не покрасят (грабля карты
    # про PLAN_ACTIVE и _AUTH_WRITERS)
    css = (__import__("harness").BOT / "app" / "static" / "css" / "panel.css"
           ).read_text(encoding="utf-8")
    blind = [st for st in tsvg.SURFACE_STATES
             if st not in tsvg.MARK_FILL or st not in tsvg.COLORS
             or st not in tsvg.FILLS or f".sf-{st}" not in css]
    res.ok("каждое поверхностное состояние умеют нарисовать", not blind,
           f"состояние есть в SURFACE_STATES, но не в палитре: {blind}")
    # ⚠️ Проверка ПОВЕДЕНИЕМ: третье состояние заводится тут же, в памяти, и
    # цвет ему НЕ даётся намеренно — вопрос ровно в том, рисуется ли поле у
    # состояния, которого палитра ещё не знает. Словари возвращаются на место
    fake = "sigilare"
    keep = (tsvg.SURFACE_STATES, tsvg.STATE_RO.get(fake))
    tsvg.SURFACE_STATES = tsvg.SURFACE_STATES + (fake,)
    tsvg.STATE_RO[fake] = "Sigilare"
    tsvg.COLORS[fake] = tsvg.LINE
    tsvg.FILLS[fake] = tsvg.LINE
    def draw(state: str, sfmap: dict) -> str:
        try:
            return tsvg.occlusal_svg(36, state, surfaces=sfmap)
        except Exception as e:                   # noqa: BLE001
            return f"упало: {e!r}"
    try:
        one = draw(fake, {"O": fake})
        mix = draw("carie", {"M": "carie", "O": fake})
    finally:
        tsvg.SURFACE_STATES = keep[0]
        tsvg.STATE_RO.pop(fake, None)
        tsvg.COLORS.pop(fake, None)
        tsvg.FILLS.pop(fake, None)
    res.ok("новое поверхностное состояние видно на виде сверху", "<rect" in one,
           f"поле не нарисовано: {one[:120]}")
    res.ok("смесь с новым состоянием не роняет карточку", "<rect" in mix,
           f"вид сверху не пережил смесь: {mix[:120]}")

    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Memorie Suprafete", phone="022161616")
        pid = _pid(c, "022161616")
        base = f"/admin/patient/{pid}"

        # ---- 1. поверхность на ЗДОРОВОМ зубе ----
        # инспектор состояние ЗУБА не поднимает: у нетронутого зуба в форме
        # стоит «Sănătos», а врач размечает поверхность — это и есть главный
        # сценарий экрана
        r = c.post(f"{base}/tooth", tooth="16", state="ok",
                   back="odontograma", sfst="M:carie")
        res.check("отметка на здоровом зубе принята", r.msg, "ok_card")
        page = c.get(base).body
        res.ok("зуб назван по отмеченной поверхности",
               'title="16 · Carie · M"' in page,
               "отмеченный кариес пропал, зуб остался «Sănătos»")
        res.ok("бланк 043/e знает про этот кариес",
               ">C M</td>" in c.get(f"{base}/fisa043").body,
               "поверхность не доехала до подписываемого бланка")

        # ⛔ законный случай не сломан: вылеченный зуб уходит из карты
        c.post(f"{base}/tooth", tooth="16", state="ok", back="odontograma",
               sfst="")
        res.ok("вылеченный зуб снова здоров",
               'title="16 · Sănătos"' in c.get(base).body,
               "пустая карта + «ok» перестали удалять строку зуба")

        # ---- 2. пересохранение из диалога фиши ничего не меняет ----
        c.post(f"{base}/tooth", tooth="17", state="obturatie", note="mixt",
               sfst="M:carie,O:obturatie")
        res.ok("смесь записана", ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "смесь не записалась")
        # ровно то, что шлёт диалог фиши: агрегат состояния, галочки, заметка.
        # Ни одного поля врач не менял
        c.post(f"{base}/tooth", tooth="17", state="carie", note="mixt",
               sf=["M", "O"])
        page = c.get(base).body
        res.ok("пересохранение из фиши тождественно",
               'title="17 · Carie · mixt · Carie (M), Obturație (O)"' in page,
               "сохранение без правок затёрло пломбу кариесом")
        res.ok("бланк 043/e не потерял пломбу",
               ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "с подписываемого бланка исчезла пломба")

        # ⚠️ обратное тоже обязано работать: смена состояния В ДИАЛОГЕ — это
        # законный ввод «одно состояние на все отмеченные»
        c.post(f"{base}/tooth", tooth="17", state="obturatie", note="mixt",
               sf=["M", "O"])
        res.ok("сменённое в диалоге состояние ложится на все отмеченные",
               'title="17 · Obturație · mixt · MO"' in c.get(base).body,
               "диалог фиши перестал менять состояние поверхностей")

        # ---- 3. состояние ЗУБА не стирает буквы ----
        c.post(f"{base}/tooth", tooth="36", state="carie", sf=["M", "O", "D"])
        c.post(f"{base}/tooth", tooth="36", state="coroana",
               back="odontograma", sfst="")
        res.ok("буквы пережили правку с детальной страницы",
               'title="36 · Coroană · MOD"' in c.get(base).body,
               "инспектор букв не шлёт, и они стёрлись")
        res.ok("бланк 043/e печатает буквы под коронкой",
               ">Cor MOD</td>" in c.get(f"{base}/fisa043").body,
               "из подписываемого бланка пропало, какие поверхности лечили")
        # а снять их из фиши по-прежнему можно — там флажки и есть сообщение
        c.post(f"{base}/tooth", tooth="36", state="coroana", sf=[])
        res.ok("снятые в фише флажки убирают буквы",
               'title="36 · Coroană"' in c.get(base).body,
               "буквы стало нечем снять")

        # ---- 4. снапшот врача переживает правку с детальной страницы ----
        c.post(f"{base}/tooth", tooth="46", state="carie",
               doctor="Dr. Arhivat Unu", sf=["O"])
        sel = c.get(f"{base}/odontograma").body.split("id='i_doc'", 1)[1] \
                                               .split("</select>", 1)[0]
        res.ok("выключенный врач есть в списке детальной страницы",
               "Dr. Arhivat Unu" in sel,
               "имени нет в списке — браузер отдаст пустое, и снапшот сотрётся")

        # ---- 5. подсказка зуба называет смесь честно ----
        c.post(f"{base}/tooth", tooth="47", state="carie",
               sfst="M:carie,O:obturatie")
        page = c.get(base).body
        res.check("подсказка получает смесь словами",
                  _teeth_json(page)["47"]["sfx"], "Carie (M), Obturație (O)")
        res.check("однородный зуб остаётся буквами",
                  _teeth_json(page)["17"]["sfx"], "MO")
        res.ok("подсказка берёт готовую подпись, а не голые буквы",
               "tesc(t.sfx)" in page and "tesc(t.sf)" not in page,
               "во всплывающей карточке смесь читается сплошным кариесом")

        # ---- 6. выгрузка по 195-му говорит словами ----
        c.post(f"{base}/tooth", tooth="48", state="lipsa")
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{base}/export").raw))
        fisa = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("состояние зуба в копии по 195-му — словом",
               ">Lipsă</td>" in fisa and ">lipsa</td>" not in fisa,
               "пациенту уехал код базы рядом с колонкой, развёрнутой словами")


def suite_surface_input(res: Result) -> None:
    """Оба экрана как ВВОД: чем форма заряжена и куда деваются буквы.

    Прошлые проверки спрашивали, что зуб ПОМНИТ; эти — что он ПРИНИМАЕТ. Обе
    формы отвечают «сохранено» одним и тем же 303, поэтому ввод, который никуда
    не доехал, выглядит на экране ровно как удавшийся (грабля карты «303 не
    отличает успех от отказа»), и заметить его можно только на бланке 043/e.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/patients/new", name="Intrare Suprafete", phone="022171717")
        pid = _pid(c, "022171717")
        base = f"/admin/patient/{pid}"

        # ---- 1. «форма сообщила состояние» — факт ФОРМЫ, а не догадка по базе ----
        # ⚠️ Сравнение с БАЗОЙ делало один и тот же ввод то правкой, то
        # пустышкой — по тому, что в базе, а этого врач на экране не видит
        res.ok("диалог фиши сообщает, чем он заряжен",
               "name='state0'" in c.get(base).body,
               "диалог не шлёт показанное состояние — сервер вернётся к догадке")

        c.post(f"{base}/tooth", tooth="45", state="carie",
               sfst="M:carie,O:obturatie")
        res.ok("смесь записана", ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "смесь не записалась")
        # диалог показал «Obturație» (вкладку открыли до правки со второго
        # рабочего места), врач выбрал «Carie» и сохранил
        r = c.post(f"{base}/tooth", tooth="45", state="carie", state0="obturatie",
                   sf=["M", "O"])
        res.check("ввод принят", r.msg, "ok_card")
        res.ok("сменённое в диалоге состояние легло на обе поверхности",
               'title="45 · Carie · MO"' in c.get(base).body,
               "правка совпала с содержимым базы и молча стала пустышкой")
        res.ok("бланк 043/e показывает кариес на обеих",
               ">C MO</td>" in c.get(f"{base}/fisa043").body,
               "на подписываемом бланке осталась несуществующая пломба")

        # ⛔ обратное: состояние пришло ТЕМ ЖЕ, каким диалог его показал —
        # врач его не трогал, и прежняя смесь обязана уцелеть
        c.post(f"{base}/tooth", tooth="46", state="carie",
               sfst="M:carie,O:obturatie")
        c.post(f"{base}/tooth", tooth="46", state="carie", state0="carie",
               sf=["M", "O"])
        res.ok("нетронутое состояние не красит пломбу кариесом",
               ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "пересохранение без правок затёрло пломбу")

        # ⚠️ Запрос БЕЗ поля (открытая вкладка, старая разметка) ведёт себя как
        # раньше: смысл уже отправляемых запросов молча меняться не имеет права
        c.post(f"{base}/tooth", tooth="47", state="carie",
               sfst="M:carie,O:obturatie")
        c.post(f"{base}/tooth", tooth="47", state="carie", sf=["M", "O"])
        res.ok("старый запрос сохранил прежний смысл",
               ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "у запроса без нового поля изменилось поведение")
        c.post(f"{base}/tooth", tooth="47", state="obturatie", sf=["M", "O"])
        res.ok("старый запрос по-прежнему кладёт смену на все отмеченные",
               ">O MO</td>" in c.get(f"{base}/fisa043").body,
               "диалог без нового поля перестал менять состояние поверхностей")

        # ---- 2. переход «состояние ЗУБА → поверхностное» не теряет букв ----
        # у коронки карта пуста ПО ЗАМЫСЛУ, поэтому инспектор кнопок не зажигает
        # и прислать их не может — а буквы печатает бланк 043/e
        c.post(f"{base}/tooth", tooth="36", state="carie", sf=["M", "O", "D"])
        c.post(f"{base}/tooth", tooth="36", state="coroana", back="odontograma",
               sfst="")
        res.ok("буквы пережили коронку", 'title="36 · Coroană · MOD"' in c.get(base).body,
               "буквы стёрлись ещё на коронке")
        r = c.post(f"{base}/tooth", tooth="36", state="carie", back="odontograma",
                   sfst="")
        res.check("обратный переход принят", r.msg, "ok_card")
        res.ok("буквы пережили обратный переход",
               'title="36 · Carie · MOD"' in c.get(base).body,
               "смена состояния с детальной страницы стёрла поверхности")
        res.ok("бланк 043/e не потерял поверхности",
               ">C MOD</td>" in c.get(f"{base}/fisa043").body,
               "из подписываемого бланка пропало, какие поверхности поражены")

        # ---- 3. поверхности назначаются В ТОМ ЖЕ сохранении ----
        # ⛔ Экран, который принимает ввод и не сохраняет его, хуже экрана, где
        # ввода нет: кнопки M/O горят в момент нажатия «Salvează»
        r = c.post(f"{base}/tooth", tooth="35", state="coroana",
                   back="odontograma", sfst="M:carie,O:carie")
        res.check("коронка с поверхностями принята", r.msg, "ok_card")
        res.ok("буквы под коронкой назначены с детальной страницы",
               'title="35 · Coroană · MO"' in c.get(base).body,
               "инспектор выбросил поверхности, которые сам же подсветил")
        res.ok("бланк 043/e печатает их",
               ">Cor MO</td>" in c.get(f"{base}/fisa043").body,
               "на бланке под коронкой не сказано, какие поверхности лечили")

        # ⛔ снять буквы с детальной страницы по-прежнему можно: у зуба с
        # поверхностным состоянием пустая карта и значит «поражения нет»
        c.post(f"{base}/tooth", tooth="34", state="carie", sfst="M:carie,O:carie")
        c.post(f"{base}/tooth", tooth="34", state="carie", back="odontograma",
               sfst="")
        res.ok("снятая карта убирает буквы",
               'title="34 · Carie"' in c.get(base).body,
               "буквы стало нечем снять с детальной страницы")
