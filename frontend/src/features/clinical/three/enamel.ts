import type * as T3 from 'three'
import { COLOR, FINISH, type Finish } from './look'
import type { Cls } from './toothGeometry'

/* Живая эмаль в шейдере коронки (волна 3, 25.10; разведка 24.10 —
   `review/odonto-models-2026-10.md` § B, слово Олега: «режущий край и граница
   эмали — косметика, заметная вблизи»). Два эффекта:
   - полупрозрачный режущий край резцов и клыков: серо-голубая зона у края,
     три доли мамелонов врезаются в неё с губной стороны, светлый ободок по
     самому краю;
   - линия эмаль–цемент: волной, на контактных сторонах выше губной; ниже неё
     тон и отделка цемента — те же, что у корня (`COLOR.dentin`, `FINISH.dentin`):
     открытая рецессией шейка и корень читаются одной поверхностью.
   Ни текстуры, ни байта в `teeth.js`, геометрия не меняется: десна садится на
   `crown.surf`, как раньше, линия — только цвет и отделка. Считается по
   координатам зуба: y — ось от шейки, +z — губная/щёчная сторона, +x — D,
   −x — M (как у таблицы `sculpt.ts` и формулы `crown.ts`).
   Только у ЖИВОЙ эмали: доля `Finish.natural` (1 у эмали, 0 у пломбы, кариеса,
   коронки, циркония) едет в шейдер со своего материала, твин отделки ведёт её
   сам — цвет поверхности с находкой (палитра сервера) край и линия не трогают.
   Модуль three не импортирует (только типы): числа проверяет vitest. */

/** Подъём линии эмаль–цемент на контактных сторонах над губной, мм (учебник:
 *  резец 3–3,5, клык 2,5, премоляр ~1, моляр ~0,5–1). У губной и язычной
 *  стороны линия — на шейке (y = 0). ⛔ Ниже здорового края десны всюду
 *  (`enamel.test` против `gum.anchorsFor`): цемент виден только при рецессии. */
export const CEJ_RISE: Record<Cls, number> = { incisor_c: 3.0, incisor_l: 2.6, canine: 2.3, premolar: 1.3, molar: 0.7 }
/** острота волны: подъём ∝ |cos θ|^CEJ_POW — узкий пик у контакта, полого у губы */
export const CEJ_POW = 2
/** полуширина перехода эмаль → цемент, мм */
const CEJ_SOFT = 0.05

/** Высота линии эмаль–цемент над шейкой под углом θ (0 — D, π/2 — губная сторона), мм. */
export function cejHeight(cls: Cls, th: number): number {
  return CEJ_RISE[cls] * Math.pow(Math.abs(Math.cos(th)), CEJ_POW)
}

/** Режущий край. Расстояния — от вершины коронки вниз, мм. */
export const EDGE = {
  /** полупрозрачная зона у края */
  zone: 1.9,
  /** на сколько мамелон (опак дентина) врезается в зону */
  lobe: 0.45,
  /** ширина перехода зоны */
  soft: 1.1,
  /** доли мамелонов на губной стороне, град, и их полуширина */
  lobes: [55, 90, 125],
  lobeW: 14,
  /** светлый ободок по самому краю: от, до, сила */
  rim: [0.08, 0.32],
  rimK: 0.8,
  /** цвет зоны и ободка (sRGB) — множитель к эмали, как у цвета вершин */
  trans: [0.6, 0.65, 0.75],
  halo: [0.97, 0.965, 0.94],
} as const

/** Сила края: центральные резцы сильнее боковых, клык слабо, жевательные — нет;
 *  у нижних край тоньше (×0,6). */
export function edgeStrength(cls: Cls, upper: boolean): number {
  const k = cls === 'incisor_c' ? 0.8 : cls === 'incisor_l' ? 0.72 : cls === 'canine' ? 0.4 : 0
  return k * (upper ? 1 : 0.6)
}

const lin = (c: number): number => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
const linHex = (h: number): number[] => [(h >> 16) & 0xff, (h >> 8) & 0xff, h & 0xff].map((v) => lin(v / 255))

/** Цвета шейдера (линейные): зона и ободок — эмаль × множитель края; цемент —
 *  отношение дентина корня к эмали (умножается на цвет вершин коронки). */
export function enamelColors(): { trans: number[]; halo: number[]; cement: number[] } {
  const e = linHex(COLOR.enamel)
  const d = linHex(COLOR.dentin)
  return {
    trans: EDGE.trans.map((v, i) => (e[i] ?? 1) * lin(v)),
    halo: EDGE.halo.map((v, i) => (e[i] ?? 1) * lin(v)),
    cement: d.map((v, i) => v / (e[i] ?? 1)),
  }
}

/** Параметры зуба для шейдера: вершина коронки (мм от шейки), сила края, подъём линии. */
export interface EnamelTooth { tip: number; edge: number; cej: number }

export function enamelTooth(cls: Cls, upper: boolean, tip: number): EnamelTooth {
  return { tip, edge: edgeStrength(cls, upper), cej: CEJ_RISE[cls] }
}

const f = (v: number): string => (Number.isInteger(v) ? v.toFixed(1) : String(v))
const v3 = (a: readonly number[]): string => `vec3(${a.map((x) => f(Number(x.toFixed(5)))).join(', ')})`

/** Куски, которые патч ищет в шейдере `MeshPhysicalMaterial`. ⛔ Не нашёлся —
 *  `replace` молча ничего не делает, и эффекта нет без единой ошибки: держит
 *  `enamel.test` › «каждая точка подмены есть в шейдере three». */
