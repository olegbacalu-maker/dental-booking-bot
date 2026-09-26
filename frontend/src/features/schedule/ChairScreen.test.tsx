import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../../services/api'
import { openScreen } from '../../test/openScreen'
import type { ChairData, ChairItem } from './chair'
import { ChairScreen, loadChair, POLL_MS } from './ChairScreen'

/* Подмена слоя сети — ТОЛЬКО в этих проверках (§26). */
const { get, post, postForm } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), postForm: vi.fn() }))
vi.mock('../../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../services/api')>()
  return { ...real, api: { get, post, postForm }, loginUrl: () => '/admin/login?next=x' }
})
/* Рабочий стол одонтограммы — свой набор у B6/B7; здесь проверяется только,
   ЧЕЙ стол экран кресла встраивает. */
vi.mock('../clinical/OdontogramTab', () => ({
  OdontogramTab: ({ pid }: { pid: number }) => <div>odontograma {pid}</div>,
}))

const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })

const item = (id: number, name: string, status: string, time: string, pid: number | null = id + 100): ChairItem => ({
  id, time, dur: 60, name, service: 'Consultație', status,
  badge: { cls: status, label: status }, urgent: false, bar: '', state: null,
  clickable: true, patient_id: pid, wait_since: null,
})

const ACTIONS = {
  confirmed: [{ to: 'waiting', cls: 'b-waiting', label: 'A venit', confirm: '' },
    { to: 'arrived', cls: 'b-arrived', label: 'În cabinet', confirm: '' }],
  waiting: [{ to: 'arrived', cls: 'b-arrived', label: 'În cabinet', confirm: '' },
    { to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' }],
  arrived: [{ to: 'done', cls: 'b-done', label: 'Finalizat', confirm: '' },
    { to: 'cancelled', cls: 'b-cancel', label: 'Anulează', confirm: '' }],
}
const DOCS = [{ dk: 'd2', name: 'Dr. Doi' }, { dk: 'd3', name: 'Dr. Trei' }]
const base = (over: Partial<ChairData>): ChairData => ({
  date: '2026-09-28', today: true, doctors: DOCS, doctor: DOCS[0] ?? null,
  chair: null, stale: [], queue: [], actions: ACTIONS, ...over,
})

const open = () => openScreen('/admin/cabinet', '/admin/cabinet?doctor=d2',
  <ChairScreen />, loadChair)

afterEach(() => {
  cleanup()
  get.mockReset()
  post.mockReset()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('ChairScreen', () => {
  it('врач не выбран: список врачей ссылками на их кресло', async () => {
    get.mockResolvedValueOnce(ok(base({ doctor: null })))
    open()
    const link = await screen.findByRole('link', { name: /Dr\. Trei/ })
    expect(link.getAttribute('href')).toBe('/admin/cabinet?doctor=d3')
    expect(get).toHaveBeenCalledWith('/chair?doctor=d2', expect.anything())
  })

  it('в кресле: имя, его одонтограмма, «Finalizat» без «Anulează»; «не завершён» с Finalizat', async () => {
    get.mockResolvedValueOnce(ok(base({
      chair: item(2, 'Ana Unu', 'arrived', '09:00'),
      stale: [item(1, 'Cezar Trei', 'arrived', '08:00')],
      queue: [item(3, 'Bogdan Doi', 'waiting', '10:00')],
    })))
    open()
    expect(await screen.findByText('Ana Unu')).toBeTruthy()
    expect(screen.getByText('odontograma 102')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Fișa pacientului/ }).getAttribute('href')).toBe('/admin/patient/102')
    expect(screen.getByRole('link', { name: /Fișa vizitei/ }).getAttribute('href')).toBe('/admin/visit/2')
    expect(screen.getAllByRole('button', { name: 'Finalizat' })).toHaveLength(2)   // кресло + «не завершён»
    // отмена визита у кресла не предлагается — это дело регистратуры
    expect(screen.queryByRole('button', { name: 'Anulează' })).toBeNull()
    expect(screen.getByText(/Nefinalizat/)).toBeTruthy()
    // в очереди — только «În cabinet»: остальное делает регистратура
    expect(screen.getByRole('button', { name: 'În cabinet' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'A venit' })).toBeNull()
  })

  it('пусто в кресле: подсказка и очередь', async () => {
    get.mockResolvedValueOnce(ok(base({ queue: [item(3, 'Bogdan Doi', 'confirmed', '10:00')] })))
    open()
    expect(await screen.findByText(/Nimeni în cabinet/)).toBeTruthy()
    expect(screen.queryByText(/odontograma/)).toBeNull()
  })

  it('«În cabinet» из очереди: POST исхода, затем кресло перечитано', async () => {
    get.mockResolvedValueOnce(ok(base({ queue: [item(3, 'Bogdan Doi', 'waiting', '10:00')] })))
    open()
    fireEvent.click(await screen.findByRole('button', { name: 'În cabinet' }))
    post.mockResolvedValueOnce(ok({}))
    get.mockResolvedValueOnce(ok(base({ chair: item(3, 'Bogdan Doi', 'arrived', '10:00') })))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/schedule/appointments/3/status', { to: 'arrived' }))
    expect(await screen.findByText('odontograma 103')).toBeTruthy()
  })

  it('опрос: регистратура завела пациента — планшет видит без перезагрузки', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    get.mockResolvedValueOnce(ok(base({ queue: [item(3, 'Bogdan Doi', 'waiting', '10:00')] })))
    open()
    await screen.findByText(/Nimeni în cabinet/)
    get.mockResolvedValueOnce(ok(base({ chair: item(3, 'Bogdan Doi', 'arrived', '10:00') })))
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS + 10) })
    expect(await screen.findByText('odontograma 103')).toBeTruthy()
    expect(get).toHaveBeenLastCalledWith('/chair?doctor=d2', {})
  })
})
