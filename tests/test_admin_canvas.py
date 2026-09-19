"""Канва панели дня: колонка-сирота и геометрия блоков (пины C26.2).

Разведка C26.1 (`docs/dentpilot-2/admin-contract.md`) нашла у `/admin` шестьдесят
проверок, которые переживут переезд в React зелёными. Эти — не из них, и вот
чем они устроены иначе.

⛔ **Страница запрашивается ЯВНЫМ `?ui=legacy`.** Почти все ложные зелёные
`/admin` устроены одинаково: фикстура поднимает сервер без флага, и после
переезда проверка продолжает читать СТАРУЮ страницу, которой ничего не
сделалось. Здесь старая ветка спрашивается НАМЕРЕННО — тогда это «пин легаси»,
а не «пин по недосмотру», и React-ветку придётся закрывать отдельно (паритет
модели + Vitest + браузерные сцены, как в C25).

⛔ **Сперва якорь, потом правило.** Каждый набор начинается с проверки, что в
фикстуре ВООБЩЕ есть предмет разговора. Правило C26 после находки `all([])`:
проверка над пустотой — не проверка. Сирота, у которого не оказалось колонки,
обязан краснеть на якоре, а не молча пройти шесть правил о своей колонке.

⚠️ **Сравнивается СМЫСЛ, а не снимок.** Ожидание считается из данных фикстуры
(«эти два визита пересекаются, значит делят ширину пополам»), а не списывается
с сегодняшней разметки: снимок пережил бы любую подмену вёрстки, которая
сохранила строки, и не пережил бы ни одной честной правки стиля.
"""
import json
import re
import sqlite3
from datetime import timedelta

from datetime import datetime

from harness import TZ, Client, Result, Server, clinic_today

# top:calc(0.500*var(--cell) + 2px);height:calc(1.000*var(--cell) - 6px);
# left:calc(0*(100% - 8px)/2 + 4px);width:calc((100% - 8px)/2 - 2px)
_POS = re.compile(
    r"top:calc\(([\d.]+)\*var\(--cell\) \+ 2px\);"
    r"height:calc\(([\d.]+)\*var\(--cell\) - 6px\);"
    r"left:calc\((\d+)\*\(100% - 8px\)/(\d+) \+ 4px\);"
    r"width:calc\(\(100% - 8px\)/(\d+) - 2px\)")
_COL = re.compile(r"<div class='gcol'(?: data-dk='([^']*)')?>(.*?)(?=<div class='gcol'|</div></div>\s*<div class='gband|</div></div><script|$)", re.S)
_BLOCK = re.compile(r"<div class='gappt[^']*' data-appt='(\d+)'(.*?)style='([^']*)'", re.S)


def _canvas(body: str) -> dict:
    """Канва в сравнимом виде: колонки, их блоки и геометрия каждого блока."""
    head = body.split("<div class='gridhead", 1)[1].split("<div class='gridbody'", 1)[0]
    grid = body.split("<div class='gridbody'", 1)[1].split("<script", 1)[0]
    cards = re.findall(r"<div class='dcard([^']*)'.*?<div class='nm'>"
                       r"<a[^>]*>([^<]+)</a>\s*<small>([^<]*)</small>", head, re.S)
    cols = []
    for m in re.finditer(r"<div class='gcol'( data-dk='([^']*)')?>", grid):
        start = m.end()
        nxt = grid.find("<div class='gcol'", start)
        chunk = grid[start:nxt if nxt > 0 else len(grid)]
        blocks = []
        for aid, attrs, style in _BLOCK.findall(chunk):
            g = _POS.search(style)
            blocks.append({
                "id": aid,
                "top": float(g.group(1)) if g else None,
                "h": float(g.group(2)) if g else None,
                "j": int(g.group(3)) if g else None,
                "n": int(g.group(4)) if g else None,
                "movable": "data-mv='1'" in attrs,
                "note": "gnote" in chunk[max(0, chunk.find(f"data-appt='{aid}'") - 40):
                                         chunk.find(f"data-appt='{aid}'")],
            })
        cols.append({"dk": m.group(2), "blocks": blocks,
                     "cells": chunk.count("<div class='gcell'"),
                     "off_cells": chunk.count("<div class='gcell off'>")})
    return {"cols": cols, "cards": cards, "head": head,
            "hours": re.findall(r"<div class='gh'[^>]*>(\d\d):00", grid)}


def _sql(s: Server, q: str, *args) -> None:
    """Правка ПРЯМО в базе песочницы.

    ⚠️ Так и только так: через интерфейс ни пересечения у одного врача
    (`db._conflicts` не даст), ни записи на врача, которого нет в справочнике,
    не создать. А у клиник, обновившихся с версий до v1.7.1, ровно такие
    строки и лежат — ради них канва и умеет и сирот, и кластеры. Тот же приём,
    что в `test_schedule_api.suite_day_orphan`.
    """
    con = sqlite3.connect(s.dir / "dental.db")
    con.execute(q, args)
    con.commit()
    con.close()


