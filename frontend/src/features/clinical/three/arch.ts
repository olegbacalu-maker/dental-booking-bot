import { oneGroup, type RawMesh } from './mesh'

/* Раскладка по дуге (B7, ступень 3) — та же парабола, что у 2D-дуги макета:
   сумма ширин зубов растягивает дугу, зуб стоит щёчной стороной наружу,
   мезиальной — к средней линии. Здесь только числа: точка на кривой, базис
   зуба, гребень десны; матрицы и группы three строит сцена (ступень 4).

   ⭐ Правило, которое ломается молча: квадранты 2 и 4 ОТРАЖАЮТСЯ (у базиса
   отрицательный определитель), потому что сетка зуба одна на все квадранты
   и мезиальная сторона у неё всегда −x. В панораме 2D отражаются 2 и 3 —
   там нижний ряд перевёрнут по вертикали; в 3D это не так, и переносить
   правило из 2D сюда нельзя. Держит `arch.test.ts`. */

export interface CurvePoint {
  x: number
  y: number
  tx: number
  ty: number
  nx: number
  ny: number
}

export interface ArchCurve {
  total: number
  at(s: number): CurvePoint
}

/** Парабола y = apexY + dir·D·x²/A² на x ∈ [−A, A], параметризованная длиной
 *  дуги s; нормаль смотрит НАРУЖУ дуги (прочь от точки внутри). */
export function archCurve(A: number, D: number, apexY: number, dir: number): ArchCurve {
  const N = 720
  const pts: [number, number][] = []
  const L: number[] = [0]
  for (let i = 0; i <= N; i++) {
    const x = -A + (2 * A * i) / N
    pts.push([x, apexY + (dir * D * x * x) / (A * A)])
    if (i) {
      const a = pts[i] as [number, number]
      const b = pts[i - 1] as [number, number]
      L.push((L[i - 1] ?? 0) + Math.hypot(a[0] - b[0], a[1] - b[1]))
    }
  }
  const total = L[N] ?? 0
  const inside: [number, number] = [0, apexY + dir * D * 0.45]
  return {
    total,
    at(s0: number): CurvePoint {
      const s = Math.max(0, Math.min(total, s0))
      let lo = 0
      let hi = N
      while (hi - lo > 1) {
        const m = (lo + hi) >> 1
        if ((L[m] ?? 0) <= s) lo = m
        else hi = m
      }
      const pl = pts[lo] as [number, number]
      const ph = pts[hi] as [number, number]
      const t = (s - (L[lo] ?? 0)) / (((L[hi] ?? 0) - (L[lo] ?? 0)) || 1)
      const x = pl[0] + (ph[0] - pl[0]) * t
      const y = pl[1] + (ph[1] - pl[1]) * t
      let tx = ph[0] - pl[0]
      let ty = ph[1] - pl[1]
      const nn = Math.hypot(tx, ty) || 1
      tx /= nn
      ty /= nn
      let nx = ty
      let ny = -tx
      if (nx * (inside[0] - x) + ny * (inside[1] - y) > 0) {
        nx = -nx
        ny = -ny
      }
      return { x, y, tx, ty, nx, ny }
    },
  }
}

/** Расстояние между челюстями в покое и в смыкании, мм. */
export const GAP = 26
export const GAP_CLOSED = 18
/** Промежуток между соседними коронками по дуге, мм. */
export const TOOTH_GAP = 0.3

export type Vec3 = [number, number, number]

export interface PlacedTooth {
  n: number
  /** длина дуги до середины зуба */
  s: number
  position: Vec3
  /** базис зуба в мире: x — дистально, y — окклюзионно, z — щёчно */
  xAxis: Vec3
  yAxis: Vec3
  zAxis: Vec3
  /** базис зеркальный (определитель < 0) — квадранты 2 и 4 */
  mirror: boolean
}

export interface ArchLayout {
  A: number
  D: number
  apex: number
  yBase: number
  dir: 1 | -1
  teeth: PlacedTooth[]
}

const norm = (v: Vec3): Vec3 => {
  const n = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / n, v[1] / n, v[2] / n]
}
export const det3 = (x: Vec3, y: Vec3, z: Vec3): number =>
  x[0] * (y[1] * z[2] - y[2] * z[1]) - x[1] * (y[0] * z[2] - y[2] * z[0]) + x[2] * (y[0] * z[1] - y[1] * z[0])

