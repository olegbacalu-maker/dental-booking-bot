import { createRef } from 'react'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CardDialog } from './CardDialog'
import { DashCanvas } from './DashCanvas'
import type { DashBlock, DashCanvasModel, DashColumn } from './dash'
import type { VisitCardView } from './day'
import { MoveDialog } from './MoveDialog'
import { CONTROL, type Occupies, type Room } from './move'

/* Полоса Control на экране: канва, окно переноса, окно визита. В полосу запись
   попадает только явным действием человека — щелчком по ней, выбором или кнопкой. */

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post: vi.fn() } }
})

const LANES: Room[] = [{ id: '', name: 'Principal' }, { id: CONTROL, name: 'Control', control: true }]

afterEach(() => { cleanup(); vi.restoreAllMocks(); get.mockReset() })

function appt(over: Partial<Extract<DashBlock, { kind: 'appt' }>>): Extract<DashBlock, { kind: 'appt' }> {
  return {
    kind: 'appt', id: 1, time: '09:00', min: 540, dur: 60, busy: true, movable: true,
    top: 0, height: 1, col: 0, of: 2, title: '', name: 'Ion Popa', service: 'Consultație', phone: '',
    status: 'confirmed', status_label: 'programată', urgent: false, source: 'manual',
    comment: '', comment_cut: '', age: null, doctor: 'Dr. Ion', pid: 17, rec: false, call: '',
    callable: true, clickable: true, service_id: 'consult', service_edit: true,
    room_id: '', room: '', bg: 'var(--green-soft)', bar: 'var(--green)',
    wait_since: null, ...over,
  }
}

function canvas(col: Partial<DashColumn>): DashCanvasModel {
  return {
    date: '2026-11-17', empty: false, base_min: 540, tight: false,
    hours: [{ h: 9, label: '09:00', now: false }, { h: 10, label: '10:00', now: false }],
    bands: { top: null, bottom: null },
    columns: [{
      key: 'k:d2', id: 'd2', name: 'Dr. Ion', orphan: false, spec: '', off: false, hue: 'var(--teal)',
      photo: '', initials: 'DI', room: '', rooms: LANES, phone: '', count: 1,
      free: '10:00', occupancy: null, title: '', cells: [true, true], blocks: [], relink: null, ...col,
    }],
  }
}

function draw(model: DashCanvasModel) {
  const onSlot = vi.fn()
  /* ячейка 300×60 в (0, 0): основная — левые 2/3, Control — правая треть */
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
    () => ({ left: 0, top: 0, width: 300, height: 60, right: 300, bottom: 60, x: 0, y: 0, toJSON: () => ({}) }))
  render(<DashCanvas model={model} rail={createRef<HTMLDivElement>()} waitTick={0} lineTick={0}
    onCard={() => {}} onSlot={onSlot} onNote={() => {}} drag={null} hover="" onDrag={() => {}}
    onHover={() => {}} onDrop={() => {}} fresh={new Set()} />)
  return onSlot
}
const cell = (h: number) => document.querySelector(`.gcell[data-h="${h}"]`) as HTMLButtonElement

