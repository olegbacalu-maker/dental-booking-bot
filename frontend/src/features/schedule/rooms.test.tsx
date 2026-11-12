import { createRef } from 'react'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CardDialog } from './CardDialog'
import { DashCanvas } from './DashCanvas'
import type { DashBlock, DashCanvasModel, DashColumn } from './dash'
import type { VisitCardView } from './day'
import { MoveDialog } from './MoveDialog'
import { clashLanes, freeRoom, lanesOf, roomShared, roomTag, sameSlot, type Occupies,
  type Room } from './move'
import { SlotDialog, type Fail } from './SlotDialog'
import { takenMinutes } from './slot'

/* Кабинет у записи на экране. У врача с несколькими кабинетами занятость
   считается ПО КАБИНЕТУ: старт свободен, пока свободен хоть один; заметка
   стойки занимает все. У врача с одним кабинетом на экране ничего нового. */

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post: vi.fn() } }
})

const R1: Room = { id: 'r-1', name: 'Cabinet 1' }
const R2: Room = { id: 'r-2', name: 'Cabinet 2' }
const ROOMS = [R1, R2]
const b = (id: number, min: number, dur: number, room?: string): Occupies =>
  ({ id, min, dur, busy: true, ...(room === undefined ? {} : { room_id: room }) })

afterEach(() => { cleanup(); vi.restoreAllMocks(); get.mockReset() })

describe('занятость по кабинетам', () => {
  it('у врача с одним кабинетом список один — как до кабинетов', () => {
    const items = [b(1, 540, 60, 'r-1')]
    expect(lanesOf(items, [R1])).toEqual([items])
    expect(lanesOf(items, [])).toEqual([items])
  })

  it('старт свободен, пока свободен хоть один кабинет', () => {
    const lanes = lanesOf([b(1, 540, 60, 'r-1')], ROOMS)
    expect(clashLanes(lanes, 540, 30, -1)).toBe(-1)
    const both = lanesOf([b(1, 540, 60, 'r-1'), b(2, 540, 30, 'r-2')], ROOMS)
    expect(clashLanes(both, 540, 30, -1)).toBe(540)
    expect(clashLanes(both, 570, 30, -1)).toBe(-1)
    expect([...takenMinutes(both, 9, 30, 15)]).toEqual([0, 15])
  })

  it('заметка стойки (без кабинета) занимает все кабинеты', () => {
    const lanes = lanesOf([b(1, 540, 60)], ROOMS)
    expect(clashLanes(lanes, 540, 30, -1)).toBe(540)
  })

  it('первый свободный кабинет — по порядку списка врача', () => {
    expect(freeRoom([], ROOMS, 540, 30, -1)).toBe('r-1')
    expect(freeRoom([b(1, 540, 60, 'r-1')], ROOMS, 540, 30, -1)).toBe('r-2')
    expect(freeRoom([b(1, 540, 60, 'r-1'), b(2, 540, 60, 'r-2')], ROOMS, 540, 30, -1)).toBe('')
    /* переносимая запись сама себе не помеха */
    expect(freeRoom([b(1, 540, 60, 'r-1')], ROOMS, 540, 30, 1)).toBe('r-1')
  })

  it('кабинет занят другим врачом — только в том же кабинете и в то же время', () => {
    const others = [b(5, 540, 60, 'r-2')]
    expect(roomShared(others, 'r-2', 570, 30)).toBe(true)
    expect(roomShared(others, 'r-1', 570, 30)).toBe(false)
    expect(roomShared(others, 'r-2', 600, 30)).toBe(false)
    expect(roomShared(others, '', 570, 30)).toBe(false)
  })

  it('метка кабинета на блоке — коротко', () => {
    expect(roomTag('Cabinet 2')).toBe('2')
    expect(roomTag('Cab. 12')).toBe('12')
    expect(roomTag('Chirurgie')).toBe('Chi')
    expect(roomTag('3')).toBe('3')
    expect(roomTag('Cabinet')).toBe('Cab')
  })

  it('та же минута в другом кабинете — перенос, а не «своё же место»', () => {
    const d = { id: 1, dk: 'd2', min: 540, dur: 30, nm: 'A', room: 'r-1' }
    expect(sameSlot(d, { dk: 'd2', min: 540, room: 'r-1' })).toBe(true)
    expect(sameSlot(d, { dk: 'd2', min: 540, room: 'r-2' })).toBe(false)
    expect(sameSlot(d, { dk: 'd2', min: 540 })).toBe(true)
  })
})

