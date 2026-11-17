import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AddDialog } from './AddDialog'
import { controlSlot, type DashCanvasModel } from './dash'
import type { DayForm } from './day'
import { CONTROL, laneEdges, lanesOf, mainLanes, type Occupies, type Room } from './move'
import { SlotDialog, type Fail } from './SlotDialog'

/* Дорожка Control: в неё запись попадает ТОЛЬКО явным выбором
   человека — полосой, полем «Coloana» или кнопкой «Adaugă ca control» в отказе.
   Нетронутое окно `room` не шлёт: решает сервер, а его автовыбор полосу не видит. */

const LANES: Room[] = [{ id: '', name: 'Principal' }, { id: CONTROL, name: 'Control', control: true }]

const FORM: DayForm = {
  doctors: [
    { id: 'd2', name: 'Dr. Ion', spec: '', rooms: LANES, parallel: true },
    { id: 'd3', name: 'Dr. Ana', spec: '' },
  ],
  times: { d2: ['10:00', '11:00'], d3: ['10:00', '11:00'] },
  hours: ['10:00', '11:00'],
  services: [{ id: 'consult', label: 'Consultație', dur: 60 } as DayForm['services'][number]],
  durations: [15, 30, 60], dur_step: 5, dur_max: 240,
  doctor: 'd2', time: '10:00', birth_max: '2026-11-17',
}

type Add = (b: unknown, f: (t: string, code?: string, data?: unknown) => void) => Promise<boolean>

const field = (ph: string) => document.querySelector(`dialog input[placeholder="${ph}"]`) as HTMLInputElement
const form = () => document.querySelector('dialog form') as HTMLFormElement
const asCtl = () => Array.from(document.querySelectorAll('dialog button'))
  .find((b) => b.textContent === 'Adaugă ca control') as HTMLButtonElement | undefined
const fill = () => {
  fireEvent.change(field('Nume pacient'), { target: { value: 'Ion Control' } })
  fireEvent.change(field('Telefon'), { target: { value: '069000111' } })
}

afterEach(() => cleanup())

describe('окно записи: Control только явным выбором', () => {
  it('нетронутое окно у врача с Control `room` не шлёт — сервер не кладёт в Control сам', async () => {
    const onAdd = vi.fn<Add>(async () => true)
    render(<AddDialog open form={FORM} date="2026-11-17" of="" busy={false} onClose={() => {}} onAdd={onAdd} />)
    fill()
    fireEvent.submit(form())
    await waitFor(() => expect(onAdd).toHaveBeenCalled())
    expect(onAdd.mock.calls[0]?.[0]).not.toHaveProperty('room')
  })

  it('отказ «врач занят» даёт кнопку «Adaugă ca control»: та же запись в Control, 15 мин', async () => {
    const onAdd = vi.fn<Add>(async (_b, fail) => { fail('Intervalul este deja ocupat la acest medic', 'conflict'); return false })
    render(<AddDialog open form={FORM} date="2026-11-17" of="" busy={false} onClose={() => {}} onAdd={onAdd} />)
    expect(asCtl()).toBeUndefined()
    fill()
    await act(async () => { fireEvent.submit(form()) })
    expect(asCtl()).toBeDefined()
    onAdd.mockImplementation(async () => true)
    await act(async () => { fireEvent.click(asCtl()!) })
    expect(onAdd.mock.calls[1]?.[0]).toMatchObject({ doctor: 'd2', time: '10:00', room: CONTROL, duration: 15 })
  })

  it('у врача без галочки кнопки в отказе нет', async () => {
    const onAdd = vi.fn<Add>(async (_b, fail) => { fail('Intervalul este deja ocupat la acest medic', 'conflict'); return false })
    render(<AddDialog open form={{ ...FORM, doctor: 'd3' }} date="2026-11-17" of="" busy={false}
      onClose={() => {}} onAdd={onAdd} />)
    fill()
    await act(async () => { fireEvent.submit(form()) })
    expect(document.querySelector('dialog .banner.err')).not.toBeNull()
    expect(asCtl()).toBeUndefined()
  })

  it('другой отказ (дубль пациента) кнопки не даёт', async () => {
    const onAdd = vi.fn<Add>(async (_b, fail) => { fail('Pacientul are deja o programare', 'dup'); return false })
    render(<AddDialog open form={FORM} date="2026-11-17" of="" busy={false} onClose={() => {}} onAdd={onAdd} />)
    fill()
    await act(async () => { fireEvent.submit(form()) })
    expect(asCtl()).toBeUndefined()
  })

  it('выбор «Control» в поле «Coloana» шлёт room и предлагает 15 мин', async () => {
    const onAdd = vi.fn<Add>(async () => true)
    render(<AddDialog open form={FORM} date="2026-11-17" of="" busy={false} onClose={() => {}} onAdd={onAdd} />)
    const lane = document.querySelector('dialog .dp-roompick select') as HTMLSelectElement
    expect(Array.from(lane.options).map((o) => o.value)).toEqual(['', CONTROL])
    fireEvent.change(lane, { target: { value: CONTROL } })
    fill()
    fireEvent.submit(form())
    await waitFor(() => expect(onAdd).toHaveBeenCalled())
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ room: CONTROL, duration: 15 })
  })
})

