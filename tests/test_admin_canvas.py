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

from harness import Client, Result, Server, clinic_today

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
