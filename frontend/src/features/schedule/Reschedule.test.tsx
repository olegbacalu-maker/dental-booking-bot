import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DashBlock, DashCanvasModel, DashColumn } from './dash'
import type { DayModel } from './day'
import { CONTROL, type Drag } from './move'
import { Reschedule, type MoveBody } from './Reschedule'

/* «Mută» окна визита у врача с кабинетами и полосой Control: что окно считает
   своим местом и какой кабинет уходит на сервер. Поведение полей дня и часа —
   в `DayScreen.test` («Mută» окна визита). */

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post: vi.fn() } }
})

const DAY = '2026-09-23'
const NEXT = '2026-09-24'
const ROOMS = [{ id: 'r-1', name: 'Cabinet 1' }, { id: 'r-2', name: 'Cabinet 2' },
  { id: CONTROL, name: 'Control', control: true }]

const appt = (id: number, min: number, room: string): DashBlock => ({
  kind: 'appt', id, time: '', min, dur: 30, busy: true, movable: true, top: 0, height: 1, col: 0, of: 1,
  title: '', name: `P${id}`, service: 'Consultație', phone: '', status: 'confirmed', status_label: '',
  urgent: false, source: 'manual', comment: '', comment_cut: '', age: null, doctor: 'Dr. Ion', pid: id,
  rec: false, call: '', callable: false, service_id: 'consult', service_edit: true, room_id: room,
  clickable: true, bg: '', bar: '', wait_since: null,
})

const col = (id: string, name: string, blocks: DashBlock[], rooms = ROOMS): DashColumn => ({
  key: `k:${id}`, id, name, orphan: false, spec: '', off: false, hue: '', photo: '', initials: '',
  rooms, count: blocks.length, free: null, occupancy: null, title: name, cells: [true, true],
  blocks, relink: null,
})

const canvas = (date: string, columns: DashColumn[]): DashCanvasModel => ({
  date, empty: false, base_min: 540, tight: false, bands: { top: null, bottom: null },
  hours: [{ h: 9, label: '09:00', now: false }, { h: 10, label: '10:00', now: false }], columns,
})

const dayOf = (cv: DashCanvasModel) => ({
  data: { date: cv.date, canvas: cv,
    form: { doctors: [{ id: 'd2', name: 'Dr. Ion', spec: '' }, { id: 'd3', name: 'Dr. Ana', spec: '' }] },
  } as unknown as DayModel,
  code: '', text: '', tone: 'ok' as const,
})

const SCREEN = canvas(DAY, [col('d2', 'Dr. Ion', [appt(1, 540, 'r-2'), appt(4, 540, CONTROL)]),
  col('d3', 'Dr. Ana', [], [])])

function show(drag: Drag, next: DashCanvasModel) {
  const onMove = vi.fn<(body: MoveBody, fail: (t: string) => void) => Promise<boolean>>(async () => true)
  const onClose = vi.fn()
  get.mockImplementation((url: string) => Promise.resolve(dayOf(url.includes(NEXT) ? next : SCREEN)))
  render(<Reschedule open drag={drag} canvas={SCREEN} today="2026-09-19" busy={false}
    onClose={onClose} onMove={onMove} />)
  return { onMove, onClose }
}

const yes = () => Array.from(document.querySelectorAll('dialog .mv-act button'))
  .find((x) => x.textContent === 'Da, mută') as HTMLButtonElement
const roomSel = () => document.querySelector('dialog .dp-roompick select') as HTMLSelectElement | null
const pickDate = async (iso: string) => {
  fireEvent.change(document.querySelector('dialog input[type="date"]') as HTMLElement, { target: { value: iso } })
  await waitFor(() => expect(document.querySelector('dialog .dlg-form')?.getAttribute('aria-busy')).toBeNull())
}

afterEach(() => { cleanup(); get.mockReset() })

