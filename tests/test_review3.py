"""Находки ревью волны 3 (08-16): интерфейс и статистика.

Шесть дефектов, ни один из которых не виден на машине разработчика:

  * фирменные кнопки при наведении меняют фон на --teal-d, а текст оставляют
    --on-teal — на зелёном по умолчанию обе переменные белые, а у клиники со
    светлым выбором это тёмный текст на тёмном фоне (3.1:1);
  * стрелка молочного прикуса нарисована знаками U+25B8/U+25BE — их рисует
    Windows своим шрифтом, мимо цвета клиники (правило карты 08-11, но сторож
    смотрит только в .py и до panel.css не доходит);
  * часы в подвале сайдбара пишутся один раз при загрузке: автоперезагрузку
    сервер выдаёт только живому расписанию, поэтому на фише и в списках они
    весь день показывают время ОТКРЫТИЯ страницы;
  * гейт svc_empty в карточке врача проверял ЛЮБУЮ услугу без активных
    исполнителей — чужой отпуск запирал сохранение услуг у всех остальных;
  * опечатка в годе (<input type=date> принимает 0012-08-15) уводила
    /admin/stats в период на 735 000 дней и роняла страницу без ответа;
  * подпись «botul a adus» считала неявки, а число над ней — нет: подпись
    объявляла часть больше целого.

И согласование формы с сервером: список часов нижней формы журнала строился по
часам КЛИНИКИ, а /admin/add отказывает по графику ВРАЧА (outside_doc).
"""
import re
from datetime import date, timedelta

from harness import BOT, TG_ON, Bot, Client, Result, Server

CSS = BOT / "app" / "static" / "css" / "panel.css"
JS = BOT / "app" / "static" / "js" / "panel.js"

# Знаки, которые рисует система: те же диапазоны, что стережёт
# test_structure._SYSGLYPH в питоновских литералах. Вшитый Inter их не
# покрывает, поэтому в CSS-свойстве content им тоже не место.
_SYSGLYPH = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2200-\u22FF"
                       "\u2300-\u23FF\u25A0-\u27BF\u2B00-\u2BFF]")

