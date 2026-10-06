import type { ToothGeom } from '../chart'
import type { RawMesh } from './mesh'
import { reliefFn, SURF, toCls, type Cls, type Letter } from './toothGeometry'

/* Коронка зуба для 3D (06.10, «ближе к натуральной» — слово Олега по кадрам
   до/после: «нравится»). Сечение коронки на каждой высоте — суперэллипс с
   ЧЕТЫРЬМЯ полуосями (мезиально/дистально, щёчно/язычно) и своей
   «квадратностью» у щёчной и язычной половин:
   - щёчная выпуклость — в пришеечной трети, язычная — в средней, резец к
     режущему краю сужается лопаткой, а не равномерно;
   - углы резца скруглены (дистальный сильнее мезиального), клык сходится в
     бугор со смещением к мезиальной стороне, у моляра щёчная борозда между
     буграми видна сбоку;
   - цвет вершины: у шейки теплее, у режущего края резца серо-голубой, в
     фиссурах жевательной поверхности темнее.
   Размеры — `md`, `bl`, `crown` с сервера; форма — рендер (решение 2 B7).
   ⭐ `surf(θ, h)` — ТА ЖЕ стенка для десны (`gum.ts`): край десны садится на
   зуб ровно там, где его стенка. Меняешь форму сечения — меняется и край; две
   разные формулы дали бы щель между десной и зубом. */

type Key = readonly [number, number, number, number, number, number, number]
// [t, aM, aD, bB, bL, sqB, sqL] — доли половин md и bl по высоте коронки

const UPPER_CENTRAL: Key[] = [
  [0.00, 0.72, 0.72, 0.80, 0.80, 2.2, 2.0],
  [0.12, 0.80, 0.80, 0.95, 0.90, 2.3, 2.0],
  [0.30, 0.92, 0.91, 1.00, 0.86, 2.5, 2.1],
  [0.55, 1.00, 0.98, 0.86, 0.58, 2.7, 2.2],
  [0.78, 1.00, 0.96, 0.58, 0.32, 2.9, 2.3],
  [0.92, 0.97, 0.90, 0.34, 0.18, 3.0, 2.4],
  [1.00, 0.88, 0.76, 0.17, 0.10, 3.0, 2.4],
]
const UPPER_LATERAL: Key[] = [
  [0.00, 0.70, 0.70, 0.80, 0.80, 2.2, 2.0],
  [0.12, 0.79, 0.79, 0.95, 0.90, 2.3, 2.0],
  [0.32, 0.92, 0.90, 1.00, 0.84, 2.4, 2.1],
  [0.58, 1.00, 0.96, 0.84, 0.56, 2.6, 2.2],
  [0.80, 0.98, 0.92, 0.56, 0.32, 2.7, 2.3],
  [0.93, 0.90, 0.80, 0.32, 0.18, 2.8, 2.3],
  [1.00, 0.78, 0.62, 0.16, 0.10, 2.8, 2.3],
]
const LOWER_INCISOR: Key[] = [
  [0.00, 0.74, 0.74, 0.86, 0.86, 2.2, 2.1],
  [0.15, 0.84, 0.84, 1.00, 0.96, 2.3, 2.1],
  [0.40, 0.95, 0.95, 0.94, 0.82, 2.5, 2.2],
  [0.65, 1.00, 1.00, 0.74, 0.58, 2.7, 2.3],
  [0.85, 1.00, 0.98, 0.48, 0.34, 2.8, 2.4],
  [0.95, 0.96, 0.92, 0.28, 0.18, 2.8, 2.4],
  [1.00, 0.90, 0.86, 0.15, 0.10, 2.8, 2.4],
]
const CANINE: Key[] = [
  [0.00, 0.72, 0.72, 0.84, 0.84, 2.2, 2.1],
  [0.18, 0.86, 0.86, 1.00, 0.96, 2.3, 2.1],
  [0.42, 0.98, 0.97, 0.98, 0.88, 2.4, 2.2],
  [0.62, 1.00, 0.97, 0.86, 0.74, 2.4, 2.2],
  [0.78, 0.84, 0.92, 0.66, 0.54, 2.3, 2.2],
  [0.90, 0.52, 0.64, 0.44, 0.34, 2.2, 2.1],
  [0.97, 0.20, 0.26, 0.20, 0.15, 2.0, 2.0],
  [1.00, 0.06, 0.08, 0.06, 0.05, 2.0, 2.0],
]
const PREMOLAR: Key[] = [
  [0.00, 0.78, 0.78, 0.80, 0.80, 2.4, 2.3],
  [0.20, 0.90, 0.90, 1.00, 0.92, 2.6, 2.4],
  [0.45, 1.00, 1.00, 0.98, 0.98, 2.7, 2.6],
  [0.75, 0.98, 0.98, 0.90, 0.88, 2.7, 2.6],
  [1.00, 0.86, 0.86, 0.76, 0.70, 2.6, 2.5],
]
const MOLAR: Key[] = [
  [0.00, 0.80, 0.80, 0.80, 0.80, 2.8, 2.7],
  [0.18, 0.94, 0.94, 1.00, 0.93, 3.1, 3.0],
  [0.42, 1.00, 1.00, 0.97, 1.00, 3.3, 3.2],
  [0.72, 0.99, 0.99, 0.90, 0.93, 3.2, 3.1],
  [1.00, 0.92, 0.92, 0.80, 0.82, 3.0, 2.9],
]

