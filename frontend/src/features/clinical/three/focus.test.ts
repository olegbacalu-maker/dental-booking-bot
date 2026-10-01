import { describe, expect, it } from 'vitest'
import { layoutArch } from './arch'
import { FOCUS_R, focusOrbit, nearestTheta } from './focus'

/* Камера у зуба — чистые числа: цель в середине коронки со смещением челюсти,
   азимут по щёчной нормали, наклон по челюсти, радиус не ниже минимума колеса. */
const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const sizes = (list: number[]) => list.map((n) => ({ n, md: 8 }))

describe('focusOrbit', () => {
  const up = layoutArch(sizes(UPPER), true)
  const lo = layoutArch(sizes(LOWER), false)
  const at = (lay: typeof up, n: number) => lay.teeth.find((t) => t.n === n)!

  it('резец спереди: камера перед дугой (резцы стоят чуть по сторонам от средней линии — азимуты зеркальны), цель — середина коронки с учётом сдвига челюсти', () => {
    const t = at(up, 11)
    const f = focusOrbit(t, 10, -3, true)
    expect(Math.abs(f.theta)).toBeLessThan(0.5)
    expect(f.theta).toBeLessThan(0)
    expect(focusOrbit(at(up, 21), 10, -3, true).theta).toBeCloseTo(-f.theta, 6)
    expect(f.target[0]).toBeCloseTo(t.position[0] + t.yAxis[0] * 5, 6)
    expect(f.target[1]).toBeCloseTo(t.position[1] + t.yAxis[1] * 5 - 3, 6)
    expect(f.target[2]).toBeCloseTo(t.position[2] + t.yAxis[2] * 5, 6)
    expect(f.r).toBe(FOCUS_R)
    expect(FOCUS_R).toBeGreaterThanOrEqual(70)
  })

  it('моляры по сторонам: камера уходит на сторону зуба (знак азимута), не остаётся спереди', () => {
    const l = focusOrbit(at(up, 18), 9, 0, true)
    const r = focusOrbit(at(up, 28), 9, 0, true)
    expect(l.theta).toBeLessThan(-0.6)
    expect(r.theta).toBeGreaterThan(0.6)
    expect(l.theta).toBeCloseTo(-r.theta, 6)
  })

  it('наклон: у верхних чуть снизу (φ > 90°), у нижних чуть сверху (φ < 90°)', () => {
    expect(focusOrbit(at(up, 16), 9, 0, true).phi).toBeGreaterThan(Math.PI / 2)
    expect(focusOrbit(at(lo, 46), 9, 0, false).phi).toBeLessThan(Math.PI / 2)
  })
})

describe('nearestTheta', () => {
  it('идёт короткой дугой и держит набежавшие обороты', () => {
    expect(nearestTheta(0, 1)).toBeCloseTo(1, 9)
    // 7 рад ≈ 0.72 рад по кругу: до 1 рад — вперёд на ~0.28, а не назад на ~6
    expect(nearestTheta(7, 1) - 7).toBeCloseTo(1 - (7 - Math.PI * 2), 9)
    // 3 → −3: через π, шаг < 0.3, а не −6
    expect(Math.abs(nearestTheta(3, -3) - 3)).toBeLessThan(0.3)
    expect(nearestTheta(0, Math.PI)).toBeCloseTo(Math.PI, 9)
  })
})
