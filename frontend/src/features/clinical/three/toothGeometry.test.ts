import { describe, expect, it } from 'vitest'
import { finite, triangles, vertices } from './mesh'
import { buildCrown, buildRoots, buildScrew, crossSec, profAt, reliefFn, SURF, toCls, type Cls } from './toothGeometry'

/* Геометрия зуба — чисто вычислимая: у каждого класса и челюсти коронка даёт
   ровно пять групп с треугольниками в порядке поверхностей, корни — по числу с
   сервера, винт — замкнутое тело вращения; всё конечное и в размерах сервера. */

const GEOM: Record<Cls, { md: number; bl: number; crown: number; root: number }> = {
  incisor_c: { md: 8.52, bl: 7.16, crown: 10.5, root: 11.7 },
  incisor_l: { md: 6.6, bl: 6.3, crown: 9.0, root: 11.7 },
  canine: { md: 7.8, bl: 8.2, crown: 10.0, root: 14.5 },
  premolar: { md: 7.48, bl: 9.5, crown: 8.5, root: 12.5 },
  molar: { md: 10.5, bl: 11.03, crown: 7.5, root: 11.2 },
}

describe('коронка', () => {
  for (const cls of Object.keys(GEOM) as Cls[]) {
    for (const upper of [true, false]) {
      it(`${cls} ${upper ? 'сверху' : 'снизу'}: пять групп O V L M D, все с треугольниками, размеры сервера`, () => {
        const g = GEOM[cls]
        const m = buildCrown({ ...g, cls, upper })
        expect(m.groups.map((x) => x.materialIndex)).toEqual([0, 1, 2, 3, 4])
        expect(m.groups.every((x) => x.count > 0 && x.count % 3 === 0)).toBe(true)
        expect(m.groups.map((x) => x.start)).toEqual(m.groups.map((_x, i) => m.groups.slice(0, i).reduce((s, y) => s + y.count, 0)))
        expect(m.index.length).toBe(m.groups.reduce((s, x) => s + x.count, 0))
        expect(finite(m)).toBe(true)
        // габариты: ширина по x ≈ md (профиль ≤ 1.02), глубина по z ≈ bl, высота — коронка плюс рельеф
        const xs = m.positions.filter((_v, i) => i % 3 === 0)
        const ys = m.positions.filter((_v, i) => i % 3 === 1)
        const zs = m.positions.filter((_v, i) => i % 3 === 2)
        expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(g.md * 1.0, 0)
        expect(Math.max(...zs) - Math.min(...zs)).toBeLessThanOrEqual(g.bl * 1.03)
        expect(Math.min(...ys)).toBeCloseTo(0, 5)
        expect(Math.max(...ys)).toBeGreaterThanOrEqual(g.crown)
        expect(Math.max(...ys)).toBeLessThan(g.crown + 3)
      })
    }
  }

  it('порядок групп — порядок поверхностей: materialIndex = буква', () => {
    expect([...SURF]).toEqual(['O', 'V', 'L', 'M', 'D'])
    const m = buildCrown({ ...GEOM.molar, cls: 'molar', upper: true })
    // площадка (O) — самая большая по счёту треугольников только у моляра с кольцами; у всех — непустая
    expect(m.groups[0]?.count).toBeGreaterThan(0)
  })

  it('незнакомый класс с сервера рисуется моляром, а не падает', () => {
    expect(toCls('molar')).toBe('molar')
    expect(toCls('incisor_l')).toBe('incisor_l')
    expect(toCls('zub')).toBe('molar')
    expect(triangles(buildCrown({ ...GEOM.molar, cls: 'zub', upper: false }))).toBeGreaterThan(1000)
  })
})

describe('профиль и сечение', () => {
  it('сплайн проходит через опорные точки: шейка и режущий край', () => {
    const prof: [number, number, number][] = [[0, 0.8, 0.8], [0.5, 1, 1], [1, 0.9, 0.9]]
    expect(profAt(prof, 0)).toEqual([0.8, 0.8])
    expect(profAt(prof, 1).map((v) => Math.round(v * 1000) / 1000)).toEqual([0.9, 0.9])
    const mid = profAt(prof, 0.5)
    expect(mid[0]).toBeCloseTo(1, 5)
  })

  it('суперэллипс: на осях — полуоси, на диагонали — квадратнее эллипса', () => {
    expect(crossSec(0, 5, 3, 2)).toEqual([5, 0])
    const [x, z] = crossSec(Math.PI / 2, 5, 3, 2)
    expect(x).toBeCloseTo(0, 10)
    expect(z).toBeCloseTo(3, 10)
    const ell = crossSec(Math.PI / 4, 5, 5, 2)
    const sq = crossSec(Math.PI / 4, 5, 5, 3.2)
    expect(Math.hypot(sq[0], sq[1])).toBeGreaterThan(Math.hypot(ell[0], ell[1]))
  })

  it('рельеф: у резца плоский край, у моляра бугры выше борозды, всё ≥ 0', () => {
    expect(reliefFn('incisor_c', true)(0.3, 0.2)).toBe(0)
    const molar = reliefFn('molar', true)
    expect(molar(-0.48, 0.51)).toBeGreaterThan(molar(0.02, 0))
    expect(molar(0.02, 0)).toBeGreaterThanOrEqual(0)
    const lower = reliefFn('molar', false)
    expect(lower(0.66, 0.36)).toBeGreaterThan(0)
  })
})

describe('корни и винт', () => {
  it('число корней — с сервера: 1, 2 и 3 дают разный объём сетки, все конечные', () => {
    const one = buildRoots({ ...GEOM.incisor_c, cls: 'incisor_c', roots: 1 })
    const two = buildRoots({ ...GEOM.premolar, cls: 'premolar', roots: 2 })
    const three = buildRoots({ ...GEOM.molar, cls: 'molar', roots: 3 })
    expect(vertices(one)).toBeLessThan(vertices(two))
    expect(vertices(two)).toBeLessThan(vertices(three))
    for (const m of [one, two, three]) {
      expect(finite(m)).toBe(true)
      expect(triangles(m)).toBeGreaterThan(100)
      // корни уходят вниз от шейки на длину сервера, не длиннее ×1.02 плюс шейка
      const ys = m.positions.filter((_v, i) => i % 3 === 1)
      expect(Math.max(...ys)).toBeCloseTo(0, 5)
      expect(Math.min(...ys)).toBeLessThan(-GEOM.incisor_c.root * 0.9)
    }
    const ys3 = three.positions.filter((_v, i) => i % 3 === 1)
    expect(Math.min(...ys3)).toBeGreaterThan(-(2.4 * 0.62 + GEOM.molar.root * 1.02) - 1e-6)
  })

  it('винт: тело вращения радиуса r, высотой 11 мм вниз от площадки', () => {
    const s = buildScrew(3)
    expect(finite(s)).toBe(true)
    const xs = s.positions.filter((_v, i) => i % 3 === 0)
    const ys = s.positions.filter((_v, i) => i % 3 === 1)
    expect(Math.max(...xs)).toBeCloseTo(3, 5)
    expect(Math.min(...ys)).toBe(-11)
    expect(Math.max(...ys)).toBeCloseTo(0.4, 5)
    expect(s.groups).toHaveLength(1)
  })
})
