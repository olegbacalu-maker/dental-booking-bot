"""Охрана доступа, страницы журнала, настройки с горячей перезагрузкой,
карточка пациента и чистые функции расписания.
"""
import json
import os
import re
import subprocess
from datetime import date, timedelta

from harness import BOT, PIN, PYTHON, Client, Result, Server


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def suite_auth(res: Result) -> None:
    with Server() as s:
        anon = Client(s.url)
        for path in ("/admin", "/admin/all", "/admin/settings", "/admin/stats"):
            r = anon.get(path)
            res.ok(f"без входа {path} не отдаётся",
                   r.status == 303 and "/admin/login" in r.location,
                   f"код {r.status}, location {r.location!r}")

        bad = Client(s.url)
        bad.post("/admin/login", password="wrong-pin", next="/admin")
        res.ok("неверный пароль не пускает",
               bad.get("/admin").status == 303, "пустил в журнал")

        good = Client(s.url).login()
        res.ok("верный пароль пускает", good.get("/admin").status == 200,
               "не пустил")
        res.ok("health отвечает всегда",
               json.loads(anon.get("/health").body).get("app") == "dentpilot",
               "health не тот")


def suite_pages(res: Result) -> None:
    """Страницы отдаются и содержат то, ради чего открываются."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d2",
               aservice="consult", aname="Pagina Test", aphone="022321321",
               back="/admin/all")

        pages = {
            "/admin": "Clinica Test",
            f"/admin/all?date={_d(1)}": "Pagina Test",
            "/admin/week": "",
            "/admin/stats": "",
            "/admin/settings": "Clinica Test",
            "/admin/medici": "Dr. Activ Doi",
            "/admin/search?q=Pagina": "Pagina Test",
            "/admin/qr-print": "",
        }
        for path, needle in pages.items():
            r = c.get(path)
            res.ok(f"страница {path} открывается", r.status == 200,
                   f"код {r.status}")
            if needle and r.status == 200:
                res.ok(f"страница {path} содержит нужное", needle in r.body,
                       f"нет {needle!r}")

        csv = c.get(f"/admin/export?from={_d(1)}&to={_d(1)}")
        res.ok("экспорт CSV отдаётся", csv.status == 200 and "Pagina Test" in csv.body,
               f"код {csv.status}")

        # оформление вынесено в файл: страница ссылается, файл отдаётся
        page = c.get("/admin").body
        res.ok("страница ссылается на таблицу стилей",
               "/static/css/panel.css?v=" in page, "нет <link> на panel.css")
        css = c.get("/static/css/panel.css")
        res.ok("таблица стилей отдаётся",
               css.status == 200 and ".banner" in css.body and "--teal" in css.body,
               f"код {css.status}, {len(css.body)} б")
        # вне сборки стили НЕ кешируются: иначе правка оформления не видна по F5
        res.ok("при работе из исходников кеш отключён",
               "no-cache" in css.header("Cache-Control"),
               f"Cache-Control: {css.header('Cache-Control')!r}")
        res.ok("метка версии в адресе — время правки файла",
               "?v=1" in page and "?v=1.11" not in page,
               "в адресе версия программы, а не время файла")
        res.ok("чужой файл через стили не вытащить",
               c.get("/static/css/..%2F..%2Fmain.py").status == 404,
               "отдал что-то постороннее")
        res.ok("несуществующий стиль — 404",
               c.get("/static/css/nope.css").status == 404, "не 404")

        # поведение страниц вынесено тем же приёмом, что и оформление
        res.ok("страница подключает общий скрипт",
               "/static/js/panel.js?v=" in page, "нет <script src> на panel.js")
        js = c.get("/static/js/panel.js")
        res.ok("скрипт отдаётся",
               js.status == 200 and "setInterval" in js.body
               and "pickName" in js.body, f"код {js.status}, {len(js.body)} б")
        res.ok("скрипт отдаётся как javascript",
               "javascript" in js.header("Content-Type"),
               f"Content-Type: {js.header('Content-Type')!r}")
        res.ok("чужой тип статики не отдаётся",
               c.get("/static/txt/panel.txt").status == 404, "отдал не css/js")


def suite_patient_card(res: Result) -> None:
    """Фиша: профиль, зубная формула, план лечения, алерты, архив."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
               aservice="consult", aname="Card Test", aphone="022654654",
               back="/admin/all")
        pid = c.get("/admin/search?q=022654654").body.split(
            "/admin/patient/", 1)[1].split("'")[0].split('"')[0].split("?")[0]

        r = c.post(f"/admin/patient/{pid}/save", name="Card Test Nou",
                   phone="022654654", email="test@example.com")
        res.check("профиль сохраняется", r.msg, "ok_card")
        res.ok("новое имя видно в карточке",
               "Card Test Nou" in c.get(f"/admin/patient/{pid}").body,
               "имя не обновилось")

        # ⚠️ проверять msg, а не код: отказ «bad_card» — тоже 303, и с кодом
        # эта проверка была пустой. Состояние звалось "caries" (в справочнике
        # "carie"), зуб не сохранялся НИКОГДА, а тест был зелёным.
        r = c.post(f"/admin/patient/{pid}/tooth", tooth="11", state="carie",
                   note="test", doctor="d2")
        res.check("зуб отмечается", r.msg, "ok_card")
        res.ok("состояние зуба видно в формуле",
               "11 · Carie · test" in c.get(f"/admin/patient/{pid}").body,
               "зуб не сохранился")

        r = c.post(f"/admin/patient/{pid}/plan", procedure="Plombă 11",
                   tooth="11", price="1200")
        res.ok("пункт плана добавляется", r.status == 303, f"код {r.status}")
        res.ok("пункт плана виден в карточке",
               "Plombă 11" in c.get(f"/admin/patient/{pid}").body,
               "плана нет на странице")

        r = c.post(f"/admin/patient/{pid}/alert", kind="allergy",
                   text="Alergie la penicilină")
        res.ok("предупреждение добавляется", r.status == 303, f"код {r.status}")
        res.ok("предупреждение видно в карточке",
               "penicilină" in c.get(f"/admin/patient/{pid}").body,
               "алерт не показан")

        # архив = скрыть из списка «недавних», но по явному запросу найти можно:
        # карточку с историей лечения нельзя терять, её именно прячут
        c.post(f"/admin/patient/{pid}/archive", on="1")
        res.ok("архивный ушёл из списка недавних",
               "Card Test Nou" not in c.get("/admin/search").body,
               "архивный всё ещё в недавних")
        res.ok("архивный находится по явному поиску",
               "Card Test Nou" in c.get("/admin/search?q=Card+Test").body,
               "архивный потерялся совсем")


