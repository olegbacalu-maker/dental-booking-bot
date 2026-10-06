import { describe, expect, it } from 'vitest'
import { layoutArch } from './arch'
import { crownModel } from './crown'
import { anchorsFor, buildGum, linRgb, marginPoint, stripesFor, type GumKind, type GumTooth } from './gum'
import { finite } from './mesh'
import { posed } from './pose'
import { toCls } from './toothGeometry'

/* Десна по краю (06.10): сетка цела и смотрит наружу у обеих челюстей, край
   садится на стенку зуба, рецессия опускает его ниже шейки, на месте
   отсутствующего зуба — гребень без дыры, полоса кармана — только где её
   прислали. */

const UP = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LO = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const CLS: Record<number, [string, number, number, number]> = {
  1: ['incisor_c', 8.6, 7.0, 10.5], 2: ['incisor_l', 6.6, 6.2, 9.0], 3: ['canine', 7.6, 8.0, 10.0], 4: ['premolar', 7.0, 9.0, 8.5],
  5: ['premolar', 6.8, 9.0, 8.5], 6: ['molar', 10.5, 11.0, 7.5], 7: ['molar', 9.5, 10.5, 7.5], 8: ['molar', 8.8, 10.0, 7.0],
}

interface Opts { rec?: Record<number, number[]>; kinds?: Record<number, GumKind>; red?: number[] }

function jaw(list: number[], upper: boolean, o: Opts = {}) {
  const geo = (n: number) => {
    const [cls, md, bl, crown] = CLS[n % 10] as [string, number, number, number]
    return { md, bl, crown, root: 12, roots: 1, cls, upper }
  }
  const lay = layoutArch(list.map((n) => ({ n, md: geo(n).md })), upper)
  const models = new Map(list.map((n) => [n, crownModel(geo(n))]))
  const ref = models.get(upper ? 16 : 36)?.tip ?? 9
  const red = linRgb(0xdc2626)
  const teeth: GumTooth[] = lay.teeth.map((p0) => {
    const g = geo(p0.n)
    const c = models.get(p0.n) as ReturnType<typeof crownModel>
    const p = posed(p0, toCls(g.cls), upper, c.tip, ref)
    const sites = o.red?.includes(p0.n) ? [red, red, red, red, red, red] : null
    return {
      n: p0.n, kind: o.kinds?.[p0.n] ?? 'tooth', s: p.s, md: g.md, bl: g.bl, root: g.root,
      position: p.position, xAxis: p.xAxis, yAxis: p.yAxis, zAxis: p.zAxis, surf: c.surf,
      anchors: anchorsFor(toCls(g.cls), o.rec?.[p0.n] ?? null, false, false), stripe: stripesFor(sites),
    }
  })
  const gum = buildGum({ A: lay.A, D: lay.D, apex: lay.apex, yBase: lay.yBase, occ: upper ? -1 : 1, teeth })
  return { lay, teeth, gum }
}

/** Сумма z-составляющих площадных нормалей треугольников впереди дуги. */
function frontNz(P: number[], idx: number[], apex: number): number {
  let sz = 0
  for (let i = 0; i < idx.length; i += 3) {
    const a = (idx[i] ?? 0) * 3
    const b = (idx[i + 1] ?? 0) * 3
    const c = (idx[i + 2] ?? 0) * 3
    const cx = ((P[a] ?? 0) + (P[b] ?? 0) + (P[c] ?? 0)) / 3
    const cz = ((P[a + 2] ?? 0) + (P[b + 2] ?? 0) + (P[c + 2] ?? 0)) / 3
    if (Math.abs(cx) > 3 || cz < apex + 2) continue
    const ux = (P[b] ?? 0) - (P[a] ?? 0)
    const uy = (P[b + 1] ?? 0) - (P[a + 1] ?? 0)
    const vx = (P[c] ?? 0) - (P[a] ?? 0)
    const vy = (P[c + 1] ?? 0) - (P[a + 1] ?? 0)
    sz += ux * vy - uy * vx
  }
  return sz
}