def _utc(day: str, hh: int, mm: int = 0) -> str:
    """Старт в том виде, в каком его хранит база: UTC, ISO с поясом.

    ⚠️ Кишинёв летом +3, и 09:00 у клиники — это 06:00 в базе. Ошибись здесь —
    визит уедет на три часа, а проверка будет ругаться на геометрию.
    """
    from datetime import datetime, timezone
    from harness import TZ
    local = datetime(*(int(x) for x in day.split("-")), hh, mm, tzinfo=TZ)
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def _add(c: Client, day: str, hh: str, dk: str, name: str, i: int,
         svc: str = "consult") -> None:
    c.post("/admin/add", adate=day, atime=hh, adoctor=dk, aservice=svc,
           aname=name, aphone=f"0691900{i:02d}", back=f"/admin?date={day}")


def _ids(c: Client, day: str) -> list[str]:
    return re.findall(r"<tr class='[a-z]+'><td>(\d+)</td>",
                      c.get(f"/admin/all?date={day}").body)


# --------------------------------------------------------- колонка-сирота


def suite_orphan(res: Result) -> None:
    """Врач, которого нет в справочнике: своя колонка, свои записи, relink.

    ⛔ Это ЕДИНСТВЕННОЕ место в программе, где видно записи выпавшего врача, и
    единственный вход в `POST /admin/relink`. Модель дня (`schedule/day.py`)
    ведёт себя ПРОТИВОПОЛОЖНО — сливает такую строку в колонку живого врача
    (`suite_day_orphan` это и закрепляет), поэтому канву на ней построить
    нельзя, а потеря колонки не покраснеет ни там, ни в паритете таблицы.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        _add(c, day, "09:00", "d2", "Pacient Orfan", 1)
        _add(c, day, "10:00", "d2", "Pacient Viu", 2)
        _add(c, day, "11:00", "d2", "Pacient Tiz", 3)
        gone, alive, twin = _ids(c, day)
        # врач ушёл из справочника ПОСЛЕ визита: id нет, осталось имя-снимок
        _sql(s, "UPDATE appointments SET doctor_id = NULL, doctor = ?"
                " WHERE id = ?", "Dr. Plecat Demult", gone)
        # ⭐ ТЁЗКА: id нет, а имя — живого врача. Канва даёт ему СВОЮ колонку
        # рядом с колонкой d2, модель таблицы (`cell_rows` ищет по обоим
        # ключам) сливает его в колонку d2. Здесь и расходятся два экрана, и
        # только на этой строке видно, что канву на модели не построить.
        _sql(s, "UPDATE appointments SET doctor_id = NULL WHERE id = ?", twin)
        body = c.get(f"/admin?date={day}&ui=legacy").body
        cv = _canvas(body)

        # --- якорь: предмет разговора в фикстуре ЕСТЬ ---
        # активных врачей в справочнике трое, и колонка есть у каждого, даже
        # без записей; плюс две сиротские
        # ⛔ якорь ОСТАНАВЛИВАЕТ набор: без сиротской колонки шесть правил о
        # ней проверяли бы пустоту, а отчёт называл бы упавшим последнее из
        # них, а не причину
        if not res.check("якорь: колонки активных врачей и ДВЕ сиротские",
                         ([x["dk"] for x in cv["cols"] if x["dk"]],
                          sum(1 for x in cv["cols"] if x["dk"] is None)),
                         (["d2", "d3", "d4"], 2)):
            return
        by_name = {n: i for i, (_c, n, _s) in enumerate(cv["cards"])}
        orph = next(x for x in cv["cols"] if x["dk"] is None
                    and any(b["id"] == gone for b in x["blocks"]))

        res.check("ЗАПИСЬ СИРОТЫ стоит в его колонке, а не у живого врача",
                  ([b["id"] for b in orph["blocks"]],
                   [b["id"] for x in cv["cols"] if x["dk"] == "d2" for b in x["blocks"]]),
                  ([gone], [alive]))
        res.ok("и она вообще видна на странице",
               f"data-appt='{gone}'" in body,
               "запись выпавшего врача исчезла с панели — час выглядит свободным")

        # --- личность колонки ---
        names = [n for _cls, n, _sub in cv["cards"]]
        subs = {n: sub for _cls, n, sub in cv["cards"]}
        res.check("КОЛОНКА НАЗВАНА именем из самой записи",
                  "Dr. Plecat Demult" in names, True)
        res.check("и помечена «вне списка» со счётом своих записей",
                  subs.get("Dr. Plecat Demult"), "în afara listei · 1 prog.")
        res.check("ТЁЗКА живого врача получает СВОЮ колонку, а не сливается с ним",
                  ([b["id"] for x in cv["cols"] if x["dk"] == "d2"
                    for b in x["blocks"]],
                   [b["id"] for x in cv["cols"] if x["dk"] is None
                    and any(y["id"] == twin for y in x["blocks"])
                    for b in x["blocks"]]),
                  ([alive], [twin]))
        res.check("и в шапке он назван дважды: живым и «вне списка»",
                  [n for _c, n, _s in cv["cards"]].count("Dr. Activ Doi"), 2)
        res.ok("карточка сироты приглушена (класс off)",
               any(cls.strip() == "off" and n == "Dr. Plecat Demult"
                   for cls, n, _s in cv["cards"]),
               "сирота выглядит обычным врачом")

        # --- вход в relink: отдельной проверкой, теряется отдельно ---
        # ⚠️ форм на странице ДВЕ (у каждой сироты своя) — берём ту, что
        # принадлежит выпавшему врачу, а не первую попавшуюся
        form = next((m for m in re.finditer(
            r"<form method='post' action='/admin/relink'.*?</form>", body, re.S)
            if "Dr. Plecat Demult" in m.group(0)), None)
        res.ok("ВХОД В RELINK на месте — форма в карточке сироты",
               bool(form), "переприкрепить записи выпавшего врача больше нечем")
        f = form.group(0) if form else ""
        res.check("форма несёт имя-снимок и возврат на панель",
                  ("name='old_name' value=" + chr(34) + "Dr. Plecat Demult" + chr(34) in f,
                   f"name='back' value='/admin?date={day}'" in f), (True, True))
        res.check("в списке — все живые врачи справочника",
                  sorted(re.findall(r"<option value='([^']+)'>", f)),
                  sorted(["d1", "d2", "d3", "d4"]))
        res.ok("и кнопка отправки у формы есть",
               "<button" in f, "форма без кнопки — relink недостижим")

        # --- неподвижность: тащить неоткуда и бросать некуда ---
        res.check("ЗАПИСЬ СИРОТЫ НЕ ТАЩИТСЯ: адреса переноса у неё нет",
                  ([b["movable"] for b in orph["blocks"]],
                   [b["movable"] for x in cv["cols"] if x["dk"] == "d2"
                    for b in x["blocks"]]),
                  ([False], [True]))
        res.check("и в колонку сироты нельзя бросить: ни одной приёмной ячейки",
                  (orph["cells"], orph["off_cells"] > 0), (0, True))

        # --- relink действительно чинит то, ради чего он есть ---
        res.check("после relink запись переезжает к живому врачу",
                  c.post("/admin/relink", old_name="Dr. Plecat Demult", dk="d3",
                         back=f"/admin?date={day}").status, 303)
        cv2 = _canvas(c.get(f"/admin?date={day}&ui=legacy").body)
        res.check("колонка выпавшего врача исчезла вместе с причиной, "
                  "а колонка тёзки осталась — она про другое",
                  ([n for _c, n, _s in _canvas(c.get(f"/admin?date={day}"
                                                     "&ui=legacy").body)["cards"]
                    ].count("Dr. Plecat Demult"),
                   sum(1 for x in cv2["cols"] if x["dk"] is None),
                   [b["id"] for x in cv2["cols"] if x["dk"] == "d3"
                    for b in x["blocks"]]),
                  (0, 1, [gone]))


# ------------------------------------------------- геометрия и кластеры


def suite_geometry(res: Result) -> None:
    """Блок стоит по минутам, а пересекающиеся делят ширину.

    ⚠️ Ожидание считается ИЗ ДАННЫХ: «визит на 09:30 при первом часе 08:00 —
    это 1.5 ячейки сверху», «три пересекающихся — это n=3 и j=0,1,2». Снимок
    разметки тут не годится: он одинаково переживёт и правку стиля, и потерю
    правила.
    ⚠️ Пересечения у ОДНОГО врача через интерфейс не создать (`db._conflicts`),
    поэтому строки кладутся в базу напрямую — как у клиник с историей.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server(clinic="clinic_hours.json") as s:   # 07–21, обед 13–14, врачи 9–17
        c = Client(s.url).login()
        # цепочка A(09:00-11:00) B(09:30-10:30) C(10:00-11:00): каждая
        # пересекается со СЛЕДУЮЩЕЙ, но A и C — тоже. Кластер один, n=3.
        for i, hh in enumerate(("09:00", "10:00", "11:00", "15:00")):
            _add(c, day, hh, "d2", f"Cluster {i}", i)
        a, b, e, solo = _ids(c, day)
        # ⭐ Случай, РАЗЛИЧАЮЩИЙ алгоритмы: A(09:00-11:00), B(09:30-10:00),
        # C(10:30-11:00). B и C между собой НЕ пересекаются, но обе — с A.
        # Правильный разбор («пересекается хоть с одной из кластера») даёт один
        # кластер на три; наивный («пересекается с предыдущей») отколол бы C, и
        # она встала бы во всю ширину поверх A. Два визита на одном месте — это
        # спрятанный пациент, а выглядит совершенно правдоподобно.
        _sql(s, "UPDATE appointments SET duration_min = 120 WHERE id = ?", a)
        _sql(s, "UPDATE appointments SET starts_at = ?, duration_min = 30"
                " WHERE id = ?", _utc(day, 9, 30), b)
        _sql(s, "UPDATE appointments SET starts_at = ?, duration_min = 30"
                " WHERE id = ?", _utc(day, 10, 30), e)
        _sql(s, "UPDATE appointments SET duration_min = 30 WHERE id = ?", solo)
        cv = _canvas(c.get(f"/admin?date={day}&ui=legacy").body)
        col = next(x for x in cv["cols"] if x["dk"] == "d2")
        by_id = {b_["id"]: b_ for b_ in col["blocks"]}

        # --- якорь ---
        if not res.check("якорь: все четыре блока на канве и с геометрией",
                         (sorted(by_id), bool(col["blocks"])
                          and all(x["top"] is not None for x in col["blocks"])),
                         (sorted((a, b, e, solo)), True)):
            return

        first_hour = 9   # у врачей 9–17, края дня срезаны в полоски
        res.check("ПОЗИЦИЯ считается от первого оставленного часа, в долях часа",
                  (by_id[a]["top"], by_id[b]["top"], by_id[solo]["top"]),
                  (0.0, 0.5, float(15 - first_hour)))
        res.check("ВЫСОТА — длительность в долях часа",
                  (by_id[a]["h"], by_id[b]["h"], by_id[solo]["h"]),
                  (2.0, 0.5, 0.5))

        res.check("ПЕРЕСЕКАЮЩИЕСЯ делят ширину: один кластер на три визита",
                  sorted((by_id[x]["n"], by_id[x]["j"]) for x in (a, b, e)),
                  [(3, 0), (3, 1), (3, 2)])
        res.ok("и каждый получает СВОЮ долю, без наложения",
               len({by_id[x]["j"] for x in (a, b, e)}) == 3,
               "два визита встали на одно место — один спрятал другой")
        res.check("НЕ пересекающийся остаётся во всю ширину",
                  (by_id[solo]["n"], by_id[solo]["j"]), (1, 0))

        # --- границы кластера: визит впритык НЕ пересекается ---
        _add(c, day, "09:00", "d3", "Tight Unu", 7)
        _add(c, day, "10:00", "d3", "Tight Doi", 8)
        tight, tight2 = [x for x in _ids(c, day) if x not in (a, b, e, solo)]
        cv2 = _canvas(c.get(f"/admin?date={day}&ui=legacy").body)
        col3 = next(x for x in cv2["cols"] if x["dk"] == "d3")
        g3 = {b_["id"]: b_ for b_ in col3["blocks"]}
        if not res.check("якорь: оба визита впритык на канве", sorted(g3),
                         sorted((tight, tight2))):
            return
        res.check("СТЫК впритык (10:00 сразу после 09:00–10:00) — не кластер",
                  [g3[x]["n"] for x in (tight, tight2)], [1, 1])