function keysOf(cls: Cls, upper: boolean): Key[] {
  if (cls === 'incisor_c') return upper ? UPPER_CENTRAL : LOWER_INCISOR
  if (cls === 'incisor_l') return upper ? UPPER_LATERAL : LOWER_INCISOR
  if (cls === 'canine') return CANINE
  if (cls === 'premolar') return PREMOLAR
  return MOLAR
}

export interface Section { aM: number; aD: number; bB: number; bL: number; sqB: number; sqL: number }

const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v))
const smooth = (e0: number, e1: number, x: number): number => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1)
  return t * t * (3 - 2 * t)
}

/** Сечение на высоте t — Катмулл–Ром по опорным строкам (как `profAt`). */
export function sectionAt(keys: Key[], t: number): Section {
  const n = keys.length
  let i = 1
  while (i < n - 1 && t > (keys[i]?.[0] ?? 1)) i++
  const k1 = keys[i - 1] ?? keys[0] as Key
  const k2 = keys[i] ?? k1
  const k0 = keys[i - 2] ?? k1
  const k3 = keys[i + 1] ?? k2
  const span = k2[0] - k1[0]
  const u = span > 0 ? clamp((t - k1[0]) / span, 0, 1) : 0
  const u2 = u * u
  const u3 = u2 * u
  const cr = (c: number): number =>
    0.5 * (2 * (k1[c] ?? 0) + (-(k0[c] ?? 0) + (k2[c] ?? 0)) * u
      + (2 * (k0[c] ?? 0) - 5 * (k1[c] ?? 0) + 4 * (k2[c] ?? 0) - (k3[c] ?? 0)) * u2
      + (-(k0[c] ?? 0) + 3 * (k1[c] ?? 0) - 3 * (k2[c] ?? 0) + (k3[c] ?? 0)) * u3)
  return { aM: cr(1), aD: cr(2), bB: cr(3), bL: cr(4), sqB: cr(5), sqL: cr(6) }
}

/** Угол в (−π, π] между двумя направлениями. */
const angDiff = (a: number, b: number): number => {
  let d = (a - b) % (2 * Math.PI)
  if (d > Math.PI) d -= 2 * Math.PI
  if (d <= -Math.PI) d += 2 * Math.PI
  return d
}

