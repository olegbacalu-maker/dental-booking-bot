import { act, fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useRef, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowMotion, endTransition as ended } from '../test/motion'
import { stepMs } from '../utils/motion'
import { noteOrigin, showDialog, useDialogFromOrigin, useDialogLeave } from './dialog'

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

/* Окно, открытое из блока сетки или строки повестки, растёт из него и
   сворачивается в него. jsdom не знает ни раскладки, ни Web Animations: место
   окна и источника подставляются, `animate` — подмена. */
function Card({ open }: { open: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  useDialogFromOrigin(ref, open)
  return <dialog ref={ref} aria-label="vizita" />
}

describe('useDialogFromOrigin', () => {
  const animate = vi.fn()
  function place() {
    for (const [k, v] of Object.entries({ offsetLeft: 400, offsetTop: 100, offsetWidth: 500, offsetHeight: 400 })) {
      Object.defineProperty(HTMLDialogElement.prototype, k, { configurable: true, get: () => v })
    }
    ;(HTMLDialogElement.prototype as { animate?: unknown }).animate = animate
  }
  function tile() {
    const el = document.createElement('div')
    el.getBoundingClientRect = () => ({ left: 100, top: 200, width: 50, height: 20, right: 150, bottom: 220,
      x: 100, y: 200, toJSON: () => ({}) }) as DOMRect
    document.body.appendChild(el)
    return el
  }
  const ONTO = 'translate(-300px, 100px) scale(0.1, 0.05)'

  afterEach(() => {
    animate.mockClear()
    noteOrigin(null)
    for (const k of ['offsetLeft', 'offsetTop', 'offsetWidth', 'offsetHeight', 'animate']) {
      delete (HTMLDialogElement.prototype as unknown as Record<string, unknown>)[k]
    }
    document.body.innerHTML = ''
  })

  it('без движения окно просто открывается и закрывается — ни роста, ни пометки сворачивания', () => {
    place()
    noteOrigin(tile())
    const { rerender } = render(<Card open />)
    const d = win()!
    expect(d.open).toBe(true)
    expect(animate).not.toHaveBeenCalled()
    rerender(<Card open={false} />)
    expect(d.open).toBe(false)
    expect(d.hasAttribute('data-grow')).toBe(false)
  })

  it('⛔ с движением: растёт из названного источника, закрываясь — получает «куда» для перехода CSS', () => {
    allowMotion()
    place()
    noteOrigin(tile())
    const { rerender } = render(<Card open />)
    const d = win()!
    expect(d.open).toBe(true)
    expect(animate).toHaveBeenCalledTimes(1)
    const [frames] = animate.mock.calls[0] as [Keyframe[]]
    expect(frames[0]).toEqual({ transformOrigin: '0 0', transform: ONTO })
    expect(frames[1]).toEqual({ transformOrigin: '0 0', transform: 'none' })
    rerender(<Card open={false} />)
    expect(d.open).toBe(false)
    /* сворачивание ведёт переход окна из panel.css: скрипт пишет только цель */
    expect(d.getAttribute('data-grow')).toBe('')
    expect(d.style.getPropertyValue('--grow-to')).toBe(ONTO)
    expect(animate).toHaveBeenCalledTimes(1)
    /* то же окно открыли снова, уже не из источника: прежняя цель снята */
    rerender(<Card open />)
    expect(d.hasAttribute('data-grow')).toBe(false)
    expect(d.style.getPropertyValue('--grow-to')).toBe('')
    expect(animate).toHaveBeenCalledTimes(1)
    rerender(<Card open={false} />)
    expect(d.hasAttribute('data-grow')).toBe(false)
  })

  it('источник одноразовый и недолгий: окно, открытое позже или вторым, ведёт себя как обычно', () => {
    allowMotion()
    place()
    const now = vi.spyOn(performance, 'now')
    now.mockReturnValue(1000)
    noteOrigin(tile())
    now.mockReturnValue(1000 + 601)
    const late = render(<Card open />)
    expect(animate).not.toHaveBeenCalled()
    late.unmount()
    now.mockReturnValue(5000)
    noteOrigin(tile())
    render(<Card open />)
    expect(animate).toHaveBeenCalledTimes(1)
    render(<Card open />)
    expect(animate).toHaveBeenCalledTimes(1)
  })

  it('источника к закрытию уже нет в дереве (запись отменили) — окно просто гаснет', () => {
    allowMotion()
    place()
    const el = tile()
    noteOrigin(el)
    const { rerender } = render(<Card open />)
    el.remove()
    rerender(<Card open={false} />)
    expect(win()!.hasAttribute('data-grow')).toBe(false)
  })

  it('Esc: окно закрыл сам браузер раньше хозяина — цель сворачивания пишется всё равно', () => {
    allowMotion()
    place()
    noteOrigin(tile())
    const { rerender } = render(<Card open />)
    const d = win()!
    d.removeAttribute('open')
    rerender(<Card open={false} />)
    expect(d.style.getPropertyValue('--grow-to')).toBe(ONTO)
  })

  /* Закрываясь, окно возвращает фокус открывшему, и после Enter или Esc браузер
     рисует на нём рамку клавиатуры. Рамку вправе получить только тот, у кого она
     была до открытия. В jsdom `:focus-visible` не считается — ответ подставлен. */
  function opener(ringed: boolean) {
    const b = document.createElement('button')
    document.body.appendChild(b)
    b.focus()
    const real = b.matches.bind(b)
    b.matches = (sel: string) => (sel === ':focus-visible' ? ringed : real(sel))
    return b
  }

  it('⛔ открыли мышью (рамки на открывшем нет) — фокус с него снят до открытия: возвращать рамку некому', () => {
    const b = opener(false)
    expect(document.activeElement).toBe(b)
    render(<Card open />)
    expect(win()!.open).toBe(true)
    expect(document.activeElement).not.toBe(b)
  })

  it('открыли с клавиатуры (рамка была) — фокус остаётся за открывшим, окно вернёт его туда же', () => {
    const b = opener(true)
    render(<Card open />)
    expect(win()!.open).toBe(true)
    expect(document.activeElement).toBe(b)
  })

  it('окно уже открыто (повторный показ) — фокус внутри окна не трогают', () => {
    const { rerender } = render(<Card open />)
    const d = win()!
    const inner = document.createElement('input')
    d.appendChild(inner)
    inner.focus()
    const real = inner.matches.bind(inner)
    inner.matches = (sel: string) => (sel === ':focus-visible' ? false : real(sel))
    rerender(<Card open />)
    expect(document.activeElement).toBe(inner)
  })
})