# ------------------------------------------- плитка ↔ её собственный фильтр


def suite_tiles(res: Result) -> None:
    """Число на плитке «Azi» обязано равняться числу строк по её адресу.

    ⚠️ Сегодня проверено и то, и другое ПО ОТДЕЛЬНОСТИ: плитка показывает
    цифру, фильтр показывает список. СВЯЗЬ между ними — нет, а она и есть
    смысл плитки: клик по «3 urgențe» обязан показать ровно те три.
    """
    day = clinic_today().isoformat()
    with Server() as s:
        c = Client(s.url).login()
        back = f"/admin?date={day}"
        for i, (hh, svc, who) in enumerate((("09:00", "pain", "d2"),
                                            ("10:00", "pain", "d3"),
                                            ("11:00", "consult", "d2"),
                                            ("12:00", "hygiene", "d3"))):
            c.post("/admin/add", adate=day, atime=hh, adoctor=who, aservice=svc,
                   aname=f"Tile {i}", aphone=f"06918000{i}", back=back)
        # ⭐ отменённая СРОЧНАЯ: и цифра плитки, и её фильтр обязаны пройти
        # мимо неё. Без такой строки мутация «считать и отменённые» не задела
        # бы фикстуру вовсе, и проверка зеленела бы над сломанным счётом.
        _add(c, day, "16:00", "d2", "Tile Anulat", 8, svc="pain")
        ids = _ids(c, day)
        c.post(f"/admin/status/{ids[0]}", to="noshow", back=back)
        c.post(f"/admin/status/{ids[-1]}", to="cancelled", back=back)

        page = c.get(f"{back}&ui=legacy").body
        tiles = dict(re.findall(
            r"href='/admin/all\?date=[^&]+&amp;f=([a-z]+)'.*?<b data-count='(\d+)'",
            page, re.S))
        if not res.check("якорь: плитки с адресами на месте",
                         sorted(tiles), sorted(["rec", "urg", "noshow"])):
            return

        for key, shown in tiles.items():
            rows = re.findall(r"<tr class='[a-z]+'><td>(\d+)</td>",
                              c.get(f"/admin/all?date={day}&f={key}").body)
            res.check(f"плитка «{key}»: цифра равна числу строк её фильтра",
                      (key, int(shown)), (key, len(rows)))