def suite_dashboard(res: Result) -> None:
    """Панель: мини-графики, загрузка кресел, повестка дня, метки подсветки.

    Всё перечисленное ломается МОЛЧА — страница остаётся кодом 200 и выглядит
    целой. Отдельная ценность у процента загрузки: он обязан совпадать с тем,
    что за тот же день показывает раздел «Statistici», иначе клиника увидит два
    разных числа про одного врача и перестанет верить обоим.

    День берётся завтрашний намеренно: сегодняшний зависит от часа прогона —
    к вечеру вся повестка «прошедшая», и проверки стали бы плавающими.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        for time, doc, svc, name in (("09:00", "d2", "consult", "Ana Test"),
                                     ("11:00", "d2", "long", "Vlad Test"),
                                     ("10:00", "d3", "hygiene", "Marian Test")):
            c.post("/admin/add", adate=day, atime=time, adoctor=doc, aservice=svc,
                   aname=name, aphone="0691" + time.replace(":", ""),
                   back="/admin/all")
        page = c.get(f"/admin?date={day}").body

        res.check("мини-график в каждой из шести плиток",
                  page.count("class='spark'"), 6)
        res.ok("график рисуется и там, где две недели нулей",
               c.get(f"/admin?date={_d(60)}").body.count("class='spark'") == 6,
               "плитка без данных осталась без графика — ряд плиток порябит")
        res.ok("ряд графика — ровно две недели",
               all(len(p.split()) == 14 for p in
                   re.findall(r"<polyline class='sp-l' points='([^']+)'", page)),
               "точек не 14")

        # ⭐ 60′ + 120′ = 180 занятых из 840 рабочих (клиника фикстуры 07–21)
        occ = re.findall(r"title='(\d+) din (\d+) minute de lucru'.*?<b>(\d+)%</b>",
                         page, re.S)
        res.ok("минуты сходятся с процентом на карточке",
               bool(occ) and all(round(100 * int(b) / int(cap)) == int(p)
                                 for b, cap, p in occ), f"{occ}")
        res.check("врач с визитами 60′+120′ — это 21% от 840",
                  next((p for b, _c, p in occ if b == "180"), None), "21")
        st = c.get(f"/admin/stats?from={day}&to={day}").body
        res.ok("тот же процент в «Statistici» за тот же день",
               "<span>21%</span>" in st,
               "дашборд и статистика разошлись в загрузке врача")
        res.check("аналитика несёт свои шесть мини-графиков",
                  st.count("class='spark'"), 6)

        res.check("в повестке все три визита", page.count("class='ag-i"), 3)
        res.check("повестка отсортирована по времени",
                  re.findall(r"<span class='ag-t'>([^<]+)</span>", page),
                  ["09:00", "10:00", "11:00"])
        res.ok("завтрашний день не приглушён как прошедший",
               "ag-i past" not in page, "будущее показано серым")
        aid = re.search(r"openCard\((\d+)\)", page).group(1)
        c.post(f"/admin/status/{aid}", to="cancelled", back=f"/admin?date={day}")
        res.check("отменённый уходит из повестки",
                  c.get(f"/admin?date={day}").body.count("class='ag-i"), 2)

        # ⭐ 60′+120′+60′ занятых из 3×840 рабочих (d1 в архиве, активны d2-d4)
        res.ok("плитка загрузки на месте и с процентом",
               "Grad de ocupare" in page and "data-suffix='%'" in page,
               "нет шестой плитки")
        res.ok("процент загрузки честный: 240 из 2520 минут = 10",
               "data-count='10' data-suffix='%'>10%<" in page,
               "цифра загрузки не сходится с минутами")
        res.ok("тренд загрузки — двумя значениями, без «pp»",
               "0% → " in page and "10%</span>" in page,
               "нет формы «ieri X% → azi Y%»")
        res.ok("метки текущего часа нет в чужом дне", "nowh" not in page,
               "завтрашний день подсвечен как «сейчас»")
        res.ok("день помечен ключом подсветки", f"data-day='{day}'" in page,
               "без data-day завтрашний день подсветится весь как новый")
        res.ok("у записей есть метки для сравнения", page.count("data-appt=") >= 6,
               f"меток {page.count('data-appt=')} (ждём и в сетке, и в повестке)")

        # ⚠️ выключатель анимаций обязан стоять В ШАПКЕ: уедет в конец body —
        # успеет отрисоваться конечный кадр, и анимация пойдёт рывком назад
        head = page.split("<body>")[0]
        res.ok("выключатель анимаций стоит в <head>",
               "dp_auto" in head and "classList.add('anim')" in head,
               "скрипт не в шапке")
        js = c.get("/static/js/panel.js").body
        res.ok("автоперезагрузка помечает себя", "dp_auto" in js,
               "цифры будут оживать каждые 12 секунд")
        res.ok("подсветка пришедших записей на месте", "dp_seen_" in js,
               "нет сравнения по id")
        css = c.get("/static/css/panel.css").body
        res.ok("движение выключается системной настройкой",
               "prefers-reduced-motion" in css, "нет уважения к настройке ОС")


def suite_analytics(res: Result) -> None:
    """Аналитика: сравнение периодов, график по дням, источники, полукруг,
    деньги, лента событий. Всё выведенное — ломается молча, страница 200.

    День завтрашний, как в suite_dashboard: сегодняшний зависит от часа прогона.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        for time, doc, svc, name, phone in (
                ("09:00", "d2", "consult", "Stat Unu", "069000001"),
                ("11:00", "d2", "long", "Stat Doi", "069000002"),
                ("10:00", "d3", "hygiene", "Stat Trei", "069000003")):
            c.post("/admin/add", adate=day, atime=time, adoctor=doc, aservice=svc,
                   aname=name, aphone=phone, back="/admin/all")
        # прошлый период той же длины: одна запись «сегодня» для сравнения
        # (08:00 — /admin/add намеренно принимает прошедший час текущего дня)
        c.post("/admin/add", adate=_d(0), atime="08:00", adoctor="d4",
               aservice="consult", aname="Stat Ieri", aphone="069000004",
               back="/admin/all")

        page = c.get(f"/admin/stats?from={day}&to={day}").body
        # «la fel ca perioada trecută» — тоже тренд: нулевые плитки равны нулю
        res.ok("шесть KPI с трендом к прошлому периоду",
               page.count("perioada trecută") >= 8,   # 6 плиток + график + деньги
               f"трендов {page.count('perioada trecută')}")
        res.ok("график по дням на месте", "linechart" in page, "нет графика")
        res.ok("точки графика подписаны значениями", "class='ld-v'" in page,
               "нет значений на точках")
        res.ok("источники — только настоящие три",
               "Telegram" in page and "Recepție" in page and "Web-chat" in page
               and "Google" not in page and "Instagram" not in page,
               "в источниках выдуманные каналы")
        res.ok("кольцо источников рисуется", "class='donut'" in page, "нет кольца")
        res.ok("полукруг загрузки рисуется", "class='gauge'" in page, "нет полукруга")
        # 3 визита (60+120+60=240′) на 3 активных врача × 840′ = 240/2520 ≈ 10%
        res.ok("средняя загрузка считается по активным врачам",
               ">10%</text>" in page, "среднее не сходится (ждали 10%)")
        res.ok("деньги подписаны как оценка по прайсу",
               "nu e contabilitate" in page, "оценка выдаётся за бухгалтерию")
        res.ok("лента событий с именем и пациентом",
               "Activitate recentă" in page and "/admin/patient/" in page,
               "нет ленты или ссылок на фиши")
        res.ok("врачи отсортированы по загрузке",
               page.find("Dr. Activ Doi") < page.find("Dr. Activ Trei"),
               "врач с большей загрузкой не первый")

        # пустой период: график рисует линию по полу (не «нет данных» — период
        # существовал, записей ноль), кольцо честно говорит «fără date», среднее 0%
        empty = c.get(f"/admin/stats?from={_d(40)}&to={_d(46)}").body
        res.ok("пустой период не роняет страницу",
               "linechart" in empty and ">0%</text>" in empty
               and "fără date" in empty,
               "пустой период сломал графики")

        # у периода «сегодня» прошлый кусок той же длины — вчера (он пуст), и
        # сегодняшний визит 08:00 обязан дать «+1 vs. (0)», а не «la fel»
        tdy = c.get(f"/admin/stats?from={_d(0)}&to={_d(0)}").body
        res.ok("у «сегодня» прошлый период — вчера",
               "vs. perioada trecută (0)" in tdy, "нет сравнения на дне")


