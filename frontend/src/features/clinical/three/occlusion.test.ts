import { describe, expect, it } from 'vitest'
import { biteAt, biteOf, blendPose, classSign, incisal, jawPose, lowerPlacement, mmOf, molarMark, OPEN_OB, poseLower, REL_I, SCHEMATIC_CLASS_SHIFT_MM, ZERO_POSE, type Bite, type JawPose, type OcclGeo } from './occlusion'

/* Прикус в 3D, этап 1: правила записи → позы на числах (замер своих моделей —
   `arch.test.ts` › «прикус по умолчанию»). Числа базы — прототипа 06.11. */

const BASE: Bite = { oj: 5.5, ob: 1.39, relR: 3.51, relL: 3.51 }
const GEO: OcclGeo = { z41: -1.37, z46: -29.85, half: 25.19 }

describe('класс по Энглю', () => {
  it('⭐ III раньше II: «III» — нижняя вперёд, «II/1» и «II/2» — назад, «I» — ноль', () => {
    expect(classSign('III')).toBe(1)
    expect(classSign('II/1')).toBe(-1)
    expect(classSign('II/2')).toBe(-1)
    expect(classSign('I')).toBe(0)
    expect(classSign('')).toBeNull()
    expect(classSign('IV')).toBeNull()
    // схематическое число, не клиническое (Q2): одно имя
    expect(SCHEMATIC_CLASS_SHIFT_MM).toBe(4)
  })

  it('миллиметры строкой: запятая, минус, пусто и мусор', () => {
    expect(mmOf('3,5')).toBe(3.5)
    expect(mmOf('-2')).toBe(-2)
    expect(mmOf(' 2.5 ')).toBe(2.5)
    expect(mmOf('')).toBeNull()
    expect(mmOf(undefined)).toBeNull()
    expect(mmOf('abc')).toBeNull()
  })
})