const FORM = { services: [{ id: 'consult', label: 'Consultație', dur: 30 }], birth_max: '2026-10-17' }
const SLOT = { dk: 'd2', name: 'Dr. Ion', hour: '10:00' }
const mp = () => Array.from(document.querySelectorAll('.dp-minpick .mp')) as HTMLButtonElement[]
const off = () => mp().filter((x) => x.disabled).map((x) => x.textContent)
const roomSel = () => document.querySelector('dialog .dp-roompick select') as HTMLSelectElement | null
const warn = () => document.querySelector('dialog .banner.warn')?.textContent ?? ''
const err = () => document.querySelector('dialog .banner.err')?.textContent ?? ''
const fill = () => {
  fireEvent.change(document.querySelector('dialog input[placeholder="Nume pacient"]') as HTMLElement,
    { target: { value: 'Ion Popa' } })
  fireEvent.change(document.querySelector('dialog input[placeholder="Telefon"]') as HTMLElement,
    { target: { value: '069000000' } })
}
const submit = () => document.querySelector('dialog form button:not([type="button"])') as HTMLButtonElement

function slot(taken: Occupies[], opts: { rooms?: Room[]; others?: Occupies[]; room?: string } = {},
  onAdd: (body: unknown, fail: Fail) => Promise<boolean> = async () => true) {
  return render(<SlotDialog open slot={{ ...SLOT, ...(opts.room ? { room: opts.room } : {}) }}
    date="2026-10-17" form={FORM} noteEnds={[11, 12]} taken={taken} rooms={opts.rooms ?? ROOMS}
    others={opts.others ?? []} busy={false} onClose={() => {}} onAdd={onAdd}
    onNote={async () => true} />)
}

describe('окно свободного часа: кабинет', () => {
  it('у врача с одним кабинетом выбора нет и поле не уходит', async () => {
    const onAdd = vi.fn<(body: unknown, f: Fail) => Promise<boolean>>(async () => true)
    slot([], { rooms: [R1] }, onAdd)
    expect(roomSel()).toBeNull()
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd.mock.calls[0]?.[0]).not.toHaveProperty('room')
  })

  it('по умолчанию — первый свободный в это время; нетронутый выбор не уходит', async () => {
    const onAdd = vi.fn<(body: unknown, f: Fail) => Promise<boolean>>(async () => true)
    slot([b(1, 600, 60, 'r-1')], {}, onAdd)
    expect(roomSel()?.value).toBe('r-2')
    /* второй кабинет свободен — минуты часа не гаснут */
    expect(off()).toEqual([])
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd.mock.calls[0]?.[0]).not.toHaveProperty('room')
  })

  it('выбранный кабинет: минуты считаются по нему, поле уходит', async () => {
    const onAdd = vi.fn<(body: unknown, f: Fail) => Promise<boolean>>(async () => true)
    slot([b(1, 600, 20, 'r-1')], {}, onAdd)
    fireEvent.change(roomSel()!, { target: { value: 'r-1' } })
    expect(off()).toEqual([':00', ':05', ':10', ':15'])
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ room: 'r-1', time: '10:20' })
  })

  it('щелчок по дорожке кабинета — кабинет выбран сразу и уходит', async () => {
    const onAdd = vi.fn<(body: unknown, f: Fail) => Promise<boolean>>(async () => true)
    slot([], { room: 'r-2' }, onAdd)
    expect(roomSel()?.value).toBe('r-2')
    fill()
    await act(async () => { fireEvent.click(submit()) })
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ room: 'r-2' })
  })

  it('кабинет занят другим врачом — предупреждение словом, записать можно', () => {
    slot([], { others: [b(7, 600, 60, 'r-1')] })
    expect(warn()).toContain('Cabinet 1')
    expect(err()).toBe('')
    expect(submit().disabled).toBe(false)
    fireEvent.change(roomSel()!, { target: { value: 'r-2' } })
    expect(warn()).toBe('')
  })
})

