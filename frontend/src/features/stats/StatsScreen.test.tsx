import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { ApiError } from '../../types/api'
import type { StatsData } from './stats'
import { StatsScreen } from './StatsScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})

const WEEK: StatsData = {
  period: { from: '2026-09-15', to: '2026-09-21', label: '15.09.2026 — 21.09.2026',
            short: '15.09–21.09', days: 7 },
  presets: [
    { key: 'azi', label: 'Azi', from: '2026-09-21', to: '2026-09-21' },
    { key: 'd7', label: '7 zile', from: '2026-09-15', to: '2026-09-21' },
  ],
  compare: 'față de săptămâna trecută',
  export_url: '/admin/export.xlsx?from=2026-09-15&to=2026-09-21',
  tiles: [
    { key: 'total', label: 'Programări', value: 24, icon: 'cal', tone: 'var(--green)',
      soft: 'var(--green-soft)', bad: false, series: [2, 4, 6, 3, 5, 2, 2],
      trend: { dir: 'up', icon: 'caret-u', value: '12%',
               label: 'față de săptămâna trecută', note: '' } },
    { key: 'cancel', label: 'Anulate', value: 3, icon: 'ban', tone: 'var(--red)',
      soft: 'var(--red-soft)', bad: true, series: [1, 0, 1, 0, 1, 0, 0],
      trend: { dir: 'dn', icon: 'caret-u', value: '50%',
               label: 'față de săptămâna trecută', note: '' } },
  ],
  chart: {
    labels: ['15.09', '16.09'], values: [2, 4],
    title: 'Programări pe zile', sub: '· 15.09 — 21.09.2026', total: 24,
    total_trend: { dir: '', icon: '', value: '', label: 'față de săptămâna trecută', note: '' },
    present_pct: 83, noshow: 2, loss: 'cca 1 000 MDL pierdut',
    wait: { text: '7 min', sub: '3 vizite măsurate' },
  },
  sources: { show: false, total: 24, parts: [] },
  occupancy: { pct: 61, note: 'media 15.09–21.09 (7 zile)' },
  money: [
    { key: 'incasari', title: 'Încasări', sub: '· bani reali, 15.09–21.09',
      value: 4200, text: '4 200 MDL', suffix: ' MDL',
      trend: { dir: 'up', icon: 'caret-u', value: '+1 200 MDL',
               label: 'față de săptămâna trecută', note: '' },
      note: [{ icon: 'cash', t: '2 000 MDL' }, { icon: 'card', t: '2 200 MDL' }],
      link: { href: '/admin/casa', label: 'Raport de casă (azi) ›', icon: 'print' } },
  ],
  doctors: [{ name: 'Dr. Ana', off: false, n: 12, came: 10, pres: 83, pct: 61 }],
  services: [{ label: 'Consultație', cnt: 5, val: 'cca 1 500 MDL', pct: 100 }],
  activity: [{ text: 'Fișă actualizată', name: 'Ion P', patient_id: 7,
               who: 'Ana', at: '21.09 10:20' }],
  hint: 'Prețurile sunt medii orientative din lista clinicii.',
}

const ok = <T,>(data: T, code = '', text = ''): ApiResult<T> => ({ data, code, text, tone: 'ok' })

afterEach(() => {
  cleanup()
  get.mockReset()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', '/admin/stats')
})

describe('StatsScreen', () => {
  it('период, плитки, врачи, услуги и лента — всё из одного конверта', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    render(<StatsScreen navigate={vi.fn()} />)
    expect(await screen.findByText('15.09.2026 — 21.09.2026')).toBeTruthy()
    expect(screen.getByText('Programări pe zile')).toBeTruthy()
    expect(screen.getByText('Dr. Ana')).toBeTruthy()
    expect(screen.getByText('Consultație')).toBeTruthy()
    expect(screen.getByText('Fișă actualizată')).toBeTruthy()
    /* Ссылка на фишу пациента из ленты — как на старой странице. */
    expect(screen.getByRole('link', { name: 'Ion P' }).getAttribute('href'))
      .toBe('/admin/patient/7')
  })

  it('деньги показываются СТРОКОЙ СЕРВЕРА и с суффиксом валюты', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    render(<StatsScreen navigate={vi.fn()} />)
    /* ⛔ `data-count` равен значению ВСЕГДА: анимация — представление, а не
       источник правды (у легаси это контракт, проверки читают атрибут). */
    const b = await screen.findByText('4 200 MDL')
    expect(b.getAttribute('data-count')).toBe('4200')
    /* ⚠️ Разделитель тысяч у счётчика свой (текст переписывается на каждом
       кадре), и он обязан СОВПАДАТЬ со строкой сервера — иначе цифра меняет
       вид в момент, когда анимация кончилась. */
    expect(b.textContent).toBe(WEEK.money[0]!.text)
    expect(screen.getByRole('link', { name: /Raport de casă/ }).getAttribute('href'))
      .toBe('/admin/casa')
  })

  it('рост плохого — стрелка вверх, но цвет КРАСНЫЙ: тон берётся у сервера', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    render(<StatsScreen navigate={vi.fn()} />)
    await screen.findByText('Anulate')
    /* Отмены выросли на 50%: направление `dn` (плохо) при стрелке вверх.
       Вычисли класс из знака числа — и рост неявок позеленел бы. */
    const bad = screen.getByText('50%').closest('span')
    expect(bad?.className).toBe('dn')
  })

  it('«неизменно» — это СЛОВО, а не нулевой процент', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    render(<StatsScreen navigate={vi.fn()} />)
    expect(await screen.findByText(/neschimbat față de săptămâna trecută/)).toBeTruthy()
  })

  it('один источник — кольца нет вовсе: это тавтология, а не разбивка', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    render(<StatsScreen navigate={vi.fn()} />)
    await screen.findByText('Programări pe zile')
    expect(screen.queryByText('Surse programări')).toBeNull()
  })

  it('готовый период меняет отбор и АДРЕС — закладка открывает тот же', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    get.mockResolvedValueOnce(ok({
      ...WEEK,
      period: { from: '2026-09-21', to: '2026-09-21', label: '21.09.2026 — 21.09.2026',
                short: '21.09–21.09', days: 1 },
    }))
    render(<StatsScreen navigate={vi.fn()} />)
    await screen.findByText('15.09.2026 — 21.09.2026')
    fireEvent.click(screen.getByRole('link', { name: 'Azi' }))
    expect(await screen.findByText('21.09.2026 — 21.09.2026')).toBeTruthy()
    expect(get).toHaveBeenLastCalledWith('/stats?from=2026-09-21&to=2026-09-21',
      expect.anything())
    expect(window.location.search).toBe('?from=2026-09-21&to=2026-09-21')
  })

  it('негодный период — отказ сервера, а НЕ молча другой период', async () => {
    get.mockResolvedValueOnce(ok(WEEK))
    get.mockRejectedValueOnce(new ApiError(
      { kind: 'validation', code: 'bad_period', text: 'Perioada aleasă nu este validă' },
      'bad_period'))
    render(<StatsScreen navigate={vi.fn()} />)
    const inputs = await screen.findAllByDisplayValue(/2026-09/)
    fireEvent.change(inputs[0]!, { target: { value: '0012-09-15' } })
    fireEvent.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('Perioada aleasă nu este validă')).toBeTruthy()
    /* Цифры остались теми, что человек набрал: экран не подменил их своими. */
    await waitFor(() => expect(screen.getByDisplayValue('0012-09-15')).toBeTruthy())
  })
})
