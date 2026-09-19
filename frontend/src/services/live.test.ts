import { afterEach, describe, expect, it, vi } from 'vitest'
import { LIVE_MS, nextLive, pollLive, type LiveResult } from './live'

/* Ответы живого канала, какими их строит core/api.live_reply. Фикстуры ТОЛЬКО
   этих проверок: бандл их не видит. */
function reply(status: number, body: unknown, head: Record<string, string> = {}): Response {
  const headers: Record<string, string> = { 'X-DP-V': '1.27.0', ...head }
  if (body !== null) headers['content-type'] = 'application/json'
  return new Response(body === null ? null : JSON.stringify(body), { status, headers })
}

const envelope = (data: unknown) => ({ ok: true, code: '', text: '', tone: 'ok', data })

const SELF = { surface: 'react', version: '1.27.0' }
const ok = <T,>(poll: {
  fresh: boolean; data: T | null; tag?: string; version?: string; surface?: string
}): LiveResult<T> => ({
  kind: 'ok',
  poll: { tag: 'h1', version: '1.27.0', surface: 'react', ...poll },
})

afterEach(() => vi.unstubAllGlobals())

describe('services/live — транспорт: четыре исхода, и ни один не исключение', () => {
  it('200 отдаёт состояние, отпечаток, версию и ПОВЕРХНОСТЬ', async () => {
    const f = vi.fn(async () => reply(200, envelope({ live: true, canvas: 1 }),
      { 'X-DP-Hash': 'abc', 'X-DP-Surface': 'react' }))
    vi.stubGlobal('fetch', f)

    const r = await pollLive<{ live: boolean }>('/schedule/live?date=2026-09-19', '')

    expect(r).toEqual({
      kind: 'ok',
      poll: { fresh: true, data: { live: true, canvas: 1 }, tag: 'abc', version: '1.27.0', surface: 'react' },
    })
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/schedule/live?date=2026-09-19')
    expect(init.credentials).toBe('same-origin')
    expect(init.redirect).toBe('manual')
    expect(init.cache).toBe('no-store')
    /* первый запрос идёт БЕЗ отпечатка: сравнивать серверу не с чем */
    expect(init.headers).toBeUndefined()
  })

  it('204 — это «состояние прежнее», а НЕ отказ, и заголовки на нём те же', async () => {
    /* ⛔ Главная причина, по которой канал не ходит через api.request: там 204
       падает в default: и приезжает как «server 204», то есть ошибка сервера
       на самом частом ответе живого журнала. */
    const f = vi.fn(async () => reply(204, null, { 'X-DP-Hash': 'abc', 'X-DP-Surface': 'react' }))
    vi.stubGlobal('fetch', f)

    const r = await pollLive('/schedule/live', 'abc')

    expect(r).toEqual({
      kind: 'ok',
      poll: { fresh: false, data: null, tag: 'abc', version: '1.27.0', surface: 'react' },
    })
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.headers).toEqual({ 'X-DP-Hash': 'abc' })
  })

  it('401 и редирект на форму входа — один исход: сессия кончилась', async () => {
    vi.stubGlobal('fetch', async () => reply(401, { ok: false, code: '', text: '', tone: 'err' }))
    expect(await pollLive('/schedule/live', '')).toEqual({ kind: 'signout' })

    vi.stubGlobal('fetch', async () => ({ type: 'opaqueredirect', status: 0 } as Response))
    expect(await pollLive('/schedule/live', '')).toEqual({ kind: 'signout' })
  })

  it('молчащая сеть и перезапуск движка — «подождать», а не «сломалось»', async () => {
    vi.stubGlobal('fetch', async () => { throw new TypeError('failed to fetch') })
    expect(await pollLive('/schedule/live', '')).toEqual({ kind: 'offline' })

    vi.stubGlobal('fetch', async () => reply(502, 'Bad Gateway', {}))
    expect(await pollLive('/schedule/live', '')).toEqual({ kind: 'offline' })
  })

  it('ответ, которого клиент не понимает, — это «прекратить», а не «повторять вечно»', async () => {
    vi.stubGlobal('fetch', async () => reply(422, { ok: false, code: '', text: '', tone: 'err', field: 'screen' }))
    expect(await pollLive('/schedule/live?screen=nope', '')).toEqual({ kind: 'broken', status: 422 })
  })

  it('период опроса — то же число, что у старой страницы', () => {
    expect(LIVE_MS).toBe(12_000)
  })
})