_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _d(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _rules() -> list[tuple[str, str]]:
    """(селектор, объявления) для каждого правила panel.css."""
    return [(m.group(1).strip(), m.group(2))
            for m in _RULE.finditer(CSS.read_text(encoding="utf-8"))]


# ---------- 1. фирменный цвет: у текста есть СВОЙ фон ----------

def suite_css(res: Result) -> None:
    """panel.css: --teal-d как фон обязан называть --on-teal-d как текст.

    ⚠️ Правило карты 08-09 живёт проверкой ровно одного места (.side .brand в
    test_theme). Кнопки меняют фон на --teal-d при наведении, а цвет текста
    берут из правила покоя — то есть --on-teal, посчитанный под СВЕТЛЫЙ --teal.
    На зелёном по умолчанию обе переменные белые, и разработчику это невидимо.
    """
    by_sel: dict[str, list[str]] = {}
    for sel, body in _rules():
        if "--teal-d" in body or "--on-teal" in body:
            by_sel.setdefault(sel, []).append(body)
    bad = [sel for sel, bodies in by_sel.items()
           if any("background:var(--teal-d)" in b for b in bodies)
           and not any("color:var(--on-teal-d)" in b for b in bodies)]
    res.ok("фон --teal-d всегда называет свой цвет текста", not bad,
           "правила красят фон тёмным фирменным, а текст берут чужой "
           f"(--on-teal посчитан под светлый --teal): {bad}")

    # знаки в content: их рисует Windows, а не вшитый Inter
    bad = []
    for sel, body in _rules():
        for m in re.finditer(r"content\s*:\s*(['\"])(.*?)\1", body):
            found = "".join(dict.fromkeys(_SYSGLYPH.findall(m.group(2))))
            if found:
                bad.append(f"{sel} -> {found}")
    res.ok("оформление не просит знаки у Windows", not bad,
           "content со знаком вне подмножеств Inter (нужен чистый CSS или "
           f"иконка): {bad}")

    # ⚠️ В плитке <b> — крупное значение (30px блоком), а подпись рисуется в
    # <small>; красить в ней слово через <b> — обычное желание, и оно выносило
    # «disponibilă v1.20.2» и предупреждение BitLocker за границы карточки.
    # Правило-глушитель обязано существовать, пока подписи умеют красить словом.
    # ⚠️ _rules() наивна: комментарий перед правилом попадает В СЕЛЕКТОР,
    # поэтому сверять надо по последней строке после «*/», а не по всей строке
    def _sel(raw: str) -> str:
        return raw.split("*/")[-1].strip().replace(" ", "")

    big = [body for sel, body in _rules()
           if _sel(sel) == ".pl-tvb" and "font-size:30px" in body]
    calm = [body for sel, body in _rules() if _sel(sel) == ".pl-tvsmallb"]
    res.ok("крупное значение плитки не подменяет собой подпись",
           not big or (calm and any("font-size:inherit" in b for b in calm)),
           "у .pl-tv b крупный кегль, а .pl-tv small b его не гасит — "
           "покрашенное слово в подписи вылезет из карточки")


# ---------- 2. часы сайдбара ----------

def suite_clock(res: Result) -> None:
    """Часы в подвале обновляются сами и идут по часам КЛИНИКИ."""
    js = JS.read_text(encoding="utf-8")
    block = js.split("sf_clock", 1)[-1].split("data-reload", 1)[0]
    res.ok("часы пересчитываются по таймеру", "setInterval(" in block,
           "sf_clock пишется один раз при загрузке, а автоперезагрузку "
           "сервер выдаёт только живому расписанию (LIVE_RELOAD)")
    res.ok("пояс берётся из разметки, а не у устройства",
           "data-tz" in block and "timeZone" in block,
           "часы считаются в поясе браузера — в облаке через туннель это "
           "чужой пояс, а весь остальной экран размечен часами клиники")
    with Server() as s:
        c = Client(s.url).login()
        page = c.get("/admin/search").body
        res.ok("сервер отдаёт часовой пояс клиники",
               'id="sf_clock" data-tz="Europe/Chisinau"' in page,
               "нет data-tz у #sf_clock")


# ---------- 3. услуги врача ----------

def suite_doc_services(res: Result) -> None:
    """Гейт svc_empty стережёт ТОЛЬКО услуги, которых касается эта отправка.

    В clinic_test.json «orphan» закреплена за одним d1, а он в архиве. Раньше
    любая правка услуг у d2/d3/d4 упиралась в неё: цикл доходил до чужой
    услуги, видел «активных исполнителей нет» и отбивал всю форму целиком.
    """
    with Server() as s:
        c = Client(s.url).login()
        r = c.post("/admin/doctor-card/d3/services", svc="hygiene")
        res.check("чужая осиротевшая услуга не мешает сохранить свои",
                  r.msg, "ok_svc_med")

        # обратная сторона: СВОЮ последнюю услугу так не осиротить
        r = c.post("/admin/doctor-card/d3/services", svc="consult")
        res.check("снять себя с услуги, где ты последний активный, нельзя",
                  r.msg, "svc_empty")


# ---------- 4. границы периода в аналитике ----------

def suite_stats_period(res: Result) -> None:
    """Опечатка в годе получает внятный отказ, а не молчание.

    `<input type=date>` отдаёт «0012-08-15» как законную ISO-дату; период
    выходил в 735 000 дней, и вычитание такого срока падало OverflowError —
    маршрут его не ловил, а BaseHTTPMiddleware не отдаёт ответ вовсе.
    """
    with Server() as s:
        c = Client(s.url).login()
        today = date.today().isoformat()
        r = c.get(f"/admin/stats?from=0012-08-15&to={today}")
        res.check("промах по сегменту года — отказ, а не падение",
                  (r.status, r.msg), (303, "bad_period"))
        r = c.get(f"/admin/stats?from=1900-01-01&to={today}")
        res.check("век вместо недели — тот же отказ",
                  (r.status, r.msg), (303, "bad_period"))
        res.ok("отказ показывается словами",
               "Perioada" in c.get("/admin/stats?msg=bad_period").body,
               "страница не показывает баннер bad_period")
        r = c.get(f"/admin/stats?from={_d(-30)}&to={today}")
        res.check("обычный период по-прежнему открывается", r.status, 200)


# ---------- 5. «botul a adus» ----------

def suite_stats_bot(res: Result) -> None:
    """Подпись карточки считает те же визиты, что и само число: без неявок."""
    with Server(clinic="clinic_split.json", env=TG_ON) as s:
        day = _d(1)
        for i, (name, phone) in enumerate((("Bot Unu", "069100100"),
                                           ("Bot Doi", "069100200"))):
            b = Bot(Client(s.url), f"bot-value-{i}")
            b.say("/start"); b.say("lang:ro"); b.say("book")
            b.say("svc:consult"); b.say("doc:db")
            b.say(f"day:{day}"); b.say(f"time:{day}T15:00" if i == 0
                                       else f"time:{day}T16:00")
            b.say(name); b.say("skip_year"); b.say(phone)
            b.say("confirm")

        c = Client(s.url).login()
        page = c.get(f"/admin/all?date={day}").body
        row = ""
        for m in re.finditer(r"<tr class='[^']*'>.*?</tr>", page, re.S):
            if "Bot Doi" in m.group(0):
                row = m.group(0)
        aid = row.split("/admin/status/", 1)[1].split("'")[0]
        c.post(f"/admin/status/{aid}", to="noshow", back=f"/admin/all?date={day}")

        stats = c.get(f"/admin/stats?from={day}&to={day}").body
        # ⚠️ Смотрим В ОДНУ карточку: число и подпись под ним обязаны считать
        # одни и те же визиты, а «200 MDL» на странице есть законно — «Top
        # servicii» перечисляет ЗАПИСИ, а не выручку
        card = [x for x in stats.split("<div class='fcard an-money'>")
                if "Venituri estimate" in x][0]
        res.ok("выручка периода не считает неявку",
               "data-count='100'" in card,
               "число карточки изменилось — проверка потеряла опору")
        res.ok("подпись «botul a adus» считает тем же правилом",
               "botul a adus cca 100 MDL" in card,
               "подпись включает неявку и превышает саму выручку: "
               + card[card.find("botul a adus"):][:40])


# ---------- 6. форма журнала и график врача ----------

def _time_options(page: str) -> list[str]:
    form = page.split('<form class="add"', 1)[1].split("</form>", 1)[0]
    block = form.split('name="atime"', 1)[1].split("</select>", 1)[0]
    return re.findall(r"value='(\d\d:\d\d)'", block)


def suite_form_hours(res: Result) -> None:
    """Нижняя форма журнала предлагает часы ВЫБРАННОГО врача.

    Сервер отказывает outside_doc по личному графику (work_from/work_to), а
    список строился по часам клиники — форма предлагала 15:00 утреннему врачу
    и получала отказ на то, что сама же и подсказала.
    """
    with Server(clinic="clinic_split.json") as s:
        c = Client(s.url).login()
        day = _d(1)

        times = _time_options(c.get(f"/admin/doctor/da?date={day}").body)
        res.ok("день утреннего врача: только его часы (9-13)",
               times and times[0] == "09:00" and times[-1] == "12:30",
               f"предложено {times[:4]}…{times[-2:]} при окне 9-13")
        times = _time_options(c.get(f"/admin/doctor/db?date={day}").body)
        res.ok("день вечернего врача: только его часы (14-18)",
               times and times[0] == "14:00" and times[-1] == "17:30",
               f"предложено {times[:4]}…{times[-2:]} при окне 14-18")

        page = c.get(f"/admin/all?date={day}&doctor=da").body
        res.ok("общий журнал: список открыт по выбранному врачу",
               _time_options(page)[:1] == ["09:00"],
               f"предложено {_time_options(page)[:4]} при окне da 9-13")
        res.ok("смена врача в форме переписывает часы",
               "DOC_TIMES" in page and '"db"' in page.split("DOC_TIMES", 1)[1][:400],
               "на странице нет часов по врачам — выбор врача не меняет список")


# ---------- 7. ширина: страница во всё окно, строка — нет (08-16) ----------

# Носители сплошного текста. ⚠️ Список ВКЛЮЧАЕТ требование, значит гниёт молча
# (полярность из CLAUDE.md): переименуют класс — правило станет искать имя,
# которого нет, найдёт ноль нарушителей и позеленеет навсегда. Поэтому ниже
# отдельная проверка, что эти имена ещё живут в разметке.
_PROSE = (".hint", ".banner")

# Ниже этого числа потолок страницы означает пустое поле справа: на 2560 старые
# 1500px оставляли 844px пустоты одним куском. 2000 — граница «это ещё ширина
# окна, а не колонка чтения», а не сама величина потолка (она 2200).
_PAGE_MIN = 2000

# Сетки, которым auto-fill ВЕРЕН, и это решение, а не недосмотр: миниатюры
# документов и флажки анамнеза — предметы своего размера, растянуть их значит
# испортить (замер: три миниатюры под auto-fit становятся полосами 582×120).
# ⚠️ Список ВКЛЮЧАЕТ требование → гниёт молча, поэтому ниже проверяется, что
# каждое имя ещё и правда объявлено с auto-fill: перевели сетку на fit —
# исключение протухло и должно уйти отсюда, а не молча разрешать чужой промах.
_FILL_OK = (".docgrid", ".anbox")

# Сеток в файле заведомо больше: проверка «нарушителей нет» позеленела бы разом,
# если бы разбор перестал их находить (переименуют свойство, сменят запись).
_GRIDS_MIN = 6

# Колонка «Preț» в таблице услуг. 150px — это 106px текста при самой длинной
# настоящей цене в 97px («1000–1200 MDL»); на прежних 120px влезало 78px, и
# вилка цен резалась одинаково на 2560 и на рабочем 1366.
_PRET_MIN = 150


def _sel(raw: str) -> str:
    """Селектор правила. ⚠️ _rules() наивна: комментарий перед правилом
    попадает В селектор, поэтому берём последнюю строку после «*/»."""
    return raw.split("*/")[-1].strip().replace(" ", "")


def _py_sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in (BOT / "app").rglob("*.py"))


