import { describe, expect, it } from 'vitest'
import { archCurve, layoutArch } from './arch'
import { crownModel } from './crown'
import { anchorsFor, archFrame, buildGum, linRgb, marginPoint, RIB, stripesFor, type GumKind, type GumTooth } from './gum'
import { finite } from './mesh'
import { posed } from './pose'
import { toCls } from './toothGeometry'

/* Десна по краю (06.10): сетка цела и смотрит наружу у обеих челюстей, край
   садится на стенку зуба, рецессия опускает его ниже шейки, на месте
   отсутствующего зуба — гребень без дыры, полоса кармана — только где её
   прислали. С 25.10: тело без швов вдоль дуги, беззубый гребень — валик, круг
   лунки лежит на десне. */

const UP = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
const LO = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
const CLS: Record<number, [string, number, number, number]> = {
  1: ['incisor_c', 8.6, 7.0, 10.5], 2: ['incisor_l', 6.6, 6.2, 9.0], 3: ['canine', 7.6, 8.0, 10.0], 4: ['premolar', 7.0, 9.0, 8.5],
  5: ['premolar', 6.8, 9.0, 8.5], 6: ['molar', 10.5, 11.0, 7.5], 7: ['molar', 9.5, 10.5, 7.5], 8: ['molar', 8.8, 10.0, 7.0],
}

interface Opts { rec?: Record<number, number[]>; kinds?: Record<number, GumKind>; red?: number[] }

function jaw(list: number[], upper: boolean, o: Opts = {}) {
  const geo = (n: number) => {
    const [cls, md, bl, crown] = CLS[n % 10] as [string, number, number, number]
    return { md, bl, crown, root: 12, roots: 1, cls, upper }
  }
  const lay = layoutArch(list.map((n) => ({ n, md: geo(n).md })), upper)
  const models = new Map(list.map((n) => [n, crownModel(geo(n))]))
  const ref = models.get(upper ? 16 : 36)?.tip ?? 9
  const red = linRgb(0xdc2626)
  const teeth: GumTooth[] = lay.teeth.map((p0) => {
    const g = geo(p0.n)
    const c = models.get(p0.n) as ReturnType<typeof crownModel>
    const p = posed(p0, toCls(g.cls), upper, c.tip, ref)
    const sites = o.red?.includes(p0.n) ? [red, red, red, red, red, red] : null
    return {
      n: p0.n, kind: o.kinds?.[p0.n] ?? 'tooth', s: p.s, md: g.md, bl: g.bl, root: g.root,
      position: p.position, xAxis: p.xAxis, yAxis: p.yAxis, zAxis: p.zAxis, surf: c.surf,
      anchors: anchorsFor(toCls(g.cls), o.rec?.[p0.n] ?? null, false, false), stripe: stripesFor(sites),
    }
  })
  const gum = buildGum({ A: lay.A, D: lay.D, apex: lay.apex, yBase: lay.yBase, occ: upper ? -1 : 1, teeth })
  return { lay, teeth, gum }
}

/** Сумма z-составляющих площадных нормалей треугольников впереди дуги. */
function frontNz(P: number[], idx: number[], apex: number): number {
  let sz = 0
  for (let i = 0; i < idx.length; i += 3) {
    const a = (idx[i] ?? 0) * 3
    const b = (idx[i + 1] ?? 0) * 3
    const c = (idx[i + 2] ?? 0) * 3
    const cx = ((P[a] ?? 0) + (P[b] ?? 0) + (P[c] ?? 0)) / 3
    const cz = ((P[a + 2] ?? 0) + (P[b + 2] ?? 0) + (P[c + 2] ?? 0)) / 3
    if (Math.abs(cx) > 3 || cz < apex + 2) continue
    const ux = (P[b] ?? 0) - (P[a] ?? 0)
    const uy = (P[b + 1] ?? 0) - (P[a + 1] ?? 0)
    const vx = (P[c] ?? 0) - (P[a] ?? 0)
    const vy = (P[c + 1] ?? 0) - (P[a + 1] ?? 0)
    sz += ux * vy - uy * vx
  }
  return sz
}

