import type { ToothGeom } from '../chart'
import { lathe, oneGroup, type RawMesh } from './mesh'

/* Части зуба, общие для всех видов коронки (B7): корни, винт импланта, пунктир
   пустого места, рельеф жевательной поверхности и буквы поверхностей. Саму
   коронку строит `crown.ts` (06.10: четыре полуоси сечения, наклон, цвет
   вершин); размеры (`md`, `bl`, `crown`, `root`, `roots`, `cls`, `upper`)
   приходят С СЕРВЕРА (`teeth_svg.tooth_geom`), здесь только форма — контракт
   clinical-chart.md › «3D — рендер, не истина».

   Канон: +x дистально, −x мезиально, +z щёчно, +y окклюзионно, шейка y = 0.
   Пять групп треугольников коронки = пять материалов = пять поверхностей в
   порядке `SURF`. */

export const SURF = ['O', 'V', 'L', 'M', 'D'] as const
export type Letter = (typeof SURF)[number]

export type Cls = 'incisor_c' | 'incisor_l' | 'canine' | 'premolar' | 'molar'
const CLASSES: readonly Cls[] = ['incisor_c', 'incisor_l', 'canine', 'premolar', 'molar']

/** Класс с сервера — строка; незнакомая рисуется моляром (форма, не диагноз). */
export function toCls(s: string): Cls {
  return (CLASSES as readonly string[]).includes(s) ? (s as Cls) : 'molar'
}

const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v))
const smooth = (e0: number, e1: number, x: number): number => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1)
  return t * t * (3 - 2 * t)
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

/** Пунктир вдоль замкнутого контура на высоте y: каждый чётный отрезок —
 *  трубка радиуса r (шесть граней), нечётный — промежуток. Трубки, а не линия:
 *  толщина линии в WebGL всегда 1 px, и пунктир на десне терялся бы. */
export function buildDashedLoop(outline: [number, number][], y: number, r: number): RawMesh {
  const SIDES = 6
  const positions: number[] = []
  const index: number[] = []
  const n = outline.length
  for (let k = 0; k < n; k += 2) {
    const a = outline[k]
    const b = outline[(k + 1) % n]
    if (!a || !b) continue
    const dx = b[0] - a[0]
    const dz = b[1] - a[1]
    const len = Math.hypot(dx, dz) || 1
    // поперечник трубки: горизонталь поперёк контура и вертикаль
    const hx = -dz / len
    const hz = dx / len
    const base = positions.length / 3
    for (const [px, pz] of [a, b]) {
      for (let s = 0; s < SIDES; s++) {
        const ph = (2 * Math.PI * s) / SIDES
        const c = Math.cos(ph) * r
        const v = Math.sin(ph) * r
        positions.push(px + hx * c, y + v, pz + hz * c)
      }
    }
    for (let s = 0; s < SIDES; s++) {
      const sn = (s + 1) % SIDES
      const i0 = base + s
      const i1 = base + sn
      const j0 = base + SIDES + s
      const j1 = base + SIDES + sn
      index.push(i0, j0, i1, i1, j0, j1)
    }
  }
  return oneGroup(positions, index)
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

/** Шеечный переход (сечение шейки коронки, сужается на 14 %) + корни
 *  (эллиптические конусы, слегка расходятся и наклонены дистально). Одна
 *  группа — один материал (дентин). */
export function buildRoots(g: RootsInput, neck: (th: number) => [number, number]): RawMesh {
  const cls = toCls(g.cls)
  const hmd = g.md / 2
  const hbl = g.bl / 2
  const TH = 48
  const COL = 2.4
  const CR = 6
  const pos: number[] = []
  const idx: number[] = []
  for (let r = 0; r <= CR; r++) {
    const t = r / CR
    const w = 1 - 0.14 * smooth(0, 1, t)
    for (let j = 0; j < TH; j++) {
      const th = (2 * Math.PI * j) / TH
      // шейка коронки (`crown.ts`) — корень продолжает её сечение
      const [nx, nz] = neck(th)
      const x = nx * w
      const z = nz * w
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