/** Рельеф стенки: борозды моляра, щёчный валик клыка и премоляра — радиальный множитель. */
function wallMod(cls: Cls, upper: boolean): (th: number, t: number) => number {
  const B = Math.PI / 2
  const g = (th: number, c: number, s: number): number => Math.exp(-0.5 * (angDiff(th, c) / s) ** 2)
  if (cls === 'molar') {
    return upper
      ? (th, t) => 1 - smooth(0.38, 0.82, t) * (0.07 * g(th, B, 0.14) + 0.045 * g(th, -B - 0.15, 0.14))
      : (th, t) => 1 - smooth(0.38, 0.82, t) * (0.05 * g(th, B + 0.3, 0.12) + 0.045 * g(th, B - 0.35, 0.12) + 0.035 * g(th, -B, 0.14))
  }
  if (cls === 'canine') return (th, t) => 1 + 0.055 * g(th, B, 0.42) * smooth(0.12, 0.6, t) * (1 - smooth(0.82, 1, t))
  if (cls === 'premolar') return (th, t) => 1 + 0.03 * g(th, B, 0.4) * smooth(0.2, 0.8, t)
  return () => 1
}

/** sRGB-доля → линейная: цвета вершин three читает линейными. */
const lin = (c: number): number => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
const CERV = [0.95, 0.86, 0.72].map(lin)
const EDGE = [0.9, 0.92, 0.95].map(lin)
const FOSSA = [0.80, 0.75, 0.66].map(lin)
const mix3 = (a: number[], b: number[], k: number): number[] => a.map((v, i) => v + ((b[i] ?? v) - v) * k)

export type CrownInput = Pick<ToothGeom, 'md' | 'bl' | 'crown' | 'cls' | 'upper'>

export interface CrownModel {
  mesh: RawMesh
  /** самая высокая точка коронки над шейкой, мм — по ней ровняется окклюзионная плоскость */
  tip: number
  /** сечение шейки (t = 0) — корень продолжает его */
  neck: (th: number) => [number, number]
  /** поверхность зуба (x, z) на высоте h мм над шейкой; h < 0 — корень */
  surf: (th: number, h: number) => [number, number]
  /** контур шейки из n точек — пунктир пустого места */
  outline: (n: number) => [number, number][]
}

