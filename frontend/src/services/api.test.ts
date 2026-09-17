import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../types/api'
import { api, loginUrl } from './api'

/* Ответы движка, какими их строит core/layout.msg_json. Это фикстуры ТОЛЬКО
   этих проверок (§26): бандл их не видит. */
function reply(status: number, body: unknown, type = 'application/json'): Response {
  const text = typeof body === 'string' ? body : JSON.stringify(body)
  return new Response(text, { status, headers: { 'content-type': type } })
}

function envelope(ok: boolean, code = '', extra: Record<string, unknown> = {}) {
  return { ok, code, text: code ? `text:${code}` : '', tone: ok ? 'ok' : 'err', ...extra }
}

async function failureOf(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p
  } catch (e) {
    if (e instanceof ApiError) return e
    throw e
  }
  throw new Error('запрос удался, а ждали отказ')
}

afterEach(() => vi.unstubAllGlobals())

describe('services/api — конверт и разбор отказов', () => {
  it('удачный ответ отдаёт data, code, text и tone; запрос same-origin и без следования редиректам', async () => {
    const fetchMock = vi.fn(async () => reply(200, envelope(true, 'ok_set', { data: { name: 'X' } })))
    vi.stubGlobal('fetch', fetchMock)

    const r = await api.get<{ name: string }>('/settings/clinic')

    expect(r).toEqual({ data: { name: 'X' }, code: 'ok_set', text: 'text:ok_set', tone: 'ok' })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/settings/clinic')
    expect(init.method).toBe('GET')
    expect(init.credentials).toBe('same-origin')
    expect(init.redirect).toBe('manual')
  })

  it('POST шлёт JSON-тело с заголовком', async () => {
    const fetchMock = vi.fn(async () => reply(200, envelope(true)))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/settings/clinic', { name: 'A' })

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ name: 'A' }))
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('401 — не вошёл', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(401, envelope(false))))
    const e = await failureOf(api.get('/x'))
    expect(e.failure.kind).toBe('unauthenticated')
    expect(e.text).toBe('')
  })

  it('opaqueredirect (303 на вход у HTML-охраны) — тоже «не вошёл», а не пустой успех', async () => {
    const opaque = { type: 'opaqueredirect', status: 0, ok: false, headers: new Headers() }
    vi.stubGlobal('fetch', vi.fn(async () => opaque as unknown as Response))
    const e = await failureOf(api.get('/x'))
    expect(e.failure.kind).toBe('unauthenticated')
  })

  it('403 — нет права, с кодом и текстом сервера', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(403, envelope(false, 'no_access'))))
    const e = await failureOf(api.get('/x'))
    expect(e.failure).toEqual({ kind: 'forbidden', code: 'no_access', text: 'text:no_access' })
    expect(e.code).toBe('no_access')
    expect(e.text).toBe('text:no_access')
  })

  it('422 — отказ проверки с виновным полем', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(422, envelope(false, 'bad_set', { field: 'name' }))))
    const e = await failureOf(api.post('/x', {}))
    expect(e.failure).toEqual({ kind: 'validation', code: 'bad_set', text: 'text:bad_set', field: 'name' })
    expect(e.field).toBe('name')
  })

  it('422 без поля — field отсутствует, а не undefined', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(422, envelope(false, 'bad_set'))))
    const e = await failureOf(api.post('/x', {}))
    expect(e.failure).toEqual({ kind: 'validation', code: 'bad_set', text: 'text:bad_set' })
    expect(e.field).toBeUndefined()
  })

  it('409 — конфликт', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(409, envelope(false, 'conflict'))))
    const e = await failureOf(api.post('/x', {}))
    expect(e.failure.kind).toBe('conflict')
    expect(e.code).toBe('conflict')
  })

  it('500 текстом (uvicorn, не конверт) — отказ сервера без текста для человека', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(500, 'Internal Server Error', 'text/plain')))
    const e = await failureOf(api.get('/x'))
    expect(e.failure).toEqual({ kind: 'server', status: 500, code: '', text: '' })
  })

  it('500 конвертом (save_err) — текст сервера доезжает', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(500, envelope(false, 'save_err'))))
    const e = await failureOf(api.post('/x', {}))
    expect(e.failure.kind).toBe('server')
    expect(e.text).toBe('text:save_err')
  })

  it('200 без ok=true в конверте — не успех', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, envelope(false, 'bad'))))
    const e = await failureOf(api.get('/x'))
    expect(e.failure.kind).toBe('server')
  })

  it('движок не ответил — отказ сети, без падения', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const e = await failureOf(api.get('/x'))
    expect(e.failure.kind).toBe('network')
  })

  it('loginUrl ведёт на вход движка с возвратом на текущий адрес', () => {
    window.history.pushState({}, '', '/admin/settings/clinic?msg=ok_set')
    expect(loginUrl()).toBe('/admin/login?next=%2Fadmin%2Fsettings%2Fclinic%3Fmsg%3Dok_set')
  })
})
