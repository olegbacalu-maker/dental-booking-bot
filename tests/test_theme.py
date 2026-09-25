"""Фирменный вид клиники: стиль, цвет, логотип (08-09).

Три набора отвечают на три разных вопроса:

* `suite_palette` — АРИФМЕТИКА и отказы. Без сервера: цвет из формы доезжает до
  таблицы стилей, поэтому главная проверка здесь — что мусор туда не попадает
  вовсе, а производные оттенки остаются читаемыми на любом выборе.
* `suite_pages` — цвет ДОЕХАЛ: журнал, экран входа, сохранение, права.
* `suite_logo` — загрузка картинки: чем она проверяется и что переживает.

⚠️ Сюда же вынесена сверка `theme.STYLES["modern"]` с `:root` в panel.css.
Стиль «Modern» — это не «ещё один вид», а ИМЯ того, что клиника видит сегодня;
разойдись эти два места, и установка, никогда не открывавшая настройки вида,
поехала бы внешне после обновления.
"""
import json
import pathlib
import re
import subprocess

from harness import BOT, PYTHON, Client, Result, Server

CSS = BOT / "app" / "static" / "css" / "panel.css"

# Заголовки настоящих файлов. Программа смотрит только сигнатуру (разбирать
# картинку нечем — Pillow в сборку не едет), поэтому для проверки достаточно
# правильного начала и любого хвоста: проверяется РОВНО то, что проверяет код.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 128
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>'
EXE = b"MZ\x90\x00\x03" + b"\x00" * 128


def _theme_of(clinic: pathlib.Path) -> dict:
    return json.loads(clinic.read_text(encoding="utf-8")).get("theme") or {}


def _root_block() -> str:
    """Кусок `:root{…}` из panel.css — до первой закрывающей скобки правила."""
    text = CSS.read_text(encoding="utf-8")
    start = text.index(":root{")
    return text[start:text.index("}", start)]


def _css_var(block: str, name: str) -> str:
    m = re.search(re.escape(name) + r":([^;]+);", block)
    return m.group(1).strip() if m else ""


# ---------- 1. арифметика и отказы ----------

