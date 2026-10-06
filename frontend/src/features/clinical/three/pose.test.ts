import { describe, expect, it } from 'vitest'
import { det3, layoutArch, type Vec3 } from './arch'
import { posed } from './pose'

/* Постановка (06.10): наклон не ломает базис (ортонормирован, отражённые
   квадранты остаются отражёнными), коронка наклоняется к мезиальной стороне,
   верхние резцы — вперёд, нижние моляры — к языку; шейка уходит к корню ровно
   настолько, насколько вершина выше эталонного моляра. */

const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const UP = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28].map((n) => ({ n, md: 8 }))
const LO = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38].map((n) => ({ n, md: 8 }))

describe('постановка зуба', () => {
  it('базис после наклона ортонормирован и сохраняет знак определителя (квадранты 2 и 4 отражены)', () => {
    for (const [list, upper] of [[UP, true], [LO, false]] as const) {
      const lay = layoutArch(list, upper)
      for (const p0 of lay.teeth) {
        const cls = p0.n % 10 <= 1 ? 'incisor_c' : p0.n % 10 === 3 ? 'canine' : p0.n % 10 >= 6 ? 'molar' : 'premolar'
        const p = posed(p0, cls, upper, 9, 9)
        for (const ax of [p.xAxis, p.yAxis, p.zAxis]) expect(Math.hypot(...ax)).toBeCloseTo(1, 9)
        expect(dot(p.xAxis, p.yAxis)).toBeCloseTo(0, 9)
        expect(dot(p.yAxis, p.zAxis)).toBeCloseTo(0, 9)
        expect(Math.sign(det3(p.xAxis, p.yAxis, p.zAxis))).toBe(Math.sign(det3(p0.xAxis, p0.yAxis, p0.zAxis)))
      }
    }
  })

  it('коронка 11 и 21 наклонена к средней линии и вперёд; нижний моляр — к языку', () => {
    const up = layoutArch(UP, true)
    for (const n of [11, 21]) {
      const p0 = up.teeth.find((t) => t.n === n)
      if (!p0) throw new Error('нет зуба')
      const p = posed(p0, 'incisor_c', true, 10, 9)
      // ось коронки в базисе места: к −x (мезиально) и к +z (губа)
      expect(dot(p.yAxis, p0.xAxis)).toBeLessThan(0)
      expect(dot(p.yAxis, p0.zAxis)).toBeGreaterThan(0)
    }
    const lo = layoutArch(LO, false)
    const m = lo.teeth.find((t) => t.n === 36)
    if (!m) throw new Error('нет зуба')
    expect(dot(posed(m, 'molar', false, 9, 9).yAxis, m.zAxis)).toBeLessThan(0)
  })

  it('шейка: эталонный моляр на месте, клык выше него уходит к корню на разницу вершин', () => {
    const up = layoutArch(UP, true)
    const m = up.teeth.find((t) => t.n === 16)
    const c = up.teeth.find((t) => t.n === 13)
    if (!m || !c) throw new Error('нет зуба')
    expect(posed(m, 'molar', true, 9.4, 9.4).position).toEqual(m.position)
    // у верхней челюсти корень — вверх (+y): вершина клыка на 1,9 мм выше моляра
    const pc = posed(c, 'canine', true, 11.3, 9.4)
    expect(pc.position[1] - c.position[1]).toBeCloseTo(1.9, 9)
  })
})