/** Ряд зубов по дуге: порядок списка — как у движка (18…11, 21…28 сверху;
 *  48…41, 31…38 снизу), ширины `md` с сервера. Дуга подбирается под сумму
 *  ширин: единичная парабола (A = 1, D = 1.6) масштабируется в её длину. */
export function layoutArch(teeth: { n: number; md: number }[], upper: boolean): ArchLayout {
  const widths = teeth.map((t) => t.md + TOOTH_GAP)
  const sum = widths.reduce((a, b) => a + b, 0)
  const unit = archCurve(1, 1.6, 0, -1)
  const sc = sum / (unit.total || 1)
  const A = sc
  const D = 1.6 * sc
  const apex = upper ? 2 : -2.5
  const cv = archCurve(A, D, apex, -1)
  const yBase = upper ? GAP / 2 : -GAP / 2
  const yAxis: Vec3 = [0, upper ? -1 : 1, 0]
  let acc = 0
  const placed: PlacedTooth[] = teeth.map((t, i) => {
    const w = widths[i] ?? 0
    const s = acc + w / 2
    acc += w
    const p = cv.at(s)
    const zAxis = norm([p.nx, 0, p.ny])
    let tv = norm([p.tx, 0, p.ty])
    if (p.x > 0) tv = [-tv[0], -tv[1], -tv[2]]
    const xAxis: Vec3 = [-tv[0], -tv[1], -tv[2]]
    return {
      n: t.n, s, position: [p.x, yBase, p.y], xAxis, yAxis, zAxis,
      mirror: det3(xAxis, yAxis, zAxis) < 0,
    }
  })
  return { A, D, apex, yBase, dir: upper ? 1 : -1, teeth: placed }
}

/** Точка в мире из локальной точки зуба (без масштаба). */
export function toWorld(t: PlacedTooth, local: Vec3): Vec3 {
  return [
    t.position[0] + t.xAxis[0] * local[0] + t.yAxis[0] * local[1] + t.zAxis[0] * local[2],
    t.position[1] + t.xAxis[1] * local[0] + t.yAxis[1] * local[1] + t.zAxis[1] * local[2],
    t.position[2] + t.xAxis[2] * local[0] + t.yAxis[2] * local[1] + t.zAxis[2] * local[2],
  ]
}

/** Десна: гребень эллиптического сечения вдоль той же параболы, чуть длиннее ряда. */
export function buildRidge(A: number, D: number, apex: number, yTop: number, dir: number): RawMesh {
  const rx = 6.0
  const ry = 8.5
  const N = 96
  const M = 28
  const ext = 4
  const yc = yTop + dir * (ry - 0.7)
  const pos: number[] = []
  const idx: number[] = []
  for (let i = 0; i <= N; i++) {
    const x = -(A + ext) + (2 * (A + ext) * i) / N
    const z = apex - (D * x * x) / (A * A)
    const dz = (-2 * D * x) / (A * A)
    const nn = Math.hypot(1, dz)
    const tx = 1 / nn
    const tz = dz / nn
    const nx = -tz
    const nz = tx
    for (let j = 0; j < M; j++) {
      const ph = (2 * Math.PI * j) / M
      const ox = Math.cos(ph) * rx
      const oy = Math.sin(ph) * ry
      pos.push(x + nx * ox, yc + oy, z + nz * ox)
    }
  }
  for (let i = 0; i < N; i++) {
    for (let j = 0; j < M; j++) {
      const jn = (j + 1) % M
      const a = i * M + j
      const b = i * M + jn
      const c = (i + 1) * M + jn
      const d = (i + 1) * M + j
      idx.push(a, c, b, a, d, c)
    }
  }
  for (const ring of [0, N]) {
    const c = pos.length / 3
    let cx = 0
    let cy = 0
    let cz = 0
    for (let j = 0; j < M; j++) {
      cx += pos[(ring * M + j) * 3] ?? 0
      cy += pos[(ring * M + j) * 3 + 1] ?? 0
      cz += pos[(ring * M + j) * 3 + 2] ?? 0
    }
    pos.push(cx / M, cy / M, cz / M)
    for (let j = 0; j < M; j++) {
      const jn = (j + 1) % M
      idx.push(c, ring * M + j, ring * M + jn)
    }
  }
  return oneGroup(pos, idx)
}
