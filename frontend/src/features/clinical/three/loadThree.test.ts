import { afterEach, describe, expect, it, vi } from 'vitest'
import { assetVer, loadThree, resetThree, threeUrl } from './loadThree'

/* three.js по требованию: адрес с версией бандла, один промис на программу,
   отказ не залипает. Сам three сюда не грузится — jsdom без WebGL, да и файл
   появляется только на сборке. */
describe('loadThree', () => {
  afterEach(() => { resetThree(); document.head.innerHTML = '' })

  it('версия — из адреса bundle.js на странице; без бандла — без версии', () => {
    expect(assetVer()).toBe('')
    expect(threeUrl('')).toBe('/static/js/three.js')
    const s = document.createElement('script')
    s.src = '/static/js/bundle.js?v=1.33.0'
    document.head.appendChild(s)
    expect(assetVer()).toBe('1.33.0')
    expect(threeUrl()).toBe('/static/js/three.js?v=1.33.0')
  })

  it('грузится один раз на программу: второй вызов — тот же промис, импорт не повторяется', async () => {
    const fake = { Scene: class {} }
    const importer = vi.fn(() => Promise.resolve(fake))
    const a = loadThree(importer)
    const b = loadThree(importer)
    expect(a).toBe(b)
    expect(await a).toBe(fake)
    expect(importer).toHaveBeenCalledTimes(1)
    expect(importer).toHaveBeenCalledWith('/static/js/three.js')
  })

  it('отказ отдаётся вызывающему и не залипает: следующий вызов пробует снова', async () => {
    const bad = vi.fn(() => Promise.reject(new Error('404')))
    await expect(loadThree(bad)).rejects.toThrow('404')
    const good = vi.fn(() => Promise.resolve({ ok: true }))
    expect(await loadThree(good)).toEqual({ ok: true })
    expect(bad).toHaveBeenCalledTimes(1)
    expect(good).toHaveBeenCalledTimes(1)
  })
})
