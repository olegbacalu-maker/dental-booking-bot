import { describe, expect, it } from 'vitest'
import { archCurve, det3, GAP, layoutArch, toWorld } from './arch'

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

  it('⭐ средняя линия не выделяется: пара 11–21 (41–31) развёрнута и раскрыта у губы не больше соседних', () => {
    /* Щель 11–21 (Олег 24.10): у параболы кривизна наибольшая в вершине, то
       есть ровно между центральными резцами, — коронки по касательной
       расходились на 42°, клин у губных углов 3,2 мм против 1,9 у 12–11.
       Коронка здесь — прямоугольник md × bl в базисе места; клин — расстояние
       между губными углами, обращёнными друг к другу. Размеры — как у
       `teeth_svg.tooth_geom` (24.10) и ровные 8 × 7: форма, а не числа. */
    const REAL: Record<number, [number, number]> = {
      11: [8.52, 7.16], 12: [6.73, 6.46], 13: [7.62, 8.07], 14: [7.48, 9.5],
      15: [7.16, 9.09], 16: [10.5, 11.03], 17: [9.98, 10.47], 18: [9.24, 9.7],
      41: [5.79, 6.55], 42: [6.26, 6.88], 43: [7.01, 7.57], 44: [7.48, 8.0],
      45: [7.16, 7.66], 46: [10.5, 10.08], 47: [9.98, 9.58], 48: [9.24, 8.87],
    }
    const real = (n: number): [number, number] => REAL[(n >= 30 ? 40 : 10) + (n % 10)] ?? [8, 7]
    for (const size of [real, (): [number, number] => [8, 7]]) {
      for (const [list, upper, l2, l1, r1, r2] of [[UPPER, true, 12, 11, 21, 22], [LOWER, false, 42, 41, 31, 32]] as const) {
        const lay = layoutArch(list.map((n) => ({ n, md: size(n)[0] })), upper)
        const at = (n: number) => lay.teeth.find((t) => t.n === n)!
        const turn = (a: number, b: number): number => {
          const za = at(a).zAxis
          const zb = at(b).zAxis
          return (Math.acos(Math.min(1, za[0] * zb[0] + za[2] * zb[2])) * 180) / Math.PI
        }
        const wedge = (a: number, b: number): number => {
          const corner = (n: number, m: number): [number, number] => {
            const [md, bl] = size(n)
            const o = at(m).position
            const c = [toWorld(at(n), [-md / 2, 0, bl / 2]), toWorld(at(n), [md / 2, 0, bl / 2])]
              .sort((p, q) => Math.hypot(p[0] - o[0], p[2] - o[2]) - Math.hypot(q[0] - o[0], q[2] - o[2]))[0]!
            return [c[0], c[2]]
          }
          const p = corner(a, b)
          const q = corner(b, a)
          return Math.hypot(p[0] - q[0], p[1] - q[1])
        }
        const mid = turn(l1, r1)
        expect(mid).toBeLessThanOrEqual(turn(l2, l1))
        expect(mid).toBeLessThanOrEqual(turn(r1, r2))
        expect(wedge(l1, r1)).toBeLessThanOrEqual(wedge(l2, l1))
        expect(wedge(l1, r1)).toBeLessThanOrEqual(wedge(r1, r2))
      }
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
