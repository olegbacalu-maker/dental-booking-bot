import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider, type LoaderFunctionArgs } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../services/api'
import { ApiError } from '../types/api'
import { NO_ACCESS_URL, queryParam, routeLoader, screenRoute, useRouteLoad } from './useRouteLoad'

vi.mock('../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../services/api')>()
  return { ...real, loginUrl: () => '/admin/login?next=%2Fx' }
})

const args = () => ({ request: new Request('http://x/admin/settings'), params: {} }) as unknown as LoaderFunctionArgs
const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })

afterEach(() => cleanup())

describe('routeLoader', () => {
  it('ответ — данные экрана, и запрос получает сигнал отмены роутера', async () => {
    const load = vi.fn().mockResolvedValue(ok({ n: 1 }))
    expect(await routeLoader(load, vi.fn())(args())).toEqual({ status: 'ready', data: { n: 1 } })
    expect(load.mock.calls[0]?.[0]).toBeInstanceOf(AbortSignal)
  })

  it('отказ сервера НЕ бросается: экран сам покажет плашку с повтором', async () => {
    const err = new ApiError({ kind: 'network', detail: 'x' }, 'x')
    const r = await routeLoader(vi.fn().mockRejectedValue(err), vi.fn())(args())
    expect(r).toEqual({ status: 'failed', error: err })
  })

  it('B3: отказ в праве уводит туда же, куда страница сервера — на любом маршруте', async () => {
    const navigate = vi.fn()
    const denied = new ApiError({ kind: 'forbidden', code: 'no_access', text: 'Nu aveți acces' }, 'f')
    const r = await routeLoader(vi.fn().mockRejectedValue(denied), navigate)(args())
    expect(r).toEqual({ status: 'leaving' })
    expect(navigate).toHaveBeenCalledWith(NO_ACCESS_URL)
    expect(NO_ACCESS_URL).toBe('/admin?msg=no_access')   // core/auth.require
  })

  it('B3: чужой 403 (не отказ в праве) не уводит никогда — плашка экрана', async () => {
    const navigate = vi.fn()
    const origin = new ApiError({ kind: 'forbidden', code: 'bad_origin', text: 'x' }, 'o')
    expect(await routeLoader(vi.fn().mockRejectedValue(origin), navigate)(args()))
      .toEqual({ status: 'failed', error: origin })
    expect(navigate).not.toHaveBeenCalled()
  })

  it('401 — уходим на вход, экран не рисует ни кадра', async () => {
    const navigate = vi.fn()
    const r = await routeLoader(
      vi.fn().mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u')), navigate)(args())
    expect(r).toEqual({ status: 'leaving' })
    expect(navigate).toHaveBeenCalledWith('/admin/login?next=%2Fx')
  })
})

/* Экран-зонд: показывает состояние и зовёт всё, что хук отдаёт. */
function Probe({ nav }: { nav: (u: string) => void }) {
  const { state, retry, replace, leaveIfSignedOut } = useRouteLoad<{ n: number }>(nav)
  return (
    <section>
      <p data-testid="s">{state.status === 'ready' ? `ready:${state.data.n}` : state.status}</p>
      <button type="button" onClick={() => replace({ n: 99 })}>replace</button>
      <button type="button" onClick={retry}>retry</button>
      <button type="button" onClick={() => leaveIfSignedOut(new ApiError({ kind: 'unauthenticated' }, 'u'))}>
        leave
      </button>
    </section>
  )
}

type Load = (id: string | undefined, signal: AbortSignal) => Promise<ApiResult<{ n: number }>>

function mount(load: Load, nav = vi.fn()) {
  const router = createMemoryRouter(
    [screenRoute('/x/:id', <Probe nav={nav} />, (signal, params) => load(params.id, signal))],
    { initialEntries: ['/x/1'] })
  render(<RouterProvider router={router} />)
  return { router, nav }
}

const s = () => screen.getByTestId('s').textContent

describe('useRouteLoad', () => {
  it('первый кадр — тот же экран в загрузке, потом данные загрузчика', async () => {
    mount(vi.fn().mockResolvedValue(ok({ n: 1 })))
    expect(s()).toBe('loading')
    expect(await screen.findByText('ready:1')).toBeTruthy()
  })

  it('replace подменяет ответом POST, а повтор снова берёт ответ загрузчика', async () => {
    const load = vi.fn().mockResolvedValueOnce(ok({ n: 1 })).mockResolvedValueOnce(ok({ n: 2 }))
    mount(load)
    await screen.findByText('ready:1')
    fireEvent.click(screen.getByText('replace'))
    expect(s()).toBe('ready:99')
    fireEvent.click(screen.getByText('retry'))
    expect(s()).toBe('loading')
    expect(await screen.findByText('ready:2')).toBeTruthy()
  })

  it('подмена не переживает НОВЫЙ ответ загрузчика: другой адрес — его данные, а не прежние', async () => {
    const load = vi.fn((id: string | undefined) => Promise.resolve(ok({ n: Number(id) })))
    const { router } = mount(load)
    await screen.findByText('ready:1')
    fireEvent.click(screen.getByText('replace'))
    expect(s()).toBe('ready:99')
    await act(() => router.navigate('/x/2'))
    expect(s()).toBe('ready:2')
  })

  it('401 при действии — уходим на вход, экран в «уходим»', async () => {
    const { nav } = mount(vi.fn().mockResolvedValue(ok({ n: 1 })))
    await screen.findByText('ready:1')
    fireEvent.click(screen.getByText('leave'))
    expect(nav).toHaveBeenCalledWith('/admin/login?next=%2Fx')
    expect(s()).toBe('leaving')
  })
})

describe('адрес после перехода (B2.3)', () => {
  function Pending() {
    const { state, pending } = useRouteLoad<{ n: number }>(vi.fn())
    return <p data-testid="s">{pending ? 'pending' : state.status === 'ready' ? `ready:${state.data.n}` : state.status}</p>
  }

  it('загрузчик видит query ТЕКУЩЕГО адреса, а не документа', async () => {
    const load = vi.fn((_s: AbortSignal, _p: unknown, q: URLSearchParams) =>
      Promise.resolve(ok({ n: Number(q.get('d')) })))
    const router = createMemoryRouter([screenRoute('/x', <Pending />, load)], { initialEntries: ['/x?d=5'] })
    render(<RouterProvider router={router} />)
    expect(await screen.findByText('ready:5')).toBeTruthy()
    await act(() => router.navigate('/x?d=6', { replace: true }))
    expect(s()).toBe('ready:6')
    expect(load).toHaveBeenLastCalledWith(expect.any(AbortSignal), expect.anything(), expect.any(URLSearchParams))
  })

  it('пока переход ждёт ответа, экран знает об этом (pending)', async () => {
    let release: (v: ApiResult<{ n: number }>) => void = () => {}
    const load = vi.fn()
      .mockResolvedValueOnce(ok({ n: 1 }))
      .mockReturnValueOnce(new Promise((r) => { release = r }))
    const router = createMemoryRouter([screenRoute('/x', <Pending />, load)], { initialEntries: ['/x?d=1'] })
    render(<RouterProvider router={router} />)
    await screen.findByText('ready:1')
    act(() => { void router.navigate('/x?d=2', { replace: true }) })
    expect(await screen.findByText('pending')).toBeTruthy()
    await act(async () => { release(ok({ n: 2 })) })
    expect(await screen.findByText('ready:2')).toBeTruthy()
  })

  it('своё правило перезапуска доходит до маршрута: смена query без перезагрузки', async () => {
    const load = vi.fn().mockResolvedValue(ok({ n: 1 }))
    const router = createMemoryRouter(
      [screenRoute('/x', <Pending />, { load, shouldRevalidate: () => false })],
      { initialEntries: ['/x'] })
    render(<RouterProvider router={router} />)
    await screen.findByText('ready:1')
    await act(() => router.navigate('/x?views=1', { replace: true }))
    expect(load).toHaveBeenCalledTimes(1)
    expect(router.state.location.search).toBe('?views=1')
  })
})

describe('queryParam', () => {
  it('повтор параметра читается как у сервера — побеждает последнее', () => {
    const q = new URLSearchParams('date=2026-09-01&date=2026-09-02&f=')
    expect(queryParam(q, 'date')).toBe('2026-09-02')
    expect(queryParam(q, 'f')).toBe('')
    expect(queryParam(q, 'nope')).toBe('')
  })
})
