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

from harness import (BOT, PIN, PYTHON, Client, Result, Server, _rmtree_settled, clinic_today,
                     new_patient, pid_by_phone)


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
        c.post("/admin/add", adate=_d(1), atime="10:00", adoctor="d2",
               aservice="consult", aname="Pagina Test", aphone="022321321",
               back="/admin/all")

        pages = {
            "/admin": "Clinica Test",
            f"/admin/all?date={_d(1)}": "Pagina Test",
            "/admin/week": "",
            # статистика и врачи — React (12.10): данные приходят из /api/*,
            # их содержимое стерегут test_stats_api и test_doctors
            "/admin/stats": "",
            "/admin/settings": "Clinica Test",
            "/admin/medici": "",
            # список пациентов — React (13.10), выдачу стережёт test_patients_api
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

        # Модалка слота выбирает и ПОЛЧАСА (08-13, Олег): клик по ячейке —
        # час, но запись бывает на 10:30, и раньше её давала только нижняя
        # форма. Обе дневные страницы несут переключатель и его механику.
        for path in ("/admin", f"/admin/all?date={_d(1)}"):
            body = c.get(path).body
            res.ok(f"модалка {path} умеет полчаса",
                   'id="hp_30"' in body and "pickHalf" in body,
                   "в модалке слота нет выбора :30 — только нижняя форма")
        # сервер принимает получасовой старт из модалки тем же маршрутом
        res.check("запись на 10:30 из модалки принимается",
                  c.post("/admin/add", adate=_d(1), atime="10:30", adoctor="d3",
                         aservice="consult", aname="Jumatate Test",
                         aphone="022321322", back="/admin/all").msg, "ok")

        # ⭐ Подсветка «сейчас» в сетке дня (08-09) — это ЛОГИКА, а не
        # оформление: строка текущего часа отмечается классом на сервере.
        # Отметка на ЧУЖОМ дне была бы прямой ложью — регистратура читает её
        # как «мы вот здесь», — и заметить такое на глаз почти нельзя:
        # завтрашний день выглядит правдоподобно с подсветкой любого часа.
        # ⚠️ Ожидание выводится ИЗ САМОЙ страницы, а не из «должен быть один»:
        # клиника фикстуры работает 7–21, и жёсткая единица делала бы прогон
        # красным по ночам. Сильная половина проверки — про чужой день — от
        # времени суток не зависит и держится всегда.
        now_h = datetime.now(ZoneInfo("Europe/Chisinau")).hour
        today = c.get("/admin/all")
        other = c.get(f"/admin/all?date={_d(1)}")
        shown = [int(h) for h in re.findall(r"class='hour[^']*'>(\d\d):00", today.body)]
        res.check("текущий час отмечен тогда и только тогда, когда он в сетке",
                  today.body.count("class='hour now'"), 1 if now_h in shown else 0)
        res.ok("на другом дне подсветки «сейчас» нет",
               "class='hour now'" not in other.body,
               "завтрашний день отмечен текущим часом — это враньё")
        res.ok("сетка дня лежит в прокручиваемой обёртке",
               "class='gridwrap'" in today.body,
               "без обёртки широкая сетка распирает страницу на телефоне")
        res.ok("статус в списке дня — отдельная плашка",
               "class='stat s-" in other.body, "нет класса статуса")

        # автоперезагрузка — ТОЛЬКО у живого расписания (data-reload на body):
        # остальным она не даёт ничего и отнимает раскрытые <details> и
        # позицию прокрутки — «вкладка FAQ закрывается сама» (Олег, 08-07)
        for path in ("/admin", f"/admin/all?date={_d(1)}", "/admin/week",
                     "/admin/doctor/d2"):
            res.ok(f"{path} перезагружает себя",
                   'data-reload="12"' in c.get(path).body,
                   "живая страница расписания без метки автообновления")

        # Ширина (08-16, просьба Олега «справа много места»): окно отдаётся
        # ВСЕМ разделам, а не двум дневным видам. Раньше здесь стоял обратный
        # набор — `content wide` у расписания и голый `content` у остальных;
        # тот второй список и был жалобой: на 27" он оставлял 844px пустоты
        # справа. ⚠️ Сторожим ОБА конца: что широкую разметку получают все
        # разделы И что двухуровневого деления больше нет — вернувшийся
        # модификатор снова сделал бы часть страниц узкими молча (увидел бы это
        # только клиент с большим монитором, на 1366 потолок не срабатывает).
        # Потолок самой СТРОКИ живёт в panel.css и проверяется там же
        # (test_review3.suite_width) — разметка о нём ничего не знает.
        # ⚠️ Настроек, статистики, врачей и пациентов в списке нет: их экраны
        # рисует React (12–13.10), и ширину раскладки ведёт клиент, серверного
        # `content` у оболочки нет.
        shells = {}
        for path in ("/admin", f"/admin/all?date={_d(1)}", "/admin/week",
                     "/admin/doctor/d2"):
            body = c.get(path).body
            m = re.search(r'<div class="(content[^"]*)"', body)
            shells[path] = m.group(1) if m else "—"
            res.ok(f"{path} занимает всю ширину окна",
                   'class="content"' in body,
                   "раздел не получил широкий контент — справа останется "
                   "пустое поле")
        res.ok("у разделов ОДИН каркас ширины, а не два сорта страниц",
               len(set(shells.values())) == 1,
               f"каркасы разошлись — часть разделов снова у́же остальных, и "
               f"новая страница молча родится узкой: {shells}")
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
        for path in ("/admin/settings", "/admin/settings/faq", "/admin/stats",
                     "/admin/medici", "/admin/search"):
            res.ok(f"{path} НЕ перезагружает себя",
                   "data-reload" not in c.get(path).body,
                   "неживой странице выдана автоперезагрузка — она снова "
                   "будет терять раскрытые details")

        csv = c.get(f"/admin/export?from={_d(1)}&to={_d(1)}")
        res.ok("экспорт CSV отдаётся", csv.status == 200 and "Pagina Test" in csv.body,
               f"код {csv.status}")

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

        # Ответ на действие — ПЛАВАЮЩЕЙ плашкой (08-14, фидбек клиники): форма
        # записи стоит внизу, 303 открывает страницу с нулевой прокруткой, и
        # баннер в потоке оставался за кадром — «сказали ок, а что случилось —
        # не поняли». Помощник один (layout.msg_banner, держит test_structure),
        # но канал проверяется на страницах ТРЁХ модулей: каждый маршрут зовёт
        # его сам, и забытый вызов уронил бы сообщение вовсе.
        # Настройки рисует React (12.10): та же плашка едет строкой сервера в
        # модели оболочки (`frame.msg`), её рисует AppShell.
        def _shell_msg(page: str) -> str:
            raw = page.split('data-shell="', 1)[1].split('"', 1)[0]
            return json.loads(html.unescape(raw))["frame"]["msg"]
        for path in (f"/admin/all?date={_d(1)}&msg=conflict",
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


def suite_live_swap(res: Result) -> None:
    """Живой журнал: опрос #live вместо перезагрузки страницы (08-20).

    Контракт трёхсторонний — layout._shell (обёртка + data-hash),
    schedule/routes._live_fragment (204/200 + X-DP-Hash) и panel.js (подмена).
    Здесь проверяется серверная половина и стыковка: отпечаток в обёртке ОБЯЗАН
    равняться отпечатку фрагмента, иначе первый же опрос привезёт «изменение»
    на неизменном дне и подмена пойдёт каждые 12 секунд — мигание, от которого
    уходили, вернётся молча.

    ⚠️ День — БУДУЩИЙ: на сегодняшнем body несёт метки «сейчас» (подсветка
    текущего часа, past у прошедших визитов), и два запроса по краям смены
    минуты дали бы ложное расхождение."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(14)
        c.post("/admin/add", adate=day, atime="10:00", adoctor="d2",
               aservice="consult", aname="Live Test", aphone="022444555",
               back="/admin/all")
        H = {"X-DP-Live": "1"}

        for path in (f"/admin?date={day}", f"/admin/all?date={day}",
                     f"/admin/week?date={day}", f"/admin/doctor/d2?date={day}"):
            page = c.get(path)
            m = re.search(r'<div id="live" data-hash="([0-9a-f]{32})">', page.body)
            res.ok(f"{path.split('?')[0]} несёт обёртку живого куска",
                   m is not None, "нет <div id=live data-hash=…> — опросу "
                   "нечего подменять")
            fr = c.get(path, headers=H)
            res.ok(f"{path.split('?')[0]} отвечает на опрос фрагментом",
                   fr.status == 200 and "<!doctype" not in fr.body
                   and 'id="live"' not in fr.body,
                   f"код {fr.status}; фрагмент обязан быть НАЧИНКОЙ обёртки, "
                   "без каркаса страницы")
            res.ok(f"{path.split('?')[0]}: отпечаток обёртки = отпечатку фрагмента",
                   m is not None and fr.header("X-DP-Hash") == m.group(1),
                   "разошлись data-hash и X-DP-Hash — первый опрос всегда "
                   "«изменение», подмена каждые 12 секунд")
            res.ok(f"{path.split('?')[0]}: фрагмент лежит в странице дословно",
                   fr.body in page.body,
                   "фрагмент отличается от куска страницы — два источника "
                   "разметки")
            same = c.get(path, headers={"X-DP-Live": "1",
                                        "X-DP-Hash": fr.header("X-DP-Hash")})
            res.ok(f"{path.split('?')[0]}: неизменный день -> 204",
                   same.status == 204 and not same.body,
                   f"код {same.status} — DOM дёргался бы без изменений")
            res.ok(f"{path.split('?')[0]}: у фрагмента версия и запрет кеша",
                   fr.header("X-DP-V") != "" and
                   fr.header("Cache-Control") == "no-store",
                   "без X-DP-V подмена вклеит новую разметку в старый каркас, "
                   "без no-store WebView2 вправе отдать вчерашний ответ")

        # изменение дня — фрагмент другой, и его видно по отпечатку
        p0 = f"/admin/all?date={day}"
        h0 = c.get(p0, headers=H).header("X-DP-Hash")
        c.post("/admin/add", adate=day, atime="12:00", adoctor="d2",
               aservice="consult", aname="Sosit Nou", aphone="022777888",
               back="/admin/all")
        fr2 = c.get(p0, headers={"X-DP-Live": "1", "X-DP-Hash": h0})
        res.ok("новая запись меняет отпечаток и приезжает фрагментом",
               fr2.status == 200 and "Sosit Nou" in fr2.body
               and fr2.header("X-DP-Hash") != h0,
               f"код {fr2.status} — приехавшая бронь не доехала бы до экрана")

        # охрана: опрос без входа не отдаёт ни фрагмента, ни отпечатка
        anon = Client(s.url).get("/admin", headers=H)
        res.ok("опрос без входа отбивается охраной",
               anon.status == 303 and "/admin/login" in anon.location,
               f"код {anon.status} — фрагмент утекал бы мимо входа")

        # неживая страница на заголовок не отзывается — отдаёт обычный каркас
        st = c.get("/admin/settings", headers=H)
        res.ok("неживая страница отвечает на опрос полным каркасом",
               st.status == 200 and "<!doctype" in st.body,
               "settings прикинулась фрагментом")

        # линию «сейчас» сервер больше не рисует — она у panel.js: серверная
        # строка с top из минут делала бы отпечаток всегда другим
        today = c.get("/admin")
        res.ok("линия «сейчас» не серверная",
               "class='nowline'" not in today.body,
               "nowline в body — отпечаток меняется каждую минуту, подмена "
               "каждые 12 секунд")
        pjs = c.get("/static/js/panel.js").body
        res.ok("линию «сейчас» рисует panel.js",
               "placeNowline" in pjs and ".nowline" in pjs,
               "линия исчезла совсем: сервер не рисует, скрипт не подхватил")

        # данные модалок обязаны переисполняться после подмены: data-live + var
        # (const при повторном объявлении — SyntaxError, клик по свежей записи
        # молча перестал бы открывать карточку)
        allp = c.get(p0).body
        res.ok("скрипты данных помечены data-live и объявляют var",
               "<script data-live>" in allp and "var CARDS" in allp
               and "var NOTE_ENDS" in allp and "const CARDS" not in allp
               and "const NOTE_ENDS" not in allp,
               "подмена не переисполнит данные модалок — карточка свежей "
               "записи не откроется")


def suite_nophone(res: Result) -> None:
    """Пациент без телефона (08-20, просьба пилота) и поиск по дате рождения.

    Опоры: галочка = намерение ИЗ ФОРМЫ (прайор 08-16 — не угадывать по
    пустоте); ключ безтелефонного УНИКАЛЕН (db.manual_key — иначе все
    безтелефонные склеились бы в одного, и _upsert переписал бы имя);
    телефон задним числом, совпавший с чужим, называется вслух."""
    with Server() as s:
        c = Client(s.url).login()
        day = _d(21)

        def add(name, phone, t, **kw):
            return c.post("/admin/add", adate=day, atime=t, adoctor="d2",
                          aservice="consult", aname=name, aphone=phone,
                          back="/admin/all", **kw)

        # пустой телефон БЕЗ галочки — прежний отказ: это недозаполненная
        # форма или устаревшая вкладка, а не намерение
        r = add("FaraTel Zero", "", "09:00")
        res.ok("пустой телефон без галочки отбивается", r.msg == "bad_phone",
               f"msg {r.msg!r}")

        # с галочкой — проходит; второй безтелефонный — ОТДЕЛЬНЫЙ человек
        r1 = add("FaraTel Unu", "", "10:00", anophone="1")
        r2 = add("FaraTel Doi", "", "11:00", anophone="1")
        res.ok("запись без телефона проходит с галочкой",
               r1.msg == "ok" and r2.msg == "ok", f"{r1.msg} / {r2.msg}")
        lst = _plist(c, "q=FaraTel")["rows"]
        res.ok("двое безтелефонных НЕ склеились и не переименованы",
               {"FaraTel Unu", "FaraTel Doi"} <= {r["name"] for r in lst},
               "второй перезаписал первого — ключ manual: снова общий")
        # перечёркнутую трубку рисует экран по пустому телефону строки
        res.ok("безтелефонный — пустым телефоном, а не выдуманным",
               all(r["phone"] == "" for r in lst), f"{[(r['name'], r['phone']) for r in lst]}")

        # так шлёт НАСТОЯЩИЙ браузер: выключенное поле в POST отсутствует
        # ВОВСЕ, а не приходит пустым — Form(...) на aphone давал бы 422
        # раньше честного bad_phone (поймано при написании)
        r = c.post("/admin/add", adate=day, atime="13:00", adoctor="d2",
                   aservice="consult", aname="FaraTel Patru", anophone="1",
                   back="/admin/all")
        res.ok("POST без поля aphone (выключенный input) проходит",
               r.msg == "ok", f"msg {r.msg!r}")

        # галочка главнее набранного телефона (вкладка без JS): номер отброшен
        r = add("FaraTel Trei", "069999888", "12:00", anophone="1")
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

        # --- галочка в формах журнала (диалоги фиши и «Pacient nou» — React,
        # их держат проверки клиента) ---
        allp = c.get(f"/admin/all?date={day}").body
        res.check("журнал: галочка в нижней форме и в модалке слота",
                  allp.count('name="anophone"'), 2)


def suite_patient_card(res: Result) -> None:
    """Фиша: профиль, зубная формула, план лечения, алерты, архив."""
    with Server() as s:
        c = Client(s.url).login()
        c.post("/admin/add", adate=_d(1), atime="09:00", adoctor="d2",
               aservice="consult", aname="Card Test", aphone="022654654",
               back="/admin/all")
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
    """Панель: мини-графики, загрузка кресел, повестка дня, метки подсветки.

    Всё перечисленное ломается МОЛЧА — страница остаётся кодом 200 и выглядит
    целой. Отдельная ценность у процента загрузки: он обязан совпадать с тем,
    что за тот же день показывает раздел «Statistici», иначе клиника увидит два
    разных числа про одного врача и перестанет верить обоим.

    День берётся завтрашний намеренно: сегодняшний зависит от часа прогона —
    к вечеру вся повестка «прошедшая», и проверки стали бы плавающими.

    Сервер — grandfather-клиника (флаг «токен нечитаем» = tg_configured):
    шесть плиток с бот-каналом видит только клиника с ботом; ветку «без
    бота» (пять плиток, без блока noi din bot) стережёт suite_bot_ui.
    """
    with Server(env={"DENTART_TOKEN_UNREADABLE": "1"}) as s:
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

        # ⚠️ Короткая запись не влезает в свой ряд: получасовая у клиники — 22px
        # при содержимом на 43. fitAppts ужимает текст в строку, а совсем узкой
        # записи убирает его совсем, и тогда title — единственное, что отвечает
        # «кто это», не открывая карточку. Пиксели тут не проверить (набор без
        # браузера), поэтому стережём то, что можно: подсказку и сам механизм.
        tips = re.findall(r"title='(\d\d:\d\d · \d+′ · [^']+)'", page)
        res.ok("подсказка блока несёт время, длительность, услугу и имя",
               any("Ana Test" in t for t in tips), f"подсказки: {tips[:3]}")
        res.ok("блок записи подгоняется под высоту ряда",
               "fitAppts" in page and "'slim'" in page and "'tiny'" in page
               and "'bare'" in page,
               "нет подгонки — короткая запись снова обрежет текст молча")
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
        # не переполняется — fitAppts не видит ничего, и получасовой визит
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
        # ⚠️ Сторож ПУСТОТЫ, а не придирка: `all([])` — истина, и без него
        # проверка зеленела бы на странице, где графиков нет ВООБЩЕ (например
        # после переезда плиток в React). Та же форма, что у недели ниже:
        # `bgs and all(...)`. Найдено разведкой C26.1.
        pts = re.findall(r"<polyline class='sp-l' points='([^']+)'", page)
        res.ok("ряд графика — ровно две недели, и графики вообще есть",
               pts and all(len(x.split()) == 14 for x in pts),
               f"рядов {len(pts)}, точек {[len(x.split()) for x in pts]}")

        # ⭐ 60′ + 120′ = 180 занятых из 840 рабочих (клиника фикстуры 07–21)
        occ = re.findall(r"title='(\d+) din (\d+) minute de lucru'.*?<b>(\d+)%</b>",
                         page, re.S)
        res.ok("минуты сходятся с процентом на карточке",
               bool(occ) and all(round(100 * int(b) / int(cap)) == int(p)
                                 for b, cap, p in occ), f"{occ}")
        res.check("врач с визитами 60′+120′ — это 21% от 840",
                  next((p for b, _c, p in occ if b == "180"), None), "21")
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
        res.ok("счётчик группирует тысячи",
               "(\\d{3})" in c.get("/static/js/panel.js").body,
               "цифры без разделителя тысяч")

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
        # 08-11: разделителем стал «›» вместо «→» — стрелка U+2192 не входит
        # ни в одно вшитое подмножество Inter, значит её рисовала Windows.
        res.ok("тренд загрузки — двумя значениями, без «pp»",
               "0% › " in page and "10%</span>" in page,
               "нет формы «ieri X% › azi Y%»")
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


def suite_grid_edges(res: Result) -> None:
    """Края дневной сетки: крайние ПОЛНОСТЬЮ закрытые часы уходят в полоску.

    Своя клиника (`clinic_hours.json`): часы 07-21, у всех врачей 09-17, обед
    13-14. В `clinic_test.json` врачи наследуют часы клиники, поэтому закрытых
    рядов там не бывает вовсе и проверять было бы нечего.

    ⚠️ Опасность здесь не косметическая: срезанный ряд может УНЕСТИ С СОБОЙ
    запись вне графика. Визит, назначенный на закрытый час (часы поменяли после
    брони), обязан оставаться видимым — иначе клиника считает время свободным и
    посадит на него второго пациента. Это и стережёт вторая половина набора.

    ⚠️ Обед — тоже полностью закрытый час, но В СЕРЕДИНЕ. Он обязан остаться
    рядом: время на канве линейно, блоки стоят множителями var(--cell) от первого
    часа, и выкинутый средний час сдвинул бы все записи после обеда.
    """
    with Server(clinic="clinic_hours.json") as s:
        c = Client(s.url).login()
        day = _d(1)
        page = c.get(f"/admin?date={day}").body
        times = re.findall(r"<div(?: class='nowh')?>(\d\d):00</div>", page)

        res.check("закрытые края ушли в полоску (две штуки)",
                  page.count("class='gband"), 2)
        # ⭐ Кто менял высоту часа, тот перекладывает линию «сейчас» (08-21,
        # нашёл Олег на канарейке): первый fitGrid идёт при парсинге БЕЗ правой
        # колонки, час встаёт на пол 66, а прогон на DOMContentLoaded растит
        # его до 92-96 — и линия panel.js оставалась в старых пикселях на
        # полтора часа выше, до 30-секундного интервала. Видно только на
        # высоком окне (на 1366 финал = полу) и только после 303-перезагрузки,
        # поэтому ни один прогон этого не видел — держим сам вызов в скрипте.
        # вызов ищем ВНУТРИ тела fitGrid, а не по всей странице: подстрока
        # нашлась бы и в чужом скрипте, и переезд вызова из функции остался
        # бы зелёным (ревью 08-22)
        fitgrid_body = page.split("function fitGrid()", 1)[-1].split(
            "fitGrid();", 1)[0]
        res.ok("fitGrid перекладывает линию «сейчас»",
               "if (window.placeNowline) placeNowline();" in fitgrid_body,
               "смена --cell не возвращает линию — после добавления записи "
               "она видимо прыгает вверх до тика интервала")
        res.ok("первый ряд — первый рабочий час, а не час клиники",
               times[:1] == ["09"], f"колонка времени начинается с {times[:1]}")
        res.ok("хвост после 17:00 срезан",
               times[-1:] == ["16"], f"колонка времени кончается на {times[-1:]}")
        res.ok("07:00 и 08:00 больше не занимают ряд",
               "07" not in times and "08" not in times, f"часы: {times}")
        res.ok("обед остался РЯДОМ, а не полоской", "13" in times,
               "закрытый час в середине срезан — записи после обеда уедут")
        res.ok("полоска объясняет себя подсказкой",
               "Închis · 07:00 - 09:00" in page,
               "нет title у полоски — часы негде прочитать")

        # запись вне графика: 07:00 у врача, который работает с 09:00.
        # ⚠️ /admin/add такую больше НЕ принимает — сервер проверяет график
        # врача (outside_doc, 08-15). Реальный путь появления такой записи —
        # часы врача сузили ПОСЛЕ брони; сеем её маршрутом фиши, который
        # график врача не перепроверяет, — сетке всё равно, откуда визит.
        c.post("/admin/add", adate=day, atime="10:00", adoctor="d2",
               aservice="consult", aname="Devreme Test", aphone="0690700",
               back="/admin/all")
        pid_e = pid_by_phone(c, "0690700")
        c.post_json(f"/api/patients/{pid_e}/appoint", {"date": day, "time": "07:00",
                                                      "doctor": "d2", "service": "consult"})
        page2 = c.get(f"/admin?date={day}").body
        times2 = re.findall(r"<div(?: class='nowh')?>(\d\d):00</div>", page2)
        res.ok("запись вне графика ДЕРЖИТ свой ряд", "07" in times2,
               "ряд срезан вместе с записью — время выглядит свободным")
        res.ok("она видна в сетке", "Devreme Test" in page2, "блока записи нет")
        res.ok("полоска слева пропала, раз ряд занят",
               page2.count("class='gband") == 1,
               "полоска осталась при непустом крайнем часе")
        res.ok("08:00 остался рядом — он больше не край",
               "08" in times2, f"часы: {times2}")

        # ---- та же пауза в таблице «Programări» (08-12) ----
        # На канве обед виден штриховкой, а сетка-таблица строилась по
        # day_slots и обеденный час выбрасывала совсем: 12:00 сменялось на
        # 14:00 без следа. Два экрана про один день говорили разное.
        grid = c.get(f"/admin/all?date={day}").body
        ghours = re.findall(r"<td class='hour[^']*'>(\d\d):00", grid)
        res.ok("часы таблицы идут непрерывно, обед не выпадает",
               ghours == [f"{h:02d}" for h in range(7, 21)], f"часы: {ghours}")
        pause_row = re.search(r"<tr class='hrow off'><td class='hour off'>13:00.*?</tr>",
                              grid, re.S)
        res.ok("обеденный ряд назван «pauză»",
               bool(pause_row) and "<small>pauză</small>" in pause_row.group(0),
               "ряд обеда не помечен — дырка в часах без объяснения")
        res.ok("в обеденный ряд не предлагают записать",
               bool(pause_row) and "class='free'" not in pause_row.group(0)
               and "class='goff'" in pause_row.group(0),
               "«+» в закрытый час: /admin/add отобьёт его через fits_clinic")
        early = re.search(r"<tr class='hrow off'><td class='hour off'>07:00.*?</tr>",
                          grid, re.S)
        res.ok("час вне графика ВРАЧЕЙ закрытым не считается",
               early is None and "Devreme Test" in grid,
               "клиника открыта в 07:00 — закрывать час нельзя, там уже визит")

        # ⭐ Час вне окна ВРАЧА: клиника открыта, но принимать некому. Канва
        # штрихует такие ячейки и не даёт по ним кликнуть — таблица обязана
        # говорить то же самое, иначе одна страница зовёт записать туда, где
        # другая запрещает (и пациент приходит в пустой кабинет).
        row7 = re.search(r"<tr class='hrow'><td class='hour'>07:00.*?</tr>", grid, re.S)
        res.ok("вне графика врача «+» не предлагают — как на канве",
               bool(row7) and "class='free'" not in row7.group(0)
               and "class='goff'" in row7.group(0)
               and "Devreme Test" in row7.group(0),
               "таблица зовёт записать туда, где канва рисует штриховку")
        row9 = re.search(r"<tr class='hrow'><td class='hour'>09:00.*?</tr>", grid, re.S)
        res.ok("в рабочий час врача «+» на месте",
               bool(row9) and "class='free'" in row9.group(0),
               "рабочий час перестал принимать записи")

    # ---- запись, которую обед накрыл ПОСЛЕ брони ----
    # ⛔ Главная опасность этого набора в таблице: час без ряда никто не
    # спрашивает у `starts`, поэтому вместе с рядом исчезал и визит. В списке
    # дня он остаётся, слот занят — а сетка показывает пустоту, и регистратура
    # сажает на это время второго пациента.
    with Server() as s:
        c = Client(s.url).login()
        day = _d(1)
        c.post("/admin/add", adate=day, atime="13:00", adoctor="d2",
               aservice="consult", aname="Pauza Test", aphone="0690713",
               back="/admin/all")
        before = c.get(f"/admin/all?date={day}").body
        res.ok("у клиники без обеда закрытых рядов нет вовсе",
               "class='hrow off'" not in before,
               "штриховка появилась там, где клиника работает весь день")

        r = c.post_json("/api/settings/hours", {"hours": {d: [7, 21, 13, 14] for d in
                                                          ("mon", "tue", "wed", "thu",
                                                           "fri", "sat", "sun")}})
        res.check("обед введён задним числом", r.msg, "ok_set")
        after = c.get(f"/admin/all?date={day}").body
        res.ok("визит, накрытый новым обедом, остался в сетке",
               "Pauza Test" in after, "визит исчез из сетки вместе с рядом")
        res.ok("его ряд помечен паузой",
               "<td class='hour off'>13:00<small>pauză</small>" in after,
               "час выглядит рабочим, хотя клиника на обеде")


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
            c.post("/admin/add", adate=day, atime=time, adoctor=doc, aservice=svc,
                   aname=name, aphone=phone, back="/admin/all")
        # прошлый период той же длины: одна запись «сегодня» для сравнения
        # (08:00 — /admin/add намеренно принимает прошедший час текущего дня)
        c.post("/admin/add", adate=_d(0), atime="08:00", adoctor="d4",
               aservice="consult", aname="Stat Ieri", aphone="069000004",
               back="/admin/all")

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
            c.post("/admin/add", adate=_d(day), atime=time, adoctor=doc,
                   aservice="consult", aname=name, aphone=phone, back="/admin/all")
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
            c.post("/admin/add", adate=_d(1), atime=at, adoctor="d2",
                   aservice="consult", aname=name, aphone=phone,
                   back="/admin/all")
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
            page = c.get("/admin").body
            res.ok("без токена секции «Sincronizări» нет",
                   "Sincronizări" not in page and "Telegram Bot" not in page,
                   "интерфейс замороженного бота виден клинике без токена")
            res.ok("без токена нет плитки Telegram на хабе",
                   "/admin/settings/telegram" not in tiles(c),
                   "плитка бота предлагается клинике без токена")

        # UNREADABLE-флаг = токен был (переезд ПК): раздел обязан ВЕРНУТЬСЯ,
        # иначе клинике после переезда некуда ввести токен заново
        with Server(env={"DENTART_ENV_FILE": str(env_path),
                         "DENTART_TOKEN_UNREADABLE": "1"}) as s2:
            c2 = Client(s2.url).login()
            page = c2.get("/admin").body
            res.ok("настроенный бот остаётся в меню (grandfather)",
                   "Sincronizări" in page and "Telegram Bot" in page,
                   "у клиники с ботом пропал раздел из меню")
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
        dash = c.get("/admin").body
        res.ok("плиток дашборда — без «Prin bot»", "Prin bot" not in dash,
               "плитка бота у клиники без бота")

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
        # ⚠️ Экраны React (настройки, статистика, врачи, пациенты) несут текст
        # в ответах /api/*, а не в странице: обход страницы у них ничего не
        # видит, и сторож молча становился пустым — поэтому в обходе их ответы.
        bot_pid = new_patient(c, "Fara Bot", "069000777")
        leaks = []
        for path in ("/admin", "/admin/all",
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
        # зеркало проверки suite_dashboard «шесть плиток»: без бота их пять
        res.check("плиток-графиков — пять", dash.count("class='spark'"), 5)
        res.ok("подзаголовок без бота", "🤖 bot" not in dash,
               "шапка продаёт замороженный канал")
        res.ok("нет блока «Programări noi din bot»",
               "Programări noi din bot" not in dash, "блок бота остался")
        res.ok("нет строки статуса бота", "Bot Telegram" not in dash
               and "Sincronizat cu botul" not in dash, "строка статуса висит")
        res.ok("нет колокольчика новых из бота", "class='bell'" not in dash,
               "колокольчик ведёт к пустому блоку")
        res.ok("подсказка канвы без бота", "prin bot apar automat" not in dash,
               "подсказка обещает бот-записи")
        day = c.get(f"/admin/all?date={_d(1)}").body
        res.ok("список дня без бот-легенды в шапке", "🤖 bot" not in day,
               "легенда с ботом на /admin/all")
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

    # grandfather: у клиники токен настроен — интерфейс остаётся полным
    with Server(env={"DENTART_TOKEN_UNREADABLE": "1"}) as s:
        c = Client(s.url).login()
        dash = c.get("/admin").body
        res.ok("grandfather: плитка «Prin bot» на месте", "Prin bot" in dash,
               "заморозка отняла интерфейс у клиники с ботом")
        res.ok("grandfather: блок новых из бота жив",
               "Programări noi din bot" in dash, "блок пропал у grandfather")
        res.ok("grandfather: колокольчик на месте", "class='bell'" in dash,
               "колокольчик пропал у grandfather")
        res.ok("grandfather: Sincronizări в сайдбаре", "Sincronizări" in dash,
               "секция пропала у grandfather")
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
    """Контракт живого протокола: тело ДЕТЕРМИНИРОВАНО при неизменных данных.

    ⭐ Это второе свойство протокола, и до 18.09 его не проверял никто.
    `suite_live_swap` рядом сравнивает обёртку с фрагментом В ПРЕДЕЛАХ ОДНОГО
    запроса — такое равенство держится само собой, потому что md5 считается от
    одной строки. А вот что ДВА запроса подряд дадут одно и то же тело, не
    следует ни из чего: достаточно одной серверной строки с минутами, случайного
    id или неустойчивого порядка, и отпечаток становится другим каждые 12 секунд.
    Подмена пойдёт на каждый опрос, мигание вернётся — то самое, от которого
    ушли 08-20 по жалобе пилота, — и увидеть это можно, только простояв на
    странице полминуты. Ни один набор столько не стоит.

    ⚠️ Проверяются ЖИВЫЕ данные, а не пустой день: в дне есть пациент в
    приёмной (`waiting_at`), запись «сейчас» и прошедшая. Минуты ожидания
    обязан рисовать `panel.js` по штампу времени в атрибуте — если их однажды
    напечатает сервер, отпечаток поедет ровно у той клиники, где кто-то ждёт.
    """
    with Server() as s:
        c = Client(s.url).login()
        day = clinic_today().isoformat()
        c.post("/admin/add", adate=day, atime="10:00", adoctor="d2",
               aservice="consult", aname="Live Stabil", aphone="069700700")
        c.post("/admin/add", adate=day, atime="11:00", adoctor="d2",
               aservice="consult", aname="Live Asteapta", aphone="069700701")
        c.post("/admin/add", adate=day, atime="12:00", adoctor="d2",
               aservice="consult", aname="Live Ghost", aphone="069700702")
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
        # дали бы разное тело. Правило держит `test_structure` («выборка дня
        # упорядочена полностью»), здесь — сама ситуация.
        import sqlite3 as _sq
        rows_by_name = {m.group(2): m.group(1) for m in re.finditer(
            r"<tr class='[a-z]+'><td>(\d+)</td>.*?(Live \w+)",
            c.get(f"/admin/all?date={day}").body, re.S)}
        assert {"Live Stabil", "Live Ghost", "Live Asteapta"} <= set(rows_by_name), \
            f"не все визиты фикстуры на месте: {sorted(rows_by_name)}"
        for who in ("Live Stabil", "Live Ghost"):
            c.post(f"/admin/status/{rows_by_name[who]}", to="done",
                   back=f"/admin?date={day}")
        con = _sq.connect(s.dir / "dental.db")
        con.execute("UPDATE appointments SET starts_at ="
                    " (SELECT starts_at FROM appointments WHERE id = ?)"
                    " WHERE id = ?", (rows_by_name["Live Stabil"],
                                      rows_by_name["Live Ghost"]))
        con.commit()
        con.close()

        # пациент В ПРИЁМНОЙ: именно у него минуты ожидания и мог бы поехать
        # отпечаток, если бы их печатал сервер
        page = c.get(f"/admin?date={day}").body
        # ⚠️ Форм статуса на странице нет: статус меняют из модалки записи, и
        # номер визита берётся из data-appt. Искать «/admin/status/» бесполезно.
        aids = re.findall(r"data-appt='(\d+)'", page)
        assert aids, "на дне нет ни одной записи — сеять нечего"
        res.ok("ничья в сортировке в фикстуре ЕСТЬ: две строки на одну минуту "
               "у одного имени",
               page.count(f"data-appt='{rows_by_name['Live Ghost']}'") > 0
               and "Live Ghost" in page,
               "легаси-строка не доехала до дня — набор проверял бы "
               "детерминизм мимо ничьей")
        c.post(f"/admin/status/{rows_by_name['Live Asteapta']}", to="waiting",
               back=f"/admin?date={day}")

        H = {"X-DP-Live": "1"}
        for path in (f"/admin?date={day}", f"/admin/all?date={day}",
                     f"/admin/week?date={day}", f"/admin/doctor/d2?date={day}"):
            name = path.split("?")[0]
            a = c.get(path, headers=H)
            b = c.get(path, headers=H)
            if a.body != b.body:
                # ⚠️ Могли пересечь границу часа между запросами: подсветка
                # текущего часа дискретна и меняться ВПРАВЕ раз в час. Второй
                # шанс отличает редкий переход от настоящего недетерминизма.
                b = c.get(path, headers=H)
                a = c.get(path, headers=H)
            res.ok(f"{name}: два запроса подряд дают одно тело",
                   a.body == b.body,
                   "тело меняется само по себе — подмена пойдёт на КАЖДЫЙ опрос "
                   "и мигание вернётся; ищите в теле время, минуты, случайный id "
                   "или неустойчивый порядок")
            res.ok(f"{name}: и один отпечаток",
                   a.header("X-DP-Hash") == b.header("X-DP-Hash"),
                   f"{a.header('X-DP-Hash')} против {b.header('X-DP-Hash')}")

        # Данные изменились — отпечаток ОБЯЗАН стать другим, иначе живой журнал
        # молчит о новой записи, и это вторая половина того же контракта.
        before = c.get(f"/admin?date={day}", headers=H).header("X-DP-Hash")
        c.post("/admin/add", adate=day, atime="15:30", adoctor="d2",
               aservice="consult", aname="Live Nou", aphone="069700702")
        after = c.get(f"/admin?date={day}", headers=H).header("X-DP-Hash")
        res.ok("новая запись меняет отпечаток", before != after,
               "отпечаток не заметил новую запись — опрос вернёт 204, и стойка "
               "не увидит бронь из бота, пока не обновит страницу руками")

        # Минуты ожидания рисует БРАУЗЕР по штампу времени: сервер печатает
        # только data-since. Иначе тело менялось бы каждую минуту у любой
        # клиники, где кто-то сидит в приёмной.
        page = c.get(f"/admin?date={day}").body
        res.ok("пациент в приёмной на странице есть (иначе проверка ниже пуста)",
               "wait-min" in page, "статус «в приёмной» не поставился")
        res.ok("минуты ожидания — штампом для panel.js, а не текстом сервера",
               "data-wait-since=" in page and not re.search(r"wait-min[^>]*>\s*\d+\s*min", page),
               "сервер печатает минуты сам — отпечаток поедет там, где ждут")


# --- C24: неделя. Пин ПОВЕДЕНИЯ, а не разметки -----------------------------
# ⚠️ До 18.09 неделя была покрыта двумя вещами: «отвечает 200» и участием в
# живом протоколе. Всё, ради чего страница существует — какие дни показаны,
# сколько записей, что написано в чипе, — не проверялось ни одним символом.
# Перенос в React без этого терял бы поведение молча, а выглядел бы рабочим.

# ⚠️ День из шапки колонки — день ЖУРНАЛА (`/admin/all`, 06.10): неделя с тех
# пор — раздел «Programări», а не панель.
_WEEK_COL = re.compile(r"<div class='wcol'><div class='wh( tdy)?'>"
                       r"<a href='/admin/all\?date=(\d{4}-\d\d-\d\d)'>([^<]+)</a>"
                       r"<small>(\d+) programări</small></div>"
                       r"<div class='wb'>(.*?)</div></div>", re.S)


def _week_cols(body: str) -> list[dict]:
    """Колонки недели по порядку: дата, подпись, счётчик, «сегодня», чипы."""
    out = []
    for tdy, date, label, count, inner in _WEEK_COL.findall(body):
        out.append({"date": date, "label": label.strip(), "count": int(count),
                    "today": bool(tdy), "chips": re.findall(r"<div class='wchip([^']*)'", inner),
                    "inner": inner})
    return out


def _close_weekend(c: Client) -> bool:
    """Закрыть субботу и воскресенье — тем же телом, что шлёт страница часов.

    ⚠️ Закрывать ПОСЛЕ сева: на нерабочий день запись через форму не
    создаётся (`/admin/add` проверяет часы клиники), и это само по себе
    поведение — см. проверку «на закрытый день записать нельзя». Поэтому
    суббота сначала рабочая, запись в неё кладётся, и лишь затем день
    закрывается — ровно так, как бывает у клиники, поменявшей график.
    """
    hours = {"mon": [7, 21], "tue": [7, 21], "wed": [7, 21], "thu": [7, 21],
             "fri": [7, 21], "sat": None, "sun": None}
    return c.post_json("/api/settings/hours", {"hours": hours}).status == 200


def suite_week(res: Result) -> None:
    """Неделя: диапазон, колонки, счётчики, чипы, цвета, навигация."""
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
                  sum(1 for x in _week_cols(c.get("/admin/week").body) if x["today"]), 1)

        # суббота пока рабочая — кладём в неё запись, она переживёт закрытие дня
        sat = c.post("/admin/add", adate=d(5), atime="11:00", adoctor="d2",
                     aservice="consult", aname="Vasile Lupu", aphone="069800802")
        res.ok("на рабочую субботу запись создаётся", sat.msg == "ok",
               f"код {sat.msg} — дальше проверять нечего")
        res.ok("выходные закрыты через настройки часов", _close_weekend(c),
               "часы не сохранились")

        page = c.get(f"/admin/week?date={d(2)}").body
        cols = _week_cols(page)
        res.check("пять рабочих дней плюс суббота с записью",
                  [x["date"] for x in cols], [d(i) for i in range(6)])
        res.ok("пустой рабочий день говорит «— liber —»", "— liber —" in page,
               "пустой день молчит")
        res.ok("воскресенье без записей скрыто", d(6) not in page,
               "пустой выходной обязан исчезнуть из недели")
        bad = c.post("/admin/add", adate=d(6), atime="11:00", adoctor="d2",
                     aservice="consult", aname="Nu Merge", aphone="069800809")
        res.check("на закрытый день записать нельзя — «вне рабочих часов»",
                  bad.msg, "outside")

        # среда: две записи и заметка стойки
        c.post("/admin/add", adate=d(2), atime="09:00", adoctor="d2",
               aservice="consult", aname="Ion Popa", aphone="069800800")
        c.post("/admin/add", adate=d(2), atime="10:30", adoctor="d2",
               aservice="pain", aname="Maria Rusu", aphone="069800801")
        c.post("/admin/note", ndate=d(2), ntime="12:00", ndoctor="d2",
               ntext="Livrare materiale")
        page = c.get(f"/admin/week?date={d(2)}").body
        cols = _week_cols(page)
        res.check("состав колонок не поехал от новых записей",
                  [x["date"] for x in cols], [d(i) for i in range(6)])
        res.ok("подпись дня — своя у каждой колонки, не по индексу",
               len({x["label"] for x in cols}) == 6,
               f"подписи повторяются: {[x['label'] for x in cols]}")
        wed = next(x for x in cols if x["date"] == d(2))
        res.check("счётчик дня считает записи и НЕ считает заметку",
                  wed["count"], 2)
        res.ok("итог недели — сумма записей без заметок",
               "3 programări" in page, "итог недели посчитан неверно")
        res.check("в среду три чипа: две записи и заметка",
                  (len(wed["chips"]), wed["chips"].count(" gnote")), (3, 1))
        res.ok("чип записи несёт час, имя и услугу",
               "<b>09:00</b> Ion Popa" in wed["inner"]
               and "Consultație" in wed["inner"], "чип потерял содержимое")
        res.ok("чип заметки пунктирный и без имени пациента",
               "1px dashed" in wed["inner"] and "Livrare materiale" in wed["inner"],
               "заметка выглядит как запись")

        # цвет — токеном темы, а не хексом: клиника выбирает свой цвет
        bgs = re.findall(r"class='wchip'[^>]*background:([^;]+);", wed["inner"])
        res.ok("фон чипа — переменная темы, а не зашитый цвет",
               bgs and all(b.strip().startswith("var(--") for b in bgs),
               f"в стиле чипа хекс: {bgs}")

        # неявка: зачёркивание живёт классом, а не разметкой
        aid = re.findall(r"data-appt='(\d+)'", c.get(f"/admin?date={d(2)}").body)
        assert aid, "запись не нашлась на дне"
        c.post(f"/admin/status/{aid[0]}", to="noshow", back=f"/admin?date={d(2)}")
        wed = next(x for x in _week_cols(c.get(f"/admin/week?date={d(2)}").body)
                   if x["date"] == d(2))
        res.ok("неявка помечена классом noshow", " noshow" in wed["chips"],
               "неявка неотличима от обычной записи")

        # отменённая запись исчезает со страницы целиком
        c.post(f"/admin/status/{aid[0]}", to="cancelled", back=f"/admin?date={d(2)}")
        wed = next(x for x in _week_cols(c.get(f"/admin/week?date={d(2)}").body)
                   if x["date"] == d(2))
        res.check("отменённая запись ушла из недели и из счётчика",
                  (len(wed["chips"]), wed["count"]), (2, 1))

        # навигация: ровно ±7 дней от понедельника, «Azi» без параметра
        nav = page.split("<div class='nav'>", 1)[1].split("</div>", 1)[0]
        res.ok("навигация ведёт на ±7 дней и на сегодня",
               f"/admin/week?date={(monday - timedelta(days=7)).isoformat()}" in nav
               and f"/admin/week?date={(monday + timedelta(days=7)).isoformat()}" in nav
               and "href='/admin/week'>Azi" in nav, "навигация недели сбита")
        res.ok("в шапке — диапазон понедельник–воскресенье",
               f"{monday.strftime('%d.%m')} – "
               f"{(monday + timedelta(days=6)).strftime('%d.%m.%Y')}" in nav,
               "диапазон недели показан неверно")
        res.ok("клик по шапке дня ведёт в день журнала («Programări»)",
               f"/admin/all?date={d(2)}" in page, "нет ссылки на день")
        res.ok("вкладка «Zi» недели — день журнала, а не панель",
               f"href='/admin/all?date={d(2)}'>Zi" in nav, "«Zi» ведёт не туда")

        res.check("на будущей неделе не подсвечен никто",
                  sum(1 for x in cols if x["today"]), 0)

        # любая дата недели даёт ТУ ЖЕ неделю: страница ключуется понедельником
        res.check("любой день недели открывает одну и ту же неделю",
                  [x["date"] for x in _week_cols(c.get(f"/admin/week?date={d(4)}").body)],
                  [x["date"] for x in cols])
        res.ok("кривая дата не роняет страницу",
               c.get("/admin/week?date=2026-13-99").status == 200,
               "кривая дата обязана молча открыть текущую неделю")


# --- C25.2: пины страниц поверх проверенного построителя -------------------
# ⚠️ Контракт самой сетки живёт в `test_grid.py` и проверяет функцию. Здесь
# другое: что страница отдаёт построителю ТО, ЧТО НАДО, и кладёт результат
# туда, куда надо. Одна и та же сетка на двух экранах, и данные в них разные:
# «Toți medicii» — все врачи и все записи дня, день врача — один врач и
# только его записи.

def _grid_heads(body: str) -> list[str]:
    """Имена колонок сетки по порядку."""
    return re.findall(r"<a class='dh-n'[^>]*>([^<]+)</a>", body)


def _grid_appts(body: str) -> list[str]:
    """Номера записей, попавших в сетку (а не в список под ней)."""
    grid = body.split("<table class='grid'>", 1)[1].split("</table>", 1)[0]
    return re.findall(r"data-appt='(\d+)'", grid)


def _seed_day(c: Client, day: str) -> dict:
    """День с двумя врачами, длинным визитом, заметкой и отменой."""
    c.post("/admin/add", adate=day, atime="09:00", adoctor="d2",
           aservice="consult", aname="Ion Popa", aphone="069140140")
    c.post("/admin/add", adate=day, atime="10:00", adoctor="d3",
           aservice="pain", aname="Maria Rusu", aphone="069140141")
    c.post("/admin/add", adate=day, atime="11:00", adoctor="d2",
           aservice="long", aname="Vasile Lupu", aphone="069140142")
    c.post("/admin/note", ndate=day, ntime="15:00", ndoctor="d2",
           ntext="Livrare materiale")
    ids = re.findall(r"data-appt='(\d+)'", c.get(f"/admin/all?date={day}").body)
    return {"ids": ids}


def suite_all_page(res: Result) -> None:
    """`/admin/all`: все врачи, все записи дня, форма и список под сеткой."""
    with Server() as s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=3)).isoformat()
        _seed_day(c, day)
        body = c.get(f"/admin/all?date={day}").body

        active_docs = [x["name"] for x in
                       json.loads(c.get("/api/doctors").body)["data"]["doctors"]
                       if not x.get("archived") and x.get("status") == "activ"]
        res.check("колонки — активные врачи справочника, в его порядке",
                  _grid_heads(body), active_docs)
        res.ok("записи обоих врачей попали в сетку",
               len(_grid_appts(body)) >= 3, "сетка недосчиталась записей")
        res.ok("заметка стойки тоже в сетке",
               "appt note" in body, "заметка стойки пропала")
        res.ok("под сеткой — форма записи и список дня",
               "id=\"addform\"" in body or "addform" in body,
               "форма записи пропала со страницы")
        res.ok("день открывается на нужной дате",
               f"date={day}" in body, "страница не помнит дату")

        # фильтр по плитке: список фильтруется, сетка остаётся целой
        f = c.get(f"/admin/all?date={day}&f=noshow").body
        res.ok("фильтр показывает свой баннер",
               "Filtru:" in f, "фильтр не отработал")
        res.check("сетка при фильтре не редеет",
                  len(_grid_appts(f)), len(_grid_appts(body)))

        res.ok("страница живая: обёртка и метка опроса",
               'id="live"' in body and 'data-reload="12"' in body,
               "«Toți medicii» перестала быть живой")


def suite_doctor_page(res: Result) -> None:
    """День одного врача: ТОЛЬКО его записи и одна колонка."""
    with Server() as s:
        c = Client(s.url).login()
        day = (clinic_today() + timedelta(days=3)).isoformat()
        _seed_day(c, day)
        all_ids = set(_grid_appts(c.get(f"/admin/all?date={day}").body))
        body = c.get(f"/admin/doctor/d2?date={day}").body

        res.check("колонка одна и это выбранный врач",
                  _grid_heads(body), ["Dr. Activ Doi"])
        mine = set(_grid_appts(body))
        res.ok("в сетке только записи этого врача",
               mine and mine < all_ids, f"его записи: {mine}, все: {all_ids}")
        res.ok("чужая запись не показана",
               "Maria Rusu" not in body.split("<table class='grid'>", 1)[1],
               "запись другого врача попала в день врача")
        res.ok("в шапке имя врача и ссылки на панель и на всех",
               "Dr. Activ Doi" in body and "/admin/all?date=" in body,
               "шапка дня врача потеряла навигацию")
        res.ok("страница живая", 'data-reload="12"' in body, "день врача не живой")
        res.check("чужой врач в адресе — на журнал",
                  c.get("/admin/doctor/d999").status, 307)

        # выключенный врач остаётся доступен как история
        r = c.post_json("/api/doctors/d3", {"name": "Dr. Activ Trei", "status": "concediu"})
        res.check("врач отправлен в отпуск (иначе проверка ниже пуста)",
                  r.msg, "ok_med")
        off = c.get(f"/admin/doctor/d3?date={day}").body
        res.ok("выключенный врач открывается и помечен как история",
               "inactiv (istoric)" in off,
               "выключенный врач исчез вместе с историей")
        allb = c.get(f"/admin/all?date={day}").body
        res.ok("и остаётся колонкой в общем дне, пока у него есть записи",
               "Dr. Activ Trei" in _grid_heads(allb),
               "записи выключенного врача негде смотреть")