function move(taken: Occupies[], opts: { others?: Occupies[]; targetRoom?: string; min?: number } = {},
  onMove = vi.fn()) {
  render(<MoveDialog open drag={{ id: 1, dk: 'd2', min: 540, dur: 30, nm: 'Ion Popa', room: 'r-1' }}
    target={{ dk: 'd2', min: opts.min ?? 600, ...(opts.targetRoom ? { room: opts.targetRoom } : {}) }}
    fromName="Dr. Ion" toName="Dr. Ion" taken={taken} rooms={ROOMS} others={opts.others ?? []}
    hours={['09:00', '10:00']} busy={false} onClose={() => {}} onMove={onMove} />)
  return onMove
}
const yes = () => Array.from(document.querySelectorAll('dialog .mv-act button'))
  .find((x) => x.textContent === 'Da, mută') as HTMLButtonElement

describe('окно переноса: кабинет', () => {
  it('у того же врача запись остаётся в своём кабинете; кабинет не уходит', () => {
    const onMove = move([b(1, 540, 30, 'r-1')])
    expect(roomSel()?.value).toBe('r-1')
    fireEvent.click(yes())
    expect(onMove).toHaveBeenCalledWith(600, undefined)
  })

  it('свой кабинет занят на новое время — первый свободный', () => {
    move([b(1, 540, 30, 'r-1'), b(2, 600, 30, 'r-1')])
    expect(roomSel()?.value).toBe('r-2')
    expect(err()).toBe('')
  })

  it('бросок в дорожку другого кабинета на то же время — перенос с кабинетом', () => {
    const onMove = move([b(1, 540, 30, 'r-1')], { targetRoom: 'r-2', min: 540 })
    expect(roomSel()?.value).toBe('r-2')
    expect(yes().disabled).toBe(false)
    fireEvent.click(yes())
    expect(onMove).toHaveBeenCalledWith(540, 'r-2')
  })

  it('выбранный кабинет занят — сказано про кабинет, кнопка выключена', () => {
    move([b(1, 540, 30, 'r-1'), b(2, 600, 30, 'r-2')])
    fireEvent.change(roomSel()!, { target: { value: 'r-2' } })
    expect(err()).toContain('Cabinetul ales este ocupat')
    expect(yes().disabled).toBe(true)
  })

  it('кабинет занят другим врачом — предупреждение, перенос разрешён', () => {
    move([b(1, 540, 30, 'r-1')], { others: [b(9, 600, 30, 'r-1')] })
    expect(warn()).toContain('Cabinet 1')
    expect(yes().disabled).toBe(false)
  })
})

const CARD: VisitCardView = {
  time: '09:00', name: 'Ion Popa', service: 'Consultație', doctor: 'Dr. Ion', phone: '', age: null,
  comment: '', status: 'confirmed', pid: 17, rec: false, call: '', callable: false,
  service_id: 'consult', service_edit: true, dur: 30, room_id: 'r-1', room: 'Cabinet 1',
}

function card(over: Partial<VisitCardView> = {}, rooms: Room[] = ROOMS,
  onRoom = vi.fn<(room: string, fail: (t: string) => void) => Promise<boolean>>(async () => true)) {
  get.mockResolvedValue({ status: 200, data: { service_id: 'consult', options: [] } })
  render(<CardDialog open id={5} card={{ ...CARD, ...over }} actions={[]} back="/admin" busy={false}
    onClose={() => {}} onComment={async () => true} onStatus={async () => true}
    rooms={rooms} onRoom={onRoom} />)
  return onRoom
}
const pen = () => document.querySelector('dialog button[aria-label="Schimbă cabinetul"]') as HTMLButtonElement | null

