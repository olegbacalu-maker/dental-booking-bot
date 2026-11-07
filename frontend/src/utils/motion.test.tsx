import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowMotion } from '../test/motion'
import { motionOk, stepMs, useLingering, useOpening } from './motion'

/* Уход за ступень (07.11, вторая волна): значение держится одну ступень после
   того, как ушло, — и только когда система разрешила движение. В jsdom
   `matchMedia` нет вовсе — это и есть «движение выключено», так всё и было. */

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('motionOk / stepMs', () => {
  it('⛔ без matchMedia движения нет; с разрешением системы — есть', () => {
    expect(motionOk()).toBe(false)
    allowMotion()
    expect(motionOk()).toBe(true)
  })

  it('ступень читается из :root, без таблицы — запас по умолчанию', () => {
    expect(stepMs('--dur-fast')).toBe(190)
    expect(stepMs('--dur')).toBe(240)
  })
})

describe('useLingering', () => {
  it('без движения ушедшее значение не держится ни кадра', () => {
    const { result, rerender } = renderHook(({ v }: { v: string | null }) => useLingering(v), { initialProps: { v: 'a' as string | null } })
    expect(result.current).toEqual({ shown: 'a', leaving: false })
    rerender({ v: null })
    expect(result.current).toEqual({ shown: null, leaving: false })
  })

  it('с движением — держится одну ступень с признаком «уходит», потом отпускается', () => {
    allowMotion()
    vi.useFakeTimers()
    const { result, rerender } = renderHook(({ v }: { v: string | null }) => useLingering(v), { initialProps: { v: 'a' as string | null } })
    rerender({ v: null })
    expect(result.current).toEqual({ shown: 'a', leaving: true })
    act(() => { vi.advanceTimersByTime(stepMs('--dur-fast') + 1) })
    expect(result.current).toEqual({ shown: null, leaving: false })
  })

  it('новое значение во время ухода прерывает уход', () => {
    allowMotion()
    vi.useFakeTimers()
    const { result, rerender } = renderHook(({ v }: { v: string | null }) => useLingering(v), { initialProps: { v: 'a' as string | null } })
    rerender({ v: null })
    rerender({ v: 'b' })
    expect(result.current).toEqual({ shown: 'b', leaving: false })
    act(() => { vi.advanceTimersByTime(500) })
    expect(result.current).toEqual({ shown: 'b', leaving: false })
  })
})

describe('useOpening', () => {
  it('держит значение момента открытия, пока ключ тот же; новый ключ — новое значение', () => {
    const { result, rerender } = renderHook(({ k, v }: { k: number | null; v: string }) => useOpening(k, v),
      { initialProps: { k: 1 as number | null, v: 'a' } })
    expect(result.current).toBe('a')
    rerender({ k: 1, v: 'b' })
    expect(result.current).toBe('a')
    rerender({ k: 2, v: 'c' })
    expect(result.current).toBe('c')
    rerender({ k: null, v: 'd' })
    rerender({ k: 1, v: 'e' })
    expect(result.current).toBe('e')
  })
})
