import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DashBlock, DashCanvasModel, DashColumn } from './dash'
import type { DayModel } from './day'
import { CONTROL, type Drag } from './move'
import { Reschedule, type MoveBody } from './Reschedule'

/* «Mută» окна визита у врача с кабинетами и полосой Control: что окно считает
   своим местом и какой кабинет уходит на сервер; и что держит высоту окна — место
   под поле кабинета, место под слово, строки в одну строку. Поведение полей дня и
   часа — в `DayScreen.test` («Mută» окна визита). */

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
    /* форма несёт кабинеты каждого врача, которого можно выбрать (`form_spec` › `rooms`) */
    form: { doctors: [{ id: 'd2', name: 'Dr. Ion', spec: '', rooms: ROOMS }, { id: 'd3', name: 'Dr. Ana', spec: '', rooms: [] }] },
  } as unknown as DayModel,
  code: '', text: '', tone: 'ok' as const,
})

const SCREEN = canvas(DAY, [col('d2', 'Dr. Ion', [appt(1, 540, 'r-2'), appt(4, 540, CONTROL)]),
  col('d3', 'Dr. Ana', [], [])])

function show(drag: Drag, next: DashCanvasModel, screen: DashCanvasModel = SCREEN) {
  const onMove = vi.fn<(body: MoveBody, fail: (t: string) => void) => Promise<boolean>>(async () => true)
  const onClose = vi.fn()
  get.mockImplementation((url: string) => Promise.resolve(dayOf(url.includes(NEXT) ? next : SCREEN)))
  render(<Reschedule open drag={drag} canvas={screen} today="2026-09-19" busy={false}
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

  it('другой врач без кабинетов: поле кабинета стоит выключенным, выбор прежнего врача не уходит', async () => {
    const { onMove } = show({ id: 4, dk: 'd2', min: 540, dur: 30, nm: 'P4', room: CONTROL }, SCREEN)
    await waitFor(() => expect(
      (document.querySelector('dialog select[aria-label="Medic"]') as HTMLSelectElement).options).toHaveLength(2))
    fireEvent.change(document.querySelector('dialog select[aria-label="Medic"]') as HTMLElement, { target: { value: 'd3' } })
    /* место под поле занято: у кого-то из врачей кабинеты есть, окно при смене врача не растёт */
    expect(roomSel()?.disabled).toBe(true)
    expect(roomSel()?.textContent).toBe('—')
    expect(document.querySelectorAll('dialog .dp-roompick')).toHaveLength(1)
    expect(Array.from(document.querySelectorAll('dialog .mv-rows b')).map((x) => x.textContent)[2])
      .toBe('miercuri, 23.09 · 09:00 · Dr. Ana')
    fireEvent.click(yes())
    await waitFor(() => expect(onMove.mock.calls[0]?.[0]).toEqual({ date: DAY, time: '09:00', doctor: 'd3' }))
    /* обратно к врачу с кабинетами — то же одно поле, уже с выбором */
    fireEvent.change(document.querySelector('dialog select[aria-label="Medic"]') as HTMLElement, { target: { value: 'd2' } })
    expect(roomSel()?.disabled).toBe(false)
    expect(document.querySelectorAll('dialog .dp-roompick')).toHaveLength(1)
  })

  it('врач с одним кабинетом: выключенное поле называет его кабинет', async () => {
    const one = canvas(DAY, [col('d2', 'Dr. Ion', [appt(1, 540, 'r-2')]),
      col('d3', 'Dr. Ana', [appt(8, 600, 'r-9')], [{ id: 'r-9', name: 'Cabinet 9' }])])
    show({ id: 8, dk: 'd3', min: 600, dur: 30, nm: 'P8', room: 'r-9' }, one, one)
    expect(roomSel()?.disabled).toBe(true)
    expect(roomSel()?.textContent).toBe('Cabinet 9')
  })

  it('клиника без кабинетов: поля кабинета и пустого места под него нет', async () => {
    const plain = canvas(DAY, [col('d2', 'Dr. Ion', [appt(1, 540, '')], []), col('d3', 'Dr. Ana', [], [])])
    get.mockImplementation(() => Promise.resolve({ ...dayOf(plain), data: { ...dayOf(plain).data,
      form: { doctors: [{ id: 'd2', name: 'Dr. Ion', spec: '', rooms: [] }, { id: 'd3', name: 'Dr. Ana', spec: '', rooms: [] }] } } }))
    render(<Reschedule open drag={{ id: 1, dk: 'd2', min: 540, dur: 30, nm: 'P1' }} canvas={plain} today="2026-09-19"
      busy={false} onClose={() => {}} onMove={async () => true} />)
    await waitFor(() => expect(
      (document.querySelector('dialog select[aria-label="Medic"]') as HTMLSelectElement).options).toHaveLength(2))
    expect(document.querySelector('dialog .dp-roompick')).toBeNull()
  })

  it('день одного врача: окно ждёт общий день и открывается уже с местом под кабинет', async () => {
    let answer: (v: ReturnType<typeof dayOf>) => void = () => {}
    get.mockImplementation(() => new Promise((res) => { answer = res }))
    /* канва экрана знает одного врача без кабинетов; у другого врача они есть */
    const mine = canvas(DAY, [col('d3', 'Dr. Ana', [appt(8, 600, '')], [])])
    render(<Reschedule open drag={{ id: 8, dk: 'd3', min: 600, dur: 30, nm: 'P8' }} canvas={mine} today="2026-09-19"
      busy={false} onClose={() => {}} onMove={async () => true} />)
    expect(document.querySelector('dialog[open]')).toBeNull()
    await act(async () => { answer(dayOf(SCREEN)) })
    await waitFor(() => expect(document.querySelector('dialog[open]')).toBeTruthy())
    expect(roomSel()?.disabled).toBe(true)
  })

  it('общий день не отвечает: окно открывается само, не дожидаясь', async () => {
    vi.useFakeTimers()
    try {
      get.mockImplementation(() => new Promise(() => {}))
      const mine = canvas(DAY, [col('d3', 'Dr. Ana', [appt(8, 600, '')], [])])
      render(<Reschedule open drag={{ id: 8, dk: 'd3', min: 600, dur: 30, nm: 'P8' }} canvas={mine} today="2026-09-19"
        busy={false} onClose={() => {}} onMove={async () => true} />)
      expect(document.querySelector('dialog[open]')).toBeNull()
      act(() => { vi.advanceTimersByTime(1600) })
      expect(document.querySelector('dialog[open]')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('строки «De la» / «La» — в одну строку: полный текст в подсказке', () => {
    show(IN_R2, SCREEN)
    const rows = Array.from(document.querySelectorAll('dialog .mv-rows.mv-fix b'))
    expect(rows.map((x) => x.textContent)).toEqual(['P1', 'miercuri, 23.09 · 09:00 · Dr. Ion · Cabinet 2',
      'miercuri, 23.09 · 09:00 · Dr. Ion · Cabinet 2'])
    expect(rows.map((x) => x.getAttribute('title'))).toEqual(rows.map((x) => x.textContent))
  })

  it('основная занята, Control свободен: отдельной кнопки нет — Control выбирают в поле кабинета', async () => {
    const busyDay = canvas(NEXT, [col('d2', 'Dr. Ion', [appt(7, 540, 'r-1'), appt(9, 540, 'r-2')])])
    const { onMove } = show(IN_R2, busyDay)
    await pickDate(NEXT)
    expect(document.querySelector('dialog .mv-say .banner:not(.mv-say-room)')?.textContent)
      .toBe('Medicul are deja o programare la 09:00.')
    expect(document.querySelector('dialog .dp-asctl')).toBeNull()
    expect(yes().disabled).toBe(true)
    fireEvent.change(roomSel()!, { target: { value: CONTROL } })
    expect(yes().disabled).toBe(false)
    fireEvent.click(yes())
    await waitFor(() => expect(onMove.mock.calls[0]?.[0]).toEqual({ date: NEXT, time: '09:00', doctor: 'd2', room: CONTROL }))
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