def suite_patients_list(res: Result) -> None:
    """Раздел «Pacienți»: фильтры, страницы, предпросмотр, экспорт, новая фиша.

    Статуса пациента в базе НЕТ — он выводится из алертов, плана и давности
    визита. Именно это здесь и стережётся: выведенная цифра ломается молча,
    страница остаётся кодом 200 и выглядит нормально.
    """
    with Server() as s:
        c = Client(s.url).login()

        def add(name: str, phone: str, day: int, time: str, doc: str) -> str:
            c.post("/admin/add", adate=_d(day), atime=time, adoctor=doc,
                   aservice="consult", aname=name, aphone=phone, back="/admin/all")
            body = c.get(f"/admin/search?q={phone}").body
            return body.split("/admin/patient/", 1)[1].split("'")[0]

        vechi = add("Elena Bălan", "068111222", -400, "10:00", "d2")
        alerg = add("Dumitru Ganea", "069222444", -5, "11:00", "d3")
        plan = add("Maria Ionescu", "069987654", -10, "12:00", "d2")
        arh = add("Svetlana Ciobanu", "078333555", -12, "13:00", "d4")
        add("Radu Marin", "079444666", 2, "14:00", "d2")

        c.post(f"/admin/patient/{alerg}/alert", kind="allergy", text="Penicilină")
        c.post(f"/admin/patient/{plan}/plan", procedure="Coroană", price="1200")
        c.post(f"/admin/patient/{arh}/archive", on="1")
        c.post(f"/admin/patient/{vechi}/save", name="Elena Bălan",
               phone="068111222", email="elena@example.com")
        # добор до второй страницы: пагинацию нечем проверить на пяти строках
        for i in range(8):
            c.post("/admin/patients/new", name=f"Pacient Masiv {i}",
                   phone=f"0611000{i:02d}")

        page = c.get("/admin/search").body
        res.ok("список рисуется таблицей", "pl-tbl" in page and "pl-tiles" in page,
               "нет разметки списка")
        res.ok("три числа над списком",
               all(x in page for x in ("Total pacienți", "Pacienți noi",
                                       "Programări (luna aceasta)")),
               "не все карточки на месте")
        res.ok("денежной карточки в разделе нет", "Venituri" not in page,
               "«Venituri» вернулась на страницу пациентов")

        def rows(path: str) -> int:
            return c.get(path).body.count("<tr id='plr")

        res.check("в списке все неархивные", rows("/admin/search"), 12)
        res.ok("архивный скрыт по умолчанию", "Svetlana" not in page,
               "архивный виден без запроса")
        res.ok("архивный находится явным поиском",
               "Svetlana" in c.get("/admin/search?q=Svetlana").body,
               "архивный потерялся совсем")

        # статусы выводятся, а не хранятся — проверяем каждую ветку
        res.ok("аллергия даёт «Necesită atenție»",
               "Necesită atenție" in page, "нет бейджа внимания")
        res.check("фильтр «внимание» — только он", rows("/admin/search?st=atentie"), 1)
        res.check("фильтр «в лечении» — только план",
                  rows("/admin/search?st=tratament"), 1)
        res.ok("год без визита = «Inactiv»", "Inactiv" in page, "нет бейджа неактивности")
        res.check("фильтр «архив» показывает архивного",
                  rows("/admin/search?st=arhivat"), 1)

        res.check("фильтр по врачу", rows("/admin/search?med=Dr.+Activ+Trei"), 1)
        res.check("фильтр по каналу «recepție»", rows("/admin/search?ch=manual"), 12)
        res.check("фильтр по каналу «telegram»", rows("/admin/search?ch=tg"), 0)
        res.ok("поиск не замечает диакритику",
               "Bălan" in c.get("/admin/search?q=balan").body, "«balan» не нашёл «Bălan»")
        res.ok("поиск по e-mail",
               "Bălan" in c.get("/admin/search?q=elena@example").body, "e-mail не ищется")
        res.ok("поиск по телефону в любом формате",
               "Radu Marin" in c.get("/admin/search?q=444+666").body,
               "пробел в номере ломает поиск")
        res.ok("ничего не найдено — не пустая страница",
               "Nimic găsit" in c.get("/admin/search?q=zzzzz").body, "нет пустого вида")

        res.check("страница ограничена per", rows("/admin/search?per=10"), 10)
        res.ok("подпись страницы честная",
               "Afișare 1–10 din 12" in c.get("/admin/search?per=10").body,
               "не та подпись под списком")
        res.check("вторая страница — остаток",
                  rows("/admin/search?per=10&page=2"), 2)
        res.ok("страница за пределом схлопывается на последнюю",
               "Afișare 11–12 din 12" in c.get("/admin/search?per=10&page=99").body,
               "page=99 отдал пустоту")
        res.ok("чужое per отбрасывается, а не ломает страницу",
               "Afișare 1–12 din 12" in c.get("/admin/search?per=7").body,
               "per=7 не откатился к 20")
        names = re.findall(r"<div class='pl-nm'><b>([^<]+)</b>",
                           c.get("/admin/search?sort=name").body)
        res.ok("сортировка по имени", names == sorted(names, key=str.lower),
               f"порядок {names}")

        peek = c.get(f"/admin/patient/{plan}/peek")
        res.ok("предпросмотр отдаёт кусок разметки, не страницу",
               peek.status == 200 and "Plan de tratament" in peek.body
               and "<html" not in peek.body, f"код {peek.status}")
        # ⚠️ журнал перезагружает себя каждые 12 с — панель обязана переживать
        # это через sessionStorage, иначе она «исчезает» на глазах (жалоба 08-06)
        page_js = c.get("/admin/search").body
        res.ok("панель переживает автоперезагрузку",
               "dp_peek" in page_js and "dp_peek_html" in page_js,
               "нет восстановления предпросмотра после обновления страницы")
        res.ok("предпросмотр показывает аллергию",
               "Penicilină" in c.get(f"/admin/patient/{alerg}/peek").body,
               "алерта нет в панели")
        res.check("предпросмотр несуществующего", c.get("/admin/patient/9999/peek").status,
                  404)

        csv_r = c.get("/admin/patients.csv")
        res.ok("экспорт отдаётся файлом",
               csv_r.status == 200 and "attachment" in csv_r.header("Content-Disposition")
               and csv_r.body.startswith("﻿"), f"код {csv_r.status}")
        res.check("экспорт слушается фильтров (шапка + одна строка)",
                  len(c.get("/admin/patients.csv?st=atentie").body.strip().split("\r\n")),
                  2)

        r = c.post("/admin/patients/new", name="Grigore Nou", phone="060777888",
                   birth_date="1978-02-02", email="gn@example.com")
        res.check("новая фиша заводится", r.msg, "new_pat")
        new_id = r.location.split("/admin/patient/")[1].split("?")[0]
        res.ok("новый пациент попал в список",
               "Grigore Nou" in c.get("/admin/search").body, "нет в списке")
        # ⭐ ключ manual:{цифры} склеивает по телефону: повтор обязан ОТКРЫТЬ
        # существующую фишу, а не переписать в ней имя
        r = c.post("/admin/patients/new", name="Alt Nume", phone="060 777 888")
        res.check("тот же телефон — не новый пациент", r.msg, "dup_pat")
        res.ok("повтор ведёт в ту же фишу", f"/admin/patient/{new_id}" in r.location,
               f"увёл на {r.location!r}")
        res.ok("имя существующего не перезаписано",
               "Grigore Nou" in c.get(f"/admin/patient/{new_id}").body,
               "имя затёрлось повтором")
        r = c.post("/admin/patients/new", name="Fara Telefon")
        res.check("без телефона тоже заводится", r.msg, "new_pat")
        res.ok("заведённый на рецепции — канал «recepție»",
               "Fara Telefon" in c.get("/admin/search?ch=manual").body,
               "канал определился неверно")
        res.check("без имени не заводится",
                  c.post("/admin/patients/new", name="  ").msg, "bad_pat")

        anon = Client(s.url)
        for path in ("/admin/search", "/admin/patients.csv", "/admin/patient/1/peek"):
            res.ok(f"без входа {path} не отдаётся", anon.get(path).status == 303,
                   "отдал без входа")
        res.ok("без входа пациент не заводится",
               anon.post("/admin/patients/new", name="X").status == 303,
               "завёл без входа")