describe('запись → поза', () => {
  it('⭐ пусто = «не записано»: ноль, модель стоит как стоит', () => {
    expect(jawPose({}, BASE, GEO)).toEqual(ZERO_POSE)
    expect(jawPose({ angle_dr: '', angle_st: '', overjet: '', overbite: '', deschisa: '  ', mediana_mm: '', mediana_spre: '' }, BASE, GEO)).toEqual(ZERO_POSE)
  })

  it('класс по обеим сторонам → dz = rel + сдвиг класса, поворота нет', () => {
    expect(jawPose({ angle_dr: 'I', angle_st: 'I' }, BASE, GEO).dz).toBeCloseTo(3.51, 9)
    expect(jawPose({ angle_dr: 'II/1', angle_st: 'II/1' }, BASE, GEO).dz).toBeCloseTo(3.51 - SCHEMATIC_CLASS_SHIFT_MM, 9)
    // прототип: III → dz 7,51, и это НЕ II (−0,49)
    const iii = jawPose({ angle_dr: 'III', angle_st: 'III' }, BASE, GEO)
    expect(iii.dz).toBeCloseTo(7.51, 9)
    expect(iii.yaw).toBe(0)
  })

  it('⭐ сдвиг класса — одна схема на все записи: поля величины у записи нет', () => {
    // лишнее поле (как бы «мм» из чужой записи) позу не меняет
    const rec = { angle_dr: 'II/1', angle_st: 'II/1', mmR: '2' } as Parameters<typeof jawPose>[0]
    expect(jawPose(rec, BASE, GEO).dz).toBeCloseTo(3.51 - SCHEMATIC_CLASS_SHIFT_MM, 9)
  })

  it('класс записан с одной стороны — обе стороны по нему', () => {
    const p = jawPose({ angle_st: 'III' }, BASE, GEO)
    expect(p.dz).toBeCloseTo(7.51, 9)
    expect(p.yaw).toBe(0)
  })

  it('разные классы сторон → поворот вокруг вертикали: знак по стороне, точно на моляры', () => {
    // правая (−x) в III — вперёд, левая во II — назад: +yaw
    const p = jawPose({ angle_dr: 'III', angle_st: 'II/1' }, BASE, GEO)
    expect(p.yaw).toBeGreaterThan(0)
    expect(Math.sin(p.yaw) * 2 * GEO.half).toBeCloseTo(2 * SCHEMATIC_CLASS_SHIFT_MM, 9)
    expect(jawPose({ angle_dr: 'II/2', angle_st: 'III' }, BASE, GEO).yaw).toBeCloseTo(-p.yaw, 9)
    // моляры встают каждый на своё место: проверка той же формулой, что у сцены
    const m46 = poseLower([-GEO.half, 0, GEO.z46], p, 0)
    const m36 = poseLower([GEO.half, 0, GEO.z46], p, 0)
    expect(m46[2] - GEO.z46).toBeCloseTo(BASE.relR + SCHEMATIC_CLASS_SHIFT_MM, 6)
    expect(m36[2] - GEO.z46).toBeCloseTo(BASE.relL - SCHEMATIC_CLASS_SHIFT_MM, 6)
    // I и II: ровно полкласса разницы
    const half = jawPose({ angle_dr: 'I', angle_st: 'II/1' }, BASE, GEO)
    expect(poseLower([-GEO.half, 0, GEO.z46], half, 0)[2] - GEO.z46).toBeCloseTo(BASE.relR, 6)
    expect(poseLower([GEO.half, 0, GEO.z46], half, 0)[2] - GEO.z46).toBeCloseTo(BASE.relL - SCHEMATIC_CLASS_SHIFT_MM, 6)
  })

  it('класса нет, overjet есть → dz = base.oj − overjet; при классе overjet не двигает челюсть', () => {
    expect(jawPose({ overjet: '2' }, BASE, GEO).dz).toBeCloseTo(3.5, 9)
    expect(jawPose({ overjet: '-1,5' }, BASE, GEO).dz).toBeCloseTo(7, 9)
    expect(jawPose({ angle_dr: 'I', angle_st: 'I', overjet: '8' }, BASE, GEO).dz).toBeCloseTo(3.51, 9)
  })

  it('overbite → dy = overbite − base.ob (без открытого прикуса)', () => {
    expect(jawPose({ overbite: '2' }, BASE, GEO).dy).toBeCloseTo(0.61, 9)
    expect(jawPose({ overbite: '3' }, BASE, GEO).dy).toBeCloseTo(1.61, 9)
    expect(jawPose({ overbite: '-1' }, BASE, GEO).dy).toBeCloseTo(-2.39, 9)
  })

  it('средняя линия: stânga = +x, dreapta = −x, без стороны — ноль', () => {
    expect(jawPose({ mediana_mm: '3', mediana_spre: 'stanga' }, BASE, GEO).dx).toBe(3)
    expect(jawPose({ mediana_mm: '2,5', mediana_spre: 'dreapta' }, BASE, GEO).dx).toBe(-2.5)
    expect(jawPose({ mediana_mm: '3', mediana_spre: '' }, BASE, GEO).dx).toBe(0)
    // прототип: средняя линия → dx 3, dz 3,51, dy 0,61
    const p = jawPose({ angle_dr: 'I', angle_st: 'I', overbite: '2', mediana_mm: '3', mediana_spre: 'stanga', incrucisata: '24–26' }, BASE, GEO)
    expect([p.dx, p.dz, p.dy].map((v) => +v.toFixed(2))).toEqual([3, 3.51, 0.61])
  })
})

