import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Toast } from './Toast'
import { allowMotion } from '../test/motion'

/* Плашка уходит за ступень (07.11, вторая волна): сперва гаснет классом `out`,
   потом просит родителя её снять. Без движения — сразу, как было. */

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Toast: уход', () => {
  it('без движения крестик снимает плашку сразу', () => {
    const onClose = vi.fn()
    render(<Toast tone="ok" text="Salvat" onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Închide' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('с движением — сперва класс out, родитель — через ступень', () => {
    allowMotion()
    vi.useFakeTimers()
    const onClose = vi.fn()
    render(<Toast tone="ok" text="Salvat" onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Închide' }))
    expect(document.querySelector('.toastbox')?.className).toContain('out')
    expect(onClose).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(300) })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('успех гаснет сам через 6 секунд тем же путём', () => {
    allowMotion()
    vi.useFakeTimers()
    const onClose = vi.fn()
    render(<Toast tone="ok" text="Salvat" onClose={onClose} />)
    act(() => { vi.advanceTimersByTime(6_050) })
    expect(document.querySelector('.toastbox')?.className).toContain('out')
    act(() => { vi.advanceTimersByTime(300) })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('⛔ новый текст на той же плашке отменяет уход прежней', () => {
    allowMotion()
    vi.useFakeTimers()
    const onClose = vi.fn()
    const { rerender } = render(<Toast tone="ok" text="Salvat" onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Închide' }))
    rerender(<Toast tone="err" text="Nu s-a salvat" onClose={onClose} />)
    expect(document.querySelector('.toastbox')?.className).not.toContain('out')
    act(() => { vi.advanceTimersByTime(1_000) })
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByText('Nu s-a salvat')).toBeTruthy()
  })
})
