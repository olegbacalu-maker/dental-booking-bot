import { describe, expect, it } from 'vitest'
import { sparkPoints } from './chart'

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
