import { describe, expect, it } from 'vitest'
import { archCurve, buildRidge, det3, GAP, layoutArch, toWorld } from './arch'
import { finite, triangles } from './mesh'

/* Раскладка — числа, а не картинка: сумма ширин равна длине дуги, мезиальная
   сторона каждого зуба смотрит к средней линии, щёчная — наружу, отражены
   ровно квадранты 2 и 4. */

const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const MD: Record<number, number> = { 1: 8.5, 2: 6.6, 3: 7.8, 4: 7.5, 5: 7.0, 6: 10.5, 7: 9.8, 8: 9.0 }
const row = (list: number[]) => list.map((n) => ({ n, md: MD[n % 10] ?? 8 }))

describe('кривая дуги', () => {
  it('длина растёт монотонно, концы — на ±A, нормаль смотрит наружу', () => {
    const cv = archCurve(10, 16, 0, -1)
    expect(cv.total).toBeGreaterThan(2 * 10)
    const a = cv.at(0)
    const b = cv.at(cv.total / 2)
    const c = cv.at(cv.total)
    expect(a.x).toBeCloseTo(-10, 5)
    expect(c.x).toBeCloseTo(10, 5)
    expect(Math.abs(b.x)).toBeLessThan(0.1)
    // «внутренняя» точка лежит внутри подковы (0, −0.45·D); нормаль в вершине смотрит от неё — вверх по y
    expect(b.ny).toBeGreaterThan(0)
    // на концах подковы нормаль уходит в стороны, прочь от средней линии
    expect(a.nx).toBeLessThan(0)
    expect(c.nx).toBeGreaterThan(0)
    // за концами — зажим
    expect(cv.at(-5).x).toBeCloseTo(a.x, 5)
    expect(cv.at(cv.total + 5).x).toBeCloseTo(c.x, 5)
  })
})

describe('расстановка', () => {
  it('сумма ширин с промежутками равна длине дуги; середины зубов идут по порядку списка', () => {
    const lay = layoutArch(row(UPPER), true)
    const cv = archCurve(lay.A, lay.D, lay.apex, -1)
    const sum = row(UPPER).reduce((s, t) => s + t.md + 0.3, 0)
    expect(cv.total).toBeCloseTo(sum, 3)
    const ss = lay.teeth.map((t) => t.s)
    expect([...ss].sort((x, y) => x - y)).toEqual(ss)
    expect(lay.teeth.at(-1)?.s).toBeLessThan(cv.total)
    expect(lay.yBase).toBe(GAP / 2)
    expect(layoutArch(row(LOWER), false).yBase).toBe(-GAP / 2)
  })

  it('мезиальная сторона (−x зуба) смотрит к средней линии у всех 32 зубов, щёчная — наружу', () => {
    for (const [list, upper] of [[UPPER, true], [LOWER, false]] as const) {
      const lay = layoutArch(row(list), upper)
      for (const t of lay.teeth) {
        const mesial = toWorld(t, [-1, 0, 0])
        const buccal = toWorld(t, [0, 0, 1])
        expect(Math.abs(mesial[0])).toBeLessThan(Math.abs(t.position[0]) + 1e-9)
        // щёчная сторона дальше от точки внутри дуги (0, apex − 0.45·D), чем центр зуба
        const inside: [number, number] = [0, lay.apex - 0.45 * lay.D]
        const dc = Math.hypot(t.position[0] - inside[0], t.position[2] - inside[1])
        const db = Math.hypot(buccal[0] - inside[0], buccal[2] - inside[1])
        expect(db).toBeGreaterThan(dc)
        // окклюзионно — к противоположной челюсти
        expect(toWorld(t, [0, 1, 0])[1] * (upper ? 1 : -1)).toBeLessThan(t.position[1] * (upper ? 1 : -1))
      }
    }
  })

  it('⭐ отражены ровно квадранты 2 и 4 (определитель базиса < 0), 1 и 3 — прямые', () => {
    const up = layoutArch(row(UPPER), true)
    const lo = layoutArch(row(LOWER), false)
    for (const t of [...up.teeth, ...lo.teeth]) {
      const q = Math.floor(t.n / 10)
      expect(det3(t.xAxis, t.yAxis, t.zAxis) < 0).toBe(q === 2 || q === 4)
      expect(t.mirror).toBe(q === 2 || q === 4)
    }
  })

  it('оси базиса единичные и взаимно перпендикулярные', () => {
    const lay = layoutArch(row(UPPER), true)
    const dot = (a: number[], b: number[]) => (a[0] ?? 0) * (b[0] ?? 0) + (a[1] ?? 0) * (b[1] ?? 0) + (a[2] ?? 0) * (b[2] ?? 0)
    for (const t of lay.teeth) {
      for (const ax of [t.xAxis, t.yAxis, t.zAxis]) expect(Math.hypot(...ax)).toBeCloseTo(1, 9)
      expect(dot(t.xAxis, t.yAxis)).toBeCloseTo(0, 9)
      expect(dot(t.xAxis, t.zAxis)).toBeCloseTo(0, 9)
      expect(dot(t.yAxis, t.zAxis)).toBeCloseTo(0, 9)
    }
  })
})

describe('десна', () => {
  it('гребень — замкнутая конечная сетка длиннее ряда, над шейками верхней челюсти', () => {
    const lay = layoutArch(row(UPPER), true)
    const m = buildRidge(lay.A, lay.D, lay.apex, lay.yBase, 1)
    expect(finite(m)).toBe(true)
    expect(triangles(m)).toBeGreaterThan(5000)
    const xs = m.positions.filter((_v, i) => i % 3 === 0)
    expect(Math.min(...xs)).toBeLessThan(-lay.A)
    expect(Math.max(...xs)).toBeGreaterThan(lay.A)
    const ys = m.positions.filter((_v, i) => i % 3 === 1)
    expect(Math.min(...ys)).toBeGreaterThan(lay.yBase - 1)
  })
})
