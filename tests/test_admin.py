"""Охрана доступа, страницы журнала, настройки с горячей перезагрузкой,
карточка пациента и чистые функции расписания.
"""
import html
import io
import json
import os
import pathlib
import re
import subprocess
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from harness import (BOT, PIN, PYTHON, Client, Result, Server, _rmtree_settled, add_appt,
                     appt_id, clinic_today, day_model, new_patient, panel_live, pid_by_phone,
                     shell_model)


def _sync(page: str) -> list:
    """Ключи пунктов секции «Sincronizări» меню React (`nav.sync` модели
    оболочки; заголовок секции рисует клиент и только при непустом списке)."""
    return [i["key"] for i in shell_model(page)["nav"]["sync"]]


def _d(offset: int) -> str:
    return (clinic_today() + timedelta(days=offset)).isoformat()


# ---- экраны фиши и списка — React (13.10): то, что они показывают, это
# ответы JSON API; страница несёт только узел ----

def _card(c: Client, pid) -> dict:
    """Фиша данными (`GET /api/patients/{pid}`)."""
    return json.loads(c.get(f"/api/patients/{pid}").body)["data"]


def _plist(c: Client, qs: str = "") -> dict:
    """Страница списка «Pacienți» данными (`GET /api/patients?…`)."""
    return json.loads(c.get("/api/patients" + (f"?{qs}" if qs else "")).body)["data"]


def _names(c: Client, qs: str = "") -> list[str]:
    return [r["name"] for r in _plist(c, qs)["rows"]]


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
        add_appt(c, _d(1), "10:00", "Pagina Test", "022321321")

        pages = {
            "/admin": "Clinica Test",
            # журнал, статистика, врачи, пациенты — React (12–13.10): данные
            # приходят из /api/*, их содержимое стерегут свои наборы
            f"/admin/all?date={_d(1)}": "",
            "/admin/week": "",
            "/admin/stats": "",
            "/admin/settings": "Clinica Test",
            "/admin/medici": "",
            "/admin/search?q=Pagina": "",
            "/admin/qr-print": "",
        }
        for path, needle in pages.items():
            r = c.get(path)
            res.ok(f"страница {path} открывается", r.status == 200,
                   f"код {r.status}")
            if needle and r.status == 200:
                res.ok(f"страница {path} содержит нужное", needle in r.body,
                       f"нет {needle!r}")

        # Окно часа выбирает и ПОЛЧАСА (08-13, Олег): клик по ячейке — час, но
        # запись бывает на 10:30. Переключатель живёт в окне React
        # (`SlotDialog`), а сервер принимает получасовой старт тем же маршрутом.
        res.check("запись на 10:30 принимается",
                  add_appt(c, _d(1), "10:30", "Jumatate Test", "022321322", "d3").msg, "ok")

        # Автоперезагрузки (data-reload на <body>) нет НИ У ОДНОЙ страницы:
        # живой у журнала только канал панели (`/api/schedule/live`, React), а
        # остальным она не даёт ничего и отнимает раскрытые <details> и
        # позицию прокрутки — «вкладка FAQ закрывается сама» (Олег, 08-07).
        for path in ("/admin", f"/admin/all?date={_d(1)}", "/admin/week",
                     "/admin/doctor/d2", "/admin/settings", "/admin/settings/faq",
                     "/admin/stats", "/admin/medici", "/admin/search", "/admin/qr-print"):
            res.ok(f"{path} НЕ перезагружает себя",
                   "data-reload" not in c.get(path).body,
                   "странице выдана автоперезагрузка — она снова будет терять "
                   "раскрытые details")

        # Ширина (08-16, просьба Олега «справа много места»): окно отдаётся
        # ВСЕМ разделам. Экраны React ведут ширину раскладкой клиента (серверного
        # `content` у их оболочки нет); у страниц на серверной оболочке
        # (`_shell`, до шага 6 снятия старого интерфейса) — тот же
        # единственный каркас `content` без модификатора: вернувшийся
        # `content wide` снова сделал бы часть страниц узкими молча. Потолок
        # самой СТРОКИ живёт в panel.css (test_review3.suite_width).
        body = c.get("/admin/qr-print").body
        res.ok("серверная оболочка занимает всю ширину окна",
               'class="content"' in body,
               "раздел не получил широкий контент — справа останется пустое поле")
        # справку рисует React: потолок строки — правило клиента `.dp-faq`
        front = BOT.parent / "frontend" / "src"
        faq_rule = re.search(r"\.dp-faq\s*\{[^}]*\}",
                             (front / "app" / "app.css").read_text(encoding="utf-8"))
        res.ok("длинный текст справки держит свой потолок",
               bool(faq_rule) and "max-width: var(--measure)" in faq_rule.group(0)
               and "dp-faq" in (front / "features" / "settings" / "FaqScreen.tsx")
               .read_text(encoding="utf-8"),
               "карточка FAQ растянулась вместе со страницей — на 2560 это "
               "строка ответа через весь монитор")

        res.check("CSV-выгрузки дня больше нет (слово Олега 12.10) — остаётся Excel",
                  c.get(f"/admin/export?from={_d(1)}&to={_d(1)}").status, 404)

        # ---- выгрузка в Excel: проверяем ТИПЫ, а не код ответа (08-12) ----
        # ⛔ CSV типов не несёт, и Excel угадывает: телефон `022447788` он
        # считает числом и роняет ведущий ноль. Файл при этом верен, испорчен
        # только экран — и заметить это нельзя, в отличие от `########` у даты.
        # Поэтому xlsx проверяется РАЗБОРОМ: телефон обязан лежать строкой,
        # дата — числом-датой со своим форматом, ширины — быть.
        # ⚠️ .raw, а не .body: тело декодируется с "replace", и zip после
        # этого — мусор (та же грабля, что у выгрузки данных пациента)
        xl = c.get(f"/admin/export.xlsx?from={_d(1)}&to={_d(1)}")
        res.ok("выгрузка Excel отдаётся",
               xl.status == 200 and xl.raw[:2] == b"PK",
               f"код {xl.status}, первые байты {xl.raw[:4]!r}")
        with zipfile.ZipFile(io.BytesIO(xl.raw)) as z:
            names = set(z.namelist())
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
            styles = z.read("xl/styles.xml").decode("utf-8")
        res.ok("книга собрана из положенных частей",
               {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml",
                "xl/worksheets/sheet1.xml"} <= names, f"внутри: {sorted(names)}")
        res.ok("телефон остался ТЕКСТОМ с ведущим нулём",
               '<t xml:space="preserve">022321321</t>' in sheet,
               "телефон ушёл числом — Excel съест ноль, и по таблице не позвонить")
        res.ok("дата ушла датой, а не строкой",
               '<c r="A2" s="2">' in sheet,
               "дата не получила формат даты — в Excel это текст или число")
        res.ok("у даты свой формат dd.mm.yyyy",
               "dd\\.mm\\.yyyy" in styles and 'numFmtId="164"' in styles,
               "формат даты не объявлен — Excel покажет серийное число")
        res.ok("ширины колонок заданы",
               "<cols>" in sheet and 'customWidth="1"' in sheet,
               "без ширин дата снова выйдет как ########")
        res.ok("шапка закреплена и есть автофильтр",
               'state="frozen"' in sheet and "<autoFilter" in sheet,
               "выгрузка на сотню строк без закреплённой шапки нечитаема")
        res.ok("имя пациента внутри книги",
               "Pagina Test" in sheet, "строк нет вовсе")

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

        # Ответ на действие — ПЛАВАЮЩЕЙ плашкой (08-14, фидбек клиники): баннер
        # в потоке оставался за кадром — «сказали ок, а что случилось — не
        # поняли». Помощник один (layout.msg_banner, держит test_structure), но
        # канал проверяется на страницах ТРЁХ модулей: каждый маршрут зовёт его
        # сам, и забытый вызов уронил бы сообщение вовсе. Экраны React несут
        # ту же плашку строкой сервера в модели оболочки (`frame.msg`), её
        # рисует AppShell. На `/admin` приземляется отказ в правах со всей
        # программы.
        def _shell_msg(page: str) -> str:
            raw = page.split('data-shell="', 1)[1].split('"', 1)[0]
            return json.loads(html.unescape(raw))["frame"]["msg"]
        for path in ("/admin?msg=no_access",
                     "/admin/settings?msg=ok_set",
                     "/admin/medici?msg=ok_med"):
            page_t = c.get(path).body
            if 'data-shell="' in page_t:
                page_t = _shell_msg(page_t)
            res.ok(f"{path.split('?')[0]} отвечает плавающей плашкой",
                   "id='dp_toast'" in page_t and "class='toastbox'" in page_t,
                   "msg рисуется строкой в потоке — внизу страницы его не видно")
            res.ok(f"{path.split('?')[0]} — плашку можно закрыть",
                   "class='t-x'" in page_t, "нет крестика")
        res.ok("чужой файл через стили не вытащить",
               c.get("/static/css/..%2F..%2Fmain.py").status == 404,
               "отдал что-то постороннее")
        res.ok("несуществующий стиль — 404",
               c.get("/static/css/nope.css").status == 404, "не 404")

        # Шрифт объявлен ОТДЕЛЬНЫМ файлом, потому что просит его не только
        # журнал: вход и установка PIN несут свою вёрстку, panel.css не
        # подключают — и до 08-11 рисовались системным шрифтом, не объявив
        # 'Inter' нигде. Сюда объявление приезжает ссылкой, туда — вставленным
        # текстом (проверка на той стороне — в test_pin).
        res.ok("страница подключает объявление шрифта",
               "/static/css/fonts.css?v=" in page, "нет <link> на fonts.css")
        # ⚠️ Считается `@font-face{`, а не `@font-face`: слово встречается и в
        # пояснениях внутри обоих файлов, и счёт по нему сравнивал бы комментарии.
        fonts = c.get("/static/css/fonts.css")
        res.ok("объявление шрифта отдаётся",
               fonts.status == 200 and fonts.body.count("@font-face{") == 4,
               f"код {fonts.status}, правил {fonts.body.count('@font-face{')} — ждём 4")
        res.ok("объявление шрифта не задваивается",
               "@font-face{" not in css.body,
               "@font-face вернулся в panel.css — два источника разъедутся молча")
        # Файлы шрифта голова просит ВМЕСТЕ со стилями (03.10, стенд
        # shift_sweep): иначе браузер узнаёт о них только из раскладки, уже
        # после бандла, и быстрый ответ данных раскладывался запасным шрифтом.
        # ⚠️ Адрес обязан совпасть с src у @font-face побайтно, а crossorigin —
        # стоять: без того или другого файл скачается дважды, а кадр всё
        # равно разложится до шрифта.
        pre = re.findall(r'<link rel="preload" href="([^"]+)" as="font" '
                         r'type="font/woff2" crossorigin>', page)
        res.ok("голова заранее просит шрифт — те же файлы, что объявляет fonts.css",
               len(pre) == 2 and all(f"url('{u}')" in fonts.body for u in pre),
               f"предзагрузка: {pre}")

        # поведение серверных страниц вынесено тем же приёмом, что и
        # оформление (экраны React panel.js не грузят: у него там нет читателей)
        res.ok("серверная страница подключает общий скрипт",
               "/static/js/panel.js?v=" in c.get("/admin/qr-print").body,
               "нет <script src> на panel.js")
        js = c.get("/static/js/panel.js")
        res.ok("скрипт отдаётся",
               js.status == 200 and "setInterval" in js.body
               and "dp_toast" in js.body, f"код {js.status}, {len(js.body)} б")
        res.ok("скрипт отдаётся как javascript",
               "javascript" in js.header("Content-Type"),
               f"Content-Type: {js.header('Content-Type')!r}")
        res.ok("чужой тип статики не отдаётся",
               c.get("/static/txt/panel.txt").status == 404, "отдал не css/js")


