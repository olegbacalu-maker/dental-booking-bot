import { describe, expect, it } from 'vitest'
import { buildJaw, LOWER, shapesOf, UPPER } from '../../../test/jaws'
import { GAP, GAP_CLOSED, type PlacedTooth } from './arch'
import { blendPose, occlusionK, SCHEMATIC_CLASS_SHIFT_MM, SCHEMATIC_TILT_II1_DEG, SCHEMATIC_TILT_II2_DEG, ZERO_POSE, type OcclRecord } from './occlusion'
import {
  CONTACT_ONLY_III, gap34, gapIncCanine, molarGaps, occlusionPlan, OVERBITE_AFTER_TILT, OVERJET_STOP_AT_CANINE, placeOf,
  planBite, SEGMENT_FROM, sweep, ZERO_TEETH, type Body,
} from './occlusionPlan'

/* Прикус в 3D, этап 4 («ocluzie»): запись → план (поза нижней челюсти + места зубов)
   на своих моделях зубов — тем же путём, что сцена (`test/jaws`). Решения Олега и
   координатора 07.11 — `occlusionPlan.ts`; числа «замер модели», не клиника.
   ⚠️ Разные классы сторон подбирают «веер» перебором (~0,4 с на запись в jsdom; полный
   прогон гоняет ~11 процессов — в 3–10 раз медленнее): своё время у этих проверок. */

const SLOW = { timeout: 30000 }
const C = (GAP - GAP_CLOSED) / 2
const S = shapesOf(buildJaw(UPPER, true), buildJaw(LOWER, false))
const plan = (rec: OcclRecord) => {
  const p = occlusionPlan(rec, S, C)
  if (!p) throw new Error('нет плана')
  return p
}
const bite = (rec: OcclRecord) => {
  const p = plan(rec)
  const b = planBite(S, p.teeth, p.jaw, -C, C)
  if (!b) throw new Error('нет замера')
  return { p, b: b.bite }
}

/** куб со стороной a, сдвинутый в (x, y, z): 8 вершин, 12 треугольников */
function cube(x: number, y: number, z: number, a = 1): Body {
  const p: number[] = []
  for (const dx of [0, a]) for (const dy of [0, a]) for (const dz of [0, a]) p.push(x + dx, y + dy, z + dz)
  const f = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
  const idx: number[] = []
  for (const [a0, b, c, d] of f) idx.push(a0!, b!, c!, a0!, c!, d!)
  return { p, idx }
}

describe('прогон до касания (`sweep`)', () => {
  it('расстояние вдоль направления, минус — наложение, мимо — Infinity', () => {
    expect(sweep(cube(0, 0, 0), cube(0, 3, 0), [0, 1, 0])).toBeCloseTo(2, 9)
    expect(sweep(cube(0, 0, 0), cube(0, 0.6, 0), [0, 1, 0])).toBeCloseTo(-0.4, 9)
    expect(sweep(cube(0, 0, 0), cube(5, 3, 0), [0, 1, 0])).toBe(Infinity)
    // B позади по ходу — не встретятся
    expect(sweep(cube(0, 3, 0), cube(0, 0, 0), [0, 1, 0])).toBe(Infinity)
    // наклонное направление: по z на 2, ход вдоль −z
    expect(sweep(cube(0, 0, 3), cube(0, 0, 0), [0, 0, -1])).toBeCloseTo(2, 9)
  })
})