export function crownModel(g: CrownInput): CrownModel {
  const cls = toCls(g.cls)
  const hmd = g.md / 2
  const hbl = g.bl / 2
  const H = g.crown
  const keys = keysOf(cls, g.upper)
  const mod = wallMod(cls, g.upper)
  const relief = reliefFn(cls, g.upper)
  const reliefK = cls === 'canine' ? 0 : 1
  const rimK = cls === 'molar' || cls === 'premolar' ? 0.62 : 0
  // бугор клыка чуть мезиальнее середины
  const ox = (t: number): number => (cls === 'canine' ? -0.07 * hmd * smooth(0.55, 1, t) : 0)

  const wall = (th: number, t: number): [number, number] => {
    const s = sectionAt(keys, t)
    const c = Math.cos(th)
    const sn = Math.sin(th)
    const sq = sn >= 0 ? s.sqB : s.sqL
    const p = 2 / sq
    const a = (c < 0 ? s.aM : s.aD) * hmd
    const b = (sn >= 0 ? s.bB : s.bL) * hbl
    const k = mod(th, t)
    const x = Math.sign(c) * Math.pow(Math.abs(c), p) * a * k
    const z = Math.sign(sn) * Math.pow(Math.abs(sn), p) * b * k
    return [x + ox(t), z]
  }
  const neck = (th: number): [number, number] => wall(th, 0)
  const surf = (th: number, h: number): [number, number] => {
    if (h >= 0) return wall(th, Math.min(h / H, 0.6))
    const d = -h
    const w = d <= 2.4 ? 1 - 0.14 * smooth(0, 2.4, d) : Math.max(0.7, 0.86 - 0.03 * (d - 2.4))
    const [x, z] = neck(th)
    return [x * w, z * w]
  }

  const TH = 72
  const ROWS = 26
  const RINGS = 10
  const pos: number[] = []
  const col: number[] = []
  const front = cls === 'incisor_c' || cls === 'incisor_l' || cls === 'canine'
  const shade = (t: number): number[] => {
    let c = mix3(CERV, [1, 1, 1], smooth(0.0, 0.42, t))
    if (front) c = mix3(c, EDGE, smooth(0.72, 1, t) * 0.85)
    if (cls === 'canine') c = mix3(c, CERV, 0.25)
    return c
  }
  const ridge = (th: number): number => {
    const [x, z] = wall(th, 1)
    return relief(x / hmd, z / hbl) * rimK
  }
  for (let r = 0; r <= ROWS; r++) {
    const t = r / ROWS
    const lift = smooth(0.72, 1, t)
    const c = shade(t)
    for (let j = 0; j < TH; j++) {
      const th = (2 * Math.PI * j) / TH
      const [x, z] = wall(th, t)
      pos.push(x, t * H + (rimK ? ridge(th) * lift : 0), z)
      col.push(c[0] ?? 1, c[1] ?? 1, c[2] ?? 1)
    }
  }
  // жевательная площадка / режущий край: кольца к центру
  let rmax = 0.001
  for (let a = -1; a <= 1; a += 0.1) for (let b = -1; b <= 1; b += 0.1) rmax = Math.max(rmax, relief(a, b))
  const ringStart: number[] = [ROWS * TH]
  const top = shade(1)
  const cx = ox(1)
  for (let k = 1; k <= RINGS; k++) {
    const s = 1 - k / RINGS
    ringStart.push(pos.length / 3)
    const fade = 1 - smooth(0.7, 1, s)
    if (k === RINGS) {
      const rl = relief(0, 0) * reliefK
      pos.push(cx, H + rl, 0)
      const c = mix3(top, FOSSA, reliefK && rimK ? smooth(0.5, 0.95, 1 - rl / rmax) * 0.85 : 0)
      col.push(c[0] ?? 1, c[1] ?? 1, c[2] ?? 1)
      break
    }
    for (let j = 0; j < TH; j++) {
      const th = (2 * Math.PI * j) / TH
      const [rx, rz] = wall(th, 1)
      const x = cx + (rx - cx) * s
      const z = rz * s
      const rl = relief(x / hmd, z / hbl) * reliefK
      pos.push(x, H + rl * fade + (rimK ? ridge(th) : 0) * (1 - fade), z)
      const deep = reliefK && rimK ? smooth(0.5, 0.95, 1 - rl / rmax) * fade * 0.85 : 0
      const c = mix3(top, FOSSA, deep)
      col.push(c[0] ?? 1, c[1] ?? 1, c[2] ?? 1)
    }
  }

  const B: Record<Letter, number[]> = { O: [], V: [], L: [], M: [], D: [] }
  const step = 360 / TH
  const sector = (deg: number): Letter => {
    let d = deg % 360
    if (d < -30) d += 360
    if (d >= 330) d -= 360
    if (d >= -30 && d < 30) return 'D'
    if (d < 150) return 'V'
    if (d < 210) return 'M'
    return 'L'
  }
  for (let r = 0; r < ROWS; r++) {
    for (let j = 0; j < TH; j++) {
      const jn = (j + 1) % TH
      const a = r * TH + j
      const b = r * TH + jn
      const c = (r + 1) * TH + jn
      const d = (r + 1) * TH + j
      B[sector((j + 0.5) * step)].push(a, c, b, a, d, c)
    }
  }
  for (let k = 0; k < RINGS; k++) {
    const o = ringStart[k] ?? 0
    const i = ringStart[k + 1] ?? 0
    if (k === RINGS - 1) {
      for (let j = 0; j < TH; j++) {
        const jn = (j + 1) % TH
        B.O.push(o + j, i, o + jn)
      }
    } else {
      for (let j = 0; j < TH; j++) {
        const jn = (j + 1) % TH
        B.O.push(o + j, i + j, i + jn, o + j, i + jn, o + jn)
      }
    }
  }
  const index: number[] = []
  const groups = SURF.map((L, slot) => {
    const start = index.length
    for (const v of B[L]) index.push(v)
    return { start, count: B[L].length, materialIndex: slot }
  })
  let tip = 0
  for (let i = 1; i < pos.length; i += 3) tip = Math.max(tip, pos[i] ?? 0)
  const outline = (n: number): [number, number][] => Array.from({ length: n }, (_v, j) => neck((2 * Math.PI * j) / n))
  return { mesh: { positions: pos, index, groups, colors: col }, tip, neck, surf, outline }
}
