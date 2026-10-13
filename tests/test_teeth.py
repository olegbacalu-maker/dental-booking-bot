"""Одонтограмма: поверхности зуба (M/O/D/V/L) и молочный прикус.

Формула — единственное место, где клиника рисует диагноз картинкой, и ломается
она молча: ответ 200, а зуб просто не тот. Поэтому здесь проверяется не
«запись прошла», а что состояние доехало до ТРЁХ представлений: экран (модель
JSON API, которую рисует React; до 13.10 — старые страницы, карточка фиши и
детальная одонтограмма), печатная 043/e и выгрузка по 195-му. Сам экран —
флажки, инспектор, переключатель вида — держат проверки клиента (vitest).
"""
import io
import json
import re
import zipfile
from datetime import date, timedelta

from harness import Client, Result, Server, clinic_today, pid_by_phone, shell_model


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


def _pid(c: Client, phone: str) -> str:
    return str(pid_by_phone(c, phone))


def _odo(c: Client, pid) -> dict:
    """Одонтограмма данными (`GET /api/patients/{pid}/odontogram`) — то, что
    рисует экран: зубы с подписями и рисунками, история, мосты, легенда."""
    return json.loads(c.get(f"/api/patients/{pid}/odontogram").body)["data"]


def _title(c: Client, pid, n: int) -> str:
    """Подпись зуба словами — та, что на кнопке и в подсказке."""
    return _odo(c, pid)["teeth"][str(n)]["title"]


def _feed(c: Client, pid) -> list[str]:
    """Тексты летописи фиши (`GET …/activity`: лента без записи о просмотре)."""
    r = c.get(f"/api/patients/{pid}/activity")
    return [a["text"] for a in json.loads(r.body)["data"]["items"]]


def suite_surfaces(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Suprafete Test", "phone": "022121212"})
        pid = _pid(c, "022121212")

        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "obturatie",
                                                         "note": "compozit", "doctor": "d2",
                                                         "surfaces": ["O", "M"]})
        res.check("поверхности сохраняются", r.msg, "ok_card")

        odo = _odo(c, pid)
        t26 = odo["teeth"]["26"]
        # ⚠️ порядок канонический MODVL, а не порядок галочек: «OM» и «MO» —
        # одно и то же, и в карте, и на печати это обязано читаться одинаково
        res.check("поверхности нормализованы в MO", t26["sf"], "MO")
        res.check("подпись зуба не потеряла прежний формат",
                  t26["title"], "26 · Obturație · compozit · MO")
        res.check("словарь поверхностей уезжает экрану (выбор поверхностей)",
                  (odo["surfaces"].get("O"), list(odo["surfaces"])),
                  ("ocluzal", ["M", "O", "D", "V", "L"]))
        res.ok("у зуба оба вида рисунка — лицевой и сверху",
               "<svg" in t26["svg"]["frontal"] and "<svg" in t26["svg"]["occlusal"]
               and t26["svg"]["frontal"] != t26["svg"]["occlusal"],
               "один из видов не отрисован")

        res.check("выдуманная поверхность отбрасывается",
                  c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie",
                                                               "surfaces": ["Z", "D"]}).msg, "ok_card")
        res.check("осталась только настоящая буква", _odo(c, pid)["teeth"]["26"]["sf"], "D")

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
        c.post_json(f"/api/patients/{pid}/teeth/11", {"state": "carie", "surfaces": []})
        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("зуб без поверхностей — только код", ">C</td>" in f043,
               "пустые поверхности замусорили клетку")


