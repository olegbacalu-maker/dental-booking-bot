import { describe, expect, it } from 'vitest'
import { SCULPT, SCULPT_OF } from '../../../../models/teeth.js'
import { layoutArch } from './arch'
import { anchorsFor, buildGum, marginPoint, stripesFor, type GumTooth } from './gum'
import { finite } from './mesh'
import { posed } from './pose'
import { ROOT_NECK, rootCount, sculptModel, surfDepth, SURF_W_MIN, type RootSet, type SculptTable } from './sculpt'
import { toCls } from './toothGeometry'

/* Свои модели зубов (07.10): таблицы, которые пишет scripts/teeth/bake.py, и
   постройка коронки по ним. Таблицы бандл не везёт (`loadTeeth`) — значит,
   ни один экран их не проверит, пока врач не откроет 3D; проверяем здесь. */

const permanent = [1, 2, 3, 4].flatMap((q) => [1, 2, 3, 4, 5, 6, 7, 8].map((k) => q * 10 + k))

describe('таблицы своих моделей', () => {
  it('каждый постоянный зуб — своя модель своей челюсти, все 16 типов на месте', () => {
    for (const n of permanent) {
      const t = SCULPT_OF[n]
      expect(t, `зуб ${n}`).toBe(`${n < 30 ? 'U' : 'L'}${n % 10}`)
      expect(SCULPT[t as string], `тип ${t}`).toBeDefined()
    }
    expect(Object.keys(SCULPT).sort()).toHaveLength(16)
  })

  it('таблица цела: строки стенки по высотам, кольца по долям, числа конечны', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      const K = tab.heights.length
      expect(tab.heights[0], name).toBe(0)
      for (let k = 1; k < K; k++) expect(tab.heights[k], name).toBeGreaterThan(tab.heights[k - 1] ?? 0)
      expect(tab.heights[K - 1], name).toBeCloseTo(tab.hCap, 3)
      expect(tab.r, name).toHaveLength(K)
      expect(tab.cx, name).toHaveLength(K)
      expect(tab.cz, name).toHaveLength(K)
      for (const row of tab.r) {
        expect(row).toHaveLength(tab.theta)
        for (const v of row) expect(v > 0 && v < 9, `${name}: радиус ${v}`).toBe(true)
      }
      const S = tab.capS ?? []
      expect(tab.cap, name).toHaveLength(S.length)
      S.forEach((s, i) => {
        expect(s > 0 && s < 1, `${name}: доля ${s}`).toBe(true)
        if (i) expect(s, name).toBeLessThan(S[i - 1] ?? 1)
      })
      for (const ring of tab.cap) {
        expect(ring).toHaveLength(tab.theta)
        for (const v of ring) expect(Number.isFinite(v) && v >= tab.hCap - 0.01, `${name}: высота ${v}`).toBe(true)
      }
    }
  })
})

describe('коронка по таблице', () => {
  const geomOf = (tab: SculptTable, cls: string, upper: boolean) =>
    ({ md: tab.ref.md, bl: tab.ref.bl, crown: tab.ref.crown, root: 12, roots: 1, cls, upper })
  const CLS: Record<string, string> = { 1: 'incisor_c', 2: 'incisor_l', 3: 'canine', 4: 'premolar', 5: 'premolar', 6: 'molar', 7: 'molar', 8: 'molar' }

  it('вершина — на высоте коронки эталона, шейка — у нуля, ширина — md с касанием контактов', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      const cm = sculptModel(tab, geomOf(tab, CLS[name.slice(1)] ?? 'molar', name.startsWith('U')))
      // вершина — по бугру; у моляра анатомическая (7–7,5 мм), а не как у формулы
      expect(Math.abs(cm.tip - tab.ref.crown), `${name}: вершина ${cm.tip}`).toBeLessThan(0.3)
      const xs = cm.mesh.positions.filter((_v, i) => i % 3 === 0)
      const width = Math.max(...xs) - Math.min(...xs)
      // CONTACT = 1,03: соседние коронки касаются, а не стоят с щелью 0,3 мм
      expect(width / tab.ref.md, name).toBeGreaterThan(1.0)
      expect(width / tab.ref.md, name).toBeLessThan(1.06)
      const neck = cm.outline(24)
      expect(neck).toHaveLength(24)
      for (const [x, z] of neck) expect(Math.hypot(x, z), name).toBeLessThan(Math.max(tab.ref.md, tab.ref.bl))
    }
  })

  it('масштаб — по размерам сервера: та же модель шире и выше у большего зуба', () => {
    const tab = SCULPT.U6 as SculptTable
    const a = sculptModel(tab, geomOf(tab, 'molar', true))
    const b = sculptModel(tab, { ...geomOf(tab, 'molar', true), md: tab.ref.md * 1.1, crown: tab.ref.crown * 1.2 })
    expect(b.tip / a.tip).toBeCloseTo(1.2, 2)
    const span = (m: typeof a) => {
      const xs = m.mesh.positions.filter((_v, i) => i % 3 === 0)
      return Math.max(...xs) - Math.min(...xs)
    }
    expect(span(b) / span(a)).toBeCloseTo(1.1, 2)
  })
})

