import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { WeekScreen } from './WeekScreen'
import type { WeekModel } from './week'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post }, loginUrl: () => '/admin/login?next=x' }
})

/* ⛔ Суббота ЕСТЬ (в ней запись), воскресенья НЕТ (пустой выходной скрыт).
   Ровно тот случай, на котором раскладка по weekday() ставит субботу под
   воскресенье и выглядит правдоподобно. */
const MODEL: WeekModel = {
  monday: '2026-09-21',
  sunday: '2026-09-27',
  prev: '2026-09-14',
  next: '2026-09-28',
  span: '21.09 – 27.09.2026',
  total: 3,
  day: '2026-09-22',
  days: [
    { date: '2026-09-21', dm: '21.09', label: 'Lu', count: 0, today: false, open: true, items: [] },
    {
      date: '2026-09-22', dm: '22.09', label: 'Ma', count: 2, today: true, open: true,
      items: [
        { kind: 'appt', id: 1, time: '09:00', name: 'Ion Popa', service: 'Consultație', noshow: false, bg: 'var(--green-soft)', bar: 'var(--green)' },
        { kind: 'appt', id: 2, time: '10:30', name: 'Maria Rusu', service: 'Durere acută', noshow: true, bg: 'var(--red-soft)', bar: 'var(--red)' },
        { kind: 'note', time: '12:00', text: 'Livrare materiale' },
      ],
    },
    { date: '2026-09-23', dm: '23.09', label: 'Mi', count: 0, today: false, open: true, items: [] },
    { date: '2026-09-24', dm: '24.09', label: 'Jo', count: 0, today: false, open: true, items: [] },
    { date: '2026-09-25', dm: '25.09', label: 'Vi', count: 0, today: false, open: true, items: [] },
    {
      date: '2026-09-26', dm: '26.09', label: 'Sâ', count: 1, today: false, open: false,
      items: [{ kind: 'appt', id: 3, time: '11:00', name: 'Vasile Lupu', service: 'Igienizare', noshow: false, bg: 'var(--blue-soft)', bar: 'var(--blue)' }],
    },
  ],
}

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })
const cols = () => Array.from(document.querySelectorAll('.wcol'))
const head = (i: number) => cols()[i]?.querySelector('.wh a')?.textContent ?? ''

beforeEach(() => { get.mockResolvedValue(ok(MODEL)) })
afterEach(() => { cleanup(); get.mockReset(); post.mockReset() })

const show = async (date = '') => {
  render(<WeekScreen date={date} navigate={() => {}} />)
  await waitFor(() => expect(cols().length).toBeGreaterThan(0))
}

describe('недельный календарь', () => {
  it('рисует ровно те дни, что прислал сервер, и в его порядке', async () => {
    await show()
    expect(cols().map((c) => c.querySelector('.wh a')?.getAttribute('href')))
      .toEqual(MODEL.days.map((d) => `/admin?date=${d.date}`))
  })

  it('скрытое воскресенье не сдвигает субботу', async () => {
    await show()
    expect(cols()).toHaveLength(6)
    expect(head(5)).toBe('Sâ 26.09')          // а не «Du»
    // 27.09 встречается в диапазоне шапки, поэтому ищем именно КОЛОНКУ
    expect(cols().some((c) => c.textContent?.includes('27.09'))).toBe(false)
  })

  it('счётчик дня и итог недели — числа сервера', async () => {
    await show()
    expect(cols()[1]?.querySelector('.wh small')?.textContent).toBe('2 programări')
    expect(screen.getByText(/21\.09 – 27\.09\.2026 · 3 programări/)).toBeTruthy()
  })

  it('чип записи несёт час, имя и услугу, заметка — своим видом', async () => {
    await show()
    const chips = cols()[1]?.querySelectorAll('.wchip') ?? []
    expect(chips).toHaveLength(3)
    expect(chips[0]?.textContent).toContain('09:00')
    expect(chips[0]?.textContent).toContain('Ion Popa')
    expect(chips[0]?.textContent).toContain('Consultație')
    expect(chips[2]?.className).toContain('gnote')
    expect(chips[2]?.textContent).toContain('Livrare materiale')
    expect(chips[2]?.textContent).not.toContain('Ion Popa')
  })

  it('неявка помечена классом, а цвет берётся строкой сервера', async () => {
    await show()
    const chips = cols()[1]?.querySelectorAll('.wchip') ?? []
    expect(chips[1]?.className).toContain('noshow')
    expect((chips[1] as HTMLElement).style.background).toContain('var(--red-soft)')
    expect((chips[0] as HTMLElement).style.background).toContain('var(--green-soft)')
  })

  it('пустой день говорит «— liber —», сегодня отмечен ровно один', async () => {
    await show()
    expect(cols()[0]?.textContent).toContain('— liber —')
    expect(document.querySelectorAll('.wh.tdy')).toHaveLength(1)
  })

  it('соседняя неделя запрашивается у сервера, а не считается на клиенте', async () => {
    await show()
    fireEvent.click(screen.getAllByText(/săpt\./)[0] as HTMLElement)
    await waitFor(() => expect(get).toHaveBeenCalledWith('/schedule/week?date=2026-09-14', expect.anything()))
  })

  it('«Azi» просит неделю без даты', async () => {
    await show('2026-09-21')
    fireEvent.click(screen.getByText('Azi'))
    await waitFor(() => expect(get).toHaveBeenCalledWith('/schedule/week', expect.anything()))
  })
})
