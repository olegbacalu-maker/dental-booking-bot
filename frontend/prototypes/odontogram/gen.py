#!/usr/bin/env python3
"""Макет раскладок одонтограммы: три раскладки на ЗУБАХ ДВИЖКА.

Геометрия (коронки, корни, фиссуры, дольки, зоны поверхностей) и палитра
состояний берутся из bot/app/teeth_svg.py и кладутся в страницу как данные;
раскладки и интерактив живут в самой странице. Запуск из любого каталога:

    python frontend/prototypes/odontogram/gen.py            # → index.html
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
OUT = os.path.join(HERE, 'odontogram.html' if ARTIFACT else 'index.html')
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

HEAD = r'''<title>Одонтограмма DentPilot</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>
:root{
  --bg:#f4f6f8;--panel:#ffffff;--line:#dde3e8;--line-2:#edf1f4;--text:#17242c;--text-2:#4a5a64;--text-3:#66747e;
  --accent:#0f7b8a;--accent-soft:#e4f2f4;--on-accent:#ffffff;--band:#eef2f5;--cell:#ffffff;--gold-text:#B45309;
  --t-line:#64748B;--t-soft:#94A3B8;--t-ghost:#CBD5E1;--f-extras:#E2E8F0;--f-carie:#FEF2F2;--f-obturatie:#EFF6FF;--f-coroana:#FFF7ED;--f-implant:#F5F3FF;
  --shadow:0 1px 2px rgba(23,36,44,.05),0 10px 28px rgba(23,36,44,.06);
  --r-card:14px;--r-ctl:9px;--r-sm:6px;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){color-scheme:dark;
    --bg:#10181c;--panel:#17202a;--line:#2a363d;--line-2:#212c34;--text:#eef3f5;--text-2:#b3c2ca;--text-3:#93a5ae;
    --accent:#35a7b8;--accent-soft:#14333a;--on-accent:#04181c;--band:#1e2a31;--cell:#1b262e;--gold-text:#F5B453;
    --t-line:#9AA8BA;--t-soft:#7C8AA0;--t-ghost:#4B5A6B;--f-extras:#3A4756;--f-carie:#3A2224;--f-obturatie:#1E2C44;--f-coroana:#3A2C14;--f-implant:#2B2547;
    --shadow:none}
}
:root[data-theme="dark"]{color-scheme:dark;
  --bg:#10181c;--panel:#17202a;--line:#2a363d;--line-2:#212c34;--text:#eef3f5;--text-2:#b3c2ca;--text-3:#93a5ae;
  --accent:#35a7b8;--accent-soft:#14333a;--on-accent:#04181c;--band:#1e2a31;--cell:#1b262e;--gold-text:#F5B453;
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
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style>
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
function render(){ const c=document.getElementById('chart'); c.innerHTML=tpl==='arcada'?renderArch():tpl==='schema'?renderSchema():renderPanorama(); document.getElementById('insp').innerHTML=renderInspector(); renderSummary(); }

/* ---------- действия ---------- */
function select(n){ sel=n; render(); }
function setState(n,s){ const t=teeth[n]; if(s==='ok'){t.state='ok';t.sf={};} else if(s==='carie'||s==='obturatie'){ for(const L in t.sf) t.sf[L]=s; t.state=s; } else {t.state=s;t.sf={};} render(); }
function cycleSf(n,L){ const t=teeth[n], st=effState(t); if(!(st==='ok'||st==='carie'||st==='obturatie')) return; const cur=t.sf[L];
  if(!cur) t.sf[L]='carie'; else if(cur==='carie') t.sf[L]='obturatie'; else delete t.sf[L];
  if(!Object.keys(t.sf).length) t.state='ok'; render(); }
function toggleMark(n,m){ const t=teeth[n]; const i=t.marks.indexOf(m); if(i>=0) t.marks.splice(i,1); else t.marks.push(m); render(); }
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
'''

html = HEAD + DEFS + BODY + '<script>\nconst G=' + json.dumps({int(k): v for k, v in G.items()}, ensure_ascii=False, separators=(',', ':')) + ';\nconst P=' + json.dumps(P, ensure_ascii=False, separators=(',', ':')) + ';\n' + JS + '</script>\n'
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