describe('services/live — правило: что делать с ответом', () => {
  it('состояние прежнее → ничего не трогаем', () => {
    expect(nextLive(ok({ fresh: false, data: null }), SELF)).toEqual({ do: 'keep' })
  })

  it('новое состояние → применяем ВМЕСТЕ с отпечатком', () => {
    expect(nextLive(ok({ fresh: true, data: { live: true }, tag: 'h2' }), SELF))
      .toEqual({ do: 'apply', data: { live: true }, tag: 'h2' })
  })

  it('чужая версия → полная перезагрузка, а не вклеивание в старый код', () => {
    expect(nextLive(ok({ fresh: true, data: { live: true }, version: '1.28.0' }), SELF))
      .toEqual({ do: 'reload', why: 'version' })
  })

  it('ЧУЖАЯ ПОВЕРХНОСТЬ → перезагрузка: это вторая половина отката', () => {
    /* ⭐ Директор выключил флаг; сервер отдаёт по адресу старую страницу.
       Узнать об этом открытая React-вкладка может только отсюда. */
    expect(nextLive(ok({ fresh: true, data: { live: true }, surface: 'legacy' }), SELF))
      .toEqual({ do: 'reload', why: 'surface' })
  })

  it('и узнаёт даже в ТИХИЙ день, когда тела нет вовсе', () => {
    /* ⛔ Ровно ради этого поверхность едет заголовком, а не полем data: на 204
       поля не приехало бы никогда. */
    expect(nextLive(ok({ fresh: false, data: null, surface: 'legacy' }), SELF))
      .toEqual({ do: 'reload', why: 'surface' })
  })

  it('пока человек тащит — не применяем, и отпечаток НЕ двигаем', () => {
    /* ⭐ Свойство старого panel.js, перенесённое буквально: отказ применить
       ничего не теряет ровно потому, что отпечаток остаётся прежним, и
       следующий тик принесёт то же самое. */
    const res = ok({ fresh: true, data: { live: true }, tag: 'h2' })
    expect(nextLive(res, SELF, true)).toEqual({ do: 'keep' })
    expect(nextLive(res, SELF, false)).toEqual({ do: 'apply', data: { live: true }, tag: 'h2' })
  })

  it('держим — сильнее перезагрузки: страницу не выдёргивают из-под мыши', () => {
    expect(nextLive(ok({ fresh: true, data: { live: true }, surface: 'legacy' }), SELF, true))
      .toEqual({ do: 'keep' })
  })

  it('сессия кончилась → уходим на вход', () => {
    expect(nextLive({ kind: 'signout' }, SELF)).toEqual({ do: 'leave' })
  })

  it('связи нет → молчим', () => {
    expect(nextLive({ kind: 'offline' }, SELF)).toEqual({ do: 'keep' })
  })

  it('непонятный ответ → опрос прекращаем СЛОВОМ, а не молчанием', () => {
    expect(nextLive({ kind: 'broken', status: 422 }, SELF)).toEqual({ do: 'stop', why: 'broken' })
  })

  it('live:false → тоже прекращаем: молчащий экран неотличим от работающего', () => {
    /* ⚠️ По проводу сегодня недостижимо (C26.5.2), ветка оставлена явной. */
    expect(nextLive(ok({ fresh: true, data: { live: false } }), SELF))
      .toEqual({ do: 'stop', why: 'not-live' })
  })

  it('пустая версия у одной из сторон перезагрузку НЕ вызывает', () => {
    /* ⚠️ Иначе страница, отданная без data-v, перезагружалась бы вечно. */
    expect(nextLive(ok({ fresh: false, data: null, version: '' }), SELF)).toEqual({ do: 'keep' })
    expect(nextLive(ok({ fresh: false, data: null }), { surface: 'react', version: '' }))
      .toEqual({ do: 'keep' })
  })
})