def suite_nophone(res: Result) -> None:
    """Пациент без телефона (08-20, просьба пилота) и поиск по дате рождения.

    Опоры: галочка = намерение ИЗ ФОРМЫ (прайор 08-16 — не угадывать по
    пустоте); ключ безтелефонного УНИКАЛЕН (db.manual_key — иначе все
    безтелефонные склеились бы в одного, и _upsert переписал бы имя);
    телефон задним числом, совпавший с чужим, называется вслух."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(21)

        def add(name, phone, t, nophone=False):
            return add_appt(c, day, t, name, phone,
                            **({"nophone": "1"} if nophone else {}))

        # пустой телефон БЕЗ галочки — прежний отказ: это недозаполненное
        # окно, а не намерение
        r = add("FaraTel Zero", "", "09:00")
        res.ok("пустой телефон без галочки отбивается", r.msg == "bad_phone",
               f"msg {r.msg!r}")

        # с галочкой — проходит; второй безтелефонный — ОТДЕЛЬНЫЙ человек
        r1 = add("FaraTel Unu", "", "10:00", nophone=True)
        r2 = add("FaraTel Doi", "", "11:00", nophone=True)
        res.ok("запись без телефона проходит с галочкой",
               r1.msg == "ok" and r2.msg == "ok", f"{r1.msg} / {r2.msg}")
        lst = _plist(c, "q=FaraTel")["rows"]
        res.ok("двое безтелефонных НЕ склеились и не переименованы",
               {"FaraTel Unu", "FaraTel Doi"} <= {r["name"] for r in lst},
               "второй перезаписал первого — ключ manual: снова общий")
        # перечёркнутую трубку рисует экран по пустому телефону строки
        res.ok("безтелефонный — пустым телефоном, а не выдуманным",
               all(r["phone"] == "" for r in lst), f"{[(r['name'], r['phone']) for r in lst]}")

        # с галочкой поля телефона в теле может не быть вовсе: отказ «нет
        # телефона» здесь был бы ложью (до 13.10 так слал браузер форму с
        # выключенным полем — и Form(...) давал 422 раньше честного bad_phone)
        r = c.post_json("/api/schedule/appointments", {"date": day, "time": "13:00",
                                                      "doctor": "d2", "service": "consult",
                                                      "name": "FaraTel Patru", "nophone": "1"})
        res.ok("запись без поля телефона, но с галочкой проходит",
               r.msg == "ok", f"msg {r.msg!r}")

        # галочка главнее набранного телефона: номер отброшен
        r = add("FaraTel Trei", "069999888", "12:00", nophone=True)
        res.ok("галочка отбрасывает набранный телефон", r.msg == "ok", r.msg)
        res.ok("отброшенный телефон не ищется",
               "FaraTel Trei" not in _names(c, "q=069999888"),
               "номер сохранился вопреки галочке")

        # фиша безтелефонного: «fără telefon» и взведённую галочку правки экран
        # выводит из пустого телефона (производная, своей колонки нет)
        res.check("в фише телефон пуст — экран скажет «fără telefon»",
                  _card(c, lst[0]["id"])["profile"]["phone"], "")

        # --- телефон задним числом, совпавший с чужим, называется вслух ---
        pid_a = new_patient(c, "Sot Comun", "068111222")
        pid_b = new_patient(c, "Sotie Aparte")
        res.ok("двое заведены отдельно", pid_a != pid_b, "фиши склеились")
        r = c.post_json(f"/api/patients/{pid_b}/profile", {"name": "Sotie Aparte",
                                                          "phone": "068 111 222"})
        res.ok("чужой номер в фише назван вслух", r.msg == "ok_tel_dup",
               f"msg {r.msg!r} — запись из журнала уедет непредсказуемо кому")
        r = c.post_json(f"/api/patients/{pid_a}/profile", {"name": "Sot Comun",
                                                          "phone": "068111222"})
        res.ok("свой номер про себя не предупреждает… нельзя: дубль уже есть",
               r.msg == "ok_tel_dup", f"msg {r.msg!r}")
        r = c.post_json(f"/api/patients/{pid_b}/profile", {"name": "Sotie Aparte", "phone": ""})
        r = c.post_json(f"/api/patients/{pid_a}/profile", {"name": "Sot Comun",
                                                          "phone": "068111222"})
        res.ok("уникальный свой номер сохраняется без предупреждения",
               r.msg == "ok_card", f"msg {r.msg!r} — баннер кричал бы на "
               "каждом пересохранении, и его перестали бы читать")

        # --- поиск: дата рождения, как её диктуют (01.01.2003) ---
        c.post_json("/api/patients", {"name": "Cautare Data", "birth_date": "2003-01-01",
                                     "phone": "067000001"})
        res.ok("поиск 01.01.2003 находит по дате рождения",
               "Cautare Data" in _names(c, "q=01.01.2003"), "формат стойки не понят")
        res.ok("поиск 1.1.2003 (без ведущих нулей) находит",
               "Cautare Data" in _names(c, "q=1.1.2003"),
               "ведущие нули стали обязательными")
        res.ok("чужая дата не находит",
               "Cautare Data" not in _names(c, "q=02.01.2003"),
               "дата матчится слишком широко")

        # --- цифры ищутся и в notes: номер второго человека на семейном ---
        c.post_json(f"/api/patients/{pid_b}/profile", {"name": "Sotie Aparte", "phone": "",
                                                      "notes": "tel. propriu: 069 555 444 (numărul familiei la soț)"})
        res.ok("номер из notes находится поиском",
               "Sotie Aparte" in _names(c, "q=069555444"),
               "совет «номер второго — в notițe» делал бы человека ненаходимым")
        # (галочку «fără telefon» в окнах записи держат проверки клиента)


def suite_patient_card(res: Result) -> None:
    """Фиша: профиль, зубная формула, план лечения, алерты, архив."""
    with Server() as s:
        c = Client(s.url).login()
        c.post_json("/api/schedule/appointments", {"date": _d(1), "time": "09:00",
                                                  "doctor": "d2", "service": "consult",
                                                  "name": "Card Test", "phone": "022654654"})
        pid = pid_by_phone(c, "022654654")

        r = c.post_json(f"/api/patients/{pid}/profile", {"name": "Card Test Nou",
                                                        "phone": "022654654",
                                                        "email": "test@example.com"})
        res.check("профиль сохраняется", r.msg, "ok_card")
        res.check("новое имя видно в карточке", _card(c, pid)["name"], "Card Test Nou")

        # Порядок карточек фиши — раскладка экрана React (вкладки B6, 26.09;
        # до 13.10 здесь проверялся порядок правой колонки старой страницы)

        # отказ обязан НАЗВАТЬ поле — экран подсвечивает его и раскрывает
        # форму: «Date invalide» без адреса читалось как «программа не работает»
        r = c.post_json(f"/api/patients/{pid}/profile", {"name": "Card Test Nou", "idnp": "123"})
        res.check("кривой IDNP — именованный отказ с полем",
                  (r.msg, json.loads(r.body).get("field")), ("bad_idnp", "idnp"))
        res.check("дата рождения в будущем — именованный отказ",
                  c.post_json(f"/api/patients/{pid}/profile", {"name": "Card Test Nou",
                                                              "birth_date": "2222-01-01"}).msg, "bad_bd")
        res.check("нормальная дата сохраняется",
                  c.post_json(f"/api/patients/{pid}/profile", {"name": "Card Test Nou",
                                                              "phone": "022654654",
                                                              "birth_date": "1985-03-07"}).msg,
                  "ok_card")
        res.check("в фише дата целиком, по-человечески",
                  _card(c, pid)["profile"]["birth"], "07.03.1985")

        # ⚠️ проверять msg, а не код: отказ «bad_card» — тоже 303, и с кодом
        # эта проверка была пустой. Состояние звалось "caries" (в справочнике
        # "carie"), зуб не сохранялся НИКОГДА, а тест был зелёным.
        r = c.post_json(f"/api/patients/{pid}/teeth/11", {"state": "carie", "note": "test",
                                                         "doctor": "d2", "surfaces": []})
        res.check("зуб отмечается", r.msg, "ok_card")
        res.check("состояние зуба видно в формуле",
                  json.loads(r.body)["data"]["teeth"]["11"]["title"], "11 · Carie · test")

        r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Plombă 11", "tooth": "11",
                                                     "price": "1200"})
        res.check("пункт плана добавляется", (r.status, r.msg), (200, "ok_card"))
        items = _card(c, pid)["plan"]["items"]
        res.check("пункт плана виден в карточке", [it["procedure"] for it in items], ["Plombă 11"])

        # ---- статусы плана: НАПРАВЛЕННЫЕ рёбра, а не кольцо (08-07) ----
        iid = items[0]["id"]

        def plan() -> dict:
            return _card(c, pid)["plan"]

        def flip(to: str) -> str:
            return c.post_json(f"/api/patients/{pid}/plan/{iid}/status", {"to": to}).msg

        res.check("из Planificat сразу в финал нельзя", flip("finalizat"), "bad_card")
        res.check("Începe: в работу — можно", flip("in_lucru"), "")
        res.check("у работы следующий шаг — «Finalizează»", plan()["items"][0]["next"], "finalizat")
        res.check("из работы назад в Planificat нельзя", flip("planificat"),
                  "bad_card")
        res.check("Finalizează — можно", flip("finalizat"), "")
        pl = plan()
        res.check("дата завершения видна", pl["items"][0]["done"], clinic_today().strftime("%d.%m.%Y"))
        # активного не осталось — вкладка по умолчанию сама «Finalizate»,
        # а не пустой экран
        res.check("без активных открыта вкладка Finalizate", pl["default_tab"], "finalizat")
        res.check("прогресс честный (1/1 finalizate)",
                  (pl["n_track"], pl["counts"].get("finalizat"), pl["pct_done"]), (1, 1, 100))
        # появился новый активный пункт — финал уходит с глаз по умолчанию
        c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Detartraj", "price": "500"})
        pl = plan()
        shown = set(_card(c, pid)["options"]["tab_states"][pl["default_tab"]])
        by = {it["procedure"]: it for it in pl["items"]}
        res.ok("законченное спрятано, когда есть активное",
               pl["default_tab"] == "act" and by["Plombă 11"]["status"] not in shown,
               f"финал остался в активной вкладке ({pl['default_tab']})")
        res.ok("активный пункт видим", by["Detartraj"]["status"] in shown,
               "активное спрятали заодно")
        res.check("у финала только «Redeschide», не «Începe» и не отказ",
                  (by["Plombă 11"]["next"], by["Plombă 11"]["refusable"]), ("in_lucru", False))
        res.check("воскресить финал в Planificat нельзя", flip("planificat"),
                  "bad_card")
        res.check("Redeschide: назад в работу — можно", flip("in_lucru"), "")

        # ---- платежи и баланс (08-07): долг = финализированное − оплачено ----
        res.check("довершаем Plombă обратно", flip("finalizat"), "")

        def fin() -> dict:
            return _card(c, pid)["finance"]

        res.check("долг равен цене финализированного",
                  (fin()["debt"], fin()["sold"]), (1200, {"kind": "bad", "amount": 1200}))
        res.check("платёж записывается",
                  c.post_json(f"/api/patients/{pid}/payments", {"amount": "500",
                                                               "method": "numerar",
                                                               "note": "avans"}).msg, "ok_pay")
        res.check("долг уменьшился до 700", fin()["debt"], 700)
        res.check("оплата остатка картой",
                  c.post_json(f"/api/patients/{pid}/payments", {"amount": "700",
                                                               "method": "card"}).msg, "ok_pay")
        res.check("после полной оплаты — achitat integral", fin()["sold"], {"kind": "ok", "amount": 0})
        c.post_json(f"/api/patients/{pid}/payments", {"amount": "300", "method": "numerar"})
        res.check("переплата показана авансом", fin()["sold"], {"kind": "plus", "amount": 300})
        res.check("нулевая сумма отбита",
                  c.post_json(f"/api/patients/{pid}/payments", {"amount": "0",
                                                               "method": "numerar"}).msg, "bad_pay")
        res.check("выдуманный метод отбит",
                  c.post_json(f"/api/patients/{pid}/payments", {"amount": "100",
                                                               "method": "crypto"}).msg, "bad_pay")
        pay_id = fin()["payments"][0]["id"]          # свежий — аванс 300
        res.check("директор удаляет платёж",
                  c.post_json(f"/api/patients/{pid}/payments/{pay_id}/delete", {}).msg, "pay_del")
        card = _card(c, pid)
        res.check("после удаления снова полная оплата", card["finance"]["sold"], {"kind": "ok", "amount": 0})
        res.ok("удаление оставило след в летописи",
               any(a["text"].startswith("Plată ștearsă") for a in card["activity"]["items"]),
               "летопись молчит про удаление")

        r = c.post_json(f"/api/patients/{pid}/alerts", {"kind": "allergy",
                                                       "text": "Alergie la penicilină"})
        res.check("предупреждение добавляется", (r.status, r.msg), (200, "ok_card"))
        res.ok("предупреждение видно в карточке",
               any("penicilină" in a["text"] for a in _card(c, pid)["alerts"]),
               "алерт не показан")

        # архив = скрыть из списка «недавних», но по явному запросу найти можно:
        # карточку с историей лечения нельзя терять, её именно прячут
        c.post_json(f"/api/patients/{pid}/archive", {"on": True})
        lst = _plist(c)
        # не «пусто, значит ушёл»: список признаётся, что спрятал одного
        res.check("архивный ушёл из списка недавних (спрятан, а не потерян)",
                  ("Card Test Nou" in [r["name"] for r in lst["rows"]], lst["hidden_arh"]),
                  (False, 1))
        res.ok("архивный находится по явному поиску",
               "Card Test Nou" in _names(c, "q=Card+Test"),
               "архивный потерялся совсем")


def suite_dashboard(res: Result) -> None:
    """Панель: подсказка блока, загрузка кресел, повестка, метки подсветки.

    Всё перечисленное ломается МОЛЧА — экран остаётся целым на вид. Отдельная
    ценность у процента загрузки: он обязан совпадать с тем, что за тот же
    день показывает раздел «Statistici», иначе клиника увидит два разных
    числа про одного врача и перестанет верить обоим.

    День берётся завтрашний намеренно: сегодняшний зависит от часа прогона —
    к вечеру вся повестка «прошедшая», и проверки стали бы плавающими.
    (Плитки «Azi» с мини-графиками жили на старой панели и ушли с ней 13.10;
    React их не рисует с 01.10.)
    """
    with Server(env={"DENTART_TOKEN_UNREADABLE": "1"}) as s:
        c = Client(s.url).login()
        day = _d(1)
        for time, doc, svc, name in (("09:00", "d2", "consult", "Ana Test"),
                                     ("11:00", "d2", "long", "Vlad Test"),
                                     ("10:00", "d3", "hygiene", "Marian Test")):
            add_appt(c, day, time, name, "0691" + time.replace(":", ""), doc, svc)
        live = panel_live(c, day)
        blocks = [b for col in live["canvas"]["columns"] for b in col["blocks"]]

        # ⚠️ Короткая запись не влезает в свой ряд: получасовая у клиники — 22px
        # при содержимом на 43. Экран ужимает текст в строку, а совсем узкой
        # записи убирает его совсем, и тогда подсказка — единственное, что
        # отвечает «кто это», не открывая карточку. Собирает её СЕРВЕР.
        res.check("подсказка блока несёт время, длительность, услугу и имя",
                  next((b["title"] for b in blocks if b.get("name") == "Ana Test"), ""),
                  "09:00 · 60′ · Consultație · Ana Test")
        # ⚠️ Ступень «только имя» уже терялась однажды: короткая запись
        # проваливалась мимо неё сразу в «текста нет» и стояла в журнале
        # безымянным цветным пятном. Имя прячет ТОЛЬКО последняя ступень.
        gcss = c.get("/static/css/panel.css").body
        tiny = gcss.split(".gappt.tiny b{")[1].split("}")[0] if ".gappt.tiny b{" in gcss else ""
        res.ok("имя прячет только последняя ступень лестницы",
               ".gappt.tiny small{display:none}" in gcss
               and ".gappt.bare b,.gappt.bare small" in gcss
               and tiny and "display:none" not in tiny,
               "у короткой записи спрятано имя — в журнале останется пятно без имени")
        # ⛔ Вид карточки «время впереди» (03.10) переносит строки flex-ом, а
        # не сеткой: строки сетки при нехватке высоты УЖИМАЮТСЯ (у детей
        # overflow:hidden, минимум нулевой), текст режется внутри строк, а блок
        # не переполняется — подгонка не видит ничего, и получасовой визит
        # остаётся «полным» с обрезками вместо имени. Поймано замером в Edge;
        # набор без браузера пикселей не видит, поэтому стережём само правило.
        grid = [sel.strip() for sel, body in
                re.findall(r"([^{}]*\.gappt[^{}]*)\{([^}]*)\}", gcss)
                if "display:grid" in body.replace(" ", "")]
        res.ok("блок канвы не раскладывается сеткой", not grid,
               f"строки сетки ужмутся, и подгонка ослепнет: {grid[:2]}")
        # ⚠️ <small> браузер уменьшает сам (font-size:smaller): без явного
        # кегля вторая строка полного блока — 10px, то самое «мелко»,
        # ради которого вид карточки менялся (03.10).
        res.ok("вторая строка полного блока — с явным кеглем",
               ".gappt:not(.slim):not(.tiny):not(.bare):not(.gnote) small{font-size:var(--fs-s)}"
               in gcss, "кегль второй строки отдан браузеру — она снова 10px")

        # ⭐ 60′ + 120′ = 180 занятых из 840 рабочих (клиника фикстуры 07–21)
        d2 = next(col for col in live["canvas"]["columns"] if col["id"] == "d2")
        res.check("загрузка кресла врача: минуты и процент",
                  (d2["occupancy"]["busy"], d2["occupancy"]["cap"], d2["occupancy"]["pct"]),
                  (180, 840, 21))
        # «Statistici» — экран React: та же цифра приходит в /api/stats
        st = json.loads(c.get(f"/api/stats?from={day}&to={day}").body)["data"]
        res.check("тот же процент в «Statistici» за тот же день",
                  next((x["pct"] for x in st["doctors"] if x["id"] == "d2"), None), 21)
        # деньги: период назван, настоящие деньги отдельно от оценки, «за сегодня»
        stk = {x["key"]: x for x in st["board"]["kpis"]}
        res.check("прошлый период назван по имени (день)",
                  stk["incasari"]["trend"]["label"], "față de ziua precedentă")
        res.ok("дневная выручка на месте",
               {"today_cash", "today_estimated"} <= set(st["board"]["money"]),
               f"{st['board']['money']}")
        res.ok("«Încasări» — настоящие деньги отдельно от оценки",
               stk["incasari"]["label"] == "Încasări"
               and {"cash", "estimated"} <= set(st["board"]["money"]),
               "нет карточки реальных денег")
        res.check("у недельного периода имя недели",
                  json.loads(c.get("/api/stats").body)["data"]["board"]["prev_name"],
                  "săptămâna trecută")

        ag = live["agenda"]
        res.check("в повестке все три визита, по времени",
                  [x["time"] for x in ag["items"]], ["09:00", "10:00", "11:00"])
        res.check("завтрашний день не приглушён как прошедший — состояния нет",
                  [x["state"] for x in ag["items"]], [None, None, None])
        c.post_json(f"/api/schedule/appointments/{ag['items'][0]['id']}/status",
                    {"to": "cancelled"})
        res.check("отменённый уходит из повестки",
                  panel_live(c, day)["agenda"]["count"], 2)

        # ⭐ 60′+120′+60′ занятых из 3×840 рабочих (d1 в архиве, активны d2-d4)
        res.check("загрузка кресел дня честная: 240 из 2520 минут = 10",
                  live["occupancy"], {"value": 10})
        res.check("метки текущего часа нет в чужом дне",
                  [h["h"] for h in live["canvas"]["hours"] if h["now"]], [])
        res.check("день канвы помечен своей датой (ключ подсветки приехавших)",
                  live["canvas"]["date"], day)

        # ⚠️ выключатель анимаций обязан стоять В ШАПКЕ: уедет в конец body —
        # успеет отрисоваться конечный кадр, и анимация пойдёт рывком назад
        head = c.get(f"/admin?date={day}").body.split("<body")[0]
        res.ok("выключатель анимаций стоит в <head>",
               "dp_auto" in head and "classList.add('anim')" in head,
               "скрипт не в шапке")
        css = c.get("/static/css/panel.css").body
        res.ok("движение выключается системной настройкой",
               "prefers-reduced-motion" in css, "нет уважения к настройке ОС")


def suite_grid_edges(res: Result) -> None:
    """Края канвы дня: крайние ПОЛНОСТЬЮ закрытые часы уходят в полоску.

    Своя клиника (`clinic_hours.json`): часы 07-21, у всех врачей 09-17, обед
    13-14. В `clinic_test.json` врачи наследуют часы клиники, поэтому закрытых
    рядов там не бывает вовсе и проверять было бы нечего.

    ⚠️ Опасность здесь не косметическая: срезанный ряд может УНЕСТИ С СОБОЙ
    запись вне графика. Визит, назначенный на закрытый час (часы поменяли после
    брони), обязан оставаться видимым — иначе клиника считает время свободным и
    посадит на него второго пациента. Это и стережёт вторая половина набора.

    ⚠️ Обед — тоже полностью закрытый час, но В СЕРЕДИНЕ. Он обязан остаться
    рядом: время на канве линейно, блоки стоят долями часа от первого ряда, и
    выкинутый средний час сдвинул бы все записи после обеда.
    (До 06.10 «Programări» рисовал таблицу со своими рядами — тот же день
    говорил на двух экранах разное; с 06.10 канва одна, и проверка одна.)
    """
    def hours(cv: dict) -> list[int]:
        return [h["h"] for h in cv["hours"]]

    def cells(cv: dict, dk: str) -> dict:
        col = next(x for x in cv["columns"] if x["id"] == dk)
        return dict(zip(hours(cv), col["cells"]))

    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        day = _d(1)
        cv = day_model(c, day)["canvas"]
        res.check("закрытые края ушли в полоски — с часами закрытия",
                  cv["bands"], {"top": {"from": "07:00", "to": "09:00"},
                                "bottom": {"from": "17:00", "to": "21:00"}})
        res.check("ряды — рабочие часы врачей, без дыр, обед РЯДОМ",
                  hours(cv), list(range(9, 17)))
        res.check("в обеденный ряд записать нельзя, в рабочий час — можно",
                  (cells(cv, "d2")[13], cells(cv, "d2")[9]), (False, True))

        # запись вне графика: 07:00 у врача, который работает с 09:00.
        # ⚠️ Окно записи такую НЕ принимает — сервер проверяет график врача
        # (outside_doc, 08-15). Реальный путь появления такой записи — часы
        # врача сузили ПОСЛЕ брони; сеем её маршрутом фиши, который график
        # врача не перепроверяет, — канве всё равно, откуда визит.
        add_appt(c, day, "10:00", "Devreme Test", "0690700")
        pid_e = pid_by_phone(c, "0690700")
        c.post_json(f"/api/patients/{pid_e}/appoint", {"date": day, "time": "07:00",
                                                      "doctor": "d2", "service": "consult"})
        cv2 = day_model(c, day)["canvas"]
        res.check("запись вне графика ДЕРЖИТ свой ряд, и 08:00 больше не край",
                  hours(cv2)[:3], [7, 8, 9])
        res.ok("она видна на канве",
               any(b.get("name") == "Devreme Test" and b["time"] == "07:00"
                   for col in cv2["columns"] for b in col["blocks"]),
               "блока записи нет — время выглядит свободным")
        res.check("полоска сверху пропала, раз ряд занят; нижняя на месте",
                  (cv2["bands"]["top"], cv2["bands"]["bottom"]),
                  (None, {"from": "17:00", "to": "21:00"}))
        # ⭐ Час вне окна ВРАЧА: клиника открыта, но принимать некому — ряд
        # есть (в нём визит), а записать туда нельзя (пациент пришёл бы в
        # пустой кабинет)
        res.check("вне графика врача записать нельзя, хоть ряд и есть",
                  cells(cv2, "d2")[7], False)

    # ---- запись, которую обед накрыл ПОСЛЕ брони ----
    # ⛔ Час без ряда никто не спрашивает: вместе с рядом исчез бы и визит. В
    # списке дня он остаётся, слот занят — а сетка показывает пустоту, и
    # регистратура сажает на это время второго пациента.
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        add_appt(c, day, "13:00", "Pauza Test", "0690713")
        res.ok("у клиники без обеда закрытых рядов нет вовсе",
               all(cells(day_model(c, day)["canvas"], "d2").values()),
               "штриховка появилась там, где клиника работает весь день")

        r = c.post_json("/api/settings/hours", {"hours": {d: [7, 21, 13, 14] for d in
                                                          ("mon", "tue", "wed", "thu",
                                                           "fri", "sat", "sun")}})
        res.check("обед введён задним числом", r.msg, "ok_set")
        after = day_model(c, day)["canvas"]
        res.ok("визит, накрытый новым обедом, остался на канве",
               any(b.get("name") == "Pauza Test" for col in after["columns"]
                   for b in col["blocks"]),
               "визит исчез вместе с рядом")
        res.check("его ряд есть, и записать в него нельзя — клиника на обеде",
                  (13 in hours(after), cells(after, "d2").get(13)), (True, False))


def suite_analytics(res: Result) -> None:
    """Аналитика: сравнение периодов, график по дням, загрузка, деньги, врачи,
    лента событий — по ответу /api/stats. Всё выведенное ломается молча, а
    ответ при этом 200.

    День завтрашний, как в suite_dashboard: сегодняшний зависит от часа прогона.

    Сервер — grandfather-клиника (флаг «токен нечитаем» = tg_configured): доля
    бота в разборе записей есть только у клиник с ботом; ветку «без бота»
    стережёт suite_bot_ui.
    """
    with Server(env={"DENTART_TOKEN_UNREADABLE": "1"}) as s:
        c = Client(s.url).login()
        day = _d(1)
        for time, doc, svc, name, phone in (
                ("09:00", "d2", "consult", "Stat Unu", "069000001"),
                ("11:00", "d2", "long", "Stat Doi", "069000002"),
                ("10:00", "d3", "hygiene", "Stat Trei", "069000003")):
            c.post_json("/api/schedule/appointments", {"date": day, "time": time,
                                                      "doctor": doc, "service": svc,
                                                      "name": name, "phone": phone})
        # прошлый период той же длины: одна запись «сегодня» для сравнения
        # (08:00 — ручная запись намеренно принимает прошедший час текущего дня)
        c.post_json("/api/schedule/appointments", {"date": _d(0), "time": "08:00",
                                                  "doctor": "d4", "service": "consult",
                                                  "name": "Stat Ieri", "phone": "069000004"})

        # Экран рисует React (старая страница снята 12.10): цифры — из /api/stats,
        # той же модели, что видит директор (карточки `board`, врачи, лента).
        def stats(a: str, b: str) -> dict:
            return json.loads(c.get(f"/api/stats?from={a}&to={b}").body)["data"]

        d = stats(day, day)
        k = {x["key"]: x for x in d["board"]["kpis"]}
        # С 08-07 прошлый период называется ПО ИМЕНИ (день/неделя/месяц), а не
        # безымянной «perioada trecută» — у каждой из четырёх карточек
        res.ok("четыре карточки с трендом к прошлому периоду",
               len(k) == 4 and all(x["trend"]["label"] == "față de ziua precedentă"
                                   for x in k.values()),
               f"{[(x['key'], x['trend']['label']) for x in k.values()]}")
        res.check("график по дням: один день — одна корзина с тремя записями",
                  (d["board"]["series"]["bucket"], d["board"]["series"]["appts"]),
                  ("day", [3]))
        # у клиники с ботом его доля едет строкой разбора записей (кольца нет)
        res.ok("доля бота названа в разборе записей",
               "prin bot" in k["programari"]["sub"], k["programari"]["sub"])
        res.ok("выдуманных источников нет нигде",
               "Google" not in json.dumps(d) and "Instagram" not in json.dumps(d),
               "в аналитике выдуманные каналы")
        # 3 визита (60+120+60=240′) на 3 активных врача × 840′ = 240/2520 ≈ 10%
        res.check("средняя загрузка считается по активным врачам",
                  k["ocupare"]["value"], 10)
        res.ok("деньги подписаны как оценка по прайсу",
               "orientative" in d["hint"], "оценка выдаётся за бухгалтерию")
        res.ok("лента событий с именем и пациентом",
               any(a["name"] and isinstance(a["patient_id"], int) for a in d["activity"]),
               f"{d['activity'][:2]}")
        names = [x["name"] for x in d["doctors"]]
        res.ok("врачи отсортированы по загрузке",
               "Dr. Activ Doi" in names and "Dr. Activ Trei" in names
               and names.index("Dr. Activ Doi") < names.index("Dr. Activ Trei"),
               f"{names}")

        # пустой период: записей ноль, но период существовал — карточки нулевые,
        # ряд по дням есть и лежит по полу
        empty = stats(_d(40), _d(46))
        ke = {x["key"]: x for x in empty["board"]["kpis"]}
        res.ok("пустой период не роняет аналитику",
               ke["programari"]["value"] == 0 and ke["ocupare"]["value"] == 0
               and empty["board"]["series"]["appts"] == [0] * 7,
               f"{empty['board']['series']['appts']}")

        # у периода «сегодня» прошлый кусок той же длины — вчера (он пуст), и
        # сегодняшний визит 08:00 обязан дать «+1 … (atunci 0)», а не «neschimbat»
        tr = {x["key"]: x for x in stats(_d(0), _d(0))["board"]["kpis"]}["programari"]["trend"]
        res.check("у «сегодня» прошлый период — вчера",
                  (tr["value"], tr["label"], tr["note"]),
                  ("+1", "față de ziua precedentă", " (atunci 0)"))


def suite_patients_list(res: Result) -> None:
    """Раздел «Pacienți»: фильтры, страницы, предпросмотр, экспорт, новая фиша.

    Статуса пациента в базе НЕТ — он выводится из алертов, плана и давности
    визита. Именно это здесь и стережётся: выведенная цифра ломается молча,
    экран остаётся кодом 200 и выглядит нормально. Экран — React (13.10):
    проверяется то, что он получает (`/api/patients*`), и книга Excel — та
    же выборка целиком.
    """
    with Server() as s:
        c = Client(s.url).login()

        def add(name: str, phone: str, day: int, time: str, doc: str) -> str:
            c.post_json("/api/schedule/appointments", {"date": _d(day), "time": time,
                                                      "doctor": doc, "service": "consult",
                                                      "name": name, "phone": phone})
            return str(pid_by_phone(c, phone))

        vechi = add("Elena Bălan", "068111222", -400, "10:00", "d2")
        alerg = add("Dumitru Ganea", "069222444", -5, "11:00", "d3")
        plan = add("Maria Ionescu", "069987654", -10, "12:00", "d2")
        arh = add("Svetlana Ciobanu", "078333555", -12, "13:00", "d4")
        add("Radu Marin", "079444666", 2, "14:00", "d2")

        c.post_json(f"/api/patients/{alerg}/alerts", {"kind": "allergy", "text": "Penicilină"})
        c.post_json(f"/api/patients/{plan}/plan", {"procedure": "Coroană", "price": "1200"})
        c.post_json(f"/api/patients/{arh}/archive", {"on": True})
        c.post_json(f"/api/patients/{vechi}/profile", {"name": "Elena Bălan",
                                                      "phone": "068111222",
                                                      "email": "elena@example.com"})
        # добор до второй страницы: пагинацию нечем проверить на пяти строках
        for i in range(8):
            c.post_json("/api/patients", {"name": f"Pacient Masiv {i}",
                                         "phone": f"0611000{i:02d}"})

        sm = json.loads(c.get("/api/patients/summary").body)["data"]
        res.check("три числа над списком, денежного среди них нет (раздел — не выручка)",
                  [t["icon"] for t in sm["tiles"]], ["users", "med", "cal"])

        def rows(qs: str = "") -> list[dict]:
            return _plist(c, qs)["rows"]

        by = {r["name"]: r for r in rows()}
        res.check("в списке все неархивные", len(by), 12)
        res.ok("архивный скрыт по умолчанию", "Svetlana Ciobanu" not in by,
               "архивный виден без запроса")
        res.ok("архивный находится явным поиском",
               "Svetlana Ciobanu" in _names(c, "q=Svetlana"),
               "архивный потерялся совсем")

        # статусы выводятся, а не хранятся — проверяем каждую ветку
        res.check("аллергия даёт «Necesită atenție»", by["Dumitru Ganea"]["status"], "atentie")
        res.check("фильтр «внимание» — только он", len(rows("st=atentie")), 1)
        res.check("фильтр «в лечении» — только план", len(rows("st=tratament")), 1)
        res.check("год без визита = «Inactiv»", by["Elena Bălan"]["status"], "inactiv")
        res.check("фильтр «архив» показывает архивного", len(rows("st=arhivat")), 1)

        res.check("фильтр по врачу", len(rows("med=Dr.+Activ+Trei")), 1)
        res.check("фильтр по каналу «recepție»", len(rows("ch=manual")), 12)
        res.check("фильтр по каналу «telegram»", len(rows("ch=tg")), 0)
        res.ok("поиск не замечает диакритику",
               "Elena Bălan" in _names(c, "q=balan"), "«balan» не нашёл «Bălan»")
        res.ok("поиск по e-mail",
               "Elena Bălan" in _names(c, "q=elena@example"), "e-mail не ищется")
        res.ok("поиск по телефону в любом формате",
               "Radu Marin" in _names(c, "q=444+666"),
               "пробел в номере ломает поиск")
        # «Nimic găsit» вместо пустой таблицы рисует экран — по пустой выдаче
        res.check("ничего не найдено — пустая выдача, а не ошибка",
                  (_plist(c, "q=zzzzz")["rows"], _plist(c, "q=zzzzz")["total"]), ([], 0))

        d = _plist(c, "per=10")
        res.check("страница ограничена per, счёт честный (Afișare 1–10 din 12)",
                  (len(d["rows"]), d["total"], d["page"], d["pages"]), (10, 12, 1, 2))
        res.check("вторая страница — остаток", len(rows("per=10&page=2")), 2)
        d = _plist(c, "per=10&page=99")
        res.check("страница за пределом схлопывается на последнюю (Afișare 11–12)",
                  (d["page"], len(d["rows"])), (2, 2))
        d = _plist(c, "per=7")
        res.check("чужое per отбрасывается, а не ломает страницу",
                  (d["per"], len(d["rows"])), (20, 12))
        names = _names(c, "sort=name")
        res.ok("сортировка по имени", names == sorted(names, key=str.lower),
               f"порядок {names}")

        peek = c.get(f"/api/patients/{plan}/peek")
        frag = json.loads(peek.body)["data"]["html"] if peek.status == 200 else ""
        res.ok("предпросмотр отдаёт кусок разметки, не страницу",
               "Plan de tratament" in frag and "<html" not in frag, f"код {peek.status}")
        res.ok("предпросмотр показывает аллергию",
               "Penicilină" in json.loads(c.get(f"/api/patients/{alerg}/peek").body)["data"]["html"],
               "алерта нет в панели")
        res.check("предпросмотр несуществующего", c.get("/api/patients/9999/peek").status,
                  404)
        # CSV снят 13.10 (слово Олега 12.10: «CSV удаляем, остаётся xlsx»)
        res.check("CSV-выгрузки списка больше нет — только книга",
                  c.get("/admin/patients.csv").status, 404)

        r = c.post_json("/api/patients", {"name": "Grigore Nou", "phone": "060777888",
                                         "birth_date": "1978-02-02", "email": "gn@example.com"})
        res.check("новая фиша заводится", r.msg, "new_pat")
        new_id = json.loads(r.body)["data"]["id"]
        res.ok("новый пациент попал в список", "Grigore Nou" in _names(c), "нет в списке")
        # ⭐ ключ manual:{цифры} склеивает по телефону: повтор обязан ОТКРЫТЬ
        # существующую фишу, а не переписать в ней имя
        r = c.post_json("/api/patients", {"name": "Alt Nume", "phone": "060 777 888"})
        res.check("тот же телефон — не новый пациент", r.msg, "dup_pat")
        res.check("повтор ведёт в ту же фишу", json.loads(r.body)["data"]["id"], new_id)
        res.check("имя существующего не перезаписано", _card(c, new_id)["name"], "Grigore Nou")
        r = c.post_json("/api/patients", {"name": "Fara Telefon"})
        res.check("без телефона тоже заводится", r.msg, "new_pat")
        res.ok("заведённый на рецепции — канал «recepție»",
               "Fara Telefon" in _names(c, "ch=manual"),
               "канал определился неверно")
        res.check("без имени не заводится",
                  c.post_json("/api/patients", {"name": "  "}).msg, "bad_pat")

        # ⭐ 08-13, скриншот Олега: «Exportă» отдавал CSV, и Excel съедал
        # ведущий ноль телефона, а даты показывал решёткой — та же беда, что
        # у выгрузки дня до 1.19.23. Кнопку рисует экран React: её адрес —
        # книга, и в исходнике экрана CSV не упоминается.
        screen = (BOT.parent / "frontend" / "src" / "features" / "patients"
                  / "PatientsSearchScreen.tsx").read_text(encoding="utf-8")
        res.ok("кнопка «Exportă» ведёт на книгу, не на CSV",
               "/admin/patients.xlsx" in screen and "patients.csv" not in screen,
               "кнопка списка отдаёт не книгу")
        xls = c.get("/admin/patients.xlsx")
        res.ok("экспорт-книга отдаётся",
               xls.status == 200 and xls.raw[:2] == b"PK",
               f"код {xls.status}, первые байты {xls.raw[:4]!r}")
        sheet = zipfile.ZipFile(io.BytesIO(xls.raw)).read(
            "xl/worksheets/sheet1.xml").decode("utf-8")
        res.ok("телефон в книге — строкой, с ведущим нулём",
               ">060777888<" in sheet,
               "060777888 не строкой — Excel снова съест ноль")
        # дата рождения — ДАТОЙ (серийным числом Excel), не текстом
        serial = str((date(1978, 2, 2) - date(1899, 12, 30)).days)
        res.ok("дата рождения — датой, а не текстом",
               f"<v>{serial}</v>" in sheet,
               "1978-02-02 не серийным числом — в Excel это текст")
        # ⭐ Книга — та же выборка, что экран (`_pl_select` + SQL, 13.10):
        # фильтр режет строки, архив скрыт, пока его не спросили поиском
        def book(qs: str) -> str:
            r = c.get("/admin/patients.xlsx" + (f"?{qs}" if qs else ""))
            return zipfile.ZipFile(io.BytesIO(r.raw)).read("xl/worksheets/sheet1.xml").decode("utf-8")

        at = book("st=atentie")
        res.ok("экспорт-книга слушается фильтров: шапка и один пациент",
               at.count("<row ") == 2 and "Dumitru Ganea" in at,
               f"строк {at.count('<row ')}")
        full = book("")
        res.ok("книга без фильтра — все живые, архивный скрыт",
               full.count("<row ") == 15 and "Svetlana" not in full,
               f"строк {full.count('<row ')} (ждём шапку и 14)")
        res.ok("архивный уезжает в книгу, когда его спросили поиском",
               "Svetlana" in book("q=Svetlana"), "поиск по архиву книга не слушает")

        anon = Client(s.url)
        for path in ("/admin/search", "/admin/patients.xlsx"):
            res.ok(f"без входа {path} не отдаётся", anon.get(path).status == 303,
                   "отдал без входа")
        res.check("без входа предпросмотр не отдаётся (JSON API — 401)",
                  anon.get("/api/patients/1/peek").status, 401)
        res.check("без входа пациент не заводится (JSON API — 401)",
                  anon.post_json("/api/patients", {"name": "X"}).status, 401)


def suite_money(res: Result) -> None:
    """Колонка «Sold» в списке пациентов и печатный отчёт кассы (1.19.0).

    Долг конкретного пациента видит ЛЮБАЯ роль — это операционка стойки, кому
    звонить. Касса за день это выручка клиники, и она за `PERM_MONEY`; что врача
    туда не пускают, проверяет `test_pin.suite_roles`.
    """
    with Server() as s:
        c = Client(s.url).login()

        def add(name: str, phone: str, at: str) -> str:
            c.post_json("/api/schedule/appointments", {"date": _d(1), "time": at,
                                                      "doctor": "d2", "service": "consult",
                                                      "name": name, "phone": phone})
            return pid_by_phone(c, phone)

        def charge(pid: int, price: int) -> None:
            """Начислить: пункт плана с ценой и довести его до finalizat —
            долг считается ТОЛЬКО по финализированным (как в фише)."""
            r = c.post_json(f"/api/patients/{pid}/plan", {"procedure": "Plombă", "tooth": "11",
                                                         "price": str(price)})
            iid = json.loads(r.body)["data"]["plan"]["items"][0]["id"]
            c.post_json(f"/api/patients/{pid}/plan/{iid}/status", {"to": "in_lucru"})
            c.post_json(f"/api/patients/{pid}/plan/{iid}/status", {"to": "finalizat"})

        def row(qs: str, pid: int) -> dict:
            """Строка ИМЕННО этого пациента в выдаче списка (пустой словарь —
            его в выдаче нет). Сумму ищем в его строке, а не по всей выдаче:
            она встретилась бы у соседа, и проверка стала бы пустой."""
            return next((r for r in _plist(c, qs)["rows"] if r["id"] == pid), {})

        dat = add("Datornic Unu", "022110011", "09:00")
        avn = add("Avansat Doi", "022220022", "10:00")
        charge(dat, 1200)
        charge(avn, 500)
        res.check("аванс записывается",
                  c.post_json(f"/api/patients/{avn}/payments", {"amount": "800",
                                                               "method": "card"}).msg, "ok_pay")

        # колонку «Sold» (долг красным, аванс зелёным) рисует экран по числу
        res.check("долг — в строке должника числом", row("", dat).get("debt"), 1200)
        res.check("аванс — отрицательным долгом", row("", avn).get("debt"), -300)

        res.ok("фильтр «с долгом» оставил должника", row("dat=da", dat) != {},
               "должник пропал")
        res.ok("фильтр «с долгом» убрал переплатившего",
               row("dat=da", avn) == {}, "аванс попал в должники")
        res.ok("фильтр «с авансом» оставил переплатившего",
               row("dat=avans", avn) != {}, "аванс пропал")
        res.ok("фильтр «с авансом» убрал должника", row("dat=avans", dat) == {},
               "должник попал в авансы")

        order = [r["id"] for r in _plist(c, "sort=debt")["rows"]]
        res.ok("сортировка по долгу: должник выше аванса",
               order.index(dat) < order.index(avn), "порядок не по сумме")

        xls = c.get("/admin/patients.xlsx")
        sheet = zipfile.ZipFile(io.BytesIO(xls.raw)).read("xl/worksheets/sheet1.xml").decode("utf-8")
        res.ok("в книге есть колонка Sold", "Sold (MDL)" in sheet,
               "выгрузка отстала от экрана")
        # число со знаком, без пробелов и валюты: иначе Excel читает колонку
        # как текст, и по ней нельзя ни просуммировать, ни отсортировать
        res.ok("в книге долг числом", "<v>1200</v>" in sheet, "долг не числом")
        res.ok("в книге аванс отрицательным", "<v>-300</v>" in sheet,
               "аванс не отличается от долга знаком")

        # ---- печатный отчёт кассы ----
        casa = c.get("/admin/casa")
        res.ok("отчёт кассы открывается", casa.status == 200, f"код {casa.status}")
        res.ok("в отчёте есть плательщик", "Avansat Doi" in casa.body,
               "платёж не попал в лист")
        res.ok("в отчёте видна сумма", "800" in casa.body, "нет суммы")
        res.ok("в отчёте есть итог по методам", "Total încasat" in casa.body,
               "нет сведения по способам оплаты")
        res.ok("метод без платежей всё равно строкой",
               "Numerar" in casa.body and "Transfer" in casa.body,
               "«сегодня не платили» неотличимо от «строку забыли»")
        res.ok("лист несёт место для подписи", "Semnătura" in casa.body,
               "лист нельзя подписать")

        # ⚠️ Час в базе UTC, лист читает человек. Ошибка не выдаёт себя ничем:
        # дата верна, формат верен, час чужой — и касса не сойдётся с ящиком.
        # ⚠️ Смотреть ТОЛЬКО в таблицу платежей: в подвале листа стоит «Tipărit»
        # с местным временем, и по всей странице проверка проходила бы вхолостую
        # даже с выброшенным astimezone (поймано мутацией).
        tbl = (casa.body.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
               if "<tbody>" in casa.body else "")
        res.ok("таблица платежей найдена", "800" in tbl, "строки платежа нет")
        ro = ZoneInfo("Europe/Chisinau")
        local = {(datetime.now(ro) - timedelta(minutes=m)).strftime("%H:%M")
                 for m in (0, 1)}
        utc = {(datetime.now(timezone.utc) - timedelta(minutes=m)).strftime("%H:%M")
               for m in (0, 1)}
        res.ok("час платежа местный", any(t in tbl for t in local),
               f"ни одного из {sorted(local)} в строке платежа")
        if not (local & utc):       # у Кишинёва сдвиг есть и зимой, и летом
            res.ok("час UTC в строку не уехал", not any(t in tbl for t in utc),
                   f"в строке час UTC {sorted(utc)} — забыт astimezone(eng.TZ)")

        empty = c.get(f"/admin/casa?d={_d(1)}")
        res.ok("день без платежей говорит об этом прямо",
               "nu au fost înregistrate" in empty.body,
               "пустой день выглядит как поломка")

        # ---- архив: куда девается пациент (вопрос Олега 08-09) ----
        # Архивация УБИРАЕТ фишу из списка. Пока это происходило молча, человек
        # возвращался в список, никого не находил и решал, что потерял запись.
        r = c.post_json(f"/api/patients/{avn}/archive", {"on": True})
        res.check("архивация называет себя отдельным сообщением", r.msg, "ok_arh")
        # проверяем ТЕКСТ ответа (его экран показывает плашкой), а не словарь:
        # «Arhivat» само по себе есть и в плашке статуса архивной фиши
        res.ok("плашка объясняет, что фиша ушла из списка",
               "nu mai apare în listă" in json.loads(r.body)["text"],
               "плашка не объясняет исчезновение")
        res.ok("архивный ушёл из списка", row("", avn) == {}, "остался в списке")
        res.check("список признаётся, что кого-то прячет (дверь «arată»)",
                  _plist(c)["hidden_arh"], 1)
        res.ok("фильтр «Arhivat» показывает архивного", row("st=arhivat", avn) != {},
               "по фильтру архив пуст")
        res.ok("поиск по имени находит архивного",
               row("q=Avansat", avn) != {}, "архивного нельзя найти поиском")
        r = c.post_json(f"/api/patients/{avn}/archive", {"on": False})
        res.check("возврат из архива — своё сообщение", r.msg, "ok_unarh")
        res.ok("вернулся в список", row("", avn) != {}, "не вернулся")


def suite_settings(res: Result) -> None:
    """Настройки: хаб из плиток, страницы-секции, сохранение по кускам.

    ⭐ Главное, что здесь стережётся, — слияние: клиника/часы/услуги живут в
    ОДНОМ clinic.json, и сохранение одной секции обязано не трогать соседние.
    Наивная нарезка на вкладки затирала бы услуги при сохранении часов — молча.
    """
    # см. suite_backup в test_privacy: без $DENTART_DATA_DIR ветка клиники
    # в прогоне не исполняется, и строка с путём проверялась бы как молчание
    # ⛔ Папку клиники уводим в сторону НАРОЧНО, и двигать надо именно её.
    # По умолчанию на стенде совпадают ВСЕ ТРИ пути — `paths.data_root()`,
    # `paths.db_dir()` и `eng.config_path().parent`, — поэтому проверка
    # «текст называет настоящую папку» зеленеет при любом источнике, в том
    # числе неверном. `paths.db_dir` про это и предупреждает: у клиники
    # `C:\ProgramData\DentPilot` и `…\data` — разные места, а совпадение
    # на стенде есть следствие раскладки, а не определение.
    # ⚠️ Развести одну только БАЗУ мало: `CLINIC_CONFIG` остаётся в `srv.dir`,
    # значит `config_path().parent` так и равен `data_root()` — а подмена
    # источника именно на него самый вероятный рецидив (первая версия
    # `layout.data_folder` была ровно такой). Сдвиг папки клиники разводит
    # все три сразу и стоит одной строки.
    srv = Server()
    root = srv.dir / "clinic-root"
    root.mkdir()
    srv.extra_env["DENTART_DATA_DIR"] = str(root)
    with srv as s:
        c = Client(s.url).login()

        # Экраны настроек рисует React (старые страницы сняты 12.10): данные —
        # из /api/settings/*, страница отдаёт узел и рамку с крошкой на хаб.
        hub = json.loads(c.get("/api/settings/hub").body)["data"]["tiles"]
        hrefs = [t["href"] for t in hub]
        res.ok("хаб — плитки секций",
               sum(h.startswith("/admin/settings/") for h in hrefs) >= 4, f"{hrefs}")
        # страница без плитки для клиники не существует — маршрут проверен ниже,
        # а здесь стережётся именно вход с хаба
        res.ok("плитка FAQ на хабе", "/admin/settings/faq" in hrefs,
               "FAQ не находима с хаба")
        for path, screen in {"/admin/settings/system": "settings_system",
                             "/admin/settings/clinic": "settings_clinic",
                             "/admin/settings/hours": "settings_hours",
                             "/admin/settings/services": "settings_services",
                             "/admin/settings/faq": "settings_faq"}.items():
            b = c.get(path)
            res.ok(f"секция {path} открывается — узел React",
                   b.status == 200 and f'data-screen="{screen}"' in b.body,
                   f"код {b.status}")
            # крошка «Setări» едет в модели рамки (`_SEC_CRUMBS`) — путь назад;
            # модель лежит в атрибуте data-shell, экранированная как HTML
            crumbs = (json.loads(html.unescape(
                b.body.split('data-shell="', 1)[1].split('"', 1)[0]))["frame"]["crumbs"]
                if 'data-shell="' in b.body else [])
            res.ok(f"из секции {path} есть путь назад",
                   any(cr.get("href") == "/admin/settings" for cr in crumbs),
                   f"нет крошки на хаб: {crumbs}")
        # «Despre DentPilot» окна Tauri (Т7): папка — ФАКТ из того же места,
        # куда программа пишет; папку клиники здесь увели в сторону нарочно
        res.check("модель оболочки называет настоящую папку клиники (Despre)",
                  shell_model(c.get("/admin").body)["about"]["data"], str(root))
        faq_items = json.loads(c.get("/api/settings/faq").body)["data"]["items"]
        # FAQ обязан называть 7-Zip: бэкап открывается им, и это единственное
        # место, где клиника об этом узнаёт
        res.ok("FAQ называет 7-Zip", any("7-Zip" in it["answer"] for it in faq_items),
               "про 7-Zip ни слова")

        # Telegram заморожен (08-08): FAQ не продаёт бота — пункты про
        # «бот ночью/в выходные» изъяты вместе с интерфейсом бота
        res.ok("FAQ не продаёт замороженного бота",
               not any("Botul primește programări" in it["question"] + it["answer"]
                       for it in faq_items),
               "пункт про бот в выходные вернулся в FAQ")

        # ⭐ Папку показываем НАСТОЯЩУЮ, а не описываем словами: раскладок две
        # (обычная и портативная), выбирает лаунчер, и пересказ устареет на
        # следующем переезде. «Stare sistem» — якорь: на эту строку ссылаются
        # и FAQ, и CITESTE-MA.txt внутри вывозного архива, поэтому её пропажа
        # обесценивает оба текста разом.
        # ⭐ Путь сверяется целиком, а не вхождением: папка базы содержит папку
        # клиники как префикс, и подстрочная проверка не отличила бы верную
        # папку от соседней (см. стенд выше).
        folder = json.loads(c.get("/api/settings/system").body)["data"]["folder"]
        res.check("«Stare sistem» показывает настоящую папку данных",
                  folder["path"], str(root))
        res.ok("FAQ называет настоящую папку, а не «папку программы»",
               any(f"<b>{root}</b>" in it["answer"] for it in faq_items)
               and not any("folderul programului" in it["answer"] for it in faq_items),
               "FAQ описывает раскладку, которой больше нет")

        # ---- сохранение по кускам: сосед не должен пострадать ----
        r = c.post_json("/api/settings/clinic", {"name": "Clinica Parțială",
                                                 "phone": "+373 60 111 222",
                                                 "address": {"ro": "str. Nouă 2", "ru": ""}})
        res.check("кусок «клиника» сохраняется", r.msg, "ok_set")
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

        r = c.post_json("/api/settings/hours", {"hours": {
            "mon": [9, 18], "tue": [9, 18], "wed": None,
            "thu": [9, 18], "fri": [9, 18, 13, 14],
            "sat": None, "sun": None}})
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

        r = c.post_json("/api/settings/services", {"services": [
            {"id": "consult", "ro": "Consultație", "ru": "Консультация",
             "price": "300 MDL", "duration": 30, "color": "", "urgent": False,
             "docs": []}]})
        res.check("кусок «услуги» сохраняется", r.msg, "ok_set")
        after = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.check("услуг стало ровно столько, сколько прислали",
                  len(after["services"]), 1)
        res.ok("врачи пережили сохранение услуг",
               len(after["doctors"]) == 4, "услуги затёрли врачей")
        res.ok("часы пережили сохранение услуг",
               after["hours"]["wed"] is None, "услуги затёрли часы")

        r = c.post_json("/api/settings/hours", {"hours": {d: None for d in
                                                          ("mon", "tue", "wed", "thu",
                                                           "fri", "sat", "sun")}})
        res.check("вся неделя закрыта — отбито", r.msg, "bad_set")

        # горячая перезагрузка: имя клиники видно сразу, без перезапуска
        r = c.post_json("/api/settings/clinic", {"name": "Clinica Redenumită",
                                                 "phone": "+373 60 111 222",
                                                 "address": {"ro": "str. Nouă 2", "ru": ""}})
        res.check("настройки сохраняются", r.msg, "ok_set")
        res.ok("новое название видно сразу",
               "Clinica Redenumită" in c.get("/admin").body,
               "hot-reload не сработал")
        res.ok("название записано в файл клиники",
               "Clinica Redenumită" in s.clinic.read_text(encoding="utf-8"),
               "clinic.json не переписан")


def suite_pwa(res: Result) -> None:
    """Значок на домашнем экране: манифест, иконки, теги в шапке.

    Манифест собирается НА ЛЕТУ, и обе причины проверяются здесь: имя и цвет
    принадлежат клинике (файл в сборке заморозил бы зелёный DentPilot на синем
    интерфейсе), а адреса внутри обязаны быть ОТНОСИТЕЛЬНЫМИ — одна и та же
    программа открывается как 127.0.0.1 и как 192.168.x.y из сети клиники."""
    with Server() as s:
        c = Client(s.url).login()

        m = c.get("/manifest.webmanifest")
        res.check("манифест отдаётся", m.status, 200)
        res.ok("манифест объявлен манифестом",
               "application/manifest+json" in m.header("content-type"),
               f"content-type: {m.header('content-type')!r}")
        try:
            man = json.loads(m.body)
            res.ok("манифест — валидный JSON", True, "")
        except json.JSONDecodeError as e:
            man = {}
            res.ok("манифест — валидный JSON", False, str(e))

        res.check("открывается журнал, а не витрина пациента",
                  man.get("start_url"), "/admin")
        res.check("запускается отдельным окном", man.get("display"), "standalone")
        icons = man.get("icons") or []
        res.ok("объявлены оба размера значка",
               {i.get("sizes") for i in icons} == {"192x192", "512x512"},
               f"размеры: {[i.get('sizes') for i in icons]}")

        # ⭐ Самая дорогая ошибка манифеста — АБСОЛЮТНЫЙ адрес. Значок
        # установится молча и будет открывать 127.0.0.1 с телефона, то есть сам
        # телефон: у клиники это выглядит как «программа не работает», а не как
        # «неверная ссылка». Проверяем весь набор адресов разом.
        addrs = ([man.get("start_url", ""), man.get("scope", "")]
                 + [i.get("src", "") for i in icons])
        res.ok("все адреса внутри относительные",
               all(a.startswith("/") for a in addrs), f"адреса: {addrs}")

        for px in (180, 192, 512):
            r = c.get(f"/icon-{px}.png")
            res.ok(f"значок {px} отдаётся PNG-ом",
                   r.status == 200 and r.raw[:8] == b"\x89PNG\r\n\x1a\n",
                   f"код {r.status}, первые байты {r.raw[:8]!r}")
            # ширина лежит в IHDR: 8 байт подписи + 8 байт заголовка чанка
            width = int.from_bytes(r.raw[16:20], "big") if len(r.raw) > 20 else 0
            res.check(f"значок {px} нарисован в свой размер", width, px)
            # ⚠️ Тип цвета из того же IHDR (байт 25): 6 = RGBA. Значку iPhone
            # (180) прозрачность ЗАПРЕЩЕНА — iOS заливает её чёрным, и знак
            # приезжает на домашний экран в чёрной рамке. Видно это только на
            # самом айфоне, поэтому проверяем байтом.
            color_type = r.raw[25] if len(r.raw) > 25 else -1
            if px == 180:
                res.ok("значок iPhone без прозрачности", color_type != 6,
                       "RGBA — на айфоне углы станут чёрными")
            else:
                res.ok(f"значок {px} с прозрачными углами", color_type == 6,
                       f"тип цвета {color_type}, ожидался RGBA")
        res.check("произвольный размер не рисуется",
                  c.get("/icon-9000.png").status, 404)

        page = c.get("/admin").body
        res.ok("журнал подключает манифест", '<link rel="manifest"' in page,
               "нет ссылки на манифест — телефон не узнает про приложение")
        res.ok("журнал объявляет значок для iPhone",
               'rel="apple-touch-icon"' in page, "нет apple-touch-icon")

        # ⚠️ На страницы со своей вёрсткой теги вставляются ПО ЯКОРЮ (charset),
        # а не заполнителем: заполнитель в новом экране забудут. Если якорь
        # однажды перепишут — эта проверка и покажет.
        login = Client(s.url).get("/admin/login").body
        res.ok("экран входа тоже несёт манифест",
               '<link rel="manifest"' in login,
               "с телефона устанавливают как раз с экрана входа")
        res.ok("теги стоят ПОСЛЕ объявления кодировки",
               login.index("charset") < login.index('rel="manifest"'),
               "имя клиники поедет в браузер раньше, чем тот узнает кодировку")

        # цвет и имя принадлежат клинике: смена темы обязана дойти до манифеста
        c.post_json("/api/settings/theme", {"style": "calm", "primary": "#7C3AED",
                                            "custom": ""})
        cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
        addr = cfg.get("address") if isinstance(cfg.get("address"), dict) else {}
        c.post_json("/api/settings/clinic", {"name": "Clinica Redenumită",
                                             "phone": cfg.get("phone", ""),
                                             "address": {"ro": addr.get("ro", ""),
                                                         "ru": addr.get("ru", "")}})
        man2 = json.loads(c.get("/manifest.webmanifest").body)
        res.ok("цвет в манифесте едет за темой клиники",
               man2.get("theme_color") != man.get("theme_color"),
               f"остался {man2.get('theme_color')!r} — цвет зашит, а не взят у темы")
        res.ok("имя клиники в манифесте",
               man2.get("short_name") == "Clinica Redenumită",
               f"short_name: {man2.get('short_name')!r}")


def suite_lan(res: Result) -> None:
    """Доступ с телефона (LAN, слой 2 PWA): секция живёт в dental.env, потому
    что слушающий адрес выбирает лаунчер до старта приложения. В тестах
    DENTART_NO_RESTART=1 — переключение отвечает баннером, а не перезапуском."""
    def tiles(c: Client) -> list:
        # ⛔ Плитки — из данных хаба, не из HTML: хаб рисует React (12.10), и
        # «адреса нет в странице» было бы правдой при любом поведении.
        return [t["href"] for t in json.loads(c.get("/api/settings/hub").body)["data"]["tiles"]]

    with Server() as s0:
        c0 = Client(s0.url).login()
        res.ok("без dental.env плитки НЕТ на хабе",
               "/admin/settings/lan" not in tiles(c0),
               "плитка видна без env-файла (запуск без лаунчера)")
        res.ok("без dental.env страница уводит на хаб",
               c0.get("/admin/settings/lan").status == 303,
               "страница открылась без env-файла")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="dp_lan_"))
    env_path = tmp / "dental.env"
    env_path.write_text("TELEGRAM_TOKEN=\n", encoding="utf-8")
    try:
        with Server(env={"DENTART_ENV_FILE": str(env_path)}) as s:
            anon = Client(s.url)
            r = anon.get("/admin/settings/lan")
            res.ok("без входа секция не отдаётся",
                   r.status == 303 and "/admin/login" in r.location,
                   f"код {r.status}, location {r.location!r}")

            c = Client(s.url).login()
            res.ok("плитка на хабе", "/admin/settings/lan" in tiles(c),
                   "нет плитки при живом env-файле")
            b = c.get("/admin/settings/lan")
            res.ok("страница открывается — узел React",
                   b.status == 200 and 'data-screen="settings_lan"' in b.body,
                   f"код {b.status}")
            d = json.loads(c.get("/api/settings/lan").body)["data"]
            res.ok("по умолчанию доступ выключен", d["enabled"] is False,
                   "состояние не «выключено»")
            # Вторая установка = второй журнал, и оба «работают» (08-13).
            # Предупреждение обязано стоять и в ВЫКЛЮЧЕННОМ состоянии: директор
            # читает страницу до включения, а ставит exe на второй ПК — после.
            res.ok("предупреждение о второй установке видно до включения",
                   "Nu instalați programul" in d["blocks"]["intro"],
                   "экран не отговаривает от второй установки")
            res.ok("иконка нарисована, а не подставлена текстом",
                   all("{_ic(" not in v for v in d["blocks"].values()),
                   "литерал {_ic(…)} уехал на экран — забыт f-префикс")

            r = c.post_json("/api/settings/lan", {"mode": "on"})
            res.check("включение сохраняется", r.msg, "ok_set")
            res.ok("dental.env получил DENTART_LAN=1",
                   "DENTART_LAN=1" in env_path.read_text(encoding="utf-8"),
                   "флага нет в файле — лаунчер не узнает о включении")
            res.ok("экран показывает активный режим",
                   json.loads(c.get("/api/settings/lan").body)["data"]["enabled"] is True,
                   "после включения состояние не «включено»")

            r = c.post_json("/api/settings/lan", {"mode": "off"})
            res.check("выключение сохраняется", r.msg, "ok_set")
            res.ok("флаг в файле погашен",
                   "DENTART_LAN=1" not in env_path.read_text(encoding="utf-8"),
                   "выключение не дошло до dental.env")
            res.ok("комментарии клиники в env-файле уцелели",
                   "TELEGRAM_TOKEN=" in env_path.read_text(encoding="utf-8"),
                   "переключение затёрло соседние ключи")

            # --- Telegram заморожен (08-08): интерфейс бота видит только
            # клиника с УЖЕ настроенным токеном (grandfather) ---
            res.check("без токена секции «Sincronizări» нет", _sync(c.get("/admin").body), [])
            res.ok("без токена нет плитки Telegram на хабе",
                   "/admin/settings/telegram" not in tiles(c),
                   "плитка бота предлагается клинике без токена")

        # UNREADABLE-флаг = токен был (переезд ПК): раздел обязан ВЕРНУТЬСЯ,
        # иначе клинике после переезда некуда ввести токен заново
        with Server(env={"DENTART_ENV_FILE": str(env_path),
                         "DENTART_TOKEN_UNREADABLE": "1"}) as s2:
            c2 = Client(s2.url).login()
            res.check("настроенный бот остаётся в меню (grandfather)",
                      _sync(c2.get("/admin").body), ["tg", "qr"])
    finally:
        _rmtree_settled(tmp)


def suite_pure(res: Result) -> None:
    """Чистая логика расписания — без сервера и без базы."""
    code = r"""
