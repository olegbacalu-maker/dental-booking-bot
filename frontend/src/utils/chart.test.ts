import { describe, expect, it } from 'vitest'
import { DONUT_R, donutArcs, gaugeArc, linePlot, sparkPoints } from './chart'

describe('спарклайн', () => {
  it('нормируется по СВОЕМУ максимуму, а не по общей шкале', () => {
    /* Иначе плитка «Anulate» (2) рядом с «Programări» (24) — прямая по полу. */
    const a = sparkPoints([0, 24])
    const b = sparkPoints([0, 2])
    expect(a).toBe(b)
  })

  it('ряд из нулей — РОВНАЯ ЛИНИЯ ПО ПОЛУ, а пустой ряд — вообще ничего', () => {
    expect(sparkPoints([0, 0, 0])).toBe('0.0,23.0 50.0,23.0 100.0,23.0')
    expect(sparkPoints([])).toBe('')
  })
})

describe('дневной график', () => {
  it('потолок оси округляется вверх до шага × 4 — подписи человеко-читаемы', () => {
    const p = linePlot(['01.09', '02.09', '03.09'], [1, 2, 3])
    expect(p.grid.map((g) => g.label)).toEqual([0, 1, 2, 3, 4])
  })

  it('ноль оси — общий у сетки и у заливки под линией', () => {
    const p = linePlot(['01.09'], [5])
    const zero = p.grid.find((g) => g.label === 0)
    expect(zero?.y).toBe(p.yZero)
  })

  it('густой период прореживает подписи, но ПОСЛЕДНЯЯ дата остаётся', () => {
    const labels = Array.from({ length: 30 }, (_, i) => `d${i}`)
    const p = linePlot(labels, labels.map(() => 1))
    expect(p.xLabels.map((x) => x.text)).toContain('d29')
    expect(p.xLabels.length).toBeLessThan(labels.length)
    /* 30 дат в ряд нечитаемы в любом случае — прореживание не косметика. */
    expect(p.xLabels.length).toBeLessThanOrEqual(12)
  })

  it('пустой период рисовать нечем — точек нет', () => {
    const p = linePlot([], [])
    expect(p.points).toBe('')
    expect(p.dots).toEqual([])
  })
})

describe('кольцо долей', () => {
  it('доли считаются от суммы ПОКАЗАННЫХ частей и сходятся в полный круг', () => {
    const { total, arcs } = donutArcs([
      { label: 'Telegram', value: 1, color: 'var(--teal)' },
      { label: 'Recepție', value: 3, color: 'var(--blue)' },
    ])
    expect(total).toBe(4)
    const circ = 2 * Math.PI * DONUT_R
    const lens = arcs.map((a) => Number(a.dash.split(' ')[0]))
    expect(lens.reduce((s, x) => s + x, 0)).toBeCloseTo(circ, 1)
    /* каждая следующая дуга начинается там, где кончилась предыдущая */
    expect(arcs[1]?.offset).toBeCloseTo(-lens[0]!, 2)
  })

  it('пустая часть дугу не рисует, а пустой итог — не рисует ничего', () => {
    const { arcs } = donutArcs([
      { label: 'Telegram', value: 0, color: 'var(--teal)' },
      { label: 'Recepție', value: 2, color: 'var(--blue)' },
    ])
    expect(arcs).toHaveLength(1)
    expect(donutArcs([{ label: 'x', value: 0, color: 'c' }]).arcs).toEqual([])
  })
})

describe('полукруг загрузки', () => {
  it('доля вне 0–100 прижимается к границе', () => {
    expect(gaugeArc(-5).pct).toBe(0)
    expect(gaugeArc(146).pct).toBe(100)
  })

  it('зазор пунктира — ДВЕ длины дуги: иначе узор повторится на первом кадре', () => {
    const { dash } = gaugeArc(50)
    const [on, gap] = dash.split(' ').map(Number)
    const ln = Math.PI * 62
    expect(on).toBeCloseTo(ln / 2, 1)
    expect(gap).toBeCloseTo(ln * 2, 1)
  })
})