describe('места зубов по плану (`placeOf`)', () => {
  const t = { ...ZERO_TEETH, tiltC: 10, tiltL: 10, incZ: 1, segR: -4, segL: 4, fan: 0.2, fanPivot: 0.1 }
  const p0 = (n: number): PlacedTooth => S.get(n)!.place

  it('⭐ разомкнуто (k = 0) и нулевой план — ТОТ ЖЕ объект места (побайтно прежнее положение, Q3)', () => {
    for (const n of [11, 12, 13, 16, 41, 43, 44, 46, 31, 34]) {
      expect(placeOf(n, p0(n), t, 0)).toBe(p0(n))
      expect(placeOf(n, p0(n), ZERO_TEETH, 1)).toBe(p0(n))
    }
  })

  it('кого двигает: верхние резцы — наклон и сдвиг, нижние 4–8 — сегмент своей стороны, 43–33 — веер; клыки верха и моляры верха — нет', () => {
    for (const n of [13, 23, 16, 26, 14]) expect(placeOf(n, p0(n), t, 1)).toBe(p0(n))
    expect(placeOf(46, p0(46), t, 1).position[2] - p0(46).position[2]).toBeCloseTo(-4, 9)
    expect(placeOf(36, p0(36), t, 1).position[2] - p0(36).position[2]).toBeCloseTo(4, 9)
    expect(SEGMENT_FROM).toBe(4)
    expect(placeOf(44, p0(44), t, 1).position[2] - p0(44).position[2]).toBeCloseTo(-4, 9)
    expect(placeOf(43, p0(43), t, 1)).not.toBe(p0(43))
    expect(placeOf(11, p0(11), t, 1).position[2] - p0(11).position[2]).toBeCloseTo(1, 9)
  })

  it('⭐ «веер» вокруг середины 41|31: средняя линия на месте (боковое смещение даёт только dx)', () => {
    const pivot = (p0(41).position[2] + p0(31).position[2]) / 2
    const tt = { ...ZERO_TEETH, fan: 0.26, fanPivot: pivot }
    const a = placeOf(41, p0(41), tt, 1).position
    const b = placeOf(31, p0(31), tt, 1).position
    expect((a[0] + b[0]) / 2).toBeCloseTo(0, 9)
    expect((a[2] + b[2]) / 2).toBeCloseTo(pivot, 9)
  })
})

describe('запись → план (свои модели, сомкнуто)', () => {
  it('⭐ пустая запись и I класс: ни один зуб не двигается, контакт не трогает I по умолчанию (Q1)', () => {
    const e = plan({})
    expect(e.teeth).toEqual(ZERO_TEETH)
    expect(e.jaw.dy).toBe(0)
    const i = bite({ angle_dr: 'I', angle_st: 'I' })
    expect(i.p.teeth).toEqual(ZERO_TEETH)
    expect(i.p.jaw.dy).toBe(0)
    expect(i.b.oj).toBeCloseTo(2.7, 1)
    expect(i.b.ob).toBeCloseTo(1.39, 1)
  })

  it('II/1: резцы вперёд на схематичный наклон, класс по ориентирам; overjet растёт, overbite меняется (не записан)', () => {
    const r = bite({ angle_dr: 'II/1', angle_st: 'II/1' })
    expect([r.p.teeth.tiltC, r.p.teeth.tiltL]).toEqual([SCHEMATIC_TILT_II1_DEG.c, SCHEMATIC_TILT_II1_DEG.l])
    expect(r.b.relR).toBeCloseTo(SCHEMATIC_CLASS_SHIFT_MM, 1)
    expect(r.b.relL).toBeCloseTo(SCHEMATIC_CLASS_SHIFT_MM, 1)
    expect(r.b.oj).toBeCloseTo(8.31, 1)
    expect(r.b.ob).toBeCloseTo(0.96, 1)
  })

  it('II/2: центральные назад, боковые вперёд; разные подтипы сторон — без наклона', () => {
    const r = bite({ angle_dr: 'II/2', angle_st: 'II/2' })
    expect([r.p.teeth.tiltC, r.p.teeth.tiltL]).toEqual([SCHEMATIC_TILT_II2_DEG.c, SCHEMATIC_TILT_II2_DEG.l])
    expect(r.b.oj).toBeCloseTo(4.82, 1)
    const mixed = plan({ angle_dr: 'II/1', angle_st: 'II/2' })
    expect([mixed.teeth.tiltC, mixed.teeth.tiltL]).toEqual([0, 0])
  })

  it('⭐ записанный overbite после наклона — число врача (±0,01)', () => {
    expect(OVERBITE_AFTER_TILT).toBe(true)
    for (const [rec, ob] of [[{ angle_dr: 'II/1', angle_st: 'II/1', overbite: '3' }, 3], [{ angle_dr: 'II/2', angle_st: 'II/2', overbite: '4' }, 4]] as const) {
      expect(Math.abs(bite(rec).b.ob - ob)).toBeLessThan(0.01)
    }
  })

  it('записанный overjet: резцы до записанного (9 — вперёд), назад — не дальше клыков, недобор виден', () => {
    expect(OVERJET_STOP_AT_CANINE).toBe(true)
    const nine = bite({ angle_dr: 'II/1', angle_st: 'II/1', overjet: '9' })
    expect(Math.abs(nine.b.oj - 9)).toBeLessThan(0.02)
    expect(nine.p.teeth.incZ).toBeGreaterThan(0)
    expect(Math.abs(nine.p.rest.oj)).toBeLessThan(0.02)
    const five = bite({ angle_dr: 'II/1', angle_st: 'II/1', overjet: '5' })
    expect(five.p.teeth.incZ).toBeLessThan(0)
    // резцы упёрлись в клыки: наложения нет, а недобор — число в плане, не спрятан
    expect(gapIncCanine(S, five.p.teeth)).toBeGreaterThan(-0.02)
    expect(five.p.rest.oj).toBeLessThan(-2)
    expect(five.b.oj - 5).toBeCloseTo(-five.p.rest.oj, 2)
  })

  it('⭐ III без overbite — до первого контакта 16/46 и 26/36 (без наложения), с overbite — его число', () => {
    expect(CONTACT_ONLY_III).toBe(true)
    const iii = plan({ angle_dr: 'III', angle_st: 'III' })
    const g = molarGaps(S, iii.teeth, iii.jaw, -C, C)
    expect(Math.min(g.R, g.L)).toBeGreaterThan(-0.01)
    expect(Math.min(g.R, g.L)).toBeLessThan(0.01)
    const ob1 = bite({ angle_dr: 'III', angle_st: 'III', overbite: '1' })
    expect(Math.abs(ob1.b.ob - 1)).toBeLessThan(0.01)
    expect(ob1.b.oj).toBeLessThan(0)
  })

  it('⭐ разные классы сторон: сегменты по сторонам, челюсть не поворачивается, промежутки 3|4 без наложения', SLOW, () => {
    for (const [r, l] of [['II/1', 'III'], ['III', 'II/1']] as const) {
      const { p, b } = bite({ angle_dr: r, angle_st: l })
      expect(p.jaw.yaw).toBe(0)
      const k = (a: string) => (a === 'III' ? -1 : 1) * SCHEMATIC_CLASS_SHIFT_MM
      expect(Math.abs(b.relR - k(r))).toBeLessThan(0.1)
      expect(Math.abs(b.relL - k(l))).toBeLessThan(0.1)
      const g = gap34(S, p.teeth)
      expect(Math.min(g.R, g.L)).toBeGreaterThan(-0.02)
      // веер ровно настолько, насколько нужно: меньший промежуток почти закрыт
      expect(Math.min(g.R, g.L)).toBeLessThan(0.5)
      expect(Math.sign(p.teeth.fan)).toBe(r === 'III' ? 1 : -1)
      // стороны с III — контакт моляров по первой паре
      const m = molarGaps(S, p.teeth, p.jaw, -C, C)
      expect(Math.min(m.R, m.L)).toBeGreaterThan(-0.01)
      expect(Math.min(m.R, m.L)).toBeLessThan(0.02)
    }
  })

  it('средняя линия — только из записи: 3 мм stânga при разных сторонах — dx = +3', SLOW, () => {
    const p = plan({ angle_dr: 'II/1', angle_st: 'III', mediana_mm: '3', mediana_spre: 'stanga' })
    expect(p.jaw.dx).toBe(3)
    expect(p.jaw.yaw).toBe(0)
  })
})