def suite_milk(res: Result) -> None:
    """Молочный прикус: номера 51-55/61-65/71-75/81-85."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Copil Test", "phone": "022131313"})
        pid = _pid(c, "022131313")

        odo = _odo(c, pid)
        res.check("молочная дуга уезжает экрану: обе челюсти и зубы в карте",
                  (odo["arches"]["milk_upper"][:2], odo["arches"]["milk_lower"][-1],
                   odo["teeth"]["54"]["milk"]), ([55, 54], 75, True))
        res.check("у взрослой фиши она свёрнута", odo["milk_open"], False)

        r = c.post_json(f"/api/patients/{pid}/teeth/54", {"state": "carie", "note": "lapte",
                                                         "doctor": "d2", "surfaces": []})
        res.check("молочный зуб принимается", r.msg, "ok_card")
        odo = _odo(c, pid)
        res.check("состояние молочного зуба видно", odo["teeth"]["54"]["title"], "54 · Carie · lapte")
        res.check("с записями молочный ряд раскрыт сам", odo["milk_open"], True)

        res.check("несуществующий номер отбит",
                  c.post_json(f"/api/patients/{pid}/teeth/99", {"state": "carie", "surfaces": []}).msg, "bad_card")
        r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Obturație 54",
                                                     "tooth": "54", "price": "300"})
        res.check("молочный зуб выбирается в плане лечения", (r.status, r.msg), (200, "ok_card"))
        res.check("в плане номер молочного зуба сохранён",
                  [it["tooth"] for it in json.loads(r.body)["data"]["plan"]["items"]], [54])

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

    С 13.10 это экран React (как и вкладка фиши): сервер отдаёт рамку с узким
    сайдбаром и номером зуба из адреса, данные — один и тот же JSON API. До
    этого стыки старых страниц (обработчики чужого экрана, возврат формы с
    `back`, открытый редирект по нему) проверялись здесь же — они ушли вместе с
    формой; узкий сайдбар остался.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Odonto Page", "phone": "022141414"})
        pid = _pid(c, "022141414")
        c.post_json(f"/api/patients/{pid}/teeth/16", {"state": "carie", "note": "test",
                                                     "surfaces": ["M", "O"]})

        card = c.get(f"/admin/patient/{pid}").body
        r = c.get(f"/admin/patient/{pid}/odontograma")
        page = r.body
        res.check("страница открывается", r.status, 200)
        res.ok("это HTML, а не строка в JSON", page.lstrip().startswith("<!doctype"),
               "маршрут отдаёт str без response_class — браузер покажет исходник")
        t16 = _odo(c, pid)["teeth"]["16"]
        res.ok("у зуба оба вида рисунка",
               "<svg" in t16["svg"]["frontal"] and "<svg" in t16["svg"]["occlusal"],
               "один из видов не отрисован")
        # ⭐ B1: сайдбар рисует React по модели оболочки — флаг узкого в ней
        res.check("сайдбар свёрнут", shell_model(page)["frame"]["rail"], True)
        res.check("в фише сайдбар обычный", shell_model(card)["frame"]["rail"], False)

        # выбор зуба переживает сохранение: экран кладёт номер в адрес, сервер
        # отдаёт его узлу параметром
        r = c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "obturatie",
                                                         "surfaces": ["O"]})
        res.check("сохранение принято", r.msg, "ok_card")
        res.ok("выбор восстанавливается из адреса",
               "&quot;t&quot;: &quot;26&quot;" in c.get(f"/admin/patient/{pid}/odontograma?t=26").body,
               "номер зуба из адреса не доехал до экрана")
        r = c.post_json(f"/api/patients/{pid}/teeth/99", {"state": "carie", "surfaces": []})
        res.check("выдуманный зуб отбит", (r.status, r.msg), (422, "bad_card"))

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
        c.post_json("/api/patients", {"name": "Suprafete Mixt", "phone": "022151515"})
        pid = _pid(c, "022151515")

        r = c.post_json(f"/api/patients/{pid}/teeth/17", {"state": "obturatie", "note": "mixt",
                                                         "surfaces": {"M": "carie", "O": "obturatie"}})
        res.check("смесь принята", r.msg, "ok_card")
        t17 = _odo(c, pid)["teeth"]["17"]
        res.check("карта поверхностей доехала до экрана",
                  t17["sfst"], {"M": "carie", "O": "obturatie"})
        res.check("подпись зуба разворачивает смесь словами",
                  t17["sfx"], "Carie (M), Obturație (O)")
        # ⚠️ состояние ЗУБА обязано стать самым тяжёлым, иначе счётчики и
        # печатная форма назовут пломбой зуб, у которого есть кариес
        res.check("зуб целиком назван по кариесу", t17["state"], "carie")
        res.ok("состояние зуба поднялось до кариеса",
               t17["title"].startswith("17 · Carie · mixt"),
               f"смесь не подняла состояние зуба до самого тяжёлого: {t17['title']!r}")

        f043 = c.get(f"/admin/patient/{pid}/fisa043").body
        res.ok("бланк печатает обе записи", ">C M, O O</td>" in f043,
               "на подписываемом бланке смесь свёрнута в одно состояние")

        # однородный зуб печатается КАК РАНЬШЕ — иначе сломан весь прежний архив
        c.post_json(f"/api/patients/{pid}/teeth/26", {"state": "carie", "surfaces": ["M", "O"]})
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
        c.post_json(f"/api/patients/{pid}/teeth/27", {"state": "carie",
                                                     "surfaces": {"Z": "carie", "M": "coroana", "O": "carie"}})
        res.check("выдуманная буква и состояние зуба отброшены",
                  _title(c, pid, 27), "27 · Carie · O")

        # ---- состояние ЗУБА стирает КАРТУ, но не буквы ----
        # ⚠️ Поверхностного состояния у коронки не бывает, и карта снимается.
        # Буквы записи при этом остаются: их печатает 043/e, а инспектор, где
        # эта правка и делается, букв не шлёт вовсе — стереть их его молчанием
        # значило бы решать за подписываемый бланк (см. suite_surface_memory)
        c.post_json(f"/api/patients/{pid}/teeth/17", {"state": "coroana",
                                                     "surfaces": {"M": "carie", "O": "obturatie"}})
        t17 = _odo(c, pid)["teeth"]["17"]
        res.check("коронка снимает поверхностные состояния",
                  (t17["title"], t17["sfst"]), ("17 · Coroană · MO", {}))


def suite_surface_memory(res: Result) -> None:
    """Что зуб ПОМНИТ между сохранениями двумя словарями поверхностей.

    Запись принимает поверхности буквами (так слал диалог старой фиши, снятой
    13.10; путь остался в контракте API) и картой состояний (её шлёт панель
    React, как слал инспектор детальной страницы). Каждый словарь отчитывается
    СВОИМ, и «поля нет» здесь не значит «пусто»:
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
        c.post_json("/api/patients", {"name": "Memorie Suprafete", "phone": "022161616"})
        pid = _pid(c, "022161616")
        base = f"/admin/patient/{pid}"
        api = f"/api/patients/{pid}"

        # ---- 1. поверхность на ЗДОРОВОМ зубе ----
        # инспектор состояние ЗУБА не поднимает: у нетронутого зуба в форме
        # стоит «Sănătos», а врач размечает поверхность — это и есть главный
        # сценарий экрана
        r = c.post_json(f"{api}/teeth/16", {"state": "ok", "surfaces": {"M": "carie"}})
        res.check("отметка на здоровом зубе принята", r.msg, "ok_card")
        res.check("зуб назван по отмеченной поверхности", _title(c, pid, 16), "16 · Carie · M")
        res.ok("бланк 043/e знает про этот кариес",
               ">C M</td>" in c.get(f"{base}/fisa043").body,
               "поверхность не доехала до подписываемого бланка")

        # ⛔ законный случай не сломан: вылеченный зуб уходит из карты
        c.post_json(f"{api}/teeth/16", {"state": "ok", "surfaces": {}})
        res.check("вылеченный зуб снова здоров", _title(c, pid, 16), "16 · Sănătos")

        # ---- 2. пересохранение из диалога фиши ничего не меняет ----
        c.post_json(f"{api}/teeth/17", {"state": "obturatie", "note": "mixt",
                                       "surfaces": {"M": "carie", "O": "obturatie"}})
        res.ok("смесь записана", ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "смесь не записалась")
        # ровно то, что шлёт диалог фиши: агрегат состояния, галочки, заметка.
        # Ни одного поля врач не менял
        c.post_json(f"{api}/teeth/17", {"state": "carie", "note": "mixt", "surfaces": ["M", "O"]})
        res.check("пересохранение буквами тождественно",
                  _title(c, pid, 17), "17 · Carie · mixt · Carie (M), Obturație (O)")
        res.ok("бланк 043/e не потерял пломбу",
               ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "с подписываемого бланка исчезла пломба")

        # ⚠️ обратное тоже обязано работать: смена состояния В ДИАЛОГЕ — это
        # законный ввод «одно состояние на все отмеченные»
        c.post_json(f"{api}/teeth/17", {"state": "obturatie", "note": "mixt",
                                       "surfaces": ["M", "O"]})
        res.check("сменённое состояние ложится на все отмеченные буквы",
                  _title(c, pid, 17), "17 · Obturație · mixt · MO")

        # ---- 3. состояние ЗУБА не стирает буквы ----
        c.post_json(f"{api}/teeth/36", {"state": "carie", "surfaces": ["M", "O", "D"]})
        c.post_json(f"{api}/teeth/36", {"state": "coroana", "surfaces": {}})
        res.check("буквы пережили правку картой (панель букв не шлёт)",
                  _title(c, pid, 36), "36 · Coroană · MOD")
        res.ok("бланк 043/e печатает буквы под коронкой",
               ">Cor MOD</td>" in c.get(f"{base}/fisa043").body,
               "из подписываемого бланка пропало, какие поверхности лечили")
        # а снять их из фиши по-прежнему можно — там флажки и есть сообщение
        c.post_json(f"{api}/teeth/36", {"state": "coroana", "surfaces": []})
        res.check("пустой список букв их снимает", _title(c, pid, 36), "36 · Coroană")

        # ---- 4. снапшот врача переживает правку с детальной страницы ----
        c.post_json(f"{api}/teeth/46", {"state": "carie", "doctor": "Dr. Arhivat Unu",
                                       "surfaces": ["O"]})
        res.ok("выключенный врач есть в списке врачей экрана",
               "Dr. Arhivat Unu" in _odo(c, pid)["doctors"],
               "имени нет в списке — экран отдаст пустое, и снапшот сотрётся")

        # ---- 5. подсказка зуба называет смесь честно ----
        c.post_json(f"{api}/teeth/47", {"state": "carie",
                                       "surfaces": {"M": "carie", "O": "obturatie"}})
        teeth = _odo(c, pid)["teeth"]
        res.check("подсказка получает смесь словами", teeth["47"]["sfx"], "Carie (M), Obturație (O)")
        res.check("однородный зуб остаётся буквами", teeth["17"]["sfx"], "MO")

        # ---- 6. выгрузка по 195-му говорит словами ----
        c.post_json(f"{api}/teeth/48", {"state": "lipsa", "surfaces": []})
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{base}/export").raw))
        fisa = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("состояние зуба в копии по 195-му — словом",
               ">Lipsă</td>" in fisa and ">lipsa</td>" not in fisa,
               "пациенту уехал код базы рядом с колонкой, развёрнутой словами")


