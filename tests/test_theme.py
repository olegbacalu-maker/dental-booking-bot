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

    res.check("битая тема откатывается к фирменной",
              [out["fallback"]["primary"], out["fallback"]["style"]],
              ["#0E9F8A", "modern"])
    res.ok("подстановка в CSS невозможна",
           "display:none" not in out["fallback_css"]
           and "}" not in out["fallback_css"][:-1],
           f"в таблицу стилей уехало: {out['fallback_css'][:200]!r}")

    # Шапка сайдбара залита фирменным цветом, и её текст обязан брать цвет,
    # посчитанный ПОД ЭТОТ фон. Проверка смотрит в сам panel.css: расчёт выше
    # останется верным, даже если правило вернут на --on-teal, и тогда жёлтая
    # клиника получит тёмный текст на тёмной шапке, а тесты промолчат.
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.side \.brand\{([^}]*)\}", css)
    head = m.group(1) if m else ""
    res.ok("шапка сайдбара красится фирменным цветом",
           "background:var(--teal-d)" in head, f"правило: {head!r}")
    res.ok("текст шапки берёт цвет, посчитанный под тёмный фон",
           "color:var(--on-teal-d)" in head, f"правило: {head!r}")

    # «Modern» = то, что клиника видит сегодня. Сверяем с самим panel.css.
    block = _root_block()
    drift = [k for k in ("--bg", "--line", "--line2", "--r-card", "--r-ctl",
                         "--sh", "--sh2", "--sh3")
             if _css_var(block, k) != _MODERN.get(k)]
    res.ok("стиль «Modern» повторяет :root в panel.css", not drift,
           f"разошлись: {drift}")


# значения стиля modern держим здесь же, рядом с проверкой: тест обязан
# сравнивать panel.css с ТРЕТЬЕЙ записью, иначе он сверяет код сам с собой
_MODERN = {
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
        res.ok("журнал открывается со стилем по умолчанию",
               'data-style="modern"' in page, "нет data-style на <html>")
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
        res.ok("на экране все три стиля",
               all(f"value='{k}'" in form.body for k in ("modern", "elegant", "calm")),
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

        r = c.post_file("/admin/settings/theme/logo", "file", "logo.jpg", JPG)
        res.check("JPEG принимается", r.msg, "ok_logo")
        res.check("тип отдачи сменился вместе с файлом",
                  anon.get("/clinic-logo").header("Content-Type"), "image/jpeg")
        res.ok("прежний PNG не остался мусором на диске",
               not (s.dir / "clinic-logo.png").exists(),
               "старый файл лежит рядом и не используется")

        r = c.post("/admin/settings/theme/logo", act="del")
        res.check("логотип удаляется", r.msg, "no_logo")
        res.check("после удаления адрес пустой", anon.get("/clinic-logo").status, 404)
        res.ok("после удаления цвет и стиль на месте",
               _theme_of(s.clinic)["primary"] == "#EA580C"
               and _theme_of(s.clinic)["style"] == "elegant",
               f"в профиле {_theme_of(s.clinic)}")

        res.ok("без входа логотип не подменить",
               anon.post_file("/admin/settings/theme/logo", "file", "x.png",
                              PNG).status == 303, "подменился")
