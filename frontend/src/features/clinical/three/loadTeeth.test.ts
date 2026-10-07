import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadTeeth, resetTeeth, teethUrl } from './loadTeeth'

/* Свои модели по требованию — как three.js: адрес с версией бандла, один промис
   на программу, отказ не залипает; битый модуль — отказ, а не пустая сцена. */
describe('loadTeeth', () => {
  afterEach(() => { resetTeeth(); document.head.innerHTML = '' })

  it('адрес рядом с бандлом и с его версией', () => {
    expect(teethUrl('')).toBe('/static/js/teeth.js')
    const s = document.createElement('script')
    s.src = '/static/js/bundle.js?v=1.39.1'
    document.head.appendChild(s)
    expect(teethUrl()).toBe('/static/js/teeth.js?v=1.39.1')
  })

  it('грузится один раз на программу', async () => {
    const set = { SCULPT: { U1: {} }, SCULPT_OF: { 11: 'U1' } }
    const importer = vi.fn(() => Promise.resolve(set))
    const a = loadTeeth(importer)
    expect(loadTeeth(importer)).toBe(a)
    expect(await a).toEqual(set)
    expect(importer).toHaveBeenCalledTimes(1)
    expect(importer).toHaveBeenCalledWith('/static/js/teeth.js')
  })

  it('отказ и битый модуль не залипают: следующий вызов пробует снова', async () => {
    await expect(loadTeeth(() => Promise.reject(new Error('404')))).rejects.toThrow('404')
    await expect(loadTeeth(() => Promise.resolve({ default: 1 }))).rejects.toThrow('SCULPT')
    const good = vi.fn(() => Promise.resolve({ SCULPT: {}, SCULPT_OF: {} }))
    expect(await loadTeeth(good)).toEqual({ SCULPT: {}, SCULPT_OF: {} })
    expect(good).toHaveBeenCalledTimes(1)
  })
})
