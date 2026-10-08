import { describe, expect, it } from 'vitest'
import { firstFreeHour, freeSlots } from './free'
import type { DashBlock, DashCanvasModel, DashColumn } from './dash'

/* «Primul loc liber» — первый свободный целый час по канве. */

function note(top: number, height: number): DashBlock {
  return { id: 100 + top, kind: 'note', top, height, col: 0, of: 1, title: 'Pauză',
    label: 'Pauză', status: 'confirmed', movable: true } as DashBlock
}

function col(over: Partial<DashColumn> = {}): DashColumn {
  return {
    key: 'd1', id: 'd1', name: 'Dr. Ion', orphan: false, spec: 'Terapie', off: false,
    hue: '#2e8b57', photo: '', initials: 'DI', count: 0, free: null, occupancy: null,
    title: 'Dr. Ion', cells: [true, true, true, true], blocks: [], relink: null, ...over,
  }
}

const HOURS = [9, 10, 11, 12]

function canvas(columns: DashColumn[]): DashCanvasModel {
  return { date: '2026-10-08', empty: false, base_min: 540, tight: false,
    hours: HOURS.map((h) => ({ h, label: `${h}:00`, now: false })),
    bands: { top: null, bottom: null }, columns }
}

describe('firstFreeHour', () => {
  it('первый открытый незанятый час; закрытая ячейка пропускается', () => {
    expect(firstFreeHour(col({ cells: [false, true, true, true] }), HOURS, 0)).toBe(10)
  })
  it('блок визита занимает свои часы, в том числе полуторачасовой — два ряда', () => {
    const c = col({ blocks: [{ ...note(0, 1.5), kind: 'appt' } as DashBlock] })
    expect(firstFreeHour(c, HOURS, 0)).toBe(11)
  })
  it('заметка стойки тоже занимает час — записать в неё сервер не даст', () => {
    expect(firstFreeHour(col({ blocks: [note(0, 1)] }), HOURS, 0)).toBe(10)
  })
  it('нижняя граница: часы раньше `fromHour` не предлагаются', () => {
    expect(firstFreeHour(col(), HOURS, 11)).toBe(11)
  })
  it('ничего свободного — null', () => {
    expect(firstFreeHour(col({ cells: [false, false, false, false] }), HOURS, 0)).toBeNull()
    expect(firstFreeHour(col({ blocks: [note(0, 4)] }), HOURS, 0)).toBeNull()
  })
})

describe('freeSlots', () => {
  it('сегодня — от СЛЕДУЮЩЕГО целого часа: 11:01 → 12:00, 11:00 ровно → 11:00', () => {
    expect(freeSlots(canvas([col()]), { hh: 11, mm: 1 })[0]!.hour).toBe('12:00')
    expect(freeSlots(canvas([col()]), { hh: 11, mm: 0 })[0]!.hour).toBe('11:00')
  })
  it('чужой день — с начала рабочего дня', () => {
    expect(freeSlots(canvas([col()]), null)[0]!.hour).toBe('09:00')
  })
  it('сирота и неактивный врач: сироты в списке нет, у неактивного часа нет', () => {
    const rows = freeSlots(canvas([
      col({ key: 'x', id: null, orphan: true, cells: [] }),
      col({ key: 'off', id: 'd9', off: true }),
    ]), null)
    expect(rows.map((r) => [r.dk, r.hour])).toEqual([['d9', null]])
  })
  it('после конца дня сегодня — свободных нет', () => {
    expect(freeSlots(canvas([col()]), { hh: 12, mm: 30 })[0]!.hour).toBeNull()
  })
})
