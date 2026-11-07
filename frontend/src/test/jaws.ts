import { SCULPT, SCULPT_OF } from '../../models/teeth.js'
import { layoutArch, toWorld, type PlacedTooth, type Vec3 } from '../features/clinical/three/arch'
import { crownModel, type CrownModel } from '../features/clinical/three/crown'
import { molarMark } from '../features/clinical/three/occlusion'
import type { ToothShape } from '../features/clinical/three/occlusionPlan'
import { posed } from '../features/clinical/three/pose'
import { sculptModel } from '../features/clinical/three/sculpt'
import { toCls } from '../features/clinical/three/toothGeometry'

/* Челюсти для проверок прикуса (волна «ocluzie»): тем же путём, что сцена
   (`scene.buildArch` со своими моделями) — раскладка `layoutArch`, свои модели
   зубов (`teeth.js`), постановка `posed` по формуле первого моляра. Размеры —
   `teeth_svg.tooth_geom` сервера (07.11.2026); для проверок, не для экрана —
   таблиц размеров в клиенте нет. */

export const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
export const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]

export const GEOM: Record<'U' | 'L', Record<number, { md: number; bl: number; crown: number; cls: string }>> = {
  U: {
    1: { md: 8.52, bl: 7.16, crown: 10.5, cls: 'incisor_c' }, 2: { md: 6.73, bl: 6.46, crown: 9.0, cls: 'incisor_l' },
    3: { md: 7.62, bl: 8.07, crown: 10.0, cls: 'canine' }, 4: { md: 7.48, bl: 9.5, crown: 8.5, cls: 'premolar' },
    5: { md: 7.16, bl: 9.09, crown: 8.5, cls: 'premolar' }, 6: { md: 10.5, bl: 11.03, crown: 7.5, cls: 'molar' },
    7: { md: 9.98, bl: 10.47, crown: 7.5, cls: 'molar' }, 8: { md: 9.24, bl: 9.7, crown: 7.5, cls: 'molar' },
  },
  L: {
    1: { md: 5.79, bl: 6.55, crown: 9.0, cls: 'incisor_c' }, 2: { md: 6.26, bl: 6.88, crown: 9.5, cls: 'incisor_l' },
    3: { md: 7.01, bl: 7.57, crown: 11.0, cls: 'canine' }, 4: { md: 7.48, bl: 8.0, crown: 8.0, cls: 'premolar' },
    5: { md: 7.16, bl: 7.66, crown: 8.0, cls: 'premolar' }, 6: { md: 10.5, bl: 10.08, crown: 7.5, cls: 'molar' },
    7: { md: 9.98, bl: 9.58, crown: 7.5, cls: 'molar' }, 8: { md: 9.24, bl: 8.87, crown: 7.5, cls: 'molar' },
  },
}

export interface Built { p: PlacedTooth; local: ArrayLike<number>; index: ArrayLike<number>; pts: number[]; mark: Vec3 | null; md: number; cm: CrownModel }

export const geomOf = (n: number) => ({ ...GEOM[n < 30 ? 'U' : 'L'][n % 10]!, root: 12, roots: 1, upper: n < 30 })

/** Челюсть так, как её ставит сцена: точки коронок и ориентиры моляров — в системе группы. */
export function buildJaw(list: number[], upper: boolean, formula = false): Map<number, Built> {
  const lay = layoutArch(list.map((n) => ({ n, md: geomOf(n).md })), upper)
  const ref = crownModel(geomOf(upper ? 16 : 36)).tip
  const out = new Map<number, Built>()
  for (const p0 of lay.teeth) {
    const g = geomOf(p0.n)
    const cm = formula ? crownModel(g) : sculptModel(SCULPT[SCULPT_OF[p0.n] ?? '']!, g)
    const p = posed(p0, toCls(g.cls), upper, cm.tip, ref)
    const pos = cm.mesh.positions
    const pts: number[] = []
    for (let i = 0; i + 2 < pos.length; i += 3) pts.push(...toWorld(p, [pos[i]!, pos[i + 1]!, pos[i + 2]!]))
    const k = p0.n % 10 === 6 ? molarMark(pos, g.md, upper) : null
    out.set(p0.n, { p, local: pos, index: cm.mesh.index, pts, mark: k ? toWorld(p, k) : null, md: g.md, cm })
  }
  return out
}

/** Коронки обеих челюстей для `occlusionPlan` — как `scene.planShapes`. */
export function shapesOf(U: Map<number, Built>, L: Map<number, Built>): Map<number, ToothShape> {
  const S = new Map<number, ToothShape>()
  for (const [M, upper] of [[U, true], [L, false]] as const) {
    for (const [n, b] of M) S.set(n, { place: b.p, pos: b.local, index: b.index, md: b.md, upper })
  }
  return S
}
