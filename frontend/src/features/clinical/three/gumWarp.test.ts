import { describe, expect, it } from 'vitest'
import { buildJaw, GEOM, LOWER, shapesOf, UPPER } from '../../../test/jaws'
import { GAP, GAP_CLOSED, layoutArch, type PlacedTooth } from './arch'
import { anchorsFor, archFrame, buildGum, gumWarpFrame, stripesFor, warpGum, WARP_W0, WARP_W1, type GumTooth, type WarpTooth } from './gum'
import { occlusionPlan, placeOf } from './occlusionPlan'
import { toCls } from './toothGeometry'

/* Десна вслед за зубами по плану прикуса (этап 4 «ocluzie», вариант (б2)
   координатора 07.11): сегменты 4–8 по сторонам и «веер» 43–33. Сцена не
   перестраивает десну (~57 мс на челюсть), а деформирует её вершины теми же
   жёсткими преобразованиями, что зубы (`warpGum`). Кадр «до/после» —
   `design/ocluzie-3d/stage4/final/sides-gum-zoom.png`. */

const SLOW = { timeout: 30000 }
const U = buildJaw(UPPER, true)
const L = buildJaw(LOWER, false)
const S = shapesOf(U, L)
const lay = layoutArch(LOWER.map((n) => ({ n, md: GEOM.L[n % 10]!.md })), false)
const teeth: GumTooth[] = LOWER.map((n) => {
  const b = L.get(n)!
  const g = GEOM.L[n % 10]!
  return {
    n, kind: 'tooth', s: b.p.s, md: g.md, bl: g.bl, root: 12, position: b.p.position, xAxis: b.p.xAxis, yAxis: b.p.yAxis, zAxis: b.p.zAxis,
    surf: b.cm.surf, anchors: anchorsFor(toCls(g.cls), null, false, false), stripe: stripesFor(null),
  }
})
const gum = buildGum({ A: lay.A, D: lay.D, apex: lay.apex, yBase: lay.yBase, occ: 1, teeth })
const F = archFrame(lay.A, lay.D, lay.apex)
const info = LOWER.map((n) => {
  const p = L.get(n)!.p
  return { n, u: F.project(p.position[0], p.position[2], p.s), neckY: p.position[1], x: p.position[0], z: p.position[2] }
})
const fr = gumWarpFrame(gum.positions, lay.A, lay.D, lay.apex, info, 1)
const warpFor = (to: (n: number, p: PlacedTooth) => PlacedTooth, w0 = WARP_W0, w1 = WARP_W1): { out: Float32Array; wt: WarpTooth[] } => {
  const wt = info.map((x) => ({ u: x.u, from: L.get(x.n)!.p, to: to(x.n, L.get(x.n)!.p) })).sort((a, b) => a.u - b.u)
  return { out: warpGum(gum.positions, fr.u, fr.depth, wt, w0, w1), wt }
}

describe('десна вслед за зубами (`warpGum`)', () => {
  it('⭐ все зубы на местах раскладки — та же сетка, число в число', () => {
    const { out } = warpFor((_n, p) => p)
    expect(Array.from(out)).toEqual(Array.from(Float32Array.from(gum.positions)))
  })

  it('⭐ у шейки вершина идёт ровно со своим зубом; тело без ступени на границе сегментов 3|4', SLOW, () => {
    const plan = occlusionPlan({ angle_dr: 'II/1', angle_st: 'III' }, S, (GAP - GAP_CLOSED) / 2)
    if (!plan) throw new Error('нет плана')
    const { out, wt } = warpFor((n, p) => placeOf(n, p, plan.teeth, 1))
    const P = gum.positions
    // (1) у шейки (глубина < 0,3) в середине своего зуба — жёсткое преобразование зуба
    let worst = 0
    for (const t of wt) {
      const f = t.from
      const g = t.to
      for (let i = 0; i < fr.u.length; i++) {
        if ((fr.depth[i] as number) > 0.3 || Math.abs((fr.u[i] as number) - t.u) > 1.5) continue
        const p = [P[i * 3] as number, P[i * 3 + 1] as number, P[i * 3 + 2] as number]
        const d = [p[0]! - f.position[0], p[1]! - f.position[1], p[2]! - f.position[2]]
        const loc = [0, 1, 2].map((r) => d[0]! * [f.xAxis, f.yAxis, f.zAxis][r]![0] + d[1]! * [f.xAxis, f.yAxis, f.zAxis][r]![1] + d[2]! * [f.xAxis, f.yAxis, f.zAxis][r]![2])
        const want = [0, 1, 2].map((c) => g.position[c]! + loc[0]! * g.xAxis[c]! + loc[1]! * g.yAxis[c]! + loc[2]! * g.zAxis[c]!)
        worst = Math.max(worst, Math.hypot(out[i * 3]! - want[0]!, out[i * 3 + 1]! - want[1]!, out[i * 3 + 2]! - want[2]!))
      }
    }
    expect(worst).toBeLessThan(1e-3)
    // (2) растяжение рёбер сетки в теле (глубина ≥ 2 мм): |Δ смещения| / длина ребра.
    // Узкий переход (без расширения книзу) — ступень на границе 3|4, проверка её видит
    const strain = (o: Float32Array): number => {
      const idx = gum.index
      let st = 0
      for (let k = 0; k + 2 < idx.length; k += 3) {
        for (const [a, b] of [[idx[k]!, idx[k + 1]!], [idx[k + 1]!, idx[k + 2]!], [idx[k + 2]!, idx[k]!]] as [number, number][]) {
          if ((fr.depth[a] as number) < 2 || (fr.depth[b] as number) < 2) continue
          const len = Math.hypot(P[a * 3]! - P[b * 3]!, P[a * 3 + 1]! - P[b * 3 + 1]!, P[a * 3 + 2]! - P[b * 3 + 2]!)
          if (len < 0.2) continue
          const dd = [0, 1, 2].map((c) => (o[a * 3 + c]! - P[a * 3 + c]!) - (o[b * 3 + c]! - P[b * 3 + c]!))
          st = Math.max(st, Math.hypot(dd[0]!, dd[1]!, dd[2]!) / len)
        }
      }
      return st
    }
    expect(strain(out)).toBeLessThan(1)
    expect(strain(warpFor((n, p) => placeOf(n, p, plan.teeth, 1), WARP_W0, 0).out)).toBeGreaterThan(5)
  })
})