describe('канва: полоса Control', () => {
  const two = [appt({}), appt({ id: 2, col: 1, room_id: CONTROL, room: 'Control', name: 'Ana Rusu', dur: 15 })]

  it('колонка размечена, в шапке подписи дорожек, у записи полосы — «C» и пунктир', () => {
    draw(canvas({ blocks: two }))
    expect(document.querySelector('.gcol')?.hasAttribute('data-ctl')).toBe(true)
    expect(Array.from(document.querySelectorAll('.dc-lanes span')).map((x) => x.textContent))
      .toEqual(['Principal', 'Control'])
    const ctl = Array.from(document.querySelectorAll('.gappt')).find((x) => x.textContent?.includes('Ana Rusu'))
    expect(ctl?.classList.contains('gctl')).toBe(true)
    expect(ctl?.querySelector('.gctl-tag')?.textContent).toBe('C')
    const main = Array.from(document.querySelectorAll('.gappt')).find((x) => x.textContent?.includes('Ion Popa'))
    expect(main?.classList.contains('gctl')).toBe(false)
  })

  it('щелчок по полосе — окно с Control; по основной занятой — основная, не Control', () => {
    const onSlot = draw(canvas({ blocks: [appt({})] }))
    fireEvent.click(cell(9), { clientX: 280, clientY: 30, detail: 1 })
    expect(onSlot).toHaveBeenLastCalledWith('d2', 'Dr. Ion', '09:00', 30, CONTROL)
    fireEvent.click(cell(9), { clientX: 60, clientY: 30, detail: 1 })
    expect(onSlot.mock.lastCall?.[4]).toBe('')
  })

  it('у врача без полосы разметки Control нет', () => {
    draw(canvas({ rooms: [], blocks: [appt({ of: 1 })] }))
    expect(document.querySelector('.gcol')?.hasAttribute('data-ctl')).toBe(false)
    expect(document.querySelector('.dc-lanes')).toBeNull()
  })
})

const b = (id: number, min: number, dur: number, room: string): Occupies => ({ id, min, dur, busy: true, room_id: room })

function move(taken: Occupies[], onMove = vi.fn()) {
  render(<MoveDialog open drag={{ id: 1, dk: 'd2', min: 540, dur: 15, nm: 'Ion Popa', room: '' }}
    target={{ dk: 'd2', min: 600 }} fromName="Dr. Ion" toName="Dr. Ion" taken={taken} rooms={LANES}
    hours={['09:00', '10:00']} busy={false} onClose={() => {}} onMove={onMove} />)
  return onMove
}
const btn = (text: string) => Array.from(document.querySelectorAll('dialog button'))
  .find((x) => x.textContent === text) as HTMLButtonElement | undefined

describe('окно переноса: основная занята — «Mută în Control»', () => {
  it('полоса свободна: кнопка шлёт перенос в Control', () => {
    const onMove = move([b(1, 540, 15, ''), b(2, 600, 60, '')])
    expect(btn('Da, mută')?.disabled).toBe(true)
    fireEvent.click(btn('Mută în Control')!)
    expect(onMove).toHaveBeenCalledWith(600, CONTROL)
  })

  it('полоса тоже занята — кнопки нет', () => {
    move([b(2, 600, 60, ''), b(3, 600, 30, CONTROL)])
    expect(btn('Mută în Control')).toBeUndefined()
  })

  it('основная свободна — кнопки нет, перенос обычный', () => {
    const onMove = move([])
    expect(btn('Mută în Control')).toBeUndefined()
    fireEvent.click(btn('Da, mută')!)
    expect(onMove).toHaveBeenCalledWith(600, undefined)
  })
})

const CARD: VisitCardView = {
  time: '09:00', name: 'Ion Popa', service: 'Consultație', doctor: 'Dr. Ion', phone: '', age: null,
  comment: '', status: 'confirmed', pid: 17, rec: false, call: '', callable: false,
  service_id: 'consult', service_edit: true, dur: 30, room_id: '', room: '',
}

describe('окно визита: «+ Control în paralel»', () => {
  it('кнопка есть только с `onControl` и зовёт его', () => {
    get.mockResolvedValue({ status: 200, data: { service_id: 'consult', options: [] } })
    const onControl = vi.fn()
    render(<CardDialog open id={5} card={CARD} actions={[]} back="/admin" busy={false}
      onClose={() => {}} onComment={async () => true} onStatus={async () => true} onControl={onControl} />)
    fireEvent.click(btn('+ Control în paralel')!)
    expect(onControl).toHaveBeenCalled()
    cleanup()
    render(<CardDialog open id={5} card={CARD} actions={[]} back="/admin" busy={false}
      onClose={() => {}} onComment={async () => true} onStatus={async () => true} />)
    expect(btn('+ Control în paralel')).toBeUndefined()
  })
})