/** Ближайшая вершина сетки к точке, мм. */
function nearest(P: number[], q: number[]): number {
  let best = Infinity
  for (let i = 0; i < P.length; i += 3) {
    best = Math.min(best, Math.hypot((P[i] ?? 0) - (q[0] ?? 0), (P[i + 1] ?? 0) - (q[1] ?? 0), (P[i + 2] ?? 0) - (q[2] ?? 0)))
  }
  return best
}

describe('десна по краю', () => {
  for (const upper of [true, false]) {
    it(`${upper ? 'верхняя' : 'нижняя'}: сетка цела, цвет у каждой вершины, нормаль впереди — наружу`, () => {
      const { gum, lay } = jaw(upper ? UP : LO, upper)
      expect(finite(gum)).toBe(true)
      expect(gum.colors?.length).toBe(gum.positions.length)
      const nv = gum.positions.length / 3
      expect(nv).toBeGreaterThan(5000)
      expect(nv).toBeLessThan(60000)
      expect(frontNz(gum.positions, gum.index, lay.apex)).toBeGreaterThan(0)
    })
  }

  it('край садится на стенку зуба: у щёчной середины 11 вершина десны не дальше 0,3 мм от точки края', () => {
    const { gum, teeth } = jaw(UP, true)
    const t = teeth.find((x) => x.n === 11) as GumTooth
    expect(nearest(gum.positions, marginPoint(t, Math.PI / 2))).toBeLessThan(0.3)
  })

  it('рецессия 3 мм у V опускает край ниже шейки, сосочек остаётся', () => {
    const a = anchorsFor('incisor_c', [0, 3, 0, 0, 0, 0], false, false)
    expect(a[2]).toBe(-3)
    expect(a[0]).toBeGreaterThan(3)
    const healthy = jaw(LO, false).teeth.find((x) => x.n === 41) as GumTooth
    const { gum, teeth } = jaw(LO, false, { rec: { 41: [0, 3, 0, 0, 0, 0] } })
    const t = teeth.find((x) => x.n === 41) as GumTooth
    const q = marginPoint(t, Math.PI / 2)
    // вдоль оси зуба край на 3,9 мм ниже здорового (0,9 над шейкой → 3 под ней)
    const h = marginPoint(healthy, Math.PI / 2)
    const along = (h[0] - q[0]) * t.yAxis[0] + (h[1] - q[1]) * t.yAxis[1] + (h[2] - q[2]) * t.yAxis[2]
    expect(along).toBeCloseTo(3.9, 6)
    expect(nearest(gum.positions, q)).toBeLessThan(0.3)
  })

  it('на месте отсутствующего зуба — гребень, а не дыра: десна есть прямо над его шейкой', () => {
    const { gum, teeth } = jaw(UP, true, { kinds: { 12: 'missing' } })
    const t = teeth.find((x) => x.n === 12) as GumTooth
    // верхняя челюсть: гребень на 0,4 мм к корню от шейки (y больше), допуск — округлость гребня
    expect(nearest(gum.positions, [t.position[0], t.position[1] + 0.4, t.position[2]])).toBeLessThan(0.8)
  })

  it('полоса кармана — только у зуба, которому её прислали', () => {
    // красная полоса: яркий красный почти без зелёного — у слизистой и низа красного меньше
    const greenless = (c: number[]): number => {
      let n = 0
      for (let i = 0; i < c.length; i += 3) if ((c[i] ?? 0) > 0.5 && (c[i + 1] ?? 1) < 0.07) n++
      return n
    }
    expect(greenless(jaw(UP, true).gum.colors ?? [])).toBe(0)
    expect(greenless(jaw(UP, true, { red: [26] }).gum.colors ?? [])).toBeGreaterThan(20)
  })
})