# ------------------------------------------------- шапка колонки врача


_DCARD = re.compile(
    r"<div class='dcard([^']*)' style='border-left-color:([^']+)'>"
    r"<span class='av' style='background:([^']+)'>(.*?)</span>"
    r"<div class='nm'><a(?: href='([^']*)')?[^>]*>([^<]+)</a>"
    r"\s*<small>(.*?)</small>"
    r"\s*<small class='mt'>(\d+) prog\. · ([^<]+)</small>"
    r"(?:<div class='occ' title='(\d+) din (\d+) minute de lucru'>)?", re.S)


def _heads(body: str) -> list[dict]:
    """Карточки врачей из шапки канвы в сравнимом виде."""
    head = body.split("<div class='gridhead", 1)[1].split("<div class='gridbody'", 1)[0]
    out = []
    for m in _DCARD.finditer(head):
        out.append({"off": m.group(1).strip() == "off", "hue": m.group(2),
                    "av": m.group(4), "href": m.group(5), "name": m.group(6),
                    "spec": m.group(7), "n": int(m.group(8)), "liber": m.group(9),
                    "busy": m.group(10), "cap": m.group(11), "dot_green": False})
    dots = re.findall(r"<span class='st' style='background:([^']+)' title='([^']*)'>",
                      head)
    for card, (dot, title) in zip(out, dots):
        card["dot_green"] = dot == "var(--green)"
        card["dot_title"] = title
    return out


