import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyHead, assetsOf, readHead, readNode } from './doc'

const parse = (html: string) => new DOMParser().parseFromString(html, 'text/html')

afterEach(() => vi.restoreAllMocks())

describe('readNode', () => {
  it('узел документа: экран, параметры, модель оболочки', () => {
    const doc = parse(`<div id="root" data-screen="schedule_week"
      data-params='{"date":"2026-09-21"}' data-shell='{"frame":{"sub":"s"}}'></div>`)
    const n = readNode(doc.getElementById('root') as HTMLElement)
    expect(n.screen).toBe('schedule_week')
    expect(n.params).toEqual({ date: '2026-09-21' })
    expect(n.shell).toEqual({ frame: { sub: 's' } })
  })

  it('битые параметры — не падение, а пустые параметры и строка в консоли', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    const doc = parse('<div id="root" data-screen="stats" data-params="{oops"></div>')
    const n = readNode(doc.getElementById('root') as HTMLElement)
    expect(n).toEqual({ screen: 'stats', params: {}, shell: null })
    expect(err).toHaveBeenCalled()
  })
})

const DOC = `<!doctype html><html data-style="calm"><head>
<meta name="theme-color" content="#0E9F8A"><title>Clinica — registru</title>
<link rel="stylesheet" href="/static/css/panel.css?v=7"><style>:root{--teal:#0E9F8A}</style>
</head><body><link rel="stylesheet" href="/static/css/bundle.css?v=7">
<script type="module" src="/static/js/bundle.js?v=7"></script></body></html>`

describe('readHead / applyHead', () => {
  it('голова нового адреса ложится в окно: тема, стиль, цвет полосы, заголовок', () => {
    const win = parse(DOC)
    applyHead({ title: 'Nou — registru', style: 'dark', themeColor: '#123456', themeCss: ':root{--teal:#123456}' }, win)
    expect(readHead(win)).toEqual(
      { title: 'Nou — registru', style: 'dark', themeColor: '#123456', themeCss: ':root{--teal:#123456}' })
  })

  it('та же голова — ни одной записи в DOM (переход не трогает то, что не менялось)', () => {
    const win = parse(DOC)
    const css = win.head.querySelector('style') as HTMLStyleElement
    const text = css.firstChild
    applyHead(readHead(parse(DOC)), win)
    expect(css.firstChild).toBe(text)
  })
})

describe('assetsOf', () => {
  it('код документа — адреса стилей и скриптов с ?v=: другая версия видна', () => {
    expect(assetsOf(parse(DOC))).toBe(
      '/static/css/panel.css?v=7 /static/css/bundle.css?v=7 /static/js/bundle.js?v=7')
    expect(assetsOf(parse(DOC.replaceAll('?v=7', '?v=8')))).not.toBe(assetsOf(parse(DOC)))
  })
})