describe('«Mută» окна визита: кабинеты', () => {
  const IN_R2: Drag = { id: 1, dk: 'd2', min: 540, dur: 30, nm: 'P1', room: 'r-2' }

  it('запись остаётся в своём кабинете: он назван, а на сервер не уходит — его держит сервер', async () => {
    const { onMove, onClose } = show(IN_R2, canvas(NEXT, [col('d2', 'Dr. Ion', [])]))
    expect(roomSel()?.value).toBe('r-2')
    expect(yes().disabled).toBe(true)
    await pickDate(NEXT)
    expect(roomSel()?.value).toBe('r-2')
    fireEvent.click(yes())
    await waitFor(() => expect(onMove).toHaveBeenCalledTimes(1))
    expect(onMove.mock.calls[0]?.[0]).toEqual({ date: NEXT, time: '09:00', doctor: 'd2' })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('свой кабинет в новом дне занят — показан первый свободный; выбранный руками уходит', async () => {
    const { onMove } = show(IN_R2, canvas(NEXT, [col('d2', 'Dr. Ion', [appt(7, 540, 'r-2')])]))
    await pickDate(NEXT)
    expect(roomSel()?.value).toBe('r-1')
    expect(yes().disabled).toBe(false)
    fireEvent.change(roomSel()!, { target: { value: 'r-2' } })
    expect(document.querySelector('dialog .banner.err')?.textContent).toContain('Cabinetul ales este ocupat')
    fireEvent.change(roomSel()!, { target: { value: 'r-1' } })
    fireEvent.click(yes())
    await waitFor(() => expect(onMove.mock.calls[0]?.[0]).toEqual({ date: NEXT, time: '09:00', doctor: 'd2', room: 'r-1' }))
  })

  it('та же минута того же дня в другом кабинете — перенос, а не своё место', async () => {
    const { onMove } = show(IN_R2, SCREEN)
    fireEvent.change(roomSel()!, { target: { value: 'r-1' } })
    expect(yes().disabled).toBe(false)
    fireEvent.click(yes())
    await waitFor(() => expect(onMove.mock.calls[0]?.[0]).toEqual({ date: DAY, time: '09:00', doctor: 'd2', room: 'r-1' }))
  })

  it('запись полосы Control остаётся в полосе и на другой день — явным ключом', async () => {
    const { onMove } = show({ id: 4, dk: 'd2', min: 540, dur: 30, nm: 'P4', room: CONTROL },
      canvas(NEXT, [col('d2', 'Dr. Ion', [])]))
    expect(roomSel()?.value).toBe(CONTROL)
    expect(yes().disabled).toBe(true)
    await pickDate(NEXT)
    expect(roomSel()?.value).toBe(CONTROL)
    fireEvent.click(yes())
    await waitFor(() => expect(onMove.mock.calls[0]?.[0]).toEqual({ date: NEXT, time: '09:00', doctor: 'd2', room: CONTROL }))
  })

  it('другой врач без кабинетов: поля кабинета нет, выбор прежнего врача не уходит', async () => {
    const { onMove } = show({ id: 4, dk: 'd2', min: 540, dur: 30, nm: 'P4', room: CONTROL }, SCREEN)
    await waitFor(() => expect(document.querySelector('dialog select[aria-label="Medic"]')).toBeTruthy())
    fireEvent.change(document.querySelector('dialog select[aria-label="Medic"]') as HTMLElement, { target: { value: 'd3' } })
    expect(roomSel()).toBeNull()
    expect(Array.from(document.querySelectorAll('dialog .mv-rows b')).map((x) => x.textContent)[2])
      .toBe('Dr. Ana · miercuri, 23.09 · 09:00')
    fireEvent.click(yes())
    await waitFor(() => expect(onMove.mock.calls[0]?.[0]).toEqual({ date: DAY, time: '09:00', doctor: 'd3' }))
  })

  it('отказ: окно не закрывается и печатает слово отказа', async () => {
    const { onMove, onClose } = show(IN_R2, canvas(NEXT, [col('d2', 'Dr. Ion', [])]))
    onMove.mockImplementation(async (_b, fail) => { fail('Pacientul are deja o programare la această oră'); return false })
    await pickDate(NEXT)
    fireEvent.click(yes())
    await waitFor(() => expect(document.querySelector('dialog .banner.err')?.textContent)
      .toBe('Pacientul are deja o programare la această oră'))
    expect(onClose).not.toHaveBeenCalled()
  })
})