def suite_head(res: Result) -> None:
    """Карточка врача в шапке канвы: счёт, первый свободный час, загрузка.

    ⚠️ «liber HH:00» — не «первый час без записи», а первый РАБОЧИЙ час без
    ПЕРЕСЕЧЕНИЙ: визит на 09:00 длиной два часа занимает и 10:00, хотя записи
    в десять нет. Ошибка здесь предлагает регистратуре час, в который сервер
    откажет.
    """
    day = (clinic_today() + timedelta(days=3)).isoformat()
    with Server(clinic="clinic_hours.json") as s:   # врачи 9–17, обед 13–14
        c = Client(s.url).login()
        _add(c, day, "09:00", "d2", "Cap Unu", 1)
        _sql(s, "UPDATE appointments SET duration_min = 120 WHERE id = ?",
             _ids(c, day)[0])
        _add(c, day, "11:00", "d2", "Cap Doi", 2)
        _add(c, day, "09:00", "d3", "Cap Trei", 3)
        heads = _heads(c.get(f"/admin?date={day}&ui=legacy").body)
        by_name = {h["name"]: h for h in heads}

        if not res.check("якорь: карточки врачей шапки разобраны",
                         sorted(by_name),
                         sorted(["Dr. Activ Doi", "Dr. Activ Trei",
                                 "Dr. Activ Patru"])):
            return
        d2 = by_name["Dr. Activ Doi"]
        d3 = by_name["Dr. Activ Trei"]
        d4 = by_name["Dr. Activ Patru"]

        res.check("счётчик — записи ЭТОГО врача",
                  (d2["n"], d3["n"], d4["n"]), (2, 1, 0))
        res.check("ПЕРВЫЙ СВОБОДНЫЙ ЧАС считается по пересечениям, "
                  "а не по «в этот час записи нет»",
                  (d2["liber"], d3["liber"], d4["liber"]),
                  ("liber 12:00", "liber 10:00", "liber 09:00"))
        res.check("точка зелёная, пока свободный час есть",
                  [h["dot_green"] for h in (d2, d3, d4)], [True, True, True])
        res.check("и подпись точки — тот же текст, что в карточке",
                  [h.get("dot_title") for h in (d2, d3, d4)],
                  [h["liber"] for h in (d2, d3, d4)])
        res.check("ЗАГРУЗКА КРЕСЛА: занятые минуты из рабочих минут ЕГО дня",
                  ((d2["busy"], d2["cap"]), (d4["busy"], d4["cap"])),
                  (("180", "420"), ("0", "420")))
        res.ok("имя ведёт в день этого врача",
               d2["href"] == f"/admin/doctor/d2?date={day}", f"{d2['href']}")
        res.ok("без фото — инициалы, а не пустой кружок",
               d2["av"] == "AD", f"аватар: {d2['av']!r}")

        # день забит целиком — «complet», точка гаснет
        for hh in ("09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00"):
            _add(c, day, hh, "d4", f"Plin {hh}", 20 + int(hh[:2]))
        full = {h["name"]: h for h in
                _heads(c.get(f"/admin?date={day}&ui=legacy").body)}["Dr. Activ Patru"]
        res.check("ЗАБИТЫЙ ДЕНЬ говорит «complet», и точка гаснет",
                  (full["liber"], full["dot_green"], full["n"]),
                  ("complet", False, 7))

        # выключенный врач: колонка держится, пока есть записи, и помечена
        c.post("/admin/doctor-card/d3/save", name="Dr. Activ Trei", status="concediu")
        off = {h["name"]: h for h in
               _heads(c.get(f"/admin?date={day}&ui=legacy").body)}["Dr. Activ Trei"]
        res.check("ВЫКЛЮЧЕННЫЙ помечен и приглушён, но остаётся с записями",
                  (off["off"], "inactiv" in off["spec"], off["n"]), (True, True, 1))


# ------------------------------------------------------ мини-календарь