describe('окно визита: кабинет', () => {
  it('у врача с одним кабинетом кабинета в окне нет', () => {
    card({}, [R1])
    expect(document.querySelector('dialog .dp-card-room')).toBeNull()
    expect(pen()).toBeNull()
  })

  it('назван кабинет; карандаш переводит запись в другой', async () => {
    const onRoom = card()
    expect(document.querySelector('dialog .dp-card-room')?.textContent).toContain('Cabinet 1')
    fireEvent.click(pen()!)
    const sel = document.querySelector('dialog form[aria-label="Cabinet"] select') as HTMLSelectElement
    const go = document.querySelector('dialog form[aria-label="Cabinet"] button:not([type="button"])') as HTMLButtonElement
    expect(go.disabled).toBe(true)
    fireEvent.change(sel, { target: { value: 'r-2' } })
    await act(async () => { fireEvent.click(go) })
    expect(onRoom.mock.calls[0]?.[0]).toBe('r-2')
  })

  it('у закрытой записи кабинет назван, карандаша нет', () => {
    card({ status: 'done', service_edit: false })
    expect(document.querySelector('dialog .dp-card-room')?.textContent).toContain('Cabinet 1')
    expect(pen()).toBeNull()
  })

  it('отказ сервера печатается в окне', async () => {
    const onRoom = vi.fn(async (_room: string, fail: (t: string) => void) => { fail('Interval ocupat'); return false })
    card({}, ROOMS, onRoom)
    fireEvent.click(pen()!)
    fireEvent.change(document.querySelector('dialog form[aria-label="Cabinet"] select') as HTMLElement,
      { target: { value: 'r-2' } })
    await act(async () => {
      fireEvent.click(document.querySelector('dialog form[aria-label="Cabinet"] button:not([type="button"])') as HTMLElement)
    })
    expect(err()).toBe('Interval ocupat')
  })
})

function appt(over: Partial<Extract<DashBlock, { kind: 'appt' }>>): Extract<DashBlock, { kind: 'appt' }> {
  return {
    kind: 'appt', id: 1, time: '09:00', min: 540, dur: 60, busy: true, movable: true,
    top: 0, height: 1, col: 0, of: 2, title: '', name: 'Ion Popa', service: 'Consultație', phone: '',
    status: 'confirmed', status_label: 'confirmată', urgent: false, source: 'manual',
    comment: '', comment_cut: '', age: null, doctor: 'Dr. Ion', pid: 17, rec: false, call: '',
    callable: true, clickable: true, service_id: 'consult', service_edit: true,
    room_id: 'r-1', room: 'Cabinet 1', bg: 'var(--green-soft)', bar: 'var(--green)',
    wait_since: null, ...over,
  }
}

function canvas(col: Partial<DashColumn>): DashCanvasModel {
  return {
    date: '2026-10-17', empty: false, base_min: 540, tight: false,
    hours: [{ h: 9, label: '09:00', now: false }, { h: 10, label: '10:00', now: false }],
    bands: { top: null, bottom: null },
    columns: [{
      key: 'k:d2', id: 'd2', name: 'Dr. Ion', orphan: false, spec: '', off: false, hue: 'var(--teal)',
      photo: '', initials: 'DI', room: 'Cabinet 1, Cabinet 2', rooms: ROOMS, phone: '', count: 1,
      free: '09:00', occupancy: null, title: '', cells: [true, true], blocks: [], relink: null, ...col,
    }],
  }
}

