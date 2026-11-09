import { describe, expect, it } from 'vitest'
import { roCount, roForm } from './plural'

const ZILE = { one: '{n} zi', few: '{n} zile', many: '{n} de zile' }

describe('roForm', () => {
  it('1 — zi, 2–19 — zile, 20+ — de zile; окончания 01–19 — без «de»', () => {
    expect(roCount(1, ZILE)).toBe('1 zi')
    expect(roCount(2, ZILE)).toBe('2 zile')
    expect(roCount(19, ZILE)).toBe('19 zile')
    expect(roCount(20, ZILE)).toBe('20 de zile')
    expect(roCount(0, ZILE)).toBe('0 zile')
    expect(roForm(100)).toBe('many')
    expect(roForm(101)).toBe('few')
    expect(roForm(119)).toBe('few')
    expect(roForm(120)).toBe('many')
  })
})
