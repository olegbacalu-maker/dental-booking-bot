import { describe, expect, it } from 'vitest'
import { squash } from './ActivityCard'
import type { ActivityItem } from './card'

/* Склейка подряд одинаковых событий летописи (09.10, разбор: два сохранения
   фиши подряд — две одинаковые строки). Склеивается только ПОКАЗ, и только
   подряд: то же событие через другое — отдельной строкой. */
const ev = (id: number, text: string, who = 'recepție', kind = 'profile'): ActivityItem =>
  ({ id, kind, icon: 'pen', text, when: '08.10.2026', hhmm: '18:24', who })

describe('squash: подряд одинаковые события летописи — одной строкой с ×N', () => {
  it('две одинаковые подряд — одна с n=2, остальные по одной', () => {
    const rows = squash([ev(3, 'Fișa pacientului a fost actualizată'), ev(2, 'Fișa pacientului a fost actualizată'),
      ev(1, 'Plată 2000 MDL (card)', 'recepție', 'pay')])
    expect(rows.map((r) => [r.id, r.n])).toEqual([[3, 2], [1, 1]])
  })

  it('то же событие через другое — не склеивается; другой автор — тоже', () => {
    const rows = squash([ev(4, 'A'), ev(3, 'B'), ev(2, 'A'), ev(1, 'A', 'Dr. Ana')])
    expect(rows.map((r) => [r.id, r.n])).toEqual([[4, 1], [3, 1], [2, 1], [1, 1]])
  })

  it('пустой список — пустой', () => {
    expect(squash([])).toEqual([])
  })
})
