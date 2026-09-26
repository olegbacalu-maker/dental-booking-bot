import type { ToothGeom } from '../chart'
import { lathe, oneGroup, type RawMesh } from './mesh'

/* Форма зуба (B7, ступень 3) — перенос блока `JS3D` макета
   `frontend/prototypes/odontogram/gen.py` и метода прототипа `dental3d`:
   суперэллипс в поперечнике, профиль по высоте сплайном Катмулла–Рома, бугры
   гауссианами, борозды вычитанием; корни — эллиптические конусы с дистальным
   наклоном; винт импланта — тело вращения. Размеры (`md`, `bl`, `crown`,
   `root`, `roots`, `cls`, `upper`) приходят С СЕРВЕРА (`teeth_svg.tooth_geom`),
   здесь только форма — контракт clinical-chart.md › «3D — рендер, не истина».

   Канон прототипа dental3d: +x дистально, −x мезиально, +z щёчно,
   +y окклюзионно, шейка y = 0. Пять групп треугольников коронки = пять
   материалов = пять поверхностей в порядке `SURF`. */

export const SURF = ['O', 'V', 'L', 'M', 'D'] as const
export type Letter = (typeof SURF)[number]

export type Cls = 'incisor_c' | 'incisor_l' | 'canine' | 'premolar' | 'molar'
const CLASSES: readonly Cls[] = ['incisor_c', 'incisor_l', 'canine', 'premolar', 'molar']

/** Класс с сервера — строка; незнакомая рисуется моляром (форма, не диагноз). */
export function toCls(s: string): Cls {
  return (CLASSES as readonly string[]).includes(s) ? (s as Cls) : 'molar'
}

/** «Квадратность» поперечника: 2 — эллипс, больше — прямоугольнее. */
const SQUARE: Record<Cls, number> = { incisor_c: 2.4, incisor_l: 2.4, canine: 2.2, premolar: 2.6, molar: 3.2 }

/** Профиль по высоте: [t от шейки к режущему краю, доля md, доля bl]. */
type Prof = [number, number, number][]
const PROF: Record<'molar' | 'premolar' | 'canine' | 'incisor', Prof> = {
  molar: [[0, 0.80, 0.80], [0.16, 0.92, 0.92], [0.34, 1, 1], [0.62, 0.99, 0.99], [0.86, 0.95, 0.95], [1, 0.90, 0.90]],
  premolar: [[0, 0.80, 0.80], [0.16, 0.92, 0.92], [0.34, 1, 1], [0.62, 0.98, 0.98], [0.86, 0.92, 0.92], [1, 0.86, 0.86]],
  canine: [[0, 0.80, 0.85], [0.2, 0.95, 1], [0.45, 1, 0.95], [0.7, 0.9, 0.7], [0.88, 0.65, 0.42], [1, 0.30, 0.16]],
  incisor: [[0, 0.78, 0.85], [0.2, 0.9, 1], [0.45, 1, 0.9], [0.7, 1.02, 0.62], [0.88, 1, 0.36], [1, 0.96, 0.14]],
}
const profOf = (cls: Cls): Prof => PROF[cls === 'incisor_c' || cls === 'incisor_l' ? 'incisor' : cls]

const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v))
const smooth = (e0: number, e1: number, x: number): number => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1)
  return t * t * (3 - 2 * t)
}

/** Доли md и bl на высоте t — сплайн Катмулла–Рома по опорным точкам профиля. */
export function profAt(prof: Prof, t: number): [number, number] {
  const n = prof.length
  let i = 1
  while (i < n - 1 && t > (prof[i]?.[0] ?? 1)) i++
  const p1 = prof[i - 1] ?? prof[0] ?? [0, 1, 1]
  const p2 = prof[i] ?? p1
  const p0 = prof[i - 2] ?? p1
  const p3 = prof[i + 1] ?? p2
  const span = p2[0] - p1[0]
  const u = span > 0 ? clamp((t - p1[0]) / span, 0, 1) : 0
  const u2 = u * u
  const u3 = u2 * u
  const cr = (k: 1 | 2): number =>
    0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * u + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * u2
      + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * u3)
  return [cr(1), cr(2)]
}

/** Точка суперэллипса с полуосями a (x) и b (z) под углом th. */
export function crossSec(th: number, a: number, b: number, sq: number): [number, number] {
  const c = Math.cos(th)
  const s = Math.sin(th)
  const p = 2 / sq
  return [Math.sign(c) * Math.pow(Math.abs(c), p) * a, Math.sign(s) * Math.pow(Math.abs(s), p) * b]
}

/** Рельеф жевательной поверхности в долях полуосей (fx: мезиально −1 …
 *  дистально +1; fz: язычно −1 … щёчно +1), мм: бугры гауссианами, борозды
 *  вычитанием. Число бугров — морфология: верхний моляр 4, нижний 5,
 *  премоляр 2, клык 1, у резца режущий край гладкий. */