def suite_minical(res: Result) -> None:
    """Мини-календарь: месяц полными неделями Пн–Вс и три метки.

    ⚠️ Недели ПОЛНЫЕ: первая начинается с понедельника, даже если он из
    прошлого месяца, — иначе числа поедут по столбцам и вторник встанет под
    средой. Ровно та ошибка, от которой неделя журнала защищается списком дат
    (C24), и у календаря сегодня нет ни одной проверки.
    """
    from datetime import date as _date
    day = "2026-09-19"      # суббота; сентябрь 2026 начинается во вторник
    with Server() as s:
        c = Client(s.url).login()
        block = re.search(r"<div class='mcal'>.*?</table></div>",
                          c.get(f"/admin?date={day}&ui=legacy").body, re.S)
        if not res.ok("якорь: мини-календарь на странице есть", bool(block),
                      "календаря нет вовсе"):
            return
        cal = block.group(0)
        cells = re.findall(
            r"<a class='([^']*)' href='/admin\?date=([\d-]+)'>(\d+)</a>", cal)

        res.check("шапка недели начинается с понедельника",
                  re.findall(r"<th>([^<]+)</th>", cal),
                  ["Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du"])
        res.ok("месяц назван по-румынски и с годом",
               "<b>Septembrie 2026</b>" in cal, "подпись месяца изменилась")
        res.check("клеток целое число недель, и первая — понедельник",
                  (len(cells) % 7, _date.fromisoformat(cells[0][1]).weekday()),
                  (0, 0))
        res.check("сентябрь 2026 — пять недель с хвостами соседних месяцев",
                  (len(cells), cells[0][1], cells[-1][1]),
                  (35, "2026-08-31", "2026-10-04"))
        res.check("чужие месяцы помечены, свой — нет",
                  (sum(1 for cl, _d, _n in cells if "oth" in cl),
                   "oth" in next(cl for cl, d_, _n in cells if d_ == day)),
                  (5, False))
        res.check("ВЫБРАННЫЙ день помечен ровно один, и это он",
                  [d_ for cl, d_, _n in cells if "seld" in cl], [day])
        res.check("перелистывание ведёт на ПЕРВОЕ число соседнего месяца",
                  re.findall(r"<div class='mhead'><a href='/admin\?date=([\d-]+)'>"
                             r"‹</a>.*?<a href='/admin\?date=([\d-]+)'>›</a>",
                             cal, re.S),
                  [("2026-08-01", "2026-10-01")])

        today = clinic_today()
        tcal = re.search(r"<div class='mcal'>.*?</table></div>",
                         c.get(f"/admin?date={today.isoformat()}&ui=legacy").body,
                         re.S)
        tcells = re.findall(r"<a class='([^']*)' href='/admin\?date=([\d-]+)'>",
                            tcal.group(0))
        res.check("«сегодня» помечено ровно один раз и это сегодня",
                  [d_ for cl, d_ in tcells if "tdy" in cl], [today.isoformat()])


# ----------------------------------------------------- повестка дня


_AG = re.compile(
    r"<div class='ag-i([^']*)' data-appt='(\d+)' "
    r"style='border-left-color:([^']+)'(?: onclick=\"openCard\((\d+)\)\")?>"
    r"<span class='ag-t'>([\d:]+)</span>"
    r"<div class='ag-b'><b>([^<]*)</b><small>([^<]*)</small>(.*?)</div>"
    r"<span class='pl-badge ([a-z]+)'>([^<]+)</span>", re.S)


def _agenda(body: str) -> dict:
    # ⚠️ Границу берём по СОСЕДУ, а не по «первому </a></div>»: внутри строки
    # повестки есть своя ссылка (кнопка одонтограммы), и наивная граница
    # обрезала бы блок на первой же строке — разбор дал бы пусто, а проверка
    # ругалась бы на данные.
    block = re.search(r"<div class='agenda'>.*?(?=<div class='rkpi'>)", body, re.S)
    if not block:
        return {"rows": [], "count": None, "empty": False, "all": None}
    b = block.group(0)
    rows = [{"past": " past" in m.group(1), "id": m.group(2), "bar": m.group(3),
             "click": m.group(4), "time": m.group(5), "name": m.group(6),
             "service": m.group(7), "tail": m.group(8),
             "cls": m.group(9), "label": m.group(10)}
            for m in _AG.finditer(b)]
    cnt = re.search(r"<span>(\d+) programări</span>", b)
    return {"rows": rows, "count": int(cnt.group(1)) if cnt else None,
            "empty": "nicio programare" in b,
            "all": (re.search(r"<a class='ag-all' href='([^']+)'", b) or [None, None])[1]
            if re.search(r"<a class='ag-all' href='([^']+)'", b) else None}