def suite_width(res: Result) -> None:
    """Ширина окна отдаётся ВСЕМ разделам, а потолок живёт у текста.

    До 08-16 широкими были два дневных вида (layout.WIDE_PAGES), а остальным
    доставался потолок 1500px без центрирования: на 27" замер давал 844px
    пустоты справа у пациентов, врачей, статистики и настроек. Сняли потолок
    страницы — и тут же выросла строка: подсказка тянулась на 2152px. Оба
    конца и сторожим, потому что ломаются они по-разному и оба молча: узкую
    страницу видно только на большом мониторе, длинную строку — только когда
    её пробуют читать.
    """
    rules = _rules()
    css = CSS.read_text(encoding="utf-8")

    base = [b for s, b in rules if _sel(s) == ".content"]
    res.ok("страница тянется во всю ширину окна",
           any("width:100%" in b and "margin-inline:auto" in b for b in base),
           "у .content нет width:100% с центрированием: без ширины flex-элемент "
           "с авто-полями схлопывается по содержимому, без центрирования весь "
           "остаток окна уходит пустым полем СПРАВА")

    # Потолок страницы: он есть (иначе колонка врача расплывётся на 4K), но не
    # тот, из-за которого жаловались. Числа берём у ЛЮБОГО правила .content* —
    # так же вернулся бы и узкий вариант вроде .content.narrow.
    tight = []
    for s, b in rules:
        if not _sel(s).startswith(".content"):
            continue
        for m in re.finditer(r"max-width:\s*(\d+)px", b):
            if int(m.group(1)) < _PAGE_MIN:
                tight.append(f"{_sel(s)} -> {m.group(1)}px")
    res.ok("страница не заперта в колонку чтения", not tight,
           f"у .content потолок ниже {_PAGE_MIN}px — это снова пустое поле "
           f"справа на широком мониторе: {tight}")
    res.ok("свой потолок у страницы всё-таки есть",
           any("max-width:" in b and "none" not in b for b in base),
           "потолок снят совсем: на 4K колонка врача уходит в 801px, и часовой "
           "визит раздувается в блок под три строки текста")

    # ---- потолок СТРОКИ ----
    root = [b for s, b in rules if _sel(s) == ":root"]
    res.ok("потолок текста назван один раз (--measure в :root)",
           any("--measure:" in b for b in root),
           "переменной --measure нет — значит число стоит по месту, и следующий "
           "абзац заведёт своё")
    for cls in _PROSE:
        bodies = [b for s, b in rules if _sel(s) == cls]
        res.ok(f"{cls}: у сплошного текста свой потолок",
               any("max-width:var(--measure)" in b for b in bodies),
               f"{cls} растягивается вместе со страницей — на 2560 это строка "
               f"в 2152px, и глаз не находит начало следующей")

    # ⭐ ПОЛЯРНОСТЬ: без этого правило выше зеленеет от переименования класса
    src = _py_sources()
    for cls in _PROSE:
        name = cls.lstrip(".")
        used = re.search(rf"class=['\"][^'\"]*\b{name}\b", src)
        res.ok(f"класс {cls} ещё живёт в разметке", bool(used),
               f"в исходниках нет ни одного class='{name}' — правило про его "
               f"потолок ищет несуществующее имя и зеленеет вхолостую")

    # ---- ряд формы: подпись + поле ----
    setb = [b for s, b in rules if _sel(s) == "table.set"]
    res.ok("ряд формы не растягивается на весь монитор",
           any("max-width:var(--measure-form)" in b for b in setb),
           "table.set без потолка: на 2560 поле «Telefon» становится 1500px, а "
           "шесть списков программы работы разъезжаются по 350px каждый")
    res.ok("потолок формы снимается модификатором, а не наоборот",
           "table.set.set-wide" in css and "set-wide" in src,
           "нет пары «потолок по умолчанию + set-wide на таблице данных»: либо "
           "правило пропало, либо таблица услуг (восемь колонок) потеряла класс")

    # Фиша таблицей не размечена, поэтому свой потолок ей нужен отдельно: на
    # 2560 её главная колонка 1812px, и «Notă (opțional…)» становилось полем в
    # 1780px, а «+ Adaugă în plan» — зелёной полосой во всю ширину.
    fform = [b for s, b in rules if _sel(s) == ".fform"]
    res.ok("формы фиши держат тот же потолок ряда, что и настройки",
           any("max-width:var(--measure-form)" in b for b in fform),
           "у .fform нет потолка --measure-form: поля и кнопки фиши "
           "растягиваются на всю ширину главной колонки")
    res.ok("потолок ряда формы назван ОДНИМ числом",
           len([b for s, b in rules
                if "max-width:" in b and "--measure-form" not in b
                and _sel(s) in (".fform", "table.set")]) == 0,
           "у .fform или table.set потолок вписан числом мимо --measure-form: "
           "поле платежа в фише разойдётся с полем настроек, хотя это одна и "
           "та же строка «подпись + ввод»")

    # Панель формы обнимает содержимое: все её поля заданы шириной в разметке,
    # поэтому растянутая панель дорисовывает белое справа от кнопки («Medic
    # nou» на 2560 — 2152px панели при 643px контролов).
    addf = [b for s, b in rules if _sel(s) == "form.add"]
    res.ok("панель формы обнимает свои поля, а не окно",
           any("width:fit-content" in b for b in addf),
           "form.add тянется во всю ширину: поля заданы числами в разметке, и "
           "остаток панели — просто белое поле справа от последней кнопки")
    res.ok("на узком экране панель по-прежнему переносит поля",
           any("max-width:100%" in b for b in addf),
           "fit-content без max-width:100% на 1366 вылезет за страницу: "
           "содержимое формы журнала шире экрана и обязано переноситься")


