import { describe, expect, it } from 'vitest'
import { SCULPT, SCULPT_OF } from '../../../../models/teeth.js'
import { archCurve, det3, GAP, GAP_CLOSED, layoutArch, toWorld, type PlacedTooth, type Vec3 } from './arch'
import { crownModel } from './crown'
import { biteAt, SCHEMATIC_CLASS_SHIFT_MM, jawPose, molarMark, OPEN_OB, REL_I, ZERO_POSE, type BitePoints, type JawPose, type OcclRecord } from './occlusion'
import { posed } from './pose'
import { sculptModel } from './sculpt'
import { toCls } from './toothGeometry'

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

/* Прикус по умолчанию (волна «ocluzie», этап 1): замер тем же путём, что у
   сцены — раскладка `layoutArch`, свои модели зубов (`teeth.js`), постановка
   `posed` по формуле первого моляра, смыкание групп на (GAP − GAP_CLOSED)/2.
   Размеры — `teeth_svg.tooth_geom` (07.11.2026). ⚠️ Закреплено ТЕКУЩЕЕ
   положение (бугор 16 впереди борозды 46 — II класс схемой, прототип 06.11): после ответа Олега на Q1
   (перевести в I класс) числа здесь меняются вместе с `layoutArch`. */
const GEOM: Record<'U' | 'L', Record<number, { md: number; bl: number; crown: number; cls: string }>> = {
  U: {
    1: { md: 8.52, bl: 7.16, crown: 10.5, cls: 'incisor_c' }, 2: { md: 6.73, bl: 6.46, crown: 9.0, cls: 'incisor_l' },
    3: { md: 7.62, bl: 8.07, crown: 10.0, cls: 'canine' }, 4: { md: 7.48, bl: 9.5, crown: 8.5, cls: 'premolar' },
    5: { md: 7.16, bl: 9.09, crown: 8.5, cls: 'premolar' }, 6: { md: 10.5, bl: 11.03, crown: 7.5, cls: 'molar' },
    7: { md: 9.98, bl: 10.47, crown: 7.5, cls: 'molar' }, 8: { md: 9.24, bl: 9.7, crown: 7.5, cls: 'molar' },
  },
  L: {
    1: { md: 5.79, bl: 6.55, crown: 9.0, cls: 'incisor_c' }, 2: { md: 6.26, bl: 6.88, crown: 9.5, cls: 'incisor_l' },
    3: { md: 7.01, bl: 7.57, crown: 11.0, cls: 'canine' }, 4: { md: 7.48, bl: 8.0, crown: 8.0, cls: 'premolar' },
    5: { md: 7.16, bl: 7.66, crown: 8.0, cls: 'premolar' }, 6: { md: 10.5, bl: 10.08, crown: 7.5, cls: 'molar' },
    7: { md: 9.98, bl: 9.58, crown: 7.5, cls: 'molar' }, 8: { md: 9.24, bl: 8.87, crown: 7.5, cls: 'molar' },
  },
}

interface Built { p: PlacedTooth; local: ArrayLike<number>; pts: number[]; mark: Vec3 | null }

/** Челюсть так, как её ставит сцена (`buildArch` со своими моделями): точки коронок
 *  и ориентиры моляров (`molarMark`) — в системе группы. */
function buildJaw(list: number[], upper: boolean, formula = false): Map<number, Built> {
  const geom = (n: number) => ({ ...GEOM[upper ? 'U' : 'L'][n % 10]!, root: 12, roots: 1, upper })
  const lay = layoutArch(list.map((n) => ({ n, md: geom(n).md })), upper)
  const ref = crownModel(geom(upper ? 16 : 36)).tip
  const out = new Map<number, Built>()
  for (const p0 of lay.teeth) {
    const g = geom(p0.n)
    const cm = formula ? crownModel(g) : sculptModel(SCULPT[SCULPT_OF[p0.n] ?? '']!, g)
    const p = posed(p0, toCls(g.cls), upper, cm.tip, ref)
    const pos = cm.mesh.positions
    const pts: number[] = []
    for (let i = 0; i + 2 < pos.length; i += 3) pts.push(...toWorld(p, [pos[i]!, pos[i + 1]!, pos[i + 2]!]))
    const k = p0.n % 10 === 6 ? molarMark(pos, g.md, upper) : null
    out.set(p0.n, { p, local: pos, pts, mark: k ? toWorld(p, k) : null })
  }
  return out
}

const pointsOf = (U: Map<number, Built>, L: Map<number, Built>, marks = true): BitePoints => ({
  u11: U.get(11)!.pts, l41: L.get(41)!.pts,
  c16: U.get(16)!.p.position, c26: U.get(26)!.p.position, c36: L.get(36)!.p.position, c46: L.get(46)!.p.position,
  ...(marks ? { k16: U.get(16)!.mark, k26: U.get(26)!.mark, k36: L.get(36)!.mark, k46: L.get(46)!.mark } : {}),
})