def suite_surface_input(res: Result) -> None:
    """Запись зуба как ВВОД: чем экран заряжен и куда деваются буквы.

    Прошлые проверки спрашивали, что зуб ПОМНИТ; эти — что он ПРИНИМАЕТ. Оба
    словаря отвечают «сохранено» одним кодом, поэтому ввод, который никуда не
    доехал, выглядит на экране ровно как удавшийся (грабля карты «303 не
    отличает успех от отказа» — у JSON та же), и заметить его можно только на
    бланке 043/e. Что экран шлёт `state0` (показанное состояние), держит
    клиент: `useChart` (до 13.10 — поле `state0` старого диалога).
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Intrare Suprafete", "phone": "022171717"})
        pid = _pid(c, "022171717")
        base = f"/admin/patient/{pid}"
        api = f"/api/patients/{pid}"

        # ---- 1. «экран сообщил состояние» — факт ВВОДА, а не догадка по базе ----
        # ⚠️ Сравнение с БАЗОЙ делало один и тот же ввод то правкой, то
        # пустышкой — по тому, что в базе, а этого врач на экране не видит

        c.post_json(f"{api}/teeth/45", {"state": "carie",
                                       "surfaces": {"M": "carie", "O": "obturatie"}})
        res.ok("смесь записана", ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "смесь не записалась")
        # диалог показал «Obturație» (вкладку открыли до правки со второго
        # рабочего места), врач выбрал «Carie» и сохранил
        r = c.post_json(f"{api}/teeth/45", {"state": "carie", "state0": "obturatie",
                                           "surfaces": ["M", "O"]})
        res.check("ввод принят", r.msg, "ok_card")
        res.check("сменённое состояние легло на обе поверхности",
                  _title(c, pid, 45), "45 · Carie · MO")
        res.ok("бланк 043/e показывает кариес на обеих",
               ">C MO</td>" in c.get(f"{base}/fisa043").body,
               "на подписываемом бланке осталась несуществующая пломба")

        # ⛔ обратное: состояние пришло ТЕМ ЖЕ, каким диалог его показал —
        # врач его не трогал, и прежняя смесь обязана уцелеть
        c.post_json(f"{api}/teeth/46", {"state": "carie",
                                       "surfaces": {"M": "carie", "O": "obturatie"}})
        c.post_json(f"{api}/teeth/46", {"state": "carie", "state0": "carie",
                                       "surfaces": ["M", "O"]})
        res.ok("нетронутое состояние не красит пломбу кариесом",
               ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "пересохранение без правок затёрло пломбу")

        # ⚠️ Запрос БЕЗ поля (открытая вкладка, старая разметка) ведёт себя как
        # раньше: смысл уже отправляемых запросов молча меняться не имеет права
        c.post_json(f"{api}/teeth/47", {"state": "carie",
                                       "surfaces": {"M": "carie", "O": "obturatie"}})
        c.post_json(f"{api}/teeth/47", {"state": "carie", "surfaces": ["M", "O"]})
        res.ok("старый запрос сохранил прежний смысл",
               ">C M, O O</td>" in c.get(f"{base}/fisa043").body,
               "у запроса без нового поля изменилось поведение")
        c.post_json(f"{api}/teeth/47", {"state": "obturatie", "surfaces": ["M", "O"]})
        res.ok("старый запрос по-прежнему кладёт смену на все отмеченные",
               ">O MO</td>" in c.get(f"{base}/fisa043").body,
               "диалог без нового поля перестал менять состояние поверхностей")

        # ---- 2. переход «состояние ЗУБА → поверхностное» не теряет букв ----
        # у коронки карта пуста ПО ЗАМЫСЛУ, поэтому инспектор кнопок не зажигает
        # и прислать их не может — а буквы печатает бланк 043/e
        c.post_json(f"{api}/teeth/36", {"state": "carie", "surfaces": ["M", "O", "D"]})
        c.post_json(f"{api}/teeth/36", {"state": "coroana", "surfaces": {}})
        res.check("буквы пережили коронку", _title(c, pid, 36), "36 · Coroană · MOD")
        r = c.post_json(f"{api}/teeth/36", {"state": "carie", "surfaces": {}})
        res.check("обратный переход принят", r.msg, "ok_card")
        res.check("буквы пережили обратный переход", _title(c, pid, 36), "36 · Carie · MOD")
        res.ok("бланк 043/e не потерял поверхности",
               ">C MOD</td>" in c.get(f"{base}/fisa043").body,
               "из подписываемого бланка пропало, какие поверхности поражены")

        # ---- 3. поверхности назначаются В ТОМ ЖЕ сохранении ----
        # ⛔ Экран, который принимает ввод и не сохраняет его, хуже экрана, где
        # ввода нет: кнопки M/O горят в момент нажатия «Salvează»
        r = c.post_json(f"{api}/teeth/35", {"state": "coroana",
                                           "surfaces": {"M": "carie", "O": "carie"}})
        res.check("коронка с поверхностями принята", r.msg, "ok_card")
        res.check("буквы под коронкой назначены картой", _title(c, pid, 35), "35 · Coroană · MO")
        res.ok("бланк 043/e печатает их",
               ">Cor MO</td>" in c.get(f"{base}/fisa043").body,
               "на бланке под коронкой не сказано, какие поверхности лечили")

        # ⛔ снять буквы с детальной страницы по-прежнему можно: у зуба с
        # поверхностным состоянием пустая карта и значит «поражения нет»
        c.post_json(f"{api}/teeth/34", {"state": "carie",
                                       "surfaces": {"M": "carie", "O": "carie"}})
        c.post_json(f"{api}/teeth/34", {"state": "carie", "surfaces": {}})
        res.check("снятая карта убирает буквы", _title(c, pid, 34), "34 · Carie")


def suite_marks(res: Result) -> None:
    """Отметка ПОВЕРХ находки: «кариес и одновременно в работе» (08-17).

    До этого «în tratament» стояло восьмым значением списка состояний, и второй
    выбор молча вытеснял первый: врач ставил кариес, потом лечение — и кариес
    исчезал из фиши, из летописи и с подписываемой 043/e. Колонка была одна,
    значение одно, и «совместить» было нечем. Здесь проверяется не «галочка
    сохранилась», а что обе величины доехали до ВСЕХ представлений: подписи
    зуба, бланка, выгрузки по 195-му и самого рисунка.
    """
    import sys
    sys.path.insert(0, str(__import__("harness").BOT))
    from app import teeth_svg as tsvg                       # noqa: E402
    from app.modules.patients import fisa043                # noqa: E402

    # ---- 0. «в лечении» больше НЕ состояние ----
    res.ok("tratament ушёл из списка состояний",
           "tratament" not in tsvg.STATE_RO and "tratament" in tsvg.TOOTH_MARKS,
           "состояние и отметка снова называются одним именем — второй выбор "
           "опять вытеснит первый")

    # ⚠️ Полярность ВКЛЮЧАЮЩАЯ: вторая отметка, дописанная в TOOTH_MARKS, ничего
    # не уронит — она просто не нарисуется, не напечатается и не переведётся, и
    # ни одна проверка не покраснеет сама (грабля карты про PLAN_ACTIVE)
    blind = [m for m in tsvg.TOOTH_MARKS
             if m not in tsvg.MARK_RO or m not in tsvg.MARK_COLORS
             or m not in fisa043._MARK_ABBR]
    res.ok("каждую отметку умеют назвать, нарисовать и напечатать", not blind,
           f"отметка есть в TOOTH_MARKS, но не во всех словарях: {blind}")
    # ⚠️ Та же полярность у РИСУНКА: цвет в словаре есть, а рисовать отметку
    # функция может и не уметь — тогда она есть словом в легенде и в подписи,
    # а на дуге её не видно. Каждую отметку спрашиваем на здоровом зубе в обоих
    # видах ЕЁ цветом (у «nerv extras» рисунок свой — каналы, не ореол).
    unseen_any = [m for m in tsvg.TOOTH_MARKS
                  if tsvg.MARK_COLORS[m] not in tsvg.tooth_svg(16, "ok", marks=(m,))
                  or tsvg.MARK_COLORS[m] not in tsvg.occlusal_svg(16, "ok", marks=(m,))]
    res.ok("каждую отметку видно на здоровом зубе в обоих видах", not unseen_any,
           f"отметка названа, но не нарисована: {unseen_any}")

    # ---- 1. отметка видна на ЛЮБОМ состоянии, в обоих видах ----
    # ⚠️ Смысл ореола именно в этом: значок поверх зуба пришлось бы уводить от
    # креста удаления, винта импланта и полей поверхностей, а «lipsă» и вовсе
    # уходит из функции своим return — там отметка пропала бы МОЛЧА
    col = tsvg.MARK_COLORS["tratament"]
    unseen = [st for st in tsvg.STATE_RO
              if col not in tsvg.tooth_svg(16, st, marks=("tratament",))
              or col not in tsvg.occlusal_svg(16, st, marks=("tratament",))]
    res.ok("отметку видно на каждом состоянии и в обоих видах", not unseen,
           f"ореол не нарисован при состояниях: {unseen}")
    res.ok("без отметки рисунок прежний",
           col not in tsvg.tooth_svg(16, "carie")
           and col not in tsvg.occlusal_svg(16, "carie"),
           "зелёный ореол появился там, где отметки нет")

    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Marcaje Test", "phone": "022181818"})
        pid = _pid(c, "022181818")
        base = f"/admin/patient/{pid}"
        api = f"/api/patients/{pid}"

        # ---- 2. то, ради чего всё затевалось ----
        c.post_json(f"{api}/teeth/16", {"state": "carie", "surfaces": ["M", "O"]})
        r = c.post_json(f"{api}/teeth/16", {"state": "carie", "state0": "carie",
                                           "surfaces": ["M", "O"], "marks": ["tratament"]})
        res.check("отметка принята", r.msg, "ok_card")
        res.check("зуб называется И находкой, И отметкой",
                  _title(c, pid, 16), "16 · Carie · În tratament · MO")
        res.ok("бланк 043/e печатает обе", ">C MO T</td>" in c.get(f"{base}/fisa043").body,
               "на подписываемом бланке снова видно только одно из двух")

        # ---- 3. отметка ОДНА держит запись ----
        # «зуб здоров, но сейчас в работе» — законная запись; раньше строка с
        # state='ok' без заметки и врача удалялась, и экран отвечал «сохранено»
        r = c.post_json(f"{api}/teeth/21", {"state": "ok", "surfaces": [],
                                           "marks": ["tratament"]})
        res.check("здоровый зуб в работе принят", r.msg, "ok_card")
        res.check("запись не удалилась вместе с состоянием",
                  _title(c, pid, 21), "21 · Sănătos · În tratament")
        res.ok("бланк печатает отметку и без находки",
               ">T</td>" in c.get(f"{base}/fisa043").body,
               "в клетке пусто, хотя зуб в работе")

        # ---- 4. снять отметку можно, и это НЕ трогает находку ----
        c.post_json(f"{api}/teeth/16", {"state": "carie", "state0": "carie",
                                       "surfaces": ["M", "O"], "marks": []})
        res.check("пустой список отметок её снимает", _title(c, pid, 16), "16 · Carie · MO")

        # ---- 5. «поля нет» ≠ «сняли» ----
        # ⚠️ Запись без поля `marks` (до 13.10 — старая форма без `mk0`) об
        # отметках не сообщает и снимать их не вправе: иначе сохранение из
        # вкладки, открытой до 08-17, снимало бы «в работе» с каждого зуба
        c.post_json(f"{api}/teeth/26", {"state": "carie", "surfaces": [], "marks": ["tratament"]})
        c.post_json(f"{api}/teeth/26", {"state": "carie", "note": "control", "surfaces": []})
        res.check("запись, не знающая про отметки, их не снимает",
                  _title(c, pid, 26), "26 · Carie · În tratament · control")

        # ---- 6. состояния «tratament» больше нет ----
        # До 13.10 форма зуба переводила его в отметку — совместимость со
        # вкладкой, открытой до 08-17 (форма снята вместе со старой фишей).
        # JSON API такое состояние не принимал никогда: оно отбивается, а не
        # пишется состоянием, вытесняя находку
        r = c.post_json(f"{api}/teeth/36", {"state": "tratament", "surfaces": []})
        res.check("«tratament» состоянием — отказ", (r.status, r.msg), (422, "bad_card"))

        # ---- 7. выгрузка по 195-му ----
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{base}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        marks = {t["tooth"]: t["marks"] for t in data["dinti"]}
        res.check("машинная копия несёт отметку", marks.get(21), "tratament")
        fisa = z.read("fisa-pacient.html").decode("utf-8")
        res.ok("читаемая копия называет отметку словом",
               "Marcaje" in fisa and "În tratament" in fisa,
               "пациенту уехала фиша без того, что зуб в работе")

        # ---- 8. летопись хранит ГОТОВУЮ строку, и в ней обе величины ----
        hist = _odo(c, pid)["history"]
        res.ok("летопись зуба называет находку и отметку",
               any("Carie (MO) · În tratament" in x["text"]
                   for x in hist.get("16", [])),
               f"в истории зуба осталось только одно из двух: {hist.get('16')}")

        # ---- 9. ореол доехал до РИСУНКА зуба, а не только до подписи ----
        # ⛔ Проверка, которой не хватало: рисование сверялось прямыми вызовами
        # `teeth_svg`, а экран — по подписи. Между ними лежит один аргумент
        # (`marks=mk` у рисунка модели), и без него зуб «в работе» неотличим от
        # обычного, легенда обещает знак, которого на дуге нет, а прогон
        # ЗЕЛЁНЫЙ — подпись на месте. Спрашивается КОНКРЕТНЫЙ зуб в обоих видах:
        # ореол, севший не на тот зуб, тоже «есть на экране».
        odo = _odo(c, pid)
        marked = odo["teeth"]["21"]["svg"]       # здоров + в работе
        plain = odo["teeth"]["16"]["svg"]        # кариес, отметку сняли в п.4
        res.ok("ореол нарисован на отмеченном зубе, в обоих видах",
               col in marked["frontal"] and col in marked["occlusal"],
               "зуб «в работе» на дуге неотличим от обычного, хотя легенда показывает ободок")
        res.ok("зуб без отметки ободка не получил",
               col not in plain["frontal"] and col not in plain["occlusal"],
               "ореол сел на зуб, у которого отметки нет")

        # ---- 10. экрану есть чем это ввести и объяснить ----
        res.check("словарь отметок уезжает экрану (галочки панели и меню зуба)",
                  list(odo["marks"]), ["tratament", "devital"])
        # ⛔ Проверяется РИСУНОК в легенде, а не слово рядом с ним. Легенда,
        # рисующая рядом с «În tratament» обычный зуб, снова показывает отметку
        # ВОСЬМЫМ СОСТОЯНИЕМ — ровно то недоразумение, ради которого отметки в
        # ней идут своим видом, — а проверка по слову осталась бы зелёной.
        leg = {x["key"]: x for x in odo["legend"]["frontal"]}
        res.ok("легенда объясняет отметку — своим видом, а не состоянием",
               leg.get("tratament", {}).get("kind") == "mark"
               and leg["tratament"]["label"] == "În tratament",
               f"легенда не отличает отметку от состояния: {leg.get('tratament')}")
        res.ok("легенда рисует отметку ободком, а не обычным зубом",
               col in leg.get("tratament", {}).get("svg", ""),
               "рядом со словом «În tratament» в легенде стоит зуб без ободка")

        # ---- 11. на бланке 043/e отметка занимает место КОДА, если находки нет ----
        # ⛔ У этого бланка «O» значит И obturație, И ocluzal. Клетка «O T» на
        # зубе без единой пломбы читается по грамматике самого листа как
        # пломбированный, а массово такие зубы создаёт МИГРАЦИЯ: у «în tratament»
        # буквы поверхностей оставались, а кода находки после перевода в отметку
        # нет. Подписанный бланк не имеет права измениться от обновления.
        # здоров + в работе + буквы поверхностей — ровно то, во что миграция 5
        # перевела «в лечении» (до 13.10 сюда же вела форма со state=tratament)
        c.post_json(f"{api}/teeth/47", {"state": "ok", "surfaces": ["M", "O"], "marks": ["tratament"]})
        f043 = c.get(f"{base}/fisa043").body
        res.ok("первым в клетке стоит код, а не буква поверхности",
               ">T MO</td>" in f043 and ">MO T</td>" not in f043,
               "клетка начинается буквой поверхности — на этом бланке это код "
               "пломбы, и зуб без пломб читается пломбированным")
        # при ЖИВОЙ находке порядок обратный — код впереди, отметка в хвосте.
        # Проверяется тут же, на соседнем зубе: два порядка в одном бланке и есть
        # то, что легко разъезжается
        c.post_json(f"{api}/teeth/37", {"state": "carie", "surfaces": ["M", "O"],
                                       "marks": ["tratament"]})
        f043 = c.get(f"{base}/fisa043").body
        res.ok("при живой находке отметка остаётся в хвосте",
               ">C MO T</td>" in f043,
               "порядок токенов клетки разъехался с легендой листа")

        # ---- 12. вторая отметка — «Nerv extras» (02.10, просьба клиники) ----
        # Девитальный зуб почти всегда несёт пломбу или коронку, поэтому это
        # ОТМЕТКА, а не состояние: состоянием оно вытесняло бы пломбу с фиши и
        # с подписываемой 043/e — та же потеря, что у «în tratament» до 08-17.
        # Проверяется совместимость с коронкой и с первой отметкой РАЗОМ и
        # доезд до тех же представлений: подпись, бланк, выгрузка, летопись,
        # дуга на странице, легенда.
        dv = tsvg.MARK_COLORS["devital"]
        res.ok("каналы нарисованы и на коронке — ради этого отметка, а не состояние",
               dv in tsvg.tooth_svg(16, "coroana", marks=("devital",))
               and dv in tsvg.occlusal_svg(16, "coroana", marks=("devital",)),
               "на коронке отметку не видно — врач выбирал бы одно из двух")
        res.ok("каналов столько, сколько корней",
               tsvg.tooth_svg(16, "ok", marks=("devital",)).count(f"stroke='{dv}'")
               == tsvg.root_count(16) == 3
               and tsvg.tooth_svg(11, "ok", marks=("devital",)).count(f"stroke='{dv}'") == 1
               and tsvg.occlusal_svg(16, "ok", marks=("devital",)).count(f"fill='{dv}'") == 3,
               "число линий каналов не совпало с числом корней")
        res.ok("у импланта, удалённого и отсутствующего каналов нет",
               not any(dv in tsvg.tooth_svg(16, st, marks=("devital",))
                       or dv in tsvg.occlusal_svg(16, st, marks=("devital",))
                       for st in ("implant", "extras", "lipsa")),
               "каналы нарисованы там, где нет ни зуба, ни корней")
        both = tsvg.tooth_svg(16, "carie", marks=("tratament", "devital"))
        res.ok("две отметки не мешают друг другу в рисунке",
               col in both and dv in both,
               "одна из отметок пропала с рисунка, когда стоят обе")
        res.ok("ореол остался только у «в работе»",
               "stroke-width='6'" not in tsvg.tooth_svg(16, "ok", marks=("devital",)),
               "у «nerv extras» появился второй ореол — на коронке их не различить")

        r = c.post_json(f"{api}/teeth/27", {"state": "coroana", "surfaces": [],
                                           "marks": ["devital", "tratament"]})
        res.check("коронка с обеими отметками принята", r.msg, "ok_card")
        res.check("подпись зуба называет коронку и обе отметки",
                  _title(c, pid, 27), "27 · Coroană · În tratament · Nerv extras")
        f043 = c.get(f"{base}/fisa043").body
        res.ok("бланк 043/e печатает код коронки и обе отметки",
               ">Cor T Dv</td>" in f043,
               "на подписываемом бланке пропала коронка или отметка")
        res.ok("легенда бланка расшифровывает Dv", "Dv — devital" in f043,
               "код на бланке есть, расшифровки нет")
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{base}/export").raw))
        data = json.loads(z.read("date-pacient.json").decode("utf-8"))
        marks = {t["tooth"]: t["marks"] for t in data["dinti"]}
        res.check("машинная копия несёт обе отметки в каноническом порядке",
                  marks.get(27), "tratament,devital")
        res.ok("читаемая копия называет «Nerv extras»",
               "Nerv extras" in z.read("fisa-pacient.html").decode("utf-8"),
               "пациенту уехала фиша без второй отметки")
        odo = _odo(c, pid)
        hist = odo["history"]
        res.ok("летопись зуба называет коронку и обе отметки",
               any("Coroană · În tratament · Nerv extras" in x["text"]
                   for x in hist.get("27", [])),
               f"в истории зуба не все три величины: {hist.get('27')}")
        svg27 = odo["teeth"]["27"]["svg"]
        res.ok("каналы доехали до рисунка зуба, в обоих видах",
               dv in svg27["frontal"] and dv in svg27["occlusal"],
               "зуб «nerv extras» на дуге неотличим от обычного")
        res.check("вторая отметка — в словаре экрана словом",
                  odo["marks"].get("devital"), "Nerv extras")
        leg = {x["key"]: x for x in odo["legend"]["frontal"]}
        res.ok("легенда рисует «Nerv extras» каналами, отметкой",
               leg.get("devital", {}).get("kind") == "mark"
               and leg["devital"]["label"] == "Nerv extras" and dv in leg["devital"]["svg"],
               "второй отметки нет в легенде или она нарисована обычным зубом")


def suite_punte(res: Result) -> None:
    """Мост (punte, 08-21, просьба пилота): конструкция ПОВЕРХ зубов.

    Канон — из ответа врача: роль у КАЖДОГО зуба (опора бывает в середине:
    47-45-43 опоры при теле 46/44), в клетке 043/e опора «Co», тело «D»
    ПЕРВЫМ токеном, над конструкцией материал (наша печать — строкой под
    решёткой). Проверяется доезд до всех представлений: экран (модель API —
    одна на детальную страницу и вкладку фиши, до 13.10 их было две), летопись
    фиши, печатная 043/e, выгрузка по 195-му — и правила дуги.
    """
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/patients", {"name": "Punte Test", "phone": "022343434"})
        pid = _pid(c, "022343434")
        base = f"/admin/patient/{pid}"
        api = f"/api/patients/{pid}"

        # состояние зубов ДО моста: опора с кариесом, тело над отсутствующим —
        # мост их не мутирует, и клетка 043/e обязана показать оба знания
        c.post_json(f"{api}/teeth/47", {"state": "carie", "doctor": "d2", "surfaces": []})
        c.post_json(f"{api}/teeth/46", {"state": "lipsa", "doctor": "d2", "surfaces": []})

        r = c.post_json(f"{api}/bridges", {"teeth": [[44, "corp"], [47, "stalp"], [45, "stalp"], [46, "corp"], [43, "stalp"]],
                                          "material": "zirconiu"})
        res.check("мост сохраняется (порядок кликов — любой)", r.msg, "ok_punte")

        odo = _odo(c, pid)
        res.check("мост доехал до экрана: зубы в порядке дуги и материал",
                  [(b["teeth"], b["material"]) for b in odo["bridges"]],
                  [([[47, "stalp"], [46, "corp"], [45, "stalp"], [44, "corp"], [43, "stalp"]],
                    "zirconiu")])
        res.ok("зуб подписан ролью", "Punte: Stâlp (zirconiu)" in odo["teeth"]["47"]["title"],
               "в подписи зуба нет роли")
        res.ok("летопись называет мост словами",
               any("stâlpi: 47, 45, 43" in t for t in _feed(c, pid)),
               "в ленте нет строки моста со словами ролей")

        # --- правила дуги (bridge_norm) ---
        for label, teeth in (
            ("дырка в ряду", "47:stalp,45:corp"),
            ("смесь дуг", "17:stalp,47:corp"),
            ("молочные", "85:stalp,84:corp"),
            ("один зуб", "41:stalp"),
            ("без единой опоры", "42:corp,41:corp"),
            ("мусорная роль отбрасывается", "42:xxx,41:corp"),
        ):
            pairs = [[int(n), role] for n, _, role in (x.partition(":") for x in teeth.split(","))]
            r = c.post_json(f"{api}/bridges", {"teeth": pairs, "material": "metal"})
            res.check(f"отказ: {label}", r.msg, "bad_punte")
        r = c.post_json(f"{api}/bridges", {"teeth": [[43, "stalp"], [42, "corp"]],
                                          "material": "metal"})
        res.check("зуб двух мостов сразу — отказ", r.msg, "dup_punte")
        r = c.post_json(f"{api}/bridges", {"teeth": [[15, "stalp"], [14, "corp"], [13, "stalp"]],
                                          "material": "alt", "material_alt": "E.max"})
        res.check("вторая дуга свободна, свой материал принят", r.msg, "ok_punte")
        res.ok("свободный материал доехал",
               "E.max" in [b["material"] for b in _odo(c, pid)["bridges"]],
               "material_alt потерян")
        # фронтальный мост ЧЕРЕЗ среднюю линию — единственная позитивная
        # ветка, где порядок дуги расходится с порядком номеров FDI (41→31):
        # сравнение «подряд» по номерам его бы отвергло. Заодно врач моста:
        # из справочника — снапшотом в летопись, чужое имя — отбрасывается
        r = c.post_json(f"{api}/bridges", {"teeth": [[31, "corp"], [41, "stalp"]],
                                          "material": "ceramică", "doctor": "Dr. Activ Doi"})
        res.check("мост через среднюю линию", r.msg, "ok_punte")
        odo = _odo(c, pid)
        res.ok("порядок через центр — по дуге, не по номерам",
               [[41, "stalp"], [31, "corp"]] in [b["teeth"] for b in odo["bridges"]],
               "фронтальный мост не нормализован порядком дуги")
        # якорь точный (« · врач» в хвосте строки моста)
        res.ok("врач моста — снапшотом в летописи",
               any("intermediari: 31 · Dr. Activ Doi" in t for t in _feed(c, pid)),
               "выбранный врач не доехал до летописи")
        r = c.post_json(f"{api}/bridges", {"teeth": [[33, "stalp"], [34, "corp"]],
                                          "material": "metal", "doctor": "Oarecare Străin"})
        res.ok("врач вне справочника отброшен — и в мосту, и в летописи",
               r.msg == "ok_punte"
               and "Oarecare Străin" not in [b["doctor"] for b in json.loads(r.body)["data"]["bridges"]]
               and not any("Oarecare Străin" in t for t in _feed(c, pid)),
               "свободный текст в поле врача прошёл в мост или летопись")

        # --- печатная 043/e ---
        fisa = c.get(f"{base}/fisa043").body
        res.ok("клетка опоры: мост первым токеном, находка следом",
               ">Co C<" in fisa,
               "клетка 47 не «Co C» — конструкция не названа раньше находки")
        res.ok("клетка тела моста над отсутствующим: «D A»",
               ">D A<" in fisa, "клетка 46 не «D A»")
        res.ok("строка моста с материалом (печатная acoladă)",
               "Punte dentară 47–43 (zirconiu): 47 Co, 46 D, 45 Co, 44 D, 43 Co"
               in fisa, "под решёткой нет строки моста")
        res.ok("легенда объясняет мостовые коды",
               "Co — dinte stâlp" in fisa, "легенда без моста")
        res.ok("легенда привязывает мост к списку под решёткой",
               "doar la dinții enumerați" in fisa,
               "клетка из одной «D» (здоровый зуб с поверхностью) без этой "
               "оговорки читалась бы как тело моста")

        # --- выгрузка по 195-му ---
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{base}/export").raw))
        html_doc = z.read([n for n in z.namelist()
                           if n.endswith(".html")][0]).decode("utf-8")
        res.ok("выгрузка несёт раздел мостов",
               "Punți dentare" in html_doc and "Stâlp" in html_doc
               and "zirconiu" in html_doc,
               "в копии по 195-му моста нет")

        # --- снятие моста ---
        bid = next((b["id"] for b in _odo(c, pid)["bridges"] if b["teeth"][0] == [47, "stalp"]), 0)
        other = Client(s.url).login()
        other.post_json("/api/patients", {"name": "Alt Pacient", "phone": "022454545"})
        pid2 = _pid(other, "022454545")
        other.post_json(f"/api/patients/{pid2}/bridges/{bid}/delete", {})
        res.ok("чужая фиша мост не снимает",
               bid in [b["id"] for b in _odo(c, pid)["bridges"]],
               "мост снят через чужой pid")
        r = c.post_json(f"{api}/bridges/{bid}/delete", {})
        res.check("свой мост снимается", r.msg, "ok_punte_del")
        # повторное снятие (вторая вкладка, тот же confirm) — отказ, а не
        # второй «ștearsă» в летописи: log_event идёт после DELETE и только
        # при реально снятой строке (ревью 08-22)
        r = c.post_json(f"{api}/bridges/{bid}/delete", {})
        res.check("повторное снятие того же моста — отказ (404)", r.status, 404)
        res.check("одно снятие — одна строка летописи",
                  sum("Punte dentară 47–43 ștearsă" in t for t in _feed(c, pid)), 1)
        odo = _odo(c, pid)
        res.ok("мост ушёл с экрана", bid not in [b["id"] for b in odo["bridges"]],
               "снятый мост остался")
        res.check("состояния зубов мост не тронул",
                  (odo["teeth"]["47"]["state"], odo["teeth"]["46"]["state"]), ("carie", "lipsa"))

        # --- мост держит фишу от физического стирания (лечение) ---
        c.post_json("/api/patients", {"name": "Doar Punte", "phone": "022565656"})
        pid3 = _pid(c, "022565656")
        c.post_json(f"/api/patients/{pid3}/bridges", {"teeth": [[21, "stalp"], [22, "corp"]],
                                                     "material": "ceramică"})
        r = c.post_json(f"/api/patients/{pid3}/erase", {"confirm": "STERG"})
        res.check("пациент с одним мостом обезличивается, не стирается",
                  r.msg, "ok_anon")


def suite_geom(res: Result) -> None:
    """Размеры для объёмного вида (B7, ступень 1): сервер владеет ими целиком,
    и они стоят на тех же числах, что рисунок сверху."""
    from app import teeth_svg as tsvg          # noqa: E402
    g16, g14, g41, g11, g55 = (tsvg.tooth_geom(n) for n in (16, 14, 41, 11, 55))
    res.check("16: первый моляр 10,5 мм мезио-дистально, три корня", (g16["md"], g16["roots"]), (10.5, 3))
    res.ok("16: вестибуло-язычно шире, чем 10 мм", g16["bl"] > 10.0, str(g16["bl"]))
    res.check("14: верхний первый премоляр — два корня", g14["roots"], 2)
    res.ok("41 уже 11: нижний резец мельче верхнего", g41["md"] < g11["md"], f"{g41['md']} vs {g11['md']}")
    res.check("41: один корень, нижняя челюсть, центральный резец", (g41["roots"], g41["upper"], g41["cls"]),
              (1, False, "incisor_c"))
    res.check("55: молочный моляр — три корня, коронка ниже постоянного", (g55["roots"], g55["crown"] < g16["crown"]),
              (3, True))
    res.check("коронка и корни — из таблиц по классу и челюсти", (g16["crown"], g16["root"], g41["crown"], g41["root"]),
              (7.5, 11.2, 9.0, 11.2))
    every = [tsvg.tooth_geom(n) for n in tsvg.FDI_ALL] if hasattr(tsvg, "FDI_ALL") else None
    if every is None:
        from app.modules.patients import odontogram as podo   # noqa: E402
        every = [tsvg.tooth_geom(n) for n in podo.FDI_ALL]
    res.check("у всех 52 зубов семь полей и положительные размеры",
              (len(every), all(set(g) == {"md", "bl", "crown", "root", "roots", "cls", "upper"} for g in every),
               all(g["md"] > 0 and g["bl"] > 0 and g["crown"] > 0 and g["root"] > 0 for g in every)),
              (52, True, True))
    res.check("пропорция — та же, что у рисунка: 36,3 ед. = 10,5 мм", round(tsvg.MM_PER_UNIT * 36.3, 6), 10.5)