def suite_grids(res: Result) -> None:
    """Сетка карточек не оставляет мёртвую колонку, а сетка предметов — своё.

    08-16, поймано съёмкой: страницам отдали ширину окна, и `.medgrid` (врачи)
    осталась на auto-fill — сетка стала заводить шесть колонок по 347px под
    четыре карточки и держать 746px мёртвого столбца справа. Дефект виден
    ТОЛЬКО на большом мониторе: на 1366 карточки переносятся и дыры нет.
    Обратное решение тоже осознанное — у миниатюр и флажков auto-fill верен,
    поэтому список исключений здесь, а не «где-то по месту».
    """
    grids = [(_sel(s), b) for s, b in _rules()
             if "grid-template-columns:repeat(auto-f" in b]
    res.ok("разбор нашёл сетки", len(grids) >= _GRIDS_MIN,
           f"найдено {len(grids)} сеток при ожидаемых {_GRIDS_MIN}+ — разбор "
           "перестал их видеть, и все проверки ниже зеленеют вхолостую")

    bad = sorted({sel for sel, b in grids
                  if "repeat(auto-fill" in b and sel not in _FILL_OK})
    res.ok("сетка карточек делит ряд, а не оставляет пустые колонки", not bad,
           f"auto-fill там, где карточки делят ряд: {bad}. Лишние колонки "
           "держат остаток ширины пустым — на 2560 это мёртвый столбец справа, "
           "и на экране разработчика (1366) его не видно")

    # ⭐ ПОЛЯРНОСТЬ: исключение обязано описывать живую сетку с живым auto-fill
    fills = {sel for sel, b in grids if "repeat(auto-fill" in b}
    stale = [x for x in _FILL_OK if x not in fills]
    res.ok("список исключений не протух", not stale,
           f"в списке имена, которых уже нет среди сеток на auto-fill: {stale}. "
           "Такой список молча разрешает чужой промах — сетку перевели или "
           "переименовали, а исключение осталось")
    src = _py_sources()
    gone = [x for x in _FILL_OK
            if not re.search(rf"class=['\"][^'\"]*\b{x.lstrip('.')}\b", src)]
    res.ok("сетки-исключения ещё живут в разметке", not gone,
           f"классов нет ни в одном class=: {gone} — правило про них ищет "
           "несуществующее имя")


