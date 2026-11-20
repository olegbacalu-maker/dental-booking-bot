import { act, fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useRef, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowMotion, endTransition as ended } from '../test/motion'
import { stepMs } from '../utils/motion'
import { showDialog, useDialogLeave } from './dialog'

/* Окно, смонтированное условно: хозяин узнаёт о закрытии после перехода окна,
   иначе узел уходит тем же кадром и окно пропадает рывком. В jsdom движения
   нет (`matchMedia` отсутствует) — там хозяин узнаёт сразу. */

function Win({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const { leave, leaving } = useDialogLeave(ref, onClose)
  useEffect(() => { showDialog(ref.current) }, [])
  return (
    <dialog ref={ref} aria-label="proba" data-leaving={leaving} onClose={leave}>
      <button type="button" onClick={leave}>Renunță</button>
      <i data-testid="inner" />
    </dialog>
  )
}

function Host({ spy }: { spy: () => void }) {
  const [open, setOpen] = useState(true)
  return open ? <Win onClose={() => { spy(); setOpen(false) }} /> : <p>fără fereastră</p>
}

const win = () => document.querySelector('dialog')

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('useDialogLeave', () => {
  it('без движения хозяин узнаёт о закрытии сразу', () => {
    const spy = vi.fn()
    render(<Host spy={spy} />)
    expect(win()?.open).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Renunță', hidden: true }))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(win()).toBeNull()
  })

  it('⛔ с движением окно закрыто, но стоит в дереве до конца перехода прозрачности', () => {
    allowMotion()
    const spy = vi.fn()
    render(<Host spy={spy} />)
    fireEvent.click(screen.getByRole('button', { name: 'Renunță', hidden: true }))
    const d = win()!
    expect(d.open).toBe(false)
    expect(d.dataset.leaving).toBe('true')
    expect(spy).not.toHaveBeenCalled()
    /* чужой переход (ребёнок, другое свойство окна) закрытия не завершает */
    ended(screen.getByTestId('inner'), 'opacity')
    ended(d, 'transform')
    expect(spy).not.toHaveBeenCalled()
    ended(d, 'opacity')
    expect(spy).toHaveBeenCalledTimes(1)
    expect(win()).toBeNull()
  })

  it('переход не пришёл (печать, старый движок) — хозяин узнаёт по таймеру ступени, один раз', () => {
    allowMotion()
    vi.useFakeTimers()
    const spy = vi.fn()
    render(<Host spy={spy} />)
    fireEvent.click(screen.getByRole('button', { name: 'Renunță', hidden: true }))
    act(() => { vi.advanceTimersByTime(stepMs('--dur-fast') - 1) })
    expect(spy).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(2) })
    expect(spy).toHaveBeenCalledTimes(1)
    act(() => { vi.advanceTimersByTime(1000) })
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('⛔ срок вышел, а переход ещё идёт (экран занят перерисовкой) — окно ждёт конца перехода, а не срока', async () => {
    allowMotion()
    vi.useFakeTimers()
    const spy = vi.fn()
    render(<Host spy={spy} />)
    const d = win()!
    let end!: () => void
    const finished = new Promise<void>((r) => { end = r })
    Object.defineProperty(d, 'getAnimations', { value: () => [
      { playState: 'running', transitionProperty: 'opacity', finished },
      { playState: 'running', transitionProperty: 'transform', finished: new Promise(() => {}) },
    ] })
    fireEvent.click(screen.getByRole('button', { name: 'Renunță', hidden: true }))
    act(() => { vi.advanceTimersByTime(stepMs('--dur-fast') + 500) })
    expect(spy).not.toHaveBeenCalled()
    expect(win()).not.toBeNull()
    await act(async () => { end(); await finished; await Promise.resolve() })
    expect(spy).toHaveBeenCalledTimes(1)
    expect(win()).toBeNull()
  })

  it('повторный вызов (кнопка и событие close окна) хозяина второй раз не зовёт', () => {
    allowMotion()
    const spy = vi.fn()
    render(<Host spy={spy} />)
    const d = win()!
    fireEvent.click(screen.getByRole('button', { name: 'Renunță', hidden: true }))
    act(() => { d.dispatchEvent(new Event('close')) })
    ended(d, 'opacity')
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('хозяин снял окно сам, пока оно гасло, — таймер снят, хозяина не зовут', () => {
    allowMotion()
    vi.useFakeTimers()
    const spy = vi.fn()
    const { unmount } = render(<Win onClose={spy} />)
    fireEvent.click(screen.getByRole('button', { name: 'Renunță', hidden: true }))
    unmount()
    act(() => { vi.advanceTimersByTime(1000) })
    expect(spy).not.toHaveBeenCalled()
  })
})
