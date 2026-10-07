import { describe, expect, it } from 'vitest'
import { SCULPT, SCULPT_OF } from '../../../../models/teeth.js'
import { sculptModel, type SculptTable } from './sculpt'

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