def suite_svc_table(res: Result) -> None:
    """Колонка «Preț» показывает вилку цен, а не первые её символы.

    08-16: модификатор `set-wide` был обоснован тем, что «Preț обрезался даже
    на 2152px», — но колонка держала вшитый в разметку `width:120px`, и вся
    выданная модификатором ширина уходила в «Denumire». То есть обоснование
    обещало то, чего поведение не делало, а сама обрезка жила и на 1366.
    ⚠️ Ширина здесь набрана числом в РАЗМЕТКЕ, поэтому и сторож смотрит в
    разметку: в panel.css этого числа нет и не будет.
    """
    src = (BOT / "app" / "modules" / "settings" / "routes.py").read_text(
        encoding="utf-8")
    m = re.search(r"<th[^>]*style='[^']*width:(\d+)px[^']*'>\s*Preț", src)
    res.ok("колонка «Preț» вообще размечена шириной", bool(m),
           "в таблице услуг не нашлось <th> с шириной для «Preț» — либо "
           "колонку переименовали, либо ширину сняли, и проверка ниже "
           "зеленеет вхолостую")
    if m:
        res.ok("вилка цен помещается в свою колонку", int(m.group(1)) >= _PRET_MIN,
               f"«Preț» шириной {m.group(1)}px при нужных {_PRET_MIN}px: "
               "«1000–1200 MDL» обрежется на любом экране, включая рабочий "
               "1366 — ширина таблицы тут ни при чём")