describe('окно пустого часа: основная занята — выход в Control кнопкой', () => {
  const SFORM = { services: [{ id: 'consult', label: 'Consultație', dur: 60 }], birth_max: '2026-11-17',
    durations: [15, 30, 60], dur_step: 5, dur_max: 240 }
  const slot = (room: string) => ({ dk: 'd2', name: 'Dr. Ion', hour: '10:00', room })
  const busyMain: Occupies[] = [{ id: 1, min: 600, dur: 60, busy: true, room_id: '' }]

  it('Control свободен, основная занята весь час: кнопка шлёт room=~control', async () => {
    const onAdd = vi.fn<(b: unknown, f: Fail) => Promise<boolean>>(async () => true)
    render(<SlotDialog open slot={slot('')} date="2026-11-17" form={SFORM} noteEnds={[11]}
      taken={busyMain} rooms={LANES} busy={false} onClose={() => {}} onAdd={onAdd} onNote={async () => true} />)
    fill()
    expect(asCtl()).toBeDefined()
    await act(async () => { fireEvent.click(asCtl()!) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ room: CONTROL, duration: 15 })
  })

  it('щелчок по полосе Control открывает окно с «Control» и 15 мин', () => {
    render(<SlotDialog open slot={slot(CONTROL)} date="2026-11-17" form={SFORM} noteEnds={[11]}
      taken={busyMain} rooms={LANES} busy={false} onClose={() => {}} onAdd={async () => true}
      onNote={async () => true} />)
    expect((document.querySelector('dialog .dp-roompick select') as HTMLSelectElement).value).toBe(CONTROL)
    expect((document.querySelector('dialog select[aria-label="Durată"]') as HTMLSelectElement).value).toBe('15')
    expect(asCtl()).toBeUndefined()
  })
})

describe('дорожки: Control уже и не считается свободным временем', () => {
  it('края: основная 2/3, Control 1/3; два кабинета + Control — 40/40/20', () => {
    expect(laneEdges(LANES).map((x) => +x.toFixed(3))).toEqual([0, 0.667, 1])
    const three: Room[] = [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }, LANES[1]!]
    expect(laneEdges(three).map((x) => +x.toFixed(3))).toEqual([0, 0.4, 0.8, 1])
  })

  it('основные дорожки без Control; одна основная — записи Control в ней не лежат', () => {
    const items: Occupies[] = [{ id: 1, min: 600, dur: 15, busy: true, room_id: CONTROL }]
    expect(mainLanes(LANES).map((r) => r.id)).toEqual([''])
    expect(lanesOf(items, mainLanes(LANES))).toEqual([[]])
  })
})

describe('отказ с выбором и быстрый контроль', () => {
  const busyData = { who: 'Ion Tabac', from: '10:00', to: '11:00', next: '11:00' }

  it('отказ с данными: «Alege 11:00» ставит время в окно, «Adaugă ca control» на месте', async () => {
    const onAdd = vi.fn<Add>(async (_b, fail) => {
      fail('Medicul are deja o programare 10:00–11:00 (Ion Tabac)', 'conflict', busyData); return false })
    render(<AddDialog open form={FORM} date="2026-11-17" of="" busy={false} onClose={() => {}} onAdd={onAdd} />)
    fill()
    await act(async () => { fireEvent.submit(form()) })
    const next = Array.from(document.querySelectorAll('dialog button')).find((b) => b.textContent === 'Alege 11:00')
    expect(asCtl()).toBeDefined()
    expect(next).toBeDefined()
    fireEvent.click(next!)
    expect(document.querySelector('dialog .banner.err')).toBeNull()
    expect(document.querySelector('.dp-when span')?.textContent).toContain('11:00')
  })

  it('отказ без свободного времени впереди — только «Adaugă ca control»', async () => {
    const onAdd = vi.fn<Add>(async (_b, fail) => { fail('x', 'conflict', { ...busyData, next: null }); return false })
    render(<AddDialog open form={FORM} date="2026-11-17" of="" busy={false} onClose={() => {}} onAdd={onAdd} />)
    fill()
    await act(async () => { fireEvent.submit(form()) })
    expect(asCtl()).toBeDefined()
    expect(Array.from(document.querySelectorAll('dialog button')).some((b) => b.textContent?.startsWith('Alege'))).toBe(false)
  })

  it('быстрый контроль: окно часа записи в полосе Control; без полосы — нет', () => {
    const col = { id: 'd2', name: 'Dr. Ion', rooms: LANES, blocks: [{ id: 7 }] }
    const c = { columns: [col] } as unknown as DashCanvasModel
    expect(controlSlot(c, 7, '10:25')).toEqual({ dk: 'd2', name: 'Dr. Ion', hour: '10:00', minute: 25, room: CONTROL })
    expect(controlSlot({ ...c, columns: [{ ...col, rooms: [] }] } as unknown as DashCanvasModel, 7, '10:25')).toBeNull()
  })
})