describe('открытый прикус — наклон секущей', () => {
  /* Модель: резец на рычаге от опоры у моляров, overbite = ob0 − подъём по дуге;
     поворот не линеен — первый шаг (atan2) промахивается, секущая доводит. */
  const lever = GEO.z41 - GEO.z46
  const probe = (p: JawPose): number => BASE.ob - (lever * Math.sin(p.pitch) + 2 * (1 - Math.cos(p.pitch)) * 4)

  it('опора — у моляров, dy не ставится, наклон положительный (передний отрезок вниз)', () => {
    const p = jawPose({ deschisa: '13–23', overbite: '-3' }, BASE, GEO, probe)
    expect(p.pivotZ).toBe(GEO.z46)
    expect(p.pivotY).toBe(0)
    expect(p.dy).toBe(0)
    expect(p.pitch).toBeGreaterThan(0)
    expect(probe(p)).toBeCloseTo(-3, 2)
  })

  it('без записанного overbite — OPEN_OB; без замера — первое приближение atan2', () => {
    expect(probe(jawPose({ deschisa: 'frontal' }, BASE, GEO, probe))).toBeCloseTo(OPEN_OB, 2)
    const rough = jawPose({ deschisa: 'frontal' }, BASE, GEO)
    expect(rough.pitch).toBeCloseTo(Math.atan2(BASE.ob - OPEN_OB, lever), 9)
  })
})

describe('замер по точкам', () => {
  it('режущий край и губная поверхность в полосе от края', () => {
    // верхний резец: край внизу (y = 1), губная точка у края z = 5; выше полосы — z = 9 (не в счёт)
    const up = [0, 1, 4, 0, 1.8, 5, 0, 6, 9]
    expect(incisal(up, true)).toEqual({ edgeY: 1, frontZ: 5 })
    // нижний: край вверху (y = 2)
    const lo = [0, 2, 0, 0, 1, 1, 0, -5, 7]
    expect(incisal(lo, false)).toEqual({ edgeY: 2, frontZ: 1 })
  })

  it('overjet, overbite и rel со знаками: по ориентирам, а без всех четырёх — по центрам с REL_I', () => {
    const w = {
      u11: [0, 1, 4, 0, 1.5, 5], l41: [0, 2, 0, 0, 1.2, 1],
      c16: [-27, 0, -28], c26: [27, 0, -28], c46: [-25, 0, -30], c36: [25, 0, -29],
    } as const
    const b = biteOf({ ...w, c16: [...w.c16], c26: [...w.c26], c46: [...w.c46], c36: [...w.c36] })
    expect(b.oj).toBeCloseTo(4, 9)
    expect(b.ob).toBeCloseTo(1, 9)
    expect(b.relR).toBeCloseTo(2 + REL_I, 9)
    expect(b.relL).toBeCloseTo(1 + REL_I, 9)
    expect(b.byMarks).toBe(false)
    const k = biteOf({
      ...w, c16: [...w.c16], c26: [...w.c26], c46: [...w.c46], c36: [...w.c36],
      k16: [-27, 0, -25], k26: [27, 0, -25], k46: [-25, 0, -26], k36: [25, 0, -24],
    })
    expect(k.byMarks).toBe(true)
    // бугор впереди борозды на 1 справа — II-сторона; слева позади на 1 — III-сторона
    expect(k.relR).toBeCloseTo(1, 9)
    expect(k.relL).toBeCloseTo(-1, 9)
    // одного ориентира нет — обе стороны по центрам, не вперемешку
    expect(biteOf({ ...w, c16: [...w.c16], c26: [...w.c26], c46: [...w.c46], c36: [...w.c36], k16: [-27, 0, -25], k26: null }).byMarks).toBe(false)
  })

  it('ориентиры моляра: бугор — высшая точка щёчного края мезиально, борозда — низшая между буграми; гладкая коронка — null', () => {
    // щёчный край (z = 4) с рельефом y(x): у верхнего бугры на −2,5 и +2,5; у нижнего бугры на −3 и 0, борозда на −1,5
    const ridge = (f: (x: number) => number): number[] => {
      const a: number[] = [0, 0, 0]
      for (let x = -5; x <= 5.001; x += 0.25) a.push(x, f(x), 4)
      return a
    }
    const up = molarMark(ridge((x) => 7 - Math.min((x + 2.5) ** 2, (x - 2.5) ** 2) * 0.1), 10.5, true)
    expect(up?.[0]).toBeCloseTo(-2.5, 6)
    const lo = molarMark(ridge((x) => (x < -1.5 ? 7 - (x + 3) ** 2 * 0.2 : 7 - x * x * 0.2)), 10.5, false)
    expect(lo?.[0]).toBeCloseTo(-1.5, 6)
    expect(molarMark(ridge(() => 6), 10.5, true)).toBeNull()
    expect(molarMark(ridge((x) => 6 - x * x * 0.05), 10.5, false)).toBeNull()
  })

  it('поза нижней — формула сцены: ноль ничего не двигает, сдвиг и подъём складываются, наклон опускает передний отрезок', () => {
    expect(poseLower([1, 2, 3], ZERO_POSE, 4)).toEqual([1, 6, 3])
    expect(poseLower([1, 2, 3], { ...ZERO_POSE, dx: 1, dy: -1, dz: 2 }, 4)).toEqual([2, 5, 5])
    const tilt = poseLower([0, 0, 10], { ...ZERO_POSE, pitch: 0.1 }, 0)
    expect(tilt[1]).toBeLessThan(0)
    // точка на опоре стоит при любом повороте
    const pin = poseLower([0, 0, -30], { ...ZERO_POSE, pitch: 0.3, yaw: 0.2, pivotZ: -30 }, 0)
    pin.forEach((v, i) => expect(v).toBeCloseTo([0, 0, -30][i]!, 9))
  })

  it('biteAt при нулевой позе = biteOf по сдвинутым группам', () => {
    const pts = {
      u11: [0, 1, 4, 0, 1.5, 5], l41: [0, -2, 0, 0, -3, 1],
      c16: [-27, 0, -28] as [number, number, number], c26: [27, 0, -28] as [number, number, number],
      c46: [-25, 0, -30] as [number, number, number], c36: [25, 0, -29] as [number, number, number],
    }
    const { bite, geo } = biteAt(pts, ZERO_POSE, -0.5, 4)
    expect(bite.ob).toBeCloseTo(2 - 0.5 - (1 - 0.5) + 0.5, 9)
    expect(bite.oj).toBeCloseTo(5 - 1, 9)
    expect(geo).toEqual({ z41: 1, z46: -29.5, half: 25 })
  })
})