describe('прикус по умолчанию (сомкнуто, без записи)', () => {
  const U = buildJaw(UPPER, true)
  const L = buildJaw(LOWER, false)
  const close = (GAP - GAP_CLOSED) / 2
  const pts = pointsOf(U, L)
  const base = biteAt(pts, ZERO_POSE, -close, close)
  const probe = (p: JawPose): number => biteAt(pts, p, -close, close).bite.ob

  it('⭐ закреплено текущее положение: overjet ≈ 5,5, overbite ≈ 1,4, бугор впереди борозды на ≈ 2,8 мм по обе стороны (до Q1)', () => {
    expect(base.bite.byMarks).toBe(true)
    expect(base.bite.oj).toBeCloseTo(5.5, 1)
    expect(base.bite.ob).toBeCloseTo(1.39, 1)
    expect(base.bite.relR).toBeCloseTo(2.81, 1)
    expect(base.bite.relL).toBeCloseTo(base.bite.relR, 6)
    // опора наклона и рычаг — из той же раскладки
    expect(base.geo.z46).toBeLessThan(-25)
    expect(base.geo.z41 - base.geo.z46).toBeGreaterThan(20)
    expect(base.geo.half).toBeGreaterThan(20)
  })

  it('⭐ ориентиры класса: бугор 16/26 и борозда 46/36 найдены на своих моделях; приближение по центрам с REL_I сходится ±0,1', () => {
    /* Класс по Энглю — мезиально-щёчный бугор верхнего 6 против щёчной борозды
       нижнего (AAPD, PMC3481985; Олег 07.11). Замер 07.11.2026: бугор впереди
       центра 16 на 3,24 мм, борозда впереди центра 46 на 1,94 — поправка к
       «центр − центр» 1,30 мм, а не 2, как брал прототип 06.11. */
    for (const n of [16, 26]) {
      const k = U.get(n)!.mark!
      expect(k, `бугор ${n}`).not.toBeNull()
      expect(k[2] - U.get(n)!.p.position[2]).toBeCloseTo(3.24, 1)
    }
    for (const n of [46, 36]) {
      const k = L.get(n)!.mark!
      expect(k, `борозда ${n}`).not.toBeNull()
      expect(k[2] - L.get(n)!.p.position[2]).toBeCloseTo(1.94, 1)
    }
    const approx = biteAt(pointsOf(U, L, false), ZERO_POSE, -close, close).bite
    expect(approx.byMarks).toBe(false)
    expect(Math.abs(approx.relR - base.bite.relR)).toBeLessThan(0.1)
    expect(REL_I).toBe(1.3)
  })

  it('коронки-формулы (без файла моделей): ориентиров нет — замер по центрам, не по случайным точкам', () => {
    const fu = buildJaw(UPPER, true, true)
    const fl = buildJaw(LOWER, false, true)
    expect(biteAt(pointsOf(fu, fl), ZERO_POSE, -close, close).bite.byMarks).toBe(false)
  })

  it('поза ставит записанное (±0,1): I → бугор в борозде, overbite по записи; II/1 и III — на SCHEMATIC_CLASS_SHIFT_MM', () => {
    const at = (rec: OcclRecord) => biteAt(pts, jawPose(rec, base.bite, base.geo, probe), -close, close).bite
    const one = at({ angle_dr: 'I', angle_st: 'I', overbite: '2' })
    expect(Math.abs(one.relR)).toBeLessThan(0.1)
    expect(Math.abs(one.relL)).toBeLessThan(0.1)
    expect(one.ob).toBeCloseTo(2, 1)
    // overjet I класса по ориентирам — ≈ 2,7 (прототип с REL_I = 2 давал 2,0)
    expect(one.oj).toBeCloseTo(base.bite.oj - base.bite.relR, 1)
    const two = at({ angle_dr: 'II/1', angle_st: 'II/1', overbite: '3' })
    expect(two.relR).toBeCloseTo(SCHEMATIC_CLASS_SHIFT_MM, 1)
    expect(two.oj).toBeCloseTo(base.bite.oj - base.bite.relR + SCHEMATIC_CLASS_SHIFT_MM, 1)
    expect(two.ob).toBeCloseTo(3, 1)
    const three = at({ angle_dr: 'III', angle_st: 'III', overbite: '1' })
    expect(three.relR).toBeCloseTo(-SCHEMATIC_CLASS_SHIFT_MM, 1)
    expect(three.oj).toBeLessThan(0)
    // разные классы сторон: каждая сторона на своём месте (поворот вокруг вертикали)
    const mix = at({ angle_dr: 'II/2', angle_st: 'III' })
    expect(Math.abs(mix.relR - SCHEMATIC_CLASS_SHIFT_MM)).toBeLessThan(0.1)
    expect(Math.abs(mix.relL + SCHEMATIC_CLASS_SHIFT_MM)).toBeLessThan(0.1)
  })

  it('открытый прикус: наклон вокруг моляров доводится секущей до записанного overbite (±0,05)', () => {
    for (const [ob, want] of [['-3', -3], ['', OPEN_OB], ['-6', -6]] as const) {
      const rec: OcclRecord = { angle_dr: 'I', angle_st: 'I', overbite: ob, deschisa: '13–23' }
      const pose = jawPose(rec, base.bite, base.geo, probe)
      expect(pose.pitch).toBeGreaterThan(0)
      expect(Math.abs(probe(pose) - want)).toBeLessThan(0.05)
      // без замера — только первое приближение, и оно мимо: секущая нужна
      const rough = jawPose(rec, base.bite, base.geo)
      expect(Math.abs(probe(rough) - want)).toBeGreaterThan(Math.abs(probe(pose) - want))
    }
  })
})
