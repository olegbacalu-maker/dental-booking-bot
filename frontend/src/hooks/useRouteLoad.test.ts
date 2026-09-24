import type { LoaderFunctionArgs } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { ApiResult } from '../services/api'
import { ApiError } from '../types/api'
import { routeLoader } from './useRouteLoad'

vi.mock('../services/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('../services/api')>()
  return { ...real, loginUrl: () => '/admin/login?next=%2Fadmin%2Fsettings' }
})

const args = () => ({ request: new Request('http://x/admin/settings'), params: {} }) as unknown as LoaderFunctionArgs
const ok = <T,>(data: T): ApiResult<T> => ({ data, code: '', text: '', tone: 'ok' })

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

  it('401 — уходим на вход, экран не рисует ни кадра', async () => {
    const navigate = vi.fn()
    const r = await routeLoader(
      vi.fn().mockRejectedValue(new ApiError({ kind: 'unauthenticated' }, 'u')), navigate)(args())
    expect(r).toEqual({ status: 'leaving' })
    expect(navigate).toHaveBeenCalledWith('/admin/login?next=%2Fadmin%2Fsettings')
  })
})