export function reliefFn(cls: Cls, upper: boolean): (fx: number, fz: number) => number {
  const gs = (fx: number, fz: number, cx: number, cz: number, s: number): number =>
    Math.exp(-0.5 * (((fx - cx) / s) ** 2 + ((fz - cz) / s) ** 2))
  if (cls === 'molar') {
    const cusps: [number, number, number][] = upper
      ? [[-0.48, 0.51, 2.0], [0.51, 0.49, 1.78], [-0.5, -0.53, 1.88], [0.53, -0.45, 1.38]]
      : [[-0.5, 0.5, 1.9], [0.12, 0.56, 1.62], [0.66, 0.36, 1.3], [-0.45, -0.5, 1.9], [0.42, -0.5, 1.62]]
    return (fx, fz) => {
      let h = 0
      for (const [cx, cz, a] of cusps) h += a * gs(fx, fz, cx, cz, 0.34)
      h -= 1.15 * gs(fx, fz, 0.02, 0, 0.24)
      h -= 0.7 * Math.exp(-0.5 * (fx / 0.1) ** 2) * clamp((fz + 0.05) / 0.35, 0, 1)
      h -= 0.55 * Math.exp(-0.5 * ((fx - 0.35) / 0.1) ** 2) * clamp((-fz - 0.05) / 0.35, 0, 1)
      return Math.max(0, h)
    }
  }
  if (cls === 'premolar') {
    const lh = upper ? 1.6 : 1.0
    return (fx, fz) => {
      let h = 2.1 * gs(fx, fz, 0, 0.46, 0.42) + lh * gs(fx, fz, 0, -0.46, 0.4)
      h -= 0.7 * Math.exp(-0.5 * (fz / 0.16) ** 2) * clamp(1 - Math.abs(fx) / 0.75, 0, 1)
      return Math.max(0, h)
    }
  }
  if (cls === 'canine') return (fx, fz) => 1.3 * gs(fx, fz, -0.1, 0, 0.45)
  return () => 0
}

export type CrownInput = Pick<ToothGeom, 'md' | 'bl' | 'crown' | 'cls' | 'upper'>

/** Коронка: стенка (θ × высота) + площадка (кольца к центру); пять групп
 *  треугольников по секторам θ и площадке — пять материалов. */