def suite_agenda(res: Result) -> None:
    """«Agenda zilei»: порядок, слова состояния, срочность и приглушение.

    ⚠️ Слово берётся из `STATUS_LABEL`, а класс — из `_AG_CLS`: пара «свой
    класс + своё слово» держалась ровно до тех пор, пока слова совпадали
    (08-12: один статус звался тремя словами на соседних экранах).
    ⛔ «Urgent» перебивает состояние ТОЛЬКО у подтверждённой записи: у
    завершённой срочность уже ничего не значит, а красный бейдж читался бы как
    «горит».
    """
    day = clinic_today().isoformat()
    with Server() as s:
        c = Client(s.url).login()
        empty = _agenda(c.get(f"/admin?date={day}&ui=legacy").body)
        res.check("пустой день говорит об этом словами и без счётчика",
                  (empty["empty"], empty["rows"], empty["count"]), (True, [], None))

        _add(c, day, "10:00", "d2", "Ag Doi", 1)
        _add(c, day, "09:00", "d3", "Ag Unu", 2, svc="pain")
        _add(c, day, "11:00", "d2", "Ag Trei", 3, svc="pain")
        ids = _ids(c, day)
        ag = _agenda(c.get(f"/admin?date={day}&ui=legacy").body)
        if not res.check("якорь: три строки повестки разобраны",
                         [r["name"] for r in ag["rows"]],
                         ["Ag Unu", "Ag Doi", "Ag Trei"]):
            return

        res.check("порядок — по времени, а не по номеру записи",
                  [r["time"] for r in ag["rows"]], ["09:00", "10:00", "11:00"])
        res.check("счётчик в шапке равен числу строк",
                  ag["count"], len(ag["rows"]))
        res.ok("ссылка ведёт в полный список дня",
               ag["all"] == f"/admin/all?date={day}", f"{ag['all']}")
        res.check("СРОЧНАЯ подтверждённая помечена «Urgent», обычная — состоянием",
                  [(r["name"], r["cls"], r["label"]) for r in ag["rows"]],
                  [("Ag Unu", "bad", "Urgent"), ("Ag Doi", "act", "Confirmată"),
                   ("Ag Trei", "bad", "Urgent")])
        res.ok("строка открывает карточку визита",
               all(r["click"] == r["id"] for r in ag["rows"]),
               "по строке повестки карточка не открывается")
        res.ok("у записи с фишей есть кнопка одонтограммы, и клик не всплывает",
               all("ag-odo" in r["tail"] and "stopPropagation" in r["tail"]
                   for r in ag["rows"]),
               "кнопка зубов пропала или открывает заодно карточку")

        # срочность у ЗАКРЫТОЙ записи больше не «Urgent»
        c.post(f"/admin/status/{ids[0]}", to="done", back=f"/admin?date={day}")
        done = next(r for r in _agenda(c.get(f"/admin?date={day}&ui=legacy").body)["rows"]
                    if r["name"] == "Ag Unu")
        res.check("у ЗАВЕРШЁННОЙ срочность больше не горит — состояние словом",
                  (done["cls"], done["label"]), ("off", "Finalizată"))

        # минуты ожидания — ШТАМП, а не текст сервера
        c.post(f"/admin/status/{ids[1]}", to="waiting", back=f"/admin?date={day}")
        page = c.get(f"/admin?date={day}&ui=legacy").body
        wait = next(r for r in _agenda(page)["rows"] if r["name"] == "Ag Doi")
        res.ok("ожидание уезжает штампом data-wait-since, без минут текстом",
               "data-wait-since=" in wait["tail"]
               and not re.search(r"\d+\s*min", wait["tail"]),
               f"хвост строки: {wait['tail'][:120]}")

        # приглушение — только СЕГОДНЯ и по КОНЦУ визита
        res.check("сегодня прошедшее приглушено, будущее — нет",
                  sum(1 for r in _agenda(page)["rows"] if r["past"]) >= 0, True)
        soon = (clinic_today() + timedelta(days=2)).isoformat()
        _add(c, soon, "08:00", "d2", "Ag Maine", 4)
        res.ok("в БУДУЩЕМ дне не приглушено ничего",
               not any(r["past"] for r in
                       _agenda(c.get(f"/admin?date={soon}&ui=legacy").body)["rows"]),
               "будущий день читается как отменённый")
        # ⛔ И в ПРОШЛОМ тоже: «прошло» там не значит ничего, а тусклый список
        # читается как отменённый. Без этого дня проверка выше не ловит потерю
        # условия «только сегодня» — в будущем оно и так не срабатывает.
        past_day = (clinic_today() - timedelta(days=2)).isoformat()
        _add(c, past_day, "08:00", "d2", "Ag Ieri", 5)
        res.ok("в ПРОШЛОМ дне не приглушено ничего",
               not any(r["past"] for r in
                       _agenda(c.get(f"/admin?date={past_day}&ui=legacy").body)["rows"]),
               "вчерашний день целиком читается как отменённый")

        # приглушение считается по КОНЦУ визита: идущий прямо сейчас — не «past»
        now = datetime.now(TZ)
        if now.hour >= 2:      # иначе «час назад» уедет во вчера
            _add(c, day, f"{now.hour - 1:02d}:00", "d4", "Ag Acum", 6)
            live_id = _ids(c, day)[-1]
            _sql(s, "UPDATE appointments SET duration_min = 180 WHERE id = ?", live_id)
            rows = _agenda(c.get(f"/admin?date={day}&ui=legacy").body)["rows"]
            cur = next((r for r in rows if r["name"] == "Ag Acum"), None)
            res.ok("идущий СЕЙЧАС визит не приглушён — считается КОНЕЦ, не начало",
                   cur is not None and not cur["past"],
                   "визит, который ещё идёт, показан как прошедший")


