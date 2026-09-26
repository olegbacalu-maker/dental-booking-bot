#!/usr/bin/env python3
"""Макет раскладок одонтограммы: три раскладки на ЗУБАХ ДВИЖКА.

Геометрия (коронки, корни, фиссуры, дольки, зоны поверхностей) и палитра
состояний берутся из bot/app/teeth_svg.py и кладутся в страницу как данные;
раскладки и интерактив живут в самой странице. Запуск из любого каталога:

    python frontend/prototypes/odontogram/gen.py            # → index.html (2D)
    python frontend/prototypes/odontogram/gen.py --3d       # → 3d.html (2D + 3D на three.js)
    python frontend/prototypes/odontogram/gen.py --artifact # тело без <html>, для публикации артефактом

⛔ Это прототип (frontend/prototypes/README.md): в сборку не входит, из src/
не импортируется. JS-порт правил отрисовки внутри страницы нужен только для
переключения состояний без сервера — в программе рисунок отдаёт сервер
(docs/dentpilot-2/clinical-chart.md).
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, 'bot'))
from app import teeth_svg as T  # noqa: E402  — без импортов проекта, тянется без fastapi

ARTIFACT = '--artifact' in sys.argv
MODE_3D = '--3d' in sys.argv
_names = {(False, False): 'index.html', (True, False): '3d.html',
          (False, True): 'odontogram.html', (True, True): 'odontogram3d.html'}
OUT = os.path.join(HERE, _names[(MODE_3D, ARTIFACT)])
if '--out' in sys.argv:
    OUT = sys.argv[sys.argv.index('--out') + 1]
# three.js — UMD-сборка r158 с jsDelivr (последняя версия с build/three.min.js;
# артефакт claude.ai пускает скрипты только с cdnjs / jsdelivr / unpkg).
THREE_URL = 'https://cdn.jsdelivr.net/npm/three@0.158.0/build/three.min.js'

UP = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LO = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]


def geom(fdi: int) -> dict:
    cls = T.tooth_class(fdi)
    k = T._width_k(fdi)
    dx = T._MARK_DX.get(cls, 7.0)
    oy = 13.0 if cls in ('incisor_c', 'incisor_l', 'canine') else 19.0
    pos = {'O': (22.0, oy), 'V': (22.0, 28.0), 'L': (22.0, 36.0),
           'M': (22.0 + dx, 27.0), 'D': (22.0 - dx, 27.0)}
    marks = {l: [round(T._sx(x, k), 1), y] for l, (x, y) in pos.items()}
    s = lambda x: T._sx(x, k)  # noqa: E731
    screw, threads = T._implant_screw(fdi)
    carie = (f"M {T._p(s(18), 16)} Q {T._p(s(22), 10, s(26), 16)} "
             f"Q {T._p(s(28), 22, s(22), 25)} Q {T._p(s(16), 22, s(18), 16)} Z")
    obt = (f"M {T._p(s(16.5), 15)} Q {T._p(s(22), 11, s(27.5), 15)} "
           f"Q {T._p(s(29), 21, s(22), 23.5)} Q {T._p(s(15), 21, s(16.5), 15)} Z")
    hw_c = dx + 1.0
    cross = (f"M {T._p(s(22 - hw_c), 15)} L {T._p(s(22 + hw_c), 43)} "
             f"M {T._p(s(22 + hw_c), 15)} L {T._p(s(22 - hw_c), 43)}")
    hw, hd = T.occ_half(fdi)
    occ = dict(outline=T.occ_outline(fdi),
               lobes=[[round(v, 2) for v in l] for l in T.occ_lobes(fdi)],
               zones={l: [round(v, 2) for v in z] for l, z in T.occ_zones(fdi).items()},
               fiss=T._occ_fissures(fdi), hw=round(hw, 2), hd=round(hd, 2))
    return dict(cls=cls, up=T.is_upper(fdi), mir=T.mirrored(fdi), k=round(k, 3),
                crown=T.crown_path(fdi), roots=T.root_paths(fdi), fiss=T._fissures(fdi),
                marks=marks, mr=round(3.1 * k, 2), hr=round(5.6 * k, 2),
                screw=screw, threads=threads, carie=carie, obt=obt, cross=cross, occ=occ)


G = {str(n): geom(n) for n in UP + LO}
P = dict(COLORS=T.COLORS, FILLS=T.FILLS, MARK_FILL=T.MARK_FILL, MARK_COLORS=T.MARK_COLORS,
         ENAMEL=list(T.ENAMEL), CROWN_GOLD=list(T.CROWN_GOLD), ROOT_FILL=T.ROOT_FILL,
         STATE_RO=T.STATE_RO, MARK_RO=T.MARK_RO)

clips = ''.join(f"<clipPath id='clip-{n}'><path d='{G[str(n)]['occ']['outline']}'/></clipPath>" for n in UP + LO)
DEFS = ("<svg width='0' height='0' style='position:absolute' aria-hidden='true' focusable='false'><defs>"
        "<linearGradient id='g-enamel' x1='.25' y1='0' x2='.75' y2='1'>"
        f"<stop offset='0' stop-color='{T.ENAMEL[0]}'/><stop offset='.52' stop-color='{T.ENAMEL[1]}'/>"
        f"<stop offset='1' stop-color='{T.ENAMEL[2]}'/></linearGradient>"
        "<linearGradient id='g-gold' x1='.25' y1='0' x2='.75' y2='1'>"
        f"<stop offset='0' stop-color='{T.CROWN_GOLD[0]}'/><stop offset='.52' stop-color='{T.CROWN_GOLD[1]}'/>"
        f"<stop offset='1' stop-color='{T.CROWN_GOLD[2]}'/></linearGradient>"
        f"{clips}</defs></svg>")

CSS3D = r'''
/* ---- 3D ---- */
.col{display:grid;gap:16px;min-width:0}
.stage-head{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;justify-content:space-between;margin-bottom:10px}
.seg{display:inline-flex;flex-wrap:wrap;gap:2px;background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:3px}
.seg button{border:none;background:none;border-radius:7px;padding:5px 10px;cursor:pointer;color:var(--text-2);font-size:13px;font-weight:500}
.seg button:hover{background:var(--line-2)}
.seg button[aria-pressed="true"]{background:var(--accent);color:var(--on-accent);font-weight:600}
.seg button:focus-visible,.tog:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.tog{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel);cursor:pointer;font-size:13px;color:var(--text-2)}
.tog:hover{border-color:var(--accent)}
.tog[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-soft);color:var(--accent);font-weight:600}
.stage{position:relative;height:520px;border-radius:12px;overflow:hidden;contain:paint;border:1px solid var(--line);
  background:linear-gradient(var(--stage-top),var(--stage-bottom))}
@media (max-width:880px){.stage{height:400px}}
.stage canvas{display:block;width:100%;height:100%;outline:none;touch-action:none;cursor:grab}
.stage canvas.pick{cursor:pointer}.stage canvas.drag{cursor:grabbing}
.stage .msg{position:absolute;inset:0;display:grid;place-items:center;padding:24px;text-align:center;color:var(--text-3);font-size:13px}
.stage .tip3{position:absolute;left:12px;bottom:10px;font-size:11.5px;color:var(--text-3);pointer-events:none}
.stage .hover3{position:absolute;left:12px;top:10px;font-size:12.5px;font-weight:600;color:var(--text-2);pointer-events:none;min-height:18px}
.stage .jaw3{position:absolute;right:12px;font-size:10px;font-weight:700;letter-spacing:.14em;color:var(--text-3);pointer-events:none}
.stage .jaw3.up{top:10px}.stage .jaw3.lo{bottom:10px}
'''

HEAD = r'''<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>
:root{
  --bg:#f4f6f8;--panel:#ffffff;--line:#dde3e8;--line-2:#edf1f4;--text:#17242c;--text-2:#4a5a64;--text-3:#66747e;
  --accent:#0f7b8a;--accent-soft:#e4f2f4;--on-accent:#ffffff;--band:#eef2f5;--cell:#ffffff;--gold-text:#B45309;--stage-top:#ffffff;--stage-bottom:#e4eaef;
  --t-line:#64748B;--t-soft:#94A3B8;--t-ghost:#CBD5E1;--f-extras:#E2E8F0;--f-carie:#FEF2F2;--f-obturatie:#EFF6FF;--f-coroana:#FFF7ED;--f-implant:#F5F3FF;
  --shadow:0 1px 2px rgba(23,36,44,.05),0 10px 28px rgba(23,36,44,.06);
  --r-card:14px;--r-ctl:9px;--r-sm:6px;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){color-scheme:dark;
    --bg:#10181c;--panel:#17202a;--line:#2a363d;--line-2:#212c34;--text:#eef3f5;--text-2:#b3c2ca;--text-3:#93a5ae;
    --accent:#35a7b8;--accent-soft:#14333a;--on-accent:#04181c;--band:#1e2a31;--cell:#1b262e;--gold-text:#F5B453;--stage-top:#1b2429;--stage-bottom:#121a1e;
    --t-line:#9AA8BA;--t-soft:#7C8AA0;--t-ghost:#4B5A6B;--f-extras:#3A4756;--f-carie:#3A2224;--f-obturatie:#1E2C44;--f-coroana:#3A2C14;--f-implant:#2B2547;
    --shadow:none}
}
:root[data-theme="dark"]{color-scheme:dark;
  --bg:#10181c;--panel:#17202a;--line:#2a363d;--line-2:#212c34;--text:#eef3f5;--text-2:#b3c2ca;--text-3:#93a5ae;
  --accent:#35a7b8;--accent-soft:#14333a;--on-accent:#04181c;--band:#1e2a31;--cell:#1b262e;--gold-text:#F5B453;--stage-top:#1b2429;--stage-bottom:#121a1e;
  --t-line:#9AA8BA;--t-soft:#7C8AA0;--t-ghost:#4B5A6B;--f-extras:#3A4756;--f-carie:#3A2224;--f-obturatie:#1E2C44;--f-coroana:#3A2C14;--f-implant:#2B2547;
  --shadow:none}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,"Segoe UI",Roboto,sans-serif;font-size:14px;line-height:1.5;
  padding-block:20px 48px;padding-inline:16px;-webkit-font-smoothing:antialiased}
h1,h2,h3{margin:0;text-wrap:balance}
button{font:inherit;color:inherit}
.top{max-width:1180px;margin:0 auto 14px;display:flex;flex-wrap:wrap;gap:12px 24px;align-items:flex-end;justify-content:space-between}
.top h1{font-size:22px;font-weight:700;letter-spacing:-.01em;line-height:1.2}
.top .sub{margin:4px 0 0;color:var(--text-2);max-width:60ch}
.tabs{display:flex;gap:4px;background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:4px;flex-wrap:wrap}
.tabs button{font-weight:500;color:var(--text-2);background:none;border:none;border-radius:8px;padding:7px 12px;cursor:pointer}
.tabs button:hover{background:var(--line-2)}
.tabs button[aria-selected="true"]{background:var(--accent);color:var(--on-accent);font-weight:600}
.tabs button:focus-visible,.btn:focus-visible,.pill:focus-visible,.chip:focus-visible,.tb:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wrap{max-width:1180px;margin:0 auto;display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;align-items:start}
@media (max-width:980px){.wrap{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);padding:14px 16px;box-shadow:var(--shadow)}
.chart-head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;justify-content:space-between;margin-bottom:6px}
.pt{display:inline-flex;align-items:center;gap:8px;font-weight:600}
.pt .dot{width:8px;height:8px;border-radius:50%;background:var(--accent)}
.pt small{font-weight:500;color:var(--text-3)}
.sum{display:flex;flex-wrap:wrap;gap:6px;font-size:12px;color:var(--text-2);font-variant-numeric:tabular-nums}
.sum span{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border:1px solid var(--line);border-radius:999px;background:var(--bg)}
.sum i{width:8px;height:8px;border-radius:2px;display:inline-block}
.btn{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-ctl);padding:6px 12px;cursor:pointer;font-weight:500;color:var(--text-2)}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.chart{overflow-x:auto;padding:6px 0 2px}
.archsvg{display:block;width:100%;max-width:560px;height:auto;margin:0 auto;overflow:visible}
.archsvg .num{font-size:11.5px;font-weight:600;fill:var(--text-3);font-family:inherit;cursor:pointer}
.archsvg .num.sel{fill:var(--accent)}
.archsvg .jaw{font-size:10px;font-weight:700;letter-spacing:.16em;fill:var(--text-3);text-anchor:middle}
.archsvg .side{font-size:10px;font-weight:600;letter-spacing:.08em;fill:var(--text-3);text-transform:uppercase}
.archsvg .brl{font-size:10px;font-weight:600;fill:var(--gold-text)}
.at{cursor:pointer}.at:focus{outline:none}.at:focus-visible .selbox,.at:focus-visible .focusbox{stroke:var(--accent);stroke-width:1.6}
.selbox{fill:var(--accent-soft);stroke:var(--accent);stroke-width:1.5}
.focusbox{fill:none;stroke:none}
.schema{display:block;width:100%;min-width:760px;height:auto}
.schema .num{font-size:11.5px;font-weight:600;fill:var(--text-3);font-family:inherit;text-anchor:middle;cursor:pointer}
.schema .num.sel{fill:var(--accent)}
.schema .jaw{font-size:9.5px;font-weight:700;letter-spacing:.16em;fill:var(--text-3);text-anchor:middle}
.schema .brl{font-size:9.5px;font-weight:600;fill:var(--gold-text);text-anchor:middle}
.st{cursor:pointer}.st:focus{outline:none}
.st .zone{stroke-width:1;stroke-linejoin:round}
.st .box{fill:none;stroke-width:1.6}
.st.sel .box{stroke:var(--accent);stroke-width:2.4}
.st:focus-visible .box{stroke:var(--accent);stroke-width:2.4}
.pan{display:grid;gap:22px;min-width:760px}
.pan h3{margin:0 0 4px;font-size:11px;font-weight:600;color:var(--text-3);letter-spacing:.08em;text-transform:uppercase}
.arch{position:relative;display:grid;grid-template-columns:repeat(16,minmax(0,1fr));gap:8px;align-items:end}
.arch:not(.lo){grid-template-rows:16px auto}.arch.lo{grid-template-rows:auto 16px;align-items:start}
.arch .tb{grid-row:2}.arch.lo .tb{grid-row:1}.arch .br{grid-row:1}.arch.lo .br{grid-row:2}
.arch.occ{align-items:center}.arch.occ:not(.lo){padding-top:24px}.arch.occ.lo{padding-bottom:24px}
.tb{background:none;border:none;padding:4px 2px;cursor:pointer;border-radius:var(--r-ctl);display:flex;flex-direction:column;align-items:center;gap:2px;
  transform:translateY(var(--arc,0px));min-width:0}
.tb .tsvg{display:block;width:100%;max-width:54px;height:auto;overflow:visible}
.tb .num{font-size:12px;font-weight:600;color:var(--text-3);font-variant-numeric:tabular-nums}
.tb:hover{background:var(--accent-soft)}.tb.sel{background:var(--accent-soft);box-shadow:inset 0 0 0 2px var(--accent)}.tb.sel .num{color:var(--accent)}
.mid{display:flex;flex-direction:column;align-items:center;margin:2px 0}
.mid i{display:block;width:100%;height:1px;background:var(--line);margin:4px 0}
.mid b{font-size:10px;font-weight:700;letter-spacing:.7px;color:var(--text-3);text-transform:uppercase}
.br{position:relative;height:12px;border:2px solid #D97706;border-bottom:none;border-radius:8px 8px 0 0;align-self:end;margin:0 8px}
.br.lo{border:2px solid #D97706;border-top:none;border-radius:0 0 8px 8px;align-self:start}
.br span{position:absolute;left:50%;transform:translateX(-50%);top:-15px;font-size:10px;font-weight:600;color:var(--gold-text);white-space:nowrap;background:var(--panel);padding:0 4px}
.br.lo span{top:auto;bottom:-15px}
.hint{margin:10px 0 0;font-size:12px;color:var(--text-3)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:12px;color:var(--text-2)}
.legend .lg{display:inline-flex;align-items:center;gap:6px}
.legend .lg svg{display:block;overflow:visible}
.legend .sep{width:1px;height:18px;background:var(--line)}
.insp{position:sticky;top:12px}
@media (max-width:980px){.insp{position:static}}
.ih{display:flex;align-items:center;gap:12px;padding-bottom:12px;border-bottom:1px solid var(--line);margin-bottom:12px}
.ih .badge{width:44px;height:44px;border-radius:var(--r-ctl);background:var(--accent);color:var(--on-accent);display:grid;place-items:center;font-size:18px;font-weight:700;flex:none;font-variant-numeric:tabular-nums}
.ih b{display:block;font-size:15px;font-weight:600;line-height:1.3}
.ih small{display:block;color:var(--text-3);font-size:12px}
.row{display:grid;gap:6px;margin-bottom:12px}
.lbl{font-size:11.5px;font-weight:500;color:var(--text-3);letter-spacing:.04em;text-transform:uppercase}
.pills{display:flex;flex-wrap:wrap;gap:6px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel);cursor:pointer;font-size:13px;color:var(--text-2)}
.pill i{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
.pill:hover{border-color:var(--accent)}
.pill.on{border-color:var(--accent);background:var(--accent-soft);color:var(--accent);font-weight:600}
.chips{display:grid;gap:6px}
.chip{display:flex;align-items:center;gap:10px;width:100%;padding:5px 10px 5px 6px;border:1px solid var(--line);border-radius:var(--r-ctl);background:var(--panel);cursor:pointer;text-align:left;font-size:13px;color:var(--text-2)}
.chip .code{width:22px;height:22px;border-radius:var(--r-sm);background:var(--bg);display:grid;place-items:center;font-weight:600;font-size:12px;color:var(--text);flex:none}
.chip .cl{flex:1}
.chip .cs{font-size:12px;font-weight:600}
.chip:hover{border-color:var(--accent)}
.chip.on{border-color:var(--accent);background:var(--accent-soft);color:var(--accent);font-weight:600}
.chip.on .code{background:var(--accent);color:var(--on-accent)}
.chip:disabled{opacity:.45;cursor:not-allowed}
.note{margin:0;font-size:12px;color:var(--text-3);line-height:1.5}
.brinfo{margin:0;font-size:13px;color:var(--text-2)}
.notes{max-width:1180px;margin:22px auto 0;color:var(--text-2)}
.notes h2{font-size:13px;font-weight:600;color:var(--text-3);letter-spacing:.06em;text-transform:uppercase;margin-bottom:8px}
.notes-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px 24px}
.notes p{margin:0;font-size:13px;line-height:1.55;max-width:62ch}
.notes b{color:var(--text)}
.notes code{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:12px;background:var(--line-2);padding:1px 5px;border-radius:4px}
@keyframes flash2d{0%{filter:brightness(1)}35%{filter:brightness(1.45) saturate(1.25)}100%{filter:brightness(1)}}
.flash{animation:flash2d .55s ease-out}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
__CSS3D__</style>
'''

BODY = r'''
<header class="top">
  <div>
    <h1>Odontogramă</h1>
    <p class="sub">Три готовых макета одонтограммы на зубах движка DentPilot. Нажмите на зуб или на поверхность: состояние меняется во всех трёх макетах.</p>
  </div>
  <div class="tabs" role="tablist" aria-label="Макет">
    <button type="button" role="tab" id="tab-arcada" data-tpl="arcada" aria-selected="true">Анатомическая дуга</button>
    <button type="button" role="tab" id="tab-schema" data-tpl="schema" aria-selected="false">Схема MODVL</button>
    <button type="button" role="tab" id="tab-panorama" data-tpl="panorama" aria-selected="false">Панорама (как сейчас)</button>
  </div>
</header>
<main class="wrap">
  <section class="card">
    <div class="chart-head">
      <div class="pt"><span class="dot"></span>Marian D. <small>· exemplu · 26.09.2026</small></div>
      <div class="sum" id="sum" aria-live="polite"></div>
      <button type="button" class="btn" id="reset">Resetează exemplul</button>
    </div>
    <div id="chart" class="chart"></div>
    <div class="legend" id="legend"></div>
  </section>
  <aside class="card insp" id="insp" aria-live="polite"></aside>
</main>
<section class="notes">
  <h2>Откуда что взято</h2>
  <div class="notes-grid">
    <p><b>Зубы.</b> Контуры коронок, корней, фиссур, долек и зон поверхностей — те же, что рисует движок DentPilot (<code>teeth_svg.py</code>), перенесены на страницу как данные вместе с палитрой состояний. Новых форм зуба здесь нет; в программе геометрию по‑прежнему отдаёт сервер.</p>
    <p><b>Макеты.</b> Три стандартные раскладки: анатомическая дуга (как в Dentrix, Curve, Dentally и в открытой библиотеке react‑advanced‑odontogram), схема поверхностей MODVL пятизонным квадратом (немецкий «Zahnschema», латиноамериканская odontograma) и нынешняя панорама двумя рядами.</p>
    <p><b>Не нарисовано.</b> Молочный ряд, пародонтограмма, история и заметки зуба. Это макет для сравнения, а не экран программы: правки здесь никуда не сохраняются, «Resetează exemplul» возвращает исходный пример.</p>
  </div>
</section>
'''

BODY3D = r'''
<header class="top">
  <div>
    <h1>Odontogramă 2D/3D</h1>
    <p class="sub">Обе челюсти в 3D и та же карта в 2D на одних данных. Клик по поверхности зуба в любом из видов меняет её состояние; вращение мышью, зум колёсиком.</p>
  </div>
  <div class="pt"><span class="dot"></span>Marian D. <small>· exemplu · 26.09.2026</small></div>
</header>
<main class="wrap">
  <div class="col">
    <section class="card">
      <div class="stage-head">
        <div class="seg" role="group" aria-label="Vedere 3D" id="views">
          <button type="button" data-view="frontal" aria-pressed="true">Frontal</button>
          <button type="button" data-view="sus" aria-pressed="false">Ocluzal sus</button>
          <button type="button" data-view="jos" aria-pressed="false">Ocluzal jos</button>
          <button type="button" data-view="dreapta" aria-pressed="false">Dreapta</button>
          <button type="button" data-view="stanga" aria-pressed="false">Stânga</button>
        </div>
        <div class="pills" id="togs">
          <button type="button" class="tog" data-tog="xray" aria-pressed="false">Rădăcini</button>
          <button type="button" class="tog" data-tog="labels" aria-pressed="true">Numere</button>
          <button type="button" class="tog" data-tog="upper" aria-pressed="true">Maxilar</button>
          <button type="button" class="tog" data-tog="lower" aria-pressed="true">Mandibular</button>
          <button type="button" class="tog" data-tog="closed" aria-pressed="false">Ocluzie</button>
          <button type="button" class="tog" data-tog="rotate" aria-pressed="false">Rotire</button>
        </div>
      </div>
      <div class="stage" id="stage">
        <div class="hover3" id="hover3"></div>
        <div class="jaw3 up">MAXILAR</div><div class="jaw3 lo">MANDIBULAR</div>
        <div class="tip3">Trage: rotește · rotița: zoom · clic pe suprafață: — → carie → obturație → — · starea din inspector se animează în 3D</div>
      </div>
    </section>
    <section class="card">
      <div class="chart-head">
        <div class="tabs" role="tablist" aria-label="Макет 2D">
          <button type="button" role="tab" id="tab-arcada" data-tpl="arcada" aria-selected="true">Дуга</button>
          <button type="button" role="tab" id="tab-schema" data-tpl="schema" aria-selected="false">Схема MODVL</button>
          <button type="button" role="tab" id="tab-panorama" data-tpl="panorama" aria-selected="false">Панорама</button>
        </div>
        <div class="sum" id="sum" aria-live="polite"></div>
        <button type="button" class="btn" id="reset">Resetează exemplul</button>
      </div>
      <div id="chart" class="chart"></div>
      <div class="legend" id="legend"></div>
    </section>
  </div>
  <aside class="card insp" id="insp" aria-live="polite"></aside>
</main>
<section class="notes">
  <h2>Откуда что взято</h2>
  <div class="notes-grid">
    <p><b>3D‑зубы.</b> 32 процедурных зуба: мезио‑дистальная и вестибуло‑язычная ширина, число корней и раскладка по дуге — из движка DentPilot (<code>teeth_svg.py</code>); высота коронки и длина корней — по классам зуба; форма коронки, бугры и корни — по методу прототипа dental3d (суперэллипс, сплайн профиля, гауссианы бугров). Ни одной сторонней модели.</p>
    <p><b>Цвета в 3D те же, что в 2D.</b> Поверхность с кариесом краснеет, с пломбой синеет, коронка золотая, имплант — титановый винт с фиолетовым кольцом, удалённый зуб — лунка в десне, отсутствующий — полупрозрачный призрак, «în tratament» — зелёное кольцо у шейки. «Rădăcini» делает десну прозрачной.</p>
    <p><b>Ограничения.</b> three.js грузится с cdn.jsdelivr.net, при первом открытии нужен интернет. Молочного ряда, пародонта, истории и заметок нет; правки не сохраняются. В программу 3D поедет через прототип dental3d и контракт клинического модуля, а не этой страницей.</p>
  </div>
</section>
'''

JS3D = r'''
/* ================= 3D: обе челюсти, three.js (UMD r158, глобал THREE) ================= */
var R3=null, hover3=null;
const SURF3=['O','V','L','M','D'];
const MM=0.2893;                       // мм в единице движка: моляр 36.3 ед. = 10.5 мм
const CROWN_H={incisor_c:[10.5,9.0],incisor_l:[9.0,9.5],canine:[10.0,11.0],premolar:[8.5,8.0],molar:[7.5,7.5]};   // [верх, низ]
const ROOT_L={incisor_c:[11.7,11.2],incisor_l:[11.7,11.7],canine:[14.5,14],premolar:[12.5,12.5],molar:[11.2,12.5]};   // ×0.9 от средних: корни остаются внутри гребня десны
const SQUARE={incisor_c:2.4,incisor_l:2.4,canine:2.2,premolar:2.6,molar:3.2};
const PROF={molar:[[0,.80,.80],[.16,.92,.92],[.34,1,1],[.62,.99,.99],[.86,.95,.95],[1,.90,.90]],
  premolar:[[0,.80,.80],[.16,.92,.92],[.34,1,1],[.62,.98,.98],[.86,.92,.92],[1,.86,.86]],
  canine:[[0,.80,.85],[.2,.95,1],[.45,1,.95],[.7,.9,.7],[.88,.65,.42],[1,.30,.16]],
  incisor:[[0,.78,.85],[.2,.9,1],[.45,1,.9],[.7,1.02,.62],[.88,1,.36],[1,.96,.14]]};
const ENAMEL3=0xe9e1d1, CERAMIC3=0xf4f0e8, DENTIN3=0xd6c2a4, GOLD3=0xF2A93B, GUM3=0xECB3AE, SOCKET3=0x8b949e, TITAN3=0xb9bec6, GLOW3=0x0b6b7a;
const profOf=cls=>PROF[cls.startsWith('incisor')?'incisor':cls];
const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
const smooth=(e0,e1,x)=>{const t=clamp((x-e0)/(e1-e0),0,1);return t*t*(3-2*t);};
function profAt(prof,t){ const n=prof.length; let i=1; while(i<n-1&&t>prof[i][0]) i++; const p1=prof[i-1],p2=prof[i],p0=prof[i-2]||p1,p3=prof[i+1]||p2;
  const span=p2[0]-p1[0], u=span>0?clamp((t-p1[0])/span,0,1):0, u2=u*u, u3=u2*u;
  const cr=k=>0.5*((2*p1[k])+(-p0[k]+p2[k])*u+(2*p0[k]-5*p1[k]+4*p2[k]-p3[k])*u2+(-p0[k]+3*p1[k]-3*p2[k]+p3[k])*u3); return [cr(1),cr(2)]; }
function crossSec(th,a,b,sq){ const c=Math.cos(th),s=Math.sin(th),p=2/sq; return [Math.sign(c)*Math.pow(Math.abs(c),p)*a, Math.sign(s)*Math.pow(Math.abs(s),p)*b]; }
/* рельеф жевательной поверхности в долях полуосей (fx: мезиально = -1 … дистально = +1; fz: язычно -1 … щёчно +1), мм */
function reliefFn(cls,upper){
  const gs=(fx,fz,cx,cz,s)=>Math.exp(-0.5*(((fx-cx)/s)**2+((fz-cz)/s)**2));
  if(cls==='molar'){ const cusps=upper?[[-.48,.51,2.0],[.51,.49,1.78],[-.5,-.53,1.88],[.53,-.45,1.38]]:[[-.5,.5,1.9],[.12,.56,1.62],[.66,.36,1.3],[-.45,-.5,1.9],[.42,-.5,1.62]];
    return (fx,fz)=>{ let h=0; for(const [cx,cz,a] of cusps) h+=a*gs(fx,fz,cx,cz,.34); h-=1.15*gs(fx,fz,.02,0,.24);
      h-=.7*Math.exp(-0.5*(fx/.1)**2)*clamp((fz+.05)/.35,0,1); h-=.55*Math.exp(-0.5*((fx-.35)/.1)**2)*clamp((-fz-.05)/.35,0,1); return Math.max(0,h); }; }
  if(cls==='premolar'){ const lh=upper?1.6:1.0; return (fx,fz)=>{ let h=2.1*gs(fx,fz,0,.46,.42)+lh*gs(fx,fz,0,-.46,.4); h-=.7*Math.exp(-0.5*(fz/.16)**2)*clamp(1-Math.abs(fx)/.75,0,1); return Math.max(0,h); }; }
  if(cls==='canine') return (fx,fz)=>1.3*gs(fx,fz,-.1,0,.45);
  return ()=>0;
}
/* Коронка: стенка (θ × высота) + площадка (кольца к центру), пять групп треугольников = пять материалов.
   Канон прототипа dental3d: +x дистально, -x мезиально, +z щёчно, +y окклюзионно, шейка y=0. */
function buildCrown(hmd,hbl,H,cls,upper){
  const TH=64, ROWS=22, RINGS=10, sq=SQUARE[cls], prof=profOf(cls), relief=reliefFn(cls,upper), rimK=(cls==='molar'||cls==='premolar')?.52:0;
  const [topMD,topBL]=profAt(prof,1); const pos=[];
  const ridge=th=>{ const [x,z]=crossSec(th,hmd*topMD,hbl*topBL,sq); return relief(x/hmd,z/hbl)*rimK; };
  for(let r=0;r<=ROWS;r++){ const t=r/ROWS, [wm,wb]=profAt(prof,t), k=smooth(.72,1,t); for(let j=0;j<TH;j++){ const th=2*Math.PI*j/TH; const [x,z]=crossSec(th,hmd*wm,hbl*wb,sq); pos.push(x,t*H+ridge(th)*k,z); } }
  const ringStart=[ROWS*TH];
  for(let k=1;k<=RINGS;k++){ const s=1-k/RINGS; ringStart.push(pos.length/3); if(k===RINGS){ pos.push(0,H+relief(0,0),0); break; }
    for(let j=0;j<TH;j++){ const th=2*Math.PI*j/TH; const [rx,rz]=crossSec(th,hmd*topMD,hbl*topBL,sq); const x=rx*s,z=rz*s, fade=1-smooth(.7,1,s); pos.push(x,H+relief(x/hmd,z/hbl)*fade+ridge(th)*(1-fade),z); } }
  const B={O:[],V:[],L:[],M:[],D:[]}, step=360/TH;
  const sector=deg=>{ let d=deg%360; if(d<-30)d+=360; if(d>=330)d-=360; if(d>=-30&&d<30) return 'D'; if(d<150) return 'V'; if(d<210) return 'M'; return 'L'; };
  for(let r=0;r<ROWS;r++) for(let j=0;j<TH;j++){ const jn=(j+1)%TH,a=r*TH+j,b=r*TH+jn,c=(r+1)*TH+jn,d=(r+1)*TH+j; B[sector((j+.5)*step)].push(a,c,b,a,d,c); }
  for(let k=0;k<RINGS;k++){ const o=ringStart[k],i=ringStart[k+1]; if(k===RINGS-1){ for(let j=0;j<TH;j++){ const jn=(j+1)%TH; B.O.push(o+j,i,o+jn); } } else for(let j=0;j<TH;j++){ const jn=(j+1)%TH; B.O.push(o+j,i+j,i+jn,o+j,i+jn,o+jn); } }
  const geo=new THREE.BufferGeometry(), idx=[]; SURF3.forEach((L,slot)=>{ geo.addGroup(idx.length,B[L].length,slot); for(const v of B[L]) idx.push(v); });
  geo.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); geo.setIndex(idx); geo.computeVertexNormals(); geo.computeBoundingSphere(); return geo;
}
function rootSpecs(cls,n,hmd,hbl,len){
  if(n===3) return [{x:-.34*hmd,z:.31*hbl,rx:.37*hmd,rz:.34*hbl,len:len*.95,ox:-.29*hmd,oz:.25*hbl},{x:.36*hmd,z:.32*hbl,rx:.35*hmd,rz:.32*hbl,len:len*.9,ox:.31*hmd,oz:.22*hbl},{x:.02*hmd,z:-.36*hbl,rx:.42*hmd,rz:.38*hbl,len:len*1.02,ox:.02*hmd,oz:-.44*hbl}];
  if(n===2){ if(cls==='premolar') return [{x:0,z:.42*hbl,rx:.55*hmd,rz:.36*hbl,len,ox:0,oz:.2*hbl},{x:0,z:-.42*hbl,rx:.55*hmd,rz:.36*hbl,len:len*.96,ox:0,oz:-.2*hbl}];
    return [{x:-.45*hmd,z:0,rx:.3*hmd,rz:.72*hbl,len,ox:-.1*hmd,oz:0},{x:.45*hmd,z:0,rx:.3*hmd,rz:.7*hbl,len:len*.95,ox:.25*hmd,oz:0}]; }
  return [{x:0,z:0,rx:.72*hmd,rz:.72*hbl,len,ox:.08*hmd,oz:0}];
}
/* Шеечный переход + корни (эллиптические конусы, слегка расходятся и наклонены дистально). */
function buildRoots(hmd,hbl,cls,nRoots,len){
  const TH=48, COL=2.4, CR=6, sq=SQUARE[cls], [wm0,wb0]=profAt(profOf(cls),0), pos=[], idx=[];
  for(let r=0;r<=CR;r++){ const t=r/CR, w=1-.14*smooth(0,1,t); for(let j=0;j<TH;j++){ const th=2*Math.PI*j/TH; const [x,z]=crossSec(th,hmd*wm0*w,hbl*wb0*w,sq); pos.push(x,-COL*t,z); } }
  for(let r=0;r<CR;r++) for(let j=0;j<TH;j++){ const jn=(j+1)%TH,a=r*TH+j,b=r*TH+jn,c=(r+1)*TH+jn,d=(r+1)*TH+j; idx.push(a,b,c,a,c,d); }
  const RS=20, RR=12;
  for(const s of rootSpecs(cls,nRoots,hmd,hbl,len)){ const base=pos.length/3;
    for(let r=0;r<=RR;r++){ const t=r/RR, y=-COL*.62-s.len*t, bend=t*t, cx=s.x+s.ox*bend, cz=s.z+s.oz*bend, k=Math.pow(1-t,.62)*(1+.1*Math.sin(Math.PI*t));
      if(r===RR){ pos.push(cx,y,cz); break; } for(let j=0;j<RS;j++){ const th=2*Math.PI*j/RS; pos.push(cx+Math.cos(th)*s.rx*k,y,cz+Math.sin(th)*s.rz*k); } }
    for(let r=0;r<RR;r++){ const o=base+r*RS,i=base+(r+1)*RS; if(r===RR-1){ const tip=base+RR*RS; for(let j=0;j<RS;j++){ const jn=(j+1)%RS; idx.push(o+j,o+jn,tip); } } else for(let j=0;j<RS;j++){ const jn=(j+1)%RS; idx.push(o+j,i+jn,i+j,o+j,o+jn,i+jn); } } }
  const geo=new THREE.BufferGeometry(); geo.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); geo.setIndex(idx); geo.computeVertexNormals(); geo.computeBoundingSphere(); return geo;
}
function buildScrew(r){ const pts=[new THREE.Vector2(0,.4),new THREE.Vector2(r*.85,.4),new THREE.Vector2(r,0),new THREE.Vector2(r,-.9)];
  for(let i=0;i<8;i++){ const y=-1.2-i*1.15, k=1-i*.055; pts.push(new THREE.Vector2(r*.78*k,y),new THREE.Vector2(r*k,y-.55)); }
  pts.push(new THREE.Vector2(r*.45,-10.6),new THREE.Vector2(0,-11)); return new THREE.LatheGeometry(pts,24); }
/* Десна: гребень эллиптического сечения вдоль той же параболы, чуть длиннее ряда. */
function buildRidge(A,D,apex,yTop,dir){
  const rx=6.0, ry=8.5, N=96, M=28, ext=4, yc=yTop+dir*(ry-.7), pos=[], idx=[];
  for(let i=0;i<=N;i++){ const x=-(A+ext)+2*(A+ext)*i/N, z=apex-D*x*x/(A*A), dz=-2*D*x/(A*A), nn=Math.hypot(1,dz), tx=1/nn, tz=dz/nn, nx=-tz, nz=tx;
    for(let j=0;j<M;j++){ const ph=2*Math.PI*j/M, ox=Math.cos(ph)*rx, oy=Math.sin(ph)*ry; pos.push(x+nx*ox,yc+oy,z+nz*ox); } }
  for(let i=0;i<N;i++) for(let j=0;j<M;j++){ const jn=(j+1)%M,a=i*M+j,b=i*M+jn,c=(i+1)*M+jn,d=(i+1)*M+j; idx.push(a,c,b,a,d,c); }
  for(const ring of [0,N]){ const c=pos.length/3; let cx=0,cy=0,cz=0; for(let j=0;j<M;j++){ cx+=pos[(ring*M+j)*3]; cy+=pos[(ring*M+j)*3+1]; cz+=pos[(ring*M+j)*3+2]; } pos.push(cx/M,cy/M,cz/M);
    for(let j=0;j<M;j++){ const jn=(j+1)%M; idx.push(c,ring*M+j,ring*M+jn); } }
  const geo=new THREE.BufferGeometry(); geo.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); geo.setIndex(idx); geo.computeVertexNormals(); geo.computeBoundingSphere(); return geo;
}
function labelTex(n,on){ const c=document.createElement('canvas'); c.width=c.height=96; const x=c.getContext('2d'); x.font='700 46px Inter, system-ui, sans-serif'; x.textAlign='center'; x.textBaseline='middle'; x.lineJoin='round'; x.lineWidth=9; x.strokeStyle='rgba(255,255,255,.88)'; x.strokeText(String(n),48,52); x.fillStyle=on?'#0f7b8a':'#3f4e58'; x.fillText(String(n),48,52); const t=new THREE.CanvasTexture(c); t.colorSpace=THREE.SRGBColorSpace; return t; }

const T3={}, crowns3=[];
function init3D(){
  const stage=document.getElementById('stage'); if(!stage) return;
  if(typeof THREE==='undefined'){ stage.insertAdjacentHTML('beforeend','<div class="msg">3D nu s-a încărcat: biblioteca three.js vine de pe cdn.jsdelivr.net și nu a răspuns. Harta 2D de mai jos funcționează.</div>'); return; }
  let renderer; try{ renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'high-performance'}); }catch(e){ stage.insertAdjacentHTML('beforeend','<div class="msg">WebGL nu este disponibil în acest browser.</div>'); return; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2)); renderer.outputColorSpace=THREE.SRGBColorSpace; renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=.95;
  const canvas=renderer.domElement; canvas.setAttribute('aria-label','Odontogramă 3D'); canvas.tabIndex=0; stage.insertBefore(canvas,stage.firstChild);
  const scene=new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xeef5f7,0xb9a692,1.1));
  const key=new THREE.DirectionalLight(0xfff4e8,2.3); key.position.set(40,80,90); scene.add(key);
  const fill=new THREE.DirectionalLight(0xdfeaf2,.9); fill.position.set(-70,20,50); scene.add(fill);
  const rim=new THREE.DirectionalLight(0xffffff,.7); rim.position.set(-20,40,-120); scene.add(rim);
  const low=new THREE.DirectionalLight(0xfff4e8,.8); low.position.set(20,-80,60); scene.add(low);
  const gumMat=new THREE.MeshStandardMaterial({color:GUM3,roughness:.78,metalness:0,side:THREE.DoubleSide});
  const upperG=new THREE.Group(), lowerG=new THREE.Group(); scene.add(upperG,lowerG);
  const reduced=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // --- твины: кадры только пока что-то движется ---
  const tweens=[]; const ease=k=>k<.5?4*k*k*k:1-Math.pow(-2*k+2,3)/2;
  function tween(dur,fn,done,delay=0,tag=null){ if(reduced||dur<=0){ fn(1); if(done) done(); return; } tweens.push({t0:performance.now()+delay,dur,fn,done,tag}); invalidate(); }
  function killTweens(tag){ for(let i=tweens.length-1;i>=0;i--) if(tweens[i].tag===tag) tweens.splice(i,1); }
  function stepTweens(now){ for(let i=tweens.length-1;i>=0;i--){ const tw=tweens[i]; if(now<tw.t0) continue; const k=Math.min(1,(now-tw.t0)/tw.dur); tw.fn(ease(k)); if(k>=1){ tweens.splice(i,1); if(tw.done) tw.done(); } } return tweens.length>0; }
  // --- челюсти: смыкание и уход из кадра — оба через сдвиг группы ---
  const GAP=26, GAP_CLOSED=18;
  const jaw={upper:{grp:upperG,closeY:0,hideY:0,dir:1},lower:{grp:lowerG,closeY:0,hideY:0,dir:-1}};
  function placeJaws(){ upperG.position.y=-jaw.upper.closeY+jaw.upper.hideY; lowerG.position.y=jaw.lower.closeY+jaw.lower.hideY; }
  function buildArch(list,upper){
    const dims=list.map(n=>({n,hmd:G[n].occ.hw*MM,hbl:G[n].occ.hd*MM})); const widths=dims.map(d=>2*d.hmd+.3); const sum=widths.reduce((a,b)=>a+b,0);
    const unit=curve(1,1.6,0,-1), sc=sum/unit.total, A=sc, D=1.6*sc, apex=upper?2:-2.5, cv=curve(A,D,apex,-1), yBase=upper?GAP/2:-GAP/2, grp=upper?upperG:lowerG;
    const ridge=new THREE.Mesh(buildRidge(A,D,apex,yBase,upper?1:-1),gumMat); ridge.raycast=()=>{}; grp.add(ridge);
    let acc=0;
    dims.forEach((d,i)=>{ const s=acc+widths[i]/2; acc+=widths[i]; const p=cv.at(s); const n=d.n, g=G[n], cls=g.cls, H=CROWN_H[cls][upper?0:1], len=ROOT_L[cls][upper?0:1];
      const mats=SURF3.map(()=>new THREE.MeshStandardMaterial({color:ENAMEL3,roughness:.32,metalness:0,emissive:new THREE.Color(GLOW3),emissiveIntensity:0}));
      const crown=new THREE.Mesh(buildCrown(d.hmd,d.hbl,H,cls,upper),mats); crown.userData.n=n; crowns3.push(crown);
      const roots=new THREE.Mesh(buildRoots(d.hmd,d.hbl,cls,g.roots.length,len),new THREE.MeshStandardMaterial({color:DENTIN3,roughness:.62,metalness:0})); roots.raycast=()=>{};
      const screw=new THREE.Mesh(buildScrew(Math.min(d.hmd,d.hbl)*.9),new THREE.MeshStandardMaterial({color:TITAN3,roughness:.35,metalness:.9})); screw.raycast=()=>{};
      // Винт виден ВСЕГДА, даже сквозь десну: та же геометрия поверх всего, полупрозрачная, с фиолетовым свечением состояния
      const screwX=new THREE.Mesh(screw.geometry,new THREE.MeshStandardMaterial({color:TITAN3,roughness:.35,metalness:.6,transparent:true,opacity:.62,depthTest:false,depthWrite:false,emissive:new THREE.Color(0x8B5CF6),emissiveIntensity:.35})); screwX.renderOrder=20; screwX.raycast=()=>{}; screw.add(screwX);
      const mkRing=(color,y)=>{ const m=new THREE.Mesh(new THREE.TorusGeometry(d.hbl*1.06,.34,8,48),new THREE.MeshBasicMaterial({color})); m.rotation.x=Math.PI/2; m.scale.set(d.hmd/d.hbl,1,1); m.position.y=y; m.raycast=()=>{}; return m; };
      const ringT=mkRing(0x16A34A,1.6), ringI=mkRing(0x8B5CF6,1.1), ringS=mkRing(0x0f7b8a,2.1);
      const socket=new THREE.Mesh(new THREE.CircleGeometry(1,32),new THREE.MeshStandardMaterial({color:SOCKET3,roughness:.95,metalness:0})); socket.scale.set(d.hmd*.85,d.hbl*.85,1); socket.rotation.x=-Math.PI/2; socket.position.y=.78; socket.raycast=()=>{};
      const tex=[labelTex(n,false),labelTex(n,true)]; const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:tex[0],transparent:true,depthTest:true})); sprite.scale.set(3.9,3.9,1); sprite.position.set(0,-2.4,8.8); sprite.raycast=()=>{};
      const grpT=new THREE.Group(); grpT.add(crown,roots,screw,ringT,ringI,ringS,socket,sprite);
      const P=new THREE.Vector3(p.x,yBase,p.y), Bv=new THREE.Vector3(p.nx,0,p.ny).normalize(), Tv=new THREE.Vector3(p.tx,0,p.ty).normalize(); if(p.x>0) Tv.negate();
      grpT.matrixAutoUpdate=false; grpT.matrix.makeBasis(Tv.clone().negate(),new THREE.Vector3(0,upper?-1:1,0),Bv).setPosition(P);
      grp.add(grpT); T3[n]={crown,mats,roots,screw,screwX,ringT,ringI,ringS,socket,sprite,tex,sx:d.hmd/d.hbl,look:null}; });
  }
  buildArch(UPPER,true); buildArch(LOWER,false);
  // --- камера и орбита ---
  const cam=new THREE.PerspectiveCamera(30,1,1,1000), target=new THREE.Vector3(0,0,-16);
  const rad=THREE.MathUtils.degToRad; const VIEWS={frontal:[0,80,172],sus:[0,152,180],jos:[0,28,180],dreapta:[-62,82,175],stanga:[62,82,175]};
  const orb={theta:0,phi:rad(80),r:172,tt:0,tp:rad(80),tr:172};
  const togs={xray:false,labels:true,upper:true,lower:true,closed:false,rotate:false};
  function applyCam(){ const sp=Math.sin(orb.phi); cam.position.set(target.x+orb.r*sp*Math.sin(orb.theta),target.y+orb.r*Math.cos(orb.phi),target.z+orb.r*sp*Math.cos(orb.theta)); cam.lookAt(target); }
  let frame=0, anim=false;
  function draw(now){ frame=0; const busy=stepTweens(now||performance.now());
    if(anim){ const k=.18; orb.theta+=(orb.tt-orb.theta)*k; orb.phi+=(orb.tp-orb.phi)*k; orb.r+=(orb.tr-orb.r)*k; if(Math.abs(orb.tt-orb.theta)<.002&&Math.abs(orb.tp-orb.phi)<.002&&Math.abs(orb.tr-orb.r)<.2){ orb.theta=orb.tt; orb.phi=orb.tp; orb.r=orb.tr; anim=false; } }
    if(togs.rotate&&!anim){ orb.theta+=.0035; orb.tt=orb.theta; }
    applyCam(); renderer.render(scene,cam); if(anim||busy||togs.rotate) invalidate(); }
  function invalidate(){ if(!frame) frame=requestAnimationFrame(draw); }
  function clearView(){ document.querySelectorAll('#views button').forEach(b=>b.setAttribute('aria-pressed','false')); }
  function setView(name){ const v=VIEWS[name]; if(!v) return; orb.tt=rad(v[0]); orb.tp=rad(v[1]); orb.tr=v[2]; if(reduced){ orb.theta=orb.tt; orb.phi=orb.tp; orb.r=orb.tr; anim=false; } else anim=true;
    if(togs.rotate){ togs.rotate=false; const b=document.querySelector('#togs .tog[data-tog="rotate"]'); if(b) b.setAttribute('aria-pressed','false'); }
    document.querySelectorAll('#views button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===name)));
    // вид на жевательные поверхности одной челюсти невозможен, пока другая стоит перед камерой — она уезжает из кадра, кнопки это показывают
    setJaw('upper', name!=='jos'); setJaw('lower', name!=='sus'); invalidate(); }
  function setJaw(k,on){ const J=jaw[k]; togs[k]=on; const b=document.querySelector(`#togs .tog[data-tog="${k}"]`); if(b) b.setAttribute('aria-pressed',String(on)); const lab=stage.querySelector(k==='upper'?'.jaw3.up':'.jaw3.lo'); if(lab) lab.hidden=!on;
    const from=J.hideY, to=on?0:J.dir*70; if(from===to&&J.grp.visible===on) return; killTweens('jaw-'+k); if(on) J.grp.visible=true;
    tween(420,t=>{ J.hideY=from+(to-from)*t; placeJaws(); },()=>{ if(!on) J.grp.visible=false; },0,'jaw-'+k); }
  function setClosed(on){ const fu=jaw.upper.closeY, fl=jaw.lower.closeY, c=on?(GAP-GAP_CLOSED)/2:0; killTweens('close');
    tween(700,k=>{ jaw.upper.closeY=fu+(c-fu)*k; jaw.lower.closeY=fl+(c-fl)*k; placeJaws(); },null,0,'close'); }
  // --- размер ---
  let lw=0,lh=0; function resize(){ const w=Math.max(1,Math.round(stage.clientWidth)), h=Math.max(1,Math.round(stage.clientHeight)); if(w===lw&&h===lh) return; lw=w; lh=h; renderer.setSize(w,h,false); cam.aspect=w/h; cam.updateProjectionMatrix(); invalidate(); }
  new ResizeObserver(resize).observe(stage); resize();
  // --- указатель: орбита, наведение, клик ---
  const ray=new THREE.Raycaster(), ndc=new THREE.Vector2(); const ptrs=new Map(); let drag=false, downX=0, downY=0, moved=false, pinch0=0, r0=0;
  function pick(ev){ const rc=canvas.getBoundingClientRect(); if(!rc.width||!rc.height) return null; ndc.x=((ev.clientX-rc.left)/rc.width)*2-1; ndc.y=-((ev.clientY-rc.top)/rc.height)*2+1; ray.setFromCamera(ndc,cam);
    const hit=ray.intersectObjects(crowns3.filter(c=>c.visible&&c.parent.parent.visible),false)[0]; if(!hit||!hit.face) return null; return {n:hit.object.userData.n,L:SURF3[hit.face.materialIndex]}; }
  const hoverEl=document.getElementById('hover3');
  function setHover(h){ const same=(h&&hover3&&h.n===hover3.n&&h.L===hover3.L)||(!h&&!hover3); if(same) return; hover3=h; canvas.classList.toggle('pick',!!h);
    hoverEl.textContent=h?`${h.n} · ${(h.L==='L'&&G[h.n].up)?'palatinal':SFNAME[h.L]} · ${P.STATE_RO[effState(teeth[h.n])]}`:''; paintGlow(); }
  let pend=null, hf=0; function runHover(){ hf=0; const ev=pend; pend=null; if(!ev||drag) return; setHover(pick(ev)); }
  canvas.addEventListener('pointerdown',ev=>{ canvas.setPointerCapture(ev.pointerId); ptrs.set(ev.pointerId,[ev.clientX,ev.clientY]); if(ptrs.size===1){ drag=true; moved=false; downX=ev.clientX; downY=ev.clientY; canvas.classList.add('drag'); } else if(ptrs.size===2){ const a=[...ptrs.values()]; pinch0=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]); r0=orb.r; } });
  canvas.addEventListener('pointermove',ev=>{ if(ptrs.has(ev.pointerId)){ const prev=ptrs.get(ev.pointerId); ptrs.set(ev.pointerId,[ev.clientX,ev.clientY]);
      if(ptrs.size===2){ const a=[...ptrs.values()]; const d=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]); if(pinch0>0){ orb.r=clamp(r0*pinch0/d,70,420); orb.tr=orb.r; anim=false; invalidate(); } moved=true; return; }
      const dx=ev.clientX-prev[0], dy=ev.clientY-prev[1]; if(Math.abs(ev.clientX-downX)>4||Math.abs(ev.clientY-downY)>4) moved=true;
      if(moved){ orb.theta-=dx*.006; orb.phi=clamp(orb.phi-dy*.006,.08,Math.PI-.08); orb.tt=orb.theta; orb.tp=orb.phi; anim=false; clearView(); invalidate(); } return; }
    pend=ev; if(!hf) hf=requestAnimationFrame(runHover); });
  function up(ev){ if(!ptrs.has(ev.pointerId)) return; ptrs.delete(ev.pointerId); if(ptrs.size) return; drag=false; canvas.classList.remove('drag');
    if(!moved){ const h=pick(ev); if(h) on3DClick(h.n,h.L); } }
  canvas.addEventListener('pointerup',up); canvas.addEventListener('pointercancel',up);
  canvas.addEventListener('pointerleave',()=>{ pend=null; if(!drag) setHover(null); });
  canvas.addEventListener('wheel',ev=>{ ev.preventDefault(); orb.r=clamp(orb.r*(1+ev.deltaY*.0012),70,420); orb.tr=orb.r; invalidate(); },{passive:false});
  canvas.addEventListener('webglcontextlost',ev=>{ ev.preventDefault(); });
  document.querySelectorAll('#views button').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
  document.querySelectorAll('#togs .tog').forEach(b=>b.addEventListener('click',()=>{ const k=b.dataset.tog; togs[k]=!togs[k]; b.setAttribute('aria-pressed',String(togs[k]));
    if(k==='xray'){ gumMat.transparent=togs.xray; gumMat.opacity=togs.xray?.28:1; gumMat.depthWrite=!togs.xray; }
    else if(k==='upper'||k==='lower') setJaw(k,togs[k]); else if(k==='closed') setClosed(togs.closed); else if(k==='rotate'&&togs.rotate) clearView();
    paint3D(); }));
  R3={renderer,scene,cam,invalidate,togs,tween,killTweens};
  const h3=(location.hash||'').slice(1); if(h3.startsWith('3d-')){ for(const part of h3.slice(3).split('-')){ if(VIEWS[part]){ setView(part); orb.theta=orb.tt; orb.phi=orb.tp; orb.r=orb.tr; anim=false; }
      else if(togs.hasOwnProperty(part)){ const b=document.querySelector(`#togs .tog[data-tog="${part}"]`); if(b) b.click(); } } }
  applyCam(); paint3D();
}
function on3DClick(n,L){ const t=teeth[n], st=effState(t); sel=n; if(st==='ok'||st==='carie'||st==='obturatie') cycleSf(n,L); else render(); }
/* Целевой вид зуба по данным: что видно и какого цвета каждая поверхность. */
function targetLook(n){ const t=teeth[n], st=effState(t), br=bridgeOf(n), pontic=!!(br&&br.role==='corp'), gone=st==='extras', ghost=st==='lipsa'&&!pontic, gold=st==='coroana'||pontic, implant=st==='implant';
  const sf=sfMap(t), whole=(st==='carie'||st==='obturatie')&&!Object.keys(sf).length;
  const cols=SURF3.map(L=>{ const c=new THREE.Color(gold?GOLD3:implant?CERAMIC3:ENAMEL3); if(!gold&&!implant){ if(sf[L]) c.lerp(new THREE.Color(P.COLORS[sf[L]]),.6); else if(whole) c.lerp(new THREE.Color(P.COLORS[st]),.32); } return c; });
  return {st,pontic,gone,ghost,gold,implant,cols,mark:t.marks.includes('tratament')}; }
const setOp=(T,v)=>T.mats.forEach(m=>{ m.transparent=true; m.opacity=v; });
/* Применить вид: мгновенно (первый кадр, конец анимации) или твином по цвету. */
function applyLook(T,look,instant){ const {tween}=R3;
  T.crown.visible=!look.gone; T.socket.visible=look.gone; T.roots.visible=!look.gone&&!look.implant&&!look.ghost&&!look.pontic; T.screw.visible=look.implant;
  T.crown.position.y=0; T.roots.position.y=0; T.screw.position.y=0; T.screw.rotation.y=0; T.crown.scale.setScalar(1); T.roots.material.opacity=1; T.roots.material.transparent=false; T.socket.material.opacity=1; T.socket.material.transparent=false;
  const op=look.ghost?.22:1, met=look.gold?.85:0, rough=look.gold?.28:look.implant?.22:.32;
  SURF3.forEach((L,i)=>{ const m=T.mats[i], c=look.cols[i];
    if(instant){ m.color.copy(c); m.metalness=met; m.roughness=rough; m.opacity=op; m.transparent=look.ghost; m.depthWrite=!look.ghost; return; }
    const c0=m.color.clone(), met0=m.metalness, r0=m.roughness, op0=m.opacity; if(c0.equals(c)&&met0===met&&op0===op){ m.roughness=rough; m.transparent=look.ghost; m.depthWrite=!look.ghost; return; }
    m.transparent=true; tween(380,k=>{ m.color.copy(c0).lerp(c,k); m.metalness=met0+(met-met0)*k; m.roughness=r0+(rough-r0)*k; m.opacity=op0+(op-op0)*k; },()=>{ m.transparent=look.ghost; m.depthWrite=!look.ghost; },0,T); }); }
function fadeRoots(T,on){ const {tween}=R3, rm=T.roots.material; rm.transparent=true; if(on){ T.roots.visible=true; rm.opacity=0; } const o0=rm.opacity, o1=on?1:0;
  tween(320,k=>{ rm.opacity=o0+(o1-o0)*k; },()=>{ if(!on) T.roots.visible=false; rm.opacity=1; rm.transparent=false; },0,T); }
/* Смена состояния зуба — маленькая сцена: имплант вкручивается, удалённый выходит из лунки, отсутствующий тает, коронка садится. */
function animateStruct(T,prev,look){ const {tween,killTweens}=R3; killTweens(T); const finish=()=>applyLook(T,look,true);
  if(look.implant){ if(T.roots.visible) fadeRoots(T,false);
    T.crown.visible=false; T.screw.visible=true; T.screw.position.y=16; T.screw.rotation.y=0;
    tween(900,k=>{ T.screw.position.y=16*(1-k); T.screw.rotation.y=k*Math.PI*6; },null,0,T);
    T.mats.forEach((m,i)=>{ m.color.copy(look.cols[i]); m.metalness=0; m.roughness=.22; }); setOp(T,0);
    tween(520,k=>{ T.crown.visible=true; T.crown.position.y=12*(1-k); setOp(T,k); },finish,820,T); return; }
  if(look.gone){ const rm=T.roots.material, rootsOn=T.roots.visible; rm.transparent=true; const op0=T.mats[0].opacity;
    T.socket.visible=true; const sm=T.socket.material; sm.transparent=true; sm.opacity=0;
    tween(720,k=>{ T.crown.position.y=16*k; T.roots.position.y=16*k; T.screw.position.y=16*k; setOp(T,op0*(1-k)); if(rootsOn) rm.opacity=1-k; sm.opacity=k; },finish,0,T); return; }
  if(look.ghost){ const op0=T.mats[0].opacity; T.mats.forEach((m,i)=>m.color.copy(look.cols[i])); if(T.roots.visible) fadeRoots(T,false); if(T.screw.visible){ tween(500,k=>{ T.screw.position.y=16*k; },null,0,T); }
    tween(500,k=>setOp(T,op0+(.22-op0)*k),finish,0,T); return; }
  if(look.gold){ if(T.roots.visible&&look.pontic) fadeRoots(T,false); if(!T.roots.visible&&!look.pontic&&!prev.gone&&!prev.implant) fadeRoots(T,true);
    if(prev.gone||prev.implant||prev.ghost){ T.crown.visible=true; T.mats.forEach((m,i)=>{ m.color.copy(look.cols[i]); m.metalness=.85; m.roughness=.28; }); setOp(T,prev.ghost?.22:0); if(prev.implant) tween(600,k=>{ T.screw.position.y=16*k; T.screw.rotation.y=-k*Math.PI*6; },null,0,T);
      tween(480,k=>{ T.crown.position.y=(prev.ghost?0:-4)*(1-k); setOp(T,(prev.ghost?.22:0)+(1-(prev.ghost?.22:0))*k); },finish,0,T); }
    else { applyLook(T,look,false); tween(440,k=>{ T.crown.scale.setScalar(1+.07*Math.sin(Math.PI*k)); },()=>T.crown.scale.setScalar(1),0,T); }
    return; }
  // живой зуб возвращается: из лунки, из-под импланта, из призрака или из-под коронки
  if(prev.implant) tween(600,k=>{ T.screw.position.y=16*k; T.screw.rotation.y=-k*Math.PI*6; },null,0,T);
  if(prev.gone){ const sm=T.socket.material; sm.transparent=true; tween(300,k=>{ sm.opacity=1-k; },null,0,T); }
  if(!T.roots.visible) fadeRoots(T,true);
  if(prev.gone||prev.implant||prev.ghost){ T.crown.visible=true; T.mats.forEach((m,i)=>{ m.color.copy(look.cols[i]); m.metalness=0; m.roughness=.32; }); const o0=prev.ghost?.22:0; setOp(T,o0);
    tween(480,k=>{ T.crown.position.y=(prev.ghost?0:-4)*(1-k); setOp(T,o0+(1-o0)*k); },finish,0,T); }
  else applyLook(T,look,false);
}
function paintGlow(){ if(!R3) return; for(const n of ALL){ const T=T3[n]; if(!T) continue; SURF3.forEach((L,i)=>{ T.mats[i].emissiveIntensity=(hover3&&hover3.n===n&&hover3.L===L)?.16:(n===sel?.05:0); }); } R3.invalidate(); }
function paint3D(){ if(!R3) return; const {togs,tween}=R3;
  for(const n of ALL){ const T=T3[n]; if(!T) continue; const look=targetLook(n), prev=T.look; T.look=look;
    T.sprite.visible=togs.labels; const want=T.tex[n===sel?1:0]; if(T.sprite.material.map!==want){ T.sprite.material.map=want; T.sprite.material.needsUpdate=true; }
    T.ringT.visible=!look.gone&&look.mark; T.ringI.visible=look.implant;
    const selNow=n===sel&&!look.gone; if(selNow&&!T.ringS.visible){ T.ringS.visible=true; const sx=T.sx; tween(220,k=>{ const s=.55+.45*k; T.ringS.scale.set(sx*s,1,s); },()=>T.ringS.scale.set(sx,1,1),0,'sel'); } else if(!selNow) T.ringS.visible=false;
    if(!prev) applyLook(T,look,true); else if(prev.st!==look.st||prev.pontic!==look.pontic) animateStruct(T,prev,look); else applyLook(T,look,false); }
  paintGlow(); }
init3D();
'''

JS = r'''
const UPPER=[18,17,16,15,14,13,12,11,21,22,23,24,25,26,27,28];
const LOWER=[48,47,46,45,44,43,42,41,31,32,33,34,35,36,37,38];
const ALL=UPPER.concat(LOWER);
const SURF=['M','O','D','V','L'];
const STATES=['ok','carie','obturatie','coroana','implant','extras','lipsa'];
const NAMES={incisor_c:'Incisiv central',incisor_l:'Incisiv lateral',canine:'Canin',premolar:['Primul premolar','Al doilea premolar'],molar:['Primul molar','Al doilea molar','Molar de minte']};
const SFNAME={O:'ocluzal',V:'vestibular',L:'lingual',M:'mezial',D:'distal'};
const SAMPLE={
  teeth:{16:{state:'carie',sf:{M:'carie',O:'obturatie'}},27:{state:'obturatie',sf:{O:'obturatie'}},36:{state:'coroana'},46:{state:'implant'},
    18:{state:'extras'},28:{state:'lipsa'},38:{state:'lipsa'},11:{state:'obturatie',sf:{V:'obturatie'}},47:{state:'carie',sf:{D:'carie'},marks:['tratament']},
    24:{state:'coroana'},25:{state:'lipsa'},26:{state:'coroana'},22:{state:'carie',sf:{M:'carie',D:'carie'}},44:{state:'obturatie',sf:{O:'obturatie'}},35:{state:'carie',sf:{O:'carie'}}},
  bridges:[{teeth:[[24,'stalp'],[25,'corp'],[26,'stalp']],material:'metaloceramică'}]
};
let teeth={}, bridges=[], sel=16, tpl='arcada';
var flashN=null;   // зуб, который только что изменили: вспышка в 2D после перерисовки
function load(){ teeth={}; for(const n of ALL){ const s=SAMPLE.teeth[n]||{}; teeth[n]={state:s.state||'ok',sf:Object.assign({},s.sf||{}),marks:(s.marks||[]).slice()}; }
  bridges=SAMPLE.bridges.map(b=>({teeth:b.teeth.map(t=>t.slice()),material:b.material})); }
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const q=n=>Math.floor(n/10);
const colOf=st=>st==='extras'?'var(--t-line)':st==='lipsa'?'var(--t-ghost)':(P.COLORS[st]||'var(--t-line)');
function effState(t){ const v=Object.values(t.sf); if(v.length&&(t.state==='ok'||t.state==='carie'||t.state==='obturatie')) return v.includes('carie')?'carie':'obturatie'; return t.state; }
function sfMap(t){ const st=effState(t); return (st==='carie'||st==='obturatie')?t.sf:{}; }
function bridgeOf(n){ for(const b of bridges){ const t=b.teeth.find(x=>x[0]===n); if(t) return {teeth:b.teeth,material:b.material,role:t[1]}; } return null; }
function toothName(n){ const g=G[n], p=n%10; if(g.cls==='premolar') return NAMES.premolar[p-4]; if(g.cls==='molar') return NAMES.molar[p-6]; return NAMES[g.cls]; }
function jawSide(n){ const k=q(n); return (k<=2?'Maxilar':'Mandibular')+' · '+((k===1||k===4)?'dreapta':'stânga'); }
function letters(t){ const sf=sfMap(t); return SURF.filter(L=>sf[L]).map(L=>(L==='L'&&G[sel&&0||1]&&false)?L:L).join(''); }
function title(n){ const t=teeth[n], st=effState(t), sf=sfMap(t); const parts=[n, P.STATE_RO[st]]; const ls=SURF.filter(L=>sf[L]); if(ls.length) parts.push(ls.map(L=>`${P.STATE_RO[sf[L]]} (${(L==='L'&&G[n].up)?'P':L})`).join(', ')); if(t.marks.length) parts.push(t.marks.map(m=>P.MARK_RO[m]).join(', ')); const b=bridgeOf(n); if(b) parts.push('punte · '+(b.role==='stalp'?'stâlp':'corp')); return parts.join(' · '); }
function aria(n){ return 'Dinte '+title(n).replace(/ · /g,', '); }

/* ---------- один зуб, каноническая ориентация (как в teeth_svg.py) ---------- */
function frontal(n,t,hit){
  const g=G[n], st=effState(t), col=colOf(st), o=[];
  for(const m of t.marks) o.push(`<path d="${g.crown}" fill="none" stroke="${P.MARK_COLORS[m]}" stroke-width="6" stroke-linejoin="round" opacity=".85"/>`);
  if(st==='lipsa'){
    o.push(`<path d="${g.crown}" fill="none" stroke="var(--t-ghost)" stroke-width="1.6" stroke-dasharray="3 3"/>`);
    for(const r of g.roots) o.push(`<path d="${r}" fill="none" stroke="var(--t-ghost)" stroke-width="1.6" stroke-dasharray="3 3"/>`);
  } else if(st==='implant'){
    o.push(`<path d="${g.screw}" fill="var(--f-implant)" stroke="${col}" stroke-width="1.8"/>`);
    for(const th of g.threads) o.push(`<path d="${th}" fill="none" stroke="${col}" stroke-width="1.4" opacity=".75"/>`);
    o.push(`<path d="${g.crown}" fill="url(#g-enamel)" stroke="${col}" stroke-width="1.8"/>`);
    for(const f of g.fiss) o.push(`<path d="${f}" fill="none" stroke="${col}" stroke-width="1.2" opacity=".5"/>`);
  } else {
    const rc=st==='extras'?col:'var(--t-line)';
    for(const r of g.roots) o.push(`<path d="${r}" fill="${st==='extras'?'var(--f-extras)':P.ROOT_FILL}" stroke="${rc}" stroke-width="1.8"/>`);
    let cf='url(#g-enamel)', cc='var(--t-line)';
    if(st==='coroana'){cc='#D97706';cf='url(#g-gold)';}
    else if(st==='extras'){cf='var(--f-extras)';cc=col;}
    else if(st==='carie'||st==='obturatie'){cc=col;}
    o.push(`<path d="${g.crown}" fill="${cf}" stroke="${cc}" stroke-width="1.8"/>`);
    if(st!=='coroana'){ const det=(st==='carie'||st==='obturatie')?cc:'var(--t-soft)'; for(const f of g.fiss) o.push(`<path d="${f}" fill="none" stroke="${det}" stroke-width="1.2" opacity=".55"/>`); }
    const sf=sfMap(t), mk=[];
    for(const L of SURF){ const s=sf[L]; if(!s) continue; const c=P.COLORS[s], f=P.MARK_FILL[s], [cx,cy]=g.marks[L];
      mk.push(L==='L'?`<circle cx="${cx}" cy="${cy}" r="${g.mr}" fill="none" stroke="${c}" stroke-width="1.6"/>`:`<circle cx="${cx}" cy="${cy}" r="${g.mr}" fill="${f}" stroke="${c}" stroke-width="1.3"/>`); }
    if(mk.length) o.push(...mk);
    else if(st==='carie') o.push(`<path d="${g.carie}" fill="${col}"/>`);
    else if(st==='obturatie') o.push(`<path d="${g.obt}" fill="${col}"/>`);
    else if(st==='extras') o.push(`<path d="${g.cross}" fill="none" stroke="${col}" stroke-width="3" stroke-linecap="round"/>`);
  }
  if(hit) for(const L of SURF){ const [cx,cy]=g.marks[L]; o.push(`<circle cx="${cx}" cy="${cy}" r="${g.hr}" data-s="${L}" fill="transparent" stroke="none"/>`); }
  return o.join('');
}
function zones(n){ const z=G[n].occ.zones; return `<g clip-path="url(#clip-${n})">`+SURF.map(L=>{const [x,y,w,h]=z[L]; return `<rect x="${x}" y="${y}" width="${w}" height="${h}" data-s="${L}" fill="transparent" stroke="none"/>`;}).join('')+'</g>'; }
function occlusal(n,t,hit){
  const g=G[n], oc=g.occ, st=effState(t), col=colOf(st), o=[];
  for(const m of t.marks) o.push(`<path d="${oc.outline}" fill="none" stroke="${P.MARK_COLORS[m]}" stroke-width="6" stroke-linejoin="round" opacity=".85"/>`);
  if(st==='lipsa'){ o.push(`<path d="${oc.outline}" fill="none" stroke="var(--t-ghost)" stroke-width="1.6" stroke-dasharray="3 3"/>`); if(hit) o.push(zones(n)); return o.join(''); }
  let fill, line;
  if(st==='coroana'){fill=P.CROWN_GOLD[2];line='#D97706';}
  else if(st==='extras'){fill='var(--f-extras)';line=col;}
  else {fill=P.ENAMEL[2];line=(st==='carie'||st==='obturatie'||st==='implant')?col:'var(--t-line)';}
  o.push(`<path d="${oc.outline}" fill="${fill}"/>`);
  if(st!=='extras'&&st!=='implant'){ const lf=st==='coroana'?P.CROWN_GOLD[0]:'url(#g-enamel)'; for(const [x,y,rx,ry] of oc.lobes) o.push(`<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" fill="${lf}"/>`); }
  if(st==='carie'||st==='obturatie'){ const sf=sfMap(t), ks=SURF.filter(L=>sf[L]);
    if(ks.length) o.push(`<g clip-path="url(#clip-${n})">`+ks.map(L=>{const [x,y,w,h]=oc.zones[L]; return `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${P.MARK_FILL[sf[L]]}" fill-opacity=".82"/>`;}).join('')+'</g>');
    else o.push(`<path d="${oc.outline}" fill="var(--f-${st})"/>`); }
  if(st==='implant'){ const r=Math.min(oc.hw,oc.hd)*.72; o.push(`<circle cx="22" cy="22" r="${r.toFixed(1)}" fill="var(--f-implant)" stroke="${col}" stroke-width="1.6"/><circle cx="22" cy="22" r="${(r*.46).toFixed(1)}" fill="none" stroke="${col}" stroke-width="1.4"/>`); }
  else if(st!=='coroana'&&(g.cls==='incisor_c'||g.cls==='incisor_l'||g.cls==='canine')){ const det=(st==='carie'||st==='obturatie')?col:'var(--t-soft)'; for(const f of oc.fiss) o.push(`<path d="${f}" fill="none" stroke="${det}" stroke-width="1.2" opacity=".55"/>`); }
  if(st==='extras'){ const hw=oc.hw*.62, hd=oc.hd*.62; o.push(`<path d="M ${(22-hw).toFixed(1)} ${(22-hd).toFixed(1)} L ${(22+hw).toFixed(1)} ${(22+hd).toFixed(1)} M ${(22+hw).toFixed(1)} ${(22-hd).toFixed(1)} L ${(22-hw).toFixed(1)} ${(22+hd).toFixed(1)}" fill="none" stroke="${col}" stroke-width="3" stroke-linecap="round"/>`); }
  o.push(`<path d="${oc.outline}" fill="none" stroke="${line}" stroke-width="1.8"/>`);
  if(hit) o.push(zones(n));
  return o.join('');
}
function svgFrontal(n,t,w,hit){ const g=G[n]; let inner=frontal(n,t,hit); if(g.mir) inner=`<g transform="translate(44,0) scale(-1,1)">${inner}</g>`; if(g.up) inner=`<g transform="translate(0,90) scale(1,-1)">${inner}</g>`;
  return `<svg class="tsvg" viewBox="0 0 44 90" width="${w}" height="${Math.round(w*90/44)}" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`; }
function svgOcc(n,t,w){ const g=G[n]; let inner=occlusal(n,t,true); if(g.mir) inner=`<g transform="translate(44,0) scale(-1,1)">${inner}</g>`; if(!g.up) inner=`<g transform="translate(0,44) scale(1,-1)">${inner}</g>`;
  return `<svg class="tsvg" viewBox="0 0 44 44" width="${w}" height="${w}" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`; }

/* ---------- макет 3: панорама (раскладка нынешней программы) ---------- */
const MID='<div class="mid"><b>Maxilar</b><i></i><b>Mandibular</b></div>';
function arcOff(i,count,lower){ const a=22, half=(count-1)/2, k=(i-half)/half; return (lower?a:-a)*(1-k*k); }
function panRow(list,lower,occ){
  const cells=list.map((n,i)=>{ const t=teeth[n]; const svg=occ?svgOcc(n,t,52):svgFrontal(n,t,38,true); const num=`<span class="num">${n}</span>`;
    const style=occ?` style="--arc:${arcOff(i,list.length,lower).toFixed(0)}px"`:'';
    return `<button type="button" class="tb${n===sel?' sel':''}" data-n="${n}"${style} aria-label="${esc(aria(n))}" title="${esc(title(n))}">${lower?svg+num:num+svg}</button>`; }).join('');
  const brs=bridges.filter(b=>b.teeth.every(([n])=>list.includes(n))).map(b=>{ const i0=list.indexOf(b.teeth[0][0]), i1=list.indexOf(b.teeth[b.teeth.length-1][0]);
    return `<div class="br${lower?' lo':''}" style="grid-column:${Math.min(i0,i1)+1} / ${Math.max(i0,i1)+2}" title="Punte ${b.teeth[0][0]}-${b.teeth[b.teeth.length-1][0]}"><span>${esc(b.material||'punte')}</span></div>`; }).join('');
  return `<div class="arch${occ?' occ':''}${lower?' lo':''}">${cells}${brs}</div>`;
}
function renderPanorama(){ return `<div class="pan"><div><h3>Vedere frontală</h3>${panRow(UPPER,false,false)}${MID}${panRow(LOWER,true,false)}</div>
<div><h3>Vedere ocluzală</h3>${panRow(UPPER,false,true)}${MID}${panRow(LOWER,true,true)}<p class="hint">Suprafața vestibulară este spre exteriorul arcadei; cea linguală/palatinală — spre mijloc.</p></div></div>`; }

/* ---------- макет 2: схема поверхностей (пятизонный квадрат) ---------- */
function schemaTooth(n,t,x,y){
  const g=G[n], st=effState(t), col=colOf(st), C=44, a=14, b=30;
  const top=`0,0 ${C},0 ${b},${a} ${a},${a}`, bottom=`0,${C} ${C},${C} ${b},${b} ${a},${b}`, left=`0,0 ${a},${a} ${a},${b} 0,${C}`, right=`${C},0 ${C},${C} ${b},${b} ${b},${a}`, center=`${a},${a} ${b},${a} ${b},${b} ${a},${b}`;
  const mesRight=!g.mir, vTop=g.up;
  const poly={V:vTop?top:bottom, L:vTop?bottom:top, M:mesRight?right:left, D:mesRight?left:right, O:center};
  const sf=sfMap(t), whole=(st==='carie'||st==='obturatie')&&!Object.keys(sf).length;
  const o=[`<g class="st${n===sel?' sel':''}" data-n="${n}" transform="translate(${x},${y})" tabindex="0" role="button" aria-label="${esc(aria(n))}"><title>${esc(title(n))}</title>`];
  for(const m of t.marks) o.push(`<rect x="-3" y="-3" width="${C+6}" height="${C+6}" rx="7" fill="none" stroke="${P.MARK_COLORS[m]}" stroke-width="3" opacity=".85"/>`);
  if(st==='lipsa'){
    o.push(`<rect x="0" y="0" width="${C}" height="${C}" rx="3" fill="none" stroke="var(--t-ghost)" stroke-width="1.6" stroke-dasharray="3 3"/>`);
    for(const L of SURF) o.push(`<polygon points="${poly[L]}" data-s="${L}" fill="transparent" stroke="none"/>`);
  } else {
    let base='var(--cell)', zl='var(--t-line)', box='var(--t-line)';
    if(st==='coroana'){base='url(#g-gold)';zl='#D97706';box='#D97706';}
    else if(st==='extras'){base='var(--f-extras)';zl='var(--t-soft)';box=col;}
    else if(st==='implant'){base='var(--f-implant)';zl='var(--t-soft)';box=col;}
    else if(whole){base=`var(--f-${st})`;zl=col;box=col;}
    else if(st==='carie'||st==='obturatie'){box=col;}
    for(const L of SURF){ const s=sf[L]; const f=s?P.MARK_FILL[s]:base; const sl=s?P.COLORS[s]:zl; o.push(`<polygon class="zone" points="${poly[L]}" data-s="${L}" fill="${f}" stroke="${sl}"/>`); }
    if(st==='implant') o.push(`<circle cx="22" cy="22" r="9" fill="var(--f-implant)" stroke="${col}" stroke-width="1.6" pointer-events="none"/><circle cx="22" cy="22" r="4" fill="none" stroke="${col}" stroke-width="1.4" pointer-events="none"/>`);
    if(st==='extras') o.push(`<path d="M 8 8 L 36 36 M 36 8 L 8 36" fill="none" stroke="${col}" stroke-width="3" stroke-linecap="round" pointer-events="none"/>`);
    o.push(`<rect class="box" x="0" y="0" width="${C}" height="${C}" rx="3" stroke="${box}" pointer-events="none"/>`);
  }
  if(n===sel) o.push(`<rect class="box" x="-1" y="-1" width="${C+2}" height="${C+2}" rx="4" pointer-events="none"/>`);
  o.push('</g>'); return o.join('');
}
function renderSchema(){
  const C=44, GAP=8, Q=22, M=12, W=M*2+16*C+15*GAP+Q, H=196;
  const xs=UPPER.map((_,i)=>M+i*(C+GAP)+(i>=8?Q:0));
  const yU=36, yL=112, mx=M+8*(C+GAP)-GAP/2+Q/2;
  let s=`<svg class="schema" viewBox="0 0 ${W} ${H}" role="img" aria-label="Schema suprafețelor MODVL: 32 de dinți, maxilar sus, mandibular jos">`;
  s+=`<line x1="${mx}" y1="14" x2="${mx}" y2="82" stroke="var(--line)" stroke-dasharray="2 4"/><line x1="${mx}" y1="110" x2="${mx}" y2="${H-14}" stroke="var(--line)" stroke-dasharray="2 4"/>`;
  s+=`<line x1="${M}" y1="95" x2="${W-M}" y2="95" stroke="var(--line)"/>`;
  s+=`<text x="${mx}" y="91" class="jaw">MAXILAR</text><text x="${mx}" y="107" class="jaw">MANDIBULAR</text>`;
  for(const b of bridges){ for(const [list,y0,y1,ty,up] of [[UPPER,18,13,9,true],[LOWER,176,181,192,false]]){ const ns=b.teeth.map(t=>t[0]); if(!ns.every(n=>list.includes(n))) continue;
      const x0=xs[Math.min(...ns.map(n=>list.indexOf(n)))]+3, x1=xs[Math.max(...ns.map(n=>list.indexOf(n)))]+C-3;
      s+=`<path d="M ${x0} ${y0} V ${y1} H ${x1} V ${y0}" fill="none" stroke="#D97706" stroke-width="2" stroke-linejoin="round"/><text x="${(x0+x1)/2}" y="${ty}" class="brl">punte · ${esc(b.material)}</text>`; } }
  UPPER.forEach((n,i)=>{ s+=`<text x="${xs[i]+C/2}" y="31" class="num${n===sel?' sel':''}" data-n="${n}">${n}</text>`+schemaTooth(n,teeth[n],xs[i],yU); });
  LOWER.forEach((n,i)=>{ s+=schemaTooth(n,teeth[n],xs[i],yL)+`<text x="${xs[i]+C/2}" y="172" class="num${n===sel?' sel':''}" data-n="${n}">${n}</text>`; });
  return s+'</svg>';
}

/* ---------- макет 1: анатомическая дуга (вид сверху, обе челюсти) ---------- */
function curve(A,D,apexY,dir){
  const N=720, pts=[], L=[0];
  for(let i=0;i<=N;i++){ const x=-A+2*A*i/N; pts.push([x,apexY+dir*D*x*x/(A*A)]); if(i) L.push(L[i-1]+Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1])); }
  const inside=[0,apexY+dir*D*0.45];
  return {total:L[N],
    at(s){ s=Math.max(0,Math.min(L[N],s)); let lo=0,hi=N; while(hi-lo>1){const m=(lo+hi)>>1; if(L[m]<=s) lo=m; else hi=m;}
      const t=(s-L[lo])/((L[hi]-L[lo])||1); const x=pts[lo][0]+(pts[hi][0]-pts[lo][0])*t, y=pts[lo][1]+(pts[hi][1]-pts[lo][1])*t;
      let tx=pts[hi][0]-pts[lo][0], ty=pts[hi][1]-pts[lo][1]; const nn=Math.hypot(tx,ty)||1; tx/=nn; ty/=nn; let nx=ty, ny=-tx;
      if(nx*(inside[0]-x)+ny*(inside[1]-y)>0){nx=-nx;ny=-ny;} return {x,y,tx,ty,nx,ny}; },
    path(s0,s1){ const out=[]; for(let s=s0;s<s1;s+=3){const p=this.at(s); out.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`);} const p=this.at(s1); out.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`); return 'M'+out.join(' L'); }};
}
function archRow(cv,list,lower){
  const GAP=2.4, ws=list.map(n=>2*G[n].occ.hw+GAP), sum=ws.reduce((a,b)=>a+b,0), sc=cv.total/sum;
  let acc=0; const place={}; list.forEach((n,i)=>{ const sm=(acc+ws[i]/2)*sc; acc+=ws[i]; place[n]={s:sm,p:cv.at(sm)}; });
  const depth=2*G[list[2]].occ.hd*sc; let out='';
  out+=`<path d="${cv.path(0,cv.total)}" fill="none" stroke="var(--band)" stroke-width="${(depth+10).toFixed(1)}" stroke-linecap="round"/>`;
  for(const b of bridges){ const ns=b.teeth.map(t=>t[0]); if(!ns.every(n=>list.includes(n))) continue;
    const s0=Math.min(...ns.map(n=>place[n].s)), s1=Math.max(...ns.map(n=>place[n].s));
    out+=`<path d="${cv.path(s0-8,s1+8)}" fill="none" stroke="#F59E0B" stroke-opacity=".28" stroke-width="${(depth*0.95).toFixed(1)}" stroke-linecap="butt"/>`;
    const pm=cv.at((s0+s1)/2), off=depth/2+14, lx=pm.x-pm.nx*off, ly=pm.y-pm.ny*off; out+=`<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" class="brl" text-anchor="${pm.x>0?'end':'start'}" dominant-baseline="central">punte · ${esc(b.material)}</text>`; }
  for(const n of list){ const {p}=place[n], t=teeth[n], k=q(n), mirror=(k===2||k===4);
    const th=Math.atan2(p.nx,-p.ny)*180/Math.PI;
    const tr=`translate(${p.x.toFixed(1)},${p.y.toFixed(1)}) rotate(${th.toFixed(1)}) scale(${sc.toFixed(3)})${mirror?' scale(-1,1)':''} translate(-22,-22)`;
    out+=`<g class="at${n===sel?' sel':''}" data-n="${n}" transform="${tr}" tabindex="0" role="button" aria-label="${esc(aria(n))}"><title>${esc(title(n))}</title>`;
    out+=n===sel?`<rect class="selbox" x="-2" y="-2" width="48" height="48" rx="9"/>`:`<rect class="focusbox" x="-2" y="-2" width="48" height="48" rx="9"/>`;
    out+=occlusal(n,t,true)+'</g>';
    const off=G[n].occ.hd*sc+13, lx=p.x+p.nx*off, ly=p.y+p.ny*off;
    out+=`<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" class="num${n===sel?' sel':''}" text-anchor="middle" dominant-baseline="central" data-n="${n}">${n}</text>`; }
  return out;
}
function renderArch(){
  const W=520, H=660, A=178, D=222, cx=W/2;
  const up=curve(A,D,64,1), lo=curve(A,D,H-64,-1);
  let s=`<svg class="archsvg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Arcada anatomică: maxilar sus, mandibular jos, dreapta pacientului în stânga"><g transform="translate(${cx},0)">`;
  s+=archRow(up,UPPER,false)+archRow(lo,LOWER,true);
  s+=`<text x="0" y="${(64+D*0.62).toFixed(0)}" class="jaw">MAXILAR</text><text x="0" y="${(H-64-D*0.62).toFixed(0)}" class="jaw">MANDIBULAR</text>`;
  s+=`<text x="${-A-4}" y="${H/2}" class="side" text-anchor="start" dominant-baseline="central">dreapta</text><text x="${A+4}" y="${H/2}" class="side" text-anchor="end" dominant-baseline="central">stânga</text>`;
  return s+'</g></svg>';
}

/* ---------- инспектор, легенда, сводка ---------- */
function renderInspector(){
  const n=sel, t=teeth[n], g=G[n], st=effState(t), up=g.up, br=bridgeOf(n), canSf=(st==='ok'||st==='carie'||st==='obturatie');
  let h=`<div class="ih"><span class="badge">${n}</span><div><b>${toothName(n)}</b><small>${jawSide(n)} · FDI ${n}</small></div></div>`;
  h+=`<div class="row"><span class="lbl">Stare</span><div class="pills">`+STATES.map(s=>`<button type="button" class="pill${s===st?' on':''}" data-state="${s}" aria-pressed="${s===st}"><i style="background:${s==='ok'?'var(--t-line)':P.COLORS[s]}"></i>${P.STATE_RO[s]}</button>`).join('')+`</div></div>`;
  h+=`<div class="row"><span class="lbl">Suprafețe</span><div class="chips">`+['O','V','L','M','D'].map(L=>{ const s=t.sf[L], letter=(L==='L'&&up)?'P':L, name=(L==='L'&&up)?'palatinal':SFNAME[L];
    return `<button type="button" class="chip${s?' on':''}" data-sf="${L}" aria-pressed="${!!s}"${canSf?'':' disabled'}><span class="code">${letter}</span><span class="cl">${name}</span>${s?`<span class="cs" style="color:${P.COLORS[s]}">${P.STATE_RO[s]}</span>`:''}</button>`; }).join('')+`</div>`+(canSf?'':`<p class="note">Suprafețele nu se marchează pe un dinte cu coroană, implant, extras sau lipsă.</p>`)+`</div>`;
  if(st==='implant') h+=`<p class="note">Implant: șurub de titan în os și coroană pe implant. În vederea 3D șurubul se vede prin gingie, cu inel violet la colet; „Rădăcini” îl arată în întregime.</p>`;
  const on=t.marks.includes('tratament');
  h+=`<div class="row"><span class="lbl">Marcaj</span><div class="pills"><button type="button" class="pill${on?' on':''}" data-mark="tratament" aria-pressed="${on}"><i style="background:${P.MARK_COLORS.tratament}"></i>${P.MARK_RO.tratament}</button></div></div>`;
  if(br) h+=`<div class="row"><span class="lbl">Punte</span><p class="brinfo">${br.teeth[0][0]}–${br.teeth[br.teeth.length-1][0]} · ${esc(br.material)} · rol: <b>${br.role==='stalp'?'stâlp':'corp de punte'}</b></p></div>`;
  h+=`<p class="note">Clic pe o suprafață din desen sau pe un chip: — → carie → obturație → —. Săgețile ← → ↑ ↓ trec la dintele vecin.</p>`;
  return h;
}
function renderLegend(){
  const st=STATES.filter(s=>s!=='ok').map(s=>`<span class="lg">${svgFrontal(36,{state:s,sf:{},marks:[]},20,false)}${P.STATE_RO[s]}</span>`).join('');
  document.getElementById('legend').innerHTML=st+`<span class="sep"></span><span class="lg">${svgFrontal(36,{state:'ok',sf:{},marks:['tratament']},20,false)}${P.MARK_RO.tratament}</span>`;
}
function renderSummary(){
  const c={}; let tr=0; for(const n of ALL){ const st=effState(teeth[n]); c[st]=(c[st]||0)+1; if(teeth[n].marks.length) tr++; }
  const parts=STATES.filter(s=>c[s]).map(s=>`<span><i style="background:${s==='ok'?'var(--t-line)':P.COLORS[s]}"></i>${P.STATE_RO[s]} ${c[s]}</span>`);
  if(tr) parts.push(`<span><i style="background:${P.MARK_COLORS.tratament}"></i>${P.MARK_RO.tratament} ${tr}</span>`);
  document.getElementById('sum').innerHTML=parts.join('');
}
function render(){ const c=document.getElementById('chart'); c.innerHTML=tpl==='arcada'?renderArch():tpl==='schema'?renderSchema():renderPanorama(); if(flashN!==null){ c.querySelectorAll(`[data-n="${flashN}"]`).forEach(el=>el.classList.add('flash')); flashN=null; } document.getElementById('insp').innerHTML=renderInspector(); renderSummary(); if(typeof paint3D==='function') paint3D(); }

/* ---------- действия ---------- */
function select(n){ sel=n; render(); }
function setState(n,s){ const t=teeth[n]; flashN=n; if(s==='ok'){t.state='ok';t.sf={};} else if(s==='carie'||s==='obturatie'){ for(const L in t.sf) t.sf[L]=s; t.state=s; } else {t.state=s;t.sf={};} render(); }
function cycleSf(n,L){ const t=teeth[n], st=effState(t); if(!(st==='ok'||st==='carie'||st==='obturatie')) return; const cur=t.sf[L];
  flashN=n; if(!cur) t.sf[L]='carie'; else if(cur==='carie') t.sf[L]='obturatie'; else delete t.sf[L];
  if(!Object.keys(t.sf).length) t.state='ok'; render(); }
function toggleMark(n,m){ const t=teeth[n]; flashN=n; const i=t.marks.indexOf(m); if(i>=0) t.marks.splice(i,1); else t.marks.push(m); render(); }
function neighbour(n,key){ for(const [up,lo] of [[UPPER,LOWER]]){ const iu=up.indexOf(n), il=lo.indexOf(n); const row=iu>=0?up:lo, i=iu>=0?iu:il;
  if(key==='ArrowLeft') return row[i-1]??null; if(key==='ArrowRight') return row[i+1]??null; if(key==='ArrowUp') return il>=0?up[i]:null; if(key==='ArrowDown') return iu>=0?lo[i]:null; } return null; }
const chart=document.getElementById('chart');
chart.addEventListener('click',e=>{ const s=e.target.closest('[data-s]'); const el=e.target.closest('[data-n]'); if(!el) return; const n=+el.dataset.n;
  if(s){ sel=n; cycleSf(n,s.dataset.s); } else select(n); });
chart.addEventListener('keydown',e=>{ const el=e.target.closest('[data-n]'); if(!el) return; if(e.key==='Enter'||e.key===' '){ e.preventDefault(); select(+el.dataset.n); } });
document.getElementById('insp').addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b||b.disabled) return;
  if(b.dataset.state) setState(sel,b.dataset.state); else if(b.dataset.sf) cycleSf(sel,b.dataset.sf); else if(b.dataset.mark) toggleMark(sel,b.dataset.mark); });
document.addEventListener('keydown',e=>{ if(!/^Arrow(Left|Right|Up|Down)$/.test(e.key)) return; const tg=e.target; if(tg&&/^(INPUT|TEXTAREA|SELECT)$/.test(tg.tagName)) return;
  const m=neighbour(sel,e.key); if(m===null) return; e.preventDefault(); select(m); const el=chart.querySelector(`[data-n="${m}"]`); if(el&&el.focus) el.focus({preventScroll:true}); });
document.getElementById('reset').addEventListener('click',()=>{ load(); sel=16; render(); });
const tabs=[...document.querySelectorAll('.tabs [role=tab]')];
function setTpl(v,save){ tpl=v; tabs.forEach(b=>b.setAttribute('aria-selected',String(b.dataset.tpl===v))); if(save){ try{localStorage.setItem('odo_tpl',v);}catch(_){} } render(); }
tabs.forEach(b=>b.addEventListener('click',()=>setTpl(b.dataset.tpl,true)));
let start='arcada'; const hash=(location.hash||'').slice(1); if(['arcada','schema','panorama'].includes(hash)) start=hash; else { try{ const v=localStorage.getItem('odo_tpl'); if(['arcada','schema','panorama'].includes(v)) start=v; }catch(_){} }
load(); renderLegend(); setTpl(start,false);
__JS3D__'''

page = HEAD.replace('__TITLE__', 'Одонтограмма 2D/3D' if MODE_3D else 'Одонтограмма DentPilot')
page = page.replace('__CSS3D__', CSS3D if MODE_3D else '')
script = ('<script>\nconst G=' + json.dumps({int(k): v for k, v in G.items()}, ensure_ascii=False, separators=(',', ':'))
          + ';\nconst P=' + json.dumps(P, ensure_ascii=False, separators=(',', ':')) + ';\n'
          + JS.replace('__JS3D__', JS3D if MODE_3D else '') + '</script>\n')
html = (page + DEFS + (BODY3D if MODE_3D else BODY)
        + (f"<script src='{THREE_URL}'></script>\n" if MODE_3D else '') + script)
assert '</script' not in json.dumps(G) and '</script' not in json.dumps(P)
if not ARTIFACT:
    # Артефакт claude.ai оборачивает тело сам; файлу в репозитории нужен полный документ.
    head_end = html.index('</style>') + len('</style>')
    html = ('<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
            + html[:head_end] + '\n</head>\n<body>\n' + html[head_end:] + '</body>\n</html>\n')
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)
print('wrote', OUT, len(html.encode('utf-8')), 'bytes')
