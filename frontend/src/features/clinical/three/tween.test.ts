import { describe, expect, it, vi } from 'vitest'
import { createTweens, ease } from './tween'

/* Твины: кадры только пока что-то движется; reduced-motion — мгновенно. */

describe('твины', () => {
  it('ease: концы точные, середина — половина, симметрия', () => {
    expect(ease(0)).toBe(0)
    expect(ease(1)).toBe(1)
    expect(ease(0.5)).toBeCloseTo(0.5, 9)
    expect(ease(0.25) + ease(0.75)).toBeCloseTo(1, 9)
  })

  it('обычный режим: просит кадр, двигает по часам, завершает с done и говорит, занято ли', () => {
    const t = 1000
    const wake = vi.fn()
    const tw = createTweens({ reduced: false, now: () => t, wake })
    const seen: number[] = []
    const done = vi.fn()
    tw.add(200, (k) => seen.push(k), done)
    expect(wake).toHaveBeenCalledTimes(1)
    expect(tw.size).toBe(1)
    expect(tw.step(1100)).toBe(true)
    expect(seen).toEqual([ease(0.5)])
    expect(done).not.toHaveBeenCalled()
    expect(tw.step(1300)).toBe(false)
    expect(seen.at(-1)).toBe(1)
    expect(done).toHaveBeenCalledTimes(1)
    expect(tw.size).toBe(0)
  })

  it('задержка: до t0 не трогает; kill по метке снимает без done', () => {
    let t = 0
    const tw = createTweens({ reduced: false, now: () => t })
    const a = vi.fn()
    const b = vi.fn()
    const doneA = vi.fn()
    tw.add(100, a, doneA, 50, 'jaw')
    tw.add(100, b, null, 0, 'sel')
    expect(tw.step(25)).toBe(true)
    expect(a).not.toHaveBeenCalled()
    expect(b).toHaveBeenCalled()
    tw.kill('jaw')
    expect(tw.size).toBe(1)
    t = 500
    expect(tw.step(500)).toBe(false)
    expect(doneA).not.toHaveBeenCalled()
  })

  it('reduced-motion: fn(1) и done сразу, в очередь ничего не попадает, кадр не просится', () => {
    const wake = vi.fn()
    const tw = createTweens({ reduced: true, wake })
    const fn = vi.fn()
    const done = vi.fn()
    tw.add(900, fn, done, 300, 'x')
    expect(fn).toHaveBeenCalledWith(1)
    expect(done).toHaveBeenCalledTimes(1)
    expect(tw.size).toBe(0)
    expect(wake).not.toHaveBeenCalled()
    expect(tw.step(10 ** 9)).toBe(false)
  })

  it('нулевая длительность — как reduced: мгновенно', () => {
    const tw = createTweens({ reduced: false, now: () => 0 })
    const fn = vi.fn()
    tw.add(0, fn)
    expect(fn).toHaveBeenCalledWith(1)
    expect(tw.size).toBe(0)
  })
})
