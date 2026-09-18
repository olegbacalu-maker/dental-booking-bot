import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { DayScreen } from './DayScreen'
import type { DayModel } from './day'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

const appt = (id: number, time: string, name: string, extra = {}) => ({
  kind: 'appt' as const, id, time, name, service: 'Consultație',
  phone: '069000000', status: 'confirmed', status_label: 'Confirmat',
  urgent: false, source: 'panel', dur: 60, comment: '', age: null,
  clickable: true, bg: 'var(--green-soft)', bar: 'var(--green)',
  min: 600, busy: true, movable: true, ...extra,
})

/* ⛔ Две колонки, и вторая пустая в 09:00: если ячейки раскладывать не по
   позиции в списке врачей, запись переедет к соседу — и это выглядит нормально. */
const MODEL: DayModel = {
  date: '2026-09-23',
  doctors: [
    { id: 'd2', name: 'Dr. Activ Doi', spec: 'Terapeut' },
    { id: 'd3', name: 'Dr. Activ Trei', spec: 'Ortodont · inactiv' },
  ],
  hours: [
    {
      h: 9, label: '09:00', closed: '', now: false, cells: [
        { kind: 'appts', drop: true, items: [appt(1, '09:00', 'Ion Popa')] },
        { kind: 'free', drop: true, items: [] },
      ],
    },
    {
      h: 10, label: '10:00', closed: '', now: true, cells: [
        { kind: 'busy', drop: true, items: [] },
        {
          kind: 'appts', drop: true, items: [appt(2, '10:00', 'Maria Rusu', {
            status: 'noshow', status_label: 'Nu s-a prezentat', urgent: true,
            service: 'Durere acută', age: 36, comment: 'sună înainte',
            bg: 'var(--red-soft)', bar: 'var(--red)',
          })],
        },
      ],
    },
    {
      h: 13, label: '13:00', closed: 'pauza', now: false, cells: [
        { kind: 'off', drop: false, items: [] },
        { kind: 'off', drop: false, items: [] },
      ],
    },
    {
      h: 19, label: '19:00', closed: 'inchis', now: false, cells: [
        { kind: 'appts', drop: false, items: [{ kind: 'note', id: 9, time: '19:00', text: 'Livrare', min: 1140, dur: 60, busy: false, movable: false }] },
        { kind: 'off', drop: false, items: [] },
      ],
    },
  ],
}

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })
const rows = () => Array.from(document.querySelectorAll('tr.hrow'))
const cellsOf = (i: number) => Array.from(rows()[i]?.querySelectorAll('td') ?? []).slice(1)

beforeEach(() => { get.mockResolvedValue(ok(MODEL)) })
afterEach(() => { cleanup(); get.mockReset(); post.mockReset() })

const show = async (props: { date?: string; doctor?: string } = {}) => {
  render(<DayScreen date={props.date ?? ''} doctor={props.doctor ?? ''} navigate={() => {}} />)
  await waitFor(() => expect(rows().length).toBeGreaterThan(0))
}

describe('день журнала', () => {
  it('колонки — врачи сервера, с подписями и ссылкой в их день', async () => {
    await show()
    const heads = Array.from(document.querySelectorAll('.dh-n'))
    expect(heads.map((h) => h.textContent)).toEqual(['Dr. Activ Doi', 'Dr. Activ Trei'])
    expect(heads[0]?.getAttribute('href')).toBe('/admin/doctor/d2?date=2026-09-23')
    expect(document.querySelectorAll('.dh-s')[1]?.textContent).toContain('inactiv')
  })

  it('запись стоит в колонке своего врача, у соседа в этот час «+»', async () => {
    await show()
    const c = cellsOf(0)
    expect(c[0]?.querySelector('[data-appt="1"]')).toBeTruthy()
    expect(c[1]?.querySelector('.free')).toBeTruthy()
  })

  it('закрытый час называет себя, и ячейки в нём пустые', async () => {
    await show()
    expect(rows()[2]?.querySelector('.hour')?.textContent).toContain('pauză')
    expect(rows()[3]?.querySelector('.hour')?.textContent).toContain('închis')
    expect(cellsOf(2).every((td) => td.className === 'goff')).toBe(true)
  })

  it('час под длинным визитом говорит «занято», а не «+»', async () => {
    await show()
    const c = cellsOf(1)
    expect(c[0]?.textContent).toContain('ocupat')
    expect(c[0]?.querySelector('.free')).toBeNull()
  })

  it('текущий час подсвечен ровно один раз', async () => {
    await show()
    expect(document.querySelectorAll('tr.hrow.now')).toHaveLength(1)
    expect(rows()[1]?.className).toContain('now')
  })

  it('карточка несёт слово статуса сервера, срочность, возраст и комментарий', async () => {
    await show()
    const card = cellsOf(1)[1]?.querySelector('[data-appt="2"]')
    expect(card?.className).toContain('noshow')
    expect(card?.className).toContain('urgent')
    expect(card?.textContent).toContain('Nu s-a prezentat')   // а не «noshow»
    expect(card?.textContent).toContain('36 a.')
    expect(card?.textContent).toContain('sună înainte')
    expect(card?.textContent).toContain('(60′)')
  })

  it('заметка стойки — своим видом и без телефона', async () => {
    await show()
    const note = cellsOf(3)[0]?.querySelector('[data-appt="9"]')
    expect(note?.className).toContain('note')
    expect(note?.textContent).toContain('Livrare')
    expect(note?.textContent).not.toContain('069000000')
  })

  it('соседний день запрашивается у сервера', async () => {
    await show({ date: '2026-09-23' })
    fireEvent.click(document.querySelectorAll('.nav a')[0] as HTMLElement)
    await waitFor(() => expect(get).toHaveBeenCalledWith(
      '/schedule/day?date=2026-09-22', expect.anything()))
  })

  it('день врача просит только его записи', async () => {
    await show({ doctor: 'd2' })
    expect(get).toHaveBeenCalledWith('/schedule/day?doctor=d2', expect.anything())
  })
})
