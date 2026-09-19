import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useLive } from './useLive'

/* Ответы канала. Пустое тело — 204 «состояние прежнее». */
function reply(status: number, data: unknown, head: Record<string, string> = {}): Response {
  const headers: Record<string, string> = {
    'X-DP-V': '1.27.0', 'X-DP-Surface': 'react', ...head,
  }
  if (data !== null) headers['content-type'] = 'application/json'
  return new Response(
    data === null ? null : JSON.stringify({ ok: true, code: '', text: '', tone: 'ok', data }),
    { status, headers })
}

const day = (n: number) => ({ live: true, n })

/* ⚠️ Тип мока называется явно: без него `vi.fn(async () => {throw})`
   выводится как Promise<never>, и подмена его на ответ не проходит
   проверку типов. */
type Fetcher = () => Promise<Response>
const init = (f: ReturnType<typeof vi.fn>, i: number) =>
  (f.mock.calls[i] as unknown as [string, RequestInit])[1]

let hidden = false

beforeEach(() => {
  hidden = false
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  // ⚠️ `shouldAdvanceTime` обязателен: `waitFor` из testing-library ждёт на
  // НАСТОЯЩИХ таймерах, и с полностью замороженными часами он не дожидается
  // ничего — все проверки падают по таймауту, хотя хук исправен.
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  // ⛔ `cleanup()` руками: `globals` у vitest в этом проекте не включены, и
  // самоочистка testing-library не регистрируется. Без неё хук ПРОШЛОЙ
  // проверки продолжает опрашивать и бьёт в `fetch` следующей — счётчик
  // запросов врёт, а выглядит это как ошибка в коде хука (19.09).
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const opts = (extra = {}) => ({
  everyMs: 12_000,
  navigate: vi.fn(),
  reload: vi.fn(),
  ...extra,
})

describe('useLive — первая загрузка и опрос ОДНИМ путём', () => {
  it('первый запрос идёт сразу и без отпечатка, следующий — через 12 с и с ним', async () => {
    const f = vi.fn(async () => reply(200, day(1), { 'X-DP-Hash': 'h1' }))
    vi.stubGlobal('fetch', f)

    const o = opts()
    const { result } = renderHook(() => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', o))

    await waitFor(() => expect(result.current.state.status).toBe('ready'))
    expect(result.current.state.data).toEqual(day(1))
    expect(init(f, 0).headers).toBeUndefined()

    f.mockImplementation(async () => reply(200, day(2), { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)
    await waitFor(() => expect(result.current.state.data).toEqual(day(2)))
    expect(init(f, 1).headers).toEqual({ 'X-DP-Hash': 'h1' })
  })

  it('204 не трогает данные и не делает экран «отказавшим»', async () => {
    const f = vi.fn(async () => reply(200, day(1), { 'X-DP-Hash': 'h1' }))
    vi.stubGlobal('fetch', f)
    const { result } = renderHook(() => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', opts()))
    await waitFor(() => expect(result.current.state.status).toBe('ready'))

    f.mockImplementation(async () => reply(204, null, { 'X-DP-Hash': 'h1' }))
    await vi.advanceTimersByTimeAsync(12_000 * 3)

    expect(result.current.state.status).toBe('ready')
    expect(result.current.state.data).toEqual(day(1))
  })

  it('⛔ пока держим — данные не применяются, и ОТПЕЧАТОК не двигается', async () => {
    /* ⭐ Ровно то свойство, на котором держался старый panel.js: отказ
       применить ничего не теряет, потому что следующий запрос уйдёт с ПРЕЖНИМ
       отпечатком и принесёт то же самое. Сдвинь отпечаток здесь — и правка,
       пришедшая во время перетаскивания, пропала бы навсегда.
       ⚠️ Признак ставится СИНХРОННО, рефом, и предикат читает его в момент
       тика: булев проп доехал бы до хука пассивным эффектом, то есть кадром
       позже — для команды длиной в круг по 127.0.0.1 этого кадра достаточно. */
    const f = vi.fn(async () => reply(200, day(1), { 'X-DP-Hash': 'h1' }))
    vi.stubGlobal('fetch', f)
    const held = { now: false }
    const o = { ...opts(), hold: () => held.now }
    const { result } = renderHook(
      () => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', o))
    await waitFor(() => expect(result.current.state.status).toBe('ready'))

    held.now = true
    f.mockImplementation(async () => reply(200, day(2), { 'X-DP-Hash': 'h2' }))
    await vi.advanceTimersByTimeAsync(12_000)

    expect(result.current.state.data).toEqual(day(1))
    expect(init(f, 1).headers).toEqual({ 'X-DP-Hash': 'h1' })

    held.now = false
    await vi.advanceTimersByTimeAsync(12_000)
    await waitFor(() => expect(result.current.state.data).toEqual(day(2)))
  })

  it('⛔ ОПОЗДАВШИЙ опрос не кладёт докомандное состояние поверх свежего', async () => {
    /* Гонка, от которой `hold` не спасает: к моменту беды команда уже
       завершилась.
           тик №2 вылетел  →  команда изменила день  →  refresh() №3 привёз
           новое и применил  →  ответ №2 доставлен со СТАРЫМ состоянием.
       Без защиты визит исчезает с канвы на двенадцать секунд, и регистратура
       записывает второй раз. Номер защищает свежесть СОСТОЯНИЯ, а не порядок
       доставки: номер не больше применённого — выбросить. */
    const gate: Array<(r: Response) => void> = []
    const f = vi.fn<Fetcher>(() => new Promise<Response>((res) => { gate.push(res) }))
    vi.stubGlobal('fetch', f)
    const { result } = renderHook(
      () => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', opts()))

    await waitFor(() => expect(gate.length).toBe(1))
    await act(async () => { gate[0]!(reply(200, day(1), { 'X-DP-Hash': 'h1' })) })
    await waitFor(() => expect(result.current.state.data).toEqual(day(1)))

    /* тик №2 вылетел и завис — это опрос, выпущенный ДО команды */
    await vi.advanceTimersByTimeAsync(12_000)
    await waitFor(() => expect(gate.length).toBe(2))

    /* команда прошла, клиент спрашивает немедленно — тик №3 */
    act(() => { result.current.refresh() })
    await waitFor(() => expect(gate.length).toBe(3))
    await act(async () => { gate[2]!(reply(200, day(2), { 'X-DP-Hash': 'h2' })) })
    await waitFor(() => expect(result.current.state.data).toEqual(day(2)))

    /* и только теперь доезжает №2 — с ДОкомандным состоянием */
    await act(async () => { gate[1]!(reply(200, day(1), { 'X-DP-Hash': 'h1' })) })
    await vi.advanceTimersByTimeAsync(100)

    expect(result.current.state.data).toEqual(day(2))
    /* и отпечаток остался свежим: следующий запрос уйдёт с h2, а не с h1 */
    await vi.advanceTimersByTimeAsync(12_000)
    await waitFor(() => expect(gate.length).toBeGreaterThan(3))
    expect(init(f, f.mock.calls.length - 1).headers).toEqual({ 'X-DP-Hash': 'h2' })
  })

  it('refresh() спрашивает НЕМЕДЛЕННО и отпечатка не трогает', async () => {
    const f = vi.fn(async () => reply(200, day(1), { 'X-DP-Hash': 'h1' }))
    vi.stubGlobal('fetch', f)
    const { result } = renderHook(
      () => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', opts()))
    await waitFor(() => expect(result.current.state.status).toBe('ready'))
    expect(f).toHaveBeenCalledTimes(1)

    act(() => { result.current.refresh() })
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2))
    /* тот же отпечаток, что и был: refresh — ТОТ ЖЕ путь, а не второй */
    expect(init(f, 1).headers).toEqual({ 'X-DP-Hash': 'h1' })
  })

  it('скрытая вкладка не опрашивается, а возврат к ней спрашивает НЕМЕДЛЕННО', async () => {
    /* Журнал висит открытым весь день за другими окнами — это прямая
       экономия у клиники, а не тонкость. */
    const f = vi.fn(async () => reply(200, day(1), { 'X-DP-Hash': 'h1' }))
    vi.stubGlobal('fetch', f)
    const { result } = renderHook(() => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', opts()))
    await waitFor(() => expect(result.current.state.status).toBe('ready'))
    expect(f).toHaveBeenCalledTimes(1)

    hidden = true
    await vi.advanceTimersByTimeAsync(12_000 * 3)
    expect(f).toHaveBeenCalledTimes(1)

    hidden = false
    document.dispatchEvent(new Event('visibilitychange'))
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2))
  })

  it('ЧУЖАЯ ПОВЕРХНОСТЬ перезагружает страницу — и в тихий день тоже', async () => {
    const f = vi.fn(async () => reply(200, day(1), { 'X-DP-Hash': 'h1' }))
    vi.stubGlobal('fetch', f)
    const o = opts()
    const { result } = renderHook(() => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', o))
    await waitFor(() => expect(result.current.state.status).toBe('ready'))

    /* 204: тела нет вовсе, и узнать об откате можно только по заголовку */
    f.mockImplementation(async () => reply(204, null, { 'X-DP-Hash': 'h1', 'X-DP-Surface': 'legacy' }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() => expect(o.reload).toHaveBeenCalledTimes(1))
    /* ⛔ И опрос после этого прекращается: страница уже уходит. */
    await vi.advanceTimersByTimeAsync(12_000 * 3)
    expect(o.reload).toHaveBeenCalledTimes(1)
  })

  it('сессия кончилась → уход на вход, и опрос прекращён', async () => {
    const f = vi.fn(async () => reply(200, day(1), { 'X-DP-Hash': 'h1' }))
    vi.stubGlobal('fetch', f)
    const o = opts()
    const { result } = renderHook(() => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', o))
    await waitFor(() => expect(result.current.state.status).toBe('ready'))

    f.mockImplementation(async () => new Response('{}', { status: 401, headers: { 'content-type': 'application/json' } }))
    await vi.advanceTimersByTimeAsync(12_000)

    await waitFor(() => expect(result.current.state.status).toBe('leaving'))
    expect(o.navigate).toHaveBeenCalledWith(expect.stringContaining('/admin/login?next='))
  })

  it('движок молчит на ПЕРВОЙ загрузке → «не удалось», а дальше — молча', async () => {
    const f = vi.fn<Fetcher>(async () => { throw new TypeError('offline') })
    vi.stubGlobal('fetch', f)
    const { result } = renderHook(() => useLive<{ n: number }>('/schedule/live', 'react', '1.27.0', opts()))

    await waitFor(() => expect(result.current.state.status).toBe('failed'))

    /* данные появились — экран оживает сам, без повтора руками */
    f.mockImplementation(async () => reply(200, day(7), { 'X-DP-Hash': 'h7' }))
    await vi.advanceTimersByTimeAsync(12_000)
    await waitFor(() => expect(result.current.state.data).toEqual(day(7)))
  })

  it('непонятный ответ прекращает опрос и называет причину', async () => {
    vi.stubGlobal('fetch', async () => new Response(
      JSON.stringify({ ok: false, code: '', text: '', tone: 'err', field: 'screen' }),
      { status: 422, headers: { 'content-type': 'application/json' } }))
    const { result } = renderHook(() => useLive('/schedule/live?screen=nope', 'react', '1.27.0', opts()))

    await waitFor(() => expect(result.current.state.status).toBe('stopped'))
    expect(result.current.state.reason).toBe('broken')
  })
})
