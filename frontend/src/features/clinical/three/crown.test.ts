import { describe, expect, it } from 'vitest'
import { crownModel } from './crown'
import { finite, triangles } from './mesh'
import { SURF, type Cls } from './toothGeometry'

/* Коронка (06.10): пять групп в порядке поверхностей, размеры сервера, цвет
   вершин на каждую точку, и — несущее — стенка `surf` та же, что у сетки: по
   ней садится край десны, расхождение дало бы щель между десной и зубом. */

const GEOM: Record<Cls, { md: number; bl: number; crown: number }> = {
  incisor_c: { md: 8.52, bl: 7.16, crown: 10.5 },
  incisor_l: { md: 6.6, bl: 6.3, crown: 9.0 },
  canine: { md: 7.8, bl: 8.2, crown: 10.0 },
  premolar: { md: 7.48, bl: 9.5, crown: 8.5 },
  molar: { md: 10.5, bl: 11.03, crown: 7.5 },
}

const col = (m: number[], i: number): number[] => [m[i * 3] ?? 0, m[i * 3 + 1] ?? 0, m[i * 3 + 2] ?? 0]

describe('коронка', () => {
  for (const cls of Object.keys(GEOM) as Cls[]) {
    for (const upper of [true, false]) {
      it(`${cls} ${upper ? 'сверху' : 'снизу'}: пять групп O V L M D, размеры сервера, цвет у каждой вершины`, () => {
        const g = GEOM[cls]
        const { mesh: m, tip } = crownModel({ ...g, cls, upper })
        expect(m.groups.map((x) => x.materialIndex)).toEqual([0, 1, 2, 3, 4])
        expect(m.groups.every((x) => x.count > 0 && x.count % 3 === 0)).toBe(true)
        expect(m.groups.map((x) => x.start)).toEqual(m.groups.map((_x, i) => m.groups.slice(0, i).reduce((s, y) => s + y.count, 0)))
        expect(m.index.length).toBe(m.groups.reduce((s, x) => s + x.count, 0))
        expect(finite(m)).toBe(true)
        expect(m.colors?.length).toBe(m.positions.length)
        const xs = m.positions.filter((_v, i) => i % 3 === 0)
        const ys = m.positions.filter((_v, i) => i % 3 === 1)
        const zs = m.positions.filter((_v, i) => i % 3 === 2)
        // ширина по x — md сервера (самое широкое сечение = 1.0), глубина по z — bl с валиками не шире 6 %
        expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(g.md, 0)
        expect(Math.max(...zs) - Math.min(...zs)).toBeLessThanOrEqual(g.bl * 1.06)
        expect(Math.min(...ys)).toBeCloseTo(0, 5)
        expect(tip).toBe(Math.max(...ys))
        expect(tip).toBeGreaterThanOrEqual(g.crown)
        expect(tip).toBeLessThan(g.crown + 3)
      })
    }
  }

  it('порядок групп — порядок поверхностей: materialIndex = буква', () => {
    expect([...SURF]).toEqual(['O', 'V', 'L', 'M', 'D'])
  })

  it('незнакомый класс рисуется моляром', () => {
    expect(triangles(crownModel({ ...GEOM.molar, cls: 'zub', upper: false }).mesh)).toBeGreaterThan(1000)
  })
})

describe('стенка для десны', () => {
  it('на шейке стенка = сечение шейки; ниже шейки корень уже, выше коронка шире', () => {
    const c = crownModel({ ...GEOM.molar, cls: 'molar', upper: true })
    for (const th of [0, 0.7, Math.PI / 2, 2.5, Math.PI, 4, 1.5 * Math.PI]) {
      const [nx, nz] = c.neck(th)
      const [sx, sz] = c.surf(th, 0)
      expect(sx).toBeCloseTo(nx, 9)
      expect(sz).toBeCloseTo(nz, 9)
      expect(Math.hypot(...c.surf(th, -2))).toBeLessThan(Math.hypot(nx, nz))
      expect(Math.hypot(...c.surf(th, 2))).toBeGreaterThan(Math.hypot(nx, nz))
    }
  })

  it('стенка лежит на сетке: точка `surf` на высоте ряда совпадает с вершиной ряда', () => {
    const g = { ...GEOM.incisor_c, cls: 'incisor_c', upper: true }
    const c = crownModel(g)
    // ряд r = 3 из 26, угол j = 18 из 72 (щёчная середина): x, y, z вершины
    const r = 3
    const j = 18
    const i = (r * 72 + j) * 3
    const h = (r / 26) * g.crown
    const [x, z] = c.surf((2 * Math.PI * j) / 72, h)
    expect(c.mesh.positions[i]).toBeCloseTo(x, 9)
    expect(c.mesh.positions[i + 1]).toBeCloseTo(h, 9)
    expect(c.mesh.positions[i + 2]).toBeCloseTo(z, 9)
  })

  it('контур шейки — n точек по сечению шейки', () => {
    const c = crownModel({ ...GEOM.canine, cls: 'canine', upper: false })
    const o = c.outline(48)
    expect(o).toHaveLength(48)
    expect(o[12]?.[0]).toBeCloseTo(c.neck(Math.PI / 2)[0], 9)
    expect(o[12]?.[1]).toBeCloseTo(c.neck(Math.PI / 2)[1], 9)
  })
})

describe('натуральность', () => {
  it('у верхнего центрального резца дистальный угол скруглён сильнее мезиального', () => {
    const g = GEOM.incisor_c
    const c = crownModel({ ...g, cls: 'incisor_c', upper: true })
    // верхний ряд стенки (t = 1): дистальная половина (x > 0) уже мезиальной (x < 0, мезиально −x)
    const top = c.mesh.positions.slice(26 * 72 * 3, 27 * 72 * 3)
    const xs = top.filter((_v, i) => i % 3 === 0)
    expect(Math.max(...xs)).toBeLessThan(-Math.min(...xs))
  })

  it('шейка теплее середины коронки: синего в цвете меньше', () => {
    const c = crownModel({ ...GEOM.premolar, cls: 'premolar', upper: true })
    const cols = c.mesh.colors ?? []
    const neck = col(cols, 0)
    const mid = col(cols, 13 * 72)
    expect((neck[2] ?? 0) / (neck[0] ?? 1)).toBeLessThan((mid[2] ?? 0) / (mid[0] ?? 1))
  })

  it('бугор клыка — мезиальнее середины: верхнее сечение сдвинуто к −x', () => {
    const c = crownModel({ ...GEOM.canine, cls: 'canine', upper: true })
    const top = c.mesh.positions.slice(26 * 72 * 3, 27 * 72 * 3).filter((_v, i) => i % 3 === 0)
    expect(top.reduce((a, b) => a + b, 0) / top.length).toBeLessThan(0)
  })
})
