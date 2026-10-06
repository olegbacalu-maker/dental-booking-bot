import { describe, expect, it } from 'vitest'
import { crownModel } from './crown'
import { finite, triangles, vertices } from './mesh'
import { buildDashedLoop, buildRoots, buildScrew, reliefFn, toCls, type Cls } from './toothGeometry'

/* Части зуба, общие для всех коронок: корни по числу с сервера и по сечению
   шейки коронки, винт — замкнутое тело вращения, пунктир пустого места,
   рельеф жевательной поверхности; всё конечное и в размерах сервера. */

const GEOM: Record<Cls, { md: number; bl: number; crown: number; root: number }> = {
  incisor_c: { md: 8.52, bl: 7.16, crown: 10.5, root: 11.7 },
  incisor_l: { md: 6.6, bl: 6.3, crown: 9.0, root: 11.7 },
  canine: { md: 7.8, bl: 8.2, crown: 10.0, root: 14.5 },
  premolar: { md: 7.48, bl: 9.5, crown: 8.5, root: 12.5 },
  molar: { md: 10.5, bl: 11.03, crown: 7.5, root: 11.2 },
}
const neckOf = (cls: Cls) => crownModel({ ...GEOM[cls], cls, upper: true }).neck

describe('рельеф и класс', () => {
  it('рельеф: у резца плоский край, у моляра бугры выше борозды, всё ≥ 0', () => {
    expect(reliefFn('incisor_c', true)(0.3, 0.2)).toBe(0)
    const molar = reliefFn('molar', true)
    expect(molar(-0.48, 0.51)).toBeGreaterThan(molar(0.02, 0))
    expect(molar(0.02, 0)).toBeGreaterThanOrEqual(0)
    const lower = reliefFn('molar', false)
    expect(lower(0.66, 0.36)).toBeGreaterThan(0)
  })

  it('незнакомый класс с сервера рисуется моляром, а не падает', () => {
    expect(toCls('molar')).toBe('molar')
    expect(toCls('incisor_l')).toBe('incisor_l')
    expect(toCls('zub')).toBe('molar')
  })
})

describe('корни и винт', () => {
  it('число корней — с сервера: 1, 2 и 3 дают разный объём сетки, все конечные', () => {
    const one = buildRoots({ ...GEOM.incisor_c, cls: 'incisor_c', roots: 1 }, neckOf('incisor_c'))
    const two = buildRoots({ ...GEOM.premolar, cls: 'premolar', roots: 2 }, neckOf('premolar'))
    const three = buildRoots({ ...GEOM.molar, cls: 'molar', roots: 3 }, neckOf('molar'))
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

  it('шейка корня — сечение шейки коронки: верхнее кольцо совпадает с ним точка в точку', () => {
    const neck = neckOf('premolar')
    const m = buildRoots({ ...GEOM.premolar, cls: 'premolar', roots: 2 }, neck)
    // первое кольцо (y = 0): 48 точек по кругу
    for (const j of [0, 12, 24, 36]) {
      const [x, z] = neck((2 * Math.PI * j) / 48)
      expect(m.positions[j * 3]).toBeCloseTo(x, 9)
      expect(m.positions[j * 3 + 2]).toBeCloseTo(z, 9)
    }
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

describe('пустое место отсутствующего зуба', () => {
  it('пунктир: трубка на каждый второй отрезок контура шейки, на заданной высоте, конечная сетка', () => {
    const o = crownModel({ ...GEOM.premolar, cls: 'premolar', upper: false }).outline(48)
    const m = buildDashedLoop(o, 1.4, 0.2)
    expect(finite(m)).toBe(true)
    // 24 штриха × 2 кольца × 6 вершин; 24 × 6 граней × 2 треугольника
    expect(vertices(m)).toBe(24 * 12)
    expect(triangles(m)).toBe(24 * 12)
    const ys = m.positions.filter((_v, i) => i % 3 === 1)
    // шестигранная трубка: по высоте ±r·sin 60° вокруг заданной высоты
    expect(Math.min(...ys)).toBeCloseTo(1.4 - 0.2 * Math.sin(Math.PI / 3), 9)
    expect(Math.max(...ys)).toBeCloseTo(1.4 + 0.2 * Math.sin(Math.PI / 3), 9)
  })
})