/** Ближайшая вершина сетки к точке, мм. */
function nearest(P: number[], q: number[]): number {
  let best = Infinity
  for (let i = 0; i < P.length; i += 3) {
    best = Math.min(best, Math.hypot((P[i] ?? 0) - (q[0] ?? 0), (P[i + 1] ?? 0) - (q[1] ?? 0), (P[i + 2] ?? 0) - (q[2] ?? 0)))
  }
  return best
}

describe('десна по краю', () => {
  for (const upper of [true, false]) {
    it(`${upper ? 'верхняя' : 'нижняя'}: сетка цела, цвет у каждой вершины, нормаль впереди — наружу`, () => {
      const { gum, lay } = jaw(upper ? UP : LO, upper)
      expect(finite(gum)).toBe(true)
      expect(gum.colors?.length).toBe(gum.positions.length)
      const nv = gum.positions.length / 3
      expect(nv).toBeGreaterThan(5000)
      expect(nv).toBeLessThan(60000)
      expect(frontNz(gum.positions, gum.index, lay.apex)).toBeGreaterThan(0)
    })
  }

  it('⭐ дуга десны — та же, что у зубов: середина каждого зуба лежит на ней на своей длине дуги (24.10)', () => {
    // своя формула у десны (до 24.10 — копия параболы) разошлась бы с зубами
    // молча: правка формы в `arch.ts` сдвигала бы зубы, а десну оставляла
    for (const [list, upper] of [[UP, true], [LO, false]] as const) {
      const { lay } = jaw(list, upper)
      const F = archFrame(lay.A, lay.D, lay.apex)
      expect(F.total).toBeCloseTo(archCurve(lay.A, lay.D, lay.apex, -1).total, 2)
      for (const t of lay.teeth) {
        const f = F.at(t.s)
        expect(Math.hypot(f.x - t.position[0], f.z - t.position[2])).toBeLessThan(0.01)
        expect(Math.abs(f.nx * t.zAxis[0] + f.nz * t.zAxis[2])).toBeGreaterThan(0.9999)
      }
    }
  })

  it('край садится на стенку зуба: у щёчной середины 11 вершина десны не дальше 0,3 мм от точки края', () => {
    const { gum, teeth } = jaw(UP, true)
    const t = teeth.find((x) => x.n === 11) as GumTooth
    expect(nearest(gum.positions, marginPoint(t, Math.PI / 2))).toBeLessThan(0.3)
  })

  it('рецессия 3 мм у V опускает край ниже шейки, сосочек остаётся', () => {
    const a = anchorsFor('incisor_c', [0, 3, 0, 0, 0, 0], false, false)
    expect(a[2]).toBe(-3)
    expect(a[0]).toBeGreaterThan(3)
    const healthy = jaw(LO, false).teeth.find((x) => x.n === 41) as GumTooth
    const { gum, teeth } = jaw(LO, false, { rec: { 41: [0, 3, 0, 0, 0, 0] } })
    const t = teeth.find((x) => x.n === 41) as GumTooth
    const q = marginPoint(t, Math.PI / 2)
    // вдоль оси зуба край на 3,9 мм ниже здорового (0,9 над шейкой → 3 под ней)
    const h = marginPoint(healthy, Math.PI / 2)
    const along = (h[0] - q[0]) * t.yAxis[0] + (h[1] - q[1]) * t.yAxis[1] + (h[2] - q[2]) * t.yAxis[2]
    expect(along).toBeCloseTo(3.9, 6)
    expect(nearest(gum.positions, q)).toBeLessThan(0.3)
  })

  /** Тело десны по рёбрам: низ каждого ребра, глубже всего, и самая большая ступень
   *  ширины (щека — нёбо/язык) у низа между соседними рёбрами в пределах зубов a..b. */
  function body(list: number[], upper: boolean, o: Opts, a: number, b: number) {
    const { gum, teeth, lay } = jaw(list, upper, o)
    const P = gum.positions
    const ribs = (P.length / 3 - 2) / RIB.verts
    expect(Number.isInteger(ribs)).toBe(true)
    const at = (i: number, j: number): number[] => [0, 1, 2].map((k) => P[(i * RIB.verts + j) * 3 + k] ?? 0)
    /** высота над шейкой первого моляра: к коронке плюс, к низу минус */
    const v = (i: number, j: number): number => ((at(i, j)[1] ?? 0) - lay.yBase) * (upper ? -1 : 1)
    const xOf = (n: number): number => (teeth.find((x) => x.n === n) as GumTooth).position[0]
    const inside = (i: number, n1: number, n2: number): boolean => {
      const x = at(i, 0)[0] ?? 0
      return x >= Math.min(xOf(n1), xOf(n2)) && x <= Math.max(xOf(n1), xOf(n2))
    }
    const ends = upper ? [18, 28] : [48, 38]
    // за крайними зубами десна скругляется к торцу — там низ поднимается намеренно
    const lows: number[] = []
    for (let i = 0; i < ribs; i++) {
      if (!inside(i, ends[0] as number, ends[1] as number)) continue
      let lo = Infinity
      for (let j = 0; j < RIB.verts; j++) lo = Math.min(lo, v(i, j))
      lows.push(lo)
    }
    const deepest = Math.min(...lows)
    const level = deepest + 1.5
    const cross = (i: number, path: number[]): number[] | null => {
      for (let k = 0; k + 1 < path.length; k++) {
        const va = v(i, path[k] as number)
        const vb = v(i, path[k + 1] as number)
        if (va >= level && vb < level) {
          const f = (va - level) / (va - vb)
          const pa = at(i, path[k] as number)
          const pb = at(i, path[k + 1] as number)
          return pa.map((x, n) => x + ((pb[n] ?? x) - x) * f)
        }
      }
      return null
    }
    const buccal = Array.from({ length: RIB.mid + 1 }, (_, j) => j)
    const lingual = Array.from({ length: RIB.L - RIB.mid + 1 }, (_, j) => RIB.L - j)
    let prev: number | null = null
    let step = 0
    let seen = 0
    for (let i = 0; i < ribs; i++) {
      const bp = inside(i, a, b) ? cross(i, buccal) : null
      const lp = bp ? cross(i, lingual) : null
      if (!bp || !lp) { prev = null; continue }
      const width = Math.hypot((bp[0] ?? 0) - (lp[0] ?? 0), (bp[2] ?? 0) - (lp[2] ?? 0))
      if (prev !== null) step = Math.max(step, Math.abs(width - prev))
      prev = width
      seen++
    }
    return { gum, teeth, flat: Math.max(...lows) - deepest, deepest, step, seen, vOf: (y: number) => (y - lay.yBase) * (upper ? -1 : 1) }
  }

  it('глубокая рецессия врезается в десну, а не выдавливает её: низ ровный, тело гладкое (кадр Олега 07.10)', () => {
    // 15 DV — 10 мм: до 07.10 низ четырёх рёбер уходил на 3,3 мм за низ челюсти «плавником»,
    // и ширина десны у низа скакала у них на 3–4 мм
    const r = body(UP, true, { rec: { 15: [1, 2, 10, 0, 0, 0], 16: [0, 2, 0, 0, 0, 0] } }, 17, 13)
    expect(r.flat).toBeLessThan(0.01)
    expect(r.deepest).toBeGreaterThan(body(UP, true, {}, 17, 13).deepest - 0.5)
    expect(r.seen).toBeGreaterThan(40)
    expect(r.step).toBeLessThan(0.4)
    // а край на месте: расщелина доходит до точки DV на корне
    const t = r.teeth.find((x) => x.n === 15) as GumTooth
    expect(nearest(r.gum.positions, marginPoint(t, (50 * Math.PI) / 180))).toBeLessThan(0.3)
  })

  it('рецессия до предела (15 мм) — низ опускается у всей челюсти, а не под одним зубом', () => {
    const r = body(LO, false, { rec: { 41: [0, 8, 0, 0, 0, 0], 31: [0, 15, 0, 0, 0, 0] } }, 43, 33)
    expect(finite(r.gum)).toBe(true)
    expect(r.flat).toBeLessThan(0.01)
    expect(r.seen).toBeGreaterThan(40)
    expect(r.step).toBeLessThan(0.4)
    // под краем 31 (15 мм ниже шейки) десна ещё есть — низ глубже него
    const t = r.teeth.find((x) => x.n === 31) as GumTooth
    const edge = marginPoint(t, Math.PI / 2)
    expect(nearest(r.gum.positions, edge)).toBeLessThan(0.3)
    expect(r.deepest).toBeLessThan(r.vOf(edge[1]) - 2)
  })

  it('на месте отсутствующего зуба — гребень, а не дыра: десна есть прямо над его шейкой', () => {
    const { gum, teeth } = jaw(UP, true, { kinds: { 12: 'missing' } })
    const t = teeth.find((x) => x.n === 12) as GumTooth
    // верхняя челюсть: гребень на 0,4 мм к корню от шейки (y больше), допуск — округлость гребня
    expect(nearest(gum.positions, [t.position[0], t.position[1] + 0.4, t.position[2]])).toBeLessThan(0.8)
  })

  /* Беззубое место и швы тела (25.10, кадр Олега: «десна, когда нет зуба, странная по
     форме» — плоская полка и вертикальные полосы через тело). Случаи: одиночная дыра
     (42, 14), две подряд (34+35, 25+26), крайний (48), лунка «extras» (37, 28). */
  const GAPS_LO: Record<number, GumKind> = { 42: 'missing', 34: 'missing', 35: 'missing', 37: 'socket', 48: 'missing' }
  const GAPS_UP: Record<number, GumKind> = { 14: 'missing', 25: 'missing', 26: 'missing', 28: 'socket' }
  const sub = (a: number[], b: number[]): number[] => [(a[0] ?? 0) - (b[0] ?? 0), (a[1] ?? 0) - (b[1] ?? 0), (a[2] ?? 0) - (b[2] ?? 0)]
  const dot3 = (a: number[], b: number[]): number => (a[0] ?? 0) * (b[0] ?? 0) + (a[1] ?? 0) * (b[1] ?? 0) + (a[2] ?? 0) * (b[2] ?? 0)
  const len = (a: number[]): number => Math.hypot(a[0] ?? 0, a[1] ?? 0, a[2] ?? 0)

  /** Самый резкий излом тела вдоль дуги, градусы: в рядах тела ниже входа края
   *  (6…боковая точка) угол между отрезками к соседним рёбрам не ближе 0,25 мм
   *  (станции у краёв петель сгущены до 0,02 мм — их шаг дал бы шум). `keep` —
   *  какие рёбра смотреть (по точке ряда 6). Шов от края до низа — излом во всех рядах. */
  function seam(P: number[], keep: (q: number[]) => boolean = () => true): number {
    const M = RIB.verts
    const nR = (P.length / 3 - 2) / M
    const at = (i: number, j: number): number[] => [0, 1, 2].map((k) => P[(i * M + j) * 3 + k] ?? 0)
    let mx = 0
    for (let i = 1; i + 1 < nR; i++) {
      if (!keep(at(i, 6))) continue
      let im = i - 1
      while (im > 0 && len(sub(at(im, 6), at(i, 6))) < 0.25) im--
      let ip = i + 1
      while (ip < nR - 1 && len(sub(at(ip, 6), at(i, 6))) < 0.25) ip++
      for (let j = 6; j <= RIB.sideB; j++) {
        const u = sub(at(i, j), at(im, j))
        const v = sub(at(ip, j), at(i, j))
        mx = Math.max(mx, (Math.acos(Math.max(-1, Math.min(1, dot3(u, v) / (len(u) * len(v))))) * 180) / Math.PI)
      }
    }
    return mx
  }

  it('⭐ тело без швов вдоль дуги: у дыры, у двух подряд, у крайнего и у лунки, за крайним зубом, у стыка моляра с премоляром (25.10)', () => {
    // до 25.10 огибающая тела в дыре и за крайним зубом СКАЧКОМ брала значение своего
    // ребра: 80–86° излома в дырах, 54–56° у целой челюсти за 18/28 и 48/38
    for (const [list, upper, kinds] of [[LO, false, GAPS_LO], [UP, true, GAPS_UP], [LO, false, {}], [UP, true, {}]] as const) {
      expect(seam(jaw(list, upper, { kinds }).gum.positions)).toBeLessThan(15)
    }
    // шов 16|15 и 46|45 (отчёт odo-look 19.10): переход тела от широкого моляра к узкому
    // премоляру ложился в ~4 мм у стыка — 11,5–12,2° через всю высоту десны
    for (const [list, upper, a, b] of [[UP, true, 16, 15], [LO, false, 46, 45]] as const) {
      const { gum, teeth } = jaw(list, upper)
      const pa = (teeth.find((t) => t.n === a) as GumTooth).position
      const pb = (teeth.find((t) => t.n === b) as GumTooth).position
      const ab = sub(pb, pa)
      const ax = ab[0] ?? 0
      const az = ab[2] ?? 0
      const zone = (q: number[]): boolean => {
        const qx = (q[0] ?? 0) - pa[0]
        const qz = (q[2] ?? 0) - pa[2]
        const f = (qx * ax + qz * az) / (ax * ax + az * az)
        // только эта сторона дуги: точка у отрезка a–b, а не напротив через рот
        return f >= 0 && f <= 1 && Math.hypot(qx - ax * f, qz - az * f) < 9
      }
      expect(seam(gum.positions, zone)).toBeLessThan(8)
    }
  })

  it('⭐ беззубый гребень — валик, а не полка: поперёк дыры вершина выше плеч на четверть полуширины, без угла коробкой (25.10)', () => {
    for (const [list, upper, kinds] of [[LO, false, GAPS_LO], [UP, true, GAPS_UP]] as const) {
      const { gum, teeth } = jaw(list, upper, { kinds })
      const P = gum.positions
      const M = RIB.verts
      const nR = (P.length / 3 - 2) / M
      const at = (i: number, j: number): number[] => [0, 1, 2].map((k) => P[(i * M + j) * 3 + k] ?? 0)
      for (const t of teeth.filter((x) => x.kind === 'missing')) {
        // ребро у середины дыры: его вершина гребня (C — предпоследняя точка ребра) ближе всех
        let bi = 0
        let bd = Infinity
        for (let i = 0; i < nR; i++) {
          const c = at(i, M - 2)
          const d = Math.hypot((c[0] ?? 0) - t.position[0], (c[2] ?? 0) - t.position[2])
          if (d < bd) { bd = d; bi = i }
        }
        const B = at(bi, 0)
        const Lp = at(bi, RIB.L)
        const C = at(bi, M - 2)
        const across = [(B[0] ?? 0) - (Lp[0] ?? 0), 0, (B[2] ?? 0) - (Lp[2] ?? 0)]
        const half = len(across) / 2
        const vOf = (q: number[]): number => (q[1] ?? 0) * (upper ? -1 : 1)
        // до 25.10 — 0,16–0,19: плита с перепадом ≤ 0,54 мм
        expect((vOf(C) - (vOf(B) + vOf(Lp)) / 2) / half).toBeGreaterThan(0.25)
        // от вершины вниз по щёчной стороне до боковой точки — ни одного угла круче 30°
        const wv = (j: number): number[] => { const q = at(bi, j); return [dot3(sub(q, C), across) / (2 * half), vOf(q)] }
        const path = [M - 2, M - 1, 0, ...Array.from({ length: RIB.sideB }, (_, k) => k + 1)].map(wv)
        for (let k = 1; k + 1 < path.length; k++) {
          const a = path[k - 1] as number[]
          const b = path[k] as number[]
          const c = path[k + 1] as number[]
          const u1 = [(b[0] ?? 0) - (a[0] ?? 0), (b[1] ?? 0) - (a[1] ?? 0)]
          const u2 = [(c[0] ?? 0) - (b[0] ?? 0), (c[1] ?? 0) - (b[1] ?? 0)]
          const turn = Math.abs(Math.atan2((u1[0] ?? 0) * (u2[1] ?? 0) - (u1[1] ?? 0) * (u2[0] ?? 0), (u1[0] ?? 0) * (u2[0] ?? 0) + (u1[1] ?? 0) * (u2[1] ?? 0)))
          expect((turn * 180) / Math.PI).toBeLessThan(30)
        }
      }
    }
  })

  it('⭐ лунка «extras» лежит на десне: её круг в плоскости шейки поставленного зуба не под десной и не висит (25.10)', () => {
    /* круг лунки — `scene.ts`: 0,85 ширины и толщины зуба, на 0,05 мм над шейкой, в
       базисе ПОСТАВЛЕННОГО зуба (наклон `pose.ts`). До 25.10 плоская горизонтальная
       плита прятала под десну половину круга — до 0,9 мм у нижнего моляра (torque −12°) */
    const ray = (P: number[], idx: number[], o: number[], d: number[]): number => {
      let best = Infinity
      for (let t = 0; t < idx.length; t += 3) {
        const v = [0, 1, 2].map((k) => [0, 1, 2].map((c) => P[(idx[t + k] ?? 0) * 3 + c] ?? 0))
        const e1 = sub(v[1] as number[], v[0] as number[])
        const e2 = sub(v[2] as number[], v[0] as number[])
        const p = [d[1]! * e2[2]! - d[2]! * e2[1]!, d[2]! * e2[0]! - d[0]! * e2[2]!, d[0]! * e2[1]! - d[1]! * e2[0]!]
        const det = dot3(e1, p)
        if (Math.abs(det) < 1e-12) continue
        const s = sub(o, v[0] as number[])
        const a = dot3(s, p) / det
        if (a < 0 || a > 1) continue
        const q = [s[1]! * e1[2]! - s[2]! * e1[1]!, s[2]! * e1[0]! - s[0]! * e1[2]!, s[0]! * e1[1]! - s[1]! * e1[0]!]
        const b = dot3(d, q) / det
        if (b < 0 || a + b > 1) continue
        const tt = dot3(e2, q) / det
        if (tt > 1e-6 && tt < best) best = tt
      }
      return best
    }
    for (const [list, upper, kinds, n] of [[LO, false, GAPS_LO, 37], [UP, true, GAPS_UP, 28]] as const) {
      const { gum, teeth } = jaw(list, upper, { kinds })
      const t = teeth.find((x) => x.n === n) as GumTooth
      const Y = t.yAxis
      // лучи — только по треугольникам у этого зуба: вся сетка (~40 тыс.) в полном
      // прогоне под нагрузкой не укладывалась в предел проверки
      const P = gum.positions
      const near: number[] = []
      for (let i = 0; i < gum.index.length; i += 3) {
        const c = [0, 2].map((k) => [0, 1, 2].reduce((s, m) => s + (P[(gum.index[i + m] ?? 0) * 3 + k] ?? 0), 0) / 3)
        if (Math.hypot((c[0] ?? 0) - t.position[0], (c[1] ?? 0) - t.position[2]) < t.md) near.push(gum.index[i] ?? 0, gum.index[i + 1] ?? 0, gum.index[i + 2] ?? 0)
      }
      for (let k = 0; k <= 16; k++) {
        const a = (k / 16) * Math.PI * 2
        const r = k === 16 ? 0 : 1
        const lx = r * 0.425 * t.md * Math.cos(a)
        const lz = r * 0.425 * t.bl * Math.sin(a)
        // точка круга (0,05 над шейкой) и ещё на 0,05 выше — касание до 0,05 мм не прячет
        const o = [0, 1, 2].map((i) => (t.position[i] ?? 0) + (t.xAxis[i] ?? 0) * lx + (Y[i] ?? 0) * 0.1 + (t.zAxis[i] ?? 0) * lz)
        // над ней десны нет
        expect(ray(P, near, o, [Y[0], Y[1], Y[2]]), `${n} k=${k}`).toBeGreaterThan(4)
        // под ней десна ближе 0,3 мм от круга
        expect(ray(P, near, o, [-Y[0], -Y[1], -Y[2]]), `${n} k=${k}`).toBeLessThan(0.35)
      }
    }
  })

  it('полоса кармана — только у зуба, которому её прислали', () => {
    // красная полоса: яркий красный почти без зелёного — у слизистой и низа красного меньше
    const greenless = (c: number[]): number => {
      let n = 0
      for (let i = 0; i < c.length; i += 3) if ((c[i] ?? 0) > 0.5 && (c[i + 1] ?? 1) < 0.07) n++
      return n
    }
    expect(greenless(jaw(UP, true).gum.colors ?? [])).toBe(0)
    expect(greenless(jaw(UP, true, { red: [26] }).gum.colors ?? [])).toBeGreaterThan(20)
  })
})