_PURE = r"""
import json, sys
sys.path.insert(0, r"{bot}")
from app.core import theme as t
from app import engine as eng

out = {{}}

# мусор в цвете: ни одна из этих строк не имеет права доехать до CSS
out["junk"] = {{s: t.parse_hex(s) for s in [
    "red", "#fff", "#GGGGGG", "", "url(http://x)",
    "#0E9F8A;}}body{{display:none", "#0E9F8A /*", "rgb(1,2,3)"]}}
out["good"] = [t.parse_hex("#0e9f8a"), t.parse_hex("0E9F8A"), t.parse_hex("  #0E9F8A  ")]

# установка без выбора обязана дать РОВНО те оттенки, что вшиты в panel.css
d = t.palette(t.DEFAULT_PRIMARY, "modern")
out["default"] = [d["--teal"], d["--teal-d"], d["--teal-soft"], d["--teal-line"],
                  d["--on-teal"]]

# тёмный оттенок читаем на фоне СВОЕГО стиля — для каждого цвета и стиля
weak = []
for hexv, _name in t.PRESETS:
    for st in t.STYLES:
        pal = t.palette(hexv, st)
        bg = t.parse_hex(t.STYLES[st]["--bg"])
        c = t.contrast(t.parse_hex(pal["--teal-d"]), bg)
        if c < 4.5:
            weak.append([hexv, st, round(c, 2)])
out["weak"] = weak

# текст ШАПКИ сайдбара лежит на --teal-d, и цвет ему даёт --on-teal-d.
# Проверяются и предустановки, и крайние светлые выборы: именно на них
# --on-teal (подобранный под светлый --teal) даёт тёмный текст, который на
# тёмной шапке нечитаем. Порог 4.5 — в шапке мелкий текст, не кнопка.
weak_head = []
for hexv in [h for h, _n in t.PRESETS] + ["#FFFFFF", "#F5D90A", "#A3E635", "#22D3EE"]:
    for st in t.STYLES:
        pal = t.palette(hexv, st)
        c = t.contrast(t.parse_hex(pal["--on-teal-d"]), t.parse_hex(pal["--teal-d"]))
        if c < 4.5:
            weak_head.append([hexv, st, round(c, 2)])
out["weak_head"] = weak_head

# Заголовок экрана входа — имя клиники, и красит его тот же --teal-d. Но лежит
# он не на фоне страницы, а на БЕЛОЙ карточке формы, поэтому меряется отдельно:
# фоны стилей светлее белого всего на 4-8%, запас тонкий, и достаточно однажды
# осветлить фон, чтобы вывод «раз читаем на --bg, то читаем и на белом» отпал.
# Порог 4.5 — это обычный текст. Светлые крайние выборы те же, что у шапки.
weak_h1 = []
for hexv in [h for h, _n in t.PRESETS] + ["#FFFFFF", "#F5D90A", "#A3E635", "#22D3EE"]:
    for st in t.STYLES:
        c = t.contrast(t.parse_hex(t.palette(hexv, st)["--teal-d"]), (255, 255, 255))
        if c < 4.5:
            weak_h1.append([hexv, st, round(c, 2)])
out["weak_h1"] = weak_h1

# наведение обязано ОТЛИЧАТЬСЯ от покоя, иначе кнопка не отзывается на мышь
out["same_hover"] = [h for h, _ in t.PRESETS
                     if t.palette(h, "modern")["--teal-d"] == h]

# светлый фирменный цвет -> тёмный текст на кнопке; тёмный -> белый
out["on_light"] = t.palette("#F5D90A", "modern")["--on-teal"]
out["on_dark"] = t.palette("#111111", "modern")["--on-teal"]

# сигнатуры файлов
out["sniff"] = [t.sniff(b"\x89PNG\r\n\x1a\n123"), t.sniff(b"\xff\xd8\xff\xe0"),
                t.sniff(b'<svg onload=x>'), t.sniff(b"MZ\x90\x00"), t.sniff(b"")]

# битая тема в clinic.json не роняет страницу и не попадает в CSS
eng.CONFIG["theme"] = {{"primary": "#fff}}body{{display:none", "style": "нет такого"}}
css = t.vars_css()
out["fallback_css"] = css
out["fallback"] = t.current()

# сами стили — сверить с :root panel.css ключ в ключ и между собой
out["styles"] = t.STYLES
out["labels"] = sorted(t.STYLE_LABEL)

# меню и шрифт (B5): наборы, подписи, читаемость нейтрального меню в каждом
# стиле (текст интерфейса на основе окна), откат битых значений
out["menus"] = t.MENUS
out["menu_labels"] = sorted(t.MENU_LABEL)
out["fonts"] = t.FONTS
out["font_labels"] = sorted(t.FONT_LABEL)
out["weak_menu"] = [[st, round(t.contrast(t.parse_hex(v["--text"]), t.parse_hex(v["--bg"])), 2)]
                    for st, v in t.STYLES.items()
                    if t.contrast(t.parse_hex(v["--text"]), t.parse_hex(v["--bg"])) < 4.5]
eng.CONFIG["theme"] = {{"menu": "розовое", "font": "Comic Sans"}}
out["fallback2"] = [t.current()["menu"], t.current()["font"]]
out["family"] = t.font_stack()

print("@@" + json.dumps(out))
"""