export function buildCrown(g: CrownInput): RawMesh {
  const cls = toCls(g.cls)
  const hmd = g.md / 2
  const hbl = g.bl / 2
  const H = g.crown
  const TH = 64
  const ROWS = 22
  const RINGS = 10
  const sq = SQUARE[cls]
  const prof = profOf(cls)
  const relief = reliefFn(cls, g.upper)
  const rimK = cls === 'molar' || cls === 'premolar' ? 0.52 : 0
  const [topMD, topBL] = profAt(prof, 1)
  const pos: number[] = []
  const ridge = (th: number): number => {
    const [x, z] = crossSec(th, hmd * topMD, hbl * topBL, sq)
    return relief(x / hmd, z / hbl) * rimK
  }
  for (let r = 0; r <= ROWS; r++) {
    const t = r / ROWS
    const [wm, wb] = profAt(prof, t)
    const k = smooth(0.72, 1, t)
    for (let j = 0; j < TH; j++) {
      const th = (2 * Math.PI * j) / TH
      const [x, z] = crossSec(th, hmd * wm, hbl * wb, sq)
      pos.push(x, t * H + ridge(th) * k, z)
    }
  }
  const ringStart: number[] = [ROWS * TH]
  for (let k = 1; k <= RINGS; k++) {
    const s = 1 - k / RINGS
    ringStart.push(pos.length / 3)
    if (k === RINGS) {
      pos.push(0, H + relief(0, 0), 0)
      break
    }
    for (let j = 0; j < TH; j++) {
      const th = (2 * Math.PI * j) / TH
      const [rx, rz] = crossSec(th, hmd * topMD, hbl * topBL, sq)
      const x = rx * s
      const z = rz * s
      const fade = 1 - smooth(0.7, 1, s)
      pos.push(x, H + relief(x / hmd, z / hbl) * fade + ridge(th) * (1 - fade), z)
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
  return { positions: pos, index, groups }
}

interface RootSpec { x: number; z: number; rx: number; rz: number; len: number; ox: number; oz: number }

/** Расположение корней: три у верхнего моляра (два щёчных и нёбный — длиннее
 *  и уходит нёбно), два у нижнего моляра (мезиальный и дистальный) и верхнего
 *  первого премоляра (щёчный и нёбный), один у остальных. */
function rootSpecs(cls: Cls, n: number, hmd: number, hbl: number, len: number): RootSpec[] {
  if (n === 3) {
    return [
      { x: -0.34 * hmd, z: 0.31 * hbl, rx: 0.37 * hmd, rz: 0.34 * hbl, len: len * 0.95, ox: -0.29 * hmd, oz: 0.25 * hbl },
      { x: 0.36 * hmd, z: 0.32 * hbl, rx: 0.35 * hmd, rz: 0.32 * hbl, len: len * 0.9, ox: 0.31 * hmd, oz: 0.22 * hbl },
      { x: 0.02 * hmd, z: -0.36 * hbl, rx: 0.42 * hmd, rz: 0.38 * hbl, len: len * 1.02, ox: 0.04 * hmd, oz: -0.28 * hbl },
    ]
  }
  if (n === 2) {
    if (cls === 'premolar') {
      return [
        { x: 0, z: 0.42 * hbl, rx: 0.55 * hmd, rz: 0.36 * hbl, len, ox: 0, oz: 0.2 * hbl },
        { x: 0, z: -0.42 * hbl, rx: 0.55 * hmd, rz: 0.36 * hbl, len: len * 0.96, ox: 0, oz: -0.2 * hbl },
      ]
    }
    return [
      { x: -0.45 * hmd, z: 0, rx: 0.3 * hmd, rz: 0.72 * hbl, len, ox: -0.1 * hmd, oz: 0 },
      { x: 0.45 * hmd, z: 0, rx: 0.3 * hmd, rz: 0.7 * hbl, len: len * 0.95, ox: 0.25 * hmd, oz: 0 },
    ]
  }
  return [{ x: 0, z: 0, rx: 0.72 * hmd, rz: 0.72 * hbl, len, ox: 0.08 * hmd, oz: 0 }]
}

export type RootsInput = Pick<ToothGeom, 'md' | 'bl' | 'root' | 'roots' | 'cls'>

/** Шеечный переход + корни (эллиптические конусы, слегка расходятся и
 *  наклонены дистально). Одна группа — один материал (дентин). */
export function buildRoots(g: RootsInput): RawMesh {
  const cls = toCls(g.cls)
  const hmd = g.md / 2
  const hbl = g.bl / 2
  const TH = 48
  const COL = 2.4
  const CR = 6
  const sq = SQUARE[cls]
  const [wm0, wb0] = profAt(profOf(cls), 0)
  const pos: number[] = []
  const idx: number[] = []
  for (let r = 0; r <= CR; r++) {
    const t = r / CR
    const w = 1 - 0.14 * smooth(0, 1, t)
    for (let j = 0; j < TH; j++) {
      const th = (2 * Math.PI * j) / TH
      const [x, z] = crossSec(th, hmd * wm0 * w, hbl * wb0 * w, sq)
      pos.push(x, -COL * t, z)
    }
  }
  for (let r = 0; r < CR; r++) {
    for (let j = 0; j < TH; j++) {
      const jn = (j + 1) % TH
      const a = r * TH + j
      const b = r * TH + jn
      const c = (r + 1) * TH + jn
      const d = (r + 1) * TH + j
      idx.push(a, b, c, a, c, d)
    }
  }
  const RS = 20
  const RR = 12
  for (const s of rootSpecs(cls, g.roots, hmd, hbl, g.root)) {
    const base = pos.length / 3
    for (let r = 0; r <= RR; r++) {
      const t = r / RR
      const y = -COL * 0.62 - s.len * t
      const bend = t * t
      const cx = s.x + s.ox * bend
      const cz = s.z + s.oz * bend
      const k = Math.pow(1 - t, 0.62) * (1 + 0.1 * Math.sin(Math.PI * t))
      if (r === RR) {
        pos.push(cx, y, cz)
        break
      }
      for (let j = 0; j < RS; j++) {
        const th = (2 * Math.PI * j) / RS
        pos.push(cx + Math.cos(th) * s.rx * k, y, cz + Math.sin(th) * s.rz * k)
      }
    }
    for (let r = 0; r < RR; r++) {
      const o = base + r * RS
      const i = base + (r + 1) * RS
      if (r === RR - 1) {
        const tip = base + RR * RS
        for (let j = 0; j < RS; j++) {
          const jn = (j + 1) % RS
          idx.push(o + j, o + jn, tip)
        }
      } else {
        for (let j = 0; j < RS; j++) {
          const jn = (j + 1) % RS
          idx.push(o + j, o + jn, i + jn, o + j, i + jn, i + j)
        }
      }
    }
  }
  return oneGroup(pos, idx)
}

/** Винт импланта радиуса r — тело вращения: площадка, шейка, восемь витков, конус. */
export function buildScrew(r: number): RawMesh {
  const pts: [number, number][] = [[0, 0.4], [r * 0.85, 0.4], [r, 0], [r, -0.9]]
  for (let i = 0; i < 8; i++) {
    const y = -1.2 - i * 1.15
    const k = 1 - i * 0.055
    pts.push([r * 0.78 * k, y], [r * k, y - 0.55])
  }
  pts.push([r * 0.45, -10.6], [0, -11])
  return lathe(pts, 24)
}