def suite_settings(res: Result) -> None:
    """Настройки: хаб из плиток, страницы-секции, сохранение по кускам.

    ⭐ Главное, что здесь стережётся, — слияние: клиника/часы/услуги живут в
    ОДНОМ clinic.json, и сохранение одной секции обязано не трогать соседние.
    Наивная нарезка на вкладки затирала бы услуги при сохранении часов — молча.
    """
    with Server() as s:
        c = Client(s.url).login()

        hub = c.get("/admin/settings").body
        res.ok("хаб — плитки, а не простыня",
               "pl-tile" in hub and hub.count("/admin/settings/") >= 4,
               "нет плиток секций")
        for path, needle in {"/admin/settings/system": "Stare sistem",
                             "/admin/settings/clinic": "Clinica Test",
                             "/admin/settings/hours": "Luni",
                             "/admin/settings/services": "Igienizare"}.items():
            b = c.get(path)
            res.ok(f"секция {path} открывается",
                   b.status == 200 and needle in b.body,
                   f"код {b.status}, нет {needle!r}")
            res.ok(f"из секции {path} есть путь назад",
                   "← Setări" in b.body, "нет навигации на хаб")

        # ---- сохранение по кускам: сосед не должен пострадать ----
        # (идёт ДО цельного payload: тот прогоняет услуги через разбор формы и
        # по своей природе плющит двуязычную цену — куски так делать не должны)
        r = c.post("/admin/settings/save", part="clinic", name="Clinica Parțială",
                   phone="+373 60 111 222", addr_ro="str. Nouă 2", addr_ru="")
        res.check("кусок «клиника» сохраняется", r.msg, "ok_set")
        res.ok("возврат на ту же секцию", "/admin/settings/clinic" in r.location,
               f"увёл на {r.location!r}")
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.check("имя обновилось", after["name"], "Clinica Parțială")
        res.ok("услуги пережили сохранение клиники",
               len(after["services"]) >= 4 and any(
                   sv.get("id") == "hygiene" for sv in after["services"]),
               "services затёрты куском clinic")
        res.ok("двуязычная цена из профиля не изуродована",
               isinstance(next(sv.get("price") for sv in after["services"]
                               if sv.get("id") == "consult"), dict),
               "price {'ro','ru'} перемолот в строку")

        r = c.post("/admin/settings/save", part="hours",
                   payload=json.dumps({"hours": {
                       "mon": [9, 18], "tue": [9, 18], "wed": None,
                       "thu": [9, 18], "fri": [9, 18, 13, 14],
                       "sat": None, "sun": None}}))
        res.check("кусок «часы» сохраняется", r.msg, "ok_set")
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.ok("имя пережило сохранение часов",
               after["name"] == "Clinica Parțială", "часы затёрли клинику")
        res.ok("среда закрыта, обед пятницы записан",
               after["hours"]["wed"] is None and after["hours"]["fri"] == [9, 18, 13, 14],
               f"часы не те: {after['hours']}")
        res.ok("строка контактов боту пересобрана",
               "13" in after.get("contacts", {}).get("ro", ""),
               "contacts не отражает новый обед")

        r = c.post("/admin/settings/save", part="services",
                   payload=json.dumps({"services": [
                       {"id": "consult", "ro": "Consultație", "ru": "Консультация",
                        "price": "300 MDL", "duration": "30", "docs": ""}]}))
        res.check("кусок «услуги» сохраняется", r.msg, "ok_set")
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.check("услуг стало ровно столько, сколько прислали",
                  len(after["services"]), 1)
        res.ok("врачи пережили сохранение услуг",
               len(after["doctors"]) == 4, "услуги затёрли врачей")
        res.ok("часы пережили сохранение услуг",
               after["hours"]["wed"] is None, "услуги затёрли часы")

        r = c.post("/admin/settings/save", part="hours",
                   payload=json.dumps({"hours": {d: None for d in
                                                 ("mon", "tue", "wed", "thu",
                                                  "fri", "sat", "sun")}}))
        res.check("вся неделя закрыта — отбито", r.msg, "bad_set")
        res.ok("ошибка вернула на страницу часов",
               "/admin/settings/hours" in r.location, f"{r.location!r}")

        # старый цельный payload остаётся рабочим (горячая перезагрузка)
        cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
        cfg["name"] = "Clinica Redenumită"
        r = c.post("/admin/settings/save",
                   payload=json.dumps(cfg, ensure_ascii=False))
        res.check("настройки сохраняются", r.msg, "ok_set")
        res.ok("новое название видно сразу",
               "Clinica Redenumită" in c.get("/admin").body,
               "hot-reload не сработал")
        res.ok("название записано в файл клиники",
               "Clinica Redenumită" in s.clinic.read_text(encoding="utf-8"),
               "clinic.json не переписан")