def suite_palette(res: Result) -> None:
    """Без сервера: разбор цвета, вывод оттенков, сигнатуры файлов."""
    code = _PURE.format(bot=str(BOT))
    p = subprocess.run([str(PYTHON), "-c", code], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(BOT))
    if "@@" not in p.stdout:
        res.failed.append(("набор палитры не запустился", p.stderr[-1500:]))
        return
    out = json.loads(p.stdout.split("@@", 1)[1].strip())

    for s, got in out["junk"].items():
        res.ok(f"мусор в цвете отвергнут: {s!r}", got is None,
               f"разобрался как {got!r} — это уехало бы в таблицу стилей")
    res.check("три записи одного цвета читаются одинаково",
              out["good"], [[14, 159, 138]] * 3)

    teal, dark, soft, line, on = out["default"]
    res.check("цвет по умолчанию — фирменный зелёный", teal, "#0E9F8A")
    res.check("оттенок наведения совпадает с вшитым в panel.css", dark, "#0B7E6D")
    res.check("подложка совпадает с вшитой", soft, "#EAFBF5")
    res.check("кромка совпадает с вшитой", line, "#CCF0E7")
    res.check("текст на фирменной кнопке остался белым", on, "#FFFFFF")

    res.ok("текст шапки читаем на тёмном фирменном при любом выборе",
           not out["weak_head"], f"слабый контраст: {out['weak_head']}")
    res.ok("тёмный оттенок читаем при любом выборе и стиле", not out["weak"],
           f"контраст ниже 4.5: {out['weak']}")
    res.ok("заголовок входа читаем на белой карточке при любом выборе",
           not out["weak_h1"], f"контраст ниже 4.5: {out['weak_h1']}")
    res.ok("наведение отличается от покоя", not out["same_hover"],
           f"совпало у {out['same_hover']}")
    res.check("на светлом фирменном цвете текст тёмный", out["on_light"], "#162033")
    res.check("на тёмном фирменном цвете текст белый", out["on_dark"], "#FFFFFF")

    png, jpg, svg, exe, empty = out["sniff"]
    res.check("PNG опознан", png, "png")
    res.check("JPEG опознан", jpg, "jpg")
    res.ok("SVG не считается картинкой", svg is None,
           "SVG — документ со скриптами, отдавать его как логотип нельзя")
    res.ok("исполняемый файл не считается картинкой", exe is None, f"опознан как {exe!r}")
    res.ok("пустой файл не считается картинкой", empty is None, f"опознан как {empty!r}")

    res.check("битая тема откатывается к фирменной и к стилю по умолчанию",
              [out["fallback"]["primary"], out["fallback"]["style"]],
              ["#0E9F8A", "fluent"])
    res.ok("подстановка в CSS невозможна",
           "display:none" not in out["fallback_css"]
           and "}" not in out["fallback_css"][:-1],
           f"в таблицу стилей уехало: {out['fallback_css'][:200]!r}")

    # Шапка сайдбара залита фирменным цветом, и её текст обязан брать цвет,
    # посчитанный ПОД ЭТОТ фон. Проверка смотрит в сам panel.css: расчёт выше
    # останется верным, даже если правило вернут на --on-teal, и тогда жёлтая
    # клиника получит тёмный текст на тёмной шапке, а тесты промолчат.
    css = CSS.read_text(encoding="utf-8")
    # ⚠️ С 08-17 фирменным залита ВСЯ боковая панель, а не только её шапка:
    # правило то же, элемент другой. Якорь переехал вместе с заливкой — искать
    # `.side .brand` стало бы проверкой того, чего в файле больше нет, и
    # «не нашлось» дало бы красное на верной вёрстке.
    # ⭐ С 25.09 (B5) заливка и текст меню идут через группу `--side-*`: так
    # вариант меню (фирменное / нейтральное) — выбор клиники в настройках, а
    # не правка правил. Проверяются ОБА звена: правило берёт группу, а группа
    # по умолчанию — фирменный тёмный и текст, посчитанный ПОД НЕГО. Одно
    # звено без другого зелено и на сломанном: правило с группой, у которой
    # умолчание белое, красит меню белым у всех, кто ничего не выбирал.
    m = re.search(r"\.side\{([^}]*)\}", css)
    head = m.group(1) if m else ""
    res.ok("боковая панель красится через группу меню",
           "background:var(--side-bg)" in head and "color:var(--side-fg)" in head,
           f"правило: {head!r}")
    block = _root_block()
    res.check("по умолчанию меню фирменное: заливка --teal-d",
              _css_var(block, "--side-bg"), "var(--teal-d)")
    res.check("текст меню берёт цвет, посчитанный под тёмный фон",
              _css_var(block, "--side-fg"), "var(--on-teal-d)")

    # ⛔ Класс ошибок, который открыла заливка (08-17): на фирменном фоне
    # серые тексты интерфейса не видны. --text2/--text3 подобраны под СВЕТЛУЮ
    # подложку и на --teal-d дают около 2:1 — подпись остаётся на экране, но
    # прочитать её нельзя, и заметить это можно только глазами на живой теме.
    # Поэтому внутри панели цвет текста берётся ТОЛЬКО от --on-teal-d
    # (приглушение — прозрачностью поверх него).
    # ⚠️ Полярность: правил `.side …` обязано найтись хотя бы несколько, иначе
    # проверка сторожит пустоту и зеленеет навсегда.
    side_rules = re.findall(r"(\.side[^{}]*)\{([^}]*)\}", css)
    grey = [sel.strip() for sel, body in side_rules
            if re.search(r"color:var\(--text[23]?\)", body)]
    res.ok("в боковой панели нет серых текстов интерфейса",
           not grey and len(side_rules) >= 5,
           f"правил .side найдено {len(side_rules)}; красят серым: {grey} — "
           f"на фирменной заливке такой текст нечитаем, а на экране остаётся")
    # ⚠️ И наоборот (B5): цвет НАПРЯМУЮ от --on-teal-d внутри меню — это
    # текст, который останется белым на нейтральном светлом меню. Внутри
    # .side цвет берётся только от --side-fg; чем он посчитан, решает группа.
    direct = [sel.strip() for sel, body in side_rules
              if re.search(r"var\(--on-teal(-d)?\)", body)]
    res.ok("в боковой панели цвет идёт только через группу меню",
           not direct, f"минуют --side-fg: {direct}")

    # «Modern» = то, что клиника видит сегодня. Сверяем с самим panel.css — по
    # ВСЕМ ключам стиля, а не по избранным: с B5 стиль достаёт до формы
    # (радиусы, высоты, заголовки, отклик), и забытый ключ разошёлся бы молча.
    block = _root_block()
    modern = out["styles"]["modern"]
    drift = [f"{k}: {modern[k]!r} в STYLES, {_css_var(block, k)!r} в :root"
             for k in modern if _css_var(block, k) != modern[k]]
    res.ok("стиль «Modern» повторяет :root в panel.css", not drift,
           f"разошлись: {drift}")
    # ⭐ и с ТРЕТЬЕЙ записью здесь — иначе код сверялся бы сам с собой
    third = [k for k, v in _MODERN.items() if modern.get(k) != v]
    res.ok("«Modern» — те значения, что записаны в тесте", not third,
           f"разошлись с записью теста: {third}")
    # Один набор ключей у всех: предпросмотр кладёт переменные стиля инлайном
    # на <html>, и ключ без пары у соседа пережил бы переключение назад.
    keysets = {st: tuple(sorted(v)) for st, v in out["styles"].items()}
    odd = [st for st, ks in keysets.items() if ks != keysets["modern"]]
    res.ok("все стили задают один и тот же набор переменных", not odd,
           f"набор ключей отличается у: {odd}")
    res.check("стилей четыре, у каждого подпись",
              [sorted(out["styles"]), out["labels"]],
              [["calm", "elegant", "fluent", "modern"]] * 2)

    # Меню и шрифт — те же два инварианта, что у стилей: умолчание повторяет
    # :root (фирменное меню = то, что клиника видит с 08-17; шрифт — вшитый
    # Inter), и у вариантов один набор ключей.
    menus = out["menus"]
    drift = [k for k, v in menus["brand"].items() if _css_var(block, k) != v]
    res.ok("меню по умолчанию повторяет :root в panel.css", not drift,
           f"разошлись: {drift}")
    res.ok("оба варианта меню задают один набор переменных",
           sorted(menus["brand"]) == sorted(menus["neutral"]),
           f"{sorted(menus['brand'])} против {sorted(menus['neutral'])}")
    res.check("вариантов меню два, у каждого подпись",
              [sorted(menus), out["menu_labels"]], [["brand", "neutral"]] * 2)
    res.ok("нейтральное меню читаемо в каждом стиле", not out["weak_menu"],
           f"контраст текста на основе окна ниже 4.5: {out['weak_menu']}")
    res.check("шрифт по умолчанию — вшитый Inter, как в :root",
              _css_var(block, "--font"), out["fonts"]["inter"])
    res.check("шрифтов два, у каждого подпись",
              [sorted(out["fonts"]), out["font_labels"]], [["inter", "system"]] * 2)
    res.check("битые меню и шрифт откатываются к умолчаниям",
              out["fallback2"], ["brand", "inter"])
    res.check("страницам со своей вёрсткой уходит тот же набор семейств",
              out["family"], out["fonts"]["inter"])