import json, os, pathlib, sys
sys.path.insert(0, r"%s")
from datetime import datetime, timedelta, date
from app import engine as eng
from app import paths
# ⚠️ статус бота ищется в sys.modules по имени пакета. Когда имя считалось от
# __package__ текущего файла, переезд файла в подпапку тихо ломал показ:
# адаптер работает, а интерфейс рисует его выключенным. Подкладываем модуль
# под НАСТОЯЩИМ именем и проверяем, что его находят из core.
import types
# настоящий адаптер — ради текстов визитки (_meta_texts); импортируем ДО
# подделки, дальше имя в sys.modules перекрывает фейк
from app import telegram as _tg_real
_fake = types.ModuleType("app.telegram")
_fake.STATUS = {"running": True, "username": "bot_de_test", "error": ""}
_fake.meta_pings = 0
def _ping():
    _fake.meta_pings = _fake.meta_pings + 1
_fake.refresh_meta = _ping
sys.modules["app.telegram"] = _fake
from app.core.layout import _tg_state, tg_refresh_meta, tg_status
tg_refresh_meta()   # обязан дозвониться до модуля под НАСТОЯЩИМ именем
_meta = _tg_real._meta_texts()          # фикстура без contacts
eng.CONFIG["contacts"] = {"ro": "str. Test 1 / tel"}
_meta_c = _tg_real._meta_texts()        # и с contacts-строкой
# фолбэк обновлятора: чистые разборщики веб-ответов GitHub. Сеть в этих
# проверках не участвует — кормим текстами, снятыми с настоящих ответов.
from app import update as upd
ATOM = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><link rel="alternate" href="https://github.com/o/r/releases/tag/v1.9.1"/></entry>
 <entry><link rel="alternate" href="https://github.com/o/r/releases/tag/v1.13.5"/></entry>
 <entry><link rel="alternate" href="https://github.com/o/r/releases/tag/v1.13.0"/></entry>
