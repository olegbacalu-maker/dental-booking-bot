import { describe, expect, it } from 'vitest'
import { clash, doctorName, dragOf, halfAt, hhmm, sameSlot } from './move'
import type { DayItem, DayModel } from './day'

/* Договор перетаскивания по одному полю. Каждая проверка ломается ровно одним
   изменением в move.ts — так и задумано: половина договора хуже его
   отсутствия, и «поехало» тут видно только руками. */

const appt = (id: number, min: number, extra: Partial<DayItem> = {}): DayItem => ({
  kind: 'appt', id, time: hhmm(min), name: `Pacient ${id}`, service: 'Consultație',
  phone: '069000000', status: 'confirmed', status_label: 'Confirmat', urgent: false,
  source: 'panel', dur: 60, comment: '', age: null, clickable: true,
  bg: 'var(--green-soft)', bar: 'var(--green)', min, busy: true, movable: true,
  ...extra,
} as DayItem)

const model = (items: DayItem[][]): DayModel => ({
  date: '2026-09-23',
  doctors: [{ id: 'd2', name: 'Dr. Activ Doi', spec: '' },
    { id: 'd3', name: 'Dr. Activ Trei', spec: '' }],
  hours: [9, 10, 11].map((h, i) => ({
    h, label: hhmm(h * 60), closed: '' as const, now: false,
    cells: [{ kind: 'appts' as const, drop: true, items: items[i] ?? [] },
      { kind: 'free' as const, drop: true, items: [] }],
  })),
  form: null, note_ends: [], cards: {}, actions: {}, note_actions: {},
  list: [], filter: null,
})

describe('час и получас', () => {
  it('минуты превращаются в HH:MM с ведущими нулями', () => {
    expect([hhmm(0), hhmm(540), hhmm(570), hhmm(1290)])
      .toEqual(['00:00', '09:00', '09:30', '21:30'])
  })

  it('верх ячейки — ровный час, низ — половина', () => {
    const rect = { top: 100, height: 56 }
    expect(halfAt(100, rect)).toBe(0)
    expect(halfAt(127, rect)).toBe(0)
    expect(halfAt(128, rect)).toBe(30)
    expect(halfAt(155, rect)).toBe(30)
  })
})

describe('что можно тащить', () => {
  it('активный визит отдаёт четыре поля и имя', () => {
    expect(dragOf(appt(1, 600), 'd2'))
      .toEqual({ id: 1, dk: 'd2', min: 600, dur: 60, nm: 'Pacient 1' })
  })

  it('закрытый визит не тащится вовсе', () => {
    expect(dragOf(appt(1, 600, { movable: false, busy: false, status: 'done' }), 'd2'))
      .toBeNull()
  })

  it('заметка тащится под СВОИМ текстом, а не под именем пациента', () => {
    const note: DayItem = { kind: 'note', id: 9, time: '11:00', text: 'Livrare',
      min: 660, dur: 60, busy: true, movable: true }
    expect(dragOf(note, 'd2')?.nm).toBe('Livrare')
  })

  it('нулевая длительность подменяется часом', () => {
    expect(dragOf(appt(1, 600, { dur: 0 }), 'd2')?.dur).toBe(60)
  })
})

describe('бросок на своё место', () => {
  const d = { id: 1, dk: 'd2', min: 600, dur: 60, nm: 'X' }

  it('та же колонка и та же минута — не перенос', () => {
    expect(sameSlot(d, { dk: 'd2', min: 600 })).toBe(true)
  })

  it('а получас того же часа — уже перенос', () => {
    expect(sameSlot(d, { dk: 'd2', min: 630 })).toBe(false)
  })

  it('и другой врач на тот же час — тоже перенос', () => {
    expect(sameSlot(d, { dk: 'd3', min: 600 })).toBe(false)
  })
})

describe('подсказка о занятости', () => {
  const m = model([[appt(1, 540)], [appt(2, 600)], []])

  it('пересечение находится и называет минуту помехи', () => {
    expect(clash(m, { dk: 'd2', min: 630 }, 60, 1)).toBe(600)
  })

  it('стык впритык помехой не считается', () => {
    expect(clash(m, { dk: 'd2', min: 660 }, 60, 1)).toBe(-1)
  })

  it('себя запись не находит — иначе перенос к соседу всегда «занято»', () => {
    expect(clash(m, { dk: 'd2', min: 540 }, 60, 1)).toBe(-1)
  })

  it('чужая колонка не мешает', () => {
    expect(clash(m, { dk: 'd3', min: 600 }, 60, 1)).toBe(-1)
  })

  it('завершённый визит места не занимает', () => {
    const done = model([[appt(1, 540)], [appt(2, 600, { busy: false })], []])
    expect(clash(done, { dk: 'd2', min: 600 }, 60, 1)).toBe(-1)
  })

  it('длительность соседа учитывается, а не «час по умолчанию»', () => {
    const long = model([[appt(1, 540, { dur: 120 })], [], []])
    expect(clash(long, { dk: 'd2', min: 630 }, 30, 7)).toBe(540)
  })

  it('неизвестная колонка — не мишень', () => {
    expect(clash(m, { dk: 'd9', min: 600 }, 60, 1)).toBe(-1)
  })
})

describe('имя колонки', () => {
  it('берётся из модели, а не из ссылок страницы', () => {
    expect(doctorName(model([]), 'd3')).toBe('Dr. Activ Trei')
    expect(doctorName(model([]), 'nimeni')).toBe('—')
  })
})
