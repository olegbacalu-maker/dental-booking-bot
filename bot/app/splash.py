"""Заставка окна программы (05.10.2026, слово Олега: «заставку при открытии
программы, и потом окно с PIN-кодом оставить на том же фоне»).

Окно открывается СРАЗУ, ещё до сервера, с этой страницей внутри; лаунчер
двигает полоску по настоящим этапам запуска (`dpStage`) и, когда журнал
отвечает, уводит окно на адрес программы — в ТОМ ЖЕ окне, и экран входа встаёт
на том же фоне (`layout.standalone`). Раньше окно появлялось только после
подъёма сервера, и несколько секунд после двойного клика не было видно ничего:
клиника кликала ещё раз.

⛔ Сервера ещё нет: ни /static, ни шрифта по ссылке. Поэтому всё — внутри
страницы: шрифт data-адресами, знак и фон — SVG-кодом.
⚠️ Модуль зовёт лаунчер до сборки приложения: импорты — только `brand` и
`paths` (слой предзагрузки, держит `test_structure`).
⚠️ Этапы — настоящие, не нарисованная полоска: что лаунчер делает, то и
пишет. Сколько уходит на каждый, видно в логе (`dentpilot.log`).
"""
from __future__ import annotations

import base64
import re

from . import brand, paths

# Только латиница: на заставке нет ни одной русской буквы, а кириллические
# файлы шрифта — лишние 60 КБ в каждом запуске.
_FONT_FILES = ("inter-latin-ext.woff2", "inter-latin.woff2")


def _fonts() -> str:
    """@font-face программы (static/css/fonts.css) с файлами data-адресами.
    ⚠️ Пропажа файла заставку не роняет: слово нарисуется системным шрифтом."""
    try:
        css = paths.resource("static", "css", "fonts.css").read_text(encoding="utf-8")
    except OSError:
        return ""
    out = []
    for rule in re.findall(r"@font-face\{[^}]*\}", css):
        m = re.search(r"/static/fonts/([\w.-]+\.woff2)", rule)
        if not m or m.group(1) not in _FONT_FILES:
            continue
        try:
            data = paths.resource("static", "fonts", m.group(1)).read_bytes()
        except OSError:
            continue
        uri = "data:font/woff2;base64," + base64.b64encode(data).decode()
        out.append(rule.replace(f"/static/fonts/{m.group(1)}", uri))
    return "\n".join(out)


def page(version: str, primary: str) -> str:
    """Страница заставки. `primary` — цвет темы клиники: фон окрашен им, как у
    экрана входа после неё, иначе на синей клинике была бы вспышка бирюзы."""
    c = primary if re.fullmatch(r"#[0-9A-Fa-f]{6}", primary or "") else brand.hexc(brand.TEAL)
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<title>DentPilot</title><style>/* @font-face — встроены data-адресами: сервера ещё нет */
{_fonts()}
html,body{{margin:0;height:100%;overflow:hidden}}
body{{--dp-c:{c};background:{brand.tint(c, .06)};font-family:Inter,'Segoe UI',sans-serif;color:#30404A;
  display:flex;align-items:center;justify-content:center;-webkit-font-smoothing:antialiased;
  transition:opacity .3s ease;user-select:none}}
body.out{{opacity:0}}
{brand.BACKDROP_CSS}{brand.LOCKUP_CSS}
main{{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;margin-top:-30px}}
.bar{{width:440px;max-width:70vw;height:6px;border-radius:99px;background:rgba(15,35,45,.09);
  margin-top:46px;overflow:hidden}}
.bar i{{display:block;height:100%;width:4%;border-radius:99px;transition:width .6s ease;
  background:linear-gradient(90deg,{brand.tint(c, .6)},{c})}}
.st{{margin-top:16px;font-size:16px;color:#4A5D66;min-height:22px}}
.foot{{position:fixed;z-index:1;bottom:22px;left:0;right:0;text-align:center;font-size:12.5px;color:#6B7C85}}
.foot b{{font-weight:600;color:#30404A}}
</style></head><body>{brand.backdrop_svg()}
<main>{brand.lockup_html()}<div class="bar"><i id="f"></i></div>
<div class="st" id="s">Se pornește DentPilot…</div></main>
<div class="foot"><b>v{version}</b> · DentPilot</div>
<script>
var crawl=null;
/* этап: текст, где полоска, и докуда ей ползти, пока этап идёт (сервер
   поднимается секунды, и стоящая полоска читалась бы как зависание) */
function dpStage(t,p,upto){{
  document.getElementById('s').textContent=t;
  var f=document.getElementById('f'); f.style.width=p+'%';
  if(crawl){{clearInterval(crawl);crawl=null}}
  if(upto){{var w=p;crawl=setInterval(function(){{w+=(upto-w)*.08;f.style.width=w+'%'}},400)}}
}}
function dpDone(){{
  if(crawl)clearInterval(crawl);
  document.getElementById('f').style.width='100%';
  setTimeout(function(){{document.body.classList.add('out')}},150);
}}
</script></body></html>"""
