import { afterEach, describe, expect, it, vi } from 'vitest'
import { FONT_WAIT_MS, fontsFor } from './fonts'

type Load = (font: string, text: string) => Promise<unknown>

/* jsdom не знает FontFaceSet — подставляем ровно то, что зовёт модуль. */
function fakeFonts(load: Load) {
  const fn = vi.fn(load)
  Object.defineProperty(document, 'fonts', { configurable: true, value: { load: fn } })
  return fn
}

/* Обещание ещё не исполнено — после того как отработали все микрозадачи. */
async function pending(p: Promise<unknown>): Promise<boolean> {
  let done = false
  void p.then(() => { done = true })
  for (let i = 0; i < 5; i++) await Promise.resolve()
  return !done
}

afterEach(() => {
  delete (document as { fonts?: unknown }).fonts
  document.body.style.fontFamily = ''
  vi.useRealTimers()
})

describe('fontsFor', () => {
  it('кадр ждёт, пока не приедет файл шрифта', async () => {
    let arrive = () => {}
    fakeFonts(() => new Promise((r) => { arrive = () => r([]) }))
    const p = fontsFor('Ion Popescu')
    expect(await pending(p)).toBe(true)
    arrive()
    await expect(p).resolves.toBeUndefined()
  })

  it('семейство — то, которым пишет body; текст — буквы интерфейса и данные', async () => {
    document.body.style.fontFamily = 'Inter, sans-serif'
    const load = fakeFonts(() => Promise.resolve([]))
    await fontsFor('Иван Петров')
    expect(load).toHaveBeenCalledTimes(1)
    const [font, text] = load.mock.calls[0] ?? ['', '']
    expect(font).toBe('1em Inter, sans-serif')
    /* кириллица имён — подмножество, которого нет в предзагрузке */
    expect(text).toContain('Иван Петров')
    /* румынская диакритика — latin-ext, нужный экрану даже без данных */
    expect(text).toMatch(/[ăîșț]/)
  })

  it(`файл не приехал за ${FONT_WAIT_MS} мс — кадр рисуется без него, а не висит`, async () => {
    vi.useFakeTimers()
    fakeFonts(() => new Promise(() => {}))
    const p = fontsFor('x')
    await vi.advanceTimersByTimeAsync(FONT_WAIT_MS - 1)
    expect(await pending(p)).toBe(true)
    await vi.advanceTimersByTimeAsync(1)
    await expect(p).resolves.toBeUndefined()
  })

  it('отказ файла шрифта — не отказ экрана, и до предела не держит', async () => {
    vi.useFakeTimers()
    fakeFonts(() => Promise.reject(new DOMException('font', 'NetworkError')))
    await expect(fontsFor('x')).resolves.toBeUndefined()
  })

  it('семейство не разобралось (load бросает) — ждать нечего', async () => {
    fakeFonts(() => { throw new DOMException('font', 'SyntaxError') })
    await expect(fontsFor('x')).resolves.toBeUndefined()
  })

  it('без FontFaceSet (jsdom, старый движок) — кадр не ждёт ничего', async () => {
    await expect(fontsFor('x')).resolves.toBeUndefined()
  })
})
