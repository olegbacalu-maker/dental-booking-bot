import { describe, expect, it } from 'vitest'
import type { DashAgendaItem } from './dash'
import { WAIT_LONG_MIN, WAIT_SHOW_MIN } from './dashFx'
import { dur, flowOf, JUST_CAME_MIN, LATE_AFTER_MIN, LONG_MIN } from './flow'

/* Поток пациента (03.10): чистые правила — границы порогов, кого задержит
   затянувшийся приём, кто какой врач. Экран — в DashRail.test. */

const T = (h: number, m: number) => new Date(2026, 9, 6, h, m).getTime()
const NOW = T(11, 30)

function it_(over: Partial<DashAgendaItem>): DashAgendaItem {
  return {
    id: 1, time: '11:00', dur: 30, name: 'X', service: 'Consultație', status: 'confirmed',
    badge: { cls: 'pln', label: 'Programată' }, urgent: false, bar: 'var(--green)', state: 'current',
    clickable: true, patient_id: 1, wait_since: null, comment: '',
    doctor: 'Dr. Ana', doctor_id: 'd1', phone: '', start_ms: T(11, 0), end_ms: T(11, 30),
    end: '11:30', in_at: '', ...over,
  }
}

describe('flow.ts: пороги', () => {
  it('⛔ пороги ожидания — ТЕ ЖЕ, что у «așteaptă N min» повестки и сетки', () => {
    expect(LONG_MIN).toBe(WAIT_LONG_MIN)
    expect(JUST_CAME_MIN).toBe(WAIT_SHOW_MIN)
  })

  it('опоздание: с 5-й минуты включительно, красное с 15-й включительно', () => {
    const f = flowOf([
      it_({ id: 1, start_ms: NOW - (LATE_AFTER_MIN - 1) * 60_000 }),
      it_({ id: 2, start_ms: NOW - LATE_AFTER_MIN * 60_000 }),
      it_({ id: 3, start_ms: NOW - (LONG_MIN - 1) * 60_000 }),
      it_({ id: 4, start_ms: NOW - LONG_MIN * 60_000 }),
    ], NOW)
    expect(f.late.map((r) => [r.it.id, r.min, r.long])).toEqual([[4, 15, true], [3, 14, false], [2, 5, false]])
  })

  it('в «Întârzie» — только ещё не пришедшие: пришёл, в кабинете, закрыт — не опаздывает', () => {
    const f = flowOf(['waiting', 'arrived', 'done', 'noshow', 'cancelled'].map((status, i) =>
      it_({ id: i + 1, status, start_ms: T(10, 0), end_ms: T(10, 30), wait_since: T(10, 0) })), NOW)
    expect(f.late).toEqual([])
    expect(f.waiting.map((r) => r.it.id)).toEqual([1])
    expect(f.incab.map((r) => r.it.id)).toEqual([2])
  })

  it('ожидание: без отметки прихода — ноль минут, а не «с начала эпохи»', () => {
    const f = flowOf([it_({ status: 'waiting', wait_since: null })], NOW)
    expect(f.waiting[0]?.min).toBe(0)
  })
})

describe('flow.ts: врач и кого задержит', () => {
  it('врач узнаётся по ключу, а без ключа (легаси) — по имени', () => {
    const f = flowOf([
      it_({ id: 1, status: 'arrived', doctor_id: '', doctor: 'Dr. Vechi', start_ms: T(11, 0), end_ms: T(12, 0), end: '12:00' }),
      it_({ id: 2, status: 'waiting', doctor_id: '', doctor: 'Dr. Vechi', wait_since: T(11, 20) }),
      it_({ id: 3, status: 'waiting', doctor_id: '', doctor: 'Dr. Altul', wait_since: T(11, 20) }),
    ], NOW)
    expect(f.waiting.map((r) => [r.it.id, r.busy])).toEqual([
      [2, { until: '12:00', over: 0 }], [3, null],
    ])
  })

  it('следующий — ближайшая ещё не начатая запись ТОГО ЖЕ врача не раньше текущей', () => {
    const f = flowOf([
      it_({ id: 1, status: 'arrived', start_ms: T(10, 0), end_ms: T(11, 0), end: '11:00' }),
      it_({ id: 2, status: 'done', start_ms: T(9, 0), end_ms: T(10, 0) }),          // раньше — не он
      it_({ id: 3, status: 'noshow', start_ms: T(11, 0), end_ms: T(11, 30) }),       // закрыт — не он
      it_({ id: 4, status: 'confirmed', name: 'Late', start_ms: T(12, 0), end_ms: T(12, 30), time: '12:00' }),
      it_({ id: 5, status: 'waiting', name: 'Next', start_ms: T(11, 30), end_ms: T(12, 0), time: '11:30',
        wait_since: T(11, 12) }),
      it_({ id: 6, status: 'confirmed', doctor_id: 'd2', start_ms: T(11, 0), end_ms: T(11, 30) }), // чужой врач
    ], NOW)
    expect(f.incab[0]?.next).toEqual({ name: 'Next', time: '11:30', waiting: 18 })
  })

  it('в срок — «следующего» не ищем вовсе; сверх плана — минуты и остаток ноль', () => {
    const f = flowOf([
      it_({ id: 1, status: 'arrived', start_ms: T(11, 0), end_ms: T(12, 0) }),
      it_({ id: 2, status: 'arrived', doctor_id: 'd2', start_ms: T(10, 0), end_ms: T(11, 20) }),
      it_({ id: 3, status: 'confirmed', start_ms: T(12, 0), end_ms: T(12, 30) }),
    ], NOW)
    expect(f.incab.map((r) => [r.it.id, r.min, r.left, r.next])).toEqual([
      [2, 10, 0, null], [1, 0, 30, null],
    ])
  })
})

describe('flow.ts: длительность словами', () => {
  it('минуты до часа, дальше — часы и минуты с ведущим нулём', () => {
    expect([0, 59, 60, 65, 130].map(dur)).toEqual(['0 min', '59 min', '1 h', '1 h 05 min', '2 h 10 min'])
  })
})