# значения стиля modern держим здесь же, рядом с проверкой: тест обязан
# сравнивать panel.css с ТРЕТЬЕЙ записью, иначе он сверяет код сам с собой.
# С B5 ключей у стиля полсотни; здесь — те, что были у стиля с 08-09, плюс по
# одному из каждой новой группы (форма, высота, отклик).
_MODERN = {
    "--r-block": "14px", "--h-ctl": "44px", "--lift": "-1px", "--h1-mark": "block",
    "--bg": "#F6FBF8", "--line": "#E7EDF5", "--line2": "#F1F6FA",
    "--r-card": "18px", "--r-ctl": "12px",
    "--sh": "0 1px 2px rgba(15,23,42,.05),0 6px 18px rgba(15,23,42,.05)",
    "--sh2": "0 2px 4px rgba(15,23,42,.05),0 10px 26px rgba(15,23,42,.07)",
    "--sh3": "0 3px 6px rgba(15,23,42,.06),0 18px 40px rgba(15,23,42,.10)",
}


# ---------- 2. цвет доехал до страниц ----------

def suite_pages(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        anon = Client(s.url)

        page = c.get("/admin").body
        # ⭐ с 25.09 умолчание — Fluent (решение Олега); modern остался базой :root
        res.ok("журнал открывается со стилем по умолчанию — Fluent",
               'data-style="fluent"' in page, "нет data-style=fluent на <html>")
        res.ok("переопределение переменных приехало в шапку",
               "<style>:root{" in page and "--teal:#0E9F8A" in page,
               "нет блока темы")

        head = page.split("<style>:root{", 1)[1].split("</style>", 1)[0]
        painted = [v for v in ("--red", "--green:", "--amber", "--blue")
                   if v in head]
        res.ok("цвета смысла тема не трогает", not painted,
               f"в теме оказались {painted} — «Urgențe» сменили бы цвет")

        hub = c.get("/admin/settings").body
        res.ok("вид клиники есть в хабе настроек",
               "/admin/settings/theme" in hub, "нет плитки")

        # ⚠️ экран собирается из трёх кусков разметки и куска JS: без этой
        # проверки он мог бы отвечать 500, а набор остался бы зелёным —
        # сохранение-то идёт отдельным маршрутом и работало бы
        form = c.get("/admin/settings/theme")
        res.check("экран вида открывается", form.status, 200)
        res.ok("на экране все четыре стиля",
               all(f"value='{k}'" in form.body
                   for k in ("modern", "elegant", "calm", "fluent")),
               "стили не отрисовались")
        res.ok("на экране все шесть цветов",
               all(f"value='{h}'" in form.body for h in
                   ("#0E9F8A", "#2563EB", "#7C3AED", "#0891B2", "#EA580C", "#E11D48")),
               "палитра не отрисовалась")
        res.ok("есть выбор своего цвета",
               "type='color'" in form.body and "value='custom'" in form.body,
               "нет поля своего цвета")

        r = c.post("/admin/settings/save", part="theme", style="calm",
                   primary="#7C3AED", custom="#000000")
        res.check("тема сохраняется", r.msg, "ok_theme")

        page = c.get("/admin").body
        res.ok("выбранный стиль применился", 'data-style="calm"' in page,
               "стиль не доехал")
        res.ok("выбранный цвет применился", "--teal:#7C3AED" in page,
               "цвет не доехал")
        res.ok("полоса браузера перекрасилась вместе со стилем",
               'content="#F2F7F4"' in page, "theme-color остался прежним")

        # меню и шрифт (B5) — тем же путём, что стиль и цвет
        r = c.post("/admin/settings/save", part="theme", style="calm",
                   primary="#7C3AED", custom="#000000", menu="neutral", font="system")
        res.check("меню и шрифт сохраняются", r.msg, "ok_theme")
        head = c.get("/admin").body.split("<style>:root{", 1)[1].split("</style>", 1)[0]
        res.ok("нейтральное меню приехало в шапку", "--side-bg:var(--bg)" in head,
               "меню осталось фирменным")
        res.ok("системный шрифт приехал в шапку",
               "--font:'Segoe UI Variable Text'" in head, "шрифт остался Inter")
        login_f = anon.get("/admin/login").body
        res.ok("экран входа взял тот же шрифт",
               "font-family:'Segoe UI Variable Text'" in login_f
               and "__FAMILY__" not in login_f,
               "у входа своя вёрстка — заполнитель не подставился")
        # ⚠️ Поля не прислали — «не сообщали», а не «сбросить»: старый клиент
        # без групп меню и шрифта не имеет права вернуть их к умолчанию.
        c.post("/admin/settings/save", part="theme", style="calm",
               primary="#7C3AED", custom="")
        res.check("без полей меню и шрифта прежний выбор цел",
                  [_theme_of(s.clinic).get("menu"), _theme_of(s.clinic).get("font")],
                  ["neutral", "system"])
        r = c.post("/admin/settings/save", part="theme", style="calm",
                   primary="#7C3AED", custom="", menu="розовое")
        res.check("незнакомое меню не сохраняется", r.msg, "bad_set")
        r = c.post("/admin/settings/save", part="theme", style="calm",
                   primary="#7C3AED", custom="", font="Comic Sans")
        res.check("незнакомый шрифт не сохраняется", r.msg, "bad_set")
        res.ok("на экране вида есть меню и шрифт",
               all(f"name='{n}' value='{v}'" in c.get("/admin/settings/theme").body
                   for n, v in (("menu", "brand"), ("menu", "neutral"),
                                ("font", "inter"), ("font", "system"))),
               "группы меню и шрифта не отрисовались")

        login = anon.get("/admin/login").body
        res.ok("экран входа перекрашен", "#7C3AED" in login,
               "вход остался зелёным — у него своя вёрстка, и её легко забыть")
        # ⭐ Заголовок входа — имя клиники фирменным цветом, и берёт он ТЁМНЫЙ
        # оттенок (#612DB9 для фиолетового выше). Проверяется значение в самом
        # правиле, а не наличие цвета на странице: чистый акцент на ней есть
        # всегда — им покрашена кнопка. Подмена __ACCENT_D__ на __ACCENT__
        # невидима разработчику: на зелёном по умолчанию она даёт сносные
        # 3.3:1, а на светлом выборе клиники заголовок исчезает — 1.6:1.
        h1 = re.search(r"h1\{[^}]*\}", login)
        color = re.search(r"color:(#[0-9A-Fa-f]{6})", h1.group(0)) if h1 else None
        res.check("заголовок входа взял тёмный оттенок, а не чистый акцент",
                  color.group(1) if color else f"не нашлось: {h1 and h1.group(0)}",
                  "#612DB9")

        cfg = json.loads(s.clinic.read_text(encoding="utf-8"))
        res.ok("сохранение темы не тронуло остальной профиль",
               bool(cfg.get("doctors")) and bool(cfg.get("services"))
               and bool(cfg.get("hours")),
               "секции профиля пропали при сохранении вида")
        res.check("тема легла в clinic.json",
                  [cfg["theme"]["style"], cfg["theme"]["primary"]],
                  ["calm", "#7C3AED"])

        r = c.post("/admin/settings/save", part="theme", style="calm",
                   primary="#fff}body{display:none", custom="")
        res.check("мусорный цвет не сохраняется", r.msg, "bad_set")
        r = c.post("/admin/settings/save", part="theme", style="хакер",
                   primary="#7C3AED", custom="")
        res.check("незнакомый стиль не сохраняется", r.msg, "bad_set")
        res.check("после отказа тема прежняя",
                  _theme_of(s.clinic)["primary"], "#7C3AED")

        r = c.post("/admin/settings/save", part="theme", style="modern",
                   primary="custom", custom="#123456")
        res.check("свой цвет сохраняется", r.msg, "ok_theme")
        res.check("свой цвет лёг в профиль",
                  _theme_of(s.clinic)["primary"], "#123456")

        r = c.get("/admin/settings/theme/palette?c=%23123456&style=modern")
        res.ok("предпросмотр своего цвета считает сервер",
               r.status == 200 and json.loads(r.body)["--teal"] == "#123456",
               f"ответ {r.status}: {r.body[:120]}")
        res.check("мусор в предпросмотре отвергается",
                  c.get("/admin/settings/theme/palette?c=red").status, 400)

        res.ok("без входа экран вида не отдаётся",
               anon.get("/admin/settings/theme").status == 303, "отдался")
        res.ok("без входа тему не сохранить",
               anon.post("/admin/settings/save", part="theme", style="calm",
                         primary="#000000").status == 303, "сохранилось")


# ---------- 3. логотип ----------

def suite_logo(res: Result) -> None:
    with Server() as s:
        c = Client(s.url).login()
        anon = Client(s.url)

        res.check("без логотипа адрес пустой", anon.get("/clinic-logo").status, 404)

        r = c.post_file("/admin/settings/theme/logo", "file", "logo.png", PNG)
        res.check("PNG принимается", r.msg, "ok_logo")

        got = anon.get("/clinic-logo")
        res.ok("логотип отдаётся БЕЗ входа — он нужен экрану входа",
               got.status == 200, f"код {got.status}")
        res.check("отдаётся с типом картинки", got.header("Content-Type"), "image/png")
        res.check("отдаётся ровно то, что загрузили", got.raw, PNG)

        res.ok("логотип виден на экране входа",
               "/clinic-logo" in anon.get("/admin/login").body, "нет на входе")
        res.ok("логотип встал в печатный бланк",
               "clogo" in c.get("/admin/casa").body, "нет в отчёте кассы")

        # ⚠️ главная проверка загрузки: имя файла ничего не значит
        r = c.post_file("/admin/settings/theme/logo", "file", "logo.png", EXE)
        res.check("исполняемый файл под видом PNG отвергнут", r.msg, "bad_logo")
        r = c.post_file("/admin/settings/theme/logo", "file", "logo.png", SVG)
        res.check("SVG под видом PNG отвергнут", r.msg, "bad_logo")
        r = c.post_file("/admin/settings/theme/logo", "file", "big.png",
                        PNG + b"\x00" * (3 * 1024 * 1024))
        res.check("слишком большой файл отвергнут", r.msg, "bad_logo")
        res.check("после отказов прежний логотип цел",
                  anon.get("/clinic-logo").raw, PNG)

        # смена цвета не имеет права уронить логотип: тема пишется секцией
        # целиком, и забытое поле стёрло бы картинку
        c.post("/admin/settings/save", part="theme", style="elegant",
               primary="#EA580C", custom="")
        res.ok("логотип пережил смену цвета",
               anon.get("/clinic-logo").status == 200 and
               _theme_of(s.clinic).get("logo") == "clinic-logo.png",
               f"в профиле {_theme_of(s.clinic)}")

        # --- логотип в шапке журнала (галочка, 08-21) ---
        # выключено по умолчанию: существующая клиника не должна проснуться
        # с новой шапкой; галочка рисуется только при живом логотипе
        res.ok("по умолчанию шапка без логотипа",
               "tb-logo" not in c.get("/admin").body,
               "логотип встал в шапку без галочки")
        res.ok("страница темы предлагает галочку при живом логотипе",
               "logo_topbar" in c.get("/admin/settings/theme").body,
               "галочки на странице нет")
        r = c.post("/admin/settings/save", part="theme", style="elegant",
                   primary="#EA580C", custom="", logo_topbar="1")
        res.check("галочка сохраняется", r.msg, "ok_theme")
        res.ok("логотип встал в шапку журнала",
               "tb-logo" in c.get("/admin").body, "в шапке пусто")

        r = c.post_file("/admin/settings/theme/logo", "file", "logo.jpg", JPG)
        res.check("JPEG принимается", r.msg, "ok_logo")
        res.check("тип отдачи сменился вместе с файлом",
                  anon.get("/clinic-logo").header("Content-Type"), "image/jpeg")
        # тот же класс, что «смена цвета роняла логотип»: маршрут логотипа
        # пишет секцию темы целиком, и забытая галочка снималась бы молча
        res.ok("галочка пережила замену файла логотипа",
               "tb-logo" in c.get("/admin").body,
               "замена файла молча сняла логотип с шапки")
        c.post("/admin/settings/save", part="theme", style="elegant",
               primary="#EA580C", custom="")
        res.ok("снятая галочка убирает логотип из шапки",
               "tb-logo" not in c.get("/admin").body,
               "логотип остался в шапке без галочки")
        c.post("/admin/settings/save", part="theme", style="elegant",
               primary="#EA580C", custom="", logo_topbar="1")
        res.ok("прежний PNG не остался мусором на диске",
               not (s.dir / "clinic-logo.png").exists(),
               "старый файл лежит рядом и не используется")

        r = c.post("/admin/settings/theme/logo", act="del")
        res.check("логотип удаляется", r.msg, "no_logo")
        res.check("после удаления адрес пустой", anon.get("/clinic-logo").status, 404)
        res.ok("удалённый логотип исчез и из шапки при живой галочке",
               "tb-logo" not in c.get("/admin").body,
               "шапка ссылается на пропавший файл")
        res.ok("после удаления цвет и стиль на месте",
               _theme_of(s.clinic)["primary"] == "#EA580C"
               and _theme_of(s.clinic)["style"] == "elegant",
               f"в профиле {_theme_of(s.clinic)}")

        res.ok("без входа логотип не подменить",
               anon.post_file("/admin/settings/theme/logo", "file", "x.png",
                              PNG).status == 303, "подменился")