describe('«Parodont» снимает план прикуса (координатор 08.11)', () => {
  it('⭐ в «Parodont» при «Ocluzie» и записи III — доля 0: челюсть, зубы и десна на местах раскладки; выход — план снова', SLOW, () => {
    const p = plan({ angle_dr: 'III', angle_st: 'III' })
    const mixed = plan({ angle_dr: 'II/1', angle_st: 'III' })
    // «Ocluzie» вкл. (смыкание полное), «Parodont» вкл.
    const k = occlusionK(C, C, true)
    expect(k).toBe(0)
    expect(blendPose(p.jaw, k)).toEqual(ZERO_POSE)
    for (const n of [11, 41, 43, 44, 46, 36]) expect(placeOf(n, S.get(n)!.place, mixed.teeth, k)).toBe(S.get(n)!.place)
    // выход из «Parodont» — тот же план целиком
    const back = occlusionK(C, C, false)
    expect(back).toBe(1)
    expect(blendPose(p.jaw, back)).toEqual(p.jaw)
    expect(placeOf(46, S.get(46)!.place, mixed.teeth, back)).not.toBe(S.get(46)!.place)
    // разомкнуто — 0 и без «Parodont» (Q3); на полпути смыкания — доля
    expect(occlusionK(0, C, false)).toBe(0)
    expect(occlusionK(C / 2, C, false)).toBeCloseTo(0.5, 12)
  })
})
