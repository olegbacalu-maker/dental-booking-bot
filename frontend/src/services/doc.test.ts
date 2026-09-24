import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchDoc } from './doc'

const parse = (html: string) => new DOMParser().parseFromString(html, 'text/html')

const ROOT = `<div id="root" data-screen="schedule_week" data-params='{"date":"2026-09-21"}'
  data-shell='{"frame":{"sub":"calendar săptămânal"}}'><p class="hint">Interfața nouă nu s-a încărcat.</p></div>`

/** Документ React-страницы, как его печатает `layout.react_shell`. */
const page = (v = 7, root = ROOT) => `<!doctype html><html lang="ro" data-style="calm"><head>
<meta name="theme-color" content="#0E9F8A"><title>Clinica — registru</title>
<link rel="stylesheet" href="/static/css/panel.css?v=${v}"><style>:root{--teal:#0E9F8A}</style>
</head><body data-v="1.30.0"><link rel="stylesheet" href="/static/css/bundle.css?v=${v}">
${root}<script type="module" src="/static/js/bundle.js?v=${v}"></script></body></html>`

/** Окно, из которого идёт переход: тот же бандл, что у `page()`. */
const HERE = parse(page())

const URL_ = 'http://x/admin/week?date=2026-09-21'

function answer(body: string, over: Record<string, unknown> = {}) {
  const res = { ok: true, status: 200, redirected: false, url: URL_, text: () => Promise.resolve(body), ...over }
  const fetch = vi.fn().mockResolvedValue(res)
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const go = () => fetchDoc(URL_, new AbortController().signal, HERE)

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('fetchDoc', () => {
  it('React-страница того же бандла: узел нового адреса и его голова', async () => {
    const fetch = answer(page())
    const a = await go()
    expect(a).toEqual({
      kind: 'page',
      node: {
        screen: 'schedule_week',
        params: { date: '2026-09-21' },
        shell: { frame: { sub: 'calendar săptămânal' } },
        head: { title: 'Clinica — registru', style: 'calm', themeColor: '#0E9F8A', themeCss: ':root{--teal:#0E9F8A}' },
      },
    })
    /* Тот же адрес, что открыл бы F5; кука своя; кеш — никогда: модель живая. */
    expect(fetch).toHaveBeenCalledWith(URL_, expect.objectContaining(
      { credentials: 'same-origin', cache: 'no-store', signal: expect.any(AbortSignal) }))
  })

  it('сервер увёл редиректом (вход, нет права) — туда же документом', async () => {
    answer('<html>login</html>', { redirected: true, url: 'http://x/admin/login?next=%2Fadmin%2Fweek' })
    expect(await go()).toEqual({ kind: 'leave', url: 'http://x/admin/login?next=%2Fadmin%2Fweek' })
  })

  it('по адресу старая страница (узла нет) — документом: её рисует сервер', async () => {
    answer('<!doctype html><html><body><aside class="side"></aside><div id="live"></div></body></html>')
    expect(await go()).toEqual({ kind: 'leave', url: URL_ })
  })

  it('узел без модели оболочки — документом: каркас печатает сервер', async () => {
    answer(page(7, '<div id="root" data-screen="schedule_week"></div>'))
    expect(await go()).toEqual({ kind: 'leave', url: URL_ })
  })

  it('другой код (exe обновили под вкладкой) — документом, иначе старый бандл жил бы до F5', async () => {
    answer(page(8))
    expect(await go()).toEqual({ kind: 'leave', url: URL_ })
  })

  it('ответ не 200 — документом: окно покажет то же, что показало бы сегодня', async () => {
    answer('Internal Server Error', { ok: false, status: 500 })
    expect(await go()).toEqual({ kind: 'leave', url: URL_ })
  })

  it('движок не ответил — документом, а не молча прежний кадр', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    expect(await go()).toEqual({ kind: 'leave', url: URL_ })
  })

  it('переход перебит следующим — ответа нет вовсе: уводить с того, куда нажали последним, нельзя', async () => {
    const ctl = new AbortController()
    vi.stubGlobal('fetch', vi.fn(() => { ctl.abort(); return Promise.reject(new DOMException('x', 'AbortError')) }))
    await expect(fetchDoc(URL_, ctl.signal, HERE)).rejects.toThrow()
  })
})