describe('поза только сомкнуто (Q3)', () => {
  const want: JawPose = { dx: 3, dy: 0.6, dz: 3.5, yaw: 0.1, pitch: 0.14, pivotY: 0, pivotZ: -29.85 }

  it('⭐ разомкнуто (k = 0) — ровно ноль: группа нижней на (0, y0, 0) без поворота, побайтно как до прикуса', () => {
    for (const y0 of [0, 1.7, -70]) {
      const pl = lowerPlacement(blendPose(want, 0), y0)
      // до волны «ocluzie» placeJaws ставил только y; x и z оставались +0, углы — +0
      expect(pl.position.map((v) => Object.is(v, 0) ? 'z' : v)).toEqual(['z', y0 === 0 ? 'z' : y0, 'z'])
      expect(pl.rotation.every((v) => Object.is(v, 0))).toBe(true)
    }
    expect(blendPose(want, -0.01)).toEqual(ZERO_POSE)
  })

  it('сомкнуто (k = 1) — запрошенная целиком; по пути — доля, опора не едет', () => {
    expect(blendPose(want, 1)).toEqual(want)
    expect(blendPose(want, 1.2)).toEqual(want)
    const half = blendPose(want, 0.5)
    expect(half.dz).toBeCloseTo(1.75, 12)
    expect(half.pitch).toBeCloseTo(0.07, 12)
    expect(half.pivotZ).toBe(want.pivotZ)
    // положение группы = poseLower точки (0, 0, 0): одна формула с замером
    expect(lowerPlacement(want, 4).position).toEqual(poseLower([0, 0, 0], want, 4))
  })
})