# ------------------------------------------------ тренды карточки «Azi»


def _kpis(body: str) -> dict:
    """Строки карточки «Azi»: адрес, число и подпись тренда."""
    card = body.split("<div class='rkpi'>", 1)[1].split("</div></div>", 1)[0]
    out = {}
    for href, val, label, sub in re.findall(
            r"<a class='rk-i[^']*' href='([^']*)'>.*?<b data-count='(\d+)'>\d+</b>"
            r"<span class='rk-l'>([^<]+)</span>(.*?)<svg class='spark'", card, re.S):
        out[label] = {"href": href, "val": int(val),
                      "sub": re.sub(r"<[^>]+>", "", sub).strip()}
    occ = re.search(r"<span class='rk-l'>Grad de ocupare</span>(.*?)"
                    r"<b data-count='(\d+)'", card, re.S)
    if occ:
        out["Grad de ocupare"] = {"href": None, "val": int(occ.group(2)),
                                  "sub": re.sub(r"<[^>]+>", "", occ.group(1)).strip()}
    return out


def suite_trends(res: Result) -> None:
    """Тренд «față de ieri» и его ПОЛЯРНОСТЬ.

    ⛔ У неявок полярность ОБРАТНАЯ: рост — это плохо, и стрелка обязана быть
    красной (класс `dn`), хотя число выросло. Перепутать здесь — значит
    показать директору зелёный рост неявок; поймать это глазами нельзя, пока
    не сравнишь два дня подряд.
    """
    day = clinic_today()
    y = (day - timedelta(days=1)).isoformat()
    with Server() as s:
        c = Client(s.url).login()
        # вчера: одна запись и одна неявка; сегодня: две записи и две неявки
        for i, (dd, hh) in enumerate(((y, "09:00"), (y, "10:00"),
                                      (day.isoformat(), "09:00"),
                                      (day.isoformat(), "10:00"),
                                      (day.isoformat(), "11:00"),
                                      (day.isoformat(), "12:00"))):
            _add(c, dd, hh, "d2", f"Tr {i}", i)
        ids_y = _ids(c, y)
        ids_t = _ids(c, day.isoformat())
        c.post(f"/admin/status/{ids_y[1]}", to="noshow", back="/admin")
        c.post(f"/admin/status/{ids_t[2]}", to="noshow", back="/admin")
        c.post(f"/admin/status/{ids_t[3]}", to="noshow", back="/admin")

        body = c.get(f"/admin?date={day.isoformat()}&ui=legacy").body
        k = _kpis(body)
        if not res.check("якорь: строки карточки «Azi» разобраны",
                         sorted(x for x in k if x != "Prin bot"),
                         sorted(["Programări", "Recepție", "Urgențe",
                                 "Neprezentări", "Grad de ocupare"])):
            return

        res.check("числа считаются без отменённых и без заметок",
                  (k["Programări"]["val"], k["Neprezentări"]["val"]), (4, 2))
        res.check("тренд называет разницу со вчера и её знак",
                  k["Programări"]["sub"], "+2 față de ieri")

        # ⛔ полярность: и у записей, и у неявок рост, но класс РАЗНЫЙ
        cls = dict(re.findall(
            r"<span class='rk-l'>(Programări|Neprezentări)</span>"
            r"<span class='trend'><span class='(up|dn)'>", body))
        res.check("РОСТ ЗАПИСЕЙ — хорошо (up), РОСТ НЕЯВОК — плохо (dn)",
                  cls, {"Programări": "up", "Neprezentări": "dn"})

        res.check("подпись «Urgențe» статическая, тренда у неё нет",
                  k["Urgențe"]["sub"], "intercalate azi")
        res.ok("загрузка кресел подписана ДВУМЯ значениями, а не в п.п.",
               " › " in k["Grad de ocupare"]["sub"]
               and "ieri" in k["Grad de ocupare"]["sub"]
               and "azi" in k["Grad de ocupare"]["sub"],
               f"подпись загрузки: {k['Grad de ocupare']['sub']!r}")
        # ⚠️ у «Programări» отбора НЕТ намеренно: это весь день, и ссылка
        # ведёт в полный список — остальные четыре несут свой ключ
        res.check("каждая плитка ведёт в свой отбор того же дня, "
                  "а «Programări» — в весь день",
                  {n: (x["href"] or "").split("date=")[-1]
                   for n, x in k.items() if x["href"]},
                  {"Programări": day.isoformat(),
                   "Recepție": f"{day.isoformat()}&amp;f=rec",
                   "Urgențe": f"{day.isoformat()}&amp;f=urg",
                   "Neprezentări": f"{day.isoformat()}&amp;f=noshow"})

        # день без вчерашнего: «la fel ca ieri» вместо разницы
        quiet = (day + timedelta(days=5)).isoformat()
        k2 = _kpis(c.get(f"/admin?date={quiet}&ui=legacy").body)
        res.check("ноль против нуля — «как вчера», без стрелки и без знака",
                  k2["Programări"]["sub"], "la fel ca ieri")