export const HOOKS = {
  vCommon: '#include <common>',
  vBegin: '#include <begin_vertex>',
  fCommon: '#include <common>',
  fColor: '#include <color_fragment>',
  fRough: '#include <roughnessmap_fragment>',
  fLights: '#include <lights_physical_fragment>',
} as const

/* Что зависит только от УГЛА вокруг оси зуба — высота линии эмаль–цемент и
   доли мамелонов — считается на вершине: обе гладкие по углу (cos², гауссы
   шириной 14° против шага сетки 3,75°), интерполяция их не портит, а
   atan/pow/exp на каждом пикселе коронки стоили +1,4 мс кадра на Intel UHD
   при холсте 2061×1015. Во фрагментном — только высота и смешения. */
function vertHead(): string {
  return `
varying float vDpY;
varying float vDpCej;
varying float vDpLobe;
uniform float uDpCej;
float dpLobe(float deg, float c) { float x = (deg - c) / ${f(EDGE.lobeW)}; return exp(-x * x); }
`
}

function vertBody(): string {
  const [l0, l1, l2] = EDGE.lobes
  return `
  {
    float dpTh = atan(position.z, position.x);
    vDpY = position.y;
    // линия эмаль–цемент (та же формула, что cejHeight)
    vDpCej = uDpCej * pow(abs(cos(dpTh)), ${f(CEJ_POW)});
    float dpDeg = degrees(dpTh);
    vDpLobe = sin(dpTh) > 0.3 ? max(max(dpLobe(dpDeg, ${f(l0)}), dpLobe(dpDeg, ${f(l1)})), dpLobe(dpDeg, ${f(l2)})) : 0.3;
  }`
}

function fragHead(): string {
  const c = enamelColors()
  return `
varying float vDpY;
varying float vDpCej;
varying float vDpLobe;
uniform float uDpTip;
uniform float uDpEdge;
uniform float uDpNatural;
const vec3 DP_TRANS = ${v3(c.trans)};
const vec3 DP_HALO = ${v3(c.halo)};
const vec3 DP_CEMENT = ${v3(c.cement)};
`
}

function fragColor(): string {
  return `
  float dpCe = 0.0;
  if (uDpNatural > 0.001) {
    dpCe = (1.0 - smoothstep(vDpCej - ${f(CEJ_SOFT)}, vDpCej + ${f(CEJ_SOFT)}, vDpY)) * uDpNatural;
    if (uDpEdge > 0.0) {
      float dpD = uDpTip - vDpY;
      float dpD0 = ${f(EDGE.zone)} - ${f(EDGE.lobe)} * vDpLobe;
      float dpTr = (1.0 - smoothstep(dpD0 - ${f(EDGE.soft)}, dpD0, dpD)) * uDpEdge * uDpNatural;
      diffuseColor.rgb = mix(diffuseColor.rgb, DP_TRANS, dpTr);
      float dpRim = (1.0 - smoothstep(${f(EDGE.rim[0])}, ${f(EDGE.rim[1])}, dpD)) * ${f(EDGE.rimK)} * uDpEdge * uDpNatural;
      diffuseColor.rgb = mix(diffuseColor.rgb, DP_HALO, dpRim);
    }
    diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * DP_CEMENT, dpCe);
  }`
}

/** Патч шейдера — чистая работа со строками: что подменилось и чего не нашлось. */
export function patchEnamelShader(vs: string, fs: string, cement: Pick<Finish, 'roughness' | 'clearcoat'> = FINISH.dentin): {
  vs: string; fs: string; missing: string[]
} {
  const missing: string[] = []
  const put = (src: string, key: keyof typeof HOOKS, add: string): string => {
    const hook = HOOKS[key]
    if (!src.includes(hook)) {
      missing.push(key)
      return src
    }
    return src.replace(hook, `${hook}\n${add}`)
  }
  let v = put(vs, 'vCommon', vertHead())
  v = put(v, 'vBegin', vertBody())
  let g = put(fs, 'fCommon', fragHead())
  g = put(g, 'fColor', fragColor())
  // ниже линии — отделка цемента (корня): матовее, без лака
  g = put(g, 'fRough', `roughnessFactor = mix(roughnessFactor, ${f(cement.roughness)}, dpCe);`)
  g = put(g, 'fLights', `#ifdef USE_CLEARCOAT\n  material.clearcoat = mix(material.clearcoat, ${f(cement.clearcoat)}, dpCe);\n#endif`)
  return { vs: v, fs: g, missing }
}

/** Материал коронки: `MeshPhysicalMaterial` плюс доля живой эмали (её ставит
 *  `look.setFinish`, как остальную отделку). */
export type EnamelMaterial = T3.MeshPhysicalMaterial & { natural: number }

/** Подключить живую эмаль к материалу коронки. Программа шейдера одна на все
 *  коронки (ключ кэша общий), числа зуба — в uniform'ах, доля `natural` читается
 *  с материала на каждом кадре (геттер), поэтому твин отделки ведёт и её. */
export function attachEnamel(m: EnamelMaterial, t: EnamelTooth): void {
  m.onBeforeCompile = (sh) => {
    const p = patchEnamelShader(sh.vertexShader, sh.fragmentShader)
    sh.vertexShader = p.vs
    sh.fragmentShader = p.fs
    sh.uniforms['uDpTip'] = { value: t.tip }
    sh.uniforms['uDpEdge'] = { value: t.edge }
    sh.uniforms['uDpCej'] = { value: t.cej }
    sh.uniforms['uDpNatural'] = { get value() { return m.natural } }
  }
  m.customProgramCacheKey = () => 'dp-enamel'
}
