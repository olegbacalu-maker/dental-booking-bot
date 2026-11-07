import { describe, expect, it } from 'vitest'
import { det3, layoutArch, type Vec3 } from './arch'
import { posed, torqued } from './pose'

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

  it('⭐ добавочный torque = torque табличный + Δ у 11 и у зеркального 21; ноль — тот же объект', () => {
    /* в базисе места ось коронки — (−sin a·cos b, cos a·cos b, sin b): torque b читается как
       asin(y · z места). У верхнего центрального резца по таблице 7°. Этап 4 «ocluzie»: II/1
       наклоняет вперёд (+), II/2 центральные назад (−) — знак обязан совпасть в обоих квадрантах. */
    const up = layoutArch(UP, true)
    for (const n of [11, 21]) {
      const p0 = up.teeth.find((t) => t.n === n)
      if (!p0) throw new Error('нет зуба')
      const p = posed(p0, 'incisor_c', true, 10, 9)
      const b = (q: typeof p): number => (Math.asin(dot(q.yAxis, p0.zAxis)) * 180) / Math.PI
      expect(b(p)).toBeCloseTo(7, 6)
      expect(b(torqued(p, 10))).toBeCloseTo(17, 6)
      expect(b(torqued(p, -12))).toBeCloseTo(-5, 6)
      const back = torqued(torqued(p, 10), -10)
      back.yAxis.forEach((v, i) => expect(v).toBeCloseTo(p.yAxis[i] as number, 12))
      expect(torqued(p, 0)).toBe(p)
      // шейка (вокруг неё поворот) на месте, базис ортонормирован
      expect(torqued(p, 10).position).toEqual(p.position)
      expect(dot(torqued(p, 10).yAxis, torqued(p, 10).zAxis)).toBeCloseTo(0, 12)
    }
  })
})