def suite_pure(res: Result) -> None:
    """Чистая логика расписания — без сервера и без базы."""
    code = r"""
import json, sys
sys.path.insert(0, r"%s")
from datetime import datetime, timedelta, date
from app import engine as eng
from app import paths
# ⚠️ статус бота ищется в sys.modules по имени пакета. Когда имя считалось от
# __package__ текущего файла, переезд файла в подпапку тихо ломал показ:
# адаптер работает, а интерфейс рисует его выключенным. Подкладываем модуль
# под НАСТОЯЩИМ именем и проверяем, что его находят из core.
import types
_fake = types.ModuleType("app.telegram")
_fake.STATUS = {"running": True, "username": "bot_de_test", "error": ""}
sys.modules["app.telegram"] = _fake
from app.core.layout import _tg_state, tg_status
now = datetime.now(eng.TZ)
out = {
 "tg_user":        tg_status().get("username"),
 "tg_running":     tg_status().get("running"),
 "tg_state_tuple": list(_tg_state()),
 "res_clinic":     paths.resource("clinic.json").exists(),
 "res_clinic_new": paths.resource("clinic_new.json").exists(),
 "res_static":     paths.resource("static").is_dir(),
 "res_index":      paths.resource("static", "index.html").exists(),
 "runtime_is_pkg": paths.runtime_dir() == paths.PKG_ROOT,
 "past_hour":      eng.is_past(now - timedelta(hours=1)),
 "future_hour":    eng.is_past(now + timedelta(hours=1)),
 "past_day":       eng.is_past_day(date.today() - timedelta(days=1)),
 "today_not_past": eng.is_past_day(date.today()),
 "dur_default":    eng.svc_duration("consult"),
 "dur_long":       eng.svc_duration("long"),
 "dur_unknown":    eng.svc_duration("nope"),
 "fits_noon":      eng.fits_clinic(now.replace(hour=12, minute=0), 60),
 "orphan_docs":    eng.allowed_doc_items("orphan"),
 "consult_docs":   len(eng.allowed_doc_items("consult")),
}
print(json.dumps(out))
""" % str(BOT)
    # ⚠️ окружение НАСЛЕДУЕТСЯ: с обрезанным PATH Windows не грузит winsock,
    # и import asyncio падает на ровном месте (WinError 10106)
    env = dict(os.environ)
    env["CLINIC_CONFIG"] = str(_fixture())
    p = subprocess.run([str(PYTHON), "-c", code], cwd=str(BOT), text=True,
                       capture_output=True, env=env)
    if p.returncode != 0:
        res.failed.append(("чистые функции: запуск", p.stderr[-500:]))
        return
    v = json.loads(p.stdout)
    # статус бота: ищется по имени пакета, а не по расположению файла
    res.check("статус бота виден из core", v["tg_user"], "bot_de_test")
    res.check("бот показан работающим", v["tg_running"], True)
    res.check("короткий статус для сайдбара", v["tg_state_tuple"],
              [True, "bot_de_test"])
    # якоря путей: то, из-за чего собранный exe не стартовал бы после переезда
    res.check("демо-профиль клиники находится", v["res_clinic"], True)
    res.check("пустой профиль клиники находится", v["res_clinic_new"], True)
    res.check("папка static находится", v["res_static"], True)
    res.check("страница пациента находится", v["res_index"], True)
    res.check("вне сборки писать некуда, кроме корня пакета",
              v["runtime_is_pkg"], True)
    res.check("прошедший час — в прошлом", v["past_hour"], True)
    res.check("будущий час — не в прошлом", v["future_hour"], False)
    res.check("вчерашний день закрыт", v["past_day"], True)
    res.check("сегодня НЕ закрытый день", v["today_not_past"], False)
    res.check("длительность по умолчанию", v["dur_default"], 60)
    res.check("длительность из конфига", v["dur_long"], 120)
    res.check("неизвестная услуга — дефолт", v["dur_unknown"], 60)
    res.check("полдень в графике", v["fits_noon"], True)
    res.check("услугу без активных врачей выполнять некому",
              v["orphan_docs"], [])
    res.check("консультацию выполняют все активные", v["consult_docs"], 3)


def _fixture():
    from harness import FIXTURES
    return FIXTURES / "clinic_test.json"
