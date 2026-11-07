import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FlowList, type FlowLabels } from './FlowTabs'
import type { FlowRow } from './flow'
import type { DashAgendaItem } from './dash'
import { allowMotion } from '../../test/motion'

/* Смыкание строк вкладки потока (07.11, вторая волна): ушедшая строка оставляет
   призрака на ступень, остальные остаются настоящими строками. Без движения
   призрака нет — список как был. */

const item = (id: number, name: string): DashAgendaItem => ({
  id, time: '09:00', dur: 60, name, service: 'Consultație', status: 'waiting',
  badge: { cls: 'wait', label: 'A venit' }, urgent: false, bar: 'var(--green)', state: 'past',
  clickable: true, patient_id: id, wait_since: null, comment: '', doctor: 'Dr. Ion', doctor_id: 'd2',
  phone: '', start_ms: 0, end_ms: 0, end: '10:00', in_at: '',
})
const row = (id: number, name: string): FlowRow => ({ it: item(id, name), min: 3, long: false, left: 0, busy: null, next: null })
const labels: FlowLabels = { waiting: 'A venit', arrived: 'În cabinet', done: 'Finalizat' }
const list = (rows: FlowRow[]) => (
  <FlowList kind="waiting" rows={rows} labels={labels} busy={false} onCard={() => undefined} onFlow={() => undefined} />
)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('FlowList: уход строки', () => {
  it('без движения ушедшая строка исчезает сразу, призрака нет', () => {
    const { rerender } = render(list([row(1, 'Ana'), row(2, 'Ion')]))
    rerender(list([row(2, 'Ion')]))
    expect(document.querySelectorAll('.fl-row').length).toBe(1)
    expect(document.querySelector('.fl-row.leaving')).toBeNull()
  })

  it('с движением — призрак ушедшей на ступень, не нажимаемый и вне списка узлов', () => {
    allowMotion()
    vi.useFakeTimers()
    const { rerender } = render(list([row(1, 'Ana'), row(2, 'Ion')]))
    rerender(list([row(2, 'Ion')]))
    const ghost = document.querySelector('.fl-row.leaving') as HTMLElement
    expect(ghost).toBeTruthy()
    expect(ghost.dataset.gone).toBe('1')
    expect(ghost.getAttribute('data-appt')).toBeNull()
    expect(ghost.getAttribute('aria-hidden')).toBe('true')
    expect(document.querySelectorAll('.fl-row[data-appt]').length).toBe(1)
    act(() => { vi.advanceTimersByTime(300) })
    expect(document.querySelector('.fl-row.leaving')).toBeNull()
  })

  it('⛔ тот же состав новым массивом (тик минут) призрака не рождает и не снимает', () => {
    allowMotion()
    vi.useFakeTimers()
    const { rerender } = render(list([row(1, 'Ana'), row(2, 'Ion')]))
    rerender(list([row(2, 'Ion')]))
    rerender(list([row(2, 'Ion')]))
    expect(document.querySelector('.fl-row.leaving')).toBeTruthy()
    rerender(list([row(1, 'Ana'), row(2, 'Ion')]))
    rerender(list([row(1, 'Ana'), row(2, 'Ion')]))
    expect(document.querySelectorAll('.fl-row.leaving').length).toBe(1)
  })

  it('последняя строка уходит — подсказка пустой вкладки стоит рядом с призраком', () => {
    allowMotion()
    vi.useFakeTimers()
    const { rerender } = render(list([row(1, 'Ana')]))
    rerender(list([]))
    expect(document.querySelector('.fl-row.leaving')).toBeTruthy()
    expect(document.querySelector('.fl-empty')?.textContent).toBe('Nimeni nu așteaptă')
    act(() => { vi.advanceTimersByTime(300) })
    expect(document.querySelector('.fl-list')).toBeNull()
    expect(document.querySelector('.fl-empty')).toBeTruthy()
  })
})