</feed>'''
now = datetime.now(eng.TZ)
out = {
 "atom_tags":      upd._tags_from_atom(ATOM),
 "atom_best":      max(upd._tags_from_atom(ATOM), key=upd._ver, default=""),
 "latest_tag":     upd._tag_from_latest_url(
                       "https://github.com/o/r/releases/tag/v1.13.5"),
 "latest_encoded": upd._tag_from_latest_url(
                       "https://github.com/o/r/releases/tag/v1.13.5%%2Brc?x=1"),
 "latest_none":    upd._tag_from_latest_url("https://github.com/o/r/releases"),
 # BitLocker: тона по кодам Shell COM (сверены с живой машиной 08-06)
 "bl_ok":     __import__("app.core.bitlocker", fromlist=["x"]).describe(1, "C:")[0],
 "bl_trap":   __import__("app.core.bitlocker", fromlist=["x"]).describe(8, "C:")[0],
 "bl_plain":  __import__("app.core.bitlocker", fromlist=["x"]).describe(2, "C:")[0],
 "bl_none":   __import__("app.core.bitlocker", fromlist=["x"]).describe(None)[0],
 "bl_c_in":   "C:" in __import__("app.core.bitlocker", fromlist=["x"]).describe(8, "C:")[1],
 "tg_user":        tg_status().get("username"),
 "tg_running":     tg_status().get("running"),
 "tg_state_tuple": list(_tg_state()),
 "meta_pinged":    _fake.meta_pings,
 "meta_short_ro":  _meta["ro"]["short"],
 "meta_desc_head": _meta["ro"]["desc"].startswith("Programări online — Clinica Test."),
 "meta_hint_ro":   "orele de lucru" in _meta["ro"]["desc"],
 "meta_hint_ru":   "часы работы" in _meta["ru"]["desc"],
 "meta_contacts":  "str. Test 1 / tel" in _meta_c["ro"]["desc"],
 "meta_lens_ok":   all(len(t["desc"]) <= 512 and len(t["short"]) <= 120
                       for m in (_meta, _meta_c) for t in m.values()),
 "res_clinic":     paths.resource("clinic.json").exists(),
 "res_clinic_new": paths.resource("clinic_new.json").exists(),
 "res_static":     paths.resource("static").is_dir(),
 "res_index":      paths.resource("static", "index.html").exists(),
 # ⛔ runtime_dir() удалён: место записи больше не считается от того, где
 # лежит программа. Обе новые функции читают ОКРУЖЕНИЕ, поэтому и проверяем
 # их окружением — в этом подпроцессе ни одна из переменных не задана.
 "db_dir_unset":   paths.db_dir() is None,
 "data_root_unset": paths.data_root() is None,
 "db_dir_from_url": (os.environ.update(
                        {"DATABASE_URL": "sqlite:///C:/x/data/dental.db"})
                     or str(paths.db_dir()).replace("\\", "/")),
 "root_needs_abs": (os.environ.update({"DENTART_DATA_DIR": "relativ"})
                    or paths.data_root() is None),
 "root_from_env":  (os.environ.update({"DENTART_DATA_DIR": r"C:\x"})
                    or str(paths.data_root()).replace("\\", "/")),
 "past_hour":      eng.is_past(now - timedelta(hours=1)),
 "future_hour":    eng.is_past(now + timedelta(hours=1)),
 "past_day":       eng.is_past_day(now.date() - timedelta(days=1)),
 "today_not_past": eng.is_past_day(now.date()),
 "dur_default":    eng.svc_duration("consult"),
 "dur_long":       eng.svc_duration("long"),
 "dur_unknown":    eng.svc_duration("nope"),
 "fits_noon":      eng.fits_clinic(now.replace(hour=12, minute=0), 60),
 # часы приёма врача — ОДИН ответ на обе дневные страницы (канва и таблица)
 "doc_hours":      sorted(eng.doctor_hours("d2", now.date() + timedelta(days=1))),
 "doc_hours_off":  sorted(eng.doctor_hours("d1", now.date() + timedelta(days=1))),
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
    # фолбэк обновлятора: то, что программа поймёт из веба при выеденном API
    res.check("атом-фид разобран на теги", v["atom_tags"],
              ["v1.9.1", "v1.13.5", "v1.13.0"])
    res.check("лучший тег — по версии, а не по порядку в фиде",
              v["atom_best"], "v1.13.5")
    res.check("тег из редиректа /releases/latest", v["latest_tag"], "v1.13.5")
    res.check("процентная кодировка тега снимается", v["latest_encoded"], "v1.13.5+rc")
    res.check("без релизов редирект не выдумывает тег", v["latest_none"], "")
    # BitLocker: код 8 («зашифрован, защита выключена») — ТРЕВОГА, не норма
    res.check("BitLocker включён — ок", v["bl_ok"], "ok")
    res.check("ловушка новых ПК (код 8) — тревога", v["bl_trap"], "alarm")
    res.check("незашифрованный диск — предупреждение", v["bl_plain"], "warn")
    res.check("не смогли проверить — честное unknown, не паника",
              v["bl_none"], "unknown")
    res.check("в тексте назван сам диск", v["bl_c_in"], True)
    # статус бота: ищется по имени пакета, а не по расположению файла
    res.check("статус бота виден из core", v["tg_user"], "bot_de_test")
    res.check("бот показан работающим", v["tg_running"], True)
    res.check("короткий статус для сайдбара", v["tg_state_tuple"],
              [True, "bot_de_test"])
    # визитка бота: описание в профиле Telegram собирается из конфига клиники
    # и живёт у Telegram — единственный текст, видимый при ВЫКЛЮЧЕННОЙ программе
    res.check("пинок визитки доходит до адаптера", v["meta_pinged"], 1)
    res.check("short-описание: имя клиники и телефон", v["meta_short_ro"],
              "Programări online — Clinica Test · ☎️ +373 60 000 000")
    res.check("описание начинается с имени клиники", v["meta_desc_head"], True)
    res.check("описание объясняет молчание (RO)", v["meta_hint_ro"], True)
    res.check("описание объясняет молчание (RU)", v["meta_hint_ru"], True)
    res.check("contacts-строка попадает в описание", v["meta_contacts"], True)
    res.check("лимиты Bot API соблюдены", v["meta_lens_ok"], True)
    # якоря путей: то, из-за чего собранный exe не стартовал бы после переезда
    res.check("демо-профиль клиники находится", v["res_clinic"], True)
    res.check("пустой профиль клиники находится", v["res_clinic_new"], True)
    res.check("папка static находится", v["res_static"], True)
    res.check("страница пациента находится", v["res_index"], True)
    # ⛔ runtime_dir() удалён — писать «рядом с программой» больше нельзя.
    res.check("без DATABASE_URL каталога базы нет", v["db_dir_unset"], True)
    res.check("без DENTART_DATA_DIR папки клиники нет", v["data_root_unset"], True)
    res.check("каталог базы считается от DATABASE_URL",
              v["db_dir_from_url"], "C:/x/data")
    # ⚠️ относительный путь отвергается: у ярлыка и у службы разный cwd
    res.check("относительный DENTART_DATA_DIR отвергнут", v["root_needs_abs"], True)
    res.check("папка клиники берётся из DENTART_DATA_DIR",
              v["root_from_env"], "C:/x")
    res.check("прошедший час — в прошлом", v["past_hour"], True)
    res.check("будущий час — не в прошлом", v["future_hour"], False)
    res.check("вчерашний день закрыт", v["past_day"], True)
    res.check("сегодня НЕ закрытый день", v["today_not_past"], False)
    res.check("длительность по умолчанию", v["dur_default"], 60)
    res.check("длительность из конфига", v["dur_long"], 120)
    res.check("неизвестная услуга — дефолт", v["dur_unknown"], 60)
    res.check("полдень в графике", v["fits_noon"], True)
    # ⛔ Формула «когда врач принимает» обязана быть ОДНА: пока её копия жила в
    # канве, а таблица «Programări» не спрашивала её вовсе, страницы разошлись —
    # там штриховка, тут «+» про одного и того же врача в один и тот же час.
    res.check("часы приёма врача = окно клиники", v["doc_hours"], list(range(7, 21)))
    res.check("выключенный врач не принимает вовсе", v["doc_hours_off"], [])
    res.check("услугу без активных врачей выполнять некому",
              v["orphan_docs"], [])
    res.check("консультацию выполняют все активные", v["consult_docs"], 3)


def _fixture():
    from harness import FIXTURES
    return FIXTURES / "clinic_test.json"


def suite_bot_ui(res: Result) -> None:
    """Telegram заморожен (08-08): панель и статистика клиники БЕЗ бота молчат
    о нём; grandfather-клиника (токен настроен) видит всё как раньше.
    Вторая ветка поднимается с DENTART_TOKEN_UNREADABLE=1 — это честный флаг
    dpapi «токен есть, но нечитаем»: tg_configured() истинен, а живой бот
    не нужен."""
    with Server() as s:  # токена нет — так выглядит новая клиника
        c = Client(s.url).login()

        # ⛔ Заморозка прячет ЭКРАНЫ, но тексты про бота протекали мимо неё:
        # 08-10 Олег увидел в карточке врача «Activ — botul și formularele îl
        # propun» у клиники, у которой бота нет и не будет. Нашлось ещё шесть
        # таких же — в баннере сохранения настроек, в подсказке про перерыв, в
        # предупреждениях об услугах без врача. Каждое поодиночке мелочь, все
        # вместе — программа рассказывает про функцию, которой у клиники нет.
        # ⚠️ Проверка обходит СТРАНИЦЫ, а не исходники: строки собираются в
        # f-строках из кусков, и поиск по коду их не ловит.
        # ⚠️ 08-13 Олег увидел «Telegram» в фильтре каналов списка пациентов:
        # страница построена ПОЗЖЕ заморозки, а слова «Telegram» в этом списке
        # не было — три дырки (фильтр, строка «Canal Telegram» в Stare sistem,
        # абзац токена в FAQ) прожили незамеченными. Слово и обе страницы
        # теперь в обходе.
        # ⚠️ Экраны React (все разделы с 13.10) несут текст в ответах /api/*,
        # а не в странице: обход страницы у них видит пустую оболочку, и сторож
        # молча становился пустым — поэтому в обходе их ответы. Журнал — в
        # первую очередь: панель, день, неделя и кресло.
        bot_pid = new_patient(c, "Fara Bot", "069000777")
        add_appt(c, _d(1), "10:00", "Fara Bot", "069000777")
        leaks = []
        for path in ("/admin", "/admin/all",
                     "/api/schedule/live?screen=panel", f"/api/schedule/live?date={_d(1)}",
                     f"/api/schedule/day?date={_d(1)}", f"/api/schedule/week?date={_d(1)}",
                     "/api/chair?doctor=d2",
                     "/api/patients", "/api/patients/summary", f"/api/patients/{bot_pid}",
                     f"/api/patients/{bot_pid}/peek",
                     "/api/settings/hub", "/api/settings/clinic",
                     "/api/settings/hours", "/api/settings/services",
                     "/api/settings/system", "/api/settings/faq", "/api/stats",
                     "/api/doctors", "/api/doctors/d2"):
            body = c.get(path).body
            for word in ("botul", "botului", "prin bot", "🤖", "Telegram"):
                if word in body:
                    leaks.append(f"{path}: {word}")
        res.ok("клинике без бота о боте не рассказывают", not leaks,
               f"утечки заморозки: {leaks}")
        res.check("«Sursă» в «Lista zilei» у клиники без бота не показывается",
                  day_model(c, _d(1))["source_col"], False)
        # экран статистики — React: его текст сервера едет в /api/stats
        stats = c.get("/api/stats").body
        res.ok("статистика без доли бота",
               "prin bot" not in stats and "Prin bot" not in stats
               and "Remindere" not in stats, "бот в разборе статистики")
        res.ok("нет «botul a adus»", "botul a adus" not in stats,
               "оценка вклада бота без бота")

        # самозапись через веб — тот же канал, что бот: заморожена вместе с ним
        res.check("лендинг самозаписи закрыт", c.get("/").status, 404)
        res.check("веб-чат закрыт",
                  c.post_json("/chat", {"session_id": "x", "message": "/start"}).status,
                  404)
        res.check("выставочный экран закрыт", c.get("/demo").status, 404)
        # ⚠️ соседи по корню обязаны выжить: на /health держится single-instance
        # guard лаунчера, на /static — всё оформление журнала
        res.check("/health не пострадал", c.get("/health").status, 200)
        res.check("оформление отдаётся",
                  c.get("/static/css/panel.css").status, 200)
        res.check("значок отдаётся", c.get("/favicon.ico").status, 200)

    # grandfather: у клиники токен настроен — интерфейс бота виден.
    # (Плитка «Prin bot», блок «Programări noi din bot» и колокольчик жили
    # только на старой панели и ушли с ней 13.10; React их не рисовал.)
    with Server(env={"DENTART_TOKEN_UNREADABLE": "1"}) as s:
        c = Client(s.url).login()
        res.check("grandfather: Sincronizări в меню", _sync(c.get("/admin").body), ["tg", "qr"])
        res.check("grandfather: «Sursă» в «Lista zilei» показывается",
                  day_model(c)["source_col"], True)
        kp = {x["key"]: x for x in
              json.loads(c.get("/api/stats").body)["data"]["board"]["kpis"]}
        res.ok("grandfather: доля бота в статистике",
               "prin bot" in kp["programari"]["sub"], "статистика урезана у grandfather")
        res.ok("grandfather: строка канала Telegram в Stare sistem",
               bool(json.loads(c.get("/api/settings/system").body)["data"]["telegram"]),
               "строка канала пропала у клиники с ботом")
        res.ok("grandfather: FAQ говорит про токен при переезде",
               any("tokenul botului Telegram" in it["answer"] for it in
                   json.loads(c.get("/api/settings/faq").body)["data"]["items"]),
               "клиника с ботом потеряет токен при переезде и не узнает об этом")
        # ⭐ Опция канала в фильтре — по ДАННЫМ, не по токену: grandfather БЕЗ
        # tg-пациентов её тоже не видит (канарейка-демо — ровно этот случай;
        # фильтр по пустому множеству продавал бы замороженный канал на демо).
        # Обратная сторона — в test_bot: у клиники с bot-пациентом опция есть.
        channels = [x["id"] for x in
                    json.loads(c.get("/api/patients/summary").body)["data"]["channels"]]
        res.ok("grandfather без tg-пациентов: фильтр каналов без Telegram",
               channels and "tg" not in channels, f"опция Telegram при нуле tg-пациентов: {channels}")
        res.check("grandfather: лендинг самозаписи открыт", c.get("/").status, 200)
        res.check("grandfather: веб-чат отвечает",
                  c.post_json("/chat", {"session_id": "g", "message": "/start"}).status,
                  200)


def suite_live_stable(res: Result) -> None:
    """Контракт живого канала: состояние ДЕТЕРМИНИРОВАНО при неизменных данных.

    ⭐ Это второе свойство протокола, и до 18.09 его не проверял никто.
    Отпечаток, посчитанный от отправленного (`test_schedule_api.
    suite_live_envelope`), держится сам собой. А вот что ДВА запроса подряд
    дадут одно и то же состояние, не следует ни из чего: достаточно одной
    серверной строки с минутами, случайного id или неустойчивого порядка, и
    отпечаток становится другим каждые 12 секунд. Панель перерисовывается на
    каждый опрос — мигание, от которого ушли 08-20 по жалобе пилота, — и
    увидеть это можно, только простояв на странице полминуты. Ни один набор
    столько не стоит.

    ⚠️ Проверяются ЖИВЫЕ данные, а не пустой день: в дне есть пациент в
    приёмной (`waiting_at`), запись «сейчас» и прошедшая. Минуты ожидания
    обязан считать браузер по отметке времени — если их однажды напечатает
    сервер, отпечаток поедет ровно у той клиники, где кто-то ждёт.
    (До 13.10 то же требовалось от тела четырёх старых живых страниц; живой
    у журнала теперь один канал — панели.)
    """
    with Server() as s:
        c = Client(s.url).login()
        day = clinic_today().isoformat()
        for hh, nm, ph in (("10:00", "Live Stabil", "069700700"),
                           ("11:00", "Live Asteapta", "069700701"),
                           ("12:00", "Live Ghost", "069700702")):
            add_appt(c, day, hh, nm, ph)
        # ⛔ НИЧЬЯ в сортировке дня: две строки с ОДНИМ `starts_at` и ОДНИМ
        # именем врача. Она достижима не «как угодно», а ровно в одном месте, и
        # это стоило проверки опытом: уникальный индекс слота ЧАСТИЧНЫЙ —
        # `uq_doctor_slot ON (doctor, starts_at) WHERE status IN (активные)`.
        # Поэтому две АКТИВНЫЕ записи на минуту не лягут (и заметка тоже: она
        # идёт через ту же проверку и отвечает «bad» — проверено 19.09), а две
        # ЗАКОНЧЕННЫЕ — лягут. У клиники это будни: приём завершили, слот
        # переиспользовали, в дне два `finalizat` на один час.
        # Дальше ничья тянется вниз: `canvas.clusters` и `canvas.blocks`
        # сортируют УСТОЙЧИВО, а сортировка кластера отделяет живых от
        # законченных — между двумя законченными она не различает ничего, и
        # порядок остаётся тот, что пришёл из базы. Он решает `col`/`of`, то
        # есть геометрию. Без тай-брейка по `a.id` два опроса при неизменном дне
        # дали бы разное состояние. Правило держит `test_structure` («выборка
        # дня упорядочена полностью»), здесь — сама ситуация.
        import sqlite3 as _sq
        ids = {nm: appt_id(c, day, nm) for nm in ("Live Stabil", "Live Asteapta", "Live Ghost")}
        for who in ("Live Stabil", "Live Ghost"):
            c.post_json(f"/api/schedule/appointments/{ids[who]}/status", {"to": "done"})
        con = _sq.connect(s.dir / "dental.db")
        con.execute("UPDATE appointments SET starts_at ="
                    " (SELECT starts_at FROM appointments WHERE id = ?)"
                    " WHERE id = ?", (ids["Live Stabil"], ids["Live Ghost"]))
        con.commit()
        con.close()
        # пациент В ПРИЁМНОЙ: именно у него минуты ожидания и мог бы поехать
        # отпечаток, если бы их печатал сервер
        c.post_json(f"/api/schedule/appointments/{ids['Live Asteapta']}/status",
                    {"to": "waiting"})
        live = panel_live(c, day)
        tie = [b for col in live["canvas"]["columns"] for b in col["blocks"]
               if b["id"] in (ids["Live Stabil"], ids["Live Ghost"])]
        res.ok("ничья в сортировке в фикстуре ЕСТЬ: две строки на одну минуту "
               "у одного врача, и обе на канве",
               len(tie) == 2 and tie[0]["min"] == tie[1]["min"],
               "ничьи нет — набор проверял бы детерминизм мимо неё")

        url = f"/api/schedule/live?screen=panel&date={day}"
        a, b = c.get(url), c.get(url)
        if a.body != b.body:
            # ⚠️ Могли пересечь границу часа между запросами: подсветка
            # текущего часа дискретна и меняться ВПРАВЕ раз в час. Второй
            # шанс отличает редкий переход от настоящего недетерминизма.
            b, a = c.get(url), c.get(url)
        res.ok("два запроса подряд дают одно состояние",
               a.body == b.body,
               "состояние меняется само по себе — перерисовка пойдёт на КАЖДЫЙ "
               "опрос и мигание вернётся; ищите в нём время, минуты, случайный "
               "id или неустойчивый порядок")
        res.ok("и один отпечаток", a.header("X-DP-Hash") == b.header("X-DP-Hash"),
               f"{a.header('X-DP-Hash')} против {b.header('X-DP-Hash')}")

        # Данные изменились — отпечаток ОБЯЗАН стать другим, иначе живой журнал
        # молчит о новой записи, и это вторая половина того же контракта.
        before = c.get(url).header("X-DP-Hash")
        add_appt(c, day, "15:30", "Live Nou", "069700703")
        after = c.get(url).header("X-DP-Hash")
        res.ok("новая запись меняет отпечаток", before != after,
               "отпечаток не заметил новую запись — опрос вернёт 204, и стойка "
               "не увидит бронь из бота, пока не обновит страницу руками")

        # Минуты ожидания считает БРАУЗЕР по отметке времени: сервер кладёт
        # только `wait_since`. Иначе состояние менялось бы каждую минуту у любой
        # клиники, где кто-то сидит в приёмной.
        wait = next((x for x in panel_live(c, day)["agenda"]["items"]
                     if x["name"] == "Live Asteapta"), {})
        res.ok("пациент в приёмной в повестке есть (иначе проверка ниже пуста)",
               wait.get("status") == "waiting", f"строка: {wait}")
        res.ok("минуты ожидания — отметкой для браузера, а не текстом сервера",
               isinstance(wait.get("wait_since"), int)
               and not any(isinstance(v, str) and re.search(r"\d+\s*min", v)
                           for v in wait.values()),
               "сервер печатает минуты сам — отпечаток поедет там, где ждут")


# --- C24: неделя. Пин ПОВЕДЕНИЯ, а не разметки -----------------------------
# ⚠️ До 18.09 неделя была покрыта двумя вещами: «отвечает 200» и участием в
# живом протоколе. Всё, ради чего экран существует — какие дни показаны,
# сколько записей, что написано в чипе, — не проверялось ни одним символом.
# С 13.10 старой страницы нет, и пин читает то, что получает экран:
# `GET /api/schedule/week`.

def _week(c: Client, day: str = "") -> dict:
    return json.loads(c.get("/api/schedule/week" + (f"?date={day}" if day else "")).body)["data"]


def _close_weekend(c: Client) -> bool:
    """Закрыть субботу и воскресенье — тем же телом, что шлёт экран часов.

    ⚠️ Закрывать ПОСЛЕ сева: на нерабочий день запись не создаётся (окно
    записи проверяет часы клиники), и это само по себе поведение — см.
    проверку «на закрытый день записать нельзя». Поэтому суббота сначала
    рабочая, запись в неё кладётся, и лишь затем день закрывается — ровно
    так, как бывает у клиники, поменявшей график.
    """
    hours = {"mon": [7, 21], "tue": [7, 21], "wed": [7, 21], "thu": [7, 21],
             "fri": [7, 21], "sat": None, "sun": None}
    return c.post_json("/api/settings/hours", {"hours": hours}).status == 200


def suite_week(res: Result) -> None:
    """Неделя: диапазон, колонки, счётчики, чипы, цвета, соседние недели."""
    with Server() as s:
        c = Client(s.url).login()
        # понедельник ближайшей ПОЛНОЙ будущей недели: прошлое не трогаем,
        # чтобы «сегодня» не путалось с наполнением
        monday = clinic_today() + timedelta(days=7 - clinic_today().weekday())
        d = lambda i: (monday + timedelta(days=i)).isoformat()  # noqa: E731

        # «сегодня» — ровно одна колонка, и спрашивается это ДО того, как набор
        # закроет выходные.
        # ⚠️ Порядок здесь несущий, а не косметический. Закрытый день без
        # записей из недели исчезает вовсе, поэтому после `_close_weekend`
        # субботний прогон не находил бы «сегодня» нигде — проверка краснела
        # каждые выходные на ровном месте (поймано 19.09). Ослабить её до
        # «в выходной ноль» нельзя: тогда два дня в неделю она зеленела бы над
        # начисто сломанной подсветкой — та же полярность, что у списков-
        # исключений в CLAUDE.md. Поэтому не ожидание подгоняется под день, а
        # вопрос задаётся там, где ответ один в любой день недели.
        res.check("на текущей неделе подсвечен ровно один день",
                  sum(1 for x in _week(c)["days"] if x["today"]), 1)

        # суббота пока рабочая — кладём в неё запись, она переживёт закрытие дня
        sat = add_appt(c, d(5), "11:00", "Vasile Lupu", "069800802")
        res.ok("на рабочую субботу запись создаётся", sat.msg == "ok",
               f"код {sat.msg} — дальше проверять нечего")
        res.ok("выходные закрыты через настройки часов", _close_weekend(c),
               "часы не сохранились")

        w = _week(c, d(2))
        res.check("пять рабочих дней плюс суббота с записью",
                  [x["date"] for x in w["days"]], [d(i) for i in range(6)])
        res.check("пустой рабочий день — без чипов (экран скажет «— liber —»)",
                  next(x["items"] for x in w["days"] if x["date"] == d(0)), [])
        res.ok("воскресенье без записей скрыто",
               d(6) not in [x["date"] for x in w["days"]],
               "пустой выходной обязан исчезнуть из недели")
        bad = add_appt(c, d(6), "11:00", "Nu Merge", "069800809")
        res.check("на закрытый день записать нельзя — «вне рабочих часов»",
                  bad.msg, "outside")

        # среда: две записи и заметка стойки
        add_appt(c, d(2), "09:00", "Ion Popa", "069800800")
        add_appt(c, d(2), "10:30", "Maria Rusu", "069800801", service="pain")
        c.post_json("/api/schedule/notes", {"date": d(2), "time": "12:00", "doctor": "d2",
                                           "text": "Livrare materiale"})
        w = _week(c, d(2))
        res.check("состав колонок не поехал от новых записей",
                  [x["date"] for x in w["days"]], [d(i) for i in range(6)])
        res.ok("подпись дня — своя у каждой колонки, не по индексу",
               len({x["label"] for x in w["days"]}) == 6,
               f"подписи повторяются: {[x['label'] for x in w['days']]}")
        wed = next(x for x in w["days"] if x["date"] == d(2))
        res.check("счётчик дня считает записи и НЕ считает заметку",
                  wed["count"], 2)
        res.check("итог недели — сумма записей без заметок", w["total"], 3)
        res.check("в среду три чипа: две записи и заметка",
                  [x["kind"] for x in wed["items"]], ["appt", "appt", "note"])
        res.check("чип записи несёт час, имя и услугу",
                  [(x["time"], x["name"], x["service"]) for x in wed["items"]
                   if x["kind"] == "appt"][0], ("09:00", "Ion Popa", "Consultație"))
        res.check("чип заметки — без имени пациента, своим видом",
                  [x for x in wed["items"] if x["kind"] == "note"],
                  [{"kind": "note", "time": "12:00", "text_cut": "Livrare materiale"}])
        # цвет — токеном темы, а не хексом: клиника выбирает свой цвет
        bgs = [x["bg"] for x in wed["items"] if x["kind"] == "appt"]
        res.ok("фон чипа — переменная темы, а не зашитый цвет",
               bgs and all(b.startswith("var(--") for b in bgs),
               f"в стиле чипа хекс: {bgs}")

        # неявка: помечена полем, а не разметкой
        aid = appt_id(c, d(2), "Ion Popa")
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "noshow"})
        wed = next(x for x in _week(c, d(2))["days"] if x["date"] == d(2))
        res.check("неявка помечена", [x.get("noshow") for x in wed["items"]
                                      if x["kind"] == "appt"], [True, False])

        # отменённая запись исчезает целиком. ⚠️ Из «неявки» прямо в «отмену»
        # ребра нет (17.10: переход только по матрице кнопок) — как и на
        # экране: сперва «Redeschide», потом «Anulează»
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "confirmed"})
        c.post_json(f"/api/schedule/appointments/{aid}/status", {"to": "cancelled"})
        wed = next(x for x in _week(c, d(2))["days"] if x["date"] == d(2))
        res.check("отменённая запись ушла из недели и из счётчика",
                  (len(wed["items"]), wed["count"]), (2, 1))

        # соседние недели: ровно ±7 дней от понедельника
        res.check("соседние недели — ±7 дней от понедельника, день открытия — эхом",
                  (w["prev"], w["next"], w["day"]),
                  ((monday - timedelta(days=7)).isoformat(),
                   (monday + timedelta(days=7)).isoformat(), d(2)))
        res.check("диапазон — понедельник–воскресенье", w["span"],
                  f"{monday.strftime('%d.%m')} – "
                  f"{(monday + timedelta(days=6)).strftime('%d.%m.%Y')}")
        res.check("на будущей неделе не подсвечен никто",
                  sum(1 for x in w["days"] if x["today"]), 0)

        # любая дата недели даёт ТУ ЖЕ неделю: она ключуется понедельником
        res.check("любой день недели открывает одну и ту же неделю",
                  [x["date"] for x in _week(c, d(4))["days"]],
                  [x["date"] for x in w["days"]])
        res.check("кривая дата не роняет экран — открывает текущую неделю",
                  c.get("/api/schedule/week?date=2026-13-99").status, 200)
