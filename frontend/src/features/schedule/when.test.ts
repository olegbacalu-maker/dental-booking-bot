import { describe, expect, it } from 'vitest'
import { dayShort, whenLine } from './when'

describe('строка «когда» в шапке окна записи', () => {
  it('день недели по-румынски, дата, начало–конец', () => {
    expect(whenLine('2026-11-14', '08:00', 0, 60)).toBe('sâmbătă, 14.11 · 08:00–09:00')
    expect(whenLine('2026-11-16', '08', 25, 30)).toBe('luni, 16.11 · 08:25–08:55')
    expect(whenLine('2026-11-15', '14:00', 50, 25)).toBe('duminică, 15.11 · 14:50–15:15')
  })

  it('день недели — по календарю даты, не по поясу браузера: все семь дней', () => {
    const names = ['luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă', 'duminică']
    names.forEach((n, i) => expect(dayShort(`2026-11-${String(16 + i)}`)).toBe(`${n}, ${16 + i}.11`))
  })

  it('часа нет — «alegeți ora»; длительности нет (поле не по правилу) — только начало', () => {
    expect(whenLine('2026-11-14', '', 0, 60)).toBe('alegeți ora')
    expect(whenLine('2026-11-14', '09:00', 5, 0)).toBe('sâmbătă, 14.11 · 09:05')
  })

  it('дата не набрана или несуществующая — время без дня', () => {
    expect(whenLine('', '09:00', 0, 30)).toBe('09:00–09:30')
    expect(whenLine('2026-02-30', '09:00', 0, 30)).toBe('09:00–09:30')
  })

  it('конец за полночь называется честно, а не обрезается до «00:30» без пометки', () => {
    expect(whenLine('2026-11-14', '23:00', 0, 90)).toBe('sâmbătă, 14.11 · 23:00–00:30 (+1 zi)')
    expect(whenLine('2026-11-14', '23:00', 0, 60)).toBe('sâmbătă, 14.11 · 23:00–00:00 (+1 zi)')
  })
})
