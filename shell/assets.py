"""Страницы и значок оболочки — из тех же исходников, что у программы.

Зовёт `build.rs` при каждой сборке (`cargo build`), результат кладёт в
`shell/gen/` (в git не едет). Python здесь — только инструмент СБОРКИ:
готовая оболочка Python не зовёт, заставка вшита в DentPilot.exe.

- `gen/icon.ico` — `scripts/make_icon.py`: значок exe, окна и значка у часов —
  та же фигура, что в шапке программы (`bot/app/brand.py`).
- `gen/ui/splash.html` — заставка с видом нынешней (`bot/app/splash.py`):
  знак, слово, фон, шрифт Inter data-адресами. ⚠️ Цвет темы клиники здесь НЕ
  вписан: его присылает движок словом `hello` уже после запуска оболочки,
  поэтому все оттенки — от `--dp-c` (color-mix), а не готовые хексы.
- `gen/ui/menubar.html` — копия `shell/ui/menubar.html` (страница полосы меню).

⛔ Тексты заставки — румынские, без знаков вне Inter (CLAUDE.md).
"""
from __future__ import annotations

import pathlib
import sys

SHELL = pathlib.Path(__file__).resolve().parent
APP = SHELL.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "scripts"))

from bot.app import brand, splash  # noqa: E402
import make_icon  # noqa: E402

TEAL = brand.hexc(brand.TEAL)


def splash_page() -> str:
    # ⚠️ splash._fonts — тот же набор начертаний, что у нынешней заставки
    # (только латиница); пропал файл шрифта — слово нарисуется системным.
    return f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<!-- Сгенерировано shell/assets.py при сборке. Не править руками. -->
<title>DentPilot</title><style>
{splash._fonts()}
html,body{{margin:0;height:100%;overflow:hidden}}
body{{--dp-c:{TEAL};background:color-mix(in srgb,var(--dp-c) 6%,#fff);
  font-family:Inter,'Segoe UI',sans-serif;color:#30404A;
  display:flex;align-items:center;justify-content:center;-webkit-font-smoothing:antialiased;
  transition:opacity .3s ease;user-select:none;cursor:default}}
body.out{{opacity:0}}
{brand.BACKDROP_CSS}{brand.LOCKUP_CSS}
main{{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;margin-top:-30px}}
.bar{{width:440px;max-width:70vw;height:6px;border-radius:99px;background:rgba(15,35,45,.09);
  margin-top:46px;overflow:hidden}}
.bar i{{display:block;height:100%;width:4%;border-radius:99px;transition:width .6s ease;
  background:linear-gradient(90deg,color-mix(in srgb,var(--dp-c) 60%,#fff),var(--dp-c))}}
.st{{margin-top:16px;font-size:16px;color:#4A5D66;min-height:22px;max-width:640px;
  text-align:center;white-space:pre-line}}
.st.err{{color:#B91C1C;user-select:text;cursor:auto}}
.log{{margin-top:10px;font-size:13px;color:#4A5D66;user-select:text;cursor:auto;
  max-width:640px;text-align:center;word-break:break-all}}
.foot{{position:fixed;z-index:1;bottom:22px;left:0;right:0;text-align:center;font-size:12.5px;color:#6B7C85}}
.foot b{{font-weight:600;color:#30404A}}
</style></head><body>{brand.backdrop_svg()}
<main>{brand.lockup_html()}<div class="bar" id="b"><i id="f"></i></div>
<div class="st" id="s">Se pornește DentPilot…</div><div class="log" id="l" hidden></div></main>
<div class="foot"><b id="v"></b>DentPilot</div>
<script>
/* Оболочка зовёт эти функции через eval: hello -> dpHello, stage -> dpStage,
   ready -> dpDone, fatal -> dpFail. Цвет до первого слова движка — из адреса
   (?c=, последний цвет клиники из shell.json), иначе бирюза. */
var crawl=null;
function dpColor(c){{if(/^#[0-9A-Fa-f]{{6}}$/.test(c||''))document.body.style.setProperty('--dp-c',c)}}
(function(){{var m=/[?&]c=(%23|#)([0-9A-Fa-f]{{6}})/.exec(location.search);if(m)dpColor('#'+m[2])}})();
function dpHello(c,v){{dpColor(c);if(v)document.getElementById('v').textContent='v'+v+' · '}}
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
function dpFail(t,log){{
  if(crawl){{clearInterval(crawl);crawl=null}}
  document.body.classList.remove('out');
  document.getElementById('b').hidden=true;
  var s=document.getElementById('s'); s.textContent=t; s.className='st err';
  var l=document.getElementById('l');
  if(log){{l.textContent='Detalii: '+log; l.hidden=false}} else l.hidden=true;
}}
document.addEventListener('contextmenu',function(e){{e.preventDefault()}});
</script></body></html>"""


def _put(path: pathlib.Path, data: bytes) -> None:
    """Писать, только если содержимое другое: сборка Tauri следит за
    `gen/ui` по времени файлов, и перезапись того же самого пересобирала бы
    оболочку при каждом `cargo build`."""
    try:
        if path.read_bytes() == data:
            return
    except OSError:
        pass
    path.write_bytes(data)


def main(out: pathlib.Path) -> None:
    ui = out / "ui"
    ui.mkdir(parents=True, exist_ok=True)
    tmp = out / "icon.ico.tmp"
    make_icon.main(str(tmp))
    _put(out / "icon.ico", tmp.read_bytes())
    tmp.unlink()
    _put(ui / "splash.html", splash_page().encode("utf-8"))
    _put(ui / "menubar.html", (SHELL / "ui" / "menubar.html").read_bytes())
    print(f"shell assets written: {out}")


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else SHELL / "gen")