describe('корни по таблице (25.10)', () => {
  // число корней — правило сервера (`teeth_svg.root_count`): верхние моляры 3,
  // нижние 2, верхний первый премоляр 2, прочие 1
  const SERVER_ROOTS: Record<string, number> = { U4: 2, U6: 3, U7: 3, U8: 3, L6: 2, L7: 2, L8: 2 }
  const CLS: Record<string, string> = { 1: 'incisor_c', 2: 'incisor_l', 3: 'canine', 4: 'premolar', 5: 'premolar', 6: 'molar', 7: 'molar', 8: 'molar' }
  const geom = (name: string, tab: SculptTable, root = 12) =>
    ({ md: tab.ref.md, bl: tab.ref.bl, crown: tab.ref.crown, root, roots: SERVER_ROOTS[name] ?? 1, cls: CLS[name.slice(1)] ?? 'molar', upper: name.startsWith('U') })
  const P = (m: { positions: number[] }, i: number): [number, number, number] =>
    [m.positions[3 * i] ?? 0, m.positions[3 * i + 1] ?? 0, m.positions[3 * i + 2] ?? 0]

  it('⛔ у каждого типа корней столько, сколько у сервера, — иначе программа строила бы формулу', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      expect(tab.roots, name).toBeDefined()
      expect(rootCount(tab.roots as RootSet), name).toBe(SERVER_ROOTS[name] ?? 1)
      expect(sculptModel(tab, geom(name, tab)).roots, name).toBeDefined()
    }
  })

  it('⛔ ствол начинается ровно шейкой коронки: шва между коронкой и корнем нет', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      const cm = sculptModel(tab, geom(name, tab))
      const rs = tab.roots as RootSet
      for (let j = 0; j < rs.theta; j++) {
        const [x, y, z] = P(cm.roots as { positions: number[] }, j)
        const [nx, nz] = cm.neck((2 * Math.PI * j) / rs.theta)
        expect(Math.hypot(x - nx, z - nz), `${name} угол ${j}`).toBeLessThan(0.02)
        expect(y).toBeCloseTo(0, 9)
      }
    }
  })

  it('⛔ стенка ниже шейки (по ней садится десна при рецессии) лежит на сетке ствола', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      const cm = sculptModel(tab, geom(name, tab))
      const rs = tab.roots as RootSet
      const sd = (ROOT_NECK + 12) / rs.len
      const lim = surfDepth(rs)
      rs.trunk.d.forEach((d, k) => {
        if (k === 0 || d > lim) return
        for (let j = 0; j < rs.theta; j += 6) {
          const [x, y, z] = P(cm.roots as { positions: number[] }, k * rs.theta + j)
          const [sx, sz] = cm.surf((2 * Math.PI * j) / rs.theta, -d * sd)
          expect(Math.hypot(x - sx, z - sz), `${name} глубина ${d} угол ${j}`).toBeLessThan(1e-6)
          expect(y).toBeCloseTo(-d * sd, 9)
        }
      })
    }
  })

  it('длина — по серверу: самый глубокий апекс на шеечный переход + root ниже шейки', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      for (const root of [10, 14]) {
        const m = sculptModel(tab, geom(name, tab, root)).roots as { positions: number[] }
        const ys = m.positions.filter((_v, i) => i % 3 === 1)
        expect(Math.min(...ys), `${name} root ${root}`).toBeCloseTo(-(ROOT_NECK + root), 1)
      }
    }
  })

  it('верхние моляры: нёбный корень длиннее щёчных, корни расходятся; ствол короче корня', () => {
    for (const name of ['U6', 'U7']) {
      const rs = (SCULPT[name] as SculptTable).roots as RootSet
      const apex = rs.list.map((q) => q.d[q.d.length - 1] ?? 0)
      const [mb = 0, db = 0, pal = 0] = apex
      expect(pal, name).toBeGreaterThan(mb)
      expect(pal, name).toBeGreaterThan(db)
      expect(rs.fur, name).toBeLessThan(0.45 * rs.len)
      const tips = rs.list.map((q) => [q.cx[q.cx.length - 1] ?? 0, q.cz[q.cz.length - 1] ?? 0])
      const tops = rs.list.map((q) => [q.cx[0] ?? 0, q.cz[0] ?? 0])
      const spread = (pts: number[][]) => Math.max(...pts.flatMap((a) => pts.map((b) => Math.hypot((a[0] ?? 0) - (b[0] ?? 0), (a[1] ?? 0) - (b[1] ?? 0)))))
      expect(spread(tips), name).toBeGreaterThan(spread(tops))
    }
  })

  it('нижние моляры: мезиальный и дистальный корень по сторонам, мезиальный длиннее; у 14/24 — щёчный и нёбный', () => {
    for (const name of ['L6', 'L7']) {
      const rs = (SCULPT[name] as SculptTable).roots as RootSet
      const [m, d] = rs.list
      expect(m?.cx[0] ?? 0, name).toBeLessThan(0)
      expect(d?.cx[0] ?? 0, name).toBeGreaterThan(0)
      expect(m?.d[m.d.length - 1] ?? 0, name).toBeGreaterThan(d?.d[d.d.length - 1] ?? 0)
    }
    const u4 = (SCULPT.U4 as SculptTable).roots as RootSet
    expect(u4.list[0]?.cz[0] ?? 0).toBeGreaterThan(0)
    expect(u4.list[1]?.cz[0] ?? 0).toBeLessThan(0)
  })

  it('обход как у формулы: нормали корня смотрят наружу', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      const m = sculptModel(tab, geom(name, tab)).roots as { positions: number[]; index: number[] }
      const rs = tab.roots as RootSet
      // треугольник второго кольца ствола под губной/щёчной стороной (угол ~90°)
      const j = Math.round(rs.theta / 4)
      const tri = m.index.findIndex((v, i) => i % 3 === 0 && v === rs.theta + j)
      const [a, b, c] = [m.index[tri] ?? 0, m.index[tri + 1] ?? 0, m.index[tri + 2] ?? 0].map((i) => P(m, i))
      const u = [(b?.[0] ?? 0) - (a?.[0] ?? 0), (b?.[1] ?? 0) - (a?.[1] ?? 0), (b?.[2] ?? 0) - (a?.[2] ?? 0)]
      const v = [(c?.[0] ?? 0) - (a?.[0] ?? 0), (c?.[1] ?? 0) - (a?.[1] ?? 0), (c?.[2] ?? 0) - (a?.[2] ?? 0)]
      const nz = (u[0] ?? 0) * (v[1] ?? 0) - (u[1] ?? 0) * (v[0] ?? 0)
      expect(nz, name).toBeGreaterThan(0)
    }
  })

  it('без таблицы корней или при чужом числе корней — корни-формула, стенка ниже шейки — её правило', () => {
    const tab = SCULPT.U6 as SculptTable
    const bare = Object.fromEntries(Object.entries(tab).filter(([k]) => k !== 'roots')) as unknown as SculptTable
    expect(sculptModel(bare, geom('U6', tab)).roots).toBeUndefined()
    const other = sculptModel(tab, { ...geom('U6', tab), roots: 2 })
    expect(other.roots).toBeUndefined()
    const [nx, nz] = other.neck(1)
    const [x, z] = other.surf(1, -2.4)
    expect(x / nx).toBeCloseTo(0.86, 6)
    expect(z / nz).toBeCloseTo(0.86, 6)
  })

  it('стенка ниже шейки не уже 0,7 шейки (как у формулы): глубже край десны держится этой глубины', () => {
    for (const [name, tab] of Object.entries(SCULPT)) {
      const rs = tab.roots as RootSet
      const lim = surfDepth(rs)
      expect(lim, name).toBeGreaterThan(2)
      const cm = sculptModel(tab, geom(name, tab))
      const sd = (ROOT_NECK + 12) / rs.len
      for (let j = 0; j < 24; j++) {
        const th = (2 * Math.PI * j) / 24
        const [nx, nz] = cm.neck(th)
        const [x, z] = cm.surf(th, -40)
        // самое глубокое, куда садится край, — сечение на глубине lim
        const [lx, lz] = cm.surf(th, -lim * sd)
        expect(Math.hypot(x - lx, z - lz), `${name} ${j}`).toBeLessThan(1e-9)
        expect(Math.hypot(x, z) / Math.hypot(nx, nz), `${name} ${j}`).toBeGreaterThan(SURF_W_MIN - 0.25)
      }
    }
  })

  it('⛔ десна на своих моделях: при рецессии до предела (31 — 15 мм, 41 — 8 мм) край лежит на десне', () => {
    // та же проверка, что `gum.test` › «рецессия до предела», но на СВОИХ коронках с
    // корнями по таблице: `gum.test` строит десну на формулах и этот путь не проходит
    const LO = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
    const rec: Record<number, number[]> = { 41: [0, 8, 0, 0, 0, 0], 31: [0, 15, 0, 0, 0, 0] }
    const g = (n: number) => {
      const name = SCULPT_OF[n] as string
      const tab = SCULPT[name] as SculptTable
      return { tab, geo: { ...geom(name, tab), md: tab.ref.md, bl: tab.ref.bl, crown: tab.ref.crown, upper: false } }
    }
    const lay = layoutArch(LO.map((n) => ({ n, md: g(n).geo.md })), false)
    const models = new Map(LO.map((n) => [n, sculptModel(g(n).tab, g(n).geo)]))
    const ref = models.get(36)?.tip ?? 9
    const teeth: GumTooth[] = lay.teeth.map((p0) => {
      const { geo } = g(p0.n)
      const c = models.get(p0.n) as ReturnType<typeof sculptModel>
      const p = posed(p0, toCls(geo.cls), false, c.tip, ref)
      return {
        n: p0.n, kind: 'tooth', s: p.s, md: geo.md, bl: geo.bl, root: geo.root,
        position: p.position, xAxis: p.xAxis, yAxis: p.yAxis, zAxis: p.zAxis, surf: c.surf,
        anchors: anchorsFor(toCls(geo.cls), rec[p0.n] ?? null, false, false), stripe: stripesFor(null),
      }
    })
    const gum = buildGum({ A: lay.A, D: lay.D, apex: lay.apex, yBase: lay.yBase, occ: 1, teeth })
    expect(finite(gum)).toBe(true)
    for (const n of [31, 41]) {
      const t = teeth.find((x) => x.n === n) as GumTooth
      const e = marginPoint(t, Math.PI / 2)
      let best = Infinity
      for (let i = 0; i < gum.positions.length; i += 3) {
        best = Math.min(best, Math.hypot((gum.positions[i] ?? 0) - (e[0] ?? 0), (gum.positions[i + 1] ?? 0) - (e[1] ?? 0), (gum.positions[i + 2] ?? 0) - (e[2] ?? 0)))
      }
      expect(best, `край ${n}`).toBeLessThan(0.3)
    }
  })
})