function draw(model: DashCanvasModel) {
  const onSlot = vi.fn()
  /* ячейка 200×60 в (0, 0): левая половина — первый кабинет */
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
    () => ({ left: 0, top: 0, width: 200, height: 60, right: 200, bottom: 60, x: 0, y: 0, toJSON: () => ({}) }))
  render(<DashCanvas model={model} rail={createRef<HTMLDivElement>()} waitTick={0} lineTick={0}
    onCard={() => {}} onSlot={onSlot} onNote={() => {}} drag={null} hover="" onDrag={() => {}}
    onHover={() => {}} onDrop={() => {}} fresh={new Set()} />)
  return onSlot
}
const cell = (h: number) => document.querySelector(`.gcell[data-h="${h}"]`) as HTMLButtonElement

describe('канва: дорожки кабинетов', () => {
  it('колонка врача с двумя кабинетами размечена, на блоке метка кабинета', () => {
    draw(canvas({ blocks: [appt({}), appt({ id: 2, col: 1, room_id: 'r-2', room: 'Cabinet 2', name: 'Ana Rusu' })] }))
    expect(document.querySelector('.gcol')?.getAttribute('data-lanes')).toBe('2')
    expect(Array.from(document.querySelectorAll('.gappt .groom')).map((x) => x.textContent)).toEqual(['1', '2'])
  })

  it('у врача с одним кабинетом ни дорожек, ни метки', () => {
    draw(canvas({ rooms: [R1], room: 'Cabinet 1', blocks: [appt({ of: 1 })] }))
    expect(document.querySelector('.gcol')?.hasAttribute('data-lanes')).toBe(false)
    expect(document.querySelector('.gappt .groom')).toBeNull()
  })

  it('час занят в одном кабинете — ячейка открыта, щелчок в свободную дорожку даёт её кабинет', () => {
    const onSlot = draw(canvas({ blocks: [appt({})] }))
    expect(cell(9).disabled).toBe(false)
    fireEvent.click(cell(9), { detail: 1, clientX: 150, clientY: 5 })
    expect(onSlot).toHaveBeenLastCalledWith('d2', 'Dr. Ion', '09:00', 0, 'r-2')
    /* щелчок в занятую дорожку и с клавиатуры — первая свободная */
    fireEvent.click(cell(9), { detail: 1, clientX: 20, clientY: 5 })
    expect(onSlot).toHaveBeenLastCalledWith('d2', 'Dr. Ion', '09:00', 0, 'r-2')
    fireEvent.click(cell(10), { detail: 1, clientX: 20, clientY: 5 })
    expect(onSlot).toHaveBeenLastCalledWith('d2', 'Dr. Ion', '10:00', 0, 'r-1')
  })

  it('ширина блока — доля его дорожки: сосед по кабинету делит её, чужой кабинет — нет', () => {
    /* место (`col`/`of`) считает сервер по одновременным записям ТОЙ ЖЕ дорожки */
    draw(canvas({ blocks: [
      appt({ id: 1, col: 0, of: 4 }), appt({ id: 2, col: 1, of: 4, name: 'Ana Rusu' }),
      appt({ id: 3, col: 1, of: 2, room_id: 'r-2', room: 'Cabinet 2', name: 'Dan Lupu' }),
    ] }))
    /* доли ширины колонки: [левый край, ширина] — множители при `(100% - 8px)` */
    const box = (id: number) => {
      const s = (document.querySelector(`.gappt[data-appt="${id}"]`) as HTMLElement).style
      return [s.left, s.width].map((v) => Number(/([\d.]+) \* \(100% - 8px\)/.exec(v)?.[1]))
    }
    expect(box(1)).toEqual([0, 0.25])
    expect(box(2)).toEqual([0.25, 0.25])
    /* одна в своём кабинете — вся половина колонки */
    expect(box(3)).toEqual([0.5, 0.5])
  })

  it('заняты оба кабинета — ячейка выключена', () => {
    draw(canvas({ blocks: [appt({}), appt({ id: 2, col: 1, room_id: 'r-2', room: 'Cabinet 2' })] }))
    expect(cell(9).disabled).toBe(true)
    expect(cell(10).disabled).toBe(false)
  })
})
